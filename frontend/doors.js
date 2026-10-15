/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — the three doors

   WHAT THIS IS
   The page each door opens on. Today, Ideas and My money each preview every
   tool behind them — one live number or one line per tool — and open the
   tool on a tap. The tools themselves are the views that already exist and
   are not touched here; this file only decides how you arrive at them.

     Today     #view-today     the market, live: Nifty, the other indices, a
                               three-month chart, FII/DII flows, every sector,
                               the movers, and a card per Today tool
     Ideas     #view-ideahub   the ranked universe and every way to find a stock
     My money  #view-money     your saved portfolio, watchlist and plans

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
  var UNI_KEY = 'altaha-universe-v2';

  /* The investor styles in backend/lenses.json, in the order the lenses page
     lists them. Names only; the screens themselves are on that page. */
  var LENSES = ['Coffee Can', 'Moat', 'QGLP', 'Tenbagger', 'Owner-Operator', 'Nomad',
                'Cannibal', 'Akre', 'Gorilla', 'Capital Cycle'];

  var ICON = {
    alerts:   '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    deals:    '<path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/>',
    wow:      '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    delivery: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    results:  '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    filings:  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 14h5M9 17h3"/>',
    setups:   '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    options:  '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    query:    '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    lenses:   '<circle cx="7" cy="14" r="4"/><circle cx="17" cy="14" r="4"/><path d="M11 14h2M3 14l2-7M21 14l-2-7"/>',
    converge: '<circle cx="8" cy="10" r="5"/><circle cx="16" cy="10" r="5"/><circle cx="12" cy="16" r="5"/>',
    owners:   '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c1-4 4-6 7-6s6 2 7 6"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2 .8 3.4 2.8 4 6"/>',
    funds:    '<path d="M3 21h18M5 21V10l7-5 7 5v11"/><path d="M9 21v-6h6v6"/>',
    record:   '<path d="M3 3v18h18"/><path d="m7 14 4-4 3 3 5-6"/>',
    charts:   '<path d="M7 4v3M7 17v3M17 4v3M17 17v3"/><rect x="4.5" y="7" width="5" height="10" rx="1"/><rect x="14.5" y="7" width="5" height="10" rx="1"/>',
    factors:  '<path d="M4 6h16M4 12h10M4 18h6"/>',
    concalls: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/>',
    review:   '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 11l2 2 4-4M9 17h6"/>',
    watch:    '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3l-5.5 2.9 1-6.2L3 9.6l6.2-.9z"/>',
    allocate: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9M12 12l-6.4 6.4"/>',
    planner:  '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h2"/>',
    adviser:  '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z"/>',
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

  var T = { last: 0, market: null, week: null, sectors: null, chart: null, movers: 'up', clock: null, prevNifty: null };

  var TODAY_TOOLS = [
    { id: 'drt-live', goto: 'discover/live', icon: 'alerts', name: 'Alerts', unit: 'fired today', live: true,
      line: 'Volume spikes, opening-range and level breaks as they happen.' },
    { id: 'drt-deals', goto: 'discover/deals', icon: 'deals', name: 'Big trades', unit: 'stocks with deals',
      line: 'Bulk and block deals, netted per stock.' },
    { id: 'drt-wow', goto: 'discover/wow', icon: 'wow', name: 'Order wins', unit: '',
      line: 'New orders measured against the size of the company that won them.' },
    { id: 'drt-special', goto: 'discover/special', icon: 'delivery', name: 'Delivery trends', unit: 'in the book',
      line: 'Advances carried on delivered volume rather than intraday churn.' },
    { id: 'drt-results', goto: 'discover/results', icon: 'results', name: 'Results calendar', unit: 'today',
      line: 'Who reports yesterday, today and this week.' },
    { id: 'drt-filings', goto: 'discover/filings', icon: 'filings', name: 'Filings & news', unit: 'filings in the feed', live: true,
      line: 'Company announcements as they reach the exchange.' },
    { id: 'drt-setups', goto: 'discover/discover', icon: 'setups', name: 'Setups', unit: 'strong setups',
      line: 'The screener’s strongest setups for the short horizon.' },
    { id: 'drt-options', goto: 'discover/options', icon: 'options', name: 'Options', unit: '',
      line: 'Option chains, open interest and the expiries ahead.' }
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
      head('Today', 'What is the market doing?', session) +
      '<div class="dr-grid">' +
        '<div class="dr-main">' +
          '<section class="dr-hero dr-rise" style="--i:1" aria-label="The market now">' +
            '<span class="dr-blob dr-b1" aria-hidden="true"></span><span class="dr-blob dr-b2" aria-hidden="true"></span>' +
            '<span class="dr-gridbg" aria-hidden="true"></span>' +
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
            '<div class="dr-sec-h"><h2>Sectors right now</h2><span>Colour is today’s move · tap one to see why</span></div>' +
            '<div class="dr-heat" id="drt-heat"><p class="dr-quiet">Reading the sectors…</p></div>' +
          '</section>' +
          '<section class="dr-sec">' +
            '<div class="dr-sec-h dr-rise" style="--i:3"><h2>Everything behind this door</h2><span>Tap a card to open the tool</span></div>' +
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
            '<p class="dr-fine">Among the sector heavyweights the site tracks live.</p>' +
          '</section>' +
          '<section class="dr-card dr-heads dr-rise" style="--i:6" aria-label="Headlines">' +
            '<div class="dr-card-h"><h2>Headlines</h2><button type="button" class="dr-link" data-goto="discover/filings">Filings ›</button></div>' +
            '<div id="drt-heads"><p class="dr-quiet">Reading the press…</p></div>' +
          '</section>' +
        '</aside>' +
      '</div>' +
      '<p class="dr-disc">Observations, not recommendations. Index levels and moves are the data feed’s; sector moves are equal-weight across the heavyweights tracked.</p>' +
    '</div>';
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
        w.innerHTML = '<p class="dr-quiet">Nothing saved yet. Tap ☆ on any stock page to follow it.</p>';
      } else {
        w.innerHTML = rows.slice(0, 6).map(function (r) {
          var sym = String(r.symbol || r).toUpperCase(), q = (quotes || {})[sym];
          return '<a class="dr-wrow" href="stock.html?ticker=' + encodeURIComponent(sym) + '">' +
            '<span class="dr-wsym">' + esc(sym) + '</span>' +
            '<span class="dr-wpx">' + (q && finite(q.ltp) ? inr(q.ltp, 2) : '') + '</span>' +
            '<span class="dr-wchg ' + (q ? tone(q.change_pct) : '') + '">' + (q ? pct(q.change_pct) : '') + '</span></a>';
        }).join('');
      }
    }
    var p = $('dr-desk-pins');
    if (p) {
      var list = pins().map(toolInfo).filter(Boolean);
      p.innerHTML = list.length ? list.map(function (t) {
        return '<button type="button" class="dr-pinchip" data-goto="' + esc(t.section + '/' + t.tab.id) + '">' +
          svg('pin', 14) + esc(t.tab.label) + '</button>';
      }).join('') : '<p class="dr-quiet">Pin any tool from the bar above it and it waits for you here.</p>';
    }
  }

  function portfolioCount() {
    var draft = readJSON(DRAFT_KEY, null);
    var n = draft && Array.isArray(draft.rows) ? draft.rows.filter(function (r) { return r && r.symbol; }).length : 0;
    if (n) return n;
    var store = readJSON(STORE_KEY, {});
    var names = store && typeof store === 'object' ? Object.keys(store) : [];
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
        return '<div class="dr-ix dr-rise" style="--i:' + (k + 2) + '">' +
          '<span class="dr-ix-n">' + esc(i.label) + '</span>' +
          '<span class="dr-ix-v">' + inr(i.level, 2) + '</span>' +
          weekSpark(i.label, t) +
          '<span class="dr-ix-c ' + t + '">' + pct(i.change_pct) + '</span></div>';
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
        '<defs><linearGradient id="drt-fill" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" stop-color="#D9BC6A" stop-opacity=".42"/><stop offset="1" stop-color="#D9BC6A" stop-opacity="0"/>' +
        '</linearGradient></defs>' +
        '<line class="dr-prevline" x1="0" x2="' + W + '" y1="' + Y(prev).toFixed(1) + '" y2="' + Y(prev).toFixed(1) + '"/>' +
        '<path class="dr-area" d="' + line + ' L' + W + ' ' + H + ' L0 ' + H + ' Z" fill="url(#drt-fill)"/>' +
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
          var L = Math.round(92 - a * 56);
          var bg = c >= 0 ? 'hsl(146,40%,' + L + '%)' : 'hsl(9,60%,' + L + '%)';
          return '<button type="button" class="dr-tile" data-sector="' + esc(r.sector) + '" style="--i:' + i +
            ';background-color:' + bg + ';color:' + (L < 60 ? '#FBF8F1' : '#17140E') + '">' +
            '<span>' + esc(r.sector) + '</span><b>' + pct(r.change_pct) + '</b>' +
            (finite(r.up) && finite(r.total) ? '<small>' + r.up + ' of ' + r.total + ' up</small>' : '') + '</button>';
        }).join('');
      }
    }
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

  function paintHeads(d) {
    var host = $('drt-heads');
    if (!host) return;
    var cs = ((d && d.clusters) || []).map(function (c) { return c.lead || {}; }).filter(function (l) { return l.title; });
    host.innerHTML = cs.length ? '<ul class="dr-hlist">' + cs.slice(0, 5).map(function (l, i) {
      return '<li style="--i:' + i + '"><a href="' + esc(l.url || '#') + '" target="_blank" rel="noopener noreferrer">' +
        esc(l.title) + '</a><small>' + esc(l.publication || '') + '</small></li>';
    }).join('') + '</ul>' : '<p class="dr-quiet">No headlines right now.</p>';
  }

  /* ── The tool cards' live numbers ─────────────────────────────────────── */

  function todayCounts() {
    get('/intraday/status', 9000).then(function (d) {
      if (!d) return fillTool('drt-live', null, 'The scanner could not be reached just now.');
      var a = d.alerts_today || [];
      fillTool('drt-live', a.length, d.market_open ? 'Watching ' + (d.watchlist_size || 0) + ' names right now.'
        : 'The market is closed; today’s alerts stay on the scanner.',
        a.slice(-4).reverse().map(function (x) { return { text: x.symbol }; }));
    });
    get('/deals?limit=6', 15000).then(function (d) {
      if (!d || d.available === false) return fillTool('drt-deals', null, (d && d.message) || 'The deals feed is unavailable today.');
      fillTool('drt-deals', d.total_symbols != null ? d.total_symbols : (d.symbols || []).length, null,
        (d.symbols || []).slice(0, 4).map(function (r) { return { text: r.symbol, tone: tone(r.net_cr) }; }));
    });
    // Order wins are read out of each filing's PDF on the server, so nothing
    // asks for them until their own tab is opened (filings-views-browser
    // pins this). The card says what the tool does instead of a count.
    fillTool('drt-wow', null);
    get('/special?limit=6', 20000).then(function (d) {
      var rows = (d && d.book) || [];
      if (!d || d.available === false || !rows.length) {
        return fillTool('drt-special', null, (d && (d.message || d.detail)) || 'The delivery record is not deep enough to rank yet.');
      }
      fillTool('drt-special', rows.length, null, rows.slice(0, 4).map(function (r) { return { text: r.symbol }; }));
    });
    get('/results/calendar', 15000).then(function (d) {
      if (!d || !d.available) return fillTool('drt-results', null, (d && d.message) || 'NSE’s calendar could not be read just now.');
      var day = (d.days || []).filter(function (x) { return x.date === d.today; })[0];
      var week = (d.days || []).reduce(function (n, x) { return n + (x.declared || 0) + (x.pending || 0); }, 0);
      fillTool('drt-results', day ? (day.declared || 0) + (day.pending || 0) : 0,
        week + ' companies between yesterday and the end of next week.',
        day ? (day.rows || []).slice(0, 4).map(function (r) { return { text: r.symbol, tone: r.status === 'declared' ? 'up' : '' }; }) : []);
    });
    get('/announcements?limit=60&min_importance=medium', 12000).then(function (d) {
      if (!d) return fillTool('drt-filings', null, 'The filings feed could not be reached.');
      var rows = d.rows || [];
      fillTool('drt-filings', d.count != null ? d.count : rows.length, null,
        rows.slice(0, 4).map(function (r) { return { text: r.symbol }; }).filter(function (c) { return c.text; }));
    });
    get('/ideas?horizon=short&limit=6', 45000).then(function (d) {
      if (!d || !d.available) return fillTool('drt-setups', null, (d && d.message) || 'No ranking yet — the scan builds one from the universe.');
      fillTool('drt-setups', (d.rows || []).length, null, (d.rows || []).slice(0, 4).map(function (r) { return { text: r.symbol }; }));
    });
    fillTool('drt-options', null);
  }

  function openToday(force) {
    var v = $('view-today');
    if (!v) return;
    var now = Date.now();
    if (!v.firstChild) v.innerHTML = todayShell();
    paintDesk(T.quotes);
    startClock();
    if (!force && T.last && now - T.last < FRESH_MS) return;
    T.last = now;
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

  /* The trading-session clock, IST, once a second while Today is on screen. */
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
    var stars = '';
    for (var i = 0; i < 44; i++) {
      // Deterministic, so the sky does not reshuffle on every visit.
      var x = (i * 37.3) % 100, y = (i * 61.7 + (i % 5) * 7) % 100, s = 1 + (i % 3) * 0.7, d = (i % 7) * 0.45;
      stars += '<i class="dr-star" style="left:' + x.toFixed(1) + '%;top:' + y.toFixed(1) + '%;width:' + s +
        'px;height:' + s + 'px;animation-delay:' + d.toFixed(2) + 's"></i>';
    }
    var universe = universeCount();
    var cards = [
      '<button type="button" class="dr-card dr-tool dr-rise" style="--i:2" data-goto="research/query">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('query') + '</span></span>' +
        '<span class="dr-tool-name">Screener</span>' +
        '<span class="dr-tool-line">Your own rules over every stored company — 55 fields, from ROE to pledged shares.</span>' +
        '<span class="dr-term"><span class="dr-type">ROE &gt; 20 AND Debt to equity &lt; 0.5</span></span></button>',
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
        '<span class="dr-tool-line" data-line>Their disclosed holdings, quarter by quarter. Fund houses are one door along.</span>' +
        '<span class="dr-tool-chips" data-chips></span></button>',
      '<button type="button" class="dr-card dr-tool dr-rise dr-record" style="--i:5" data-goto="research/tracker">' +
        '<span class="dr-sheen" aria-hidden="true"></span>' +
        '<span class="dr-record-row"><span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('record') + '</span></span>' +
          '<span class="dr-tool-name">Track record</span>' +
          '<span class="dr-tool-line">Every idea the site has shown, and how it has done since.</span></span>' +
          '<img src="research-illustration.webp" alt="" width="132" height="88" loading="lazy"></span></button>'
    ].join('');
    var more = [
      ['research/convergence', 'converge', 'Convergence', 'Stocks that pass three or more investor styles'],
      ['research/funds', 'funds', 'Fund houses', 'What the mutual funds disclosed holding'],
      ['research/charts', 'charts', 'Charts', 'Drawings, levels and indicators for any stock'],
      ['research/factors', 'factors', 'Factors', 'What each factor has actually predicted'],
      ['research/concalls', 'concalls', 'Concalls', 'Earnings call transcripts, digested']
    ].map(function (m, k) {
      return '<button type="button" class="dr-card dr-row dr-rise" style="--i:' + (6 + k) + '" data-goto="' + m[0] + '">' +
        '<span class="dr-tool-ic">' + svg(m[1]) + '</span><span><b>' + esc(m[2]) + '</b><small>' + esc(m[3]) + '</small></span>' +
        '<span class="dr-row-go">' + svg('arrow', 16) + '</span></button>';
    }).join('');

    return '<div class="dr dr-ideas">' +
      head('Ideas', 'What should I look at?') +
      '<button type="button" class="dr-universe dr-rise" style="--i:1" data-goto="research/ideas">' +
        '<span class="dr-sky" aria-hidden="true">' + stars + '</span>' +
        '<span class="dr-orbits" aria-hidden="true">' +
          '<span class="dr-ring r1"></span><span class="dr-ring r2"></span>' +
          '<span class="dr-orbit o1"><span class="dr-planet p-jupiter s84"></span></span>' +
          '<span class="dr-orbit o2"><span class="dr-planet p-mars s56"></span></span>' +
          '<span class="dr-planet p-earth s140 dr-earth"></span>' +
        '</span>' +
        '<span class="dr-universe-t">' +
          '<span class="dr-label gold">Universe scan</span>' +
          '<span class="dr-universe-h">Explore the whole NSE universe</span>' +
          '<span class="dr-universe-p">Every listed company, ranked by the Altaha Score and grouped by industry. Fly in, filter, and open any stock.</span>' +
          (universe ? '<span class="dr-universe-n"><b class="dr-n" data-count-to="' + universe + '">' + inr(universe, 0) + '</b> companies on NSE today</span>' : '') +
          '<span class="dr-cta">Start the scan ' + svg('arrow', 16) + '</span>' +
        '</span>' +
        '<span class="dr-credit">Planet textures: Solar System Scope, CC BY 4.0</span>' +
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

  function moneyShell() {
    var n = portfolioCount();
    var w = readJSON(WATCH_KEY, []);
    w = Array.isArray(w) ? w : [];
    var ring = Math.min(100, n * 10);
    return '<div class="dr dr-money">' +
      head('My money', 'How am I doing, and what next?') +
      '<button type="button" class="dr-hero dr-pfhero dr-rise" style="--i:1" data-goto="portfolio/portfolio">' +
        '<span class="dr-blob dr-b1" aria-hidden="true"></span><span class="dr-blob dr-b3" aria-hidden="true"></span>' +
        '<span class="dr-gridbg" aria-hidden="true"></span>' +
        '<span class="dr-ringwrap" aria-hidden="true"><svg viewBox="0 0 120 120"><circle class="dr-ring-bg" cx="60" cy="60" r="48"/>' +
          '<circle class="dr-ring-fg" cx="60" cy="60" r="48" pathLength="100" style="--len:' + (n ? ring : 6) + '"/></svg>' +
          '<span class="dr-ring-n"><b class="dr-n" data-count-to="' + n + '">' + n + '</b><small>' + (n === 1 ? 'holding' : 'holdings') + '</small></span></span>' +
        '<span class="dr-pf-t">' +
          '<span class="dr-label gold">Portfolio review</span>' +
          '<span class="dr-pf-h">' + (n ? 'Your portfolio is saved here' : 'See what to do with every stock you own') + '</span>' +
          '<span class="dr-pf-p">' + (n ? 'Run the review for a hold, trim, average, add or exit call on each holding, with the reasons.'
            : 'Add your holdings or import your broker’s file. You get a call on each one — hold, trim, average down, add or exit — and the reasons.') + '</span>' +
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
          '<span class="dr-tool-line">How much, what risk it can carry, and which asset classes follow.</span>' +
          '<span class="dr-stack" aria-hidden="true"><i style="--w:52%;--i:0"></i><i style="--w:26%;--i:1"></i><i style="--w:12%;--i:2"></i><i style="--w:10%;--i:3"></i></span>' +
        '</button>' +
        '<button type="button" class="dr-card dr-tool dr-rise" style="--i:4" data-goto="portfolio/planner">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('planner') + '</span></span>' +
          '<span class="dr-tool-name">Money planner</span>' +
          '<span class="dr-tool-line">Income, expenses, tax and the cushion to keep before investing.</span>' +
          '<svg class="dr-gauge" viewBox="0 0 200 104" aria-hidden="true"><path class="bg" d="M16 96 A84 84 0 0 1 184 96"/><path class="fg dr-draw" pathLength="1" d="M16 96 A84 84 0 0 1 152 40"/></svg>' +
        '</button>' +
        '<a class="dr-card dr-tool dr-rise" style="--i:5" href="advisors.html">' +
          '<span class="dr-sheen" aria-hidden="true"></span>' +
          '<span class="dr-tool-top"><span class="dr-tool-ic">' + svg('adviser') + '</span></span>' +
          '<span class="dr-tool-name">Talk to an adviser</span>' +
          '<span class="dr-tool-line">Chat with SEBI-registered advisers and research analysts. Free.</span>' +
          '<span class="dr-chat" aria-hidden="true"><span class="me">Is my portfolio too heavy in banks?</span><span class="them"><i></i><i></i><i></i></span></span>' +
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
    if (tile) {
      // The sector's story lives on the market board, with its constituents.
      var name = tile.dataset.sector;
      if (window.AltahaNav) window.AltahaNav.go('discover', 'screener', true);
      setTimeout(function () { if (window.AltahaSectors) window.AltahaSectors.open(name); }, 350);
      return;
    }
    if (t.closest('#dr-desk-watchopen')) { openWatchlist(); }
  });

  // The header reads /market and /sector/overview every minute for its
  // ticker. Each read refreshes Today in place, with the level flashing.
  window.addEventListener('altaha:market', function (e) {
    var d = e.detail || {};
    var v = $('view-today');
    if (!v || !v.firstChild) return;
    if (d.indices && d.indices.length) { T.market = { indices: d.indices, status: (T.market || {}).status }; paintIndices(T.market); }
    if (d.sectors) paintSectors(d.sectors);
  });
  window.addEventListener('storage', function (e) {
    if (e.key === WATCH_KEY || e.key === PIN_KEY) paintDesk(T.quotes);
  });
  window.addEventListener('altaha:pins', function () { paintDesk(T.quotes); });

  window.AltahaDoors = { open: open, pins: pins, PIN_KEY: PIN_KEY };

  /* The landing view is Today, so it may already be on screen before the
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
