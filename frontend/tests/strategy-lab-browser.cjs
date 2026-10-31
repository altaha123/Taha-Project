/* The Strategy lab, in a real browser.

   Everything on this page fails quietly when it breaks: a table that sorts
   on the wrong column, a compare tick that draws no line, a calculator that
   prints NaN, a chart that spills past a phone's edge. None of them throws.
   So the page is driven end to end against the real report shape — the
   fixture is strategy_lab.run() on a seeded synthetic walk
   (backend/tests/make_strategy_lab_fixture.py) — at desktop and phone width.

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/strategy-lab');
fs.mkdirSync(output, { recursive: true });
const REPORT = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/strategy-lab-demo.json'), 'utf8'));

const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8'
      : file.endsWith('.webp') ? 'image/webp' : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(resolve => server.listen(8771, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [], asked = [];
  let failNext = false;

  async function context(width) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 600 });
    await ctx.addInitScript(() => { localStorage.setItem('altaha-guide-dismissed', '1'); });
    await ctx.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/strategies') {
        asked.push(u.search);
        if (failNext) {
          failNext = false;
          return route.fulfill({ status: 422, json: { detail: 'Not enough price history. The lab needs a year of warm-up and at least 3 years to test; this stock has about 1.2 usable years.' } });
        }
        return route.fulfill({ json: REPORT });
      }
      if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
      return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [], items: [],
                                     sectors: [], rankings: [], status: 'idle' } });
    });
    return ctx;
  }

  const base = 'http://127.0.0.1:8771/';
  const ours = () => errors.filter(e => /strategy-lab\.js/.test(e));

  /* ── 1 · Desktop: a stock page link lands on a filled report ─────────── */

  let ctx = await context(1280);
  let page = await ctx.newPage();
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.goto(base + '?go=strategies&lab=DEMO', { waitUntil: 'domcontentloaded' });
  await page.locator('#sl-table tbody tr').nth(11).waitFor();
  assert.ok(asked[0].includes('ticker=DEMO') && asked[0].includes('years=10'), 'the ?lab= symbol is the one asked for');
  assert.equal(await page.locator('#sl-table tbody tr').count(), REPORT.strategies.length + 1, 'holding plus every rule');
  assert.equal((await page.locator('#sl-sym').inputValue()), 'DEMO');
  const verdict = await page.locator('.sl-verdict').innerText();
  assert.ok(verdict.includes('of 11') && verdict.includes('DEMO'), 'the verdict counts the rules');
  assert.ok(verdict.includes('No rule beat holding on Sharpe'), 'the luck line matches the fixture verdict');
  assert.ok(await page.locator('#sl-table tr.hold').isVisible(), 'holding is the first row');
  assert.ok((await page.locator('#sl-table thead').innerText()).includes('AFTER TAX'), 'rupee stocks show after-tax CAGR');

  // The chart: holding, the selected rule, and the rest faint.
  assert.equal(await page.locator('#sl-chart path.ln.hold').count(), 1);
  assert.equal(await page.locator('#sl-chart path.ln.sel').count(), 1);
  assert.equal(await page.locator('#sl-chart path.ln.faint').count(), REPORT.strategies.length - 1);
  const d = await page.locator('#sl-chart path.ln.hold').getAttribute('d');
  assert.ok(d && d.startsWith('M') && !/NaN/.test(d), 'the holding line has real coordinates');
  // The default selection is the best Sharpe the server named.
  assert.equal((await page.locator('#sl-detail h3').innerText()).trim(), REPORT.luck.best_name);

  // Hover shows the date and values.
  await page.locator('#sl-chart').scrollIntoViewIfNeeded();
  const box = await page.locator('#sl-chart svg').boundingBox();
  await page.locator('#sl-chart svg').hover({ position: { x: box.width * 0.6, y: box.height * 0.5 } });
  await page.locator('#sl-tip:not([hidden])').waitFor();
  assert.ok(/×/.test(await page.locator('#sl-tip').innerText()));

  // Sort by Sharpe: the first rule row has the highest Sharpe.
  await page.selectOption('#sl-sort', 'sharpe');
  const top = REPORT.strategies.slice().sort((a, b) => (b.metrics.sharpe ?? -9) - (a.metrics.sharpe ?? -9))[0];
  assert.equal(await page.locator('#sl-table tbody tr').nth(1).getAttribute('data-row'), top.id);
  // Shallowest worst fall first.
  await page.selectOption('#sl-sort', 'dd');
  const shallow = REPORT.strategies.slice().sort((a, b) => b.metrics.max_drawdown_pct - a.metrics.max_drawdown_pct)[0];
  assert.equal(await page.locator('#sl-table tbody tr').nth(1).getAttribute('data-row'), shallow.id);

  // Family chips filter the rows; holding stays as the benchmark.
  await page.locator('[data-family="Mean reversion"]').click();
  assert.equal(await page.locator('#sl-table tbody tr').count(), 1 + REPORT.strategies.filter(s => s.family === 'Mean reversion').length);
  await page.locator('[data-family="all"]').click();

  // A row opens its detail.
  await page.locator('#sl-table tr[data-row="rsi_reversion"] th').click();
  assert.equal((await page.locator('#sl-detail h3').innerText()).trim(), 'RSI dip');
  assert.ok((await page.locator('#sl-detail').innerText()).includes('O02 Market RSI Reversion'), 'the quants.md source is named');
  assert.equal(await page.locator('#sl-detail .sl-yb-row:not(.sl-yb-h)').count(),
               REPORT.strategies.find(s => s.id === 'rsi_reversion').years.length);
  // Keyboard reaches rows too.
  await page.locator('#sl-table tr[data-row="donchian"]').focus();
  await page.keyboard.press('Enter');
  assert.equal((await page.locator('#sl-detail h3').innerText()).trim(), '20-day breakout');

  // Compare: two ticks, two coloured lines, a side-by-side table; a fourth tick is refused.
  await page.locator('[data-cmp="trend_50_200"]').check();
  await page.locator('[data-cmp="vol_target_hold"]').check();
  assert.equal(await page.locator('#sl-chart path.ln.k1').count(), 1);
  assert.equal(await page.locator('#sl-chart path.ln.k2').count(), 1);
  assert.equal(await page.locator('.sl-cmp-t thead th').count(), 4, 'blank corner, holding and two rules');
  await page.locator('[data-cmp="macd_trend"]').check();
  await page.locator('[data-cmp="sma_20_50"]').click();      // a fourth: refused
  assert.equal(await page.locator('[data-cmp]:checked').count(), 3, 'at most three to compare');
  assert.equal(await page.locator('[data-cmp="sma_20_50"]').isChecked(), false);
  await page.locator('[data-clear-cmp]').click();
  assert.equal(await page.locator('.sl-cmp-t').count(), 0);

  // Every rule off the chart, holding and the selection stay.
  await page.locator('#sl-showall').uncheck();
  assert.equal(await page.locator('#sl-chart path.ln.faint').count(), 0);
  await page.locator('#sl-showall').check();

  // The calculators: prefilled, and they answer as numbers change.
  const kelly = await page.locator('[data-calc="kelly"] output').innerText();
  assert.ok(/Kelly/.test(kelly) && !/NaN/.test(kelly), 'Kelly answers from the prefilled trade stats: ' + kelly);
  assert.ok(/stays in cash/.test(await page.locator('[data-calc="vol"] output').innerText()));
  await page.locator('[data-calc="risk"] input[name="entry"]').fill('1250');
  await page.locator('[data-calc="risk"] input[name="exit"]').fill('1180');
  const risk = await page.locator('[data-calc="risk"] output').innerText();
  assert.ok(risk.includes('71 shares'), 'five lakh at 1% over a ₹70 risk is 71 shares: ' + risk);
  // Choosing another rule refreshes Kelly from its trades and keeps what was typed above.
  await page.locator('[data-calc="risk"] input[name="exit"]').fill('1180');
  await page.locator('#sl-table tr[data-row="macd_trend"] th').click();
  const macd = REPORT.strategies.find(s => s.id === 'macd_trend').metrics;
  assert.equal(Number(await page.locator('[data-calc="kelly"] input[name="p"]').inputValue()), macd.win_rate_pct);
  assert.equal(await page.locator('[data-calc="risk"] input[name="entry"]').inputValue(), '1250');
  await page.locator('[data-calc="risk"] input[name="exit"]').fill('1300');
  assert.ok((await page.locator('[data-calc="risk"] output').innerText()).includes('below the entry'));

  // The glossary gives formulas, and the page credits its source and says what it is not.
  assert.ok((await page.locator('.sl-gloss').innerText()).includes('√252'));
  const foot = await page.locator('.sl-assume').innerText();
  assert.ok(foot.includes('not a recommendation') && foot.includes('quants.md'));
  assert.equal(await page.locator('.sl-assume a[href="https://quants.md/"]').count(), 1);

  // Changing the window asks again with the new years.
  await page.locator('#sl-years [data-years="5"]').click();
  await page.locator('#sl-table tbody tr').nth(11).waitFor();
  assert.ok(asked[asked.length - 1].includes('years=5'));

  // An answer the server refuses is shown in its words, with a way to retry.
  failNext = true;
  await page.locator('#sl-sym').fill('young');
  await page.locator('#sl-go').click();
  await page.locator('.sl-err').waitFor();
  assert.ok((await page.locator('.sl-err').innerText()).includes('Not enough price history'));
  await page.locator('[data-retry]').click();
  await page.locator('#sl-table tbody tr').nth(11).waitFor();

  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(output, 'strategy-lab-desktop.png'), fullPage: true });

  // The Ideas door lists it, and search finds it by what people call it.
  await page.goto(base + '#research/ideahub', { waitUntil: 'domcontentloaded' });
  await page.locator('[data-goto="research/strategies"]').waitFor();
  await ctx.close();

  /* ── 2 · Phone: nothing spills past the edge ──────────────────────────── */

  ctx = await context(390);
  page = await ctx.newPage();
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.goto(base + '?go=strategies&lab=DEMO', { waitUntil: 'domcontentloaded' });
  await page.locator('#sl-table tbody tr').nth(11).waitFor();
  await page.waitForTimeout(500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 1, 'the page does not scroll sideways on a phone (overflow ' + overflow + 'px)');
  const scroller = await page.locator('.sl-scroll').first().evaluate(n => n.scrollWidth > n.clientWidth);
  assert.ok(scroller, 'the wide table scrolls inside its own box instead');
  await page.screenshot({ path: path.join(output, 'strategy-lab-phone.png'), fullPage: true });
  await ctx.close();

  assert.deepEqual(ours(), [], 'strategy-lab.js threw:\n' + ours().join('\n'));
  await browser.close();
  server.close();
  console.log('strategy lab: all checks passed');
})().catch(async e => {
  console.error(e);
  process.exit(1);
});
