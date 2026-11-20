/* WOW orders and Concall summaries in a real Chromium, against fixtures shaped
   exactly like the API payloads. No live calls.

   What this guards:
     · an order whose value the company did not disclose must render as "value
       not disclosed" — never as zero, never ranked above a disclosed one
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
       says it has finished */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/filings-views');
fs.mkdirSync(output, { recursive: true });

const wow = {
  available: true, threshold_pct: 10,
  counts: { orders: 3, with_value: 2, value_not_disclosed: 1, wow: 1 },
  note: '', source: 'BSE corporate announcements, Regulation 30. Order values are read from the filed document, not the headline.',
  explain: 'An order is called WOW when its disclosed value is at least 10% of the company’s market capitalisation. Orders whose value the company did not disclose are listed but never ranked, and never given an assumed figure.',
  rows: [
    { symbol: 'SMALLCO', company: 'Small Engineering Ltd', headline: 'Receipt of work order from NHAI for a highway package', at: '2026-09-12T11:02:00+05:30', date: '2026-09-12', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/1.pdf', value_cr: 450.75, value_basis: 'stated next to an order-value phrase in the filing', value_confident: true, currency_converted: false, excerpt: 'The Company has received a work order. The order value is Rs. 450.75 crore, to be executed over 24 months.', market_cap_cr: 1050, pct_of_market_cap: 42.93, wow: true },
    { symbol: 'BIGCO', company: 'Big Infra Ltd', headline: 'Order win intimation under Regulation 30', at: '2026-09-11T15:40:00+05:30', date: '2026-09-11', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/2.pdf', value_cr: 320, value_basis: 'largest rupee figure in the filing; the filing does not label it as the order value', value_confident: false, currency_converted: true, excerpt: 'The company informed that USD 38 million was involved in the transaction.', market_cap_cr: 42000, pct_of_market_cap: 0.76, wow: false },
    { symbol: 'ACCURACY', company: 'Accuracy Shipping Ltd', headline: 'Receipt Of Letter Of Intent For Setting Up Of Container Freight Station At Kandla', at: '2026-09-10T09:15:00+05:30', date: '2026-09-10', quarter: 'Q2 FY27', pdf: 'https://www.bseindia.com/x/3.pdf', value_cr: null, value_basis: null, value_confident: false, currency_converted: false, excerpt: null, market_cap_cr: null, pct_of_market_cap: null, wow: false }
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
  let wowCalls = 0, ccCalls = 0, wowPayload = wow, ccQueue = null;
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/wow-orders') { wowCalls++; return route.fulfill({ json: wowPayload }); }
    if (u.pathname === '/concalls') {
      ccCalls++;
      const next = ccQueue ? (ccQueue.length > 1 ? ccQueue.shift() : ccQueue[0]) : concalls;
      return route.fulfill({ json: next });
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

  assert.equal(await page.locator('#view-wow .wo').count(), 3);
  // The threshold is on the page.
  assert.match(await page.locator('.wo-counts').innerText(), /threshold 10% of market cap/i);

  // A disclosed order leads with its share of the company, not the rupee figure.
  const first = page.locator('#view-wow .wo').first();
  assert.match(await first.innerText(), /42\.9%/);
  assert.match(await first.innerText(), /of market cap/i);
  assert.match(await first.innerText(), /WOW/);

  // An undisclosed value says so, is last, and shows no number.
  const last = page.locator('#view-wow .wo').last();
  assert.match(await last.innerText(), /value not disclosed/i);
  assert.doesNotMatch(await last.innerText(), /₹0|0\.0%/);
  assert.equal(await last.locator('.wo-pct.none').count(), 1);

  // An unlabelled or converted figure is flagged rather than presented flat.
  const mid = page.locator('#view-wow .wo').nth(1);
  assert.match(await mid.innerText(), /unlabelled figure/i);
  assert.match(await mid.innerText(), /converted/i);

  // The evidence for a figure is one disclosure away, and the figure never
  // appears without it. Opened through the element's own `open` property
  // rather than a synthetic click: the homepage mounts a fixed bar and a
  // scroll-reveal observer over this content, and fighting those would be a
  // test of the page chrome, not of whether the evidence is there.
  await page.evaluate(() => {
    document.querySelectorAll('#view-wow .wo-ev').forEach(d => { d.open = true; });
  });
  const evidence = page.locator('#view-wow .wo-ev').first();
  assert.match(await evidence.locator('blockquote').innerText(), /450\.75 crore/);
  assert.match(await evidence.locator('.basis').innerText(), /order-value phrase/);
  // A row with no disclosed value has nothing to disclose and shows no panel.
  assert.equal(await last.locator('.wo-ev').count(), 0);

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
  ccQueue = null;

  const relevant = errors.filter(e => /wow\.js|concalls\.js/.test(e));
  assert.deepEqual(relevant, []);

  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({
    viewports: [320, 390, 768, 1280], themes: ['light', 'dark'],
    lazyLoaded: true, undisclosedNeverZero: true, thresholdVisible: true,
    quarterComparison: true, unwatchedQuarterNotCompared: true,
    everyQuoteAttributed: true, noSummaryStatedPlainly: true,
    fillsInWhileReading: true, keyCallsFirst: true, modelNamedOnEachSummary: true,
    stopsPollingWhenDone: true, errors
  }, null, 2));

  await browser.close(); server.close();
  console.log('WOW orders and Concall summaries Chromium checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
