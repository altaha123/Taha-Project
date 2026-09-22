/* The Delivery pane in a real Chromium, against a fixture produced by the real
   backend module (see backend/tests/make_delivery_fixture.py). No live calls.

   What this is actually guarding:
     · A MISSING READING IS NOT A DELIVERED ZERO. "0" in the delivered column
       is a dramatic claim about a company — nobody took delivery all day —
       and it renders identically to a bug. A session the exchange published
       no quantity for must read as an em dash.
     · THE DERIVATION IS DISCLOSED. Delivered quantity is traded quantity
       times the published share, because the panel does not store NSE's
       DELIV_QTY. It is arithmetic on a filed figure, not a filed figure, and
       the page has to say so where the number is.
     · NOTHING IS FETCHED UNTIL THE PANE IS OPENED. This is a few hundred
       sessions of exchange data; a reader who came for the price must not pay
       for it.
     · A STOCK OUTSIDE THE STORE IS EXPLAINED, NOT ERRORED. Searching a small
       cap or a US ticker is not a mistake, and "unavailable" without a reason
       reads as a broken page.
     · phone through desktop, both themes, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/delivery');
fs.mkdirSync(output, { recursive: true });

const delivery = JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/delivery-reliance.json'), 'utf8'));

const analyze = {
  ticker: 'RELIANCE', name: 'Reliance Industries Limited', currency: 'INR', price: 1402.5,
  scoring: { score: 61, label: 'Watch', pillars: {}, checks: [] },
  profile: { sector: 'Energy', summary: 'Refining, retail and telecom.' },
  disclaimer: 'Educational tool.'
};

// What the endpoint returns for a name the store does not carry. Produced by
// the same code path as the real one: available:false with a reason.
const notCovered = {
  available: false, symbol: 'NVDA', reason: 'not_covered',
  min_turnover_cr: 25, covered_symbols: 612,
  message: 'No delivery record is held for NVDA. The exchange publishes this ' +
    'for NSE equity-series stocks only, and the store keeps the roughly 612 ' +
    'names that trade above about Rs 12 crore a day.'
};

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(root, p === '/' ? '/index.html' : p);
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

(async () => {
  await new Promise(r => server.listen(8775, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  const asked = [];
  let covered = true;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/delivery') {
      asked.push(u.searchParams.get('days'));
      return route.fulfill({ json: covered ? delivery : notCovered });
    }
    if (u.pathname === '/analyze') return route.fulfill({ json: analyze });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });

  await page.goto('http://127.0.0.1:8775/stock.html?ticker=RELIANCE', { waitUntil: 'domcontentloaded' });
  await page.locator('#pane-btn-deliv').waitFor();

  // ── Lazy, and only once ──────────────────────────────────────────────────
  assert.deepEqual(asked, [], 'delivery must not load before its pane is opened');
  await page.locator('#pane-btn-deliv').click();
  await page.locator('.dv-table').waitFor();
  assert.deepEqual(asked, ['60'], 'first open asks for the default window');
  await page.locator('#pane-btn-deliv').click();
  assert.deepEqual(asked, ['60'], 'reopening the pane must not refetch');

  // ── The headline figures are the ones the module computed ────────────────
  const tiles = await page.locator('.dv-tile').allInnerTexts();
  const joined = tiles.join(' | ');
  assert.match(joined, new RegExp(delivery.summary.latest.toFixed(2) + '%'),
    `latest share missing from tiles: ${joined}`);
  assert.match(joined, new RegExp(delivery.summary.avg_20.toFixed(2) + '%'));
  assert.match(joined, new RegExp(String(delivery.summary.year_sessions)),
    'the longer average must state how many sessions it actually holds');

  const rows = page.locator('.dv-table tbody tr');
  assert.equal(await rows.count(), delivery.rows.length);

  // The delivered share is the second column, not the last. This table is
  // wider than a phone, and the far-right column is the one nobody scrolls to.
  // innerText comes back uppercased: thead carries text-transform.
  assert.deepEqual(
    (await page.locator('.dv-table thead th').allInnerTexts()).map(t => t.toLowerCase()),
    ['session', 'delivered share', 'delivered', 'traded', 'close']);

  // ── The derivation, checked on screen ────────────────────────────────────
  // 2,000,000 traded at 66.00% is exactly 1,320,000 delivered. The page shows
  // it in lakh, which is how an Indian reader counts shares; the exact figure
  // stays in the cell's title.
  const first = rows.first();
  assert.equal(await first.locator('th').innerText(), delivery.rows[0].date);
  const deliveredCell = first.locator('td').nth(1);   // share, DELIVERED, traded, close
  assert.match(await deliveredCell.innerText(), /13\.20 L/);
  // en-IN grouping: 13,20,000, not 1,320,000. That is the point of the locale.
  assert.match(await deliveredCell.getAttribute('title'), /13,20,000 shares, derived/);
  assert.match(await page.locator('.dv-note').innerText(), /derived/i,
    'the page must disclose that delivered quantity is derived');

  // ── A missing reading is an em dash, never a zero ────────────────────────
  const holeIndex = delivery.rows.findIndex(r => r.traded_qty === null);
  assert.ok(holeIndex > -1, 'fixture must contain a session with no traded quantity');
  const hole = rows.nth(holeIndex);
  assert.equal(await hole.locator('td').nth(1).innerText(), '—');   // delivered
  assert.equal(await hole.locator('td').nth(2).innerText(), '—');   // traded
  // Its published share is still shown: that figure was not missing.
  assert.match(await hole.locator('td').nth(0).innerText(),
    new RegExp(delivery.rows[holeIndex].deliv_pct.toFixed(2) + '%'));

  const bodyText = await page.locator('#pane-deliv').innerText();
  assert.doesNotMatch(bodyText, /\b0 shares\b/);

  // ── The window buttons ask for the window ────────────────────────────────
  await page.locator('#dv-ranges button[data-d="120"]').click();
  await page.waitForFunction(() =>
    document.querySelector('#dv-ranges button[data-d="120"]').getAttribute('aria-pressed') === 'true');
  assert.deepEqual(asked, ['60', '120']);

  // ── A stock the store does not carry ─────────────────────────────────────
  covered = false;
  const other = await context.newPage();
  await other.goto('http://127.0.0.1:8775/stock.html?ticker=NVDA', { waitUntil: 'domcontentloaded' });
  await other.locator('#pane-btn-deliv').click();
  // The loading placeholder carries the same class, so wait for the settled
  // one rather than reading whichever was painted first.
  await other.locator('#pane-deliv .own-empty:not(.is-loading)').waitFor();
  const empty = await other.locator('#pane-deliv .own-empty').innerText();
  assert.match(empty, /NSE equity-series/, `reason not explained: ${empty}`);
  assert.equal(await other.locator('#pane-deliv .dv-table').count(), 0);
  await other.close();

  // ── It reads on a phone, in both themes ──────────────────────────────────
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(220);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `${width} ${theme}: horizontal page scroll`);
      await page.screenshot({ path: path.join(output, `${width}-${theme}.png`) });
    }
  }

  const relevant = errors.filter(e => /stock\.js/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close(); server.close();
  console.log('Delivery pane: lazy, derived figures disclosed, holes are dashes, not a zero');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
