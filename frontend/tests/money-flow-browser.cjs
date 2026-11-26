/* Money flow in a real Chromium, against fixtures the real backend produced
   from an invented market (backend/tests/make_money_flow_fixture.py). No live
   calls.

   What this is actually guarding:
     · NOTHING IS FETCHED UNTIL THE TAB IS SHOWN, and then the page is ONE
       request. Changing the range, the shading or the themes never goes back
       to the server; only opening a sector does, once.
     · THE ROTATION CHART PLAYS. The trails start at the first week, travel to
       the last and stop there; the slider moves them by hand; and with motion
       off the chart is simply drawn at the last week.
     · A SECTOR OPENS INTO ITS STOCKS from a card, from the heatmap and from
       the chart, as a dialog that takes focus, holds Tab, closes on Escape
       and gives focus back.
     · THE PAGE IS DARK IN BOTH THEMES, and nothing on it is invisible under
       any motion setting (the trap motion-off-browser.cjs describes).
     · phone through desktop, no horizontal page scroll, no figure cut off.
     · An empty server and an unreachable one each say so. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/money-flow');
fs.mkdirSync(output, { recursive: true });
const SCALE = Number(process.env.SHOT_SCALE || 1);
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures', name), 'utf8'));
const flow = read('money-flow.json'), sectors = read('money-flow-sectors.json'), brief = read('money-flow-brief.json');

async function openTab(page, id) {
  await page.waitForLoadState('load');
  await page.waitForTimeout(400);
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.evaluate(t => window.AltahaNav.go('discover', t, true), id);
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

/* A page on the site with the API answered from the fixtures. `mode` decides
   what /moneyflow says: the fixture, an empty server, or no answer at all. */
async function open(browser, opts) {
  const context = await browser.newContext({
    viewport: opts.viewport || { width: 1280, height: 1000 },
    reducedMotion: opts.motion === 'on' ? 'no-preference' : 'reduce', deviceScaleFactor: SCALE });
  await context.addInitScript(() => { try { localStorage.setItem('altaha-guide-dismissed', '1'); } catch (e) {} });
  if (opts.init) await context.addInitScript(opts.init);
  const page = await context.newPage(), errors = [], asked = [];
  const state = { mode: opts.mode || 'ok' };
  page.on('pageerror', e => errors.push(String(e.stack || e.message || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    // An outside script answered with this test's JSON would be a syntax error
    // on the page that nothing here caused.
    if (['font', 'image', 'script'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname.startsWith('/moneyflow')) asked.push(u.pathname);
    if (u.pathname === '/moneyflow') {
      if (state.mode === 'down') return route.abort();
      return route.fulfill({ json: state.mode === 'empty'
        ? { available: false, message: 'Money Flow has no data yet. The evening job fills it; the first run needs the backfill.' }
        : flow });
    }
    if (u.pathname === '/moneyflow/brief') return route.fulfill({ json: brief });
    if (u.pathname.startsWith('/moneyflow/sector/')) {
      const hit = sectors[u.pathname.split('/').pop()];
      return hit ? route.fulfill({ json: hit }) : route.fulfill({ status: 404, json: { detail: 'No such sector.' } });
    }
    if (u.pathname === '/market') return route.fulfill({ json: { indices: [], status: 'closed' } });
    return route.fulfill({ json: { available: false, rows: [], items: [], sectors: [] } });
  });
  await page.goto('http://127.0.0.1:' + server.address().port + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);
  await page.waitForLoadState('load');
  await page.waitForTimeout(600);
  return { context, page, errors, asked, state };
}

/* Every element with text of its own that cannot be seen: opacity multiplied
   down the tree, the way the compositor does it. */
const invisible = page => page.evaluate(() => {
  const out = [];
  document.querySelectorAll('#mf-root *').forEach(el => {
    if (el.closest('svg') && el.tagName !== 'svg') return;
    if (el.closest('details:not([open])') && el.tagName !== 'SUMMARY' && !el.matches('details')) return;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own || !el.offsetParent) return;
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity);
    if (o < 0.5) out.push(el.className + ': ' + el.textContent.trim().slice(0, 40));
  });
  return out;
});

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  /* ════════════════════════════════════════════════════════════════════════
     1 · The page
     ════════════════════════════════════════════════════════════════════════ */
  const { context, page, errors, asked } = await open(browser, {});
  const whole = () => asked.filter(p => p === '/moneyflow');

  // ── Lazy. The Market page's card asks for the brief; the tab asks for none
  assert.equal(whole().length, 0, 'the page must not load before the tab is shown');
  assert.deepEqual(asked, ['/moneyflow/brief'], 'the Market page should ask for the brief and nothing else');
  const tool = page.locator('#drt-moneyflow');
  assert.match(await tool.innerText(), /Money flow/);
  assert.match(await tool.innerText(), new RegExp(String(brief.inflow_sectors)));
  assert.match(await tool.innerText(), /Ranked first on money flow: IT,/);

  await openTab(page, 'flows');
  await page.locator('#mf-root .mf-card').first().waitFor({ state: 'visible' });
  assert.equal(whole().length, 1);

  // ── It says what it is, and when ───────────────────────────────────────────
  assert.match(await page.locator('.mf-top h2').innerText(), /Money\s+flow/);
  assert.match(await page.locator('.mf-asof').innerText(), /Session of Fri 20 Nov 2026 · FPI data to 1–15 Nov 2026/);
  assert.equal(await page.locator('.mf-tile').count(), 4);
  assert.match(await page.locator('.mf-tile').nth(3).innerText(), /Turned to buying\s+5\s+Cement, FMCG, Financials, Healthcare, Telecom/);

  // ── The market: bars and, under them, the running total ───────────────────
  const hero = page.locator('.mf-hero');
  assert.equal(await hero.locator('.mf-bar').count() > 100, true, 'sixty sessions of two bars each');
  assert.equal(await hero.locator('.mf-line').count(), 2);
  assert.deepEqual(await hero.locator('.mf-legend > span').allInnerTexts(), ['FII', 'DII']);
  // One axis per panel: the bars' zero line sits above the running total's.
  const zeros = await hero.locator('.mf-zero').evaluateAll(els => els.map(e => e.getBoundingClientRect().top));
  assert.equal(zeros.length, 2);
  assert.ok(zeros[0] < zeros[1]);
  // The crosshair finds the session; the tooltip names both and both totals.
  const svg = hero.locator('.mf-hero-svg'), box = await svg.boundingBox();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.3);
  const tip = page.locator('.mf-tip');
  await tip.waitFor({ state: 'visible' });
  assert.match(await tip.innerText(), /\w{3} \d+ \w{3} 2026[\s\S]*FII[\s\S]*DII[\s\S]*FII running[\s\S]*DII running/);
  assert.equal(await hero.locator('.mf-cross').evaluate(e => e.style.display), '');
  // ... and the keyboard does the same.
  // ... and the keyboard carries on from where the pointer was.
  const at = Number(await svg.getAttribute('data-i'));
  assert.ok(at > 30 && at < 40, 'the crosshair is not under the pointer: ' + at);
  await svg.focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal(await svg.getAttribute('data-i'), String(at - 1));
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  assert.equal(await svg.getAttribute('data-i'), String(at + 1));
  const want = flow.market.days[at + 1].date.split('-');
  assert.ok((await tip.innerText()).includes(Number(want[2]) + ' ' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][want[1] - 1]),
    'the tooltip is not for the session the keyboard moved to');
  await page.mouse.move(5, 5);
  // Twenty sessions is the same data, narrower: no request.
  await hero.locator('[data-range="20"]').click();
  assert.equal(await hero.locator('.mf-table tbody tr').count(), 20);
  assert.equal(whole().length, 1, 'changing the range went back to the server');
  await hero.locator('[data-range="60"]').click();
  // Every figure is reachable without hovering.
  await hero.locator('.mf-table summary').click();
  assert.equal(await hero.locator('.mf-table tbody tr').count(), 60);
  assert.match(await hero.locator('.mf-table tbody tr').first().innerText(), /Fri 20 Nov 2026/);
  await hero.locator('.mf-table summary').click();

  // ── The heatmap ────────────────────────────────────────────────────────────
  const heat = page.locator('.mf-heat');
  await heat.scrollIntoViewIfNeeded();
  assert.equal(await heat.locator('tbody tr').count(), flow.heatmap.rows.length + 1);
  assert.equal(await heat.locator('thead th').count(), 12 + 3);
  const firstRow = heat.locator('tbody tr').first();
  assert.equal(await firstRow.locator('th').innerText(), 'IT');
  assert.equal(await firstRow.locator('td.mf-cell').count(), 12);
  // IT was bought more every fortnight: its last cell is the strongest green.
  assert.match(await firstRow.locator('td.mf-cell').last().getAttribute('class'), /in4/);
  const metals = heat.locator('tbody tr', { has: page.locator('th', { hasText: /^Metals$/ }) });
  assert.match(await metals.locator('td.mf-cell').last().getAttribute('class'), /out4/);
  assert.match(await metals.locator('.mf-trend').innerText(), /Selling more/);
  // Inflow and outflow are different colours, and neither is the page's.
  const fill = sel => page.locator(sel).first().evaluate(e => getComputedStyle(e).backgroundColor);
  const [cin, cout, cz] = [await fill('td.mf-cell.in4'), await fill('td.mf-cell.out4'), await fill('.mf-ramp .z')];
  assert.equal(new Set([cin, cout, cz]).size, 3);
  // A cell says its figure in the cell, and the rest on hover.
  const cell = firstRow.locator('td.mf-cell').last();
  await cell.hover();
  assert.match(await tip.innerText(), /₹[\d,]+ cr\s+IT\s+1–15 Nov 2026\s+\+\d+\.\d\d% of FPI holdings in the sector/);
  // Shading by rupees repaints, without a request.
  const before = await heat.locator('td.mf-cell').evaluateAll(els => els.map(e => e.className).join('|'));
  await heat.locator('[data-heat="cr"]').click();
  const after = await heat.locator('td.mf-cell').evaluateAll(els => els.map(e => e.className).join('|'));
  assert.notEqual(before, after);
  assert.equal(await heat.locator('[data-heat="cr"]').getAttribute('aria-pressed'), 'true');
  assert.equal(whole().length, 1);
  await heat.locator('[data-heat="pct"]').click();
  await page.screenshot({ path: path.join(output, 'heatmap.png') });

  // ── Rotation ───────────────────────────────────────────────────────────────
  const rot = page.locator('.mf-rot');
  await rot.scrollIntoViewIfNeeded();
  const nSectors = flow.rrg.series.filter(s => s.kind === 'sector').length;
  assert.equal(await rot.locator('.mf-rr').count(), nSectors);
  assert.deepEqual(await rot.locator('.mf-qname').allTextContents().then(t => t.map(x => x.toLowerCase()).sort()),
    ['improving', 'lagging', 'leading', 'weakening']);
  // A Leading sector's dot is right of and above the crossing; a Lagging one's neither.
  const centre = await rot.locator('.mf-zero').evaluateAll(els => {
    const r = els.map(e => e.getBoundingClientRect());
    const v = r.find(b => b.width < 3), h = r.find(b => b.height < 3);
    return { x: v.left, y: h.top };
  });
  const dotOf = key => rot.locator('.mf-rr[data-key="' + key + '"] .mf-dot').evaluate(e => {
    const b = e.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
  });
  const itDot = await dotOf('information-technology'), metalDot = await dotOf('metals-mining');
  assert.ok(itDot.x > centre.x && itDot.y < centre.y, 'IT is Leading and is not drawn there');
  assert.ok(metalDot.x < centre.x && metalDot.y > centre.y, 'Metals is Lagging and is not drawn there');
  // Bought is a solid dot, sold a hollow one: not colour alone.
  assert.match(await rot.locator('.mf-rr[data-key="information-technology"] .mf-dot').getAttribute('class'), /\bin\b/);
  assert.match(await rot.locator('.mf-rr[data-key="metals-mining"] .mf-dot').getAttribute('class'), /\bout\b/);
  // Every sector is also in a list, under its quadrant.
  assert.equal(await rot.locator('.mf-qlist li').count(), flow.rrg.series.filter(s => s.kind === 'sector' && s.quadrant).length);
  assert.match(await rot.locator('.mf-qlist').first().innerText(), /Leading[\s\S]*IT/);
  // The slider moves the trails by hand.
  const trail = () => rot.locator('.mf-rr[data-key="information-technology"] .mf-trail').getAttribute('points');
  const full = await trail();
  assert.equal(full.split(' ').length, 8, 'one point a week for eight weeks');
  await rot.locator('.mf-scrub').fill('2');
  assert.equal((await trail()).split(' ').length, 3);
  assert.match(await rot.locator('.mf-week').innerText(), /Week to \d+ \w{3}/);
  const early = await dotOf('information-technology');
  assert.ok(Math.abs(early.x - itDot.x) + Math.abs(early.y - itDot.y) > 2, 'the dot did not move with the slider');
  await rot.locator('.mf-scrub').fill('7');
  assert.equal(await trail(), full);
  // With motion reduced, Play draws the last week and stops.
  await rot.locator('.mf-playbtn').click();
  assert.equal(await trail(), full);
  // Hovering a sector names it; the rest step back.
  await rot.locator('.mf-rr[data-key="information-technology"] .mf-hit').hover({ force: true });
  assert.match(await tip.innerText(), /Information Technology\s+Leading[\s\S]*strength[\s\S]*momentum[\s\S]*FPI, latest fortnight[\s\S]*Money Flow Score/);
  assert.equal(await rot.locator('.mf-rrg-svg.has-focus .mf-rr.on').count(), 1);
  assert.equal(await rot.locator('.mf-qlist li.on').count(), 1);
  await page.mouse.move(5, 5);
  // Themes are price-only indices: off until asked for, and no request.
  assert.equal(await rot.locator('.mf-rr.k-theme').count(), 0);
  await rot.locator('[data-themes]').check();
  assert.equal(await rot.locator('.mf-rr.k-theme').count(), 6);
  assert.match(await rot.locator('.mf-rrg-legend').innerText(), /Theme: price only, no FPI data/);
  assert.equal(await rot.locator('.mf-rr.k-theme[data-sector]').count(), 0, 'a theme has no sector to open');
  assert.equal(whole().length, 1);
  await page.screenshot({ path: path.join(output, 'rotation.png') });
  await rot.locator('[data-themes]').uncheck();

  // ── The ranking ────────────────────────────────────────────────────────────
  const cards = page.locator('.mf-card');
  assert.equal(await cards.count(), flow.sectors.length);
  assert.match(await cards.first().innerText(), /^01\s+IT\s+Leading/);
  assert.match(await cards.first().innerText(), /Buying more[\s\S]*Latest[\s\S]*Last three[\s\S]*Against the Nifty 50[\s\S]*FPI flow[\s\S]*Rotation[\s\S]*Breadth/);
  assert.match(await cards.last().innerText(), /^19\s+Metals\s+Lagging/);
  assert.equal(await page.locator('.mf-trendline.flip').count(),
    flow.sectors.filter(c => c.fpi && c.fpi.flipped_to_inflow).length, 'a flip to buying is not flagged on its card');
  // A score ring is as long as its score.
  const ringOf = c => c.locator('.mf-ring .v').evaluate(e => parseFloat(getComputedStyle(e).strokeDasharray));
  assert.ok(await ringOf(cards.first()) > 5 * await ringOf(cards.last()));
  assert.match(await page.locator('.mf-unscored').innerText(), /Diversified, Forest, Utilities/);
  assert.match(await page.locator('.mf-method summary').innerText(), /How the score is made/);
  await page.locator('.mf-method summary').click();
  assert.equal(await page.locator('.mf-method tbody tr').count(), 24);
  assert.match(await page.locator('.mf-method').innerText(), /Construction\s+NIFTY INFRASTRUCTURE\s+A judgement/);
  await page.locator('.mf-method summary').click();

  /* ════════════════════════════════════════════════════════════════════════
     2 · A sector, opened
     ════════════════════════════════════════════════════════════════════════ */
  const drawer = page.locator('#mf-drawer'), panel = drawer.locator('.mf-panel');
  await cards.first().scrollIntoViewIfNeeded();
  await cards.first().focus();
  await page.keyboard.press('Enter');
  await panel.locator('.mf-stocks').waitFor({ state: 'visible' });
  assert.deepEqual(asked.filter(p => p.startsWith('/moneyflow/sector/')), ['/moneyflow/sector/information-technology']);
  assert.equal(await panel.getAttribute('role'), 'dialog');
  assert.equal(await panel.getAttribute('aria-modal'), 'true');
  assert.equal(await page.locator('#mf-dtitle').innerText(), 'Information Technology');
  assert.match(await panel.locator('.mf-dhead').innerText(), /Rank 1 of 19/i);
  assert.equal(await panel.locator('.mf-dfacts > div').count(), 4);
  assert.equal(await panel.locator('.mf-fbar').count(), 14);
  // The stocks, most accumulated first, each with its three readings.
  const rows = panel.locator('.mf-stocks tbody tr:not(.mf-why)');
  assert.equal(await rows.count(), sectors['information-technology'].stocks.length);
  assert.match(await rows.first().innerText(), /^ITE1[\s\S]*\d+%\s+usual \d+%[\s\S]*\d\.\d×[\s\S]*5 of 5 up on volume[\s\S]*Bought ₹[\d.,]+ cr\s+Long Horizon Mutual Fund/);
  assert.match(await panel.locator('.mf-stocks tr.mf-why').first().innerText(), /Delivered share \d+% over five sessions[\s\S]*Closed up on above-usual volume in 5 of the last 5 sessions[\s\S]*net bought in bulk and block deals/);
  assert.match(await rows.first().locator('a').getAttribute('href'), /^stock\.html\?ticker=ITE1&pane=deliv$/);
  const scores = await panel.locator('.mf-acc b').allInnerTexts().then(t => t.map(Number));
  assert.deepEqual(scores, scores.slice().sort((a, b) => b - a));
  await page.screenshot({ path: path.join(output, 'sector.png') });
  // Focus is inside, Tab stays inside, Escape closes and gives focus back.
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('#mf-drawer')), true);
  for (let i = 0; i < 40; i++) await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('#mf-drawer')), true, 'Tab left the open dialog');
  await page.keyboard.press('Escape');
  await drawer.waitFor({ state: 'hidden' });
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains('mf-card')), true, 'focus was not given back');
  assert.equal(await page.evaluate(() => document.documentElement.classList.contains('mf-locked')), false);
  // From the heatmap, and from the chart; the scrim closes it.
  await heat.locator('.mf-rowbtn', { hasText: /^FMCG$/ }).click();
  await panel.locator('.mf-stocks').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#mf-dtitle').innerText(), 'Fast Moving Consumer Goods');
  assert.match(await panel.locator('.mf-dchips').innerText(), /Turned to buying/);
  await drawer.locator('.mf-scrim').click({ position: { x: 10, y: 300 } });
  await drawer.waitFor({ state: 'hidden' });
  await rot.locator('.mf-rr[data-key="metals-mining"]').focus();
  await page.keyboard.press('Enter');
  await panel.locator('.mf-stocks').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#mf-dtitle').innerText(), 'Metals & Mining');
  await panel.locator('.mf-close').click();
  await drawer.waitFor({ state: 'hidden' });
  // A basket says it is one.
  await heat.locator('.mf-rowbtn', { hasText: /^Textiles$/ }).click();
  await panel.locator('.mf-stocks').waitFor({ state: 'visible' });
  assert.match(await panel.innerText(), /Measured on a basket of 8 Textiles stocks\. NSE publishes no textiles index\./);
  await page.keyboard.press('Escape');
  await drawer.waitFor({ state: 'hidden' });
  assert.equal(whole().length, 1, 'opening sectors re-read the whole page');

  /* ════════════════════════════════════════════════════════════════════════
     3 · Dark in both themes, at every width
     ════════════════════════════════════════════════════════════════════════ */
  for (const width of [390, 820, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(400);                     // the charts redraw at the new size
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(120);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `${width} ${theme}: horizontal page scroll`);
      // The page wears the site's theme (THEME.md): its cards are the surface
      // token, light by day and dark by night, and the text on a card is the
      // primary ink, which is the opposite. (It used to be a dark stage of
      // its own in both themes.)
      const lumOf = c => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
      const card = await page.locator('.mf-card').first().evaluate(e => getComputedStyle(e).backgroundColor.match(/[\d.]+/g).map(Number));
      const ink = await page.locator('.mf-card .mf-name').first().evaluate(e => getComputedStyle(e).color.match(/[\d.]+/g).map(Number));
      if (theme === 'dark') {
        assert.ok(lumOf(card) < 60, `${width} dark: a card is not dark (${lumOf(card)})`);
        assert.ok(lumOf(ink) > 200, `${width} dark: card text is not light on a dark card`);
      } else {
        assert.ok(lumOf(card) > 230, `${width} light: a card is not light (${lumOf(card)})`);
        assert.ok(lumOf(ink) < 60, `${width} light: card text is not dark on a light card`);
      }
      // No figure is cut off by its own box.
      const clipped = await page.locator('.mf-tile .v, .mf-flowfig, .mf-card-top, .mf-rs').evaluateAll(
        els => els.filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).map(e => e.className + ':' + e.textContent.slice(0, 30)));
      assert.deepEqual(clipped, [], `${width} ${theme}: a figure is cut off`);
      const out = await page.locator('.mf-card').evaluateAll(els => els.filter(e => {
        const c = e.getBoundingClientRect();
        return [...e.querySelectorAll('b, small, span')].some(x => { const r = x.getBoundingClientRect(); return r.width && r.right > c.right + 1; });
      }).length);
      assert.equal(out, 0, `${width} ${theme}: something spills out of a sector card`);
      assert.deepEqual(await invisible(page), [], `${width} ${theme}: text that cannot be seen`);
      await page.screenshot({ path: path.join(output, `${width}-${theme}.png`) });
    }
    // The charts are drawn at the size they are seen, not scaled down.
    const vb = await page.locator('.mf-hero-svg').getAttribute('viewBox');
    assert.equal(vb.split(' ')[2], width < 620 ? '380' : '1000', `${width}: the market chart was not redrawn`);
    const tick = await page.locator('.mf-hero-svg .mf-tick').first().evaluate(e => e.getBoundingClientRect().height);
    assert.ok(tick >= 9, `${width}: an axis label is ${tick.toFixed(1)}px tall`);
    const lab = await page.locator('.mf-rrg-svg .mf-lab').first().evaluate(e => e.getBoundingClientRect().height);
    assert.ok(lab >= 9, `${width}: a sector label on the rotation chart is ${lab.toFixed(1)}px tall`);
  }
  // On a phone the heatmap scrolls inside its own box, with the sector names held in place.
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.waitForTimeout(400);
  const sc = page.locator('.mf-heat .mf-scroll');
  await sc.scrollIntoViewIfNeeded();
  assert.equal(await sc.evaluate(e => e.scrollWidth > e.clientWidth + 20), true);
  await sc.evaluate(e => e.scrollTo(400, 0));
  const nameLeft = await page.locator('.mf-heat tbody th').first().evaluate(e => e.getBoundingClientRect().left);
  const boxLeft = await sc.evaluate(e => e.getBoundingClientRect().left);
  assert.ok(Math.abs(nameLeft - boxLeft) < 8, 'the sector names scrolled away with the cells');
  // On a phone a sector's stocks are blocks, each figure under its label.
  await page.locator('.mf-card').first().scrollIntoViewIfNeeded();
  await page.locator('.mf-card').first().click();
  await panel.locator('.mf-stocks').waitFor({ state: 'visible' });
  assert.equal(await panel.evaluate(e => e.scrollWidth > e.clientWidth + 1), false, 'the open sector scrolls sideways on a phone');
  assert.equal(await panel.locator('.mf-stocks').evaluate(e => e.scrollWidth > e.parentElement.clientWidth + 1), false);
  assert.match(await panel.locator('.mf-stocks td').first().evaluate(e => getComputedStyle(e, '::before').content), /Delivered today/);
  assert.equal(await panel.locator('.mf-fn-svg').getAttribute('viewBox'), '0 0 360 170');
  await page.screenshot({ path: path.join(output, '390-sector.png') });
  await page.keyboard.press('Escape');
  await drawer.waitFor({ state: 'hidden' });
  assert.deepEqual(errors, [], 'page errors:\n' + errors.join('\n'));
  await context.close();

  /* ════════════════════════════════════════════════════════════════════════
     4 · Motion
     ════════════════════════════════════════════════════════════════════════ */
  // On: the rotation chart starts at the first week, travels, and stops at the last.
  {
    const s = await open(browser, { motion: 'on' });
    await openTab(s.page, 'flows');
    await s.page.locator('#mf-root .mf-card').first().waitFor({ state: 'attached' });
    assert.equal(await s.page.locator('#mf-root.mf-anim').count(), 1);
    const points = () => s.page.locator('.mf-rr[data-key="information-technology"] .mf-trail').getAttribute('points');
    const final = await points();
    await s.page.locator('.mf-rot').scrollIntoViewIfNeeded();
    await s.page.waitForFunction(() => document.querySelector('.mf-rrg-svg.is-moving'), null, { timeout: 5000 });
    const mid = await points();
    assert.ok(mid.split(' ').length < 8 || mid !== final, 'the trail did not start short');
    assert.equal(await s.page.locator('.mf-playbtn').innerText(), 'Pause');
    await s.page.waitForFunction(() => !document.querySelector('.mf-rrg-svg.is-moving'), null, { timeout: 12000 });
    assert.equal(await points(), final, 'the trail did not end where the data ends');
    assert.equal(await s.page.locator('.mf-playbtn').innerText(), 'Replay');
    // Replay starts again; pausing holds it where it is.
    await s.page.locator('.mf-playbtn').click();
    await s.page.waitForFunction(() => document.querySelector('.mf-rrg-svg.is-moving'));
    await s.page.locator('.mf-playbtn').click();
    const held = await points();
    await s.page.waitForTimeout(400);
    assert.equal(await points(), held, 'Pause did not hold the chart');
    // Once everything has come into view, nothing is left hidden.
    for (const sel of ['.mf-tiles', '.mf-hero', '.mf-heat', '.mf-rot', '.mf-ranking']) {
      await s.page.locator(sel).scrollIntoViewIfNeeded();
      await s.page.waitForTimeout(250);
    }
    await s.page.waitForTimeout(2600);
    assert.deepEqual(await invisible(s.page), [], 'with motion on, text is left invisible after its reveal');
    assert.deepEqual(s.errors, []);
    await s.context.close();
  }
  // Off by the site's own switch, remembered from a previous visit; and with
  // every animation paused by a stylesheet nobody here wrote.
  for (const [name, init] of [
    ['off', () => { document.documentElement.setAttribute('data-motion', 'off'); }],
    ['paused', () => { const st = document.createElement('style'); st.textContent = '*{animation-play-state:paused!important}';
      document.addEventListener('DOMContentLoaded', () => document.head.appendChild(st)); }],
  ]) {
    const s = await open(browser, { motion: name === 'paused' ? 'on' : 'reduce', init });
    await openTab(s.page, 'flows');
    await s.page.locator('#mf-root .mf-card').first().waitFor({ state: 'attached' });
    for (const sel of ['.mf-tiles', '.mf-hero', '.mf-heat', '.mf-rot', '.mf-ranking']) {
      await s.page.locator(sel).scrollIntoViewIfNeeded();
      await s.page.waitForTimeout(200);
    }
    if (name === 'off') {
      assert.equal(await s.page.locator('#mf-root.mf-anim').count(), 0, 'motion is off and the page armed its reveals');
      assert.deepEqual(await invisible(s.page), [], 'with motion off, text cannot be seen');
      const full = await s.page.locator('.mf-rr[data-key="information-technology"] .mf-trail').getAttribute('points');
      assert.equal(full.split(' ').length, 8, 'with motion off the rotation chart is not at its last week');
    } else {
      // Paused mid-reveal is the trap: a reveal held at its first frame is
      // invisible for good. Only whole sections fade, and those are counted.
      const hidden = await s.page.locator('.mf-sec, .mf-tiles').evaluateAll(els =>
        els.filter(e => getComputedStyle(e).opacity === '0' && e.classList.contains('is-in')).length);
      assert.equal(hidden, 0, 'a section that has come into view is held invisible by a paused animation');
    }
    await s.context.close();
  }

  /* ════════════════════════════════════════════════════════════════════════
     5 · An empty server, and none
     ════════════════════════════════════════════════════════════════════════ */
  {
    const s = await open(browser, { mode: 'empty' });
    await openTab(s.page, 'flows');
    // The loading state is drawn in the same box first, so wait for the
    // answer by its words, not for the box.
    await s.page.locator('#mf-root .mf-state', { hasText: 'Nothing to show yet' }).waitFor({ state: 'visible' });
    assert.match(await s.page.locator('#mf-root .mf-state').innerText(), /Nothing to show yet\s+Money Flow has no data yet\. The evening job fills it/);
    assert.match(await s.page.locator('.mf-top h2').innerText(), /Money\s+flow/);
    assert.equal(await s.page.locator('.mf-sec').count(), 0);
    await s.context.close();
  }
  {
    const s = await open(browser, { mode: 'down' });
    await openTab(s.page, 'flows');
    await s.page.locator('#mf-root [data-retry]').waitFor({ state: 'visible' });
    assert.match(await s.page.locator('#mf-root .mf-state').innerText(), /The engine is unreachable/);
    s.state.mode = 'ok';
    await s.page.locator('#mf-root [data-retry]').click();
    await s.page.locator('#mf-root .mf-card').first().waitFor({ state: 'visible' });
    assert.equal(await s.page.locator('.mf-card').count(), flow.sectors.length);
    // A sector the server does not know says so and can be closed.
    await s.page.evaluate(() => { document.querySelector('.mf-card').dataset.sector = 'atlantis'; });
    await s.page.locator('.mf-card').first().click();
    // "Reading the sector" is drawn in the same box until the server answers.
    await s.page.locator('#mf-drawer .mf-state', { hasText: 'could not be read' }).waitFor({ state: 'visible' });
    assert.match(await s.page.locator('#mf-drawer .mf-state').innerText(), /That sector could not be read\s+No such sector\./);
    await s.page.locator('#mf-drawer .mf-btn[data-close]').click();
    await s.page.locator('#mf-drawer').waitFor({ state: 'hidden' });
    assert.deepEqual(s.errors, []);
    await s.context.close();
  }

  await browser.close();
  server.close();
  console.log('money-flow-browser: ok');
})().catch(e => { console.error(e); process.exit(1); });
