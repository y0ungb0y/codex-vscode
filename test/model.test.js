const test = require('node:test');
const assert = require('node:assert/strict');
const { summary, reset, remaining, mergeSnapshot, translateError } = require('../src/model');
const { Client, runJson } = require('../src/client');

test('quota uses remaining percent and distinguishes unavailable from zero', () => {
  assert.equal(remaining({ remaining: 0 }), '0%');
  assert.equal(remaining(null), '未提供');
  assert.equal(summary({ quota: { five_hour: { remaining: 95 }, weekly: { remaining: 0 } } }), '5h 95% · 周 0%');
  assert.match(summary({ error: 'login expired or rejected; sign in again' }), /重新授权/);
});
test('reset times are Beijing time independent of the host timezone', () => {
  assert.match(reset({ resets_at: Date.UTC(2026, 10, 11, 0, 0) / 1000 }), /08:00.*北京时间/);
  assert.equal(reset(null), '未提供重置时间');
});
test('snapshot updates preserve quota query time, discard mismatched account metadata', () => {
  const old = { quotaUpdatedAt: 'old', accounts: [{ id: '1', email: 'a@b', quota: { weekly: { remaining: 4 } } }] };
  const merged = mergeSnapshot(old, { updatedAt: 'new', accounts: [{ id: '1', email: 'a@b', saved: true, selected: true }] });
  assert.equal(merged.quotaUpdatedAt, 'old');
  assert.equal(merged.accounts[0].quota.weekly.remaining, 4);
  const different = mergeSnapshot(old, { accounts: [{ id: '1', email: 'other@b', saved: true }] });
  assert.equal(different.accounts[0].quota, undefined);
});
test('client uses JSON output without exposing raw stderr and rejects invalid operations', async () => {
  const json = await runJson(process.execPath, ['-e', 'console.log(JSON.stringify({selected:"3"}))']);
  assert.equal(json.selected, '3');
  await assert.rejects(runJson(process.execPath, ['-e', 'console.error("secret-stderr");console.log("bad-json")']),
    error => !error.message.includes('secret-stderr'));
  const client = new Client(__dirname, () => ({}));
  await assert.rejects(client.request('select', '4'), /无效/);
});
test('client timeout is bounded and CLI commands cannot be injected', async () => {
  await assert.rejects(runJson(process.execPath, ['-e', 'setTimeout(()=>{},10000)'], { timeout: 50 }), /超时/);
  const client = new Client(__dirname, () => ({}));
  await assert.rejects(client.request('exec', '1'), /无效/);
});

test('provider secrets travel on stdin rather than command arguments', async () => {
  const program = 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.stringify({received:JSON.parse(s).apiKey==="fixture-key",argvSafe:!process.argv.includes("fixture-key")})))';
  const result = await runJson(process.execPath, ['-e', program], { input: { apiKey: 'fixture-key' } });
  assert.deepEqual(result, { received: true, argvSafe: true });
  const client = new Client(__dirname, () => ({}));
  await assert.rejects(client.providerRequest('exec'), /无效/);
});
