'use strict';

// «Aprendizaje» rendering without a browser or network: escaping and role-gated buttons.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const source = readFileSync(path.join(root, 'frontend/js/learning.js'), 'utf8');

function load(role) {
  const context = vm.createContext({
    state: { user: { id: 'u1', role } },
    esc: value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  });
  vm.runInContext(`${source}
    function actionButton(action,label,extra='',kind='primary'){return '<button data-action="'+esc(action)+'" '+extra+'>'+esc(label)+'</button>';}
    function badge(value,label){return '<span class="badge">'+esc(label||value)+'</span>';}
    function empty(title){return '<p>'+esc(title)+'</p>';}
    this.row = learningGapRow; this.evalPanel = learningEvalPanel;`, context);
  return context;
}

const gap = { id: 'g1', question: '<img src=x onerror=alert(1)>¿Mi techo?', route: 'ia', reason: 'blocked', topic: 'techo',
  occurrences: 2, last_seen_local: '2026-11-25 10:00', priority: 45.5, status: 'open', pending_proposals: 1 };

test('gap rows escape visitor-derived text', () => {
  const html = load('admin').row(gap);
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
});

test('advisors can propose but see no admin decisions', () => {
  const html = load('advisor').row(gap);
  assert.ok(html.includes('data-action="learning-propose"'));
  assert.ok(!html.includes('learning-dismiss'));
  assert.ok(!html.includes('learning-resolve'));
  const approved = load('advisor').row({ ...gap, status: 'approved' });
  assert.ok(!approved.includes('learning-propose') && !approved.includes('learning-resolve'));
});

test('admins see dismiss and resolve where they apply', () => {
  assert.ok(load('admin').row(gap).includes('data-action="learning-dismiss"'));
  assert.ok(load('admin').row({ ...gap, status: 'approved' }).includes('data-action="learning-resolve"'));
});

test('the latest bank run is escaped and only admins get the run button', () => {
  const data = { can_run: false, running: false, error: '', latest: { model: 'qwen2.5:3b', finished_local: 'hoy', summary: '7 de 10 casos pasan.',
    results: [{ case_id: 'reserva', ok: false, replaced: false, failed: [{ description: 'Remite a «Citas y equipo».' }], published: '<b>Reservaste</b>' }] } };
  const html = load('advisor').evalPanel(data);
  assert.ok(html.includes('&lt;b&gt;Reservaste&lt;/b&gt;') && !html.includes('<b>'));
  assert.ok(!html.includes('learning-run-eval'));
  assert.ok(load('admin').evalPanel({ ...data, can_run: true }).includes('learning-run-eval'));
});
