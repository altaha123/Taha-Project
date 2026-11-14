/* The footer: every tool on the site, by door, at the bottom of every page.
 *
 *   · it is on the homepage, the stock page and the Pro page, and not on the
 *     two full-screen desks
 *   · a link opens its tool in place on the homepage, and is an ordinary
 *     link to index.html#door/tool anywhere else
 *   · the address to write to is a mailto
 *   · on a 390px phone it stacks, nothing scrolls sideways, and the last line
 *     clears the bottom bar
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend'), out = path.resolve('test-results/footer');
const PORT = 8776;

const server = http.createServer((req, res) => {
  const name = path.join(root, decodeURIComponent(req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!name.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' :
      name.endsWith('.html') ? 'text/html' : name.endsWith('.png') ? 'image/png' : 'application/octet-stream');
    res.end(fs.readFileSync(name));
  } catch (e) { res.writeHead(404).end(); }
});

async function open(browser, size, file) {
  const context = await browser.newContext({ viewport: size, hasTouch: size.width < 600 });
  await context.addInitScript(() => localStorage.setItem('altaha-guide-dismissed', '1'));
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname === '127.0.0.1') return route.continue();
    if (['script', 'font', 'stylesheet', 'image'].includes(route.request().resourceType())) return route.abort();
    return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' },
                           headers: { 'access-control-allow-origin': '*' } });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  await page.goto(`http://127.0.0.1:${PORT}/${file}`, { waitUntil: 'domcontentloaded' });
  return { context, page, errors };
}

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // The homepage, on a desktop.
    let { context, page, errors } = await open(browser, { width: 1366, height: 900 }, 'index.html');
    const foot = page.locator('footer.sh-footer');
    await foot.waitFor();
    assert.deepEqual(await foot.locator('.sh-fcol h4').allInnerTexts().then(a => a.map(s => s.toLowerCase())),
                     ['today', 'ideas', 'my money', 'altaha']);
    assert.ok(await foot.locator('.sh-fcol a').count() >= 25, 'the footer does not list the tools');
    assert.equal(await foot.locator('.sh-fmail').getAttribute('href'), 'mailto:hello@altahascreener.in');
    assert.match(await foot.locator('.sh-fbase').innerText(), /not investment advice/);
    assert.match(await foot.locator('.sh-fbase').innerText(), new RegExp(String(new Date().getFullYear())));
    await foot.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'desktop.png') });
    // A link opens its tool in place.
    await foot.locator('a', { hasText: 'Stock picks' }).click();
    await page.locator('#view-ideas').waitFor({ state: 'visible' });
    assert.match(page.url(), /#research\/ideas/);
    await page.waitForFunction(() => window.scrollY < 50, null, { timeout: 3000 })
      .catch(() => assert.fail('the reader was left at the bottom of the new page'));
    await foot.locator('a', { hasText: 'Watchlists' }).click();
    await page.locator('#view-watchlists').waitFor({ state: 'visible' });
    assert.equal(await page.locator('footer.sh-footer').count(), 1, 'the footer was built twice');
    assert.deepEqual(errors, [], errors.join('\n'));
    await context.close();

    // Off the homepage a link is an ordinary link back to it.
    ({ context, page, errors } = await open(browser, { width: 1366, height: 900 }, 'pro.html'));
    await page.locator('footer.sh-footer').waitFor();
    assert.equal(await page.locator('footer.sh-footer a', { hasText: 'Stock picks' }).getAttribute('href'), 'index.html#research/ideas');
    assert.equal(await page.locator('footer.sh-footer a', { hasText: 'Daily policy brief' }).getAttribute('href'), 'brief.html');
    // The pages a search engine reads are linked from every page, so a crawler finds them.
    assert.equal(await page.locator('footer.sh-footer a', { hasText: 'All stocks' }).getAttribute('href'), '/stocks');
    assert.equal(await page.locator('footer.sh-footer a', { hasText: 'in a minute' }).getAttribute('href'), '/today');
    assert.deepEqual(errors, [], errors.join('\n'));
    await context.close();

    // The two full-screen desks lay out their own viewport.
    for (const file of ['wealth.html', 'advisors.html']) {
      ({ context, page, errors } = await open(browser, { width: 1366, height: 900 }, file));
      await page.locator('.sh-chrome').waitFor();
      assert.equal(await page.locator('footer.sh-footer').count(), 0, `${file} grew a footer`);
      await context.close();
    }

    // A 390px phone.
    ({ context, page, errors } = await open(browser, { width: 390, height: 800 }, 'index.html'));
    const pf = page.locator('footer.sh-footer');
    await pf.waitFor();
    // The page keeps growing as its parts arrive; go to the end until it is the end.
    await page.waitForFunction(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
      const base = document.querySelector('.sh-fbase').getBoundingClientRect();
      const bar = document.querySelector('.ux-bottom');
      return base.bottom <= window.innerHeight && (!bar || base.bottom <= bar.getBoundingClientRect().top + 1);
    }, null, { timeout: 8000 }).catch(() => assert.fail('the last line of the footer sits under the bottom bar'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, 'the footer scrolls sideways on a phone');
    for (const b of await pf.locator('.sh-fcol a').evaluateAll(ns => ns.map(n => n.getBoundingClientRect().right))) {
      assert.ok(b <= 390, 'a footer link runs off a phone screen');
    }
    await page.screenshot({ path: path.join(out, 'phone.png') });
    assert.deepEqual(errors, [], errors.join('\n'));
    await context.close();
    console.log('footer: on the public pages, off the desks, links open in place, mail address, phone layout all hold');
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); console.log('::error title=Footer::' + String(e.message).split('\n')[0]); process.exit(1); });
