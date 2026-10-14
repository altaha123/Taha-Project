/* Sharing a quarter's results, in a real browser.

   The results card used to carry one button, "Share on WhatsApp", posting a
   text message and nothing else. It now carries the networks' own marks — X,
   WhatsApp, Telegram, LinkedIn, Facebook — and the card as a picture. The
   failures worth a browser are the silent ones:

     · a logo that is in the markup but draws nothing, at either theme;
     · a network button whose address drops the card's link, which is the only
       way the picture reaches X or Telegram;
     · a shared link (?go=results&q=TARIL) that opens an empty results box, or
       runs the stock analysis instead;
     · the share sheet opening without the card image in it;
     · the row overflowing a 390px phone.

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/results-share');
fs.mkdirSync(output, { recursive: true });

// TARIL's September 2026 quarter as /results returns it from the NSE filing.
const RESULTS = {
  available: true, symbol: 'TARIL', name: 'Transformers And Rectifiers (India) Limited',
  quarter: 'Q2 FY27', as_of: '2026-09-30', filed_at: '13-Oct-2026 16:34:09',
  basis: 'consolidated', pat_label: 'Consolidated profit after tax (as filed)',
  source: 'NSE corporate filing (XBRL, LODR Reg 33)',
  pat_cr: 81.38, pat_yoy_pct: 117.9, pat_yoy_base_cr: 37.35, pat_qoq_base_cr: 64.29,
  revenue_cr: 739.44, revenue_yoy_pct: 60.7, revenue_yoy_base_cr: 460.03,
  net_margin_pct: 11.0, net_margin_yoy_pct: 8.1,
  revenue_series: [{ period: 'Q2 FY27', date: '2026-09-30', value_cr: 739.44 },
                   { period: 'Q1 FY27', date: '2026-06-30', value_cr: 572.34 }],
  pat_series: [{ period: 'Q2 FY27', date: '2026-09-30', value_cr: 81.38 },
               { period: 'Q1 FY27', date: '2026-06-30', value_cr: 64.29 }],
  bullets: ['Net profit rose from ₹37.35 Cr to ₹81.38 Cr YoY (+117.9%)'],
  note: 'Figures as the company filed them with NSE.', disclaimer: 'Educational analysis.'
};

// A real PNG, so the sheet's <img> loads and reports a natural size.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR4nGP4/+H/fwYGBgYADvYD/Qd5yTsAAAAASUVORK5CYII=',
  'base64');

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

(async () => {
  await new Promise(resolve => server.listen(8771, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript(() => {
    localStorage.setItem('altaha-guide-dismissed', '1');
    // Record what each button opens instead of opening it.
    window.__opened = [];
    window.open = (url) => { window.__opened.push(String(url)); return null; };
  });
  const page = await context.newPage(), errors = [], asked = [];
  page.on('pageerror', e => errors.push(String(e.stack)));

  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
    if (u.pathname === '/results') {
      asked.push(u.searchParams.get('ticker'));
      return route.fulfill({ json: RESULTS });
    }
    if (u.pathname === '/og/results.png') {
      return route.fulfill({ status: 200, contentType: 'image/png', body: PNG,
                             headers: { 'Access-Control-Allow-Origin': '*' } });
    }
    return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [],
                                   items: [], sectors: [], rankings: [], status: 'idle' } });
  });

  /* ── 1 · A shared link opens that stock's results, not the analysis ───── */

  await page.goto('http://127.0.0.1:8771/?go=results&q=TARIL', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#rcardwrap', { state: 'visible', timeout: 15000 });
  assert.deepEqual(asked, ['TARIL'], 'the shared link did not ask for TARIL\'s results');
  assert.equal(await page.locator('#rquarter').innerText(), 'Q2 FY27');
  assert.equal(await page.locator('#rtk').inputValue(), 'TARIL');

  /* ── 2 · Every network has its mark, and the mark draws ──────────────── */

  const bar = page.locator('#rsharebar');
  await bar.scrollIntoViewIfNeeded();
  const nets = await bar.locator('.shround').evaluateAll(els => els.map(b => {
    const svg = b.querySelector('svg'), r = svg && svg.getBoundingClientRect();
    return { label: b.getAttribute('aria-label'), w: r ? r.width : 0, h: r ? r.height : 0,
             colour: getComputedStyle(b).color,
             path: !!(svg && svg.querySelector('path[d]')) };
  }));
  assert.deepEqual(nets.map(n => n.label),
    ['Share on X', 'Share on WhatsApp', 'Share on Telegram', 'Share on LinkedIn',
     'Share on Facebook'], 'the row is not the five networks, in order');
  nets.forEach(n => {
    assert.ok(n.path && n.w >= 14 && n.h >= 14, `${n.label}: the logo does not draw`);
  });
  const brand = Object.fromEntries(nets.map(n => [n.label.replace('Share on ', ''), n.colour]));
  assert.equal(brand.WhatsApp, 'rgb(37, 211, 102)', 'WhatsApp is not in its own green');
  assert.equal(brand.Telegram, 'rgb(38, 165, 228)', 'Telegram is not in its own blue');
  assert.ok(await bar.locator('[data-to="sheet"] svg').count(), 'the image button has no glyph');
  assert.ok(await bar.locator('[data-to="copy"] svg').count(), 'copy link has no glyph');
  await page.locator('#rcard').screenshot({ path: path.join(output, 'card-desktop.png') });

  /* ── 3 · Each network gets the card's link, which carries the picture ── */

  const link = encodeURIComponent('/share/results/TARIL?period=Q2-FY27');
  const expect = {
    'Share on X': 'https://x.com/intent/post?text=',
    'Share on WhatsApp': 'https://wa.me/?text=',
    'Share on Telegram': 'https://t.me/share/url?url=',
    'Share on LinkedIn': 'https://www.linkedin.com/sharing/share-offsite/?url=',
    'Share on Facebook': 'https://www.facebook.com/sharer/sharer.php?u='
  };
  for (const [label, prefix] of Object.entries(expect)) {
    await page.evaluate(() => { window.__opened = []; });
    await bar.locator(`[aria-label="${label}"]`).click();
    const opened = await page.evaluate(() => window.__opened);
    assert.equal(opened.length, 1, `${label} opened ${opened.length} windows`);
    assert.ok(opened[0].startsWith(prefix), `${label} opened ${opened[0]}`);
    assert.ok(opened[0].includes(link), `${label} dropped the card's link: ${opened[0]}`);
    assert.ok(!/onrender\.com/.test(opened[0]), `${label} handed out the API host`);
  }
  // A press confirms with a ring and leaves the logo where it was — before
  // and after the confirmation clears.
  const logosLeft = () => bar.locator('.shround').evaluateAll(els => els.map(b => ({
    svg: !!b.querySelector('svg path[d]'), text: b.textContent.trim() })));
  (await logosLeft()).forEach((b, i) => {
    assert.ok(b.svg && !b.text, `button ${i} lost its logo when pressed: "${b.text}"`);
  });
  assert.ok(await bar.locator('.shround.done').count(), 'a press shows no confirmation');
  await page.waitForTimeout(2400);
  (await logosLeft()).forEach((b, i) => {
    assert.ok(b.svg && !b.text, `button ${i} lost its logo after the confirmation cleared`);
  });

  const tg = decodeURIComponent((await page.evaluate(() => {
    window.__opened = [];
    document.querySelector('[aria-label="Share on Telegram"]').click();
    return window.__opened[0];
  })).split('&text=')[1]);
  assert.match(tg, /TARIL — Q2 FY27 results, as filed with NSE\./);
  assert.match(tg, /Profit ₹81\.38 Cr \(\+117\.9% YoY\)/);

  /* ── 4 · The image opens in the sheet, with every way out ────────────── */

  await bar.locator('[data-to="sheet"]').click();
  const sheet = page.locator('#shsheet');
  await sheet.waitFor({ state: 'visible' });
  await page.waitForFunction(() => {
    const img = document.getElementById('shcardimg');
    return img && !img.hidden && img.naturalWidth > 0;
  }, null, { timeout: 10000 });
  assert.match(await page.locator('#shcardimg').getAttribute('src'),
    /\/og\/results\.png\?ticker=TARIL&period=Q2-FY27$/);
  assert.equal(await page.locator('#shttl').innerText(), 'TARIL — Q2 FY27 results');
  const sheetNets = await sheet.locator('.shnet').evaluateAll(els => els.map(b => ({
    text: b.textContent.trim(), svg: !!b.querySelector('svg path[d]') })));
  assert.deepEqual(sheetNets.map(n => n.text), ['X', 'WhatsApp', 'Telegram', 'LinkedIn', 'Facebook']);
  sheetNets.forEach(n => assert.ok(n.svg, `${n.text} in the sheet has no logo`));
  assert.ok(await sheet.locator('[data-do="dl"]').isVisible(), 'no way to download the image');
  assert.ok(await sheet.locator('[data-do="copyimg"]').isVisible(),
    'Copy image is hidden in a browser that can copy images');
  await sheet.locator('.shbox').screenshot({ path: path.join(output, 'sheet-desktop.png') });

  // A press flashes its label and keeps its logo.
  await sheet.locator('[data-do="tg"]').click();
  assert.equal(await sheet.locator('[data-do="tg"] .lbl').textContent(), 'Opened');
  assert.ok(await sheet.locator('[data-do="tg"] svg').count(), 'the logo went with the flash');
  await page.keyboard.press('Escape');
  await sheet.waitFor({ state: 'hidden' });

  /* ── 5 · A phone, and the dark theme ──────────────────────────────────── */

  await page.setViewportSize({ width: 390, height: 844 });
  await bar.scrollIntoViewIfNeeded();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 0, `the page scrolls sideways by ${overflow}px on a phone`);
  const rowRight = await bar.evaluate(el => {
    const r = el.getBoundingClientRect();
    return Math.max(...Array.from(el.children).map(c => c.getBoundingClientRect().right)) - r.right;
  });
  assert.ok(rowRight <= 1, 'a share button hangs off the card on a phone');
  await page.locator('#rcard').screenshot({ path: path.join(output, 'card-phone.png') });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  const dark = await bar.locator('.shnet-x').evaluate(b => ({
    fg: getComputedStyle(b).color, bg: getComputedStyle(b).backgroundColor }));
  assert.notEqual(dark.fg, dark.bg, 'the X mark vanishes on the dark theme');
  assert.notEqual(dark.fg, 'rgb(0, 0, 0)', 'the X mark is black on the dark theme');
  await page.locator('#rcard').screenshot({ path: path.join(output, 'card-dark.png') });

  assert.deepEqual(errors, [], 'the page threw:\n' + errors.join('\n'));
  await browser.close();
  server.close();
  console.log('results share: all assertions passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
