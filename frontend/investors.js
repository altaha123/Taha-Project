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

  /* ── The picture beside a name ─────────────────────────────────────────────
     Two initials, with a picture laid over them where investor-pictures.js
     holds one. A picture that does not load removes itself and the initials
     are what is left, so no card ever shows a broken image. What may be a
     picture, and why most names have none, is in that file. */

  function picture(id) {
    var all = window.AltahaInvestorPictures || {};
    return Object.prototype.hasOwnProperty.call(all, id) ? all[id] : null;
  }

  function initials(name) {
    var w = String(name || '').replace(/[^A-Za-zÀ-ɏ ]/g, ' ').trim()
      .split(/\s+/).filter(Boolean);
    if (!w.length) return '?';
    return (w[0][0] + (w.length > 1 ? w[w.length - 1][0] : (w[0][1] || ''))).toUpperCase();
  }

  /* `i` is anything with an id, a name and a kind: a directory row or a
     portfolio. A company is a rounded square and a person a circle, picture
     or not, so the two read differently before a single one has a picture. */
  function avatar(i, cls) {
    var pic = picture(i.id);
    return '<span class="iv-av' + (i.kind === 'fund' ? ' is-org' : '') +
      (pic && pic.kind === 'logo' ? ' is-logo' : '') + (cls ? ' ' + cls : '') +
      '" aria-hidden="true"><i>' + esc(initials(i.name)) + '</i>' +
      (pic && pic.src
        ? '<img loading="lazy" decoding="async" alt="" src="' + esc(pic.src) +
          '" onerror="this.remove()">'
        : '') +
      '</span>';
  }

  /* A free licence asks for the author, the licence and what was changed to
     be named where the picture is shown. This is that, not a courtesy. */
  function linked(text, href) {
    return href
      ? '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + esc(text) + '</a>'
      : esc(text);
  }
  function credit(pic) {
    if (!pic || pic.kind !== 'photo' || !pic.credit) return '';
    return linked(pic.credit, pic.source) +
      (pic.license ? ', ' + linked(pic.license, pic.license_url) : '') +
      (pic.changes ? ', ' + esc(pic.changes) : '');
  }

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
    /* The holding count goes on the card. Clicking a name and landing on an
       empty page reads as a broken feature; the same emptiness, labelled
       before the click, reads as a ledger still being filled. */
    var cards = d.investors.map(function (i) {
      var n = i.positions;
      var tag = n == null
        ? (i.kind === 'fund' ? 'fund' : 'individual')
        : (n > 0 ? n + ' holding' + (n === 1 ? '' : 's') : 'none found yet');
      return '<button type="button" class="iv-card has-av' +
        (n === 0 ? ' is-empty' : '') + '" data-id="' + esc(i.id) + '">' +
        avatar(i) +
        '<span class="iv-card-t">' +
        '<b>' + esc(i.name) + '</b>' +
        '<span class="iv-kind">' + esc(tag) + '</span>' +
        '<span class="iv-about">' + esc(i.about || '') + '</span>' +
        '</span>' +
        '</button>';
    }).join('');

    var credits = d.investors.map(function (i) {
      var c = credit(picture(i.id));
      return c ? esc(i.name) + ' by ' + c : '';
    }).filter(Boolean);

    /* One line: the 1% floor, the quarterly cadence, and how much of the
       exchange the ledger has read. A portfolio built from 300 companies out
       of 2,000 is a sample, and the count is what says so. Never started and
       part-way through are not the same situation, so "0 read" is not shown
       for a collector that has not run. */
    var read = '';
    if (led.companies_read != null) {
      read = !led.companies_read && led.attempted === 0
        ? ' · <b>nothing read yet</b>'
        : ' · <b>' + esc(String(led.companies_read)) +
          (led.universe ? ' of ' + esc(String(led.universe)) : '') +
          '</b> companies read so far';
    }
    var cover = '<p class="iv-cover">Stakes above 1%, from quarterly filings' +
      (led.latest_period ? ', to ' + esc(led.latest_period) : '') + read +
      (led.persistent === false ? ' · <b>not stored between restarts</b>' : '') +
      '</p>';

    box.innerHTML =
      cover +
      '<div class="iv-grid">' + cards + '</div>' +
      (credits.length
        ? '<p class="iv-credit">Photographs: ' + credits.join('; ') + '.</p>'
        : '');

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

  /* Who this page is about: the picture, the name, the line about them, and
     whose photograph it is. The same on a full portfolio and an empty one. */
  function whoHead(d) {
    var named = d && d.name;
    var by = named ? credit(picture(d.id)) : '';
    return '<div class="iv-who-head">' +
      (named ? avatar(d, 'lg') : '') +
      '<div>' +
        '<h3 class="iv-name">' + esc(named || 'Not found') + '</h3>' +
        ((d && d.about) ? '<p class="iv-about">' + esc(d.about) + '</p>' : '') +
      '</div></div>' +
      (by ? '<p class="iv-credit">Photograph by ' + by + '.</p>' : '');
  }

  function paintPortfolio(d) {
    var box = $('investors-body');
    if (!box) return;

    var back = '<button type="button" class="iv-back" id="iv-back">' +
      '&larr; All investors</button>';

    if (!d || !d.available) {
      /* An empty portfolio is a statement about the LEDGER, not about the
         investor, and the page has to say which. Without the coverage line a
         reader concludes the person holds nothing. */
      var cov = d && d.coverage;
      box.innerHTML = back +
        whoHead(d) +
        '<div class="iv-empty">' + esc((d && d.message) ||
          'Nothing could be read for this investor.') + '</div>' +
        (cov && cov.companies_read != null
          ? '<p class="iv-cover"><b>' + esc(String(cov.companies_read)) +
            '</b> companies read so far' +
            (cov.latest_period ? ', to ' + esc(cov.latest_period) : '') +
            ' · fills in nightly</p>'
          : '') +
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
      whoHead(d) +
      redirect +
      '<p class="iv-asof"><b>' + esc(d.period || '') + '</b> · ' +
        esc(String(counted)) + ' disclosed holding' + (counted === 1 ? '' : 's') +
        (d.compared_with ? ', compared with ' + esc(d.compared_with) : '') +
        ' · stakes below 1% are not filed</p>';

    var list = d.positions.length
      ? '<ul class="iv-list">' + d.positions.map(positionRow).join('') + '</ul>'
      : '<div class="iv-empty">No disclosed holdings in this quarter.</div>';

    var gone = (d.no_longer_disclosed || []).length
      ? '<h4 class="iv-h4">No longer disclosed</h4>' +
        '<p class="iv-sub">Fell below 1% or was sold; the filing does not say which.</p>' +
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
          return '<li><b>' + esc(e.alias) + '</b>, ' +
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
      // data-nosnippet: not to be quoted by a search engine as the page.
      box.innerHTML = '<div class="iv-empty" data-nosnippet>The engine is unreachable. ' +
        'If it has been idle it takes about thirty seconds to wake. Try again.</div>';
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

  /* Called by the admin panel when a sweep finishes, so the cards fill in
     rather than sitting stale behind a panel that just said it read 2,000
     companies. */
  window.AltahaLedgerDone = function () {
    if (loaded) load();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }
})();
