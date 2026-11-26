'use strict';

// Exercise the actual form controllers with synthetic elements, without a browser,
// credentials, network requests, or access to an application database.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const operationsSource = readFileSync(path.join(root, 'frontend/js/operations.js'), 'utf8');
const appSource = readFileSync(path.join(root, 'frontend/js/app.js'), 'utf8');

class Element {
  constructor(value = '') {
    this.value = value;
    this.isConnected = true;
    this.textContent = '';
    this.handlers = {};
  }
  addEventListener(type, handler) { this.handlers[type] = handler; }
  emit(type) { return this.handlers[type]?.({ target: this }); }
}

class Select extends Element {
  set innerHTML(html) {
    this.options = [...html.matchAll(/<option value="([^"]*)"([^>]*)>([\s\S]*?)<\/option>/g)]
      .map(([, value, attributes, label]) => ({ value, selected: /\bselected\b/.test(attributes), label }));
    this.value = (this.options.find(option => option.selected) || this.options[0])?.value || '';
  }
}

function harness(overrides = {}) {
  const timers = [];
  const context = vm.createContext({
    state: { leads: [], users: [], user: { id: 'admin', role: 'admin' } },
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'),
    URLSearchParams, Intl, Date,
    setTimeout: callback => { timers.push(callback); return callback; },
    clearTimeout: callback => { const index = timers.indexOf(callback); if (index >= 0) timers.splice(index, 1); },
    ...overrides,
  });
  vm.runInContext(operationsSource, context);
  return { context, flush: () => timers.shift()?.() };
}

function leadSearchHarness(result) {
  const original = { id: 'original', name: 'Prospecto original', advisor_id: 'advisor-b' };
  const setup = harness({ api: async () => result });
  setup.context.state.leads = [original];
  const input = new Element();
  const select = new Select();
  select.innerHTML = '<option value="">Sin prospecto</option><option value="original" selected>Prospecto original</option>';
  const status = new Element();
  setup.context.bindLeadSearch(input, select, status, 'Sin prospecto');
  return { ...setup, input, select, status, original };
}

test('searching without matches preserves the selected prospect and its advisor', async () => {
  const setup = leadSearchHarness({ leads: [], total: 0 });
  setup.input.value = 'sin coincidencias';
  setup.input.emit('input');
  await setup.flush();
  assert.equal(setup.select.value, 'original');
  assert.equal(setup.context.state.leads.find(lead => lead.id === 'original')?.advisor_id, 'advisor-b');
  assert.match(setup.status.textContent, /^0 coincidencias/);
});

test('searching for another prospect requires an explicit selection to replace the current one', async () => {
  const setup = leadSearchHarness({ leads: [{ id: 'other', name: 'Otro prospecto' }], total: 1 });
  setup.input.emit('input');
  await setup.flush();
  assert.equal(setup.select.value, 'original');
  assert.ok(setup.select.options.some(option => option.value === 'other'));
  setup.select.value = 'other';
  assert.equal(setup.select.value, 'other');
});

test('an explicitly cleared prospect is not restored by a subsequent search', async () => {
  const setup = leadSearchHarness({ leads: [{ id: 'other', name: 'Otro prospecto' }], total: 1 });
  setup.select.value = '';
  setup.input.emit('input');
  await setup.flush();
  assert.equal(setup.select.value, '');
});

test('an older failed search cannot overwrite the status of a newer successful search', async () => {
  let rejectOld;
  const setup = leadSearchHarness({ leads: [], total: 0 });
  setup.context.api = url => url.includes('old')
    ? new Promise((resolve, reject) => { rejectOld = reject; })
    : Promise.resolve({ leads: [{ id: 'new', name: 'Resultado nuevo' }], total: 1 });
  setup.input.value = 'old';
  setup.input.emit('input');
  const pending = setup.flush();
  setup.input.value = 'new';
  setup.input.emit('input');
  await setup.flush();
  const currentStatus = setup.status.textContent;
  rejectOld(new Error('Fallo de búsqueda anterior'));
  await pending;
  assert.equal(setup.status.textContent, currentStatus);
});

test('the pipeline board groups every record by stage and honors an active stage filter', () => {
  const setup = harness();
  const leads = [
    { id: 'a', stage: 'nuevo' },
    { id: 'b', stage: 'nuevo' },
    { id: 'c', stage: 'ganado' },
    { id: 'd', stage: 'perdido' },
  ];
  const groups = setup.context.pipelineGroups(leads, '');
  assert.equal(groups.length, 11);
  assert.equal(groups.filter(group => group.leads.length).map(group => group.stage).join(','), 'nuevo,ganado,perdido');
  assert.equal(groups.find(group => group.stage === 'nuevo').leads.length, 2);
  const filtered = setup.context.pipelineGroups(leads, 'ganado');
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].stage, 'ganado');
  assert.equal(filtered[0].leads.length, 1);
});

function appointmentHarness(role = 'admin', assignedAdvisor = 'advisor-b') {
  const leads = [
    { id: 'lead-a', name: 'Prospecto A', advisor_id: 'advisor-a' },
    { id: 'lead-b', name: 'Prospecto B', advisor_id: assignedAdvisor },
  ];
  const users = [
    { id: 'advisor-a', name: 'Asesor A', active: true, public_booking: true },
    { id: 'advisor-b', name: 'Asesor B', active: true, public_booking: true },
  ];
  const elements = new Map();
  for (const selector of ['#appointment-lead-search', '#appointment-date', '#appointment-start', '#appointment-slots', '#appointment-zone', '#appointment-lead-search-status', '#appointment-assignment-note', '#appointment-form']) elements.set(selector, new Element());
  elements.set('#appointment-lead-select', new Select());
  elements.set('#appointment-advisor', new Select());
  elements.set('#dialog-content', {
    set innerHTML(html) {
      for (const id of ['appointment-lead-select', 'appointment-advisor']) {
        const match = html.match(new RegExp(`<select[^>]*id="${id}"[^>]*>([\\s\\S]*?)<\\/select>`));
        if (match) elements.get('#' + id).innerHTML = match[1];
      }
      elements.get('#appointment-date').value = '2026-11-11';
    },
  });
  const setup = harness({
    $: selector => elements.get(selector),
    openDialog() {}, loading: () => '',
    dateInput: () => '2026-11-11',
    loadLeads: async () => leads,
    loadUsers: async () => users,
  });
  setup.context.state = { leads, users, user: { id: role === 'admin' ? 'admin' : 'advisor-b', role } };
  const slotQueries = [];
  setup.context.loadSlots = async (...args) => { slotQueries.push(args.slice(0, 2)); };
  vm.runInContext(appSource.slice(appSource.indexOf('async function newAppointment('), appSource.indexOf('async function loadSlots(')), setup.context);
  return { ...setup, elements, slotQueries };
}

test('booking from a CRM profile selects its assigned advisor before loading slots', async () => {
  const setup = appointmentHarness();
  await setup.context.newAppointment('lead-b');
  assert.equal(setup.elements.get('#appointment-advisor').value, 'advisor-b');
  assert.equal(setup.slotQueries[0][0], 'advisor-b');
});

test('changing the prospect updates the booking advisor and available slots', async () => {
  const setup = appointmentHarness();
  await setup.context.newAppointment('lead-a');
  const leadSelect = setup.elements.get('#appointment-lead-select');
  leadSelect.value = 'lead-b';
  await leadSelect.emit('change');
  assert.equal(setup.elements.get('#appointment-advisor').value, 'advisor-b');
  assert.equal(setup.slotQueries.at(-1)[0], 'advisor-b');
});

test('an advisor can select only their own booking calendar', async () => {
  const setup = appointmentHarness('advisor');
  await setup.context.newAppointment('lead-b');
  const available = setup.elements.get('#appointment-advisor').options.filter(option => option.value);
  assert.deepEqual(available.map(option => option.value), ['advisor-b']);
});

test('an unavailable assigned advisor is not silently replaced by the first calendar', async () => {
  const setup = appointmentHarness('admin', 'unavailable-advisor');
  await setup.context.newAppointment('lead-b');
  assert.equal(setup.elements.get('#appointment-advisor').value, '');
  assert.equal(setup.slotQueries[0][0], '');
});

test('choosing a different advisor explains the reassignment before booking', async () => {
  const setup = appointmentHarness();
  await setup.context.newAppointment('lead-b');
  const advisor = setup.elements.get('#appointment-advisor');
  advisor.value = 'advisor-a';
  await advisor.emit('change');
  assert.match(setup.elements.get('#appointment-assignment-note').textContent, /asignar|pasar|responsable/i);
  assert.match(setup.elements.get('#appointment-assignment-note').textContent, /Asesor A/);
});

test('searching without replacing a prospect preserves a manually chosen booking advisor', async () => {
  const setup = appointmentHarness();
  setup.context.api = async () => ({ leads: [], total: 0 });
  await setup.context.newAppointment('lead-b');
  const advisor = setup.elements.get('#appointment-advisor');
  advisor.value = 'advisor-a';
  await advisor.emit('change');
  const queryCount = setup.slotQueries.length;
  const search = setup.elements.get('#appointment-lead-search');
  search.value = 'sin coincidencias';
  search.emit('input');
  await setup.flush();
  assert.equal(setup.elements.get('#appointment-lead-select').value, 'lead-b');
  assert.equal(advisor.value, 'advisor-a');
  assert.equal(setup.slotQueries.length, queryCount);
});
