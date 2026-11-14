/* The home page's opening data comes from one early request (boot.js).
   This checks the behaviour that must never go wrong:
     - an answer in /boot is handed to the page without a second request;
     - it is handed over once: the next request for the same thing is real;
     - a part /boot does not have goes to the network as before;
     - signed-in requests and writes are never answered from /boot;
     - /boot failing, or being slow, costs the page nothing but the speed-up. */
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const assert = require('assert');
const API = 'https://taha-project.onrender.com';
const bootJs = fs.readFileSync(path.join(__dirname, '..', 'boot.js'), 'utf8');

async function open(browser, boot) {
  const context = await browser.newContext();
  const seen = [];
  await context.route('**/*', async route => {
    const u = new URL(route.request().url());
    if (u.hostname === 'site.test') {
      if (u.pathname === '/boot.js') return route.fulfill({ contentType: 'text/javascript', body: bootJs });
      return route.fulfill({ contentType: 'text/html', body: '<!doctype html><script src="/boot.js"></script><p>ok</p>' });
    }
    if (u.origin === API) {
      seen.push(route.request().method() + ' ' + u.pathname + u.search);
      if (u.pathname === '/boot') return boot(route);
      return route.fulfill({ json: { from: 'network', path: u.pathname + u.search },
                             headers: { 'Access-Control-Allow-Origin': '*' } });
    }
    return route.abort();
  });
  const page = await context.newPage();
  await page.goto('http://site.test/');
  return { page, seen, context };
}
const cors = { 'Access-Control-Allow-Origin': '*' };
const get = (page, p, init) => page.evaluate(([u, i]) => fetch(u, i || undefined).then(r => r.json()), [API + p, init]);

(async () => {
  const browser = await chromium.launch();

  /* 1. the ordinary case */
  {
    const { page, seen, context } = await open(browser, route => route.fulfill({ headers: cors, json: {
      at: '2026-11-14T10:00:00+05:30',
      data: { '/market': { from: 'boot', n: 1 }, '/sector/overview?window=1D&stocks=1': { from: 'boot', n: 2 },
              '/not/a/known/key': { from: 'boot' } }, age: {} } }));
    assert.deepStrictEqual(await get(page, '/market'), { from: 'boot', n: 1 });
    assert.deepStrictEqual(seen, ['GET /boot'], 'the answer came from /boot, with no second request');
    // parameters in another order are the same request
    assert.deepStrictEqual(await get(page, '/sector/overview?stocks=1&window=1D'), { from: 'boot', n: 2 });
    // once only: a refresh is a real request
    assert.strictEqual((await get(page, '/market')).from, 'network');
    // a part /boot did not have
    assert.strictEqual((await get(page, '/results/calendar')).from, 'network');
    // something /boot never answers, even if the server sent it
    assert.strictEqual((await get(page, '/not/a/known/key')).from, 'network');
    // a different question on the same path
    assert.strictEqual((await get(page, '/ideas?horizon=month&limit=15')).from, 'network');
    await context.close();
  }

  /* 2. signed-in requests and writes always go to the network */
  {
    const { page, context } = await open(browser, route => route.fulfill({ headers: cors, json: {
      at: 'x', data: { '/market': { from: 'boot' }, '/deals?limit=6': { from: 'boot' } }, age: {} } }));
    assert.strictEqual((await get(page, '/market', { headers: { 'X-Test': '1' } })).from, 'network');
    assert.strictEqual((await get(page, '/deals?limit=6', { method: 'POST', body: '{}' })).from, 'network');
    await context.close();
  }

  /* 3. /boot fails: everything works as it did before */
  for (const boot of [route => route.fulfill({ status: 503, headers: cors, body: 'down' }),
                      route => route.abort(),
                      route => route.fulfill({ headers: cors, json: {} }),
                      route => route.fulfill({ headers: cors, json: { data: { '/market': { from: 'unsigned' } } } })]) {
    const { page, context } = await open(browser, boot);
    assert.strictEqual((await get(page, '/market')).from, 'network');
    await context.close();
  }

  /* 4. /boot is slow: a request waits a little, then goes to the network */
  {
    const { page, context } = await open(browser, async route => {
      await new Promise(r => setTimeout(r, 6000));
      route.fulfill({ headers: cors, json: { at: 'x', data: { '/market': { from: 'boot' } }, age: {} } }).catch(() => {});
    });
    const t0 = Date.now();
    assert.strictEqual((await get(page, '/market')).from, 'network');
    const took = Date.now() - t0;
    assert.ok(took >= 2000 && took < 4500, 'held for about the wait, not for /boot: ' + took + ' ms');
    // a request /boot could never answer is not held at all
    const t1 = Date.now();
    await get(page, '/universe');
    assert.ok(Date.now() - t1 < 1000);
    await context.close();
  }

  await browser.close();
  console.log('boot: one early request answers the page, once, and never gets in the way');
})().catch(e => { console.error(e); process.exit(1); });
