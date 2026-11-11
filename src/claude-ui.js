'use strict';
const vscode = require('vscode');
const path = require('node:path');
const os = require('node:os');
const { expandHome } = require('./client');
const { createProviderUI } = require('./providers-ui');

function createClaudeUI(context, client, hooks, configuration) {
  let state, disposed = false, timer, refreshing;
  const placeholders = ['accounts', 'history'].map(section => {
    const provider = {
      getChildren: () => [{ label: section === 'accounts' ? '官方账号管理 · 暂未实现' : '统一历史会话 · 暂未实现' }],
      getTreeItem(node) {
        const item = new vscode.TreeItem(node.label);
        item.iconPath = new vscode.ThemeIcon('info');
        item.tooltip = '当前版本只实现 Claude Code 第三方供应商管理。';
        return item;
      },
    };
    const tree = vscode.window.createTreeView(`cxClaude.${section}`, { treeDataProvider: provider });
    tree.description = hooks.environmentLabel;
    tree.message = 'Claude Code · 界面占位，暂无账号或历史读写功能';
    return tree;
  });
  const adapter = {
    async providerRequest(operation, payload) {
      const config = vscode.workspace.getConfiguration('claudeCode');
      const mutates = ['select', 'restore'].includes(operation) || operation === 'save' && state?.activeId === payload?.id;
      if (mutates) {
        const overrides = config.get('environmentVariables', []);
        if (overrides.some?.(e => /^(ANTHROPIC_|CLAUDE_CODE_(USE_|OAUTH_TOKEN|SUBAGENT_MODEL))/.test(e.name || ''))) {
          throw new Error('VS Code 的 claudeCode.environmentVariables 含接入覆盖项；请先移除这些覆盖项，再通过 CX 切换。');
        }
      }
      const result = await client.claudeRequest(operation, payload);
      if (operation === 'select' || operation === 'save' && result.requiresReload) {
        const key = 'cxClaude.previousLoginPrompt';
        if (context.globalState && !context.globalState.get(key)) {
          const previous = config.inspect('disableLoginPrompt')?.globalValue;
          await context.globalState.update(key, { value: previous });
        }
        await config.update('disableLoginPrompt', true, vscode.ConfigurationTarget.Global);
      } else if (operation === 'restore' && context.globalState) {
        const previous = context.globalState.get('cxClaude.previousLoginPrompt');
        if (previous) {
          await config.update('disableLoginPrompt', previous.value, vscode.ConfigurationTarget.Global);
          await context.globalState.update('cxClaude.previousLoginPrompt', undefined);
        }
      }
      return result;
    },
  };
  const ui = createProviderUI(context, adapter, {
    application: 'claude', environmentLabel: hooks.environmentLabel,
    state: () => ({ providerState: state }),
    update(data) { state = data; ui.render(); return data; },
    run: action => hooks.run(action),
    notice: message => hooks.notice(`Claude Code：${message}`),
    refresh: () => refresh(),
  });
  function refresh() {
    if (disposed) return Promise.resolve();
    if (refreshing) return refreshing;
    refreshing = hooks.run(async () => {
      state = await client.claudeRequest('snapshot');
      ui.render();
    }).catch(error => { ui.tree.message = `Claude Code：${error.message}`; })
      .finally(() => { refreshing = undefined; });
    return refreshing;
  }
  const home = expandHome(configuration().claudeHome || process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude'));
  const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(home, 'settings.json'));
  const changed = () => { clearTimeout(timer); timer = setTimeout(() => refresh(), 800); };
  context.subscriptions.push(...placeholders, watcher, watcher.onDidCreate(changed), watcher.onDidChange(changed), watcher.onDidDelete(changed),
    ui.tree.onDidChangeVisibility(e => { if (e.visible) refresh(); }),
    { dispose() { disposed = true; clearTimeout(timer); } });
  return { refresh, getSnapshot: () => state };
}

module.exports = { createClaudeUI };
