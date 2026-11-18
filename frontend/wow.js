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
  /* Exchange time, always. A filing made at 11:02 in Mumbai read "05:32 am"
     on a machine set to UTC, which is a different fact about the filing. */
  var IST = { timeZone: 'Asia/Kolkata' };
  function when(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d)) return String(iso).slice(0, 16);
      return d.toLocaleDateString('en-IN', Object.assign({ day: 'numeric', month: 'short' }, IST)) +
        ', ' + d.toLocaleTimeString('en-IN', Object.assign({ hour: '2-digit', minute: '2-digit' }, IST)) +
        ' IST';
    } catch (e) { return String(iso).slice(0, 16); }
  }
  function clock(iso) {
    try {
      var d = new Date(iso);
      return isNaN(d) ? '' : d.toLocaleTimeString('en-IN',
        Object.assign({ hour: '2-digit', minute: '2-digit' }, IST)) + ' IST';
    } catch (e) { return ''; }
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

  /* What the row can say about the value. "Not read yet" and "could not be
     read" are not "not disclosed": the filing may well state a figure. */
  var STATE = {
    unread: { head: 'filing not read yet', order: 'not read yet' },
    unreadable: { head: 'filing could not be read', order: 'could not be read' }
  };

  function row(r, threshold) {
    var pct = r.pct_of_market_cap;
    var st = STATE[r.read_state];
    var head;
    if (pct != null) {
      head = '<span class="wo-pct tnum' + (r.wow ? ' wow' : '') + '">' +
        pct.toFixed(1) + '%</span><span class="wo-of">of market cap</span>';
    } else if (r.value_cr != null) {
      head = '<span class="wo-pct tnum none">' + cr(r.value_cr) +
        '</span><span class="wo-of">market cap unavailable</span>';
    } else if (st) {
      head = '<span class="wo-pct tnum none">—</span>' +
        '<span class="wo-of"' + (r.read_state === 'unreadable'
          ? ' title="The PDF has no text layer, usually a scan. Any value it states is in the image."'
          : ' title="Not downloaded yet. The next refresh reads it."') + '>' + st.head + '</span>';
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
          '<span><b>Order</b> ' + (r.value_cr != null ? cr(r.value_cr)
            : (st ? st.order : 'not disclosed')) + '</span>' +
          '<span><b>Market cap</b> ' + (r.market_cap_cr == null ? '—' : cr(r.market_cap_cr)) + '</span>' +
        '</div>' +
        (r.excerpt
          ? '<details class="wo-ev" data-key="' + esc(r.pdf || r.headline || '') + '">' +
            '<summary>Where this figure came from</summary>' +
            '<blockquote>' + esc(r.excerpt) + '</blockquote>' +
            '<p class="basis">' + esc(r.value_basis || '') + '</p></details>'
          : '') +
        (r.pdf ? '<a class="wo-pdf" href="' + esc(r.pdf) + '" target="_blank" rel="noopener">Open the filing →</a>' : '') +
      '</div>' +
      '</article>';
  }

  /* One line above the list saying how current it is. The server answers at
     once and reads new filings behind the answer; while it does, this says
     so and the page asks again by itself. */
  function status(d, rows) {
    var asOf = d.as_of ? 'Read at ' + clock(d.as_of) + '. ' : '';
    if (d.refreshing) {
      return '<div class="wo-status is-busy" role="status" aria-live="polite">' +
        '<i aria-hidden="true"></i><span>' +
        (rows.length
          ? asOf + 'Checking the exchange for newer filings — this list updates by itself.'
          : 'Reading this week’s order filings. The first read of a week takes a minute or two; ' +
            'this page fills in by itself.') +
        '</span></div>';
    }
    if (d.refresh_error) {
      return '<div class="wo-status is-warn" role="status"><span>' +
        'Could not check the exchange for newer filings just now. ' +
        (rows.length ? asOf + 'Showing what was read then.' : '') +
        '</span><button type="button" class="wo-retry" data-wow-retry>Try again</button></div>';
    }
    return d.as_of ? '<div class="wo-status"><span>' + asOf.trim() + '</span></div>' : '';
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

    // While a first read is still going, "0 WOW" would be a finding it has not made.
    var bar = (!rows.length && d.refreshing) ? '' : '<div class="wo-counts">' +
      '<span><b class="tnum">' + (c.wow || 0) + '</b> WOW</span>' +
      '<span><b class="tnum">' + (c.with_value || 0) + '</b> with a disclosed value</span>' +
      '<span><b class="tnum">' + (c.value_not_disclosed || 0) + '</b> value not disclosed</span>' +
      (c.unreadable ? '<span><b class="tnum">' + c.unreadable + '</b> could not be read</span>' : '') +
      (c.not_read ? '<span><b class="tnum">' + c.not_read + '</b> not read yet</span>' : '') +
      '<span class="thr">threshold ' + esc(String(d.threshold_pct)) + '% of market cap</span>' +
      '</div>';

    var body = rows.length
      ? rows.map(function (r) { return row(r, d.threshold_pct); }).join('')
      : (d.refreshing ? ''
        : '<div class="wo-empty">No order announcements in this window. ' +
          'Order flow is lumpy — a quiet week is normal, not a fault.</div>');

    // A repaint must not snap shut the evidence a reader has open.
    var open = {};
    box.querySelectorAll('details.wo-ev[open]').forEach(function (el) {
      open[el.getAttribute('data-key')] = 1;
    });

    box.innerHTML = status(d, rows) + bar + quarterBlock(d.quarter) +
      '<div class="wo-list">' + body + '</div>' +
      (d.note ? '<p class="wo-note">' + esc(d.note) + '</p>' : '') +
      '<p class="wo-src">' + esc(d.source) + '</p>' +
      '<p class="wo-src">' + esc(d.explain) + '</p>';

    box.querySelectorAll('details.wo-ev').forEach(function (el) {
      if (open[el.getAttribute('data-key')]) el.open = true;
    });
  }

  function failed(box, slow) {
    if (!box) return;
    box.innerHTML = '<div class="wo-empty"><p>' +
      (slow
        ? 'The engine is taking too long to answer. If it has been idle it takes about thirty seconds to wake.'
        : 'The engine is unreachable. If it has been idle it takes about thirty seconds to wake.') +
      '</p><button type="button" class="wo-retry" data-wow-retry>Try again</button></div>';
  }

  var WAIT_MS = 25000;        // one request; the server answers in well under a second when awake
  var POLL_MS = 8000;         // while a refresh is reading filings
  var POLL_MAX = 30;          // four minutes, then the reader can press Try again
  var polls = 0, timer = null, painted = false, pending = false, inflight = false;

  function get() {
    var ctl = window.AbortController ? new AbortController() : null;
    var t = setTimeout(function () { if (ctl) ctl.abort(); }, WAIT_MS);
    return fetch(API + '/wow-orders?days=7', ctl ? { signal: ctl.signal } : {})
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .finally(function () { clearTimeout(t); });
  }

  function load() {
    var box = $('wow-body');
    if (inflight) return;              // the view's style changes more than once per switch
    inflight = true;
    clearTimeout(timer);
    if (box && !painted) {
      box.innerHTML = '<div class="wo-empty is-loading" aria-busy="true">' +
        'Loading order wins…</div>';
    }
    get().then(function (d) {
      inflight = false;
      paint(d);
      painted = true;
      pending = !!(d && d.refreshing);
      var view = $('view-wow');
      if (!pending || !view || view.style.display === 'none') return;
      if (polls < POLL_MAX) {
        polls += 1;
        timer = setTimeout(load, POLL_MS);
      } else {
        // Stopped asking: say so, rather than promising an update that will not come.
        var s = box && box.querySelector('.wo-status span');
        if (s) {
          s.textContent = 'Still reading the filings. ';
          s.insertAdjacentHTML('afterend',
            '<button type="button" class="wo-retry" data-wow-retry>Check again</button>');
          s.parentNode.classList.remove('is-busy');
        }
      }
    }).catch(function (e) {
      inflight = false;
      // A list already on screen stays there; only a first load shows the error.
      if (!painted) failed(box, e && e.name === 'AbortError');
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('[data-wow-retry]')) return;
    polls = 0; painted = false;
    load();
  });

  /* Loaded when the tab is first opened, never on page load: this reads PDFs. */
  function watch() {
    var view = $('view-wow');
    if (!view) return;
    var seen = new MutationObserver(function () {
      if (view.style.display === 'none') return;
      if (!loaded) { loaded = true; load(); }
      // Back on the tab while a refresh was still reading: pick it up again.
      else if (pending) { polls = 0; load(); }
    });
    seen.observe(view, { attributes: true, attributeFilter: ['style'] });
    if (view.style.display !== 'none' && !loaded) { loaded = true; load(); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }
})();
