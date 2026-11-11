'use strict';
const vscode = require('vscode');

function createHistoryUI(context, client, hooks) {
  const events = new vscode.EventEmitter();
  let threads = [], cursor, search = '', archived = false, lastRead;
  const label = id => {
    if (id === 'openai') return '官方';
    const p = hooks.state()?.providerState?.providers?.find(p => `cx_${p.id}` === id || p.sourceId === id);
    return p?.name || id || '未知接入';
  };
  const provider = {
    onDidChangeTreeData: events.event,
    getChildren() { return [...threads.map(thread => ({ thread })), ...(cursor ? [{ more: true }] : [])]; },
    getTreeItem(node) {
      if (node.more) {
        const item = new vscode.TreeItem('加载更多会话…');
        item.command = { command: 'cxAccounts.historyMore', title: '加载更多' }; return item;
      }
      const t = node.thread;
      const item = new vscode.TreeItem((t.name || t.preview || t.id).replace(/\s+/g, ' ').slice(0, 90));
      item.id = `history-${t.id}`; item.contextValue = 'cxHistory'; item.description = label(t.modelProvider);
      item.tooltip = `${label(t.modelProvider)}\n${t.cwd || ''}\n点击预览；箭头按钮在 Codex 中继续。`;
      item.iconPath = new vscode.ThemeIcon('comment-discussion');
      item.command = { command: 'cxAccounts.historyOpen', title: '预览历史会话', arguments: [node] };
      return item;
    },
  };
  const tree = vscode.window.createTreeView('cxAccounts.history', { treeDataProvider: provider });
  function render() {
    events.fire(); tree.description = hooks.environmentLabel;
    tree.message = `${archived ? '已归档' : '未归档'} · 所有供应商 · 已加载 ${threads.length} 条${search ? ` · 搜索：${search}` : ''}`;
  }
  async function refresh(more = false) {
    try {
      const data = await hooks.run(() => client.historyRequest('list', { cursor: more ? cursor : undefined, search, archived }));
      threads = more ? [...threads, ...data.threads.filter(t => !threads.some(old => old.id === t.id))] : data.threads;
      cursor = data.nextCursor; render();
    } catch (error) { tree.message = error.message; }
  }
  async function showPage(id, older) {
    const data = await hooks.run(() => client.historyRequest('read', { id, cursor: older ? lastRead?.nextCursor : undefined }));
    lastRead = data;
    const content = [`${data.name}\n接入：${label(data.modelProvider)}\n会话 ID：${data.id}`,
      '历史预览不修改原记录。工具仅显示操作摘要；继续会话请使用 CX 会话行右侧箭头。',
      ...data.messages.map(m => `—— ${m.role} ——\n${m.text}`),
      ...(data.truncated ? ['本页内容较长，已限制预览长度；原始记录未改动。'] : []),
      ...(data.nextCursor ? ['还有更早的消息：在统一历史标题栏菜单选择“加载更早消息”。'] : []),
    ].join('\n\n');
    const document = await vscode.workspace.openTextDocument({ content, language: 'plaintext' });
    await vscode.window.showTextDocument(document, { preview: true });
  }
  async function openNative(id) {
    if (!/^[A-Za-z0-9_-]{8,100}$/.test(id)) throw new Error('会话编号无效。');
    const scheme = vscode.env.uriScheme || 'vscode';
    const opened = await vscode.env.openExternal(vscode.Uri.parse(`${scheme}://openai.chatgpt/local/${encodeURIComponent(id)}`));
    if (opened === false) throw new Error('无法打开 Codex 会话；请确认官方 Codex 插件已安装。');
  }
  function notify(message) {
    hooks.notice?.(message);
    tree.message = message;
  }
  async function fork(argument) {
    const t = argument?.thread;
    if (!t) return;
    const result = await hooks.run(() => client.historyRequest('fork', { id: t.id }));
    await openNative(result.id); await refresh();
    notify('已使用当前配置创建会话分支，并打开新会话。');
  }
  const handlers = {
    historyRefresh: () => refresh(), historyMore: () => refresh(true),
    historyOpen: node => node?.thread ? showPage(node.thread.id, false) : undefined,
    historyOlder: () => lastRead?.nextCursor ? showPage(lastRead.id, true) : notify('当前预览没有更多消息。'),
    historyFork: fork,
    async historyContinue(node) {
      if (!node?.thread) return;
      const active = hooks.state()?.providerState?.providerId || 'openai';
      if (node.thread.modelProvider !== active) return fork(node);
      await openNative(node.thread.id);
    },
    async historySearch() {
      const value = await vscode.window.showInputBox({ title: '搜索所有供应商的本机会话', prompt: '按标题搜索；留空恢复全部。搜索区分大小写。', value: search });
      if (value === undefined) return;
      search = value.trim(); await refresh();
    },
    async historyArchived() { archived = !archived; await refresh(); },
  };
  for (const [name, handler] of Object.entries(handlers)) {
    context.subscriptions.push(vscode.commands.registerCommand(`cxAccounts.${name}`, async arg => {
      try { return await handler(arg); } catch (error) { vscode.window.showErrorMessage(`CX：${error.message}`); }
    }));
  }
  context.subscriptions.push(events, tree, tree.onDidChangeVisibility(e => { if (e.visible) refresh(); }));
  return { tree, render, refresh };
}

module.exports = { createHistoryUI };
