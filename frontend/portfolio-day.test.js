/* The portfolio's "Today" figure.
 *
 * A reader added three stocks on the day they bought them. All three were
 * below their buy price, so the review said −₹96 overall — and +₹720 today.
 * The +₹720 was each stock's move from yesterday's close, a move that
 * happened before the reader owned any of it. A holding bought today starts
 * its day at the buy price, the way every broker counts it.
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

// ── The exchange's date, not the reader's ────────────────────────────────────

assert.equal(P.istToday(Date.parse('2026-11-22T19:00:00Z')), '2026-11-23', '00:30 IST is already the 23rd');
assert.equal(P.istToday(Date.parse('2026-11-23T18:29:00Z')), '2026-11-23', '23:59 IST is still the 23rd');
assert.equal(P.istToday(Date.parse('2026-11-23T18:31:00Z')), '2026-11-24');

// ── Where the day starts ─────────────────────────────────────────────────────

const TODAY = '2026-11-23';
assert.equal(P.dayOpenPrice(100, 90, '2026-11-20', TODAY), 100, 'held from before: yesterday\'s close');
assert.equal(P.dayOpenPrice(100, 90, '', TODAY), 100, 'no buy date: yesterday\'s close');
assert.equal(P.dayOpenPrice(100, 105, TODAY, TODAY), 105, 'bought today: the buy price');
assert.equal(P.dayOpenPrice(100, null, TODAY, TODAY), 100, 'bought today, cost unknown: nothing better than the close');
assert.equal(P.dayOpenPrice(null, null, '', TODAY), null, 'no close and no cost: no day figure');

// ── The portfolio that was reported ──────────────────────────────────────────

const book = [
  // symbol,       qty, avg cost, ltp,    today's move
  ['ABDL',         20,  795.20,   794.05, -0.03],
  ['HONASA',       30,  536.00,   535.30, +1.88],
  ['WELSPUNLIV',   58,  277.05,   276.16, +2.75]
];
let day = 0, wrong = 0, pl = 0;
book.forEach(function (h) {
  const qty = h[1], buy = h[2], ltp = h[3];
  const prev = ltp / (1 + h[4] / 100);
  wrong += qty * (ltp - prev);
  day += qty * (ltp - P.dayOpenPrice(prev, buy, TODAY, TODAY));
  pl += qty * (ltp - buy);
});
assert.equal(Math.round(wrong), 720, 'the figure that was shown, for the record');
assert.equal(Math.round(day), -96, 'bought today: the day is the whole of the P&L');
assert.equal(Math.round(day), Math.round(pl));

console.log('Portfolio day: a holding bought today starts its day at the buy price.');
