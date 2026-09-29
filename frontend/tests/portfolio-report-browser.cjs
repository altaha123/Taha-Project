/* The portfolio report in a real Chromium, against the synthetic report the
   portfolio workflow builds (backend/tests/portfolio_fixture.py). No live calls.

   What this is actually guarding:
     · THE FULL REPORT IS THE VISUAL ONE, and it is the same thing the reader
       downloads and prints: every section, a line for every holding, the
       charts drawn from HTML and SVG (no chart library, no canvas).
     · THE NUMBERS ON THE CHARTS ARE THE REPORT'S: the plan's headline and
       trades, one pie slice per sector (six at most), one bar per score.
     · THE FILE WORKS ON ITS OWN: no script, links that work from anywhere,
       prints on A4 with the "See the numbers" tables left off paper.
     · THE DETAILED ANALYSIS IS STILL THERE, one more button, charts drawn.
     · MOTION OFF MEANS EVERYTHING IS VISIBLE AT ONCE.
     · phone and desktop, light and dark, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/portfolio-report');
fs.mkdirSync(output, { recursive: true });
const fixtures = path.resolve(process.env.PF_FIXTURES || '/tmp/portfolio-fixtures');
const report = JSON.parse(fs.readFileSync(path.join(fixtures, 'portfolio-12.json')));
const plan = report.action_plan;

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

async function open(browser, port, opts) {
  const context = await browser.newContext(Object.assign({ viewport: { width: 1280, height: 900 }, acceptDownloads: true }, opts || {}));
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.pathname === '/portfolio/start') return route.fulfill({ json: { job_id: 'fixture', total: 12 } });
    if (u.pathname === '/portfolio/status') return route.fulfill({ json: { status: 'done', done: 12, total: 12, revision: 1, report } });
    if (u.hostname !== '127.0.0.1') {
      const t = route.request().resourceType();
      if (t === 'script' || t === 'font' || t === 'stylesheet') return route.abort();
      return route.fulfill({ json: { available: false, rows: [], items: [] } });
    }
    return route.continue();
  });
  await page.goto(`http://127.0.0.1:${port}/?go=portfolio`, { waitUntil: 'domcontentloaded' });
  await page.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
  await page.locator('#pf_rows .pf_qty').first().fill('10');
  await page.evaluate(() => { window.__tracked = []; window.AltahaTrack = (n, p) => window.__tracked.push([n, p]); });
  await page.locator('#pf_go').click();
  await page.locator('#pf_plan .pp').waitFor();
  await page.locator('#pf_full').click();
  await page.locator('#pf_visual .ar-root').waitFor();
  return { context, page, errors };
}

(async () => {
  assert.ok(plan && plan.available, 'the fixture carries an action plan');
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  // ── Desktop: the report on the page ─────────────────────────────────────
  {
    const { context, page, errors } = await open(browser, port);
    const v = page.locator('#pf_visual');
    assert.equal(await page.locator('#pf_report').isVisible(), false, 'the detailed analysis waits for its button');
    assert.equal(await v.locator('.ar-cover h1').innerText(), plan.headline);
    assert.equal(await v.locator('.ar-sec').count(), 9, 'nine questions, in order');
    assert.equal(await v.locator('canvas').count(), 0, 'no chart library');

    // Stock by stock: a line for every holding, the plan's trades.
    assert.equal(await v.locator('.ar-row').count(), plan.actions.length);
    assert.match(await v.locator('.ar-row', { hasText: 'HDFCBANK' }).innerText(), /Sell 5 of 10 shares · ₹3,00,000/);
    assert.match(await v.locator('.ar-row', { hasText: 'TATAMOTORS' }).innerText(), /same industry \(Auto Manufacturers\)/);

    // Charts carry the report's own numbers.
    const sectors = report.sectors.filter(s => s.weight_pct > 0).length;
    assert.equal(await v.locator('.ar-arc').count(), Math.min(6, sectors), 'a slice per sector, six at most');
    const scored = report.holdings.filter(h => typeof h.composite === 'number').length;
    assert.equal(await v.locator('.ar-srow').count(), scored, 'a bar per scored holding');
    const w = await v.locator('.ar-srow', { hasText: 'ICICIBANK' }).locator('.ar-bar').evaluate(e => e.style.width);
    assert.equal(parseFloat(w), +report.holdings.find(h => h.symbol === 'ICICIBANK').composite.toFixed(1), 'the bar is the score');
    assert.ok(await v.locator('.ar-seg').count() >= 3, 'the plan bar and the score bands');
    assert.ok(await v.locator('.ar-drow').count() >= 10, 'now vs after the plan');
    // Every stock with a trade moves; a hold stays put.
    const moving = plan.actions.filter(a => a.move).length;
    assert.equal(await v.locator('.ar-dot.then').count(), moving, 'one "after" dot per trade');
    assert.equal(await v.locator('.ar-dot.then.t-trim').count(), plan.counts.TRIM);
    assert.ok(await v.locator('.ar-vrow').count() >= 10, 'gains and losses');
    assert.match(await v.locator('#ar-how').innerText(), /not registered with SEBI/);

    // Every chart's numbers are one tap away.
    const tables = v.locator('.ar-data');
    assert.ok(await tables.count() >= 5);
    await tables.first().locator('summary').click();
    assert.ok(await tables.first().locator('tbody tr').count() >= 1);

    // Download from inside the report: the file stands on its own.
    const dl = page.waitForEvent('download');
    await v.locator('[data-ar="download"]').click();
    const file = path.join(output, 'report.html');
    await (await dl).saveAs(file);
    const html = fs.readFileSync(file, 'utf8');
    assert.ok(!/<script/i.test(html), 'the file runs nothing');
    assert.ok(html.includes(plan.headline) && html.includes('not registered with SEBI'));
    assert.ok(html.includes('https://altahascreener.in/stock.html?ticker=HDFCBANK'));

    // The detailed analysis is still one button away, charts drawn.
    await page.locator('#pf_detail').click();
    await page.locator('#pi-money-map').waitFor();
    assert.equal(await page.locator('#pf_detail').getAttribute('aria-expanded'), 'true');

    const tracked = await page.evaluate(() => window.__tracked);
    assert.ok(tracked.some(t => t[0] === 'portfolio_report_downloaded' && t[1].format === 'html'));
    assert.ok(tracked.some(t => t[0] === 'portfolio_detail_opened'));
    assert.ok(!JSON.stringify(tracked).match(/HDFCBANK|₹|TRIM/), 'no symbol, call or rupee in analytics');

    await page.locator('#pf_visual').scrollIntoViewIfNeeded();
    await page.locator('#pf_visual .ar-cover').screenshot({ path: path.join(output, 'cover-1280.png') });
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();

    // ── The file on its own, and on paper ─────────────────────────────────
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const fp = await ctx.newPage(), ferr = [];
    fp.on('pageerror', e => ferr.push(String(e)));
    await ctx.route('**/*', r => r.request().url().startsWith('file:') ? r.continue() : r.abort());
    await fp.goto('file://' + file);
    assert.equal(await fp.locator('.ar-sec').count(), 9);
    assert.equal(await fp.locator('[data-ar]').count(), 0, 'no page buttons in the file');
    await fp.emulateMedia({ media: 'print' });
    await fp.setViewportSize({ width: 794, height: 1123 });
    assert.equal(await fp.locator('.ar-data').first().isVisible(), false, 'the tables stay off paper');
    assert.ok(await fp.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'fits A4 width');
    const pdf = await fp.pdf({ format: 'A4', printBackground: true });
    assert.ok(pdf.length > 50000, 'prints');
    fs.writeFileSync(path.join(output, 'report.pdf'), pdf);
    assert.deepEqual(ferr, []);
    await ctx.close();
  }

  // ── Phone, both themes ──────────────────────────────────────────────────
  {
    const { context, page, errors } = await open(browser, port,
      { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(200);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1, `${theme}: page scrolls sideways by ${overflow}px`);
      const clipped = await page.evaluate(() => [...document.querySelectorAll('#pf_visual .ar-dlab, #pf_visual .ar-vlab, #pf_visual .ar-slab')]
        .filter(e => e.scrollWidth > e.clientWidth + 1 && e.textContent.length < 12).map(e => e.textContent));
      assert.deepEqual(clipped, [], `${theme}: a ten-letter symbol fits its column`);
      await page.locator('#pf_visual .ar-cover').screenshot({ path: path.join(output, `cover-390-${theme}.png`) });
      await page.locator('#ar-money').screenshot({ path: path.join(output, `money-390-${theme}.png`) });
    }
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  // ── Motion off: every chart complete at once ────────────────────────────
  {
    const { context, page, errors } = await open(browser, port, { reducedMotion: 'reduce' });
    await page.evaluate(() => document.querySelectorAll('#pf_visual .ar-sec').forEach(s => s.scrollIntoView()));
    await page.waitForTimeout(200);
    const bad = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('#pf_visual *').forEach(el => {
        const cs = getComputedStyle(el);
        if (cs.animationName !== 'none') out.push(el.className.baseVal ?? el.className + ': animates');
        if (el.textContent.trim() && Number(cs.opacity) < 0.3) out.push(el.className + ': opacity ' + cs.opacity);
      });
      return out;
    });
    assert.deepEqual(bad, [], 'motion off');
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('portfolio report browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
