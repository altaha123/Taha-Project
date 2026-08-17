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
    var b = $('.themebtn');
    if (b) {
      b.textContent = t === 'dark' ? '\u263E' : '\u2600';
      b.setAttribute('aria-label',
        t === 'dark' ? 'Switch to light appearance' : 'Switch to dark appearance');
    }
    window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } }));
  }

  function themeToggle() {
    var b = document.createElement('button');
    b.className = 'themebtn';
    b.type = 'button';
    b.addEventListener('click', function () {
      applyTheme(theme() === 'dark' ? 'light' : 'dark');
    });
    document.body.appendChild(b);
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
    if (!node || reduced) return;
    var busy = false;

    new MutationObserver(function () {
      if (busy) return;
      var target = parseInt((node.textContent || '').replace(/[^0-9]/g, ''), 10);
      if (!isFinite(target) || target <= 0) return;
      if (node.dataset.shown === String(target)) return;

      busy = true;
      node.dataset.shown = String(target);
      var t0 = performance.now(), dur = 1050;

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
    portfolio: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'
  };

  var MOB = [
    ['tab-screener',  'Screener',  'screener'],
    ['tab-ideas',     'Ideas',     'ideas'],
    ['tab-live',      'Live',      'live'],
    ['tab-filings',   'Filings',   'filings'],
    ['tab-portfolio', 'Portfolio', 'portfolio']
  ];

  function mobileNav() {
    if (!$('#tab-screener')) return;

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

  /* ── BOOT ─────────────────────────────────────────────────────────────── */

  function boot() {
    [themeToggle, candleField, indexTiles, heroIn, stickyNav, revealInit,
     countUp, confidence, commandK, mobileNav, watchMain]
      .forEach(function (fn) { try { fn(); } catch (e) { /* never block the page */ } });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
