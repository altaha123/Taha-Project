/* One computer, more than one account.
 *
 * Signed in, the list in the browser is a copy of the ACCOUNT's portfolio. It
 * used to outlive the session it came from: signing out left it on the screen
 * for whoever sat down next, and the next account to sign in with nothing
 * saved was handed it by the rule written for a list typed signed out ("an
 * empty account takes what this browser holds"). One reader's holdings ended
 * up saved under another reader's email, and in that reader's daily email.
 *
 * Nothing threw and every screen looked right, so each step is driven here in
 * a real browser, against accounts that are kept apart the way the API keeps
 * them: by the session token.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');
const PORT = 8773;
const TOKEN = 'altaha-session-v1', DRAFT = 'altaha-portfolio-draft-v1';

const server = http.createServer((req, res) => {
  const name = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!name.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' :
      name.endsWith('.html') ? 'text/html' : 'application/octet-stream');
    res.end(fs.readFileSync(name));
  } catch (e) { res.writeHead(404).end(); }
});

const SESSIONS = { 'tok-asha': 'asha@example.com', 'tok-asha-2': 'asha@example.com',
                   'tok-meera': 'meera@example.com', 'tok-ravi': 'ravi@example.com' };

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const errors = [];
  let accounts = {}, expired = new Set(), slowMe = null;
  const of = email => accounts[email] || (accounts[email] = { holdings: [], puts: 0 });
  const held = email => of(email).holdings.map(h => h.symbol).join();

  /* One browser: a fresh context with one tab, and the API behind it. */
  async function browserOf() {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const token = (req.headers()['authorization'] || '').replace(/^Bearer /, '');
      const email = expired.has(token) ? '' : SESSIONS[token];
      if (p === '/auth/me') {
        if (slowMe) await slowMe;
        return email ? route.fulfill({ json: { email: email, digest_opt_in: true } })
                     : route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
      }
      if (p === '/auth/logout') return route.fulfill({ json: { ok: true } });
      if (p === '/me/portfolio') {
        if (!email) return route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
        const acct = of(email);
        if (req.method() === 'PUT') {
          acct.holdings = JSON.parse(req.postData() || '{}').holdings || [];
          acct.puts += 1;
          return route.fulfill({ json: { saved: acct.holdings.length, rejected: [], holdings: acct.holdings } });
        }
        return route.fulfill({ json: { holdings: acct.holdings } });
      }
      if (url.hostname !== '127.0.0.1') {
        const kind = req.resourceType();
        if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
        return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack)));
    page.on('dialog', d => d.accept(d.type() === 'prompt' ? d.defaultValue() : undefined));
    page.portfolio = async () => {
      await page.goto(`http://127.0.0.1:${PORT}/?go=portfolio`, { waitUntil: 'domcontentloaded' });
      await page.locator('#pf_rows .pf_sym').first().waitFor();
    };
    /* The sign-in page: the only place a reader signs in or out, and a page
       that does not load the portfolio's own script. */
    page.signinPage = () => page.goto(`http://127.0.0.1:${PORT}/signin.html`, { waitUntil: 'domcontentloaded' });
    page.signOut = async () => {
      await page.signinPage();
      await page.evaluate(() => window.AltahaAuth.signOut());
    };
    page.signIn = async token => {
      await page.signinPage();
      await page.evaluate(([k, t]) => localStorage.setItem(k, t), [TOKEN, token]);
    };
    page.symbols = () => page.locator('#pf_rows .pf_sym').evaluateAll(ns => ns.map(n => n.value).filter(Boolean));
    page.type = async (sym, qty) => {
      const n = await page.locator('#pf_rows .pfrow').count();
      const blank = await page.locator('#pf_rows .pf_sym').last().inputValue() === '';
      if (!blank) await page.locator('#pf_addrow').click();
      const i = blank ? n - 1 : n;
      await page.locator('#pf_rows .pf_sym').nth(i).fill(sym);
      await page.locator('#pf_rows .pf_qty').nth(i).fill(String(qty));
    };
    page.note = () => page.locator('#pf_note').innerText();
    page.who = () => page.evaluate(() => { const u = window.AltahaAuth.user(); return u ? u.email : ''; });
    return page;
  }
  const until = async (fn, what) => {
    for (let i = 0; i < 60; i++) { if (await fn()) return; await new Promise(r => setTimeout(r, 150)); }
    assert.fail(what);
  };
  const settle = () => new Promise(r => setTimeout(r, 2600));   // longer than the save delay

  try {
    /* ── 1. Sign out, and somebody else signs in ─────────────────────────── */
    let page = await browserOf();
    await page.signIn('tok-asha');
    await page.portfolio();
    await page.type('HDFCBANK', 10);
    await until(() => held('asha@example.com') === 'HDFCBANK', 'a holding typed while signed in never reached the account');

    await page.signOut();
    await page.signIn('tok-meera');
    // The first thing Meera's screen draws must not be Asha's holdings, even
    // before the server has said whose session this is.
    let release; slowMe = new Promise(r => { release = r; });
    await page.portfolio();
    assert.deepEqual(await page.symbols(), [], 'the next account was shown the last account\'s portfolio');
    release(); slowMe = null;
    await until(async () => (await page.who()) === 'meera@example.com', 'the page never learned who was signed in');
    await settle();
    assert.deepEqual(await page.symbols(), [], 'the last account\'s portfolio came back onto the screen');
    assert.equal(held('meera@example.com'), '', 'one account\'s portfolio was saved into another account');
    assert.equal(of('meera@example.com').puts, 0, 'an account that changed nothing was written to');
    assert.equal(held('asha@example.com'), 'HDFCBANK', 'the first account lost its portfolio');

    // Meera's own list goes to Meera's account and nowhere else.
    await page.type('INFY', 5);
    await until(() => held('meera@example.com') === 'INFY', 'the second account could not save its own portfolio');
    assert.equal(held('asha@example.com'), 'HDFCBANK');

    // Asha comes back to the same browser: her list, not Meera's, and her
    // account is not overwritten with what was on the screen.
    await page.signOut();
    await page.signIn('tok-asha');
    await page.portfolio();
    await until(async () => (await page.symbols()).join() === 'HDFCBANK', 'the first account did not get its own portfolio back');
    await settle();
    assert.equal(held('asha@example.com'), 'HDFCBANK', 'the first account was overwritten by the second account\'s list');
    assert.equal(held('meera@example.com'), 'INFY');

    /* ── 2. Signed out, an account's list is not on the screen ───────────── */
    await page.signOut();
    await page.portfolio();
    assert.deepEqual(await page.symbols(), [], 'a signed-out screen still showed the account\'s portfolio');
    assert.equal(await page.evaluate(k => localStorage.getItem(k), DRAFT), null,
      'the account\'s portfolio was left in the browser after signing out');
    assert.match(await page.note(), /signed out/i, 'the list vanished with nothing saying why');
    assert.equal(held('asha@example.com'), 'HDFCBANK', 'signing out emptied the account');

    /* ── 3. A list typed signed out still goes to the account that signs in ─ */
    await page.type('TCS', 3);
    await page.signIn('tok-ravi');
    await page.portfolio();
    await until(() => held('ravi@example.com') === 'TCS', 'a list typed signed out was not kept on signing in');
    assert.deepEqual(await page.symbols(), ['TCS']);
    await page.context().close();

    /* ── 4. A new session lands on top of a live one (an emailed link) ───── */
    accounts = {};
    page = await browserOf();
    await page.signIn('tok-asha');
    await page.portfolio();
    await page.type('HDFCBANK', 10);
    await until(() => held('asha@example.com') === 'HDFCBANK', 'setup: not saved');
    await page.signIn('tok-ravi');                       // no sign-out in between
    await page.portfolio();
    await until(async () => (await page.who()) === 'ravi@example.com', 'the page never learned who was signed in');
    await until(async () => (await page.symbols()).length === 0, 'another account\'s portfolio stayed on the screen');
    await settle();
    assert.equal(held('ravi@example.com'), '', 'a session that replaced another inherited its portfolio');
    assert.equal(of('ravi@example.com').puts, 0);
    assert.match(await page.note(), /another account/i, 'the list vanished with nothing saying why');
    assert.equal(held('asha@example.com'), 'HDFCBANK');

    // Pressing Save in the moment before the page knows whose session it is
    // must not send a list another account left here.
    await page.signIn('tok-asha');
    await page.portfolio();
    await until(async () => (await page.symbols()).join() === 'HDFCBANK', 'setup: not loaded');
    await page.signIn('tok-meera');
    slowMe = new Promise(r => { release = r; });
    await page.portfolio();
    if ((await page.symbols()).length) await page.locator('#pf_save').click();
    await new Promise(r => setTimeout(r, 400));
    assert.equal(of('meera@example.com').puts, 0, 'Save sent another account\'s list before the sign-in was checked');
    release(); slowMe = null;
    await until(async () => (await page.symbols()).length === 0, 'another account\'s portfolio stayed on the screen');
    await settle();
    assert.equal(held('meera@example.com'), '');
    await page.context().close();

    /* ── 5. A session that lapses does not cost an unsent change ─────────── */
    accounts = {};
    page = await browserOf();
    await page.signIn('tok-asha');
    await page.portfolio();
    await page.type('HDFCBANK', 10);
    await until(() => held('asha@example.com') === 'HDFCBANK', 'setup: not saved');
    await page.signinPage();
    expired.add('tok-asha');                             // the session ends on the server
    await page.evaluate(k => {                           // …with an edit that never left this browser
      const d = JSON.parse(localStorage.getItem(k)); d.rows[0].qty = '55'; localStorage.setItem(k, JSON.stringify(d));
    }, DRAFT);
    await page.portfolio();
    await until(async () => (await page.who()) === '' && !(await page.evaluate(k => localStorage.getItem(k), TOKEN)),
      'an expired session was not cleared');
    assert.deepEqual(await page.symbols(), ['HDFCBANK'], 'an unsent change was thrown away when the session lapsed');
    await page.signIn('tok-asha-2');
    await page.portfolio();
    await until(() => of('asha@example.com').holdings[0].qty === 55, 'the unsent change never reached its own account');

    // The same lapse with nothing unsent: the account has it all, so it goes.
    await page.signinPage();
    expired.add('tok-asha-2');
    await page.portfolio();
    await until(async () => (await page.symbols()).length === 0, 'a lapsed session left the account\'s portfolio on the screen');
    assert.match(await page.note(), /signed out/i);
    assert.equal(held('asha@example.com'), 'HDFCBANK');
    await page.context().close();

    /* ── 6. Signing out in one tab empties the other ─────────────────────── */
    accounts = {}; expired = new Set();
    page = await browserOf();
    await page.signIn('tok-asha');
    await page.portfolio();
    await page.type('HDFCBANK', 10);
    await until(() => held('asha@example.com') === 'HDFCBANK', 'setup: not saved');
    const other = await page.context().newPage();
    await other.goto(`http://127.0.0.1:${PORT}/signin.html`, { waitUntil: 'domcontentloaded' });
    await other.evaluate(() => window.AltahaAuth.signOut());
    await until(async () => (await page.symbols()).length === 0, 'a tab left open kept showing the portfolio after sign-out');
    // Nothing the open tab does afterwards may put the list back for the next account.
    await page.locator('#pf_addrow').click();
    await other.evaluate(([k, t]) => localStorage.setItem(k, t), [TOKEN, 'tok-meera']);
    await page.portfolio();
    await until(async () => (await page.who()) === 'meera@example.com', 'the page never learned who was signed in');
    await settle();
    assert.equal(held('meera@example.com'), '', 'a tab left open handed the portfolio to the next account');
    await page.context().close();

    /* ── 7. A portfolio saved by name belongs to the account that named it ── */
    accounts = {};
    page = await browserOf();
    await page.signIn('tok-asha');
    await page.portfolio();
    await page.type('HDFCBANK', 10);
    await until(() => held('asha@example.com') === 'HDFCBANK', 'setup: not saved');
    await until(async () => (await page.who()) === 'asha@example.com', 'setup: not signed in');
    await page.locator('#pf_save').click();              // the prompt is accepted with its default name
    const names = () => page.locator('#pf_saved option').evaluateAll(os => os.map(o => o.value).filter(Boolean));
    await until(async () => (await names()).length === 1, 'the named portfolio was not saved');
    await page.signOut();
    await page.portfolio();
    assert.deepEqual(await names(), [], 'a signed-out screen offered an account\'s saved portfolio');
    await page.signIn('tok-meera');
    await page.portfolio();
    await until(async () => (await page.who()) === 'meera@example.com', 'the page never learned who was signed in');
    assert.deepEqual(await names(), [], 'one account was offered a portfolio another account saved');
    await page.signOut();
    await page.signIn('tok-asha');
    await page.portfolio();
    await until(async () => (await names()).length === 1, 'the account that named a portfolio could not find it again');
    await page.context().close();

    assert.deepEqual(errors, [], errors.join('\n'));
    console.log('portfolio accounts: a portfolio stays with its account through sign-out, a second account, a lapsed session and a second tab');
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); console.log('::error title=Portfolio accounts::' + String(e.message).split('\n')[0]); process.exit(1); });
