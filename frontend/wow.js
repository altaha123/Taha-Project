/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — wow.js

   WOW orders: order wins measured against the company that won them.

   THE ONE JUDGEMENT THIS VIEW MAKES
   An order is "WOW" when its DISCLOSED value is at least a set share of market
   capitalisation. The threshold comes from the API and is printed on the page,
   because a rule the reader cannot see is a rule they cannot argue with.

   HOW THE PAGE IS LAID OUT, AND WHY
   The WOW orders are the page, so they come first and get the room: who won
   what from whom, how big it is against the company, and a bar that shows
   that size at a glance. Everything else is still here and one line each —
   the smaller orders, the bids and memoranda that are not orders yet, the
   orders with no rupee value — and opens to the same detail when asked.

   WHAT IT WILL NOT DO
   An order whose value the company did not disclose is shown — it happened,
   and hiding it would misrepresent the day — but it is never ranked, never
   given an estimated number, and never described as small. "Not disclosed" and
   "small" are different facts and this page keeps them apart. A lowest bid or
   a memorandum of understanding is never called WOW: it is not an order.

   No target, no entry, no instruction. An order is an event with a size.

   NOTHING HERE WAITS ON THE SERVER READING A PDF
   /wow-orders answers with whatever has been read and says whether more is
   being read behind it. While it is, this asks again every few seconds.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var MAX_POLLS = 60;            // four minutes of asking again, then stop
  var BAR_FULL = 50;             // the bar is full at half the company's value

  var loaded = false, timer = null, polls = 0, lastPaint = '';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function link(url) {
    return /^https?:\/\//i.test(String(url || '')) ? esc(url) : '';
  }
  function cr(v) {
    var n = Number(v);
    if (v == null || !isFinite(n)) return '—';
    if (n === 0) return '₹0';
    if (n >= 100000) return '₹' + (n / 100000).toFixed(2) + ' lakh cr';
    if (n >= 1) return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: n >= 100 ? 0 : 2 }) + ' cr';
    return '₹' + (n * 100).toFixed(2) + ' lakh';
  }
  function pctText(p) {
    var n = Number(p);
    if (!isFinite(n)) return '—';
    if (n >= 10) return Math.round(n) + '%';
    if (n >= 0.1) return n.toFixed(1) + '%';
    return '<0.1%';
  }
  function day(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
    } catch (e) { return String(iso).slice(0, 10); }
  }
  function visible() {
    var view = $('view-wow');
    return !!view && view.style.display !== 'none';
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  /* ── What a row says ──────────────────────────────────────────────────── */

  var STAGE = {
    l1: { tag: 'Lowest bidder', verb: 'lowest bid', why: 'Lowest bidder — the order has not been awarded yet' },
    mou: { tag: 'MoU', verb: 'memorandum of understanding', why: 'A memorandum of understanding — not an order' },
    update: { tag: 'Update', verb: 'order', why: 'An update to an order filed earlier' }
  };

  /* The bar: the order against the company, full at half the company's
     value, with a tick where WOW begins. */
  function bar(r, threshold) {
    var p = r.pct_of_market_cap;
    if (p == null) return '';
    var w = Math.max(1.5, Math.min(100, 100 * p / BAR_FULL));
    var t = Math.min(100, 100 * threshold / BAR_FULL);
    return '<span class="wo-bar' + (p >= BAR_FULL ? ' over' : '') + '" role="img" aria-label="' +
      esc(pctText(p)) + ' of market cap">' +
      '<i style="width:' + w.toFixed(1) + '%"></i>' +
      '<u style="left:' + t.toFixed(1) + '%"></u></span>';
  }

  /* "₹2,691 cr order from NTPC Green Energy Limited" — the sentence the
     exchange's headline never is. Built only from what the filing states. */
  function sentence(r) {
    var st = STAGE[r.stage];
    var what = st ? st.verb : (r.kind ? r.kind.toLowerCase() : 'order');
    var from = r.customer ? ' from <b>' + esc(r.customer) + '</b>' : '';
    if (r.value_cr != null) {
      return '<b class="wo-val tnum">' + cr(r.value_cr) + '</b> ' + esc(what) + from;
    }
    return esc(what.charAt(0).toUpperCase() + what.slice(1)) + from;
  }

  function noValue(r) {
    if (r.value_state === 'confidential') return 'The company says the value is confidential';
    if (r.value_state === 'unread') return 'The filing has not been read yet';
    if (r.size_text) return 'No rupee value. Size as filed: ' + r.size_text;
    return 'The filing states no rupee value';
  }

  /* A length of sales a reader can picture: weeks, then months, then years. */
  function span(months) {
    var m = Number(months);
    if (m < 0.25) return 'under a week';
    if (m < 1) return 'about ' + plural(Math.max(1, Math.round(m * 4.35)), 'week', 'weeks');
    if (m < 18) {
      var r1 = Math.round(m * 10) / 10;
      return (r1 % 1 === 0 ? String(r1) : r1.toFixed(1)) + (r1 === 1 ? ' month' : ' months');
    }
    return (m / 12).toFixed(1) + ' years';
  }

  function chips(r) {
    var out = [];
    if (r.market_cap_cr != null) out.push(['Market cap', cr(r.market_cap_cr)]);
    if (r.months_of_sales != null) {
      out.push(['Against sales', span(r.months_of_sales) + ' of ' +
        (r.sales_year ? esc(r.sales_year) + ' ' : 'a year’s ') + 'sales']);
    }
    if (r.period) out.push(['To be done', esc(r.period)]);
    out.push(['Filed', esc(day(r.at)) + (r.filings > 1 ? ' · ' + r.filings + ' filings' : '')]);
    return '<dl class="wo-facts">' + out.map(function (c) {
      return '<div><dt>' + c[0] + '</dt><dd>' + c[1] + '</dd></div>';
    }).join('') + '</dl>';
  }

  function cautions(r) {
    var out = '';
    if (r.outsized) {
      out += '<p class="wo-warn">This order is larger than the whole company’s market cap. ' +
        'That does happen to small companies; it is also what a misread figure looks like. ' +
        'Open the filing before relying on it.</p>';
    }
    if (r.stage !== 'order' && STAGE[r.stage]) {
      out += '<p class="wo-warn soft">' + esc(STAGE[r.stage].why) + ', so it is not counted as WOW.</p>';
    }
    return out;
  }

  function flags(r) {
    var f = '';
    if (r.value_cr != null && !r.value_confident) {
      f += '<em class="fl soft" title="The filing states this figure but does not label it as the order value">unlabelled figure</em>';
    }
    if (r.currency_converted) {
      f += '<em class="fl soft" title="Converted from US dollars at an assumed rate' +
        (r.fx_rate ? ' of ₹' + esc(r.fx_rate) : '') + '">converted</em>';
    }
    return f;
  }

  function evidence(r) {
    if (!r.excerpt) return '';
    return '<details class="wo-ev" data-k="ev:' + esc(r.pdf || r.symbol) + '">' +
      '<summary>Where this figure came from</summary>' +
      '<blockquote>' + esc(r.excerpt) + '</blockquote>' +
      '<p class="basis">' + esc(r.value_basis || '') +
        (r.currency_converted && r.fx_rate
          ? ' · US dollars converted at ₹' + esc(r.fx_rate) + ', an assumed rate' : '') +
      '</p></details>';
  }

  function coName(r) {
    return r.symbol
      ? '<a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.company || r.symbol) + '</a>'
      : esc(r.company || 'Unnamed company');
  }

  /* Everything under the top line. Shared by a WOW card and an opened row. */
  function detail(r) {
    var pdf = link(r.pdf);
    return (r.nature ? '<p class="wo-for">' + esc(r.nature) + '</p>' : '') +
      (r.value_cr == null ? '<p class="wo-for none">' + esc(noValue(r)) + '</p>' : '') +
      chips(r) + cautions(r) +
      '<div class="wo-foot">' + evidence(r) +
        (pdf ? '<a class="wo-pdf" href="' + pdf + '" target="_blank" rel="noopener">Open the filing →</a>' : '') +
      '</div>';
  }

  /* A WOW order: the full card. */
  function card(r, threshold, rank) {
    return '<article class="wo is-wow">' +
      '<div class="wo-meter">' +
        '<span class="wo-rank tnum">' + rank + '</span>' +
        '<span class="wo-pct wow tnum">' + esc(pctText(r.pct_of_market_cap)) + '</span>' +
        '<span class="wo-of">of market cap</span>' +
        bar(r, threshold) +
      '</div>' +
      '<div class="wo-body">' +
        '<div class="wo-co">' + coName(r) +
          '<em class="fl wow">WOW</em>' +
          (r.kind ? '<em class="fl soft">' + esc(r.kind) + '</em>' : '') + flags(r) +
        '</div>' +
        '<p class="wo-hl">' + sentence(r) + '</p>' +
        detail(r) +
      '</div>' +
      '</article>';
  }

  /* Every other order: one line, which opens. */
  function line(r, threshold) {
    var st = STAGE[r.stage];
    var size;
    if (r.pct_of_market_cap != null) {
      size = '<span class="wo-pct tnum">' + esc(pctText(r.pct_of_market_cap)) + '</span>' +
        '<span class="wo-of">of market cap</span>' + bar(r, threshold);
    } else if (r.value_cr != null) {
      size = '<span class="wo-pct tnum none">—</span><span class="wo-of">market cap unavailable</span>';
    } else {
      size = '<span class="wo-pct tnum none">—</span><span class="wo-of">' +
        (r.value_state === 'confidential' ? 'value confidential'
          : (r.value_state === 'unread' ? 'not read yet' : 'value not disclosed')) + '</span>';
    }
    return '<details class="wo wo-row" data-k="row:' + esc(r.pdf || (r.symbol + r.at)) + '">' +
      '<summary>' +
        '<span class="wo-co">' + coName(r) +
          (st ? '<em class="fl soft">' + esc(st.tag) + '</em>' : '') + flags(r) + '</span>' +
        '<span class="wo-hl">' + sentence(r) + '</span>' +
        '<span class="wo-size">' + size + '</span>' +
      '</summary>' +
      '<div class="wo-body">' + detail(r) + '</div>' +
      '</details>';
  }

  /* ── The top of the page ───────────────────────────────────────────────── */

  function lead(d, groups) {
    var c = d.counts || {}, t = d.threshold_pct, wow = groups.wow;
    var top = wow[0] || groups.sized[0];
    var biggest = groups.wow.concat(groups.sized).slice().sort(function (a, b) {
      return (b.value_cr || 0) - (a.value_cr || 0);
    })[0];
    var say = wow.length
      ? '<b class="tnum">' + wow.length + '</b> ' + (wow.length === 1 ? 'order' : 'orders') +
        ' this week ' + (wow.length === 1 ? 'is' : 'are') + ' big enough to matter'
      : 'No order this week is big enough to be called WOW';
    function tile(label, r, big, sub) {
      if (!r) return '';
      return '<div class="wo-tile"><span class="lb">' + label + '</span>' +
        '<span class="vv tnum">' + big + '</span>' +
        '<span class="sub">' + esc(r.company || r.symbol || '') + (sub ? ' · ' + sub : '') + '</span></div>';
    }
    return '<section class="wo-lead">' +
      '<h3 class="wo-say">' + say + '</h3>' +
      '<p class="wo-rule">An order is <b>WOW</b> when it is worth at least <b>' + esc(String(t)) +
        '%</b> of the company’s market cap, which is what the whole company is valued at on the ' +
        'stock market. A ₹100 crore order is routine for a giant and can be a year’s work for a small company.</p>' +
      '<div class="wo-tiles">' +
        tile('Biggest against its company', top,
          top ? esc(pctText(top.pct_of_market_cap)) : '', top ? cr(top.value_cr) + ' order' : '') +
        tile('Biggest in rupees', biggest, biggest ? cr(biggest.value_cr) : '',
          biggest && biggest.pct_of_market_cap != null ? esc(pctText(biggest.pct_of_market_cap)) + ' of market cap' : '') +
        '<div class="wo-tile"><span class="lb">Read this week</span>' +
          '<span class="vv tnum">' + (c.orders || 0) + '</span>' +
          '<span class="sub">order filings · ' + (c.with_value || 0) + ' state a rupee value</span></div>' +
      '</div>' +
      '</section>';
  }

  function counts(d) {
    var c = d.counts || {};
    return '<div class="wo-counts">' +
      '<span><b class="tnum">' + (c.wow || 0) + '</b> WOW</span>' +
      '<span><b class="tnum">' + (c.with_value || 0) + '</b> with a disclosed value</span>' +
      '<span><b class="tnum">' + (c.value_not_disclosed || 0) + '</b> value not disclosed</span>' +
      (c.unread ? '<span><b class="tnum">' + c.unread + '</b> not read yet</span>' : '') +
      (d.reading ? '<span class="st is-on" role="status">Checking for new filings…</span>' : '') +
      '<span class="thr">threshold ' + esc(String(d.threshold_pct)) + '% of market cap</span>' +
      '</div>';
  }

  function group(title, n, note, body, open) {
    if (!n) return '';
    return '<section class="wo-group">' +
      '<h3 class="wo-gh">' + title + ' <span class="tnum">' + n + '</span></h3>' +
      '<p class="wo-gn">' + note + '</p>' +
      '<div class="wo-list' + (open ? '' : ' rows') + '">' + body + '</div>' +
      '</section>';
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
      '<h3>All disclosed orders, this quarter against last</h3>' +
      '<div class="wq-grid">' + side(prev) +
        '<div class="wq-arrow">' + delta + '</div>' + side(now) + '</div>' +
      '<p class="wq-note">' + esc(q.caveat) + '</p>' +
      '</section>';
  }

  /* ── Painting ──────────────────────────────────────────────────────────── */

  function keepOpen(box) {
    var state = {};
    box.querySelectorAll('details[data-k]').forEach(function (el) {
      state[el.getAttribute('data-k')] = el.open;
    });
    return state;
  }
  function restoreOpen(box, state) {
    box.querySelectorAll('details[data-k]').forEach(function (el) {
      var k = el.getAttribute('data-k');
      if (Object.prototype.hasOwnProperty.call(state, k)) el.open = state[k];
    });
  }

  function waiting() {
    return '<div class="wo-empty is-loading" aria-busy="true">' +
      '<b>Reading this week’s order filings…</b> The first read takes a minute or two, ' +
      'and the orders appear here as they are read. There is no need to reload.' +
      '<span class="wo-skel"></span><span class="wo-skel"></span><span class="wo-skel"></span></div>';
  }

  function paint(d) {
    var box = $('wow-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="wo-empty">' +
        esc((d && d.message) || 'The orders feed could not be read.') + '</div>';
      return;
    }
    // An unchanged answer is not repainted: a reader who has opened a row
    // should not have the list rebuilt under them every few seconds.
    var sig = JSON.stringify([d.rows, d.counts, d.reading, d.note, d.quarter]);
    if (sig === lastPaint) return;
    lastPaint = sig;

    var rows = d.rows || [], t = d.threshold_pct, open = keepOpen(box);
    if (!rows.length) {
      box.innerHTML = d.reading ? waiting()
        : '<div class="wo-empty">No order announcements in this window. ' +
          'Order flow is lumpy — a quiet week is normal, not a fault.</div>' +
          (d.note ? '<p class="wo-note">' + esc(d.note) + '</p>' : '');
      return;
    }
    var firm = rows.filter(function (r) { return (r.stage || 'order') === 'order'; });
    var g = {
      wow: firm.filter(function (r) { return r.wow; }),
      sized: firm.filter(function (r) { return !r.wow && r.value_cr != null; }),
      blank: firm.filter(function (r) { return r.value_cr == null; }),
      soft: rows.filter(function (r) { return (r.stage || 'order') !== 'order'; })
    };
    var one = function (r) { return line(r, t); };

    box.innerHTML = lead(d, g) + counts(d) +
      group('WOW orders', g.wow.length,
        'Worth ' + esc(String(t)) + '% or more of the company’s market cap. The largest against its company comes first.',
        g.wow.map(function (r, i) { return card(r, t, i + 1); }).join(''), true) +
      group('Other orders with a value', g.sized.length,
        'Under ' + esc(String(t)) + '% of market cap. Tap one for what it is for and where the figure came from.',
        g.sized.map(one).join('')) +
      group('Not firm orders', g.soft.length,
        'A lowest bid that has not been awarded, a memorandum of understanding, or an update to an order ' +
        'filed earlier. Listed so the week is complete, and never counted as WOW.',
        g.soft.map(one).join('')) +
      group('No rupee value', g.blank.length,
        'The company gave no amount, sized the order in megawatts or tonnes, or said the value is confidential. ' +
        'Never ranked, and never given an assumed figure.',
        g.blank.map(one).join('')) +
      quarterBlock(d.quarter) +
      (d.note ? '<p class="wo-note">' + esc(d.note) + '</p>' : '') +
      '<p class="wo-src">' + esc(d.source) + '</p>' +
      '<p class="wo-src">' + esc(d.explain) + '</p>';
    restoreOpen(box, open);
  }

  function again(seconds) {
    clearTimeout(timer);
    if (!seconds || polls >= MAX_POLLS) return;
    timer = setTimeout(function () {
      if (visible()) { polls++; load(true); }
    }, Math.max(3, seconds) * 1000);
  }

  function load(quiet) {
    var box = $('wow-body');
    if (box && !quiet) {
      lastPaint = '';
      box.innerHTML = waiting();
    }
    fetch(API + '/wow-orders?days=7')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function (d) {
        paint(d);
        again(d && d.reading ? (d.poll_seconds || 4) : 0);
      })
      .catch(function () {
        // A background refresh that fails leaves what is on screen alone.
        if (quiet) { again(15); return; }
        if (box) {
          // data-nosnippet: a search engine that runs this page while the API
          // is asleep must not quote this line as what the page says.
          box.innerHTML = '<div class="wo-empty" data-nosnippet>The engine is unreachable. ' +
            'If it has been idle it takes about thirty seconds to wake. ' +
            '<button type="button" class="wo-retry">Try again</button></div>';
          var b = box.querySelector('.wo-retry');
          if (b) b.addEventListener('click', function () { polls = 0; load(false); });
        }
      });
  }

  /* Loaded when the tab is first opened, never on page load: this reads PDFs. */
  function watch() {
    var view = $('view-wow');
    if (!view) return;
    var seen = new MutationObserver(function () {
      if (view.style.display !== 'none' && !loaded) { loaded = true; load(false); }
    });
    seen.observe(view, { attributes: true, attributeFilter: ['style'] });
    if (view.style.display !== 'none' && !loaded) { loaded = true; load(false); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }

  window.AltahaWow = { paint: paint };
})();
