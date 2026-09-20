/* The four products, in a real browser.

   Navigation is the one part of this site that every other part depends on,
   and the failure modes are all silent: a hash that used to open a view now
   opens nothing, a destination is owned by two products at once, a phone bar
   and a desktop bar name different things. None of that throws, so none of it
   shows up in a syntax check.

   What this asserts:
     · the primary navigation is exactly Discover, Allocate, Portfolio, Research
     · every destination has exactly one owner, and every one is reachable
     · every address the site has ever published still resolves to a visible
       view — #screener, #ideas, #planner, #social, #funds, #screener/funds
     · the two new hubs render rather than sitting empty
     · nothing overflows a 390px screen

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/nav-products');
fs.mkdirSync(output, { recursive: true });

const indices = [
  { label: 'NIFTY 50', level: 25150.75, change_pct: 1.25 },
  { label: 'SENSEX', level: 81900, change_pct: -0.65 }
];

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

const PRODUCTS = ['Discover', 'Allocate', 'Portfolio', 'Research'];

(async () => {
  await new Promise(resolve => server.listen(8768, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, hasTouch: true });
  await context.addInitScript(() => {
    localStorage.setItem('altaha-guide-dismissed', '1');
    /* Allocate opens by asking what there is to allocate, and that prompt is
       modal — its backdrop would swallow every click this file makes once the
       run reaches Allocate. Answered here so navigation is what gets tested;
       the prompt itself has its own check in allocate-money-browser.cjs. */
    localStorage.setItem('altaha-allocate-money-v1', JSON.stringify({ amount: 500000 }));
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/market') {
      return route.fulfill({ json: { indices, status: 'closed', ist: '19 Sep 2026, 15:45 IST' } });
    }
    if (u.pathname === '/intraday/status') {
      return route.fulfill({ json: { running: false, market_open: false, watchlist_size: 40,
                                     alerts_today: [], top_rvol_now: [] } });
    }
    if (u.pathname === '/planner/questions') {
      return route.fulfill({ json: { questions: [], bands: [] } });
    }
    return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [],
                                   items: [], sectors: [], rankings: [], status: 'idle' } });
  });

  await page.goto('http://127.0.0.1:8768/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);

  /* ── 1 · Exactly four products, named and in order ───────────────────── */

  const sections = await page.evaluate(() => window.AltahaNav.sections.map(s => ({
    id: s.id, label: s.label, question: s.question,
    tabs: s.tabs.map(t => t.id), extras: (s.extras || []).map(t => t.id)
  })));
  assert.deepEqual(sections.map(s => s.label), PRODUCTS, 'primary navigation is not the four products');
  sections.forEach(s => assert.ok(s.question && s.question.endsWith('?'),
    `${s.label} does not state the question it answers`));

  /* Desktop bar and phone bar have to agree, or "where am I" has two answers. */
  assert.deepEqual(await page.locator('.sh-top').allInnerTexts().then(x => x.map(t => t.trim())),
                   PRODUCTS, 'the header bar does not match the products');
  assert.deepEqual(await page.locator('.ux-bottom button').allInnerTexts(),
                   PRODUCTS.concat(['Watchlist']), 'the phone bar does not match the products');

  /* ── 2 · One owner per destination, and no orphans ───────────────────── */

  const owners = {};
  sections.forEach(s => s.tabs.concat(s.extras).forEach(t => {
    assert.equal(owners[t], undefined, `${t} is owned by both ${owners[t]} and ${s.id}`);
    owners[t] = s.id;
  }));
  ['ideas', 'screener', 'charts', 'results', 'investors', 'funds', 'filings', 'concalls',
   'social', 'vocab', 'tracker', 'portfolio', 'planner', 'live', 'deals', 'special',
   'wow', 'options', 'discover', 'allocate', 'score', 'factors'].forEach(t => {
    assert.ok(owners[t], `${t} lost its home in the restructure`);
  });

  /* The eight destinations Research is meant to carry in its visible row. */
  const research = sections.filter(s => s.id === 'research')[0];
  assert.deepEqual(research.tabs,
    ['screener', 'score', 'factors', 'results', 'investors', 'charts', 'filings'],
    'the Research row is not the eight named destinations');

  assert.deepEqual(sections.find(s => s.id === 'discover').tabs.slice(0, 3), ['ideas', 'live', 'tracker']);
  assert.equal(owners.ideas, 'discover');
  assert.equal(owners.live, 'discover');
  assert.equal(owners.tracker, 'discover');

  await page.evaluate(() => window.AltahaNav.go('discover', null, true));
  assert.ok(await page.locator('#view-ideas').isVisible());
  await page.evaluate(() => window.AltahaUniverse.update({status:'running',done:50,total:100,scored:42}));
  assert.equal(await page.locator('.su-planet.is-scanned').count(), 3);
  assert.equal(await page.locator('.su-planet.is-scanning').count(), 1);
  assert.match(await page.locator('.su-detail').innerText(), /50 \/ 100/);
  await page.evaluate(() => window.AltahaUniverse.update({status:'done'}));
  assert.equal(await page.locator('.su-planet.is-scanned').count(), 6);
  await page.evaluate(() => window.AltahaUniverse.update({status:'done',stopped_early:true}));
  assert.match(await page.locator('.su-status').innerText(), /paused/);
  await page.evaluate(() => window.AltahaUniverse.update({status:'error'}));
  assert.equal(await page.locator('.su-planet.is-scanning').count(), 0);
  await page.evaluate(() => window.AltahaUniverse.update({status:'cached'}));
  assert.match(await page.locator('.su-status').innerText(), /saved/);
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.evaluate(() => window.AltahaUniverse.update({status:'running',done:50,total:100}));
  assert.equal(await page.locator('.su-sweep').evaluate(el => getComputedStyle(el).animationName), 'none');
  await page.emulateMedia({reducedMotion:'no-preference'});

  /* ── 3 · Every address the site has published still opens something ──── */

  async function shows(hash, viewId) {
    await page.evaluate(h => { location.hash = h; }, hash);
    await page.waitForTimeout(500);
    assert.ok(await page.locator('#' + viewId).isVisible(),
              `${hash} no longer opens #${viewId}`);
  }
  await shows('#screener', 'view-screener');
  await shows('#ideas', 'view-ideas');
  await shows('#research/ideas', 'view-ideas');
  await shows('#portfolio/tracker', 'view-tracker');
  await shows('#funds', 'view-funds');
  await shows('#screener/funds', 'view-funds');
  await shows('#screener/filings', 'view-filings');
  await shows('#planner', 'view-planner');
  await shows('#portfolio', 'view-portfolio');

  /* The old pair form, where the section and the tab no longer agree with
     each other: the destination is what has to be honoured. */
  await page.evaluate(() => window.AltahaNav.go('screener', 'concalls', true));
  await page.waitForTimeout(400);
  assert.ok(await page.locator('#view-concalls').isVisible(),
            "go('screener','concalls') stopped resolving");

  /* A lone id that names a destination rather than a product is that
     destination — portfolio.js and the old bottom bar both rely on it. */
  await page.evaluate(() => window.AltahaNav.go('planner', null, true));
  await page.waitForTimeout(400);
  assert.ok(await page.locator('#view-planner').isVisible(), "go('planner') stopped opening the planner");

  /* ── 4 · The two new hubs actually render ────────────────────────────── */

  await page.evaluate(() => window.AltahaNav.go('discover', 'discover', true));
  await page.locator('#dsc-market .dsc-ix').first().waitFor();
  assert.match(await page.locator('#dsc-market').innerText(), /NIFTY 50/);
  await page.locator('#dsc-activity .dsc-card').first().waitFor();
  assert.equal(await page.locator('#dsc-activity .dsc-card').count(), 4,
               'Discover lost one of its activity cards');
  /* A hub whose feeds are all empty must still say something rather than
     present four blank boxes. */
  assert.ok((await page.locator('#dsc-activity').innerText()).trim().length > 80);

  await page.evaluate(() => window.AltahaNav.go('allocate', null, true));
  await page.locator('#alc-steps .alc-step').first().waitFor();
  assert.equal(await page.locator('.alc-step').count(), 5, 'the allocation sequence is not five steps');
  /* Nothing has been entered, so nothing may claim to be done. */
  assert.equal(await page.locator('.alc-chip.is-done').count(), 0,
               'a step reported itself complete on no evidence');
  await page.locator('#alc_cap').fill('500000');
  await page.locator('#alc_out .alc-big').first().waitFor();
  assert.match(await page.locator('#alc_out').innerText(), /₹/);

  /* ── 5 · The mega menu carries each product's question ───────────────── */

  /* Hover opens the panel, which is what a mouse does before it clicks — a
     click here would land on an already-open panel and toggle it shut. */
  for (const label of PRODUCTS) {
    await page.locator('.sh-top', { hasText: new RegExp('^' + label + '$') }).hover();
    await page.locator('.sh-mega.open .sh-megaq').waitFor();
    assert.match(await page.locator('.sh-mega.open .sh-megaq').innerText(), /\?$/,
                 `${label} opens a panel that does not state its question`);
    assert.ok(await page.locator('.sh-mega.open .sh-item').count() >= 1,
              `${label} opens an empty panel`);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
  }

  /* ── 6 · Nothing overflows a phone ───────────────────────────────────── */

  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ['ideas', 'discover', 'allocate', 'score', 'factors']) {
      await page.evaluate(v => window.AltahaNav.go(null, v, true), view);
      await page.waitForTimeout(350);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
                   false, `${view} overflows at ${width}`);
    }
    for (const view of ['ideas', 'discover', 'allocate']) {
      await page.evaluate(v => window.AltahaNav.go(null, v, true), view);
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(output, `${width}-${view}.png`), fullPage: true });
    }
  }

  assert.deepEqual(errors, [], 'the page threw while navigating');

  await browser.close();
  server.close();
  console.log('four products ok — screenshots in test-results/nav-products');
})().catch(e => { console.error(e); process.exit(1); });
