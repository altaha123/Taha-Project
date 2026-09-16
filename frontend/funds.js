/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — funds.js

   Fund house portfolios, from the monthly disclosures SEBI requires.

   HOW THIS DIFFERS FROM THE INVESTOR VIEW, AND WHY THAT MATTERS ON SCREEN
   The two pages look alike and are built on opposite kinds of data. The
   investor side reads quarterly shareholding filings, which name a holder only
   above 1% — so those portfolios are a floor. This side reads a fund's own
   monthly portfolio statement, which is COMPLETE: every position, however
   small, with an ISIN on each row. A reader moving between the two will carry
   assumptions from one to the other, so each page states its own limits in its
   own words rather than sharing a single vague disclaimer.

   THE ONE THING THIS PAGE MUST NOT IMPLY
   That it covers the industry. AMFI lists 53 fund houses and publishes a
   directory, not a feed; each pack comes from that AMC's own website and many
   build their download list in JavaScript. The count read is printed at the
   top of the list, and a fund house that is absent is absent because it has
   not been READ — never because it holds nothing.

   PERCENTAGES ARE NOT ADDED
   A company held by twenty-two schemes has twenty-two weights, each a share of
   a different portfolio. Adding them produces a number that means nothing, so
   the headline is the rupee value across the house and the scheme weights sit
   underneath, unsummed.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var loaded = false;
  var directory = null;

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
    if (n >= 1) return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 }) + ' cr';
    return '₹' + (n * 100).toFixed(1) + ' lakh';
  }
  function pct(v) {
    var n = Number(v);
    return isFinite(n) ? n.toFixed(2) + '%' : '—';
  }
  function monthName(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso + 'T00:00:00');
      return d.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
    } catch (e) { return String(iso); }
  }

  /* ── The directory ─────────────────────────────────────────────────────── */

  function paintDirectory(d) {
    var box = $('funds-body');
    if (!box) return;
    if (!d || !d.available || !(d.funds || []).length) {
      box.innerHTML = '<div class="iv-empty">' +
        esc((d && d.message) ||
            'No fund house portfolio has been read yet. The monthly packs are ' +
            'fetched one asset manager at a time.') + '</div>';
      return;
    }
    var cards = d.funds.map(function (f) {
      return '<button type="button" class="iv-card" data-id="' + esc(f.amc_id) + '">' +
        '<b>' + esc(f.amc_name || f.amc_id) + '</b>' +
        '<span class="iv-kind">' + esc(String(f.schemes || 0)) + ' schemes</span>' +
        '<span class="iv-about">' + esc(String(f.rows || 0)) +
          ' disclosed positions</span>' +
        '</button>';
    }).join('');

    box.innerHTML =
      '<p class="iv-lead">Every position each scheme held at the end of ' +
      esc(monthName(d.month)) + ', from the asset manager&rsquo;s own monthly ' +
      'disclosure. No 1% floor &mdash; this is the whole book.</p>' +
      /* Coverage, stated plainly. This is the sentence that keeps the page
         from implying it covers the industry. */
      '<p class="iv-cover"><b>' + esc(String(d.read)) + '</b> of the ' +
      esc(String(d.listed_with_amfi)) + ' fund houses AMFI lists have been read ' +
      'for this month. ' + esc(d.note || '') + ' A fund house not shown here ' +
      'has not been read &mdash; it does not mean it holds nothing.</p>' +
      '<div class="iv-grid">' + cards + '</div>' +
      (d.lag ? '<p class="iv-cover">' + esc(d.lag) + '</p>' : '');

    box.querySelectorAll('.iv-card').forEach(function (b) {
      b.addEventListener('click', function () { open(b.getAttribute('data-id')); });
    });
  }

  /* ── One fund house ────────────────────────────────────────────────────── */

  function schemeList(schemes) {
    if (!schemes || schemes.length < 1) return '';
    return '<ul class="iv-parts">' + schemes.map(function (s) {
      return '<li>' +
        '<span class="nm">' + esc(s.scheme) + '</span>' +
        '<span class="rel">' + esc(cr((s.value_lakh || 0) / 100)) + '</span>' +
        '<span class="vv">' + pct(s.pct_nav) + '</span>' +
        '</li>';
    }).join('') + '</ul>';
  }

  function positionRow(p) {
    var many = p.scheme_count > 1;
    return '<li class="iv-pos">' +
      '<div class="iv-pos-head">' +
        (p.symbol
          ? '<a class="sym" href="stock.html?ticker=' +
            encodeURIComponent(p.symbol) + '">' + esc(p.symbol) + '</a>'
          : '<span class="sym">' + esc(p.isin) + '</span>') +
        '<span class="fu-co">' + esc(p.name) + '</span>' +
        '<span class="vv">' + esc(cr(p.value_cr)) + '</span>' +
        '<span class="mv">' + esc(String(p.scheme_count)) + ' scheme' +
          (many ? 's' : '') +
          (p.industry ? ' · ' + esc(p.industry) : '') + '</span>' +
      '</div>' +
      /* Scheme weights, never summed — each is a share of a different
         portfolio and adding them would produce a meaningless number. */
      (many ? schemeList(p.schemes.slice(0, 8)) : schemeList(p.schemes)) +
      '</li>';
  }

  function paintFund(d) {
    var box = $('funds-body');
    if (!box) return;
    var back = '<button type="button" class="iv-back" id="fund-back">' +
      '&larr; All fund houses</button>';

    if (!d || !d.available) {
      box.innerHTML = back + '<div class="iv-empty">' +
        esc((d && d.message) || 'Nothing could be read for this fund house.') +
        '</div>';
      wireBack();
      return;
    }

    var head =
      '<h3 class="iv-name">' + esc(d.name || d.amc_id) + '</h3>' +
      '<p class="iv-asof">Portfolio as at <b>' + esc(monthName(d.month)) +
        '</b> &mdash; ' + esc(String(d.count)) + ' listed compan' +
        (d.count === 1 ? 'y' : 'ies') + ' across ' +
        esc(String(d.schemes || 0)) + ' schemes. Disclosed monthly and due by ' +
        'the tenth of the following month, so this can be about six weeks old.' +
        (d.source ? ' <a href="' + esc(d.source) + '" target="_blank" ' +
          'rel="noopener">The pack it came from</a>.' : '') +
      '</p>';

    var list = d.positions.length
      ? '<ul class="iv-list">' + d.positions.map(positionRow).join('') + '</ul>'
      : '<div class="iv-empty">No listed equity in this pack.</div>';

    /* Shown rather than dropped, so the weights on screen reconcile against
       the fund's real book. */
    var other = (d.not_on_nse || []).length
      ? '<h4 class="iv-h4">Not on NSE&rsquo;s equity list</h4>' +
        '<p class="iv-sub">Held, and carried in the pack, but not matched to a ' +
        'listed NSE company &mdash; another fund&rsquo;s units, an unlisted ' +
        'holding, or something quoted only on BSE. Listed here rather than ' +
        'dropped so the figures above can be reconciled against the ' +
        'fund&rsquo;s real portfolio.</p>' +
        '<ul class="iv-list is-gone">' +
          d.not_on_nse.map(function (p) {
            return '<li class="iv-pos"><div class="iv-pos-head">' +
              '<span class="sym">' + esc(p.isin) + '</span>' +
              '<span class="fu-co">' + esc(p.name) + '</span>' +
              '<span class="vv was">' + esc(cr(p.value_cr)) + '</span>' +
              '</div></li>';
          }).join('') + '</ul>'
      : '';

    var notes = (d.notes || []).length
      ? '<div class="iv-notes">' + d.notes.map(function (n) {
          return '<p>' + esc(n) + '</p>';
        }).join('') + '</div>'
      : '';

    box.innerHTML = back + head + list + other + notes;
    wireBack();
  }

  function wireBack() {
    var b = $('fund-back');
    if (b) b.addEventListener('click', function () { paintDirectory(directory); });
  }

  /* ── Loading ───────────────────────────────────────────────────────────── */

  function busy(msg) {
    var box = $('funds-body');
    if (box) {
      box.innerHTML = '<div class="iv-empty is-loading" aria-busy="true">' +
        esc(msg) + '</div>';
    }
  }

  function fail() {
    var box = $('funds-body');
    if (box) {
      box.innerHTML = '<div class="iv-empty">The engine is unreachable. ' +
        'If it has been idle it takes about thirty seconds to wake — try again.</div>';
    }
  }

  function open(id) {
    busy('Reading the monthly portfolio…');
    fetch(API + '/fund?amc=' + encodeURIComponent(id))
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paintFund)
      .catch(fail);
  }

  function load() {
    busy('Loading the fund houses…');
    fetch(API + '/funds')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function (d) { directory = d; paintDirectory(d); })
      .catch(fail);
  }

  function watch() {
    var view = $('view-funds');
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
