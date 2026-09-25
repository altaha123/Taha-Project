/* The Fundamentals pane in a real Chromium, against a fixture produced by the
   real backend module (see backend/tests/make_fundamentals_fixture.py). No
   live calls.

   What this is actually guarding:
     · ONE ACCOUNTING BASIS. Reliance files consolidated and standalone results
       for the same quarter and they differ by more than a factor of two. A
       page that mixes them shows that difference as growth, and looks entirely
       normal while doing it. The basis must be named on screen and the numbers
       must match it.
     · NO PERCENTAGE ACROSS ZERO. A quarter that turned a loss into a profit
       must read as words, never as a percentage — a percentage there reports a
       recovery as a collapse.
     · the table must stay readable on a phone: the line item and the change
       must be reachable without losing the row.
     · phone through desktop, both themes, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/fundamentals');
fs.mkdirSync(output, { recursive: true });

const fundamentals = JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/fundamentals-reliance.json'), 'utf8'));

// Balance sheet, cash flow and the industry comparison — also produced by the
// real module, from a temporary store (make_fundamentals_fixture.stored()).
const position = JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/fundamentals-reliance-position.json'), 'utf8'));
const peers = JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/fundamentals-reliance-peers.json'), 'utf8'));

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

const num = t => Number(String(t).replace(/[^0-9.\-]/g, ''));

(async () => {
  await new Promise(r => server.listen(8773, '127.0.0.1', r));
  // CHROMIUM_PATH lets this run against a Chromium that is already on the
  // machine. CI installs its own and leaves it unset.
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  let calls = 0, extras = 0;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/fundamentals') { calls++; return route.fulfill({ json: fundamentals }); }
    if (u.pathname === '/fundamentals/position') { extras++; return route.fulfill({ json: position }); }
    if (u.pathname === '/fundamentals/peers') { extras++; return route.fulfill({ json: peers }); }
    if (u.pathname === '/analyze') return route.fulfill({ json: analyze });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });

  await page.goto('http://127.0.0.1:8773/stock.html?ticker=RELIANCE', { waitUntil: 'domcontentloaded' });
  await page.locator('#pane-btn-funda').waitFor();

  // The pane sits after Ownership, which is where it was asked to sit.
  const order = await page.evaluate(() =>
    [...document.querySelectorAll('.stk-pane-btn')].map(b => b.dataset.p));
  assert.equal(order[order.indexOf('owners') + 1], 'funda',
    `Fundamentals must follow Ownership, got ${order.join(',')}`);

  // Nothing is fetched until the pane is asked for. Six quarters is six
  // documents on the exchange; a stock page must not pull them to show a price.
  assert.equal(calls, 0, 'fundamentals must not load before its pane is opened');
  assert.equal(extras, 0, 'nor the balance sheet or the industry comparison');

  await page.locator('#pane-btn-funda').click();
  await page.locator('.fu-table').first().waitFor();
  assert.equal(calls, 1);
  await page.locator('#pane-btn-funda').click();
  assert.equal(calls, 1, 'reopening the pane must not refetch');

  // ── THE BASIS GUARD ──────────────────────────────────────────────────────
  // The basis is stated, the other one is acknowledged, and the figures on
  // screen are the ones from that basis. The fixture's standalone revenue is
  // 45% of consolidated, so a mixed series is arithmetically detectable here.
  const asof = await page.locator('#pane-funda .own-asof').innerText();
  assert.match(asof, /consolidated/i);
  assert.match(asof, /also files standalone/i);
  assert.match(asof, /6 quarters read/);

  const revenueRow = page.locator('.fu-table tbody tr', { hasText: 'Revenue from operations' }).first();
  const revenueCells = (await revenueRow.locator('td.tnum:not(.fu-ch)').allInnerTexts()).map(num);
  // Latest plus five older quarters, all within a plausible band of each
  // other. A standalone row among them would sit at ~45% of its neighbours.
  assert.equal(revenueCells.length, 6, 'six quarters of revenue');
  const lo = Math.min(...revenueCells), hi = Math.max(...revenueCells);
  assert.ok(hi / lo < 1.6,
    `revenue spans ${lo}–${hi}: that is two accounting bases, not one company`);
  assert.ok(Math.abs(revenueCells[0] - 269496) < 2,
    `latest revenue reads ${revenueCells[0]}, expected the consolidated 2,69,496 crore`);

  // ── THE PERCENTAGE-ACROSS-ZERO GUARD ─────────────────────────────────────
  // The fixture's June 2025 quarter is a loss, so profit after tax this
  // quarter is a turnaround. It must read in words.
  const patRow = page.locator('.fu-table tbody tr', { hasText: 'Profit after tax' }).first();
  const yoyCell = patRow.locator('td.fu-ch').first();
  assert.match(await yoyCell.innerText(), /to profit/i);
  assert.ok(!/%/.test(await yoyCell.innerText()),
    'a loss turning into a profit is not a percentage');
  assert.ok(await yoyCell.evaluate(el => el.classList.contains('word')));
  // And the lead sentence says the same thing, in prose, with no percentage.
  const lead = await page.locator('#pane-funda .own-lead').innerText();
  assert.match(lead, /profit after tax turned from a loss into a profit/i);
  assert.match(lead, /Revenue grew 10\.5%/);
  assert.match(lead, /against Q1 FY26/);

  // The tax line turned positive in the same quarter, and must NOT borrow the
  // profit vocabulary: a tax credit becoming a tax charge is not a company
  // turning profitable.
  // Matched on the row label exactly — "Tax" is a substring of "Profit before
  // tax", and the loose match quietly tested the wrong row.
  const taxYoy = await page.evaluate(() => {
    const row = [...document.querySelectorAll('.fu-table tbody tr')]
      .find(tr => tr.querySelector('th').firstChild.textContent.trim() === 'Tax');
    return row && row.querySelector('td.fu-ch').textContent.trim();
  });
  assert.match(taxYoy || '', /to positive/i);

  // Where the base IS positive the percentage is shown, signed and toned.
  const revYoy = revenueRow.locator('td.fu-ch').first();
  assert.match(await revYoy.innerText(), /^\+?\-?\d+\.\d%$/);
  assert.ok(await revYoy.evaluate(el =>
    el.classList.contains('up') || el.classList.contains('dn')));

  // Both change columns, and both say which period they compare against, so
  // "+10.5%" is never a figure whose baseline the reader has to guess.
  const changeHeads = await page.locator('.fu-table thead th.fu-chh').allInnerTexts();
  assert.equal(changeHeads.length, 2, 'year-on-year and sequential');
  assert.match(changeHeads[0], /Q1 FY26/);   // the same quarter a year back
  assert.match(changeHeads[1], /Q4 FY26/);   // the quarter just gone

  // Every P&L line the payload declares is drawn; a silently dropped row is a
  // blank the reader reads as a zero.
  const wantLines = fundamentals.lines.map(l => l.label);
  // First text node only: a row label may carry a unit note under it.
  const gotLines = await page.evaluate(() =>
    [...document.querySelectorAll('.fu-table:not(.fu-ratios) tbody th[scope="row"]')]
      .map(th => th.firstChild.textContent.trim()));
  for (const l of wantLines)
    assert.ok(gotLines.includes(l), `missing P&L line ${l}`);

  // Ratios: every one defined, each with its arithmetic written out. "OPM"
  // means nothing to a reader who does not already know it.
  const ratioRows = page.locator('.fu-ratios tbody tr');
  assert.equal(await ratioRows.count(), fundamentals.ratio_defs.length);
  const ratiosText = await page.locator('.fu-ratios').innerText();
  for (const r of fundamentals.ratio_defs) {
    assert.ok(ratiosText.includes(r.label), `missing ratio ${r.label}`);
    assert.ok(ratiosText.includes(r.formula), `ratio ${r.label} does not show its formula`);
  }
  // The unit is on the row, so the five older quarters are not bare numbers of
  // an unstated quantity.
  assert.match(await page.locator('.fu-ratios tbody tr', { hasText: 'Interest cover' })
    .first().locator('th').innerText(), /×/);
  // Operating margin is EBITDA over revenue and the fixture is built at 17.08%.
  const opm = page.locator('.fu-ratios tbody tr', { hasText: 'Operating margin' }).first();
  assert.ok(Math.abs(num(await opm.locator('td.fu-now').innerText()) - 17.08) < 0.05);
  // A trend is the question for a ratio, so it gets a mark as well as figures.
  assert.ok(await page.locator('.fu-spark').count() >= 4);

  // The basis is not only asserted in the summary line — the note above the
  // table repeats it, because the table is what gets screenshotted and shared.
  assert.match(await page.locator('.fu-cap').first().innerText(), /consolidated/i);
  // And the table carries an accessible name of its own.
  assert.match(await page.locator('.fu-table').first().locator('caption').innerText(),
    /consolidated/i);

  // EPS is rupees per share while the column header says crore. The row says
  // so on itself rather than leaving the reader to divide by a crore.
  assert.match(await page.locator('.fu-table tbody tr', { hasText: 'EPS (basic)' })
    .first().locator('th').innerText(), /per share/i);

  // Provenance: the filing it came from is one click away.
  assert.ok(await page.locator('#pane-funda .own-asof a[href*="nseindia"]').count() >= 1);

  // ── Against its industry ────────────────────────────────────────────────
  // The industry is named, the median printed beside the company's own
  // figure, and the rank is "N of M" peers — never a verdict.
  await page.locator('#funda-peers .fu-peers').waitFor();
  assert.match(await page.locator('#funda-peers .fu-cap').innerText(), /Refineries & Marketing/);
  const opmRow = page.locator('#funda-peers tbody tr', { hasText: 'Operating margin' });
  const opmCells = await opmRow.locator('td').allInnerTexts();
  assert.equal(opmCells[0], '17.1%');
  assert.equal(opmCells[1], '11.3%', 'the median of six peers at 7.5 to 15% is 11.25');
  assert.equal(opmCells[2], '6 of 6');
  assert.match(await page.locator('#funda-peers').innerText(), /6 of the 6 other companies/);
  assert.match(await page.locator('#funda-peers tbody tr', { hasText: 'Debt to equity' })
    .locator('th').innerText(), /lower is better/i);

  // ── Balance sheet and cash flow ─────────────────────────────────────────
  // Crore values printed as crore (not divided again), full years only in the
  // cash flow — a half-year beside a year would read as a collapse — and a
  // line the company never filed is not drawn as a row of dashes.
  await page.locator('#funda-position .fu-stmt').first().waitFor();
  assert.equal(extras, 2);
  const tables = page.locator('#funda-position .fu-stmt');
  assert.equal(await tables.count(), 2);
  const bsHead = await tables.nth(0).locator('thead th').allInnerTexts();
  // Headers are uppercased by CSS; compare the words.
  assert.deepEqual(bsHead.slice(1).map(t => t.toUpperCase()),
    ['MAR 2026', 'SEP 2025', 'MAR 2025', 'SEP 2024']);
  const assets = await tables.nth(0).locator('tbody tr', { hasText: 'Total assets' })
    .locator('td').allInnerTexts();
  assert.equal(num(assets[0]), 1950000, `total assets read ${assets[0]}`);
  assert.equal(await tables.nth(0).locator('tbody tr', { hasText: 'Deposits' }).count(), 0);
  const cfHead = await tables.nth(1).locator('thead th').allInnerTexts();
  assert.deepEqual(cfHead.slice(1).map(t => t.toUpperCase()), ['FY26', 'FY25', 'FY24']);
  const fcf = await tables.nth(1).locator('tbody tr', { hasText: 'Free cash flow' }).first()
    .locator('td').allInnerTexts();
  assert.equal(num(fcf[0]), 47000);
  const conv = await tables.nth(1).locator('tbody tr', { hasText: 'Cash conversion' })
    .locator('td').allInnerTexts();
  assert.equal(num(conv[0]), 209.42);

  // ── Phone through desktop, both themes ───────────────────────────────────
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(60);
      // The PAGE must not scroll sideways. The table may — it is inside its
      // own scroller, which is the point.
      const over = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 1, `horizontal page overflow ${over}px at ${width}`);

      const shot = await page.locator('#funda-body').boundingBox();
      await page.screenshot({
        path: path.join(output, `funda-${width}-${theme}.png`),
        fullPage: true,
        clip: shot
          ? { x: 0, y: Math.max(0, shot.y), width, height: Math.min(shot.height, 2600) }
          : undefined,
      });
    }
  }

  // On a phone the line item stays put while the quarters scroll, so a reader
  // who has scrolled to an older quarter still knows which row they are on.
  await page.setViewportSize({ width: 390, height: 900 });
  await page.evaluate(() => document.documentElement.dataset.theme = 'light');
  await page.waitForTimeout(60);
  const wrap = page.locator('.fu-wrap').first();
  assert.ok(await wrap.evaluate(el => el.scrollWidth > el.clientWidth + 20),
    'the table should scroll inside its own box on a phone');
  await wrap.evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await page.waitForTimeout(80);
  const pinned = await page.locator('.fu-table tbody th.fu-line').first().boundingBox();
  assert.ok(pinned && pinned.x >= -1 && pinned.x < 40,
    `line-item column drifted to x=${pinned && pinned.x} after scrolling`);
  await page.screenshot({
    path: path.join(output, 'funda-390-scrolled.png'),
    clip: { x: 0, y: 0, width: 390, height: 900 }
  });
  await page.setViewportSize({ width: 1280, height: 1000 });

  // ── A company with nothing to show ───────────────────────────────────────
  // Deliberately slow: the bug this covers only appears when the fetch takes
  // long enough for the loading placeholder to be seen, which is every CI
  // runner and almost no development machine.
  const page2 = await context.newPage();
  await context.route('**/fundamentals*', async route => {
    await new Promise(r => setTimeout(r, 700));
    route.fulfill({
      json: { symbol: 'XYZ', available: false, rows: [], lines: [],
              message: 'No quarterly results filing could be read for XYZ right now.' }
    });
  });
  await page2.goto('http://127.0.0.1:8773/stock.html?ticker=XYZ', { waitUntil: 'domcontentloaded' });
  await page2.locator('#pane-btn-funda').click();

  // While fetching, the pane says so — and that placeholder is NOT the empty
  // state. Conflating the two is what made the ownership test assert against
  // "Reading the filings…".
  const loading = page2.locator('#funda-body .own-empty.is-loading');
  await loading.waitFor();
  assert.match(await loading.innerText(), /Reading the results filings/i);

  const settled = page2.locator('#funda-body .own-empty:not(.is-loading)');
  await settled.waitFor();
  assert.match(await settled.innerText(), /No quarterly results filing/);
  assert.equal(await page2.locator('#funda-body .fu-table').count(), 0,
    'no table at all rather than an empty one');

  assert.deepEqual(errors, [], 'page errors: ' + errors.join('\n'));
  await browser.close();
  server.close();
  console.log('fundamentals pane ok — screenshots in ' + path.relative(process.cwd(), output));
})().catch(e => { console.error(e); process.exit(1); });
