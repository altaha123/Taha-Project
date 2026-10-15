/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — shell.js
   Builds the application chrome and owns the motion vocabulary.

   THREE LAYERS, IN THE ORDER A TRADER READS THEM
     1  Headline ribbon   what just happened          /social/news/feed
     2  Live ticker       what things are doing now   /market + /sector/overview
     3  Menu              where you can go            proxied to AltahaNav

   IT DOES NOT OWN ROUTING
   nav.js already resolves sections and tabs, restores them from the hash and
   proxies to the legacy tab buttons, and it works. This file renders a
   different set of pixels and calls AltahaNav.go(). If AltahaNav has not
   loaded yet the menu waits for it rather than growing a second router — two
   routers on one page is how a back button starts lying.

   SEARCH LEAVES THE PAGE
   Analysing a stock used to replace part of the homepage, so there was no URL
   for a company, nothing to link to, nothing to share and no back button. It
   now navigates to stock.html?ticker=SYM, which is a real page with a real
   address.

   EVERY NETWORK CALL FAILS SOFT
   The ribbon, the ticker and the typeahead each hide themselves if their
   endpoint is unreachable. On a free instance that is asleep this is the
   normal case for the first thirty seconds, and chrome that renders an error
   is worse than chrome that renders nothing.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined) n.textContent = txt;
    return n;
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    var opts = ctl ? { signal: ctl.signal } : {};
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 9000);
    return fetch(API + path, opts)
      .then(function (r) {
        if (timer) clearTimeout(timer);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
  }

  /* ── Icons ────────────────────────────────────────────────────────────────
     Inline SVG paths, not image files. Three reasons that matters here: they
     cost no extra request on a page already waiting on a sleeping backend,
     they are drawn in currentColor so they recolour with the theme and on
     hover for free, and they stay sharp on any display. Stroke geometry
     matches the icons nav.js already draws, so the two sets look like one.

     Each one depicts its destination rather than decorating it — a receipt
     for the ledger, candles for charts, a target for the measured record. An
     icon that could be swapped with its neighbour without anyone noticing is
     not carrying information and should not be on the screen. */

  var ICON = {
    ledger:   '<path d="M5 3v18l2.5-1.6L10 21l2.5-1.6L15 21l2.5-1.6L20 21V3z"/><path d="M9 8h6M9 12h6"/>',
    candles:  '<path d="M7 4v3M7 17v3M17 4v3M17 17v3"/><rect x="4.5" y="7" width="5" height="10" rx="1"/><rect x="14.5" y="7" width="5" height="10" rx="1"/>',
    document: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 14h5M9 17h3"/>',
    bell:     '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    exchange: '<path d="M3 8h14l-4-4"/><path d="M21 16H7l4 4"/>',
    layers:   '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
    bulb:     '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6h5.4c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z"/>',
    pulse:    '<path d="M3 12h3.5l2.2-6 3.4 12 2.6-7.5 1.4 1.5H21"/>',
    target:   '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.6"/><circle cx="12" cy="12" r="1"/>',
    bars:     '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    shield:   '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    plan:     '<path d="M3 3v18h18"/><path d="m7 14 3-3 3 3 5-6"/>',
    share:    '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v13"/>',
    chat:     '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12Z"/><path d="M8.5 11h7M8.5 14h4"/>',
    lens:     '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 4v4M12 16v4M4 12h4M16 12h4"/>',
    converge: '<circle cx="8" cy="10" r="5"/><circle cx="16" cy="10" r="5"/><circle cx="12" cy="16" r="5"/>'
  };

  function svg(key) {
    return '<span class="sh-ico" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      (ICON[key] || '') + '</svg></span>';
  }

  /* ── The door map ──────────────────────────────────────────────────────────
     Three doors, each the answer to one question, and a Me menu. Mirrors the
     sections in nav.js (same section and tab ids) because this file also runs
     on pages without nav.js — the stock page, Pro, Advisors — where a door is
     a link back to index.html#section/tab. Every item has a few `kw` words so
     the search box finds a tool by what people call it, not only by its
     label: "bulk" finds Big trades, "pledge" finds the Screener. */

  var DOORS = [
    {
      id: 'discover', label: 'Today', question: 'What is the market doing?',
      items: [
        { tab: 'today', label: 'Overview', icon: 'pulse', hint: 'The market at a glance, live', kw: 'home market nifty sensex index sectors heatmap fii dii' },
        { tab: 'live', label: 'Alerts', icon: 'bell', hint: 'Intraday signals as they fire', kw: 'live scanner intraday volume breakout' },
        { tab: 'deals', label: 'Big trades', icon: 'exchange', hint: 'Bulk and block deals, and who made them', kw: 'bulk block deals' },
        { tab: 'wow', label: 'Order wins', icon: 'target', hint: 'New orders measured against company size', kw: 'wow orders contract' },
        { tab: 'special', label: 'Delivery trends', icon: 'bars', hint: 'Price moves backed by delivered volume', kw: 'delivery special accumulation' },
        { tab: 'results', label: 'Results calendar', icon: 'document', hint: 'Who reports yesterday, today and this week', kw: 'results earnings quarterly calendar' },
        { tab: 'filings', label: 'Filings & news', icon: 'document', hint: 'Company announcements as they are filed', kw: 'news announcements filings exchange' },
        { tab: 'discover', label: 'Setups', icon: 'target', hint: 'Today’s strongest setups and unusual activity', kw: 'opportunities setups ideas today' },
        { tab: 'options', label: 'Options', icon: 'layers', hint: 'Option prices and open interest', kw: 'options open interest oi derivatives fno chain' },
        { tab: 'screener', label: 'Market board', icon: 'bars', hint: 'The market board and a stock search box', kw: 'analysis board movers', quiet: true }
      ]
    },
    {
      id: 'research', label: 'Ideas', question: 'What should I look at?',
      items: [
        { tab: 'ideahub', label: 'Overview', icon: 'bulb', hint: 'Every way to find a stock, in one place', kw: 'ideas find discover' },
        { tab: 'ideas', label: 'Universe scan', icon: 'bulb', hint: 'NSE stocks ranked by the Altaha Score', kw: 'universe scan ranked top best planets' },
        { tab: 'query', label: 'Screener', icon: 'lens', hint: 'Filter every company by your own rules', kw: 'query filter screen roe roce pe debt pledge promoter' },
        { tab: 'lenses', label: 'Investor styles', icon: 'lens', hint: 'Stocks picked the way great investors pick them', kw: 'lenses philosophy coffee can moat qglp' },
        { tab: 'convergence', label: 'Convergence', icon: 'converge', hint: 'Stocks that pass three or more investor styles', kw: 'convergence lenses' },
        { tab: 'investors', label: 'Who owns what', icon: 'shield', hint: 'What well-known investors disclosed holding', kw: 'investors superstar ownership holdings' },
        { tab: 'funds', label: 'Fund houses', icon: 'layers', hint: 'What the mutual funds disclosed holding', kw: 'mutual fund amc portfolios' },
        { tab: 'charts', label: 'Charts', icon: 'candles', hint: 'Price charts, drawings, levels and indicators', kw: 'chart technicals rsi macd fibonacci' },
        { tab: 'tracker', label: 'Track record', icon: 'target', hint: 'How past ideas have done since they were found', kw: 'tracker performance record' },
        { tab: 'factors', label: 'Factors', icon: 'plan', hint: 'What each factor has actually predicted', kw: 'factors ic accuracy' },
        { tab: 'concalls', label: 'Concalls', icon: 'chat', hint: 'Earnings call transcripts, digested', kw: 'concall earnings call transcript' }
      ]
    },
    {
      id: 'portfolio', label: 'My money', question: 'How am I doing, and what next?',
      items: [
        { tab: 'money', label: 'Overview', icon: 'shield', hint: 'Your portfolio, watchlist and plans', kw: 'money mine' },
        { tab: 'portfolio', label: 'Portfolio review', icon: 'plan', hint: 'A clear call on every holding', kw: 'portfolio holdings review plan hold trim exit' },
        { tab: 'allocate', label: 'Allocation plan', icon: 'shield', hint: 'Where your next rupee should go', kw: 'allocate asset allocation invest' },
        { tab: 'planner', label: 'Money planner', icon: 'plan', hint: 'Income, expenses, tax and your cushion', kw: 'planner budget tax emergency' },
        { href: 'advisors.html', label: 'Talk to an adviser', icon: 'chat', hint: 'Chat with SEBI-registered advisers', kw: 'advisor adviser sebi chat expert' }
      ]
    }
  ];

  var ME_ITEMS = [
    { section: 'me', tab: 'score', label: 'How the score works', icon: 'target', hint: 'Every pillar and weight, in plain words', kw: 'altaha score methodology' },
    { section: 'me', tab: 'vocab', label: 'Glossary', icon: 'document', hint: 'Market terms in plain language', kw: 'glossary vocabulary terms meaning' },
    { section: 'me', tab: 'social', label: 'Post drafts', icon: 'share', hint: 'Prepare posts for X and Telegram', kw: 'social posts drafts twitter telegram' }
  ];

  /* Everything the search box can open that is not a company. */
  function allTools() {
    var out = [];
    DOORS.forEach(function (d) {
      d.items.forEach(function (it) {
        out.push({ section: d.id, door: d.label, tab: it.tab, href: it.href, label: it.tab && /^(today|ideahub|money)$/.test(it.tab) ? d.label : it.label,
                   hint: it.hint, icon: it.icon, kw: it.kw || '' });
      });
    });
    ME_ITEMS.forEach(function (it) {
      out.push({ section: 'me', door: 'Me', tab: it.tab, label: it.label, hint: it.hint, icon: it.icon, kw: it.kw || '' });
    });
    out.push({ door: 'Me', href: 'pro.html?from=search', label: 'Altaha Pro', hint: 'Saved screens and the daily email', icon: 'bulb', kw: 'pro premium subscribe price' });
    out.push({ door: 'Me', href: 'signin.html', label: 'Sign in', hint: 'Keep your portfolio and watchlist on your account', icon: 'shield', kw: 'login account sign' });
    return out;
  }

  /* ── Navigation hand-off ─────────────────────────────────────────────────── */

  function navigate(sectionId, tabId, tries) {
    if (window.AltahaNav && typeof window.AltahaNav.go === 'function') {
      window.AltahaNav.go(sectionId, tabId || null, true);
      return;
    }
    // On the stock page there is no AltahaNav and no tab machinery — the
    // section lives on the homepage, so go there and let the hash restore it.
    if (!document.getElementById('tab-screener')) {
      location.href = 'index.html#' + sectionId + (tabId && tabId !== sectionId ? '/' + tabId : '');
      return;
    }
    if ((tries || 0) > 25) return;
    setTimeout(function () { navigate(sectionId, tabId, (tries || 0) + 1); }, 200);
  }

  function openStock(sym, from) {
    sym = String(sym || '').trim().toUpperCase();
    if (!sym) return;
    if (window.AltahaTrack) window.AltahaTrack('stock_opened', { ticker: sym, from: from || 'link' });
    location.href = 'stock.html?ticker=' + encodeURIComponent(sym);
  }
  window.AltahaOpenStock = openStock;

  /* ── Build the chrome ──────────────────────────────────────────────────────
     Three rows, top to bottom:
       1  the live tape    prices moving now (startTicker)
       2  the bar          brand · three doors · search · Me
       3  the door bar     the tools behind the door you are in (index only)
     The headline ribbon that used to sit above the tape now lives on the
     Today page as its Headlines card, and the row of Watchlist, Advisors,
     Pro, Sign in and theme buttons is the Me menu. */

  var CHROME = null;
  var PIN_KEY = 'altaha-pins-v1';

  function onIndex() { return !!document.getElementById('tab-screener'); }
  function narrow() { return window.matchMedia && window.matchMedia('(max-width:1040px)').matches; }

  function build() {
    if (document.querySelector('.sh-chrome')) return;

    var chrome = el('div', 'sh-chrome');

    var ticker = el('div', 'sh-ticker');
    ticker.setAttribute('aria-label', 'Live market prices');
    ticker.innerHTML =
      '<span class="sh-livetag"><i class="sh-dot"></i>Live</span>' +
      '<div class="sh-railbox"><div class="sh-rail" id="sh-rail"></div></div>' +
      '<span class="sh-ribbon-clock" id="sh-clock"></span>';

    var bar = el('div', 'sh-bar');

    var brand = el('a', 'sh-brand');
    brand.href = 'index.html';
    brand.setAttribute('aria-label', 'Altaha Screener home');
    brand.innerHTML =
      '<span class="mk" aria-hidden="true"></span>' +
      '<span class="nm">Altaha <i>Screener</i></span>';

    var nav = el('nav', 'sh-nav sh-doors');
    nav.setAttribute('aria-label', 'Main');
    nav.innerHTML = '<span class="sh-door-ind" aria-hidden="true"></span>' + DOORS.map(function (d) {
      return '<button type="button" class="sh-top sh-door" data-sec="' + esc(d.id) + '" title="' + esc(d.question) + '">' +
        esc(d.label) + '</button>';
    }).join('');

    var search = el('div', 'sh-search');
    search.innerHTML =
      '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/></svg>' +
      '<input id="sh-q" type="text" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="false" ' +
      'aria-controls="sh-ac" placeholder="Search stocks, tools, or what you want to do" aria-label="Search stocks and tools" />' +
      '<span class="kbd">Ctrl K</span><div class="sh-ac" id="sh-ac" role="listbox"></div>';

    /* Me: account, Pro, Advisors, the watchlist, appearance and learning.
       The ids are the ones the rest of the site and its tests already know. */
    var meWrap = el('div', 'sh-mewrap');
    var me = el('button', 'sh-icon sh-me');
    me.type = 'button';
    me.id = 'sh-me';
    me.setAttribute('aria-label', 'Me: account, settings and learning');
    me.setAttribute('aria-haspopup', 'true');
    me.setAttribute('aria-expanded', 'false');
    me.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>';
    var menu = el('div', 'sh-memenu');
    menu.id = 'sh-memenu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Me');

    var right = el('div', 'sh-right');      // experience.js adds the Watchlist button here
    var account = el('a', 'sh-account');
    account.id = 'sh-account';
    account.href = 'signin.html';
    account.textContent = 'Sign in';
    var pro = el('a', 'sh-pro');
    pro.id = 'sh-pro';
    pro.href = 'pro.html?from=header';
    pro.innerHTML = 'Altaha Pro<small>Saved screens and the daily email</small>';
    pro.addEventListener('click', function () {
      if (window.AltahaTrack) window.AltahaTrack('pro_cta_clicked', { from: 'header' });
    });
    var adv = el('a', 'sh-adv');
    adv.id = 'sh-adv';
    adv.href = 'advisors.html';
    adv.innerHTML = 'Talk to an adviser<small>SEBI-registered, free to chat</small>';
    adv.addEventListener('click', function () {
      if (window.AltahaTrack) window.AltahaTrack('advisors_cta_clicked', { from: 'header' });
    });
    var themeBtn = el('button', 'sh-icon sh-themebtn');
    themeBtn.type = 'button';
    themeBtn.id = 'sh-theme';
    themeBtn.setAttribute('aria-label', 'Switch appearance');
    right.appendChild(account);
    right.appendChild(pro);
    right.appendChild(adv);
    var themeRow = el('div', 'sh-merow');
    themeRow.innerHTML = '<span>Appearance</span>';
    themeRow.appendChild(themeBtn);
    var learn = el('div', 'sh-melearn');
    learn.innerHTML = '<h4>Learn</h4>' + ME_ITEMS.map(function (it) { return itemHTML('me', it); }).join('');
    menu.appendChild(right);
    menu.appendChild(themeRow);
    menu.appendChild(learn);
    meWrap.appendChild(me);
    meWrap.appendChild(menu);

    paintAccount();
    window.addEventListener('altaha-auth', paintAccount);

    bar.appendChild(brand);
    bar.appendChild(nav);
    bar.appendChild(search);
    bar.appendChild(meWrap);

    chrome.appendChild(ticker);
    chrome.appendChild(bar);

    if (onIndex()) {
      var doorbar = el('nav', 'sh-doorbar');
      doorbar.id = 'sh-doorbar';
      doorbar.setAttribute('aria-label', 'Tools behind this door');
      chrome.appendChild(doorbar);
      document.documentElement.classList.add('sh-has-doorbar');
    }

    document.body.insertBefore(chrome, document.body.firstChild);

    /* On a phone, Me opens as a sheet that also carries the whole map: every
       tool behind every door, for the reader who would rather browse than
       search. */
    var drawer = el('dialog', 'sh-drawer');
    drawer.setAttribute('aria-label', 'Me and every tool');
    drawer.id = 'sh-drawer';
    document.body.appendChild(drawer);

    document.body.classList.add('sh-on');
    CHROME = chrome;

    wireDoors();
    wireMe(drawer);
    wireSearch();
    wireTheme();
    wireScroll();
  }

  // One builder for the Me menu, the phone sheet and the door bar, so an item
  // can never appear in one and be missing from another.
  function itemHTML(secId, it) {
    if (it.href) {
      return '<a class="sh-item" href="' + esc(it.href) + '">' + svg(it.icon) +
        '<span class="sh-txt"><b>' + esc(it.label) + '</b>' +
        '<span>' + esc(it.hint) + '</span></span></a>';
    }
    return '<button class="sh-item" type="button" data-sec="' + esc(it.section || secId) +
      '" data-tab="' + esc(it.tab) + '">' + svg(it.icon) +
      '<span class="sh-txt"><b>' + esc(it.label) + '</b>' +
      '<span>' + esc(it.hint) + '</span></span></button>';
  }

  /* ── The doors ───────────────────────────────────────────────────────────── */

  var activeDoor = null, activeTab = null;

  function wireDoors() {
    document.querySelectorAll('.sh-door').forEach(function (b) {
      b.addEventListener('click', function () { navigate(b.dataset.sec, null); });
    });
    window.addEventListener('altaha:navigate', function (e) {
      var d = (e && e.detail) || {};
      activeDoor = d.section || null;
      activeTab = d.tab || null;
      paintDoors();
      paintDoorbar();
    });
    window.addEventListener('resize', function () { paintDoors(true); });
    // nav.js routes the first view before this header exists, so its first
    // announcement is missed; ask it where we are instead. On the stock page
    // and the others there is no router, no door is open, and the indicator
    // simply stays hidden.
    function sync() {
      var nav = window.AltahaNav;
      if (!nav || typeof nav.current !== 'function') return;
      var c = nav.current();
      if (!c || (c.section === activeDoor && c.tab === activeTab)) return;
      activeDoor = c.section;
      activeTab = c.tab;
      paintDoors(true);
      paintDoorbar();
    }
    paintDoors();
    sync();
    setTimeout(sync, 250);
    setTimeout(sync, 1200);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { paintDoors(true); });
  }

  function paintDoors(instant) {
    var ind = document.querySelector('.sh-door-ind');
    var on = null;
    document.querySelectorAll('.sh-door').forEach(function (b) {
      var is = b.dataset.sec === activeDoor;
      b.classList.toggle('on', is);
      if (is) { b.setAttribute('aria-current', 'page'); on = b; } else b.removeAttribute('aria-current');
    });
    if (!ind) return;
    if (!on) { ind.style.opacity = '0'; return; }
    if (instant) ind.style.transition = 'none';
    ind.style.opacity = '1';
    ind.style.width = on.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + on.offsetLeft + 'px)';
    if (instant) { void ind.offsetWidth; ind.style.transition = ''; }
  }

  function readPins() {
    try { var p = JSON.parse(localStorage.getItem(PIN_KEY) || '[]'); return Array.isArray(p) ? p : []; }
    catch (e) { return []; }
  }

  /* The door bar: the tools behind the door you are in, the one you are on
     lit, and a pin for it. Switching between two tools in one door never
     needs a menu. */
  function paintDoorbar() {
    var bar = document.getElementById('sh-doorbar');
    if (!bar) return;
    var door = DOORS.filter(function (d) { return d.id === activeDoor; })[0];
    var items = door ? door.items.filter(function (it) { return !it.quiet || it.tab === activeTab; })
                     : activeDoor === 'me' ? ME_ITEMS : [];
    if (!items.length) { bar.innerHTML = ''; bar.classList.remove('on'); return; }
    var pinned = readPins();
    var pinnable = activeTab && !/^(today|ideahub|money)$/.test(activeTab);
    bar.innerHTML = '<div class="sh-doorbar-in">' + items.map(function (it, i) {
      var on = it.tab && it.tab === activeTab;
      if (it.href) {
        return '<a class="sh-pill" style="--i:' + i + '" href="' + esc(it.href) + '">' + esc(it.label) + '</a>';
      }
      return '<button type="button" class="sh-pill' + (on ? ' on' : '') + '" style="--i:' + i + '" data-sec="' +
        esc(door ? door.id : 'me') + '" data-tab="' + esc(it.tab) + '"' + (on ? ' aria-current="page"' : '') + '>' +
        esc(it.label) + '</button>';
    }).join('') + '</div>' +
      (pinnable ? '<button type="button" class="sh-pin' + (pinned.indexOf(activeTab) > -1 ? ' on' : '') + '" id="sh-pin" ' +
        'aria-pressed="' + (pinned.indexOf(activeTab) > -1 ? 'true' : 'false') + '" title="Pin this tool to your desk on Today">' +
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v8"/></svg><span>' +
        (pinned.indexOf(activeTab) > -1 ? 'Pinned' : 'Pin') + '</span></button>' : '');
    bar.classList.add('on');
    // Same backstop as the doors: the pills rise in from opacity 0, so once
    // they have had time to, the entrance is switched off.
    bar.classList.remove('sh-played');
    clearTimeout(bar._played);
    bar._played = setTimeout(function () { bar.classList.add('sh-played'); }, 1500);
    var cur = bar.querySelector('.sh-pill.on');
    if (cur && cur.scrollIntoView) {
      var box = bar.querySelector('.sh-doorbar-in');
      if (box && box.scrollWidth > box.clientWidth) box.scrollLeft = cur.offsetLeft - 40;
    }
  }

  function wireDoorbar() {
    var bar = document.getElementById('sh-doorbar');
    if (!bar) return;
    bar.addEventListener('click', function (e) {
      var pin = e.target.closest('#sh-pin');
      if (pin) {
        var p = readPins(), i = p.indexOf(activeTab);
        if (i > -1) p.splice(i, 1); else p.unshift(activeTab);
        try { localStorage.setItem(PIN_KEY, JSON.stringify(p.slice(0, 8))); } catch (err) {}
        window.dispatchEvent(new CustomEvent('altaha:pins'));
        paintDoorbar();
        return;
      }
      var b = e.target.closest('.sh-pill[data-tab]');
      if (b) navigate(b.dataset.sec, b.dataset.tab);
    });
  }

  /* ── Me ──────────────────────────────────────────────────────────────────── */

  function wireMe(drawer) {
    var me = document.getElementById('sh-me');
    var menu = document.getElementById('sh-memenu');
    wireDoorbar();

    function setMenu(on) {
      menu.classList.toggle('open', on);
      me.setAttribute('aria-expanded', on ? 'true' : 'false');
    }

    drawer.innerHTML =
      '<div class="sh-col sh-dme"><h4>Me</h4>' +
        '<div class="sh-dacct"><a class="sh-item sh-dacc" href="signin.html">' + svg('shield') +
          '<span class="sh-txt"><b class="sh-dacc-name">Sign in</b><span>Keep your portfolio and watchlist on your account</span></span></a></div>' +
        '<a class="sh-dpro" href="pro.html?from=menu"><b>Altaha Pro</b>' +
          '<span>The portfolio story, watchlist alerts and saved screens — ₹1,999 a year</span></a>' +
        '<a class="sh-item" href="advisors.html">' + svg('chat') +
          '<span class="sh-txt"><b>Talk to an adviser</b><span>SEBI-registered advisers, free to chat</span></span></a>' +
        '<button class="sh-item sh-dwatch" type="button">' + svg('target') +
          '<span class="sh-txt"><b>Watchlist</b><span>Stocks you follow</span></span></button>' +
        '<button class="sh-item sh-dtheme" type="button">' + svg('layers') +
          '<span class="sh-txt"><b>Appearance</b><span>Switch between light and dark</span></span></button>' +
        ME_ITEMS.map(function (it) { return itemHTML('me', it); }).join('') +
      '</div>' +
      DOORS.map(function (d) {
        return '<div class="sh-col"><h4>' + esc(d.label) + '</h4>' +
          '<p class="sh-megaq">' + esc(d.question) + '</p>' +
          d.items.filter(function (it) { return !it.quiet; }).map(function (it) { return itemHTML(d.id, it); }).join('') + '</div>';
      }).join('');

    var drawerClose = el('button', 'ux-button', 'Close');
    drawerClose.type = 'button';
    drawerClose.addEventListener('click', function () { setDrawer(false); });
    drawer.prepend(drawerClose);
    drawer.addEventListener('close', function () {
      drawer.classList.remove('open');
      me.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    });
    function setDrawer(on) {
      try {
        if (on && !drawer.open) drawer.showModal();
        if (!on && drawer.open) drawer.close();
      } catch (e) {}
      drawer.classList.toggle('open', on);
      me.setAttribute('aria-expanded', on ? 'true' : 'false');
      document.body.style.overflow = on ? 'hidden' : '';
      if (on) paintAccount();
    }
    window.matchMedia('(max-width:1040px)').addEventListener('change', function (e) {
      if (!e.matches && drawer.open) setDrawer(false);
      if (e.matches) setMenu(false);
    });

    me.addEventListener('click', function (e) {
      e.stopPropagation();
      if (narrow()) setDrawer(!drawer.classList.contains('open'));
      else setMenu(!menu.classList.contains('open'));
    });
    document.addEventListener('click', function (e) {
      if (!menu.classList.contains('open')) return;
      if (e.target.closest && e.target.closest('.sh-mewrap')) {
        var it = e.target.closest('.sh-item[data-tab], a, .ux-desktop-save');
        if (it) setMenu(false);
        return;
      }
      setMenu(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (menu.classList.contains('open')) { setMenu(false); me.focus(); }
      if (drawer.classList.contains('open')) { setDrawer(false); me.focus(); }
    });
    menu.addEventListener('click', function (e) {
      var it = e.target.closest('.sh-item[data-tab]');
      if (!it) return;
      navigate(it.dataset.sec, it.dataset.tab);
    });
    drawer.addEventListener('click', function (e) {
      if (e.target.closest('.sh-dtheme')) { toggleTheme(); return; }
      if (e.target.closest('.sh-dwatch')) {
        setDrawer(false);
        if (window.AltahaWatchlist) window.AltahaWatchlist.open();
        return;
      }
      var it = e.target.closest('.sh-item, .sh-dpro');
      if (!it) return;
      setDrawer(false);
      if (it.tagName === 'A') return;
      navigate(it.dataset.sec, it.dataset.tab);
    });

    window.AltahaShell = window.AltahaShell || {};
    window.AltahaShell.openMe = function () {
      if (narrow()) setDrawer(true); else setMenu(true);
    };
  }

  /* ── Search + typeahead ──────────────────────────────────────────────────── */

  var UNIVERSE = null;

  // The cache key carries a version because the rows it holds are normalised
  // now. A browser holding yesterday's raw payload under the old key would
  // otherwise keep feeding the broken shape back in for a day.
  var UNI_KEY = 'altaha-universe-v2';

  /* /universe answers with {"s": "RELIANCE", "n": "Reliance Industries Limited"}.
     This read it as r.symbol / r.name / r[0] / r[1] — none of which exist on
     that object — so every row scored as an empty symbol with an empty name
     and nothing ever matched. The box looked broken because it was: typing
     "reliance" against 2,300 real NSE tickers returned zero rows.

     Normalising once on load, instead of at every keystroke, means the matcher
     below reads one shape and only one, whatever the endpoint hands back. */
  function normalise(rows) {
    var out = [];
    for (var i = 0; i < (rows || []).length; i++) {
      var r = rows[i] || {};
      var s = String(r.s || r.symbol || r.ticker || r[0] || '').trim().toUpperCase();
      if (!s) continue;
      var n = String(r.n || r.name || r.company || r[1] || '').trim();
      out.push({ s: s, n: n || s, x: String(r.x || r.exchange || 'NSE').toUpperCase() });
    }
    return out;
  }

  function loadUniverse() {
    // Cached for a day. ~2,300 rows is far too much to refetch per keystroke,
    // and /universe already sets Cache-Control to say so.
    try {
      var raw = localStorage.getItem(UNI_KEY);
      if (raw) {
        var o = JSON.parse(raw);
        if (o && o.day === new Date().toISOString().slice(0, 10) && o.rows && o.rows.length) {
          UNIVERSE = normalise(o.rows);
          return;
        }
      }
    } catch (e) {}
    try { localStorage.removeItem('altaha-universe'); } catch (e) {}
    get('/universe', 12000).then(function (d) {
      UNIVERSE = normalise((d && d.rows) || []);
      try {
        localStorage.setItem(UNI_KEY, JSON.stringify({
          day: new Date().toISOString().slice(0, 10), rows: UNIVERSE
        }));
      } catch (e) {}
    }).catch(function () { UNIVERSE = []; });
  }

  /* Ranked, not merely filtered. An exact ticker has to outrank a company that
     merely contains the same letters, or typing ITC buries ITC under forty
     names with "itc" in the middle of a word. Same ladder premium-plus.js
     scores with, so the two search boxes agree on what the best answer is. */
  function score(r, q) {
    var s = r.s, n = (r.n || '').toUpperCase();
    if (s === q) return 1000;
    if (s.indexOf(q) === 0) return 600 - s.length;
    if (n.indexOf(q) === 0) return 400 - n.length / 10;
    if (n.indexOf(' ' + q) > -1) return 300;
    if (s.indexOf(q) > -1) return 200;
    if (n.indexOf(q) > -1) return 100;
    return 0;
  }

  function match(q) {
    if (!UNIVERSE || !UNIVERSE.length || !q) return [];
    q = q.trim().toUpperCase();
    if (!q) return [];
    var hits = [];
    for (var i = 0; i < UNIVERSE.length; i++) {
      var sc = score(UNIVERSE[i], q);
      if (sc) hits.push({ r: UNIVERSE[i], sc: sc });
    }
    hits.sort(function (a, b) { return b.sc - a.sc || (a.r.s < b.r.s ? -1 : 1); });
    return hits.slice(0, 9).map(function (h) { return h.r; });
  }

  /* Tools ranked the same way: the label first, then the words people use
     for it. */
  function matchTools(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    var words = q.split(/\s+/);
    return allTools().map(function (t) {
      var label = t.label.toLowerCase(), hay = (label + ' ' + t.kw + ' ' + t.hint + ' ' + t.door).toLowerCase();
      if (!words.every(function (w) { return hay.indexOf(w) > -1; })) return null;
      var sc = label.indexOf(q) === 0 ? 300 : label.indexOf(q) > -1 ? 200 : (' ' + t.kw + ' ').indexOf(' ' + words[0]) > -1 ? 120 : 60;
      return { t: t, sc: sc };
    }).filter(Boolean).sort(function (a, b) { return b.sc - a.sc; }).slice(0, 6).map(function (h) { return h.t; });
  }

  var RECENT_KEY = 'altaha-recent-v1';
  function recents() {
    try { var r = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); return Array.isArray(r) ? r : []; }
    catch (e) { return []; }
  }
  function remember(entry) {
    var r = recents().filter(function (x) { return !(x.kind === entry.kind && x.id === entry.id); });
    r.unshift(entry);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, 6))); } catch (e) {}
  }

  /* One box for everything: companies, every tool behind every door, and a
     few things you might want to do. Empty, it offers what you opened last
     and the three doors. */
  function wireSearch() {
    var input = document.getElementById('sh-q');
    var ac = document.getElementById('sh-ac');
    if (!input || !ac) return;
    var sel = -1, rows = [], q = '';

    // The part you typed is marked inside both the ticker and the company
    // name, so it is obvious why a row is on the list — RELIANCE for "reli"
    // and RELCHEMQ for the same four letters are on it for different reasons.
    function mark(text, needle) {
      var i = needle ? text.toUpperCase().indexOf(needle.toUpperCase()) : -1;
      if (i < 0) return esc(text);
      return esc(text.slice(0, i)) + '<i>' + esc(text.slice(i, i + needle.length)) +
        '</i>' + esc(text.slice(i + needle.length));
    }

    function toolRow(t) {
      return { kind: 'tool', id: (t.section || '') + '/' + (t.tab || t.href), t: t };
    }
    function build() {
      var out = [];
      if (!q) {
        recents().forEach(function (r) {
          if (r.kind === 'stock') out.push({ kind: 'stock', id: r.id, s: r.id, n: r.n || '', head: 'Recent' });
          else {
            var t = allTools().filter(function (x) { return (x.section || '') + '/' + (x.tab || x.href) === r.id; })[0];
            if (t) { var tr = toolRow(t); tr.head = 'Recent'; out.push(tr); }
          }
        });
        DOORS.forEach(function (d) {
          out.push({ kind: 'tool', id: d.id + '/door', head: 'Go to',
                     t: { section: d.id, tab: null, label: d.label, hint: d.question, icon: d.items[0].icon, door: '' } });
        });
        return out;
      }
      match(q).slice(0, 6).forEach(function (r) { out.push({ kind: 'stock', id: r.s, s: r.s, n: r.n, x: r.x, head: 'Stocks' }); });
      matchTools(q).forEach(function (t) { var tr = toolRow(t); tr.head = 'Tools'; out.push(tr); });
      out.push({ kind: 'screen', id: 'screen', head: 'Do', q: q });
      if (/portf|holding|my stock/i.test(q)) out.push({ kind: 'tool', id: 'portfolio/portfolio', head: 'Do',
        t: { section: 'portfolio', tab: 'portfolio', label: 'Review my portfolio', hint: 'A call on every holding', icon: 'plan', door: 'My money' } });
      return out;
    }

    function rowHTML(r, i) {
      var cls = 'row' + (i === sel ? ' sel' : '');
      if (r.kind === 'stock') {
        return '<b class="' + cls + '" role="option" data-i="' + i + '"><span class="s">' + mark(r.s, q) + '</span>' +
          '<span class="n">' + mark(r.n || '', q) + '</span>' +
          '<span class="x">' + esc(r.x || 'NSE') + '</span></b>';
      }
      if (r.kind === 'screen') {
        return '<b class="' + cls + ' tool" role="option" data-i="' + i + '">' + svg('lens') +
          '<span class="tl"><span class="tn">Screen every company for “' + esc(r.q) + '”</span>' +
          '<span class="th">Ideas · Screener</span></span></b>';
      }
      return '<b class="' + cls + ' tool" role="option" data-i="' + i + '">' + svg(r.t.icon) +
        '<span class="tl"><span class="tn">' + mark(r.t.label, q) + '</span>' +
        '<span class="th">' + esc((r.t.door ? r.t.door + ' · ' : '') + (r.t.hint || '')) + '</span></span></b>';
    }

    function paint() {
      if (document.activeElement !== input) { ac.classList.remove('open'); input.setAttribute('aria-expanded', 'false'); return; }
      if (q && !rows.some(function (r) { return r.kind === 'stock'; }) && UNIVERSE === null) {
        rows.unshift({ kind: 'loading', head: 'Stocks' });
      }
      var html = '', head = null;
      rows.forEach(function (r, i) {
        if (r.head !== head) { head = r.head; html += '<span class="hd">' + esc(head) + '</span>'; }
        if (r.kind === 'loading') { html += '<b class="row empty">Loading the NSE list…</b>'; return; }
        html += rowHTML(r, i);
      });
      ac.innerHTML = html;
      ac.classList.toggle('open', !!html);
      input.setAttribute('aria-expanded', html ? 'true' : 'false');
    }

    function pick(r) {
      if (!r || r.kind === 'loading') return;
      ac.classList.remove('open');
      input.blur();
      if (r.kind === 'stock') {
        remember({ kind: 'stock', id: r.s, n: r.n });
        openStock(r.s, 'search');
      } else if (r.kind === 'screen') {
        if (window.AltahaTrack) window.AltahaTrack('search_screen', {});
        navigate('research', 'query');
      } else if (r.t.href) {
        remember({ kind: 'tool', id: r.id });
        location.href = r.t.href;
      } else {
        if (r.t.tab) remember({ kind: 'tool', id: r.id });
        navigate(r.t.section, r.t.tab);
      }
      input.value = '';
      q = '';
    }

    function refresh() {
      sel = -1;
      q = input.value.trim();
      rows = build();
      paint();
    }

    var missTimer = null, missReported = '';
    input.addEventListener('input', function () {
      refresh();
      if (missTimer) clearTimeout(missTimer);
      missTimer = setTimeout(function () {
        if (!q || q.length < 2 || UNIVERSE === null) return;
        if (rows.some(function (r) { return r.kind === 'stock' || r.kind === 'tool'; })) return;
        if (q.toUpperCase() === missReported) return;
        missReported = q.toUpperCase();
        if (window.AltahaTrack) window.AltahaTrack('search_no_match', { query: q });
      }, 900);
    });
    input.addEventListener('focus', function () {
      document.body.classList.add('sh-searching');
      refresh();
    });
    input.addEventListener('keydown', function (e) {
      var live = rows.filter(function (r) { return r.kind !== 'loading'; }).length;
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, rows.length - 1); while (rows[sel] && rows[sel].kind === 'loading') sel++; paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, -1); paint(); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (sel >= 0 && rows[sel]) return pick(rows[sel]);
        // Enter on a typed symbol with nothing selected opens the best
        // company, as the box always has; failing a company, the best tool.
        var first = rows.filter(function (r) { return r.kind === 'stock'; })[0] ||
                    rows.filter(function (r) { return r.kind === 'tool'; })[0];
        if (first) return pick(first);
        if (q && live) return;
        if (q) openStock(q, 'search');
      } else if (e.key === 'Escape') { ac.classList.remove('open'); input.blur(); }
    });
    ac.addEventListener('mousedown', function (e) {
      var r = e.target.closest('.row[data-i]');
      if (r) { e.preventDefault(); pick(rows[+r.dataset.i]); }
    });
    input.addEventListener('blur', function () {
      setTimeout(function () {
        ac.classList.remove('open');
        input.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('sh-searching');
      }, 140);
    });

    // "/" and Ctrl/Cmd+K focus search, the two conventions people already know.
    document.addEventListener('keydown', function (e) {
      var k = (e.key || '').toLowerCase();
      var t = e.target;
      var typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
      if (k === 'k' && (e.metaKey || e.ctrlKey) && !e.altKey) { e.preventDefault(); focusSearch(); return; }
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || typing) return;
      e.preventDefault();
      focusSearch();
    });

    loadUniverse();
  }

  function focusSearch() {
    var input = document.getElementById('sh-q');
    if (!input) return;
    if (window.scrollY > 0 && window.matchMedia('(max-width:720px)').matches) window.scrollTo({ top: 0 });
    input.focus();
    input.select();
  }

  /* Redrawn whenever auth.js announces a change — signing in on the sign-in
     page and coming back should not need a reload to show it. */
  function paintAccount() {
    var a = document.getElementById('sh-account');
    if (!a || !window.AltahaAuth) return;
    var user = window.AltahaAuth.user();
    var d = document.querySelector('#sh-drawer .sh-dacc-name');
    if (d) d.textContent = user && user.email ? user.email : 'Sign in';
    if (user && user.email) {
      a.textContent = user.email.split('@')[0];
      a.title = 'Signed in as ' + user.email;
      a.setAttribute('aria-label', 'Account: ' + user.email);
    } else {
      a.textContent = 'Sign in';
      a.removeAttribute('title');
      a.setAttribute('aria-label', 'Sign in');
    }
  }

  /* ── Theme ───────────────────────────────────────────────────────────────── */

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  }
  function paintThemeBtn() {
    var b = document.getElementById('sh-theme');
    if (!b) return;
    var dark = currentTheme() === 'dark';
    b.innerHTML = dark
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>';
    b.setAttribute('aria-label', dark ? 'Switch to light appearance' : 'Switch to dark appearance');
  }
  function toggleTheme() {
    // Same attribute, same storage key and same event as premium.js, so the
    // charts and the segmented control stay in step with this button.
    var t = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('altaha-theme', t); } catch (e) {}
    window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } }));
    paintThemeBtn();
  }
  function wireTheme() {
    var b = document.getElementById('sh-theme');
    if (!b) return;
    paintThemeBtn();
    b.addEventListener('click', toggleTheme);
    window.addEventListener('altaha:theme', paintThemeBtn);
  }

  function wireScroll() {
    var last = 0;
    window.addEventListener('scroll', function () {
      var y = window.scrollY || 0;
      if ((y > 8) !== (last > 8) && CHROME) CHROME.classList.toggle('scrolled', y > 8);
      last = y;
    }, { passive: true });
  }

  /* ── The IST clock at the end of the tape ─────────────────────────────────
     The headline ribbon that used to own this clock is the Headlines card on
     the Today page now. */

  function startClock() {
    var clock = document.getElementById('sh-clock');
    if (!clock) return;
    function stamp() {
      try {
        clock.textContent = new Date().toLocaleTimeString('en-IN', {
          hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata'
        }) + ' IST';
      } catch (e) {}
    }
    stamp();
    setInterval(stamp, 30000);
  }

  /* ── The live ticker ─────────────────────────────────────────────────────── */

  var lastVals = {};

  function chipHTML(c) {
    var up = c.pct > 0, dn = c.pct < 0;
    var cls = up ? 'up' : (dn ? 'dn' : '');
    var arrow = up ? '▲' : (dn ? '▼' : '•');
    var pct = (c.pct == null || isNaN(c.pct)) ? '—'
      : (c.pct > 0 ? '+' : '') + Number(c.pct).toFixed(2) + '%';
    return '<a class="sh-chip" data-k="' + esc(c.key) + '" href="' +
      (c.link ? 'stock.html?ticker=' + encodeURIComponent(c.sym) : 'javascript:void 0') + '">' +
      '<span class="sym">' + esc(c.sym) + '</span>' +
      (c.level != null ? '<span class="lv tnum">' + esc(c.level) + '</span>' : '') +
      '<span class="ch tnum ' + cls + '"><span class="arw">' + arrow + '</span> ' + pct + '</span></a>';
  }

  function startTicker() {
    var rail = document.getElementById('sh-rail');
    if (!rail) return;

    function render(chips) {
      if (!chips.length) return;
      // Duplicated once so the marquee can translate exactly -50% and land on
      // an identical frame. Any other distance shows a seam.
      var html = chips.map(chipHTML).join('');
      rail.innerHTML = html + html;
      rail.style.setProperty('--sh-dur', Math.max(38, chips.length * 3.4) + 's');

      chips.forEach(function (c) {
        var prev = lastVals[c.key];
        if (prev !== undefined && c.pct !== prev) {
          var dir = c.pct > prev ? 'flash-up' : 'flash-dn';
          rail.querySelectorAll('[data-k="' + c.key + '"]').forEach(function (n) {
            n.classList.remove('flash-up', 'flash-dn');
            void n.offsetWidth;                 // restart the animation
            n.classList.add(dir);
          });
        }
        lastVals[c.key] = c.pct;
      });
    }

    function load() {
      var chips = [], idx = [], sec = null, status = null;
      get('/market', 11000).then(function (d) {
        idx = (d && d.indices) || [];
        status = (d && d.status) || null;
        (d && d.indices || []).forEach(function (i) {
          chips.push({ key: 'i:' + i.label, sym: i.label, level: i.level,
                       pct: i.change_pct, link: false });
        });
      }).catch(function () {}).then(function () {
        return get('/sector/overview?window=1D&stocks=1', 12000).catch(function () { return null; });
      }).then(function (d) {
        sec = d;
        var seen = {};
        ((d && d.rows) || []).forEach(function (row) {
          (row.stocks || []).forEach(function (s) {
            if (!s.symbol || seen[s.symbol]) return;
            seen[s.symbol] = 1;
            chips.push({ key: 's:' + s.symbol, sym: s.symbol, level: null,
                         pct: s.change_pct, link: true });
          });
        });
        // Biggest movers first — a ticker of the calmest names in the market
        // is a screensaver.
        chips.sort(function (a, b) {
          var ai = a.key.charAt(0) === 'i', bi = b.key.charAt(0) === 'i';
          if (ai !== bi) return ai ? -1 : 1;
          return Math.abs(b.pct || 0) - Math.abs(a.pct || 0);
        });
        render(chips.slice(0, 40));
        // One fetch, two consumers: the homepage board listens for this
        // instead of pulling /market and /sector/overview again on its own.
        // Kept on AltahaShell too, so a page that mounts after this read (the
        // Today door) can use it instead of asking again.
        try {
          window.AltahaShell = window.AltahaShell || {};
          window.AltahaShell.market = { indices: idx, sectors: sec, status: status };
          window.dispatchEvent(new CustomEvent('altaha:market',
            { detail: { indices: idx, sectors: sec, status: status } }));
        } catch (e) {}
      });
    }

    load();
    setInterval(function () { if (!document.hidden) load(); }, 60000);
    // Refresh on return, so coming back to the tab shows live prices rather
    // than whatever was on screen when you left.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) load();
    });
  }

  /* ── 3D primitives ────────────────────────────────────────────────────────
     Applied by class so any page can opt in without importing anything.     */

  function startTilt() {
    if (REDUCED) return;
    var MAX = 7;                             // degrees; past ~8 it reads as a gimmick
    document.addEventListener('pointermove', function (e) {
      var card = e.target.closest ? e.target.closest('.d3-card.tilt') : null;
      if (!card) return;
      var r = card.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width;
      var py = (e.clientY - r.top) / r.height;
      card.style.setProperty('--ry', ((px - 0.5) * 2 * MAX).toFixed(2) + 'deg');
      card.style.setProperty('--rx', ((0.5 - py) * 2 * MAX).toFixed(2) + 'deg');
      card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
      card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
    }, { passive: true });
    document.addEventListener('pointerleave', function (e) {
      var card = e.target.closest ? e.target.closest('.d3-card.tilt') : null;
      if (!card) return;
      card.style.setProperty('--rx', '0deg');
      card.style.setProperty('--ry', '0deg');
    }, true);
  }

  function startReveal() {
    var nodes = document.querySelectorAll('.reveal');
    if (!nodes.length) return;
    if (REDUCED || !('IntersectionObserver' in window)) {
      nodes.forEach(function (n) { n.classList.add('in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        // Stagger by position in the row so a grid assembles rather than
        // snapping in as one block.
        var i = +(en.target.dataset.i || 0);
        setTimeout(function () { en.target.classList.add('in'); }, Math.min(i, 8) * 55);
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    nodes.forEach(function (n) { io.observe(n); });
  }

  /* Count a number up to its value. Exposed because the homepage and the
     stock page both want it and neither should reimplement easing. */
  function countUp(node, to, decimals, ms) {
    to = Number(to);
    if (isNaN(to)) { node.textContent = '—'; return; }
    decimals = decimals == null ? 0 : decimals;
    // Preserve the public helper without displaying intermediate financial values.
    node.textContent = to.toFixed(decimals);
  }

  window.AltahaShell = window.AltahaShell || {};
  window.AltahaShell.countUp = countUp;
  window.AltahaShell.reveal = startReveal;
  window.AltahaShell.reduced = function () { return REDUCED; };
  window.AltahaShell.api = function () { return API; };
  window.AltahaShell.focusSearch = focusSearch;

  /* ── Boot ────────────────────────────────────────────────────────────────── */

  function start() {
    build();
    startClock();
    startTicker();
    startTilt();
    startReveal();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
