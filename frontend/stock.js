/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — stock.js
   Renders one company at its own URL: stock.html?ticker=RELIANCE

   WHAT THIS PAGE IS FOR
   Everything a reader looks a company up for, in one place and in a fixed
   order: what it is worth, how its price has moved, how it scores and why,
   who owns it, what it earns, how it compares with its peers, how much of its
   trading is delivered, and what is being reported and filed about it.

   ONE SCORE, AND ITS ARITHMETIC
   The page used to show three scores that did not add up to each other: the
   Altaha Score, and under it a technical and a fundamental score whose checks
   were listed as "the ledger" although none of their points go into the
   headline. The Score section now shows the headline's own arithmetic, taken
   from the payload it came from: each pillar's rank among peers, its weight,
   the points it added, and how far the total was pulled toward 50 for what
   could not be measured. The older checks are still there, named as what they
   are.

   WHAT IT DELIBERATELY DOES NOT RENDER
   No target, no entry, no stop, no instruction of any kind. The levels are
   arithmetic on the price series. Issuing recommendations to the public in
   India requires SEBI registration; that is the constraint the whole product
   is built inside.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function num(v, d) {
    if (v == null || v === '' || isNaN(Number(v))) return null;
    return Number(Number(v).toFixed(d == null ? 2 : d));
  }
  function money(v, cur) {
    var n = num(v, 2);
    if (n == null) return '—';
    var sym = cur === 'INR' ? '₹' : (cur === 'USD' ? '$' : '');
    return sym + n.toLocaleString(cur === 'INR' ? 'en-IN' : 'en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pct(v, d) {
    var n = num(v, d == null ? 2 : d);
    if (n == null) return '—';
    return (n > 0 ? '+' : '') + n + '%';
  }
  function tone(v) { return v > 0 ? 'up' : (v < 0 ? 'dn' : ''); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function track(name, props) { if (window.AltahaTrack) window.AltahaTrack(name, props || {}); }

  function param(k) {
    try { return new URLSearchParams(location.search).get(k); } catch (e) { return null; }
  }

  /* A link somebody else wrote is only ever followed over http or https. The
     news and filings rows carry addresses from a search result and from the
     exchange, and neither is allowed to hand this page a script. */
  function safeUrl(u) {
    u = String(u == null ? '' : u).trim();
    return /^https?:\/\/[^\s<>"']+$/i.test(u) ? u : '';
  }

  /* ?ticker=TCS on the static page, /stock-TCS on the one the API sends
     (clean-url.js reads both). The fallback is for a page that loads this
     file without that one. */
  var TICKER = (window.AltahaPageTicker ? window.AltahaPageTicker() : (param('ticker') || ''))
    .trim().toUpperCase();
  var BASE = TICKER.replace(/\.(NS|BO)$/, '');
  /* Set by the API on /stock-TCS, where the title, the description and the
     canonical address are already in the HTML and are the ones to keep. */
  var SSR = window.ALTAHA_SSR || null;

  /* The page's one copy of /analyze, and the holding period the Score section
     is showing. Every horizon's score is in that one response, so switching
     between them asks nobody. */
  var DATA = null;
  var HZ = 'position';

  function getJSON(path) {
    return fetch(API + path).then(function (r) {
      if (!r.ok) throw new Error('down');
      return r.json();
    });
  }

  /* Another company's page, at the same kind of address this one has. */
  function stockHref(sym) {
    return /\/stock-[^\/]+\/?$/.test(location.pathname)
      ? '/stock-' + encodeURIComponent(sym)
      : 'stock.html?ticker=' + encodeURIComponent(sym);
  }

  /* ── When ────────────────────────────────────────────────────────────────
     "3h ago" for today and yesterday, a date after that. A headline's age is
     most of what a reader wants from its timestamp. */
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function ago(iso) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    var m = Math.round((Date.now() - t) / 60000);
    if (m < 0) m = 0;
    if (m < 60) return (m || 1) + 'm ago';
    if (m < 48 * 60) return Math.round(m / 60) + 'h ago';
    if (m < 14 * 24 * 60) return Math.round(m / 1440) + 'd ago';
    return shortDate(iso);
  }
  function shortDate(iso) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    // Shown as an Indian date whatever the reader's clock says.
    var d = new Date(t + 5.5 * 3600 * 1000);
    var now = new Date(Date.now() + 5.5 * 3600 * 1000);
    return d.getUTCDate() + ' ' + MON[d.getUTCMonth()] +
      (d.getUTCFullYear() !== now.getUTCFullYear() ? ' ' + d.getUTCFullYear() : '');
  }

  /* ── States ──────────────────────────────────────────────────────────────── */

  /* The shape of the page while it loads, not a paragraph about the server.
     The one sentence appears only if the wait runs long, which is when a
     reader starts wondering whether anything is happening. */
  var slowTimer = null;
  function loading() {
    $('state').innerHTML =
      '<div class="stk-loading" aria-busy="true" aria-label="Loading">' +
        '<div class="skel sk-bar"></div>' +
        '<div class="sk-grid"><div class="skel sk-card tall"></div><div class="skel sk-card"></div>' +
        '<div class="skel sk-card"></div><div class="skel sk-card tall"></div></div>' +
        '<p class="sk-note" id="sk-note" hidden>Waking the engine. This takes about thirty seconds after a quiet spell.</p>' +
      '</div>';
    slowTimer = setTimeout(function () { var n = $('sk-note'); if (n) n.hidden = false; }, 4500);
  }
  function failed(msg) {
    clearTimeout(slowTimer);
    $('state').innerHTML =
      '<div class="stk-state"><div class="big">' + esc(msg) + '</div>' +
      '<div><a href="./" style="color:var(--gold)">Back to the screener</a></div></div>';
  }

  /* ── Logos ───────────────────────────────────────────────────────────────
     A company's initials on a tinted tile, always; and over it the company's
     own mark, when its website is known and the image actually loads.

     The initials are not a fallback bolted on afterwards. They are what is
     drawn first, so a logo that is slow, blocked or missing costs nothing:
     the tile is already there and already identifies the company. The mark is
     asked for from the company's own domain through a favicon service, and is
     kept only if it comes back at a usable size. That service answers an
     unknown domain with a 16-pixel placeholder rather than an error, and a
     blurred globe beside a company's name is worse than its initials.

     no-referrer, so the service is told which domain's icon is wanted and not
     which page wanted it. */
  var HUES = [38, 152, 205, 268, 330, 18, 95, 232, 178, 300];
  function hueOf(sym) {
    var h = 0, s = String(sym || '');
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return HUES[h % HUES.length];
  }
  function initials(name, sym) {
    var words = String(name || '').replace(/[^A-Za-z0-9& ]+/g, ' ').trim().split(/\s+/)
      .filter(function (w) { return w && !/^(the|of|and|ltd|limited|india|&)$/i.test(w); });
    var out = words.length >= 2 ? words[0].charAt(0) + words[1].charAt(0)
      : (words[0] || String(sym || '')).slice(0, 2);
    return out.toUpperCase() || '·';
  }
  function logoTag(sym, name, domain, size) {
    return '<span class="lg' + (size ? ' lg-' + size : '') + '" data-sym="' + esc(sym) +
      '" data-name="' + esc(name || '') + '" data-domain="' + esc(domain || '') +
      '" aria-hidden="true"></span>';
  }
  function paintLogo(node, sym, name, domain) {
    if (!node) return;
    node.textContent = '';
    node.classList.remove('has-img');
    node.style.setProperty('--lg-h', hueOf(sym));
    var m = document.createElement('span');
    m.className = 'lg-m';
    m.textContent = initials(name, sym);
    node.appendChild(m);
    domain = String(domain || '').toLowerCase();
    if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(domain)) return;
    var img = new Image();
    img.alt = '';
    img.decoding = 'async';
    img.referrerPolicy = 'no-referrer';
    img.onload = function () {
      if (img.naturalWidth < 24 || !node.isConnected) return;
      node.appendChild(img);
      node.classList.add('has-img');
    };
    img.src = 'https://www.google.com/s2/favicons?sz=128&domain=' + encodeURIComponent(domain);
  }
  function hydrateLogos(root) {
    [].slice.call((root || document).querySelectorAll('.lg[data-sym]')).forEach(function (n) {
      if (n.firstChild) return;
      paintLogo(n, n.dataset.sym, n.dataset.name, n.dataset.domain);
    });
  }

  /* ── Identity ────────────────────────────────────────────────────────────── */

  function paintHead(d) {
    var base = String(d.ticker || TICKER).replace(/\.(NS|BO)$/, '');
    if (!SSR) {
      document.title = base + ' — ' + (d.name || 'Stock') + ' | Altaha Screener';
      canonical(d, base);
    }
    $('crumb').textContent = base;
    $('nm').textContent = d.name || base;

    var tags = [];
    if (d.exchange) tags.push(d.exchange);
    tags.push(base);
    if (d.profile && d.profile.sector) tags.push(d.profile.sector);
    if (d.profile && d.profile.industry) tags.push(d.profile.industry);
    $('tags').innerHTML = tags.map(function (t) {
      return '<span class="stk-tag">' + esc(t) + '</span>';
    }).join('');

    $('px').textContent = money(d.price, d.currency);
    // The daily change is not in /analyze, so it is filled by the chart call
    // rather than invented here. An empty field beats a wrong one.
    $('chg').textContent = '';

    var domain = (d.logo && d.logo.domain) || '';
    paintLogo($('logo'), base, d.name, domain);
    paintLogo($('mini-logo'), base, d.name, domain);
    $('mini-sym').textContent = base;
    $('mini-px').textContent = money(d.price, d.currency);
  }

  /* This address and /stock-TCS show the same company. A search engine that
     finds both is told which one to keep: the one with the figures in its
     HTML. Only for an NSE listing, the only kind that has such a page, and
     only on the live site, the only place that address exists. */
  function canonical(d, base) {
    if (d.exchange !== 'NSE' || document.querySelector('link[rel="canonical"]')) return;
    if (!/(^|\.)altahascreener\.in$/.test(location.hostname)) return;
    var link = document.createElement('link');
    link.rel = 'canonical';
    link.href = location.origin + '/stock-' + encodeURIComponent(base);
    document.head.appendChild(link);
  }

  /* Whether this is a lender. A bank's deposits are its raw material, so its
     debt to equity and its return on capital employed do not mean what they
     mean for a manufacturer, and the page leaves both out for one. */
  function isLender(d) {
    var m = (d.business_model && d.business_model.key) ||
      (d.scoring && d.scoring.model && d.scoring.model.key) || '';
    return m === 'lender';
  }

  /* ── Score ───────────────────────────────────────────────────────────────
     The Altaha Score is a rank, not a mark out of a hundred for effort. Each
     factor is measured against the company's peers and becomes a percentile;
     factors average into pillars; pillars are weighted for the kind of
     business and the holding period; and the weighted sum is pulled toward 50
     in proportion to how much could not be measured. All four steps are in
     the payload, and this section prints them in that order, so the number at
     the top is the last line of arithmetic the reader can follow down the
     page rather than a figure to be taken on trust.

     THE WORD BESIDE IT comes from the API (`band`), which reads the site's
     one scale. These scores bunch around 50 by construction, so a scale that
     waits for 72 to say "strong" almost never says it; the old labels here
     did exactly that, and read "MIXED" for most of the market. The cuts below
     are only for an API that has not been deployed with `band` yet. */

  var PILLARS = {
    quality:            ['Business quality',   'Profitability, and how steady the profits are'],
    growth:             ['Growth',             'Sales, profit and margin against a year ago'],
    acceleration:       ['Acceleration',       'Whether that growth is speeding up or slowing'],
    value:              ['Valuation',          'Earnings against the price paid for them'],
    financial_strength: ['Financial strength', 'Debt, and profit against the interest on it'],
    momentum:           ['Price trend',        'The twelve-month trend and closeness to the high'],
    risk:               ['Stability',          'How calm the price has been'],
    participation:      ['Trading interest',   'Turnover against the stock’s own history']
  };
  var PILLAR_ORDER = ['quality', 'growth', 'acceleration', 'value', 'financial_strength',
                      'momentum', 'risk', 'participation'];
  function pillarName(k) { return (PILLARS[k] || [String(k).replace(/_/g, ' ')])[0]; }

  /* The engine's factor labels are written for the methodology document
     ("Negative dispersion of bounded PAT growth"). These say the same thing
     to somebody who has not read it. */
  var FACTORS = {
    momentum_12_1: '12-month price momentum',
    trend_quality: 'Steadiness of the trend',
    high_52w: 'Closeness to the 52-week high',
    reversal_5d: 'Last week’s move, reversed',
    low_volatility: 'Low price volatility',
    volume_shock: 'Turnover against its own history',
    earnings_yield: 'Earnings yield',
    cycle_earnings_yield: 'Earnings yield on three-year median profit',
    earnings_growth: 'Profit growth, year on year',
    revenue_growth: 'Revenue growth, year on year',
    margin_trend: 'Margin change, year on year',
    margin_level: 'Operating margin',
    return_on_assets: 'Return on assets',
    earnings_consistency: 'Consistency of profit growth',
    other_income_quality: 'Profit not reliant on other income',
    eps_acceleration: 'EPS growth speeding up',
    revenue_acceleration: 'Revenue growth speeding up',
    margin_acceleration: 'Margin gains speeding up',
    earnings_surprise: 'Latest EPS against its own history',
    low_leverage: 'Low debt to equity',
    interest_coverage: 'Interest cover',
    interest_coverage_trend: 'Interest cover, change in a year'
  };
  function factorName(e) { return FACTORS[e.factor] || e.label || e.factor; }

  var DEFAULT_CUTS = [[60, 'Strong'], [55, 'Good'], [40, 'Average'], [33, 'Weak'], [0, 'Poor']];
  function bandOf(score, sc, d) {
    if (score == null) return '';
    if (sc && sc.band) return sc.band;
    var cuts = (d && d.score_bands && d.score_bands.bands)
      ? d.score_bands.bands.map(function (b) { return [b.floor, b.label]; }) : DEFAULT_CUTS;
    for (var i = 0; i < cuts.length; i++) if (score >= cuts[i][0]) return cuts[i][1];
    return cuts[cuts.length - 1][1];
  }

  function scoringOf(d) { return (d.horizons && d.horizons[HZ]) || d.scoring || {}; }
  function scoreOf(d, sc) {
    if (sc.score != null) return sc.score;
    // An API from before v4 sent its score in `verdict`.
    return d.altaha_score_v4 ? null
      : (d.verdict && d.verdict.score != null ? d.verdict.score : null);
  }
  function rankOf(d) {
    if (d.percentiles && d.percentiles[HZ] != null) return d.percentiles[HZ];
    return (HZ === 'position' && d.percentile != null) ? d.percentile : null;
  }
  function sentence(t) {
    t = String(t || '').trim();
    if (!t) return '';
    return /[.!?]$/.test(t) ? t : t + '.';
  }
  function niceDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m ? Number(m[3]) + ' ' + MON[Number(m[2]) - 1] + ' ' + m[1] : '';
  }
  function fig(v) {
    var n = Number(v);
    if (v == null || isNaN(n)) return '—';
    var a = Math.abs(n), d = a >= 100 ? 0 : (a >= 10 ? 1 : 2);
    // A reading that rounds to nothing is nothing, not "-0".
    if (Number(n.toFixed(d)) === 0) n = 0;
    return n.toLocaleString('en-IN', { maximumFractionDigits: d });
  }

  /* Bars that grow to their value. Set a frame later so the browser has the
     zero-width state to animate from; a bar inside a hidden pane is set again
     when its pane is shown. */
  function growBars(root) {
    if (!root) return;
    var bars = [].slice.call(root.querySelectorAll('[data-w]'));
    if (REDUCED) { bars.forEach(function (b) { b.style.width = clamp(+b.dataset.w, 0, 100) + '%'; }); return; }
    bars.forEach(function (b) { b.style.width = '0%'; });
    requestAnimationFrame(function () { requestAnimationFrame(function () {
      bars.forEach(function (b, i) {
        b.style.transitionDelay = Math.min(i * 45, 400) + 'ms';
        b.style.width = clamp(+b.dataset.w, 0, 100) + '%';
      });
    }); });
  }

  function paintScore(d) {
    var sc = scoringOf(d);
    var score = scoreOf(d, sc);
    var band = bandOf(score, sc, d);

    // The API says which kind of "no score" this is — being scored right now,
    // no peer cohort for this market, or no scan yet — and each one asks
    // something different of the reader.
    $('scorelb').textContent = score == null ? (sc.label || 'NOT SCORED') : band.toUpperCase();
    $('dial').dataset.score = score == null ? '' : score;
    drawDial(false);

    paintHorizons(d);
    paintScoreSay(d, sc, score);
    paintAddsUp(d, sc, score);
    paintDrivers(d, score);
    paintFactors(d, sc, score);
    paintScoreChip(d, score, band);
    paintOverviewScore(d, sc, score, band);
  }

  /* The dial. Drawn when the score arrives, and again, from empty, the first
     time its section is opened: an arc that swept round inside a hidden pane
     has finished before anybody could see it. */
  function drawDial(replay) {
    var dial = $('dial'), arc = $('arc'), n = $('scoren');
    if (!dial || !arc || !n) return;
    var raw = dial.dataset.score;
    var r = 84, circ = 2 * Math.PI * r;
    arc.style.strokeDasharray = circ;
    if (raw === '' || raw == null) {
      n.textContent = '—';
      arc.style.strokeDashoffset = circ;
      return;
    }
    var score = Number(raw), to = circ * (1 - clamp(score, 0, 100) / 100);
    if (REDUCED) {
      n.textContent = Math.round(score);
      arc.style.strokeDashoffset = to;
      return;
    }
    if (replay) {
      arc.style.transition = 'none';
      arc.style.strokeDashoffset = circ;
      void arc.getBoundingClientRect();
      arc.style.transition = '';
    }
    if (window.AltahaShell && window.AltahaShell.countUp) window.AltahaShell.countUp(n, score, 0, 1100);
    else n.textContent = Math.round(score);
    // One frame later, so the browser has a state to animate away from.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { arc.style.strokeDashoffset = to; });
    });
  }

  /* The holding period. The three scores share their factors and differ in
     how the pillars are weighted, so the switch changes the arithmetic below
     and nothing has to be fetched. */
  function paintHorizons(d) {
    var host = $('hz');
    if (!host) return;
    var hs = d.horizons;
    if (!hs) { host.innerHTML = ''; return; }
    var order = ['trade', 'position', 'invest'].filter(function (k) { return hs[k]; });
    if (order.length < 2) { host.innerHTML = ''; return; }
    var short = { trade: 'Days to weeks', position: 'Weeks to months', invest: 'A year or more' };
    host.innerHTML = order.map(function (k) {
      return '<button type="button" data-hz="' + k + '" aria-pressed="' + (k === HZ) + '"' +
        (k === HZ ? ' class="on"' : '') + '>' + esc(short[k] || hs[k].horizon_label || k) + '</button>';
    }).join('');
    host.onclick = function (e) {
      var b = e.target.closest ? e.target.closest('[data-hz]') : null;
      if (!b || b.dataset.hz === HZ) return;
      HZ = b.dataset.hz;
      track('stock_section_clicked', { section: 'horizon_' + HZ });
      paintScore(DATA);
      growBars($('pane-scores'));
      var again = host.querySelector('[data-hz="' + HZ + '"]');
      if (again) again.focus();
    };
  }

  /* Beside the dial: one sentence, where the score ranks, and what it was
     measured as. For a company with no score, the reason it has none. */
  function paintScoreSay(d, sc, score) {
    var line = $('score-line'), rank = $('score-rank'), sub = $('score-sub'), basis = $('basis');
    if (score == null) {
      line.textContent = '';
      rank.innerHTML = '';
      sub.textContent = '';
      basis.textContent = sentence(sc.summary) ||
        'There is no score for this company yet.';
      basis.hidden = false;
      return;
    }

    var ps = sc.pillars || {}, keys = Object.keys(ps).filter(function (k) { return ps[k] != null; });
    var text = '';
    if (keys.length > 1) {
      var best = keys.reduce(function (a, b) { return ps[b] > ps[a] ? b : a; });
      var worst = keys.reduce(function (a, b) { return ps[b] < ps[a] ? b : a; });
      text = 'Strongest on ' + pillarName(best).toLowerCase() + ', weakest on ' +
        pillarName(worst).toLowerCase() + '.';
    } else if (keys.length === 1) {
      text = 'Scored on ' + pillarName(keys[0]).toLowerCase() + ' alone.';
    }
    line.textContent = text;

    var p = rankOf(d);
    rank.innerHTML = p == null ? '' :
      '<div class="rk-t"><b>Ranks above ' + p + '%</b> of the ' +
        (d.cohort_size ? Number(d.cohort_size).toLocaleString('en-IN') + ' ' : '') +
        'companies in the last scan</div>' +
      '<div class="rk-bar" role="img" aria-label="Above ' + p + ' percent of scanned companies">' +
        '<i style="--p:' + clamp(p, 0, 100) + '%"></i></div>';

    var bits = [];
    if (sc.model && sc.model.name) bits.push('Weighted for a ' + sc.model.name.toLowerCase());
    if (sc.horizon_label) bits.push(String(sc.horizon_label).toLowerCase());
    var asof = niceDate(d.altaha_score_v4 && d.altaha_score_v4.as_of);
    if (asof) bits.push('as of ' + asof);
    sub.textContent = bits.join(' · ');

    // Where the peers came from, when the company was ranked on request.
    var note = sentence(sc.cohort_note);
    basis.textContent = note;
    basis.hidden = !note;
  }

  /* How it adds up: pillar by pillar, then the sum, then the confidence step.
     `contribution` is the engine's own working, so the points printed here
     add up to its raw score to the decimal. */
  function paintAddsUp(d, sc, score) {
    var sec = $('s-adds'), host = $('pillars');
    var rows = (sc.contribution || []).slice();
    var ps = sc.pillars || {};
    if (score == null || (!rows.length && !Object.keys(ps).length)) {
      sec.hidden = true;
      host.innerHTML = '';
      return;
    }
    sec.hidden = false;

    // An older payload has the pillar scores and not the working; the bars
    // are still worth drawing.
    var plain = !rows.length;
    if (plain) {
      rows = Object.keys(ps).map(function (k) { return { pillar: k, pillar_score: ps[k] }; });
    }
    rows.sort(function (a, b) {
      return ((b.weight || 0) - (a.weight || 0)) ||
        (PILLAR_ORDER.indexOf(a.pillar) - PILLAR_ORDER.indexOf(b.pillar));
    });

    var html = plain ? '' :
      '<div class="pl pl-head" aria-hidden="true"><span>Pillar</span><span>Rank among peers</span>' +
      '<span>Rank</span><span>Weight</span><span>Points</span></div>';
    html += rows.map(function (r, i) {
      var v = r.pillar_score, meta = PILLARS[r.pillar] || [pillarName(r.pillar), ''];
      return '<div class="pl" style="--i:' + i + '">' +
        '<div class="pl-n"><b>' + esc(meta[0]) + '</b>' +
          (meta[1] ? '<small>' + esc(meta[1]) + '</small>' : '') + '</div>' +
        '<div class="pl-bar" role="img" aria-label="' + (v == null ? 'not measured' :
          Math.round(v) + ' out of 100 against peers') + '">' +
          '<i class="fill" data-w="' + (v == null ? 0 : v) + '"></i><span class="mid"></span></div>' +
        '<div class="pl-s tnum">' + (v == null ? 'n/a' : Math.round(v)) + '</div>' +
        (plain ? '' :
          '<div class="pl-w tnum">× ' + Math.round((r.weight || 0) * 100) + '%</div>' +
          '<div class="pl-p tnum">' + (r.points == null ? '—' : r.points.toFixed(1)) + '</div>') +
        '</div>';
    }).join('');

    if (!plain) {
      // Pillars the weights name and the sum does not include: not measurable
      // for this kind of business, or no data. They are why confidence is low.
      var have = {};
      rows.forEach(function (r) { have[r.pillar] = 1; });
      var missing = Object.keys(sc.weights || {}).filter(function (k) {
        return sc.weights[k] > 0 && !have[k];
      });
      if (missing.length) {
        html += '<div class="pl-miss">Not measured: ' + missing.map(function (k) {
          return '<b>' + esc(pillarName(k)) + '</b>';
        }).join(', ') + '. Their weight is shared among the rest, and lowers confidence.</div>';
      }

      var raw = sc.raw_score, conf = sc.confidence;
      if (raw != null && conf != null) {
        html += '<div class="pl-sum"><span>Weighted sum</span><b class="tnum">' + raw.toFixed(1) + '</b></div>' +
          '<div class="pl-conf">' +
            '<div class="pl-conf-t"><b>Confidence ' + conf.toFixed(1) + '%.</b> ' +
              'The sum is pulled toward 50 by what could not be measured' +
              (sc.confidence_notes ? ': ' + esc(String(sc.confidence_notes).split(/;\s*/)
                .map(function (c) { return c.charAt(0).toLowerCase() + c.slice(1); }).join('; ')) : '') +
              '.</div>' +
            '<div class="cf' + ((Math.abs(raw - 50) > 9 && Math.abs(score - 50) > 9) ? ' far' : '') +
              '" role="img" aria-label="' + raw.toFixed(1) + ' pulled toward 50 gives ' +
              score.toFixed(1) + '">' +
              '<span class="cf-50" style="left:50%"><em>50</em></span>' +
              '<span class="cf-pull" style="left:' + Math.min(raw, score) + '%;width:' +
                Math.abs(raw - score) + '%"></span>' +
              '<span class="cf-raw" style="left:' + clamp(raw, 0, 100) + '%"><em>' + raw.toFixed(1) + '</em></span>' +
              '<span class="cf-fin" style="left:' + clamp(score, 0, 100) + '%"><em>' + score.toFixed(1) + '</em></span>' +
            '</div>' +
            '<div class="pl-eq tnum">50 + (' + raw.toFixed(1) + ' − 50) × ' + conf.toFixed(1) +
              '% = <b>' + score.toFixed(1) + '</b></div>' +
          '</div>';
      }
    }
    host.innerHTML = html;

    var x = [];
    if (sc.model && sc.model.name) x.push(sc.model.name + ' weights');
    if (sc.horizon_label) x.push(String(sc.horizon_label).toLowerCase());
    $('adds-x').textContent = x.join(' · ');
  }

  function peerWords(e) {
    var parts = String(e.peer_group || '').split(':'), n = e.peer_count || 0;
    var kind = parts[1], name = parts.slice(2).join(':');
    var who = kind === 'model' ? (name === 'lender' ? 'lenders' : name + ' companies')
      : kind === 'sector' ? name + ' companies'
      : kind === 'size' ? name + '-cap companies'
      : 'scanned companies';
    return n + ' ' + who;
  }

  function driverItem(e) {
    var p = Math.round(e.percentile);
    return '<li><span class="dv-l">' + esc(factorName(e)) + '</span>' +
      '<span class="dv-b"><i class="fill" data-w="' + p + '"></i></span>' +
      '<span class="dv-p tnum">beats ' + p + '%</span></li>';
  }

  function paintDrivers(d, score) {
    var sec = $('s-drivers'), v4 = d.altaha_score_v4 || {};
    var up = v4.what_helped || [], dn = v4.what_hurt || [];
    if (score == null || (!up.length && !dn.length)) { sec.hidden = true; return; }
    sec.hidden = false;
    $('drivers').innerHTML =
      '<div class="drv-col up"><h3>Helped</h3>' + (up.length
        ? '<ul>' + up.map(driverItem).join('') + '</ul>'
        : '<p class="drv-none">Nothing ranks above the middle of its peers.</p>') + '</div>' +
      '<div class="drv-col dn"><h3>Hurt</h3>' + (dn.length
        ? '<ul>' + dn.map(driverItem).join('') + '</ul>'
        : '<p class="drv-none">Nothing ranks below the middle of its peers.</p>') + '</div>';
  }

  /* Every factor behind the pillars: its value, where that sits among peers,
     and which peers. A factor with no reading says why instead of scoring. */
  function paintFactors(d, sc, score) {
    var sec = $('s-factors');
    var ledger = sc.factor_ledger || (d.altaha_score_v4 && d.altaha_score_v4.factor_ledger) || [];
    if (score == null || !ledger.length) { sec.hidden = true; return; }
    sec.hidden = false;

    var live = ledger.filter(function (e) { return e.applicable !== false; });
    var skipped = ledger.filter(function (e) { return e.applicable === false; });
    var ps = sc.pillars || {};
    var html = '';
    PILLAR_ORDER.forEach(function (fam) {
      var rows = live.filter(function (e) { return e.family === fam; });
      if (!rows.length) return;
      var unweighted = sc.weights && sc.weights[fam] === 0;
      html += '<div class="fl-g' + (unweighted ? ' off' : '') + '"><h3><span>' + esc(pillarName(fam)) +
        (unweighted ? '<em>not counted at this holding period</em>' : '') + '</span>' +
        (ps[fam] != null ? '<b class="tnum">' + Math.round(ps[fam]) + '</b>' : '') + '</h3>' +
        rows.map(function (e) {
          var has = e.percentile != null;
          return '<div class="fl-r' + (has ? '' : ' none') + '">' +
            '<span class="fl-l">' + esc(factorName(e)) +
              (has ? '<small>among ' + esc(peerWords(e)) + '</small>' : '') + '</span>' +
            '<span class="fl-v tnum">' + (e.value == null ? '—' : fig(e.value)) + '</span>' +
            (has
              ? '<span class="fl-b"><i class="fill" data-w="' + e.percentile + '"></i><span class="mid"></span></span>' +
                '<span class="fl-p tnum">' + Math.round(e.percentile) + '</span>'
              : '<span class="fl-why">' + esc(e.missing_reason || 'not measured') + '</span>') +
            '</div>';
        }).join('') + '</div>';
    });
    if (skipped.length) {
      html += '<details class="fl-skip"><summary>' + skipped.length + ' factor' +
        (skipped.length === 1 ? ' does' : 's do') + ' not apply to this kind of business</summary><p>' +
        skipped.map(function (e) { return esc(factorName(e)); }).join(' · ') + '</p></details>';
    }
    $('factors').innerHTML = html;
    var cov = sc.coverage;
    $('factors-x').textContent = cov && cov.total
      ? cov.present + ' of ' + cov.total + ' measured · rank is the percentile among peers' : '';
  }

  /* The score, under the name. It is the one number this site exists to
     give. The chip states it, says where it ranks, and opens its section;
     nothing is worked out here. A stock without a score shows no chip. */
  function paintScoreChip(d, score, band) {
    var chip = $('stk-scorechip');
    if (!chip) return;
    if (score == null) { chip.hidden = true; return; }
    $('stk-scorechip-n').textContent = Math.round(score);
    $('stk-scorechip-lb').textContent = band ? '· ' + band : '';
    var p = rankOf(d);
    $('stk-scorechip-sub').textContent = p == null ? 'out of 100'
      : 'Ranks above ' + p + '% of companies scanned';
    var arc = $('stk-scorechip-arc');
    if (arc) {
      var circ = 2 * Math.PI * 19;
      arc.style.strokeDasharray = circ;
      arc.style.strokeDashoffset = circ * (1 - clamp(score, 0, 100) / 100);
    }
    chip.setAttribute('aria-label', 'Altaha Score ' + Math.round(score) + ' out of 100' +
      (band ? ', ' + band : '') + '. Open the score breakdown.');
    chip.hidden = false;
  }

  function wireScoreChip() {
    var chip = $('stk-scorechip');
    if (!chip) return;
    chip.addEventListener('click', function () {
      track('stock_section_clicked', { section: 'score_chip' });
      showPane('scores', true);
    });
  }

  /* The score's card on the Overview: the pillars at a glance and the single
     strongest and weakest factor. The number itself is in the chip above, and
     the same number printed twice on one screen reads as two numbers. */
  function paintOverviewScore(d, sc, score, band) {
    var card = $('ov-score'), body = $('ov-score-body');
    if (!card || !body) return;
    if (score == null) {
      // Being scored right now is worth a line; "no cohort for this market"
      // is said once, in the Score section.
      if (sc.pending) {
        card.hidden = false;
        body.innerHTML = '<p class="ov-wait"><span class="sai-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
          'Ranking this company against the scan…</p>';
      } else {
        card.hidden = true;
      }
      return;
    }
    var ps = sc.pillars || {}, w = sc.weights || {};
    var keys = Object.keys(ps).filter(function (k) {
        // A pillar this holding period gives no weight is measured but adds
        // nothing to the number; its bar here would look like it did.
        return ps[k] != null && !(sc.weights && sc.weights[k] === 0);
      })
      .sort(function (a, b) {
        return ((w[b] || 0) - (w[a] || 0)) || (PILLAR_ORDER.indexOf(a) - PILLAR_ORDER.indexOf(b));
      }).slice(0, 6);
    var v4 = d.altaha_score_v4 || {};
    var up = (v4.what_helped || [])[0], dn = (v4.what_hurt || [])[0];
    body.innerHTML =
      (keys.length ? '<div class="ovs-p">' + keys.map(function (k) {
        return '<div class="ovs-r"><span>' + esc(pillarName(k)) + '</span>' +
          '<span class="ovs-b"><i class="fill" data-w="' + ps[k] + '"></i><span class="mid"></span></span>' +
          '<b class="tnum">' + Math.round(ps[k]) + '</b></div>';
      }).join('') + '</div>' : '') +
      ((up || dn) ? '<ul class="ovs-d">' +
        (up ? '<li class="up"><i aria-hidden="true">▲</i><span>' + esc(factorName(up)) +
          '</span><b class="tnum">beats ' + Math.round(up.percentile) + '%</b></li>' : '') +
        (dn ? '<li class="dn"><i aria-hidden="true">▼</i><span>' + esc(factorName(dn)) +
          '</span><b class="tnum">beats ' + Math.round(dn.percentile) + '%</b></li>' : '') +
        '</ul>' : '') +
      '<p class="ovs-f">Each bar is a rank among peers, from 0 to 100.</p>';
    card.hidden = false;
    growBars(body);
  }

  /* ── Other checks ────────────────────────────────────────────────────────
     The technical and fundamental checks the site scored companies on before
     the Altaha Score was a peer rank. They are still computed and still say
     something about a chart and a balance sheet, but none of their points go
     into the number above, and the section says so in its heading. */
  function paintLedger(d) {
    var t = d.technical || {}, f = d.fundamental || {};
    var groups = [
      ['Price checks', t.checks || [], t.score],
      ['Statement checks', f.checks || [], f.score]
    ];
    var html = '';
    groups.forEach(function (g) {
      if (!g[1].length) return;
      html += '<h3 class="chk-h">' + esc(g[0]) +
        (g[2] == null ? '' : '<b class="tnum">' + Math.round(g[2]) + ' / 100</b>') + '</h3>';
      html += g[1].map(function (c) {
        var mx = Number(c.max) || 0, p = Number(c.points) || 0;
        var share = mx > 0 ? clamp(p / mx, 0, 1) : 0;
        var cls = mx > 0 && p >= mx ? 'full' : (p <= 0 ? 'zero' : '');
        return '<details class="chk">' +
          '<summary>' +
            '<span class="cn">' + esc(c.name) + '</span>' +
            '<span class="cv">' + esc(c.value) + '</span>' +
            '<span class="pts"><span class="ptbar"><span class="ptfill ' + cls +
              '" style="width:' + (share * 100).toFixed(0) + '%"></span></span>' +
              '<span class="ptn">' + p + '/' + mx + '</span></span>' +
          '</summary>' +
          '<div class="body">' +
            '<div class="row"><span class="k">Measured</span><span class="v mono">' +
              esc(c.value) + '</span></div>' +
            '<div class="row"><span class="k">Formula</span><span class="v mono">' +
              esc(c.formula) + '</span></div>' +
            '<div class="row"><span class="k">Why</span><span class="v">' +
              esc(c.explain) + '</span></div>' +
          '</div></details>';
      }).join('');
    });
    var diag = $('diag');
    if (diag) diag.parentNode.hidden = !html;
    $('ledger').innerHTML = html;
    var bits = [];
    if (t.score != null) bits.push('Price ' + Math.round(t.score) + '/100');
    if (f.score != null) bits.push('Statements ' + Math.round(f.score) + '/100');
    if (f.f_score != null) bits.push('Piotroski ' + f.f_score + '/9');
    $('diag-x').textContent = (bits.length ? bits.join(' · ') + ' · ' : '') + 'not part of the score';
  }

  /* ── Key figures ─────────────────────────────────────────────────────────
     The figures a reader checks before they read anything else, each with
     where it sits among the company's peers. All come from the backend's
     `ratios` block so there is one definition of each, and a figure the
     provider does not publish shows a dash rather than a zero.

     The set depends on the business. A bank's deposits are what it sells, so
     its debt to equity says nothing a reader could use and its return on
     capital employed is not defined the way a manufacturer's is; for a lender
     those two tiles are left out rather than printed with a peer rank as
     though they meant something. */

  function compactMoney(v, cur) {
    var n = Number(v);
    if (!n || isNaN(n)) return '—';
    var sym = cur === 'INR' ? '₹' : '$';
    function f(x) {
      return x >= 1000 ? Math.round(x).toLocaleString('en-IN')
           : x >= 100  ? x.toFixed(0)
                       : x.toFixed(2);
    }
    if (cur === 'INR') {
      if (n >= 1e7) return sym + f(n / 1e7) + ' Cr.';
      if (n >= 1e5) return sym + f(n / 1e5) + ' L';
    }
    if (n >= 1e12) return sym + f(n / 1e12) + 'T';
    if (n >= 1e9) return sym + f(n / 1e9) + 'B';
    if (n >= 1e6) return sym + f(n / 1e6) + 'M';
    return sym + n.toLocaleString();
  }

  /* A header figure with its unit. Not called `plain`: the Financials pane
     further down this same closure declares a `plain(v, d)` of its own, and a
     function declaration hoists over an earlier one of the same name. That is
     how every ratio in the header strip came to be printed by the other
     function — rounded to whole numbers, units dropped, debt/equity 0.3 as "0". */
  function withUnit(v, unit, nd) {
    var n = num(v, nd == null ? 2 : nd);
    if (n == null) return '—';
    return n.toLocaleString('en-IN', { maximumFractionDigits: nd == null ? 2 : nd }) + (unit || '');
  }

  function paintKey(d) {
    var r = d.ratios || {};
    var peers = d.peers || {};
    var cur = d.currency;
    var tx = (d.technical && d.technical.extras) || {};
    var lender = isLender(d);

    /* `key` is the metric name the backend's peer block uses — null where a
       peer percentile is meaningless, as it is for a rupee amount. */
    var tiles = [
      { label: 'Market cap',     value: compactMoney(r.market_cap, cur) },
      { label: 'P/E',            value: withUnit(r.pe, '', 1),             key: 'pe' },
      { label: 'Price / book',   value: withUnit(r.price_to_book, '', 2) },
      { label: 'Dividend yield', value: withUnit(r.dividend_yield, '%', 2), key: 'dividend_yield' },
      { label: 'ROE',            value: withUnit(r.roe, '%', 1),           key: 'roe' }
    ];
    if (!lender) {
      tiles.push({ label: 'ROCE',          value: withUnit(r.roce, '%', 1),          key: 'roce' });
      tiles.push({ label: 'Debt / equity', value: withUnit(r.debt_to_equity, '', 2), key: 'debt_to_equity' });
    }
    tiles.push({ label: 'Book value', value: r.book_value == null ? '—' : money(r.book_value, cur) });

    var grid = $('kgrid');
    grid.dataset.n = tiles.length;
    grid.innerHTML = tiles.map(function (t, i) {
      return '<div class="ktile" style="--i:' + i + '">' +
        '<div class="k">' + esc(t.label) + '</div>' +
        '<div class="v">' + esc(t.value) + '</div>' +
        meter(t.key ? peers[t.key] : null) +
      '</div>';
    }).join('');

    // Whom the meters compare against, said once for the whole card.
    var first = Object.keys(peers).map(function (k) { return peers[k]; })
      .filter(function (p) { return p && p.peers; })[0];
    $('key-vs').textContent = first ? 'Against ' + first.peers + ' ' + first.group : '';

    paintRange(r.low_52w != null ? r.low_52w : tx.low_52w,
               r.high_52w != null ? r.high_52w : tx.high_52w,
               r.price != null ? r.price : d.price, cur);
    growBars(grid);
  }

  /* The peer meter.

     One gold track per figure showing where it sits among its peers, with a
     tick at the 50th so the reader can see the median without being told what
     to think about it. Deliberately one hue and no red/green: whether a high
     P/E is bad is a judgement, and this page reports arithmetic. The phrase
     ("cheaper than 81%") is written by the backend so the words and the
     direction of the measurement can never disagree. */
  function meter(p) {
    if (!p || p.percentile == null) return '<div class="kmeter empty"></div>';
    var pc = clamp(p.percentile, 0, 100);
    var phrase = String(p.phrase || '');
    var full = phrase + ' of ' + p.peers + ' ' + p.group;
    return '<div class="kmeter" title="' + esc(full) + '">' +
      '<div class="track" role="img" aria-label="' + esc(full) + '">' +
        '<span class="fill" data-w="' + pc + '"></span>' +
        '<span class="mid" aria-hidden="true"></span>' +
      '</div>' +
      '<div class="cap">' + esc(phrase.charAt(0).toUpperCase() + phrase.slice(1)) + ' of peers</div>' +
    '</div>';
  }

  /* The 52-week range as a line the price sits on, not two numbers and a
     dash. Where it sits is the whole reason anybody reads the range. */
  function paintRange(lo, hi, px, cur) {
    var host = $('krange');
    lo = num(lo); hi = num(hi); px = num(px);
    if (lo == null || hi == null || !(hi > lo)) { host.innerHTML = ''; host.hidden = true; return; }
    host.hidden = false;
    var at = px == null ? null : clamp(100 * (px - lo) / (hi - lo), 0, 100);
    var off = px == null || !hi ? null : 100 * (px / hi - 1);
    host.innerHTML =
      '<div class="kr-h"><span class="k">52-week range</span>' +
        (off == null ? '' : '<span class="kr-x">' +
          (Math.abs(off) < 0.05 ? 'At the high' : Math.abs(off).toFixed(1) + '% below the high') + '</span>') +
      '</div>' +
      '<div class="kr-bar" role="img" aria-label="Price ' + (at == null ? '' : Math.round(at) +
        ' percent of the way from the 52-week low to the high') + '">' +
        (at == null ? '' : '<i style="--at:' + at.toFixed(1) + '%"></i>') + '</div>' +
      '<div class="kr-ends tnum"><span>' + esc(money(lo, cur)) + '</span><span>' +
        esc(money(hi, cur)) + '</span></div>';
  }

  /* The description the provider publishes runs to a thousand characters and
     is the last thing that should push the page down. It opens clamped to
     four lines with the rest one tap away. */
  function paintAbout(d) {
    var p = d.profile || {};
    var box = $('brief');
    if (!p.description) { box.hidden = true; return; }

    $('brief-body').textContent = p.description;

    var more = $('brief-more');
    // Clamped text is only worth a control when there is something hidden by
    // the clamp. scrollHeight is read after layout for the same reason.
    requestAnimationFrame(function () {
      var el = $('brief-body');
      if (el.scrollHeight - el.clientHeight > 4) {
        more.hidden = false;
        more.addEventListener('click', function () {
          var open = el.classList.toggle('open');
          more.textContent = open ? 'Show less' : 'Read more';
        });
      }
    });

    var meta = [];
    if (p.employees) meta.push(Number(p.employees).toLocaleString('en-IN') + ' employees');
    var site = safeUrl(p.website);
    if (site) meta.push('<a href="' + esc(site) + '" target="_blank" rel="noopener noreferrer">' +
      esc(site.replace(/^https?:\/\//, '').replace(/\/$/, '')) + '</a>');
    $('brief-meta').innerHTML = meta.join(' · ');
    $('brief-meta').title = p.source || '';
  }

  /* ── Overview: the year's price ──────────────────────────────────────────
     One request at load, and it does two jobs. The number under the price is
     today's move and only ever today's move: `day_change_pct`, the last close
     against the one before it, which does not depend on the range asked for.
     The same response's closes draw the year on the Overview, so the first
     screen shows how the price has moved without the reader opening the
     chart. The full chart, with its ranges and its measuring, is one tap
     away and asks for itself.

     There is no fallback to `change_pct` for the headline: that is the move
     across whatever window was drawn, and printing a year's return where a
     reader looks for the day's is worse than printing nothing. */
  function loadYear(d0) {
    var card = $('ov-price');
    getJSON('/chart?ticker=' + encodeURIComponent(TICKER) + '&range=1Y')
      .then(function (d) {
        if (d && d.day_change_pct != null) {
          var c = $('chg');
          c.className = 'chg tnum ' + tone(d.day_change_pct);
          c.textContent = pct(d.day_change_pct) + ' today';
          var m = $('mini-chg');
          m.className = 'tnum ' + tone(d.day_change_pct);
          m.textContent = pct(d.day_change_pct);
        }
        drawYear(d, d0);
      })
      .catch(function () { if (card) card.hidden = true; });
  }

  function drawYear(d, d0) {
    var card = $('ov-price'), box = $('ov-spark');
    var rows = ((d && d.candles) || []).filter(function (r) {
      return r && typeof r[4] === 'number' && isFinite(r[4]);
    });
    if (rows.length < 2) { card.hidden = true; return; }
    var closes = rows.map(function (r) { return r[4]; });
    var n = closes.length, lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var pad = (hi - lo) * 0.1 || 1;
    lo -= pad; hi += pad;
    var W = 1000, H = 150;
    function x(i) { return (i / (n - 1)) * W; }
    function y(v) { return H - ((v - lo) / (hi - lo)) * H; }
    var line = 'M' + closes.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join(' L');
    var rising = closes[n - 1] >= closes[0];
    var stroke = rising ? 'var(--sh-up)' : 'var(--sh-dn)';
    box.innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="' +
        'Closing price over the last year, from ' + esc(money(closes[0], d.currency)) + ' to ' +
        esc(money(closes[n - 1], d.currency)) + '">' +
        '<defs><linearGradient id="ovG" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" stop-color="' + stroke + '" stop-opacity=".22"/>' +
          '<stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/></linearGradient></defs>' +
        '<path class="ov-area" d="' + line + ' L' + W + ',' + H + ' L0,' + H + ' Z" fill="url(#ovG)"/>' +
        '<path class="ov-line' + (REDUCED ? '' : ' draw') + '" d="' + line + '" style="stroke:' + stroke + '"/>' +
      '</svg>' +
      '<span class="ov-dot" style="top:' + (100 * y(closes[n - 1]) / H).toFixed(1) + '%;color:' + stroke + '"></span>';
    var path = box.querySelector('.ov-line.draw');
    if (path && path.getTotalLength) path.style.setProperty('--len', path.getTotalLength());

    // The year from the closes just drawn; the shorter windows from the
    // engine, which measured them on the same series it scored.
    var tx = (d0.technical && d0.technical.extras) || {};
    var rets = [['1 month', tx.ret_1m], ['3 months', tx.ret_3m], ['6 months', tx.ret_6m],
                ['1 year', closes[0] ? 100 * (closes[n - 1] / closes[0] - 1) : null]];
    $('ov-rets').innerHTML = rets.filter(function (r) { return r[1] != null; }).map(function (r) {
      return '<div class="ov-ret"><span>' + r[0] + '</span><b class="tnum ' + tone(r[1]) + '">' +
        pct(r[1], 1) + '</b></div>';
    }).join('');
  }

  /* ── Technical snapshot ──────────────────────────────────────────────────
     Readings off the price series, beside the chart they describe. The
     technical and fundamental scores that used to head this grid are not
     here: they are the older checks' totals, and sitting above a list of
     figures they read as two more headline scores. */
  function paintNumbers(d) {
    var x = (d.technical && d.technical.extras) || {};
    var cells = [
      ['RSI', x.rsi == null ? '—' : x.rsi, 'Momentum, 0 to 100'],
      ['ADX', x.adx == null ? '—' : x.adx, 'Trend strength; above 25 is a trend'],
      ['ATR', d.atr_pct == null ? '—' : num(d.atr_pct, 1) + '%', 'Average daily range'],
      ['1 month', x.ret_1m == null ? '—' : pct(x.ret_1m, 1), 'Return', x.ret_1m],
      ['3 months', x.ret_3m == null ? '—' : pct(x.ret_3m, 1), 'Return', x.ret_3m],
      ['6 months', x.ret_6m == null ? '—' : pct(x.ret_6m, 1), 'Return', x.ret_6m],
      ['In 52-week range', x.range_position == null ? '—' : x.range_position + '%',
        '0 is the low, 100 the high'],
      ['From high', x.drawdown_from_high == null ? '—' : pct(x.drawdown_from_high, 1),
        'Below the 52-week high', x.drawdown_from_high]
    ];
    $('nums').innerHTML = cells.map(function (c, i) {
      return '<div class="num" style="--i:' + i + '">' +
        '<div class="k">' + esc(c[0]) + '</div>' +
        '<div class="v tnum ' + (c[3] == null ? '' : tone(c[3])) + '">' + esc(c[1]) + '</div>' +
        '<div class="h">' + esc(c[2]) + '</div></div>';
    }).join('');
  }

  /* ── Levels ──────────────────────────────────────────────────────────────── */

  function paintLevels(d) {
    var lv = d.levels;
    if (!lv || (!lv.supports && !lv.resistances)) {
      $('s-levels').hidden = true;
      return;
    }
    var zones = [].concat(lv.resistances || [], lv.supports || []);
    zones.sort(function (a, b) { return (b.level || 0) - (a.level || 0); });
    if (!zones.length) { $('s-levels').hidden = true; return; }
    $('levels').innerHTML = zones.slice(0, 8).map(function (z, i) {
      var kind = String(z.kind || '').toLowerCase();
      return '<div class="lvl ' + (kind === 'resistance' ? 'res' : 'sup') + '" style="--i:' + i +
        '" title="' + esc(z.why || '') + '">' +
        '<div class="k">' + esc(z.kind) + (z.strength == null ? '' : ' · ' + z.strength + '/100') + '</div>' +
        '<div class="v tnum">' + money(z.level, d.currency) + '</div>' +
        '<div class="h">' +
          (z.distance_pct == null ? '' : pct(z.distance_pct, 1) + ' away') +
          (z.touches ? ' · ' + z.touches + (z.touches === 1 ? ' touch' : ' touches') : '') + '</div></div>';
    }).join('');
  }

  /* ── Smart AI: the score in plain English ─────────────────────────────────
     A floating button, bottom right. Opening it offers one question; nothing
     is requested from the server until the reader asks it. Each fresh
     explanation spends part of a small free daily allowance, and most
     visitors never ask. The answer stays in the panel for the visit, so
     closing and reopening does not ask again. */

  var QUESTION = 'What does this score mean, in simple words?';

  function paintExplain(d) {
    var wrap = $('sai'), panel = $('sai-panel'), fab = $('sai-fab'), box = $('sai-body');
    if (!wrap || !panel || !fab || !box) return;
    var sc = d.scoring || {};
    // No score, nothing to explain — and the server would say the same after
    // analysing the stock again.
    if (sc.score == null) { wrap.hidden = true; return; }
    wrap.hidden = false;
    var horizon = sc.horizon || 'position';
    var name = d.name || TICKER;

    function setOpen(open) {
      panel.hidden = !open;
      fab.setAttribute('aria-expanded', open ? 'true' : 'false');
      wrap.classList.toggle('open', open);
      if (open) {
        var first = box.querySelector('button') || $('sai-x');
        if (first) first.focus();
      } else {
        fab.focus();
      }
    }

    function offer() {
      box.innerHTML =
        '<p class="sai-hi">Ask about the Altaha Score for <b>' + esc(name) + '</b>.</p>' +
        '<button type="button" class="sai-q" id="sai-q">' + esc(QUESTION) + '</button>';
      $('sai-q').addEventListener('click', ask);
    }

    function retry(message) {
      box.insertAdjacentHTML('beforeend', '<p class="sai-note">' + esc(message) + '</p>' +
        '<button type="button" class="sai-q" id="sai-q">Try again</button>');
      $('sai-q').addEventListener('click', ask);
    }

    function ask() {
      // The question stays on screen as the reader's side of the exchange.
      box.innerHTML = '<p class="sai-you">' + esc(QUESTION) + '</p>' +
        '<p class="sai-wait" role="status"><span class="sai-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
        'Reading the numbers…</p>';
      fetch(API + '/explain?ticker=' + encodeURIComponent(TICKER) +
            '&horizon=' + encodeURIComponent(horizon))
        .then(function (r) {
          if (!r.ok) throw new Error('down');
          return r.json();
        })
        .then(function (x) {
          if (window.AltahaTrack) {
            window.AltahaTrack('score_explained', {
              ticker: TICKER, ok: !!x.available, reason: x.reason || null, cached: !!x.cached
            });
          }
          var you = '<p class="sai-you">' + esc(QUESTION) + '</p>';
          if (!x.available) {
            box.innerHTML = you;
            if (x.reason === 'busy' || x.reason === 'error') {
              retry(x.message || 'No explanation is available right now.');
            } else {
              box.insertAdjacentHTML('beforeend', '<p class="sai-note">' +
                esc(x.message || 'No explanation is available.') + '</p>');
            }
            return;
          }
          var when = '';
          try {
            // Written in IST on the server, and shown in IST whatever the
            // reader's clock says — "written today" has to mean an Indian day.
            when = new Date(x.generated_at).toLocaleString('en-IN',
              { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
                timeZone: 'Asia/Kolkata' }) + ' IST';
          } catch (e) {}
          // A stored explanation is from earlier today, and the score it was
          // written against may have moved since. Say which score it read.
          var drift = (x.score != null && sc.score != null &&
                       Math.round(x.score) !== Math.round(sc.score))
            ? ' It was written when the score was ' + Math.round(x.score) + '.' : '';
          box.innerHTML = you +
            '<div class="sai-ans">' + (x.paragraphs || []).map(function (p) {
              return '<p>' + esc(p) + '</p>';
            }).join('') + '</div>' +
            '<p class="sai-meta"><span class="sai-tag">AI-written</span>' +
            esc((when ? 'Written ' + when + '. ' : '') + (x.disclaimer || '') + drift) + '</p>';
        })
        .catch(function () {
          box.innerHTML = '<p class="sai-you">' + esc(QUESTION) + '</p>';
          retry('The explanation could not be loaded.');
        });
    }

    offer();
    fab.addEventListener('click', function () { setOpen(panel.hidden); });
    $('sai-x').addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) setOpen(false);
    });
  }

  /* ── Chart ───────────────────────────────────────────────────────────────
     A line, drawn from the same closes the engine scored. Deliberately not a
     charting library: this page needs one honest series, and pulling 200 KB
     of candlestick engine over a mobile connection to draw it would be a poor
     trade. The full workspace still lives on the Charts tab.               */

  /* Windows of history, not candle sizes. The old list asked for '1D' and
     '1W', which on this API name daily and weekly BARS — four hundred and
     twelve hundred sessions of them — so a button labelled "1 day" drew a
     year and a half. '6M' and '1Y' were not ranges the API knew at all and
     came back 400, and '6M' is where this chart opens, so the stock page's
     chart drew nothing until you pressed something else. '1M' was worse than
     an error: it matched the one-MINUTE timeframe and returned intraday bars
     when the live feed was up, and 503 when it wasn't.

     All five are daily-resolution windows now, which need no live feed. The
     intraday timeframes still exist and still belong to the charting
     workspace, where the control is explicitly a bar size.

     1D and 5D are the exception: a day drawn from daily bars is one point.
     They ask for '1DAY' and '5DAY' — intraday bars trimmed to the last one
     and five sessions — because '1D' on this API is still the daily candle
     size. Those two need the live feed; the rest never do. */
  var RANGES = [['1D', '1 day', '1DAY'], ['5D', '5 days', '5DAY'],
                ['1M', '1 month'], ['3M', '3 months'], ['6M', '6 months'],
                ['1Y', '1 year'], ['5Y', '5 years']];
  function rangeKey(r) {
    var hit = RANGES.filter(function (x) { return x[0] === r; })[0];
    return (hit && hit[2]) || r;
  }
  function isIntraday(r) { return rangeKey(r) !== r; }
  var chartRange = '6M', chartRequest = 0;

  function paintRanges() {
    $('ranges').innerHTML = RANGES.map(function (r) {
      return '<button type="button" aria-label="' + r[1] + '" aria-pressed="' + (r[0] === chartRange) + '" data-r="' + r[0] + '"' +
        (r[0] === chartRange ? ' class="on"' : '') + '>' + esc(r[0]) + '</button>';
    }).join('');
    $('ranges').onclick = function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      chartRange = b.dataset.r;
      if (window.AltahaTrack) window.AltahaTrack('chart_range_changed', { range: chartRange });
      paintRanges();
      $('ranges').querySelector('[data-r="' + chartRange + '"]').focus();
      loadChart();
    };
  }

  function loadChart() {
    var box = $('chartbox');
    var request = ++chartRequest;
    box.setAttribute('aria-busy', 'true');
    box.innerHTML = '<div class="skel" style="height:250px"></div>';
    var asked = chartRange, failStatus = 0;
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=' + rangeKey(chartRange))
      .then(function (r) {
        if (!r.ok) {
          failStatus = r.status;
          if (window.AltahaTrack) {
            window.AltahaTrack('chart_failed', { range: asked, status: r.status });
            window.AltahaTrack('api_error', { endpoint: '/chart', status: r.status });
          }
          throw new Error('x');
        }
        return r.json();
      })
      .then(function (d) {
        if (request !== chartRequest) return;
        box.setAttribute('aria-busy', 'false');
        drawChart(d, box);
      })
      .catch(function () {
        if (request !== chartRequest) return;
        box.setAttribute('aria-busy', 'false');
        box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
          'font-size:13px">' + (isIntraday(asked) && failStatus
            ? 'Intraday prices for this stock are not available right now. Try 1M or longer.'
            : 'Price history is not available right now.') + '</div>';
      });
  }

  /* A candle's calendar date. The API stamps daily bars at the exchange's
     midnight — 18:30Z the evening before for NSE — so formatting the raw
     instant in UTC printed yesterday, and formatting it in the reader's zone
     only worked for readers in the exchange's zone. Six hours forward lands
     IST, New York and UTC midnights all on their own day, read in UTC. */
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function candleDate(raw) {
    var t = null;
    if (typeof raw === 'number') t = raw > 1e12 ? raw : raw * 1000;
    else if (raw != null) t = Date.parse(raw);
    if (t == null || isNaN(t)) return null;
    return new Date(t + 6 * 3600 * 1000);
  }
  function dayLabel(raw) {
    var dt = candleDate(raw);
    if (!dt) return 'Date unavailable';
    return dt.getUTCDate() + ' ' + MONTHS[dt.getUTCMonth()] + ' ' + dt.getUTCFullYear();
  }
  /* Intraday bars are stamped from naive exchange time read as UTC, so their
     wall-clock time is the UTC reading, unshifted. */
  function barTime(raw, withDate) {
    var t = typeof raw === 'number' ? (raw > 1e12 ? raw : raw * 1000) : Date.parse(raw);
    if (t == null || isNaN(t)) return 'Time unavailable';
    var dt = new Date(t), hh = dt.getUTCHours(), mm = dt.getUTCMinutes();
    var clock = (hh % 12 || 12) + ':' + (mm < 10 ? '0' : '') + mm + (hh < 12 ? ' am' : ' pm');
    return withDate ? dt.getUTCDate() + ' ' + MONTHS[dt.getUTCMonth()] + ', ' + clock : clock;
  }
  function span(a, b) {
    var ta = typeof a === 'number' ? a * (a > 1e12 ? 1 : 1000) : Date.parse(a);
    var tb = typeof b === 'number' ? b * (b > 1e12 ? 1 : 1000) : Date.parse(b);
    if (isNaN(ta) || isNaN(tb)) return '';
    var da = Math.floor(ta / 86400000), db = Math.floor(tb / 86400000);
    if (da !== db) { var k = Math.abs(db - da); return k + (k === 1 ? ' day' : ' days'); }
    var m = Math.round(Math.abs(tb - ta) / 60000);
    return (m >= 60 ? Math.floor(m / 60) + 'h ' : '') + (m % 60) + 'm';
  }
  function daysBetween(a, b) {
    var da = candleDate(a), db = candleDate(b);
    if (!da || !db) return null;
    return Math.round(Math.abs(db - da) / 86400000);
  }

  /* The line, plus the two things a reader does with it: hover to read a
     close off any day, and drag across a stretch to read the move between
     its ends — what Google Finance does, measured on the same closes. */
  function drawChart(d, box) {
    var rows = ((d && d.candles) || []).filter(function (r) { return r && typeof r[4] === 'number' && isFinite(r[4]); });
    if (rows.length < 2) {
      box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
        'font-size:13px">Not enough history to draw this range.</div>';
      return;
    }
    var closes = rows.map(function (r) { return r[4]; });
    var n = closes.length, cur = d.currency;
    var intraday = isIntraday(chartRange);
    /* What a move is measured from: the close before the window when the API
       sends one (the intraday windows), else the window's first close. On 1D
       that is yesterday's close, drawn as a dashed line, as a quote screen does. */
    var base = (intraday && typeof d.base_close === 'number') ? d.base_close : closes[0];
    var showBase = chartRange === '1D' && base !== closes[0];
    var lo = Math.min.apply(null, closes.concat(showBase ? [base] : []));
    var hi = Math.max.apply(null, closes.concat(showBase ? [base] : []));
    var pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;

    var W = 1000, H = 250;
    var x = function (i) { return (i / (n - 1)) * W; };
    var y = function (v) { return H - ((v - lo) / (hi - lo)) * H; };

    var pts = closes.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var area = line + ' L' + W + ',' + H + ' L0,' + H + ' Z';
    var rising = closes[n - 1] >= base;
    var stroke = rising ? 'var(--sh-up)' : 'var(--sh-dn)';
    var label = (RANGES.filter(function (r) { return r[0] === chartRange; })[0] || [])[1] || '';

    var periodLow = Math.min.apply(null, closes), periodHigh = Math.max.apply(null, closes);
    var last = closes[n - 1], position = periodHigh === periodLow ? 50 : 100 * (last - periodLow) / (periodHigh - periodLow);
    var pullback = periodHigh ? 100 * (last / periodHigh - 1) : null;
    var guides = [0.15, 0.5, 0.85].map(function (f) {
      return '<div class="sc-guide" style="top:' + (f * 100) + '%"><span>' + esc(money(hi - f * (hi - lo), cur)) + '</span></div>';
    }).join('');
    box.innerHTML =
      '<div class="sc-eyebrow"><span>CLOSING PRICE</span><span>' + esc(cur || 'Price') + ' · ' + n + ' observations</span></div>' +
      '<div class="sc-read" aria-hidden="true">' +
        '<div class="sc-price tnum"></div>' +
        '<div class="sc-sub"><span class="sc-chg tnum"></span><span class="sc-when"></span></div>' +
      '</div>' +
      '<div class="sc-plot ' + (rising ? 'rise' : 'fall') + '" tabindex="0" role="application" ' +
        'aria-roledescription="price chart" aria-describedby="chart-close-value" ' +
        'aria-label="Closing prices for ' + esc(TICKER) + '. Arrow keys move through days; ' +
        'hold Shift to measure the change across a stretch.">' +
        '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs><linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" stop-color="' + stroke + '" stop-opacity=".26"/>' +
          '<stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/>' +
        '</linearGradient>' +
        '<linearGradient id="scSelG" x1="0" y1="0" x2="0" y2="1">' +
          '<stop class="sc-sel-stop" offset="0" stop-opacity=".32"/>' +
          '<stop class="sc-sel-stop" offset="1" stop-opacity="0"/>' +
        '</linearGradient>' +
        '<clipPath id="scClip"><rect class="sc-clip" x="0" y="-10" width="0" height="' + (H + 20) + '"/></clipPath>' +
        '</defs>' +
        '<g class="sc-base">' +
          '<path class="spark-fill" d="' + area + '"/>' +
          '<path class="spark-line' + (REDUCED ? '' : ' spark-draw') + '" d="' + line +
            '" style="stroke:' + stroke + '"/>' +
        '</g>' +
        '<g class="sc-sel" clip-path="url(#scClip)">' +
          '<path class="sc-sel-fill" d="' + area + '" fill="url(#scSelG)"/>' +
          '<path class="sc-sel-line" d="' + line + '"/>' +
        '</g>' +
        '</svg>' + guides +
        '<div class="sc-latest" aria-hidden="true" style="top:' + (100 * y(last) / H).toFixed(2) + '%;color:' + stroke + '"><i></i></div>' +
        (showBase ? '<div class="sc-base-line" style="top:' + (100 * y(base) / H).toFixed(2) + '%">' +
          '<span>Prev close ' + esc(money(base, cur)) + '</span></div>' : '') +
        '<div class="sc-band"></div>' +
        '<div class="sc-x sc-x-a"></div><div class="sc-x sc-x-b"></div>' +
        '<div class="sc-dot sc-dot-a"></div><div class="sc-dot sc-dot-b"></div>' +
        '<div class="sc-tip" role="presentation"></div>' +
      '</div>' +
      '<div class="sc-foot"><span>' + esc(when(0)) + '</span><span>' + esc(when(n - 1)) + '</span></div>' +
      '<div class="sc-tools"><span class="sc-hint">Hover to inspect · drag to measure</span>' +
        '<button type="button" class="sc-reset">Reset view</button></div>' +
      '<div class="sc-insights">' +
        '<div><span>Lowest close</span><strong>' + esc(money(periodLow, cur)) + '</strong><small>' + esc(when(closes.indexOf(periodLow))) + '</small></div>' +
        '<div><span>Highest close</span><strong>' + esc(money(periodHigh, cur)) + '</strong><small>' + esc(when(closes.indexOf(periodHigh))) + '</small></div>' +
        '<div><span>From highest close</span><strong>' + esc(pct(pullback)) + '</strong><small>Latest close vs period high</small></div>' +
      '</div>' +
      '<div class="sc-position"><div><span>Latest close in this range</span><b>' + (periodHigh === periodLow ? 'Unchanged throughout' : Math.round(position) + '% of the way from low to high') + '</b></div>' +
        '<div class="sc-rail"><i style="--position:' + position.toFixed(2) + '%"></i></div>' +
      '</div><p class="sc-source">Closing prices, latest ' + esc(when(n - 1)) + '. Not a live tick.</p>' +
      '<output class="ux-chart-value sc-sr" id="chart-close-value" aria-live="polite"></output>';

    var plot = box.querySelector('.sc-plot');
    var q = function (s) { return box.querySelector(s); };
    var el = {
      price: q('.sc-price'), chg: q('.sc-chg'), when: q('.sc-when'),
      band: q('.sc-band'), xa: q('.sc-x-a'), xb: q('.sc-x-b'),
      da: q('.sc-dot-a'), db: q('.sc-dot-b'), tip: q('.sc-tip'),
      clip: q('.sc-clip'), out: q('#chart-close-value')
    };

    function pctOf(a, b) { return closes[a] ? 100 * (closes[b] - closes[a]) / closes[a] : null; }
    function fromBase(i) { return base ? 100 * (closes[i] - base) / base : null; }
    function when(i) { return intraday ? barTime(rows[i][0], chartRange !== '1D') : dayLabel(rows[i][0]); }
    function signed(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + money(Math.abs(v), cur); }
    function arrow(v) { return v > 0 ? '▲ ' : v < 0 ? '▼ ' : ''; }
    function place(node, i) {
      node.style.left = (100 * i / (n - 1)) + '%';
      node.style.top = (100 * y(closes[i]) / H) + '%';
    }
    function setRead(price, chgV, chgP, when) {
      el.price.textContent = money(price, cur);
      el.chg.className = 'sc-chg tnum ' + tone(chgV);
      el.chg.textContent = chgP == null ? '' : arrow(chgV) + signed(chgV) + ' (' + pct(Math.abs(chgP)).replace('+', '') + ')';
      el.when.textContent = when;
    }
    function tipAt(i, html) {
      el.tip.innerHTML = html;
      var f = i / (n - 1);
      el.tip.style.left = (100 * f) + '%';
      // Keep the card inside the box at both edges.
      el.tip.style.transform = 'translateX(' + (f < 0.12 ? '0' : f > 0.88 ? '-100%' : '-50%') + ')';
      el.tip.classList.toggle('edge-l', f < 0.12);
      el.tip.classList.toggle('edge-r', f > 0.88);
    }

    function rest() {
      plot.classList.remove('hovering', 'measuring', 'up', 'dn');
      el.out.textContent = 'Latest close ' + money(last, cur) + ' · ' + when(n - 1);
      var ch = closes[n - 1] - base;
      setRead(closes[n - 1], ch, fromBase(n - 1),
        chartRange === '1D' ? 'today' : (label ? 'past ' + label : ''));
    }

    function hover(i) {
      plot.classList.remove('measuring', 'up', 'dn');
      plot.classList.add('hovering');
      place(el.xa, i); place(el.da, i);
      var date = when(i);
      var ch = closes[i] - base;
      setRead(closes[i], ch, fromBase(i), date);
      tipAt(i, '<b class="tnum">' + esc(money(closes[i], cur)) + '</b><span>' + esc(date) + '</span>');
      el.out.textContent = date + ' · Close ' + money(closes[i], cur);
    }

    function measure(a, b) {
      if (a === b) return hover(b);
      var from = Math.min(a, b), to = Math.max(a, b);
      var ch = closes[to] - closes[from], p = pctOf(from, to);
      var dir = ch >= 0 ? 'up' : 'dn';
      plot.classList.add('hovering', 'measuring');
      plot.classList.toggle('up', dir === 'up');
      plot.classList.toggle('dn', dir === 'dn');
      place(el.xa, a); place(el.da, a); place(el.xb, b); place(el.db, b);
      el.band.style.left = (100 * from / (n - 1)) + '%';
      el.band.style.width = (100 * (to - from) / (n - 1)) + '%';
      el.clip.setAttribute('x', x(from).toFixed(1));
      el.clip.setAttribute('width', (x(to) - x(from)).toFixed(1));
      var d0 = when(from), d1 = when(to);
      var gap = intraday ? span(rows[from][0], rows[to][0]) : '';
      if (!intraday) {
        var days = daysBetween(rows[from][0], rows[to][0]);
        gap = days == null ? '' : days + (days === 1 ? ' day' : ' days');
      }
      setRead(closes[to], ch, p, d0 + ' → ' + d1);
      tipAt((from + to) / 2,
        '<b class="tnum ' + tone(ch) + '">' + arrow(ch) + esc(pct(p)) + '</b>' +
        '<span class="tnum">' + esc(signed(ch)) + (gap ? ' · ' + esc(gap) : '') + '</span>');
      el.out.textContent = 'From ' + d0 + ' to ' + d1 + ': ' + pct(p) + ', ' + signed(ch);
    }

    // Pointer: move to read, press and drag to measure.
    var anchor = null, head = n - 1, dragging = false;
    function idxAt(e) {
      var r = plot.getBoundingClientRect();
      var f = Math.max(0, Math.min(1, (e.clientX - r.left) / (r.width || 1)));
      return Math.round(f * (n - 1));
    }
    plot.addEventListener('pointermove', function (e) {
      head = idxAt(e);
      if (dragging) measure(anchor, head); else if (e.pointerType === 'mouse') hover(head);
    });
    plot.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      dragging = true;
      anchor = head = idxAt(e);
      try { plot.setPointerCapture(e.pointerId); } catch (err) {}
      hover(head);
      if (window.AltahaTrack) window.AltahaTrack('chart_measure_started', { range: chartRange });
    });
    function release(e) {
      if (!dragging) return;
      dragging = false;
      try { plot.releasePointerCapture(e.pointerId); } catch (err) {}
      // A tap or click is not a measurement; a finished drag stays up to be read.
      if (anchor === head) { anchor = null; }
    }
    plot.addEventListener('pointerup', release);
    plot.addEventListener('pointercancel', function (e) { release(e); anchor = null; rest(); });
    plot.addEventListener('pointerleave', function (e) {
      if (dragging || e.pointerType !== 'mouse' || anchor !== null) return;
      rest();
    });

    // Keyboard: arrows move, Shift+arrows measure from where Shift was first held.
    plot.addEventListener('keydown', function (e) {
      var k = e.key, step = e.ctrlKey || e.metaKey ? Math.max(1, Math.round(n / 10)) : 1, next = head;
      if (k === 'ArrowLeft') next = head - step;
      else if (k === 'ArrowRight') next = head + step;
      else if (k === 'Home') next = 0;
      else if (k === 'End') next = n - 1;
      else if (k === 'Escape') { anchor = null; rest(); return; }
      else return;
      e.preventDefault();
      next = Math.max(0, Math.min(n - 1, next));
      if (e.shiftKey) { if (anchor == null) anchor = head; head = next; measure(anchor, head); }
      else { anchor = null; head = next; hover(head); }
    });
    plot.addEventListener('blur', function () { if (!dragging) { anchor = null; rest(); } });

    q('.sc-reset').addEventListener('click', function () { anchor = null; head = n - 1; rest(); });
    rest();

    if (!REDUCED) {
      var path = box.querySelector('.spark-draw');
      if (path && path.getTotalLength) {
        var len = path.getTotalLength();
        path.style.setProperty('--len', len);
      }
    }
  }

  /* The method notes under a section. True, worth keeping, and nobody's first
     reason for opening the section: folded, one tap away. */
  function notesBlock(notes) {
    notes = (notes || []).filter(Boolean);
    if (!notes.length) return '';
    return '<details class="own-notes"><summary>Notes on these figures</summary>' +
      notes.map(function (n) { return '<p>' + esc(n) + '</p>'; }).join('') + '</details>';
  }

  /* ── Ownership ────────────────────────────────────────────────────────────
     The shareholding pattern, read from the company's own Reg 31 filing.

     THE ONE THING THIS SECTION MUST NOT DO
     In the exchange's format "Public" is the PARENT of the foreign, domestic
     and non-institutional lines, not their sibling. Drawing all four together
     double-counts roughly half the company. The API hands back `split` — the
     decomposition that does sum to 100 — and this renders only that. The
     reported public figure appears once, in prose, described as the total it
     is.

     COLOUR
     Four categorical hues, fixed per category and never cycled, validated for
     colour-vision deficiency against both surfaces rather than chosen by eye.
     Identity is never carried by colour alone: every series is directly
     labelled at its last point, repeated in the legend, and repeated again in
     the table under the chart. */

  var OWN_KEYS = ['promoter', 'dii', 'fii', 'public_non_institutional'];
  var OWN_SHORT = {
    promoter: 'Promoters',
    dii: 'DII',
    fii: 'FII',
    public_non_institutional: 'Public'
  };

  var ownLoaded = false;

  function pp(v, d) {
    var n = num(v, d == null ? 2 : d);
    if (n == null) return '—';
    return (n > 0 ? '+' : '') + n.toFixed(d == null ? 2 : d) + ' pp';
  }
  function crore(v) {
    var n = Number(v);
    if (!isFinite(n) || n === 0) return '—';
    if (Math.abs(n) >= 1e7) return (n / 1e7).toFixed(2) + ' cr';
    if (Math.abs(n) >= 1e5) return (n / 1e5).toFixed(2) + ' lakh';
    return n.toLocaleString('en-IN');
  }
  function holders(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return Math.round(n).toLocaleString('en-IN');
  }

  /* The composition bar. One row, six segments at most, 2px of surface between
     each so adjacent fills never read as one. */
  function ownBar(split) {
    var parts = split.filter(function (s) { return s.pct > 0.05; });
    return '<div class="own-bar" role="img" aria-label="Shareholding composition">' +
      parts.map(function (s) {
        return '<i class="seg s-' + esc(s.key) + '" style="flex:' + s.pct + '" ' +
          'title="' + esc(s.label) + ' ' + s.pct.toFixed(2) + '%"></i>';
      }).join('') + '</div>';
  }

  /* The trend. Four series on one percentage axis — never two scales. */
  /* One panel per category: the number, how it moved, and its own sparkline.
     Replaces a four-series line chart and a separate row list that showed the
     same four things twice.

     WHY SMALL MULTIPLES AND NOT ONE CHART
     Promoters sit near 62% and domestic institutions near 1%. On one linear
     axis that is a line at the top, two lines flattened onto the floor, and
     two-thirds of the plot empty in between — and the end labels of the two
     floor-level series land on top of each other. Each panel here gets its own
     scale, so a move from 3.17% to 1.36% is visible movement rather than a
     twitch, and no two labels can ever collide because no panel has more than
     one series. */
  function spark(points, key) {
    if (!points || points.length < 2) {
      return '<div class="op-nospark">Not enough quarter-ends to plot yet</div>';
    }
    var W = 260, H = 46, P = 3;
    var vals = points.map(function (p) { return p.v; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    // A dead-flat series would divide by zero and draw at the top edge; give
    // it a band so it reads as the flat line it is, centred.
    if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
    var pad = (hi - lo) * 0.18;
    lo -= pad; hi += pad;

    function x(i) { return P + (i / (points.length - 1)) * (W - P * 2); }
    function y(v) { return P + (1 - (v - lo) / (hi - lo)) * (H - P * 2); }

    var d = points.map(function (p, i) {
      return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.v).toFixed(1);
    }).join(' ');
    var area = d + ' L' + x(points.length - 1).toFixed(1) + ' ' + (H - P) +
               ' L' + x(0).toFixed(1) + ' ' + (H - P) + ' Z';
    var last = points[points.length - 1];

    var hits = points.map(function (p, i) {
      var bw = (W - P * 2) / Math.max(1, points.length - 1);
      return '<rect class="oh" x="' + (x(i) - bw / 2).toFixed(1) + '" y="0" width="' +
        bw.toFixed(1) + '" height="' + H + '" data-period="' + esc(p.label) +
        '" data-val="' + p.v.toFixed(2) + '"></rect>';
    }).join('');

    return '<svg class="op-spark s-' + esc(key) + '" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none" role="img" aria-label="' +
      points.length + ' quarters, ' + points[0].v.toFixed(2) + '% to ' +
      last.v.toFixed(2) + '%">' +
      '<path class="ar" d="' + area + '"/>' +
      '<path class="ln" d="' + d + '"/>' +
      '<circle class="dt" cx="' + x(points.length - 1).toFixed(1) + '" cy="' +
        y(last.v).toFixed(1) + '" r="2.6"/>' + hits + '</svg>';
  }

  /* A change chip. `fmt` decides how the magnitude reads, because percentage
     points and people are not the same quantity: 0.48 points is meaningful to
     two decimals, and "+230574.00 shareholders" is not a number anyone wrote. */
  function chip(v, unit, fmt) {
    if (v == null) return '<span class="op-chip none">—<b>' + unit + '</b></span>';
    var t = Math.abs(v) < (fmt ? 0.5 : 0.005) ? 'flat' : (v > 0 ? 'up' : 'dn');
    var sign = v > 0 ? '+' : (v < 0 ? '−' : '');
    var mag = fmt ? fmt(Math.abs(v)) : Math.abs(v).toFixed(2);
    return '<span class="op-chip ' + t + '">' + sign + mag +
      '<b>' + unit + '</b></span>';
  }

  function ownPanels(split, history) {
    // Only quarter-ends go on the line. An interim filing a fortnight after
    // the last one would otherwise occupy the same width as a full quarter.
    var qs = (history || []).filter(function (h) { return h.quarter_end !== false; });
    var by = {};
    OWN_KEYS.forEach(function (k) {
      by[k] = qs.filter(function (h) { return h[k] != null; })
               .map(function (h) { return { v: h[k], label: String(h.period).slice(0, 7) }; });
    });

    var order = OWN_KEYS.filter(function (k) {
      return split.some(function (s) { return s.key === k; });
    });
    // Anything outside the four main lines (government, custodian) still has a
    // row, just without a panel of its own.
    var extras = split.filter(function (s) { return OWN_KEYS.indexOf(s.key) < 0; });

    var panels = order.map(function (k) {
      var s = split.filter(function (x) { return x.key === k; })[0];
      var pts = by[k] || [];
      // Labelled "range", because a bare pair of numbers under a line reads as
      // first-and-last and these are lowest-and-highest.
      var vals = pts.map(function (p) { return p.v; });
      var range = pts.length > 1
        ? '<div class="op-range"><span>' + pts.length + ' quarters</span>' +
          '<span><b>range</b> ' + Math.min.apply(null, vals).toFixed(2) + '–' +
          Math.max.apply(null, vals).toFixed(2) + '</span></div>'
        : '';
      return '<article class="op s-' + esc(k) + '">' +
        '<header><i></i><h3>' + esc(s.label) + '</h3>' +
          (s.derived ? '<em class="drv" title="Not filed as its own line in this quarter’s format; derived from the totals the filing does report">derived</em>' : '') +
        '</header>' +
        '<div class="op-val tnum">' + s.pct.toFixed(2) + '<span>%</span></div>' +
        '<div class="op-chips">' + chip(s.change_qoq, 'QoQ') + chip(s.change_yoy, 'YoY') + '</div>' +
        spark(pts, k) + range +
        '<div class="op-holders">' +
          (s.holders == null ? '—' : holders(s.holders)) +
          '<b>' + (s.holders === 1 ? 'holder' : 'holders') + '</b>' +
          (s.holders_change_qoq
            ? '<em class="' + tone(s.holders_change_qoq) + '">' +
              (s.holders_change_qoq > 0 ? '+' : '−') +
              holders(Math.abs(s.holders_change_qoq)) + '</em>' : '') +
        '</div>' +
        '</article>';
    }).join('');

    var rest = extras.length
      ? '<div class="op-rest">' + extras.map(function (s) {
          return '<span><i class="s-' + esc(s.key) + '"></i>' + esc(s.label) +
            '<b class="tnum">' + s.pct.toFixed(2) + '%</b></span>';
        }).join('') + '</div>'
      : '';

    return '<div class="op-grid">' + panels + '</div>' + rest +
      '<div class="own-read" id="own-read" aria-live="polite"></div>';
  }

  function ownNames(list, heading, empty) {
    if (!list || !list.length) return '<div class="own-empty">' + esc(empty) + '</div>';
    return '<h3 class="own-h3">' + esc(heading) + '</h3>' +
      '<ul class="own-names">' + list.map(function (n) {
        var ch = n.change_qoq;
        var badge = n.new_in_table
          ? '<em class="new">new in table</em>'
          : (ch == null ? '<em class="flat">comparison unavailable</em>' : Math.abs(ch) < 0.005
              ? '<em class="flat">unchanged</em>'
              : '<em class="' + tone(ch) + '">' + pp(ch) + '</em>');
        return '<li><span class="nm">' + esc(n.name) + '</span>' +
          '<span class="kd">' + esc(n.kind || '') + '</span>' +
          '<span class="vv tnum">' + n.pct.toFixed(2) + '%</span>' + badge + '</li>';
      }).join('') + '</ul>';
  }

  /* The table the chart is an illustration of. Required, not a fallback: a
     reader who cannot separate two hues still gets every number. */
  function ownTable(history) {
    var rows = (history || []).slice().reverse();
    if (!rows.length) return '';
    return '<details class="own-more"><summary>All figures, quarter by quarter</summary>' +
      '<div class="own-tablewrap"><table class="own-table">' +
      '<caption>Shareholding by category, percent of total shares. Source column links the filing.</caption>' +
      '<thead><tr><th scope="col">Quarter ended</th>' +
      OWN_KEYS.map(function (k) { return '<th scope="col">' + esc(OWN_SHORT[k]) + '</th>'; }).join('') +
      '<th scope="col">Shareholders</th><th scope="col">Filed</th><th scope="col">Source</th></tr></thead><tbody>' +
      rows.map(function (h) {
        return '<tr><th scope="row">' + esc(h.period) + '</th>' +
          OWN_KEYS.map(function (k) {
            return '<td class="tnum">' + (h[k] == null ? '—' : h[k].toFixed(2) + '%') + '</td>';
          }).join('') +
          '<td class="tnum">' + holders(h.holders) + '</td>' +
          '<td>' + esc(h.filed || '—') + (h.revised ? ' <em>revised</em>' : '') + '</td>' +
          '<td>' + (h.source ? '<a href="' + esc(h.source) + '" target="_blank" rel="noopener">XBRL</a>' : '—') + '</td>' +
          '</tr>';
      }).join('') + '</tbody></table></div></details>';
  }

  function wireOwnHover() {
    var read = $('own-read');
    if (!read) return;
    [].slice.call(document.querySelectorAll('.op-spark')).forEach(function (svg) {
      function show(e) {
        var t = e.target;
        if (!t || !t.classList || !t.classList.contains('oh')) return;
        var panel = svg.closest ? svg.closest('.op') : null;
        var who = panel ? panel.querySelector('h3').textContent : '';
        read.innerHTML = '<b>' + esc(t.dataset.period) + '</b> · ' + esc(who) +
          ' ' + esc(t.dataset.val) + '%';
      }
      svg.addEventListener('mousemove', show);
      svg.addEventListener('focusin', show);
      svg.addEventListener('mouseleave', function () { read.innerHTML = ''; });
    });
  }

  function paintOwnership(d) {
    var box = $('own-body');
    if (!box) return;

    if (!d || !d.available) {
      box.innerHTML = '<div class="own-empty">' +
        esc((d && d.message) || 'No shareholding filing could be read for this company.') +
        '</div>';
      return;
    }

    var split = (d.split || []).filter(function (s) { return s.pct != null; });
    var t = d.totals || {};

    // Lead with the finding: the biggest mover this quarter, named in a
    // sentence, before any chart.
    var movers = split.filter(function (s) {
      return s.change_qoq != null && Math.abs(s.change_qoq) >= 0.05;
    }).sort(function (a, b) { return Math.abs(b.change_qoq) - Math.abs(a.change_qoq); });
    var lead;
    if (!movers.length) {
      lead = split.some(function (s) { return s.change_qoq != null; })
        ? 'No comparable category moved by more than a twentieth of a point over the quarter.'
        : 'Quarter-on-quarter comparison is unavailable for the filings read.';
    } else {
      var m = movers[0];
      lead = m.label + ' ' + (m.change_qoq > 0 ? 'rose' : 'fell') + ' ' +
        Math.abs(m.change_qoq).toFixed(2) + ' percentage points over the quarter, to ' +
        m.pct.toFixed(2) + '%.';
      if (movers.length > 1) {
        var n2 = movers[1];
        lead += ' ' + n2.label + ' ' + (n2.change_qoq > 0 ? 'rose' : 'fell') + ' ' +
          Math.abs(n2.change_qoq).toFixed(2) + '.';
      }
    }

    if (d.basis_period && d.basis_period !== d.period) {
      lead = 'Latest holdings are from the interim filing dated ' + d.period +
        '. Quarterly changes compare quarter-ends through ' + d.basis_period + '; they do not describe changes since the interim filing.';
    }

    var read = (d.quarters_read || 0) + ' quarter-end' +
      ((d.quarters_read === 1) ? '' : 's') +
      (d.interim_filings ? ' and ' + d.interim_filings + ' interim filing' +
        (d.interim_filings === 1 ? '' : 's') : '') + ' read';
    var head = '<p class="own-lead">' + esc(lead) + '</p>' +
      '<p class="own-asof">As filed for <b>' + esc(d.period || '—') + '</b>' +
      (d.filed ? ', filed ' + esc(d.filed) : '') + '. ' + esc(read) + '.' +
      (d.latest_source ? ' <a href="' + esc(d.latest_source) +
        '" target="_blank" rel="noopener">Open the filing</a>.' : '') + '</p>';

    var count = '';
    if (t.holders != null) {
      count = '<div class="own-count">' +
        '<div class="big tnum">' + holders(t.holders) + '</div>' +
        '<div class="lb">shareholders on the register</div>' +
        '<div class="ch">' +
          chip(t.holders_change_qoq, 'QoQ', holders) +
          chip(t.holders_change_yoy, 'YoY', holders) +
        '</div></div>';
    }

    var notes = notesBlock(d.notes);

    box.innerHTML = head + '<div id="own-intelligence"></div>' + ownBar(split) +
      ownPanels(split, d.history) + count + ownTable(d.history) +
      '<div class="own-namecols">' +
      '<div>' + ownNames(d.names && d.names.promoters, 'Promoter group',
        'This company reports no promoter holding.') + '</div>' +
      '<div>' + ownNames(d.names && d.names.public, 'Public holders above 1%',
        'No public holder crosses one per cent in this filing.') + '</div>' +
      '</div>' + notes;

    wireOwnHover();
    if (window.OwnershipInsights) window.OwnershipInsights.mount(d, {ticker:TICKER, api:API, name:$('nm').textContent});
  }

  function loadOwnership() {
    var box = $('own-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the filings…</div>';
    }
    fetch(API + '/shareholding?ticker=' + encodeURIComponent(TICKER) + '&quarters=8&names=40')
      .then(function (r) {
        if (!r.ok) throw new Error('down');
        return r.json();
      })
      .then(paintOwnership)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="own-empty">The filings could not be read ' +
            'just now. Try again in a moment.</div>';
        }
      });
  }


  /* ── Fundamentals ─────────────────────────────────────────────────────────
     The quarterly P&L as filed, the ratios that follow from it, and a change
     column.

     A TABLE, DELIBERATELY
     Sixteen line items against six quarters with a change column is tabular
     data, and a reader comparing two quarters of "other expenses" wants the
     number, not a mark whose length they have to estimate. The sparklines in
     the ratio block earn their place because a trend is the question there;
     in the P&L the question is "what was it", and the answer is a figure.

     THE TWO THINGS THIS MUST NOT DO
     Mix accounting bases — the payload carries one basis and names it, and
     the basis is printed at the top rather than assumed. And print a
     percentage across zero: a company that lost money and then made money has
     not grown by a percentage, so the payload sends a `kind` and this renders
     the words instead of inventing a number. */

  var fundaLoaded = false;

  function cr(v) {
    if (v == null || isNaN(Number(v))) return '—';
    var n = Number(v) / 1e7;
    var a = Math.abs(n);
    var s = a >= 1000 ? n.toFixed(0) : (a >= 10 ? n.toFixed(1) : n.toFixed(2));
    return Number(s).toLocaleString('en-IN');
  }
  function plain(v, d) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(Number(v).toFixed(d == null ? 2 : d)).toLocaleString('en-IN');
  }

  /* The change cell. `kind` comes from the API precisely so this never has to
     infer a turnaround from a sign.

     Two vocabularies, because one does not fit. On profit after tax "to
     profit" is exactly the right phrase; on the tax line it is nonsense — tax
     going from a credit to a charge is not a company turning profitable. So
     the profit lines get the profit words and everything else gets the
     sign words, which are true of any line. */
  var PROFIT_LINES = {
    pbt_before_exceptional: 1, pbt: 1, pat: 1, eps_basic: 1, exceptional: 1
  };
  var KIND_WORDS = {
    loss_to_profit: 'to profit',
    profit_to_loss: 'to loss',
    loss_widened: 'loss wider',
    loss_narrowed: 'loss narrower',
    unavailable: '—',
    flat: 'flat'
  };
  var SIGN_WORDS = {
    loss_to_profit: 'to positive',
    profit_to_loss: 'to negative',
    loss_widened: 'more negative',
    loss_narrowed: 'less negative',
    unavailable: '—',
    flat: 'flat'
  };
  function words(key) { return PROFIT_LINES[key] ? KIND_WORDS : SIGN_WORDS; }

  function changeCell(c, key) {
    if (!c || c.kind === 'unavailable') return '<td class="fu-ch none">—</td>';
    /* Nil in both quarters — exceptional items, usually. "Flat" is true but it
       says a line moved nowhere when the line was never there. */
    if (c.pct == null && c.kind === 'flat' && !c.abs)
      return '<td class="fu-ch none">—</td>';
    if (c.pct == null) {
      var word = words(key)[c.kind] || 'changed';
      var t = (c.kind === 'loss_to_profit' || c.kind === 'loss_narrowed') ? 'up'
            : (c.kind === 'profit_to_loss' || c.kind === 'loss_widened') ? 'dn' : '';
      return '<td class="fu-ch word ' + t + '" title="A percentage change needs a ' +
        'positive base to mean anything">' + esc(word) + '</td>';
    }
    var tone2 = c.pct > 0.005 ? 'up' : (c.pct < -0.005 ? 'dn' : '');
    return '<td class="fu-ch ' + tone2 + ' tnum">' +
      (c.pct > 0 ? '+' : '') + c.pct.toFixed(1) + '%</td>';
  }

  function fundaTable(d) {
    var rows = d.rows || [];
    if (!rows.length) return '';
    var latest = rows[0];
    var older = rows.slice(1);

    var head = '<tr><th scope="col" class="fu-line">₹ crore</th>' +
      '<th scope="col" class="fu-now">' + esc(latest.label || '') + '</th>' +
      '<th scope="col" class="fu-chh">' +
        (latest.yoy_against ? 'vs ' + esc(latest.yoy_against) : 'YoY') + '</th>' +
      '<th scope="col" class="fu-chh">' +
        (latest.qoq_against ? 'vs ' + esc(latest.qoq_against) : 'QoQ') + '</th>' +
      older.map(function (r) {
        return '<th scope="col">' + esc(r.label || '') + '</th>';
      }).join('') + '</tr>';

    var body = (d.lines || []).map(function (ln) {
      var v = latest.values || {};
      var isKey = ln.key === 'revenue' || ln.key === 'ebitda' || ln.key === 'pat';
      var money = ln.unit !== 'rupees';
      var fmt = money ? cr : function (x) { return plain(x, 2); };
      /* The column header reads "₹ crore". EPS is rupees per share, so it says
         so on its own row rather than being read off by a factor of a crore. */
      return '<tr' + (isKey ? ' class="key"' : '') + '>' +
        '<th scope="row" class="fu-line">' + esc(ln.label) +
          (money ? '' : '<em>₹ per share</em>') + '</th>' +
        '<td class="fu-now tnum">' + fmt(v[ln.key]) + '</td>' +
        changeCell((latest.yoy || {})[ln.key], ln.key) +
        changeCell((latest.qoq || {})[ln.key], ln.key) +
        older.map(function (r) {
          return '<td class="tnum">' + fmt((r.values || {})[ln.key]) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    /* The note sits OUTSIDE the scroller. Inside it, it is as wide as the
       table and gets clipped at the viewport edge on a phone — which is where
       it matters most, because that is where the basis is least visible. */
    return '<h3 class="fu-h3">Profit and loss</h3>' +
      '<p class="fu-cap" id="fu-cap-pl">' + esc(d.basis.charAt(0).toUpperCase() + d.basis.slice(1)) +
      ', ₹ crore. Change against the same quarter a year earlier, then against the quarter before.</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table" aria-describedby="fu-cap-pl">' +
      '<caption class="fu-vh">Quarterly profit and loss, ' + esc(d.basis) +
      ' basis, in rupees crore</caption>' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div></div>';
  }

  function ratioSpark(rows, key) {
    var pts = rows.slice().reverse()
      .map(function (r) { return (r.ratios || {})[key]; })
      .filter(function (v) { return v != null; });
    if (pts.length < 2) return '';
    var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
    if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
    var W = 96, H = 22;
    var d = pts.map(function (v, i) {
      var x = (i / (pts.length - 1)) * W;
      var y = (1 - (v - lo) / (hi - lo)) * (H - 4) + 2;
      return (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
    }).join(' ');
    return '<svg class="fu-spark" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none" aria-hidden="true"><path d="' + d + '"/></svg>';
  }

  function fundaRatios(d) {
    var rows = d.rows || [];
    if (!rows.length) return '';
    var latest = rows[0], older = rows.slice(1);
    var body = (d.ratio_defs || []).map(function (rd) {
      var unit = rd.key === 'interest_cover_x' ? '×' : '%';
      var val = (latest.ratios || {})[rd.key];
      /* The unit goes on the row label. Suffixing every cell in six columns is
         noise; suffixing only the latest leaves the older quarters looking
         like a different quantity. */
      return '<tr>' +
        '<th scope="row" class="fu-line">' + esc(rd.label) +
          '<em>' + esc(rd.formula) + ', ' + unit + '</em></th>' +
        '<td class="fu-now tnum">' + (val == null ? '—' : plain(val, 2) + unit) + '</td>' +
        '<td class="fu-sp">' + ratioSpark(rows, rd.key) + '</td>' +
        older.map(function (r) {
          var x = (r.ratios || {})[rd.key];
          return '<td class="tnum">' + (x == null ? '—' : plain(x, 2)) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    var head = '<tr><th scope="col" class="fu-line">Ratio</th>' +
      '<th scope="col" class="fu-now">' + esc(latest.label || '') + '</th>' +
      '<th scope="col" class="fu-sp">Trend</th>' +
      older.map(function (r) {
        return '<th scope="col">' + esc(r.label || '') + '</th>';
      }).join('') + '</tr>';

    return '<h3 class="fu-h3">Ratios</h3>' +
      '<p class="fu-cap" id="fu-cap-ratios">From the lines above. Blank where the ' +
      'denominator is zero or negative.</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table fu-ratios" aria-describedby="fu-cap-ratios">' +
      '<caption class="fu-vh">Quarterly ratios</caption>' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div></div>';
  }

  function paintFunda(d) {
    var box = $('funda-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="own-empty">' +
        esc((d && d.message) || 'The filings could not be read.') + '</div>';
      return;
    }
    var rows = d.rows || [];
    var latest = rows[0] || {};
    var rev = (latest.yoy || {}).revenue || {};
    var pat = (latest.yoy || {}).pat || {};

    var LEAD_WORDS = {
      loss_to_profit: 'turned from a loss into a profit',
      profit_to_loss: 'turned from a profit into a loss',
      loss_widened: 'lost more',
      loss_narrowed: 'lost less',
      flat: 'was unchanged'
    };
    function phrase(c, what) {
      if (!c || c.kind === 'unavailable') return '';
      if (c.pct != null) {
        if (Math.abs(c.pct) < 0.05) return what + ' was flat';
        return what + ' ' + (c.pct > 0 ? 'grew' : 'fell') + ' ' +
          Math.abs(c.pct).toFixed(1) + '%';
      }
      return what + ' ' + (LEAD_WORDS[c.kind] || 'changed');
    }
    var bits = [phrase(rev, 'Revenue'), phrase(pat, 'profit after tax')]
      .filter(Boolean);
    var lead = bits.length
      ? bits.join(' and ') + ' against ' + (latest.yoy_against || 'a year earlier') + '.'
      : 'Not enough history yet to compare this quarter with a year earlier.';

    var alts = (d.basis_alternatives || []).filter(function (b) { return b !== d.basis; });
    var head = '<p class="own-lead">' + esc(lead) + '</p>' +
      '<p class="own-asof">' +
        '<b>' + esc(d.basis) + '</b> results — ' + esc(d.basis_reason) + '. ' +
        esc(String(d.count)) + ' quarter' + (d.count === 1 ? '' : 's') + ' read' +
        (d.partial ? ' of ' + esc(String(d.requested)) + ' asked for' : '') + '.' +
        (alts.length ? ' The company also files ' + esc(alts.join(' and ')) + '.' : '') +
        (latest.source ? ' <a href="' + esc(latest.source) +
          '" target="_blank" rel="noopener">Open the filing</a>.' : '') +
      '</p>';

    box.innerHTML = head + fundaTable(d) + fundaRatios(d) + notesBlock(d.notes);
    paintTrend(d);
  }

  /* The quarters as bars, above the table that holds them to the rupee. A
     reader sees the direction here and reads the amount there; the bars are
     drawn from the same rows, so they cannot show a different year. A loss
     hangs below the line rather than standing on it. */
  function paintTrend(d) {
    var host = $('funda-trend');
    if (!host) return;
    var rows = (d.rows || []).slice().reverse();          // oldest first
    function series(key) {
      return rows.map(function (r) {
        var v = (r.values || {})[key];
        return { label: r.label || '', v: (v == null || isNaN(Number(v))) ? null : Number(v) / 1e7 };
      });
    }
    function chart(title, key) {
      var pts = series(key);
      var vals = pts.filter(function (p) { return p.v != null; }).map(function (p) { return p.v; });
      if (vals.length < 2) return '';
      var top = Math.max.apply(null, vals.concat([0])), bot = Math.min.apply(null, vals.concat([0]));
      var span = (top - bot) || 1, zero = 100 * top / span;
      var last = pts[pts.length - 1];
      return '<figure class="ft"><figcaption><span>' + esc(title) + '</span><b class="tnum">' +
        (last.v == null ? '—' : '₹' + cr(last.v * 1e7) + ' cr') + '</b></figcaption>' +
        '<div class="ft-plot" style="--zero:' + zero.toFixed(1) + '%">' + pts.map(function (p, i) {
          if (p.v == null) return '<div class="ft-c"><span class="ft-x">' + esc(p.label) + '</span></div>';
          var h = 100 * Math.abs(p.v) / span;
          return '<div class="ft-c" title="' + esc(p.label + ': ₹' + cr(p.v * 1e7) + ' cr') + '">' +
            '<i class="' + (p.v < 0 ? 'neg' : '') + (i === pts.length - 1 ? ' now' : '') +
            '" style="--h:' + h.toFixed(1) + '%;--i:' + i + '"></i>' +
            '<span class="ft-x">' + esc(p.label) + '</span></div>';
        }).join('') + '</div></figure>';
    }
    var html = chart('Revenue', 'revenue') + chart('Profit after tax', 'pat');
    host.innerHTML = html ? '<div class="ft-row">' + html + '</div>' : '';
  }

  /* ── Against its industry ────────────────────────────────────────────────
     Each measure beside the median of the company's NSE industry and how many
     peers it is ahead of. The API shows a measure only when enough of the
     industry has recent results held, and says how much of it was read; this
     prints that rather than implying the whole industry. Whether higher is
     better is stated per row, never coloured as good or bad: a current ratio
     can be too high as easily as too low. */

  function peerVal(m, v) {
    if (v == null) return '—';
    return plain(v, 1) + (m.key.slice(-2) === '_x' ? '×' : '%');
  }

  function paintPeers(d) {
    var box = $('funda-peers');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = d && d.industry
        ? '<p class="fu-cap">' + esc(d.message || '') + '</p>' : '';
      return;
    }
    var body = d.measures.map(function (m) {
      var rank = m.above + ' of ' + m.peers;
      var dir = m.higher_is_better === true ? 'higher is better'
        : m.higher_is_better === false ? 'lower is better' : '';
      return '<tr>' +
        '<th scope="row" class="fu-line">' + esc(m.label) +
          (dir ? '<em>' + esc(dir) + '</em>' : '') + '</th>' +
        '<td class="fu-now tnum">' + peerVal(m, m.value) + '</td>' +
        '<td class="tnum">' + peerVal(m, m.median) + '</td>' +
        '<td class="tnum">' + esc(rank) + '</td></tr>';
    }).join('');
    box.innerHTML = '<h3 class="fu-h3">Against the industry median</h3>' +
      '<p class="fu-cap" id="fu-cap-peers">' + esc(d.industry) + ', as ' +
      esc(d.classifier || 'NSE') + ' classifies it. ' + esc(d.as_of || 'Latest') +
      ' results against the median of its peers.</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table fu-peers" aria-describedby="fu-cap-peers">' +
      '<caption class="fu-vh">Against the industry median</caption>' +
      '<thead><tr><th scope="col" class="fu-line">Measure</th>' +
      '<th scope="col" class="fu-now">This company</th>' +
      '<th scope="col">Industry median</th>' +
      '<th scope="col">Above</th></tr></thead>' +
      '<tbody>' + body + '</tbody></table></div></div>' + notesBlock(d.notes);
  }

  /* ── Balance sheet and cash flow ─────────────────────────────────────────
     Values arrive in ₹ crore already (the stored tables keep crore), so they
     are printed with plain() rather than cr(), which divides rupees. A line
     the company never filed is left out by the API, so a bank shows deposits
     and loans and a manufacturer inventories and receivables. */

  function statementTable(id, title, cap, part) {
    var rows = part.rows || [];
    if (!rows.length) return '';
    var head = '<tr><th scope="col" class="fu-line">₹ crore</th>' +
      rows.map(function (r, i) {
        return '<th scope="col"' + (i ? '' : ' class="fu-now"') + '>' +
          esc(r.label || r.period_end) + '</th>';
      }).join('') + '</tr>';
    function money(r, k) { return plain((r.values || {})[k], 0); }
    var lines = (part.lines || []).map(function (ln) {
      var isKey = ['total_assets', 'total_equity', 'total_borrowings', 'cfo', 'fcf']
        .indexOf(ln.key) >= 0;
      return '<tr' + (isKey ? ' class="key"' : '') + '>' +
        '<th scope="row" class="fu-line">' + esc(ln.label) + '</th>' +
        rows.map(function (r, i) {
          return '<td class="tnum' + (i ? '' : ' fu-now') + '">' + money(r, ln.key) + '</td>';
        }).join('') + '</tr>';
    }).join('');
    var ratios = (part.ratio_defs || []).filter(function (rd) {
      return rows.some(function (r) { return (r.ratios || {})[rd.key] != null; });
    }).map(function (rd) {
      var unit = rd.key.slice(-2) === '_x' ? '×' : '%';
      return '<tr><th scope="row" class="fu-line">' + esc(rd.label) +
        '<em>' + esc(rd.formula) + ', ' + unit + '</em></th>' +
        rows.map(function (r, i) {
          var v = (r.ratios || {})[rd.key];
          return '<td class="tnum' + (i ? '' : ' fu-now') + '">' +
            (v == null ? '—' : plain(v, 2)) + '</td>';
        }).join('') + '</tr>';
    }).join('');
    return '<h3 class="fu-h3">' + esc(title) + '</h3>' +
      '<p class="fu-cap" id="' + id + '">' + esc(cap) + '</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table fu-stmt" aria-describedby="' + id + '">' +
      '<caption class="fu-vh">' + esc(title) + ', in rupees crore</caption>' +
      '<thead>' + head + '</thead><tbody>' + lines + ratios + '</tbody></table></div></div>';
  }

  function paintPosition(d) {
    var box = $('funda-position');
    if (!box) return;
    if (!d || !d.available) { box.innerHTML = ''; return; }
    box.innerHTML =
      statementTable('fu-cap-bs', 'Balance sheet',
        'At each March and September, ' + d.basis + ', ₹ crore.', d.balance) +
      statementTable('fu-cap-cf', 'Cash flow',
        'Each full financial year, ' + d.basis + ', ₹ crore. Capital expenditure is shown positive.',
        d.cashflow) + notesBlock(d.notes);
  }

  /* The medians belong beside the named peers, so they load with the Peers
     section; the balance sheet and cash flow load with the Financials. */
  function loadMedians() {
    getJSON('/fundamentals/peers?ticker=' + encodeURIComponent(TICKER))
      .then(paintPeers)
      .catch(function () { paintPeers(null); });
  }

  function loadPosition() {
    getJSON('/fundamentals/position?ticker=' + encodeURIComponent(TICKER))
      .then(paintPosition)
      .catch(function () { paintPosition(null); });
  }

  function loadFunda() {
    loadPosition();
    var box = $('funda-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the results filings…</div>';
    }
    fetch(API + '/fundamentals?ticker=' + encodeURIComponent(TICKER) + '&quarters=6')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paintFunda)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="own-empty">The filings could not be read ' +
            'just now. Try again in a moment.</div>';
        }
      });
  }

  /* ── Peers ───────────────────────────────────────────────────────────────
     The company beside the named companies of its industry.

     Every row, this company's included, is worked out by the API from the
     same stored filings and prices, so the columns compare like with like.
     That is why this row's P/E can differ from the one in Key figures by a
     day's price move: the table says what date its prices are from.

     A column nobody has a figure for is not drawn. Debt to equity and
     operating margin are left out for a lender for the reason they are left
     out of its Key figures. Sorting only reorders what was sent; the median
     row is the peers' and never includes the company itself. */

  var peersLoaded = false;
  var PEERS = null;
  var peerSort = { key: 'market_cap_cr', dir: -1 };

  function f1(v) { return Number(v).toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }); }
  function f2(v) { return Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function grow1(v) { return (v > 0 ? '+' : '') + f1(v) + '%'; }
  var PEER_COLS = [
    { key: 'market_cap_cr',   label: 'Market cap', unit: '₹ cr',
      fmt: function (v) { return Math.round(v).toLocaleString('en-IN'); } },
    { key: 'pe',              label: 'P/E', fmt: f1 },
    { key: 'pb',              label: 'P/B', fmt: f2 },
    { key: 'roe_pct',         label: 'ROE', fmt: function (v) { return f1(v) + '%'; } },
    { key: 'opm_pct',         label: 'Op. margin', fmt: function (v) { return f1(v) + '%'; }, notLender: true },
    { key: 'revenue_yoy_pct', label: 'Sales growth', fmt: grow1, toned: true },
    { key: 'pat_yoy_pct',     label: 'Profit growth', fmt: grow1, toned: true },
    { key: 'debt_equity_x',   label: 'Debt / equity', fmt: f2, notLender: true },
    { key: 'score',           label: 'Altaha Score', score: true,
      fmt: function (v) { return String(Math.round(v)); } }
  ];

  function peerCols(d) {
    var lender = DATA && isLender(DATA);
    return PEER_COLS.filter(function (c) {
      if (c.notLender && lender) return false;
      return (d.rows || []).some(function (r) { return r[c.key] != null; });
    });
  }

  function paintPeerTable() {
    var d = PEERS, box = $('peers-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="own-empty">' +
        esc((d && d.message) || 'The peer table could not be read just now.') + '</div>';
      return;
    }
    // The scan scores its own cohort; a company ranked on request is not in
    // it, so its row arrives without a score the page already holds.
    var mine = DATA && DATA.scoring;
    d.rows.forEach(function (r) {
      if (r.is_self && r.score == null && mine && mine.score != null) {
        r.score = mine.score;
        r.band = bandOf(mine.score, mine, DATA);
      }
    });
    var cols = peerCols(d);
    var rows = d.rows.slice().sort(function (a, b) {
      var x = a[peerSort.key], y = b[peerSort.key];
      // A company without the figure sorts last whichever way the column runs.
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return peerSort.dir * (x - y);
    });

    var head = '<tr><th scope="col" class="pr-co">Company</th>' + cols.map(function (c) {
      var on = c.key === peerSort.key;
      return '<th scope="col" aria-sort="' + (on ? (peerSort.dir < 0 ? 'descending' : 'ascending') : 'none') + '">' +
        '<button type="button" data-sort="' + c.key + '"' + (on ? ' class="on"' : '') + '>' + esc(c.label) +
        (c.unit ? '<em>' + esc(c.unit) + '</em>' : '') +
        '<i aria-hidden="true">' + (on ? (peerSort.dir < 0 ? '↓' : '↑') : '') + '</i></button></th>';
    }).join('') + '</tr>';

    function cell(r, c) {
      var v = r[c.key];
      if (v == null) return '<td class="none">—</td>';
      if (c.score) {
        return '<td><span class="pr-score b-' + esc(String(r.band || '').toLowerCase()) + '" title="' +
          esc(r.band || '') + '">' + esc(c.fmt(v)) + '</span></td>';
      }
      return '<td class="tnum' + (c.toned ? ' ' + tone(v) : '') + '">' + esc(c.fmt(v)) + '</td>';
    }

    var body = rows.map(function (r, i) {
      var name = '<span class="pr-n"><b>' + esc(r.company || r.symbol) + '</b><small>' + esc(r.symbol) +
        (r.is_self ? ' · this company' : '') + '</small></span>';
      return '<tr' + (r.is_self ? ' class="self"' : '') + ' style="--i:' + Math.min(i, 14) + '">' +
        '<th scope="row" class="pr-co">' +
          (r.is_self ? '<span class="pr-a">' : '<a class="pr-a" href="' + esc(stockHref(r.symbol)) + '">') +
          logoTag(r.symbol, r.company, r.domain, 'sm') + name +
          (r.is_self ? '</span>' : '</a>') + '</th>' +
        cols.map(function (c) { return cell(r, c); }).join('') + '</tr>';
    }).join('');

    var med = d.medians || {};
    var foot = '<tr class="med"><th scope="row" class="pr-co"><span class="pr-a"><span class="lg lg-sm lg-med" aria-hidden="true">' +
      '<span class="lg-m">M</span></span><span class="pr-n"><b>Peer median</b><small>' + d.peers_shown +
      ' companies</small></span></span></th>' + cols.map(function (c) {
        var v = med[c.key];
        return (v == null || c.score) ? '<td class="none">' + (c.score ? '' : '—') + '</td>'
          : '<td class="tnum">' + esc(c.fmt(v)) + '</td>';
      }).join('') + '</tr>';

    var dated = d.prices_as_of
      ? ' Prices ' + ((d.prices_oldest && d.prices_oldest !== d.prices_as_of)
          ? 'from ' + niceDate(d.prices_oldest) + ' to ' + niceDate(d.prices_as_of)
          : 'as of ' + niceDate(d.prices_as_of)) + '.'
      : '';
    box.innerHTML =
      '<p class="fu-cap" id="pr-cap">' + esc(d.selection || '') + esc(dated) + '</p>' +
      '<div class="fu-block pr-block"><div class="fu-wrap">' +
      '<table class="pr-table" aria-describedby="pr-cap">' +
      '<caption class="fu-vh">' + esc(d.industry || 'Industry') + ' peers</caption>' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody><tfoot>' + foot + '</tfoot></table></div></div>' +
      notesBlock([d.note]);
    hydrateLogos(box);
    $('peers-x').textContent = d.industry ? d.industry + ' · ' + (d.classifier || 'NSE') : '';
  }

  function wirePeerSort() {
    var box = $('peers-body');
    if (!box) return;
    box.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-sort]') : null;
      if (!b) return;
      var key = b.dataset.sort;
      // Open on the direction a reader wants first: the largest, the highest.
      peerSort = { key: key, dir: peerSort.key === key ? -peerSort.dir : -1 };
      track('stock_section_clicked', { section: 'peers_sort_' + key });
      paintPeerTable();
      var again = box.querySelector('[data-sort="' + key + '"]');
      if (again) again.focus();
    });
  }

  function loadPeers() {
    var box = $('peers-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">Reading the industry…</div>';
    }
    getJSON('/stock/peers?ticker=' + encodeURIComponent(TICKER))
      .then(function (d) { PEERS = d; paintPeerTable(); })
      .catch(function () { PEERS = null; paintPeerTable(); });
    loadMedians();
  }

  /* ── News and filings ────────────────────────────────────────────────────
     Three lists, never merged. A filing is the company speaking; a headline
     is a journalist speaking about it; an industry headline is a journalist
     speaking about something else that may matter to it. They are different
     kinds of fact, and each list says which it is.

     Headlines are shown as published, with the publication named and the
     original linked. The tag on an industry headline is the driver it
     mentions (the API's keyword rule), which tells a reader why a story about
     the repo rate is on a bank's page. It does not say what the story means
     for the price, and nothing here does. */

  var NEWS = null, FILINGS = null;
  var newsDriver = '', filingCat = '';

  function newsRow(r, i) {
    var url = safeUrl(r.url);
    var head = '<span class="nw-h">' + esc(r.headline) + '</span>';
    return '<li class="nw-i" style="--i:' + Math.min(i, 12) + '">' +
      (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer nofollow">' + head + '</a>' : head) +
      '<span class="nw-m">' +
        (r.driver ? '<em class="nw-d">' + esc(r.driver) + '</em>' : '') +
        '<b>' + esc(r.source || 'Press') + '</b>' +
        (r.when_iso ? '<time datetime="' + esc(r.when_iso) + '">' + esc(ago(r.when_iso)) + '</time>' : '') +
      '</span></li>';
  }

  function paintNews() {
    var d = NEWS || {};
    var c = d.company || {}, ind = d.industry || {};
    var cRows = c.rows || [], iRows = ind.rows || [];

    $('news-company').innerHTML = cRows.length
      ? '<ul class="nw-l">' + cRows.map(newsRow).join('') + '</ul>'
      : '<div class="own-empty">' + (c.searched === false || !d.company
          ? 'The press search could not be reached just now.'
          : 'No press coverage naming this company in the last ' + (c.days || 21) + ' days.') + '</div>';

    $('news-ind-h').textContent = ind.label ? 'Industry: ' + ind.label : 'Industry news';
    var drivers = [];
    iRows.forEach(function (r) { if (r.driver && drivers.indexOf(r.driver) < 0) drivers.push(r.driver); });
    if (newsDriver && drivers.indexOf(newsDriver) < 0) newsDriver = '';
    var shown = newsDriver ? iRows.filter(function (r) { return r.driver === newsDriver; }) : iRows;
    $('news-industry').innerHTML = iRows.length
      ? (drivers.length > 1
          ? '<div class="fil-cats nw-drv" role="group" aria-label="Filter by what the story is about">' +
            '<button type="button" data-driver="" aria-pressed="' + (!newsDriver) + '"' +
              (!newsDriver ? ' class="on"' : '') + '>All</button>' +
            drivers.map(function (n) {
              return '<button type="button" data-driver="' + esc(n) + '" aria-pressed="' + (n === newsDriver) + '"' +
                (n === newsDriver ? ' class="on"' : '') + '>' + esc(n) + '</button>';
            }).join('') + '</div>'
          : '') +
        '<ul class="nw-l">' + shown.map(newsRow).join('') + '</ul>'
      : '<div class="own-empty">' + (ind.searched === false || !d.industry
          ? 'The press search could not be reached just now.'
          : 'No industry coverage in the last ' + (ind.days || 7) + ' days.') + '</div>';
  }

  function filingRow(r, i) {
    var url = safeUrl(r.pdf);
    var imp = String(r.importance || 'low');
    return '<li class="fil-i imp-' + esc(imp) + '" style="--i:' + Math.min(i, 12) + '">' +
      '<time class="fil-t tnum" datetime="' + esc(r.at || '') + '">' + esc(shortDate(r.at) || '—') + '</time>' +
      '<span class="fil-c">' + esc(r.category || 'Other') + '</span>' +
      '<span class="fil-h">' + esc(r.headline) + '</span>' +
      (url ? '<a class="fil-a" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer nofollow">' +
        'Open<span class="fu-vh"> the filing: ' + esc(String(r.headline).slice(0, 80)) + '</span> ›</a>'
        : '<span class="fil-a none"></span>') +
      '</li>';
  }

  function paintFilings() {
    var d = FILINGS || {}, rows = d.rows || [];
    var cats = (d.categories || []).filter(function (c) { return c && c.name; });
    if (filingCat && !cats.some(function (c) { return c.name === filingCat; })) filingCat = '';
    $('filings-cats').innerHTML = cats.length > 1
      ? '<button type="button" data-cat="" aria-pressed="' + (!filingCat) + '"' + (!filingCat ? ' class="on"' : '') +
          '>All<b>' + rows.length + '</b></button>' +
        cats.map(function (c) {
          return '<button type="button" data-cat="' + esc(c.name) + '" aria-pressed="' + (c.name === filingCat) + '"' +
            (c.name === filingCat ? ' class="on"' : '') + '>' + esc(c.name) + '<b>' + c.count + '</b></button>';
        }).join('')
      : '';
    var shown = filingCat ? rows.filter(function (r) { return r.category === filingCat; }) : rows;
    $('filings-body').innerHTML = shown.length
      ? '<ul class="fil-l">' + shown.map(filingRow).join('') + '</ul>'
      : '<div class="own-empty">' + esc(d.available === false || !FILINGS
          ? (d.message || 'The exchange could not be read just now.')
          : 'No filings in the last ' + (d.days ? Math.round(d.days / 30) + ' months' : 'year') + '.') + '</div>';
    $('filings-x').textContent = d.source ? String(d.source).replace(/ \(.*\)$/, '') : 'Exchange';
  }

  /* The Overview's "Latest": the newest few of what the company filed and
     what was reported about it, each marked as which. Routine filings — a
     trading window closing, a newspaper notice — are not what anybody means
     by news, and stay in the full list. */
  function paintLatest() {
    var card = $('ov-latest'), body = $('ov-latest-body');
    if (!card || !body) return;
    var items = [];
    ((NEWS && NEWS.company && NEWS.company.rows) || []).slice(0, 3).forEach(function (r) {
      items.push({ t: Date.parse(r.when_iso || '') || 0, kind: 'Press', head: r.headline,
                   meta: r.source, when: r.when_iso, url: safeUrl(r.url) });
    });
    ((FILINGS && FILINGS.rows) || []).filter(function (r) { return r.importance !== 'routine'; })
      .slice(0, 3).forEach(function (r) {
        items.push({ t: Date.parse(r.at || '') || 0, kind: 'Filing', head: r.headline,
                     meta: r.category, when: r.at, url: safeUrl(r.pdf) });
      });
    items.sort(function (a, b) { return b.t - a.t; });
    items = items.slice(0, 5);
    if (!items.length) { card.hidden = true; return; }
    body.innerHTML = '<ul class="lt-l">' + items.map(function (it, i) {
      var head = '<span class="lt-h">' + esc(it.head) + '</span>';
      return '<li style="--i:' + i + '">' +
        (it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer nofollow">' + head + '</a>' : head) +
        '<span class="lt-m"><em class="lt-k k-' + it.kind.toLowerCase() + '">' + it.kind + '</em>' +
          esc(it.meta || '') + (it.when ? ' · ' + esc(ago(it.when)) : '') + '</span></li>';
    }).join('') + '</ul>';
    card.hidden = false;

    // On the tab: how much of it is from the last three days.
    var cut = Date.now() - 3 * 86400000;
    var fresh = ((NEWS && NEWS.company && NEWS.company.rows) || [])
      .filter(function (r) { return Date.parse(r.when_iso || '') >= cut; }).length +
      ((FILINGS && FILINGS.rows) || [])
      .filter(function (r) { return r.importance !== 'routine' && Date.parse(r.at || '') >= cut; }).length;
    var badge = $('news-count');
    if (badge) { badge.hidden = !fresh; badge.textContent = fresh || ''; }
  }

  /* Bulk and block deals: who traded a large line of this company, on which
     side, at what price. The exchange's own disclosure, listed as it was
     made. A proprietary desk is marked as one, because a desk making a market
     is on the tape every day and says nothing about the company. */
  var dealsLoaded = false;
  function paintDeals(d) {
    var box = $('deals-body');
    if (!box) return;
    var rows = (d && d.rows) || [];
    if (!d || d.available === false) {
      box.innerHTML = '<div class="own-empty">The deals feed could not be read just now.</div>';
      return;
    }
    if (!rows.length) {
      box.innerHTML = '<div class="own-empty">No bulk or block deal disclosed in the last ' +
        (d.days || 90) + ' days.</div>';
      return;
    }
    box.innerHTML = '<ul class="fil-l dl-l">' + rows.slice(0, 30).map(function (r, i) {
      var buy = r.side === 'BUY';
      var who = r.prop_desk ? 'Proprietary desk' : (r.institutional ? 'Institution' : '');
      return '<li class="dl-i" style="--i:' + Math.min(i, 12) + '">' +
        '<span class="fil-t tnum">' + esc(String(r.date || '').replace(/-(\d{4})$/, ' $1').replace(/-/g, ' ')) + '</span>' +
        '<span class="dl-s ' + (buy ? 'up' : 'dn') + '">' + esc(buy ? 'Bought' : 'Sold') + '</span>' +
        '<span class="dl-c">' + esc(r.client || '—') +
          (who ? '<em>' + who + '</em>' : '') + '</span>' +
        '<span class="dl-q tnum">' + (r.qty ? Number(r.qty).toLocaleString('en-IN') : '—') +
          (r.price ? ' at ' + esc(money(r.price, 'INR')) : '') + '</span>' +
        '<span class="dl-v tnum">' + (r.value_cr == null ? '—' : '₹' + f2(r.value_cr) + ' cr') +
          '<em>' + esc(r.kind || '') + '</em></span></li>';
    }).join('') + '</ul>';
  }
  function loadDeals() {
    if (dealsLoaded) return;
    dealsLoaded = true;
    $('deals-body').innerHTML =
      '<div class="own-empty is-loading" aria-busy="true">Reading the exchange…</div>';
    getJSON('/deals/' + encodeURIComponent(BASE) + '?days=90')
      .then(paintDeals)
      .catch(function () { paintDeals(null); });
  }

  function wireNews() {
    var ind = $('news-industry'), cats = $('filings-cats');
    if (ind) ind.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-driver]') : null;
      if (!b) return;
      newsDriver = b.dataset.driver;
      paintNews();
      var again = ind.querySelector('[aria-pressed="true"]');
      if (again) again.focus();
    });
    if (cats) cats.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-cat]') : null;
      if (!b) return;
      filingCat = b.dataset.cat;
      paintFilings();
      var again = cats.querySelector('[aria-pressed="true"]');
      if (again) again.focus();
    });
  }

  /* Asked for once the page is up, not with it. Neither list is needed to
     show a price or a score, and the press search is the slowest thing the
     page does. The sector and industry are passed back for a company the API
     holds no profile of; the name that is searched for is the API's own. */
  var newsLoaded = false;
  function loadNews() {
    if (newsLoaded) return;
    newsLoaded = true;
    var d = DATA || {}, p = d.profile || {};
    $('news-company').innerHTML = $('news-industry').innerHTML =
      '<div class="own-empty is-loading" aria-busy="true">Searching the press…</div>';
    $('filings-body').innerHTML =
      '<div class="own-empty is-loading" aria-busy="true">Reading the exchange…</div>';
    var q = '?ticker=' + encodeURIComponent(TICKER) +
      '&sector=' + encodeURIComponent(p.sector || '') +
      '&industry=' + encodeURIComponent(p.industry || '');
    getJSON('/stock/news' + q)
      .then(function (x) { NEWS = x; })
      .catch(function () { NEWS = null; })
      .then(function () { paintNews(); paintLatest(); });
    getJSON('/stock/filings?ticker=' + encodeURIComponent(TICKER))
      .then(function (x) { FILINGS = x; })
      .catch(function () { FILINGS = null; })
      .then(function () { paintFilings(); paintLatest(); });
  }

  /* ── Delivery ─────────────────────────────────────────────────────────────
     NSE publishes, per stock per session, what share of the traded volume was
     actually DELIVERED — settled into somebody's demat account — rather than
     bought and sold again before the close. It is in the full bhavcopy, it is
     free, and no OHLCV feed carries it, which is why almost nothing in retail
     tooling here shows it per company.

     This reads /delivery, which reads the same panel the Altaha Special book
     is ranked on. One store, so the book and this page can never quote
     different delivery figures for the same session.

     WHAT IT DOES NOT DO: say whether a number is good. A 70% day on a stock
     that normally delivers 65% is unremarkable; the same 70% on one that
     normally delivers 30% is the whole story. So every figure is shown
     against this company's own average and never against a threshold, and
     nothing here is phrased as a signal to act on. */

  var DV_RANGES = [['20', '20 sessions'], ['60', '60 sessions'], ['120', '120 sessions']];
  var dvDays = '60';
  var dvLoaded = false;
  var dvRequest = 0;

  function paintDelivery(d) {
    var box = $('dv-body');
    if (!box) return;

    if (!d || d.available !== true) {
      // Not covered, still building, or no sessions yet — each of which is a
      // fact about the data rather than a failure, and is written as one.
      var msg = (d && d.message) || 'Delivery data is unavailable just now.';
      box.innerHTML = '<div class="own-empty' + (d && d.building ? ' is-loading' : '') + '"' +
        (d && d.building ? ' aria-busy="true"' : '') + '>' + esc(msg) + '</div>';
      return;
    }

    window.AltahaDelivery.mount(box, d);
  }

  function paintDvRanges() {
    var host = $('dv-ranges');
    if (!host) return;
    host.innerHTML = DV_RANGES.map(function (r) {
      return '<button type="button" aria-label="' + r[1] + '" aria-pressed="' +
        (r[0] === dvDays) + '" data-d="' + r[0] + '"' +
        (r[0] === dvDays ? ' class="on"' : '') + '>' + esc(r[0]) + '</button>';
    }).join('');
    host.onclick = function (e) {
      var b = e.target.closest('button');
      if (!b || b.dataset.d === dvDays) return;
      dvDays = b.dataset.d;
      paintDvRanges();
      host.querySelector('[data-d="' + dvDays + '"]').focus();
      loadDelivery();
    };
  }

  function loadDelivery() {
    var request = ++dvRequest;
    var box = $('dv-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the exchange delivery record…</div>';
    }
    fetch(API + '/delivery?ticker=' + encodeURIComponent(TICKER) + '&days=' + encodeURIComponent(dvDays))
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function(d) { if (request === dvRequest) paintDelivery(d); })
      .catch(function () {
        if (box && request === dvRequest) {
          box.innerHTML = '<div class="own-empty">The delivery record could not ' +
            'be read just now. Try again in a moment.</div>';
        }
      });
  }

  /* ── Sections ────────────────────────────────────────────────────────────
     Eight sections, one showing. The bar sits directly under the name, so the
     page reads as a set of sections from its first screen.

     Each section draws itself the first time it is opened, not on load. The
     chart's SVG scales to its container, and a container that is `hidden`
     measures zero; and the filings, the delivery record and the peer table
     are fetches nobody who came for the price should pay for.

     MOTION
     The marker under the active tab slides to it, the section that opens
     rises into place, and its bars grow to their values. All three are
     transform, opacity or width on small elements, none of them moves a
     number that is being read, and none runs for a reader who has asked for
     reduced motion. */

  var PANES = ['info', 'chart', 'scores', 'owners', 'funda', 'peers', 'deliv', 'news'];
  var chartDrawn = false;
  var scoreShown = false;
  var current = 'info';

  function moveMarker() {
    var bar = $('panes'), ind = $('panes-ind'), btn = $('pane-btn-' + current);
    if (!bar || !ind || !btn) return;
    ind.style.width = btn.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + btn.offsetLeft + 'px)';
    ind.classList.add('on');
  }

  function showPane(name, scroll) {
    if (PANES.indexOf(name) < 0) name = 'info';
    var changed = name !== current;
    current = name;
    PANES.forEach(function (p) {
      var pane = $('pane-' + p), btn = $('pane-btn-' + p);
      if (!pane || !btn) return;
      var on = p === name;
      pane.hidden = !on;
      pane.classList.toggle('enter', on && changed && !REDUCED);
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
      btn.tabIndex = on ? 0 : -1;
    });
    moveMarker();

    // The active tab stays in view on a phone, where the bar scrolls sideways.
    var btn = $('pane-btn-' + name), bar = $('panes');
    if (btn && bar && bar.scrollWidth > bar.clientWidth) {
      var left = btn.offsetLeft - (bar.clientWidth - btn.offsetWidth) / 2;
      try { bar.scrollTo({ left: Math.max(0, left), behavior: REDUCED ? 'auto' : 'smooth' }); }
      catch (e) { bar.scrollLeft = Math.max(0, left); }
    }

    if (name === 'chart' && !chartDrawn) {
      chartDrawn = true;
      paintRanges();
      loadChart();
    }
    if (name === 'scores') {
      // Its first opening replays the dial from empty; after that it stays.
      drawDial(!scoreShown);
      scoreShown = true;
    }
    if (name === 'owners' && !ownLoaded) {
      ownLoaded = true;
      loadOwnership();
    }
    if (name === 'funda' && !fundaLoaded) {
      fundaLoaded = true;
      loadFunda();
    }
    if (name === 'peers' && !peersLoaded) {
      peersLoaded = true;
      loadPeers();
    }
    if (name === 'deliv' && !dvLoaded) {
      dvLoaded = true;
      paintDvRanges();
      loadDelivery();
    }
    if (name === 'news') { loadNews(); loadDeals(); }
    if (changed) growBars($('pane-' + name));

    // The section is part of the address, so a link to a company's filings
    // opens on its filings. Replaced, not pushed: Back leaves the company.
    try {
      if (window.history && history.replaceState) {
        history.replaceState(history.state, '', location.pathname + location.search +
          (name === 'info' ? '' : '#' + name));
      }
    } catch (e) {}

    if (scroll) {
      var top = $('stk-panebar');
      if (top && top.scrollIntoView) {
        top.scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' });
      }
    }
    // analytics.js keeps a closed list of events; this is the one that asks
    // which sections of a company's page get opened.
    if (changed) track('stock_section_clicked', { section: name });
  }

  function wirePanes() {
    var bar = $('panes');
    if (!bar) return;
    bar.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-p]') : null;
      if (b) showPane(b.dataset.p);
    });
    // Left/right arrows move between tabs, which is the half of the tablist
    // pattern a screen reader actually uses.
    var btns = [].slice.call(bar.querySelectorAll('[data-p]'));
    btns.forEach(function (b, i) {
      // One stop in the tab order for the whole bar; the arrows do the rest.
      b.tabIndex = b.classList.contains('active') ? 0 : -1;
      b.addEventListener('keydown', function (e) {
        var step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        var to = e.key === 'Home' ? btns[0] : e.key === 'End' ? btns[btns.length - 1]
          : step ? btns[(i + step + btns.length) % btns.length] : null;
        if (!to) return;
        e.preventDefault();
        to.focus(); showPane(to.dataset.p);
      });
    });
    // A card on the Overview opens the section behind it.
    document.addEventListener('click', function (e) {
      var go = e.target.closest ? e.target.closest('[data-go]') : null;
      if (!go) return;
      track('stock_section_clicked', { section: 'overview_' + go.dataset.go });
      showPane(go.dataset.go, true);
    });

    window.addEventListener('resize', moveMarker);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveMarker).catch(function () {});
    moveMarker();

    /* Scrolled past the name, the bar carries the company and its price, so
       a reader halfway down the financials still knows whose they are. */
    var head = $('stk-head'), panebar = $('stk-panebar');
    if (head && panebar && 'IntersectionObserver' in window) {
      var chrome = document.querySelector('.sh-chrome');
      new IntersectionObserver(function (entries) {
        var past = !entries[0].isIntersecting;
        panebar.classList.toggle('is-stuck', past);
        // The marker's place depends on the bar's layout, which just changed.
        setTimeout(moveMarker, 0);
        setTimeout(moveMarker, 260);
      }, { rootMargin: '-' + (((chrome && chrome.offsetHeight) || 96) + 4) + 'px 0px 0px 0px' }).observe(head);
    }
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */

  function paintAll(d) {
    DATA = d;
    paintHead(d);
    paintKey(d);
    paintAbout(d);
    paintScore(d);
    paintNumbers(d);
    paintLedger(d);
    paintExplain(d);
    paintLevels(d);
  }

  function start() {
    if (!TICKER) {
      failed('No stock was named. Try searching for one.');
      return;
    }
    /* A company outside the scan's cohort is ranked against it the first time
       anyone opens it, and that can outlast the API's short wait. The API then
       answers "SCORING" and finishes the work behind the response; asking
       again a few seconds later finds it cached. Bounded: three tries, then the
       page leaves the honest message in place rather than polling forever. */
    function awaitScore(d, tries) {
      if (!(d && d.scoring && d.scoring.pending) || tries >= 3) return;
      setTimeout(function () {
        fetch(API + '/analyze?ticker=' + encodeURIComponent(TICKER))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d2) {
            if (!d2) return;
            DATA = d2;
            paintScore(d2);
            paintLedger(d2);
            paintExplain(d2);
            if (current === 'scores') { drawDial(true); growBars($('pane-scores')); }
            awaitScore(d2, tries + 1);
          })
          .catch(function () {});
      }, 6000);
    }

    loading();
    fetch(API + '/analyze?ticker=' + encodeURIComponent(TICKER))
      .then(function (r) {
        if (!r.ok) track('api_error', { endpoint: '/analyze', status: r.status });
        if (r.status === 404) throw new Error('notfound');
        if (!r.ok) throw new Error('down');
        return r.json();
      })
      .then(function (d) {
        clearTimeout(slowTimer);
        $('state').innerHTML = '';
        $('body').hidden = false;
        var sc = (d.scoring && d.scoring.score != null) ? Math.round(d.scoring.score) : null;
        track('stock_viewed', {
          ticker: TICKER,
          sector: (d.profile && d.profile.sector) || null,
          score: sc
        });
        paintAll(d);
        awaitScore(d, 0);
        $('disc').textContent = d.disclaimer ||
          'Educational tool. Scores and evidence only — never a recommendation to buy or sell.';
        wirePanes();
        wireScoreChip();
        wirePeerSort();
        wireNews();
        // The day's move for the headline and the year for the Overview; the
        // full chart draws itself when its section is first opened.
        loadYear(d);

        // A link can name the section to open: ?pane=owners, or #owners.
        var want = (param('pane') || (location.hash || '').replace(/^#/, '')).toLowerCase();
        if (want && want !== 'info' && PANES.indexOf(want) >= 0) showPane(want);
        // The press and the filings, once the first screen is up.
        setTimeout(loadNews, 350);
        if (window.AltahaShell) window.AltahaShell.reveal();
      })
      .catch(function (e) {
        var reason = (e && e.message === 'notfound') ? 'not_found' : 'engine_unreachable';
        track('stock_view_failed', { ticker: TICKER, reason: reason });
        failed(reason === 'not_found'
          ? "Couldn't find " + TICKER + '. Check the spelling.'
          : 'The engine could not be reached. After a quiet spell it takes about thirty seconds to wake. Try again.');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
