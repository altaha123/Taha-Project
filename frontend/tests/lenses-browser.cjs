/* The Lenses views in a real Chromium, against responses produced by the real
   backend (backend/tests/make_lenses_fixture.py).

   What is guarded:
     · the Research menu carries a LENSES column in the same shape as the
       others, on desktop and in the mobile drawer, and both items route;
     · the index shows every lens, a count per live lens, and "Coming soon"
       with its reason, never a count, for the blocked ones;
     · a lens page lists its rules, marks each rule ✓ / ✗ / – with the figure
       behind it on hover, and keeps near misses in a collapsible section;
     · convergence ranks companies with a badge per lens met;
     · the stock page says "Meets N of 10 lenses" with badges linking to each;
     · every view carries the notice, and no view uses the words the site's
       SEBI position rules out. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/lenses');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/lenses.json'), 'utf8'));
const NOTICE = /rules-based filters applied to historical financial data\. They are not investment advice or recommendations\./;
const BANNED = /\b(buy|sell|target|recommend|top picks|best stocks|should|opportunity)\b/i;

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

function answer(u) {
  const p = u.pathname;
  if (p === '/api/lenses') return fx.index;
  if (p === '/api/lenses/convergence') return fx.convergence[u.searchParams.get('min_lenses') || '3'];
  let m = p.match(/^\/api\/lenses\/stock\/(.+)$/);
  if (m) return fx.stock[decodeURIComponent(m[1])] || fx.stock.NOPE;
  m = p.match(/^\/api\/lenses\/([a-z]+)$/);
  if (m) return fx.lens[m[1]];
  return null;
}

async function wire(context) {
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = route.request().resourceType();
    if (['font', 'stylesheet', 'image'].includes(type)) return route.abort();
    if (type === 'script') return route.fulfill({ body: '', contentType: 'text/javascript' });
    const body = answer(u);
    if (body) return route.fulfill({ json: body });
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
}

async function viewText(page, id) {
  return (await page.locator('#' + id).innerText());
}

(async () => {
  await new Promise(r => server.listen(8781, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  // ── Desktop: the Research menu ─────────────────────────────────────────
  const desk = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await wire(desk);
  const page = await desk.newPage();
  page.on('pageerror', e => errors.push(String(e && (e.stack || e.message || e))));
  await page.goto('http://127.0.0.1:8781/', { waitUntil: 'load' });
  await page.waitForTimeout(1200);

  await page.locator('.sh-top[data-sec="research"]').hover();
  const mega = page.locator('.sh-mega.open');
  await mega.waitFor({ state: 'visible' });
  const heads = await mega.locator('.sh-col h4').allInnerTexts();
  assert.deepEqual(heads.map(h => h.toUpperCase()),
    ['STOCKS', 'THE EVIDENCE', 'OWNERSHIP', 'NEWS', 'LENSES']);
  const col = mega.locator('.sh-col').nth(4);
  assert.equal(await col.locator('.sh-item').count(), 2);
  assert.equal(await col.locator('.sh-item .sh-ico svg').count(), 2, 'each item has an icon tile');
  const colText = await col.innerText();
  assert.match(colText, /Philosophy lenses/);
  assert.match(colText, /Stocks screened the way great investors think/);
  assert.match(colText, /Convergence/);
  assert.match(colText, /Stocks that clear three or more lenses/);
  // Same shape as its neighbours: the heading is mono uppercase.
  const h4 = await col.locator('h4').evaluate(n => {
    const s = getComputedStyle(n); return [s.textTransform, s.fontFamily];
  });
  assert.equal(h4[0], 'uppercase');
  // All five columns sit on one row at this width.
  const tops = await mega.locator('.sh-col').evaluateAll(ns => ns.map(n => Math.round(n.getBoundingClientRect().top)));
  assert.equal(new Set(tops).size, 1, 'the five Research columns share one row at 1440px: ' + tops);
  await page.waitForTimeout(700);     // the columns lift in on staggered delays
  await page.screenshot({ path: path.join(output, 'menu-desktop.png') });

  // ── The index ──────────────────────────────────────────────────────────
  await col.locator('.sh-item').first().click();
  await page.locator('#view-lenses .ln-card').first().waitFor({ state: 'visible' });
  assert.ok(await page.locator('#view-lenses').isVisible());
  assert.match(page.url(), /#research\/lenses$/);
  assert.equal(await page.locator('.ln-card').count(), 10);
  assert.equal(await page.locator('.ln-card.is-soon').count(), 3);
  for (const id of ['moat', 'coffeecan', 'capcycle']) {
    const card = page.locator('.ln-card[data-lens="' + id + '"]');
    assert.match(await card.innerText(), /Coming soon/i);
    assert.equal(await card.locator('.ln-count').count(), 0, id + ' must not show a count');
  }
  const qglp = page.locator('.ln-card[data-lens="qglp"]');
  assert.match(await qglp.innerText(), /Raamdeo Agrawal/i);
  await page.waitForTimeout(1800);      // let the count-up finish
  assert.equal(await qglp.locator('.ln-count b').innerText(),
    String(fx.index.lenses.find(l => l.id === 'qglp').counts.pass));
  assert.match(await viewText(page, 'view-lenses'), NOTICE);
  assert.doesNotMatch(await viewText(page, 'view-lenses'), BANNED);
  await page.screenshot({ path: path.join(output, 'index-desktop.png'), fullPage: true });

  // ── One lens ───────────────────────────────────────────────────────────
  await qglp.click();
  await page.locator('.ln-hero').waitFor({ state: 'visible' });
  assert.match(page.url(), /#research\/lenses\/qglp$/);
  assert.equal(await page.locator('.ln-rulelist li').count(), 4);
  const passRow = page.locator('.ln-results .ln-table tbody tr').first();
  assert.match(await passRow.innerText(), /GROW/);
  assert.equal(await passRow.locator('.ln-cell.is-pass').count(), 4);
  const tip = await passRow.locator('.ln-cell').first().getAttribute('title');
  assert.match(tip, /^Passes: Return on equity above 20% · \d/, 'hover shows the value: ' + tip);
  assert.match(await passRow.innerText(), /4 of 4/);
  const near = page.locator('details.ln-near');
  assert.equal(await near.getAttribute('open'), null, 'near misses start collapsed');
  await near.locator('summary').click();
  const nearRow = near.locator('tbody tr').first();
  assert.match(await nearRow.innerText(), /STEADY/);
  assert.equal(await nearRow.locator('.ln-cell.is-fail').count(), 1);
  assert.match(await viewText(page, 'view-lenses'), NOTICE);
  assert.doesNotMatch(await viewText(page, 'view-lenses'), BANNED);
  await page.screenshot({ path: path.join(output, 'lens-desktop.png'), fullPage: true });

  // A deep link lands on the lens, and back returns to the index.
  await page.goto('http://127.0.0.1:8781/#research/lenses/moat', { waitUntil: 'load' });
  await page.locator('.ln-soonbox').waitFor({ state: 'visible', timeout: 8000 });
  assert.match(await page.locator(".ln-soonbox").innerText(), /Coming soon/i);
  assert.equal(await page.locator('.ln-table').count(), 0, 'a coming-soon lens lists no companies');
  await page.locator('.ln-back a').click();
  await page.locator('.ln-card').first().waitFor({ state: 'visible' });

  // ── Convergence ────────────────────────────────────────────────────────
  await page.evaluate(() => window.AltahaNav.go('research', 'convergence', true));
  await page.locator('#view-convergence .ln-convbar').waitFor({ state: 'visible' });
  await page.locator('.ln-chip[data-min="2"]').click();
  await page.locator('.ln-conv li').first().waitFor({ state: 'visible' });
  const first = page.locator('.ln-conv li').first();
  assert.match(await first.innerText(), /GROW/);
  const badges = first.locator('.ln-badge');
  assert.equal(await badges.count(), fx.convergence['2'].stocks[0].lenses.length);
  assert.match(await viewText(page, 'view-convergence'), NOTICE);
  assert.doesNotMatch(await viewText(page, 'view-convergence'), BANNED);
  await page.screenshot({ path: path.join(output, 'convergence-desktop.png'), fullPage: true });
  await badges.first().click();
  await page.locator('.ln-hero').waitFor({ state: 'visible' });

  // ── Dark theme: tokens, not a second stylesheet ────────────────────────
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await page.evaluate(() => window.AltahaNav.go('research', 'lenses', true));
  await page.waitForTimeout(400);
  const bg = await page.locator('.ln-card').first().evaluate(n => getComputedStyle(n).backgroundColor);
  assert.notEqual(bg, 'rgb(255, 253, 248)', 'cards take the dark card colour');
  await page.screenshot({ path: path.join(output, 'index-dark.png'), fullPage: true });

  // ── The stock page strip ───────────────────────────────────────────────
  const sp = await desk.newPage();
  sp.on('pageerror', e => errors.push(String(e && (e.stack || e.message || e))));
  await sp.goto('http://127.0.0.1:8781/stock.html?ticker=GROW', { waitUntil: 'load' });
  await sp.locator('#stk-lenses .ln-strip').waitFor({ state: 'visible' });
  const strip = await sp.locator('#stk-lenses').innerText();
  assert.match(strip, new RegExp('Meets ' + fx.stock.GROW.meets + ' of 10 lenses'));
  assert.equal(await sp.locator('#stk-lenses .ln-badge').count(), 10);
  assert.equal(await sp.locator('#stk-lenses .ln-badge.is-pass').count(), fx.stock.GROW.meets);
  assert.match(await sp.locator('#stk-lenses .ln-badge.is-pass').first().getAttribute('href'),
    /index\.html#research\/lenses\/[a-z]+$/);
  assert.match(strip, NOTICE);
  assert.doesNotMatch(strip, BANNED);
  await sp.screenshot({ path: path.join(output, 'stock-strip.png') });
  await sp.goto('http://127.0.0.1:8781/stock.html?ticker=NOPE', { waitUntil: 'load' });
  await sp.locator('#stk-lenses .ln-strip.is-empty').waitFor({ state: 'visible' });

  // ── Mobile: the drawer carries the same column, and the views fit ──────
  const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await wire(mob);
  const mp = await mob.newPage();
  mp.on('pageerror', e => errors.push(String(e && (e.stack || e.message || e))));
  await mp.goto('http://127.0.0.1:8781/', { waitUntil: 'load' });
  await mp.waitForTimeout(1200);
  await mp.locator('#sh-burger').click();
  const drawer = mp.locator('#sh-drawer');
  await drawer.waitFor({ state: 'visible' });
  const dtext = await drawer.innerText();
  assert.match(dtext, /Philosophy lenses/);
  assert.match(dtext, /Convergence/);
  await mp.screenshot({ path: path.join(output, 'menu-mobile.png') });
  await drawer.locator('.sh-item[data-tab="lenses"]').click();
  await mp.locator('#view-lenses .ln-card').first().waitFor({ state: 'visible' });
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 1, 'no horizontal page scroll on a phone: ' + overflow);
  await mp.screenshot({ path: path.join(output, 'index-mobile.png'), fullPage: true });
  await mp.locator('.ln-card[data-lens="qglp"]').click();
  await mp.locator('.ln-table').first().waitFor({ state: 'visible' });
  const overflow2 = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow2 <= 1, 'the rule table scrolls inside its box, not the page: ' + overflow2);
  await mp.screenshot({ path: path.join(output, 'lens-mobile.png'), fullPage: true });

  const mine = errors.filter(e => /lenses\.js|AltahaLenses|ln-/.test(e));
  assert.deepEqual(mine, [], 'lenses.js raised: ' + mine.join('\n'));
  await browser.close();
  server.close();
  console.log('lenses browser test: ok');
})().catch(e => { console.error(e); process.exit(1); });
