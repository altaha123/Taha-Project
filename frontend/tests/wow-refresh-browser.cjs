/* WOW orders: the page answers, then catches up. Real Chromium, fixtures only.

   The page used to sit on "Reading the filings…" for as long as the server
   took to download every order PDF of the week — minutes, sometimes forever.
   The server now answers at once and reads behind the answer. What this
   guards, on the page side:

     · a first read says it is reading, never "a quiet week", and fills in by
       itself when the server has finished
     · a repaint while the reader has the evidence open does not snap it shut
     · a filing not read yet says so, and is never counted as "not disclosed"
     · times are the exchange's, in IST, on a machine set to another zone
     · a request that hangs ends in a message and a working Try again, not a
       spinner that never stops
     · a refresh that failed says so, and leaves the list it had on screen */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/wow-refresh');
fs.mkdirSync(output, { recursive: true });
const PORT = 8792;

const base = {
  available: true, threshold_pct: 10, note: '', from_ledger: false, refresh_error: '',
  source: 'Exchange corporate announcements, Regulation 30.',
  explain: 'An order is called WOW when its disclosed value is at least 10% of the company’s market capitalisation.',
  quarter: null
};
const big = {
  symbol: 'SMALLCO', company: 'Small Engineering Ltd', headline: 'Receipt of work order from NHAI',
  at: '2026-11-17T11:02:00+05:30', date: '2026-11-17', quarter: 'Q3 FY27',
  pdf: 'https://www.bseindia.com/x/big.pdf', read_state: 'read',
  value_cr: 450.75, value_basis: 'stated next to an order-value phrase in the filing',
  value_confident: true, currency_converted: false,
  excerpt: 'The Company has received a work order. The order value is Rs. 450.75 crore.',
  market_cap_cr: 1050, pct_of_market_cap: 42.93, wow: true
};
const unread = {
  symbol: 'LATECO', company: 'Late Filing Ltd', headline: 'Bagging of orders',
  at: '2026-11-17T15:40:00+05:30', date: '2026-11-17', quarter: 'Q3 FY27',
  pdf: 'https://www.bseindia.com/x/late.pdf', read_state: 'unread',
  value_cr: null, value_basis: null, value_confident: false, currency_converted: false,
  excerpt: null, market_cap_cr: null, pct_of_market_cap: null, wow: false
};
const counts = (o) => Object.assign({ orders: 0, with_value: 0, value_not_disclosed: 0,
                                       unreadable: 0, not_read: 0, wow: 0 }, o);

async function openTab(page, id) {
  await page.waitForLoadState('load');
  await page.waitForTimeout(400);
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.evaluate(t => window.AltahaNav.go('screener', t, true), id);
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

/* A page whose /wow-orders answers come from `answer(n)`, n counting calls
   from 1. Returning null leaves the request hanging. */
async function open(browser, answer) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 }, reducedMotion: 'reduce',
    timezoneId: 'America/New_York' });
  await context.addInitScript(() => { try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (e) {} });
  const page = await context.newPage(), errors = [], calls = { n: 0 };
  page.on('pageerror', e => errors.push(String(e.stack || e.message || e)));
  await page.clock.install();
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/wow-orders') {
      calls.n += 1;
      const body = answer(calls.n);
      return body ? route.fulfill({ json: body }) : undefined;     // hang
    }
    if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
    return route.fulfill({ json: { available: false, rows: [], items: [], sectors: [] } });
  });
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);
  await openTab(page, 'wow');
  return { context, page, errors, calls };
}

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  // ── A first read of the week, then the answer ──────────────────────────
  {
    const { context, page, errors, calls } = await open(browser, n => n === 1
      ? Object.assign({}, base, { rows: [], counts: counts(), as_of: null, refreshing: true, from_ledger: true })
      : n === 2
        ? Object.assign({}, base, { rows: [big, unread], counts: counts({ orders: 2, with_value: 1, not_read: 1, wow: 1 }),
                                    as_of: '2026-11-17T16:05:00+05:30', refreshing: true })
        : Object.assign({}, base, { rows: [big, unread], counts: counts({ orders: 2, with_value: 1, not_read: 1, wow: 1 }),
                                    as_of: '2026-11-17T16:06:00+05:30', refreshing: false }));
    const status = page.locator('#wow-body .wo-status');
    await status.waitFor({ state: 'visible' });
    assert.match(await status.innerText(), /Reading this week’s order filings/);
    assert.equal(await page.locator('#wow-body .wo-empty').count(), 0,
      'a first read must not say "no order announcements"');
    await page.screenshot({ path: path.join(output, 'first-read.png') });

    // The page asks again by itself, about every eight seconds.
    await page.clock.fastForward(8500);
    await page.locator('#wow-body .wo').first().waitFor({ state: 'visible' });
    assert.equal(calls.n, 2);
    assert.match(await status.innerText(), /Read at 04:05 pm IST/i);
    assert.match(await status.innerText(), /Checking the exchange for newer filings/);

    // Open the evidence, then let the refresh finish: it stays open.
    await page.locator('#wow-body .wo-ev summary').first().click();
    await page.clock.fastForward(8500);
    await page.waitForFunction(() => /04:06/.test(document.querySelector('#wow-body .wo-status').textContent));
    assert.equal(calls.n, 3);
    assert.equal(await page.locator('#wow-body .wo-ev').first().evaluate(d => d.open), true,
      'the repaint closed the evidence the reader had open');
    assert.doesNotMatch(await status.innerText(), /Checking/);

    // No further asking once the server says it is done.
    await page.clock.fastForward(20000);
    await page.waitForTimeout(200);
    assert.equal(calls.n, 3, 'the page kept polling after the refresh finished');

    // A filing not read yet says so, and is not counted as undisclosed.
    const late = page.locator('#wow-body .wo', { hasText: 'Late Filing Ltd' });
    assert.match(await late.innerText(), /filing not read yet/i);
    assert.match(await late.innerText(), /Order\s+not read yet/i);
    assert.doesNotMatch(await late.innerText(), /not disclosed/);
    const bar = await page.locator('#wow-body .wo-counts').innerText();
    assert.match(bar, /1\s*not read yet/);
    assert.match(bar, /0\s*value not disclosed/);

    // Exchange time on a machine in New York: 11:02 IST, labelled.
    assert.match(await page.locator('#wow-body .wo', { hasText: 'Small Engineering' }).innerText(),
      /17 Nov, 11:02 am IST/i);
    await page.screenshot({ path: path.join(output, 'filled.png'), fullPage: true });
    assert.deepEqual(errors, []);
    await context.close();
  }

  // ── A request that hangs ends in a message and a working Try again ─────
  {
    let hang = true;
    const { context, page, errors, calls } = await open(browser, () => hang ? null
      : Object.assign({}, base, { rows: [big], counts: counts({ orders: 1, with_value: 1, wow: 1 }),
                                  as_of: '2026-11-17T16:05:00+05:30', refreshing: false }));
    await page.locator('#wow-body .is-loading').waitFor({ state: 'visible' });
    await page.clock.fastForward(26000);
    const msg = page.locator('#wow-body .wo-empty');
    await page.waitForFunction(() => /taking too long/.test(document.getElementById('wow-body').textContent));
    assert.match(await msg.innerText(), /taking too long/);
    await page.screenshot({ path: path.join(output, 'timed-out.png') });
    hang = false;
    await page.locator('#wow-body [data-wow-retry]').click();
    await page.locator('#wow-body .wo').first().waitFor({ state: 'visible' });
    assert.equal(calls.n, 2);
    assert.deepEqual(errors, []);
    await context.close();
  }

  // ── A refresh that failed keeps the list and offers to try again ───────
  {
    const { context, page, errors } = await open(browser, () =>
      Object.assign({}, base, { rows: [big], counts: counts({ orders: 1, with_value: 1, wow: 1 }),
                                as_of: '2026-11-17T09:30:00+05:30', refreshing: false,
                                refresh_error: 'Could not refresh announcements: timed out' }));
    const status = page.locator('#wow-body .wo-status.is-warn');
    await status.waitFor({ state: 'visible' });
    assert.match(await status.innerText(), /Could not check the exchange/);
    assert.match(await status.innerText(), /Read at 09:30 am IST/i);
    assert.equal(await page.locator('#wow-body .wo').count(), 1, 'the list it had must stay on screen');
    assert.equal(await page.locator('#wow-body .wo-status [data-wow-retry]').count(), 1);
    assert.deepEqual(errors, []);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('WOW orders refresh Chromium checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
