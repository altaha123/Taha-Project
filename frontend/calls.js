/* Altaha — Track record

   WHAT THIS TAB IS FOR
   The Ideas list is rebuilt from the latest scan every time it loads, so it
   has no memory. A name that has sat on it since Monday looks the same as one
   that arrived this morning, and a call that was dropped simply vanishes. This
   tab is the memory: every idea the list has generated, grouped by the day it
   was generated, with the time, the price, and what it has returned from that
   day to the latest scan as if nothing was done after. Where the list itself
   later closed the call — a stop, a target, or the day it left the list —
   that is shown beside it, with everything else that happened on the way.

   It used to be two tabs. "Call log" dated the calls and "Track record"
   scored a second, hand-added list of them; they were one question — what
   did the ideas do — answered from two ledgers. This is the one page, and
   #research/tracker opens it.

   The record itself lives on the server (backend/call_log.py) and is written
   once per scan, so every reader sees the same history and none of it depends
   on this browser.

   It also gives every row on the Universe scan list a stamp — "Called Mon
   26 Oct at ₹101 · +4.9% since" — through AltahaCalls.stamp(), so the date an
   idea was generated is visible where the idea is, not only here.
*/

(function () {
  'use strict';
  if (window.AltahaCalls) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var S = { data: null, horizon: 'all', status: 'all', q: '', day: '', open: {},
            built: false, loading: false, retries: 0, error: null };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function finite(v) { return v !== null && v !== '' && isFinite(v); }
  function inr(v) {
    if (!finite(v)) return '—';
    return '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pct(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2) + '%';
  }
  function tone(v) { return !finite(v) ? '' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'dn' : ''; }
  function istToday() { return new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10); }
  function istYesterday() { return new Date(Date.now() + 330 * 60000 - 864e5).toISOString().slice(0, 10); }
  function still() {
    try {
      return document.documentElement.dataset.motion === 'off' ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) { return false; }
  }

  var STANCE = { 'BUY ZONE': 'buy', 'BREAKOUT WATCH': 'watch', 'AVOID': 'avoid' };
  function stanceCls(s) { return STANCE[s] || 'wait'; }
  function stanceChip(s) {
    return '<span class="cl-stance ' + stanceCls(s) + '">' + esc(s || 'On the list') + '</span>';
  }

  var OUTCOME = {
    live: ['On the list', 'live'],
    target: ['Target reached', 'win'],
    stop: ['Stop hit', 'loss'],
    dropped: ['Dropped from the list', 'gone']
  };
  var EVENT = {
    called: 'Called', stance: 'Stance changed', levels: 'Levels redrawn',
    target: 'Target reached', stop: 'Stop hit', dropped: 'Dropped from the list'
  };

  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 20000);
    return fetch(API + path, ctl ? { signal: ctl.signal } : {})
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().then(function (j) { if (!r.ok) throw new Error(j && j.detail || ('HTTP ' + r.status)); return j; });
      });
  }

  /* ── The stamp on each Universe scan row ─────────────────────────────── */

  function dayWord(c) {
    if (!c) return '';
    if (c.date === istToday()) return 'today';
    if (c.date === istYesterday()) return 'yesterday';
    return c.day ? c.day.replace(/ \d{4}$/, '') : c.date;
  }

  function stamp(call, symbol) {
    if (!call || !call.called) return '';
    var c = call.called, fresh = c.date === istToday();
    return '<button type="button" class="cl-stamp' + (fresh ? ' fresh' : '') + '" data-calls-sym="' + esc(symbol || '') + '" ' +
      'title="Open this idea in the Track record">' +
      '<span class="cl-stamp-dot" aria-hidden="true"></span>' +
      (fresh ? '<b>New today</b> · ' + esc(c.time) : 'Called <b>' + esc(dayWord(c)) + '</b> · ' + esc(c.time)) +
      (finite(call.called_price) ? ' at ' + inr(call.called_price) : '') +
      (finite(call.move_pct) && !fresh ? ' · <span class="' + tone(call.move_pct) + '">' + pct(call.move_pct) + '</span> since' : '') +
      '</button>';
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-calls-sym]');
    if (!b) return;
    e.preventDefault();
    S.q = b.dataset.callsSym || '';
    S.day = '';
    if (window.AltahaNav) window.AltahaNav.go('research', 'calls', true);
    else location.hash = '#research/calls';
  });

  /* ── The tab ─────────────────────────────────────────────────────────── */

  var SHARE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/>' +
    '<path d="M12 3v13"/><path d="M8 7l4-4 4 4"/></svg>';

  function shell() {
    return '<div class="cl">' +
      '<header class="cl-head">' +
        '<p class="cl-kick">Ideas · our record</p>' +
        '<h2>Track record</h2>' +
        '<p class="cl-lede">Every idea, recorded the day it was generated — the date, the time and the price — ' +
          'and what it has returned since, with nothing done after.</p>' +
      '</header>' +
      '<div class="cl-stats" id="cl-stats" aria-live="polite"></div>' +
      '<div class="cl-strip" id="cl-strip" role="group" aria-label="Ideas per day, last two weeks"></div>' +
      '<div class="cl-tools">' +
        '<div class="seg mono" id="cl-hz" role="group" aria-label="List">' +
          '<button type="button" data-v="all" class="active" aria-pressed="true">All</button>' +
        '</div>' +
        '<div class="seg mono" id="cl-st" role="group" aria-label="Status">' +
          '<button type="button" data-v="all" class="active" aria-pressed="true">All</button>' +
          '<button type="button" data-v="open" aria-pressed="false">Open</button>' +
          '<button type="button" data-v="closed" aria-pressed="false">Closed</button>' +
        '</div>' +
        '<label class="cl-search"><span class="cl-sr">Find a stock</span>' +
          '<input id="cl-q" type="search" placeholder="Find a stock" autocomplete="off" spellcheck="false"></label>' +
        '<a class="cl-csv" id="cl-csv" href="' + esc(API + '/calls/export.csv') + '" download>Download CSV</a>' +
        '<button type="button" class="cl-csv cl-share" id="cl-share" data-share="{&quot;kind&quot;:&quot;record&quot;}">' +
          SHARE_ICON + 'Share the record</button>' +
      '</div>' +
      '<div class="cl-filter" id="cl-filter" hidden></div>' +
      '<div class="cl-feed" id="cl-feed"><div class="cl-skel"></div><div class="cl-skel"></div><div class="cl-skel"></div></div>' +
      '<p class="cl-method" id="cl-method"></p>' +
    '</div>';
  }

  /* The lists the record actually holds, in the order the server names them.
     The buttons used to be fixed at "Short term" and "Medium term", two lists
     that were retired — so on a record made of the four lists that replaced
     them, both filters emptied the page. */
  function horizonButtons(d) {
    var hs = (d && d.horizons) || [];
    if (S.horizon !== 'all' && !hs.some(function (h) { return h.key === S.horizon; })) S.horizon = 'all';
    var key = JSON.stringify(hs);
    if (S.hzKey === key) return;
    S.hzKey = key;
    var host = $('cl-hz');
    host.hidden = hs.length < 2;
    host.innerHTML = [{ key: 'all', label: 'All' }].concat(hs).map(function (h) {
      var on = S.horizon === h.key;
      return '<button type="button" data-v="' + esc(h.key) + '"' + (on ? ' class="active"' : '') +
        ' aria-pressed="' + (on ? 'true' : 'false') + '">' + esc(h.label) + '</button>';
    }).join('');
  }

  function build() {
    var v = $('view-calls');
    if (!v || S.built) return;
    v.innerHTML = shell();
    S.built = true;
    [['cl-hz', 'horizon'], ['cl-st', 'status']].forEach(function (pair) {
      $(pair[0]).addEventListener('click', function (e) {
        var b = e.target.closest('button[data-v]');
        if (!b) return;
        S[pair[1]] = b.dataset.v;
        this.querySelectorAll('button').forEach(function (x) {
          var on = x === b;
          x.classList.toggle('active', on);
          x.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        render();
      });
    });
    var q = $('cl-q'), t = null;
    q.addEventListener('input', function () {
      clearTimeout(t);
      t = setTimeout(function () { S.q = q.value.trim().toUpperCase(); render(); }, 120);
    });
    $('cl-strip').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-day]');
      if (!b) return;
      S.day = S.day === b.dataset.day ? '' : b.dataset.day;
      render();
    });
    $('cl-filter').addEventListener('click', function (e) {
      if (!e.target.closest('button')) return;
      S.day = ''; S.q = ''; $('cl-q').value = '';
      render();
    });
    $('cl-feed').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-open]');
      if (!b) return;
      var id = b.dataset.open, card = b.closest('.cl-call');
      S.open[id] = !S.open[id];
      card.classList.toggle('open', !!S.open[id]);
      b.setAttribute('aria-expanded', S.open[id] ? 'true' : 'false');
    });
  }

  function load() {
    if (S.loading) return;
    S.loading = true;
    get('/calls?limit=1000', 25000).then(function (d) {
      S.data = d; S.error = null;
    }).catch(function (e) {
      S.error = e && e.message || 'unreachable';
    }).then(function () {
      S.loading = false;
      render();
      // A scan nobody had opened is written in the background on the first
      // read. Come back for it a few times rather than show an empty log.
      if (S.data && S.data.recording && S.retries < 4) { S.retries++; setTimeout(load, 7000); }
      else S.retries = 0;
    });
  }

  function count(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  /* What the ideas returned comes first, then what the market did over the
     same days, then what the list itself did with them. */
  function stats(d) {
    var s = d.summary || {}, o = s.outcomes || {};
    function tile(label, value, note, cls) {
      return '<div class="cl-stat"><span>' + label + '</span><b class="' + (cls || '') + '">' + value + '</b><small>' + note + '</small></div>';
    }
    var tiles = [
      tile('Ideas recorded', esc(s.calls || 0), s.first_logged ? 'since ' + esc(s.first_logged) : 'from the next scan'),
      tile('Average return', pct(s.avg_since_pct),
           s.since_priced ? 'since each idea, nothing done after' : 'no prices yet', tone(s.avg_since_pct)),
      tile('Up since the idea', s.since_priced ? esc(s.up_since) + ' of ' + esc(s.since_priced) : '—',
           s.up_since_pct != null ? esc(s.up_since_pct) + '% · median ' + pct(s.median_since_pct) : 'no prices yet')
    ];
    if (s.index_priced) {
      tiles.push(tile('Against the index', pct(s.avg_vs_index_pct),
        esc(s.beat_index) + ' of ' + esc(s.index_priced) + ' beat ' + esc(d.index_name || 'the index') +
        ' (' + pct(s.avg_index_pct) + ') over the same days', tone(s.avg_vs_index_pct)));
    }
    tiles.push(tile('Open now', esc(s.open || 0), 'still on the list'));
    tiles.push(tile('Targets · stops', esc(o.target || 0) + ' · ' + esc(o.stop || 0),
      esc(o.dropped || 0) + ' dropped from the list'));
    return tiles.join('');
  }

  function strip(days) {
    var top = Math.max.apply(null, days.map(function (x) { return x.calls; }).concat([1]));
    return days.map(function (x, i) {
      var h = x.calls ? Math.max(8, Math.round(x.calls / top * 58)) : 3;
      var on = S.day === x.date;
      return '<button type="button" class="cl-bar' + (on ? ' on' : '') + (x.calls ? '' : ' none') + '" data-day="' + esc(x.date) + '"' +
        ' aria-pressed="' + (on ? 'true' : 'false') + '" style="--h:' + h + 'px;--i:' + i + '"' +
        ' aria-label="' + esc(x.weekday + ' ' + x.label + ': ' + count(x.calls, 'idea', 'ideas')) + '">' +
        '<span class="cl-bar-n">' + (x.calls || '') + '</span><i aria-hidden="true"></i>' +
        '<span class="cl-bar-d">' + esc(x.weekday.charAt(0)) + '<small>' + esc(x.label.split(' ')[0]) + '</small></span></button>';
    }).join('');
  }

  function levels(r) {
    var bits = [];
    if (finite(r.entry)) bits.push('<span><small>Buy near</small>' + inr(r.entry) + '</span>');
    if (finite(r.stop)) bits.push('<span><small>Stop</small>' + inr(r.stop) + '</span>');
    if (finite(r.target)) bits.push('<span><small>Target</small>' + inr(r.target) + '</span>');
    if (finite(r.rr)) bits.push('<span><small>R:R</small>1:' + esc(r.rr) + '</span>');
    return bits.length ? '<div class="cl-levels">' + bits.join('') + '</div>' : '';
  }

  function timeline(r) {
    return '<ol class="cl-tl">' + (r.events || []).map(function (e) {
      var at = e.at || {};
      return '<li class="k-' + esc(e.kind) + '"><span class="cl-tl-when"><b>' + esc(at.weekday || '') + '</b> ' +
        esc((at.day || '').replace(/^\w+ /, '')) + ' · ' + esc(at.time || '') + '</span>' +
        '<span class="cl-tl-what"><b>' + esc(EVENT[e.kind] || e.kind) + '</b>' +
        (finite(e.price) ? ' at ' + inr(e.price) : '') + (e.note ? ' — ' + esc(e.note) : '') + '</span></li>';
    }).join('') + '</ol>';
  }

  function days(n) { return n == null ? '' : n === 0 ? 'the same day' : count(n, 'day', 'days'); }
  function shortDay(w) { return w && w.day ? w.day.replace(/ \d{4}$/, '') : ''; }

  /* One idea. The line of prices is always the same sentence: the price on
     the day of the idea, the price now, and the return between them with
     nothing done after. A call the list has closed gets a second line saying
     where the list left it, which is a different number once the stock has
     kept moving. */
  function card(r, i) {
    var o = OUTCOME[r.status === 'open' ? 'live' : (r.outcome || 'dropped')] || OUTCOME.dropped;
    var closed = r.status !== 'open';
    var atClose = r.since_basis === 'close';
    var openNow = !!S.open[r.id];
    var note = atClose
      ? 'to its closing price · no longer in the scan'
      : (r.since_days === 0 ? 'since the idea, today' : 'in ' + days(r.since_days) + ', nothing done after') +
        (closed ? '' : ' · ' + count(r.scans_seen, 'scan', 'scans'));
    var vs = finite(r.index_pct)
      ? '<span class="cl-vs">Index ' + pct(r.index_pct) + ' over the same days · <b class="' + tone(r.vs_index_pct) + '">' +
        pct(r.vs_index_pct) + '</b> against it</span>'
      : '';
    var left = closed && !atClose
      ? '<p class="cl-left ' + o[1] + '"><b>' + esc(o[0]) + '</b> ' + esc(shortDay(r.closed)) +
        (finite(r.price_now) ? ' at ' + inr(r.price_now) : '') +
        (finite(r.move_pct) ? ' · <span class="' + tone(r.move_pct) + '">' + pct(r.move_pct) + '</span> from the idea' : '') +
        (r.days != null ? ' · after ' + esc(days(r.days)) : '') + '</p>'
      : '';
    return '<article class="cl-call ' + o[1] + (openNow ? ' open' : '') + '" style="--i:' + Math.min(i, 12) + '">' +
      '<div class="cl-time"><b>' + esc((r.called || {}).time || '') + '</b><i aria-hidden="true"></i></div>' +
      '<div class="cl-body">' +
        '<div class="cl-row1">' +
          '<a class="cl-sym" href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.symbol) + '</a>' +
          '<span class="cl-name">' + esc(r.name || '') + '</span>' +
          stanceChip(r.called_stance) +
          '<span class="cl-out ' + o[1] + '">' + esc(o[0]) + '</span>' +
        '</div>' +
        '<div class="cl-row2">' + esc(r.setup || 'Idea') + ' · ' + esc(r.horizon_label || '') +
          (r.hold ? ' · typical hold ' + esc(r.hold) : '') + (r.sector ? ' · ' + esc(r.sector) : '') + '</div>' +
        '<div class="cl-prices">' +
          '<span class="cl-px"><small>Price at the idea</small><b>' + inr(r.called_price) + '</b></span>' +
          '<span class="cl-arrow" aria-hidden="true">→</span>' +
          '<span class="cl-px"><small>' + (atClose ? 'Closed at' : 'Latest scan') + '</small><b>' + inr(r.since_price) + '</b></span>' +
          '<span class="cl-move ' + tone(r.since_pct) + '">' + pct(r.since_pct) + '</span>' +
          '<span class="cl-span">' + esc(note) + '</span>' +
        '</div>' +
        vs + left +
        levels(r) +
        '<button type="button" class="cl-more" data-open="' + esc(r.id) + '" aria-expanded="' + (openNow ? 'true' : 'false') + '">' +
          'Timeline <span>' + esc((r.events || []).length) + '</span></button>' +
        '<div class="cl-tlwrap">' + timeline(r) + '</div>' +
      '</div>' +
    '</article>';
  }

  function dayHead(date, sample, n) {
    var c = sample.called || {};
    var word = date === istToday() ? 'Today' : date === istYesterday() ? 'Yesterday' : (c.weekday || '');
    return '<div class="cl-day"><h3>' + esc(word) + '</h3><span>' +
      esc(word === c.weekday ? (c.day || '').replace(/^\w+ /, '') : (c.weekday || '') + ' ' + (c.day || '').replace(/^\w+ /, '')) +
      '</span><b>' + count(n, 'idea', 'ideas') + '</b></div>';
  }

  function filtered(rows) {
    return rows.filter(function (r) {
      if (S.horizon !== 'all' && r.horizon !== S.horizon) return false;
      if (S.status !== 'all' && r.status !== S.status) return false;
      if (S.day && (r.called || {}).date !== S.day) return false;
      if (S.q && r.symbol.indexOf(S.q) === -1 && String(r.name || '').toUpperCase().indexOf(S.q) === -1) return false;
      return true;
    });
  }

  function render() {
    if (!S.built) return;
    var feed = $('cl-feed');
    if (S.error && !S.data) {
      feed.innerHTML = '<p class="cl-empty">The track record could not be read just now (' + esc(S.error) + '). It will load when the engine answers.</p>';
      return;
    }
    var d = S.data;
    if (!d) return;
    $('cl-stats').innerHTML = stats(d);
    horizonButtons(d);
    /* The share card posts these same figures, so its text is filled from
       this response. setAttribute takes a string, not markup. */
    $('cl-share').setAttribute('data-share', JSON.stringify(
      Object.assign({ kind: 'record', index_name: d.index_name || null }, d.summary || {})));
    // Rebuilt only when the days change, so the bars grow in once rather
    // than replaying on every filter tap; the pressed day is a class flip.
    var key = JSON.stringify(d.by_day || []);
    if (S.stripKey !== key) { $('cl-strip').innerHTML = strip(d.by_day || []); S.stripKey = key; }
    $('cl-strip').querySelectorAll('.cl-bar').forEach(function (b) {
      var on = b.dataset.day === S.day;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    var q = $('cl-q');
    if (q && q.value.trim().toUpperCase() !== S.q) q.value = S.q;
    var f = $('cl-filter'), bits = [];
    if (S.day) bits.push('on ' + S.day);
    if (S.q) bits.push('matching “' + S.q + '”');
    f.hidden = !bits.length;
    f.innerHTML = bits.length ? 'Showing ideas ' + esc(bits.join(' ')) + ' <button type="button">Show all</button>' : '';

    var rows = filtered(d.rows || []);
    if (!rows.length) {
      feed.innerHTML = '<p class="cl-empty">' + (d.total
        ? 'No idea matches these filters.'
        : d.recording
          ? 'Writing the latest scan into the record now — this takes a few seconds.'
          : 'No ideas recorded yet. The record starts with the next universe scan: every idea from then on is dated here, with its price and what it returns.') + '</p>';
    } else {
      var html = [], lastDay = null, group = [];
      var flush = function () {
        if (!group.length) return;
        html.push('<section class="cl-group">' + dayHead(lastDay, group[0], group.length) +
          group.map(card).join('') + '</section>');
        group = [];
      };
      rows.forEach(function (r) {
        var day = (r.called || {}).date || '';
        if (day !== lastDay) { flush(); lastDay = day; }
        group.push(r);
      });
      flush();
      feed.innerHTML = html.join('');
      if (still()) feed.classList.add('cl-still');
    }
    $('cl-method').textContent = [d.method, d.latest_scan ? 'Latest scan: ' + d.latest_scan + '.' : '', d.disclaimer || '']
      .filter(Boolean).join(' ');
  }

  function open() {
    build();
    render();
    load();
  }

  // A #research/calls address can switch to the tab before this deferred file
  // has run, and then nobody called open(). Check once the page has settled.
  function openIfShowing() {
    var v = $('view-calls');
    if (v && v.style.display === 'block' && !S.built) open();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(openIfShowing, 0); });
  else setTimeout(openIfShowing, 0);

  window.AltahaCalls = { open: open, reload: load, stamp: stamp };
})();
