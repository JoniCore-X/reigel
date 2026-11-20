'use strict';

// Run the real frontend/js/ia.js against a small synthetic DOM and a scripted
// fetch, so response order can be controlled. No browser, server, model or data.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = readFileSync(path.resolve(__dirname, '..', 'frontend/js/ia.js'), 'utf8');

class ClassList {
  constructor() { this.items = new Set(); }
  add(...names) { names.forEach(name => this.items.add(name)); }
  remove(...names) { names.forEach(name => this.items.delete(name)); }
  toggle(name, force) {
    const on = force === undefined ? !this.items.has(name) : force;
    if (on) this.items.add(name); else this.items.delete(name);
    return on;
  }
  contains(name) { return this.items.has(name); }
}

class Node {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.attributes = {};
    this.style = {};
    this.handlers = {};
    this.classList = new ClassList();
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    this._text = '';
  }
  set className(value) { this.classList = new ClassList(); String(value).split(/\s+/).filter(Boolean).forEach(n => this.classList.add(n)); }
  get className() { return [...this.classList.items].join(' '); }
  set textContent(value) { this.children.forEach(child => { child.parent = null; }); this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { nodes.forEach(node => { node.remove(); node.parent = this; this.children.push(node); }); }
  insertBefore(node, reference) {
    node.remove();
    const index = this.children.indexOf(reference);
    node.parent = this;
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
  }
  replaceChildren(...nodes) { this.children.forEach(child => { child.parent = null; }); this.children = []; this._text = ''; this.append(...nodes); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
  dispatch(type, event = {}) { (this.handlers[type] || []).forEach(handler => handler({ target: this, preventDefault() {}, ...event })); }
  focus() {}
  closest() { return null; }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  querySelector(selector) {
    if (!selector.startsWith('.')) return null;
    return this.descendants().find(node => node.classList.contains(selector.slice(1))) || null;
  }
}

function deferred() {
  let resolve; let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

const json = data => ({ ok: true, status: 200, json: async () => data });
const conversation = (id, title) => ({ id, title, updated_at: '2026-11-19T12:00:00+00:00', message_count: 2, preview: '' });
const messages = (id, reply) => [
  { id: `${id}-u`, role: 'user', content: `Pregunta ${id}`, status: 'complete' },
  { id: `${id}-a`, role: 'assistant', content: reply, status: 'complete' },
];

function harness(conversations) {
  const ids = ['ia-thread', 'ia-empty', 'ia-scroll', 'ia-form', 'ia-text', 'ia-send', 'ia-send-label', 'ia-notice',
    'ia-counter', 'ia-history', 'ia-menu', 'ia-collapse', 'ia-scrim', 'ia-sidebar', 'ia-history-empty', 'ia-owner',
    'ia-retention', 'ia-back', 'ia-actions-menu', 'ia-plus', 'ia-actions-copy', 'ia-actions-stop', 'ia-new', 'ia-search'];
  const elements = Object.fromEntries(ids.map(id => [id, new Node('div', id)]));
  elements['ia-thread'].append(elements['ia-empty']);
  elements['ia-actions-menu'].hidden = true;
  const shell = new Node('div', 'ia-shell');
  const routes = new Map();
  const copied = [];
  const documentHandlers = {};
  const document = {
    referrer: '',
    querySelector: selector => (selector === '#ia-shell' ? shell : null),
    getElementById: id => elements[id] || null,
    createElement: tag => new Node(tag),
    addEventListener: (type, handler) => { (documentHandlers[type] ||= []).push(handler); },
  };
  const fetch = (url, options = {}) => {
    const key = `${options.method || 'GET'} ${url}`;
    const route = routes.get(key);
    if (!route) return Promise.reject(new Error(`Ruta no preparada: ${key}`));
    return route(options);
  };
  const context = vm.createContext({
    document, fetch, AbortController, TextDecoder, TextEncoder, URL, URLSearchParams, Intl,
    setTimeout, clearTimeout,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    location: { origin: 'http://localhost', pathname: '/ia', search: '', href: 'http://localhost/ia' },
    history: { replaceState() {} },
    navigator: { clipboard: { writeText: async text => { copied.push(text); } } },
  });
  routes.set('GET /api/ia/bootstrap', async () => json({
    owner: 'visitor', retention_days: 7, conversations,
    model: { enabled: true, status: 'available', model: 'sintetico' },
  }));
  const run = () => vm.runInContext(source, context);
  const historyRow = id => elements['ia-history'].children.find(row => row.dataset.id === id);
  const historyButton = id => historyRow(id)?.querySelector('.ia-history-open');
  const threadText = () => elements['ia-thread'].textContent;
  return { elements, routes, copied, run, historyRow, historyButton, threadText };
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));

test('a slow response for an earlier selection never replaces the latest one', async () => {
  const setup = harness([conversation('c', 'Inicial'), conversation('a', 'Lenta'), conversation('b', 'Rápida')]);
  setup.routes.set('GET /api/ia/conversations/c', async () => json({ conversation: conversation('c', 'Inicial'), messages: messages('c', 'Respuesta C') }));
  setup.run();
  await settle(); await settle();
  assert.match(setup.threadText(), /Respuesta C/);

  const slow = deferred();
  setup.routes.set('GET /api/ia/conversations/a', () => slow.promise);
  setup.routes.set('GET /api/ia/conversations/b', async () => json({ conversation: conversation('b', 'Rápida'), messages: messages('b', 'Respuesta B') }));
  setup.historyButton('a').dispatch('click');
  setup.historyButton('b').dispatch('click');
  await settle();
  assert.match(setup.threadText(), /Respuesta B/);

  slow.resolve(json({ conversation: conversation('a', 'Lenta'), messages: messages('a', 'Respuesta A') }));
  await settle(); await settle();
  assert.match(setup.threadText(), /Respuesta B/, 'the late response for A replaced the selected conversation B');
  assert.doesNotMatch(setup.threadText(), /Respuesta A/);
  assert.equal(setup.historyButton('b').getAttribute('aria-current'), 'true');
});

const actionNamed = (row, label) => row.querySelector('.ia-history-actions')?.children.find(button => button.textContent === label);

test('a conversation can be renamed from its history menu', async () => {
  const setup = harness([conversation('a', 'Título viejo')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Título viejo'), messages: messages('a', 'Respuesta A') }));
  const sent = [];
  setup.routes.set('PATCH /api/ia/conversations/a', async options => {
    sent.push(JSON.parse(options.body));
    return json({ conversation: conversation('a', 'Respaldo en casa') });
  });
  setup.run();
  await settle(); await settle();
  const row = setup.historyRow('a');
  row.querySelector('.ia-history-more').dispatch('click');
  actionNamed(row, 'Renombrar').dispatch('click');
  const field = row.querySelector('.ia-history-rename');
  assert.ok(field, 'rename field not shown');
  field.value = 'Respaldo en casa';
  field.dispatch('keydown', { key: 'Enter' });
  await settle(); await settle();
  assert.deepEqual(sent, [{ title: 'Respaldo en casa' }]);
  assert.match(setup.historyButton('a').textContent, /Respaldo en casa/);
});

test('deleting asks for confirmation and clears the open conversation', async () => {
  const setup = harness([conversation('a', 'Para borrar'), conversation('b', 'Se queda')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Para borrar'), messages: messages('a', 'Respuesta A') }));
  let deletes = 0;
  setup.routes.set('DELETE /api/ia/conversations/a', async () => { deletes += 1; return json({ deleted: 'a' }); });
  setup.run();
  await settle(); await settle();
  assert.match(setup.threadText(), /Respuesta A/);
  const row = setup.historyRow('a');
  row.querySelector('.ia-history-more').dispatch('click');
  actionNamed(row, 'Eliminar').dispatch('click');
  assert.equal(deletes, 0, 'deleted without confirmation');
  actionNamed(row, 'Eliminar definitivamente').dispatch('click');
  await settle(); await settle();
  assert.equal(deletes, 1);
  assert.equal(setup.historyRow('a'), undefined);
  assert.ok(setup.historyRow('b'));
  assert.doesNotMatch(setup.threadText(), /Respuesta A/);
});

test('switching conversation during a reply never moves that reply into the new one', async () => {
  const setup = harness([conversation('a', 'Primera'), conversation('b', 'Segunda')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Primera'), messages: [] }));
  setup.run();
  await settle(); await settle();

  // A streaming reply for A whose abort is delivered after B has already loaded.
  const encoder = new TextEncoder();
  const chunks = [`event: meta\ndata: ${JSON.stringify({ assistant_id: 'a-reply', conversation: conversation('a', 'Primera') })}\n\n`,
    `event: delta\ndata: ${JSON.stringify({ text: 'Respuesta parcial de A.' })}\n\n`];
  const pending = [];
  setup.routes.set('POST /api/ia/conversations/a/messages', async options => {
    options.signal.addEventListener('abort', () => {
      setTimeout(() => pending.splice(0).forEach(read => read.reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))), 5);
    });
    return { ok: true, status: 200, body: { getReader: () => ({
      read: () => {
        if (chunks.length) return Promise.resolve({ value: encoder.encode(chunks.shift()), done: false });
        const read = deferred(); pending.push(read); return read.promise;
      },
    }) } };
  });
  setup.routes.set('GET /api/ia/conversations/b', async () => json({ conversation: conversation('b', 'Segunda'), messages: messages('b', 'Respuesta B') }));

  setup.elements['ia-text'].value = 'Hola';
  setup.elements['ia-form'].dispatch('submit');
  await settle(); await settle();
  assert.match(setup.threadText(), /Respuesta parcial de A/);

  setup.historyButton('b').dispatch('click');
  await new Promise(resolve => setTimeout(resolve, 20));

  assert.match(setup.threadText(), /Respuesta B/);
  assert.doesNotMatch(setup.threadText(), /parcial de A/);
  assert.doesNotMatch(setup.elements['ia-notice'].textContent, /detenida/, 'A\'s stop notice was shown over B');

  // "Copy last reply" must copy B's reply, not A's interrupted text.
  setup.elements['ia-actions-menu'].dispatch('click', { target: { closest: () => ({ dataset: { iaMenu: 'copy' }, classList: { contains: () => false }, disabled: false }) } });
  await settle();
  assert.deepEqual(setup.copied, ['Respuesta B']);
});
