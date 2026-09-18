/* The portfolio panel's three quiet lies.
 *
 * 1. An uploaded list lived in memory only. Import a broker file, reload, and
 *    twenty-one holdings were gone with nothing saying so.
 * 2. The line above the account box read "Saved in this browser — sign in",
 *    sitting directly on top of a box reading "Signed in as ...".
 * 3. "Send me today's email" wrote its answer to a note several screens below
 *    the button, so pressing it looked like pressing a dead button.
 *
 * None of the three throws. All three are only visible on a screen.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');

const server = http.createServer((req, res) => {
  const name = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!name.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      name.endsWith('.js') ? 'text/javascript' :
      name.endsWith('.css') ? 'text/css' :
      name.endsWith('.html') ? 'text/html' : 'application/octet-stream');
    res.end(fs.readFileSync(name));
  } catch (e) { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(r => server.listen(8767, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    let signedIn = false, accountHoldings = [], sendResult = null;
    const calls = [];

    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      if (p === '/auth/me') {
        return signedIn
          ? route.fulfill({ json: { email: 'reader@example.com', digest_opt_in: true,
                                    holdings: accountHoldings.length, watchlist: 0 } })
          : route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
      }
      if (p === '/me/portfolio') {
        calls.push(route.request().method() + ' ' + p);
        if (route.request().method() === 'PUT') {
          accountHoldings = (JSON.parse(route.request().postData() || '{}').holdings) || [];
          return route.fulfill({ json: { saved: accountHoldings.length, rejected: [],
                                         holdings: accountHoldings } });
        }
        return route.fulfill({ json: { holdings: accountHoldings } });
      }
      if (p === '/me/digest/send-test') {
        calls.push('POST ' + p);
        return sendResult
          ? route.fulfill({ json: sendResult })
          : route.fulfill({ status: 400, json: { detail: 'Save a portfolio first.' } });
      }
      if (url.hostname !== '127.0.0.1') {
        const kind = route.request().resourceType();
        if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
        return route.fulfill({ json: { available: false, rows: [], rankings: [],
                                       sectors: [], items: [], status: 'idle' } });
      }
      return route.continue();
    });

    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e.stack)));
    const open = async () => {
      await page.goto('http://127.0.0.1:8767/?go=portfolio', { waitUntil: 'domcontentloaded' });
      await page.locator('#pf_rows .pf_sym').first().waitFor();
    };
    const lede = () => page.locator('#pf_lede').innerText();

    // ── 1. What is on the screen is still there after a reload ──────────────
    await open();
    await page.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
    await page.locator('#pf_rows .pf_qty').first().fill('10');
    await page.locator('#pf_rows .pf_buy').first().fill('1650');
    await page.waitForFunction(() =>
      JSON.parse(localStorage.getItem('altaha-portfolio-draft-v1') || 'null'));

    await open();
    assert.equal(await page.locator('#pf_rows .pf_sym').first().inputValue(), 'HDFCBANK',
      'the holding on screen did not survive a reload');
    assert.equal(await page.locator('#pf_rows .pf_qty').first().inputValue(), '10');
    assert.equal(await page.locator('#pf_rows .pf_buy').first().inputValue(), '1650',
      'the cost basis was dropped on the way back');

    // ── 2. The lede tells the truth about where the list lives ──────────────
    assert.match(await lede(), /Saved in this browser/);
    assert.match(await lede(), /sign in/i);

    signedIn = true;
    await page.evaluate(() => localStorage.setItem('altaha-session-v1', 'a-session'));
    await open();
    await page.locator('.pfacct.on').waitFor();
    const signedInLede = await lede();
    assert.doesNotMatch(signedInLede, /Saved in this browser/,
      'a signed-in reader is still being told their list is browser-only');
    assert.doesNotMatch(signedInLede, /sign in/i,
      'a signed-in reader is still being told to sign in');
    assert.match(signedInLede, /Save/);

    // ── 3. The button answers where the button is ───────────────────────────
    // Nothing held yet: it says so beside itself, and does not go to the server
    // to be told the same thing.
    page.once('dialog', d => d.accept());
    await page.locator('#pf_clear').click();
    await page.waitForFunction(() =>
      !document.querySelector('#pf_rows .pf_sym').value, null, { timeout: 5000 });
    calls.length = 0;
    await page.locator('#pf_sendtest').click();
    await page.locator('#pf_acctnote').waitFor({ state: 'visible' });
    assert.match(await page.locator('#pf_acctnote').innerText(), /at least one holding/i);
    assert.ok(!calls.some(c => c.includes('send-test')),
      'asked the server a question the page could already answer');

    // With a holding, the answer is the real one — still beside the button.
    await page.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
    await page.locator('#pf_rows .pf_qty').first().fill('10');
    sendResult = { sent: true, subject: 'Your holdings today', provider: 'test' };
    await page.locator('#pf_sendtest').click();
    // Wait for the answer, not for the "sending" line that also names the
    // address — the two are one keystroke apart and only one of them is proof.
    await page.waitForFunction(() =>
      /Your holdings today/.test(document.getElementById('pf_acctnote').textContent));
    assert.match(await page.locator('#pf_acctnote').innerText(), /reader@example\.com/);
    assert.ok(calls.some(c => c === 'POST /me/digest/send-test'));

    assert.deepEqual(errors, []);
    await context.close();
    console.log('Portfolio: the list survives a reload, the lede matches the session, ' +
                'and the email button answers where it stands.');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
