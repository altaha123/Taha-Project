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

  /* ── plumbing ──────────────────────────────────────────────────────────────────── */

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

  /* ── tools ───────────────────────────────────────────────────────────── */

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
