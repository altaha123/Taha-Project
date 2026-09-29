/* The stock page's headline figures, in a real Chromium. The /analyze
   responses are shaped as backend/main.py returns them; no live calls.

   What this is actually guarding:
     · THE RATIO STRIP PRINTS WHAT THE API SENT. stock.js once held two
       functions named `plain` in one closure; the later declaration hoisted
       over the earlier, so every header ratio went through the wrong one —
       rounded to a whole number with its unit dropped. Reliance's debt/equity
       of 0.3 read "0", its ROCE read "9" with no %. Nothing threw.
     · A COMPANY OUTSIDE THE SCAN IS SCORED, AND SAYS HOW. The API ranks it
       against the scan's cohort on request. The first request can outlast the
       API's wait and come back "SCORING"; the page must say so, ask again,
       and then show the number with its provenance — "ranked on request" —
       rather than a bare figure indistinguishable from a scanned one.
     · IT STOPS ASKING. A score that never arrives leaves the honest message
       on screen after three tries; it does not poll forever.
     · A US LISTING SAYS WHY IT HAS NO SCORE ("NOT RANKED"), rather than the
       old blanket "NOT SCORED" that read as a fault. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/stock-score');
fs.mkdirSync(output, { recursive: true });

const ratios = {
  market_cap: 16206490000000, price: 1197.6, high_52w: 1584.97, low_52w: 1197.6,
  pe: 22.4, book_value: 668.04, dividend_yield: 0.49, roce: 9.4, roe: 8.7,
  debt_to_equity: 0.3, price_to_book: 1.79
};

const base = (extra) => Object.assign({
  ticker: 'RELIANCE.NS', name: 'Reliance Industries Limited', exchange: 'NSE',
  currency: 'INR', price: 1197.6, ratios: ratios, peers: {},
  technical: { score: 9, checks: [] }, fundamental: { score: 75, checks: [] },
  profile: { sector: 'Energy', industry: 'Oil & Gas Refining & Marketing' },
  disclaimer: 'Educational tool.'
}, extra);

const pending = base({
  scoring: { score: null, label: 'SCORING', pending: true, confidence: 0,
             basis: 'Altaha Score v4 unavailable',
             summary: "Scoring RELIANCE against the scan's 200 companies — this takes a few seconds the first time. Refresh in a moment." },
  altaha_score_v4: { available: false, pending: true, reason: 'pending', methodology_version: 'v4',
                     message: "Scoring RELIANCE against the scan's 200 companies — this takes a few seconds the first time. Refresh in a moment." }
});

const note = "Not in the scan's analysed cohort, so ranked on request against its 200 companies, " +
             'using prices and filings as of 2026-09-29 — the same date its peers were measured on.';
const scored = base({
  percentile: 44,
  scoring: { score: 47.3, label: 'MIXED', tone: 'mixed', confidence: 71.5, horizon: 'position',
             horizon_label: 'Weeks to months', model: { name: 'Cyclical' },
             basis: 'Altaha Score v4 · peer-relative · as of 2026-09-29 · ranked on request against the scan cohort',
             summary: 'Strongest on business quality (68/100); weakest on price trend (12/100).',
             cohort_note: note, pillars: { quality: 68, momentum: 12 } },
  altaha_score_v4: { methodology_version: 'v4', cohort: { basis: 'on_request', peers: 200, note: note } }
});

const us = base({
  ticker: 'AAPL', name: 'Apple Inc.', exchange: 'US', currency: 'USD',
  scoring: { score: null, label: 'NOT RANKED', confidence: 0, basis: 'Altaha Score v4 unavailable',
             summary: 'Altaha Score v4 ranks Indian companies against their NSE peers. US listings have no peer cohort yet, so this page shows the technical and fundamental checks without a headline score.' },
  altaha_score_v4: { available: false, reason: 'no_cohort_for_market', methodology_version: 'v4',
                     message: 'Altaha Score v4 ranks Indian companies against their NSE peers.' }
});

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

async function open(browser, port, ticker, answers) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  const seen = { analyze: 0 };
  page.on('pageerror', e => errors.push(String(e.stack)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/analyze') {
      const a = answers[Math.min(seen.analyze, answers.length - 1)];
      seen.analyze++;
      return route.fulfill({ json: a });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
  // The retry waits six seconds of page time; a fake clock runs it in none.
  await page.clock.install();
  await page.goto(`http://127.0.0.1:${port}/stock.html?ticker=${ticker}`, { waitUntil: 'domcontentloaded' });
  await page.locator('#kgrid .ktile').first().waitFor();
  return { context, page, errors, seen };
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });

  // ── THE RATIO STRIP ──────────────────────────────────────────────────────
  {
    const { context, page, errors } = await open(browser, port, 'RELIANCE', [scored]);
    const tiles = await page.evaluate(() => Object.fromEntries(
      [...document.querySelectorAll('#kgrid .ktile')].map(t =>
        [t.querySelector('.k').textContent.trim(), t.querySelector('.v').textContent.trim()])));
    assert.equal(tiles['P/E'], '22.4', `P/E reads ${tiles['P/E']}`);
    assert.equal(tiles['Dividend yield'], '0.49%', `dividend yield reads ${tiles['Dividend yield']}`);
    assert.equal(tiles['ROCE'], '9.4%', `ROCE reads ${tiles['ROCE']}`);
    assert.equal(tiles['ROE'], '8.7%', `ROE reads ${tiles['ROE']}`);
    assert.equal(tiles['Debt / equity'], '0.3', `debt/equity reads ${tiles['Debt / equity']}`);

    // A scored-on-request company shows its number and where its peers came from.
    await page.clock.runFor(1500);
    assert.equal(await page.locator('#scorelb').innerText(), 'MIXED');
    const basis = await page.locator('#basis').innerText();
    assert.match(basis, /ranked on request/i);
    assert.match(basis, /against its 200 companies/);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, 'scored-on-request.png'), fullPage: false });
    await context.close();
  }

  // ── PENDING, THEN SCORED ─────────────────────────────────────────────────
  {
    const { context, page, errors, seen } = await open(browser, port, 'RELIANCE', [pending, scored]);
    assert.equal(await page.locator('#scorelb').innerText(), 'SCORING');
    assert.equal(await page.locator('#scoren').innerText(), '—');
    assert.match(await page.locator('#basis').innerText(), /takes a few seconds the first time/);
    assert.equal(seen.analyze, 1);
    await page.clock.runFor(6500);
    await page.waitForFunction(() => document.getElementById('scorelb').textContent === 'MIXED');
    await page.clock.runFor(1500);
    assert.equal(seen.analyze, 2, 'one retry once the first answer said the score was pending');
    assert.match(await page.locator('#basis').innerText(), /ranked on request/i);
    // Scored now, so no further requests however long the reader stays.
    await page.clock.runFor(30000);
    assert.equal(seen.analyze, 2, 'a scored page stops asking');
    assert.deepEqual(errors, []);
    await context.close();
  }

  // ── IT STOPS ASKING ──────────────────────────────────────────────────────
  {
    const { context, page, errors, seen } = await open(browser, port, 'RELIANCE', [pending]);
    for (let i = 0; i < 6; i++) await page.clock.runFor(6500);
    assert.equal(seen.analyze, 4, `first load plus three retries, then stop — saw ${seen.analyze}`);
    assert.equal(await page.locator('#scorelb').innerText(), 'SCORING');
    assert.deepEqual(errors, []);
    await context.close();
  }

  // ── A US LISTING ─────────────────────────────────────────────────────────
  {
    const { context, page, errors, seen } = await open(browser, port, 'AAPL', [us]);
    assert.equal(await page.locator('#scorelb').innerText(), 'NOT RANKED');
    assert.match(await page.locator('#basis').innerText(), /no peer cohort/i);
    await page.clock.runFor(20000);
    assert.equal(seen.analyze, 1, 'nothing pending, nothing retried');
    assert.deepEqual(errors, []);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('stock score browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
