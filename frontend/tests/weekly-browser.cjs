/* The weekly brief in a real Chromium. The responses are the real module's
   own (backend/tests/make_weekly_fixture.py). No live calls.

   What this is actually guarding:
     · THE WEEK IN BRIEF LEADS, and every section that has something to say
       is drawn: the market, money flow, the rules that matter, the forum.
     · A SESSION NEVER RECORDED READS AS "not recorded", never as zero.
     · A PAST ISSUE OPENS FROM ITS ADDRESS (?w=2026-W47) and from the picker.
     · TOPICS ARE TEXT. The owner's paragraphs and "- " lists are drawn as
       paragraphs and lists; nothing in them is read as markup.
     · THE EDITOR IS THE OWNER'S: hidden without the admin key; with it, a
       refused topic shows the sentence that was refused.
     · An empty week says so, and offers the forum and "Suggest a topic".
     · phone width, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/weekly');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/weekly-brief.json'), 'utf8'));

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  const file = path.join(root, p === '/' ? '/index.html' : p);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/html; charset=utf-8');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

async function open(browser, opts) {
  opts = opts || {};
  const context = await browser.newContext({ viewport: opts.viewport || { width: 1280, height: 900 } });
  const asked = [], posted = [];
  if (opts.admin) await context.addInitScript(() => localStorage.setItem('altaha-admin-key', 'k'));
  await context.route('**/*', route => {
    const req = route.request(), u = new URL(req.url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') return route.fulfill({ body: '', contentType: 'text/plain' });
    asked.push(u.pathname + u.search);
    if (u.pathname === '/weekly/issues') return route.fulfill({ json: fx.issues });
    if (u.pathname === '/weekly') {
      const w = u.searchParams.get('week');
      return route.fulfill({ json: w === fx.published.week ? fx.published : fx.draft });
    }
    if (u.pathname === '/admin/weekly/topics') {
      posted.push({ body: JSON.parse(req.postData() || '{}'), key: req.headers()['x-admin-key'] });
      return route.fulfill({ status: 422, json: { detail: { rule: 'tip', sentence: 'Buy HDFC Bank at 1650.',
        message: 'The brief gives no prices to buy or sell at, targets or stop-loss levels. Rephrase the sentence below.' } } });
    }
    return route.fulfill({ status: 404, json: { detail: 'none' } });
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.goto(server.base + '/weekly.html' + (opts.query || ''), { waitUntil: 'load' });
  return { context, page, errors, asked, posted };
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  server.base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // ── A published issue, opened from its address ──────────────────────────
    {
      const t = await open(browser, { query: '?w=2026-W47&from=email' });
      const { page } = t;
      await page.locator('.wk-lead p').first().waitFor();
      assert.match(await page.locator('#wk-when').innerText(), /16–22 Nov 2026\s*Published/i);
      assert.equal(await page.locator('#wk-weeks').inputValue(), '2026-W47');
      assert.deepEqual(await page.locator('.wk-lead p').allInnerTexts(), fx.published.summary);
      assert.deepEqual(await page.locator('.wk-sec > h2').allInnerTexts(),
        ['This week’s topics', 'The market', 'Money flow', 'New rules that matter', 'On the forum']);
      // The owner's topic: paragraphs, a list, a link, and no editor without the key.
      const topic = page.locator('.wk-topic').first();
      assert.equal(await topic.locator('h3').innerText(), 'What the budget could change for banks');
      assert.equal(await topic.locator('li').count(), 3);
      assert.equal(await topic.locator('a[href="https://example.com/budget-notes"]').count(), 1);
      assert.equal(await page.locator('#wk-edit, [data-del]').count(), 0, 'the editor showed without the key');
      // Money flow: Thursday was never recorded, and says so.
      assert.match(await page.locator('.wk-sec', { hasText: 'Money flow' }).innerText(), /Thu\s+not recorded\s+not recorded/);
      assert.match(await page.locator('.wk-sec', { hasText: 'Money flow' }).innerText(), /4 of 5 sessions on record/);
      // The forum: a member's title is text, and links to its discussion.
      const forum = page.locator('.wk-sec', { hasText: 'On the forum' });
      assert.equal(await forum.locator('a', { hasText: 'Bank NIMs <next> quarter' }).getAttribute('href'), 'forum.html#t/9');
      assert.equal(await page.locator('next').count(), 0, 'a title was read as markup');
      assert.match(await page.locator('.wk-sec', { hasText: 'The market' }).innerText(), /NIFTY 50\s+25,250\.00\s+\+1\.00%/);
      await page.screenshot({ path: path.join(output, '1280-published.png'), fullPage: true });
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }

    // ── This week so far, with nothing yet; then the picker ─────────────────
    {
      const t = await open(browser);
      const { page } = t;
      await page.locator('.wk-lead').waitFor();
      assert.match(await page.locator('#wk-when').innerText(), /So far/i);
      assert.match(await page.locator('.wk-lead').innerText(), /Nothing recorded for this week yet/);
      assert.match(await page.locator('body').innerText(), /Nobody posted on the forum this week/);
      assert.equal(await page.locator('a[href="forum.html#new/c/altaha"]').count(), 1, 'no way to suggest a topic');
      // With no topics, the invitation waits at the end.
      const heads = await page.locator('.wk-sec > h2').allInnerTexts();
      assert.equal(heads[heads.length - 1], 'This week’s topics');
      await page.locator('#wk-weeks').selectOption('2026-W47');
      await page.locator('.wk-topic').waitFor();
      assert.ok(t.asked.includes('/weekly?week=2026-W47'));
      assert.match(page.url(), /\?w=2026-W47$/);
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }

    // ── The owner adds a topic, and a refused one says which sentence ───────
    {
      const t = await open(browser, { admin: true, query: '?w=2026-W47' });
      const { page } = t;
      await page.locator('#wk-edit').waitFor();
      assert.equal(await page.locator('[data-del]').count(), 1);
      await page.locator('#wk-e-title').fill('Banks into results');
      await page.locator('#wk-e-body').fill('Loan growth is steady. Buy HDFC Bank at 1650.');
      await page.locator('#wk-edit button[type=submit]').click();
      await page.locator('#wk-e-msg.is-err blockquote').waitFor();
      assert.equal(await page.locator('#wk-e-msg blockquote').innerText(), 'Buy HDFC Bank at 1650.');
      assert.deepEqual(t.posted[0], { key: 'k', body: { week: '2026-W47', action: 'add', title: 'Banks into results',
        body: 'Loan growth is steady. Buy HDFC Bank at 1650.', symbols: '' } });
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }

    // ── A phone ─────────────────────────────────────────────────────────────
    {
      const t = await open(browser, { query: '?w=2026-W47', viewport: { width: 390, height: 844 } });
      await t.page.locator('.wk-topic').waitFor();
      assert.ok(await t.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'the brief scrolls sideways on a phone');
      await t.page.screenshot({ path: path.join(output, '390-published.png'), fullPage: true });
      assert.deepEqual(t.errors, []);
      await t.context.close();
    }
    console.log('weekly brief browser checks passed');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
