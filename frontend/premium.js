/* ============================================================================
   ALTAHA SCREENER — PREMIUM LAYER  v1
   ----------------------------------------------------------------------------
   Behaviour that the stylesheet cannot express. Strictly additive: this file
   never rewrites existing markup, never rebinds an existing handler, and never
   renames an id. Everything it adds is either a class, a new element, or a
   listener on an element it created itself.

   If this file fails to load, the site behaves exactly as it does today.
============================================================================ */

(function () {
  'use strict';

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ── 1. THEME ─────────────────────────────────────────────────────────
     The initial theme is set by the inline snippet in <head> so there is no
     flash. This only wires the toggle and keeps it in sync with the system
     setting for people who never touch it. */

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
  }

  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('altaha-theme', t); } catch (e) {}
    var b = $('.themebtn');
    if (b) {
      b.textContent = t === 'dark' ? '☾' : '☀';
      b.setAttribute('aria-label', t === 'dark' ? 'Switch to light appearance' : 'Switch to dark appearance');
    }
    // Recolour the chart library, which paints to canvas and ignores CSS vars.
    window.dispatchEvent(new CustomEvent('altaha:theme', { detail: { theme: t } }));
  }

  function buildThemeToggle() {
    var b = document.createElement('button');
    b.className = 'themebtn';
    b.type = 'button';
    b.addEventListener('click', function () {
      applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
    });
    document.body.appendChild(b);
    applyTheme(currentTheme());
  }

  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  (mq.addEventListener ? mq.addEventListener.bind(mq, 'change') : mq.addListener.bind(mq))(function (e) {
    var saved = null;
    try { saved = localStorage.getItem('altaha-theme'); } catch (err) {}
    if (!saved) applyTheme(e.matches ? 'dark' : 'light');
  });

  /* ── 2. HERO ENTRANCE ────────────────────────────────────────────────── */

  function hero() {
    var h = $('header.wrap');
    if (h && !reduced) h.classList.add('hero-in');
  }

  /* ── 3. STICKY COMMAND BAR ───────────────────────────────────────────── */

  function stickyNav() {
    var nav = $('.tabnav');
    if (!nav) return;
    var sentinel = document.createElement('div');
    sentinel.style.cssText = 'position:absolute;height:1px;width:1px;';
    nav.parentNode.insertBefore(sentinel, nav);
    new IntersectionObserver(function (entries) {
      nav.classList.toggle('is-stuck', !entries[0].isIntersecting);
    }, { threshold: 0 }).observe(sentinel);
  }

  /* ── 4. SCROLL REVEAL ────────────────────────────────────────────────────
     Applied to top-level panels only. Reveal on every row is noise; reveal on
     sections reads as intent. */

  var REVEAL = ['#pricewrap', '#volwrap', '#shwrap', '#lvlwrap', '#setupwrap',
                '#plainwrap', '#planwrap', '.verdict', '.sched', '.lh',
                '.statbox', '.ideas-intro'];

  var io = null;
  function revealSetup() {
    if (reduced || !('IntersectionObserver' in window)) return;
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('seen'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.04 });
    scanReveal();
  }

  function scanReveal() {
    if (!io) return;
    $$(REVEAL.join(',')).forEach(function (el) {
      if (el.dataset.rv) return;
      el.dataset.rv = '1';
      el.classList.add('reveal');
      io.observe(el);
    });
  }

  /* ── 5. SCORE COUNT-UP ───────────────────────────────────────────────────
     The existing code writes a final number straight into #score. Watching the
     node lets the number climb without touching the code that sets it. */

  function countUp() {
    var el = $('#score');
    if (!el || reduced) return;
    var animating = false;

    new MutationObserver(function () {
      if (animating) return;
      var target = parseInt((el.textContent || '').replace(/[^0-9]/g, ''), 10);
      if (!isFinite(target) || target <= 0) return;
      if (el.dataset.shown === String(target)) return;

      animating = true;
      el.dataset.shown = String(target);
      var start = performance.now(), dur = 1100;

      (function step(now) {
        var p = Math.min(1, (now - start) / dur);
        var eased = 1 - Math.pow(1 - p, 4);            // matches the arc easing
        el.textContent = Math.round(target * eased);
        if (p < 1) requestAnimationFrame(step);
        else { el.textContent = target; animating = false; }
      })(start);
    }).observe(el, { childList: true, characterData: true, subtree: true });
  }

  /* ── 6. DATA-CONFIDENCE CHIP ─────────────────────────────────────────────
     A 70 built on price alone is not the same object as a 70 built on price
     plus filings, and the seal renders them identically. This reads the basis
     line the backend already sends and labels the difference. */

  function confidence() {
    var basis = $('#vbasis');
    if (!basis) return;

    new MutationObserver(function () {
      if (basis.querySelector('.confchip')) return;
      var txt = (basis.textContent || '').toLowerCase();
      if (!txt) return;

      var cls, label;
      if (txt.indexOf('technical only') > -1) {
        cls = 'thin';
        label = 'Price evidence only';
      } else if (txt.indexOf('50%') > -1) {
        cls = '';
        label = 'Full evidence';
      } else { return; }

      var chip = document.createElement('span');
      chip.className = 'confchip ' + cls;
      chip.innerHTML = '<i></i>' + label;
      chip.title = cls === 'thin'
        ? 'No published financial statements were available, so this score reflects price behaviour alone. It is not comparable with a score that includes fundamentals.'
        : 'Scored on both price behaviour and published financial statements.';
      basis.appendChild(chip);
    }).observe(basis, { childList: true, characterData: true, subtree: true });
  }

  /* ── 7. ⌘K / CTRL-K TO SEARCH ────────────────────────────────────────── */

  function commandK() {
    var input = $('#tk');
    if (!input) return;

    var mac = /Mac|iPhone|iPad/.test(navigator.platform || '');
    var hint = document.createElement('span');
    hint.className = 'kbdhint';
    hint.textContent = mac ? '⌘K' : 'Ctrl K';
    var row = input.closest('.searchrow');
    if (row) row.insertBefore(hint, row.querySelector('button'));

    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        var t = $('#tab-screener');
        if (t && !t.classList.contains('active')) t.click();
        window.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' });
        input.focus(); input.select();
      }
      if (e.key === 'Escape' && document.activeElement === input) input.blur();
    });
  }

  /* ── 8. MOBILE TAB BAR ───────────────────────────────────────────────────
     Five destinations, proxied to the existing desktop buttons with .click().
     No DOM surgery on the real nav, so every existing handler is untouched. */

  var ICONS = {
    screener: '<path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z"/><path d="m20 20-4.2-4.2"/>',
    ideas:    '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6h5.4c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z"/>',
    live:     '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    filings:  '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    portfolio:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'
  };

  var MOB = [
    { id: 'tab-screener',  label: 'Screener',  icon: 'screener'  },
    { id: 'tab-ideas',     label: 'Ideas',     icon: 'ideas'     },
    { id: 'tab-live',      label: 'Live',      icon: 'live'      },
    { id: 'tab-filings',   label: 'Filings',   icon: 'filings'   },
    { id: 'tab-portfolio', label: 'Portfolio', icon: 'portfolio' }
  ];

  function mobileNav() {
    if (!$('#tab-screener')) return;

    var bar = document.createElement('nav');
    bar.className = 'mobnav';
    bar.setAttribute('aria-label', 'Sections');
    var inner = document.createElement('div');
    inner.className = 'mobnav-inner';

    MOB.forEach(function (m) {
      var src = document.getElementById(m.id);
      if (!src) return;
      var b = document.createElement('button');
      b.type = 'button';
      b.dataset.proxy = m.id;
      b.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        ICONS[m.icon] + '</svg><span>' + m.label + '</span>';
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
    if (tabs) new MutationObserver(sync).observe(tabs, {
      subtree: true, attributes: true, attributeFilter: ['class']
    });
  }

  /* ── 9. RESCAN ON CONTENT CHANGE ─────────────────────────────────────────
     Results are injected after an async fetch, so new panels need registering
     with the reveal observer. Debounced to keep this off the critical path. */

  function watchMain() {
    var main = $('main.wrap');
    if (!main) return;
    var t;
    new MutationObserver(function () {
      clearTimeout(t);
      t = setTimeout(scanReveal, 120);
    }).observe(main, { childList: true, subtree: true });
  }

  /* ── BOOT ─────────────────────────────────────────────────────────────── */

  function boot() {
    try { buildThemeToggle(); } catch (e) {}
    try { hero(); }            catch (e) {}
    try { stickyNav(); }       catch (e) {}
    try { revealSetup(); }     catch (e) {}
    try { countUp(); }         catch (e) {}
    try { confidence(); }      catch (e) {}
    try { commandK(); }        catch (e) {}
    try { mobileNav(); }       catch (e) {}
    try { watchMain(); }       catch (e) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
