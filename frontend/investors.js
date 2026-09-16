/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — investors.js

   Investor portfolios, assembled by inverting the shareholding filings.

   THE THING THIS VIEW MUST NEVER LET A READER BELIEVE
   That it is showing a portfolio. It is showing the part of one that crossed
   1% of a company's equity, as at a quarter end up to four months ago. A
   ₹400 crore position in a large cap sits below that line and does not appear
   at all. So the floor and the lag are on the page itself — in the header of
   every portfolio, not folded away in a footnote — because a reader who takes
   this for a live holdings list has been misled even though every number on
   it is correct.

   WHY EVERY TOTAL COMES APART
   "Vijay Kedia holds 20.91% of Atul Auto" is 18.20% in his own name plus
   2.71% through Kedia Securities. "Rekha Jhunjhunwala holds 14.37% of Metro
   Brands" is three family trusts of which she is trustee — which is not the
   same as owning the shares, and a reader may reasonably think it should not
   be added up at all. So the constituents are rendered under every rolled-up
   position with what each one is. A total you cannot take apart is an
   assertion; one you can is evidence.

   WHAT IS NOT CLAIMED
   A company dropping off the list is labelled "no longer disclosed", never
   "sold" — below 1% the filing simply stops naming a holder, and it does not
   say which happened. A promoter stake is labelled as one, because an
   investor's own company is not a stock pick. No target, no entry, no
   instruction.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var loaded = false;
  var directory = null;
  var current = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function pct(v, dp) {
    var n = Number(v);
    return isFinite(n) ? n.toFixed(dp == null ? 2 : dp) + '%' : '—';
  }

  var RELATION_TAG = {
    self: 'own name',
    family: 'family',
    entity: 'their company',
    trust: 'family trust',
    joint: 'held jointly'
  };

  var CHANGE_WORD = {
    added: 'added', trimmed: 'trimmed', held: 'unchanged',
    'new': 'new this quarter', unknown: ''
  };

  /* ── The directory ─────────────────────────────────────────────────────── */

  function paintDirectory(d) {
    var box = $('investors-body');
    if (!box) return;
    if (!d || !d.available || !(d.investors || []).length) {
      box.innerHTML = '<div class="iv-empty">' +
        esc((d && d.message) || 'The investor list could not be read.') + '</div>';
      return;
    }
    var led = d.ledger || {};
    var cards = d.investors.map(function (i) {
      return '<button type="button" class="iv-card" data-id="' + esc(i.id) + '">' +
        '<b>' + esc(i.name) + '</b>' +
        '<span class="iv-kind">' + esc(i.kind === 'fund' ? 'fund' : 'individual') + '</span>' +
        '<span class="iv-about">' + esc(i.about || '') + '</span>' +
        '</button>';
    }).join('');

    /* The coverage line is not decoration. A portfolio assembled from 300
       companies out of 2,000 is a sample, and saying which is the difference
       between a floor and a claim. */
    var cover = '';
    if (led.companies_read != null) {
      cover = '<p class="iv-cover">Built from <b>' + esc(String(led.companies_read)) +
        '</b> companies read so far' +
        (led.latest_period ? ', to ' + esc(led.latest_period) : '') +
        '. The ledger is filled one company at a time, so an investor may hold ' +
        'something in a company that has not been read yet.' +
        (led.persistent === false
          ? ' <b>This instance is not storing the ledger between restarts.</b>'
          : '') +
        '</p>';
    }

    box.innerHTML =
      '<p class="iv-lead">Taken from each company&rsquo;s own shareholding filing. ' +
      'Only stakes above 1% are named in those filings, and they are quarterly ' +
      '&mdash; so every portfolio here is the disclosed floor of what someone ' +
      'holds, as at a quarter end, not a live position.</p>' +
      cover +
      '<div class="iv-grid">' + cards + '</div>';

    box.querySelectorAll('.iv-card').forEach(function (b) {
      b.addEventListener('click', function () { open(b.getAttribute('data-id')); });
    });
  }

  /* ── One portfolio ─────────────────────────────────────────────────────── */

  function partsList(parts, cls) {
    if (!parts || !parts.length) return '';
    return '<ul class="iv-parts' + (cls ? ' ' + cls : '') + '">' +
      parts.map(function (p) {
        return '<li>' +
          '<span class="nm">' + esc(p.name) + '</span>' +
          '<span class="rel">' + esc(RELATION_TAG[p.relation] || p.relation) + '</span>' +
          '<span class="vv">' + pct(p.pct) + '</span>' +
          '</li>';
      }).join('') + '</ul>';
  }

  function positionRow(p) {
    var ch = p.change || {};
    var tone = ch.kind === 'added' || ch.kind === 'new' ? 'up'
             : (ch.kind === 'trimmed' ? 'dn' : '');
    var move = CHANGE_WORD[ch.kind] || '';
    if (ch.delta != null && (ch.kind === 'added' || ch.kind === 'trimmed')) {
      move += ' ' + (ch.delta > 0 ? '+' : '') + Number(ch.delta).toFixed(2) + ' pp';
    }
    return '<li class="iv-pos">' +
      '<div class="iv-pos-head">' +
        '<a class="sym" href="stock.html?ticker=' + encodeURIComponent(p.symbol) +
          '">' + esc(p.symbol) + '</a>' +
        (p.promoter
          ? '<span class="iv-flag" title="The investor is a promoter of this ' +
            'company. Their own business, not a position taken in someone ' +
            'else&rsquo;s.">promoter stake</span>' : '') +
        '<span class="vv">' + pct(p.pct) + '</span>' +
        (move ? '<span class="mv ' + tone + '">' + esc(move) + '</span>' : '') +
      '</div>' +
      /* The breakdown, whenever the headline is a sum of more than one row.
         This is the part that keeps the total honest. */
      (p.split ? partsList(p.parts) : '') +
      (p.beside && p.beside.length
        ? '<p class="iv-beside">Also on this register, not added to the total ' +
          'because the filing does not say how it divides:</p>' +
          partsList(p.beside, 'is-beside')
        : '') +
      '</li>';
  }

  function paintPortfolio(d) {
    var box = $('investors-body');
    if (!box) return;

    var back = '<button type="button" class="iv-back" id="iv-back">' +
      '&larr; All investors</button>';

    if (!d || !d.available) {
      box.innerHTML = back +
        '<h3 class="iv-name">' + esc((d && d.name) || 'Not found') + '</h3>' +
        '<div class="iv-empty">' + esc((d && d.message) ||
          'Nothing could be read for this investor.') + '</div>' +
        (d && d.entities && d.entities.length
          ? '<p class="iv-looking">Names being looked for: ' +
            d.entities.map(function (e) { return '<b>' + esc(e.alias) + '</b>'; })
              .join(', ') + '.</p>'
          : '');
      wireBack();
      return;
    }

    /* A redirect is a statement of fact and gets said before anything else. */
    var redirect = d.redirected_from
      ? '<p class="iv-redirect">You asked for <b>' + esc(d.redirected_from.name) +
        '</b>. ' + esc(d.redirected_from.about || '') + '</p>'
      : '';

    var counted = d.positions.length;
    var head =
      '<h3 class="iv-name">' + esc(d.name) + '</h3>' +
      '<p class="iv-about">' + esc(d.about || '') + '</p>' +
      redirect +
      '<p class="iv-asof"><b>' + esc(d.period || '') + '</b> filings &mdash; ' +
        esc(String(counted)) + ' disclosed holding' + (counted === 1 ? '' : 's') +
        (d.compared_with ? ', compared with ' + esc(d.compared_with) : '') +
        '. Stakes below 1% of a company are not named in its filing and do not ' +
        'appear here.</p>';

    var list = d.positions.length
      ? '<ul class="iv-list">' + d.positions.map(positionRow).join('') + '</ul>'
      : '<div class="iv-empty">No disclosed holdings in this quarter.</div>';

    var gone = (d.no_longer_disclosed || []).length
      ? '<h4 class="iv-h4">No longer disclosed</h4>' +
        '<p class="iv-sub">Named in ' + esc(d.compared_with || 'the previous quarter') +
        ' and not in ' + esc(d.period) + '. The stake has fallen below the 1% ' +
        'threshold or been sold &mdash; the filing does not say which.</p>' +
        '<ul class="iv-list is-gone">' +
          d.no_longer_disclosed.map(function (x) {
            return '<li class="iv-pos"><div class="iv-pos-head">' +
              '<a class="sym" href="stock.html?ticker=' +
                encodeURIComponent(x.symbol) + '">' + esc(x.symbol) + '</a>' +
              '<span class="vv was">was ' + pct(x.was_pct) + '</span>' +
              '</div></li>';
          }).join('') + '</ul>'
      : '';

    var who = (d.entities || []).length
      ? '<h4 class="iv-h4">Names counted as ' + esc(d.name) + '</h4>' +
        '<ul class="iv-who">' + d.entities.map(function (e) {
          return '<li><b>' + esc(e.alias) + '</b> &mdash; ' +
            esc(e.relation_word || e.relation) + '</li>';
        }).join('') + '</ul>'
      : '';

    var notes = (d.notes || []).length
      ? '<div class="iv-notes">' + d.notes.map(function (n) {
          return '<p>' + esc(n) + '</p>';
        }).join('') + '</div>'
      : '';

    box.innerHTML = back + head + list + gone + who + notes;
    wireBack();
  }

  function wireBack() {
    var b = $('iv-back');
    if (b) b.addEventListener('click', function () { paintDirectory(directory); });
  }

  /* ── Loading ───────────────────────────────────────────────────────────── */

  function busy(msg) {
    var box = $('investors-body');
    if (box) {
      box.innerHTML = '<div class="iv-empty is-loading" aria-busy="true">' +
        esc(msg) + '</div>';
    }
  }

  function open(id) {
    current = id;
    busy('Reading the filings…');
    fetch(API + '/investor?id=' + encodeURIComponent(id))
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paintPortfolio)
      .catch(function () { fail(); });
  }

  function fail() {
    var box = $('investors-body');
    if (box) {
      box.innerHTML = '<div class="iv-empty">The engine is unreachable. ' +
        'If it has been idle it takes about thirty seconds to wake — try again.</div>';
    }
  }

  function load() {
    busy('Loading the investor list…');
    fetch(API + '/investors')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function (d) { directory = d; paintDirectory(d); })
      .catch(function () { fail(); });
  }

  /* Loaded when the tab is first opened, never on page load. */
  function watch() {
    var view = $('view-investors');
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
