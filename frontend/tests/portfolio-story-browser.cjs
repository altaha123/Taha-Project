/* The portfolio story in a real Chromium, against the synthetic report the
   portfolio workflow builds (backend/tests/portfolio_fixture.py). No live
   calls.

   What this is actually guarding:
     · THE REVIEW OPENS AS A STORY, and the full report stays closed until the
       reader asks — by the bar under the story, the skip link, or the last
       chapter's button — and then opens with its charts drawn.
     · EVERY WAY OF TURNING THE PAGE WORKS: Next, Back, the arrow keys, a
       swipe on a touch screen, and the progress pips.
     · A STAGED UPDATE DOES NOT MOVE THE READER. The report arrives three
       times (cached valuation, prices, complete); a reader on chapter four
       stays on chapter four.
     · MOTION OFF MEANS EVERYTHING IS VISIBLE AT ONCE. With reduced motion,
       no chapter element runs an animation and nothing sits at opacity 0.
     · NO FIGURE LEAVES FOR ANALYTICS. The events carry chapter ids only.
     · phone and desktop, light and dark, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/portfolio-story');
fs.mkdirSync(output, { recursive: true });
const fixtures = path.resolve(process.env.PF_FIXTURES || '/tmp/portfolio-fixtures');
const report = JSON.parse(fs.readFileSync(path.join(fixtures, 'portfolio-12.json')));

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

async function open(browser, port, opts) {
  const context = await browser.newContext(Object.assign({ viewport: { width: 1280, height: 900 } }, opts || {}));
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.pathname === '/portfolio/start') return route.fulfill({ json: { job_id: 'fixture', total: 12 } });
    if (u.pathname === '/portfolio/status') return route.fulfill({ json: { status: 'done', done: 12, total: 12, revision: 1, report } });
    if (u.hostname !== '127.0.0.1') {
      const t = route.request().resourceType();
      if (t === 'script' || t === 'font' || t === 'stylesheet') return route.abort();
      return route.fulfill({ json: { available: false, rows: [], items: [] } });
    }
    return route.continue();
  });
  await page.goto(`http://127.0.0.1:${port}/?go=portfolio`, { waitUntil: 'domcontentloaded' });
  await page.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
  await page.locator('#pf_rows .pf_qty').first().fill('10');
  // Record what would be sent to analytics.
  await page.evaluate(() => { window.__tracked = []; window.AltahaTrack = (n, p) => window.__tracked.push([n, p]); });
  await page.locator('#pf_go').click();
  await page.locator('#pf_story .ps').waitFor();
  return { context, page, errors };
}

const current = page => page.locator('.ps-ch:not([hidden])').getAttribute('data-ch');

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });

  // ── Desktop: the story, turning pages, staged updates, the full report ──
  {
    const { context, page, errors } = await open(browser, port);
    assert.equal(await page.locator('#pf_report').isVisible(), false, 'full report closed');
    assert.equal(await page.locator('#pf_fullbar').isVisible(), true);
    const ids = await page.locator('.ps-ch').evaluateAll(a => a.map(x => x.dataset.ch));
    assert.deepEqual(ids, ['money', 'sectors', 'biggest', 'spread', 'movers', 'score', 'rough', 'news', 'questions', 'recap']);
    assert.equal(await page.locator('.ps-ch:not([hidden])').count(), 1, 'one chapter at a time');
    assert.equal(await current(page), 'money');
    assert.match(await page.locator('.ps-count').innerText(), /Chapter 1 of 10/i);
    assert.equal(await page.locator('.ps-prev').isDisabled(), true);
    assert.match(await page.locator('.ps-ch[data-ch="money"] h3').innerText(), /₹25,00,000/);

    await page.locator('.ps-next').click();
    assert.equal(await current(page), 'sectors');
    await page.locator('.ps').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await current(page), 'biggest');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await current(page), 'sectors');
    await page.locator('.ps-pip').nth(3).click();
    assert.equal(await current(page), 'spread');
    assert.equal(await page.locator('.ps-pip.done').count(), 3);

    // A fresh report for the same portfolio — what every staged update is —
    // goes through the app's own render path and keeps the reader in place.
    // Mark the player, then wait until a re-render has replaced it.
    await page.evaluate(() => { document.querySelector('#pf_story .ps').dataset.old = '1'; });
    await page.locator('#pf_go').click();
    await page.waitForFunction(() => {
      const ps = document.querySelector('#pf_story .ps');
      return ps && !ps.dataset.old;
    }, null, { timeout: 15000 });
    assert.equal(await current(page), 'spread', 'a re-render must not send the reader back to chapter one');

    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(1500);          // let the entrance finish
      await page.screenshot({ path: path.join(output, `1280-${String(i + 1).padStart(2, '0')}.png`) });
      if (await page.locator('.ps-next').isVisible()) await page.locator('.ps-next').click();
    }
    assert.equal(await current(page), 'recap');
    assert.equal(await page.locator('.ps-next').isVisible(), false, 'no Next on the last chapter');

    // Analytics carries chapter ids, never a figure.
    const tracked = await page.evaluate(() => window.__tracked);
    const story = tracked.filter(t => t[0] === 'portfolio_story_viewed');
    assert.ok(story.length >= 10, 'every chapter read is recorded once');
    assert.equal(new Set(story.map(t => t[1].chapter)).size, story.length, 'once per chapter');
    assert.ok(!JSON.stringify(tracked).match(/25,00,000|2500000|HDFCBANK/), 'no figures or holdings in analytics');

    // The last chapter opens the full report, with its charts drawn.
    await page.locator('.ps-ch[data-ch="recap"] [data-ps="full"]').click();
    await page.locator('#pi-money-map').waitFor();
    assert.equal(await page.locator('#pf_full').getAttribute('aria-expanded'), 'true');
    assert.ok((await page.evaluate(() => window.__tracked)).some(t => t[0] === 'portfolio_full_report_opened' && t[1].from === 'story_end'));
    await page.getByRole('button', { name: 'Advanced analysis', exact: true }).click();
    await page.waitForFunction(() => window.Chart && Object.keys(Chart.instances).length === 7);
    const blank = await page.evaluate(() => [...document.querySelectorAll('#pf_report canvas')]
      .filter(c => !c.getContext('2d').getImageData(0, 0, c.width, c.height).data.some(v => v !== 0)).map(c => c.id));
    assert.deepEqual(blank, [], 'charts drawn after the report opens');
    // And it closes again.
    await page.locator('#pf_full').click();
    assert.equal(await page.locator('#pf_report').isVisible(), false);
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  // ── Phone: swipe, skip link, no sideways scroll, dark theme ─────────────
  {
    const { context, page, errors } = await open(browser, port,
      { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => document.documentElement.dataset.theme = t, theme);
      for (let i = 0; i < 10; i++) {
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        assert.ok(overflow <= 1, `${theme} chapter ${i + 1}: page scrolls sideways by ${overflow}px`);
        if (theme === 'light') {
          await page.waitForTimeout(1500);
          await page.locator('#pf_story').screenshot({ path: path.join(output, `390-${String(i + 1).padStart(2, '0')}.png`) });
        }
        if (await page.locator('.ps-next').isVisible()) await page.locator('.ps-next').click();
      }
      await page.locator('.ps-pip').first().click();
    }
    // A horizontal swipe turns the page.
    const box = await page.locator('.ps-stage').boundingBox();
    const y = box.y + Math.min(120, box.height / 2);
    await page.locator('.ps-stage').dispatchEvent('pointerdown', { pointerType: 'touch', clientX: box.x + 300, clientY: y });
    await page.locator('.ps-stage').dispatchEvent('pointerup', { pointerType: 'touch', clientX: box.x + 60, clientY: y + 8 });
    assert.equal(await current(page), 'sectors', 'swipe left turns to the next chapter');
    // The skip link opens the full report from anywhere.
    await page.locator('.ps-skip').click();
    await page.locator('#pi-money-map').waitFor();
    assert.ok((await page.evaluate(() => window.__tracked)).some(t => t[0] === 'portfolio_full_report_opened' && t[1].from === 'story_skip'));
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  // ── Motion off: every chapter complete at once ──────────────────────────
  {
    const { context, page, errors } = await open(browser, port, { reducedMotion: 'reduce' });
    for (let i = 0; i < 10; i++) {
      const hidden = await page.evaluate(() => {
        const ch = document.querySelector('.ps-ch:not([hidden])');
        const bad = [];
        ch.querySelectorAll('*').forEach(el => {
          const cs = getComputedStyle(el);
          if (cs.animationName !== 'none') bad.push(el.className + ': animates');
          if (el.textContent.trim() && Number(cs.opacity) < 0.99) bad.push(el.className + ': opacity ' + cs.opacity);
        });
        return bad;
      });
      assert.deepEqual(hidden, [], `chapter ${i + 1} with motion off`);
      if (await page.locator('.ps-next').isVisible()) await page.locator('.ps-next').click();
    }
    assert.deepEqual(errors.filter(e => /portfolio/.test(e)), []);
    await context.close();
  }

  await browser.close();
  server.close();
  console.log('portfolio story browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
