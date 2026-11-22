/* The three doors, in a real browser.

   Navigation is the one part of this site that every other part depends on,
   and the failure modes are all silent: a hash that used to open a view now
   opens nothing, a destination is owned by two doors at once, a phone bar
   and a desktop bar name different things. None of that throws, so none of it
   shows up in a syntax check.

   What this asserts:
     · the site opens on Market, and the doors are exactly Market, Ideas and
       Portfolio, with Me beside them; header and phone bar agree
     · each door's menu opens on a hover, on its arrow and from the keyboard,
       lists every tool behind the door in its groups, and gets out of the way
     · every destination has exactly one owner, and every one is reachable
     · every address the site has ever published still resolves to a visible
       view — #screener, #ideas, #planner, #portfolio, #funds, #screener/funds
     · the door pages and the older hubs render rather than sitting empty
     · the line under the header says where the reader is and pins the tool;
       below 1040px it is a button that opens the same menu as a sheet from
       the bottom of the screen; search finds a tool by the word people use
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

const DOORS = ['Market', 'Ideas', 'Portfolio'];

(async () => {
  await new Promise(resolve => server.listen(8768, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, hasTouch: true });
  // Member tools (gate.js) open for a signed-in reader.
  await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-test'));
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

  /* A door's menu, opened the way a mouse opens it: come to rest on the door.
     The pointer is taken off the header first, so that it arrives rather than
     happening to be there already. */
  async function openMenu(sec) {
    await page.mouse.move(640, 760);
    await page.locator(`.sh-doorwrap[data-sec="${sec}"]`).hover();
    await page.locator(`#sh-megawrap.open #sh-mega-${sec}`).waitFor({ state: 'visible' });
  }
  async function viaMenu(sec, tab) {
    await openMenu(sec);
    await page.locator(`#sh-mega-${sec} .sh-item[data-tab="${tab}"]`).click();
  }
  const menuTabs = sec => page.locator(`#sh-mega-${sec} .sh-item`).evaluateAll(ns => ns.map(n => n.dataset.tab || n.getAttribute('href')));

  /* ── 0 · The site opens on Market, not on a banner ──────────────────────── */

  await page.locator('#view-today .dr-title').waitFor();
  assert.equal((await page.locator('#view-today .dr-title').innerText()).trim(), 'Market');
  assert.equal(await page.locator('header.wrap').isVisible(), false, 'the old landing banner is gone');
  /* ?go= opens the tool it names, every time. index.html clicks the named tab
     on a timer of its own and the router opens the landing view as it
     starts; when the router came second, a shared ?go=portfolio link opened
     on Market instead (it failed CI that way, not locally). The router is
     slowed down here so it always comes second. */
  await page.route('**/nav.js*', async r => { await new Promise(res => setTimeout(res, 600)); await r.continue(); });
  for (const [go, view] of [['portfolio', 'view-portfolio'], ['discover', 'view-today'],
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
  assert.deepEqual(sections.map(s => s.label), DOORS.concat(['Me']), 'the doors are not Market, Ideas, Portfolio and Me');
  assert.deepEqual(await page.evaluate(() => window.AltahaNav.doors), ['discover', 'research', 'portfolio']);
  sections.slice(0, 3).forEach(s => assert.ok(s.question && s.question.endsWith('?'),
    `${s.label} does not state the question it answers`));

  /* Desktop bar and phone bar have to agree, or "where am I" has two answers. */
  assert.deepEqual(await page.locator('.sh-door').allInnerTexts().then(x => x.map(t => t.trim())),
                   DOORS, 'the header does not show the three doors');
  assert.deepEqual(await page.locator('.ux-bottom button').evaluateAll(ns => ns.map(n => n.getAttribute('aria-label'))),
                   ['Market', 'Ideas', 'Search', 'Portfolio', 'Me'], 'the phone bar does not match the doors');
  // Market is lit in the header. On a door's own page there is no bar under
  // the header: it would only repeat the page's heading.
  await page.waitForFunction(() => document.querySelector('.sh-door.on'));
  assert.equal((await page.locator('.sh-door.on').innerText()).trim(), 'Market');
  assert.equal(await page.locator('#sh-doorbar').isVisible(), false, 'the bar under the header is shown on a door’s own page');

  /* ── 1b · Built for the first visit ──────────────────────────────────────
     People who were sent the site found it too complex to navigate. Market
     now says what the site does and offers three tasks; the door bar shows
     a short row with the rest under More. */

  const start = page.locator('#view-today #dr-start');
  await start.waitFor({ state: 'visible' });
  assert.match(await start.innerText(), /0 to 100/, 'Start here does not say what the site does');
  assert.deepEqual((await start.locator('.dr-task b').allInnerTexts()).map(t => t.trim()),
                   ['Check a stock', 'Get stock picks', 'Check my portfolio']);
  assert.ok(await start.locator('a[href="stock.html?ticker=RELIANCE"]').count(), 'no example stock to try');

  /* ── 1c · The door menus ──────────────────────────────────────────────────
     Resting on a door opens one panel with every tool behind it, in named
     groups, each with its hint. It replaced a row of pills with the rest
     under "More", which readers found confusing. */

  assert.equal(await page.locator('#sh-megawrap.open').count(), 0, 'a menu opened by itself');
  assert.equal(await page.locator('#sh-mega-discover').isVisible(), false);
  await openMenu('discover');
  assert.deepEqual(await page.locator('#sh-mega-discover .sh-mega-col h4').allInnerTexts().then(t => t.map(x => x.trim().toLowerCase())),
                   ['live market', 'money flow', 'company news'], 'Market’s menu groups changed');
  assert.deepEqual(await menuTabs('discover'), ['live', 'options', 'deals', 'special', 'wow', 'results', 'filings'],
                   'Market’s menu does not list every tool behind the door');
  assert.match(await page.locator('#sh-mega-discover .sh-item[data-tab="options"]').innerText(), /open interest/i,
               'a tool in the menu lost its hint');
  // The card on the left: the door's question, the market as it stands, and
  // nothing to open, because this is already the door's page.
  const lead = page.locator('#sh-mega-discover .sh-mega-lead');
  assert.match(await lead.innerText(), /What is happening today\?/);
  await page.locator('#sh-mega-live .sh-mega-ix').first().waitFor({ state: 'visible' });
  assert.match(await page.locator('#sh-mega-live').innerText(), /NIFTY 50\s+25,150\.75\s+\+1\.25%/);
  assert.equal(await lead.getAttribute('aria-current'), 'page');
  assert.match(await lead.innerText(), /You are here/);
  assert.equal(await page.locator('.sh-doorcv[data-sec="discover"]').getAttribute('aria-expanded'), 'true');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the menu overflows the page');
  await page.screenshot({ path: path.join(output, '1280-menu-today.png') });

  // Along the doors the same panel shows the next door's tools; one at a time.
  await page.locator('.sh-doorwrap[data-sec="research"]').hover();
  await page.locator('#sh-mega-research').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#sh-mega-discover').isVisible(), false, 'two menus are open at once');
  assert.deepEqual(await menuTabs('research'),
                   ['query', 'lenses', 'forum.html', 'charts', 'strategies', 'concalls', 'investors', 'funds', 'calls']);
  assert.match(await page.locator('#sh-mega-research .sh-mega-lead').innerText(), /Open Ideas/);
  await page.screenshot({ path: path.join(output, '1280-menu-ideas.png') });
  await page.locator('.sh-doorwrap[data-sec="portfolio"]').hover();
  await page.locator('#sh-mega-portfolio').waitFor({ state: 'visible' });
  assert.deepEqual(await menuTabs('portfolio'), ['portfolio', 'watchlists', 'allocate', 'planner', 'advisors.html', 'wealth.html']);
  // From the door down into its panel is a diagonal; the menu waits for it.
  await page.locator('#sh-mega-portfolio .sh-item[data-tab="planner"]').hover();
  await page.waitForTimeout(500);
  assert.ok(await page.locator('#sh-mega-portfolio').isVisible(), 'the menu closed on the way from the door to a tool');
  // Leaving both closes it, after a moment rather than at once.
  await page.mouse.move(640, 760);
  await page.locator('#sh-megawrap.open').waitFor({ state: 'detached' });
  await page.locator('#sh-mega-portfolio').waitFor({ state: 'hidden' });     // it fades out, so not at once

  // The way a hand does it: a few pixels at a time, in a straight line from
  // the door to a tool in the last column. hover() above jumps there, which
  // is how two faults got past it. The menu used to shut once the pointer
  // was on it, because Chrome reported a leave as it came off the strip
  // under the bar. And the line from Market or Ideas to the last column
  // crosses the doors beside it, each of which swapped the pane on the way.
  const middle = async sel => { const b = await page.locator(sel).boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };
  const glide = async (from, to, pxPerSec) => {
    const steps = Math.max(2, Math.round(Math.hypot(to[0] - from[0], to[1] - from[1]) / pxPerSec * 1000 / 16));
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(from[0] + (to[0] - from[0]) * i / steps, from[1] + (to[1] - from[1]) * i / steps);
      await page.waitForTimeout(16);
    }
  };
  for (const sec of ['discover', 'research', 'portfolio']) {
    for (const speed of [300, 900]) {
      await page.mouse.move(640, 760);
      await page.locator('#sh-megawrap.open').waitFor({ state: 'detached' });
      const from = await middle(`.sh-doorwrap[data-sec="${sec}"] .sh-door`);
      await page.mouse.move(from[0], from[1], { steps: 3 });
      await page.locator(`#sh-mega-${sec}`).waitFor({ state: 'visible' });
      const tool = `#sh-mega-${sec} .sh-mega-col:last-child .sh-item:last-child`;
      await glide(from, await middle(tool), speed);
      await page.waitForTimeout(600);       // longer than the menu waits before closing
      assert.ok(await page.locator(`#sh-mega-${sec}`).isVisible(),
                `${sec}: the menu closed or changed on the way to its last column at ${speed}px/s`);
      assert.ok(await page.locator(tool).evaluate(n => n.matches(':hover')), `${sec}: the pointer is not on the tool it went to`);
    }
  }
  // Sliding along the bar still moves from door to door, and resting on one opens it.
  await glide(await middle('#sh-mega-portfolio .sh-mega-col:last-child .sh-item:last-child'),
              await middle('.sh-doorwrap[data-sec="portfolio"] .sh-door'), 900);
  await glide(await middle('.sh-doorwrap[data-sec="portfolio"] .sh-door'), await middle('.sh-doorwrap[data-sec="discover"] .sh-door'), 600);
  await page.locator('#sh-mega-discover').waitFor({ state: 'visible' });
  await page.mouse.move(640, 760);
  await page.locator('#sh-megawrap.open').waitFor({ state: 'detached' });
  // Escape closes it too.
  await openMenu('discover');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sh-megawrap.open').count(), 0, 'Escape did not close the menu');

  // Without a mouse: the arrow beside the door opens the menu and puts the
  // cursor in it, the arrow keys walk it, Escape hands the cursor back.
  await page.mouse.move(640, 760);
  await page.locator('.sh-doorcv[data-sec="research"]').focus();
  await page.keyboard.press('Enter');
  await page.locator('#sh-mega-research').waitFor({ state: 'visible' });
  assert.ok(await page.evaluate(() => document.activeElement.classList.contains('sh-mega-lead')), 'the keyboard did not land in the menu');
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.tab), 'query');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sh-megawrap.open').count(), 0);
  assert.ok(await page.evaluate(() => document.activeElement.matches('.sh-doorcv[data-sec="research"]')),
            'Escape did not hand the cursor back to the door');
  // A finger has no hover: a tap on the arrow opens the menu, another closes it.
  await page.locator('.sh-doorcv[data-sec="portfolio"]').tap();
  await page.locator('#sh-mega-portfolio').waitFor({ state: 'visible' });
  await page.locator('.sh-doorcv[data-sec="portfolio"]').tap();
  assert.equal(await page.locator('#sh-megawrap.open').count(), 0, 'a second tap did not close the menu');

  // A tool opened from the menu: the menu goes, the line under the header
  // says where the reader is, and the menu marks the tool as the one open.
  await viaMenu('research', 'concalls');
  await page.locator('#view-concalls').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#sh-megawrap.open').count(), 0, 'the menu stayed open over the tool it opened');
  assert.equal((await page.locator('#sh-doorbar .sh-crumb-door').innerText()).trim(), 'Ideas');
  assert.equal((await page.locator('#sh-doorbar .sh-crumb-here').innerText()).trim(), 'Concalls');
  assert.match(await page.locator('#sh-doorbar .sh-crumb-hint').innerText(), /Earnings calls/);
  assert.deepEqual(await page.locator('#sh-mega [aria-current="page"]').evaluateAll(ns => ns.map(n => n.dataset.tab)), ['concalls']);
  // The door in that line, and the door's name in the header, both open the door's page.
  await page.locator('#sh-doorbar .sh-crumb-door').click();
  await page.locator('#view-ideahub').waitFor({ state: 'visible' });
  await viaMenu('discover', 'deals');
  await page.locator('#view-deals').waitFor({ state: 'visible' });
  await page.locator('.sh-door[data-sec="research"]').click();
  await page.locator('#view-ideahub').waitFor({ state: 'visible' });
  await page.waitForTimeout(500);
  assert.equal(await page.locator('#sh-megawrap.open').count(), 0, 'a click on a door’s name left its menu over the page');

  /* ── 1d · The same menu on a narrow screen ────────────────────────────────
     Below 1040px the header has no doors to hang a menu from. The bar under
     it is one button that says where the reader is and opens a sheet from
     the bottom of the screen: the three doors across the top, and under the
     one chosen its own page and its tools, in the same groups. It replaced
     a row of pills that scrolled sideways with the rest under "More". */
  await page.setViewportSize({ width: 900, height: 900 });
  await page.evaluate(() => window.AltahaNav.go('discover', 'today', true));
  const where = page.locator('#sh-where');
  await where.waitFor({ state: 'visible' });
  assert.equal(await page.locator('.sh-doorwrap').first().isVisible(), false);
  assert.equal((await where.locator('.sh-where-door').innerText()).trim(), 'Market');
  assert.equal((await where.locator('.sh-where-here').innerText()).trim(), 'Overview');
  assert.equal(await page.locator('#sh-doorbar .sh-crumb').count(), 0, 'the wide screen’s line is on a narrow one');
  const sheet = page.locator('#sh-sheet');
  const sheetTabs = sec => page.locator(`#sh-sheet-${sec} .sh-item`).evaluateAll(ns => ns.map(n => n.dataset.tab || n.getAttribute('href')));
  assert.equal(await sheet.isVisible(), false, 'the sheet opened by itself');
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  assert.equal(await where.getAttribute('aria-expanded'), 'true');
  assert.deepEqual(await sheet.locator('.sh-sheet-tab').allInnerTexts().then(t => t.map(x => x.trim())), DOORS,
                   'the sheet does not carry the three doors');
  assert.deepEqual(await sheet.locator('.sh-sheet-tab[aria-selected="true"]').allInnerTexts().then(t => t.map(x => x.trim())), ['Market'],
                   'the sheet did not open on the door the reader is in');
  // The same tools, in the same order and groups, as the menu on a wide screen.
  assert.deepEqual(await sheetTabs('discover'), ['live', 'options', 'deals', 'special', 'wow', 'results', 'filings']);
  assert.deepEqual(await page.locator('#sh-sheet-discover h4').allInnerTexts().then(t => t.map(x => x.trim().toLowerCase())),
                   ['live market', 'money flow', 'company news']);
  assert.match(await page.locator('#sh-sheet-discover .sh-item[data-tab="options"]').innerText(), /open interest/i,
               'a tool in the sheet lost its hint');
  assert.match(await page.locator('#sh-sheet-discover .sh-sheet-lead').innerText(), /What is happening today\?/);
  assert.equal(await page.locator('#sh-sheet-discover .sh-sheet-lead').getAttribute('aria-current'), 'page');
  // It fits the screen it is on, and leaves the top of the page showing behind it.
  await page.waitForFunction(() => Math.round(document.getElementById('sh-sheet').getBoundingClientRect().bottom) === innerHeight,
                             null, { timeout: 4000 }).catch(() => assert.fail('the sheet never came to rest on the bottom edge'));
  const box = await sheet.boundingBox();
  assert.ok(box.y > 60 && box.width <= 900, `the sheet covers the whole screen (${JSON.stringify(box)})`);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'the sheet overflows the page');
  // Another door is one tap away, without leaving the sheet.
  await sheet.locator('.sh-sheet-tab[data-sec="research"]').click();
  await page.locator('#sh-sheet-research').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#sh-sheet-discover').isVisible(), false, 'two doors are showing at once');
  assert.deepEqual(await sheetTabs('research'),
                   ['query', 'lenses', 'forum.html', 'charts', 'strategies', 'concalls', 'investors', 'funds', 'calls']);
  await sheet.locator('.sh-sheet-tab[data-sec="research"]').press('ArrowRight');
  await page.locator('#sh-sheet-portfolio').waitFor({ state: 'visible' });
  assert.deepEqual(await sheetTabs('portfolio'), ['portfolio', 'watchlists', 'allocate', 'planner', 'advisors.html', 'wealth.html']);
  await page.screenshot({ path: path.join(output, '900-sheet-portfolio.png') });
  // Three ways out that are not choosing something: Escape, the cross, the page behind.
  await page.keyboard.press('Escape');
  await sheet.waitFor({ state: 'hidden' });
  assert.equal(await where.getAttribute('aria-expanded'), 'false');
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  await sheet.locator('.sh-sheet-x').click();
  await sheet.waitFor({ state: 'hidden' });
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  await page.mouse.click(450, 30);
  await sheet.waitFor({ state: 'hidden' });
  assert.equal(await page.evaluate(() => document.body.style.overflow), '', 'the page behind stayed locked after the sheet closed');
  // And a pull on the handle: a short one settles back, a long one closes.
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  await page.waitForTimeout(500);
  const grab = await sheet.locator('.sh-sheet-grab').boundingBox();
  const gx = grab.x + grab.width / 2, gy = grab.y + grab.height / 2;
  await page.mouse.move(gx, gy); await page.mouse.down();
  await page.mouse.move(gx, gy + 40, { steps: 8 }); await page.waitForTimeout(700); await page.mouse.up();
  await page.waitForTimeout(450);
  assert.ok(await sheet.isVisible(), 'a short pull on the handle closed the sheet');
  await page.mouse.move(gx, gy); await page.mouse.down();
  await page.mouse.move(gx, gy + 320, { steps: 12 }); await page.mouse.up();
  await sheet.waitFor({ state: 'hidden' });

  // A tool chosen in another door: the sheet goes, the button names the tool,
  // and the sheet marks it as the one open the next time it comes up.
  await where.click();
  await sheet.locator('.sh-sheet-tab[data-sec="research"]').click();
  await page.locator('#sh-sheet-research .sh-item[data-tab="concalls"]').click();
  await page.locator('#view-concalls').waitFor({ state: 'visible' });
  await sheet.waitFor({ state: 'hidden' });
  assert.equal((await where.locator('.sh-where-door').innerText()).trim(), 'Ideas');
  assert.equal((await where.locator('.sh-where-here').innerText()).trim(), 'Concalls');
  assert.equal(await page.locator('#sh-pin').isVisible(), true, 'the pin left the bar on a narrow screen');
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  assert.deepEqual(await sheet.locator('.sh-sheet-tab[aria-selected="true"]').allInnerTexts().then(t => t.map(x => x.trim())), ['Ideas']);
  assert.deepEqual(await sheet.locator('[aria-current="page"]').evaluateAll(ns => ns.map(n => n.dataset.tab)), ['concalls']);
  // The card at the top of a door's list is the door's own page.
  await page.locator('#sh-sheet-research .sh-sheet-lead').click();
  await page.locator('#view-ideahub').waitFor({ state: 'visible' });
  await sheet.waitFor({ state: 'hidden' });
  assert.equal((await where.locator('.sh-where-here').innerText()).trim(), 'Overview');
  // Me has no sheet of its own: its pages are in the Me menu, and the button opens that.
  await page.evaluate(() => window.AltahaNav.go('me', 'vocab', true));
  await page.locator('#view-vocab').waitFor({ state: 'visible' });
  assert.equal((await where.locator('.sh-where-door').innerText()).trim(), 'Me');
  assert.equal((await where.locator('.sh-where-here').innerText()).trim(), 'Glossary');
  await where.click();
  await page.locator('#sh-drawer.open').waitFor({ state: 'visible' });
  assert.equal(await sheet.isVisible(), false);
  await page.keyboard.press('Escape');
  await page.locator('#sh-drawer.open').waitFor({ state: 'detached' });
  // Back on a wide screen the button gives way to the line, and an open sheet does not follow.
  await page.evaluate(() => window.AltahaNav.go('research', 'concalls', true));
  await where.click();
  await sheet.waitFor({ state: 'visible' });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator('#sh-doorbar .sh-crumb-here').waitFor({ state: 'visible' });
  assert.equal(await sheet.isVisible(), false, 'the sheet stayed open on a wide screen');
  assert.equal(await page.locator('#sh-where').count(), 0);

  // "Check a stock" puts the cursor in the search box; "Hide this" sticks.
  await page.locator('.sh-door[data-sec="discover"]').click();
  await start.waitFor({ state: 'visible' });
  await start.locator('.dr-task[data-start="search"]').click();
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), 'sh-q',
               'Check a stock does not put the cursor in the search box');
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await start.locator('#dr-start-x').click();
  assert.equal(await page.locator('#dr-start').count(), 0, 'Hide this did not hide Start here');
  assert.equal(await page.evaluate(() => localStorage.getItem('altaha-start-hidden-v1')), '1');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaNav);
  await page.locator('#view-today .dr-title').waitFor();
  assert.equal(await page.locator('#dr-start').count(), 0, 'Start here came back after it was hidden');

  /* ── 2 · One owner per destination, and no orphans ───────────────────── */

  const owners = {};
  sections.forEach(s => s.tabs.concat(s.extras).forEach(t => {
    assert.equal(owners[t], undefined, `${t} is owned by both ${owners[t]} and ${s.id}`);
    owners[t] = s.id;
  }));
  ['ideas', 'screener', 'charts', 'results', 'investors', 'funds', 'filings', 'concalls',
   'social', 'vocab', 'calls', 'portfolio', 'planner', 'live', 'deals', 'special',
   'wow', 'options', 'allocate', 'score', 'query', 'lenses',
   'today', 'ideahub', 'money', 'strategies'].forEach(t => {
    assert.ok(owners[t], `${t} lost its home in the restructure`);
  });

  /* Each door opens on its own page, and the tools land where their
     question is answered. */
  assert.equal(sections[0].tabs[0], 'today');
  assert.equal(sections[1].tabs[0], 'ideahub');
  assert.equal(sections[2].tabs[0], 'money');
  ['live', 'deals', 'wow', 'special', 'results', 'filings', 'options', 'screener'].forEach(t =>
    assert.equal(owners[t], 'discover', `${t} belongs behind Market`));
  ['ideas', 'query', 'lenses', 'investors', 'funds', 'charts', 'calls', 'strategies', 'concalls'].forEach(t =>
    assert.equal(owners[t], 'research', `${t} belongs behind Ideas`));
  ['portfolio', 'allocate', 'planner'].forEach(t => assert.equal(owners[t], 'portfolio', `${t} belongs behind Portfolio`));
  /* Setups ("Opportunities now") was removed as a tool: Market's own page
     shows what it showed. It must be gone from the map, not merely hidden. */
  assert.equal(owners.discover, undefined, 'the removed Setups tool is still on the map');
  // Factors went the same way.
  assert.equal(owners.factors, undefined, 'the removed Factors tool is still on the map');
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
  // The Tracker became the Track record, one page with the dated calls.
  await shows('#portfolio/tracker', 'view-calls');
  await shows('#research/tracker', 'view-calls');
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
  // Addresses that used to open the removed Setups hub. A link somebody
  // saved or shared has to land on Market, not on a blank page.
  await shows('#discover', 'view-today');
  await shows('#discover/discover', 'view-today');
  // And the removed Factors page: its old addresses open Ideas.
  await shows('#research/factors', 'view-ideahub');
  await shows('#factors', 'view-ideahub');
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
  assert.equal(await page.locator('#view-today .dr-tool').count(), 7, 'Market’s tool cards changed');
  assert.equal(await page.locator('#view-today .dr-tool', { hasText: 'Setups' }).count(), 0,
               'the removed Setups tool still has a card on Market');
  // A card is a door to its tool.
  await page.locator('#view-today .dr-tool[data-goto="discover/live"]').click();
  await page.locator('#view-live').waitFor({ state: 'visible' });
  await page.evaluate(() => window.AltahaNav.go('research', null, true));
  await page.locator('#view-ideahub .dr-universe').waitFor({ state: 'visible' });
  assert.ok(await page.locator('#view-ideahub .dr-tool').count() >= 4);
  await page.evaluate(() => window.AltahaNav.go('portfolio', null, true));
  await page.locator('#view-money .dr-pfhero').waitFor({ state: 'visible' });
  assert.match(page.url(), /#portfolio\/money$/);

  /* The Setups hub is gone. Asking for it by its old name — a button somebody
     still has, a pinned tool from before — opens Market and lights Market's own
     pill, rather than opening nothing or throwing. */
  await page.evaluate(() => localStorage.setItem('altaha-pins-v1', JSON.stringify(['discover', 'deals'])));
  await page.evaluate(() => window.AltahaNav.go('discover', 'discover', true));
  await page.locator('#view-today .dr-hero').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#view-discover').count(), 0, 'the removed Setups page is still in the document');
  assert.deepEqual(await page.locator('#sh-mega [aria-current="page"]').evaluateAll(ns => ns.map(n => n.dataset.sec + '/' + (n.dataset.tab || ''))),
                   ['discover/'], 'Market’s own page is not the one marked open');
  assert.equal(await page.locator('#sh-doorbar').isVisible(), false);
  assert.match(page.url(), /#discover\/today$/);
  assert.doesNotMatch(await page.locator('#view-today').innerText(), /\bSetups\b|Opportunities now/);
  // A tool pinned before it was removed leaves no chip, and takes nothing else with it.
  assert.deepEqual(await page.locator('#dr-desk-pins .dr-pinchip').allInnerTexts().then(t => t.map(x => x.trim())), ['Big trades']);
  await page.evaluate(() => localStorage.removeItem('altaha-pins-v1'));

  /* Factors was removed with it. Its old name opens Ideas; the Score page no
     longer sends anybody there; and the panel that used to fill it does not
     reappear at the foot of Track record, which is where its script fell back
     to when it could not find a page of its own. (The Tracker's own view has
     since merged into the dated record; its id opens that page.) */
  await page.evaluate(() => window.AltahaNav.go('research', 'factors', true));
  await page.locator('#view-ideahub .dr-universe').waitFor({ state: 'visible' });
  assert.match(page.url(), /#research\/ideahub$/);
  await page.evaluate(() => window.AltahaNav.go(null, 'tracker', true));
  await page.locator('#view-calls').waitFor({ state: 'visible' });
  await page.waitForTimeout(1600);
  assert.equal(await page.locator('#lab, #view-calls .lab, #view-tracker').count(), 0, 'the factor panel moved into Track record instead of going');
  await page.evaluate(() => window.AltahaNav.go(null, 'score', true));
  await page.locator('#view-score').waitFor({ state: 'visible' });
  assert.doesNotMatch(await page.locator('#view-score').innerText(), /factor evidence|under Factors/i);
  await page.locator('#view-score [data-goto="calls"]').waitFor();

  // Neither removed tool is offered anywhere: door menus, door bar, footer, hub cards, legacy tabs.
  await page.evaluate(() => window.AltahaNav.go('research', null, true));
  await page.locator('#view-ideahub .dr-universe').waitFor({ state: 'visible' });
  for (const gone of ['discover', 'factors']) {
    const left = await page.locator(`[data-tab="${gone}"], [data-foot-tab="${gone}"], [data-goto="${gone}"], [data-goto$="/${gone}"], #tab-${gone}, #view-${gone}`)
      .evaluateAll(ns => ns.map(n => n.outerHTML.slice(0, 90)));
    assert.deepEqual(left, [], `the removed "${gone}" tool is still offered`);
  }
  assert.equal(await page.locator('.sh-footer a', { hasText: /^(Setups|Factors)$/ }).count(), 0);

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

  /* ── 5 · The door menu, pins, and search ─────────────────────────────── */

  await page.locator('.sh-door', { hasText: /^Ideas$/ }).click();
  await viaMenu('research', 'query');
  await page.locator('#view-query').waitFor({ state: 'visible' });
  assert.equal((await page.locator('#sh-doorbar .sh-crumb-here').innerText()).trim(), 'Screener');
  assert.equal((await page.locator('.sh-door.on').innerText()).trim(), 'Ideas');
  // Pin it, and it waits on Market's desk.
  await page.locator('#sh-pin').click();
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('altaha-pins-v1'))), ['query']);
  assert.equal(await page.locator('#sh-pin').getAttribute('aria-pressed'), 'true');
  await page.locator('.sh-door', { hasText: /^Market$/ }).click();
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
    for (const view of ['today', 'ideahub', 'money', 'ideas', 'allocate', 'score']) {
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
