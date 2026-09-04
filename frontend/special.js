/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Special — renders the delivery-weighted momentum book.

   Loads on demand, not at boot: it walks a few hundred NSE bhavcopies on the
   server the first time and a visitor who never opens this tab should never
   pay for that.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
          : (window.API_BASE || 'https://taha-project.onrender.com');
  var loaded = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  var f = function (v, d) { return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d == null ? 1 : d); };

  function measured(m) {
    if (!m) return '';
    return '<div class="sp-stat"><div class="k">Measured CAGR</div><div class="v">' +
        f(m.cagr_pct, 2) + '%</div><div class="h">vs NIFTY ' + f(m.nifty_cagr_pct, 2) + '%</div></div>' +
      '<div class="sp-stat"><div class="k">Sharpe</div><div class="v">' + f(m.sharpe, 2) +
        '</div><div class="h">vs NIFTY ' + f(m.nifty_sharpe, 2) + '</div></div>' +
      '<div class="sp-stat"><div class="k">Worst drawdown</div><div class="v">' +
        f(m.max_drawdown_pct, 1) + '%</div><div class="h">peak to trough</div></div>' +
      (m.decay_warning ? '<div class="sp-caveat sp-warn"><b>Every one of these signals has weakened.</b> ' +
        esc(m.decay_warning) + '</div>' : '') +
      (m.vs_single_best ? '<div class="sp-caveat"><b>Why five and not the best one.</b> ' +
        esc(m.vs_single_best) + '</div>' : '') +
      '<div class="sp-caveat"><b>Read this before the list.</b> ' + esc(m.honest_note) +
        ' Tested over ' + esc(m.window) + '.</div>';
  }

  function legend(sigs) {
    if (!sigs || !sigs.length) return '';
    return '<div class="sp-legend">' + sigs.map(function (s) {
      return '<div class="sp-leg"><b>' + esc(s.label) + '</b><span>' + esc(s.note) + '</span></div>';
    }).join('') + '</div>';
  }

  function bars(parts) {
    return '<div class="sp-parts">' + parts.map(function (c) {
      var v = c.percentile;
      var cls = v == null ? 'na' : (v >= 70 ? 'hi' : (v <= 30 ? 'lo' : 'mid'));
      return '<div class="sp-part"><span class="pl">' + esc(c.label) + '</span>' +
        '<span class="pb"><i class="' + cls + '" style="width:' +
        (v == null ? 0 : Math.max(2, v)).toFixed(0) + '%"></i></span>' +
        '<span class="pv">' + (v == null ? '—' : Math.round(v)) + '</span></div>';
    }).join('') + '</div>';
  }

  function row(r, i) {
    var sc = Math.max(0, Math.min(100, r.composite));
    return '<details class="sp-row"><summary>' +
      '<span class="sp-rank">' + (i + 1) + '</span>' +
      '<span><span class="sp-sym"><a href="stock.html?ticker=' +
        encodeURIComponent(r.symbol) + '">' + esc(r.symbol) + '</a></span>' +
        '<span class="sp-sub">₹' + f(r.turnover_cr, 0) + 'cr a day · ' +
        f(r.above_200dma_pct, 0) + '% over its 200-day · ₹' + f(r.price, 2) + '</span></span>' +
      '<span class="sp-bar"><i style="width:' + sc.toFixed(0) + '%"></i></span>' +
      '<span class="sp-deliv"><span class="n">' + f(r.composite, 0) +
        '</span><span class="l">of 100</span></span>' +
      '</summary><div class="sp-body-open">' +
      bars(r.components || []) +
      '<div class="sp-kv"><span class="k">Reading</span><span class="v">' + esc(r.why) + '</span></div>' +
      '</div></details>';
  }

  function load(force) {
    if (loaded && !force) return;
    loaded = true;
    var host = $('sprows');
    if (!host) return;
    host.innerHTML = '<div class="sp-state"><b>Reading the delivery record…</b>' +
      'The first build walks a year of exchange bhavcopies and can take a minute.</div>';
    fetch(API + '/special?limit=20')
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (o) {
        var d = o.j;
        if (!o.ok || !d || d.available === false) {
          var msg = (d && (d.message || d.detail)) ||
            'The delivery history is not deep enough to rank anything yet.';
          host.innerHTML = '<div class="sp-state"><b>Not ready</b>' + esc(msg) + '</div>';
          if (d && d.measured) $('spmeasured').innerHTML = measured(d.measured);
          return;
        }
        $('spmeasured').innerHTML = measured(d.measured) + legend(d.signals);
        $('spasof').textContent = 'as of ' + esc(d.as_of) + ' · ranked ' +
          d.universe_ranked + ' names';
        host.innerHTML = (d.book || []).map(row).join('') ||
          '<div class="sp-state">No name clears every filter today.</div>';
        $('spdisc').textContent = (d.method || '') + '  ' + (d.disclaimer || '');
      })
      .catch(function () {
        loaded = false;
        host.innerHTML = '<div class="sp-state"><b>The engine is unreachable</b>' +
          'If it has been idle it takes about thirty seconds to wake — try again.</div>';
      });
  }

  function wire() {
    var btn = $('spload');
    if (btn) btn.addEventListener('click', function () { load(true); });
    // Load the first time the tab is actually shown.
    var view = $('view-special');
    if (!view || !('MutationObserver' in window)) return;
    new MutationObserver(function () {
      if (view.style.display !== 'none') load(false);
    }).observe(view, { attributes: true, attributeFilter: ['style'] });
    if (view.style.display !== 'none') load(false);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();
})();
