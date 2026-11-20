/* WOW orders and Concall summaries in a real Chromium, against fixtures shaped
   exactly like the API payloads. No live calls.

   What this guards:
     · the WOW orders lead the page, each saying who won what from whom and how
       large it is against the company, with the smaller orders one line each
     · a lowest bid or a memorandum of understanding is never shown as WOW,
       however large, and says why
     · an order whose value the company did not disclose must render as "value
       not disclosed" — never as zero, never ranked above a disclosed one; one
       the company calls confidential, and one not read yet, say that instead
     · the page is answered before the filings are read, fills in by itself,
       and keeps open what the reader opened
     · the WOW threshold must be visible on the page, because a rule nobody can
       read is a rule nobody can argue with
     · a quarter the service did not watch must not be presented as a fall in
       order inflow
     · every quoted concall line must carry the name of who said it
     · with no model configured, the page must say so rather than presenting
       the extraction as a written summary
     · with a model configured, the page must fill in while the server is
       still reading rather than wait for it, list the key calls first, name
       the model that wrote each summary, and stop asking once the server
       says it has finished
     · a call can be shared only once it has a written summary, the card and
       the link it shares are that call's, and a shared link opens onto that
       call — including one too old to be in the list any more */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/filings-views');
fs.mkdirSync(output, { recursive: true });

const wow = {
  available: true, threshold_pct: 10,
  counts: { orders: 7, firm: 6, with_value: 4, sized: 4, value_not_disclosed: 2, unread: 1, not_firm: 1, wow: 2 },
  reading: false, poll_seconds: null, read_at: '2026-09-12T17:00:00+05:30',
  note: '', source: 'BSE corporate announcements, Regulation 30. Order values are read from the filed document, not the headline.',
  explain: 'An order is called WOW when its disclosed value is at least 10% of the company’s market capitalisation. Orders whose value the company did not disclose are listed but never ranked, and never given an assumed figure.',
  rows: [
    { symbol: 'TINYCO', company: 'Tiny Infra Projects Ltd', headline: 'Bagging/Receiving of orders/contracts', at: '2026-09-12T16:20:00+05:30', date: '2026-09-12', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/7.pdf', read: true, stage: 'order', kind: 'Work order', customer: 'Hindalco Industries Limited', nature: null, period: null, size_text: null, value_cr: 136.29, value_state: 'stated', value_basis: 'stated next to an order-value phrase in the filing', value_confident: true, currency_converted: false, fx_rate: null, excerpt: 'Intimation of workorder from M/S Hindalco Industries Limited worth Rs.136.29 crores', market_cap_cr: 106.7, pct_of_market_cap: 127.73, sales_cr: null, sales_year: null, pct_of_sales: null, months_of_sales: null, wow: true, outsized: true, filings: 1 },
    { symbol: 'SMALLCO', company: 'Small Engineering Ltd', headline: 'Receipt of work order from NHAI for a highway package', at: '2026-09-12T11:02:00+05:30', date: '2026-09-12', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/1.pdf', read: true, stage: 'order', kind: 'Work order', customer: 'National Highways Authority of India <script>window.__wowxss=1</script>', nature: 'Four-laning of a 42 km highway package on EPC mode', period: '24 months', size_text: null, value_cr: 450.75, value_state: 'stated', value_basis: 'stated as the size of the order in the filing’s disclosure table', value_confident: true, currency_converted: false, fx_rate: null, excerpt: 'The Company has received a work order. The order value is Rs. 450.75 crore, to be executed over 24 months.', market_cap_cr: 1050, pct_of_market_cap: 42.93, sales_cr: 901.5, sales_year: 'FY26', pct_of_sales: 50, months_of_sales: 6, wow: true, outsized: false, filings: 2 },
    { symbol: 'BIGCO', company: 'Big Infra Ltd', headline: 'Order win intimation under Regulation 30', at: '2026-09-11T15:40:00+05:30', date: '2026-09-11', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/2.pdf', read: true, stage: 'order', kind: 'Letter of award', customer: 'Posh Offshore Private Limited', nature: 'Subsea inspection work', period: 'By May 2027', size_text: null, value_cr: 320, value_state: 'stated', value_basis: 'largest rupee figure in the filing; the filing does not label it as the order value', value_confident: false, currency_converted: true, fx_rate: 93.5, excerpt: 'The company informed that USD 38 million was involved in the transaction.', market_cap_cr: 42000, pct_of_market_cap: 0.76, sales_cr: 16000, sales_year: 'FY26', pct_of_sales: 2, months_of_sales: 0.2, wow: false, outsized: false, filings: 1 },
    { symbol: 'ROADCO', company: 'Road Builders Ltd', headline: 'Road Builders Ltd has informed the Exchange about L1 for NHAI Project', at: '2026-09-11T18:05:00+05:30', date: '2026-09-11', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/4.pdf', read: true, stage: 'l1', kind: 'Lowest bidder (L1)', customer: 'National Highways Authority of India (NHAI)', nature: 'Construction of an 8-lane expressway package', period: '18 months', size_text: null, value_cr: 1465, value_state: 'stated', value_basis: 'stated as the size of the order in the filing’s disclosure table', value_confident: true, currency_converted: false, fx_rate: null, excerpt: 'Quoted EPC Price for the Project Rs.1,465.00 Crore excluding GST', market_cap_cr: 3114.3, pct_of_market_cap: 47.04, sales_cr: 7519.88, sales_year: 'FY26', pct_of_sales: 19.5, months_of_sales: 2.3, wow: false, outsized: false, filings: 1 },
    { symbol: 'ACCURACY', company: 'Accuracy Shipping Ltd', headline: 'Receipt Of Letter Of Intent For Setting Up Of Container Freight Station At Kandla', at: '2026-09-10T09:15:00+05:30', date: '2026-09-10', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/3.pdf', read: true, stage: 'order', kind: 'Letter of intent', customer: 'Deendayal Port Authority', nature: 'Container freight station at Kandla', period: null, size_text: '40,000 containers a year', value_cr: null, value_state: 'not_stated', value_basis: null, value_confident: false, currency_converted: false, fx_rate: null, excerpt: null, market_cap_cr: null, pct_of_market_cap: null, sales_cr: null, sales_year: null, pct_of_sales: null, months_of_sales: null, wow: false, outsized: false, filings: 1 },
    { symbol: 'SECRETCO', company: 'Secret Systems Ltd', headline: 'Receiving of order', at: '2026-09-10T08:15:00+05:30', date: '2026-09-10', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/5.pdf', read: true, stage: 'order', kind: 'Purchase order', customer: 'Overseas customer in a space sector', nature: 'Manufacturing electrical wire harness', period: '4-6 months', size_text: 'This cannot be disclosed being confidential in nature', value_cr: null, value_state: 'confidential', value_basis: null, value_confident: false, currency_converted: false, fx_rate: null, excerpt: null, market_cap_cr: null, pct_of_market_cap: null, sales_cr: null, sales_year: null, pct_of_sales: null, months_of_sales: null, wow: false, outsized: false, filings: 1 },
    { symbol: 'LATECO', company: 'Late Filer Ltd', headline: 'Bagging/Receiving of orders/contracts', at: '2026-09-09T19:15:00+05:30', date: '2026-09-09', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/6.pdf', read: false, stage: 'order', kind: null, customer: null, nature: null, period: null, size_text: null, value_cr: null, value_state: 'unread', value_basis: null, value_confident: false, currency_converted: false, fx_rate: null, excerpt: null, market_cap_cr: null, pct_of_market_cap: null, sales_cr: null, sales_year: null, pct_of_sales: null, months_of_sales: null, wow: false, outsized: false, filings: 1 }
  ],
  quarter: {
    this_quarter: { label: 'Q2 FY27', start: '2026-07-01', end: '2026-09-30', orders: 3, with_value: 2, value_not_disclosed: 1, total_cr: 770.75, companies: 3, biggest: { symbol: 'SMALLCO', company: 'Small Engineering Ltd', value_cr: 450.75, pct_of_market_cap: 42.93 }, partial: false, trading_days: 55, days_not_recorded: 0 },
    previous_quarter: { label: 'Q1 FY27', start: '2026-04-01', end: '2026-06-30', orders: 5, with_value: 4, value_not_disclosed: 1, total_cr: 512.0, companies: 4, biggest: { symbol: 'OTHERCO', company: 'Other Ltd', value_cr: 200, pct_of_market_cap: 11.1 }, partial: false, trading_days: 63, days_not_recorded: 1 },
    change_pct: 50.5, change_cr: 258.75, comparable: true, recording_since: '2026-04-01',
    caveat: 'Counts only orders whose value the company disclosed, so every total is a floor on order inflow rather than a complete order book.'
  }
};

const wowPartial = JSON.parse(JSON.stringify(wow));
wowPartial.quarter.previous_quarter.partial = true;
wowPartial.quarter.previous_quarter.days_not_recorded = 40;
wowPartial.quarter.change_pct = null;
wowPartial.quarter.comparable = false;
wowPartial.quarter.caveat += ' One of these quarters began before this service started recording, so the two are not yet comparable and no percentage change is shown.';

const concalls = {
  available: true, count: 1, summary_configured: false, model: null, days: 21,
  counts: { calls: 1, key: 0, summarised: 0, waiting: 0 },
  status: { reading: false, phase: null, last_pass: '2026-09-12T10:00:00+05:30', error: null, capped: null, feed: [] },
  poll_seconds: null, disclaimer: null,
  source: 'Earnings call transcripts filed with BSE under Regulation 30. The digest is extracted from the document itself; nothing in it is paraphrased.',
  rows: [{
    symbol: 'SHIPROCKET', company: 'Shiprocket Ltd',
    headline: 'Announcement under Regulation 30 (LODR)-Earnings Call Transcript',
    at: '2026-09-11T19:24:00+05:30', pdf: 'https://www.bseindia.com/x/t.pdf', readable: true,
    brief: { status: 'off' }, key: false,
    digest: {
      quarter: 'Q1 FY27', call_date: '2026-09-08', words: 8978,
      management: [
        { name: 'Saahil Goel', role: 'Managing Director And Chief Executive Officer' },
        { name: 'Tanmay Kumar', role: 'Chief Financial Officer' },
        { name: 'Shreyanse Jain', role: 'Associate Director, Investor Relations' }],
      analysts: [{ name: 'Sachin Salgaonkar', firm: '' }, { name: 'Della Desai', firm: '' }, { name: 'Kunal Thanvi', firm: 'Jm Financial' }],
      analyst_count: 3,
      speakers: [['Saahil Goel', 16], ['Moderator', 7]],
      guidance: [
        { said: 'The CM has improved a little bit, right, over this revenue growth and we expect it to maintain around that range as it has in the last trajectory.', by: 'Saahil Goel' },
        { said: 'We will stand for the merchants, we will represent their needs in the market, and we will continuously innovate on solving those sides.', by: 'Saahil Goel' }],
      guidance_count: 2,
      topics: { margin: { mentions: 56, per_1k_words: 6.24 }, pricing: { mentions: 9, per_1k_words: 1.0 }, debt: { mentions: 7, per_1k_words: 0.78 }, 'working capital': { mentions: 4, per_1k_words: 0.45 } },
      prepared_remarks_share: 44.0
    },
    versus_previous: {
      available: true, from_quarter: 'Q4 FY26', to_quarter: 'Q1 FY27',
      topic_shifts: [
        { topic: 'margin', now: 6.24, before: 1.2, change: 5.04, direction: 'up', new: false, dropped: false },
        { topic: 'debt', now: 0.78, before: 3.5, change: -2.72, direction: 'down', new: false, dropped: false },
        { topic: 'pricing', now: 1.0, before: 0, change: 1.0, direction: 'up', new: true, dropped: false },
        { topic: 'hiring', now: 0, before: 0.6, change: -0.6, direction: 'down', new: false, dropped: true }],
      talked_more_about: ['margin', 'pricing'], talked_less_about: ['debt', 'hiring'],
      guidance_count: { now: 2, before: 5, change: -3 },
      call_length_words: { now: 8978, before: 6000 },
      analysts_on_call: { now: 3, before: 8 },
      caveat: 'Topic emphasis counts how often a subject came up per thousand words. It says what management spent the call on, which is not the same as what they said about it.'
    }
  }]
};


/* The same page with a model configured, as three answers in a row: the
   server still reading and nothing in the ledger yet; two calls read, one
   briefed and one waiting; then finished. */
const ccStatus = (reading, phase) => ({ reading, phase, last_pass: null, error: null, capped: null, feed: [] });
const ccBase = {
  available: true, summary_configured: true, model: 'claude-sonnet-5-5', days: 21,
  disclaimer: 'Written by Claude from the filed transcript. Quotes are checked word for word against it; figures in the rest are not, so check one against the transcript before you rely on it.',
  source: 'Earnings call transcripts filed with BSE under Regulation 30. The summary is written by a model from the transcript; the quotes in it are checked against the document, and the counts under each call involve no model at all.'
};
const ccShiprocket = concalls.rows[0];
const ccBrief = {
  status: 'ready', style: 1, model: 'claude-sonnet-5-5', written_at: '2026-09-12T10:04:00+05:30',
  headline: 'Revenue grew 34% and contribution margin is expected to hold <script>window.__xss=1</script>',
  summary: 'Management said transactions grew 36% and revenue nearly 34% in the quarter, ahead of last year’s 24%. They expect contribution margin to stay around its current range.',
  quarter: ['Transactions grew 36% and GMV 31%.', 'Revenue grew nearly 34%, against 24% for FY26.'],
  commitments: [{ topic: 'Contribution margin', said: 'The CM has improved a little bit, right, over this revenue growth and we expect it to maintain around that range as it has in the last trajectory.', by: 'Saahil Goel' }],
  quotes_dropped: 1,
  pressed_on: ['Whether margin growing faster than revenue would continue; management expects the range to hold.'],
  not_answered: ['How many power merchants use Martech: no number was given.'],
  weight: 'high', weight_reason: 'Management guided on contribution margin and gave growth figures by segment.', partial: false
};
const ccOther = {
  symbol: 'QUIETCO', company: 'Quiet Industries Ltd',
  headline: 'Transcript Of Q1 FY27 Earnings Conference Call',
  at: '2026-09-12T12:10:00+05:30', pdf: 'https://www.bseindia.com/x/q.pdf', readable: true, key: false,
  digest: Object.assign({}, ccShiprocket.digest, { management: [], analysts: [], analyst_count: 0 }),
  versus_previous: { available: false, reason: 'No earlier transcript has been read for this company yet.' }
};
const ccReading = Object.assign({}, ccBase, {
  count: 0, rows: [], counts: { calls: 0, key: 0, summarised: 0, waiting: 0 },
  status: ccStatus(true, 'reading'), poll_seconds: 3 });
const ccFilling = Object.assign({}, ccBase, {
  count: 2, counts: { calls: 2, key: 1, summarised: 1, waiting: 1 },
  status: ccStatus(true, 'summarising'), poll_seconds: 3,
  rows: [Object.assign({}, ccShiprocket, { key: true, brief: ccBrief }),
         Object.assign({}, ccOther, { brief: { status: 'pending' } })] });
const ccDone = Object.assign({}, ccBase, {
  count: 2, counts: { calls: 2, key: 1, summarised: 2, waiting: 0 },
  status: ccStatus(false, null), poll_seconds: null,
  rows: [Object.assign({}, ccShiprocket, { key: true, brief: ccBrief }),
         Object.assign({}, ccOther, { brief: Object.assign({}, ccBrief, {
           headline: 'Management repeated the reported numbers and gave no guidance',
           summary: 'The call restated the quarter’s results. Answers to questions on demand and margins stayed general.',
           commitments: [], quotes_dropped: 0, not_answered: [], weight: 'low',
           weight_reason: 'Nothing was said beyond what the results filing already contained.' }) })] });


/* Open a tab and prove it is actually on screen.
   Two traps this closes. The homepage restores its default tab on load, so a
   navigation issued the instant AltahaNav appears is silently overridden a
   moment later. And `innerText` on a display:none element falls back to
   textContent, so every content assertion in this file would pass against a
   view nobody can see. Hence the explicit visibility check. */
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

(async () => {
  await new Promise(r => server.listen(8773, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  // Reduced motion, deliberately. The page reveals content through an
  // intersection observer, so anything below the fold sits at opacity 0 until
  // it scrolls into view — which makes a click on it wait forever for an
  // element that is, correctly, not yet visible. Turning motion off is how a
  // real reader with the OS preference set sees this page anyway.
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript(() => { try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (e) {} });
  const page = await context.newPage(), errors = [];
  let wowCalls = 0, ccCalls = 0, wowPayload = wow, wowQueue = null, ccQueue = null, oneCall = null;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/wow-orders') {
      wowCalls++;
      const next = wowQueue ? (wowQueue.length > 1 ? wowQueue.shift() : wowQueue[0]) : wowPayload;
      return route.fulfill({ json: next });
    }
    if (u.pathname === '/concalls') {
      ccCalls++;
      const next = ccQueue ? (ccQueue.length > 1 ? ccQueue.shift() : ccQueue[0]) : concalls;
      return route.fulfill({ json: next });
    }
    if (u.pathname === '/concall' && oneCall && u.searchParams.get('ticker') === oneCall.symbol) {
      return route.fulfill({ json: oneCall });
    }
    if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
    return route.fulfill({ json: { available: false, rows: [], items: [], sectors: [] } });
  });

  await page.goto('http://127.0.0.1:8773/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);

  // Nothing fetched until the view is opened — both read PDFs server-side.
  assert.equal(wowCalls, 0, 'WOW orders must not load before its tab is opened');
  assert.equal(ccCalls, 0, 'concalls must not load before its tab is opened');

  // ── WOW orders ───────────────────────────────────────────────────────────
  await openTab(page, 'wow');
  await page.locator('#view-wow .wo').first().waitFor({ state: 'visible' });
  assert.equal(wowCalls, 1);
  assert.ok(await page.locator('#view-wow').isVisible(), 'WOW view must be on screen');

  const wv = page.locator('#view-wow');
  assert.equal(await wv.locator('.wo').count(), 7);
  // The top of the page says what happened this week and what WOW means.
  assert.match(await wv.locator('.wo-say').innerText(), /2 orders this week are big enough to matter/i);
  assert.match(await wv.locator('.wo-rule').innerText(), /at least 10% of the company.s market cap/i);
  const tiles = wv.locator('.wo-tile');
  assert.match(await tiles.nth(0).innerText(), /128%[\s\S]*Tiny Infra Projects Ltd/);
  assert.match(await tiles.nth(1).innerText(), /₹451 cr[\s\S]*Small Engineering Ltd/);
  assert.match(await tiles.nth(2).innerText(), /7[\s\S]*order filings · 4 state a rupee value/);
  // The threshold is on the page.
  assert.match(await wv.locator('.wo-counts').innerText(), /threshold 10% of market cap/i);
  assert.match(await wv.locator('.wo-counts').innerText(), /1\s*not read yet/i);

  // The groups, in order, each with its count.
  assert.deepEqual((await wv.locator('.wo-gh').allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim().toUpperCase()),
    ['WOW ORDERS 2', 'OTHER ORDERS WITH A VALUE 1', 'NOT FIRM ORDERS 1', 'NO RUPEE VALUE 3']);

  // A WOW order is a card that says who won what from whom, and how big it
  // is against the company. The fixture is ordered by the server; the page
  // keeps that order.
  const cards = wv.locator('.wo.is-wow');
  assert.equal(await cards.count(), 2);
  const first = cards.nth(1);
  assert.match(await first.locator('.wo-pct').innerText(), /43%/);
  assert.match(await first.locator('.wo-of').innerText(), /of market cap/i);
  assert.match(await first.locator('.wo-co').innerText(), /Small Engineering Ltd[\s\S]*WOW[\s\S]*Work order/i);
  assert.match(await first.locator('.wo-hl').innerText(),
    /₹451 cr work order from National Highways Authority of India/);
  assert.match(await first.locator('.wo-for').innerText(), /Four-laning of a 42 km highway/);
  const facts1 = await first.locator('.wo-facts').innerText();
  assert.match(facts1, /₹1,050 cr/);
  assert.match(facts1, /6 months of FY26 sales/);
  assert.match(facts1, /24 months/);
  assert.match(facts1, /2 filings/);
  // The bar is the order against the company, with the WOW line marked on it.
  const fill = await first.locator('.wo-bar i').evaluate(el => parseFloat(el.style.width));
  const tick = await first.locator('.wo-bar u').evaluate(el => parseFloat(el.style.left));
  assert.ok(Math.abs(fill - 85.9) < 0.2 && tick === 20, `bar ${fill} / tick ${tick}`);
  // Text from a filing is text. A tag in a customer's name is printed, not run.
  assert.match(await first.locator('.wo-hl').innerText(), /<script>/);
  assert.equal(await page.evaluate(() => window.__wowxss), undefined);

  // An order larger than the company says to open the filing.
  const huge = cards.nth(0);
  assert.match(await huge.locator('.wo-rank').evaluate(el => el.textContent), /^1$/);
  assert.match(await huge.locator('.wo-pct').innerText(), /128%/);
  assert.match(await huge.locator('.wo-warn').innerText(), /larger than the whole company.s market cap/i);
  assert.equal(await first.locator('.wo-warn').count(), 0);
  assert.doesNotMatch(await huge.locator('.wo-facts').innerText(), /sales/i,
    'no sales on file means no sales comparison, not a made-up one');

  // Every other order is one line, and opens to the same detail.
  const rows = wv.locator('.wo-row');
  assert.equal(await rows.count(), 5);
  const mid = rows.nth(0);
  assert.equal(await mid.evaluate(el => el.open), false);
  assert.match(await mid.locator(':scope > summary').innerText(), /Big Infra Ltd/);
  assert.match(await mid.locator(':scope > summary').innerText(), /0\.8%/);
  // An unlabelled or converted figure is flagged rather than presented flat.
  assert.match(await mid.locator(':scope > summary').innerText(), /unlabelled figure/i);
  assert.match(await mid.locator(':scope > summary').innerText(), /converted/i);
  await mid.evaluate(el => { el.open = true; });
  assert.match(await mid.locator('.wo-facts').innerText(), /under a week of FY26 sales/);
  assert.match(await mid.locator('.wo-ev .basis').evaluate(el => el.textContent),
    /converted at ₹93\.5, an assumed rate/);

  // A lowest bid is not an order: never WOW, whatever its size, and it says so.
  const bid = rows.nth(1);
  assert.match(await bid.locator(':scope > summary').innerText(), /Road Builders Ltd[\s\S]*Lowest bidder/i);
  assert.match(await bid.locator(':scope > summary').innerText(), /₹1,465 cr lowest bid from National Highways/);
  assert.match(await bid.locator(':scope > summary').innerText(), /47%/);
  assert.equal(await bid.evaluate(el => el.classList.contains('is-wow')), false);
  assert.equal(await bid.locator('.fl.wow').count(), 0);
  await bid.evaluate(el => { el.open = true; });
  assert.match(await bid.locator('.wo-warn').innerText(), /not been awarded yet, so it is not counted as WOW/i);

  // An undisclosed value says so, and shows no number.
  const none = rows.nth(2);
  assert.match(await none.locator(':scope > summary').innerText(), /Accuracy Shipping Ltd/);
  assert.match(await none.locator(':scope > summary').innerText(), /value not disclosed/i);
  assert.doesNotMatch(await none.innerText(), /₹0|0\.0%/);
  assert.equal(await none.locator('.wo-pct.none').count(), 1);
  await none.evaluate(el => { el.open = true; });
  assert.match(await none.locator('.wo-for.none').innerText(), /Size as filed: 40,000 containers a year/);
  // Confidential and unread are different facts from undisclosed.
  assert.match(await rows.nth(3).locator(':scope > summary').innerText(), /Secret Systems Ltd[\s\S]*value confidential/i);
  assert.match(await rows.nth(4).locator(':scope > summary').innerText(), /Late Filer Ltd[\s\S]*not read yet/i);
  await rows.nth(4).evaluate(el => { el.open = true; });
  assert.match(await rows.nth(4).locator('.wo-for.none').innerText(), /has not been read yet/i);
  const last = rows.nth(4);

  // The evidence for a figure is one disclosure away, and the figure never
  // appears without it. Opened through the element's own `open` property
  // rather than a synthetic click: the homepage mounts a fixed bar and a
  // scroll-reveal observer over this content, and fighting those would be a
  // test of the page chrome, not of whether the evidence is there.
  await page.evaluate(() => {
    document.querySelectorAll('#view-wow .wo-ev').forEach(d => { d.open = true; });
  });
  const evidence = first.locator('.wo-ev');
  assert.match(await evidence.locator('blockquote').innerText(), /450\.75 crore/);
  assert.match(await evidence.locator('.basis').innerText(), /disclosure table/);
  // A row with no disclosed value has nothing to disclose and shows no panel.
  assert.equal(await last.locator('.wo-ev').count(), 0);
  assert.equal(await none.locator('.wo-ev').count(), 0);
  // Every filing is one tap away.
  assert.equal(await wv.locator('.wo-pdf').count(), 7);

  // Quarter on quarter, both sides labelled.
  const wq = page.locator('.wq');
  assert.match(await wq.innerText(), /Q1 FY27/);
  assert.match(await wq.innerText(), /Q2 FY27/);
  assert.match(await wq.innerText(), /\+50\.5%/);

  assert.ok(await page.locator('#view-wow').isVisible());
  await page.screenshot({ path: path.join(output, 'wow-1280-light.png'), fullPage: true });

  // ── Concall summaries ────────────────────────────────────────────────────
  await openTab(page, 'concalls');
  await page.locator('#view-concalls .cc').first().waitFor({ state: 'visible' });
  assert.equal(ccCalls, 1);
  assert.ok(await page.locator('#view-concalls').isVisible(), 'concalls view must be on screen');

  // With no model configured the page says so, in those terms.
  assert.match(await page.locator('.cc-nosum').innerText(), /No written summary on this instance/i);
  assert.match(await page.locator('.cc-nosum').innerText(), /extracted from the transcript/i);

  // Every quoted line carries who said it, and it is never the moderator.
  const quotes = page.locator('.cc-quote');
  assert.equal(await quotes.count(), 2);
  for (let i = 0; i < 2; i++) {
    const cite = await quotes.nth(i).locator('cite').innerText();
    assert.ok(cite.trim().length > 2, 'quote missing attribution');
    assert.notEqual(cite.trim().toLowerCase(), 'moderator');
  }

  // What changed since last quarter, including a newly raised and a dropped topic.
  const shift = page.locator('.cc-shift');
  assert.match(await shift.innerText(), /What changed since Q4 FY26/i);
  assert.match(await shift.innerText(), /newly raised/i);
  assert.match(await shift.innerText(), /not raised/i);
  assert.match(await shift.innerText(), /5\s*→\s*2/);   // guidance lines fell

  assert.ok(await page.locator('#view-concalls').isVisible());
  await page.screenshot({ path: path.join(output, 'concalls-1280-light.png'), fullPage: true });

  // ── A quarter we did not watch is not reported as a fall ─────────────────
  wowPayload = wowPartial;
  const page2 = await context.newPage();
  await page2.goto('http://127.0.0.1:8773/', { waitUntil: 'domcontentloaded' });
  await page2.waitForFunction(() => !!window.AltahaNav);
  await openTab(page2, 'wow');
  await page2.locator('#view-wow .wq').waitFor({ state: 'visible' });
  assert.match(await page2.locator('.wq-delta').innerText(), /not comparable yet/i);
  assert.match(await page2.locator('.wq-side.partial').innerText(), /Recording started part-way/i);
  await page2.close();

  // ── Answered before the filings are read ─────────────────────────────────
  // The server says it is still reading. The page says so, asks again by
  // itself, fills in, keeps what the reader opened, and stops asking.
  const wowEmpty = Object.assign({}, wow, { rows: [], reading: true, poll_seconds: 3,
    counts: { orders: 0, firm: 0, with_value: 0, sized: 0, value_not_disclosed: 0, unread: 0, not_firm: 0, wow: 0 } });
  const wowPart = Object.assign({}, wow, { rows: wow.rows.slice(0, 3), reading: true, poll_seconds: 3,
    counts: { orders: 3, firm: 3, with_value: 3, sized: 3, value_not_disclosed: 0, unread: 0, not_firm: 0, wow: 2 } });
  wowQueue = [wowEmpty, wowPart, wow];
  wowCalls = 0;
  const pageR = await context.newPage();
  pageR.on('pageerror', e => errors.push(String(e.stack)));
  await pageR.goto('http://127.0.0.1:8773/', { waitUntil: 'domcontentloaded' });
  await pageR.waitForFunction(() => !!window.AltahaNav);
  await openTab(pageR, 'wow');
  const wr = pageR.locator('#view-wow');
  await wr.locator('.wo-empty.is-loading').waitFor({ state: 'visible' });
  assert.match(await wr.locator('.wo-empty').innerText(), /first read takes a minute or two/i);
  await wr.locator('.wo').first().waitFor({ state: 'visible', timeout: 8000 });
  assert.equal(wowCalls, 2, 'the page should have asked again by itself, once');
  assert.equal(await wr.locator('.wo').count(), 3);
  assert.match(await wr.locator('.wo-counts .st').innerText(), /Checking for new filings/i);
  await wr.locator('.wo-row').first().evaluate(el => { el.open = true; });
  await wr.locator('.wo').nth(6).waitFor({ state: 'attached', timeout: 8000 });
  assert.equal(wowCalls, 3);
  assert.equal(await wr.locator('.wo-row').first().evaluate(el => el.open), true,
    'a row the reader opened must survive the list refreshing');
  assert.equal(await wr.locator('.wo-counts .st').count(), 0, 'nothing is in progress, so nothing says so');
  await pageR.waitForTimeout(4200);
  assert.equal(wowCalls, 3, 'the page must stop asking once the server says it has finished');
  await pageR.close();
  wowQueue = null;

  // ── Phone through desktop, both themes ───────────────────────────────────
  for (const [tab, name] of [['wow', 'wow'], ['concalls', 'concalls']]) {
    await openTab(page, tab);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const theme of ['light', 'dark']) {
        await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
        await page.waitForTimeout(60);
        const over = await page.evaluate(() =>
          document.documentElement.scrollWidth - document.documentElement.clientWidth);
        assert.ok(over <= 1, `horizontal overflow ${over}px on ${name} at ${width}`);
        if (width === 390) {
          await page.screenshot({ path: path.join(output, `${name}-390-${theme}.png`), fullPage: true });
        }
      }
    }
  }


  // ── With a model: fills in while the server reads, key calls first ───────
  ccQueue = [ccReading, ccFilling, ccDone];
  ccCalls = 0;
  const page3 = await context.newPage();
  page3.on('pageerror', e => errors.push(String(e.stack)));
  await page3.setViewportSize({ width: 1280, height: 1000 });
  await page3.goto('http://127.0.0.1:8773/', { waitUntil: 'domcontentloaded' });
  await page3.waitForFunction(() => !!window.AltahaNav);
  await openTab(page3, 'concalls');
  const cc3 = page3.locator('#view-concalls');

  // The server is still reading. The page says so and comes back by itself:
  // this is the state the old page sat in until the request died.
  await cc3.locator('.cc-empty.is-loading').waitFor({ state: 'visible' });
  assert.match(await cc3.locator('.cc-empty').innerText(), /first pass takes a few minutes/i);
  assert.equal(await cc3.locator('.cc-nosum').count(), 0, 'a configured page must not say summaries are off');

  await cc3.locator('.cc').first().waitFor({ state: 'visible', timeout: 8000 });
  assert.equal(ccCalls, 2, 'the page should have asked again by itself, once');
  assert.match(await cc3.locator('.cc-counts').innerText(), /2\s*calls in 21 days/i);
  assert.match(await cc3.locator('.cc-counts .st').innerText(), /Writing summaries/i);

  // The key call is first, flagged, and its brief is open.
  const lead = cc3.locator('.cc').first();
  assert.ok(await lead.evaluate(el => el.classList.contains('is-key')), 'the key call must be listed first');
  assert.match(await lead.locator('.cc-co').innerText(), /Shiprocket Ltd/);
  assert.match(await lead.locator('.cc-co em.key').innerText(), /key call/i);
  assert.match(await cc3.locator('.cc-group').first().innerText(), /key calls/i);
  assert.match(await cc3.locator('.cc-groupnote').innerText(), /not the company or its share/i);
  assert.match(await lead.locator('.cc-hl').innerText(), /Revenue grew 34%/);
  assert.match(await lead.locator('.cc-why').innerText(), /why it is a key call/i);
  assert.equal(await lead.locator('.cc-full').evaluate(el => el.open), true);
  assert.match(await lead.locator('.cc-full').innerText(), /Left unanswered/i);

  // A summary says a model wrote it, names the model, and admits a dropped quote.
  const by = await lead.locator('.cc-by').innerText();
  assert.match(by, /Summary by claude-sonnet-5-5/);
  assert.match(by, /quotes checked against it/i);
  assert.match(by, /1 quote offered by the model did not match and was left out/i);

  // Text from a model is text. A tag in a headline is printed, not run.
  assert.match(await lead.locator('.cc-hl').innerText(), /<script>/);
  assert.equal(await page3.evaluate(() => window.__xss), undefined);
  assert.equal(await cc3.locator('.cc script').count(), 0);

  // The counted layer is still there under the brief, folded, and says no
  // model is involved in it.
  assert.equal(await lead.locator('.cc-more').evaluate(el => el.open), false);
  await lead.locator('.cc-more').evaluate(el => { el.open = true; });
  assert.match(await lead.locator('.cc-more').innerText(), /No model is involved/i);
  assert.match(await lead.locator('.cc-more .cc-shift').innerText(), /What changed since Q4 FY26/i);

  // The call still waiting for its summary shows the extraction, as that.
  const second = cc3.locator('.cc').nth(1);
  assert.match(await second.locator('.cc-wait').innerText(), /summary of this call is being written/i);
  assert.equal(await second.locator('.cc-hl').count(), 0);
  assert.equal(await second.locator('.cc-quote').count(), 2);

  // Every quote on the page, written layer or counted, carries a name.
  const all3 = cc3.locator('.cc-quote');
  for (let i = 0, n = await all3.count(); i < n; i++) {
    const cite = (await all3.nth(i).locator('cite').innerText()).trim();
    assert.ok(cite.length > 2, 'quote missing attribution');
    assert.notEqual(cite.toLowerCase(), 'moderator');
  }

  // Only a call with a written summary can be shared: the card is drawn from
  // the summary, and there is not one yet for the second call.
  assert.equal(await lead.locator('.cc-share').count(), 1);
  assert.equal(await second.locator('.cc-share').count(), 0,
    'a call still waiting for its summary must not offer a card of it');

  // The reader finishes. The second brief arrives without a reload, what the
  // person had opened stays open, and the page stops asking.
  await second.locator('.cc-hl').waitFor({ state: 'visible', timeout: 8000 });
  assert.equal(ccCalls, 3);
  assert.equal(await lead.locator('.cc-more').evaluate(el => el.open), true,
    'a section the reader opened must survive the list refreshing');
  assert.equal(await second.locator('.cc-full').evaluate(el => el.open), false,
    'a call that is not key stays folded to its headline and summary');
  assert.match(await second.locator('.cc-why').innerText(), /How much the call added: low/i);
  assert.match(await cc3.locator('.cc-group').nth(1).innerText(), /other calls/i);
  assert.equal(await cc3.locator('.cc-counts .st').count(), 0, 'nothing is in progress, so nothing says so');
  await second.locator('.cc-full').evaluate(el => { el.open = true; });
  assert.match(await second.locator('.cc-full .cc-none').innerText(), /No commitment is quoted/i);
  await second.locator('.cc-full').evaluate(el => { el.open = false; });
  await page3.waitForTimeout(4200);
  assert.equal(ccCalls, 3, 'the page must stop asking once the server says it has finished');

  // ── Sharing a call ───────────────────────────────────────────────────────
  // The button carries the call it sits on. The headline here has a tag in
  // it, which must survive the attribute as text and nothing else.
  assert.equal(await second.locator('.cc-share').count(), 1, 'a summarised call can be shared');
  const shared = JSON.parse(await lead.locator('.cc-share').getAttribute('data-share'));
  assert.deepEqual([shared.kind, shared.ticker, shared.company, shared.quarter],
    ['concall', 'SHIPROCKET', 'Shiprocket Ltd', 'Q1 FY27']);
  assert.match(shared.headline, /^Revenue grew 34%.*<script>/);

  // Pressing it opens the sheet on that call's card, with X and WhatsApp.
  await lead.locator('.cc-share').evaluate(el => el.click());
  const sheet = page3.locator('#shsheet');
  await sheet.waitFor({ state: 'visible' });
  assert.match(await sheet.locator('#shttl').innerText(), /SHIPROCKET — Q1 FY27 earnings call/);
  assert.match(await sheet.locator('#shsub').innerText(), /written by a model/i);
  assert.match(await sheet.locator('#shcardimg').getAttribute('src'),
    /\/og\/concall\.png\?ticker=SHIPROCKET&period=Q1-FY27$/);
  for (const net of ['x', 'wa']) {
    assert.equal(await sheet.locator(`[data-do="${net}"]`).count(), 1);
    const to = decodeURIComponent(await page3.evaluate(
      ([n, d]) => window.AltahaShare.shareUrl(n, d), [net, shared]));
    assert.match(to, /\/share\/concall\/SHIPROCKET\?period=Q1-FY27/, `${net} must carry the call's link`);
    assert.match(to, /Shiprocket Ltd — Q1 FY27 earnings call/);
    assert.match(to, /Revenue grew 34%/);
    assert.doesNotMatch(to, /onrender\.com/, 'a post must not name the API host');
  }
  await sheet.locator('.shx').evaluate(el => el.click());
  await sheet.waitFor({ state: 'hidden' });
  assert.equal(await page3.evaluate(() => window.__xss), undefined);

  await page3.screenshot({ path: path.join(output, 'concalls-brief-1280-light.png'), fullPage: true });
  for (const width of [320, 390, 768, 1280]) {
    await page3.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page3.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page3.waitForTimeout(60);
      const over = await page3.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 1, `horizontal overflow ${over}px on the concall briefs at ${width}`);
      if (width === 390) {
        await page3.screenshot({ path: path.join(output, `concalls-brief-390-${theme}.png`), fullPage: true });
      }
    }
  }
  await page3.close();

  // ── Arriving from a shared link ──────────────────────────────────────────
  // The link names a company. Its call is brought into view with its brief
  // open, and the stock is not analysed instead: the reader was sent a call.
  ccQueue = [ccDone];
  const page4 = await context.newPage();
  page4.on('pageerror', e => errors.push(String(e.stack)));
  let analysed = 0;
  page4.on('request', r => { if (new URL(r.url()).pathname === '/analyze') analysed++; });
  await page4.goto('http://127.0.0.1:8773/?go=concalls&q=QUIETCO', { waitUntil: 'domcontentloaded' });
  const sent = page4.locator('#view-concalls .cc.is-arrived');
  await sent.waitFor({ state: 'visible', timeout: 8000 });
  assert.equal(await sent.count(), 1);
  assert.match(await sent.locator('.cc-co').innerText(), /Quiet Industries Ltd/);
  assert.equal(await sent.locator('.cc-full').evaluate(el => el.open), true,
    'the call a link was sent for opens with its brief showing');
  assert.equal(await page4.locator('#view-concalls .cc-group', { hasText: /you were sent/i }).count(), 0,
    'a call already in the list is not listed twice');
  await page4.waitForTimeout(600);
  assert.equal(analysed, 0, 'a shared call must not run the stock analysis');
  await page4.close();

  // A link older than the list. The call is asked for by name and shown above
  // the list, rather than the reader landing on a page that does not have it.
  oneCall = {
    available: true, symbol: 'FARCO', company: 'Far Away Ltd', quarter: 'Q4 FY26',
    filed_at: '2026-05-20T18:00:00+05:30', pdf: 'https://www.bseindia.com/x/far.pdf',
    digest: Object.assign({}, ccShiprocket.digest, { quarter: 'Q4 FY26', call_date: '2026-05-18' }),
    versus_previous: { available: false, reason: 'No earlier transcript has been read for this company yet.' },
    brief: Object.assign({}, ccBrief, { headline: 'Capacity doubles at the Hosur plant by March' }),
    summary_configured: true, summary: null
  };
  const page5 = await context.newPage();
  page5.on('pageerror', e => errors.push(String(e.stack)));
  await page5.goto('http://127.0.0.1:8773/?go=concalls&q=FARCO', { waitUntil: 'domcontentloaded' });
  const far = page5.locator('#view-concalls .cc.is-arrived');
  await far.waitFor({ state: 'visible', timeout: 8000 });
  assert.match(await far.locator('.cc-hl').innerText(), /Capacity doubles at the Hosur plant/);
  assert.match(await page5.locator('#view-concalls .cc-group').first().innerText(), /you were sent/i);
  assert.equal(await page5.locator('#view-concalls .cc').count(), 3, 'the list is still there under it');
  assert.equal(await far.locator('.cc-share').count(), 1);
  await page5.close();
  oneCall = null;
  ccQueue = null;

  const relevant = errors.filter(e => /wow\.js|concalls\.js|share\.js/.test(e));
  assert.deepEqual(relevant, []);

  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({
    viewports: [320, 390, 768, 1280], themes: ['light', 'dark'],
    lazyLoaded: true, undisclosedNeverZero: true, thresholdVisible: true,
    wowOrdersLead: true, bidNeverWow: true, answeredBeforeReading: true,
    quarterComparison: true, unwatchedQuarterNotCompared: true,
    everyQuoteAttributed: true, noSummaryStatedPlainly: true,
    fillsInWhileReading: true, keyCallsFirst: true, modelNamedOnEachSummary: true,
    stopsPollingWhenDone: true, sharesOnlySummarisedCalls: true,
    sharedLinkOpensItsCall: true, errors
  }, null, 2));

  await browser.close(); server.close();
  console.log('WOW orders and Concall summaries Chromium checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
