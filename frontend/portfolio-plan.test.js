/* The action plan's drawing, without a browser.

   What this guards:
     · TEXT IS TEXT: a company name or reason from the API is escaped.
     · EVERY CALL IS DRAWN with its trade, its reason and its evidence.
     · THE DISCLAIMER IS ON THE PAGE, whatever else changes.
     · MOTION-OFF SAFETY: no animation fills `forwards` or `both` — the fill
       that froze the home page's hero at opacity 0 (tests/motion-off-browser.cjs). */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const P = require('./portfolio-plan.js');

const plan = {
  available: true, headline: '2 of your 3 holdings need a move: 1 to exit, 1 to add.',
  money: 'Selling as suggested frees about ₹50,000.',
  counts: { EXIT: 1, TRIM: 0, AVERAGE: 0, ADD: 1, HOLD: 1 },
  actions: [
    { symbol: 'BAD<img src=x onerror=1>', name: 'Bad Co', action: 'EXIT', conviction: 'high', todo: 'Sell all 10 shares · ₹50,000',
      why: 'Its evidence is poor.', reasons: ['Altaha Score 29/100.'], score: 29, weight_pct: 2, pnl_pct: -30,
      switch: 'Consider switching to GOOD — same industry, score 64 vs 29.', alternatives: [{ symbol: 'GOOD', score: 64 }] },
    { symbol: 'ADDME', name: 'ADDME', action: 'ADD', conviction: 'high', todo: 'Buy 7 more · ₹1,05,000', why: 'Strong.', reasons: ['x'],
      score: 79, weight_pct: 6, pnl_pct: 8.7, alternatives: [] },
    { symbol: 'KEEP', name: 'KEEP', action: 'HOLD', conviction: 'medium', todo: 'No change needed', why: 'Solid.', reasons: [],
      score: 57, weight_pct: 9, pnl_pct: null, alternatives: [] }
  ],
  rotation: [{ sector: 'Healthcare', relative_3m: 5.5, your_weight_pct: 1, market_weight_pct: 7.2, why: 'Healthcare is beating…',
               stocks: [{ symbol: 'CIPLA', score: 61 }] }],
  method: 'Strong = score 60+…', disclaimer: 'Altaha is not registered with SEBI as an investment adviser or research analyst.'
};
const html = P.render(plan, { weighted_score: 69.5 });

assert.ok(!/<img/i.test(html), 'a symbol is escaped');
assert.ok(html.includes('BAD&lt;img'), 'and still shown');
assert.equal((html.match(/class="pp-card /g) || []).length, 3, 'one card per holding');
assert.match(html, /data-act="EXIT"[\s\S]*Sell all 10 shares · ₹50,000/);
assert.match(html, /Consider switching to GOOD/);
assert.match(html, /stock\.html\?ticker=GOOD/);
assert.match(html, /stock\.html\?ticker=CIPLA/);
assert.match(html, /Where the money could go/);
assert.match(html, /not registered with SEBI/);
assert.match(html, /data-pp-count="70"/, 'the portfolio score, rounded');
assert.match(html, /Needs a move · 2/);
assert.match(html, /<b>1<\/b><span>Exit<\/span>/);

const css = fs.readFileSync(path.join(__dirname, 'portfolio-plan.css'), 'utf8');
for (const decl of css.match(/animation(?:-fill-mode)?\s*:[^;}]+/g) || []) {
  assert.doesNotMatch(decl, /\b(forwards|both)\b/, 'fill that could hold an element invisible: ' + decl);
}
assert.match(css, /prefers-reduced-motion:reduce/);
assert.match(css, /html\[data-motion="off"\] \.pp \*/);
console.log('portfolio plan drawing passed');
