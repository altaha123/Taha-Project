/* ============================================================================
   Altaha — bulk, block and short deals

   Two surfaces from one module: a board of the day's disclosures on the Live
   tab, and a per-stock block that appears under any stock you analyse.

   WHAT IT REFUSES TO DO
   Print the rows raw. Every finance site in India shows a bulk-deal table, and
   read straight it misleads in two reliable ways:

     · The same counterparty is often on both sides of the same stock on the
       same day. That is a position opened and closed, or stock crossed between
       accounts — not accumulation. The buy side alone reads as demand that
       never existed.
     · A large share of small-cap bulk-deal rows are proprietary desks making
       markets. Their name on the buy side means a market maker had inventory
       that afternoon. It carries no view about the company.

   The backend nets both out and this shows the difference: what was actually
   accumulated, beside what merely crossed the tape.

   AND IT IS NOT A SIGNAL
   A bulk deal says who traded, not whether they were right. In a small cap it
   is as often an operator distributing stock as an investor building a
   position, and the exchange record cannot tell you which. It sits beside the
   analysis as evidence, the way a filing does, and never touches a score.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_DEALS__) return;
  window.__ALTAHA_DEALS__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  var REDUCED = false;
  try { REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function cr(v) {
    if (v == null) return "—";
    var n = Number(v);
    return (n > 0 ? "+" : n < 0 ? "−" : "") + "₹" + Math.abs(n).toLocaleString("en-IN",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "cr";
  }
  function plain(v) {
    if (v == null) return "—";
    return "₹" + Number(v).toLocaleString("en-IN",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "cr";
  }
  function tone(v) { return v == null ? "" : v > 0 ? "up" : v < 0 ? "dn" : ""; }

  /* ---- the board -------------------------------------------------------- */

  var state = { board: null, busy: false, mounted: false };

  function boardHost() {
    var el = document.getElementById("dl-board");
    if (el) return el;
    /* Its own tab, beside Filings. Both are exchange disclosures, which is
       what these are — the earlier home on the intraday-alerts view was
       wrong on both counts: nav.js renames that tab "Alerts" and nests it
       under Ideas, so the board was neither where it was described nor
       anywhere a reader would look for it. */
    var view = document.getElementById("view-deals") ||
               document.getElementById("view-live") ||
               document.getElementById("view-screener");
    if (!view) return null;
    el = document.createElement("section");
    el.id = "dl-board";
    el.className = "dl-board";
    view.appendChild(el);
    return el;
  }

  function tags(r) {
    var out = [];
    if (r.block) out.push('<i class="dl-tag block">block</i>');
    if (r.crossed) out.push('<i class="dl-tag cross">crossed</i>');
    if (r.prop_cr > 0) out.push('<i class="dl-tag prop">' + plain(r.prop_cr) + " prop</i>");
    return out.join("");
  }

  function party(p) {
    return '<li><b>' + esc(p.client) + "</b>" +
      (p.institutional ? '<i class="dl-inst">institution</i>' : "") +
      "<span>" + plain(p.value_cr) + "</span></li>";
  }

  function symbolRow(r, i) {
    var parties = "";
    if ((r.top_buyers || []).length || (r.top_sellers || []).length) {
      parties = '<div class="dl-parties">' +
        ((r.top_buyers || []).length
          ? '<div><h6 class="up">Bought</h6><ul>' + r.top_buyers.map(party).join("") + "</ul></div>" : "") +
        ((r.top_sellers || []).length
          ? '<div><h6 class="dn">Sold</h6><ul>' + r.top_sellers.map(party).join("") + "</ul></div>" : "") +
      "</div>";
    }
    return '<div class="dl-row" style="--i:' + Math.min(i, 12) + '">' +
      '<div class="dl-top">' +
        '<span class="dl-sym" data-t="' + esc(r.symbol) + '">' + esc(r.symbol) +
          '<small>' + esc(r.name || "") + "</small></span>" +
        '<span class="dl-net ' + tone(r.net_cr) + '">' + cr(r.net_cr) +
          "<small>net</small></span>" +
      "</div>" +
      '<div class="dl-meta">' + tags(r) +
        "<span>" + r.deals + " deal" + (r.deals === 1 ? "" : "s") + "</span>" +
        "<span>" + plain(r.gross_cr) + " traded through them</span>" +
      "</div>" +
      parties +
      '<p class="dl-read">' + esc(r.reading) + "</p>" +
    "</div>";
  }

  function renderBoard() {
    var el = boardHost();
    if (!el) return;
    var d = state.board;
    if (!d) { el.innerHTML = '<div class="dl-load">Reading the exchange…</div>'; return; }
    if (!d.available) {
      el.innerHTML = '<div class="dl-load">' + esc(d.message || "No disclosures.") + "</div>";
      return;
    }
    var c = d.counts || {};
    var rows = d.symbols || [];
    el.innerHTML =
      '<div class="dl-hdr"><h3>Who traded size today</h3>' +
        "<span>Bulk and block deals disclosed to the exchange" +
        (d.as_on ? " — " + esc(d.as_on) : "") + "</span></div>" +
      '<div class="dl-counts">' +
        '<span><b>' + (c.bulk || 0) + "</b>bulk</span>" +
        '<span><b>' + (c.block || 0) + "</b>block</span>" +
        '<span><b>' + (c.short || 0) + "</b>short-sell</span>" +
        '<span><b>' + (d.total_symbols || 0) + "</b>stocks</span>" +
      "</div>" +
      '<p class="dl-timing">' + esc(d.timing || "") + "</p>" +
      (rows.length
        ? '<div class="dl-rows">' + rows.map(symbolRow).join("") + "</div>"
        : '<div class="dl-load">Nothing above the size filter today.</div>') +
      '<p class="dl-caveat">' + esc(d.caveat || "") + "</p>";
  }

  async function loadBoard() {
    if (state.busy) return;
    state.busy = true;
    if (!state.board) renderBoard();
    try {
      var r = await fetch(API + "/deals?min_value_cr=1&limit=25");
      state.board = await r.json();
    } catch (e) {
      state.board = { available: false, message: "Engine unreachable — it may be waking up." };
    } finally {
      state.busy = false;
      renderBoard();
    }
  }

  /* ---- the per-stock block ---------------------------------------------- */

  var perStock = { sym: null, busy: false };

  function stockHost() {
    var el = document.getElementById("dl-stock");
    if (el) return el;
    var result = document.getElementById("result");
    if (!result) return null;
    el = document.createElement("div");
    el.id = "dl-stock";
    el.className = "dl-stock";
    el.hidden = true;
    var before = document.getElementById("sharerow") || document.getElementById("disc");
    if (before && before.parentNode === result) result.insertBefore(el, before);
    else result.appendChild(el);
    return el;
  }

  function dealRow(r) {
    return "<tr class=\"" + (r.side === "BUY" ? "up" : "dn") + "\">" +
      "<td>" + esc(r.date) + "</td>" +
      "<td>" + esc(r.client) +
        (r.prop_desk ? '<i class="dl-inst prop">prop desk</i>' : "") + "</td>" +
      "<td>" + esc(r.kind) + "</td>" +
      "<td>" + esc(r.side) + "</td>" +
      "<td>" + (r.qty == null ? "—" : Number(r.qty).toLocaleString("en-IN")) + "</td>" +
      "<td>" + (r.price == null ? "—" : "₹" + Number(r.price).toLocaleString("en-IN")) + "</td>" +
      "<td>" + plain(r.value_cr) + "</td></tr>";
  }

  async function loadStock(sym) {
    var el = stockHost();
    if (!el || !sym || perStock.busy) return;
    perStock.busy = true;
    perStock.sym = sym;
    try {
      var r = await fetch(API + "/deals/" + encodeURIComponent(sym) + "?days=90");
      var d = await r.json();
      if (perStock.sym !== sym) return;
      var rows = (d && d.rows) || [];
      if (!rows.length) { el.hidden = true; el.innerHTML = ""; return; }
      var net = d.net || null;
      el.hidden = false;
      el.innerHTML =
        '<div class="dl-hdr"><h3>Who traded size in ' + esc(sym) + "</h3>" +
          "<span>Bulk and block deals disclosed to the exchange, last 90 days</span></div>" +
        (net ? '<div class="dl-summary ' + tone(net.net_cr) + '">' +
                 "<b>" + cr(net.net_cr) + "</b><span>" + esc(net.reading) + "</span></div>" : "") +
        '<div class="dl-tablewrap"><table class="dl-table"><thead><tr>' +
          "<th>date</th><th>counterparty</th><th>type</th><th>side</th>" +
          "<th>quantity</th><th>price</th><th>value</th>" +
        "</tr></thead><tbody>" + rows.slice(0, 25).map(dealRow).join("") + "</tbody></table></div>" +
        (rows.length > 25 ? '<p class="dl-caveat">' + (rows.length - 25) +
           " older disclosures not shown.</p>" : "") +
        '<p class="dl-caveat">A disclosure says who traded, not whether they were ' +
          "right. In a small cap a bulk deal is as often an operator distributing " +
          "stock as an investor building a position, and the exchange record " +
          "cannot tell you which. It never touches the score above.</p>";
    } catch (e) {
      el.hidden = true;
    } finally {
      perStock.busy = false;
    }
  }

  /* ---- wiring -----------------------------------------------------------
     The analysed symbol is read from the page rather than hooked into
     analyse(), so this keeps working if that function is replaced — which has
     already happened once in this codebase with loadTracker. */
  var lastSym = null;
  function watch() {
    var el = document.getElementById("csym");
    var result = document.getElementById("result");
    if (!el || !result || result.style.display === "none") return;
    /* #csym is `<b>TICKER</b> · EXCHANGE`, so the bold element is the symbol
       and splitting the text is only the fallback. Reading the structure
       beats parsing the rendering. */
    var b = el.querySelector("b");
    var sym = ((b ? b.textContent : el.textContent) || "").trim().toUpperCase()
      .replace(".NS", "").replace(".BO", "").split(/[\s·]/)[0];
    if (!sym || sym === lastSym) return;
    lastSym = sym;
    loadStock(sym);
  }

  var seenLive = false;
  function tick() {
    watch();
    var live = document.getElementById("view-deals") ||
               document.getElementById("view-live") ||
               document.getElementById("view-screener");
    if (!live || getComputedStyle(live).display === "none") return;
    if (seenLive) return;
    seenLive = true;
    loadBoard();
  }

  setInterval(tick, 1200);
  setTimeout(tick, 1500);

  document.addEventListener("click", function (ev) {
    var s = ev.target.closest && ev.target.closest(".dl-sym[data-t]");
    if (s && typeof window.analyse === "function") {
      try { window.analyse(s.getAttribute("data-t")); } catch (e) {}
    }
  });

  window.AltahaDeals = { board: loadBoard, forSymbol: loadStock };
})();
