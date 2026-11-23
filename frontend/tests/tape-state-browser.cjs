/* The tag at the head of the tape, in a real browser.
 *
 * The tag used to be the word "Live", written into the header as a constant.
 * At ten at night it sat above a page that said "Market closed", on gold, with
 * a beating dot. It is a claim about the session, so it has to follow it.
 *
 * What this asserts:
 *   · /market says closed: the tag reads Closed, is not gold and does not beat
 *   · /market says open: the tag reads Live, on gold, beating
 *   · /market says pre: the tag reads Pre-open, the word the Market page uses
 *   · /market cannot be read: the tag goes by the IST clock, wherever the
 *     reader's own clock is set. A weekday at 11:00 is Live; 21:42, a Sunday
 *     and 08:00 are not
 *   · a tab left open across 15:30 with /market gone quiet turns to Closed by
 *     itself, with no reload
 *   · the tag is the same on the stock page: it belongs to the header
 *
 * Provider calls are fulfilled from fixtures; nothing here touches a network.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend'), out = path.resolve('test-results/tape-state');
const PORT = 8791;

const indices = [
  { label: 'NIFTY 50', level: 25349.65, change_pct: -1.75 },
  { label: 'SENSEX', level: 82435.99, change_pct: -1.77 }
];

const server = http.createServer((req, res) => {
  const name = path.join(root, decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!name.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' :
      name.endsWith('.html') ? 'text/html' : name.endsWith('.png') ? 'image/png' : 'application/octet-stream');
    res.end(fs.readFileSync(name));
  } catch (e) { res.writeHead(404).end(); }
});

/* A page whose /market answers with whatever `market.status` holds at the
   time: 'open', 'pre', 'closed', or null for a backend that cannot be read.
   `at` fixes the browser's clock; `zone` is the reader's own time zone. */
async function open(browser, { file = 'index.html', status, at, zone, ticking = false }) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, timezoneId: zone || 'Asia/Kolkata' });
  await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-test'));
  await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
  const market = { status };
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    const cors = { 'access-control-allow-origin': '*' };
    if (u.pathname === '/market') {
      if (!market.status) return route.fulfill({ status: 503, json: { detail: 'unavailable' }, headers: cors });
      return route.fulfill({ json: { indices, status: market.status, ist: '' }, headers: cors });
    }
    return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' }, headers: cors });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  if (at) {
    // `ticking` lets time be moved forward with its timers; otherwise the
    // clock simply reads `at`.
    if (ticking) await page.clock.install({ time: new Date(at) });
    else await page.clock.setFixedTime(new Date(at));
  }
  const asked = page.waitForResponse(r => new URL(r.url()).pathname === '/market');
  await page.goto(`http://127.0.0.1:${PORT}/${file}`, { waitUntil: 'domcontentloaded' });
  await page.locator('#sh-livetag').waitFor();
  await asked;
  return { context, page, errors, market };
}

/* What the reader sees in the tag. */
function tag(page) {
  return page.locator('#sh-livetag').evaluate(n => {
    const dot = n.querySelector('.sh-dot');
    return {
      text: n.innerText.trim().toUpperCase(),
      state: n.getAttribute('data-state'),
      off: n.classList.contains('is-off'),
      bg: getComputedStyle(n).backgroundColor,
      gold: getComputedStyle(document.documentElement).getPropertyValue('--gold').trim(),
      beat: getComputedStyle(dot, '::after').display !== 'none' && getComputedStyle(dot, '::after').animationName !== 'none',
      pulse: getComputedStyle(dot).animationName,
      label: document.getElementById('sh-ticker').getAttribute('aria-label')
    };
  });
}
const reads = (page, text) => page.waitForFunction(
  t => (document.getElementById('sh-livetag-t') || {}).textContent === t, text, { timeout: 8000 });

/* Monday 23 November 2026, by the IST clock. */
const IST = hhmm => `2026-11-23T${hhmm}:00+05:30`;

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const done = async t => { assert.deepEqual(t.errors, [], t.errors.join('\n')); await t.context.close(); };
  try {
    /* ── 1 · /market says closed, at the hour the tag was caught saying Live ── */
    let t = await open(browser, { status: 'closed', at: IST('21:42') });
    await reads(t.page, 'Closed');
    let g = await tag(t.page);
    assert.equal(g.text, 'CLOSED');
    assert.equal(g.state, 'closed');
    assert.ok(g.off, 'a closed market still wears the live tag');
    assert.equal(g.beat, false, 'the dot beats on a closed market');
    assert.equal(g.pulse, 'none', 'the dot pulses on a closed market');
    assert.match(g.label, /last close/i);
    assert.doesNotMatch(g.label, /live/i);
    const closedBg = g.bg;
    await t.page.locator('.sh-ticker').screenshot({ path: path.join(out, 'closed.png') });
    await done(t);

    /* ── 2 · /market says open ─────────────────────────────────────────────── */
    t = await open(browser, { status: 'open', at: IST('11:00') });
    await reads(t.page, 'Live');
    g = await tag(t.page);
    assert.equal(g.text, 'LIVE');
    assert.equal(g.state, 'open');
    assert.equal(g.off, false);
    assert.equal(g.beat, true, 'the dot is still on an open market');
    assert.equal(g.label, 'Live market prices');
    assert.notEqual(g.bg, closedBg, 'open and closed look the same');
    await t.page.locator('.sh-ticker').screenshot({ path: path.join(out, 'open.png') });
    await done(t);

    /* /market outranks the clock: a holiday falls on a weekday at eleven, and
       a special session trades after half past three. */
    t = await open(browser, { status: 'closed', at: IST('11:00') });
    await reads(t.page, 'Closed');
    await done(t);
    t = await open(browser, { status: 'open', at: IST('18:30') });
    await reads(t.page, 'Live');
    await done(t);

    /* ── 3 · /market says pre ──────────────────────────────────────────────── */
    t = await open(browser, { status: 'pre', at: IST('09:05') });
    await reads(t.page, 'Pre-open');
    g = await tag(t.page);
    assert.equal(g.state, 'pre');
    assert.ok(g.off);
    assert.equal(g.beat, false);
    await done(t);

    /* ── 4 · /market cannot be read: the IST clock, in any reader's zone ───── */
    for (const [at, zone, want] of [
      [IST('11:00'), 'Asia/Kolkata', 'Live'],
      [IST('11:00'), 'America/Los_Angeles', 'Live'],       // Sunday evening there
      [IST('21:42'), 'Asia/Kolkata', 'Closed'],
      [IST('21:42'), 'Pacific/Auckland', 'Closed'],        // Tuesday morning there
      [IST('09:14'), 'Europe/London', 'Pre-open'],
      [IST('09:15'), 'Europe/London', 'Live'],
      [IST('15:29'), 'Asia/Tokyo', 'Live'],
      [IST('15:30'), 'Asia/Tokyo', 'Closed'],
      ['2026-11-22T11:00:00+05:30', 'Asia/Kolkata', 'Closed'],   // a Sunday
      ['2026-11-21T11:00:00+05:30', 'America/New_York', 'Closed'] // a Saturday
    ]) {
      t = await open(browser, { status: null, at, zone });
      await reads(t.page, want).catch(async () => {
        assert.fail(`${at} read in ${zone}: wanted ${want}, the tag says ${(await tag(t.page)).text}`);
      });
      await done(t);
    }

    /* ── 5 · A tab left open across the close ─────────────────────────────── */
    t = await open(browser, { status: 'open', at: IST('15:27'), ticking: true });
    await reads(t.page, 'Live');
    t.market.status = null;                 // the backend goes quiet
    await t.page.clock.runFor('06:00');     // 15:33, and nobody has reloaded
    await reads(t.page, 'Closed');
    assert.equal((await tag(t.page)).beat, false);
    await done(t);

    /* …and one where /market keeps answering, and says so itself. */
    t = await open(browser, { status: 'open', at: IST('15:27'), ticking: true });
    await reads(t.page, 'Live');
    t.market.status = 'closed';
    await t.page.clock.runFor('02:00');
    await reads(t.page, 'Closed');
    await done(t);

    /* ── 6 · The stock page wears the same header ─────────────────────────── */
    t = await open(browser, { file: 'stock.html?ticker=RELIANCE', status: 'closed', at: IST('21:42') });
    await reads(t.page, 'Closed');
    assert.ok((await tag(t.page)).off);
    await t.context.close();

    /* ── 7 · Dark theme: closed is still not gold ─────────────────────────── */
    t = await open(browser, { status: 'closed', at: IST('21:42') });
    await t.page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await reads(t.page, 'Closed');
    await t.page.locator('.sh-ticker').screenshot({ path: path.join(out, 'closed-dark.png') });
    await done(t);

    console.log('tape state: ok');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
