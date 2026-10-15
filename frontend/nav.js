/* Altaha — Navigation

   THREE DOORS, ONE QUESTION EACH
   The site used to show four menus, seven header buttons and two strips, and
   a phone got one list of all twenty-five destinations. Everything was on
   offer at once, so nothing stood out. Now there are three doors, each the
   answer to a question somebody actually arrives with, plus a Me menu:

     Today      What is the market doing?          (section id: discover)
     Ideas      What should I look at?             (section id: research)
     My money   How am I doing, and what next?     (section id: portfolio)
     Me         Account, settings and learning     (section id: me)

   Each door opens on a page of its own (today / ideahub / money, built by
   doors.js) that previews every tool behind it with one live number or one
   line, and the tool opens on a tap. Nothing was removed: every tool that
   had a tab still has one, in exactly one door.

   THE SECTION IDS DID NOT CHANGE
   Today is still `discover`, Ideas is still `research` and My money is still
   `portfolio`, so #discover/deals, #research/query and #portfolio keep
   working, and so does every caller of AltahaNav.go() in this codebase.
   Only the labels and the tabs inside them moved.

   TABS ARE THE DOOR, EXTRAS ARE RARE
   `tabs` are the tools shown in the door bar (shell.js) and on the door
   page. `extras` are routable but deliberately quiet: the old Stock
   analysis view, whose search box and market board the header search and
   the Today page now cover.

   OLD ADDRESSES STILL RESOLVE
   ALIASES maps every section id this site has ever put in a URL onto the
   door that now owns it, and a tab id always wins over the section id it
   arrived with, so AltahaNav.go('screener', 'filings') lands on Today ›
   Filings & news whether or not the caller knows the doors exist.

   shell.js renders the visible header from this map; this module owns
   routing and fallback navigation.
*/

(function () {
  'use strict';

  var SECTIONS = [
    {
      id: 'discover', label: 'Today',
      question: 'What is the market doing?',
      blurb: 'What is the market doing? — prices, sectors, flows, and everything that happened today',
      icon: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
      tabs: [
        { id: 'today',    label: 'Overview',          hint: 'The market at a glance, live' },
        { id: 'live',     label: 'Alerts',            hint: 'Intraday signals as they fire' },
        { id: 'deals',    label: 'Big trades',        hint: 'Bulk and block deals, and who made them' },
        { id: 'wow',      label: 'Order wins',        hint: 'New orders measured against company size' },
        { id: 'special',  label: 'Delivery trends',   hint: 'Price moves backed by delivered volume' },
        { id: 'results',  label: 'Results calendar',  hint: 'Who reports yesterday, today and this week' },
        { id: 'filings',  label: 'Filings & news',    hint: 'Company announcements as they are filed' },
        { id: 'discover', label: 'Setups',            hint: 'Today’s strongest setups and unusual activity' },
        { id: 'options',  label: 'Options',           hint: 'Option prices and open interest' }
      ],
      extras: [
        { id: 'screener', label: 'Market board',      hint: 'The market board and a stock search box' }
      ]
    },
    {
      id: 'research', label: 'Ideas',
      question: 'What should I look at?',
      blurb: 'What should I look at? — the ranked universe, your own screens, and what great investors hold',
      icon: '<circle cx="12" cy="12" r="9"/><path d="m15.6 8.4-2.3 5-5 2.2 2.3-5Z"/>',
      tabs: [
        { id: 'ideahub',     label: 'Overview',        hint: 'Every way to find a stock, in one place' },
        { id: 'ideas',       label: 'Universe scan',   hint: 'NSE stocks ranked by the Altaha Score' },
        { id: 'query',       label: 'Screener',        hint: 'Filter every company by your own rules' },
        { id: 'lenses',      label: 'Investor styles', hint: 'Stocks picked the way great investors pick them' },
        { id: 'convergence', label: 'Convergence',     hint: 'Stocks that pass three or more investor styles' },
        { id: 'investors',   label: 'Who owns what',   hint: 'What well-known investors disclosed holding' },
        { id: 'funds',       label: 'Fund houses',     hint: 'What the mutual funds disclosed holding' },
        { id: 'charts',      label: 'Charts',          hint: 'Price charts, drawings, levels and indicators' },
        { id: 'tracker',     label: 'Track record',    hint: 'How past ideas have done since they were found' },
        { id: 'factors',     label: 'Factors',         hint: 'What each factor has actually predicted' },
        { id: 'concalls',    label: 'Concalls',        hint: 'Earnings call transcripts, digested' }
      ],
      extras: []
    },
    {
      id: 'portfolio', label: 'My money',
      question: 'How am I doing, and what next?',
      blurb: 'How am I doing, and what next? — your holdings, your plan and the next rupee',
      icon: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/>',
      tabs: [
        { id: 'money',     label: 'Overview',          hint: 'Your portfolio, watchlist and plans' },
        { id: 'portfolio', label: 'Portfolio review',  hint: 'A clear call on every holding' },
        { id: 'allocate',  label: 'Allocation plan',   hint: 'Where your next rupee should go' },
        { id: 'planner',   label: 'Money planner',     hint: 'Income, expenses, tax and your cushion', brand: 'planner' }
      ],
      extras: []
    },
    {
      id: 'me', label: 'Me',
      question: 'Account, settings and learning',
      blurb: 'How Altaha works, the glossary, and your account',
      icon: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
      tabs: [
        { id: 'score',  label: 'How the score works', hint: 'Every pillar and weight, in plain words' },
        { id: 'vocab',  label: 'Glossary',            hint: 'Market terms in plain language' },
        { id: 'social', label: 'Post drafts',         hint: 'Prepare posts for X and Telegram' }
      ],
      extras: []
    }
  ];

  /* The three doors the header and the phone bar show. Me is reached from
     its own button, not as a fourth door. */
  var DOORS = ['discover', 'research', 'portfolio'];

  /* Every section id this site has ever put in a URL, pointed at the door
     that now owns it. A hash is a promise; breaking one silently is how a
     shared link turns into a bounce. */
  var ALIASES = {
    today:    'discover',
    screener: 'discover',
    stocks:   'research',
    ideas:    'research',
    social:   'me',
    news:     'discover',
    planner:  'portfolio',
    allocate: 'portfolio',
    money:    'portfolio',
    learn:    'me'
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

  /* The first screen is Today: the market, live, with every tool behind the
     door one tap away. Looking up one company is the header search, which is
     on every page, so it no longer needs the landing view to itself. */
  var HOME = { section: 'discover', tab: 'today' };
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

  function queryGo() {
    try {
      return (new URLSearchParams(location.search).get('go') || '').trim().toLowerCase().replace(/[^a-z]/g, '');
    } catch (e) {
      return '';
    }
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
      go('me', 'vocab', true);
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
    document.body.dataset.tab = tabId || "";
    // The landing banner belongs to the landing page. Asked for a product —
    // by a link (?go=), an address (#portfolio) or a click — the reader gets
    // the product, not 600px of welcome above it.
    document.body.classList.toggle('at-home', !location.hash && !/[?&]go=/.test(location.search));
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
    document.body.classList.remove('at-home');
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

    /* A bare door id that is also one of its own tools is that tool, which is
       what it meant before the doors had pages of their own: #portfolio has
       always been the holdings review (sign-in, Pro and Advisors link it),
       and #discover the Opportunities hub. A door's own page is
       #portfolio/money, #discover/today, #research/ideahub. */
    var self = rawSection(sectionId);
    if (self && tabById(self, sectionId)) return { section: self.id, tab: sectionId };

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
    var qGo = queryGo();
    /* ?go=portfolio and friends. index.html also clicks the named tab, but
       on its own timer; now that the landing view is routed rather than
       merely painted, whichever ran second used to win, and a shared link
       could open on Today instead of the tool it named. Honouring it here
       makes the answer the same every time. A tab id wins, as everywhere,
       and an explicit #hash wins over both (readHash answers HOME when
       there is no hash at all, so it is asked only when there is one). */
    var hasHash = !!(location.hash || '').replace(/^#/, '');
    if (qCharts != null) go('research', 'charts', false);
    else if (hasHash && r) go(r.section, r.tab, false);
    else if (qGo && ownerOf(qGo)) go(ownerOf(qGo).id, qGo, false);
    else if (qGo && (rawSection(qGo) || ALIASES[qGo])) go(qGo, null, false);
    else if (r) go(r.section, r.tab, false);
    else go(HOME.section, HOME.tab, false);

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

  window.AltahaNav = {
    go: go, sections: SECTIONS, aliases: ALIASES, doors: DOORS,
    current: function () { return { section: current.section, tab: current.tab }; },
    ownerOf: function (tabId) { var o = ownerOf(tabId); return o ? o.id : null; }
  };
})();
