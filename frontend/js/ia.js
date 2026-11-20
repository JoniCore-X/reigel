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
    // Incremented whenever the visible conversation changes. A response or a
    // reply that belongs to an earlier view only updates the history list.
    view: 0,
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

  function renderHistory() {
    historyList.replaceChildren();
    state.conversations.forEach(item => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.id = item.id;
      button.setAttribute('aria-current', String(item.id === state.activeId));
      const title = document.createElement('strong');
      title.textContent = item.title || 'Nueva conversación';
      const date = document.createElement('small');
      date.textContent = dateLabel(item.updated_at);
      button.append(title, date);
      button.addEventListener('click', () => {
        if (state.streaming) state.controller?.abort();
        selectConversation(item.id);
        if (isMobile()) setSidebar(false);
      });
      historyList.append(button);
    });
    find('ia-history-empty').hidden = state.conversations.length > 0;
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
      return;
    }
    state.messages.forEach(message => {
      thread.append(messageNode(message));
    });
    scrollToEnd();
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

  function appendAssistant() {
    const node = messageNode({ id: 'pending', role: 'assistant', content: '', status: 'streaming' });
    const dots = document.createElement('span');
    dots.className = 'ia-typing';
    dots.setAttribute('aria-label', 'R.E.I.G.E.L. está preparando la respuesta');
    dots.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
    node.querySelector('.ia-msg-body').append(dots);
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
    if (state.modelReady) return;
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
    appendUser(value);
    const pending = appendAssistant();
    let content = '';
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
          const body = pending.querySelector('.ia-msg-body');
          if (!content) body.replaceChildren();
          content += data.text;
          body.textContent = content;
          if (nearEnd()) scrollToEnd();
        },
        done: data => {
          if (visible()) finalize(pending, data.assistant);
          upsertConversation(data.conversation);
          renderHistory();
        },
        replace: data => {
          if (!visible()) return;
          finalize(pending, data.assistant);
          showNotice(data.detail);
        },
        error: data => {
          if (!visible()) return;
          if (data.assistant) finalize(pending, data.assistant);
          else pending.remove();
          showNotice(data.detail, { retry: true });
        },
      });
    } catch (error) {
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
        input.focus();
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

  function prefill() {
    const query = new URLSearchParams(location.search).get('q');
    if (!query) return;
    input.value = query.slice(0, 4000);
    resizeInput();
    input.focus();
    try {
      const url = new URL(location.href);
      url.searchParams.delete('q');
      history.replaceState(null, '', url.pathname + (url.search ? url.search : ''));
    } catch { /* The query string is optional. */ }
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
