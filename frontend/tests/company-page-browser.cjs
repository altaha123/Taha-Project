/* Company pages, in a real Chromium: /stock-SYMBOL and /stocks.
   Run from the repository root: node frontend/tests/company-page-browser.cjs

   The pages are printed by the real renderer against the real stock.html
   (backend/tests/company_pages_fixture.py), so this fails when either
   changes shape. No live calls: the API is answered here.

   What this is actually guarding:
     · THE PAGE IS A COMPANY WITH SCRIPTS OFF. That is how a search engine
       first reads it. The name, the price, the filed figures and the links to
       its neighbours must all be showing, and nothing may be a skeleton.
     · THE SAME PAGE STILL WORKS WITH SCRIPTS ON. /stock-ACME has no ?ticker=,
       and the page's scripts used to read the company from there. Each must
       find it in the address, or the page is a shell around a loading message.
     · THE TITLE AND CANONICAL THE SERVER SENT ARE THE ONES THAT STAY.
       stock.js used to write its own title once the data arrived.
     · THE STATIC PAGE IS UNCHANGED. stock.html?ticker=ACME must work exactly
       as it did, with no empty at-a-glance section and no dashed empty box
       where the disclaimer now sits outside the hidden body.
     · THE DIRECTORY IS A PAGE OF THE SITE: header, footer, every company a
       link, a filter that only hides. */

const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/company-pages');
fs.mkdirSync(output, { recursive: true });

const made = spawnSync('python3', ['backend/tests/company_pages_fixture.py'],
                       { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
assert.equal(made.status, 0, 'the renderer failed:\n' + made.stderr);
const pages = JSON.parse(made.stdout);

const analyze = {
  ticker: 'ACME.NS', name: 'Acme Chemicals Ltd', exchange: 'NSE', currency: 'INR', price: 815.0,
  ratios: { market_cap: 125000000000, price: 815.0, high_52w: 990, low_52w: 610, pe: 24.1,
            book_value: 168.2, dividend_yield: 0.62, roce: 28.4, roe: 21.2, debt_to_equity: 0.12 },
  peers: {}, technical: { score: 58, checks: [] }, fundamental: { score: 75, checks: [] },
  profile: { sector: 'Chemicals', industry: 'Specialty Chemicals' },
  scoring: { score: 61.4, label: 'STRONG', confidence: 71.5, horizon: 'position',
             horizon_label: 'Weeks to months', model: { name: 'Compounder' },
             basis: 'Altaha Score v4', summary: 'Strongest on business quality.',
             pillars: { quality: 68, momentum: 52 } },
  altaha_score_v4: { methodology_version: 'v4' },
  disclaimer: 'Educational tool. Scores and evidence only.'
};

const types = { '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.ico': 'image/x-icon' };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  const html = (body, code) => { res.writeHead(code || 200, { 'Content-Type': types['.html'] }); res.end(body); };
  if (p === '/stock-ACME') return html(pages.company);
  if (p === '/stock-PLAIN') return html(pages.plain);
  if (p === '/stock-NOSUCH') return html(pages.missing, 404);
  if (p === '/stocks') return html(pages.directory);
  const file = path.join(root, p === '/' ? '/index.html' : p);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

async function open(browser, port, url, opts) {
  const context = await browser.newContext(Object.assign({ viewport: { width: 1280, height: 1000 } }, opts));
  const page = await context.newPage(), errors = [], asked = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) return route.abort();
    asked.push(u.pathname + u.search);
    if (u.pathname === '/analyze') return route.fulfill({ json: analyze });
    if (u.pathname === '/chart') {
      return route.fulfill({ json: { currency: 'INR', day_change_pct: 0.31,
        candles: [790, 801, 797, 812, 815].map((v, i) => ['2026-09-1' + i, v, v, v, v, 1000]) } });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [], results: [] } });
  });
  const resp = await page.goto(`http://127.0.0.1:${port}${url}`, { waitUntil: 'domcontentloaded' });
  return { context, page, errors, asked, resp };
}

const fits = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    /* ── 1. Scripts off: what a crawler is sent ─────────────────────────── */
    for (const width of [1280, 390]) {
      const t = await open(browser, port, '/stock-ACME',
                           { javaScriptEnabled: false, viewport: { width, height: 900 } });
      assert.equal(await t.page.title(),
        'Acme Chemicals Ltd (ACME) share price, score and fundamentals | Altaha Screener');
      assert.equal((await t.page.locator('h1#nm').innerText()).trim(), 'Acme Chemicals Ltd');
      assert.equal(await t.page.locator('h1#nm .skel').count(), 0, 'the name is still a skeleton');
      assert.match(await t.page.locator('#px').innerText(), /₹812\.50/);
      assert.deepEqual(await t.page.locator('#tags .stk-tag').allInnerTexts(),
                       ['NSE', 'ACME', 'Chemicals', 'Specialty Chemicals']);
      const glance = t.page.locator('#glance');
      assert.ok(await glance.isVisible(), 'the figures are not showing with scripts off');
      assert.match(await glance.innerText(), /is listed on the National Stock Exchange of India/);
      assert.equal(await glance.locator('.gl-table tbody tr').count(), 4);
      assert.equal(await glance.locator('.gl-peers a').count(), 12);
      assert.equal(await glance.locator('.gl-peers a').first().getAttribute('href'), '/stock-CHEM14');
      assert.ok(await glance.locator('.gl-facts > div').count() >= 12);
      assert.ok(!(await t.page.locator('#body').isVisible()), 'the empty panes are showing');
      assert.ok(!(await t.page.locator('#disc').isVisible()), 'an empty disclaimer box is showing');
      assert.ok(await fits(t.page), 'the page scrolls sideways at ' + width);
      await t.page.screenshot({ path: path.join(output, `no-js-${width}.png`), fullPage: true });
      await t.context.close();
    }

    /* ── 2. Scripts on: the same address is the working stock page ──────── */
    {
      const t = await open(browser, port, '/stock-ACME');
      await t.page.locator('#kgrid .ktile').first().waitFor();
      assert.ok(t.asked.some(u => u === '/analyze?ticker=ACME'),
                'stock.js did not find the company in the address: ' + t.asked.join(' '));
      assert.equal(await t.page.title(),
        'Acme Chemicals Ltd (ACME) share price, score and fundamentals | Altaha Screener',
        'stock.js replaced the title the server sent');
      const canon = await t.page.locator('link[rel="canonical"]').evaluateAll(a => a.map(l => l.getAttribute('href')));
      assert.deepEqual(canon, ['https://altahascreener.in/stock-ACME']);
      assert.match(await t.page.locator('#px').innerText(), /₹815\.00/, 'the live price did not replace the last close');
      assert.equal((await t.page.locator('h1#nm').innerText()).trim(), 'Acme Chemicals Ltd');
      assert.match(await t.page.locator('#stk-lab-link').getAttribute('href'), /lab=ACME/);
      assert.equal(await t.page.locator('.stk-id .ux-save, .stk-id button').count() >= 1, true,
                   'experience.js did not add the Save button');
      // The section stays, under the panes and above the disclaimer.
      const order = await t.page.evaluate(() => {
        const y = id => document.getElementById(id).getBoundingClientRect().top + scrollY;
        return [y('panes'), y('glance'), y('disc')];
      });
      assert.ok(order[0] < order[1] && order[1] < order[2], 'panes, at a glance, disclaimer: ' + order);
      assert.match(await t.page.locator('#disc').innerText(), /Educational tool/);
      await t.page.locator('[data-p="chart"]').click();
      await t.page.locator('.sc-insights').waitFor();
      assert.equal(await t.page.locator('footer.sh-footer').count(), 1);
      assert.equal(await t.page.locator('footer.sh-footer a', { hasText: 'All companies' }).getAttribute('href'), '/stocks');
      assert.ok(await fits(t.page));
      await t.page.screenshot({ path: path.join(output, 'live-1280.png'), fullPage: true });
      await t.page.setViewportSize({ width: 390, height: 844 });
      await t.page.waitForTimeout(150);
      assert.ok(await fits(t.page), 'the live page scrolls sideways on a phone');
      await t.page.locator('#glance').scrollIntoViewIfNeeded();
      await t.page.screenshot({ path: path.join(output, 'live-390-glance.png') });
      await t.page.emulateMedia({ colorScheme: 'dark' });
      await t.page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
      await t.page.screenshot({ path: path.join(output, 'live-390-glance-dark.png') });
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 3. The static page is as it was ────────────────────────────────── */
    {
      const t = await open(browser, port, '/stock.html?ticker=ACME');
      await t.page.locator('#kgrid .ktile').first().waitFor();
      assert.equal(await t.page.title(), 'ACME — Acme Chemicals Ltd | Altaha Screener');
      assert.equal(await t.page.locator('#glance').count(), 0, 'an empty section was left in the static page');
      assert.equal(await t.page.locator('link[rel="canonical"]').count(), 0,
                   'a canonical was added off the live site, where /stock-ACME does not exist');
      assert.match(await t.page.locator('#disc').innerText(), /Educational tool/);
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();

      // Before the data arrives the disclaimer has no words, and must take no room.
      const slow = await browser.newContext({ javaScriptEnabled: false });
      const p = await slow.newPage();
      await p.goto(`http://127.0.0.1:${port}/stock.html?ticker=ACME`);
      assert.ok(!(await p.locator('#disc').isVisible()), 'an empty dashed box sits on the static page');
      await slow.close();
    }

    /* ── 3b. On the live site, the static page points at the company page ─
       Both addresses show the same company, and only /stock-ACME has the
       figures in its HTML. The canonical is added by stock.js, and only on
       the live host, so it is opened here under that name with every file
       answered from disk. */
    {
      const context = await browser.newContext();
      const page = await context.newPage();
      await context.route('**/*', route => {
        const u = new URL(route.request().url());
        if (u.hostname !== 'altahascreener.in') {
          if (u.pathname === '/analyze') return route.fulfill({ json: analyze });
          if (/fonts\./.test(u.hostname)) return route.abort();
          return route.fulfill({ json: { available: false, rows: [], items: [], results: [] } });
        }
        const file = path.join(root, decodeURIComponent(u.pathname));
        try {
          return route.fulfill({ body: fs.readFileSync(file),
                                 contentType: types[path.extname(file)] || 'application/octet-stream' });
        } catch (_) { return route.fulfill({ status: 404, body: '' }); }
      });
      await page.goto('http://altahascreener.in/stock.html?ticker=ACME', { waitUntil: 'domcontentloaded' });
      await page.locator('#kgrid .ktile').first().waitFor();
      assert.deepEqual(
        await page.locator('link[rel="canonical"]').evaluateAll(a => a.map(l => l.href)),
        ['http://altahascreener.in/stock-ACME']);
      await context.close();
    }

    /* ── 4. Without the template: figures and a way through ─────────────── */
    {
      const t = await open(browser, port, '/stock-PLAIN');
      await t.page.locator('footer.sh-footer').waitFor();
      assert.equal((await t.page.locator('h1').innerText()).trim(), 'Acme Chemicals Ltd');
      assert.equal(await t.page.locator('.gl-open a').getAttribute('href'), '/stock?ticker=ACME');
      assert.ok(await t.page.locator('#glance').isVisible());
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();
    }

    /* ── 5. Every company, A to Z ───────────────────────────────────────── */
    {
      const t = await open(browser, port, '/stocks');
      await t.page.locator('footer.sh-footer').waitFor();
      assert.equal(await t.page.locator('#sh-q').count(), 1, 'the site header and its search box did not mount');
      assert.equal(await t.page.locator('.dir-list a').count(), 18);
      assert.equal(await t.page.locator('.dir-list a', { hasText: 'Gamma & Sons Ltd' }).getAttribute('href'), '/stock-G%26S');
      await t.page.locator('#dir-q').fill('gamma');
      assert.equal(await t.page.locator('.dir-list li:visible').count(), 1);
      assert.equal(await t.page.locator('.dir-group:visible').count(), 1);
      await t.page.locator('#dir-q').fill('CHEM0');
      assert.equal(await t.page.locator('.dir-list li:visible').count(), 9, 'a symbol did not match');
      await t.page.locator('#dir-q').fill('zzz');
      assert.equal(await t.page.locator('.dir-list li:visible').count(), 0);
      assert.ok(await t.page.locator('#dir-none').isVisible());
      await t.page.locator('#dir-q').fill('');
      assert.equal(await t.page.locator('.dir-list li:visible').count(), 18);
      assert.ok(await fits(t.page));
      await t.page.screenshot({ path: path.join(output, 'directory-1280.png'), fullPage: true });
      await t.page.setViewportSize({ width: 390, height: 844 });
      await t.page.waitForTimeout(150);
      assert.ok(await fits(t.page), 'the directory scrolls sideways on a phone');
      await t.page.screenshot({ path: path.join(output, 'directory-390.png') });
      assert.deepEqual(t.errors, [], t.errors.join('\n'));
      await t.context.close();

      const off = await open(browser, port, '/stocks', { javaScriptEnabled: false });
      assert.equal(await off.page.locator('.dir-list a:visible').count(), 18, 'the list needs scripts to show');
      await off.context.close();
    }

    /* ── 6. No such company ─────────────────────────────────────────────── */
    {
      const t = await open(browser, port, '/stock-NOSUCH');
      assert.equal(t.resp.status(), 404);
      assert.match(await t.page.locator('h1').innerText(), /No company page for NOSUCH/);
      assert.equal(await t.page.locator('meta[name="robots"]').getAttribute('content'), 'noindex,follow');
      await t.context.close();
    }

    console.log('company pages ok — screenshots in test-results/company-pages');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
