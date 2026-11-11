/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Stock picks

   WHAT THIS IS
   The four lists the Ideas door leads with: this week, this month, momentum,
   long term. One tab each. Under the tabs, one line saying what the list is
   and one line saying how it did when tested, then the picks.

   It is drawn in two places from one set of functions, so the two can never
   describe the same pick differently:

     · the Ideas door (doors.js)       the top five, in #dri-picks
     · the Stock picks tab (index.html) all fifteen, each with its ledger

   WHERE THE NUMBERS COME FROM
   /ideas?horizon=week|month|momentum|long. The order is the server's. The
   tested record (`tested`) is read from the study file the API ships
   (backend/ideas_study.json); nothing here computes or rounds a return it
   was not given.

   A SCAN FROM BEFORE THE LISTS
   Until the first scan with leader ranks finishes, the API answers with the
   old short and medium lists (`method_key` is absent). Those rows are drawn
   by the page as they always were; this file says so in one line and stays
   out of the way.

   WORDS
   A reader told us the site had too much writing. Each pick gets at most
   four facts of four words. Everything longer is behind "Details".
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';
  if (typeof window !== 'undefined' && window.AltahaPicks) return;

  var LISTS = [
    { key: 'week',     label: 'This week',  short: 'week',  hold: 'about a week' },
    { key: 'month',    label: 'This month', short: 'month', hold: 'about a month' },
    { key: 'momentum', label: 'Momentum',   hold: 'about 3 months' },
    { key: 'long',     label: 'Long term',  hold: 'about a year' }
  ];
  var KEYS = LISTS.map(function (l) { return l.key; });
  var STORE = 'altaha-pick-list';
  var DEFAULT = 'month';
  var FRESH_MS = 120000;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function finite(v) { return v != null && v !== '' && isFinite(Number(v)); }
  function inr(v) {
    if (!finite(v)) return '—';
    var n = Number(v);
    return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: n >= 1000 ? 0 : 2 });
  }
  function signed(v, dp) {
    if (!finite(v)) return '—';
    var n = Number(v);
    return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(dp == null ? 1 : dp) + '%';
  }
  function valid(key) { return KEYS.indexOf(key) !== -1; }

  /* The chosen list is a convenience, never state the page depends on. */
  function chosen() {
    try { var k = localStorage.getItem(STORE); if (valid(k)) return k; } catch (e) {}
    return DEFAULT;
  }
  function remember(key) { try { localStorage.setItem(STORE, key); } catch (e) {} }

  /* ── What a pick says ──────────────────────────────────────────────────── */

  function whyHTML(s) {
    var why = (s && s.why) || [];
    if (!why.length) return '';
    return '<div class="pk-why">' + why.slice(0, 4).map(function (w) {
      return '<span>' + esc(w) + '</span>';
    }).join('') + '</div>';
  }

  /* Hold, and the one price that ends it. No target: the test found a target
     was the most expensive rule a plan could carry. */
  function planHTML(p) {
    if (!p || p.style !== 'hold' || !finite(p.stop)) return '';
    return '<div class="pk-plan">' +
      '<span><b>Hold</b> ' + esc(p.hold_text || '') + '</span>' +
      '<span><b>Exit below</b> ' + inr(p.stop) +
        (finite(p.risk_pct) ? ' <small>−' + Number(p.risk_pct).toFixed(0) + '%</small>' : '') + '</span>' +
    '</div>';
  }

  /* ── The tested record ─────────────────────────────────────────────────── */

  function isTested(d) { return !!(d && d.method_key === 'tested_lists'); }

  function recordHTML(d) {
    var t = d && d.tested;
    if (!t || !finite(t.up_pct)) return '';
    var st = d.study || {};
    var years = (st.from && st.to) ? String(st.from).slice(0, 4) + '–' + String(st.to).slice(0, 4) : '';
    var h = t.by_half || {};
    var halves = Object.keys(h).map(function (k) {
      var x = h[k] || {};
      return '<li><b>' + esc(k.replace('-', '–')) + '</b> ' + Math.round(x.up_pct) + ' in 100 rose · ' +
        signed(x.avg_pct) + ' · market ' + signed(x.index_avg_pct) + '</li>';
    }).join('');
    return '<div class="pk-record">' +
      '<div class="pk-record-n">' +
        '<span><b>' + Math.round(t.up_pct) + '</b><small>in 100 picks rose</small></span>' +
        '<span><b class="' + (t.avg_pct >= 0 ? 'up' : 'dn') + '">' + signed(t.avg_pct) + '</b><small>average pick</small></span>' +
        '<span><b>' + signed(t.index_avg_pct) + '</b><small>the market</small></span>' +
      '</div>' +
      '<details class="pk-how"><summary>Tested on NSE prices' + (years ? ', ' + esc(years) : '') + '</summary>' +
        '<ul>' +
          '<li>' + Number(t.picks).toLocaleString('en-IN') + ' picks from ' + Number(t.list_dates).toLocaleString('en-IN') +
            ' past lists. Bought next morning, held ' + esc(d.hold_text || '') + '.</li>' +
          halves +
          '<li>Half the picks made less than ' + signed(t.median_pct) + '. One in twenty lost more than ' +
            Math.abs(Number(t.worst_5pct)).toFixed(0) + '%.</li>' +
          '<li>Before costs and tax. The past does not promise the future.</li>' +
        '</ul></details>' +
    '</div>';
  }

  /* What the list's own calls have done since it went live. Shown only once
     there is something to show: five closed calls. */
  function liveHTML(d) {
    var l = d && d.live;
    if (!l || !finite(l.closed) || l.closed < 5) return '';
    return '<p class="pk-live">Live since ' + esc(l.since || '') + ': ' + l.closed_up + ' of ' + l.closed +
      ' closed calls rose' + (finite(l.closed_avg_pct) ? ', average ' + signed(l.closed_avg_pct) : '') + '.</p>';
  }

  function tabsHTML(active, cls) {
    return '<div class="pk-tabs ' + (cls || '') + '" role="tablist" aria-label="Holding period">' +
      LISTS.map(function (l) {
        var on = l.key === active;
        /* "This" drops out on a phone, where four full labels do not fit. */
        var text = l.short ? '<i>This </i>' + esc(l.short) : esc(l.label);
        return '<button type="button" role="tab" class="pk-tab' + (on ? ' on' : '') + '" data-pick="' + l.key +
          '" aria-selected="' + on + '" aria-label="' + esc(l.label) + '">' + text + '</button>';
      }).join('') + '</div>';
  }

  function updatedText(d) {
    if (!d || !d.scanned_at) return '';
    var days = d.staleness && finite(d.staleness.days) ? Number(d.staleness.days) : null;
    var when = days === 0 ? 'today' : days === 1 ? 'yesterday' : days != null ? days + ' days ago'
      : String(d.scanned_at).split(',')[0];
    return 'Updated ' + when;
  }

  /* ── The door panel: top five ──────────────────────────────────────────── */

  var cache = {};
  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : ((typeof window !== 'undefined' && window.API_BASE) || 'https://taha-project.onrender.com');

  function load(key) {
    var hit = cache[key];
    if (hit && Date.now() - hit.at < FRESH_MS) return Promise.resolve(hit.data);
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, 45000);
    return fetch(API + '/ideas?horizon=' + key + '&limit=15', ctl ? { signal: ctl.signal } : {})
      .then(function (r) { if (timer) clearTimeout(timer); return r.ok ? r.json() : null; })
      .then(function (d) { if (d) cache[key] = { at: Date.now(), data: d }; return d; })
      .catch(function () { if (timer) clearTimeout(timer); return null; });
  }

  function cardHTML(s, i) {
    var p = s.plan || {};
    return '<a class="pk-card" href="stock.html?ticker=' + encodeURIComponent(s.symbol) + '" data-t="' + esc(s.symbol) + '">' +
      '<span class="pk-rank">' + (i + 1) + '</span>' +
      '<span class="pk-main">' +
        '<span class="pk-name">' + esc(s.name || s.symbol) + '</span>' +
        '<span class="pk-sym">' + esc(s.symbol) + ' · ' + inr(s.price) + '</span>' +
        whyHTML(s) +
      '</span>' +
      (p.style === 'hold' && finite(p.stop)
        ? '<span class="pk-exit"><small>Exit below</small><b>' + inr(p.stop) + '</b></span>' : '') +
    '</a>';
  }

  function bodyHTML(key, d) {
    if (!d) {
      return '<p class="pk-quiet">The picks could not be loaded. If the site has been idle it takes about thirty seconds to wake. ' +
        '<button type="button" class="pk-retry" data-pick="' + key + '">Try again</button></p>';
    }
    if (!d.available) return '<p class="pk-quiet">No scan has run yet, so there are no picks to show.</p>';
    var rows = d.rows || [];
    var meta = LISTS[KEYS.indexOf(key)];
    var out = '';
    if (isTested(d)) {
      out += '<p class="pk-idea">' + esc(d.idea || '') + ' <span>Hold ' + esc(d.hold_text || meta.hold) + '.</span></p>' +
        recordHTML(d) + liveHTML(d);
    } else {
      out += '<p class="pk-quiet">These are from the last scan, made the old way. The four tested lists appear after the next scan.</p>';
    }
    if (d.staleness && d.staleness.warn) {
      out += '<p class="pk-stale">' + esc(d.staleness.text || 'This list is old.') + '</p>';
    }
    out += rows.length
      ? '<div class="pk-cards">' + rows.slice(0, 5).map(cardHTML).join('') + '</div>'
      : '<p class="pk-quiet">Nothing passed every test in this scan.</p>';
    out += '<div class="pk-foot">' +
      (rows.length ? '<button type="button" class="pk-all" data-goto="research/ideas">See all ' + rows.length + ' picks</button>' : '') +
      '<span class="pk-updated">' + esc(updatedText(d)) + '</span></div>';
    return out;
  }

  function mount(host) {
    if (!host || host.dataset.pkBuilt) return;
    host.dataset.pkBuilt = '1';
    var key = chosen();
    host.innerHTML = '<div class="pk-head"><span class="pk-label">Stock picks</span></div>' +
      tabsHTML(key) + '<div class="pk-body" aria-live="polite"></div>';
    var body = host.querySelector('.pk-body');

    function show(k) {
      key = k;
      remember(k);
      host.querySelectorAll('.pk-tab').forEach(function (b) {
        var on = b.dataset.pick === k;
        b.classList.toggle('on', on);
        b.setAttribute('aria-selected', String(on));
      });
      body.innerHTML = '<div class="pk-skel"><i></i><i></i><i></i></div>';
      load(k).then(function (d) { if (key === k) body.innerHTML = bodyHTML(k, d); });
    }

    host.addEventListener('click', function (ev) {
      var tab = ev.target.closest('.pk-tab, .pk-retry');
      if (tab && host.contains(tab)) {
        if (tab.classList.contains('pk-retry')) delete cache[tab.dataset.pick];
        show(tab.dataset.pick);
        return;
      }
      var card = ev.target.closest('.pk-card');
      if (card && window.AltahaOpenStock) {
        ev.preventDefault();
        window.AltahaOpenStock(card.dataset.t, 'picks');
      }
    });
    show(key);
  }

  var api = {
    LISTS: LISTS, valid: valid, chosen: chosen, remember: remember,
    isTested: isTested, whyHTML: whyHTML, planHTML: planHTML, recordHTML: recordHTML,
    liveHTML: liveHTML, updatedText: updatedText, mount: mount, signed: signed, inr: inr
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.AltahaPicks = api;
})();
