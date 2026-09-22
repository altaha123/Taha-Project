/* The guided card in Allocate, driven the way a reader drives it.
 *
 * Four things here fail silently rather than throwing, which is why they are
 * asserted in a real browser instead of a unit test. A slider whose reported
 * figure does not match what the handle was set to. A questionnaire that asks
 * again for answers already given in the planner. A card that reaches the
 * asset classes without a profile behind them. And rupee figures that do not
 * add up to the sum the reader put in — the one thing on the page somebody
 * will check with a calculator.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');

// The shape the server sends. The real list is asserted in
// backend/tests/test_risk_profile.py; this only has to be that shape.
const QUESTIONS = {
  questions: [
    { id: 'age', axis: 'capacity', weight: 18, kind: 'choice',
      label: 'How old are you?', why: 'Years to retirement decide the recovery time.',
      options: [{ value: 'under25', label: 'Under 25', score: 100 },
                { value: '65plus', label: '65 or older', score: 15 }] },
    { id: 'horizon', axis: 'capacity', weight: 24, kind: 'choice',
      label: 'When will you need this money?', why: 'The single strongest input.',
      options: [{ value: 'under1', label: 'Within a year', score: 0 },
                { value: '10plus', label: 'More than 10 years', score: 100 }] },
    { id: 'emergency', axis: 'capacity', weight: 16, kind: 'choice',
      label: 'How many months of expenses could you cover from cash today?',
      why: 'An emergency fund stops a job loss becoming a forced sale.',
      options: [{ value: 'none', label: 'None', score: 0 },
                { value: 'over12', label: 'More than 12 months', score: 100 }] },
    { id: 'drawdown_action', axis: 'tolerance', weight: 34, kind: 'choice',
      label: 'It falls by a third. What do you actually do?',
      why: 'An action, not an attitude.',
      options: [{ value: 'sell_all', label: 'Sell everything and stop', score: 0 },
                { value: 'buy_more', label: 'Put more in while it is cheaper', score: 100 }] },
    { id: 'max_fall', axis: 'tolerance', weight: 26, kind: 'choice',
      label: 'How far could this fall before you could not leave it alone?',
      why: 'Indian equity has fallen more than 38% inside a year.',
      options: [{ value: 'any', label: 'Any fall would worry me', score: 0 },
                { value: '40plus', label: '40% or more', score: 100 }] },
    { id: 'purpose', axis: 'context', weight: 0, kind: 'choice',
      label: 'What is this money for?', why: 'Recorded, not scored.',
      options: [{ value: 'retirement', label: 'Retirement' },
                { value: 'house', label: 'A house' }] },
    { id: 'mode', axis: 'context', weight: 0, kind: 'choice',
      label: 'How would you put money in?', why: 'A SIP and a lump sum are different risks.',
      options: [{ value: 'sip', label: 'A fixed amount every month' },
                { value: 'lumpsum', label: 'One lump sum' }] },
    { id: 'amount', axis: 'context', weight: 0, kind: 'amount',
      label: 'How much, in rupees?', why: 'The slider already answered this.' }
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

const rupees = text => Number(String(text).replace(/[^0-9]/g, ''));

(async () => {
  await new Promise(r => server.listen(8771, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    // Reduced motion, because mid-animation nothing is reliably clickable and
    // the card promises to work without the movement anyway. That promise is
    // exactly what this setting tests.
    const context = await browser.newContext({
      viewport: { width: 1280, height: 950 }, reducedMotion: 'reduce' });
    let saved = null;

    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      if (p === '/planner/questions') return route.fulfill({ json: QUESTIONS });
      if (p === '/auth/me') return route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
      if (p === '/me/risk-profile') {
        saved = JSON.parse(route.request().postData() || '{}').answers;
        return route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
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
    await page.goto('http://127.0.0.1:8771/?go=allocate', { waitUntil: 'domcontentloaded' });

    // ── Stage 1 · the amount ────────────────────────────────────────────────────
    await page.locator('#acf-card').waitFor({ state: 'visible' });
    await page.locator('#acf_slider').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#acf_slider').getAttribute('min'), '0');

    // The ends of the track are the ends the reader was promised.
    await page.locator('#acf_slider').fill('0');
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 1,
      'the track must start at ₹1');
    await page.locator('#acf_slider').fill('10000');
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 200000000,
      'the track must end at ₹20 crore');
    // The moving figure keeps a fixed number of decimals for its unit, so the
    // reading cannot change length as it moves.
    assert.match(await page.locator('#acf_big').innerText(), /^₹20\.00 Cr$/);

    // ── A drag moves the reading, it does not lurch ────────────────────────────────────
    // While the handle is moving the step has to be finer than the reading.
    // The settled step at ₹18.5 lakh is ₹25,000 against ₹10,000 of displayed
    // resolution, so a coarse drag skipped two or three readings at a time.
    const walk = await page.evaluate(() => {
      const flow = window.AltahaAllocateFlow;
      const at = flow.rupeesToSlider(1850000);
      const out = [];
      for (let p = at; p < at + 12; p++) out.push(flow.sliderToRupees(p, true));
      return out;
    });
    const jumps = walk.slice(1).map((v, i) => v - walk[i]).filter(d => d > 0);
    assert.ok(jumps.length >= 8, 'most of a drag produced no change at all');
    assert.ok(Math.max(...jumps) <= 10000,
      `a single drag step moved ₹${Math.max(...jumps)}, more than the reading's resolution`);
    // Letting go still settles onto a round figure.
    assert.equal(await page.evaluate(() =>
      window.AltahaAllocateFlow.sliderToRupees(
        window.AltahaAllocateFlow.rupeesToSlider(1850000))), 1850000);

    // A quick pick and the typed figure are the same number in three places:
    // the big display, the exact line and the handle.
    await page.locator('.acf-chip', { hasText: '₹1 Cr' }).click();
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 10000000);
    assert.equal(await page.locator('#acf_type').inputValue(), '10000000');
    const pos = Number(await page.locator('#acf_slider').inputValue());
    await page.locator('#acf_slider').fill(String(pos));
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 10000000,
      'nudging the handle after a quick pick must not move the figure');

    await page.locator('#acf_type').fill('2500000');
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 2500000);

    // ── The adviser asks it ────────────────────────────────────────────────────
    // (the amount stage; the questions get their own art below)
    // A figure carrying meaning would be a figure a screen reader cannot
    // read, so the question stays a real heading and the drawing stays
    // hidden from the accessibility tree. Both halves are asserted.
    assert.equal(await page.locator('.acf-adviser.is-ask').count(), 1);
    assert.equal(await page.locator('.acf-adviser').getAttribute('aria-hidden'), 'true');
    assert.equal(await page.locator('.acf-bubble h3').innerText(),
      'How much are you putting to work?');
    assert.equal(await page.locator('.acf-adviser').innerText(), '',
      'the figure must carry no text of its own');

    // ── The default amount is real state, not just something drawn ─────────
    // Pressing Continue without touching the handle used to carry a reader
    // all the way to the allocation with no amount at all: "allocating ₹0"
    // in the header and a dead end at the end of the flow.
    await page.evaluate(() => localStorage.removeItem('altaha-allocate-flow-v1'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('#acf_slider').waitFor({ state: 'visible' });
    const opening = rupees(await page.locator('#acf_exact').innerText());
    assert.ok(opening > 0, 'the slider must open on a real figure');
    await page.locator('#acf_next').click();
    await page.locator('.acf-opts').waitFor({ state: 'visible' });
    assert.match(await page.locator('.acf-progress .acf-step').innerText(),
      new RegExp('allocating', 'i'));
    assert.ok(!(await page.locator('.acf-progress .acf-step').innerText()).includes('₹0'),
      'the untouched default must carry through as the amount, not as zero');
    await page.locator('#acf_back').click();
    await page.locator('#acf_slider').waitFor({ state: 'visible' });
    await page.locator('#acf_type').fill('2500000');

    // ── Stage 2 · the questions, one at a time ───────────────────────────────────────
    await page.locator('#acf_next').click();
    await page.locator('.acf-opts').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#acf_slider').count(), 0, 'the stage must replace, not stack');
    assert.match(await page.locator('.acf-progress .acf-step').innerText(), /question 1 of 7/i);
    assert.equal(await page.locator('.acf-q .acf-why').count(), 1,
      'every question says why it is being asked');
    // Each question draws the thing it is asking about, and pointing at an
    // option previews that option before it is committed to. The age question
    // is the one this was built for: the adviser ages with the answer.
    assert.equal(await page.locator('.acf-q h3').innerText(), 'How old are you?');
    await page.locator('.acf-opt', { hasText: 'Under 25' }).hover();
    await page.waitForFunction(() =>
      !!document.querySelector('#acf_art .is-age-young'));
    await page.locator('.acf-opt', { hasText: '65 or older' }).hover();
    await page.waitForFunction(() =>
      !!document.querySelector('#acf_art .is-age-elder'),
      null, { timeout: 4000 });
    assert.equal(await page.locator('#acf_art .adv-specs').count(), 1,
      'reading glasses arrive with the older answer');
    // Pointing away puts the picture back to what is actually selected.
    await page.locator('.acf-q h3').hover();
    await page.waitForFunction(() =>
      !!document.querySelector('#acf_art .is-age-young'), null, { timeout: 4000 });
    assert.equal(await page.locator('#acf_art').innerText(), '',
      'the picture must carry no words of its own');

    // Time question, time picture.
    await page.locator('.acf-opt').first().click();
    await page.waitForTimeout(700);
    assert.equal(await page.locator('.acf-q h3').innerText(), 'When will you need this money?');
    assert.equal(await page.locator('#acf_art .qa-scene.is-horizon').count(), 1,
      'the horizon question must draw time, not a person');
    await page.locator('.acf-opt', { hasText: 'Within a year' }).hover();
    await page.waitForFunction(() => {
      const sand = document.querySelectorAll('#acf_art .qa-sand');
      return sand.length === 2;
    });
    await page.locator('#acf_prev').click();
    await page.locator('.acf-opts').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.acf-q h3').innerText(), 'How old are you?',
      'Back must return to the previous question');
    assert.equal(await page.locator('#acf_art .is-age-young').count(), 1,
      'and to the answer that was given there');

    // The context questions are asked; `amount` is not, because the slider
    // already answered it.
    const asked = [];
    for (let i = 0; i < 7; i++) {
      asked.push(await page.locator('.acf-q h3').innerText());
      await page.locator('.acf-opt').first().click();          // the cautious answer
      await page.waitForTimeout(60);
    }
    assert.ok(asked.some(q => /what is this money for/i.test(q)));
    assert.ok(!asked.some(q => /how much, in rupees/i.test(q)),
      'the slider already answered the amount; asking again is asking twice');

    // The last question does not advance on its own: the step into the
    // allocation is taken deliberately.
    await page.locator('#acf_forward').click();

    // ── Stage 3 · the answer ───────────────────────────────────────────────────
    await page.locator('.acf-first').waitFor({ state: 'visible' });

    // The headline is the sum and the order, not the band. The band is a label.
    assert.match(await page.locator('.acf-head h3').innerText(), /₹25 L, in order/);
    assert.equal(await page.locator('.acf-bandline b').innerText(), 'Conservative');
    // The profile is the lower of the two axes rather than the flattering one;
    // the axes now sit behind a tap, so they are read from the markup.
    const axes = await page.evaluate(() =>
      [...document.querySelectorAll('.acf-axis .v')].map(n => Number(n.textContent)));
    assert.equal(axes[2], Math.min(axes[0], axes[1]));
    assert.equal(await page.locator('.acf-more[open]').count(), 0,
      'the theory opens on request, not by default');

    // Signed out, nothing is recorded, and the card says so rather than
    // quietly not saving.
    assert.match(await page.locator('.acf-bandline').innerText(), /not recorded/i);
    assert.equal(saved, null);

    // ── First calls: the cushion is a line with a number, not a paragraph ──
    // "None" was the answer to the cushion question, so the cushion is call
    // one. It cannot be sized without the household number, so it is asked
    // for on the card rather than assumed — and until then nothing is taken
    // off the sum.
    assert.equal(await page.locator('.acf-call.is-cushion.needs').count(), 1);
    assert.equal(rupees(await page.locator('#acf_free').innerText()), 2500000);
    await page.locator('#acf_expenses').fill('50000');
    await page.locator('#acf_expenses').press('Enter');
    await page.locator('#acf_expenses').blur();
    await page.waitForFunction(() => document.querySelector('.acf-call.is-cushion.needs') === null);
    assert.equal(rupees(await page.locator('.acf-call.is-cushion .acf-call-amt').innerText()), 300000,
      'six months of ₹50,000 with nothing held is ₹3 lakh');
    assert.equal(rupees(await page.locator('#acf_free').innerText()), 2200000);
    assert.equal(await page.locator('#acf_expenses').inputValue(), '50000',
      'the figure typed stays on the card after the repaint');

    // ── Dated money gets no growth sleeve ──────────────────────────────────────
    // "Within a year" was the horizon. That is not a risk to be sized; it is
    // the reason equity does not apply to this money at all.
    assert.equal(await page.locator('.acf-groups .acf-group').count(), 1);
    assert.equal(await page.locator('.acf-groups .acf-group.is-stable').count(), 1);
    assert.ok((await page.locator('.acf-flag.is-stop').count()) >= 1,
      'money needed within three years must be flagged');
    const flagText = (await page.locator('.acf-flag').allInnerTexts()).join('\n');
    assert.ok(!/step\s+\d/i.test(flagText),
      'a flag still points at the allocation sequence that was removed');

    // The money adds up. This is the one number a reader checks by hand.
    await page.waitForFunction(() => {
      const all = document.querySelectorAll('.acf-money');
      return all.length === 1 && [...all].every(n => n.hasAttribute('data-settled'));
    });
    const sleeveTotal = (await page.locator('.acf-money').allInnerTexts()).map(rupees)
      .reduce((a, b) => a + b, 0);
    assert.equal(sleeveTotal, 2200000, 'the sleeves must add to exactly what is free');
    assert.equal(sleeveTotal + 300000, 2500000, 'first calls plus sleeves must equal the sum put in');
    for (const group of await page.locator('.acf-how-group').all()) {
      const sleeve = rupees(await group.locator('summary b').innerText());
      const rows = (await group.locator('.acf-sleeve-t b').allInnerTexts()).map(rupees);
      assert.equal(rows.reduce((a, b) => a + b, 0), sleeve,
        'the categories inside a sleeve must add to the sleeve above them');
    }

    // ── What it becomes: the years move the numbers ────────────────────────────────
    assert.equal(await page.locator('#acf_years').inputValue(), '1',
      'a one-year horizon opens the outcomes on one year');
    const before = await page.locator('.acf-out-total b').innerText();
    assert.match(before, /₹/);
    await page.locator('#acf_years').fill('10');
    await page.waitForFunction(() => document.querySelector('#acf_years_v').textContent === '10');
    const after = await page.locator('.acf-out-total b').innerText();
    assert.notEqual(after, before, 'ten years must not read the same as one');
    assert.match(await page.locator('.acf-out-total small').innerText(), /today's money/);
    assert.match(await page.locator('.acf-out-rows li').first().innerText(), /a year/);

    // ── How to do it: kind, route, and what to look for, never a name ──────
    assert.equal(await page.locator('.acf-how-group[open]').count(), 1);
    const how = await page.locator('.acf-how').innerText();
    assert.match(how, /Where:/);
    assert.match(how, /Look for:/);
    assert.match(how, /DICGC/);

    // ── What was considered and left out, with the reason ──────────────────
    const left = await page.evaluate(() => document.querySelector('.acf-leftout').textContent);
    assert.match(left, /Direct property/);
    assert.match(left, /Alternative investment funds/);
    assert.match(left, /₹1 crore per fund/);
    assert.match(left, /angel/i);

    // ── The same figures, as twelve monthly ones ───────────────────────────────────
    await page.locator('#acf_monthly').click();
    await page.waitForFunction(() => {
      const n = document.querySelector('.acf-money');
      return n && n.hasAttribute('data-settled') && /a month/.test(n.parentElement.textContent);
    });
    assert.equal(rupees(await page.locator('.acf-money').innerText()), Math.round(2200000 / 12));
    assert.match(await page.locator('.acf-how-group summary b').innerText(), /a month/);
    await page.locator('#acf_lump').click();
    await page.waitForFunction(() => {
      const n = document.querySelector('.acf-money');
      return n && n.hasAttribute('data-settled') && !/a month/.test(n.parentElement.textContent);
    });
    assert.equal(rupees(await page.locator('.acf-money').innerText()), 2200000);

    // ── The effects are decoration, and prove it ───────────────────────────────────
    // Everything above ran under reduced motion, which switches the coin
    // layer off entirely. That every figure, control and reading was still
    // correct IS the assertion: the money effects are never load-bearing.
    assert.equal(await page.evaluate(() => window.AltahaMoneyFx.still()), true);
    assert.equal(await page.locator('.mfx-coin').count(), 0,
      'reduced motion must spawn no coins at all');
    assert.equal(await page.locator('.acf-ring .acf-arc').count(), 1,
      'the ring is markup, not motion, and must be drawn either way');
    assert.equal(await page.locator('.acf-adviser.is-present').count(), 1,
      'the figure turns to the allocation it is handing over');
    // One person the whole way through, not three different drawings.
    assert.equal(await page.locator('.acf-adviser .adv-gold').count() >= 2, true);
    assert.match(await page.locator('.acf-ring .acf-total').innerText(), /[0-9]/);

    // It names categories and never a product or an instruction — including
    // everything folded behind a tap, which is why this reads textContent.
    const prose = (await page.evaluate(() => document.querySelector('#acf-body').textContent)).toLowerCase();
    for (const word of [' buy ', ' sell ', 'we recommend', 'you should']) {
      assert.ok(!prose.includes(word), `the card issued an instruction: ${word.trim()}`);
    }
    assert.ok(prose.includes('categories, never products'));

    // ── The card is the whole of Allocate ──────────────────────────────────────────
    // The five-step sequence that used to sit under it is gone, so nothing
    // below can repeat the card's split back in different words.
    assert.equal(await page.locator('#alc-steps').count(), 0);
    assert.equal(await page.locator('.alc-step').count(), 0);
    assert.equal(await page.evaluate(() => typeof window.AltahaAllocate), 'undefined');

    // ── The answers are the planner's answers ──────────────────────────────────────
    const draft = await page.evaluate(() =>
      JSON.parse(localStorage.getItem('altaha-risk-answers-v1') || '{}'));
    assert.equal(draft.horizon, 'under1');
    assert.equal(draft.purpose, 'retirement');

    // ── Coming back lands on the answer, not on question one ───────────────
    await page.goto('http://127.0.0.1:8771/?go=allocate', { waitUntil: 'domcontentloaded' });
    await page.locator('#acf-card').waitFor({ state: 'visible' });
    await page.locator('#acf_slider').waitFor({ state: 'visible' });
    assert.equal(rupees(await page.locator('#acf_exact').innerText()), 2500000,
      'the amount must survive a reload');

    // ── Narrow screens ─────────────────────────────────────────────────────────
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false, `the card overflowed the page at ${width}px`);
      assert.equal(await page.locator('#acf_slider').isVisible(), true);
      // The figure stays on the card at every width rather than pushing the
      // question into a gutter or hanging off the edge.
      const seated = await page.locator('.acf-adviser').boundingBox();
      const frame = await page.locator('#acf-card').boundingBox();
      assert.ok(seated.width <= frame.width,
        `the adviser was wider than the card at ${width}px`);
      assert.ok(seated.x >= frame.x - 1 && seated.x + seated.width <= frame.x + frame.width + 1,
        `the adviser hung off the card at ${width}px`);
    }

    assert.deepEqual(errors, [], 'the page threw while the card was driven');

    // ── And with motion on, the money actually moves ───────────────────────────────
    const lively = await browser.newContext({
      viewport: { width: 1100, height: 950 }, reducedMotion: 'no-preference' });
    await lively.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/planner/questions') return route.fulfill({ json: QUESTIONS });
      if (url.pathname === '/auth/me') return route.fulfill({ status: 401, json: { detail: 'Sign in.' } });
      if (url.hostname !== '127.0.0.1') {
        const kind = route.request().resourceType();
        if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
        return route.fulfill({ json: { available: false, rows: [], rankings: [],
                                       sectors: [], items: [], status: 'idle' } });
      }
      return route.continue();
    });
    const moving = await lively.newPage();
    const movingErrors = [];
    moving.on('pageerror', e => movingErrors.push(String(e.stack)));
    await moving.goto('http://127.0.0.1:8771/?go=allocate', { waitUntil: 'domcontentloaded' });
    await moving.locator('#acf_slider').waitFor({ state: 'visible' });

    // A quick pick throws coins, and more of them for more money.
    await moving.locator('.acf-chip', { hasText: '₹50K' }).click();
    await moving.waitForFunction(() => document.querySelectorAll('.mfx-coin').length > 0);
    const small = await moving.locator('.mfx-coin').count();
    await moving.waitForFunction(() => document.querySelectorAll('.mfx-coin').length === 0,
      null, { timeout: 6000 });
    await moving.locator('.acf-chip', { hasText: '₹5 Cr' }).click();
    await moving.waitForFunction(() => document.querySelectorAll('.mfx-coin').length > 0);
    const large = await moving.locator('.mfx-coin').count();
    assert.ok(large > small,
      `₹5 Cr must throw more coins than ₹50K (${large} vs ${small})`);
    assert.equal(await moving.locator('.mfx-coin').first().innerText(), '₹');

    // Every coin clears up after itself rather than piling on the card.
    await moving.waitForFunction(() => document.querySelectorAll('.mfx-coin').length === 0,
      null, { timeout: 8000 });
    assert.ok(await moving.evaluate(() => window.AltahaMoneyFx.liveCount() === 0),
      'coins must not leak once they have landed');

    // The layer takes no clicks: the control underneath it stays reachable.
    assert.equal(await moving.evaluate(() =>
      getComputedStyle(document.querySelector('.mfx-layer')).pointerEvents), 'none');
    assert.equal(await moving.locator('.mfx-layer').getAttribute('aria-hidden'), 'true');

    assert.deepEqual(movingErrors, [], 'the page threw while the coins were flying');
    await lively.close();

    console.log('Allocate guided card: checks passed');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
