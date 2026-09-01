/* ============================================================================
   Altaha — the Engine Lab

   The tracker answers "did the ideas work". This answers the harder question
   underneath it: "does the scoring engine itself carry any signal, and which
   parts of it".

   THE NUMBER PEOPLE WILL MISREAD, SO IT IS EXPLAINED EVERY TIME
   An information coefficient of 0.03 to 0.05 is what a real, professionally
   traded equity factor looks like. It means right about 52% of the time. Shown
   without that context it reads as failure, and someone would go and "fix" a
   working engine. Shown with it, it reads as what it is.

   WHAT THIS PANEL REFUSES TO DO
   Show an average before there is enough data to support one. The backend
   withholds it below eight measured dates; this panel says how long the wait
   is instead of drawing an empty chart. A number that will be quoted forever
   and caveated once should not exist yet.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_LAB__) return;
  window.__ALTAHA_LAB__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function num(v, dp) {
    return v == null ? "—" : Number(v).toFixed(dp == null ? 2 : dp);
  }
  function signed(v, dp) {
    if (v == null) return "—";
    return (v > 0 ? "+" : "") + Number(v).toFixed(dp == null ? 3 : dp);
  }
  function cls(v) { return v == null ? "" : (v > 0.01 ? "pos" : v < -0.01 ? "neg" : ""); }

  var state = { horizon: 21, busy: false };

  function host() {
    var view = document.getElementById("view-tracker");
    if (!view) return null;
    var el = document.getElementById("lab");
    if (el) return el;
    el = document.createElement("section");
    el.id = "lab";
    el.className = "lab";
    view.appendChild(el);
    return el;
  }

  /* ---- the health line --------------------------------------------------
     First, because everything below it is meaningless if the store is not
     recording. This is the failure that ran silently in production for
     months: sqlite could not open its file, the endpoint answered 503 with
     that string, and nothing anywhere said "no evidence is being collected". */
  function healthHTML(cov) {
    if (!cov || cov.available === false) {
      return '<div class="labwarn"><b>The point-in-time store is not running.</b> ' +
        esc(cov && cov.reason || "Nothing is being recorded, so none of this can be measured.") +
        "</div>";
    }
    var d = cov.diagnostics || {};
    var bits = [];
    if (cov.ok === false) {
      bits.push('<div class="labwarn"><b>The store could not be read.</b> ' +
        esc(cov.error || "") + "</div>");
    }
    if (d.persistent === false) {
      bits.push('<div class="labwarn"><b>Not on a persistent disk.</b> ' +
        esc(d.warning || "") + "</div>");
    }
    bits.push('<div class="labstats">' +
      cell(cov.snapshot_dates, "days recorded") +
      cell(cov.distinct_symbols, "symbols") +
      cell(cov.distinct_factors, "factors tracked") +
      cell(cov.forward_returns, "outcomes attached") +
      cell(cov.labelled_pairs, "measurable pairs") +
      "</div>");
    if (cov.first_date) {
      bits.push('<p class="labnote">Recording since ' + esc(cov.first_date) +
        (cov.last_date ? ", last snapshot " + esc(cov.last_date) : "") + ".</p>");
    }
    return bits.join("");
  }

  function cell(v, label) {
    return '<div class="labcell"><b>' + (v == null ? "—" : v) +
           "</b><span>" + esc(label) + "</span></div>";
  }

  /* ---- the factor table ------------------------------------------------- */
  function icHTML(ic) {
    if (!ic || !ic.factors || !ic.factors.length) {
      return '<p class="labnote">No factor has enough labelled history yet.</p>';
    }
    var measured = ic.factors.filter(function (f) { return f.reliable; });
    if (!measured.length) {
      var best = ic.factors[0] || {};
      return '<div class="labwait"><b>Collecting.</b> Every scan banks what the ' +
        'engine believed that day; an outcome is attached once the horizon has ' +
        'elapsed. No average is published below eight measured dates — an ' +
        'information coefficient from a handful of overlapping windows is noise ' +
        'with a decimal point, and it would be quoted long after the caveat was ' +
        'forgotten.' +
        (best.dates != null ? " <span>Furthest along: " + esc(best.factor) +
          ", " + best.dates + " date" + (best.dates === 1 ? "" : "s") + ".</span>" : "") +
        "</div>";
    }
    var rows = measured.map(function (f) {
      return "<tr>" +
        "<td>" + esc(f.factor) + "</td>" +
        '<td class="' + cls(f.mean_ic) + '"><b>' + signed(f.mean_ic) + "</b></td>" +
        "<td>" + num(f.hit_rate_pct, 0) + "%</td>" +
        '<td class="' + (f.quintile_spread_pct > 0 ? "pos" : f.quintile_spread_pct < 0 ? "neg" : "") +
          '">' + signed(f.quintile_spread_pct, 2) + "%</td>" +
        "<td>" + f.dates + "</td>" +
        '<td class="labverdict">' + esc(f.verdict || "") + "</td>" +
      "</tr>";
    }).join("");
    return '<table class="labtable"><thead><tr>' +
      "<th>factor</th><th>mean IC</th><th>dates positive</th>" +
      "<th>top minus bottom fifth</th><th>dates</th><th>reading</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>";
  }

  function scaleHTML() {
    return '<div class="labscale"><b>How to read an IC.</b> It is the ' +
      "correlation between how the engine ranked a list and how that list " +
      "actually did, against the index, over the same window. " +
      "<i>0.03 to 0.05 is what a real equity factor looks like</i> — right about " +
      "52% of the time. The money is in applying that across hundreds of names, " +
      "not in being right about one. Above 0.10 sustained is usually a bug " +
      "rather than a discovery.</div>";
  }

  /* ---- render ----------------------------------------------------------- */
  async function load() {
    var el = host();
    if (!el || state.busy) return;
    state.busy = true;
    if (!el.innerHTML) {
      el.innerHTML = '<div class="labload">Reading the engine’s own record…</div>';
    }
    try {
      var r = await Promise.all([
        fetch(API + "/pit/coverage").then(function (x) { return x.json(); }),
        fetch(API + "/pit/ic?horizon=" + state.horizon).then(function (x) { return x.json(); })
      ]);
      var cov = r[0], ic = r[1];
      el.innerHTML =
        '<div class="labhdr"><h3>Engine Lab</h3>' +
        "<span>Does the scoring engine itself carry signal — and which parts of it</span></div>" +
        healthHTML(cov) +
        '<div class="labbar" id="labbar">' +
          [5, 10, 21, 63].map(function (h) {
            return '<button type="button" data-h="' + h + '"' +
                   (h === state.horizon ? ' class="on"' : "") + ">" + h + " sessions</button>";
          }).join("") +
        "</div>" +
        scaleHTML() +
        icHTML(ic) +
        '<p class="labnote">' + esc((ic && ic.factors && ic.factors.length &&
          ic.factors[0].reliable) ? "Windows overlap, so treat any t-statistic as a " +
          "rough guide rather than a significance test. A factor is only worth " +
          "acting on once it has survived a market regime it was not measured in." :
          "Nothing here is fitted. The engine's weights are unchanged priors; this " +
          "panel exists to replace them with measurements once the record supports it.") +
        "</p>";

      var bar = document.getElementById("labbar");
      if (bar && !bar.dataset.wired) {
        bar.dataset.wired = "1";
        bar.addEventListener("click", function (ev) {
          var b = ev.target.closest("button[data-h]");
          if (!b) return;
          state.horizon = parseInt(b.dataset.h, 10);
          load();
        });
      }
    } catch (e) {
      el.innerHTML = '<div class="labload">Engine unreachable — it may be waking up.</div>';
    } finally {
      state.busy = false;
    }
  }

  /* The tracker tab is the honesty surface, so the lab lives at the bottom of
     it rather than competing for a tab of its own. Loaded when that view is
     actually shown, not on every page load. */
  var seen = false;
  function poll() {
    var v = document.getElementById("view-tracker");
    if (!v || getComputedStyle(v).display === "none") return;
    if (seen) return;
    seen = true;
    load();
  }
  setInterval(poll, 1200);
  setTimeout(poll, 1500);

  window.AltahaLab = { load: load, refresh: function () { seen = false; poll(); } };
})();
