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
     · no horizontal page scroll at phone width;
     · Ask AI stays locked until the server accepts the admin key, sends the
       key as a header and never in a URL, shows Claude's reply as text (no
       markup survives), shows each query with the screener's own count or
       its parse error, puts a query in the editor and runs it, carries the
       conversation into a follow-up, and Lock forgets the key. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/query');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/query.json'), 'utf8'));
const asked = [];
const aiSeen = [];

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
    if (u.pathname === '/admin/query/ai') {
      const req = route.request(), key = req.headers()['x-admin-key'] || '';
      const post = req.method() === 'POST';
      aiSeen.push({ method: req.method(), url: req.url(), key, body: post ? req.postDataJSON() : null });
      if (key !== fx.ai.key) return route.fulfill({ status: 401, json: fx.ai.refused });
      if (!post) return route.fulfill({ json: fx.ai.status });
      const n = aiSeen.filter(s => s.method === 'POST' && s.key === fx.ai.key).length;
      return route.fulfill({ json: fx.ai.answers[Math.min(n, fx.ai.answers.length) - 1] });
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

      // 8 · Ask AI is locked until the server accepts the admin key
      aiSeen.length = 0;
      await page.locator('#qs-aibtn').click();
      await page.waitForSelector('#qs-ai:not([hidden]) #qs-ai-keyin');
      assert.ok(await page.locator('#qs-ai-chat').isHidden(), 'the chat shows before a key is given');
      await page.fill('#qs-ai-keyin', 'wrong-key');
      await page.locator('#qs-ai-keygo').click();
      await page.waitForFunction(() => /not accepted/.test(document.getElementById('qs-ai-keymsg').textContent));
      assert.ok(await page.locator('#qs-ai-chat').isHidden(), 'a wrong key opened the chat');
      assert.equal(await page.evaluate(() => sessionStorage.getItem('altaha.query.aikey')), null,
                   'a refused key was kept');
      await page.fill('#qs-ai-keyin', fx.ai.key);
      await page.locator('#qs-ai-keygo').click();
      await page.waitForSelector('#qs-ai-chat:not([hidden]) #qs-ai-starters .qs-chip');

      // 9 · a question: the reply as text, each query with the screener's own count
      await page.fill('#qs-ai-in', 'Companies with a high return on capital');
      await page.keyboard.press('Enter');
      await page.waitForSelector('.qs-ai-msg.is-ai .qs-ai-q');
      const firstAsk = aiSeen.find(s => s.method === 'POST');
      assert.equal(firstAsk.key, fx.ai.key);
      assert.deepEqual(firstAsk.body.messages,
                       [{ role: 'user', content: 'Companies with a high return on capital' }]);
      assert.equal(firstAsk.body.query, 'ROCE > 20', "the editor's query did not go with the question");
      assert.ok(aiSeen.every(s => !s.url.includes(fx.ai.key)), 'the admin key went into a URL');
      const cards = page.locator('.qs-ai-q');
      assert.equal(await cards.count(), 2);
      assert.match(await cards.nth(0).innerText(), /3 companies match of 4/);
      assert.match(await cards.nth(1).innerText(), /Does not run: 'ROEE' is not a field/);
      assert.equal(await cards.nth(1).locator('[data-airun]').count(), 0,
                   'a query that does not parse is offered to run');
      assert.equal(await page.locator('.qs-ai-text img').count(), 0, 'markup in a reply was rendered');
      assert.match(await page.locator('.qs-ai-text').innerText(), /<img src=x onerror=alert\(1\)>/);
      assert.equal(await page.locator('.qs-ai-text li').count(), 2);
      assert.equal(await page.locator('.qs-ai-text code').first().innerText(), 'ROCE');

      // 10 · "Use and run" puts the query in the editor and runs it
      await page.fill('#qs-q', '');
      const ran = page.waitForResponse(r => r.url().includes('/fundamentals/query?'));
      await cards.nth(0).locator('[data-airun]').click();
      assert.equal(await page.inputValue('#qs-q'), 'ROCE > 20');
      await ran;
      await page.waitForFunction(() => document.querySelectorAll('.qs-table tbody tr').length === 3);

      // 11 · a follow-up carries the conversation, queries included
      await page.locator('.qs-ai-follow .qs-chip').click();
      await page.waitForFunction(() => document.querySelectorAll('.qs-ai-msg.is-ai').length === 2 &&
                                       !document.querySelector('.qs-ai-msg.is-busy'));
      const secondAsk = aiSeen.filter(s => s.method === 'POST')[1];
      assert.deepEqual(secondAsk.body.messages.map(m => m.role), ['user', 'assistant', 'user']);
      assert.match(secondAsk.body.messages[1].content,
                   /Query 1 — High return on capital \(3 matched\):\nROCE > 20/);
      const aiOverflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(aiOverflow <= 1, `Ask AI scrolls the page sideways by ${aiOverflow}px at ${width}px`);
      await page.locator('#qs-ai').screenshot({ path: path.join(output, width + '-ask-ai.png') });

      // 12 · Lock forgets the key
      await page.locator('#qs-ai-lock').click();
      assert.ok(await page.locator('#qs-ai-keyin').isVisible(), 'Lock did not ask for the key again');
      assert.equal(await page.evaluate(() => sessionStorage.getItem('altaha.query.aikey')), null);
      await context.close();
    }
    assert.deepEqual(errors, [], 'page errors: ' + errors.join('\n'));
    console.log('query screener ok — screenshots in test-results/query');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
