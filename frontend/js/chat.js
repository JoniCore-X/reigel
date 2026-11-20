'use strict';

// The conversation belongs to the server cookie. No customer data goes to localStorage.
(() => {
  const panel = document.querySelector('#reigel-chat');
  if (!panel) return;
  const find = selector => panel.querySelector(selector);
  const chat = {loaded:false,busy:false,mode:'ai',optedOut:false,appointment:null,config:null,poll:null,pending:null,bookingRequest:null,slotRequest:0,returnFocus:null,iaProbe:null,step:1};
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const requestId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const zone = () => chat.config?.business?.timezone || 'America/Puerto_Rico';
  const dateValue = (offset = 0) => new Intl.DateTimeFormat('en-CA',{timeZone:zone(),year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(Date.now()+offset*86400000));
  const dateLabel = value => new Intl.DateTimeFormat('es-PR',{timeZone:zone(),weekday:'long',day:'numeric',month:'long',hour:'numeric',minute:'2-digit'}).format(new Date(value));
  const timeLabel = value => new Intl.DateTimeFormat('es-PR',{timeZone:zone(),hour:'numeric',minute:'2-digit'}).format(new Date(value));
  const LOGO = '/static/assets/power-solar/reigel-logo.png';
  // [main, detail]: narrow screens may hide the detail, never the main state.
  const MODE = {ai:['Asistente automático',' · el equipo puede intervenir'],human:['Atención del equipo solicitada',''],stopped:['Asistencia comercial detenida','']};
  const MAX_TEXT_HEIGHT = 140;

  // Status lines are live regions (role="alert"); the tone only changes their presentation.
  function notice(selector, text, tone = 'error') {
    const node = find(selector);
    if (!node) return;
    node.textContent = text;
    if (text) node.dataset.tone = tone; else delete node.dataset.tone;
  }

  function showMode(mode) {
    const [main, detail] = MODE[mode];
    const node = find('#chat-mode');
    node.textContent = main;
    if (detail) {
      const extra = document.createElement('span');
      extra.className = 'rc-mode-detail';
      extra.textContent = detail;
      node.append(extra);
    }
  }

  // The booking panel owns the screen while open: the dock and composer
  // compact through [data-booking="open"] and return when it closes.
  function setBooking(open) {
    find('#chat-booking').hidden = !open;
    panel.dataset.booking = open ? 'open' : 'closed';
  }

  // After a confirmed appointment the primary dock action shows it instead
  // of offering another booking.
  function showDockFor(appointment) {
    const confirmed = appointment?.status === 'confirmed';
    panel.dataset.appointment = confirmed ? 'confirmed' : 'none';
    const title = find('.rc-dock-book strong'), detail = find('.rc-dock-book small');
    if (title) title.textContent = confirmed ? 'Ver mi cita' : 'Coordinar evaluación';
    if (detail) detail.textContent = confirmed ? 'Tu evaluación ya tiene fecha' : 'Elige asesor y horario';
  }

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

  // Composer grows with its text up to MAX_TEXT_HEIGHT, then scrolls.
  function fitComposer() {
    const text = find('#chat-text');
    if (!text?.style) return;
    // Empty: CSS keeps one line; the placeholder never sets the height.
    if (!text.value) { text.style.height = ''; text.style.overflowY = 'hidden'; return; }
    text.style.height = 'auto';
    const height = Math.min(text.scrollHeight || 0, MAX_TEXT_HEIGHT);
    if (height) text.style.height = `${height}px`;
    text.style.overflowY = text.scrollHeight > MAX_TEXT_HEIGHT ? 'auto' : 'hidden';
  }

  function setBusy(value) {
    chat.busy = value;
    const sendButton = find('#chat-send');
    const sendLabel = find('.rc-send-label');
    sendButton.disabled = value;
    if (sendLabel) sendLabel.textContent = value ? 'Enviando…' : 'Enviar';
    else sendButton.textContent = value ? 'Enviando…' : 'Enviar ↗';
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
      // The welcome cards stay above the greeting until the visitor writes.
      panel.dataset.chatStarted = String(messages.some(message => message.direction === 'inbound'));
      const signature = JSON.stringify(messages.map(message => [message.id,message.text,message.direction]));
      if (signature !== log.dataset.signature) {
        log.innerHTML = messages.map(message => message.direction === 'inbound'
          ? `<article class="chat-bubble customer"><span class="chat-speaker">Tú</span><p>${safe(message.text)}</p></article>`
          : `<article class="chat-bubble assistant"><img class="rc-bubble-avatar" src="${LOGO}" alt="" width="32" height="32"><span class="chat-speaker">Power Solar · R.E.I.G.E.L.</span><p>${safe(message.text)}</p></article>`).join('');
        const firstPaint = !log.dataset.signature;
        log.dataset.signature = signature;
        // A new visitor starts at the welcome cards, not at the end of the greeting.
        if (firstPaint && panel.dataset.chatStarted !== 'true') scroll.scrollTop = 0;
        else if (nearEnd || chat.busy) scroll.scrollTop = scroll.scrollHeight;
      }
    } else if (data.reply) {
      const bubble = document.createElement('article');
      bubble.className = 'chat-bubble assistant';
      const avatar = document.createElement('img');
      avatar.className = 'rc-bubble-avatar';
      avatar.src = LOGO;
      avatar.alt = '';
      const text = document.createElement('p');
      text.textContent = data.reply;
      bubble.append(avatar,text);
      log.append(bubble);
    }
    chat.mode = data.mode || data.conversation?.mode || chat.mode;
    chat.optedOut = Boolean(data.opted_out);
    const mode = chat.optedOut ? 'stopped' : chat.mode === 'human' ? 'human' : 'ai';
    panel.dataset.chatMode = mode;
    showMode(mode);
    find('#chat-human-note').hidden = chat.mode !== 'human' || chat.optedOut;
    find('#chat-optout-note').hidden = !chat.optedOut;
    panel.querySelectorAll('[data-chat-book], [data-chat-prompt]').forEach(button => button.disabled = chat.optedOut || chat.busy);
    find('#chat-book-confirm').disabled = chat.optedOut;
    if (chat.optedOut) setBooking(false);
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
        // Titles come from the knowledge base as published; only the label is ours.
        const label = document.createElement('span');
        label.className = 'rc-source-label';
        label.textContent = 'Fuente: ';
        const title = document.createElement('span');
        title.textContent = source.title || source.name || 'Consultar fuente';
        link.append(label,title);
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
      notice('#chat-status','Conectando con tu conversación…','info');
      try {
        render(await call('/api/public/chat'));
        chat.loaded = true;
        notice('#chat-status','');
      } catch (error) {
        notice('#chat-status',error.message);
      }
    } else await refresh();
    if (prompt) find('#chat-text').value = prompt;
    fitComposer();
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
    notice('#chat-status','');
    if (chat.pending?.text !== text) chat.pending = {text,request_id:requestId()};
    setBusy(true);
    try {
      const result = await call('/api/public/chat',chat.pending);
      panel.dataset.chatStarted = 'true';
      render(result);
      const normalized = text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
      if (!chat.optedOut && /\b(?:agendar|reservar|coordinar|agendame|reservame|coordiname)\b|\b(?:quiero|deseo|necesito)\b.*\b(?:cita|evaluacion)\b/.test(normalized)) openBooking(false);
      chat.loaded = true;
      chat.pending = null;
      find('#chat-text').value = '';
      fitComposer();
    } catch (error) { notice('#chat-status',error.message); }
    finally { setBusy(false); find('#chat-text').focus(); }
  }

  async function human() {
    if (chat.busy) return;
    notice('#chat-status','');
    setBusy(true);
    try {
      render(await call('/api/public/chat/human',{request_id:requestId()}));
      chat.loaded = true;
    } catch (error) { notice('#chat-status',error.message); }
    finally { setBusy(false); }
  }

  async function openBooking(focus = true) {
    if (chat.optedOut) return;
    if (chat.appointment?.status === 'confirmed') { find('#chat-appointment').scrollIntoView({block:'nearest'}); find('#chat-appointment').focus(); return; }
    const section = find('#chat-booking');
    setBooking(true);
    if (focus) section.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});
    if (chat.config) return;
    notice('#chat-booking-status','Consultando los horarios del equipo…','info');
    try {
      chat.config = await call('/api/public/config');
      const advisors = chat.config.advisors || [];
      find('#chat-advisor').innerHTML = '<option value="">Selecciona un asesor</option>' + advisors.map(advisor => `<option value="${safe(advisor.id)}">${safe(advisor.name)}</option>`).join('');
      find('#chat-date').min = dateValue();
      find('#chat-date').max = dateValue(60);
      find('#chat-date').value = dateValue(1);
      find('#chat-zone').textContent = `Horarios de ${zone()}.`;
      notice('#chat-booking-status',advisors.length ? 'Elige un horario, revisa tus datos y confirma. La cita se reserva solamente al pulsar Confirmar mi cita.' : 'Aún no hay horarios publicados. Solicita atención del equipo para coordinar tu evaluación.','info');
      find('#chat-book-form').hidden = !advisors.length;
      if (advisors.length === 1) { find('#chat-advisor').value = advisors[0].id; await slots(); }
    } catch (error) {
      chat.config = null;
      notice('#chat-booking-status',error.message);
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

  // Booking steps: progressive enhancement over a single form. Without this
  // script every fieldset stays visible and the form submits as one page.
  const STEP_ARC = {1:1/6,2:3/6,3:5/6};
  const stepFields = () => find('#chat-book-form');
  function field(name) { return stepFields()?.querySelector(`[name="${name}"]`); }
  function value(name) { return String(field(name)?.value ?? '').trim(); }

  function drawArc(fraction) {
    const fill = find('#chat-book-arc');
    const sun = find('#chat-book-sun');
    if (fill?.style) fill.style.strokeDashoffset = String(100 - fraction * 100);
    if (sun && typeof fill?.getPointAtLength === 'function' && typeof fill.getTotalLength === 'function') {
      const point = fill.getPointAtLength(fill.getTotalLength() * fraction);
      sun.setAttribute('cx',point.x.toFixed(1));
      sun.setAttribute('cy',point.y.toFixed(1));
    }
  }

  function summary() {
    const list = find('#chat-book-summary');
    if (!list) return;
    const advisorId = value('advisor_id');
    const advisor = (chat.config?.advisors || []).find(item => String(item.id) === advisorId);
    const start = value('start_at');
    const contact = [value('email'),value('phone')].filter(Boolean).join(' · ');
    const rows = [
      ['Asesor',advisor?.name || 'Equipo de Power Solar'],
      ['Fecha y hora',start ? `${dateLabel(start)} (${zone()})` : 'Sin horario'],
      ['Nombre',value('name')],
      ['Contacto',contact],
      ['Municipio',value('municipality') || 'No indicado'],
    ];
    if (value('monthly_bill')) rows.push(['Factura declarada',`${value('monthly_bill')} USD al mes, aproximada`]);
    list.replaceChildren(...rows.map(([label,text]) => {
      const row = document.createElement('div');
      const term = document.createElement('dt');
      const detail = document.createElement('dd');
      term.textContent = label;
      detail.textContent = text;
      row.append(term,detail);
      return row;
    }));
    list.hidden = false;
  }

  function showStep(step, focus = true) {
    const form = stepFields();
    if (!form) return;
    chat.step = step;
    form.dataset.step = String(step);
    panel.querySelectorAll('[data-book-step]').forEach(fieldset => { fieldset.hidden = Number(fieldset.dataset.bookStep) !== step; });
    panel.querySelectorAll('[data-book-marker]').forEach(marker => {
      const number = Number(marker.dataset.bookMarker);
      marker.classList.toggle('is-done',number < step);
      if (number === step) marker.setAttribute('aria-current','step'); else marker.removeAttribute('aria-current');
    });
    find('#chat-book-back').hidden = step === 1;
    find('#chat-book-next').hidden = step === 3;
    find('#chat-book-confirm').hidden = step !== 3;
    if (step === 3) summary();
    drawArc(STEP_ARC[step]);
    if (focus) panel.querySelector(`[data-book-step="${step}"] .rc-step-title`)?.focus();
  }

  // Returns [field, message] for the first problem in a step, or null.
  function problem(step) {
    if (step === 1) {
      if (!value('advisor_id')) return [find('#chat-advisor'),'Selecciona un asesor.'];
      if (!value('start_at')) return [find('#chat-slots')?.querySelector('[data-chat-slot]') || find('#chat-date'),'Elige un horario disponible.'];
    }
    if (step === 2) {
      if (!value('name')) return [field('name'),'Escribe tu nombre completo.'];
      if (!value('email') && !value('phone')) return [field('email'),'Incluye un correo electrónico o teléfono.'];
      if (value('email') && field('email')?.checkValidity?.() === false) return [field('email'),'Revisa el correo electrónico: parece incompleto.'];
      if (value('monthly_bill') && field('monthly_bill')?.checkValidity?.() === false) return [field('monthly_bill'),'La factura aproximada debe ser un número entre 0 y 100,000.'];
    }
    if (step === 3 && !field('consent')?.checked) return [field('consent'),'Marca la autorización para poder confirmar tu cita.'];
    return null;
  }

  function report([target, message]) {
    notice('#chat-book-error',message);
    if (target) { target.setAttribute('aria-invalid','true'); target.focus?.(); }
  }

  function validStep(step) {
    stepFields()?.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
    const found = problem(step);
    if (found) report(found);
    return !found;
  }

  function nextStep() {
    notice('#chat-book-error','');
    if (validStep(chat.step)) showStep(Math.min(chat.step + 1,3));
  }

  function previousStep() {
    notice('#chat-book-error','');
    showStep(Math.max(chat.step - 1,1));
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
    // The booking arc completed: the full sun over the horizon (decorative).
    const sun = confirmed ? '<div class="rc-appointment-sky"><svg class="rc-appointment-sun" viewBox="0 0 240 96" aria-hidden="true" focusable="false"><defs><radialGradient id="rc-sun-glow"><stop offset="0" stop-color="#ffe2bd"/><stop offset=".45" stop-color="#ff8a2b" stop-opacity=".75"/><stop offset="1" stop-color="#ff8a2b" stop-opacity="0"/></radialGradient></defs><path class="rc-sky-line" d="M0 86H240"/><path class="rc-sky-arc" d="M14 86A160 160 0 0 1 226 86"/><circle class="rc-sun-halo" cx="120" cy="46" r="42" fill="url(#rc-sun-glow)"/><path class="rc-sun-rays" d="M145 46h8M137.7 63.7l5.6 5.6M120 71v8M95 46h-8M102.3 63.7l-5.6 5.6M102.3 28.3l-5.6-5.6M120 21v-8M137.7 28.3l5.6-5.6"/><circle class="rc-sun-core" cx="120" cy="46" r="18"/></svg></div>' : '';
    find('#chat-appointment').hidden = false;
    find('#chat-appointment').classList.toggle('cancelled',cancelled);
    find('#chat-appointment').classList.toggle('is-confirmed',confirmed);
    find('#chat-appointment').innerHTML = `${sun}<div class="rc-appointment-body"><span class="chat-step">${safe(presentation[0])}</span><h3>${safe(presentation[1])}</h3><p>${safe(dateLabel(appointment.start_at))}<br>${safe(appointment.advisor_name || 'Equipo de Power Solar')}</p><small>${safe(zone())} · Referencia ${safe(appointment.id)}</small><p class="field-help">${safe(presentation[2])}</p></div>`;
    showDockFor(appointment);
    if (confirmed) setBooking(false);
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
  find('#chat-text').addEventListener('input',fitComposer);
  globalThis.addEventListener?.('resize',() => { if (panel.open) fitComposer(); });
  panel.addEventListener('click',event => {
    const prompt = event.target.closest('[data-chat-prompt]');
    if (prompt) { find('#chat-text').value = prompt.dataset.chatPrompt; send(prompt.dataset.chatPrompt); }
    if (event.target.closest('[data-chat-human]')) human();
    if (event.target.closest('[data-chat-book]')) openBooking();
    const slot = event.target.closest('[data-chat-slot]');
    if (slot) {
      find('#chat-start').value = slot.dataset.chatSlot;
      chat.bookingRequest = null;
      panel.querySelectorAll('[data-chat-slot]').forEach(button => { button.classList.toggle('selected',button === slot); button.setAttribute('aria-pressed',String(button === slot)); button.removeAttribute('aria-invalid'); });
      if (chat.step === 1) notice('#chat-book-error','');
    }
  });
  find('#chat-booking-close').addEventListener('click',() => { setBooking(false); find('#chat-text').focus(); });
  find('#chat-advisor').addEventListener('change',slots);
  find('#chat-date').addEventListener('change',slots);
  find('#chat-book-form').addEventListener('input',() => { chat.bookingRequest = null; });
  find('#chat-book-next')?.addEventListener('click',nextStep);
  find('#chat-book-back')?.addEventListener('click',previousStep);
  // Enter inside steps 1 and 2 advances instead of submitting the booking.
  find('#chat-book-form').addEventListener('keydown',event => {
    if (event.key !== 'Enter' || chat.step >= 3 || event.target?.tagName !== 'INPUT') return;
    event.preventDefault();
    nextStep();
  });
  find('#chat-book-form').addEventListener('submit',async event => {
    event.preventDefault();
    const form = event.currentTarget, button = find('#chat-book-confirm');
    if (button.disabled || chat.optedOut) return;
    notice('#chat-book-error','');
    // Every step is checked again before sending; the first failure is shown in place.
    const failed = [1,2,3].find(step => problem(step));
    if (failed) { showStep(failed,false); validStep(failed); return; }
    const fields = new FormData(form);
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
      if (field('consent')) field('consent').checked = false;
      showStep(1,false);
      find('#chat-appointment').focus();
    } catch (error) {
      if (error.status === 409) {
        // The slot was taken meanwhile: back to step 1 with fresh times.
        chat.bookingRequest = null;
        showStep(1,false);
        notice('#chat-book-error',error.message);
        await slots();
        find('#chat-slots')?.querySelector('[data-chat-slot]')?.focus?.();
      } else notice('#chat-book-error',error.message);
    } finally { button.disabled = chat.optedOut; button.textContent = 'Confirmar mi cita ↗'; }
  });
  if (find('#chat-book-progress')) {
    find('#chat-book-form').noValidate = true;
    find('#chat-book-progress').hidden = false;
    showStep(1,false);
  }
  panel.dataset.chatMode = 'ai';
  panel.dataset.booking = 'closed';
  showMode('ai');
  if (panel.dataset.chatPage === 'true') open();
})();
