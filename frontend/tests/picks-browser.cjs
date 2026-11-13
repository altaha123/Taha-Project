/* The Ideas page: two lists, short term and long term.
 *
 * There were ten tabs. A reader asked for two, and for the short-term one to
 * be a single list built from the chart, the industry, the last quarter and
 * the news together. This drives the real page in Chromium against
 * fixtures/picks.json, which is the engine's own answer for one day:
 *
 *   · the door opens on Short term, with its tested record, and has two tabs
 *   · each pick says why in words, and carries one exit price
 *   · the full list draws every pick; its ledger reads as screens passed
 *   · stocks on the verge of a breakout are listed apart, as a watch list
 *   · Long term is the other tab; the choice survives a reload
 *   · an empty short list says that an empty list is the answer
 *   · a scan from before the lists, a scan ranked with an older recipe and an
 *     API that does not answer each say so and throw nothing
 *   · on a 390px phone both tabs fit and nothing scrolls sideways
 */


const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/picks');
fs.mkdirSync(output, { recursive: true });
const FIX = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/picks.json'), 'utf8'));
const KEYS = ['short', 'long'];
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

/* mode: 'picks' (the lists), 'legacy' (a scan from before them),
   'oldrecipe' (the lists, ranked before a recipe changed), 'down' (the API
   does not answer), 'offseason' (nobody has reported lately), 'weak' (the
   index is under its 200-day average). */
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
      if (state.mode === 'oldrecipe') {
        return route.fulfill({ json: { ...(FIX[h] || FIX.short), tested: null, recipe_current: false },
                               headers: cors });
      }
      if (state.mode === 'quiet' && h === 'short') {
        return route.fulfill({ json: FIX.short_empty, headers: cors });
      }
      if (state.mode === 'weak') {
        return route.fulfill({ json: { ...(FIX[h] || FIX.short), regime: { ok: false, label: 'Index below its 50-day average — trend setups fail more often here.' },
          market_test: { state: 'below_200d', text: 'The index is under its 200-day average. In the test, picks made on days like this averaged +9.2% (64 in 100 rose), against +4.4% on the other days. The list is not held back in either.' } },
                               headers: cors });
      }
      return route.fulfill({ json: FIX[h] || FIX.short, headers: cors });
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
  fs.mkdirSync(output, { recursive: true });

  /* ── 1 · The door: two tabs, short term first ─────────────────────────── */

  let { context, page, state } = await open(browser, { width: 1280, height: 900 }, 'picks');
  await page.goto(url('#research'));
  const panel = page.locator('#view-ideahub #dri-picks');
  await panel.locator('.pk-card').first().waitFor({ state: 'visible' });
  assert.deepEqual(await panel.locator('.pk-tab').evaluateAll(ns => ns.map(n => n.getAttribute('aria-label'))),
                   ['Short term', 'Long term']);
  assert.equal(await panel.locator('.pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'short',
               'a first visit should open on the short-term list');
  assert.ok((await panel.locator('.pk-card').first().boundingBox()).y < 900, 'no pick on the first screen');
  assert.equal(await panel.locator('.pk-record-n').count(), 1, 'the tested record is not beside the list');
  assert.equal(await panel.locator('.pk-card').count(), Math.min(5, FIX.short.rows.length));
  const first = FIX.short.rows[0];
  assert.match(await panel.locator('.pk-card').first().innerText(), new RegExp(first.symbol));
  assert.ok(Math.abs(rupees(await panel.locator('.pk-card .pk-exit b').first().innerText()) - first.plan.stop) < 1,
            'the exit price on the card is not the plan\'s');
  assert.match(await panel.locator('.pk-card .pk-why').first().innerText(), /Broke out/);
  await page.screenshot({ path: path.join(output, 'door-desktop.png') });

  await panel.locator('.pk-tab[data-pick="long"]').click();
  await panel.locator(`.pk-card[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  assert.match(await panel.locator('.pk-idea').innerText(), /about a year/);
  await panel.locator('.pk-tab[data-pick="short"]').click();
  await panel.locator(`.pk-card[data-t="${first.symbol}"]`).waitFor();

  /* ── 2 · The full list ────────────────────────────────────────────────── */

  await panel.locator('.pk-all').click();
  await page.locator('#view-ideas').waitFor({ state: 'visible' });
  await page.locator(`#idearows .idea[data-t="${first.symbol}"]`).waitFor();
  assert.equal(await page.locator('#hzseg .hz').count(), 2, 'the list page has more than two tabs');
  assert.equal(await page.locator('#hzseg .hz[aria-selected="true"]').getAttribute('data-h'), 'short');
  assert.equal(await page.locator('#idearows .idea').count(), FIX.short.rows.length, 'not every pick is drawn');
  assert.equal(await page.locator('#pickhead .pk-record-n').count(), 1);
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /about a month/);
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /−8%/);
  // On the verge: listed apart, and said not to be picks.
  assert.equal(await page.locator('#pickhead .pk-watch tbody tr').count(), FIX.short.watch.length,
               'the stocks on the verge are not listed');
  await page.locator('#pickhead .pk-watch summary').click();
  assert.match(await page.locator('#pickhead .pk-watch').innerText(), /Not picks/);
  // The ledger: the screens a pick passed, in words.
  const r0 = page.locator('#idearows .idea').first();
  await r0.locator('.morebtn').click();
  await r0.locator('.evbtn').click();
  const ledger = await r0.locator('.evwrap').innerText();
  for (const word of ['Consolidation', 'Breakout', 'Technicals', 'Industry', 'Fundamentals']) {
    assert.match(ledger, new RegExp(word), `the ledger does not show ${word}`);
  }
  assert.doesNotMatch(ledger, /null|undefined|NaN/, 'the ledger printed a hole');
  await page.screenshot({ path: path.join(output, 'list-desktop.png'), fullPage: false });

  await page.locator('#hzseg .hz[data-h="long"]').click();
  await page.locator(`#idearows .idea[data-t="${FIX.long.rows[0].symbol}"]`).waitFor();
  assert.match(await page.locator('#idearows .pk-plan').first().innerText(), /about a year/);
  assert.equal(await page.locator('#pickhead .pk-watch').count(), 0, 'the watch list belongs to the short-term tab');
  assert.equal(await page.evaluate(() => localStorage.getItem('altaha-pick-list')), 'long');
  assert.ok(state.asked.every(h => KEYS.includes(h)), 'the page asked for a list it no longer shows: ' + state.asked.join());

  // The choice survives a reload, on the door too.
  await page.goto(url('#research'));
  await page.reload();
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'long');
  assert.deepEqual(state.errors, [], 'the page threw');
  await context.close();

  /* ── 3 · A reader who had one of the old eight lists chosen ───────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'picks'));
  await page.addInitScript(() => localStorage.setItem('altaha-pick-list', 'momentum'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-tab[aria-selected="true"]').getAttribute('data-pick'), 'short',
               'a list that no longer has a tab was opened');
  await context.close();

  /* ── 4 · A day nothing passes ─────────────────────────────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'quiet'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-record').waitFor();
  assert.equal(await page.locator('#dri-picks .pk-card').count(), 0);
  assert.match(await page.locator('#dri-picks .pk-body').innerText(), /An empty list is the answer/);
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .ideas-note').waitFor();
  assert.match(await page.locator('#idearows').innerText(), /An empty list is the answer/);
  assert.deepEqual(state.errors, [], 'the page threw on an empty list');
  await context.close();

  /* ── 5 · A scan from before the lists still draws ─────────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'legacy'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.match(await page.locator('#dri-picks .pk-quiet').first().innerText(), /after the next scan/);
  assert.equal(await page.locator('#dri-picks .pk-record').count(), 0, 'an untested list is showing a tested record');
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  assert.equal(await page.locator('#idearows .idea').count(), FIX.legacy.rows.length);
  assert.deepEqual(state.errors, [], 'the page threw on an old scan');
  await context.close();

  /* ── 6 · A scan ranked with an earlier recipe shows no record ─────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'oldrecipe'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.equal(await page.locator('#dri-picks .pk-record').count(), 0, 'a record was printed beside an older recipe');
  assert.match(await page.locator('#dri-picks .pk-body').innerText(), /previous recipe/);
  assert.deepEqual(state.errors, [], 'the page threw on an older recipe');
  await context.close();

  /* ── 7 · The API does not answer ──────────────────────────────────────── */

  ({ context, page, state } = await open(browser, { width: 1280, height: 900 }, 'down'));
  await page.goto(url('#research'));
  const retry = page.locator('#dri-picks .pk-retry');
  await retry.waitFor({ state: 'visible' });
  state.mode = 'picks';
  await retry.click();
  await page.locator('#dri-picks .pk-card').first().waitFor();
  assert.deepEqual(state.errors, [], 'the page threw when the API was down');
  await context.close();

  /* ── 8 · A 390px phone ────────────────────────────────────────────────── */

  ({ context, page, state } = await open(browser, { width: 390, height: 800 }, 'picks'));
  await page.goto(url('#research'));
  await page.locator('#dri-picks .pk-card').first().waitFor();
  const tabs = await page.locator('#dri-picks .pk-tab').evaluateAll(ns => ns.map(n => {
    const b = n.getBoundingClientRect(); return { left: b.left, right: b.right, h: b.height };
  }));
  assert.equal(tabs.length, 2);
  tabs.forEach((t, i) => {
    assert.ok(t.left >= 0 && t.right <= 390, `tab ${i + 1} runs off a phone screen`);
    assert.ok(t.h >= 38, `tab ${i + 1} is ${Math.round(t.h)}px tall: too small to tap`);
  });
  assert.ok((await page.locator('#dri-picks .pk-card').first().boundingBox()).y < 800, 'no pick on a phone\'s first screen');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the door scrolls sideways on a phone');
  await page.screenshot({ path: path.join(output, 'door-phone.png') });
  await page.goto(url('#research/ideas'));
  await page.locator('#idearows .idea').first().waitFor();
  await page.locator('#idearows .idea').first().locator('.morebtn').click();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the list scrolls sideways on a phone');
  assert.ok((await page.locator('#idearows .idea').first().boundingBox()).y < 800, 'no stock on a phone\'s first screen of the list');
  await page.screenshot({ path: path.join(output, 'list-phone.png') });
  assert.deepEqual(state.errors, [], 'the page threw on a phone');
  await context.close();

  await browser.close();
  server.close();
  console.log('picks: two tabs, short-term list with its ledger and watch list, long term, empty day, old scan, older recipe, unreachable API and phone all hold');
})().catch(e => {
  console.error(e);
  console.log('::error title=Stock picks::' + String(e.message).split('\n')[0]);
  process.exit(1);
});
