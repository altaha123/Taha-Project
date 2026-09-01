/* ============================================================================
   Altaha — Chart patterns panel

   Renders /patterns beneath the charting workspace: the shapes found on the
   current symbol and timeframe, what confirms or kills each one, and how often
   the same shape resolved in this stock's own history.

   The panel is built around one editorial rule. A pattern name on its own is
   an assertion, and assertions are what this project exists not to make. So
   nothing is shown without the number behind it — every shape ships its
   checks, its trigger, its invalidation, and either a base rate or an explicit
   statement that the sample is too small to quote one. Where the forward
   indicators disagree with the shape, that disagreement is printed as
   prominently as the shape itself.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_PATTERNS__) return;
  window.__ALTAHA_PATTERNS__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function rupee(v) {
    return v == null ? "—" : "₹" + Number(v).toLocaleString("en-IN",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pct(v, dp) {
    if (v == null) return "—";
    return (v > 0 ? "+" : "") + Number(v).toFixed(dp == null ? 2 : dp) + "%";
  }

  var state = { sym: null, range: "1D", busy: false, data: null };

  /* ---- the panel ------------------------------------------------------- */

  function host() {
    var view = document.getElementById("view-charts");
    if (!view) return null;
    var el = document.getElementById("patpanel");
    if (el) return el;
    el = document.createElement("div");
    el.id = "patpanel";
    el.className = "patpanel";
    view.appendChild(el);
    return el;
  }

  /* The workspace is height:calc(100vh - 168px), so anything appended after it
     starts a full screen below the fold — findable only by someone who already
     knew to scroll. This strip goes ABOVE the chart, names what was found in
     one line, and scrolls to the detail. */
  function summary(d) {
    var view = document.getElementById("view-charts");
    if (!view) return;
    var bar = document.getElementById("patbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "patbar";
      bar.className = "patbar";
      var cw = document.getElementById("cw");
      if (cw && cw.parentNode === view) view.insertBefore(bar, cw);
      else view.insertBefore(bar, view.firstChild);
      bar.addEventListener("click", function () {
        var p = document.getElementById("patpanel");
        if (p) p.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    if (!d || !d.available) { bar.innerHTML = ""; bar.hidden = true; return; }
    bar.hidden = false;
    if (!d.count) {
      bar.innerHTML = '<b>No textbook pattern</b><span>on the ' + esc(d.timeframe) +
        " chart right now — read why below</span>";
      bar.className = "patbar quiet";
      return;
    }
    bar.className = "patbar";
    bar.innerHTML = "<b>" + d.count + " pattern" + (d.count > 1 ? "s" : "") + "</b>" +
      d.patterns.slice(0, 3).map(function (p) {
        return '<i class="' + esc(p.direction) + '">' + esc(p.name) +
               " <em>" + esc(p.status) + "</em></i>";
      }).join("") +
      "<span>tap for the full reading &darr;</span>";
  }

  function checksHTML(checks) {
    return '<ul class="patchecks">' + (checks || []).map(function (c) {
      return '<li class="' + (c.ok ? "ok" : "no") + '"><b>' + (c.ok ? "✓" : "✕") +
             "</b> " + esc(c.check) + " <span>" + esc(c.detail) + "</span></li>";
    }).join("") + "</ul>";
  }

  function baseRateHTML(br) {
    if (!br) return "";
    if (!br.reliable) {
      return '<div class="patrate thin">' + esc(br.note) + "</div>";
    }
    var rows = Object.keys(br.horizons).sort(function (a, b) { return a - b; })
      .map(function (k) {
        var h = br.horizons[k];
        return "<tr><td>" + h.sessions + " sessions</td>" +
               "<td><b>" + h.resolved_in_direction_pct + "%</b></td>" +
               '<td class="' + (h.median_return_pct > 0 ? "pos" : h.median_return_pct < 0 ? "neg" : "") +
                 '">' + pct(h.median_return_pct) + "</td>" +
               '<td class="neg">' + pct(h.worst_pct) + "</td>" +
               "<td>" + h.n + "</td></tr>";
      }).join("");
    return '<div class="patrate"><h5>What happened the last ' + br.instances +
      " times this shape appeared here</h5>" +
      '<table class="pattable"><thead><tr><th>after</th><th>resolved in direction</th>' +
      "<th>median</th><th>worst</th><th>n</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      '<p class="patnote">' + esc(br.note) + "</p></div>";
  }

  function confluenceHTML(cf) {
    if (!cf) return "";
    var cls = /argue/i.test(cf.verdict) ? "no" : /line up/i.test(cf.verdict) ? "ok" : "mix";
    var bits = [];
    if (cf.agrees && cf.agrees.length) bits.push("For: " + cf.agrees.map(esc).join("; "));
    if (cf.argues && cf.argues.length) bits.push("Against: " + cf.argues.map(esc).join("; "));
    return '<div class="patconf ' + cls + '"><b>' + esc(cf.verdict) + "</b>" +
           (bits.length ? "<span>" + bits.join(" · ") + "</span>" : "") + "</div>";
  }

  function patternHTML(p) {
    return '<div class="patcard ' + esc(p.direction) + '">' +
      '<div class="pathead"><span class="patname">' + esc(p.name) +
        '<i class="patstatus ' + esc(p.status) + '">' + esc(p.status) + "</i></span>" +
        '<span class="patconf-n">' + p.confidence + '<small>shape match</small></span></div>' +

      '<div class="patlevels">' +
        '<div><b>Confirms above</b><span>' + rupee(p.trigger) +
          (p.distance_to_trigger_pct != null
            ? ' <i>' + pct(p.distance_to_trigger_pct, 1) + " away</i>" : "") + "</span></div>" +
        '<div><b>Invalidated at</b><span>' + rupee(p.invalidation) + "</span></div>" +
        '<div><b>Measured move</b><span>' + rupee(p.target) + "</span></div>" +
      "</div>" +

      '<p class="patwhy">' + esc(p.note) + "</p>" +
      confluenceHTML(p.confluence) +
      checksHTML(p.checks) +
      baseRateHTML(p.base_rate) +
      '<div class="patpoints">' + (p.points || []).map(function (pt) {
        return "<span>" + esc(pt.label) + " · " + esc(pt.date) + " · " + rupee(pt.price) + "</span>";
      }).join("") + "</div>" +
      shareRow(p) +
    "</div>";
  }

  /* Every pattern the panel prints can be published as the chart it was found
     on. The card carries the shape and the candles; the trigger, the
     invalidation and the measured move printed above stay here, beside the
     base rate and the disclaimer that qualify them. */
  function shareAttr(o) {
    return 'data-share="' + JSON.stringify(o)
      .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;") + '"';
  }

  function shareRow(p) {
    var sym = state.sym || currentSymbol();
    if (!sym) return "";
    return '<div class="patshare"><button class="shbtn" type="button" ' +
      shareAttr({ kind: "chart", ticker: sym, range: state.range,
                  pattern: { name: p.name, status: p.status, confidence: p.confidence } }) +
      ">Share this chart</button></div>";
  }

  function forwardHTML(f) {
    if (!f || !f.available) return "";
    var rows = [];
    if (f.rsi && f.rsi.prices) {
      var ps = Object.keys(f.rsi.prices).sort(function (a, b) { return a - b; })
        .map(function (k) { return "RSI " + k + " at " + rupee(f.rsi.prices[k]); });
      rows.push(["RSI now " + (f.rsi.current == null ? "—" : f.rsi.current.toFixed(1)),
                 ps.join(" · ")]);
    }
    if (f.supertrend) {
      /* The rule without the number is useless: "a close above the band flips
         it" is only actionable once you know what the band is. */
      rows.push(["Supertrend " + esc(f.supertrend.direction),
                 esc(f.supertrend.note) + (f.supertrend.flip_price != null
                   ? "  The band is at " + rupee(f.supertrend.flip_price) + "." : "")]);
    }
    if (f.ema_cross_20_50) rows.push(["20 / 50 EMA", esc(f.ema_cross_20_50.note)]);
    if (f.ema_cross_50_200) rows.push(["50 / 200 EMA", esc(f.ema_cross_50_200.note)]);
    if (f.macd) rows.push(["MACD", esc(f.macd.note)]);
    if (f.bollinger) rows.push(["Bollinger " + esc(f.bollinger.state), esc(f.bollinger.note)]);
    if (f.expected_range && f.expected_range.bands) {
      var b = f.expected_range.bands["5"] || f.expected_range.bands[5];
      if (b) rows.push(["Typical 5-session range",
                        rupee(b.low) + " – " + rupee(b.high) + " (±" + b.pct + "%)"]);
    }
    return '<div class="patfwd"><h4>What has to happen next</h4>' +
      '<p class="patnote">' + esc(f.method) + "</p>" +
      rows.map(function (r) {
        return '<div class="patfwdrow"><b>' + r[0] + "</b><span>" + r[1] + "</span></div>";
      }).join("") + "</div>";
  }

  /* ======================================================================
     The overlay — the shape drawn ON the chart

     The panel below the chart has always described the pattern in words and
     numbers. It was never drawn where a reader looks, which made it easy to
     miss entirely: "cup and handle, confirmed" means very little until you can
     see the cup.

     Nothing here reaches into the charting bundle. charts.js publishes the
     chart handle and the candlestick series through window.AltahaChartTap, and
     everything below is computed from those two public methods —
     priceToCoordinate for the y axis, logicalToCoordinate for the x. The
     bundle does not know this exists and does not have to.

     WHY logicalToCoordinate AND NOT timeToCoordinate
     timeToCoordinate answers null for any timestamp that is not exactly a
     point on the scale. Pattern pivots and chart candles come from the same
     history so they should always match — but "should always match" is how
     every seam in this project has broken so far. Matching the pivot to its
     nearest candle and asking for that candle's logical coordinate is right
     when the timestamps agree and still right, to within one bar, when a
     timezone or a resample has moved them.

     The overlay is off by default and remembers its own state. A chart covered
     in annotations you did not ask for is worse than a plain one.
     ====================================================================== */

  var overlay = (function () {
    var KEY = "altaha.patterns.overlay";
    var cv = null, ctx = null, chip = null, timer = null, raf = null, sig = "";
    var on = (function () {
      try { return localStorage.getItem(KEY) !== "0"; } catch (e) { return true; }
    })();

    function tok(name, dflt) {
      try {
        var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || dflt;
      } catch (e) { return dflt; }
    }

    function tap() {
      var T = window.AltahaChartTap;
      return (T && T.ready()) ? T.get() : null;
    }

    /* The candle nearest a pivot's timestamp, as a logical index. */
    function indexAt(times, t) {
      if (!times.length || t == null) return null;
      var lo = 0, hi = times.length - 1;
      if (t <= times[0]) return 0;
      if (t >= times[hi]) return hi;
      while (hi - lo > 1) {
        var mid = (lo + hi) >> 1;
        if (times[mid] <= t) lo = mid; else hi = mid;
      }
      return (t - times[lo] <= times[hi] - t) ? lo : hi;
    }

    function host() { return document.getElementById("cw-price"); }

    function ensure() {
      var box = host();
      if (!box) return false;
      if (!cv || cv.parentNode !== box) {
        cv = document.createElement("canvas");
        cv.id = "cw-pat-ov";
        cv.className = "cw-patov";
        /* Below the drawing canvas (z-index 6) so a user's own trendline is
           always on top of ours, and click-through in every case. */
        cv.style.cssText = "position:absolute;inset:0;z-index:5;pointer-events:none";
        box.appendChild(cv);
        ctx = cv.getContext("2d");
      }
      return !!ctx;
    }

    function size() {
      var box = host();
      if (!box || !cv) return false;
      var dpr = window.devicePixelRatio || 1;
      var w = box.clientWidth, h = box.clientHeight;
      if (!w || !h) return false;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
        cv.style.width = w + "px";
        cv.style.height = h + "px";
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      return true;
    }

    /* A joined polyline reads as the shape for the shapes that ARE a line —
       a cup, a double bottom, shoulders. A triangle's pivots alternate between
       two trendlines, and joining them in time order draws a zigzag that looks
       nothing like a triangle. Those get their two fitted lines instead. */
    function isPolyline(name) {
      var n = String(name || "").toLowerCase();
      return !/triangle|rectangle|channel|wedge|flag/.test(n);
    }

    function fit(pts) {
      var n = pts.length;
      if (n < 2) return null;
      var mx = 0, my = 0, i;
      for (i = 0; i < n; i++) { mx += pts[i][0]; my += pts[i][1]; }
      mx /= n; my /= n;
      var num = 0, den = 0;
      for (i = 0; i < n; i++) {
        num += (pts[i][0] - mx) * (pts[i][1] - my);
        den += (pts[i][0] - mx) * (pts[i][0] - mx);
      }
      if (!den) return null;
      var m = num / den;
      return [m, my - m * mx];
    }

    function colourFor(direction) {
      if (direction === "bullish") return tok("--pass", "#1F5D45");
      if (direction === "bearish") return tok("--fail", "#8E2F2A");
      return tok("--gold", "#B08D2E");
    }

    function dash(c, a, b, colour, width) {
      c.save();
      c.setLineDash([7, 6]);
      c.strokeStyle = colour;
      c.lineWidth = width || 1.5;
      c.beginPath();
      c.moveTo(a[0], a[1]);
      c.lineTo(b[0], b[1]);
      c.stroke();
      c.restore();
    }

    function label(c, text, x, y, colour, right) {
      c.save();
      c.font = "600 10px 'IBM Plex Mono', monospace";
      var w = c.measureText(text).width;
      if (right) x -= w;
      c.fillStyle = tok("--paper", "#FBFAF7");
      c.globalAlpha = 0.88;
      c.fillRect(x - 3, y - 11, w + 6, 14);
      c.globalAlpha = 1;
      c.fillStyle = colour;
      c.fillText(text, x, y);
      c.restore();
    }

    function paint() {
      if (!on) { if (cv && ctx) size(); return; }
      if (!ensure() || !size()) return;
      var d = state.data;
      var T = tap();
      if (!d || !d.available || !d.patterns || !d.patterns.length || !T) return;

      var ts = T.chart.timeScale();
      var box = host();
      var wide = box.clientWidth;

      /* Only the two strongest shapes. Every detected pattern at once turns
         the chart into a scribble, and the panel below has the rest. */
      d.patterns.slice(0, 2).forEach(function (p, k) {
        var colour = colourFor(p.direction);
        var pts = [];
        (p.points || []).forEach(function (pt) {
          if (pt.price == null) return;
          var i = pt.t != null ? indexAt(T.times, pt.t) : null;
          if (i == null) return;
          var x = ts.logicalToCoordinate(i);
          var y = T.series.priceToCoordinate(pt.price);
          if (x == null || y == null) return;
          pts.push([x, y, pt.label || "", i]);
        });
        if (!pts.length) return;

        ctx.save();
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.globalAlpha = k ? 0.55 : 1;

        if (isPolyline(p.name)) {
          if (pts.length > 1) {
            ctx.strokeStyle = colour;
            ctx.lineWidth = 2.2;
            ctx.beginPath();
            ctx.moveTo(pts[0][0], pts[0][1]);
            for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
            ctx.stroke();
          }
        } else {
          var mid = pts.reduce(function (a, q) { return a + q[1]; }, 0) / pts.length;
          /* y grows downward, so "above the midline" is the SMALLER y. */
          [pts.filter(function (q) { return q[1] <= mid; }),
           pts.filter(function (q) { return q[1] > mid; })].forEach(function (group) {
            if (group.length < 2) return;
            var f = fit(group.map(function (q) { return [q[0], q[1]]; }));
            if (!f) return;
            var xs = group.map(function (q) { return q[0]; });
            var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
            /* Extended a little to the right, dashed, because a trendline
               projected forward is an extrapolation and should not be drawn
               as though it were data. */
            var x2 = Math.min(wide - 4, x1 + (x1 - x0) * 0.35);
            ctx.strokeStyle = colour;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(x0, f[0] * x0 + f[1]);
            ctx.lineTo(x1, f[0] * x1 + f[1]);
            ctx.stroke();
            dash(ctx, [x1, f[0] * x1 + f[1]], [x2, f[0] * x2 + f[1]], colour, 2);
          });
        }

        pts.forEach(function (q) {
          ctx.beginPath();
          ctx.arc(q[0], q[1], 4.5, 0, Math.PI * 2);
          ctx.fillStyle = tok("--paper", "#FBFAF7");
          ctx.fill();
          ctx.lineWidth = 2.4;
          ctx.strokeStyle = colour;
          ctx.stroke();
          if (q[2] && !k) label(ctx, q[2], q[0] + 7, q[1] - 7, colour);
        });

        /* The trigger and the invalidation, as levels. These are on the site,
           beside the base rate and the disclaimer that qualify them — unlike
           the share card, which carries neither and so carries no levels. */
        if (!k) {
          [[p.trigger, "confirms " + (p.direction === "bearish" ? "below" : "above")],
           [p.invalidation, "invalid at"]].forEach(function (lv) {
            if (lv[0] == null) return;
            var y = T.series.priceToCoordinate(lv[0]);
            if (y == null) return;
            dash(ctx, [0, y], [wide, y], colour, 1.4);
            /* Right-aligned. The workspace's own OHLC legend sits at the top
               left, and a level near the top of the range put its label
               underneath that legend — drawn, invisible, indistinguishable
               from not drawn at all. */
            label(ctx, lv[1] + " " + Number(lv[0]).toFixed(2), wide - 10, y - 5,
                  colour, true);
          });
        }
        ctx.restore();
      });

      /* Whose shape this is, so a screenshot is self-describing. Lifted clear
         of the time axis: the axis is part of the chart's own canvas and
         drawing the caption over it made both unreadable. */
      var axis = 26;
      try { axis = ts.height() || 26; } catch (e) {}
      var top = d.patterns[0];
      label(ctx, top.name + " · " + top.status + " · " + top.confidence + " shape match",
            10, box.clientHeight - axis - 10, colourFor(top.direction));
    }

    function draw() {
      if (raf) return;
      raf = requestAnimationFrame(function () { raf = null; try { paint(); } catch (e) {} });
    }

    /* A vertical drag on the price scale fires no event the chart exposes, so
       a cheap signature poll catches it — the same trick the charting bundle
       uses on itself for exactly the same reason. */
    function signature() {
      var T = tap();
      var box = host();
      if (!T || !box) return "";
      var r = null;
      try { r = T.chart.timeScale().getVisibleLogicalRange(); } catch (e) {}
      var y = null;
      try {
        var last = T.rows[T.rows.length - 1];
        if (last) y = T.series.priceToCoordinate(last.close);
      } catch (e) {}
      return (r ? r.from.toFixed(2) + "," + r.to.toFixed(2) : "") + "|" + y +
             "|" + box.clientWidth + "x" + box.clientHeight + "|" + (state.data ? 1 : 0);
    }

    function tick() {
      var view = document.getElementById("view-charts");
      if (!view || getComputedStyle(view).display === "none") return;
      if (!on) return;
      var sg = signature();
      if (sg === sig) return;
      sig = sg;
      draw();
    }

    function set(next) {
      on = !!next;
      try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) {}
      if (chip) {
        chip.classList.toggle("on", on);
        chip.setAttribute("aria-pressed", on ? "true" : "false");
      }
      sig = "";
      if (!on && ctx) { ensure(); size(); }
      else draw();
    }

    /* The toggle, and the share button beside it. Both are appended to the
       workspace's own footer so they sit with the indicator chips rather than
       in a second bar of their own. The bundle's footer handler filters on
       button[data-i], so neither of these reaches it. */
    function mount() {
      var foot = document.querySelector("#view-charts .cw-foot");
      if (!foot) return;
      if (!chip || chip.parentNode !== foot) {
        chip = document.createElement("button");
        chip.type = "button";
        chip.className = "cw-chip" + (on ? " on" : "");
        chip.setAttribute("data-pat", "1");
        chip.setAttribute("aria-pressed", on ? "true" : "false");
        chip.title = "Draw the detected pattern on the chart";
        chip.textContent = "Patterns";
        chip.addEventListener("click", function (ev) {
          ev.stopPropagation();
          set(!on);
        });
        var note = document.getElementById("cw-note");
        foot.insertBefore(chip, note || null);
      }
      if (!document.getElementById("cw-share")) {
        var sh = document.createElement("button");
        sh.type = "button";
        sh.id = "cw-share";
        sh.className = "cw-chip";
        sh.setAttribute("data-share-chart", "1");
        sh.textContent = "Share chart";
        sh.title = "Post this chart, with the shape drawn on it";
        sh.addEventListener("click", function (ev) {
          ev.stopPropagation();
          if (!window.AltahaShare) return;
          var d = state.data;
          var top = (d && d.patterns && d.patterns[0]) || null;
          window.AltahaShare.open({
            kind: "chart",
            ticker: currentSymbol() || state.sym,
            range: currentRange(),
            pattern: top ? { name: top.name, status: top.status, confidence: top.confidence } : null
          });
        });
        var note2 = document.getElementById("cw-note");
        foot.insertBefore(sh, note2 || null);
      }
    }

    function boot() {
      mount();
      if (!timer) timer = setInterval(tick, 140);
      if (window.AltahaChartTap && window.AltahaChartTap.watch) {
        window.AltahaChartTap.watch(function () { sig = ""; draw(); });
      }
      window.addEventListener("resize", function () { sig = ""; draw(); });
    }

    /* The workspace mounts asynchronously, and on a slow connection so does
       the charting library. Retry until the footer exists rather than
       assuming a timing that holds on a fast machine. */
    (function wait(n) {
      if (document.querySelector("#view-charts .cw-foot")) { boot(); return; }
      if (n > 60) return;
      setTimeout(function () { wait(n + 1); }, 400);
    })(0);

    return { draw: draw, set: set, isOn: function () { return on; } };
  })();

  /* ---- load ------------------------------------------------------------ */

  async function load(sym, range) {
    var el = host();
    if (!el || !sym) return;
    if (state.busy) return;
    state.busy = true;
    state.sym = sym;
    state.range = range || state.range;

    el.innerHTML = '<div class="patload">Reading the chart for ' + esc(sym) +
                   " on the " + esc(state.range) + " timeframe…</div>";
    try {
      var url = API + "/patterns?ticker=" + encodeURIComponent(sym) +
                "&range=" + encodeURIComponent(state.range);
      var r = await fetch(url);
      var d = await r.json();
      if (!r.ok) {
        el.innerHTML = '<div class="patload">' + esc(d.detail || "Couldn't read patterns.") + "</div>";
        return;
      }
      if (!d.available) {
        summary(null);
        state.data = null;
        overlay.draw();
        el.innerHTML = '<div class="patload">' + esc(d.message || "Not enough history.") + "</div>";
        return;
      }
      summary(d);
      state.data = d;
      overlay.draw();
      el.innerHTML =
        '<div class="pathdr"><h3>Patterns on the ' + esc(d.timeframe) + " chart</h3>" +
        "<span>" + esc(d.symbol) + " · " + esc(d.as_of) + " · last " + rupee(d.last_close) +
        " · ATR " + rupee(d.atr) + "</span></div>" +
        (d.count
          ? d.patterns.map(patternHTML).join("")
          : '<div class="patload">No textbook pattern on this timeframe right now. That is the ' +
            "usual answer — most stocks, most days, are not in one, and a detector that " +
            "always finds something has stopped detecting.</div>") +
        forwardHTML(d.forward) +
        '<p class="patdisc">' + esc(d.disclaimer) + "</p>";
    } catch (e) {
      el.innerHTML = '<div class="patload">Engine unreachable — it may be waking up.</div>';
    } finally {
      state.busy = false;
    }
  }

  /* ---- wiring ----------------------------------------------------------
     The chart workspace owns the symbol box and the timeframe bar, and it is
     built by an eval'd bundle this file must not reach into. Listening to the
     controls is enough, and it keeps the two independent. */

  /* BUGFIX: these selectors were written for the full-window chart page
     (?chart=SYMBOL), whose controls are #fcinput / #fctfbar. The Charts TAB
     builds a different workspace whose ids are all cw-* — #cw-in for the
     symbol, #cw-go for Load, #cw-tfs for the timeframes, with the active one
     carrying .on rather than .active.

     So on the tab itself currentSymbol() returned null, refresh() did nothing,
     and the panel was never populated. It only ever worked when the URL
     happened to carry ?charts=SYMBOL, which is exactly how it was tested. */
  function currentSymbol() {
    var i = document.getElementById("cw-in") || document.getElementById("fcinput");
    if (i && i.value && i.value.trim()) return i.value.trim().toUpperCase();
    try {
      var q = new URLSearchParams(location.search);
      return (q.get("charts") || q.get("chart") || "").toUpperCase() || null;
    } catch (e) { return null; }
  }

  function currentRange() {
    var on = document.querySelector("#cw-tfs button.on, #fctfbar .tf.active");
    return (on && on.dataset && on.dataset.r) || "1D";
  }

  /* Rather than guessing every control that might change the symbol, watch
     what the controls produce. One cheap comparison a second is immune to the
     workspace being rebuilt, renamed, or driven from code we do not own —
     which is precisely how the selector bug above went unnoticed. */
  var lastKey = null;
  function poll() {
    var view = document.getElementById("view-charts");
    if (!view || getComputedStyle(view).display === "none") return;
    var s = currentSymbol();
    if (!s) return;
    var key = s + "|" + currentRange();
    if (key === lastKey) return;
    lastKey = key;
    load(s, currentRange());
  }

  function refresh() { lastKey = null; poll(); }
  setInterval(poll, 1000);

  /* First paint once the workspace has mounted and loaded its own data. */
  function boot(tries) {
    if (!document.getElementById("view-charts")) {
      if ((tries || 0) < 30) return setTimeout(function () { boot((tries || 0) + 1); }, 400);
      return;
    }
    refresh();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 1200); });
  } else {
    setTimeout(boot, 1200);
  }
  window.AltahaPatterns = {
    refresh: refresh, load: load,
    data: function () { return state.data; },
    overlay: overlay
  };
})();
