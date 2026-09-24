/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — lenses.js

   Lenses: named investing philosophies, each applied as a set of rules to
   every company whose statements the site has read. Three views on the
   homepage and one strip on the stock page:

     #research/lenses          every lens as a card, with how many companies
                               meet it
     #research/lenses/<id>     one lens: the idea, its rules, the companies
                               that meet every judged rule, and the near misses
     #research/convergence     companies that meet several lenses at once
     stock.html                "Meets 3 of 10 lenses", with a badge per lens

   WHAT THE PAGE SAYS, AND WHAT IT NEVER SAYS
   The wording is factual and nothing else: a company "meets Gorilla criteria"
   or "passes 3 of 4 rules". Every view carries the notice the API sends with
   the data. A rule that could not be judged is shown as a dash with the
   reason, never as a pass or a fail.

   Everything is read from the nightly run the API caches; nothing is
   computed here except layout.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';
  var NOTICE = 'Lenses are rules-based filters applied to historical financial data. ' +
               'They are not investment advice or recommendations.';
  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  var cache = { index: null, lens: {}, convergence: {} };

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
  function stockHref(sym) { return 'stock.html?ticker=' + encodeURIComponent(sym); }
  function lensHref(id) { return 'index.html#research/lenses/' + encodeURIComponent(id); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  function when(run) {
    if (!run || !run.finished_utc) return '';
    try {
      var d = new Date(run.finished_utc);
      return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) { return ''; }
  }

  function footer() {
    return '<p class="ln-notice" role="note">' + esc(NOTICE) + '</p>';
  }

  function loading(host, what) {
    host.innerHTML = '<div class="ln-state"><span class="ln-spin" aria-hidden="true"></span>' +
      'Loading ' + esc(what) + '…</div>' + footer();
  }

  function failed(host, retry) {
    host.innerHTML = '<div class="ln-state">The lens results could not be loaded. ' +
      'The server may be waking up; this takes about thirty seconds.' +
      '<button type="button" class="ln-btn">Try again</button></div>' + footer();
    var b = host.querySelector('.ln-btn');
    if (b) b.addEventListener('click', retry);
  }

  /* A number that counts up to its value once it scrolls into view. The real
     figure is in the page until then, so a screen reader, a print or anything
     that reads the card before it is on screen never sees a false zero. */
  function countUp(node) {
    var end = Number(node.getAttribute('data-count')) || 0;
    node.textContent = end.toLocaleString('en-IN');
    if (REDUCED || end === 0 || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        io.disconnect();
        var t0 = null, dur = 900 + Math.min(700, end * 4);
        function step(ts) {
          if (t0 === null) t0 = ts;
          var p = Math.min(1, (ts - t0) / dur);
          var eased = 1 - Math.pow(1 - p, 3);
          node.textContent = Math.round(end * eased).toLocaleString('en-IN');
          if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      });
    }, { threshold: 0.4 });
    io.observe(node);
  }

  /* ── The address: #research/lenses[/<id>] ─────────────────────────────── */

  function hashParts() {
    return (location.hash || '').replace(/^#/, '').split('/');
  }
  function lensFromHash() {
    var p = hashParts();
    return (p[1] === 'lenses' && p[2]) ? decodeURIComponent(p[2]) : null;
  }

  /* ── 1 · The index ────────────────────────────────────────────────────── */

  var GLYPH = {
    gorilla:   '<path d="M4 20h16"/><path d="M6 20V10l6-5 6 5v10"/><path d="M10 20v-5h4v5"/>',
    moat:      '<path d="M3 17c3 2 6 2 9 0s6-2 9 0"/><path d="M6 13V6h12v7"/><path d="M10 13V9h4v4"/>',
    tenbagger: '<path d="M4 19 10 13l4 3 6-8"/><path d="M15 8h5v5"/>',
    coffeecan: '<path d="M6 7h11v9a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4Z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M9 3v2M12 3v2M15 3v2"/>',
    qglp:      '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    akre:      '<path d="M5 10h14"/><path d="M7 10l-2 10M12 10v10M17 10l2 10"/><path d="M4 7h16"/>',
    nomad:     '<circle cx="12" cy="12" r="8"/><path d="m15.5 8.5-2 5-5 2 2-5Z"/>',
    cannibal:  '<circle cx="12" cy="12" r="8"/><path d="M12 12 19 8.5M12 12l7 3.5"/>',
    owner:     '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    capcycle:  '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4h-4"/>'
  };
  function glyph(id) {
    return '<span class="ln-glyph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
      (GLYPH[id] || GLYPH.nomad) + '</svg></span>';
  }

  function renderIndex(host, d) {
    var live = d.lenses.filter(function (l) { return l.status === 'live'; }).length;
    var html = '<header class="tabhead ln-head">' +
      '<p class="ln-kicker">Research · Lenses</p>' +
      '<h2>Stocks screened the way great investors think</h2>' +
      '<p>Each lens turns a well-known investing philosophy into rules, and applies them to every ' +
      'NSE company whose filed statements this site has read. A company meets a lens when it ' +
      'passes every rule that could be judged from its filings.</p>' +
      '<p class="ln-meta">' + esc(plural(d.lenses.length, 'lens', 'lenses')) + ' · ' + live + ' live' +
      (d.run ? ' · computed ' + esc(when(d.run)) + ' over ' +
        esc((d.run.companies || 0).toLocaleString('en-IN')) + ' companies' : ' · not yet computed') +
      '</p></header>';

    html += '<div class="ln-grid">';
    d.lenses.forEach(function (l, i) {
      var soon = l.status !== 'live';
      var c = l.counts || {};
      html += '<a class="ln-card' + (soon ? ' is-soon' : '') + '" href="#research/lenses/' +
        encodeURIComponent(l.id) + '" data-lens="' + esc(l.id) + '" style="--i:' + i + '">' +
        '<span class="ln-card-top">' + glyph(l.id) +
          (soon ? '<span class="ln-soon">Coming soon</span>'
                : '<span class="ln-rules">' + plural(l.rules.length, 'rule', 'rules') + '</span>') +
        '</span>' +
        '<span class="ln-orig">' + esc(l.originator) + '</span>' +
        '<span class="ln-name">' + esc(l.name) + '</span>' +
        '<span class="ln-idea">' + esc(l.idea) + '</span>' +
        (soon
          ? '<span class="ln-why">' + esc(l.coming_soon_reason || '') + '</span>'
          : '<span class="ln-count"><b data-count="' + (c.pass || 0) + '">' + (c.pass || 0) + '</b>' +
            '<span>' + ((c.pass || 0) === 1 ? 'company meets it' : 'companies meet it') +
            '<i>' + esc(plural(c.near_miss || 0, 'near miss', 'near misses')) + '</i></span></span>') +
        '</a>';
    });
    html += '</div>';
    html += '<p class="ln-conv-link"><a href="#research/convergence" data-goto="research/convergence">' +
      'Companies that meet three or more lenses →</a></p>';
    html += footer();
    host.innerHTML = html;

    Array.prototype.forEach.call(host.querySelectorAll('.ln-count b'), countUp);
    Array.prototype.forEach.call(host.querySelectorAll('.ln-card'), function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        openLens(a.getAttribute('data-lens'), true);
      });
    });
  }

  function showIndex() {
    var host = $('lenses-body');
    if (!host) return;
    if (cache.index) { renderIndex(host, cache.index); return; }
    loading(host, 'lenses');
    getJSON('/api/lenses').then(function (d) {
      cache.index = d;
      if (!lensFromHash()) renderIndex(host, d);
    }).catch(function () { failed(host, showIndex); });
  }

  /* ── 2 · One lens ─────────────────────────────────────────────────────── */

  var MARK = { pass: '✓', fail: '✗', na: '–' };
  var WORD = { pass: 'Passes', fail: 'Does not pass', na: 'Not judged' };

  function ruleCell(r, i) {
    var res = r.result || 'na';
    var tip = WORD[res] + ': ' + r.label +
      (r.display ? ' · ' + r.display : '') + (r.note ? ' · ' + r.note : '');
    return '<td class="ln-cell is-' + res + '" title="' + esc(tip) + '" aria-label="Rule ' +
      (i + 1) + ': ' + esc(tip) + '"><span>' + MARK[res] + '</span>' +
      (r.display ? '<small>' + esc(r.display) + '</small>' : '') + '</td>';
  }

  function table(rows, rules, caption) {
    if (!rows.length) return '';
    var h = '<div class="ln-tablewrap"><table class="ln-table"><caption class="ln-sr">' +
      esc(caption) + '</caption><thead><tr><th scope="col">Company</th>';
    rules.forEach(function (r, i) {
      h += '<th scope="col" title="' + esc(r.label) + '">R' + (i + 1) + '</th>';
    });
    h += '<th scope="col">Rules passed</th></tr></thead><tbody>';
    rows.forEach(function (s) {
      h += '<tr><th scope="row"><a href="' + stockHref(s.symbol) + '">' +
        '<b>' + esc(s.symbol) + '</b><span>' + esc(s.company || '') + '</span></a>' +
        (s.industry ? '<em>' + esc(s.industry) + '</em>' : '') + '</th>';
      s.rules.forEach(function (r, i) { h += ruleCell(r, i); });
      h += '<td class="ln-score">' + s.passed + ' of ' + s.total +
        (s.na ? '<small>' + s.na + ' not judged</small>' : '') + '</td></tr>';
    });
    return h + '</tbody></table></div>';
  }

  function renderLens(host, d) {
    var l = d.lens, soon = l.status !== 'live', c = d.counts || {};
    var html = '<nav class="ln-back"><a href="#research/lenses">← All lenses</a></nav>' +
      '<header class="ln-hero">' + glyph(l.id) +
      '<p class="ln-kicker">' + esc(l.originator) + '</p>' +
      '<h2>' + esc(l.name) + '</h2>' +
      '<p class="ln-hero-idea">' + esc(l.idea) + '</p></header>';

    html += '<section class="ln-rulebox" aria-label="Rules"><h3>The rules</h3><ol class="ln-rulelist">';
    l.rules.forEach(function (r, i) {
      html += '<li><span class="ln-rn">R' + (i + 1) + '</span>' + esc(r.label) + '</li>';
    });
    html += '</ol><p class="ln-small">A rule that cannot be computed from a company\'s filings ' +
      '(too little history, a line not filed) is not judged. A company is listed only when at least ' +
      Math.round((l.min_coverage || 0.75) * 100) + '% of the rules could be judged.</p></section>';

    if (soon) {
      html += '<div class="ln-soonbox"><b>Coming soon.</b> ' + esc(l.coming_soon_reason || '') +
        '</div>' + footer();
      host.innerHTML = html;
      wireBack(host);
      return;
    }

    var passing = d.passing || [], near = d.near_misses || [];
    html += '<section class="ln-results"><h3>' +
      (passing.length ? plural(passing.length, 'company meets', 'companies meet') + ' ' +
        esc(l.name) + ' criteria' : 'No company meets every judged rule in the latest run') +
      '</h3>' +
      '<p class="ln-small">Hover or tap a mark for the figure behind it. ' +
      (c.insufficient ? esc(plural(c.insufficient, 'company has', 'companies have')) +
        ' too little data to judge. ' : '') +
      (d.run ? 'Computed ' + esc(when(d.run)) + '.' : '') + '</p>' +
      table(passing, l.rules, 'Companies that meet ' + l.name + ' criteria') + '</section>';

    if (near.length) {
      html += '<details class="ln-near"><summary>Near misses <span>' + near.length +
        ' pass all but one judged rule</span></summary>' +
        table(near, l.rules, 'Near misses for ' + l.name) + '</details>';
    }
    html += footer();
    host.innerHTML = html;
    wireBack(host);
  }

  function wireBack(host) {
    var a = host.querySelector('.ln-back a');
    if (a) a.addEventListener('click', function (ev) {
      ev.preventDefault();
      history.pushState(null, '', '#research/lenses');
      showIndex();
      scrollTop();
    });
  }

  function scrollTop() {
    var v = $('view-lenses');
    if (!v || REDUCED) return;
    var chrome = document.querySelector('.sh-chrome');
    var y = v.getBoundingClientRect().top + window.scrollY - ((chrome && chrome.offsetHeight) || 0) - 12;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  }

  function openLens(id, push) {
    var host = $('lenses-body');
    if (!host || !id) return;
    if (push) history.pushState(null, '', '#research/lenses/' + encodeURIComponent(id));
    scrollTop();
    if (cache.lens[id]) { renderLens(host, cache.lens[id]); return; }
    loading(host, 'the lens');
    getJSON('/api/lenses/' + encodeURIComponent(id)).then(function (d) {
      cache.lens[id] = d;
      if (lensFromHash() === id) renderLens(host, d);
    }).catch(function () { failed(host, function () { openLens(id, false); }); });
  }

  function routeLenses() {
    var id = lensFromHash();
    if (id) openLens(id, false); else showIndex();
  }

  /* ── 3 · Convergence ──────────────────────────────────────────────────── */

  var convMin = 3;

  function renderConvergence(host, d) {
    var rows = d.stocks || [];
    var html = '<header class="tabhead ln-head">' +
      '<p class="ln-kicker">Research · Lenses</p>' +
      '<h2>Convergence</h2>' +
      '<p>Companies that meet several lenses at once. Each lens reads the same filings through a ' +
      'different philosophy, so a company that clears several has passed several independent sets ' +
      'of rules.</p></header>' +
      '<div class="ln-convbar" role="group" aria-label="Minimum lenses met">' +
      '<span>Meets at least</span>';
    [2, 3, 4].forEach(function (n) {
      html += '<button type="button" class="ln-chip' + (n === convMin ? ' on' : '') +
        '" data-min="' + n + '" aria-pressed="' + (n === convMin) + '">' + n + ' lenses</button>';
    });
    html += '</div>';
    if (!rows.length) {
      html += '<div class="ln-state">No company meets ' + convMin + ' or more lenses in the latest run.</div>';
    } else {
      html += '<ol class="ln-conv">';
      rows.forEach(function (s, i) {
        html += '<li style="--i:' + Math.min(i, 20) + '"><span class="ln-rank">' + (i + 1) + '</span>' +
          '<a class="ln-conv-co" href="' + stockHref(s.symbol) + '"><b>' + esc(s.symbol) + '</b>' +
          '<span>' + esc(s.company || '') + '</span>' +
          (s.industry ? '<em>' + esc(s.industry) + '</em>' : '') + '</a>' +
          '<span class="ln-conv-n"><b>' + s.passed + '</b> of ' + (d.live_lenses || 0) + ' live lenses</span>' +
          '<span class="ln-badges">' + s.lenses.map(function (l) {
            return '<a class="ln-badge is-pass" href="#research/lenses/' + encodeURIComponent(l.id) +
              '" data-goto-lens="' + esc(l.id) + '">' + esc(l.name) + '</a>';
          }).join('') + '</span></li>';
      });
      html += '</ol>';
    }
    html += footer();
    host.innerHTML = html;

    Array.prototype.forEach.call(host.querySelectorAll('.ln-chip'), function (b) {
      b.addEventListener('click', function () {
        convMin = Number(b.getAttribute('data-min')) || 3;
        showConvergence();
      });
    });
    Array.prototype.forEach.call(host.querySelectorAll('[data-goto-lens]'), function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        var id = a.getAttribute('data-goto-lens');
        if (window.AltahaNav) window.AltahaNav.go('research', 'lenses', true);
        history.replaceState(null, '', '#research/lenses/' + encodeURIComponent(id));
        openLens(id, false);
      });
    });
  }

  function showConvergence() {
    var host = $('convergence-body');
    if (!host) return;
    var key = String(convMin);
    if (cache.convergence[key]) { renderConvergence(host, cache.convergence[key]); return; }
    loading(host, 'convergence');
    getJSON('/api/lenses/convergence?min_lenses=' + convMin).then(function (d) {
      cache.convergence[key] = d;
      renderConvergence(host, d);
    }).catch(function () { failed(host, showConvergence); });
  }

  /* ── 4 · The strip on the stock page ──────────────────────────────────── */

  function mountStrip(host, symbol) {
    if (!host || !symbol) return;
    getJSON('/api/lenses/stock/' + encodeURIComponent(symbol)).then(function (d) {
      if (!d || !d.lenses) return;
      var total = d.lenses.length;
      if (!d.covered) {
        host.innerHTML = '<div class="ln-strip is-empty"><span class="ln-strip-k">Lenses</span>' +
          '<span>Not yet computed for this company: its filed statements have not been read into ' +
          'the fundamentals tables.</span><a href="index.html#research/lenses">About lenses</a></div>';
        host.hidden = false;
        return;
      }
      var badges = d.lenses.map(function (l) {
        var st = l.status !== 'live' ? 'soon' : ((l.result && l.result.status) || 'none');
        var tip = l.status !== 'live' ? l.name + ': coming soon'
          : !l.result ? l.name + ': not computed'
          : st === 'pass' ? 'Meets ' + l.name + ' criteria: passes ' + l.result.passed + ' of ' + l.result.total + ' rules'
          : st === 'near_miss' ? l.name + ': passes ' + l.result.passed + ' of ' + l.result.total + ' rules (near miss)'
          : st === 'insufficient' ? l.name + ': too little data to judge'
          : l.name + ': passes ' + l.result.passed + ' of ' + l.result.total + ' rules';
        return '<a class="ln-badge is-' + st.replace('_', '-') + '" href="' + lensHref(l.id) +
          '" title="' + esc(tip) + '">' + esc(l.name) + '</a>';
      }).join('');
      host.innerHTML = '<div class="ln-strip"><span class="ln-strip-k">Lenses</span>' +
        '<span class="ln-strip-n">Meets <b>' + d.meets + '</b> of ' + total + ' lenses</span>' +
        '<span class="ln-badges">' + badges + '</span>' +
        '<p class="ln-strip-note">' + esc(NOTICE) + '</p></div>';
      host.hidden = false;
    }).catch(function () { host.hidden = true; });
  }

  /* ── Wiring ───────────────────────────────────────────────────────────── */

  function onNavigate(tab) {
    if (tab === 'lenses') routeLenses();
    else if (tab === 'convergence') showConvergence();
  }

  window.addEventListener('altaha:navigate', function (ev) {
    onNavigate(ev && ev.detail && ev.detail.tab);
  });
  window.addEventListener('hashchange', function () {
    var p = hashParts();
    if (p[1] === 'lenses') routeLenses();
  });

  function boot() {
    var tl = $('tab-lenses'), tc = $('tab-convergence');
    if (tl) tl.addEventListener('click', function () { setTimeout(routeLenses, 0); });
    if (tc) tc.addEventListener('click', function () { setTimeout(showConvergence, 0); });
    var v = $('view-lenses');
    if (v && v.style.display !== 'none') routeLenses();
    var strip = $('stk-lenses');
    if (strip) {
      var sym = '';
      try { sym = new URLSearchParams(location.search).get('ticker') || ''; } catch (e) {}
      mountStrip(strip, sym.trim().toUpperCase().replace(/\.(NS|BO)$/, ''));
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.AltahaLenses = { open: openLens, index: showIndex, convergence: showConvergence,
                          strip: mountStrip };
})();
