/* Delivery trends, the rendering: state in, HTML out. The fixture is produced
   by the real backend function (backend/tests/make_delivery_trends_fixture.py)
   from invented data, so a renamed key fails here rather than on the page. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ui = require('./delivery-trends.js');
const d = JSON.parse(fs.readFileSync('frontend/tests/fixtures/delivery-trends.json', 'utf8'));

// ── The numbers on a row are the payload's, and the sentence repeats them ──
const html = ui.render(d, { view: 'today', dir: 'all' });
const rel = d.views.today.rows.find(r => r.symbol === 'RELIANCE');
assert.equal(rel.mult, 4.5);
assert.match(html, /data-sym="RELIANCE"/);
assert.match(html, /<b>4\.5×<\/b><small>₹252 cr vs ₹56\.0 cr<\/small>/);
assert.match(html, /<b>60%<\/b><small>usual 40%<\/small>/);
assert.match(html, /class="dt-chg up">\+3\.0%/);
assert.equal(ui.reading('today', rel),
  '₹252 cr of shares were taken to delivery, 4.5× its usual ₹56.0 cr day, as the price rose 3.0%. ' +
  '60% of the volume was delivered against a usual 40%. It closed near the day’s high.');
assert.match(html, /stock\.html\?ticker=RELIANCE&amp;pane=deliv/);

// A fall is said as a fall, in words and in colour, and never as "−-3.4%".
const tcs = d.views.today.rows.find(r => r.symbol === 'TCS');
assert.match(ui.reading('today', tcs), /as the price fell 3\.4%\./);
assert.match(ui.row('today', tcs), /class="dt-chg dn">−3\.4%/);

// ── Direction is a filter over the same rows, and the counts are the server's
const up = ui.render(d, { view: 'today', dir: 'up' });
const down = ui.render(d, { view: 'today', dir: 'down' });
assert.match(up, /data-sym="RELIANCE"/); assert.doesNotMatch(up, /data-sym="TCS"/);
assert.match(down, /data-sym="TCS"/); assert.doesNotMatch(down, /data-sym="RELIANCE"/);
const count = h => (h.match(/<details class="dt-row"/g) || []).length;
assert.equal(count(up) + count(down), count(html));
assert.match(html, new RegExp('Spikes today <span class="dt-count">' + d.views.today.total + '</span>'));

// ── Each list says its own rule, and the week names how many sessions ──────
const week = ui.render(d, { view: 'week', dir: 'all' });
assert.ok(week.includes(d.views.week.rule.replace(/&/g, '&amp;')));
const lt = d.views.week.rows.find(r => r.symbol === 'LT');
assert.match(ui.reading('week', lt), /with 4 of the last 5 sessions above normal\./);
const quiet = ui.render(d, { view: 'quiet', dir: 'up' });
assert.match(quiet, /data-sym="ITC"/, 'the quiet list ignores the direction filter');
assert.doesNotMatch(quiet, /data-dir=/, 'and does not offer one');
assert.match(ui.reading('quiet', d.views.quiet.rows.find(r => r.symbol === 'ITC')),
  /53% of the volume was delivered, against 40% in the 60 before/);

// ── The bar chart: one bar per reading, the row's own sessions marked ──────
const bars = s => (s.match(/<rect/g) || []).length, hot = s => (s.match(/class="hot"/g) || []).length;
const sp = ui.spark([1, 2, null, 4], 2, 1);
assert.equal(bars(sp), 3, 'a missing session draws no bar');
assert.equal(hot(sp), 1);
assert.equal(hot(ui.spark([1, 1, 1, 1, 1, 1, 1], 1, 5)), 5);
assert.doesNotMatch(ui.spark([null, null], null, 1), /<rect/);
assert.doesNotMatch(ui.spark([], 5, 1), /NaN/);
assert.equal(bars(ui.row('today', tcs)), tcs.spark_cr.filter(v => v !== null).length);
assert.ok(tcs.spark_cr.includes(null), 'the fixture carries a session with no quantity');

// ── Rupees at the precision the size deserves ─────────────────────────────
assert.equal(ui.cr(37442), '₹37,442 cr');
assert.equal(ui.cr(56), '₹56.0 cr');
assert.equal(ui.cr(3.456), '₹3.46 cr');
assert.equal(ui.cr(null), '—');
assert.equal(ui.times(12.4), '12×'); assert.equal(ui.times(1.26), '1.3×'); assert.equal(ui.times(undefined), '—');
assert.equal(ui.signed(0, 1, '%'), '0.0%'); assert.equal(ui.signed(-2.04, 1, ' pts'), '−2.0 pts');

// ── Industries, the market line, the limits ───────────────────────────────
assert.match(html, /Where the rupees went this week/);
assert.ok(html.includes(d.sectors[0].industry.replace(/&/g, '&amp;')));
assert.match(html, new RegExp(d.market.share_pct.toFixed(1) + '%'));
assert.match(html, /left out for a split or bonus/);
assert.doesNotMatch(html, /NaN|undefined|null/);

// ── States that are not a list ────────────────────────────────────────────
const young = ui.render({ available: false, building: true, sessions: 10, needed: 26, message: 'Reading — 10 of 26 sessions in.' });
assert.match(young, /10 \/ 26 sessions/); assert.match(young, /width:38%/);
assert.match(ui.render({ available: false, message: 'Not loaded.' }), /Nothing to show yet<\/b>Not loaded\./);
assert.match(ui.render(null), /could not be read just now/);
const noQuiet = JSON.parse(JSON.stringify(d));
noQuiet.views.quiet = { rows: [], total: 0, up: 0, down: 0, unavailable: true, rule: 'Needs 60 sessions of history; 40 are held so far.' };
assert.match(ui.render(noQuiet, { view: 'quiet' }), /class="dt-empty">Needs 60 sessions of history; 40 are held so far\./);
const none = JSON.parse(JSON.stringify(d));
none.views.today = { rows: [], total: 0, up: 0, down: 0, rule: 'r' };
assert.match(ui.render(none, { view: 'today' }), /No stock delivered twice its usual rupees/);
const capped = JSON.parse(JSON.stringify(d));
capped.views.today.total = 140;
assert.match(ui.render(capped, { view: 'today' }), new RegExp('The ' + d.views.today.rows.length + ' most unusual of 140 are listed'));

// ── Nothing from the feed reaches the page as markup ──────────────────────
const evil = JSON.parse(JSON.stringify(d));
evil.views.today.rows[0].symbol = '<img src=x onerror=1>';
evil.views.today.rows[0].name = '<script>x</script>';
evil.sectors[0].industry = '<b>Bad</b>';
const safe = ui.render(evil, { view: 'today' });
assert.doesNotMatch(safe, /<img|<script|<b>Bad/);
assert.match(safe, /&lt;img src=x onerror=1&gt;/);

console.log('delivery-trends: rows carry their arithmetic, a fall reads as a fall, holes draw nothing');
