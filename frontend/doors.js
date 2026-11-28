/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — the three doors

   WHAT THIS IS
   The page each door opens on. Market, Ideas and Portfolio each preview every
   tool behind them — one live number or one line per tool — and open the
   tool on a tap. The tools themselves are the views that already exist and
   are not touched here; this file only decides how you arrive at them.

     Market     #view-today     the market, live: Nifty, the other indices, a
                               three-month chart, FII/DII flows, every sector,
                               the movers, and a card per Market tool
     Ideas     #view-ideahub   the ranked universe and every way to find a stock
     Portfolio #view-money     your saved portfolio, watchlist and plans

   IT OWNS NO DATA, AND INVENTS NONE
   Every figure is read from an endpoint another view already uses. A feed
   that is asleep (normal for the first thirty seconds on a free instance)
   leaves its card saying so, and every other card still renders. A count
   that cannot be read is shown as a dash, never as zero.

   MOTION
   Cards rise in, counts count up, the chart draws itself, prices flash when
   they change, the planets turn. All of it stops for prefers-reduced-motion
   or the site's own motion switch (html[data-motion="off"]), and nothing is
   ever hidden waiting for an animation to reveal it. Prices are never
   counted up: an intermediate price is a price that never traded.

   NOTHING HERE IS A RECOMMENDATION
   These are observations about the market and pointers to tools.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';
  if (window.AltahaDoors) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var FRESH_MS = 120000;
  var PIN_KEY = 'altaha-pins-v1';
  var WATCH_KEY = 'altaha-watchlist-v1';
  var STORE_KEY = 'altaha-portfolios';
  var DRAFT_KEY = 'altaha-portfolio-draft-v1';
  var UNI_KEY = 'altaha-universe-v4';        // written by shell.js (see its note)

  /* The investor styles in backend/lenses.json, in the order the lenses page
     lists them. Names only; the screens themselves are on that page. */
  var LENSES = ['Coffee Can', 'Moat', 'QGLP', 'Tenbagger', 'Owner-Operator', 'Nomad',
                'Cannibal', 'Akre', 'Gorilla', 'Capital Cycle'];

  var ICON = {
    alerts:   '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    deals:    '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    flows:    '<path d="M3 17c4 0 4-10 9-10s5 6 9 6"/><path d="m17 9 4 4-4 4"/>',
    wow:      '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    delivery: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    results:  '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    filings:  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 14h5M9 17h3"/>',
    options:  '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    query:    '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    lenses:   '<circle cx="7" cy="14" r="4"/><circle cx="17" cy="14" r="4"/><path d="M11 14h2M3 14l2-7M21 14l-2-7"/>',
    converge: '<circle cx="8" cy="10" r="5"/><circle cx="16" cy="10" r="5"/><circle cx="12" cy="16" r="5"/>',
    owners:   '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c1-4 4-6 7-6s6 2 7 6"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .8 3.4 2.8 4 6"/>',
    funds:    '<path d="M3 21h18M5 21V10l7-5 7 5v11"/><path d="M9 21v-6h6v6"/>',
    record:   '<path d="M3 3v18h18"/><path d="m7 14 4-4 3 3 5-6"/>',
    charts:   '<path d="M7 4v3M7 17v3M17 4v3M17 17v3"/><rect x="4.5" y="7" width="5" height="10" rx="1"/><rect x="14.5" y="7" width="5" height="10" rx="1"/>',
    flask:    '<path d="M9 3h6M10 3v6.5L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.5V3"/><path d="M7.5 15h9"/>',
    concalls: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/>',
    review:   '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 11l2 2 4-4M9 17h6"/>',
    watch:    '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3l-5.5 2.9 1-6.2L3 9.6l6.2-.9z"/>',
    allocate: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9M12 12l-6.4 6.4"/>',
    planner:  '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    adviser:  '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/>',
    search:   '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    pin:      '<path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v8"/>',
    arrow:    '<path d="M5 12h14M13 6l6 6-6 6"/>'
  };

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function finite(v) { return v != null && v !== '' && isFinite(Number(v)); }
  function inr(v, dp) {
    if (!finite(v)) return '—';
    return Number(v).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function pct(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2) + '%';
  }
  function tone(v) { return !finite(v) ? '' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'dn' : ''; }
  function svg(key, size) {
    return '<svg class="dr-ic" width="' + (size || 20) + '" height="' + (size || 20) +
      '" viewBox="0 0 24 24" aria-hidden="true">' + (ICON[key] || '') + '</svg>';
  }
  function still() {
    try {
      return document.documentElement.dataset.motion === 'off' ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) { return false; }
  }
  function readJSON(key, fallback) {
    try { var v = JSON.parse(localStorage.getItem(key)); return v == null ? fallback : v; }
    catch (e) { return fallback; }
  }

  /* Bounded, and a failure is a resolved null: one sleeping feed must never
     hold the page open. */
  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 12000);
    return fetch(API + path, ctl ? { signal: ctl.signal } : {})
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().then(function (j) { return r.ok ? j : null; });
      })
      .catch(function () { if (timer) clearTimeout(timer); return null; });
  }

  /* Count a whole number up to its value. Counts only — never a price. */
  function countUp(node, to) {
    if (!node) return;
    if (!finite(to)) { node.textContent = '—'; return; }
    to = Math.round(Number(to));
    if (still() || to <= 0) { node.textContent = inr(to, 0); return; }
    var t0 = null, dur = Math.min(1600, 500 + to * 12);
    function step(t) {
      if (t0 === null) t0 = t;
      var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      node.textContent = inr(Math.round(to * e), 0);
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function pins() { var p = readJSON(PIN_KEY, []); return Array.isArray(p) ? p.slice(0, 8) : []; }

  /* The tool's place in the map nav.js owns, for labels and routing. */
  function toolInfo(tabId) {
    var nav = window.AltahaNav;
    var secs = (nav && nav.sections) || [];
    for (var i = 0; i < secs.length; i++) {
      var all = secs[i].tabs.concat(secs[i].extras || []);
      for (var j = 0; j < all.length; j++) {
        if (all[j].id === tabId) return { section: secs[i].id, door: secs[i].label, tab: all[j] };
      }
    }
    return null;
  }

  /* ── Shared pieces of markup ─────────────────────────────────────────── */

  function head(title, question, extra) {
    return '<header class="dr-head dr-rise">' +
      '<div><h1 class="dr-title">' + esc(title) + '</h1>' +
      '<p class="dr-q">' + esc(question) + '</p></div>' + (extra || '') + '</header>';
  }

  /* A card that opens a tool. `body` is filled in later by its feed. */
  function toolCard(o, i) {
    return '<button type="button" class="dr-card dr-tool dr-rise" style="--i:' + i + '" data-goto="' +
      esc(o.goto) + '" id="' + esc(o.id) + '">' +
      '<span class="dr-sheen" aria-hidden="true"></span>' +
      '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg(o.icon) + '</span>' +
      (o.live ? '<span class="dr-livetag"><i class="dr-ping"></i>Live</span>' : '') + '</span>' +
      '<span class="dr-tool-name">' + esc(o.name) + '</span>' +
      '<span class="dr-tool-count"><b class="dr-n" data-count>—</b><small>' + esc(o.unit || '') + '</small></span>' +
      '<span class="dr-tool-line" data-line>' + esc(o.line) + '</span>' +
      '<span class="dr-tool-chips" data-chips></span>' +
      '</button>';
  }

  function fillTool(id, count, line, chips) {
    var card = $(id);
    if (!card) return;
    var n = card.querySelector('[data-count]');
    if (count === null || count === undefined) {
      card.querySelector('.dr-tool-count').classList.add('is-empty');
    } else {
      countUp(n, count);
    }
    if (line) card.querySelector('[data-line]').textContent = line;
    if (chips && chips.length) {
      card.querySelector('[data-chips]').innerHTML = chips.slice(0, 4).map(function (c) {
        return '<span class="dr-chip' + (c.tone ? ' ' + c.tone : '') + '">' + esc(c.text) + '</span>';
      }).join('');
    }
  }

  /* ════════════════════════════════════════════════════════════════════════
     TODAY
     ════════════════════════════════════════════════════════════════════════ */

  var T = { last: 0, market: null, week: null, sectors: null, chart: null, movers: 'up', clock: null, prevNifty: null,
            sector: null, sectorRows: [], nse: {}, wq: {}, wqAt: 0 };

  var TODAY_TOOLS = [
    { id: 'drt-live', goto: 'discover/live', icon: 'alerts', name: 'Alerts', unit: 'fired today', live: true,
      line: 'Unusual moves, as they happen.' },
    { id: 'drt-deals', goto: 'discover/deals', icon: 'deals', name: 'Big trades', unit: 'stocks with deals',
      line: 'Bulk and block deals.' },
    { id: 'drt-moneyflow', goto: 'discover/flows', icon: 'flows', name: 'Money flow', unit: 'sectors FPIs bought',
      line: 'FPI, FII and DII money, sector by sector.' },
    { id: 'drt-wow', goto: 'discover/wow', icon: 'wow', name: 'Order wins', unit: '',
      line: 'New orders, sized against the company.' },
    { id: 'drt-special', goto: 'discover/special', icon: 'delivery', name: 'Delivery trends', unit: 'delivery spikes',
      line: 'Where delivery ran above normal.' },
    { id: 'drt-results', goto: 'discover/results', icon: 'results', name: 'Results calendar', unit: 'today',
      line: 'Who reports this week.' },
    { id: 'drt-filings', goto: 'discover/filings', icon: 'filings', name: 'Filings & news', unit: 'filings in the feed', live: true,
      line: 'Company announcements, live.' },
    { id: 'drt-options', goto: 'discover/options', icon: 'options', name: 'Options', unit: '',
      line: 'Option chains and open interest.' }
  ];

  function todayShell() {
    var session =
      '<div class="dr-session" aria-live="off">' +
        '<div class="dr-session-top"><span class="dr-state" id="drt-state">Market</span>' +
        '<span class="dr-clock" id="drt-clock"></span></div>' +
        '<div class="dr-sbar"><i id="drt-sbar"></i></div>' +
        '<div class="dr-sticks"><span>9:15</span><span>12:00</span><span>15:30</span></div>' +
      '</div>';
    return '<div class="dr dr-today">' +
      head('Market', 'What is happening today?', session) +
      startHTML() +
      '<div class="dr-grid">' +
        '<div class="dr-main">' +
          '<section class="dr-hero dr-rise" style="--i:1" aria-label="The market now">' +
            '<div class="dr-hero-l">' +
              '<span class="dr-kick"><i class="dr-ping"></i>NIFTY 50</span>' +
              '<div class="dr-big"><span class="dr-level" id="drt-level">—</span>' +
              '<span class="dr-pill" id="drt-pill">—</span></div>' +
              '<div class="dr-chart" id="drt-chart"><p class="dr-quiet">Reading three months of the index…</p></div>' +
              '<div class="dr-axis" id="drt-axis"></div>' +
            '</div>' +
            '<div class="dr-hero-r">' +
              '<div class="dr-idx" id="drt-idx"></div>' +
              '<div class="dr-breadth" id="drt-breadth"></div>' +
              '<div class="dr-flows" id="drt-flows"></div>' +
            '</div>' +
          '</section>' +
          '<section class="dr-sec dr-rise" style="--i:2">' +
            '<div class="dr-sec-h"><h2>Sector performance</h2><span>Colour is today’s move · tap one to see its stocks</span></div>' +
            '<div class="dr-heat" id="drt-heat"><p class="dr-quiet">Reading the sectors…</p></div>' +
            '<div class="dr-secpanel" id="drt-secpanel" role="region" tabindex="-1" hidden></div>' +
          '</section>' +
          '<section class="dr-sec">' +
            '<div class="dr-sec-h dr-rise" style="--i:3"><h2>More tools for today’s market</h2><span>Tap a card to open the tool</span></div>' +
            '<div class="dr-cards">' + TODAY_TOOLS.map(function (t, i) { return toolCard(t, i + 4); }).join('') + '</div>' +
          '</section>' +
        '</div>' +
        '<aside class="dr-aside">' +
          deskHTML() +
          '<section class="dr-card dr-movers dr-rise" style="--i:5" aria-label="Top movers">' +
            '<div class="dr-card-h"><h2>Top movers</h2>' +
              '<div class="dr-seg" role="tablist" aria-label="Gainers or losers">' +
                '<span class="dr-seg-ind" id="drt-segind" aria-hidden="true"></span>' +
                '<button type="button" role="tab" data-movers="up" aria-selected="true">Gainers</button>' +
                '<button type="button" role="tab" data-movers="dn" aria-selected="false">Losers</button>' +
              '</div></div>' +
            '<div id="drt-movers"><p class="dr-quiet">Reading the heavyweights…</p></div>' +
            '<p class="dr-fine">Among tracked large companies.</p>' +
          '</section>' +
          '<section class="dr-card dr-heads dr-rise" style="--i:6" aria-label="Headlines">' +
            '<div class="dr-card-h"><h2>Headlines</h2><button type="button" class="dr-link" data-goto="discover/filings">Filings ›</button></div>' +
            '<div id="drt-heads"><p class="dr-quiet">Reading the press…</p></div>' +
          '</section>' +
        '</aside>' +
      '</div>' +
      '<p class="dr-disc">Observations, not recommendations.</p>' +
    '</div>';
  }

  /* ── Start here ───────────────────────────────────────────────────────
     People who were sent a link to this site said it was too complex to
     find their way around. The first screen was a market dashboard — index
     levels, FII/DII flows, eight tool cards — with nothing saying what the
     site does or where to begin. This strip says it in one sentence and
     offers the three things people actually come to do, each one tap away.
     It stays until the reader hides it, and stays hidden after that. */

  var START_KEY = 'altaha-start-hidden-v1';
  var START_TRY = [['RELIANCE', 'Reliance'], ['TCS', 'TCS'], ['HDFCBANK', 'HDFC Bank'], ['INFY', 'Infosys']];

  function startHidden() {
    try { return localStorage.getItem(START_KEY) === '1'; } catch (e) { return false; }
  }

  function startHTML() {
    if (startHidden()) return '';
    var task = function (attrs, icon, title, line) {
      return '<button type="button" class="dr-task" ' + attrs + '>' +
        '<span class="dr-task-ic">' + svg(icon, 22) + '</span>' +
        '<span class="dr-task-t"><b>' + esc(title) + '</b><small>' + esc(line) + '</small></span>' +
        '<span class="dr-task-go" aria-hidden="true">' + svg('arrow', 16) + '</span></button>';
    };
    return '<section class="dr-start dr-rise" style="--i:1" id="dr-start" aria-labelledby="dr-start-h">' +
      '<div class="dr-start-top">' +
        '<div><h2 id="dr-start-h">New here? Start with one of these.</h2>' +
        '<p>Altaha scores any stock from 0 to 100, and ranks stocks on measured figures in lists held for a few weeks to a year.</p></div>' +
        '<button type="button" class="dr-start-x" id="dr-start-x">Hide this</button>' +
      '</div>' +
      '<div class="dr-tasks">' +
        task('data-start="search"', 'search', 'Check a stock', 'Its score, and why.') +
        task('data-goto="research/ideas"', 'converge', 'Get stock picks', 'For a few weeks, a few months or a year.') +
        task('data-goto="portfolio/portfolio"', 'review', 'Check my portfolio', 'A clear call on each holding.') +
      '</div>' +
      '<p class="dr-start-try"><span>Try one:</span>' +
        START_TRY.map(function (t) {
          return '<a href="stock.html?ticker=' + encodeURIComponent(t[0]) + '">' + esc(t[1]) + '</a>';
        }).join('') +
        '<button type="button" class="dr-link" data-goto="me/score">How the score works ›</button>' +
      '</p>' +
    '</section>';
  }

  function wireStart() {
    var box = $('dr-start');
    if (!box || box._wired) return;
    box._wired = true;
    box.addEventListener('click', function (e) {
      if (e.target.closest('#dr-start-x')) {
        try { localStorage.setItem(START_KEY, '1'); } catch (err) {}
        if (box.parentNode) box.parentNode.removeChild(box);
        var q = document.getElementById('sh-q');
        if (q) q.focus();
        return;
      }
      if (e.target.closest('[data-start="search"]')) {
        if (window.AltahaShell && window.AltahaShell.focusSearch) window.AltahaShell.focusSearch();
        else { var i = document.getElementById('sh-q'); if (i) i.focus(); }
      }
    });
  }

  function deskHTML() {
    return '<section class="dr-card dr-desk dr-rise" style="--i:4" aria-label="Your desk">' +
      '<h2 class="dr-label">Your desk</h2>' +
      '<div id="dr-desk-pf"></div>' +
      '<div class="dr-desk-block"><div class="dr-desk-h"><b>Watchlist</b><button type="button" class="dr-link" id="dr-desk-watchopen">Open ›</button></div>' +
      '<div id="dr-desk-watch"></div></div>' +
      '<div class="dr-desk-block"><div class="dr-desk-h"><b>Pinned by you</b></div><div class="dr-pins" id="dr-desk-pins"></div></div>' +
    '</section>';
  }

  function paintDesk(quotes) {
    var pf = $('dr-desk-pf');
    if (pf) {
      var n = portfolioCount();
      pf.innerHTML = '<button type="button" class="dr-deskpf" data-goto="portfolio/portfolio">' +
        '<span class="dr-sheen dark" aria-hidden="true"></span>' +
        '<span class="dr-deskpf-ic">' + svg('review', 22) + '</span>' +
        '<span><b>' + (n ? 'Your portfolio' : 'Review your portfolio') + '</b>' +
        '<small>' + (n ? n + ' holding' + (n === 1 ? '' : 's') + ' saved · get your plan ›'
                       : 'Add what you own and get a call on each ›') + '</small></span></button>';
    }
    var w = $('dr-desk-watch');
    if (w) {
      var rows = readJSON(WATCH_KEY, []);
      rows = Array.isArray(rows) ? rows : [];
      if (!rows.length) {
        w.innerHTML = '<p class="dr-quiet">Tap ☆ on a stock to follow it.</p>';
      } else {
        var missing = [];
        w.innerHTML = deskSymbols(rows).map(function (sym) {
          // The watchlist's own read first: the sector feed covers the large
          // names only, so a small cap would otherwise show no price at all.
          var q = T.wq[sym] || (quotes || {})[sym];
          var has = q && finite(q.ltp);
          if (!has) missing.push(sym);
          var amt = q ? dayChange(q) : null;
          var t = q ? tone(finite(q.change_pct) ? q.change_pct : amt) : '';
          var label = esc(sym) + (has ? ', ' + inr(q.ltp, 2) + ' rupees' +
            (finite(q.change_pct) ? ', ' + pct(q.change_pct) + ' today' : '') : '');
          return '<a class="dr-wrow" href="stock.html?ticker=' + encodeURIComponent(sym) + '" aria-label="' + label + '">' +
            '<span class="dr-wsym">' + esc(sym) + '</span>' +
            '<span class="dr-wpx">' + (has ? '₹' + inr(q.ltp, 2) : (T.wqBusy ? '<i class="dr-wwait" aria-hidden="true"></i>' : '—')) + '</span>' +
            '<span class="dr-wchg ' + t + '">' +
              (has && finite(q.change_pct) ? '<b>' + pct(q.change_pct) + '</b>' : '') +
              (has && finite(amt) ? '<small>' + (amt > 0 ? '+' : amt < 0 ? '−' : '') + '₹' + inr(Math.abs(amt), 2) + '</small>' : '') +
            '</span></a>';
        }).join('');
        if (missing.length && !T.wqBusy && Date.now() - T.wqAt > 30000) loadDeskQuotes(missing);
      }
    }
    var p = $('dr-desk-pins');
    if (p) {
      var list = pins().map(toolInfo).filter(Boolean);
      p.innerHTML = list.length ? list.map(function (t) {
        return '<button type="button" class="dr-pinchip" data-goto="' + esc(t.section + '/' + t.tab.id) + '">' +
          svg('pin', 14) + esc(t.tab.label) + '</button>';
      }).join('') : '<p class="dr-quiet">Pin a tool to keep it here.</p>';
    }
  }

  function deskSymbols(rows) {
    if (!rows) { rows = readJSON(WATCH_KEY, []); rows = Array.isArray(rows) ? rows : []; }
    return rows.slice(0, 6).map(function (r) { return String((r && r.symbol) || r).toUpperCase(); })
      .filter(function (s) { return /^[A-Z0-9][A-Z0-9.&^=_-]{0,29}$/.test(s); });
  }

  /* Today's move in rupees: the feed's own figure, else price less the
     previous close. */
  function dayChange(q) {
    if (finite(q.change)) return Number(q.change);
    if (finite(q.ltp) && finite(q.prev_close)) return Number(q.ltp) - Number(q.prev_close);
    if (finite(q.ltp) && finite(q.change_pct) && Number(q.change_pct) !== -100) {
      var p = Number(q.change_pct);
      return Number(q.ltp) - Number(q.ltp) / (1 + p / 100);
    }
    return null;
  }

  /* Price and today's move for the desk's names, from the same read the
     Watchlist page uses. Names the server has not fetched yet come back in
     `pending`; they are asked for again a few times. */
  function loadDeskQuotes(syms, tries) {
    syms = syms || deskSymbols();
    if (!syms.length || T.wqBusy) return;
    T.wqBusy = true;
    get('/watchlist/quotes?symbols=' + encodeURIComponent(syms.join(',')), 30000).then(function (d) {
      T.wqBusy = false;
      T.wqAt = Date.now();
      ((d && d.rows) || []).forEach(function (r) { if (r && r.symbol) T.wq[String(r.symbol).toUpperCase()] = r; });
      paintDesk(T.quotes);
      var pend = (d && d.pending) || [];
      if (pend.length && (tries || 0) < 4) {
        setTimeout(function () { loadDeskQuotes(pend, (tries || 0) + 1); }, 2000);
      }
    });
  }

  function portfolioCount() {
    var draft = readJSON(DRAFT_KEY, null);
    var n = draft && Array.isArray(draft.rows) ? draft.rows.filter(function (r) { return r && r.symbol; }).length : 0;
    if (n) return n;
    var store = readJSON(STORE_KEY, {});
    // A portfolio named while signed in is that account's (portfolio.js,
    // offered): it is not counted for anybody else.
    var user = window.AltahaAuth && window.AltahaAuth.user && window.AltahaAuth.user();
    var who = (user && user.email) || '';
    var names = store && typeof store === 'object' ? Object.keys(store).filter(function (n) {
      return !(store[n] && store[n].owner) || store[n].owner === who;
    }) : [];
    if (!names.length) return 0;
    var first = store[names[0]];
    var rows = (first && (first.rows || first.holdings)) || (Array.isArray(first) ? first : []);
    return Array.isArray(rows) ? rows.length : 0;
  }

  /* ── The hero: index levels, chart, breadth, flows ────────────────────── */

  function paintIndices(m) {
    var idx = (m && m.indices) || [];
    var nifty = idx.filter(function (i) { return /NIFTY 50/i.test(i.label); })[0];
    var lvl = $('drt-level'), pill = $('drt-pill');
    if (nifty && lvl) {
      var prev = T.prevNifty;
      lvl.textContent = inr(nifty.level, 2);
      if (prev !== null && prev !== nifty.level) {
        lvl.classList.remove('flash-up', 'flash-dn');
        void lvl.offsetWidth;
        lvl.classList.add(nifty.level > prev ? 'flash-up' : 'flash-dn');
      }
      T.prevNifty = nifty.level;
      pill.className = 'dr-pill ' + tone(nifty.change_pct);
      pill.textContent = (nifty.change_pct > 0 ? '▲ ' : nifty.change_pct < 0 ? '▼ ' : '') +
        (finite(nifty.change) ? (nifty.change > 0 ? '+' : '') + inr(nifty.change, 2) + ' ' : '') + '(' + pct(nifty.change_pct) + ')';
    } else if (lvl) {
      lvl.textContent = '—';
      pill.textContent = 'Index levels unavailable right now';
      pill.className = 'dr-pill';
    }
    var host = $('drt-idx');
    if (host) {
      var others = idx.filter(function (i) { return !/NIFTY 50/i.test(i.label); });
      host.innerHTML = others.length ? others.map(function (i, k) {
        // A rising VIX is a market getting more nervous, so its colour runs the
        // other way to a price's.
        var vix = /VIX/i.test(i.label);
        var t = vix ? tone(-(i.change_pct || 0)) : tone(i.change_pct);
        // The arrow follows the sign of the number, whatever its colour.
        var c = Number(i.change_pct);
        var arrow = !finite(i.change_pct) || !c ? '' :
          '<span class="dr-ix-a" aria-hidden="true">' + (c > 0 ? '▲' : '▼') + '\u00A0</span>';
        return '<div class="dr-ix dr-rise" style="--i:' + (k + 2) + '">' +
          '<span class="dr-ix-n">' + esc(i.label) + '</span>' +
          '<span class="dr-ix-v">' + inr(i.level, 2) + '</span>' +
          weekSpark(i.label, t) +
          '<span class="dr-ix-c ' + t + '">' + arrow + pct(i.change_pct) + '</span></div>';
      }).join('') : '';
    }
    var st = $('drt-state');
    if (st && m) {
      var open = m.status === 'open';
      st.textContent = open ? 'Market open' : m.status === 'pre' ? 'Pre-open' : 'Market closed';
      st.classList.toggle('on', open);
    }
  }

  /* Five sessions of closes from /market/week, as a sparkline per index. */
  function weekSpark(label, t) {
    var s = (T.week && T.week.sessions) || [];
    var vals = s.map(function (d) { return ((d.indices || {})[label] || {}).close; }).filter(finite);
    if (vals.length < 2) return '<span class="dr-ix-s"></span>';
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals), rg = (mx - mn) || 1;
    var pts = vals.map(function (v, i) {
      return (i / (vals.length - 1) * 64).toFixed(1) + ',' + (3 + (1 - (v - mn) / rg) * 18).toFixed(1);
    }).join(' ');
    return '<svg class="dr-ix-s ' + t + '" viewBox="0 0 64 24" aria-hidden="true"><polyline class="dr-draw" pathLength="1" points="' + pts + '"/></svg>';
  }

  function paintChart(d) {
    var host = $('drt-chart'), axis = $('drt-axis');
    if (!host) return;
    var rows = (d && d.candles) || [];
    var closes = rows.map(function (r) { return { t: r[0], c: r[4] }; }).filter(function (r) { return finite(r.c); });
    if (closes.length < 5) {
      host.innerHTML = '<p class="dr-quiet">The index chart could not be read just now.</p>';
      if (axis) axis.innerHTML = '';
      return;
    }
    var W = 640, H = 200, vals = closes.map(function (r) { return r.c; });
    var prev = vals[vals.length - 2];
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals), rg = (mx - mn) || 1;
    function Y(v) { return 12 + (1 - (v - mn) / rg) * (H - 24); }
    var pts = vals.map(function (v, i) { return [i / (vals.length - 1) * W, Y(v)]; });
    var line = 'M' + pts.map(function (p) { return p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' L');
    var last = pts[pts.length - 1];
    var up = vals[vals.length - 1] >= vals[0];
    host.innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<line class="dr-prevline" x1="0" x2="' + W + '" y1="' + Y(prev).toFixed(1) + '" y2="' + Y(prev).toFixed(1) + '"/>' +
        '<path class="dr-area" d="' + line + ' L' + W + ' ' + H + ' L0 ' + H + ' Z"/>' +
        '<path class="dr-line dr-draw" pathLength="1" d="' + line + '"/>' +
      '</svg>' +
      '<span class="dr-dot" style="left:' + (last[0] / W * 100).toFixed(2) + '%;top:' + (last[1] / H * 100).toFixed(2) + '%"></span>' +
      '<span class="dr-chart-cap">3 months · ' + (up ? 'higher' : 'lower') + ' than ' + closes.length + ' sessions ago</span>';
    if (axis) {
      var fmt = function (t) {
        try { return new Date(t * 1000).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }); }
        catch (e) { return ''; }
      };
      var mid = closes[Math.floor(closes.length / 2)];
      axis.innerHTML = '<span>' + fmt(closes[0].t) + '</span><span>' + fmt(mid.t) + '</span><span>' + fmt(closes[closes.length - 1].t) + '</span>';
    }
  }

  function paintFlows() {
    var host = $('drt-flows');
    if (!host) return;
    var s = ((T.week && T.week.sessions) || []).filter(function (d) { return d.flows; });
    var day = s[s.length - 1];
    if (!day) { host.innerHTML = ''; return; }
    var fii = ((day.flows || {}).fii || {}).net, dii = ((day.flows || {}).dii || {}).net;
    if (!finite(fii) && !finite(dii)) { host.innerHTML = ''; return; }
    var big = Math.max(Math.abs(fii || 0), Math.abs(dii || 0)) || 1;
    function row(name, v, k) {
      var w = finite(v) ? Math.max(4, Math.abs(v) / big * 100) : 0;
      return '<div class="dr-flow"><span>' + name + '</span>' +
        '<span class="dr-flow-bar"><i class="' + tone(v) + '" style="width:' + w.toFixed(1) + '%;animation-delay:' + (500 + k * 200) + 'ms"></i></span>' +
        '<b class="' + tone(v) + '">' + (finite(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + inr(Math.abs(v), 0) : '—') + '</b></div>';
    }
    host.innerHTML = '<span class="dr-label light">FII / DII · ' + esc(day.label || day.date) + ' · ₹ crore</span>' +
      row('FII', fii, 0) + row('DII', dii, 1);
  }

  /* ── Sectors, breadth and movers, from one /sector/overview read ─────── */

  function paintSectors(d) {
    var rows = (d && d.rows) || [];
    var heat = $('drt-heat');
    if (heat) {
      if (!rows.length) {
        heat.innerHTML = '<p class="dr-quiet">Sector data is not available right now.</p>';
      } else {
        heat.innerHTML = rows.map(function (r, i) {
          var c = Number(r.change_pct) || 0, a = Math.min(1, Math.abs(c) / 2.4);
          /* The tile is the card surface tinted toward gain or loss by how far
             the sector moved: at most 22%, so the ink on it always reads. */
          var heat = Math.round(a * 22);
          return '<button type="button" class="dr-tile" data-sector="' + esc(r.sector) +
            '" aria-expanded="false" aria-controls="drt-secpanel" style="--i:' + i +
            ';--heat:' + heat + ';--tone:var(' + (c >= 0 ? '--gain' : '--loss') + ')">' +
            '<span>' + esc(r.sector) + '</span><b class="' + tone(r.change_pct) + '">' + pct(r.change_pct) + '</b>' +
            (finite(r.up) && finite(r.total) ? '<small>' + r.up + ' of ' + r.total + ' up</small>' : '') + '</button>';
        }).join('');
      }
    }
    // The open sector's stocks follow the same read the tiles were drawn from.
    T.sectorRows = rows;
    paintSectorPanel();
    if (T.sector) loadSectorIndex(T.sector);
    var up = 0, dn = 0;
    rows.forEach(function (r) { up += Number(r.up) || 0; dn += Number(r.down) || 0; });
    var b = $('drt-breadth');
    if (b) {
      b.innerHTML = (up + dn) ? '<div class="dr-breadth-t"><span>Rising <b class="up">' + up + '</b></span>' +
        '<span>Falling <b class="dn">' + dn + '</b></span></div>' +
        '<div class="dr-breadth-bar"><i style="width:' + (up / (up + dn) * 100).toFixed(1) + '%"></i></div>' : '';
    }
    var stocks = [], seen = {};
    rows.forEach(function (r) {
      (r.stocks || []).forEach(function (s) {
        if (!s.symbol || seen[s.symbol] || !finite(s.change_pct)) return;
        seen[s.symbol] = 1;
        stocks.push(s);
      });
    });
    T.quotes = {};
    stocks.forEach(function (s) { T.quotes[s.symbol] = s; });
    stocks.sort(function (a, b2) { return b2.change_pct - a.change_pct; });
    T.stocks = stocks;
    paintMovers();
    paintDesk(T.quotes);
  }

  /* ── A sector's stocks, opened where the tile is ──────────────────────
     Tapping a sector used to leave Market for the market board and ask it to
     open the sector there. The board names its tiles after NSE indices
     ("Nifty Realty"), not sectors ("Real Estate"), so nothing opened: the
     reader was moved to another page and shown no stocks.

     The stocks open under the tiles instead, and the reader stays on Market.
     The first list is the one the tile's own number is the average of; it
     arrived with the tiles, so it is on screen at once. Where NSE publishes
     an index for the sector, the rest of that index's members are read from
     the exchange (/index/performance) and added below it. They are added
     below, never merged in, so a row the reader is about to tap does not
     move when the second read lands. */

  var SECTOR_NSE = {
    'Technology':             { id: 'NIFTY IT', name: 'Nifty IT' },
    'Financial Services':     { id: 'NIFTY FINANCIAL SERVICES', name: 'Nifty Financial Services' },
    'Healthcare':             { id: 'NIFTY HEALTHCARE INDEX', name: 'Nifty Healthcare' },
    'Consumer Defensive':     { id: 'NIFTY FMCG', name: 'Nifty FMCG' },
    'Consumer Cyclical':      { id: 'NIFTY AUTO', name: 'Nifty Auto' },
    'Basic Materials':        { id: 'NIFTY METAL', name: 'Nifty Metal' },
    'Energy':                 { id: 'NIFTY ENERGY', name: 'Nifty Energy' },
    'Real Estate':            { id: 'NIFTY REALTY', name: 'Nifty Realty' },
    'Communication Services': { id: 'NIFTY MEDIA', name: 'Nifty Media' }
  };
  var NSE_FRESH_MS = 55000;

  function sectorRow(name) {
    var rows = T.sectorRows || [];
    for (var i = 0; i < rows.length; i++) if (rows[i].sector === name) return rows[i];
    return null;
  }

  function sectorTile(name) {
    var tiles = document.querySelectorAll('#drt-heat .dr-tile');
    for (var i = 0; i < tiles.length; i++) if (tiles[i].dataset.sector === name) return tiles[i];
    return null;
  }

  /* Best first; a stock with no change to show goes last, not to the middle. */
  function byChange(a, b) {
    var x = finite(a.change_pct) ? Number(a.change_pct) : -Infinity;
    var y = finite(b.change_pct) ? Number(b.change_pct) : -Infinity;
    return y === x ? String(a.symbol).localeCompare(String(b.symbol)) : y - x;
  }

  function stockList(list) {
    return '<ul class="dr-slist">' + list.map(function (s) {
      return '<li><a href="stock.html?ticker=' + encodeURIComponent(s.symbol) + '">' +
        '<span class="dr-msym">' + esc(s.symbol) + '</span>' +
        '<span class="dr-mpx">' + (finite(s.ltp) ? inr(s.ltp, 2) : '') + '</span>' +
        '<span class="dr-mchg ' + tone(s.change_pct) + '">' + pct(s.change_pct) + '</span></a></li>';
    }).join('') + '</ul>';
  }

  function paintSectorPanel() {
    var host = $('drt-secpanel');
    if (!host) return;
    var name = T.sector, r = name ? sectorRow(name) : null;
    var tiles = document.querySelectorAll('#drt-heat .dr-tile');
    for (var i = 0; i < tiles.length; i++) {
      var on = !!r && tiles[i].dataset.sector === name;
      tiles[i].classList.toggle('is-open', on);
      tiles[i].setAttribute('aria-expanded', on ? 'true' : 'false');
    }
    if (!r) {
      T.sector = null;
      host.hidden = true;
      host.innerHTML = '';
      return;
    }

    var seen = {};
    var own = (r.stocks || []).filter(function (s) {
      if (!s || !s.symbol || seen[s.symbol]) return false;
      seen[s.symbol] = 1;
      return true;
    }).sort(byChange);
    var ix = SECTOR_NSE[name], hit = ix ? T.nse[ix.id] : null, more = [];
    if (hit && hit.stocks) {
      Object.keys(hit.stocks).forEach(function (sym) {
        if (seen[sym]) return;
        var q = hit.stocks[sym] || {};
        more.push({ symbol: sym, ltp: q.price, change_pct: q.change_pct });
      });
      more.sort(byChange);
    }

    var facts = [];
    if (finite(r.change_pct)) facts.push('<b class="' + tone(r.change_pct) + '">' + pct(r.change_pct) + '</b> today');
    if (finite(r.up) && finite(r.total)) facts.push(r.up + ' of ' + r.total + ' up');
    var html = '<div class="dr-secpanel-h"><div><h3>' + esc(name) + ' stocks</h3>' +
      (facts.length ? '<p>' + facts.join(' · ') + '</p>' : '') + '</div>' +
      '<button type="button" class="dr-secpanel-x" id="drt-secpanel-x" aria-label="Close ' + esc(name) + ' stocks">Close</button></div>';
    if (own.length) {
      html += '<p class="dr-secpanel-cap">The sector’s move today is the average of ' +
        (own.length === 1 ? 'this stock' : 'these ' + own.length + ' stocks') + '.</p>' + stockList(own);
    }
    if (more.length) {
      html += '<p class="dr-secpanel-cap">' + (own.length ? 'More in' : 'In') + ' NSE’s ' + esc(ix.name) + ' index</p>' + stockList(more);
    } else if (hit && hit.loading) {
      html += '<p class="dr-quiet dr-secpanel-note">Reading ' + (own.length ? 'the rest of ' : '') + esc(ix.name) + ' from NSE…</p>';
    } else if (!own.length) {
      html += '<p class="dr-quiet dr-secpanel-note">Stock quotes for this sector are not available right now.</p>';
    }

    // A refresh redraws the list; whoever was on a row stays on that row.
    var active = host.contains(document.activeElement) ? document.activeElement : null;
    var href = active && active.getAttribute('href'), onClose = !!active && active.id === 'drt-secpanel-x';
    host.setAttribute('aria-label', name + ' stocks');
    host.innerHTML = html;
    host.hidden = false;
    if (onClose) {
      $('drt-secpanel-x').focus({ preventScroll: true });
    } else if (href) {
      var links = host.querySelectorAll('a');
      for (var k = 0; k < links.length; k++) {
        if (links[k].getAttribute('href') === href) { links[k].focus({ preventScroll: true }); break; }
      }
    }
  }

  /* The rest of the sector's NSE index. A failure leaves the first list
     standing and is tried again on the next refresh, not in a loop. */
  function loadSectorIndex(name) {
    var ix = SECTOR_NSE[name];
    if (!ix) return;
    var hit = T.nse[ix.id];
    if (hit && (hit.loading || Date.now() - hit.at < NSE_FRESH_MS)) return;
    T.nse[ix.id] = { at: hit ? hit.at : 0, stocks: hit ? hit.stocks : null, loading: true };
    get('/index/performance?index=' + encodeURIComponent(ix.id) + '&window=1D', 20000).then(function (d) {
      var stocks = d && d.stocks && Object.keys(d.stocks).length ? d.stocks : null;
      var was = T.nse[ix.id] || {};
      T.nse[ix.id] = { at: Date.now(), stocks: stocks || was.stocks || null, loading: false };
      if (T.sector === name) paintSectorPanel();
    });
  }

  function closeSector() {
    var name = T.sector;
    if (!name) return;
    T.sector = null;
    paintSectorPanel();
    var tile = sectorTile(name);
    if (tile) tile.focus({ preventScroll: true });
  }

  function toggleSector(name) {
    if (T.sector === name) { closeSector(); return; }
    T.sector = name;
    loadSectorIndex(name);
    paintSectorPanel();
    var host = $('drt-secpanel');
    if (!host || host.hidden) return;
    // Focus goes to the list so a keyboard or screen reader lands on the
    // stocks, not on the ten tiles between the one pressed and the list.
    host.focus({ preventScroll: true });
    host.scrollIntoView({ block: 'nearest', behavior: still() ? 'auto' : 'smooth' });
  }

  function paintMovers() {
    var host = $('drt-movers');
    if (!host) return;
    var s = T.stocks || [];
    if (!s.length) { host.innerHTML = '<p class="dr-quiet">Live quotes are not available right now.</p>'; return; }
    var list = T.movers === 'up' ? s.slice(0, 6) : s.slice(-6).reverse();
    host.innerHTML = '<ol class="dr-mlist">' + list.map(function (x, i) {
      return '<li style="--i:' + i + '"><a href="stock.html?ticker=' + encodeURIComponent(x.symbol) + '">' +
        '<span class="dr-msym">' + esc(x.symbol) + '</span>' +
        '<span class="dr-mpx">' + (finite(x.ltp) ? inr(x.ltp, 2) : '') + '</span>' +
        '<span class="dr-mchg ' + tone(x.change_pct) + '">' + pct(x.change_pct) + '</span></a></li>';
    }).join('') + '</ol>';
    var ind = $('drt-segind');
    if (ind) ind.style.transform = T.movers === 'up' ? 'translateX(0)' : 'translateX(100%)';
    document.querySelectorAll('[data-movers]').forEach(function (b) {
      b.setAttribute('aria-selected', b.dataset.movers === T.movers ? 'true' : 'false');
    });
  }

  /* Where a headline goes. The feed calls the story's address `link`. This
     card read `url`, which the feed has never sent, so every headline was a
     link to "#": it underlined on hover and went nowhere. `url` is still
     accepted, in case a source ever arrives under that name.

     Only an http(s) address becomes a link. The text is other people's RSS,
     and escaping it does not stop a "javascript:" address from being one. */
  function storyHref(l) {
    var u = String((l && (l.link || l.url)) || '').trim();
    return /^https?:\/\//i.test(u) ? u : '';
  }

  function paintHeads(d) {
    var host = $('drt-heads');
    if (!host) return;
    var cs = ((d && d.clusters) || []).map(function (c) { return c.lead || {}; }).filter(function (l) { return l.title; });
    host.innerHTML = cs.length ? '<ul class="dr-hlist">' + cs.slice(0, 5).map(function (l, i) {
      var href = storyHref(l);
      // A headline with nowhere to go is text, not a link that does nothing.
      return '<li style="--i:' + i + '">' + (href
        ? '<a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(l.title) + '</a>'
        : '<span>' + esc(l.title) + '</span>') +
        '<small>' + esc(l.publication || '') + '</small></li>';
    }).join('') + '</ul>' : '<p class="dr-quiet">No headlines right now.</p>';
  }

  /* ── The tool cards' live numbers ─────────────────────────────────────── */

  function todayCounts() {
    get('/intraday/status', 9000).then(function (d) {
      if (!d) return fillTool('drt-live', null, 'The scanner could not be reached just now.');
      // A break both lanes called is one call: skip Select's record of one Classic already made.
      var a = (d.alerts_today || []).filter(function (x) { return !(x.engine === 'select' && x.pair_time); });
      fillTool('drt-live', a.length, d.market_open ? 'Watching ' + (d.watchlist_size || 0) + ' names right now.'
        : 'Market closed.',
        a.slice(-4).reverse().map(function (x) { return { text: x.symbol }; }));
    });
    get('/deals?limit=6', 15000).then(function (d) {
      if (!d || d.available === false) return fillTool('drt-deals', null, (d && d.message) || 'The deals feed is unavailable today.');
      fillTool('drt-deals', d.total_symbols != null ? d.total_symbols : (d.symbols || []).length, null,
        (d.symbols || []).slice(0, 4).map(function (r) { return { text: r.symbol, tone: tone(r.net_cr) }; }));
    });
    // A few figures, not the page: /moneyflow itself is fetched when its tab opens.
    get('/moneyflow/brief', 15000).then(function (d) {
      if (!d || d.available === false) return fillTool('drt-moneyflow', null, (d && d.message) || 'FPI, FII and DII money, sector by sector.');
      fillTool('drt-moneyflow', d.inflow_sectors, d.line,
        (d.top || []).slice(0, 4).map(function (r) { return { text: r.short, tone: r.direction === 'inflow' ? 'up' : r.direction === 'outflow' ? 'dn' : '' }; }));
    });
    // Order wins are read out of each filing's PDF on the server, so nothing
    // asks for them until their own tab is opened (filings-views-browser
    // pins this). The card says what the tool does instead of a count.
    fillTool('drt-wow', null);
    // The count is the latest session's spikes, not the size of the one-year
    // book: that was always 6 here, because 6 is what this asked for.
    get('/delivery/trends?limit=6', 20000).then(function (d) {
      var t = d && d.views && d.views.today;
      if (!d || d.available === false || !t) {
        return fillTool('drt-special', null, (d && (d.message || d.detail)) || 'The delivery record is not deep enough to read yet.');
      }
      fillTool('drt-special', t.total, t.total ? t.up + ' on a rise, ' + t.down + ' on a fall.' : 'Nothing unusual in the latest session.',
        (t.rows || []).slice(0, 4).map(function (r) { return { text: r.symbol, tone: tone(r.chg_pct) }; }));
    });
    get('/results/calendar', 15000).then(function (d) {
      if (!d || !d.available) return fillTool('drt-results', null, (d && d.message) || 'NSE’s calendar could not be read just now.');
      var day = (d.days || []).filter(function (x) { return x.date === d.today; })[0];
      var week = (d.days || []).reduce(function (n, x) { return n + (x.declared || 0) + (x.pending || 0); }, 0);
      fillTool('drt-results', day ? (day.declared || 0) + (day.pending || 0) : 0,
        week + ' companies report this week.',
        day ? (day.rows || []).slice(0, 4).map(function (r) { return { text: r.symbol, tone: r.status === 'declared' ? 'up' : '' }; }) : []);
    });
    get('/announcements?limit=60&min_importance=medium', 12000).then(function (d) {
      if (!d) return fillTool('drt-filings', null, 'The filings feed could not be reached.');
      var rows = d.rows || [];
      fillTool('drt-filings', d.count != null ? d.count : rows.length, null,
        rows.slice(0, 4).map(function (r) { return { text: r.symbol }; }).filter(function (c) { return c.text; }));
    });
    fillTool('drt-options', null);
  }

  function openToday(force) {
    var v = $('view-today');
    if (!v) return;
    var now = Date.now();
    if (!v.firstChild) v.innerHTML = todayShell();
    wireStart();
    paintDesk(T.quotes);
    startClock();
    if (!force && T.last && now - T.last < FRESH_MS) return;
    T.last = now;
    loadDeskQuotes();
    // The header already reads /market and /sector/overview for its ticker
    // and announces them; use that read when it is in, and fetch only if not.
    var shared = window.AltahaShell && window.AltahaShell.market;
    if (shared && shared.indices && shared.indices.length) {
      T.market = { indices: shared.indices, status: shared.status };
      paintIndices(T.market);
      if (shared.sectors) paintSectors(shared.sectors);
    } else {
      get('/market', 9000).then(function (d) { T.market = d; paintIndices(d); });
      get('/sector/overview?window=1D&stocks=1', 12000).then(paintSectors);
    }
    get('/market', 9000).then(function (d) { if (d) { T.market = d; paintIndices(d); } });
    get('/market/week', 15000).then(function (d) { T.week = d; paintFlows(); if (T.market) paintIndices(T.market); });
    get('/chart?ticker=%5ENSEI&range=3M', 20000).then(paintChart);
    get('/social/news/feed?limit=8&sort=latest', 11000).then(paintHeads);
    todayCounts();
  }

  /* The trading-session clock, IST, once a second while Market is on screen. */
  function startClock() {
    if (T.clock) return;
    function tick() {
      var v = $('view-today');
      if (!v || v.style.display === 'none' || document.hidden) return;
      var d = new Date(), ist = new Date(d.getTime() + d.getTimezoneOffset() * 60000 + 5.5 * 3600000);
      var two = function (n) { return (n < 10 ? '0' : '') + n; };
      var c = $('drt-clock');
      if (c) c.textContent = two(ist.getHours()) + ':' + two(ist.getMinutes()) + ':' + two(ist.getSeconds()) + ' IST';
      var mins = ist.getHours() * 60 + ist.getMinutes() + ist.getSeconds() / 60;
      var bar = $('drt-sbar');
      if (bar) bar.style.width = (Math.max(0, Math.min(1, (mins - 555) / 375)) * 100).toFixed(2) + '%';
    }
    tick();
    T.clock = setInterval(tick, 1000);
  }

  /* ════════════════════════════════════════════════════════════════════════
     IDEAS
     ════════════════════════════════════════════════════════════════════════ */

  var I = { built: false };

  function ideasShell() {
    var universe = universeCount();
    var cards = [
      '<button type="button" class="dr-card dr-tool dr-rise" style="--i:2" data-goto="research/query">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('query') + '</span></span>' +
        '<span class="dr-tool-name">Screener</span>' +
        '<span class="dr-tool-line">Pick what you want in a company, or write your own query.</span>' +
        '<span class="dr-tool-chips">' + ['Makes good money', 'Owes little', 'Not too pricey', 'Growing fast'].map(function (n, k) {
          return '<span class="dr-chip dr-pop" style="--i:' + k + '">' + esc(n) + '</span>';
        }).join('') + '</span></button>',
      '<button type="button" class="dr-card dr-tool dr-rise" style="--i:3" data-goto="research/lenses">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('lenses') + '</span></span>' +
        '<span class="dr-tool-name">Investor styles</span>' +
        '<span class="dr-tool-count"><b class="dr-n" data-count-to="' + LENSES.length + '">' + LENSES.length + '</b><small>ways great investors pick stocks</small></span>' +
        '<span class="dr-tool-chips">' + LENSES.slice(0, 6).map(function (n, k) {
          return '<span class="dr-chip dr-pop" style="--i:' + k + '">' + esc(n) + '</span>';
        }).join('') + '</span></button>',
      '<button type="button" class="dr-card dr-tool dr-rise" style="--i:4" data-goto="research/investors" id="dri-owners">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('owners') + '</span></span>' +
        '<span class="dr-tool-name">Who owns what</span>' +
        '<span class="dr-tool-count"><b class="dr-n" data-count>—</b><small>well-known investors tracked</small></span>' +
        '<span class="dr-tool-line" data-line>What well-known investors hold.</span>' +
        '<span class="dr-tool-chips" data-chips></span></button>',
      '<button type="button" class="dr-card dr-tool dr-rise dr-record" style="--i:5" data-goto="research/calls">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-record-row"><span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('record') + '</span></span>' +
          '<span class="dr-tool-name">Track record</span>' +
          '<span class="dr-tool-line">Every pick, dated, and its return since.</span></span>' +
          '<img src="research-illustration.webp" alt="" width="132" height="88" loading="lazy"></span></button>'
    ].join('');
    var more = [
      ['research/funds', 'funds', 'Fund houses', 'What mutual funds hold'],
      ['research/charts', 'charts', 'Charts', 'Chart any stock'],
      ['research/strategies', 'flask', 'Strategy lab', 'Trading rules, tested on any stock'],
      ['research/concalls', 'concalls', 'Concalls', 'Earnings calls, summarised'],
      // A page of its own, so a link rather than a tab.
      ['forum.html', 'adviser', 'Forum', 'Discuss stocks with other investors']
    ].map(function (m, k) {
      var inner = '<span class="dr-tool-ic">' + svg(m[1]) + '</span><span><b>' + esc(m[2]) + '</b><small>' + esc(m[3]) + '</small></span>' +
        '<span class="dr-row-go">' + svg('arrow', 16) + '</span>';
      if (/\.html$/.test(m[0])) {
        return '<a class="dr-card dr-row dr-rise" style="--i:' + (6 + k) + '" href="' + m[0] + '">' + inner + '</a>';
      }
      return '<button type="button" class="dr-card dr-row dr-rise" style="--i:' + (6 + k) + '" data-goto="' + m[0] + '">' + inner + '</button>';
    }).join('');

    return '<div class="dr dr-ideas">' +
      head('Ideas', 'What should I look at?') +
      /* The door answers its own question first: the pick lists, three by
         holding time and five by chart setup (picks.js). It used to open on
         a picture of a planet and a button, and a reader had to open a tool
         and scroll past the planet again before seeing a single stock. */
      '<section class="pk-panel dr-rise" id="dri-picks" style="--i:1" aria-label="Stock picks"></section>' +
      '<button type="button" class="dr-universe dr-rise" style="--i:2" data-goto="research/ideas">' +
        '<span class="dr-orbits" aria-hidden="true">' +
          '<span class="dr-ring r1"></span><span class="dr-ring r2"></span>' +
          '<span class="dr-orbit o1"><span class="dr-planet p-a"></span></span>' +
          '<span class="dr-orbit o2"><span class="dr-planet p-b"></span></span>' +
          '<span class="dr-planet p-c dr-earth"></span>' +
        '</span>' +
        '<span class="dr-universe-t">' +
          '<span class="dr-label gold">Universe scan</span>' +
          '<span class="dr-universe-h">Scan the whole NSE</span>' +
          '<span class="dr-universe-p">Every listed company, scored and ranked.</span>' +
          (universe ? '<span class="dr-universe-n"><b class="dr-n" data-count-to="' + universe + '">' + inr(universe, 0) + '</b> companies on NSE today</span>' : '') +
          '<span class="dr-cta">Open the scan ' + svg('arrow', 16) + '</span>' +
        '</span>' +
      '</button>' +
      '<div class="dr-cards wide">' + cards + '</div>' +
      '<div class="dr-rows">' + more + '</div>' +
    '</div>';
  }

  function universeCount() {
    var o = readJSON(UNI_KEY, null);
    return o && Array.isArray(o.rows) ? o.rows.length : 0;
  }

  function openIdeas() {
    var v = $('view-ideahub');
    if (!v) return;
    if (!I.built) {
      v.innerHTML = ideasShell();
      I.built = true;
      if (window.AltahaPicks) window.AltahaPicks.mount($('dri-picks'));
      v.querySelectorAll('[data-count-to]').forEach(function (n) { countUp(n, n.dataset.countTo); });
      get('/investors', 15000).then(function (d) {
        var list = (d && (d.investors || d.rows || d.directory)) || [];
        fillTool('dri-owners', list.length || null, null,
          list.slice(0, 3).map(function (x) { return { text: x.name || x.investor || '' }; }).filter(function (c) { return c.text; }));
      });
    }
  }

  /* ════════════════════════════════════════════════════════════════════════
     MY MONEY
     ════════════════════════════════════════════════════════════════════════ */

  /* The planner's card says what the planner says. Somebody with a date sees
     it here, with how far along they are and whether this month's check-in is
     still to do — which is the reason to open it. Everybody else sees what it
     is for. The date is the planner's to work out; this only asks for it. */
  function plannerCard() {
    var p = null;
    try { p = window.AltahaPlanner && window.AltahaPlanner.summary(); } catch (e) {}
    var has = !!p && !p.example && (p.status === 'dated' || p.status === 'free');
    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    var when = has && p.when ? String(p.when).split('-') : null;
    var line = !has ? 'Find the month work becomes optional, and what moves it.'
      : (p.status === 'free' ? 'Work is already optional.'
          : 'Work becomes optional in ' + MONTHS[Number(when[1]) - 1] + ' ' + when[0] + '.') +
        (p.due ? ' This month\u2019s check-in is due.' : p.streak > 1 ? ' ' + p.streak + ' check-ins running.' : '');
    // The arc is a half circle; draw as much of it as there is progress.
    var f = has ? Math.max(0.04, Math.min(1, p.progress)) : 0.71;
    var x = (100 - 84 * Math.cos(f * Math.PI)).toFixed(1), y = (96 - 84 * Math.sin(f * Math.PI)).toFixed(1);
    return '<button type="button" class="dr-card dr-tool dr-rise" style="--i:4" data-goto="portfolio/planner" id="drm-planner" data-private>' +
      '<span class="dr-sheen" aria-hidden="true"></span>' +
      '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('planner') + '</span></span>' +
      '<span class="dr-tool-name">Money planner</span>' +
      '<span class="dr-tool-line">' + esc(line) + '</span>' +
      '<svg class="dr-gauge" viewBox="0 0 200 104" aria-hidden="true"><path class="bg" d="M16 96 A84 84 0 0 1 184 96"/>' +
        '<path class="fg dr-draw" pathLength="1" d="M16 96 A84 84 0 0 1 ' + x + ' ' + y + '"/></svg>' +
    '</button>';
  }

  function moneyShell() {
    var n = portfolioCount();
    var w = readJSON(WATCH_KEY, []);
    w = Array.isArray(w) ? w : [];
    var ring = Math.min(100, n * 10);
    return '<div class="dr dr-money">' +
      head('Portfolio', 'How am I doing, and what next?') +
      '<button type="button" class="dr-hero dr-pfhero dr-rise" style="--i:1" data-goto="portfolio/portfolio">' +
        '<span class="dr-ringwrap" aria-hidden="true"><svg viewBox="0 0 120 120"><circle class="dr-ring-bg" cx="60" cy="60" r="48"/>' +
          '<circle class="dr-ring-fg" cx="60" cy="60" r="48" pathLength="100" style="--len:' + (n ? ring : 6) + '"/></svg>' +
          '<span class="dr-ring-n"><b class="dr-n" data-count-to="' + n + '">' + n + '</b><small>' + (n === 1 ? 'holding' : 'holdings') + '</small></span></span>' +
        '<span class="dr-pf-t">' +
          '<span class="dr-label gold">Portfolio review</span>' +
          '<span class="dr-pf-h">' + (n ? 'Your portfolio is saved here' : 'See what to do with every stock you own') + '</span>' +
          '<span class="dr-pf-p">' + (n ? 'Get a hold, trim, add or exit call on each holding.'
            : 'Add your holdings or your broker’s file. Get a hold, trim, add or exit call on each.') + '</span>' +
          '<span class="dr-cta">' + (n ? 'Review my portfolio' : 'Add my holdings') + ' ' + svg('arrow', 16) + '</span>' +
        '</span>' +
      '</button>' +
      '<div class="dr-cards wide">' +
        '<button type="button" class="dr-card dr-tool dr-rise" style="--i:2" id="drm-watch">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('watch') + '</span></span>' +
          '<span class="dr-tool-name">Watchlist</span>' +
          '<span class="dr-tool-count"><b class="dr-n" data-count-to="' + w.length + '">' + w.length + '</b><small>stocks followed</small></span>' +
          '<span class="dr-tool-chips">' + w.slice(0, 5).map(function (r) { return '<span class="dr-chip">' + esc(r.symbol || r) + '</span>'; }).join('') + '</span>' +
        '</button>' +
        '<button type="button" class="dr-card dr-tool dr-rise" style="--i:3" data-goto="portfolio/allocate">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('allocate') + '</span></span>' +
          '<span class="dr-tool-name">Allocation plan</span>' +
          '<span class="dr-tool-line">How to split your money by risk.</span>' +
          '<span class="dr-stack" aria-hidden="true"><i style="--w:52%;--i:0"></i><i style="--w:26%;--i:1"></i><i style="--w:12%;--i:2"></i><i style="--w:10%;--i:3"></i></span>' +
        '</button>' +
        plannerCard() +
        '<a class="dr-card dr-tool dr-rise" style="--i:5" href="advisors.html">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('adviser') + '</span></span>' +
          '<span class="dr-tool-name">Talk to an adviser</span>' +
          '<span class="dr-tool-line">Chat with SEBI-registered advisers. Free.</span>' +
          '<span class="dr-chat" aria-hidden="true"><span class="me">Is my portfolio too heavy in banks?</span><span class="them"><i></i><i></i><i></i></span></span>' +
        '</a>' +
        '<a class="dr-card dr-tool dr-rise" style="--i:6" href="wealth.html">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('review') + '</span></span>' +
          '<span class="dr-tool-name">Wealth desk</span>' +
          '<span class="dr-tool-line">Manage money for others? Clients, calls and commission in one place.</span>' +
          '<span class="dr-tool-chips"><span class="dr-chip">Clients</span><span class="dr-chip">Calls</span><span class="dr-chip">Commission</span></span>' +
        '</a>' +
      '</div>' +
    '</div>';
  }

  function openMoney() {
    var v = $('view-money');
    if (!v) return;
    // Rebuilt on every visit: it reads only this browser's storage, and a
    // holding saved a minute ago should show.
    v.innerHTML = moneyShell();
    v.querySelectorAll('[data-count-to]').forEach(function (n) { countUp(n, n.dataset.countTo); });
    var wb = $('drm-watch');
    if (wb) wb.addEventListener('click', openWatchlist);
  }

  function openWatchlist() {
    if (window.AltahaWatchlist) { window.AltahaWatchlist.open(); return; }
    var b = document.querySelector('.ux-desktop-save') ||
      Array.prototype.filter.call(document.querySelectorAll('button'), function (x) { return x.textContent.trim() === 'Watchlist'; })[0];
    if (b) b.click();
  }

  /* ════════════════════════════════════════════════════════════════════════
     Wiring
     ════════════════════════════════════════════════════════════════════════ */

  /* Every entrance starts at opacity 0 and rises in. If something pauses
     animations (a stylesheet elsewhere, an extension, a browser setting the
     media query does not cover), that start state would be the end state and
     the page would sit blank. So, a moment after a door is drawn, entrances
     are switched off for it: by then every one has played, and anything
     still frozen simply appears. motion-off-browser pins this. */
  function played(v) {
    if (!v) return;
    v.classList.remove('dr-played');
    clearTimeout(v._drPlayed);
    // index.html's view switch fades every view in from opacity 0 with a
    // class it adds on each switch; that goes too, for the same reason.
    v._drPlayed = setTimeout(function () { v.classList.remove('viewfade'); v.classList.add('dr-played'); }, 2200);
  }

  function open(which, force) {
    document.documentElement.classList.add('doors-on');
    played($('view-' + which));
    if (which === 'today') openToday(force);
    else if (which === 'ideahub') openIdeas();
    else if (which === 'money') openMoney();
  }

  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var mv = t.closest('[data-movers]');
    if (mv) { T.movers = mv.dataset.movers; paintMovers(); return; }
    var tile = t.closest('.dr-tile[data-sector]');
    if (tile) { toggleSector(tile.dataset.sector); return; }
    if (t.closest('#drt-secpanel-x')) { closeSector(); return; }
    if (t.closest('#dr-desk-watchopen')) { openWatchlist(); }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !T.sector) return;
    var host = $('drt-secpanel');
    if (host && host.contains(e.target)) { e.preventDefault(); closeSector(); }
  });

  // The header reads /market and /sector/overview every minute for its
  // ticker. Each read refreshes Market in place, with the level flashing.
  window.addEventListener('altaha:market', function (e) {
    var d = e.detail || {};
    var v = $('view-today');
    if (!v || !v.firstChild) return;
    if (d.indices && d.indices.length) { T.market = { indices: d.indices, status: (T.market || {}).status }; paintIndices(T.market); }
    if (d.sectors) paintSectors(d.sectors);
    // The desk's names move with the market; the server answers from cache.
    if (v.style.display !== 'none' && Date.now() - T.wqAt > 55000) loadDeskQuotes();
  });
  window.addEventListener('storage', function (e) {
    if (e.key === WATCH_KEY || e.key === PIN_KEY) paintDesk(T.quotes);
  });
  window.addEventListener('altaha:pins', function () { paintDesk(T.quotes); });

  window.AltahaDoors = { open: open, pins: pins, PIN_KEY: PIN_KEY };

  /* The landing view is Market, so it may already be on screen before the
     tab handler that calls open() exists. */
  function boot() {
    ['today', 'ideahub', 'money'].forEach(function (w) {
      var v = $('view-' + w);
      if (v && v.style.display !== 'none' && !v.firstChild) open(w);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  } else {
    setTimeout(boot, 200);
  }
})();
