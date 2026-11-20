/* Delivery trends in a real Chromium, against a fixture the real backend
   function produced from invented data (backend/tests/make_delivery_trends_
   fixture.py). No live calls.

   What this is actually guarding:
     · THE TAB OPENS ON WHAT ITS NAME SAYS. For a long time "Delivery trends"
       opened on a one-year ranking and three backtest figures, with nothing
       about this week on the page. The lists come first; the ranking is
       folded away underneath and is NOT FETCHED until somebody opens it.
     · NOTHING IS FETCHED UNTIL THE TAB IS SHOWN, and switching between the
       three lists or the price direction never goes back to the server. Only
       changing the liquidity floor does, because that changes who qualifies.
     · A ROW OPENS INTO THE ARITHMETIC, in words, with a link to every session.
     · A YOUNG STORE EXPLAINS ITSELF rather than rendering an empty page.
     · phone through desktop, both themes, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/delivery-trends');
fs.mkdirSync(output, { recursive: true });
const SCALE = Number(process.env.SHOT_SCALE || 1);

const trends = JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/delivery-trends.json'), 'utf8'));
const building = { available: false, building: true, sessions: 9, needed: 26,
  message: 'Reading the exchange delivery record — 9 of 26 sessions in. This fills itself; nothing here needs a retry.' };
const book = { available: false, building: true, sessions: 60, needed: 120,
  message: 'Reading the exchange delivery record — 60 of 120 sessions in.' };

async function openTab(page, id) {
  await page.waitForLoadState('load');
  await page.waitForTimeout(400);
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.evaluate(t => window.AltahaNav.go('discover', t, true), id);
    try {
      await page.locator('#view-' + id).waitFor({ state: 'visible', timeout: 2000 });
      await page.waitForTimeout(150);
      if (await page.locator('#view-' + id).isVisible()) return;
    } catch (_) { /* retry */ }
  }
  assert.fail('could not open the ' + id + ' view');
}

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
  await new Promise(r => server.listen(8791, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 }, reducedMotion: 'reduce', deviceScaleFactor: SCALE });
  await context.addInitScript(() => { try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (e) {} });
  const page = await context.newPage(), errors = [];
  const asked = [];                       // every /delivery/trends query string
  let bookCalls = 0, payload = trends;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/delivery/trends') {
      asked.push(u.search);
      const floor = Number(u.searchParams.get('min_turnover_cr') || 10);
      return route.fulfill({ json: payload.available === false ? payload
        : Object.assign({}, payload, { min_turnover_cr: floor }) });
    }
    if (u.pathname === '/special') { bookCalls++; return route.fulfill({ json: book }); }
    if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
    return route.fulfill({ json: { available: false, rows: [], items: [], sectors: [] } });
  });

  await page.goto('http://127.0.0.1:8791/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);
  await page.waitForLoadState('load');
  await page.waitForTimeout(600);

  // ── Lazy. The Market page's own card asks for six rows; the tab asks for none
  const fromTab = () => asked.filter(q => /limit=60/.test(q));
  assert.equal(fromTab().length, 0, 'the lists must not load before the tab is shown');
  assert.equal(bookCalls, 0, 'the Market page no longer reads the one-year book for a count');

  await openTab(page, 'special');
  await page.locator('#dt-root .dt-row').first().waitFor({ state: 'visible' });
  assert.equal(fromTab().length, 1);
  assert.equal(bookCalls, 0, 'the one-year book is not read until it is opened');

  // ── The tab says what it is, and opens on the latest session's spikes ─────
  assert.match(await page.locator('#view-special .tabhead h2').innerText(), /Delivery trends/);
  assert.match(await page.locator('.dt-asof').innerText(), /Session of Thu 19 Nov 2026/);
  const rows = page.locator('#dt-root .dt-list .dt-row');
  assert.equal(await rows.count(), trends.views.today.rows.length);
  assert.equal(await rows.first().getAttribute('data-sym'), 'RELIANCE', 'most unusual first');
  assert.match(await rows.first().locator('summary').innerText(), /4\.5×[\s\S]*₹252 cr vs ₹56\.0 cr[\s\S]*60%[\s\S]*\+3\.0%/);
  // The header and the rows are one grid: the columns must line up.
  const xs = sel => page.locator(sel).evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().right)));
  assert.deepEqual(await xs('.dt-head > span'), await xs('.dt-row:first-of-type > summary > span'));
  await page.screenshot({ path: path.join(output, 'today.png') });

  // ── A row opens into the arithmetic and a way to every session ───────────
  await rows.first().locator('summary').click();
  assert.match(await rows.first().locator('.dt-open').innerText(),
    /₹252 cr of shares were taken to delivery, 4\.5× its usual ₹56\.0 cr day, as the price rose 3\.0%/);
  assert.equal(await rows.first().locator('.dt-links a').getAttribute('href'), 'stock.html?ticker=RELIANCE&pane=deliv');
  await page.screenshot({ path: path.join(output, 'today-open.png') });

  // ── Direction filters in place ───────────────────────────────────────────
  await page.locator('#dt-root [data-dir="down"]').click();
  assert.equal(await rows.count(), trends.views.today.rows.filter(r => r.chg_pct < 0).length);
  assert.equal(await rows.first().getAttribute('data-sym'), 'TCS');
  assert.equal(await page.locator('#dt-root [data-dir="down"]').getAttribute('aria-pressed'), 'true');
  await page.locator('#dt-root [data-dir="all"]').click();

  // ── The other two lists, with no further request ─────────────────────────
  await page.locator('#dt-root [data-view="week"]').click();
  assert.ok((await rows.evaluateAll(els => els.map(e => e.dataset.sym))).includes('LT'));
  assert.match(await page.locator('.dt-rule').innerText(), /three of the five have to/);
  await page.screenshot({ path: path.join(output, 'week.png') });
  await page.locator('#dt-root [data-view="quiet"]').click();
  assert.equal(await rows.first().getAttribute('data-sym'), 'ITC');
  assert.equal(await page.locator('#dt-root [data-dir]').count(), 0, 'a still price has no direction to filter');
  assert.equal(fromTab().length, 1, 'switching lists must not refetch');

  // ── The floor is the one control that goes back to the server ────────────
  await page.locator('#dt-root [data-view="today"]').click();
  await page.locator('#dt-root [data-floor="50"]').click();
  await page.waitForFunction(() => document.querySelector('#dt-root [data-floor="50"]').classList.contains('active'));
  assert.equal(fromTab().length, 2);
  assert.match(fromTab()[1], /min_turnover_cr=50/);
  assert.equal(await page.locator('#dt-root [data-view="today"]').getAttribute('aria-pressed'), 'true', 'the list in view survives a refetch');

  // ── Industries ───────────────────────────────────────────────────────────
  assert.match(await page.locator('.dt-sectors').innerText(), new RegExp(trends.sectors[0].industry));
  assert.equal(await page.locator('.dt-sectors > .dt-sec').count(), 8);
  await page.locator('.dt-sectors').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(output, 'sectors.png') });

  // ── The old book: still there, read only when opened ─────────────────────
  assert.equal(await page.locator('#spbook').evaluate(el => el.open), false);
  await page.locator('#spbook > summary').click();
  await page.waitForFunction(() => /60 \/ 120 sessions/.test(document.getElementById('sprows').textContent));
  assert.equal(bookCalls, 1);
  await page.locator('#spbook > summary').click();

  // ── It reads on a phone, in both themes ──────────────────────────────────
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.locator('#view-special .tabhead').scrollIntoViewIfNeeded();
      await page.waitForTimeout(250);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `${width} ${theme}: horizontal page scroll`);
      const clipped = await page.locator('#dt-root .dt-row > summary .dt-fig b').evaluateAll(
        els => els.filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).length);
      assert.equal(clipped, 0, `${width} ${theme}: a figure is cut off`);
      await page.screenshot({ path: path.join(output, `${width}-${theme}.png`) });
      await page.locator('.dt-sectors').scrollIntoViewIfNeeded();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `${width} ${theme}: industries overflow`);
      await page.screenshot({ path: path.join(output, `${width}-${theme}-sectors.png`) });
    }
  }
  await page.evaluate(() => document.documentElement.dataset.theme = 'light');
  await page.setViewportSize({ width: 1280, height: 1000 });

  // ── A young store explains itself ────────────────────────────────────────
  payload = building;
  await page.locator('#dt-root [data-floor="10"]').click();
  await page.waitForFunction(() => /9 \/ 26 sessions/.test(document.getElementById('dt-root').textContent));
  assert.match(await page.locator('#dt-root').innerText(), /Reading the exchange’s delivery files/);
  assert.equal(await page.locator('#dt-root .dt-row').count(), 0);

  const relevant = errors.filter(e => /delivery-trends\.js|special\.js|doors\.js/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close(); server.close();
  console.log('Delivery trends: opens on this week, rows carry their arithmetic, the book waits to be asked');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
