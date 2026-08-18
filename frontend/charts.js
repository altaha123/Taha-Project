/* ============================================================================
   Altaha — Charts
   ----------------------------------------------------------------------------
   A drop-in Charts tab. One <script> line in index.html and nothing else: this
   file injects its own tab button (desktop bar and mobile bar), its own view
   container, and its own workspace. It reads API_BASE from the page and needs
   no backend change to run.

   WHAT IS NEW HERE VERSUS THE EXISTING CHART PANEL
   ------------------------------------------------
   1. Drawings are anchored to TIME AND PRICE, not to the on-screen pixel or to
      a bar index. Switch 15m to 1D and the trendline you drew still sits on the
      same two dates. The old panel stored a lightweight-charts LineSeries per
      drawing, which meant the drawing was data — it could not be moved, could
      not be deleted individually, and was wiped on every timeframe change.
   2. Drawings live on a canvas above the chart, so there is no limit on what
      can be drawn: rectangles, Fibonacci grids, parallel channels, a measuring
      ruler and a risk/reward position box are all just paths.
   3. Everything is selectable, draggable by body or by handle, deletable, and
      undoable, and it persists per symbol in the browser.
   4. It works on touch. The existing site hides its drawing tools below 780px
      with the comment "unusable on touch" — they were not unusable, the hit
      targets were 24px. These are 40px with 16px hit tolerance.
   5. The last candle updates from the live quote every second or two instead
      of the whole chart being refetched every sixty. That, more than anything
      else, is what makes a chart feel alive.

   The drawing model is deliberately plain JSON:
     { id, type, pts:[{t,p}], color, width, text }
   so it can be exported, shared as a URL, or saved server-side later without
   touching any of the rendering code.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_CHARTS__) return;
  window.__ALTAHA_CHARTS__ = 1;

  /* ── plumbing ──────────────────────────────────────────────────────────── */

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  var $ = function (id) { return document.getElementById(id); };
  var IS_TOUCH = window.matchMedia("(hover:none)").matches;
  var TOL = IS_TOUCH ? 16 : 8;
  var HANDLE = IS_TOUCH ? 7 : 5;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function tok(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fb;
  }
  function fmt(n, d) {
    if (n == null || !isFinite(n)) return "—";
    return Number(n).toLocaleString("en-IN", {
      minimumFractionDigits: d == null ? 2 : d,
      maximumFractionDigits: d == null ? 2 : d
    });
  }
  function uid() { return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  /* IST session window. The market status pill on the page is authoritative
     when it exists; this is the fallback so the Charts tab is never wrong on
     its own. */
  function marketOpen() {
    var mk = $("mkstatus");
    if (mk && mk.classList.contains("open")) return true;
    if (mk && (mk.classList.contains("closed") || mk.classList.contains("pre"))) return false;
    var n = new Date(Date.now() + (new Date().getTimezoneOffset() * 60000) + 19800000);
    if (n.getDay() === 0 || n.getDay() === 6) return false;
    var m = n.getHours() * 60 + n.getMinutes();
    return m >= 555 && m < 930;
  }

  /* ── timeframes ────────────────────────────────────────────────────────── */

  var TFS = [
    { k: "1m", lab: "1m" }, { k: "5m", lab: "5m" }, { k: "15m", lab: "15m" },
    { k: "1H", lab: "1H" }, { k: "4H", lab: "4H" }, { k: "1D", lab: "1D" },
    { k: "1W", lab: "1W" }
  ];

  /* ── tools ─────────────────────────────────────────────────────────────── */

  var I = {
    pan: '<path d="M6 11V6.5a1.5 1.5 0 0 1 3 0V11m0-1V5a1.5 1.5 0 0 1 3 0v5m0-.5V6a1.5 1.5 0 0 1 3 0v6"/><path d="M15 8.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-1a6 6 0 0 1-5.2-3L4 13.4a1.5 1.5 0 0 1 2.5-1.7L8 13.5"/>',
    sel: '<path d="M5 3l14 7.5-6.2 1.8L9.6 19z"/>',
    trend: '<path d="M4 19 20 5"/><circle cx="4" cy="19" r="2"/><circle cx="20" cy="5" r="2"/>',
    ray: '<path d="M4 18 20 6"/><circle cx="4" cy="18" r="2"/><path d="m16 6 4 0 0 4"/>',
    xline: '<path d="M2 20 22 4"/><path d="m5 18.5-2.6 1.9M19 5.6l2.6-1.9"/>',
    hline: '<path d="M3 12h18"/><circle cx="8" cy="12" r="2"/>',
    vline: '<path d="M12 3v18"/><circle cx="12" cy="9" r="2"/>',
    rect: '<rect x="3.5" y="6.5" width="17" height="11" rx="1"/>',
    fib: '<path d="M3 5h18M3 10h18M3 14h18M3 19h18"/>',
    chan: '<path d="M3 16 21 6M3 20 21 10"/>',
    pos: '<rect x="3.5" y="4.5" width="17" height="6" rx="1"/><rect x="3.5" y="13.5" width="17" height="6" rx="1"/><path d="M3 12h18"/>',
    ruler: '<path d="m4 14 6-6"/><path d="M3 17 17 3l4 4L7 21z"/><path d="m8 10 2 2m2-6 2 2"/>',
    text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    brush: '<path d="M3 21c3 0 4-2 4-4a3 3 0 1 0-4 4Z"/><path d="M9 15 20.5 3.5a1.8 1.8 0 0 1 2.5 2.5L11.5 17.5"/>',
    magnet: '<path d="M6 3v9a6 6 0 0 0 12 0V3"/><path d="M6 8h4M14 8h4"/>',
    undo: '<path d="M3 8h11a6 6 0 0 1 0 12H8"/><path d="m3 8 4-4M3 8l4 4"/>',
    trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>'
  };

  /* Ordered exactly as they are used: navigate, select, then the lines, then
     the areas, then the analytical tools, then the annotations. */
  var TOOLS = [
    { t: "pan", tip: "Pan & zoom", icon: I.pan },
    { t: "sel", tip: "Select & move", icon: I.sel },
    { rule: 1 },
    { t: "trend", tip: "Trend line", icon: I.trend, n: 2 },
    { t: "ray", tip: "Ray", icon: I.ray, n: 2 },
    { t: "xline", tip: "Extended line", icon: I.xline, n: 2 },
    { t: "hline", tip: "Horizontal line", icon: I.hline, n: 1 },
    { t: "vline", tip: "Vertical line", icon: I.vline, n: 1 },
    { rule: 1 },
    { t: "rect", tip: "Rectangle", icon: I.rect, n: 2 },
    { t: "chan", tip: "Parallel channel", icon: I.chan, n: 3 },
    { t: "fib", tip: "Fib retracement", icon: I.fib, n: 2 },
    { rule: 1 },
    { t: "pos", tip: "Risk / reward box", icon: I.pos, n: 2 },
    { t: "ruler", tip: "Measure", icon: I.ruler, n: 2 },
    { rule: 1 },
    { t: "text", tip: "Note", icon: I.text, n: 1 },
    { t: "brush", tip: "Freehand", icon: I.brush, n: 0 }
  ];

  /* Written per tool. A generated string ("tap 2 points") is technically true
     and tells nobody what they are about to get. */
  var HINT = {
    trend: "Tap the start of the line, then the end.",
    ray: "Tap two points — the line runs on past the second one.",
    xline: "Tap two points — the line runs both ways forever.",
    hline: "Tap the price level to mark.",
    vline: "Tap the candle to mark.",
    rect: "Tap two opposite corners of the box.",
    chan: "Tap the two ends of the base line, then a third point to set the width.",
    fib: "Tap the swing low, then the swing high. Or the reverse, for a fall.",
    pos: "Tap your entry, then your stop. The target lands at 2R — drag it to change.",
    ruler: "Tap where you start measuring, then where you finish.",
    text: "Tap where the note should sit.",
    brush: "Draw with your finger or the mouse held down."
  };

  var PALETTE = ["#B08D2E", "#1F5D45", "#8E2F2A", "#2E5E8E", "#16130E"];
  var FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618];

  /* ── markup ────────────────────────────────────────────────────────────── */

  function railHTML() {
    return TOOLS.map(function (t) {
      if (t.rule) return "<hr>";
      return '<button class="cw-t" type="button" data-t="' + t.t + '" data-tip="' + t.tip +
             '" aria-label="' + t.tip + '"><svg viewBox="0 0 24 24">' + t.icon + "</svg></button>";
    }).join("");
  }

  function viewHTML() {
    return '' +
'<p class="lede" style="margin-bottom:18px">Full-screen charting with drawings that stay put. Anchors are stored against the date and price you clicked, so a trendline drawn on the 15-minute chart is still on the same two candles when you switch to daily. Everything you draw is saved in this browser, per symbol.</p>' +
'<div class="cw" id="cw">' +
  '<div class="cw-tape">' +
    '<div class="cw-sym"><input id="cw-in" placeholder="SYMBOL" spellcheck="false" autocomplete="off" aria-label="Symbol"><button id="cw-go" type="button">Load</button></div>' +
    '<span class="cw-px" id="cw-px">—</span>' +
    '<span class="cw-chg" id="cw-chg"></span>' +
    '<span class="cw-live" id="cw-live"><i></i><span>Delayed</span></span>' +
    '<div class="cw-tfs" id="cw-tfs">' +
      TFS.map(function (f) { return '<button type="button" data-r="' + f.k + '">' + f.lab + "</button>"; }).join("") +
    '</div>' +
  '</div>' +
  '<div class="cw-rail" id="cw-rail">' + railHTML() +
    '<hr>' +
    '<button class="cw-t" type="button" data-a="magnet" data-tip="Snap to candle" aria-label="Snap to candle"><svg viewBox="0 0 24 24">' + I.magnet + '</svg></button>' +
    '<button class="cw-t" type="button" data-a="undo" data-tip="Undo" aria-label="Undo"><svg viewBox="0 0 24 24">' + I.undo + '</svg></button>' +
    '<button class="cw-t" type="button" data-a="clear" data-tip="Clear all" aria-label="Clear all drawings"><svg viewBox="0 0 24 24">' + I.trash + '</svg></button>' +
  '</div>' +
  '<div class="cw-pane">' +
    '<div class="cw-price" id="cw-price">' +
      '<div class="cw-legend" id="cw-legend"></div>' +
      '<canvas class="cw-canvas" id="cw-cv"></canvas>' +
      '<div class="cw-msg on" id="cw-msg">Type a symbol to begin</div>' +
      '<div class="cw-insp" id="cw-insp">' +
        '<span class="lab">Style</span>' +
        PALETTE.map(function (c) { return '<button class="cw-sw" type="button" data-c="' + c + '" style="background:' + c + '" aria-label="Colour ' + c + '"></button>'; }).join("") +
        '<button class="cw-wd" type="button" data-w="1" aria-label="Thin"><i style="height:1px"></i></button>' +
        '<button class="cw-wd" type="button" data-w="2" aria-label="Medium"><i style="height:2px"></i></button>' +
        '<button class="cw-wd" type="button" data-w="3" aria-label="Thick"><i style="height:3px"></i></button>' +
        '<button class="cw-del" type="button" id="cw-del" aria-label="Delete drawing"><svg viewBox="0 0 24 24">' + I.trash + '</svg></button>' +
      '</div>' +
    '</div>' +
    '<div class="cw-sub" id="cw-sub"></div>' +
  '</div>' +
  '<div class="cw-foot">' +
    '<button class="cw-chip on" type="button" data-i="ma">EMA 20/50/200</button>' +
    '<button class="cw-chip" type="button" data-i="bb">Bollinger</button>' +
    '<button class="cw-chip" type="button" data-i="vwap">VWAP</button>' +
    '<button class="cw-chip on" type="button" data-i="vol">Volume</button>' +
    '<button class="cw-chip" type="button" data-i="rsi">RSI 14</button>' +
    '<button class="cw-chip" type="button" data-i="macd">MACD</button>' +
    '<button class="cw-chip" type="button" data-i="png">Save PNG</button>' +
    '<span class="cw-note" id="cw-note"></span>' +
  '</div>' +
'</div>' +
'<p class="disc" style="margin-top:20px">Drawings are yours alone — they never leave this browser and are not part of any score. A line on a chart is a hypothesis you have drawn, not evidence the engine has found. The Screener tab is where the evidence lives.</p>';
  }

  /* ── indicator maths ───────────────────────────────────────────────────── */

  function ema(v, n) {
    var k = 2 / (n + 1), out = new Array(v.length), prev = null;
    for (var i = 0; i < v.length; i++) {
      if (v[i] == null) { out[i] = null; continue; }
      prev = prev == null ? v[i] : v[i] * k + prev * (1 - k);
      out[i] = i >= n - 1 ? prev : null;
    }
    return out;
  }
  function sma(v, n) {
    var out = new Array(v.length), s = 0;
    for (var i = 0; i < v.length; i++) {
      s += v[i];
      if (i >= n) s -= v[i - n];
      out[i] = i >= n - 1 ? s / n : null;
    }
    return out;
  }
  function boll(v, n, k) {
    var m = sma(v, n), up = [], lo = [];
    for (var i = 0; i < v.length; i++) {
      if (m[i] == null) { up[i] = lo[i] = null; continue; }
      var s = 0;
      for (var j = i - n + 1; j <= i; j++) s += Math.pow(v[j] - m[i], 2);
      var sd = Math.sqrt(s / n);
      up[i] = m[i] + k * sd; lo[i] = m[i] - k * sd;
    }
    return { mid: m, up: up, lo: lo };
  }
  function rsi(v, n) {
    var out = new Array(v.length).fill(null), g = 0, l = 0;
    for (var i = 1; i < v.length; i++) {
      var d = v[i] - v[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
      if (i <= n) { g += up; l += dn; if (i === n) { g /= n; l /= n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); } }
      else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); }
    }
    return out;
  }
  function macd(v) {
    var f = ema(v, 12), s = ema(v, 26), line = [], i;
    for (i = 0; i < v.length; i++) line[i] = (f[i] == null || s[i] == null) ? null : f[i] - s[i];
    var seed = line.map(function (x) { return x == null ? 0 : x; });
    var sig = ema(seed, 9), hist = [];
    for (i = 0; i < v.length; i++) hist[i] = (line[i] == null || sig[i] == null) ? null : line[i] - sig[i];
    return { line: line, sig: sig, hist: hist };
  }
  /* VWAP resets at each session boundary, which for intraday data means each
     new calendar day in IST. On daily bars it is meaningless and is skipped. */
  function vwap(rows) {
    var out = [], cumPV = 0, cumV = 0, day = null;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var d = new Date((r.time + 19800) * 1000).getUTCDate();
      if (d !== day) { day = d; cumPV = 0; cumV = 0; }
      var tp = (r.high + r.low + r.close) / 3, vv = r.volume || 0;
      cumPV += tp * vv; cumV += vv;
      out[i] = cumV ? cumPV / cumV : null;
    }
    return out;
  }

  /* ══════════════════════════════════════════════════════════════════════
     THE WORKSPACE
     ══════════════════════════════════════════════════════════════════════ */

  function Workspace() {
    var W = {
      chart: null, cs: null, vs: null, sub: null, subS: null, subH: null,
      e20: null, e50: null, e200: null, bu: null, bl: null, vw: null,
      sym: "", range: "1D", rows: [], times: [], barSec: 86400,
      req: 0, mode: "pan", tool: null, pending: [], preview: null,
      drawings: [], sel: null, dragging: null, undo: [],
      magnet: false, color: PALETTE[0], width: 2,
      ind: { ma: true, bb: false, vwap: false, vol: true, rsi: false, macd: false },
      es: null, poll: null, refresh: null, lastTick: 0, lastPx: null,
      ptrs: {}, pinch: null, hover: null, sigTimer: null, sig: ""
    };

    var box, cv, ctx, msgEl, noteEl, legEl, inspEl, pxEl, chgEl, liveEl;

    /* ---- theme ---------------------------------------------------------- */

    function theme() {
      var L = window.LightweightCharts;
      return {
        layout: {
          background: { type: "solid", color: tok("--surface", "#ffffff") },
          textColor: tok("--ink-2", "#4A443A"),
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10
        },
        grid: { vertLines: { color: tok("--rule-2", "#EBE6DC") }, horzLines: { color: tok("--rule-2", "#EBE6DC") } },
        /* minimumWidth pins the axis gutter. Without it the RSI pane (values
           0–100) draws a narrower price scale than the price pane (values in
           thousands), the two panes end at different x, and every drawing sits
           a few pixels off the candle it belongs to. */
        rightPriceScale: {
          borderColor: tok("--rule", "#DDD6C9"),
          scaleMargins: { top: 0.08, bottom: 0.24 },
          minimumWidth: 64
        },
        timeScale: {
          borderColor: tok("--rule", "#DDD6C9"), timeVisible: true,
          secondsVisible: false, rightOffset: 8, barSpacing: 8
        },
        crosshair: {
          mode: L.CrosshairMode.Normal,
          vertLine: { color: tok("--gold", "#B08D2E"), width: 1, style: 2, labelBackgroundColor: tok("--ink", "#16130E") },
          horzLine: { color: tok("--gold", "#B08D2E"), width: 1, style: 2, labelBackgroundColor: tok("--ink", "#16130E") }
        },
        handleScroll: true, handleScale: true
      };
    }

    /* ---- geometry -------------------------------------------------------
       Anchors are stored as {t, p}. At render time t becomes a fractional
       logical index by interpolating the loaded candle times, and that index
       becomes an x coordinate by calibrating against the two ends of the
       visible range. Both directions extrapolate cleanly past the last bar,
       which is what lets a ray run into empty space on the right. */

    function tToL(t) {
      var a = W.times, n = a.length;
      if (!n) return 0;
      if (t <= a[0]) return (t - a[0]) / W.barSec;
      if (t >= a[n - 1]) return (n - 1) + (t - a[n - 1]) / W.barSec;
      var lo = 0, hi = n - 1, m;
      while (hi - lo > 1) { m = (lo + hi) >> 1; if (a[m] <= t) lo = m; else hi = m; }
      var span = a[hi] - a[lo] || 1;
      return lo + (t - a[lo]) / span;
    }
    function lToT(l) {
      var a = W.times, n = a.length;
      if (!n) return 0;
      if (l <= 0) return Math.round(a[0] + l * W.barSec);
      if (l >= n - 1) return Math.round(a[n - 1] + (l - (n - 1)) * W.barSec);
      var i = Math.floor(l), f = l - i;
      return Math.round(a[i] + f * (a[i + 1] - a[i]));
    }

    function geo() {
      if (!W.chart || !W.cs) return null;
      var ts = W.chart.timeScale(), vr = ts.getVisibleLogicalRange();
      if (!vr) return null;
      var x0 = ts.logicalToCoordinate(vr.from), x1 = ts.logicalToCoordinate(vr.to);
      if (x0 == null || x1 == null || x1 === x0) return null;
      var k = (x1 - x0) / (vr.to - vr.from);
      return {
        from: vr.from, to: vr.to, k: k,
        w: ts.width(), h: Math.max(10, box.clientHeight - ts.height()),
        x: function (l) { return x0 + (l - vr.from) * k; },
        l: function (x) { return vr.from + (x - x0) / k; }
      };
    }
    function X(g, t) { return g.x(tToL(t)); }
    function Y(p) { var y = W.cs.priceToCoordinate(p); return y == null ? null : y; }
    function pAt(y) { var p = W.cs.coordinateToPrice(y); return p == null ? null : p; }
    function tAt(g, x) { return lToT(g.l(x)); }

    /* Magnet: snap the price to the nearest of the four values on the nearest
       candle. Traders anchor to highs and lows, not to wherever the cursor
       happened to land. */
    function snap(t, p) {
      if (!W.magnet || !W.rows.length) return { t: t, p: p };
      var i = Math.round(tToL(t));
      i = Math.max(0, Math.min(W.rows.length - 1, i));
      var r = W.rows[i], best = r.close, bd = Infinity;
      [r.open, r.high, r.low, r.close].forEach(function (v) {
        var d = Math.abs(v - p); if (d < bd) { bd = d; best = v; }
      });
      return { t: r.time, p: best };
    }

    /* ---- drawing model -------------------------------------------------- */

    function key() { return "altaha.charts.v1." + (W.sym || "_"); }
    function save() {
      try { localStorage.setItem(key(), JSON.stringify(W.drawings)); } catch (e) {}
    }
    function load() {
      W.drawings = [];
      try {
        var raw = localStorage.getItem(key());
        if (raw) W.drawings = JSON.parse(raw) || [];
      } catch (e) { W.drawings = []; }
      W.sel = null; W.undo = [];
    }
    function push() {
      W.undo.push(JSON.stringify(W.drawings));
      if (W.undo.length > 60) W.undo.shift();
    }
    function undo() {
      if (!W.undo.length) return;
      W.drawings = JSON.parse(W.undo.pop());
      W.sel = null; save(); inspector(); render();
    }

    /* ---- rendering ------------------------------------------------------ */

    function sizeCanvas() {
      var dpr = window.devicePixelRatio || 1;
      var w = box.clientWidth, h = box.clientHeight;
      if (!w || !h) return false;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
        cv.style.width = w + "px"; cv.style.height = h + "px";
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return true;
    }

    var raf = null;
    function render() {
      if (raf) return;
      raf = requestAnimationFrame(function () { raf = null; paint(); });
    }

    function paint() {
      if (!ctx || !sizeCanvas()) return;
      ctx.clearRect(0, 0, cv.width, cv.height);
      var g = geo();
      if (!g) return;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, g.w, g.h); ctx.clip();
      W.drawings.forEach(function (d) { shape(d, g, d === W.sel); });
      if (W.preview) shape(W.preview, g, false, true);
      ctx.restore();
    }

    function stroke(color, width, dash) {
      ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.setLineDash(dash || []); ctx.lineCap = "round"; ctx.lineJoin = "round";
    }
    function label(text, x, y, bg, fg) {
      ctx.font = "500 10px 'IBM Plex Mono', monospace";
      var w = ctx.measureText(text).width + 10;
      ctx.fillStyle = bg; ctx.globalAlpha = 0.92;
      ctx.fillRect(x, y - 8, w, 16);
      ctx.globalAlpha = 1; ctx.fillStyle = fg;
      ctx.fillText(text, x + 5, y + 3.5);
    }
    function handles(pts) {
      ctx.fillStyle = tok("--surface", "#fff");
      ctx.strokeStyle = tok("--gold", "#B08D2E");
      ctx.lineWidth = 1.5; ctx.setLineDash([]);
      pts.forEach(function (q) {
        if (q.x == null || q.y == null) return;
        ctx.beginPath();
        ctx.rect(q.x - HANDLE, q.y - HANDLE, HANDLE * 2, HANDLE * 2);
        ctx.fill(); ctx.stroke();
      });
    }

    /* Every shape resolves its anchors to pixels first, then draws. Returning
       the pixel points lets the hit-tester reuse exactly the same geometry
       rather than reimplement it — the classic source of "the line is not
       where I click" bugs. */
    function pix(d, g) {
      return d.pts.map(function (a) {
        var y = Y(a.p);
        return { x: X(g, a.t), y: y == null ? null : y };
      });
    }

    function shape(d, g, selected, ghost) {
      var P = pix(d, g);
      if (!P.length || P[0].x == null || P[0].y == null) return;
      var col = d.color || W.color, wd = d.width || W.width;
      ctx.globalAlpha = ghost ? 0.6 : 1;

      if (d.type === "hline") {
        stroke(col, wd, [5, 4]);
        ctx.beginPath(); ctx.moveTo(0, P[0].y); ctx.lineTo(g.w, P[0].y); ctx.stroke();
        label(fmt(d.pts[0].p), 4, P[0].y - 10, col, "#fff");
      } else if (d.type === "vline") {
        stroke(col, wd, [5, 4]);
        ctx.beginPath(); ctx.moveTo(P[0].x, 0); ctx.lineTo(P[0].x, g.h); ctx.stroke();
      } else if (d.type === "text") {
        ctx.font = "500 12px 'Inter', system-ui, sans-serif";
        var t = d.text || "Note";
        var tw = ctx.measureText(t).width;
        ctx.fillStyle = col; ctx.globalAlpha = ghost ? 0.5 : 0.12;
        ctx.fillRect(P[0].x - 5, P[0].y - 12, tw + 10, 20);
        ctx.globalAlpha = ghost ? 0.6 : 1;
        ctx.fillStyle = col; ctx.fillText(t, P[0].x, P[0].y + 3);
      } else if (d.type === "brush") {
        stroke(col, wd);
        ctx.beginPath();
        P.forEach(function (q, i) { if (q.y == null) return; i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y); });
        ctx.stroke();
      } else if (P.length >= 2 && P[1].x != null && P[1].y != null) {
        var a = P[0], b = P[1];

        if (d.type === "trend" || d.type === "ray" || d.type === "xline") {
          var A = a, B = b;
          if (d.type !== "trend") {
            var dx = b.x - a.x, dy = b.y - a.y;
            var len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len, R = 6000;
            B = { x: b.x + ux * R, y: b.y + uy * R };
            if (d.type === "xline") A = { x: a.x - ux * R, y: a.y - uy * R };
          }
          stroke(col, wd);
          ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke();
        } else if (d.type === "rect") {
          stroke(col, wd);
          ctx.fillStyle = col; ctx.globalAlpha = ghost ? 0.06 : 0.09;
          ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
          ctx.globalAlpha = ghost ? 0.6 : 1;
          ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
        } else if (d.type === "fib") {
          var p0 = d.pts[0].p, p1 = d.pts[1].p, dp = p1 - p0;
          var xl = Math.min(a.x, b.x), xr = Math.max(a.x, b.x);
          FIB.forEach(function (lv, i) {
            var pv = p0 + dp * lv, yy = Y(pv);
            if (yy == null) return;
            stroke(col, lv === 0 || lv === 1 ? wd : 1, lv === 0 || lv === 1 ? [] : [4, 4]);
            ctx.globalAlpha = ghost ? 0.55 : (lv === 0 || lv === 1 ? 1 : 0.75);
            ctx.beginPath(); ctx.moveTo(xl, yy); ctx.lineTo(Math.max(xr, g.w), yy); ctx.stroke();
            ctx.globalAlpha = 1;
            ctx.font = "500 9.5px 'IBM Plex Mono', monospace";
            ctx.fillStyle = col;
            ctx.fillText((lv * 100).toFixed(1).replace(/\.0$/, "") + "%  " + fmt(pv), xl + 4, yy - 3);
          });
          ctx.globalAlpha = ghost ? 0.6 : 1;
        } else if (d.type === "chan") {
          var off = 0;
          if (d.pts[2]) {
            var y3 = Y(d.pts[2].p), x3 = X(g, d.pts[2].t);
            var m = (b.y - a.y) / ((b.x - a.x) || 1);
            off = y3 - (a.y + m * (x3 - a.x));
          }
          stroke(col, wd);
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(a.x, a.y + off); ctx.lineTo(b.x, b.y + off); ctx.stroke();
          ctx.fillStyle = col; ctx.globalAlpha = ghost ? 0.05 : 0.07;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
          ctx.lineTo(b.x, b.y + off); ctx.lineTo(a.x, a.y + off);
          ctx.closePath(); ctx.fill();
          ctx.globalAlpha = ghost ? 0.6 : 1;
        } else if (d.type === "ruler") {
          var e = d.pts[0].p, f = d.pts[1].p;
          var pct = e ? (f - e) / e * 100 : 0;
          var bars = Math.round(Math.abs(tToL(d.pts[1].t) - tToL(d.pts[0].t)));
          var upd = f >= e;
          var kc = upd ? tok("--pass", "#1F5D45") : tok("--fail", "#8E2F2A");
          ctx.fillStyle = kc; ctx.globalAlpha = 0.10;
          ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
          ctx.globalAlpha = 1;
          stroke(kc, 1.5, [4, 3]);
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          label((pct >= 0 ? "+" : "") + pct.toFixed(2) + "%  ·  " + fmt(f - e) + "  ·  " + bars + " bars",
                Math.min(a.x, b.x) + 6, Math.min(a.y, b.y) - 6, kc, "#fff");
        } else if (d.type === "pos") {
          var entry = d.pts[0].p, stop = d.pts[1].p;
          var tgt = d.pts[2] ? d.pts[2].p : entry + (entry - stop) * 2;
          var yE = Y(entry), yS = Y(stop), yT = Y(tgt);
          if (yE == null || yS == null || yT == null) return;
          var xL = Math.min(a.x, b.x), xR = Math.max(a.x, b.x);
          if (xR - xL < 40) xR = xL + 90;
          var gp = tok("--pass", "#1F5D45"), bd = tok("--fail", "#8E2F2A");
          ctx.fillStyle = bd; ctx.globalAlpha = 0.13;
          ctx.fillRect(xL, Math.min(yE, yS), xR - xL, Math.abs(yS - yE));
          ctx.fillStyle = gp; ctx.globalAlpha = 0.13;
          ctx.fillRect(xL, Math.min(yE, yT), xR - xL, Math.abs(yT - yE));
          ctx.globalAlpha = 1;
          stroke(tok("--ink", "#16130E"), 1.2);
          ctx.beginPath(); ctx.moveTo(xL, yE); ctx.lineTo(xR, yE); ctx.stroke();
          var risk = Math.abs(entry - stop), rew = Math.abs(tgt - entry);
          label("Entry " + fmt(entry), xL + 4, yE - 10, tok("--ink", "#16130E"), "#fff");
          label("Stop " + fmt(stop) + "  (−" + (entry ? (risk / entry * 100).toFixed(2) : "0") + "%)", xL + 4, yS + (yS > yE ? 12 : -10), bd, "#fff");
          label("Target " + fmt(tgt) + "  ·  " + (risk ? (rew / risk).toFixed(2) : "—") + "R", xL + 4, yT + (yT > yE ? 12 : -10), gp, "#fff");
        }
      }
      ctx.globalAlpha = 1;
      if (selected) handles(anchorPix(d, g));
    }

    /* Which points get a draggable handle. For most shapes it is the anchors
       themselves; the position box also exposes its target. */
    function anchorPix(d, g) { return pix(d, g); }

    /* ---- hit testing ---------------------------------------------------- */

    function distSeg(px, py, x1, y1, x2, y2) {
      var dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
      if (!l2) return Math.hypot(px - x1, py - y1);
      var t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2));
      return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    }

    function hit(px, py) {
      var g = geo(); if (!g) return null;
      for (var i = W.drawings.length - 1; i >= 0; i--) {
        var d = W.drawings[i], P = pix(d, g);
        if (!P.length || P[0].y == null) continue;

        for (var h = 0; h < P.length; h++) {
          if (P[h].y != null && Math.abs(px - P[h].x) <= HANDLE + 3 && Math.abs(py - P[h].y) <= HANDLE + 3)
            return { d: d, handle: h };
        }
        if (d.type === "hline") { if (Math.abs(py - P[0].y) <= TOL) return { d: d, handle: null }; }
        else if (d.type === "vline") { if (Math.abs(px - P[0].x) <= TOL) return { d: d, handle: null }; }
        else if (d.type === "text") { if (Math.abs(px - P[0].x) < 90 && Math.abs(py - P[0].y) < 14) return { d: d, handle: null }; }
        else if (d.type === "brush") {
          for (var j = 1; j < P.length; j++)
            if (P[j].y != null && P[j - 1].y != null && distSeg(px, py, P[j - 1].x, P[j - 1].y, P[j].x, P[j].y) <= TOL)
              return { d: d, handle: null };
        } else if (P.length >= 2 && P[1].y != null) {
          var a = P[0], b = P[1];
          if (d.type === "rect" || d.type === "ruler" || d.type === "pos" || d.type === "fib") {
            var xl = Math.min(a.x, b.x) - TOL, xr = Math.max(a.x, b.x) + TOL;
            var yt = Math.min(a.y, b.y) - TOL, yb = Math.max(a.y, b.y) + TOL;
            if (px >= xl && px <= xr && py >= yt && py <= yb) return { d: d, handle: null };
          } else if (distSeg(px, py, a.x, a.y, b.x, b.y) <= TOL) return { d: d, handle: null };
        }
      }
      return null;
    }

    /* ---- interaction ---------------------------------------------------- */

    function local(e) {
      var r = cv.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function anchorAt(pt) {
      var g = geo(); if (!g) return null;
      var p = pAt(pt.y); if (p == null) return null;
      return snap(tAt(g, pt.x), p);
    }

    function setMode(m, tool) {
      W.mode = m; W.tool = tool || null; W.pending = []; W.preview = null;
      cv.classList.toggle("live", m !== "pan");
      cv.classList.toggle("grab", m === "sel");
      $("cw-rail").querySelectorAll(".cw-t[data-t]").forEach(function (b) {
        b.classList.toggle("on", b.dataset.t === (m === "pan" ? "pan" : (tool || "sel")));
      });
      note(m === "pan" ? "Scroll to zoom, drag to pan. Double-click fits everything back on screen."
        : m === "sel" ? "Tap a drawing to select it. Drag the body to move, a corner to reshape."
        : (HINT[tool] || "Tap the chart to place this.") + " Esc cancels.");
      render();
    }
    function toolDef(t) {
      for (var i = 0; i < TOOLS.length; i++) if (TOOLS[i].t === t) return TOOLS[i];
      return {};
    }

    function onDown(e) {
      cv.setPointerCapture && cv.setPointerCapture(e.pointerId);
      W.ptrs[e.pointerId] = local(e);
      if (Object.keys(W.ptrs).length === 2) { startPinch(); return; }
      var pt = local(e);

      /* In pan mode the canvas is click-through except where a drawing sits
         under the cursor, so reaching here at all means something was hit. */
      if (W.mode === "pan") {
        var hp = hit(pt.x, pt.y);
        if (!hp) return;
        W.sel = hp.d;
        W.dragging = { h: hp.handle, last: pt, moved: false };
        inspector(); render();
        return;
      }

      if (W.mode === "sel") {
        var h = hit(pt.x, pt.y);
        if (h) {
          W.sel = h.d;
          W.dragging = { h: h.handle, last: pt, moved: false };
          inspector(); render();
        } else {
          W.sel = null; inspector();
          W.dragging = { pan: true, last: pt };
          cv.classList.add("grabbing");
          render();
        }
        return;
      }

      if (W.tool === "brush") {
        var a0 = anchorAt(pt); if (!a0) return;
        W.preview = { id: uid(), type: "brush", pts: [a0], color: W.color, width: W.width };
        W.dragging = { brush: true };
        return;
      }

      var a = anchorAt(pt); if (!a) return;
      W.pending.push(a);
      var need = toolDef(W.tool).n || 2;

      if (W.tool === "pos" && W.pending.length === 2) {
        var entry = W.pending[0].p, stop = W.pending[1].p;
        commit({ type: "pos", pts: [W.pending[0], W.pending[1], { t: W.pending[1].t, p: entry + (entry - stop) * 2 }] });
        return;
      }
      if (W.tool === "chan" && W.pending.length === 3) { commit({ type: "chan", pts: W.pending.slice() }); return; }
      if (W.pending.length >= need && W.tool !== "chan") {
        var o = { type: W.tool, pts: W.pending.slice() };
        if (W.tool === "text") {
          var txt = window.prompt("Note text", "");
          if (!txt) { W.pending = []; W.preview = null; render(); return; }
          o.text = txt.slice(0, 60);
        }
        commit(o);
      }
    }

    function commit(o) {
      push();
      o.id = uid(); o.color = W.color; o.width = W.width;
      W.drawings.push(o);
      W.pending = []; W.preview = null;
      W.sel = o;
      save(); inspector();
      setMode("sel");
    }

    function onMove(e) {
      var pt = local(e);
      if (W.ptrs[e.pointerId]) W.ptrs[e.pointerId] = pt;
      if (W.pinch) { movePinch(); return; }

      if (W.dragging) {
        if (W.dragging.pan) {
          var g0 = geo();
          if (g0) {
            var dl = (pt.x - W.dragging.last.x) / g0.k;
            W.chart.timeScale().setVisibleLogicalRange({ from: g0.from - dl, to: g0.to - dl });
          }
          W.dragging.last = pt; render(); return;
        }
        if (W.dragging.brush) {
          var ab = anchorAt(pt);
          if (ab && W.preview) { W.preview.pts.push(ab); render(); }
          return;
        }
        var d = W.sel; if (!d) return;
        var a1 = anchorAt(pt); if (!a1) return;
        if (!W.dragging.moved) push();
        if (W.dragging.h != null) {
          d.pts[W.dragging.h] = a1;
        } else {
          var g1 = geo(); if (!g1) return;
          var dx = pt.x - W.dragging.last.x, dy = pt.y - W.dragging.last.y;
          d.pts = d.pts.map(function (q) {
            var y = Y(q.p); if (y == null) return q;
            var np = pAt(y + dy);
            return { t: lToT(tToL(q.t) + dx / g1.k), p: np == null ? q.p : np };
          });
          W.dragging.last = pt;
        }
        W.dragging.moved = true;
        render(); return;
      }

      /* In pan mode the canvas stays click-through until a drawing is under
         the cursor, which is what lets the chart keep its own pan and zoom. */
      if (W.mode === "pan") {
        var h = hit(pt.x, pt.y);
        cv.classList.toggle("live", !!h);
        W.hover = h;
        return;
      }

      /* Live preview of the shape being placed. */
      if (W.tool && W.pending.length) {
        var ap = anchorAt(pt); if (!ap) return;
        var pts = W.pending.concat([ap]);
        if (W.tool === "pos" && pts.length === 2) {
          pts = [pts[0], pts[1], { t: pts[1].t, p: pts[0].p + (pts[0].p - pts[1].p) * 2 }];
        }
        W.preview = { type: W.tool, pts: pts, color: W.color, width: W.width, text: "Note" };
        render();
      }
    }

    function onUp(e) {
      delete W.ptrs[e.pointerId];
      if (Object.keys(W.ptrs).length < 2) W.pinch = null;
      cv.classList.remove("grabbing");
      if (W.dragging && W.dragging.brush && W.preview && W.preview.pts.length > 2) {
        var o = W.preview; W.preview = null; W.dragging = null;
        commit({ type: "brush", pts: o.pts });
        return;
      }
      if (W.dragging && W.dragging.moved) save();
      W.dragging = null;
      render();
    }

    function onWheel(e) {
      if (W.mode === "pan") return;
      e.preventDefault();
      var g = geo(); if (!g) return;
      var pt = local(e), lc = g.l(pt.x), f = e.deltaY > 0 ? 1.12 : 0.89;
      var from = lc - (lc - g.from) * f, to = lc + (g.to - lc) * f;
      if (to - from < 8 || to - from > 5000) return;
      W.chart.timeScale().setVisibleLogicalRange({ from: from, to: to });
      render();
    }

    function startPinch() {
      var ids = Object.keys(W.ptrs);
      var g = geo(); if (!g) return;
      var a = W.ptrs[ids[0]], b = W.ptrs[ids[1]];
      W.pinch = { d0: Math.abs(a.x - b.x) || 1, from: g.from, to: g.to, cx: g.l((a.x + b.x) / 2) };
    }
    function movePinch() {
      var ids = Object.keys(W.ptrs); if (ids.length < 2) return;
      var a = W.ptrs[ids[0]], b = W.ptrs[ids[1]];
      var d = Math.abs(a.x - b.x) || 1, f = W.pinch.d0 / d;
      var from = W.pinch.cx - (W.pinch.cx - W.pinch.from) * f;
      var to = W.pinch.cx + (W.pinch.to - W.pinch.cx) * f;
      if (to - from < 8 || to - from > 5000) return;
      W.chart.timeScale().setVisibleLogicalRange({ from: from, to: to });
      render();
    }

    /* ---- inspector ------------------------------------------------------ */

    function inspector() {
      if (!W.sel) { inspEl.classList.remove("on"); return; }
      inspEl.classList.add("on");
      inspEl.querySelectorAll(".cw-sw").forEach(function (b) {
        b.classList.toggle("on", b.dataset.c === (W.sel.color || W.color));
      });
      inspEl.querySelectorAll(".cw-wd").forEach(function (b) {
        b.classList.toggle("on", +b.dataset.w === (W.sel.width || W.width));
      });
    }

    function del() {
      if (!W.sel) return;
      push();
      W.drawings = W.drawings.filter(function (d) { return d !== W.sel; });
      W.sel = null; save(); inspector(); render();
    }

    /* ---- data ----------------------------------------------------------- */

    function note(m) { noteEl.textContent = m; }
    function msg(m) {
      if (m) { msgEl.textContent = m; msgEl.classList.add("on"); }
      else msgEl.classList.remove("on");
    }

    function ensure() {
      if (W.chart) return true;
      if (typeof window.LightweightCharts === "undefined") return false;
      if (!box.clientWidth || !box.clientHeight) return false;
      W.chart = window.LightweightCharts.createChart(box, Object.assign(
        { width: box.clientWidth, height: box.clientHeight }, theme()));
      W.cs = W.chart.addCandlestickSeries({
        upColor: tok("--pass", "#1F5D45"), downColor: tok("--fail", "#8E2F2A"),
        borderUpColor: tok("--pass", "#1F5D45"), borderDownColor: tok("--fail", "#8E2F2A"),
        wickUpColor: tok("--pass", "#1F5D45"), wickDownColor: tok("--fail", "#8E2F2A")
      });
      W.vs = W.chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
      W.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      var mk = function (c, w) {
        return W.chart.addLineSeries({ color: c, lineWidth: w, priceLineVisible: false, lastValueVisible: false });
      };
      W.e20 = mk(tok("--gold", "#B08D2E"), 2);
      W.e50 = mk(tok("--ink-2", "#4A443A"), 1);
      W.e200 = mk(tok("--mute", "#8B8477"), 1);
      W.bu = mk(tok("--rule", "#DDD6C9"), 1);
      W.bl = mk(tok("--rule", "#DDD6C9"), 1);
      W.vw = mk("#2E5E8E", 1);

      W.chart.timeScale().subscribeVisibleLogicalRangeChange(function (r) {
        render();
        if (W.sub && r) { try { W.sub.timeScale().setVisibleLogicalRange(r); } catch (e) {} }
      });
      W.chart.subscribeCrosshairMove(legend);

      new ResizeObserver(function () {
        if (!W.chart) return;
        W.chart.applyOptions({ width: box.clientWidth, height: box.clientHeight });
        render();
      }).observe(box);

      /* A vertical drag on the price scale does not fire a logical range
         change, so drawings would lag behind the candles. A cheap signature
         poll catches it without a permanent rAF loop. */
      W.sigTimer = setInterval(function () {
        if (!W.chart || !W.rows.length) return;
        var y = W.cs.priceToCoordinate(W.rows[W.rows.length - 1].close);
        var g = geo();
        var s = (g ? g.from.toFixed(2) + "," + g.to.toFixed(2) : "") + "|" + y + "|" + box.clientHeight;
        if (s !== W.sig) { W.sig = s; render(); }
      }, 110);
      return true;
    }

    function legend(param) {
      if (!param || !param.time || !param.seriesData) { paintLegend(null); return; }
      paintLegend(param.seriesData.get(W.cs));
    }
    function paintLegend(c) {
      if (!c || c.open === undefined) {
        var last = W.rows[W.rows.length - 1];
        if (!last) { legEl.innerHTML = ""; return; }
        c = last;
      }
      var chg = c.open ? (c.close - c.open) / c.open * 100 : 0;
      var col = c.close >= c.open ? "var(--pass)" : "var(--fail)";
      legEl.innerHTML =
        "<b>" + esc(W.sym) + "</b> <span class='k'>" + esc(W.range) + "</span>&nbsp; " +
        "<span class='k'>O</span> " + fmt(c.open) + "&nbsp; <span class='k'>H</span> " + fmt(c.high) +
        "&nbsp; <span class='k'>L</span> " + fmt(c.low) + "&nbsp; <span class='k'>C</span> " +
        "<b style='color:" + col + "'>" + fmt(c.close) + "</b>&nbsp; " +
        "<span style='color:" + col + "'>" + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%</span>";
    }

    function indicators() {
      var closes = W.rows.map(function (r) { return r.close; });
      var t = W.rows.map(function (r) { return r.time; });
      var pair = function (arr) {
        var o = [];
        for (var i = 0; i < arr.length; i++) if (arr[i] != null) o.push({ time: t[i], value: +arr[i].toFixed(2) });
        return o;
      };
      W.e20.setData(pair(ema(closes, 20)));
      W.e50.setData(pair(ema(closes, 50)));
      W.e200.setData(pair(ema(closes, 200)));
      var b = boll(closes, 20, 2);
      W.bu.setData(pair(b.up)); W.bl.setData(pair(b.lo));
      var intraday = ["1m", "5m", "15m", "1H", "4H"].indexOf(W.range) >= 0;
      W.vw.setData(intraday ? pair(vwap(W.rows)) : []);
      applyInd();
      subPane();
    }

    function applyInd() {
      var v = W.ind;
      W.e20.applyOptions({ visible: v.ma }); W.e50.applyOptions({ visible: v.ma });
      W.e200.applyOptions({ visible: v.ma });
      W.bu.applyOptions({ visible: v.bb }); W.bl.applyOptions({ visible: v.bb });
      W.vw.applyOptions({ visible: v.vwap });
      W.vs.applyOptions({ visible: v.vol });
    }

    function subPane() {
      var host = $("cw-sub"), want = W.ind.rsi || W.ind.macd;
      host.classList.toggle("on", want);
      if (!want) {
        if (W.sub) { W.sub.remove(); W.sub = null; W.subS = null; W.subH = null; }
        return;
      }
      if (!W.sub) {
        W.sub = window.LightweightCharts.createChart(host, Object.assign(
          { width: host.clientWidth, height: host.clientHeight || 132 }, theme()));
        W.sub.timeScale().applyOptions({ visible: false });
        new ResizeObserver(function () {
          if (W.sub) W.sub.applyOptions({ width: host.clientWidth, height: host.clientHeight || 132 });
        }).observe(host);
      }
      if (W.subS) { try { W.sub.removeSeries(W.subS); } catch (e) {} W.subS = null; }
      if (W.subH) { try { W.sub.removeSeries(W.subH); } catch (e) {} W.subH = null; }

      var closes = W.rows.map(function (r) { return r.close; });
      var t = W.rows.map(function (r) { return r.time; });
      var pair = function (arr) {
        var o = []; for (var i = 0; i < arr.length; i++) if (arr[i] != null) o.push({ time: t[i], value: +arr[i].toFixed(3) });
        return o;
      };
      if (W.ind.rsi) {
        W.subS = W.sub.addLineSeries({ color: tok("--gold", "#B08D2E"), lineWidth: 2, priceLineVisible: false });
        W.subS.setData(pair(rsi(closes, 14)));
        [70, 30].forEach(function (lv) {
          W.subS.createPriceLine({ price: lv, color: tok("--rule", "#DDD6C9"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });
        });
      } else {
        var m = macd(closes);
        W.subH = W.sub.addHistogramSeries({ priceFormat: { type: "price", precision: 2 } });
        W.subH.setData(m.hist.map(function (v, i) {
          return v == null ? null : { time: t[i], value: +v.toFixed(3), color: v >= 0 ? tok("--pass", "#1F5D45") : tok("--fail", "#8E2F2A") };
        }).filter(Boolean));
        W.subS = W.sub.addLineSeries({ color: tok("--gold", "#B08D2E"), lineWidth: 2, priceLineVisible: false });
        W.subS.setData(pair(m.line));
      }
      var r = W.chart.timeScale().getVisibleLogicalRange();
      if (r) { try { W.sub.timeScale().setVisibleLogicalRange(r); } catch (e) {} }
    }

    function setPrice(px, prev) {
      if (px == null) { pxEl.textContent = "—"; return; }
      pxEl.textContent = "₹" + fmt(px);
      if (prev != null && px !== prev) {
        pxEl.classList.remove("up", "dn");
        void pxEl.offsetWidth;
        pxEl.classList.add(px > prev ? "up" : "dn");
      }
      var first = W.rows.length ? W.rows[0].open : null;
      if (first) {
        var c = (px - first) / first * 100;
        chgEl.textContent = (c >= 0 ? "▲ " : "▼ ") + Math.abs(c).toFixed(2) + "%";
        chgEl.className = "cw-chg " + (c >= 0 ? "up" : "dn");
      }
    }

    async function loadData(sym, range) {
      if (sym && sym !== W.sym) {
        save();
        W.sym = sym;
        load();
        $("cw-in").value = sym;
      }
      if (range) W.range = range;
      if (!W.sym) return;

      $("cw-tfs").querySelectorAll("button").forEach(function (b) {
        b.classList.toggle("on", b.dataset.r === W.range);
      });

      if (!ensure()) { requestAnimationFrame(function () { loadData(); }); return; }

      var req = ++W.req;
      msg("Loading " + W.sym + " " + W.range + "…");
      note("Fetching candles");
      try {
        var res = await fetch(API + "/chart?ticker=" + encodeURIComponent(W.sym) + "&range=" + encodeURIComponent(W.range));
        var d = await res.json();
        if (req !== W.req) return;
        if (!res.ok) {
          msg((d.detail || "Unavailable").slice(0, 160));
          liveEl.classList.remove("on");
          note("No data for this timeframe");
          return;
        }
        W.rows = (d.candles || []).filter(function (r) { return r[0] != null; }).map(function (r) {
          return { time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[9] || 0 };
        });
        if (!W.rows.length) { msg("No candles returned"); return; }
        W.times = W.rows.map(function (r) { return r.time; });
        var diffs = [];
        for (var i = 1; i < Math.min(W.times.length, 80); i++) diffs.push(W.times[i] - W.times[i - 1]);
        diffs.sort(function (a, b) { return a - b; });
        W.barSec = diffs[Math.floor(diffs.length / 2)] || 86400;

        W.cs.setData(W.rows);
        var prev = null;
        W.vs.setData(W.rows.map(function (r) {
          var c = (prev != null && r.close < prev) ? "rgba(142,47,42,.32)" : "rgba(31,93,69,.32)";
          prev = r.close;
          return { time: r.time, value: r.volume, color: c };
        }));
        indicators();
        W.chart.timeScale().fitContent();
        msg("");
        setPrice(d.last, null);
        W.lastPx = d.last;
        paintLegend(null);
        liveEl.classList.toggle("on", !!d.live);
        liveEl.querySelector("span").textContent = d.live ? "Live" : "Delayed";
        note(W.rows.length + " candles · " + (d.live ? "intraday via Dhan" : "daily feed") +
             " · " + W.drawings.length + " drawing" + (W.drawings.length === 1 ? "" : "s"));
        render();
        startLive();
        scheduleRefresh(!!d.live);
      } catch (e) {
        if (req === W.req) { msg("Chart unavailable — the engine may be waking up"); note("Retry in a moment"); }
      }
    }

    function scheduleRefresh(live) {
      if (W.refresh) { clearInterval(W.refresh); W.refresh = null; }
      if (!live) return;
      W.refresh = setInterval(function () {
        if (document.visibilityState !== "visible" || !marketOpen()) return;
        if (!$("view-charts") || $("view-charts").style.display === "none") return;
        loadData();
      }, 120000);
    }

    /* ---- live tape ------------------------------------------------------
       The single biggest reason the site reads as static: a chart that only
       redraws once a minute. Here the last candle is mutated in place from a
       quote every couple of seconds, so the wick grows while you watch. If the
       backend exposes /stream/quotes (see live.py) this rides an SSE stream
       instead of polling. */

    function stopLive() {
      if (W.es) { try { W.es.close(); } catch (e) {} W.es = null; }
      if (W.poll) { clearInterval(W.poll); W.poll = null; }
    }

    function applyTick(px) {
      if (!px || !W.rows.length) return;
      var last = W.rows[W.rows.length - 1];
      last.close = px;
      last.high = Math.max(last.high, px);
      last.low = Math.min(last.low, px);
      try { W.cs.update(last); } catch (e) {}
      setPrice(px, W.lastPx);
      W.lastPx = px;
      W.lastTick = Date.now();
      liveEl.classList.add("on");
      liveEl.querySelector("span").textContent = "Live";
      render();
    }

    function startLive() {
      stopLive();
      if (!W.sym) return;
      var sse = new EventSource(API + "/stream/quotes?tickers=" + encodeURIComponent(W.sym));
      var ok = false;
      sse.onmessage = function (ev) {
        ok = true;
        try {
          var d = JSON.parse(ev.data);
          var px = d.ltp != null ? d.ltp : (d[W.sym] && d[W.sym].ltp);
          if (px) applyTick(px);
        } catch (e) {}
      };
      sse.onerror = function () {
        try { sse.close(); } catch (e) {}
        W.es = null;
        if (!ok) startPoll();
      };
      W.es = sse;
      /* If the stream endpoint does not exist yet, fall back quickly rather
         than sitting silent. */
      setTimeout(function () { if (!ok) { stopLive(); startPoll(); } }, 4000);
    }

    function startPoll() {
      if (W.poll) clearInterval(W.poll);
      W.poll = setInterval(async function () {
        if (document.visibilityState !== "visible" || !marketOpen()) return;
        var v = $("view-charts");
        if (!v || v.style.display === "none") return;
        try {
          var r = await fetch(API + "/quote?ticker=" + encodeURIComponent(W.sym));
          if (!r.ok) return;
          var q = await r.json();
          if (q.ltp) applyTick(q.ltp);
        } catch (e) {}
      }, 3000);
    }

    /* Age of the last tick, so a frozen feed announces itself instead of
       pretending. An honest "stale 40s" beats a green dot that lies. */
    setInterval(function () {
      if (!W.lastTick) return;
      var age = Math.round((Date.now() - W.lastTick) / 1000);
      if (!marketOpen()) { liveEl.classList.remove("on"); liveEl.querySelector("span").textContent = "Closed"; return; }
      if (age > 25) { liveEl.classList.remove("on"); liveEl.querySelector("span").textContent = "Stale " + age + "s"; }
    }, 5000);

    /* ---- PNG ------------------------------------------------------------ */

    function png() {
      if (!W.chart) return;
      try {
        var base = W.chart.takeScreenshot();
        var out = document.createElement("canvas");
        out.width = base.width; out.height = base.height;
        var c = out.getContext("2d");
        c.drawImage(base, 0, 0);
        /* takeScreenshot returns a canvas sized in CSS pixels; the overlay is
           sized in device pixels. Scaling the source to the destination in one
           call keeps the drawings registered with the candles at any DPR. */
        c.drawImage(cv, 0, 0, cv.width, cv.height, 0, 0, base.width, base.height);
        c.font = "500 11px 'IBM Plex Mono', monospace";
        c.fillStyle = "rgba(0,0,0,.42)";
        c.fillText("altaha screener · " + W.sym + " · " + W.range, 10, base.height - 10);
        var a = document.createElement("a");
        a.href = out.toDataURL("image/png");
        a.download = W.sym + "-" + W.range + ".png";
        a.click();
        note("Saved " + a.download);
      } catch (e) { note("Could not export this chart"); }
    }

    /* ---- wiring --------------------------------------------------------- */

    function bind() {
      box = $("cw-price"); cv = $("cw-cv"); ctx = cv.getContext("2d");
      msgEl = $("cw-msg"); noteEl = $("cw-note"); legEl = $("cw-legend");
      inspEl = $("cw-insp"); pxEl = $("cw-px"); chgEl = $("cw-chg"); liveEl = $("cw-live");

      $("cw-go").addEventListener("click", go);
      $("cw-in").addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
      function go() {
        var v = $("cw-in").value.trim().toUpperCase().replace(".NS", "").replace(".BO", "");
        if (v) loadData(v, null);
      }

      $("cw-tfs").addEventListener("click", function (e) {
        var b = e.target.closest("button[data-r]"); if (b) loadData(null, b.dataset.r);
      });

      $("cw-rail").addEventListener("click", function (e) {
        var b = e.target.closest("button"); if (!b) return;
        if (b.dataset.t) { setMode(b.dataset.t === "pan" ? "pan" : (b.dataset.t === "sel" ? "sel" : "draw"), b.dataset.t === "pan" || b.dataset.t === "sel" ? null : b.dataset.t); return; }
        if (b.dataset.a === "magnet") { W.magnet = !W.magnet; b.classList.toggle("on", W.magnet); note(W.magnet ? "Snapping to candle open, high, low and close." : "Free placement."); }
        if (b.dataset.a === "undo") undo();
        if (b.dataset.a === "clear") {
          if (!W.drawings.length) return;
          if (!window.confirm("Remove all " + W.drawings.length + " drawings on " + W.sym + "?")) return;
          push(); W.drawings = []; W.sel = null; save(); inspector(); render();
        }
      });

      inspEl.addEventListener("click", function (e) {
        var b = e.target.closest("button"); if (!b || !W.sel) return;
        if (b.dataset.c) { push(); W.sel.color = W.color = b.dataset.c; }
        if (b.dataset.w) { push(); W.sel.width = W.width = +b.dataset.w; }
        if (b.id === "cw-del") { del(); return; }
        save(); inspector(); render();
      });

      document.querySelector("#view-charts .cw-foot").addEventListener("click", function (e) {
        var b = e.target.closest("button[data-i]"); if (!b) return;
        var k = b.dataset.i;
        if (k === "png") { png(); return; }
        if (k === "rsi" && !W.ind.rsi) W.ind.macd = false;
        if (k === "macd" && !W.ind.macd) W.ind.rsi = false;
        W.ind[k] = !W.ind[k];
        document.querySelectorAll("#view-charts .cw-foot .cw-chip[data-i]").forEach(function (c) {
          if (c.dataset.i !== "png") c.classList.toggle("on", !!W.ind[c.dataset.i]);
        });
        if (W.rows.length) { applyInd(); subPane(); }
      });

      cv.addEventListener("pointerdown", onDown);
      cv.addEventListener("pointermove", onMove);
      cv.addEventListener("pointerup", onUp);
      cv.addEventListener("pointercancel", onUp);
      cv.addEventListener("wheel", onWheel, { passive: false });
      cv.addEventListener("dblclick", function () {
        if (W.chart) W.chart.timeScale().fitContent();
      });
      /* Hover detection has to happen on the container, because the canvas is
         click-through until it knows there is something under the cursor. */
      box.addEventListener("pointermove", function (e) { if (W.mode === "pan" && !W.dragging) onMove(e); });
      box.addEventListener("pointerdown", function (e) {
        if (W.mode !== "pan" || W.dragging) return;
        var pt = local(e);
        if (!hit(pt.x, pt.y) && W.sel) { W.sel = null; inspector(); render(); }
      });

      document.addEventListener("keydown", function (e) {
        var v = $("view-charts");
        if (!v || v.style.display === "none") return;
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
        if (e.key === "Escape") { W.pending = []; W.preview = null; W.sel = null; inspector(); setMode("pan"); }
        else if (e.key === "Delete" || e.key === "Backspace") { if (W.sel) { e.preventDefault(); del(); } }
        else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
        else if (e.key.toLowerCase() === "t") setMode("draw", "trend");
        else if (e.key.toLowerCase() === "h") setMode("draw", "hline");
        else if (e.key.toLowerCase() === "f") setMode("draw", "fib");
        else if (e.key.toLowerCase() === "r") setMode("draw", "ruler");
        else if (e.key.toLowerCase() === "v") setMode("sel");
      });

      /* Theme flips are a full rebuild — lightweight-charts caches its colours
         and there is no cheaper way to recolour the candles. */
      new MutationObserver(function () {
        if (!W.chart) return;
        W.chart.applyOptions(theme());
        W.cs.applyOptions({
          upColor: tok("--pass"), downColor: tok("--fail"),
          borderUpColor: tok("--pass"), borderDownColor: tok("--fail"),
          wickUpColor: tok("--pass"), wickDownColor: tok("--fail")
        });
        if (W.sub) W.sub.applyOptions(theme());
        render();
      }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

      setMode("pan");
    }

    return {
      bind: bind,
      open: function (sym) {
        if (sym) { $("cw-in").value = sym; loadData(sym, W.range); }
        else if (!W.sym) {
          var seed = ($("tk") && $("tk").value.trim().toUpperCase()) || "RELIANCE";
          loadData(seed, W.range);
        } else if (W.chart) {
          W.chart.applyOptions({ width: box.clientWidth, height: box.clientHeight });
          render();
        }
      },
      close: function () { stopLive(); },
      sym: function () { return W.sym; }
    };
  }

  /* ══════════════════════════════════════════════════════════════════════
     MOUNTING — one script tag, no HTML edits
     ══════════════════════════════════════════════════════════════════════ */

  var WS = null;

  function showCharts() {
    document.querySelectorAll("div[id^='view-']").forEach(function (v) {
      v.style.display = v.id === "view-charts" ? "block" : "none";
    });
    document.querySelectorAll(".tabs .tab, .moreMenu button").forEach(function (b) {
      b.classList.remove("active"); b.setAttribute("aria-selected", "false");
    });
    var t = $("tab-charts");
    if (t) { t.classList.add("active"); t.setAttribute("aria-selected", "true"); }
    document.querySelectorAll(".mobnav button").forEach(function (b) {
      b.classList.toggle("on", b.dataset.proxy === "tab-charts");
    });
    if (typeof moveTabInk === "function") { try { moveTabInk("charts"); } catch (e) {} }
    if (WS) WS.open();
  }

  function hideCharts() {
    var v = $("view-charts");
    if (v) v.style.display = "none";
    var t = $("tab-charts");
    if (t) { t.classList.remove("active"); t.setAttribute("aria-selected", "false"); }
  }

  function mount() {
    var nav = document.querySelector(".tabs");
    var main = document.querySelector("main.wrap");
    if (!main) return;

    /* View container, placed after the Screener view so tab order matches
       reading order for a screen reader. */
    var view = document.createElement("div");
    view.id = "view-charts";
    view.style.display = "none";
    view.innerHTML = viewHTML();
    var anchor = $("view-live") || $("view-ideas") || main.firstElementChild;
    main.insertBefore(view, anchor ? anchor.nextSibling : null);

    /* Desktop tab, inserted right after Live — a chart belongs next to the
       real-time section, not buried behind More. */
    if (nav) {
      var btn = document.createElement("button");
      btn.className = "tab"; btn.id = "tab-charts"; btn.type = "button";
      btn.setAttribute("role", "tab"); btn.setAttribute("aria-selected", "false");
      btn.textContent = "Charts";
      var after = $("tab-live");
      if (after && after.parentNode === nav) nav.insertBefore(btn, after.nextSibling);
      else nav.appendChild(btn);
      btn.addEventListener("click", showCharts);
      /* Any other tab hides us again. Capture phase, so this runs before the
         page's own switchTab and there is never a frame with two views up. */
      nav.addEventListener("click", function (e) {
        var b = e.target.closest("button");
        if (b && b !== btn) hideCharts();
      }, true);
      var mm = $("moreMenu");
      if (mm) mm.addEventListener("click", hideCharts, true);
      if (typeof refreshSegsSoon === "function") { try { refreshSegsSoon(); } catch (e) {} }
    }

    /* Mobile bar. premium.js builds it from a hardcoded list, so the button is
       appended afterwards rather than by editing that file. */
    var tries = 0;
    var mobTimer = setInterval(function () {
      var inner = document.querySelector(".mobnav-inner");
      if (!inner) { if (++tries > 40) clearInterval(mobTimer); return; }
      clearInterval(mobTimer);
      if (inner.querySelector("[data-proxy='tab-charts']")) return;
      var b = document.createElement("button");
      b.type = "button"; b.dataset.proxy = "tab-charts";
      b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" ' +
        'stroke-linejoin="round" aria-hidden="true"><path d="M4 20V4"/><path d="M4 20h16"/>' +
        '<path d="M8 16V9M12 16V6M16 16v-4"/></svg><span>Charts</span>';
      b.addEventListener("click", function () {
        showCharts();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      var live = inner.querySelector("[data-proxy='tab-live']");
      if (live) inner.insertBefore(b, live.nextSibling); else inner.appendChild(b);
      inner.querySelectorAll("button").forEach(function (x) {
        if (x.dataset.proxy !== "tab-charts") x.addEventListener("click", hideCharts);
      });
    }, 120);

    WS = Workspace();
    WS.bind();

    /* Deep link: /?charts=RELIANCE opens the workspace on its own, which is
       what you want when sharing a chart from Instagram. */
    var q = new URLSearchParams(location.search).get("charts");
    if (q != null) {
      document.body.classList.add("chartsonly");
      showCharts();
      WS.open((q || "RELIANCE").trim().toUpperCase());
    }

    /* Hand-off from the Screener: clicking Full chart opens this tab on the
       symbol currently analysed rather than a second browser tab. */
    var fc = $("fullchartbtn");
    if (fc) {
      var clone = fc.cloneNode(true);
      fc.parentNode.replaceChild(clone, fc);
      clone.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var s = ($("tk") && $("tk").value.trim().toUpperCase()) || (WS && WS.sym());
        showCharts();
        if (s) WS.open(s);
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
