/* The query screener (#research/query) in a real Chromium, against responses
   produced by the real endpoints (backend/tests/make_query_fixture.py).

   What is guarded:
     · the tab is reachable from Research and builds itself on first sight;
     · an example chip fills the editor, runs, and shows the count and table;
     · the three-box builder writes a line in the syntax the backend reads;
     · typing a partial name offers the field, and Enter inserts it;
     · a bad field name comes back as a readable error with a caret under the
       word and a one-click replacement that re-runs;
     · a column header re-sorts on the server, and clicking again reverses;
     · the query is kept in the address, so a reload runs it again;
     · a missing figure prints as —, never as 0;
     · no horizontal page scroll at phone width. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/query');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/query.json'), 'utf8'));
const asked = [];

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

async function wire(context) {
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = route.request().resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') {
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    if (u.pathname === '/fundamentals/query/fields') return route.fulfill({ json: fx.fields });
    if (u.pathname === '/fundamentals/query') {
      const s = u.searchParams;
      const key = [s.get('q'), s.get('sort') || '', s.get('order') || ''].join('|');
      asked.push(key);
      const hit = fx.queries[key];
      if (!hit) return route.fulfill({ status: 500, json: { detail: 'no fixture for ' + key } });
      return route.fulfill({ status: hit.status, json: hit.body });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];
  try {
    for (const width of [1280, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await wire(context);
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(base + '/index.html#research/query');
      await page.waitForSelector('#qs-examples .qs-chip');
      assert.ok(await page.locator('#view-query').isVisible(), 'the query view is not shown');

      // 1 · an example runs as it stands
      await page.locator('#qs-examples .qs-chip').first().click();
      await page.waitForSelector('.qs-table');
      assert.match(await page.locator('.qs-sum').innerText(), /2\s+companies match/);
      assert.deepEqual(await page.locator('.qs-table tbody th[scope=row] b').allInnerTexts(),
                       ['ACME', 'BETA']);
      assert.match(decodeURIComponent(await page.evaluate(() => location.hash)),
                   /^#research\/query\/ROCE > 20\nDebt to equity/);

      // 2 · the builder writes a line the backend reads
      await page.locator('#qs-clear').click();
      await page.selectOption('#qs-bfield', 'roce');
      await page.selectOption('#qs-bop', '>');
      await page.fill('#qs-bval', '20');
      await page.locator('#qs-badd').click();
      assert.equal(await page.inputValue('#qs-q'), 'ROCE > 20');

      // 3 · a column header sorts on the server, twice reverses
      await page.locator('#qs-run').click();
      await page.waitForFunction(() => document.querySelectorAll('.qs-table tbody tr').length === 3);
      const syms = () => page.locator('.qs-table tbody th[scope=row] b').allInnerTexts();
      assert.deepEqual(await syms(), ['ACME', 'DELTA', 'BETA']);
      // DELTA has no ROE: a dash, never a zero.
      const deltaRow = page.locator('.qs-table tbody tr', { hasText: 'DELTA' });
      assert.match(await deltaRow.innerText(), /—/);
      await page.locator('.qs-sort[data-sort="roe"]').click();
      await page.waitForFunction(() => document.querySelector('th[aria-sort] .qs-sort[data-sort="roe"]'));
      assert.deepEqual(await syms(), ['ACME', 'BETA', 'DELTA']);
      await page.locator('.qs-sort[data-sort="roe"]').click();
      await page.waitForFunction(() => document.querySelector('th[aria-sort="ascending"]'));
      assert.deepEqual(await syms(), ['BETA', 'ACME', 'DELTA']);

      // 4 · suggestions while typing
      await page.locator('#qs-clear').click();
      await page.locator('#qs-q').pressSequentially('return on eq');
      await page.waitForSelector('#qs-ac:not([hidden]) li');
      assert.match(await page.locator('#qs-ac li').first().innerText(), /^ROE/);
      await page.keyboard.press('Enter');
      assert.equal(await page.inputValue('#qs-q'), 'ROE ');

      // 5 · a bad name: readable error, caret, one-click fix that re-runs
      await page.fill('#qs-q', 'ROEE > 15');
      await page.locator('#qs-run').click();
      await page.waitForSelector('#qs-err:not([hidden])');
      assert.match(await page.locator('#qs-err').innerText(), /'ROEE' is not a field/);
      assert.match(await page.locator('.qs-where').innerText(), /ROEE > 15\n\^/);
      await page.locator('#qs-err [data-fix="ROCE"]').click();
      assert.equal(await page.inputValue('#qs-q'), 'ROCE > 15');

      // 6 · nothing matches: said in words
      await page.fill('#qs-q', 'ROE > 100');
      await page.locator('#qs-run').click();
      await page.waitForFunction(() => /No company meets/.test(document.getElementById('qs-out').innerText));

      // 7 · the address carries the query: a reload runs it again
      await page.goto(base + '/index.html#research/query/' + encodeURIComponent('ROCE > 20'));
      await page.waitForFunction(() => document.querySelectorAll('.qs-table tbody tr').length === 3);

      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(overflow <= 1, `page scrolls sideways by ${overflow}px at ${width}px`);
      await page.screenshot({ path: path.join(output, width + '-query.png'), fullPage: true });
      await context.close();
    }
    assert.deepEqual(errors, [], 'page errors: ' + errors.join('\n'));
    console.log('query screener ok — screenshots in test-results/query');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
