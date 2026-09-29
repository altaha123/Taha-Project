/* Altaha Pro in a real Chromium: the waitlist page, the header link, and
   saved screens in the query screener. No live calls.

   What this is actually guarding:
     · THE WAITLIST SENDS WHAT IT SAYS. The plan the reader picked and the
       page they came from reach POST /pro/waitlist; a signed-in reader's
       account address is used, with no email box to fill in.
     · A REFUSAL READS AS A SENTENCE and the button comes back: a bad address
       is caught before sending, and a server "too many" is shown as written.
     · THE PAGE PROMISES NOTHING IT CANNOT KEEP: it says nothing is charged.
     · PRO IS REACHABLE: a header link on desktop, the menu on a small phone.
     · SAVED SCREENS WORK SIGNED OUT, move to the account on sign-in, and
       delete through the API (a DELETE the CORS allow-list must permit).
     · phone width, no horizontal page scroll. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/pro');
fs.mkdirSync(output, { recursive: true });
const fx = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/query.json'), 'utf8'));

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

async function wire(context, state) {
  await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url());
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') {
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    if (u.pathname === '/auth/me') {
      return state.user ? route.fulfill({ json: state.user }) : route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
    }
    if (u.pathname === '/pro/waitlist') {
      state.joins.push({ body: JSON.parse(req.postData() || '{}'), auth: req.headers()['authorization'] || null });
      if (state.refuse) return route.fulfill({ status: 429, json: { detail: 'That is a lot of sign-ups from one place. Try again in an hour.' } });
      return route.fulfill({ json: { joined: true, already: false, signed_in: !!state.user } });
    }
    if (u.pathname === '/me/screens' && req.method() === 'GET') return route.fulfill({ json: { screens: state.screens } });
    if (u.pathname === '/me/screens' && req.method() === 'PUT') {
      const b = JSON.parse(req.postData() || '{}');
      state.puts.push(b);
      state.screens = [{ id: state.screens.length + 1, name: b.name, query: b.query }]
        .concat(state.screens.filter(s => s.name !== b.name));
      return route.fulfill({ json: { screen: state.screens[0], screens: state.screens } });
    }
    const del = u.pathname.match(/^\/me\/screens\/(\d+)$/);
    if (del && req.method() === 'DELETE') {
      state.deletes.push(+del[1]);
      state.screens = state.screens.filter(s => s.id !== +del[1]);
      return route.fulfill({ json: { screens: state.screens } });
    }
    if (u.pathname === '/fundamentals/query/fields') return route.fulfill({ json: fx.fields });
    if (u.pathname === '/fundamentals/query') {
      const s = u.searchParams;
      const hit = fx.queries[[s.get('q'), s.get('sort') || '', s.get('order') || ''].join('|')];
      state.ran.push(s.get('q'));
      return hit ? route.fulfill({ status: hit.status, json: hit.body }) : route.fulfill({ status: 500, json: { detail: 'no fixture' } });
    }
    return route.fulfill({ json: { available: false, rows: [], items: [] } });
  });
}

function fresh() { return { user: null, joins: [], puts: [], deletes: [], screens: [], ran: [], refuse: false }; }

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];

  // ── The waitlist, signed out ────────────────────────────────────────────
  {
    const state = fresh();
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await wire(context, state);
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + '/pro.html?from=header', { waitUntil: 'load' });
    await page.evaluate(() => { window.__t = []; window.AltahaTrack = (n, p) => window.__t.push([n, p]); });
    assert.match(await page.locator('#pro-card').innerText(), /Nothing is charged today/);
    assert.match(await page.locator('#pro-card').innerText(), /₹1,999/);

    // A bad address is caught before anything is sent.
    await page.locator('#pro-email').fill('not-an-email');
    await page.locator('#pro-go').click();
    assert.match(await page.locator('#pro-msg').innerText(), /does not look like an email/);
    assert.equal(state.joins.length, 0);

    // The plan picked and the page it came from are what is sent.
    await page.locator('label.pro-plan', { hasText: '₹249' }).click();
    await page.locator('#pro-email').fill('reader@example.com');
    await page.locator('#pro-go').click();
    await page.locator('.pro-done').waitFor();
    assert.deepEqual(state.joins[0].body, { email: 'reader@example.com', source: 'header', plan: 'monthly' });
    assert.match(await page.locator('.pro-done').innerText(), /reader@example\.com/);
    assert.match(await page.locator('.pro-done').innerText(), /monthly/);
    assert.deepEqual((await page.evaluate(() => window.__t)).filter(t => t[0] === 'pro_waitlist_joined'),
      [['pro_waitlist_joined', { from: 'header', signed_in: false }]]);
    await page.screenshot({ path: path.join(output, 'waitlist-joined.png') });
    await context.close();
  }

  // ── A refusal reads as a sentence, and the button comes back ────────────
  {
    const state = fresh(); state.refuse = true;
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await wire(context, state);
    const page = await context.newPage();
    await page.goto(base + '/pro.html', { waitUntil: 'load' });
    await page.locator('#pro-email').fill('reader@example.com');
    await page.locator('#pro-go').click();
    await page.waitForFunction(() => /sign-ups from one place/.test(document.getElementById('pro-msg').textContent));
    assert.equal(await page.locator('#pro-go').isDisabled(), false);
    assert.equal(state.joins[0].body.source, 'direct');
    await context.close();
  }

  // ── Signed in: the account address, no email box ────────────────────────
  {
    const state = fresh(); state.user = { id: 7, email: 'member@example.com' };
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'tok-123'));
    await wire(context, state);
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + '/pro.html?from=story', { waitUntil: 'load' });
    await page.waitForFunction(() => !document.getElementById('pro-signedin').hidden);
    assert.match(await page.locator('#pro-signedin').innerText(), /member@example\.com/);
    assert.equal(await page.locator('#pro-email').isVisible(), false);
    await page.locator('#pro-go').click();
    await page.locator('.pro-done').waitFor();
    assert.equal(state.joins[0].auth, 'Bearer tok-123');
    assert.equal(state.joins[0].body.email, undefined, 'the account address is the server’s to use');
    assert.equal(state.joins[0].body.source, 'story');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.ok(overflow <= 1, 'no sideways scroll on a phone: ' + overflow);
    await page.screenshot({ path: path.join(output, 'waitlist-phone.png'), fullPage: true });
    await context.close();
  }

  // ── Saved screens: signed out, then signed in ───────────────────────────
  {
    const state = fresh();
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await wire(context, state);
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + '/#research/query', { waitUntil: 'load' });
    await page.locator('#qs-q').waitFor();
    // The header carries Pro on a desktop.
    assert.equal(await page.locator('#sh-pro').isVisible(), true);
    assert.match(await page.locator('#sh-pro').getAttribute('href'), /pro\.html\?from=header/);

    // Nothing to save yet: say so instead of saving an empty screen.
    await page.locator('#qs-save').click();
    assert.match(await page.locator('#qs-savemsg').innerText(), /Write or pick a query first/);

    await page.locator('#qs-q').fill('ROCE > 20');
    await page.locator('#qs-save').click();
    await page.locator('#qs-savename').fill('High ROCE');
    await page.locator('#qs-savego').click();
    await page.locator('#qs-saved .qs-chip', { hasText: 'High ROCE' }).waitFor();
    assert.match(await page.locator('#qs-saved').innerText(), /Sign in to keep them on every device/);
    const local = await page.evaluate(() => JSON.parse(localStorage.getItem('altaha.query.saved')));
    assert.equal(local[0].name, 'High ROCE');
    assert.equal(local[0].query, 'ROCE > 20');

    // A saved chip loads and runs its query.
    await page.locator('#qs-q').fill('');
    await page.locator('#qs-saved .qs-chip', { hasText: 'High ROCE' }).click();
    await page.waitForFunction(() => document.getElementById('qs-q').value === 'ROCE > 20');
    await page.waitForFunction(() => /companies match/.test(document.getElementById('qs-out').textContent));
    assert.ok(state.ran.includes('ROCE > 20'));

    // Signing in moves the browser's screens to the account, once.
    state.user = { id: 7, email: 'member@example.com' };
    await page.evaluate(() => { localStorage.setItem('altaha-session-v1', 'tok-123'); window.AltahaAuth.refresh(); });
    await page.waitForFunction(() => !/Sign in to keep/.test(document.getElementById('qs-saved').textContent));
    assert.deepEqual(state.puts, [{ name: 'High ROCE', query: 'ROCE > 20' }]);
    assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('altaha.query.saved'))), []);
    assert.equal(await page.locator('#qs-saved .qs-chip').count(), 1);

    // Deleting goes to the API.
    await page.locator('#qs-saved .qs-sdel').first().click();
    await page.waitForFunction(() => document.getElementById('qs-saved').hidden);
    assert.deepEqual(state.deletes, [1]);
    await context.close();
  }

  // ── Phones: in the header at 390px, in the menu at 320px ────────────────
  for (const width of [390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });
    await wire(context, fresh());
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack || e)));
    await page.goto(base + '/', { waitUntil: 'load' });
    await page.locator('#sh-burger').waitFor();
    const overflowTop = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.ok(overflowTop <= 1, width + 'px: the header row fits: ' + overflowTop);
    if (width === 390) {
      assert.equal(await page.locator('#sh-pro').isVisible(), true, 'room for Pro beside Sign in at 390px');
      await page.screenshot({ path: path.join(output, 'header-390.png') });
      await context.close();
      continue;
    }
    assert.equal(await page.locator('#sh-pro').isVisible(), false, 'no room in the header row at 320px');
    await page.locator('#sh-burger').click();
    await page.locator('#sh-drawer .sh-dpro').waitFor({ state: 'visible' });
    assert.match(await page.locator('#sh-drawer .sh-dpro').getAttribute('href'), /pro\.html\?from=menu/);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.ok(overflow <= 1, 'no sideways scroll: ' + overflow);
    await context.close();
  }

  const relevant = errors.filter(e => /(pro|query|shell|portfolio-story)\b/.test(e) && !/Failed to load resource/.test(e));
  assert.deepEqual(relevant, []);
  await browser.close();
  server.close();
  console.log('pro browser checks passed');
})().catch(e => { console.error(e); server.close(); process.exit(1); });
