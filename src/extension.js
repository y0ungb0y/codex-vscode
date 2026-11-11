'use strict';
const vscode = require('vscode');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const { Client, expandHome } = require('./client');
const { remaining, reset, translateError, summary, mergeSnapshot } = require('./model');
const { createProviderUI } = require('./providers-ui');
const { createHistoryUI } = require('./history-ui');

function activate(context) {
  const configuration = () => {
    const config = vscode.workspace.getConfiguration('cxAccounts');
    return Object.fromEntries(['pythonPath', 'codexPath', 'proxyUrl', 'accountsRoot', 'codexHome',
      'refreshIntervalSeconds', 'autoRefresh', 'emails'].map(key => [key, config.get(key)]));
  };
  const client = new Client(context.extensionPath, configuration);
  const events = new vscode.EventEmitter();
  const environmentLabel = vscode.env.remoteName ? `远程 ${os.hostname()}` : `本机 ${os.hostname()}`;
  let state, busy = false, disposed = false, loginTerminal, timer, watcherTimer;
  const output = vscode.window.createOutputChannel('CX 账号管理');
  const bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
  bar.command = 'cxAccounts.switch';
  const provider = {
    onDidChangeTreeData: events.event,
    getChildren(node) {
      if (!node) return state?.accounts?.map(account => ({ kind: 'account', account })) || [];
      if (node.kind !== 'account') return [];
      const a = node.account;
      const details = [{ label: a.email, icon: 'mail' }];
      if (a.error) details.push({ label: translateError(a.error), icon: 'warning' });
      else if (a.quota) {
        details.push({ label: `5 小时剩余 ${remaining(a.quota.five_hour)}`, detail: reset(a.quota.five_hour), icon: 'clock' });
        details.push({ label: `周额度剩余 ${remaining(a.quota.weekly)}`, detail: reset(a.quota.weekly), icon: 'calendar' });
        if (a.quota.plan) details.push({ label: `套餐 ${a.quota.plan}`, icon: 'credit-card' });
      } else details.push({ label: a.saved ? '已保存登录，点击上方刷新查询额度' : '点击钥匙按钮完成授权', icon: 'info' });
      return details.map(detail => ({ kind: 'detail', ...detail }));
    },
    getTreeItem(node) {
      if (node.kind === 'detail') {
        const item = new vscode.TreeItem(node.label);
        item.description = node.detail;
        item.tooltip = [node.label, node.detail].filter(Boolean).join('\n');
        item.iconPath = new vscode.ThemeIcon(node.icon);
        return item;
      }
      const a = node.account;
      const thirdParty = state?.providerState?.mode === 'thirdParty';
      const item = new vscode.TreeItem(`账号 ${a.id}${a.selected ? thirdParty ? ' · 官方登录已保留' : ' · 当前选择' : ''}`, vscode.TreeItemCollapsibleState.Expanded);
      item.id = a.id; item.contextValue = 'cxAccount';
      item.description = summary(a);
      item.tooltip = `${a.email}\n${summary(a)}\n${environmentLabel}\n当前选择表示磁盘上的账号，切换后需重载官方 Codex 插件。`;
      item.iconPath = new vscode.ThemeIcon(a.selected && !thirdParty ? 'pass-filled' : 'account',
        a.selected && !thirdParty ? new vscode.ThemeColor('testing.iconPassed') : undefined);
      return item;
    },
  };
  const tree = vscode.window.createTreeView('cxAccounts.accounts', { treeDataProvider: provider, showCollapseAll: true });
  tree.description = environmentLabel;
  const hooks = {
    state: () => state, environmentLabel,
    notice(message) { output.appendLine(`${new Date().toISOString()} ${message}`); render(message); },
    update(data) { state = { ...state, providerState: data }; render(); return data; },
    async run(action) {
      if (busy || loginTerminal) throw new Error('CX 正在查询或授权，请完成后重试。');
      busy = true; render();
      try { return await action(); }
      finally { busy = false; render(); }
    },
  };
  const providers = createProviderUI(context, client, hooks);
  const history = createHistoryUI(context, client, hooks);

  function render(message) {
    if (disposed) return;
    events.fire();
    providers.render();
    history.render();
    const active = state?.accounts?.find(a => a.selected);
    const access = state?.providerState;
    const thirdParty = access?.mode === 'thirdParty';
    bar.text = thirdParty ? `${busy ? '$(sync~spin)' : '$(server-process)'} CX ${access.activeName} · ${access.model}` :
      `${busy ? '$(sync~spin)' : '$(account)'} CX ${active ? active.id : '未选择'}`;
    if (!thirdParty && active?.quota) bar.text += ` · 5h ${remaining(active.quota.five_hour)} · 周 ${remaining(active.quota.weekly)}`;
    bar.tooltip = `${environmentLabel}\n${thirdParty ? `第三方 API：${access.activeName}\n模型：${access.model}\n点击切回 ChatGPT 账号` : active ? `${active.email}\n${summary(active)}` : '点击选择账号'}\n切换后需重载窗口。`;
    bar.show();
    const updated = state?.quotaUpdatedAt ? new Date(state.quotaUpdatedAt).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '';
    tree.message = message || (loginTerminal ? '授权进行中：请在终端查看设备码，并在本机浏览器完成确认。' :
      `${busy ? '正在处理…' : updated ? `额度更新 ${updated}（北京时间）` : '点击刷新查询额度'} · 切换后需重载窗口`);
  }
  async function refresh(live = true, reportError = true) {
    if (busy || loginTerminal || disposed) return;
    busy = true; render();
    try {
      const data = await client.request(live ? 'status' : 'snapshot');
      state = live ? { ...data, quotaUpdatedAt: new Date().toISOString() } : mergeSnapshot(state, data);
      output.appendLine(`${new Date().toISOString()} ${environmentLabel}: ${live ? '额度查询完成' : '账号状态已读取'}`);
    } catch (error) {
      const message = translateError(error.message);
      output.appendLine(message);
      if (reportError) vscode.window.showErrorMessage(`CX：${message}`, '设置').then(value => {
        if (value) vscode.commands.executeCommand('cxAccounts.settings');
      });
      tree.message = message;
    } finally { busy = false; render(tree.message?.includes('失败') ? tree.message : undefined); }
  }
  async function choose(argument, title) {
    if (argument?.account) return argument.account;
    if (typeof argument === 'string') return state?.accounts.find(a => a.id === argument);
    if (!state) await refresh(false);
    const picked = await vscode.window.showQuickPick((state?.accounts || []).map(a => ({
      label: `${a.selected ? '$(check) ' : ''}账号 ${a.id}`, description: a.email,
      detail: summary(a), account: a,
    })), { title: `${title} · ${environmentLabel}` });
    return picked?.account;
  }
  async function switchAccount(argument) {
    if (busy || loginTerminal) return render('CX 正在查询或授权，请完成后再切换。');
    const a = await choose(argument, '选择 Codex 账号');
    if (!a) return;
    if (!a.saved) return authorize({ account: a });
    busy = true; render('正在切换账号…');
    try {
      const data = await client.request('select', a.id);
      state = mergeSnapshot(state, data);
      const message = `账号 ${a.id} 已选择；执行“CX: 重载窗口”后官方 Codex 插件生效。`;
      output.appendLine(`${new Date().toISOString()} ${message}`);
      render(message);
    } catch (error) { vscode.window.showErrorMessage(`CX：${translateError(error.message)}`); }
    finally { busy = false; render(); }
  }
  async function authorize(argument) {
    if (busy || loginTerminal) return render('CX 正在查询或授权，请完成后重试。');
    const a = await choose(argument, '授权 Codex 账号');
    if (!a) return;
    try {
      const options = await client.loginTerminalOptions(a.id);
      const task = new vscode.Task({ type: 'cx-login', account: a.id }, vscode.TaskScope.Global,
        `CX 授权 · 账号 ${a.id}`, 'CX',
        new vscode.ProcessExecution(options.shellPath, options.shellArgs, { env: options.env }));
      task.presentationOptions = { reveal: vscode.TaskRevealKind.Always, panel: vscode.TaskPanelKind.Dedicated, clear: true };
      loginTerminal = await vscode.tasks.executeTask(task);
      render(`授权终端已打开：请使用 ${a.email} 完成授权；授权不会切换当前账号。`);
    } catch (error) { vscode.window.showErrorMessage(`CX：${translateError(error.message)}`); }
  }
  function schedule() {
    clearInterval(timer);
    const opts = configuration();
    if (opts.autoRefresh) timer = setInterval(() => {
      if (tree.visible || providers.tree.visible) refresh(true, false);
    }, Math.min(3600, Math.max(60, opts.refreshIntervalSeconds || 300)) * 1000);
  }
  const watchers = [];
  function watchFiles() {
    watchers.splice(0).forEach(w => w.dispose());
    const opts = configuration();
    const roots = [
      [expandHome(opts.accountsRoot || path.join(os.homedir(), '.codex-accounts')), '**/{auth.json,registry.json}'],
      [expandHome(opts.codexHome || process.env.CODEX_HOME || path.join(os.homedir(), '.codex')), '{auth.json,config.toml}'],
    ];
    for (const [root, pattern] of roots) {
      const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, pattern));
      const change = () => {
        clearTimeout(watcherTimer);
        watcherTimer = setTimeout(() => refresh(false, false), 700);
      };
      context.subscriptions.push(watcher.onDidCreate(change), watcher.onDidChange(change), watcher.onDidDelete(change));
      watchers.push(watcher);
    }
  }
  const commands = {
    refresh: () => refresh(true), switch: switchAccount, login: authorize,
    reload: () => vscode.commands.executeCommand('workbench.action.reloadWindow'),
    settings: () => vscode.commands.executeCommand('workbench.action.openSettings', '@ext:wangxin-local.cx-codex-accounts'),
    openGuide: () => {
      const guide = ['README.md', 'readme.md'].map(name => path.join(context.extensionPath, name)).find(file => fs.existsSync(file));
      return vscode.commands.executeCommand('markdown.showPreview', vscode.Uri.file(guide || path.join(context.extensionPath, 'readme.md')));
    },
  };
  for (const [name, handler] of Object.entries(commands)) {
    context.subscriptions.push(vscode.commands.registerCommand(`cxAccounts.${name}`, handler));
  }
  context.subscriptions.push(
    events, tree, bar, output,
    tree.onDidChangeVisibility(event => { if (event.visible) refresh(true, false); }),
    providers.tree.onDidChangeVisibility(event => { if (event.visible) refresh(false, false); }),
    vscode.tasks.onDidEndTaskProcess(event => {
      if (event.execution !== loginTerminal) return;
      loginTerminal = null;
      if (event.exitCode === 0) {
        render('授权已完成；当前账号选择保持不变，如需生效请执行“CX: 重载窗口”。');
        output.appendLine(`${new Date().toISOString()} 授权已完成（账号 ${event.execution.task?.definition?.account || ''}）。`);
      } else {
        render('授权未完成；请查看授权终端，设备码过期时可再次点击钥匙按钮。');
        output.appendLine(`${new Date().toISOString()} 授权未完成，退出码 ${event.exitCode ?? '未知'}。`);
      }
      refresh(true, true);
    }),
    vscode.workspace.onDidChangeConfiguration(event => {
      if (event.affectsConfiguration('cxAccounts')) { schedule(); watchFiles(); refresh(false); }
    }),
    { dispose() { disposed = true; clearInterval(timer); clearTimeout(watcherTimer); watchers.forEach(w => w.dispose()); } },
  );
  watchFiles(); schedule(); render();
  const ready = refresh(false, false).then(async () => {
    if (tree.visible) await refresh(true, false);
    if (history.tree.visible) await history.refresh();
  });
  // Useful for extension-host verification; exposes metadata only, never tokens.
  return { ready, getSnapshot: () => state, refresh };
}

module.exports = { activate };
