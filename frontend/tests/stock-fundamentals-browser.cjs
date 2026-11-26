/* The Financials section in a real Chromium, against a fixture produced by the
   real backend module (see backend/tests/make_fundamentals_fixture.py). No
   live calls.

   What this is actually guarding:
     · IT OPENS ON PICTURES, NOT PROSE. A row of figures, a chart, a split of
       ₹100, and the statement behind a toggle. No sentence, no paragraph
       about accounting bases, no caption over a table.
     · A BAR STARTS AT ZERO, and a quarter that lost money hangs below the
       line. A chart that cropped its axis would turn a 5% rise into a cliff.
     · ONE ACCOUNTING BASIS. Reliance files consolidated and standalone results
       for the same quarter and they differ by more than a factor of two. The
       basis is named on screen and the numbers match it.
     · NO PERCENTAGE ACROSS ZERO. A quarter that turned a loss into a profit
       reads as words, on the card and in the table, never as a percentage.
     · THE COLOUR OF A CHANGE MEANS SOMETHING. Borrowings going up are not
       green; a cost going up is not green either.
     · the statement stays readable on a phone: the line item and the change
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

  let asked = '';
  page.on('request', r => { if (new URL(r.url()).pathname === '/fundamentals') asked = r.url(); });
  await page.locator('#pane-btn-funda').click();
  await page.locator('#funda-body .kp').first().waitFor();
  assert.equal(calls, 1);
  // Two years, so four quarters can be set against the same quarter a year earlier.
  assert.match(asked, /quarters=8/);
  await page.locator('#pane-btn-funda').click();
  assert.equal(calls, 1, 'reopening the pane must not refetch');

  // ── PICTURES, NOT PROSE ──────────────────────────────────────────────────
  assert.equal(await page.locator('#pane-funda .own-lead, #pane-funda .own-asof, #pane-funda .fu-cap').count(), 0,
    'a sentence or a caption is back above the financials');
  assert.equal(await page.locator('#pane-funda .own-notes').count(), 0, 'method notes are back under the financials');
  // The basis, the unit and the filing are three chips.
  const meta = await page.locator('#fn-meta').innerText();
  assert.match(meta, /consolidated/i);
  assert.match(meta, /₹ crore/i);
  assert.match(await page.locator('#fn-meta a').getAttribute('href'), /nseindia/);
  // The statement is there and folded.
  assert.equal(await page.locator('#funda-body .fn-more').getAttribute('open'), null);

  // The figures: each with its latest value and its change on the year.
  const cards = page.locator('#funda-body .kp');
  assert.deepEqual((await cards.locator('.kp-l').allInnerTexts()).map(t => t.toLowerCase()),
    ['revenue', 'ebitda', 'net profit', 'eps']);
  // A CARD'S HEADLINE FIGURE IS A METRIC, so it is in the display face
  // (Fraunces, at the 22px heading size) like every other metric card. A
  // chart's title is a card title, and stays in the interface sans.
  assert.match(await cards.nth(0).locator('.kp-v').evaluate(el => getComputedStyle(el).fontFamily), /^"?Fraunces/);
  assert.match(await page.locator('#funda-body .fc h3').evaluate(
    el => getComputedStyle(el).fontFamily), /^"?Inter/, 'a chart title is in the display serif');
  // Each card carries its own small trend, drawn as a line.
  assert.equal(await cards.locator('.kp-s svg path.kp-ln').count(), 4);
  const rev = cards.nth(0);
  assert.match(await rev.locator('.kp-v').innerText(), /₹2\.69L cr/);
  assert.match(await rev.locator('.kp-c').innerText(), /10\.5%\s*YoY/i);
  assert.ok(await rev.locator('.mv').evaluate(el => el.classList.contains('up')));
  assert.equal(await rev.getAttribute('aria-pressed'), 'true');
  // The quarter that turned a loss into a profit says so in words.
  const patChip = await cards.nth(2).locator('.kp-c').innerText();
  assert.match(patChip, /to profit/i);
  assert.ok(!/%/.test(patChip), 'a loss turning into a profit is not a percentage');

  // The chart: one bar a quarter, every one standing on zero.
  const chart = page.locator('#funda-body .fc');
  assert.equal(await chart.locator('h3').innerText(), 'Revenue');
  assert.equal(await chart.locator('.fc-c[data-i]').count(), 6);
  const want = fundamentals.rows.slice().reverse().map(r => r.values.revenue);
  const got = await chart.locator('.fc-c[data-i]').evaluateAll(cols =>
    cols.map(c => parseFloat(c.style.getPropertyValue('--h'))));
  got.forEach((h, i) => assert.ok(Math.abs(h / got[5] - want[i] / want[5]) < 0.01,
    `bar ${i} is ${(h / got[5]).toFixed(3)} of the latest; its revenue is ${(want[i] / want[5]).toFixed(3)}`));
  // Slim bars against a scale that starts at zero: never the fat blocks.
  const barWidths = await chart.locator('.fc-c[data-i] > i').evaluateAll(b => b.map(x => x.getBoundingClientRect().width));
  assert.ok(Math.max(...barWidths) <= 28, 'a bar is ' + Math.max(...barWidths) + 'px wide');
  const ticks = await chart.locator('.fc-grid b').allInnerTexts();
  assert.ok(ticks.includes('0') && ticks.length >= 3, 'the scale reads ' + ticks);
  assert.ok(ticks.filter(t => t !== '0').every(t => /L$/.test(t)), 'one axis, two styles of figure: ' + ticks);
  // The latest quarter is read out above it, and the one under the pointer replaces it.
  assert.match(await chart.locator('.fc-read').innerText(), /Q1 FY27[\s\S]*2\.69L cr[\s\S]*10\.5%/);
  await chart.locator('.fc-c[data-i="0"]').hover();
  assert.match(await chart.locator('.fc-read').innerText(), /Q4 FY25/);
  // A bar is a button: the keyboard reads a quarter out as well.
  await chart.locator('.fc-c[data-i="3"]').focus();
  assert.match(await chart.locator('.fc-read').innerText(), /Q3 FY26/);

  // The pointer gone, the latest quarter is back.
  await page.mouse.move(5, 5);
  await page.locator('#funda-body .fc h3').focus().catch(() => {});
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await chart.locator('.fc-c[data-i="1"]').hover();
  await page.mouse.move(5, 5);
  assert.match(await chart.locator('.fc-read').innerText(), /Q1 FY27/);

  // The margins: two lines on one scale, named, the pointed-at quarter read out.
  const margins = page.locator('#funda-body .lc');
  assert.equal(await margins.locator('path.lc-l').count(), 2);
  assert.match(await margins.locator('.fc-read').innerText(), /Q1 FY27[\s\S]*Operating\s*17\.1%[\s\S]*Net\s*8\.3%/);
  await margins.locator('.lc-c[data-i="3"]').hover();
  assert.match(await margins.locator('.fc-read').innerText(), /Q3 FY26/);

  // Where the money went: every amount on the right comes back to revenue and
  // other income, and what was kept is named.
  const flow = page.locator('#funda-body .mf');
  await flow.locator('svg path.mf-r').first().waitFor();
  const latest = fundamentals.rows[0].values;
  const leaves = (await flow.locator('.mf-c li b').allInnerTexts()).map(t => /L/.test(t) ? num(t) * 1e5 : num(t));
  const whole = (latest.revenue + latest.other_income) / 1e7;
  assert.ok(Math.abs(leaves.reduce((x, y) => x + y, 0) / whole - 1) < 0.01,
    `the flow's parts come to ${leaves.reduce((x, y) => x + y, 0)} of ${whole}`);
  assert.match(await flow.locator('.mf-c li.net').innerText(), /Net profit[\s\S]*22,290 cr/);
  assert.match(await flow.locator('.mf-a').innerText(), /Revenue[\s\S]*2\.69L cr/);
  assert.match(await flow.locator('.mf-plot').getAttribute('aria-label'), /Net profit ₹22,290 cr/);
  // On a wide screen the flow stands in for the single bar; neither is lost.
  assert.equal(await page.locator('#funda-body .sp').isVisible(), false);

  // Another figure, and the chart is about that one. The loss hangs below the line.
  await cards.nth(2).click();
  assert.equal(await page.locator('#funda-body .fc h3').innerText(), 'Net profit');
  assert.equal(await cards.nth(2).getAttribute('aria-pressed'), 'true');
  assert.equal(await cards.nth(0).getAttribute('aria-pressed'), 'false');
  assert.equal(await page.locator('#funda-body .fc .fc-c.neg').count(), 1,
    'the loss-making quarter is not drawn as a loss');
  assert.equal(calls, 1, 'choosing a figure asked the API again');

  // Where each ₹100 went: the parts come back to the whole.
  const parts = (await page.locator('#funda-body .sp .sp-k b').allTextContents()).map(num);
  assert.ok(parts.length >= 4);
  assert.ok(Math.abs(parts.reduce((x, y) => x + y, 0) - 100) < 0.6, `the parts of ₹100 come to ${parts}`);

  // ── The statement, opened ────────────────────────────────────────────────
  await page.locator('#funda-body .fn-more > summary').click();
  await page.locator('#funda-body .fu-table').first().waitFor();

  // THE BASIS GUARD. The fixture's standalone revenue is 45% of consolidated,
  // so a mixed series is arithmetically detectable here.
  const revenueRow = page.locator('.fu-table tbody tr', { hasText: 'Revenue from operations' }).first();
  const revenueCells = (await revenueRow.locator('td.tnum:not(.fu-ch)').allInnerTexts()).map(num);
  assert.equal(revenueCells.length, 6, 'six quarters of revenue');
  const lo = Math.min(...revenueCells), hi = Math.max(...revenueCells);
  assert.ok(hi / lo < 1.6,
    `revenue spans ${lo}–${hi}: that is two accounting bases, not one company`);
  assert.ok(Math.abs(revenueCells[0] - 269496) < 2,
    `latest revenue reads ${revenueCells[0]}, expected the consolidated 2,69,496 crore`);
  assert.match(await page.locator('.fu-table').first().locator('caption').textContent(), /consolidated/i);

  // THE PERCENTAGE-ACROSS-ZERO GUARD, in the table as on the card.
  const patRow = page.locator('.fu-table tbody tr', { hasText: 'Profit after tax' }).first();
  const yoyCell = patRow.locator('td.fu-ch').first();
  assert.match(await yoyCell.innerText(), /to profit/i);
  assert.ok(!/%/.test(await yoyCell.innerText()),
    'a loss turning into a profit is not a percentage');
  assert.ok(await yoyCell.evaluate(el => el.classList.contains('word')));

  // The tax line turned positive in the same quarter, and must NOT borrow the
  // profit vocabulary: a tax credit becoming a tax charge is not a company
  // turning profitable. Matched on the row label exactly — "Tax" is a
  // substring of "Profit before tax".
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
  // A cost that went up is not good news: its change carries no colour.
  const costYoy = page.locator('.fu-table tbody tr', { hasText: 'Employee cost' }).first().locator('td.fu-ch').first();
  assert.match(await costYoy.innerText(), /%$/);
  assert.ok(await costYoy.evaluate(el => !el.classList.contains('up') && !el.classList.contains('dn')),
    'a rise in a cost is coloured as though it were a rise in profit');

  // Both change columns say which period they compare against.
  const changeHeads = await page.locator('.fu-table thead th.fu-chh').allInnerTexts();
  assert.equal(changeHeads.length, 2, 'year-on-year and sequential');
  assert.match(changeHeads[0], /Q1 FY26/);   // the same quarter a year back
  assert.match(changeHeads[1], /Q4 FY26/);   // the quarter just gone

  // Every P&L line the payload declares is drawn; a silently dropped row is a
  // blank the reader reads as a zero.
  const wantLines = fundamentals.lines.map(l => l.label);
  const gotLines = await page.evaluate(() =>
    [...document.querySelectorAll('.fu-table:not(.fu-ratios) tbody th[scope="row"]')]
      .map(th => th.firstChild.textContent.trim()));
  for (const l of wantLines)
    assert.ok(gotLines.includes(l), `missing P&L line ${l}`);

  // Ratios: every one defined, each with its arithmetic written out.
  const ratioRows = page.locator('.fu-ratios tbody tr');
  assert.equal(await ratioRows.count(), fundamentals.ratio_defs.length);
  const ratiosText = await page.locator('.fu-ratios').innerText();
  for (const r of fundamentals.ratio_defs) {
    assert.ok(ratiosText.includes(r.label), `missing ratio ${r.label}`);
    assert.ok(ratiosText.includes(r.formula), `ratio ${r.label} does not show its formula`);
  }
  assert.match(await page.locator('.fu-ratios tbody tr', { hasText: 'Interest cover' })
    .first().locator('th').innerText(), /×/);
  const opm = page.locator('.fu-ratios tbody tr', { hasText: 'Operating margin' }).first();
  assert.ok(Math.abs(num(await opm.locator('td.fu-now').innerText()) - 17.08) < 0.05);
  assert.ok(await page.locator('.fu-spark').count() >= 4);
  // EPS is rupees per share while the column header says crore.
  assert.match(await page.locator('.fu-table tbody tr', { hasText: 'EPS (basic)' })
    .first().locator('th').innerText(), /per share/i);

  // ── Balance sheet ────────────────────────────────────────────────────────
  // Crore values printed as crore (not divided again), and a line the company
  // never filed is not drawn as a card or a row of dashes.
  // The industry comparison sits with the named peers, so opening the
  // financials reads the balance sheet and cash flow and nothing else.
  assert.equal(extras, 1);
  await page.locator('#fn-views [data-fv="balance"]').click();
  const bal = page.locator('#funda-position .fn-view[data-view="balance"]');
  await bal.locator('.kp').first().waitFor();
  assert.equal(await page.locator('#funda-body').isVisible(), false, 'two views are showing at once');
  const balLabels = (await bal.locator('.kp-l').allInnerTexts()).map(t => t.toLowerCase());
  assert.ok(balLabels.includes('total assets') && balLabels.includes('borrowings'), String(balLabels));
  assert.ok(!balLabels.includes('deposits'), 'a line never filed got a card');
  assert.match(await bal.locator('.kp').first().locator('.kp-v').innerText(), /₹19\.50L cr/);
  // Borrowings rose. That is shown as a rise and not in the colour of good news.
  const debt = bal.locator('.kp', { hasText: /borrowings/i }).locator('.mv');
  assert.ok(await debt.evaluate(el => el.classList.contains('up') && el.classList.contains('inv')),
    'a rise in borrowings is drawn as good news');
  // Total assets have no good direction at all.
  assert.ok(await bal.locator('.kp').first().locator('.mv').evaluate(el => el.classList.contains('plain')));
  // What funds it: one bar a balance sheet.
  assert.equal(await bal.locator('.sp .sp-r').count(), 4);
  assert.equal(await bal.locator('.mf').count(), 0);
  await bal.locator('.fn-more > summary').click();
  const bsTable = bal.locator('.fu-stmt');
  await bsTable.waitFor();
  const bsHead = await bsTable.locator('thead th').allInnerTexts();
  // Headers are uppercased by CSS; compare the words.
  assert.deepEqual(bsHead.slice(1).map(t => t.toUpperCase()),
    ['MAR 2026', 'SEP 2025', 'MAR 2025', 'SEP 2024']);
  const assets = await bsTable.locator('tbody tr', { hasText: 'Total assets' })
    .locator('td').allInnerTexts();
  assert.equal(num(assets[0]), 1950000, `total assets read ${assets[0]}`);
  assert.equal(await bsTable.locator('tbody tr', { hasText: 'Deposits' }).count(), 0);

  // ── Cash flow ────────────────────────────────────────────────────────────
  // Full years only — a half-year beside a year would read as a collapse.
  await page.locator('#fn-views [data-fv="cash"]').click();
  const cash = page.locator('#funda-position .fn-view[data-view="cash"]');
  await cash.locator('.kp').first().waitFor();
  assert.equal(await bal.isVisible(), false);
  assert.equal(await cash.locator('.fc .fc-c[data-i]').count(), 3);
  assert.match(await cash.locator('.kp[data-metric="fcf"] .kp-v').innerText(), /₹47,000 cr/);
  // Cash left after investing: the second bar starts where the third ends.
  const bridge = await cash.locator('.br .br-t i').evaluateAll(b => b.map(x => [parseFloat(x.style.left), parseFloat(x.style.width)]));
  assert.equal(bridge.length, 3);
  assert.ok(Math.abs(bridge[1][0] - bridge[2][1]) < 0.01 && Math.abs(bridge[1][0] + bridge[1][1] - 100) < 0.01, String(bridge));
  assert.ok(Math.abs(bridge[2][1] - 100 * 47000 / 178000) < 0.05);
  await cash.locator('.fn-more > summary').click();
  const cfTable = cash.locator('.fu-stmt');
  await cfTable.waitFor();
  const cfHead = await cfTable.locator('thead th').allInnerTexts();
  assert.deepEqual(cfHead.slice(1).map(t => t.toUpperCase()), ['FY26', 'FY25', 'FY24']);
  const fcf = await cfTable.locator('tbody tr', { hasText: 'Free cash flow' }).first()
    .locator('td').allInnerTexts();
  assert.equal(num(fcf[0]), 47000);
  const conv = await cfTable.locator('tbody tr', { hasText: 'Cash conversion' })
    .locator('td').allInnerTexts();
  assert.equal(num(conv[0]), 209.42);
  assert.equal(calls, 1);
  assert.equal(extras, 1, 'switching between the three views asked the API again');
  await page.locator('#fn-views [data-fv="income"]').click();
  await page.locator('#funda-body .kp').first().waitFor();

  // ── Against the industry median ─────────────────────────────────────────
  // In the Peers section, under the named table, and read only when that
  // section is opened. The industry is named, the median printed beside the
  // company's own figure, and the rank is "N of M" peers — never a verdict.
  assert.equal(await page.locator('#funda-peers .fu-peers').count(), 0,
    'the industry comparison loaded before its section was opened');
  await page.locator('#pane-btn-peers').click();
  await page.locator('#funda-peers .fu-peers').waitFor();
  assert.equal(extras, 2);
  assert.match(await page.locator('#funda-peers .fu-cap').innerText(), /Refineries & Marketing/);
  const opmRow = page.locator('#funda-peers tbody tr', { hasText: 'Operating margin' });
  const opmCells = await opmRow.locator('td').allInnerTexts();
  assert.equal(opmCells[0], '17.1%');
  assert.equal(opmCells[1], '11.3%', 'the median of six peers at 7.5 to 15% is 11.25');
  assert.equal(opmCells[2], '6 of 6');
  // How much of the industry was read is a method note: folded, and there.
  assert.match(await page.locator('#funda-peers details.own-notes').textContent(),
    /6 of the 6 other companies/);
  assert.match(await page.locator('#funda-peers tbody tr', { hasText: 'Debt to equity' })
    .locator('th').innerText(), /lower is better/i);
  await page.locator('#pane-btn-funda').click();
  assert.equal(calls, 1, 'returning to the financials must not refetch');

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
      // The flow needs three columns and two gutters; where there is no room
      // the single bar says the same thing. Exactly one of them, never neither.
      const pictures = [await page.locator('#funda-body .mf').isVisible(), await page.locator('#funda-body .sp').isVisible()];
      assert.deepEqual(pictures, width > 900 ? [true, false] : [false, true], `at ${width}: ${pictures}`);
      // No label runs outside its card.
      const spill = await page.evaluate(() => {
        const out = [];
        document.querySelectorAll('#funda-body .card').forEach(card => {
          if (!card.offsetParent) return;
          const c = card.getBoundingClientRect();
          card.querySelectorAll('.fc-x, .fc-n, .mf-c li, .mf-a, .mf-b, .fc-grid b, .lc-k').forEach(el => {
            const r = el.getBoundingClientRect();
            if (!r.width || getComputedStyle(el).opacity === '0') return;
            if (r.left < c.left - 1 || r.right > c.right + 1) out.push(el.className + ' ' + el.textContent.trim());
          });
        });
        return out;
      });
      assert.deepEqual(spill, [], `at ${width} a label runs outside its card`);

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
