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
  removeAttribute(name) { delete this.attributes[name]; }
  click() { this.dispatch('click'); }
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

function harness(conversations, options = {}) {
  const ids = ['ia-thread', 'ia-empty', 'ia-scroll', 'ia-form', 'ia-text', 'ia-send', 'ia-send-label', 'ia-notice',
    'ia-counter', 'ia-history', 'ia-menu', 'ia-collapse', 'ia-scrim', 'ia-sidebar', 'ia-history-empty', 'ia-owner',
    'ia-retention', 'ia-back', 'ia-actions-menu', 'ia-plus', 'ia-actions-copy', 'ia-actions-stop', 'ia-new', 'ia-search',
    'ia-actions-pdf', 'ia-actions-txt', 'ia-print-title', 'ia-print-date',
    'ia-attach', 'ia-file', 'ia-attach-tray', 'ia-attach-chip', 'ia-attach-name', 'ia-attach-meta',
    'ia-attach-remove', 'ia-attach-error', 'ia-actions-files', 'ia-actions-files-desc'];
  const elements = Object.fromEntries(ids.map(id => [id, new Node('div', id)]));
  elements['ia-actions-pdf'].dataset.iaMenu = 'export-pdf';
  elements['ia-actions-txt'].dataset.iaMenu = 'export-txt';
  elements['ia-thread'].append(elements['ia-empty']);
  elements['ia-actions-menu'].hidden = true;
  const shell = new Node('div', 'ia-shell');
  const routes = new Map();
  const copied = [];
  const downloads = [];
  const printed = [];
  const documentHandlers = {};
  const document = {
    referrer: '',
    querySelector: selector => (selector === '#ia-shell' ? shell : null),
    getElementById: id => elements[id] || null,
    createElement: tag => {
      const node = new Node(tag);
      // A download link records what it would save instead of saving it.
      if (tag === 'a') node.click = () => downloads.push({ name: node.download, url: node.href });
      return node;
    },
    addEventListener: (type, handler) => { (documentHandlers[type] ||= []).push(handler); },
  };
  const fetch = (url, options = {}) => {
    const key = `${options.method || 'GET'} ${url}`;
    const route = routes.get(key);
    if (!route) return Promise.reject(new Error(`Ruta no preparada: ${key}`));
    return route(options);
  };
  const blobs = new Map();
  const FakeURL = Object.assign(function FakeURL(...args) { return new URL(...args); }, {
    createObjectURL: blob => { const url = `blob:test/${blobs.size + 1}`; blobs.set(url, blob); return url; },
    revokeObjectURL: url => { blobs.delete(url); },
  });
  const context = vm.createContext({
    document, fetch, AbortController, TextDecoder, TextEncoder, URL: FakeURL, URLSearchParams, Intl, Blob,
    print: () => printed.push({
      title: elements['ia-print-title'].textContent, date: elements['ia-print-date'].textContent,
    }),
    setTimeout, clearTimeout,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    location: { origin: 'http://localhost', pathname: '/ia', search: options.search || '', href: `http://localhost/ia${options.search || ''}` },
    ...(options.storage ? { sessionStorage: options.storage } : {}),
    history: { replaceState() {} },
    navigator: { clipboard: { writeText: async text => { copied.push(text); } } },
  });
  routes.set('GET /api/ia/bootstrap', async () => json({
    owner: 'visitor', retention_days: 7, conversations,
    model: { enabled: true, status: 'available', model: 'sintetico' },
    ...(options.attachments ? { attachments: options.attachments } : {}),
  }));
  const run = () => vm.runInContext(source, context);
  const historyRow = id => elements['ia-history'].children.find(row => row.dataset.id === id);
  const historyButton = id => historyRow(id)?.querySelector('.ia-history-open');
  const threadText = () => elements['ia-thread'].textContent;
  const blobOf = url => blobs.get(url);
  return { elements, routes, copied, downloads, printed, blobOf, run, historyRow, historyButton, threadText };
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

test('choosing a suggested question sends it at once, without pasting it first', async () => {
  const setup = harness([conversation('a', 'Primera')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Primera'), messages: [] }));
  const sent = [];
  const encoder = new TextEncoder();
  setup.routes.set('POST /api/ia/conversations/a/messages', async options => {
    sent.push(JSON.parse(options.body).text);
    const chunks = [
      `event: meta\ndata: ${JSON.stringify({ assistant_id: 'a-r', conversation: conversation('a', 'Primera') })}\n\n`,
      `event: delta\ndata: ${JSON.stringify({ text: 'Una persona del equipo revisa la factura.' })}\n\n`,
      `event: done\ndata: ${JSON.stringify({ assistant: { id: 'a-r', role: 'assistant', content: 'Una persona del equipo revisa la factura.', status: 'complete' }, conversation: conversation('a', 'Primera') })}\n\n`,
    ];
    return { ok: true, status: 200, body: { getReader: () => ({
      read: () => Promise.resolve(chunks.length ? { value: encoder.encode(chunks.shift()), done: false } : { value: undefined, done: true }),
    }) } };
  });
  setup.run();
  await settle(); await settle();

  const question = '¿Cómo se evalúa un hogar antes de proponer un sistema solar?';
  setup.elements['ia-thread'].dispatch('click', { target: { closest: selector => (selector === '[data-ia-prompt]' ? { dataset: { iaPrompt: question } } : null) } });
  await new Promise(resolve => setTimeout(resolve, 20));

  assert.deepEqual(sent, [question]);
  assert.equal(setup.elements['ia-text'].value, '', 'the field is left empty after sending');
  assert.match(setup.threadText(), /revisa la factura/);
});

function memoryStorage(entries = {}) {
  const data = new Map(Object.entries(entries));
  return {
    data,
    getItem: key => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: key => data.delete(key),
  };
}

function autoSendSetup(storage) {
  const question = 'Quiero entender cómo evaluar el consumo y los costos de energía de mi hogar.';
  const setup = harness([], { search: `?q=${encodeURIComponent(question)}`, storage });
  const sent = [];
  const encoder = new TextEncoder();
  setup.routes.set('POST /api/ia/conversations', async () => json({ conversation: conversation('n', 'Nueva') }));
  setup.routes.set('POST /api/ia/conversations/n/messages', async options => {
    sent.push(JSON.parse(options.body).text);
    const chunks = [`event: done\ndata: ${JSON.stringify({ assistant: { id: 'n-r', role: 'assistant', content: 'Respuesta.', status: 'complete' }, conversation: conversation('n', 'Nueva') })}\n\n`];
    return { ok: true, status: 200, body: { getReader: () => ({
      read: () => Promise.resolve(chunks.length ? { value: encoder.encode(chunks.shift()), done: false } : { value: undefined, done: true }),
    }) } };
  });
  return { setup, sent, question };
}

test('a topic clicked on the site (one-time authorization) is sent at once in /ia', async () => {
  const storage = memoryStorage();
  const { setup, sent, question } = autoSendSetup(storage);
  storage.setItem('ia:autosend', JSON.stringify({ pregunta: question, timestamp: Date.now() }));
  setup.run();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.deepEqual(sent, [question]);
  assert.equal(storage.getItem('ia:autosend'), null, 'the authorization is single use');
});

test('a shared link /ia?q=… without authorization only fills the field', async () => {
  const { setup, sent, question } = autoSendSetup(memoryStorage());
  setup.run();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.deepEqual(sent, []);
  assert.equal(setup.elements['ia-text'].value, question);
});

test('an expired or mismatched authorization does not send', async () => {
  for (const saved of [
    { pregunta: 'Quiero entender cómo evaluar el consumo y los costos de energía de mi hogar.', timestamp: Date.now() - 31000 },
    { pregunta: 'Otra pregunta distinta', timestamp: Date.now() },
  ]) {
    const storage = memoryStorage({ 'ia:autosend': JSON.stringify(saved) });
    const { setup, sent } = autoSendSetup(storage);
    setup.run();
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.deepEqual(sent, []);
    assert.equal(storage.getItem('ia:autosend'), null, 'a rejected authorization is still consumed');
  }
});


test('a fast double click on a suggestion sends it only once', async () => {
  const setup = harness([]);
  let created = 0;
  const sent = [];
  const encoder = new TextEncoder();
  setup.routes.set('POST /api/ia/conversations', async () => {
    created += 1;
    await new Promise(resolve => setTimeout(resolve, 10));
    return json({ conversation: conversation('n', 'Nueva') });
  });
  setup.routes.set('POST /api/ia/conversations/n/messages', async options => {
    sent.push(JSON.parse(options.body).text);
    const chunks = [`event: done\ndata: ${JSON.stringify({ assistant: { id: 'n-r', role: 'assistant', content: 'Ok.', status: 'complete' }, conversation: conversation('n', 'Nueva') })}\n\n`];
    return { ok: true, status: 200, body: { getReader: () => ({
      read: () => Promise.resolve(chunks.length ? { value: encoder.encode(chunks.shift()), done: false } : { value: undefined, done: true }),
    }) } };
  });
  setup.run();
  await settle(); await settle();
  const click = { target: { closest: selector => (selector === '[data-ia-prompt]' ? { dataset: { iaPrompt: '¿Qué es la medición neta?' } } : null) } };
  setup.elements['ia-thread'].dispatch('click', click);
  setup.elements['ia-thread'].dispatch('click', click);
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(created, 1);
  assert.deepEqual(sent, ['¿Qué es la medición neta?']);
});

test('a connection error keeps the chosen question in the field', async () => {
  const setup = harness([conversation('a', 'Primera')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Primera'), messages: [] }));
  setup.routes.set('POST /api/ia/conversations/a/messages', async () => { throw new Error('Sin conexión'); });
  setup.run();
  await settle(); await settle();
  setup.elements['ia-thread'].dispatch('click', { target: { closest: selector => (selector === '[data-ia-prompt]' ? { dataset: { iaPrompt: '¿Qué es la medición neta?' } } : null) } });
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(setup.elements['ia-text'].value, '¿Qué es la medición neta?');
  assert.match(setup.elements['ia-notice'].textContent, /conexión|Sin/i);
});

// --- «Descargar conversación»: client-side export (text Blob and print to PDF) ---

const openMenu = setup => setup.elements['ia-plus'].dispatch('click', { detail: 1 });
const chooseItem = (setup, id) => {
  const item = setup.elements[id];
  setup.elements['ia-actions-menu'].dispatch('click', { target: { closest: () => item } });
};

test('export is unavailable while the conversation is empty', async () => {
  const setup = harness([]);
  setup.run();
  await settle(); await settle();
  openMenu(setup);
  assert.equal(setup.elements['ia-actions-txt'].getAttribute('aria-disabled'), 'true');
  assert.equal(setup.elements['ia-actions-pdf'].getAttribute('aria-disabled'), 'true');
  chooseItem(setup, 'ia-actions-txt');
  chooseItem(setup, 'ia-actions-pdf');
  await settle();
  assert.deepEqual(setup.downloads, []);
  assert.deepEqual(setup.printed, []);
});

test('the text export holds the conversation as plain text, with header and notice', async () => {
  const tricky = 'Mira <img src=x onerror=alert(1)> y\u0007 sigue.\r\nSegunda línea.';
  const setup = harness([conversation('a', 'Batería <b>y</b> apagones')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({
    conversation: conversation('a', 'Batería <b>y</b> apagones'),
    messages: [
      { id: 'a-u', role: 'user', content: '¿Cuánto dura?', status: 'complete' },
      { id: 'a-a', role: 'assistant', content: tricky, status: 'stopped' },
    ],
  }));
  setup.run();
  await settle(); await settle();
  openMenu(setup);
  assert.equal(setup.elements['ia-actions-txt'].getAttribute('aria-disabled'), undefined);
  chooseItem(setup, 'ia-actions-txt');
  await settle();

  assert.equal(setup.downloads.length, 1);
  const [download] = setup.downloads;
  assert.match(download.name, /^reigel-conversacion-\d{4}-\d{2}-\d{2}\.txt$/);
  const blob = setup.blobOf(download.url);
  assert.equal(blob.type, 'text/plain;charset=utf-8');
  const text = await blob.text();
  assert.ok(text.startsWith('Power Solar · R.E.I.G.E.L. · Conversación con IA\r\n'));
  assert.match(text, /Conversación: Batería <b>y<\/b> apagones\r\n/);
  assert.match(text, /Exportada: .+\(hora de Puerto Rico\)\r\n/);
  assert.match(text, /Tú:\r\n¿Cuánto dura\?\r\n/);
  // Plain text: kept literally (never interpreted), control characters removed.
  assert.match(text, /R\.E\.I\.G\.E\.L\.:\r\nMira <img src=x onerror=alert\(1\)> y sigue\.\r\nSegunda línea\.\r\n/);
  assert.doesNotMatch(text, /\u0007/);
  assert.match(text, /\(Respuesta detenida antes de completarse\.\)/);
  assert.match(text, /puede equivocarse\. Confirma los datos importantes con el equipo\.\r\n$/);
  assert.doesNotMatch(text.replace(/\r\n/g, ''), /\n/, 'every line ends in CRLF');
  assert.match(setup.elements['ia-notice'].textContent, /descargada como texto/);
});

test('saving as PDF fills the print header and opens the browser print dialog', async () => {
  const setup = harness([conversation('a', 'Respaldo')]);
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Respaldo'), messages: messages('a', 'Respuesta A') }));
  setup.run();
  await settle(); await settle();
  openMenu(setup);
  chooseItem(setup, 'ia-actions-pdf');
  await settle();
  assert.equal(setup.printed.length, 1);
  assert.equal(setup.printed[0].title, 'Respaldo');
  assert.match(setup.printed[0].date, /^Exportada: .+\(hora de Puerto Rico\)$/);
  assert.deepEqual(setup.downloads, [], 'the PDF path never creates a file itself');
});

// --- Adjuntar documento: the browser sends the raw file; the chip shows server metadata ---

const LIMITS = { max_bytes: 3 * 1024 * 1024, max_pages: 15, max_chars: 12000, formats: ['PDF', '.txt', '.md'] };
const doneStream = (id, text) => {
  const encoder = new TextEncoder();
  const chunks = [`event: done\ndata: ${JSON.stringify({ assistant: { id: `${id}-r`, role: 'assistant', content: text, status: 'complete' }, conversation: conversation(id, 'Doc') })}\n\n`];
  return { ok: true, status: 200, body: { getReader: () => ({
    read: () => Promise.resolve(chunks.length ? { value: encoder.encode(chunks.shift()), done: false } : { value: undefined, done: true }),
  }) } };
};

test('without server support the attachment controls stay hidden and disabled', async () => {
  const setup = harness([]);
  setup.run();
  await settle(); await settle();
  assert.equal(setup.elements['ia-attach'].hidden, true);
  assert.equal(setup.elements['ia-actions-files'].getAttribute('aria-disabled'), 'true');
});

test('a chosen document is uploaded raw, shown as a chip and sent with the next message', async () => {
  const setup = harness([conversation('a', 'Doc')], { attachments: LIMITS });
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Doc'), messages: [] }));
  const uploads = [];
  setup.routes.set('POST /api/ia/conversations/a/attachments', async options => {
    uploads.push(options);
    return { ok: true, status: 201, json: async () => ({ attachment: { id: 'f1', name: 'factura <b>.pdf', kind: 'pdf', size_bytes: 2048, pages: 2, chars: 900, truncated: false } }) };
  });
  const sent = [];
  setup.routes.set('POST /api/ia/conversations/a/messages', async options => { sent.push(JSON.parse(options.body)); return doneStream('a', 'Listo.'); });
  setup.run();
  await settle(); await settle();
  assert.equal(setup.elements['ia-attach'].hidden, false);
  assert.equal(setup.elements['ia-actions-files'].getAttribute('aria-disabled'), undefined);
  assert.match(setup.elements['ia-actions-files-desc'].textContent, /PDF, \.txt o \.md · hasta 3 MB y 15 páginas/);

  const file = { name: 'factura <b>.pdf', size: 2048 };
  setup.elements['ia-file'].dispatch('change', { target: { files: [file] } });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].body, file, 'the raw file is the body');
  assert.equal(uploads[0].headers['X-Attachment-Name'], encodeURIComponent('factura <b>.pdf'));
  assert.equal(setup.elements['ia-attach-chip'].hidden, false);
  assert.equal(setup.elements['ia-attach-name'].textContent, 'factura <b>.pdf', 'names are text, never HTML');
  assert.match(setup.elements['ia-attach-meta'].textContent, /2 KB · 2 páginas/);
  assert.equal(setup.elements['ia-text'].required, false, 'a document alone can be sent');

  setup.elements['ia-text'].value = '¿Qué dice?';
  setup.elements['ia-form'].dispatch('submit');
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(sent, [{ text: '¿Qué dice?', attachment_id: 'f1' }]);
  assert.equal(setup.elements['ia-attach-chip'].hidden, true, 'the chip clears once sent');
  assert.match(setup.threadText(), /Documento adjunto: factura <b>\.pdf/);
});

test('files that are too large or of another format are refused before uploading', async () => {
  const setup = harness([conversation('a', 'Doc')], { attachments: LIMITS });
  setup.routes.set('GET /api/ia/conversations/a', async () => json({ conversation: conversation('a', 'Doc'), messages: [] }));
  let uploads = 0;
  setup.routes.set('POST /api/ia/conversations/a/attachments', async () => { uploads += 1; return json({}); });
  setup.run();
  await settle(); await settle();
  setup.elements['ia-file'].dispatch('change', { target: { files: [{ name: 'foto.png', size: 10 }] } });
  await settle();
  assert.match(setup.elements['ia-attach-error'].textContent, /Formato no admitido/);
  assert.equal(setup.elements['ia-attach-error'].hidden, false);
  setup.elements['ia-file'].dispatch('change', { target: { files: [{ name: 'grande.pdf', size: 3 * 1024 * 1024 + 1 }] } });
  await settle();
  assert.match(setup.elements['ia-attach-error'].textContent, /supera el máximo de 3 MB/);
  assert.equal(uploads, 0);
});

test('a server refusal is shown in the tray and a pending document can be removed', async () => {
  const setup = harness([conversation('a', 'Doc')], { attachments: LIMITS });
  setup.routes.set('GET /api/ia/conversations/a', async () => json({
    conversation: conversation('a', 'Doc'), messages: [],
    pending_attachment: { id: 'f9', name: 'notas.md', kind: 'md', size_bytes: 500, pages: null, chars: 500, truncated: false },
  }));
  setup.routes.set('POST /api/ia/conversations/a/attachments', async () => ({
    ok: false, status: 422, json: async () => ({ detail: 'El PDF está protegido con contraseña o cifrado.' }),
  }));
  const removed = [];
  setup.routes.set('DELETE /api/ia/conversations/a/attachments/f9', async () => { removed.push('f9'); return json({ removed: 'f9' }); });
  setup.run();
  await settle(); await settle();
  assert.equal(setup.elements['ia-attach-name'].textContent, 'notas.md', 'a pending document is restored');
  setup.elements['ia-file'].dispatch('change', { target: { files: [{ name: 'cifrado.pdf', size: 100 }] } });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.match(setup.elements['ia-attach-error'].textContent, /protegido con contraseña/);
  assert.equal(setup.elements['ia-attach-name'].textContent, 'notas.md', 'the earlier document stays attached');
  setup.elements['ia-attach-remove'].dispatch('click');
  await settle();
  assert.deepEqual(removed, ['f9']);
  assert.equal(setup.elements['ia-attach-chip'].hidden, true);
});
