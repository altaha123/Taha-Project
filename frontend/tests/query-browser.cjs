/* The screener (#research/query) in a real Chromium, against responses
   produced by the real endpoints (backend/tests/make_query_fixture.py).

   What is guarded, first, is the page a newcomer meets, which asks for no
   typing at all:
     · it opens on cards to tap, with no number, no table and the editor
       folded away;
     · tapping a card runs it: the count, a bar for each choice in turn, the
       table, and the query in the address, with no button pressed;
     · a card's setting tightens the list; the cross on a bar removes that
       choice; Start over clears everything;
     · a ready-made idea switches on the cards it is made of, and tapping it
       again switches them off; a list nobody fits says so in words;
     · the last list comes back, cards lit, on the next visit;
     · a query typed, saved or opened from a link lights the cards it is made
       of and carries the rest as "your own rules".

   And then the editor underneath, as before:
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
      await page.waitForSelector('.qz-wish-main');
      assert.ok(await page.locator('#view-query').isVisible(), 'the query view is not shown');
      const hash = () => page.evaluate(() => decodeURIComponent(location.hash));
      const syms0 = () => page.locator('.qs-table tbody th[scope=row] b').allInnerTexts();
      const bars = () => page.locator('.qz-bar').evaluateAll(ns => ns.map(n =>
        n.querySelector('.qz-bar-l b').textContent + ' ' + n.querySelector('.qz-bar-n').textContent));
      /* The buttons under the board. On a phone the bar along the bottom covers
         the last strip of the screen, and a button that scrolls to rest there is
         under its search button: a person scrolls on, a click cannot. Each is
         brought to the middle of the screen first. */
      const act = async sel => {
        await page.locator(sel).evaluate(n => n.scrollIntoView({ block: 'center' }));
        await page.locator(sel).click();
      };
      const lit = () => page.locator('.qz-wish.on').evaluateAll(ns => ns.map(n =>
        n.dataset.wishbox + ':' + ((n.querySelector('.qz-level.on') || {}).textContent || '')));
      const count = n => page.waitForFunction(k => (document.getElementById('qz-n') || {}).textContent === k, String(n));

      // A · the page a newcomer meets: cards to tap, nothing to type
      assert.equal(await page.locator('.qz-recipe').count(), 6);
      assert.equal(await page.locator('.qz-wish').count(), 10);
      assert.match(await page.locator('#qz-board').innerText(), /Tap a card above/);
      assert.equal(await page.locator('.qs-table, #qz-n').count(), 0, 'a list is shown before anything is chosen');
      assert.equal(await page.locator('#qs-q').isVisible(), false, 'the editor is open on a first visit');
      assert.equal(await page.locator('#qz-acts').isVisible(), false);
      assert.doesNotMatch(await page.locator('#qz').innerText(), /\bquery\b|\bfield\b|\bcondition\b/i,
                          'the words of the editor are on the page a newcomer meets');

      // B · one tap is a question asked: the count, the bars, the table, the address
      await page.locator('.qz-wish-main[data-wish="profit"]').click();
      await page.waitForSelector('.qs-table');
      await count(2);
      assert.match(await page.locator('.qz-count').innerText(), /2\s*companies fit\s*out of 4/);
      assert.deepEqual(await bars(), ['Every company we have figures for 4', 'Makes good money 2']);
      assert.deepEqual(await syms0(), ['ACME', 'BETA']);
      assert.equal(await hash(), '#research/query/ROE > 12');
      assert.equal(await page.inputValue('#qs-q'), 'ROE > 12', 'the choice was not written into the editor');
      assert.deepEqual(await lit(), ['profit:Good']);
      assert.equal(await page.locator('.qz-wish-main[data-wish="profit"]').getAttribute('aria-pressed'), 'true');
      assert.match(await page.locator('.qz-wish.on .qz-note').innerText(), /₹12 a year on every ₹100[\s\S]*ROE above 12%/);
      assert.match(await page.locator('#qz-board .qz-unk').innerText(), /1 company is left out/);

      // C · a setting tightens it, a second card narrows it, and each has its bar
      await page.locator('.qz-level[data-wish="profit"][data-level="1"]').click();
      await count(1);
      assert.equal(await hash(), '#research/query/ROE > 18');
      assert.deepEqual(await syms0(), ['ACME']);
      assert.match(await page.locator('.qz-count').innerText(), /1\s*company fits/);
      await page.locator('.qz-wish-main[data-wish="debt"]').click();
      await page.waitForFunction(() => document.querySelectorAll('.qz-bar').length === 3);
      assert.equal(await hash(), '#research/query/ROE > 18\nDebt to equity < 0.5');
      assert.deepEqual(await bars(), ['Every company we have figures for 4', 'Makes good money 1', 'Owes little 1']);
      assert.deepEqual(await lit(), ['profit:Great', 'debt:Little']);

      // D · the last list comes back on the next visit, cards and all
      await page.goto(base + '/index.html');
      await page.goto(base + '/index.html#research/query');
      await page.waitForSelector('.qs-table');
      assert.deepEqual(await lit(), ['profit:Great', 'debt:Little']);
      assert.equal(await page.locator('#qs-q').isVisible(), false, 'a list made of cards opened the editor');

      // E · the cross on a bar removes that choice; Start over removes them all
      await page.locator('.qz-bar-x[data-drop="profit"]').click();
      await count(2);
      assert.equal(await hash(), '#research/query/Debt to equity < 0.5');
      assert.deepEqual(await lit(), ['debt:Little']);
      // A list can be kept by name from here, and comes back with a tap.
      await act('#qz-save');
      await page.locator('#qz-result #qs-savename').fill('Little debt');
      await page.locator('#qs-savego').click();
      await page.locator('#qs-saved .qs-chip', { hasText: 'Little debt' }).waitFor();
      await act('#qz-reset');
      assert.match(await page.locator('#qz-board').innerText(), /Tap a card above/);
      assert.equal(await page.locator('.qs-table, .qz-wish.on').count(), 0, 'Start over left something behind');
      assert.equal(await hash(), '#research/query');
      assert.equal(await page.inputValue('#qs-q'), '');

      await page.locator('#qs-saved .qs-chip', { hasText: 'Little debt' }).click();
      await count(2);
      assert.deepEqual(await lit(), ['debt:Little'], 'a saved list did not come back with its card lit');
      await page.locator('#qs-saved .qs-sdel').click();
      await page.waitForFunction(() => document.getElementById('qs-saved').hidden);
      await act('#qz-reset');

      // F · a ready-made idea is cards switched on together; nobody fitting is said in words
      await page.locator('.qz-recipe[data-recipe="nodebt"]').click();
      await count(0);
      assert.equal(await hash(), '#research/query/Debt to equity < 0.1\nROE > 18');
      assert.deepEqual(await lit(), ['profit:Great', 'debt:Almost none']);
      assert.equal(await page.locator('.qz-recipe[data-recipe="nodebt"]').getAttribute('aria-pressed'), 'true');
      assert.match(await page.locator('#qz-board').innerText(), /No company fits all of that/);
      assert.deepEqual(await bars(), ['Every company we have figures for 4', 'Owes little 0', 'Makes good money 0']);
      await page.waitForFunction(() => /No company meets/.test(document.getElementById('qs-out').innerText));
      await page.locator('.qz-recipe[data-recipe="nodebt"]').click();
      assert.equal(await page.locator('.qz-wish.on').count(), 0, 'tapping a lit idea again did not switch it off');
      const fits = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(fits <= 1, `the finder scrolls sideways by ${fits}px at ${width}px`);
      await page.locator('.qz-recipe[data-recipe="nodebt"]').click();
      await count(0);
      await page.screenshot({ path: path.join(output, width + '-finder.png'), fullPage: true });
      await act('#qz-reset');

      // 1 · the second section, Make your own query, is a tab at the top and
      //     not a fold at the foot. One section is on screen at a time.
      assert.deepEqual(await page.locator('.qs-mode b').allInnerTexts(), ['Pick what you want', 'Make your own query']);
      assert.equal(await page.locator('#qs-mode-pick').getAttribute('aria-selected'), 'true');
      assert.ok(await page.locator('#qz').isVisible() && !(await page.locator('#qs-adv').isVisible()));
      await page.locator('#qs-mode-write').click();
      assert.equal(await page.locator('#qs-mode-write').getAttribute('aria-selected'), 'true');
      assert.ok(await page.locator('#qs-adv').isVisible() && !(await page.locator('#qz').isVisible()),
                'both sections are showing at once');
      assert.ok(await page.locator('#qs-q').isVisible());
      // The arrow keys move between the two, as on any tab list.
      await page.locator('#qs-mode-write').press('ArrowLeft');
      assert.ok(await page.locator('#qz').isVisible());
      assert.equal(await page.evaluate(() => document.activeElement.id), 'qs-mode-pick');
      await page.locator('#qs-mode-pick').press('ArrowRight');
      assert.ok(await page.locator('#qs-adv').isVisible());

      // An example runs as it stands, and the reader stays in this section.
      await page.waitForSelector('#qs-examples .qs-chip');
      await page.locator('#qs-examples .qs-chip').first().click();
      await page.waitForSelector('.qs-table');
      assert.match(await page.locator('.qs-sum').innerText(), /2\s+companies match/);
      // A query written in the editor lights the card it contains, and the rest are "your own rules".
      await page.waitForFunction(() => document.querySelectorAll('.qz-bar').length === 3);
      assert.deepEqual(await lit(), ['debt:Little']);
      assert.deepEqual(await bars(), ['Every company we have figures for 4', 'Owes little 2', 'Your own rules 2']);
      assert.deepEqual(await page.locator('.qs-table tbody th[scope=row] b').allInnerTexts(),
                       ['ACME', 'BETA']);
      assert.match(decodeURIComponent(await page.evaluate(() => location.hash)),
                   /^#research\/query\/ROCE > 20\nDebt to equity/);
      assert.ok(await page.locator('#qs-adv').isVisible(), 'running a query moved the reader out of the editor');
      // The same query, seen from the cards: its card is lit and the rest is one bar.
      await page.locator('#qs-mode-pick').click();
      assert.ok(await page.locator('.qz-wish.on[data-wish="debt"], .qz-wish.on').first().isVisible());
      // Edit as a query goes back to the editor with those lines in it.
      await act('#qz-edit');
      assert.ok(await page.locator('#qs-adv').isVisible());
      assert.match(await page.inputValue('#qs-q'), /^ROCE > 20\nDebt to equity/);

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
      // A rule no card explains opens the section that can show it.
      assert.ok(await page.locator('#qs-adv').isVisible(), 'a typed query opened on the cards');
      assert.equal(await page.inputValue('#qs-q'), 'ROCE > 20');

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
