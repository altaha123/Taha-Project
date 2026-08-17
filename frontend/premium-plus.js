/* ============================================================================
   ALTAHA SCREENER — PREMIUM PLUS  v3
   ----------------------------------------------------------------------------
   Loads after premium.js. Separate file on purpose: if anything here misbehaves
   you delete one <script> line and keep the working v2 layer.

   Everything runs off a single interception of the /analyze response. The page
   already fetches that payload; re-requesting it for the profile card, the
   ledger grouping and the compare panel would have tripled the load on a free
   Render instance for data already in flight.

   CONTENTS
     1  Payload interception          7  Ledger — heat strip and grouping
     2  Company profile               8  Mobile tables to cards
     3  Typeahead search              9  Print / PDF export
     4  Recent stocks                10  Empty and error states
     5  Sticky context bar           11  Accessibility
     6  Inline vocabulary            12  Compare two stocks
============================================================================ */

(function () {
  'use strict';

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };

  /* API_BASE is a top-level const in the page's own script. Classic scripts
     share the global declarative scope, so it is readable here — but it is not
     on window, so `typeof` is the only safe way to ask. */
  var API = (typeof API_BASE !== 'undefined' && API_BASE)
          ? API_BASE : 'https://taha-project.onrender.com';

  var LAST = null;                       // most recent /analyze payload

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  /* ── 1. PAYLOAD INTERCEPTION ──────────────────────────────────────────────
     The response is cloned, so the page's own handler still consumes an
     unread body. Failures are swallowed: a bug in this file must never be
     able to break the analysis the user actually asked for. */

  var origFetch = window.fetch;
  window.fetch = function (input, init) {
    var p = origFetch.apply(this, arguments);
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (/\/analyze\?/.test(url)) {
      p.then(function (res) {
        if (!res || !res.ok) return;
        res.clone().json().then(function (d) {
          LAST = d;
          try { onPayload(d); } catch (e) {}
        }).catch(function () {});
      }).catch(function () {});
    }
    return p;
  };

  function onPayload(d) {
    profileCard(d);
    heatStrip(d);
    groupLedger(d);
    pushRecent(d);
    markVocab();
    mobiliseTables();
  }

  /* ── 2. COMPANY PROFILE ───────────────────────────────────────────────────
     The score answers "is this good". It does not answer "what is this", and
     a reader who cannot answer the second question has no business acting on
     the first. Sits directly under the verdict, before the trade plan. */

  function inr(n) {
    if (!n || !isFinite(n)) return null;
    if (n >= 1e12) return '\u20B9' + (n / 1e12).toFixed(2) + ' lakh Cr';
    if (n >= 1e7)  return '\u20B9' + Math.round(n / 1e7).toLocaleString('en-IN') + ' Cr';
    return '\u20B9' + Math.round(n).toLocaleString('en-IN');
  }

  function profileCard(d) {
    var old = $('#altaha-profile');
    if (old) old.remove();

    var p = d.profile;
    if (!p || !p.description) return;                 // fails quiet, not blank

    var anchor = $('.verdict');
    if (!anchor) return;

    var facts = [];
    if (p.sector)   facts.push(['Sector', p.sector]);
    if (p.industry) facts.push(['Industry', p.industry]);
    var cap = d.currency === 'INR' ? inr(p.market_cap)
            : (p.market_cap ? '$' + (p.market_cap / 1e9).toFixed(1) + 'B' : null);
    if (cap) facts.push(['Market cap', cap]);
    if (p.employees) facts.push(['Employees', Number(p.employees).toLocaleString('en-IN')]);

    var text = p.description.trim();
    var SHORT = 340;
    var clipped = text.length > SHORT;
    var head = clipped ? text.slice(0, text.lastIndexOf(' ', SHORT)) + '\u2026' : text;

    var box = el('section', 'apf', '');
    box.id = 'altaha-profile';
    box.innerHTML =
      '<div class="apf-head"><span class="sk">What the business does</span></div>' +
      '<p class="apf-text"><span class="apf-short">' + esc(head) + '</span>' +
      (clipped ? '<span class="apf-long" hidden>' + esc(text) + '</span>' : '') + '</p>' +
      (clipped ? '<button type="button" class="apf-more">Read the full description</button>' : '') +
      (facts.length ? '<dl class="apf-facts">' + facts.map(function (f) {
         return '<div><dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd></div>';
       }).join('') + '</dl>' : '') +
      '<p class="apf-src">' + esc(p.source || 'Description as published by the data provider') +
      (p.website ? ' \u00b7 <a href="' + esc(p.website) + '" target="_blank" rel="noopener noreferrer">Company site</a>' : '') +
      '</p>';

    anchor.parentNode.insertBefore(box, anchor.nextSibling);

    var more = box.querySelector('.apf-more');
    if (more) more.addEventListener('click', function () {
      var s = box.querySelector('.apf-short'), l = box.querySelector('.apf-long');
      var open = l.hasAttribute('hidden');
      if (open) { s.setAttribute('hidden', ''); l.removeAttribute('hidden'); more.textContent = 'Show less'; }
      else      { l.setAttribute('hidden', ''); s.removeAttribute('hidden'); more.textContent = 'Read the full description'; }
    });
  }

  /* ── 3. TYPEAHEAD ─────────────────────────────────────────────────────────
     The whole product was gated behind knowing an exact NSE symbol. Someone
     looking for Bajaj Finance types "BAJAJ" and got nothing back. This is the
     single largest usability gap in the site.

     The list is fetched once and cached for a day. If the /universe endpoint
     isn't deployed yet it falls back to the built-in seed below, so the
     feature works either way — just with less coverage. */

  var SEED = ('RELIANCE Reliance Industries|TCS Tata Consultancy Services|HDFCBANK HDFC Bank|' +
    'INFY Infosys|ICICIBANK ICICI Bank|BHARTIARTL Bharti Airtel|SBIN State Bank of India|' +
    'LT Larsen & Toubro|ITC ITC|HINDUNILVR Hindustan Unilever|BAJFINANCE Bajaj Finance|' +
    'BAJAJFINSV Bajaj Finserv|KOTAKBANK Kotak Mahindra Bank|AXISBANK Axis Bank|ASIANPAINT Asian Paints|' +
    'MARUTI Maruti Suzuki|TITAN Titan Company|SUNPHARMA Sun Pharmaceutical|ULTRACEMCO UltraTech Cement|' +
    'WIPRO Wipro|NESTLEIND Nestle India|ONGC Oil & Natural Gas|NTPC NTPC|POWERGRID Power Grid|' +
    'TATAMOTORS Tata Motors|TATASTEEL Tata Steel|JSWSTEEL JSW Steel|ADANIENT Adani Enterprises|' +
    'ADANIPORTS Adani Ports|HCLTECH HCL Technologies|TECHM Tech Mahindra|COALINDIA Coal India|' +
    'GRASIM Grasim Industries|HINDALCO Hindalco|CIPLA Cipla|DRREDDY Dr Reddys Laboratories|' +
    'DIVISLAB Divis Laboratories|EICHERMOT Eicher Motors|BAJAJ-AUTO Bajaj Auto|HEROMOTOCO Hero MotoCorp|' +
    'M&M Mahindra & Mahindra|BRITANNIA Britannia Industries|DABUR Dabur India|MARICO Marico|' +
    'GODREJCP Godrej Consumer|PIDILITIND Pidilite Industries|DMART Avenue Supermarts|' +
    'INDUSINDBK IndusInd Bank|BANKBARODA Bank of Baroda|PNB Punjab National Bank|CANBK Canara Bank|' +
    'IRCTC Indian Railway Catering|IRFC Indian Railway Finance|BEL Bharat Electronics|' +
    'HAL Hindustan Aeronautics|BHEL BHEL|SAIL Steel Authority of India|VEDL Vedanta|' +
    'ZOMATO Zomato|PAYTM One97 Communications|NYKAA FSN E-Commerce|POLICYBZR PB Fintech|' +
    'DLF DLF|GODREJPROP Godrej Properties|OBEROIRLTY Oberoi Realty|LODHA Macrotech Developers|' +
    'TRENT Trent|PAGEIND Page Industries|HAVELLS Havells India|VOLTAS Voltas|SIEMENS Siemens|' +
    'ABB ABB India|CUMMINSIND Cummins India|BOSCHLTD Bosch|SHREECEM Shree Cement|AMBUJACEM Ambuja Cements|' +
    'ACC ACC|TATAPOWER Tata Power|ADANIGREEN Adani Green Energy|IOC Indian Oil|BPCL BPCL|' +
    'HINDPETRO Hindustan Petroleum|GAIL GAIL India|LICI Life Insurance Corporation|' +
    'SBILIFE SBI Life Insurance|HDFCLIFE HDFC Life Insurance|ICICIPRULI ICICI Prudential Life|' +
    'ICICIGI ICICI Lombard|CHOLAFIN Cholamandalam Investment|MUTHOOTFIN Muthoot Finance|' +
    'BAJAJHLDNG Bajaj Holdings|SHRIRAMFIN Shriram Finance|LTIM LTIMindtree|PERSISTENT Persistent Systems|' +
    'COFORGE Coforge|MPHASIS Mphasis|OFSS Oracle Financial Services|CDSL Central Depository Services|' +
    'BSE BSE|MCX Multi Commodity Exchange|ANGELONE Angel One|CAMS Computer Age Management|' +
    'KFINTECH KFin Technologies|IEX Indian Energy Exchange|APOLLOHOSP Apollo Hospitals|' +
    'MAXHEALTH Max Healthcare|FORTIS Fortis Healthcare|LUPIN Lupin|AUROPHARMA Aurobindo Pharma|' +
    'TORNTPHARM Torrent Pharmaceuticals|ALKEM Alkem Laboratories|ZYDUSLIFE Zydus Lifesciences|' +
    'ASTRAL Astral|POLYCAB Polycab India|KEI KEI Industries|SUPREMEIND Supreme Industries|' +
    'BALKRISIND Balkrishna Industries|MRF MRF|APOLLOTYRE Apollo Tyres|TVSMOTOR TVS Motor|' +
    'ASHOKLEY Ashok Leyland|ESCORTS Escorts Kubota|BHARATFORG Bharat Forge|' +
    'AAPL Apple|MSFT Microsoft|NVDA NVIDIA|GOOGL Alphabet|AMZN Amazon|META Meta Platforms|' +
    'TSLA Tesla|NFLX Netflix|AMD Advanced Micro Devices|INTC Intel').split('|')
    .map(function (r) { var i = r.indexOf(' '); return { s: r.slice(0, i), n: r.slice(i + 1) }; });

  var UNIVERSE = SEED.slice();
  var CACHE_KEY = 'altaha-universe-v1';

  function loadUniverse() {
    try {
      var raw = localStorage.getItem(CACHE_KEY);
      if (raw) {
        var c = JSON.parse(raw);
        if (c && c.rows && c.rows.length && (Date.now() - c.at) < 864e5) {
          UNIVERSE = c.rows;
          return;
        }
      }
    } catch (e) {}

    origFetch(API + '/universe').then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.rows || !d.rows.length) return;
        UNIVERSE = d.rows;
        try { localStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), rows: d.rows })); }
        catch (e) { /* quota — the in-memory copy still works this session */ }
      }).catch(function () { /* seed list stands */ });
  }

  /* Ranked, not merely filtered. An exact symbol must outrank a company whose
     name happens to contain the same letters, or typing ITC surfaces forty
     companies with "itc" buried in a word before the one you meant. */
  function search(q, limit) {
    q = q.trim().toUpperCase();
    if (q.length < 1) return [];
    var out = [];
    for (var i = 0; i < UNIVERSE.length; i++) {
      var r = UNIVERSE[i];
      var s = r.s, n = (r.n || '').toUpperCase(), sc = 0;
      if (s === q) sc = 1000;
      else if (s.indexOf(q) === 0) sc = 600 - s.length;
      else if (n.indexOf(q) === 0) sc = 400 - n.length / 10;
      else if (n.indexOf(' ' + q) > -1) sc = 300;
      else if (s.indexOf(q) > -1) sc = 200;
      else if (n.indexOf(q) > -1) sc = 100;
      if (sc) out.push({ r: r, sc: sc });
    }
    out.sort(function (a, b) { return b.sc - a.sc; });
    return out.slice(0, limit || 7).map(function (o) { return o.r; });
  }

  function attachTypeahead(input, onPick) {
    if (!input) return;
    var wrap = input.closest('.searchrow') || input.parentNode;
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';

    var list = el('div', 'tah');
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.appendChild(list);

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('autocomplete', 'off');

    var rows = [], cur = -1;

    function close() {
      list.hidden = true; cur = -1;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }

    function highlight(text, q) {
      var i = text.toUpperCase().indexOf(q.toUpperCase());
      if (i < 0 || !q) return esc(text);
      return esc(text.slice(0, i)) + '<b>' + esc(text.slice(i, i + q.length)) +
             '</b>' + esc(text.slice(i + q.length));
    }

    function open(q) {
      rows = search(q);
      if (!rows.length) { close(); return; }
      list.innerHTML = rows.map(function (r, i) {
        return '<div class="tah-item" role="option" id="tah-' + i + '" data-i="' + i + '">' +
               '<span class="tah-sym">' + highlight(r.s, q) + '</span>' +
               '<span class="tah-name">' + highlight(r.n || '', q) + '</span></div>';
      }).join('');
      list.hidden = false;
      cur = -1;
      input.setAttribute('aria-expanded', 'true');
    }

    function move(step) {
      if (list.hidden) return;
      var items = $$('.tah-item', list);
      if (!items.length) return;
      if (cur > -1) items[cur].classList.remove('on');
      cur = (cur + step + items.length) % items.length;
      items[cur].classList.add('on');
      items[cur].scrollIntoView({ block: 'nearest' });
      input.setAttribute('aria-activedescendant', 'tah-' + cur);
    }

    function pick(i) {
      var r = rows[i];
      if (!r) return;
      input.value = r.s;
      close();
      onPick(r.s);
    }

    input.addEventListener('input', function () {
      var q = input.value.trim();
      if (q.length < 1) { close(); return; }
      open(q);
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) open(input.value.trim()); else move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') { if (!list.hidden && cur > -1) { e.preventDefault(); pick(cur); } else close(); }
      else if (e.key === 'Escape') { close(); }
    });

    list.addEventListener('mousedown', function (e) {
      var it = e.target.closest('.tah-item');
      if (!it) return;
      e.preventDefault();
      pick(parseInt(it.dataset.i, 10));
    });

    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) close();
    });
  }

  function typeahead() {
    loadUniverse();
    attachTypeahead($('#tk'), function (sym) {
      var go = $('#go'); if (go) go.click();
    });
    attachTypeahead($('#rtk'), function () {
      var go = $('#rgo'); if (go) go.click();
    });
    var tk = $('#tk');
    if (tk) tk.placeholder = 'Search a company or symbol \u2014 Reliance, HDFC Bank, NVDA\u2026';
  }

  /* ── 4. RECENT STOCKS ─────────────────────────────────────────────────── */

  var R_KEY = 'altaha-recent-v1';

  function readRecents() {
    try { return JSON.parse(localStorage.getItem(R_KEY)) || []; } catch (e) { return []; }
  }

  function pushRecent(d) {
    var s = (d.ticker || '').replace('.NS', '').replace('.BO', '');
    if (!s) return;
    var list = readRecents().filter(function (r) { return r.s !== s; });
    list.unshift({ s: s, n: d.name || s, v: d.verdict && d.verdict.score });
    list = list.slice(0, 8);
    try { localStorage.setItem(R_KEY, JSON.stringify(list)); } catch (e) {}
    drawRecents();
  }

  function drawRecents() {
    var host = $('#altaha-recents');
    if (!host) {
      var hint = $('.hint');
      if (!hint) return;
      host = el('div', '', '');
      host.id = 'altaha-recents';
      hint.parentNode.insertBefore(host, hint.nextSibling);
    }
    var list = readRecents();
    if (!list.length) { host.innerHTML = ''; return; }

    host.className = 'recents';
    host.innerHTML = '<span class="sk">Recent</span>' + list.map(function (r) {
      var b = r.v >= 72 ? 'b-strong' : r.v >= 55 ? 'b-good' : r.v >= 40 ? 'b-mixed' : 'b-weak';
      return '<button type="button" class="rc" data-s="' + esc(r.s) + '" title="' + esc(r.n) + '">' +
             esc(r.s) + (r.v != null ? '<i class="rc-dot ' + b + '"></i>' : '') + '</button>';
    }).join('') + '<button type="button" class="rc rc-clear" title="Clear recent">Clear</button>';

    host.onclick = function (e) {
      var b = e.target.closest('.rc');
      if (!b) return;
      if (b.classList.contains('rc-clear')) {
        try { localStorage.removeItem(R_KEY); } catch (err) {}
        drawRecents();
        return;
      }
      var tk = $('#tk'); if (!tk) return;
      tk.value = b.dataset.s;
      var go = $('#go'); if (go) go.click();
    };
  }

  /* ── 5. STICKY CONTEXT BAR ────────────────────────────────────────────────
     The result page runs long — verdict, plan, archetype, chart, levels,
     volume, shareholding, two ledgers. By the time you are reading a
     fundamental check you have lost the score, the price, and often which
     company you were looking at. */

  function contextBar() {
    var verdict = $('.verdict');
    if (!verdict || !('IntersectionObserver' in window)) return;

    var bar = el('div', 'ctxbar');
    bar.innerHTML =
      '<div class="ctx-in">' +
      '<span class="ctx-sym"></span>' +
      '<span class="ctx-px"></span>' +
      '<span class="ctx-spacer"></span>' +
      '<span class="ctx-lbl"></span>' +
      '<span class="ctx-score"></span>' +
      '</div>';
    document.body.appendChild(bar);

    bar.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
    });

    function fill() {
      var sym = $('#csym'), px = $('#cpx'), sc = $('#score'), lb = $('#vlabel');
      bar.querySelector('.ctx-sym').textContent = sym ? sym.textContent.split('·')[0].trim() : '';
      bar.querySelector('.ctx-px').textContent = px ? px.textContent.replace(/^Price\s*/, '') : '';
      bar.querySelector('.ctx-lbl').textContent = lb ? lb.textContent : '';
      var v = sc ? parseInt(sc.textContent.replace(/[^0-9]/g, ''), 10) : NaN;
      var s = bar.querySelector('.ctx-score');
      s.textContent = isFinite(v) ? v : '';
      s.className = 'ctx-score ' + (v >= 72 ? 'b-strong' : v >= 55 ? 'b-good'
                                  : v >= 40 ? 'b-mixed' : 'b-weak');
    }

    new IntersectionObserver(function (e) {
      var res = $('#result');
      var visible = res && res.style.display !== 'none';
      if (!e[0].isIntersecting && visible) { fill(); bar.classList.add('on'); }
      else bar.classList.remove('on');
    }, { threshold: 0, rootMargin: '-64px 0px 0px 0px' }).observe(verdict);
  }

  /* ── 6. INLINE VOCABULARY ─────────────────────────────────────────────────
     A glossary tab is where definitions go to be ignored. The definition
     should appear where the confusion happens. Terms are marked in the ledger
     and plain-summary text only — marking them everywhere turns the page into
     a field of dotted underlines. */

  var TERMS = {
    'RSI': 'Relative Strength Index. Measures how hard price has risen versus fallen over 14 sessions, on a 0\u2013100 scale. Above 70 is often called overbought, below 30 oversold \u2014 but in a strong trend a stock can sit above 70 for months.',
    'MACD': 'Moving Average Convergence Divergence. The gap between a fast and a slow average of price. When the gap is widening upward, momentum is building; when it narrows, momentum is fading.',
    'ADX': 'Average Directional Index. Measures how strong a trend is, not which way it points. Below 20 means price is choppy and directionless; above 25 means the trend has real force.',
    'ATR': 'Average True Range. The typical distance a stock travels in a day, in rupees. Used to place a stop beyond ordinary noise rather than at a round number.',
    'VWAP': 'Volume Weighted Average Price. The average price paid today, weighted by how much traded at each level. Institutions measure their fills against it.',
    'RVOL': 'Relative Volume. Today\u2019s volume compared with what this stock normally trades by this time of day. 3\u00d7 means three times its usual activity \u2014 something is happening.',
    'OBV': 'On-Balance Volume. A running total that adds the day\u2019s volume on up days and subtracts it on down days. When it rises with price, buying is genuine; when it falls while price holds, it is not.',
    'Bollinger': 'Bollinger Bands. A band drawn two standard deviations either side of a 20-day average. When the band narrows sharply, volatility has compressed \u2014 often before a large move.',
    'Supertrend': 'A band placed a multiple of ATR away from price. Which side price sits on is a simple, mechanical read of trend regime.',
    'ROCE': 'Return on Capital Employed. Operating profit divided by the capital the business runs on. It answers: for every rupee tied up in this company, how much does it earn?',
    'F-Score': 'Piotroski F-Score. Nine pass/fail accounting tests of profitability, leverage and efficiency, scored 0\u20139. Designed for manufacturers \u2014 several of its tests are meaningless for banks.',
    'G-Score': 'Mohanram G-Score. Six tests of earnings quality and growth durability, aimed at separating real growth from growth bought with accounting.',
    'DMA': 'Daily Moving Average. The average closing price over a number of sessions \u2014 50-DMA over fifty, 200-DMA over two hundred. Used to define trend.',
    'alpha': 'Return beyond the index over the identical window. A 9% gain while the market did 11% is negative alpha \u2014 the position lost against the alternative of simply owning the index.',
    'drawdown': 'The worst fall from a peak before any recovery. It measures what you would have had to sit through, which is usually what decides whether a person actually held on.',
    'R:R': 'Risk to reward. The distance to the target divided by the distance to the stop. At 1:2, a strategy is profitable even winning only four times in ten.',
    'liquidity': 'How easily you can buy or sell without moving the price yourself. Thin stocks look tradeable on screen and are not.',
    'promoter': 'The founding owners of an Indian listed company. A large promoter stake means their money falls with yours; a falling stake is worth asking questions about.'
  };

  var TERM_RE = new RegExp('\\b(' + Object.keys(TERMS)
    .sort(function (a, b) { return b.length - a.length; })
    .map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); })
    .join('|') + ')\\b', 'g');

  function markVocab() {
    var scopes = ['#tledger .learn', '#fledger .learn', '.plainv', '.sthesis', '#vsummary'];
    $$(scopes.join(',')).forEach(function (node) {
      if (node.dataset.vocab) return;
      node.dataset.vocab = '1';
      walk(node);
    });
  }

  function walk(node) {
    $$('*', node).concat([node]).forEach(function (n) {
      [].slice.call(n.childNodes).forEach(function (c) {
        if (c.nodeType !== 3) return;                       // text nodes only
        if (!TERM_RE.test(c.nodeValue)) return;
        TERM_RE.lastIndex = 0;
        var frag = document.createDocumentFragment();
        var last = 0, m;
        while ((m = TERM_RE.exec(c.nodeValue))) {
          frag.appendChild(document.createTextNode(c.nodeValue.slice(last, m.index)));
          var b = el('button', 'vterm', esc(m[1]));
          b.type = 'button';
          b.dataset.term = m[1];
          b.setAttribute('aria-label', m[1] + ' \u2014 what this means');
          frag.appendChild(b);
          last = m.index + m[1].length;
        }
        frag.appendChild(document.createTextNode(c.nodeValue.slice(last)));
        c.parentNode.replaceChild(frag, c);
      });
    });
  }

  function vocabPopover() {
    var pop = el('div', 'vpop');
    pop.hidden = true;
    pop.setAttribute('role', 'tooltip');
    document.body.appendChild(pop);

    function hide() { pop.hidden = true; }

    document.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.vterm') : null;
      if (!b) { hide(); return; }
      e.preventDefault();
      var def = TERMS[b.dataset.term];
      if (!def) return;
      pop.innerHTML = '<span class="vpop-t">' + esc(b.dataset.term) + '</span>' +
                      '<span class="vpop-d">' + esc(def) + '</span>';
      pop.hidden = false;
      var r = b.getBoundingClientRect();
      var w = Math.min(320, window.innerWidth - 24);
      pop.style.width = w + 'px';
      var left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
      pop.style.left = left + 'px';
      var below = r.bottom + 10;
      if (below + pop.offsetHeight > window.innerHeight - 12 && r.top > pop.offsetHeight + 20) {
        pop.style.top = (r.top - pop.offsetHeight - 10 + window.scrollY) + 'px';
      } else {
        pop.style.top = (below + window.scrollY) + 'px';
      }
    });

    window.addEventListener('scroll', hide, { passive: true });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  }

  /* ── 7. LEDGER — HEAT STRIP AND GROUPING ──────────────────────────────────
     Twenty-five collapsed rows is a wall, and the reader cannot see the shape
     of the evidence before deciding what to open. The strip shows the balance
     at a glance; the groups replace computation order with reading order. */

  function heatStrip(d) {
    [['#tledger', d.technical && d.technical.checks],
     ['#fledger', d.fundamental && d.fundamental.checks]].forEach(function (pair) {
      var host = $(pair[0]), checks = pair[1];
      if (!host || !checks || !checks.length) return;

      var old = host.previousElementSibling;
      if (old && old.classList && old.classList.contains('heat')) old.remove();

      var strip = el('div', 'heat', '');
      strip.setAttribute('role', 'group');
      strip.setAttribute('aria-label', 'Evidence at a glance');

      var pass = 0, part = 0, fail = 0;
      strip.innerHTML = checks.map(function (c, i) {
        var ratio = c.max ? c.points / c.max : 0;
        var k = ratio >= 0.99 ? 'h-pass' : ratio <= 0.001 ? 'h-fail' : 'h-part';
        if (k === 'h-pass') pass++; else if (k === 'h-fail') fail++; else part++;
        return '<button type="button" class="hseg ' + k + '" data-i="' + i + '" ' +
               'title="' + esc(c.name + ' \u2014 ' + c.points + '/' + c.max) + '"></button>';
      }).join('') +
      '<span class="heat-key"><i class="h-pass"></i>' + pass +
      ' <i class="h-part"></i>' + part + ' <i class="h-fail"></i>' + fail + '</span>';

      strip.addEventListener('click', function (e) {
        var seg = e.target.closest('.hseg');
        if (!seg) return;
        var rows = $$('details.row', host);
        var row = rows[parseInt(seg.dataset.i, 10)];
        if (!row) return;
        row.open = true;
        row.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
        row.classList.add('flash');
        setTimeout(function () { row.classList.remove('flash'); }, 1400);
      });

      host.parentNode.insertBefore(strip, host);
    });
  }

  var GROUPS = [
    ['Trend',       /Trend structure|Hull|Supertrend|ADX|52-week range/i],
    ['Momentum',    /RSI|MACD/i],
    ['Volatility',  /Bollinger|squeeze/i],
    ['Volume',      /Volume|Accumulation|On-Balance/i],
    ['Ownership',   /holding/i],
    ['Returns & leverage', /ROCE|Debt/i],
    ['Growth',      /Revenue growth/i],
    ['Valuation',   /Valuation|P\/E/i],
    ['Accounting quality', /F-Score/i],
    ['Growth quality',     /G-Score/i]
  ];

  function groupLedger(d) {
    [['#tledger', d.technical && d.technical.checks],
     ['#fledger', d.fundamental && d.fundamental.checks]].forEach(function (pair) {
      var host = $(pair[0]), checks = pair[1];
      if (!host || !checks || !checks.length) return;

      var rows = $$('details.row', host);
      if (rows.length !== checks.length) return;         // markup changed — bail

      var buckets = {};
      checks.forEach(function (c, i) {
        var g = 'Other';
        for (var k = 0; k < GROUPS.length; k++) {
          if (GROUPS[k][1].test(c.name)) { g = GROUPS[k][0]; break; }
        }
        (buckets[g] = buckets[g] || []).push({ row: rows[i], c: c });
      });

      var order = GROUPS.map(function (g) { return g[0]; }).concat(['Other']);
      var frag = document.createDocumentFragment();

      order.forEach(function (g) {
        var items = buckets[g];
        if (!items || !items.length) return;
        var got = items.reduce(function (a, x) { return a + x.c.points; }, 0);
        var max = items.reduce(function (a, x) { return a + x.c.max; }, 0);
        var h = el('div', 'lgroup',
          '<span class="lgroup-n">' + esc(g) + '</span>' +
          '<span class="lgroup-s">' + got + '<i> / ' + max + '</i></span>');
        frag.appendChild(h);
        items.forEach(function (x) { frag.appendChild(x.row); });
      });

      host.appendChild(frag);
    });
  }

  /* ── 8. MOBILE TABLES TO CARDS ────────────────────────────────────────────
     Wide tables on a phone are either a horizontal-scroll mess or unreadably
     compressed. Stamping each cell with its column header lets CSS restack
     them as labelled rows below 700px. */

  function mobiliseTables() {
    $$('table').forEach(function (t) {
      if (t.dataset.mob) return;
      var heads = $$('thead th', t).map(function (h) { return h.textContent.trim(); });
      if (!heads.length) return;
      t.dataset.mob = '1';
      t.classList.add('mtable');
      $$('tbody tr', t).forEach(function (tr) {
        $$('td', tr).forEach(function (td, i) {
          if (heads[i]) td.setAttribute('data-label', heads[i]);
        });
      });
    });
  }

  /* ── 9. PRINT / PDF ───────────────────────────────────────────────────────
     A CA's audience keeps records and sends documents to other people. The
     print stylesheet does the work; this only opens all the ledger rows first,
     because a PDF of collapsed <details> is a PDF of nothing. */

  function printExport() {
    var host = $('#auditbtn');
    if (!host || !host.parentNode) return;

    var b = el('button', 'act prbtn',
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" ' +
      'stroke-linejoin="round"><path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-5h20v5a2 2 0 0 1-2 2h-2"/>' +
      '<path d="M6 14h12v7H6z"/></svg>Save as PDF');
    b.type = 'button';

    b.addEventListener('click', function () {
      var audit = $('#auditwrap');
      var wasHidden = audit && audit.style.display === 'none';
      if (audit) audit.style.display = 'block';
      var closed = $$('details.row').filter(function (r) { return !r.open; });
      closed.forEach(function (r) { r.open = true; });

      window.addEventListener('afterprint', function restore() {
        window.removeEventListener('afterprint', restore);
        closed.forEach(function (r) { r.open = false; });
        if (wasHidden && audit) audit.style.display = 'none';
      });

      setTimeout(function () { window.print(); }, 120);
    });

    host.parentNode.insertBefore(b, host.nextSibling);
  }

  /* ── 10. EMPTY AND ERROR STATES ───────────────────────────────────────────
     A failed lookup is where a product either explains itself or feels broken.
     "Not found" becomes: what you typed, what to check, and the three nearest
     things it could have meant. */

  function states() {
    var box = $('#state');
    if (!box) return;

    new MutationObserver(function () {
      if (box.dataset.enriched === box.innerHTML) return;
      var txt = box.textContent || '';
      if (!/Couldn.t find|not found|404/i.test(txt)) return;

      var typed = ((($('#tk') || {}).value) || '').trim();
      var near = search(typed, 3).filter(function (r) { return r.s !== typed.toUpperCase(); });
      if (!near.length) return;

      var add = el('div', 'st-sugg',
        '<span class="sk">Did you mean</span>' + near.map(function (r) {
          return '<button type="button" class="rc" data-s="' + esc(r.s) + '">' +
                 esc(r.s) + ' <i>' + esc(r.n || '') + '</i></button>';
        }).join(''));

      add.addEventListener('click', function (e) {
        var b = e.target.closest('.rc'); if (!b) return;
        var tk = $('#tk'); if (!tk) return;
        tk.value = b.dataset.s;
        var go = $('#go'); if (go) go.click();
      });

      box.appendChild(add);
      box.dataset.enriched = box.innerHTML;
    }).observe(box, { childList: true, subtree: true, characterData: true });
  }

  /* ── 11. ACCESSIBILITY ────────────────────────────────────────────────────
     The tabs carry role="tablist" but no arrow-key navigation and no
     aria-controls, which is the half of the pattern a screen reader actually
     uses. Also adds a skip link and marks the decorative candle field hidden. */

  function a11y() {
    var link = el('a', 'skiplink', 'Skip to the screener');
    link.href = '#tk';
    document.body.insertBefore(link, document.body.firstChild);

    var VIEWS = { 'tab-screener': 'view-screener', 'tab-ideas': 'view-ideas',
                  'tab-filings': 'view-filings', 'tab-live': 'view-live',
                  'tab-portfolio': 'view-portfolio', 'tab-tracker': 'view-tracker',
                  'tab-results': 'view-results', 'tab-options': 'view-options',
                  'tab-vocab': 'view-vocab' };

    Object.keys(VIEWS).forEach(function (id) {
      var btn = document.getElementById(id), view = document.getElementById(VIEWS[id]);
      if (!btn || !view) return;
      btn.setAttribute('aria-controls', VIEWS[id]);
      view.setAttribute('role', 'tabpanel');
      view.setAttribute('aria-labelledby', id);
    });

    var tabs = $$('.tabs > .tab');
    tabs.forEach(function (t, i) {
      t.addEventListener('keydown', function (e) {
        var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        if (!d) return;
        e.preventDefault();
        var n = tabs[(i + d + tabs.length) % tabs.length];
        n.focus(); n.click();
      });
    });

    var cnd = $('.hero-candles');
    if (cnd) cnd.setAttribute('aria-hidden', 'true');
  }

  /* ── 12. COMPARE ──────────────────────────────────────────────────────────
     The most-asked-for feature in every screener, and the one where this
     engine has an advantage nobody else does: it can show which specific
     check differs, not just which total is larger.

     Both sides are fetched fresh rather than reusing the on-screen payload,
     so the two are always scored against the same moment. */

  function compare() {
    var anchor = $('.sched');
    if (!anchor) return;

    var box = el('section', 'cmp', '');
    box.id = 'altaha-compare';
    box.innerHTML =
      '<button type="button" class="act cmp-open">Compare with another stock</button>' +
      '<div class="cmp-panel" hidden>' +
      '  <div class="cmp-bar">' +
      '    <input class="cmp-input" placeholder="Second stock \u2014 symbol or company" ' +
      '           autocomplete="off" spellcheck="false" aria-label="Second stock to compare">' +
      '    <button type="button" class="act solid cmp-go">Compare</button>' +
      '    <button type="button" class="act cmp-close">Close</button>' +
      '  </div>' +
      '  <div class="cmp-out"></div>' +
      '</div>';

    anchor.parentNode.insertBefore(box, anchor.nextSibling);

    var panel = box.querySelector('.cmp-panel');
    var input = box.querySelector('.cmp-input');
    var out   = box.querySelector('.cmp-out');

    box.querySelector('.cmp-open').addEventListener('click', function () {
      panel.hidden = false;
      this.style.display = 'none';
      input.focus();
      attachTypeahead(input, function () { run(); });
    });
    box.querySelector('.cmp-close').addEventListener('click', function () {
      panel.hidden = true;
      box.querySelector('.cmp-open').style.display = '';
      out.innerHTML = '';
    });
    box.querySelector('.cmp-go').addEventListener('click', run);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !$('.tah', box) ) run();
    });

    function get(sym) {
      return origFetch(API + '/analyze?ticker=' + encodeURIComponent(sym))
        .then(function (r) {
          if (!r.ok) throw new Error(r.status === 404 ? 'not found' : 'unavailable');
          return r.json();
        });
    }

    function run() {
      var b = input.value.trim();
      var a = LAST && LAST.ticker;
      if (!b) return;
      if (!a) { out.innerHTML = '<p class="cmp-msg">Analyse a stock first, then compare.</p>'; return; }

      out.innerHTML = '<p class="cmp-msg">Scoring both against the same moment\u2026</p>';

      Promise.all([get(a), get(b)]).then(function (both) {
        draw(both[0], both[1]);
      }).catch(function (err) {
        out.innerHTML = '<p class="cmp-msg">Couldn\u2019t score \u201C' + esc(b) +
          '\u201D \u2014 ' + esc(err.message || 'try again') +
          '. Check the symbol, or pick one from the suggestions.</p>';
      });
    }

    function cell(v) { return v == null ? '\u2014' : v; }

    function draw(A, B) {
      function bandOf(v) {
        return v >= 72 ? 'b-strong' : v >= 55 ? 'b-good' : v >= 40 ? 'b-mixed' : 'b-weak';
      }
      function head(d) {
        var v = d.verdict.score;
        return '<div class="cmp-col">' +
          '<div class="cmp-name">' + esc(d.name) + '</div>' +
          '<div class="cmp-sym">' + esc(d.ticker) + '</div>' +
          '<div class="cmp-score ' + bandOf(v) + '">' + v + '</div>' +
          '<div class="cmp-lbl">' + esc(d.verdict.label) + '</div>' +
          '<div class="cmp-sub"><span>Technical <b>' + cell(d.technical.score) + '</b></span>' +
          '<span>Fundamental <b>' + cell(d.fundamental.score) + '</b></span></div>' +
          '</div>';
      }

      // Where the two actually disagree — the part no other screener can show
      var map = {};
      (A.technical.checks || []).concat(A.fundamental.checks || []).forEach(function (c) {
        map[c.name] = { a: c, b: null };
      });
      (B.technical.checks || []).concat(B.fundamental.checks || []).forEach(function (c) {
        if (map[c.name]) map[c.name].b = c; else map[c.name] = { a: null, b: c };
      });

      var diffs = Object.keys(map).map(function (k) {
        var p = map[k];
        if (!p.a || !p.b || !p.a.max) return null;
        var d = (p.a.points / p.a.max) - (p.b.points / p.b.max);
        return Math.abs(d) < 0.01 ? null
          : { name: k, d: d, a: p.a.points + '/' + p.a.max, b: p.b.points + '/' + p.b.max };
      }).filter(Boolean).sort(function (x, y) { return Math.abs(y.d) - Math.abs(x.d); }).slice(0, 8);

      out.innerHTML =
        '<div class="cmp-heads">' + head(A) + '<div class="cmp-v">vs</div>' + head(B) + '</div>' +
        (diffs.length
          ? '<div class="cmp-diff"><span class="sk">Where they differ most</span>' +
            diffs.map(function (r) {
              return '<div class="cmp-row">' +
                '<span class="cmp-a ' + (r.d > 0 ? 'win' : '') + '">' + r.a + '</span>' +
                '<span class="cmp-k">' + esc(r.name) + '</span>' +
                '<span class="cmp-b ' + (r.d < 0 ? 'win' : '') + '">' + r.b + '</span>' +
                '</div>';
            }).join('') + '</div>'
          : '<p class="cmp-msg">These two pass and fail the same checks \u2014 the totals differ only by degree.</p>') +
        '<p class="cmp-note">Both scored at the same moment. A comparison is not a ranking: ' +
        'two businesses in different sectors are measured against thresholds that suit ' +
        'one better than the other.</p>';
    }
  }

  /* ── BOOT ─────────────────────────────────────────────────────────────── */

  function boot() {
    [typeahead, drawRecents, contextBar, vocabPopover, printExport,
     states, a11y, compare, mobiliseTables]
      .forEach(function (fn) { try { fn(); } catch (e) {} });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
