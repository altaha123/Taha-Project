/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — home.js
   Two jobs on the homepage, and nothing else.

   1  SEARCH LEAVES THE PAGE
      Analysing a company used to expand a panel inside this document, so a
      company had no address: nothing to link, nothing to share, and Back did
      not work. Search now goes to stock.html?ticker=SYM.

      It is intercepted in the CAPTURE phase rather than by rebinding the
      existing handler. The original analyse() and everything hanging off it
      stay exactly as they are — if this file is deleted the old in-page flow
      returns, working, which is the property that makes a change like this
      safe to ship on a Friday.

   2  THE FIRST SCREEN HAS THE MARKET ON IT
      A board of indices and the day's movers, drawn from endpoints the site
      already serves. If either is unreachable the board removes itself
      rather than printing an error: on a free instance a cold start is the
      normal case, and chrome that says "failed" is worse than chrome that
      waits.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : (window.API_BASE || 'https://taha-project.onrender.com');

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function open(sym) {
    sym = String(sym || '').trim().toUpperCase();
    if (!sym) return false;
    location.href = 'stock.html?ticker=' + encodeURIComponent(sym);
    return true;
  }

  /* ── 1 · Send the search somewhere real ──────────────────────────────────── */

  function hijack() {
    var input = document.getElementById('tk');
    var go = document.getElementById('go');

    if (go) {
      go.addEventListener('click', function (e) {
        var v = input && input.value.trim();
        if (!v) return;                       // let the old handler show its own hint
        e.preventDefault();
        e.stopImmediatePropagation();
        open(v);
      }, true);
    }

    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        var v = input.value.trim();
        if (!v) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        open(v);
      }, true);
    }

    // The "Try RELIANCE · HDFCBANK · …" shortcuts under the box.
    document.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('.hint b[data-t]');
      if (!b) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      open(b.dataset.t);
    }, true);
  }

  /* ── 2 · The market board ────────────────────────────────────────────────── */

  function mount() {
    if (document.querySelector('.mb')) return null;
    var main = document.querySelector('main.wrap');
    var host = document.getElementById('view-screener');
    if (!main) return null;
    var box = document.createElement('div');
    box.className = 'mb';
    box.innerHTML = '<div class="mb-idx"><div class="mb-skel"></div><div class="mb-skel"></div>' +
                    '<div class="mb-skel"></div><div class="mb-skel"></div></div>';
    // Above the search row, below the (now much shorter) masthead.
    if (host && host.parentNode) host.parentNode.insertBefore(box, host);
    else main.insertBefore(box, main.firstChild);
    return box;
  }

  function fail(box) { if (box && box.parentNode) box.parentNode.removeChild(box); }

  /* The board used to fetch /market and /sector/overview itself, which meant
     the homepage pulled the same two endpoints the chrome's ticker had just
     pulled — two callers, one screen, double the load on a 512 MB instance.
     It now listens for the ticker's broadcast and only falls back to its own
     fetch if the chrome is absent (this file works without shell.js). */
  var painted = false;

  function board() {
    var box = mount();
    if (!box) return;

    window.addEventListener('altaha:market', function (e) {
      var d = (e && e.detail) || {};
      if (!d.indices || !d.indices.length) return;
      painted = true;
      paint(box, d.indices, d.sectors);
    });

    // Fallback only: if no broadcast arrives, the chrome is not running.
    setTimeout(function () {
      if (painted) return;
      if (window.AltahaShell) {
        // The chrome IS running and still produced nothing, which means its
        // market call failed. Remove the skeleton rather than leave it
        // shimmering forever — an unresolved placeholder reads as broken.
        fail(box);
        return;
      }
      var indices = null, movers = null, done = 0;
      function maybePaint() {
        if (++done < 2) return;
        if (!indices || !indices.length) { fail(box); return; }
        painted = true; paint(box, indices, movers);
      }
      fetch(API + '/market').then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { indices = (d && d.indices) || []; })
        .catch(function () { indices = []; }).then(maybePaint);
      fetch(API + '/sector/overview?window=1d')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { movers = d; })
        .catch(function () { movers = null; }).then(maybePaint);
    }, 6000);
  }

  function paint(box, indices, sectors) {
    var biggest = Math.max.apply(null, indices.map(function (i) {
      return Math.abs(Number(i.change_pct) || 0);
    }).concat([0.01]));

    var idxHTML = indices.map(function (i, n) {
      var p = Number(i.change_pct);
      var t = p > 0 ? 'up' : (p < 0 ? 'dn' : '');
      var w = Math.min(100, (Math.abs(p) / biggest) * 100);
      return '<div class="mb-card d3-card tilt reveal" data-i="' + n + '">' +
        '<div class="k">' + esc(i.label) + '</div>' +
        '<div class="v tnum">' + (i.level == null ? '—'
          : Number(i.level).toLocaleString('en-IN', { maximumFractionDigits: 2 })) + '</div>' +
        '<div class="c tnum ' + t + '">' + (isNaN(p) ? '—'
          : (p > 0 ? '+' : '') + p.toFixed(2) + '%') + '</div>' +
        '<div class="spark"><i class="' + t + '" data-w="' + w.toFixed(0) + '"></i></div>' +
        '</div>';
    }).join('');

    // Flatten every sector's constituents into one list, then take the ends.
    var all = [];
    ((sectors && sectors.rows) || []).forEach(function (row) {
      (row.stocks || []).forEach(function (s) {
        if (s && s.symbol && s.change_pct != null) all.push(s);
      });
    });
    all.sort(function (a, b) { return b.change_pct - a.change_pct; });

    function col(title, rows, cls) {
      if (!rows.length) return '';
      return '<div class="mb-col d3-card reveal">' +
        '<h3>' + esc(title) + '</h3><ol>' +
        rows.map(function (s) {
          return '<li><a href="stock.html?ticker=' + encodeURIComponent(s.symbol) + '">' +
            esc(s.symbol) + '</a><em class="' + cls + '">' +
            (s.change_pct > 0 ? '+' : '') + Number(s.change_pct).toFixed(2) + '%</em></li>';
        }).join('') + '</ol></div>';
    }

    var moversHTML = all.length
      ? '<div class="mb-movers">' +
          col('Leading today', all.slice(0, 5), 'up') +
          col('Lagging today', all.slice(-5).reverse(), 'dn') +
        '</div>'
      : '';

    box.innerHTML = '<div class="mb-idx">' + idxHTML + '</div>' + moversHTML +
      '<p class="mb-note">Type any Indian or US stock below. You get a 0–100 score ' +
      'and every calculation that produced it — line by line.</p>';

    requestAnimationFrame(function () {
      box.querySelectorAll('.spark i').forEach(function (n) {
        n.style.width = n.dataset.w + '%';
      });
    });
    if (window.AltahaShell) window.AltahaShell.reveal();
  }

  function start() {
    hijack();
    board();
    // No interval of its own any more: the chrome already refreshes every 60
    // seconds and broadcasts, and the listener above repaints from that.
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
