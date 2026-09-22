'use strict';
/* The arithmetic behind the guided Allocate card, without a browser.
 *
 * Three things are worth pinning here and nowhere else. The profile is the
 * LOWER of capacity and temperament — a flattering average is how somebody
 * ends up holding a portfolio they sell at the bottom. The slider has to
 * reach the sum a person actually has, at every order of magnitude between
 * ₹1 and ₹20 crore, and hand back exactly what it was set to. And the split
 * shown in words by the step list has to be the same split the card turns
 * into rupees; those two drifting apart is the kind of bug nobody notices
 * until a reader adds them up.
 */
const assert = require('node:assert/strict');
const math = require('./risk-math.js');
const flow = require('./allocate-flow.js');

const QUESTIONS = [
  { id: 'horizon', axis: 'capacity', weight: 24,
    options: [{ value: 'under1', score: 0 }, { value: '10plus', score: 100 }] },
  { id: 'emergency', axis: 'capacity', weight: 16,
    options: [{ value: 'none', score: 0 }, { value: 'over12', score: 100 }] },
  { id: 'drawdown_action', axis: 'tolerance', weight: 34,
    options: [{ value: 'sell_all', score: 0 }, { value: 'buy_more', score: 100 }] },
  { id: 'max_fall', axis: 'tolerance', weight: 26,
    options: [{ value: 'any', score: 0 }, { value: '40plus', score: 100 }] },
  { id: 'purpose', axis: 'context', weight: 0, options: [{ value: 'retirement' }] }
];
const BANDS = [
  { from: 0, to: 20, band: 'Conservative', note: 'Capital first.' },
  { from: 20, to: 40, band: 'Moderately conservative', note: '' },
  { from: 40, to: 60, band: 'Balanced', note: '' },
  { from: 60, to: 80, band: 'Growth', note: '' },
  { from: 80, to: 101, band: 'Aggressive', note: 'Patience is the constraint.' }
];

/* ── The lower of the two decides ───────────────────────────────────────────── */
const brave = { horizon: 'under1', emergency: 'none',
                drawdown_action: 'buy_more', max_fall: '40plus' };
const cautious = { horizon: '10plus', emergency: 'over12',
                   drawdown_action: 'sell_all', max_fall: 'any' };

let p = math.assess(brave, QUESTIONS, BANDS);
assert.equal(p.capacity, 0);
assert.equal(p.tolerance, 100);
assert.equal(p.score, 0, 'temperament must never lift a profile its circumstances cannot carry');
assert.equal(p.band, 'Conservative');
assert.equal(p.binding, 'capacity');

p = math.assess(cautious, QUESTIONS, BANDS);
assert.equal(p.score, 0, 'circumstances must never lift a profile its owner could not sit through');
assert.equal(p.binding, 'tolerance');

p = math.assess({ ...brave, horizon: '10plus', emergency: 'over12' }, QUESTIONS, BANDS);
assert.equal(p.score, 100);
assert.equal(p.band, 'Aggressive');
assert.equal(p.binding, 'both');

/* An unanswered question is not evidence of caution: it leaves the denominator. */
p = math.assess({ horizon: '10plus', drawdown_action: 'buy_more' }, QUESTIONS, BANDS);
assert.equal(p.capacity, 100);
assert.equal(p.tolerance, 100);
assert.equal(math.assess({ horizon: '10plus' }, QUESTIONS, BANDS), null,
  'one axis alone is not a profile');
assert.equal(math.assess({}, QUESTIONS, BANDS), null);

/* Context questions carry no weight and must never move a band. */
const withContext = math.assess({ ...brave, purpose: 'retirement' }, QUESTIONS, BANDS);
assert.equal(withContext.score, math.assess(brave, QUESTIONS, BANDS).score);
assert.equal(math.required(QUESTIONS).length, 4);
assert.equal(math.remaining({ horizon: '10plus' }, QUESTIONS).length, 3);

console.log('Risk arithmetic: 14 assertions passed');

/* ── The slider reaches every order of magnitude, exactly ─────────────────── */
assert.equal(flow.sliderToRupees(0), 1, 'the track starts at ₹1');
assert.equal(flow.sliderToRupees(10000), 200000000, 'and ends at ₹20 crore');
assert.equal(flow.sliderToRupees(-50), 1);
assert.equal(flow.sliderToRupees(99999), 200000000);
assert.equal(flow.sliderToRupees('nonsense'), 1);

for (const amount of [1, 1000, 50000, 100000, 500000, 2500000, 10000000, 50000000, 200000000]) {
  const pos = flow.rupeesToSlider(amount);
  assert.equal(flow.sliderToRupees(pos), amount,
    `picking ${amount} then nudging the slider must not move the figure`);
  assert.ok(pos >= 0 && pos <= 10000);
}
// Monotonic, and the range this card is for gets most of the track.
let last = -1;
for (let pos = 0; pos <= 10000; pos += 25) {
  const v = flow.sliderToRupees(pos);
  assert.ok(v >= last, 'the scale must never go backwards');
  last = v;
}
assert.ok(flow.rupeesToSlider(100000) / 10000 <= 0.25,
  '₹1 lakh must sit in the first quarter, or the useful range is squeezed into the end');
// Rounded to something a person would say out loud.
assert.equal(flow.snap(1034771), 1025000);   // ₹25,000 steps above ₹10 lakh
assert.equal(flow.snap(0), 1);
assert.equal(flow.snap(9e9), 200000000);
assert.equal(flow.words(15000000), '₹1.5 Cr');
assert.equal(flow.words(250000), '₹2.5 L');
assert.equal(flow.words(45000), '₹45K');

console.log('Amount slider: 34 assertions passed');

/* ── The split, in rupees ───────────────────────────────────────────────────── */
const built = flow.plan('Balanced', 10000000, { horizon: '10plus', emergency: '6_12' });
const total = built.groups.reduce((sum, g) => sum + g.share.rupees_mid, 0);
assert.ok(Math.abs(total - 10000000) <= 3,
  'the midpoints of the three sleeves must account for the whole sum');
for (const g of built.groups) {
  assert.ok(g.share.rupees_low <= g.share.rupees_mid && g.share.rupees_mid <= g.share.rupees_high);
  const inner = g.sleeves.reduce((sum, s) => sum + s.rupees, 0);
  assert.ok(Math.abs(inner - g.share.rupees_mid) <= 2, `${g.label} sleeves must sum to the sleeve`);
  for (const s of g.sleeves) assert.ok(s.why, 'every category says why it is there');
}
assert.equal(flow.plan('Balanced', 0, {}), null);
assert.equal(flow.plan('Not a band', 100000, {}), null);

/* The flags are the part that matters most. */
const soon = flow.plan('Aggressive', 1000000, { horizon: '1_3' });
assert.ok(soon.flags.some(f => f.level === 'stop'),
  'money needed within three years must be flagged however brave the profile');
// And flagged is not enough: money with a date inside three years gets no
// growth sleeve at all, however brave the profile reads.
assert.equal(soon.dated, true);
assert.equal(soon.groups.length, 1);
assert.equal(soon.groups[0].key, 'stable');
assert.equal(soon.groups[0].share.rupees_mid, 1000000);
assert.deepEqual(soon.groups[0].sleeves.map(s => s.label),
  ['Bank fixed deposits', 'Short-term bonds & debt funds'],
  'dated money is a deposit and a short bond fund, never a fifteen-year lock');
const lump = flow.plan('Growth', 1000000, { horizon: '10plus', mode: 'lumpsum' });
assert.ok(lump.flags.some(f => /lump sum/i.test(f.title)));
for (const sample of [
  soon,
  flow.plan('Balanced', 1000000, { horizon: '3_5' }),
  flow.plan('Growth', 1000000, { horizon: '10plus', emi: 'over60' }),
  lump,
]) {
  for (const flag of sample.flags) {
    assert.ok(!/step\s*\d/i.test(flag.title + ' ' + flag.text),
      `a flag still points at a removed step: ${flag.title}`);
  }
}
assert.equal(flow.plan('Growth', 1000000, { horizon: '10plus', emergency: '6_12' }).flags.length, 0);

/* ── First calls: the cushion and costly loans come off the top ───────────── */
// Without the household numbers the cushion cannot be sized, so the card asks
// rather than pretending: a call with no rupees and a `needs` marker.
const unsized = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none' });
assert.equal(unsized.first.length, 1);
assert.equal(unsized.first[0].key, 'cushion');
assert.equal(unsized.first[0].needs, 'expenses');
assert.equal(unsized.free, 1000000, 'an unsized call must not silently shrink the split');
assert.ok(!unsized.flags.some(f => /cushion/i.test(f.title)),
  'the cushion is a line with a number, not a paragraph in the flags');

// With them, the gap is six months of expenses less what is already held,
// and it comes off the sum before anything is split.
const sized = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none' }, { expenses: 50000 });
assert.equal(sized.first[0].rupees, 300000);
assert.equal(sized.free, 700000);
assert.equal(sized.first[0].rupees + sized.groups.reduce((s, g) => s + g.share.rupees_mid, 0), 1000000,
  'first calls plus sleeves must equal exactly what was put in');
// Someone already holding a month and a half is asked for less.
const partial = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'under3' }, { expenses: 50000 });
assert.equal(partial.first[0].rupees, 225000);
// A planner figure for liquid savings wins over the estimate from the answer.
const planned = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none' }, { expenses: 50000, liquid: 250000 });
assert.equal(planned.first[0].rupees, 50000);
// Six months already held: no call at all, whatever the answer said.
assert.equal(flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none' }, { expenses: 50000, liquid: 300000 }).first.length, 0);

// Costly debt is the second call and is capped at what is left.
const indebted = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none', emi: 'over60' },
  { expenses: 100000, debt: 900000 });
assert.deepEqual(indebted.first.map(c => [c.key, c.rupees]), [['cushion', 600000], ['debt', 400000]]);
assert.equal(indebted.free, 0);
assert.equal(indebted.groups.length, 0, 'nothing free, nothing split');
// Heavy EMIs with no figure: asked, not assumed.
const heavy = flow.plan('Growth', 1000000, { horizon: '10plus', emi: '40_60' });
assert.equal(heavy.first[0].key, 'debt');
assert.equal(heavy.first[0].needs, 'debt');
// The cushion can never exceed the sum.
assert.equal(flow.plan('Growth', 100000, { horizon: '10plus', emergency: 'none' }, { expenses: 50000 }).first[0].rupees, 100000);

/* ── Alternatives enter only when everything allows it ────────────────────── */
const long = { horizon: '10plus', emergency: 'over12', experience: 'over10' };
assert.equal(flow.alternatives(5000000, 'Aggressive', long), null, 'not at ₹50 lakh');
assert.equal(flow.alternatives(50000000, 'Balanced', long), null, 'not for a balanced profile');
assert.equal(flow.alternatives(50000000, 'Aggressive', { ...long, horizon: '5_10' }), null, 'not inside ten years');
assert.equal(flow.alternatives(50000000, 'Aggressive', { ...long, experience: 'under3' }), null, 'not without the years in the market');
const alt = flow.alternatives(50000000, 'Aggressive', long);
assert.equal(alt.pct, 15);
assert.deepEqual(alt.mix.map(r => r[0]), ['Alternative investment funds (Category II & III)', 'Early-stage & angel investing']);
assert.equal(alt.mix.reduce((s, r) => s + r[1], 0), 100);
// Growth at ₹5 crore: funds yes, angel no.
const growthAlt = flow.alternatives(50000000, 'Growth', long);
assert.equal(growthAlt.pct, 10);
assert.deepEqual(growthAlt.mix, [['Alternative investment funds (Category II & III)', 100]]);
// Aggressive at ₹2 crore: angel yes (a ₹25 lakh cheque is 12.5%), funds no (₹1 crore would be half).
assert.deepEqual(flow.alternatives(20000000, 'Aggressive', long).mix, [['Early-stage & angel investing', 100]]);

// When they enter, they are carved out of growth, and everything still adds up.
const rich = flow.plan('Aggressive', 100000000, long);
assert.equal(rich.groups.length, 4);
assert.equal(rich.groups[3].key, 'alt');
assert.equal(rich.groups[3].share.rupees_mid, 15000000);
assert.equal(rich.groups.reduce((s, g) => s + g.share.rupees_mid, 0), 100000000);
assert.ok(rich.groups[0].share.mid + rich.groups[3].share.mid <= 90.05, 'growth plus alternatives must stay inside the growth guardrail');
// Listed real estate joins the growth sleeve once the sum is large enough.
assert.ok(rich.groups[0].sleeves.some(s => /REIT/.test(s.label)));
assert.ok(!flow.plan('Growth', 200000, long).groups[0].sleeves.some(s => /REIT/.test(s.label)),
  'not at ₹2 lakh, where a tenth of the sleeve is not worth a separate line');
assert.ok(!flow.plan('Conservative', 5000000, long).groups[0].sleeves.some(s => /REIT/.test(s.label)));

// What was left out is said, with the reason in the reader's own numbers.
const small = flow.plan('Balanced', 1000000, { horizon: '10plus', emergency: 'over12' });
assert.deepEqual(small.left_out.map(o => o.label),
  ['Direct property', 'Alternative investment funds', 'Start-ups and angel investing', 'Crypto']);
assert.match(small.left_out[1].text, /more than all of this money/);
assert.match(flow.plan('Growth', 30000000, long).left_out[1].text, /33% of what is free/);
assert.deepEqual(rich.left_out.map(o => o.label), ['Direct property', 'Crypto'],
  'what is in the split is not also listed as left out');

/* ── Every category names the instrument, never the product ─────────────── */
for (const band of ['Conservative', 'Moderately conservative', 'Balanced', 'Growth', 'Aggressive']) {
  for (const g of flow.plan(band, 100000000, long).groups) {
    for (const s of g.sleeves) {
      const h = flow.HOWTO[s.label];
      assert.ok(h && h.holds && h.via && h.route && h.look, `${s.label} has no instrument`);
    }
  }
}
// Never a product name, never an instruction to buy or sell. The bank-count
// sentence is built per sum, so it is grepped too.
for (const [label, h] of Object.entries(flow.HOWTO)) {
  const text = [h.holds, h.via, h.route, h.look, flow.holding(label, 1800000).look].join(' ');
  assert.ok(!/\b(buy|sell)\b/i.test(text), `${label}: the route issues an instruction`);
  assert.ok(!/(HDFC|SBI|ICICI|Axis|Nippon|Mirae|Zerodha|Groww|Kuvera|Parag)/i.test(text), `${label}: names a product`);
  assert.ok(!/you should|we recommend/i.test(text), `${label}: tells the reader what to do`);
}

const grown = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'over12' });
const held = grown.groups.flatMap(g => g.sleeves.map(s => flow.HOWTO[s.label].holds)).join(' | ');
assert.match(held, /Nifty 50 index fund/);
assert.match(held, /Nifty Midcap 150/);
assert.match(held, /Nifty Smallcap 250/);
assert.match(held, /S&P 500 feeder/);
assert.match(held, /fixed deposit of one to three years/);
assert.match(held, /short-duration debt fund/);
assert.match(held, /PPF/);
assert.match(held, /Sovereign Gold Bonds/);
assert.match(held, /gold ETF/);
assert.ok(!flow.plan('Balanced', 1000000, { horizon: '10plus', emergency: 'over12' })
  .groups[0].sleeves.some(s => /Small-cap/.test(s.label)),
  'small-caps are the violent part; Balanced does not hold them');
assert.ok(!flow.plan('Conservative', 1000000, { horizon: '10plus', emergency: 'over12' })
  .groups[0].sleeves.some(s => /Mid-cap|Small-cap/.test(s.label)));

// Money needed inside three years is deposits and short bonds, never PPF.
const datedBook = flow.plan('Aggressive', 2500000, { horizon: 'under1', emergency: 'over12' });
assert.deepEqual(datedBook.groups[0].sleeves.map(s => s.label),
  ['Bank fixed deposits', 'Short-term bonds & debt funds']);

// "Which bank" is a count under the ₹5 lakh DICGC cover, not a name.
assert.match(flow.bankSpread(240000), /One scheduled commercial bank/);
assert.match(flow.bankSpread(500000), /One scheduled commercial bank/);
assert.match(flow.bankSpread(500001), /2 scheduled commercial banks/);
assert.match(flow.bankSpread(1320000), /3 scheduled commercial banks/);
assert.match(flow.holding('Bank fixed deposits', 1320000).look, /3 scheduled commercial banks/);
assert.match(flow.holding('Bank fixed deposits', 1320000).look, /DICGC/);

/* ── What it becomes: a range, never a promise ──────────────────────────── */
const ten = flow.outcomes(sized.groups, 10);
assert.equal(ten.years, 10);
assert.equal(ten.invested, 700000);
assert.ok(ten.low < ten.high);
assert.ok(ten.low > ten.invested, 'ten years of a mixed book has always ended above where it started');
assert.ok(ten.today_low < ten.low, 'inflation only ever makes the figure smaller');
const grew = ten.rows.find(r => r.key === 'growth');
assert.ok(grew.fall < grew.rupees, 'the equity row must show a fall that has actually happened');
assert.ok(ten.rows.find(r => r.key === 'stable').fall === ten.rows.find(r => r.key === 'stable').rupees);
const one = flow.outcomes(sized.groups, 1);
assert.ok(one.high < ten.low, 'more years, more money — the slider has to move the numbers');
// No public series for alternatives, so no number is invented for them.
const altRow = flow.outcomes(rich.groups, 10).rows.find(r => r.key === 'alt');
assert.equal(altRow.low, null);
assert.ok(altRow.note);

/* Riskier bands hold more equity, and never less. */
const order = ['Conservative', 'Moderately conservative', 'Balanced', 'Growth', 'Aggressive'];
for (let i = 1; i < order.length; i++) {
  const lower = flow.SPLIT[order[i - 1]].growth, higher = flow.SPLIT[order[i]].growth;
  assert.ok(higher[0] >= lower[0] && higher[1] >= lower[1],
    `${order[i]} must not hold less growth than ${order[i - 1]}`);
}
for (const band of order) {
  const s = flow.SPLIT[band];
  assert.equal(s.growth[0] + s.stable[0] + s.gold[0] <= 100, true, `${band} floors must fit in 100%`);
  assert.equal(s.growth[1] + s.stable[1] + s.gold[1] >= 100, true, `${band} ceilings must reach 100%`);
  // Scaled midpoints must add to the whole sum and each stay inside its own
  // published range — otherwise the rupee figures contradict the percentages
  // printed beside them.
  const scaled = flow.plan(band, 1000000, { horizon: '10plus', emergency: '6_12' });
  const shares = scaled.groups.reduce((sum, g) => sum + g.share.mid, 0);
  assert.ok(Math.abs(shares - 100) < 0.5, `${band} scaled midpoints must add to 100%`);
  for (const g of scaled.groups) {
    assert.ok(g.share.mid >= g.share.low - 0.05 && g.share.mid <= g.share.high + 0.05,
      `${band} ${g.key}: the scaled midpoint must stay inside its published range`);
  }
  assert.ok(Math.abs(scaled.groups.reduce((sum, g) => sum + g.share.rupees_mid, 0) - 1000000) <= 3);
}

/* The split's numeric ranges now live in exactly one place — allocate-flow's
   own SPLIT — so there is no second copy that can drift. The step list that
   printed them again in words was removed along with the old Allocate page. */

console.log('Allocation split, first calls, alternatives and outcomes: assertions passed');

/* ── Question art ───────────────────────────────────────────────────────────── */
// Each scene has to actually respond to the option, or it is a decoration
// pretending to be an answer. The cheap way to prove that is to render every
// option of every question and check the markup differs.
require('./adviser.js');
const art = require('./question-art.js');

const OPTIONS = {
  age: ['under25', '25_34', '35_44', '45_54', '55_64', '65plus'],
  horizon: ['under1', '1_3', '3_5', '5_10', '10plus'],
  surplus: ['none', 'under10', '10_25', '25_40', 'over40'],
  emergency: ['none', 'under3', '3_6', '6_12', 'over12'],
  emi: ['none', 'under20', '20_40', '40_60', 'over60'],
  dependents: ['0', '1_2', '3_4', '5plus'],
  drawdown_action: ['sell_all', 'sell_some', 'hold', 'hold_plan', 'buy_more'],
  max_fall: ['any', '10', '20', '30', '40plus'],
  priority: ['protect', 'mostly_protect', 'balanced', 'mostly_grow', 'grow'],
  experience: ['none', 'under3', '3_10', 'over10'],
  purpose: ['retirement', 'house', 'education', 'wealth', 'income', 'other'],
  mode: ['sip', 'lumpsum', 'both']
};

assert.deepEqual(art.ids.sort(), Object.keys(OPTIONS).sort(),
  'every question with options here should have art, and vice versa');

for (const [id, values] of Object.entries(OPTIONS)) {
  const drawn = values.map(v => art.scene(id, v));
  drawn.forEach((markup, i) => {
    assert.ok(markup && markup.length > 100, `${id}/${values[i]} drew nothing`);
    assert.ok(markup.includes('aria-hidden="true"'), `${id} must be hidden from readers`);
    assert.ok(!/undefined|NaN|null/.test(markup), `${id}/${values[i]} leaked a bad value`);
    // No text in the picture: the question and the options carry the words.
    assert.ok(!/>[A-Za-z]{3,}</.test(markup.replace(/<text[^>]*>₹<\/text>/g, '')),
      `${id}/${values[i]} put words inside the drawing`);
  });
  assert.ok(new Set(drawn).size >= Math.min(3, values.length),
    `${id} draws the same picture for different answers, so it answers nothing`);
}

// The one the ageing is for: the figure has to visibly age across the range.
assert.ok(art.scene('age', 'under25').includes('is-age-young'));
assert.ok(art.scene('age', '65plus').includes('is-age-elder'));
assert.ok(art.scene('age', '65plus').includes('adv-specs'), 'reading glasses by 65');
assert.ok(!art.scene('age', 'under25').includes('adv-specs'), 'and none at 24');
assert.ok(art.scene('age', '45_54').includes('is-salt'), 'greying in the middle');

// An unknown question or a nonsense option must fall back, never throw.
assert.equal(art.scene('not_a_question', 'x'), null);
assert.equal(art.has('horizon'), true);
assert.equal(art.has('nope'), false);
for (const id of art.ids) assert.ok(art.scene(id, undefined) !== undefined);

console.log('Question art: ' + Object.values(OPTIONS).flat().length + ' scenes asserted');
