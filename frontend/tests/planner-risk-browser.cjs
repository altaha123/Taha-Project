/* The fork, and the questionnaire it leads to.
 *
 * Arriving at a portfolio review with no portfolio, the honest answer is not
 * an empty table with an Analyse button under it. The fork asks once, sends
 * somebody with nothing to the planner, and never asks again.
 *
 * The questionnaire is served rather than held in the page, so the test drives
 * it the way a browser does: render whatever the server sent, refuse to submit
 * until it is answered, and show the working rather than a bare verdict.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');

// Same shape the server sends; the real list's structure is asserted in
// backend/tests/test_account_endpoints.py.
const QUESTIONS = {
  questions: [
    { id: 'horizon', axis: 'capacity', weight: 24, kind: 'choice',
      label: 'When will you need this money?', why: 'The strongest input.',
      options: [{ value: 'under1', label: 'Within a year', score: 0 },
                { value: '10plus', label: 'More than 10 years', score: 100 }] },
    { id: 'drawdown_action', axis: 'tolerance', weight: 34, kind: 'choice',
      label: 'It falls by a third. What do you do?', why: 'An action, not an attitude.',
      options: [{ value: 'sell_all', label: 'Sell everything', score: 0 },
                { value: 'buy_more', label: 'Put more in', score: 100 }] },
    { id: 'amount', axis: 'context', weight: 0, kind: 'amount',
      label: 'How much, in rupees?', why: 'The monthly figure.' },
    { id: 'target', axis: 'context', weight: 0, kind: 'amount', optional: true,
      label: 'Target? (optional)', why: 'Checks the plan against arithmetic.' }
  ],
  bands: [{ from: 0, to: 20, band: 'Conservative', note: 'Capital first.' },
          { from: 20, to: 40, band: 'Moderately conservative', note: '' },
          { from: 40, to: 60, band: 'Balanced', note: '' },
          { from: 60, to: 80, band: 'Growth', note: '' },
          { from: 80, to: 101, band: 'Aggressive', note: 'Patience is the constraint.' }]
};

const server = http.createServer((req, res) => {
  const name = path.join(root, decodeURIComponent(
    req.url.split('?')[0] === '/' ? '/index.html' : req.url.split('?')[0]));
  if (!name.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type',
      name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css'
      : name.endsWith('.html') ? 'text/html' : 'application/octet-stream');
    res.end(fs.readFileSync(name));
  } catch (e) { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(r => server.listen(8768, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // The tab swap and the section reveals are animations, and mid-animation
    // nothing inside them is reliably clickable. The page already honours
    // prefers-reduced-motion — asking for it is closer to how a reader with
    // that setting uses the site than sleeping until the fade ends.
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    let signedIn = false, saved = null;

    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      if (p === '/planner/questions') return route.fulfill({ json: QUESTIONS });
      if (p === '/auth/me') {
        return signedIn
          ? route.fulfill({ json: { email: 'reader@example.com', digest_opt_in: true,
                                    holdings: 0, watchlist: 0 } })
          : route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
      }
      if (p === '/me/risk-profile') {
        saved = JSON.parse(route.request().postData() || '{}').answers;
        return route.fulfill({ json: { profile: {
          capacity: 100, tolerance: 0, score: 0, band: 'Conservative',
          band_note: 'Capital preservation comes first.', gap: 100,
          binding: 'tolerance',
          binding_note: 'Your circumstances could carry more risk than you would hold.'
        }, adviser: { configured: false } } });
      }
      if (url.hostname !== '127.0.0.1') {
        const kind = route.request().resourceType();
        if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
        return route.fulfill({ json: { available: false, rows: [], rankings: [],
                                       sectors: [], items: [], status: 'idle' } });
      }
      return route.continue();
    });

    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e.stack)));
    const openPortfolio = () =>
      page.goto('http://127.0.0.1:8768/?go=portfolio', { waitUntil: 'domcontentloaded' });

    // ── The fork is asked of somebody with nothing to review ────────────────
    await openPortfolio();
    await page.locator('#pf_fork').waitFor({ state: 'visible' });

    // ── "Not yet" lands on the questions, not on an empty table ─────────────
    // Driven by the button rather than by calling the router, because that is
    // the whole flow under test: somebody with no holdings being taken
    // somewhere useful.
    await page.locator('#pf_fork_no').click();
    await page.locator('#view-planner').waitFor({ state: 'visible' });
    await page.locator('#riskprofile').waitFor({ state: 'visible' });
    await page.locator('#prisk_body .prq').first().waitFor();
    assert.equal(await page.locator('#prisk_body .prq').count(), 4);

    // Every question says why it is asked. Somebody handing over their income
    // and their fears is owed the reason for each one.
    for (const why of await page.locator('#prisk_body .prq .why').allInnerTexts()) {
      assert.ok(why.trim().length > 0, 'a question was asked without saying why');
    }

    // It will not be submitted half-answered, and says how much is left.
    assert.equal(await page.locator('#prisk_go').isDisabled(), true);
    assert.match(await page.locator('#prisk_go').innerText(), /3 questions to go/i);

    const body = page.locator('#prisk_body');
    await body.getByRole('button', { name: 'More than 10 years' }).click();
    await body.getByRole('button', { name: 'Sell everything' }).click();
    assert.match(await page.locator('#prisk_go').innerText(), /1 question to go/i);

    await body.locator('.prq-amt').first().fill('25000');
    assert.equal(await page.locator('#prisk_go').isDisabled(), false,
      'the optional target was treated as required');

    // ── Signed out it is computed and shown, and said to be unsaved ─────────
    await page.locator('#prisk_go').click();
    await page.locator('#prisk_result').waitFor();
    assert.match(await page.locator('#prisk_note').innerText(), /Sign in to keep/i);
    assert.equal(saved, null, 'a profile was sent with nobody to record it against');
    // A long horizon and an unwilling temperament: the lower one decides.
    assert.match(await page.locator('#prisk_result h4').innerText(), /Conservative/i);
    assert.match(await page.locator('.prres-gap').innerText(), /lower of the two/i);

    // ── The fork is not asked twice ─────────────────────────────────────────
    await openPortfolio();
    await page.waitForTimeout(250);
    assert.equal(await page.locator('#pf_fork').isVisible(), false,
      'the fork asked again after it had been answered');

    // ── Never asked at all of somebody who already has rows ─────────────────
    await page.evaluate(() => {
      localStorage.removeItem('altaha-portfolio-fork-v1');
      localStorage.setItem('altaha-portfolio-draft-v1',
        JSON.stringify({ rows: [{ symbol: 'HSCL', qty: '66', buy: '713.44', date: '' }] }));
    });
    await openPortfolio();
    await page.waitForTimeout(250);
    assert.equal(await page.locator('#pf_fork').isVisible(), false,
      'asked somebody who already has holdings whether they have holdings');

    // ── Signed in, the answers survive and the profile becomes a record ─────
    signedIn = true;
    await page.evaluate(() => {
      localStorage.setItem('altaha-session-v1', 'a-session');
      localStorage.removeItem('altaha-portfolio-fork-v1');
      localStorage.removeItem('altaha-portfolio-draft-v1');
    });
    await openPortfolio();
    await page.locator('#pf_fork_no').click();
    await page.locator('#riskprofile').waitFor({ state: 'visible' });
    await page.locator('#prisk_body .prq').first().waitFor();
    assert.equal(await page.locator('#prisk_go').isDisabled(), false,
      'the answers already given were lost on a reload');

    await page.locator('#prisk_go').click();
    await page.locator('#prisk_result').waitFor();
    await page.waitForFunction(() =>
      /Saved/.test(document.getElementById('prisk_note').textContent));
    assert.deepEqual(saved, { horizon: '10plus', drawdown_action: 'sell_all', amount: 25000 });
    assert.match(await page.locator('.prres-gap').innerText(), /comfortable|would hold/i);

    assert.deepEqual(errors, []);
    await context.close();
    console.log('Planner: the fork asks once, and the profile is the lower of the two.');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
