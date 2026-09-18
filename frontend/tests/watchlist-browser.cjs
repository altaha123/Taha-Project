/* The watchlist across a sign-in.
 *
 * The store is covered by backend/tests/test_accounts.py. What cannot be
 * covered there is the handoff: a list built signed out has to survive signing
 * in, a removal has to stick across a reload, and a save the network dropped
 * must not claim to have reached the account. All three are silent when they
 * break — the star still turns gold — so they are checked in a real browser.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const HARNESS = `<!doctype html><meta charset="utf-8"><title>watchlist harness</title>
<body><div class="stk-id"></div>
<script>window.API_BASE = 'https://api.test';</script>
<script src="auth.js"></script><script src="experience.js"></script></body>`;

(async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 850 } });
    const calls = [];
    let account = [], saveFails = false;

    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const body = () => { try { return JSON.parse(route.request().postData() || '{}'); } catch (_) { return {}; } };
      if (url.hostname === 'altaha.test') {
        if (url.pathname === '/harness.html')
          return route.fulfill({ body: HARNESS, contentType: 'text/html' });
        const file = path.join(__dirname, '..', path.basename(url.pathname));
        if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
        return route.fulfill({ body: fs.readFileSync(file), contentType:
          file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css'
          : file.endsWith('.webp') ? 'image/webp' : 'text/html' });
      }
      calls.push(route.request().method() + ' ' + url.pathname);
      if (url.pathname === '/auth/me')
        return route.fulfill({ json: { email: 'reader@example.com', digest_opt_in: true,
                                       holdings: 0, watchlist: account.length } });
      if (url.pathname === '/me/watchlist' && route.request().method() === 'GET')
        return route.fulfill({ json: { symbols: account } });
      if (url.pathname === '/me/watchlist') {                       // PUT
        if (saveFails) return route.fulfill({ status: 503, json: { detail: 'down' } });
        account = body().symbols || [];
        return route.fulfill({ json: { saved: account.length, rejected: [], symbols: account } });
      }
      if (url.pathname === '/me/watchlist/merge') {
        for (const sym of body().symbols || []) if (!account.includes(sym)) account.push(sym);
        return route.fulfill({ json: { added: 0, rejected: [], symbols: account } });
      }
      return route.abort();
    });

    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const open = async () => {
      await page.goto('https://altaha.test/harness.html?ticker=INFY');
      await page.locator('[data-save-stock="INFY"]').waitFor();
    };
    const listed = () => page.evaluate(() => JSON.parse(localStorage.getItem('altaha-watchlist-v1') || '[]'));
    const note = () => page.evaluate(() => document.querySelector('.ux-dialog .ux-note').textContent);
    const until = async (fn, what) => {
      for (let i = 0; i < 60; i++) { if (await fn()) return; await page.waitForTimeout(100); }
      throw new Error('timed out waiting for ' + what);
    };
    const signIn = () => page.evaluate(() => localStorage.setItem('altaha-session-v1', 'a-session'));
    const openList = () => page.locator('.ux-bottom button', { hasText: 'Watchlist' }).click();
    const closeList = () => page.locator('.ux-dialog-head button').click();

    // 1. Signed out, the list is this browser's and nothing is sent anywhere.
    await open();
    await page.locator('[data-save-stock="INFY"]').click();
    assert.deepEqual(await listed(), ['INFY']);
    assert.match(await note(), /this browser only\. Sign in/);
    assert.deepEqual(calls, []);

    // 2. Signing in hands that list over rather than replacing it with an
    //    empty account, and keeps what the account already had.
    account = ['TCS'];
    await signIn();
    await open();
    await page.waitForFunction(() => document.querySelectorAll('.ux-saved-row').length === 2);
    assert.deepEqual(await listed(), ['TCS', 'INFY']);
    assert.match(await note(), /Saved to your account/);
    assert.equal(calls.filter(c => c.endsWith('/me/watchlist/merge')).length, 1);

    // 3. A second visit reads the account instead of merging again — merging
    //    twice is what pushes back a stock removed on another device.
    account = ['TCS'];
    calls.length = 0;
    await open();
    await page.waitForFunction(() => document.querySelectorAll('.ux-saved-row').length === 1);
    assert.deepEqual(await listed(), ['TCS']);
    assert.deepEqual(calls.filter(c => c.includes('watchlist')), ['GET /me/watchlist']);

    // 4. A removal reaches the account, so it is still gone on the next device.
    await openList();
    await page.locator('.ux-saved-row button').click();
    await page.waitForFunction(() => !document.querySelectorAll('.ux-saved-row').length);
    await until(() => account.length === 0, 'the removal to reach the account');
    assert.deepEqual(await listed(), []);
    await closeList();

    // 5. When the account cannot be reached the star still lights, because the
    //    stock IS saved here — but the reader is told where it is saved.
    saveFails = true;
    await page.locator('[data-save-stock="INFY"]').click();
    await page.getByText(/catch up when the connection does/).waitFor();
    assert.deepEqual(await listed(), ['INFY']);
    assert.deepEqual(account, []);

    // 6. ...and the next visit retries that edit rather than adopting an
    //    account copy that never heard about it.
    saveFails = false;
    await open();
    await until(() => account.length === 1, 'the unsent edit to be retried');
    assert.deepEqual(await listed(), ['INFY']);
    assert.deepEqual(account, ['INFY']);

    assert.deepEqual(errors, []);
    await context.close();
    console.log('Watchlist survives sign-in, removals stick, and a failed save says so.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
