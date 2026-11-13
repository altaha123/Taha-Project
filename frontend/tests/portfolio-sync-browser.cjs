/* One account, two computers.
 *
 * The portfolio was pulled from the account only into an EMPTY table and sent
 * to it only when Save was pressed. So a second computer that already held an
 * older list showed it for ever, and a change made without pressing Save
 * never left the machine it was typed on. Two browser contexts stand in for
 * two computers here; one mocked account sits behind both.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');
const PORT = 8771;

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

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const account = { holdings: [], puts: 0 };
  const errors = [];

  async function computer() {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => localStorage.setItem('altaha-session-v1', 'a-session'));
    await context.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      if (p === '/auth/me') return route.fulfill({ json: { email: 'reader@example.com', digest_opt_in: true } });
      if (p === '/me/portfolio') {
        if (route.request().method() === 'PUT') {
          account.holdings = JSON.parse(route.request().postData() || '{}').holdings || [];
          account.puts += 1;
          return route.fulfill({ json: { saved: account.holdings.length, rejected: [], holdings: account.holdings } });
        }
        return route.fulfill({ json: { holdings: account.holdings } });
      }
      if (url.hostname !== '127.0.0.1') {
        const kind = route.request().resourceType();
        if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
        return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(String(e.stack)));
    page.open = async () => {
      await page.goto(`http://127.0.0.1:${PORT}/?go=portfolio`, { waitUntil: 'domcontentloaded' });
      await page.locator('#pf_rows .pf_sym').first().waitFor();
    };
    page.symbols = () => page.locator('#pf_rows .pf_sym').evaluateAll(ns => ns.map(n => n.value).filter(Boolean));
    return page;
  }
  const until = async (fn, what) => {
    for (let i = 0; i < 60; i++) { if (await fn()) return; await new Promise(r => setTimeout(r, 150)); }
    assert.fail(what);
  };

  try {
    // Computer A types a holding and never presses Save: it reaches the account anyway.
    const a = await computer();
    await a.open();
    await a.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
    await a.locator('#pf_rows .pf_qty').first().fill('10');
    await a.locator('#pf_rows .pf_buy').first().fill('1650');
    await a.locator('#pf_rows .pf_date').first().fill('2025-04-01');
    await until(() => account.holdings.length === 1 && account.holdings[0].buy_date === '2025-04-01',
      'a holding typed while signed in never reached the account');
    assert.equal(account.holdings[0].symbol, 'HDFCBANK');

    // Computer B has never seen this account's list: it shows it, date and all.
    const b = await computer();
    await b.open();
    await until(async () => (await b.symbols()).join() === 'HDFCBANK', 'a second computer did not load the account\'s portfolio');
    assert.equal(await b.locator('#pf_rows .pf_date').first().inputValue(), '2025-04-01', 'the buy date did not follow the account');

    // B changes the quantity. A, which still holds the OLD list, picks the change up on reload.
    await b.locator('#pf_rows .pf_qty').first().fill('25');
    await until(() => account.holdings[0] && account.holdings[0].qty === 25, 'the second computer\'s edit never reached the account');
    await a.open();
    await until(async () => (await a.locator('#pf_rows .pf_qty').first().inputValue()) === '25',
      'a computer holding an older list kept it instead of taking the account\'s');

    // An open tab catches up when it is looked at again, without a reload.
    await b.locator('#pf_rows .pf_qty').first().fill('40');
    await until(() => account.holdings[0].qty === 40, 'edit not sent');
    await a.evaluate(() => { window.__realNow = Date.now; Date.now = () => window.__realNow() + 60000; window.dispatchEvent(new Event('focus')); });
    await until(async () => (await a.locator('#pf_rows .pf_qty').first().inputValue()) === '40',
      'an open tab did not catch up when it was looked at again');

    // Agreeing with the account does not send it back: no save loop.
    const puts = account.puts;
    await a.open(); await b.open();
    await new Promise(r => setTimeout(r, 2500));
    assert.equal(account.puts, puts, 'loading the account\'s copy wrote it straight back');

    // A change this computer could not send is newer than the account and wins.
    await a.evaluate(() => {
      const d = JSON.parse(localStorage.getItem('altaha-portfolio-draft-v1'));
      d.rows[0].qty = '55'; localStorage.setItem('altaha-portfolio-draft-v1', JSON.stringify(d));
    });
    await a.open();
    await until(() => account.holdings[0].qty === 55, 'an unsent local change was thrown away for the older account copy');

    assert.deepEqual(errors, [], errors.join('\n'));
    console.log('portfolio sync: two computers on one account agree, edits travel without Save, dates follow, no save loop');
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); console.log('::error title=Portfolio sync::' + String(e.message).split('\n')[0]); process.exit(1); });
