/* Altaha — keep S/R lines, hide the price-axis pills they draw on top of the numbers.
   Also move Tick to the end of the timeframe bar so daily stays the default. */
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

  function boot() {
    wrapChart();
    moveTick("tfbar");
    moveTick("fctfbar");
  }

  wrapChart();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
  setTimeout(boot, 400);
  setTimeout(boot, 1200);
})();
