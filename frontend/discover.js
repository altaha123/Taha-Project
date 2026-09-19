/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Discover

   THE QUESTION THIS PRODUCT ANSWERS
   "Where are opportunities now?" Not "what is this company worth" — that is
   Research — and not "what should I buy" — nobody here answers that. Just:
   out of two thousand listed names, which handful had something happen to
   them today, and what was it.

   IT OWNS NO DATA
   Every block is a window onto a feed that already has a tab of its own, cut
   to the few rows worth a glance, with the door to the full view underneath.
   A hub that re-implements its children drifts out of step with them inside a
   month, and then two screens disagree about the same number in front of the
   same reader.

   EVERY BLOCK FAILS ON ITS OWN
   Five endpoints, five independent renders. A dead delivery cache removes the
   delivery card and nothing else. The one thing this view must never do is
   present an empty page because one feed was asleep — on a free instance that
   is the normal case for the first thirty seconds after a cold start.

   NOTHING HERE IS A RECOMMENDATION
   The wording is load-bearing. "Where the unusual activity is" is an
   observation. "Buy these" is advice, which this project does not give and is
   not registered to give.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';
  if (window.AltahaDiscover) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  /* Long enough that flicking between tabs does not re-fan-out five requests,
     short enough that a scanner card is never stale by the time it is read. */
  var FRESH_MS = 180000;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function num(v, dp) {
    if (v == null || isNaN(v)) return '—';
    return Number(v).toFixed(dp == null ? 2 : dp);
  }
  function pct(v) {
    if (v == null || isNaN(v)) return '—';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%';
  }
  function tone(v) {
    if (v == null || isNaN(v)) return '';
    return v > 0 ? ' up' : v < 0 ? ' dn' : '';
  }
  function cr(v) {
    if (v == null || isNaN(v)) return '—';
    return '₹' + Number(v).toFixed(Math.abs(v) >= 100 ? 0 : 1) + 'cr';
  }

  /* Every request is bounded and every failure is a resolved promise carrying
     null. A hub that can be held open by one slow feed is a hub that looks
     broken while it is working. */
  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    var opts = ctl ? { signal: ctl.signal } : {};
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 12000);
    return fetch(API + path, opts)
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().then(function (j) { return r.ok ? j : null; });
      })
      .catch(function () { if (timer) clearTimeout(timer); return null; });
  }

  function card(cls, title, sub, body, goto_, cta) {
    return '<section class="dsc-card ' + cls + '">' +
      '<div class="dsc-h"><h3>' + esc(title) + '</h3>' +
      (sub ? '<span>' + esc(sub) + '</span>' : '') + '</div>' +
      body +
      (goto_ ? '<button class="dsc-more" type="button" data-goto="' + esc(goto_) + '">' +
        esc(cta || 'Open the full view') + ' →</button>' : '') +
      '</section>';
  }

  function quiet(msg) {
    return '<p class="dsc-quiet">' + esc(msg) + '</p>';
  }

  function loading(what) {
    return '<p class="dsc-quiet is-loading" aria-busy="true">Reading ' + esc(what) + '…</p>';
  }

  /* ── 1 · The market right now ───────────────────────────────────────────
     Context before names. A list of strong setups on a day the index is down
     two percent is a different object from the same list on a quiet day, and
     the reader has to be told which one they are looking at first. */

  function market() {
    var host = $('dsc-market');
    if (!host) return;
    host.innerHTML = '<div class="dsc-mkt">' + loading('the index levels') + '</div>';
    get('/market', 9000).then(function (d) {
      if (!d || !(d.indices || []).length) {
        host.innerHTML = '<div class="dsc-mkt">' +
          quiet('Index levels are unavailable right now. Everything below still reads.') +
          '</div>';
        return;
      }
      var open = d.status === 'open';
      host.innerHTML = '<div class="dsc-mkt">' +
        '<div class="dsc-mkt-h">' +
          '<span class="dsc-state' + (open ? ' on' : '') + '">' +
            (open ? 'Market open' : 'Market closed') + '</span>' +
          (d.ist ? '<span class="dsc-when">' + esc(d.ist) + '</span>' : '') +
        '</div>' +
        '<div class="dsc-idx">' + d.indices.map(function (i) {
          return '<div class="dsc-ix">' +
            '<span class="k">' + esc(i.label) + '</span>' +
            '<span class="v tnum">' + num(i.level, 2) + '</span>' +
            '<span class="c tnum' + tone(i.change_pct) + '">' + pct(i.change_pct) + '</span>' +
          '</div>';
        }).join('') + '</div></div>';
    });
  }

  /* ── 2 · Today's strongest setups ───────────────────────────────────────
     The screener's own ranking, top six, unmodified. Re-ranking it here would
     produce a second opinion about the same universe, which is how two pages
     start disagreeing in front of the same reader. */

  function setups() {
    var host = $('dsc-setups');
    if (!host) return;
    host.innerHTML = card('is-setups', 'Strongest setups today', '', loading('the ranking'), null);
    get('/ideas?horizon=short&limit=6', 45000).then(function (d) {
      var body, sub = '';
      if (!d) {
        body = quiet('The ranking engine is unreachable. If it has been idle it takes about thirty seconds to wake.');
      } else if (!d.available) {
        body = quiet(d.message || 'No scan has been run yet, so there is no ranking to show. The screener builds one from the universe.');
      } else if (!(d.rows || []).length) {
        body = quiet('Nothing clears the conviction floor for this horizon today. That is a real answer, not an error — a screener that always finds something is not screening.');
      } else {
        sub = d.scanned_at ? 'scanned ' + d.scanned_at : '';
        body = '<ol class="dsc-rows">' + d.rows.slice(0, 6).map(function (r) {
          return '<li class="dsc-row">' +
            '<a class="dsc-sym" href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' +
              esc(r.symbol) + '<small>' + esc(r.name || '') + '</small></a>' +
            '<span class="dsc-mid">' + esc(r.setup || '—') +
              (r.horizon ? ' · typical hold ' + esc(r.horizon) : '') + '</span>' +
            '<span class="dsc-val tnum">' + num(r.conviction, 0) + '<small>conviction</small></span>' +
          '</li>';
        }).join('') + '</ol>';
        if (d.regime && !d.regime.ok) {
          body += '<p class="dsc-warn"><b>Market regime.</b> ' + esc(d.regime.label) + '</p>';
        }
      }
      host.innerHTML = card('is-setups', 'Strongest setups today', sub, body,
                            'research/ideas', 'Open the stock screener');
    });
  }

  /* ── 3 · Unusual activity ───────────────────────────────────────────────
     Four feeds that each answer "something happened here that does not happen
     most days". Rendered into one grid, each one replacing its own placeholder
     the moment its request lands, so the fastest feed is not held behind the
     slowest. */

  function activity() {
    var host = $('dsc-activity');
    if (!host) return;
    host.innerHTML =
      '<h3 class="dsc-sech">Where the unusual activity is</h3>' +
      '<div class="dsc-grid">' +
        '<div id="dsc-live"></div>' +
        '<div id="dsc-deals"></div>' +
        '<div id="dsc-deliv"></div>' +
        '<div id="dsc-wow"></div>' +
      '</div>';

    slot('dsc-live', 'Live scanner', loading('the intraday scanner'));
    slot('dsc-deals', 'Bulk & block deals', loading('today’s disclosures'));
    slot('dsc-deliv', 'Delivery trends', loading('the delivery record'));
    slot('dsc-wow', 'Order wins', loading('the filings'));

    get('/intraday/status', 9000).then(function (d) {
      var body;
      if (!d) {
        body = quiet('The scanner could not be reached.');
      } else {
        var fired = (d.alerts_today || []).length;
        body = '<p class="dsc-big"><b class="tnum">' + fired + '</b> ' +
          (fired === 1 ? 'alert' : 'alerts') + ' today</p>' +
          quiet(d.market_open
            ? 'Watching ' + (d.watchlist_size || 0) + ' names for volume spikes, opening-range breaks and level breaks.'
            : 'The market is closed, so nothing new will fire until it opens. Today’s alerts stay on the scanner.');
        if ((d.top_rvol_now || []).length) {
          body += '<p class="dsc-chips">' + d.top_rvol_now.slice(0, 5).map(function (x) {
            var sym = x && (x.symbol || x[0]);
            return sym ? '<span class="dsc-chip">' + esc(sym) + '</span>' : '';
          }).join('') + '</p>';
        }
      }
      slot('dsc-live', 'Live scanner', body, 'discover/live', 'Open the scanner');
    });

    get('/deals?limit=6', 15000).then(function (d) {
      var rows = (d && d.symbols) || [];
      var body = !d ? quiet('The deals feed is unavailable today.')
        : !rows.length ? quiet('No bulk or block disclosures cleared the size filter today.')
        : '<ul class="dsc-mini">' + rows.slice(0, 5).map(function (r) {
            return '<li><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' +
              esc(r.symbol) + '</a><span class="tnum' + tone(r.net_cr) + '">' +
              cr(r.net_cr) + '</span></li>';
          }).join('') + '</ul>' +
          quiet('Netted per stock: a large buy against an equally large sell is shares changing hands, not demand arriving.');
      slot('dsc-deals', 'Bulk & block deals',
           body, 'discover/deals', 'Open the deals board');
    });

    get('/special?limit=6', 20000).then(function (d) {
      var rows = (d && d.book) || [];
      var body = !d ? quiet('The delivery cache is unavailable.')
        : (d.available === false || !rows.length)
          ? quiet((d && (d.message || d.detail)) ||
                  'The delivery history is not deep enough to rank anything yet.')
          : '<ul class="dsc-mini">' + rows.slice(0, 5).map(function (r) {
              return '<li><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' +
                esc(r.symbol) + '</a><span class="tnum">' + num(r.composite, 0) + '</span></li>';
            }).join('') + '</ul>' +
            quiet('Ranked on how much of the advance happened on delivered volume rather than intraday churn.');
      slot('dsc-deliv', 'Delivery trends',
           body, 'discover/special', 'Open delivery trends');
    });

    get('/wow-orders?days=7', 20000).then(function (d) {
      var body;
      if (!d || d.available === false) {
        body = quiet((d && d.message) || 'The orders reader is unavailable.');
      } else {
        var c = d.counts || {};
        body = '<p class="dsc-big"><b class="tnum">' + (c.wow || 0) + '</b> ' +
          'order' + ((c.wow || 0) === 1 ? '' : 's') + ' worth noticing</p>' +
          quiet('Order value read out of the filed PDF and sized against the company that won it. ' +
                (c.value_not_disclosed || 0) + ' disclosed no value and are listed, never ranked.');
      }
      slot('dsc-wow', 'Order wins', body, 'discover/wow', 'Open WOW orders');
    });
  }

  function slot(id, title, body, goto_, cta) {
    var n = $(id);
    if (n) n.innerHTML = card('is-small', title, '', body, goto_, cta);
  }

  /* ── Mounting ───────────────────────────────────────────────────────────── */

  var last = 0;

  function open(force) {
    if (!$('dsc-market')) return;
    var now = Date.now();
    if (!force && last && now - last < FRESH_MS) return;
    last = now;
    market();
    setups();
    activity();
    var disc = $('dsc-disc');
    if (disc) {
      disc.textContent = 'Observations, not recommendations. Nothing on this page ' +
        'is a solicitation to buy or sell any security, and no position is ' +
        'suggested in any of the names above.';
    }
  }

  window.AltahaDiscover = { open: open, refresh: function () { open(true); } };

  /* The tab handler in index.html calls open() on switch. This catches the
     case where the view is already on screen because the hash pointed here on
     load, which happens before that handler exists. */
  function boot() {
    var v = $('view-discover');
    if (v && v.style.display !== 'none') open(false);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 400); });
  } else {
    setTimeout(boot, 400);
  }
  setInterval(boot, 2000);
})();
