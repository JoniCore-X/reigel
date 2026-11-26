'use strict';

// Run the real frontend/js/chat.js against the real dialog markup of
// frontend/chat.html, parsed into a small synthetic DOM, with a scripted fetch.
// No browser, server, model or data: it checks the booking steps only.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const source = readFileSync(path.join(root, 'frontend/js/chat.js'), 'utf8');
const page = readFileSync(path.join(root, 'frontend/chat.html'), 'utf8');

const VOID = new Set(['input', 'img', 'br', 'meta', 'link', 'path', 'circle', 'rect', 'hr']);
const camel = name => name.replace(/-([a-z])/g, (_, char) => char.toUpperCase());

class Text {
  constructor(text) { this.text = text; this.parent = null; }
  get textContent() { return this.text; }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
}

class Element {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.doc = doc;
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.handlers = {};
    this.classes = new Set();
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.id = '';
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    const element = this;
    this.classList = {
      add: (...names) => names.forEach(name => element.classes.add(name)),
      remove: (...names) => names.forEach(name => element.classes.delete(name)),
      contains: name => element.classes.has(name),
      toggle(name, force) { const on = force === undefined ? !element.classes.has(name) : Boolean(force); if (on) element.classes.add(name); else element.classes.delete(name); return on; },
    };
  }
  set className(value) { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classes].join(' '); }
  get type() { return this.attributes.type || ''; }
  get elements() { return this.descendants(); }
  setAttribute(name, value) {
    value = String(value);
    if (name === 'id') this.id = value;
    else if (name === 'class') this.className = value;
    else if (name === 'hidden') this.hidden = true;
    else if (name === 'disabled') this.disabled = true;
    else if (name === 'checked') this.checked = true;
    else if (name === 'value') { this.value = value; this.attributes.value = value; }
    else if (name.startsWith('data-')) this.dataset[camel(name.slice(5))] = value;
    else this.attributes[name] = value;
  }
  getAttribute(name) {
    if (name === 'id') return this.id || null;
    if (name === 'class') return this.className;
    if (name === 'hidden') return this.hidden ? '' : null;
    if (name.startsWith('data-')) { const key = camel(name.slice(5)); return key in this.dataset ? this.dataset[key] : null; }
    return name in this.attributes ? this.attributes[name] : null;
  }
  removeAttribute(name) {
    if (name === 'hidden') this.hidden = false;
    else if (name.startsWith('data-')) delete this.dataset[camel(name.slice(5))];
    else delete this.attributes[name];
  }
  get textContent() { return this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.replaceChildren(); if (String(value)) this.append(new Text(String(value))); }
  set innerHTML(html) { this.replaceChildren(...parse(String(html), this.doc)); }
  append(...nodes) { nodes.forEach(node => { node.remove(); node.parent = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.append(...nodes); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
  descendants() { return this.children.filter(child => child instanceof Element).flatMap(child => [child, ...child.descendants()]); }
  matches(selector) { return selector.split(',').some(part => matchChain(this, part.trim().split(/\s+/))); }
  closest(selector) { for (let node = this; node; node = node.parent) if (node instanceof Element && node.matches(selector)) return node; return null; }
  querySelector(selector) { return this.descendants().find(node => node.matches(selector)) || null; }
  querySelectorAll(selector) { return this.descendants().filter(node => node.matches(selector)); }
  addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
  dispatch(type, init = {}) {
    let stopped = false;
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { stopped = true; }, ...init };
    for (let node = this; node && !stopped; node = node.parent) {
      (node.handlers[type] || []).forEach(handler => handler({ ...event, currentTarget: node, preventDefault: () => { event.defaultPrevented = true; } }));
    }
    return event;
  }
  click() { if (!this.disabled) this.dispatch('click'); }
  requestSubmit() { this.dispatch('submit'); }
  focus() { this.doc.activeElement = this; }
  blur() {}
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  checkValidity() {
    if (this.type === 'email' && this.value) return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(this.value);
    if (this.type === 'number' && this.value) {
      const number = Number(this.value);
      return Number.isFinite(number) && number >= Number(this.attributes.min ?? -Infinity) && number <= Number(this.attributes.max ?? Infinity);
    }
    return true;
  }
}

function matchCompound(node, compound) {
  const tokens = compound.match(/[a-zA-Z][\w-]*|#[\w-]+|\.[\w-]+|\[[\w-]+(?:="[^"]*")?\]/g) || [];
  return tokens.every(token => {
    if (token[0] === '#') return node.id === token.slice(1);
    if (token[0] === '.') return node.classes.has(token.slice(1));
    if (token[0] === '[') {
      const [, name, expected] = token.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
      const actual = node.getAttribute(name);
      return expected === undefined ? actual !== null : actual === expected;
    }
    return node.tagName === token.toUpperCase();
  });
}

function matchChain(node, chain) {
  if (!matchCompound(node, chain[chain.length - 1])) return false;
  let rest = chain.slice(0, -1);
  for (let ancestor = node.parent; rest.length && ancestor; ancestor = ancestor.parent) {
    if (ancestor instanceof Element && matchCompound(ancestor, rest[rest.length - 1])) rest = rest.slice(0, -1);
  }
  return rest.length === 0;
}

function parse(html, doc) {
  const top = new Element('fragment', doc);
  const stack = [top];
  const pattern = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:[^>"]|"[^"]*")*)>|([^<]+)/g;
  for (const [, close, open, rawAttributes, text] of html.matchAll(pattern)) {
    const current = stack[stack.length - 1];
    if (text !== undefined) { if (text.trim()) current.append(new Text(text)); continue; }
    if (close) { while (stack.length > 1 && stack.pop().tagName !== close.toUpperCase()); continue; }
    if (!open) continue;
    const element = new Element(open, doc);
    for (const [, name, value] of rawAttributes.matchAll(/([^\s=\/]+)(?:\s*=\s*"([^"]*)")?/g)) element.setAttribute(name, value ?? '');
    current.append(element);
    if (!VOID.has(open.toLowerCase()) && !/\/\s*$/.test(rawAttributes)) stack.push(element);
  }
  return [...top.children];
}

class FakeFormData {
  constructor(form) {
    this.entries = new Map();
    form.descendants().forEach(node => {
      const name = node.attributes.name;
      if (!name || node.disabled) return;
      if (node.type === 'checkbox' && !node.checked) return;
      this.entries.set(name, node.type === 'checkbox' ? (node.attributes.value || 'on') : node.value);
    });
  }
  get(name) { return this.entries.has(name) ? this.entries.get(name) : null; }
  has(name) { return this.entries.has(name); }
}

const json = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const flush = async () => { for (let i = 0; i < 12; i += 1) await new Promise(resolve => setImmediate(resolve)); };

function setup(routes) {
  const doc = { activeElement: null };
  const dialogHtml = page.match(/<dialog[\s\S]*<\/dialog>/)[0];
  const body = new Element('body', doc);
  body.append(...parse(dialogHtml, doc));
  const panel = body.querySelector('#reigel-chat');
  const requests = [];
  doc.querySelector = selector => body.querySelector(selector);
  doc.querySelectorAll = selector => body.querySelectorAll(selector);
  doc.createElement = tag => new Element(tag, doc);
  const fetch = async (url, options = {}) => {
    const method = options.method || 'GET';
    const data = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ method, url, data });
    const route = routes[`${method} ${url.split('?')[0]}`];
    assert.ok(route, `unexpected request ${method} ${url}`);
    return typeof route === 'function' ? route(data, requests) : route;
  };
  const context = vm.createContext({
    document: doc, fetch, FormData: FakeFormData, URL, AbortController, setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval: () => {}, matchMedia: () => ({ matches: false }),
    location: { assign() {} }, crypto: webcrypto, console,
  });
  vm.runInContext(source, context, { filename: 'chat.js' });
  const find = selector => panel.querySelector(selector);
  const field = name => find('#chat-book-form').querySelector(`[name="${name}"]`);
  return { panel, find, field, requests, doc };
}

const SLOT_A = '2026-11-20T14:00:00+00:00';
const SLOT_B = '2026-11-20T15:00:00+00:00';

test('booking runs in three validated steps, returns to step 1 on 409 and only shows a server appointment', async () => {
  let bookings = 0;
  const { panel, find, field, requests, doc } = setup({
    'GET /api/public/chat': json({ conversation_id: 'c1', messages: [{ direction: 'outbound', text: 'Hola <b>visitante</b>' }],
      sources: [{ title: 'Guía publicada', url: 'https://example.org/guia' }, { title: 'Sin cifrado', url: 'http://example.org/x' }] }),
    'GET /api/public/config': json({ advisors: [{ id: 'a1', name: 'Asesora Demo' }], business: { timezone: 'America/Puerto_Rico' } }),
    'GET /api/public/slots': json({ slots: [{ start_at: SLOT_A }, { start_at: SLOT_B }] }),
    'POST /api/public/chat/book': data => {
      bookings += 1;
      if (bookings === 1) return json({ detail: 'Ese horario ya no está disponible. Elige otro.' }, 409);
      return json({ messages: [], appointment: { id: 'apt-1', reference: 'K7M-4QX', start_at: data.start_at, status: 'confirmed', advisor_name: 'Asesora Demo' } });
    },
  });
  await flush();

  // Welcome stays until the visitor writes; message text is escaped.
  assert.equal(panel.dataset.chatStarted, 'false');
  assert.equal(find('#chat-messages').querySelector('.chat-bubble p').textContent, 'Hola &lt;b&gt;visitante&lt;/b&gt;');
  // Source titles stay as published, behind a Spanish label; only HTTPS links render.
  assert.deepEqual(find('#chat-sources').children.map(link => link.textContent), ['Fuente: Guía publicada']);
  assert.equal(panel.dataset.booking, 'closed');

  // Progressive enhancement over the single form.
  const form = find('#chat-book-form');
  assert.equal(form.noValidate, true);
  assert.equal(find('#chat-book-progress').hidden, false);
  const visibleSteps = () => panel.querySelectorAll('[data-book-step]').filter(step => !step.hidden).map(step => step.dataset.bookStep);
  const current = () => panel.querySelectorAll('[data-book-marker]').filter(marker => marker.getAttribute('aria-current') === 'step').map(marker => marker.dataset.bookMarker);
  assert.deepEqual(visibleSteps(), ['1']);
  assert.deepEqual(current(), ['1']);
  assert.equal(find('#chat-book-confirm').hidden, true);
  assert.equal(find('#chat-book-back').hidden, true);

  find('[data-chat-book]').click();
  await flush();
  assert.equal(panel.dataset.booking, 'open');
  assert.equal(find('#chat-booking').hidden, false);
  assert.equal(find('#chat-advisor').value, 'a1');
  assert.equal(panel.querySelectorAll('[data-chat-slot]').length, 2);

  // Step 1 requires a time.
  find('#chat-book-next').click();
  assert.equal(find('#chat-book-error').textContent, 'Elige un horario disponible.');
  assert.deepEqual(visibleSteps(), ['1']);

  panel.querySelectorAll('[data-chat-slot]')[0].click();
  assert.equal(find('#chat-start').value, SLOT_A);
  // Enter in a step 1 field advances instead of submitting.
  const enter = find('#chat-date').dispatch('keydown', { key: 'Enter' });
  assert.equal(enter.defaultPrevented, true);
  assert.deepEqual(visibleSteps(), ['2']);
  assert.deepEqual(current(), ['2']);
  assert.ok(panel.querySelector('[data-book-marker="1"]').classList.contains('is-done'));
  assert.equal(doc.activeElement, panel.querySelector('[data-book-step="2"] .rc-step-title'));

  // Step 2: name, then email or phone, then a valid email.
  find('#chat-book-next').click();
  assert.equal(find('#chat-book-error').textContent, 'Escribe tu nombre completo.');
  field('name').value = 'Visitante Sintético';
  find('#chat-book-next').click();
  assert.equal(find('#chat-book-error').textContent, 'Incluye un correo electrónico o teléfono.');
  field('email').value = 'sin-dominio';
  find('#chat-book-next').click();
  assert.match(find('#chat-book-error').textContent, /correo electrónico/);
  assert.equal(field('email').getAttribute('aria-invalid'), 'true');
  field('email').value = '';
  field('phone').value = '+1 787 555 0100';
  field('municipality').value = 'Caguas';
  field('municipality').dispatch('keydown', { key: 'Enter' });
  assert.deepEqual(visibleSteps(), ['3']);
  assert.equal(find('#chat-book-error').textContent, '');

  // Step 3: generated summary, consent unchecked and required.
  const summary = find('#chat-book-summary').textContent;
  for (const text of ['Asesora Demo', 'hora de Puerto Rico', 'Visitante Sintético', '+1 787 555 0100', 'Caguas']) assert.ok(summary.includes(text), text);
  assert.equal(field('consent').checked, false);
  assert.equal(find('#chat-book-confirm').hidden, false);
  form.requestSubmit();
  await flush();
  assert.equal(find('#chat-book-error').textContent, 'Marca la autorización para poder confirmar tu cita.');
  assert.equal(requests.filter(request => request.method === 'POST').length, 0);

  // Taken slot: back to step 1 with the notice and refreshed times.
  field('consent').checked = true;
  const slotQueries = requests.filter(request => request.url.startsWith('/api/public/slots')).length;
  form.requestSubmit();
  await flush();
  const first = requests.filter(request => request.method === 'POST')[0];
  assert.equal(first.data.consent, true);
  assert.equal(first.data.start_at, SLOT_A);
  assert.equal(first.data.phone, '+1 787 555 0100');
  assert.deepEqual(visibleSteps(), ['1']);
  assert.equal(find('#chat-book-error').textContent, 'Ese horario ya no está disponible. Elige otro.');
  assert.equal(find('#chat-start').value, '');
  assert.equal(requests.filter(request => request.url.startsWith('/api/public/slots')).length, slotQueries + 1);
  assert.equal(find('#chat-appointment').hidden, true);

  // Second attempt with a new time and a new request id.
  panel.querySelectorAll('[data-chat-slot]')[1].click();
  find('#chat-book-next').click();
  find('#chat-book-next').click();
  assert.deepEqual(visibleSteps(), ['3']);
  form.requestSubmit();
  await flush();
  const second = requests.filter(request => request.method === 'POST')[1];
  assert.equal(second.data.start_at, SLOT_B);
  assert.notEqual(second.data.request_id, first.data.request_id);
  assert.equal(find('#chat-appointment').hidden, false);
  assert.match(find('#chat-appointment').textContent, /CITA CONFIRMADA/);
  assert.match(find('#chat-appointment').textContent, /Código de tu citaK7M-4QX/);
  assert.doesNotMatch(find('#chat-appointment').textContent, /apt-1/);
  assert.ok(find('#chat-appointment').querySelector('.rc-appointment-sun'));
  assert.equal(find('#chat-booking').hidden, true);
  assert.equal(field('consent').checked, false);
  // The dock stops offering a new booking and shows the confirmed one.
  assert.equal(panel.dataset.booking, 'closed');
  assert.equal(panel.dataset.appointment, 'confirmed');
  assert.equal(find('.rc-dock-book strong').textContent, 'Ver mi cita');
  find('[data-chat-book]').click();
  await flush();
  assert.equal(find('#chat-booking').hidden, true);
  assert.equal(doc.activeElement, find('#chat-appointment'));
});

test('submitting from an earlier step validates in place without sending', async () => {
  const { panel, find, requests } = setup({
    'GET /api/public/chat': json({ conversation_id: 'c2', messages: [{ direction: 'inbound', text: 'Quiero una cita' }] }),
  });
  await flush();
  assert.equal(panel.dataset.chatStarted, 'true');
  find('#chat-book-form').requestSubmit();
  await flush();
  assert.equal(find('#chat-book-error').textContent, 'Selecciona un asesor.');
  assert.deepEqual(panel.querySelectorAll('[data-book-step]').filter(step => !step.hidden).map(step => step.dataset.bookStep), ['1']);
  assert.equal(requests.filter(request => request.method === 'POST').length, 0);
});
