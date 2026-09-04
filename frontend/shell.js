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
    share:    '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v13"/>'
  };

  function svg(key) {
    return '<span class="sh-ico" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      (ICON[key] || '') + '</svg></span>';
  }

  /* ── The menu map ──────────────────────────────────────────────────────────
     Grouped into columns, which is the whole reason the old bar failed: eleven
     flat destinations tell a first-time visitor that everything matters
     equally, so nothing does. `tab` values are the ids nav.js already knows. */

  var MENU = [
    {
      id: 'screener', label: 'Analyse',
      cols: [
        { head: 'One stock', items: [
          { tab: 'screener', label: 'Score & ledger', icon: 'ledger', hint: 'Every point, with its arithmetic' },
          { tab: 'charts',   label: 'Charts',         icon: 'candles', hint: 'Drawings, Fibonacci, RSI, MACD' },
          { tab: 'results',  label: 'Results',        icon: 'document', hint: 'Latest quarterly numbers' }
        ]},
        { head: 'Altaha only', items: [
          { tab: 'special', label: 'Altaha Special', icon: 'target',
            hint: 'Delivery-weighted momentum — a signal only NSE publishes' }
        ]},
        { head: 'The market', items: [
          { tab: 'filings', label: 'Filings',  icon: 'bell', hint: 'Live exchange announcements' },
          { tab: 'deals',   label: 'Deals',    icon: 'exchange', hint: 'Who traded size, netted' },
          { tab: 'options', label: 'Options',  icon: 'layers', hint: 'Chain, OI and max pain' }
        ]}
      ]
    },
    {
      id: 'ideas', label: 'Ideas',
      cols: [
        { head: 'What the scan found', items: [
          { tab: 'ideas', label: "Today's shortlist", icon: 'bulb', hint: 'Ranked, with the setup named' },
          { tab: 'live',  label: 'Alerts',            icon: 'pulse', hint: 'Intraday scanner' }
        ]},
        { head: 'Does it work?', items: [
          { tab: 'tracker', label: 'Track record', icon: 'target', hint: 'Measured hit rate, not a highlight reel' }
        ]}
      ]
    },
    {
      id: 'portfolio', label: 'Portfolio',
      cols: [
        { head: 'Your book', items: [
          { tab: 'portfolio', label: 'Review', icon: 'bars', hint: 'Every holding, then the book as a whole' }
        ]},
        { head: 'Against your rules', items: [
          { tab: 'portfolio', label: 'Policy audit', icon: 'shield', hint: 'Breaches, with the arithmetic to close them' }
        ]}
      ]
    },
    { id: 'planner', label: 'Planner', cols: [
      { head: 'Household', items: [
        { tab: 'planner', label: 'Money planner', icon: 'plan', hint: 'The same lens, on your own finances' }
      ]}
    ]},
    { id: 'social', label: 'Social', cols: [
      { head: 'Publish', items: [
        { tab: 'social', label: 'Filings & news', icon: 'share', hint: 'Drafted, reviewed, ready to post' }
      ]}
    ]}
  ];

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

  function openStock(sym) {
    sym = String(sym || '').trim().toUpperCase();
    if (!sym) return;
    location.href = 'stock.html?ticker=' + encodeURIComponent(sym);
  }
  window.AltahaOpenStock = openStock;

  /* ── Build the chrome ────────────────────────────────────────────────────── */

  var CHROME = null;

  function build() {
    if (document.querySelector('.sh-chrome')) return;

    var chrome = el('div', 'sh-chrome');

    /* 1 · ribbon */
    var ribbon = el('div', 'sh-ribbon');
    ribbon.innerHTML =
      '<span class="sh-ribbon-tag"><i class="sh-dot"></i>Live</span>' +
      '<div class="sh-ribbon-slot" id="sh-slot"></div>' +
      '<span class="sh-ribbon-clock" id="sh-clock"></span>';

    /* 2 · ticker */
    var ticker = el('div', 'sh-ticker');
    ticker.setAttribute('aria-label', 'Live market prices');
    ticker.innerHTML = '<div class="sh-rail" id="sh-rail"></div>';

    /* 3 · menu bar */
    var bar = el('div', 'sh-bar');

    var brand = el('a', 'sh-brand');
    brand.href = 'index.html';
    brand.innerHTML = '<span class="mk">A</span><span class="nm">Altaha <i>Screener</i></span>';

    var nav = el('nav', 'sh-nav');
    nav.setAttribute('aria-label', 'Main');
    MENU.forEach(function (sec) {
      var b = el('button', 'sh-top');
      b.type = 'button';
      b.dataset.sec = sec.id;
      b.setAttribute('aria-expanded', 'false');
      b.setAttribute('aria-haspopup', 'true');
      b.innerHTML = esc(sec.label) +
        '<svg class="cv" width="10" height="10" viewBox="0 0 24 24" fill="none" ' +
        'stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg>';
      nav.appendChild(b);
    });

    var search = el('div', 'sh-search');
    search.innerHTML =
      '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/></svg>' +
      '<input id="sh-q" type="text" autocomplete="off" spellcheck="false" ' +
      'placeholder="Search a stock" aria-label="Search for a stock" />' +
      '<span class="kbd">/</span><div class="sh-ac" id="sh-ac" role="listbox"></div>';

    var right = el('div', 'sh-right');
    var themeBtn = el('button', 'sh-icon');
    themeBtn.type = 'button';
    themeBtn.id = 'sh-theme';
    themeBtn.setAttribute('aria-label', 'Switch appearance');
    var burger = el('button', 'sh-icon sh-burger');
    burger.type = 'button';
    burger.id = 'sh-burger';
    burger.setAttribute('aria-label', 'Menu');
    burger.setAttribute('aria-expanded', 'false');
    burger.innerHTML =
      '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>';
    right.appendChild(themeBtn);
    right.appendChild(burger);

    bar.appendChild(brand);
    bar.appendChild(nav);
    bar.appendChild(search);
    bar.appendChild(right);

    var megawrap = el('div', 'sh-megawrap');
    megawrap.id = 'sh-megawrap';

    chrome.appendChild(ribbon);
    chrome.appendChild(ticker);
    chrome.appendChild(bar);
    chrome.appendChild(megawrap);

    document.body.insertBefore(chrome, document.body.firstChild);

    var drawer = el('div', 'sh-drawer');
    drawer.id = 'sh-drawer';
    document.body.appendChild(drawer);

    document.body.classList.add('sh-on');
    CHROME = chrome;

    wireMenu(megawrap, drawer);
    wireSearch();
    wireTheme();
    wireScroll();
  }

  /* ── Mega menu ───────────────────────────────────────────────────────────── */

  // One builder for both the desktop panel and the mobile drawer, so an icon
  // can never appear in one and be missing from the other.
  function itemHTML(secId, it) {
    return '<button class="sh-item" type="button" data-sec="' + esc(secId) +
      '" data-tab="' + esc(it.tab) + '">' + svg(it.icon) +
      '<span class="sh-txt"><b>' + esc(it.label) + '</b>' +
      '<span>' + esc(it.hint) + '</span></span></button>';
  }

  function columnsHTML(sec) {
    return sec.cols.map(function (c) {
      return '<div class="sh-col"><h4>' + esc(c.head) + '</h4>' +
        c.items.map(function (it) { return itemHTML(sec.id, it); }).join('') + '</div>';
    }).join('');
  }

  function wireMenu(megawrap, drawer) {
    var panel = el('div', 'sh-mega');
    megawrap.appendChild(panel);
    var openId = null, closeTimer = null;

    function close() {
      openId = null;
      panel.classList.remove('open');
      document.querySelectorAll('.sh-top').forEach(function (b) {
        b.setAttribute('aria-expanded', 'false');
      });
    }
    function open(secId) {
      var sec = MENU.filter(function (s) { return s.id === secId; })[0];
      if (!sec) return;
      openId = secId;
      panel.innerHTML = columnsHTML(sec);
      panel.classList.add('open');
      document.querySelectorAll('.sh-top').forEach(function (b) {
        b.setAttribute('aria-expanded', b.dataset.sec === secId ? 'true' : 'false');
      });
    }

    document.querySelectorAll('.sh-top').forEach(function (b) {
      // Hover opens, because that is what a mega menu is for; click still
      // works and is what a keyboard and a touchscreen actually use.
      b.addEventListener('mouseenter', function () {
        clearTimeout(closeTimer);
        open(b.dataset.sec);
      });
      b.addEventListener('click', function (e) {
        e.preventDefault();
        if (openId === b.dataset.sec) { close(); navigate(b.dataset.sec, null); }
        else open(b.dataset.sec);
      });
      b.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') close();
      });
    });

    [panel, megawrap].forEach(function (n) {
      n.addEventListener('mouseenter', function () { clearTimeout(closeTimer); });
    });
    if (CHROME) {
      CHROME.addEventListener('mouseleave', function () {
        closeTimer = setTimeout(close, 180);
      });
    }
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    document.addEventListener('click', function (e) {
      if (!e.target.closest || (!e.target.closest('.sh-chrome'))) close();
    });

    panel.addEventListener('click', function (e) {
      var it = e.target.closest('.sh-item');
      if (!it) return;
      close();
      navigate(it.dataset.sec, it.dataset.tab);
    });

    /* Mobile drawer — the same map, stacked, so there is one source of truth
       for what the destinations are. */
    drawer.innerHTML = MENU.map(function (sec) {
      return '<div class="sh-col"><h4>' + esc(sec.label) + '</h4>' +
        sec.cols.map(function (c) {
          return c.items.map(function (it) { return itemHTML(sec.id, it); }).join('');
        }).join('') + '</div>';
    }).join('');

    var burger = document.getElementById('sh-burger');
    function setDrawer(on) {
      drawer.classList.toggle('open', on);
      burger.setAttribute('aria-expanded', on ? 'true' : 'false');
      document.body.style.overflow = on ? 'hidden' : '';
    }
    burger.addEventListener('click', function () {
      setDrawer(!drawer.classList.contains('open'));
    });
    drawer.addEventListener('click', function (e) {
      var it = e.target.closest('.sh-item');
      if (!it) return;
      setDrawer(false);
      navigate(it.dataset.sec, it.dataset.tab);
    });
  }

  /* ── Search + typeahead ──────────────────────────────────────────────────── */

  var UNIVERSE = null;

  function loadUniverse() {
    // Cached for a day. ~2,000 rows is far too much to refetch per keystroke,
    // and /universe already sets Cache-Control to say so.
    try {
      var raw = localStorage.getItem('altaha-universe');
      if (raw) {
        var o = JSON.parse(raw);
        if (o && o.day === new Date().toISOString().slice(0, 10) && o.rows && o.rows.length) {
          UNIVERSE = o.rows;
          return;
        }
      }
    } catch (e) {}
    get('/universe', 12000).then(function (d) {
      UNIVERSE = (d && d.rows) || [];
      try {
        localStorage.setItem('altaha-universe', JSON.stringify({
          day: new Date().toISOString().slice(0, 10), rows: UNIVERSE
        }));
      } catch (e) {}
    }).catch(function () { UNIVERSE = []; });
  }

  function match(q) {
    if (!UNIVERSE || !q) return [];
    q = q.toUpperCase();
    var starts = [], holds = [];
    for (var i = 0; i < UNIVERSE.length && starts.length + holds.length < 220; i++) {
      var r = UNIVERSE[i];
      var s = String(r.symbol || r[0] || '').toUpperCase();
      var n = String(r.name || r[1] || '').toUpperCase();
      if (s.indexOf(q) === 0) starts.push(r);
      else if (s.indexOf(q) > -1 || n.indexOf(q) > -1) holds.push(r);
    }
    return starts.concat(holds).slice(0, 9);
  }

  function wireSearch() {
    var input = document.getElementById('sh-q');
    var ac = document.getElementById('sh-ac');
    if (!input || !ac) return;
    var sel = -1, rows = [];

    function paint() {
      if (!rows.length) { ac.classList.remove('open'); ac.innerHTML = ''; return; }
      ac.innerHTML = rows.map(function (r, i) {
        var s = r.symbol || r[0] || '';
        var n = r.name || r[1] || '';
        return '<b class="row' + (i === sel ? ' sel' : '') + '" role="option" data-s="' +
          esc(s) + '"><span class="s">' + esc(s) + '</span>' +
          '<span class="n">' + esc(n) + '</span></b>';
      }).join('');
      ac.classList.add('open');
    }

    input.addEventListener('input', function () {
      sel = -1;
      rows = match(input.value.trim());
      paint();
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, rows.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, -1); paint(); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        var pick = (sel >= 0 && rows[sel]) ? (rows[sel].symbol || rows[sel][0]) : input.value.trim();
        openStock(pick);
      } else if (e.key === 'Escape') { ac.classList.remove('open'); input.blur(); }
    });
    ac.addEventListener('mousedown', function (e) {
      var r = e.target.closest('.row');
      if (r) { e.preventDefault(); openStock(r.dataset.s); }
    });
    input.addEventListener('blur', function () {
      setTimeout(function () { ac.classList.remove('open'); }, 120);
    });

    // "/" focuses search, the convention every data product on the web uses.
    document.addEventListener('keydown', function (e) {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      input.focus();
      input.select();
    });

    loadUniverse();
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
  function wireTheme() {
    var b = document.getElementById('sh-theme');
    if (!b) return;
    paintThemeBtn();
    b.addEventListener('click', function () {
      // Same attribute, same storage key and same event as premium.js, so the
      // charts and the segmented control stay in step with this button.
      var t = currentTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', t);
      try { localStorage.setItem('altaha-theme', t); } catch (e) {}
      window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } }));
      paintThemeBtn();
    });
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

  /* ── The headline ribbon ─────────────────────────────────────────────────── */

  function startRibbon() {
    var slot = document.getElementById('sh-slot');
    var clock = document.getElementById('sh-clock');
    if (!slot) return;
    var heads = [], idx = 0, showing = null;

    function tick() {
      if (!heads.length) return;
      var h = heads[idx % heads.length];
      idx++;
      var node = el('div', 'sh-head');
      node.innerHTML =
        '<span class="src">' + esc(h.pub) + '</span>' +
        '<a href="' + esc(h.url || '#') + '" target="_blank" rel="noopener noreferrer">' +
        esc(h.title) + '</a>' +
        (h.corr > 1 ? '<span class="corr">' + h.corr + ' outlets</span>' : '');
      slot.appendChild(node);
      // Two frames, not one: the browser needs to have committed the start
      // state before the transition to the end state means anything.
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { node.classList.add('on'); });
      });
      if (showing) {
        var old = showing;
        old.classList.remove('on');
        old.classList.add('out');
        setTimeout(function () { if (old.parentNode) old.parentNode.removeChild(old); }, 420);
      }
      showing = node;
    }

    function load() {
      get('/social/news/feed?limit=14&sort=latest', 11000).then(function (d) {
        var cs = (d && d.clusters) || [];
        heads = cs.map(function (c) {
          var L = c.lead || {};
          return {
            title: L.title || '',
            pub: L.publication || '',
            url: L.url || '',
            corr: c.corroboration || 1
          };
        }).filter(function (h) { return h.title; });
        if (heads.length && !showing) tick();
      }).catch(function () { /* ribbon stays empty rather than saying "error" */ });
    }

    function stamp() {
      if (!clock) return;
      try {
        clock.textContent = new Date().toLocaleTimeString('en-IN', {
          hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata'
        }) + ' IST';
      } catch (e) {}
    }

    load();
    stamp();
    setInterval(stamp, 30000);
    setInterval(load, 300000);
    if (!REDUCED) setInterval(tick, 7000);
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
      var chips = [];
      get('/market', 11000).then(function (d) {
        (d && d.indices || []).forEach(function (i) {
          chips.push({ key: 'i:' + i.label, sym: i.label, level: i.level,
                       pct: i.change_pct, link: false });
        });
      }).catch(function () {}).then(function () {
        return get('/sector/overview?window=1d', 12000).catch(function () { return null; });
      }).then(function (d) {
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
      });
    }

    load();
    setInterval(load, 60000);
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
    if (REDUCED) { node.textContent = to.toFixed(decimals); return; }
    var from = 0, t0 = null, dur = ms || 900;
    function frame(t) {
      if (t0 === null) t0 = t;
      var p = Math.min(1, (t - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      node.textContent = (from + (to - from) * eased).toFixed(decimals);
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  window.AltahaShell = {
    countUp: countUp,
    reveal: startReveal,
    reduced: function () { return REDUCED; },
    api: function () { return API; }
  };

  /* ── Boot ────────────────────────────────────────────────────────────────── */

  function start() {
    build();
    startRibbon();
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
