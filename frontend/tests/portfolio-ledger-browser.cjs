/* The holdings editor as a ledger (portfolio.js, section 3a).
 *
 * Readers said the editor was unattractive and took too much room: every
 * holding was a block of four labelled form boxes, so twenty-one stocks ran to
 * about 2,300px on a laptop and 6,000px on a phone, and none of it said how
 * the portfolio was doing. This pins the replacement:
 *
 *   1. One line per holding: a badge, the symbol with the company's name,
 *      quantity and average cost typed in place, today's price, value and
 *      profit — and the whole list in well under half the old height.
 *   2. A board above it: worth now, invested, profit and today's move, worked
 *      out from the quotes the page was given and nothing else.
 *   3. Sorting reorders the saved list; a new row is focused; a removed row is
 *      gone from the draft.
 *   4. A symbol without a price says so, and nothing is estimated.
 *   5. The signed-in box is one slim strip, and its controls still work.
 *   6. A phone gets compact cards, no sideways scroll, and every input is
 *      still a real input.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');
const output = path.resolve('test-results/portfolio-ledger');
fs.mkdirSync(output, { recursive: true });

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

// 21 holdings, the size of the portfolio in the report that prompted this.
const HOLD = [
  ['HSCL', 66, 713.44], ['IRISDOREME', 900, 57.97], ['TCS', 10, 3400], ['RELIANCE', 25, 1250],
  ['HDFCBANK', 30, 1600], ['INFY', 20, 1500], ['ITC', 100, 420], ['SBIN', 40, 700],
  ['LT', 8, 3300], ['BHARTIARTL', 15, 1500], ['SUNPHARMA', 20, 1650], ['ASIANPAINT', 10, 2900],
  ['MARUTI', 2, 11000], ['TITAN', 6, 3300], ['NESTLEIND', 10, 2300], ['HINDALCO', 60, 600],
  ['NHPC', 300, 85], ['DIVISLAB', 5, 5600], ['ALKEM', 6, 5100], ['ABB', 4, 6500], ['KAYNES', 3, 5000]
];
// A price for every holding but KAYNES: 10% above cost, and 1% up on the day.
const QUOTES = {};
HOLD.forEach(([s, , buy]) => {
  if (s === 'KAYNES') return;
  const ltp = Math.round(buy * 1.1 * 100) / 100;
  QUOTES[s] = { symbol: s, ltp, prev_close: Math.round(ltp / 1.01 * 100) / 100, change_pct: 1,
                spark: [buy, buy * 1.05, ltp], source: 'Test feed' };
});
QUOTES.WIPRO = { symbol: 'WIPRO', ltp: 200, prev_close: 202, change_pct: -0.99, spark: [210, 205, 200], source: 'Test feed' };
const NAMES = { HSCL: 'Himadri Speciality Chemical Limited', TCS: 'Tata Consultancy Services Limited', WIPRO: 'Wipro Limited' };

(async () => {
  await new Promise(r => server.listen(8785, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const draft = { rows: HOLD.map(([symbol, qty, buy]) => ({ symbol, qty: String(qty), buy: String(buy), date: '' })) };
  async function wire(context, opts) {
    opts = opts || {};
    await context.addInitScript(d => {
      try { localStorage.setItem('altaha-portfolio-draft-v1', JSON.stringify(d)); } catch (e) {}
    }, draft);
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      if (url.hostname === '127.0.0.1') return route.continue();
      const kind = route.request().resourceType();
      if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
      if (p === '/auth/me') {
        return opts.signedIn
          ? route.fulfill({ json: { email: 'reader@example.com', digest_opt_in: true } })
          : route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
      }
      if (p === '/me/portfolio') return route.fulfill({ json: { holdings: [] } });
      if (p === '/universe') {
        return route.fulfill({ json: { rows: Object.keys(NAMES).map(s => ({ s, n: NAMES[s], x: 'NSE' })) } });
      }
      if (p === '/watchlist/quotes') {
        const want = (url.searchParams.get('symbols') || '').split(',');
        return route.fulfill({ json: { rows: want.map(s => QUOTES[s]).filter(Boolean), pending: [] } });
      }
      return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
    });
  }
  const errors = [];

  try {
    // ── 1-4 · Desktop ──────────────────────────────────────────────────────
    {
      const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      await wire(context);
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e.stack)));
      await page.goto('http://127.0.0.1:8785/#portfolio', { waitUntil: 'domcontentloaded' });
      await page.locator('#pf_rows .pfrow').nth(20).waitFor();
      await page.waitForFunction(() => /Worth now/.test((document.getElementById('pf_board') || {}).textContent || ''));

      // 1 · One line per holding, and the list is compact.
      assert.equal(await page.locator('#pf_rows .pfrow').count(), 21);
      const geo = await page.evaluate(() => {
        const rows = [...document.querySelectorAll('#pf_rows .pfrow')];
        return { list: document.getElementById('pf_rows').getBoundingClientRect().height,
                 tallest: Math.max(...rows.map(r => r.getBoundingClientRect().height)) };
      });
      assert.ok(geo.tallest <= 80, `a holding takes ${geo.tallest}px; one line is the point`);
      assert.ok(geo.list < 1700, `21 holdings take ${geo.list}px (the old editor took ~2,300px)`);
      assert.ok(await page.locator('.pfhead').isVisible(), 'the one header for every row is missing');
      const first = page.locator('#pf_rows .pfrow').first();
      assert.equal(await first.locator('.pf-av').innerText(), 'HS');
      assert.match(await first.locator('.pf-name').innerText(), /Himadri Speciality Chemical/);
      // HSCL: 66 × 784.78 = 51,795; cost 47,087; profit 4,708 (10%).
      assert.match(await first.locator('.pf-price').innerText(), /₹784\.78/);
      assert.match(await first.locator('.pf-price').innerText(), /\+1\.00% today/);
      assert.match(await first.locator('.pf-val').innerText(), /₹51,795/);
      assert.match(await first.locator('.pf-val').innerText(), /\+₹4,708.*\+10\.0%/s);
      assert.equal(await first.locator('.pf-val .pf-pl.up').count(), 1, 'a profit is not shown as one');

      // 2 · The board adds up what is on screen.
      const board = await page.locator('#pf_board').innerText();
      assert.match(board, /21 stocks/);
      assert.match(board, /20 in profit/, 'KAYNES has no price, so it is neither in profit nor in loss');
      assert.match(board, /\+10\.0% overall/);
      assert.match(board, /20 of 21 priced/);
      // The strip is split by value now, so a holding with no price has no share to draw.
      assert.equal(await page.locator('#pf_board .pf-strip i').count(), 20, 'every priced holding belongs in the allocation strip');
      assert.ok(await page.locator('.pf-tag', { hasText: 'Biggest' }).count() === 1, 'the largest holding is not marked');

      // 4 · No price, no estimate.
      const kaynes = page.locator('#pf_rows .pfrow').nth(20);
      assert.match(await kaynes.locator('.pf-price').innerText(), /—/);
      assert.match(await kaynes.locator('.pf-val').innerText(), /₹15,000\s*invested/, 'without a price the row shows what was put in');

      // 3 · Sorting reorders the saved list.
      await page.locator('[data-pfsort="az"]').click();
      const az = await page.$$eval('#pf_rows .pf_sym', ns => ns.map(n => n.value));
      assert.deepEqual(az, [...az].sort(), 'A–Z did not sort');
      assert.equal(await page.locator('[data-pfsort="az"]').getAttribute('aria-pressed'), 'true');
      const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-portfolio-draft-v1')).rows.map(r => r.symbol));
      assert.deepEqual(saved, az, 'the draft does not keep the order on screen');
      await page.locator('[data-pfsort="value"]').click();
      const vals = await page.$$eval('#pf_rows .pf-val b', ns => ns.map(n => Number(n.textContent.replace(/[^0-9.]/g, ''))));
      assert.deepEqual(vals, [...vals].sort((a, b) => b - a), 'Biggest is not largest first');

      // A new row is ready to type into, and gets its name and price.
      await page.locator('#pf_addrow').click();
      const last = page.locator('#pf_rows .pfrow').last();
      assert.equal(await page.evaluate(() => {
        const r = [...document.querySelectorAll('#pf_rows .pfrow')].pop();
        return document.activeElement === r.querySelector('.pf_sym');
      }), true, 'the new row did not get the cursor');
      await page.keyboard.type('wipro');
      await last.locator('.pf_qty').fill('10');
      await last.locator('.pf_buy').fill('250');
      await page.waitForFunction(() => /₹200\.00/.test([...document.querySelectorAll('#pf_rows .pfrow')].pop().querySelector('.pf-price').textContent));
      assert.match(await last.locator('.pf-name').innerText(), /Wipro Limited/);
      assert.match(await last.locator('.pf-val').innerText(), /−₹500.*−20\.0%/s);
      assert.equal(await last.locator('.pf-val .pf-pl.dn').count(), 1, 'a loss is not shown as one');

      // Removing a row takes it out of the draft.
      await last.locator('.pfdel').click();
      assert.equal(await page.locator('#pf_rows .pfrow').count(), 21);
      assert.equal((await page.evaluate(() => localStorage.getItem('altaha-portfolio-draft-v1'))).includes('WIPRO'), false);

      // Analyse still reads the same model.
      assert.equal(await page.evaluate(() => document.querySelectorAll('#pf_rows .pf_sym').length), 21);
      await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: false });
      await context.close();
    }

    // ── 5 · The signed-in strip ────────────────────────────────────────────
    {
      const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      await context.addInitScript(() => { try { localStorage.setItem('altaha-session-v1', 'test-token'); } catch (e) {} });
      await wire(context, { signedIn: true });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e.stack)));
      await page.goto('http://127.0.0.1:8785/#portfolio', { waitUntil: 'domcontentloaded' });
      await page.locator('.pfacct.on').waitFor();
      const h = await page.locator('.pfacct.on').evaluate(n => n.getBoundingClientRect().height);
      assert.ok(h <= 80, `the signed-in box is ${h}px tall; it should be one strip`);
      assert.match(await page.locator('.pfacct.on').innerText(), /Signed in as reader@example\.com/);
      assert.equal(await page.locator('#pf_digest').isChecked(), true);
      assert.ok(await page.locator('#pf_sendtest').isVisible());
      await context.close();
    }

    // ── 6 · Phone ──────────────────────────────────────────────────────────
    {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
      await wire(context);
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e.stack)));
      await page.goto('http://127.0.0.1:8785/#portfolio', { waitUntil: 'domcontentloaded' });
      await page.locator('#pf_rows .pfrow').nth(20).waitFor();
      await page.waitForFunction(() => /Worth now/.test((document.getElementById('pf_board') || {}).textContent || ''));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the phone scrolls sideways');
      const list = await page.evaluate(() => document.getElementById('pf_rows').getBoundingClientRect().height);
      assert.ok(list < 3300, `21 holdings take ${list}px on a phone (the old editor took ~6,000px)`);
      const card = page.locator('#pf_rows .pfrow').first();
      for (const sel of ['.pf_sym', '.pf_qty', '.pf_buy']) {
        const box = await card.locator(sel).boundingBox();
        assert.ok(box && box.width >= 60, `${sel} is too narrow to read on a phone (${box && box.width}px)`);
      }
      // The remove button does not sit on top of a figure.
      const del = await card.locator('.pfdel').boundingBox();
      for (const sel of ['.pf-price', '.pf-val']) {
        const b = await card.locator(sel).boundingBox();
        const overlap = !(del.x + del.width <= b.x || b.x + b.width <= del.x || del.y + del.height <= b.y || b.y + b.height <= del.y);
        assert.equal(overlap, false, `the remove button covers ${sel}`);
      }
      await card.locator('.pf_qty').fill('70');
      assert.match(await card.locator('.pf-val').innerText(), /₹54,935/, 'typing a quantity did not update the value');
      await page.screenshot({ path: path.join(output, 'phone.png'), fullPage: false });
      await context.close();
    }

    assert.deepEqual(errors, [], 'the page threw');
    console.log('portfolio ledger ok — screenshots in test-results/portfolio-ledger');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
