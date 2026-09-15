/* The Ownership pane in a real Chromium, against a fixture shaped exactly like
   the /shareholding payload. No live calls.

   What this is actually guarding:
     · the pane must not draw Public alongside FII and DII — in the exchange's
       format Public CONTAINS them, and a chart of all four double-counts half
       the company. The bar and the rows render `split` only.
     · a derived figure must stay visibly derived.
     · every series must be identifiable without colour: legend, direct label
       and table, all three present.
     · phone through desktop, both themes, no horizontal scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/ownership');
fs.mkdirSync(output, { recursive: true });

const history = [
  { period: '2025-03-31', filed: '2025-04-21', promoter: 50.11, fii: 19.06, dii: 19.46, public_non_institutional: 11.27, holders: 4765728, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_1' },
  { period: '2025-06-30', filed: '2025-07-21', promoter: 50.07, fii: 19.21, dii: 19.80, public_non_institutional: 10.82, holders: 4435756, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_2' },
  { period: '2025-09-30', filed: '2025-10-17', promoter: 50.01, fii: 18.65, dii: 20.33, public_non_institutional: 10.91, holders: 4393764, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_3' },
  { period: '2025-12-31', filed: '2026-01-21', promoter: 50.01, fii: 19.09, dii: 20.18, public_non_institutional: 10.62, holders: 4206159, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_4' },
  { period: '2026-03-31', filed: '2026-04-21', promoter: 50.00, fii: 18.67, dii: 20.55, public_non_institutional: 10.69, holders: 4421289, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_5' },
  { period: '2026-06-30', filed: '2026-07-16', promoter: 50.48, fii: 17.20, dii: 21.19, public_non_institutional: 11.04, holders: 4651863, source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_6', revised: true }
];

const shareholding = {
  symbol: 'RELIANCE', available: true, period: '2026-06-30', filed: '2026-07-16',
  quarters_read: 6, latest_source: 'https://nsearchives.nseindia.com/corporate/xbrl/SHP_6',
  split: [
    { key: 'promoter', label: 'Promoters', pct: 50.48, holders: 47, change_qoq: 0.48, change_yoy: 0.41, holders_change_qoq: 0, derived: false, reported_absent: false },
    { key: 'fii', label: 'Foreign institutions (FII/FPI)', pct: 17.20, holders: 1542, change_qoq: -1.47, change_yoy: -2.01, holders_change_qoq: -40, derived: false, reported_absent: false },
    { key: 'dii', label: 'Domestic institutions (DII)', pct: 21.19, holders: 378, change_qoq: 0.64, change_yoy: 1.39, holders_change_qoq: 12, derived: true, reported_absent: false },
    { key: 'public_non_institutional', label: 'Public — non-institutional', pct: 11.04, holders: 4649821, change_qoq: 0.35, change_yoy: 0.22, holders_change_qoq: 230574, derived: false, reported_absent: false },
    { key: 'government', label: 'Government', pct: 0.10, holders: 74, change_qoq: 0, change_yoy: 0, holders_change_qoq: 0, derived: false, reported_absent: false }
  ],
  totals: { holders: 4651863, holders_change_qoq: 230574, holders_change_yoy: -113865, shares: 13303071854, public_total_pct: 49.52, split_sums_to: 100.01, reconciles: true },
  history,
  names: {
    promoters: [
      { name: 'Srichakra Commercials LLP', pct: 11.12, kind: 'Body corporate / other', change_qoq: 0.02, new_in_table: false },
      { name: 'K D Ambani', pct: 0.24, kind: 'Individual', change_qoq: 0, new_in_table: false }
    ],
    public: [
      { name: 'Life Insurance Corporation of India', pct: 6.88, kind: 'Insurance', change_qoq: 0.08, new_in_table: false },
      { name: 'SBI Mutual Funds', pct: 2.62, kind: 'Mutual fund', change_qoq: -0.07, new_in_table: false },
      { name: 'ICICI Prudential Mutual Fund', pct: 1.76, kind: 'Mutual fund', change_qoq: null, new_in_table: true }
    ]
  },
  notes: [
    'For older quarters the exchange format reported a single Institutions line. The domestic figure there is the reported total less foreign institutions, and is marked as derived.',
    'Public shareholding as the exchange reports it (49.52%) includes foreign institutions, domestic institutions and non-institutional holders. The four lines above do not overlap and sum to 100.'
  ]
};

const analyze = {
  ticker: 'RELIANCE', name: 'Reliance Industries Limited', currency: 'INR', price: 1402.5,
  scoring: { score: 61, label: 'Watch', pillars: {}, checks: [] },
  profile: { sector: 'Energy', summary: 'Refining, retail and telecom.' },
  disclaimer: 'Educational tool.'
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
  await new Promise(r => server.listen(8771, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  let shareholdingCalls = 0;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/shareholding') { shareholdingCalls++; return route.fulfill({ json: shareholding }); }
    if (u.pathname === '/analyze') return route.fulfill({ json: analyze });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });

  await page.goto('http://127.0.0.1:8771/stock.html?ticker=RELIANCE', { waitUntil: 'domcontentloaded' });
  await page.locator('#pane-btn-owners').waitFor();

  // Nothing is fetched until the pane is asked for.
  assert.equal(shareholdingCalls, 0, 'ownership must not load before its pane is opened');

  await page.locator('#pane-btn-owners').click();
  await page.locator('.own-rows .own-row').first().waitFor();
  assert.equal(shareholdingCalls, 1);

  // Lead with the finding: the biggest mover, named, before any chart.
  const lead = await page.locator('.own-lead').innerText();
  assert.match(lead, /Foreign institutions/);
  assert.match(lead, /fell 1\.47 percentage points/);

  // THE DOUBLE-COUNT GUARD. The reported public total (49.52) must never be a
  // row or a bar segment beside the categories it contains.
  const rowLabels = await page.locator('.own-rows .own-row .k').allInnerTexts();
  assert.equal(rowLabels.length, 5);
  assert.ok(!rowLabels.some(t => /^Public shareholding/i.test(t.trim())));
  assert.equal(await page.locator('.own-bar .seg').count(), 5);
  const segSum = await page.locator('.own-bar').evaluate(bar =>
    [...bar.querySelectorAll('.seg')].reduce((a, s) => a + parseFloat(s.style.flex), 0));
  assert.ok(Math.abs(segSum - 100) < 0.2, `bar segments sum to ${segSum}, not 100`);
  // The overlap is explained in prose exactly once.
  assert.match(await page.locator('.own-notes').innerText(), /do not overlap and sum to 100/);

  // A derived figure stays visibly derived.
  const diiRow = page.locator('.own-rows .own-row', { hasText: 'Domestic institutions' });
  assert.match(await diiRow.innerText(), /derived/i);

  // Identity never rests on colour: legend, direct labels and a table.
  assert.equal(await page.locator('.own-legend .lg').count(), 4);
  assert.equal(await page.locator('.own-chart .oll').count(), 4);
  // textContent, not innerText: innerText is an HTML concept and comes back
  // empty for an SVG <text>, which would make this assertion pass vacuously.
  const labelText = (await page.locator('.own-chart').evaluate(
    svg => [...svg.querySelectorAll('.oll')].map(t => t.textContent))).join(' ');
  for (const s of ['Promoters', 'DII', 'FII', 'Public']) {
    assert.ok(labelText.includes(s), `direct label missing: ${s} (got "${labelText}")`);
  }
  await page.locator('.own-more > summary').click();
  assert.equal(await page.locator('.own-table tbody tr').count(), 6);
  assert.match(await page.locator('.own-table tbody tr').first().innerText(), /2026-06-30/);
  assert.match(await page.locator(".own-table tbody tr").first().innerText(), /revised/i);

  // Axis ticks must be round numbers a reader can do arithmetic against.
  const yticks = await page.locator('.own-chart').evaluate(
    svg => [...svg.querySelectorAll('.oyl')].map(t => t.textContent));
  for (const t of yticks) {
    assert.ok(/^\d+(\.\d)?$/.test(t), `tick not a plain number: ${t}`);
    assert.equal(Number(t) % 5, 0, `tick ${t} is not a round step`);
  }

  // One percentage axis, never two.
  assert.ok(await page.locator(".own-chart .oyl").count() >= 3);

  // Named holders, and a holder new to the table labelled as such rather than
  // as a purchase the filing does not evidence.
  assert.equal(await page.locator('.own-names').count(), 2);
  assert.match(await page.locator('.own-names').nth(1).innerText(), /new in table/);
  assert.match(await page.locator('.own-names').nth(0).innerText(), /Srichakra/);

  // Hover puts real numbers on screen.
  await page.locator('.own-chart .oh').nth(2).hover();
  assert.match(await page.locator('#own-read').innerText(), /2025-09-30/);
  assert.match(await page.locator('#own-read').innerText(), /FII 18\.65%/);

  // The chart keeps a readable floor width and scrolls inside its own box
  // rather than shrinking its labels to nothing on a phone.
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.waitForTimeout(60);
  const chartBox = await page.locator('.own-chart').boundingBox();
  assert.ok(chartBox.width >= 500, `chart squeezed to ${chartBox.width}px`);
  const wrapScrolls = await page.locator('.own-chartwrap').evaluate(
    n => n.scrollWidth > n.clientWidth);
  assert.ok(wrapScrolls, 'chart should scroll inside its own container on a phone');

  // Phone through desktop, both themes, no horizontal overflow.
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(60);
      const over = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 1, `horizontal overflow ${over}px at ${width}`);
      await page.screenshot({ path: path.join(output, `own-${width}-${theme}.png`), fullPage: width === 1280 });
    }
  }
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.evaluate(() => document.documentElement.dataset.theme = 'light');

  // The empty state says what is missing instead of rendering a blank panel.
  const page2 = await context.newPage();
  await context.route('**/shareholding*', route => route.fulfill({
    json: { symbol: 'XYZ', available: false, message: 'No shareholding filing could be read for XYZ right now.', split: [], history: [], names: { promoters: [], public: [] }, notes: [] }
  }));
  await page2.goto('http://127.0.0.1:8771/stock.html?ticker=XYZ', { waitUntil: 'domcontentloaded' });
  await page2.locator('#pane-btn-owners').click();
  await page2.locator('.own-empty').waitFor();
  assert.match(await page2.locator('.own-empty').innerText(), /No shareholding filing/);
  assert.equal(await page2.locator('.own-bar').count(), 0);

  const relevant = errors.filter(e => /stock\.js/.test(e));
  assert.deepEqual(relevant, []);

  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({
    viewports: [320, 390, 768, 1280], themes: ['light', 'dark'],
    lazyLoaded: true, noDoubleCount: true, derivedLabelled: true,
    legendAndDirectLabelsAndTable: true, hoverReadout: true,
    emptyState: true, errors
  }, null, 2));

  await browser.close(); server.close();
  console.log('Ownership pane Chromium checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
