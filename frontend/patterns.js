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

  var state = { sym: null, range: "1D", busy: false };

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
    "</div>";
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
        el.innerHTML = '<div class="patload">' + esc(d.message || "Not enough history.") + "</div>";
        return;
      }
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

  function currentSymbol() {
    var i = document.getElementById("cinput") || document.getElementById("fcinput");
    if (i && i.value.trim()) return i.value.trim().toUpperCase();
    try {
      var q = new URLSearchParams(location.search);
      return (q.get("charts") || q.get("chart") || "").toUpperCase() || null;
    } catch (e) { return null; }
  }

  function currentRange() {
    var on = document.querySelector("#ctfbar .tf.active, #fctfbar .tf.active");
    return (on && on.dataset && on.dataset.r) || "1D";
  }

  function refresh() {
    var s = currentSymbol();
    if (s) load(s, currentRange());
  }

  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest(".tf[data-r]")) { setTimeout(refresh, 600); return; }
    if (t.closest("#cgo, #fcgo")) { setTimeout(refresh, 900); return; }
  }, true);

  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter") return;
    var id = ev.target && ev.target.id;
    if (id === "cinput" || id === "fcinput") setTimeout(refresh, 900);
  }, true);

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
  window.AltahaPatterns = { refresh: refresh, load: load };
})();
