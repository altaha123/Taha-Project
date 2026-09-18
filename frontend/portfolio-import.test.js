/* Broker statement import.
 *
 * Every failure this guards against is silent. A Dhan file imported twenty-one
 * holdings, dropped the cost basis because "Avg. Buy Rate" matched no column
 * name, turned every company into a symbol no exchange has ever heard of, and
 * added a twenty-second holding of ten lakh shares of "INVESTMENT" from the
 * totals line. Nothing threw. The page just quietly showed a portfolio that
 * was not the one in the file.
 */
'use strict';
const assert = require('node:assert/strict');

global.window = {};
global.document = {
  getElementById: () => null,
  createElement: () => ({ style: {}, classList: { add() {} }, setAttribute() {}, appendChild() {} })
};
require('./portfolio.js');
const P = global.window.AltahaPortfolio;

// Enough of /universe to cover the cases. Real shape: {s, n, x}.
const UNIVERSE = [
  { s: 'HSCL',       n: 'Himadri Speciality Chemical Limited', x: 'NSE' },
  { s: 'TARIL',      n: 'Transformers And Rectifiers (India) Limited', x: 'NSE' },
  { s: 'PRAVEG',     n: 'Praveg Limited', x: 'NSE' },
  { s: 'MANYAVAR',   n: 'Vedant Fashions Limited', x: 'NSE' },
  { s: 'PETRONET',   n: 'Petronet LNG Limited', x: 'NSE' },
  { s: 'INFY',       n: 'Infosys Limited', x: 'NSE' },
  { s: 'INDOTECH',   n: 'Indo Tech Transformers Limited', x: 'NSE' },
  { s: 'VOLTAMP',    n: 'Voltamp Transformers Limited', x: 'NSE' },
  { s: 'BAJAJ-AUTO', n: 'Bajaj Auto Limited', x: 'NSE' },
  { s: 'BAJFINANCE', n: 'Bajaj Finance Limited', x: 'NSE' },
  { s: 'BAJAJHLDNG', n: 'Bajaj Holdings & Investment Limited', x: 'NSE' }
];
const idx = P.indexUniverse(UNIVERSE);

// A Dhan export, shape for shape. The account details are invented — a real
// statement carries a client code, a mobile number and an email address, which
// is exactly why none of this is ever sent to the server.
const DHAN = `EQ,For 18-09-2026
Name,A Reader
UCC,AAAA00000A
Mobile,0000000000
Email ID,reader@example.com

Scrip Name,Quantity,Avg. Buy Rate,Buy Value,LTP,Current Value,P&L,P&L%
"Himadri Speciality Chemical","66","713.44","47086.85","662.50","43725.00","-3361.85","-7.14"
"Transformers & Rectifiers","379","416.43","157828.10","282.50","107067.50","-50760.60","-32.16"
"Praveg","27","732.00","19764.00","249.15","6727.05","-13036.95","-65.96"

Investment,1060205.80,Current Value,907338.99,Overall P&L,-152866.80,Overall P&L%,-14.42
NOTE : This sheet was downloaded at 9/18/2026 02:55 PM
`;

// ── The file parses, and the columns are found ───────────────────────────────

const rows = P.parseCSV(DHAN);
const head = P.findHeader(rows);
assert.ok(head, 'Dhan header row was not recognised');
assert.deepEqual(rows[head.index].slice(0, 3), ['Scrip Name', 'Quantity', 'Avg. Buy Rate']);
assert.equal(head.map.symbol, 0);
assert.equal(head.map.qty, 1);
assert.equal(head.map.buy, 2, 'the cost column was dropped — P&L would silently vanish');

// ── The totals line is not a holding ─────────────────────────────────────────

const parsed = P.rowsFromMap(rows, head.index, head.map);
assert.equal(parsed.length, 3, 'expected exactly the three real holdings');
assert.ok(!parsed.some(r => /investment/i.test(r.raw)), 'the totals line imported as a holding');
assert.equal(parsed[0].buy, 713.44);
assert.equal(parsed[0].qty, 66);

// ── Company names become the symbols everything downstream is keyed on ───────

const out = P.resolveRows(parsed, idx);
assert.deepEqual(out.unresolved, [], 'a holding was left unmatched');
assert.deepEqual(out.rows.map(r => r.symbol), ['HSCL', 'TARIL', 'PRAVEG']);
assert.equal(out.rows[0].buy, 713.44, 'cost basis lost in resolution');

// "&" is "And" on the exchange, and the broker drops the "(India)".
assert.equal(P.resolveOne('Transformers & Rectifiers', idx).symbol, 'TARIL');
// A ticker is checked before a name: PRAVEG is both, and the ticker cannot be wrong.
assert.equal(P.resolveOne('PRAVEG', idx).symbol, 'PRAVEG');
// The exchange name and the trading name are not the same word.
assert.equal(P.resolveOne('Vedant Fashions', idx).symbol, 'MANYAVAR');

// ── A broker that exports symbols still works, untouched ─────────────────────

const ZERODHA = 'Symbol,Quantity Available,Average Price\nINFY,10,1500.5\nHSCL,66,713.44\n';
const zRows = P.parseCSV(ZERODHA);
const zHead = P.findHeader(zRows);
assert.equal(zHead.map.buy, 2);
const zOut = P.resolveRows(P.rowsFromMap(zRows, zHead.index, zHead.map), idx);
assert.deepEqual(zOut.rows.map(r => r.symbol), ['INFY', 'HSCL']);
assert.deepEqual(zOut.unresolved, []);

// ── What cannot be placed is asked about, never guessed ──────────────────────

const unknown = P.resolveOne('Some Company That Is Not Listed', idx);
assert.equal(unknown.symbol, null, 'an unlisted name was silently matched to something');

// A name that genuinely fits several companies offers them rather than
// picking one. "Bajaj" is three different listed companies.
const ambiguous = P.resolveOne('Bajaj', idx);
assert.equal(ambiguous.symbol, null, 'a half-written name was resolved to one company');
assert.ok(ambiguous.candidates.length >= 3, 'expected the Bajaj companies offered as choices');

// But a name that uniquely starts a company's own name is not ambiguous:
// only one listed company is called "Transformers ...".
assert.equal(P.resolveOne('Transformers', idx).symbol, 'TARIL');

// ── Name normalisation ───────────────────────────────────────────────────────

assert.equal(P.normName('Himadri Speciality Chemical Limited'), 'himadri speciality chemical');
assert.equal(P.normName('Transformers & Rectifiers'), 'transformers and rectifiers');
assert.equal(P.normName('  ACME   Industries Ltd.  '), 'acme industries');

console.log('Broker import: Dhan names resolve, cost basis survives, totals line stays out.');
