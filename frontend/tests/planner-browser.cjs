/* The money planner (planner.js over planner-math.js).
 *
 * It used to be fifteen empty boxes and a verdict that appeared after most of
 * them were filled, and it remembered nothing. It now opens with an answer —
 * the month somebody's investments could pay their bills — and gives them
 * reasons to come back: a check-in, goals, a price for anything in days.
 *
 * Almost everything that can go wrong with that goes wrong quietly:
 *
 *   1. A date on the screen that is not the date the arithmetic gives.
 *   2. Numbers that are gone after a reload, or a page that leaves an empty
 *      record in the browser of somebody who never opened the planner.
 *   3. A what-if that changes the saved plan, or a ticked move that draws no
 *      second line.
 *   4. A price tag that says "0 months" for a purchase that costs days.
 *   5. A goal that does not move the date, or three salary-day figures that
 *      add up to a rupee more than was put away.
 *   6. A budget nobody itemised being handed a grade.
 *   7. A check-in that does not survive the month turning, or a streak broken
 *      by a month that is not over yet.
 *   8. A name typed into a form running as markup.
 *   9. An amount in the text that goes to WhatsApp, or in any request at all.
 *  10. The door bar lighting "Overview" over the planner (it did), and a phone
 *      that has to be scrolled sideways.
 *
 * The clock is pinned. The planner's whole answer is a date.
 */
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve('frontend');
const M = require(path.join(root, 'planner-math.js'));
const output = path.resolve('test-results/planner');
fs.mkdirSync(output, { recursive: true });

const NOW = new Date('2026-11-19T06:30:00Z');           // noon in India; the 19th everywhere
const LATER = new Date('2026-12-03T06:30:00Z');
const KEY = 'altaha-planner-v1';
const HOME = { age: '30', salary: '120000', spend: '70000', invested: '800000' };

const QUESTIONS = {
  questions: [
    { id: 'horizon', axis: 'capacity', weight: 24, kind: 'choice',
      label: 'When will you need this money?', why: 'The strongest input.',
      options: [{ value: 'under1', label: 'Within a year', score: 0 },
                { value: '10plus', label: 'More than 10 years', score: 100 }] }
  ],
  bands: [{ from: 0, to: 101, band: 'Balanced', note: '' }]
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

const BASE = 'http://127.0.0.1:8793';
const sent = [];                        // everything any page asked the network for

async function fresh(browser, viewport, when) {
  // Reduced motion, as the other suites ask for it: mid-fade nothing is
  // reliably clickable, and it is how a reader with that setting sees it.
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
  await context.route('**/*', route => {
    const req = route.request(), url = new URL(req.url());
    sent.push(req.method() + ' ' + req.url() + ' ' + (req.postData() || ''));
    if (url.pathname === '/planner/questions') return route.fulfill({ json: QUESTIONS });
    if (url.pathname === '/auth/me') return route.fulfill({ status: 401, json: { detail: 'Sign in to use this.' } });
    if (url.hostname !== '127.0.0.1') {
      const kind = req.resourceType();
      if (kind === 'script' || kind === 'font' || kind === 'stylesheet') return route.abort();
      return route.fulfill({ json: { available: false, rows: [], rankings: [], sectors: [], items: [], status: 'idle' } });
    }
    return route.continue();
  });
  const page = await context.newPage();
  await page.clock.setFixedTime(when || NOW);
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.stack)));
  return { context, page, errors };
}
const open = (page) => page.goto(BASE + '/#portfolio/planner', { waitUntil: 'domcontentloaded' })
  .then(() => page.locator('#mp-hero').waitFor({ state: 'visible' }));
/* Somebody who has been here before: their numbers are in the browser when
   the page loads. They are written on a bare page of the same site, and the
   planner is then opened — not opened, written to and reloaded. A reload
   puts the page back where it was scrolled before (here, the top) at the
   moment it finishes loading, over anything scrolled since. The steps below
   run inside that moment on a slow machine, and the phone check then found a
   tool it had just opened back under the fold. That is the browser keeping a
   reader's place across a reload, not the planner. */
const returning = async (page, state) => {
  await page.goto(BASE + '/planner.css', { waitUntil: 'domcontentloaded' });
  await page.evaluate(([k, v]) => localStorage.setItem(k, v), [KEY, JSON.stringify(state)]);
  await page.goto(BASE + '/#portfolio/planner', { waitUntil: 'domcontentloaded' });
  await page.locator('#mp-hero').waitFor({ state: 'visible' });
};
const stored = (page) => page.evaluate(k => JSON.parse(localStorage.getItem(k) || 'null'), KEY);
const when = (page) => page.locator('#mp-when').innerText();
const tab = async (page, id) => {
  await page.locator('#mp-tab-' + id).click();
  await page.locator('#mp-panel-' + id).waitFor({ state: 'visible' });
};
const fill = (page, sel, v) => page.locator(sel).fill(String(v));
const settle = (page) => page.waitForTimeout(320);        // the save is debounced
const plan = (state, at) => M.derive(state, at || NOW);

(async () => {
  await new Promise(r => server.listen(8793, '127.0.0.1', r));
  const browser = await chromium.launch({
    headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  try {
    /* ══ A first visit ══════════════════════════════════════════════════════ */
    let { context, page, errors } = await fresh(browser, { width: 1280, height: 900 });
    await open(page);

    // It opens with the question it answers, not with a form to fill in.
    assert.match(await when(page), /When does work become optional\?/);
    assert.equal(await page.locator('#mp-path-chart').isVisible(), false,
      'an empty chart card was shown to somebody with no numbers');
    assert.equal(await page.locator('#mp-moves').isVisible(), false);
    assert.doesNotMatch(await page.locator('#view-planner').innerText(), /NaN|undefined|Infinity|null/);

    // Merely loading the page leaves nothing behind.
    await settle(page);
    assert.equal(await stored(page), null, 'a page load wrote a planner record nobody asked for');

    // The door bar says where the reader is — arriving, and coming back.
    const lit = () => page.locator('#sh-doorbar .sh-pill.on').allInnerTexts();
    assert.deepEqual(await lit(), ['Money planner']);
    await page.locator('#sh-doorbar .sh-pill[data-tab="money"]').click();
    await page.locator('#view-money').waitFor({ state: 'visible' });
    await page.locator('#sh-doorbar .sh-pill[data-tab="planner"]').click();
    await page.locator('#mp-hero').waitFor({ state: 'visible' });
    await page.waitForTimeout(200);
    assert.deepEqual(await lit(), ['Money planner'],
      'the planner was on screen with another tool lit in the door bar above it');

    /* ══ Four numbers, one date ═════════════════════════════════════════════ */
    await fill(page, '#mp-age', 30);
    await fill(page, '#mp-salary', 120000);
    // Grouped the way the figure is said, as it is typed.
    assert.equal(await page.locator('#mp-salary').inputValue(), '1,20,000');
    assert.match(await when(page), /When does work/, 'income alone was given a date');

    await fill(page, '#mp-spend', 70000);
    assert.match(await when(page), /^[A-Z][a-z]+ 20\d\d$/);
    await fill(page, '#mp-invested', 800000);

    const base = plan(HOME);
    assert.equal(base.status, 'dated');
    assert.equal(await when(page), M.monthName(base.when),
      'the date on the screen is not the date the arithmetic gives');
    const hero = await page.locator('#mp-hero').innerText();
    assert.ok(hero.includes('about ' + base.ageThen), 'the age at the date is missing or wrong');
    assert.ok(hero.includes(M.short(base.sim.target)) && hero.includes(M.short(800000)));
    assert.match(hero, /Log your first check-in/);
    assert.match(await page.locator('#mp-put').getAttribute('placeholder'), /All ₹50,000 left over/);

    // The path: drawn, named, readable without a pointer, and with a table twin.
    const chart = page.locator('#mp-path-chart');
    await chart.locator('svg').waitFor();
    assert.equal(await chart.locator('path.line.s1').count(), 1);
    assert.equal(await chart.locator('line.goal').count(), 1);
    assert.ok((await chart.locator('svg').getAttribute('aria-label')).includes(M.monthName(base.when)));
    assert.equal(await page.locator('#mp-path-legend li').count(), 2);
    assert.ok(await page.locator('#mp-path-table tbody tr').count() >= 10);
    const box = await chart.locator('svg').boundingBox();
    assert.ok(box.width > 600 && box.height >= 240, 'the chart was drawn at no size');
    await chart.locator('svg').scrollIntoViewIfNeeded();
    const at = await chart.locator('svg').boundingBox();
    await page.mouse.move(at.x + at.width * 0.5, at.y + at.height * 0.5);
    await chart.locator('.mp-tip').waitFor({ state: 'visible' });
    assert.match(await chart.locator('.mp-tip').innerText(), /Your plan[\s\S]*Freedom line/);
    await page.mouse.move(0, 0);
    await chart.locator('svg').focus();
    await page.keyboard.press('ArrowLeft');
    assert.equal(await chart.locator('.mp-tip').isVisible(), true, 'the readout needs a pointer');
    await chart.locator('svg').blur();

    // The working is on the page, under the assumptions.
    await page.locator('#mp-assume > summary').click();
    assert.match(await page.locator('#mp-working').innerText(), /FREEDOM FIGURE[\s\S]*REAL GROWTH[\s\S]*RESULT/);

    await page.screenshot({ path: path.join(output, '1280-date.png'), fullPage: true });

    /* ══ It is still there after a reload ═══════════════════════════════════ */
    await settle(page);
    assert.deepEqual((({ age, salary, spend, invested }) => ({ age, salary, spend, invested }))(await stored(page)), HOME);
    await open(page);
    assert.equal(await when(page), M.monthName(base.when), 'the numbers did not survive a reload');
    assert.equal(await page.locator('#mp-invested').inputValue(), '8,00,000');

    /* ══ What moves it ══════════════════════════════════════════════════════ */
    const moves = Object.fromEntries(M.moves(base).map(x => [x.id, x]));
    const more = page.locator('[data-move="more"]');
    assert.ok((await more.locator('xpath=..').innerText()).includes(M.span(moves.more.delta)));
    assert.equal(await page.locator('[data-move="trim"]').count(), 0,
      'a trim was offered on a budget with no itemised wants');
    await more.check();
    await page.locator('[data-move="stepup"]').check();
    const both = M.combine(base, ['more', 'stepup']);
    const combo = await page.locator('#mp-combo').innerText();
    assert.ok(combo.includes(M.monthName(both.when)) && combo.includes(M.span(both.delta) + ' sooner'));
    assert.ok(both.when < base.when);
    // A second line, named in the legend, and its own point on the chart.
    assert.equal(await chart.locator('path.line.s2').count(), 1, 'a ticked move drew no line');
    assert.equal(await page.locator('#mp-path-legend li').count(), 3);
    // A what-if is a thought. The plan is exactly what it was.
    assert.equal(await when(page), M.monthName(base.when));
    await settle(page);
    assert.deepEqual((({ age, salary, spend, invested }) => ({ age, salary, spend, invested }))(await stored(page)), HOME);
    assert.equal(JSON.stringify(await stored(page)).includes('stepup'), false);
    await more.uncheck();
    await page.locator('[data-move="stepup"]').uncheck();
    assert.equal(await page.locator('#mp-combo').count(), 0);
    // Raising the dial is the real thing, and it does move the date.
    await page.locator('#mp-stepup').fill('10');
    assert.equal(await when(page), M.monthName(plan({ ...HOME, stepUp: 10 }).when));
    await page.locator('[data-act="defaults"]').click();
    assert.equal(await when(page), M.monthName(base.when));

    /* ══ The price of a thing, in time ══════════════════════════════════════ */
    await tab(page, 'tag');
    // Choosing a tool brings it up and scrolls the hero away, so the date
    // rides along beside the tabs.
    assert.equal(await page.locator('#mp-pin').innerText(), M.monthName(base.when, true),
      'the date beside the tabs is not the date');
    assert.ok((await page.locator('#mp-panel-tag').boundingBox()).y < 450, 'a chosen tool was left below the fold');
    await fill(page, '#mp-tag-cost', 5000);
    const small = M.priceTag(base, 5000, false);
    assert.ok(small.delay > 0 && small.delay < 1);
    assert.equal(await page.locator('#mp-tag-delay').innerText(), M.span(small.delay) + ' later',
      'a purchase that costs days was priced at nothing');
    assert.match(await page.locator('#mp-tag-say').innerText(), /costs .* (working day|hours? of work)/);

    await fill(page, '#mp-tag-cost', 80000);
    const phone = M.priceTag(base, 80000, false);
    assert.equal(await page.locator('#mp-tag-delay').innerText(), M.span(phone.delay) + ' later');
    // A habit is priced twice, and says so.
    await page.locator('[data-act="tag-mode"][data-mode="monthly"]').click();
    await fill(page, '#mp-tag-cost', 2000);
    const habit = M.priceTag(base, 2000, true);
    assert.equal(await page.locator('#mp-tag-delay').innerText(), M.span(habit.delay) + ' later');
    assert.match(await page.locator('#mp-tag-out').innerText(), /priced twice/);
    assert.ok((await page.locator('#mp-tag-out').innerText()).includes(M.short(habit.extraCorpus)));

    // A name is text. Whatever is typed is shown, and never run.
    await page.locator('[data-act="tag-mode"][data-mode="once"]').click();
    await fill(page, '#mp-tag-name', '<img src=x onerror=__ran=1><b>phone</b>');     // inside the 40 the box takes
    await fill(page, '#mp-tag-cost', 80000);
    assert.equal(await page.locator('#mp-tag-say img, #mp-tag-say b').count(), 0);
    await page.locator('#mp-tag-keep').click();
    assert.equal(await page.locator('#mp-kept li').count(), 1);
    assert.equal(await page.locator('#mp-kept img, #mp-kept b').count(), 0, 'a typed name ran as markup');
    assert.ok((await page.locator('#mp-kept').innerText()).includes('<b>phone</b>'));
    assert.equal(await page.evaluate(() => window.__ran), undefined);
    // Kept, and still there next time.
    await settle(page);
    assert.equal((await stored(page)).tags.length, 1);
    await page.locator('[data-act="tag-drop"]').click();
    assert.equal(await page.locator('#mp-kept-card').isVisible(), false);

    /* ══ Goals come out of the same pot ═════════════════════════════════════ */
    await tab(page, 'goals');
    await page.locator('[data-act="goal-kind"][data-kind="home"]').click();
    await page.locator('#mp-goal-save').click();
    const due = M.addMonths('2026-11', 60);
    const withGoal = plan({ ...HOME, goals: [{ id: 'g', name: 'Home deposit', cost: 2000000, saved: 0, due }] });
    const card = page.locator('.mp-goal').first();
    assert.ok((await card.innerText()).includes(M.inr(withGoal.goals[0].monthly)),
      'the monthly figure on the goal is not the one that reaches it');
    assert.ok((await card.innerText()).includes(M.monthName(due, true)));
    assert.equal(await page.locator('#mp-goals-need').innerText(), M.inr(withGoal.goalsMonthly));
    assert.equal(await when(page), M.monthName(withGoal.when));
    assert.ok(withGoal.when > base.when, 'a goal did not move the date');
    assert.match(await page.locator('#mp-goals-delay').innerText(), /later/);
    assert.match(await page.locator('[data-badge="goals"]').innerText(), /^1$/);

    // More asked for than there is: said in rupees, not hidden in a total.
    await fill(page, '#mp-goal-name', 'A villa');
    await fill(page, '#mp-goal-cost', 90000000);
    await fill(page, '#mp-goal-years', 3);
    await page.locator('#mp-goal-save').click();
    await page.locator('#mp-goals-short').waitFor();
    assert.match(await page.locator('#mp-goals-short').innerText(), /ask for ₹[\d,]+ a month more than you have/);
    // Refused without a cost, and says why.
    await page.locator('#mp-goal-save').click();
    assert.match(await page.locator('#mp-goal-msg').innerText(), /needs a cost/);
    assert.equal(await page.locator('.mp-goal').count(), 2);
    // Editing keeps the goal's date unless the years are changed.
    await page.locator('.mp-goal').first().locator('[data-act="goal-edit"]').click();
    assert.equal(await page.locator('#mp-goal-years').inputValue(), '5');
    await fill(page, '#mp-goal-cost', 1500000);
    await page.locator('#mp-goal-save').click();
    await settle(page);
    assert.deepEqual((await stored(page)).goals.map(g => [g.cost, g.due])[0], [1500000, due]);
    for (const drop of await page.locator('[data-act="goal-drop"]').all()) await page.locator('[data-act="goal-drop"]').first().click();
    assert.equal(await page.locator('.mp-goal').count(), 0);
    assert.equal(await when(page), M.monthName(base.when), 'removing the goals did not give the date back');

    /* ══ The budget: nothing graded blind, and a split that adds up ═════════ */
    await tab(page, 'budget');
    assert.equal(await page.locator('#mp-grade').innerText(), '—', 'a budget nobody itemised was graded');
    assert.match(await page.locator('#mp-health').innerText(), /No grade yet/);
    assert.match(await page.locator('#mp-ledger').innerText(), /itemise to judge/);

    const cats = { e_rent: 30000, e_groc: 15000, e_eat: 12000, e_shop: 8000 };
    for (const [id, v] of Object.entries(cats)) await fill(page, `[data-f="cats.${id}"]`, v);
    await fill(page, '[data-f="liquid"]', 200000);
    const itemised = plan({ ...HOME, liquid: '200000', cats });
    assert.equal(await page.locator('#mp-grade').innerText(), itemised.health.grade);
    assert.equal(await page.locator('#mp-keep').innerText(), M.inr(itemised.leftover));
    // The itemised total replaces the single figure, visibly, and it is locked.
    await tab(page, 'date');
    assert.equal(await page.locator('#mp-spend').inputValue(), '65,000');
    assert.equal(await page.locator('#mp-spend').getAttribute('readonly') !== null, true);
    assert.match(await page.locator('#mp-spend-note').innerText(), /itemised budget/);
    assert.equal(await when(page), M.monthName(itemised.when));
    // Now there is a want to trim, and the trim is theirs.
    assert.match(await page.locator('[data-move="trim"]').locator('xpath=..').innerText(), /Trim eating out by a quarter: ₹3,000/);

    await tab(page, 'budget');
    const parts = {};
    for (const k of ['cushion', 'goals', 'longRun']) {
      parts[k] = Number((await page.locator(`#mp-pay-rows [data-part="${k}"]`).innerText()).replace(/[^\d]/g, ''));
    }
    assert.equal(parts.cushion + parts.goals + parts.longRun, itemised.put,
      'the salary-day figures do not add up to what is put away');
    assert.deepEqual(parts, { cushion: itemised.split.cushion, goals: itemised.split.goals, longRun: itemised.split.longRun });
    assert.ok(parts.cushion > 0, 'a cushion short of six months was not being filled');

    // Allocate sizes its cushion from these without asking again.
    const published = await page.evaluate(() => window.AltahaPlannerState);
    assert.equal(published.expenses, 65000);
    assert.equal(published.liquid, 200000);
    assert.equal(published.income, 120000);
    assert.equal(published.efGap, itemised.cushion.gap);

    await page.locator('[data-act="bud-clear"]').click();
    await tab(page, 'date');
    assert.equal(await page.locator('#mp-spend').inputValue(), '70,000', 'clearing the itemised budget lost the single figure');

    /* ══ Tax: the figures the old planner gave, to the rupee ════════════════ */
    await tab(page, 'tax');
    await fill(page, '#mp-tax-gross', 1500000);
    assert.equal(await page.locator('#mp-tax-new .ptv').innerText(), '₹97,500');
    assert.equal(await page.locator('#mp-tax-old .ptv').innerText(), '₹2,57,400');
    assert.match(await page.locator('#mp-tax-verdict').innerText(), /new regime saves you ₹1,59,900/);
    assert.equal(await page.locator('#mp-tax-new.win').count(), 1);

    /* ══ The questionnaire lives in the last tab ════════════════════════════ */
    assert.equal(await page.locator('#riskprofile').isVisible(), false);
    await page.evaluate(() => window.AltahaPlanner.open('risk'));
    await page.locator('#mp-panel-risk #riskprofile').waitFor({ state: 'visible' });
    await page.locator('#prisk_body .prq').first().waitFor();
    assert.equal(await page.locator('#mp-tab-risk').getAttribute('aria-selected'), 'true');
    // Tabs by keyboard, as a tab list should be.
    await page.locator('#mp-tab-risk').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#mp-tab-date').getAttribute('aria-selected'), 'true');
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#mp-panel-tag').isVisible(), true);

    /* ══ The check-in, and the month turning ════════════════════════════════ */
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.locator('#mp-chip-checkin').click();
    await page.locator('#mp-panel-checkin').waitFor({ state: 'visible' });
    assert.match(await page.locator('#mp-ck-status').innerText(), /November: due/i);
    assert.equal(await page.locator('#mp-ck-invested').inputValue(), '8,00,000');
    await page.locator('#mp-ck-invested').fill('');
    await page.locator('#mp-ck-go').click();
    assert.match(await page.locator('#mp-ck-msg').innerText(), /Type what you have invested/);
    await fill(page, '#mp-ck-invested', 850000);
    await page.locator('#mp-ck-go').click();
    assert.match(await page.locator('#mp-ck-status').innerText(), /November: done · 1 month running/i);
    assert.match(await page.locator('#mp-hero').innerText(), /Checked in for November/);
    assert.match(await page.locator('#mp-ck-out').innerText(), /First dot on the chart[\s\S]*December/);
    // The plan now starts from what was logged.
    assert.equal(await page.locator('#mp-invested').inputValue(), '8,50,000');
    assert.equal(await when(page), M.monthName(plan({ ...HOME, liquid: '200000', invested: '850000' }).when));
    await settle(page);
    assert.deepEqual((await stored(page)).log.map(e => [e.ym, e.invested]), [['2026-11', 850000]]);
    assert.deepEqual(errors, []);
    await context.close();

    // A fortnight on, in December. The same browser, so the same storage.
    ({ context, page, errors } = await fresh(browser, { width: 1280, height: 900 }, LATER));
    await returning(page, {
      v: 1, ...HOME, invested: '850000', liquid: '200000',
      log: [{ ym: '2026-10', invested: 800000, liquid: 200000 }, { ym: '2026-11', invested: 850000, liquid: 200000 }],
      seen: { on: '2026-11-19', when: '2040-01' }
    });
    const dec = plan({ ...HOME, invested: '850000', liquid: '200000' }, LATER);
    assert.equal(await when(page), M.monthName(dec.when));
    assert.match(await page.locator('#mp-chip-checkin').innerText(), /December check-in due/);
    assert.equal(await page.locator('[data-badge="checkin"].dot').count(), 1);
    // Told how far the date has moved since they last looked, and when that was.
    assert.match(await page.locator('.mp-since').innerText(), /further off than when you last looked, on 19 Nov/);
    await page.locator('#mp-chip-checkin').click();
    // Two months running, and December only due — not a streak broken on the 3rd.
    assert.match(await page.locator('#mp-ck-status').innerText(), /December: due · 2 months running/i);
    await fill(page, '#mp-ck-invested', 910000);
    await page.locator('#mp-ck-go').click();
    assert.match(await page.locator('#mp-ck-status').innerText(), /December: done · 3 months running/i);
    const expected = M.project(850000, 1, dec.params);
    assert.equal(await page.locator('#mp-ck-diff').innerText(),
      M.short(Math.abs(910000 - expected)) + (910000 >= expected ? ' ahead' : ' behind'));
    await page.locator('#mp-ck-chart svg').waitFor();
    assert.equal(await page.locator('#mp-ck-chart circle.mp-pt.s1').count() >= 3, true);
    assert.equal(await page.locator('#mp-ck-log tbody tr').count(), 3);
    // Logging the same month again corrects it rather than adding a second.
    await fill(page, '#mp-ck-invested', 915000);
    await page.locator('#mp-ck-go').click();
    await settle(page);
    assert.deepEqual((await stored(page)).log.map(e => e.ym), ['2026-10', '2026-11', '2026-12']);
    assert.equal((await stored(page)).log[2].invested, 915000);
    await page.evaluate(() => document.getElementById('mp-ck-chart').scrollIntoView({ block: 'center' }));
    await page.screenshot({ path: path.join(output, '1280-checkin.png') });

    // What goes to WhatsApp: the date and the percentages. Never an amount.
    await page.evaluate(() => { window.__shared = null; window.open = (u) => { window.__shared = u; return null; }; window.scrollTo(0, 0); });
    await page.locator('[data-act="share"]').click();
    const text = decodeURIComponent((await page.evaluate(() => window.__shared)).split('text=')[1]);
    assert.ok(text.includes(await when(page)) && /#portfolio\/planner/.test(text));
    assert.match(text, /3 monthly check-ins in a row/);
    assert.doesNotMatch(text, /₹|\d{1,2},\d{2},\d{3}|\d{5,}/, 'an amount went into the shared text');

    // The My money overview says what the planner says.
    await page.locator('#sh-doorbar .sh-pill[data-tab="money"]').click();
    await page.locator('#drm-planner').waitFor({ state: 'visible' });
    assert.ok((await page.locator('#drm-planner').innerText()).includes('Work becomes optional in ' + await page.evaluate(() => {
      const s = window.AltahaPlanner.summary(), p = s.when.split('-');
      return ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][p[1] - 1] + ' ' + p[0];
    })));
    assert.deepEqual(errors, []);
    await context.close();

    /* ══ An example, and wiping the lot ═════════════════════════════════════ */
    ({ context, page, errors } = await fresh(browser, { width: 1280, height: 900 }));
    await open(page);
    await page.locator('[data-act="example"]').click();
    assert.match(await when(page), /^[A-Z][a-z]+ 20\d\d$/);
    assert.match(await page.locator('.mp-example').innerText(), /sample numbers, not yours/i);
    // Somebody else's numbers are not this reader's date: not to share, and
    // not on the overview card.
    assert.equal(await page.locator('[data-act="share"]').count(), 0);
    assert.equal(await page.evaluate(() => window.AltahaPlanner.summary().example), true);
    // Changing one makes it theirs.
    await fill(page, '#mp-age', 41);
    assert.equal(await page.locator('.mp-example').count(), 0);
    await settle(page);
    assert.notEqual(await stored(page), null);
    page.once('dialog', d => d.accept());
    await page.locator('[data-act="reset"]').click();
    assert.match(await when(page), /When does work become optional\?/);
    assert.equal(await page.locator('#mp-age').inputValue(), '');
    await settle(page);
    assert.equal(await stored(page), null, 'clearing left the numbers in the browser');
    assert.deepEqual(errors, []);
    await context.close();

    /* ══ A path with no date says why, and never invents one ════════════════ */
    ({ context, page, errors } = await fresh(browser, { width: 1280, height: 900 }));
    await open(page);
    await fill(page, '#mp-salary', 60000);
    await fill(page, '#mp-spend', 75000);
    assert.match(await when(page), /You spend ₹15,000 more than you take home/);
    assert.match(await page.locator('#mp-hero .mp-eyebrow').innerText(), /no date on this path yet/i);
    assert.doesNotMatch(await page.locator('#view-planner').innerText(), /NaN|undefined|Infinity/);
    await fill(page, '#mp-spend', 20000);
    await fill(page, '#mp-invested', 90000000);
    assert.match(await when(page), /Work is optional/);
    assert.deepEqual(errors, []);
    await context.close();

    /* ══ A phone ════════════════════════════════════════════════════════════ */
    ({ context, page, errors } = await fresh(browser, { width: 390, height: 844 }));
    await returning(page, {
      v: 1, ...HOME, liquid: '200000',
      cats: { e_rent: '30000', e_groc: '15000', e_health: '4000', e_eat: '12000', e_shop: '8000' },
      goals: [{ id: 'g1', name: 'Home deposit', kind: 'home', cost: 2000000, saved: 100000, due: '2031-11' }],
      tags: [{ id: 't1', name: 'A new phone', cost: 80000, monthly: false }],
      log: [{ ym: '2026-09', invested: 760000, liquid: 200000 }, { ym: '2026-10', invested: 800000, liquid: 200000 }]
    });
    assert.match(await when(page), /^[A-Z][a-z]+ 20\d\d$/);
    // The ring has no room beside the date; the same reading is a bar under it.
    assert.equal(await page.locator('.mp-ring').isVisible(), false);
    assert.equal(await page.locator('.mp-bar').isVisible(), true);
    await page.locator('[data-move="more"]').check();
    for (const id of ['date', 'tag', 'goals', 'checkin', 'budget', 'tax', 'risk']) {
      await page.locator('#mp-tab-' + id).click();
      await page.locator('#mp-panel-' + id).waitFor({ state: 'visible' });
      if (id === 'tag') await fill(page, '#mp-tag-cost', 80000);
      if (id === 'tax') await fill(page, '#mp-tax-gross', 2400000);
      await page.waitForTimeout(120);
      const wide = await page.evaluate(() => {
        const limit = document.documentElement.clientWidth;
        const over = [...document.querySelectorAll('#mp *')].filter(e => {
          if (!e.offsetParent || e.closest('.mp-tabs, .mp-scroll')) return false;
          const r = e.getBoundingClientRect();
          return r.width > 0 && (r.right > limit + 1 || r.left < -1);
        }).map(e => (e.id || e.className || e.tagName) + ' ' + Math.round(e.getBoundingClientRect().right));
        return { page: document.documentElement.scrollWidth - limit, over: over.slice(0, 5) };
      });
      assert.ok(wide.page <= 0, `${id}: the page scrolls sideways on a phone`);
      assert.deepEqual(wide.over, [], `${id}: something runs off the side of a phone`);
      // A tapped tool is on the screen: under the hero it used to open below
      // the fold, with nothing visibly changing.
      const top = await page.evaluate(i => document.getElementById('mp-panel-' + i).getBoundingClientRect().top, id);
      assert.ok(top > 100 && top < 844 * 0.5, `${id}: opened at ${Math.round(top)}px, off the top or below the fold`);
      await page.screenshot({ path: path.join(output, `390-${id}.png`) });
    }
    // Deep in the longest tool, the tabs are still there, and the next tool
    // opens at its own heading rather than wherever the last one was scrolled.
    await page.locator('#mp-tab-budget').click();
    await page.evaluate(() => window.scrollBy(0, 1400));
    await page.waitForTimeout(150);
    const strip = await page.locator('#mp-tabs').boundingBox();
    assert.ok(strip.y > 60 && strip.y < 200, 'the tool tabs scrolled away inside a long tool');
    await page.locator('#mp-tab-tax').click();
    await page.waitForTimeout(150);
    const landed = await page.evaluate(() => ({
      panel: document.getElementById('mp-panel-tax').getBoundingClientRect().top,
      footer: (document.querySelector('.sh-foot, footer') || document.body).getBoundingClientRect().top }));
    assert.ok(landed.panel > 100 && landed.panel < 420, 'leaving a long tool for a short one lost the reader below it');
    // Every box is a real 16px input: a smaller one makes an iPhone zoom on focus.
    const sizes = await page.evaluate(() => [...document.querySelectorAll('#mp input.mp-in')]
      .map(i => parseFloat(getComputedStyle(i).fontSize)));
    assert.ok(sizes.length > 20 && sizes.every(px => px >= 16));
    // The chart is the width it has, not the width it was first drawn at.
    await page.locator('#mp-tab-date').click();
    const narrow = await page.locator('#mp-path-chart svg').boundingBox();
    assert.ok(narrow.width <= 390 && narrow.width > 250);
    assert.deepEqual(errors, []);
    await context.close();

    /* ══ Nothing typed ever left the browser ════════════════════════════════ */
    const figures = /120000|1,20,000|70000|800000|850000|910000|2000000|1500000|90000000/;
    const leaked = sent.filter(line => !line.includes('127.0.0.1') && figures.test(decodeURIComponent(line)));
    assert.deepEqual(leaked, [], 'a figure typed into the planner was sent somewhere');
    assert.deepEqual(sent.filter(line => /^(POST|PUT|PATCH)/.test(line) && /planner/.test(line)), []);

    console.log('Planner: a date from four numbers, kept, moved by what should move it, and nothing leaves the browser.');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
