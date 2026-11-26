/* Altaha — the sign-in gate

   WHAT IT COVERS
   Some tools are for members: Alerts, Big trades, Delivery trends, Investor
   styles, Who owns what, Fund houses and the Strategy lab on the main page,
   and the two pages of their own, Talk to an adviser (advisors.html) and the
   Wealth desk (wealth.html). Opened signed out, each shows a sign-in card in
   its place, and the sign-in page brings the reader back to the same tool.
   Everything else on the site stays open, as it always was.

   WHY IN THE HEAD, AND WHY CSS
   This file runs before the body is drawn and reads the session straight
   from storage (auth.js keeps it under the same key), so a gated view is
   hidden from the first frame instead of flashing up and then vanishing.
   The hiding is a stylesheet rule keyed on a class on <html>, not a branch
   in each tool: a tool opened by any route (the menu, a door card, the
   search palette, a #hash, an old tab button) is covered the same way,
   because whichever way it opens, it is the same element on screen.

   WHAT IT IS NOT
   The data behind these tools is public market data and the API serves it
   to anyone; this decides what the site shows, not what the server sends.
   An account's own data (chats, a desk's clients) is checked server-side
   by the token, as before. */

(function () {
  'use strict';

  var KEY = 'altaha-session-v1';
  var root = document.documentElement;

  /* Tab id → what the card calls it, and why it is worth signing in for. */
  var TOOLS = {
    live:       ['Alerts',          'Intraday signals as they fire.'],
    deals:      ['Big trades',      'Bulk and block deals, and who made them.'],
    special:    ['Delivery trends', 'Where delivery is running above normal.'],
    lenses:     ['Investor styles', 'Stocks picked the way great investors pick them.'],
    investors:  ['Who owns what',   'What well-known investors disclosed holding.'],
    funds:      ['Fund houses',     'What the mutual funds disclosed holding.'],
    strategies: ['Strategy lab',    'Would a trading rule have beaten holding the stock?']
  };
  var PAGES = {
    advisors: ['Talk to an adviser', 'Chat with SEBI-registered advisers, free.', 'adv'],
    wealth:   ['Wealth desk',        'For portfolio managers: clients, calls and commission.', 'wd'],
    broker:   ['Your broker',        'Connect Dhan or Zerodha: see your funds, holdings and orders, and trade from any stock page.', 'bk-page']
  };

  /* Which page this is: a page of its own names itself on the script tag. */
  var me = document.currentScript;
  var pageId = (me && me.getAttribute('data-page')) || '';
  var page = PAGES[pageId] || null;

  function hasSession() {
    if (window.AltahaAuth && typeof window.AltahaAuth.authed === 'function') {
      return window.AltahaAuth.authed();
    }
    try { return !!localStorage.getItem(KEY); } catch (e) { return false; }
  }

  /* The rules. Hidden only while signed out; the inline display a tool sets
     on its own view is beaten by !important, and given back the moment the
     class goes. */
  var css = [];
  Object.keys(TOOLS).forEach(function (id) {
    css.push('html.gate-out #view-' + id);
  });
  var rules = css.join(',') + '{display:none!important}';
  Object.keys(TOOLS).forEach(function (id) {
    rules += 'html.gate-out body[data-tab="' + id + '"] #altaha-gate{display:block}';
  });
  if (page) {
    rules += 'html.gate-out #' + page[2] + '{display:none!important}' +
             'html.gate-out #altaha-gate{display:block}';
  }
  rules +=
    '#altaha-gate{display:none;box-sizing:border-box;max-width:560px;margin:48px auto;padding:0 16px}' +
    '#altaha-gate .ag-card{border:1px solid var(--border);border-radius:14px;' +
      'background:var(--bg);color:var(--text-primary);padding:32px 28px;text-align:center;' +
      'box-shadow:0 1px 2px rgba(0,0,0,.04)}' +
    '#altaha-gate .ag-lock{width:44px;height:44px;margin:0 auto 14px;border-radius:50%;display:grid;' +
      'place-items:center;background:var(--surface-raised);color:var(--text-primary)}' +
    '#altaha-gate .ag-kick{margin:0 0 6px;font:500 12px/1.4 "IBM Plex Mono",ui-monospace,monospace;' +
      'letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted)}' +
    '#altaha-gate h2{margin:0 0 10px;font:400 30px/1.15 "Instrument Serif",Georgia,serif}' +
    '#altaha-gate p.ag-lede{margin:0 auto 22px;max-width:40ch;font:400 15px/1.55 Inter,system-ui,sans-serif;' +
      'color:var(--text-secondary)}' +
    '#altaha-gate .ag-go{display:inline-flex;align-items:center;justify-content:center;min-height:48px;' +
      'padding:0 26px;border-radius:999px;background:var(--accent);color:var(--on-accent);' +
      'font:600 15px/1 Inter,system-ui,sans-serif;text-decoration:none}' +
    '#altaha-gate .ag-go:focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px}' +
    '#altaha-gate .ag-note{margin:14px 0 0;font:400 13px/1.5 Inter,system-ui,sans-serif;color:var(--text-muted)}';

  var style = document.createElement('style');
  style.id = 'altaha-gate-css';
  style.textContent = rules;
  (document.head || root).appendChild(style);

  function sync() {
    root.classList.toggle('gate-out', !hasSession());
    paint();
  }
  sync();

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* Where the sign-in page should send the reader back to. signin.html only
     accepts a page of this site by name plus a hash, so that is the shape. */
  function nextFor() {
    var file = (location.pathname.split('/').pop() || 'index.html');
    if (!/^[a-z][a-z0-9-]*\.html$/.test(file)) file = 'index.html';
    var hash = (location.hash || '').replace(/[^A-Za-z0-9#\/_-]/g, '');
    if (!page && !hash && document.body && document.body.dataset.tab) {
      var nav = window.AltahaNav;
      var owner = nav && nav.ownerOf ? nav.ownerOf(document.body.dataset.tab) : null;
      if (owner) hash = '#' + owner + '/' + document.body.dataset.tab;
    }
    return 'signin.html?next=' + encodeURIComponent(file + hash);
  }

  var shownFor = null;
  function paint() {
    var host = document.getElementById('altaha-gate');
    if (!host) return;
    var tab = page ? pageId : (document.body && document.body.dataset.tab) || '';
    var t = page || TOOLS[tab];
    if (!t || !root.classList.contains('gate-out')) { shownFor = null; return; }
    var key = tab + '|' + location.hash;
    if (shownFor === key) return;
    shownFor = key;
    host.innerHTML =
      '<div class="ag-card" role="region" aria-labelledby="ag-title">' +
        '<div class="ag-lock" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" ' +
          'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
          '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></div>' +
        '<p class="ag-kick">Members only</p>' +
        '<h2 id="ag-title">Sign in to open ' + esc(t[0]) + '</h2>' +
        '<p class="ag-lede">' + esc(t[1]) + ' Sign in with your email and it opens right here.</p>' +
        '<a class="ag-go" id="ag-go" href="' + esc(nextFor()) + '">Sign in to continue</a>' +
        '<p class="ag-note">No password: we email you a six-digit code. It is free.</p>' +
      '</div>';
    var go = document.getElementById('ag-go');
    if (go) go.addEventListener('click', function () {
      if (window.AltahaTrack) window.AltahaTrack('gate_signin_clicked', { tool: tab });
    });
  }

  function mount() {
    if (document.getElementById('altaha-gate')) return;
    var host = document.createElement('div');
    host.id = 'altaha-gate';
    /* A page of its own: the gate stands where its content would. The main
       page: beside the views, so it sits where the tool would have. */
    var anchor = page ? document.getElementById(page[2])
                      : document.getElementById('view-today');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(host, anchor);
    else document.body.insertBefore(host, document.body.firstChild);
    paint();
    if (!page && document.body) {
      new MutationObserver(paint).observe(document.body, { attributes: true, attributeFilter: ['data-tab'] });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  window.addEventListener('altaha-auth', sync);
  window.addEventListener('altaha:navigate', paint);
  window.addEventListener('hashchange', paint);
  window.addEventListener('storage', function (e) {
    if (e.key === KEY || e.key === null) sync();
  });

  window.AltahaGate = {
    tools: Object.keys(TOOLS),
    locked: function (tabId) { return !!TOOLS[tabId] && !hasSession(); },
    sync: sync
  };
})();
