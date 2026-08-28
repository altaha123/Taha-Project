/* Altaha Screener — full drawing chart plus the label/Tick fix. */
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

  function wrapChart() {
    var L = window.LightweightCharts;
    if (!L || typeof L.createChart !== "function" || L.__altahaLabelPatch) return;
    L.__altahaLabelPatch = 1;
    var orig = L.createChart;
    L.createChart = function () {
      var chart = orig.apply(this, arguments);
      ["addCandlestickSeries", "addLineSeries", "addAreaSeries", "addBarSeries", "addHistogramSeries"].forEach(function (name) {
        if (typeof chart[name] !== "function") return;
        var add = chart[name].bind(chart);
        chart[name] = function () {
          var series = add.apply(chart, arguments);
          if (series && typeof series.createPriceLine === "function") {
            var make = series.createPriceLine.bind(series);
            series.createPriceLine = function (opts) {
              opts = Object.assign({}, opts || {}, { axisLabelVisible: false });
              return make(opts);
            };
          }
          return series;
        };
      });
      return chart;
    };
  }

  function bootPatch() {
    wrapChart();
    moveTick("tfbar");
    moveTick("fctfbar");
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
      screener.tabs.push({
        id: "charts",
        label: "Charts",
        hint: "Drawings, Fibonacci, RSI, MACD"
      });
    }
    if (typeof nav.go === "function") {
      var onScreener = document.querySelector('.navmain-btn.on[data-section="screener"]');
      if (onScreener) nav.go("screener", "screener", false);
    }
  }

  wrapChart();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootPatch);
  } else {
    bootPatch();
  }
  setTimeout(bootPatch, 400);
  setTimeout(bootPatch, 1200);

  var N = 15;
  var i = 0;
  function next() {
    if (i >= N) {
      var src = (window.__ALTAHA_CHARTS_PARTS || []).join("");
      window.__ALTAHA_CHARTS_PARTS = null;
      try { (0, eval)(src); } catch (e) { console.error("Altaha chart failed to load", e); }
      showChartsInMenu();
      setTimeout(showChartsInMenu, 400);
      setTimeout(showChartsInMenu, 1200);
      return;
    }
    i += 1;
    var s = document.createElement("script");
    var n = i < 10 ? "0" + i : String(i);
    s.src = "charts.p" + n + ".js";
    s.onload = next;
    s.onerror = function () { console.error("Missing chart piece " + n); next(); };
    document.head.appendChild(s);
  }
  next();
})();
