/* The portfolio action plan in a real Chromium, against the synthetic report
   the portfolio workflow builds (backend/tests/portfolio_fixture.py — now with
   a small scanned cohort, so switches and industries appear). No live calls.

   What this is actually guarding:
     · THE REVIEW ANSWERS "WHAT DO I DO?" FIRST: after Analyse, the action plan
       is what the reader sees — a call on every holding, most urgent first,
       each with its trade and its reason. The story and the full report are
       closed until asked for.
     · THE FILTERS WORK: tapping "Trim" or "Needs a move" shows only those.
     · SWITCHES AND INDUSTRIES LINK TO REAL STOCK PAGES.
     · THE DISCLAIMER IS ON THE PAGE: not SEBI-registered, rule-based.
     · MOTION OFF MEANS EVERYTHING IS VISIBLE AT ONCE.
     · phone and desktop, light and dark, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/portfolio-plan');
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
  const context = await browser.newContext(Object.assign({ viewport: { width: 1280, height: 900 } }, opts || {}));
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
  return { context, page, errors };
}

(async () => {
  assert.ok(plan && plan.available, 'the fixture carries an action plan');
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  // ── Desktop: the plan first, everything else on request ─────────────────
  {
    const { context, page, errors } = await open(browser, port);
    assert.equal(await page.locator('#pf_story').isVisible(), false, 'story closed');
    assert.equal(await page.locator('#pf_report').isVisible(), false, 'full report closed');
    assert.equal(await page.locator('#pf_storybtn').isVisible(), true);
    assert.equal(await page.locator('#pf_full').isVisible(), true);

    assert.equal(await page.locator('.pp-hero h2').innerText(), plan.headline);
    const cards = await page.locator('.pp-card').evaluateAll(cs => cs.map(c => ({
      act: c.dataset.act, sym: c.querySelector('h3 a').textContent,
      todo: c.querySelector('.pp-todo').textContent, why: c.querySelector('.pp-why').textContent })));
    assert.equal(cards.length, plan.actions.length, 'a card for every holding');
    const order = ['EXIT', 'TRIM', 'AVERAGE', 'ADD', 'HOLD'];
    for (let i = 1; i < cards.length; i++) {
      assert.ok(order.indexOf(cards[i].act) >= order.indexOf(cards[i - 1].act), 'most urgent first');
    }
    for (const c of cards) {
      assert.ok(c.todo.trim() && c.why.trim(), `${c.sym} has a trade and a reason`);
    }
    const hdfc = cards.find(c => c.sym === 'HDFCBANK');
    assert.equal(hdfc.act, 'TRIM');
    assert.match(hdfc.todo, /Sell 5 of 10 shares · ₹3,00,000/);

    // A switch links to the stronger company's page.
    const swap = page.locator('.pp-card[data-act="TRIM"]', { hasText: 'TATAMOTORS' }).locator('.pp-switch');
    assert.match(await swap.innerText(), /Consider switching to M&M/);
    assert.match(await swap.locator('.pp-alt').first().getAttribute('href'), /stock\.html\?ticker=M%26M/);

    // Where the money could go: underweight industries doing well.
    assert.equal(await page.locator('.pp-rot').count(), plan.rotation.length);
    assert.ok(plan.rotation.length >= 1);
    assert.match(await page.locator('.pp-where').innerText(), /ahead of the Nifty 50/);

    // The filters.
    await page.locator('.pp-filter [data-pp-filter="MOVE"]').click();
    const moving = await page.locator('.pp-card:not([hidden])').evaluateAll(cs => cs.map(c => c.dataset.act));
    assert.ok(moving.length && moving.every(a => a !== 'HOLD'));
    await page.locator('.pp-chip.t-trim').click();
    const trims = await page.locator('.pp-card:not([hidden])').evaluateAll(cs => cs.map(c => c.dataset.act));
    assert.deepEqual([...new Set(trims)], ['TRIM']);
    assert.equal(trims.length, plan.counts.TRIM);
    await page.locator('.pp-filter [data-pp-filter="ALL"]').click();
    assert.equal(await page.locator('.pp-card:not([hidden])').count(), plan.actions.length);

    // Why this call opens the evidence.
    await page.locator('.pp-card').first().locator('.pp-more summary').click();
    assert.ok(await page.locator('.pp-card').first().locator('.pp-more li').count() >= 2);

    // The disclaimer says what these calls are.
    await page.locator('.pp-how summary').click();
    assert.match(await page.locator('.pp-how').innerText(), /not registered with SEBI/);

    // The story and the full report open on request.
    await page.locator('#pf_storybtn').click();
    await page.locator('#pf_story .ps').waitFor();
    await page.locator('#pf_full').click();
    await page.locator('#pi-money-map').waitFor();

    const tracked = await page.evaluate(() => window.__tracked);
    const viewed = tracked.filter(t => t[0] === 'portfolio_plan_viewed');
    assert.equal(viewed.length, 1);
    assert.ok(!JSON.stringify(tracked).match(/HDFCBANK|₹|TRIM/), 'no symbol, call or rupee in analytics');

    await page.locator('#pf_plan').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'plan-1280.png') });
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
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
      await page.locator('#pf_plan').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `plan-390-${theme}.png`) });
    }
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  // ── Motion off: every card complete at once ─────────────────────────────
  {
    const { context, page, errors } = await open(browser, port, { reducedMotion: 'reduce' });
    const bad = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('#pf_plan *').forEach(el => {
        const cs = getComputedStyle(el);
        if (cs.animationName !== 'none') out.push(el.className + ': animates');
        // Near-invisible, not dimmed: the "0 Exit" chip is 0.35 on purpose.
        if (el.textContent.trim() && Number(cs.opacity) < 0.3) out.push(el.className + ': opacity ' + cs.opacity);
      });
      return out;
    });
    assert.deepEqual(bad, [], 'motion off');
    assert.equal(await page.locator('.pp-ring-mid b').innerText(), String(Math.round(report.weighted_score)),
      'the score is shown at its value, not counting');
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('portfolio plan browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
