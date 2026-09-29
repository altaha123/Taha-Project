/* The portfolio story's chapters, without a browser.

   What this guards:
     · THE ARITHMETIC IN THE SENTENCES. "If it fell 10%, your portfolio would
       fall about 2.4% — ₹60,000" is a claim a reader will check.
     · NO ADVICE. Observations and questions only: nothing tells the reader
       to buy, sell, exit, reduce, trim or add. See README on SEBI.
     · ONE QUESTION PER KIND OF FINDING, not the same question twice.
     · A CHAPTER WITHOUT DATA IS LEFT OUT, not drawn empty.
     · TEXT IS TEXT. A headline from a news feed is escaped, and only http(s)
       links are ever rendered.
     · MOTION-OFF SAFETY. No animation in the stylesheet may fill `forwards`
       or `both`: those are what froze the home page's hero at opacity 0 when
       motion was paused (see tests/motion-off-browser.cjs). */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const S = require('./portfolio-story.js');

function holding(symbol, value, cost, score, sector) {
  return { symbol, name: symbol, value, cost, pnl: cost == null ? null : value - cost,
           weight_pct: value / 2500000 * 100, composite: score, sector };
}
const holdings = [
  holding('HDFCBANK', 600000, 540000, 78, 'Financial Services'),
  holding('RELIANCE', 400000, 430000, 68, 'Energy'),
  holding('TCS', 300000, 250000, 75, 'Technology'),
  holding('ICICIBANK', 250000, 200000, 82, 'Financial Services'),
  holding('LT', 200000, 220000, 72, 'Industrials'),
  holding('INFY', 175000, 200000, 48, 'Technology'),
  holding('SUNPHARMA', 150000, 110000, 79, 'Healthcare'),
  holding('ITC', 125000, 120000, 61, 'Consumer Defensive'),
  holding('TATAMOTORS', 100000, null, 35, 'Consumer Cyclical'),
  holding('NTPC', 75000, 70000, 55, 'Utilities'),
  holding('BHARTIARTL', 75000, 60000, 65, 'Communication Services'),
  holding('TATASTEEL', 50000, 60000, 42, 'Basic Materials'),
];
const withCost = holdings.filter(h => h.cost != null);
const report = {
  holdings, total_value: 2500000,
  total_cost: withCost.reduce((s, h) => s + h.cost, 0),
  total_pnl: withCost.reduce((s, h) => s + h.pnl, 0),
  weighted_score: 69.55,
  policy: { max_stock_pct: 15, max_sector_pct: 35, min_composite: 45 },
  sectors: [['Financial Services', 34], ['Technology', 19], ['Energy', 16], ['Industrials', 8], ['Healthcare', 6],
            ['Consumer Defensive', 5], ['Consumer Cyclical', 4], ['Utilities', 3], ['Communication Services', 3], ['Basic Materials', 2]]
    .map(([sector, weight_pct]) => ({ sector, weight_pct })),
  concentration: { effective_n: 7.8, top3_pct: 52, top1_pct: 24 },
  score_distribution: [['Exceptional', 80], ['Strong', 70], ['Good', 60], ['Average', 50], ['Weak', 40], ['High concern', 0]]
    .map(([label, floor]) => ({ label, floor })),
  data_quality: { scored_value_pct: 100 },
  developments: { events: [{ headline: 'HDFC Bank results <img src=x onerror="window.__x=1">', source: 'NSE',
    url: 'javascript:alert(1)', published_at: '2026-09-28T10:00:00Z', symbols: ['HDFCBANK'] }] },
  ic_review: {
    risk_budget: { available: true, from: '2026-03-19', worst_day_pct: -0.91, window_drawdown_pct: -4.09,
      value_at_risk: { '95': { historical_pct: 0.55 } }, effective_risk_positions: 4.1,
      holdings: [{ symbol: 'HDFCBANK', weight_pct: 24, risk_share_pct: 43.7 }] },
    agenda: [
      { rank: 1, rule: 'max_stock_pct', title: 'Single-stock cap · HDFCBANK', measured: 24, limit: 15, question: 'x' },
      { rank: 2, rule: 'max_stock_pct', title: 'Single-stock cap · RELIANCE', measured: 16, limit: 15, question: 'x' },
      { rank: 3, rule: 'risk_share', title: 'Risk concentration · HDFCBANK', measured: 43.7, limit: 30, question: 'x' },
      { rank: 4, rule: 'risk_budget', title: 'Risk budget concentration', measured: 70, limit: 60, question: 'x' },
      { rank: 5, rule: 'min_composite', title: 'Score floor · TATAMOTORS', measured: 35, limit: 45, question: 'x' },
      { rank: 6, rule: 'min_composite', title: 'Score floor · TATASTEEL', measured: 42, limit: 45, question: 'x' },
    ]
  }
};

const chs = S.chapters(report, { now: Date.parse('2026-09-29T10:00:00Z') });
const byId = Object.fromEntries(chs.map(c => [c.id, c]));
assert.deepEqual(chs.map(c => c.id),
  ['money', 'sectors', 'biggest', 'spread', 'movers', 'score', 'rough', 'news', 'questions', 'recap']);

// The arithmetic the sentences state.
assert.equal(byId.money.title, 'Your portfolio is worth ₹25,00,000');
assert.match(byId.money.lede, /On the 11 of your 12 holdings with a buy price/);
assert.match(byId.biggest.lede, /₹24 of every ₹100/);
assert.match(byId.biggest.lede, /about \*\*2\.4%\*\* — roughly \*\*₹60,000\*\*/);
assert.match(byId.biggest.lede, /You set 15% as the most for any one stock; this is 24%/);
assert.match(byId.sectors.lede, /₹34 of every ₹100\*\* sits in Financial Services/);
assert.match(byId.spread.lede, /about 8 equal-sized ones/);
assert.match(byId.spread.lede, /HDFCBANK\*\* alone drives 44% of the ups and downs/);
assert.match(byId.movers.lede, /HDFCBANK\*\* has added the most: \*\*\+₹60,000\*\*/);
assert.match(byId.movers.lede, /RELIANCE\*\* has cost the most: \*\*−₹30,000\*\*/);
assert.match(byId.rough.lede, /1 day in 20\*\*, your portfolio lost more than \*\*₹13,750\*\*/);
assert.match(byId.score.lede, /69\.55 out of 100|69\.5 out of 100|69\.6 out of 100/);
assert.equal(S.words(2272894), '₹22.7 lakh');
assert.equal(S.words(12500000), '₹1.25 crore');
assert.equal(S.inr(-2500000), '−₹25,00,000');

// One question per kind of finding.
const qs = byId.questions.visual.items;
assert.equal(qs.length, 3);
assert.match(qs[0].head, /HDFCBANK \(24%\) and RELIANCE \(16%\) are above your per-stock limit/);
assert.match(qs[1].head, /HDFCBANK causes 44% of the swings/);
assert.match(qs[2].head, /TATAMOTORS \(35\) and TATASTEEL \(42\) score below your floor of 45/);
assert.equal(new Set(qs.map(q => q.question)).size, 3, 'no question asked twice');

// No advice, anywhere a reader is told something.
const told = chs.flatMap(c => [c.title, c.lede, c.big || ''].concat(
  c.id === 'questions' ? c.visual.items.flatMap(q => [q.head, q.fact, q.question]) : []));
for (const t of told) {
  assert.doesNotMatch(t, /\b(you should|should you|we recommend|recommend|exit|reduce|trim|accumulate|add more|book profits?|stop[- ]loss|target price)\b/i, t);
}

// Without buy prices there is no gain or loss to tell, and no movers chapter.
const noCost = S.chapters(Object.assign({}, report, {
  holdings: holdings.map(h => Object.assign({}, h, { cost: null, pnl: null })), total_cost: null, total_pnl: null }));
assert.equal(noCost.find(c => c.id === 'money').big, undefined);
assert.match(noCost.find(c => c.id === 'money').lede, /Add the price you paid/);
assert.ok(!noCost.some(c => c.id === 'movers'));
// Without risk history or news, those chapters are left out or said plainly.
const bare = S.chapters({ holdings: holdings.slice(0, 1), total_value: 600000 });
assert.deepEqual(bare.map(c => c.id), ['money', 'recap']);
assert.deepEqual(S.chapters({ holdings: [] }), []);
assert.deepEqual(S.chapters(null), []);
const quiet = S.chapters(Object.assign({}, report, { developments: { events: [] } })).find(c => c.id === 'news');
assert.equal(quiet.title, 'A quiet week for your companies');

// Text is text.
const html = S.html(chs);
assert.ok(!/<img/i.test(html), 'a headline is escaped');
assert.ok(html.includes('&lt;img src=x'), 'and still shown');
assert.ok(!/javascript:/i.test(html), 'only http(s) links are rendered');

// Motion-off safety in the stylesheet.
const css = fs.readFileSync(path.join(__dirname, 'portfolio-story.css'), 'utf8');
for (const decl of css.match(/animation(?:-fill-mode)?\s*:[^;}]+/g) || []) {
  assert.doesNotMatch(decl, /\b(forwards|both)\b/, 'fill that could hold an element invisible: ' + decl);
}
assert.match(css, /prefers-reduced-motion:reduce/);
assert.match(css, /html\[data-motion="off"\] \.ps \*/);

console.log('portfolio story chapters passed (' + chs.length + ' chapters)');
