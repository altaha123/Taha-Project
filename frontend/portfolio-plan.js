/* Altaha — Your action plan

   WHAT A READER CAME FOR
   "What should I do with my holdings?" The review used to answer every other
   question first — concentration, risk budgets, factor exposure — and this
   one never. This file answers it at the top of the page, in one card per
   holding: EXIT, TRIM, AVERAGE DOWN, ADD or HOLD, the exact shares and
   rupees, one plain sentence saying why, and where a stronger company exists
   in the same industry, its name. Then the sectors doing well where the
   reader holds little, with the best-scoring stocks in each.

   The calls themselves are made on the server (backend/action_plan.py), from
   written-down rules; this file only draws them. They are advice, shown by
   the owner's decision, and the page says in plain words that Altaha is not
   a SEBI-registered adviser and that the rules do not know the reader's goals
   or taxes (action_plan.DISCLAIMER). Keep that sentence on the page.

   MOTION
   The score ring draws, the verdict stamps, the cards are dealt as they
   scroll into view. Rupee amounts are always their real value — only the
   pictures move. Animations fill `backwards` only, and none of it runs with
   reduced motion or the site's data-motion="off". */

(function (root) {
  'use strict';

  var ACT = {
    EXIT:    { label: 'Exit',          tone: 'exit', icon: '✕', what: 'Sell the whole position' },
    TRIM:    { label: 'Trim',          tone: 'trim', icon: '↘', what: 'Sell some' },
    AVERAGE: { label: 'Average down',  tone: 'avg',  icon: '⤓', what: 'Buy more at a lower price' },
    ADD:     { label: 'Add',           tone: 'add',  icon: '↗', what: 'Buy more' },
    HOLD:    { label: 'Hold',          tone: 'hold', icon: '●', what: 'No change' }
  };
  var ORDER = ['EXIT', 'TRIM', 'AVERAGE', 'ADD', 'HOLD'];
  var CONV = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var finite = function (v) { return typeof v === 'number' && isFinite(v); };
  function still() {
    return (root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches) ||
      (root.document && document.documentElement.dataset.motion === 'off');
  }
  function stockLink(sym) {
    return '<a href="stock.html?ticker=' + encodeURIComponent(sym) + '" target="_blank" rel="noopener">' + esc(sym) + '</a>';
  }

  /* ── Drawing ─────────────────────────────────────────────────────────── */

  function hero(plan, report) {
    var score = finite(report.weighted_score) ? report.weighted_score : null;
    var counts = plan.counts || {};
    var chips = ORDER.map(function (a, i) {
      var n = counts[a] || 0;
      return '<button type="button" class="pp-chip t-' + ACT[a].tone + (n ? '' : ' zero') + '" data-pp-filter="' + a +
        '" style="--i:' + i + '"' + (n ? '' : ' disabled') + '><b>' + n + '</b><span>' + esc(ACT[a].label) + '</span></button>';
    }).join('');
    return '<div class="pp-hero">' +
      (score != null
        ? '<div class="pp-ring" role="img" aria-label="' + esc('Portfolio score ' + Math.round(score) + ' out of 100') + '">' +
            '<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="pp-ring-bg" cx="60" cy="60" r="52"></circle>' +
            '<circle class="pp-ring-fg" cx="60" cy="60" r="52" pathLength="100" style="--s:' + Math.max(0, Math.min(100, score)) + '"></circle></svg>' +
            '<div class="pp-ring-mid"><b data-pp-count="' + Math.round(score) + '">' + Math.round(score) + '</b><span>Portfolio score</span></div></div>'
        : '') +
      '<div class="pp-herocopy"><span class="pp-eyebrow">Your action plan</span>' +
        '<h2>' + esc(plan.headline) + '</h2>' +
        (plan.money ? '<p class="pp-money">' + esc(plan.money) + '</p>' : '') +
        '<div class="pp-tally" role="group" aria-label="Calls by kind — tap one to show only those">' + chips + '</div>' +
      '</div></div>';
  }

  function card(a, i) {
    var m = ACT[a.action] || ACT.HOLD;
    var stats = [];
    if (finite(a.score)) stats.push('<span class="pp-stat"><b>' + Math.round(a.score) + '</b>/100 score</span>');
    if (finite(a.weight_pct)) stats.push('<span class="pp-stat"><b>' + a.weight_pct.toFixed(1) + '%</b> of your money</span>');
    if (finite(a.pnl_pct)) stats.push('<span class="pp-stat ' + (a.pnl_pct >= 0 ? 'up' : 'down') + '"><b>' +
      (a.pnl_pct >= 0 ? '+' : '−') + Math.abs(a.pnl_pct).toFixed(1) + '%</b> since you bought</span>');
    var alts = (a.alternatives || []).map(function (x) {
      return '<a class="pp-alt" href="stock.html?ticker=' + encodeURIComponent(x.symbol) + '" target="_blank" rel="noopener">' +
        esc(x.symbol) + ' <b>' + Math.round(x.score) + '</b></a>';
    }).join('');
    return '<article class="pp-card t-' + m.tone + '" data-act="' + esc(a.action) + '" style="--i:' + i + '">' +
      '<header><span class="pp-stamp"><i aria-hidden="true">' + m.icon + '</i>' + esc(m.label) + '</span>' +
        '<span class="pp-conv c-' + esc(a.conviction) + '">' + esc(CONV[a.conviction] || '') + '</span></header>' +
      '<h3>' + stockLink(a.symbol) + (a.name && a.name !== a.symbol ? '<small>' + esc(a.name) + '</small>' : '') + '</h3>' +
      '<p class="pp-todo">' + esc(a.todo) + '</p>' +
      '<p class="pp-why">' + esc(a.why) + '</p>' +
      (stats.length ? '<div class="pp-stats">' + stats.join('') + '</div>' : '') +
      (a.switch ? '<div class="pp-switch"><span class="pp-swap" aria-hidden="true">⇄</span><p>' + esc(a.switch) + '</p>' +
        (alts ? '<div class="pp-alts">' + alts + '</div>' : '') + '</div>' : '') +
      '<details class="pp-more"><summary>Why this call</summary><ul>' +
        (a.reasons || []).map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul></details>' +
    '</article>';
  }

  function rotation(plan) {
    var rows = plan.rotation || [];
    var swaps = [];
    (plan.actions || []).forEach(function (a) {
      (a.alternatives || []).slice(0, 1).forEach(function (x) { swaps.push({ from: a.symbol, to: x }); });
    });
    var body = '';
    if (rows.length) {
      body += '<div class="pp-rots">' + rows.map(function (r, i) {
        var mine = Math.max(0, Math.min(100, r.your_weight_pct || 0)), mkt = Math.max(0, Math.min(100, r.market_weight_pct || 0));
        var scale = Math.max(mine, mkt, 1);
        return '<article class="pp-rot" style="--i:' + i + '">' +
          '<span class="pp-rotup"><i aria-hidden="true">▲</i> ' + esc(r.relative_3m.toFixed(1)) + '% ahead of the Nifty 50 · 3 months</span>' +
          '<h4>' + esc(r.sector) + '</h4>' +
          '<p>' + esc(r.why) + '</p>' +
          '<div class="pp-wbars"><div><span>You</span><i style="--w:' + (100 * mine / scale).toFixed(1) + '%"></i><b>' + mine.toFixed(1) + '%</b></div>' +
            '<div class="mkt"><span>Market</span><i style="--w:' + (100 * mkt / scale).toFixed(1) + '%"></i><b>' + mkt.toFixed(1) + '%</b></div></div>' +
          '<div class="pp-picks"><span>Strongest stocks there</span>' + r.stocks.map(function (s) {
            return '<a class="pp-alt" href="stock.html?ticker=' + encodeURIComponent(s.symbol) + '" target="_blank" rel="noopener">' +
              esc(s.symbol) + ' <b>' + Math.round(s.score) + '</b></a>';
          }).join('') + '</div></article>';
      }).join('') + '</div>';
    }
    if (swaps.length) {
      body += '<div class="pp-swaps"><h4>Stronger companies to consider instead</h4><ul>' +
        swaps.map(function (s) {
          // Only ever the same industry; a report cached before that rule
          // carries no `match` and gets no label rather than a wrong one.
          var kin = s.to.match === 'industry' ? ' · same industry' : '';
          return '<li><span>' + esc(s.from) + '</span><i aria-hidden="true">→</i>' + stockLink(s.to.symbol) +
            ' <small>score ' + Math.round(s.to.score) + kin + '</small></li>';
        }).join('') + '</ul></div>';
    }
    if (!body) {
      body = '<p class="pp-calm">No sector stands out right now: the ones beating the market are ones you already hold ' +
        'in proportion, or have no strongly scored stocks to suggest. Nothing to move for its own sake.</p>';
    }
    return '<section class="pp-where"><h3>Where the money could go</h3>' +
      '<p class="pp-sub">Sectors doing better than the market where you hold less than the market does — and the best-scoring stocks in each.</p>' +
      body + '</section>';
  }

  function render(plan, report) {
    var acts = plan.actions || [];
    var moves = acts.filter(function (a) { return a.action !== 'HOLD'; }).length;
    return '<div class="pp" role="region" aria-label="Your action plan">' +
      hero(plan, report) +
      '<div class="pp-filter" role="group" aria-label="Show">' +
        '<button type="button" class="on" data-pp-filter="ALL">All · ' + acts.length + '</button>' +
        '<button type="button" data-pp-filter="MOVE">Needs a move · ' + moves + '</button>' +
        '<button type="button" data-pp-filter="HOLD">Hold · ' + (acts.length - moves) + '</button>' +
      '</div>' +
      '<div class="pp-cards">' + acts.map(card).join('') + '</div>' +
      rotation(plan) +
      '<details class="pp-how"><summary>How these calls are made — and what they are not</summary>' +
        '<p>' + esc(plan.method) + '</p><p class="pp-disc">' + esc(plan.disclaimer) + '</p></details>' +
    '</div>';
  }

  /* ── Behaviour ───────────────────────────────────────────────────────── */

  function countUp(el) {
    var target = Number(el.getAttribute('data-pp-count'));
    if (!finite(target) || still() || !root.requestAnimationFrame) return;
    var t0 = null, dur = 1100;
    el.textContent = '0';
    function step(t) {
      if (t0 == null) t0 = t;
      var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = String(Math.round(target * e));
      if (k < 1) root.requestAnimationFrame(step); else el.textContent = String(target);
    }
    root.requestAnimationFrame(step);
  }

  function deal(host) {
    var cards = host.querySelectorAll('.pp-card, .pp-rot');
    if (still() || !('IntersectionObserver' in root)) {
      cards.forEach(function (c) { c.classList.add('in'); });
      return;
    }
    // Dealt as they come into view, so the ones below the fold still get
    // their entrance. A card not yet seen is fully visible to anything that
    // reads it — the animation only runs once it is on screen.
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('in');
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    cards.forEach(function (c) { io.observe(c); });
  }

  function filter(host, which) {
    host.querySelectorAll('.pp-filter button').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-pp-filter') === which);
    });
    var shown = 0;
    host.querySelectorAll('.pp-card').forEach(function (c) {
      var a = c.getAttribute('data-act');
      var on = which === 'ALL' || (which === 'MOVE' ? a !== 'HOLD' : a === which);
      c.hidden = !on;
      if (on) {
        c.style.setProperty('--i', String(shown++));
        c.classList.remove('in');
        void c.offsetWidth;
        c.classList.add('in');
      }
    });
  }

  function mount(host, report, opts) {
    if (!host) return false;
    var plan = report && report.action_plan;
    if (!plan || !plan.available || !(plan.actions || []).length) {
      host.hidden = true; host.innerHTML = '';
      return false;
    }
    var same = host.__ppKey === (plan.actions || []).map(function (a) { return a.symbol + a.action; }).join(',');
    host.__ppKey = (plan.actions || []).map(function (a) { return a.symbol + a.action; }).join(',');
    host.innerHTML = render(plan, report);
    host.hidden = false;
    if (!host.__ppWired) {
      host.__ppWired = true;
      host.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-pp-filter]');
        if (b && host.contains(b)) filter(host, b.getAttribute('data-pp-filter'));
      });
    }
    // A staged update of the same plan (prices, then the complete report)
    // redraws without replaying the whole entrance under the reader.
    if (same) {
      host.querySelectorAll('.pp-card, .pp-rot').forEach(function (c) { c.classList.add('in'); });
      host.querySelector('.pp').classList.add('settled');
    } else {
      host.querySelectorAll('[data-pp-count]').forEach(countUp);
      deal(host);
      if (root.AltahaTrack) root.AltahaTrack('portfolio_plan_viewed', { moves: (plan.actions || []).filter(function (a) { return a.action !== 'HOLD'; }).length, holdings: plan.actions.length });
    }
    return true;
  }

  function destroy(host) {
    if (!host) return;
    host.innerHTML = ''; host.hidden = true; host.__ppKey = null;
  }

  root.PortfolioPlan = { mount: mount, destroy: destroy };
  if (typeof module !== 'undefined') module.exports = { render: render, ACT: ACT };
})(typeof window !== 'undefined' ? window : globalThis);
