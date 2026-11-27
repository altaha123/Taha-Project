/* The stock picks, in a real browser.

   Colleagues who were sent the site said two things: it is too complex, and
   there is too much writing. Both were truest of Ideas, which answered "what
   should I look at?" with a picture of a planet. So what this pins is mostly
   about the first screen, and none of it throws when it breaks:

     · the Ideas door shows picks on the first screen, above the scan. Three
       lists by holding time (Swing / This month, After results, Long term)
       share one row equally, five by chart setup sit under them, and a
       first visit opens on Swing / This month
     · a choice or a link from before the lists changed (this week,
       momentum, trade, position) opens the list that replaced it, and
       storage that throws costs nothing but the memory of the choice
     · a list rebuilt since the study last ran says its record is being
       measured, and prints no record (and no tally of live calls) of the
       list it replaced; once measured, the study's own numbers are shown
     · a pick shows at most four facts, a hold and an exit price; Details
       has the company's figures and the ledger, every part in plain words,
       adding up to the score
     · the chosen tab is remembered, and "See all" opens the same list
     · a scan from before the lists still draws, the old way, and says so
     · an unreachable API says so and offers a retry
     · the results list says what it is ranked on, shows the result each pick
       was priced on, and says when it fills in between results seasons
     · on a 390px phone the three tabs keep their thirds, every tab fits and
       nothing scrolls sideways
     · the new words describe, never advise: no buy, sell, should or
       recommend in the tabs, the facts, the figures or the ledger

   /ideas is fulfilled from fixtures/picks.json: the real engine's answer
   (leaders.rank, ideas.select) on the study's price panel and the companies'
   filings as they stood that day (backend/tests/make_picks_fixture.py),
   trimmed to the fields the page reads. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/picks');
fs.mkdirSync(output, { recursive: true });
const FIX = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/picks.json'), 'utf8'));
/* A live catalyst on the first breakout pick, as ideas.catalysts() writes one.
   The fixture is made from the price panel, which has no orders or calls. */
const CATALYST = 'Order worth ₹420 crore, 6.1% of its market value, disclosed 2026-11-20';
FIX.breakout.rows[0].catalysts = { lines: [CATALYST], score: 2.2 };
/* The live-only facts (pledges, the industry's Money Flow quadrant) have no
   history, so the fixture has none; one pick carries them here. */
Object.assign(FIX.long.rows[0].leader.fundamentals, { pledge_pct: 0, sector_mf_quadrant: 'Leading' });
/* How the list's own calls have done (main.py, _live_record). */
const LIVE = { calls: 12, closed: 8, closed_up: 5, closed_avg_pct: 2.4, open: 4, open_up: 3, since: '2026-11-09' };
/* A record in the study's shape, for a list once the study has measured it. */
const STUDIED = {
  list_dates: 410, picks: 6150, up_pct: 56.2, avg_pct: 2.31, median_pct: 1.4, index_avg_pct: 1.05, worst_5pct: -14.8,
  avg_after_costs_pct: 1.82, from: '2018-06-01',
  by_half: { '2018-21': { up_pct: 55.1, avg_pct: 2.2, index_avg_pct: 1.2 }, '2022-26': { up_pct: 57.3, avg_pct: 2.4, index_avg_pct: 0.9 } }
};
const TARGET = { target_pct: 12, sold: { up_pct: 58.4, avg_pct: 1.92 }, held: { up_pct: 56.2, avg_pct: 2.31 } };
const HOLD = ['month', 'results', 'long'];
const HOLD_LABELS = ['Swing / This month', 'After results', 'Long term'];
const SETUP_LABELS = ['Breakouts', 'Technicals', 'Swing dips', 'Money flow', 'Emerging'];
const CHIPS = ['~ 2–4 weeks', '~ 1 month', '~ 1 year'];
/* Advice words the new copy never uses. */
const ADVICE = /\b(buy|sell|should|recommend)/i;
const PORT = 8793;

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

/* mode: 'picks' (the lists, as the fixture has them), 'measuring' (the three
   lists before the study has measured them), 'studied' (the three lists once
   it has), 'legacy' (a scan from before the lists), 'oldrecipe' (the lists,
   ranked before a recipe changed), 'down' (the API does not answer),
   'offseason' (nobody has reported lately), 'weak' (the index is under its
   200-day average). */
async function open(browser, size, mode) {
  const context = await browser.newContext({ viewport: size, hasTouch: size.width < 600 });
  // about:blank, between two loads, has no storage of its own.
  await context.addInitScript(() => { try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (e) {} });
  const state = { mode, asked: [], errors: [] };
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    const cors = { 'access-control-allow-origin': '*' };
    if (u.pathname === '/ideas') {
      const h = u.searchParams.get('horizon');
      state.asked.push(h);
      const fix = FIX[h] || FIX.month;
      if (state.mode === 'down') return route.abort();
      if (state.mode === 'legacy') return route.fulfill({ json: FIX.legacy, headers: cors });
      if (state.mode === 'oldrecipe') {
        return route.fulfill({ json: { ...fix, tested: null, target_test: null, recipe_current: false },
                               headers: cors });
      }
      if (state.mode === 'offseason' && h === 'results') {
        return route.fulfill({ json: FIX.results_empty, headers: cors });
      }
      if (state.mode === 'weak') {
        return route.fulfill({ json: { ...fix, regime: { ok: false, label: 'Index below its 50-day average — trend setups fail more often here.' },
          market_test: { state: 'below_200d', text: 'The index is under its 200-day average. In the test, picks made on days like this averaged +9.2% (64 in 100 rose), against +4.4% on the other days. The list is not held back in either.' } },
                               headers: cors });
      }
      if (state.mode === 'measuring' && HOLD.includes(h)) {
        return route.fulfill({ json: { ...fix, study_current: false, tested: null, target_test: null, market_test: null,
                                       live: h === 'month' ? LIVE : null }, headers: cors });
      }
      if (state.mode === 'studied' && HOLD.includes(h)) {
        return route.fulfill({ json: { ...fix, study_current: true, tested: STUDIED, target_test: TARGET,
                                       live: h === 'month' ? LIVE : null }, headers: cors });
      }
      // The month list's calls so far, as the server tallies them: made by
      // the list it replaced while the new one is being measured.
      return route.fulfill({ json: h === 'month' ? { ...fix, live: LIVE } : fix, headers: cors });
    }
    if (u.pathname === '/scan/status') {
      return route.fulfill({ json: { status: 'done', done: 100, total: 100, scored: 200 }, headers: cors });
    }
    return route.fulfill({ json: {}, headers: cors });
  });
  const page = await context.newPage();
  page.on('pageerror', e => state.errors.push(String(e.stack || e)));
  return { context, page, state };
}

const url = hash => `http://127.0.0.1:${PORT}/index.html${hash}`;
const rupees = s => Number(String(s).replace(/[^0-9.]/g, ''));
const pct = v => Math.round(Number(v)) + '%';
const boxes = (loc) => loc.evaluateAll(ns => ns.map(n => {
  const b = n.getBoundingClientRect(); return { left: b.left, right: b.right, top: b.top, w: b.width, h: b.height };
}));
const stored = page => page.evaluate(() => localStorage.getItem('altaha-pick-list'));

/* The three tabs by holding time: one row, three equal thirds. */
function thirds(tabs, where) {
  assert.equal(tabs.length, 3, `${where}: the holding row has ${tabs.length} tabs, not three`);
  tabs.forEach((t, i) => {
    assert.ok(Math.abs(t.top - tabs[0].top) < 1, `${where}: tab ${i + 1} is not on the row`);
    assert.ok(Math.abs(t.w - tabs[0].w) < 1.5, `${where}: tab ${i + 1} is ${Math.round(t.w)}px wide, not ${Math.round(tabs[0].w)}`);
  });
  assert.ok(tabs[1].left > tabs[0].right - 1 && tabs[2].left > tabs[1].right - 1, `${where}: the tabs overlap`);
}

/* Every pick on a list by holding time: its facts, its prices, its words. */
async function checkCards(panel, key) {
  const fix = FIX[key];
  const shown = v => (Math.round(v * 100) / 100 >= 1000 ? Math.round(v) : v);
  const n = Math.min(5, fix.rows.length);
  assert.equal(await panel.locator('.pk-card').count(), n, `${key}: the door shows the top five`);
  for (let i = 0; i < n; i++) {
    const card = panel.locator('.pk-card').nth(i), row = fix.rows[i];
    assert.equal(await card.getAttribute('data-t'), row.symbol, `${key}: the door reordered the list`);
    const facts = await card.locator('.pk-why span').allInnerTexts();
    assert.ok(facts.length >= 1 && facts.length <= 4, `${row.symbol} shows ${facts.length} facts`);
    assert.deepEqual(facts, row.why.slice(0, 4), `${row.symbol}: the facts are not the server's`);
    facts.forEach(f => assert.doesNotMatch(f, ADVICE, `${row.symbol}: a fact gives advice: ${f}`));
    assert.deepEqual(await card.locator('.pk-lv small').allInnerTexts(), ['Price', 'Target', 'Exit below']);
    assert.equal(rupees(await card.locator('.pk-lv b').first().innerText()), shown(row.price), `${row.symbol} shows the wrong price`);
    assert.equal(rupees(await card.locator('.pk-aim b').innerText()), shown(row.plan.aim), `${row.symbol} shows the wrong target`);
    assert.equal((await card.locator('.pk-aim i').innerText()).trim(), '+' + pct(row.plan.aim_pct));
    assert.equal(rupees(await card.locator('.pk-exit b').innerText()), shown(row.plan.stop), `${row.symbol} shows the wrong exit price`);
    assert.equal((await card.locator('.pk-exit i').innerText()).trim(), '−' + pct(row.plan.risk_pct));
    assert.ok(row.plan.aim > row.price && row.price > row.plan.stop);
  }
}

(async () => {
  await new Promise(resolve => server.listen(PORT, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  /* ── 1 · The Ideas door answers its own question ──────────────────────── */

  let { context, page, state } = await open(browser, { width: 1280, height: 900 }, 'picks');
  await page.goto(url('#research'));
  const panel = page.locator('#view-ideahub #dri-picks');
  await panel.locator('.pk-card').first().waitFor({ state: 'visible' });

  assert.deepEqual(await panel.locator('.pk-tab').evaluateAll(ns => ns.map(n => n.getAttribute('aria-label'))),
                   HOLD_LABELS.concat(SETUP_LABELS));
  const holdRow = panel.locator('.pk-tabs.hold .pk-tab');
  assert.deepEqual(await holdRow.evaluateAll(ns => ns.map(n => n.dataset.pick)), HOLD, 'the holding row is not the three lists');
  assert.deepEqual((await holdRow.locator('small').allInnerTexts()).map(t => t.trim()), CHIPS);
  thirds(await boxes(holdRow), 'door');
  assert.equal(await panel.locator('.pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'month',
               'a first visit should open on Swing / This month');
  assert.deepEqual((await panel.locator('.pk-group-h').allInnerTexts()).map(t => t.trim().toLowerCase()), ['by holding time', 'by chart setup']);

  // Picks before the scan, and on the first screen.
  const firstCard = await panel.locator('.pk-card').first().boundingBox();
  const scan = await page.locator('#view-ideahub .dr-universe').boundingBox();
  assert.ok(firstCard.y < 900, `the first pick is ${Math.round(firstCard.y)}px down: not on the first screen`);
  assert.ok(firstCard.y < scan.y, 'the scan is drawn above the picks again');

  // What the list is, in one line, and where its record stands.
  const month = FIX.month;
  assert.match(await panel.locator('.pk-idea').innerText(), /Hold about a month/);
  if (month.study_current === false) {
    // Rebuilt since the study ran: no record, no tally of the replaced
    // list's calls, and a plain line saying the record is being measured.
    assert.equal(await panel.locator('.pk-record').count(), 0, 'the replaced list’s record is printed beside the new one');
    assert.equal(await panel.locator('.pk-live').count(), 0, 'the replaced list’s live calls are printed beside the new one');
    const measuring = await panel.locator('.pk-measuring').innerText();
    assert.match(measuring, /being measured/);
    assert.doesNotMatch(measuring, ADVICE);
  } else {
    const record = (await panel.locator('.pk-record-n b').allInnerTexts()).map(t => t.trim());
    assert.equal(record.length, 3, 'a list by holding time shows three figures');
    assert.equal(record[0], String(Math.round(month.tested.up_pct)), 'the "rose" figure is not the study’s');
    assert.equal(record[1], (month.tested.avg_pct >= 0 ? '+' : '\u2212') + Math.abs(month.tested.avg_pct).toFixed(1) + '%',
                 'the average is not the study’s');
    assert.equal(await panel.locator('.pk-measuring').count(), 0);
    assert.match(await panel.locator('.pk-live').innerText(), /5 of 8 closed calls rose/);
  }
  await checkCards(panel, 'month');
  // The target is a mark and says so. A list not measured yet says nothing
  // about what its test found.
  const aim = await panel.locator('.pk-aimnote').innerText();
  assert.match(aim, new RegExp(Math.round(month.exit_pct) + '% above the price'));
  assert.match(aim, /not an order to sell/);
  if (month.study_current === false) assert.doesNotMatch(aim, /In the test|was tested/, 'the target note quotes a test the list has not had');
  // "See all" can be read: it was ink on ink, a black pill with nothing on it.
  const seeAll = await panel.locator('.pk-all').evaluate(n => { const c = getComputedStyle(n); return [c.color, c.backgroundColor]; });
  assert.notEqual(seeAll[0], seeAll[1], 'the "See all" button is the same colour as its own text');
  const doorText = await panel.innerText();
  assert.doesNotMatch(doorText, /\bWAIT\b|R:R|Stop loss|BUY RANGE/i, 'the old trade plan is back on the door');
  assert.doesNotMatch(doorText, /This week|Momentum/, 'a replaced list is still named on the door');
  await page.screenshot({ path: path.join(output, 'door-desktop.png') });

  /* ── 2 · Tabs switch the list, and the choice is remembered ───────────── */

  await panel.locator('.pk-tab[data-pick="results"]').click();
  await panel.locator(`.pk-card[data-t="${FIX.results.rows[0].symbol}"]`).waitFor();
  await checkCards(panel, 'results');
  assert.equal(await stored(page), 'results');

  await panel.locator('.pk-tab[data-pick="long"]').click();
  await panel.locator(`.pk-card[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  assert.match(await panel.locator('.pk-idea').innerText(), /Hold about a year/);
  await checkCards(panel, 'long');
  assert.equal(await panel.locator('.pk-live').count(), 0, 'no live line until five calls have closed');
  assert.ok(state.asked.includes('long'));
  assert.equal(await stored(page), 'long');

  /* ── 3 · "See all" opens the same list, stocks first ──────────────────── */

  await panel.locator('.pk-all').click();
  await page.locator('#view-ideas').waitFor({ state: 'visible' });
  await page.locator('#idearows .idea').first().waitFor();
  assert.match(page.url(), /#research\/ideas$/);
  assert.equal(await page.locator('#hzseg .hz.on').getAttribute('data-h'), 'long', 'the full list opened on another tab');
  // The tab here is the door's: the same lists, names and chips.
  const pageTabs = await page.locator('#hzseg .hz').evaluateAll(ns => ns.map(n => [n.dataset.h, n.getAttribute('aria-label'), n.querySelector('small').textContent]));
  assert.deepEqual(pageTabs, HOLD.map((k, i) => [k, HOLD_LABELS[i], CHIPS[i]]), 'the page’s tabs and the door’s have drifted apart');
  thirds(await boxes(page.locator('#hzseg .hz')), 'page');
  const long = FIX.long;
  assert.equal(await page.locator('#idearows .idea').count(), long.rows.length);
  assert.deepEqual(await page.locator('#idearows .idea').evaluateAll(ns => ns.map(n => n.dataset.t)),
                   long.rows.map(r => r.symbol), 'the page reordered the server’s list');
  assert.doesNotMatch(await page.locator('#view-ideas .tabhead').innerText(), ADVICE);

  const firstRow = await page.locator('#idearows .idea').first().boundingBox();
  const hero = await page.locator('#scan-universe').boundingBox();
  assert.ok(firstRow.y < hero.y, 'the scan is above the list again');
  assert.ok(firstRow.y < 900, `the first stock is ${Math.round(firstRow.y)}px down: not on the first screen`);

  const rows = page.locator('#idearows .idea');
  const exit = Math.round(long.exit_pct);
  for (let i = 0; i < long.rows.length; i++) {
    const r = rows.nth(i);
    const facts = await r.locator('.pk-why span').count();
    assert.ok(facts >= 1 && facts <= 4, `row ${i + 1} shows ${facts} facts`);
    const plan = await r.locator('.pk-plan').innerText();
    assert.match(plan, /Hold\s+about a year/); assert.match(plan, /Exit below\s+₹/); assert.match(plan, new RegExp('−' + exit + '%'));
    assert.match(plan, new RegExp('Target\\s+₹[\\d,.]+\\s*\\+' + exit + '%'), `row ${i + 1} gives no target`);
    assert.equal(await r.locator('.ideaplan2').count(), 0, 'a tested pick is showing the old plan grid');
  }
  assert.doesNotMatch(await page.locator('#idearows').innerText(), /\bWAIT\b|BUY RANGE|R:R/i);
  // What the target is is said once under the list.
  const pageAim = await page.locator('#pickaim .pk-aimnote').innerText();
  assert.match(pageAim, new RegExp(exit + '% above the price[\\s\\S]*not an order to sell'));
  if (long.study_current === false) {
    assert.doesNotMatch(pageAim, /In the test|was tested/);
    assert.equal(await page.locator('#pickhead .pk-record').count(), 0);
    assert.match(await page.locator('#pickhead .pk-measuring').innerText(), /being measured/);
  }
  assert.match(await page.locator('#pickhead').innerText(), /stocks compared/);
  // The reasons a name was left out are kept, folded.
  const notes = (long.selection_notes || []).length;
  if (notes) assert.match(await page.locator('#pickhead .pk-notes summary').innerText(), new RegExp(`${notes} notes? on this list`));
  else assert.equal(await page.locator('#pickhead .pk-notes').count(), 0);
  // No filter dialog and no thin-stock switch for fifteen rows.
  assert.equal(await page.locator('#view-ideas .ux-filterbar').isVisible(), false);
  assert.equal(await page.locator('#thintoggle').isVisible(), false);

  // Details: the company's figures, then the ledger behind the score.
  const top = long.rows[0], f = top.leader.fundamentals;
  await rows.first().locator('.morebtn').click();
  const funds = rows.first().locator('.pk-funds');
  await funds.waitFor({ state: 'visible' });
  const dt = (await funds.locator('dt').allInnerTexts()).map(t => t.trim());
  const dd = (await funds.locator('dd').allInnerTexts()).map(t => t.trim());
  assert.ok(dt[0].startsWith('Last quarter') && dt[0].includes(f.quarter), `the figures start with ${dt[0]}`);
  assert.ok(dd[0].includes('+' + Math.round(f.revenue_yoy_pct) + '%'), `the quarter reads ${dd[0]}`);
  assert.equal(dt.includes('Cash') || dt.includes('Debt'), !f.is_financial,
               'a lender is shown cash flow and debt, or a company is not');
  assert.equal(dd[dt.indexOf('Pledged')], 'No shares pledged');
  assert.equal(dd[dt.indexOf('Industry on Money Flow')], 'Leading');
  dd.forEach(t => assert.doesNotMatch(t, /null|undefined|NaN|\bbuy\b|\bsell\b|should|recommend/i, `a figure reads "${t}"`));
  // The F-score is said once, from the filings.
  assert.doesNotMatch(await rows.first().locator('.ln').innerText(), /Piotroski/);

  await rows.first().locator('.evbtn').click();
  const ledger = rows.first().locator('.evrow');
  const pts = (await ledger.locator('> i').allInnerTexts()).map(t => parseFloat(t.replace('+', '')));
  assert.equal(pts.length, top.evidence.length);
  assert.ok(Math.abs(pts.reduce((a, b) => a + b, 0) - top.conviction) < 1.5, 'the ledger no longer adds up to the score');
  // Each part in the page's own plain words, one per part of the score. As
  // written: the ledger sets its labels in capitals.
  const labels = (await ledger.locator('> b').allTextContents()).map(t => t.trim());
  assert.deepEqual(labels, await page.evaluate(ev => ev.map(e => window.AltahaPicks.factorLabel(e)), top.evidence),
                   'the ledger is not the score’s own parts');
  top.evidence.forEach((e, i) => {
    assert.notEqual(labels[i], e.key, `the ledger prints the bare key "${e.key}"`);
    assert.ok(/\s/.test(labels[i]), `"${labels[i]}" is not a plain label`);
    assert.doesNotMatch(labels[i], ADVICE);
  });
  await page.screenshot({ path: path.join(output, 'list-desktop.png') });

  /* ── 3b · The results list ─────────────────────────────────────────────── */

  await page.locator('#hzseg .hz[data-h="results"]').click();
  const res = FIX.results;
  await page.locator(`#idearows .idea[data-t="${res.rows[0].symbol}"]`).waitFor();
  assert.deepEqual(await page.locator('#idearows .idea').evaluateAll(ns => ns.map(n => n.dataset.t)),
                   res.rows.map(r => r.symbol), 'the page reordered the results list');
  assert.ok((await page.locator('#pickhead').innerText()).includes(res.idea), 'the results list does not say what it is');
  if (res.study_current === false) assert.equal(await page.locator('#pickhead .pk-record').count(), 0);
  // Above its 200-day average: nothing to explain, so no market line.
  assert.equal(await page.locator('#pickhead .pk-market').count(), 0);
  const r0 = page.locator('#idearows .idea').first();
  assert.match(await r0.locator('.pk-why').innerText(), /Results on/);
  if (res.rows[0].results.vol_x != null) assert.match(await r0.locator('.pk-why').innerText(), /Volume [\d.]+× usual/);
  assert.match(await r0.locator('.pk-plan').innerText(), /about a month/);
  assert.match(await r0.locator('.pk-plan').innerText(), new RegExp('−' + Math.round(res.exit_pct) + '%'));
  await r0.locator('.morebtn').click();
  const fact = await r0.locator('.pk-fact').first().innerText();
  const [, mm, dd2] = res.rows[0].results.session.split('-');
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(mm) - 1];
  assert.match(fact, new RegExp('Priced on ' + Number(dd2) + ' ' + mon + ':'), 'the result date should read as a day and a month');
  assert.match(fact, /the average stock/);
  // The chart and the tape, as facts, with the line that says they rank nothing.
  const chart = r0.locator('.pk-chart');
  assert.equal(await chart.locator('dt').count(), res.rows[0].chart.length);
  assert.deepEqual(await chart.locator('dt').allInnerTexts(), res.rows[0].chart.map(c => c.k));
  assert.match(await chart.locator('p').innerText(), /none of them changes a rank/);
  // The ledger: the result-day move first, then the volume and the growth.
  await r0.locator('.evbtn').click();
  assert.equal(await r0.locator('.evrow').count(), res.rows[0].evidence.length);
  assert.match(await r0.locator('.evrow b').first().textContent(), /Move on the day its results were priced/);
  assert.match(await r0.locator('.evrow').first().innerText(), /results reached the exchange/);
  await page.screenshot({ path: path.join(output, 'results-desktop.png') });

  /* ── The setup lists: a second row of tabs, each with its own record ── */
  for (const key of ['breakout', 'technical', 'quick', 'flow', 'emerging']) {
    await page.locator(`#hzseg2 .hz[data-h="${key}"]`).click();
    await page.locator(`#idearows .idea[data-t="${FIX[key].rows[0].symbol}"]`).waitFor();
    assert.ok(await page.locator('#pickhead .pk-record-n').count() === 1, `${key}: the tested record is beside the list`);
    assert.equal(await page.locator('#pickhead .pk-measuring').count(), 0, `${key}: a measured list says it is being measured`);
    assert.ok((await page.locator('#idearows .idea').count()) === FIX[key].rows.length, `${key}: every pick is drawn`);
    assert.ok(await page.locator(`#hzseg2 .hz[data-h="${key}"]`).getAttribute('aria-selected') === 'true'
      && (await page.locator('#hzseg .hz[aria-selected="true"]').count()) === 0, `${key}: only its tab is selected`);
  }
  /* Swing dips (the quick list, rebuilt December 2026): held about a month,
     no target, and the average pick now covers the cost of trading it. */
  await page.locator('#hzseg2 .hz[data-h="quick"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.quick.rows[0].symbol}"]`).waitFor();
  assert.match(await page.locator('#idearows .idea .pk-plan').first().innerText(), /about a month/, 'quick: the plan says how long');
  assert.doesNotMatch(await page.locator('#idearows .idea .pk-plan').first().innerText(), /5-day average/);
  // A rebuilt setup list is held for its large winners and carries no target.
  assert.doesNotMatch(await page.locator('#idearows').innerText(), /Target/, 'quick: a target is shown on a list held for its winners');
  assert.equal(await page.locator('#pickaim .pk-aimnote').count(), 0);
  assert.equal(await page.locator('#pickhead .pk-cost').count(), FIX.quick.tested.avg_after_costs_pct < 0 ? 1 : 0,
    'quick: the cost note follows the record');
  // The record carries the share of 25%+ winners, as a fourth figure.
  assert.equal(await page.locator('#pickhead .pk-record-n.four > span').count(), 4, 'quick: the big-winner figure is missing');
  assert.match(await page.locator('#pickhead .pk-record-n').innerText(), /made 25% or more/);
  await page.locator('#pickhead .pk-record').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'quick-desktop.png') });
  /* Emerging: sold on a close under the 50-day average, and said so. */
  await page.locator('#hzseg2 .hz[data-h="emerging"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.emerging.rows[0].symbol}"]`).waitFor();
  assert.match(await page.locator('#idearows .idea .pk-plan').first().innerText(), /50-day average/, 'emerging: the plan names its sell rule');
  /* Money flow: the sector table, top sectors marked. */
  await page.locator('#hzseg2 .hz[data-h="flow"]').click();
  await page.locator('#pickhead .pk-sectors table').waitFor();
  assert.ok((await page.locator('#pickhead .pk-sectors tbody tr').count()) === FIX.flow.sector_flow.length, 'flow: every sector is ranked');
  assert.ok((await page.locator('#pickhead .pk-sectors tbody tr.on').count()) === FIX.flow.flow_sectors, 'flow: the sectors picked from are marked');
  assert.equal(FIX.flow.flow_sectors, 3, 'flow: the list takes the top three sectors');
  // Each sector's own index against its 60-session high: a sector breakout.
  assert.match(await page.locator('#pickhead .pk-sectors thead').textContent(), /Index/);
  assert.match(await page.locator('#pickhead .pk-sectors tbody').textContent(), /New high|% under/);
  /* Breakouts: the ledger is pass or fail, and the watch list is separate. */
  await page.locator('#hzseg2 .hz[data-h="breakout"]').click();
  const b0 = page.locator(`#idearows .idea[data-t="${FIX.breakout.rows[0].symbol}"]`);
  await b0.waitFor();
  assert.ok((await page.locator('#pickhead .pk-watch tbody tr').count()) === FIX.breakout.watch.length, 'breakout: the unbroken bases are listed apart');
  await b0.locator('.morebtn').click();
  await b0.locator('.evbtn').click();
  assert.ok(/VCP launchpad|Base turnaround/.test(await b0.locator('.evwrap').innerText())
    && !/null|undefined|NaN/.test(await b0.locator('.evwrap').innerText()),
    'breakout: the ledger names the pattern and reads as conditions met');
  // A live catalyst is marked on the pick and said in full in its details.
  assert.equal(await b0.locator('.pk-cat').innerText(), 'Catalyst');
  assert.match(await b0.locator('.pk-catalyst').innerText(), /Order worth/);
  // The pattern is a badge on the pick, and is not said twice.
  assert.equal(await b0.locator('.pk-badge:not(.pk-cat)').innerText(), FIX.breakout.rows[0].pattern);
  assert.equal((await b0.locator('.pk-why span').allInnerTexts()).filter(t => t === FIX.breakout.rows[0].pattern).length, 0);
  // Its figures are beside it too, where the filings give them, as facts.
  assert.equal(await b0.locator('.pk-funds').count(), FIX.breakout.rows[0].leader && FIX.breakout.rows[0].leader.fundamentals ? 1 : 0);
  await page.screenshot({ path: path.join(output, 'breakout-desktop.png') });

  // Another tab on the full list asks the server for that list.
  await page.locator('#hzseg .hz[data-h="month"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.month.rows[0].symbol}"]`).waitFor();
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /about a month/);
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), new RegExp('−' + Math.round(month.exit_pct) + '%'));
  assert.equal(await stored(page), 'month');
  // Every fact, and every part of every ledger, on the three lists describes:
  // the labels the page gives the parts, and what each part measured.
  const named = await page.evaluate(keys => keys.map(k => window.AltahaPicks.factorLabel({ key: k })),
                                    ['pull', 'high', 'fundmom', 'secflow', 'catalyst', 'reaction', 'volume', 'growth',
                                     'quality', 'compounding', 'governance', 'valuation', 'trendq']);
  named.forEach(n => { assert.ok(/\s/.test(n), `"${n}" is not a plain label`); assert.doesNotMatch(n, ADVICE); });
  for (const key of HOLD) {
    for (const r of FIX[key].rows) {
      r.why.forEach(w => assert.doesNotMatch(w, ADVICE, `${key} ${r.symbol}: "${w}"`));
      r.evidence.forEach(e => assert.doesNotMatch(e.detail, ADVICE, `${key} ${r.symbol}: "${e.detail}"`));
    }
  }

  // And the choice survives a reload, on the door too.
  await page.locator('#hzseg .hz[data-h="long"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  await page.goto(url('#research'));
  await page.reload();
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'long');
  assert.deepEqual(state.errors, [], 'the page threw');
  await context.close();

  /* ── 3c · Old names still open a list ─────────────────────────────────── */
  // A choice remembered from before the lists changed opens the list that
  // replaced it, and is kept that way.

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'picks'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  for (const [old, now] of [['week', 'month'], ['momentum', 'long'], ['trade', 'month'], ['position', 'long'], ['WEEK', 'month']]) {
    await page.evaluate(v => localStorage.setItem('altaha-pick-list', v), old);
    state.asked = [];
    await page.reload();
    await page.locator(`#dri-picks .pk-card[data-t="${FIX[now].rows[0].symbol}"]`).waitFor();
    assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), now,
                 `a stored "${old}" did not open ${now}`);
    assert.equal(await stored(page), now, `a stored "${old}" was not rewritten`);
    assert.ok(!state.asked.includes(old), `the door asked the server for "${old}"`);
  }
  // An address naming an old list opens the one that replaced it, and the
  // address says so.
  for (const [hash, now] of [['#ideas/week', 'month'], ['#research/ideas/momentum', 'long'], ['#ideas/position', 'long']]) {
    await page.goto('about:blank');
    await page.goto(url(hash));
    await page.locator(`#idearows .idea[data-t="${FIX[now].rows[0].symbol}"]`).waitFor();
    assert.equal(await page.locator('#hzseg .hz.on').getAttribute('data-h'), now, `${hash} did not open ${now}`);
    assert.match(page.url(), new RegExp('#research/ideas/' + now + '$'), `${hash} left the address as it was`);
    assert.equal(await stored(page), now);
  }
  // Once the address names a list, a tab keeps it in step, and a reload
  // opens what was on screen.
  await page.locator('#hzseg .hz[data-h="results"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.results.rows[0].symbol}"]`).waitFor();
  assert.match(page.url(), /#research\/ideas\/results$/);
  await page.reload();
  await page.locator(`#idearows .idea[data-t="${FIX.results.rows[0].symbol}"]`).waitFor();
  assert.equal(await page.locator('#hzseg .hz.on').getAttribute('data-h'), 'results');
  // A name that is no list is no harm: the remembered list opens.
  await page.goto('about:blank');
  await page.goto(url('#research/ideas/nonsense'));
  await page.locator(`#idearows .idea[data-t="${FIX.results.rows[0].symbol}"]`).waitFor();
  assert.equal(await page.locator('#hzseg .hz.on').getAttribute('data-h'), 'results');
  assert.deepEqual(state.errors, [], 'the page threw on an old name');
  await context.close();

  // Storage that refuses: the first list opens, and nothing throws.
  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'picks'));
  await context.addInitScript(() => {
    const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
    Storage.prototype.getItem = function (k) { if (k === 'altaha-pick-list') throw new Error('blocked'); return get.call(this, k); };
    Storage.prototype.setItem = function (k, v) { if (k === 'altaha-pick-list') throw new Error('blocked'); return set.call(this, k, v); };
  });
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'month');
  await page.locator('#dri-picks .pk-tab[data-pick="long"]').click();
  await page.locator(`#dri-picks .pk-card[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  assert.deepEqual(state.errors, [], 'the page threw when storage refused');
  await context.close();

  /* ── 3d · Once the study has measured the new lists ───────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'studied'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  const studied = (await page.locator('#dri-picks .pk-record-n b').allInnerTexts()).map(t => t.trim());
  assert.deepEqual(studied, [String(Math.round(STUDIED.up_pct)), '+' + STUDIED.avg_pct.toFixed(1) + '%',
                             '+' + STUDIED.index_avg_pct.toFixed(1) + '%'], 'the record is not the study’s');
  assert.deepEqual((await page.locator('#dri-picks .pk-record-n small').allInnerTexts()).map(t => t.trim()),
                   ['of every 100 picks went up', 'average gain per pick, held about a month', 'the market over the same time']);
  assert.equal(await page.locator('#dri-picks .pk-measuring').count(), 0);
  assert.match(await page.locator('#dri-picks .pk-live').innerText(), /5 of 8 closed calls rose/);
  await page.locator('#dri-picks .pk-how summary').click();
  const how = await page.locator('#dri-picks .pk-how').innerText();
  assert.match(how, /Before costs and tax/); assert.match(how, /2018-21/); assert.match(how, /2022-26/);
  assert.match(how, new RegExp(STUDIED.picks.toLocaleString('en-IN')), 'the number of tested picks is missing');
  const sold = await page.locator('#dri-picks .pk-aimnote').innerText();
  assert.ok(sold.includes(`${TARGET.sold.up_pct} of 100`) && sold.includes(`+${TARGET.sold.avg_pct.toFixed(2)}%`),
            'the target note does not give the study’s figures for selling there');
  assert.deepEqual(state.errors, [], 'the page threw on a measured list');
  await context.close();

  /* ── 3e · Before the study has measured them ──────────────────────────── */
  // The record in the study file is the replaced list's: none is printed,
  // nor the calls the replaced list made, nor what a test found about the
  // target. One plain line says the record is being measured.

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'measuring'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-record').count(), 0, 'the replaced list’s record is printed beside the new one');
  assert.equal(await page.locator('#dri-picks .pk-live').count(), 0, 'the replaced list’s calls are printed beside the new one');
  const measuring = await page.locator('#dri-picks .pk-measuring').innerText();
  assert.match(measuring, /record is being measured/);
  assert.doesNotMatch(measuring, ADVICE);
  assert.doesNotMatch(await page.locator('#dri-picks .pk-aimnote').innerText(), /In the test|was tested/,
                      'the target note quotes a test the list has not had');
  await page.locator('#dri-picks .pk-tab[data-pick="long"]').click();
  await page.locator(`#dri-picks .pk-card[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  await page.locator('#dri-picks .pk-all').click();
  await page.locator(`#idearows .idea[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  assert.equal(await page.locator('#pickhead .pk-record').count(), 0);
  assert.match(await page.locator('#pickhead .pk-measuring').innerText(), /being measured/);
  assert.doesNotMatch(await page.locator('#pickaim').innerText(), /In the test|was tested/);
  // A setup list was measured on its own recipe: its record stands.
  await page.locator('#hzseg2 .hz[data-h="technical"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.technical.rows[0].symbol}"]`).waitFor();
  assert.equal(await page.locator('#pickhead .pk-record').count(), 1);
  assert.equal(await page.locator('#pickhead .pk-measuring').count(), 0);
  assert.deepEqual(state.errors, [], 'the page threw on a list being measured');
  await context.close();

  /* ── 4 · A scan from before the lists still draws ─────────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'legacy'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.match(await page.locator('#dri-picks .pk-quiet').first().innerText(), /after the next scan/);
  assert.equal(await page.locator('#dri-picks .pk-record').count(), 0, 'an untested list is showing a tested record');
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  assert.equal(await page.locator('#idearows .idea').count(), FIX.legacy.rows.length);
  assert.ok(await page.locator('#idearows .ideaplan2').count() > 0, 'the old rows lost their plan');
  assert.equal(await page.locator('#idearows .pk-plan').count(), 0);
  assert.match(await page.locator('#pickhead').innerText(), /after the next scan/);
  assert.deepEqual(state.errors, [], 'the page threw on an old scan');
  await context.close();

  /* ── 4b · A scan ranked with an earlier recipe shows no record ────────── */
  // After a deploy that changes a recipe, the scan on disk keeps its old ranks
  // until the next one. The server sends no record; the page says why, once.

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'oldrecipe'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-record').count(), 0, 'a record was printed beside an older recipe');
  assert.match(await page.locator('#dri-picks .pk-body').innerText(), /previous recipe/);
  assert.equal(await page.locator('#dri-picks .pk-measuring').count(), 0, 'two lines say why there is no record');
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  assert.equal(await page.locator('#pickhead .pk-record').count(), 0);
  assert.match(await page.locator('#pickhead').innerText(), /previous recipe/);
  assert.deepEqual(state.errors, [], 'the page threw on an older recipe');
  await context.close();

  /* ── 4c · Between results seasons the results list says when it fills in ── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'offseason'));
  await page.addInitScript(() => localStorage.setItem('altaha-pick-list', 'results'));
  const between = FIX.results_empty.empty_text;
  assert.match(between, /Companies report again from about \d+ \w+|reporting now/, 'the fixture does not name the next season');
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-idea').waitFor();
  assert.equal(await page.locator('#dri-picks .pk-card').count(), 0);
  assert.ok((await page.locator('#dri-picks .pk-body').innerText()).includes(between), 'the door does not say when the list fills in');
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .ideas-note').waitFor();
  assert.equal((await page.locator('#idearows .ideas-note').innerText()).trim(), between);
  assert.equal(await page.locator('#idearows .idea').count(), 0);
  await page.screenshot({ path: path.join(output, 'results-between-seasons.png') });
  assert.deepEqual(state.errors, [], 'the page threw on an empty results list');
  await context.close();

  /* ── 4d · A weak market: what the test found, not the old warning ──────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'weak'));
  await page.addInitScript(() => localStorage.setItem('altaha-pick-list', 'technical'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.match(await page.locator('#dri-picks .pk-market').innerText(), /not held back/);
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  assert.match(await page.locator('#pickhead .pk-market').innerText(), /under its 200-day average/);
  assert.doesNotMatch(await page.locator('#view-ideas').innerText(), /trend setups fail more often/,
                      'the untested warning is back on a tested list');
  assert.deepEqual(state.errors, [], 'the page threw in a weak market');
  await context.close();

  /* ── 5 · An API that does not answer says so ──────────────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'down'));
  await page.goto(url('#research'));
  const retry = page.locator('#dri-picks .pk-retry');
  await retry.waitFor({ state: 'visible' });
  assert.match(await page.locator('#dri-picks .pk-quiet').innerText(), /could not be loaded/);
  state.mode = 'picks';
  await retry.click();
  await page.locator('#dri-picks .pk-card').first().waitFor();
  // The rest of the door is still there: every other tool stays reachable.
  assert.ok(await page.locator('#view-ideahub .dr-tool').count() >= 4);
  await context.close();

  /* ── 6 · A 390px phone ─────────────────────────────────────────────────── */

  ({ context, page, state } = await open(browser, { width: 390, height: 800 }, 'picks'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  const tabs = await boxes(page.locator('#dri-picks .pk-tab'));
  assert.equal(tabs.length, 8);
  tabs.forEach((t, i) => {
    assert.ok(t.left >= 0 && t.right <= 390, `tab ${i + 1} runs off a phone screen (${Math.round(t.right)}px)`);
    assert.ok(t.h >= 38, `tab ${i + 1} is ${Math.round(t.h)}px tall: too small to tap`);
  });
  thirds(await boxes(page.locator('#dri-picks .pk-tabs.hold .pk-tab')), 'door on a phone');
  // A phone keeps each list's holding time, and the first list's short name.
  assert.deepEqual((await page.locator('#dri-picks .pk-tabs.hold .pk-tab').allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim()),
                   ['Swing ' + CHIPS[0], 'After results ' + CHIPS[1], 'Long term ' + CHIPS[2]]);
  assert.ok((await page.locator('#dri-picks .pk-card').first().boundingBox()).y < 800, 'no pick on a phone’s first screen');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the door scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'door-phone.png') });

  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  const pageRight = await page.locator('#hzseg .hz, #hzseg2 .hz').evaluateAll(ns => ns.map(n => n.getBoundingClientRect().right));
  assert.equal(pageRight.length, 8);
  pageRight.forEach((r, i) => assert.ok(r <= 390, `list tab ${i + 1} runs off a phone screen`));
  thirds(await boxes(page.locator('#hzseg .hz')), 'page on a phone');
  // Money flow on a phone: the sector table fits or scrolls inside its own box.
  await page.locator('#hzseg2 .hz[data-h="flow"]').click();
  await page.locator('#pickhead .pk-sectors table').waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the money-flow list scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'flow-phone.png') });
  // The results list on a phone: the chart facts stack and nothing runs wide.
  await page.locator('#hzseg .hz[data-h="results"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.results.rows[0].symbol}"]`).waitFor();
  await page.locator('#idearows .idea').first().locator('.morebtn').click();
  await page.locator('#idearows .idea').first().locator('.pk-chart').waitFor({ state: 'visible' });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the results list scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'results-phone.png') });
  // Long term on a phone: long industry names wrap inside their own facts,
  // and the figures box stacks.
  await page.locator('#hzseg .hz[data-h="long"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  await page.locator('#idearows .idea').first().locator('.morebtn').click();
  await page.locator('#idearows .idea').first().locator('.pk-funds').waitFor({ state: 'visible' });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the long-term list scrolls sideways on a phone');
  const pills = await page.locator('#idearows .pk-why span').evaluateAll(ns => ns.map(n => n.getBoundingClientRect().right));
  pills.forEach((r, i) => assert.ok(r <= 390, `fact ${i + 1} runs off a phone screen`));
  await page.locator('#hzseg .hz[data-h="month"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.month.rows[0].symbol}"]`).waitFor();
  assert.ok((await page.locator('#idearows .idea').first().boundingBox()).y < 800, 'no stock on a phone’s first screen of the list');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the list scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'list-phone.png') });
  assert.deepEqual(state.errors, [], 'the page threw on a phone');
  await context.close();

  // With a record above the picks, and without one, the first pick is still
  // on a phone's first screen, on the door and on the full list.
  for (const mode of ['studied', 'measuring']) {
    ({ context, page, state } = await open(browser, { width: 390, height: 800 }, mode));
    await page.goto(url('#research'));
    await page.locator('#dri-picks .pk-card').first().waitFor();
    assert.equal(await page.locator('#dri-picks .pk-record').count(), mode === 'studied' ? 1 : 0);
    const card = (await page.locator('#dri-picks .pk-card').first().boundingBox()).y;
    assert.ok(card < 800, `${mode}: the first pick is ${Math.round(card)}px down a phone`);
    await page.goto(url('#research/ideas'));
    await page.locator(`#idearows .idea[data-t="${FIX.month.rows[0].symbol}"]`).waitFor();
    const row = (await page.locator('#idearows .idea').first().boundingBox()).y;
    assert.ok(row < 800, `${mode}: the first stock is ${Math.round(row)}px down a phone`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, `${mode}: the list scrolls sideways`);
    if (mode === 'studied') await page.screenshot({ path: path.join(output, 'list-phone-studied.png') });
    assert.deepEqual(state.errors, [], `the page threw on a phone (${mode})`);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('picks: door, three lists by holding time, old names and addresses, measuring and measured records, full list, ' +
              'figures and ledger, results list, setups, weak market, old scan, older recipe, unreachable API and phone all hold');
})().catch(err => {
  console.error(err && err.stack || err);
  console.log(`::error title=Stock picks::${String(err && err.message || err).split('\n')[0]}`);
  process.exit(1);
});
