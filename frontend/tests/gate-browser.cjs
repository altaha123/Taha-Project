/* The sign-in gate (gate.js), in a real browser.

   Signed out, the member tools show a sign-in card in their place and the
   card sends the reader to signin.html with a way back to the same tool.
   Signed in, the tool itself is on screen and the card is not. Tools that
   are not gated stay open either way.

   Nothing here touches a network: the API is answered with empty shapes. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');

const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8'
      : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

const GATED = [
  ['discover', 'live', 'Alerts'],
  ['discover', 'deals', 'Big trades'],
  ['discover', 'special', 'Delivery trends'],
  ['research', 'lenses', 'Investor styles'],
  ['research', 'investors', 'Who owns what'],
  ['research', 'funds', 'Fund houses'],
  ['research', 'strategies', 'Strategy lab']
];

(async () => {
  await new Promise(resolve => server.listen(8779, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  async function context(signedIn, width) {
    const ctx = await browser.newContext({ viewport: { width: width || 1280, height: 900 } });
    await ctx.addInitScript(on => {
      localStorage.setItem('altaha-guide-dismissed', '1');
      if (on) localStorage.setItem('altaha-session-v1', 'test-session');
    }, signedIn);
    await ctx.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/auth/me') return route.fulfill({ json: { email: 'reader@example.com' } });
      return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [], items: [],
                                     sectors: [], rankings: [], status: 'idle' } });
    });
    return ctx;
  }

  const base = 'http://127.0.0.1:8779/';
  const shown = (page, sel) => page.evaluate(s => {
    const n = document.querySelector(s);
    return !!n && getComputedStyle(n).display !== 'none' && n.getClientRects().length > 0;
  }, sel);

  /* ── 1 · Signed out: every member tool is a sign-in card ─────────────── */
  for (const width of [1280, 390]) {
    const ctx = await context(false, width);
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    for (const [door, tab, label] of GATED) {
      await page.goto(base + '#' + door + '/' + tab, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(t => document.body.dataset.tab === t, tab);
      await page.locator('#altaha-gate .ag-go').waitFor({ state: 'visible' });
      assert.equal(await shown(page, '#view-' + tab), false, label + ' must be hidden signed out');
      assert.match(await page.locator('#ag-title').innerText(), new RegExp(label));
      const href = await page.locator('#ag-go').getAttribute('href');
      assert.equal(decodeURIComponent(href.split('next=')[1]), 'index.html#' + door + '/' + tab,
        label + ' sign-in must come back to the same tool');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false,
        'the sign-in card must fit at ' + width);
    }

    // A tool that is not gated stays open, and the card is not shown over it.
    await page.goto(base + '#research/query', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.body.dataset.tab === 'query');
    assert.equal(await shown(page, '#altaha-gate'), false, 'the screener is not gated');
    assert.equal(await shown(page, '#view-query'), true, 'the screener stays open signed out');

    // Opened by a click rather than an address, the gate is the same.
    await page.evaluate(() => window.AltahaNav.go('discover', 'deals', true));
    await page.waitForFunction(() => document.body.dataset.tab === 'deals');
    assert.equal(await shown(page, '#altaha-gate'), true, 'a click to Big trades is gated too');
    assert.equal(await shown(page, '#view-deals'), false);

    // The card goes to the sign-in page.
    await page.locator('#ag-go').click();
    await page.waitForURL(/signin\.html\?next=index\.html%23discover%2Fdeals/);
    await ctx.close();
  }

  /* ── 2 · Signed in: the tool, not the card ───────────────────────────── */
  {
    const ctx = await context(true);
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    for (const [door, tab, label] of GATED) {
      await page.goto(base + '#' + door + '/' + tab, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(t => document.body.dataset.tab === t, tab);
      await page.waitForFunction(t => {
        const n = document.getElementById('view-' + t);
        return n && getComputedStyle(n).display !== 'none';
      }, tab);
      assert.equal(await shown(page, '#altaha-gate'), false, label + ' must not show the card signed in');
    }

    // Signing out on this page closes the tool again, without a reload.
    await page.evaluate(() => window.AltahaAuth.signOut());
    await page.waitForFunction(() => document.documentElement.classList.contains('gate-out'));
    assert.equal(await shown(page, '#view-strategies'), false, 'signing out hides the tool again');
    assert.equal(await shown(page, '#altaha-gate'), true);
    await ctx.close();
  }

  /* ── 3 · The adviser page and the wealth desk ────────────────────────── */
  for (const [file, main, label] of [['advisors.html', '#adv', 'Talk to an adviser'],
                                     ['wealth.html', '#wd', 'Wealth desk']]) {
    let ctx = await context(false);
    let page = await ctx.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + file, { waitUntil: 'domcontentloaded' });
    await page.locator('#altaha-gate .ag-go').waitFor({ state: 'visible' });
    assert.equal(await shown(page, main), false, label + ' must be hidden signed out');
    assert.match(await page.locator('#ag-title').innerText(), new RegExp(label));
    assert.equal(decodeURIComponent((await page.locator('#ag-go').getAttribute('href')).split('next=')[1]), file);
    await ctx.close();

    ctx = await context(true);
    page = await ctx.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + file, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(m => getComputedStyle(document.querySelector(m)).display !== 'none', main);
    assert.equal(await shown(page, '#altaha-gate'), false, label + ' must open signed in');
    await ctx.close();
  }

  const ours = errors.filter(e => /gate\.js/.test(e));
  assert.deepEqual(ours, [], 'gate.js threw');
  console.log('gate: signed-out card on 7 tools and 2 pages, open when signed in');
  await browser.close();
  server.close();
})().catch(e => { console.error(e); process.exit(1); });
