/* ============================================================================
   Altaha Charts: the arithmetic
   ----------------------------------------------------------------------------
   Everything the charting workspace computes from candles lives here and
   nowhere else: the moving averages, the oscillators, the bands, the candle
   transforms (Heikin Ashi, resampling to a longer bar) and the catalogue that
   says which indicators exist, what they can be tuned by, and how each is
   drawn.

   No DOM, no chart library, no globals read. That is deliberate: this is the
   one part of a chart that can be wrong without looking wrong, so it is the
   part that has to run under plain node (charts-math.test.js, on every push).

   Conventions
   - Inputs are plain arrays of numbers, oldest first.
   - Outputs are arrays of the same length. A bar with no value yet (the first
     thirteen bars of a 14-period RSI) is null, never 0 and never NaN, so a
     chart can leave a gap instead of drawing a line to the floor.
   ========================================================================== */

(function (root, factory) {
  var M = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = M;
  else root.AltahaChartMath = M;
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";

  function nulls(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = null; return a; }
  function ok(x) { return x != null && isFinite(x); }

  /* ── averages ──────────────────────────────────────────────────────────── */

  /* Every average here tolerates leading nulls, because they are chained:
     a MACD signal line is an EMA of a series whose first 25 values do not
     exist. The window only starts counting at the first real value. */

  function sma(v, n) {
    var out = nulls(v.length), s = 0, cnt = 0, q = [];
    for (var i = 0; i < v.length; i++) {
      if (!ok(v[i])) { s = 0; cnt = 0; q = []; continue; }
      q.push(v[i]); s += v[i]; cnt++;
      if (cnt > n) { s -= q.shift(); cnt--; }
      if (cnt === n) out[i] = s / n;
    }
    return out;
  }

  /* Seeded with the simple average of the first n values, which is what every
     reference implementation (and the backend's engine.py) does. Seeding with
     the first price instead gives numbers that disagree for the first few
     hundred bars. */
  function ema(v, n) {
    var out = nulls(v.length), k = 2 / (n + 1), prev = null, s = 0, cnt = 0;
    for (var i = 0; i < v.length; i++) {
      if (!ok(v[i])) continue;
      if (prev == null) {
        s += v[i]; cnt++;
        if (cnt === n) { prev = s / n; out[i] = prev; }
      } else {
        prev = v[i] * k + prev * (1 - k);
        out[i] = prev;
      }
    }
    return out;
  }

  /* Wilder's smoothing: an EMA with alpha 1/n. RSI, ATR and ADX all use it. */
  function rma(v, n) {
    var out = nulls(v.length), prev = null, s = 0, cnt = 0;
    for (var i = 0; i < v.length; i++) {
      if (!ok(v[i])) continue;
      if (prev == null) {
        s += v[i]; cnt++;
        if (cnt === n) { prev = s / n; out[i] = prev; }
      } else {
        prev = (prev * (n - 1) + v[i]) / n;
        out[i] = prev;
      }
    }
    return out;
  }

  function wma(v, n) {
    var out = nulls(v.length), den = n * (n + 1) / 2;
    for (var i = n - 1; i < v.length; i++) {
      var s = 0, good = true;
      for (var j = 0; j < n; j++) {
        var x = v[i - j];
        if (!ok(x)) { good = false; break; }
        s += x * (n - j);
      }
      if (good) out[i] = s / den;
    }
    return out;
  }

  function hma(v, n) {
    var half = wma(v, Math.max(1, Math.floor(n / 2))), full = wma(v, n), d = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(half[i]) && ok(full[i])) d[i] = 2 * half[i] - full[i];
    return wma(d, Math.max(1, Math.round(Math.sqrt(n))));
  }

  function vwma(v, vol, n) {
    var out = nulls(v.length);
    for (var i = n - 1; i < v.length; i++) {
      var pv = 0, vv = 0;
      for (var j = i - n + 1; j <= i; j++) { pv += v[j] * (vol[j] || 0); vv += (vol[j] || 0); }
      if (vv) out[i] = pv / vv;
    }
    return out;
  }

  function dema(v, n) {
    var e1 = ema(v, n), e2 = ema(e1, n), out = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(e1[i]) && ok(e2[i])) out[i] = 2 * e1[i] - e2[i];
    return out;
  }

  function tema(v, n) {
    var e1 = ema(v, n), e2 = ema(e1, n), e3 = ema(e2, n), out = nulls(v.length);
    for (var i = 0; i < v.length; i++)
      if (ok(e1[i]) && ok(e2[i]) && ok(e3[i])) out[i] = 3 * e1[i] - 3 * e2[i] + e3[i];
    return out;
  }

  function ma(kind, v, n, vol) {
    if (kind === "EMA") return ema(v, n);
    if (kind === "WMA") return wma(v, n);
    if (kind === "HMA") return hma(v, n);
    if (kind === "RMA") return rma(v, n);
    if (kind === "VWMA") return vwma(v, vol || [], n);
    return sma(v, n);
  }

  /* ── rolling windows ───────────────────────────────────────────────────── */

  function highest(v, n) {
    var out = nulls(v.length);
    for (var i = n - 1; i < v.length; i++) {
      var m = -Infinity;
      for (var j = i - n + 1; j <= i; j++) if (v[j] > m) m = v[j];
      out[i] = m;
    }
    return out;
  }
  function lowest(v, n) {
    var out = nulls(v.length);
    for (var i = n - 1; i < v.length; i++) {
      var m = Infinity;
      for (var j = i - n + 1; j <= i; j++) if (v[j] < m) m = v[j];
      out[i] = m;
    }
    return out;
  }
  /* Population standard deviation, as Bollinger defined his bands. */
  function stdev(v, n) {
    var out = nulls(v.length);
    for (var i = n - 1; i < v.length; i++) {
      var s = 0, good = true, j;
      for (j = i - n + 1; j <= i; j++) { if (!ok(v[j])) { good = false; break; } s += v[j]; }
      if (!good) continue;
      var m = s / n, q = 0;
      for (j = i - n + 1; j <= i; j++) q += (v[j] - m) * (v[j] - m);
      out[i] = Math.sqrt(q / n);
    }
    return out;
  }
  function typical(h, l, c) {
    var out = new Array(c.length);
    for (var i = 0; i < c.length; i++) out[i] = (h[i] + l[i] + c[i]) / 3;
    return out;
  }
  function trueRange(h, l, c) {
    var out = new Array(c.length);
    for (var i = 0; i < c.length; i++) {
      out[i] = i === 0 ? h[i] - l[i]
        : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
    }
    return out;
  }
  function atr(h, l, c, n) { return rma(trueRange(h, l, c), n); }

  /* ── bands and overlays ────────────────────────────────────────────────── */

  function bollinger(v, n, k) {
    var mid = sma(v, n), sd = stdev(v, n), up = nulls(v.length), lo = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(mid[i]) && ok(sd[i])) {
      up[i] = mid[i] + k * sd[i]; lo[i] = mid[i] - k * sd[i];
    }
    return { mid: mid, up: up, lo: lo };
  }

  function keltner(h, l, c, n, mult, atrLen) {
    var mid = ema(c, n), a = atr(h, l, c, atrLen || n), up = nulls(c.length), lo = nulls(c.length);
    for (var i = 0; i < c.length; i++) if (ok(mid[i]) && ok(a[i])) {
      up[i] = mid[i] + mult * a[i]; lo[i] = mid[i] - mult * a[i];
    }
    return { mid: mid, up: up, lo: lo };
  }

  function donchian(h, l, n) {
    var up = highest(h, n), lo = lowest(l, n), mid = nulls(h.length);
    for (var i = 0; i < h.length; i++) if (ok(up[i]) && ok(lo[i])) mid[i] = (up[i] + lo[i]) / 2;
    return { up: up, lo: lo, mid: mid };
  }

  function envelope(v, n, pct) {
    var mid = sma(v, n), up = nulls(v.length), lo = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(mid[i])) {
      up[i] = mid[i] * (1 + pct / 100); lo[i] = mid[i] * (1 - pct / 100);
    }
    return { mid: mid, up: up, lo: lo };
  }

  /* Supertrend. `dir` is +1 while price is above the line (an uptrend, line
     drawn under the candles) and -1 while below. */
  function supertrend(h, l, c, n, mult) {
    var a = atr(h, l, c, n), len = c.length;
    var line = nulls(len), dir = nulls(len), fu = null, fl = null, d = 1;
    for (var i = 0; i < len; i++) {
      if (!ok(a[i])) continue;
      var mid = (h[i] + l[i]) / 2, bu = mid + mult * a[i], bl = mid - mult * a[i];
      if (fu == null) { fu = bu; fl = bl; }
      else {
        fu = (bu < fu || c[i - 1] > fu) ? bu : fu;
        fl = (bl > fl || c[i - 1] < fl) ? bl : fl;
        if (d === 1 && c[i] < fl) d = -1;
        else if (d === -1 && c[i] > fu) d = 1;
      }
      dir[i] = d; line[i] = d === 1 ? fl : fu;
    }
    return { line: line, dir: dir };
  }

  /* Parabolic SAR, Wilder's original rules: the stop accelerates each time
     price makes a new extreme, and may never sit inside the previous two bars. */
  function psar(h, l, step, max) {
    var n = h.length, out = nulls(n), dir = nulls(n);
    if (n < 2) return { sar: out, dir: dir };
    var up = h[1] >= h[0], af = step, ep = up ? h[0] : l[0], s = up ? l[0] : h[0];
    for (var i = 1; i < n; i++) {
      s = s + af * (ep - s);
      if (up) {
        s = Math.min(s, l[i - 1], i > 1 ? l[i - 2] : l[i - 1]);
        if (l[i] < s) { up = false; s = ep; ep = l[i]; af = step; }
        else if (h[i] > ep) { ep = h[i]; af = Math.min(max, af + step); }
      } else {
        s = Math.max(s, h[i - 1], i > 1 ? h[i - 2] : h[i - 1]);
        if (h[i] > s) { up = true; s = ep; ep = h[i]; af = step; }
        else if (l[i] < ep) { ep = l[i]; af = Math.min(max, af + step); }
      }
      out[i] = s; dir[i] = up ? 1 : -1;
    }
    return { sar: out, dir: dir };
  }

  /* Ichimoku. The two spans are plotted `disp` bars AHEAD of the bar they are
     computed on, so those arrays are longer than the input by `disp`. The
     caller supplies the future timestamps. Chikou is the close plotted `disp`
     bars BACK. */
  function ichimoku(h, l, c, conv, base, spanB, disp) {
    var n = c.length;
    function mid(len) {
      var hh = highest(h, len), ll = lowest(l, len), o = nulls(n);
      for (var i = 0; i < n; i++) if (ok(hh[i]) && ok(ll[i])) o[i] = (hh[i] + ll[i]) / 2;
      return o;
    }
    var tenkan = mid(conv), kijun = mid(base), sb = mid(spanB);
    var a = nulls(n + disp), b = nulls(n + disp), chikou = nulls(n);
    for (var i = 0; i < n; i++) {
      if (ok(tenkan[i]) && ok(kijun[i])) a[i + disp] = (tenkan[i] + kijun[i]) / 2;
      if (ok(sb[i])) b[i + disp] = sb[i];
      if (i - disp >= 0) chikou[i - disp] = c[i];
    }
    return { tenkan: tenkan, kijun: kijun, spanA: a, spanB: b, chikou: chikou };
  }

  /* VWAP that restarts each session. `dayOf(i)` names the session a bar
     belongs to; the chart passes the calendar day. */
  function vwap(h, l, c, vol, dayOf) {
    var out = nulls(c.length), pv = 0, vv = 0, day = null;
    for (var i = 0; i < c.length; i++) {
      var d = dayOf ? dayOf(i) : 0;
      if (d !== day) { day = d; pv = 0; vv = 0; }
      var w = vol[i] || 0;
      pv += (h[i] + l[i] + c[i]) / 3 * w; vv += w;
      if (vv) out[i] = pv / vv;
    }
    return out;
  }

  /* VWAP from one chosen bar onward: what it has cost, on average, to own the
     stock since that day. */
  function anchoredVwap(h, l, c, vol, from) {
    var out = nulls(c.length), pv = 0, vv = 0;
    for (var i = Math.max(0, from); i < c.length; i++) {
      var w = vol[i] || 0;
      pv += (h[i] + l[i] + c[i]) / 3 * w; vv += w;
      if (vv) out[i] = pv / vv;
    }
    return out;
  }

  function alligator(h, l) {
    var med = h.map(function (x, i) { return (x + l[i]) / 2; });
    function shift(a, k) { var o = nulls(a.length + k); for (var i = 0; i < a.length; i++) o[i + k] = a[i]; return o; }
    return { jaw: shift(rma(med, 13), 8), teeth: shift(rma(med, 8), 5), lips: shift(rma(med, 5), 3) };
  }

  /* ZigZag: joins swing highs and lows that reverse by at least `pct` percent.
     Returned as a sparse array (value at pivots, null between) plus the pivot
     list, so a chart can draw straight segments between them. */
  function zigzag(h, l, pct) {
    var n = h.length, out = nulls(n), piv = [];
    if (n < 2) return { line: out, pivots: piv };
    var th = pct / 100, dir = 0, hi = h[0], hiI = 0, lo = l[0], loI = 0;
    for (var i = 1; i < n; i++) {
      if (dir >= 0 && h[i] > hi) { hi = h[i]; hiI = i; }
      if (dir <= 0 && l[i] < lo) { lo = l[i]; loI = i; }
      if (dir >= 0 && l[i] <= hi * (1 - th) && hiI !== i) {
        piv.push({ i: hiI, p: hi, hi: true }); dir = -1; lo = l[i]; loI = i;
      } else if (dir <= 0 && h[i] >= lo * (1 + th) && loI !== i) {
        piv.push({ i: loI, p: lo, hi: false }); dir = 1; hi = h[i]; hiI = i;
      }
    }
    if (dir === 1) piv.push({ i: hiI, p: hi, hi: true });
    else if (dir === -1) piv.push({ i: loI, p: lo, hi: false });
    piv.sort(function (a, b) { return a.i - b.i; });
    /* Fill the gaps by straight-line interpolation so one line series draws it. */
    for (var k = 0; k < piv.length; k++) {
      out[piv[k].i] = piv[k].p;
      if (k) {
        var a = piv[k - 1], b = piv[k];
        for (var j = a.i + 1; j < b.i; j++) out[j] = a.p + (b.p - a.p) * (j - a.i) / (b.i - a.i);
      }
    }
    return { line: out, pivots: piv };
  }

  /* Classic floor-trader pivots from the previous period's high, low and
     close. `periodOf(i)` names the period (day, week or month) of bar i. */
  function pivots(h, l, c, periodOf) {
    var n = c.length, keys = ["p", "r1", "r2", "r3", "s1", "s2", "s3"], out = {};
    keys.forEach(function (k) { out[k] = nulls(n); });
    var cur = null, ph = null, pl = null, pc = null, hh = -Infinity, ll = Infinity, cc = null, lv = null;
    for (var i = 0; i < n; i++) {
      var per = periodOf(i);
      if (per !== cur) {
        if (cur != null) { ph = hh; pl = ll; pc = cc; }
        cur = per; hh = -Infinity; ll = Infinity;
        if (ph != null) {
          var p = (ph + pl + pc) / 3;
          lv = { p: p, r1: 2 * p - pl, s1: 2 * p - ph, r2: p + (ph - pl), s2: p - (ph - pl),
                 r3: ph + 2 * (p - pl), s3: pl - 2 * (ph - p) };
        }
      }
      if (h[i] > hh) hh = h[i];
      if (l[i] < ll) ll = l[i];
      cc = c[i];
      if (lv) keys.forEach(function (k) { out[k][i] = lv[k]; });
    }
    return out;
  }

  /* ── oscillators ───────────────────────────────────────────────────────── */

  function rsi(v, n) {
    var out = nulls(v.length), g = 0, l = 0;
    for (var i = 1; i < v.length; i++) {
      var d = v[i] - v[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
      if (i <= n) {
        g += up; l += dn;
        if (i === n) { g /= n; l /= n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); }
      } else {
        g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n;
        out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
      }
    }
    return out;
  }

  function macd(v, fast, slow, signal) {
    var f = ema(v, fast), s = ema(v, slow), n = v.length, line = nulls(n), hist = nulls(n);
    for (var i = 0; i < n; i++) if (ok(f[i]) && ok(s[i])) line[i] = f[i] - s[i];
    var sig = ema(line, signal);
    for (i = 0; i < n; i++) if (ok(line[i]) && ok(sig[i])) hist[i] = line[i] - sig[i];
    return { line: line, sig: sig, hist: hist };
  }

  function stoch(h, l, c, kLen, kSmooth, dLen) {
    var hh = highest(h, kLen), ll = lowest(l, kLen), raw = nulls(c.length);
    for (var i = 0; i < c.length; i++) if (ok(hh[i]) && ok(ll[i])) {
      raw[i] = hh[i] === ll[i] ? 50 : 100 * (c[i] - ll[i]) / (hh[i] - ll[i]);
    }
    var k = sma(raw, kSmooth);
    return { k: k, d: sma(k, dLen) };
  }

  function stochRsi(v, rsiLen, stLen, kSmooth, dLen) {
    var r = rsi(v, rsiLen), raw = nulls(v.length);
    for (var i = 0; i < v.length; i++) {
      if (i < stLen - 1 || !ok(r[i - stLen + 1])) continue;
      var hi = -Infinity, lo = Infinity;
      for (var j = i - stLen + 1; j <= i; j++) { if (r[j] > hi) hi = r[j]; if (r[j] < lo) lo = r[j]; }
      raw[i] = hi === lo ? 50 : 100 * (r[i] - lo) / (hi - lo);
    }
    var k = sma(raw, kSmooth);
    return { k: k, d: sma(k, dLen) };
  }

  function adx(h, l, c, n) {
    var len = c.length, pdm = new Array(len), mdm = new Array(len);
    pdm[0] = 0; mdm[0] = 0;
    for (var i = 1; i < len; i++) {
      var up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
      pdm[i] = (up > dn && up > 0) ? up : 0;
      mdm[i] = (dn > up && dn > 0) ? dn : 0;
    }
    var tr = rma(trueRange(h, l, c), n), p = rma(pdm, n), m = rma(mdm, n);
    var pdi = nulls(len), mdi = nulls(len), dx = nulls(len);
    for (i = 0; i < len; i++) if (ok(tr[i]) && tr[i] !== 0) {
      pdi[i] = 100 * p[i] / tr[i]; mdi[i] = 100 * m[i] / tr[i];
      var s = pdi[i] + mdi[i];
      dx[i] = s === 0 ? 0 : 100 * Math.abs(pdi[i] - mdi[i]) / s;
    }
    return { adx: rma(dx, n), pdi: pdi, mdi: mdi };
  }

  function cci(h, l, c, n) {
    var tp = typical(h, l, c), m = sma(tp, n), out = nulls(c.length);
    for (var i = n - 1; i < c.length; i++) {
      if (!ok(m[i])) continue;
      var dev = 0;
      for (var j = i - n + 1; j <= i; j++) dev += Math.abs(tp[j] - m[i]);
      dev /= n;
      out[i] = dev === 0 ? 0 : (tp[i] - m[i]) / (0.015 * dev);
    }
    return out;
  }

  function willr(h, l, c, n) {
    var hh = highest(h, n), ll = lowest(l, n), out = nulls(c.length);
    for (var i = 0; i < c.length; i++) if (ok(hh[i]) && ok(ll[i])) {
      out[i] = hh[i] === ll[i] ? -50 : -100 * (hh[i] - c[i]) / (hh[i] - ll[i]);
    }
    return out;
  }

  function mfi(h, l, c, vol, n) {
    var tp = typical(h, l, c), out = nulls(c.length);
    for (var i = n; i < c.length; i++) {
      var pos = 0, neg = 0;
      for (var j = i - n + 1; j <= i; j++) {
        var f = tp[j] * (vol[j] || 0);
        if (tp[j] > tp[j - 1]) pos += f; else if (tp[j] < tp[j - 1]) neg += f;
      }
      out[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
    }
    return out;
  }

  function obv(c, vol) {
    var out = new Array(c.length), s = 0;
    for (var i = 0; i < c.length; i++) {
      if (i) s += c[i] > c[i - 1] ? (vol[i] || 0) : c[i] < c[i - 1] ? -(vol[i] || 0) : 0;
      out[i] = s;
    }
    return out;
  }

  function roc(v, n) {
    var out = nulls(v.length);
    for (var i = n; i < v.length; i++) if (v[i - n]) out[i] = 100 * (v[i] - v[i - n]) / v[i - n];
    return out;
  }
  function momentum(v, n) {
    var out = nulls(v.length);
    for (var i = n; i < v.length; i++) out[i] = v[i] - v[i - n];
    return out;
  }

  /* Accumulation/distribution line, and the two things built on it. */
  function adl(h, l, c, vol) {
    var out = new Array(c.length), s = 0;
    for (var i = 0; i < c.length; i++) {
      var r = h[i] - l[i];
      s += r ? ((c[i] - l[i]) - (h[i] - c[i])) / r * (vol[i] || 0) : 0;
      out[i] = s;
    }
    return out;
  }
  function cmf(h, l, c, vol, n) {
    var out = nulls(c.length);
    for (var i = n - 1; i < c.length; i++) {
      var mf = 0, vv = 0;
      for (var j = i - n + 1; j <= i; j++) {
        var r = h[j] - l[j], w = vol[j] || 0;
        mf += r ? ((c[j] - l[j]) - (h[j] - c[j])) / r * w : 0; vv += w;
      }
      out[i] = vv ? mf / vv : 0;
    }
    return out;
  }
  function chaikinOsc(h, l, c, vol, fast, slow) {
    var a = adl(h, l, c, vol), f = ema(a, fast), s = ema(a, slow), out = nulls(c.length);
    for (var i = 0; i < c.length; i++) if (ok(f[i]) && ok(s[i])) out[i] = f[i] - s[i];
    return out;
  }

  function awesome(h, l) {
    var med = h.map(function (x, i) { return (x + l[i]) / 2; });
    var f = sma(med, 5), s = sma(med, 34), out = nulls(h.length);
    for (var i = 0; i < h.length; i++) if (ok(f[i]) && ok(s[i])) out[i] = f[i] - s[i];
    return out;
  }

  function aroon(h, l, n) {
    var up = nulls(h.length), dn = nulls(h.length);
    for (var i = n; i < h.length; i++) {
      var hi = -Infinity, hiI = i, lo = Infinity, loI = i;
      for (var j = i - n; j <= i; j++) {
        if (h[j] >= hi) { hi = h[j]; hiI = j; }
        if (l[j] <= lo) { lo = l[j]; loI = j; }
      }
      up[i] = 100 * (n - (i - hiI)) / n; dn[i] = 100 * (n - (i - loI)) / n;
    }
    return { up: up, dn: dn };
  }

  function trix(v, n) {
    var e3 = ema(ema(ema(v, n), n), n), out = nulls(v.length);
    for (var i = 1; i < v.length; i++) if (ok(e3[i]) && ok(e3[i - 1]) && e3[i - 1]) {
      out[i] = 100 * (e3[i] - e3[i - 1]) / e3[i - 1];
    }
    return out;
  }

  function tsi(v, long, short) {
    var n = v.length, m = nulls(n), am = nulls(n);
    for (var i = 1; i < n; i++) { m[i] = v[i] - v[i - 1]; am[i] = Math.abs(m[i]); }
    var a = ema(ema(m, long), short), b = ema(ema(am, long), short), out = nulls(n);
    for (i = 0; i < n; i++) if (ok(a[i]) && ok(b[i]) && b[i]) out[i] = 100 * a[i] / b[i];
    return out;
  }

  function cmo(v, n) {
    var out = nulls(v.length);
    for (var i = n; i < v.length; i++) {
      var up = 0, dn = 0;
      for (var j = i - n + 1; j <= i; j++) { var d = v[j] - v[j - 1]; if (d > 0) up += d; else dn -= d; }
      out[i] = (up + dn) === 0 ? 0 : 100 * (up - dn) / (up + dn);
    }
    return out;
  }

  function ultimate(h, l, c, a, b, d) {
    var n = c.length, bp = new Array(n), tr = new Array(n), out = nulls(n);
    for (var i = 0; i < n; i++) {
      var pc = i ? c[i - 1] : c[i];
      bp[i] = c[i] - Math.min(l[i], pc);
      tr[i] = Math.max(h[i], pc) - Math.min(l[i], pc);
    }
    function avg(i, len) {
      var x = 0, y = 0;
      for (var j = i - len + 1; j <= i; j++) { x += bp[j]; y += tr[j]; }
      return y ? x / y : 0;
    }
    for (i = d; i < n; i++) out[i] = 100 * (4 * avg(i, a) + 2 * avg(i, b) + avg(i, d)) / 7;
    return out;
  }

  /* Annualised close-to-close volatility, in percent. */
  function histVol(v, n, perYear) {
    var r = nulls(v.length);
    for (var i = 1; i < v.length; i++) if (v[i - 1] > 0 && v[i] > 0) r[i] = Math.log(v[i] / v[i - 1]);
    var out = nulls(v.length);
    for (i = n; i < v.length; i++) {
      var s = 0, j;
      for (j = i - n + 1; j <= i; j++) s += r[j];
      var m = s / n, q = 0;
      for (j = i - n + 1; j <= i; j++) q += (r[j] - m) * (r[j] - m);
      out[i] = 100 * Math.sqrt(q / (n - 1)) * Math.sqrt(perYear || 252);
    }
    return out;
  }

  function bbPercent(v, n, k) {
    var b = bollinger(v, n, k), out = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(b.up[i]) && b.up[i] !== b.lo[i]) out[i] = (v[i] - b.lo[i]) / (b.up[i] - b.lo[i]);
    return out;
  }
  function bbWidth(v, n, k) {
    var b = bollinger(v, n, k), out = nulls(v.length);
    for (var i = 0; i < v.length; i++) if (ok(b.mid[i]) && b.mid[i]) out[i] = (b.up[i] - b.lo[i]) / b.mid[i];
    return out;
  }

  /* Least-squares line through values[from..to]; returns the two end values
     and the standard deviation of the residuals, for a regression channel. */
  function regression(v, from, to) {
    var n = to - from + 1;
    if (n < 2) return null;
    var sx = 0, sy = 0, sxx = 0, sxy = 0, i;
    for (i = 0; i < n; i++) { var y = v[from + i]; sx += i; sy += y; sxx += i * i; sxy += i * y; }
    var den = n * sxx - sx * sx;
    if (!den) return null;
    var m = (n * sxy - sx * sy) / den, b = (sy - m * sx) / n, q = 0;
    for (i = 0; i < n; i++) { var e = v[from + i] - (b + m * i); q += e * e; }
    return { start: b, end: b + m * (n - 1), slope: m, sd: Math.sqrt(q / n) };
  }

  /* Volume traded at each price between two bars, in `rows` equal price
     buckets. A bar's volume is spread evenly across the buckets its range
     touches, which is the usual approximation when there is no tick data. */
  function volumeProfile(h, l, c, o, vol, from, to, rows) {
    from = Math.max(0, from); to = Math.min(c.length - 1, to);
    if (to < from) return null;
    var hi = -Infinity, lo = Infinity, i;
    for (i = from; i <= to; i++) { if (h[i] > hi) hi = h[i]; if (l[i] < lo) lo = l[i]; }
    if (!(hi > lo)) return null;
    var step = (hi - lo) / rows, up = [], dn = [];
    for (i = 0; i < rows; i++) { up.push(0); dn.push(0); }
    for (i = from; i <= to; i++) {
      var a = Math.max(0, Math.min(rows - 1, Math.floor((l[i] - lo) / step)));
      var b = Math.max(0, Math.min(rows - 1, Math.floor((h[i] - lo) / step)));
      var share = (vol[i] || 0) / (b - a + 1);
      for (var k = a; k <= b; k++) { if (c[i] >= o[i]) up[k] += share; else dn[k] += share; }
    }
    var max = 0, poc = 0, total = 0;
    for (i = 0; i < rows; i++) {
      var t = up[i] + dn[i]; total += t;
      if (t > max) { max = t; poc = i; }
    }
    return { lo: lo, hi: hi, step: step, up: up, dn: dn, max: max, poc: poc, total: total };
  }

  /* ── candle transforms ─────────────────────────────────────────────────── */

  function heikinAshi(rows) {
    var out = [], po = null, pc = null;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i], c = (r.open + r.high + r.low + r.close) / 4;
      var o = po == null ? (r.open + r.close) / 2 : (po + pc) / 2;
      out.push({ time: r.time, open: o, high: Math.max(r.high, o, c), low: Math.min(r.low, o, c),
                 close: c, volume: r.volume });
      po = o; pc = c;
    }
    return out;
  }

  /* Fold candles into longer ones. `bucket(row)` names the longer bar a candle
     belongs to; consecutive candles with the same name are merged. The merged
     bar keeps the timestamp of its first candle. */
  function resample(rows, bucket) {
    var out = [], cur = null, key = null;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i], k = bucket(r, i);
      if (cur == null || k !== key) {
        key = k;
        cur = { time: r.time, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume || 0 };
        out.push(cur);
      } else {
        if (r.high > cur.high) cur.high = r.high;
        if (r.low < cur.low) cur.low = r.low;
        cur.close = r.close; cur.volume += r.volume || 0;
      }
    }
    return out;
  }

  /* Timestamps are exchange wall-clock seconds, so the calendar day is a
     plain division with no timezone arithmetic. */
  function dayKey(t) { return Math.floor(t / 86400); }
  function weekKey(t) { return Math.floor((dayKey(t) + 3) / 7); }      /* weeks start on Monday */
  function monthKey(t) { var d = new Date(t * 1000); return d.getUTCFullYear() * 12 + d.getUTCMonth(); }

  /* Merge `n` intraday candles at a time, never across a session boundary:
     the 15:15 bar must not be glued to the next morning's 09:15. */
  function resampleIntraday(rows, n) {
    var day = null, idx = 0;
    return resample(rows, function (r) {
      var d = dayKey(r.time);
      if (d !== day) { day = d; idx = 0; }
      return d + ":" + Math.floor((idx++) / n);
    });
  }
  function resampleMonthly(rows) { return resample(rows, function (r) { return monthKey(r.time); }); }

  /* ══════════════════════════════════════════════════════════════════════
     THE CATALOGUE
     One entry per indicator. The workspace reads nothing else to know what an
     indicator is called, what it can be tuned by, or how to draw it.

       pane   false: drawn over the candles. true: a panel of its own below.
       params the numbers a reader may change, with their sensible limits.
       out    one entry per plotted series. `s` is the style:
                line (default), hist (bars from zero), dots (no joining line),
                step. `ahead` shifts a series that many bars into the future.
       fill   pairs of outputs to shade between (overlays only).
       levels fixed reference lines in a pane (70 and 30 on an RSI).
       calc   (D, p) -> { key: array }. D carries o, h, l, c, v, t.
     ══════════════════════════════════════════════════════════════════════ */

  var GOLD = "#B08D2E", GREEN = "#1F5D45", RED = "#8E2F2A", BLUE = "#2E5E8E", INK = "#33333A",
      PURPLE = "#6B4E9B", TEAL = "#1E7B85", ORANGE = "#C0692B", MUTE = "#6E6E78", PINK = "#B0457A";

  var LEN = function (v, l) { return { k: "len", l: l || "Length", v: v, min: 1, max: 500 }; };
  var SRC = { k: "src", l: "Source", v: "close", opts: ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"] };

  function source(D, s) {
    if (s === "open") return D.o;
    if (s === "high") return D.h;
    if (s === "low") return D.l;
    var i, n = D.c.length, out = new Array(n);
    if (s === "hl2") { for (i = 0; i < n; i++) out[i] = (D.h[i] + D.l[i]) / 2; return out; }
    if (s === "hlc3") { for (i = 0; i < n; i++) out[i] = (D.h[i] + D.l[i] + D.c[i]) / 3; return out; }
    if (s === "ohlc4") { for (i = 0; i < n; i++) out[i] = (D.o[i] + D.h[i] + D.l[i] + D.c[i]) / 4; return out; }
    return D.c;
  }

  function oneMa(id, name, short, colour, fn) {
    return {
      id: id, name: name, short: short, cat: "Trend", pane: false,
      params: [LEN(20), SRC],
      out: [{ k: "ma", l: short, c: colour, w: 2 }],
      calc: function (D, p) { return { ma: fn(source(D, p.src), p.len, D) }; }
    };
  }

  var INDICATORS = [
    /* ── trend, over the candles ── */
    {
      id: "ema3", name: "EMA 20 / 50 / 200", short: "EMA", cat: "Trend", pane: false,
      params: [{ k: "a", l: "Fast", v: 20, min: 1, max: 500 }, { k: "b", l: "Medium", v: 50, min: 1, max: 500 },
               { k: "c", l: "Slow", v: 200, min: 1, max: 1000 }],
      out: [{ k: "a", l: "Fast", c: GOLD, w: 2 }, { k: "b", l: "Medium", c: INK, w: 1 }, { k: "c", l: "Slow", c: MUTE, w: 1 }],
      calc: function (D, p) { return { a: ema(D.c, p.a), b: ema(D.c, p.b), c: ema(D.c, p.c) }; }
    },
    oneMa("sma", "Simple moving average", "SMA", BLUE, function (s, n) { return sma(s, n); }),
    oneMa("ema", "Exponential moving average", "EMA", GOLD, function (s, n) { return ema(s, n); }),
    oneMa("wma", "Weighted moving average", "WMA", PURPLE, function (s, n) { return wma(s, n); }),
    oneMa("hma", "Hull moving average", "HMA", TEAL, function (s, n) { return hma(s, n); }),
    oneMa("vwma", "Volume weighted moving average", "VWMA", ORANGE, function (s, n, D) { return vwma(s, D.v, n); }),
    oneMa("dema", "Double exponential moving average", "DEMA", PINK, function (s, n) { return dema(s, n); }),
    oneMa("tema", "Triple exponential moving average", "TEMA", GREEN, function (s, n) { return tema(s, n); }),
    {
      id: "supertrend", name: "Supertrend", short: "Supertrend", cat: "Trend", pane: false,
      params: [LEN(10, "ATR length"), { k: "mult", l: "Multiplier", v: 3, min: 0.5, max: 20, step: 0.1 }],
      out: [{ k: "line", l: "Supertrend", c: GREEN, c2: RED, w: 2, by: "dir" }],
      calc: function (D, p) { return supertrend(D.h, D.l, D.c, p.len, p.mult); }
    },
    {
      id: "psar", name: "Parabolic SAR", short: "SAR", cat: "Trend", pane: false,
      params: [{ k: "step", l: "Start and step", v: 0.02, min: 0.001, max: 0.5, step: 0.001 },
               { k: "max", l: "Maximum", v: 0.2, min: 0.01, max: 1, step: 0.01 }],
      out: [{ k: "sar", l: "SAR", c: BLUE, w: 1, s: "dots" }],
      calc: function (D, p) { return psar(D.h, D.l, p.step, p.max); }
    },
    {
      id: "ichimoku", name: "Ichimoku cloud", short: "Ichimoku", cat: "Trend", pane: false,
      params: [{ k: "conv", l: "Conversion", v: 9, min: 1, max: 200 }, { k: "base", l: "Base", v: 26, min: 1, max: 300 },
               { k: "span", l: "Span B", v: 52, min: 1, max: 500 }, { k: "disp", l: "Displacement", v: 26, min: 1, max: 100 }],
      out: [{ k: "tenkan", l: "Conversion", c: BLUE, w: 1 }, { k: "kijun", l: "Base", c: RED, w: 1 },
            { k: "spanA", l: "Span A", c: GREEN, w: 1, ahead: "disp" }, { k: "spanB", l: "Span B", c: ORANGE, w: 1, ahead: "disp" },
            { k: "chikou", l: "Lagging", c: MUTE, w: 1 }],
      fill: [["spanA", "spanB"]],
      calc: function (D, p) { return ichimoku(D.h, D.l, D.c, p.conv, p.base, p.span, p.disp); }
    },
    {
      id: "alligator", name: "Williams Alligator", short: "Alligator", cat: "Trend", pane: false,
      params: [],
      out: [{ k: "jaw", l: "Jaw", c: BLUE, w: 1, ahead: 8 }, { k: "teeth", l: "Teeth", c: RED, w: 1, ahead: 5 },
            { k: "lips", l: "Lips", c: GREEN, w: 1, ahead: 3 }],
      calc: function (D) { return alligator(D.h, D.l); }
    },
    {
      id: "zigzag", name: "ZigZag", short: "ZigZag", cat: "Trend", pane: false,
      params: [{ k: "pct", l: "Reversal %", v: 5, min: 0.1, max: 50, step: 0.1 }],
      out: [{ k: "line", l: "ZigZag", c: PURPLE, w: 2 }],
      calc: function (D, p) { return { line: zigzag(D.h, D.l, p.pct).line }; }
    },
    {
      id: "pivots", name: "Pivot points (standard)", short: "Pivots", cat: "Trend", pane: false,
      params: [],
      out: [{ k: "p", l: "P", c: GOLD, w: 1, s: "step" }, { k: "r1", l: "R1", c: RED, w: 1, s: "step" },
            { k: "r2", l: "R2", c: RED, w: 1, s: "step" }, { k: "r3", l: "R3", c: RED, w: 1, s: "step" },
            { k: "s1", l: "S1", c: GREEN, w: 1, s: "step" }, { k: "s2", l: "S2", c: GREEN, w: 1, s: "step" },
            { k: "s3", l: "S3", c: GREEN, w: 1, s: "step" }],
      /* Daily pivots on intraday bars, monthly on daily bars, yearly beyond. */
      calc: function (D) {
        var per = D.barSec < 86400 ? dayKey : D.barSec < 7 * 86400 ? monthKey
          : function (t) { return new Date(t * 1000).getUTCFullYear(); };
        return pivots(D.h, D.l, D.c, function (i) { return per(D.t[i]); });
      }
    },

    /* ── volatility, over the candles ── */
    {
      id: "bb", name: "Bollinger Bands", short: "BB", cat: "Volatility", pane: false,
      params: [LEN(20), { k: "mult", l: "Std dev", v: 2, min: 0.1, max: 10, step: 0.1 }],
      out: [{ k: "mid", l: "Basis", c: ORANGE, w: 1 }, { k: "up", l: "Upper", c: BLUE, w: 1 }, { k: "lo", l: "Lower", c: BLUE, w: 1 }],
      fill: [["up", "lo"]],
      calc: function (D, p) { return bollinger(D.c, p.len, p.mult); }
    },
    {
      id: "keltner", name: "Keltner Channels", short: "KC", cat: "Volatility", pane: false,
      params: [LEN(20), { k: "mult", l: "Multiplier", v: 2, min: 0.1, max: 10, step: 0.1 }, { k: "atr", l: "ATR length", v: 10, min: 1, max: 200 }],
      out: [{ k: "mid", l: "Basis", c: TEAL, w: 1 }, { k: "up", l: "Upper", c: TEAL, w: 1 }, { k: "lo", l: "Lower", c: TEAL, w: 1 }],
      fill: [["up", "lo"]],
      calc: function (D, p) { return keltner(D.h, D.l, D.c, p.len, p.mult, p.atr); }
    },
    {
      id: "donchian", name: "Donchian Channels", short: "DC", cat: "Volatility", pane: false,
      params: [LEN(20)],
      out: [{ k: "up", l: "Upper", c: PURPLE, w: 1 }, { k: "lo", l: "Lower", c: PURPLE, w: 1 }, { k: "mid", l: "Middle", c: ORANGE, w: 1 }],
      fill: [["up", "lo"]],
      calc: function (D, p) { return donchian(D.h, D.l, p.len); }
    },
    {
      id: "envelope", name: "Envelope", short: "Env", cat: "Volatility", pane: false,
      params: [LEN(20), { k: "pct", l: "Percent", v: 5, min: 0.1, max: 50, step: 0.1 }],
      out: [{ k: "mid", l: "Basis", c: ORANGE, w: 1 }, { k: "up", l: "Upper", c: PINK, w: 1 }, { k: "lo", l: "Lower", c: PINK, w: 1 }],
      fill: [["up", "lo"]],
      calc: function (D, p) { return envelope(D.c, p.len, p.pct); }
    },

    /* ── volume ── */
    {
      id: "vwap", name: "VWAP (session)", short: "VWAP", cat: "Volume", pane: false,
      params: [],
      note: "Restarts every session, so it only means something on intraday bars.",
      out: [{ k: "vwap", l: "VWAP", c: BLUE, w: 2 }],
      calc: function (D) {
        if (D.barSec >= 86400) return { vwap: nulls(D.c.length) };
        return { vwap: vwap(D.h, D.l, D.c, D.v, function (i) { return dayKey(D.t[i]); }) };
      }
    },
    {
      id: "vol", name: "Volume", short: "Vol", cat: "Volume", pane: false, special: "volume",
      params: [{ k: "ma", l: "Average length (0 for none)", v: 20, min: 0, max: 200 }],
      out: [{ k: "vol", l: "Volume", c: GREEN, c2: RED, s: "hist" }, { k: "ma", l: "Average", c: ORANGE, w: 1 }],
      calc: function (D, p) { return { vol: D.v.slice(), ma: p.ma > 0 ? sma(D.v, p.ma) : nulls(D.v.length) }; }
    },
    {
      id: "obv", name: "On balance volume", short: "OBV", cat: "Volume", pane: true,
      params: [], out: [{ k: "obv", l: "OBV", c: BLUE, w: 2 }], fmt: "volume",
      calc: function (D) { return { obv: obv(D.c, D.v) }; }
    },
    {
      id: "mfi", name: "Money flow index", short: "MFI", cat: "Volume", pane: true,
      params: [LEN(14)], out: [{ k: "mfi", l: "MFI", c: PURPLE, w: 2 }], levels: [80, 20],
      calc: function (D, p) { return { mfi: mfi(D.h, D.l, D.c, D.v, p.len) }; }
    },
    {
      id: "cmf", name: "Chaikin money flow", short: "CMF", cat: "Volume", pane: true,
      params: [LEN(20)], out: [{ k: "cmf", l: "CMF", c: GREEN, w: 2 }], levels: [0],
      calc: function (D, p) { return { cmf: cmf(D.h, D.l, D.c, D.v, p.len) }; }
    },
    {
      id: "adl", name: "Accumulation / distribution", short: "A/D", cat: "Volume", pane: true,
      params: [], out: [{ k: "adl", l: "A/D", c: TEAL, w: 2 }], fmt: "volume",
      calc: function (D) { return { adl: adl(D.h, D.l, D.c, D.v) }; }
    },
    {
      id: "chaikin", name: "Chaikin oscillator", short: "Chaikin", cat: "Volume", pane: true,
      params: [{ k: "fast", l: "Fast", v: 3, min: 1, max: 100 }, { k: "slow", l: "Slow", v: 10, min: 2, max: 200 }],
      out: [{ k: "osc", l: "Chaikin", c: ORANGE, w: 2 }], levels: [0], fmt: "volume",
      calc: function (D, p) { return { osc: chaikinOsc(D.h, D.l, D.c, D.v, p.fast, p.slow) }; }
    },

    /* ── momentum, in panes ── */
    {
      id: "rsi", name: "Relative strength index", short: "RSI", cat: "Momentum", pane: true,
      params: [LEN(14), { k: "ma", l: "Smoothing (0 for none)", v: 0, min: 0, max: 200 }],
      out: [{ k: "rsi", l: "RSI", c: GOLD, w: 2 }, { k: "ma", l: "Average", c: BLUE, w: 1 }],
      levels: [70, 50, 30], band: [70, 30],
      calc: function (D, p) {
        var r = rsi(D.c, p.len);
        return { rsi: r, ma: p.ma > 0 ? sma(r, p.ma) : nulls(r.length) };
      }
    },
    {
      id: "macd", name: "MACD", short: "MACD", cat: "Momentum", pane: true,
      params: [{ k: "fast", l: "Fast", v: 12, min: 1, max: 200 }, { k: "slow", l: "Slow", v: 26, min: 2, max: 400 },
               { k: "sig", l: "Signal", v: 9, min: 1, max: 100 }],
      out: [{ k: "hist", l: "Histogram", c: GREEN, c2: RED, s: "hist" }, { k: "line", l: "MACD", c: BLUE, w: 2 },
            { k: "sig", l: "Signal", c: ORANGE, w: 1 }],
      levels: [0],
      calc: function (D, p) { return macd(D.c, p.fast, p.slow, p.sig); }
    },
    {
      id: "stoch", name: "Stochastic", short: "Stoch", cat: "Momentum", pane: true,
      params: [{ k: "k", l: "%K length", v: 14, min: 1, max: 200 }, { k: "smooth", l: "%K smoothing", v: 3, min: 1, max: 50 },
               { k: "d", l: "%D length", v: 3, min: 1, max: 50 }],
      out: [{ k: "k", l: "%K", c: BLUE, w: 2 }, { k: "d", l: "%D", c: ORANGE, w: 1 }],
      levels: [80, 20], band: [80, 20],
      calc: function (D, p) { return stoch(D.h, D.l, D.c, p.k, p.smooth, p.d); }
    },
    {
      id: "stochrsi", name: "Stochastic RSI", short: "StochRSI", cat: "Momentum", pane: true,
      params: [{ k: "rsi", l: "RSI length", v: 14, min: 2, max: 200 }, { k: "st", l: "Stochastic length", v: 14, min: 2, max: 200 },
               { k: "k", l: "%K", v: 3, min: 1, max: 50 }, { k: "d", l: "%D", v: 3, min: 1, max: 50 }],
      out: [{ k: "k", l: "%K", c: BLUE, w: 2 }, { k: "d", l: "%D", c: ORANGE, w: 1 }],
      levels: [80, 20], band: [80, 20],
      calc: function (D, p) { return stochRsi(D.c, p.rsi, p.st, p.k, p.d); }
    },
    {
      id: "adx", name: "Average directional index", short: "ADX", cat: "Trend", pane: true,
      params: [LEN(14)],
      out: [{ k: "adx", l: "ADX", c: GOLD, w: 2 }, { k: "pdi", l: "+DI", c: GREEN, w: 1 }, { k: "mdi", l: "-DI", c: RED, w: 1 }],
      levels: [25],
      calc: function (D, p) { return adx(D.h, D.l, D.c, p.len); }
    },
    {
      id: "cci", name: "Commodity channel index", short: "CCI", cat: "Momentum", pane: true,
      params: [LEN(20)], out: [{ k: "cci", l: "CCI", c: TEAL, w: 2 }], levels: [100, 0, -100], band: [100, -100],
      calc: function (D, p) { return { cci: cci(D.h, D.l, D.c, p.len) }; }
    },
    {
      id: "willr", name: "Williams %R", short: "%R", cat: "Momentum", pane: true,
      params: [LEN(14)], out: [{ k: "r", l: "%R", c: PURPLE, w: 2 }], levels: [-20, -80], band: [-20, -80],
      calc: function (D, p) { return { r: willr(D.h, D.l, D.c, p.len) }; }
    },
    {
      id: "roc", name: "Rate of change", short: "ROC", cat: "Momentum", pane: true,
      params: [LEN(12)], out: [{ k: "roc", l: "ROC", c: BLUE, w: 2 }], levels: [0],
      calc: function (D, p) { return { roc: roc(D.c, p.len) }; }
    },
    {
      id: "mom", name: "Momentum", short: "Mom", cat: "Momentum", pane: true,
      params: [LEN(10)], out: [{ k: "mom", l: "Momentum", c: ORANGE, w: 2 }], levels: [0],
      calc: function (D, p) { return { mom: momentum(D.c, p.len) }; }
    },
    {
      id: "ao", name: "Awesome oscillator", short: "AO", cat: "Momentum", pane: true,
      params: [], out: [{ k: "ao", l: "AO", c: GREEN, c2: RED, s: "hist", rising: true }], levels: [0],
      calc: function (D) { return { ao: awesome(D.h, D.l) }; }
    },
    {
      id: "aroon", name: "Aroon", short: "Aroon", cat: "Trend", pane: true,
      params: [LEN(14)], out: [{ k: "up", l: "Up", c: GREEN, w: 2 }, { k: "dn", l: "Down", c: RED, w: 2 }],
      levels: [70, 30],
      calc: function (D, p) { return aroon(D.h, D.l, p.len); }
    },
    {
      id: "trix", name: "TRIX", short: "TRIX", cat: "Momentum", pane: true,
      params: [LEN(18)], out: [{ k: "trix", l: "TRIX", c: PINK, w: 2 }], levels: [0],
      calc: function (D, p) { return { trix: trix(D.c, p.len) }; }
    },
    {
      id: "tsi", name: "True strength index", short: "TSI", cat: "Momentum", pane: true,
      params: [{ k: "long", l: "Long", v: 25, min: 2, max: 200 }, { k: "short", l: "Short", v: 13, min: 1, max: 100 },
               { k: "sig", l: "Signal", v: 13, min: 1, max: 100 }],
      out: [{ k: "tsi", l: "TSI", c: BLUE, w: 2 }, { k: "sig", l: "Signal", c: ORANGE, w: 1 }], levels: [0],
      calc: function (D, p) { var t = tsi(D.c, p.long, p.short); return { tsi: t, sig: ema(t, p.sig) }; }
    },
    {
      id: "cmo", name: "Chande momentum oscillator", short: "CMO", cat: "Momentum", pane: true,
      params: [LEN(9)], out: [{ k: "cmo", l: "CMO", c: TEAL, w: 2 }], levels: [50, 0, -50],
      calc: function (D, p) { return { cmo: cmo(D.c, p.len) }; }
    },
    {
      id: "uo", name: "Ultimate oscillator", short: "UO", cat: "Momentum", pane: true,
      params: [{ k: "a", l: "Fast", v: 7, min: 1, max: 100 }, { k: "b", l: "Middle", v: 14, min: 2, max: 200 },
               { k: "c", l: "Slow", v: 28, min: 3, max: 400 }],
      out: [{ k: "uo", l: "UO", c: GOLD, w: 2 }], levels: [70, 30],
      calc: function (D, p) { return { uo: ultimate(D.h, D.l, D.c, p.a, p.b, p.c) }; }
    },

    /* ── volatility, in panes ── */
    {
      id: "atr", name: "Average true range", short: "ATR", cat: "Volatility", pane: true,
      params: [LEN(14)], out: [{ k: "atr", l: "ATR", c: RED, w: 2 }],
      calc: function (D, p) { return { atr: atr(D.h, D.l, D.c, p.len) }; }
    },
    {
      id: "bbp", name: "Bollinger %B", short: "%B", cat: "Volatility", pane: true,
      params: [LEN(20), { k: "mult", l: "Std dev", v: 2, min: 0.1, max: 10, step: 0.1 }],
      out: [{ k: "b", l: "%B", c: BLUE, w: 2 }], levels: [1, 0.5, 0], band: [1, 0],
      calc: function (D, p) { return { b: bbPercent(D.c, p.len, p.mult) }; }
    },
    {
      id: "bbw", name: "Bollinger band width", short: "BBW", cat: "Volatility", pane: true,
      params: [LEN(20), { k: "mult", l: "Std dev", v: 2, min: 0.1, max: 10, step: 0.1 }],
      out: [{ k: "w", l: "Width", c: ORANGE, w: 2 }], prec: 4,
      calc: function (D, p) { return { w: bbWidth(D.c, p.len, p.mult) }; }
    },
    {
      id: "hv", name: "Historical volatility", short: "HV", cat: "Volatility", pane: true,
      params: [LEN(20)], out: [{ k: "hv", l: "HV %", c: PURPLE, w: 2 }],
      calc: function (D, p) {
        var perYear = D.barSec >= 28 * 86400 ? 12 : D.barSec >= 7 * 86400 ? 52 : D.barSec >= 86400 ? 252
          : Math.round(252 * 22500 / Math.max(60, D.barSec));
        return { hv: histVol(D.c, p.len, perYear) };
      }
    }
  ];

  var BY_ID = {};
  INDICATORS.forEach(function (d) { BY_ID[d.id] = d; });

  /* Columns of numbers from candle rows, which is what every calc() takes. */
  function columns(rows) {
    var n = rows.length, D = { o: new Array(n), h: new Array(n), l: new Array(n), c: new Array(n),
                               v: new Array(n), t: new Array(n), barSec: 86400 };
    for (var i = 0; i < n; i++) {
      var r = rows[i];
      D.o[i] = r.open; D.h[i] = r.high; D.l[i] = r.low; D.c[i] = r.close; D.v[i] = r.volume || 0; D.t[i] = r.time;
    }
    var diffs = [];
    for (i = 1; i < Math.min(n, 80); i++) diffs.push(D.t[i] - D.t[i - 1]);
    diffs.sort(function (a, b) { return a - b; });
    D.barSec = diffs[Math.floor(diffs.length / 2)] || 86400;
    return D;
  }

  function defaults(def) {
    var p = {};
    (def.params || []).forEach(function (q) { p[q.k] = q.v; });
    return p;
  }

  return {
    sma: sma, ema: ema, rma: rma, wma: wma, hma: hma, vwma: vwma, dema: dema, tema: tema, ma: ma,
    highest: highest, lowest: lowest, stdev: stdev, trueRange: trueRange, atr: atr,
    bollinger: bollinger, keltner: keltner, donchian: donchian, envelope: envelope,
    supertrend: supertrend, psar: psar, ichimoku: ichimoku, vwap: vwap, anchoredVwap: anchoredVwap,
    alligator: alligator, zigzag: zigzag, pivots: pivots,
    rsi: rsi, macd: macd, stoch: stoch, stochRsi: stochRsi, adx: adx, cci: cci, willr: willr,
    mfi: mfi, obv: obv, roc: roc, momentum: momentum, adl: adl, cmf: cmf, chaikinOsc: chaikinOsc,
    awesome: awesome, aroon: aroon, trix: trix, tsi: tsi, cmo: cmo, ultimate: ultimate,
    histVol: histVol, bbPercent: bbPercent, bbWidth: bbWidth,
    regression: regression, volumeProfile: volumeProfile,
    heikinAshi: heikinAshi, resample: resample, resampleIntraday: resampleIntraday,
    resampleMonthly: resampleMonthly, dayKey: dayKey, weekKey: weekKey, monthKey: monthKey,
    columns: columns, defaults: defaults,
    INDICATORS: INDICATORS, indicator: function (id) { return BY_ID[id] || null; }
  };
});
