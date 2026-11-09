// Execute the actual controller with deterministic DOM and HTTP boundaries.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('src/foot_web/static/analysis.js', 'utf8');

class Element {
  constructor() {
    this.dataset = {}; this.listeners = {}; this.attrs = {}; this.hidden = false;
    this.children = []; this.checked = true; this.value = ''; this.textContent = '';
    this.classList = {toggle() {}, contains() { return false; }, add() {}};
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  querySelector(selector) { return selector === 'use' ? (this.glyph ||= new Element()) : (this.label ||= new Element()); }
  append() {}
  replaceChildren() { this.children = []; }
}

function boot(row) {
  const elements = {};
  const get = id => elements[id] ||= new Element();
  const initial = get('analysis-task-data');
  initial.textContent = JSON.stringify(row.task);
  const button = get('btn-recompute');
  button.dataset.analysisDate = '2026-11-09';
  button.dataset.analysisMode = row.action.mode;
  button.querySelector('span').textContent = row.action.label;
  button.title = row.action.title;
  button.disabled = row.action.disabled;
  const cancel = new Element();
  const requests = [];
  const toasts = [];
  const context = {
    document: {getElementById(id) { return ['analysis-attempt-rows', 'research-match-list'].includes(id) ? null : get(id); },
      querySelector() { return null; },
      querySelectorAll(selector) { return selector === '[data-analysis-action="cancel"]' ? [cancel] : []; },
      addEventListener() {}, createDocumentFragment() { return new Element(); }},
    window: {FOOT: {csrf: 'isolated', toast: message => toasts.push(message)}, addEventListener() {}},
    fetch(url, options) { return new Promise(resolve => requests.push({url, options, resolve})); },
    setInterval() {}, clearInterval() {}, setTimeout() {}, clearTimeout() {},
    AbortSignal, AbortController, Date, location: {assign() { throw new Error('unexpected navigation'); }}
  };
  get('analysis-result').firstChild = new Element();
  vm.runInNewContext(source, context);
  return {get, button, cancel, requests, toasts};
}

async function main() {
  for (const row of cases) {
    const ui = boot(row);
    assert.equal(ui.button.querySelector('span').textContent, row.action.label);
    assert.equal(ui.button.disabled, row.action.disabled);
    assert.equal(ui.get('analysis-workspace').hidden, !row.task);
  }
  const first = boot(cases[0]);
  const click = first.button.listeners.click();
  assert.equal(first.button.querySelector('span').textContent, '正在提交…');
  assert.equal(first.button.disabled, true);
  const queued = cases.find(row => row.task?.status === 'queued').task;
  first.requests[0].resolve({ok: true, json: async () => ({success: true, task: queued, reused: false})});
  await click;
  assert.equal(first.button.querySelector('span').textContent, '等待分析');
  const stop = first.cancel.listeners.click();
  assert.equal(first.button.querySelector('span').textContent, '正在终止…');
  const cancelled = cases.find(row => row.task?.status === 'cancelled' && !row.task.attempts.length).task;
  first.requests.find(row => row.url.endsWith('/cancel')).resolve({ok: true, json: async () => ({task: cancelled})});
  await stop;
  assert.equal(first.button.querySelector('span').textContent, '开始分析');
  assert.equal(first.button.disabled, false);
  assert.equal(first.get('analysis-title').textContent, '任务已取消 · 尚未开始分析');

  const busy = boot(cases[0]);
  const submitBusy = busy.button.listeners.click();
  busy.requests[0].resolve({ok: false, json: async () => ({success: false, message: '2026-11-08 任务正在执行'})});
  await submitBusy;
  assert.equal(busy.button.querySelector('span').textContent, '开始分析');
  assert.equal(busy.get('analysis-title').textContent, '分析提交未完成');
  assert.ok(busy.toasts.includes('2026-11-08 任务正在执行'));
  console.log('Actual analysis.js: initial states, submit, queued, cancel-before-run, cross-day busy passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
