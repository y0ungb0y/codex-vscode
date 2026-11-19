const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { Client } = require('../src/client');

test('real client adds slot 4, switches it and archives removal without exporting credentials', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cx-account-client-'));
  const emails = { '1': 'one@example.invalid', '2': 'two@example.invalid', '3': 'three@example.invalid' };
  const options = { accountsRoot: path.join(root, 'accounts'), codexHome: path.join(root, 'codex'), emails };
  const client = new Client(path.resolve(__dirname, '..'), () => options);
  const authorizeFixture = (number, email) => {
    const directory = path.join(options.accountsRoot, number);
    fs.mkdirSync(directory, { recursive: true });
    const claims = Buffer.from(JSON.stringify({ email })).toString('base64url');
    fs.writeFileSync(path.join(directory, 'auth.json'), JSON.stringify({ tokens: {
      id_token: `fixture.${claims}.fixture`, refresh_token: 'fixture-private-login', account_id: 'fixture-' + number,
    } }));
  };
  try {
    const added = await client.accountRequest('add', { email: 'four@example.invalid' });
    assert.equal(added.addedId, '4');
    assert.equal(added.accounts.length, 4);
    assert.doesNotMatch(JSON.stringify(added), /refresh_token|id_token|fixture-private-login/);
    authorizeFixture('4', 'four@example.invalid');
    authorizeFixture('1', emails['1']);
    assert.equal((await client.request('select', '4')).selected, '4');
    const terminal = await client.loginTerminalOptions('4');
    assert.equal(terminal.shellArgs.at(-1), '4');
    await assert.rejects(client.accountRequest('delete', { id: '4' }), /切换/);
    await client.request('select', '1');
    const removed = await client.accountRequest('delete', { id: '4', expectedEmail: 'four@example.invalid' });
    assert.equal(removed.accounts.length, 3);
    assert.equal(removed.selected, '1');
    assert.equal(fs.existsSync(path.join(options.accountsRoot, '4', 'auth.json')), false);
    assert.equal(fs.existsSync(path.join(removed.backupPath, 'auth.json')), true);
    assert.doesNotMatch(JSON.stringify(removed), /refresh_token|id_token|fixture-private-login/);
    assert.equal((await client.accountRequest('add', { email: 'five@example.invalid' })).addedId, '5');
    await assert.rejects(client.accountRequest('exec'), /无效/);
  } finally {
    assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('cx-account-client-'));
    fs.rmSync(root, { recursive: true, force: true });
  }
});
