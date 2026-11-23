/* The forum in a real Chromium: reading, the name a member picks, writing,
   and the stock pages' way in. No live calls; the API is a small fake that
   answers the way backend/forum_routes.py does.

   What this is actually guarding:
     · READING NEEDS NOTHING. Signed out, the front page, a category and a
       discussion all draw, and the way to write is a sign-in link that comes
       back to the same discussion.
     · A MEMBER'S WORDS ARE TEXT. A post with markup in it is printed, not
       run; an http(s) address becomes a link marked nofollow ugc; a
       javascript: address stays text.
     · A NAME BEFORE THE FIRST POST, and never the email.
     · A HOUSE RULE THAT REFUSES A POST SAYS WHICH SENTENCE, and the button
       comes back so the writer can fix it and send again.
     · A STOCK PAGE'S "START A DISCUSSION" lands in the composer on that
       company, and posting opens the new discussion.
     · phone width, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/forum');
fs.mkdirSync(output, { recursive: true });

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

const CATS = [
  { id: 'stocks', label: 'Stocks', blurb: 'One company at a time', threads: 2 },
  { id: 'market', label: 'Market & economy', blurb: 'Indices and flows', threads: 1 },
  { id: 'beginners', label: 'Beginners', blurb: 'No question is too basic', threads: 0 }];
const RULES = ['Share reasons, not tips: no prices to buy or sell at, no targets, no stop-loss levels.'];
const DISCLAIMER = 'Posts are written by members and are their own opinions.';

function thread(id, o) {
  return Object.assign({ id, category: 'stocks', category_label: 'Stocks', symbol: 'TCS', company: 'Tata Consultancy Services',
    title: 'Deal wins this quarter', author: 'Patient Compounder', created_at: '2026-11-20T09:00:00+00:00',
    last_post_at: '2026-11-21T09:00:00+00:00', replies: 2, locked: false, pinned: false, helpful: 1,
    excerpt: 'Large deal TCV was the best in six quarters.' }, o || {});
}

function fresh() {
  return {
    user: null, member: null, posted: [], handles: [],
    threads: [thread(7), thread(8, { category: 'market', category_label: 'Market & economy', symbol: null, company: null,
      title: 'FIIs sold all week', replies: 0, helpful: 0 })],
    posts: { 7: [
      { id: 70, author: 'Patient Compounder', created_at: '2026-11-20T09:00:00+00:00', status: 'visible', helpful: 1, voted: false, mine: false,
        body: 'Large deal TCV was the best in six quarters.\n\nSource: https://example.com/tcs-q2 and javascript:alert(1)' },
      { id: 71, author: '<b>Mallory</b>', created_at: '2026-11-21T09:00:00+00:00', status: 'visible', helpful: 0, voted: false, mine: false,
        body: '<img src=x onerror="window.__pwned=1"> margins?' },
      { id: 72, author: 'Gone', created_at: '2026-11-21T10:00:00+00:00', status: 'hidden', helpful: 0, voted: false, mine: false, body: null }] },
    refuseNext: false,
  };
}

async function wire(context, state) {
  await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') {
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    const body = () => JSON.parse(req.postData() || '{}');
    if (u.pathname === '/auth/me') {
      return state.user ? route.fulfill({ json: state.user }) : route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
    }
    if (u.pathname === '/forum') {
      const cat = u.searchParams.get('category'), sym = u.searchParams.get('symbol');
      const rows = state.threads.filter(t => (!cat || t.category === cat) && (!sym || t.symbol === sym));
      return route.fulfill({ json: { categories: CATS, rules: RULES, disclaimer: DISCLAIMER, threads: rows,
        page: 1, has_more: false, category: cat, symbol: sym, q: null, sort: 'latest' } });
    }
    if (u.pathname === '/forum/me') {
      if (!state.user) return route.fulfill({ status: 401, json: { detail: 'Sign in to post on the forum.' } });
      return route.fulfill({ json: { member: state.member, can_post: !!state.member } });
    }
    if (u.pathname === '/forum/me/handle') {
      const h = body().handle;
      state.handles.push(h);
      if (/@/.test(h)) return route.fulfill({ status: 400, json: { detail: 'A forum name cannot be an email address or a phone number.' } });
      state.member = { handle: h, status: 'active', since: '2026-11-22' };
      return route.fulfill({ json: { member: state.member } });
    }
    let m;
    if ((m = u.pathname.match(/^\/forum\/threads\/(\d+)$/))) {
      const t = state.threads.find(x => x.id === +m[1]);
      if (!t) return route.fulfill({ status: 404, json: { detail: 'That discussion is not on the forum.' } });
      return route.fulfill({ json: { thread: t, posts: state.posts[t.id] || [], disclaimer: DISCLAIMER } });
    }
    if (u.pathname === '/forum/threads' && req.method() === 'POST') {
      const b = body();
      state.posted.push(b);
      if (state.refuseNext) {
        state.refuseNext = false;
        return route.fulfill({ status: 422, json: { detail: { rule: 'tip', sentence: 'Buy at 3400 with a stop loss at 3300.',
          message: 'A price to buy or sell at, a target or a stop-loss level is what a stock tip is made of.' } } });
      }
      const t = thread(99, { title: b.title, symbol: b.symbol || null, category: b.category, replies: 0, author: state.member.handle });
      state.threads.unshift(t);
      state.posts[99] = [{ id: 990, author: state.member.handle, created_at: new Date().toISOString(), status: 'visible',
        helpful: 0, voted: false, mine: true, body: b.body }];
      return route.fulfill({ json: { thread: t, posts: state.posts[99], disclaimer: DISCLAIMER } });
    }
    if ((m = u.pathname.match(/^\/forum\/threads\/(\d+)\/posts$/))) {
      const p = { id: 1000 + state.posted.length, author: state.member.handle, created_at: new Date().toISOString(),
        status: 'visible', helpful: 0, voted: false, mine: true, body: body().body };
      state.posted.push({ reply: +m[1], body: p.body });
      return route.fulfill({ json: { post: p } });
    }
    if ((m = u.pathname.match(/^\/forum\/posts\/(\d+)\/helpful$/))) {
      return route.fulfill({ json: { post_id: +m[1], helpful: body().on ? 2 : 1, mine: !!body().on } });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
}

async function open(browser, state, hash, viewport) {
  const context = await browser.newContext({ viewport: viewport || { width: 1280, height: 900 } });
  await wire(context, state);
  if (state.user) await context.addInitScript(() => { localStorage.setItem('altaha-session-v1', 'tok'); });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.goto(server.base + '/forum.html' + (hash || ''), { waitUntil: 'load' });
  // After load: analytics.js defines its own AltahaTrack as it runs.
  await page.evaluate(() => { window.__t = []; window.AltahaTrack = (n, p) => window.__t.push([n, p]); });
  return { context, page, errors };
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  server.base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // ── Signed out: the front page, a category, a discussion ────────────────
    {
      const state = fresh();
      const { context, page, errors } = await open(browser, state);
      await page.locator('.fm-row').first().waitFor();
      assert.equal(await page.locator('.fm-row').count(), 2);
      assert.ok(await page.locator('#fm-h1').isVisible(), 'the front page lost its heading');
      assert.deepEqual(await page.locator('.fm-chips .fm-chip').allInnerTexts(), ['All', 'Stocks', 'Market & economy', 'Beginners']);
      assert.match(await page.locator('#fm-side').innerText(), /Sign in[\s\S]*Categories[\s\S]*House rules[\s\S]*weekly brief/i);
      await page.screenshot({ path: path.join(output, '1280-front.png'), fullPage: true });

      await page.locator('.fm-chip', { hasText: 'Market & economy' }).click();
      // The address changes at once; the page redraws when the hashchange
      // event reaches it, which a browser may hand over a frame later. This
      // used to wait on the address and then on this discussion's title, and
      // the title is on the front page too: both were true before the page
      // had redrawn, so the count below read the front page's two rows (CI,
      // every run from the day the forum landed). Wait for the redraw itself:
      // the chip marked as the category on show, drawn in the same stroke
      // that clears the old list.
      await page.locator('.fm-chip[aria-current="page"]', { hasText: 'Market & economy' }).waitFor();
      assert.equal(await page.evaluate(() => location.hash), '#c/market');
      await page.locator('.fm-row h3', { hasText: 'FIIs sold all week' }).waitFor();
      assert.equal(await page.locator('.fm-row').count(), 1);
      assert.equal(await page.locator('#fm-h1').isVisible(), false);

      await page.goto(server.base + '/forum.html#t/7');
      await page.locator('.fm-post').first().waitFor();
      assert.equal(await page.locator('.fm-post').count(), 3);
      assert.equal(await page.evaluate(() => window.__pwned), undefined, 'a post ran as markup');
      assert.equal(await page.locator('.fm-post img, .fm-post-h b b').count(), 0, 'a member\'s words were read as markup');
      assert.match(await page.locator('#p71').innerText(), /<img src=x/);
      const link = page.locator('#p70 .fm-body a');
      assert.equal(await link.count(), 1, 'one http address, one link; javascript: stays text');
      assert.equal(await link.getAttribute('href'), 'https://example.com/tcs-q2');
      assert.equal(await link.getAttribute('rel'), 'nofollow ugc noopener');
      assert.match(await page.locator('#p72').innerText(), /Hidden while/);
      assert.equal(await page.locator('#p72 .fm-acts').count(), 0);
      // The way to write: sign in, and come back to this discussion.
      const gate = page.locator('.fm-reply a.fm-btn');
      assert.equal(await gate.getAttribute('href'), 'signin.html?next=' + encodeURIComponent('forum.html#t/7'));
      assert.equal(await page.locator('#fm-reply').count(), 0, 'a signed-out reader was offered a reply box');
      assert.ok(await page.locator('[data-helpful="70"]').isDisabled(), 'a signed-out reader could vote');
      assert.match(await page.locator('.fm-disclaimer').innerText(), /own opinions/);
      assert.match(await page.locator('.fm-thread-h a.fm-tag').getAttribute('href'), /stock\.html\?ticker=TCS/);
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── Signed in: a name first, then a refused post, then a real one ───────
    {
      const state = fresh();
      state.user = { id: 1, email: 'reader@example.com' };
      const { context, page, errors } = await open(browser, state, '#new/stock/TCS');
      await page.locator('#fm-name-form').waitFor();
      // An email is refused as a name, and says so.
      await page.locator('#fm-name').fill('reader@example.com');
      await page.locator('#fm-name-form button').click();
      await page.locator('#fm-name-msg.is-err').waitFor();
      assert.match(await page.locator('#fm-name-msg').innerText(), /cannot be an email/);
      await page.locator('#fm-name').fill('Patient Reader');
      await page.locator('#fm-name-form button').click();
      await page.locator('#fm-new-form').waitFor();
      assert.equal(await page.locator('#fm-cat').inputValue(), 'stocks');
      assert.equal(await page.locator('#fm-sym').inputValue(), 'TCS');
      assert.match(await page.locator('#fm-new-form').innerText(), /Posting as Patient Reader/);
      assert.equal(await page.locator('body').innerText().then(t => /reader@example\.com/.test(t)), false, 'the email is on the page');

      // A general category hides the stock box.
      await page.locator('#fm-cat').selectOption('market');
      assert.equal(await page.locator('#fm-sym-field').isVisible(), false);
      await page.locator('#fm-cat').selectOption('stocks');

      state.refuseNext = true;
      await page.locator('#fm-title').fill('TCS after the deal wins');
      await page.locator('#fm-body').fill('Strong numbers all round. Buy at 3400 with a stop loss at 3300.');
      await page.locator('#fm-new-form button[type=submit]').click();
      await page.locator('#fm-new-msg.is-err blockquote').waitFor();
      assert.equal(await page.locator('#fm-new-msg blockquote').innerText(), 'Buy at 3400 with a stop loss at 3300.');
      assert.equal(await page.locator('#fm-new-form button[type=submit]').isDisabled(), false, 'the button did not come back');
      assert.deepEqual((await page.evaluate(() => window.__t)).filter(t => t[0] === 'forum_post_refused'),
        [['forum_post_refused', { rule: 'tip' }]]);

      await page.locator('#fm-body').fill('Strong numbers all round. The deal pipeline looks real to me; what am I missing?');
      await page.locator('#fm-new-form button[type=submit]').click();
      await page.waitForFunction(() => location.hash === '#t/99');
      await page.locator('.fm-post.is-first').waitFor();
      assert.match(await page.locator('.fm-thread-h h2').innerText(), /TCS after the deal wins/);
      assert.deepEqual(state.posted[1], { category: 'stocks', symbol: 'TCS', title: 'TCS after the deal wins',
        body: 'Strong numbers all round. The deal pipeline looks real to me; what am I missing?' });
      assert.deepEqual((await page.evaluate(() => window.__t)).filter(t => t[0] === 'forum_thread_started'),
        [['forum_thread_started', { category: 'stocks', from: 'stock' }]]);
      // My own post: a Remove, and no vote or report on it.
      assert.equal(await page.locator('.fm-post.is-first [data-remove]').count(), 1);
      assert.equal(await page.locator('.fm-post.is-first [data-report]').count(), 0);

      // A reply appends without reloading the discussion.
      await page.locator('#fm-reply-body').fill('Adding one thing: attrition is down too.');
      await page.locator('#fm-reply button').click();
      await page.locator('.fm-post').nth(1).waitFor();
      assert.match(await page.locator('.fm-post').nth(1).innerText(), /attrition is down/);
      assert.equal(await page.locator('#fm-reply-body').inputValue(), '');
      await page.screenshot({ path: path.join(output, '1280-thread.png'), fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── Signed in with a name: voting on someone else's post ────────────────
    {
      const state = fresh();
      state.user = { id: 2, email: 'b@example.com' };
      state.member = { handle: 'Bala', status: 'active', since: '2026-11-01' };
      const { context, page, errors } = await open(browser, state, '#t/7');
      const vote = page.locator('[data-helpful="70"]');
      await vote.waitFor();
      assert.equal(await vote.isDisabled(), false);
      await vote.click();
      await page.waitForFunction(() => document.querySelector('[data-helpful="70"]').getAttribute('aria-pressed') === 'true');
      assert.match(await vote.innerText(), /Helpful · 2/);
      assert.ok(await page.locator('#fm-reply').isVisible());
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── A phone ─────────────────────────────────────────────────────────────
    {
      const state = fresh();
      for (const hash of ['', '#t/7']) {
        const { context, page, errors } = await open(browser, state, hash, { width: 390, height: 844 });
        await page.locator(hash ? '.fm-post' : '.fm-row').first().waitFor();
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
          `the forum${hash ? ' discussion' : ''} scrolls sideways on a phone`);
        await page.screenshot({ path: path.join(output, '390' + (hash ? '-thread' : '-front') + '.png'), fullPage: true });
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    console.log('forum browser checks passed');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
