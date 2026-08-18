/* ============================================================================
   Altaha — Tracker repairs
   ----------------------------------------------------------------------------
   Three things were wrong with the Tracker tab, and they had different causes.

   1. EVERY PRICE COLUMN WAS BLANK.
      The columns are filled by tracker.update_all(), which is called from
      exactly one place: /cron/tick, and only after 16:00 IST. With no external
      cron pointed at that endpoint, it had never run — so every row showed
      "Now ₹—, Return —, Index —, 0 days" forever. There is now a Refresh
      prices button that calls the marking routine directly, and the tab says
      how many rows are still unmarked instead of leaving you to guess.

   2. STOCKS APPEARED WITHOUT BEING ADDED.
      That is deliberate in the engine — recording only the ideas someone
      chooses to save turns a hit rate into a highlight reel. It is the right
      default for measuring the engine and the wrong one for a watchlist. The
      My picks filter separates the two, and Clear auto-recorded removes the
      scan's rows in one go. Set AUTOTRACK=0 on Render to stop new ones.

   3. THERE WAS NO WAY TO REMOVE ANYTHING.
      The backend has had /tracker/remove all along; nothing in the interface
      ever called it. Each row now carries a Remove control.

   This file replaces the page's own loadTracker(). It does not modify it in
   place, so deleting this one <script> line restores the original behaviour
   exactly.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_TRACKERFIX__) return;
  window.__ALTAHA_TRACKERFIX__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function pct(v) { return v == null ? "\u2014" : (v > 0 ? "+" : "") + v + "%"; }
  function sign(v) { return v == null ? "" : (v > 0 ? "pos" : (v < 0 ? "neg" : "")); }
  function rupee(v) { return v == null ? "\u2014" : "\u20B9" + Number(v).toLocaleString("en-IN"); }

  var srcFilter = "";        // "" = everything, "manual" = only what you added

  /* ---- styles, on the existing tokens ---------------------------------- */

  var css = document.createElement("style");
  css.textContent = [
    ".tk{position:relative}",
    ".tkrm{position:absolute;top:10px;right:10px;border:1px solid var(--rule);",
    "  background:var(--paper);color:var(--mute);border-radius:999px;cursor:pointer;",
    "  font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;",
    "  padding:4px 10px;transition:border-color 150ms,color 150ms,background 150ms}",
    ".tkrm:hover{border-color:var(--fail);color:var(--fail)}",
    ".tkrm[disabled]{opacity:.5;cursor:default}",
    ".tk .tkt{padding-right:86px}",
    ".tkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}",
    ".tkflag{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--mute);",
    "  border-left:2px solid var(--gold);padding:2px 0 2px 10px;margin:0 0 12px;line-height:1.7}",
    ".tksrc{font-family:var(--mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;",
    "  color:var(--mute);border:1px solid var(--rule-2);border-radius:999px;padding:2px 7px;margin-left:8px}",
    "@media(max-width:560px){.tk .tkt{padding-right:0}.tkrm{position:static;margin-top:10px;display:inline-block}}"
  ].join("\n");
  document.head.appendChild(css);

  /* ---- toolbar --------------------------------------------------------- */

  function toolbar() {
    var host = $("view-tracker");
    if (!host || $("tkbar2")) return;
    var bar = document.createElement("div");
    bar.className = "tkbar";
    bar.id = "tkbar2";
    bar.innerHTML =
      '<button class="act solid" id="tkrefresh" type="button">Refresh prices</button>' +
      '<button class="act" id="tkmine" type="button">My picks only</button>' +
      '<button class="act" id="tkclearauto" type="button">Clear auto-recorded</button>';
    var anchor = $("tkstats");
    host.insertBefore(bar, anchor);

    $("tkrefresh").addEventListener("click", refresh);
    $("tkmine").addEventListener("click", function () {
      srcFilter = srcFilter === "manual" ? "" : "manual";
      this.classList.toggle("solid", srcFilter === "manual");
      this.textContent = srcFilter === "manual" ? "Showing my picks" : "My picks only";
      render();
    });
    $("tkclearauto").addEventListener("click", clearAuto);
  }

  /* ---- actions --------------------------------------------------------- */

  async function refresh() {
    var b = $("tkrefresh");
    b.disabled = true;
    b.textContent = "Marking\u2026";
    try {
      /* This is the call that was never being made. It fetches daily bars for
         each unmarked row and computes return, index return, best, worst and
         days held. Capped server-side, so a large list may need two presses —
         the button says so rather than looking finished. */
      var r = await fetch(API + "/tracker/update?limit=150", { method: "POST" });
      var j = await r.json();
      b.textContent = r.ok
        ? "Marked " + (j.updated || 0)
        : (j.detail || "Couldn't mark").slice(0, 40);
      await render();
    } catch (e) {
      b.textContent = "Engine unreachable";
    }
    setTimeout(function () { b.disabled = false; b.textContent = "Refresh prices"; }, 2600);
  }

  async function remove(id, el) {
    el.disabled = true;
    el.textContent = "Removing";
    try {
      await fetch(API + "/tracker/remove?id=" + encodeURIComponent(id), { method: "POST" });
      var card = el.closest(".tk");
      if (card) { card.style.transition = "opacity 200ms"; card.style.opacity = "0"; }
      setTimeout(render, 220);
    } catch (e) {
      el.disabled = false; el.textContent = "Remove";
    }
  }

  async function clearAuto() {
    var b = $("tkclearauto");
    try {
      var d = await (await fetch(API + "/tracker/list?limit=1000")).json();
      var auto = (d.rows || []).filter(function (r) { return (r.source || "auto") === "auto"; });
      if (!auto.length) { b.textContent = "Nothing auto-recorded"; return; }
      if (!window.confirm(
        "Remove " + auto.length + " automatically recorded ideas?\n\n" +
        "Anything you added yourself is kept. This also resets the hit-rate " +
        "statistics, because those are computed from the rows that remain."
      )) return;
      b.disabled = true;
      for (var i = 0; i < auto.length; i++) {
        b.textContent = "Removing " + (i + 1) + "/" + auto.length;
        await fetch(API + "/tracker/remove?id=" + encodeURIComponent(auto[i].id), { method: "POST" });
      }
      b.textContent = "Removed " + auto.length;
      await render();
    } catch (e) {
      b.textContent = "Couldn't clear";
    }
    setTimeout(function () { b.disabled = false; b.textContent = "Clear auto-recorded"; }, 2600);
  }

  /* ---- render ---------------------------------------------------------- */

  async function render() {
    toolbar();
    var rowsEl = $("tkrows");
    if (!rowsEl) return;
    var csv = $("tkcsv");
    if (csv) csv.href = API + "/tracker/export.csv";

    var status = (typeof tkFilter !== "undefined" && tkFilter) ? tkFilter : "";
    rowsEl.innerHTML = (typeof SKEL === "function") ? SKEL(3) : "Loading\u2026";

    try {
      var q = "/tracker/list?status=" + encodeURIComponent(status) + "&limit=400" +
              (srcFilter ? "&source=" + srcFilter : "");
      var res = await Promise.all([
        fetch(API + q),
        fetch(API + "/tracker/stats")
      ]);
      var d = await res[0].json();
      var st = await res[1].json();

      var o = st.overall;
      var stats = $("tkstats");
      if (stats) {
        stats.innerHTML = o ? [
          cell(0, st.total_tracked, "ideas recorded"),
          cell(1, pct(o.avg_alpha_pct), "avg alpha vs index", sign(o.avg_alpha_pct)),
          cell(2, o.beat_index_pct != null ? o.beat_index_pct + "%" : "\u2014", "beat the index"),
          cell(3, pct(o.avg_return_pct), "avg return", sign(o.avg_return_pct)),
          cell(4, pct(o.avg_max_drawdown_pct), "avg worst dip", "neg"),
          cell(5, o.median_days_held, "median days held")
        ].join("") :
          '<div class="statcell" style="grid-column:1/-1"><b>' + (st.total_tracked || 0) +
          '</b><span>recorded, none marked yet \u2014 press Refresh prices</span></div>';
      }

      /* The honest status line. Previously the tab was silent about the one
         thing that mattered: whether marking had ever run. */
      var flags = [];
      if (st.unmarked) {
        flags.push("<b>" + st.unmarked + " row" + (st.unmarked === 1 ? "" : "s") +
          " have no prices yet.</b> Press Refresh prices. Marking otherwise only " +
          "runs after 16:00 IST, and only if an external cron is calling /cron/tick.");
      }
      if (st.mark_errors) {
        flags.push(st.mark_errors + " row" + (st.mark_errors === 1 ? "" : "s") +
          " could not be priced from either feed \u2014 usually a delisted or renamed symbol.");
      }
      if (st.autotrack === false) {
        flags.push("Automatic recording is off. Only names you press Add on are tracked.");
      } else if (st.autotrack === true) {
        flags.push("Every scan records its ideas automatically, so this list grows on its own. " +
          "Set AUTOTRACK=0 on Render to record only what you add by hand.");
      }
      if (st.storage_is_ephemeral) {
        flags.push("<b>DATA_DIR is not set to a Render disk</b>, so this record is wiped on every deploy.");
      }
      var note = $("tknote");
      if (note) {
        note.innerHTML = flags.map(function (f) { return '<div class="tkflag">' + f + "</div>"; }).join("") +
          "<div>" + esc(st.note || "") + "</div>";
      }

      if (!d.rows || !d.rows.length) {
        rowsEl.innerHTML = '<div class="ideas-note" style="padding:14px 0">' +
          (srcFilter === "manual"
            ? "You have not added anything by hand yet. Open the Ideas tab and press <b>Track</b> on a name, or analyse a stock and add it from there."
            : "Nothing recorded yet. Run a universe scan, or press <b>Record current ideas</b> above.") +
          "</div>";
        return;
      }

      rowsEl.innerHTML = d.rows.map(function (r, i) {
        var src = (r.source || "auto") === "manual" ? "ADDED BY YOU" : "FROM SCAN";
        return '<div class="tk rise" style="--i:' + Math.min(i, 10) + '">' +
          '<button class="tkrm" type="button" data-id="' + esc(r.id) + '">Remove</button>' +
          '<div class="tkt"><span class="tknm">' + esc(r.name || r.symbol) +
            '<span class="tkstat ' + esc(r.status) + '">' + esc(r.status) + '</span>' +
            '<span class="tksrc">' + src + '</span>' +
            '<small>' + esc(r.symbol) + ' \u00B7 ' + esc(r.setup || "\u2014") +
            ' \u00B7 added ' + esc(r.added_on) + ' at ' + rupee(r.added_price) + '</small></span>' +
          '<span class="tkret ' + sign(r.alpha_pct) + '">' + pct(r.alpha_pct) + '<small>alpha</small></span></div>' +
          '<div class="tkln">' +
            '<span>Now ' + rupee(r.last_price) + '</span>' +
            '<span class="' + sign(r.return_pct) + '">Return ' + pct(r.return_pct) + '</span>' +
            '<span>Index ' + pct(r.bench_return_pct) + '</span>' +
            '<span>Best ' + pct(r.max_gain_pct) + '</span>' +
            '<span>Worst ' + pct(r.max_drawdown_pct) + '</span>' +
            '<span>' + (r.days_held || 0) + ' days</span>' +
            (r.sector ? '<span>' + esc(r.sector) + '</span>' : "") +
          '</div>' +
          (r.mark_error ? '<div class="warnbox">Could not price this symbol: ' + esc(r.mark_error) + '</div>' : "") +
          (r.invalidated_by ? '<div class="warnbox">' + esc(r.invalidated_by) + '</div>' : "") +
        '</div>';
      }).join("");

      rowsEl.querySelectorAll(".tkrm").forEach(function (b) {
        b.addEventListener("click", function () { remove(b.dataset.id, b); });
      });
    } catch (e) {
      rowsEl.innerHTML = '<div class="ideas-note" style="padding:14px 0">Engine unreachable \u2014 it may be waking from sleep. Try again in about 30 seconds.</div>';
    }
  }

  function cell(i, val, label, cls) {
    return '<div class="statcell rise" style="--i:' + i + '"><b class="' + (cls || "") + '">' +
           val + "</b><span>" + label + "</span></div>";
  }

  /* Replace the page's own function. It is a top-level declaration, so it is a
     writable property of window and every existing caller — switchTab, the
     filter buttons, the backfill button — picks this up with no other edit. */
  window.loadTracker = render;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", toolbar);
  else toolbar();
})();
