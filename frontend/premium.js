/* ============================================================================
   ALTAHA SCREENER — PREMIUM LAYER  v2
   ----------------------------------------------------------------------------
   Replaces v1. Strictly additive: no existing markup is rewritten, no existing
   handler is rebound, no id is renamed. If this file fails to load the site
   behaves exactly as it does without it.

   Fixed from v1
     · Reveals no longer set a persistent opacity:0. Elements inside
       display:none tab views never intersect an observer, so v1 left Ideas,
       Portfolio and Filings blank. v2 adds a one-shot animation class instead,
       which fails open.
     · The nav no longer goes full-bleed with a negative margin, which was the
       cause of the misalignment and horizontal scroll.

   New in v2
     · A candlestick field drawn behind the hero — the product's own subject
       used as its ornament, generated as SVG so it is sharp everywhere and
       costs nothing to fetch.
     · Live index tiles under the hero, mirrored from the ticker data the page
       already loads. No extra API call.
============================================================================ */

(function () {
  'use strict';

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  var SVGNS = 'http://www.w3.org/2000/svg';

  function el(name, attrs) {
    var n = document.createElementNS(SVGNS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  /* Deterministic pseudo-random. The candle field should look designed and
     identical on every load, not different each refresh. */
  function rng(seed) {
    var s = seed;
    return function () { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  }

  /* ── 1. THEME ─────────────────────────────────────────────────────────── */

  function theme() { return document.documentElement.getAttribute('data-theme') || 'light'; }

  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('altaha-theme', t); } catch (e) {}

    /* Segmented control: mark the live option and move the puck. */
    var seg = $('.themeseg');
    if (seg) {
      seg.querySelectorAll('button').forEach(function (btn) {
        var on = btn.dataset.t === t;
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
      });
      seg.dataset.t = t;
    }
    /* The old floating button, if anything still renders one. */
    var b = $('.themebtn');
    if (b) {
      b.textContent = t === 'dark' ? '\u263E' : '\u2600';
      b.setAttribute('aria-label',
        t === 'dark' ? 'Switch to light appearance' : 'Switch to dark appearance');
    }
    window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } }));
  }

  /* The control lives in the ticker strip at the very top of the page rather
     than floating over the bottom-right corner, where it sat on top of the
     content, competed with the mobile tab bar, and was easy to miss entirely.
     A two-option segmented control also states what it will do: a lone sun
     icon leaves you guessing whether it shows the current theme or the one
     you would switch to. */
  function themeToggle() {
    var seg = document.createElement('div');
    seg.className = 'themeseg';
    seg.setAttribute('role', 'radiogroup');
    seg.setAttribute('aria-label', 'Appearance');
    seg.innerHTML =
      '<i class="themepuck" aria-hidden="true"></i>' +
      '<button type="button" role="radio" data-t="light" aria-label="Light appearance">' +
        '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">' +
        '<circle cx="8" cy="8" r="3.1" fill="currentColor"/>' +
        '<g stroke="currentColor" stroke-width="1.3" stroke-linecap="round">' +
        '<path d="M8 1.4v1.8M8 12.8v1.8M1.4 8h1.8M12.8 8h1.8"/>' +
        '<path d="M3.3 3.3l1.3 1.3M11.4 11.4l1.3 1.3M12.7 3.3l-1.3 1.3M4.6 11.4l-1.3 1.3"/>' +
        '</g></svg><span>Light</span></button>' +
      '<button type="button" role="radio" data-t="dark" aria-label="Dark appearance">' +
        '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">' +
        '<path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" fill="currentColor"/>' +
        '</svg><span>Dark</span></button>';

    seg.addEventListener('click', function (ev) {
      var btn = ev.target.closest('button[data-t]');
      if (btn) applyTheme(btn.dataset.t);
    });
    /* Left/right arrows move between options, as a radiogroup should. */
    seg.addEventListener('keydown', function (ev) {
      if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
      ev.preventDefault();
      applyTheme(theme() === 'dark' ? 'light' : 'dark');
    });

    var bar = $('.tickerinner');
    if (bar) bar.appendChild(seg);
    else document.body.appendChild(seg);   // strip absent: still reachable
    applyTheme(theme());
  }

  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  var onMq = function (e) {
    var saved = null;
    try { saved = localStorage.getItem('altaha-theme'); } catch (err) {}
    if (!saved) applyTheme(e.matches ? 'dark' : 'light');
  };
  if (mq.addEventListener) mq.addEventListener('change', onMq); else mq.addListener(onMq);

  /* ── 2. HERO CANDLE FIELD ─────────────────────────────────────────────────
     Sixty sessions of a plausible uptrend with two corrections, drawn wide and
     faint behind the wordmark. Not real data and not presented as any: it is
     ornament, and ornament that claimed to be a live index would be a lie in a
     product whose entire pitch is that its numbers are auditable. */

  function candleField() {
    var host = $('header.wrap');
    if (!host) return;

    var W = 1200, H = 190, N = 58, pad = 3;
    var slot = W / N, bw = slot - pad * 2;

    // Trend, pullback, trend, pullback, rally to a new high. Tuned by eye
    // against an ASCII render until the silhouette reads as a chart at a
    // glance rather than as noise.
    var rand = rng(20260817);
    var price = 40, series = [];
    for (var i = 0; i < N; i++) {
      var drift = 0.95;
      if (i >= 17 && i < 24) drift = -1.9;
      if (i >= 38 && i < 45) drift = -1.7;
      if (i >= 50)           drift =  1.5;
      var open = price;
      price += drift + (rand() - 0.5) * 1.9;
      var close = price;
      series.push({
        o: open, c: close,
        h: Math.max(open, close) + rand() * 1.5,
        l: Math.min(open, close) - rand() * 1.5
      });
    }

    var vals = series.reduce(function (a, d) { return a.concat([d.h, d.l]); }, []);
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var span = (hi - lo) || 1;
    var y = function (v) { return H - ((v - lo) / span) * (H - 16) - 8; };

    var svg = el('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      preserveAspectRatio: 'none',
      'aria-hidden': 'true', focusable: 'false'
    });

    series.forEach(function (d, i) {
      var x = i * slot + pad;
      var up = d.c >= d.o;
      var col = up ? 'var(--up)' : 'var(--down)';
      var g = el('g', {});
      if (!reduced) g.setAttribute('style', 'animation-delay:' + (120 + i * 17) + 'ms');
      g.appendChild(el('line', {
        class: 'wick', x1: x + bw / 2, x2: x + bw / 2,
        y1: y(d.h), y2: y(d.l), stroke: col, 'stroke-opacity': .55
      }));
      var top = y(Math.max(d.o, d.c));
      var hgt = Math.max(1.5, Math.abs(y(d.o) - y(d.c)));
      g.appendChild(el('rect', {
        class: 'cndl', x: x, y: top, width: bw, height: hgt,
        rx: 1, fill: col, 'fill-opacity': up ? .5 : .42
      }));
      svg.appendChild(g);
    });

    var box = document.createElement('div');
    box.className = 'hero-candles';
    box.appendChild(svg);
    host.appendChild(box);
  }

  /* ── 3. LIVE INDEX TILES ──────────────────────────────────────────────────
     The page already fetches index levels and writes them into #tickers as
     11px text in a black bar. This mirrors that same data into three glass
     tiles under the hero — no second request, and it degrades to nothing if
     the feed is down. */

  function sparkline(seed, rising) {
    var W = 200, H = 26, N = 26, rand = rng(seed);
    var v = 50, pts = [];
    for (var i = 0; i < N; i++) {
      v += (rand() - (rising ? 0.38 : 0.62)) * 6;
      pts.push(v);
    }
    var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
    var span = (hi - lo) || 1;
    var d = pts.map(function (p, i) {
      return (i ? 'L' : 'M') + (i / (N - 1) * W).toFixed(1) + ' ' +
             (H - ((p - lo) / span) * (H - 4) - 2).toFixed(1);
    }).join(' ');

    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H,
                          preserveAspectRatio: 'none', 'aria-hidden': 'true' });
    svg.appendChild(el('path', {
      d: d, fill: 'none', stroke: rising ? 'var(--up)' : 'var(--down)',
      'stroke-width': 1.6, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    return svg;
  }

  function indexTiles() {
    var src = $('#tickers');
    var host = $('header.wrap');
    if (!src || !host) return;

    var grid = document.createElement('div');
    grid.className = 'hero-tiles';
    host.appendChild(grid);

    function paint() {
      var rows = $$('.tk', src).slice(0, 3);
      var usable = rows.filter(function (r) { return $('.l', r); });
      if (!usable.length) { grid.style.display = 'none'; return; }
      grid.style.display = '';

      grid.innerHTML = '';
      usable.forEach(function (r, i) {
        var name = ($('.n', r) || {}).textContent || '';
        var lvl  = ($('.l', r) || {}).textContent || '';
        var chgEl = $('.c', r);
        var chg  = chgEl ? chgEl.textContent.trim() : '';
        var up   = chgEl ? chgEl.classList.contains('up') : true;

        var tile = document.createElement('div');
        tile.className = 'hero-tile';
        tile.innerHTML =
          '<div class="hero-tile-name"></div>' +
          '<div class="hero-tile-val"></div>' +
          '<div class="hero-tile-chg ' + (up ? 'up' : 'dn') + '"></div>' +
          '<div class="hero-tile-spark"></div>';
        tile.querySelector('.hero-tile-name').textContent = name;
        tile.querySelector('.hero-tile-val').textContent  = lvl;
        tile.querySelector('.hero-tile-chg').textContent  = chg;
        tile.querySelector('.hero-tile-spark')
            .appendChild(sparkline(9001 + i * 137, up));
        grid.appendChild(tile);
      });
    }

    paint();
    new MutationObserver(paint).observe(src, { childList: true, subtree: true });
  }

  /* ── 4. HERO ENTRANCE ─────────────────────────────────────────────────── */

  function heroIn() {
    var h = $('header.wrap');
    if (h && !reduced) h.classList.add('hero-in');
  }

  /* ── 5. STICKY COMMAND BAR ────────────────────────────────────────────── */

  function stickyNav() {
    var nav = $('.tabnav');
    if (!nav || !('IntersectionObserver' in window)) return;
    var s = document.createElement('div');
    s.style.cssText = 'height:1px;width:100%;';
    nav.parentNode.insertBefore(s, nav);
    new IntersectionObserver(function (e) {
      nav.classList.toggle('is-stuck', !e[0].isIntersecting);
    }, { threshold: 0 }).observe(s);
  }

  /* ── 6. SECTION REVEAL ────────────────────────────────────────────────────
     One-shot animation class, never a persistent opacity:0. An element that is
     never observed — because its tab is display:none — stays fully visible.
     That is the whole point; v1 got this wrong and blanked three tabs. */

  var SEL = '#pricewrap,#volwrap,#shwrap,#lvlwrap,#setupwrap,#plainwrap,' +
            '#planwrap,.verdict,.sched,.statbox';
  var io = null;

  function revealInit() {
    if (reduced || !('IntersectionObserver' in window)) return;
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('rv');
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.05 });
    revealScan();
  }

  function revealScan() {
    if (!io) return;
    $$(SEL).forEach(function (n) {
      if (n.dataset.rvSeen) return;
      n.dataset.rvSeen = '1';
      io.observe(n);
    });
  }

  /* ── 7. SCORE COUNT-UP ────────────────────────────────────────────────── */

  function countUp() {
    var node = $('#score');
    if (!node) return;
    var busy = false;

    new MutationObserver(function () {
      if (busy) return;
      var target = parseInt((node.textContent || '').replace(/[^0-9]/g, ''), 10);
      if (!isFinite(target) || target <= 0) return;
      if (node.dataset.shown === String(target)) return;

      node.dataset.shown = String(target);

      // Announced before the count starts, so the dial sweeps alongside the
      // number instead of a second behind it.
      window.dispatchEvent(new CustomEvent('altaha:score', { detail: { score: target } }));

      if (reduced) { node.textContent = target; return; }

      busy = true;
      var t0 = performance.now(), dur = 1250;   // matches the needle sweep

      (function step(now) {
        var p = Math.min(1, (now - t0) / dur);
        node.textContent = Math.round(target * (1 - Math.pow(1 - p, 4)));
        if (p < 1) requestAnimationFrame(step);
        else { node.textContent = target; busy = false; }
      })(t0);
    }).observe(node, { childList: true, characterData: true, subtree: true });
  }

  /* ── 8. DATA-CONFIDENCE CHIP ──────────────────────────────────────────────
     A 70 from price alone and a 70 from price plus filings render identically
     on the seal. This labels the difference using the basis line the backend
     already sends. */

  function confidence() {
    var basis = $('#vbasis');
    if (!basis) return;

    new MutationObserver(function () {
      if (basis.querySelector('.confchip')) return;
      var t = (basis.textContent || '').toLowerCase();
      if (!t) return;

      var thin = t.indexOf('technical only') > -1;
      if (!thin && t.indexOf('50%') === -1) return;

      var chip = document.createElement('span');
      chip.className = 'confchip' + (thin ? ' thin' : '');
      chip.appendChild(document.createElement('i'));
      chip.appendChild(document.createTextNode(thin ? 'Price evidence only' : 'Full evidence'));
      chip.title = thin
        ? 'No published financial statements were available, so this score reflects price behaviour alone. It is not comparable with a score that includes fundamentals.'
        : 'Scored on both price behaviour and published financial statements.';
      basis.appendChild(chip);
    }).observe(basis, { childList: true, characterData: true, subtree: true });
  }

  /* ── 9. ⌘K TO SEARCH ──────────────────────────────────────────────────── */

  function commandK() {
    var input = $('#tk');
    if (!input) return;

    var mac = /Mac|iPhone|iPad/.test(navigator.platform || '');
    var row = input.closest ? input.closest('.searchrow') : null;
    if (row && row.querySelector('button')) {
      var hint = document.createElement('span');
      hint.className = 'kbdhint';
      hint.textContent = mac ? '\u2318K' : 'Ctrl K';
      row.insertBefore(hint, row.querySelector('button'));
    }

    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key || '').toLowerCase() === 'k') {
        e.preventDefault();
        var t = $('#tab-screener');
        if (t && !t.classList.contains('active')) t.click();
        window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
        input.focus(); input.select();
      }
      if (e.key === 'Escape' && document.activeElement === input) input.blur();
    });
  }

  /* ── 10. MOBILE TAB BAR ───────────────────────────────────────────────────
     Proxies to the existing desktop buttons with .click(). No DOM surgery on
     the real nav, so every handler already written keeps working. */

  var ICONS = {
    screener:  '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    ideas:     '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6h5.4c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z"/>',
    live:      '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    filings:   '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    portfolio: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    more:      '<circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/>'
  };

  /* Five slots, and nine destinations to fit into them.
     The desktop bar solves this with a More menu, but that menu lives inside
     .tabnav — which this same stylesheet sets to display:none below 780px. The
     result was that Tracker, Results, Options and Vocabulary did not exist at
     all on a phone, which is where most of the traffic arrives. Filings moves
     behind More; the menu itself is reused, so every handler already written
     keeps working and nothing new needs wiring. */
  var MOB = [
    ['tab-screener',  'Screener',  'screener'],
    ['tab-ideas',     'Ideas',     'ideas'],
    ['tab-live',      'Live',      'live'],
    ['tab-portfolio', 'Portfolio', 'portfolio'],
    ['tab-more',      'More',      'more']
  ];

  /* Filings left the bottom bar to make room for More, so it has to appear
     inside More — otherwise the fix that rescued four tabs would have stranded
     a fifth. The entry is injected rather than written into index.html so this
     stays a one-file change, and it is hidden on desktop where Filings already
     has its own button in the bar. */
  function moreMenuFilings() {
    var menu = $('#moreMenu'), src = $('#tab-filings');
    if (!menu || !src || menu.querySelector('[data-proxy="tab-filings"]')) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'mobonly';
    b.setAttribute('role', 'menuitem');
    b.dataset.proxy = 'tab-filings';
    b.textContent = 'Filings';
    b.addEventListener('click', function () { src.click(); });
    menu.insertBefore(b, menu.firstChild);
  }

  function mobileNav() {
    if (!$('#tab-screener')) return;
    moreMenuFilings();

    var bar = document.createElement('nav');
    bar.className = 'mobnav';
    bar.setAttribute('aria-label', 'Sections');
    var inner = document.createElement('div');
    inner.className = 'mobnav-inner';

    MOB.forEach(function (m) {
      var src = document.getElementById(m[0]);
      if (!src) return;
      var b = document.createElement('button');
      b.type = 'button';
      b.dataset.proxy = m[0];
      b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
                    ICONS[m[2]] + '</svg><span>' + m[1] + '</span>';
      b.addEventListener('click', function () {
        src.click();
        if (m[0] === 'tab-more') return;   // keep the page still; the menu is anchored
        window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
      });
      inner.appendChild(b);
    });

    bar.appendChild(inner);
    document.body.appendChild(bar);

    function sync() {
      $$('.mobnav button').forEach(function (b) {
        var src = document.getElementById(b.dataset.proxy);
        b.classList.toggle('on', !!src && src.classList.contains('active'));
      });
    }
    sync();

    var tabs = $('.tabs');
    if (tabs) new MutationObserver(sync)
      .observe(tabs, { subtree: true, attributes: true, attributeFilter: ['class'] });
  }

  /* ── 11. WATCH FOR INJECTED CONTENT ───────────────────────────────────── */

  function watchMain() {
    var main = $('main.wrap');
    if (!main) return;
    var t;
    new MutationObserver(function () {
      clearTimeout(t);
      t = setTimeout(revealScan, 140);
    }).observe(main, { childList: true, subtree: true });
  }


  /* ══════════════════════════════════════════════════════════════════════
     v2.1 — THE DIAL
     ══════════════════════════════════════════════════════════════════════
     The seal was a progress ring, which is a loading indicator in formal
     dress. This rebuilds it as the instrument the product actually is: a 250°
     dial with a tick ring, a track banded by verdict, and a needle.

     The original #arc is hidden rather than driven, because the existing code
     computes its dashoffset against a full-circle circumference. Fighting that
     maths from the outside would be fragile; owning the whole element is not.
     ═══════════════════════════════════════════════════════════════════════ */

  var DIAL = { CX: 95, CY: 95, START: -125, SWEEP: 250, R: 70 };

  function polar(r, deg) {
    var a = (deg - 90) * Math.PI / 180;
    return [DIAL.CX + r * Math.cos(a), DIAL.CY + r * Math.sin(a)];
  }

  function arcPath(r, a0, a1) {
    var p0 = polar(r, a0), p1 = polar(r, a1);
    var large = Math.abs(a1 - a0) > 180 ? 1 : 0;
    return 'M' + p0[0].toFixed(2) + ' ' + p0[1].toFixed(2) +
           ' A' + r + ' ' + r + ' 0 ' + large + ' 1 ' +
           p1[0].toFixed(2) + ' ' + p1[1].toFixed(2);
  }

  function angleFor(v) { return DIAL.START + (Math.max(0, Math.min(100, v)) / 100) * DIAL.SWEEP; }

  /* Thresholds mirror engine.composite() — 72 / 55 / 40. If those move in the
     backend they must move here, or the dial will disagree with the words
     printed next to it. */
  function band(v) {
    if (v >= 72) return { key: 'b-strong', css: 'var(--pass)' };
    if (v >= 55) return { key: 'b-good',   css: 'var(--gold)' };
    if (v >= 40) return { key: 'b-mixed',  css: 'var(--part)' };
    return          { key: 'b-weak',   css: 'var(--fail)' };
  }

  var dial = null;

  function buildDial() {
    var seal = $('.seal');
    var svg = seal && seal.querySelector('svg');
    if (!svg) return;

    // Retire the progress ring. The thin outer circle (r=88) stays as the bezel.
    $$('circle', svg).forEach(function (c) {
      if (c.getAttribute('r') !== '88') c.style.display = 'none';
    });

    var g = el('g', { class: 'dial' });

    // Tick ring — 51 ticks, one every 2 points, every fifth one major.
    var ticks = [];
    for (var i = 0; i <= 50; i++) {
      var deg = DIAL.START + (i / 50) * DIAL.SWEEP;
      var major = i % 5 === 0;
      var a = polar(major ? 78 : 81, deg);
      var b = polar(86, deg);
      var t = el('line', {
        class: 'tick' + (major ? ' major' : ''),
        x1: a[0].toFixed(2), y1: a[1].toFixed(2),
        x2: b[0].toFixed(2), y2: b[1].toFixed(2)
      });
      ticks.push({ node: t, value: (i / 50) * 100 });
      g.appendChild(t);
    }

    var track = el('path', { class: 'gauge-track',
      d: arcPath(DIAL.R, DIAL.START, DIAL.START + DIAL.SWEEP) });
    var value = el('path', { class: 'gauge-value', d: '' });

    var needle = el('g', { class: 'needle-wrap' });
    needle.appendChild(el('path', { class: 'needle',
      d: 'M95 33 L98.1 92 L91.9 92 Z' }));               // tapered pointer
    var hub = el('g', {});
    hub.appendChild(el('circle', { class: 'hub', cx: 95, cy: 95, r: 6.5 }));
    hub.appendChild(el('circle', { class: 'hub-ring', cx: 95, cy: 95, r: 9.5 }));

    // No 0/100 end labels: the caption below the needle already reads
    // "out of 100", and a dial that states its scale twice is a dial that
    // does not trust its own caption.

    g.appendChild(track); g.appendChild(value);
    g.appendChild(needle); g.appendChild(hub);
    svg.appendChild(g);

    dial = { svg: svg, value: value, needle: needle, ticks: ticks, at: 0 };
    render(0);
  }

  function render(v) {
    if (!dial) return;
    var bd = band(v);
    var a1 = angleFor(v);

    dial.value.setAttribute('d', arcPath(DIAL.R, DIAL.START, Math.max(DIAL.START + 0.4, a1)));
    dial.value.setAttribute('stroke', bd.css);
    dial.value.style.color = bd.css;                     // drives the drop-shadow

    dial.ticks.forEach(function (t) {
      t.node.classList.toggle('lit', t.value <= v + 0.5);
      if (t.value <= v + 0.5) t.node.style.color = bd.css;
      else t.node.style.color = '';
    });
  }

  function sweep(target) {
    if (!dial) return;
    var bd = band(target);

    var valEl = $('#score');
    if (valEl) {
      valEl.classList.remove('b-strong', 'b-good', 'b-mixed', 'b-weak');
      valEl.classList.add(bd.key);
    }

    if (reduced) {
      render(target);
      dial.needle.setAttribute('transform', 'rotate(' + angleFor(target).toFixed(2) + ' 95 95)');
      return;
    }

    var from = dial.at, t0 = performance.now(), dur = 1250;
    dial.at = target;

    (function step(now) {
      var p = Math.min(1, (now - t0) / dur);

      // The arc uses a clean decay — data does not overshoot its own maximum.
      var pArc = 1 - Math.pow(1 - p, 4);
      render(from + (target - from) * pArc);

      // The needle is mechanism, so it overshoots and settles. Damped sine.
      var pNdl = 1 - Math.exp(-5.5 * p) * Math.cos(7.5 * p);
      var deg = angleFor(from + (target - from) * pNdl);
      dial.needle.setAttribute('transform', 'rotate(' + deg.toFixed(2) + ' 95 95)');

      if (p < 1) requestAnimationFrame(step);
      else {
        render(target);
        dial.needle.setAttribute('transform', 'rotate(' + angleFor(target).toFixed(2) + ' 95 95)');
      }
    })(t0);
  }

  function watchScore() {
    var last = null;
    window.addEventListener('altaha:score', function (e) {
      var v = e.detail && e.detail.score;
      if (!isFinite(v) || v === last) return;
      last = v;
      sweep(v);
    });
  }

  /* ══════════════════════════════════════════════════════════════════════
     v2.1 — SCORE CARD
     ══════════════════════════════════════════════════════════════════════
     A 1080×1350 PNG of the current verdict, drawn on canvas and downloaded.
     The analysis is the content, so posting it should not require a
     screenshot with a browser toolbar in it.

     Everything on the card is read from the DOM that is already on screen —
     no second request, and nothing can appear on the card that is not also
     visible in the page it came from.
     ═══════════════════════════════════════════════════════════════════════ */

  function txt(sel) { var n = $(sel); return n ? (n.textContent || '').trim() : ''; }

  function drawCard() {
    var W = 1080, H = 1350, c = document.createElement('canvas');
    c.width = W; c.height = H;
    var x = c.getContext('2d');

    var name  = txt('#cname') || 'Altaha Screener';
    var sym   = txt('#csym');
    var px    = txt('#cpx');
    var score = parseInt(txt('#score').replace(/[^0-9]/g, ''), 10);
    var label = txt('#vlabel');
    var tsc   = txt('#tscore');
    var fsc   = txt('#fscore');
    if (!isFinite(score)) return null;

    var bd = score >= 72 ? '#34C48D' : score >= 55 ? '#D9BE7E'
           : score >= 40 ? '#D8AE4B' : '#F0736A';

    // Ground
    x.fillStyle = '#0A0B0E'; x.fillRect(0, 0, W, H);
    var glow = x.createRadialGradient(W / 2, 300, 40, W / 2, 300, 720);
    glow.addColorStop(0, 'rgba(196,166,97,.16)');
    glow.addColorStop(1, 'rgba(196,166,97,0)');
    x.fillStyle = glow; x.fillRect(0, 0, W, H);

    // Chart paper
    x.strokeStyle = 'rgba(255,255,255,.045)'; x.lineWidth = 1;
    for (var gx = 0; gx <= W; gx += 72) { x.beginPath(); x.moveTo(gx, 0); x.lineTo(gx, H); x.stroke(); }
    for (var gy = 0; gy <= H; gy += 72) { x.beginPath(); x.moveTo(0, gy); x.lineTo(W, gy); x.stroke(); }

    var S = '"Inter", system-ui, -apple-system, sans-serif';
    var M = '"IBM Plex Mono", ui-monospace, monospace';

    // Wordmark
    x.textAlign = 'center';
    x.fillStyle = 'rgba(255,255,255,.42)'; x.font = '500 22px ' + M;
    x.fillText('A L T A H A   S C R E E N E R', W / 2, 96);

    // Subject
    x.fillStyle = '#F3F4F7'; x.font = '600 62px ' + S;
    var nm = name.length > 26 ? name.slice(0, 25) + '…' : name;
    x.fillText(nm, W / 2, 200);
    x.fillStyle = 'rgba(255,255,255,.50)'; x.font = '400 28px ' + M;
    x.fillText([sym, px].filter(Boolean).join('   ·   '), W / 2, 248);

    // The dial, redrawn at scale
    var cx = W / 2, cy = 600, R = 210;
    function pol(r, deg) {
      var a = (deg - 90) * Math.PI / 180;
      return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    }
    var A0 = -125, SW = 250, A1 = A0 + (score / 100) * SW;
    function rad(d) { return (d - 90) * Math.PI / 180; }

    x.lineCap = 'round';
    x.strokeStyle = 'rgba(255,255,255,.10)'; x.lineWidth = 17;
    x.beginPath(); x.arc(cx, cy, R, rad(A0), rad(A0 + SW)); x.stroke();

    x.strokeStyle = bd; x.lineWidth = 17;
    x.shadowColor = bd; x.shadowBlur = 34;
    x.beginPath(); x.arc(cx, cy, R, rad(A0), rad(A1)); x.stroke();
    x.shadowBlur = 0;

    // Tick ring
    for (var i = 0; i <= 50; i++) {
      var d = A0 + (i / 50) * SW, major = i % 5 === 0;
      var p1 = pol(major ? 232 : 240, d), p2 = pol(252, d);
      x.strokeStyle = (i / 50) * 100 <= score ? bd : 'rgba(255,255,255,.16)';
      x.lineWidth = major ? 3 : 1.6;
      x.beginPath(); x.moveTo(p1[0], p1[1]); x.lineTo(p2[0], p2[1]); x.stroke();
    }

    // Reading
    x.fillStyle = '#F3F4F7'; x.font = '600 168px ' + S;
    x.fillText(String(score), cx, cy + 62);
    x.fillStyle = 'rgba(255,255,255,.42)'; x.font = '400 22px ' + M;
    x.fillText('O U T   O F   1 0 0', cx, cy + 118);

    if (label) {
      x.fillStyle = bd; x.font = '500 30px ' + M;
      x.fillText(label.toUpperCase(), cx, 900);
    }

    // Split
    x.strokeStyle = 'rgba(255,255,255,.12)'; x.lineWidth = 1;
    x.beginPath(); x.moveTo(180, 960); x.lineTo(900, 960); x.stroke();

    [['TECHNICAL', tsc, W / 2 - 180], ['FUNDAMENTAL', fsc, W / 2 + 180]].forEach(function (col) {
      x.fillStyle = 'rgba(255,255,255,.42)'; x.font = '400 20px ' + M;
      x.fillText(col[0], col[2], 1020);
      x.fillStyle = '#F3F4F7'; x.font = '600 56px ' + S;
      x.fillText(col[1] || '—', col[2], 1084);
    });

    x.beginPath(); x.moveTo(180, 1140); x.lineTo(900, 1140); x.stroke();

    // Provenance. A number without a date is not evidence.
    var when = new Date().toLocaleDateString('en-IN',
      { day: 'numeric', month: 'short', year: 'numeric' });
    x.fillStyle = 'rgba(255,255,255,.52)'; x.font = '400 22px ' + M;
    x.fillText(when, cx, 1200);
    x.fillStyle = 'rgba(255,255,255,.34)'; x.font = '400 19px ' + M;
    x.fillText('Every calculation shown at the source', cx, 1240);
    x.fillStyle = 'rgba(196,166,97,.72)'; x.font = '500 21px ' + M;
    x.fillText('taha-project-one.vercel.app', cx, 1284);

    return { canvas: c, sym: sym || 'stock' };
  }

  function scoreCard() {
    var host = $('.verdict');
    if (!host) return;

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'act cardbtn';
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" ' +
      'stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 11 5 5 5-5"/>' +
      '<path d="M4 20h16"/></svg>Save score card';
    btn.style.display = 'none';

    btn.addEventListener('click', function () {
      var made;
      try { made = drawCard(); } catch (e) { made = null; }
      if (!made) { btn.textContent = 'Analyse a stock first'; return; }
      made.canvas.toBlob(function (blob) {
        if (!blob) return;
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'altaha-' + made.sym.replace(/[^A-Za-z0-9]/g, '') + '.png';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      }, 'image/png');
    });

    host.appendChild(btn);

    var sc = $('#score');
    if (sc) new MutationObserver(function () {
      btn.style.display = /\d/.test(sc.textContent || '') ? '' : 'none';
    }).observe(sc, { childList: true, characterData: true, subtree: true });
  }

  /* ── BOOT ─────────────────────────────────────────────────────────────── */

  function boot() {
    [themeToggle, candleField, indexTiles, heroIn, stickyNav, revealInit,
     countUp, confidence, commandK, mobileNav, watchMain,
     buildDial, watchScore, scoreCard]
      .forEach(function (fn) { try { fn(); } catch (e) { /* never block the page */ } });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
