/* The fund house portfolios view in a real Chromium, against fixtures produced
   by the real backend modules (backend/tests/make_funds_fixture.py).

   What is guarded here is the difference between this page and the investor
   one. They look alike and rest on opposite kinds of data, and a reader who
   carries assumptions from one to the other will be wrong:

     · COVERAGE MUST BE STATED. AMFI lists 53 fund houses and publishes a
       directory, not a feed. A page showing four of them while looking like
       it shows the industry is the failure mode, so the count read is on the
       page and an absent fund house is absent because it was not READ.
     · a debt holding in the same workbook must never appear as an equity
       position.
     · a holding whose ISIN is not on NSE's equity list must be shown
       separately, not dropped — otherwise the weights silently fail to
       reconcile against the fund's real book.
     · scheme weights must NOT be added together. A company held by two
       schemes has two weights of two different portfolios.
     · the monthly cadence and its lag must be on the page. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/funds');
fs.mkdirSync(output, { recursive: true });

const fx = n => JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/funds-' + n + '.json'), 'utf8'));

const directory = fx('directory');
const fund20 = fx('20');

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

const num = t => Number(String(t).replace(/[^0-9.\-]/g, ''));

async function openTab(page, id) {
  await page.waitForLoadState('load');
  // The homepage re-applies its default tab up to about a second after load,
  // so a view opened inside that window is silently hidden again.
  await page.waitForTimeout(1200);
  for (let attempt = 0; attempt < 6; attempt++) {
    await page.evaluate(t => window.AltahaNav.go('screener', t, true), id);
    try {
      await page.locator('#view-' + id).waitFor({ state: 'visible', timeout: 2000 });
      await page.waitForTimeout(400);
      if (await page.locator('#view-' + id).isVisible()) return;
    } catch (_) { /* retry */ }
  }
  assert.fail('could not open the ' + id + ' view');
}

(async () => {
  await new Promise(r => server.listen(8777, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  let directoryCalls = 0;
  page.on('pageerror', e => errors.push(String(e && (e.stack || e.message || e))));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    // An external <script src> answered with JSON throws "Unexpected token
    // ':'" — the stub's fault, and it would drown the page errors this checks.
    if (route.request().resourceType() === 'script') {
      return route.fulfill({ body: '', contentType: 'text/javascript' });
    }
    if (u.pathname === '/funds') { directoryCalls++; return route.fulfill({ json: directory }); }
    if (u.pathname === '/fund') return route.fulfill({ json: fund20 });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });

  await page.goto('http://127.0.0.1:8777/', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('load');
  await page.waitForTimeout(1200);
  assert.equal(directoryCalls, 0, 'the fund list must not load before its tab is opened');

  await openTab(page, 'funds');
  await page.locator('.iv-card').first().waitFor({ state: 'visible' });
  assert.ok(await page.locator('#view-funds').isVisible());
  assert.equal(directoryCalls, 1);

  // ── COVERAGE IS PART OF THE ANSWER ───────────────────────────────────────
  const cover = await page.locator('.iv-cover').first().innerText();
  assert.match(cover, new RegExp(String(directory.read) + '\\b'));
  assert.match(cover, /53 fund houses AMFI lists/);
  assert.match(cover, /has not been read/i,
    'an absent fund house must be absent because it was not read, not because it holds nothing');
  // The lag, before any portfolio is opened.
  assert.match(await page.locator('#funds-body').innerText(), /six weeks/i);
  assert.match(await page.locator('.iv-lead').innerText(), /No 1% floor/i);

  // ── One fund house ───────────────────────────────────────────────────────
  await page.locator('.iv-card').first().click();
  await page.locator('.iv-pos').first().waitFor();

  const asof = await page.locator('.iv-asof').innerText();
  assert.match(asof, /August 2026/);
  assert.match(asof, /six weeks/i);

  // ── A debt holding must never be an equity position ──────────────────────
  const listText = await page.locator('.iv-list').first().innerText();
  assert.ok(!/National Housing Bank/i.test(listText),
    'a debenture in the same workbook must not appear as an equity position');
  assert.match(listText, /RELIANCE/);
  assert.match(listText, /Reliance Industries Limited/);

  // ── Scheme weights are shown but NEVER summed ────────────────────────────
  // BHEL is held by two schemes, at 2.01% of one and 3.33% of the other. The
  // headline must be the rupee value, not 5.34%.
  const bhel = page.locator('.iv-pos', { hasText: 'BHEL' }).first();
  assert.match(await bhel.locator('.mv').innerText(), /2 schemes/);
  const headline = await bhel.locator('.iv-pos-head .vv').innerText();
  assert.match(headline, /₹/, 'the headline across a house is a rupee value');
  assert.ok(!/%/.test(headline),
    'two scheme weights of two different portfolios must not be added into one percentage');
  const weights = (await bhel.locator('.iv-parts .vv').allInnerTexts()).map(num);
  assert.deepEqual(weights.sort((a, b) => a - b), [2.01, 3.33]);
  // Each weight is attached to the scheme it belongs to.
  const bhelParts = await bhel.locator('.iv-parts').innerText();
  assert.match(bhelParts, /Large Cap Fund/);
  assert.match(bhelParts, /Mid Cap Fund/);

  // Positions are ranked by what the house actually holds, in rupees.
  const values = await page.locator('.iv-list').first()
    .locator('.iv-pos-head .vv').allInnerTexts();
  const nums = values.map(num);
  assert.deepEqual(nums, [...nums].sort((a, b) => b - a),
    'positions must be ranked by value across the house');

  // ── An unmatched ISIN is shown, not dropped ──────────────────────────────
  const other = page.locator('.iv-list.is-gone');
  assert.equal(await other.locator('.iv-pos').count(), 1);
  assert.match(await other.innerText(), /Gold ETF/);
  assert.match(await page.locator('.iv-sub').innerText(), /reconciled/i);
  assert.match(await page.locator('.iv-sub').innerText(), /rather than dropped/i);

  // ── The pack it came from is one click away ──────────────────────────────
  assert.ok(await page.locator('.iv-asof a[href*="barodabnpparibasmf"]').count() >= 1);

  // ── Phone through desktop, both themes ───────────────────────────────────
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(60);
      const over = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 1, `horizontal overflow ${over}px at ${width}`);
      const shot = await page.locator('#funds-body').boundingBox();
      await page.screenshot({
        path: path.join(output, `funds-${width}-${theme}.png`),
        fullPage: true,
        clip: shot
          ? { x: 0, y: Math.max(0, shot.y), width, height: Math.min(shot.height, 2600) }
          : undefined,
      });
    }
  }
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.evaluate(() => document.documentElement.dataset.theme = 'light');

  // ── Nothing read yet ─────────────────────────────────────────────────────
  const page2 = await context.newPage();
  await context.route('**/funds*', async route => {
    if (new URL(route.request().url()).pathname !== '/funds') return route.fallback();
    await new Promise(r => setTimeout(r, 700));
    route.fulfill({ json: { available: false, funds: [], read: 0,
                            listed_with_amfi: 53,
                            message: 'No fund house portfolio has been read yet.' } });
  });
  await page2.goto('http://127.0.0.1:8777/', { waitUntil: 'domcontentloaded' });
  await openTab(page2, 'funds');
  const loading = page2.locator('#funds-body .iv-empty.is-loading');
  try {
    await loading.waitFor({ timeout: 1500 });
    assert.match(await loading.innerText(), /Loading the fund houses/i);
  } catch (_) { /* already settled: the assertion below is the one that counts */ }
  const settled = page2.locator('#funds-body .iv-empty:not(.is-loading)');
  await settled.waitFor();
  assert.match(await settled.innerText(), /No fund house portfolio has been read/i);
  assert.equal(await page2.locator('#funds-body .iv-pos').count(), 0);

  assert.deepEqual(errors, [], 'page errors: ' + errors.join('\n'));
  await browser.close();
  server.close();
  console.log('fund house portfolios ok — screenshots in ' +
    path.relative(process.cwd(), output));
})().catch(e => { console.error(e); process.exit(1); });
