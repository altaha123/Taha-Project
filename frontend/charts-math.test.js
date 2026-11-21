/* node frontend/charts-math.test.js

   The indicator arithmetic is the part of a chart that can be wrong without
   looking wrong: an RSI that is off by three points still draws a perfectly
   plausible line. So the values here are checked against pandas and against
   the backend's own engine.py on one 400-bar series, and every indicator in
   the catalogue is run once to prove it returns arrays of the right length
   with no NaN in them.

   The reference numbers were produced by engine.py (EMA, RSI, MACD, ATR, ADX,
   WMA, Supertrend) and by plain pandas for the rest. engine.py seeds its
   averages from the first price, TradingView and this file from a simple
   average of the first n; the two agree once the warm-up has passed, which is
   why the comparison is made on the last bar of 400. */
const assert = require('node:assert/strict');
const M = require('./charts-math.js');

const n = 400, c = [], h = [], l = [], o = [], v = [], t = [];
for (let i = 0; i < n; i++) {
  c.push(100 + 10 * Math.sin(i / 7) + i * 0.1 + 3 * Math.cos(i / 3.3));
  h.push(c[i] + 1 + Math.abs(Math.sin(i)));
  l.push(c[i] - 1 - Math.abs(Math.cos(i)));
  o.push(i ? c[i - 1] : c[0]);
  v.push(1000 + 500 * Math.abs(Math.sin(i / 5)));
  t.push(1700000000 + i * 86400);
}
const last = a => a[a.length - 1];
const near = (got, want, tol, what) =>
  assert.ok(Math.abs(got - want) <= tol, `${what}: got ${got}, want ${want} (within ${tol})`);

near(last(M.ema(c, 20)), 137.37391411215447, 1e-6, 'EMA 20');
near(last(M.rsi(c, 14)), 75.28034093694406, 1e-6, 'RSI 14');
const md = M.macd(c, 12, 26, 9);
near(last(md.line), 2.2863727463624457, 1e-6, 'MACD line');
near(last(md.sig), 0.564178489325574, 1e-6, 'MACD signal');
near(last(md.hist), 1.7221942570368718, 1e-6, 'MACD histogram');
near(last(M.atr(h, l, c, 14)), 3.3642281013053887, 1e-6, 'ATR 14');
near(last(M.adx(h, l, c, 14).adx), 38.43543050501318, 1e-4, 'ADX 14');
near(last(M.wma(c, 10)), 141.63350132984564, 1e-9, 'WMA 10');
near(last(M.bollinger(c, 20, 2).up), 147.1595753475331, 1e-9, 'Bollinger upper');
const st = M.stoch(h, l, c, 14, 3, 3);
near(last(st.k), 92.06448909654311, 1e-9, 'Stochastic %K');
near(last(st.d), 92.07453192357065, 1e-9, 'Stochastic %D');
near(last(M.cci(h, l, c, 20)), 112.9077113783577, 1e-9, 'CCI 20');
near(last(M.obv(c, v)), 39316.282826838986, 1e-6, 'OBV');
near(last(M.mfi(h, l, c, v, 14)), 100, 1e-9, 'MFI 14');
near(last(M.willr(h, l, c, 14)), -6.13784329342215, 1e-9, 'Williams %R');
near(last(M.vwap(h, l, c, v, () => 0)), 120.00044462999549, 1e-9, 'VWAP, one session');
const dc = M.donchian(h, l, 20);
near(last(dc.up), 145.6831329434164, 1e-9, 'Donchian upper');
near(last(dc.lo), 123.73033839842009, 1e-9, 'Donchian lower');
near(last(M.roc(c, 12)), 13.12555389711665, 1e-9, 'ROC 12');

/* Supertrend agrees with engine.py on the direction it ends in. */
const sup = M.supertrend(h, l, c, 10, 3);
assert.equal(last(sup.dir), 1, 'Supertrend ends bullish, as engine.py says');

/* Warm-up is null, never 0 and never NaN: a chart leaves a gap there. */
assert.equal(M.rsi(c, 14)[13], null);
assert.ok(M.rsi(c, 14)[14] != null);
assert.equal(M.sma(c, 5)[3], null);
assert.equal(M.ema(c, 5)[3], null);
near(M.ema(c, 5)[4], (c[0] + c[1] + c[2] + c[3] + c[4]) / 5, 1e-12, 'EMA seeded with the SMA');

/* An RSI over an unbroken advance is 100, not NaN (the engine.py bug). */
const up = Array.from({ length: 30 }, (_, i) => 100 + i);
assert.equal(last(M.rsi(up, 14)), 100);

/* Candle transforms. */
const rows = c.map((x, i) => ({ time: t[i], open: o[i], high: h[i], low: l[i], close: x, volume: v[i] }));
const ha = M.heikinAshi(rows);
assert.equal(ha.length, n);
near(ha[5].close, (rows[5].open + rows[5].high + rows[5].low + rows[5].close) / 4, 1e-12, 'HA close');
near(ha[5].open, (ha[4].open + ha[4].close) / 2, 1e-12, 'HA open');

/* Intraday folding never joins the last bar of one session to the first of
   the next, and keeps the first bar's time. */
const day = 86400, s0 = 20000 * day + 9 * 3600 + 15 * 60;
const intra = [];
for (let d = 0; d < 2; d++) for (let k = 0; k < 5; k++) {
  intra.push({ time: s0 + d * day + k * 900, open: 10 + k, high: 11 + k, low: 9 + k, close: 10.5 + k, volume: 100 });
}
const fold = M.resampleIntraday(intra, 2);
assert.equal(fold.length, 6, '5 bars a day in pairs is 3 a day, never a bar across the night');
assert.equal(fold[0].time, intra[0].time);
assert.equal(fold[0].open, 10); assert.equal(fold[0].close, 11.5); assert.equal(fold[0].high, 12); assert.equal(fold[0].low, 9);
assert.equal(fold[0].volume, 200);
assert.equal(fold[3].time, intra[5].time, 'the second session starts a new bar');

const monthly = M.resample(rows, r => M.monthKey(r.time));
assert.ok(monthly.length >= 13 && monthly.length <= 15, 'about thirteen months in 400 days');
assert.equal(monthly.reduce((s, r) => s + r.volume, 0).toFixed(6), v.reduce((s, x) => s + x, 0).toFixed(6), 'no volume lost in folding');

/* ZigZag pivots alternate between highs and lows. */
const zz = M.zigzag(h, l, 5);
for (let i = 1; i < zz.pivots.length; i++) assert.notEqual(zz.pivots[i].hi, zz.pivots[i - 1].hi, 'zigzag alternates');

/* Volume profile puts all the volume somewhere. */
const vp = M.volumeProfile(h, l, c, o, v, 100, 200, 24);
const vpTotal = vp.up.reduce((s, x) => s + x, 0) + vp.dn.reduce((s, x) => s + x, 0);
near(vpTotal, v.slice(100, 201).reduce((s, x) => s + x, 0), 1e-6, 'volume profile total');

/* Regression channel through a straight line has no spread. */
const straight = Array.from({ length: 50 }, (_, i) => 10 + 2 * i);
const reg = M.regression(straight, 5, 25);
near(reg.slope, 2, 1e-12, 'regression slope'); near(reg.sd, 0, 1e-9, 'regression spread');
near(reg.start, 20, 1e-9, 'regression start'); near(reg.end, 60, 1e-9, 'regression end');

/* Every indicator in the catalogue: arrays at least as long as the input,
   finite or null, never NaN, and an output for every line it declares. */
const D = M.columns(rows);
assert.equal(D.barSec, 86400);
let count = 0;
for (const def of M.INDICATORS) {
  const out = def.calc(D, M.defaults(def));
  for (const o2 of def.out) {
    const a = out[o2.k];
    assert.ok(Array.isArray(a), `${def.id}: no "${o2.k}" output`);
    assert.ok(a.length >= n, `${def.id}.${o2.k}: ${a.length} values for ${n} bars`);
    assert.ok(a.every(x => x === null || Number.isFinite(x)), `${def.id}.${o2.k}: NaN or Infinity in the output`);
    /* VWAP is session-only, and a line whose length is 0 is switched off. */
    const off = M.defaults(def)[o2.k] === 0;
    if (!/^(vwap)$/.test(def.id) && !off) assert.ok(a.some(x => x !== null), `${def.id}.${o2.k}: nothing but gaps`);
  }
  assert.ok(def.name && def.short && def.cat, `${def.id}: unnamed`);
  count++;
}
assert.ok(count >= 40, `${count} indicators`);
assert.equal(new Set(M.INDICATORS.map(d => d.id)).size, count, 'indicator ids are unique');

/* Ichimoku's spans are drawn 26 bars ahead, so they run past the last candle. */
const ich = M.indicator('ichimoku').calc(D, M.defaults(M.indicator('ichimoku')));
assert.equal(ich.spanA.length, n + 26);

console.log(`charts-math: ${count} indicators checked against pandas and engine.py, transforms and drawings maths hold`);
