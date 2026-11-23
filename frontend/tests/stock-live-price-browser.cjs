/* The stock page's price while the market trades, in a real Chromium.
   Run from the repository root: node frontend/tests/stock-live-price-browser.cjs

   The page is served with its API pointed at this file's own server, which
   answers /analyze and /chart from fixtures and holds /stream/quotes open as
   the real one does, pushing ticks when the test says so. The clock is fixed.

   What this is guarding:
     · IN THE SESSION THE PRICE FOLLOWS THE TAPE. The header price, the price
       in the stuck bar and the day's move all follow each tick, and "Live"
       says the stream is open.
     · THE DAY'S MOVE IS MEASURED FROM THE LAST SESSION'S CLOSE. If today's
       bar is in the daily series, that is the bar before it; if the series
       still ends on the last session, it is that session's close. Measured
       from the wrong one, a tick prints yesterday's move as today's.
     · OUT OF HOURS NOTHING IS OPENED. At the weekend the page asks for no
       stream and shows the close it was sent.
     · A STREAM THAT IS NOT THERE BREAKS NOTHING. An API answering with JSON
       instead of a stream leaves the page as it was, without an error. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/stock-live-price');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/stock-page.json'), 'utf8'));

const year = Array.from({ length: 120 }, (_, i) => {
  const v = 880 + i * 1.1;
  return [Date.UTC(2026, 5, 1) / 1000 + i * 86400, v, v, v, v, 1000];
});

// What /chart says about the last two closes, set per scenario.
let chart = {}, streamMode = 'stream';
const streams = [];        // open /stream/quotes responses
let streamAsks = 0;

const types = { '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.html': 'text/html; charset=utf-8', '.png': 'image/png' };
let PORT = 0;
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const json = o => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(o)); };
  if (u.pathname === '/analyze') return json(fx.analyze);
  if (u.pathname === '/chart') return json(Object.assign({ currency: 'INR', candles: year }, chart));
  if (u.pathname === '/stream/quotes') {
    streamAsks++;
    assert.equal(u.searchParams.get('tickers'), 'NORTHBANK');
    if (streamMode !== 'stream') return json({ detail: 'Live feed module not available' });
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    res.write(': heartbeat websocket\n\n');
    streams.push(res);
    req.on('close', () => streams.splice(streams.indexOf(res), 1));
    return;
  }
  const p = decodeURIComponent(u.pathname);
  const file = path.join(root, p === '/' ? '/index.html' : p);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return json({ available: false, rows: [], items: [] });
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  let body = fs.readFileSync(file);
  if (p === '/stock.html') {
    body = String(body).replace(/var API_BASE = "[^"]*"/, `var API_BASE = "http://127.0.0.1:${PORT}"`);
  }
  res.end(body);
});

function tick(ltp) {
  const frame = `data: ${JSON.stringify({ symbol: 'NORTHBANK', ltp, mode: 'websocket' })}\n\n`;
  streams.forEach(r => r.write(frame));
}

// 11:00 IST on Monday 23 Nov 2026, and noon on the Saturday before.
const MONDAY = new Date('2026-11-23T05:30:00Z'), SATURDAY = new Date('2026-11-21T06:30:00Z');

async function open(browser, when) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.clock.setFixedTime(when);
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    return u.hostname === '127.0.0.1' ? route.continue() : route.abort();
  });
  await page.goto(`http://127.0.0.1:${PORT}/stock.html?ticker=NORTHBANK`, { waitUntil: 'domcontentloaded' });
  await page.locator('#ov-spark svg').waitFor();
  return { context, page, errors };
}

const text = (page, sel) => page.locator(sel).innerText();

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  PORT = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    /* ── 1. In the session, today's bar in the series ─────────────────────── */
    {
      chart = { last: 1010, prev_close: 1000, day_change_pct: 1.0, as_of: '2026-11-23 00:00:00' };
      const t = await open(browser, MONDAY);
      const { page } = t;
      await page.locator('#px-live').waitFor({ state: 'visible' });
      assert.equal(await text(page, '#chg'), '+1% today');

      tick(1020);
      await page.waitForFunction(() => document.getElementById('px').textContent === '₹1,020.00');
      assert.equal(await text(page, '#chg'), '+2% today');
      assert.equal(await page.locator('#mini-px').textContent(), '₹1,020.00');
      assert.equal(await page.locator('#mini-chg').textContent(), '+2%');
      assert.match(await page.locator('#chg').getAttribute('class'), /\bup\b/);

      tick(995.5);
      await page.waitForFunction(() => document.getElementById('px').textContent === '₹995.50');
      assert.equal(await text(page, '#chg'), '-0.45% today');
      assert.match(await page.locator('#chg').getAttribute('class'), /\bdn\b/);
      assert.match(await page.locator('#px').getAttribute('class'), /\btick-dn\b/);
      await page.screenshot({ path: path.join(output, 'live-1280.png'), clip: { x: 0, y: 0, width: 1280, height: 420 } });

      // A phone: the marker fits under the price without pushing the page sideways.
      await page.setViewportSize({ width: 390, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        'the page scrolls sideways on a phone');
      assert.ok(await page.locator('#px-live').isVisible());
      await page.screenshot({ path: path.join(output, 'live-390.png'), clip: { x: 0, y: 0, width: 390, height: 520 } });
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 2. In the session, the series still ending on the last session ───── */
    {
      // Friday's close is 1010. Measured from Thursday's 990 a tick at 1020
      // would read +3.03%: Friday's move and today's, added up and called today.
      chart = { last: 1010, prev_close: 990, day_change_pct: 2.02, as_of: '2026-11-20 00:00:00' };
      const t = await open(browser, MONDAY);
      await t.page.locator('#px-live').waitFor({ state: 'visible' });
      tick(1020);
      await t.page.waitForFunction(() => document.getElementById('px').textContent === '₹1,020.00');
      assert.equal(await text(t.page, '#chg'), '+0.99% today');
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 3. At the weekend nothing is opened ───────────────────────────────── */
    {
      chart = { last: 1010, prev_close: 1000, day_change_pct: 1.0, as_of: '2026-11-20 00:00:00' };
      const before = streamAsks;
      const t = await open(browser, SATURDAY);
      await t.page.waitForTimeout(1500);
      assert.equal(streamAsks, before, 'a stream was opened at the weekend');
      assert.equal(await t.page.locator('#px-live').isVisible(), false);
      assert.equal(await text(t.page, '#px'), '₹1,156.00');
      assert.equal(await text(t.page, '#chg'), '+1% today');
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 4. An API with no stream breaks nothing ──────────────────────────── */
    {
      streamMode = 'json';
      chart = { last: 1010, prev_close: 1000, day_change_pct: 1.0, as_of: '2026-11-23 00:00:00' };
      const before = streamAsks;
      const t = await open(browser, MONDAY);
      await t.page.waitForTimeout(1500);
      assert.equal(streamAsks, before + 1, 'the page did not ask for the stream, or asked again at once');
      assert.equal(await t.page.locator('#px-live').isVisible(), false);
      assert.equal(await text(t.page, '#px'), '₹1,156.00');
      assert.equal(await text(t.page, '#chg'), '+1% today');
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
      streamMode = 'stream';
    }

    console.log('stock live price ok — screenshots in test-results/stock-live-price');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
