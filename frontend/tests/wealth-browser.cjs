/* The Wealth desk in a real Chromium. No live calls: the book is the fixture
   backend/tests/make_wealth_fixture.py writes from the real compute_book().

   What this is actually guarding — every one of these fails silently:
     · SIGNED OUT, THE WAY IN WORKS: sign-in comes back here (?next=), and the
       sample desk opens with no account.
     · THE SAMPLE DESK IS WHOLE: five clients, the book value, a client's
       holdings with the recommended price beside the bought-at price, the
       fee's working step by step — and nothing in it reads NaN or undefined.
     · THE WHAT-IF AGREES WITH THE BILL: at the client's own terms the slider
       shows exactly the accrued fee, and moving it changes it by the
       arithmetic the server uses.
     · THE SAMPLE NEVER WRITES: a save on the sample desk sends nothing.
     · SETTING UP SENDS WHAT WAS TYPED: name, registration and fee terms.
     · EVERY WRITE SENDS WHAT THE FORM SAYS: a client, a buy linked to a call
       with its recommended price, one call booked for two clients, a
       settlement, an invoice marked paid.
     · WHAT A MANAGER TYPES IS TEXT: a client named with markup is shown as
       characters and never runs.
     · PRIVACY BLURS, AND IS REMEMBERED.
     · A CLIENT SEES THEIR OWN PORTFOLIO, READ-ONLY: no trade, settle or edit.
     · THE STATEMENT PRINTS THE CLIENT, not the page.
     · A PHONE FITS: no sideways scroll on any view.
     · A STATEMENT IS READ ON THE PAGE: an .xlsx holdings statement is read in
       the browser, its stocks matched by ISIN or name, and what is sent is
       stocks, quantities and prices — never the client's name or code from
       the file. A statement for somebody else says so before anything is saved.
     · EVERY PRICE CAN BE CORRECTED: a holding's average or recommended price,
       one purchase on its own, any ledger entry — each sends what was changed. */
const fs = require('node:fs'), path = require('node:path'),
      http = require('node:http'), assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve('frontend'), output = path.resolve('test-results/wealth');
fs.mkdirSync(output, { recursive: true });
const BOOK = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/wealth-demo.json'), 'utf8'));

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

function own(book) {
  const b = JSON.parse(JSON.stringify(book));
  b.demo = false;
  b.desk.display_name = 'Nadia Rahman';
  b.desk.firm = 'Rahman Wealth';
  return b;
}

function fresh(opts) {
  return Object.assign({ user: null, desk: false, shared: [], writes: [], book: own(BOOK) }, opts || {});
}

async function wire(context, state) {
  await context.addInitScript(() => {
    window.__printed = 0;
    window.print = () => { window.__printed++; };
  });
  if (state.user) {
    await context.addInitScript(() => { try { localStorage.setItem('altaha-session-v1', 'tok-test'); } catch (e) {} });
  }
  await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url()), m = req.method();
    if (u.hostname === '127.0.0.1') return route.continue();
    const type = req.resourceType();
    if (['font', 'image'].includes(type)) return route.abort();
    if (type === 'script' || type === 'stylesheet') {
      return route.fulfill({ body: '', contentType: type === 'script' ? 'text/javascript' : 'text/css' });
    }
    const p = u.pathname, body = () => JSON.parse(req.postData() || '{}');
    const authed = !!state.user && /Bearer tok-test/.test(req.headers()['authorization'] || '');
    if (p === '/auth/me') return authed ? route.fulfill({ json: state.user }) : route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
    if (p === '/wealth/demo') return route.fulfill({ json: BOOK });
    if (p === '/universe') return route.fulfill({ json: { rows: [{ s: 'TCS', n: 'Tata Consultancy Services Limited' }, { s: 'HAL', n: 'Hindustan Aeronautics' }] } });
    if (!p.startsWith('/wealth/')) return route.fulfill({ status: 404, json: { detail: 'not here' } });
    if (!authed) return route.fulfill({ status: 401, json: { detail: 'Sign in to use your wealth desk.' } });
    if (m !== 'GET') state.writes.push({ m, p, body: m === 'DELETE' && !req.postData() ? {} : body() });
    if (p === '/wealth/desk' && m === 'GET') {
      return route.fulfill({ json: { desk: state.desk ? state.book.desk : null, email: state.user.email, shared: state.shared.length,
        registrations: BOOK.vocab.registrations, default_terms: { share_pct: 20, hurdle_pct: 0, hurdle_type: 'hard', hwm: true,
        fixed_pct: 0, basis: 'total', gst_pct: 0, period: 'quarterly' }, fee_note: BOOK.fee_note } });
    }
    if (p === '/wealth/desk' && m === 'PUT') { state.desk = true; return route.fulfill({ json: { desk: state.book.desk } }); }
    if (p === '/wealth/book') return state.desk ? route.fulfill({ json: state.book }) : route.fulfill({ status: 403, json: { detail: 'Set up your wealth desk first.' } });
    if (p === '/wealth/shared') return route.fulfill({ json: { portfolios: state.shared } });
    if (p === '/wealth/clients' && m === 'POST') {
      const c = JSON.parse(JSON.stringify(state.book.clients[0]));
      Object.assign(c, { id: 99, name: body().name, code: 'C-099' });
      state.book.clients.push(c);
      return route.fulfill({ json: { client: c } });
    }
    if (/\/events$/.test(p) && m === 'PUT') return route.fulfill({ json: { changed: body().edits.length, warning: null } });
    if (/\/events\/\d+$/.test(p) && m === 'PUT') return route.fulfill({ json: { changed: 1, warning: null } });
    if (/\/holdings\/[^/]+$/.test(p)) return route.fulfill({ json: { changed: 1, warning: null } });
    if (p === '/wealth/isin') {
      const known = { INE263A01024: 'BEL', INE129A01019: 'GAIL', INE040A01034: 'HDFCBANK', INE009A01021: 'INFY', INE154A01025: 'ITC' };
      const map = {};
      body().isins.forEach(i => { if (known[i]) map[i] = known[i]; });
      return route.fulfill({ json: { map, missing: [] } });
    }
    if (/\/statement\/plan$/.test(p)) {
      const b = body();
      return route.fulfill({ json: { mode: b.mode, as_of: b.as_of, buy_date: b.buy_date, counts: { new: b.rows.length },
        items: b.rows.map(r => ({ symbol: r.symbol, status: 'new', include: true, have: null, want: { qty: r.qty, avg: r.avg, close: r.close },
          ops: [{ kind: 'buy', symbol: r.symbol, qty: r.qty, price: r.avg }], fix_avg: null, note: '' })) } });
    }
    if (/\/statement\/apply$/.test(p)) {
      const n = body().rows.length - (body().skip || []).length;
      return route.fulfill({ json: { added: n, corrected: 0, holdings: n, done: { new: n }, warning: null } });
    }
    if (/\/events$/.test(p)) return route.fulfill({ json: { ids: [501], added: 1, warning: null } });
    if (/\/settle$/.test(p)) return route.fulfill({ json: { settlement: { id: 77, amount: 11502.39, status: 'due' } } });
    if (/\/apply$/.test(p)) return route.fulfill({ json: { booked: body().fills.map((f, i) => ({ client_id: f.client_id, id: 600 + i })) } });
    if (/\/wealth\/settlements\/\d+$/.test(p)) return route.fulfill({ json: { settlement: { id: 1, status: body().status } } });
    if (p === '/wealth/recs' && m === 'POST') return route.fulfill({ json: { rec: Object.assign({}, state.book.recs[0], { id: 1 }) } });
    return route.fulfill({ json: { ok: true } });
  });
}

async function noSideways(page, label) {
  const sw = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(sw <= 0, `${label}: sideways scroll of ${sw}px on a phone`);
}

async function clean(page, label) {
  const bad = await page.evaluate(() => {
    const t = document.getElementById('wd').innerText;
    const m = t.match(/.{0,30}(NaN|undefined|Infinity|\[object Object\]).{0,30}/);
    return m ? m[0] : '';
  });
  assert.equal(bad, '', `${label}: "${bad}"`);
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  const errors = [];
  const watch = (page, label) => page.on('pageerror', e => errors.push(`${label}: ${e.message}`));

  try {
    // ── Signed out: the way in ─────────────────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const state = fresh();
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'landing');
      await page.goto(`${base}/wealth.html`);
      await page.waitForSelector('.wd-land');
      assert.equal(await page.getAttribute('.wd-land a[href^="signin.html"]', 'href'), 'signin.html?next=wealth.html');
      assert.ok(await page.$('a[href="wealth.html?demo=1"]'), 'the sample desk is offered');
      await page.screenshot({ path: `${output}/landing.png` });
      await ctx.close();
    }

    // ── The sample desk ────────────────────────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const state = fresh();
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'demo');
      await page.goto(`${base}/wealth.html?demo=1`);
      await page.waitForSelector('.wd-hero .wd-big');
      await page.waitForTimeout(1300);                                   // the count-up
      const big = await page.textContent('.wd-hero .wd-big');
      assert.ok(big.replace(/[^\d]/g, '') === String(Math.round(BOOK.totals.aum)), `book value shows ${big}`);
      assert.equal(await page.locator('.wd-cards .wd-card').count(), 5);
      assert.ok(await page.isVisible('.wd-demo'), 'the sample is labelled as a sample');
      await clean(page, 'overview');
      await page.screenshot({ path: `${output}/overview.png`, fullPage: true });

      // A client: one price a holding was bought at, and a logo beside each name.
      const ayesha = BOOK.clients[0];
      await page.click(`.wd-card[data-go="client/${ayesha.id}"]`);
      await page.waitForSelector('.wd-table');
      const head = await page.locator('.wd-table thead').innerText();
      assert.match(head, /AVG COST/i);
      assert.doesNotMatch(head, /RECOMMENDED|BOUGHT AT|STOP/i, 'the second price is back in the table');
      assert.equal(await page.locator('.wd-table thead th').count(), 8, 'the holdings table grew past eight columns');
      const first = ayesha.holdings[0];
      const row = await page.locator('.wd-table tbody tr').first().innerText();
      assert.ok(row.includes(first.symbol), row);
      assert.ok(row.replace(/[^\d]/g, '').includes(String(Math.round(first.avg))), `average cost in "${row}"`);
      assert.equal(await page.locator('.wd-table tbody tr .wd-logo').count(), ayesha.holdings.length + (ayesha.cash > 0.5 ? 1 : 0), 'a holding has no logo');
      assert.equal(await page.locator('.wd-table tbody tr').first().locator('.wd-logo i').innerText(), first.symbol.replace(/[^A-Z0-9]/g, '').slice(0, 2),
        'the initials under a logo are not the stock’s');
      assert.deepEqual(await page.locator('.wd-acts .wd-act').allInnerTexts().then(a => a.map(x => x.trim())), ['Add stocks', 'Sell', 'Money in / out', 'More']);
      await clean(page, 'client');
      await page.screenshot({ path: `${output}/client.png`, fullPage: true });

      // The fee, step by step, and the what-if agrees with it.
      await page.click('[data-ctab="fees"]');
      await page.waitForSelector('.wd-steps');
      assert.equal(await page.locator('.wd-step').count(), ayesha.fee.steps.length);
      const wiTotal = () => page.textContent('[data-out="total"]');
      const asInr = v => '₹' + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
      assert.equal(await wiTotal(), Math.abs(ayesha.fee.total) >= 1000 ? asInr(ayesha.fee.total) : await wiTotal());
      await page.locator('[data-wi="share"]').fill('30');
      const want = await page.evaluate(([w, t]) => window.AltahaWealth.feeMath(Object.assign({}, t, { share_pct: 30 }),
        w.level, w.base, w.capital_days, w.days).total, [ayesha.fee.whatif, ayesha.terms]);
      assert.equal(await wiTotal(), asInr(want), 'the what-if runs the server’s arithmetic');
      assert.ok(want > ayesha.fee.total, 'a larger share is a larger fee');
      await clean(page, 'fees');
      await page.screenshot({ path: `${output}/fees.png`, fullPage: true });

      // The sample never writes.
      await page.click('.wd-acts [data-act="settle"]');
      await page.waitForSelector('#wd-modal[open]');
      await page.click('#wd-modal [type=submit]');
      await page.waitForSelector('#wd-toast.on');
      assert.match(await page.textContent('#wd-toast'), /sample desk/i);
      assert.equal(state.writes.length, 0, 'the sample desk sent a write');

      // Recommendations and commission draw.
      await page.click('.wd-tab[data-go="calls"]');
      await page.waitForSelector('.wd-rec');
      assert.ok(await page.locator('.wd-rec').count() >= 5);
      await clean(page, 'calls');
      await page.click('.wd-tab[data-go="fees"]');
      await page.waitForSelector('.wd-sens');
      await clean(page, 'commission');
      await page.screenshot({ path: `${output}/commission.png`, fullPage: true });

      // The statement prints the client.
      await page.goto(`${base}/wealth.html?demo=1#client/${ayesha.id}`);
      await page.waitForSelector('.wd-acts [data-act="client-more"]');
      await page.click('.wd-acts [data-act="client-more"]');
      await page.click('#wd-modal [data-act="m-statement"]');
      await page.waitForFunction(() => window.__printed > 0);
      const printed = await page.textContent('#wd-print');
      assert.ok(printed.includes(ayesha.name) && printed.includes(first.symbol), 'the statement carries the client and holdings');

      // Privacy blurs, and is remembered.
      await page.click('.wd-bar [data-act="privacy"]');
      assert.ok(await page.evaluate(() => document.getElementById('wd').classList.contains('wd-private')));
      const blur = await page.evaluate(() => getComputedStyle(document.querySelector('.wd-hero .pv')).filter);
      assert.match(blur, /blur/);
      await page.reload();
      await page.waitForSelector('.wd-hero');
      assert.ok(await page.evaluate(() => document.getElementById('wd').classList.contains('wd-private')), 'privacy is remembered');
      await ctx.close();
    }

    // ── Setting up a desk, and every write ─────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const state = fresh({ user: { email: 'nadia@example.com' } });
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'setup');
      await page.goto(`${base}/wealth.html`);
      await page.waitForSelector('[data-form="setup"]');
      await page.fill('[name=display_name]', 'Nadia Rahman');
      await page.fill('[name=firm]', 'Rahman Wealth');
      await page.selectOption('[name=reg_kind]', 'pms');
      await page.fill('[name=registration]', 'INP12');
      await page.click('[data-form="setup"] [type=submit]');
      assert.match(await page.textContent('[data-form="setup"] .wd-err'), /INP followed by nine digits/);
      await page.fill('[name=registration]', 'INP000001234');
      await page.click('[data-form="setup"] [type=submit]');
      await page.waitForSelector('[name=t_share_pct]');
      await page.fill('[name=t_share_pct]', '25');
      await page.fill('[name=t_hurdle_pct]', '8');
      assert.match(await page.textContent('[data-example]'), /₹10,00,000/);
      await page.click('[data-form="setup"] [type=submit]');
      await page.waitForSelector('#wd-modal[open]');                    // the first client
      const put = state.writes.find(w => w.p === '/wealth/desk' && w.m === 'PUT');
      assert.equal(put.body.display_name, 'Nadia Rahman');
      assert.equal(put.body.reg_kind, 'pms');
      assert.equal(put.body.registration, 'INP000001234');
      assert.equal(put.body.terms.share_pct, 25);
      assert.equal(put.body.terms.hurdle_pct, 8);
      assert.equal(put.body.terms.hwm, true);

      // A client named with markup is text.
      await page.fill('#wd-modal [name=name]', '<img src=x onerror="window.__pwned=1">Zara');
      await page.fill('#wd-modal [name=email]', 'zara@example.com');
      await page.check('#wd-modal [name=portal]');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const add = state.writes.find(w => w.p === '/wealth/clients');
      assert.equal(add.body.email, 'zara@example.com');
      assert.equal(add.body.portal, true);
      assert.equal(add.body.terms.share_pct, BOOK.desk.terms.share_pct, 'a new client starts on the desk’s terms');
      await page.waitForFunction(() => location.hash === '#client/99');
      await page.waitForSelector('.wd-cid h2');
      assert.ok((await page.textContent('.wd-cid h2')).includes('<img'), 'the markup is shown as characters');
      assert.equal(await page.evaluate(() => window.__pwned), undefined, 'markup in a client name ran');

      // A single buy, from the More menu, linked to an open call.
      const c1 = state.book.clients[0];
      const rec = state.book.recs.find(r => r.status === 'open' && r.action === 'buy');
      await page.goto(`${base}/wealth.html#client/${c1.id}`);
      await page.waitForSelector('.wd-acts [data-act="add-event"]');

      // A field tapped the moment the form opens keeps the cursor. A deferred
      // focus once pulled it back to the first box, and on CI's slower
      // machine the quantity landed in the stock symbol ("RELIANCE10").
      await page.evaluate(() => {
        document.querySelector('.wd-acts [data-act="add-event"]').click();
        document.querySelector('#wd-modal [name=qty]').focus();
      });
      await page.waitForTimeout(150);
      await page.keyboard.type('10');
      assert.deepEqual(await page.evaluate(() => ({ symbol: document.querySelector('#wd-modal [name=symbol]').value,
        qty: document.querySelector('#wd-modal [name=qty]').value })), { symbol: '', qty: '10' }, 'typing went to another field');
      await page.click('#wd-modal [data-close]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      await page.click('.wd-acts [data-act="client-more"]');
      await page.click('#wd-modal [data-act="m-event"][data-kind="buy"]');
      await page.waitForSelector('#wd-modal [name=symbol]');
      assert.equal(await page.locator('#wd-modal [name=rec_price]').count(), 0, 'the trade form asks for a second price');
      assert.equal(await page.locator('#wd-modal .ev-rec').isVisible(), false, 'the call field shows before there is a call to link');
      await page.fill('#wd-modal [name=symbol]', rec.symbol);
      await page.dispatchEvent('#wd-modal [name=symbol]', 'input');
      await page.fill('#wd-modal [name=qty]', '10');
      await page.fill('#wd-modal [name=price]', '1,234.50');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const ev = state.writes.find(w => /\/events$/.test(w.p)).body.events[0];
      assert.equal(ev.kind, 'buy');
      assert.equal(ev.symbol, rec.symbol);
      assert.equal(ev.price, '1234.50', 'commas are stripped before sending');
      assert.equal(String(ev.rec_id), String(rec.id), 'the open call is linked');
      assert.ok(!('rec_price' in ev), 'a second price was sent with the trade');

      // Many stocks in one go: typed, pasted from a spreadsheet, sent together.
      await page.goto(`${base}/wealth.html#client/${c1.id}`);
      await page.waitForSelector('.wd-acts [data-act="add-stocks"]');
      await page.click('.wd-acts [data-act="add-stocks"]');
      await page.waitForSelector('#wd-modal .wd-addrows');
      assert.equal(await page.locator('#wd-modal tr[data-row]').count(), 4, 'the form does not open with room for several stocks');
      assert.match(await page.locator('#wd-modal .wd-addrows thead').innerText(), /AVG COST/i);
      assert.doesNotMatch(await page.locator('#wd-modal').innerText(), /recommended/i);
      // An empty form says so, and sends nothing.
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => /at least one stock/.test(document.querySelector('#wd-modal .wd-err').textContent));
      const row = n => page.locator('#wd-modal tr[data-row]').nth(n);
      await row(0).locator('[data-f="symbol"]').fill('infy');
      await row(0).locator('[data-f="qty"]').fill('25');
      await row(0).locator('[data-f="avg"]').fill('1,540.50');
      // A row begun and not finished is named, not dropped.
      await row(1).locator('[data-f="symbol"]').fill('TCS');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => /Row 2 \(TCS\) needs a quantity/.test(document.querySelector('#wd-modal .wd-err').textContent));
      // Three rows copied from Excel, pasted into the second row, header and all.
      await row(1).locator('[data-f="symbol"]').focus();
      await page.evaluate(() => {
        const dt = new DataTransfer();
        dt.setData('text', 'Symbol\tQty\tAvg\nTCS\t12\t3305\nHDFCBANK\t40\t812.3\nITC\t100\t284\nSBIN\t30\t1086.5\n');
        document.activeElement.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      });
      assert.equal(await page.locator('#wd-modal tr[data-row]').count(), 5, 'pasted rows did not make room for themselves');
      assert.equal(await row(4).locator('[data-f="symbol"]').inputValue(), 'SBIN');
      assert.match(await page.locator('#wd-modal [data-total]').innerText(), /5 stocks ready to add/);
      await page.click('#wd-modal [data-more]');
      assert.equal(await page.locator('#wd-modal tr[data-row]').count(), 6);
      await row(5).locator('[data-del]').click();
      assert.equal(await page.locator('#wd-modal tr[data-row]').count(), 5);
      state.writes.length = 0;
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const many = state.writes.find(w => /\/statement\/apply$/.test(w.p));
      assert.ok(many, 'the stocks were not sent');
      assert.equal(state.writes.length, 1, 'adding five stocks took more than one request');
      assert.equal(many.body.mode, 'add');
      assert.deepEqual(many.body.rows, [
        { symbol: 'INFY', qty: '25', avg: '1540.50' }, { symbol: 'TCS', qty: '12', avg: '3305' },
        { symbol: 'HDFCBANK', qty: '40', avg: '812.3' }, { symbol: 'ITC', qty: '100', avg: '284' }, { symbol: 'SBIN', qty: '30', avg: '1086.5' }]);
      assert.equal(many.body.buy_date, many.body.as_of);
      state.writes.length = 0;

      // One call, two clients.
      await page.goto(`${base}/wealth.html#calls`);
      await page.waitForSelector(`.wd-rec [data-act="book-rec"][data-rid="${rec.id}"]`);
      await page.click(`.wd-rec [data-act="book-rec"][data-rid="${rec.id}"]`);
      await page.waitForSelector('#wd-modal .wd-pick');
      const picks = page.locator('#wd-modal .wd-pick');
      await picks.nth(0).locator('[data-amt]').fill('100000');
      await picks.nth(1).locator('[data-qty]').fill('7');
      assert.match(await page.textContent('#wd-modal [data-sum]'), /2 clients/);
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const apply = state.writes.find(w => /\/apply$/.test(w.p));
      assert.equal(apply.p, `/wealth/recs/${rec.id}/apply`);
      assert.equal(apply.body.fills.length, 2);
      assert.equal(apply.body.fills[0].amount, '100000');
      assert.equal(apply.body.fills[1].qty, '7');

      // Settle, and mark paid.
      await page.goto(`${base}/wealth.html#client/${c1.id}/fees`);
      await page.waitForSelector('.wd-receipt [data-act="settle"]');
      await page.click('.wd-receipt [data-act="settle"]');
      await page.waitForSelector('#wd-modal [name=amount]');
      await page.fill('#wd-modal [name=note]', 'INV-0042');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const st = state.writes.find(w => /\/settle$/.test(w.p));
      assert.equal(st.p, `/wealth/clients/${c1.id}/settle`);
      assert.equal(st.body.note, 'INV-0042');
      assert.equal(st.body.as_of, null, 'today is sent as today');
      await page.goto(`${base}/wealth.html#fees`);
      const due = state.book.commission.settlements.find(s => s.status === 'due');
      await page.waitForSelector(`[data-act="mark"][data-sid="${due.id}"]`);
      await page.click(`[data-act="mark"][data-sid="${due.id}"]`);
      await page.waitForSelector('#wd-modal [name=paid_on]');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const mk = state.writes.find(w => w.p === `/wealth/settlements/${due.id}`);
      assert.equal(mk.body.status, 'paid');
      assert.match(mk.body.paid_on, /^\d{4}-\d{2}-\d{2}$/);
      await ctx.close();
    }

    // ── A statement, and every correction ──────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const state = fresh({ user: { email: 'nadia@example.com', wealth_desk: true }, desk: true });
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'statement');
      const STMT = path.join(root, 'tests', 'fixtures', 'holdings-statement.xlsx');
      const c1 = state.book.clients[0];

      // Upload: read in the page, matched, reviewed, applied.
      await page.goto(`${base}/wealth.html#client/${c1.id}`);
      await page.waitForSelector('.wd-acts [data-act="add-stocks"]');
      await page.click('.wd-acts [data-act="add-stocks"]');
      await page.click('#wd-modal [data-act="upload"]');
      await page.setInputFiles('#wd-modal input[name=file]', STMT);
      await page.waitForSelector('#wd-modal .wd-plan tbody tr');
      assert.match(await page.textContent('#wd-modal .wd-warn'), /Priya Raman/, 'a statement for somebody else says so');
      assert.match(await page.textContent('#wd-modal .wd-mh'), /4 Nov 2026/, 'the statement’s own date is read');
      const plan = state.writes.find(w => /statement\/plan$/.test(w.p));
      assert.deepEqual(plan.body.rows.map(r => [r.symbol, r.qty, r.avg]),
        [['BEL', 120, 268.4], ['GAIL', 300, 171.25], ['HDFCBANK', 25, 1612], ['INFY', 18, 1745.5], ['ITC', 210, 432.1], ['TCS', 6, 3890]],
        'matched by ISIN, and by a name cut short');
      assert.equal(plan.body.as_of, '2026-11-04');
      await page.screenshot({ path: `${output}/statement-review.png` });
      await page.uncheck('#wd-modal [data-take="ITC"]');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const apply = state.writes.find(w => /statement\/apply$/.test(w.p));
      assert.deepEqual(apply.body.skip, ['ITC'], 'an unticked holding is left out');
      const sent = JSON.stringify(state.writes);
      assert.ok(!/Priya|1234567890/.test(sent), 'the client’s name or code from the statement was sent');

      // A holding's average cost.
      const h = c1.holdings[0];
      await page.waitForSelector(`.wd-table [data-act="edit-hold"][data-sym="${h.symbol}"]`);
      await page.click(`.wd-table [data-act="edit-hold"][data-sym="${h.symbol}"]`);
      await page.waitForSelector('#wd-modal [name=avg]');
      assert.equal(Number(await page.inputValue('#wd-modal [name=avg]')), h.avg);
      await page.fill('#wd-modal [name=avg]', '1,111.50');
      assert.equal(await page.locator('#wd-modal [name=rec]').count(), 0);
      assert.match(await page.textContent('#wd-modal [data-prev]'), /invested/);
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const hold = state.writes.find(w => /\/holdings\//.test(w.p));
      assert.equal(hold.p, `/wealth/clients/${c1.id}/holdings/${h.symbol}`);
      assert.deepEqual(hold.body, { avg: '1111.50' });

      // One purchase on its own.
      await page.click(`.wd-table [data-act="edit-hold"][data-sym="${h.symbol}"]`);
      await page.waitForSelector('#wd-modal [data-pane="each"]');
      await page.click('#wd-modal [data-pane="each"]');
      await page.fill('#wd-modal tr[data-eid] [data-f="qty"]', '400');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const each = state.writes.find(w => /\/events$/.test(w.p) && w.m === 'PUT');
      assert.equal(each.body.edits.length, 1);
      assert.equal(each.body.edits[0].qty, '400');
      assert.deepEqual(Object.keys(each.body.edits[0]).sort(), ['id', 'qty'], 'only what was changed is sent');

      // Any ledger entry.
      await page.goto(`${base}/wealth.html#client/${c1.id}/ledger`);
      const buy = c1.events.find(e => e.kind === 'buy');
      await page.waitForSelector(`[data-act="edit-event"][data-eid="${buy.id}"]`);
      await page.click(`[data-act="edit-event"][data-eid="${buy.id}"]`);
      await page.waitForSelector('#wd-modal [name=price]');
      assert.equal(Number(await page.inputValue('#wd-modal [name=price]')), buy.price, 'the entry opens as it is');
      assert.equal(await page.inputValue('#wd-modal [name=on_date]'), buy.on_date);
      await page.fill('#wd-modal [name=price]', '999');
      await page.click('#wd-modal [type=submit]');
      await page.waitForFunction(() => !document.getElementById('wd-modal').open);
      const one = state.writes.find(w => w.p === `/wealth/clients/${c1.id}/events/${buy.id}`);
      assert.equal(one.m, 'PUT');
      assert.equal(one.body.price, '999');
      assert.equal(one.body.symbol, buy.symbol);
      assert.ok(!('rec_price' in one.body), 'an edit sent a second price; what is stored must be left alone');

      // A new client, started from their statement.
      state.writes.length = 0;
      await page.click('.wd-bar [data-act="add-client"]');
      await page.setInputFiles('#wd-modal input[name=statement]', STMT);
      await page.waitForFunction(() => document.querySelector('#wd-modal [name=name]').value === 'Priya Raman');
      assert.equal(await page.inputValue('#wd-modal [name=since]'), '2026-11-04');
      await page.click('#wd-modal [type=submit]');
      await page.waitForSelector('#wd-modal .wd-plan tbody tr', { timeout: 10000 });
      assert.equal(state.writes.find(w => w.p === '/wealth/clients').body.name, 'Priya Raman');
      assert.equal(await page.locator('#wd-modal .wd-warn').count(), 0, 'the right client’s statement raises no warning');
      await ctx.close();
    }

    // ── A client's own view: read-only ─────────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const view = JSON.parse(JSON.stringify(BOOK.clients[1]));
      delete view.notes;
      const state = fresh({ user: { email: 'rohan@example.com' }, desk: false,
        shared: [{ desk: { display_name: 'Nadia Rahman', firm: 'Rahman Wealth', reg_short: 'SEBI PMS', registration: 'INP000001234' }, client: view }] });
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'portal');
      await page.goto(`${base}/wealth.html`);
      await page.waitForSelector('.wd-cid h2');
      assert.ok((await page.textContent('.wd-cid h2')).includes(view.name));
      assert.match(await page.textContent('#wd-view'), /read-only/);
      for (const a of ['add-event', 'add-stocks', 'client-more', 'settle', 'import', 'del-event', 'hold']) {
        assert.equal(await page.locator(`#wd-view [data-act="${a}"]`).count(), 0, `a client can ${a}`);
      }
      assert.equal(await page.locator('[data-ctab="profile"]').count(), 0);
      await page.click('[data-ctab="fees"]');
      await page.waitForSelector('.wd-steps');
      assert.equal(await page.locator('.wd-receipt [data-act="settle"]').count(), 0);
      await clean(page, 'portal');
      await page.screenshot({ path: `${output}/client-view.png`, fullPage: true });
      await ctx.close();
    }

    // ── The ways in: the Me menu follows the account, the door shows it ─
    {
      const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const state = fresh({ user: { email: 'nadia@example.com', wealth_desk: true }, desk: true });
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'ways in');
      await page.goto(`${base}/wealth.html`);
      await page.waitForSelector('.wd-hero');
      await page.waitForFunction(() => /Your wealth desk/.test((document.getElementById('sh-wd') || {}).textContent || ''));
      assert.equal(await page.getAttribute('#sh-wd', 'href'), 'wealth.html');
      state.user = { email: 'rohan@example.com', wealth_shared: 1 };
      await page.evaluate(() => window.AltahaAuth.refresh());
      await page.waitForFunction(() => /Your portfolio manager/.test(document.getElementById('sh-wd').textContent));
      assert.equal(await page.getAttribute('#sh-wd', 'href'), 'wealth.html#mine');
      await page.goto(`${base}/index.html#portfolio/money`);
      await page.waitForSelector('.dr-money a.dr-card[href="wealth.html"]', { timeout: 20000 });
      await ctx.close();
    }

    // ── A phone ────────────────────────────────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
      const state = fresh();
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'phone');
      const c = BOOK.clients[0];
      for (const h of ['overview', 'clients', `client/${c.id}`, `client/${c.id}/ledger`, `client/${c.id}/fees`, 'calls', 'fees', 'settings']) {
        await page.goto(`${base}/wealth.html?demo=1#${h}`);
        await page.waitForSelector('#wd-view');
        await page.waitForTimeout(400);
        await noSideways(page, h);
        await clean(page, `phone ${h}`);
      }
      await page.goto(`${base}/wealth.html?demo=1#client/${c.id}`);
      await page.waitForSelector('.wd-hlist');
      assert.ok(await page.isVisible('.wd-hlist .wd-hcard'), 'holdings are cards on a phone');
      assert.ok(!(await page.isVisible('.wd-table-wrap.cards')), 'the wide table is hidden on a phone');
      await page.screenshot({ path: `${output}/phone-client.png`, fullPage: true });
      await ctx.close();
    }

    // ── Motion off: nothing left invisible ─────────────────────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
      const state = fresh();
      await wire(ctx, state);
      const page = await ctx.newPage();
      await page.goto(`${base}/wealth.html?demo=1`);
      await page.waitForSelector('.wd-card');
      const op = await page.evaluate(() => [...document.querySelectorAll('.wd-rise, .wd-area .fl')].map(n => +getComputedStyle(n).opacity));
      assert.ok(op.length && op.every(o => o === 1), 'an entrance was left invisible with motion off');
      await ctx.close();
    }

    // ── A desk left open catches up with another computer ──────────────
    {
      const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const state = fresh({ user: { email: 'nadia@example.com', wealth_desk: true }, desk: true });
      await wire(ctx, state);
      const page = await ctx.newPage();
      watch(page, 'second computer');
      await page.goto(`${base}/wealth.html#clients`);
      await page.waitForFunction(n => document.body.innerText.includes(n), state.book.clients[0].name);
      // Another computer renames a client on the same account.
      state.book.clients[0].name = 'Renamed Elsewhere';
      await page.evaluate(() => { const now = Date.now; Date.now = () => now() + 60000; window.dispatchEvent(new Event('focus')); });
      await page.waitForFunction(() => document.body.innerText.includes('Renamed Elsewhere'), null, { timeout: 8000 })
        .catch(() => assert.fail('an open desk did not pick up a change made on another computer'));
      await ctx.close();
    }

    assert.deepEqual(errors, [], errors.join('\n'));
    console.log('wealth desk: two computers, landing, sample, setup, writes, client view, phone and motion-off all pass');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
