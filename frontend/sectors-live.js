/* ============================================================================
   Altaha — the live sector board

   Which part of the market is actually moving today, and which names inside it
   are doing the moving.

   WHERE THE NUMBERS COME FROM
   /sector/benchmarks — published NSE index levels and NSE historical closes.
   No equal-weight stock baskets, ETF proxies or inferred constituent breadth.

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
    var market = view.querySelector('.mb');
    if (market) {
      market.after(el);
    } else if (after && after.parentNode === view) {
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
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'off' || !el) return;
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

  /* Financial labels show the exact received value throughout the animation. */
  function countUp(node, to) {
    node.setAttribute("data-v", to);
    node.textContent = pct(to);
  }

  /* ---- markup ----------------------------------------------------------- */

  function tile(r, i) {
    var t = tone(r.change_pct);
    var open = state.open === r.sector;
    return '<button class="sb-tile ' + t + (open ? " open" : "") + '" type="button"' +
      ' data-sector="' + esc(r.sector) + '" style="--i:' + Math.min(i, 11) + '"' +
      ' aria-expanded="' + (open ? "true" : "false") + '">' +
      '<span class="sb-head">' + icon(r.icon) +
        '<span class="sb-name">' + esc(r.sector) + "</span></span>" +
      '<span class="sb-pct ' + t + '" data-v="' + (r.change_pct == null ? "" : r.change_pct) + '">' +
        pct(r.change_pct) + "</span>" +
      '<span class="sb-meta">' + (r.index_level != null
        ? 'Index ' + Number(r.index_level).toLocaleString('en-IN', {maximumFractionDigits:2})
        : 'Index level unavailable') + '</span>' +
      '<span class="sb-meta">' + (r.change_pct == null ? 'Return unavailable' : 'NSE benchmark') +
        (r.relative_pp != null
          ? '<em class="' + tone(r.relative_pp) + '">' +
            (r.relative_pp > 0 ? '+' : '') + Number(r.relative_pp).toFixed(2) + ' pp vs Nifty 50</em>'
          : '') + '</span>' +
    "</button>";
  }

  function detail(r) {
    var d = state.data || {};
    return '<div class="sb-detail" role="region" aria-label="Benchmark calculation">' +
      '<h4>' + esc(r.sector) + '</h4><p class="sb-note">' +
      esc(d.method || 'Published NSE index price return.') + '</p>' +
      '<p class="sb-note">' + (d.as_of ? 'Exchange timestamp: ' + esc(d.as_of) + ' IST. ' : 'Exchange timestamp unavailable. ') +
      (r.baseline_date ? 'Comparison close: ' + esc(r.baseline_date) + '. ' : '') +
      (r.change_pct == null ? 'The exchange data needed for this return is unavailable. ' : '') +
      '</p><a href="https://www.niftyindices.com/indices/equity/sectoral-indices" target="_blank" rel="noopener noreferrer">NSE index definitions ↗</a></div>';
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
    var focused = el.contains(document.activeElement) ? document.activeElement : null;
    var focusedSector = focused && focused.getAttribute('data-sector');
    var focusedWindow = focused && focused.getAttribute('data-w');
    var status = d.stale ? "Last available · refresh failed" : d.available ? "NSE snapshot" : "NSE unavailable";
    var opened = rows.filter(function (r) { return r.sector === state.open; })[0];

    el.innerHTML =
      '<div class="sb-hdr">' +
        "<h3>NSE sector benchmarks</h3>" +
        '<div class="sb-bar">' +
          '<span class="sb-live"><i></i>' + status + "</span>" +
          ["1D", "1W", "1M"].map(function (w) {
            return '<button type="button" class="sb-win' + (w === state.window ? " on" : "") +
                   '" data-w="' + w + '">' +
                   (w === "1D" ? "Day" : w === "1W" ? "7D" : "30D") + "</button>";
          }).join("") +
        "</div>" +
      "</div>" +
      '<div class="sb-grid">' + rows.map(tile).join("") + "</div>" +
      (opened ? detail(opened) : "") +
      '<p class="sb-foot">Published NSE index price returns, ranked highest first. ' +
        'Day compares with the previous close; 7D/30D compare with the close on or before 7/30 calendar days earlier. ' +
        (d.as_of ? 'Exchange timestamp ' + esc(d.as_of) + ' IST. ' : '') +
        (d.baseline_date ? 'Comparison close ' + esc(d.baseline_date) + '. ' : '') +
        (d.stale ? 'Refresh failed; showing the last available snapshot. ' : '') +
        'Unavailable returns are shown as —.</p>';

    playMoves(el, before);
    el.querySelectorAll('[data-sector], [data-w]').forEach(function(n) {
      if ((focusedSector && n.getAttribute('data-sector') === focusedSector) ||
          (focusedWindow && n.getAttribute('data-w') === focusedWindow)) n.focus({preventScroll:true});
    });
    el.querySelectorAll(".sb-pct").forEach(function (n) {
      var v = parseFloat(n.getAttribute("data-v"));
      if (isFinite(v)) { n.setAttribute("data-v", ""); countUp(n, v); }
    });
  }

  /* ---- data ------------------------------------------------------------- */

  async function load(quiet) {
    if (state.busy) return;
    state.busy = true;
    var requestedWindow = state.window;
    if (!quiet && !state.data) render();
    try {
      var r = await fetch(API + "/sector/benchmarks?window=" +
                          encodeURIComponent(requestedWindow));
      var d = await r.json();
      if (requestedWindow !== state.window) return;
      if (r.ok && d && d.rows) {
        state.data = d;
        render();
      } else if (state.data) {
        state.data = Object.assign({}, state.data, {stale:true}); render();
      } else {
        var el = host();
        if (el) {
          el.innerHTML = '<div class="sb-load">' +
            esc((d && d.detail) || "Sector data is not available right now.") + "</div>";
        }
      }
    } catch (e) {
      if (state.data && requestedWindow === state.window) {
        state.data = Object.assign({}, state.data, {stale:true}); render();
      }
      if (!state.data && requestedWindow === state.window) {
        var h = host();
        if (h) h.innerHTML = '<div class="sb-load">Engine unreachable — it may be waking up.</div>';
      }
    } finally {
      state.busy = false;
      if (requestedWindow !== state.window) load();
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
    if (state.data && state.data.available && !state.data.stale && !marketOpen()) return;
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
