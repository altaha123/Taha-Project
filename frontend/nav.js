/* Altaha — Navigation

   FOUR PRODUCTS, FOUR QUESTIONS
   The site used to be one screener with eleven tabs hanging off it, which told
   a first-time reader that everything mattered equally, so nothing did. The
   primary navigation now names four products, and each one exists to answer a
   single question a person actually arrives with:

     Discover   Where are opportunities now?
     Allocate   What should I do with my money?
     Portfolio  How are my existing investments doing?
     Research   What does the evidence say about this company?

   A destination belongs to the product whose question it answers. The live
   scanner and the deals board are Discover because they are about now; the
   planner is Allocate because it is about the next rupee; the screener,
   the score and the factor evidence are Research because they are about
   what is true, not what to do about it.

   SUB-TABS ARE THE PRODUCT, EXTRAS ARE THE LONG TAIL
   Each section carries a short `tabs` list — what belongs in the visible row
   under the product name — and an `extras` list of destinations that are
   owned by the section and fully routable but do not deserve a slot in the
   row. The mega menu in shell.js shows both. This is what stops the Research
   row from becoming the old eleven-tab bar with a new name on it.

   OLD ADDRESSES STILL RESOLVE
   Bookmarks, share links and the browser tests all carry the old section ids
   (#screener, #ideas, #social, #planner). ALIASES maps every one of them onto
   its new home, and a tab id always wins over the section id it arrived with,
   so AltahaNav.go('screener', 'filings') lands on Research → News whether or
   not the caller knows Research exists.

   shell.js provides the visible header; this module owns routing and
   fallback navigation. Section and tab identifiers stay stable.
*/

(function () {
  'use strict';

  var SECTIONS = [
    {
      id: 'discover', label: 'Discover',
      question: 'Where are opportunities now?',
      blurb: 'Where are opportunities now? — today’s setups, live alerts and unusual activity',
      icon: '<circle cx="12" cy="12" r="9"/><path d="m15.6 8.4-2.3 5-5 2.2 2.3-5Z"/>',
      tabs: [
        { id: 'ideas', label: 'Universe Scan', hint: 'Explore the NSE universe and reveal ranked stocks' },
        { id: 'live', label: 'Alerts', hint: 'Intraday alerts as they fire' },
        { id: 'tracker', label: 'Tracker', hint: 'Follow discovered stocks and their performance' },
        { id: 'discover', label: 'Opportunities now', hint: 'Today’s setups, movers and unusual activity' },
        { id: 'special',  label: 'Delivery trends',   hint: 'Price momentum backed by delivered volume' },
        { id: 'deals',    label: 'Bulk & block deals', hint: 'Large trades and their participants' },
        { id: 'wow',      label: 'WOW orders',        hint: 'Order wins measured against company size' }
      ],
      extras: [
        { id: 'options',  label: 'Options activity',  hint: 'Option prices and open interest' }
      ]
    },
    {
      id: 'allocate', label: 'Allocate',
      question: 'What should I do with my money?',
      blurb: 'What should I do with my money? — the order to put it to work in, and how much of it',
      icon: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/><path d="M12 12 5.6 18.4"/>',
      tabs: [
        { id: 'allocate', label: 'Allocation plan', hint: 'What the next rupee should do, in order' },
        { id: 'planner',  label: 'Money planner',   hint: 'Income, expenses, tax and the cushion', brand: 'planner' }
      ],
      extras: []
    },
    {
      id: 'portfolio', label: 'Portfolio',
      question: 'How are my existing investments doing?',
      blurb: 'How are my existing investments doing? — holdings, exposures and the record of your picks',
      icon: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
      tabs: [
        { id: 'portfolio', label: 'Holdings review', hint: 'Your holdings against their scores and exposures' }
      ],
      extras: []
    },
    {
      id: 'research', label: 'Research',
      question: 'What does the evidence say?',
      blurb: 'The evidence — screener, scores, fundamentals, ownership, technicals and news',
      icon: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
      tabs: [
        { id: 'screener',  label: 'Stock analysis',  hint: 'One company, scored, with the ledger' },
        { id: 'score',     label: 'Altaha Score',    hint: 'How the score is built and what it has been worth' },
        { id: 'factors',   label: 'Factors',         hint: 'What each factor has actually predicted' },
        { id: 'results',   label: 'Fundamentals',    hint: 'Quarterly numbers and the year-ago comparison' },
        { id: 'investors', label: 'Ownership',       hint: 'What well-known investors disclosed holding' },
        { id: 'charts',    label: 'Technicals',      hint: 'Price charts, levels and indicators' },
        { id: 'filings',   label: 'News',            hint: 'Company announcements as they are filed' }
      ],
      extras: [
        { id: 'funds',    label: 'Fund house portfolios', hint: 'What the mutual funds disclosed holding' },
        { id: 'concalls', label: 'Concall summaries',     hint: 'Earnings call transcripts, digested' },
        { id: 'social',   label: 'News & post drafts',    hint: 'Read updates and prepare posts' },
        { id: 'vocab',    label: 'Glossary',              hint: 'Financial terms in plain language' }
      ]
    }
  ];

  /* Every section id this site has ever put in a URL, pointed at the product
     that now owns it. A hash is a promise; breaking one silently is how a
     shared link turns into a bounce. */
  var ALIASES = {
    screener: 'research',
    stocks:   'research',
    ideas:    'discover',
    social:   'research',
    planner:  'allocate',
    news:     'research'
  };

  var reduced = false;
  try {
    reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (e) {}

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $id(id) { return document.getElementById(id); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined) n.textContent = txt;
    return n;
  }

  /* The first screen stays what it has always been: the search box, the
     market board and the day's movers, which is Research → Stock analysis
     under the new names. Discover is a place you choose to go, not a wall
     put in front of somebody who arrived to look up one company. */
  var HOME = { section: 'research', tab: 'screener' };
  var current = { section: HOME.section, tab: HOME.tab };
  var booting = true;

  function allTabs(s) {
    return s.tabs.concat(s.extras || []);
  }

  function rawSection(id) {
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === id) return SECTIONS[i];
    }
    return null;
  }

  function sectionById(id) {
    return rawSection(id) || rawSection(ALIASES[id]) || SECTIONS[0];
  }

  function ownerOf(tabId) {
    for (var i = 0; i < SECTIONS.length; i++) {
      var t = allTabs(SECTIONS[i]);
      for (var j = 0; j < t.length; j++) {
        if (t[j].id === tabId) return SECTIONS[i];
      }
    }
    return null;
  }

  function tabById(section, tabId) {
    var t = allTabs(section);
    for (var i = 0; i < t.length; i++) {
      if (t[i].id === tabId) return t[i];
    }
    return null;
  }

  function queryChartsSymbol() {
    try {
      var q = new URLSearchParams(location.search).get('charts');
      return q;
    } catch (e) {
      return null;
    }
  }

  function clickLegacy(tabId, tries) {
    var btn = $id('tab-' + tabId);
    if (btn) {
      btn.click();
      return;
    }
    if ((tries || 0) >= 25) return;
    setTimeout(function () { clickLegacy(tabId, (tries || 0) + 1); }, 200);
  }

  function build() {
    var oldNav = $('.tabnav');
    if (!oldNav) return false;

    oldNav.setAttribute('aria-hidden', 'true');
    oldNav.classList.add('legacy-nav');

    var wrap = el('div', 'navwrap');

    var primary = el('nav', 'navmain');
    primary.setAttribute('role', 'tablist');
    primary.setAttribute('aria-label', 'Products');

    SECTIONS.forEach(function (s) {
      var b = el('button', 'navmain-btn');
      b.type = 'button';
      b.dataset.section = s.id;
      b.setAttribute('role', 'tab');
      b.title = s.question;
      b.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + s.icon + '</svg>' +
        '<span class="navmain-lbl">' + s.label + '</span>';
      b.addEventListener('click', function () { go(s.id, null, true); });
      primary.appendChild(b);
    });

    var sub = el('div', 'navsub');
    var subInner = el('nav', 'navsub-inner');
    subInner.setAttribute('role', 'tablist');
    subInner.setAttribute('aria-label', 'Views');
    sub.appendChild(subInner);

    var learn = el('button', 'navlearn');
    learn.type = 'button';
    learn.innerHTML = '<span>Glossary</span>';
    learn.addEventListener('click', function () {
      go('research', 'vocab', true);
    });
    sub.appendChild(learn);

    var blurb = el('p', 'navblurb');

    wrap.appendChild(primary);
    wrap.appendChild(sub);
    wrap.appendChild(blurb);
    oldNav.parentNode.insertBefore(wrap, oldNav);

    return true;
  }

  function markLearn(on) {
    var l = $('.navlearn');
    if (l) l.classList.toggle('on', !!on);
    if (on) {
      document.querySelectorAll('.navmain-btn').forEach(function (b) {
        b.classList.remove('on');
        b.setAttribute('aria-selected', 'false');
      });
      var sub = $('.navsub-inner');
      if (sub) sub.innerHTML = '';
      var blurb = $('.navblurb');
      if (blurb) blurb.textContent = 'Plain-English definitions for every term the scores use.';
      syncMobile('vocab');
    }
  }

  function go(sectionId, tabId, userInitiated) {
    /* A tab id is more specific than the section id it arrived with, so it
       wins. Old links carry pairs like ('screener', 'funds') that no longer
       agree with each other; the destination is the thing to honour.

       And a lone id that names a tab rather than a product is that tab:
       go('planner') and go('ideas') both predate this structure and both have
       to keep landing where they always did. */
    var s;
    if (tabId) {
      s = ownerOf(tabId) || sectionById(sectionId);
    } else {
      var asTab = rawSection(sectionId) ? null : ownerOf(sectionId);
      if (asTab) { s = asTab; tabId = sectionId; }
      else s = sectionById(sectionId);
    }
    markLearn(false);

    // Only deliberate navigation. Restoring a section from the hash on load
    // would otherwise count as a visit to a page nobody chose to open.
    if (userInitiated && window.AltahaTrack) {
      window.AltahaTrack('view_opened', { section: s && s.id, tab: tabId || null });
    }

    var target = tabId;
    if (!target || !tabById(s, target)) {
      target = s.tabs.length ? s.tabs[0].id : null;
    }
    var def = target ? tabById(s, target) : null;

    /* News & post drafts is a panel over the page rather than a view, so it
       opens rather than switching a tab. */
    if (target === 'social') {
      if (window.AltahaSocial && typeof window.AltahaSocial.open === 'function') {
        window.AltahaSocial.open();
      } else {
        var so = $id('altaha-social-open');
        if (so) so.click();
      }
      current = { section: s.id, tab: target };
      paint(s, target);
      if (userInitiated) { setHash(s.id, target); }
      return;
    }

    /* The planner is the other brand on this page, not a tab in the screener's
       strip, so it is reached through the brand switch. */
    if (def && def.brand === 'planner') {
      var pb = $id('bsw-planner');
      if (pb) pb.click();
      current = { section: s.id, tab: target };
      paint(s, target);
      if (userInitiated) { setHash(s.id, target); scrollToContent(); }
      return;
    }

    var sb = $id('bsw-screener');
    if (sb && !sb.classList.contains('active')) sb.click();

    if (target) clickLegacy(target, 0);

    current = { section: s.id, tab: target };
    paint(s, target);
    if (userInitiated) { setHash(s.id, target); scrollToContent(); }
  }

  function paint(section, tabId) {
    document.querySelectorAll('.navmain-btn').forEach(function (b) {
      var on = b.dataset.section === section.id;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });

    var host = $('.navsub-inner');
    if (host) {
      host.innerHTML = '';
      /* An extra that is currently open is shown in the row so the reader can
         see where they are — but only while they are there. */
      var row = section.tabs.slice();
      if (tabId && !row.some(function (t) { return t.id === tabId; })) {
        var extra = tabById(section, tabId);
        if (extra) row.push(extra);
      }
      if (row.length > 1) {
        row.forEach(function (t) {
          var b = el('button', 'navsub-btn' + (t.id === tabId ? ' on' : ''));
          b.type = 'button';
          b.setAttribute('role', 'tab');
          b.setAttribute('aria-selected', t.id === tabId ? 'true' : 'false');
          b.innerHTML = '<span class="navsub-lbl">' + t.label + '</span>' +
                        '<span class="navsub-hint">' + t.hint + '</span>';
          b.addEventListener('click', function () { go(section.id, t.id, true); });
          host.appendChild(b);
        });
      }
      host.parentNode.classList.toggle('empty', row.length <= 1);
    }

    var blurb = $('.navblurb');
    if (blurb) blurb.textContent = section.blurb || '';

    syncMobile(section.id);
    window.dispatchEvent(new CustomEvent('altaha:navigate', { detail: { section: section.id, tab: tabId } }));
  }

  function scrollToContent() {
    if (booting) return;
    var anchor = document.body.classList.contains('sh-on')
      ? ($id('view-' + current.tab) || $('main')) : $('.navwrap');
    if (!anchor) return;
    var top = anchor.getBoundingClientRect().top + window.scrollY - (document.querySelector('.sh-chrome')?.offsetHeight || 0) - 12;
    window.scrollTo({ top: Math.max(0, top), behavior: reduced ? 'auto' : 'smooth' });
  }

  var lastWritten = null;

  function hashFor(sectionId, tabId) {
    return '#' + sectionId + (tabId && tabId !== sectionId ? '/' + tabId : '');
  }

  function setHash(sectionId, tabId) {
    var h = hashFor(sectionId, tabId);
    lastWritten = h;
    if (location.hash !== h) history.pushState(null, '', h);
  }

  function readHash() {
    var raw = (location.hash || '').replace(/^#/, '').split('/');
    var sectionId = raw[0] || '';
    var tabId = raw[1] || null;
    if (!sectionId) return { section: HOME.section, tab: HOME.tab };

    /* #funds and #screener/funds both mean the same destination. An explicit
       tab slot is the most specific thing in the address, so it is read first
       — the section beside it may be a name this site stopped using. Failing
       that, a bare tab id sitting in the section slot resolves to its owner. */
    if (tabId) {
      var tabOwner = ownerOf(tabId);
      if (tabOwner) return { section: tabOwner.id, tab: tabId };
    }
    var owner = ownerOf(sectionId);
    if (owner && !rawSection(sectionId)) return { section: owner.id, tab: sectionId };

    var known = rawSection(sectionId) || ALIASES[sectionId];
    return known ? { section: sectionById(sectionId).id, tab: tabId } : null;
  }

  window.addEventListener('hashchange', function () {
    if (location.hash === lastWritten) return;
    var r = readHash();
    if (r) {
      lastWritten = location.hash;
      go(r.section, r.tab, false);
    }
  });

  function buildMobile() {
    document.querySelectorAll('.mobnav, .navmob').forEach(function (n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });

    var bar = el('nav', 'navmob');
    bar.setAttribute('aria-label', 'Products');
    var inner = el('div', 'navmob-inner');
    inner.style.gridTemplateColumns = 'repeat(' + SECTIONS.length + ', 1fr)';

    SECTIONS.forEach(function (s) {
      var b = el('button', 'navmob-btn');
      b.type = 'button';
      b.dataset.section = s.id;
      b.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + s.icon + '</svg>' +
        '<span>' + s.label + '</span>';
      b.addEventListener('click', function () { go(s.id, null, true); });
      inner.appendChild(b);
    });

    bar.appendChild(inner);
    document.body.appendChild(bar);
  }

  function syncMobile(activeId) {
    document.querySelectorAll('.navmob-btn').forEach(function (b) {
      b.classList.toggle('on', b.dataset.section === activeId);
    });
  }

  function start() {
    if (!build()) return;

    buildMobile();
    setTimeout(buildMobile, 400);
    setTimeout(buildMobile, 1200);

    var qCharts = queryChartsSymbol();
    var r = readHash();
    if (qCharts != null) go('research', 'charts', false);
    else if (r) go(r.section, r.tab, false);
    else paint(sectionById(HOME.section), HOME.tab);

    var legacy = $('.legacy-nav');
    if (legacy) {
      var WATCH = [];
      SECTIONS.forEach(function (s) {
        allTabs(s).forEach(function (t) { WATCH.push(t.id); });
      });
      new MutationObserver(function () {
        var active = null;
        WATCH.forEach(function (t) {
          var b = $id('tab-' + t);
          if (b && b.classList.contains('active')) active = t;
        });
        if (!active || active === current.tab) return;
        var owner = ownerOf(active);
        if (owner) {
          current = { section: owner.id, tab: active };
          paint(owner, active);
        }
      }).observe(legacy, { subtree: true, attributes: true, attributeFilter: ['class'] });
    }

    /* Any button anywhere on the page can name a destination with
       data-goto="tab" or data-goto="section/tab". One delegated handler beats
       a dozen files each reaching for AltahaNav and each getting the
       section-vs-tab question subtly wrong. */
    document.addEventListener('click', function (ev) {
      var b = ev.target && ev.target.closest && ev.target.closest('[data-goto]');
      if (!b) return;
      ev.preventDefault();
      var raw = String(b.dataset.goto || '').split('/');
      var tab = raw.length > 1 ? raw[1] : raw[0];
      var owner = ownerOf(tab);
      go(raw.length > 1 ? raw[0] : (owner ? owner.id : 'research'), tab, true);
    });

    setTimeout(function () { booting = false; }, 600);

    function dropClonedSocial() {
      document.querySelectorAll('.navmain #altaha-social-open').forEach(function (el) {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
      var host = $('.navmain');
      if (host) host.style.gridTemplateColumns = '';
    }
    dropClonedSocial();
    setTimeout(dropClonedSocial, 500);
    setTimeout(dropClonedSocial, 1600);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.AltahaNav = { go: go, sections: SECTIONS, aliases: ALIASES };
})();
