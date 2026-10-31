/* The three doors, in a real browser.

   Navigation is the one part of this site that every other part depends on,
   and the failure modes are all silent: a hash that used to open a view now
   opens nothing, a destination is owned by two doors at once, a phone bar
   and a desktop bar name different things. None of that throws, so none of it
   shows up in a syntax check.

   What this asserts:
     · the site opens on Today, and the doors are exactly Today, Ideas and
       My money, with Me beside them; header and phone bar agree
     · every destination has exactly one owner, and every one is reachable
     · every address the site has ever published still resolves to a visible
       view — #screener, #ideas, #planner, #portfolio, #funds, #screener/funds
     · the door pages and the older hubs render rather than sitting empty
     · the door bar switches tools and pins them; search finds a tool by the
       word people use for it
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

const DOORS = ['Today', 'Ideas', 'My money'];

(async () => {
  await new Promise(resolve => server.listen(8768, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, hasTouch: true });
  await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
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
    // The weekday planets (#134) read the last five sessions from here; the
    // shape is market_week.build_week's.
    if (u.pathname === '/market/week') {
      return route.fulfill({ json: { flows_source: 'NSE provisional cash-market figures, ₹ crore',
        sessions: [{ date: '2026-09-23', weekday: 'Wed', label: 'Wed 23 Sep', mood: 'up',
          indices: { 'NIFTY 50': { close: 25150, change_pct: 0.84 } },
          flows: { fii: { net: -3693.93 }, dii: { net: 2838.17 } },
          synopsis: 'Nifty rose 0.8% to 25,150.' }] } });
    }
    return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [],
                                   items: [], sectors: [], rankings: [], status: 'idle' } });
  });

  await page.goto('http://127.0.0.1:8768/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);

  /* ── 0 · The site opens on Today, not on a banner ──────────────────────── */

  await page.locator('#view-today .dr-title').waitFor();
  assert.equal((await page.locator('#view-today .dr-title').innerText()).trim(), 'Today');
  assert.equal(await page.locator('header.wrap').isVisible(), false, 'the old landing banner is gone');
  /* ?go= opens the tool it names, every time. index.html clicks the named tab
     on a timer of its own and the router opens the landing view as it
     starts; when the router came second, a shared ?go=portfolio link opened
     on Today instead (it failed CI that way, not locally). The router is
     slowed down here so it always comes second. */
  await page.route('**/nav.js*', async r => { await new Promise(res => setTimeout(res, 600)); await r.continue(); });
  for (const [go, view] of [['portfolio', 'view-portfolio'], ['discover', 'view-discover'],
                            ['allocate', 'view-allocate'], ['research', 'view-ideahub'], ['ideas', 'view-ideas']]) {
    await page.goto('http://127.0.0.1:8768/?go=' + go, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => !!window.AltahaNav);
    await page.waitForTimeout(400);
    assert.equal(await page.locator('header.wrap').isVisible(), false, `?go=${go} opens on the product, not a banner`);
    assert.ok(await page.locator('#' + view).isVisible(), `?go=${go} did not open #${view}`);
  }
  await page.unroute('**/nav.js*');
  await page.goto('http://127.0.0.1:8768/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);

  /* ── 1 · Three doors and Me, named and in order ──────────────────────── */

  const sections = await page.evaluate(() => window.AltahaNav.sections.map(s => ({
    id: s.id, label: s.label, question: s.question,
    tabs: s.tabs.map(t => t.id), extras: (s.extras || []).map(t => t.id)
  })));
  assert.deepEqual(sections.map(s => s.label), DOORS.concat(['Me']), 'the doors are not Today, Ideas, My money and Me');
  assert.deepEqual(await page.evaluate(() => window.AltahaNav.doors), ['discover', 'research', 'portfolio']);
  sections.slice(0, 3).forEach(s => assert.ok(s.question && s.question.endsWith('?'),
    `${s.label} does not state the question it answers`));

  /* Desktop bar and phone bar have to agree, or "where am I" has two answers. */
  assert.deepEqual(await page.locator('.sh-door').allInnerTexts().then(x => x.map(t => t.trim())),
                   DOORS, 'the header does not show the three doors');
  assert.deepEqual(await page.locator('.ux-bottom button').evaluateAll(ns => ns.map(n => n.getAttribute('aria-label'))),
                   ['Today', 'Ideas', 'Search', 'My money', 'Me'], 'the phone bar does not match the doors');
  // Today is lit, in the header and in the door bar.
  await page.waitForFunction(() => document.querySelector('.sh-door.on'));
  assert.equal((await page.locator('.sh-door.on').innerText()).trim(), 'Today');
  assert.equal((await page.locator('#sh-doorbar .sh-pill.on').innerText()).trim(), 'Overview');

  /* ── 2 · One owner per destination, and no orphans ───────────────────── */

  const owners = {};
  sections.forEach(s => s.tabs.concat(s.extras).forEach(t => {
    assert.equal(owners[t], undefined, `${t} is owned by both ${owners[t]} and ${s.id}`);
    owners[t] = s.id;
  }));
  ['ideas', 'screener', 'charts', 'results', 'investors', 'funds', 'filings', 'concalls',
   'social', 'vocab', 'tracker', 'portfolio', 'planner', 'live', 'deals', 'special',
   'wow', 'options', 'discover', 'allocate', 'score', 'factors', 'query', 'lenses',
   'convergence', 'today', 'ideahub', 'money', 'strategies'].forEach(t => {
    assert.ok(owners[t], `${t} lost its home in the restructure`);
  });

  /* Each door opens on its own page, and the tools land where their
     question is answered. */
  assert.equal(sections[0].tabs[0], 'today');
  assert.equal(sections[1].tabs[0], 'ideahub');
  assert.equal(sections[2].tabs[0], 'money');
  ['live', 'deals', 'wow', 'special', 'results', 'filings', 'options', 'screener'].forEach(t =>
    assert.equal(owners[t], 'discover', `${t} belongs behind Today`));
  ['ideas', 'query', 'lenses', 'convergence', 'investors', 'funds', 'charts', 'tracker', 'factors', 'strategies', 'concalls'].forEach(t =>
    assert.equal(owners[t], 'research', `${t} belongs behind Ideas`));
  ['portfolio', 'allocate', 'planner'].forEach(t => assert.equal(owners[t], 'portfolio', `${t} belongs behind My money`));
  ['score', 'vocab', 'social'].forEach(t => assert.equal(owners[t], 'me', `${t} belongs in Me`));

  await page.evaluate(() => window.AltahaNav.go('research', 'ideas', true));
  assert.ok(await page.locator('#view-ideas').isVisible());
  // Since #134 the planets are the week (Mon–Fri), each opening that
  // session's synopsis; scan progress is carried by the meter alone. These
  // lines still counted planets lit as scan checkpoints, so the step went red
  // on main the moment the planets changed meaning.
  assert.equal(await page.locator('.su-planet').count(), 5, 'one planet per weekday');
  assert.deepEqual(await page.locator('.su-planet b').allInnerTexts(), ['MON','TUE','WED','THU','FRI']);
  await page.evaluate(() => window.AltahaUniverse.update({status:'running',done:50,total:100,scored:42}));
  assert.equal(await page.locator('.su-progress').evaluate(el => el.value), 50);
  assert.match(await page.locator('.su-detail').innerText(), /50 \/ 100/);
  await page.evaluate(() => window.AltahaUniverse.update({status:'done'}));
  assert.equal(await page.locator('.su-progress').evaluate(el => el.value), 100);
  await page.evaluate(() => window.AltahaUniverse.update({status:'done',stopped_early:true}));
  assert.match(await page.locator('.su-status').innerText(), /stopped before completion/);
  await page.evaluate(() => window.AltahaUniverse.update({status:'error'}));
  await page.evaluate(() => window.AltahaUniverse.update({status:'cached'}));
  assert.match(await page.locator('.su-status').innerText(), /saved/);
  // Motion allowed first, so the assertion below is a comparison rather than a
  // sentence that would pass just as happily against a stylesheet that never
  // animated anything.
  // The one planet animation left is the opened day's pulse, so that is what
  // is asserted under both motion settings.
  const wed = page.locator('.su-planet').nth(2);
  await wed.click();
  assert.equal(await wed.getAttribute('aria-expanded'), 'true');
  assert.equal(
    await wed.locator('i').evaluate(el => getComputedStyle(el).animationName), 'su-pulse',
    'the planet must animate when motion is allowed, or the next assertion proves nothing');

  await page.emulateMedia({reducedMotion:'reduce'});
  // .su-sweep was removed in 9dd183c and the checkpoint pulse in #134; the
  // intent is unchanged: under prefers-reduced-motion nothing in the scan
  // animates, which universe-scan.css enforces with `.scan-universe *`.
  assert.equal(await wed.locator('i').evaluate(el => getComputedStyle(el).animationName), 'none');
  await wed.click();
  assert.equal(await wed.getAttribute('aria-expanded'), 'false');
  await page.emulateMedia({reducedMotion:'no-preference'});

  // Exercise the real start/poll controller with mocked backend checkpoints.
  let phase = 'running';
  const discovered = {symbol:'TEST',name:'Test company',score:72.4,sector:'Industrials',finding:'Setup: Momentum'};
  await page.route('**/scan/start*', route => route.fulfill({json:{started:true,status:'running',run_id:123,total:100,done:0,scored:0,discoveries:[],planet_batches:[]}}));
  await page.route('**/scan/status*', route => route.fulfill({json:{status:phase,run_id:123,total:100,done:phase==='done'?100:50,scored:15,elapsed_seconds:65,discoveries:[discovered],planet_batches:[{number:1,count:15,rows:[discovered]}]}}));
  await page.evaluate(() => startScan(true,false));
  assert.equal(await page.locator('#scan-results').isVisible(),false);
  await page.evaluate(() => pollScan());
  await page.locator('.su-card').first().waitFor();
  assert.match(await page.locator('.su-card').first().innerText(), /TEST/);
  assert.equal(await page.locator('header.wrap').isVisible(),false,'scan view retains the empty header');
  for (const width of [390,768,1280]) {
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'live scan overflows at '+width);
    await page.screenshot({path:path.join(output, width+'-live-universe.png'),fullPage:true});
  }
  await page.locator('.su-card summary').first().click();
  assert.match(await page.locator('.su-card').first().innerText(), /Setup: Momentum/);
  await page.locator('.su-motion').click();
  assert.equal(await page.locator('#scan-universe').evaluate(el=>el.classList.contains('su-paused')),true);
  await page.locator('.su-planet').nth(2).click();
  const day = page.locator('.su-day');
  await day.waitFor();
  assert.match(await day.getAttribute('aria-label'), /Wednesday/);
  assert.match(await day.innerText(), /Nifty rose 0\.8% to 25,150\./);
  assert.match(await day.innerText(), /FII \/ FPI[\s\S]*−₹3,694 cr/);
  // A day with no session on record says so rather than inventing one.
  await page.locator('.su-planet').nth(0).click();
  await page.waitForFunction(() => /Monday/.test(document.querySelector('.su-day')?.getAttribute('aria-label') || ''));
  assert.match(await page.locator('.su-day').innerText(), /No session on record/);
  await page.locator('.su-day-x').click();
  assert.equal(await page.locator('.su-planet[aria-expanded=true]').count(), 0);
  await page.evaluate(() => window.AltahaNav.go('discover','screener',true));
  await page.locator('#su-dock').waitFor();
  phase='done'; await page.evaluate(() => pollScan());
  assert.match(await page.locator('#su-dock').innerText(), /Scan complete/);
  await page.locator('#su-dock').click();
  assert.equal(await page.locator('#scan-results').isVisible(),true);
  assert.equal(await page.locator('#su-dock').isVisible(),false);
  await page.evaluate(() => window.AltahaUniverse.update({status:'running',run_id:124,total:100,done:0,discoveries:[],planet_batches:[]}));
  assert.equal(await page.locator('.su-card').count(),0,'old run leaked into fresh scan');
  await page.evaluate(() => window.AltahaUniverse.update({status:'error'}));
  await page.unroute('**/scan/status*');
  await page.unroute('**/scan/start*');

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
  // #portfolio was always the holdings review; sign-in, Pro and Advisors
  // link it. The door's own page has an address of its own.
  await shows('#portfolio', 'view-portfolio');
  await shows('#portfolio/money', 'view-money');
  await shows('#discover/today', 'view-today');
  await shows('#today', 'view-today');
  await shows('#research', 'view-ideahub');
  await shows('#discover/deals', 'view-deals');
  await shows('#research/query', 'view-query');
  await shows('#research/charts', 'view-charts');
  await shows('#me/vocab', 'view-vocab');

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

  /* ── 4 · The door pages and the older hubs actually render ────────────── */

  await page.evaluate(() => window.AltahaNav.go('discover', null, true));
  await page.locator('#view-today .dr-hero').waitFor({ state: 'visible' });
  assert.match(await page.locator('#view-today .dr-hero').innerText(), /NIFTY 50/);
  assert.match(await page.locator('#drt-level').innerText(), /25,150\.75/);
  assert.equal(await page.locator('#view-today .dr-tool').count(), 8, 'Today lost one of its tool cards');
  // A card is a door to its tool.
  await page.locator('#view-today .dr-tool[data-goto="discover/live"]').click();
  await page.locator('#view-live').waitFor({ state: 'visible' });
  await page.evaluate(() => window.AltahaNav.go('research', null, true));
  await page.locator('#view-ideahub .dr-universe').waitFor({ state: 'visible' });
  assert.ok(await page.locator('#view-ideahub .dr-tool').count() >= 4);
  await page.evaluate(() => window.AltahaNav.go('portfolio', null, true));
  await page.locator('#view-money .dr-pfhero').waitFor({ state: 'visible' });
  assert.match(page.url(), /#portfolio\/money$/);

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
  /* Allocate is the guided card and nothing else: the five-step sequence and
     the position calculator that used to sit under it were removed. The card
     boots off view visibility rather than off the router, so arriving here by
     navigation has to be enough to build it. */
  await page.locator('#acf-card').waitFor({ state: 'visible' });
  await page.locator('#acf_slider').waitFor({ state: 'visible' });
  assert.equal(await page.locator('.alc-step').count(), 0,
               'the old allocation sequence is still being rendered');
  /* Nothing has been answered, so nothing downstream may claim a profile. */
  assert.equal(await page.locator('.acf-groups').count(), 0,
               'asset classes appeared before the questions were answered');
  assert.match(await page.locator('#acf_exact').innerText(), /₹/,
               'Allocate rendered without an amount');

  /* ── 5 · The door bar, pins, and search ──────────────────────────────── */

  await page.locator('.sh-door', { hasText: /^Ideas$/ }).click();
  await page.locator('#sh-doorbar .sh-pill[data-tab="query"]').click();
  await page.locator('#view-query').waitFor({ state: 'visible' });
  assert.equal((await page.locator('#sh-doorbar .sh-pill.on').innerText()).trim(), 'Screener');
  assert.equal((await page.locator('.sh-door.on').innerText()).trim(), 'Ideas');
  // Pin it, and it waits on Today's desk.
  await page.locator('#sh-pin').click();
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-pins-v1'))), ['query']);
  assert.equal(await page.locator('#sh-pin').getAttribute('aria-pressed'), 'true');
  await page.locator('.sh-door', { hasText: /^Today$/ }).click();
  await page.locator('#dr-desk-pins .dr-pinchip[data-goto="research/query"]').waitFor({ state: 'visible' });

  // Search finds a tool by the word people use for it, and Enter opens it.
  await page.keyboard.press('Control+k');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'sh-q', 'Ctrl+K focuses search');
  await page.locator('#sh-q').fill('bulk');
  await page.locator('#sh-ac.open .row.tool', { hasText: 'Big trades' }).waitFor();
  await page.locator('#sh-q').press('Enter');
  await page.locator('#view-deals').waitFor({ state: 'visible' });
  // Empty, it offers what was opened last and the three doors.
  await page.locator('#sh-q').focus();
  await page.locator('#sh-ac.open .hd', { hasText: 'Recent' }).waitFor();
  assert.match(await page.locator('#sh-ac').innerText(), /Big trades/);
  await page.locator('#sh-q').press('Escape');

  // Me holds the account, Pro, Advisors, appearance and learning.
  await page.locator('#sh-me').click();
  await page.locator('#sh-memenu.open #sh-pro').waitFor({ state: 'visible' });
  assert.ok(await page.locator('#sh-memenu #sh-account').isVisible());
  assert.ok(await page.locator('#sh-memenu #sh-adv').isVisible());
  await page.locator('#sh-memenu .sh-item[data-tab="vocab"]').click();
  await page.locator('#view-vocab').waitFor({ state: 'visible' });

  /* ── 6 · Nothing overflows a phone ───────────────────────────────────── */

  for (const width of [390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const view of ['today', 'ideahub', 'money', 'ideas', 'discover', 'allocate', 'score', 'factors']) {
      await page.evaluate(v => window.AltahaNav.go(null, v, true), view);
      await page.waitForTimeout(350);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
                   false, `${view} overflows at ${width}`);
    }
    for (const view of ['today', 'ideahub', 'money', 'ideas']) {
      await page.evaluate(v => window.AltahaNav.go(null, v, true), view);
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(output, `${width}-${view}.png`), fullPage: true });
    }
  }

  assert.deepEqual(errors, [], 'the page threw while navigating');

  await browser.close();
  server.close();
  console.log('three doors ok — screenshots in test-results/nav-products');
})().catch(e => { console.error(e); process.exit(1); });
