const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { Client } = require('../src/client');

test('real JSON bridge accepts a key on stdin and returns only supplier metadata', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cx-provider-client-'));
  try {
    const client = new Client(path.resolve(__dirname, '..'), () => ({
      accountsRoot: path.join(root, 'accounts'), codexHome: path.join(root, 'codex'),
    }));
    const saved = await client.providerRequest('save', { name: 'Fixture supplier',
      baseUrl: 'https://fixture.example.invalid/v1', model: 'fixture-model', apiKey: 'cx-client-fixture-key',
    });
    assert.equal(saved.providers.length, 1);
    assert.equal(saved.providers[0].hasKey, true);
    assert.ok(!JSON.stringify(saved).includes('cx-client-fixture-key'));
    const enabled = await client.providerRequest('select', { id: saved.savedId });
    assert.equal(enabled.activeId, saved.savedId);
    const snapshot = await client.request('snapshot');
    assert.equal(snapshot.providerState.mode, 'thirdParty');
    assert.equal(snapshot.accounts.length, 3);
    await assert.rejects(client.request('select', '3'));
    assert.equal((await client.request('snapshot')).providerState.mode, 'thirdParty');
    const restored = await client.providerRequest('restore');
    assert.equal(restored.mode, 'official');
    await client.providerRequest('delete', { id: saved.savedId });
    assert.equal((await client.request('snapshot')).providerState.providers.length, 0);
  } finally {
    assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('cx-provider-client-'));
    fs.rmSync(root, { recursive: true, force: true });
  }
});
