/* The results calendar, in a real browser.

   The submenu under Quarterly results: Yesterday, Today, Tomorrow, This week,
   Next week. What would fail silently:

     · a tab whose count disagrees with the rows it shows;
     · "today" taken from the reader's clock instead of the exchange's (IST);
     · a company whose board has met but whose filing has not arrived shown
       as filed — "Filed" must only ever mean the document is on NSE;
     · a filing the morning after the meeting listed under the wrong day;
     · a row that does not open the company's results;
     · an address (#research/results/tomorrow) that does not open its tab;
     · a company name rendered as markup;
     · an unreachable engine leaving the list on "Reading…" for ever.

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/results-calendar');
fs.mkdirSync(output, { recursive: true });

const day = (date, rows) => ({ date, rows,
  declared: rows.filter(r => r.status === 'declared').length,
  pending: rows.filter(r => r.status !== 'declared').length });

// The server's shape (results_calendar.calendar), on Wednesday 14 Oct 2026.
const CAL = {
  available: true, today: '2026-10-14', from: '2026-10-12', to: '2026-10-25',
  checked_at: '2026-10-14T15:02:11', notes: [],
  source: 'NSE event calendar and NSE Integrated Filing — Financials',
  days: [
    day('2026-10-12', [
      { symbol: 'HCLTECH', company: 'HCL Technologies Limited', status: 'declared',
        filed_at: '2026-10-12T19:38:00', quarter: 'Q2 FY27', bases: ['consolidated', 'standalone'],
        meeting: '2026-10-12', purpose: 'Financial Results/Dividend' }]),
    day('2026-10-13', [
      { symbol: 'TARIL', company: 'Transformers And Rectifiers (India) Limited', status: 'declared',
        filed_at: '2026-10-13T16:34:06', quarter: 'Q2 FY27', bases: ['consolidated', 'standalone'],
        meeting: '2026-10-13', purpose: 'Financial Results/Other business matters' },
      { symbol: 'LATE', company: 'Late Filer Limited', status: 'declared',
        filed_at: '2026-10-14T09:05:00', quarter: 'Q2 FY27', bases: ['standalone'],
        meeting: '2026-10-13', purpose: 'Financial Results' },
      { symbol: 'SLOW', company: 'Slow Industries Limited', status: 'awaited',
        meeting: '2026-10-13', purpose: 'Financial Results' }]),
    day('2026-10-14', [
      { symbol: 'DLINKINDIA', company: 'D-Link (India) Limited', status: 'declared',
        filed_at: '2026-10-14T12:38:00', quarter: 'Q2 FY27', bases: ['standalone'] },
      { symbol: 'EVIL', company: '<img src=x onerror="window.__pwned=1">', status: 'today',
        meeting: '2026-10-14', purpose: 'Financial Results' },
      { symbol: 'NOW', company: 'Now Limited', status: 'today', meeting: '2026-10-14',
        purpose: 'Financial Results/Dividend' }]),
    day('2026-10-15', [
      { symbol: '360ONE', company: '360 ONE WAM LIMITED', status: 'scheduled',
        meeting: '2026-10-15', purpose: 'Financial Results/Dividend' },
      { symbol: '5PAISA', company: '5Paisa Capital Limited', status: 'scheduled',
        meeting: '2026-10-15', purpose: 'Financial Results' }]),
    day('2026-10-16', []),
    day('2026-10-17', [
      { symbol: 'AXISBANK', company: 'Axis Bank Limited', status: 'scheduled',
        meeting: '2026-10-17', purpose: 'Financial Results/Fund Raising' }]),
    day('2026-10-18', []),
    day('2026-10-19', [
      { symbol: 'BAJFINANCE', company: 'Bajaj Finance Limited', status: 'scheduled',
        meeting: '2026-10-19', purpose: 'Financial Results' }]),
    day('2026-10-20', []), day('2026-10-21', []), day('2026-10-22', []),
    day('2026-10-23', []), day('2026-10-24', []), day('2026-10-25', [])
  ]
};

const RESULTS = {
  available: true, symbol: 'TARIL', name: 'Transformers And Rectifiers (India) Limited',
  quarter: 'Q2 FY27', as_of: '2026-09-30', filed_at: '13-Oct-2026 16:34:09',
  basis: 'consolidated', pat_cr: 81.38, pat_yoy_pct: 117.9, pat_yoy_base_cr: 37.35,
  revenue_cr: 739.44, revenue_yoy_pct: 60.7, net_margin_pct: 11, net_margin_yoy_pct: 8.1,
  revenue_series: [{ period: 'Q2 FY27', value_cr: 739.44 }, { period: 'Q1 FY27', value_cr: 572.34 }],
  pat_series: [{ period: 'Q2 FY27', value_cr: 81.38 }, { period: 'Q1 FY27', value_cr: 64.29 }],
  bullets: [], note: '', disclaimer: ''
};

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

(async () => {
  await new Promise(resolve => server.listen(8772, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  // The reader's clock says a different day from the exchange's. The page
  // must use the server's "today".
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 },
                                             timezoneId: 'America/Los_Angeles' });
  await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
  const page = await context.newPage(), errors = [], asked = [];
  let calendarCalls = 0, calendarDown = false;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/results/calendar') {
      calendarCalls += 1;
      if (calendarDown) return route.fulfill({ status: 503, json: { detail: 'Could not read the results calendar: NSE refused' } });
      // Slow enough that a second open of the tab lands while the first
      // read is still on the wire, as it does on a loaded machine.
      return new Promise(res => setTimeout(res, 400)).then(() => route.fulfill({ json: CAL }));
    }
    if (u.pathname === '/results') {
      asked.push(u.searchParams.get('ticker'));
      return route.fulfill({ json: RESULTS });
    }
    return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [],
                                   items: [], sectors: [], rankings: [], status: 'idle' } });
  });

  const tabs = () => page.locator('#rcalseg [data-rcal]').evaluateAll(els => els.map(b => ({
    tab: b.dataset.rcal, text: b.textContent.trim(), n: b.querySelector('b').textContent,
    on: b.getAttribute('aria-selected') === 'true' })));
  const rows = () => page.locator('#rcallist .rcal-row').evaluateAll(els => els.map(r => ({
    sym: r.dataset.sym, status: r.querySelector('.rcal-st').textContent.trim(),
    cls: r.querySelector('.rcal-st').className, meta: (r.querySelector('.rcal-meta') || {}).textContent || '' })));

  /* ── 1 · Opening Results lands on Today, with every tab counted ─────────── */

  await page.goto('http://127.0.0.1:8772/?go=results', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#rcallist .rcal-row', { timeout: 15000 });
  assert.equal(calendarCalls, 1, 'the calendar was not read exactly once on opening');
  assert.deepEqual((await tabs()).map(t => [t.tab, t.n, t.on]), [
    ['yesterday', '3', false], ['today', '3', true], ['tomorrow', '2', false],
    ['week', '10', false], ['next', '1', false]], 'tab counts or the default tab are wrong');

  /* ── 2 · Today: filed first, then the boards meeting today ─────────────── */

  let r = await rows();
  assert.deepEqual(r.map(x => x.sym), ['DLINKINDIA', 'EVIL', 'NOW']);
  assert.equal(r[0].status, 'Filed 12:38');
  assert.match(r[0].cls, /declared/);
  assert.equal(r[2].status, 'Board meets today');
  assert.match(r[2].meta, /also dividend/);
  assert.equal(await page.locator('#rcalsum').innerText(), '3 companies · 1 filed');
  assert.equal(await page.evaluate(() => window.__pwned), undefined, 'a company name ran as markup');
  assert.ok((await page.locator('#rcallist').innerText()).includes('<img src=x'),
    'the hostile name is not shown as text');
  await page.locator('#rcal').screenshot({ path: path.join(output, 'today.png') });

  /* ── 3 · Yesterday: a met-but-unfiled board is never "Filed" ──────────── */

  await page.locator('[data-rcal="yesterday"]').click();
  r = await rows();
  assert.deepEqual(r.map(x => [x.sym, x.status]), [
    ['TARIL', 'Filed 16:34'],
    ['LATE', 'Filed 14 Oct, 09:05'],
    ['SLOW', 'Board met · not filed yet']]);
  assert.ok(!/declared/.test(r[2].cls), 'an awaited result is styled as filed');
  assert.match(r[0].meta, /Q2 FY27 · consolidated & standalone/);

  /* ── 4 · Tomorrow, and the address follows the tab ─────────────────────── */

  await page.evaluate(() => { location.hash = '#research/results'; });
  await page.locator('[data-rcal="tomorrow"]').click();
  r = await rows();
  assert.deepEqual(r.map(x => [x.sym, x.status]),
    [['360ONE', 'Board meeting'], ['5PAISA', 'Board meeting']]);
  assert.equal(new URL(page.url()).hash, '#research/results/tomorrow');

  /* ── 5 · A week is grouped by day, empty days left out ─────────────────── */

  await page.locator('[data-rcal="week"]').click();
  const heads = await page.locator('#rcallist .rcal-day').allTextContents();
  assert.deepEqual(heads.map(h => h.replace(/\s+/g, ' ').trim()), [
    'Mon · 12 Oct1', 'Yesterday · 13 Oct3', 'Today · 14 Oct3', 'Tomorrow · 15 Oct2', 'Sat · 17 Oct1']);
  assert.equal((await rows()).length, 10);
  await page.locator('#rcal').screenshot({ path: path.join(output, 'this-week.png') });

  /* ── 6 · The filter narrows, and says so when nothing matches ──────────── */

  await page.locator('#rcalq').fill('transformers');
  assert.deepEqual((await rows()).map(x => x.sym), ['TARIL']);
  await page.locator('#rcalq').fill('zzz');
  assert.match(await page.locator('#rcallist .rcal-empty').innerText(), /Nothing this week matches/);
  await page.locator('#rcalq').fill('taril');

  /* ── 7 · A row opens the company's results ─────────────────────────────── */

  await page.locator('#rcallist .rcal-row[data-sym="TARIL"]').click();
  await page.waitForSelector('#rcardwrap', { state: 'visible' });
  assert.deepEqual(asked, ['TARIL']);
  assert.equal(await page.locator('#rquarter').innerText(), 'Q2 FY27');
  assert.equal(await page.locator('#rtk').inputValue(), 'TARIL');

  /* ── 8 · Next week is empty but for one, and says nothing invented ─────── */

  await page.locator('#rcalq').fill('');
  await page.locator('[data-rcal="next"]').click();
  assert.deepEqual((await rows()).map(x => x.sym), ['BAJFINANCE']);

  /* ── 9 · An address opens its tab; a phone does not scroll sideways ───── */

  const phone = await context.newPage();
  phone.on('pageerror', e => errors.push(String(e.stack)));
  await phone.setViewportSize({ width: 390, height: 844 });
  await phone.goto('http://127.0.0.1:8772/#research/results/tomorrow', { waitUntil: 'domcontentloaded' });
  await phone.waitForSelector('#rcallist .rcal-row', { timeout: 15000 });
  assert.equal(await phone.locator('#rcalseg [aria-selected="true"]').getAttribute('data-rcal'), 'tomorrow');
  const overflow = await phone.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 0, `the page scrolls sideways by ${overflow}px on a phone`);
  await phone.locator('#rcal').screenshot({ path: path.join(output, 'tomorrow-phone.png') });
  await phone.close();

  /* ── 10 · The engine down: a sentence, never a spinner for ever ────────── */

  calendarDown = true;
  const down = await context.newPage();
  down.on('pageerror', e => errors.push(String(e.stack)));
  await down.goto('http://127.0.0.1:8772/?go=results', { waitUntil: 'domcontentloaded' });
  await down.waitForFunction(() => /NSE refused/.test(
    (document.querySelector('#rcallist') || {}).textContent || ''), null, { timeout: 15000 });
  assert.deepEqual(await down.locator('#rcalseg b').allTextContents(), ['', '', '', '', ''],
    'counts shown for a calendar that could not be read');
  await down.close();

  assert.deepEqual(errors, [], 'the page threw:\n' + errors.join('\n'));
  await browser.close();
  server.close();
  console.log('results calendar: all assertions passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
