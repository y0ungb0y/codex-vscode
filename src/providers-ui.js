'use strict';
const vscode = require('vscode');
const crypto = require('node:crypto');

function escape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function formHtml(webview, record, storage, application = 'codex') {
  const nonce = crypto.randomBytes(24).toString('base64');
  const claude = application === 'claude';
  const title = claude ? 'Claude Code 第三方供应商' : '第三方供应商';
  const mappings = claude ? `<label for="auth">认证方式</label><select id="auth"><option value="token" ${record?.authType !== 'apiKey' ? 'selected' : ''}>Bearer Token（ANTHROPIC_AUTH_TOKEN）</option><option value="apiKey" ${record?.authType === 'apiKey' ? 'selected' : ''}>x-api-key（ANTHROPIC_API_KEY）</option></select>` +
    ['haiku', 'sonnet', 'opus', 'fable', 'subagent'].map(tier => `<label for="${tier}Model">${tier} 模型映射（可选）</label><input id="${tier}Model" maxlength="160" value="${escape(record?.[tier + 'Model'])}" placeholder="留空使用上方默认模型">`).join('') : '';
  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style nonce="${nonce}">
body{max-width:680px;margin:32px auto;padding:0 28px;font-family:var(--vscode-font-family);color:var(--vscode-foreground)}
h1{font-size:24px;font-weight:600}p{line-height:1.65;color:var(--vscode-descriptionForeground)}
label{display:block;margin-top:22px;font-weight:600}input,textarea,select{box-sizing:border-box;display:block;width:100%;margin-top:8px;padding:10px;border:1px solid var(--vscode-input-border,transparent);background:var(--vscode-input-background);color:var(--vscode-input-foreground);font:inherit}
input:focus,button:focus{outline:1px solid var(--vscode-focusBorder);outline-offset:2px}.hint{display:block;margin-top:6px;font-size:12px;color:var(--vscode-descriptionForeground)}
.actions{display:flex;gap:12px;margin-top:28px}button{cursor:pointer;border:0;padding:10px 18px;background:var(--vscode-button-background);color:var(--vscode-button-foreground);font:inherit}button.secondary{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}button:disabled{opacity:.6;cursor:wait}#result{white-space:pre-wrap;color:var(--vscode-errorForeground);line-height:1.6}
</style></head><body><h1>${record ? '编辑' : '添加'}${title}</h1>
<p>保存服务地址、模型和 API Key，然后在 CX 侧栏启用。启用后需重新加载窗口。</p>
<form id="provider-form">
<label for="name">供应商名称</label><input id="name" required maxlength="80" value="${escape(record?.name)}" placeholder="例如：我的模型网关">
<label for="url">接口基础地址（Base URL）</label><input id="url" type="url" required maxlength="2048" value="${escape(record?.baseUrl)}" placeholder="https://gateway.example.com/v1">
<span class="hint">${claude ? '填写 Anthropic 兼容接口的基础地址，例如 https://gateway.example.com 或 https://api.deepseek.com/anthropic。不要添加 /messages；请求将使用 /v1/messages。' : '填写基础地址，无需添加 /responses。服务必须兼容 Responses API；仅支持 Chat Completions 的服务无法直接使用。'}</span>
<label for="model">模型名称</label><input id="model" required maxlength="160" value="${escape(record?.model)}" placeholder="填写供应商提供的模型 ID">
${mappings}
<label for="models">${claude ? 'CX 模型候选' : 'Codex 模型菜单'}（每行一个模型 ID）</label><textarea id="models" rows="4" placeholder="留空时只显示上方默认模型">${escape((record?.models || []).join('\n'))}</textarea>
<button class="secondary" id="discover" type="button">${claude ? '选择已配置模型' : '从接口选择模型'}</button><span class="hint">${claude ? '模型候选显示在 CX 中；Claude Code 使用默认模型和上述分档映射。接口需兼容 Anthropic Messages。' : '可手动添加 DeepSeek、Qwen、GLM 等模型 ID；列表中出现不代表接口已兼容，CX 会为所选模型生成 Codex 模型目录。'}</span>
<label for="key">API Key</label><input id="key" type="password" ${record?.hasKey ? '' : 'required'} maxlength="16384" autocomplete="off" spellcheck="false" placeholder="${record?.hasKey ? '已保存密钥；留空保留，输入新值则替换' : '请输入供应商密钥'}">
<span class="hint">存储方式：${escape(storage)}。${claude ? '密钥在 CX 中加密保存；启用时按 Claude Code 原生格式写入用户 settings.json 的 env，不显示在侧栏和日志。' : '密钥不会显示在侧栏、日志或 config.toml 中。'}</span>
<p>配置保存在当前窗口所在的机器。${claude ? '不会修改 Codex 配置；第三方计费由供应商决定。' : '本机与 AMAX 分别添加；第三方计费由供应商决定，不计入 ChatGPT 的 5 小时与周额度。'}</p>
<div class="actions"><button type="submit">保存并启用</button><button class="secondary" id="save-only" type="button">仅保存</button></div>
<p id="result" role="alert" aria-live="polite"></p></form>
<script nonce="${nonce}">
const api=acquireVsCodeApi(),form=document.getElementById('provider-form'),result=document.getElementById('result');
function payload(){return {name:document.getElementById('name').value,baseUrl:document.getElementById('url').value,model:document.getElementById('model').value,models:document.getElementById('models').value.split(/\\r?\\n/).map(v=>v.trim()).filter(Boolean),apiKey:document.getElementById('key').value,...(document.getElementById('auth')?{authType:document.getElementById('auth').value,...Object.fromEntries(['haiku','sonnet','opus','fable','subagent'].map(tier=>[tier+'Model',document.getElementById(tier+'Model').value]))}: {})};}
function save(enable){if(!form.reportValidity())return;result.textContent='正在保存…';form.querySelectorAll('button').forEach(b=>b.disabled=true);api.postMessage({type:'save',enable,payload:payload()});document.getElementById('key').value='';}
form.addEventListener('submit',e=>{e.preventDefault();save(true)});document.getElementById('save-only').addEventListener('click',()=>save(false));
document.getElementById('discover').addEventListener('click',()=>{result.textContent='正在发现模型…';form.querySelectorAll('button').forEach(b=>b.disabled=true);api.postMessage({type:'discover',payload:payload()});});
window.addEventListener('message',e=>{if(e.data.type==='error'||e.data.type==='models'){result.textContent=e.data.message||'';form.querySelectorAll('button').forEach(b=>b.disabled=false);if(e.data.models?.length){document.getElementById('models').value=e.data.models.join('\\n');const model=document.getElementById('model');if(!e.data.models.includes(model.value))model.value=e.data.models[0];}}});
</script></body></html>`;
}

function createProviderUI(context, client, hooks) {
  const events = new vscode.EventEmitter();
  const claude = hooks.application === 'claude';
  const namespace = claude ? 'cxClaude' : 'cxAccounts';
  const appLabel = claude ? 'Claude Code' : 'Codex';
  const snapshot = () => hooks.state()?.providerState;
  const provider = {
    onDidChangeTreeData: events.event,
    getChildren(node) {
      if (!node) return (snapshot()?.providers || []).map(record => ({ kind: 'provider', record }));
      if (node.kind !== 'provider') return [];
      if (node.kind === 'model') return [];
      return [{ label: node.record.baseUrl, icon: 'link' },
        { label: `模型：${node.record.model}`, icon: 'symbol-method' },
        { label: node.record.hasKey ? 'API Key 已保存' : 'API Key 缺失，请编辑', icon: 'key' },
        { label: `${claude ? 'Anthropic Messages' : 'Responses API'} · 供应商独立计费`, icon: 'info' }].map(detail => ({ kind: 'detail', ...detail }))
        .concat((node.record.models || [node.record.model]).map(model => ({ kind: 'model', model, record: node.record })));
    },
    getTreeItem(node) {
      if (node.kind === 'model') {
        const item = new vscode.TreeItem(node.model);
        item.iconPath = new vscode.ThemeIcon(node.model === node.record.model ? 'check' : 'symbol-method');
        item.command = { command: `${namespace}.providerModel`, title: '设为默认模型', arguments: [node] };
        item.tooltip = '设为默认模型，启用当前供应商后重载生效。'; return item;
      }
      if (node.kind === 'detail') {
        const item = new vscode.TreeItem(node.label);
        item.tooltip = node.label; item.iconPath = new vscode.ThemeIcon(node.icon); return item;
      }
      const p = node.record;
      const item = new vscode.TreeItem(`${p.name}${p.selected ? ' · 当前接入' : ''}`, vscode.TreeItemCollapsibleState.Collapsed);
      item.id = `provider-${p.id}`; item.contextValue = claude ? 'cxClaudeProvider' : 'cxProvider'; item.description = p.model;
      item.tooltip = `${p.baseUrl}\n模型：${p.model}\n${p.selected ? '当前配置指向此供应商；修改后需重载窗口。' : '点击双向箭头启用。'}`;
      item.iconPath = new vscode.ThemeIcon(p.selected ? 'pass-filled' : 'server-process',
        p.selected ? new vscode.ThemeColor('testing.iconPassed') : undefined);
      return item;
    },
  };
  const tree = vscode.window.createTreeView(`${namespace}.providers`, { treeDataProvider: provider, showCollapseAll: true });
  const panels = new Set();
  function render() {
    events.fire();
    tree.description = hooks.environmentLabel;
    const s = snapshot();
    tree.message = s?.mode === 'thirdParty' ? `当前：${s.activeName} · ${s.model} · 切换后需重载窗口` :
      claude ? 'Claude Code 第三方供应商；点击 + 添加或导入已有配置。' : '当前使用 ChatGPT 账号。点击 + 添加第三方供应商。';
  }
  function notify(message) {
    hooks.notice?.(message);
    tree.message = message;
  }
  async function reloaded(result) {
    if (!result.requiresReload) return;
    notify(`接入配置已更新；执行“CX: 重载窗口”后 ${appLabel} 生效。`);
  }
  async function edit(argument) {
    const record = argument?.record;
    const panel = vscode.window.createWebviewPanel('cxProviderForm', record ? `编辑供应商 · ${record.name}` : '添加第三方供应商',
      vscode.ViewColumn.Active, { enableScripts: true, localResourceRoots: [] });
    panels.add(panel);
    panel.webview.html = formHtml(panel.webview, record, snapshot()?.storage || '当前机器的受保护存储', hooks.application);
    let saving = false;
    let savedId = record?.id;
    const listener = panel.webview.onDidReceiveMessage(async message => {
      if (!['save', 'discover'].includes(message?.type) || saving) return;
      saving = true;
      try {
        if (message.type === 'discover') {
          const data = await hooks.run(() => client.providerRequest('models', { ...message.payload, id: savedId }));
          const selected = new Set(message.payload.models || [message.payload.model]);
          selected.add(message.payload.model);
          const picked = await vscode.window.showQuickPick(data.models.map(id => ({ label: id, picked: selected.has(id) })),
            { title: claude ? '选择 Claude 的 CX 模型候选' : '勾选要显示在 Codex 中的模型', canPickMany: true, placeHolder: data.notice });
          panel.webview.postMessage({ type: 'models', models: picked?.map(p => p.label), message: data.notice });
          return;
        }
        const result = await hooks.run(async () => {
          const saved = await client.providerRequest('save', { ...record, ...message.payload, id: savedId });
          savedId = saved.savedId;
          hooks.update(saved);
          if (message.enable === true) {
            const selected = await client.providerRequest('select', { id: saved.savedId });
            hooks.update(selected); return selected;
          }
          return saved;
        });
        panel.dispose();
        if (result.requiresReload) await reloaded(result);
        else notify('供应商已保存，可在 CX 侧栏点击双向箭头启用。');
      } catch (error) {
        panel.webview.postMessage({ type: 'error', message: error.message });
      } finally { saving = false; }
    });
    const closed = panel.onDidDispose(() => { panels.delete(panel); listener.dispose(); closed.dispose(); });
  }
  async function select(argument) {
    const record = argument?.record;
    if (!record) return;
    await hooks.run(async () => hooks.update(await client.providerRequest('select', { id: record.id })));
    notify(`供应商“${record.name}”已启用；执行“CX: 重载窗口”后生效。`);
  }
  async function remove(argument) {
    const record = argument?.record;
    if (!record) return;
    await hooks.run(async () => hooks.update(await client.providerRequest('delete', { id: record.id })));
    notify(`供应商“${record.name}”及其保存的 API Key 已删除。`);
  }
  async function restore() {
    if (!snapshot()?.canRestore) return notify('没有需要恢复的 CX 供应商切换记录。');
    const result = await hooks.run(async () => hooks.update(await client.providerRequest('restore')));
    notify('已恢复启用第三方供应商前的接入配置。');
    await reloaded(result);
  }
  async function importCurrent() {
    const result = await hooks.run(async () => hooks.update(await client.providerRequest('import')));
    notify(result.alreadyImported ? '当前供应商已在 CX 侧栏中。' : '当前供应商已导入 CX，原接入配置和登录保持不变。');
  }
  async function selectModels(argument) {
    const record = argument?.record;
    if (!record) return;
    const result = await hooks.run(() => client.providerRequest('models', { id: record.id }));
    const wanted = new Set(record.models || [record.model]);
    const picked = await vscode.window.showQuickPick(result.models.map(id => ({ label: id, picked: wanted.has(id) })),
      { title: claude ? '选择此供应商的 CX 模型候选' : '选择此供应商的 Codex 模型菜单', canPickMany: true, placeHolder: result.notice });
    if (!picked?.length) return;
    const models = picked.map(p => p.label);
    const updated = await hooks.run(async () => hooks.update(await client.providerRequest('save', {
      ...record, model: models.includes(record.model) ? record.model : models[0], models, apiKey: '',
    })));
    if (updated.requiresReload) await reloaded(updated);
    else notify(claude ? 'CX 模型候选已保存。' : '模型菜单已保存，启用此供应商时会生成 Codex 模型目录。');
  }
  async function defaultModel(argument) {
    if (!argument?.record || !argument.model) return;
    const result = await hooks.run(async () => hooks.update(await client.providerRequest('save', {
      ...argument.record, model: argument.model, apiKey: '',
    })));
    if (result.requiresReload) await reloaded(result);
    else notify('默认模型已保存，启用此供应商后生效。');
  }
  const handlers = { providerAdd: () => edit(), providerEdit: edit, providerSwitch: select, providerDelete: remove,
    providerRestore: restore, providerImport: importCurrent, providerModels: selectModels, providerModel: defaultModel };
  if (claude) {
    handlers.providerImportCC = async () => {
      const result = await hooks.run(async () => hooks.update(await client.providerRequest('import-cc')));
      notify(`已从 CC Switch 导入 ${result.imported} 个 Claude 供应商，跳过 ${result.skipped} 个非第三方配置。`);
    };
    handlers.providerTest = async node => {
      if (!node?.record) return;
      const result = await hooks.run(() => client.providerRequest('test', { id: node.record.id }));
      notify(`“${node.record.name}”连接成功：${result.message}`);
    };
    handlers.refresh = () => hooks.refresh();
  }
  for (const [name, handler] of Object.entries(handlers)) {
    context.subscriptions.push(vscode.commands.registerCommand(`${namespace}.${name}`, async argument => {
      try { return await handler(argument); }
      catch (error) { vscode.window.showErrorMessage(`CX：${error.message}`); }
    }));
  }
  context.subscriptions.push(tree, events, { dispose() { for (const panel of panels) panel.dispose(); } });
  return { render, tree };
}

module.exports = { createProviderUI, formHtml, escape };
