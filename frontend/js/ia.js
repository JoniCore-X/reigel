'use strict';

// /ia: owner-scoped conversation workspace. Text is inserted with textContent only.
(() => {
  const shell = document.querySelector('#ia-shell');
  if (!shell) return;
  const find = id => document.getElementById(id);
  const thread = find('ia-thread');
  const empty = find('ia-empty');
  const scroll = find('ia-scroll');
  const form = find('ia-form');
  const input = find('ia-text');
  const sendButton = find('ia-send');
  const sendLabel = find('ia-send-label');
  const notice = find('ia-notice');
  const counter = find('ia-counter');
  const historyList = find('ia-history');
  const state = {
    owner: null, conversations: [], activeId: null, messages: [],
    streaming: false, controller: null, modelReady: false,
    // Suggestions already shown in this conversation (sent to the engine to avoid repeats).
    sending: false, seen: [], seenFor: undefined,
    // Incremented whenever the visible conversation changes. A response or a
    // reply that belongs to an earlier view only updates the history list.
    view: 0,
    search: '',
  };
  const nextView = () => ++state.view;

  const DATE = new Intl.DateTimeFormat('es-PR', {
    timeZone: 'America/Puerto_Rico', day: 'numeric', month: 'short',
    hour: 'numeric', minute: '2-digit',
  });
  const dateLabel = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : DATE.format(date);
  };
  const isMobile = () => matchMedia('(max-width: 900px)').matches;
  const nearEnd = () => scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120;
  const scrollToEnd = () => { scroll.scrollTop = scroll.scrollHeight; };

  async function request(path, { method = 'GET', body, timeout = 20000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : 'No pudimos completar la solicitud.');
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('La operación tardó demasiado. Inténtalo de nuevo.');
      if (error instanceof TypeError) throw new Error('No hay conexión con el servidor.');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function showNotice(message, { retry = false } = {}) {
    notice.replaceChildren();
    const text = document.createElement('span');
    text.textContent = message;
    notice.append(text);
    if (retry) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Reintentar';
      button.addEventListener('click', () => boot(), { once: true });
      notice.append(button);
    }
    notice.hidden = false;
  }

  function hideNotice() {
    notice.hidden = true;
    notice.replaceChildren();
  }

  function setComposerEnabled(enabled) {
    input.disabled = !enabled;
    sendButton.disabled = !enabled;
  }

  function setStreaming(value) {
    state.streaming = value;
    thread.setAttribute('aria-busy', String(value));
    sendLabel.textContent = value ? 'Detener' : 'Enviar';
    sendButton.classList.toggle('is-stop', value);
    sendButton.setAttribute('aria-label', value ? 'Detener la respuesta' : 'Enviar mensaje');
    input.disabled = value || !state.modelReady;
    if (!value) {
      sendButton.disabled = !state.modelReady;
      input.focus();
    } else {
      sendButton.disabled = !state.modelReady;
    }
    if (!menu.hidden) syncMenu();
  }

  function setSidebar(open) {
    shell.dataset.sidebar = open ? 'open' : 'closed';
    const menu = find('ia-menu');
    const collapse = find('ia-collapse');
    const scrim = find('ia-scrim');
    menu.hidden = open;
    menu.setAttribute('aria-expanded', String(open));
    collapse.setAttribute('aria-expanded', String(open));
    scrim.hidden = !open || !isMobile();
    find('ia-sidebar').inert = !open;
  }

  function setupSidebar() {
    setSidebar(!isMobile());
    find('ia-collapse').addEventListener('click', () => setSidebar(false));
    find('ia-menu').addEventListener('click', () => setSidebar(true));
    find('ia-scrim').addEventListener('click', () => setSidebar(false));
    const query = matchMedia('(max-width: 900px)');
    const sync = () => setSidebar(!query.matches);
    if (query.addEventListener) query.addEventListener('change', sync);
    else query.addListener(sync);
  }

  function upsertConversation(summary) {
    if (!summary || !summary.id) return;
    const existing = state.conversations.find(item => item.id === summary.id);
    if (existing) Object.assign(existing, summary);
    else state.conversations.unshift({ ...summary });
    state.conversations.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
  }

  function smallButton(label, className, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
  }

  // One history row: open the conversation, or manage it (rename / delete).
  function historyItem(item) {
    const row = document.createElement('div');
    row.className = 'ia-history-item';
    row.dataset.id = item.id;
    const label = item.title || 'Nueva conversación';

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'ia-history-open';
    open.setAttribute('aria-current', String(item.id === state.activeId));
    const title = document.createElement('strong');
    title.textContent = label;
    const date = document.createElement('small');
    date.textContent = dateLabel(item.updated_at);
    open.append(title, date);
    open.addEventListener('click', () => {
      if (state.streaming) state.controller?.abort();
      selectConversation(item.id);
      if (isMobile()) setSidebar(false);
    });

    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'ia-history-more';
    more.textContent = '⋯';
    more.setAttribute('aria-label', `Opciones de «${label}»`);
    more.setAttribute('aria-expanded', 'false');

    const actions = document.createElement('div');
    actions.className = 'ia-history-actions';
    actions.hidden = true;
    const showActions = (...buttons) => {
      actions.replaceChildren(...buttons);
      actions.hidden = false;
      more.setAttribute('aria-expanded', 'true');
      buttons[0]?.focus();
    };
    const closeActions = () => {
      actions.hidden = true;
      actions.replaceChildren();
      more.setAttribute('aria-expanded', 'false');
    };
    const menuButtons = () => [
      smallButton('Renombrar', 'ia-history-action', () => startRename(row, item, closeActions)),
      smallButton('Eliminar', 'ia-history-action is-danger', () => showActions(
        smallButton('Eliminar definitivamente', 'ia-history-action is-danger', () => removeConversation(item)),
        smallButton('Cancelar', 'ia-history-action', () => { closeActions(); more.focus(); }),
      )),
    ];
    more.addEventListener('click', () => (actions.hidden ? showActions(...menuButtons()) : closeActions()));
    row.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !actions.hidden) { closeActions(); more.focus(); }
    });
    row.append(open, more, actions);
    return row;
  }

  function startRename(row, item, done) {
    done();
    const open = row.querySelector('.ia-history-open');
    const field = document.createElement('input');
    field.type = 'text';
    field.className = 'ia-history-rename';
    field.maxLength = 80;
    field.value = item.title || '';
    field.setAttribute('aria-label', 'Nuevo título de la conversación');
    open.hidden = true;
    row.insertBefore(field, open);
    field.focus();
    field.select?.();
    let finished = false;
    const finish = async save => {
      if (finished) return;
      finished = true;
      const value = field.value.trim();
      if (save && value && value !== item.title) {
        try {
          const data = await request(`/api/ia/conversations/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { title: value } });
          upsertConversation(data.conversation);
        } catch (error) {
          showNotice(error.message);
        }
      }
      renderHistory();
    };
    field.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    field.addEventListener('blur', () => finish(true));
  }

  async function removeConversation(item) {
    try {
      await request(`/api/ia/conversations/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
    } catch (error) {
      showNotice(error.message);
      return;
    }
    state.conversations = state.conversations.filter(entry => entry.id !== item.id);
    if (item.id === state.activeId) {
      nextView();
      state.activeId = null;
      state.messages = [];
      renderMessages();
    }
    renderHistory();
    showNotice('Conversación eliminada.');
  }

  function renderHistory() {
    historyList.replaceChildren();
    state.conversations.forEach(item => historyList.append(historyItem(item)));
    const emptyNote = find('ia-history-empty');
    emptyNote.hidden = state.conversations.length > 0;
    emptyNote.textContent = state.search ? 'Sin resultados para esta búsqueda.' : 'Aún no hay conversaciones guardadas.';
  }

  // Search titles and messages on the server; the newest answer wins.
  let searchTimer = null;
  let searchSeq = 0;
  async function runSearch(value) {
    const seq = ++searchSeq;
    state.search = value.trim();
    try {
      const query = state.search ? `?q=${encodeURIComponent(state.search)}` : '';
      const data = await request(`/api/ia/conversations${query}`);
      if (seq !== searchSeq) return;
      state.conversations = Array.isArray(data.conversations) ? data.conversations : [];
      renderHistory();
    } catch (error) {
      if (seq === searchSeq) showNotice(error.message);
    }
  }

  function stateNote(message) {
    if (message.status === 'stopped' && !message.content) {
      return 'Respuesta detenida antes de empezar.';
    }
    return {
      stopped: 'Respuesta detenida antes de completarse.',
      error: 'La respuesta se interrumpió por un error.',
      rejected: 'Respuesta retirada por seguridad; se muestra una alternativa.',
      streaming: 'Respuesta incompleta.',
    }[message.status] || '';
  }

  function messageNode(message) {
    const article = document.createElement('article');
    article.className = `ia-msg ia-msg--${message.role === 'user' ? 'user' : 'assistant'}`;
    article.dataset.id = message.id;
    article.dataset.role = message.role;
    if (message.role !== 'user') {
      const avatar = document.createElement('img');
      avatar.className = 'ia-msg-avatar';
      avatar.src = '/static/assets/power-solar/reigel-logo.png';
      avatar.alt = 'R.E.I.G.E.L.';
      avatar.width = 26;
      avatar.height = 26;
      article.append(avatar);
    }
    const body = document.createElement('div');
    body.className = 'ia-msg-body';
    if (message.status === 'streaming') body.classList.add('is-streaming');
    body.textContent = message.content || '';
    article.append(body);
    const note = document.createElement('p');
    note.className = 'ia-msg-state';
    note.hidden = true;
    const text = stateNote(message);
    if (text) {
      note.textContent = text;
      note.dataset.state = message.status;
      note.hidden = false;
    }
    article.append(note);
    return article;
  }

  function renderMessages() {
    thread.replaceChildren();
    if (!state.messages.length) {
      empty.hidden = false;
      thread.append(empty);
      loadSuggestions();
      return;
    }
    state.messages.forEach(message => {
      thread.append(messageNode(message));
    });
    scrollToEnd();
    loadSuggestions();
  }

  function removeFollowups() {
    thread.querySelectorAll?.('.ia-followups').forEach(node => node.remove());
  }

  // Six suggestions chosen by the server (reigel/suggestions.py) from the visitor's
  // own conversation. They are optional: if the request fails, nothing is shown.
  async function loadSuggestions() {
    const view = state.view;
    if (state.seenFor !== state.activeId) {
      state.seen = [];
      state.seenFor = state.activeId;
    }
    const params = new URLSearchParams();
    if (state.activeId) params.set('conversation_id', state.activeId);
    if (state.seen.length) params.set('seen', state.seen.slice(-60).join(','));
    let data;
    try {
      data = await request(`/api/ia/suggestions?${params}`);
    } catch {
      return;
    }
    if (view !== state.view || state.streaming || state.sending) return;
    const items = Array.isArray(data?.suggestions) ? data.suggestions : [];
    if (!items.length) return;
    state.seen.push(...items.map(item => item.id));
    const buttons = items.map(item => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ia-suggestion';
      button.dataset.iaPrompt = item.text;
      button.dataset.suggestionId = item.id;
      button.textContent = item.text;
      return button;
    });
    if (!state.messages.length) {
      empty.querySelector('.ia-prompts')?.replaceChildren(...buttons);
      return;
    }
    removeFollowups();
    const row = document.createElement('div');
    row.className = 'ia-followups';
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', 'Preguntas sugeridas');
    row.append(...buttons);
    thread.append(row);
    if (nearEnd()) scrollToEnd();
  }

  function appendUser(text) {
    const message = {
      id: `local-${Date.now()}`, role: 'user', content: text,
      status: 'complete', created_at: new Date().toISOString(),
    };
    state.messages.push(message);
    if (thread.contains(empty)) thread.replaceChildren();
    thread.append(messageNode(message));
    scrollToEnd();
  }

  // Sol de Power Solar en la punta del texto mientras se genera: los rayos giran
  // como un engranaje y el rayo eléctrico queda quieto (decorativo).
  const SUN_SVG = '<svg viewBox="0 0 100 100" focusable="false" aria-hidden="true">'
    + '<path class="ia-sun-rays" d="M44.7 16.4L50.0 1.0L55.3 16.4ZM62.2 18.3L74.5 7.6L71.4 23.6ZM76.4 28.6L92.4 25.5L81.7 37.8ZM83.6 44.7L99.0 50.0L83.6 55.3ZM81.7 62.2L92.4 74.5L76.4 71.4ZM71.4 76.4L74.5 92.4L62.2 81.7ZM55.3 83.6L50.0 99.0L44.7 83.6ZM37.8 81.7L25.5 92.4L28.6 76.4ZM23.6 71.4L7.6 74.5L18.3 62.2ZM16.4 55.3L1.0 50.0L16.4 44.7ZM18.3 37.8L7.6 25.5L23.6 28.6ZM28.6 23.6L25.5 7.6L37.8 18.3Z"/>'
    + '<circle class="ia-sun-ring" cx="50" cy="50" r="34"/><circle class="ia-sun-core" cx="50" cy="50" r="26"/>'
    + '<path class="ia-sun-bolt" d="M56 27 41 54h10l-5 21 16-29H51l5-19Z"/></svg>';

  function sunCursor() {
    const sun = document.createElement('span');
    sun.className = 'ia-sun';
    sun.setAttribute('aria-hidden', 'true');
    sun.innerHTML = SUN_SVG;
    return sun;
  }

  // Revela el texto ya validado por el servidor de forma suave: avanza a ritmo
  // constante por palabras completas y acelera si el modelo va más rápido, para
  // no quedarse atrás. Sin animación (movimiento reducido, pestaña oculta o un
  // entorno sin requestAnimationFrame) muestra el texto de inmediato.
  function createRevealer(body) {
    const animate = typeof requestAnimationFrame === 'function'
      && !(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
    const cursor = sunCursor();
    let target = '';
    let shown = 0;
    let frame = 0;
    let last = 0;
    const waiters = [];
    body.replaceChildren(cursor);
    const hidden = () => typeof document.hidden === 'boolean' && document.hidden;
    const release = () => { if (shown >= target.length) waiters.splice(0).forEach(resolve => resolve()); };
    function insert(text, fresh) {
      if (!text) return;
      const node = fresh ? document.createElement('span') : document.createTextNode(text);
      if (fresh) { node.className = 'ia-word'; node.textContent = text; }
      body.insertBefore(node, cursor);
    }
    function flush() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      if (!animate) {
        body.textContent = target;
        body.append(cursor);
      } else {
        insert(target.slice(shown), false);
      }
      shown = target.length;
      release();
    }
    function step(now) {
      frame = 0;
      const elapsed = last ? Math.min(now - last, 100) : 16;
      last = now;
      const backlog = target.length - shown;
      if (backlog <= 0) { last = 0; release(); return; }
      const perSecond = Math.max(60, backlog * 3);
      let next = Math.min(target.length, shown + Math.max(1, Math.round(perSecond * elapsed / 1000)));
      const space = target.slice(next).search(/\s/);
      if (space > 0 && space < 20) next += space;
      insert(target.slice(shown, next), true);
      shown = next;
      if (nearEnd()) scrollToEnd();
      frame = requestAnimationFrame(step);
    }
    return {
      push(text) {
        target += text;
        if (!animate || hidden()) { flush(); return; }
        if (!frame) frame = requestAnimationFrame(step);
      },
      finished() {
        if (!animate || hidden() || shown >= target.length) { flush(); return Promise.resolve(); }
        return new Promise(resolve => { waiters.push(resolve); setTimeout(flush, 6000); });
      },
      stop() { if (frame) cancelAnimationFrame(frame); frame = 0; },
    };
  }

  function appendAssistant() {
    const node = messageNode({ id: 'pending', role: 'assistant', content: '', status: 'streaming' });
    const waiting = document.createElement('span');
    waiting.className = 'ia-waiting';
    waiting.setAttribute('role', 'status');
    waiting.setAttribute('aria-label', 'R.E.I.G.E.L. está preparando la respuesta');
    waiting.append(sunCursor());
    node.querySelector('.ia-msg-body').append(waiting);
    // «Respuesta incompleta» describes a saved reply left unfinished, not one being written now.
    node.querySelector('.ia-msg-state').hidden = true;
    thread.append(node);
    scrollToEnd();
    return node;
  }

  function finalize(node, message) {
    if (!node) return;
    if (!message) {
      node.remove();
      return;
    }
    node.dataset.id = message.id;
    node.classList.remove('ia-msg--streaming');
    const body = node.querySelector('.ia-msg-body');
    body.classList.remove('is-streaming');
    body.textContent = message.content || '';
    const note = node.querySelector('.ia-msg-state');
    const text = stateNote(message);
    note.hidden = !text;
    if (text) {
      note.textContent = text;
      note.dataset.state = message.status;
    }
    const index = state.messages.findIndex(item => item.id === message.id);
    if (index >= 0) state.messages[index] = message;
    else state.messages.push(message);
  }

  function applyModel(model) {
    state.modelReady = Boolean(model && model.enabled && model.status === 'available');
    setComposerEnabled(state.modelReady);
    if (state.modelReady) {
      if (state.pendingQuery) autoSendPending();
      return;
    }
    const reasons = {
      disabled: 'La IA local no está activada en este servidor. Puedes consultar el historial guardado.',
      model_missing: `El modelo local ${model?.model || ''} no está instalado en Ollama. El equipo debe instalarlo.`.replace('  ', ' '),
      unavailable: 'Ollama no responde en este equipo. Verifica que esté en ejecución y reintenta la conexión.',
    };
    state.modelMessage = reasons[model?.status] || 'La IA local no está disponible en este momento.';
    showNotice(state.modelMessage, { retry: true });
  }

  function restoreModelNotice() {
    if (!state.modelReady && state.modelMessage && notice.hidden) {
      showNotice(state.modelMessage, { retry: true });
    }
  }

  function applyOwner(data) {
    if (data.owner === 'user') {
      find('ia-owner').textContent = `Historial de ${data.user?.name || 'tu cuenta'}`;
      find('ia-retention').textContent = 'Las conversaciones quedan guardadas en tu cuenta del equipo.';
    } else {
      find('ia-owner').textContent = 'Sesión temporal de visitante';
      find('ia-retention').textContent = `Las conversaciones se conservan ${data.retention_days || 7} días desde la última actividad.`;
    }
    applyBackLink();
  }

  function applyBackLink() {
    const link = find('ia-back');
    try {
      const origin = location.origin;
      const own = new Set(['/', '/ia', '/chat']);
      if (document.referrer) {
        const target = new URL(document.referrer);
        if (target.origin === origin && target.pathname !== location.pathname && !own.has(target.pathname)) link.href = target.href;
      }
    } catch { /* Keep the default destination. */ }
  }

  async function selectConversation(id) {
    const view = nextView();
    hideNotice();
    try {
      const data = await request(`/api/ia/conversations/${encodeURIComponent(id)}`);
      if (view !== state.view) return;
      state.activeId = data.conversation.id;
      state.messages = Array.isArray(data.messages) ? data.messages : [];
      upsertConversation(data.conversation);
      renderHistory();
      renderMessages();
      if (isMobile()) setSidebar(false);
      restoreModelNotice();
    } catch (error) {
      if (view === state.view) showNotice(error.message, { retry: true });
    }
  }

  async function newConversation() {
    if (state.streaming) state.controller?.abort();
    const view = nextView();
    hideNotice();
    try {
      const data = await request('/api/ia/conversations', { method: 'POST', body: {} });
      if (view !== state.view) return;
      state.activeId = data.conversation.id;
      state.messages = [];
      upsertConversation(data.conversation);
      renderHistory();
      renderMessages();
      if (isMobile()) setSidebar(false);
      if (state.modelReady) input.focus();
      restoreModelNotice();
    } catch (error) {
      if (view === state.view) showNotice(error.message, { retry: true });
    }
  }

  function dispatchBlock(block, handlers) {
    let event = 'message';
    const data = [];
    block.split(/\r?\n/).forEach(line => {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^\s/, ''));
    });
    if (!data.length) return;
    let parsed;
    try { parsed = JSON.parse(data.join('\n')); } catch { return; }
    if (typeof handlers[event] === 'function') handlers[event](parsed);
  }

  async function stream(path, body, handlers) {
    const controller = new AbortController();
    state.controller = controller;
    let response;
    try {
      response = await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('No hay conexión con el servidor.');
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'No se pudo iniciar la respuesta.');
      error.status = response.status;
      throw error;
    }
    if (!response.body) throw new Error('El navegador no puede leer la respuesta en partes.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finished = false;
    const settle = handlers => {
      const wrapped = {};
      Object.entries(handlers).forEach(([name, callback]) => {
        wrapped[name] = data => {
          if (name === 'done' || name === 'replace' || name === 'error') finished = true;
          callback(data);
        };
      });
      return wrapped;
    };
    const safe = settle(handlers);
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let match = buffer.match(/\r?\n\r?\n/);
      while (match && match.index !== undefined) {
        dispatchBlock(buffer.slice(0, match.index), safe);
        buffer = buffer.slice(match.index + match[0].length);
        match = buffer.match(/\r?\n\r?\n/);
      }
    }
    if (!finished) throw new Error('La conexión se interrumpió antes de completar la respuesta.');
  }

  function isAbort(error) {
    return error && (error.name === 'AbortError' || error.code === 20);
  }

  async function send() {
    if (state.sending) return;
    state.sending = true;
    try {
      await sendNow();
    } finally {
      state.sending = false;
    }
  }

  async function sendNow() {
    const value = input.value.trim();
    if (!value || state.streaming || !state.modelReady) return;
    hideNotice();
    if (!state.activeId) {
      const creating = nextView();
      try {
        const created = await request('/api/ia/conversations', { method: 'POST', body: {} });
        // The visitor opened another conversation meanwhile: keep the text in the field.
        if (creating !== state.view) return;
        state.activeId = created.conversation.id;
        state.messages = [];
        upsertConversation(created.conversation);
        renderHistory();
      } catch (error) {
        showNotice(error.message, { retry: true });
        return;
      }
    }
    input.value = '';
    resizeInput();
    removeFollowups();
    appendUser(value);
    const pending = appendAssistant();
    let content = '';
    let reveal = null;
    // This reply belongs to the conversation visible now. If the visitor opens
    // another one, the server still stores the reply, but it no longer touches
    // the visible thread, its messages or its notices.
    const view = state.view;
    const conversationId = state.activeId;
    const visible = () => view === state.view;
    setStreaming(true);
    try {
      await stream(`/api/ia/conversations/${encodeURIComponent(conversationId)}/messages`, { text: value }, {
        meta: data => {
          pending.dataset.id = data.assistant_id;
          upsertConversation(data.conversation);
          renderHistory();
        },
        delta: data => {
          if (!visible()) return;
          if (!reveal) reveal = createRevealer(pending.querySelector('.ia-msg-body'));
          content += data.text;
          reveal.push(data.text);
          if (nearEnd()) scrollToEnd();
        },
        done: async data => {
          upsertConversation(data.conversation);
          renderHistory();
          if (!visible()) return;
          // The last words finish appearing before the message settles.
          if (reveal) await reveal.finished();
          if (visible()) {
            finalize(pending, data.assistant);
            loadSuggestions();
          }
        },
        replace: data => {
          if (!visible()) return;
          reveal?.stop();
          finalize(pending, data.assistant);
          showNotice(data.detail);
        },
        error: data => {
          if (!visible()) return;
          reveal?.stop();
          if (data.assistant) finalize(pending, data.assistant);
          else {
            pending.remove();
            input.value = value;
            resizeInput();
          }
          showNotice(data.detail, { retry: true });
        },
      });
    } catch (error) {
      reveal?.stop();
      if (!visible()) {
        // Stopped because the visitor left this conversation; nothing to show.
      } else if (isAbort(error)) {
        if (pending.dataset.id !== 'pending') {
          finalize(pending, {
            id: pending.dataset.id, role: 'assistant', content, status: 'stopped',
          });
        } else {
          pending.remove();
        }
        showNotice(content ? 'Respuesta detenida.' : 'Respuesta detenida antes de empezar.');
      } else {
        if (content) {
          finalize(pending, {
            id: pending.dataset.id, role: 'assistant', content, status: 'error',
          });
        } else {
          pending.remove();
          input.value = value;
          resizeInput();
        }
        showNotice(error.message, { retry: true });
      }
    } finally {
      state.controller = null;
      setStreaming(false);
    }
  }

  function resizeInput() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    const length = input.value.length;
    counter.hidden = length < 3500;
    counter.textContent = `${length}/4000`;
  }

  const menu = find('ia-actions-menu');
  const plus = find('ia-plus');

  function syncMenu() {
    const last = [...state.messages].reverse().find(item => item.role === 'assistant' && item.content);
    find('ia-actions-copy').disabled = !last;
    find('ia-actions-stop').disabled = !state.streaming;
  }

  function setMenu(open) {
    menu.hidden = !open;
    plus.setAttribute('aria-expanded', String(open));
    if (open) syncMenu();
  }

  async function copyLastReply() {
    const last = [...state.messages].reverse().find(item => item.role === 'assistant' && item.content);
    if (!last) return;
    try {
      await navigator.clipboard.writeText(last.content);
      showNotice('Respuesta copiada al portapapeles.');
    } catch {
      showNotice('No pudimos copiar la respuesta. Selecciona el texto y cópialo manualmente.');
    }
  }

  function runMenuAction(action) {
    if (action === 'new') newConversation();
    else if (action === 'stop') state.controller?.abort();
    else if (action === 'copy') copyLastReply();
  }

  function bindEvents() {
    find('ia-new').addEventListener('click', newConversation);
    find('ia-search').addEventListener('input', event => {
      clearTimeout(searchTimer);
      const value = event.target.value;
      searchTimer = setTimeout(() => runSearch(value), 250);
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (state.streaming) state.controller?.abort();
      else send();
    });
    input.addEventListener('input', resizeInput);
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (state.streaming) state.controller?.abort();
        else send();
      }
    });
    thread.addEventListener('click', event => {
      const prompt = event.target.closest('[data-ia-prompt]');
      if (prompt) {
        input.value = prompt.dataset.iaPrompt;
        resizeInput();
        // A suggestion is a complete question: it is sent right away. While a reply is
        // being written or the model is unavailable, it stays in the field instead.
        if (!state.streaming && state.modelReady) send();
        else input.focus();
      }
    });
    plus.addEventListener('click', () => setMenu(menu.hidden));
    menu.addEventListener('click', event => {
      const item = event.target.closest('[data-ia-menu]');
      if (!item || item.classList.contains('is-off') || item.disabled) return;
      setMenu(false);
      runMenuAction(item.dataset.iaMenu);
    });
    document.addEventListener('click', event => {
      if (!menu.hidden && !event.target.closest('#ia-actions-menu') && !event.target.closest('#ia-plus')) setMenu(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !menu.hidden) setMenu(false);
    });
  }

  // Decides whether a question that arrived in the address (?q=) may be sent without
  // the visitor pressing Enviar. The site's topic buttons use this route, but anyone
  // can also build a link /ia?q=… and send it to someone. Regla del titular: solo con
  // una autorización de un solo uso que el clic en un botón del sitio deja en
  // sessionStorage (misma pestaña), para la misma pregunta y con menos de 30 s.
  // No es autenticación; evita que un enlace externo hable en nombre del visitante.
  function shouldAutoSend(query) {
    if (!state.modelReady || state.streaming || typeof query !== 'string' || !query.trim()) {
      return false;
    }
    const key = 'ia:autosend';
    try {
      const saved = sessionStorage.getItem(key);
      // Autorización de un solo uso.
      sessionStorage.removeItem(key);
      if (!saved) return false;
      const data = JSON.parse(saved);
      const elapsed = Date.now() - data.timestamp;
      return data.pregunta === query && Number.isFinite(elapsed) && elapsed >= 0 && elapsed < 30000;
    } catch {
      return false;
    }
  }

  function prefill() {
    const query = new URLSearchParams(location.search).get('q');
    if (!query) return;
    input.value = query.slice(0, 4000);
    resizeInput();
    try {
      const url = new URL(location.href);
      url.searchParams.delete('q');
      history.replaceState(null, '', url.pathname + (url.search ? url.search : ''));
    } catch { /* The query string is optional. */ }
    state.pendingQuery = input.value;
    if (!autoSendPending()) input.focus();
  }

  // Sends the question that arrived with ?q= when the rule allows it. Also called when
  // the model becomes ready later (Reintentar), within the same 30-second authorization.
  function autoSendPending() {
    const query = state.pendingQuery;
    if (!query || input.value !== query || !shouldAutoSend(query)) return false;
    state.pendingQuery = null;
    // A topic chosen on the site starts its own conversation instead of joining the last one.
    state.activeId = null;
    state.messages = [];
    renderMessages();
    send();
    return true;
  }

  async function boot() {
    hideNotice();
    try {
      const data = await request('/api/ia/bootstrap');
      state.owner = data.owner;
      applyOwner(data);
      state.conversations = Array.isArray(data.conversations) ? data.conversations : [];
      renderHistory();
      if (state.conversations.length) {
        await selectConversation(state.conversations[0].id);
      } else {
        state.activeId = null;
        state.messages = [];
        renderMessages();
      }
      applyModel(data.model);
      prefill();
    } catch (error) {
      showNotice(error.message, { retry: true });
      setComposerEnabled(false);
    }
  }

  setupSidebar();
  bindEvents();
  resizeInput();
  setComposerEnabled(false);
  boot();
})();
