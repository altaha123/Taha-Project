/* The Call log, the Watchlists page and the portfolio pulse, in a real browser.

   Each of these fails silently when it breaks — a timeline that renders no
   dates, a rename that does not stick, a share link that opens an empty list,
   a game that never scores — so they are driven end to end here against
   fixture data. The clock is pinned: the game's rules depend on the IST
   session, and a test that passes only before 3:30 pm is not a test.

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/calls-watchlists');
fs.mkdirSync(output, { recursive: true });

const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8'
      : file.endsWith('.webp') ? 'image/webp' : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

/* ── Fixtures ─────────────────────────────────────────────────────────── */

const when = (iso, weekday, day, time) => ({ iso, date: iso.slice(0, 10), weekday, day, time });
const MON = when('2026-10-26T05:10:00+00:00', 'Monday', 'Mon 26 Oct 2026', '10:40 IST');
const TUE = when('2026-10-27T05:10:00+00:00', 'Tuesday', 'Tue 27 Oct 2026', '10:40 IST');
const CALLS = {
  total: 3, method: 'Each call is dated by the scan that first listed it.', latest_scan: '28 Oct 2026, 05:10',
  disclaimer: 'Research, not advice.', recording: false,
  summary: { calls: 3, open: 1, closed: 2, outcomes: { stop: 0, target: 1, dropped: 1 }, this_week: 3,
             priced: 3, in_profit: 2, in_profit_pct: 66.7, median_move_pct: 4.95, first_logged: '2026-10-26' },
  by_day: Array.from({ length: 14 }, (_, i) => {
    const d = new Date(Date.UTC(2026, 9, 16 + i));
    const iso = d.toISOString().slice(0, 10);
    return { date: iso, weekday: d.toUTCString().slice(0, 3), label: d.getUTCDate() + ' Oct',
             calls: iso === '2026-10-26' ? 2 : iso === '2026-10-27' ? 1 : 0 };
  }),
  rows: [
    { id: 3, symbol: 'INFY', name: 'Infosys', sector: 'IT', horizon: 'short', horizon_label: 'Short term',
      setup: 'Pullback', hold: '1–3 weeks', called: TUE, called_price: 1500, called_stance: 'BREAKOUT WATCH',
      stance: 'BUY ZONE', entry: 1500, stop: 1440, target: 1620, rr: 2, status: 'closed', outcome: 'target',
      closed: when('2026-10-28T05:10:00+00:00', 'Wednesday', 'Wed 28 Oct 2026', '10:40 IST'),
      price_now: 1625, move_pct: 8.33, days: 1, scans_seen: 2,
      events: [{ at: TUE, kind: 'called', stance: 'BREAKOUT WATCH', price: 1500, note: 'BREAKOUT WATCH' },
               { at: TUE, kind: 'stance', stance: 'BUY ZONE', price: 1510, note: 'BREAKOUT WATCH → BUY ZONE' },
               { at: TUE, kind: 'target', stance: 'BUY ZONE', price: 1625, note: 'Scan price at or above the target.' }] },
    { id: 1, symbol: 'ABB', name: 'ABB India', sector: 'Capital Goods', horizon: 'short', horizon_label: 'Short term',
      setup: 'Momentum breakout', hold: '2–6 weeks', called: MON, called_price: 101, called_stance: 'BUY ZONE',
      stance: 'BUY ZONE', entry: 100, stop: 92, target: 118, rr: 2.1, status: 'open', outcome: null, closed: null,
      price_now: 106, move_pct: 4.95, days: 3, scans_seen: 3,
      events: [{ at: MON, kind: 'called', stance: 'BUY ZONE', price: 101, note: 'BUY ZONE · buy near ₹100.00 · stop ₹92.00 · target ₹118.00' }] },
    { id: 2, symbol: 'TCS', name: 'Tata Consultancy', sector: 'IT', horizon: 'medium', horizon_label: 'Medium term',
      setup: 'Quality compounder', hold: '3–9 months', called: MON, called_price: 3200, called_stance: 'WAIT',
      stance: 'WAIT', status: 'closed', outcome: 'dropped', closed: TUE, price_now: 3150, move_pct: -1.56, days: 1, scans_seen: 1,
      events: [{ at: MON, kind: 'called', stance: 'WAIT', price: 3200, note: 'WAIT' },
               { at: TUE, kind: 'dropped', stance: 'WAIT', price: 3150, note: 'No longer on the list in this scan.' }] }
  ]
};

// Thirty sessions of closes ending 29 Oct, the last move set per symbol so the
// game has a known winner: TCS tops the list on the 29th.
const LAST_MOVE = { TCS: 2.4, INFY: -0.8, ABB: 1.1, RELIANCE: 0.3, TATAMOTORS: -1.6, HDFCBANK: 0.6, ICICIBANK: -0.2 };
function sessions(n, end) {
  const out = [], d = new Date(end + 'T00:00:00Z');
  while (out.length < n) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.unshift(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}
function quote(sym) {
  const seed = [...sym].reduce((a, c) => a + c.charCodeAt(0), 0);
  const last = LAST_MOVE[sym] != null ? LAST_MOVE[sym] : ((seed % 7) - 3) / 2;
  const dates = sessions(30, '2026-10-29');
  const spark = [];
  let px = 500 + (seed % 40) * 37;
  for (let i = 0; i < 30; i++) { px *= 1 + Math.sin(seed + i) / 100; spark.push(Math.round(px * 100) / 100); }
  spark[29] = Math.round(spark[28] * (1 + last / 100) * 100) / 100;
  return { symbol: sym, ltp: spark[29], prev_close: spark[28], change_pct: last,
           week_pct: Math.round((spark[29] / spark[24] - 1) * 1e4) / 100,
           month_pct: Math.round((spark[29] / spark[8] - 1) * 1e4) / 100,
           spark, spark_dates: dates, last_date: dates[29], source: 'fixture',
           name: sym === 'TCS' ? 'Tata Consultancy Services' : sym.charAt(0) + sym.slice(1).toLowerCase(),
           score: 40 + seed % 50, label: 'Moderate' };
}
const UNIVERSE = [['RELIANCE', 'Reliance Industries'], ['TATAMOTORS', 'Tata Motors'], ['TATASTEEL', 'Tata Steel'],
  ['TCS', 'Tata Consultancy Services'], ['INFY', 'Infosys'], ['HDFCBANK', 'HDFC Bank'], ['ICICIBANK', 'ICICI Bank'], ['ABB', 'ABB India']]
  .map(([s, n]) => ({ s, n, x: 'NSE' }));
const FEATURED = { lists: [
  { id: 'f-calls', name: 'Altaha open calls', emoji: '📣', color: 'gold', blurb: 'Every name the Ideas list is calling right now.', symbols: ['ABB'] },
  { id: 'f-giants', name: 'Nifty giants', emoji: '🐘', color: 'blue', blurb: 'The heaviest names.', symbols: ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'TCS', 'INFY'] }] };

const PULSE_REPORT = {
  holdings: [{ symbol: 'ABB', weight_pct: 60, pnl: 1200, value: 6000 }, { symbol: 'TCS', weight_pct: 40, pnl: -300, value: 4000 }],
  total_value: 10000, sectors: [{ sector: 'Capital Goods', weight_pct: 60 }],
  data_quality: { valuation_complete: true, cost_value_pct: 100, scored_value_pct: 100 }, policy: { max_stock_pct: 20, max_sector_pct: 40 },
  pulse: { winners: ['ABB'], losers: ['TCS'], no_cost: [], today: { up: 1, down: 1, best: 'ABB', worst: 'TCS' },
    leans: { positive: ['ABB'], negative: ['TCS'], mixed: [], quiet: [] }, method: 'Lean = filings read by category.',
    disclaimer: 'A tally of evidence, not a forecast.',
    holdings: {
      ABB: { symbol: 'ABB', name: 'ABB India', pnl_pct: 25, pnl: 1200, day_change_pct: 1.1, lean: 'positive', lean_label: 'Leaning positive', points: 3.5,
             reasons: [{ sign: 1, points: 2.5, kind: 'filing', text: 'ABB wins ₹900 cr order', url: 'https://nseindia.com/a.pdf', why: 'Order win filed — counts for the stock.', source: 'NSE filing', at: '2026-10-28T09:00:00Z' },
                       { sign: 1, points: 1, kind: 'score', text: 'Altaha Score 74/100', why: 'A strong score counts a little for it.' }] },
      TCS: { symbol: 'TCS', name: 'Tata Consultancy', pnl_pct: -7, pnl: -300, day_change_pct: -0.8, lean: 'negative', lean_label: 'Leaning negative', points: -1.5,
             reasons: [{ sign: -1, points: -1, kind: 'score', text: 'Altaha Score 38/100', why: 'A weak score counts a little against it.' },
                       { sign: -1, points: -0.5, kind: 'trend', text: '4.2% below its 200-day average', why: 'The long trend counts half a point.' }] } } } };

/* ── The run ──────────────────────────────────────────────────────────── */

(async () => {
  await new Promise(resolve => server.listen(8769, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:8769' });
  await context.addInitScript(() => {
    localStorage.setItem('altaha-guide-dismissed', '1');
    if (!localStorage.getItem('altaha-watchlist-v1'))
      localStorage.setItem('altaha-watchlist-v1', JSON.stringify(['TCS', 'INFY', 'ABB', 'RELIANCE']));
  });
  const errors = [], quoted = [];

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/calls') return route.fulfill({ json: CALLS });
    if (u.pathname === '/watchlist/featured') return route.fulfill({ json: FEATURED });
    if (u.pathname === '/universe') return route.fulfill({ json: { rows: UNIVERSE, count: UNIVERSE.length } });
    if (u.pathname === '/watchlist/quotes') {
      const syms = (u.searchParams.get('symbols') || '').split(',').filter(Boolean);
      quoted.push(...syms);
      return route.fulfill({ json: { rows: syms.map(quote), pending: [], market_open: false, note: 'Fixture prices.' } });
    }
    if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
    return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [], items: [],
                                   sectors: [], rankings: [], status: 'idle' } });
  });

  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  const base = 'http://127.0.0.1:8769/';
  const ours = () => errors.filter(e => /calls\.js|watchlists\.js|portfolio-intelligence\.js/.test(e));

  // Thursday 29 Oct 2026, 10:30 IST — the market is open and picks are allowed.
  await page.clock.setFixedTime(new Date('2026-10-29T05:00:00Z'));

  /* ── 1 · The call log ─────────────────────────────────────────────── */

  await page.goto(base + '#research/calls', { waitUntil: 'domcontentloaded' });
  await page.locator('#view-calls .cl-call').first().waitFor();
  assert.equal(await page.locator('#view-calls .cl-call').count(), 3);
  const days = await page.locator('.cl-day h3').allInnerTexts();
  assert.deepEqual(days, ['Tuesday', 'Monday'], 'calls are grouped under the day they were made');
  assert.ok((await page.locator('.cl-call').first().innerText()).includes('10:40 IST'));
  assert.ok((await page.locator('.cl-stats').innerText()).includes('66.7% of priced calls'));
  await page.locator('#cl-st button[data-v="open"]').click();
  assert.equal(await page.locator('.cl-call').count(), 1);
  assert.ok((await page.locator('.cl-call').innerText()).includes('ABB'));
  await page.locator('#cl-st button[data-v="all"]').click();
  await page.locator('.cl-call:has-text("INFY") .cl-more').click();
  await page.locator('.cl-call.open .cl-tl li').nth(2).waitFor();
  assert.ok((await page.locator('.cl-call.open .cl-tl').innerText()).includes('BREAKOUT WATCH → BUY ZONE'));
  await page.locator('.cl-bar[data-day="2026-10-26"]').click();
  assert.equal(await page.locator('.cl-call').count(), 2, 'tapping a day filters to it');
  await page.locator('#cl-filter button').click();
  await page.locator('#cl-q').fill('tcs');
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.cl-call').count(), 1);
  await page.locator('#cl-q').fill('');
  await page.waitForTimeout(250);
  await page.waitForTimeout(1200);           // let the rise-in animations settle
  await page.screenshot({ path: path.join(output, 'call-log-desktop.png'), fullPage: true });

  // The stamp on an Ideas row opens that stock's calls.
  const stampHtml = await page.evaluate(() => window.AltahaCalls.stamp(
    { called: { date: '2026-10-26', day: 'Mon 26 Oct 2026', time: '10:40 IST' }, called_price: 101, move_pct: 4.95 }, 'ABB'));
  assert.ok(stampHtml.includes('Called <b>Mon 26 Oct</b>') && stampHtml.includes('+4.95%'));

  /* ── 2 · Watchlists ───────────────────────────────────────────────── */

  await page.goto(base + '?go=watchlists', { waitUntil: 'domcontentloaded' });
  await page.locator('#view-watchlists .wl-card').nth(3).waitFor();
  assert.equal(await page.locator('.wl-card').count(), 4, 'the main list is the star list');
  assert.ok((await page.locator('.wl-card').first().innerText()).includes('₹'));
  // Sorted by today's move: TCS (+2.4%) leads.
  assert.equal((await page.locator('.wl-card .wl-card-sym').first().innerText()).trim(), 'TCS');
  await page.waitForTimeout(1400);
  await page.screenshot({ path: path.join(output, 'watchlists-desktop.png'), fullPage: true });

  // Rename the main list.
  await page.locator('[data-act="rename"]').click();
  await page.locator('#wl-name-in').fill('Core holdings');
  await page.locator('#wl-name-in').press('Enter');
  assert.equal((await page.locator('.wl-name').innerText()).trim(), 'Core holdings');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-watchlists-v2')).main.name), 'Core holdings');

  // A new list, named on the spot, with a stock added from the search box.
  await page.locator('#wl-new').click();
  await page.locator('#wl-name-in').fill('EV bets');
  await page.locator('#wl-name-in').press('Enter');
  assert.equal((await page.locator('.wl-name').innerText()).trim(), 'EV bets');
  await page.locator('#wl-add-in').fill('tata mo');
  await page.locator('#wl-sugg li[data-add="TATAMOTORS"]').waitFor();
  await page.locator('#wl-add-in').press('Enter');
  await page.locator('.wl-card[data-sym="TATAMOTORS"]').waitFor();
  await page.locator('#wl-add-in').fill('reliance');
  await page.locator('#wl-sugg li[data-add="RELIANCE"]').click();
  await page.locator('.wl-card[data-sym="RELIANCE"]').waitFor();
  await page.locator('#wl-add-in').fill('INFY');
  await page.locator('#wl-sugg li').first().waitFor();
  await page.locator('#wl-add-in').press('Enter');
  await page.locator('.wl-card[data-sym="INFY"]').waitFor();
  const doc = await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-watchlists-v2')));
  assert.deepEqual(doc.lists[0].symbols, ['TATAMOTORS', 'RELIANCE', 'INFY']);
  assert.ok(doc.lists[0].added.TATAMOTORS.at === '2026-10-29');

  // Emoji and colour.
  await page.locator('[data-act="style"]').click();
  await page.locator('[data-emoji="⚡"]').click();
  await page.locator('[data-color="green"]').click();
  assert.ok(await page.locator('.wl-hero.c-green').isVisible());
  assert.equal((await page.locator('.wl-tile.on .wl-tile-e').innerText()).trim(), '⚡');

  // Race and heatmap.
  await page.locator('#wl-mode button[data-v="race"]').click();
  await page.locator('.wl-lane').nth(2).waitFor();
  assert.ok((await page.locator('.wl-race-cap').innerText()).includes('RELIANCE'), 'the race names its leader');
  await page.waitForTimeout(1400);
  await page.locator('.wl-race').screenshot({ path: path.join(output, 'watchlists-race.png') });
  await page.locator('#wl-mode button[data-v="heat"]').click();
  assert.equal(await page.locator('.wl-hcell').count(), 3);
  await page.locator('#wl-mode button[data-v="cards"]').click();

  // Remove a stock, then share the list and open the link elsewhere.
  await page.locator('.wl-card[data-sym="INFY"] .wl-x').click();
  assert.equal(await page.locator('.wl-card').count(), 2);
  await page.locator('[data-act="share"]').click();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  assert.match(link, /\?go=watchlists&wl=/);

  const other = await context.newPage();
  other.on('pageerror', e => errors.push(String(e.stack || e)));
  await other.clock.setFixedTime(new Date('2026-10-29T05:00:00Z'));
  await other.evaluate(() => 0).catch(() => {});
  await other.goto(link, { waitUntil: 'domcontentloaded' });
  await other.locator('.wl-tile[data-list="shared"]').waitFor();
  assert.equal((await other.locator('.wl-name').innerText()).trim(), 'EV bets');
  assert.equal(await other.locator('.wl-card').count(), 2);
  const before = await other.evaluate(() => window.AltahaWatchlists.lists().length);
  await other.locator('[data-act="follow"]').click();
  assert.equal(await other.evaluate(() => window.AltahaWatchlists.lists().length), before + 1);
  assert.equal(await other.locator('.wl-tile[data-list="shared"]').count(), 0, 'a kept list is no longer shown as shared');
  await other.close();

  // A featured list is read-only and can be kept.
  await page.locator('.wl-tile[data-list="f-giants"]').click();
  await page.locator('.wl-card').nth(4).waitFor();
  assert.equal(await page.locator('[data-act="rename"]').count(), 0);
  assert.equal(await page.locator('.wl-x').count(), 0);

  // The copy kept in the other tab is in this one too: same browser, same
  // storage. Delete the original, which needs two taps.
  const ev = '.wl-tile[data-list="' + doc.lists[0].id + '"]';
  assert.equal(await page.locator('.wl-tile:has-text("EV bets")').count(), 2);
  await page.locator(ev).click();
  await page.locator('[data-act="delete"]').click();
  assert.equal(await page.locator(ev).count(), 1);
  await page.locator('[data-act="delete"]').click();
  assert.equal(await page.locator(ev).count(), 0);
  assert.equal(await page.locator('.wl-tile:has-text("EV bets")').count(), 1);

  /* ── 3 · The game: pick before the close, scored after it ─────────── */

  await page.locator('.wl-tile[data-list="main"]').click();
  await page.locator('.wl-card[data-sym="TCS"] [data-pick]').click();
  await page.locator('.wl-card.picked[data-sym="TCS"]').waitFor();
  assert.equal(await page.locator('[data-pick]').count(), 0, 'one pick a day');

  // 4:30 pm IST the same day.
  await page.clock.setFixedTime(new Date('2026-10-29T11:00:00Z'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.wl-game-result.win').waitFor();
  assert.ok((await page.locator('.wl-game-result').innerText()).includes('TCS won the day'));
  const g = await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-watchgame-v1')));
  assert.equal(g.points, 3);
  assert.equal(g.streak, 1);
  await page.screenshot({ path: path.join(output, 'watchlists-game.png'), fullPage: true });

  /* ── 4 · The portfolio pulse renders ──────────────────────────────── */

  await page.evaluate(report => {
    const host = document.createElement('div');
    host.id = 'pulse-host';
    host.innerHTML = window.PortfolioIntelligence.build(report);
    document.body.prepend(host);
  }, PULSE_REPORT);
  await page.locator('#pi-pulse').waitFor();
  await page.locator('#pi-pulse .pi-pulse-row').first().click();
  assert.ok((await page.locator('#pi-pulse').innerText()).includes('ABB wins ₹900 cr order'));
  await page.locator('#pi-pulse').screenshot({ path: path.join(output, 'portfolio-pulse.png') });

  /* ── 5 · A phone ──────────────────────────────────────────────────── */

  await page.setViewportSize({ width: 390, height: 850 });
  await page.goto(base + '?go=watchlists', { waitUntil: 'domcontentloaded' });
  await page.locator('.wl-card').first().waitFor();
  const overflowW = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(overflowW <= 391, 'watchlists overflow a 390px screen: ' + overflowW);
  await page.screenshot({ path: path.join(output, 'watchlists-phone.png'), fullPage: true });
  await page.goto(base + '#research/calls', { waitUntil: 'domcontentloaded' });
  await page.locator('.cl-call').first().waitFor();
  const overflowC = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(overflowC <= 391, 'call log overflows a 390px screen: ' + overflowC);
  await page.screenshot({ path: path.join(output, 'call-log-phone.png'), fullPage: true });

  assert.deepEqual(ours(), [], 'errors thrown by the new pages:\n' + ours().join('\n'));
  await browser.close();
  server.close();
  console.log('call log, watchlists, game and portfolio pulse ok — screenshots in test-results/calls-watchlists');
})().catch(async e => {
  console.error(e);
  server.close();
  process.exit(1);
});
