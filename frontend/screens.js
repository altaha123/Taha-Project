/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — screens.js

   Quarterly screens: three questions asked of every NSE company at once,
   from the statements the fundamentals crawl has stored — fast growers with
   expanding margins, operational turnarounds, and cash-rich free-cash-flow
   compounders (backend/fundamentals_screens.py). Shown under the lens cards
   on #research/lenses, and only there.

   The lenses apply investing philosophies to full financial years; these
   answer what the latest filings show. Same rules for the wording: a
   company "meets the condition on the figures shown", every match prints
   the figures that met it, and nothing is called good or bad.

   Each screen is a <details> carrying what it looks for, its exact rule and
   the order it lists in; its matches are fetched the first time it is
   opened, not before.

   A figure comes with a unit: "pct" a percentage (24.3%), "pts" a change in
   percentage points (+3.4 pts), "x" a multiple (1.25×), "cr" rupees crore
   (₹6,400 cr). A figure the filings do not give is printed as a dash, never
   as 0.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';
  var index = null, pending = null, detail = {};

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function getJSON(path) {
    return fetch(API + path, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function onIndexRoute() {
    var p = (location.hash || '').replace(/^#/, '').split('/');
    return p[1] === 'lenses' && !p[2];
  }

  // Decimal places by unit: whole rupees crore; two for a multiple, where
  // 0.25× and 0.3× are different answers to a debt test; one otherwise.
  var DIGITS = { cr: 0, x: 2, pct: 1, pts: 1 };

  function fig(f) {
    if (f.value == null) return '—';
    var n = Number(f.value);
    if (!isFinite(n)) return '—';
    var d = DIGITS[f.unit] == null ? 1 : DIGITS[f.unit];
    var s = Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: d });
    // A figure that rounds to nothing carries no sign: "0 pts", not "-0 pts".
    var zero = Number(Math.abs(n).toFixed(d)) === 0;
    var sign = (!zero && n < 0) ? '-' : '';
    if (f.unit === 'pct') return sign + s + '%';
    // A change says which way it went, up as well as down.
    if (f.unit === 'pts') return (zero ? '' : (n < 0 ? '-' : '+')) + s + ' pts';
    if (f.unit === 'x') return sign + s + '×';
    // The sign goes before the rupee: "-₹6,400 cr", not "₹-6,400 cr".
    if (f.unit === 'cr') return sign + '₹' + s + ' cr';
    return sign + s;
  }

  function matchesTable(d) {
    if (!d.matches.length) {
      return '<p class="ln-small">No company meets this condition on the figures held.</p>';
    }
    var rows = d.matches.map(function (m) {
      return '<tr><th scope="row"><a href="stock.html?ticker=' + encodeURIComponent(m.symbol) +
        '">' + esc(m.symbol) + '</a><span class="sc-co">' + esc(m.company || '') + '</span></th>' +
        '<td class="sc-asof">' + esc(m.as_of || '') + '</td>' +
        '<td class="sc-figs">' + m.figures.map(function (f) {
          return '<span><i>' + esc(f.label) + '</i> ' + esc(fig(f)) + '</span>';
        }).join('') + '</td></tr>';
    }).join('');
    return '<div class="ln-tablewrap"><table class="ln-table sc-table">' +
      '<caption class="sc-vh">' + esc(d.screen.name) + '</caption>' +
      '<thead><tr><th scope="col">Company</th><th scope="col">As of</th>' +
      '<th scope="col">The figures</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (d.count > d.matches.length
        ? '<p class="ln-small">Showing ' + d.matches.length + ' of ' + d.count + '.</p>' : '');
  }

  function openScreen(el) {
    var id = el.getAttribute('data-screen'), box = el.querySelector('.sc-body');
    if (!box || box.getAttribute('data-loaded')) return;
    box.setAttribute('data-loaded', '1');
    if (detail[id]) { box.innerHTML = matchesTable(detail[id]); return; }
    box.innerHTML = '<p class="ln-small">Loading…</p>';
    getJSON('/fundamentals/screens/' + encodeURIComponent(id)).then(function (d) {
      detail[id] = d;
      box.innerHTML = matchesTable(d);
    }).catch(function () {
      box.removeAttribute('data-loaded');
      box.innerHTML = '<p class="ln-small">The matches could not be loaded. Close and ' +
        'open this again to retry.</p>';
    });
  }

  function render(host, d) {
    if (!d || !d.available) { host.innerHTML = ''; return; }
    host.innerHTML = '<section class="sc-wrap" aria-labelledby="sc-h">' +
      '<h3 id="sc-h" class="sc-h">Quarterly screens</h3>' +
      '<p class="ln-small">Three questions asked of all ' +
      esc(Number(d.companies_held || 0).toLocaleString('en-IN')) + ' companies whose ' +
      'statements are held, from their latest filings. A company without the figures a ' +
      'screen needs is left out, not failed.</p>' +
      d.screens.map(function (s) {
        var n = Number(s.count) || 0;
        return '<details class="sc-item" data-screen="' + esc(s.id) + '">' +
          '<summary>' + esc(s.name) + ' <span>' + esc(n.toLocaleString('en-IN')) + ' ' +
          (n === 1 ? 'company' : 'companies') + '</span></summary>' +
          (s.description ? '<p class="ln-small sc-desc">' + esc(s.description) + '</p>' : '') +
          '<p class="ln-small sc-rule">' + esc(s.rule) + '</p>' +
          (s.order ? '<p class="ln-small sc-order">' + esc(s.order) + '</p>' : '') +
          '<div class="sc-body"></div></details>';
      }).join('') +
      '<p class="ln-notice" role="note">' + esc(d.notice || '') + '</p></section>';
    Array.prototype.forEach.call(host.querySelectorAll('.sc-item'), function (el) {
      el.addEventListener('toggle', function () { if (el.open) openScreen(el); });
    });
  }

  function show() {
    var host = $('screens-body');
    if (!host) return;
    // Emptied, not just hidden, off the index: a lens page is judged by the
    // tables on it, and an opened screen left behind would be one of them.
    if (!onIndexRoute()) { host.hidden = true; host.innerHTML = ''; return; }
    host.hidden = false;
    if (index) { if (!host.firstChild) render(host, index); return; }
    // Opening the tab fires the navigate event, the click and a hashchange
    // together; they share one request rather than making three.
    if (pending) return;
    pending = getJSON('/fundamentals/screens').then(function (d) {
      index = d;
      if (onIndexRoute()) render(host, d);
    }).catch(function () { host.innerHTML = ''; })
      .then(function () { pending = null; });
  }

  window.addEventListener('altaha:navigate', function (ev) {
    if (ev && ev.detail && ev.detail.tab === 'lenses') setTimeout(show, 0);
  });
  window.addEventListener('hashchange', function () { setTimeout(show, 0); });
  window.addEventListener('popstate', function () { setTimeout(show, 0); });

  function boot() {
    var tl = $('tab-lenses');
    if (tl) tl.addEventListener('click', function () { setTimeout(show, 0); });
    var v = $('view-lenses');
    if (v && v.style.display !== 'none') show();
    // lenses.js moves between the index and a lens with history.pushState,
    // which fires no event; it redraws #lenses-body each time, so that is
    // what is watched.
    var lb = $('lenses-body');
    if (lb && window.MutationObserver) {
      new MutationObserver(function () { show(); }).observe(lb, { childList: true });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
