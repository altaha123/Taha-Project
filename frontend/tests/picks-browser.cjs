/* The stock picks, in a real browser.

   Colleagues who were sent the site said two things: it is too complex, and
   there is too much writing. Both were truest of Ideas, which answered "what
   should I look at?" with a picture of a planet. So what this pins is mostly
   about the first screen, and none of it throws when it breaks:

     · the Ideas door shows picks on the first screen, above the scan, in four
       tabs: this week, this month, momentum, long term
     · each list says what it is in one line and how it tested in three
       numbers that are the study's own, not the page's
     · a pick shows its reasons, a hold and an exit price. No WAIT, no target
     · the chosen tab is remembered, and "See all" opens the same list
     · on the full list the stocks come before the scan, every row has its
       reasons and its plan, and the ledger adds up to the score
     · a scan from before the lists still draws, the old way, and says so
     · an unreachable API says so and offers a retry
     · on a 390px phone all four tabs fit and nothing scrolls sideways

   /ideas is fulfilled from fixtures/picks.json, which is the real endpoint's
   answer for 9 Nov 2026 trimmed to the fields the page reads. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/picks');
fs.mkdirSync(output, { recursive: true });
const FIX = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/picks.json'), 'utf8'));
const KEYS = ['week', 'month', 'momentum', 'long'];
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

/* mode: 'picks' (the four lists), 'legacy' (a scan from before them),
   'down' (the API does not answer). */
async function open(browser, size, mode) {
  const context = await browser.newContext({ viewport: size, hasTouch: size.width < 600 });
  await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
  const state = { mode, asked: [], errors: [] };
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    const cors = { 'access-control-allow-origin': '*' };
    if (u.pathname === '/ideas') {
      const h = u.searchParams.get('horizon');
      state.asked.push(h);
      if (state.mode === 'down') return route.abort();
      if (state.mode === 'legacy') return route.fulfill({ json: FIX.legacy, headers: cors });
      return route.fulfill({ json: FIX[h] || FIX.month, headers: cors });
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
                   ['This week', 'This month', 'Momentum', 'Long term']);
  assert.equal(await panel.locator('.pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'month',
               'a first visit should open on the month list');

  // Picks before the scan, and on the first screen.
  const firstCard = await panel.locator('.pk-card').first().boundingBox();
  const scan = await page.locator('#view-ideahub .dr-universe').boundingBox();
  assert.ok(firstCard.y < 900, `the first pick is ${Math.round(firstCard.y)}px down: not on the first screen`);
  assert.ok(firstCard.y < scan.y, 'the scan is drawn above the picks again');
  assert.equal(await panel.locator('.pk-card').count(), 5, 'the door shows the top five');

  // What the list is, in one line, and how it tested, in the study's numbers.
  const month = FIX.month;
  assert.match(await panel.locator('.pk-idea').innerText(), /Hold about a month/);
  const record = (await panel.locator('.pk-record-n b').allInnerTexts()).map(t => t.trim());
  assert.equal(record[0], String(Math.round(month.tested.up_pct)), 'the "rose" figure is not the study’s');
  assert.equal(record[1], '+' + month.tested.avg_pct.toFixed(1) + '%', 'the average is not the study’s');
  assert.equal(record[2], '+' + month.tested.index_avg_pct.toFixed(1) + '%', 'the market figure is not the study’s');
  await panel.locator('.pk-how summary').click();
  const how = await panel.locator('.pk-how').innerText();
  assert.match(how, /Before costs and tax/, 'the record does not say it is before costs');
  assert.match(how, /2017–21/); assert.match(how, /2022–26/);
  assert.match(how, new RegExp(month.tested.picks.toLocaleString('en-IN')), 'the number of tested picks is missing');
  // Live calls are shown once five have closed; this list has eight.
  assert.match(await panel.locator('.pk-live').innerText(), /5 of 8 closed calls rose/);

  // A pick: name, reasons, and the one price that ends it.
  for (let i = 0; i < 5; i++) {
    const card = panel.locator('.pk-card').nth(i), row = month.rows[i];
    assert.match(await card.innerText(), new RegExp(row.symbol));
    assert.ok(await card.locator('.pk-why span').count() >= 1, `${row.symbol} gives no reason`);
    assert.equal(rupees(await card.locator('.pk-exit b').innerText()), Math.round(row.plan.stop * 100) / 100 >= 1000
      ? Math.round(row.plan.stop) : row.plan.stop, `${row.symbol} shows the wrong exit price`);
  }
  const doorText = await panel.innerText();
  assert.doesNotMatch(doorText, /\bWAIT\b|Target|R:R|Stop loss/i, 'the old trade plan is back on the door');
  await page.screenshot({ path: path.join(output, 'door-desktop.png') });

  /* ── 2 · Tabs switch the list, and the choice is remembered ───────────── */

  await panel.locator('.pk-tab[data-pick="long"]').click();
  await panel.locator(`.pk-card[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  assert.match(await panel.locator('.pk-idea').innerText(), /Hold about a year/);
  assert.equal((await panel.locator('.pk-record-n b').first().innerText()).trim(), String(Math.round(FIX.long.tested.up_pct)));
  assert.equal(await panel.locator('.pk-live').count(), 0, 'no live line until five calls have closed');
  assert.ok(state.asked.includes('long'));

  await panel.locator('.pk-tab[data-pick="momentum"]').click();
  await panel.locator(`.pk-card[data-t="${FIX.momentum.rows[0].symbol}"]`).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('altaha-pick-list')), 'momentum');

  /* ── 3 · "See all" opens the same list, stocks first ──────────────────── */

  await panel.locator('.pk-all').click();
  await page.locator('#view-ideas').waitFor({ state: 'visible' });
  await page.locator('#idearows .idea').first().waitFor();
  assert.match(page.url(), /#research\/ideas$/);
  assert.equal(await page.locator('#hzseg .hz.on').getAttribute('data-h'), 'momentum', 'the full list opened on another tab');
  assert.equal(await page.locator('#idearows .idea').count(), 15);
  assert.deepEqual(await page.locator('#idearows .idea').evaluateAll(ns => ns.map(n => n.dataset.t)),
                   FIX.momentum.rows.map(r => r.symbol), 'the page reordered the server’s list');

  const firstRow = await page.locator('#idearows .idea').first().boundingBox();
  const hero = await page.locator('#scan-universe').boundingBox();
  assert.ok(firstRow.y < hero.y, 'the scan is above the list again');
  assert.ok(firstRow.y < 900, `the first stock is ${Math.round(firstRow.y)}px down: not on the first screen`);

  const rows = page.locator('#idearows .idea');
  for (let i = 0; i < 15; i++) {
    const r = rows.nth(i);
    assert.ok(await r.locator('.pk-why span').count() >= 1, `row ${i + 1} gives no reason`);
    const plan = await r.locator('.pk-plan').innerText();
    assert.match(plan, /Hold\s+about 3 months/); assert.match(plan, /Exit below\s+₹/); assert.match(plan, /−15%/);
    assert.equal(await r.locator('.ideaplan2').count(), 0, 'a tested pick is showing the old plan grid');
  }
  assert.doesNotMatch(await page.locator('#idearows').innerText(), /\bWAIT\b|BUY RANGE|TARGET|R:R/i);
  assert.match(await page.locator('#pickhead').innerText(), /stocks compared/);
  // The reasons a name was left out are kept, folded.
  assert.match(await page.locator('#pickhead .pk-notes summary').innerText(), /1 note on this list/);
  // No filter dialog and no thin-stock switch for fifteen rows.
  assert.equal(await page.locator('#view-ideas .ux-filterbar').isVisible(), false);
  assert.equal(await page.locator('#thintoggle').isVisible(), false);

  // The ledger behind the score adds up to it.
  await rows.first().locator('.morebtn').click();
  await rows.first().locator('.evbtn').click();
  const first = FIX.momentum.rows[0];
  const pts = (await rows.first().locator('.evrow > i').allInnerTexts()).map(t => parseFloat(t.replace('+', '')));
  assert.equal(pts.length, first.evidence.length);
  assert.ok(Math.abs(pts.reduce((a, b) => a + b, 0) - first.conviction) < 1.5, 'the ledger no longer adds up to the score');
  await page.screenshot({ path: path.join(output, 'list-desktop.png') });

  // Another tab on the full list asks the server for that list.
  await page.locator('#hzseg .hz[data-h="week"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.week.rows[0].symbol}"]`).waitFor();
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /about a week/);
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /−7%/);
  assert.equal(await page.evaluate(() => localStorage.getItem('altaha-pick-list')), 'week');

  // And the choice survives a reload, on the door too.
  await page.goto(url('#research'));
  await page.reload();
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'week');
  assert.deepEqual(state.errors, [], 'the page threw');
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
  const tabs = await page.locator('#dri-picks .pk-tab').evaluateAll(ns => ns.map(n => {
    const b = n.getBoundingClientRect(); return { left: b.left, right: b.right, h: b.height };
  }));
  assert.equal(tabs.length, 4);
  tabs.forEach((t, i) => {
    assert.ok(t.left >= 0 && t.right <= 390, `tab ${i + 1} runs off a phone screen (${Math.round(t.right)}px)`);
    assert.ok(t.h >= 38, `tab ${i + 1} is ${Math.round(t.h)}px tall: too small to tap`);
  });
  assert.ok((await page.locator('#dri-picks .pk-card').first().boundingBox()).y < 800, 'no pick on a phone’s first screen');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the door scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'door-phone.png') });

  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  const pageTabs = await page.locator('#hzseg .hz').evaluateAll(ns => ns.map(n => n.getBoundingClientRect().right));
  pageTabs.forEach((r, i) => assert.ok(r <= 390, `list tab ${i + 1} runs off a phone screen`));
  assert.ok((await page.locator('#idearows .idea').first().boundingBox()).y < 800, 'no stock on a phone’s first screen of the list');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the list scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'list-phone.png') });
  assert.deepEqual(state.errors, [], 'the page threw on a phone');
  await context.close();

  await browser.close();
  server.close();
  console.log('picks: door, tabs, full list, old scan, unreachable API and phone all hold');
})().catch(err => {
  console.error(err && err.stack || err);
  console.log(`::error title=Stock picks::${String(err && err.message || err).split('\n')[0]}`);
  process.exit(1);
});
