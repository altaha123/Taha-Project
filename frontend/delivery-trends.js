/* ═══════════════════════════════════════════════════════════════════════════
   Delivery trends — where delivery is unusual now.

   The tab carried this name for a long time while showing something else: a
   one-year ranking that skips the most recent month on purpose. Nothing that
   happened this week could appear in it. This is the reading the name asks
   for — each stock against its own normal, in the latest session, across the
   week, and quietly over a month — from /delivery/trends.

   Every number on a row is one a reader can redo from the exchange's file:
   rupees delivered, the usual day's rupees, the share of volume delivered and
   its own average. There is no score here.

   The rendering is pure (state in, HTML out) so the node test can read it;
   the wiring at the bottom only runs in a browser.
   ═══════════════════════════════════════════════════════════════════════════ */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AltahaDeliveryTrends = api;
  if (typeof document !== 'undefined') api.wire();
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var VIEWS = [
    { id: 'today', label: 'Spikes today', empty: 'No stock delivered twice its usual rupees in the latest session at this size.' },
    { id: 'week', label: 'Building all week', empty: 'No stock held delivery above normal across the week at this size.' },
    { id: 'quiet', label: 'Quiet build-up', empty: 'No stock shows a month of rising delivery on a still price at this size.' }
  ];
  var DIRS = [
    { id: 'all', label: 'All' },
    { id: 'up', label: 'Price up' },
    { id: 'down', label: 'Price down' }
  ];

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v) {
    return v !== null && v !== undefined && v !== '' && isFinite(Number(v)) ? Number(v) : null;
  }
  /* Rupees crore, at the precision the size deserves. */
  function cr(v) {
    var n = num(v);
    if (n === null) return '—';
    var a = Math.abs(n);
    var d = a >= 100 ? 0 : a >= 10 ? 1 : 2;
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }) + ' cr';
  }
  function pct(v, d) { var n = num(v); return n === null ? '—' : n.toFixed(d == null ? 0 : d) + '%'; }
  function signed(v, d, unit) {
    var n = num(v);
    if (n === null) return '—';
    var s = Math.abs(n).toFixed(d == null ? 1 : d);
    return (n > 0 ? '+' : n < 0 ? '−' : '') + s + (unit || '');
  }
  function times(v) {
    var n = num(v);
    if (n === null) return '—';
    return (n >= 10 ? n.toFixed(0) : n.toFixed(1)) + '×';
  }
  function tone(v) { var n = num(v); return n === null || n === 0 ? '' : n > 0 ? ' up' : ' dn'; }
  /* Assembled by hand: toLocaleDateString puts the commas in different places
     on different browsers, and this line is the one that dates the page. */
  var DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(v) {
    var d = new Date(String(v) + 'T12:00:00Z');
    return isFinite(d.getTime())
      ? DOW[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear()
      : String(v || '');
  }

  /* The sentence under a row. Built from the same fields the row prints, so
     the words and the numbers cannot disagree. */
  function reading(view, r) {
    var c = num(r.chg_pct), move;
    if (view === 'today') {
      move = c === null ? '' : c > 0 ? ', as the price rose ' + pct(c, 1) : c < 0 ? ', as the price fell ' + pct(-c, 1) : ', with the price unchanged';
      var where = num(r.close_loc) === null ? '' : r.close_loc >= 0.75 ? ' It closed near the day’s high.' : r.close_loc <= 0.25 ? ' It closed near the day’s low.' : '';
      return cr(r.delivered_cr) + ' of shares were taken to delivery, ' + times(r.mult) + ' its usual ' + cr(r.usual_cr) + ' day' + move + '. ' +
        pct(r.deliv_pct) + ' of the volume was delivered against a usual ' + pct(r.usual_pct) + '.' + where;
    }
    if (view === 'week') {
      move = c === null ? '' : c > 0 ? ' The price is up ' + pct(c, 1) + ' over the five sessions.' : c < 0 ? ' The price is down ' + pct(-c, 1) + ' over the five sessions.' : ' The price is unchanged over the five sessions.';
      return 'A typical day this week saw ' + cr(r.delivered_cr) + ' delivered, ' + times(r.mult) + ' the usual ' + cr(r.usual_cr) +
        (num(r.days_above) === null ? '' : ', with ' + r.days_above + ' of the last 5 sessions above normal') + '.' +
        (num(r.week_cr) === null ? '' : ' ' + cr(r.week_cr) + ' in all.') + move;
    }
    return 'Over the last 20 sessions ' + pct(r.deliv_pct) + ' of the volume was delivered, against ' + pct(r.usual_pct) +
      ' in the 60 before, on ' + times(r.mult) + ' the rupees. The price has moved ' + signed(c, 1, '%') + ' in that time.';
  }

  /* Twenty sessions of rupees delivered. Bars, because each is a separate
     day's total and a line would draw a path between them that nobody traded.
     `hot` is how many of the newest bars the row is about. */
  function spark(values, usual, hot) {
    var v = (values || []).map(num), max = 0, i;
    for (i = 0; i < v.length; i++) if (v[i] !== null && v[i] > max) max = v[i];
    var u = num(usual);
    if (u !== null && u > max) max = u;
    if (!v.length || !(max > 0)) return '<span class="dt-spark dt-spark-none" aria-hidden="true"></span>';
    var W = 100, H = 30, step = W / v.length, bw = Math.max(1.5, step - 1.4), out = '';
    for (i = 0; i < v.length; i++) {
      if (v[i] === null) continue;
      var h = Math.max(1, v[i] / max * H);
      out += '<rect' + (i >= v.length - hot ? ' class="hot"' : '') + ' x="' + (i * step).toFixed(2) + '" y="' + (H - h).toFixed(2) +
        '" width="' + bw.toFixed(2) + '" height="' + h.toFixed(2) + '" rx="1"/>';
    }
    var line = u === null ? '' : '<line x1="0" x2="' + W + '" y1="' + (H - u / max * H).toFixed(2) + '" y2="' + (H - u / max * H).toFixed(2) + '"/>';
    return '<svg class="dt-spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' + out + line + '</svg>';
  }

  function row(view, r) {
    var hot = view === 'today' ? 1 : view === 'week' ? 5 : 20;
    var sub = [r.name, r.industry].filter(Boolean).map(esc).join(' · ') ||
      'Trades about ' + esc(cr(r.turnover_cr)) + ' a day';
    return '<details class="dt-row" data-sym="' + esc(r.symbol) + '"><summary>' +
      '<span class="dt-id"><span class="dt-sym">' + esc(r.symbol) + '</span><span class="dt-sub">' + sub + '</span></span>' +
      '<span class="dt-chart">' + spark(r.spark_cr, r.usual_cr, hot) + '</span>' +
      '<span class="dt-fig"><b>' + esc(times(r.mult)) + '</b><small>' + esc(cr(r.delivered_cr)) + ' vs ' + esc(cr(r.usual_cr)) + '</small></span>' +
      '<span class="dt-fig dt-share"><b>' + esc(pct(r.deliv_pct)) + '</b><small>usual ' + esc(pct(r.usual_pct)) + '</small></span>' +
      '<span class="dt-fig dt-px"><b class="dt-chg' + tone(r.chg_pct) + '">' + esc(signed(r.chg_pct, 1, '%')) + '</b><small>₹' +
        (num(r.price) === null ? '—' : Number(r.price).toLocaleString('en-IN', { maximumFractionDigits: 2 })) + '</small></span>' +
      '</summary><div class="dt-open"><p>' + esc(reading(view, r)) + '</p>' +
      '<p class="dt-links"><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '&amp;pane=deliv">Every session for ' + esc(r.symbol) + ' →</a>' +
      '<span>Trades about ' + esc(cr(r.turnover_cr)) + ' on a usual day</span></p></div></details>';
  }

  function tile(k, v, n) {
    return '<div class="dt-tile"><div class="k">' + esc(k) + '</div><div class="v">' + v + '</div><div class="n">' + n + '</div></div>';
  }

  function tiles(d) {
    var m = d.market || {}, v = d.views || {}, t = v.today || {}, w = v.week || {}, q = v.quiet || {};
    return '<div class="dt-tiles">' +
      tile('Market delivered share', esc(pct(m.share_pct, 1)),
        num(m.pp) === null ? 'of all rupees traded' : esc(signed(m.pp, 1, ' pts')) + ' against its 20-session average') +
      tile('Rupees delivered', esc(cr(m.delivered_cr)),
        num(m.mult) === null ? 'across the exchange' : esc(times(m.mult)) + ' a usual session') +
      tile('Spikes today', String(t.total == null ? '—' : t.total),
        '<span class="dt-chg up">' + (t.up || 0) + '</span> on a rise · <span class="dt-chg dn">' + (t.down || 0) + '</span> on a fall') +
      tile('Building all week', String(w.total == null ? '—' : w.total),
        q.unavailable ? 'held above normal for five sessions' : (q.total || 0) + ' more building quietly over a month') +
      '</div>';
  }

  function seg(name, items, active, label) {
    return '<div class="seg dt-seg" role="group" aria-label="' + esc(label) + '">' + items.map(function (it) {
      return '<button type="button" data-' + name + '="' + esc(it.id) + '"' + (String(it.id) === String(active) ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + '>' +
        esc(it.label) + (it.count == null ? '' : ' <span class="dt-count">' + it.count + '</span>') + '</button>';
    }).join('') + '</div>';
  }

  function controls(d, s) {
    var v = d.views || {};
    var views = VIEWS.map(function (x) { return { id: x.id, label: x.label, count: (v[x.id] || {}).total }; });
    var floors = (d.floors_cr || [2, 10, 50]).map(function (f) { return { id: f, label: '₹' + f + ' cr' }; });
    return '<div class="dt-controls">' + seg('view', views, s.view, 'Which list') +
      '<div class="dt-filters">' +
        (s.view === 'quiet' ? '' : seg('dir', DIRS, s.dir, 'Price direction')) +
        '<label class="dt-floor"><span>Trades at least</span>' + seg('floor', floors, d.min_turnover_cr, 'Smallest daily turnover') + '<span>a day</span></label>' +
      '</div></div>';
  }

  function list(d, s) {
    var meta = VIEWS.filter(function (x) { return x.id === s.view; })[0] || VIEWS[0];
    var v = (d.views || {})[meta.id] || { rows: [] };
    var rows = (v.rows || []).filter(function (r) {
      if (meta.id === 'quiet' || s.dir === 'all') return true;
      var c = num(r.chg_pct);
      return c !== null && (s.dir === 'up' ? c > 0 : c < 0);
    });
    var capped = (v.total || 0) > (v.rows || []).length
      ? '<p class="dt-capped">The ' + (v.rows || []).length + ' most unusual of ' + v.total + ' are listed.</p>' : '';
    var head = '<div class="dt-head" aria-hidden="true"><span>Stock</span><span class="dt-chart">Rupees delivered, 20 sessions</span>' +
      '<span>Against its usual day</span><span class="dt-share">Share delivered</span><span class="dt-px">' +
      (meta.id === 'today' ? 'Day' : meta.id === 'week' ? '5 sessions' : '20 sessions') + '</span></div>';
    var body = v.unavailable ? '<div class="dt-empty">' + esc(v.rule || '') + '</div>'
      : rows.length ? head + rows.map(function (r) { return row(meta.id, r); }).join('')
      : '<div class="dt-empty">' + esc(meta.empty) + '</div>';
    return '<p class="dt-rule">' + (v.unavailable ? '' : esc(v.rule || '')) + '</p><div class="dt-list">' + body + '</div>' + capped;
  }

  function sectors(d) {
    var all = d.sectors || [];
    if (!all.length) return '';
    var max = 1;
    all.forEach(function (x) { if (num(x.mult) !== null && x.mult > max) max = x.mult; });
    var scale = Math.max(1.5, max);
    function one(x) {
      var m = num(x.mult) || 0;
      return '<div class="dt-sec"><span class="n">' + esc(x.industry) + '<small>' + x.members + ' stocks</small></span>' +
        '<span class="b" aria-hidden="true"><i class="' + (m >= 1.15 ? 'hi' : m < 0.9 ? 'lo' : '') + '" style="width:' + Math.max(2, m / scale * 100).toFixed(1) + '%"></i>' +
          '<u style="left:' + (1 / scale * 100).toFixed(1) + '%"></u></span>' +
        '<span class="m"><b>' + esc(times(x.mult)) + '</b><small>' + esc(cr(x.delivered_cr)) + ' a day</small></span>' +
        '<span class="s"><b>' + esc(pct(x.share_pct)) + '</b><small>' + esc(signed(x.pp, 1, ' pts')) + '</small></span>' +
        '<span class="c"><b class="dt-chg' + tone(x.chg_pct) + '">' + esc(signed(x.chg_pct, 1, '%')) + '</b><small>median stock</small></span></div>';
    }
    var top = all.slice(0, 8), rest = all.slice(8);
    return '<section class="dt-sectors"><div class="dt-sechead"><h3>Where the rupees went this week</h3>' +
      '<p>A typical day of the last five sessions against a usual day of the twenty before, by industry. The tick marks a usual day.</p></div>' +
      '<div class="dt-sechdr" aria-hidden="true"><span>Industry</span><span></span><span>Against usual</span><span>Share delivered</span><span>5 sessions</span></div>' +
      top.map(one).join('') +
      (rest.length ? '<details class="dt-more"><summary>' + rest.length + ' more industries</summary>' + rest.map(one).join('') + '</details>' : '') +
      '<p class="dt-secnote">Covers the ' + (d.sector_coverage || 0) + ' companies in NSE’s Nifty Total Market list, the only ones with a published industry. The lists above cover every stock.</p></section>';
  }

  function notes(d) {
    return '<details class="tabnote dt-notes"><summary>What a delivery figure can and cannot tell you</summary>' +
      '<p>NSE publishes, for every stock every day, how much of the traded volume was <b>delivered</b>: settled into somebody’s demat account, not bought and sold again before the close. Rupees delivered is that quantity at the day’s average price, worked out here from the exchange’s file.</p>' +
      (d.caveats || []).map(function (c) { return '<p>' + esc(c) + '</p>'; }).join('') +
      (d.excluded_corporate_action ? '<p>' + d.excluded_corporate_action + ' stock' + (d.excluded_corporate_action === 1 ? ' is' : 's are') +
        ' left out because the price shows a split or bonus inside the window, which would make the price change meaningless.</p>' : '') +
      '</details>';
  }

  function building(d) {
    var have = (d && d.sessions) || 0, need = (d && d.needed) || 26;
    var msg = (d && (d.message || d.detail)) || 'The delivery record could not be read just now.';
    if (!d || !d.building) return '<div class="sp-state"><b>Nothing to show yet</b>' + esc(msg) + '</div>';
    var p = Math.max(2, Math.min(100, Math.round(have / need * 100)));
    return '<div class="sp-state"><b>Reading the exchange’s delivery files</b>' + esc(msg) +
      '<span class="sp-prog"><i style="width:' + p + '%"></i></span><span class="sp-progn mono">' + have + ' / ' + need + ' sessions</span></div>';
  }

  function render(d, state) {
    var s = { view: (state && state.view) || 'today', dir: (state && state.dir) || 'all' };
    if (!d || d.available === false) return building(d);
    return '<p class="dt-asof mono">Session of ' + esc(day(d.as_of)) + ' · ' + Number(d.universe || 0).toLocaleString('en-IN') +
      ' stocks read · published by NSE after the close</p>' +
      tiles(d) + controls(d, s) + list(d, s) + sectors(d) + notes(d) +
      '<p class="dt-disc">' + esc(d.disclaimer || '') + ' Source: ' + esc(d.source || 'NSE full bhavcopy') + '.</p>';
  }

  /* ── Browser wiring ─────────────────────────────────────────────────────── */
  function wire() {
    var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
            : (window.API_BASE || 'https://taha-project.onrender.com');
    var state = { view: 'today', dir: 'all', floor: null }, data = null, asked = false, poll = null, seq = 0;
    function host() { return document.getElementById('dt-root'); }
    function shown() { var v = document.getElementById('view-special'); return !!v && v.style.display !== 'none'; }
    function paint() { var h = host(); if (h) h.innerHTML = render(data, state); }

    function load() {
      var h = host();
      if (!h) return;
      asked = true;
      var mine = ++seq;
      if (!data || data.available === false) {
        h.innerHTML = '<div class="sp-state"><b>Reading the delivery record…</b>Comparing every stock with its own usual day.</div>';
      } else { h.classList.add('is-loading'); }
      fetch(API + '/delivery/trends?limit=60' + (state.floor == null ? '' : '&min_turnover_cr=' + encodeURIComponent(state.floor)))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (mine !== seq) return;
          h.classList.remove('is-loading');
          data = d;
          paint();
          clearTimeout(poll);
          // The store fills itself in the background; keep looking only while
          // it says it is filling and this tab is the one on screen.
          if (d && d.available === false && d.building) poll = setTimeout(function () { if (shown()) load(); else asked = false; }, 20000);
        })
        .catch(function () {
          if (mine !== seq) return;
          asked = false;
          h.classList.remove('is-loading');
          h.innerHTML = '<div class="sp-state"><b>The engine is unreachable</b>If it has been idle it takes about thirty seconds to wake. ' +
            '<button type="button" class="act" data-retry>Try again</button></div>';
        });
    }

    function start() {
      var view = document.getElementById('view-special'), h = host();
      if (!view || !h) return;
      h.addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('button') : null;
        if (!b || !h.contains(b)) return;
        if (b.hasAttribute('data-retry')) return load();
        if (b.dataset.view) { state.view = b.dataset.view; return paint(); }
        if (b.dataset.dir) { state.dir = b.dataset.dir; return paint(); }
        if (b.dataset.floor) { state.floor = Number(b.dataset.floor); return load(); }
      });
      if ('MutationObserver' in window) {
        new MutationObserver(function () { if (shown() && !asked) load(); })
          .observe(view, { attributes: true, attributeFilter: ['style'] });
      }
      if (shown()) load();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  }

  return { render: render, reading: reading, row: row, spark: spark, cr: cr, times: times, signed: signed, wire: wire };
});
