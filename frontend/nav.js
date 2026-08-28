/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — Navigation
   ═══════════════════════════════════════════════════════════════════════════

   Eleven destinations behind one flat bar plus a More menu, and the bar was
   the first thing a new visitor met. Everything looked equally important, so
   nothing did — and the two strongest modules, the Tracker and the glossary,
   were the two buried deepest.

   This replaces it with two levels:

     Screener   Analysis · Results · Filings
     Portfolio  (single view)
     Ideas      Ideas · Alerts · Track record · Options
     Planner    (single view)
     Social     (overlay)

   Four things to know about how it is built:

   1. It proxies rather than rewrites. The original tab buttons stay in the
      DOM, hidden; the new controls call .click() on them. switchTab and its
      seven data-loading handlers are untouched, so nothing that already works
      can break here.

   2. The More menu is gone entirely, not fixed. Its labels were invisible in
      dark mode because the panel kept a hardcoded white background while its
      buttons used var(--ink). Removing the component removes that class of
      bug rather than patching one instance of it.

   3. Sections are in the URL. #ideas/tracker restores the exact view, so a
      tab can be linked, bookmarked and shared — which the audit asked for and
      which costs almost nothing once routing exists at all.

   4. Choosing a tab scrolls to the content. The hero is tall; without this,
      picking a tab left the user looking at the same hero and wondering
      whether the click had registered.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var SECTIONS = [
    {
      id: 'screener', label: 'Screener',
      blurb: 'Score any stock, read the chart, check the filings',
      icon: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
      tabs: [
        { id: 'screener', label: 'Analysis', hint: 'Score with the full ledger' },
        { id: 'results',  label: 'Results',  hint: 'Latest quarterly numbers' },
        { id: 'filings',  label: 'Filings',  hint: 'Live exchange announcements' }
      ]
    },
    {
      id: 'portfolio', label: 'Portfolio',
      blurb: 'Your holdings, reviewed and graded',
      icon: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
      tabs: [{ id: 'portfolio', label: 'Review', hint: 'Every holding, then the book' }]
    },
    {
      id: 'ideas', label: 'Ideas',
      blurb: 'What the scan found, and how past calls actually did',
      icon: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.8 1 .9 1.6h5.4c.1-.6.4-1.2.9-1.6A6 6 0 0 0 12 3Z"/>',
      tabs: [
        { id: 'ideas',   label: 'Ideas',        hint: "Today's ranked shortlist" },
        { id: 'live',    label: 'Alerts',       hint: 'Intraday scanner' },
        { id: 'tracker', label: 'Track record', hint: 'Measured hit rate' },
        { id: 'options', label: 'Options',      hint: 'Chain, OI and max pain' }
      ]
    },
    {
      id: 'planner', label: 'Planner', brand: 'planner',
      blurb: 'Household money through the same lens',
      icon: '<path d="M3 3v18h18"/><path d="m7 14 3-3 3 3 5-6"/>',
      tabs: []
    },
    {
      id: 'social', label: 'Social',
      blurb: 'Filings and news, ready to post',
      icon: '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v13"/>',
      tabs: []
    }
  ];

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

  var current = { section: 'screener', tab: 'screener' };
  var booting = true;

  function sectionById(id) {
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === id) return SECTIONS[i];
    }
    return SECTIONS[0];
  }

  function ownerOf(tabId) {
    for (var i = 0; i < SECTIONS.length; i++) {
      for (var j = 0; j < SECTIONS[i].tabs.length; j++) {
        if (SECTIONS[i].tabs[j].id === tabId) return SECTIONS[i];
      }
    }
    return null;
  }

  function build() {
    var oldNav = $('.tabnav');
    if (!oldNav) return false;

    oldNav.setAttribute('aria-hidden', 'true');
    oldNav.classList.add('legacy-nav');

    var wrap = el('div', 'navwrap');

    var primary = el('nav', 'navmain');
    primary.setAttribute('role', 'tablist');
    primary.setAttribute('aria-label', 'Sections');

    SECTIONS.forEach(function (s) {
      var b = el('button', 'navmain-btn');
      b.type = 'button';
      b.dataset.section = s.id;
      b.setAttribute('role', 'tab');
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
      var t = $id('tab-vocab');
      if (t) { t.click(); scrollToContent(); }
      markLearn(true);
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
    var s = sectionById(sectionId);
    markLearn(false);

    if (s.id === 'social') {
      if (window.AltahaSocial && typeof window.AltahaSocial.open === 'function') {
        window.AltahaSocial.open();
      } else {
        var so = $id('altaha-social-open');
        if (so) so.click();
      }
      current = { section: s.id, tab: null };
      paint(s, null);
      if (userInitiated) { setHash(s.id, null); }
      return;
    }

    if (s.brand === 'planner') {
      var pb = $id('bsw-planner');
      if (pb) pb.click();
      current = { section: s.id, tab: null };
      paint(s, null);
      if (userInitiated) { setHash(s.id, null); scrollToContent(); }
      return;
    }

    var sb = $id('bsw-screener');
    if (sb && !sb.classList.contains('active')) sb.click();

    var target = tabId;
    if (!target || !s.tabs.some(function (t) { return t.id === target; })) {
      target = s.tabs.length ? s.tabs[0].id : null;
    }

    if (target) {
      var btn = $id('tab-' + target);
      if (btn) btn.click();
    }

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
      if (section.tabs.length > 1) {
        section.tabs.forEach(function (t) {
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
      host.parentNode.classList.toggle('empty', section.tabs.length <= 1);
    }

    var blurb = $('.navblurb');
    if (blurb) blurb.textContent = section.blurb || '';

    syncMobile(section.id);
  }

  function scrollToContent() {
    if (booting) return;
    var anchor = $('.navwrap');
    if (!anchor) return;
    var top = anchor.getBoundingClientRect().top + window.scrollY - 12;
    window.scrollTo({ top: Math.max(0, top), behavior: reduced ? 'auto' : 'smooth' });
  }

  var lastWritten = null;

  function hashFor(sectionId, tabId) {
    return '#' + sectionId + (tabId && tabId !== sectionId ? '/' + tabId : '');
  }

  function setHash(sectionId, tabId) {
    var h = hashFor(sectionId, tabId);
    lastWritten = h;
    if (location.hash !== h) history.replaceState(null, '', h);
  }

  function readHash() {
    var raw = (location.hash || '').replace(/^#/, '').split('/');
    var sectionId = raw[0] || '';
    var tabId = raw[1] || null;
    if (!sectionId) return null;

    var owner = ownerOf(sectionId);
    if (owner && owner.id !== sectionId) return { section: owner.id, tab: sectionId };

    var known = SECTIONS.some(function (s) { return s.id === sectionId; });
    return known ? { section: sectionId, tab: tabId } : null;
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
    bar.setAttribute('aria-label', 'Sections');
    var inner = el('div', 'navmob-inner');

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

    var r = readHash();
    if (r) go(r.section, r.tab, false);
    else paint(SECTIONS[0], 'screener');

    var legacy = $('.legacy-nav');
    if (legacy) {
      new MutationObserver(function () {
        var active = null;
        ['screener', 'ideas', 'filings', 'live', 'portfolio',
         'results', 'options', 'tracker'].forEach(function (t) {
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

  window.AltahaNav = { go: go, sections: SECTIONS };
})();
