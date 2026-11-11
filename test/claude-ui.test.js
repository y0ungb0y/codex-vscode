const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const vm = require('node:vm');

test('Claude sidebar isolates commands, reserves account/history UI, saves aliases and manages login prompt', async () => {
  const commands = new Map(), trees = new Map(), panels = [], calls = [], updates = [], notices = [], errors = [];
  const disposable = () => ({ dispose() {} });
  class EventEmitter { constructor() { this.event = () => disposable(); } fire() {} dispose() {} }
  const values = new Map();
  const config = {
    get: (key, fallback) => values.has(key) ? values.get(key) : fallback,
    inspect: () => ({ globalValue: false }),
    async update(key, value) { updates.push([key, value]); values.set(key, value); },
  };
  const vscode = {
    EventEmitter, ThemeIcon: class {}, ThemeColor: class {}, RelativePattern: class {},
    TreeItem: class { constructor(label) { this.label = label; } },
    TreeItemCollapsibleState: { Collapsed: 1 }, ViewColumn: { Active: 1 }, ConfigurationTarget: { Global: 1 },
    commands: { registerCommand(name, handler) { commands.set(name, handler); return disposable(); } },
    workspace: {
      getConfiguration: () => config,
      createFileSystemWatcher: () => ({ ...disposable(), onDidCreate: () => disposable(), onDidChange: () => disposable(), onDidDelete: () => disposable() }),
    },
    window: {
      createTreeView(id, options) { const tree = { ...disposable(), provider: options.treeDataProvider, onDidChangeVisibility: () => disposable() }; trees.set(id, tree); return tree; },
      createWebviewPanel() {
        const panel = { webview: { onDidReceiveMessage: fn => { panel.receive = fn; return disposable(); }, postMessage(message) { panel.message = message; } },
          onDidDispose: fn => { panel.closed = fn; return disposable(); }, dispose() { panel.closed?.(); } };
        panels.push(panel); return panel;
      },
      async showErrorMessage(message) { errors.push(message); },
      async showInformationMessage() { throw new Error('Unexpected information popup'); },
      async showWarningMessage() { throw new Error('Unexpected warning popup'); },
    },
  };
  const original = Module._load;
  let createClaudeUI;
  try {
    Module._load = function (name, parent, main) { return name === 'vscode' ? vscode : original.call(this, name, parent, main); };
    ({ createClaudeUI } = require('../src/claude-ui'));
  } finally { Module._load = original; }
  const state = { providers: [], mode: 'unconfigured' };
  const client = { async claudeRequest(operation, payload = {}) {
    calls.push({ operation, payload });
    if (operation === 'save') { state.providers = [{ ...payload, id: 'fixture-id', apiKey: undefined, hasKey: true }]; return { ...state, savedId: 'fixture-id' }; }
    if (operation === 'select') { state.activeId = payload.id; state.mode = 'thirdParty'; state.canRestore = true; return { ...state, requiresReload: true }; }
    if (operation === 'restore') return { ...state, activeId: null, requiresReload: true };
    if (operation === 'import-cc') return { ...state, imported: 2, skipped: 1 };
    if (operation === 'test') return { ok: true, message: 'fixture success' };
    return state;
  } };
  const storage = new Map();
  const context = { subscriptions: [], globalState: { get: key => storage.get(key), async update(key, value) { storage.set(key, value); } } };
  const ui = createClaudeUI(context, client, { environmentLabel: 'fixture', run: action => action(), notice: message => notices.push(message) }, () => ({}));
  try {
    await ui.refresh();
    assert.equal(commands.has('cxAccounts.providerSwitch'), false);
    for (const section of ['accounts', 'history']) {
      const provider = trees.get(`cxClaude.${section}`).provider;
      const item = provider.getTreeItem(provider.getChildren()[0]);
      assert.match(item.label, /暂未实现/);
      assert.equal(item.command, undefined);
    }
    await commands.get('cxClaude.providerAdd')();
    const html = panels[0].webview.html;
    assert.match(html, /Anthropic/);
    assert.match(html, /id="sonnetModel"/);
    assert.doesNotMatch(html, /Responses API/);
    assert.doesNotThrow(() => new vm.Script(html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1]));
    await panels[0].receive({ type: 'save', enable: true, payload: { name: 'fixture', baseUrl: 'https://example.invalid', model: 'fixture',
      authType: 'apiKey', sonnetModel: 'fixture-sonnet', apiKey: 'fixture-secret' } });
    assert.equal(calls.find(c => c.operation === 'save').payload.sonnetModel, 'fixture-sonnet');
    assert.deepEqual(updates[0], ['disableLoginPrompt', true]);
    await commands.get('cxClaude.providerTest')({ record: { id: 'fixture-id', name: 'fixture' } });
    assert.ok(notices.some(n => n.includes('连接成功')));
    await commands.get('cxClaude.providerImportCC')();
    assert.ok(notices.some(n => n.includes('2 个 Claude')));
    values.set('environmentVariables', [{ name: 'ANTHROPIC_AUTH_TOKEN', value: 'fixture-override' }]);
    const selects = calls.filter(c => c.operation === 'select').length;
    await commands.get('cxClaude.providerSwitch')({ record: { id: 'fixture-id' } });
    assert.equal(errors.length, 1);
    assert.match(errors[0], /接入覆盖项/);
    assert.equal(calls.filter(c => c.operation === 'select').length, selects);
    values.set('environmentVariables', []);
    await commands.get('cxClaude.providerRestore')();
    assert.deepEqual(updates.at(-1), ['disableLoginPrompt', false]);
  } finally { context.subscriptions.forEach(d => d.dispose()); }
});
