/* Altaha — Watchlists

   WHAT THIS PAGE IS
   The watchlist used to be one list in a dialog: symbols and a Remove button.
   This is the page it grows into — as many named lists as somebody wants, each
   with its own emoji and colour, every name live with today's move, the week,
   a sparkline and how far it has come since it went on the list. Three ways to
   look at a list (cards, a race, a heatmap), lists everyone can see and copy,
   share links, and a daily game: pick the name you think ends the day on top.

   WHERE EACH PART LIVES
   · The MAIN list is the one the ☆ Save button on every stock writes to, and
     the one the daily email reads. It stays where it always was —
     localStorage 'altaha-watchlist-v1', synced by experience.js — so nothing
     that reads it today changes. This page edits it through
     AltahaWatchlist.reload().
   · Every OTHER list, and the main list's name, emoji and colour, are one
     document in 'altaha-watchlists-v2', copied to the account through
     /me/watchlists when the reader is signed in. Same rules as the main
     list: the browser copy is what the screen reads, the account follows,
     sign-in merges once per browser, and an edit that never reached the
     account outranks the older account copy.
   · Featured lists come from /watchlist/featured and are read-only: Follow
     copies one into your own lists.
   · A shared list arrives in the address (?wl=…) and is shown, not saved,
     until the reader chooses to keep it.
   · The game is this browser's alone ('altaha-watchgame-v1'). It is a game:
     no money, no advice, and the page says so.
*/

(function () {
  'use strict';
  if (window.AltahaWatchlists) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var MAIN_KEY = 'altaha-watchlist-v1';
  var SETS_KEY = 'altaha-watchlists-v2';
  var ACCOUNT_KEY = 'altaha-watchlists-account-v2';
  var UNSENT_KEY = 'altaha-watchlists-unsent-v2';
  var GAME_KEY = 'altaha-watchgame-v1';
  var VIEW_KEY = 'altaha-watchlists-view-v1';
  var UNI_KEY = 'altaha-universe-v2';
  var MAX_LISTS = 20, MAX_SYMBOLS = 100, MAX_NAME = 40;
  var COLORS = ['gold', 'green', 'blue', 'rose', 'violet', 'slate'];
  var EMOJI = ['⭐', '🚀', '💎', '🔥', '🌱', '🏦', '⚡', '🛢️', '💊', '🏗️', '🎯', '🧠', '🐘', '🍀', '🎲', '👀'];

  var S = {
    active: 'main', mode: 'cards', sort: 'move', q: {}, featured: [], shared: null,
    built: false, visible: false, loading: false, renaming: false, confirmDelete: null,
    uni: null, flash: {}, timer: null
  };

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function finite(v) { return v !== null && v !== '' && v !== undefined && isFinite(v); }
  function inr(v, d) {
    if (!finite(v)) return '—';
    d = d == null ? 2 : d;
    return '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pct(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2) + '%';
  }
  function tone(v) { return !finite(v) ? '' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'dn' : 'flat'; }
  function readJSON(k, fb) { try { var v = JSON.parse(localStorage.getItem(k)); return v == null ? fb : v; } catch (e) { return fb; } }
  function writeJSON(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } }
  function local(k) { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }
  function setLocal(k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (e) {} }
  function istNow() { return new Date(Date.now() + 330 * 60000); }
  function istDate() { return istNow().toISOString().slice(0, 10); }
  function istMinutes() { var n = istNow(); return n.getUTCHours() * 60 + n.getUTCMinutes(); }
  function istWeekday() { return istNow().getUTCDay(); }
  function niceDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso + 'T00:00:00Z').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
    } catch (e) { return iso; }
  }
  function still() {
    try {
      return document.documentElement.dataset.motion === 'off' ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) { return false; }
  }
  function norm(s) { return String(s || '').trim().toUpperCase().replace(/\.NS$|\.BO$/, ''); }
  function validSym(s) { return /^[A-Z0-9&.\-]{1,20}$/.test(s); }
  function cleanName(s, fb) {
    s = String(s || '').replace(/[\u0000-\u001f\u007f]/g, '').replace(/\s+/g, ' ').trim().slice(0, MAX_NAME);
    return s || fb;
  }
  function uid() { return 'l' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function auth() { return (window.AltahaAuth && window.AltahaAuth.authed()) ? window.AltahaAuth : null; }
  function who() { var a = auth(), u = a && a.user(); return (u && u.email) || ''; }

  var toastTimer = null;
  function toast(text) {
    var t = $('wl-toast');
    if (!t) return;
    t.textContent = text;
    t.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('on'); }, 2800);
  }

  /* ── The lists ───────────────────────────────────────────────────────── */

  function mainSymbols() {
    if (window.AltahaWatchlist && window.AltahaWatchlist.symbols) return window.AltahaWatchlist.symbols();
    var rows = readJSON(MAIN_KEY, []);
    return Array.isArray(rows) ? rows.filter(function (x) { return typeof x === 'string'; }).map(norm) : [];
  }

  function writeMain(symbols) {
    if (!writeJSON(MAIN_KEY, symbols)) { toast('Could not save. Browser storage may be full.'); return false; }
    if (window.AltahaWatchlist && window.AltahaWatchlist.reload) window.AltahaWatchlist.reload();
    return true;
  }

  function blankDoc() {
    return { main: { name: 'My watchlist', emoji: '⭐', color: 'gold', added: {} }, lists: [] };
  }

  function readDoc() {
    var d = readJSON(SETS_KEY, null);
    if (!d || typeof d !== 'object') d = blankDoc();
    if (!d.main || typeof d.main !== 'object') d.main = blankDoc().main;
    if (!d.main.added || typeof d.main.added !== 'object') d.main.added = {};
    if (!Array.isArray(d.lists)) d.lists = [];
    d.lists = d.lists.filter(function (l) { return l && typeof l === 'object' && l.id; }).slice(0, MAX_LISTS);
    d.lists.forEach(function (l) {
      l.symbols = Array.isArray(l.symbols) ? l.symbols.map(norm).filter(validSym).slice(0, MAX_SYMBOLS) : [];
      if (!l.added || typeof l.added !== 'object') l.added = {};
      if (COLORS.indexOf(l.color) < 0) l.color = 'gold';
    });
    return d;
  }

  var DOC = readDoc();

  function saveDoc(opts) {
    writeJSON(SETS_KEY, DOC);
    if (!(opts && opts.quiet)) pushDoc();
  }

  function myLists() {
    var m = DOC.main;
    return [{ id: 'main', name: m.name || 'My watchlist', emoji: m.emoji || '⭐', color: m.color || 'gold',
              symbols: mainSymbols(), added: m.added, main: true }].concat(DOC.lists);
  }

  function listById(id) {
    if (id === 'shared') return S.shared;
    var mine = myLists().filter(function (l) { return l.id === id; })[0];
    if (mine) return mine;
    return S.featured.filter(function (l) { return l.id === id; })[0] || null;
  }

  function isMine(l) { return l && !l.featured && !l.isShared; }

  function setSymbols(l, symbols) {
    if (l.main) return writeMain(symbols);
    l.symbols = symbols;
    saveDoc();
    return true;
  }

  function addedMeta(l) { return l.main ? DOC.main.added : l.added; }

  function addSymbol(l, sym) {
    sym = norm(sym);
    if (!validSym(sym)) { toast('That does not look like an NSE symbol.'); return false; }
    var cur = (l.main ? mainSymbols() : l.symbols).slice();
    if (cur.indexOf(sym) >= 0) { toast(sym + ' is already on ' + l.name + '.'); return false; }
    if (cur.length >= MAX_SYMBOLS) { toast('A list holds ' + MAX_SYMBOLS + ' stocks. Remove one to add another.'); return false; }
    var q = S.q[sym];
    addedMeta(l)[sym] = { at: istDate(), px: q && finite(q.ltp) ? Number(q.ltp) : null };
    if (l.main) saveDoc();
    if (!setSymbols(l, cur.concat(sym))) return false;
    if (window.AltahaTrack) window.AltahaTrack('watchlist_changed', { ticker: sym, action: 'added', list: l.main ? 'main' : 'named' });
    toast('Added ' + sym + ' to ' + l.name + '.');
    loadQuotes([sym]);
    return true;
  }

  function removeSymbol(l, sym) {
    var cur = (l.main ? mainSymbols() : l.symbols).filter(function (x) { return x !== sym; });
    delete addedMeta(l)[sym];
    if (l.main) saveDoc();
    setSymbols(l, cur);
    toast('Removed ' + sym + ' from ' + l.name + '.');
  }

  function newList(name, symbols, emoji, color) {
    if (DOC.lists.length >= MAX_LISTS) { toast('You have ' + (MAX_LISTS + 1) + ' lists. Delete one to make another.'); return null; }
    var l = { id: uid(), name: cleanName(name, 'New list'), emoji: emoji || EMOJI[(DOC.lists.length + 1) % EMOJI.length],
              color: color || COLORS[(DOC.lists.length + 1) % COLORS.length],
              symbols: (symbols || []).map(norm).filter(validSym).slice(0, MAX_SYMBOLS),
              added: {}, created: istDate() };
    l.symbols.forEach(function (s) {
      var q = S.q[s];
      l.added[s] = { at: istDate(), px: q && finite(q.ltp) ? Number(q.ltp) : null };
    });
    DOC.lists.push(l);
    saveDoc();
    return l;
  }

  function deleteList(id) {
    DOC.lists = DOC.lists.filter(function (l) { return l.id !== id; });
    if (S.active === id) S.active = 'main';
    saveDoc();
  }

  /* Prices recorded at the moment a stock went on a list are filled in once
     the first quote for it arrives, but only on the day it was added: a price
     from next week would make "since added" a lie. */
  function backfillAdded() {
    var today = istDate(), dirty = false;
    myLists().forEach(function (l) {
      var meta = addedMeta(l);
      Object.keys(meta).forEach(function (s) {
        var m = meta[s], q = S.q[s];
        if (m && m.px == null && m.at === today && q && finite(q.ltp)) { m.px = Number(q.ltp); dirty = true; }
      });
    });
    if (dirty) saveDoc();
  }

  /* ── The account copy ────────────────────────────────────────────────── */

  var pushing = Promise.resolve();

  function wire() {
    return { main: { name: DOC.main.name, emoji: DOC.main.emoji, color: DOC.main.color, added: DOC.main.added },
             lists: DOC.lists };
  }

  function pushDoc() {
    var a = auth();
    if (!a) return;
    var body = JSON.stringify(wire()), me = who();
    pushing = pushing.then(function () {
      return a.fetch('/me/watchlists', { method: 'PUT', body: body }).then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        setLocal(UNSENT_KEY, '');
      });
    }).catch(function () {
      setLocal(UNSENT_KEY, me);
    });
  }

  function mergeInto(server) {
    var byId = {};
    DOC.lists.forEach(function (l) { byId[l.id] = l; });
    (server.lists || []).forEach(function (l) {
      var mine = byId[l.id];
      if (!mine) { if (DOC.lists.length < MAX_LISTS) DOC.lists.push(l); return; }
      l.symbols.forEach(function (s) { if (mine.symbols.indexOf(s) < 0 && mine.symbols.length < MAX_SYMBOLS) mine.symbols.push(s); });
      Object.keys(l.added || {}).forEach(function (s) { if (!mine.added[s]) mine.added[s] = l.added[s]; });
    });
    if (server.main) {
      if (DOC.main.name === 'My watchlist' && server.main.name) DOC.main.name = server.main.name;
      if (server.main.emoji && DOC.main.emoji === '⭐') DOC.main.emoji = server.main.emoji;
      Object.keys(server.main.added || {}).forEach(function (s) { if (!DOC.main.added[s]) DOC.main.added[s] = server.main.added[s]; });
    }
  }

  function adopt(server) {
    DOC.main = Object.assign(blankDoc().main, server.main || {});
    if (!DOC.main.added) DOC.main.added = {};
    DOC.lists = server.lists || [];
    saveDoc({ quiet: true });
    DOC = readDoc();
  }

  function pullDoc() {
    var a = auth(), me = who();
    if (!a || !me) return;
    if (local(ACCOUNT_KEY) !== me) {
      a.fetch('/me/watchlists').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d) return;
        mergeInto(d);
        setLocal(ACCOUNT_KEY, me);
        saveDoc();
        render();
      }).catch(function () {});
      return;
    }
    if (local(UNSENT_KEY) === me) { pushDoc(); return; }
    a.fetch('/me/watchlists').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (d && d.updated_at) { adopt(d); render(); }
    }).catch(function () {});
  }

  /* ── Data from the API ───────────────────────────────────────────────── */

  function get(path, ms) {
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, ms || 30000);
    return fetch(API + path, ctl ? { signal: ctl.signal } : {}).then(function (r) {
      if (timer) clearTimeout(timer);
      return r.ok ? r.json() : null;
    }).catch(function () { if (timer) clearTimeout(timer); return null; });
  }

  var inflight = {};
  function loadQuotes(symbols, tries) {
    symbols = (symbols || []).filter(function (s) { return validSym(s) && !inflight[s]; });
    if (!symbols.length) return Promise.resolve();
    var chunks = [];
    for (var i = 0; i < symbols.length; i += MAX_SYMBOLS) chunks.push(symbols.slice(i, i + MAX_SYMBOLS));
    return Promise.all(chunks.map(function (chunk) {
      chunk.forEach(function (s) { inflight[s] = 1; });
      return get('/watchlist/quotes?symbols=' + encodeURIComponent(chunk.join(',')), 45000).then(function (d) {
        chunk.forEach(function (s) { delete inflight[s]; });
        if (!d) return;
        (d.rows || []).forEach(function (r) {
          var prev = S.q[r.symbol];
          if (prev && finite(prev.ltp) && finite(r.ltp) && prev.ltp !== r.ltp) S.flash[r.symbol] = r.ltp > prev.ltp ? 'up' : 'dn';
          S.q[r.symbol] = r;
        });
        S.marketOpen = !!d.market_open;
        S.note = d.note;
        if ((d.pending || []).length && (tries || 0) < 6) {
          setTimeout(function () { loadQuotes(d.pending, (tries || 0) + 1); }, 1500);
        }
      });
    })).then(function () {
      backfillAdded();
      resolveGame();
      paintStage();
      paintShelf();
      S.flash = {};
    });
  }

  function refreshQuotes() {
    var l = listById(S.active), set = {};
    myLists().forEach(function (x) { x.symbols.forEach(function (s) { set[s] = 1; }); });
    if (l) l.symbols.forEach(function (s) { set[s] = 1; });
    // Already-quoted names are asked for again so the prices move; the server
    // answers them from its cache.
    Object.keys(set).forEach(function (s) { delete inflight[s]; });
    return loadQuotes(Object.keys(set));
  }

  function loadFeatured() {
    return get('/watchlist/featured', 20000).then(function (d) {
      S.featured = ((d && d.lists) || []).map(function (l) { l.featured = true; l.added = {}; return l; });
      paintShelf();
      if (listById(S.active) && listById(S.active).featured) paintStage();
    });
  }

  function universe() {
    if (S.uni) return Promise.resolve(S.uni);
    var cached = readJSON(UNI_KEY, null);
    if (cached && Array.isArray(cached.rows) && cached.rows.length) {
      S.uni = cached.rows;
      return Promise.resolve(S.uni);
    }
    return get('/universe', 15000).then(function (d) {
      S.uni = (d && d.rows) || [];
      if (S.uni.length) writeJSON(UNI_KEY, { day: istDate(), rows: S.uni });
      return S.uni;
    });
  }

  /* ── Sharing ─────────────────────────────────────────────────────────── */

  function b64url(text) {
    var bytes = new TextEncoder().encode(text), bin = '';
    bytes.forEach(function (b) { bin += String.fromCharCode(b); });
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function unb64url(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }

  function shareUrl(l) {
    var payload = b64url(JSON.stringify({ n: l.name, e: l.emoji, c: l.color, s: l.symbols.slice(0, MAX_SYMBOLS) }));
    var base = location.origin && location.origin !== 'null' ? location.origin + location.pathname : 'https://altahascreener.in/index.html';
    return base + '?go=watchlists&wl=' + payload;
  }

  function readShared() {
    var raw = null;
    try { raw = new URLSearchParams(location.search).get('wl'); } catch (e) {}
    if (!raw) return null;
    try {
      var d = JSON.parse(unb64url(raw));
      var syms = (Array.isArray(d.s) ? d.s : []).map(norm).filter(validSym).slice(0, MAX_SYMBOLS);
      if (!syms.length) return null;
      return { id: 'shared', isShared: true, name: cleanName(d.n, 'Shared list'),
               emoji: String(d.e || '🔗').slice(0, 8), color: COLORS.indexOf(d.c) >= 0 ? d.c : 'gold',
               symbols: syms, added: {} };
    } catch (e) { return null; }
  }

  function share(l) {
    var url = shareUrl(l);
    var text = l.emoji + ' ' + l.name + ' — my watchlist on Altaha Screener';
    if (navigator.share && window.matchMedia('(hover: none)').matches) {
      navigator.share({ title: l.name, text: text, url: url }).catch(function () {});
      return;
    }
    var done = function () { toast('Link copied. Anyone who opens it sees ' + l.name + ' live and can keep a copy.'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, function () { window.prompt('Copy this link', url); });
    } else {
      window.prompt('Copy this link', url);
    }
  }

  /* ── The game: pick today's winner ───────────────────────────────────── */

  function game() {
    var g = readJSON(GAME_KEY, null);
    if (!g || typeof g !== 'object') g = {};
    g.picks = g.picks && typeof g.picks === 'object' ? g.picks : {};
    ['points', 'streak', 'best', 'played', 'wins'].forEach(function (k) { g[k] = Number(g[k]) || 0; });
    return g;
  }
  function saveGame(g) { writeJSON(GAME_KEY, g); }

  function pickOpen() {
    var wd = istWeekday();
    return wd >= 1 && wd <= 5 && istMinutes() < 930;
  }

  function pick(l, sym) {
    if (!pickOpen()) { toast('Picks open on weekdays until 3:30 pm IST. Come back for the next session.'); return; }
    var g = game(), day = istDate();
    var field = l.symbols.slice(0, 40);
    if (field.length < 3) { toast('Pick from a list with at least three stocks, so there is a race to win.'); return; }
    g.picks[day] = { sym: sym, list: l.name, field: field, at: new Date().toISOString() };
    saveGame(g);
    toast('Your pick for today: ' + sym + '. Results after the close.');
    if (window.AltahaTrack) window.AltahaTrack('watchlist_game_pick', { size: field.length });
    paintStage();
  }

  // The move on one session, read from the closes the quote carries.
  function moveOn(q, day) {
    if (!q || !Array.isArray(q.spark_dates)) return { known: false };
    var i = q.spark_dates.indexOf(day);
    if (i > 0) return { known: true, pct: 100 * (q.spark[i] / q.spark[i - 1] - 1) };
    if (q.last_date && q.last_date > day) return { known: true, none: true };
    return { known: false };
  }

  function resolveGame() {
    var g = game(), today = istDate(), changed = false, need = [];
    Object.keys(g.picks).sort().forEach(function (day) {
      var p = g.picks[day];
      if (!p || p.result) return;
      if (day === today && istMinutes() < 940) return;          // ten minutes after the close
      var me = moveOn(S.q[p.sym], day);
      if (!me.known) { need = need.concat(p.field); return; }
      if (me.none) { p.result = { kind: 'void' }; changed = true; return; }
      var moves = [];
      p.field.forEach(function (s) {
        var m = moveOn(S.q[s], day);
        if (m.known && !m.none) moves.push({ s: s, pct: m.pct });
      });
      if (moves.length < Math.min(3, p.field.length)) { need = need.concat(p.field); return; }
      moves.sort(function (a, b) { return b.pct - a.pct; });
      var rank = moves.findIndex(function (m) { return m.s === p.sym; }) + 1;
      var avg = moves.reduce(function (t, m) { return t + m.pct; }, 0) / moves.length;
      var pts = rank === 1 ? 3 : me.pct > avg ? 1 : 0;
      p.result = { kind: rank === 1 ? 'win' : pts ? 'beat' : 'miss', rank: rank, of: moves.length,
                   pct: Math.round(me.pct * 100) / 100, top: moves[0].s, topPct: Math.round(moves[0].pct * 100) / 100,
                   points: pts };
      g.points += pts; g.played += 1;
      if (rank === 1) g.wins += 1;
      g.streak = pts ? g.streak + 1 : 0;
      g.best = Math.max(g.best, g.streak);
      changed = true;
    });
    if (changed) saveGame(g);
    if (need.length) {
      var missing = need.filter(function (s, i) { return need.indexOf(s) === i && !S.q[s]; });
      if (missing.length) loadQuotes(missing);
    }
  }

  function confetti() {
    if (still()) return;
    var host = document.createElement('div');
    host.className = 'wl-confetti';
    host.setAttribute('aria-hidden', 'true');
    var colors = ['#D9BC6A', '#3FBF87', '#5B9BD5', '#E0614F', '#9A7FD1', '#F2C14E'];
    for (var i = 0; i < 70; i++) {
      var b = document.createElement('i');
      b.style.left = (Math.random() * 100) + '%';
      b.style.background = colors[i % colors.length];
      b.style.animationDelay = (Math.random() * 0.4) + 's';
      b.style.setProperty('--dx', ((Math.random() - 0.5) * 240) + 'px');
      b.style.setProperty('--r', (Math.random() * 720 - 360) + 'deg');
      host.appendChild(b);
    }
    document.body.appendChild(host);
    setTimeout(function () { host.remove(); }, 2600);
  }

  /* ── Rendering ───────────────────────────────────────────────────────── */

  function mood(l) {
    var up = 0, dn = 0, sum = 0, n = 0;
    l.symbols.forEach(function (s) {
      var q = S.q[s];
      if (!q || !finite(q.change_pct)) return;
      n++; sum += q.change_pct;
      if (q.change_pct > 0) up++; else if (q.change_pct < 0) dn++;
    });
    var avg = n ? sum / n : null;
    var face = avg == null ? '🫥' : avg > 1.5 ? '🤩' : avg > 0.3 ? '😊' : avg >= -0.3 ? '😐' : avg >= -1.5 ? '😟' : '😱';
    var word = avg == null ? 'Waiting for prices' : avg > 1.5 ? 'Flying' : avg > 0.3 ? 'Cheerful' : avg >= -0.3 ? 'Calm' : avg >= -1.5 ? 'Uneasy' : 'Rough day';
    return { up: up, dn: dn, flat: n - up - dn, n: n, avg: avg, face: face, word: word };
  }

  function spark(q, w, h) {
    var v = (q && q.spark) || [];
    if (v.length < 2) return '<svg class="wl-spark" viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true"></svg>';
    var mn = Math.min.apply(null, v), mx = Math.max.apply(null, v), rg = (mx - mn) || 1;
    var pts = v.map(function (x, i) {
      return (i / (v.length - 1) * w).toFixed(1) + ',' + (2 + (1 - (x - mn) / rg) * (h - 4)).toFixed(1);
    });
    var t = v[v.length - 1] >= v[0] ? 'up' : 'dn';
    return '<svg class="wl-spark ' + t + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<polyline class="wl-spark-area" points="0,' + h + ' ' + pts.join(' ') + ' ' + w + ',' + h + '"/>' +
      '<polyline class="wl-spark-line" pathLength="1" points="' + pts.join(' ') + '"/></svg>';
  }

  function since(l, s) {
    var m = addedMeta(l) && addedMeta(l)[s], q = S.q[s];
    if (!m || !finite(m.px) || !q || !finite(q.ltp)) return null;
    return { pct: 100 * (q.ltp / m.px - 1), at: m.at, px: m.px };
  }

  function sorted(l) {
    var rows = l.symbols.map(function (s, i) { return { s: s, i: i, q: S.q[s] || null, since: since(l, s) }; });
    var by = {
      move: function (a, b) { return (finite(b.q && b.q.change_pct) ? b.q.change_pct : -1e9) - (finite(a.q && a.q.change_pct) ? a.q.change_pct : -1e9); },
      since: function (a, b) { return (b.since ? b.since.pct : -1e9) - (a.since ? a.since.pct : -1e9); },
      score: function (a, b) { return (finite(b.q && b.q.score) ? b.q.score : -1) - (finite(a.q && a.q.score) ? a.q.score : -1); },
      az: function (a, b) { return a.s < b.s ? -1 : 1; },
      mine: function (a, b) { return a.i - b.i; }
    }[S.sort] || function (a, b) { return a.i - b.i; };
    return rows.sort(by);
  }

  function shelfCard(l, k) {
    var m = mood(l), on = l.id === S.active;
    var bar = m.n ? '<span class="wl-moodbar" aria-hidden="true"><i class="up" style="flex:' + m.up + '"></i><i class="flat" style="flex:' + m.flat + '"></i><i class="dn" style="flex:' + m.dn + '"></i></span>'
      : '<span class="wl-moodbar" aria-hidden="true"><i class="flat" style="flex:1"></i></span>';
    return '<button type="button" class="wl-tile c-' + esc(l.color) + (on ? ' on' : '') + (l.featured ? ' feat' : '') +
      '" data-list="' + esc(l.id) + '" aria-pressed="' + (on ? 'true' : 'false') + '" style="--i:' + k + '">' +
      '<span class="wl-tile-e" aria-hidden="true">' + esc(l.emoji || '⭐') + '</span>' +
      '<span class="wl-tile-t"><b>' + esc(l.name) + '</b><small>' + (l.featured ? 'Featured · ' : l.isShared ? 'Shared · ' : '') +
      l.symbols.length + (l.symbols.length === 1 ? ' stock' : ' stocks') +
      (m.avg != null ? ' · <span class="' + tone(m.avg) + '">' + pct(m.avg) + '</span>' : '') + '</small></span>' +
      bar + '</button>';
  }

  function paintShelf() {
    var host = $('wl-shelf');
    if (!host) return;
    var mine = myLists(), k = 0;
    var html = '<div class="wl-shelf-row" role="group" aria-label="Your lists">' +
      (S.shared ? shelfCard(S.shared, k++) : '') +
      mine.map(function (l) { return shelfCard(l, k++); }).join('') +
      '<button type="button" class="wl-tile wl-new" id="wl-new" style="--i:' + (k++) + '"><span class="wl-tile-e" aria-hidden="true">＋</span>' +
      '<span class="wl-tile-t"><b>New list</b><small>name it anything</small></span></button></div>';
    if (S.featured.length) {
      html += '<p class="wl-shelf-h">Featured lists — open one, race it, or keep a copy</p><div class="wl-shelf-row" role="group" aria-label="Featured lists">' +
        S.featured.map(function (l) { return shelfCard(l, k++); }).join('') + '</div>';
    }
    host.innerHTML = html;
  }

  function hero(l) {
    var m = mood(l), mine = isMine(l);
    var name = S.renaming && mine
      ? '<input id="wl-name-in" class="wl-name-in" maxlength="' + MAX_NAME + '" value="' + esc(l.name) + '" aria-label="List name">'
      : '<h3 class="wl-name">' + esc(l.name) + '</h3>';
    var acts = mine
      ? '<button type="button" class="wl-act" data-act="rename">Rename</button>' +
        '<button type="button" class="wl-act" data-act="style" aria-expanded="false">Emoji &amp; colour</button>' +
        '<button type="button" class="wl-act" data-act="share">Share</button>' +
        '<button type="button" class="wl-act" data-act="copy">Duplicate</button>' +
        (l.main ? '' : '<button type="button" class="wl-act danger' + (S.confirmDelete === l.id ? ' armed' : '') + '" data-act="delete">' +
          (S.confirmDelete === l.id ? 'Tap again to delete' : 'Delete') + '</button>')
      : '<button type="button" class="wl-act primary" data-act="follow">Keep a copy</button>' +
        '<button type="button" class="wl-act" data-act="share">Share</button>';
    var gauge = m.n ? Math.max(4, Math.min(96, 50 + (m.avg || 0) * 14)) : 50;
    return '<div class="wl-hero c-' + esc(l.color) + '">' +
      '<span class="wl-hero-glow" aria-hidden="true"></span>' +
      '<div class="wl-hero-l">' +
        '<span class="wl-hero-e" aria-hidden="true">' + esc(l.emoji || '⭐') + '</span>' +
        '<div class="wl-hero-t">' + name +
          '<p class="wl-hero-sub">' + (l.featured ? esc(l.blurb || 'A list everyone can see.') : l.isShared ? 'Shared with you. It is not saved until you keep a copy.' :
            l.main ? 'The list the ☆ Save button on every stock adds to, and the one your daily email reads.' :
            'Made ' + esc(niceDate(l.created)) + '.') + '</p>' +
          '<div class="wl-acts">' + acts + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="wl-mood" aria-label="List mood: ' + esc(m.word) + '">' +
        '<span class="wl-mood-face" aria-hidden="true">' + m.face + '</span>' +
        '<b>' + esc(m.word) + '</b>' +
        '<span class="wl-gauge" aria-hidden="true"><i style="left:' + gauge.toFixed(1) + '%"></i></span>' +
        '<small>' + (m.n ? '<span class="up">' + m.up + ' up</span> · <span class="dn">' + m.dn + ' down</span> · avg ' + pct(m.avg) : 'Prices are on their way') + '</small>' +
      '</div>' +
      '<div class="wl-style" id="wl-style" hidden>' +
        '<div class="wl-emojis" role="group" aria-label="Emoji">' + EMOJI.map(function (e) {
          return '<button type="button" data-emoji="' + esc(e) + '"' + (e === l.emoji ? ' class="on"' : '') + '>' + e + '</button>';
        }).join('') + '</div>' +
        '<div class="wl-colors" role="group" aria-label="Colour">' + COLORS.map(function (c) {
          return '<button type="button" class="c-' + c + (c === l.color ? ' on' : '') + '" data-color="' + c + '" aria-label="' + c + '"></button>';
        }).join('') + '</div>' +
      '</div>' +
    '</div>';
  }

  function toolbar(l) {
    var mine = isMine(l);
    function seg(id, cur, opts) {
      return '<div class="wl-seg" id="' + id + '" role="group" aria-label="View">' + opts.map(function (o) {
        return '<button type="button" data-v="' + o[0] + '"' + (o[0] === cur ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + '>' + o[1] + '</button>';
      }).join('') + '</div>';
    }
    return '<div class="wl-tools">' +
      (mine ? '<div class="wl-add"><label class="wl-sr" for="wl-add-in">Add a stock</label>' +
        '<input id="wl-add-in" type="search" placeholder="Add a stock — name or symbol" autocomplete="off" spellcheck="false" ' +
        'role="combobox" aria-expanded="false" aria-controls="wl-sugg" aria-autocomplete="list">' +
        '<ul class="wl-sugg" id="wl-sugg" role="listbox" hidden></ul></div>' : '') +
      seg('wl-mode', S.mode, [['cards', 'Cards'], ['race', 'Race'], ['heat', 'Heatmap']]) +
      '<label class="wl-sortl"><span>Sort</span><select id="wl-sort">' +
        [['move', 'Today’s move'], ['since', 'Since added'], ['score', 'Altaha Score'], ['az', 'A–Z'], ['mine', 'List order']].map(function (o) {
          return '<option value="' + o[0] + '"' + (o[0] === S.sort ? ' selected' : '') + '>' + o[1] + '</option>';
        }).join('') + '</select></label>' +
    '</div>';
  }

  function copyMenu(l, s) {
    var targets = myLists().filter(function (x) { return x.id !== l.id && x.symbols.indexOf(s) < 0; });
    if (!targets.length) return '';
    return '<label class="wl-copy" title="Copy to another list"><span class="wl-sr">Copy ' + esc(s) + ' to</span>' +
      '<select data-copy="' + esc(s) + '"><option value="">Copy to…</option>' + targets.map(function (x) {
        return '<option value="' + esc(x.id) + '">' + esc((x.emoji || '') + ' ' + x.name) + '</option>';
      }).join('') + '</select></label>';
  }

  function cards(l, rows, today) {
    return '<div class="wl-grid">' + rows.map(function (r, k) {
      var q = r.q || {}, s = r.s, picked = today && today.sym === s;
      var fl = S.flash[s] ? ' flash-' + S.flash[s] : '';
      return '<article class="wl-card ' + tone(q.change_pct) + (picked ? ' picked' : '') + fl + '" style="--i:' + Math.min(k, 16) + '" data-sym="' + esc(s) + '">' +
        '<div class="wl-card-top">' +
          '<a class="wl-card-sym" href="stock.html?ticker=' + encodeURIComponent(s) + '">' + esc(s) + '</a>' +
          (finite(q.score) ? '<span class="wl-score" title="Altaha Score">' + Math.round(q.score) + '</span>' : '') +
          '<span class="wl-card-pill ' + tone(q.change_pct) + '">' + pct(q.change_pct) + '</span>' +
        '</div>' +
        '<p class="wl-card-name">' + esc(q.name || ' ') + '</p>' +
        '<div class="wl-card-px"><b>' + inr(q.ltp) + '</b>' + spark(q, 120, 36) + '</div>' +
        '<div class="wl-card-stats">' +
          '<span><small>Week</small><b class="' + tone(q.week_pct) + '">' + pct(q.week_pct) + '</b></span>' +
          '<span><small>Month</small><b class="' + tone(q.month_pct) + '">' + pct(q.month_pct) + '</b></span>' +
          '<span><small>Since added</small><b class="' + (r.since ? tone(r.since.pct) : '') + '">' + (r.since ? pct(r.since.pct) : '—') + '</b></span>' +
        '</div>' +
        (r.since ? '<p class="wl-card-since">On this list since ' + esc(niceDate(r.since.at)) + ' at ' + inr(r.since.px) + '</p>' : '') +
        '<div class="wl-card-acts">' +
          (pickOpen() && !today ? '<button type="button" class="wl-pick" data-pick="' + esc(s) + '" title="Pick as today’s winner">⚑ Pick</button>' : '') +
          (picked ? '<span class="wl-picked">⚑ Your pick today</span>' : '') +
          (isMine(l) ? copyMenu(l, s) + '<button type="button" class="wl-x" data-remove="' + esc(s) + '" aria-label="Remove ' + esc(s) + ' from ' + esc(l.name) + '">×</button>' : '') +
        '</div>' +
      '</article>';
    }).join('') + '</div>';
  }

  function race(l, rows) {
    var priced = rows.filter(function (r) { return r.q && finite(r.q.change_pct); })
      .sort(function (a, b) { return b.q.change_pct - a.q.change_pct; });
    if (!priced.length) return '<p class="wl-empty">The race starts when the prices arrive.</p>';
    var top = Math.max.apply(null, priced.map(function (r) { return Math.abs(r.q.change_pct); }).concat([0.5]));
    var lead = priced[0];
    return '<div class="wl-race" style="--rows:' + priced.length + '">' +
      '<p class="wl-race-cap">' + (S.marketOpen ? 'Live race · ' : 'Final standings · ') + 'leader <b>' + esc(lead.s) + '</b> ' +
        '<span class="' + tone(lead.q.change_pct) + '">' + pct(lead.q.change_pct) + '</span></p>' +
      '<div class="wl-race-track">' + priced.map(function (r, k) {
        var w = Math.abs(r.q.change_pct) / top * 50;
        var pos = r.q.change_pct >= 0;
        return '<div class="wl-lane" style="--k:' + k + '" data-sym="' + esc(r.s) + '">' +
          '<span class="wl-lane-n">' + (k === 0 ? '👑' : (k + 1)) + '</span>' +
          '<a class="wl-lane-s" href="stock.html?ticker=' + encodeURIComponent(r.s) + '">' + esc(r.s) + '</a>' +
          '<span class="wl-lane-bar"><i class="' + (pos ? 'up' : 'dn') + '" style="' + (pos ? 'left:50%' : 'right:50%') + ';width:' + w.toFixed(2) + '%"></i></span>' +
          '<span class="wl-lane-v ' + tone(r.q.change_pct) + '">' + pct(r.q.change_pct) + '</span></div>';
      }).join('') + '</div></div>';
  }

  function heat(l, rows) {
    var priced = rows.filter(function (r) { return r.q && finite(r.q.change_pct); });
    if (!priced.length) return '<p class="wl-empty">The heatmap fills in when the prices arrive.</p>';
    var order = priced.slice().sort(function (a, b) { return Math.abs(b.q.change_pct) - Math.abs(a.q.change_pct); });
    var big = {};
    order.slice(0, Math.min(3, Math.floor(priced.length / 4))).forEach(function (r) { big[r.s] = 1; });
    return '<div class="wl-heat">' + priced.map(function (r, k) {
      var c = r.q.change_pct, a = Math.min(1, Math.abs(c) / 3);
      var L = Math.round(90 - a * 52);
      var bg = c >= 0 ? 'hsl(150,42%,' + L + '%)' : 'hsl(8,62%,' + L + '%)';
      return '<a class="wl-hcell' + (big[r.s] ? ' big' : '') + '" href="stock.html?ticker=' + encodeURIComponent(r.s) + '" style="--i:' + Math.min(k, 20) +
        ';background:' + bg + ';color:' + (L < 62 ? '#FBF8F1' : '#17140E') + '">' +
        '<b>' + esc(r.s) + '</b><span>' + pct(c) + '</span><small>' + inr(r.q.ltp, 0) + '</small></a>';
    }).join('') + '</div>';
  }

  // The most recent scored pick, if it is recent enough to still be news.
  function latestResult(g) {
    var days = Object.keys(g.picks).filter(function (d) { return g.picks[d] && g.picks[d].result; }).sort();
    var d = days[days.length - 1];
    if (!d) return null;
    var age = (Date.parse(istDate()) - Date.parse(d)) / 864e5;
    return age <= 3 ? g.picks[d] : null;
  }

  function gamePanel(l) {
    var g = game(), today = g.picks[istDate()];
    var hist = Object.keys(g.picks).sort().reverse().slice(0, 7).map(function (d) {
      var p = g.picks[d], r = p.result;
      var cls = !r ? 'wait' : r.kind;
      var txt = !r ? 'waiting for the close' : r.kind === 'void' ? 'no session — not scored'
        : (r.kind === 'win' ? '1st of ' + r.of + ' · +3' : r.rank + ' of ' + r.of + (r.points ? ' · +1' : ' · 0')) + ' · ' + pct(r.pct);
      return '<li class="' + cls + '"><span>' + esc(niceDate(d)) + '</span><b>' + esc(p.sym) + '</b><small>' + esc(txt) + '</small></li>';
    }).join('');
    var fresh = latestResult(g);
    var banner = '';
    if (fresh) {
      var r = fresh.result;
      banner = '<div class="wl-game-result ' + r.kind + '">' +
        (r.kind === 'win' ? '🏆 <b>' + esc(fresh.sym) + ' won the day</b> — ' + pct(r.pct) + ', first of ' + r.of + '. Three points.'
          : r.kind === 'beat' ? '👏 <b>' + esc(fresh.sym) + ' beat the list</b> — ' + pct(r.pct) + ', ' + r.rank + ' of ' + r.of + '. One point. ' + esc(r.top) + ' won with ' + pct(r.topPct) + '.'
          : r.kind === 'void' ? 'No session on that day, so the pick was not scored.'
          : '😅 <b>' + esc(fresh.sym) + '</b> finished ' + r.rank + ' of ' + r.of + ' (' + pct(r.pct) + '). ' + esc(r.top) + ' won with ' + pct(r.topPct) + '.') +
        '</div>';
    }
    var status = today
      ? '<p class="wl-game-now">Today’s pick: <b>' + esc(today.sym) + '</b> from ' + esc(today.list) + '. ' +
        (today.result ? 'Scored.' : 'Results after 3:30 pm IST.') + '</p>'
      : pickOpen()
        ? '<p class="wl-game-now">Tap <b>⚑ Pick</b> on the stock you think ends today highest on this list.</p>'
        : '<p class="wl-game-now">Picks are closed — they open on weekdays until 3:30 pm IST.</p>';
    return '<section class="wl-game" aria-labelledby="wl-game-h">' +
      '<div class="wl-game-head"><h3 id="wl-game-h">Pick today’s winner</h3>' +
        '<div class="wl-game-score"><span><b>' + g.points + '</b><small>points</small></span>' +
        '<span><b>' + g.streak + (g.streak >= 3 ? ' 🔥' : '') + '</b><small>streak</small></span>' +
        '<span><b>' + g.best + '</b><small>best</small></span>' +
        '<span><b>' + g.wins + '/' + g.played + '</b><small>wins</small></span></div></div>' +
      banner + status +
      (hist ? '<ol class="wl-game-hist">' + hist + '</ol>' : '') +
      '<p class="wl-game-fine">Three points if your pick tops the list, one if it beats the list’s average. A game for fun on this browser — no money, and not a view on what to buy.</p>' +
    '</section>';
  }

  function paintStage() {
    var host = $('wl-stage');
    if (!host) return;
    var l = listById(S.active) || listById('main');
    S.active = l.id;
    var today = game().picks[istDate()];
    var rows = sorted(l);
    var body = !l.symbols.length
      ? '<div class="wl-empty"><span class="wl-empty-e" aria-hidden="true">' + esc(l.emoji || '⭐') + '</span>' +
        '<b>' + esc(l.name) + ' is empty</b><p>Add a stock above, tap ☆ Save on any stock page, or copy names in from a featured list.</p></div>'
      : S.mode === 'race' ? race(l, rows) : S.mode === 'heat' ? heat(l, rows) : cards(l, rows, today);
    host.innerHTML = hero(l) + toolbar(l) + body + gamePanel(l) +
      '<p class="wl-note">' + esc(S.note || 'Prices are delayed daily closes unless the live feed is connected.') + '</p>';
    if (S.renaming) {
      var inp = $('wl-name-in');
      if (inp) { inp.focus(); inp.select(); }
    }
    var g = game(), last = latestResult(g);
    if (last && last.result.kind === 'win' && !last.result.celebrated) {
      last.result.celebrated = true;
      saveGame(g);
      confetti();
    }
    if (still()) host.classList.add('wl-still');
  }

  function render() {
    if (!S.built) return;
    var note = $('wl-sync');
    if (note) {
      note.textContent = auth()
        ? 'Saved to your account — every list follows you to any device you sign in on.'
        : 'Saved on this browser. Sign in and your lists follow you everywhere.';
    }
    paintShelf();
    paintStage();
  }

  /* ── Suggestions for the add box ─────────────────────────────────────── */

  var suggIndex = -1;
  function suggest(text) {
    var box = $('wl-sugg'), inp = $('wl-add-in');
    if (!box) return;
    text = text.trim().toUpperCase();
    if (!text) { box.hidden = true; inp.setAttribute('aria-expanded', 'false'); return; }
    universe().then(function (rows) {
      var starts = [], contains = [];
      for (var i = 0; i < rows.length && starts.length < 8; i++) {
        var r = rows[i], s = String(r.s || r.symbol || ''), n = String(r.n || r.name || '');
        if (s.indexOf(text) === 0) starts.push(r);
        else if (contains.length < 8 && (n.toUpperCase().indexOf(text) >= 0 || s.indexOf(text) > 0)) contains.push(r);
      }
      var list = starts.concat(contains).slice(0, 8);
      if (!list.length && validSym(text)) list = [{ s: text, n: 'Add “' + text + '”' }];
      suggIndex = -1;
      box.innerHTML = list.map(function (r, k) {
        var s = String(r.s || r.symbol || '');
        return '<li role="option" id="wl-sugg-' + k + '" data-add="' + esc(s) + '"><b>' + esc(s) + '</b><span>' + esc(r.n || r.name || '') + '</span></li>';
      }).join('');
      box.hidden = !list.length;
      inp.setAttribute('aria-expanded', list.length ? 'true' : 'false');
    });
  }

  /* ── The page and its events ─────────────────────────────────────────── */

  function shell() {
    return '<div class="wl">' +
      '<header class="wl-head">' +
        '<p class="wl-kick">My money · watchlists</p>' +
        '<h2>Watchlists</h2>' +
        '<p class="wl-lede">Every list you keep, live: today’s move, the week, the month, and how far each name has come since it went on the list. Race them, share them, and pick a winner.</p>' +
        '<p class="wl-sync" id="wl-sync"></p>' +
      '</header>' +
      '<div class="wl-shelf" id="wl-shelf"></div>' +
      '<div class="wl-stage" id="wl-stage"></div>' +
      '<div class="wl-toast" id="wl-toast" role="status" aria-live="polite"></div>' +
    '</div>';
  }

  function commitRename() {
    var inp = $('wl-name-in'), l = listById(S.active);
    if (!inp || !l) { S.renaming = false; return; }
    var name = cleanName(inp.value, l.name);
    S.renaming = false;
    if (name !== l.name) {
      if (l.main) DOC.main.name = name; else l.name = name;
      saveDoc();
      toast('Renamed to ' + name + '.');
    }
    render();
  }

  function onClick(e) {
    var t = e.target;
    var tile = t.closest('[data-list]');
    if (tile) {
      S.active = tile.dataset.list; S.renaming = false; S.confirmDelete = null;
      writeJSON(VIEW_KEY, { active: S.active, mode: S.mode, sort: S.sort });
      render();
      refreshQuotes();
      return;
    }
    if (t.closest('#wl-new')) {
      var l = newList('New list ' + (DOC.lists.length + 1));
      if (l) { S.active = l.id; S.renaming = true; render(); }
      return;
    }
    var act = t.closest('[data-act]');
    var cur = listById(S.active);
    if (act && cur) {
      var a = act.dataset.act;
      if (a === 'rename') { S.renaming = true; paintStage(); return; }
      if (a === 'style') {
        var st = $('wl-style'); st.hidden = !st.hidden;
        act.setAttribute('aria-expanded', st.hidden ? 'false' : 'true');
        return;
      }
      if (a === 'share') { share(cur); return; }
      if (a === 'copy' || a === 'follow') {
        var copy = newList(a === 'copy' ? cur.name + ' (copy)' : cur.name, cur.symbols, cur.emoji, cur.color);
        if (copy) {
          toast(a === 'follow' ? 'Kept a copy of ' + cur.name + ' in your lists.' : 'Duplicated ' + cur.name + '.');
          if (cur.isShared) {
            S.shared = null;
            try { history.replaceState(null, '', location.pathname + '#portfolio/watchlists'); } catch (x) {}
          }
          S.active = copy.id; render();
        }
        return;
      }
      if (a === 'delete') {
        if (S.confirmDelete === cur.id) {
          var name = cur.name; deleteList(cur.id); S.confirmDelete = null; toast('Deleted ' + name + '.'); render();
        } else {
          S.confirmDelete = cur.id; paintStage();
          setTimeout(function () { if (S.confirmDelete === cur.id) { S.confirmDelete = null; paintStage(); } }, 3500);
        }
        return;
      }
    }
    var em = t.closest('[data-emoji]');
    if (em && cur && isMine(cur)) {
      if (cur.main) DOC.main.emoji = em.dataset.emoji; else cur.emoji = em.dataset.emoji;
      saveDoc(); render(); var s1 = $('wl-style'); if (s1) s1.hidden = false; return;
    }
    var co = t.closest('[data-color]');
    if (co && cur && isMine(cur)) {
      if (cur.main) DOC.main.color = co.dataset.color; else cur.color = co.dataset.color;
      saveDoc(); render(); var s2 = $('wl-style'); if (s2) s2.hidden = false; return;
    }
    var rm = t.closest('[data-remove]');
    if (rm && cur && isMine(cur)) { removeSymbol(cur, rm.dataset.remove); render(); return; }
    var pk = t.closest('[data-pick]');
    if (pk && cur) { pick(cur, pk.dataset.pick); return; }
    var ad = t.closest('[data-add]');
    if (ad && cur && isMine(cur)) {
      if (addSymbol(cur, ad.dataset.add)) { render(); var inp2 = $('wl-add-in'); if (inp2) inp2.focus(); }
      return;
    }
    var seg = t.closest('#wl-mode button[data-v]');
    if (seg) {
      S.mode = seg.dataset.v;
      writeJSON(VIEW_KEY, { active: S.active, mode: S.mode, sort: S.sort });
      paintStage();
      return;
    }
    if (!t.closest('.wl-add')) { var bx = $('wl-sugg'); if (bx) bx.hidden = true; }
  }

  function onChange(e) {
    var t = e.target, cur = listById(S.active);
    if (t.id === 'wl-sort') {
      S.sort = t.value;
      writeJSON(VIEW_KEY, { active: S.active, mode: S.mode, sort: S.sort });
      paintStage();
      return;
    }
    if (t.dataset && t.dataset.copy && t.value) {
      var target = listById(t.value);
      if (target && isMine(target)) addSymbol(target, t.dataset.copy);
      render();
    }
  }

  function onKey(e) {
    var t = e.target;
    if (t.id === 'wl-name-in') {
      if (e.key === 'Enter') { e.preventDefault(); commitRename(); }
      if (e.key === 'Escape') { S.renaming = false; paintStage(); }
      return;
    }
    if (t.id === 'wl-add-in') {
      var box = $('wl-sugg'), items = box ? box.querySelectorAll('li') : [];
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!items.length) return;
        e.preventDefault();
        suggIndex = (suggIndex + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items.forEach(function (li, k) { li.classList.toggle('on', k === suggIndex); li.setAttribute('aria-selected', k === suggIndex ? 'true' : 'false'); });
        t.setAttribute('aria-activedescendant', 'wl-sugg-' + suggIndex);
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        var choice = items[suggIndex >= 0 ? suggIndex : 0];
        var sym = choice ? choice.dataset.add : norm(t.value);
        var cur = listById(S.active);
        if (cur && isMine(cur) && addSymbol(cur, sym)) { render(); var again = $('wl-add-in'); if (again) again.focus(); }
        return;
      }
      if (e.key === 'Escape' && box) { box.hidden = true; }
    }
  }

  var suggTimer = null;
  function onInput(e) {
    if (e.target.id !== 'wl-add-in') return;
    clearTimeout(suggTimer);
    var v = e.target.value;
    suggTimer = setTimeout(function () { suggest(v); }, 90);
  }

  function build() {
    var v = $('view-watchlists');
    if (!v || S.built) return;
    v.innerHTML = shell();
    S.built = true;
    v.addEventListener('click', onClick);
    v.addEventListener('change', onChange);
    v.addEventListener('keydown', onKey);
    v.addEventListener('input', onInput);
    v.addEventListener('focusout', function (e) {
      if (e.target.id === 'wl-name-in') setTimeout(function () { if (S.renaming) commitRename(); }, 0);
    });
  }

  function poll() {
    clearInterval(S.timer);
    S.timer = setInterval(function () {
      if (S.visible && !document.hidden) refreshQuotes();
    }, 60000);
  }

  function open() {
    build();
    S.visible = true;
    render();
    refreshQuotes();
    loadFeatured();
    pullDoc();
    poll();
  }

  function show() {
    if (window.AltahaNav) window.AltahaNav.go('portfolio', 'watchlists', true);
    else location.href = 'index.html?go=watchlists';
  }

  /* ── Boot ────────────────────────────────────────────────────────────── */

  var saved = readJSON(VIEW_KEY, null);
  if (saved && typeof saved === 'object') {
    if (saved.mode) S.mode = saved.mode;
    if (saved.sort) S.sort = saved.sort;
    if (saved.active) S.active = saved.active;
  }
  S.shared = readShared();
  if (S.shared) S.active = 'shared';

  window.addEventListener('altaha:navigate', function (e) {
    var tab = e.detail && e.detail.tab;
    S.visible = tab === 'watchlists';
  });
  window.addEventListener('altaha-auth', function () { if (S.built) { pullDoc(); render(); } });
  window.addEventListener('storage', function (e) {
    if (e.key === SETS_KEY || e.key === MAIN_KEY || e.key === null) { DOC = readDoc(); render(); }
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && S.visible) refreshQuotes();
  });
  // A star pressed on this page (an Ideas row, the market board) changes the
  // main list; repaint if the reader is looking at it.
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-save-stock]') && S.visible) setTimeout(render, 0);
  });

  // ?go=watchlists can switch to the tab before this deferred file has run,
  // in which case nobody called open(). Check once the page has settled.
  function openIfShowing() {
    var v = $('view-watchlists');
    if (v && v.style.display === 'block' && !S.built) open();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(openIfShowing, 0); });
  else setTimeout(openIfShowing, 0);

  window.AltahaWatchlists = {
    open: open, show: show,
    // For the tests and for any page that wants a count without the page.
    lists: function () { return myLists().map(function (l) { return { id: l.id, name: l.name, symbols: l.symbols.slice() }; }); }
  };
})();
