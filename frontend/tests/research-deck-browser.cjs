/* The Research Deck in a real Chromium: reading, sharing on X, and the owner
   writing. No live calls; the API is a small fake that answers the way
   backend/research_routes.py does.

   What this is actually guarding:
     · ONLY THE OWNER WRITES. Signed out there is no New article button and
       no edit link anywhere; ?edit=new says only the owner can write. A
       wrong admin key is refused and forgotten.
     · AN ARTICLE IS TEXT. Markup in a body is printed, not run; a
       javascript: link stays text; photos written as ![caption](media:id)
       become figures.
     · SHARE ON X opens x.com's composer with the title and the site's own
       /share/research link (never the API host), so X draws the card.
     · THE OWNER'S LOOP: sign in, upload a cover, write, publish, and the
       share buttons appear on the spot.
     · phone width, no horizontal page scroll.

   Run: node frontend/tests/research-deck-browser.cjs  (from the repo root) */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/research-deck');
fs.mkdirSync(output, { recursive: true });
const KEY = 'owner-key';

// A 1x1 PNG, for every photo the fake serves.
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkqPhfDwAEhgHZ0rYpnQAAAABJRU5ErkJggg==', 'base64');

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

function fresh() {
  return {
    nextMedia: 1,
    articles: [{
      id: 1, slug: 'capital-goods-order-books', version: 2, status: 'published',
      title: 'Capital goods: why the order book matters this year',
      summary: 'Order inflows have doubled in two years. Execution, not demand, is now the constraint.',
      body: '## The order book\n\nInflows doubled. See **this** and *that*, and $LT.\n\n' +
            '![The order book chart](media:00000000000000aa)\n\n- One\n- Two\n\n' +
            '<script>window.__pwned = 1</script>\n\n[bad](javascript:alert(1)) and [good](https://nseindia.com)',
      cover: '00000000000000aa', tickers: ['LT', 'SIEMENS'],
      published_at: '2026-11-20T10:00:00+00:00', updated_at: '2026-11-21T10:00:00+00:00',
      created_at: '2026-11-20T10:00:00+00:00', minutes: 3
    }, {
      id: 2, slug: 'draft-banks', version: 1, status: 'draft', title: 'Banks: a draft',
      summary: 'Not ready.', body: 'WIP', cover: null, tickers: ['HDFCBANK'],
      published_at: null, updated_at: '2026-11-22T10:00:00+00:00', created_at: '2026-11-22T10:00:00+00:00', minutes: 1
    }]
  };
}

function links(a) {
  return Object.assign({}, a, {
    url: 'https://altahascreener.in/research-deck?a=' + a.slug,
    share_url: 'https://altahascreener.in/share/research/' + a.slug + '?v=' + a.version,
    card_url: 'https://altahascreener.in/og/research.png?slug=' + a.slug + '&v=' + a.version
  });
}

async function open(browser, state, query, viewport, key) {
  const context = await browser.newContext({ viewport: viewport || { width: 1280, height: 900 } });
  if (key) await context.addInitScript(k => { try { localStorage.setItem('altaha-admin-key', k); } catch (e) {} }, key);
  await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (type === 'font') return route.abort();
    if (!/onrender\.com$/.test(u.hostname)) {
      if (type === 'image') return route.fulfill({ body: PIXEL, contentType: 'image/png' });
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    const admin = (req.headers()['x-admin-key'] || u.searchParams.get('key')) === KEY;
    const body = () => { try { return JSON.parse(req.postData() || '{}'); } catch (e) { return {}; } };
    let m;
    if (u.pathname.startsWith('/research/media/')) return route.fulfill({ body: PIXEL, contentType: 'image/png' });
    if (u.pathname === '/research/articles') {
      const t = u.searchParams.get('ticker');
      const items = state.articles.filter(a => a.status === 'published' && (!t || a.tickers.includes(t))).map(links);
      return route.fulfill({ json: { total: items.length, items } });
    }
    if ((m = /^\/research\/articles\/(.+)$/.exec(u.pathname))) {
      const a = state.articles.find(x => x.slug === decodeURIComponent(m[1]) && x.status === 'published');
      return a ? route.fulfill({ json: links(a) }) : route.fulfill({ status: 404, json: { detail: 'There is no such article, or it is not published.' } });
    }
    if (u.pathname.startsWith('/admin/research')) {
      if (!admin) return route.fulfill({ status: 401, json: { detail: 'admin key required' } });
      if (u.pathname === '/admin/research') {
        const id = u.searchParams.get('id');
        if (id) {
          const a = state.articles.find(x => String(x.id) === id);
          return a ? route.fulfill({ json: links(a) }) : route.fulfill({ status: 404, json: { detail: 'There is no such article.' } });
        }
        return route.fulfill({ json: { total: state.articles.length, items: state.articles.map(links) } });
      }
      if (u.pathname === '/admin/research/media') {
        assert.match(body().data || '', /^data:image\//, 'the upload was not sent as a data URL');
        const id = String(state.nextMedia++).padStart(16, 'b');
        return route.fulfill({ json: { id, ref: 'media:' + id, mime: 'image/png', width: 1, height: 1, size: 70 } });
      }
      if (u.pathname === '/admin/research/save') {
        const b = body();
        if (!String(b.title || '').trim()) return route.fulfill({ status: 400, json: { detail: 'Give the article a title.' } });
        let a = b.id ? state.articles.find(x => x.id === b.id) : null;
        const now = new Date().toISOString();
        if (!a) {
          a = { id: state.articles.length + 1, slug: b.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
                version: 0, created_at: now, published_at: null };
          state.articles.push(a);
        }
        Object.assign(a, { title: b.title, summary: b.summary, body: b.body, status: b.status,
                           tickers: String(b.tickers || '').split(/,/).map(s => s.replace(/\s+/g, '')).filter(Boolean).map(s => s.toUpperCase()),
                           cover: b.cover ? b.cover.replace('media:', '') : null, updated_at: now, minutes: 1 });
        a.version += 1;
        if (b.status === 'published' && !a.published_at) a.published_at = now;
        state.saved = Object.assign({}, b);
        return route.fulfill({ json: links(a) });
      }
      if (u.pathname === '/admin/research/delete') {
        state.articles = state.articles.filter(x => x.id !== body().id);
        return route.fulfill({ json: { deleted: body().id } });
      }
    }
    return route.fulfill({ json: {} });
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${server.address().port}/research-deck.html${query || ''}`);
  return { context, page, errors };
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // ── A reader: the deck, signed out ─────────────────────────────────────
    {
      const { context, page, errors } = await open(browser, fresh(), '');
      await page.locator('.rd-tile').first().waitFor();
      assert.equal(await page.locator('.rd-tile').count(), 1, 'a draft reached the public deck');
      assert.equal(await page.locator('#rd-owner-bar').isVisible(), false, 'a reader sees New article');
      assert.match(await page.locator('.rd-tile-title').innerText(), /Capital goods/);
      await page.screenshot({ path: path.join(output, '1280-deck.png'), fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── A reader: one article, and sharing it on X ─────────────────────────
    {
      const { context, page, errors } = await open(browser, fresh(), '?a=capital-goods-order-books');
      await page.locator('.rd-article').waitFor();
      assert.equal(await page.evaluate(() => window.__pwned), undefined, 'a script in an article body ran');
      assert.ok((await page.locator('.rd-body').innerText()).includes('<script>'), 'markup in a body was swallowed rather than printed');
      assert.equal(await page.locator('.rd-body a[href^="javascript"]').count(), 0, 'a javascript: link became a link');
      assert.equal(await page.locator('.rd-body a[href="https://nseindia.com"]').count(), 1);
      assert.equal(await page.locator('.rd-body figure img').count(), 1, 'a photo line did not become a figure');
      assert.equal(await page.locator('.rd-body figcaption').innerText(), 'The order book chart');
      assert.equal(await page.locator('.rd-body a.rd-sym').getAttribute('href'), 'stock.html?ticker=LT');
      assert.equal(await page.locator('text=Edit this article').count(), 0, 'a reader sees the edit link');

      const [popup] = await Promise.all([
        context.waitForEvent('page'),
        page.locator('.rd-share [data-act="x"]').first().click()
      ]);
      const x = new URL(popup.url());
      assert.equal(x.hostname, 'x.com');
      assert.equal(x.pathname, '/intent/post');
      assert.match(x.searchParams.get('text'), /^Capital goods/);
      assert.match(x.searchParams.get('text'), /\$LT/);
      assert.match(x.searchParams.get('url'), /\/share\/research\/capital-goods-order-books\?v=2$/);
      assert.doesNotMatch(x.searchParams.get('url'), /onrender/, 'the API host reached the X post');
      await popup.close();
      await page.screenshot({ path: path.join(output, '1280-article.png'), fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── Not the owner: the editor stays shut ───────────────────────────────
    {
      const { context, page, errors } = await open(browser, fresh(), '?edit=new', null, 'wrong-key');
      await page.locator('.rd-empty').waitFor();
      assert.match(await page.locator('.rd-empty').innerText(), /Only the owner/);
      assert.equal(await page.evaluate(() => localStorage.getItem('altaha-admin-key')), null, 'a refused key was kept');
      assert.equal(await page.locator('#ed-title').count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── The owner: sign in, write, publish, share ──────────────────────────
    {
      const state = fresh();
      const { context, page, errors } = await open(browser, state, '');
      page.once('dialog', d => d.accept(KEY));
      await page.locator('#rd-owner').click();
      await page.locator('#rd-owner-bar').waitFor({ state: 'visible' });
      await page.locator('.rd-tile.is-draft').waitFor();
      assert.equal(await page.locator('.rd-tile').count(), 2, 'the owner does not see their drafts');

      await page.locator('#rd-new').click();
      await page.locator('#ed-title').waitFor();
      await page.fill('#ed-title', 'Auto ancillaries: a photo essay');
      await page.fill('#ed-summary', 'Five plants, one theme: capacity is sold out.');
      await page.fill('#ed-tickers', 'motherson, uno minda');
      await page.locator('#ed-cover-file').setInputFiles({ name: 'plant.png', mimeType: 'image/png', buffer: PIXEL });
      await page.locator('#ed-cover img').waitFor();
      await page.fill('#ed-body', 'First paragraph.');
      await page.locator('#ed-body').evaluate(el => el.setSelectionRange(el.value.length, el.value.length));
      await page.locator('#ed-photo').setInputFiles({ name: 'line-3.png', mimeType: 'image/png', buffer: PIXEL });
      await page.waitForFunction(() => /media:/.test(document.getElementById('ed-body').value));
      assert.match(await page.inputValue('#ed-body'), /^First paragraph\.\n\n!\[line-3\]\(media:[0-9a-f]{16}\)/);

      await page.locator('#ed-preview-btn').click();
      assert.equal(await page.locator('#ed-preview figure').count(), 1, 'the preview does not show the photo');
      await page.locator('#ed-preview-btn').click();

      await page.locator('#ed-publish').click();
      await page.locator('.rd-published').waitFor();
      assert.equal(state.saved.status, 'published');
      assert.match(state.saved.cover, /^media:/);
      assert.match(await page.locator('#ed-status').innerText(), /Published/);
      assert.equal(await page.locator('.rd-published .rd-share [data-act="x"]').count(), 1, 'no Share on X after publishing');
      assert.match(page.url(), /\?edit=\d+$/);
      await page.screenshot({ path: path.join(output, '1280-published.png'), fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }

    // ── A phone ─────────────────────────────────────────────────────────────
    {
      for (const q of ['', '?a=capital-goods-order-books']) {
        const { context, page, errors } = await open(browser, fresh(), q, { width: 390, height: 844 });
        await page.locator(q ? '.rd-article' : '.rd-tile').first().waitFor();
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
          `the deck${q ? ' article' : ''} scrolls sideways on a phone`);
        await page.screenshot({ path: path.join(output, '390' + (q ? '-article' : '-deck') + '.png'), fullPage: true });
        assert.deepEqual(errors, []);
        await context.close();
      }
    }
    console.log('research deck browser checks passed');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
