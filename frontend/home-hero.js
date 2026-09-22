/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — home-hero.js
   Builds the opening screen and drives the motion CSS alone cannot express.

   The division of labour with home-hero.css is deliberate: every entrance
   animation is pure CSS, running at first paint, so the headline arrives
   even if this file never loads or throws. What lives here is only the work
   that needs the DOM — the markup itself, the rotating question, the objects
   in the backdrop, and the pointer lean.

   Nothing here fetches, polls, or schedules a repaint on a timer that runs
   when the tab is in the background. Two intervals exist, both suspended on
   visibilitychange, both switched off by the site's Motion toggle.

   THE RULE THIS FILE INHERITS: a financial label is never animated. There is
   no count-up in this file and there must not be one. The only text that
   changes is the rotating question and the search box's own placeholder,
   neither of which is a number the reader could act on.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var root = document.documentElement;
  var reduce = matchMedia('(prefers-reduced-motion: reduce)');

  /* The site's Motion toggle (home-motion.js) owns data-motion on <html>.
     This file reads it rather than keeping a second preference, so one
     button governs the whole page. */
  function moving() {
    return !reduce.matches && root.dataset.motion !== 'off' && !document.hidden;
  }

  /* ── The floating objects ───────────────────────────────────────────────
     The competitor floats glass blocks that mean nothing. These are the six
     things the product is made of, drawn in the site's own ink-and-gold line
     style: research, idle money, allocation, baskets, selection, evidence.
     Each is a 24×24 path set — about a kilobyte in total, and it recolours
     with the theme instead of needing a second set of files for dark mode. */
  var GLYPHS = [
    /* research — candles with a trend over them */
    '<path d="M2.5 20.5h19"/><rect x="5" y="10" width="3.6" height="8" rx=".8"/>' +
    '<path d="M6.8 7.6v2.4M6.8 18v2.4"/><rect x="15.4" y="7" width="3.6" height="7" rx=".8"/>' +
    '<path d="M17.2 4.6V7M17.2 14v2.6"/>' +
    '<path class="hh-accent" d="M3.6 15.4 6.8 12l5.2 2.4 5.2-6.2"/>',
    /* idle money — a stack of coins */
    '<ellipse class="hh-accent" cx="12" cy="6.4" rx="7.4" ry="2.9"/>' +
    '<path d="M4.6 6.4v4.8c0 1.6 3.32 2.9 7.4 2.9s7.4-1.3 7.4-2.9V6.4"/>' +
    '<path d="M4.6 11.2V16c0 1.6 3.32 2.9 7.4 2.9s7.4-1.3 7.4-2.9v-4.8"/>',
    /* allocation — a ring with one sleeve called out */
    '<circle cx="12" cy="12" r="8.4"/>' +
    '<path class="hh-accent" d="M12 3.6a8.4 8.4 0 0 1 7.28 12.6"/>' +
    '<path d="M12 12V3.6M12 12l7.28 4.2"/>',
    /* baskets — a basket with its holdings */
    '<path d="M3.2 8.8h17.6l-1.9 9.9a2 2 0 0 1-2 1.6H7.1a2 2 0 0 1-2-1.6z"/>' +
    '<path d="M8.4 8.8 12 3.4l3.6 5.4"/>' +
    '<path class="hh-accent" d="M9.4 12.4v4.2M12 12.4v4.2M14.6 12.4v4.2"/>',
    /* selection — a magnifier over a line */
    '<circle cx="10.6" cy="10.6" r="6.6"/><path d="m15.4 15.4 4.8 4.8"/>' +
    '<path class="hh-accent" d="M7.4 12.2 9.8 9.4l2.2 1.8 3-3.6"/>',
    /* evidence — a filed document, stamped */
    '<path d="M6 2.8h7.4L19 8.4v12.8H6z"/><path d="M13.4 2.8v5.6H19"/>' +
    '<path d="M8.8 12.8h7M8.8 16h4.6"/>' +
    '<circle class="hh-accent" cx="16.2" cy="18" r="2.7"/>'
  ];

  /* ── The questions ──────────────────────────────────────────────────────
     Most people arrive with a question they are slightly embarrassed to ask
     out loud. Asking it for them is the most useful thing this screen can
     do, and each one here is answered by a destination that already exists —
     no question is asked that the product cannot follow through on. */
  var ASKS = [
    'Confused about what to do with your idle money?',
    'Not sure whether that stock is worth buying?',
    'Wondering how your holdings are really doing?',
    'Want to see who actually bought into the company?'
  ];

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  /* ── 1 · The stage ──────────────────────────────────────────────────────
     The headline is built from one span per word so the sentence can
     assemble itself; the spans are inline-block, so the line still wraps
     normally and still reads as a single sentence to a screen reader. */
  function buildHero(header) {
    header.classList.add('hh-stage');

    var orbit = el('div', 'hh-orbit');
    orbit.setAttribute('aria-hidden', 'true');
    orbit.innerHTML = GLYPHS.map(function (g) {
      return '<div class="hh-tile"><div class="hh-card">' +
        '<svg viewBox="0 0 24 24" focusable="false">' + g + '</svg></div></div>';
    }).join('');
    // First child after the artwork: later siblings share its z-index, so the
    // words paint over the tiles by document order rather than by a fight.
    var art = header.querySelector('#skin-art');
    if (art && art.nextSibling) header.insertBefore(orbit, art.nextSibling);
    else header.insertBefore(orbit, header.firstChild);

    var hero = el('section', 'hh-hero');

    var words = ['Discover', 'the', 'power', 'of'];
    var head = el('h2', 'hh-head',
      words.map(function (w, i) {
        return '<span class="hh-w" style="--hh-i:' + i + '">' + w + '</span>';
      }).join(' ') + ' <span class="hh-w" style="--hh-i:4"><em>money</em>.</span>');
    hero.appendChild(head);

    hero.appendChild(el('p', 'hh-sub',
      'Altaha guides you through <b style="--hh-i:0">stock research</b>, ' +
      '<b style="--hh-i:1">selection</b>, <b style="--hh-i:2">baskets</b> and ' +
      '<b style="--hh-i:3">allocation</b> across asset classes — with every ' +
      'number showing the working behind it.'));

    var ask = el('p', 'hh-ask');
    // aria-live, because the sentence changes on its own: a reader who cannot
    // see the rotation still hears each question once, politely.
    ask.setAttribute('aria-live', 'polite');
    ask.appendChild(el('span', 'hh-ask-line', ASKS[0]));
    hero.appendChild(ask);

    var cta = el('div', 'hh-cta',
      '<a class="hh-btn hh-btn-gold" href="index.html?go=allocate" data-hh-go="allocate">' +
        'Plan my allocation <span aria-hidden="true">&rarr;</span></a>' +
      '<a class="hh-btn" href="#tk" data-hh-go="search">' +
        'Research a stock <span aria-hidden="true">&rarr;</span></a>');
    hero.appendChild(cta);

    cta.addEventListener('click', function (e) {
      var a = e.target.closest('[data-hh-go]');
      if (!a) return;
      if (a.dataset.hhGo === 'allocate') {
        // Fall through to the href when nav.js is absent, so the button is
        // never dead — the address it points at resolves on its own.
        if (!window.AltahaNav) return;
        e.preventDefault();
        window.AltahaNav.go('allocate', 'allocate', true);
        return;
      }
      var tk = document.getElementById('tk');
      if (!tk) return;
      e.preventDefault();
      tk.scrollIntoView({ behavior: moving() ? 'smooth' : 'auto', block: 'center' });
      tk.focus({ preventScroll: true });
    });

    var anchor = header.querySelector('.brand');
    if (anchor && anchor.nextSibling) header.insertBefore(hero, anchor.nextSibling);
    else header.appendChild(hero);

    return ask;
  }

  /* ── 2 · The rotating question ──────────────────────────────────────────
     Out, swap, in. The height is reserved in CSS, so the buttons underneath
     never move under a thumb mid-rotation. */
  function rotateAsk(ask) {
    var i = 0, timer = null;

    function step() {
      var line = ask.querySelector('.hh-ask-line');
      if (!line || !moving()) return;
      line.classList.add('hh-out');
      setTimeout(function () {
        i = (i + 1) % ASKS.length;
        var next = el('span', 'hh-ask-line', ASKS[i]);
        line.replaceWith(next);
      }, 320);
    }
    function play() {
      if (timer) clearInterval(timer);
      timer = moving() ? setInterval(step, 4600) : null;
    }
    play();
    return play;
  }

  /* ── 3 · The backdrop ───────────────────────────────────────────────────
     Three additions inside #skin-art, which is pointer-events:none and
     overflow:hidden — so none of this can be clicked and none of it can
     widen the document at any viewport. */
  function dressBackdrop() {
    var svg = document.querySelector('#skin-art svg');
    if (!svg) return;
    var NS = 'http://www.w3.org/2000/svg';

    /* a · The candles get their index. The page's own generator writes an
          inline animation-delay for the one-shot grow; the wave needs a
          second delay on the same element, and an inline style cannot be
          overridden from a stylesheet without !important. So the index moves
          into a custom property and the CSS times both animations. */
    var candles = svg.querySelectorAll('.sk-candle');
    for (var c = 0; c < candles.length; c++) {
      candles[c].style.removeProperty('animation-delay');
      candles[c].style.setProperty('--ci', c);
    }

    /* b · Embers off the hills. Deterministic, like the candles: the picture
          should look the same on every visit rather than reshuffling. */
    var seed = 31;
    function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
    for (var i = 0; i < 14; i++) {
      var e = document.createElementNS(NS, 'circle');
      e.setAttribute('class', 'hh-ember');
      e.setAttribute('cx', (40 + rnd() * 1320).toFixed(0));
      e.setAttribute('cy', (392 + rnd() * 62).toFixed(0));
      e.setAttribute('r', (1.4 + rnd() * 2.4).toFixed(1));
      e.setAttribute('fill', 'var(--gold)');
      e.style.setProperty('--hh-dur', (7 + rnd() * 7).toFixed(1) + 's');
      e.style.setProperty('--hh-delay', (rnd() * -13).toFixed(1) + 's');
      svg.appendChild(e);
    }

    /* c · A spark running the trend arc, bursting where it lands. offset-path
          takes the arc's own `d`, read off the element rather than copied
          here, so the two can never drift apart. Skipped where offset-path
          is unsupported: a stationary dot in the corner says nothing. */
    var arc = svg.querySelector('.sk-arc');
    var supported = window.CSS && CSS.supports && CSS.supports('offset-path', 'path("M0 0L1 1")');
    if (arc && supported) {
      var d = arc.getAttribute('d');
      [['hh-spark', 10, .22], ['hh-spark', 4.5, 1]].forEach(function (spec) {
        var s = document.createElementNS(NS, 'circle');
        s.setAttribute('class', spec[0]);
        s.setAttribute('r', spec[1]);
        s.setAttribute('fill', 'var(--gold)');
        s.setAttribute('opacity', spec[2]);
        s.style.offsetPath = 'path("' + d + '")';
        svg.appendChild(s);
      });
      var burst = document.createElementNS(NS, 'circle');
      burst.setAttribute('class', 'hh-burst');
      burst.setAttribute('cx', '1364'); burst.setAttribute('cy', '172');
      burst.setAttribute('r', '9'); burst.setAttribute('fill', 'none');
      burst.setAttribute('stroke', 'var(--gold)'); burst.setAttribute('stroke-width', '2');
      svg.appendChild(burst);
    }
  }

  /* ── 4 · The lean ───────────────────────────────────────────────────────
     Two custom properties on <html>; the artwork and each tile read them and
     scale by their own depth, so one pointer event moves seven things at
     different rates without seven listeners. Coalesced onto a frame, because
     pointermove fires far more often than the screen refreshes. */
  function lean(header) {
    var queued = false, px = 0, py = 0;

    header.addEventListener('pointermove', function (ev) {
      if (ev.pointerType !== 'mouse' || !moving()) return;
      var r = header.getBoundingClientRect();
      px = ((ev.clientX - r.left) / r.width - .5) * -16;
      py = ((ev.clientY - r.top) / r.height - .5) * -10;
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        root.style.setProperty('--hh-px', px.toFixed(2) + 'px');
        root.style.setProperty('--hh-py', py.toFixed(2) + 'px');
      });
    });
    header.addEventListener('pointerleave', function () {
      root.style.setProperty('--hh-px', '0px');
      root.style.setProperty('--hh-py', '0px');
    });
  }

  /* ── 5 · The search box types to itself ─────────────────────────────────
     Only ever the placeholder attribute, never the value: the field's own
     contents belong to the reader, and the autocomplete reads that value.
     Stops the moment the box is focused or has anything in it, so it can
     never be mistaken for text somebody typed. */
  function typePlaceholder(input) {
    var NAMES = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'NVDA', 'AAPL'];
    var PREFIX = 'Enter a stock — ';
    var REST = 'Enter a stock — RELIANCE, TCS, NVDA…';
    var n = 0, ch = 0, erasing = false, timer = null;

    function idle() { return !input.value && document.activeElement !== input; }

    function tick() {
      if (!moving() || !idle()) { input.placeholder = REST; return schedule(900); }
      var word = NAMES[n];
      if (!erasing) {
        ch++;
        input.placeholder = PREFIX + word.slice(0, ch) + '▌';
        if (ch >= word.length) { erasing = true; return schedule(1500); }
        return schedule(72);
      }
      ch -= 2;
      if (ch <= 0) { ch = 0; erasing = false; n = (n + 1) % NAMES.length; return schedule(260); }
      input.placeholder = PREFIX + word.slice(0, ch) + '▌';
      return schedule(34);
    }
    function schedule(ms) { clearTimeout(timer); timer = setTimeout(tick, ms); }

    input.addEventListener('focus', function () { clearTimeout(timer); input.placeholder = REST; });
    input.addEventListener('blur', function () { ch = 0; erasing = false; schedule(1200); });
    schedule(1800);
    return function () { if (moving()) schedule(400); else { clearTimeout(timer); input.placeholder = REST; } };
  }

  /* ── 6 · The search box brings its own list into view ───────────────────
     The stage is tall on purpose, which puts the search box low on a phone —
     low enough that the suggestion list opens below the fold, and on screens
     narrower than 1041px, underneath the site's fixed bottom bar. Found at
     390px by tapping the first suggestion and watching the bar take the tap.

     The list is absolutely positioned, so it adds nothing to the document
     and there is no scroll for scroll-margin to act against; and the scroll
     the browser performs for a focused field is the smallest one that makes
     the field visible, which knows nothing about a fixed bar on top of it.
     So the field works out whether its own list will fit and scrolls itself
     the rest of the way.

     Instantly, not smoothly: a focus scroll still animating when somebody
     taps the first suggestion is worse than no scroll at all. */
  function keepListInView(input) {
    var row = input.closest('.searchrow');
    if (!row) return;
    input.addEventListener('focus', function () {
      var bar = document.querySelector('.ux-bottom');
      var barH = bar && getComputedStyle(bar).display !== 'none' ? bar.offsetHeight : 0;
      // premium-plus.css caps the list at min(330px, 42vh); this asks for the
      // same room plus a hair, so the whole list clears the bar when it can.
      var listRoom = Math.min(330, window.innerHeight * .42) + 12;
      var r = row.getBoundingClientRect();
      var overflow = (r.bottom + listRoom) - (window.innerHeight - barH);
      if (overflow <= 0) return;
      // Never past the point where the field itself would leave the top.
      window.scrollBy(0, Math.min(overflow, Math.max(0, r.top - 12)));
    });
  }

  /* ── 6 · Start ──────────────────────────────────────────────────────────
     hh-on is the switch every ambient rule in the stylesheet hangs off. It
     goes on only once the markup exists, so a thrown exception above leaves
     the page in its previous, working state rather than half-animated. */
  function start() {
    var header = document.querySelector('header.wrap');
    if (!header || !document.getElementById('view-screener')) return;
    if (header.classList.contains('hh-stage')) return;

    var ask = buildHero(header);
    dressBackdrop();
    lean(header);
    root.classList.add('hh-on');

    var replay = rotateAsk(ask);
    var input = document.getElementById('tk');
    var retype = null;
    if (input) { keepListInView(input); retype = typePlaceholder(input); }

    function sync() {
      root.classList.toggle('hh-tab-hidden', document.hidden);
      replay();
      if (retype) retype();
    }
    document.addEventListener('visibilitychange', sync);
    reduce.addEventListener('change', sync);
    // home-motion.js writes data-motion on <html> when the Motion button is
    // pressed. Observing the attribute keeps these two timers honest without
    // either file having to know the other exists.
    new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ['data-motion'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
