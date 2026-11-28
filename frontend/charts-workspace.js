/* ============================================================================
   Altaha Charts: the workspace
   ----------------------------------------------------------------------------
   The Charts tab. charts.js loads charts-math.js and then this file; this file
   builds its own view, its own tab and everything inside it.

   WHAT A READER CAN DO HERE
   - Eleven timeframes (1m to 1M) and eight chart types: candles, hollow
     candles, Heikin Ashi, bars, line, step line, area and baseline.
   - Forty-odd indicators from charts-math.js, any number of each, every one
     tunable, each RSI or MACD in a pane of its own that can be resized.
   - Over forty drawing tools in seven groups: lines, channels, Fibonacci and
     Gann, chart patterns, forecasting and measuring, shapes, and notes.
     Every drawing can be selected, moved, reshaped, recoloured, restyled,
     extended, locked, hidden, cloned, copied and pasted, put in front or
     behind, given text, and undone or redone.
   - Full screen, an object tree and a data window, compare symbols, log and
     percent scales, bar replay, price alerts on any horizontal line, go to a
     date, range presets, a context menu, keyboard shortcuts, image export.

   Drawings are anchored to TIME AND PRICE, not to pixels or bar numbers, so a
   trendline drawn on 1D still sits on the same two days on 1W. The model is
   plain JSON, one array per symbol in this browser:
     { id, type, pts:[{t,p}], color, width, style, fill, text, extL, extR,
       locked, hidden, alert, ... }
   Drawings saved by the earlier workspace (the same key, the same types) load
   unchanged.

   Every popup, menu and dialog is a child of #cw, never of <body>: in full
   screen only the element that went full screen is drawn, and a menu
   attached anywhere else would open where nobody can see it.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_CHARTS__) return;
  window.__ALTAHA_CHARTS__ = 1;

  var M = window.AltahaChartMath;
  if (!M) { console.error("[altaha-charts] charts-math.js did not load"); return; }

  /* ── plumbing ──────────────────────────────────────────────────────────── */

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  var $ = function (id) { return document.getElementById(id); };
  var IS_TOUCH = window.matchMedia && window.matchMedia("(hover:none)").matches;
  var TOL = IS_TOUCH ? 14 : 7;
  var HANDLE = IS_TOUCH ? 7 : 5;

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  /* A colour is a theme token, read at the moment it is drawn (theme.js), so
     the workspace is right in both themes and follows the toggle. A value
     that starts with "--" anywhere in this file or in charts-math.js is a
     token name; asColor() turns it into the colour it means now. */
  var Th = window.AltahaTheme;
  function tok(name) { return Th.color(name); }
  function asColor(c) { return typeof c === "string" && c.indexOf("--") === 0 ? tok(c) : c; }
  function alphaOf(c, a) { return Th.alpha(asColor(c), a); }
  /* <input type="color"> takes six hex digits and nothing else. */
  function hex6(c) { c = asColor(c); return /^#[0-9a-f]{6}$/i.test(c || "") ? c : tok("--text-muted"); }
  function ok(x) { return x != null && isFinite(x); }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function fmt(n, d) {
    if (!ok(n)) return "–";
    if (d == null) d = Math.abs(n) < 10 && n !== 0 ? 3 : 2;
    return Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtV(v) {
    if (!ok(v)) return "–";
    var a = Math.abs(v), s = v < 0 ? "-" : "";
    if (a >= 1e9) return s + (a / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return s + (a / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return s + (a / 1e3).toFixed(1) + "K";
    return s + Math.round(a);
  }
  function pctS(v) { return ok(v) ? (v >= 0 ? "+" : "") + v.toFixed(2) + "%" : "–"; }
  function uid() { return "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function sget(k, fb) {
    try { var v = localStorage.getItem(k); return v == null ? fb : JSON.parse(v); } catch (e) { return fb; }
  }
  function sset(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  /* Candle times are exchange wall-clock seconds written as UTC (see W.off for
     the one feed that is not), so formatting reads the UTC fields. */
  function fmtT(t, withTime) {
    if (!ok(t)) return "";
    var d = new Date((t + W.off) * 1000);
    var s = d.getUTCDate() + " " + MON[d.getUTCMonth()] + " '" + String(d.getUTCFullYear()).slice(2);
    if (withTime) s += " " + String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
    return s;
  }
  function span(sec) {
    sec = Math.abs(sec);
    var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.round(sec % 3600 / 60);
    if (d >= 7) return Math.floor(d / 7) + "w " + (d % 7) + "d";
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    return m + "m";
  }

  /* IST session window. The market pill on the page is trusted when present. */
  function marketOpen() {
    var mk = $("mkstatus");
    if (mk && mk.classList.contains("open")) return true;
    if (mk && (mk.classList.contains("closed") || mk.classList.contains("pre"))) return false;
    var n = new Date(Date.now() + (new Date().getTimezoneOffset() * 60000) + 19800000);
    if (n.getDay() === 0 || n.getDay() === 6) return false;
    var m = n.getHours() * 60 + n.getMinutes();
    return m >= 555 && m < 930;
  }

  /* ── timeframes and chart types ────────────────────────────────────────
     `fetch` is the range asked of /chart. `n` merges that many intraday bars
     into one; `month` folds daily bars into months. `pat` is what the
     patterns panel (patterns.js) is told, since /chart/patterns only knows
     the seven candle sizes the backend serves. Daily asks for "5Y", which
     is daily bars too, so a reader can scroll back as far as there is
     history instead of stopping at 400 sessions. */
  var TFS = [
    { k: "1m", fetch: "1m", pat: "1m", intra: 1 },
    { k: "3m", fetch: "1m", pat: "1m", n: 3, intra: 1 },
    { k: "5m", fetch: "5m", pat: "5m", intra: 1 },
    { k: "15m", fetch: "15m", pat: "15m", intra: 1 },
    { k: "30m", fetch: "15m", pat: "15m", n: 2, intra: 1 },
    { k: "1H", fetch: "1H", pat: "1H", intra: 1 },
    { k: "2H", fetch: "1H", pat: "1H", n: 2, intra: 1 },
    { k: "4H", fetch: "4H", pat: "4H", intra: 1 },
    { k: "1D", fetch: "5Y", pat: "1D" },
    { k: "1W", fetch: "1W", pat: "1W" },
    { k: "1M", fetch: "5Y", pat: "1W", month: true }
  ];
  function tfOf(k) { for (var i = 0; i < TFS.length; i++) if (TFS[i].k === k) return TFS[i]; return TFS[8]; }

  var TYPES = [
    { k: "candles", lab: "Candles" }, { k: "hollow", lab: "Hollow candles" }, { k: "ha", lab: "Heikin Ashi" },
    { k: "bars", lab: "Bars" }, { k: "line", lab: "Line" }, { k: "step", lab: "Step line" },
    { k: "area", lab: "Area" }, { k: "baseline", lab: "Baseline" }
  ];

  /* ── icons ─────────────────────────────────────────────────────────────── */

  var I = {
    cursor: '<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/><circle cx="12" cy="12" r="1"/>',
    eraser: '<path d="m7 20-3.6-3.6a2 2 0 0 1 0-2.8L13.2 3.8a2 2 0 0 1 2.8 0l4.2 4.2a2 2 0 0 1 0 2.8L10.4 20z"/><path d="M7 20h13M9 10.5l4.5 4.5"/>',
    trend: '<path d="M5 19 19 5"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/>',
    ray: '<path d="M4 19 21 6"/><circle cx="4" cy="19" r="2"/><circle cx="12" cy="13" r="2"/>',
    xline: '<path d="M2 21 22 3"/><circle cx="8" cy="15.6" r="2"/><circle cx="16" cy="8.4" r="2"/>',
    infoline: '<path d="M4 19 14 9"/><circle cx="4" cy="19" r="2"/><circle cx="14" cy="9" r="2"/><rect x="14.5" y="14" width="6.5" height="6" rx="1"/>',
    arrowline: '<path d="M4 20 19 5"/><path d="M11 5h8v8"/>',
    angle: '<path d="M4 19h16"/><path d="M4 19 17 7"/><path d="M11 19a7 7 0 0 0-2.1-5"/>',
    hline: '<path d="M2 12h20"/><circle cx="12" cy="12" r="2"/>',
    hray: '<path d="M8 12h14"/><circle cx="6" cy="12" r="2"/>',
    vline: '<path d="M12 2v20"/><circle cx="12" cy="12" r="2"/>',
    cross: '<path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="2"/>',
    chan: '<path d="M3 15 21 5M3 20 21 10"/>',
    regchan: '<path d="M3 12 21 6"/><path d="M3 17l18-6M3 7l18-6" stroke-dasharray="2 2"/>',
    pitchfork: '<path d="M3 12h3M6 12l15-7M6 12h15M6 12l15 7"/><circle cx="4" cy="12" r="1.6"/>',
    fib: '<path d="M3 5h18M3 10h18M3 14h18M3 19h18"/>',
    fibext: '<path d="M3 20 8 9l4 6"/><path d="M14 4h7M14 9h7M14 14h7M14 19h7"/>',
    fibtime: '<path d="M4 4v16M7 4v16M10 4v16M15 4v16M21 4v16"/>',
    fibfan: '<path d="M3 20 21 4M3 20 21 9M3 20l18-5M3 20h18"/>',
    gannfan: '<path d="M3 20 11 3M3 20 21 3M3 20l18-9M3 20l18-3"/>',
    gannbox: '<rect x="3.5" y="3.5" width="17" height="17"/><path d="m3.5 3.5 17 17M20.5 3.5l-17 17M12 3.5v17M3.5 12h17"/>',
    xabcd: '<path d="m3 17 5-11 4 8 4-10 5 13"/><path d="m3 17 9-3M8 6l8-2" stroke-dasharray="2 2"/>',
    abcd: '<path d="M3 18 9 6l5 9 7-11"/>',
    trianglep: '<path d="M3 5 21 12 3 19"/><path d="m3 5 9 10" stroke-dasharray="2 2"/>',
    elliott5: '<path d="m2 18 4-8 3 4 5-11 3 6 5-5"/>',
    elliott3: '<path d="m3 5 6 11 5-6 7 9"/>',
    hs: '<path d="m2 17 4-7 3 5 3-11 3 11 3-5 4 7"/><path d="M2 15h20" stroke-dasharray="2 2"/>',
    pos: '<rect x="3.5" y="4" width="17" height="7" rx="1"/><rect x="3.5" y="13" width="17" height="7" rx="1"/><path d="M8 8l2-2 2 2"/>',
    short: '<rect x="3.5" y="4" width="17" height="7" rx="1"/><rect x="3.5" y="13" width="17" height="7" rx="1"/><path d="m8 16 2 2 2-2"/>',
    ruler: '<path d="M3 17 17 3l4 4L7 21z"/><path d="m8 10 2 2m2-6 2 2"/>',
    prange: '<path d="M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4"/>',
    drange: '<path d="M4 12h16M8 8l-4 4 4 4M16 8l4 4-4 4"/>',
    avwap: '<path d="M3 18c4-1 5-9 9-9s5 5 9 3"/><path d="M4 4v16"/>',
    vprofile: '<path d="M4 4v16"/><path d="M4 6h6M4 9h11M4 12h15M4 15h9M4 18h5"/>',
    rect: '<rect x="3.5" y="6.5" width="17" height="11" rx="1"/>',
    ellipse: '<ellipse cx="12" cy="12" rx="9" ry="6"/>',
    triangle: '<path d="M12 4 21 19H3z"/>',
    path: '<path d="m3 18 5-10 6 6 7-10"/><circle cx="3" cy="18" r="1.5"/><circle cx="21" cy="4" r="1.5"/>',
    brush: '<path d="M3 21c3 0 4-2 4-4a3 3 0 1 0-4 4Z"/><path d="M9 15 20.5 3.5a1.8 1.8 0 0 1 2.5 2.5L11.5 17.5"/>',
    hilite: '<path d="m9 15-3 3H3v-3l9-9 6 6-3 3"/><path d="m14 4 6 6"/><path d="M3 21h18"/>',
    text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    callout: '<path d="M4 4h16v11h-9l-4 4v-4H4z"/>',
    pricelabel: '<path d="m3 12 5-6h13v12H8z"/><path d="M11 12h6"/>',
    arrowup: '<path d="m12 4 6 7h-4v9h-4v-9H6z"/>',
    arrowdown: '<path d="m12 20 6-7h-4V4h-4v9H6z"/>',
    flag: '<path d="M5 21V4"/><path d="M5 4h12l-3 4 3 4H5"/>',
    magnet: '<path d="M6 3v9a6 6 0 0 0 12 0V3"/><path d="M6 8h4M14 8h4"/>',
    stay: '<path d="m4 20 4-1 10-10-3-3L5 16z"/><path d="m14 6 3 3"/><path d="M15 20h6"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    unlock: '<rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 7.6-1.7"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="m3 3 18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4M6.6 6.6C3.7 8.4 2 12 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    undo: '<path d="M3 8h11a6 6 0 0 1 0 12H8"/><path d="m3 8 4-4M3 8l4 4"/>',
    redo: '<path d="M21 8H10a6 6 0 0 0 0 12h6"/><path d="m21 8-4-4M21 8l-4 4"/>',
    trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    unfull: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    fx: '<path d="M5 19c3 0 3-14 7-14M7 11h6"/><path d="m14 13 6 6M20 13l-6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    compare: '<circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/>',
    replay: '<path d="M4 12a8 8 0 1 0 2.3-5.6"/><path d="M4 4v4h4"/><path d="m11 9 4 3-4 3z"/>',
    bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    panel: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M15 4.5v15"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.3-4.3"/>',
    caret: '<path d="m6 9 6 6 6-6"/>',
    clone: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    zin: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.3-4.3M8 11h6M11 8v6"/>',
    zout: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.3-4.3M8 11h6"/>',
    left: '<path d="m15 6-6 6 6 6"/>',
    right: '<path d="m9 6 6 6-6 6"/>',
    reset: '<path d="M4 12a8 8 0 1 0 2.3-5.6"/><path d="M4 4v4h4"/>',
    end: '<path d="m5 6 6 6-6 6M12 6l6 6-6 6"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    step: '<path d="m6 5 9 7-9 7z"/><path d="M18 5v14"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    keys: '<rect x="2.5" y="6" width="19" height="12" rx="1.5"/><path d="M6 10h1M10 10h1M14 10h1M18 10h1M7 14h10"/>',
    candles: '<path d="M7 3v4M7 16v5M17 6v3M17 15v4"/><rect x="4.5" y="7" width="5" height="9" rx="1"/><rect x="14.5" y="9" width="5" height="6" rx="1"/>',
    bars: '<path d="M7 4v16M4 8h3M7 16h3M17 6v13M14 10h3M17 15h3"/>',
    line: '<path d="m3 17 5-6 4 3 8-9"/>',
    area: '<path d="m3 17 5-6 4 3 8-9v15H3z"/>',
    baseline: '<path d="M3 12h18" stroke-dasharray="2 2"/><path d="m3 15 4-5 4 6 4-9 6 5"/>',
    stepl: '<path d="M3 17h4v-5h5v3h4V6h5"/>',
    tree: '<path d="M4 5h6M4 12h6M4 19h6M14 5h6M14 12h6M14 19h6"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="1.5"/><path d="M4 16V5a1 1 0 0 1 1-1h11"/>',
    front: '<rect x="8" y="8" width="12" height="12" rx="1"/><path d="M4 16V4h12"/>',
    back: '<rect x="4" y="4" width="12" height="12" rx="1"/><path d="M8 20h12V8"/>'
  };
  function svg(name, cls) {
    return '<svg class="' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (I[name] || "") + "</svg>";
  }
  var TYPE_ICON = { candles: "candles", hollow: "candles", ha: "candles", bars: "bars", line: "line",
                    step: "stepl", area: "area", baseline: "baseline" };

  /* ── drawing tools ─────────────────────────────────────────────────────
     n: points to place (0 = drawn freehand, -1 = as many as you like).
     Every hint is written for the tool, because "tap 2 points" is true of
     half of them and tells nobody what they are about to get. */
  var T = {
    trend: { lab: "Trend line", n: 2, key: "Alt+T", hint: "Tap the start of the line, then the end. Hold Shift for a level line." },
    ray: { lab: "Ray", n: 2, hint: "Tap two points. The line runs on past the second one." },
    xline: { lab: "Extended line", n: 2, hint: "Tap two points. The line runs both ways for ever." },
    infoline: { lab: "Info line", n: 2, hint: "Tap two points. The line shows the move, the bars and the angle between them." },
    arrowline: { lab: "Arrow", n: 2, hint: "Tap where the arrow starts, then where it points." },
    angle: { lab: "Trend angle", n: 2, hint: "Tap two points to measure the angle of the move." },
    hline: { lab: "Horizontal line", n: 1, key: "Alt+H", hint: "Tap the price level to mark." },
    hray: { lab: "Horizontal ray", n: 1, key: "Alt+J", hint: "Tap the level. The line runs to the right from there." },
    vline: { lab: "Vertical line", n: 1, key: "Alt+V", hint: "Tap the candle to mark." },
    cross: { lab: "Cross line", n: 1, key: "Alt+C", hint: "Tap a point. A level and a date line cross there." },
    chan: { lab: "Parallel channel", n: 3, hint: "Tap the two ends of the base line, then a third point to set the width." },
    regchan: { lab: "Regression trend", n: 2, hint: "Tap the first and the last candle. The channel is fitted to the closes between them." },
    pitchfork: { lab: "Pitchfork", n: 3, hint: "Tap the pivot, then the high and the low of the swing that follows." },
    fib: { lab: "Fib retracement", n: 2, key: "Alt+F", hint: "Tap the start of the move, then its end. Levels are measured back from the end." },
    fibext: { lab: "Trend-based Fib extension", n: 3, hint: "Tap the start of the move, its end, then the end of the pullback." },
    fibtime: { lab: "Fib time zones", n: 2, hint: "Tap a turning point, then the next one. The zones run on at Fibonacci intervals." },
    fibfan: { lab: "Fib speed fan", n: 2, hint: "Tap the start and the end of a move." },
    gannfan: { lab: "Gann fan", n: 2, hint: "Tap the pivot, then a point that sets the 1x1 angle." },
    gannbox: { lab: "Gann box", n: 2, hint: "Tap two opposite corners of the box." },
    xabcd: { lab: "XABCD pattern", n: 5, hint: "Tap X, A, B, C and D in turn. The Fibonacci ratios between the legs are shown." },
    abcd: { lab: "ABCD pattern", n: 4, hint: "Tap A, B, C and D in turn." },
    trianglep: { lab: "Triangle pattern", n: 4, hint: "Tap the four turning points of the triangle in turn." },
    elliott5: { lab: "Elliott impulse wave", n: 6, hint: "Tap the start, then the ends of waves 1 to 5." },
    elliott3: { lab: "Elliott correction", n: 4, hint: "Tap the start, then the ends of waves A, B and C." },
    hs: { lab: "Head and shoulders", n: 7, hint: "Tap the start, the left shoulder, the trough, the head, the trough, the right shoulder and the end." },
    pos: { lab: "Long position", n: 2, hint: "Tap your entry, then your stop below it. The target lands at 2R; drag it to change." },
    short: { lab: "Short position", n: 2, hint: "Tap your entry, then your stop above it. The target lands at 2R; drag it to change." },
    ruler: { lab: "Date and price range", n: 2, key: "Alt+R", hint: "Tap where you start measuring, then where you finish." },
    prange: { lab: "Price range", n: 2, hint: "Tap two price levels to measure between them." },
    drange: { lab: "Date range", n: 2, hint: "Tap two candles to count the bars and the time between them." },
    avwap: { lab: "Anchored VWAP", n: 1, hint: "Tap the candle to anchor on. The line is the average price paid since that day." },
    vprofile: { lab: "Fixed range volume profile", n: 2, hint: "Tap the first and the last candle of the range." },
    rect: { lab: "Rectangle", n: 2, key: "Alt+B", hint: "Tap two opposite corners of the box." },
    ellipse: { lab: "Ellipse", n: 2, hint: "Tap two opposite corners of the box the ellipse fills." },
    triangle: { lab: "Triangle", n: 3, hint: "Tap the three corners." },
    path: { lab: "Path", n: -1, hint: "Tap each point. Tap the last point again, double-click or press Enter to finish." },
    brush: { lab: "Brush", n: 0, hint: "Draw with your finger or the mouse held down." },
    hilite: { lab: "Highlighter", n: 0, hint: "Draw over what you want to highlight." },
    text: { lab: "Text", n: 1, hint: "Tap where the text should sit." },
    callout: { lab: "Callout", n: 2, hint: "Tap the point the note is about, then where the note should sit." },
    pricelabel: { lab: "Price label", n: 1, hint: "Tap the price to label." },
    arrowup: { lab: "Arrow mark up", n: 1, hint: "Tap the candle to mark." },
    arrowdown: { lab: "Arrow mark down", n: 1, hint: "Tap the candle to mark." },
    flag: { lab: "Flag", n: 1, hint: "Tap the candle to flag." }
  };
  var GROUPS = [
    { g: "lines", lab: "Lines", tools: ["trend", "ray", "xline", "infoline", "arrowline", "angle", "hline", "hray", "vline", "cross"] },
    { g: "chan", lab: "Channels and pitchforks", tools: ["chan", "regchan", "pitchfork"] },
    { g: "fib", lab: "Fibonacci and Gann", tools: ["fib", "fibext", "fibtime", "fibfan", "gannfan", "gannbox"] },
    { g: "pat", lab: "Chart patterns", tools: ["xabcd", "abcd", "trianglep", "hs", "elliott5", "elliott3"] },
    { g: "fc", lab: "Forecast and measure", tools: ["pos", "short", "ruler", "prange", "drange", "avwap", "vprofile"] },
    { g: "shape", lab: "Shapes", tools: ["rect", "ellipse", "triangle", "path", "brush", "hilite"] },
    { g: "note", lab: "Text and marks", tools: ["text", "callout", "pricelabel", "arrowup", "arrowdown", "flag"] }
  ];
  function groupOf(t) {
    for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].tools.indexOf(t) >= 0) return GROUPS[i];
    return null;
  }
  var LINES = { trend: 1, ray: 1, xline: 1, infoline: 1, arrowline: 1, angle: 1 };
  var TEXTUAL = { text: 1, callout: 1 };
  var FILLED = { rect: 1, ellipse: 1, triangle: 1, chan: 1, regchan: 1, pitchfork: 1, fib: 1, fibext: 1, gannbox: 1, xabcd: 1, trianglep: 1 };
  var EXTENDABLE = { trend: 1, ray: 1, xline: 1, infoline: 1, chan: 1, regchan: 1, fib: 1, fibext: 1 };
  var FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618, 2.618];
  var FIBEXT_LEVELS = [0, 0.382, 0.5, 0.618, 1, 1.272, 1.618, 2, 2.618];
  /* Token names, not colours: asColor() reads them when a level is drawn. */
  var FIB_COLORS = ["--text-muted", "--chart-6", "--chart-1", "--chart-3", "--chart-2", "--chart-5",
                    "--text-muted", "--chart-2", "--chart-6", "--chart-4", "--chart-1"];
  /* What a drawing can be coloured: the chart series, gain and loss, and the
     three inks. A drawing keeps the token, so it is right in both themes. */
  var PALETTE = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6",
                 "--gain", "--loss", "--warning", "--info", "--text-primary", "--text-secondary", "--text-muted"];
  var CMP_COLORS = ["--chart-2", "--chart-1", "--chart-3", "--chart-6"];

  /* ── state ─────────────────────────────────────────────────────────────── */

  var LKEY = "altaha.charts.v2.layout";
  var DEF = {
    type: "candles", tf: "1D", studies: [{ id: "ema3" }, { id: "vol" }],
    log: false, pct: false, invert: false, side: false, sideTab: "tree",
    magnet: 0, stay: false, paneH: {},
    set: { grid: true, cross: 0, levels: true, wm: true, last: true, up: "", down: "" }
  };
  var L = (function () {
    var s = sget(LKEY, null), o = clone(DEF);
    if (s && typeof s === "object") {
      Object.keys(DEF).forEach(function (k) { if (s[k] != null) o[k] = s[k]; });
      o.set = Object.assign({}, DEF.set, s.set || {});
    }
    o.studies = (o.studies || []).filter(function (x) { return x && M.indicator(x.id); }).map(function (x) {
      return { uid: x.uid || uid(), id: x.id, p: Object.assign(M.defaults(M.indicator(x.id)), x.p || {}),
               hidden: !!x.hidden, col: x.col || {} };
    });
    if (!tfOf(o.tf) || tfOf(o.tf).k !== o.tf) o.tf = "1D";
    return o;
  })();
  function saveLayout() { sset(LKEY, L); }

  var W = {
    chart: null, main: null, space: null, vol: null, volMA: null, all: [], levelLines: [],
    sym: "", raw: [], full: [], rows: [], disp: [], times: [], timeline: [], barSec: 86400, off: 0,
    D: null, live: false, meta: null, req: 0,
    st: [], panes: [], paneSig: "", seriesSig: "",
    cmp: [],
    mode: "pan", tool: null, pending: [], preview: null, dragging: null,
    drawings: [], sel: null, undo: [], redo: [], clip: null, hideAll: false, lockAll: false,
    color: PALETTE[0], width: 2, lastTool: {},
    es: null, poll: null, refresh: null, lastTick: 0, lastPx: null, tickTimer: null,
    ptrs: {}, pinch: null, hover: null, sig: "", xIdx: null, replay: null, cache: {},
    universe: null, syncing: false, xsync: false
  };

  var root, box, cv, ctx, msgEl, noteEl, legEl, inspEl, pxEl, chgEl, liveEl, subEl, sideEl, toastEl;

  /* ── markup ────────────────────────────────────────────────────────────── */

  function railHTML() {
    var h = '<button class="cw-t" type="button" data-t="pan" data-tip="Cursor" aria-label="Cursor">' + svg("cursor") + "</button>" +
            '<button class="cw-t" type="button" data-t="erase" data-tip="Eraser" aria-label="Eraser">' + svg("eraser") + "</button><hr>";
    GROUPS.forEach(function (g) {
      var t = W.lastTool[g.g] || g.tools[0];
      h += '<div class="cw-grp" data-g="' + g.g + '">' +
        '<button class="cw-t" type="button" data-t="' + t + '" data-tip="' + esc(T[t].lab) + '" aria-label="' + esc(T[t].lab) + '">' + svg(t) + "</button>" +
        '<button class="cw-more" type="button" data-more="' + g.g + '" aria-label="More ' + esc(g.lab.toLowerCase()) + '" aria-haspopup="menu">' + svg("right") + "</button></div>";
    });
    h += "<hr>" +
      '<button class="cw-t" type="button" data-a="magnet" data-tip="Magnet" aria-label="Magnet">' + svg("magnet") + '<i class="cw-badge"></i></button>' +
      '<button class="cw-t" type="button" data-a="stay" data-tip="Keep drawing" aria-label="Keep drawing after each shape">' + svg("stay") + "</button>" +
      '<button class="cw-t" type="button" data-a="lockall" data-tip="Lock all drawings" aria-label="Lock all drawings">' + svg("lock") + "</button>" +
      '<button class="cw-t" type="button" data-a="hideall" data-tip="Hide all drawings" aria-label="Hide all drawings">' + svg("eye") + "</button>" +
      '<button class="cw-t" type="button" data-a="remove" data-tip="Remove" aria-label="Remove drawings or indicators">' + svg("trash") + "</button>";
    return h;
  }

  function tbtn(a, icon, label, txt) {
    return '<button class="cw-tb" type="button" data-a="' + a + '" title="' + esc(label) + '" aria-label="' + esc(label) + '">' +
      svg(icon) + (txt ? "<span>" + txt + "</span>" : "") + "</button>";
  }

  function viewHTML() {
    return '' +
'<header class="tabhead cw-head"><h2>Charts</h2><p>Drawings, indicators and replay on any NSE stock. Drawings are anchored to the candle you tapped and saved in this browser, per symbol.</p></header>' +
'<div class="cw" id="cw">' +
  '<div class="cw-tape">' +
    '<div class="cw-sym">' + svg("search", "cw-sym-i") +
      '<input id="cw-in" placeholder="Symbol" spellcheck="false" autocomplete="off" aria-label="Symbol" role="combobox" aria-expanded="false" aria-controls="cw-sug">' +
      '<button id="cw-go" type="button">Load</button></div>' +
    '<span class="cw-px" id="cw-px">–</span>' +
    '<span class="cw-chg" id="cw-chg"></span>' +
    '<span class="cw-live" id="cw-live"><i></i><span>Delayed</span></span>' +
    '<span class="cw-sep"></span>' +
    '<div class="cw-tfs" id="cw-tfs" role="group" aria-label="Timeframe">' +
      TFS.map(function (f) { return '<button type="button" data-r="' + f.k + '" data-api="' + f.pat + '">' + f.k + "</button>"; }).join("") +
    "</div>" +
    '<span class="cw-sep"></span>' +
    '<button class="cw-tb" type="button" data-a="type" id="cw-type" title="Chart type" aria-label="Chart type" aria-haspopup="menu">' + svg("candles") + svg("caret", "cw-caret") + "</button>" +
    tbtn("ind", "fx", "Indicators (/)", "Indicators") +
    tbtn("cmp", "compare", "Compare a symbol", "Compare") +
    tbtn("replay", "replay", "Bar replay", "Replay") +
    tbtn("alert", "bell", "Price alert", "Alert") +
    '<span class="cw-sep"></span>' +
    tbtn("undo", "undo", "Undo (Ctrl+Z)") +
    tbtn("redo", "redo", "Redo (Ctrl+Y)") +
    '<span class="cw-grow"></span>' +
    tbtn("settings", "gear", "Chart settings") +
    tbtn("shot", "camera", "Save or copy an image of the chart") +
    tbtn("side", "panel", "Object tree and data window") +
    tbtn("keys", "keys", "Keyboard shortcuts (?)") +
    '<button class="cw-tb" type="button" data-a="full" id="cw-full" title="Full screen (Shift+F)" aria-label="Full screen">' + svg("full") + "</button>" +
  "</div>" +
  '<div class="cw-rail" id="cw-rail">' + railHTML() + "</div>" +
  '<div class="cw-pane" id="cw-panes">' +
    '<div class="cw-price" id="cw-price">' +
      '<div class="cw-legend" id="cw-legend"></div>' +
      '<canvas class="cw-canvas" id="cw-cv"></canvas>' +
      '<div class="cw-msg on" id="cw-msg">Type a symbol to begin</div>' +
      '<div class="cw-insp" id="cw-insp" role="toolbar" aria-label="Drawing"></div>' +
      '<div class="cw-nav" id="cw-nav">' +
        '<button type="button" data-nav="zout" aria-label="Zoom out">' + svg("zout") + "</button>" +
        '<button type="button" data-nav="zin" aria-label="Zoom in">' + svg("zin") + "</button>" +
        '<button type="button" data-nav="left" aria-label="Scroll left">' + svg("left") + "</button>" +
        '<button type="button" data-nav="right" aria-label="Scroll right">' + svg("right") + "</button>" +
        '<button type="button" data-nav="reset" aria-label="Reset chart view">' + svg("reset") + "</button>" +
      "</div>" +
      '<button class="cw-rt" id="cw-rt" type="button" aria-label="Scroll to the latest bar">' + svg("end") + "</button>" +
      '<div class="cw-toast" id="cw-toast" role="status" aria-live="polite"></div>' +
      '<div class="cw-replay" id="cw-replay"></div>' +
    "</div>" +
    '<div class="cw-sub" id="cw-sub"></div>' +
  "</div>" +
  '<aside class="cw-side" id="cw-side" aria-label="Object tree and data window"></aside>' +
  '<div class="cw-foot">' +
    '<div class="cw-zooms" role="group" aria-label="Date range">' +
      ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "All"].map(function (z) {
        return '<button class="cw-chip" type="button" data-zoom="' + z + '">' + z + "</button>";
      }).join("") +
    "</div>" +
    '<button class="cw-chip cw-ico" type="button" data-goto="1" title="Go to a date" aria-label="Go to a date">' + svg("calendar") + "</button>" +
    '<span class="cw-sep"></span>' +
    '<button class="cw-chip" type="button" data-scale="pct" title="Percent scale">%</button>' +
    '<button class="cw-chip" type="button" data-scale="log" title="Log scale">log</button>' +
    '<button class="cw-chip" type="button" data-scale="auto" title="Fit prices to the screen">auto</button>' +
    '<span class="cw-note" id="cw-note"></span>' +
  "</div>" +
"</div>" +
'<p class="disc" style="margin-top:20px">Drawings, alerts and layouts never leave this browser and are not part of any score.</p>';
  }

  /* ── theme ─────────────────────────────────────────────────────────────── */

  function upC() { return asColor(L.set.up) || tok("--gain"); }
  function dnC() { return asColor(L.set.down) || tok("--loss"); }

  function theme(sub) {
    var LW = window.LightweightCharts, grid = L.set.grid ? Th.alpha("--border", 0.5) : "transparent";
    var tf = tfOf(L.tf), T = Th.chart();
    return {
      layout: {
        background: { type: "solid", color: tok("--surface") },
        textColor: tok("--text-muted"),
        fontFamily: T.fontSans, fontSize: T.axisSize
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      /* minimumWidth pins the axis gutter. Without it a pane whose values are
         0 to 100 draws a narrower scale than the price pane, the panes end at
         different x, and every bar sits a few pixels off the one above it. */
      rightPriceScale: { borderColor: tok("--border"), minimumWidth: 76,
                         scaleMargins: sub ? { top: 0.1, bottom: 0.08 } : { top: 0.08, bottom: 0.2 } },
      timeScale: { borderColor: tok("--border"), timeVisible: !!tf.intra, secondsVisible: false,
                   rightOffset: 10, barSpacing: 7, minBarSpacing: 0.5 },
      crosshair: {
        mode: L.set.cross ? LW.CrosshairMode.Magnet : LW.CrosshairMode.Normal,
        vertLine: { color: tok("--text-muted"), width: 1, style: 2, labelBackgroundColor: tok("--accent") },
        horzLine: { color: tok("--text-muted"), width: 1, style: 2, labelBackgroundColor: tok("--accent") }
      },
      watermark: {
        visible: !sub && !!L.set.wm && !!W.sym, text: W.sym ? W.sym + " · " + L.tf : "",
        color: Th.alpha("--text-muted", 0.1), fontSize: T.displaySize, fontFamily: T.fontMono,
        horzAlign: "center", vertAlign: "center"
      },
      handleScroll: true, handleScale: true
    };
  }

  /* ══════════════════════════════════════════════════════════════════════
     GEOMETRY
     Anchors are {t, p}. t becomes a fractional bar index by interpolating
     the loaded candle times, and that index becomes an x by calibrating
     against the two ends of the visible range. Both directions extrapolate
     past the last bar, which is what lets a ray run on into empty space.
     ══════════════════════════════════════════════════════════════════════ */

  function tToL(t) {
    var a = W.times, n = a.length;
    if (!n) return 0;
    if (t <= a[0]) return (t - a[0]) / W.barSec;
    if (t >= a[n - 1]) return (n - 1) + (t - a[n - 1]) / W.barSec;
    var lo = 0, hi = n - 1, m;
    while (hi - lo > 1) { m = (lo + hi) >> 1; if (a[m] <= t) lo = m; else hi = m; }
    return lo + (t - a[lo]) / ((a[hi] - a[lo]) || 1);
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
    if (!W.chart || !W.main) return null;
    var ts = W.chart.timeScale(), vr = ts.getVisibleLogicalRange();
    if (!vr) return null;
    var x0 = ts.logicalToCoordinate(vr.from), x1 = ts.logicalToCoordinate(vr.to);
    if (x0 == null || x1 == null || x1 === x0) return null;
    var k = (x1 - x0) / (vr.to - vr.from);
    return {
      /* Not ts.width(): with an indicator pane below, the price chart's time
         axis is hidden and the library then reports its width as 0, which
         clipped every drawing away. The plot is the box less the price axis. */
      from: vr.from, to: vr.to, k: k, w: plotW(), W: box.clientWidth,
      h: Math.max(10, box.clientHeight - (W.panes.length ? 0 : ts.height())),
      x: function (l) { return x0 + (l - vr.from) * k; },
      l: function (x) { return vr.from + (x - x0) / k; }
    };
  }
  function plotW() {
    var aw = 0;
    try { aw = W.chart.priceScale("right").width(); } catch (e) {}
    return Math.max(10, box.clientWidth - (aw || 76));
  }
  function X(g, t) { return g.x(tToL(t)); }
  function Y(p) { if (!W.main || !ok(p)) return null; var y = W.main.priceToCoordinate(p); return y == null ? null : y; }
  function pAt(y) { var p = W.main ? W.main.coordinateToPrice(y) : null; return p == null ? null : p; }
  function idxOf(t) { return clamp(Math.round(tToL(t)), 0, Math.max(0, W.rows.length - 1)); }

  /* Magnet: weak snaps to a candle's open, high, low or close when within
     a dozen pixels of it; strong always snaps. Traders anchor to highs and
     lows, not to wherever the cursor happened to land. */
  function snap(t, p, y) {
    if (!L.magnet || !W.rows.length) return { t: t, p: p };
    var i = Math.round(tToL(t));
    if (i < 0 || i >= W.rows.length) return { t: t, p: p };
    var r = W.disp[i] || W.rows[i], best = r.close, bd = Infinity;
    [r.open, r.high, r.low, r.close].forEach(function (v) {
      var d = Math.abs((Y(v) == null ? 0 : Y(v)) - y);
      if (d < bd) { bd = d; best = v; }
    });
    if (L.magnet === 1 && bd > 12) return { t: r.time, p: p };
    return { t: r.time, p: best };
  }

  /* ══════════════════════════════════════════════════════════════════════
     DRAWINGS: model, undo, persistence
     ══════════════════════════════════════════════════════════════════════ */

  function key() { return "altaha.charts.v1." + (W.sym || "_"); }
  function save() { sset(key(), W.drawings); }
  function loadDrawings() {
    var d = sget(key(), []);
    W.drawings = Array.isArray(d) ? d.filter(function (x) { return x && x.type && Array.isArray(x.pts); }) : [];
    W.sel = null; W.undo = []; W.redo = [];
  }
  function push() {
    W.undo.push(JSON.stringify(W.drawings));
    if (W.undo.length > 100) W.undo.shift();
    W.redo = [];
  }
  function restore(json) {
    var selId = W.sel && W.sel.id;
    W.drawings = JSON.parse(json);
    W.sel = null;
    for (var i = 0; i < W.drawings.length; i++) if (W.drawings[i].id === selId) W.sel = W.drawings[i];
    save(); inspector(); sideRefresh(); render();
  }
  function undo() {
    if (!W.undo.length) { note("Nothing to undo."); return; }
    W.redo.push(JSON.stringify(W.drawings));
    restore(W.undo.pop());
  }
  function redo() {
    if (!W.redo.length) { note("Nothing to redo."); return; }
    W.undo.push(JSON.stringify(W.drawings));
    restore(W.redo.pop());
  }
  function changed() { save(); inspector(); sideRefresh(); render(); }

  function byId(id) {
    for (var i = 0; i < W.drawings.length; i++) if (W.drawings[i].id === id) return W.drawings[i];
    return null;
  }
  function select(d) { W.sel = d; inspector(); sideRefresh(); render(); }
  function del(d) {
    d = d || W.sel; if (!d) return;
    push();
    W.drawings = W.drawings.filter(function (x) { return x !== d; });
    if (W.sel === d) W.sel = null;
    changed();
  }
  function duplicate(d) {
    d = d || W.sel; if (!d) return;
    push();
    var c = clone(d); c.id = uid(); c.locked = false;
    var g = geo(), dx = g ? 12 / g.k : 1, dy = 0;
    if (g) { var y = Y(c.pts[0].p); if (y != null) dy = pAt(y + 12) - c.pts[0].p; }
    c.pts = c.pts.map(function (q) { return { t: lToT(tToL(q.t) + dx), p: q.p + (dy || 0) }; });
    W.drawings.push(c); W.sel = c; changed();
  }
  function paste() {
    if (!W.clip) return;
    var c = clone(W.clip); c.id = uid();
    var g = geo();
    if (g && c.pts.length) {
      /* Into view: shifted so its first anchor lands mid-screen. */
      var mid = g.l(g.w / 2), dl = mid - tToL(c.pts[0].t);
      var mp = pAt(g.h / 2), dp = (mp == null ? 0 : mp - c.pts[0].p);
      c.pts = c.pts.map(function (q) { return { t: lToT(tToL(q.t) + dl), p: q.p + dp }; });
    }
    push(); W.drawings.push(c); W.sel = c; changed();
    note("Pasted.");
  }
  function order(d, front) {
    push();
    W.drawings = W.drawings.filter(function (x) { return x !== d; });
    if (front) W.drawings.push(d); else W.drawings.unshift(d);
    changed();
  }

  function newDrawing(type, pts) {
    var o = { id: uid(), type: type, pts: pts, color: W.color, width: W.width, style: "solid" };
    if (type === "fib" || type === "fibext") o.tv = 1;
    if (type === "hilite") { o.color = "--highlight"; o.width = 14; }
    if (type === "arrowup") o.color = "--gain";
    if (type === "arrowdown") o.color = "--loss";
    if (type === "text" || type === "callout") { o.fs = 14; o.text = ""; }
    if (type === "regchan") o.dev = 2;
    if (type === "vprofile") o.rowsN = 24;
    return o;
  }

  /* ══════════════════════════════════════════════════════════════════════
     PAINTING
     Each drawing records the geometry it painted (segments, boxes,
     polygons, ellipses, handles) as it paints, and hit-testing reads that
     record. The hit-tester therefore can never disagree with what is on
     screen, which is the classic source of "the line is not where I click".
     ══════════════════════════════════════════════════════════════════════ */

  var HITS = {}, HC = null;

  function sizeCanvas() {
    var dpr = window.devicePixelRatio || 1, w = box.clientWidth, h = box.clientHeight;
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
    paintFills(g);
    HITS = {};
    if (!W.hideAll) {
      W.drawings.forEach(function (d) {
        if (d.hidden) return;
        HC = { s: [], b: [], p: [], e: [], h: null };
        try { shape(d, g, false); } catch (e) {}
        HITS[d.id] = HC;
      });
    }
    if (W.preview) {
      HC = { s: [], b: [], p: [], e: [], h: null };
      ctx.globalAlpha = 0.75;
      try { shape(W.preview, g, true); } catch (e) {}
      ctx.globalAlpha = 1;
    }
    if (W.sel && !W.sel.hidden && !W.hideAll && HITS[W.sel.id]) handles(HITS[W.sel.id].h);
    /* The points placed so far, marked the moment they are placed: a line
       of no length yet is otherwise invisible, and a click that shows
       nothing reads as a click that did nothing. */
    if (W.mode === "draw" && W.pending.length) {
      handles(W.pending.map(function (q) { return { x: X(g, q.t), y: Y(q.p) }; }));
    }
    ctx.restore();
    axisTags(g);
    rtButton(g);
  }

  /* Bands and clouds: the space between two outputs of an overlay. */
  function paintFills(g) {
    W.st.forEach(function (s) {
      if (s.hidden || s.def.pane || !s.def.fill || !s.data) return;
      s.def.fill.forEach(function (pair) {
        var a = s.data[pair[0]], b = s.data[pair[1]];
        if (!a || !b) return;
        var i0 = Math.max(0, Math.floor(g.from) - 1), i1 = Math.min(a.length - 1, Math.ceil(g.to) + 1);
        var cloud = s.id === "ichimoku", col = colOf(s, s.def.out[1]);
        var run = [];
        function flush() {
          if (run.length < 2) { run = []; return; }
          ctx.beginPath();
          run.forEach(function (q, k) { if (k) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); });
          for (var k = run.length - 1; k >= 0; k--) ctx.lineTo(run[k][0], run[k][2]);
          ctx.closePath();
          ctx.fillStyle = cloud ? (run.up ? tok("--gain") : tok("--loss")) : col;
          ctx.globalAlpha = cloud ? 0.12 : 0.07; ctx.fill(); ctx.globalAlpha = 1;
          run = [];
        }
        for (var i = i0; i <= i1; i++) {
          if (!ok(a[i]) || !ok(b[i])) { flush(); continue; }
          var ya = Y(a[i]), yb = Y(b[i]);
          if (ya == null || yb == null) { flush(); continue; }
          var up = a[i] >= b[i];
          if (cloud && run.length && run.up !== up) { run.push([g.x(i), ya, yb]); flush(); }
          if (!run.length) run.up = up;
          run.push([g.x(i), ya, yb]);
        }
        flush();
      });
    });
  }

  function dashFor(style, w) {
    if (style === "dash") return [w * 4 + 2, w * 3 + 1];
    if (style === "dot") return [0.1, w * 2.6 + 1];
    return [];
  }
  function stroke(col, w, style) {
    ctx.strokeStyle = col; ctx.lineWidth = w;
    ctx.setLineDash(dashFor(style, w)); ctx.lineCap = "round"; ctx.lineJoin = "round";
  }
  function seg(a, b) {
    if (!a || !b || a.y == null || b.y == null) return;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    HC.s.push([a.x, a.y, b.x, b.y]);
  }
  function polyline(P, close) {
    var Q = P.filter(function (q) { return q && q.y != null; });
    if (Q.length < 2) return;
    ctx.beginPath();
    Q.forEach(function (q, i) { if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y); });
    if (close) ctx.closePath();
    ctx.stroke();
    for (var i = 1; i < Q.length; i++) HC.s.push([Q[i - 1].x, Q[i - 1].y, Q[i].x, Q[i].y]);
    if (close) HC.s.push([Q[Q.length - 1].x, Q[Q.length - 1].y, Q[0].x, Q[0].y]);
  }
  function fillPoly(P, col, a, record) {
    var Q = P.filter(function (q) { return q && q.y != null; });
    if (Q.length < 3 || !a) return;
    ctx.beginPath();
    Q.forEach(function (q, i) { if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y); });
    ctx.closePath();
    var ga = ctx.globalAlpha;
    ctx.fillStyle = col; ctx.globalAlpha = ga * a; ctx.fill(); ctx.globalAlpha = ga;
    if (record !== false) HC.p.push(Q.map(function (q) { return [q.x, q.y]; }));
  }
  function fillRect(x, y, w, h, col, a) {
    var ga = ctx.globalAlpha;
    ctx.fillStyle = col; ctx.globalAlpha = ga * a;
    ctx.fillRect(Math.min(x, x + w), Math.min(y, y + h), Math.abs(w), Math.abs(h));
    ctx.globalAlpha = ga;
    HC.b.push([Math.min(x, x + w), Math.min(y, y + h), Math.abs(w), Math.abs(h)]);
  }
  /* Far along a->b, for rays and extended lines. */
  function extend(a, b, left, right) {
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len, R = 1e4;
    return [left ? { x: a.x - ux * R, y: a.y - uy * R } : a, right ? { x: b.x + ux * R, y: b.y + uy * R } : b];
  }
  function arrowHead(a, b, col, w, size) {
    var ang = Math.atan2(b.y - a.y, b.x - a.x), s = size || (8 + w * 2);
    ctx.setLineDash([]); ctx.fillStyle = col;
    ctx.beginPath();
    ctx.moveTo(b.x, b.y);
    ctx.lineTo(b.x - s * Math.cos(ang - 0.42), b.y - s * Math.sin(ang - 0.42));
    ctx.lineTo(b.x - s * Math.cos(ang + 0.42), b.y - s * Math.sin(ang + 0.42));
    ctx.closePath(); ctx.fill();
  }
  /* Labels on the drawing layer: the 11px label size, in Inter. */
  function labelFont() { var T = Th.chart(); return "500 " + T.axisSize + "px " + T.fontSans; }
  /* A filled label. align: 0 left, 0.5 centre, 1 right of x. Recorded as a
     box so clicking the label selects its drawing. */
  function label(text, x, y, bg, fg, align, font) {
    ctx.font = font || labelFont();
    var lines = String(text).split("\n"), w = 0;
    lines.forEach(function (s) { w = Math.max(w, ctx.measureText(s).width); });
    w += 12;
    var h = lines.length * 15 + 4, x0 = x - w * (align || 0), y0 = y - h / 2;
    var ga = ctx.globalAlpha;
    ctx.setLineDash([]);
    ctx.fillStyle = bg; ctx.globalAlpha = ga * 0.94;
    roundRect(x0, y0, w, h, 4); ctx.fill();
    ctx.globalAlpha = ga; ctx.fillStyle = fg;
    lines.forEach(function (s, i) { ctx.fillText(s, x0 + 6, y0 + 14 + i * 15); });
    HC.b.push([x0, y0, w, h]);
    return { x: x0, y: y0, w: w, h: h };
  }
  function plainText(text, x, y, col, align, font) {
    ctx.font = font || labelFont(); ctx.fillStyle = col;
    var w = ctx.measureText(text).width, x0 = x - w * (align || 0);
    ctx.fillText(text, x0, y);
    HC.b.push([x0 - 2, y - 11, w + 4, 15]);
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  }
  function onWhite(c) {
    /* Text on a filled label: the light ink unless the fill is pale. */
    var T = Th.chart(), lightInk = T.theme === "dark" ? T.text : T.onAccent, darkInk = T.theme === "dark" ? T.onAccent : T.text;
    var m = /^#?([0-9a-f]{6})$/i.exec(asColor(c) || "");
    if (!m) return lightInk;
    var n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    return (r * 0.299 + g * 0.587 + b * 0.114) > 170 ? darkInk : lightInk;
  }
  function handles(list) {
    if (!list) return;
    ctx.fillStyle = tok("--surface");
    ctx.strokeStyle = tok("--highlight");
    ctx.lineWidth = 1.5; ctx.setLineDash([]);
    list.forEach(function (q) {
      if (q.x == null || q.y == null) return;
      ctx.beginPath(); ctx.arc(q.x, q.y, HANDLE, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
  }
  function pix(d, g) {
    return d.pts.map(function (a, i) {
      var y = Y(a.p);
      return { x: X(g, a.t), y: y, i: i };
    });
  }
  function levelsOf(d) {
    var def = d.type === "fibext" ? FIBEXT_LEVELS : FIB_LEVELS;
    if (Array.isArray(d.levels) && d.levels.length) return d.levels;
    return def.map(function (v) { return { v: v, on: true }; });
  }
  function need(type) { var n = (T[type] || {}).n; return n > 0 ? n : 0; }

  /* Above a high, below a low: where a pattern's point label belongs. */
  function lbPos(P, i) {
    var q = P[i], a = P[i - 1], b = P[i + 1], up;
    if (a && b) up = q.y <= Math.min(a.y, b.y) || (q.y < (a.y + b.y) / 2);
    else if (a) up = q.y < a.y; else if (b) up = q.y < b.y; else up = true;
    return up ? -12 : 20;
  }
  function patternPoints(P, labels, col) {
    ctx.font = "600 12px 'Inter', system-ui, sans-serif";
    P.forEach(function (q, i) {
      if (!labels[i] || q.y == null) return;
      var t = labels[i], w = ctx.measureText(t).width;
      ctx.fillStyle = col; ctx.fillText(t, q.x - w / 2, q.y + lbPos(P, i));
    });
  }
  function ratioOn(a, b, r) {
    if (!a || !b || !ok(r)) return;
    label(r.toFixed(3), (a.x + b.x) / 2, (a.y + b.y) / 2, tok("--surface"), tok("--text-secondary"), 0.5);
  }

  function shape(d, g, ghost) {
    var P = pix(d, g);
    if (!P.length || P[0].y == null) return;
    var c = asColor(d.color || W.color), w = d.width || 2, sty = d.style || "solid";
    var fa = d.fill == null ? 1 : d.fill;          /* fill strength, 0 to 1 */
    var A = d.pts, typ = d.type, n = need(typ);
    stroke(c, w, sty);

    /* A multi-point tool still being placed: show the legs so far. */
    if (ghost && n > 2 && P.length < n && !/^(xabcd|abcd|trianglep|elliott5|elliott3|hs|triangle)$/.test(typ)) {
      polyline(P); return;
    }
    if (n >= 2 && P.length < 2 && !ghost) return;

    var a = P[0], b = P[1], txt, i, k;

    switch (typ) {
      case "trend": case "ray": case "xline": case "infoline": case "arrowline": case "angle": {
        if (!b) return;
        var eL = d.extL != null ? d.extL : typ === "xline";
        var eR = d.extR != null ? d.extR : (typ === "ray" || typ === "xline");
        var E = extend(a, b, eL, eR);
        seg(E[0], E[1]);
        if (typ === "arrowline") arrowHead(a, b, c, w);
        if (typ === "infoline" || typ === "angle") {
          var deg = Math.atan2(a.y - b.y, b.x - a.x) * 180 / Math.PI;
          if (typ === "angle") {
            stroke(c, 1, "dash");
            var rr = Math.min(60, Math.abs(b.x - a.x) || 40);
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(a.x + rr * (b.x >= a.x ? 1 : -1), a.y); ctx.stroke();
            ctx.beginPath(); ctx.arc(a.x, a.y, rr * 0.6, b.x >= a.x ? 0 : Math.PI, -deg * Math.PI / 180, b.x >= a.x ? deg > 0 : deg < 0); ctx.stroke();
            label(deg.toFixed(1) + "°", a.x + rr * 0.7 * (b.x >= a.x ? 1 : -1), a.y + (deg > 0 ? 12 : -12), c, onWhite(c), b.x >= a.x ? 0 : 1);
          } else {
            var dp = A[1].p - A[0].p, bars = Math.round(tToL(A[1].t) - tToL(A[0].t));
            txt = (dp >= 0 ? "+" : "") + fmt(dp) + " (" + pctS(A[0].p ? dp / A[0].p * 100 : 0) + ")\n" +
                  bars + " bars, " + span(A[1].t - A[0].t) + "\n" + deg.toFixed(1) + "°";
            label(txt, b.x + 10, b.y + 26, tok("--accent"), tok("--on-accent"), 0);
          }
        }
        if (d.text) plainText(d.text, (a.x + b.x) / 2, (a.y + b.y) / 2 - 7, c, 0.5, "500 12px 'Inter', system-ui, sans-serif");
        HC.h = [a, b];
        break;
      }
      case "hline": case "hray": case "cross": {
        var x0 = typ === "hray" ? a.x : 0;
        seg({ x: x0, y: a.y }, { x: g.w, y: a.y });
        if (typ === "cross") seg({ x: a.x, y: 0 }, { x: a.x, y: g.h });
        if (d.text) plainText(d.text, g.w - 8, a.y - 6, c, 1, "500 12px 'Inter', system-ui, sans-serif");
        if (d.alert) { ctx.fillStyle = c; ctx.font = "13px sans-serif"; ctx.fillText("🔔", (typ === "hray" ? a.x : 4) + 4, a.y - 5); }
        HC.h = [{ x: typ === "hline" ? Math.min(g.w - 30, Math.max(30, a.x)) : a.x, y: a.y, i: 0 }];
        break;
      }
      case "vline": {
        seg({ x: a.x, y: 0 }, { x: a.x, y: g.h });
        if (d.text) plainText(d.text, a.x + 6, 16, c, 0, "500 12px 'Inter', system-ui, sans-serif");
        HC.h = [{ x: a.x, y: Math.min(g.h - 30, Math.max(30, g.h / 2)), i: 0 }];
        break;
      }
      case "chan": {
        if (!b) return;
        var off = 0;
        if (P[2] && P[2].y != null) {
          var m = (b.y - a.y) / ((b.x - a.x) || 1);
          off = P[2].y - (a.y + m * (P[2].x - a.x));
        }
        var eL2 = !!d.extL, eR2 = !!d.extR;
        var a2 = { x: a.x, y: a.y + off }, b2 = { x: b.x, y: b.y + off };
        var E1 = extend(a, b, eL2, eR2), E2 = extend(a2, b2, eL2, eR2);
        fillPoly([E1[0], E1[1], E2[1], E2[0]], c, 0.08 * fa);
        seg(E1[0], E1[1]); seg(E2[0], E2[1]);
        stroke(c, 1, "dash");
        var Em = extend({ x: a.x, y: a.y + off / 2 }, { x: b.x, y: b.y + off / 2 }, eL2, eR2);
        seg(Em[0], Em[1]);
        HC.h = [a, b, { x: P[2] ? P[2].x : b.x, y: P[2] ? P[2].y : b.y + off, i: 2 }];
        break;
      }
      case "regchan": {
        if (!b) return;
        var cl = W.rows.map(function (r) { return r.close; });
        var la = tToL(A[0].t), lb = tToL(A[1].t);
        var i0 = clamp(Math.round(Math.min(la, lb)), 0, cl.length - 1), i1 = clamp(Math.round(Math.max(la, lb)), 0, cl.length - 1);
        var reg = M.regression(cl, i0, i1);
        if (!reg) { seg(a, b); HC.h = [a, b]; break; }
        var dev = d.dev || 2, xs = g.x(i0), xe = g.x(i1);
        var rows3 = [[reg.start, reg.end], [reg.start + dev * reg.sd, reg.end + dev * reg.sd], [reg.start - dev * reg.sd, reg.end - dev * reg.sd]];
        var ext = d.extR ? 1e4 : 0, slope = (xe - xs) ? 1 : 0;
        var lines3 = rows3.map(function (r) {
          var p = { x: xs, y: Y(r[0]) }, q = { x: xe, y: Y(r[1]) };
          if (ext && slope) q = extend(p, q, false, true)[1];
          return [p, q];
        });
        fillPoly([lines3[1][0], lines3[1][1], lines3[2][1], lines3[2][0]], c, 0.07 * fa);
        seg(lines3[0][0], lines3[0][1]);
        stroke(c, Math.max(1, w - 1), sty === "solid" ? "dash" : sty);
        seg(lines3[1][0], lines3[1][1]); seg(lines3[2][0], lines3[2][1]);
        var first = la <= lb ? 0 : 1;
        HC.h = [{ x: xs, y: Y(reg.start), i: first }, { x: xe, y: Y(reg.end), i: 1 - first }];
        break;
      }
      case "pitchfork": {
        if (!P[2] || P[2].y == null) { seg(a, b); HC.h = [a, b]; break; }
        var mid = { x: (b.x + P[2].x) / 2, y: (b.y + P[2].y) / 2 };
        var dx = mid.x - a.x, dy = mid.y - a.y, len = Math.hypot(dx, dy) || 1, R = 1e4 / len;
        var far = function (q) { return { x: q.x + dx * R, y: q.y + dy * R }; };
        fillPoly([b, far(b), far(P[2]), P[2]], c, 0.07 * fa);
        seg(a, far(a)); seg(b, far(b)); seg(P[2], far(P[2]));
        stroke(c, 1, "dash"); seg(b, P[2]);
        HC.h = [a, b, P[2]];
        break;
      }
      case "fib": case "fibext": {
        var lvls = levelsOf(d).filter(function (x) { return x.on !== false; });
        var base, unit, xl, xr;
        if (typ === "fib") {
          if (!b) return;
          var from = d.tv ? A[1].p : A[0].p, to = d.tv ? A[0].p : A[1].p;
          base = from; unit = to - from;
          xl = Math.min(a.x, b.x); xr = Math.max(a.x, b.x);
        } else {
          if (!P[2] || P[2].y == null) { stroke(c, 1, "dash"); polyline(P); HC.h = P; break; }
          base = A[2].p; unit = A[1].p - A[0].p;
          xl = P[2].x; xr = P[2].x + Math.max(60, Math.abs(b.x - a.x));
          stroke(c, 1, "dash"); polyline([a, b, P[2]]);
        }
        var eR3 = d.extR != null ? d.extR : true, eL3 = !!d.extL;
        var L0 = eL3 ? 0 : xl, R0 = eR3 ? g.w : xr;
        var ys = lvls.map(function (lv) { return { lv: lv, p: base + unit * lv.v, y: Y(base + unit * lv.v) }; });
        ys.forEach(function (q, j) {
          var lc = d.mono ? c : (q.lv.c || asColor(FIB_COLORS[j % FIB_COLORS.length]));
          if (j && ys[j - 1].y != null && q.y != null && fa) {
            var ga = ctx.globalAlpha;
            ctx.fillStyle = lc; ctx.globalAlpha = ga * 0.07 * fa;
            ctx.fillRect(L0, Math.min(q.y, ys[j - 1].y), R0 - L0, Math.abs(q.y - ys[j - 1].y));
            ctx.globalAlpha = ga;
          }
        });
        ys.forEach(function (q, j) {
          if (q.y == null) return;
          var lc = d.mono ? c : (q.lv.c || asColor(FIB_COLORS[j % FIB_COLORS.length]));
          stroke(lc, q.lv.v === 0 || q.lv.v === 1 ? w : Math.max(1, w - 1), sty);
          seg({ x: L0, y: q.y }, { x: R0, y: q.y });
          if (d.labels !== false) {
            ctx.font = labelFont(); ctx.fillStyle = lc;
            ctx.fillText((typ === "fib" ? (q.lv.v * 100).toFixed(1).replace(/\.0$/, "") + "%" : q.lv.v.toString()) +
                         "  (" + fmt(q.p) + ")", xl + 4, q.y - 4);
          }
        });
        if (typ === "fib") { stroke(c, 1, "dot"); seg(a, b); }
        HC.b.push([Math.min(L0, R0), Math.min.apply(null, ys.map(function (q) { return q.y == null ? 1e9 : q.y; })),
                   Math.abs(R0 - L0), 0]);
        var yy = ys.filter(function (q) { return q.y != null; }).map(function (q) { return q.y; });
        if (yy.length) { var top = Math.min.apply(null, yy), bot = Math.max.apply(null, yy); HC.b[HC.b.length - 1] = [Math.min(xl, R0), top, Math.abs(R0 - xl), bot - top]; }
        HC.h = typ === "fib" ? [a, b] : [a, b, P[2]];
        break;
      }
      case "fibtime": {
        if (!b) return;
        var l0 = tToL(A[0].t), u = tToL(A[1].t) - l0, seq = [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233];
        if (!u) { seg({ x: a.x, y: 0 }, { x: a.x, y: g.h }); HC.h = [a, b]; break; }
        seq.forEach(function (s, j) {
          var x = g.x(l0 + u * s);
          if (x < -10 || x > g.w + 10) return;
          stroke(d.mono ? c : asColor(FIB_COLORS[j % FIB_COLORS.length]), j < 2 ? w : 1, sty);
          seg({ x: x, y: 0 }, { x: x, y: g.h });
          plainText(String(s), x + 3, 14, c, 0);
        });
        stroke(c, 1, "dot"); seg(a, b);
        HC.h = [a, b];
        break;
      }
      case "fibfan": case "gannfan": {
        if (!b) return;
        var fdx = b.x - a.x, fdy = b.y - a.y;
        /* Speed fan: rays from the start through the end of the move cut
           back by each ratio, in price and in time. Gann: the classic
           angles, 1x1 being the line from the pivot to the second tap. */
        var rays = [];
        if (typ === "fibfan") {
          [0, 0.25, 0.382, 0.5, 0.618, 0.75].forEach(function (r) { rays.push({ x: b.x, y: b.y - fdy * r, lab: String(1 - r), main: r === 0 }); });
          [0.25, 0.382, 0.5, 0.618, 0.75].forEach(function (r) { rays.push({ x: b.x - fdx * r, y: b.y, lab: String(1 - r) }); });
        } else {
          [[1, 8], [1, 4], [1, 3], [1, 2], [1, 1], [2, 1], [3, 1], [4, 1], [8, 1]].forEach(function (r) {
            var mx = Math.max(r[0], r[1]);
            rays.push({ x: a.x + fdx * r[0] / mx, y: a.y + fdy * r[1] / mx, lab: r[0] + "/" + r[1], main: r[0] === r[1] });
          });
        }
        rays.forEach(function (r, j) {
          var lc = d.mono ? c : asColor(FIB_COLORS[j % FIB_COLORS.length]);
          var e = extend(a, r, false, true);
          stroke(lc, r.main ? w : 1, sty);
          seg(a, e[1]);
          if (d.labels !== false) plainText(r.lab, r.x + 3, r.y - 3, lc, 0);
        });
        if (typ === "fibfan") { stroke(c, 1, "dot"); ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(fdx), Math.abs(fdy)); }
        HC.h = [a, b];
        break;
      }
      case "gannbox": {
        if (!b) return;
        var gl = [0, 0.25, 0.382, 0.5, 0.618, 0.75, 1], bx = b.x - a.x, by = b.y - a.y;
        fillRect(a.x, a.y, bx, by, c, 0.05 * fa);
        gl.forEach(function (v, j) {
          stroke(d.mono ? c : asColor(FIB_COLORS[j % FIB_COLORS.length]), v === 0 || v === 1 ? w : 1, v === 0 || v === 1 ? sty : "dash");
          seg({ x: a.x + bx * v, y: a.y }, { x: a.x + bx * v, y: b.y });
          seg({ x: a.x, y: a.y + by * v }, { x: b.x, y: a.y + by * v });
          if (d.labels !== false) {
            plainText(String(v), a.x + bx * v, Math.min(a.y, b.y) - 4, c, 0.5);
            plainText(String(v), Math.min(a.x, b.x) - 4, a.y + by * v + 4, c, 1);
          }
        });
        stroke(c, 1, "solid"); seg(a, b); seg({ x: a.x, y: b.y }, { x: b.x, y: a.y });
        HC.h = [a, b];
        break;
      }
      case "xabcd": case "abcd": case "trianglep": case "elliott5": case "elliott3": case "hs": {
        var labs = { xabcd: ["X", "A", "B", "C", "D"], abcd: ["A", "B", "C", "D"], trianglep: ["A", "B", "C", "D"],
                     elliott5: ["(0)", "(1)", "(2)", "(3)", "(4)", "(5)"], elliott3: ["(0)", "(A)", "(B)", "(C)"],
                     hs: ["", "Left shoulder", "", "Head", "", "Right shoulder", ""] }[typ];
        var mv = function (q, r) { return Math.abs(q.p - r.p); };
        if (typ === "xabcd") {
          fillPoly([P[0], P[1], P[2]], c, 0.1 * fa); if (P[4]) fillPoly([P[2], P[3], P[4]], c, 0.1 * fa);
        } else if (typ === "trianglep" && P[3]) fillPoly(P, c, 0.08 * fa);
        polyline(P);
        stroke(c, 1, "dash");
        if (typ === "xabcd") {
          if (P[2]) { seg(P[0], P[2]); ratioOn(P[0], P[2], mv(A[2], A[1]) / (mv(A[1], A[0]) || 1)); }
          if (P[3]) { seg(P[1], P[3]); ratioOn(P[1], P[3], mv(A[3], A[2]) / (mv(A[2], A[1]) || 1)); }
          if (P[4]) { seg(P[2], P[4]); ratioOn(P[2], P[4], mv(A[4], A[3]) / (mv(A[3], A[2]) || 1));
                      seg(P[0], P[4]); ratioOn(P[0], P[4], mv(A[4], A[1]) / (mv(A[1], A[0]) || 1)); }
        } else if (typ === "abcd") {
          if (P[2]) { seg(P[0], P[2]); ratioOn(P[0], P[2], mv(A[2], A[1]) / (mv(A[1], A[0]) || 1)); }
          if (P[3]) { seg(P[1], P[3]); ratioOn(P[1], P[3], mv(A[3], A[2]) / (mv(A[2], A[1]) || 1)); }
        } else if (typ === "trianglep") {
          if (P[2]) seg(extend(P[0], P[2], false, true)[0], extend(P[0], P[2], false, true)[1]);
          if (P[3]) seg(extend(P[1], P[3], false, true)[0], extend(P[1], P[3], false, true)[1]);
        } else if (typ === "hs" && P[4]) {
          var nk = extend(P[2], P[4], false, true);
          stroke(c, Math.max(1, w), "dash"); seg(nk[0], nk[1]);
          plainText("Neckline", P[4].x + 6, P[4].y + 14, c, 0);
        }
        patternPoints(P, labs, c);
        HC.h = P;
        break;
      }
      case "pos": case "short": {
        if (!b) return;
        var entry = A[0].p, stop = A[1].p;
        var tgt = A[2] ? A[2].p : entry + (entry - stop) * 2;
        var yE = Y(entry), yS = Y(stop), yT = Y(tgt);
        if (yE == null || yS == null || yT == null) return;
        var xL = Math.min(a.x, b.x), xR = Math.max(a.x, b.x);
        if (xR - xL < 40) xR = xL + 90;
        var gp = tok("--gain"), bd = tok("--loss");
        fillRect(xL, yE, xR - xL, yS - yE, bd, 0.16);
        fillRect(xL, yE, xR - xL, yT - yE, gp, 0.16);
        stroke(tok("--text-secondary"), 1.2, "solid");
        seg({ x: xL, y: yE }, { x: xR, y: yE });
        var risk = Math.abs(entry - stop), rew = Math.abs(tgt - entry), longSide = tgt >= entry;
        var tl = "Target " + fmt(tgt) + "  " + pctS(entry ? (tgt - entry) / entry * 100 : 0) + "  " + (risk ? (rew / risk).toFixed(2) : "–") + "R";
        var sl = "Stop " + fmt(stop) + "  " + pctS(entry ? (stop - entry) / entry * 100 : 0);
        var mid2 = (longSide ? "Long" : "Short") + " " + fmt(entry);
        if (d.acct && d.risk && risk) {
          var qty = Math.floor(d.acct * d.risk / 100 / risk);
          mid2 += "  Qty " + qty + "  Risk ₹" + fmt(qty * risk, 0);
        }
        /* Where it stands now, once price has reached the box. */
        var lastR = W.rows[W.rows.length - 1];
        if (lastR && lastR.time >= A[0].t && risk) {
          var cur = lastR.close, pnl = longSide ? cur - entry : entry - cur;
          mid2 += "  Now " + (pnl >= 0 ? "+" : "") + (pnl / risk).toFixed(2) + "R";
          var yc = Y(cur);
          if (yc != null && Math.min(yS, yT) <= yc && yc <= Math.max(yS, yT)) {
            stroke(tok("--text-secondary"), 1, "dot"); seg({ x: xL, y: yc }, { x: xR, y: yc });
          }
        }
        label(tl, xL + 4, yT + (yT > yE ? 12 : -12), gp, tok("--on-accent"), 0);
        label(sl, xL + 4, yS + (yS > yE ? 12 : -12), bd, tok("--on-accent"), 0);
        label(mid2, xL + 4, yE, tok("--accent"), tok("--on-accent"), 0);
        HC.h = [{ x: a.x, y: yE, i: 0 }, { x: b.x, y: yS, i: 1 }, { x: b.x, y: yT, i: 2 }];
        break;
      }
      case "ruler": case "prange": case "drange": {
        if (!b) return;
        var e1 = A[0].p, f1 = A[1].p, pct1 = e1 ? (f1 - e1) / e1 * 100 : 0;
        var bars2 = Math.round(tToL(A[1].t) - tToL(A[0].t)), upd = f1 >= e1;
        var kc = typ === "drange" ? (asColor(d.color) || c) : (upd ? tok("--gain") : tok("--loss"));
        if (typ === "prange") {
          var xa = Math.min(a.x, b.x), xb = Math.max(a.x, b.x); if (xb - xa < 30) xb = xa + 60;
          fillRect(xa, a.y, xb - xa, b.y - a.y, kc, 0.12);
          stroke(kc, 1.2, "solid");
          seg({ x: xa, y: a.y }, { x: xb, y: a.y }); seg({ x: xa, y: b.y }, { x: xb, y: b.y });
          var cx = (xa + xb) / 2; seg({ x: cx, y: a.y }, { x: cx, y: b.y }); arrowHead({ x: cx, y: a.y }, { x: cx, y: b.y }, kc, 1);
          label((f1 - e1 >= 0 ? "+" : "") + fmt(f1 - e1) + "  (" + pctS(pct1) + ")", cx, Math.max(a.y, b.y) + 14, kc, onWhite(kc), 0.5);
        } else if (typ === "drange") {
          var ya = Math.min(a.y, b.y), yb = Math.max(a.y, b.y); if (yb - ya < 30) yb = ya + 40;
          fillRect(a.x, ya, b.x - a.x, yb - ya, kc, 0.1);
          stroke(kc, 1.2, "solid");
          seg({ x: a.x, y: ya }, { x: a.x, y: yb }); seg({ x: b.x, y: ya }, { x: b.x, y: yb });
          var cy = (ya + yb) / 2; seg({ x: a.x, y: cy }, { x: b.x, y: cy }); arrowHead({ x: a.x, y: cy }, { x: b.x, y: cy }, kc, 1);
          var i0d = idxOf(Math.min(A[0].t, A[1].t)), i1d = idxOf(Math.max(A[0].t, A[1].t)), vs = 0;
          for (k = i0d; k <= i1d; k++) vs += (W.rows[k] && W.rows[k].volume) || 0;
          label(Math.abs(bars2) + " bars, " + span(A[1].t - A[0].t) + "\nVolume " + fmtV(vs), (a.x + b.x) / 2, yb + 22, kc, onWhite(kc), 0.5);
        } else {
          fillRect(a.x, a.y, b.x - a.x, b.y - a.y, kc, 0.12);
          stroke(kc, 1.5, "dash"); seg(a, b); arrowHead(a, b, kc, 1);
          label((pct1 >= 0 ? "+" : "") + pct1.toFixed(2) + "%   " + fmt(f1 - e1) + "\n" + Math.abs(bars2) + " bars, " + span(A[1].t - A[0].t),
                (a.x + b.x) / 2, Math.min(a.y, b.y) - 22, kc, onWhite(kc), 0.5);
        }
        HC.h = [a, b];
        break;
      }
      case "avwap": {
        var ia = Math.max(0, Math.ceil(tToL(A[0].t) - 0.5));
        if (!W.D || ia >= W.rows.length) { HC.h = [a]; break; }
        var av = M.anchoredVwap(W.D.h, W.D.l, W.D.c, W.D.v, ia);
        var pts2 = [];
        var j0 = Math.max(ia, Math.floor(g.from) - 1), j1 = Math.min(av.length - 1, Math.ceil(g.to) + 1);
        for (k = j0; k <= j1; k++) if (ok(av[k])) pts2.push({ x: g.x(k), y: Y(av[k]) });
        polyline(pts2);
        var last2 = av[av.length - 1];
        if (ok(last2) && pts2.length) label("AVWAP " + fmt(last2), pts2[pts2.length - 1].x + 6, pts2[pts2.length - 1].y, c, onWhite(c), 0);
        HC.h = [{ x: g.x(ia), y: Y(av[ia]), i: 0 }];
        break;
      }
      case "vprofile": {
        if (!b || !W.D) return;
        var va = idxOf(Math.min(A[0].t, A[1].t)), vb = idxOf(Math.max(A[0].t, A[1].t));
        var vp = M.volumeProfile(W.D.h, W.D.l, W.D.c, W.D.o, W.D.v, va, vb, d.rowsN || 24);
        var xa2 = g.x(va), xb2 = g.x(vb);
        if (!vp) { seg({ x: xa2, y: a.y }, { x: xb2, y: a.y }); HC.h = [a, b]; break; }
        var maxW = Math.max(40, (xb2 - xa2) * 0.6);
        var yt = Y(vp.hi), yb2 = Y(vp.lo);
        stroke(tok("--border"), 1, "solid");
        fillRect(xa2, yt, xb2 - xa2, yb2 - yt, c, 0.03);
        /* Value area: the 70% of volume around the busiest row. */
        var tot = vp.total, acc = vp.up[vp.poc] + vp.dn[vp.poc], lo2 = vp.poc, hi2 = vp.poc;
        while (acc < tot * 0.7 && (lo2 > 0 || hi2 < vp.up.length - 1)) {
          var nl = lo2 > 0 ? vp.up[lo2 - 1] + vp.dn[lo2 - 1] : -1, nh = hi2 < vp.up.length - 1 ? vp.up[hi2 + 1] + vp.dn[hi2 + 1] : -1;
          if (nh >= nl) { hi2++; acc += nh; } else { lo2--; acc += nl; }
        }
        for (k = 0; k < vp.up.length; k++) {
          var y1 = Y(vp.lo + k * vp.step), y2 = Y(vp.lo + (k + 1) * vp.step);
          if (y1 == null || y2 == null) continue;
          var hgt = Math.max(1, Math.abs(y1 - y2) - 1), wu = vp.max ? vp.up[k] / vp.max * maxW : 0, wd = vp.max ? vp.dn[k] / vp.max * maxW : 0;
          var inVa = k >= lo2 && k <= hi2;
          ctx.globalAlpha = inVa ? 0.55 : 0.28; ctx.fillStyle = upC(); ctx.fillRect(xa2, Math.min(y1, y2), wu, hgt);
          ctx.fillStyle = dnC(); ctx.fillRect(xa2 + wu, Math.min(y1, y2), wd, hgt); ctx.globalAlpha = 1;
        }
        var pocP = vp.lo + (vp.poc + 0.5) * vp.step, yp = Y(pocP);
        stroke(c, 2, "solid"); seg({ x: xa2, y: yp }, { x: xb2, y: yp });
        label("POC " + fmt(pocP), xb2 + 4, yp, c, onWhite(c), 0);
        HC.h = [{ x: X(g, A[0].t), y: a.y, i: 0 }, { x: X(g, A[1].t), y: b.y, i: 1 }];
        break;
      }
      case "rect": case "ellipse": case "triangle": {
        if (typ === "triangle") {
          if (P.length < 3) { polyline(P); HC.h = P; break; }
          fillPoly(P, c, 0.1 * fa); polyline(P, true); HC.h = P; break;
        }
        if (!b) return;
        if (typ === "rect") {
          fillRect(a.x, a.y, b.x - a.x, b.y - a.y, c, 0.1 * fa);
          ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
          var xr2 = Math.min(a.x, b.x), yr2 = Math.min(a.y, b.y), wr = Math.abs(b.x - a.x), hr = Math.abs(b.y - a.y);
          HC.s.push([xr2, yr2, xr2 + wr, yr2], [xr2, yr2 + hr, xr2 + wr, yr2 + hr], [xr2, yr2, xr2, yr2 + hr], [xr2 + wr, yr2, xr2 + wr, yr2 + hr]);
          HC.h = [a, b, { x: a.x, y: b.y, i: "ab" }, { x: b.x, y: a.y, i: "ba" }];
        } else {
          var ecx = (a.x + b.x) / 2, ecy = (a.y + b.y) / 2, erx = Math.abs(b.x - a.x) / 2, ery = Math.abs(b.y - a.y) / 2;
          ctx.beginPath(); ctx.ellipse(ecx, ecy, Math.max(1, erx), Math.max(1, ery), 0, 0, Math.PI * 2);
          var ga2 = ctx.globalAlpha; ctx.fillStyle = c; ctx.globalAlpha = ga2 * 0.1 * fa; ctx.fill(); ctx.globalAlpha = ga2; ctx.stroke();
          HC.e.push([ecx, ecy, erx, ery]);
          HC.h = [a, b];
        }
        if (d.text) {
          ctx.font = "500 " + (d.fs || 13) + "px 'Inter', system-ui, sans-serif"; ctx.fillStyle = c;
          var tw = ctx.measureText(d.text).width;
          ctx.fillText(d.text, (a.x + b.x) / 2 - tw / 2, (a.y + b.y) / 2 + 4);
        }
        break;
      }
      case "path": case "brush": case "hilite": {
        if (typ === "hilite") { ctx.lineWidth = w; ctx.globalAlpha *= 0.4; ctx.setLineDash([]); }
        if (typ === "path" && d.closed && P.length > 2) fillPoly(P, c, 0.08 * fa);
        polyline(P, typ === "path" && d.closed);
        if (typ === "path" && d.arrow && P.length > 1) arrowHead(P[P.length - 2], P[P.length - 1], c, w);
        ctx.globalAlpha = ghost ? 0.75 : 1;
        HC.h = typ === "path" ? P : null;
        break;
      }
      case "text": {
        var fs = d.fs || 14, tl2 = (d.text || (ghost ? "Text" : "")).split("\n");
        ctx.font = "500 " + fs + "px 'Inter', system-ui, sans-serif";
        var tw2 = 0; tl2.forEach(function (s) { tw2 = Math.max(tw2, ctx.measureText(s).width); });
        var th = tl2.length * fs * 1.3;
        if (d.bg) { ctx.fillStyle = c; var ga3 = ctx.globalAlpha; ctx.globalAlpha = ga3 * 0.14; roundRect(a.x - 6, a.y - fs - 4, tw2 + 12, th + 8, 4); ctx.fill(); ctx.globalAlpha = ga3; }
        ctx.fillStyle = c;
        tl2.forEach(function (s, j) { ctx.fillText(s, a.x, a.y + j * fs * 1.3); });
        HC.b.push([a.x - 6, a.y - fs - 4, tw2 + 12, th + 8]);
        HC.h = [{ x: a.x - 6, y: a.y - fs - 4, i: 0 }];
        break;
      }
      case "callout": {
        if (!b) { HC.h = [a]; break; }
        var fs2 = d.fs || 13, tx2 = (d.text || (ghost ? "Note" : "Note")).split("\n");
        ctx.font = "500 " + fs2 + "px 'Inter', system-ui, sans-serif";
        var cw2 = 0; tx2.forEach(function (s) { cw2 = Math.max(cw2, ctx.measureText(s).width); });
        var bw = cw2 + 16, bh = tx2.length * fs2 * 1.35 + 12;
        stroke(c, w, sty); seg(a, { x: b.x + bw / 2, y: b.y + bh / 2 });
        ctx.setLineDash([]); ctx.fillStyle = c; roundRect(b.x, b.y, bw, bh, 6); ctx.fill();
        ctx.fillStyle = onWhite(c);
        tx2.forEach(function (s, j) { ctx.fillText(s, b.x + 8, b.y + 6 + fs2 + j * fs2 * 1.35); });
        ctx.beginPath(); ctx.arc(a.x, a.y, 3, 0, Math.PI * 2); ctx.fillStyle = c; ctx.fill();
        HC.b.push([b.x, b.y, bw, bh]);
        HC.h = [a, b];
        break;
      }
      case "pricelabel": {
        var lb = label(fmt(A[0].p) + (d.text ? "  " + d.text : ""), a.x + 10, a.y - 18, c, onWhite(c), 0);
        ctx.fillStyle = c; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(lb.x + 6, lb.y + lb.h); ctx.lineTo(lb.x + 16, lb.y + lb.h); ctx.closePath(); ctx.fill();
        HC.h = [a];
        break;
      }
      case "arrowup": case "arrowdown": {
        var upw = typ === "arrowup", s0 = 9 + w * 2, ay = a.y + (upw ? 6 : -6);
        ctx.setLineDash([]); ctx.fillStyle = c; ctx.beginPath();
        if (upw) { ctx.moveTo(a.x, ay); ctx.lineTo(a.x + s0 * 0.7, ay + s0); ctx.lineTo(a.x + s0 * 0.25, ay + s0); ctx.lineTo(a.x + s0 * 0.25, ay + s0 * 1.8); ctx.lineTo(a.x - s0 * 0.25, ay + s0 * 1.8); ctx.lineTo(a.x - s0 * 0.25, ay + s0); ctx.lineTo(a.x - s0 * 0.7, ay + s0); }
        else { ctx.moveTo(a.x, ay); ctx.lineTo(a.x + s0 * 0.7, ay - s0); ctx.lineTo(a.x + s0 * 0.25, ay - s0); ctx.lineTo(a.x + s0 * 0.25, ay - s0 * 1.8); ctx.lineTo(a.x - s0 * 0.25, ay - s0 * 1.8); ctx.lineTo(a.x - s0 * 0.25, ay - s0); ctx.lineTo(a.x - s0 * 0.7, ay - s0); }
        ctx.closePath(); ctx.fill();
        HC.b.push([a.x - s0 * 0.7, upw ? ay : ay - s0 * 1.8, s0 * 1.4, s0 * 1.8]);
        if (d.text) plainText(d.text, a.x, upw ? ay + s0 * 1.8 + 14 : ay - s0 * 1.8 - 5, c, 0.5, "500 12px 'Inter', system-ui, sans-serif");
        HC.h = [a];
        break;
      }
      case "flag": {
        ctx.setLineDash([]); ctx.strokeStyle = c; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(a.x, a.y - 30); ctx.stroke();
        ctx.fillStyle = c; ctx.beginPath(); ctx.moveTo(a.x, a.y - 30); ctx.lineTo(a.x + 18, a.y - 30); ctx.lineTo(a.x + 13, a.y - 24); ctx.lineTo(a.x + 18, a.y - 18); ctx.lineTo(a.x, a.y - 18); ctx.closePath(); ctx.fill();
        HC.b.push([a.x - 3, a.y - 31, 22, 32]);
        if (d.text) plainText(d.text, a.x + 22, a.y - 20, c, 0, "500 12px 'Inter', system-ui, sans-serif");
        HC.h = [a];
        break;
      }
      default:
        polyline(P);
    }
  }

  /* Price tags on the axis for level lines and for whatever is selected, and
     date tags along the bottom: where the drawing meets the scales. */
  function axisTags(g) {
    if (W.hideAll) return;
    var tags = [];
    W.drawings.forEach(function (d) {
      if (d.hidden || !d.pts.length) return;
      if (d.type === "hline" || d.type === "hray" || d.type === "cross") tags.push({ p: d.pts[0].p, c: asColor(d.color || W.color) });
    });
    var times = [];
    if (W.sel && !W.sel.hidden) {
      var s = W.sel;
      if (s.type !== "brush" && s.type !== "hilite") {
        s.pts.forEach(function (q) {
          if (s.type !== "vline") tags.push({ p: q.p, c: tok("--accent") });
          if (s.type !== "hline") times.push(q.t);
        });
      }
    }
    W.drawings.forEach(function (d) { if (!d.hidden && (d.type === "vline" || d.type === "cross") && d !== W.sel) times.push(d.pts[0].t); });
    ctx.font = labelFont(); ctx.setLineDash([]);
    tags.forEach(function (t) {
      var y = Y(t.p); if (y == null || y < 0 || y > g.h) return;
      ctx.fillStyle = t.c; ctx.fillRect(g.w + 1, y - 9, g.W - g.w - 1, 18);
      ctx.fillStyle = onWhite(t.c); ctx.fillText(fmt(t.p), g.w + 6, y + 4);
    });
    var intra = !!tfOf(L.tf).intra;
    times.forEach(function (t) {
      var x = X(g, t); if (x < 0 || x > g.w) return;
      var s2 = fmtT(t, intra), tw = ctx.measureText(s2).width + 12;
      ctx.fillStyle = tok("--accent"); ctx.fillRect(x - tw / 2, g.h - 18, tw, 18);
      ctx.fillStyle = tok("--on-accent"); ctx.fillText(s2, x - tw / 2 + 6, g.h - 5);
    });
  }

  /* ── hit testing ───────────────────────────────────────────────────────── */

  function distSeg(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
    if (!l2) return Math.hypot(px - x1, py - y1);
    var t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }
  function inPoly(px, py, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / ((yj - yi) || 1e-9) + xi)) inside = !inside;
    }
    return inside;
  }
  function hit(px, py) {
    if (W.hideAll) return null;
    /* Hit-testing reads what the last paint recorded; if a paint is still
       waiting for its frame, the record is stale, so paint now. */
    if (raf) { cancelAnimationFrame(raf); raf = null; paint(); }
    var i, d, C, k;
    /* Handles of the selected drawing first: they sit on top of everything. */
    if (W.sel && HITS[W.sel.id] && HITS[W.sel.id].h) {
      var hs = HITS[W.sel.id].h;
      for (k = 0; k < hs.length; k++) {
        if (hs[k] && hs[k].y != null && Math.hypot(px - hs[k].x, py - hs[k].y) <= HANDLE + (IS_TOUCH ? 8 : 4))
          return { d: W.sel, handle: hs[k].i != null ? hs[k].i : k };
      }
    }
    for (i = W.drawings.length - 1; i >= 0; i--) {
      d = W.drawings[i]; C = HITS[d.id];
      if (!C || d.hidden) continue;
      for (k = 0; k < C.s.length; k++) if (distSeg(px, py, C.s[k][0], C.s[k][1], C.s[k][2], C.s[k][3]) <= TOL) return { d: d, handle: null };
      for (k = 0; k < C.b.length; k++) {
        var bb = C.b[k];
        if (px >= bb[0] - 2 && px <= bb[0] + bb[2] + 2 && py >= bb[1] - 2 && py <= bb[1] + bb[3] + 2) return { d: d, handle: null };
      }
      for (k = 0; k < C.p.length; k++) if (inPoly(px, py, C.p[k])) return { d: d, handle: null };
      for (k = 0; k < C.e.length; k++) {
        var e = C.e[k], q = Math.pow((px - e[0]) / (e[2] || 1), 2) + Math.pow((py - e[1]) / (e[3] || 1), 2);
        if (q <= 1.08) return { d: d, handle: null };
      }
    }
    return null;
  }

  /* ══════════════════════════════════════════════════════════════════════
     INTERACTION
     ══════════════════════════════════════════════════════════════════════ */

  function local(e) {
    var r = cv.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }
  function anchorAt(pt) {
    var g = geo(); if (!g) return null;
    var p = pAt(pt.y); if (p == null) return null;
    return snap(lToT(g.l(pt.x)), p, pt.y);
  }

  function setMode(m, tool) {
    W.mode = m; W.tool = tool || null; W.pending = []; W.preview = null;
    cv.classList.toggle("live", m !== "pan");
    /* While a tool is out, the legend's buttons and the zoom buttons that
       appear on hover step aside: a click meant for the chart must reach it. */
    root.classList.toggle("drawing", m !== "pan");
    cv.classList.toggle("erase", m === "erase");
    root.querySelectorAll("#cw-rail .cw-t[data-t]").forEach(function (b) {
      b.classList.toggle("on", m === "draw" ? b.dataset.t === tool : b.dataset.t === m);
    });
    root.querySelectorAll("#cw-rail .cw-grp").forEach(function (gEl) {
      var gr = GROUPS.filter(function (x) { return x.g === gEl.dataset.g; })[0];
      gEl.classList.toggle("on", m === "draw" && gr && gr.tools.indexOf(tool) >= 0);
    });
    if (m === "pan") note(IS_TOUCH ? "Drag to pan, pinch to zoom. Tap a drawing to select it." :
                          "Drag to pan, scroll to zoom. Click a drawing to select it; right-click for more.");
    else if (m === "erase") note("Tap a drawing to remove it. Esc stops erasing.");
    else if (m === "replay-pick") note("Tap the candle the replay should start from. Esc cancels.");
    else note((T[tool] && T[tool].hint || "Tap the chart to place this.") + " Esc cancels.");
    render();
  }

  function pickTool(t) {
    var gr = groupOf(t);
    if (gr) {
      W.lastTool[gr.g] = t;
      sset("altaha.charts.v2.tools", W.lastTool);
      var gEl = root.querySelector('.cw-grp[data-g="' + gr.g + '"] .cw-t');
      if (gEl) { gEl.dataset.t = t; gEl.dataset.tip = T[t].lab; gEl.setAttribute("aria-label", T[t].lab); gEl.innerHTML = svg(t); }
    }
    W.sel = null; inspector();
    if (W.hideAll) { W.hideAll = false; railState(); toast("Drawings were hidden; they are shown again so you can see this one."); }
    setMode("draw", t);
  }

  /* Moving the crosshair redraws the price chart and every pane, so it is
     done once per frame however many pointer events arrive in it. */
  var xhPt = null, xhRaf = null;
  function crosshairAt(pt) {
    xhPt = pt;
    if (xhRaf) return;
    xhRaf = requestAnimationFrame(function () { xhRaf = null; if (xhPt) crosshairNow(xhPt); });
  }
  function crosshairNow(pt) {
    if (!W.chart || !W.main || typeof W.chart.setCrosshairPosition !== "function") return;
    var g = geo(); if (!g) return;
    var i = clamp(Math.round(g.l(pt.x)), 0, W.disp.length - 1), r = W.disp[i];
    var p = pAt(pt.y);
    if (!r || p == null) return;
    try { W.chart.setCrosshairPosition(p, r.time, W.main); } catch (e) {}
    legendAt(i);
  }

  function onDown(e) {
    if (e.button === 2) return;
    /* No mousedown default: it would move focus to the workspace, out of a
       text box this very press is about to open. */
    if (e.cancelable) e.preventDefault();
    closePops();
    cv.setPointerCapture && cv.setPointerCapture(e.pointerId);
    W.ptrs[e.pointerId] = local(e);
    if (Object.keys(W.ptrs).length === 2) { W.dragging = null; W.preview = null; startPinch(); return; }
    var pt = local(e);

    if (W.mode === "erase") {
      var he = hit(pt.x, pt.y);
      if (he) { del(he.d); note("Removed. Ctrl+Z brings it back."); }
      return;
    }
    if (W.mode === "replay-pick") {
      var g0 = geo(); if (!g0) return;
      var idx = clamp(Math.round(g0.l(pt.x)), 1, W.full.length - 1);
      setMode("pan");
      startReplay(idx);
      return;
    }
    if (W.mode === "pan") {
      var hp = hit(pt.x, pt.y);
      if (!hp) { if (W.sel) select(null); return; }
      W.sel = hp.d;
      W.dragging = { h: hp.handle, last: pt, moved: false, start: pt };
      inspector(); sideRefresh(); render();
      return;
    }

    /* Drawing. */
    var t = W.tool, a = anchorAt(pt); if (!a) return;
    if (t === "brush" || t === "hilite") {
      W.preview = newDrawing(t, [a]);
      W.dragging = { brush: true };
      return;
    }
    if (t === "path") {
      var last = W.pending[W.pending.length - 1], g1 = geo();
      if (last && g1) {
        var lx = X(g1, last.t), ly = Y(last.p), fx = X(g1, W.pending[0].t), fy = Y(W.pending[0].p);
        if (Math.hypot(lx - pt.x, ly - pt.y) < 10) { finishPath(false); return; }
        if (W.pending.length > 2 && Math.hypot(fx - pt.x, fy - pt.y) < 10) { finishPath(true); return; }
      }
      W.pending.push(a);
      W.preview = newDrawing("path", W.pending.concat([a]));
      return;
    }
    if (e.shiftKey && LINES[t] && W.pending.length === 1) a.p = W.pending[0].p;
    W.pending.push(a);
    var n = need(t) || 1;
    if (W.pending.length >= n) { place(); return; }
    /* Press, drag, release also places a two-point tool. */
    if (n === 2 && W.pending.length === 1) W.dragging = { place: true, start: pt };
    W.preview = previewOf(W.pending.concat([a]));
    render();
  }

  function previewOf(pts) {
    var t = W.tool, o = newDrawing(t, pts.slice());
    if ((t === "pos" || t === "short") && pts.length >= 2) {
      var en = pts[0].p, sp = pts[1].p;
      if (t === "pos" && sp > en) sp = en - (sp - en);
      if (t === "short" && sp < en) sp = en + (en - sp);
      o.pts = [pts[0], { t: pts[1].t, p: sp }, { t: pts[1].t, p: en + (en - sp) * 2 }];
    }
    return o;
  }

  function place() {
    var o = previewOf(W.pending);
    W.pending = []; W.preview = null; W.dragging = null;
    if (o.type === "pos" || o.type === "short") {
      var tl = tToL(o.pts[0].t), tr = tToL(o.pts[1].t);
      if (Math.abs(tr - tl) < 3) { o.pts[1].t = lToT(tl + 20); o.pts[2].t = o.pts[1].t; }
    }
    commit(o);
    if (TEXTUAL[o.type]) editText(o, true);
  }

  function finishPath(closed) {
    var pts = W.pending.slice();
    /* A double-click lands two clicks on the same spot; keep one. */
    var g = geo();
    if (g && pts.length > 1) {
      var p1 = pts[pts.length - 1], p0 = pts[pts.length - 2];
      if (Math.hypot(X(g, p1.t) - X(g, p0.t), Y(p1.p) - Y(p0.p)) < 4) pts.pop();
    }
    W.pending = []; W.preview = null;
    if (pts.length < 2) { render(); return; }
    var o = newDrawing("path", pts); if (closed) o.closed = true;
    commit(o);
  }

  function commit(o) {
    push();
    W.drawings.push(o);
    W.sel = o;
    save(); inspector(); sideRefresh();
    if (L.stay && !TEXTUAL[o.type]) { var t = W.tool; setMode("draw", t); W.sel = o; inspector(); }
    else setMode("pan");
    render();
  }

  function onMove(e) {
    var pt = local(e);
    if (W.ptrs[e.pointerId]) W.ptrs[e.pointerId] = pt;
    if (W.pinch) { movePinch(); return; }

    if (W.dragging) {
      if (W.dragging.brush) {
        var ab = anchorAt(pt);
        if (ab && W.preview) { W.preview.pts.push(ab); render(); }
        return;
      }
      if (W.dragging.place) {
        var ap = anchorAt(pt); if (!ap) return;
        if (e.shiftKey && LINES[W.tool]) ap.p = W.pending[0].p;
        W.preview = previewOf(W.pending.concat([ap]));
        crosshairAt(pt); render(); return;
      }
      var d = W.sel; if (!d) return;
      if (!W.dragging.moved && Math.hypot(pt.x - W.dragging.start.x, pt.y - W.dragging.start.y) < 3) return;
      if (d.locked || W.lockAll) { if (!W.dragging.warned) { note("This drawing is locked. Unlock it to move it."); W.dragging.warned = 1; } return; }
      var a1 = anchorAt(pt); if (!a1) return;
      if (!W.dragging.moved) push();
      var h = W.dragging.h;
      if (h != null) {
        if (h === "ab") { d.pts[0].t = a1.t; d.pts[1].p = a1.p; }
        else if (h === "ba") { d.pts[1].t = a1.t; d.pts[0].p = a1.p; }
        else if (d.type === "hline" || d.type === "hray") { d.pts[0].p = a1.p; if (d.type === "hray") d.pts[0].t = a1.t; }
        else if (d.type === "vline") d.pts[0].t = a1.t;
        else if (d.type === "regchan" || d.type === "vprofile" || d.type === "avwap") d.pts[h] = { t: a1.t, p: d.pts[h].p };
        else if ((d.type === "pos" || d.type === "short") && h === 2) d.pts[2] = { t: d.pts[1].t, p: a1.p };
        else if ((d.type === "pos" || d.type === "short") && h === 1) { d.pts[1] = a1; if (d.pts[2]) d.pts[2].t = a1.t; }
        else if ((d.type === "pos" || d.type === "short") && h === 0) d.pts[0] = a1;
        else d.pts[h] = a1;
      } else {
        var g1 = geo(); if (!g1) return;
        var dx = pt.x - W.dragging.last.x, dy = pt.y - W.dragging.last.y;
        d.pts = d.pts.map(function (q) {
          var y = Y(q.p); if (y == null) return q;
          var np = pAt(y + dy);
          var nt = d.type === "hline" ? q.t : lToT(tToL(q.t) + dx / g1.k);
          return { t: nt, p: d.type === "vline" || np == null ? q.p : np };
        });
        W.dragging.last = pt;
      }
      W.dragging.moved = true;
      render(); return;
    }

    if (W.mode === "pan") {
      var hh = hit(pt.x, pt.y);
      cv.classList.toggle("live", !!hh);
      cv.classList.toggle("onhandle", !!(hh && hh.handle != null));
      W.hover = hh;
      return;
    }
    if (W.mode === "erase") { cv.classList.toggle("target", !!hit(pt.x, pt.y)); return; }
    crosshairAt(pt);
    if (W.tool && W.pending.length) {
      var ap2 = anchorAt(pt); if (!ap2) return;
      if (e.shiftKey && LINES[W.tool] && W.pending.length === 1) ap2.p = W.pending[0].p;
      W.preview = W.tool === "path" ? newDrawing("path", W.pending.concat([ap2])) : previewOf(W.pending.concat([ap2]));
      render();
    }
  }

  function onUp(e) {
    var pt = local(e);
    delete W.ptrs[e.pointerId];
    if (Object.keys(W.ptrs).length < 2) W.pinch = null;
    if (W.dragging && W.dragging.brush && W.preview) {
      var o = W.preview; W.preview = null; W.dragging = null;
      if (o.pts.length > 2) commit(o); else render();
      return;
    }
    if (W.dragging && W.dragging.place) {
      var st = W.dragging.start; W.dragging = null;
      /* A press dragged out to a second point; a click that wobbled a few
         pixels on a touchpad is still a click, so the bar is set high. */
      if (Math.hypot(pt.x - st.x, pt.y - st.y) > 14) {
        var a = anchorAt(pt);
        if (a) { if (e.shiftKey && LINES[W.tool]) a.p = W.pending[0].p; W.pending.push(a); place(); }
      }
      return;
    }
    if (W.dragging && W.dragging.moved) { save(); sideRefresh(); }
    W.dragging = null;
    render();
  }

  function onWheel(e) {
    e.preventDefault();
    var g = geo(); if (!g) return;
    var pt = local(e);
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      var dl = (e.shiftKey ? e.deltaY : e.deltaX) / g.k * 0.6;
      W.chart.timeScale().setVisibleLogicalRange({ from: g.from + dl, to: g.to + dl });
      render(); return;
    }
    var lc = g.l(pt.x), f = e.deltaY > 0 ? 1.12 : 0.89;
    var from = lc - (lc - g.from) * f, to = lc + (g.to - lc) * f;
    if (to - from < 6 || to - from > 20000) return;
    W.chart.timeScale().setVisibleLogicalRange({ from: from, to: to });
    render();
  }
  function startPinch() {
    var ids = Object.keys(W.ptrs), g = geo(); if (!g) return;
    var a = W.ptrs[ids[0]], b = W.ptrs[ids[1]];
    W.pinch = { d0: Math.abs(a.x - b.x) || 1, from: g.from, to: g.to, cx: g.l((a.x + b.x) / 2) };
  }
  function movePinch() {
    var ids = Object.keys(W.ptrs); if (ids.length < 2) return;
    var a = W.ptrs[ids[0]], b = W.ptrs[ids[1]];
    var f = W.pinch.d0 / (Math.abs(a.x - b.x) || 1);
    var from = W.pinch.cx - (W.pinch.cx - W.pinch.from) * f, to = W.pinch.cx + (W.pinch.to - W.pinch.cx) * f;
    if (to - from < 6 || to - from > 20000) return;
    W.chart.timeScale().setVisibleLogicalRange({ from: from, to: to });
    render();
  }

  function zoom(f) {
    var g = geo(); if (!g) return;
    var c = (g.from + g.to) / 2, h = (g.to - g.from) / 2 * f;
    if (h * 2 < 6) return;
    W.chart.timeScale().setVisibleLogicalRange({ from: c - h, to: c + h });
  }
  function scrollBars(n) {
    var g = geo(); if (!g) return;
    W.chart.timeScale().setVisibleLogicalRange({ from: g.from + n, to: g.to + n });
  }
  function resetView() {
    if (!W.chart) return;
    var n = W.disp.length, show = Math.min(n, IS_TOUCH ? 90 : 160);
    W.chart.timeScale().setVisibleLogicalRange({ from: n - show, to: n + 8 });
    try { W.chart.priceScale("right").applyOptions({ autoScale: true }); } catch (e) {}
    footState();
  }
  function rtButton(g) {
    var b = $("cw-rt"); if (!b) return;
    b.classList.toggle("on", !!(g && W.disp.length && g.to < W.disp.length - 2));
  }

  /* ══════════════════════════════════════════════════════════════════════
     SELECTION TOOLBAR, TEXT EDITING, MENUS AND DIALOGS
     ══════════════════════════════════════════════════════════════════════ */

  function inspector() {
    var d = W.sel;
    if (!d) { inspEl.classList.remove("on"); inspEl.innerHTML = ""; return; }
    var c = asColor(d.color || W.color);
    var h = '<span class="cw-i-name">' + esc((T[d.type] || {}).lab || d.type) + "</span>" +
      '<button type="button" data-x="color" title="Colour" aria-label="Colour"><i class="cw-sw-dot" style="background:' + esc(c) + '"></i></button>';
    if (d.type !== "arrowup" && d.type !== "arrowdown" && d.type !== "flag" && d.type !== "text" && d.type !== "pricelabel") {
      h += '<button type="button" data-x="width" title="Thickness" aria-label="Thickness"><i class="cw-wd-i" style="height:' + Math.min(6, d.width || 2) + 'px"></i></button>' +
           '<button type="button" data-x="style" title="Line style" aria-label="Line style"><i class="cw-st-i cw-st-' + (d.style || "solid") + '"></i></button>';
    }
    if (TEXTUAL[d.type]) h += '<button type="button" data-x="text" title="Edit text" aria-label="Edit text">' + svg("text") + "</button>";
    if (d.type === "hline" || d.type === "hray") h += '<button type="button" data-x="alert" class="' + (d.alert ? "on" : "") + '" title="Alert when price crosses" aria-label="Alert">' + svg("bell") + "</button>";
    h += '<button type="button" data-x="settings" title="Settings" aria-label="Settings">' + svg("gear") + "</button>" +
         '<button type="button" data-x="lock" class="' + (d.locked ? "on" : "") + '" title="' + (d.locked ? "Unlock" : "Lock") + '" aria-label="Lock">' + svg(d.locked ? "lock" : "unlock") + "</button>" +
         '<button type="button" data-x="clone" title="Clone" aria-label="Clone">' + svg("clone") + "</button>" +
         '<button type="button" data-x="del" class="cw-i-del" title="Remove (Delete)" aria-label="Remove">' + svg("trash") + "</button>";
    inspEl.innerHTML = h;
    inspEl.classList.add("on");
  }

  function inspAction(x, btn) {
    var d = W.sel; if (!d) return;
    if (x === "color") return colorPop(btn, d.color || W.color, function (c) { push(); d.color = W.color = c; if (d.type === "fib" || d.type === "fibext" || d.type === "fibtime" || d.type === "fibfan" || d.type === "gannfan" || d.type === "gannbox") d.mono = true; changed(); });
    if (x === "width") return listPop(btn, [1, 2, 3, 4].map(function (v) {
      return { html: '<i class="cw-wd-i" style="height:' + v + 'px;width:44px"></i>', on: (d.width || 2) === v, fn: function () { push(); d.width = W.width = v; changed(); } };
    }));
    if (x === "style") return listPop(btn, ["solid", "dash", "dot"].map(function (v) {
      return { html: '<i class="cw-st-i cw-st-' + v + '" style="width:44px"></i>', on: (d.style || "solid") === v, fn: function () { push(); d.style = v; changed(); } };
    }));
    if (x === "text") return editText(d, false);
    if (x === "alert") { push(); d.alert = !d.alert; d.fired = false; changed(); toast(d.alert ? "You will be told when price crosses " + fmt(d.pts[0].p) + "." : "Alert off."); if (d.alert) askNotify(); return; }
    if (x === "settings") return drawingSettings(d);
    if (x === "lock") { push(); d.locked = !d.locked; changed(); return; }
    if (x === "clone") return duplicate(d);
    if (x === "del") return del(d);
  }

  /* An input over the chart, where the text will sit, instead of a prompt(). */
  function editText(d, isNew) {
    var g = geo(); if (!g) return;
    var anchor = d.type === "callout" ? d.pts[1] : d.pts[0];
    var x = X(g, anchor.t), y = Y(anchor.p);
    var ta = document.createElement("textarea");
    ta.className = "cw-edit"; ta.value = d.text || ""; ta.rows = 2;
    ta.setAttribute("aria-label", "Text");
    ta.placeholder = "Type, then Enter";
    ta.style.left = clamp(x - 4, 4, box.clientWidth - 220) + "px";
    ta.style.top = clamp(y - 22, 4, box.clientHeight - 60) + "px";
    ta.style.color = asColor(d.color || W.color);
    box.appendChild(ta);
    /* Focused at once, so the first keys typed land in it rather than on the
       chart as shortcuts; and again after the click that placed it, whose
       default action would otherwise move focus to the workspace. */
    var born = Date.now();
    ta.focus();
    setTimeout(function () { if (!done) { ta.focus(); ta.select(); } }, 0);
    var before = d.text || "", done = false;
    function finish(keep) {
      if (done) return; done = true;
      var v = ta.value.replace(/\s+$/, "").slice(0, 400);
      ta.remove();
      if (!keep) { if (isNew && !before) { W.drawings = W.drawings.filter(function (q) { return q !== d; }); W.undo.pop(); W.sel = null; changed(); } return; }
      if (!v && isNew && d.type === "text") { W.drawings = W.drawings.filter(function (q) { return q !== d; }); W.undo.pop(); W.sel = null; changed(); return; }
      if (v !== before) { if (!isNew) push(); d.text = v; }
      changed();
    }
    ta.addEventListener("keydown", function (e) {
      e.stopPropagation();
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    ta.addEventListener("blur", function () {
      if (Date.now() - born < 400) { setTimeout(function () { if (!done) ta.focus(); }, 0); return; }
      finish(true);
    });
  }

  /* ── popovers, menus, dialogs ─────────────────────────────────────────── */

  var popEl = null;
  function closePops() {
    if (popEl) { popEl.remove(); popEl = null; }
    var s = $("cw-sug"); if (s) { s.remove(); $("cw-in").setAttribute("aria-expanded", "false"); }
  }
  /* Positioned inside #cw so it is visible in full screen too. */
  function pop(anchor, html, cls, at) {
    closePops();
    var p = document.createElement("div");
    p.className = "cw-pop " + (cls || "");
    p.setAttribute("role", "menu");
    if (typeof html === "string") p.innerHTML = html; else p.appendChild(html);
    root.appendChild(p);
    var R = root.getBoundingClientRect(), x, y;
    if (at) { x = at.x - R.left; y = at.y - R.top; }
    else {
      var r = anchor.getBoundingClientRect();
      var railSide = anchor.closest && anchor.closest(".cw-rail") && root.clientWidth > 780;
      x = railSide ? r.right - R.left + 6 : r.left - R.left;
      y = railSide ? r.top - R.top : r.bottom - R.top + 6;
    }
    var pw = p.offsetWidth, ph = p.offsetHeight;
    x = clamp(x, 6, Math.max(6, root.clientWidth - pw - 6));
    if (y + ph > root.clientHeight - 6) y = Math.max(6, root.clientHeight - ph - 6);
    p.style.left = x + "px"; p.style.top = y + "px";
    popEl = p;
    return p;
  }
  function listPop(anchor, items, at, cls) {
    var wrap = document.createElement("div");
    items.forEach(function (it) {
      if (it.sep) { var hr = document.createElement("hr"); wrap.appendChild(hr); return; }
      if (it.head) { var hd = document.createElement("div"); hd.className = "cw-pop-h"; hd.textContent = it.head; wrap.appendChild(hd); return; }
      var b = document.createElement("button");
      b.type = "button"; b.className = "cw-pop-i" + (it.on ? " on" : "") + (it.danger ? " danger" : "");
      b.setAttribute("role", "menuitem");
      b.innerHTML = (it.icon ? svg(it.icon) : "") + (it.html || "<span>" + esc(it.lab) + "</span>") + (it.key ? '<kbd>' + esc(it.key) + "</kbd>" : "");
      b.addEventListener("click", function (e) { e.stopPropagation(); closePops(); it.fn(); });
      wrap.appendChild(b);
    });
    return pop(anchor, wrap, cls, at);
  }
  function colorPop(anchor, cur, fn) {
    var wrap = document.createElement("div");
    wrap.className = "cw-colors";
    PALETTE.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "cw-sw" + (c.toLowerCase() === String(cur).toLowerCase() ? " on" : "");
      b.style.background = asColor(c); b.setAttribute("aria-label", "Colour " + c.replace(/^--/, "").replace(/-/g, " "));
      b.addEventListener("click", function (e) { e.stopPropagation(); closePops(); fn(c); });
      wrap.appendChild(b);
    });
    var lab = document.createElement("label");
    lab.className = "cw-custom";
    lab.innerHTML = '<input type="color" value="' + hex6(cur) + '"><span>Custom</span>';
    lab.querySelector("input").addEventListener("change", function (e) { closePops(); fn(e.target.value); });
    wrap.appendChild(lab);
    return pop(anchor, wrap, "cw-pop-colors");
  }

  var modalEl = null;
  function closeModal() { if (modalEl) { modalEl.remove(); modalEl = null; } }
  function modal(title, body, opts) {
    closeModal(); closePops();
    opts = opts || {};
    var back = document.createElement("div");
    back.className = "cw-modal-back";
    back.innerHTML = '<div class="cw-modal ' + (opts.cls || "") + '" role="dialog" aria-modal="true" aria-label="' + esc(title) + '">' +
      '<div class="cw-modal-h"><h3>' + esc(title) + '</h3><button type="button" class="cw-x" aria-label="Close">' + svg("x") + "</button></div>" +
      '<div class="cw-modal-b"></div>' +
      (opts.foot ? '<div class="cw-modal-f"></div>' : "") + "</div>";
    var b = back.querySelector(".cw-modal-b");
    if (typeof body === "string") b.innerHTML = body; else b.appendChild(body);
    if (opts.foot) {
      opts.foot.forEach(function (f) {
        var btn = document.createElement("button");
        btn.type = "button"; btn.className = "cw-btn" + (f.primary ? " primary" : "") + (f.danger ? " danger" : "");
        btn.textContent = f.lab;
        btn.addEventListener("click", function () { if (f.fn() !== false) closeModal(); });
        back.querySelector(".cw-modal-f").appendChild(btn);
      });
    }
    back.querySelector(".cw-x").addEventListener("click", closeModal);
    back.addEventListener("pointerdown", function (e) { if (e.target === back) closeModal(); });
    back.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Escape") closeModal(); });
    root.appendChild(back);
    modalEl = back;
    var f0 = back.querySelector("input,select,textarea,button:not(.cw-x)");
    if (f0 && !IS_TOUCH) f0.focus();
    return back;
  }

  function row(lab, control) { return '<label class="cw-row"><span>' + esc(lab) + "</span>" + control + "</label>"; }

  function drawingSettings(d) {
    var before = JSON.stringify(W.drawings), c = d.color || W.color;
    var h = '<div class="cw-form">';
    h += row("Colour", '<input type="color" data-k="color" value="' + hex6(c) + '">');
    h += row("Thickness", '<select data-k="width">' + [1, 2, 3, 4, 6, 8, 14].map(function (v) { return "<option" + ((d.width || 2) === v ? " selected" : "") + ">" + v + "</option>"; }).join("") + "</select>");
    h += row("Line", '<select data-k="style">' + [["solid", "Solid"], ["dash", "Dashed"], ["dot", "Dotted"]].map(function (v) { return '<option value="' + v[0] + '"' + ((d.style || "solid") === v[0] ? " selected" : "") + ">" + v[1] + "</option>"; }).join("") + "</select>");
    if (FILLED[d.type] || d.type === "path") h += row("Fill", '<input type="range" min="0" max="2" step="0.1" data-k="fill" value="' + (d.fill == null ? 1 : d.fill) + '">');
    if (EXTENDABLE[d.type]) {
      var eL = d.extL != null ? d.extL : d.type === "xline", eR = d.extR != null ? d.extR : (d.type === "ray" || d.type === "xline" || d.type === "fib" || d.type === "fibext");
      h += row("Extend left", '<input type="checkbox" data-k="extL"' + (eL ? " checked" : "") + ">");
      h += row("Extend right", '<input type="checkbox" data-k="extR"' + (eR ? " checked" : "") + ">");
    }
    if (d.type === "regchan") h += row("Deviations", '<input type="number" min="0.5" max="5" step="0.1" data-k="dev" value="' + (d.dev || 2) + '">');
    if (d.type === "vprofile") h += row("Rows", '<input type="number" min="6" max="100" step="1" data-k="rowsN" value="' + (d.rowsN || 24) + '">');
    if (d.type === "path") { h += row("Close the shape", '<input type="checkbox" data-k="closed"' + (d.closed ? " checked" : "") + ">"); h += row("Arrow at the end", '<input type="checkbox" data-k="arrow"' + (d.arrow ? " checked" : "") + ">"); }
    if (d.type === "pos" || d.type === "short") {
      h += row("Account size (₹)", '<input type="number" min="0" step="1000" data-k="acct" value="' + (d.acct || "") + '" placeholder="e.g. 500000">');
      h += row("Risk per trade (%)", '<input type="number" min="0" max="100" step="0.1" data-k="risk" value="' + (d.risk || "") + '" placeholder="e.g. 1">');
      h += row("Entry", '<input type="number" step="0.05" data-pt="0" value="' + d.pts[0].p.toFixed(2) + '">');
      h += row("Stop", '<input type="number" step="0.05" data-pt="1" value="' + d.pts[1].p.toFixed(2) + '">');
      if (d.pts[2]) h += row("Target", '<input type="number" step="0.05" data-pt="2" value="' + d.pts[2].p.toFixed(2) + '">');
    }
    if (d.type === "hline" || d.type === "hray" || d.type === "cross" || d.type === "pricelabel") {
      h += row("Price", '<input type="number" step="0.05" data-pt="0" value="' + d.pts[0].p.toFixed(2) + '">');
    }
    if (d.type === "hline" || d.type === "hray") h += row("Alert when price crosses", '<input type="checkbox" data-k="alert"' + (d.alert ? " checked" : "") + ">");
    if (TEXTUAL[d.type] || d.type === "rect" || d.type === "ellipse") h += row("Font size", '<input type="number" min="8" max="48" data-k="fs" value="' + (d.fs || 13) + '">');
    if (d.type === "text") h += row("Background", '<input type="checkbox" data-k="bg"' + (d.bg ? " checked" : "") + ">");
    if (d.type !== "brush" && d.type !== "hilite") h += '<label class="cw-row cw-row-wide"><span>Text</span><textarea data-k="text" rows="2" maxlength="400">' + esc(d.text || "") + "</textarea></label>";
    if (/^(fib|fibext|fibtime|fibfan|gannfan|gannbox)$/.test(d.type)) {
      h += row("One colour for every level", '<input type="checkbox" data-k="mono"' + (d.mono ? " checked" : "") + ">");
      h += row("Show labels", '<input type="checkbox" data-k="labels"' + (d.labels !== false ? " checked" : "") + ">");
    }
    if (d.type === "fib" || d.type === "fibext") {
      h += '<div class="cw-levels"><span>Levels</span>' + levelsOf(d).map(function (lv, i) {
        return '<label><input type="checkbox" data-lv-on="' + i + '"' + (lv.on !== false ? " checked" : "") + '><input type="number" step="0.001" data-lv="' + i + '" value="' + lv.v + '"></label>';
      }).join("") + '<button type="button" class="cw-btn" data-addlv="1">Add a level</button></div>';
    }
    h += row("Locked", '<input type="checkbox" data-k="locked"' + (d.locked ? " checked" : "") + ">");
    h += "</div>";
    var m = modal((T[d.type] || {}).lab || "Drawing", h, { foot: [
      { lab: "Remove", danger: true, fn: function () { W.undo.push(before); W.redo = []; W.drawings = W.drawings.filter(function (q) { return q !== d; }); W.sel = null; changed(); } },
      { lab: "Cancel", fn: function () { restore(before); } },
      { lab: "Done", primary: true, fn: function () { if (JSON.stringify(W.drawings) !== before) { W.undo.push(before); W.redo = []; } changed(); } }
    ] });
    function apply(el) {
      var k = el.dataset.k;
      if (k) {
        var v = el.type === "checkbox" ? el.checked : el.type === "number" || el.type === "range" ? parseFloat(el.value) : el.value;
        if (k === "width" || k === "fs") v = parseInt(v, 10);
        if (el.type === "number" && !isFinite(v)) v = null;
        d[k] = v;
        if (k === "color" && /^(fib|fibext|fibtime|fibfan|gannfan|gannbox)$/.test(d.type)) d.mono = true;
        if (k === "alert") d.fired = false;
      }
      if (el.dataset.pt != null) {
        var p = parseFloat(el.value); if (isFinite(p)) d.pts[+el.dataset.pt].p = p;
      }
      if (el.dataset.lv != null || el.dataset.lvOn != null) {
        var lv = levelsOf(d).map(function (x) { return { v: x.v, on: x.on !== false }; });
        m.querySelectorAll("[data-lv]").forEach(function (inp) { var v2 = parseFloat(inp.value); if (isFinite(v2)) lv[+inp.dataset.lv].v = v2; });
        m.querySelectorAll("[data-lv-on]").forEach(function (inp) { lv[+inp.dataset.lvOn].on = inp.checked; });
        d.levels = lv;
      }
      save(); render(); inspector();
    }
    m.querySelectorAll("input,select,textarea").forEach(function (el) {
      el.addEventListener(el.type === "range" || el.tagName === "TEXTAREA" || el.type === "number" ? "input" : "change", function () { apply(el); });
    });
    var add = m.querySelector("[data-addlv]");
    if (add) add.addEventListener("click", function () {
      var lv = levelsOf(d).slice(); lv.push({ v: 4.236, on: true }); d.levels = lv;
      closeModal(); render(); drawingSettings(d);
    });
  }

  function contextMenu(e) {
    e.preventDefault();
    var r = box.getBoundingClientRect(), pt = { x: e.clientX - r.left, y: e.clientY - r.top };
    var h = hit(pt.x, pt.y), items = [];
    if (h) {
      var d = h.d; select(d);
      items.push({ head: (T[d.type] || {}).lab || "Drawing" });
      items.push({ lab: "Settings", icon: "gear", fn: function () { drawingSettings(d); } });
      if (TEXTUAL[d.type]) items.push({ lab: "Edit text", icon: "text", fn: function () { editText(d, false); } });
      if (d.type === "hline" || d.type === "hray") items.push({ lab: d.alert ? "Turn the alert off" : "Alert when price crosses", icon: "bell", fn: function () { W.sel = d; inspAction("alert"); } });
      items.push({ lab: "Clone", icon: "clone", key: "Ctrl+D", fn: function () { duplicate(d); } });
      items.push({ lab: "Copy", icon: "copy", key: "Ctrl+C", fn: function () { W.clip = clone(d); note("Copied. Ctrl+V pastes it, here or on another symbol."); } });
      items.push({ lab: d.locked ? "Unlock" : "Lock", icon: d.locked ? "unlock" : "lock", fn: function () { push(); d.locked = !d.locked; changed(); } });
      items.push({ lab: "Hide", icon: "eyeOff", fn: function () { push(); d.hidden = true; W.sel = null; changed(); } });
      items.push({ lab: "Bring to front", icon: "front", fn: function () { order(d, true); } });
      items.push({ lab: "Send to back", icon: "back", fn: function () { order(d, false); } });
      items.push({ sep: 1 });
      items.push({ lab: "Remove", icon: "trash", key: "Del", danger: true, fn: function () { del(d); } });
    } else {
      var p = pAt(pt.y), g = geo(), t = g ? lToT(g.l(pt.x)) : null;
      items.push({ lab: "Reset chart view", icon: "reset", key: "Alt+R", fn: resetView });
      if (p != null) {
        items.push({ lab: "Add an alert at " + fmt(p), icon: "bell", fn: function () { addAlert(p, t); } });
        items.push({ lab: "Horizontal line at " + fmt(p), icon: "hline", fn: function () { commit(Object.assign(newDrawing("hline", [{ t: t, p: p }]))); } });
        items.push({ lab: "Copy price " + fmt(p), icon: "copy", fn: function () { try { navigator.clipboard.writeText(p.toFixed(2)); note("Copied " + p.toFixed(2) + "."); } catch (x) {} } });
      }
      if (W.clip) items.push({ lab: "Paste drawing", icon: "copy", key: "Ctrl+V", fn: paste });
      items.push({ sep: 1 });
      items.push({ lab: "Indicators", icon: "fx", key: "/", fn: indicatorDialog });
      items.push({ lab: "Object tree", icon: "tree", fn: function () { toggleSide(true, "tree"); } });
      items.push({ lab: "Chart settings", icon: "gear", fn: chartSettings });
      if (W.drawings.length) items.push({ lab: "Remove all drawings", icon: "trash", danger: true, fn: removeAll });
    }
    listPop(null, items, { x: e.clientX, y: e.clientY }, "cw-ctx");
  }

  function addAlert(p, t) {
    var o = newDrawing("hline", [{ t: t || (W.times[W.times.length - 1] || 0), p: p }]);
    o.alert = true; o.color = "--warning"; o.style = "dash"; o.width = 1;
    commit(o);
    toast("Alert set at " + fmt(p) + ". This tab will tell you when price crosses it.");
    askNotify();
  }
  function askNotify() {
    try { if (window.Notification && Notification.permission === "default") Notification.requestPermission(); } catch (e) {}
  }
  function checkAlerts(prev, px) {
    if (prev == null || px == null) return;
    var hitAny = false;
    W.drawings.forEach(function (d) {
      if (!d.alert || d.fired || !d.pts.length) return;
      var lv = d.pts[0].p;
      if ((prev < lv && px >= lv) || (prev > lv && px <= lv)) {
        d.fired = true; hitAny = true;
        var msg2 = W.sym + " crossed " + fmt(lv) + (px >= lv ? " going up" : " going down") + ", now " + fmt(px) + ".";
        toast(msg2, 9000);
        try { if (window.Notification && Notification.permission === "granted") new Notification("Altaha alert", { body: msg2 }); } catch (e) {}
      }
    });
    if (hitAny) { save(); render(); }
  }

  function toast(m, ms) {
    toastEl.textContent = m; toastEl.classList.add("on");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { toastEl.classList.remove("on"); }, ms || 3200);
  }
  function note(m) { if (noteEl) noteEl.textContent = m; }
  function msg(m, html) {
    if (m) { if (html) msgEl.innerHTML = m; else msgEl.textContent = m; msgEl.classList.add("on"); }
    else msgEl.classList.remove("on");
  }

  function removeAll() {
    if (!W.drawings.length) { note("There are no drawings on " + W.sym + "."); return; }
    modal("Remove all drawings", "<p class='cw-p'>Remove all " + W.drawings.length + " drawings on " + esc(W.sym) + "? Ctrl+Z brings them back.</p>", { foot: [
      { lab: "Cancel", fn: function () {} },
      { lab: "Remove", danger: true, fn: function () { push(); W.drawings = []; W.sel = null; changed(); } }
    ] });
  }

  /* ══════════════════════════════════════════════════════════════════════
     INDICATORS
     ══════════════════════════════════════════════════════════════════════ */

  function studyLabel(s) {
    /* A zero here means "none" (no smoothing line), so it is not shown. */
    var vals = (s.def.params || []).filter(function (q) { return (q.k !== "src" || s.p.src !== "close") && s.p[q.k] !== 0; })
      .map(function (q) { return s.p[q.k]; });
    return s.def.short + (vals.length ? " " + vals.join(" ") : "");
  }
  function colOf(s, o) { return asColor((s.col && s.col[o.k]) || o.c); }

  function addStudy(id) {
    var def = M.indicator(id); if (!def) return;
    if (id === "vol" && L.studies.some(function (x) { return x.id === "vol"; })) { toast("Volume is already on the chart."); return; }
    L.studies.push({ uid: uid(), id: id, p: M.defaults(def), hidden: false, col: {} });
    saveLayout(); rebuild(true);
    toast(def.name + " added.");
  }
  function removeStudy(u) {
    L.studies = L.studies.filter(function (x) { return x.uid !== u; });
    delete L.paneH[u];
    saveLayout(); rebuild(true);
  }
  function studyOf(u) { for (var i = 0; i < L.studies.length; i++) if (L.studies[i].uid === u) return L.studies[i]; return null; }

  function indicatorDialog() {
    var cats = ["All", "Trend", "Momentum", "Volatility", "Volume"], cat = "All";
    var wrap = document.createElement("div");
    wrap.className = "cw-ind";
    wrap.innerHTML = '<input type="search" class="cw-ind-q" placeholder="Search, e.g. RSI or bands" aria-label="Search indicators">' +
      '<div class="cw-ind-cats">' + cats.map(function (c) { return '<button type="button" class="cw-chip' + (c === cat ? " on" : "") + '" data-cat="' + c + '">' + c + "</button>"; }).join("") + "</div>" +
      '<div class="cw-ind-list" role="list"></div>' +
      '<div class="cw-ind-on"></div>';
    var list = wrap.querySelector(".cw-ind-list"), q = wrap.querySelector(".cw-ind-q"), onEl = wrap.querySelector(".cw-ind-on");
    function draw() {
      var s = q.value.trim().toLowerCase();
      list.innerHTML = M.INDICATORS.filter(function (d) {
        return (cat === "All" || d.cat === cat) && (!s || (d.name + " " + d.short).toLowerCase().indexOf(s) >= 0);
      }).map(function (d) {
        var n = L.studies.filter(function (x) { return x.id === d.id; }).length;
        return '<button type="button" class="cw-ind-i" data-id="' + d.id + '" role="listitem"><b>' + esc(d.name) + "</b><span>" +
          esc(d.cat) + (d.pane ? ", own pane" : ", on the price") + (n ? ' <em>' + n + " on</em>" : "") + "</span>" + svg("plus") + "</button>";
      }).join("") || "<p class='cw-p'>Nothing by that name.</p>";
      onEl.innerHTML = L.studies.length ? "<h4>On this chart</h4>" + L.studies.map(function (x) {
        var s2 = { def: M.indicator(x.id), p: x.p };
        return '<div class="cw-ind-r"><span>' + esc(studyLabel(s2)) + '</span><button type="button" data-set="' + x.uid + '" aria-label="Settings">' + svg("gear") +
          '</button><button type="button" data-rm="' + x.uid + '" aria-label="Remove">' + svg("x") + "</button></div>";
      }).join("") : "";
    }
    wrap.addEventListener("click", function (e) {
      var c = e.target.closest("[data-cat]");
      if (c) { cat = c.dataset.cat; wrap.querySelectorAll("[data-cat]").forEach(function (b) { b.classList.toggle("on", b === c); }); draw(); return; }
      var i = e.target.closest("[data-id]"); if (i) { addStudy(i.dataset.id); draw(); return; }
      var r = e.target.closest("[data-rm]"); if (r) { removeStudy(r.dataset.rm); draw(); return; }
      var st = e.target.closest("[data-set]"); if (st) studySettings(st.dataset.set);
    });
    q.addEventListener("input", draw);
    q.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { var f = list.querySelector("[data-id]"); if (f) { addStudy(f.dataset.id); draw(); } }
    });
    draw();
    modal("Indicators", wrap, { cls: "cw-modal-wide" });
  }

  function studySettings(u) {
    var s = studyOf(u); if (!s) return;
    var def = M.indicator(s.id), before = JSON.stringify(s);
    var h = '<div class="cw-form">';
    (def.params || []).forEach(function (q) {
      if (q.opts) h += row(q.l, '<select data-p="' + q.k + '">' + q.opts.map(function (o) { return "<option" + (s.p[q.k] === o ? " selected" : "") + ">" + o + "</option>"; }).join("") + "</select>");
      else h += row(q.l, '<input type="number" data-p="' + q.k + '" min="' + q.min + '" max="' + q.max + '" step="' + (q.step || 1) + '" value="' + s.p[q.k] + '">');
    });
    def.out.forEach(function (o) {
      h += row(o.l, '<input type="color" data-c="' + o.k + '" value="' + hex6(colOf(s, o)) + '">');
    });
    if (def.note) h += "<p class='cw-p'>" + esc(def.note) + "</p>";
    h += "</div>";
    var m = modal(def.name, h, { foot: [
      { lab: "Defaults", fn: function () { s.p = M.defaults(def); s.col = {}; saveLayout(); rebuild(true); } },
      { lab: "Cancel", fn: function () { var o = JSON.parse(before); s.p = o.p; s.col = o.col; saveLayout(); rebuild(true); } },
      { lab: "Done", primary: true, fn: function () {} }
    ] });
    m.querySelectorAll("[data-p]").forEach(function (el) {
      el.addEventListener("change", function () {
        var q = def.params.filter(function (x) { return x.k === el.dataset.p; })[0];
        var v = q.opts ? el.value : parseFloat(el.value);
        if (!q.opts) { if (!isFinite(v)) return; v = clamp(v, q.min, q.max); if (!q.step || q.step >= 1) v = Math.round(v); }
        s.p[q.k] = v; saveLayout(); rebuild(true);
      });
    });
    m.querySelectorAll("[data-c]").forEach(function (el) {
      el.addEventListener("input", function () { s.col = s.col || {}; s.col[el.dataset.c] = el.value; saveLayout(); rebuild(true); });
    });
  }

  /* ══════════════════════════════════════════════════════════════════════
     DATA → SERIES
     ══════════════════════════════════════════════════════════════════════ */

  function ensure() {
    if (W.chart) return true;
    var LW = window.LightweightCharts;
    if (!LW || typeof LW.createChart !== "function") return false;
    if (!box.clientWidth || !box.clientHeight) return false;
    W.chart = LW.createChart(box, Object.assign({ width: box.clientWidth, height: box.clientHeight }, theme(false)));
    hookChart(W.chart, null);
    if (W.watching) return true;
    W.watching = true;
    new ResizeObserver(function () {
      if (!W.chart) return;
      W.chart.applyOptions({ width: box.clientWidth, height: box.clientHeight });
      render();
    }).observe(box);
    setInterval(watchdog, 1500);
    /* A vertical drag on the price scale changes no logical range, so the
       drawings would lag the candles. A cheap signature check catches it
       without a permanent animation loop. */
    setInterval(function () {
      if (!W.chart || !W.main || !W.disp.length || !visible()) return;
      var y = W.main.priceToCoordinate(W.disp[W.disp.length - 1].close), g = geo();
      var s = (g ? g.from.toFixed(2) + "," + g.to.toFixed(2) : "") + "|" + y + "|" + box.clientWidth + "x" + box.clientHeight;
      if (s !== W.sig) { W.sig = s; render(); }
    }, 120);
    return true;
  }

  /* ── never a blank chart ────────────────────────────────────────────────
     A chart with candles loaded must show them. Every second and a half the
     workspace checks that it does: a visible range, a price scale that can
     place the last close, the library's own element in place, and ink on
     the plot. Two failed checks in a row and the chart is rebuilt from the
     candles it already holds, drawings and indicators kept, and the failure
     is reported so it can be found and fixed rather than lived with. */
  /* Ink on the plot: pixels that differ from the background, over every
     canvas the size of the plot (the library paints candles on one and the
     crosshair on a transparent one above it). */
  function plotInk() {
    var list = [], area = 0;
    box.querySelectorAll("canvas").forEach(function (c) {
      if (c === cv || c.classList.contains("cw-patov") || !c.width || !c.height) return;
      var a = c.width * c.height;
      if (a > area * 1.01) { area = a; list = [c]; } else if (a >= area * 0.99) list.push(c);
    });
    if (!list.length) return 0;
    var bg = tok("--surface"), m = /^#?([0-9a-f]{6})$/i.exec(bg), n = 0;
    var br = m ? parseInt(m[1], 16) >> 16 : 255, bgc = m ? (parseInt(m[1], 16) >> 8) & 255 : 255, bb = m ? parseInt(m[1], 16) & 255 : 255;
    list.forEach(function (c) {
      var x = c.getContext("2d"); if (!x) { n++; return; }
      var d = x.getImageData(0, 0, c.width, c.height).data;
      for (var i = 0; i < d.length; i += 4 * 37) {
        if (d[i + 3] < 40) continue;
        if (Math.abs(d[i] - br) + Math.abs(d[i + 1] - bgc) + Math.abs(d[i + 2] - bb) > 40) n++;
      }
    });
    return n;
  }
  function blankReason() {
    if (!W.chart || !W.main) return "no chart";
    var n = W.disp.length, g = geo();
    if (!g) return "no visible range";
    if (g.to < 0 || g.from > n - 1) return "scrolled off the data";
    if (W.main.priceToCoordinate(W.disp[n - 1].close) == null) return "price scale lost";
    if (!box.querySelector("table")) return "chart element missing";
    /* Only while the price scale fits itself: a reader who dragged the
       scale until the candles left the screen did that on purpose. */
    var auto = true;
    try { auto = W.chart.priceScale("right").options().autoScale; } catch (e) {}
    if (auto && plotInk() === 0) return "nothing painted";
    return null;
  }
  function watchdog() {
    if (!W.raw.length || !visible() || msgEl.classList.contains("on") || document.visibilityState !== "visible") { W.blank = 0; return; }
    var why;
    try { why = blankReason(); } catch (e) { why = "check failed: " + (e && e.message); }
    W.blank = why ? (W.blank || 0) + 1 : 0;
    if (W.blank < 2) return;
    W.blank = 0;
    if (why === "scrolled off the data") { resetView(); return; }
    report(new Error("Chart went blank: " + why));
    restoreChart();
    toast("The chart had gone blank, so it was redrawn. Your drawings and indicators are kept.", 6000);
  }
  /* Rebuilt from scratch: new library charts, the same candles, layout and
     drawings. */
  function restoreChart() {
    W.panes.forEach(function (p) { try { p.chart.remove(); } catch (e) {} try { p.el.remove(); } catch (e) {} });
    W.panes = []; W.paneSig = "";
    try { if (W.chart) W.chart.remove(); } catch (e) {}
    W.chart = null; W.main = null; W.space = null; W.vol = null; W.all = []; W.levelLines = []; W.seriesSig = "";
    Array.prototype.slice.call(box.children).forEach(function (el) {
      if (el.tagName === "DIV" && el.querySelector && el.querySelector("table")) el.remove();
    });
    faultOff();
    if (!ensure()) return;
    rebuild(true);
    resetView();
  }
  function report(err) {
    var ctxt = { sym: W.sym, tf: L.tf, type: L.type, bars: W.disp.length, mode: W.mode, tool: W.tool,
                 studies: L.studies.map(function (x) { return x.id; }).join(","), drawings: W.drawings.length, full: isFull() };
    if (window.console) console.error("[altaha-charts]", err, ctxt);
    try { if (window.Sentry && window.Sentry.captureException) window.Sentry.captureException(err, { tags: { area: "charts" }, extra: ctxt }); } catch (e) {}
  }
  /* An error the chart did not catch is shown on the chart, with a way back. */
  function fault(err) {
    var el = $("cw-fault");
    if (!el) {
      el = document.createElement("div");
      el.id = "cw-fault"; el.className = "cw-fault"; el.setAttribute("role", "alert");
      box.appendChild(el);
      el.addEventListener("click", function (e) { if (e.target.closest("[data-restore]")) restoreChart(); });
    }
    el.innerHTML = "<span>The chart ran into an error: " + esc(String(err && err.message || err).slice(0, 160)) +
      "</span><button type='button' class='cw-btn primary' data-restore='1'>Restore chart</button>";
    el.classList.add("on");
  }
  function faultOff() { var el = $("cw-fault"); if (el) el.classList.remove("on"); }
  window.addEventListener("error", function (ev) {
    var where = String((ev && ev.filename) || "") + " " + String((ev && ev.error && ev.error.stack) || "");
    if (/charts-workspace|charts-math|lightweight-charts/.test(where) && visible()) fault(ev.error || ev.message);
  });

  function charts() { return [W.chart].concat(W.panes.map(function (p) { return p.chart; })).filter(Boolean); }

  function hookChart(chart, pane) {
    chart.timeScale().subscribeVisibleLogicalRangeChange(function (r) {
      if (!pane) { render(); footState(); }
      if (W.syncing || !r) return;
      W.syncing = true;
      charts().forEach(function (c) { if (c !== chart) { try { c.timeScale().setVisibleLogicalRange(r); } catch (e) {} } });
      W.syncing = false;
    });
    chart.subscribeCrosshairMove(function (param) {
      var i = null;
      if (param && param.time != null) {
        i = typeof param.logical === "number" ? Math.round(param.logical) : null;
        if (i == null) { var t = param.time; i = W.timeline.indexOf(t); }
      }
      if (!W.xsync) {
        W.xsync = true;
        charts().forEach(function (c) {
          if (c === chart) return;
          try {
            if (i == null || i < 0 || i >= W.disp.length) { c.clearCrosshairPosition(); return; }
            var tgt = c === W.chart ? { s: W.main, v: W.disp[i].close } : paneTarget(c, i);
            if (tgt && tgt.s && ok(tgt.v)) c.setCrosshairPosition(tgt.v, W.disp[i].time, tgt.s);
            else c.clearCrosshairPosition();
          } catch (e) {}
        });
        W.xsync = false;
      }
      legendAt(i);
    });
  }
  function paneTarget(c, i) {
    for (var k = 0; k < W.panes.length; k++) {
      var p = W.panes[k];
      if (p.chart !== c) continue;
      var s = p.st, ser = s.ser[s.def.out[0].k], arr = s.data && s.data[s.def.out[0].k];
      if (ser && ser[0] && arr && ok(arr[i])) return { s: ser[0], v: arr[i] };
      for (var j = 0; j < s.def.out.length; j++) {
        var o = s.def.out[j], a2 = s.data && s.data[o.k];
        if (a2 && ok(a2[i]) && s.ser[o.k] && s.ser[o.k][0]) return { s: s.ser[o.k][0], v: a2[i] };
      }
    }
    return null;
  }

  /* Raw rows from /chart → the bars on screen: fold to the timeframe, cut at
     the replay point, transform for Heikin Ashi. */
  function derive() {
    var tf = tfOf(L.tf), raw = W.raw;
    if (tf.n) W.full = M.resampleIntraday(raw.map(function (r) { return Object.assign({}, r, { time: r.time + W.off }); }), tf.n)
                     .map(function (r) { return Object.assign(r, { time: r.time - W.off }); });
    else if (tf.month) W.full = M.resample(raw, function (r) { return M.monthKey(r.time + W.off); });
    else W.full = raw.slice();
    W.rows = W.replay ? W.full.slice(0, W.replay.idx + 1) : W.full;
    W.disp = L.type === "ha" ? M.heikinAshi(W.rows) : W.rows;
    W.times = W.rows.map(function (r) { return r.time; });
    var diffs = [];
    for (var i = 1; i < Math.min(W.times.length, 120); i++) diffs.push(W.times[i] - W.times[i - 1]);
    diffs.sort(function (a, b) { return a - b; });
    W.barSec = diffs[Math.floor(diffs.length / 2)] || 86400;
    W.D = M.columns(W.rows);
    W.D.barSec = W.barSec;
    W.D.t = W.times.map(function (t) { return t + W.off; });
  }

  function futureTimes(k) {
    var out = [], t = W.times[W.times.length - 1];
    for (var i = 0; i < k; i++) {
      t += W.barSec;
      if (W.barSec >= 86400 && W.barSec < 7 * 86400) {
        var wd = new Date((t + W.off) * 1000).getUTCDay();
        while (wd === 0 || wd === 6) { t += 86400; wd = new Date((t + W.off) * 1000).getUTCDay(); }
      }
      out.push(t);
    }
    return out;
  }

  function computeStudies() {
    var old = {};
    W.st.forEach(function (s) { old[s.uid] = s; });
    W.st = L.studies.map(function (x) {
      var s = old[x.uid] || { ser: {} };
      s.uid = x.uid; s.id = x.id; s.def = M.indicator(x.id); s.p = x.p; s.hidden = x.hidden; s.col = x.col || {};
      try { s.data = W.rows.length ? s.def.calc(W.D, s.p) : {}; } catch (e) { s.data = {}; }
      return s;
    });
    var extra = 0;
    W.st.forEach(function (s) {
      Object.keys(s.data || {}).forEach(function (k) {
        if (Array.isArray(s.data[k])) extra = Math.max(extra, s.data[k].length - W.rows.length);
      });
    });
    W.timeline = W.times.concat(futureTimes(Math.min(extra, 200)));
  }

  function lineOpts(o, s, extra) {
    return Object.assign({
      color: colOf(s, o), lineWidth: o.w || 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: !s.hidden
    }, extra || {});
  }

  function addSeries(chart, kind, opts, bag) {
    var s = chart["add" + kind + "Series"](opts);
    bag.push(s);
    return s;
  }

  /* One output → one or two series (a line coloured by direction is two,
     so the line breaks at a flip instead of joining the two bands). */
  function makeOutSeries(chart, s, o, bag, scaleId) {
    var base = scaleId ? { priceScaleId: scaleId } : {};
    if (s.def.prec) base.priceFormat = { type: "price", precision: s.def.prec, minMove: Math.pow(10, -s.def.prec) };
    if (s.def.fmt === "volume") base.priceFormat = { type: "volume" };
    if (o.s === "hist") return [addSeries(chart, "Histogram", Object.assign({ priceLineVisible: false, lastValueVisible: false, visible: !s.hidden, color: colOf(s, o) }, base), bag)];
    if (o.by) return [addSeries(chart, "Line", lineOpts(o, s, base), bag), addSeries(chart, "Line", lineOpts(o, s, Object.assign({ color: asColor(o.c2) }, base)), bag)];
    var ex = Object.assign({}, base);
    if (o.s === "dots") { ex.lineVisible = false; ex.pointMarkersVisible = true; }
    if (o.s === "step") ex.lineType = 1;
    if (chart !== W.chart) { ex.lastValueVisible = true; }
    return [addSeries(chart, "Line", lineOpts(o, s, ex), bag)];
  }

  function outData(s, o, idx) {
    var arr = (s.data || {})[o.k] || [], T2 = W.timeline, out = [], out2 = [], prev = null;
    var n = Math.min(arr.length, T2.length), up = upC(), dn = dnC();
    for (var i = 0; i < n; i++) {
      var v = arr[i], t = T2[i];
      if (!ok(v)) { out.push({ time: t }); if (o.by) out2.push({ time: t }); prev = null; continue; }
      if (o.s === "hist") {
        var col;
        if (s.id === "vol") { var r = W.disp[i]; col = r && r.close >= r.open ? up : dn; col = alphaOf(col, 0.38); }
        else if (o.rising) col = prev == null || v >= prev ? colOf(s, o) : (asColor(o.c2) || dn);
        else col = v >= 0 ? colOf(s, o) : (asColor(o.c2) || dn);
        out.push({ time: t, value: v, color: col });
      } else if (o.by) {
        var dir = s.data[o.by][i];
        if (dir === 1) { out.push({ time: t, value: v }); out2.push({ time: t }); }
        else { out2.push({ time: t, value: v }); out.push({ time: t }); }
      } else out.push({ time: t, value: v });
      prev = v;
    }
    return idx === 1 ? out2 : out;
  }
  /* Lines are 1.5px. An area is its line colour at 15%, flat: both ends of
     the fill are the same colour, so there is no gradient. */
  function mainOpts() {
    var up = upC(), dn = dnC(), T = Th.chart(), ink = T.text, line = T.series[0], lw = T.lineWidth;
    var base = { priceLineVisible: !!L.set.last, lastValueVisible: true, priceLineStyle: 2 };
    switch (L.type) {
      case "hollow": return ["Candlestick", Object.assign(base, { upColor: "transparent", downColor: dn, borderUpColor: up, borderDownColor: dn, wickUpColor: up, wickDownColor: dn })];
      case "bars": return ["Bar", Object.assign(base, { upColor: up, downColor: dn, thinBars: false })];
      case "line": return ["Line", Object.assign(base, { color: ink, lineWidth: lw })];
      case "step": return ["Line", Object.assign(base, { color: ink, lineWidth: lw, lineType: 1 })];
      case "area": return ["Area", Object.assign(base, { lineColor: line, topColor: T.fills[0], bottomColor: T.fills[0], lineWidth: lw })];
      case "baseline": {
        var bv = W.disp.length ? W.disp[Math.max(0, W.disp.length - 120)].close : 0;
        var upFill = alphaOf(up, T.fillOpacity), dnFill = alphaOf(dn, T.fillOpacity);
        return ["Baseline", Object.assign(base, { baseValue: { type: "price", price: bv }, topLineColor: up, bottomLineColor: dn,
          topFillColor1: upFill, topFillColor2: upFill, bottomFillColor1: dnFill, bottomFillColor2: dnFill, lineWidth: lw })];
      }
      default: return ["Candlestick", Object.assign(base, { upColor: up, downColor: dn, borderUpColor: up, borderDownColor: dn, wickUpColor: up, wickDownColor: dn })];
    }
  }
  function mainData() {
    if (L.type === "line" || L.type === "step" || L.type === "area" || L.type === "baseline")
      return W.disp.map(function (r) { return { time: r.time, value: r.close }; });
    return W.disp.map(function (r) { return { time: r.time, open: r.open, high: r.high, low: r.low, close: r.close }; });
  }

  /* Every series on the price chart is rebuilt when the set of them changes
     (a type switch, an indicator added). Order is z-order: volume under the
     price, overlays over it, comparisons on top. */
  function buildMainSeries() {
    var c = W.chart;
    W.all.forEach(function (s) { try { c.removeSeries(s); } catch (e) {} });
    W.all = []; W.levelLines = [];
    W.space = addSeries(c, "Line", { priceScaleId: "space", visible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, W.all);
    W.vol = null; W.volMA = null;
    W.st.forEach(function (s) {
      if (s.id !== "vol") return;
      s.ser = {};
      s.ser.vol = [addSeries(c, "Histogram", { priceFormat: { type: "volume" }, priceScaleId: "vol", visible: !s.hidden, priceLineVisible: false, lastValueVisible: false }, W.all)];
      s.ser.ma = [addSeries(c, "Line", lineOpts(s.def.out[1], s, { priceScaleId: "vol" }), W.all)];
      W.vol = s.ser.vol[0];
    });
    try { c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } }); } catch (e) {}
    var mo = mainOpts();
    W.main = addSeries(c, mo[0], mo[1], W.all);
    W.st.forEach(function (s) {
      if (s.def.pane || s.id === "vol") return;
      s.ser = {};
      s.def.out.forEach(function (o) { s.ser[o.k] = makeOutSeries(c, s, o, W.all); });
    });
    W.cmp.forEach(function (cp) {
      cp.series = addSeries(c, "Line", { color: cp.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false }, W.all);
    });
  }

  function setMainData() {
    W.space.setData(W.timeline.map(function (t) { return { time: t }; }));
    W.main.setData(mainData());
    if (L.type === "baseline") W.main.applyOptions(mainOpts()[1]);
    W.st.forEach(function (s) {
      if (s.def.pane) return;
      s.def.out.forEach(function (o) {
        var ser = s.ser[o.k]; if (!ser) return;
        ser.forEach(function (se, j) { se.setData(outData(s, o, j)); });
      });
    });
    W.cmp.forEach(function (cp) { if (cp.series) cp.series.setData(cmpData(cp)); });
    publishTap();
  }

  /* Panes: a chart each, stacked under the price chart, kept in step. */
  function buildPanes() {
    var want = W.st.filter(function (s) { return s.def.pane; });
    var sig = want.map(function (s) { return s.uid + ":" + s.id; }).join(",");
    if (sig !== W.paneSig) {
      W.panes.forEach(function (p) { try { p.chart.remove(); } catch (e) {} p.el.remove(); });
      W.panes = [];
      want.forEach(function (s) {
        var el = document.createElement("div");
        el.className = "cw-pn"; el.dataset.uid = s.uid;
        var hgt = L.paneH[s.uid] || (root.clientWidth < 780 ? 96 : 128);
        el.style.height = hgt + "px";
        el.innerHTML = '<div class="cw-pn-grip" role="separator" aria-orientation="horizontal" aria-label="Resize pane"></div>' +
          '<div class="cw-legend cw-pn-leg"></div><div class="cw-pn-host"></div>';
        subEl.appendChild(el);
        var host = el.querySelector(".cw-pn-host");
        var ch = window.LightweightCharts.createChart(host, Object.assign({ width: host.clientWidth || box.clientWidth, height: hgt - 1 }, theme(true)));
        var p = { uid: s.uid, el: el, host: host, chart: ch, leg: el.querySelector(".cw-pn-leg"), st: s, all: [], lines: [] };
        new ResizeObserver(function () { try { ch.applyOptions({ width: host.clientWidth, height: host.clientHeight }); } catch (e) {} }).observe(host);
        hookChart(ch, p);
        grip(el.querySelector(".cw-pn-grip"), p);
        W.panes.push(p);
      });
      W.paneSig = sig;
    }
    W.panes.forEach(function (p, k) {
      var s = W.st.filter(function (x) { return x.uid === p.uid; })[0];
      p.st = s;
      p.all.forEach(function (se) { try { p.chart.removeSeries(se); } catch (e) {} });
      p.all = []; p.lines = [];
      p.space = addSeries(p.chart, "Line", { priceScaleId: "space", visible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, p.all);
      p.space.setData(W.timeline.map(function (t) { return { time: t }; }));
      s.ser = {};
      s.def.out.forEach(function (o) {
        s.ser[o.k] = makeOutSeries(p.chart, s, o, p.all);
        s.ser[o.k].forEach(function (se, j) { se.setData(outData(s, o, j)); });
      });
      var first = s.ser[s.def.out[0].k][0];
      (s.def.levels || []).forEach(function (lv) {
        try { first.createPriceLine({ price: lv, color: tok("--text-muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" }); } catch (e) {}
      });
      p.chart.applyOptions({ timeScale: { visible: k === W.panes.length - 1, timeVisible: !!tfOf(L.tf).intra } });
    });
    W.chart.applyOptions({ timeScale: { visible: !W.panes.length } });
  }

  function grip(el, p) {
    el.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      var y0 = e.clientY, h0 = p.el.offsetHeight;
      function mv(ev) { var h = clamp(h0 - (ev.clientY - y0), 56, 420); p.el.style.height = h + "px"; }
      function upf() {
        el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", upf);
        L.paneH[p.uid] = p.el.offsetHeight; saveLayout(); render();
      }
      el.addEventListener("pointermove", mv); el.addEventListener("pointerup", upf);
    });
  }

  function drawLevels() {
    (W.levelLines || []).forEach(function (ln) { try { W.main.removePriceLine(ln); } catch (e) {} });
    W.levelLines = [];
    var lv = W.meta && W.meta.levels;
    if (!lv || !W.main || !L.set.levels || W.cmp.length) return;
    var sup = tok("--gain"), res = tok("--loss");
    function add(z, colour, tag) {
      if (!z || z.level == null) return;
      var s = clamp(z.strength == null ? 50 : z.strength, 0, 100);
      try {
        W.levelLines.push(W.main.createPriceLine({ price: z.level, color: colour, lineWidth: s >= 70 ? 2 : 1,
          lineStyle: s >= 55 ? 0 : 2, axisLabelVisible: false, title: tag + " " + Math.round(s) + (z.touches ? " · " + z.touches + "t" : "") }));
      } catch (e) {}
    }
    (lv.supports || []).slice(0, 3).forEach(function (z) { add(z, sup, "S"); });
    (lv.resistances || []).slice(0, 3).forEach(function (z) { add(z, res, "R"); });
  }

  function publishTap() {
    var tap = window.AltahaChartTap;
    if (tap && typeof tap.publish === "function") {
      try { tap.publish(W.chart, W.main, box, W.disp); } catch (e) {}
    }
  }

  /* Everything after the candles change: indicators, series, panes, legends. */
  function rebuild(structural, keepView) {
    if (!W.chart || !W.raw.length) return;
    var vr = W.chart.timeScale().getVisibleLogicalRange();
    derive();
    computeStudies();
    var sig = L.type + "|" + W.st.filter(function (s) { return !s.def.pane; }).map(function (s) { return s.uid + JSON.stringify(s.p) + JSON.stringify(s.col) + s.hidden; }).join(",") + "|" + W.cmp.map(function (c) { return c.sym; }).join(",");
    if (structural || sig !== W.seriesSig) { buildMainSeries(); W.seriesSig = sig; drawLevels(); }
    setMainData();
    buildPanes();
    applyScale();
    buildLegends();
    if (keepView && vr) { try { W.chart.timeScale().setVisibleLogicalRange(vr); } catch (e) {} }
    else if (vr) { charts().forEach(function (c) { try { c.timeScale().setVisibleLogicalRange(vr); } catch (e) {} }); }
    W.chart.applyOptions({ watermark: theme(false).watermark });
    legendAt(null);
    sideRefresh();
    render();
  }

  function applyScale() {
    if (!W.chart) return;
    var mode = W.cmp.length || L.pct ? 2 : L.log ? 1 : 0;
    var hasVol = W.st.some(function (s) { return s.id === "vol" && !s.hidden; });
    try {
      W.chart.priceScale("right").applyOptions({ mode: mode, invertScale: !!L.invert,
        scaleMargins: { top: 0.08, bottom: hasVol ? 0.2 : 0.06 } });
    } catch (e) {}
    footState();
  }
  function footState() {
    var f = root && root.querySelector(".cw-foot"); if (!f) return;
    var auto = true;
    try { auto = W.chart ? W.chart.priceScale("right").options().autoScale : true; } catch (e) {}
    f.querySelectorAll("[data-scale]").forEach(function (b) {
      var k = b.dataset.scale;
      b.classList.toggle("on", k === "auto" ? auto : k === "pct" ? !!(L.pct || W.cmp.length) : !!L.log);
    });
  }

  /* ── legends ─────────────────────────────────────────────────────────── */

  function legBtns(u) {
    return '<span class="cw-lg-b"><button type="button" data-lg="eye" data-u="' + u + '" aria-label="Show or hide">' + svg("eye") + "</button>" +
      '<button type="button" data-lg="set" data-u="' + u + '" aria-label="Settings">' + svg("gear") + "</button>" +
      '<button type="button" data-lg="rm" data-u="' + u + '" aria-label="Remove">' + svg("x") + "</button></span>";
  }
  function buildLegends() {
    var h = '<div class="cw-lg-row cw-lg-main"><b>' + esc(W.sym) + '</b><span class="k">' + esc(L.tf) + '</span><span data-v="ohlc"></span>' +
      (W.replay ? '<span class="cw-lg-tag">Replay</span>' : "") + "</div>";
    W.st.forEach(function (s) {
      if (s.def.pane) return;
      h += '<div class="cw-lg-row' + (s.hidden ? " off" : "") + '" data-u="' + s.uid + '"><span class="nm">' + esc(studyLabel(s)) +
        '</span><span data-v="' + s.uid + '"></span>' + legBtns(s.uid) + "</div>";
    });
    W.cmp.forEach(function (c) {
      h += '<div class="cw-lg-row"><i class="cw-lg-dot" style="background:' + c.color + '"></i><span class="nm">' + esc(c.sym) +
        '</span><span data-v="cmp-' + esc(c.sym) + '"></span><span class="cw-lg-b"><button type="button" data-lg="cmprm" data-u="' + esc(c.sym) + '" aria-label="Remove ' + esc(c.sym) + '">' + svg("x") + "</button></span></div>";
    });
    legEl.innerHTML = h;
    legEl.classList.toggle("folded", !!W.legFold);
    W.panes.forEach(function (p) {
      p.leg.innerHTML = '<div class="cw-lg-row' + (p.st.hidden ? " off" : "") + '" data-u="' + p.uid + '"><span class="nm">' + esc(studyLabel(p.st)) +
        '</span><span data-v="' + p.uid + '"></span>' + legBtns(p.uid) + "</div>";
    });
  }
  var legRaf = null, legIdx = null;
  function legendAt(i) {
    legIdx = i;
    if (legRaf) return;
    legRaf = requestAnimationFrame(function () { legRaf = null; paintLegend(legIdx); });
  }
  function paintLegend(i) {
    if (!W.disp.length) return;
    if (i == null || i < 0 || i >= W.disp.length) i = W.disp.length - 1;
    W.xIdx = i;
    var c = W.disp[i], pv = i ? W.disp[i - 1].close : c.open;
    /* The close is ink. The change is green or red by its own sign, and
       says so with an arrow as well as a colour. */
    var chg = pv ? (c.close - pv) / pv * 100 : 0, rose = c.close - pv >= 0, col = rose ? "var(--gain)" : "var(--loss)";
    var el = legEl.querySelector('[data-v="ohlc"]');
    if (el) el.innerHTML = "<span class='k'>O</span>" + fmt(c.open) + " <span class='k'>H</span>" + fmt(c.high) +
      " <span class='k'>L</span>" + fmt(c.low) + " <span class='k'>C</span><b>" + fmt(c.close) + "</b> " +
      "<span style='color:" + col + "'>" + (rose ? "\u25B2 +" : "\u25BC ") + fmt(c.close - pv) + " (" + pctS(chg) + ")</span>" +
      (W.rows[i] && W.rows[i].volume ? " <span class='k'>Vol</span>" + fmtV(W.rows[i].volume) : "");
    W.st.forEach(function (s) {
      var holder = (s.def.pane ? subEl : legEl).querySelector('[data-v="' + s.uid + '"]');
      if (!holder) return;
      holder.innerHTML = s.def.out.map(function (o) {
        var v = s.data && s.data[o.k] ? s.data[o.k][i] : null;
        if (!ok(v)) return "";
        return "<span style='color:" + colOf(s, o) + "'>" + (s.def.fmt === "volume" || s.id === "vol" ? fmtV(v) : fmt(v, s.def.prec)) + "</span>";
      }).join(" ");
    });
    W.cmp.forEach(function (cp) {
      var h2 = legEl.querySelector('[data-v="cmp-' + cp.sym + '"]'); if (!h2) return;
      var r = cp.byTime && cp.byTime[c.time];
      h2.textContent = r != null ? fmt(r) : "";
    });
    if (L.side && L.sideTab === "data") dataWindow();
  }

  function legendClick(e) {
    var b = e.target.closest("button[data-lg]"); if (!b) return;
    e.stopPropagation();
    var u = b.dataset.u, a = b.dataset.lg;
    if (a === "cmprm") { W.cmp = W.cmp.filter(function (c) { return c.sym !== u; }); rebuild(true, true); return; }
    var s = studyOf(u); if (!s) return;
    if (a === "eye") { s.hidden = !s.hidden; saveLayout(); rebuild(true, true); }
    if (a === "set") studySettings(u);
    if (a === "rm") removeStudy(u);
  }

  /* ── side panel: object tree and data window ──────────────────────────── */

  function toggleSide(on, tab) {
    L.side = on == null ? !L.side : on;
    if (tab) L.sideTab = tab;
    saveLayout();
    root.classList.toggle("side-on", L.side);
    root.querySelector('[data-a="side"]').classList.toggle("on", L.side);
    sideRefresh();
    setTimeout(function () { charts().forEach(function (c) { try { c.timeScale().applyOptions({}); } catch (e) {} }); render(); }, 30);
  }
  function sideRefresh() {
    if (!sideEl || !L.side) return;
    var h = '<div class="cw-side-tabs"><button type="button" data-st="tree" class="' + (L.sideTab === "tree" ? "on" : "") + '">Objects</button>' +
      '<button type="button" data-st="data" class="' + (L.sideTab === "data" ? "on" : "") + '">Data window</button>' +
      '<button type="button" class="cw-x" data-st="close" aria-label="Close">' + svg("x") + "</button></div><div class='cw-side-b'>";
    if (L.sideTab === "tree") {
      h += "<h4>Drawings <em>" + W.drawings.length + "</em></h4>";
      h += W.drawings.length ? W.drawings.slice().reverse().map(function (d) {
        return '<div class="cw-ob' + (d === W.sel ? " on" : "") + (d.hidden ? " off" : "") + '" data-id="' + d.id + '">' + svg(d.type) +
          '<span>' + esc((T[d.type] || {}).lab || d.type) + (d.text ? ": " + esc(d.text.slice(0, 18)) : "") + "</span>" +
          '<button type="button" data-ob="eye" aria-label="Show or hide">' + svg(d.hidden ? "eyeOff" : "eye") + "</button>" +
          '<button type="button" data-ob="lock" aria-label="Lock">' + svg(d.locked ? "lock" : "unlock") + "</button>" +
          '<button type="button" data-ob="rm" aria-label="Remove">' + svg("trash") + "</button></div>";
      }).join("") : "<p class='cw-p'>Nothing drawn on " + esc(W.sym || "this chart") + " yet.</p>";
      h += "<h4>Indicators <em>" + L.studies.length + "</em></h4>";
      h += L.studies.map(function (x) {
        var s = { def: M.indicator(x.id), p: x.p };
        return '<div class="cw-ob' + (x.hidden ? " off" : "") + '" data-u="' + x.uid + '">' + svg("fx") + "<span>" + esc(studyLabel(s)) + "</span>" +
          '<button type="button" data-os="eye" aria-label="Show or hide">' + svg(x.hidden ? "eyeOff" : "eye") + "</button>" +
          '<button type="button" data-os="set" aria-label="Settings">' + svg("gear") + "</button>" +
          '<button type="button" data-os="rm" aria-label="Remove">' + svg("trash") + "</button></div>";
      }).join("") + '<button type="button" class="cw-btn" data-os="add">Add an indicator</button>';
    } else h += '<div class="cw-dw"></div>';
    sideEl.innerHTML = h + "</div>";
    if (L.sideTab === "data") dataWindow();
  }
  function dataWindow() {
    var el = sideEl && sideEl.querySelector(".cw-dw"); if (!el || !W.disp.length) return;
    var i = W.xIdx == null ? W.disp.length - 1 : W.xIdx, c = W.disp[i], r = W.rows[i] || c;
    var rows2 = [["Date", fmtT(c.time, !!tfOf(L.tf).intra)], ["Open", fmt(c.open)], ["High", fmt(c.high)], ["Low", fmt(c.low)], ["Close", fmt(c.close)],
      ["Change", i ? pctS((c.close - W.disp[i - 1].close) / W.disp[i - 1].close * 100) : "–"], ["Volume", fmtV(r.volume)]];
    var h = "<h4>" + esc(W.sym) + " " + esc(L.tf) + "</h4>" + rows2.map(function (x) { return "<div class='cw-dw-r'><span>" + x[0] + "</span><b>" + x[1] + "</b></div>"; }).join("");
    W.st.forEach(function (s) {
      h += "<h4>" + esc(studyLabel(s)) + "</h4>";
      s.def.out.forEach(function (o) {
        var v = s.data && s.data[o.k] ? s.data[o.k][i] : null;
        h += "<div class='cw-dw-r'><span><i class='cw-lg-dot' style='background:" + colOf(s, o) + "'></i>" + esc(o.l) + "</span><b>" +
          (ok(v) ? (s.def.fmt === "volume" || s.id === "vol" ? fmtV(v) : fmt(v, s.def.prec)) : "–") + "</b></div>";
      });
    });
    el.innerHTML = h;
  }
  function sideClick(e) {
    var t = e.target.closest("[data-st]");
    if (t) { if (t.dataset.st === "close") toggleSide(false); else { L.sideTab = t.dataset.st; saveLayout(); sideRefresh(); } return; }
    var ob = e.target.closest("[data-ob]"), row2 = e.target.closest(".cw-ob[data-id]");
    if (row2) {
      var d = byId(row2.dataset.id); if (!d) return;
      if (ob) {
        push();
        if (ob.dataset.ob === "eye") d.hidden = !d.hidden;
        if (ob.dataset.ob === "lock") d.locked = !d.locked;
        if (ob.dataset.ob === "rm") { W.drawings = W.drawings.filter(function (x) { return x !== d; }); if (W.sel === d) W.sel = null; }
        changed(); return;
      }
      select(d.hidden ? null : d);
      return;
    }
    var os = e.target.closest("[data-os]");
    if (os) {
      if (os.dataset.os === "add") { indicatorDialog(); return; }
      var u = os.closest("[data-u]").dataset.u, s = studyOf(u); if (!s) return;
      if (os.dataset.os === "eye") { s.hidden = !s.hidden; saveLayout(); rebuild(true, true); }
      if (os.dataset.os === "set") studySettings(u);
      if (os.dataset.os === "rm") removeStudy(u);
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
     LOADING
     ══════════════════════════════════════════════════════════════════════ */

  function setPrice(px, prev) {
    if (px == null) { pxEl.textContent = "–"; return; }
    pxEl.textContent = "₹" + fmt(px);
    if (prev != null && px !== prev) {
      pxEl.classList.remove("up", "dn"); void pxEl.offsetWidth;
      pxEl.classList.add(px > prev ? "up" : "dn");
    }
    var base = W.meta && W.meta.prev_close;
    if (base) {
      var c = (px - base) / base * 100;
      chgEl.textContent = (c >= 0 ? "▲ " : "▼ ") + Math.abs(c).toFixed(2) + "%";
      chgEl.title = "Change today, from yesterday's close of " + fmt(base);
      chgEl.className = "cw-chg " + (c >= 0 ? "up" : "dn");
    } else chgEl.textContent = "";
  }

  function rowsFrom(d) {
    return (d.candles || []).filter(function (r) { return r && r[0] != null && ok(r[4]); }).map(function (r) {
      return { time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[9] || 0 };
    });
  }

  function fetchChart(sym, range) {
    var k = sym + "|" + range, c = W.cache[k];
    if (c && Date.now() - c.at < 60000) return Promise.resolve(c.d);
    return fetch(API + "/chart?ticker=" + encodeURIComponent(sym) + "&range=" + encodeURIComponent(range)).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (d) {
        if (!res.ok) { var err = new Error((d && d.detail) || "Unavailable"); err.status = res.status; throw err; }
        W.cache[k] = { at: Date.now(), d: d };
        return d;
      });
    });
  }

  function loadData(sym, tf) {
    if (sym) {
      sym = String(sym).trim().toUpperCase().replace(/\.(NS|BO)$/, "").replace(/[^A-Z0-9&.\-^]/g, "");
      if (!sym) return;
      if (sym !== W.sym) {
        save();
        W.sym = sym; loadDrawings(); W.cmp = [];
        if (W.replay) stopReplay(true);
        try { sset("altaha.charts.v2.last", sym); } catch (e) {}
      }
      $("cw-in").value = sym;
    }
    if (tf) { L.tf = tf; saveLayout(); }
    if (!W.sym) return;
    tfButtons();
    if (!ensure()) { requestAnimationFrame(function () { loadData(); }); return; }
    var req = ++W.req, t = tfOf(L.tf);
    msg("Loading " + W.sym + " " + L.tf + "…");
    note("Fetching candles");
    fetchChart(W.sym, t.fetch).then(function (d) {
      if (req !== W.req) return;
      var rows = rowsFrom(d);
      if (!rows.length) { msg("No candles came back for " + W.sym + "."); return; }
      W.meta = d; W.live = !!d.live;
      W.off = (rows[0].time % 86400 === 66600) ? 19800 : 0;
      var first = !W.raw.length || W.lastKey !== W.sym + "|" + L.tf;
      W.lastKey = W.sym + "|" + L.tf;
      W.raw = rows;
      if (W.replay) W.replay.idx = Math.min(W.replay.idx, rows.length - 1);
      W.chart.applyOptions(theme(false));
      rebuild(true, !first);
      if (first) resetView();
      msg("");
      setPrice(d.last, null); W.lastPx = d.last;
      liveEl.classList.toggle("on", !!d.live);
      liveEl.querySelector("span").textContent = d.live ? "Live" : "Delayed";
      note(W.full.length + " bars, " + (d.live ? "intraday via the live feed" : "daily feed") + ", " +
           W.drawings.length + " drawing" + (W.drawings.length === 1 ? "" : "s") + ".");
      startLive(); scheduleRefresh(!!d.live);
      refreshCompares();
    }).catch(function (e) {
      if (req !== W.req) return;
      if (t.intra && (e.status === 503 || e.status === 404)) {
        msg("<div><b>" + esc(e.message) + "</b><br><button type='button' class='cw-btn primary' data-fallback='1D'>Show the daily chart</button></div>", true);
        note("Intraday bars need the live data feed.");
      } else if (e.status) { msg(String(e.message).slice(0, 180)); note("No data for this timeframe."); }
      else { msg("Chart unavailable. The engine may be waking up; it usually takes under a minute."); note("Retry in a moment."); }
    });
  }

  function tfButtons() {
    $("cw-tfs").querySelectorAll("button").forEach(function (b) {
      var on = b.dataset.r === L.tf;
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var tb = $("cw-type"); if (tb) tb.firstChild.outerHTML = svg(TYPE_ICON[L.type] || "candles");
  }

  function scheduleRefresh(live) {
    if (W.refresh) { clearInterval(W.refresh); W.refresh = null; }
    if (!live) return;
    W.refresh = setInterval(function () {
      if (document.visibilityState !== "visible" || !marketOpen() || !visible() || W.replay) return;
      delete W.cache[W.sym + "|" + tfOf(L.tf).fetch];
      loadData();
    }, 120000);
  }

  /* ── live ticks ─────────────────────────────────────────────────────────
     The last candle is moved in place from a quote every second or two, so
     the wick grows while you watch. /stream/quotes is tried first and /quote
     polled if the stream is not there. */

  function stopLive() {
    if (W.es) { try { W.es.close(); } catch (e) {} W.es = null; }
    if (W.poll) { clearInterval(W.poll); W.poll = null; }
  }
  function applyTick(px) {
    if (!px || !W.raw.length) return;
    var prev = W.lastPx;
    var last = W.raw[W.raw.length - 1];
    last.close = px; last.high = Math.max(last.high, px); last.low = Math.min(last.low, px);
    setPrice(px, prev); W.lastPx = px; W.lastTick = Date.now();
    liveEl.classList.add("on"); liveEl.querySelector("span").textContent = "Live";
    checkAlerts(prev, px);
    if (W.replay) return;
    /* The candle at once; the indicators at most once a second. */
    derive();
    try {
      var dd = mainData();
      W.main.update(dd[dd.length - 1]);
    } catch (e) {}
    if (!W.tickTimer) W.tickTimer = setTimeout(function () { W.tickTimer = null; rebuild(false, true); }, 1000);
    render();
  }
  function startLive() {
    stopLive();
    if (!W.sym || typeof EventSource === "undefined") { startPoll(); return; }
    var sse, ok2 = false;
    try { sse = new EventSource(API + "/stream/quotes?tickers=" + encodeURIComponent(W.sym)); } catch (e) { startPoll(); return; }
    sse.onmessage = function (ev) {
      ok2 = true;
      try { var d = JSON.parse(ev.data); var px = d.ltp != null ? d.ltp : (d[W.sym] && d[W.sym].ltp); if (px) applyTick(px); } catch (e) {}
    };
    sse.onerror = function () { try { sse.close(); } catch (e) {} W.es = null; if (!ok2) startPoll(); };
    W.es = sse;
    setTimeout(function () { if (!ok2 && W.es === sse) { stopLive(); startPoll(); } }, 4000);
  }
  function startPoll() {
    if (W.poll) clearInterval(W.poll);
    W.poll = setInterval(function () {
      if (document.visibilityState !== "visible" || !marketOpen() || !visible()) return;
      fetch(API + "/quote?ticker=" + encodeURIComponent(W.sym)).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (q) { if (q && q.ltp) applyTick(q.ltp); }).catch(function () {});
    }, 3000);
  }
  setInterval(function () {
    if (!W.lastTick || !liveEl) return;
    var age = Math.round((Date.now() - W.lastTick) / 1000);
    if (!marketOpen()) { liveEl.classList.remove("on"); liveEl.querySelector("span").textContent = "Closed"; return; }
    if (age > 25) { liveEl.classList.remove("on"); liveEl.querySelector("span").textContent = "Stale " + age + "s"; }
  }, 5000);

  /* ── compare ─────────────────────────────────────────────────────────── */

  function cmpData(cp) {
    var tf = tfOf(L.tf), rows = cp.raw;
    if (tf.n) rows = M.resampleIntraday(rows, tf.n);
    else if (tf.month) rows = M.resample(rows, function (r) { return M.monthKey(r.time + W.off); });
    var have = {};
    W.times.forEach(function (t) { have[t] = 1; });
    cp.byTime = {};
    var out = [];
    rows.forEach(function (r) { if (have[r.time]) { out.push({ time: r.time, value: r.close }); cp.byTime[r.time] = r.close; } });
    return out;
  }
  function addCompare(sym) {
    sym = String(sym || "").trim().toUpperCase().replace(/\.(NS|BO)$/, "");
    if (!sym || sym === W.sym) return;
    if (W.cmp.some(function (c) { return c.sym === sym; })) { toast(sym + " is already compared."); return; }
    if (W.cmp.length >= 4) { toast("Four comparisons at most."); return; }
    note("Fetching " + sym);
    fetchChart(sym, tfOf(L.tf).fetch).then(function (d) {
      var rows = rowsFrom(d);
      if (!rows.length) { toast("No candles for " + sym + "."); return; }
      W.cmp.push({ sym: sym, raw: rows, color: asColor(CMP_COLORS[W.cmp.length % CMP_COLORS.length]) });
      rebuild(true, true);
      toast(sym + " added. The scale is now in percent from the left edge of the screen.");
    }).catch(function (e) { toast("Could not load " + sym + ": " + (e.message || "unavailable")); });
  }
  function refreshCompares() {
    var syms = W.cmp.map(function (c) { return c.sym; });
    if (!syms.length) return;
    Promise.all(syms.map(function (s) { return fetchChart(s, tfOf(L.tf).fetch).then(rowsFrom).catch(function () { return []; }); }))
      .then(function (all) {
        all.forEach(function (rows, i) { if (W.cmp[i]) W.cmp[i].raw = rows; });
        W.cmp = W.cmp.filter(function (c) { return c.raw.length; });
        rebuild(true, true);
      });
  }
  function compareDialog(anchor) {
    var wrap = document.createElement("div");
    wrap.className = "cw-cmp";
    wrap.innerHTML = '<input type="text" placeholder="Symbol to compare, e.g. NIFTYBEES" aria-label="Symbol to compare" spellcheck="false" autocomplete="off">' +
      '<div class="cw-cmp-l"></div>' +
      (W.cmp.length ? "<div class='cw-pop-h'>Compared</div>" + W.cmp.map(function (c) {
        return '<button type="button" class="cw-pop-i" data-rm="' + esc(c.sym) + '"><i class="cw-lg-dot" style="background:' + c.color + '"></i><span>' + esc(c.sym) + "</span>" + svg("x") + "</button>";
      }).join("") : "");
    var p = pop(anchor, wrap, "cw-pop-cmp"), inp = wrap.querySelector("input"), list = wrap.querySelector(".cw-cmp-l");
    function draw() {
      list.innerHTML = suggest(inp.value, 6).map(function (r) {
        return '<button type="button" class="cw-pop-i" data-s="' + esc(r.s) + '"><b>' + esc(r.s) + "</b><span>" + esc(r.n || "") + "</span></button>";
      }).join("");
    }
    inp.addEventListener("input", draw);
    inp.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Enter") { closePops(); addCompare(inp.value); } if (e.key === "Escape") closePops(); });
    wrap.addEventListener("click", function (e) {
      var s = e.target.closest("[data-s]"); if (s) { closePops(); addCompare(s.dataset.s); return; }
      var r = e.target.closest("[data-rm]"); if (r) { W.cmp = W.cmp.filter(function (c) { return c.sym !== r.dataset.rm; }); closePops(); rebuild(true, true); }
    });
    universe(draw);
    inp.focus();
    return p;
  }

  /* ── symbol search ───────────────────────────────────────────────────── */

  function universe(cb) {
    if (W.universe) { cb && cb(); return; }
    // v3: the list now carries NSE SME and BSE; see the note in shell.js.
    var cached = sget("altaha.charts.v3.universe", null);
    if (cached && cached.at && Date.now() - cached.at < 86400000 && cached.rows && cached.rows.length) { W.universe = cached.rows; cb && cb(); return; }
    /* Everyone who asked while the list was on its way is answered when it
       lands: the first letters of a first visit arrive before it does. */
    universe.wait = universe.wait || [];
    if (cb) universe.wait.push(cb);
    if (universe.busy) return;
    universe.busy = true;
    fetch(API + "/universe?v=4").then(function (r) { return r.json(); }).then(function (d) {
      W.universe = (d.rows || []).map(function (r) { return { s: r.s || r[0], n: r.n || r[1] || "" }; }).filter(function (r) { return r.s; });
      if (W.universe.length && d.v >= 4) sset("altaha.charts.v3.universe", { at: Date.now(), rows: W.universe });
    }).catch(function () {}).then(function () {
      universe.busy = false;
      var run = universe.wait; universe.wait = [];
      run.forEach(function (f) { try { f(); } catch (e) {} });
    });
  }
  function suggest(q, n) {
    q = String(q || "").trim().toUpperCase();
    if (!q || !W.universe) return [];
    var a = [], b = [], c = [];
    for (var i = 0; i < W.universe.length && a.length < n; i++) {
      var r = W.universe[i], s = r.s.toUpperCase(), nm = (r.n || "").toUpperCase();
      if (s === q) a.unshift(r);
      else if (s.indexOf(q) === 0) a.push(r);
      else if (nm.indexOf(q) === 0) b.push(r);
      else if (s.indexOf(q) > 0 || nm.indexOf(q) > 0) c.push(r);
    }
    return a.concat(b, c).slice(0, n);
  }
  function symSuggest() {
    var inp = $("cw-in"), q = inp.value;
    var old = $("cw-sug"); if (old) old.remove();
    var list = suggest(q, 8);
    if (!list.length) { inp.setAttribute("aria-expanded", "false"); return; }
    var el = document.createElement("div");
    el.id = "cw-sug"; el.className = "cw-pop cw-sug"; el.setAttribute("role", "listbox");
    el.innerHTML = list.map(function (r, i) {
      return '<button type="button" role="option" class="cw-pop-i' + (i === 0 ? " on" : "") + '" data-s="' + esc(r.s) + '"><b>' + esc(r.s) + "</b><span>" + esc(r.n || "") + "</span></button>";
    }).join("");
    root.appendChild(el);
    var R = root.getBoundingClientRect(), r2 = inp.parentNode.getBoundingClientRect();
    el.style.left = Math.max(6, r2.left - R.left) + "px"; el.style.top = (r2.bottom - R.top + 4) + "px";
    inp.setAttribute("aria-expanded", "true");
    el.addEventListener("pointerdown", function (e) {
      var b = e.target.closest("[data-s]"); if (!b) return;
      e.preventDefault(); el.remove(); inp.setAttribute("aria-expanded", "false"); loadData(b.dataset.s, null); inp.blur();
    });
  }

  /* ── bar replay ──────────────────────────────────────────────────────────
     The chart is cut at a bar of your choosing and played forward one bar at
     a time. Indicators are computed only on what has been "seen", so nothing
     from the future leaks onto the screen. */

  function startReplay(idx) {
    if (!W.full.length) return;
    W.replay = { idx: clamp(idx, 1, W.full.length - 1), playing: false, speed: 1, timer: null };
    rebuild(false, true);
    replayBar();
    toast("Replay from " + fmtT(W.full[W.replay.idx].time, !!tfOf(L.tf).intra) + ". Press play or step one bar at a time.");
  }
  function stopReplay(silent) {
    if (!W.replay) return;
    clearInterval(W.replay.timer);
    W.replay = null;
    $("cw-replay").classList.remove("on");
    root.querySelector('[data-a="replay"]').classList.remove("on");
    if (!silent) { rebuild(false, true); resetView(); }
  }
  function replayStep() {
    var R = W.replay; if (!R) return;
    if (R.idx >= W.full.length - 1) { R.playing = false; clearInterval(R.timer); replayBar(); toast("Replay reached the latest bar."); return; }
    var g = geo(), atEnd = g && g.to >= W.rows.length - 2;
    R.idx++;
    rebuild(false, true);
    if (atEnd) scrollBars(1);
    replayBar();
  }
  function replayBar() {
    var R = W.replay, el = $("cw-replay");
    root.querySelector('[data-a="replay"]').classList.toggle("on", !!R);
    if (!R) { el.classList.remove("on"); return; }
    el.innerHTML = '<button type="button" data-rp="play" aria-label="' + (R.playing ? "Pause" : "Play") + '">' + svg(R.playing ? "pause" : "play") + "</button>" +
      '<button type="button" data-rp="step" aria-label="Forward one bar">' + svg("step") + "</button>" +
      '<select data-rp="speed" aria-label="Speed">' + [1, 2, 5, 10].map(function (s) { return '<option value="' + s + '"' + (R.speed === s ? " selected" : "") + ">" + s + "x</option>"; }).join("") + "</select>" +
      '<span class="cw-rp-d">' + esc(fmtT(W.full[R.idx].time, !!tfOf(L.tf).intra)) + "</span>" +
      '<button type="button" data-rp="pick">Pick bar</button>' +
      '<button type="button" data-rp="exit" class="cw-rp-x">Exit replay</button>';
    el.classList.add("on");
  }
  function replayClick(e) {
    var b = e.target.closest("[data-rp]"); if (!b || b.tagName === "SELECT") return;
    var R = W.replay; if (!R) return;
    var a = b.dataset.rp;
    if (a === "play") {
      R.playing = !R.playing; clearInterval(R.timer);
      if (R.playing) R.timer = setInterval(replayStep, 1000 / R.speed);
      replayBar();
    } else if (a === "step") { R.playing = false; clearInterval(R.timer); replayStep(); }
    else if (a === "pick") { R.playing = false; clearInterval(R.timer); setMode("replay-pick"); }
    else if (a === "exit") stopReplay(false);
  }

  /* ── image export ─────────────────────────────────────────────────────── */

  function snapshot() {
    if (!W.chart) return null;
    var base = W.chart.takeScreenshot(), sc = base.width / box.clientWidth;
    var shots = W.panes.map(function (p) { return p.chart.takeScreenshot(); });
    var head = Math.round(30 * sc), total = head + base.height + shots.reduce(function (s, c) { return s + c.height; }, 0);
    var out = document.createElement("canvas");
    out.width = base.width; out.height = total;
    var c = out.getContext("2d");
    c.fillStyle = tok("--surface"); c.fillRect(0, 0, out.width, out.height);
    c.drawImage(base, 0, head);
    /* Every overlay on the price chart, in the order it is stacked. */
    var ovs = box.querySelectorAll("canvas.cw-patov, #cw-cv");
    ovs.forEach(function (ov) { try { c.drawImage(ov, 0, 0, ov.width, ov.height, 0, head, base.width, base.height); } catch (e) {} });
    var y = head + base.height;
    shots.forEach(function (s) { c.drawImage(s, 0, y); y += s.height; });
    c.fillStyle = tok("--text-primary");
    c.font = "600 " + Math.round(13 * sc) + "px " + Th.font("--font-sans");   // theme-ok: pixels of the exported image, scaled by its density
    var last = W.disp[W.disp.length - 1];
    c.fillText(W.sym + "  " + L.tf + "  " + (last ? fmtT(last.time, !!tfOf(L.tf).intra) + "  C " + fmt(last.close) : ""), 10 * sc, 20 * sc);
    c.font = "500 " + Math.round(11 * sc) + "px " + Th.font("--font-sans");   // theme-ok: pixels of the exported image, scaled by its density
    c.fillStyle = tok("--text-muted");
    var wm = "altaha screener";
    c.fillText(wm, out.width - c.measureText(wm).width - 10 * sc, 20 * sc);
    return out;
  }
  function shotMenu(anchor) {
    listPop(anchor, [
      { lab: "Download image", icon: "camera", fn: function () {
        try {
          var out = snapshot(); if (!out) return;
          var a = document.createElement("a");
          a.href = out.toDataURL("image/png"); a.download = W.sym + "-" + L.tf + ".png"; a.click();
          note("Saved " + a.download + ".");
        } catch (e) { note("Could not export this chart."); }
      } },
      { lab: "Copy image", icon: "copy", fn: function () {
        try {
          var out = snapshot(); if (!out || !navigator.clipboard || !window.ClipboardItem) { note("This browser cannot copy images. Use Download."); return; }
          out.toBlob(function (b) {
            navigator.clipboard.write([new ClipboardItem({ "image/png": b })]).then(function () { toast("Image copied."); }, function () { note("Copying was blocked. Use Download."); });
          });
        } catch (e) { note("Could not copy this chart."); }
      } }
    ]);
  }

  /* ── settings, shortcuts, go to date ──────────────────────────────────── */

  function chartSettings() {
    var s = L.set;
    var h = '<div class="cw-form">' +
      row("Rising candles", '<input type="color" data-s="up" value="' + hex6(upC()) + '">') +
      row("Falling candles", '<input type="color" data-s="down" value="' + hex6(dnC()) + '">') +
      row("Grid lines", '<input type="checkbox" data-s="grid"' + (s.grid ? " checked" : "") + ">") +
      row("Crosshair snaps to the close", '<input type="checkbox" data-s="cross"' + (s.cross ? " checked" : "") + ">") +
      row("Last price line", '<input type="checkbox" data-s="last"' + (s.last ? " checked" : "") + ">") +
      row("Support and resistance from the engine", '<input type="checkbox" data-s="levels"' + (s.levels ? " checked" : "") + ">") +
      row("Symbol watermark", '<input type="checkbox" data-s="wm"' + (s.wm ? " checked" : "") + ">") +
      row("Invert the price scale", '<input type="checkbox" data-l="invert"' + (L.invert ? " checked" : "") + ">") +
      "</div>";
    var m = modal("Chart settings", h, { foot: [
      { lab: "Defaults", fn: function () { L.set = clone(DEF.set); L.invert = false; saveLayout(); restyle(); } },
      { lab: "Done", primary: true, fn: function () {} }
    ] });
    m.querySelectorAll("[data-s],[data-l]").forEach(function (el) {
      el.addEventListener(el.type === "color" ? "input" : "change", function () {
        var v = el.type === "checkbox" ? (el.dataset.s === "cross" ? (el.checked ? 1 : 0) : el.checked) : el.value;
        if (el.dataset.l) L[el.dataset.l] = v; else s[el.dataset.s] = v;
        saveLayout(); restyle();
      });
    });
  }
  function restyle() {
    charts().forEach(function (c, i) { c.applyOptions(theme(i > 0)); });
    if (W.panes.length) W.chart.applyOptions({ timeScale: { visible: false } });
    W.seriesSig = ""; rebuild(true, true);
  }

  function shortcuts() {
    var rows2 = [["Esc", "Cancel the tool, deselect, leave full screen"], ["Delete", "Remove the selected drawing"],
      ["Ctrl+Z / Ctrl+Y", "Undo / redo"], ["Ctrl+C, Ctrl+V", "Copy and paste a drawing"], ["Ctrl+D", "Clone the selected drawing"],
      ["Alt+T", "Trend line"], ["Alt+H", "Horizontal line"], ["Alt+J", "Horizontal ray"], ["Alt+V", "Vertical line"], ["Alt+C", "Cross line"],
      ["Alt+F", "Fib retracement"], ["Alt+R", "Reset the chart view"], ["Alt+B", "Rectangle"], ["Alt+A", "Alert at the last price"],
      ["/", "Indicators"], ["Shift+F", "Full screen"], ["← →", "Scroll a bar"], ["+ −", "Zoom"],
      ["Shift while drawing", "Keep a trend line level"], ["Shift+wheel", "Scroll through time"], ["Right-click", "More, for a drawing or the chart"]];
    modal("Keyboard shortcuts", "<div class='cw-keys'>" + rows2.map(function (r) { return "<kbd>" + esc(r[0]) + "</kbd><span>" + esc(r[1]) + "</span>"; }).join("") + "</div>");
  }

  function gotoDate(anchor) {
    var wrap = document.createElement("div");
    wrap.className = "cw-goto";
    var last = W.rows[W.rows.length - 1];
    wrap.innerHTML = '<label>Go to<input type="date" value="' + (last ? new Date((last.time + W.off) * 1000).toISOString().slice(0, 10) : "") + '"></label><button type="button" class="cw-btn primary">Go</button>';
    pop(anchor, wrap, "cw-pop-goto");
    var inp = wrap.querySelector("input");
    inp.focus();
    function go() {
      var t = Date.parse(inp.value + "T00:00:00Z") / 1000 - W.off;
      if (!ok(t)) return;
      closePops();
      if (W.times.length && t < W.times[0]) toast("The chart starts on " + fmtT(W.times[0]) + "; that is as far back as it goes.");
      var l = tToL(t), g = geo(), half = g ? (g.to - g.from) / 2 : 60;
      W.chart.timeScale().setVisibleLogicalRange({ from: l - half, to: l + half });
      var o = newDrawing("vline", [{ t: W.times[idxOf(t)] || t, p: W.rows[idxOf(t)] ? W.rows[idxOf(t)].close : 0 }]);
      W.flash = o; flash(o);
    }
    wrap.querySelector("button").addEventListener("click", go);
    inp.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Enter") go(); });
  }
  function flash(o) {
    o.style = "dash"; o.width = 1; o.color = "--highlight";
    W.drawings.push(o); render();
    setTimeout(function () { W.drawings = W.drawings.filter(function (x) { return x !== o; }); render(); }, 1600);
  }

  function zoomPreset(z) {
    if (!W.rows.length) return;
    var last = W.rows[W.rows.length - 1].time + W.off, d = new Date(last * 1000), from;
    var dayS = 86400;
    if (z === "All") { W.chart.timeScale().setVisibleLogicalRange({ from: -2, to: W.disp.length + 6 }); return; }
    if (z === "YTD") from = Date.UTC(d.getUTCFullYear(), 0, 1) / 1000;
    else {
      var map = { "1D": 1, "5D": 5, "1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826 };
      from = last - (map[z] || 30) * dayS;
      if (z === "1D") from = Math.floor(last / dayS) * dayS;
    }
    /* Ask for a coarser bar when the range is far wider than the screen can
       hold at this timeframe, and a finer one when it is narrower. */
    var tf = tfOf(L.tf), wantTf = null;
    if ((z === "1D" || z === "5D") && !tf.intra) wantTf = z === "1D" ? "5m" : "15m";
    else if ((z === "5Y" || z === "All") && tf.intra) wantTf = "1D";
    else if (z === "5Y" && L.tf === "1D") wantTf = "1W";
    if (wantTf && wantTf !== L.tf) { W.pendingZoom = z; loadData(null, wantTf); return; }
    var l = tToL(from - W.off);
    W.chart.timeScale().setVisibleLogicalRange({ from: Math.max(-2, l), to: W.disp.length + 4 });
    if (l < -1) toast("The chart holds " + fmtT(W.times[0]) + " onwards; this is all of it.");
  }

  /* ══════════════════════════════════════════════════════════════════════
     FULL SCREEN
     The Fullscreen API where there is one; on an iPhone, which has none for
     anything but video, the workspace is fixed over the page instead.
     ══════════════════════════════════════════════════════════════════════ */

  function isFull() { return document.fullscreenElement === root || document.webkitFullscreenElement === root || root.classList.contains("cw-max"); }
  function toggleFull(force) {
    var want = force == null ? !isFull() : force;
    var req = root.requestFullscreen || root.webkitRequestFullscreen;
    if (want) {
      if (req && !root.classList.contains("cw-max")) {
        Promise.resolve(req.call(root)).catch(function () { maxOn(true); });
      } else maxOn(true);
    } else {
      if (document.fullscreenElement || document.webkitFullscreenElement) {
        (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      }
      maxOn(false);
    }
  }
  function maxOn(on) {
    root.classList.toggle("cw-max", on);
    document.documentElement.classList.toggle("cw-max-on", on);
    fullState();
  }
  function fullState() {
    var f = isFull(), b = $("cw-full"), tape = root.querySelector(".cw-tape");
    if (tape) tape.scrollLeft = 0;
    if (b) { b.innerHTML = svg(f ? "unfull" : "full"); b.classList.toggle("on", f); b.setAttribute("aria-label", f ? "Leave full screen" : "Full screen"); }
    setTimeout(function () {
      if (tape) tape.scrollLeft = 0;
      charts().forEach(function (c) { try { c.applyOptions({}); } catch (e) {} });
      render();
    }, 60);
  }

  /* ══════════════════════════════════════════════════════════════════════
     WIRING
     ══════════════════════════════════════════════════════════════════════ */

  function visible() { var v = $("view-charts"); return !!(v && v.style.display !== "none" && v.offsetParent !== null) || isFull(); }

  function bind() {
    root = $("cw"); box = $("cw-price"); cv = $("cw-cv"); ctx = cv.getContext("2d");
    msgEl = $("cw-msg"); noteEl = $("cw-note"); legEl = $("cw-legend"); inspEl = $("cw-insp");
    pxEl = $("cw-px"); chgEl = $("cw-chg"); liveEl = $("cw-live"); subEl = $("cw-sub"); sideEl = $("cw-side"); toastEl = $("cw-toast");
    W.lastTool = sget("altaha.charts.v2.tools", {}) || {};
    $("cw-rail").innerHTML = railHTML();

    /* Symbol box. */
    var inp = $("cw-in");
    function go() {
      var s = $("cw-sug"), first = s && s.querySelector(".cw-pop-i.on");
      var v = first ? first.dataset.s : inp.value;
      closePops();
      if (v && v.trim()) loadData(v, null);
      inp.blur();
    }
    $("cw-go").addEventListener("click", go);
    inp.addEventListener("keydown", function (e) {
      var s = $("cw-sug");
      if (e.key === "Enter") { e.preventDefault(); go(); }
      else if (e.key === "Escape") { closePops(); inp.blur(); }
      else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && s) {
        e.preventDefault();
        var items = Array.prototype.slice.call(s.querySelectorAll(".cw-pop-i")), k = items.findIndex(function (x) { return x.classList.contains("on"); });
        if (k >= 0) items[k].classList.remove("on");
        k = (k + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items[k].classList.add("on");
      }
    });
    inp.addEventListener("input", function () { universe(symSuggest); symSuggest(); });
    inp.addEventListener("focus", function () { inp.select(); universe(); });
    inp.addEventListener("blur", function () { setTimeout(function () { var s = $("cw-sug"); if (s && document.activeElement !== inp) s.remove(); }, 150); });

    $("cw-tfs").addEventListener("click", function (e) {
      var b = e.target.closest("button[data-r]"); if (!b) return;
      /* Folded into one button on a narrow workspace: it opens the list. */
      var other = $("cw-tfs").querySelector("button:not(.on)");
      if (b.classList.contains("on") && other && getComputedStyle(other).display === "none") {
        listPop(b, [{ head: "Timeframe" }].concat(TFS.map(function (f) {
          return { lab: f.k, on: f.k === L.tf, fn: function () { if (W.replay) stopReplay(true); loadData(null, f.k); } };
        })), null, "cw-pop-tf");
        return;
      }
      if (W.replay) stopReplay(true);
      loadData(null, b.dataset.r);
    });

    /* Rail: tools, flyouts and the drawing switches. */
    var press = null;
    $("cw-rail").addEventListener("pointerdown", function (e) {
      var b = e.target.closest(".cw-grp .cw-t"); if (!b) return;
      clearTimeout(press);
      press = setTimeout(function () { press = "long"; flyout(b.parentNode); }, 480);
    });
    $("cw-rail").addEventListener("pointerup", function () { if (press !== "long") clearTimeout(press); });
    $("cw-rail").addEventListener("click", function (e) {
      if (press === "long") { press = null; return; }
      var more = e.target.closest("[data-more]");
      if (more) { e.stopPropagation(); flyout(more.parentNode); return; }
      var b = e.target.closest("button"); if (!b) return;
      if (b.dataset.t) {
        var t = b.dataset.t;
        if (t === "pan" || t === "erase") { W.sel = null; inspector(); setMode(t); }
        else if (W.mode === "draw" && W.tool === t) setMode("pan");
        else pickTool(t);
        return;
      }
      var a = b.dataset.a;
      if (a === "magnet") {
        L.magnet = (L.magnet + 1) % 3; saveLayout(); railState();
        note(["Free placement.", "Weak magnet: snaps to an open, high, low or close when you are near one.", "Strong magnet: always snaps to the nearest open, high, low or close."][L.magnet]);
      }
      if (a === "stay") { L.stay = !L.stay; saveLayout(); railState(); note(L.stay ? "The tool stays on after each shape. Esc puts it down." : "The tool puts itself down after each shape."); }
      if (a === "lockall") { W.lockAll = !W.lockAll; railState(); note(W.lockAll ? "All drawings are locked." : "Drawings can be moved again."); }
      if (a === "hideall") { W.hideAll = !W.hideAll; W.sel = null; inspector(); railState(); render(); note(W.hideAll ? "Drawings hidden. They are still saved." : "Drawings shown."); }
      if (a === "remove") listPop(b, [
        { lab: "Remove " + W.drawings.length + " drawings", icon: "trash", fn: removeAll },
        { lab: "Remove " + L.studies.length + " indicators", icon: "fx", fn: function () { L.studies = []; L.paneH = {}; saveLayout(); rebuild(true, true); } },
        { lab: "Remove everything", icon: "trash", danger: true, fn: function () { L.studies = []; saveLayout(); push(); W.drawings = []; W.sel = null; changed(); rebuild(true, true); } }
      ]);
    });

    /* Top bar. */
    root.querySelector(".cw-tape").addEventListener("click", function (e) {
      var b = e.target.closest("button[data-a]"); if (!b) return;
      var a = b.dataset.a;
      if (a === "type") listPop(b, TYPES.map(function (t) { return { lab: t.lab, icon: TYPE_ICON[t.k], on: L.type === t.k, fn: function () { L.type = t.k; saveLayout(); tfButtons(); rebuild(true, true); } }; }));
      if (a === "ind") indicatorDialog();
      if (a === "cmp") compareDialog(b);
      if (a === "replay") { if (W.replay) stopReplay(false); else setMode("replay-pick"); }
      if (a === "alert") { var last = W.rows[W.rows.length - 1]; if (last) addAlert(W.lastPx || last.close, last.time); }
      if (a === "undo") undo();
      if (a === "redo") redo();
      if (a === "settings") chartSettings();
      if (a === "shot") shotMenu(b);
      if (a === "side") toggleSide();
      if (a === "keys") shortcuts();
      if (a === "full") toggleFull();
    });

    inspEl.addEventListener("click", function (e) { var b = e.target.closest("button[data-x]"); if (b) { e.stopPropagation(); inspAction(b.dataset.x, b); } });
    inspEl.addEventListener("pointerdown", function (e) { e.stopPropagation(); });
    legEl.addEventListener("click", legendClick);
    legEl.addEventListener("pointerdown", function (e) { if (e.target.closest("button")) e.stopPropagation(); });
    subEl.addEventListener("click", legendClick);
    sideEl.addEventListener("click", sideClick);
    $("cw-replay").addEventListener("click", replayClick);
    $("cw-replay").addEventListener("change", function (e) {
      if (e.target.dataset.rp !== "speed" || !W.replay) return;
      W.replay.speed = +e.target.value;
      if (W.replay.playing) { clearInterval(W.replay.timer); W.replay.timer = setInterval(replayStep, 1000 / W.replay.speed); }
    });
    msgEl.addEventListener("click", function (e) { var b = e.target.closest("[data-fallback]"); if (b) loadData(null, b.dataset.fallback); });
    $("cw-nav").addEventListener("click", function (e) {
      var b = e.target.closest("[data-nav]"); if (!b) return;
      var a = b.dataset.nav;
      if (a === "zin") zoom(0.7); if (a === "zout") zoom(1.4);
      if (a === "left") scrollBars(-10); if (a === "right") scrollBars(10);
      if (a === "reset") resetView();
    });
    $("cw-rt").addEventListener("click", function () { try { W.chart.timeScale().scrollToRealTime(); } catch (e) {} });

    root.querySelector(".cw-foot").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      if (b.dataset.zoom) { zoomPreset(b.dataset.zoom); return; }
      if (b.dataset.goto) { gotoDate(b); return; }
      var k = b.dataset.scale;
      if (!k) return;
      if (k === "auto") { try { W.chart.priceScale("right").applyOptions({ autoScale: true }); } catch (x) {} }
      if (k === "log") { L.log = !L.log; if (L.log) L.pct = false; }
      if (k === "pct") { if (W.cmp.length) { toast("The scale stays in percent while symbols are compared."); return; } L.pct = !L.pct; if (L.pct) L.log = false; }
      saveLayout(); applyScale(); render();
    });

    /* The chart. */
    cv.addEventListener("pointerdown", safe(onDown));
    cv.addEventListener("pointermove", safe(onMove));
    cv.addEventListener("pointerup", safe(onUp));
    cv.addEventListener("pointercancel", safe(onUp));
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("dblclick", function (e) {
      if (W.mode === "draw" && W.tool === "path") { finishPath(false); return; }
      var pt = local(e), h = hit(pt.x, pt.y);
      if (h) { if (TEXTUAL[h.d.type]) editText(h.d, false); else drawingSettings(h.d); }
    });
    box.addEventListener("contextmenu", contextMenu);
    /* The canvas lets pointer events through to the chart in cursor mode
       until something drawn is under the pointer. A touch has no hover to
       find that out with, so the press itself is checked, and if it landed
       on a drawing the chart is kept from panning while it is dragged. */
    box.addEventListener("pointerdown", function (e) {
      if (W.mode !== "pan" || e.target === cv || e.button === 2) return;
      if (e.target.closest && e.target.closest(".cw-legend button, .cw-insp, .cw-nav, .cw-rt, .cw-replay, .cw-edit, .cw-msg button")) return;
      var r = cv.getBoundingClientRect(), h = hit(e.clientX - r.left, e.clientY - r.top);
      if (!h) { if (W.sel) select(null); closePops(); return; }
      e.stopPropagation(); e.preventDefault();
      W.grab = true;
      try { cv.setPointerCapture(e.pointerId); } catch (x) {}
      cv.classList.add("live");
      onDown(e);
    }, true);
    ["mousedown", "touchstart", "touchmove"].forEach(function (ev) {
      box.addEventListener(ev, function (e) { if (W.grab) { e.stopPropagation(); if (ev !== "mousedown" && e.cancelable) e.preventDefault(); } }, { capture: true, passive: false });
    });
    document.addEventListener("pointerup", function () { if (W.grab) { W.grab = false; } }, true);
    box.addEventListener("pointermove", function (e) { if (W.mode === "pan" && !W.dragging && e.target !== cv) onMove(e); });
    box.addEventListener("pointerleave", function () { if (W.mode !== "pan") { try { W.chart.clearCrosshairPosition(); } catch (e) {} legendAt(null); } });

    document.addEventListener("pointerdown", function (e) {
      if (popEl && !popEl.contains(e.target) && !(e.target.closest && e.target.closest("[data-more],[data-a='type'],[data-a='shot'],[data-a='cmp'],[data-goto],#cw-insp,#cw-in,#cw-tfs"))) closePops();
    }, true);

    document.addEventListener("keydown", keys);
    document.addEventListener("fullscreenchange", fullState);
    document.addEventListener("webkitfullscreenchange", fullState);

    /* Theme flips: lightweight-charts caches its colours. */
    new MutationObserver(function () { if (W.chart) restyle(); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    /* If the view is shown by a route that never called open(). */
    new ResizeObserver(function () { if (box.clientWidth && box.clientHeight && !W.sym && visible()) WS.open(); }).observe(box);

    root.classList.toggle("side-on", !!L.side);
    root.querySelector('[data-a="side"]').classList.toggle("on", !!L.side);
    railState(); tfButtons(); footState();
    setMode("pan");
  }

  /* A drawing that fails must say so. Silently doing nothing is the one
     failure a reader cannot report. */
  function safe(fn) {
    return function (e) {
      try { fn(e); } catch (err) {
        report(err);
        W.dragging = null;
        toast("Something went wrong while drawing (" + (err && err.message || err) + "). Press Esc and try again.", 9000);
      }
    };
  }

  function railState() {
    var r = $("cw-rail");
    var mg = r.querySelector('[data-a="magnet"]');
    mg.classList.toggle("on", L.magnet > 0);
    mg.querySelector(".cw-badge").textContent = L.magnet === 2 ? "S" : L.magnet === 1 ? "W" : "";
    mg.dataset.tip = ["Magnet: off", "Magnet: weak", "Magnet: strong"][L.magnet];
    r.querySelector('[data-a="stay"]').classList.toggle("on", !!L.stay);
    var lk = r.querySelector('[data-a="lockall"]'); lk.classList.toggle("on", W.lockAll); lk.innerHTML = svg(W.lockAll ? "lock" : "unlock");
    var hd = r.querySelector('[data-a="hideall"]'); hd.classList.toggle("on", W.hideAll); hd.innerHTML = svg(W.hideAll ? "eyeOff" : "eye");
  }

  function flyout(grpEl) {
    var g = GROUPS.filter(function (x) { return x.g === grpEl.dataset.g; })[0]; if (!g) return;
    listPop(grpEl, [{ head: g.lab }].concat(g.tools.map(function (t) {
      return { lab: T[t].lab, icon: t, key: T[t].key, on: W.tool === t && W.mode === "draw", fn: function () { pickTool(t); } };
    })), null, "cw-fly");
  }

  function keys(e) {
    if (!visible()) return;
    var tg = e.target, tag = tg && tg.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (tg && tg.isContentEditable)) return;
    if (modalEl || box.querySelector(".cw-edit")) return;
    var k = e.key, low = (k || "").toLowerCase(), mod = e.metaKey || e.ctrlKey;
    if (k === "Escape") {
      if (popEl) { closePops(); return; }
      if (W.mode !== "pan" || W.pending.length) { W.pending = []; W.preview = null; setMode("pan"); return; }
      if (W.sel) { select(null); return; }
      if (root.classList.contains("cw-max")) { toggleFull(false); return; }
      return;
    }
    if (k === "Enter" && W.mode === "draw" && W.tool === "path" && W.pending.length > 1) { finishPath(false); return; }
    if ((k === "Delete" || k === "Backspace") && W.sel) { e.preventDefault(); del(); return; }
    if (mod && low === "z" && !e.shiftKey) { e.preventDefault(); undo(); return; }
    if (mod && (low === "y" || (low === "z" && e.shiftKey))) { e.preventDefault(); redo(); return; }
    if (mod && low === "c" && W.sel) { W.clip = clone(W.sel); note("Copied. Ctrl+V pastes it, here or on another symbol."); return; }
    if (mod && low === "v" && W.clip) { e.preventDefault(); paste(); return; }
    if (mod && low === "d" && W.sel) { e.preventDefault(); duplicate(); return; }
    if (mod) return;
    if (e.altKey) {
      var map = { t: "trend", h: "hline", j: "hray", v: "vline", c: "cross", f: "fib", b: "rect" };
      var code = (e.code || "").replace("Key", "").toLowerCase();
      if (map[code]) { e.preventDefault(); pickTool(map[code]); return; }
      if (code === "r") { e.preventDefault(); resetView(); return; }
      if (code === "a") { e.preventDefault(); var last = W.rows[W.rows.length - 1]; if (last) addAlert(W.lastPx || last.close, last.time); return; }
      return;
    }
    if (k === "/") { e.preventDefault(); indicatorDialog(); return; }
    if (k === "?") { e.preventDefault(); shortcuts(); return; }
    if (k === "F" && e.shiftKey) { e.preventDefault(); toggleFull(); return; }
    if (k === "ArrowLeft") { e.preventDefault(); scrollBars(-1); return; }
    if (k === "ArrowRight") { e.preventDefault(); scrollBars(1); return; }
    if (k === "+" || k === "=") { zoom(0.8); return; }
    if (k === "-") { zoom(1.25); return; }
    /* The single letters the earlier workspace answered to, kept. */
    if (low === "t") pickTool("trend");
    else if (low === "h") pickTool("hline");
    else if (low === "f") pickTool("fib");
    else if (low === "r") pickTool("ruler");
    else if (low === "v") { W.sel = null; inspector(); setMode("pan"); }
  }

  /* ── the public face ─────────────────────────────────────────────────── */

  var WS = {
    bind: bind,
    open: function (sym) {
      if (sym) { loadData(sym, null); return; }
      if (!W.sym) {
        var seed = ($("tk") && $("tk").value.trim().toUpperCase()) || sget("altaha.charts.v2.last", null) || "RELIANCE";
        loadData(seed, null);
      } else if (W.chart) {
        W.chart.applyOptions({ width: box.clientWidth, height: box.clientHeight });
        render();
      }
    },
    close: function () { stopLive(); if (root && root.classList.contains("cw-max")) toggleFull(false); },
    sym: function () { return W.sym; },
    /* For tests and for anyone driving the chart from code. */
    state: function () {
      return { sym: W.sym, tf: L.tf, type: L.type, bars: W.disp.length, drawings: W.drawings.length,
               studies: L.studies.map(function (s) { return s.id; }), panes: W.panes.length, replay: !!W.replay,
               mode: W.mode, tool: W.tool, full: isFull(), compares: W.cmp.map(function (c) { return c.sym; }) };
    },
    drawings: function () { return clone(W.drawings); },
    /* For tests: what the watchdog would say now, and a forced rebuild. */
    health: function () { try { return blankReason(); } catch (e) { return "check failed"; } },
    restore: function () { restoreChart(); },
    tools: function () { return Object.keys(T); }
  };
  window.AltahaCharts = WS;

  /* ══════════════════════════════════════════════════════════════════════
     MOUNTING
     ══════════════════════════════════════════════════════════════════════ */

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
    WS.open();
  }
  function hideCharts() {
    var v = $("view-charts");
    if (v) v.style.display = "none";
    var t = $("tab-charts");
    if (t) { t.classList.remove("active"); t.setAttribute("aria-selected", "false"); }
    WS.close();
  }

  function mount() {
    var nav = document.querySelector(".tabs");
    var main = document.querySelector("main.wrap");
    if (!main) return;

    var view = document.createElement("div");
    view.id = "view-charts";
    view.style.display = "none";
    view.innerHTML = viewHTML();
    var anchor = $("view-live") || $("view-ideas") || main.firstElementChild;
    main.insertBefore(view, anchor ? anchor.nextSibling : null);

    if (nav) {
      var btn = document.createElement("button");
      btn.className = "tab"; btn.id = "tab-charts"; btn.type = "button";
      btn.setAttribute("role", "tab"); btn.setAttribute("aria-selected", "false");
      btn.textContent = "Charts";
      var after = $("tab-live");
      if (after && after.parentNode === nav) nav.insertBefore(btn, after.nextSibling);
      else nav.appendChild(btn);
      btn.addEventListener("click", showCharts);
      nav.addEventListener("click", function (e) {
        var b = e.target.closest("button");
        if (b && b !== btn) hideCharts();
      }, true);
      var mm = $("moreMenu");
      if (mm) mm.addEventListener("click", hideCharts, true);
      if (typeof refreshSegsSoon === "function") { try { refreshSegsSoon(); } catch (e) {} }
    }

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
      b.addEventListener("click", function () { showCharts(); window.scrollTo({ top: 0, behavior: "smooth" }); });
      var live = inner.querySelector("[data-proxy='tab-live']");
      if (live) inner.insertBefore(b, live.nextSibling); else inner.appendChild(b);
      inner.querySelectorAll("button").forEach(function (x) {
        if (x.dataset.proxy !== "tab-charts") x.addEventListener("click", hideCharts);
      });
    }, 120);

    WS.bind();

    var q = null;
    try { q = new URLSearchParams(location.search).get("charts"); } catch (e) {}
    if (q != null) {
      document.body.classList.add("chartsonly");
      showCharts();
      WS.open((q || "RELIANCE").trim().toUpperCase());
    }

    var fc = $("fullchartbtn");
    if (fc) {
      var cl = fc.cloneNode(true);
      fc.parentNode.replaceChild(cl, fc);
      cl.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var s = ($("tk") && $("tk").value.trim().toUpperCase()) || WS.sym();
        showCharts();
        if (s) WS.open(s);
      });
    }
  }

  function selfCheck() {
    var view = $("view-charts"), tab = $("tab-charts");
    if (view && tab) return;
    if (!view) { console.error("[altaha-charts] view-charts was never created; 'main.wrap' is missing."); return; }
    var nav = document.querySelector(".tabs");
    if (!nav) return;
    var b = document.createElement("button");
    b.className = "tab"; b.id = "tab-charts"; b.type = "button";
    b.setAttribute("role", "tab"); b.setAttribute("aria-selected", "false");
    b.textContent = "Charts";
    nav.appendChild(b);
    b.addEventListener("click", showCharts);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { mount(); setTimeout(selfCheck, 400); });
  } else { mount(); setTimeout(selfCheck, 400); }
})();
