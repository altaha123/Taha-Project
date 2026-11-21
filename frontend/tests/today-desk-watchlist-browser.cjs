/* Market › Your desk › Watchlist: every name shows its price and today's move.
 *
 * The desk used to take prices only from the sector feed, which carries the
 * large names. A small cap on the watchlist (EMCURE, ARROWGREEN) therefore
 * showed its symbol and nothing else. The desk now reads /watchlist/quotes,
 * the same read the Watchlist page makes, so this asserts that:
 *   - each watched name shows its price, today's % and today's ₹ move
 *   - a name the server has not fetched yet (`pending`) is asked for again
 *     and filled in when it arrives
 *   - a fall is marked as a fall, with a minus sign and the falling colour
 *   - the rows fit at phone and desktop widths
 * Run: node frontend/tests/today-desk-watchlist-browser.cjs
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/today-desk');
fs.mkdirSync(output, { recursive: true });

const indices = [{ label: 'NIFTY 50', level: 25800.6, change_pct: 1.12 }];
const sectors = { rows: [{ sector: 'Real Estate', change_pct: 1.2, up: 1, down: 0, total: 1,
  stocks: [{ symbol: 'DLF', change_pct: 2.9, ltp: 812.4 }] }], source: 'dhan', window: '1D' };
const quotes = {
  EMCURE: { symbol: 'EMCURE', ltp: 1402.5, prev_close: 1370.0, change_pct: 2.37, spark: [] },
  WELCORP: { symbol: 'WELCORP', ltp: 880.1, prev_close: 902.2, change_pct: -2.45, spark: [] },
  ARROWGREEN: { symbol: 'ARROWGREEN', ltp: 612.0, prev_close: 600.0, change_pct: 2.0, spark: [] }
};

const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(r => server.listen(8793, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  for (const width of [390, 1280]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2 });
    await context.addInitScript(() => {
      localStorage.setItem('altaha-guide-dismissed', '1');
      localStorage.setItem('altaha-watchlist-v1', JSON.stringify(['EMCURE', 'ARROWGREEN', 'WELCORP', 'DLF']));
    });
    const page = await context.newPage(), asked = [];
    page.on('pageerror', e => errors.push(String(e.stack)));
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/market') return route.fulfill({ json: { indices, status: 'open' } });
      if (u.pathname === '/sector/overview') return route.fulfill({ json: sectors });
      if (u.pathname === '/watchlist/quotes') {
        const syms = (u.searchParams.get('symbols') || '').split(',');
        asked.push(syms);
        // ARROWGREEN is not in the server's cache the first time it is asked for.
        const first = asked.filter(a => a.includes('ARROWGREEN')).length === 1;
        const rows = syms.filter(s => quotes[s] && !(s === 'ARROWGREEN' && first)).map(s => quotes[s]);
        const pending = syms.filter(s => s === 'ARROWGREEN' && first);
        return route.fulfill({ json: { rows, pending, market_open: true } });
      }
      return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
    });

    await page.goto('http://127.0.0.1:8793/', { waitUntil: 'domcontentloaded' });
    const row = sym => page.locator('#dr-desk-watch a[href="stock.html?ticker=' + sym + '"]');
    await row('EMCURE').locator('.dr-wchg b').waitFor();

    // A small cap the sector feed never carries: price, % and ₹ move.
    assert.match(await row('EMCURE').locator('.dr-wpx').innerText(), /₹1,402\.50/);
    assert.equal(await row('EMCURE').locator('.dr-wchg b').innerText(), '+2.37%');
    assert.equal(await row('EMCURE').locator('.dr-wchg small').innerText(), '+₹32.50');
    assert.match(await row('EMCURE').locator('.dr-wchg').getAttribute('class'), /\bup\b/);

    // A fall reads as a fall.
    assert.equal(await row('WELCORP').locator('.dr-wchg b').innerText(), '−2.45%');
    assert.equal(await row('WELCORP').locator('.dr-wchg small').innerText(), '−₹22.10');
    assert.match(await row('WELCORP').locator('.dr-wchg').getAttribute('class'), /\bdn\b/);

    // A name the sector feed does carry, and the server did not answer for,
    // still shows the feed's figures; the ₹ move is worked out from them.
    await page.waitForFunction(() => /812\.40/.test((document.querySelector('#dr-desk-watch a[href="stock.html?ticker=DLF"]') || {}).textContent || ''));
    assert.equal(await row('DLF').locator('.dr-wchg b').innerText(), '+2.90%');

    // The pending name is asked for again and filled in.
    await row('ARROWGREEN').locator('.dr-wchg b').waitFor({ timeout: 8000 });
    assert.equal(await row('ARROWGREEN').locator('.dr-wchg small').innerText(), '+₹12.00');
    assert.ok(asked.length >= 2 && asked[asked.length - 1].join() === 'ARROWGREEN', 'only the pending name is asked again');
    assert.match(await row('EMCURE').getAttribute('aria-label'), /EMCURE, 1,402\.50 rupees, \+2\.37% today/);

    const fit = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#dr-desk-watch .dr-wrow')];
      return { overflow: document.documentElement.scrollWidth > innerWidth + 1,
               clipped: rows.some(r => r.scrollWidth > r.clientWidth + 1) };
    });
    assert.deepEqual(fit, { overflow: false, clipped: false }, width + ': the desk rows fit');

    await page.locator('#dr-desk-watch').scrollIntoViewIfNeeded();
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
      await page.waitForTimeout(200);
      await page.locator('.dr-desk').screenshot({ path: path.join(output, `${width}-${theme}-desk.png`) });
    }
    await context.close();
  }

  const relevant = errors.filter(e => /doors\.js|shell\.js|nav\.js/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close(); server.close();
  console.log('Market desk watchlist shows price and today\'s move for every name');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
