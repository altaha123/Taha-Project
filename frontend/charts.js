/* Altaha Screener: loads the Charts workspace, and wraps the charting library. */
(function () {
  "use strict";

  function moveTick(barId) {
    var bar = document.getElementById(barId);
    if (!bar) return;
    var tick = bar.querySelector('[data-r="tick"]');
    var week = bar.querySelector('[data-r="1W"]');
    if (!tick || !week || !week.parentNode) return;
    if (tick.previousElementSibling === week) return;
    week.parentNode.insertBefore(tick, week.nextSibling);
  }

  /* Hide the price-line labels that otherwise sit on top of the axis numbers.
     Done by wrapping createChart, which is harder than it looks:

     BUGFIX — this used to write two properties straight onto
     window.LightweightCharts: a `__altahaLabelPatch` marker and a replacement
     `createChart`. The v4 standalone build FREEZES its namespace object, so
     both assignments throw a TypeError under "use strict" — which this file
     is. And wrapChart() is called at the top level of this IIFE, above the
     piece loader, so the throw aborted the entire module: the fifteen chart
     pieces were never fetched, the drawing workspace never mounted, and the
     Charts tab opened to nothing.

     The cruel part is that it only failed when the charting library loaded
     SUCCESSFULLY. If the CDN was slow and the global was still undefined,
     wrapChart returned early at the `!L` guard, the module survived, and the
     tab worked in its degraded form — so the failure looked intermittent and
     unrelated to the library.

     The marker is now a variable in this closure rather than a property on
     someone else's frozen object, and a frozen namespace is replaced by a
     shallow copy on the global (which IS writable) instead of mutated in
     place. Nothing in here is allowed to throw: a charting library that
     changes shape again must cost us the label tweak, never the chart. */
  var labelPatchDone = false;

  /* ---- the tap --------------------------------------------------------
     The charting workspace is an eval'd bundle. Its chart handle, its
     candlestick series and its rows all live in a closure inside that bundle
     and nothing outside can reach them — which is fine until you want to draw
     a detected pattern ON the chart rather than describe it underneath.

     Rather than reaching into someone else's closure, or worse, editing a
     bundle that is shipped as fifteen concatenated string literals, the wrap
     that was already here for the price-line labels does the work. It sees
     every createChart call and every addCandlestickSeries call, so it can
     hand out the handle it is already holding, and patching setData gives the
     rows for free.

     Deliberately read-only: this publishes handles, it does not drive the
     chart. If the bundle changes shape the overlay stops drawing and nothing
     else in the tab notices. */
  var tap = { chart: null, series: null, container: null, rows: [], times: [] };
  var tapWatchers = [];

  function announce() {
    for (var i = 0; i < tapWatchers.length; i++) {
      try { tapWatchers[i](tap); } catch (e) {}
    }
  }

  function tapCandles(chart, container, series) {
    if (!series) return;
    tap.chart = chart;
    tap.series = series;
    tap.container = (container && container.nodeType === 1) ? container : null;
    tap.rows = [];
    tap.times = [];
    if (typeof series.setData === "function") {
      var set = series.setData.bind(series);
      series.setData = function (data) {
        var out = set(data);
        try {
          tap.rows = Array.isArray(data) ? data : [];
          tap.times = tap.rows.map(function (r) { return r && r.time; });
        } catch (e) { tap.rows = []; tap.times = []; }
        announce();
        return out;
      };
    }
    announce();
  }

  window.AltahaChartTap = {
    get: function () { return tap; },
    /* The workspace hands over its chart itself, whatever the chart type: a
       line or bar chart has no candlestick series for the wrap below to see. */
    publish: function (chart, series, container, rows) {
      tap.chart = chart; tap.series = series;
      tap.container = (container && container.nodeType === 1) ? container : null;
      tap.rows = Array.isArray(rows) ? rows : [];
      tap.times = tap.rows.map(function (r) { return r && r.time; });
      announce();
    },
    ready: function () { return !!(tap.chart && tap.series && tap.times.length); },
    /* Called on every setData and on first attach. A subscriber that throws
       must not take the others down with it, hence the try above. */
    watch: function (fn) {
      if (typeof fn !== "function") return;
      tapWatchers.push(fn);
      if (tap.chart) { try { fn(tap); } catch (e) {} }
    }
  };

  function wrapChart() {
    if (labelPatchDone) return;
    var L = window.LightweightCharts;
    if (!L || typeof L.createChart !== "function") return;

    var orig = L.createChart;
    function patchedCreateChart(container) {
      var chart = orig.apply(this, arguments);
      ["addCandlestickSeries", "addLineSeries", "addAreaSeries", "addBarSeries", "addHistogramSeries"].forEach(function (name) {
        if (typeof chart[name] !== "function") return;
        var add = chart[name].bind(chart);
        chart[name] = function () {
          var series = add.apply(this, arguments);
          if (series && typeof series.createPriceLine === "function") {
            var make = series.createPriceLine.bind(series);
            series.createPriceLine = function (opts) {
              opts = Object.assign({}, opts || {}, { axisLabelVisible: false });
              return make(opts);
            };
          }
          if (name === "addCandlestickSeries") tapCandles(chart, container, series);
          return series;
        };
      });
      return chart;
    }

    try {
      if (Object.isFrozen(L) || !Object.isExtensible(L)) {
        var copy = {};
        Object.getOwnPropertyNames(L).forEach(function (k) {
          try { copy[k] = L[k]; } catch (e) {}
        });
        copy.createChart = patchedCreateChart;
        window.LightweightCharts = copy;      // the global binding is writable
      } else {
        L.createChart = patchedCreateChart;
      }
    } catch (e) {
      if (window.console) console.warn("[altaha-charts] price-line label tweak skipped:", e.message);
    }
    labelPatchDone = true;                    // once, whatever happened
  }

  function bootPatch() {
    try { wrapChart(); } catch (e) {}
    try { moveTick("tfbar"); moveTick("fctfbar"); } catch (e) {}
    try { seedFromQuery(); } catch (e) {}
  }

  /* A shared chart link lands here.
     /share/chart/RELIANCE forwards a human to /?q=RELIANCE&go=charts&range=1D.
     The nav opens the tab; nothing was putting the symbol into the workspace,
     so the reader arrived at an empty chart with the symbol they came for
     sitting in the URL. Seeded through the workspace's own controls rather
     than its internals: type into the box and press Load, which is what a
     person would do. */
  function seedFromQuery() {
    var p;
    try { p = new URLSearchParams(location.search); } catch (e) { return; }
    if ((p.get("go") || "").toLowerCase() !== "charts") return;
    var sym = (p.get("q") || "").trim().toUpperCase().replace(/[^A-Z0-9&.\-]/g, "");
    if (!sym) return;
    var input = document.getElementById("cw-in");
    var load = document.getElementById("cw-go");
    if (!input || !load || input.dataset.seeded) return;
    input.dataset.seeded = "1";
    input.value = sym;
    /* Timeframe first, then Load. The timeframe button alone cannot fetch:
       it calls the workspace's loader with no symbol, which returns early
       while no symbol has been chosen. Pressing it only records the range. */
    var range = (p.get("range") || "").trim();
    if (range) {
      var tf = document.querySelector('#cw-tfs button[data-r="' + range.replace(/[^\w]/g, "") + '"]');
      if (tf) tf.click();
    }
    load.click();
  }

  function queryChartsSymbol() {
    try { return new URLSearchParams(location.search).get("charts"); }
    catch (e) { return null; }
  }

  function showChartsInMenu() {
    var nav = window.AltahaNav;
    if (!nav || !nav.sections) return;
    var screener = null;
    for (var i = 0; i < nav.sections.length; i++) {
      if (nav.sections[i].id === "screener") { screener = nav.sections[i]; break; }
    }
    if (!screener || !screener.tabs) return;
    var has = false;
    for (var j = 0; j < screener.tabs.length; j++) {
      if (screener.tabs[j].id === "charts") { has = true; break; }
    }
    if (!has) {
      screener.tabs.splice(1, 0, {
        id: "charts",
        label: "Charts",
        hint: "Drawings, Fibonacci, RSI, MACD"
      });
    }
    if (typeof nav.go !== "function") return;

    var q = queryChartsSymbol();
    var view = document.getElementById("view-charts");
    var chartsOpen = view && view.style.display !== "none";
    if (q != null || chartsOpen) {
      nav.go("screener", "charts", false);
      return;
    }

    var onScreener = document.querySelector('.navmain-btn.on[data-section="screener"]');
    if (!onScreener) return;
    var onSub = document.querySelector(".navsub-btn.on .navsub-lbl");
    var label = onSub ? onSub.textContent : "Analysis";
    var tab = "screener";
    if (label === "Charts") tab = "charts";
    else if (label === "Results") tab = "results";
    else if (label === "Filings") tab = "filings";
    nav.go("screener", tab, false);
  }

  /* Guarded: nothing above this line may stop the piece loader below it
     from running. That was the whole failure. */
  try { wrapChart(); } catch (e) {}
  /* The library can land at any time now; wrap it before anything draws. */
  window.addEventListener("altaha:chartlib", function () { try { wrapChart(); } catch (e) {} });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootPatch);
  } else {
    bootPatch();
  }
  setTimeout(bootPatch, 400);
  setTimeout(bootPatch, 1200);

  /* ---- the charting library ------------------------------------------
     index.html used to load it in the head, from unpkg, with a
     document.write fallback to jsdelivr: 160 KB from another site that every
     visit waited for before the first paint, chart or no chart, and a
     fallback that Chrome refuses outright on a slow connection. It is now
     fetched when a chart first needs it, by AltahaBoot.chartLib in
     index.html, which appends an ordinary script element and tries the
     second CDN if the first fails. This asks for it once the workspace is
     mounted, and if the library never arrives it says so on the page rather
     than leaving the reader to guess. Pages without that loader (and this
     file's own older behaviour) use the list below. */
  var CDNS = [
    "https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js",
    "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
  ];

  function haveLibrary() {
    var L = window.LightweightCharts;
    return !!(L && typeof L.createChart === "function");
  }

  function ensureLibrary(done) {
    if (haveLibrary()) { done(true); return; }
    /* index.html has one loader for it, shared with the chart on the
       analysis page, so the library is never fetched twice. */
    if (window.AltahaBoot && typeof window.AltahaBoot.chartLib === "function") {
      window.AltahaBoot.chartLib(done);
      return;
    }
    var k = 0;
    (function attempt() {
      if (haveLibrary()) { done(true); return; }
      if (k >= CDNS.length) { done(false); return; }
      var s = document.createElement("script");
      s.src = CDNS[k++];
      s.async = false;
      s.onload = function () { done(haveLibrary()); };
      s.onerror = attempt;
      document.head.appendChild(s);
    })();
  }

  function libraryMissingNotice() {
    var view = document.getElementById("view-charts");
    if (!view || document.getElementById("chartlibwarn")) return;
    var d = document.createElement("div");
    d.id = "chartlibwarn";
    d.className = "warnbox";
    d.style.cssText = "margin:14px 0";
    d.innerHTML = "<b>The charting library did not load.</b> Drawings and indicators " +
      "need it, so the chart is blank. This is a network problem, not a broken " +
      "symbol. It is fetched from a public CDN; reload once you have a steadier " +
      "connection.";
    view.insertBefore(d, view.firstChild);
  }

  /* The workspace is two ordinary scripts: the arithmetic, then the
     workspace that uses it. It used to be fifteen string fragments joined and
     eval'd, which no stack trace, linter or reader could make sense of. */
  var FILES = ["charts-math.js?v=20261121-tv", "charts-workspace.js?v=20261121-tv"];
  var i = 0;
  function next() {
    if (i >= FILES.length) {
      showChartsInMenu();
      setTimeout(showChartsInMenu, 400);
      setTimeout(showChartsInMenu, 1200);
      try { seedFromQuery(); } catch (e) {}
      // The workspace is mounted either way; the library decides whether a
      // chart can be drawn inside it.
      ensureLibrary(function (ok) {
        if (ok) { try { wrapChart(); } catch (e) {} }
        else { libraryMissingNotice(); setTimeout(libraryMissingNotice, 1500); }
      });
      return;
    }
    var s = document.createElement("script");
    var name = FILES[i++];
    s.src = name;
    s.onload = next;
    s.onerror = function () { console.error("[altaha-charts] missing " + name); next(); };
    document.head.appendChild(s);
  }
  next();
})();
