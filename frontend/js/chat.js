'use strict';

// The conversation belongs to the server cookie. No customer data goes to localStorage.
(() => {
  const panel = document.querySelector('#reigel-chat');
  if (!panel) return;
  const find = selector => panel.querySelector(selector);
  const chat = {loaded:false,busy:false,mode:'ai',optedOut:false,appointment:null,config:null,poll:null,pending:null,bookingRequest:null,slotRequest:0,returnFocus:null,iaProbe:null};
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const requestId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const zone = () => chat.config?.business?.timezone || 'America/Puerto_Rico';
  const dateValue = (offset = 0) => new Intl.DateTimeFormat('en-CA',{timeZone:zone(),year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()+offset*86400000));
  const dateLabel = value => new Intl.DateTimeFormat('es-PR',{timeZone:zone(),weekday:'long',day:'numeric',month:'long',hour:'numeric',minute:'2-digit'}).format(new Date(value));
  const timeLabel = value => new Intl.DateTimeFormat('es-PR',{timeZone:zone(),hour:'numeric',minute:'2-digit'}).format(new Date(value));

  async function call(path, data) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 65000);
    try {
      const response = await fetch(path,{method:data === undefined ? 'GET' : 'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:data === undefined ? undefined : JSON.stringify(data),signal:controller.signal});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(typeof result.detail === 'string' ? result.detail : 'No pudimos completar la solicitud. Revisa los datos e inténtalo nuevamente.');
        error.status = response.status;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('La respuesta está tardando. Reintenta el mismo mensaje; conservaremos su referencia para evitar duplicarlo.');
      if (error instanceof TypeError) throw new Error('No hay conexión con el equipo. Comprueba tu conexión y vuelve a intentar.');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function setBusy(value) {
    chat.busy = value;
    find('#chat-send').disabled = value;
    find('#chat-send').textContent = value ? 'Enviando…' : 'Enviar ↗';
    find('#chat-thinking').hidden = !value;
    panel.setAttribute('aria-busy',String(value));
    panel.querySelectorAll('[data-chat-prompt]').forEach(button => button.disabled = value || chat.optedOut);
    panel.querySelectorAll('[data-chat-book]').forEach(button => button.disabled = value || chat.optedOut);
    panel.querySelectorAll('[data-chat-human]').forEach(button => button.disabled = value);
  }

  function render(data) {
    const log = find('#chat-messages');
    const scroll = find('.chat-scroll');
    const sessionState = find('#chat-session-state');
    const nearEnd = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
    const messages = Array.isArray(data.messages) ? data.messages : [];
    if (sessionState && typeof data.conversation_id === 'string' && data.conversation_id.trim()) sessionState.hidden = false;
    if (messages.length) {
      const signature = JSON.stringify(messages.map(message => [message.id,message.text,message.direction]));
      if (signature !== log.dataset.signature) {
        log.innerHTML = messages.map(message => `<article class="chat-bubble ${message.direction === 'inbound' ? 'customer' : 'assistant'}"><span class="chat-speaker">${message.direction === 'inbound' ? 'Tú' : 'Power Solar · R.E.I.G.E.L.'}</span><p>${safe(message.text)}</p></article>`).join('');
        log.dataset.signature = signature;
        if (nearEnd || chat.busy) scroll.scrollTop = scroll.scrollHeight;
      }
    } else if (data.reply) {
      const bubble = document.createElement('article');
      bubble.className = 'chat-bubble assistant';
      const text = document.createElement('p');
      text.textContent = data.reply;
      bubble.append(text);
      log.append(bubble);
    }
    chat.mode = data.mode || data.conversation?.mode || chat.mode;
    chat.optedOut = Boolean(data.opted_out);
    find('#chat-mode').textContent = chat.optedOut ? 'Asistencia comercial detenida' : chat.mode === 'human' ? 'Atención del equipo solicitada' : 'Asistente virtual de Power Solar';
    find('#chat-human-note').hidden = chat.mode !== 'human' || chat.optedOut;
    find('#chat-optout-note').hidden = !chat.optedOut;
    panel.querySelectorAll('[data-chat-book], [data-chat-prompt]').forEach(button => button.disabled = chat.optedOut || chat.busy);
    find('#chat-book-confirm').disabled = chat.optedOut;
    if (chat.optedOut) find('#chat-booking').hidden = true;
    if (data.appointment) renderAppointment(data.appointment);
    const references = data.sources || [];
    const sourceBox = find('#chat-sources');
    sourceBox.replaceChildren();
    references.slice(0,3).forEach(source => {
      const href = source.url || source.source_url;
      try {
        const parsed = new URL(href);
        if (parsed.protocol !== 'https:') return;
        const link = document.createElement('a');
        link.href = parsed.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = source.title || source.name || 'Consultar fuente';
        sourceBox.append(link);
      } catch { /* Only complete HTTPS references are rendered. */ }
    });
  }

  async function refresh() {
    if (chat.busy || !panel.open) return;
    try { render(await call('/api/public/chat')); } catch { /* A polling failure never replaces a customer's message or form. */ }
  }

  async function open(event) {
    const prompt = event?.currentTarget?.dataset.chatPrefill;
    if (prompt) {
      document.querySelectorAll('.intent-option').forEach(button => button.classList.toggle('is-selected',button === event.currentTarget));
    }
    chat.returnFocus = document.activeElement;
    if (!panel.open) panel.showModal();
    document.querySelectorAll('[data-open-chat]').forEach(button => button.setAttribute('aria-expanded','true'));
    if (!chat.loaded) {
      find('#chat-status').textContent = 'Conectando con tu conversación…';
      try {
        render(await call('/api/public/chat'));
        chat.loaded = true;
        find('#chat-status').textContent = '';
      } catch (error) {
        find('#chat-status').textContent = error.message;
      }
    } else await refresh();
    if (prompt) find('#chat-text').value = prompt;
    find('#chat-text').focus();
    clearInterval(chat.poll);
    chat.poll = setInterval(refresh,8000);
  }

  function closed() {
    clearInterval(chat.poll);
    document.querySelectorAll('[data-open-chat]').forEach(button => button.setAttribute('aria-expanded','false'));
    if (panel.dataset.chatPage === 'true') { location.assign('/captacion'); return; }
    chat.returnFocus?.focus();
  }

  async function send(text) {
    text = text.trim();
    if (!text || chat.busy) return;
    find('#chat-status').textContent = '';
    if (chat.pending?.text !== text) chat.pending = {text,request_id:requestId()};
    setBusy(true);
    try {
      const result = await call('/api/public/chat',chat.pending);
      render(result);
      const normalized = text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
      if (!chat.optedOut && /\b(?:agendar|reservar|coordinar|agendame|reservame|coordiname)\b|\b(?:quiero|deseo|necesito)\b.*\b(?:cita|evaluacion)\b/.test(normalized)) openBooking(false);
      chat.loaded = true;
      chat.pending = null;
      find('#chat-text').value = '';
    } catch (error) { find('#chat-status').textContent = error.message; }
    finally { setBusy(false); find('#chat-text').focus(); }
  }

  async function human() {
    if (chat.busy) return;
    find('#chat-status').textContent = '';
    setBusy(true);
    try {
      render(await call('/api/public/chat/human',{request_id:requestId()}));
      chat.loaded = true;
    } catch (error) { find('#chat-status').textContent = error.message; }
    finally { setBusy(false); }
  }

  async function openBooking(focus = true) {
    if (chat.optedOut) return;
    if (chat.appointment?.status === 'confirmed') { find('#chat-appointment').scrollIntoView({block:'nearest'}); return; }
    const section = find('#chat-booking');
    section.hidden = false;
    if (focus) section.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'nearest'});
    if (chat.config) return;
    find('#chat-booking-status').textContent = 'Consultando los horarios del equipo…';
    try {
      chat.config = await call('/api/public/config');
      const advisors = chat.config.advisors || [];
      find('#chat-advisor').innerHTML = '<option value="">Selecciona un asesor</option>' + advisors.map(advisor => `<option value="${safe(advisor.id)}">${safe(advisor.name)}</option>`).join('');
      find('#chat-date').min = dateValue();
      find('#chat-date').max = dateValue(60);
      find('#chat-date').value = dateValue(1);
      find('#chat-zone').textContent = `Horarios de ${zone()}.`;
      find('#chat-booking-status').textContent = advisors.length ? 'Elige un horario y confirma tus datos. La cita se reserva al pulsar Confirmar mi cita.' : 'Aún no hay horarios publicados. Solicita atención del equipo para coordinar tu evaluación.';
      find('#chat-book-form').hidden = !advisors.length;
      if (advisors.length === 1) { find('#chat-advisor').value = advisors[0].id; await slots(); }
    } catch (error) {
      chat.config = null;
      find('#chat-booking-status').textContent = error.message;
    }
  }

  async function slots() {
    const version = ++chat.slotRequest;
    const advisor = find('#chat-advisor').value, date = find('#chat-date').value;
    find('#chat-start').value = '';
    const container = find('#chat-slots');
    if (!advisor || !date) { container.innerHTML = '<p class="slot-empty">Selecciona un asesor y una fecha.</p>'; return; }
    container.innerHTML = '<p class="status-inline">Consultando horarios…</p>';
    try {
      const data = await call(`/api/public/slots?advisor_id=${encodeURIComponent(advisor)}&date=${encodeURIComponent(date)}`);
      if (version !== chat.slotRequest) return;
      container.innerHTML = data.slots?.length ? data.slots.map(slot => `<button type="button" class="slot-button" data-chat-slot="${safe(slot.start_at)}" aria-pressed="false">${safe(timeLabel(slot.start_at))}</button>`).join('') : '<p class="slot-empty">No hay horarios este día. Prueba otra fecha.</p>';
    } catch (error) { if (version === chat.slotRequest) container.innerHTML = `<p class="form-error">${safe(error.message)}</p>`; }
  }

  function renderAppointment(appointment) {
    if (!appointment.start_at || !appointment.id) return;
    chat.appointment = appointment;
    const cancelled = appointment.status === 'cancelled';
    const confirmed = appointment.status === 'confirmed';
    const presentation = {
      confirmed: ['CITA CONFIRMADA','Tu próximo paso ya tiene fecha.','Guarda esta confirmación. Si necesitas un cambio, solicita atención del equipo.'],
      cancelled: ['CITA CANCELADA','Este horario ya no está reservado.','Puedes consultar otro horario o solicitar atención del equipo.'],
      completed: ['CITA REALIZADA','El equipo registró esta cita como realizada.','Puedes coordinar otra evaluación o solicitar atención del equipo.'],
      no_show: ['NO ASISTIÓ','El equipo registró que no asististe a esta cita.','Puedes consultar otro horario o pedir al equipo que revise este registro.']
    }[appointment.status] || ['ESTADO POR VERIFICAR','Consulta el estado de esta cita con el equipo.','Solicita atención del equipo antes de asumir que existe una reserva activa.'];
    find('#chat-appointment').hidden = false;
    find('#chat-appointment').classList.toggle('cancelled',cancelled);
    find('#chat-appointment').innerHTML = `<span class="chat-step">${safe(presentation[0])}</span><h3>${safe(presentation[1])}</h3><p>${safe(dateLabel(appointment.start_at))}<br>${safe(appointment.advisor_name || 'Equipo de Power Solar')}</p><small>${safe(zone())} · Referencia ${safe(appointment.id)}</small><p class="field-help">${safe(presentation[2])}</p>`;
    if (confirmed) find('#chat-booking').hidden = true;
  }

  // General conversation buttons go to /ia only when its model can answer
  // now. Disabled or unreachable Ollama, a server error, a timeout, or an older
  // process without /api/ia/status (404) keep the deterministic chat, which
  // answers without the model and offers booking and human attention.
  function iaAvailable() {
    if (!chat.iaProbe) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 4000);
      chat.iaProbe = fetch('/api/ia/status',{credentials:'same-origin',cache:'no-store',signal:controller.signal})
        .then(response => (response.ok ? response.json() : null))
        .then(data => data?.available === true)
        .catch(() => false)
        .finally(() => clearTimeout(timer));
    }
    return chat.iaProbe;
  }

  // The public conversation now lives in the full-screen /ia workspace. The
  // legacy dialog on / stays available for existing links and deep entry.
  document.querySelectorAll('[data-open-chat]').forEach(button => button.addEventListener('click',async () => {
    const prompt = button.dataset.chatPrefill;
    if (await iaAvailable()) location.assign(prompt ? `/ia?q=${encodeURIComponent(prompt)}` : '/ia');
    else open({currentTarget:button});
  }));
  find('#chat-close').addEventListener('click',() => panel.close());
  panel.addEventListener('close',closed);
  find('#chat-form').addEventListener('submit',event => { event.preventDefault(); send(find('#chat-text').value); });
  find('#chat-text').addEventListener('keydown',event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(event.currentTarget.value); } });
  panel.addEventListener('click',event => {
    const prompt = event.target.closest('[data-chat-prompt]');
    if (prompt) { find('#chat-text').value = prompt.dataset.chatPrompt; send(prompt.dataset.chatPrompt); }
    if (event.target.closest('[data-chat-human]')) human();
    if (event.target.closest('[data-chat-book]')) openBooking();
    const slot = event.target.closest('[data-chat-slot]');
    if (slot) {
      find('#chat-start').value = slot.dataset.chatSlot;
      chat.bookingRequest = null;
      panel.querySelectorAll('[data-chat-slot]').forEach(button => { button.classList.toggle('selected',button === slot); button.setAttribute('aria-pressed',String(button === slot)); });
    }
  });
  find('#chat-booking-close').addEventListener('click',() => { find('#chat-booking').hidden = true; find('#chat-text').focus(); });
  find('#chat-advisor').addEventListener('change',slots);
  find('#chat-date').addEventListener('change',slots);
  find('#chat-book-form').addEventListener('input',() => { chat.bookingRequest = null; });
  find('#chat-book-form').addEventListener('submit',async event => {
    event.preventDefault();
    const form = event.currentTarget, button = find('#chat-book-confirm');
    if (button.disabled || chat.optedOut) return;
    const fields = new FormData(form);
    find('#chat-book-error').textContent = '';
    if (!fields.get('email')?.trim() && !fields.get('phone')?.trim()) { find('#chat-book-error').textContent = 'Incluye un correo electrónico o teléfono.'; return; }
    if (!fields.get('start_at')) { find('#chat-book-error').textContent = 'Elige un horario disponible.'; return; }
    const data = {name:fields.get('name').trim(),email:fields.get('email')?.trim() || '',phone:fields.get('phone')?.trim() || '',municipality:fields.get('municipality')?.trim() || '',monthly_bill:fields.get('monthly_bill') ? Number(fields.get('monthly_bill')) : null,consent:fields.has('consent'),advisor_id:fields.get('advisor_id'),start_at:fields.get('start_at'),request_id:chat.bookingRequest || requestId()};
    chat.bookingRequest = data.request_id;
    button.disabled = true;
    button.textContent = 'Confirmando tu cita…';
    try {
      const result = await call('/api/public/chat/book',data);
      if (!result.appointment?.id) throw new Error('No recibimos la confirmación de la cita. Solicita atención del equipo antes de repetir.');
      render(result);
      renderAppointment(result.appointment);
      chat.bookingRequest = null;
      find('#chat-appointment').focus();
    } catch (error) {
      find('#chat-book-error').textContent = error.message;
      if (error.status === 409) { chat.bookingRequest = null; await slots(); }
    } finally { button.disabled = false; button.textContent = 'Confirmar mi cita ↗'; }
  });
  if (panel.dataset.chatPage === 'true') open();
})();
