/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — wow.js

   WOW orders: order wins measured against the company that won them.

   THE ONE JUDGEMENT THIS VIEW MAKES
   An order is "WOW" when its DISCLOSED value is at least a set share of market
   capitalisation. The threshold comes from the API and is printed on the page,
   because a rule the reader cannot see is a rule they cannot argue with.

   WHAT IT WILL NOT DO
   An order whose value the company did not disclose is shown — it happened,
   and hiding it would misrepresent the day — but it is never ranked, never
   given an estimated number, and never described as small. "Not disclosed" and
   "small" are different facts and this page keeps them apart.

   No target, no entry, no instruction. An order is an event with a size.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var loaded = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function cr(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    if (n >= 100000) return '₹' + (n / 100000).toFixed(2) + ' lakh cr';
    if (n >= 1) return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' cr';
    return '₹' + (n * 100).toFixed(2) + ' lakh';
  }
  function when(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) +
        ', ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return String(iso).slice(0, 16); }
  }

  function quarterBlock(q) {
    if (!q) return '';
    var now = q.this_quarter, prev = q.previous_quarter;
    var delta = '';
    if (q.change_pct != null) {
      delta = '<span class="wq-delta ' + (q.change_pct >= 0 ? 'up' : 'dn') + '">' +
        (q.change_pct >= 0 ? '+' : '') + q.change_pct + '%</span>';
    } else {
      delta = '<span class="wq-delta flat">not comparable yet</span>';
    }
    function side(b) {
      return '<div class="wq-side' + (b.partial ? ' partial' : '') + '">' +
        '<div class="lb">' + esc(b.label) + '</div>' +
        '<div class="vv tnum">' + cr(b.total_cr) + '</div>' +
        '<div class="sub">' + b.with_value + ' of ' + b.orders +
          ' orders disclosed a value · ' + b.companies + ' companies</div>' +
        (b.biggest ? '<div class="sub big">Biggest: ' + esc(b.biggest.company || b.biggest.symbol || '') +
          ' ' + cr(b.biggest.value_cr) + '</div>' : '') +
        (b.partial ? '<div class="sub warn">Recording started part-way through this quarter</div>' : '') +
        '</div>';
    }
    return '<section class="wq">' +
      '<h3>Disclosed order inflow, quarter on quarter</h3>' +
      '<div class="wq-grid">' + side(prev) +
        '<div class="wq-arrow">' + delta + '</div>' + side(now) + '</div>' +
      '<p class="wq-note">' + esc(q.caveat) + '</p>' +
      '</section>';
  }

  function row(r, threshold) {
    var pct = r.pct_of_market_cap;
    var head;
    if (pct != null) {
      head = '<span class="wo-pct tnum' + (r.wow ? ' wow' : '') + '">' +
        pct.toFixed(1) + '%</span><span class="wo-of">of market cap</span>';
    } else if (r.value_cr != null) {
      head = '<span class="wo-pct tnum none">' + cr(r.value_cr) +
        '</span><span class="wo-of">market cap unavailable</span>';
    } else {
      head = '<span class="wo-pct tnum none">—</span>' +
        '<span class="wo-of">value not disclosed</span>';
    }

    var flags = '';
    if (r.wow) flags += '<em class="fl wow">WOW</em>';
    if (r.value_cr != null && !r.value_confident) {
      flags += '<em class="fl soft" title="The filing states this figure but does not label it as the order value">unlabelled figure</em>';
    }
    if (r.currency_converted) {
      flags += '<em class="fl soft" title="Converted from a foreign currency at an assumed rate">converted</em>';
    }

    return '<article class="wo' + (r.wow ? ' is-wow' : '') + '">' +
      '<div class="wo-head">' + head + flags + '</div>' +
      '<div class="wo-body">' +
        '<div class="wo-co">' +
          (r.symbol
            ? '<a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.company || r.symbol) + '</a>'
            : esc(r.company || 'Unnamed company')) +
          '<span class="wo-when">' + esc(when(r.at)) + '</span>' +
        '</div>' +
        '<p class="wo-hl">' + esc(r.headline) + '</p>' +
        '<div class="wo-nums">' +
          '<span><b>Order</b> ' + (r.value_cr == null ? 'not disclosed' : cr(r.value_cr)) + '</span>' +
          '<span><b>Market cap</b> ' + (r.market_cap_cr == null ? '—' : cr(r.market_cap_cr)) + '</span>' +
        '</div>' +
        (r.excerpt
          ? '<details class="wo-ev"><summary>Where this figure came from</summary>' +
            '<blockquote>' + esc(r.excerpt) + '</blockquote>' +
            '<p class="basis">' + esc(r.value_basis || '') + '</p></details>'
          : '') +
        (r.pdf ? '<a class="wo-pdf" href="' + esc(r.pdf) + '" target="_blank" rel="noopener">Open the filing →</a>' : '') +
      '</div>' +
      '</article>';
  }

  function paint(d) {
    var box = $('wow-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="wo-empty">' +
        esc((d && d.message) || 'The orders feed could not be read.') + '</div>';
      return;
    }
    var c = d.counts || {};
    var rows = d.rows || [];

    var bar = '<div class="wo-counts">' +
      '<span><b class="tnum">' + (c.wow || 0) + '</b> WOW</span>' +
      '<span><b class="tnum">' + (c.with_value || 0) + '</b> with a disclosed value</span>' +
      '<span><b class="tnum">' + (c.value_not_disclosed || 0) + '</b> value not disclosed</span>' +
      '<span class="thr">threshold ' + esc(String(d.threshold_pct)) + '% of market cap</span>' +
      '</div>';

    var body = rows.length
      ? rows.map(function (r) { return row(r, d.threshold_pct); }).join('')
      : '<div class="wo-empty">No order announcements in this window. ' +
        'Order flow is lumpy — a quiet week is normal, not a fault.</div>';

    box.innerHTML = bar + quarterBlock(d.quarter) +
      '<div class="wo-list">' + body + '</div>' +
      (d.note ? '<p class="wo-note">' + esc(d.note) + '</p>' : '') +
      '<p class="wo-src">' + esc(d.source) + '</p>' +
      '<p class="wo-src">' + esc(d.explain) + '</p>';
  }

  function load() {
    var box = $('wow-body');
    if (box) box.innerHTML = '<div class="wo-empty">Reading the filings…</div>';
    fetch(API + '/wow-orders?days=7')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paint)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="wo-empty">The engine is unreachable. ' +
            'If it has been idle it takes about thirty seconds to wake — try again.</div>';
        }
      });
  }

  /* Loaded when the tab is first opened, never on page load: this reads PDFs. */
  function watch() {
    var view = $('view-wow');
    if (!view) return;
    var seen = new MutationObserver(function () {
      if (view.style.display !== 'none' && !loaded) { loaded = true; load(); }
    });
    seen.observe(view, { attributes: true, attributeFilter: ['style'] });
    if (view.style.display !== 'none' && !loaded) { loaded = true; load(); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }
})();
