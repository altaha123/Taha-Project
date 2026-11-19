/* The stock page as a whole, in a real Chromium.
   Run from the repository root: node frontend/tests/stock-page-browser.cjs

   The responses are the real modules' own (backend/tests/
   make_stock_page_fixture.py): /analyze over a ranked cohort, the peer table
   over a throwaway store, the press and filings assemblers over canned search
   results and exchange rows. No live calls.

   What this is actually guarding:
     · THE PAGE HAS AN ORDER. Name, price and score, then the section bar
       directly under them, then cards. The bar used to sit under a strip of
       lens badges, nine figures and a paragraph.
     · THE SCORE ADDS UP ON SCREEN. The points printed against each pillar
       sum to the weighted sum printed under them, and that sum, pulled
       toward 50 by the confidence printed beside it, is the number on the
       dial. The old page listed checks whose points went into a different
       score altogether.
     · A HOLDING PERIOD CHANGES THE ARITHMETIC AND ASKS NOBODY. All three are
       in the one response.
     · A BANK IS NOT SHOWN A DEBT-TO-EQUITY. Nor a ROCE, here or among peers.
     · PEERS ARE NAMED, THE COMPANY'S OWN ROW IS MARKED, AND SORTING ONLY
       REORDERS. A company with no figure sorts last in both directions.
     · A LOGO IS THE COMPANY'S INITIALS UNTIL ITS MARK HAS LOADED AT A USABLE
       SIZE. The favicon service answers an unknown domain with a 16-pixel
       placeholder, which must never replace the initials.
     · PRESS AND FILINGS ARE THREE LISTS, AND A LINK FROM A FEED IS ONLY EVER
       http(s). A headline's `javascript:` address is printed as text.
     · AN UNANSWERED SEARCH IS NOT "NO NEWS".
     · NOTHING SLOW IS FETCHED TO SHOW A PRICE. Peers load with their section.
     · EVERY SECTION FITS A PHONE, and nothing moves for a reader who asked
       for reduced motion. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/stock-page');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/stock-page.json'), 'utf8'));
const lenses = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/lenses.json'), 'utf8'));

const PNG64 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAUUlEQVR42u3PMQ0AMAgAMJgG1KEOqVPBQdI6aFZPXPbiOAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAYF9HyTJAY7THInWAAAAAElFTkSuQmCC', 'base64');
const PNG16 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGklEQVR42mMUiVrAQApgYiARjGoY1TB0NAAAbHUBLsKWU5AAAAAASUVORK5CYII=', 'base64');

const types = { '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.html': 'text/html; charset=utf-8', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(root, p === '/' ? '/index.html' : p);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

// Shaped as backend/deals.py for_symbol() returns them.
const deals = { available: true, symbol: 'NORTHBANK', days: 90, count: 2, rows: [
  { symbol: 'NORTHBANK', client: 'Quarry Lane Capital', side: 'BUY', qty: 5200000, price: 1141.5,
    value_cr: 593.58, date: '12-Nov-2026', kind: 'block', prop_desk: false, institutional: true },
  { symbol: 'NORTHBANK', client: 'Tidewater Securities', side: 'SELL', qty: 4100000, price: 1139.0,
    value_cr: 466.99, date: '03-Nov-2026', kind: 'bulk', prop_desk: true, institutional: false },
] };

const year = Array.from({ length: 120 }, (_, i) => {
  const v = 880 + i * 2.3 + (i % 7) * 4;
  return [new Date(Date.UTC(2025, 10, 20) + i * 3 * 86400000).toISOString().slice(0, 10), v, v, v, v, 1000];
});

async function open(browser, port, opts) {
  opts = opts || {};
  const context = await browser.newContext(Object.assign(
    { viewport: { width: 1280, height: 1000 } }, opts.context));
  const page = await context.newPage(), errors = [], asked = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) return route.abort();
    if (u.hostname === 'www.google.com' && u.pathname === '/s2/favicons') {
      // The company's own domain has a real mark; every other domain gets
      // what the service really sends for one it does not know.
      const real = u.searchParams.get('domain') === 'northernunion.example';
      assert.equal(route.request().headers().referer, undefined, 'the page told the icon service where it was');
      return route.fulfill({ contentType: 'image/png', body: real ? PNG64 : PNG16 });
    }
    asked.push(u.pathname + u.search);
    const analyze = opts.analyze ? opts.analyze(JSON.parse(JSON.stringify(fx.analyze))) : fx.analyze;
    switch (u.pathname) {
      case '/analyze': return route.fulfill({ json: analyze });
      case '/chart': return route.fulfill({ json: { currency: 'INR', day_change_pct: 0.84, candles: year } });
      case '/stock/peers': return route.fulfill({ json: fx.peers });
      case '/stock/news': return route.fulfill({ json: opts.news === undefined ? fx.news : opts.news });
      case '/stock/filings': return route.fulfill({ json: opts.filings === undefined ? fx.filings : opts.filings });
    }
    if (u.pathname === '/deals/NORTHBANK') return route.fulfill({ json: deals });
    if (u.pathname.startsWith('/api/lenses/stock/')) return route.fulfill({ json: lenses.stock.GROW });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
  await page.goto(`http://127.0.0.1:${port}/stock.html?ticker=NORTHBANK${opts.hash || ''}`,
                  { waitUntil: 'domcontentloaded' });
  // Attached, not visible: a link that names a section opens on that section.
  await page.locator('#kgrid .ktile').first().waitFor({ state: 'attached' });
  return { context, page, errors, asked };
}

const num = t => Number(String(t).replace(/[^0-9.\-]/g, ''));
const fits = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    const sc = fx.analyze.scoring;

    /* ── 1. The order of the page, and the Overview ─────────────────────── */
    {
      const t = await open(browser, port);
      const { page } = t;
      assert.deepEqual(await page.locator('.stk-pane-btn').evaluateAll(a => a.map(b => b.dataset.p)),
        ['info', 'chart', 'scores', 'owners', 'funda', 'peers', 'deliv', 'news']);
      const y = async sel => (await page.locator(sel).boundingBox()).y;
      assert.ok(await y('#nm') < await y('#panes'), 'the section bar is above the name');
      assert.ok(await y('#panes') < await y('#kgrid'), 'the figures are above the section bar');
      await page.locator('#stk-lenses .ln-strip').waitFor();
      assert.ok(await y('#panes') < await y('#stk-lenses'), 'the lenses are above the section bar again');
      assert.equal(await page.locator('.ov-rail #stk-lenses').count(), 1, 'the lenses left the side column');

      // A bank: no ROCE, no debt to equity, and its price to book instead.
      const tiles = await page.evaluate(() => Object.fromEntries(
        [...document.querySelectorAll('#kgrid .ktile')].map(t =>
          [t.querySelector('.k').textContent.trim(), t.querySelector('.v').textContent.trim()])));
      assert.deepEqual(Object.keys(tiles),
        ['Market cap', 'P/E', 'Price / book', 'Dividend yield', 'ROE', 'Book value']);
      assert.equal(tiles['Price / book'], '1.59');
      assert.equal(tiles['P/E'], '11.8');
      assert.match(await page.locator('#key-vs').innerText(), /Against 16 Financial Services peers/i);
      assert.match(await page.locator('#krange').innerText(), /At the high/);

      // The year is drawn and the day's move is the day's.
      await page.locator('#ov-spark svg').waitFor();
      assert.equal(await page.locator('#chg').innerText(), '+0.84% today');
      assert.equal(await page.locator('#ov-rets .ov-ret').count(), 4);

      // The score card shows the pillars that count at this holding period.
      const bars = await page.locator('#ov-score .ovs-r span:first-child').allInnerTexts();
      assert.ok(bars.includes('Business quality') && !bars.includes('Trading interest'),
        'a pillar with no weight is drawn as though it counted: ' + bars);
      assert.equal(await page.locator('#stk-scorechip-n').innerText(), String(Math.round(sc.score)));
      assert.match(await page.locator('#stk-scorechip').innerText(),
        new RegExp('Altaha Score · ' + sc.band));

      // Nothing slow was fetched to show this screen.
      assert.ok(!t.asked.some(u => u.startsWith('/stock/peers')), 'peers were fetched before their section');
      assert.ok(!t.asked.some(u => /^\/(shareholding|fundamentals|delivery|deals)/.test(u)),
        'a section was fetched before it was opened: ' + t.asked.join(' '));

      // The press and the filings arrive once the page is up, and the newest
      // of both are on the Overview, each marked as which it is.
      await page.locator('#ov-latest .lt-l li').first().waitFor();
      const kinds = await page.locator('#ov-latest .lt-k').allInnerTexts();
      assert.ok(kinds.some(k => /press/i.test(k)) && kinds.some(k => /filing/i.test(k)), String(kinds));
      // The page says what kind of business it is; the name that gets
      // searched for is the API's own record, never something a page sent.
      const want = t.asked.find(u => u.startsWith('/stock/news'));
      assert.match(want, /industry=Banks%20-%20Regional/);
      assert.ok(!/[?&]name=/.test(want), 'the page sent the API a name to search for');

      // The logo: initials first, then the company's own mark over them.
      await page.locator('#logo.has-img img').waitFor();
      assert.equal(await page.locator('#logo .lg-m').innerText(), 'NU');
      await page.screenshot({ path: path.join(output, 'overview-1280.png'), fullPage: true });

      /* ── 2. The score adds up ──────────────────────────────────────────── */
      await page.locator('#stk-scorechip').click();
      assert.ok(await page.locator('#pane-scores').isVisible());
      assert.match(page.url(), /#scores$/);
      await page.waitForFunction(n => document.getElementById('scoren').textContent === n,
                                 String(Math.round(sc.score)));
      assert.equal(await page.locator('#scorelb').innerText(), sc.band.toUpperCase());
      assert.match(await page.locator('#score-rank').innerText(),
        new RegExp('Ranks above ' + fx.analyze.percentiles.position + '% of the ' + fx.analyze.cohort_size));

      const points = (await page.locator('#pillars .pl:not(.pl-head) .pl-p').allInnerTexts()).map(num);
      assert.equal(points.length, sc.contribution.length);
      const sum = num(await page.locator('#pillars .pl-sum b').innerText());
      assert.ok(Math.abs(points.reduce((a, b) => a + b, 0) - sum) <= 0.11 * points.length,
        `the points ${points} do not add up to the ${sum} printed under them`);
      assert.equal(sum, Number(sc.raw_score.toFixed(1)));
      const eq = await page.locator('#pillars .pl-eq').innerText();
      // The API sends confidence to one decimal, so the line is exact to that.
      const final = 50 + (sc.raw_score - 50) * sc.confidence / 100;
      assert.ok(Math.abs(final - sc.score) < 0.06, `the fixture itself does not add up: ${final} vs ${sc.score}`);
      assert.match(eq, new RegExp(`= ${sc.score.toFixed(1)}$`));
      assert.ok(eq.includes(`(${sc.raw_score.toFixed(1)} − 50) × ${sc.confidence.toFixed(1)}%`), eq);
      assert.match(await page.locator('#pillars .pl-miss').innerText(),
        /Not measured: (Financial strength, Valuation|Valuation, Financial strength)/);
      // Each bar reaches the rank printed beside it.
      await page.waitForTimeout(1300);
      const widths = await page.locator('#pillars .pl:not(.pl-head)').evaluateAll(rows => rows.map(r =>
        [Math.round(100 * r.querySelector('.fill').offsetWidth / r.querySelector('.pl-bar').offsetWidth),
         Number(r.querySelector('.pl-s').textContent)]));
      widths.forEach(([w, s]) => assert.ok(Math.abs(w - s) <= 2, `a bar at ${w}% beside a rank of ${s}`));

      assert.equal(await page.locator('#drivers .drv-col.up li').count(), 3);
      assert.match(await page.locator('#drivers').innerText(), /12-month price momentum/);
      const measured = fx.analyze.scoring.factor_ledger.filter(e => e.applicable !== false).length;
      assert.equal(await page.locator('#factors .fl-r').count(), measured);
      assert.match(await page.locator('#factors .fl-g.off h3').innerText(), /not counted at this holding period/i);
      // The older checks are there, folded, and say what they are.
      assert.equal(await page.locator('#diag').getAttribute('open'), null);
      assert.match(await page.locator('#diag-x').innerText(), /not part of the score/i);
      await page.screenshot({ path: path.join(output, 'score-1280.png'), fullPage: true });

      /* ── 3. Another holding period, and nobody asked ───────────────────── */
      const before = t.asked.filter(u => u.startsWith('/analyze')).length;
      const inv = fx.analyze.horizons.invest;
      await page.locator('#hz [data-hz="invest"]').click();
      await page.waitForFunction(n => document.getElementById('scoren').textContent === n,
                                 String(Math.round(inv.score)));
      assert.equal(num(await page.locator('#pillars .pl-sum b').innerText()), Number(inv.raw_score.toFixed(1)));
      assert.match(await page.locator('#score-rank').innerText(),
        new RegExp('Ranks above ' + fx.analyze.percentiles.invest + '%'));
      assert.equal(await page.locator('#hz [data-hz="invest"]').getAttribute('aria-pressed'), 'true');
      assert.equal(t.asked.filter(u => u.startsWith('/analyze')).length, before, 'a holding period asked the API');

      /* ── 4. Peers ──────────────────────────────────────────────────────── */
      await page.locator('#pane-btn-peers').click();
      await page.locator('.pr-table tbody tr').first().waitFor();
      assert.equal(t.asked.filter(u => u.startsWith('/stock/peers')).length, 1);
      assert.equal(await page.locator('.pr-table tbody tr').count(), fx.peers.rows.length);
      assert.equal(await page.locator('.pr-table tbody tr.self').count(), 1);
      assert.match(await page.locator('.pr-table tbody tr.self').innerText(), /NORTHBANK · this company/i);
      const heads = (await page.locator('.pr-table thead th').allInnerTexts()).map(h => h.toLowerCase());
      assert.ok(!heads.some(h => /debt|margin/.test(h)), 'a bank was given a debt-to-equity column: ' + heads);
      // The company was ranked on request, so the scan sent no score for its
      // row; the page fills in the one it already holds.
      assert.equal(await page.locator('.pr-table tbody tr.self .pr-score').innerText(),
        String(Math.round(sc.score)));
      const caps = () => page.locator('.pr-table tbody tr td:nth-child(2)').allInnerTexts().then(a => a.map(num));
      assert.deepEqual(await caps(), (await caps()).slice().sort((a, b) => b - a), 'not largest first');
      // Sorting reorders; a company with no score is last both ways.
      const scores = () => page.locator('.pr-table tbody tr td:last-child').allInnerTexts();
      await page.locator('[data-sort="score"]').click();
      let col = await scores();
      const held = col.filter(v => v !== '—').map(Number);
      assert.deepEqual(held, held.slice().sort((a, b) => b - a));
      assert.ok(col.indexOf('—') > held.length - 1, 'a blank sorted above a number');
      await page.locator('[data-sort="score"]').click();
      col = await scores();
      assert.deepEqual(col.filter(v => v !== '—').map(Number), held.slice().sort((a, b) => a - b));
      assert.equal(col[col.length - 1], '—');
      assert.equal(await page.locator('.pr-table thead th[aria-sort="ascending"]').count(), 1);
      assert.match(await page.locator('.pr-table tfoot').innerText(), /Peer median/);
      // Every row has its initials; a 16-pixel placeholder never replaced them.
      await page.waitForTimeout(400);
      assert.equal(await page.locator('.pr-table tbody .lg .lg-m').count(), fx.peers.rows.length);
      assert.equal(await page.locator('.pr-table tbody .lg.has-img').count(), 0,
        'the icon service\'s placeholder was shown as a company\'s logo');
      assert.match(await page.locator('.pr-table tbody tr:not(.self) a.pr-a').first().getAttribute('href'),
        /^stock\.html\?ticker=[A-Z]+$/);
      await page.screenshot({ path: path.join(output, 'peers-1280.png'), fullPage: true });

      /* ── 5. News and filings ───────────────────────────────────────────── */
      await page.locator('#pane-btn-news').click();
      await page.locator('#news-company .nw-i').first().waitFor();
      assert.equal(await page.locator('#news-company .nw-i').count(), fx.news.company.rows.length);
      assert.equal(await page.locator('#news-ind-h').innerText(), 'Industry: Banks');
      const all = fx.news.industry.rows.length;
      assert.equal(await page.locator('#news-industry .nw-i').count(), all);
      assert.match(await page.locator('#news-industry .nw-i').first().innerText(), /Interest rates/);
      await page.locator('#news-industry [data-driver="Asset quality"]').click();
      const narrowed = await page.locator('#news-industry .nw-i').count();
      assert.ok(narrowed >= 1 && narrowed < all);
      assert.ok((await page.locator('#news-industry .nw-i').allInnerTexts()).every(x => /Asset quality/.test(x)));
      for (const a of await page.locator('#pane-news a[target="_blank"]').all()) {
        assert.match(await a.getAttribute('rel'), /noopener/);
        assert.match(await a.getAttribute('href'), /^https?:\/\//);
      }
      assert.equal(await page.locator('#filings-body .fil-i').count(), fx.filings.rows.length);
      await page.locator('#filings-cats [data-cat="Results"]').click();
      const results = fx.filings.rows.filter(r => r.category === 'Results').length;
      assert.equal(await page.locator('#filings-body .fil-i').count(), results);
      await page.locator('#filings-cats [data-cat=""]').click();
      // A filing with no document has no link to open.
      assert.equal(await page.locator('#filings-body .fil-i', { hasText: 'Closure of trading window' })
        .locator('a').count(), 0);
      // Big trades: read with this section and not before it, each with its
      // side, and a proprietary desk marked as one.
      await page.locator('#deals-body .dl-i').first().waitFor();
      assert.equal(await page.locator('#deals-body .dl-i').count(), 2);
      assert.match(await page.locator('#deals-body .dl-i').first().innerText(),
        /Bought[\s\S]*Quarry Lane Capital[\s\S]*Institution[\s\S]*52,00,000[\s\S]*593\.58 cr/i);
      assert.match(await page.locator('#deals-body .dl-i').nth(1).innerText(), /Sold[\s\S]*Proprietary desk/i);
      await page.screenshot({ path: path.join(output, 'news-1280.png'), fullPage: true });

      // Scrolled past the name, the bar carries the company and its price.
      await page.evaluate(() => scrollTo(0, 700));
      await page.locator('#stk-panebar.is-stuck #stk-mini').waitFor();
      assert.match(await page.locator('#stk-mini').innerText(), /NORTHBANK[\s\S]*1,156\.00[\s\S]*\+0\.84%/);
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 6. A company that is not a lender keeps its figures ────────────── */
    {
      const t = await open(browser, port, { analyze: a => {
        a.business_model = { key: 'compounder', name: 'Compounder' };
        a.ratios.roce = 21.4; a.ratios.debt_to_equity = 0.31;
        return a;
      } });
      const labels = await t.page.locator('#kgrid .ktile .k').allInnerTexts();
      assert.ok(labels.some(l => /roce/i.test(l)) && labels.some(l => /debt/i.test(l)), String(labels));
      assert.equal(labels.length, 8);
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }

    /* ── 7. A feed cannot hand the page a script, and silence is not "none" ─ */
    {
      const news = JSON.parse(JSON.stringify(fx.news));
      news.company.rows[0].url = 'javascript:alert(document.domain)';
      news.company.rows[1].headline = '<img src=x onerror=alert(1)> bonds';
      const filings = JSON.parse(JSON.stringify(fx.filings));
      filings.rows[0].pdf = 'javascript:alert(1)';
      const t = await open(browser, port, { news, filings, hash: '#news' });
      // The address named the section, so the page opened on it.
      await t.page.locator('#news-company .nw-i').first().waitFor();
      assert.ok(await t.page.locator('#pane-news').isVisible(), 'a link to #news did not open the news');
      assert.equal(await t.page.locator('#news-company .nw-i').first().locator('a').count(), 0,
        'a javascript: address from a feed became a link');
      assert.equal(await t.page.locator('#news-company img').count(), 0, 'a headline was read as markup');
      assert.equal(await t.page.locator('#filings-body .fil-i').first().locator('a').count(), 0);
      assert.equal(await t.page.locator('#pane-news a[href^="javascript"]').count(), 0);
      assert.deepEqual(t.errors, []);
      await t.context.close();

      const quiet = await open(browser, port, { hash: '#news', filings: null,
        news: { symbol: 'NORTHBANK', kind: 'press',
                company: { rows: [], searched: false, days: 21 },
                industry: { label: 'Banks', rows: [], searched: true, days: 7, drivers: [] } } });
      await quiet.page.locator('#news-company .own-empty:not(.is-loading)').waitFor();
      assert.match(await quiet.page.locator('#news-company').innerText(), /could not be reached/);
      assert.match(await quiet.page.locator('#news-industry').innerText(), /No industry coverage in the last 7 days/);
      assert.match(await quiet.page.locator('#filings-body').innerText(), /could not be read/);
      assert.equal(await quiet.page.locator('#ov-latest').isVisible(), false);
      assert.deepEqual(quiet.errors, []);
      await quiet.context.close();
    }

    /* ── 8. A phone, every section, both themes ─────────────────────────── */
    {
      const t = await open(browser, port, { context: { viewport: { width: 390, height: 844 },
                                                       isMobile: true, hasTouch: true } });
      await t.page.locator('#ov-latest .lt-l li').first().waitFor();
      for (const pane of ['info', 'chart', 'scores', 'owners', 'funda', 'peers', 'deliv', 'news']) {
        await t.page.locator('#pane-btn-' + pane).click();
        await t.page.waitForTimeout(350);
        assert.ok(await fits(t.page), `the ${pane} section scrolls the page sideways on a phone`);
        // The tab that was tapped is on screen, not scrolled out of the bar.
        const b = await t.page.locator('#pane-btn-' + pane).boundingBox();
        assert.ok(b.x >= -1 && b.x + b.width <= 391, `the ${pane} tab is off the edge of the bar`);
      }
      await t.page.locator('#pane-btn-scores').click();
      await t.page.screenshot({ path: path.join(output, 'score-390.png'), fullPage: true });
      await t.page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
      await t.page.locator('#pane-btn-info').click();
      await t.page.screenshot({ path: path.join(output, 'overview-390-dark.png'), fullPage: true });
      assert.ok(await fits(t.page));
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 9. Reduced motion: everything in place, nothing moving ─────────── */
    {
      const t = await open(browser, port, { context: { reducedMotion: 'reduce' } });
      await t.page.locator('#pane-btn-scores').click();
      assert.equal(await t.page.locator('#scoren').innerText(), String(Math.round(sc.score)));
      assert.equal(await t.page.locator('#pane-scores.enter').count(), 0);
      const first = await t.page.locator('#pillars .pl:not(.pl-head)').first().evaluate(r =>
        [Math.round(100 * r.querySelector('.fill').offsetWidth / r.querySelector('.pl-bar').offsetWidth),
         Number(r.querySelector('.pl-s').textContent)]);
      assert.ok(Math.abs(first[0] - first[1]) <= 2, 'a bar waited for an animation that never ran');
      assert.equal(await t.page.locator('.rk-bar i').evaluate(e => getComputedStyle(e).animationName), 'none');
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }

    console.log('stock page ok — screenshots in test-results/stock-page');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
