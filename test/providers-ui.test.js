const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const vm = require('node:vm');

test('provider sidebar opens a protected form, saves and activates, edits without exposing stored keys', async () => {
  const commands = new Map(), panels = [], calls = [], reloads = [];
  const disposable = () => ({ dispose() {} });
  class EventEmitter {
    constructor() { this.event = () => disposable(); }
    fire() {} dispose() {}
  }
  let data = { mode: 'official', providers: [], storage: 'fixture storage' };
  const vscode = {
    EventEmitter, TreeItemCollapsibleState: { Collapsed: 1 }, ViewColumn: { Active: 1 },
    TreeItem: class { constructor(label) { this.label = label; } }, ThemeIcon: class {}, ThemeColor: class {},
    commands: {
      registerCommand: (name, fn) => { commands.set(name, fn); return disposable(); },
      async executeCommand(name) { reloads.push(name); },
    },
    window: {
      createTreeView: (id, options) => ({ ...disposable(), provider: options.treeDataProvider }),
      createWebviewPanel: (id, title, column, options) => {
        const panel = { options, title, webview: {
          onDidReceiveMessage: fn => { panel.receive = fn; return disposable(); },
          postMessage: message => { panel.error = message; },
        }, onDidDispose: fn => { panel.closed = fn; return disposable(); },
        dispose() { panel.disposed = true; panel.closed?.(); } };
        panels.push(panel); return panel;
      },
      async showInformationMessage() {},
      async showQuickPick(items) { return items; },
      async showWarningMessage(message, options, ...choices) { return choices.includes('删除') ? '删除' : '只启用，稍后重载'; },
      async showErrorMessage(message) { throw new Error(message); },
    },
  };
  const original = Module._load;
  let createProviderUI;
  try {
    Module._load = function (name, parent, main) {
      return name === 'vscode' ? vscode : original.call(this, name, parent, main);
    };
    ({ createProviderUI } = require('../src/providers-ui'));
  } finally { Module._load = original; }
  const client = { async providerRequest(operation, payload) {
    calls.push({ operation, payload });
    if (operation === 'save') return { ...data, savedId: 'fixture-id', providers: [{
      id: 'fixture-id', name: payload.name, baseUrl: payload.baseUrl, model: payload.model, models: payload.models, hasKey: true,
    }] };
    if (operation === 'select') return { ...data, mode: 'thirdParty', activeId: payload.id, requiresReload: true,
      providers: data.providers.map(p => ({ ...p, selected: p.id === payload.id })) };
    if (operation === 'delete') return { ...data, providers: [] };
    if (operation === 'models') return { models: ['fixture-model', 'deepseek-fixture'], notice: 'fixture notice' };
    throw new Error('Unexpected fixture operation');
  } };
  const context = { subscriptions: [] };
  const ui = createProviderUI(context, client, {
    state: () => ({ providerState: data }), environmentLabel: 'fixture remote',
    update: next => { data = next; return next; }, run: action => action(),
  });
  try {
    await commands.get('cxAccounts.providerAdd')();
    const panel = panels[0];
    assert.equal(panel.options.enableScripts, true);
    assert.deepEqual(panel.options.localResourceRoots, []);
    assert.match(panel.webview.html, /default-src 'none'/);
    assert.match(panel.webview.html, /type="password"/);
    const script = panel.webview.html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
    assert.doesNotThrow(() => new vm.Script(script));
    await panel.receive({ type: 'save', enable: true, payload: {
      name: '<script>fixture</script>', baseUrl: 'https://example.invalid/v1', model: 'fixture-model', apiKey: 'fixture-key',
    } });
    assert.deepEqual(calls.map(c => c.operation), ['save', 'select']);
    assert.equal(calls[1].payload.id, 'fixture-id');
    assert.equal(data.activeId, 'fixture-id');
    assert.equal(panel.disposed, true);
    assert.equal(reloads.length, 0, 'save never reloads without user choosing it');
    ui.render();
    const row = ui.tree.provider.getChildren()[0];
    assert.match(ui.tree.provider.getTreeItem(row).label, /当前接入/);
    assert.ok(ui.tree.provider.getChildren(row).some(child => child.label === 'API Key 已保存'));
    await commands.get('cxAccounts.providerEdit')(row);
    assert.match(panels[1].webview.html, /&lt;script&gt;fixture&lt;\/script&gt;/);
    assert.ok(!panels[1].webview.html.includes('fixture-key'));
    assert.match(panels[1].webview.html, /留空保留/);
    assert.ok(!Object.hasOwn(data.providers[0], 'apiKey'));
    await commands.get('cxAccounts.providerModels')(row);
    assert.deepEqual(data.providers[0].models, ['fixture-model', 'deepseek-fixture']);
  } finally { context.subscriptions.forEach(d => d.dispose()); }
});
