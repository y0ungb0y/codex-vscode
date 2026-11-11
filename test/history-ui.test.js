const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

test('unified history previews both providers and uses native fork for a different provider', async () => {
  const commands = new Map(), calls = [], opened = [], documents = [];
  const disposable = () => ({ dispose() {} });
  class EventEmitter { constructor() { this.event = () => disposable(); } fire() {} dispose() {} }
  const vscode = {
    EventEmitter, TreeItem: class { constructor(label) { this.label = label; } }, ThemeIcon: class {},
    Uri: { parse: value => value },
    env: { uriScheme: 'vscode-test', async openExternal(uri) { opened.push(uri); return true; } },
    commands: { registerCommand(name, handler) { commands.set(name, handler); return disposable(); } },
    workspace: { async openTextDocument(options) { documents.push(options); return options; } },
    window: {
      createTreeView: (id, options) => ({ ...disposable(), provider: options.treeDataProvider, onDidChangeVisibility: () => disposable() }),
      async showWarningMessage() { return '创建分支并打开'; }, async showInformationMessage() {},
      async showTextDocument() {}, async showErrorMessage(message) { throw new Error(message); },
    },
  };
  const original = Module._load;
  let createHistoryUI;
  try {
    Module._load = function (name, parent, main) { return name === 'vscode' ? vscode : original.call(this, name, parent, main); };
    ({ createHistoryUI } = require('../src/history-ui'));
  } finally { Module._load = original; }
  const client = { async historyRequest(operation, payload) {
    calls.push({ operation, payload });
    if (operation === 'list') return { threads: [
      { id: 'thr_official111', name: 'Official fixture', modelProvider: 'openai' },
      { id: 'thr_custom1111', name: 'Custom fixture', modelProvider: 'custom' },
    ], nextCursor: null };
    if (operation === 'read') return { id: payload.id, name: 'Fixture', modelProvider: 'custom', messages: [{ role: '用户', text: 'Private fixture preview' }] };
    if (operation === 'fork') return { id: 'thr_new1111111', modelProvider: 'openai' };
    throw new Error('Unknown operation');
  } };
  const context = { subscriptions: [] };
  const ui = createHistoryUI(context, client, { state: () => ({ providerState: { providerId: 'openai', providers: [] } }),
    environmentLabel: 'fixture', run: action => action() });
  try {
    await ui.refresh();
    const rows = ui.tree.provider.getChildren();
    assert.equal(rows.length, 2);
    await commands.get('cxAccounts.historyOpen')(rows[1]);
    assert.equal(documents[0].language, 'plaintext');
    assert.match(documents[0].content, /Private fixture preview/);
    assert.equal(opened.length, 0, 'preview does not change the active conversation');
    await commands.get('cxAccounts.historyContinue')(rows[0]);
    assert.equal(opened[0], 'vscode-test://openai.chatgpt/local/thr_official111');
    await commands.get('cxAccounts.historyContinue')(rows[1]);
    assert.ok(calls.some(c => c.operation === 'fork' && c.payload.id === 'thr_custom1111'));
    assert.equal(opened[1], 'vscode-test://openai.chatgpt/local/thr_new1111111');
  } finally { context.subscriptions.forEach(d => d.dispose()); }
});
