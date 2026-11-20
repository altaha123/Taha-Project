/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — query.js

   The screener: every stored company, narrowed to the ones that fit what
   the reader asks for. Ideas → Screener (#research/query).

   TWO SECTIONS, ONE QUESTION UNDERNEATH
   Two tabs sit under the title, and each is a whole way of asking.

   "Pick what you want" asks nothing in numbers. It shows a handful of things
   a person might want from a company ("Makes good money", "Owes little",
   "Not too pricey"), each a card to tap, with three settings where a setting
   makes sense. Tapping writes the rules, runs them and shows who is left,
   and a strip of bars shows how each choice narrowed the list. Nothing has
   to be typed, and there is no button to press to see a result.

   "Make your own query" is the editor, for a reader who knows the number
   they want. It used to be folded away at the foot of the first section
   behind a line of small type, where it read as a footnote and not as a
   second way in; it is a section of its own now, one tap from the top:

     · the server's example queries, each just a query they can edit;
     · a three-box builder (field, comparison, value) that writes the line;
     · suggestions as they type, from every field name and alias;
     · every field listed with what it means, one click to insert;
     · an error that says what is wrong and offers the field they meant.

   The two are one query. A choice writes its lines into the editor; a query
   typed or opened from a link is read back into the choices it matches, and
   anything left over is carried as "your own rules". The results table sits
   under both. A query that arrives from outside (a link, a saved screen, the
   last visit) opens the section that can show all of it: the editor if any
   line is not a card's, the cards otherwise. Nothing moves the reader
   between sections while they are working in one.

   The parsing and the figures live in backend/fundamentals_query.py; this
   file never evaluates anything. The query is kept in the address
   (#research/query/<query>) so a result can be bookmarked or shared.

   Ask AI (admin key only) is a conversation with Claude that answers what
   can be screened and writes queries, each checked by the screener's own
   parser before it is shown — see backend/query_assistant.py.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';
  var PAGE = 50;
  var KEY = 'altaha.query.last';

  var meta = null, metaPending = null, built = false;
  var state = { q: '', sort: '', order: 'desc', results: [], data: null, busy: false, err: '', again: false };
  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  function still() { return REDUCED || document.documentElement.getAttribute('data-motion') === 'off'; }
  var ac = { items: [], active: 0, from: 0, to: 0, open: false };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function getJSON(path) {
    return fetch(API + path, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) {
          var err = new Error((body && body.detail) || ('HTTP ' + r.status));
          err.status = r.status;
          err.body = body;
          throw err;
        }
        return body;
      });
    });
  }
  function norm(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9%]/g, ''); }

  /* ── Formatting a figure by its unit ─────────────────────────────────── */

  function fmt(v, unit) {
    if (v == null || v === '') return '<span class="qs-na" title="Not available">—</span>';
    if (unit === 'text') return esc(v);
    var n = Number(v);
    if (!isFinite(n)) return '—';
    var abs = Math.abs(n);
    var dp = unit === 'cr' ? (abs >= 100 ? 0 : 1)
      : unit === 'x' ? (abs >= 100 ? 0 : 2)
      : unit === 'inr' ? (abs >= 1000 ? 0 : 2)
      : (abs >= 100 ? 0 : 1);
    var s = Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: dp,
                                                  minimumFractionDigits: 0 });
    var sign = n < 0 ? '-' : '';
    if (unit === 'pct') return sign + s + '%';
    if (unit === 'x') return sign + s + '×';
    if (unit === 'inr') return sign + '₹' + s;
    if (unit === 'cr') return sign + '₹' + s + ' cr';
    return sign + s;
  }
  var UNIT_WORD = { cr: '₹ crore', inr: '₹', pct: '%', x: 'times', num: 'number', text: 'text' };

  /* ── Address ─────────────────────────────────────────────────────────── */

  function hashParts() { return (location.hash || '').replace(/^#/, '').split('/'); }
  function onRoute() { var p = hashParts(); return p[1] === 'query' || p[0] === 'query'; }
  function queryFromHash() {
    var p = hashParts();
    var i = p[1] === 'query' ? 2 : (p[0] === 'query' ? 1 : -1);
    if (i < 0 || !p[i]) return '';
    try { return decodeURIComponent(p.slice(i).join('/')); } catch (e) { return ''; }
  }
  function writeHash(q) {
    var h = '#research/query' + (q ? '/' + encodeURIComponent(q) : '');
    if (location.hash !== h) {
      try { history.replaceState(null, '', h); } catch (e) {}
    }
  }
  function remember(q) { try { localStorage.setItem(KEY, q); } catch (e) {} }
  function recall() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } }

  /* ── Saved screens ──────────────────────────────────────────────────────
     Named queries the reader keeps. Signed in they live on the account
     (/me/screens) and follow the reader to every device; signed out they are
     kept in this browser, and move to the account the first time the reader
     signs in here. One list either way — the reader never has to know which
     store it came from. */

  var SAVED_KEY = 'altaha.query.saved';
  var saved = [];

  function signedIn() { return !!(window.AltahaAuth && window.AltahaAuth.authed && window.AltahaAuth.authed()); }
  function localScreens() {
    try { var v = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); return Array.isArray(v) ? v : []; }
    catch (e) { return []; }
  }
  function writeLocal(list) { try { localStorage.setItem(SAVED_KEY, JSON.stringify(list.slice(0, 25))); } catch (e) {} }
  function api(path, opts) {
    return window.AltahaAuth.fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Could not reach your account.');
        return d;
      });
    });
  }

  function loadSaved() {
    if (!signedIn()) { saved = localScreens(); paintSaved(); return Promise.resolve(saved); }
    // Screens kept in this browser before signing in go to the account once.
    var pending = localScreens();
    var upload = pending.reduce(function (p, sc) {
      return p.then(function () {
        return api('/me/screens', { method: 'PUT', body: JSON.stringify({ name: sc.name, query: sc.query }) })
          .catch(function () {});
      });
    }, Promise.resolve());
    return upload.then(function () {
      if (pending.length) writeLocal([]);
      return api('/me/screens');
    }).then(function (d) { saved = d.screens || []; paintSaved(); return saved; })
      .catch(function () { saved = localScreens(); paintSaved(); return saved; });
  }

  function paintSaved() {
    var box = $('qs-saved');
    if (!box) return;
    if (!saved.length) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<span class="qs-exlab">Your screens</span>' + saved.map(function (sc, i) {
      return '<span class="qs-schip"><button type="button" class="qs-chip" data-saved="' + i + '" title="' +
        esc(String(sc.query).replace(/\n/g, ' AND ')) + '">' + esc(sc.name) + '</button>' +
        '<button type="button" class="qs-sdel" data-delsaved="' + i + '" aria-label="Delete saved screen ' +
        esc(sc.name) + '">×</button></span>';
    }).join('') + (signedIn() ? '' : '<a class="qs-ssign" href="signin.html">Sign in to keep them on every device</a>');
  }

  function saveScreen(name, query) {
    name = String(name || '').replace(/\s+/g, ' ').trim();
    if (!name) return Promise.reject(new Error('Give the screen a name.'));
    if (!query) return Promise.reject(new Error('There is no query to save.'));
    if (signedIn()) {
      return api('/me/screens', { method: 'PUT', body: JSON.stringify({ name: name, query: query }) })
        .then(function (d) { saved = d.screens || []; paintSaved(); });
    }
    var list = localScreens().filter(function (sc) { return sc.name !== name; });
    if (list.length >= 25) return Promise.reject(new Error('You have 25 saved screens — delete one to save another.'));
    list.unshift({ name: name, query: query, updated_at: new Date().toISOString() });
    writeLocal(list);
    saved = list; paintSaved();
    return Promise.resolve();
  }

  function deleteSaved(i) {
    var sc = saved[i];
    if (!sc) return;
    if (signedIn() && sc.id != null) {
      api('/me/screens/' + encodeURIComponent(sc.id), { method: 'DELETE' })
        .then(function (d) { saved = d.screens || []; paintSaved(); })
        .catch(function () {});
      return;
    }
    var list = localScreens().filter(function (x) { return x.name !== sc.name; });
    writeLocal(list); saved = list; paintSaved();
  }

  window.addEventListener('altaha-auth', function () { if (built) loadSaved(); });

  /* ── The page ────────────────────────────────────────────────────────── */

  function skeleton(host) {
    host.innerHTML =
      '<header class="qs-head">' +
        '<p class="ln-kicker">Ideas · Screener</p>' +
        '<h2>Find stocks your way</h2>' +
        '<p>Two ways to do it. Pick what you want from ready-made choices, or write your own query. ' +
          'Either way the list updates as you go.</p>' +
      '</header>' +
      '<div class="qs-modes" id="qs-modes" role="tablist" aria-label="How to find stocks">' +
        '<button type="button" class="qs-mode on" id="qs-mode-pick" role="tab" data-mode="pick" ' +
          'aria-selected="true" aria-controls="qz">' +
          '<span class="qs-mode-ic" aria-hidden="true">👆</span>' +
          '<span class="qs-mode-t"><b>Pick what you want</b><span>Tap cards. Nothing to type.</span></span></button>' +
        '<button type="button" class="qs-mode" id="qs-mode-write" role="tab" data-mode="write" ' +
          'aria-selected="false" aria-controls="qs-adv" tabindex="-1">' +
          '<span class="qs-mode-ic" aria-hidden="true">✍️</span>' +
          '<span class="qs-mode-t"><b>Make your own query</b><span>Write the exact rules and numbers.</span></span></button>' +
      '</div>' +
      '<div class="qs-saved" id="qs-saved" aria-label="Your saved screens" hidden></div>' +
      '<section class="qz" id="qz" role="tabpanel" aria-labelledby="qs-mode-pick">' +
        '<div class="qz-step">' +
          '<h3 class="qz-h"><span class="qz-num" aria-hidden="true">1</span>Start with a ready-made idea' +
            '<small>or skip straight to step 2</small></h3>' +
          '<div class="qz-recipes" id="qz-recipes"></div>' +
        '</div>' +
        '<div class="qz-step">' +
          '<h3 class="qz-h"><span class="qz-num" aria-hidden="true">2</span>Pick what matters to you' +
            '<small>as many as you like</small></h3>' +
          '<div class="qz-wishes" id="qz-wishes"></div>' +
        '</div>' +
        '<div class="qz-step qz-result" id="qz-result">' +
          '<h3 class="qz-h"><span class="qz-num" aria-hidden="true">3</span>See who fits</h3>' +
          '<div class="qz-board" id="qz-board" aria-live="polite"></div>' +
          '<div class="qz-acts" id="qz-acts" hidden>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qz-reset">Start over</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qz-save">Save this list</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-copy" hidden>Copy link</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qz-edit">Edit as a query</button>' +
          '</div>' +
        '</div>' +
        '<button type="button" class="qz-float" id="qz-float" hidden></button>' +
      '</section>' +
      '<section class="qs-adv" id="qs-adv" role="tabpanel" aria-labelledby="qs-mode-write" hidden>' +
        '<div class="qz-step">' +
          '<h3 class="qz-h"><span class="qz-num" aria-hidden="true">1</span>Start from an example' +
            '<small>or skip straight to step 2</small></h3>' +
          '<div class="qs-examples" id="qs-examples" aria-label="Example queries"></div>' +
        '</div>' +
        '<div class="qz-step">' +
        '<h3 class="qz-h"><span class="qz-num" aria-hidden="true">2</span>Write your rules' +
          '<small>one per line</small></h3>' +
        '<div class="qs-card">' +
        '<div class="qs-builder" role="group" aria-label="Add a condition">' +
          '<label class="qs-lab"><span>Field</span><select id="qs-bfield"></select></label>' +
          '<label class="qs-lab qs-lab-op"><span>Is</span><select id="qs-bop">' +
            '<option value=">">greater than</option><option value="<">less than</option>' +
            '<option value=">=">at least</option><option value="<=">at most</option>' +
            '<option value="=">equal to</option></select></label>' +
          '<label class="qs-lab qs-lab-val"><span>Value <i id="qs-bunit"></i></span>' +
            '<input id="qs-bval" type="text" inputmode="decimal" autocomplete="off" placeholder="15"></label>' +
          '<button type="button" class="qs-btn qs-btn-ghost" id="qs-badd">+ Add condition</button>' +
        '</div>' +
        '<div class="qs-editor">' +
          '<label for="qs-q" class="qs-edlab">Your query <span>one rule per line — ' +
            'a company has to meet all of them</span></label>' +
          '<div class="qs-edwrap">' +
            '<textarea id="qs-q" rows="5" spellcheck="false" autocomplete="off" ' +
              'aria-autocomplete="list" aria-controls="qs-ac" ' +
              'placeholder="Market cap > 500&#10;ROE > 15&#10;Debt to equity < 0.5"></textarea>' +
            '<ul id="qs-ac" class="qs-ac" role="listbox" hidden></ul>' +
          '</div>' +
          '<p class="qs-hint">Use <code>AND</code>, <code>OR</code>, <code>NOT</code> and brackets; ' +
            'compare fields with each other or do sums (<code>Market cap / Sales &lt; 3</code>); ' +
            'match text in quotes (<code>Industry contains "bank"</code>). ' +
            '<kbd>Ctrl</kbd>+<kbd>Enter</kbd> runs it.</p>' +
          '<div id="qs-err" class="qs-err" role="alert" hidden></div>' +
          '<div class="qs-actions">' +
            '<button type="button" class="qs-btn qs-btn-go" id="qs-run">Run query</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-clear">Clear</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-save">Save screen</button>' +
            '<button type="button" class="qs-btn qs-aibtn" id="qs-aibtn" aria-expanded="false" ' +
              'aria-controls="qs-ai"><span class="qs-aispark" aria-hidden="true">✦</span>Ask AI' +
              '<span class="qs-aitag">Admin</span></button>' +
          '</div>' +
          /* One form for both Save buttons. It sits here, and moves under
             step 3 when "Save this list" up there is the one pressed. */
          '<form class="qs-saveform" id="qs-saveform" hidden>' +
            '<label for="qs-savename">Give this list a name</label>' +
            '<input id="qs-savename" type="text" maxlength="60" autocomplete="off" placeholder="e.g. Safe and growing">' +
            '<button type="submit" class="qs-btn qs-btn-go" id="qs-savego">Save</button>' +
            '<button type="button" class="qs-btn qs-btn-ghost" id="qs-savecancel">Cancel</button>' +
            '<p class="qs-savemsg" id="qs-savemsg" role="status"></p>' +
          '</form>' +
        '</div>' +
        '<section class="qs-ai" id="qs-ai" aria-labelledby="qs-ai-title" hidden>' +
          '<div class="qs-ai-head">' +
            '<div><h3 class="qs-ai-title" id="qs-ai-title"><span aria-hidden="true">✦</span> Ask AI</h3>' +
              '<p class="qs-ai-sub">Ask what you can screen on, or describe the companies you want. ' +
              'Claude writes the query and checks it against every company before you see it.</p></div>' +
            '<div class="qs-ai-tools">' +
              '<button type="button" class="qs-btn qs-btn-ghost qs-ai-mini" id="qs-ai-reset" hidden>New chat</button>' +
              '<button type="button" class="qs-btn qs-btn-ghost qs-ai-mini" id="qs-ai-lock" hidden>Lock</button>' +
              '<button type="button" class="qs-ai-x" id="qs-ai-close" aria-label="Close Ask AI">×</button>' +
            '</div>' +
          '</div>' +
          '<form class="qs-ai-key" id="qs-ai-keyform" autocomplete="off">' +
            '<label for="qs-ai-keyin">Admin key</label>' +
            '<div class="qs-ai-keyrow">' +
              '<input id="qs-ai-keyin" type="password" autocomplete="off" spellcheck="false" ' +
                'placeholder="The ADMIN_KEY set on the server">' +
              '<button type="submit" class="qs-btn qs-btn-go" id="qs-ai-keygo">Unlock</button>' +
            '</div>' +
            '<p class="qs-ai-fine" id="qs-ai-keymsg" role="status"></p>' +
          '</form>' +
          '<div class="qs-ai-chat" id="qs-ai-chat" hidden>' +
            '<div class="qs-ai-log" id="qs-ai-log" aria-live="polite" hidden></div>' +
            '<div class="qs-ai-starters" id="qs-ai-starters" aria-label="Questions to start with" hidden></div>' +
            '<form class="qs-ai-ask" id="qs-ai-form">' +
              '<textarea id="qs-ai-in" rows="2" aria-label="Ask Claude about the screener" ' +
                'placeholder="e.g. Debt-free companies growing profits 20% a year"></textarea>' +
              '<button type="submit" class="qs-btn qs-btn-go" id="qs-ai-send">Ask</button>' +
            '</form>' +
            '<p class="qs-ai-fine" id="qs-ai-foot"></p>' +
          '</div>' +
        '</section>' +
        '</div>' +
        '<details class="qs-ref" id="qs-ref"><summary>Every field you can use ' +
          '<span id="qs-refn"></span></summary>' +
          '<input id="qs-find" class="qs-find" type="search" placeholder="Find a field — e.g. debt, growth, promoter">' +
          '<div id="qs-fields"></div></details>' +
        '</div>' +
      '</section>' +
      '<div id="qs-out" class="qs-out"></div>' +
      '<p class="ln-notice qs-notice" role="note" id="qs-notice"></p>';
    paintFinder();
    paintBoard();
  }

  /* ── The two sections ───────────────────────────────────────────────────
     One is on screen at a time. `follow` is set when a query is about to run
     that the reader did not make in the section they are looking at (it came
     from the address, a saved screen or their last visit); when its answer
     arrives the section that can show all of it opens. A tap on a card or a
     press of Run query never sets it, so nobody is moved out of the section
     they are working in. */

  var mode = 'pick', follow = false;

  function setMode(m, focus) {
    mode = m === 'write' ? 'write' : 'pick';
    [['pick', 'qz'], ['write', 'qs-adv']].forEach(function (pair) {
      var on = pair[0] === mode, tab = $('qs-mode-' + pair[0]);
      $(pair[1]).hidden = !on;
      tab.classList.toggle('on', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      if (on && focus) tab.focus();
    });
    paintFloat();
  }

  /* ── The finder ─────────────────────────────────────────────────────────
     WISHES are the things a reader can ask for. Each has up to three
     settings, and each setting is nothing but lines of the query language
     the editor below takes, so a choice here and a line typed there are the
     same thing. `say` is the card's one line; `note` says what a setting
     means in rupees on a hundred, which is how the figure would be explained
     to somebody who has never met it; `num` is the same in the terms the
     results table uses. Every line is checked against the server's parser
     by backend/tests/test_query_wishes.py, so a renamed field fails a test
     and not a reader.

     RECIPES are starting points: a few wishes switched on together. They
     are not a second kind of thing; after one is tapped the cards show
     exactly what it chose, and each can be changed. */

  var WISHES = [
    { id: 'profit', icon: '💰', tint: '176,141,46', title: 'Makes good money', say: 'Earns well on what its owners put in', def: 0,
      levels: [
        { tag: 'Good',  q: ['ROE > 12'], num: 'ROE above 12%', note: 'Earns more than ₹12 a year on every ₹100 of its owners’ money.' },
        { tag: 'Great', q: ['ROE > 18'], num: 'ROE above 18%', note: 'Earns more than ₹18 a year on every ₹100 of its owners’ money.' },
        { tag: 'Top',   q: ['ROE > 25'], num: 'ROE above 25%', note: 'Earns more than ₹25 a year on every ₹100 of its owners’ money.' }] },
    { id: 'growth', icon: '🌱', tint: '47,125,79', title: 'Growing fast', say: 'Sells more and earns more every year', def: 0,
      levels: [
        { tag: 'Steady', q: ['Sales growth 3Y > 10', 'Profit growth 3Y > 10'], num: 'Sales and profit up 10% a year, 3 years', note: 'Sales and profit both grew more than 10% a year over three years.' },
        { tag: 'Fast',   q: ['Sales growth 3Y > 15', 'Profit growth 3Y > 15'], num: 'Sales and profit up 15% a year, 3 years', note: 'Sales and profit both grew more than 15% a year over three years.' },
        { tag: 'Racing', q: ['Sales growth 3Y > 25', 'Profit growth 3Y > 25'], num: 'Sales and profit up 25% a year, 3 years', note: 'Sales and profit both grew more than 25% a year over three years.' }] },
    { id: 'debt', icon: '🕊️', tint: '68,125,159', title: 'Owes little', say: 'Has not borrowed much', def: 1,
      levels: [
        { tag: 'Some',        q: ['Debt to equity < 1'],   num: 'Debt to equity under 1',   note: 'Has borrowed less than its own money: under ₹100 for every ₹100 it owns.' },
        { tag: 'Little',      q: ['Debt to equity < 0.5'], num: 'Debt to equity under 0.5', note: 'Has borrowed less than ₹50 for every ₹100 of its own money.' },
        { tag: 'Almost none', q: ['Debt to equity < 0.1'], num: 'Debt to equity under 0.1', note: 'Has borrowed less than ₹10 for every ₹100 of its own money.' }] },
    { id: 'cheap', icon: '🏷️', tint: '176,58,43', title: 'Not too pricey', say: 'The share price is low for what it earns', def: 1,
      levels: [
        { tag: 'Fair',       q: ['PE > 0', 'PE < 30'], num: 'PE under 30', note: 'You pay less than ₹30 for every ₹1 it earns in a year. Loss-makers are left out.' },
        { tag: 'Cheap',      q: ['PE > 0', 'PE < 20'], num: 'PE under 20', note: 'You pay less than ₹20 for every ₹1 it earns in a year. Loss-makers are left out.' },
        { tag: 'Very cheap', q: ['PE > 0', 'PE < 12'], num: 'PE under 12', note: 'You pay less than ₹12 for every ₹1 it earns in a year. Loss-makers are left out.' }] },
    { id: 'dividend', icon: '🎁', tint: '128,90,170', title: 'Pays you every year', say: 'Shares its profit as dividends', def: 0,
      levels: [
        { tag: 'A little', q: ['Dividend yield > 1'], num: 'Dividend yield above 1%', note: 'Pays more than ₹1 a year on every ₹100 of its shares.' },
        { tag: 'Good',     q: ['Dividend yield > 2'], num: 'Dividend yield above 2%', note: 'Pays more than ₹2 a year on every ₹100 of its shares.' },
        { tag: 'A lot',    q: ['Dividend yield > 4'], num: 'Dividend yield above 4%', note: 'Pays more than ₹4 a year on every ₹100 of its shares.' }] },
    { id: 'size', icon: '🏢', tint: '90,100,120', title: 'How big?', say: 'Choose the size of company', def: 2, kind: 'choice',
      levels: [
        { tag: 'Small',  q: ['Market cap < 5000'], num: 'Market cap under ₹5,000 cr', note: 'All its shares together are worth less than ₹5,000 crore.' },
        { tag: 'Medium', q: ['Market cap >= 5000', 'Market cap < 50000'], num: 'Market cap ₹5,000 to ₹50,000 cr', note: 'All its shares together are worth ₹5,000 to ₹50,000 crore.' },
        { tag: 'Big',    q: ['Market cap >= 50000'], num: 'Market cap above ₹50,000 cr', note: 'All its shares together are worth more than ₹50,000 crore.' }] },
    { id: 'owners', icon: '🔑', tint: '190,120,30', title: 'Founders still own a lot', say: 'The people who run it hold a big share', def: 1,
      levels: [
        { tag: 'A fair share', q: ['Promoter holding > 40'], num: 'Promoter holding above 40%', note: 'The founders and their family own more than 40 of every 100 shares.' },
        { tag: 'Half',         q: ['Promoter holding > 50'], num: 'Promoter holding above 50%', note: 'The founders and their family own more than half the company.' },
        { tag: 'Most of it',   q: ['Promoter holding > 65'], num: 'Promoter holding above 65%', note: 'The founders and their family own more than 65 of every 100 shares.' }] },
    { id: 'clean', icon: '🔒', tint: '40,130,130', title: 'No shares pawned', say: 'The owners have not pledged shares for loans', def: 0,
      levels: [
        { tag: 'None', q: ['Pledged percentage = 0'], num: 'Pledged shares: 0%', note: 'The owners have not handed over any of their shares as security for a loan.' }] },
    { id: 'cash', icon: '💵', tint: '31,122,85', title: 'Brings in real cash', say: 'Profit that turns up in the bank', def: 1,
      levels: [
        { tag: 'Some',   q: ['Operating cash flow > 0'], num: 'Operating cash flow positive', note: 'The business itself brought in cash last year.' },
        { tag: 'Plenty', q: ['Operating cash flow > 0', 'Free cash flow 3Y > 0'], num: 'Free cash flow positive over 3 years', note: 'It brought in cash, and had some left after paying for its own growth, over three years.' },
        { tag: 'All of it', q: ['Operating cash flow > 0', 'Free cash flow 3Y > 0', 'Cash conversion > 1'], num: 'Cash conversion above 1', note: 'It had cash left over, and every rupee of profit arrived as a rupee of cash or more.' }] },
    { id: 'hot', icon: '🔥', tint: '214,110,40', title: 'Had a strong last quarter', say: 'The newest results were clearly better', def: 0,
      levels: [
        { tag: 'Better',      q: ['Sales growth YoY quarter > 10', 'Profit growth YoY quarter > 10'], num: 'Latest quarter up 10% on last year', note: 'Sales and profit were both more than 10% higher than in the same three months last year.' },
        { tag: 'Much better', q: ['Sales growth YoY quarter > 20', 'Profit growth YoY quarter > 20'], num: 'Latest quarter up 20% on last year', note: 'Sales and profit were both more than 20% higher than in the same three months last year.' },
        { tag: 'Booming',     q: ['Sales growth YoY quarter > 40', 'Profit growth YoY quarter > 40'], num: 'Latest quarter up 40% on last year', note: 'Sales and profit were both more than 40% higher than in the same three months last year.' }] }
  ];

  var RECIPES = [
    { id: 'steady',  icon: '🛡️', name: 'Safe and steady',     say: 'Big, earns well, owes little',           set: [['size', 2], ['profit', 0], ['debt', 1]] },
    { id: 'growers', icon: '🚀', name: 'Fast growers',        say: 'Sales and profit climbing quickly',      set: [['growth', 1], ['profit', 0]] },
    { id: 'bargain', icon: '🛍️', name: 'Good and not pricey', say: 'Earns well, and the price is low',       set: [['cheap', 1], ['profit', 0], ['debt', 0]] },
    { id: 'income',  icon: '🏦', name: 'Pays you to hold',    say: 'Dividends from a healthy business',      set: [['dividend', 1], ['profit', 0], ['debt', 1]] },
    { id: 'nodebt',  icon: '🧘', name: 'Debt-free winners',   say: 'Owes almost nothing, earns a lot',       set: [['debt', 2], ['profit', 1]] },
    { id: 'owner',   icon: '👑', name: 'Run by its owners',   say: 'Founders hold most of it, none pawned',  set: [['owners', 1], ['clean', 0], ['profit', 0]] }
  ];

  var pick = [];        // what the reader chose: [{ id, level }], in the order chosen
  var custom = [];      // lines in the query that no choice explains ("your own rules")
  var counts = {};      // query → { count, screened }, so a bar is asked for once
  var runTimer = null, funnelGen = 0, shownCount = 0;

  function wishById(id) {
    for (var i = 0; i < WISHES.length; i++) if (WISHES[i].id === id) return WISHES[i];
    return null;
  }
  function picked(id) {
    for (var i = 0; i < pick.length; i++) if (pick[i].id === id) return pick[i];
    return null;
  }
  function linesFor(p) { return wishById(p.id).levels[p.level].q; }
  function tidy(line) { return String(line).replace(/\s+/g, ' ').trim(); }

  /* The query the choices amount to: each choice's lines in the order it was
     chosen, a line two choices share written once, then the reader's own. */
  function buildQuery(upTo) {
    var out = [], n = upTo == null ? pick.length : upTo;
    pick.slice(0, n).forEach(function (p) {
      linesFor(p).forEach(function (l) { if (out.indexOf(l) < 0) out.push(l); });
    });
    if (upTo == null) custom.forEach(function (l) { if (out.indexOf(l) < 0) out.push(l); });
    return out.join('\n');
  }

  /* The other way: a query (typed, opened from a link, or a saved screen)
     read back into the choices it is made of. The strictest setting that
     fits is the one taken, so "Plenty of cash" is not read as "Some cash"
     and a stray line. Whatever no choice accounts for is kept as it is. */
  function readQuery(q) {
    var lines = String(q || '').split('\n').map(tidy).filter(Boolean);
    var left = lines.slice(), found = [];
    WISHES.forEach(function (w) {
      var order = w.levels.map(function (l, i) { return i; }).sort(function (a, b) {
        return w.levels[b].q.length - w.levels[a].q.length || b - a;
      });
      for (var k = 0; k < order.length; k++) {
        var L = w.levels[order[k]].q;
        if (L.every(function (x) { return left.indexOf(x) > -1; })) {
          found.push({ id: w.id, level: order[k], at: lines.indexOf(L[L.length - 1]) });
          L.forEach(function (x) { left.splice(left.indexOf(x), 1); });
          break;
        }
      }
    });
    found.sort(function (a, b) { return a.at - b.at; });
    pick = found.map(function (f) { return { id: f.id, level: f.level }; });
    custom = left;
  }

  function recipeOn(r) {
    return !custom.length && r.set.length === pick.length && r.set.every(function (s) {
      var p = picked(s[0]);
      return p && p.level === s[1];
    });
  }

  function paintFinder() {
    var rec = $('qz-recipes'), box = $('qz-wishes');
    if (!rec || !box) return;
    rec.innerHTML = RECIPES.map(function (r) {
      var on = recipeOn(r);
      return '<button type="button" class="qz-recipe' + (on ? ' on' : '') + '" data-recipe="' + esc(r.id) +
        '" aria-pressed="' + on + '"><span class="qz-emoji" aria-hidden="true">' + r.icon + '</span>' +
        '<span class="qz-recipe-t"><b>' + esc(r.name) + '</b><span>' + esc(r.say) + '</span></span></button>';
    }).join('');
    box.innerHTML = WISHES.map(function (w) {
      var p = picked(w.id), on = !!p, lv = on ? p.level : w.def, L = w.levels[lv];
      return '<div class="qz-wish' + (on ? ' on' : '') + '" data-wishbox="' + esc(w.id) + '" style="--tint:' + w.tint + '">' +
        '<button type="button" class="qz-wish-main" data-wish="' + esc(w.id) + '" aria-pressed="' + on + '">' +
          '<span class="qz-emoji" aria-hidden="true">' + w.icon + '</span>' +
          '<span class="qz-wish-t"><b>' + esc(w.title) + '</b><span>' + esc(w.say) + '</span></span>' +
          '<span class="qz-tick" aria-hidden="true"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
            'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span>' +
        '</button>' +
        (on ? '<div class="qz-more">' +
          (w.levels.length > 1 ? '<div class="qz-levels" role="group" aria-label="' + esc(w.title) + ': ' +
              (w.kind === 'choice' ? 'which' : 'how much') + '">' +
            w.levels.map(function (l, i) {
              return '<button type="button" class="qz-level' + (i === lv ? ' on' : '') + '" data-wish="' + esc(w.id) +
                '" data-level="' + i + '" aria-pressed="' + (i === lv) + '">' + esc(l.tag) + '</button>';
            }).join('') + '</div>' : '') +
          '<p class="qz-note">' + esc(L.note) + ' <span class="qz-numtag">' + esc(L.num) + '</span></p>' +
        '</div>' : '') +
      '</div>';
    }).join('');
  }

  /* A choice changed: write the query it amounts to, show the cards as they
     now stand at once, and run a moment later, so three quick taps are one
     question to the server and not three. */
  function chosen() {
    var q = buildQuery();
    if (ta()) ta().value = q;
    paintFinder();
    clearTimeout(runTimer);
    if (!q) { clearAll(); return; }
    paintBoard('counting');
    runTimer = setTimeout(function () { state.sort = ''; run(false); }, 160);
  }

  function toggleWish(id) {
    var i = pick.map(function (p) { return p.id; }).indexOf(id);
    if (i > -1) pick.splice(i, 1);
    else pick.push({ id: id, level: wishById(id).def });
    chosen();
  }
  function setLevel(id, level) {
    var p = picked(id);
    if (!p || p.level === level) return;
    p.level = level;
    chosen();
  }
  function useRecipe(id) {
    var r = RECIPES.filter(function (x) { return x.id === id; })[0];
    if (!r) return;
    if (recipeOn(r)) pick = [];                     // tapping the lit one again switches it off
    else pick = r.set.map(function (s) { return { id: s[0], level: s[1] }; });
    custom = [];
    chosen();
  }

  function nf(x) { return Number(x || 0).toLocaleString('en-IN'); }

  function countFor(q) {
    if (counts[q]) return Promise.resolve(counts[q]);
    return getJSON('/fundamentals/query?q=' + encodeURIComponent(q) + '&limit=1&offset=0').then(function (d) {
      if (!d || d.available === false) throw new Error('unavailable');
      counts[q] = { count: d.count, screened: d.screened };
      return counts[q];
    });
  }

  /* A number that climbs or falls to its new value, so a change of mind is
     seen to change the answer. The true figure is written first and last. */
  function tickTo(node, to) {
    var from = shownCount;
    shownCount = to;
    node.textContent = nf(to);
    if (still() || from === to || !window.requestAnimationFrame) return;
    var t0 = null, dur = 520;
    node.textContent = nf(from);
    (function step(ts) {
      if (t0 === null) t0 = ts;
      var k = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      if (shownCount !== to) return;                // a newer answer has taken over
      node.textContent = nf(Math.round(from + (to - from) * e));
      if (k < 1) requestAnimationFrame(step);
    })(performance.now());
  }

  /* Step 3. What it says depends on where the reader is:
       nothing chosen     an invitation, and no number
       'counting'         the bars as they stood, dimmed
       'down'             the server did not answer, and a way to ask again
       otherwise          the count, and a bar for each choice in turn. */
  function paintBoard(mode) {
    var board = $('qz-board'), acts = $('qz-acts');
    if (!board) return;
    var any = pick.length || custom.length;
    acts.hidden = !any;
    if (!any) {
      shownCount = 0;
      board.className = 'qz-board is-empty';
      board.innerHTML = '<p class="qz-wait"><span aria-hidden="true">👆</span> Tap a card above and the companies that fit appear here.</p>';
      paintFloat();
      return;
    }
    if (mode === 'counting' && board.querySelector('.qz-count')) { board.classList.add('is-counting'); return; }
    if (mode === 'down') {
      board.className = 'qz-board is-down';
      board.innerHTML = '<p class="qz-wait">The list could not be fetched just now. The server may be waking up, ' +
        'which takes about half a minute. <button type="button" class="qs-btn qs-btn-ghost" id="qz-retry">Try again</button></p>';
      paintFloat();
      return;
    }
    var d = state.data;
    if (!d || mode === 'counting') {
      board.className = 'qz-board is-counting';
      board.innerHTML = '<p class="qz-wait">Counting the companies that fit…</p>';
      return;
    }
    var steps = [{ label: 'Every company we have figures for', icon: '', q: null, n: d.screened }];
    pick.forEach(function (p, i) {
      var w = wishById(p.id), L = w.levels[p.level];
      steps.push({ label: w.title, tag: w.levels.length > 1 ? L.tag : '', icon: w.icon, tint: w.tint,
                   q: buildQuery(i + 1), drop: p.id });
    });
    if (custom.length) steps.push({ label: 'Your own rules', tag: custom.length + (custom.length === 1 ? ' line' : ' lines'),
                                    icon: '✍️', q: buildQuery(), drop: '*' });
    steps[steps.length - 1].n = steps.length > 1 ? d.count : d.screened;
    steps.forEach(function (st) { if (st.q && st.n == null && counts[st.q]) st.n = counts[st.q].count; });
    var none = d.count === 0;
    board.className = 'qz-board' + (none ? ' is-none' : '');
    board.innerHTML =
      '<div class="qz-count"><b id="qz-n">' + nf(d.count) + '</b><span>' +
        (none ? 'No company fits all of that.' : (d.count === 1 ? 'company fits' : 'companies fit')) +
        '<small>' + (none ? 'Turn one choice off, or ease one, and the list comes back.'
                          : 'out of ' + nf(d.screened) + ' we have figures for') + '</small></span></div>' +
      '<ol class="qz-funnel" aria-label="How each choice narrowed the list">' + steps.map(function (st, i) {
        var known = st.n != null, pct = known && d.screened ? Math.max(st.n ? 1.5 : 0, 100 * st.n / d.screened) : 0;
        return '<li class="qz-bar' + (i === steps.length - 1 && i > 0 ? ' is-last' : '') + (i === 0 ? ' is-all' : '') +
          '"' + (st.tint ? ' style="--tint:' + st.tint + '"' : '') + '>' +
          '<span class="qz-bar-l">' + (st.icon ? '<span aria-hidden="true">' + st.icon + '</span>' : '') +
            '<b>' + esc(st.label) + '</b>' + (st.tag ? '<i>' + esc(st.tag) + '</i>' : '') + '</span>' +
          '<span class="qz-bar-track"><span class="qz-bar-fill" style="width:' + pct.toFixed(2) + '%"></span></span>' +
          '<span class="qz-bar-n">' + (known ? nf(st.n) : '…') + '</span>' +
          (st.drop ? '<button type="button" class="qz-bar-x" data-drop="' + esc(st.drop) + '" aria-label="Remove: ' +
            esc(st.label) + '">×</button>' : '<span class="qz-bar-x" aria-hidden="true"></span>') + '</li>';
      }).join('') + '</ol>' +
      (d.unknown ? '<p class="qz-unk">' + nf(d.unknown) + (d.unknown === 1 ? ' company is' : ' companies are') +
        ' left out because a figure these choices need has not been filed for ' + (d.unknown === 1 ? 'it' : 'them') + '.</p>' : '');
    tickTo($('qz-n'), d.count);
    paintFloat();

    // The bars in between are asked for one each, once, and drawn as they arrive.
    var gen = ++funnelGen;
    steps.forEach(function (st) {
      if (!st.q || st.n != null) return;
      countFor(st.q).then(function () { if (gen === funnelGen) paintBoard(); }).catch(function () {});
    });
  }

  /* On a long page the answer is below the cards. A small bar at the foot of
     the screen carries the count while the reader is still choosing, and
     takes them to the list. It goes once the list itself is in sight. */
  function paintFloat() {
    var f = $('qz-float'), res = $('qz-result');
    if (!f || !res) return;
    var d = state.data, any = pick.length || custom.length;
    var below = res.getBoundingClientRect().top > (window.innerHeight || 0) - 90;
    var view = $('view-query');
    var show = !!(mode === 'pick' && any && d && below && view && view.style.display !== 'none');
    f.hidden = !show;
    if (show) f.innerHTML = '<b>' + nf(d.count) + '</b> ' + (d.count === 1 ? 'company fits' : 'companies fit') +
      '<span aria-hidden="true">See the list ↓</span>';
  }

  function clearAll() {
    clearTimeout(runTimer);
    pick = []; custom = [];
    var t = ta();
    if (t) t.value = '';
    state.q = ''; state.data = null; state.results = []; state.err = ''; state.sort = '';
    $('qs-out').innerHTML = ''; $('qs-err').hidden = true; $('qs-copy').hidden = true;
    $('qs-saveform').hidden = true;
    writeHash('');
    remember('');
    paintFinder();
    paintBoard();
  }

  function fillHelpers() {
    var fields = meta.fields || [];
    $('qs-refn').textContent = '(' + fields.length + ')';
    $('qs-notice').textContent = meta.notice || '';

    $('qs-examples').innerHTML = (meta.examples || []).map(function (e, i) {
        return '<button type="button" class="qs-chip" data-ex="' + i + '" title="' +
          esc(e.query.replace(/\n/g, ' AND ')) + '">' + esc(e.name) + '</button>';
      }).join('');

    var groups = {}, order = [];
    fields.forEach(function (f) {
      if (!groups[f.group]) { groups[f.group] = []; order.push(f.group); }
      groups[f.group].push(f);
    });
    $('qs-bfield').innerHTML = order.map(function (g) {
      return '<optgroup label="' + esc(g) + '">' + groups[g].map(function (f) {
        return '<option value="' + esc(f.id) + '"' + (f.id === 'roce' ? ' selected' : '') +
          '>' + esc(f.label) + '</option>';
      }).join('') + '</optgroup>';
    }).join('');
    syncBuilder();

    $('qs-fields').innerHTML = order.map(function (g) {
      return '<section class="qs-fgroup"><h4>' + esc(g) + '</h4><ul>' +
        groups[g].map(function (f) {
          return '<li data-find="' + esc(norm(f.label + ' ' + f.description + ' ' +
                                               (f.aliases || []).join(' '))) + '">' +
            '<button type="button" class="qs-fbtn" data-insert="' + esc(f.label) + '">' +
            esc(f.label) + '</button> <small>' + esc(UNIT_WORD[f.unit] || '') + '</small>' +
            '<p>' + esc(f.description) +
            ((f.aliases && f.aliases.length)
              ? ' <em>Also: ' + esc(f.aliases.slice(0, 3).join(', ')) + '</em>' : '') +
            '</p></li>';
        }).join('') + '</ul></section>';
    }).join('');
  }

  function fieldById(id) {
    var fs = (meta && meta.fields) || [];
    for (var i = 0; i < fs.length; i++) if (fs[i].id === id) return fs[i];
    return null;
  }

  function syncBuilder() {
    var f = fieldById($('qs-bfield').value);
    var text = f && f.unit === 'text';
    var op = $('qs-bop');
    Array.prototype.forEach.call(op.options, function (o) {
      o.disabled = text && o.value !== '=';
    });
    if (text) op.value = '=';
    $('qs-bunit').textContent = f ? (text ? '' : '(' + (UNIT_WORD[f.unit] || '') + ')') : '';
    $('qs-bval').setAttribute('inputmode', text ? 'text' : 'decimal');
    $('qs-bval').placeholder = text ? 'e.g. Pharmaceuticals' : (f && f.unit === 'x' ? '0.5' : '15');
  }

  /* ── Editing the query ───────────────────────────────────────────────── */

  function ta() { return $('qs-q'); }

  function insertAtCursor(text) {
    var t = ta(), s = t.selectionStart, e = t.selectionEnd, v = t.value;
    var before = v.slice(0, s), after = v.slice(e);
    var pad = before && !/[\s(]$/.test(before) ? ' ' : '';
    t.value = before + pad + text + ' ' + after.replace(/^ /, '');
    var at = (before + pad + text + ' ').length;
    t.focus();
    t.setSelectionRange(at, at);
  }

  function addLine(line) {
    var t = ta(), v = t.value.replace(/\s+$/, '');
    t.value = (v ? v + '\n' : '') + line;
    t.focus();
    t.setSelectionRange(t.value.length, t.value.length);
  }

  function builderAdd() {
    var f = fieldById($('qs-bfield').value);
    var val = $('qs-bval').value.trim();
    if (!f) return;
    if (!val) { $('qs-bval').focus(); return; }
    if (f.unit === 'text') val = '"' + val.replace(/"/g, '') + '"';
    else val = val.replace(/[^0-9.,\-]/g, '') || '0';
    addLine(f.label + ' ' + $('qs-bop').value + ' ' + val);
    $('qs-bval').value = '';
  }

  /* ── Suggestions while typing ────────────────────────────────────────── */

  var STOP = /^(and|or|not|contains)$/i;

  function currentWord() {
    // The run of name words ending at the cursor: after the last operator,
    // bracket, newline or keyword.
    var t = ta(), pos = t.selectionStart, v = t.value.slice(0, pos);
    var m = v.match(/([A-Za-z][A-Za-z0-9 %'.&_]*)$/);
    if (!m) return null;
    var words = m[1].split(' '), start = pos - m[1].length;
    // Drop leading keywords so "ROE > 15 AND sal" suggests from "sal".
    while (words.length && STOP.test(words[0])) {
      start += words[0].length + 1;
      words.shift();
    }
    var w = words.join(' ').replace(/^\s+/, '');
    start = pos - w.length;
    if (!w || STOP.test(w.trim())) return null;
    return { text: w, from: start, to: pos };
  }

  function rank(text) {
    var q = norm(text), out = [];
    if (!q) return out;
    (meta.fields || []).forEach(function (f) {
      var names = [f.label].concat(f.aliases || []), best = 0;
      names.forEach(function (n) {
        var k = norm(n);
        var s = k === q ? 100 : k.indexOf(q) === 0 ? 80 - k.length / 10
          : k.indexOf(q) > 0 ? 40 - k.length / 10 : 0;
        if (s > best) best = s;
      });
      if (best > 0 && norm(f.label) !== q) out.push({ f: f, s: best });
    });
    out.sort(function (a, b) { return b.s - a.s; });
    return out.slice(0, 7).map(function (x) { return x.f; });
  }

  function closeAc() {
    ac.open = false;
    $('qs-ac').hidden = true;
    ta().removeAttribute('aria-activedescendant');
  }

  function openAc() {
    var w = currentWord();
    if (!meta || !w || w.text.length < 2) { closeAc(); return; }
    ac.items = rank(w.text);
    if (!ac.items.length) { closeAc(); return; }
    ac.from = w.from; ac.to = w.to; ac.active = 0; ac.open = true;
    paintAc();
  }

  function paintAc() {
    var ul = $('qs-ac');
    ul.innerHTML = ac.items.map(function (f, i) {
      return '<li role="option" id="qs-ac-' + i + '" data-i="' + i + '"' +
        (i === ac.active ? ' aria-selected="true" class="on"' : '') + '><b>' + esc(f.label) +
        '</b><span>' + esc(f.description) + '</span></li>';
    }).join('');
    ul.hidden = false;
    ta().setAttribute('aria-activedescendant', 'qs-ac-' + ac.active);
  }

  function pickAc(i) {
    var f = ac.items[i];
    if (!f) return;
    var t = ta(), v = t.value;
    var tail = v.slice(ac.to).replace(/^ +/, '');
    var ins = f.label + ' ';
    t.value = v.slice(0, ac.from) + ins + tail;
    var at = ac.from + ins.length;
    t.setSelectionRange(at, at);
    t.focus();
    closeAc();
  }

  /* ── Running ─────────────────────────────────────────────────────────── */

  function showError(e, q) {
    var box = $('qs-err');
    var info = (e && e.body && e.body.error) || null;
    // Kept so Ask AI can be asked why the query did not run.
    state.err = info ? info.message : ((e && e.message) || '');
    if (!info) {
      box.innerHTML = '<b>Could not run the query.</b> ' +
        esc((e && e.message) || 'The server did not answer.') + ' Try again in a moment.';
      box.hidden = false;
      return;
    }
    var html = '<b>' + esc(info.message) + '</b>';
    if (info.position != null && q) {
      var p = Math.max(0, Math.min(q.length, info.position));
      var ls = q.lastIndexOf('\n', p - 1) + 1, le = q.indexOf('\n', p);
      if (le < 0) le = q.length;
      var line = q.slice(ls, le), col = p - ls;
      html += '<pre class="qs-where">' + esc(line) + '\n' +
        esc(new Array(col + 1).join(' ')) + '^</pre>';
    }
    if (info.suggestions && info.suggestions.length) {
      html += '<div class="qs-sug">Replace with: ' + info.suggestions.map(function (s) {
        return '<button type="button" class="qs-chip" data-fix="' + esc(s) + '" data-pos="' +
          (info.position == null ? '' : info.position) + '">' + esc(s) + '</button>';
      }).join('') + '</div>';
    }
    box.innerHTML = html;
    box.hidden = false;
  }

  function applyFix(label, pos) {
    var t = ta(), v = t.value, p = parseInt(pos, 10);
    if (isNaN(p)) return;
    // The bad name runs from its position to the next operator or line end.
    var rest = v.slice(p), m = rest.match(/^[A-Za-z0-9 %'.&_]*?(?=\s*(>=|<=|!=|<>|==|[<>=+\-*\/()\n]|\s(and|or|contains)\b|$))/i);
    var len = m ? m[0].length : 0;
    t.value = v.slice(0, p) + label + v.slice(p + len);
    run(false);
  }

  function run(append) {
    var q = ta().value.trim();
    if (!q) { ta().focus(); return; }
    /* A choice made while an answer is on its way is not dropped: it runs as
       soon as that answer is in. Without this, a quick second tap on a card
       left the list showing the first tap's companies. */
    if (state.busy) { if (!append) state.again = true; return; }
    closeAc();
    if (!append) { state.q = q; state.results = []; }
    state.busy = true;
    $('qs-err').hidden = true;
    var btn = $('qs-run');
    btn.disabled = true; btn.classList.add('is-busy');
    btn.textContent = append ? 'Run query' : 'Running…';
    if (!append) {
      var out = $('qs-out');
      if (!out.firstChild) out.innerHTML = '<p class="ln-small">Screening every company…</p>';
      else out.classList.add('is-stale');
    }
    var params = 'q=' + encodeURIComponent(state.q) + '&limit=' + PAGE +
      '&offset=' + (append ? state.results.length : 0) +
      (state.sort ? '&sort=' + encodeURIComponent(state.sort) + '&order=' + state.order : '');
    if (window.AltahaTrack && !append) window.AltahaTrack('query_run', { length: q.length });
    getJSON('/fundamentals/query?' + params).then(function (d) {
      if (d && d.available === false) {
        $('qs-out').innerHTML = '<p class="ln-small">' + esc(d.message || 'Not available yet.') + '</p>';
        return;
      }
      state.data = d;
      state.err = '';
      state.sort = d.sort; state.order = d.order;
      state.results = append ? state.results.concat(d.results) : d.results;
      counts[state.q] = { count: d.count, screened: d.screened };
      writeHash(state.q);
      remember(state.q);
      /* The cards follow the query that ran, whoever wrote it: a line typed
         in the editor, a saved screen or a link lights the choices it is
         made of. Not while a newer choice is waiting, which would undo it. */
      if (!state.again && ta().value.trim() === state.q) {
        readQuery(state.q);
        paintFinder();
        if (follow) setMode(custom.length ? 'write' : 'pick');
      }
      follow = false;
      paintResults();
      paintBoard();
    }).catch(function (e) {
      if (!append) $('qs-out').innerHTML = '';
      showError(e, state.q);
      state.data = null;
      if (e && e.body && e.body.error) {
        // A rule that cannot be read is the editor's to explain; its section opens to show it.
        readQuery(state.q); paintFinder();
        follow = false;
        setMode('write');
        var board = $('qz-board');
        board.className = 'qz-board is-down';
        board.innerHTML = '<p class="qz-wait">One of the rules in <b>Make your own query</b> could not be read. It is marked there, with a fix.</p>';
        $('qz-acts').hidden = false;
      } else {
        paintBoard('down');
      }
    }).then(function () {
      state.busy = false;
      btn.disabled = false; btn.classList.remove('is-busy'); btn.textContent = 'Run query';
      $('qs-out').classList.remove('is-stale');
      if (state.again) { state.again = false; run(false); }
    });
  }

  function paintResults() {
    var d = state.data, out = $('qs-out');
    var n = function (x) { return Number(x || 0).toLocaleString('en-IN'); };
    /* How many of how many, and who was left out for want of a figure, is
       said once, in step 3 above. This heading only names the table. */
    var head = '<div class="qs-sum"><p><b>' + n(d.count) + '</b> ' +
      (d.count === 1 ? 'company matches' : 'companies match') + '</p>' +
      (d.count ? '<button type="button" class="qs-btn qs-btn-ghost qs-csv" id="qs-csv">Download CSV</button>' : '') +
      '</div>';
    $('qs-copy').hidden = false;
    if (!d.count) {
      out.innerHTML = head + '<p class="ln-small">No company meets all of that. ' +
        'Turn one choice off, or ease one, and the list comes back.</p>';
      return;
    }
    var cols = d.columns;
    var th = '<th scope="col" class="qs-co">Company</th>' + cols.map(function (c) {
      var on = c.id === state.sort;
      var arrow = on ? (state.order === 'asc' ? ' ▲' : ' ▼') : '';
      return '<th scope="col"' + (on ? ' aria-sort="' + (state.order === 'asc' ? 'ascending' : 'descending') + '"' : '') +
        '><button type="button" class="qs-sort" data-sort="' + esc(c.id) + '" title="' +
        esc(c.description) + '">' + esc(c.label) + arrow + '</button></th>';
    }).join('');
    var rows = state.results.map(function (r, i) {
      return '<tr><td class="qs-n">' + (i + 1) + '</td><th scope="row"><a href="stock.html?ticker=' +
        encodeURIComponent(r.symbol) + '"><b>' + esc(r.symbol) + '</b><span>' +
        esc(r.name || '') + '</span>' + (r.industry ? '<em>' + esc(r.industry) + '</em>' : '') +
        '</a></th>' + cols.map(function (c) {
          return '<td class="qs-num' + (c.unit === 'text' ? ' qs-txt' : '') + '">' + fmt(r[c.id], c.unit) + '</td>';
        }).join('') + '</tr>';
    }).join('');
    var more = state.results.length < d.count
      ? '<button type="button" class="qs-btn qs-btn-ghost qs-more" id="qs-more">Show ' +
        Math.min(PAGE, d.count - state.results.length) + ' more (' + n(state.results.length) +
        ' of ' + n(d.count) + ' shown)</button>' : '';
    /* The headings are the names the filings use (ROE, PE). What each one
       means is one tap away, in the words the server keeps for it. */
    var legend = '<details class="qs-legend"><summary>What do these columns mean?</summary><dl>' +
      cols.map(function (c) {
        return '<dt>' + esc(c.label) + '</dt><dd>' + esc(c.description || '') + '</dd>';
      }).join('') + '</dl></details>';
    out.innerHTML = head + '<p class="qs-tip">Tap a company to see everything about it. Tap a column to sort by it.</p>' +
      '<div class="ln-tablewrap"><table class="ln-table qs-table">' +
      '<thead><tr><th scope="col" class="qs-n">#</th>' + th + '</tr></thead><tbody>' + rows +
      '</tbody></table></div>' + more + legend +
      '<p class="ln-small">Figures are the latest filed, in ₹ crore where money; — means not ' +
      'available. ' + (d.computed_utc ? 'Computed ' +
        esc(new Date(d.computed_utc).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })) + '.' : '') + '</p>';
  }

  function sortBy(id) {
    if (state.sort === id) state.order = state.order === 'asc' ? 'desc' : 'asc';
    else { state.sort = id; state.order = 'desc'; }
    ta().value = state.q;
    run(false);
  }

  function downloadCsv() {
    var d = state.data;
    if (!d) return;
    var params = 'q=' + encodeURIComponent(state.q) + '&limit=500&offset=0' +
      '&sort=' + encodeURIComponent(state.sort) + '&order=' + state.order;
    getJSON('/fundamentals/query?' + params).then(function (all) {
      var cols = all.columns;
      var cell = function (v) {
        var s = v == null ? '' : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      var lines = [['Symbol', 'Name', 'Industry'].concat(cols.map(function (c) {
        return c.label + (c.unit === 'cr' ? ' (₹ cr)' : c.unit === 'pct' ? ' (%)' : '');
      })).map(cell).join(',')];
      all.results.forEach(function (r) {
        lines.push([r.symbol, r.name, r.industry].concat(cols.map(function (c) {
          return r[c.id];
        })).map(cell).join(','));
      });
      var blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'altaha-query.csv';
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    }).catch(function (e) { showError(e, state.q); });
  }

  /* ── Ask AI ─────────────────────────────────────────────────────────────
     A conversation with Claude beside the editor (backend/query_assistant.py).
     It is for the site owner: the panel opens only with the admin key, which
     is checked against the server, kept in sessionStorage for this tab only
     and sent as a header, never put in the address. Every query Claude
     proposes comes back already run through the screener's own parser, with
     the screener's own match count; this file shows them and puts one in the
     editor, and evaluates nothing itself. */

  var AI_KEY = 'altaha.query.aikey';
  var AI_TURNS = 16;
  var STARTERS = ['What can I screen on?', 'Explain my current query',
    'Debt-free companies growing profits fast', 'Why does my query match nothing?'];
  var ai = { open: false, unlocked: false, busy: false, gen: 0, status: null,
             history: [], log: [], mem: '' };

  function aiKey() {
    try { return sessionStorage.getItem(AI_KEY) || ai.mem; } catch (e) { return ai.mem; }
  }
  function setAiKey(k) {
    ai.mem = k || '';
    try { if (k) sessionStorage.setItem(AI_KEY, k); else sessionStorage.removeItem(AI_KEY); } catch (e) {}
  }

  function aiRequest(body) {
    var opts = { method: body ? 'POST' : 'GET',
                 headers: { Accept: 'application/json', 'X-Admin-Key': aiKey() } };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(API + '/admin/query/ai', opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var err = new Error(typeof d.detail === 'string' ? d.detail : 'HTTP ' + r.status);
          err.status = r.status;
          throw err;
        }
        return d;
      });
    });
  }

  // Claude's reply is plain text: paragraphs, "- " bullets, `code` and **bold**.
  // Everything is escaped first, so nothing it writes can become markup.
  function inline(s) {
    return esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  }
  function prose(text) {
    return String(text || '').replace(/\r/g, '').split(/\n{2,}/).map(function (block) {
      var html = '', list = [], para = [];
      var flush = function () {
        if (para.length) { html += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; }
        if (list.length) { html += '<ul>' + list.map(function (l) { return '<li>' + inline(l) + '</li>'; }).join('') + '</ul>'; list = []; }
      };
      block.split('\n').forEach(function (line) {
        var m = line.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)$/);
        if (m) { if (para.length) flush(); list.push(m[1]); }
        else if (line.trim()) { if (list.length) flush(); para.push(line); }
      });
      flush();
      return html;
    }).join('');
  }

  function aiCard(q, i, j) {
    var nf = function (x) { return Number(x || 0).toLocaleString('en-IN'); };
    var badge = !q.valid
      ? '<span class="qs-ai-n is-bad">Does not run: ' + esc(q.error || 'the screener could not read it') + '</span>'
      : q.count == null ? '<span class="qs-ai-n">Reads correctly</span>'
      : '<span class="qs-ai-n is-ok">' + nf(q.count) + (q.count === 1 ? ' company matches' : ' companies match') +
        (q.screened ? ' of ' + nf(q.screened) : '') + '</span>';
    var id = i + ':' + j;
    return '<article class="qs-ai-q"><header><b>' + esc(q.title) + '</b>' + badge + '</header>' +
      '<pre>' + esc(q.query) + '</pre>' +
      (q.explanation ? '<p>' + esc(q.explanation) + '</p>' : '') +
      (q.sample && q.sample.length ? '<p class="qs-ai-sample">First matches: ' +
        q.sample.map(esc).join(', ') + '</p>' : '') +
      '<div class="qs-ai-qbtns">' +
        (q.valid ? '<button type="button" class="qs-btn qs-btn-go qs-ai-mini" data-airun="' + id +
          '">Use and run</button>' : '') +
        '<button type="button" class="qs-btn qs-btn-ghost qs-ai-mini" data-aiuse="' + id + '">' +
          (q.valid ? 'Put in editor' : 'Put in editor to fix') + '</button>' +
      '</div></article>';
  }

  function aiEntry(m, i) {
    if (m.role === 'user') return '<div class="qs-ai-msg is-user"><p>' + esc(m.text) + '</p></div>';
    if (m.role === 'note') return '<div class="qs-ai-msg is-note" role="alert">' + esc(m.text) + '</div>';
    var cards = (m.queries || []).map(function (q, j) { return aiCard(q, i, j); }).join('');
    var next = (m.follow_ups || []).map(function (t) {
      return '<button type="button" class="qs-chip" data-aiask="' + esc(t) + '">' + esc(t) + '</button>';
    }).join('');
    return '<div class="qs-ai-msg is-ai"><span class="qs-ai-who">Claude</span>' +
      '<div class="qs-ai-text">' + prose(m.reply) + '</div>' +
      (cards ? '<div class="qs-ai-qs">' + cards + '</div>' : '') +
      (next ? '<div class="qs-ai-follow" aria-label="Ask next">' + next + '</div>' : '') + '</div>';
  }

  function paintAiLog() {
    var st = ai.status || {}, off = st.available === false, html = '';
    if (off) html += '<div class="qs-ai-msg is-note">' + esc(st.message || 'Ask AI is switched off on the server.') + '</div>';
    html += ai.log.map(aiEntry).join('');
    if (ai.busy) {
      html += '<div class="qs-ai-msg is-ai is-busy" role="status"><span class="qs-ai-dots" aria-hidden="true">' +
        '<i></i><i></i><i></i></span>Claude is writing the query and checking it against every company…</div>';
    }
    var log = $('qs-ai-log');
    log.innerHTML = html;
    log.hidden = !html;
    var starters = $('qs-ai-starters'), showStarters = !ai.log.length && !off;
    starters.hidden = !showStarters;
    starters.innerHTML = showStarters ? STARTERS.map(function (t) {
      return '<button type="button" class="qs-chip" data-aiask="' + esc(t) + '">' + esc(t) + '</button>';
    }).join('') : '';
    $('qs-ai-reset').hidden = !ai.log.length;
    $('qs-ai-in').disabled = off;
    $('qs-ai-send').disabled = off || ai.busy;
    $('qs-ai-foot').textContent = off ? '' : (st.disclaimer || '');
    // Show the top of the newest entry, which is where an answer starts.
    var last = log.lastElementChild;
    if (last && ai.log.length) log.scrollTop = Math.max(0, last.offsetTop - 4);
  }

  function aiShowKey(msg, isErr) {
    ai.unlocked = false;
    $('qs-ai-keyform').hidden = false;
    $('qs-ai-chat').hidden = true;
    $('qs-ai-lock').hidden = true;
    $('qs-ai-reset').hidden = true;
    var m = $('qs-ai-keymsg');
    m.textContent = msg || 'Ask AI is for the site owner. The key is checked on the server, ' +
      'kept in this tab only, and forgotten when the tab closes.';
    m.classList.toggle('is-err', !!isErr);
    var inp = $('qs-ai-keyin');
    inp.value = '';
    if (ai.open) inp.focus();
  }

  function aiShowChat() {
    ai.unlocked = true;
    $('qs-ai-keyform').hidden = true;
    $('qs-ai-chat').hidden = false;
    $('qs-ai-lock').hidden = false;
    paintAiLog();
  }

  function aiUnlock(key) {
    setAiKey(key);
    var go = $('qs-ai-keygo');
    go.disabled = true; go.textContent = 'Checking…';
    $('qs-ai-keymsg').textContent = 'Checking the key…';
    $('qs-ai-keymsg').classList.remove('is-err');
    return aiRequest(null).then(function (d) {
      ai.status = d;
      aiShowChat();
      if (!$('qs-ai-in').disabled) $('qs-ai-in').focus();
    }).catch(function (e) {
      if (e.status === 401) {
        setAiKey('');
        aiShowKey('That key was not accepted. It is the ADMIN_KEY set on the server.', true);
      } else {
        aiShowKey('Could not reach the server — it may be waking up. Try again in a minute.', true);
      }
    }).then(function () { go.disabled = false; go.textContent = 'Unlock'; });
  }

  function aiOpen() {
    ai.open = true;
    $('qs-ai').hidden = false;
    $('qs-aibtn').setAttribute('aria-expanded', 'true');
    if (ai.unlocked) { aiShowChat(); if (!$('qs-ai-in').disabled) $('qs-ai-in').focus(); }
    else if (aiKey()) { $('qs-ai-keyform').hidden = false; aiUnlock(aiKey()); }
    else aiShowKey('');
  }

  function aiClose() {
    ai.open = false;
    $('qs-ai').hidden = true;
    $('qs-aibtn').setAttribute('aria-expanded', 'false');
    $('qs-aibtn').focus();
  }

  function aiForget(msg) {
    ai.gen++;
    ai.busy = false; ai.status = null; ai.history = []; ai.log = [];
    setAiKey('');
    aiShowKey(msg);
  }

  // What Claude said, as it goes back to it next turn: the reply and each
  // query it proposed, so "make the second one stricter" has a referent.
  function historyText(d) {
    var t = d.reply || '';
    (d.queries || []).forEach(function (q, k) {
      t += '\n\nQuery ' + (k + 1) + ' — ' + q.title +
        (!q.valid ? ' (did not parse: ' + (q.error || '') + ')'
          : q.count != null ? ' (' + q.count + ' matched)' : '') + ':\n' + q.query;
    });
    return t;
  }

  function aiSend(text) {
    text = String(text || '').trim();
    if (!text || ai.busy) return;
    if (!ai.unlocked) { aiOpen(); return; }
    var gen = ai.gen, input = $('qs-ai-in');
    ai.busy = true;
    ai.log.push({ role: 'user', text: text });
    ai.history.push({ role: 'user', content: text });
    input.value = '';
    paintAiLog();
    if (window.AltahaTrack) window.AltahaTrack('query_ai_ask', { length: text.length });
    var failed = function (msg) {
      ai.history.pop();
      ai.log.push({ role: 'note', text: msg });
      if (!input.value) input.value = text;
    };
    aiRequest({ messages: ai.history.slice(-AI_TURNS), query: ta().value.trim(), error: state.err || '' })
      .then(function (d) {
        if (gen !== ai.gen) return;
        if (!d.available) { failed(d.message || 'Ask AI could not answer that.'); return; }
        ai.log.push({ role: 'ai', reply: d.reply, queries: d.queries || [], follow_ups: d.follow_ups || [] });
        ai.history.push({ role: 'assistant', content: historyText(d) });
      })
      .catch(function (e) {
        if (gen !== ai.gen) return;
        if (e.status === 401) { aiForget('The admin key is no longer accepted. Enter it again.'); return; }
        failed(e.status === 400 ? e.message
          : 'Could not reach the server — it may be waking up. Try again in a minute.');
      })
      .then(function () {
        if (gen !== ai.gen) return;
        ai.busy = false;
        paintAiLog();
      });
  }

  function aiUse(id, andRun) {
    var p = String(id).split(':'), m = ai.log[+p[0]];
    var q = m && m.queries && m.queries[+p[1]];
    if (!q) return;
    var t = ta();
    t.value = q.query;
    state.sort = '';
    closeAc();
    $('qs-err').hidden = true;
    t.scrollIntoView({ block: 'center' });
    t.focus({ preventScroll: true });
    if (andRun) run(false);
  }

  /* ── Wiring ──────────────────────────────────────────────────────────── */

  function wire(host) {
    var t = ta();
    // The cards are redrawn on every choice; the one just pressed keeps the keyboard.
    function refocus(sel) {
      var n = host.querySelector(sel);
      if (n) try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); }
    }
    t.addEventListener('input', openAc);
    t.addEventListener('click', closeAc);
    t.addEventListener('blur', function () { setTimeout(closeAc, 150); });
    t.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(false); return; }
      if (!ac.open) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); ac.active = (ac.active + 1) % ac.items.length; paintAc(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); ac.active = (ac.active - 1 + ac.items.length) % ac.items.length; paintAc(); }
      else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickAc(ac.active); }
      else if (e.key === 'Escape') { e.preventDefault(); closeAc(); }
    });
    $('qs-ac').addEventListener('mousedown', function (e) {
      var li = e.target.closest('li[data-i]');
      if (li) { e.preventDefault(); pickAc(+li.getAttribute('data-i')); }
    });
    $('qs-bfield').addEventListener('change', syncBuilder);
    $('qs-badd').addEventListener('click', builderAdd);
    $('qs-bval').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); builderAdd(); }
    });
    $('qs-run').addEventListener('click', function () { clearTimeout(runTimer); state.sort = ''; run(false); });
    $('qs-clear').addEventListener('click', function () { clearAll(); t.focus(); });
    $('qz-reset').addEventListener('click', function () {
      clearAll();
      var first = host.querySelector('.qz-recipe');
      if (first) first.focus();
    });
    $('qs-modes').addEventListener('click', function (e) {
      var b = e.target.closest('.qs-mode');
      if (b) setMode(b.getAttribute('data-mode'));
    });
    $('qs-modes').addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      setMode(e.key === 'Home' ? 'pick' : e.key === 'End' ? 'write' : mode === 'pick' ? 'write' : 'pick', true);
    });
    /* The cards have already written their lines into the editor, so this
       only has to show it. */
    $('qz-edit').addEventListener('click', function () {
      setMode('write');
      window.scrollTo({ top: Math.max(0, $('qs-modes').getBoundingClientRect().top + window.scrollY - 90),
                        behavior: still() ? 'auto' : 'smooth' });
      try { t.focus({ preventScroll: true }); } catch (err) { t.focus(); }
    });
    $('qz-float').addEventListener('click', function () {
      var chrome = document.querySelector('.sh-chrome');
      var y = $('qz-result').getBoundingClientRect().top + window.scrollY - ((chrome && chrome.offsetHeight) || 0) - 12;
      window.scrollTo({ top: Math.max(0, y), behavior: still() ? 'auto' : 'smooth' });
    });
    window.addEventListener('scroll', paintFloat, { passive: true });
    window.addEventListener('resize', paintFloat);
    $('qs-copy').addEventListener('click', function () {
      var b = $('qs-copy');
      var done = function () { b.textContent = 'Link copied'; setTimeout(function () { b.textContent = 'Copy link'; }, 1600); };
      try { navigator.clipboard.writeText(location.href).then(done, done); } catch (e) { done(); }
    });
    $('qs-find').addEventListener('input', function () {
      var q = norm(this.value);
      Array.prototype.forEach.call($('qs-fields').querySelectorAll('li'), function (li) {
        li.hidden = !!q && li.getAttribute('data-find').indexOf(q) < 0;
      });
      Array.prototype.forEach.call($('qs-fields').querySelectorAll('.qs-fgroup'), function (g) {
        g.hidden = !g.querySelector('li:not([hidden])');
      });
    });
    host.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      if (b.hasAttribute('data-level')) {
        setLevel(b.getAttribute('data-wish'), +b.getAttribute('data-level'));
        refocus('.qz-level[data-wish="' + b.getAttribute('data-wish') + '"][data-level="' + b.getAttribute('data-level') + '"]');
      } else if (b.hasAttribute('data-wish')) {
        toggleWish(b.getAttribute('data-wish'));
        refocus('.qz-wish-main[data-wish="' + b.getAttribute('data-wish') + '"]');
      } else if (b.hasAttribute('data-recipe')) {
        useRecipe(b.getAttribute('data-recipe'));
        refocus('.qz-recipe[data-recipe="' + b.getAttribute('data-recipe') + '"]');
      } else if (b.hasAttribute('data-drop')) {
        if (b.getAttribute('data-drop') === '*') custom = [];
        else pick = pick.filter(function (p) { return p.id !== b.getAttribute('data-drop'); });
        chosen();
      } else if (b.id === 'qz-retry') {
        state.sort = ''; run(false);
      } else if (b.hasAttribute('data-ex')) {
        var ex = meta.examples[+b.getAttribute('data-ex')];
        t.value = ex.query; state.sort = ''; run(false);
      } else if (b.hasAttribute('data-insert')) {
        insertAtCursor(b.getAttribute('data-insert'));
      } else if (b.hasAttribute('data-fix')) {
        applyFix(b.getAttribute('data-fix'), b.getAttribute('data-pos'));
      } else if (b.hasAttribute('data-sort')) {
        sortBy(b.getAttribute('data-sort'));
      } else if (b.id === 'qs-more') {
        run(true);
      } else if (b.id === 'qs-csv') {
        downloadCsv();
      } else if (b.hasAttribute('data-saved')) {
        var sc = saved[+b.getAttribute('data-saved')];
        if (sc) { t.value = sc.query; state.sort = ''; follow = true; run(false); }
      } else if (b.hasAttribute('data-delsaved')) {
        deleteSaved(+b.getAttribute('data-delsaved'));
      } else if (b.hasAttribute('data-aiask')) {
        aiSend(b.getAttribute('data-aiask'));
      } else if (b.hasAttribute('data-aiuse')) {
        aiUse(b.getAttribute('data-aiuse'), false);
      } else if (b.hasAttribute('data-airun')) {
        aiUse(b.getAttribute('data-airun'), true);
      }
    });
    $('qs-aibtn').addEventListener('click', function () { if (ai.open) aiClose(); else aiOpen(); });
    $('qs-ai-close').addEventListener('click', aiClose);
    $('qs-ai-lock').addEventListener('click', function () {
      aiForget('Locked. Enter the admin key to open Ask AI again.');
    });
    $('qs-ai-reset').addEventListener('click', function () {
      ai.gen++; ai.busy = false; ai.history = []; ai.log = [];
      paintAiLog();
      $('qs-ai-in').focus();
    });
    $('qs-ai-keyform').addEventListener('submit', function (e) {
      e.preventDefault();
      var k = $('qs-ai-keyin').value.trim();
      if (!k) { $('qs-ai-keyin').focus(); return; }
      aiUnlock(k);
    });
    $('qs-ai-form').addEventListener('submit', function (e) {
      e.preventDefault();
      aiSend($('qs-ai-in').value);
    });
    $('qs-ai-in').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); aiSend(this.value); }
    });
    function openSave(under) {
      var f = $('qs-saveform');
      if (f.parentNode !== under) under.appendChild(f);
      $('qs-savemsg').textContent = '';
      f.hidden = false;
      if (!t.value.trim()) {
        $('qs-savemsg').textContent = 'Write or pick a query first, then save it.';
        return;
      }
      $('qs-savename').focus();
    }
    $('qs-save').addEventListener('click', function () { openSave(host.querySelector('.qs-editor')); });
    $('qz-save').addEventListener('click', function () { openSave($('qz-result')); });
    $('qs-savecancel').addEventListener('click', function () { $('qs-saveform').hidden = true; });
    $('qs-saveform').addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = $('qs-savemsg');
      msg.textContent = '';
      saveScreen($('qs-savename').value, t.value.trim()).then(function () {
        msg.textContent = 'Saved.';
        $('qs-savename').value = '';
        setTimeout(function () { $('qs-saveform').hidden = true; msg.textContent = ''; }, 900);
      }).catch(function (err) { msg.textContent = err.message || 'Could not save that screen.'; });
    });
  }

  function show() {
    var host = $('query-body');
    if (!host || !onRoute()) return;
    if (!built) {
      built = true;
      skeleton(host);
      wire(host);
      loadSaved();
    }
    var fromHash = queryFromHash();
    if (meta) { start(fromHash); return; }
    if (metaPending) return;
    metaPending = getJSON('/fundamentals/query/fields').then(function (d) {
      meta = d;
      if (!d.available) {
        $('qs-out').innerHTML = '<p class="ln-small">' + esc(d.message || 'The query screener is not available yet.') + '</p>';
        return;
      }
      fillHelpers();
      start(queryFromHash());
    }).catch(function () {
      metaPending = null;
      $('qs-out').innerHTML = '<p class="ln-small">The field list could not be loaded. ' +
        'Open this tab again to retry.</p>';
    });
  }

  function start(q) {
    var t = ta();
    if (q && q !== state.q) { t.value = q; state.sort = ''; follow = true; run(false); return; }
    /* Back again with nothing asked for in the address: the list the reader
       last made is put back, cards and all, instead of an empty page. */
    if (!t.value && !state.q) {
      var last = recall();
      if (last) { t.value = last; state.sort = ''; follow = true; run(false); }
    }
    paintFloat();
  }

  window.addEventListener('altaha:navigate', function (ev) {
    if (ev && ev.detail && ev.detail.tab === 'query') setTimeout(show, 0);
  });
  window.addEventListener('hashchange', function () { if (onRoute()) setTimeout(show, 0); });

  function boot() {
    var b = $('tab-query');
    if (b) b.addEventListener('click', function () { setTimeout(show, 0); });
    var v = $('view-query');
    if (v && v.style.display !== 'none') show();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.AltahaQuery = { show: show, run: function (q) { show(); ta().value = q; follow = true; run(false); } };
})();
