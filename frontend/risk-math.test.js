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
const fs = require('node:fs');
const path = require('node:path');
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

/* ── The lower of the two decides ─────────────────────────────────────────── */
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

/* ── The split, in rupees ─────────────────────────────────────────────────── */
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
const noCushion = flow.plan('Growth', 1000000, { horizon: '10plus', emergency: 'none' });
assert.ok(noCushion.flags.some(f => /cushion/i.test(f.title)));
const lump = flow.plan('Growth', 1000000, { horizon: '10plus', mode: 'lumpsum' });
assert.ok(lump.flags.some(f => /lump sum/i.test(f.title)));
assert.equal(flow.plan('Growth', 1000000, { horizon: '10plus', emergency: '6_12' }).flags.length, 0);

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

/* ── The words and the numbers must be the same split ─────────────────────── */
// The step list prints ranges as text; this card turns them into rupees. If
// they ever disagree, one of the two screens is lying to the same reader.
const allocate = fs.readFileSync(path.join(__dirname, 'allocate.js'), 'utf8');
let found = 0;
for (const band of order) {
  const block = allocate.slice(allocate.indexOf(`'${band}': {`));
  for (const key of ['growth', 'stable', 'gold']) {
    const m = new RegExp(`${key}:\\s*'(\\d+)[–-](\\d+)%'`).exec(block.slice(0, 400));
    assert.ok(m, `allocate.js should state a ${key} range for ${band}`);
    assert.deepEqual([Number(m[1]), Number(m[2])], flow.SPLIT[band][key],
      `${band} ${key}: the step list and the card must show the same range`);
    found++;
  }
}
assert.equal(found, 15);

console.log('Allocation split: 33 assertions passed');
