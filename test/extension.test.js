const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

test('extension wires account tree, switch/reload choice, login task and quota refresh', async () => {
  const commands = new Map(), events = {}, executed = [], bars = [];
  const disposable = () => ({ dispose() {} });
  const data = () => ({ selected: '3', accounts: [1, 2, 3].map(n => ({
    id: String(n), email: `account${n}@example.invalid`, saved: true, selected: n === 3,
  })) });
  let selected = '3', bridgeCalls = [], task, thirdParty = false;
  class FakeClient {
    async request(operation, number) {
      bridgeCalls.push(operation);
      if (operation === 'select') { selected = number; thirdParty = false; }
      const snapshot = data(); snapshot.selected = selected;
      snapshot.providerState = { mode: thirdParty ? 'thirdParty' : 'official', activeName: 'fixture-gateway', model: 'fixture-model', providers: [] };
      snapshot.accounts.forEach(a => {
        a.selected = a.id === selected;
        if (operation === 'status') a.quota = { five_hour: { remaining: 88 }, weekly: { remaining: 0 } };
      });
      return snapshot;
    }
    async loginTerminalOptions(number) {
      return { shellPath: 'python3', shellArgs: ['bridge.py', 'login', number], env: { PYTHONIOENCODING: 'utf-8' } };
    }
  }
  class EventEmitter {
    constructor() { this.listeners = []; this.event = listener => { this.listeners.push(listener); return disposable(); }; }
    fire(value) { this.listeners.forEach(f => f(value)); }
    dispose() {}
  }
  const settings = { autoRefresh: false };
  const tree = { ...disposable(), visible: false, onDidChangeVisibility: callback => { events.visible = callback; return disposable(); } };
  const vscode = {
    EventEmitter, StatusBarAlignment: { Right: 1 }, TreeItemCollapsibleState: { Expanded: 2 },
    TreeItem: class { constructor(label) { this.label = label; } },
    ThemeIcon: class {}, ThemeColor: class {}, RelativePattern: class {},
    Task: class { constructor(definition, scope, name, source, execution) { Object.assign(this, { definition, scope, name, source, execution }); } },
    ProcessExecution: class { constructor(process, args, options) { Object.assign(this, { process, args, options }); } },
    TaskScope: { Global: 1 }, TaskRevealKind: { Always: 1 }, TaskPanelKind: { Dedicated: 1 },
    Uri: { file: value => value }, env: { remoteName: 'ssh-remote' },
    workspace: {
      getConfiguration: () => ({ get: key => settings[key] }),
      createFileSystemWatcher: () => ({ ...disposable(), onDidCreate: () => disposable(), onDidChange: () => disposable(), onDidDelete: () => disposable() }),
      onDidChangeConfiguration: () => disposable(),
    },
    commands: {
      registerCommand(name, handler) { commands.set(name, handler); return disposable(); },
      async executeCommand(...args) { executed.push(args); },
    },
    tasks: {
      async executeTask(value) { task = value; return { task: value }; },
      onDidEndTaskProcess(callback) { events.taskEnd = callback; return disposable(); },
    },
    window: {
      createOutputChannel: () => ({ ...disposable(), appendLine() {} }),
      createStatusBarItem: () => { const bar = { ...disposable(), show() {} }; bars.push(bar); return bar; },
      createTreeView: (id, options) => {
        if (id === 'cxAccounts.accounts') { tree.provider = options.treeDataProvider; return tree; }
        return { ...disposable(), visible: false, onDidChangeVisibility: () => disposable() };
      },
      async showWarningMessage() { return '只切换，稍后重载'; },
      async showInformationMessage() {}, async showErrorMessage(message) { throw new Error(message); },
    },
  };
  const original = Module._load;
  let extension;
  try {
    Module._load = function (request, parent, main) {
      if (request === 'vscode') return vscode;
      if (request === './client' && parent.filename.endsWith('extension.js')) return { Client: FakeClient, expandHome: value => value };
      return original.call(this, request, parent, main);
    };
    extension = require('../src/extension');
  } finally { Module._load = original; }
  const context = { extensionPath: '/test-extension', subscriptions: [] };
  const api = extension.activate(context);
  try {
    await api.ready;
    assert.equal(api.getSnapshot().selected, '3');
    assert.match(tree.description, /远程/);
    assert.equal(tree.provider.getChildren().length, 3);
    await commands.get('cxAccounts.refresh')();
    assert.match(bars[0].text, /5h 88%.*周 0%/);
    const rows = tree.provider.getChildren();
    const details = tree.provider.getChildren(rows[2]);
    assert.ok(details.some(node => node.label.includes('周额度剩余 0%')));
    thirdParty = true;
    await commands.get('cxAccounts.refresh')();
    assert.match(bars[0].text, /fixture-gateway.*fixture-model/);
    assert.doesNotMatch(bars[0].text, /5h/);
    assert.match(tree.provider.getTreeItem(tree.provider.getChildren()[2]).label, /官方登录已保留/);
    await commands.get('cxAccounts.switch')({ account: api.getSnapshot().accounts[0] });
    assert.equal(api.getSnapshot().selected, '1');
    assert.equal(api.getSnapshot().providerState.mode, 'official');
    assert.equal(executed.length, 0, 'later reload does not reload without choice');
    await commands.get('cxAccounts.login')({ account: api.getSnapshot().accounts[1] });
    assert.deepEqual(task.execution.args, ['bridge.py', 'login', '2']);
    assert.equal(api.getSnapshot().selected, '1', 'starting login does not select its account');
    assert.ok(bridgeCalls.includes('select'));
    await commands.get('cxAccounts.reload')();
    assert.deepEqual(executed[0], ['workbench.action.reloadWindow']);
  } finally {
    for (const item of context.subscriptions) item.dispose();
  }
});
