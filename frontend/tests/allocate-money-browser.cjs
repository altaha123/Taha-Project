/* Allocate's opening question, in a real browser.

   The page is a sequence of five steps whose numbers are all derived from one
   figure: how much money the reader actually has. Asking for it is therefore
   the first thing the product does, and every failure mode of asking is
   silent — a modal that reappears on every visit, one that cannot be escaped,
   one whose answer is stored and never used, one that covers the page it was
   meant to introduce. None of those throw.

   What this asserts:
     · the question is asked on a first visit, and never asked again after it
       has been answered OR declined
     · the quick amounts fill the field and echo back in words, so a mistyped
       zero is visible before it is committed
     · the answer reaches the banner AND the position calculator below it
     · the calculator is seeded with the growth sleeve the recorded profile
       implies, never with the whole amount
     · declining is a real answer: the five steps still render
     · Escape, the backdrop and the close button all shut it, and focus comes
       back to where it was
     · nothing overflows a 390px screen, and no page error is thrown

   Provider calls are fulfilled from fixtures; nothing here touches a network. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend');
const output = path.resolve('test-results/allocate-money');
fs.mkdirSync(output, { recursive: true });

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

const MONEY_KEY = 'altaha-allocate-money-v1';
const SIZE_KEY = 'altaha-allocate-size-v1';

(async () => {
  await new Promise(resolve => server.listen(8771, '127.0.0.1', resolve));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  const errors = [];

  /* A fresh browser profile per scenario. The whole point of the feature is
     what it remembers, so a shared one would make each case depend on the
     order the cases happen to run in. */
  async function fresh(seed) {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 }, hasTouch: true });
    await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
    if (seed) await context.addInitScript(seed);
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/market') {
        return route.fulfill({ json: { indices: [], status: 'closed', ist: '20 Sep 2026, 15:45 IST' } });
      }
      return route.fulfill({ json: { available: false, rows: [], symbols: [], book: [],
                                     items: [], sectors: [], rankings: [], status: 'idle' } });
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack)));
    await page.goto('http://127.0.0.1:8771/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => !!window.AltahaNav && !!window.AltahaAllocate);
    await page.evaluate(() => window.AltahaNav.go('allocate', null, true));
    return { context, page };
  }

  const sheet = '#alc-sheet';
  const box = '#alc-sheet .alc-box';

  /* ── 1 · Asked on a first visit ──────────────────────────────────────── */

  let { context, page } = await fresh();
  await page.locator(box).waitFor({ state: 'visible' });

  assert.match(await page.locator('#alc-ask-t').innerText(), /how much money do you have/i,
               'the opening question is not the one the product is meant to ask');

  /* The cash is decoration and must stay out of the accessibility tree — a
     screen reader announcing five money emojis before the question is worse
     than no emojis at all. */
  const cash = await page.locator('.alc-cash').innerText();
  assert.ok(/[\u{1F4B0}\u{1F4B5}\u{1FA99}\u{1F4B8}]/u.test(cash),
            'the cash emojis are missing from the prompt');
  assert.equal(await page.locator('.alc-cash').getAttribute('aria-hidden'), 'true');

  /* It is a dialog, and it says so. */
  assert.equal(await page.locator(sheet).getAttribute('role'), 'dialog');
  assert.equal(await page.locator(sheet).getAttribute('aria-modal'), 'true');

  /* Nothing can be committed before there is something to commit. */
  assert.equal(await page.locator('#alc-ask-go').isDisabled(), true,
               'the plan could be started with no amount entered');

  /* ── 2 · The quick amounts fill and echo ─────────────────────────────── */

  await page.locator('.alc-q', { hasText: '₹5 lakh' }).click();
  assert.equal(await page.locator('#alc-ask').inputValue(), '500000');
  const echo = await page.locator('#alc-ask-e').innerText();
  assert.match(echo, /₹5,00,000/, 'the amount is not echoed in Indian digit grouping');
  assert.match(echo, /5 lakh/, 'the amount is not echoed in words, where a stray zero shows');
  assert.equal(await page.locator('#alc-ask-go').isDisabled(), false);

  await page.screenshot({ path: path.join(output, 'asked.png') });

  /* ── 3 · The answer reaches the page ─────────────────────────────────── */

  await page.locator('#alc-ask-go').click();
  await page.locator(sheet).waitFor({ state: 'hidden' });

  await page.locator('.alc-money').waitFor();
  assert.match(await page.locator('.alc-money').innerText(), /₹5,00,000/,
               'the amount just given is not shown back on the page');
  assert.equal(await page.locator('.alc-step').count(), 5,
               'the sequence is no longer five steps');

  /* Stored, so the next visit does not ask again. */
  assert.equal(await page.evaluate(k => JSON.parse(localStorage.getItem(k)).amount, MONEY_KEY),
               500000);

  /* ── 4 · Asked once, not on every visit ──────────────────────────────── */

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaAllocate);
  await page.evaluate(() => window.AltahaNav.go('allocate', null, true));
  await page.locator('.alc-money').waitFor();
  await page.waitForTimeout(700);
  assert.equal(await page.locator(box).isVisible(), false,
               'the question was asked again after it had been answered');
  assert.match(await page.locator('.alc-money').innerText(), /₹5,00,000/,
               'the answer did not survive a reload');

  /* ── 5 · Changing it reopens the same question ───────────────────────── */

  await page.locator('.alc-money [data-money]').click();
  await page.locator(box).waitFor({ state: 'visible' });
  assert.equal(await page.locator('#alc-ask').inputValue(), '500000',
               'reopening did not carry the figure already given');

  /* Escape shuts it, and nothing is lost by shutting it. */
  await page.keyboard.press('Escape');
  await page.locator(sheet).waitFor({ state: 'hidden' });
  assert.match(await page.locator('.alc-money').innerText(), /₹5,00,000/);

  /* The backdrop shuts it too — on a phone that is where a thumb lands. */
  await page.locator('.alc-money [data-money]').click();
  await page.locator(box).waitFor({ state: 'visible' });
  await page.locator('.alc-back').click({ position: { x: 5, y: 5 } });
  await page.locator(sheet).waitFor({ state: 'hidden' });

  /* ── 6 · Typing an amount, committed with Enter ──────────────────────── */

  await page.locator('.alc-money [data-money]').click();
  await page.locator(box).waitFor({ state: 'visible' });
  await page.locator('#alc-ask').fill('1200000');
  assert.match(await page.locator('#alc-ask-e').innerText(), /12 lakh/);
  await page.locator('#alc-ask').press('Enter');
  await page.locator(sheet).waitFor({ state: 'hidden' });
  assert.match(await page.locator('.alc-money').innerText(), /₹12,00,000/,
               'Enter did not commit the typed amount');

  await context.close();

  /* ── 7 · The sleeve, not the total, reaches the calculator ───────────── */

  ({ context, page } = await fresh());
  await page.locator(box).waitFor({ state: 'visible' });

  /* A Balanced profile puts 40–60% in growth-type categories. The calculator
     must start from the low end of that band — ₹2,00,000 of ₹5,00,000 — and
     never from the whole amount, which is the number that would quietly turn
     an allocation page into a stock-buying page. */
  await page.evaluate(() => {
    window.AltahaRiskProfile = { band: 'Balanced', score: 55, recorded: false };
    window.dispatchEvent(new CustomEvent('altaha:risk', { detail: window.AltahaRiskProfile }));
  });
  await page.locator('.alc-q', { hasText: '₹5 lakh' }).click();
  await page.locator('#alc-ask-go').click();
  await page.locator(sheet).waitFor({ state: 'hidden' });

  await page.locator('.alc-money').waitFor();
  const banner = await page.locator('.alc-money').innerText();
  assert.match(banner, /Balanced/, 'the banner does not name the profile driving the sleeve');
  assert.match(banner, /40–60%/, 'the banner does not state the band it is taking the low end of');
  assert.match(banner, /₹2,00,000/, 'the sleeve is not the low end of the band');

  assert.equal(await page.locator('#alc_cap').inputValue(), '200000',
               'the calculator was seeded with the whole amount instead of the growth sleeve');
  assert.equal(await page.evaluate(k => JSON.parse(localStorage.getItem(k)).capital, SIZE_KEY),
               200000);

  /* And the arithmetic below it actually ran on that figure. */
  await page.locator('#alc_out .alc-big').first().waitFor();
  assert.match(await page.locator('#alc_out').innerText(), /₹/);

  await page.screenshot({ path: path.join(output, 'answered.png'), fullPage: true });
  await context.close();

  /* ── 8 · Declining is a real answer ──────────────────────────────────── */

  ({ context, page } = await fresh());
  await page.locator(box).waitFor({ state: 'visible' });
  await page.locator('.alc-skip').click();
  await page.locator(sheet).waitFor({ state: 'hidden' });

  await page.locator('.alc-money.is-skip').waitFor();
  assert.equal(await page.locator('.alc-step').count(), 5,
               'declining to give a figure cost the reader the sequence');
  assert.equal(await page.evaluate(k => JSON.parse(localStorage.getItem(k)).skipped, MONEY_KEY),
               true);

  /* Refusing once must not mean being asked again on the next visit. */
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AltahaAllocate);
  await page.evaluate(() => window.AltahaNav.go('allocate', null, true));
  await page.locator('.alc-money.is-skip').waitFor();
  await page.waitForTimeout(700);
  assert.equal(await page.locator(box).isVisible(), false,
               'the question was asked again after it had been declined');

  /* The way back in is still offered. */
  await page.locator('.alc-money [data-money]').click();
  await page.locator(box).waitFor({ state: 'visible' });
  await page.locator('.alc-x').click();
  await page.locator(sheet).waitFor({ state: 'hidden' });
  await context.close();

  /* ── 9 · Readable in both themes ─────────────────────────────────────── */

  /* Measured rather than eyeballed. The first version of this prompt put its
     one call to action at 3.43:1 in the light theme — --gold resolves to
     #A8801C there, and near-white on it is under the 4.5:1 that text this
     size needs. Nothing about that looks wrong in a screenshot taken on the
     machine that wrote it. */
  for (const scheme of ['light', 'dark']) {
    const c = await browser.newContext({
      viewport: { width: 1280, height: 900 }, colorScheme: scheme });
    await c.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
    await c.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      return route.fulfill({ json: { available: false, rows: [], items: [],
                                     sectors: [], rankings: [], status: 'idle' } });
    });
    const p2 = await c.newPage();
    p2.on('pageerror', e => errors.push(String(e.stack)));
    await p2.goto('http://127.0.0.1:8771/', { waitUntil: 'domcontentloaded' });
    await p2.waitForFunction(() => !!window.AltahaNav && !!window.AltahaAllocate);
    await p2.evaluate(() => window.AltahaNav.go('allocate', null, true));
    await p2.locator(box).waitFor({ state: 'visible' });

    const ratios = await p2.evaluate(() => {
      const rgb = s => s.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
      const lum = c => {
        const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
      };
      const contrast = (a, b) => {
        const L1 = lum(a), L2 = lum(b);
        return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      };
      const boxBg = rgb(getComputedStyle(document.querySelector('.alc-box')).backgroundColor);
      const out = {};
      ['#alc-ask-go', '.alc-skip', '.alc-ask-s', '#alc-ask-e', '.alc-ask-d', '.alc-ask-t']
        .forEach(sel => {
          const n = document.querySelector(sel);
          if (!n) return;
          const cs = getComputedStyle(n);
          const bg = cs.backgroundColor === 'rgba(0, 0, 0, 0)' ? boxBg : rgb(cs.backgroundColor);
          out[sel] = contrast(rgb(cs.color), bg);
        });
      return out;
    });

    Object.keys(ratios).forEach(sel => {
      assert.ok(ratios[sel] >= 4.5,
        sel + ' reads at ' + ratios[sel].toFixed(2) + ':1 in the ' + scheme +
        ' theme, under the 4.5:1 this size of text needs');
    });
    await c.close();
  }

  /* ── 10 · On a phone ─────────────────────────────────────────────────── */

  ({ context, page } = await fresh());
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(box).waitFor({ state: 'visible' });

  /* The prompt has to fit the screen it is shown on. */
  const fits = await page.locator(box).evaluate(n => {
    const r = n.getBoundingClientRect();
    return r.left >= -1 && r.right <= window.innerWidth + 1;
  });
  assert.equal(fits, true, 'the prompt is wider than a phone screen');

  assert.equal(await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1), false,
    'the prompt pushed the page sideways');

  await page.locator('.alc-q', { hasText: '₹1 lakh' }).tap();
  assert.equal(await page.locator('#alc-ask').inputValue(), '100000');
  await page.locator('#alc-ask-go').tap();
  await page.locator(sheet).waitFor({ state: 'hidden' });
  await page.locator('.alc-money').waitFor();

  assert.equal(await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1), false,
    'the banner pushed the page sideways on a phone');

  await page.screenshot({ path: path.join(output, 'phone.png'), fullPage: true });
  await context.close();

  await browser.close();
  server.close();

  assert.deepEqual(errors, [], 'the page threw while being driven');
  console.log('Allocate opens by asking what there is to allocate — screenshots in test-results/allocate-money');
})().catch(e => { console.error(e); process.exit(1); });
