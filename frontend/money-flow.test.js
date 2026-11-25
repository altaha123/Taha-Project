/* Money flow, the rendering: data in, markup out. The fixture is produced by
   the real backend (backend/tests/make_money_flow_fixture.py) from an invented
   market, so a renamed key fails here rather than on the page. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ui = require('./money-flow.js');
const d = JSON.parse(fs.readFileSync('frontend/tests/fixtures/money-flow.json', 'utf8'));
const sectors = JSON.parse(fs.readFileSync('frontend/tests/fixtures/money-flow-sectors.json', 'utf8'));
const clone = x => JSON.parse(JSON.stringify(x));
const count = (s, re) => (s.match(re) || []).length;

// ── Figures say their sign, in rupees crore, with Indian grouping ───────────
assert.equal(ui.cr(43102, true), '+₹43,102 cr');
assert.equal(ui.cr(-6533, true), '−₹6,533 cr');
assert.equal(ui.cr(123456, true), '+₹1,23,456 cr');
assert.equal(ui.cr(1200), '₹1,200 cr', 'a bought-or-sold total has no sign of its own');
assert.equal(ui.cr(null), '—');
assert.equal(ui.cr(0, true), '₹0 cr');
// A heatmap cell has room for five characters.
assert.deepEqual([612, -6533, 43102, -110, 0, 123456, null].map(ui.compact),
  ['+612', '−6.5k', '+43k', '−110', '0', '+1.2L', '']);
assert.equal(ui.signed(-3.24, 1), '−3.2');
assert.equal(ui.period('2026-11-01', '2026-11-15', true), '1–15 Nov 2026');
assert.equal(ui.period('2026-10-16', '2026-10-31'), '16–31 Oct');
assert.equal(ui.day('2026-11-20', true), 'Fri 20 Nov 2026');

// ── The page: every section, in order, from one payload ─────────────────────
const html = ui.render(d, {});
const order = ['mf-tiles"', 'mf-sec mf-hero"', 'mf-sec mf-heat"', 'mf-sec mf-rot"', 'mf-sec mf-ranking"', 'mf-method"']
  .map(c => html.indexOf('class="' + c));
assert.ok(order.every(i => i > 0), 'a section is missing: ' + order);
assert.deepEqual(order.slice().sort((a, b) => a - b), order, 'the sections are out of order');
assert.doesNotMatch(html, /NaN|undefined|Infinity|\[object/, 'something unformatted reached the page');
assert.match(html, /Session of Fri 20 Nov 2026 · FPI data to 1–15 Nov 2026/);

// ── Sector cards: ranked, each with its score and the three parts of it ─────
assert.equal(count(html, /class="mf-card"/g), d.sectors.length);
const it = d.sectors[0];
assert.equal(it.sector, 'Information Technology');
const itCard = ui.card(it, 0);
assert.match(itCard, /<span class="mf-rank">01<\/span><span class="mf-name">IT<\/span>/);
assert.match(itCard, new RegExp('<b>' + Math.round(it.score) + '</b>'));
assert.match(itCard, /q-leading/);
assert.match(itCard, /Buying more/);
assert.ok(itCard.includes(ui.cr(it.fpi.latest_cr, true)) && itCard.includes(ui.cr(it.fpi.sum3_cr, true)));
['FPI flow', 'Rotation', 'Breadth'].forEach(k => assert.ok(itCard.includes('<span>' + k + '</span>'), k));
assert.match(itCard, /data-sector="information-technology"/);
assert.match(itCard, /aria-label="Information Technology, score \d+ of 100, rank 1 of 19\. Open its stocks\."/);
// Cards come out in rank order.
const ranks = [...html.matchAll(/<span class="mf-rank">(\d+)<\/span>/g)].map(m => +m[1]);
assert.deepEqual(ranks, d.sectors.map((_, i) => i + 1));

// ── A flip from selling to buying is flagged, in words and with a mark ──────
const fmcg = d.sectors.find(c => c.short === 'FMCG');
assert.equal(fmcg.fpi.flipped_to_inflow, true);
const fmcgCard = ui.card(fmcg, 3);
assert.match(fmcgCard, /class="mf-trendline flip" title="FPIs turned from selling to buying/);
assert.match(fmcgCard, /Turned to buying/);
assert.doesNotMatch(itCard, /mf-trendline flip/);
assert.match(html, new RegExp('Turned to buying</div><div class="v">' + d.fpi.flipped_to_inflow.length + '</div>'));
// Every trend has a word; direction is never an arrow's colour alone.
assert.equal(ui.trendWord({ direction: 'outflow', trend: 'decelerating' }), 'Selling less');
assert.equal(ui.trendWord({ direction: 'flat', trend: 'steady' }), 'No net flow');
assert.equal(ui.trendWord(null), 'No FPI data');

// ── The heatmap: sector by fortnight, the figure in the cell is rupees ──────
const heat = ui.heatmap(d.heatmap, 'pct', d.fpi.latest_period);
assert.equal(count(heat, /<td class="mf-cell /g), (d.heatmap.rows.length + 1) * d.heatmap.periods.length);
assert.equal(count(heat, /<th scope="col" title=/g), 12);
const row0 = d.heatmap.rows[0];
assert.ok(heat.includes('>' + ui.compact(row0.cells[11].net_cr) + '</td>'));
assert.match(heat, /data-period="1–15 Nov 2026"/);
assert.match(heat, /<th scope="row">All sectors<\/th>/);
// Shading is a share of holdings by default, rupees on request; the scale is
// the 90th percentile so one extraordinary fortnight does not grey the rest.
assert.equal(ui.heatStep(0.01, 1), 'z');
assert.deepEqual([0.2, 0.5, 0.8, 5].map(v => ui.heatStep(v, 1)), ['in1', 'in2', 'in3', 'in4']);
assert.deepEqual([-0.2, -5].map(v => ui.heatStep(v, 1)), ['out1', 'out4']);
assert.equal(ui.heatStep(null, 1), 'na');
const many = { rows: [{ cells: Array.from({ length: 20 }, (_, i) => ({ pct: i === 19 ? 500 : i })) }] };
assert.equal(ui.heatScale(many.rows, 'pct'), 18);
assert.notEqual(ui.heatmap(d.heatmap, 'cr'), heat, 'the rupee shading is the same as the share shading');
assert.match(ui.heatmap(d.heatmap, 'cr'), /data-heat="cr" class="active" aria-pressed="true"/);

// ── The market: two panels on one time axis, never two scales on one plot ───
const days = d.market.days;
const g = ui.heroGeometry(days);
assert.ok(g.A.y(0) < g.B.y(0), 'the running total is drawn under the daily bars, not over them');
assert.ok(g.A.y(1000) < g.A.y(0) && g.A.y(-1000) > g.A.y(0), 'buying is up, selling is down');
days.forEach(x => [x.fii, x.dii].forEach(v =>
  assert.ok(g.A.y(v) >= 26 && g.A.y(v) <= 250, 'a bar runs out of its panel: ' + v)));
days.forEach(x => [x.fii_cum, x.dii_cum].forEach(v =>
  assert.ok(g.B.y(v) >= 308 && g.B.y(v) <= 432, 'a running total runs out of its panel: ' + v)));
const hero = ui.hero(d.market, 60);
assert.equal(count(hero, /class="mf-bar fii/g) + count(hero, /class="mf-bar dii/g), days.filter(x => x.fii).length + days.filter(x => x.dii).length);
assert.equal(count(hero, /class="mf-line /g), 2);
assert.match(hero, /Every session as a table/);
assert.equal(count(hero, /<tr><th>\w{3} \d/g), 60, 'the table twin carries every session');
// Twenty sessions shows twenty.
assert.equal(count(ui.hero(d.market, 20), /<tr><th>\w{3} \d/g), 20);
// A bar's data end is rounded and its baseline end is square.
assert.equal(ui.barPath(10, 8, 100, 60), 'M10 100V64a4 4 0 0 1 4 -4h0a4 4 0 0 1 4 4V100Z');
assert.equal(ui.barPath(10, 8, 100, 100.2), '');
// Under five sessions a chart would be a pair of bars: the figures instead.
const young = clone(d.market);
young.days = young.days.slice(-2); young.sessions = 2;
const few = ui.hero(young, 60);
assert.doesNotMatch(few, /<svg class="mf-hero-svg"/);
assert.match(few, /class="mf-figs"/);
assert.ok(few.includes(ui.cr(young.latest.fii, true)) && few.includes('Bought ' + ui.cr(young.latest.fii_buy)));
assert.match(ui.hero({ available: false, message: 'No session has been recorded yet.' }, 60), /No session has been recorded yet\./);

// ── Rotation: 100/100 is the crossing, right is stronger, up is gaining ─────
const rrg = ui.rrgWithFlow(d);
const geo = ui.rrgGeometry(rrg, { themes: false });
assert.equal(geo.series.length, d.rrg.series.filter(s => s.kind === 'sector').length);
assert.equal(ui.rrgGeometry(rrg, { themes: true }).series.length, d.rrg.series.length);
assert.ok(geo.X(101) > geo.X(100) && geo.Y(101) < geo.Y(100));
assert.ok(geo.cx > 50 + 0.15 * 650 && geo.cx < 700 - 0.15 * 650, '100 has been pushed to the edge');
const itSeries = geo.series.find(e => e.s.key === 'information-technology');
const last = itSeries.pts[itSeries.pts.length - 1];
assert.ok(last.x > geo.cx && last.y < geo.cy, 'a Leading sector is drawn outside the Leading quadrant');
assert.equal(itSeries.s.direction, 'inflow');
// Between two weeks a sector is on the line joining them.
const a = itSeries.pts[3], b = itSeries.pts[4], mid = ui.rrgAt(itSeries.pts, 3.5);
assert.ok(Math.abs(mid.x - (a.x + b.x) / 2) < 1e-9 && Math.abs(mid.y - (a.y + b.y) / 2) < 1e-9);
assert.deepEqual(ui.rrgAt(itSeries.pts, 7), { x: last.x, y: last.y, i: 7 });
assert.equal(ui.rrgAt([null, null, { x: 1, y: 2 }], 1), null, 'a series is not drawn before its first reading');
// No two placed labels overlap.
const labs = Object.values(ui.rrgLabels(geo));
assert.ok(labs.length >= 10, 'most sectors should get a label');
labs.forEach((p, i) => labs.slice(i + 1).forEach(q =>
  assert.ok(!(p.x0 < q.x1 && p.x1 > q.x0 && p.y0 < q.y1 && p.y1 > q.y0), 'two labels overlap')));
const rot = ui.rotation(d, { themes: false });
assert.equal(count(rot, /class="mf-rr k-sector"/g), geo.series.length);
assert.equal(count(rot, /class="mf-rr k-theme"/g), 0);
assert.equal(count(ui.rotation(d, { themes: true }), /class="mf-rr k-theme"/g), 6);
assert.match(rot, /class="mf-dot in" r="6"/); assert.match(rot, /class="mf-dot out" r="6"/);
// Every sector is also named in a list, by quadrant.
['Leading', 'Improving', 'Weakening', 'Lagging'].forEach(q => assert.ok(rot.includes('q-' + q.toLowerCase())));
assert.equal(count(rot, /<li data-key=/g), geo.series.filter(e => e.s.quadrant).length);

// ── A narrow screen gets its own drawing, not a scaled one ──────────────────
const narrow = ui.render(d, { narrow: true });
assert.match(narrow, /<svg class="mf-hero-svg" viewBox="0 0 380 /);
assert.match(narrow, /<svg class="mf-rrg-svg" viewBox="0 0 380 /);
assert.equal(count(narrow, /<tr><th>\w{3} \d/g), 20, 'a phone opens on twenty sessions');
assert.match(ui.render(d, {}), /<svg class="mf-hero-svg" viewBox="0 0 1000 /);

// ── What is not scored is said, with its reason left to the heatmap ─────────
assert.match(html, /Not scored, too few companies to measure: Diversified, Forest, Utilities\./);
assert.equal(count(html, /<tr><th>[^<]+<\/th><td>[^<]*<\/td><td><span class="mf-fit/g), 24, 'the mapping table lists all 24 NSDL rows');
assert.match(html, /f-ambiguous">A judgement/);

// ── Nothing from the server reaches the page as markup ──────────────────────
const evil = clone(d);
evil.sectors[0].short = '<img src=x onerror=alert(1)>';
evil.heatmap.rows[0].short = '"><script>x</script>';
evil.gaps = ['<b>bold</b>'];
evil.rrg.series[0].name = '<svg onload=1>';
const safe = ui.render(evil, {});
assert.doesNotMatch(safe, /<img src=x|<script>x|<b>bold|<svg onload/);
assert.match(safe, /&lt;img src=x onerror=alert\(1\)&gt;/);

// ── States ──────────────────────────────────────────────────────────────────
assert.match(ui.render({ available: false, message: 'Money Flow has no data yet.' }, {}), /Nothing to show yet<\/b><span>Money Flow has no data yet\./);
assert.match(ui.render(null, {}), /Nothing to show yet/);
const gappy = clone(d); gappy.gaps = ['FII/DII: 1 session recorded.'];
assert.match(ui.render(gappy, {}), /What is missing<\/b><ul><li>FII\/DII: 1 session recorded\.<\/li>/);

// ── One sector, opened ──────────────────────────────────────────────────────
const itd = sectors['information-technology'];
const dr = ui.drawer(itd);
assert.match(dr, /<h3 id="mf-dtitle">Information Technology<\/h3>/);
assert.match(dr, /Rank 1 of 19/);
assert.equal(count(dr, /class="mf-fbar /g), itd.fortnights.filter(f => f.net_cr).length);
const top = itd.stocks[0];
assert.equal(top.symbol, 'ITE1');
assert.match(dr, /stock\.html\?ticker=ITE1&amp;pane=deliv/);
assert.ok(dr.includes('<b>' + Math.round(top.deliv_pct) + '%</b><small>usual ' + Math.round(top.deliv_avg20) + '%</small>'));
assert.match(dr, /class="mf-deal in"><i aria-hidden="true"><\/i>Bought ₹/);
assert.match(dr, /Long Horizon Mutual Fund/);
assert.ok(dr.includes(top.reasons[0]));
assert.equal(count(dr, /<tr class="mf-why">/g), itd.stocks.length);
['Delivered today', 'Volume vs usual', '5 sessions', 'Bulk and block, 30 days', 'Score'].forEach(l =>
  assert.equal(count(dr, new RegExp('data-label="' + l + '"', 'g')), itd.stocks.length, l));
// A sold stock is marked as sold, not left blank.
const sold = itd.stocks.find(r => r.deals && r.deals.net_cr < 0);
if (sold) assert.match(dr, /class="mf-deal out"><i aria-hidden="true"><\/i>Sold ₹/);
// A sector that could not be scored still opens, and says so.
const div = ui.drawer(sectors['diversified']);
assert.match(div, /<div class="mf-eyebrow">Not scored<\/div>/);
assert.match(div, /Not measured against the Nifty 50\. No index, and one company in our universe\./);
assert.doesNotMatch(div, /\d\.\d{6,}/, 'an unrounded number reached a path');
const bare = clone(sectors['diversified']); bare.stocks = [];
assert.match(ui.drawer(bare), /No stock in this sector can be read for accumulation yet/);
// A basket says it is one, and why.
const basket = Object.values(sectors).find(x => x.card && x.card.index.source === 'basket');
assert.match(ui.drawer(basket), /Measured on a basket of \d+ \w+ stocks/);
assert.match(dr, /Measured on Nifty IT\./);
assert.match(ui.drawer(null), /Reading the sector/);
assert.doesNotMatch(dr + div, /NaN|undefined|\[object/);

// ── What a hover says ───────────────────────────────────────────────────────
const cell = { getAttribute: () => 'cell', dataset: { cr: '-6533', pct: '-1.37', sector: 'Auto', period: '1–15 Oct 2026' } };
assert.equal(ui.tip(cell), '<b>−₹6,533 cr</b><span>Auto</span><span>1–15 Oct 2026</span><span>−1.37% of FPI holdings in the sector</span>');

console.log('money-flow.test.js: ok');
