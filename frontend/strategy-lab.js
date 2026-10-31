/* Altaha — Strategy lab

   WHAT THIS TAB IS FOR
   Pick a stock and see how eleven textbook trading rules would have done on
   its own past prices, measured the way quants measure a strategy (return,
   CAGR, Sharpe, worst fall, win rate, profit factor) and set beside the rule
   anyone can follow: buy it and hold it. The idea and the six headline
   numbers follow quants.md, an open library of fifty backtested strategies;
   the costs, the taxes, the luck bar and the two-halves check are this
   project's, because a pre-cost, pre-tax table of the best of eleven tries
   is the most flattering document in finance.

   The arithmetic lives on the server (backend/strategy_lab.py, /strategies).
   This file draws it. It never shows what a rule is doing today: the server
   does not send that, on purpose, and nothing here reconstructs it.

   The sizing calculators at the bottom are arithmetic on numbers the reader
   types in, prefilled from the report where the report has them.
*/

(function () {
  'use strict';
  if (window.AltahaStrategyLab) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var YEARS = [3, 5, 10, 15];
  var TRY = [['RELIANCE', 'RELIANCE'], ['HDFCBANK', 'HDFCBANK'], ['INFY', 'INFY'],
             ['TITAN', 'TITAN'], ['^NSEI', 'Nifty 50']];
  var SORTS = [
    ['library', 'Library order'], ['sharpe', 'Highest Sharpe'], ['cagr', 'Highest CAGR'],
    ['total', 'Highest total return'], ['dd', 'Shallowest worst fall'],
    ['win', 'Highest win rate'], ['pf', 'Highest profit factor'], ['tax', 'Highest after-tax CAGR']
  ];

  var S = { data: null, sym: '', years: 10, cost: '', sort: 'library', family: 'all',
            selected: null, compare: [], showAll: true, loading: false, error: null,
            built: false, linked: false, seq: 0 };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function finite(v) { return v !== null && v !== undefined && v !== '' && isFinite(v); }
  function pct(v, dp) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(dp == null ? 1 : dp) + '%';
  }
  function plain(v, dp) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v < 0 ? '−' : '') + Math.abs(v).toFixed(dp == null ? 2 : dp);
  }
  function pts(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v).toFixed(1) + ' pts';
  }
  function tone(v) { return !finite(v) ? '' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'dn' : ''; }
  function money(v, cur) {
    if (!finite(v)) return '—';
    var sym = cur === 'USD' ? '$' : '₹';
    return sym + Number(v).toLocaleString(cur === 'USD' ? 'en-US' : 'en-IN', { maximumFractionDigits: 0 });
  }
  function day(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00Z');
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function param(name) {
    try { return (new URLSearchParams(location.search).get(name) || '').trim(); } catch (e) { return ''; }
  }

  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 60000);
    return fetch(API + path, ctl ? { signal: ctl.signal } : {}).then(function (r) {
      if (timer) clearTimeout(timer);
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error((j && j.detail) || ('The server answered ' + r.status + '.'));
        return j;
      });
    }, function (e) {
      if (timer) clearTimeout(timer);
      throw new Error(e && e.name === 'AbortError'
        ? 'The server took too long. It may be waking up — try again in half a minute.'
        : 'Could not reach the server. Check the connection and try again.');
    });
  }

  /* ── Shell ───────────────────────────────────────────────────────────── */

  function shell() {
    return '<div class="sl">' +
      '<header class="sl-head">' +
        '<p class="sl-kick">Ideas · strategy lab</p>' +
        '<h2>Would a trading rule have beaten holding?</h2>' +
        '<p class="sl-lede">Eleven textbook rules, tested on one stock’s own past prices with Indian costs and ' +
        'tax, measured the way quants measure a strategy, and set beside simply buying and holding it. ' +
        'A record of the past, not a prediction or a recommendation.</p>' +
      '</header>' +
      '<form class="sl-form" id="sl-form" autocomplete="off">' +
        '<label class="sl-field sl-sym"><span>Stock</span>' +
          '<input id="sl-sym" name="sym" type="text" inputmode="text" spellcheck="false" ' +
          'placeholder="RELIANCE, TCS, AAPL, ^NSEI" aria-label="Stock symbol"></label>' +
        '<div class="sl-field"><span id="sl-years-lbl">History</span>' +
          '<div class="sl-seg" role="radiogroup" aria-labelledby="sl-years-lbl" id="sl-years">' +
          YEARS.map(function (y) {
            return '<button type="button" role="radio" data-years="' + y + '">' + y + 'y</button>';
          }).join('') + '</div></div>' +
        '<label class="sl-field sl-cost"><span>Round-trip cost %</span>' +
          '<input id="sl-cost" type="number" min="0" max="3" step="0.01" placeholder="auto" ' +
          'aria-describedby="sl-cost-help"></label>' +
        '<button class="sl-go" id="sl-go" type="submit">Run the test</button>' +
      '</form>' +
      '<p class="sl-try" id="sl-try">Try ' + TRY.map(function (t) {
        return '<button type="button" data-try="' + esc(t[0]) + '">' + esc(t[1]) + '</button>';
      }).join('') + '<small id="sl-cost-help">Cost left blank means 0.49% a round trip for Indian stocks: ' +
      'STT, stamp duty, exchange charges, GST, DP charges and a little slippage.</small></p>' +
      '<div id="sl-out" aria-live="polite"></div>' +
      '</div>';
  }

  function paintControls() {
    var seg = $('sl-years');
    if (seg) Array.prototype.forEach.call(seg.querySelectorAll('button'), function (b) {
      var on = Number(b.dataset.years) === S.years;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    var go = $('sl-go');
    if (go) { go.disabled = S.loading; go.textContent = S.loading ? 'Testing…' : 'Run the test'; }
  }

  function build() {
    var host = $('view-strategies');
    if (!host || S.built) return !!host;
    host.innerHTML = shell();
    S.built = true;
    $('sl-form').addEventListener('submit', function (e) {
      e.preventDefault();
      run($('sl-sym').value);
    });
    $('sl-years').addEventListener('click', function (e) {
      var b = e.target.closest('[data-years]');
      if (!b) return;
      S.years = Number(b.dataset.years);
      paintControls();
      if (S.sym) run(S.sym);
    });
    $('sl-try').addEventListener('click', function (e) {
      var b = e.target.closest('[data-try]');
      if (!b) return;
      $('sl-sym').value = b.dataset.try;
      run(b.dataset.try);
    });
    host.addEventListener('click', onClick);
    host.addEventListener('change', onChange);
    host.addEventListener('input', onInput);
    paintControls();
    return true;
  }

  /* ── Loading ─────────────────────────────────────────────────────────── */

  function run(sym) {
    sym = String(sym || '').trim().toUpperCase().replace(/\s+/g, '');
    if (!sym) { $('sl-sym').focus(); return; }
    S.sym = sym;
    $('sl-sym').value = sym;
    var costRaw = ($('sl-cost') && $('sl-cost').value || '').trim();
    var cost = costRaw === '' ? '' : Math.max(0, Math.min(3, Number(costRaw)));
    S.cost = isFinite(cost) ? cost : '';
    S.loading = true; S.error = null;
    var seq = ++S.seq;
    paintControls();
    $('sl-out').innerHTML = '<div class="sl-wait"><span class="sl-spin" aria-hidden="true"></span>' +
      'Reading ' + S.years + ' years of ' + esc(sym) + ' and running eleven rules… ' +
      '<small>The first request after a quiet spell can take half a minute while the server wakes.</small></div>';
    var q = '/strategies?ticker=' + encodeURIComponent(sym) + '&years=' + S.years +
      (S.cost !== '' ? '&cost=' + encodeURIComponent(S.cost) : '');
    get(q, 70000).then(function (d) {
      if (seq !== S.seq) return;
      S.loading = false;
      S.data = d;
      S.compare = [];
      S.selected = (d.luck && d.luck.best_id) || (d.strategies[0] && d.strategies[0].id);
      store('altaha.lab.sym', sym);
      paintControls();
      render();
      if (window.AltahaTrack) window.AltahaTrack('strategy_lab_run', { years: S.years });
    }, function (e) {
      if (seq !== S.seq) return;
      S.loading = false;
      S.error = e.message;
      paintControls();
      $('sl-out').innerHTML = '<div class="sl-err" role="alert"><b>No result.</b> ' + esc(e.message) +
        ' <button type="button" data-retry>Try again</button></div>';
    });
  }

  /* ── The report ──────────────────────────────────────────────────────── */

  function rowsAll() {
    return S.data ? S.data.strategies : [];
  }
  function byId(id) {
    if (!S.data) return null;
    if (id === 'hold') return S.data.hold;
    for (var i = 0; i < S.data.strategies.length; i++) if (S.data.strategies[i].id === id) return S.data.strategies[i];
    return null;
  }

  function sortKey(r) {
    var m = r.metrics;
    switch (S.sort) {
      case 'sharpe': return m.sharpe;
      case 'cagr': return m.cagr_pct;
      case 'total': return m.total_return_pct;
      case 'dd': return m.max_drawdown_pct;
      case 'win': return m.win_rate_pct;
      case 'pf': return m.profit_factor_note ? Infinity : m.profit_factor;
      case 'tax': return m.after_tax_cagr_pct;
      default: return null;
    }
  }

  function visibleRows() {
    var rows = rowsAll().filter(function (r) { return S.family === 'all' || r.family === S.family; });
    if (S.sort === 'library') return rows;
    return rows.slice().sort(function (a, b) {
      var x = sortKey(a), y = sortKey(b);
      if (!finite(x) && x !== Infinity) return 1;
      if (!finite(y) && y !== Infinity) return -1;
      return y - x;
    });
  }

  function verdict(d) {
    var s = d.summary, L = d.luck || {}, h = d.hold.metrics, inr = d.currency === 'INR';
    var growth = 1 + h.total_return_pct / 100;
    var out = '<p>Over <b>' + d.years + ' years</b> (' + esc(day(d.start)) + ' to ' + esc(day(d.end)) + '), ' +
      'simply holding <b>' + esc(d.ticker) + '</b> turned ' + (inr ? '₹1' : '$1') + ' into <b>' +
      (inr ? '₹' : '$') + growth.toFixed(2) + '</b>: ' + pct(h.cagr_pct) + ' a year, with a worst fall of ' +
      pct(h.max_drawdown_pct) + '.</p>';
    out += '<p><b>' + s.beat_hold_cagr + ' of ' + s.of + '</b> rules earned more than holding' +
      (inr && s.beat_hold_after_tax != null ? ' (<b>' + s.beat_hold_after_tax + '</b> after tax)' : '') +
      '. <b>' + s.shallower_drawdown + ' of ' + s.of + '</b> had a shallower worst fall.' +
      (s.shallower_drawdown >= s.of / 2 && s.beat_hold_cagr <= s.of / 4
        ? ' On this stock the rules bought a smoother ride, not a richer one.' : '') + '</p>';
    if (L.verdict === 'no_lead') {
      out += '<p>No rule beat holding on Sharpe, so there is no lead for luck to explain.</p>';
    } else if (L.verdict === 'within_luck') {
      out += '<p>The best, <b>' + esc(L.best_name) + '</b>, led holding’s Sharpe by ' + plain(L.best_sharpe_lead) +
        '. With about ' + L.effective_rules + ' genuinely different rules tried over ' + L.years +
        ' years, luck alone would hand the best of them a lead of about ' + plain(L.luck_bar_sharpe) +
        ' — this one is inside that.</p>';
    } else if (L.verdict === 'clears_luck') {
      out += '<p>The best, <b>' + esc(L.best_name) + '</b>, led holding’s Sharpe by ' + plain(L.best_sharpe_lead) +
        ', more than the ' + plain(L.luck_bar_sharpe) + ' luck alone would hand the best of about ' +
        L.effective_rules + ' different rules over ' + L.years + ' years. Evidence, not proof: one stock, one history.</p>';
    }
    return out;
  }

  function stat(label, big, small, cls) {
    return '<div class="sl-stat"><span>' + esc(label) + '</span><b class="' + (cls || '') + '">' + big + '</b>' +
      '<small>' + small + '</small></div>';
  }

  function render() {
    var d = S.data, out = $('sl-out');
    if (!d || !out) return;
    var h = d.hold.metrics, s = d.summary, L = d.luck || {}, inr = d.currency === 'INR';
    var html = '';
    if (d.short_history) {
      html += '<p class="sl-note">This company has a shorter history than you asked for: the test covers all ' +
        d.years + ' years of it after a one-year warm-up.</p>';
    }
    (d.warnings || []).forEach(function (w) { html += '<p class="sl-warn" role="note">' + esc(w) + '</p>'; });
    html += '<section class="sl-verdict">' + verdict(d) + '</section>';
    html += '<div class="sl-stats">' +
      stat('Holding it', pct(h.cagr_pct), 'a year · Sharpe ' + plain(h.sharpe) + ' · worst fall ' + pct(h.max_drawdown_pct, 0)) +
      stat('Rules that earned more', s.beat_hold_cagr + '<i>/' + s.of + '</i>',
        inr && s.beat_hold_after_tax != null ? s.beat_hold_after_tax + ' after tax' : 'on CAGR, before tax',
        s.beat_hold_cagr ? 'up' : '') +
      stat('Shallower worst fall', s.shallower_drawdown + '<i>/' + s.of + '</i>', 'than holding through it',
        s.shallower_drawdown ? 'up' : '') +
      stat('Luck bar', plain(L.luck_bar_sharpe), 'Sharpe lead luck gives the best of ~' + esc(L.effective_rules) + ' rules') +
      '</div>';

    html += '<section class="sl-card sl-chartcard">' +
      '<div class="sl-card-h"><h3>Growth of ' + (inr ? '₹1' : '$1') + '</h3>' +
      '<label class="sl-toggle"><input type="checkbox" id="sl-showall"' + (S.showAll ? ' checked' : '') + '> Every rule</label></div>' +
      '<div class="sl-legend" id="sl-legend"></div>' +
      '<div class="sl-chart" id="sl-chart"></div>' +
      '<h4 class="sl-sub">Below its previous high</h4>' +
      '<div class="sl-chart sl-under" id="sl-under"></div>' +
      '<p class="sl-fine">Log scale, so equal heights are equal percentage moves. Every line starts in cash on the same day.</p>' +
      '</section>';

    html += '<section class="sl-card">' +
      '<div class="sl-card-h"><h3>Every rule, measured</h3>' +
      '<label class="sl-sort">Sort <select id="sl-sort">' + SORTS.filter(function (o) { return inr || o[0] !== 'tax'; }).map(function (o) {
        return '<option value="' + o[0] + '"' + (S.sort === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
      }).join('') + '</select></label></div>' +
      '<div class="sl-chips" role="group" aria-label="Rule family">' +
      ['all'].concat(d.families || []).map(function (f) {
        var n = f === 'all' ? rowsAll().length : rowsAll().filter(function (r) { return r.family === f; }).length;
        return '<button type="button" data-family="' + esc(f) + '" class="' + (S.family === f ? 'on' : '') + '">' +
          esc(f === 'all' ? 'All' : f) + ' <small>' + n + '</small></button>';
      }).join('') + '</div>' +
      '<div class="sl-scroll" tabindex="0" role="region" aria-label="Results table"><table class="sl-table" id="sl-table"></table></div>' +
      '<p class="sl-fine">Tap a row to read it. Tick up to three to compare. Win rate and profit factor count closed trades only; ' +
      'fewer than ' + d.assumptions.min_trades + ' is marked, because a handful of trades is an anecdote.</p>' +
      '</section>';

    html += '<div id="sl-compare"></div>';
    html += '<section class="sl-card sl-detail" id="sl-detail"></section>';
    html += luckCard(d);
    html += sizingCard(d);
    html += glossary(d);
    html += assumptions(d);
    out.innerHTML = html;
    paintTable();
    paintDetail();
    paintCompare();
    paintCharts();
    refreshCalcs();
  }

  /* ── Table ───────────────────────────────────────────────────────────── */

  function cellPct(v, dp) { return '<td class="n ' + tone(v) + '">' + pct(v, dp) + '</td>'; }

  function rowHtml(r, isHold) {
    var m = r.metrics, inr = S.data.currency === 'INR';
    var few = m.few_trades && m.trades > 0;
    var pf = m.profit_factor_note ? '<span title="No losing trade">no loss</span>' : plain(m.profit_factor);
    var on = S.selected === r.id, cmp = S.compare.indexOf(r.id) >= 0;
    var vs = r.vs_hold || {};
    return '<tr class="' + (isHold ? 'hold' : '') + (on ? ' on' : '') + '" data-row="' + esc(r.id) + '" tabindex="0" ' +
      'aria-selected="' + (on ? 'true' : 'false') + '">' +
      '<td class="cmp">' + (isHold ? '' : '<input type="checkbox" aria-label="Compare ' + esc(r.name) + '" data-cmp="' + esc(r.id) + '"' +
        (cmp ? ' checked' : '') + '>') + '</td>' +
      '<th scope="row"><b>' + esc(r.name) + '</b><small>' + esc(r.family) + '</small></th>' +
      cellPct(m.total_return_pct, 0) + cellPct(m.cagr_pct) +
      (inr ? cellPct(m.after_tax_cagr_pct) : '') +
      '<td class="n ' + tone(m.sharpe) + '">' + plain(m.sharpe) + '</td>' +
      '<td class="n dn">' + pct(m.max_drawdown_pct, 0) + '</td>' +
      '<td class="n' + (few ? ' few' : '') + '">' + (m.trades ? pct(m.win_rate_pct, 0).replace('+', '') : '—') + '</td>' +
      '<td class="n' + (few ? ' few' : '') + '">' + (m.trades ? pf : '—') + '</td>' +
      '<td class="n">' + (m.trades || (isHold || m.exposure_pct >= 99 ? '<small>always in</small>' : '0')) + '</td>' +
      '<td class="n">' + Math.round(m.exposure_pct) + '%</td>' +
      '<td class="n">' + (isHold ? '—' : (vs.years_full ? vs.years_beat + '/' + vs.years_full : '—')) + '</td>' +
      '<td class="c">' + (isHold ? '' : (r.consistent ? '<span class="sl-yes" title="Beat cash in both halves">✓</span>' : '<span class="sl-no" title="Did not beat cash in both halves">·</span>')) + '</td>' +
      '</tr>';
  }

  function paintTable() {
    var t = $('sl-table');
    if (!t || !S.data) return;
    var inr = S.data.currency === 'INR';
    var head = '<thead><tr><th class="cmp"><span class="sl-sr">Compare</span></th><th scope="col">Rule</th>' +
      '<th scope="col" class="n">Return</th><th scope="col" class="n">CAGR</th>' +
      (inr ? '<th scope="col" class="n" title="Estimated CAGR after Indian capital gains tax">After tax</th>' : '') +
      '<th scope="col" class="n">Sharpe</th><th scope="col" class="n">Worst fall</th>' +
      '<th scope="col" class="n">Win rate</th><th scope="col" class="n">Profit factor</th>' +
      '<th scope="col" class="n">Trades</th><th scope="col" class="n">In market</th>' +
      '<th scope="col" class="n" title="Full calendar years the rule beat holding">Years ahead</th>' +
      '<th scope="col" class="c" title="Sharpe above zero in both halves of the test">Both halves</th></tr></thead>';
    var body = rowHtml(S.data.hold, true) + visibleRows().map(function (r) { return rowHtml(r, false); }).join('');
    t.innerHTML = head + '<tbody>' + body + '</tbody>';
  }

  /* ── Detail and compare ─────────────────────────────────────────────── */

  function yearBars(r, hold) {
    var hy = {};
    hold.years.forEach(function (y) { hy[y.year] = y; });
    var max = 1;
    r.years.forEach(function (y) {
      max = Math.max(max, Math.abs(y.ret_pct), Math.abs((hy[y.year] || {}).ret_pct || 0));
    });
    function bar(v, cls) {
      if (!finite(v)) return '<span class="sl-yb-bar"></span>';
      var w = Math.min(50, Math.abs(v) / max * 50);
      return '<span class="sl-yb-bar"><i class="' + cls + (v < 0 ? ' neg' : '') + '" style="width:' + w.toFixed(1) + '%"></i></span>';
    }
    return '<div class="sl-yb" role="table" aria-label="Calendar-year returns">' +
      '<div class="sl-yb-row sl-yb-h" role="row"><span role="columnheader">Year</span><span role="columnheader">' + esc(r.name) +
      '</span><span role="columnheader">Holding</span></div>' +
      r.years.map(function (y) {
        var hv = (hy[y.year] || {}).ret_pct;
        return '<div class="sl-yb-row' + (y.partial ? ' partial' : '') + '" role="row">' +
          '<span role="cell">' + y.year + (y.partial ? '<small>part</small>' : '') + '</span>' +
          '<span role="cell" class="sl-yb-cell">' + bar(y.ret_pct, 'r') + '<em class="' + tone(y.ret_pct) + '">' + pct(y.ret_pct, 0) + '</em></span>' +
          '<span role="cell" class="sl-yb-cell">' + bar(hv, 'h') + '<em class="' + tone(hv) + '">' + pct(hv, 0) + '</em></span>' +
          '</div>';
      }).join('') + '</div>';
  }

  function kv(k, v, cls) { return '<div><dt>' + esc(k) + '</dt><dd class="' + (cls || '') + '">' + v + '</dd></div>'; }

  function paintDetail() {
    var box = $('sl-detail');
    if (!box || !S.data) return;
    var r = byId(S.selected) || S.data.strategies[0];
    if (!r) { box.innerHTML = ''; return; }
    var m = r.metrics, h = S.data.hold, vs = r.vs_hold || {}, inr = S.data.currency === 'INR';
    var halves = (r.halves || []).map(function (x, i) {
      var hh = (h.halves || [])[i] || {};
      return '<div class="sl-half"><span>' + (i ? 'Second half' : 'First half') + '<small>' + esc(day(x.from)) + ' – ' + esc(day(x.to)) + '</small></span>' +
        '<b class="' + tone(x.sharpe) + '">Sharpe ' + plain(x.sharpe) + '</b>' +
        '<small>' + pct(x.cagr_pct) + ' a year · holding ' + plain(hh.sharpe) + ' / ' + pct(hh.cagr_pct) + '</small></div>';
    }).join('');
    box.innerHTML =
      '<div class="sl-card-h"><h3>' + esc(r.name) + '</h3><span class="sl-fam">' + esc(r.family) + '</span></div>' +
      '<p class="sl-rule"><b>The rule.</b> ' + esc(r.rule) + '</p>' +
      '<p class="sl-idea"><b>The idea.</b> ' + esc(r.idea) + '</p>' +
      '<p class="sl-src">Adapted from quants.md <b>' + esc(r.inspired_by) + '</b>, rewritten long-only for a cash account, ' +
      'with textbook settings that were not tuned to this stock.</p>' +
      '<dl class="sl-kv">' +
        kv('CAGR', pct(m.cagr_pct) + ' <small>' + pts(vs.cagr_pts) + ' vs holding</small>', tone(m.cagr_pct)) +
        (inr ? kv('After tax', pct(m.after_tax_cagr_pct) + ' <small>' + pts(vs.after_tax_cagr_pts) + ' vs holding</small>', tone(m.after_tax_cagr_pct)) : '') +
        kv('Sharpe', plain(m.sharpe) + ' <small>' + (finite(vs.sharpe) ? (vs.sharpe >= 0 ? '+' : '−') + Math.abs(vs.sharpe).toFixed(2) : '—') + ' vs holding</small>', tone(m.sharpe)) +
        kv('Worst fall', pct(m.max_drawdown_pct) + ' <small>' + pts(vs.drawdown_pts) + ' vs holding</small>', 'dn') +
        kv('Volatility', pct(m.volatility_pct).replace('+', '') + ' <small>a year</small>') +
        kv('Calmar', plain(m.calmar) + ' <small>CAGR ÷ worst fall</small>') +
        kv('Closed trades', String(m.trades || 0) + (m.few_trades && m.trades ? ' <small class="few">too few to lean on</small>' : '')) +
        kv('Average win / loss', pct(m.avg_win_pct) + ' / ' + pct(m.avg_loss_pct)) +
        kv('Average hold', finite(m.avg_hold_sessions) ? m.avg_hold_sessions + ' <small>sessions</small>' : '—') +
        kv('Turnover', finite(m.turnover_per_year) ? m.turnover_per_year + '× <small>a year</small>' : '—') +
        kv('Moves with holding', finite(vs.correlation) ? plain(vs.correlation) + ' <small>correlation of daily returns</small>' : '—') +
        kv('Years ahead of holding', vs.years_full ? vs.years_beat + ' of ' + vs.years_full : '—') +
      '</dl>' +
      '<h4 class="sl-sub">Two halves</h4><div class="sl-halves">' + halves + '</div>' +
      '<h4 class="sl-sub">Year by year</h4>' + yearBars(r, h);
  }

  function paintCompare() {
    var box = $('sl-compare');
    if (!box || !S.data) return;
    if (S.compare.length < 1) { box.innerHTML = ''; return; }
    var list = [S.data.hold].concat(S.compare.map(byId).filter(Boolean));
    var inr = S.data.currency === 'INR';
    var rowsDef = [
      ['The rule', function (r) { return '<small>' + esc(r.rule) + '</small>'; }],
      ['Return', function (r) { return pct(r.metrics.total_return_pct, 0); }],
      ['CAGR', function (r) { return pct(r.metrics.cagr_pct); }],
      inr ? ['After tax', function (r) { return pct(r.metrics.after_tax_cagr_pct); }] : null,
      ['Sharpe', function (r) { return plain(r.metrics.sharpe); }],
      ['Worst fall', function (r) { return pct(r.metrics.max_drawdown_pct, 0); }],
      ['Win rate', function (r) { return r.metrics.trades ? pct(r.metrics.win_rate_pct, 0).replace('+', '') : '—'; }],
      ['Profit factor', function (r) { return r.metrics.profit_factor_note ? 'no loss' : plain(r.metrics.profit_factor); }],
      ['In market', function (r) { return Math.round(r.metrics.exposure_pct) + '%'; }],
      ['Both halves beat cash', function (r) { return r.id === 'hold' ? halvesWord(r) : (r.consistent ? 'Yes' : 'No'); }]
    ].filter(Boolean);
    box.innerHTML = '<section class="sl-card sl-cmp"><div class="sl-card-h"><h3>Side by side</h3>' +
      '<button type="button" class="sl-link" data-clear-cmp>Clear</button></div>' +
      '<div class="sl-scroll"><table class="sl-table sl-cmp-t"><thead><tr><th></th>' +
      list.map(function (r, i) {
        return '<th scope="col"><span class="sl-swatch k' + i + '" aria-hidden="true"></span>' + esc(r.name) + '</th>';
      }).join('') + '</tr></thead><tbody>' +
      rowsDef.map(function (rd) {
        return '<tr><th scope="row">' + rd[0] + '</th>' + list.map(function (r) { return '<td>' + rd[1](r) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table></div></section>';
  }

  function halvesWord(h) {
    var hv = h.halves || [];
    return hv.length === 2 && hv.every(function (x) { return finite(x.sharpe) && x.sharpe > 0; }) ? 'Yes' : 'No';
  }

  /* ── Charts ─────────────────────────────────────────────────────────── */

  /* Drawn at the box's real pixel width, not stretched from a fixed
     viewBox: stretching a 1000-unit drawing onto a phone shrinks the axis
     labels to four pixels. Redrawn when the width changes. */
  var W = 1000, H = 300, PL = 46, PR = 14, PT = 12, PB = 26;
  function measure(box) {
    W = Math.max(300, Math.round(box.clientWidth || 1000));
    H = Math.round(Math.min(320, Math.max(210, W * 0.32)));
    PL = W < 520 ? 38 : 46;
  }

  function niceLogTicks(lo, hi) {
    var out = [], steps = [1, 2, 5];
    for (var e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)) + 1; e++) {
      steps.forEach(function (s) {
        var v = s * Math.pow(10, e);
        if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
      });
    }
    var most = H < 260 ? 5 : 7;
    if (out.length > most) out = out.filter(function (v) { return /^(1|5)/.test(String(v)) || v === 1; });
    if (out.indexOf(1) < 0 && lo < 1 && hi > 1) out.push(1);
    return out.sort(function (a, b) { return a - b; });
  }

  function yearTicks(dates, x) {
    var out = [], last = null;
    dates.forEach(function (d, i) {
      var y = d.slice(0, 4);
      if (y !== last) { out.push([i, y]); last = y; }
    });
    var every = Math.ceil(out.length / Math.max(3, Math.floor(W / 110)));
    return out.filter(function (t, k) { return k % every === 0 && t[0] > 0; })
      .map(function (t) { return '<text x="' + x(t[0]).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle">' + t[1] + '</text>' +
        '<line class="g" x1="' + x(t[0]).toFixed(1) + '" x2="' + x(t[0]).toFixed(1) + '" y1="' + PT + '" y2="' + (H - PB) + '"/>'; }).join('');
  }

  function seriesList() {
    var d = S.data, list = [];
    if (S.showAll) {
      rowsAll().forEach(function (r) {
        if (r.id !== S.selected && S.compare.indexOf(r.id) < 0) list.push({ r: r, cls: 'faint' });
      });
    }
    S.compare.forEach(function (id, i) {
      var r = byId(id);
      if (r && id !== S.selected) list.push({ r: r, cls: 'k' + (i + 1) });
    });
    list.push({ r: d.hold, cls: 'hold' });
    var sel = byId(S.selected);
    if (sel) list.push({ r: sel, cls: 'sel' });
    return list;
  }

  function path(vals, x, y) {
    var p = '';
    for (var i = 0; i < vals.length; i++) {
      if (!finite(vals[i]) || vals[i] <= 0) continue;
      p += (p ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(vals[i]).toFixed(1);
    }
    return p;
  }

  function drawdowns(vals) {
    var peak = 1, out = [];
    for (var i = 0; i < vals.length; i++) {
      peak = Math.max(peak, vals[i]);
      out.push(vals[i] / peak - 1);
    }
    return out;
  }

  function paintCharts() {
    var d = S.data, box = $('sl-chart'), under = $('sl-under');
    if (!d || !box) return;
    measure(box);
    var dates = d.curve_dates, n = dates.length;
    var list = seriesList();
    var lo = Infinity, hi = -Infinity;
    list.forEach(function (s) {
      s.r.curve.forEach(function (v) { if (v > 0) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    });
    lo = Math.min(lo, 1); hi = Math.max(hi, 1);
    var L0 = Math.log(lo * 0.95), L1 = Math.log(hi * 1.05);
    function x(i) { return PL + (W - PL - PR) * (n > 1 ? i / (n - 1) : 0); }
    function y(v) { return PT + (H - PT - PB) * (1 - (Math.log(v) - L0) / (L1 - L0)); }
    var ticks = niceLogTicks(lo * 0.95, hi * 1.05).map(function (v) {
      return '<line class="g' + (v === 1 ? ' one' : '') + '" x1="' + PL + '" x2="' + (W - PR) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"/>' +
        '<text x="' + (PL - 6) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end">' + (v >= 10 ? v.toFixed(0) : v < 1 ? v.toFixed(2) : v.toFixed(v % 1 ? 1 : 0)) + '×</text>';
    }).join('');
    var lines = list.map(function (s) {
      return '<path class="ln ' + s.cls + '" d="' + path(s.r.curve, x, y) + '"><title>' + esc(s.r.name) + '</title></path>';
    }).join('');
    box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="Growth of one unit for holding and the rules, log scale">' +
      '<g class="ax">' + ticks + yearTicks(dates, x) + '</g>' + lines +
      '<line class="cross" id="sl-cross" x1="0" x2="0" y1="' + PT + '" y2="' + (H - PB) + '" visibility="hidden"/>' +
      '<rect class="hit" x="' + PL + '" y="' + PT + '" width="' + (W - PL - PR) + '" height="' + (H - PT - PB) + '"/></svg>' +
      '<div class="sl-tip" id="sl-tip" hidden></div>';

    var sel = byId(S.selected);
    var legend = [['hold', d.hold.name], ['sel', sel ? sel.name : '']];
    S.compare.forEach(function (id, i) { var r = byId(id); if (r && id !== S.selected) legend.push(['k' + (i + 1), r.name]); });
    if (S.showAll) legend.push(['faint', 'Other rules']);
    $('sl-legend').innerHTML = legend.map(function (l) {
      return '<span><i class="sw ' + l[0] + '" aria-hidden="true"></i>' + esc(l[1]) + '</span>';
    }).join('');

    // Underwater chart: holding against the selected rule.
    if (under) {
      var hd = drawdowns(d.hold.curve), sd = sel ? drawdowns(sel.curve) : [];
      var mn = Math.min.apply(null, hd.concat(sd).concat([-0.05]));
      var UH = Math.round(Math.min(150, Math.max(100, W * 0.14)));
      function uy(v) { return PT + (UH - PT - 18) * (v / mn); }
      function area(vals) {
        var p = 'M' + x(0).toFixed(1) + ',' + uy(0).toFixed(1);
        vals.forEach(function (v, i) { p += 'L' + x(i).toFixed(1) + ',' + uy(v).toFixed(1); });
        return p + 'L' + x(vals.length - 1).toFixed(1) + ',' + uy(0).toFixed(1) + 'Z';
      }
      var ut = [0, mn / 2, mn].map(function (v) {
        return '<line class="g" x1="' + PL + '" x2="' + (W - PR) + '" y1="' + uy(v).toFixed(1) + '" y2="' + uy(v).toFixed(1) + '"/>' +
          '<text x="' + (PL - 6) + '" y="' + (uy(v) + 4).toFixed(1) + '" text-anchor="end">' + Math.round(v * 100) + '%</text>';
      }).join('');
      under.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + UH + '" width="' + W + '" height="' + UH + '" role="img" aria-label="How far below its previous high each line was">' +
        '<g class="ax">' + ut + '</g>' +
        '<path class="uw hold" d="' + area(hd) + '"/>' +
        (sel ? '<path class="uw sel" d="' + area(sd) + '"/>' : '') + '</svg>';
    }

    // Hover: the date and the value of every highlighted line.
    var svg = box.querySelector('svg'), tip = $('sl-tip'), cross = $('sl-cross');
    var named = list.filter(function (s) { return s.cls !== 'faint'; }).reverse();
    function move(ev) {
      var rect = svg.getBoundingClientRect();
      var px = (ev.clientX - rect.left) / rect.width * W;
      var i = Math.round((px - PL) / (W - PL - PR) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
      cross.setAttribute('visibility', 'visible');
      tip.hidden = false;
      tip.innerHTML = '<b>' + esc(day(dates[i])) + '</b>' + named.map(function (s) {
        var v = s.r.curve[i];
        return '<span><i class="sw ' + s.cls + '"></i>' + esc(s.r.name) + '<em>' + (finite(v) ? v.toFixed(2) + '×' : '—') + '</em></span>';
      }).join('');
      var left = (x(i) / W) * rect.width;
      tip.style.left = Math.min(Math.max(8, left + 12), rect.width - tip.offsetWidth - 8) + 'px';
    }
    function leave() { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); }
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', leave);
  }

  /* ── Luck, sizing, glossary, assumptions ────────────────────────────── */

  function luckCard(d) {
    var L = d.luck || {};
    return '<section class="sl-card sl-prose"><h3>Why the top row is probably worse than it looks</h3>' +
      '<p>Run enough rules on one stock and one of them will shine by chance. The question is not “which rule won?” but ' +
      '“did the winner win by more than luck hands out?”</p>' +
      '<p>Of the ' + L.rules_tried + ' rules, many are near-copies of each other: most trend rules are in the market on the same days. ' +
      'Measured by how differently they actually moved, this test is about <b>' + esc(L.effective_rules) + '</b> separate tries, ' +
      'not ' + L.rules_tried + '. Over ' + esc(L.years) + ' years, the best of that many rules with no edge at all would be expected to ' +
      'beat its true Sharpe by about <b>' + plain(L.luck_bar_sharpe) + '</b>. That is the luck bar. A lead over holding smaller ' +
      'than it is what chance alone produces.</p>' +
      '<p class="sl-fine">The expected maximum of several Sharpe ratios, after Bailey and López de Prado, “The Deflated Sharpe Ratio” (2014); ' +
      'separate tries counted from the spread of the rules’ return correlations. An approximation, offered as one.</p></section>';
  }

  function sizingCard(d) {
    var sel = byId(S.selected) || {}, m = sel.metrics || {}, hv = d.hold.metrics.volatility_pct;
    var cur = d.currency === 'INR' ? '₹' : '$';
    return '<section class="sl-card sl-size"><h3>Size a position</h3>' +
      '<p class="sl-fine">Arithmetic on the numbers you type. Prefilled from this report where it can be; nothing here tells you what to trade.</p>' +
      '<div class="sl-calcs">' +
        '<form class="sl-calc" data-calc="risk"><h4>Risk per trade</h4>' +
          '<label>Capital (' + cur + ')<input type="number" min="0" step="1000" name="cap" value="500000"></label>' +
          '<label>Risk per trade (%)<input type="number" min="0" max="100" step="0.1" name="risk" value="1"></label>' +
          '<label>Entry price<input type="number" min="0" step="0.05" name="entry" placeholder="e.g. 1250"></label>' +
          '<label>Exit price if wrong<input type="number" min="0" step="0.05" name="exit" placeholder="e.g. 1180"></label>' +
          '<output class="sl-out" name="out"></output>' +
          '<p class="sl-fine">Quantity = capital × risk % ÷ (entry − exit if wrong). A gap through your exit price loses more than this.</p></form>' +
        '<form class="sl-calc" data-calc="vol"><h4>Volatility target</h4>' +
          '<label>Capital (' + cur + ')<input type="number" min="0" step="1000" name="cap" value="500000"></label>' +
          '<label>Target volatility (% a year)<input type="number" min="1" max="100" step="1" name="target" value="15"></label>' +
          '<label>This stock’s volatility (% a year)<input type="number" min="1" max="300" step="0.1" name="vol" value="' + (finite(hv) ? hv : '') + '"></label>' +
          '<output class="sl-out" name="out"></output>' +
          '<p class="sl-fine">Position = capital × min(1, target ÷ stock volatility). The stock’s figure is its realised volatility over this test.</p></form>' +
        '<form class="sl-calc" data-calc="kelly"><h4>Kelly fraction</h4>' +
          '<label>Win rate (%)<input type="number" min="0" max="100" step="0.1" name="p" value="' + (finite(m.win_rate_pct) ? m.win_rate_pct : '') + '"></label>' +
          '<label>Average win (%)<input type="number" min="0" step="0.01" name="win" value="' + (finite(m.avg_win_pct) ? m.avg_win_pct : '') + '"></label>' +
          '<label>Average loss (%)<input type="number" step="0.01" name="loss" value="' + (finite(m.avg_loss_pct) ? Math.abs(m.avg_loss_pct) : '') + '"></label>' +
          '<output class="sl-out" name="out"></output>' +
          '<p class="sl-fine">f* = p − (1 − p) ÷ b, where b = average win ÷ average loss. ' +
          (sel.name ? 'Prefilled from ' + esc(sel.name) + (m.few_trades ? ', which has too few trades for these to mean much' : '') + '. ' : '') +
          'Kelly assumes the odds are known; from a backtest they are only estimated, so most practitioners use half or less.</p></form>' +
      '</div></section>';
  }

  function calc(form) {
    var f = function (n) { var el = form.elements[n]; return el && el.value !== '' ? Number(el.value) : NaN; };
    var out = form.querySelector('output'), kind = form.dataset.calc, cur = S.data && S.data.currency;
    var msg = '';
    if (kind === 'risk') {
      var cap = f('cap'), risk = f('risk'), entry = f('entry'), exit = f('exit');
      if ([cap, risk, entry, exit].every(isFinite) && entry > 0) {
        if (exit >= entry) msg = 'The exit-if-wrong price has to be below the entry price.';
        else {
          var atRisk = cap * risk / 100, per = entry - exit, qty = Math.floor(atRisk / per);
          var value = qty * entry;
          msg = '<b>' + qty.toLocaleString('en-IN') + ' shares</b> · ' + money(value, cur) + ' (' + (cap ? (value / cap * 100).toFixed(1) : '—') +
            '% of capital) · ' + money(qty * per, cur) + ' lost if the exit is hit' +
            (value > cap ? '<br><small class="few">That is more than the capital: the exit is too close for this risk.</small>' : '');
        }
      } else msg = 'Fill in all four.';
    } else if (kind === 'vol') {
      var c = f('cap'), tg = f('target'), v = f('vol');
      if ([c, tg, v].every(isFinite) && v > 0) {
        var share = Math.min(1, tg / v);
        msg = '<b>' + money(c * share, cur) + '</b> in the stock (' + (share * 100).toFixed(0) + '% of capital); ' +
          money(c * (1 - share), cur) + ' stays in cash.';
      } else msg = 'Fill in all three.';
    } else if (kind === 'kelly') {
      var p = f('p') / 100, w = f('win'), l = Math.abs(f('loss'));
      if ([p, w, l].every(isFinite) && l > 0 && w > 0) {
        var b = w / l, k = p - (1 - p) / b;
        msg = k <= 0
          ? '<b>Kelly says 0%.</b> On these numbers the edge is negative: the average loss outweighs the wins.'
          : '<b>Full Kelly ' + (k * 100).toFixed(0) + '%</b> of capital per trade · half Kelly ' + (k * 50).toFixed(0) +
            '% · payoff ratio ' + b.toFixed(2) + (k > 0.5 ? '<br><small class="few">Above 50% is a sign the estimates are too good to trust.</small>' : '');
      } else msg = 'Fill in all three.';
    }
    out.innerHTML = msg;
  }

  function glossary(d) {
    var rf = d.assumptions.risk_free_pct;
    var items = [
      ['Return', 'How much the account grew over the whole test.', '(final ÷ start) − 1'],
      ['CAGR', 'The steady yearly return that would have turned the start into the finish.', '(final ÷ start)^(1 ÷ years) − 1'],
      ['Sharpe', 'Return above cash per unit of bumpiness, scaled to a year. Above ' + rf + '% a year for this stock. Around 0.5 is respectable for a simple rule; above 1 over a decade is rare.',
       'mean(daily return − daily risk-free) ÷ sd(daily return) × √252'],
      ['Worst fall', 'The largest drop from a high to a later low. The number that decides whether a person sticks with a rule.', 'min over days of (value ÷ highest value so far) − 1'],
      ['Win rate', 'The share of closed trades that made money. A high win rate with small wins and big losses still loses.', 'winning trades ÷ closed trades'],
      ['Profit factor', 'Money made on winners for every unit lost on losers. 1.0 is breaking even.', 'gross profit ÷ gross loss, in money'],
      ['After tax', 'CAGR after Indian capital gains tax: 20% on gains held a year or less, 12.5% on longer ones, paid each March, everything closed on the last day.', 'see the assumptions below'],
      ['In market', 'The share of days the rule held the stock at all. Time out of the market is time cash earns nothing here.', 'days with a position ÷ days'],
      ['Years ahead', 'Full calendar years in which the rule did better than holding. A ten-year number can rest on one year.', 'years rule > holding ÷ full years'],
      ['Both halves', 'Whether the rule beat cash (Sharpe above zero) in the first half of the test and again in the second.', 'Sharpe(first half) > 0 and Sharpe(second half) > 0']
    ].filter(function (it) { return d.currency === 'INR' || it[0] !== 'After tax'; });
    return '<section class="sl-card sl-gloss"><h3>Reading the numbers</h3><dl>' + items.map(function (it) {
      return '<div><dt>' + esc(it[0]) + '</dt><dd>' + esc(it[1]) + '<code>' + esc(it[2]) + '</code></dd></div>';
    }).join('') + '</dl></section>';
  }

  function assumptions(d) {
    var a = d.assumptions;
    var lines = [
      'Prices: daily, adjusted for splits and dividends, ' + esc(day(d.start)) + ' to ' + esc(day(d.end)) + '.',
      esc(a.execution) + ' ' + esc(a.start),
      'Costs: ' + a.cost_round_trip_pct + '% a round trip, charged on every change in position.',
      'Long only: an Indian cash account cannot hold a short overnight, so no rule here shorts. ' + esc(a.cash),
      'Sharpe is measured above ' + a.risk_free_pct + '% a year' + (d.currency === 'INR' ? ', about the 91-day Treasury bill over the last decade' : '') + '.',
      'Volatility-sized rules aim at ' + a.vol_target_pct + '% a year, never use more than the whole account, and only resize when the weight is ' + a.drift_band_pct + ' points off.'
    ];
    if (a.tax) lines.push('Tax: ' + esc(a.tax.note));
    lines.push('Every parameter is the textbook one and was not tuned to this stock. Tuning on the same prices a rule is measured on is how a backtest becomes fiction.');
    return '<section class="sl-card sl-prose sl-assume"><h3>How this was tested</h3><ul>' +
      lines.map(function (l) { return '<li>' + l + '</li>'; }).join('') + '</ul>' +
      '<p class="sl-disc">' + esc(d.disclaimer) + '</p>' +
      '<p class="sl-fine">' + esc(d.attribution) + ' <a href="' + esc(d.source && d.source.url || 'https://quants.md/') +
      '" target="_blank" rel="noopener">quants.md</a></p></section>';
  }

  /* ── Events ─────────────────────────────────────────────────────────── */

  function select(id) {
    if (!id || !byId(id) || id === 'hold') return;
    S.selected = id;
    paintTable();
    paintDetail();
    paintCharts();
    // Only the Kelly inputs come from the selected rule. The other two hold
    // what the reader typed, so they are left alone.
    var kelly = document.querySelector('#view-strategies [data-calc="kelly"]');
    if (kelly && S.data) {
      var tmp = document.createElement('div');
      tmp.innerHTML = sizingCard(S.data);
      var fresh = tmp.querySelector('[data-calc="kelly"]');
      if (fresh) { kelly.replaceWith(fresh); calc(fresh); }
    }
  }

  function refreshCalcs() {
    Array.prototype.forEach.call(document.querySelectorAll('#view-strategies .sl-calc'), calc);
  }

  function onClick(e) {
    var t = e.target;
    if (t.closest('[data-retry]')) { run(S.sym); return; }
    if (t.closest('[data-clear-cmp]')) { S.compare = []; paintTable(); paintCompare(); paintCharts(); return; }
    var fam = t.closest('[data-family]');
    if (fam) {
      S.family = fam.dataset.family;
      Array.prototype.forEach.call(document.querySelectorAll('#view-strategies [data-family]'), function (b) {
        b.classList.toggle('on', b.dataset.family === S.family);
      });
      paintTable();
      return;
    }
    if (t.closest('[data-cmp]')) return;          // handled on change
    var row = t.closest('tr[data-row]');
    if (row && row.dataset.row !== 'hold') select(row.dataset.row);
  }

  function onChange(e) {
    var t = e.target;
    if (t.id === 'sl-sort') { S.sort = t.value; paintTable(); return; }
    if (t.id === 'sl-showall') { S.showAll = t.checked; paintCharts(); return; }
    if (t.dataset && t.dataset.cmp) {
      var id = t.dataset.cmp, at = S.compare.indexOf(id);
      if (t.checked && at < 0) {
        if (S.compare.length >= 3) { t.checked = false; return; }
        S.compare.push(id);
      } else if (!t.checked && at >= 0) {
        S.compare.splice(at, 1);
      }
      paintCompare();
      paintCharts();
    }
  }

  function onInput(e) {
    var form = e.target.closest && e.target.closest('.sl-calc');
    if (form) calc(form);
  }

  var resizeTimer = null, lastWidth = 0;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var box = $('sl-chart');
      if (!box || !S.data || !box.clientWidth || Math.abs(box.clientWidth - lastWidth) < 8) return;
      lastWidth = box.clientWidth;
      paintCharts();
    }, 150);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var row = e.target.closest && e.target.closest('#view-strategies tr[data-row]');
    if (!row || e.target.tagName === 'INPUT') return;
    e.preventDefault();
    select(row.dataset.row);
  });

  /* ── Public ─────────────────────────────────────────────────────────── */

  function open(sym) {
    if (!build()) return;
    // ?lab=SYMBOL (the stock page's link) is honoured on the first open only;
    // coming back to the tab later shows whatever was last run.
    var want = sym || (!S.linked && param('lab')) || '';
    S.linked = true;
    if (want) { run(want); return; }
    if (S.data || S.loading || S.error) return;
    run(store('altaha.lab.sym') || 'RELIANCE');
  }

  // A ?go=strategies or #research/strategies address can switch to the tab
  // before this deferred file has run, and then nobody called open(). Check
  // once the page has settled, the way calls.js does.
  function openIfShowing() {
    var v = $('view-strategies');
    if (v && v.style.display === 'block' && !S.built) open();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(openIfShowing, 0); });
  else setTimeout(openIfShowing, 0);

  window.AltahaStrategyLab = { open: open, run: function (s) { if (build()) run(s); } };
})();
