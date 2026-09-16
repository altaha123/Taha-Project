/* The investor portfolios view in a real Chromium, against fixtures produced
   by the real backend modules (backend/tests/make_investors_fixture.py).

   This page makes public, attributed claims about what named private
   individuals own, so what is guarded here is not layout — it is whether the
   page can overstate a position, invent one, or present a disclosed floor as
   though it were a portfolio:

     · a rolled-up total must always be shown broken into the filed rows it
       was summed from. 20.91% that cannot be taken apart is an assertion.
     · one name filed twice in a register must be summed, not collapsed.
     · a family trust must be labelled as one wherever it is counted.
     · a promoter stake must be labelled — an investor's own company is not a
       stock pick.
     · a company dropping off must never be called a sale.
     · the 1% floor and the quarterly lag must be on the page, in the header of
       every portfolio, not folded into a footnote.
     · a dead investor must redirect and say so. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/investors');
fs.mkdirSync(output, { recursive: true });

const fx = n => JSON.parse(
  fs.readFileSync(path.join(root, 'tests/fixtures/investors-' + n + '.json'), 'utf8'));

const directory = fx('directory');
const portfolios = {
  'vijay-kedia': fx('vijay-kedia'),
  'rekha-jhunjhunwala': fx('rekha-jhunjhunwala'),
  'rakesh-jhunjhunwala': fx('rakesh-jhunjhunwala'),
  'dolly-khanna': fx('dolly-khanna'),
};

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

const num = t => Number(String(t).replace(/[^0-9.\-]/g, ''));

/* The shell nav replaces the legacy tab strip and hides it, so the old buttons
   are present but invisible; and `innerText` on a display:none element falls
   back to textContent, which would make every assertion below pass against a
   view nobody can see. Hence AltahaNav plus an explicit visibility check —
   the same helper the filings-views test needed for the same reason. */
async function openTab(page, id) {
  await page.waitForLoadState('load');
  // The homepage re-applies its default tab up to about a second after load.
  // Navigating inside that window looks like it worked — the view goes
  // visible — and is then silently undone, so the wait is before the first
  // attempt and every attempt re-checks AFTER a pause rather than on the spot.
  await page.waitForTimeout(1200);
  for (let attempt = 0; attempt < 6; attempt++) {
    await page.evaluate(t => window.AltahaNav.go('screener', t, true), id);
    try {
      await page.locator('#view-' + id).waitFor({ state: 'visible', timeout: 2000 });
      await page.waitForTimeout(400);
      if (await page.locator('#view-' + id).isVisible()) return;
    } catch (_) { /* retry */ }
  }
  assert.fail('could not open the ' + id + ' view');
}

/* The homepage re-applies its default tab a moment after load, so a view
   opened and then merely read from can be hidden again underneath you — which
   is how the ownership test once asserted against a pane nobody could see.
   Every interaction goes through this rather than trusting the earlier open. */
async function onTab(page, id) {
  if (!(await page.locator('#view-' + id).isVisible())) await openTab(page, id);
  return page;
}

(async () => {
  await new Promise(r => server.listen(8775, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const page = await context.newPage(), errors = [];
  let directoryCalls = 0;
  page.on('pageerror', e => errors.push(String(e && (e.stack || e.message || e))));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    // An external <script src> answered with JSON is parsed as JavaScript and
    // throws "Unexpected token ':'". That is the stub's fault, not the page's,
    // and left in it would drown the page errors this test actually cares
    // about — the homepage loads three of them.
    if (route.request().resourceType() === 'script') {
      return route.fulfill({ body: '', contentType: 'text/javascript' });
    }
    if (u.pathname === '/investors') { directoryCalls++; return route.fulfill({ json: directory }); }
    if (u.pathname === '/investor') {
      const id = u.searchParams.get('id');
      return route.fulfill({ json: portfolios[id] || { available: false, message: 'unknown' } });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });

  await page.goto('http://127.0.0.1:8775/', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('load');
  await page.waitForTimeout(1200);

  // Nothing is fetched until the tab is opened.
  assert.equal(directoryCalls, 0, 'the investor list must not load before its tab is opened');

  await openTab(page, 'investors');
  await page.locator('.iv-card').first().waitFor({ state: 'visible' });
  assert.ok(await page.locator('#view-investors').isVisible(),
    'the investors view must actually be on screen');
  assert.equal(directoryCalls, 1);

  // ── The directory ────────────────────────────────────────────────────────
  const names = await page.locator('.iv-card b').allInnerTexts();
  assert.ok(names.includes('Vijay Kedia'));
  assert.ok(names.includes('Rekha Jhunjhunwala'));
  // A dead investor gets no card of his own.
  assert.ok(!names.includes('Rakesh Jhunjhunwala'),
    'Rakesh Jhunjhunwala died in 2022 and must not have a portfolio card');
  // The sample is stated: a portfolio built from 8 companies out of 2,000 is
  // not the same claim as one built from all of them.
  assert.match(await page.locator('.iv-cover').innerText(), /companies read so far/i);

  // The caveats are on the page before any portfolio is opened.
  const lead = await page.locator('.iv-lead').innerText();
  assert.match(lead, /above 1%/);
  assert.match(lead, /quarter/i);

  // ── A rolled-up total ────────────────────────────────────────────────────
  await onTab(page, 'investors');
  await page.locator('.iv-card', { hasText: 'Vijay Kedia' }).first().click();
  await page.locator('.iv-pos').first().waitFor();

  const atul = page.locator('.iv-pos', { hasText: 'ATULAUTO' }).first();
  assert.ok(Math.abs(num(await atul.locator('.iv-pos-head .vv').innerText()) - 20.91) < 0.01,
    'Atul Auto must read 20.91% — 18.20 in his own name plus 2.71 through his company');

  // THE GUARD THAT MATTERS: the total must come apart on screen.
  const parts = atul.locator('.iv-parts li');
  assert.equal(await parts.count(), 2, 'a summed total must show the rows it was summed from');
  const partText = await atul.locator('.iv-parts').innerText();
  assert.match(partText, /VIJAY KEDIA/);
  assert.match(partText, /KEDIA SECURITIES/);
  assert.match(partText, /own name/i);
  assert.match(partText, /their company/i);
  const partVals = (await parts.locator('.vv').allInnerTexts()).map(num);
  assert.ok(Math.abs(partVals.reduce((a, b) => a + b, 0) - 20.91) < 0.01,
    `the parts shown (${partVals}) must add up to the headline`);

  // A single-row position is not dressed up with a breakdown it does not have.
  const elecon = page.locator('.iv-pos', { hasText: 'ELECON' }).first();
  assert.equal(await elecon.locator('.iv-parts li').count(), 0);

  // Movement is named and signed.
  assert.match(await atul.locator('.mv').innerText(), /added \+0\.60 pp/);

  // ── Two folios of one name ───────────────────────────────────────────────
  await onTab(page, 'investors');
  await page.locator('#iv-back').click();
  await page.locator('.iv-card', { hasText: 'Rekha Jhunjhunwala' }).first().click();
  await page.locator('.iv-pos').first().waitFor();

  const titan = page.locator('.iv-pos', { hasText: 'TITAN' }).first();
  assert.ok(Math.abs(num(await titan.locator('.iv-pos-head .vv').innerText()) - 5.31) < 0.01,
    'Titan names her twice, 4.24 and 1.07 — the position is 5.31, not 1.07');
  assert.equal(await titan.locator('.iv-parts li').count(), 2);

  // ── A family trust is counted AND labelled ───────────────────────────────
  const metro = page.locator('.iv-pos', { hasText: 'METROBRAND' }).first();
  assert.ok(Math.abs(num(await metro.locator('.iv-pos-head .vv').innerText()) - 14.37) < 0.01);
  const metroParts = await metro.locator('.iv-parts').innerText();
  assert.equal((metroParts.match(/family trust/gi) || []).length, 3,
    'every trust row must say it is a trust, not just the block as a whole');
  assert.match(metroParts, /ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST/);
  // And the judgement is stated in prose as well as in a tag.
  assert.match(await page.locator('.iv-notes').innerText(),
    /discretionary trust is not the same as shares owned outright/i);

  // ── A promoter stake is not presented as a stock pick ────────────────────
  const star = page.locator('.iv-pos', { hasText: 'STARHEALTH' }).first();
  assert.match(await star.innerText(), /promoter stake/i);
  assert.match(await star.locator('.mv').innerText(), /trimmed/);

  // ── A company dropping off is never called a sale ────────────────────────
  const gone = page.locator('.iv-list.is-gone');
  assert.match(await page.locator('.iv-sub').innerText(), /fallen below the 1% threshold or been sold/i);
  assert.match(await page.locator('.iv-sub').innerText(), /does not say which/i);
  assert.ok(!/\bsold\b(?!\s*—|\s*&mdash)/i.test(await gone.innerText()),
    'the list itself must not assert a sale');
  assert.match(await gone.innerText(), /CRISIL/);

  // ── The floor and the lag are in the portfolio header ────────────────────
  const asof = await page.locator('.iv-asof').innerText();
  assert.match(asof, /below 1%/i);
  assert.match(asof, /Q1 FY27/);
  assert.match(asof, /compared with Q4 FY26/);

  // ── Which names were counted as this person ──────────────────────────────
  const who = await page.locator('.iv-who').innerText();
  assert.match(who, /Rekha Jhunjhunwala/);
  assert.match(who, /trustee/i);

  // ── A dead investor redirects, and says so ───────────────────────────────
  // Reached the way a deep link or an old bookmark would: his id still
  // resolves, and what it resolves TO is the point.
  await onTab(page, 'investors');
  await page.locator('#iv-back').click();
  await page.locator('.iv-card').first().waitFor({ state: 'visible' });
  await page.evaluate(() => {
    document.querySelector('.iv-card').setAttribute('data-id', 'rakesh-jhunjhunwala');
  });
  await page.locator('.iv-card').first().click();
  await page.locator('.iv-redirect').waitFor();
  const redirect = await page.locator('.iv-redirect').innerText();
  assert.match(redirect, /Rakesh Jhunjhunwala/);
  assert.match(redirect, /2022/);
  assert.match(await page.locator('.iv-name').innerText(), /Rekha Jhunjhunwala/);

  // ── An investor with nothing recorded says so, and what it looked for ────
  await onTab(page, 'investors');
  await page.locator('#iv-back').click();
  await page.locator('.iv-card').first().waitFor({ state: 'visible' });
  await page.locator('.iv-card', { hasText: 'Dolly Khanna' }).first().click();
  await page.locator('.iv-empty:not(.is-loading)').waitFor();
  assert.match(await page.locator('.iv-empty').innerText(), /Nothing has been recorded/i);
  assert.match(await page.locator('.iv-looking').innerText(), /Dolly Khanna/);
  assert.equal(await page.locator('.iv-pos').count(), 0,
    'no positions at all rather than an empty-looking list');

  // ── Phone through desktop, both themes ───────────────────────────────────
  await onTab(page, 'investors');
  await page.locator('#iv-back').click();
  await page.locator('.iv-card', { hasText: 'Rekha Jhunjhunwala' }).first().click();
  await page.locator('.iv-pos').first().waitFor();
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      await page.waitForTimeout(60);
      const over = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 1, `horizontal overflow ${over}px at ${width}`);
      const shot = await page.locator('#investors-body').boundingBox();
      await page.screenshot({
        path: path.join(output, `investors-${width}-${theme}.png`),
        fullPage: true,
        clip: shot
          ? { x: 0, y: Math.max(0, shot.y), width, height: Math.min(shot.height, 2600) }
          : undefined,
      });
    }
  }

  assert.deepEqual(errors, [], 'page errors: ' + errors.join('\n'));
  await browser.close();
  server.close();
  console.log('investor portfolios ok — screenshots in ' +
    path.relative(process.cwd(), output));
})().catch(e => { console.error(e); process.exit(1); });
