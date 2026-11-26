/* ═══════════════════════════════════════════════════════════════════════════
   Money flow — where institutional money is moving.

   One page from one payload (/moneyflow), top to bottom:

     the market   FII and DII in the cash market: daily bars, and under them
                  the running total. Two panels on one time axis, never two
                  scales on one plot: a line drawn against a second axis lines
                  up with the bars wherever the scales happen to put it.
     the heatmap  FPI equity flow, sector by fortnight, twelve fortnights.
     rotation     each sector's eight-week trail against the Nifty 50, which
                  can be played.
     the ranking  one card per sector with its Money Flow Score and the three
                  parts it is made of. A card opens the stocks inside it.

   COLOUR DOES ONE JOB EACH
     green / red      money in, money out. Everywhere: heatmap cells, the
                      dots on the rotation chart, the flow bars.
     blue / orange    who: FII, DII. Only in the market chart.
     silver           everything that is a level, not a direction (a score).
   Both pairs were run through a colour-blindness check against this page's
   surface. Direction is never colour alone: a figure carries its sign, an
   inflow dot is solid and an outflow dot hollow, and every trend has a word.

   The rendering is pure (data in, markup out) so the node test can read it;
   the wiring at the bottom only runs in a browser. Every string from the
   server goes through esc() before it reaches markup.
   ═══════════════════════════════════════════════════════════════════════════ */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AltahaMoneyFlow = api;
  if (typeof document !== 'undefined') api.wire();
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  /* ── small readers ────────────────────────────────────────────────────── */
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v) {
    return v !== null && v !== undefined && v !== '' && isFinite(Number(v)) ? Number(v) : null;
  }
  var MINUS = '−', DASH = '—';
  function grouped(n, d) {
    return Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  /* Rupees crore. `signed` puts a plus on an inflow: on this page the sign is
     the point, so a positive figure says so. */
  function cr(v, signed) {
    var n = num(v);
    if (n === null) return DASH;
    var sign = n < 0 ? MINUS : (signed && n > 0 ? '+' : '');
    return sign + '₹' + grouped(n) + ' cr';
  }
  /* The same figure with no room: 43,102 -> +43.1k, 612 -> +612. */
  function compact(v) {
    var n = num(v);
    if (n === null) return '';
    var a = Math.abs(n), sign = n < 0 ? MINUS : n > 0 ? '+' : '';
    if (a >= 100000) return sign + (a / 100000).toFixed(a >= 1000000 ? 0 : 1) + 'L';
    if (a >= 10000) return sign + (a / 1000).toFixed(0) + 'k';
    if (a >= 1000) return sign + (a / 1000).toFixed(1) + 'k';
    return sign + a.toFixed(0);
  }
  function signed(v, d, unit) {
    var n = num(v);
    if (n === null) return DASH;
    var s = Math.abs(n).toFixed(d == null ? 1 : d);
    return (n > 0 ? '+' : n < 0 ? MINUS : '') + s + (unit || '');
  }
  function pct(v, d) { var n = num(v); return n === null ? DASH : n.toFixed(d == null ? 0 : d) + '%'; }
  function times(v) { var n = num(v); return n === null ? DASH : (n >= 10 ? n.toFixed(0) : n.toFixed(1)) + '×'; }
  function way(v) { var n = num(v); return n === null || n === 0 ? 'flat' : n > 0 ? 'in' : 'out'; }

  var DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function parts(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
  }
  function day(iso, long) {
    var p = parts(iso);
    if (!p) return String(iso || '');
    var dow = DOW[new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay()];
    return long ? dow + ' ' + p.d + ' ' + MON[p.m - 1] + ' ' + p.y : p.d + ' ' + MON[p.m - 1];
  }
  /* A fortnight: "1–15 Nov 2026". NSDL's are always inside one month. */
  function period(start, end, year) {
    var a = parts(start), b = parts(end);
    if (!b) return '';
    var head = a && a.m === b.m ? a.d + '–' + b.d : (a ? a.d + ' ' + MON[a.m - 1] + ' – ' + b.d : 'to ' + b.d);
    return head + ' ' + MON[b.m - 1] + (year ? ' ' + b.y : '');
  }

  /* Round numbers for an axis: about `count` of them covering min..max. */
  function niceTicks(min, max, count) {
    if (!(max > min)) { max = min + 1; }
    var raw = (max - min) / Math.max(1, count || 4);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    var step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
    for (var v = lo; v <= hi + step / 2; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : +v.toFixed(10));
    return out;
  }
  function axisLabel(v) {
    var a = Math.abs(v), s = v < 0 ? MINUS : '';
    return a >= 1000 ? s + (a / 1000).toFixed(a % 1000 ? 1 : 0) + 'k' : s + String(+a.toFixed(2));
  }

  /* ── words ────────────────────────────────────────────────────────────── */
  var TREND_WORD = {
    'inflow|accelerating': 'Buying more', 'inflow|decelerating': 'Buying less',
    'inflow|reversing': 'Turned to buying', 'inflow|steady': 'Buying',
    'outflow|accelerating': 'Selling more', 'outflow|decelerating': 'Selling less',
    'outflow|reversing': 'Turned to selling', 'outflow|steady': 'Selling',
    'flat|steady': 'No net flow'
  };
  function trendWord(f) {
    if (!f) return 'No FPI data';
    return TREND_WORD[f.direction + '|' + f.trend] || TREND_WORD[f.direction + '|steady'] || 'No net flow';
  }
  /* An arrow whose angle is the trend: straight up or down when the flow is
     growing, a shallower slope when it is fading, a turn when it reversed. */
  function trendArrow(f) {
    var dir = f ? f.direction : 'flat', t = f ? f.trend : 'steady';
    var cls = dir === 'inflow' ? 'in' : dir === 'outflow' ? 'out' : 'flat';
    var d;
    if (dir === 'flat') d = 'M4 12h16M15 7l5 5-5 5';
    else if (t === 'reversing') d = dir === 'inflow' ? 'M5 4v9a5 5 0 0 0 10 0V5M10.5 9.5 15 5l4.5 4.5' : 'M5 20v-9a5 5 0 0 1 10 0v8M10.5 14.5 15 19l4.5-4.5';
    else if (t === 'decelerating') d = dir === 'inflow' ? 'M5 17 19 8M11 7h8v8' : 'M5 7l14 9M11 17h8V9';
    else d = dir === 'inflow' ? 'M12 20V4M5 11l7-7 7 7' : 'M12 4v16M5 13l7 7 7-7';
    return '<svg class="mf-arrow ' + cls + '" viewBox="0 0 24 24" aria-hidden="true"><path d="' + d + '"/></svg>';
  }
  var QUAD_NOTE = {
    Leading: 'Ahead of the Nifty 50 and still gaining', Weakening: 'Ahead of the Nifty 50, losing pace',
    Lagging: 'Behind the Nifty 50 and still losing', Improving: 'Behind the Nifty 50, closing the gap'
  };
  function quadChip(q) {
    return q ? '<span class="mf-quad q-' + esc(q.toLowerCase()) + '" title="' + esc(QUAD_NOTE[q] || '') + '"><i aria-hidden="true"></i>' + esc(q) + '</span>'
             : '<span class="mf-quad q-none">Not placed</span>';
  }

  /* ════════════════════════════════════════════════════════════════════════
     THE MARKET: FII and DII
     ════════════════════════════════════════════════════════════════════════ */
  /* A chart is drawn at the size it will be seen. Scaling a 1000-unit drawing
     down to a phone turns an 11px axis label into a 4px one, so a narrow
     screen gets its own, smaller drawing with the same text size instead. */
  var HERO_WIDE = { W: 1000, H: 476, L: 54, R: 16, aTop: 26, aBot: 250, bTop: 308, bBot: 432, labels: 6 };
  var HERO_NARROW = { W: 380, H: 452, L: 40, R: 8, aTop: 26, aBot: 222, bTop: 280, bBot: 408, labels: 4 };
  var RRG_WIDE = { W: 720, H: 610, L: 50, R: 20, T: 22, B: 44 };
  var RRG_NARROW = { W: 380, H: 470, L: 34, R: 10, T: 16, B: 40 };
  var FN_WIDE = { W: 640, H: 150, L: 46, R: 18, mid: 70, half: 56, labels: 6 };
  var FN_NARROW = { W: 360, H: 170, L: 40, R: 10, mid: 78, half: 62, labels: 4 };
  var HERO = {}, RRG = {}, FN = {}, narrow = false;
  function setNarrow(flag) {
    narrow = !!flag;
    var k;
    for (k in HERO_WIDE) HERO[k] = (narrow ? HERO_NARROW : HERO_WIDE)[k];
    for (k in RRG_WIDE) RRG[k] = (narrow ? RRG_NARROW : RRG_WIDE)[k];
    for (k in FN_WIDE) FN[k] = (narrow ? FN_NARROW : FN_WIDE)[k];
  }
  setNarrow(false);

  function heroGeometry(days) {
    var g = HERO, n = days.length, plotW = g.W - g.L - g.R, slot = plotW / Math.max(1, n);
    var bw = Math.max(2, Math.min(12, (slot - 5) / 2));
    var vals = [], cums = [];
    days.forEach(function (d) {
      [d.fii, d.dii].forEach(function (v) { if (num(v) !== null) vals.push(v); });
      [d.fii_cum, d.dii_cum].forEach(function (v) { if (num(v) !== null) cums.push(v); });
    });
    /* The scale runs from the data's own low to its own high, zero always
       inside it, with a little air; the ticks are the round numbers that
       fall within. Stretching to the next round number left a third of the
       panel empty. */
    function scale(list, top, bot) {
      var lo = Math.min.apply(null, list.concat([0])), hi = Math.max.apply(null, list.concat([0]));
      if (hi === lo) hi = lo + 1;
      var pad = (hi - lo) * 0.07;
      lo = lo < 0 ? lo - pad : lo; hi = hi > 0 ? hi + pad : hi;
      var ticks = niceTicks(lo, hi, 4).filter(function (t) { return t >= lo && t <= hi; });
      return { ticks: ticks, lo: lo, hi: hi, y: function (v) { return bot - (v - lo) / (hi - lo) * (bot - top); } };
    }
    var A = scale(vals, g.aTop, g.aBot), B = scale(cums, g.bTop, g.bBot);
    var x = function (i) { return g.L + slot * i + slot / 2; };
    return { n: n, slot: slot, bw: bw, A: A, B: B, x: x };
  }

  /* A bar with its data end rounded and its baseline end square. */
  function barPath(x, w, y0, y1) {
    var h = Math.abs(y1 - y0), r = +Math.min(4, w / 2, h).toFixed(2);
    if (h < 0.5) return '';
    if (y1 < y0) {
      return 'M' + x + ' ' + y0 + 'V' + (y1 + r) + 'a' + r + ' ' + r + ' 0 0 1 ' + r + ' ' + (-r) +
        'h' + (w - 2 * r) + 'a' + r + ' ' + r + ' 0 0 1 ' + r + ' ' + r + 'V' + y0 + 'Z';
    }
    return 'M' + x + ' ' + y0 + 'V' + (y1 - r) + 'a' + r + ' ' + r + ' 0 0 0 ' + r + ' ' + r +
      'h' + (w - 2 * r) + 'a' + r + ' ' + r + ' 0 0 0 ' + r + ' ' + (-r) + 'V' + y0 + 'Z';
  }

  function heroSvg(days) {
    var g = HERO, G = heroGeometry(days), o = '', i;
    var f1 = function (v) { return v.toFixed(1); };
    function grid(S, top, bot, unit) {
      var s = '';
      S.ticks.forEach(function (t) {
        var y = S.y(t);
        s += '<line class="' + (t === 0 ? 'mf-zero' : 'mf-grid') + '" x1="' + g.L + '" x2="' + (g.W - g.R) + '" y1="' + f1(y) + '" y2="' + f1(y) + '"/>' +
          '<text class="mf-tick" x="' + (g.L - 8) + '" y="' + f1(y + 3.5) + '" text-anchor="end">' + esc(axisLabel(t)) + '</text>';
      });
      return s + '<text class="mf-axis" x="' + g.L + '" y="' + (top - 12) + '">' + unit + '</text>';
    }
    o += grid(G.A, g.aTop, g.aBot, 'Net bought or sold each session, ₹ cr');
    o += grid(G.B, g.bTop, g.bBot, 'Running total since ' + esc(day(days[0].date)) + ', ₹ cr');
    var zero = G.A.y(0);
    for (i = 0; i < G.n; i++) {
      var d = days[i], cx = G.x(i);
      ['fii', 'dii'].forEach(function (k, j) {
        var v = num(d[k]);
        if (v === null || v === 0) return;
        var x = j === 0 ? cx - 1 - G.bw : cx + 1;
        o += '<path class="mf-bar ' + k + (v < 0 ? ' neg' : '') + '" style="--i:' + i + '" d="' + barPath(f1(x) * 1, +G.bw.toFixed(1), +zero.toFixed(1), +G.A.y(v).toFixed(1)) + '"/>';
      });
    }
    ['fii', 'dii'].forEach(function (k) {
      var path = '';
      days.forEach(function (d, j) {
        var v = num(d[k + '_cum']);
        if (v !== null) path += (path ? 'L' : 'M') + f1(G.x(j)) + ' ' + f1(G.B.y(v));
      });
      var last = days[G.n - 1], lv = num(last[k + '_cum']);
      o += '<path class="mf-line ' + k + '" pathLength="1" d="' + path + '"/>';
      if (lv !== null) o += '<circle class="mf-end ' + k + '" cx="' + f1(G.x(G.n - 1)) + '" cy="' + f1(G.B.y(lv)) + '" r="4.5"/>';
    });
    /* A handful of dates along the bottom, the last one always. */
    var every = Math.max(1, Math.ceil(G.n / g.labels));
    for (i = G.n - 1; i >= 0; i -= every) {
      o += '<text class="mf-tick" x="' + f1(G.x(i)) + '" y="' + (g.bBot + 22) + '" text-anchor="middle">' + esc(day(days[i].date)) + '</text>';
    }
    o += '<line class="mf-cross" x1="0" x2="0" y1="' + g.aTop + '" y2="' + g.bBot + '" style="display:none"/>';
    return '<svg class="mf-hero-svg" viewBox="0 0 ' + g.W + ' ' + g.H + '" role="img" tabindex="0" aria-label="FII and DII net flows by session, with running totals. The table below carries every figure.">' + o + '</svg>';
  }

  function flowTable(days) {
    return '<details class="mf-table"><summary>Every session as a table</summary><div class="mf-scroll"><table><thead><tr><th>Session</th><th>FII net</th><th>DII net</th><th>FII running</th><th>DII running</th></tr></thead><tbody>' +
      days.slice().reverse().map(function (d) {
        return '<tr><th>' + esc(day(d.date, true)) + '</th><td>' + esc(cr(d.fii, true)) + '</td><td>' + esc(cr(d.dii, true)) +
          '</td><td>' + esc(cr(d.fii_cum, true)) + '</td><td>' + esc(cr(d.dii_cum, true)) + '</td></tr>';
      }).join('') + '</tbody></table></div></details>';
  }

  /* With under five sessions on record a chart would be one pair of bars and
     a "running total" of nothing. The figures are the honest form. */
  function heroFigures(m) {
    var l = m.latest || {};
    function one(k, name) {
      return '<div class="mf-fig ' + k + '"><span class="mf-key ' + k + '" aria-hidden="true"></span><div><div class="k">' + name + ', ' + esc(day(l.date, true)) + '</div>' +
        '<div class="v">' + esc(cr(l[k], true)) + '</div><div class="n">Bought ' + esc(cr(l[k + '_buy'])) + ' · sold ' + esc(cr(l[k + '_sell'])) + '</div></div></div>';
    }
    return '<div class="mf-figs">' + one('fii', 'FII') + one('dii', 'DII') + '</div>';
  }

  function hero(m, range) {
    if (!m || !m.available) {
      return '<section class="mf-sec mf-hero"><div class="mf-head"><h3>FII and DII, cash market</h3></div>' +
        '<p class="mf-empty">' + esc((m && m.message) || 'No session has been recorded yet.') + '</p></section>';
    }
    var all = m.days || [], days = all.slice(-range), few = all.length < 5;
    var ranges = [20, 60].filter(function (r) { return all.length > 20 || r === 20; });
    return '<section class="mf-sec mf-hero"><div class="mf-head"><div><h3>FII and DII, cash market</h3>' +
      '<p>' + esc(m.note || '') + '</p></div>' +
      (few ? '' : '<div class="mf-tools"><span class="mf-legend"><span><i class="mf-key fii"></i>FII</span><span><i class="mf-key dii"></i>DII</span></span>' +
        (ranges.length > 1 ? '<div class="mf-seg" role="group" aria-label="How many sessions">' + ranges.map(function (r) {
          return '<button type="button" data-range="' + r + '"' + (r === range ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + '>' + r + ' sessions</button>';
        }).join('') + '</div>' : '') + '</div>') + '</div>' +
      (few ? heroFigures(m) : '<div class="mf-plot" data-plot="hero">' + heroSvg(days) + '</div>') +
      (few ? '' : flowTable(days)) + '</section>';
  }

  /* ════════════════════════════════════════════════════════════════════════
     THE HEATMAP: sector by fortnight
     ════════════════════════════════════════════════════════════════════════ */
  /* The value a cell is shaded by, and where the scale tops out. The 90th
     percentile, not the maximum: one extraordinary fortnight would otherwise
     wash every other cell to grey. */
  function heatScale(rows, key) {
    var a = [];
    rows.forEach(function (r) { (r.cells || []).forEach(function (c) { var v = num(c[key]); if (v !== null) a.push(Math.abs(v)); }); });
    if (!a.length) return 1;
    a.sort(function (x, y) { return x - y; });
    return a[Math.min(a.length - 1, Math.floor(a.length * 0.9))] || a[a.length - 1] || 1;
  }
  function heatStep(v, max) {
    var n = num(v);
    if (n === null) return 'na';
    var s = Math.abs(n) / (max || 1);
    var k = s < 0.06 ? 0 : s < 0.3 ? 1 : s < 0.6 ? 2 : s < 0.9 ? 3 : 4;
    return k === 0 ? 'z' : (n > 0 ? 'in' : 'out') + k;
  }

  function heatmap(h, mode, latest) {
    var rows = (h && h.rows) || [], periods = (h && h.periods) || [];
    if (!rows.length || !periods.length) {
      return '<section class="mf-sec mf-heat"><div class="mf-head"><h3>FPI flow by sector</h3></div>' +
        '<p class="mf-empty">No NSDL fortnight is stored yet. The backfill reads two years of them.</p></section>';
    }
    var key = mode === 'cr' ? 'net_cr' : 'pct', max = heatScale(rows, key);
    var head = periods.map(function (p) {
      var b = parts(p.end), a = parts(p.start);
      return '<th scope="col" title="' + esc(period(p.start, p.end, true)) + '"><span>' + (a ? a.d : '') + '–' + (b ? b.d : '') + '</span><small>' + (b ? MON[b.m - 1] : '') + '</small></th>';
    }).join('');
    var body = rows.map(function (r) {
      return '<tr><th scope="row"><button type="button" class="mf-rowbtn" data-sector="' + esc(r.slug) + '">' + esc(r.short) + '</button></th>' +
        r.cells.map(function (c, i) {
          var p = periods[i];
          return '<td class="mf-cell ' + heatStep(c[key], max) + '" style="--c:' + i + '" data-tip="cell" data-sector="' + esc(r.short) + '" data-period="' + esc(period(p.start, p.end, true)) +
            '" data-cr="' + esc(c.net_cr) + '" data-pct="' + esc(c.pct) + '">' + esc(compact(c.net_cr)) + '</td>';
        }).join('') +
        '<td class="mf-sum"><b>' + esc(cr(r.sum3_cr, true)) + '</b></td>' +
        '<td class="mf-trend">' + trendArrow(r) + '<span>' + esc(trendWord(r)) + '</span></td></tr>';
    }).join('');
    var tmax = Math.max.apply(null, (h.totals || []).map(function (t) { return Math.abs(num(t) || 0); }).concat([1]));
    var foot = '<tr class="mf-total"><th scope="row">All sectors</th>' + (h.totals || []).map(function (t, i) {
      return '<td class="mf-cell ' + heatStep(t, tmax * 1.1) + '" style="--c:' + i + '">' + esc(compact(t)) + '</td>';
    }).join('') + '<td></td><td></td></tr>';
    var scale = ['out4', 'out3', 'out2', 'out1', 'z', 'in1', 'in2', 'in3', 'in4'].map(function (s) { return '<i class="mf-cell ' + s + '"></i>'; }).join('');
    return '<section class="mf-sec mf-heat"><div class="mf-head"><div><h3>FPI flow by sector, last ' + periods.length + ' fortnights</h3>' +
      '<p>Equity, net, in ₹ crore. Each cell is one sector in one fortnight' + (latest ? '; the newest is ' + esc(period(latest.start, latest.end, true)) : '') + '. NSDL publishes about a week after a fortnight ends.</p></div>' +
      '<div class="mf-tools"><div class="mf-seg" role="group" aria-label="What the shading measures">' +
        '<button type="button" data-heat="pct"' + (mode !== 'cr' ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + ' title="Flow as a share of what FPIs hold in the sector">Share of holdings</button>' +
        '<button type="button" data-heat="cr"' + (mode === 'cr' ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + '>Rupees</button></div></div></div>' +
      '<div class="mf-scroll"><table class="mf-heat-t"><thead><tr><th scope="col">Sector</th>' + head +
      '<th scope="col" class="mf-sum">Last 3</th><th scope="col">Trend</th></tr></thead><tbody>' + body + foot + '</tbody></table></div>' +
      '<div class="mf-scale"><span>Sold</span><span class="mf-ramp" aria-hidden="true">' + scale + '</span><span>Bought</span>' +
      '<em>Shaded by ' + (mode === 'cr' ? 'rupees' : 'flow as a share of what FPIs hold in that sector, so a small sector is not drowned by Financials') + '. The figure in the cell is always ₹ crore.</em></div></section>';
  }

  /* ════════════════════════════════════════════════════════════════════════
     ROTATION
     ════════════════════════════════════════════════════════════════════════ */

  /* Where everything goes, in pixels: the scale, and each series' position
     in each week (null in a week it has no reading for). Pure, so the test
     can check that 100/100 is the centre and that up means gaining. */
  function rrgGeometry(rrg, opts) {
    var g = RRG, weeks = (rrg && rrg.weeks) || [], showThemes = !!(opts && opts.themes);
    var series = ((rrg && rrg.series) || []).filter(function (s) { return showThemes || s.kind !== 'theme'; });
    /* Each axis runs over what the trails cover, padded, with 100 kept at
       least a fifth of the way in from either end: the centre line is the
       index, and a chart that pushed it to the edge would hide which side of
       it a sector is on. */
    function extent(key) {
      var lo = 100, hi = 100;
      series.forEach(function (s) { (s.points || []).forEach(function (p) { lo = Math.min(lo, p[key]); hi = Math.max(hi, p[key]); }); });
      var pad = Math.max(0.6, (hi - lo) * 0.1);
      lo -= pad; hi += pad;
      var span = hi - lo;
      if (100 - lo < 0.2 * span) lo = 100 - 0.25 * (hi - 100);
      if (hi - 100 < 0.2 * span) hi = 100 + 0.25 * (100 - lo);
      return [lo, hi];
    }
    var ex = extent('ratio'), ey = extent('momentum');
    var X = function (v) { return g.L + (v - ex[0]) / (ex[1] - ex[0]) * (g.W - g.L - g.R); };
    var Y = function (v) { return g.H - g.B - (v - ey[0]) / (ey[1] - ey[0]) * (g.H - g.T - g.B); };
    var out = series.map(function (s) {
      var by = {};
      (s.points || []).forEach(function (p) { by[p.week] = p; });
      return {
        s: s, pts: weeks.map(function (w) { return by[w] ? { x: X(by[w].ratio), y: Y(by[w].momentum), p: by[w] } : null; })
      };
    });
    return { weeks: weeks, dates: (rrg && rrg.week_dates) || weeks, series: out, X: X, Y: Y, ex: ex, ey: ey, cx: X(100), cy: Y(100) };
  }

  /* A series' position at a fractional week t: between two readings it is on
     the straight line joining them. */
  function rrgAt(pts, t) {
    var first = -1, i;
    for (i = 0; i < pts.length; i++) if (pts[i]) { first = i; break; }
    if (first < 0 || t < first) return null;
    var lo = Math.min(pts.length - 1, Math.floor(t)), hi = Math.min(pts.length - 1, lo + 1);
    while (lo > first && !pts[lo]) lo--;
    if (!pts[lo]) return null;
    if (!pts[hi] || hi === lo) return { x: pts[lo].x, y: pts[lo].y, i: lo };
    var f = Math.max(0, Math.min(1, t - lo));
    return { x: pts[lo].x + (pts[hi].x - pts[lo].x) * f, y: pts[lo].y + (pts[hi].y - pts[lo].y) * f, i: lo };
  }

  /* Labels beside the final positions. Each tries right, left, above, below
     and takes the first place that overlaps no label already set; one that
     fits nowhere is left for the hover to name. */
  function rrgLabels(geo) {
    var g = RRG, placed = [], last = geo.weeks.length - 1;
    var heads = geo.series.map(function (e) { return rrgAt(e.pts, last); });
    heads.forEach(function (h) { if (h) placed.push({ x0: h.x - 8, x1: h.x + 8, y0: h.y - 8, y1: h.y + 8 }); });
    var order = geo.series.map(function (e, i) { return i; }).sort(function (a, b) {
      return (num(geo.series[b].s.score) || 0) - (num(geo.series[a].s.score) || 0);
    });
    var labels = {};
    order.forEach(function (i) {
      var h = heads[i], name = geo.series[i].s.name;
      if (!h) return;
      var w = name.length * 6.1 + 4, tries = [
        { dx: 11, dy: 4, a: 'start', x0: h.x + 10, x1: h.x + 11 + w, y0: h.y - 8, y1: h.y + 7 },
        { dx: -11, dy: 4, a: 'end', x0: h.x - 11 - w, x1: h.x - 10, y0: h.y - 8, y1: h.y + 7 },
        { dx: 0, dy: -11, a: 'middle', x0: h.x - w / 2, x1: h.x + w / 2, y0: h.y - 24, y1: h.y - 9 },
        { dx: 0, dy: 20, a: 'middle', x0: h.x - w / 2, x1: h.x + w / 2, y0: h.y + 9, y1: h.y + 24 }
      ];
      for (var k = 0; k < tries.length; k++) {
        var t = tries[k];
        if (t.x0 < g.L || t.x1 > g.W - g.R || t.y0 < g.T || t.y1 > g.H - g.B) continue;
        var hit = placed.some(function (b) { return t.x0 < b.x1 && t.x1 > b.x0 && t.y0 < b.y1 && t.y1 > b.y0; });
        if (!hit) { placed.push(t); labels[geo.series[i].s.key] = t; return; }
      }
    });
    return labels;
  }

  function headShape(s) {
    var dir = s.kind === 'theme' ? 'theme' : (s.direction || 'flat');
    if (dir === 'theme') return '<path class="mf-dot theme" d="M0-6 6 0 0 6-6 0Z"/>';
    return '<circle class="mf-dot ' + (dir === 'inflow' ? 'in' : dir === 'outflow' ? 'out' : 'flat') + '" r="6"/>';
  }

  function rrgSvg(rrg, opts) {
    var g = RRG, geo = rrgGeometry(rrg, opts), labels = rrgLabels(geo), o = '', f1 = function (v) { return v.toFixed(1); };
    var x0 = g.L, x1 = g.W - g.R, y0 = g.T, y1 = g.H - g.B;
    o += '<rect class="mf-q lead" x="' + f1(geo.cx) + '" y="' + y0 + '" width="' + f1(x1 - geo.cx) + '" height="' + f1(geo.cy - y0) + '"/>' +
         '<rect class="mf-q impr" x="' + x0 + '" y="' + y0 + '" width="' + f1(geo.cx - x0) + '" height="' + f1(geo.cy - y0) + '"/>' +
         '<rect class="mf-q weak" x="' + f1(geo.cx) + '" y="' + f1(geo.cy) + '" width="' + f1(x1 - geo.cx) + '" height="' + f1(y1 - geo.cy) + '"/>' +
         '<rect class="mf-q lagg" x="' + x0 + '" y="' + f1(geo.cy) + '" width="' + f1(geo.cx - x0) + '" height="' + f1(y1 - geo.cy) + '"/>';
    niceTicks(geo.ex[0], geo.ex[1], 6).forEach(function (t) {
      if (t <= geo.ex[0] || t >= geo.ex[1] || t === 100) return;
      o += '<line class="mf-grid" x1="' + f1(geo.X(t)) + '" x2="' + f1(geo.X(t)) + '" y1="' + y0 + '" y2="' + y1 + '"/>' +
        '<text class="mf-tick" x="' + f1(geo.X(t)) + '" y="' + (y1 + 16) + '" text-anchor="middle">' + t + '</text>';
    });
    niceTicks(geo.ey[0], geo.ey[1], 5).forEach(function (t) {
      if (t <= geo.ey[0] || t >= geo.ey[1] || t === 100) return;
      o += '<line class="mf-grid" x1="' + x0 + '" x2="' + x1 + '" y1="' + f1(geo.Y(t)) + '" y2="' + f1(geo.Y(t)) + '"/>' +
        '<text class="mf-tick" x="' + (x0 - 8) + '" y="' + f1(geo.Y(t) + 3.5) + '" text-anchor="end">' + t + '</text>';
    });
    o += '<line class="mf-zero" x1="' + f1(geo.cx) + '" x2="' + f1(geo.cx) + '" y1="' + y0 + '" y2="' + y1 + '"/>' +
         '<line class="mf-zero" x1="' + x0 + '" x2="' + x1 + '" y1="' + f1(geo.cy) + '" y2="' + f1(geo.cy) + '"/>' +
         '<text class="mf-tick" x="' + f1(geo.cx) + '" y="' + (y1 + 16) + '" text-anchor="middle">100</text>' +
         '<text class="mf-tick" x="' + (x0 - 8) + '" y="' + f1(geo.cy + 3.5) + '" text-anchor="end">100</text>';
    var qi = narrow ? 8 : 12;
    o += '<text class="mf-qname" x="' + (x1 - qi) + '" y="' + (y0 + qi + 10) + '" text-anchor="end">Leading</text>' +
         '<text class="mf-qname" x="' + (x0 + qi) + '" y="' + (y0 + qi + 10) + '">Improving</text>' +
         '<text class="mf-qname" x="' + (x1 - qi) + '" y="' + (y1 - qi) + '" text-anchor="end">Weakening</text>' +
         '<text class="mf-qname" x="' + (x0 + qi) + '" y="' + (y1 - qi) + '">Lagging</text>';
    o += '<text class="mf-axis" x="' + x1 + '" y="' + (g.H - 6) + '" text-anchor="end">' + (narrow ? 'Stronger' : 'Stronger than the ' + esc(rrg.benchmark || 'Nifty 50')) + ' →</text>' +
         '<text class="mf-axis" x="' + x0 + '" y="' + (g.H - 6) + '">← Weaker</text>' +
         '<text class="mf-axis" transform="translate(13 ' + y0 + ') rotate(-90)" text-anchor="end">Gaining →</text>';
    var last = geo.weeks.length - 1;
    geo.series.forEach(function (e) {
      var s = e.s, lab = labels[s.key], pts = e.pts, head = rrgAt(pts, last), trail = '', dots = '';
      if (!head) return;
      pts.forEach(function (p, i) {
        if (!p) return;
        trail += (trail ? ' ' : '') + f1(p.x) + ',' + f1(p.y);
        if (i < last) dots += '<circle class="mf-step" data-i="' + i + '" cx="' + f1(p.x) + '" cy="' + f1(p.y) + '" r="2.2"/>';
      });
      o += '<g class="mf-rr k-' + esc(s.kind) + '" data-key="' + esc(s.key) + '" data-tip="rrg"' + (s.kind === 'sector' ? ' data-sector="' + esc(s.key) + '" tabindex="0" role="button"' : '') +
        ' aria-label="' + esc(s.full || s.name) + ': ' + esc(s.quadrant || 'not placed') + '">' +
        '<polyline class="mf-trail" points="' + trail + '"/>' + dots +
        '<g class="mf-headg" transform="translate(' + f1(head.x) + ' ' + f1(head.y) + ')"><circle class="mf-hit" r="14"/>' + headShape(s) +
        (lab ? '<text class="mf-lab" x="' + lab.dx + '" y="' + lab.dy + '" text-anchor="' + lab.a + '">' + esc(s.name) + '</text>' : '') + '</g></g>';
    });
    return '<svg class="mf-rrg-svg" viewBox="0 0 ' + g.W + ' ' + g.H + '" role="group" aria-label="Sector rotation against the ' + esc(rrg.benchmark || 'Nifty 50') + '. The lists beside it name every sector in each quadrant.">' + o + '</svg>';
  }

  /* Each series, with the FPI direction its dot is drawn in. */
  function rrgWithFlow(d) {
    var dir = {};
    (d.sectors || []).concat(d.unscored || []).forEach(function (c) { dir[c.slug] = c.fpi ? c.fpi.direction : null; });
    var rrg = d.rrg || {};
    return {
      benchmark: rrg.benchmark, weeks: rrg.weeks || [], week_dates: rrg.week_dates || rrg.weeks || [],
      series: (rrg.series || []).map(function (s) {
        var c = {}; for (var k in s) c[k] = s[k];
        c.direction = s.kind === 'theme' ? null : (dir[s.key] || 'flat');
        return c;
      })
    };
  }

  function quadLists(rrg, themes) {
    var groups = { Leading: [], Improving: [], Weakening: [], Lagging: [] };
    rrg.series.forEach(function (s) {
      if ((s.kind === 'theme' && !themes) || !groups[s.quadrant]) return;
      groups[s.quadrant].push(s);
    });
    return '<div class="mf-quads"><p class="mf-qcap">Strength · momentum. 100 is the index.</p>' + ['Leading', 'Improving', 'Weakening', 'Lagging'].map(function (q) {
      var list = groups[q];
      return '<div class="mf-qlist"><h4>' + quadChip(q) + '<small>' + esc(QUAD_NOTE[q]) + '</small></h4>' +
        (list.length ? '<ul>' + list.map(function (s) {
          var p = s.points[s.points.length - 1] || {};
          var name = s.kind === 'sector'
            ? '<button type="button" class="mf-rowbtn" data-sector="' + esc(s.key) + '">' + esc(s.name) + '</button>'
            : '<span class="mf-theme">' + esc(s.name) + '</span>';
          return '<li data-key="' + esc(s.key) + '">' + name + '<span>' + esc(num(p.ratio) === null ? '' : p.ratio.toFixed(1)) + ' · ' + esc(num(p.momentum) === null ? '' : p.momentum.toFixed(1)) + '</span></li>';
        }).join('') + '</ul>' : '<p>None this week.</p>') + '</div>';
    }).join('') + '</div>';
  }

  function rotation(d, state) {
    var rrg = rrgWithFlow(d), n = rrg.weeks.length;
    if (!n || !rrg.series.length) {
      return '<section class="mf-sec mf-rot"><div class="mf-head"><h3>Sector rotation</h3></div>' +
        '<p class="mf-empty">The rotation chart needs about three months of index closes. The backfill reads them.</p></section>';
    }
    var hasThemes = rrg.series.some(function (s) { return s.kind === 'theme'; });
    return '<section class="mf-sec mf-rot"><div class="mf-head"><div><h3>Sector rotation against the ' + esc(rrg.benchmark || 'Nifty 50') + '</h3>' +
      '<p>Each sector’s last ' + n + ' weeks. Right of centre is stronger than the index; above centre is gaining on it. Sectors usually travel clockwise.</p></div>' +
      '<div class="mf-tools">' + (hasThemes ? '<label class="mf-check"><input type="checkbox" data-themes' + (state.themes ? ' checked' : '') + '><span>Bank, PSU and energy themes</span></label>' : '') + '</div></div>' +
      '<div class="mf-rot-grid"><div><div class="mf-plot" data-plot="rrg">' + rrgSvg(rrg, state) + '</div>' +
      '<div class="mf-play"><button type="button" class="mf-playbtn" data-play aria-label="Play the last ' + n + ' weeks"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg><span>Play</span></button>' +
      '<input type="range" class="mf-scrub" min="0" max="' + (n - 1) + '" step="0.01" value="' + (n - 1) + '" aria-label="Week">' +
      '<output class="mf-week">Week to ' + esc(day(rrg.week_dates[n - 1])) + '</output></div>' +
      '<div class="mf-legend mf-rrg-legend"><span><svg viewBox="-8 -8 16 16" aria-hidden="true"><circle class="mf-dot in" r="6"/></svg>FPIs bought in the latest fortnight</span>' +
      '<span><svg viewBox="-8 -8 16 16" aria-hidden="true"><circle class="mf-dot out" r="6"/></svg>FPIs sold</span>' +
      (state.themes && hasThemes ? '<span><svg viewBox="-8 -8 16 16" aria-hidden="true"><path class="mf-dot theme" d="M0-6 6 0 0 6-6 0Z"/></svg>Theme: price only, no FPI data</span>' : '') + '</div></div>' +
      quadLists(rrg, state.themes) + '</div></section>';
  }

  /* ════════════════════════════════════════════════════════════════════════
     THE RANKING
     ════════════════════════════════════════════════════════════════════════ */
  var RING = 2 * Math.PI * 26;
  function ring(score) {
    var s = num(score), len = s === null ? 0 : Math.max(0, Math.min(100, s)) / 100 * RING;
    return '<svg class="mf-ring" viewBox="0 0 64 64" aria-hidden="true"><circle class="t" cx="32" cy="32" r="26"/>' +
      '<circle class="v" cx="32" cy="32" r="26" stroke-dasharray="' + len.toFixed(1) + ' ' + RING.toFixed(1) + '" style="--len:' + len.toFixed(1) + '"/></svg>';
  }
  /* Twelve fortnights as bars around a centre line. */
  function flowSpark(values) {
    var v = (values || []).map(num), max = 0, i, W = 120, H = 30;
    for (i = 0; i < v.length; i++) if (v[i] !== null && Math.abs(v[i]) > max) max = Math.abs(v[i]);
    if (!v.length || !max) return '<span class="mf-spark none" aria-hidden="true"></span>';
    var step = W / v.length, bw = Math.max(2, step - 2), o = '';
    for (i = 0; i < v.length; i++) {
      if (v[i] === null || v[i] === 0) continue;
      var h = Math.max(1.5, Math.abs(v[i]) / max * (H / 2 - 1));
      o += '<rect class="' + (v[i] > 0 ? 'in' : 'out') + '" x="' + (i * step).toFixed(1) + '" y="' + (v[i] > 0 ? H / 2 - h : H / 2).toFixed(1) +
        '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="1"/>';
    }
    return '<svg class="mf-spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' + o + '<line x1="0" x2="' + W + '" y1="' + H / 2 + '" y2="' + H / 2 + '"/></svg>';
  }
  var PART = { fpi: 'FPI flow', rs: 'Rotation', breadth: 'Breadth' };
  function meters(c) {
    var parts_ = c.components || {};
    return '<div class="mf-parts">' + ['fpi', 'rs', 'breadth'].map(function (k) {
      var p = parts_[k] || {}, s = num(p.score);
      return '<div class="mf-part' + (s === null ? ' na' : '') + '"><span>' + PART[k] + '</span><i><b style="width:' + (s === null ? 0 : s).toFixed(0) + '%"></b></i><em>' + (s === null ? DASH : s.toFixed(0)) + '</em></div>';
    }).join('') + '</div>';
  }

  function card(c, i) {
    var f = c.fpi || {}, rs = c.rs || {};
    return '<button type="button" class="mf-card" data-sector="' + esc(c.slug) + '" style="--i:' + i + '" aria-label="' + esc(c.sector) + ', score ' + esc(num(c.score) === null ? 'none' : Math.round(c.score)) + ' of 100, rank ' + esc(c.rank) + ' of ' + esc(c.of) + '. Open its stocks.">' +
      '<div class="mf-card-top"><span class="mf-rank">' + (c.rank < 10 ? '0' : '') + esc(c.rank) + '</span><span class="mf-name">' + esc(c.short) + '</span>' + quadChip(c.quadrant) + '</div>' +
      '<div class="mf-card-mid"><div class="mf-score">' + ring(c.score) + '<b>' + (num(c.score) === null ? DASH : Math.round(c.score)) + '</b></div>' +
        '<div class="mf-flow"><div class="mf-trendline' + (f.flipped_to_inflow ? ' flip' : '') + '"' +
          (f.flipped_to_inflow ? ' title="FPIs turned from selling to buying in the latest fortnight"' : '') + '>' + trendArrow(f) + '<span>' + esc(trendWord(c.fpi)) + '</span></div>' +
        '<div class="mf-flowfig"><small>Latest</small><b>' + esc(cr(f.latest_cr, true)) + '</b></div>' +
        '<div class="mf-flowfig"><small>Last three</small><b>' + esc(cr(f.sum3_cr, true)) + '</b></div></div></div>' +
      flowSpark(c.fpi_spark) +
      '<div class="mf-rs"><span>Against the Nifty 50</span><b>' + esc(signed(rs.rs_1m, 1)) + '</b><small>1 month</small><b>' + esc(signed(rs.rs_3m, 1)) + '</b><small>3 months</small></div>' +
      meters(c) +
      '<div class="mf-open">' + (c.top_stocks && c.top_stocks.length ? esc(c.top_stocks.map(function (s) { return s.symbol; }).join(' · ')) : 'Stocks inside') + '<span aria-hidden="true">→</span></div>' +
      '</button>';
  }

  function ranking(d) {
    var list = d.sectors || [], w = d.weights || {};
    if (!list.length) {
      return '<section class="mf-sec mf-ranking"><div class="mf-head"><h3>Sectors, ranked on money flow</h3></div>' +
        '<p class="mf-empty">No sector can be scored yet: a score needs two of FPI flow, rotation and breadth.</p></section>';
    }
    var un = (d.unscored || []).map(function (c) { return c.short; });
    return '<section class="mf-sec mf-ranking"><div class="mf-head"><div><h3>Sectors, ranked on money flow</h3>' +
      '<p>Sector Money Flow Score, out of 100: FPI flow ' + esc(w.fpi) + ', rotation ' + esc(w.rs) + ', breadth ' + esc(w.breadth) + '. Open a sector for the stocks being accumulated inside it.</p></div></div>' +
      '<div class="mf-cards">' + list.map(card).join('') + '</div>' +
      (un.length ? '<p class="mf-unscored">Not scored, too few companies to measure: ' + esc(un.join(', ')) + '. Their flows are in the heatmap.</p>' : '') + '</section>';
  }

  /* ── the four figures at the top ─────────────────────────────────────── */
  function tile(k, v, n, cls) {
    return '<div class="mf-tile ' + (cls || '') + '"><div class="k">' + k + '</div><div class="v">' + v + '</div><div class="n">' + n + '</div></div>';
  }
  function tiles(d) {
    var m = d.market || {}, f = d.fpi || {}, lp = f.latest_period || {}, flips = f.flipped_to_inflow || [];
    var who = function (k, name) {
      if (!m.available) return tile(name + ', latest session', DASH, 'Not recorded yet');
      var l = m.latest || {};
      return tile('<i class="mf-key ' + k + '"></i>' + name + ', ' + esc(day(l.date)), esc(cr(l[k], true)),
        esc(cr(m[k + '_5d'], true)) + ' over ' + m.sessions_in_5d + ' session' + (m.sessions_in_5d === 1 ? '' : 's') +
        (m.sessions_in_20d > m.sessions_in_5d ? ' · ' + esc(cr(m[k + '_20d'], true)) + ' over ' + m.sessions_in_20d : ''));
    };
    return '<div class="mf-tiles">' + who('fii', 'FII') + who('dii', 'DII') +
      tile('FPI equity, ' + esc(period(lp.start, lp.end) || 'latest fortnight'), esc(cr(f.total_cr, true)),
        (f.inflow_sectors || 0) + ' sectors bought · ' + (f.outflow_sectors || 0) + ' sold') +
      tile('Turned to buying', String(flips.length), flips.length ? esc(flips.slice(0, 6).join(', ')) + (flips.length > 6 ? ' and ' + (flips.length - 6) + ' more' : '') : 'No sector flipped from selling this fortnight') +
      '</div>';
  }

  function method(d) {
    var m = d.method || {}, map = d.mapping || [];
    var fit = { clean: 'Clean', broad: 'Broad', ambiguous: 'A judgement', none: 'No index', excluded: 'Left out' };
    return '<details class="mf-method"><summary>How the score is made, and which index stands for which sector</summary><div class="mf-method-body">' +
      '<dl>' + [['The score', m.score], ['FPI flow', m.fpi], ['Rotation', m.rrg], ['Against the index', m.rs], ['Breadth', m.breadth], ['Accumulation', m.accumulation]].map(function (r) {
        return r[1] ? '<dt>' + r[0] + '</dt><dd>' + esc(r[1]) + '</dd>' : '';
      }).join('') + '</dl>' +
      '<div class="mf-scroll"><table><thead><tr><th>NSDL sector</th><th>NSE index</th><th>Fit</th><th>Note</th></tr></thead><tbody>' +
      map.map(function (r) {
        return '<tr><th>' + esc(r.nsdl_sector) + '</th><td>' + esc(r.nse_index || 'Basket of its own stocks') + '</td><td><span class="mf-fit f-' + esc(r.fit) + '">' + esc(fit[r.fit] || r.fit) + '</span></td><td>' + esc(r.note || '') + '</td></tr>';
      }).join('') + '</tbody></table></div></div></details>';
  }

  function state_(title, text, extra) {
    return '<div class="mf-state"><b>' + esc(title) + '</b><span>' + esc(text) + '</span>' + (extra || '') + '</div>';
  }

  function render(d, state) {
    var s = { range: (state && state.range) || 60, heat: (state && state.heat) || 'pct', themes: !!(state && state.themes) };
    setNarrow(!!(state && state.narrow));
    if (narrow && !(state && state.ranged)) s.range = 20;
    var top = '<header class="mf-top"><div class="mf-eyebrow">Institutional flows · India</div><h2>Money <i>flow</i></h2>';
    if (!d || d.available === false) {
      return '<div class="mf-stage">' + top + '</header>' +
        state_('Nothing to show yet', (d && d.message) || 'Money Flow has not been filled on this server yet.') + '</div>';
    }
    var lp = (d.fpi || {}).latest_period;
    if ((d.market || {}).days && d.market.days.length <= 20) s.range = 20;
    if (state) state.range = s.range;
    return '<div class="mf-stage">' + top +
      '<p class="mf-asof">Session of ' + esc(day(d.as_of, true)) + (lp ? ' · FPI data to ' + esc(period(lp.start, lp.end, true)) : '') + '</p></header>' +
      tiles(d) + hero(d.market, s.range) + heatmap(d.heatmap, s.heat, lp) + rotation(d, s) + ranking(d) +
      ((d.gaps || []).length ? '<div class="mf-gaps"><b>What is missing</b><ul>' + d.gaps.map(function (g) { return '<li>' + esc(g) + '</li>'; }).join('') + '</ul></div>' : '') +
      method(d) + '<p class="mf-disc">' + esc(d.disclaimer || '') + '</p></div>';
  }

  /* ════════════════════════════════════════════════════════════════════════
     ONE SECTOR, OPENED
     ════════════════════════════════════════════════════════════════════════ */
  function fortnightBars(list) {
    var v = list.map(function (f) { return num(f.net_cr); }), max = 0, W = FN.W, H = FN.H, L = FN.L, R = FN.R, mid = FN.mid, half = FN.half, i;
    v.forEach(function (x) { if (x !== null && Math.abs(x) > max) max = Math.abs(x); });
    if (!list.length || !max) return '';
    var step = (W - L - R) / list.length, bw = Math.max(3, Math.min(18, step - 4)), o = '';
    var top = max * 1.08, Y = function (x) { return mid - x / top * half; };
    var ticks = niceTicks(-max, max, 4).filter(function (t) { return Math.abs(t) <= top; });
    ticks.forEach(function (t) {
      o += '<line class="' + (t === 0 ? 'mf-zero' : 'mf-grid') + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(t).toFixed(1) + '" y2="' + Y(t).toFixed(1) + '"/>' +
        '<text class="mf-tick" x="' + (L - 6) + '" y="' + (Y(t) + 3.5).toFixed(1) + '" text-anchor="end">' + esc(axisLabel(t)) + '</text>';
    });
    for (i = 0; i < list.length; i++) {
      if (v[i] === null) continue;
      var x = L + i * step + (step - bw) / 2;
      o += '<g data-tip="fn" data-period="' + esc(period(list[i].start, list[i].end, true)) + '" data-cr="' + esc(v[i]) + '" data-pct="' + esc(list[i].pct) + '">' +
        '<rect class="mf-hit" x="' + (L + i * step).toFixed(1) + '" y="8" width="' + step.toFixed(1) + '" height="' + (H - 30) + '"/>' +
        '<path class="mf-fbar ' + (v[i] >= 0 ? 'in' : 'out') + '" d="' + barPath(+x.toFixed(1), +bw.toFixed(1), mid, +Y(v[i]).toFixed(1)) + '"/></g>';
    }
    var every = Math.max(1, Math.ceil(list.length / FN.labels));
    for (i = list.length - 1; i >= 0; i -= every) {
      var b = parts(list[i].end);
      o += '<text class="mf-tick" x="' + (L + i * step + step / 2).toFixed(1) + '" y="' + (H - 4) + '" text-anchor="middle">' + (b ? b.d + ' ' + MON[b.m - 1] + (b.m === 1 || i < every ? ' ' + String(b.y).slice(2) : '') : '') + '</text>';
    }
    return '<svg class="mf-fn-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="FPI equity net investment in this sector, per fortnight">' + o + '</svg>';
  }

  function dealChip(x) {
    if (!x || num(x.net_cr) === null || Math.abs(x.net_cr) < 0.05) {
      return x && x.prop_cr ? '<span class="mf-deal none">Market makers only</span>' : '<span class="mf-deal none">' + DASH + '</span>';
    }
    var who = (x.net_cr > 0 ? x.top_buyers : x.top_sellers) || [];
    return '<span class="mf-deal ' + (x.net_cr > 0 ? 'in' : 'out') + '"><i aria-hidden="true"></i>' + (x.net_cr > 0 ? 'Bought ' : 'Sold ') + esc(cr(Math.abs(x.net_cr))) + '</span>' +
      (who.length ? '<small>' + esc(String(who[0].client).toLowerCase().replace(/\b[a-z]/g, function (c) { return c.toUpperCase(); })) + '</small>' : '');
  }

  function stockRow(r) {
    var up = num(r.deliv_ratio) !== null && r.deliv_ratio >= 1.05, base = num(r.deliv_avg20), now = num(r.deliv_pct);
    return '<tr><th scope="row"><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '&amp;pane=deliv">' + esc(r.symbol) + '</a>' +
      '<small>' + esc(r.name || '') + '</small></th>' +
      '<td class="mf-deliv" data-label="Delivered today"><b>' + esc(pct(now)) + '</b><small>usual ' + esc(pct(base)) + '</small>' +
        '<span class="mf-dbar' + (up ? ' up' : '') + '" aria-hidden="true"><i style="width:' + Math.min(100, now || 0).toFixed(0) + '%"></i><u style="left:' + Math.min(100, base || 0).toFixed(0) + '%"></u></span></td>' +
      '<td data-label="Volume vs usual"><b>' + esc(times(r.vol_ratio)) + '</b><small>5 sessions ' + esc(times(r.vol_ratio_5d)) + '</small></td>' +
      '<td data-label="5 sessions"><b class="mf-chg ' + way(r.chg_5d) + '">' + esc(signed(r.chg_5d, 1, '%')) + '</b><small>' + (num(r.up_vol_days) === null ? '' : r.up_vol_days + ' of 5 up on volume') + '</small></td>' +
      '<td class="mf-dealcell" data-label="Bulk and block, 30 days">' + dealChip(r.deals) + '</td>' +
      '<td class="mf-acc" data-label="Score"><b>' + (num(r.score) === null ? DASH : Math.round(r.score)) + '</b><span aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, num(r.score) || 0)).toFixed(0) + '%"></i></span></td></tr>' +
      '<tr class="mf-why"><td colspan="6">' + ((r.reasons || []).length ? esc(r.reasons.join(' ')) : 'Nothing unusual in delivery, volume or deals.') + '</td></tr>';
  }

  function drawer(d) {
    if (!d) return state_('Reading the sector…', 'Its fortnights and its stocks.');
    var c = d.card || {}, f = c.fpi || {}, rs = c.rs || {}, br = c.breadth, idx = d.index || {}, ci = c.index || {};
    var stocks = d.stocks || [];
    var basis = ci.source === 'basket' ? 'Measured on ' + esc((ci.label || 'a basket of its own stocks').replace(/^B/, 'a b')) + (idx.name ? ', because ' + esc(idx.name) + ' has too little history yet.' : '.')
              : ci.source === 'index' ? 'Measured on ' + esc(ci.label || idx.name) + '.'
              : 'Not measured against the Nifty 50.';
    return '<header class="mf-dhead"><div><div class="mf-eyebrow">' + (num(c.rank) === null ? 'Not scored' : 'Rank ' + esc(c.rank) + ' of ' + esc(c.of)) + '</div>' +
      '<h3 id="mf-dtitle">' + esc(d.sector) + '</h3><div class="mf-dchips">' + quadChip(c.quadrant) +
      '<span class="mf-trendline">' + trendArrow(f) + '<span>' + esc(trendWord(c.fpi)) + '</span></span></div></div>' +
      '<div class="mf-score big">' + ring(c.score) + '<b>' + (num(c.score) === null ? DASH : Math.round(c.score)) + '</b></div>' +
      '<button type="button" class="mf-close" data-close aria-label="Close">×</button></header>' +
      '<div class="mf-dfacts">' +
        '<div><span>Latest fortnight</span><b>' + esc(cr(f.latest_cr, true)) + '</b><small>' + esc(period(f.period_start, f.period_end, true)) + '</small></div>' +
        '<div><span>Last three</span><b>' + esc(cr(f.sum3_cr, true)) + '</b><small>' + esc(signed(f.sum3_pct, 2, '%')) + ' of FPI holdings</small></div>' +
        '<div><span>Against the Nifty 50</span><b>' + esc(signed(rs.rs_1m, 1)) + ' · ' + esc(signed(rs.rs_3m, 1)) + '</b><small>1 and 3 months, points</small></div>' +
        '<div><span>Above their 50-day</span><b>' + (br ? esc(pct(br.pct)) : DASH) + '</b><small>' + (br ? br.above + ' of ' + br.of + ' stocks' : 'Not measured') + '</small></div></div>' +
      meters(c) +
      '<section><h4>FPI flow, fortnight by fortnight</h4><div class="mf-plot" data-plot="fn">' + (fortnightBars(d.fortnights || []) || '<p class="mf-empty">No fortnight is stored for this sector.</p>') + '</div></section>' +
      '<section><h4>Stocks showing accumulation</h4><p class="mf-dnote">' + esc(d.method || '') + '</p>' +
      (stocks.length ? '<div class="mf-scroll"><table class="mf-stocks"><thead><tr><th scope="col">Stock</th><th scope="col">Delivered today</th><th scope="col">Volume vs usual</th><th scope="col">5 sessions</th><th scope="col">Bulk and block, 30 days</th><th scope="col">Score</th></tr></thead><tbody>' +
        stocks.map(stockRow).join('') + '</tbody></table></div>'
        : '<p class="mf-empty">No stock in this sector can be read for accumulation yet. That needs the delivery record, which fills itself from NSE’s daily file.</p>') + '</section>' +
      '<p class="mf-dnote">' + basis + (idx.note ? ' ' + esc(idx.note) : '') + (c.partial ? ' Scored without ' + esc((c.missing || []).map(function (k) { return PART[k].toLowerCase(); }).join(' and ')) + ', which could not be measured.' : '') + '</p>' +
      '<p class="mf-disc">' + esc(d.disclaimer || '') + '</p>';
  }

  /* What a hover or a focus says. */
  function tip(el) {
    var t = el.getAttribute('data-tip'), d = el.dataset;
    if (t === 'cell' || t === 'fn') {
      return '<b>' + esc(cr(d.cr, true)) + '</b>' + (t === 'cell' ? '<span>' + esc(d.sector) + '</span>' : '') + '<span>' + esc(d.period) + '</span>' +
        (num(d.pct) === null ? '' : '<span>' + esc(signed(d.pct, 2, '%')) + ' of FPI holdings in the sector</span>');
    }
    return '';
  }

  /* ════════════════════════════════════════════════════════════════════════
     Browser wiring
     ════════════════════════════════════════════════════════════════════════ */
  function wire() {
    var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
            : (window.API_BASE || 'https://taha-project.onrender.com');
    var state = { range: 60, heat: 'pct', themes: false, narrow: false, ranged: false }, data = null, asked = false, seq = 0;
    var anim = { raf: 0, t: 0, played: false }, geo = null, opened = null, lastFocus = null, tipEl = null, io = null;

    function host() { return document.getElementById('mf-root'); }
    function shown() { var v = document.getElementById('view-flows'); return !!v && v.style.display !== 'none'; }
    function still() {
      var off = document.documentElement.getAttribute('data-motion') === 'off';
      try { off = off || window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
      return off;
    }

    /* ── tooltip ─────────────────────────────────────────────────────────── */
    function showTip(html, x, y) {
      var h = host();
      if (!h || !html) return hideTip();
      if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'mf-tip'; tipEl.setAttribute('role', 'status'); }
      var stage = h.querySelector('.mf-stage') || h;
      if (tipEl.parentNode !== stage) stage.appendChild(tipEl);
      tipEl.innerHTML = html;
      tipEl.hidden = false;
      var w = tipEl.offsetWidth, ht = tipEl.offsetHeight, vw = document.documentElement.clientWidth;
      var left = Math.max(8, Math.min(vw - w - 8, x + 14)), top = y - ht - 12;
      if (top < 8) top = y + 18;
      tipEl.style.left = left + 'px'; tipEl.style.top = top + 'px';
    }
    function hideTip() { if (tipEl) tipEl.hidden = true; }

    /* ── the rotation chart, frame by frame ─────────────────────────────── */
    function rrgFrame(t) {
      var h = host(), svg = h && h.querySelector('.mf-rrg-svg');
      if (!svg || !geo) return;
      anim.t = t;
      var n = geo.weeks.length;
      geo.series.forEach(function (e) {
        var g = svg.querySelector('.mf-rr[data-key="' + e.s.key + '"]');
        if (!g) return;
        var at = rrgAt(e.pts, t);
        g.style.display = at ? '' : 'none';
        if (!at) return;
        var pts = [];
        for (var i = 0; i <= at.i; i++) if (e.pts[i]) pts.push(e.pts[i].x.toFixed(1) + ',' + e.pts[i].y.toFixed(1));
        if (t > at.i) pts.push(at.x.toFixed(1) + ',' + at.y.toFixed(1));     // between two weeks
        g.querySelector('.mf-trail').setAttribute('points', pts.join(' '));
        g.querySelector('.mf-headg').setAttribute('transform', 'translate(' + at.x.toFixed(1) + ' ' + at.y.toFixed(1) + ')');
        Array.prototype.forEach.call(g.querySelectorAll('.mf-step'), function (c) { c.style.display = +c.getAttribute('data-i') <= at.i && +c.getAttribute('data-i') < t ? '' : 'none'; });
      });
      var scrub = h.querySelector('.mf-scrub'), week = h.querySelector('.mf-week');
      if (scrub && document.activeElement !== scrub) scrub.value = t;
      if (week) week.textContent = 'Week to ' + day(geo.dates[Math.min(n - 1, Math.round(t))]);
      svg.classList.toggle('is-moving', t < n - 1);
    }
    function stop() {
      if (anim.raf) cancelAnimationFrame(anim.raf);
      anim.raf = 0;
      var b = host() && host().querySelector('.mf-playbtn');
      if (b) { b.classList.remove('on'); b.querySelector('span').textContent = anim.t >= (geo ? geo.weeks.length - 1 : 0) ? 'Replay' : 'Play'; }
    }
    function play() {
      if (!geo) return;
      stop();
      var n = geo.weeks.length - 1, b = host().querySelector('.mf-playbtn');
      if (still() || n < 1) { rrgFrame(n); return stop(); }
      var from = anim.t >= n ? 0 : anim.t, start = null, dur = 900 * (n - from);
      if (b) { b.classList.add('on'); b.querySelector('span').textContent = 'Pause'; }
      function step(ts) {
        if (start === null) start = ts;
        var k = Math.min(1, (ts - start) / dur);
        rrgFrame(from + (n - from) * k);
        if (k < 1) anim.raf = requestAnimationFrame(step); else stop();
      }
      anim.raf = requestAnimationFrame(step);
    }
    function initRrg() {
      geo = data && data.rrg ? rrgGeometry(rrgWithFlow(data), state) : null;
      anim.t = geo ? geo.weeks.length - 1 : 0;
    }

    /* ── sections reveal as they come into view ─────────────────────────── */
    function reveal() {
      var h = host();
      if (!h) return;
      var secs = h.querySelectorAll('.mf-sec, .mf-tiles');
      if (io) { io.disconnect(); io = null; }
      if (still() || !('IntersectionObserver' in window)) {
        h.classList.remove('mf-anim');
        return;
      }
      h.classList.add('mf-anim');
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          en.target.classList.add('is-in');
          io.unobserve(en.target);
          if (en.target.classList.contains('mf-rot') && !anim.played) { anim.played = true; anim.t = 0; rrgFrame(0); play(); }
        });
      }, { threshold: 0.18 });
      Array.prototype.forEach.call(secs, function (s) { io.observe(s); });
    }

    function isNarrow() { var h = host(); return !!h && h.clientWidth > 0 && h.clientWidth < 620; }
    function paint(keep) {
      var h = host();
      if (!h) return;
      stop(); hideTip();
      state.narrow = isNarrow();
      var y = window.scrollY;
      h.innerHTML = render(data, state);
      tipEl = null;
      initRrg();
      if (keep) {
        /* A control was used: the page is already on screen, so nothing
           replays and nothing jumps. */
        h.classList.remove('mf-anim');
        window.scrollTo(0, y);
      } else {
        anim.played = false;
        reveal();
      }
    }

    function load() {
      var h = host();
      if (!h) return;
      asked = true;
      var mine = ++seq;
      if (!data) h.innerHTML = '<div class="mf-stage">' + state_('Reading the flows…', 'FPI fortnights, FII and DII, and every sector against the Nifty 50.') + '</div>';
      fetch(API + '/moneyflow').then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== seq) return;
        data = d;
        paint(false);
      }).catch(function () {
        if (mine !== seq) return;
        asked = false;
        h.innerHTML = '<div class="mf-stage">' + state_('The engine is unreachable', 'If it has been idle it takes about thirty seconds to wake.',
          '<button type="button" class="mf-btn" data-retry>Try again</button>') + '</div>';
      });
    }

    /* ── the sector drawer ───────────────────────────────────────────────── */
    function drawerEl() {
      var el = document.getElementById('mf-drawer');
      if (el) return el;
      el = document.createElement('div');
      el.id = 'mf-drawer';
      el.className = 'mf-drawer';
      el.hidden = true;
      el.innerHTML = '<div class="mf-scrim" data-close></div><aside class="mf-panel" role="dialog" aria-modal="true" aria-labelledby="mf-dtitle" tabindex="-1"></aside>';
      document.body.appendChild(el);
      el.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('[data-close]')) closeDrawer();
      });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.stopPropagation(); return closeDrawer(); }
        if (e.key !== 'Tab') return;
        /* Tab stays inside the open panel. */
        var f = el.querySelectorAll('button, a[href], [tabindex="0"]');
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      });
      ['pointermove', 'pointerleave'].forEach(function (ev) { el.addEventListener(ev, onPointer, true); });
      return el;
    }
    function openDrawer(slug) {
      var el = drawerEl(), panel = el.querySelector('.mf-panel'), mine = slug;
      lastFocus = document.activeElement;
      opened = slug;
      panel.innerHTML = drawer(null);
      el.hidden = false;
      document.documentElement.classList.add('mf-locked');
      requestAnimationFrame(function () { el.classList.add('open'); panel.focus(); });
      fetch(API + '/moneyflow/sector/' + encodeURIComponent(slug)).then(function (r) { return r.json(); }).then(function (d) {
        if (opened !== mine) return;
        setNarrow(window.innerWidth < 620);
        panel.innerHTML = d && d.sector ? drawer(d) : state_('That sector could not be read', (d && d.detail) || 'Try again in a moment.', '<button type="button" class="mf-btn" data-close>Close</button>');
        setNarrow(state.narrow);          // the page's own charts keep their geometry
        panel.scrollTop = 0;
        var c = panel.querySelector('.mf-close');
        if (c) c.focus();
      }).catch(function () {
        if (opened !== mine) return;
        panel.innerHTML = state_('The engine is unreachable', 'The sector could not be read just now.', '<button type="button" class="mf-btn" data-close>Close</button>');
      });
    }
    function closeDrawer() {
      var el = document.getElementById('mf-drawer');
      if (!el || el.hidden) return;
      opened = null;
      el.classList.remove('open');
      document.documentElement.classList.remove('mf-locked');
      hideTip();
      setTimeout(function () { if (!opened) el.hidden = true; }, still() ? 0 : 260);
      if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
    }

    /* ── pointer: tooltips and the crosshair ─────────────────────────────── */
    function heroHover(svg, e) {
      var days = (data.market.days || []).slice(-state.range), G = heroGeometry(days), box = svg.getBoundingClientRect();
      var x = (e.clientX - box.left) / box.width * HERO.W;
      var i = Math.max(0, Math.min(days.length - 1, Math.round((x - HERO.L - G.slot / 2) / G.slot)));
      heroAt(svg, i, e.clientX, e.clientY);
    }
    function heroAt(svg, i, cx, cy) {
      var days = (data.market.days || []).slice(-state.range), G = heroGeometry(days), d = days[i], cross = svg.querySelector('.mf-cross');
      if (!d) return;
      svg.setAttribute('data-i', i);
      cross.style.display = '';
      cross.setAttribute('x1', G.x(i)); cross.setAttribute('x2', G.x(i));
      if (cx == null) { var b = svg.getBoundingClientRect(); cx = b.left + G.x(i) / HERO.W * b.width; cy = b.top + 40; }
      showTip('<span>' + esc(day(d.date, true)) + '</span>' +
        '<div class="row"><i class="mf-key fii"></i><b>' + esc(cr(d.fii, true)) + '</b><span>FII</span></div>' +
        '<div class="row"><i class="mf-key dii"></i><b>' + esc(cr(d.dii, true)) + '</b><span>DII</span></div>' +
        '<div class="row sub"><i class="mf-key fii line"></i><b>' + esc(cr(d.fii_cum, true)) + '</b><span>FII running</span></div>' +
        '<div class="row sub"><i class="mf-key dii line"></i><b>' + esc(cr(d.dii_cum, true)) + '</b><span>DII running</span></div>', cx, cy);
    }
    function rrgTip(g, x, y) {
      var key = g.getAttribute('data-key'), e = geo && geo.series.filter(function (s) { return s.s.key === key; })[0];
      if (!e) return;
      var at = rrgAt(e.pts, anim.t), p = at ? e.pts[at.i].p : null, s = e.s;
      var c = (data.sectors || []).concat(data.unscored || []).filter(function (c) { return c.slug === key; })[0];
      showTip('<b>' + esc(s.full || s.name) + '</b><span>' + esc(s.quadrant || 'Not placed') + (p ? ' · week to ' + esc(day(p.date || p.week)) : '') + '</span>' +
        (p ? '<div class="row"><b>' + p.ratio.toFixed(1) + '</b><span>strength (100 is the index)</span></div><div class="row"><b>' + p.momentum.toFixed(1) + '</b><span>momentum</span></div>' : '') +
        (c && c.fpi ? '<div class="row"><b>' + esc(cr(c.fpi.latest_cr, true)) + '</b><span>FPI, latest fortnight</span></div>' : (s.kind === 'theme' ? '<span>A theme: price only</span>' : '')) +
        (c && num(c.score) !== null ? '<div class="row"><b>' + Math.round(c.score) + '</b><span>Money Flow Score</span></div>' : ''), x, y);
    }
    function focusSeries(key) {
      var h = host(), svg = h && h.querySelector('.mf-rrg-svg');
      if (!svg) return;
      svg.classList.toggle('has-focus', !!key);
      Array.prototype.forEach.call(svg.querySelectorAll('.mf-rr'), function (g) { g.classList.toggle('on', g.getAttribute('data-key') === key); });
      Array.prototype.forEach.call(h.querySelectorAll('.mf-qlist li'), function (li) { li.classList.toggle('on', li.getAttribute('data-key') === key); });
    }
    function onPointer(e) {
      if (!data) return;
      if (e.type === 'pointerleave') { hideTip(); return; }
      var t = e.target, svg = t.closest ? t.closest('.mf-hero-svg') : null;
      if (svg) return heroHover(svg, e);
      var rr = t.closest ? t.closest('.mf-rr') : null;
      if (rr) { focusSeries(rr.getAttribute('data-key')); return rrgTip(rr, e.clientX, e.clientY); }
      var li = t.closest ? t.closest('.mf-qlist li') : null;
      focusSeries(li ? li.getAttribute('data-key') : null);
      var el = t.closest ? t.closest('[data-tip]') : null;
      if (el) return showTip(tip(el), e.clientX, e.clientY);
      var cross = host() && host().querySelector('.mf-cross');
      if (cross) cross.style.display = 'none';
      hideTip();
    }

    function start() {
      var view = document.getElementById('view-flows'), h = host();
      if (!view || !h) return;
      h.addEventListener('click', function (e) {
        var t = e.target, b = t.closest ? t.closest('button, .mf-rr[data-sector]') : null;
        if (!b || !h.contains(b)) return;
        if (b.hasAttribute('data-retry')) return load();
        if (b.hasAttribute('data-play')) return anim.raf ? stop() : play();
        if (b.dataset.range) { state.range = Number(b.dataset.range); state.ranged = true; return paint(true); }
        if (b.dataset.heat) { state.heat = b.dataset.heat; return paint(true); }
        if (b.dataset.sector) return openDrawer(b.dataset.sector);
      });
      h.addEventListener('change', function (e) {
        if (e.target.hasAttribute && e.target.hasAttribute('data-themes')) { state.themes = e.target.checked; paint(true); }
      });
      h.addEventListener('input', function (e) {
        if (e.target.classList && e.target.classList.contains('mf-scrub')) { stop(); rrgFrame(Number(e.target.value)); stop(); }
      });
      h.addEventListener('keydown', function (e) {
        var t = e.target;
        if (t.classList && t.classList.contains('mf-rr') && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); return openDrawer(t.dataset.sector); }
        if (t.classList && t.classList.contains('mf-hero-svg') && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
          e.preventDefault();
          var n = Math.min(state.range, (data.market.days || []).length), i = t.hasAttribute('data-i') ? +t.getAttribute('data-i') : n;
          heroAt(t, Math.max(0, Math.min(n - 1, i + (e.key === 'ArrowLeft' ? -1 : 1))));
        }
      });
      h.addEventListener('focusin', function (e) {
        var rr = e.target.closest ? e.target.closest('.mf-rr') : null;
        if (rr) { var b = rr.querySelector('.mf-headg').getBoundingClientRect(); focusSeries(rr.getAttribute('data-key')); rrgTip(rr, b.left + b.width / 2, b.top); }
      });
      h.addEventListener('focusout', function () { hideTip(); focusSeries(null); });
      ['pointermove', 'pointerleave'].forEach(function (ev) { h.addEventListener(ev, onPointer, ev === 'pointerleave'); });
      h.addEventListener('pointerleave', function () { hideTip(); focusSeries(null); var c = h.querySelector('.mf-cross'); if (c) c.style.display = 'none'; });
      if ('MutationObserver' in window) {
        new MutationObserver(function () {
          if (shown() && !asked) load();
          if (!shown()) { stop(); closeDrawer(); }
        }).observe(view, { attributes: true, attributeFilter: ['style'] });
      }
      /* A phone turned on its side, or a window dragged narrow: the charts
         are redrawn at the new size, not scaled. */
      var rz = 0;
      window.addEventListener('resize', function () {
        clearTimeout(rz);
        rz = setTimeout(function () { if (data && shown() && isNarrow() !== state.narrow) paint(true); }, 180);
      });
      if (shown()) load();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  }

  return {
    render: render, drawer: drawer, hero: hero, heatmap: heatmap, rotation: rotation, ranking: ranking, card: card,
    heroGeometry: heroGeometry, heroSvg: heroSvg, barPath: barPath, rrgGeometry: rrgGeometry, rrgAt: rrgAt,
    rrgLabels: rrgLabels, rrgWithFlow: rrgWithFlow, heatScale: heatScale, heatStep: heatStep,
    setNarrow: setNarrow, niceTicks: niceTicks, cr: cr, compact: compact, signed: signed, period: period, day: day,
    trendWord: trendWord, tip: tip, wire: wire
  };
});
