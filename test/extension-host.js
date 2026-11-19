const assert = require('node:assert/strict');
const fs = require('node:fs');
const vscode = require('vscode');

exports.run = async function () {
  const resultFile = process.env.CX_EXTENSION_TEST_RESULT;
  try {
    const extension = vscode.extensions.getExtension('wangxin-local.cx-codex-accounts');
    assert.ok(extension, 'extension registered');
    const api = await extension.activate();
    await api.ready;
    const snapshot = api.getSnapshot();
    assert.equal(snapshot.selected, '3');
    assert.equal(snapshot.accounts.length, 3);
    assert.equal(snapshot.accounts[0].email, 'one@example.invalid');
    const commands = await vscode.commands.getCommands(true);
    for (const name of ['refresh', 'switch', 'login', 'reload', 'openGuide', 'settings', 'add', 'delete']) {
      assert.ok(commands.includes(`cxAccounts.${name}`), `command ${name} registered`);
    }
    for (const name of ['refresh', 'providerAdd', 'providerEdit', 'providerSwitch', 'providerImport', 'providerImportCC', 'providerTest', 'providerRestore']) {
      assert.ok(commands.includes(`cxClaude.${name}`), `Claude command ${name} registered`);
    }
    assert.equal(api.claude.getSnapshot().application, 'claude');
    await vscode.commands.executeCommand('cxAccounts.add', { email: 'four@example.invalid', authorize: false });
    const added = api.getSnapshot().accounts.find(a => a.email === 'four@example.invalid');
    assert.equal(added.id, '4');
    assert.equal(api.getSnapshot().selected, '3');
    await vscode.commands.executeCommand('cxAccounts.delete', { account: added });
    assert.equal(api.getSnapshot().accounts.length, 3);
    await api.refresh(true);
    const refreshed = api.getSnapshot();
    assert.equal(refreshed.selected, '3');
    assert.equal(refreshed.accounts.length, 3);
    assert.ok(refreshed.accounts.every(a => a.error), 'incompatible fixture backend gives per-account errors');
    fs.writeFileSync(resultFile, JSON.stringify({ passed: true, selected: refreshed.selected,
      checks: ['activation', 'snapshot', 'command-registration', 'account-add-delete', 'claude-command-registration', 'claude-snapshot', 'refresh-error-handling', 'selection-preservation'] }));
  } catch (error) {
    fs.writeFileSync(resultFile, JSON.stringify({ passed: false, error: error.stack }));
    throw error;
  }
};
