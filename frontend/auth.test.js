const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/auth.js', 'utf8');
function setup(fetch, blocked = false) {
  const data = new Map();
  const events = {};
  const storage = { getItem: k => data.get(k), setItem(k, v) {
    if (blocked) throw Error('blocked'); data.set(k, v);
  }, removeItem: k => data.delete(k) };
  const window = { addEventListener: (k, fn) => events[k] = fn, dispatchEvent() {} };
  vm.runInNewContext(source, { window, localStorage: storage, fetch, AbortController,
    setTimeout, clearTimeout, CustomEvent: function () {}, console });
  return { auth: window.AltahaAuth, data, events };
}
const response = (status, body) => ({ status, ok: status === 200, json: async () => body });
const key = 'altaha-session-v1';
test('failed delivery and HTML proxy errors never report success', async () => {
  const { auth } = setup(async () => response(503, { detail: 'Email unavailable' }));
  await assert.rejects(auth.requestLink('a@example.com'), /Email unavailable/);
  const html = setup(async () => ({ ok: false, json: async () => { throw Error(); } }));
  await assert.rejects(html.auth.requestLink('a@example.com'), /temporarily unavailable/);
});
test('blocked storage does not consume a link', async () => {
  let calls = 0;
  const { auth } = setup(async () => { calls++; }, true);
  await assert.rejects(auth.verify('one-time'), /storage/);
  assert.equal(calls, 0);
});
test('successful verification persists session; logout clears it', async () => {
  const { auth } = setup(async () => response(200, { token: 'session', user: { email: 'a@example.com' } }));
  await auth.verify('link');
  assert.equal(auth.token(), 'session');
  assert.equal(auth.user().email, 'a@example.com');
  await auth.signOut();
  assert.equal(auth.user(), null);
  assert.equal(auth.token(), '');
});
test('expired session clears, temporary server failure preserves session', async () => {
  let status = 503;
  const { auth, data } = setup(async () => response(status, {}));
  data.set(key, 'old');
  await auth.refresh();
  assert.equal(auth.token(), 'old');
  status = 401;
  await auth.refresh();
  assert.equal(auth.token(), '');
});
test('late 401 cannot clear a newer sign-in', async () => {
  let finish;
  const { auth, data } = setup(() => new Promise(resolve => finish = resolve));
  data.set(key, 'old');
  const pending = auth.refresh();
  data.set(key, 'new');
  finish(response(401, {}));
  await pending;
  assert.equal(auth.token(), 'new');
});
test('late profile cannot resurrect signed-out user', async () => {
  let finish;
  const { auth, data } = setup(() => new Promise(resolve => finish = resolve));
  data.set(key, 'old');
  const pending = auth.refresh();
  data.delete(key);
  finish(response(200, { email: 'old@example.com' }));
  await pending;
  assert.equal(auth.user(), null);
});
