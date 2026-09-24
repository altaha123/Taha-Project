/* Smart AI on the stock page, in a real Chromium: a floating button that
   opens a panel over the page and explains the score in plain English. The /explain
   responses are shaped exactly as backend/score_explain.py returns them; no
   live calls, and no model.

   What this is actually guarding:
     · NOTHING IS REQUESTED UNTIL THE READER ASKS. Every fresh explanation
       spends part of a small free daily allowance, and most visitors never
       open the Scores pane.
     · THE WORDS ARE LABELLED AS AI-WRITTEN, with the disclaimer, every time.
       An explanation that could be mistaken for the site's own analysis is
       the failure this section exists to avoid.
     · MODEL TEXT IS TEXT. Whatever the model returns is escaped, never
       rendered as markup.
     · EVERY REFUSAL READS AS A SENTENCE. Switched off, out of allowance,
       busy — each shows the server's message, and only the transient ones
       offer "Try again".
     · A STORED EXPLANATION WRITTEN AGAINST AN OLDER SCORE SAYS SO.
     · AN UNSCORED STOCK SHOWS NO BUTTON. There is nothing to explain.
     · THE BUTTON FLOATS WHEREVER THE READER IS, and on a phone it sits above
       the bottom product bar, never on top of it.
     · THE PANEL CLOSES with its close button and with Escape, and reopening
       it shows the same answer without asking the server again.
     · phone through desktop, both themes, no horizontal page scroll. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/explain');
fs.mkdirSync(output, { recursive: true });

const analyze = (score) => ({
  ticker: 'RELIANCE', name: 'Reliance Industries Limited', currency: 'INR', price: 1402.5,
  scoring: { score: score, label: 'CONSTRUCTIVE', horizon: 'position', horizon_label: 'Position',
             pillars: { quality: 71, value: 39 }, checks: [] },
  profile: { sector: 'Energy' },
  disclaimer: 'Educational tool.'
});

const written = {
  available: true, cached: false, model: 'openai/gpt-oss-120b', provider: 'Groq',
  score: 68, horizon: 'position', generated_at: '2026-09-24T10:15+05:30',
  paragraphs: [
    'Reliance scores 68 out of 100, labelled CONSTRUCTIVE: better than average on most measures.',
    'Its ROCE (profit on the money invested in the business) of 18% lifts the score; a P/E dearer than 70% of peers holds it back. <img src=x onerror="window.__xss=1">',
    'Two factors were missing, so confidence is 74%. This explains the score; it is not a recommendation.'
  ],
  disclaimer: 'Written by an AI model (openai/gpt-oss-120b, via Groq) from the numbers on this page. It is an explanation of the score, not advice, and it can be wrong — check anything that matters against the ledger below.'
};
const off = { available: false, reason: 'not_configured',
              message: 'Plain-English explanations are not switched on on this instance.' };
const busy = { available: false, reason: 'busy',
               message: 'The free explanation service is at its limit right now. Try again in a few minutes.' };

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

(async () => {
  await new Promise(r => server.listen(8783, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];
  const asked = [];
  let score = 68, replies = [written];

  async function open(viewport, theme) {
    const context = await browser.newContext({ viewport });
    await context.addInitScript(t => { try { localStorage.setItem('altaha-theme', t); } catch (e) {} }, theme);
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      if (['font', 'image'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/explain') {
        asked.push(u.search);
        return route.fulfill({ json: replies.length > 1 ? replies.shift() : replies[0] });
      }
      if (u.pathname === '/analyze') return route.fulfill({ json: analyze(score) });
      return route.fulfill({ json: { available: false, rows: [], items: [] } });
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack)));
    await page.goto('http://127.0.0.1:8783/stock.html?ticker=RELIANCE', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => !document.getElementById('body').hidden);
    return { context, page };
  }

  // Open the panel and ask the one question.
  async function ask(page) {
    await page.locator('#sai-fab').click();
    await page.locator('#sai-q').click();
  }

  // ── Floating, lazy, labelled, escaped ────────────────────────────────────
  let { context, page } = await open({ width: 1280, height: 1000 }, 'light');
  const fab = page.locator('#sai-fab');
  await fab.waitFor();
  assert.match(await fab.innerText(), /Smart AI/);
  assert.equal(await fab.getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#sai-panel').isHidden(), true, 'the panel starts closed');
  assert.equal(await page.locator('#sai').evaluate(n => getComputedStyle(n).position), 'fixed');
  // Still on screen after scrolling to the bottom of the page.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const box = await fab.boundingBox();
  assert.ok(box && box.y + box.height <= 1000 && box.x + box.width <= 1280, 'button must stay on screen');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, 'desktop-closed.png') });

  await fab.click();
  assert.equal(await fab.getAttribute('aria-expanded'), 'true');
  const q = page.locator('#sai-q');
  assert.match(await q.innerText(), /What does this score mean, in simple words\?/);
  assert.match(await page.locator('.sai-hi').innerText(), /Reliance Industries Limited/);
  assert.deepEqual(asked, [], 'nothing may be requested before the reader asks');
  await page.waitForTimeout(300);   // let the panel's fade-in finish
  await page.screenshot({ path: path.join(output, 'desktop-offer.png') });

  await q.click();
  await page.locator('.sai-ans').waitFor();
  assert.deepEqual(asked, ['?ticker=RELIANCE&horizon=position']);
  assert.match(await page.locator('.sai-you').innerText(), /in simple words/, 'the question stays on screen');
  assert.equal(await page.locator('.sai-ans p').count(), 3);
  const meta = await page.locator('.sai-meta').innerText();
  assert.match(meta, /AI-written/i);
  assert.match(meta, /not advice/);
  assert.match(meta, /10:15 am IST/i, 'the time is shown in IST whatever the browser clock');
  assert.doesNotMatch(meta, /written when the score was/, 'no drift note when the score matches');
  assert.match(await page.locator('.sai-ans').innerText(), /<img src=x/,
    'model output must render as text');
  assert.equal(await page.locator('.sai-ans img').count(), 0);
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  await page.screenshot({ path: path.join(output, 'desktop-answer.png') });

  // Close with Escape, reopen: same answer, no second request.
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sai-panel').isHidden(), true);
  await fab.click();
  await page.locator('.sai-ans').waitFor();
  assert.equal(asked.length, 1, 'reopening must not ask the server again');
  await page.locator('#sai-x').click();
  assert.equal(await page.locator('#sai-panel').isHidden(), true);
  await context.close();

  // ── Dark theme, phone width, above the bottom product bar ────────────────
  ({ context, page } = await open({ width: 390, height: 844 }, 'dark'));
  await page.screenshot({ path: path.join(output, 'phone-dark-closed.png') });
  // The dark theme's gold is light; the label on it must be dark ink.
  const ink = await page.locator('#sai-fab').evaluate(n => getComputedStyle(n).color);
  assert.equal(ink, 'rgb(23, 20, 14)', 'the dark-theme button needs dark text to be readable');
  const bar = await page.locator('.ux-bottom').boundingBox();
  const fabBox = await page.locator('#sai-fab').boundingBox();
  if (bar) assert.ok(fabBox.y + fabBox.height <= bar.y, 'the button must sit above the bottom bar');
  await ask(page);
  await page.locator('.sai-ans').waitFor();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 0, `page scrolls sideways by ${overflow}px on a phone`);
  const panelBox = await page.locator('#sai-panel').boundingBox();
  assert.ok(panelBox.x >= 0 && panelBox.x + panelBox.width <= 390, 'the panel must fit the phone');
  const [fg, bg] = await page.locator('.sai-ans p').first().evaluate(n => [
    getComputedStyle(n).color, getComputedStyle(document.getElementById('sai-panel')).backgroundColor]);
  assert.notEqual(fg, bg, 'text must be visible against its panel in dark mode');
  await page.screenshot({ path: path.join(output, 'phone-dark-answer.png') });
  await context.close();

  // ── A stored copy written against an older score says so ────────────────
  score = 71;
  ({ context, page } = await open({ width: 1280, height: 1000 }, 'light'));
  await ask(page);
  await page.locator('.sai-ans').waitFor();
  assert.match(await page.locator('.sai-meta').innerText(), /written when the score was 68/);
  await context.close();
  score = 68;

  // ── Switched off: the message, and no retry ──────────────────────────────
  replies = [off];
  ({ context, page } = await open({ width: 1280, height: 1000 }, 'light'));
  await ask(page);
  await page.locator('.sai-note').waitFor();
  assert.match(await page.locator('#sai-body').innerText(), /not switched on/);
  assert.equal(await page.locator('#sai-q').count(), 0, 'nothing to retry when switched off');
  await context.close();

  // ── Busy: the message, a retry, and the retry asks again ─────────────────
  replies = [busy, written];
  const before = asked.length;
  ({ context, page } = await open({ width: 1280, height: 1000 }, 'light'));
  await ask(page);
  await page.locator('.sai-note').waitFor();
  assert.match(await page.locator('#sai-body').innerText(), /at its limit/);
  await page.locator('#sai-q').click();
  await page.locator('.sai-ans').waitFor();
  assert.equal(asked.length - before, 2);
  await context.close();

  // ── No score, no button ──────────────────────────────────────────────────
  score = null;
  ({ context, page } = await open({ width: 1280, height: 1000 }, 'light'));
  assert.equal(await page.locator('#sai').isHidden(), true);
  await context.close();

  await browser.close();
  server.close();
  assert.deepEqual(errors, [], 'page errors:\n' + errors.join('\n'));
  console.log('smart AI: floating, lazy, labelled, escaped, refusals readable, both themes, phone width');
})().catch(e => { console.error(e); process.exit(1); });
