/* The portfolio report's pure parts: run with `node frontend/portfolio-report.test.js`.
   The browser test (tests/portfolio-report-browser.cjs) covers the page. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const R = require('./portfolio-report.js');

const holding = (symbol, value, extra) => Object.assign({
  symbol, name: symbol + ' Ltd', value, weight_pct: 0, composite: 60, sector: 'Technology',
  industry: 'Software - Application', pnl: value * 0.1, pnl_pct: 10, cost: value * 0.9
}, extra || {});

function report() {
  const rows = [
    holding('BIG', 600000, { sector: 'Financial Services', industry: 'Banks - Regional', composite: 78 }),
    holding('MID', 300000, { composite: 62, pnl: -30000, pnl_pct: -9 }),
    holding('LOW', 100000, { sector: 'Basic Materials', industry: 'Steel', composite: 29, pnl: -20000, pnl_pct: -17 }),
  ];
  const total = rows.reduce((t, r) => t + r.value, 0);
  rows.forEach(r => { r.weight_pct = 100 * r.value / total; });
  return {
    holdings: rows, total_value: total, total_cost: 900000, total_pnl: 50000, total_pnl_pct: 5.6,
    weighted_score: 66.4, grade: 'B', generated_at: '2026-09-29T10:00:00Z',
    policy: { max_stock_pct: 15, max_sector_pct: 35 },
    concentration: { effective_n: 2.2 },
    sectors: [
      { sector: 'Financial Services', weight_pct: 60, count: 1, benchmark_weight_pct: 30 },
      { sector: 'Technology', weight_pct: 30, count: 1, benchmark_weight_pct: 12 },
      { sector: 'Basic Materials', weight_pct: 10, count: 1, benchmark_weight_pct: 8 },
    ],
    sector_comparison: [
      { sector: 'Financial Services', weight_pct: 60, benchmark_weight_pct: 30 },
      { sector: 'Technology', weight_pct: 30, benchmark_weight_pct: 12 },
    ],
    score_distribution: [
      { label: 'Strong', floor: 70, weight_pct: 60, count: 1 },
      { label: 'Good', floor: 60, weight_pct: 30, count: 1 },
      { label: 'High concern', floor: 0, weight_pct: 10, count: 1 },
    ],
    benchmark: { name: 'Nifty 500', as_of: 'March 2026' },
    action_plan: {
      available: true, headline: '2 of your 3 holdings need a move: 1 to exit, 1 to trim.',
      money: 'Selling as suggested frees about ₹4,00,000.', freed: 400000, needed: 0,
      counts: { EXIT: 1, TRIM: 1, AVERAGE: 0, ADD: 0, HOLD: 1 },
      method: 'Strong = score 60+.', disclaimer: 'Altaha is not registered with SEBI as an investment adviser or research analyst.',
      rotation: [],
      actions: [
        { symbol: 'LOW', action: 'EXIT', score: 29, why: 'Poor evidence.', todo: 'Sell all',
          move: { side: 'sell', shares: 10, of_shares: 10, value: 100000, all: true },
          switch: 'Consider switching to JSWSTEEL — same industry (Steel), score 64 vs 29 for LOW.',
          alternatives: [{ symbol: 'JSWSTEEL', score: 64, match: 'industry', group: 'Steel' }] },
        { symbol: 'BIG', action: 'TRIM', score: 78, why: 'Above your limit.', todo: 'Sell some',
          move: { side: 'sell', shares: 5, of_shares: 10, value: 300000, all: false }, switch: null, alternatives: [] },
        { symbol: 'MID', action: 'HOLD', score: 62, why: 'Fine.', todo: 'No change needed', move: null, switch: null, alternatives: [] },
      ],
    },
  };
}

// Rupees, the Indian way, and never a unit wrapped away from its number.
assert.equal(R._inr(1234567), '₹12,34,567');
assert.equal(R._inr(-48000), '−\u2060₹48,000', 'the sign stays with its number');
assert.equal(R._short(48000), '₹48,000');
assert.equal(R._short(250000), '₹2.5 L');
assert.equal(R._short(2208000), '₹22.08 L');
assert.equal(R._short(25000000), '₹2.5 Cr');

// After the plan: every move applied at once, shares of what is then invested.
{
  const d = report(), out = R._after(d, d.action_plan);
  const by = Object.fromEntries(out.map(x => [x.symbol, x]));
  assert.equal(by.LOW.after, 0, 'an exit leaves nothing');
  assert.equal(Math.round(by.BIG.after), 50, '300k of the 600k left invested');
  assert.ok(Math.abs(out.reduce((t, x) => t + x.after, 0) - 100) < 1e-9, 'the shares add up');
}

// The pie keeps at most six slices; the rest fold into "Other", nothing lost.
{
  const d = { sectors: 'ABCDEFGH'.split('').map((c, i) => ({ sector: 'S' + c, weight_pct: 20 - i * 2, count: 1 })) };
  const s = R._slices(d);
  assert.equal(s.length, 6);
  assert.ok(s[5].other && /Other \(3\)/.test(s[5].name));
  assert.equal(s.reduce((t, x) => t + x.w, 0), d.sectors.reduce((t, x) => t + x.weight_pct, 0));
}

// The report: every section, every holding, the trade and the disclaimer.
{
  const d = report(), html = R.build(d);
  ['What should I do?', 'What exactly, stock by stock?', 'What does the plan change?', 'Where is my money?',
   'How good are my stocks?', 'What made or lost me money?', 'Where could new money go?', 'How were these calls made?']
    .forEach(q => assert.ok(html.includes(q), q));
  assert.ok(html.includes('Sell all 10 shares · ₹1,00,000'));
  assert.ok(html.includes('Sell 5 of 10 shares · ₹3,00,000'));
  assert.ok(html.includes('same industry (Steel)'));
  assert.ok(html.includes('not registered with SEBI'));
  assert.ok(html.includes('Start with LOW'), 'the first thing is the most urgent call, not the headline again');
  assert.ok(!/industries/i.test(html.replace(/same industry/g, '')), 'a broad group is a sector; "industry" means the exact one');
  assert.equal((html.match(/class="ar-row"/g) || []).length, 3, 'a line for every holding');
  assert.equal((html.match(/class="ar-arc /g) || []).length, 3, 'a slice for every sector');
}

// Names from the data are text, never markup.
{
  const d = report();
  d.holdings[0].name = '<img src=x onerror=alert(1)>';
  d.action_plan.actions[0].why = '<script>alert(1)</script>';
  const html = R.build(d);
  assert.ok(!html.includes('<img src=x') && !html.includes('<script>alert'));
  assert.ok(html.includes('&lt;img src=x'));
}

// Without a plan, or without holdings, it still reads — and says so.
{
  const d = report(); d.action_plan = { available: false };
  const html = R.build(d);
  assert.ok(html.includes('No action plan is available'));
  assert.doesNotThrow(() => R.build({}));
  assert.doesNotThrow(() => R.build(null));
}

// The file: self-contained, runs nothing, links that work from anywhere.
{
  const doc = R.documentHTML(report());
  assert.ok(doc.startsWith('<!DOCTYPE html>'));
  assert.ok(!/<script/i.test(doc), 'no script in the file');
  assert.ok(!/<link /i.test(doc) && !/src="http/.test(doc), 'no network');
  assert.ok(doc.includes('https://altahascreener.in/stock.html?ticker=BIG'));
  assert.ok(doc.includes('data-theme="light"'), 'paper is light');
  assert.ok(doc.includes('@page'));
}

// Motion fills backwards only: nothing is ever held invisible by a pause.
{
  const css = R.CSS;
  const fills = css.match(/animation:[^;}]*/g) || [];
  assert.ok(fills.length >= 5);
  fills.forEach(f => assert.ok(!/\b(forwards|both)\b/.test(f), f));
  assert.ok(css.includes('prefers-reduced-motion') && css.includes('data-motion="off"'));
}

// The call colours are the validated set, in both themes.
{
  const css = R.CSS;
  ['#B03A2B', '#C98500', '#1F7A55', '#3F6FB0', '#C4364F', '#B88A12', '#2E9E6E', '#5B87CC'].forEach(c => assert.ok(css.includes(c), c));
  assert.deepEqual(R.EDGE, ['EXIT', 'TRIM', 'ADD', 'AVERAGE', 'HOLD'], 'the order the palette was validated in');
}

// The script is where index.html says it is, before portfolio.js.
{
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  assert.ok(html.indexOf('portfolio-report.js') > 0 && html.indexOf('portfolio-report.js') < html.indexOf('src="portfolio.js"'));
}

console.log('portfolio report tests passed');
