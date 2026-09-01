/* ============================================================================
   Altaha — the live sector board

   Which part of the market is actually moving today, and which names inside it
   are doing the moving.

   WHERE THE NUMBERS COME FROM
   /sector/overview?stocks=1 — one bulk Dhan quote covering every constituent
   of every sector plus the benchmark, in a single request. The sector figure
   is the equal-weight average of its carried heavyweights, not a published
   index level: an index is capitalisation-weighted, so "Nifty Bank is up 1%"
   can mean one enormous name moved and eleven others did nothing. The
   breadth count beside each tile is there for exactly that reason, and it is
   why clicking through to the constituents matters more than the headline.

   ANIMATION, AND THE LINE IT DOES NOT CROSS
   Tiles reorder as the market moves, and a reorder that teleports is a reorder
   nobody can follow — so the board measures each tile's position before and
   after a refresh and plays the difference (a FLIP). The percentage counts up
   to its new value rather than snapping. Both are legibility, not decoration:
   the eye tracks a moving object and does not track a changed one.

   Everything here respects prefers-reduced-motion, and every animation is on
   transform and opacity only, so it never costs a layout.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_SECTORS__) return;
  window.__ALTAHA_SECTORS__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  var REDUCED = false;
  try {
    REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {}

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function pct(v, dp) {
    if (v == null) return "—";
    var n = Number(v);
    return (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(dp == null ? 2 : dp) + "%";
  }
  function tone(v) { return v == null ? "" : v > 0 ? "up" : v < 0 ? "dn" : "flat"; }
  function rupee(v) {
    return v == null ? "—" : "₹" + Number(v).toLocaleString("en-IN",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /* ---- the icons ---------------------------------------------------------
     Drawn here rather than shipped from the server: these are the site's own
     stroke language (1.6px, round caps, currentColor) and they have to sit
     with the rest of the iconography, not look pasted in from elsewhere. The
     backend sends a key; the drawing is a frontend decision. */
  var ICONS = {
    chip: '<rect x="8" y="8" width="8" height="8" rx="1"/><path d="M10 4v4M14 4v4M10 16v4M14 16v4M4 10h4M4 14h4M16 10h4M16 14h4"/>',
    bank: '<path d="M3 10h18M5 10v8M9 10v8M15 10v8M19 10v8M3 21h18M12 3l9 5H3z"/>',
    pill: '<rect x="3" y="8" width="18" height="8" rx="4" transform="rotate(-40 12 12)"/><path d="M9.5 9.5l5 5"/>',
    wheat: '<path d="M12 21V9"/><path d="M12 9c0-2 1.6-3.6 3.6-3.6C15.6 7.4 14 9 12 9zM12 9C12 7 10.4 5.4 8.4 5.4 8.4 7.4 10 9 12 9z"/><path d="M12 13c0-2 1.6-3.6 3.6-3.6C15.6 11.4 14 13 12 13zM12 13c0-2-1.6-3.6-3.6-3.6C8.4 11.4 10 13 12 13z"/><path d="M12 17c0-2 1.6-3.6 3.6-3.6C15.6 15.4 14 17 12 17zM12 17c0-2-1.6-3.6-3.6-3.6C8.4 15.4 10 17 12 17z"/>',
    car: '<path d="M5 17h14M4 17v-4l2-5h12l2 5v4"/><path d="M6 8h12"/><circle cx="7.5" cy="17.5" r="1.6"/><circle cx="16.5" cy="17.5" r="1.6"/>',
    ingot: '<path d="M4 17h16l-2.5-5h-11z"/><path d="M7 12l1.6-4h6.8L17 12"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    plug: '<path d="M9 3v6M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0z"/><path d="M12 18v3"/>',
    factory: '<path d="M3 21V10l6 4V10l6 4V7l6 4v10z"/><path d="M7 21v-4M13 21v-4M19 21v-4"/>',
    building: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 21v-5h6v5"/><path d="M8 8h.01M12 8h.01M16 8h.01M8 12h.01M12 12h.01M16 12h.01"/>',
    tower: '<path d="M12 21V9"/><path d="M8 21l4-12 4 12"/><path d="M6.5 6.5a7 7 0 0 1 11 0M4 4a11 11 0 0 1 16 0"/>',
    dot: '<circle cx="12" cy="12" r="7"/>'
  };

  function icon(key) {
    return '<svg class="sb-icon" viewBox="0 0 24 24" aria-hidden="true">' +
           (ICONS[key] || ICONS.dot) + "</svg>";
  }

  var state = { window: "1D", data: null, open: null, busy: false, timer: null };

  /* ---- mount ------------------------------------------------------------ */

  function host() {
    var el = document.getElementById("sb-board");
    if (el) return el;
    var view = document.getElementById("view-screener");
    if (!view) return null;
    el = document.createElement("section");
    el.id = "sb-board";
    el.className = "sb-board";
    /* Above the search result and below the search box: this is market
       context, and context belongs before the thing it contextualises. */
    var after = view.querySelector(".hint") || view.querySelector(".searchrow");
    if (after && after.parentNode === view) {
      view.insertBefore(el, after.nextSibling);
    } else {
      view.insertBefore(el, view.firstChild);
    }
    return el;
  }

  /* ---- animation --------------------------------------------------------
     FLIP: read every tile's box, re-render, read them again, and play the
     difference. Without it a refresh that reorders the board teleports every
     tile and the reader loses the one thing the movement was telling them. */
  function positions(el) {
    var map = {};
    if (!el) return map;
    el.querySelectorAll("[data-sector]").forEach(function (n) {
      map[n.getAttribute("data-sector")] = n.getBoundingClientRect();
    });
    return map;
  }

  function playMoves(el, before) {
    if (REDUCED || !el) return;
    el.querySelectorAll("[data-sector]").forEach(function (n) {
      var was = before[n.getAttribute("data-sector")];
      if (!was) return;
      var now = n.getBoundingClientRect();
      var dx = was.left - now.left, dy = was.top - now.top;
      if (!dx && !dy) return;
      n.style.transition = "none";
      n.style.transform = "translate(" + dx + "px," + dy + "px)";
      requestAnimationFrame(function () {
        n.style.transition = "transform .52s cubic-bezier(.2,.8,.25,1)";
        n.style.transform = "";
      });
    });
  }

  /* Count the number up rather than snapping it. A figure that changes while
     you are looking at it is noticed; one that has already changed is not. */
  function countUp(node, to) {
    var from = parseFloat(node.getAttribute("data-v"));
    node.setAttribute("data-v", to);
    if (REDUCED || !isFinite(from) || from === to) {
      node.textContent = pct(to);
      return;
    }
    var t0 = 0, dur = 620;
    function step(ts) {
      if (!t0) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - k, 3);
      node.textContent = pct(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  /* ---- markup ----------------------------------------------------------- */

  function tile(r, i) {
    var t = tone(r.change_pct);
    var up = r.up || 0, total = r.total || 0;
    var upPct = total ? (up / total) * 100 : 0;
    var open = state.open === r.sector;
    return '<button class="sb-tile ' + t + (open ? " open" : "") + '" type="button"' +
      ' data-sector="' + esc(r.sector) + '" style="--i:' + Math.min(i, 11) + '"' +
      ' aria-expanded="' + (open ? "true" : "false") + '">' +
      '<span class="sb-head">' + icon(r.icon) +
        '<span class="sb-name">' + esc(r.sector) + "</span></span>" +
      '<span class="sb-pct ' + t + '" data-v="' + (r.change_pct == null ? "" : r.change_pct) + '">' +
        pct(r.change_pct) + "</span>" +
      '<span class="sb-breadth" title="' + up + " of " + total + ' advancing">' +
        '<i style="width:' + upPct.toFixed(1) + '%"></i></span>' +
      '<span class="sb-meta">' + up + "/" + total + " advancing" +
        (r.relative_pp != null
          ? '<em class="' + tone(r.relative_pp) + '">' + pct(r.relative_pp, 1) + " vs Nifty</em>"
          : "") + "</span>" +
    "</button>";
  }

  function stockRow(s) {
    return '<li class="' + tone(s.change_pct) + '"><b>' + esc(s.symbol) + "</b>" +
      "<span>" + rupee(s.ltp) + "</span>" +
      '<em class="' + tone(s.change_pct) + '">' + pct(s.change_pct) + "</em></li>";
  }

  function detail(r) {
    var stocks = r.stocks || [];
    if (!stocks.length) {
      return '<div class="sb-detail"><p class="sb-note">Constituent detail is not ' +
        "available for this window.</p></div>";
    }
    var up = stocks.filter(function (s) { return s.change_pct > 0; });
    var dn = stocks.filter(function (s) { return s.change_pct < 0; }).reverse();
    var flat = stocks.filter(function (s) { return s.change_pct === 0; });
    return '<div class="sb-detail" role="region">' +
      '<div class="sb-cols">' +
        '<div class="sb-col"><h5 class="up">Advancing <i>' + up.length + "</i></h5>" +
          (up.length ? "<ul>" + up.map(stockRow).join("") + "</ul>"
                     : '<p class="sb-note">Nothing in this sector is up.</p>') + "</div>" +
        '<div class="sb-col"><h5 class="dn">Declining <i>' + dn.length + "</i></h5>" +
          (dn.length ? "<ul>" + dn.map(stockRow).join("") + "</ul>"
                     : '<p class="sb-note">Nothing in this sector is down.</p>') + "</div>" +
      "</div>" +
      (flat.length ? '<p class="sb-note">' + flat.length + " unchanged.</p>" : "") +
      '<p class="sb-note">Equal-weight across the ' + stocks.length +
        " heavyweights carried for this sector, not a published index level — " +
        "so one very large company cannot speak for the rest. Click any name to " +
        "score it." +
      "</p></div>";
  }

  function render() {
    var el = host();
    if (!el) return;
    var d = state.data;
    if (!d) {
      el.innerHTML = '<div class="sb-load">Reading the market…</div>';
      return;
    }
    var rows = d.rows || [];
    if (!rows.length) {
      el.innerHTML = '<div class="sb-load">Sector data is not available right now.</div>';
      return;
    }

    var before = positions(el);
    var live = (d.source || "").toLowerCase() === "dhan";
    var opened = rows.filter(function (r) { return r.sector === state.open; })[0];

    el.innerHTML =
      '<div class="sb-hdr">' +
        "<h3>Where the market is moving</h3>" +
        '<div class="sb-bar">' +
          '<span class="sb-live ' + (live ? "on" : "") + '"><i></i>' +
            (live ? "Live feed" : "Delayed") + "</span>" +
          ["1D", "1W", "1M"].map(function (w) {
            return '<button type="button" class="sb-win' + (w === state.window ? " on" : "") +
                   '" data-w="' + w + '">' +
                   (w === "1D" ? "Today" : w === "1W" ? "Week" : "Month") + "</button>";
          }).join("") +
        "</div>" +
      "</div>" +
      '<div class="sb-grid">' + rows.map(tile).join("") + "</div>" +
      (opened ? detail(opened) : "") +
      '<p class="sb-foot">Ranked by return relative to the Nifty. Breadth is how ' +
        "many of the sector's carried names are advancing — a sector can be green " +
        "on one enormous company while most of it falls, and the bar is there to " +
        "show you when that is happening.</p>";

    playMoves(el, before);
    el.querySelectorAll(".sb-pct").forEach(function (n) {
      var v = parseFloat(n.getAttribute("data-v"));
      if (isFinite(v)) { n.setAttribute("data-v", ""); countUp(n, v); }
    });
  }

  /* ---- data ------------------------------------------------------------- */

  async function load(quiet) {
    if (state.busy) return;
    state.busy = true;
    if (!quiet && !state.data) render();
    try {
      var r = await fetch(API + "/sector/overview?window=" +
                          encodeURIComponent(state.window) + "&stocks=1");
      var d = await r.json();
      if (r.ok && d && d.rows) {
        state.data = d;
        render();
      } else if (!state.data) {
        var el = host();
        if (el) {
          el.innerHTML = '<div class="sb-load">' +
            esc((d && d.detail) || "Sector data is not available right now.") + "</div>";
        }
      }
    } catch (e) {
      if (!state.data) {
        var h = host();
        if (h) h.innerHTML = '<div class="sb-load">Engine unreachable — it may be waking up.</div>';
      }
    } finally {
      state.busy = false;
    }
  }

  /* ---- interaction ------------------------------------------------------
     Delegated, because the board redraws itself wholesale on every refresh and
     per-tile listeners would survive the first render and quietly stop working
     after the second. */
  document.addEventListener("click", function (ev) {
    var el = document.getElementById("sb-board");
    if (!el || !ev.target.closest) return;

    var win = ev.target.closest(".sb-win[data-w]");
    if (win && el.contains(win)) {
      state.window = win.getAttribute("data-w");
      state.data = null;
      state.open = null;
      render();
      load();
      return;
    }

    var name = ev.target.closest("#sb-board .sb-detail li b");
    if (name) {
      /* A constituent is a stock like any other — send it to the analyser
         rather than making the reader retype it. */
      var sym = name.textContent.trim();
      if (sym && typeof window.analyse === "function") {
        try { window.analyse(sym); } catch (e) {}
      }
      return;
    }

    var tileEl = ev.target.closest(".sb-tile[data-sector]");
    if (tileEl && el.contains(tileEl)) {
      var s = tileEl.getAttribute("data-sector");
      state.open = (state.open === s) ? null : s;
      render();
      var d = document.querySelector("#sb-board .sb-detail");
      if (d && !REDUCED) d.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });

  /* ---- lifecycle --------------------------------------------------------
     Refreshed while the market is open and left alone when it is not. Polling
     a closed market repaints the same numbers and costs the reader battery. */
  function marketOpen() {
    var s = document.getElementById("mkstatustx");
    return !!(s && /open/i.test(s.textContent || ""));
  }

  function tick() {
    var view = document.getElementById("view-screener");
    if (!view || getComputedStyle(view).display === "none") return;
    if (document.hidden) return;
    if (state.data && !marketOpen()) return;
    load(true);
  }

  function boot() {
    if (!host()) { setTimeout(boot, 500); return; }
    load();
    if (!state.timer) state.timer = setInterval(tick, 30000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 300); });
  } else {
    setTimeout(boot, 300);
  }

  window.AltahaSectors = {
    reload: function () { state.data = null; load(); },
    open: function (s) { state.open = s; render(); }
  };
})();
