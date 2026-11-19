/* Today › Headlines: a headline opens its story.
 *
 * This exists because of a bug that shipped. The news feed calls a story's
 * address `link`; the Headlines card read `url`, which the feed has never
 * sent. So every headline was a link to "#": it underlined on hover, showed
 * the site's own address in the status bar, and went nowhere. Nothing threw,
 * and every other test fed the page an empty feed.
 *
 * So this feeds it stories in the shape the server really sends
 * (backend/market_news.py) and asserts on what the reader gets:
 *   - a headline is a link to the story, and tapping it opens the story in a
 *     new tab while Today stays where it is
 *   - no headline is ever a link to "#"
 *   - a story with no address is text, not a link that does nothing
 *   - only an http(s) address becomes a link — the text is other people's RSS
 *   - a headline's own markup is shown as text, never run
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/today-headlines');
fs.mkdirSync(output, { recursive: true });

const STORY = 'https://www.thehindubusinessline.com/markets/dhan-launches-sif/article70001.ece';
const QUOTED = 'https://example.com/story?id=7&q="rates"';
const lead = (id, title, publication, extra) => ({ id, title, publication, summary: '', score: 5, ...extra });
// The shape feed() returns: clusters, each with the story that leads it.
const feed = { total_clusters: 5, total_stories: 5, clusters: [
  { corroboration: 1, lead: lead('a', 'Dhan launches SIF investing, offering long-short strategies', 'Hindu BusinessLine', { link: STORY }) },
  { corroboration: 1, lead: lead('b', 'A story the feed sent with no address', 'Mint', { link: '' }) },
  { corroboration: 1, lead: lead('c', 'A story whose address is a script', 'Somebody', { link: 'javascript:window.__ran=1' }) },
  { corroboration: 1, lead: lead('d', '<img src=x onerror=__ran=1>Rates & "bonds" <b>steady</b>', 'Economic Times', { link: QUOTED }) },
  { corroboration: 1, lead: lead('e', 'A story sent under the other name', 'Reuters', { url: 'https://example.org/older-name' }) }
] };

const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript; charset=utf-8'
      : file.endsWith('.css') ? 'text/css; charset=utf-8'
      : file.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream');
    res.end(fs.readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(r => server.listen(8795, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  for (const width of [390, 1280]) {
    const context = await browser.newContext({ viewport: { width, height: 840 }, reducedMotion: 'reduce' });
    await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1') return route.continue();
      // The story itself, opened in its own tab.
      if (route.request().resourceType() === 'document') {
        return route.fulfill({ contentType: 'text/html', body: '<title>the story</title><p>the story</p>' });
      }
      if (['script', 'font', 'stylesheet'].includes(route.request().resourceType())) return route.abort();
      if (u.pathname === '/social/news/feed') return route.fulfill({ json: feed });
      return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack)));

    await page.goto('http://127.0.0.1:8795/', { waitUntil: 'domcontentloaded' });
    const list = page.locator('#drt-heads .dr-hlist');
    await list.locator('li').first().waitFor();
    assert.equal(await list.locator('li').count(), 5, `${width}: every story in the feed is listed`);
    const address = page.url();

    // No headline is a link to nowhere. This is the bug, stated as a rule.
    const hrefs = await list.locator('a').evaluateAll(as => as.map(a => a.getAttribute('href')));
    assert.ok(hrefs.every(h => /^https?:\/\//.test(h)), `${width}: a headline links to "${hrefs.find(h => !/^https?:\/\//.test(h))}"`);
    assert.deepEqual(hrefs, [STORY, QUOTED, 'https://example.org/older-name'],
      `${width}: each headline goes to the address the feed sent for it`);

    // A new tab, and nothing handed to the site it opens.
    const first = list.locator('a').first();
    assert.equal(await first.getAttribute('target'), '_blank');
    assert.match(await first.getAttribute('rel'), /noopener/);
    assert.match(await first.innerText(), /Dhan launches SIF investing/);
    assert.match(await list.locator('li').first().locator('small').innerText(), /Hindu BusinessLine/);

    // The tap: the story opens, and Today has not gone anywhere.
    const [story] = await Promise.all([context.waitForEvent('page'), first.click()]);
    await story.waitForLoadState('domcontentloaded');
    assert.equal(story.url(), STORY, `${width}: the headline opened something other than its story`);
    assert.equal(page.url(), address, `${width}: opening a story moved Today`);
    assert.ok(await page.locator('#view-today').isVisible());
    await story.close();

    // No address, or an address that is not a web address: text, not a link.
    for (const title of ['A story the feed sent with no address', 'A story whose address is a script']) {
      const row = list.locator('li', { hasText: title });
      assert.equal(await row.locator('a').count(), 0, `${width}: "${title}" was made a link`);
      assert.match(await row.innerText(), new RegExp(title));
    }
    assert.equal(await page.evaluate(() => window.__ran), undefined);

    // A headline is text. Whatever a feed puts in a title is shown, not run.
    const marked = list.locator('li', { hasText: 'Rates &' });
    assert.equal(await marked.locator('img, b').count(), 0, `${width}: a headline's markup was rendered`);
    assert.ok((await marked.locator('a').innerText()).includes('<b>steady</b>'));
    assert.equal(await page.evaluate(() => window.__ran), undefined);

    await page.locator('#drt-heads').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `${width}-headlines.png`) });
    await context.close();
  }

  await browser.close();
  server.close();
  assert.deepEqual(errors, []);
  console.log('Today headlines open their stories');
})().catch(e => { console.error(e); process.exit(1); });
