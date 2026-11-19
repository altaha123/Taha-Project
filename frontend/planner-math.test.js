'use strict';
/* The planner's arithmetic, without a browser.
 *
 * The planner answers with a date, and a date is easy to get plausibly wrong:
 * nothing throws when a purchase moves it by "0 months", when three rupee
 * figures on the salary-day plan add up to a rupee more than was saved, or
 * when a budget nobody itemised is handed an A for having no EMIs. Those are
 * the things pinned here. The clock is always passed in — a test that reads
 * the real date passes in November and fails in December.
 */
const assert = require('node:assert/strict');
const m = require('./planner-math.js');

const NOW = new Date(2026, 10, 19);            // 19 November 2026
const HOME = { age: 30, salary: 120000, spend: 70000, invested: 800000, liquid: 200000 };
const plan = (over) => m.derive(Object.assign({}, HOME, over || {}), NOW);

/* ── There is a date, and it behaves ────────────────────────────────────────── */
const base = plan();
assert.equal(base.status, 'dated');
assert.equal(base.now, '2026-11');
assert.match(base.when, /^20\d\d-\d\d$/);
assert.equal(base.sim.target, 70000 * 12 * 30, 'freedom is thirty times a year of spending');
assert.equal(base.when, m.addMonths('2026-11', Math.ceil(base.sim.months)));
assert.equal(base.ageThen, Math.round(30 + base.sim.months / 12));
assert.ok(base.progress > 0.03 && base.progress < 0.04, 'eight lakh of 2.52 crore is about 3%');

// Saving more, starting with more, and spending less each bring it closer.
assert.ok(plan({ salary: 140000 }).sim.months < base.sim.months);
assert.ok(plan({ invested: 2000000 }).sim.months < base.sim.months);
assert.ok(plan({ spend: 60000 }).sim.months < base.sim.months);
// The dials do what they say.
assert.ok(plan({ stepUp: 10 }).sim.months < base.sim.months);
assert.ok(plan({ ret: 8 }).sim.months > base.sim.months);
assert.ok(plan({ infl: 8 }).sim.months > base.sim.months,
  'the model is in today\'s rupees: higher inflation has to push the date out');
assert.ok(plan({ multiple: 25 }).sim.months < base.sim.months);
assert.ok(plan({ after: 80 }).sim.months < base.sim.months);
// Blank is the default; zero is an answer.
assert.equal(plan({ stepUp: '' }).a.stepUp, 5);
assert.equal(plan({ stepUp: 0 }).a.stepUp, 0);
assert.ok(plan({ stepUp: 0 }).sim.months > base.sim.months);

/* ── No numbers, no date — and never a made-up one ──────────────────────────── */
assert.equal(m.derive({}, NOW).status, 'empty');
assert.equal(m.derive({ salary: 100000 }, NOW).status, 'empty', 'income alone says nothing about when');
assert.equal(m.derive({}, NOW).when, null);

const over = plan({ spend: 150000, invested: 0 });
assert.equal(over.status, 'none');
assert.equal(over.why, 'overspend');
assert.equal(over.when, null);
assert.equal(over.put, 0, 'a negative amount cannot be put away');

assert.equal(plan({ invested: 30000000 }).status, 'free');
assert.equal(plan({ invested: 30000000 }).sim.months, 0);
assert.equal(plan({ invested: 30000000 }).progress, 1);

/* ── What was typed wins over what was assumed ──────────────────────────────── */
assert.equal(base.put, 50000, 'left blank, everything left over is put away');
assert.equal(plan({ put: '30000' }).put, 30000);
assert.equal(plan({ put: '0' }).put, 0);
assert.equal(plan({ put: '' }).put, 50000);
assert.equal(plan({ salary: '1,20,000' }).income, 120000, 'a figure typed with commas is still a figure');

// An itemised budget replaces the single spending total.
const itemised = plan({ cats: { e_rent: 30000, e_groc: 15000, e_eat: 12000, e_shop: 8000 } });
assert.equal(itemised.itemised, true);
assert.equal(itemised.expenses, 65000);
assert.equal(itemised.needs, 45000);
assert.equal(itemised.wants, 20000);
assert.equal(itemised.topWant.id, 'e_eat');
assert.equal(base.itemised, false);

/* ── The salary-day split adds up, to the rupee ─────────────────────────────── */
[[50000, 18333.4, 12345.6], [1000, 5000, 5000], [0, 100, 100], [73219, 0, 80000], [99999, 33333.3, 33333.3]]
  .forEach(([put, cushion, goals]) => {
    const s = m.split(put, cushion, goals);
    assert.equal(s.cushion + s.goals + s.longRun, s.put, `the split of ${put} does not add up`);
    assert.ok(s.cushion >= 0 && s.goals >= 0 && s.longRun >= 0);
  });
assert.equal(m.split(10000, 2000, 12000).short, 4000, 'goals asking for more than is saved is said, in rupees');
assert.equal(m.split(10000, 2000, 3000).short, 0);

// The cushion is six months of spending, never takes more than half of what
// is saved, and stops when it is full.
const cush = m.cushion(70000, 200000, 50000);
assert.equal(cush.target, 420000);
assert.equal(cush.gap, 220000);
assert.ok(cush.monthly <= 25000);
assert.ok(cush.monthly * cush.months >= cush.gap);
assert.equal(cush.months, 12, 'a gap filled over a year was quoted as thirteen months');
assert.equal(m.cushion(70000, 0, 10001).monthly, 5000, 'half of what is saved, rounded down, never up');
assert.equal(m.cushion(70000, 500000, 50000).monthly, 0);
assert.equal(m.cushion(70000, 0, 10000).monthly, 5000, 'never more than half of what is saved');
assert.equal(base.split.cushion + base.split.goals + base.split.longRun, base.put);

/* ── Goals: the date decides the bucket, and the monthly figure gets there ──── */
const soon = m.goalPlan({ cost: 500000, saved: 0, due: '2028-11' }, '2026-11', base.a);
const mid = m.goalPlan({ cost: 1500000, saved: 100000, due: '2031-11' }, '2026-11', base.a);
const far = m.goalPlan({ cost: 3000000, saved: 0, due: '2041-11' }, '2026-11', base.a);
assert.equal(soon.bucket, 'safe');
assert.equal(mid.bucket, 'mixed');
assert.equal(far.bucket, 'growth');
assert.equal(soon.rate, m.SAFE_RATE);
assert.equal(far.rate, 10);
assert.ok(mid.future > 1500000, 'a goal five years out costs more than it does today');
// Pay the monthly figure, at the assumed rate, and the goal is met.
[soon, mid, far].forEach((g, i) => {
  const rm = m.monthlyRate(g.rate);
  let pot = [0, 100000, 0][i];
  for (let k = 0; k < g.months; k++) pot = pot * (1 + rm) + g.monthly;
  assert.ok(Math.abs(pot - g.future) < 1, 'the monthly amount does not reach the goal');
});
assert.equal(m.goalPlan({ cost: 100000, saved: 500000, due: '2028-11' }, '2026-11', base.a).monthly, 0);
assert.equal(m.goalPlan({ cost: 100000, saved: 0, due: '2020-01' }, '2026-11', base.a).months, 1,
  'a goal whose date has passed is due now, not in negative time');

// A goal is paid for out of the same pot, so it moves the date — later.
const withGoal = plan({ goals: [{ id: 'g1', name: 'Home deposit', cost: 1500000, saved: 0, due: '2031-11' }] });
assert.ok(withGoal.sim.months > base.sim.months);
assert.ok(withGoal.split.goals > 0);
assert.equal(withGoal.split.cushion + withGoal.split.goals + withGoal.split.longRun, withGoal.put);
const greedy = plan({ goals: [{ id: 'g2', name: 'Villa', cost: 90000000, saved: 0, due: '2029-11' }] });
assert.ok(greedy.split.short > 0);
assert.equal(greedy.split.longRun, 0);

/* ── Health: a check that cannot be judged is not a pass ────────────────────── */
assert.equal(base.health.grade, null, 'a budget nobody itemised was graded');
assert.equal(base.health.pass.emi, 'na');
assert.equal(base.health.pass.split, 'na');
assert.equal(base.health.pass.rate, true);
assert.equal(base.health.pass.cover, false, 'under three months of cover is a fail');
assert.ok(['A', 'B+', 'B', 'C', 'D'].includes(itemised.health.grade));
const tight = plan({ salary: 100000, liquid: 0,
  cats: { e_rent: 55000, e_groc: 15000, e_eat: 30000 } });
assert.equal(tight.health.pass.emi, false);
assert.equal(tight.health.pass.rate, false);
assert.equal(tight.health.grade, 'D');
assert.equal(m.health({ income: 0, expenses: 10 }), null);

/* ── What moves the date ────────────────────────────────────────────────────── */
const moves = m.moves(itemised);
const by = Object.fromEntries(moves.map(x => [x.id, x]));
['more', 'stepup', 'trim', 'lean', 'keep'].forEach(id => {
  assert.equal(by[id].kind, 'sooner');
  assert.ok(by[id].delta > 0, `${id} did not bring the date closer`);
});
['creep', 'wait', 'costs'].forEach(id => {
  assert.equal(by[id].kind, 'later');
  assert.ok(by[id].delta < 0, `${id} did not push the date away`);
});
assert.equal(by.trim.name, 'eating out', 'the trim is offered on the biggest want');
assert.equal(by.trim.amount, 3000);
assert.ok(!m.moves(base).some(x => x.id === 'trim'), 'a trim was offered with no itemised wants to trim');

// Ticked together they compound, and a later-only id is ignored.
const both = m.combine(itemised, ['more', 'stepup']);
assert.ok(both.delta > Math.max(by.more.delta, by.stepup.delta));
assert.equal(both.when, m.addMonths('2026-11', Math.ceil(both.sim.months)));
assert.equal(m.combine(itemised, []), null);
assert.equal(m.combine(itemised, ['creep']), null);
// The plan itself is not disturbed by asking what-if.
assert.equal(m.derive(Object.assign({}, HOME), NOW).sim.months, base.sim.months);
m.moves(base); m.combine(base, ['more']);
assert.equal(base.params.monthly, 50000);
assert.equal(base.params.drains.length, 1);

// Nothing left over and nothing invested: no date, and no move here conjures
// one — raising a saving of zero by 10% a year is still zero.
const stuck = plan({ salary: 70000, spend: 70000, invested: 0 });
assert.equal(stuck.status, 'none');
assert.equal(stuck.why, 'nothing');
assert.ok(m.moves(stuck).every(x => x.delta === null));
// A thin margin is different: the path has no date inside sixty years, and a
// move can be the thing that puts one on it.
const thin = plan({ salary: 78000, spend: 70000, invested: 0, liquid: 500000 });
assert.equal(thin.status, 'none');
assert.equal(thin.why, 'far');
assert.ok(m.moves(thin).some(x => x.unlocks));
assert.ok(m.moves(thin).filter(x => x.unlocks).every(x => x.kind === 'sooner' && x.delta === null));

/* ── The price of a thing, in time ──────────────────────────────────────────── */
const phone = m.priceTag(base, 80000, false);
assert.ok(phone.delay > 0);
const small = m.priceTag(base, 5000, false);
assert.ok(small.delay > 0 && small.delay < 1,
  'a small purchase rounded to nothing; the date is interpolated so it should not');
assert.ok(Math.abs(phone.workDays - 80000 / (120000 / 22)) < 1e-9);
assert.ok(phone.grown > 80000, 'left invested until the date it is worth more than it cost');
// A monthly habit costs twice: less invested, and a bigger finish line.
const habit = m.priceTag(base, 2000, true);
assert.equal(habit.extraCorpus, 2000 * 12 * 30);
assert.ok(habit.delay > m.priceTag(base, 2000 * 12, false).delay * 5);
assert.equal(m.priceTag(over, 80000, false).delay, null, 'no date to move means no delay to quote');
assert.equal(m.priceTag(over, 80000, false).dated, false);

/* ── The check-in ───────────────────────────────────────────────────────────── */
assert.deepEqual(m.streak([], '2026-11'), { count: 0, due: true, last: null });
assert.deepEqual(m.streak([{ ym: '2026-09' }, { ym: '2026-10' }], '2026-11'),
  { count: 2, due: true, last: '2026-10' }, 'a streak was broken by a month that is not over');
assert.deepEqual(m.streak([{ ym: '2026-09' }, { ym: '2026-10' }, { ym: '2026-11' }], '2026-11'),
  { count: 3, due: false, last: '2026-11' });
assert.equal(m.streak([{ ym: '2026-08' }, { ym: '2026-11' }], '2026-11').count, 1);
assert.equal(m.streak([{ ym: '2026-08' }], '2026-11').count, 0);
assert.equal(m.streak([{ ym: '2025-12' }, { ym: '2026-01' }], '2026-01').count, 2, 'a streak stopped at new year');

// Held against nominal rupees, because a statement is nominal.
assert.equal(m.project(100000, 12, { ret: 0, monthly: 5000, stepUp: 0, drains: [] }), 160000);
assert.ok(m.project(100000, 12, { ret: 10, monthly: 0, stepUp: 0, drains: [] }) - 110000 < 1e-6);
assert.equal(m.project(0, 24, { ret: 0, monthly: 1000, stepUp: 10, drains: [] }), 12000 + 13200);
assert.equal(m.project(0, 12, { ret: 0, monthly: 1000, stepUp: 0, drains: [{ monthly: 400, months: 6 }] }),
  6 * 600 + 6 * 1000);

/* ── Tax: old against new ───────────────────────────────────────────────────── */
assert.equal(m.tax({}), null);
assert.equal(m.tax({ gross: 0 }), null);
// ₹12.75 lakh of salary is the well-known nil point of the new regime.
assert.equal(m.tax({ gross: 1275000 }).neu.tax, 0);
// Just above it, marginal relief: the tax is the excess, not a cliff.
assert.equal(m.tax({ gross: 1280000 }).neu.tax, Math.round(5000 * 1.04));
const fifteen = m.tax({ gross: 1500000 });
assert.equal(fifteen.neu.taxable, 1425000);
assert.equal(fifteen.neu.tax, 97500);
assert.equal(fifteen.old.tax, 257400);
assert.equal(fifteen.winner, 'new');
assert.equal(fifteen.saving, 159900);
const capped = m.tax({ gross: 2400000, c80: 900000, nps: 900000, hl: 900000 });
assert.equal(capped.deductions, 50000 + 150000 + 50000 + 200000, 'a deduction went past its legal cap');
assert.equal(m.tax({ gross: 550000 }).old.tax, 0, 'the old-regime rebate up to five lakh taxable');
const heavy = m.tax({ gross: 1500000, c80: 150000, d80: 75000, nps: 50000, hl: 200000, hra: 300000 });
assert.equal(heavy.winner, 'old');
assert.equal(heavy.flip, null);
assert.equal(m.tax({ gross: 300000 }).winner, 'either');

/* ── Words and figures ──────────────────────────────────────────────────────── */
assert.equal(m.inr(120000), '₹1,20,000');
assert.equal(m.inr(-4500.4), '−₹4,500');
assert.equal(m.short(25200000), '₹2.52 Cr');
assert.equal(m.short(800000), '₹8 L');
assert.equal(m.short(1250000), '₹12.5 L');
assert.equal(m.short(45000), '₹45,000');
assert.equal(m.short(99960), '₹1 L', 'a figure a rupee short of a lakh printed as 99,960 beside one printed as 1 L');
assert.equal(m.short(9996000), '₹1 Cr');
assert.equal(m.short(-250000), '−₹2.5 L');
assert.equal(m.span(0.01), 'under a day');
assert.equal(m.span(0.2), '6 days');
assert.equal(m.span(1), '4 weeks');
assert.equal(m.span(7), '7 months');
assert.equal(m.span(12), '1 year');
assert.equal(m.span(13), '1 year 1 month');
assert.equal(m.span(172.3), '14 years 4 months');
assert.equal(m.span(-7), '7 months', 'a span is a length; the caller says which way');
assert.equal(m.monthName('2041-03'), 'March 2041');
assert.equal(m.monthName('2041-03', true), 'Mar 2041');
assert.equal(m.addMonths('2026-11', 2), '2027-01');
assert.equal(m.addMonths('2026-01', -1), '2025-12');
assert.equal(m.monthsBetween('2026-11', '2031-11'), 60);
assert.equal(m.ymOf(new Date(2027, 0, 1)), '2027-01');

console.log('Planner arithmetic: the date moves the right way, the split adds up, and nothing is graded blind.');
