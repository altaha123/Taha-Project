/* Today › Sectors right now: a sector tile opens that sector's stocks, in place.
 *
 * This exists because of a bug that shipped. Tapping a tile left Today for
 * the market board and asked the board to open the sector by name. The board
 * names its tiles after NSE indices ("Nifty Realty"), Today names them after
 * sectors ("Real Estate"), so the name never matched: the reader was sent to
 * another page and shown no stocks at all.
 *
 * So this asserts on what the reader gets, at phone and desktop widths:
 *   - the tap stays on Today (same address, same view)
 *   - the sector's own stocks are listed at once, each a link to its page
 *   - the rest of the sector's NSE index is added below them, not merged in
 *   - a sector NSE has no index for, and an NSE read that fails, still list
 *     the stocks that came with the tiles
 *   - a minute's refresh updates the open list instead of closing it
 *   - it closes by the tile, the Close button and Escape, focus back on the tile
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/today-sectors');
fs.mkdirSync(output, { recursive: true });

const indices = [{ label: 'NIFTY 50', level: 25227.95, change_pct: -0.63 }, { label: 'SENSEX', level: 82031, change_pct: -0.6 }];
const rows = [
  { sector: 'Real Estate', icon: 'building', change_pct: 1.57, relative_pp: 2.2, up: 3, down: 1, total: 4, stocks: [
    { symbol: 'DLF', change_pct: 2.9, ltp: 812.4 }, { symbol: 'GODREJPROP', change_pct: 2.1, ltp: 2450 },
    { symbol: 'OBEROIRLTY', change_pct: 1.6, ltp: 1820.55 }, { symbol: 'PRESTIGE', change_pct: -0.32, ltp: 1690 }] },
  { sector: 'Utilities', icon: 'plug', change_pct: -0.91, relative_pp: -0.3, up: 0, down: 2, total: 2, stocks: [
    { symbol: 'NTPC', change_pct: -0.6, ltp: 355 }, { symbol: 'POWERGRID', change_pct: -1.22, ltp: 301.2 }] },
  { sector: 'Technology', icon: 'chip', change_pct: -1.36, relative_pp: -0.7, up: 1, down: 1, total: 2, stocks: [
    { symbol: 'TCS', change_pct: -3.1, ltp: 3400 }, { symbol: 'INFY', change_pct: 0.38, ltp: 1500 }] },
  { sector: 'Basic Materials', icon: 'ingot', change_pct: -2.26, relative_pp: -1.6, up: 0, down: 2, total: 2, stocks: [
    { symbol: 'TATASTEEL', change_pct: -2.4, ltp: 160 }, { symbol: 'HINDALCO', change_pct: -2.12, ltp: 700 }] }
];
const sectors = { rows, source: 'dhan', window: '1D' };
// What NSE publishes for the index: the four carried names and three more.
const realty = { index: 'NIFTY REALTY', window: '1D', stocks: {
  DLF: { change_pct: 2.9, price: 812.4 }, GODREJPROP: { change_pct: 2.1, price: 2450 },
  OBEROIRLTY: { change_pct: 1.6, price: 1820.55 }, PRESTIGE: { change_pct: -0.32, price: 1690 },
  LODHA: { change_pct: 3.4, price: 1310 }, PHOENIXLTD: { change_pct: 0.75, price: 1655.3 }, SOBHA: { change_pct: null, price: 1502 } } };

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
  await new Promise(r => server.listen(8791, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  for (const width of [390, 1280]) {
    const context = await browser.newContext({ viewport: { width, height: 840 }, hasTouch: true, deviceScaleFactor: 2 });
    await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
    const page = await context.newPage(), indexReads = [], opened = [];
    page.on('pageerror', e => errors.push(String(e.stack)));
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') {
        // Opening a stock is a navigation; record it and stay on the page.
        if (u.pathname === '/stock.html') { opened.push(u.searchParams.get('ticker')); return route.fulfill({ status: 204, body: '' }); }
        return route.continue();
      }
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/market') return route.fulfill({ json: { indices, status: 'open' } });
      if (u.pathname === '/sector/overview') return route.fulfill({ json: sectors });
      if (u.pathname === '/index/performance') {
        const index = u.searchParams.get('index');
        indexReads.push(index);
        if (index === 'NIFTY REALTY') return route.fulfill({ json: realty });
        return route.fulfill({ status: 503, json: { detail: 'NSE is not answering' } });   // every other index
      }
      return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
    });

    await page.goto('http://127.0.0.1:8791/', { waitUntil: 'domcontentloaded' });
    const tile = name => page.locator('#drt-heat .dr-tile[data-sector="' + name + '"]');
    const panel = page.locator('#drt-secpanel');
    await tile('Real Estate').waitFor();
    assert.equal(await panel.isVisible(), false, 'no sector is open to begin with');
    assert.equal(await tile('Real Estate').getAttribute('aria-expanded'), 'false');
    const address = page.url();

    // The tap: stocks, here, and nowhere else.
    await tile('Real Estate').tap();
    await panel.locator('.dr-slist a').first().waitFor();
    assert.equal(page.url(), address, `${width}: a sector tap must not leave Today`);
    assert.ok(await page.locator('#view-today').isVisible(), `${width}: Today is still the view on screen`);
    assert.equal(await page.locator('#view-screener').isVisible(), false, `${width}: the market board was opened instead`);
    assert.equal(await tile('Real Estate').getAttribute('aria-expanded'), 'true');
    assert.match(await panel.locator('h3').innerText(), /Real Estate stocks/);
    assert.match(await panel.locator('.dr-secpanel-h p').innerText(), /\+1\.57% today · 3 of 4 up/);

    // The carried names first, best to worst, then the rest of NSE's index.
    await panel.locator('a[href="stock.html?ticker=LODHA"]').waitFor();
    const lists = await panel.locator('.dr-slist').evaluateAll(ls => ls.map(l => [...l.querySelectorAll('.dr-msym')].map(n => n.textContent)));
    assert.deepEqual(lists, [['DLF', 'GODREJPROP', 'OBEROIRLTY', 'PRESTIGE'], ['LODHA', 'PHOENIXLTD', 'SOBHA']],
      `${width}: carried names, then the index members that are not among them`);
    assert.deepEqual(indexReads, ['NIFTY REALTY']);
    const captions = await panel.locator('.dr-secpanel-cap').allInnerTexts();
    assert.match(captions[0], /average of these 4 stocks/);
    assert.match(captions[1], /More in NSE’s Nifty Realty index/);
    assert.match(await panel.locator('a[href="stock.html?ticker=DLF"]').innerText(), /812\.40[\s\S]*\+2\.90%/);
    // No change published is a dash, never 0.00%.
    assert.match(await panel.locator('a[href="stock.html?ticker=SOBHA"]').innerText(), /—/);
    assert.doesNotMatch(await panel.locator('a[href="stock.html?ticker=SOBHA"]').innerText(), /0\.00%/);

    // The list is on screen, clear of the fixed header and the phone's tab bar.
    await page.waitForTimeout(700);
    const seen = await page.evaluate(() => {
      const first = document.querySelector('#drt-secpanel .dr-slist a').getBoundingClientRect();
      const top = document.elementFromPoint(first.left + first.width / 2, first.top + first.height / 2);
      return { inView: first.top >= 0 && first.bottom <= innerHeight, hit: !!top && !!top.closest('#drt-secpanel'),
               overflow: document.documentElement.scrollWidth > innerWidth + 1 };
    });
    assert.deepEqual(seen, { inView: true, hit: true, overflow: false }, `${width}: the first stock is visible and tappable`);
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
      await page.waitForTimeout(250);
      await page.screenshot({ path: path.join(output, `${width}-${theme}-real-estate.png`) });
    }
    await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });

    // A row is a link to the stock.
    await panel.locator('a[href="stock.html?ticker=GODREJPROP"]').tap();
    await page.waitForTimeout(200);
    assert.deepEqual(opened, ['GODREJPROP']);

    // A minute's refresh keeps the sector open and carries the new figures.
    const fresh = { ...sectors, rows: rows.map(r => r.sector !== 'Real Estate' ? r
      : { ...r, change_pct: 1.9, stocks: r.stocks.map(s => s.symbol === 'DLF' ? { ...s, change_pct: 4.2, ltp: 822.9 } : s) }) };
    await page.evaluate(d => window.dispatchEvent(new CustomEvent('altaha:market', { detail: d })), { indices, sectors: fresh });
    assert.ok(await panel.isVisible(), `${width}: a refresh must not close the open sector`);
    assert.match(await panel.locator('a[href="stock.html?ticker=DLF"]').innerText(), /822\.90[\s\S]*\+4\.20%/);
    assert.match(await panel.locator('.dr-secpanel-h p').innerText(), /\+1\.90% today/);
    assert.equal(await tile('Real Estate').getAttribute('aria-expanded'), 'true');
    assert.equal(await panel.locator('a[href="stock.html?ticker=LODHA"]').count(), 1, 'the NSE members survive the refresh');

    // Another sector replaces it. NSE publishes no index for Utilities, so no read is made.
    await tile('Utilities').tap();
    await panel.locator('a[href="stock.html?ticker=NTPC"]').waitFor();
    assert.equal(await tile('Real Estate').getAttribute('aria-expanded'), 'false');
    assert.equal(await tile('Utilities').getAttribute('aria-expanded'), 'true');
    assert.equal(await panel.locator('.dr-slist').count(), 1);
    assert.equal(indexReads.includes('NIFTY POWER') || indexReads.length > 1, false, 'no index read for a sector without one');

    // NSE not answering: the stocks that came with the tiles still stand.
    await tile('Technology').tap();
    await panel.locator('a[href="stock.html?ticker=INFY"]').waitFor();
    await page.waitForFunction(() => !/Reading/.test(document.getElementById('drt-secpanel').textContent));
    assert.deepEqual(await panel.locator('.dr-msym').allInnerTexts(), ['INFY', 'TCS']);
    assert.deepEqual(indexReads, ['NIFTY REALTY', 'NIFTY IT']);

    // Tapping the open tile closes it.
    await tile('Technology').tap();
    assert.equal(await panel.isVisible(), false);
    assert.equal(await tile('Technology').getAttribute('aria-expanded'), 'false');

    // Keyboard: Enter opens and moves to the list; Escape and Close hand focus back.
    await tile('Basic Materials').focus();
    await page.keyboard.press('Enter');
    await panel.locator('a[href="stock.html?ticker=HINDALCO"]').waitFor();
    assert.equal(await page.evaluate(() => document.activeElement.id), 'drt-secpanel');
    assert.equal(await panel.getAttribute('aria-label'), 'Basic Materials stocks');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'drt-secpanel-x');
    await page.keyboard.press('Escape');
    assert.equal(await panel.isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.sector), 'Basic Materials');
    await page.keyboard.press('Enter');
    await panel.locator('#drt-secpanel-x').click();
    assert.equal(await panel.isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.sector), 'Basic Materials');

    // A sector that drops out of the feed closes rather than showing stale stocks.
    await tile('Utilities').tap();
    await panel.locator('a[href="stock.html?ticker=NTPC"]').waitFor();
    await page.evaluate(d => window.dispatchEvent(new CustomEvent('altaha:market', { detail: d })),
      { indices, sectors: { ...sectors, rows: rows.filter(r => r.sector !== 'Utilities') } });
    assert.equal(await panel.isVisible(), false);

    await context.close();
  }

  const relevant = errors.filter(e => /doors\.js|shell\.js|nav\.js/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close(); server.close();
  console.log('Today sector tiles open their stocks in place');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
