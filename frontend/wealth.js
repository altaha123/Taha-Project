/* Altaha — Wealth desk

   WHAT THIS PAGE IS
   A portfolio manager's book. Sign in, set up a desk once, and the account is
   a wealth manager's: every client's portfolio live, the price each stock was
   RECOMMENDED at beside the price the client BOUGHT at, and — where the
   arrangement is a share of profits — the commission, worked out step by step
   with its high-water mark, hurdle, fixed fee and GST.

   WHERE THE ARITHMETIC LIVES
   On the server (backend/wealth.py, /wealth/book). This file draws what it
   sends. The one exception is the what-if slider on a client's fee, which
   re-runs fee_math() below — a line-for-line copy of the server's — on the
   four numbers the server sent with the fee, so dragging it never needs a
   request and never disagrees with the bill.

   FOUR WAYS IN
   · Signed out: what the desk is, and a sample desk to try (?demo=1) — the
     same screens over five invented clients, priced live, nothing stored.
   · Signed in, no desk: a two-step setup. Then the desk.
   · Signed in with a desk: the desk.
   · Signed in as a CLIENT whose manager switched sharing on: their own
     portfolio, read-only (#mine). Nobody else's, and no private notes.

   VIEWS (the hash)
   #overview  #clients  #client/ID[/holdings|ledger|fees|profile]
   #calls  #fees  #settings  #mine
*/

(function () {
  'use strict';
  if (window.AltahaWealth) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');
  var PRIV_KEY = 'altaha-wealth-private-v1';
  var UNI_KEY = 'altaha-universe-v2';
  var COLORS = ['gold', 'green', 'blue', 'rose', 'violet', 'slate'];
  var PALETTE = ['#C9A63E', '#2F9E6E', '#3D7FB8', '#C8566B', '#8B6BC4', '#66758A', '#D9822B', '#4BA3A3', '#9C6B4E', '#A3A34B'];
  var CTABS = [['holdings', 'Holdings'], ['ledger', 'Ledger'], ['fees', 'Fees'], ['profile', 'Profile']];

  var S = {
    mode: 'boot', book: null, info: null, shared: null, view: 'overview', cid: null, ctab: 'holdings',
    q: '', status: 'live', sort: 'value', recFilter: 'open', stlFilter: 'all', ledFilter: 'all',
    priv: false, polls: 0, timer: null, uni: null, step: 1, setup: {}, mine: 0, whatif: {}
  };

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function finite(v) { return v !== null && v !== undefined && v !== '' && isFinite(v); }
  function num(v) { return finite(v) ? Number(v) : 0; }
  function local(k) { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }
  function setLocal(k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (e) {} }
  function readJSON(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }

  function inr(v, dp) {
    if (!finite(v)) return '—';
    v = Number(v);
    if (dp == null) dp = Math.abs(v) >= 1000 ? 0 : 2;
    var s = Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
    return (v < -0.005 ? '−' : '') + '₹' + s;
  }
  /* A price per share, to the paisa — what a broker's statement shows and
     what a manager checks against it. Amounts stay in whole rupees. */
  function px(v) {
    if (!finite(v)) return '—';
    var r = Math.round(Number(v) * 100) / 100;
    return inr(r, Math.abs(r - Math.round(r)) < 0.001 ? 0 : 2);
  }
  function signed(v, dp) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0.005 ? '+' : '') + inr(v, dp);
  }
  function short(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    var a = Math.abs(v), sg = v < -0.5 ? '−' : '';
    if (a >= 1e7) return sg + '₹' + (a / 1e7).toFixed(a >= 1e9 ? 0 : 2) + ' Cr';
    if (a >= 1e5) return sg + '₹' + (a / 1e5).toFixed(a >= 1e6 ? 1 : 2) + ' L';
    if (a >= 1e4) return sg + '₹' + (a / 1e3).toFixed(1) + 'K';
    return sg + '₹' + Math.round(a).toLocaleString('en-IN');
  }
  function pct(v, dp) {
    if (!finite(v)) return '—';
    v = Number(v);
    return (v > 0.0049 ? '+' : v < -0.0049 ? '−' : '') + Math.abs(v).toFixed(dp == null ? 2 : dp) + '%';
  }
  function qty(v) {
    if (!finite(v)) return '—';
    v = Number(v);
    return Math.abs(v - Math.round(v)) < 1e-6 ? Math.round(v).toLocaleString('en-IN') : v.toLocaleString('en-IN', { maximumFractionDigits: 4 });
  }
  function tone(v) { return !finite(v) ? 'flat' : Number(v) > 0.004 ? 'up' : Number(v) < -0.004 ? 'dn' : 'flat'; }
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(iso) {
    if (!iso) return '—';
    var p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? (+p[2]) + ' ' + MON[+p[1] - 1] + ' ' + p[0] : iso;
  }
  function dshort(iso) {
    if (!iso) return '';
    var p = String(iso).slice(0, 10).split('-');
    return p.length === 3 ? (+p[2]) + ' ' + MON[+p[1] - 1] : iso;
  }
  function monthLabel(k) { var p = k.split('-'); return MON[+p[1] - 1]; }
  function istNow() { return new Date(Date.now() + 330 * 60000); }
  function today() { return istNow().toISOString().slice(0, 10); }
  function initials(name) {
    var w = String(name || '?').replace(/[^A-Za-zÀ-ɏ ]/g, ' ').trim().split(/\s+/).filter(Boolean);
    if (!w.length) return '?';
    var dr = /^(dr|mr|mrs|ms|shri|smt)$/i;
    w = w.filter(function (x) { return !dr.test(x); });
    if (!w.length) return '?';
    return (w[0][0] + (w.length > 1 ? w[w.length - 1][0] : (w[0][1] || ''))).toUpperCase();
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function still() {
    try {
      return document.documentElement.dataset.motion === 'off' ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) { return false; }
  }
  function numv(s) {
    s = String(s == null ? '' : s).replace(/[,₹\s]/g, '');
    return s === '' ? '' : s;
  }

  var toastTimer = null;
  function toast(text, bad) {
    var t = $('wd-toast');
    if (!t) return;
    t.textContent = text;
    t.classList.toggle('bad', !!bad);
    t.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('on'); }, bad ? 5200 : 3000);
  }

  var IC = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6A17.4 17.4 0 0 0 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    home: '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="17.5" cy="9" r="2.5"/><path d="M17 14.6c2.4.3 4 1.9 4.6 4.4"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
    coins: '<ellipse cx="9" cy="7" rx="6" ry="2.6"/><path d="M3 7v4c0 1.4 2.7 2.6 6 2.6s6-1.2 6-2.6V7"/><path d="M9 17.4c-3.3 0-6-1.2-6-2.6v-3.6"/><ellipse cx="16" cy="15" rx="5" ry="2.2"/><path d="M11 15v3.4c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2V15"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    back: '<path d="M15 18l-6-6 6-6"/>',
    trade: '<path d="M7 17 17 7"/><path d="M8 7h9v9"/>',
    rupee: '<path d="M6 4h12M6 9h12M14.5 20 7 13h2.5c3 0 5.5-2 5.5-4.5S12.5 4 9.5 4"/>',
    call: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    bill: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z"/><path d="M9 8h6M9 12h6"/>',
    print: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M6 14h12v7H6z"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
    dots: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    in: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 21h16"/>',
    out: '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M4 21h16"/>',
    gift: '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M5 12v9h14v-9M12 8S10 3 7.5 4.5 9 8 12 8Zm0 0s2-5 4.5-3.5S15 8 12 8Z"/>',
    split: '<path d="M6 3v6a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3"/><path d="M12 15v6"/>',
    bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    alert: '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4M12 17v.5"/>',
    check: '<path d="m5 12 4 4 10-10"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 21h14"/>',
    paste: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h6M9 18h3"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z"/><path d="m9 12 2 2 4-4"/>'
  };
  function ic(k) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (IC[k] || '') + '</svg>';
  }

  /* ── The server ──────────────────────────────────────────────────────── */

  function auth() { return window.AltahaAuth || null; }
  function signedIn() { var a = auth(); return !!(a && a.authed && a.authed()); }

  function detail(d) {
    if (!d) return '';
    if (typeof d.detail === 'string') return d.detail;
    if (d.detail && typeof d.detail.message === 'string') return d.detail.message;
    if (Array.isArray(d.detail) && d.detail[0] && d.detail[0].msg) return d.detail[0].msg;
    return '';
  }

  function api(path, opts) {
    opts = opts || {};
    var method = opts.method || 'GET';
    if (S.mode === 'demo' && method !== 'GET') {
      var e = new Error('This is the sample desk — nothing is saved. Sign in and set up your own desk to keep clients.');
      e.demo = true;
      return Promise.reject(e);
    }
    var init = { method: method, headers: {} };
    if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
    var a = auth();
    var p = (a && a.fetch) ? a.fetch(path, init) : fetch(API + path, init);
    return p.then(function (r) {
      if (opts.raw) {
        if (!r.ok) throw new Error('Could not download that (' + r.status + ').');
        return r;
      }
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var err = new Error(detail(d) || ('Something went wrong (' + r.status + '). Try again.'));
          err.status = r.status;
          throw err;
        }
        return d;
      });
    }, function () {
      throw new Error('Could not reach the server. On the free instance the first request after a quiet spell can take half a minute — try again.');
    });
  }

  /* ── Routing ─────────────────────────────────────────────────────────── */

  function readHash() {
    var h = (location.hash || '').replace(/^#/, '').split('/');
    var v = h[0] || 'overview';
    if (v === 'client' && h[1]) {
      S.view = 'client';
      S.cid = parseInt(h[1], 10);
      S.ctab = CTABS.some(function (t) { return t[0] === h[2]; }) ? h[2] : 'holdings';
    } else if (['overview', 'clients', 'calls', 'fees', 'settings', 'mine'].indexOf(v) >= 0) {
      S.view = v;
    } else {
      S.view = 'overview';
    }
  }

  function go(to) {
    var h = '#' + to;
    if (location.hash === h) { readHash(); render(); return; }
    location.hash = h;
  }

  window.addEventListener('hashchange', function () {
    readHash();
    if (S.mode === 'desk' || S.mode === 'demo' || S.mode === 'portal') {
      render();
      var top = $('wd-tabs');
      if (top && window.scrollY > top.offsetTop) window.scrollTo({ top: Math.max(0, top.offsetTop - 80), behavior: still() ? 'auto' : 'smooth' });
    }
  });

  /* ── Loading ─────────────────────────────────────────────────────────── */

  function isDemo() { return /[?&]demo=1(\b|$)/.test(location.search); }

  function boot() {
    S.priv = local(PRIV_KEY) === '1';
    readHash();
    measureChrome();
    if (isDemo()) { loadDemo(); return; }
    if (!signedIn()) { landing(); return; }
    api('/wealth/desk').then(function (d) {
      S.info = d;
      if (d.desk) {
        loadBook(false);
        if (d.shared) loadShared(true);
      } else if (d.shared) {
        S.mode = 'portal';
        S.view = 'mine';
        loadShared(false);
      } else {
        setupView();
      }
    }).catch(function (e) {
      if (e.status === 401) landing();
      else failView(e.message);
    });
  }

  function loadDemo() {
    S.mode = 'demo';
    fetch(API + '/wealth/demo').then(function (r) {
      if (!r.ok) throw new Error('The sample desk could not be opened (' + r.status + ').');
      return r.json();
    }).then(function (d) {
      S.book = d;
      render();
      schedulePoll();
    }).catch(function (e) { failView(e.message || 'The sample desk could not be opened.'); });
  }

  function loadBook(quiet) {
    var path = S.mode === 'demo' ? '/wealth/demo' : '/wealth/book';
    return api(path).then(function (d) {
      if (S.mode !== 'demo') S.mode = 'desk';
      var first = !S.book;
      S.book = d;
      if (quiet && !first) patch(); else render();
      schedulePoll();
      return d;
    }).catch(function (e) {
      if (e.status === 403) { setupView(); return; }
      if (!quiet) failView(e.message);
      throw e;
    });
  }

  function loadShared(quiet) {
    return api('/wealth/shared').then(function (d) {
      S.shared = d.portfolios || [];
      if (S.mode === 'portal' || !quiet) render();
      else if (S.view === 'mine') render();
      else paintTabs();
    }).catch(function (e) { if (!quiet) failView(e.message); });
  }

  /* Names still coming are fetched in chunks; ask again, a few times. */
  function schedulePoll() {
    clearTimeout(S.timer);
    var b = S.book;
    if (!b || !b.pending || !b.pending.length) { S.polls = 0; return; }
    if (S.polls >= 8) return;
    S.polls++;
    S.timer = setTimeout(function () { loadBook(true).catch(function () {}); }, 3500);
  }

  /* After a write: the whole book again, kept where the reader was. */
  function reload(msg) {
    var y = window.scrollY, next = S.after, then = S.then;
    S.after = null; S.then = null;
    return loadBook(true).then(function () {
      if (msg) toast(msg);
      if (next) go(next); else window.scrollTo(0, y);
      if (then) setTimeout(then, 350);
    });
  }

  function measureChrome() {
    var c = document.querySelector('.sh-chrome');
    var h = c ? c.offsetHeight : 0;
    var wd = $('wd');
    if (wd) wd.style.setProperty('--sh-h', (h ? h + 8 : 12) + 'px');
  }
  window.addEventListener('resize', measureChrome);

  /* ── Lookups ─────────────────────────────────────────────────────────── */

  function clients() { return (S.book && S.book.clients) || []; }
  function clientById(id) {
    var c = clients();
    for (var i = 0; i < c.length; i++) if (c[i].id === id) return c[i];
    return null;
  }
  function recById(id) {
    var r = (S.book && S.book.recs) || [];
    for (var i = 0; i < r.length; i++) if (r[i].id === id) return r[i];
    return null;
  }
  function pv(html) { return '<span class="pv">' + html + '</span>'; }

  /* ── Charts ──────────────────────────────────────────────────────────── */

  var CHARTS = {};
  var chartSeq = 0;

  function sparkPath(vals, w, h, pad) {
    var v = vals.filter(finite).map(Number);
    if (v.length < 2) return null;
    var lo = Math.min.apply(null, v), hi = Math.max.apply(null, v), span = hi - lo || 1;
    pad = pad || 2;
    return v.map(function (x, i) {
      return (i ? 'L' : 'M') + (i * w / (v.length - 1)).toFixed(2) + ' ' + (pad + (h - 2 * pad) * (1 - (x - lo) / span)).toFixed(2);
    }).join(' ');
  }

  function spark(vals, cls) {
    var d = sparkPath(vals || [], 100, 30, 3);
    if (!d) return '<svg class="' + (cls || 'wd-spark') + '" viewBox="0 0 100 30" aria-hidden="true"></svg>';
    return '<svg class="' + (cls || 'wd-spark') + '" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">' +
      '<path class="f" d="' + d + ' L100 30 L0 30 Z"/><path class="l" vector-effect="non-scaling-stroke" d="' + d + '"/></svg>';
  }

  function mini(vals) {
    var v = (vals || []).filter(finite);
    var d = sparkPath(v, 74, 24, 2);
    if (!d) return '';
    var col = v[v.length - 1] >= v[0] ? 'var(--up)' : 'var(--dn)';
    return '<svg class="wd-mini" viewBox="0 0 74 24" aria-hidden="true"><path d="' + d + '" stroke="' + col + '"/></svg>';
  }

  /* A filled line with a crosshair. Drawn in a 600×200 box that stretches;
     the stroke and the dot are kept round by drawing the dot in HTML. */
  function area(vals, dates, opts) {
    opts = opts || {};
    var v = (vals || []).map(function (x) { return finite(x) ? Number(x) : null; });
    var ok = v.filter(function (x) { return x !== null; });
    if (ok.length < 2) {
      return '<div class="wd-area' + (opts.light ? ' light' : '') + '" style="display:grid;place-items:center;color:' +
        (opts.light ? 'var(--mute)' : 'rgba(251,248,241,.55)') + ';font-size:13px">The chart fills in once prices for the last sessions arrive.</div>';
    }
    var id = 'wdc' + (++chartSeq);
    var W = 600, H = 200, P = 10;
    var lo = Math.min.apply(null, ok), hi = Math.max.apply(null, ok), span = (hi - lo) || Math.abs(hi) * 0.02 || 1;
    lo -= span * 0.08; hi += span * 0.08; span = hi - lo;
    var pts = [];
    v.forEach(function (x, i) {
      if (x === null) return;
      pts.push([i * W / (v.length - 1), P + (H - 2 * P) * (1 - (x - lo) / span), x, i]);
    });
    var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    var fill = line + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + H + ' L' + pts[0][0].toFixed(1) + ' ' + H + ' Z';
    var gid = id + 'g';
    var col = opts.light ? 'var(--a, var(--gold))' : 'var(--a2, #F2D58A)';
    CHARTS[id] = { pts: pts, dates: dates || [], W: W, H: H, fmt: opts.fmt || inr };
    var grid = [0.25, 0.5, 0.75].map(function (f) { return '<line class="gd" vector-effect="non-scaling-stroke" x1="0" x2="' + W + '" y1="' + (H * f) + '" y2="' + (H * f) + '"/>'; }).join('');
    return '<div class="wd-area' + (opts.light ? ' light' : '') + '" id="' + id + '" role="img" aria-label="' + esc(opts.label || 'Value over the last sessions') + '">' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
        '<defs><linearGradient id="' + gid + '" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="' + col + '" stop-opacity=".42"/>' +
        '<stop offset="1" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' + grid +
        '<path class="fl" d="' + fill + '" fill="url(#' + gid + ')"/>' +
        '<path class="ln" pathLength="1" vector-effect="non-scaling-stroke" d="' + line + '"/>' +
        '<line class="cx" vector-effect="non-scaling-stroke" x1="0" x2="0" y1="0" y2="' + H + '" style="display:none"/>' +
      '</svg><span class="wd-tip" style="display:none"></span></div>';
  }

  function wireCharts(root) {
    (root || document).querySelectorAll('.wd-area[id]').forEach(function (el) {
      var c = CHARTS[el.id];
      if (!c || el._wired) return;
      el._wired = true;
      var tip = el.querySelector('.wd-tip'), cx = el.querySelector('.cx');
      var dot = document.createElement('span');
      dot.style.cssText = 'position:absolute;width:12px;height:12px;border-radius:50%;transform:translate(-50%,-50%);display:none;pointer-events:none;' +
        'background:#FBF8F1;border:3px solid var(--a, #C9A63E);box-shadow:0 2px 8px rgba(0,0,0,.3)';
      el.appendChild(dot);
      function at(clientX) {
        var r = el.getBoundingClientRect();
        var x = (clientX - r.left) / r.width * c.W, best = c.pts[0];
        c.pts.forEach(function (p) { if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p; });
        var lx = best[0] / c.W * 100, ly = best[1] / c.H * 100;
        cx.setAttribute('x1', best[0]); cx.setAttribute('x2', best[0]); cx.style.display = '';
        dot.style.left = lx + '%'; dot.style.top = ly + '%'; dot.style.display = '';
        tip.style.left = Math.min(88, Math.max(12, lx)) + '%'; tip.style.top = ly + '%'; tip.style.display = '';
        tip.innerHTML = '<span class="pv">' + esc(c.fmt(best[2])) + '</span><small>' + esc(day(c.dates[best[3]] || '')) + '</small>';
      }
      el.addEventListener('pointermove', function (e) { at(e.clientX); });
      el.addEventListener('pointerdown', function (e) { at(e.clientX); });
      el.addEventListener('pointerleave', function () { tip.style.display = 'none'; cx.style.display = 'none'; dot.style.display = 'none'; });
    });
  }

  function donut(items, centre, sub) {
    var total = items.reduce(function (s, x) { return s + Math.max(0, num(x.value)); }, 0);
    if (total <= 0) return '<p class="wd-muted">Nothing held yet.</p>';
    var at = 0, segs = '', legend = '';
    items.slice(0, 9).forEach(function (x, i) {
      var len = 100 * Math.max(0, num(x.value)) / total;
      var colr = x.color || PALETTE[i % PALETTE.length];
      segs += '<circle class="seg" cx="85" cy="85" r="64" pathLength="100" stroke="' + colr + '" style="--len:' + Math.max(0, len - 0.6).toFixed(2) +
        ';--i:' + i + ';stroke-dashoffset:' + (-at).toFixed(2) + '"/>';
      at += len;
      legend += '<li><i style="background:' + colr + '"></i><span>' + esc(x.label) + '</span><b>' + (len >= 9.95 ? len.toFixed(0) : len.toFixed(1)) + '%</b></li>';
    });
    if (items.length > 9) {
      var rest = items.slice(9).reduce(function (s, x) { return s + num(x.value); }, 0);
      legend += '<li><i style="background:var(--rule)"></i><span>' + (items.length - 9) + ' more</span><b>' + (100 * rest / total).toFixed(1) + '%</b></li>';
    }
    return '<div class="wd-donut"><div class="wd-donut-c"><svg viewBox="0 0 170 170" aria-hidden="true">' +
      '<circle cx="85" cy="85" r="64" stroke="var(--rule-2)"/>' + segs + '</svg><span><b class="pv">' + esc(centre) + '</b><small>' + esc(sub || '') + '</small></span></div>' +
      '<ul class="wd-legend">' + legend + '</ul></div>';
  }

  function countUps(root) {
    (root || document).querySelectorAll('[data-count]').forEach(function (el) {
      var to = Number(el.dataset.count), fmt = el.dataset.fmt || 'inr';
      var f = fmt === 'short' ? short : fmt === 'int' ? function (x) { return Math.round(x).toLocaleString('en-IN'); } : function (x) { return inr(x, 0); };
      if (!isFinite(to) || still()) { el.textContent = f(to); return; }
      var t0 = null, dur = 1100;
      function step(t) {
        if (!t0) t0 = t;
        var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        el.textContent = f(to * e);
        if (k < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }

  /* ── The fee, for the what-if slider (wealth.fee_math, line for line) ─ */

  function feeMath(t, level, base, capDays, days) {
    var gain = level - base;
    var fixed = t.fixed_pct / 100 * capDays / 365;
    var hurdle = t.hurdle_pct / 100 * capDays / 365;
    var after = gain - fixed;
    var excess = t.hurdle_type === 'soft' ? (after > hurdle ? after : 0) : after - hurdle;
    excess = Math.max(excess, 0);
    var share = t.share_pct / 100 * excess, fee = fixed + share, gst = fee * t.gst_pct / 100;
    return { gain: gain, fixed: fixed, hurdle: hurdle, excess: excess, share: share, fee: fee, gst: gst, total: fee + gst };
  }

  function termsShort(t) {
    if (!t) return '';
    var parts = [];
    if (t.fixed_pct) parts.push(t.fixed_pct + '% fixed');
    if (t.share_pct) parts.push(t.share_pct + '%' + (t.hurdle_pct ? ' over ' + t.hurdle_pct + '%' : '') + ' share');
    if (!parts.length) return 'No fee';
    return parts.join(' + ') + (t.share_pct && t.hwm ? ' · HWM' : '');
  }

  /* ── Rendering: the frame ────────────────────────────────────────────── */

  function render() {
    var root = $('wd');
    if (!root) return;
    CHARTS = {};
    root.classList.toggle('wd-private', S.priv);
    if (S.mode === 'portal') { root.innerHTML = portalFrame(); after(root); return; }
    if (!S.book) return;
    root.innerHTML = deskBar() + demoBanner() + '<nav class="wd-tabs" id="wd-tabs" aria-label="Wealth desk">' + tabsHTML() + '</nav>' +
      '<section id="wd-view" aria-live="polite">' + viewHTML() + '</section>';
    after(root);
    document.title = (S.view === 'client' && clientById(S.cid) ? clientById(S.cid).name + ' — ' : '') + 'Wealth desk — Altaha Screener';
  }

  /* A quiet refresh (prices arriving) redraws the view, not the frame, so a
     form being typed into in the settings is not wiped. */
  function patch() {
    if (S.view === 'settings' && document.activeElement && $('wd-view') && $('wd-view').contains(document.activeElement)) return;
    var v = $('wd-view');
    if (!v) { render(); return; }
    CHARTS = {};
    v.innerHTML = viewHTML();
    var bar = document.querySelector('.wd-bar');
    if (bar) bar.outerHTML = deskBar();
    paintTabs();
    after($('wd'));
  }

  function after(root) {
    wireCharts(root);
    countUps(root);
    wireWhatIf();
    wireTerms(root);
    measureChrome();
  }

  function paintTabs() {
    var t = $('wd-tabs');
    if (t) t.innerHTML = tabsHTML();
  }

  function deskBar() {
    var b = S.book, d = b.desk || {};
    var reg = d.reg_short ? '<span class="wd-reg">' + ic('shield') + esc(d.reg_short) + (d.registration ? ' ' + esc(d.registration) : '') + '</span>'
      : '<span class="wd-reg none">Not registered</span>';
    var pend = b.pending && b.pending.length
      ? '<span class="wd-pending"><i></i>Fetching prices for ' + plural(b.pending.length, 'stock') + '…</span>' : '';
    return '<header class="wd-bar">' +
      '<span class="wd-mono" aria-hidden="true">' + esc((d.display_name || 'W').trim().charAt(0).toUpperCase()) + '</span>' +
      '<div class="wd-who"><p class="wd-kick">Wealth desk' + (b.demo ? ' · sample' : '') + '</p>' +
        '<h1>' + esc(d.display_name || 'Your desk') + '</h1>' +
        '<small>' + esc(d.firm || '') + (d.firm ? ' · ' : '') + reg + '</small></div>' +
      '<div class="wd-bar-r">' + pend +
        '<button type="button" class="wd-ic" data-act="privacy" aria-pressed="' + S.priv + '" title="' + (S.priv ? 'Show amounts and names' : 'Hide amounts and names (for screen-sharing)') +
          '" aria-label="' + (S.priv ? 'Show amounts and names' : 'Hide amounts and names') + '">' + ic(S.priv ? 'eyeoff' : 'eye') + '</button>' +
        '<button type="button" class="wd-btn" data-act="new-rec">' + ic('call') + 'New call</button>' +
        '<button type="button" class="wd-btn primary" data-act="add-client">' + ic('plus') + 'Add client</button>' +
      '</div></header>';
  }

  function demoBanner() {
    if (!S.book.demo) return '';
    return '<div class="wd-demo"><span>✨ <b>This is a sample desk</b> — five invented clients, priced at today’s market. Click anything; nothing is saved.</span>' +
      '<a class="wd-btn gold" href="' + (signedIn() ? 'wealth.html' : 'signin.html?next=wealth.html') + '">' + (signedIn() ? 'Set up my own desk' : 'Sign in to set up my desk') + '</a></div>';
  }

  function tabsHTML() {
    var b = S.book, alerts = (b && b.alerts || []).filter(function (a) { return ['overdue', 'unpaid', 'stop'].indexOf(a.kind) >= 0; }).length;
    var due = (b && b.clients || []).filter(function (c) { return c.status !== 'closed' && c.fee && c.fee.overdue && c.fee.total > 0.5; }).length;
    var tabs = [['overview', 'Overview', 'home', alerts], ['clients', 'Clients', 'users', 0], ['calls', 'Recommendations', 'target', 0],
                ['fees', 'Commission', 'coins', due], ['settings', 'Desk', 'gear', 0]];
    if (S.shared && S.shared.length) tabs.push(['mine', 'Shared with me', 'share', 0]);
    var cur = S.view === 'client' ? 'clients' : S.view;
    return tabs.map(function (t) {
      return '<button type="button" class="wd-tab' + (cur === t[0] ? ' on' : '') + '" data-go="' + t[0] + '"' + (cur === t[0] ? ' aria-current="page"' : '') + '>' +
        ic(t[2]) + t[1] + (t[3] ? '<span class="wd-badge">' + t[3] + '</span>' : '') + '</button>';
    }).join('');
  }

  function viewHTML() {
    switch (S.view) {
      case 'clients': return clientsView();
      case 'client': return clientView(clientById(S.cid));
      case 'calls': return callsView();
      case 'fees': return feesView();
      case 'settings': return settingsView();
      case 'mine': return mineView();
      default: return overviewView();
    }
  }

  function greeting() {
    var h = istNow().getUTCHours();
    return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  }

  function marketPill(b) {
    return b.market_open ? '<span class="wd-pill wd-live up"><i></i>Market open</span>'
      : '<span class="wd-pill"><i style="color:#8E877A"></i>Market closed · last close</span>';
  }

  /* ── Overview ────────────────────────────────────────────────────────── */

  function overviewView() {
    var b = S.book, t = b.totals, name = (b.desk.display_name || '').split(' ')[0];
    if (!b.clients.length) return firstClientEmpty();
    var html = '<div class="wd-hero c-gold wd-rise">' +
      '<span class="wd-glow" aria-hidden="true"></span>' +
      '<div><p class="wd-hero-k">Book value · ' + esc(day(b.as_of)) + '</p>' +
        '<p class="wd-hero-hi">' + greeting() + (name ? ', ' + esc(name) : '') + '. Here is your book.</p>' +
        '<p class="wd-big pv" data-count="' + num(t.aum) + '" data-fmt="inr">' + esc(inr(t.aum, 0)) + '</p>' +
        '<div class="wd-hero-sub">' +
          '<span class="wd-pill ' + tone(t.day_change) + '">' + (num(t.day_change) >= 0 ? '▲' : '▼') + ' ' + pv(esc(signed(t.day_change, 0))) + ' today · ' + esc(pct(t.day_pct)) + '</span>' +
          marketPill(b) + '<span class="wd-pill">' + plural(t.active, 'active client') + '</span></div></div>' +
      '<div class="wd-hero-chart"><div class="wd-chart-k"><span>Last ' + (b.spark.values.length || 30) + ' sessions</span><span class="pv">' +
        esc(b.spark.values.length ? pct(100 * (b.spark.values[b.spark.values.length - 1] / b.spark.values[0] - 1)) : '') + '</span></div>' +
        area(b.spark.values, b.spark.dates, { label: 'Book value over the last sessions' }) + '</div>' +
      '<div class="wd-trio">' +
        '<div><small>Profit since the start</small><b class="pv ' + (num(t.profit) >= 0 ? '' : 'dn') + '">' + esc(signed(t.profit, 0)) + '</b><span>' + esc(pct(t.profit_pct)) + ' on capital · ' + plural(t.in_profit, 'client') + ' in profit</span></div>' +
        '<div class="gold"><small>Your commission, accrued</small><b class="pv">' + esc(inr(t.accrued, 0)) + '</b><span>' + esc(short(t.accrued_share)) + ' profit share · ' + esc(short(t.accrued_fixed)) + ' fixed</span></div>' +
        '<div><small>Collected · ' + esc(t.fy_label) + '</small><b class="pv">' + esc(inr(t.collected_fy, 0)) + '</b><span>' + (num(t.due) > 0.5 ? pv(esc(short(t.due))) + ' billed, awaiting payment' : 'Nothing awaiting payment') + '</span></div>' +
      '</div></div>';

    var rs = b.rec_stats || {};
    html += '<div class="wd-kpis">' +
      kpi('Clients', t.active + (t.paused ? ' <small style="font-size:.5em" class="wd-muted">+' + t.paused + ' paused</small>' : ''), t.clients + ' on the desk', 'users', 'c-blue', 1) +
      kpi('Capital managed', pv(esc(short(t.capital))), pv(esc(short(t.cash))) + ' in cash', 'rupee', 'c-green', 2) +
      kpi('In profit', t.in_profit + '<small style="font-size:.5em" class="wd-muted"> of ' + (t.active + t.paused) + '</small>', t.below_hwm ? t.below_hwm + ' below the high-water mark' : 'None below the high-water mark', 'up', 'c-gold', 3) +
      kpi('Open calls', rs.open || 0, (rs.judged ? rs.working + ' of ' + rs.judged + ' working · avg ' + pct(rs.avg_pct, 1) : 'No calls yet'), 'target', 'c-violet', 4) +
      kpi('Booked profit', pv(esc(short(t.booked))), pv(esc(short(t.unrealised))) + ' on paper', 'check', 'c-rose', 5) +
      '</div>';

    html += '<div class="wd-grid2">' +
      '<div class="wd-panel wd-rise" style="--i:2"><h3>Needs your attention <small>' + plural(b.alerts.length, 'item') + '</small></h3>' + alertsHTML(b.alerts.slice(0, 7)) + '</div>' +
      '<div class="wd-panel wd-rise" style="--i:3"><h3>Commission <button type="button" class="wd-link" data-go="fees">Open ›</button></h3>' + monthsHTML(b.commission.months) +
        '<div class="wd-key"><span><i style="background:color-mix(in srgb,var(--gold) 40%,var(--rule))"></i>Billed</span><span><i style="background:var(--gold)"></i>Received</span></div></div>' +
      '</div>';

    var top = b.clients.filter(function (c) { return c.status !== 'closed'; }).sort(function (x, y) { return num(y.value) - num(x.value); }).slice(0, 6);
    html += '<div class="wd-sec"><div><h2>Your clients</h2><p>Largest first. Tap a client for their holdings, ledger and fees.</p></div>' +
      '<button type="button" class="wd-btn" data-go="clients">All ' + b.clients.length + ' clients ›</button></div>' +
      '<div class="wd-cards">' + top.map(card).join('') + '</div>';

    html += '<div class="wd-grid2" style="margin-top:16px">' +
      '<div class="wd-panel wd-rise" style="--i:4"><h3>What the book holds <small>across every client</small></h3>' + exposureHTML(b.exposures.slice(0, 8)) + '</div>' +
      '<div class="wd-panel wd-rise" style="--i:5"><h3>Where the money is <small>by sector</small></h3>' +
        donut(b.sectors.map(function (s) { return { label: s.sector, value: s.value, color: s.sector === 'Cash' ? '#9CC6EC' : null }; }), short(t.aum), 'book value') + '</div>' +
      '</div>';
    html += '<p class="wd-note">' + esc(b.disclaimer) + '</p>';
    return html;
  }

  function kpi(label, value, sub, icon, cls, i) {
    return '<div class="wd-kpi ' + cls + ' wd-rise" style="--i:' + i + '"><span class="wd-kpi-ic">' + ic(icon) + '</span><small>' + esc(label) + '</small><b>' + value + '</b><span>' + sub + '</span></div>';
  }

  var ALERT_STYLE = { overdue: ['gold', 'bill'], unpaid: ['rose', 'coins'], below_hwm: ['rose', 'down'], target: ['green', 'target'],
                      stop: ['rose', 'alert'], concentration: ['violet', 'spark'], unpriced: ['slate', 'rupee'], cash: ['blue', 'rupee'] };

  function alertsHTML(list) {
    if (!list.length) {
      return '<div class="wd-allclear">' + ic('check') + '<span><b>All clear.</b> No fees overdue, no calls at their stop, nothing concentrated.</span></div>';
    }
    return '<ul class="wd-alerts">' + list.map(function (a) {
      var st = ALERT_STYLE[a.kind] || ['slate', 'bell'];
      var to = a.rec_id ? 'calls' : a.client_id ? 'client/' + a.client_id + (a.kind === 'overdue' || a.kind === 'unpaid' || a.kind === 'below_hwm' ? '/fees' : '') : 'overview';
      return '<li><button type="button" class="wd-alert c-' + st[0] + '" data-go="' + to + '"><span class="dotc">' + ic(st[1]) + '</span><span class="pv">' + esc(a.text) + '</span><em>›</em></button></li>';
    }).join('') + '</ul>';
  }

  function monthsHTML(months) {
    var max = 0;
    months.forEach(function (m) { max = Math.max(max, num(m.billed), num(m.received)); });
    if (max <= 0) return '<div class="wd-empty" style="padding:22px"><p style="margin:0">No fees billed yet. Settle a client’s period from their Fees tab and it shows here.</p></div>';
    return '<div class="wd-months" role="img" aria-label="Commission billed and received, last twelve months">' + months.map(function (m, i) {
      return '<div class="wd-mo" title="' + esc(monthLabel(m.month) + ': billed ' + inr(m.billed, 0) + ', received ' + inr(m.received, 0)) + '"><div class="cols">' +
        '<i class="b" style="height:' + (100 * num(m.billed) / max).toFixed(1) + '%;--i:' + i + '"></i>' +
        '<i class="r" style="height:' + (100 * num(m.received) / max).toFixed(1) + '%;--i:' + i + '"></i></div><small>' + monthLabel(m.month) + '</small></div>';
    }).join('') + '</div>';
  }

  function exposureHTML(rows) {
    if (!rows.length) return '<p class="wd-muted">Nothing held yet.</p>';
    var max = Math.max.apply(null, rows.map(function (r) { return num(r.value); })) || 1;
    return '<div class="wd-bars">' + rows.map(function (r, i) {
      var who = r.clients.slice(0, 4).map(function (c) { return '<span class="wd-av sm c-' + esc(c.color) + '" title="' + esc(c.name) + '">' + esc(initials(c.name)) + '</span>'; }).join('');
      return '<div class="wd-barrow"><div class="nm"><b><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.symbol) + '</a></b>' +
        '<small><span class="wd-stack">' + who + '</span> ' + plural(r.clients.length, 'client') + '</small></div>' +
        '<div class="wd-track"><i style="width:' + (100 * num(r.value) / max).toFixed(1) + '%;--i:' + i + '"></i></div>' +
        '<div class="v pv">' + esc(short(r.value)) + '<small class="' + tone(r.pnl_pct) + '">' + esc(pct(r.pnl_pct, 1)) + '</small></div></div>';
    }).join('') + '</div>';
  }

  function firstClientEmpty() {
    return '<div class="wd-empty wd-rise"><div class="wd-art">🗂️</div><h3>Your desk is ready</h3>' +
      '<p>Add your first client — a name is enough to start. Then record what they hold, or paste their holdings from a spreadsheet.</p>' +
      '<button type="button" class="wd-btn primary" data-act="add-client">' + ic('plus') + 'Add your first client</button> ' +
      '<a class="wd-btn ghost" href="wealth.html?demo=1">See a sample desk</a></div>';
  }

  /* ── Clients ─────────────────────────────────────────────────────────── */

  function card(c, i) {
    var f = c.fee || {}, t = c.terms || {};
    var foot = '';
    if (c.status === 'closed') foot = '<span class="wd-muted">Closed</span>';
    else if (num(f.to_hwm) > 0.5 && t.share_pct) {
      foot = '<span class="wd-chip warn pv">' + esc(short(f.to_hwm)) + ' below mark</span>';
    } else foot = '<span class="wd-fee pv">' + ic('coins') + esc(inr(f.total, 0)) + '</span>';
    return '<button type="button" class="wd-card c-' + esc(c.color) + ' wd-rise" style="--i:' + (i || 0) + '" data-go="client/' + c.id + '">' +
      '<span class="wd-card-top"><span class="wd-av">' + esc(initials(c.name)) + '</span><span class="wd-card-n"><b class="pv">' + esc(c.name) + '</b>' +
        '<small>' + esc(c.code) + (c.city ? ' · ' + esc(c.city) : '') + ' · ' + esc(c.risk) + '</small></span>' +
        '<span class="wd-st ' + esc(c.status) + '">' + esc(c.status) + '</span></span>' +
      '<span class="wd-card-v"><b class="pv">' + esc(short(c.value)) + '</b><span class="ret ' + tone(c.profit) + '">' + esc(pct(c.profit_pct, 1)) +
        '<small class="pv">' + esc(signed(c.profit, 0)) + '</small></span></span>' +
      spark(c.spark && c.spark.values) +
      '<span class="wd-card-f"><span class="' + tone(c.day_change) + '">' + esc(pct(c.day_pct)) + ' today</span><span>' + esc(termsShort(t)) + '</span>' + foot + '</span>' +
      '</button>';
  }

  function clientsView() {
    var b = S.book;
    if (!b.clients.length) return firstClientEmpty();
    var segs = [['live', 'Current'], ['active', 'Active'], ['paused', 'Paused'], ['closed', 'Closed'], ['all', 'All']];
    return '<div class="wd-sec" style="margin-top:4px"><div><h2>Clients</h2><p>' + plural(b.clients.length, 'client') + ' · ' + pv(esc(inr(b.totals.aum, 0))) + ' under management.</p></div>' +
      '<button type="button" class="wd-btn primary" data-act="add-client">' + ic('plus') + 'Add client</button></div>' +
      '<div class="wd-tools"><label class="wd-search">' + ic('users') + '<span class="wd-sr">Find a client</span><input id="wd-q" type="search" placeholder="Find a client by name, code, city or tag" value="' + esc(S.q) + '" autocomplete="off"></label>' +
      '<div class="wd-seg" role="group" aria-label="Status">' + segs.map(function (s) {
        return '<button type="button" data-act="status" data-v="' + s[0] + '" class="' + (S.status === s[0] ? 'on' : '') + '" aria-pressed="' + (S.status === s[0]) + '">' + s[1] + '</button>';
      }).join('') + '</div>' +
      '<label><span class="wd-sr">Sort</span><select class="wd-select" id="wd-sort">' +
        [['value', 'Largest'], ['return', 'Best return'], ['today', 'Today'], ['fee', 'Commission accrued'], ['name', 'Name']].map(function (o) {
          return '<option value="' + o[0] + '"' + (S.sort === o[0] ? ' selected' : '') + '>' + o[1] + '</option>';
        }).join('') + '</select></label></div>' +
      '<div class="wd-cards" id="wd-cardgrid">' + clientCards() + '</div>';
  }

  function clientCards() {
    var q = S.q.trim().toLowerCase();
    var list = clients().filter(function (c) {
      if (S.status === 'live' && c.status === 'closed') return false;
      if (['active', 'paused', 'closed'].indexOf(S.status) >= 0 && c.status !== S.status) return false;
      if (!q) return true;
      return [c.name, c.code, c.city, c.email, (c.tags || []).join(' ')].join(' ').toLowerCase().indexOf(q) >= 0;
    });
    var key = { value: function (c) { return -num(c.value); }, return: function (c) { return -num(c.profit_pct); },
                today: function (c) { return -num(c.day_pct); }, fee: function (c) { return -num(c.fee && c.fee.total); },
                name: function (c) { return c.name.toLowerCase(); } }[S.sort] || function (c) { return -num(c.value); };
    list.sort(function (a, b) { var x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : 0; });
    if (!list.length) return '<div class="wd-empty" style="grid-column:1/-1"><p style="margin:0">No client matches that.</p></div>';
    return list.map(card).join('');
  }

  /* ── One client ──────────────────────────────────────────────────────── */

  function clientView(c, ro) {
    if (!c) {
      return '<div class="wd-empty"><h3>That client is not on this desk</h3><p>They may have been removed.</p>' +
        '<button type="button" class="wd-btn" data-go="clients">All clients</button></div>';
    }
    var t = c.terms || {}, f = c.fee || {};
    var contact = [c.email, c.phone].filter(Boolean).map(esc).join(' · ');
    var acts = ro ? '<button type="button" class="wd-act primary" data-act="statement" data-id="' + c.id + '">' + ic('print') + 'Statement</button>' :
      '<button type="button" class="wd-act primary" data-act="add-event" data-id="' + c.id + '" data-kind="buy">' + ic('trade') + 'Trade</button>' +
      '<button type="button" class="wd-act" data-act="add-event" data-id="' + c.id + '" data-kind="deposit">' + ic('rupee') + 'Money in / out</button>' +
      '<button type="button" class="wd-act" data-act="upload" data-id="' + c.id + '">' + ic('in') + 'Upload statement</button>' +
      '<button type="button" class="wd-act" data-act="settle" data-id="' + c.id + '">' + ic('bill') + 'Settle fee</button>' +
      '<button type="button" class="wd-act" data-act="statement" data-id="' + c.id + '">' + ic('print') + 'Statement</button>' +
      '<button type="button" class="wd-act" data-go="client/' + c.id + '/profile">' + ic('edit') + 'Edit</button>';
    var html = (ro ? '' : '<button type="button" class="wd-back" data-go="clients">' + ic('back') + 'All clients</button>') +
      '<div class="wd-hero wd-chero c-' + esc(c.color) + ' wd-rise"><span class="wd-glow" aria-hidden="true"></span>' +
      '<div style="min-width:0"><div class="wd-cid"><span class="wd-av lg">' + esc(initials(c.name)) + '</span><div style="min-width:0">' +
        '<p class="wd-hero-k">' + esc(c.code) + ' · ' + esc(c.risk) + (c.status !== 'active' ? ' · ' + esc(c.status) : '') + '</p>' +
        '<h2 class="pv">' + esc(c.name) + '</h2><p>' + (c.city ? esc(c.city) + ' · ' : '') + 'Client since ' + esc(day(c.since)) +
        (contact ? ' · <span class="pv">' + contact + '</span>' : '') + '</p></div></div>' +
        '<div class="wd-terms"><span class="wd-chip dark">' + ic('coins') + esc(c.terms_label) + '</span>' +
          (c.portal && !ro ? '<span class="wd-chip dark" title="This client can see their portfolio when they sign in">' + ic('share') + 'Shared with client</span>' : '') +
          (c.tags || []).map(function (x) { return '<span class="wd-chip dark">' + esc(x) + '</span>'; }).join('') + '</div>' +
        '<div class="wd-cvals"><div class="wd-cv"><small>Value today</small><p class="wd-big pv" data-count="' + num(c.value) + '">' + esc(inr(c.value, 0)) + '</p></div>' +
          '<div class="wd-cv"><small>Profit</small><b class="pv ' + (num(c.profit) < 0 ? 'dn' : '') + '">' + esc(signed(c.profit, 0)) + '</b></div>' +
          '<div class="wd-cv"><small>Return</small><b>' + esc(pct(c.profit_pct, 1)) + '</b></div>' +
          '<div class="wd-cv"><small>XIRR</small><b title="' + (c.xirr == null ? 'Shown once the money has been in for 90 days' : 'Annualised, money-weighted') + '">' + (c.xirr == null ? '—' : esc(pct(c.xirr, 1))) + '</b></div>' +
          '<div class="wd-cv"><small>Today</small><b class="pv">' + esc(signed(c.day_change, 0)) + '</b></div></div>' +
        '<div class="wd-acts">' + acts + '</div></div>' +
      '<div class="wd-hero-chart"><div class="wd-chart-k"><span>Value, last sessions</span><span class="pv">' + esc(short(c.capital)) + ' capital in</span></div>' +
        area(c.spark && c.spark.values, c.spark && c.spark.dates, { label: c.name + '’s portfolio value' }) +
        '<div class="wd-trio" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-top:10px">' +
          '<div><small>Cash</small><b class="pv">' + esc(short(c.cash)) + '</b></div>' +
          '<div class="gold"><small>' + (ro ? 'Fee accrued' : 'Your fee, accrued') + '</small><b class="pv">' + esc(inr(f.total, 0)) + '</b></div></div></div>' +
      '</div>';
    if (c.errors && c.errors.length && !ro) {
      html += '<div class="wd-demo" style="border-color:var(--dn)"><span>⚠️ <b>Something in this ledger does not add up:</b> ' + esc(c.errors[0]) + ' Check the ledger.</span></div>';
    }
    var tabs = ro ? CTABS.filter(function (x) { return x[0] !== 'profile'; }) : CTABS;
    var counts = { holdings: c.holdings.length, ledger: c.events.length };
    var cur = ro ? (S.ctab === 'profile' ? 'holdings' : S.ctab) : S.ctab;
    html += '<div class="wd-subtabs c-' + esc(c.color) + '" role="tablist">' + tabs.map(function (x) {
      return '<button type="button" role="tab" aria-selected="' + (cur === x[0]) + '" class="' + (cur === x[0] ? 'on' : '') + '" data-ctab="' + x[0] + '">' +
        x[1] + (counts[x[0]] ? ' <span class="wd-muted">' + counts[x[0]] + '</span>' : '') + '</button>';
    }).join('') + '</div><div class="c-' + esc(c.color) + '">';
    if (cur === 'ledger') html += ledgerTab(c, ro);
    else if (cur === 'fees') html += feesTab(c, ro);
    else if (cur === 'profile' && !ro) html += profileTab(c);
    else html += holdingsTab(c, ro);
    return html + '</div>';
  }

  function scoreChip(s) {
    if (!finite(s)) return '';
    return '<span class="wd-score ' + (s >= 65 ? 'hi' : s < 40 ? 'lo' : '') + '" title="Altaha Score">' + Math.round(s) + '</span>';
  }

  function ttTrack(h) {
    if (!finite(h.target) || !finite(h.stop) || !finite(h.ltp) || h.target <= h.stop) return '<span class="wd-muted">—</span>';
    var span = h.target - h.stop;
    var at = Math.max(0, Math.min(1, (h.ltp - h.stop) / span)), rec = finite(h.rec_price) ? Math.max(0, Math.min(1, (h.rec_price - h.stop) / span)) : null;
    return '<span class="wd-tt" title="Stop ' + esc(px(h.stop)) + ' · target ' + esc(px(h.target)) + '"><span class="bar"></span>' +
      (rec !== null ? '<span class="rec" style="left:' + (100 * rec).toFixed(1) + '%"></span>' : '') +
      '<span class="at" style="left:' + (100 * at).toFixed(1) + '%"></span></span>';
  }

  /* A price in the holdings table is a button that opens the holding's
     editor, except on a client's own read-only view. */
  function editCell(c, h, html, ro, what) {
    if (ro) return html;
    return '<button type="button" class="wd-cellbtn" data-act="edit-hold" data-id="' + c.id + '" data-sym="' + esc(h.symbol) + '" ' +
      'title="Edit the ' + what + ' price" aria-label="Edit ' + esc(h.symbol) + '’s ' + what + ' price">' + html + ic('edit') + '</button>';
  }

  function edge(h) {
    if (!finite(h.edge_pct)) return '';
    var good = h.edge_pct >= 0;
    return '<span class="wd-edge ' + (good ? 'good' : 'bad') + '" title="' + (good ? 'Bought below' : 'Bought above') + ' the recommended price">' +
      (good ? '▼ ' : '▲ ') + Math.abs(h.edge_pct).toFixed(1) + '%</span>';
  }

  function holdingsTab(c, ro) {
    if (!c.holdings.length) {
      return '<div class="wd-empty"><div class="wd-art">📈</div><h3>Nothing held yet</h3><p>' + (ro ? 'Your manager has not recorded any holdings yet.' :
        'Upload their holdings statement from the broker (.xlsx or CSV), record a buy, or book a recommendation for them.') + '</p>' +
        (ro ? '' : '<button type="button" class="wd-btn primary" data-act="add-event" data-id="' + c.id + '" data-kind="buy">' + ic('trade') + 'Record a buy</button> ' +
        '<button type="button" class="wd-btn" data-act="upload" data-id="' + c.id + '">' + ic('in') + 'Upload a holdings statement</button>') + '</div>';
    }
    var rows = c.holdings.map(function (h) {
      return '<tr><td class="wd-sym"><a href="stock.html?ticker=' + encodeURIComponent(h.symbol) + '"><b>' + esc(h.symbol) + '</b></a>' + scoreChip(h.score) +
          '<small>' + esc(h.name || h.sector || '') + (h.price_source === 'manual' ? ' · hand-priced' : '') + '</small></td>' +
        '<td>' + esc(qty(h.qty)) + '</td>' +
        '<td>' + editCell(c, h, finite(h.rec_price) ? esc(px(h.rec_price)) : '<span class="wd-muted">Add</span>', ro, 'recommended') + '</td>' +
        '<td>' + editCell(c, h, esc(px(h.avg)), ro, 'buying') + ' ' + edge(h) + '</td>' +
        '<td>' + (h.priced ? esc(px(h.ltp)) + '<small class="' + tone(h.change_pct) + '">' + esc(pct(h.change_pct)) + '</small>' : '<span class="wd-muted">no price</span>') + '</td>' +
        '<td>' + mini(h.spark) + '</td>' +
        '<td class="pv">' + esc(inr(h.value, 0)) + '</td>' +
        '<td class="' + tone(h.pnl) + '"><span class="pv">' + esc(signed(h.pnl, 0)) + '</span><small class="' + tone(h.pnl) + '">' + esc(pct(h.pnl_pct, 1)) + '</small></td>' +
        '<td><span class="wd-w" style="--w:' + Math.min(100, num(h.weight)).toFixed(1) + '%"><i></i>' + esc(finite(h.weight) ? h.weight.toFixed(1) + '%' : '—') + '</span></td>' +
        '<td>' + ttTrack(h) + '</td>' +
        (ro ? '' : '<td><button type="button" class="wd-rowbtn" data-act="hold" data-id="' + c.id + '" data-sym="' + esc(h.symbol) + '" aria-label="Actions for ' + esc(h.symbol) + '">' + ic('dots') + '</button></td>') +
        '</tr>';
    }).join('');
    var cost = c.holdings.reduce(function (s, h) { return s + num(h.cost); }, 0);
    var unpnl = c.holdings.reduce(function (s, h) { return s + num(h.pnl); }, 0);
    if (num(c.cash) > 0.5) {
      rows += '<tr><td class="wd-sym"><b>Cash</b><small>' + (c.mode === 'holdings' ? 'From sales, not yet reinvested' : 'Not yet invested') + '</small></td><td></td><td></td><td></td><td></td><td></td>' +
        '<td class="pv">' + esc(inr(c.cash, 0)) + '</td><td></td><td><span class="wd-w" style="--w:' + (100 * num(c.cash) / Math.max(1, num(c.value))).toFixed(1) + '%"><i></i>' +
        (100 * num(c.cash) / Math.max(1, num(c.value))).toFixed(1) + '%</span></td><td></td>' + (ro ? '' : '<td></td>') + '</tr>';
    }
    var table = '<div class="wd-table-wrap cards"><table class="wd-table"><thead><tr><th scope="col">Stock</th><th scope="col">Qty</th><th scope="col">Recommended</th>' +
      '<th scope="col">Bought at</th><th scope="col">Price</th><th scope="col"><span class="wd-sr">Trend</span>30 days</th><th scope="col">Value</th><th scope="col">P&amp;L</th>' +
      '<th scope="col">Weight</th><th scope="col">Stop → target</th>' + (ro ? '' : '<th scope="col"><span class="wd-sr">Actions</span></th>') + '</tr></thead><tbody>' + rows + '</tbody>' +
      '<tfoot><tr class="wd-foot"><td>Total</td><td></td><td></td><td class="pv">' + esc(inr(cost, 0)) + '</td><td></td><td></td><td class="pv">' + esc(inr(c.value, 0)) + '</td>' +
      '<td class="' + tone(unpnl) + ' pv">' + esc(signed(unpnl, 0)) + '</td><td></td><td></td>' + (ro ? '' : '<td></td>') + '</tr></tfoot></table></div>';
    var cardsHtml = '<div class="wd-hlist">' + c.holdings.map(function (h) {
      return '<div class="wd-hcard"><div class="wd-hcard-t"><div class="wd-sym"><a href="stock.html?ticker=' + encodeURIComponent(h.symbol) + '"><b>' + esc(h.symbol) + '</b></a>' + scoreChip(h.score) +
        '<small>' + esc(qty(h.qty)) + ' shares · ' + esc(finite(h.weight) ? h.weight.toFixed(1) + '%' : '') + '</small></div>' +
        '<div style="text-align:right"><b class="pv">' + esc(inr(h.value, 0)) + '</b><small class="' + tone(h.pnl) + '" style="display:block"><span class="pv">' + esc(signed(h.pnl, 0)) + '</span> · ' + esc(pct(h.pnl_pct, 1)) + '</small></div>' +
        (ro ? '' : '<button type="button" class="wd-rowbtn" data-act="hold" data-id="' + c.id + '" data-sym="' + esc(h.symbol) + '" aria-label="Actions for ' + esc(h.symbol) + '">' + ic('dots') + '</button>') + '</div>' +
        '<div class="wd-hcard-g"><div><small>Recommended</small><b>' + editCell(c, h, finite(h.rec_price) ? esc(px(h.rec_price)) : '—', ro, 'recommended') + '</b></div>' +
        '<div><small>Bought at</small><b>' + editCell(c, h, esc(px(h.avg)), ro, 'buying') + '</b> ' + edge(h) + '</div>' +
        '<div><small>Price</small><b>' + (h.priced ? esc(px(h.ltp)) : '—') + '</b> <span class="' + tone(h.change_pct) + '">' + esc(pct(h.change_pct, 1)) + '</span></div></div></div>';
    }).join('') + '</div>';
    var closed = (c.closed || []).filter(function (x) { return Math.abs(num(x.pnl)) > 0.005; });
    var side = '<div class="wd-panel"><h3>Booked so far <small>' + pv(esc(signed(c.realised, 0))) + '</small></h3>' +
      (closed.length ? '<div class="wd-bars">' + closed.slice(0, 8).map(function (x) {
        return '<div class="wd-barrow"><div class="nm"><b>' + esc(x.symbol) + '</b><small>' + esc(qty(x.qty)) + ' sold' + (x.held ? ' · still held' : '') + '</small></div>' +
          '<div></div><div class="v ' + tone(x.pnl) + ' pv">' + esc(signed(x.pnl, 0)) + '<small>' + esc(pct(x.pnl_pct, 1)) + '</small></div></div>';
      }).join('') + '</div>' : '<p class="wd-muted" style="margin:0">Nothing sold yet.</p>') +
      '<p class="wd-note">Dividends ' + pv(esc(inr(c.dividends, 0))) + ' · charges ' + pv(esc(inr(c.charges, 0))) + ' · on paper ' + pv(esc(signed(c.unrealised, 0))) + '</p></div>';
    return table + cardsHtml + '<div class="wd-grid2" style="margin-top:16px"><div class="wd-panel"><h3>Allocation <small>by sector</small></h3>' +
      donut(c.sectors.map(function (s) { return { label: s.sector, value: s.value, color: s.sector === 'Cash' ? '#9CC6EC' : null }; }), short(c.value), 'value') + '</div>' + side + '</div>';
  }

  var KIND = {
    buy: ['Bought', 'up', 'buy'], sell: ['Sold', 'down', 'sell'], deposit: ['Money in', 'in', 'deposit'], withdrawal: ['Money out', 'out', 'withdrawal'],
    dividend: ['Dividend', 'gift', 'dividend'], split: ['Bonus / split', 'split', 'split'], topup: ['Topped up', 'in', 'topup']
  };

  function ledgerTab(c, ro) {
    var segs = [['all', 'Everything'], ['trades', 'Trades'], ['money', 'Money'], ['other', 'Dividends & splits']];
    var list = c.events.filter(function (e) {
      if (S.ledFilter === 'trades') return e.kind === 'buy' || e.kind === 'sell';
      if (S.ledFilter === 'money') return ['deposit', 'withdrawal', 'topup'].indexOf(e.kind) >= 0;
      if (S.ledFilter === 'other') return e.kind === 'dividend' || e.kind === 'split';
      return true;
    });
    var html = '<div class="wd-tools">' + (ro ? '' : '<button type="button" class="wd-btn primary" data-act="add-event" data-id="' + c.id + '" data-kind="buy">' + ic('plus') + 'Add entry</button>' +
      '<button type="button" class="wd-btn" data-act="upload" data-id="' + c.id + '">' + ic('in') + 'Upload a statement</button>') +
      '<div class="wd-seg" role="group" aria-label="Show">' + segs.map(function (s) {
        return '<button type="button" data-act="ledfilter" data-v="' + s[0] + '" class="' + (S.ledFilter === s[0] ? 'on' : '') + '" aria-pressed="' + (S.ledFilter === s[0]) + '">' + s[1] + '</button>';
      }).join('') + '</div></div>';
    if (!list.length) return html + '<div class="wd-empty"><p style="margin:0">Nothing here yet.</p></div>';
    var month = '', out = '';
    list.forEach(function (e) {
      var m = e.on_date.slice(0, 7);
      if (m !== month) { month = m; out += '<li class="wd-day">' + MON[+m.slice(5, 7) - 1] + ' ' + m.slice(0, 4) + '</li>'; }
      var k = KIND[e.kind] || [e.kind, 'dots', 'split'];
      var title, sub = [dshort(e.on_date)], amt = '', amtSub = '';
      if (e.kind === 'buy' || e.kind === 'sell') {
        title = k[0] + ' ' + qty(e.qty) + ' ' + esc(e.symbol);
        sub.push('at ' + px(e.price));
        if (finite(e.rec_price)) sub.push('recommended ' + px(e.rec_price) + ' (' + pct(100 * (e.price / e.rec_price - 1), 1) + ')');
        if (num(e.charges)) sub.push('charges ' + inr(e.charges));
        amt = (e.kind === 'buy' ? '−' : '+') + inr(e.qty * e.price, 0).replace('−', '');
      } else if (e.kind === 'split') {
        title = esc(e.symbol) + ' ×' + qty(e.qty);
        sub.push(e.qty === 2 ? '1:1 bonus or 2-for-1 split' : 'every share became ' + qty(e.qty));
      } else {
        title = k[0];
        amt = (e.kind === 'withdrawal' ? '−' : '+') + inr(e.amount, 0);
      }
      if (e.note) sub.push(e.note);
      out += '<li class="wd-ev"><span class="k ' + k[2] + '">' + ic(k[1]) + '</span><span class="t"><b>' + title + '</b><small>' + esc(sub.join(' · ')) + '</small></span>' +
        '<span class="amt pv">' + esc(amt) + (amtSub ? '<small>' + amtSub + '</small>' : '') + '</span>' +
        (ro || e.auto ? '<span></span>' : '<span class="acts"><button type="button" class="wd-rowbtn" data-act="edit-event" data-id="' + c.id + '" data-eid="' + e.id + '" aria-label="Edit this entry">' + ic('edit') + '</button>' +
          '<button type="button" class="wd-rowbtn" data-act="del-event" data-id="' + c.id + '" data-eid="' + e.id + '" aria-label="Remove this entry">' + ic('trash') + '</button></span>') + '</li>';
    });
    return html + '<div class="wd-panel" style="padding:8px"><ul class="wd-ledger">' + out + '</ul></div>' +
      (c.topups > 0.5 && !ro ? '<p class="wd-note">“Topped up” lines are added automatically: a buy that cost more than the cash on hand is counted as the client adding exactly the shortfall that day. Record money in and out to replace them.</p>' : '');
  }

  function feesTab(c, ro) {
    var f = c.fee || {}, t = c.terms || {};
    var steps = (f.steps || []).map(function (s) {
      var v = s.unit === 'days' ? plural(s.value, 'day') : s.key === 'gain' ? signed(s.value) : inr(s.value);
      return '<li class="wd-step' + (s.key === 'total' ? ' total' : '') + (num(s.value) === 0 && s.unit !== 'days' ? ' zero' : '') + '"><span><b>' + esc(s.label) + '</b><small>' + esc(s.formula) + '</small></span>' +
        '<span class="v pv">' + esc(v) + '</span></li>';
    }).join('');
    var due = f.overdue ? '<span class="wd-chip warn">Period ended ' + esc(day(f.next_due)) + '</span>' : '<span class="wd-chip">Period ends ' + esc(day(f.next_due)) + '</span>';
    var hwm = num(f.to_hwm) > 0.5 && t.share_pct
      ? '<p class="wd-note" style="color:var(--dn)">' + pv(esc(inr(f.to_hwm, 0))) + ' below the ' + (t.hwm ? 'high-water mark' : 'last settlement') + ' — no profit share is due until it is made back.</p>' : '';
    var receipt = '<div class="wd-receipt"><div class="wd-due"><div><small>Accrued this period</small><b class="pv">' + esc(inr(f.total)) + '</b></div>' +
      '<div style="text-align:right">' + due + '<div class="wd-muted" style="font-size:12.5px;margin-top:6px">' + esc(c.terms_label) + '</div></div></div>' +
      '<ol class="wd-steps">' + steps + '</ol>' + hwm +
      (ro ? '' : '<div class="wd-acts" style="margin-top:14px"><button type="button" class="wd-btn primary" data-act="settle" data-id="' + c.id + '">' + ic('bill') + 'Settle this period</button>' +
        '<button type="button" class="wd-btn" data-act="past" data-id="' + c.id + '">Record an earlier settlement</button></div>') + '</div>';
    var w = f.whatif || {};
    S.whatif[c.id] = { terms: t, w: w };
    var wi = '<div class="wd-panel wd-whatif" data-whatif="' + c.id + '"><h3>What if <small>nothing is saved</small></h3>' +
      '<label><span>Profit share <b data-out="share">' + num(t.share_pct) + '%</b></span><input class="wd-range" type="range" min="0" max="50" step="1" value="' + num(t.share_pct) + '" data-wi="share"></label>' +
      '<label><span>Hurdle <b data-out="hurdle">' + num(t.hurdle_pct) + '% a year</b></span><input class="wd-range" type="range" min="0" max="20" step="0.5" value="' + num(t.hurdle_pct) + '" data-wi="hurdle"></label>' +
      (t.basis === 'total' ? '<label><span>If prices moved <b data-out="move">0%</b></span><input class="wd-range" type="range" min="-30" max="30" step="1" value="0" data-wi="move"></label>' :
        '<p class="wd-note" style="margin:0 0 12px">Measured on booked profit, so price moves do not change it until a sale.</p>') +
      '<div class="wd-wiout"><small>Would be due this period</small><b class="pv" data-out="total">' + esc(inr(f.total)) + '</b><small data-out="delta">Same as now</small></div></div>';
    var hist = (c.settlements || []);
    var latest = hist.length ? hist[0].id : null;
    var list = hist.length ? '<ul class="wd-stl">' + hist.map(function (s) {
      var lvl = t.basis === 'realised' ? s.level_realised : s.level_total;
      var acts = ro ? '' : (s.status === 'due' ? '<button type="button" class="wd-btn sm" data-act="mark" data-sid="' + s.id + '">Mark paid</button>' : '') +
        (s.id === latest ? '<button type="button" class="wd-btn sm ghost" data-act="undo" data-sid="' + s.id + '">Undo</button>' : '');
      return '<li><span><b>' + esc(day(s.period_start)) + ' → ' + esc(day(s.period_end)) + '</b><small>Profit level ' + pv(esc(signed(lvl, 0))) +
        (s.paid_on ? ' · paid ' + esc(day(s.paid_on)) : '') + (s.note ? ' · ' + esc(s.note) : '') + '</small></span>' +
        '<span class="amt"><span class="pv">' + esc(inr(s.amount)) + '</span> <span class="wd-pst ' + esc(s.status) + '">' + esc(s.status === 'nil' ? 'nothing due' : s.status) + '</span></span>' +
        '<span class="acts" style="display:flex;gap:6px;justify-content:flex-end">' + acts + '</span></li>';
    }).join('') + '</ul>' : '<p class="wd-muted" style="margin:0">No settlements yet. ' + (ro ? '' : 'When you bill this client, settle the period here — it becomes the high-water mark the next period is measured from.') + '</p>';
    return '<div class="wd-feegrid">' + receipt + wi + '</div>' +
      '<div class="wd-panel" style="margin-top:16px"><h3>Settlements <small>' + plural(hist.length, 'period') + '</small></h3>' + list + '</div>' +
      (ro ? '' : '<p class="wd-note">' + esc(S.book.fee_note) + '</p>');
  }

  function wireWhatIf() {
    document.querySelectorAll('[data-whatif]').forEach(function (box) {
      var st = S.whatif[box.dataset.whatif];
      if (!st || box._wired) return;
      box._wired = true;
      function run() {
        var share = +(box.querySelector('[data-wi=share]') || {}).value || 0;
        var hurdle = +(box.querySelector('[data-wi=hurdle]') || {}).value || 0;
        var mvEl = box.querySelector('[data-wi=move]'), mv = mvEl ? +mvEl.value : 0;
        var t = Object.assign({}, st.terms, { share_pct: share, hurdle_pct: hurdle });
        var w = st.w;
        var m = feeMath(t, num(w.level) + num(w.mv) * mv / 100, num(w.base), num(w.capital_days), num(w.days));
        var base = feeMath(st.terms, num(w.level), num(w.base), num(w.capital_days), num(w.days));
        box.querySelector('[data-out=share]').textContent = share + '%';
        box.querySelector('[data-out=hurdle]').textContent = hurdle + '% a year';
        if (mvEl) box.querySelector('[data-out=move]').textContent = (mv > 0 ? '+' : '') + mv + '%';
        box.querySelector('[data-out=total]').textContent = inr(m.total);
        var d = m.total - base.total;
        box.querySelector('[data-out=delta]').textContent = Math.abs(d) < 0.5 ? 'Same as now' : (d > 0 ? signed(d) + ' more than now' : inr(-d) + ' less than now');
      }
      box.addEventListener('input', run);
    });
  }

  function profileTab(c) {
    return '<form class="wd-panel" data-form="client" data-id="' + c.id + '"><h3>Profile and terms</h3>' + clientFields(c) +
      '<div class="wd-acts" style="margin-top:14px"><button type="submit" class="wd-btn primary">' + ic('check') + 'Save changes</button><span class="wd-err" role="alert"></span></div></form>' +
      '<div class="wd-panel wd-danger" style="margin-top:16px"><h3>Remove this client</h3><p style="margin:0 0 12px;color:var(--ink-2);font-size:14px">' +
        'Deletes their profile, every trade and every settlement. To keep the record, set their status to Closed instead.</p>' +
      '<button type="button" class="wd-btn danger" data-act="del-client" data-id="' + c.id + '">' + ic('trash') + 'Delete ' + esc(c.name) + '</button></div>';
  }

  /* ── Recommendations ─────────────────────────────────────────────────── */

  function callsView() {
    var b = S.book, rs = b.rec_stats || {};
    var list = (b.recs || []).filter(function (r) {
      if (S.recFilter === 'open') return r.status === 'open';
      if (S.recFilter === 'closed') return r.status === 'closed';
      if (S.recFilter === 'hits') return r.state === 'target' || r.state === 'stop';
      return true;
    });
    var segs = [['open', 'Open'], ['hits', 'At target or stop'], ['closed', 'Closed'], ['all', 'All']];
    return '<div class="wd-sec" style="margin-top:4px"><div><h2>Recommendations</h2><p>Make a call once, book it for as many clients as acted on it — each keeps the price you recommended beside the price they got.</p></div>' +
      '<button type="button" class="wd-btn primary" data-act="new-rec">' + ic('plus') + 'New call</button></div>' +
      '<div class="wd-kpis">' + kpi('Open', rs.open || 0, (rs.closed || 0) + ' closed', 'target', 'c-violet', 0) +
        kpi('Working', (rs.working || 0) + '<small style="font-size:.5em" class="wd-muted"> of ' + (rs.judged || 0) + '</small>', 'above the price you called', 'up', 'c-green', 1) +
        kpi('Average since call', esc(pct(rs.avg_pct, 1)), rs.best ? 'best ' + esc(rs.best) + ' · worst ' + esc(rs.worst) : '—', 'call', 'c-gold', 2) +
        kpi('Targets reached', rs.targets || 0, 'still open', 'check', 'c-green', 3) +
        kpi('Stops hit', rs.stops || 0, 'still open — review them', 'alert', 'c-rose', 4) + '</div>' +
      '<div class="wd-tools"><div class="wd-seg" role="group" aria-label="Show">' + segs.map(function (s) {
        return '<button type="button" data-act="recfilter" data-v="' + s[0] + '" class="' + (S.recFilter === s[0] ? 'on' : '') + '" aria-pressed="' + (S.recFilter === s[0]) + '">' + s[1] + '</button>';
      }).join('') + '</div></div>' +
      (list.length ? '<div class="wd-recs">' + list.map(recCard).join('') + '</div>' :
        '<div class="wd-empty"><div class="wd-art">🎯</div><h3>' + ((b.recs || []).length ? 'Nothing in this list' : 'No calls yet') + '</h3>' +
        '<p>A call is a stock, a price, and — if you set them — a target and a stop. Book it for clients and every one of them is tracked against it.</p>' +
        '<button type="button" class="wd-btn primary" data-act="new-rec">' + ic('plus') + 'Make a call</button></div>') +
      '<p class="wd-note">A target or stop counts as reached when a daily close since the call crossed it, as far back as the quotes go (about six weeks); older calls are judged on today’s price.</p>';
  }

  var STATE_LABEL = { open: 'Open', near: 'Near target', target: 'Target reached', stop: 'Stop hit', closed: 'Closed' };

  function recCard(r, i) {
    var tr = r.track, track = '';
    if (tr) {
      var buy = r.action === 'buy';
      var at = buy ? tr.at : 1 - tr.at, rec = buy ? tr.rec : 1 - tr.rec;
      track = '<div class="wd-rtrack" title="Where the price sits between the stop and the target"><span class="bar"></span>' +
        '<span class="rec" style="left:' + (100 * rec).toFixed(1) + '%"></span><span class="at" style="left:' + (100 * at).toFixed(1) + '%"></span>' +
        '<span class="lo">Stop ' + esc(px(r.stop)) + '</span><span class="hi">Target ' + esc(px(r.target)) + '</span></div>';
    }
    var fills = r.fills || [];
    var who = fills.slice(0, 6).map(function (f) { return '<span class="wd-av sm c-' + esc(f.color) + '" title="' + esc(f.name + ': ' + qty(f.qty) + ' at ' + px(f.price)) + '">' + esc(initials(f.name)) + '</span>'; }).join('');
    var slip = finite(r.avg_fill) ? 100 * (r.avg_fill / r.price - 1) : null;
    return '<article class="wd-rec ' + esc(r.state) + ' wd-rise" style="--i:' + (i || 0) + '">' +
      '<div class="wd-rec-t"><div><b><span class="wd-side ' + esc(r.action) + '">' + esc(r.action.toUpperCase()) + '</span><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '" style="text-decoration:none">' + esc(r.symbol) + '</a>' + scoreChip(r.score) + '</b>' +
        '<small>' + esc(r.name || '') + (r.name ? ' · ' : '') + 'called ' + esc(day(r.on_date)) + (r.horizon ? ' · ' + esc(r.horizon) : '') + '</small></div>' +
        '<span class="wd-state ' + esc(r.state) + '">' + esc(STATE_LABEL[r.state] || r.state) + '</span></div>' +
      '<div class="wd-rec-p"><div><small>Called at</small><b>' + esc(px(r.price)) + '</b></div>' +
        '<div><small>' + (r.status === 'closed' ? 'Closed at' : 'Now') + '</small><b>' + esc(px(r.status === 'closed' ? r.close_price : r.ltp)) + '</b></div>' +
        '<div><small>Since the call</small><b class="' + tone(r.since_pct) + '">' + esc(pct(r.since_pct, 1)) + '</b></div></div>' +
      track + (r.thesis ? '<p class="wd-thesis">' + esc(r.thesis) + '</p>' : '') +
      '<div class="wd-fills">' + (fills.length ? '<span class="wd-stack">' + who + '</span><span>' + plural(fills.length, 'fill') + ' · ' + pv(esc(short(r.filled_value))) +
        (slip !== null ? ' · avg fill ' + esc(pct(slip, 2)) + ' vs call' : '') + '</span>' : '<span class="wd-muted">No client booked yet.</span>') + '</div>' +
      '<div class="wd-rec-a">' + (r.status === 'open' ? '<button type="button" class="wd-btn sm primary" data-act="book-rec" data-rid="' + r.id + '">' + ic('users') + 'Book for clients</button>' +
        '<button type="button" class="wd-btn sm" data-act="close-rec" data-rid="' + r.id + '">Close call</button>' : '') +
        '<button type="button" class="wd-btn sm ghost" data-act="edit-rec" data-rid="' + r.id + '">' + ic('edit') + 'Edit</button></div></article>';
  }

  /* ── Commission ──────────────────────────────────────────────────────── */

  function feesView() {
    var b = S.book, t = b.totals, cm = b.commission;
    var live = b.clients.filter(function (c) { return c.status !== 'closed'; });
    var sMax = Math.max.apply(null, cm.sensitivity.map(function (s) { return num(s.fee); })) || 1;
    var html = '<div class="wd-hero c-gold wd-rise" style="grid-template-columns:minmax(0,1fr)"><span class="wd-glow" aria-hidden="true"></span>' +
      '<div><p class="wd-hero-k">Commission · ' + esc(t.fy_label) + '</p><p class="wd-hero-hi">What your agreements have earned this period, before you bill it.</p>' +
      '<p class="wd-big pv" data-count="' + num(t.accrued) + '">' + esc(inr(t.accrued, 0)) + '<small>accrued</small></p></div>' +
      '<div class="wd-trio"><div><small>Billed, awaiting payment</small><b class="pv">' + esc(inr(t.due, 0)) + '</b><span>' +
        plural(cm.settlements.filter(function (s) { return s.status === 'due'; }).length, 'invoice') + '</span></div>' +
        '<div class="gold"><small>Collected this year</small><b class="pv">' + esc(inr(t.collected_fy, 0)) + '</b><span>' + esc(t.fy_label) + '</span></div>' +
        '<div><small>Billed this year</small><b class="pv">' + esc(inr(t.billed_fy, 0)) + '</b><span>' + esc(short(t.accrued_share)) + ' share + ' + esc(short(t.accrued_fixed)) + ' fixed accruing</span></div></div></div>';
    html += '<div class="wd-grid2"><div class="wd-panel"><h3>Last twelve months</h3>' + monthsHTML(cm.months) +
      '<div class="wd-key"><span><i style="background:color-mix(in srgb,var(--gold) 40%,var(--rule))"></i>Billed</span><span><i style="background:var(--gold)"></i>Received</span></div></div>' +
      '<div class="wd-panel"><h3>If the market moves <small>accrued across the book</small></h3><div class="wd-sens" role="img" aria-label="Accrued commission if every price moved">' +
        cm.sensitivity.map(function (s, i) {
          return '<div class="' + (s.move === 0 ? 'zero' : '') + '"><span class="c"><i style="height:' + (100 * num(s.fee) / sMax).toFixed(1) + '%;--i:' + i + '"></i></span>' +
            '<b class="pv">' + esc(short(s.fee)) + '</b><small>' + (s.move > 0 ? '+' : '') + s.move + '%</small></div>';
        }).join('') + '</div><p class="wd-note">Every price moved by the same amount, everything else held. A high-water mark and a hurdle make the curve bend: below them a fall costs you nothing more, above them every rupee of gain is shared.</p></div></div>';
    var rows = live.map(function (c) {
      var f = c.fee || {}, last = (c.settlements || [])[0];
      return '<tr><td><button type="button" class="wd-link" style="text-decoration:none;color:inherit" data-go="client/' + c.id + '/fees"><b class="pv">' + esc(c.name) + '</b></button><small>' + esc(termsShort(c.terms)) + '</small></td>' +
        '<td>' + esc(day(f.period_start)) + '<small>' + plural(f.days || 0, 'day') + '</small></td>' +
        '<td>' + (f.overdue ? '<span class="wd-chip warn">' + esc(day(f.next_due)) + '</span>' : esc(day(f.next_due))) + '</td>' +
        '<td class="' + tone(f.gain) + ' pv">' + esc(signed(f.gain, 0)) + (num(f.to_hwm) > 0.5 ? '<small>below the mark</small>' : '') + '</td>' +
        '<td><b class="pv">' + esc(inr(f.total, 0)) + '</b></td>' +
        '<td>' + (last ? esc(day(last.period_end)) + '<small><span class="wd-pst ' + esc(last.status) + '">' + esc(last.status === 'nil' ? 'nothing due' : last.status) + '</span></small>' : '<span class="wd-muted">Never</span>') + '</td>' +
        '<td><button type="button" class="wd-btn sm" data-act="settle" data-id="' + c.id + '">Settle</button></td></tr>';
    }).join('');
    html += '<div class="wd-sec"><div><h2>By client</h2><p>The period each client is in now, and what it has earned so far.</p></div></div>' +
      '<div class="wd-table-wrap"><table class="wd-table"><thead><tr><th scope="col">Client</th><th scope="col">Period from</th><th scope="col">Ends</th><th scope="col">New profit</th>' +
      '<th scope="col">Accrued</th><th scope="col">Last settled</th><th scope="col"><span class="wd-sr">Settle</span></th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    var segs = [['all', 'All'], ['due', 'Awaiting payment'], ['paid', 'Paid']];
    var stl = cm.settlements.filter(function (s) { return S.stlFilter === 'all' || s.status === S.stlFilter; });
    html += '<div class="wd-sec"><div><h2>Invoices</h2><p>Every period you have settled. Mark one paid when the money arrives.</p></div>' +
      '<button type="button" class="wd-btn" data-act="export" data-what="fees">' + ic('download') + 'Export CSV</button></div>' +
      '<div class="wd-tools"><div class="wd-seg" role="group" aria-label="Show">' + segs.map(function (s) {
        return '<button type="button" data-act="stlfilter" data-v="' + s[0] + '" class="' + (S.stlFilter === s[0] ? 'on' : '') + '" aria-pressed="' + (S.stlFilter === s[0]) + '">' + s[1] + '</button>';
      }).join('') + '</div></div>' +
      (stl.length ? '<div class="wd-panel" style="padding:10px"><ul class="wd-stl">' + stl.map(function (s) {
        return '<li><span style="display:flex;gap:10px;align-items:center;min-width:0"><span class="wd-av sm c-' + esc(s.client_color) + '">' + esc(initials(s.client_name)) + '</span>' +
          '<span style="min-width:0"><b class="pv">' + esc(s.client_name) + '</b><small>' + esc(day(s.period_start)) + ' → ' + esc(day(s.period_end)) + (s.paid_on ? ' · paid ' + esc(day(s.paid_on)) : '') + '</small></span></span>' +
          '<span class="amt"><span class="pv">' + esc(inr(s.amount)) + '</span> <span class="wd-pst ' + esc(s.status) + '">' + esc(s.status === 'nil' ? 'nothing due' : s.status) + '</span></span>' +
          '<span class="acts" style="display:flex;justify-content:flex-end">' + (s.status === 'due' ? '<button type="button" class="wd-btn sm" data-act="mark" data-sid="' + s.id + '">Mark paid</button>' : '') + '</span></li>';
      }).join('') + '</ul></div>' : '<div class="wd-empty"><p style="margin:0">No invoices here.</p></div>') +
      '<p class="wd-note">' + esc(b.fee_note) + '</p>';
    return html;
  }

  /* ── Desk settings ───────────────────────────────────────────────────── */

  function regOptions(cur) {
    var regs = (S.book && S.book.vocab && S.book.vocab.registrations) || (S.info && S.info.registrations) || [];
    return regs.map(function (r) { return '<option value="' + esc(r.id) + '"' + (r.id === cur ? ' selected' : '') + '>' + esc(r.label) + '</option>'; }).join('');
  }

  function deskFields(d) {
    d = d || {};
    return '<div class="wd-form">' +
      field('Your name', '<input name="display_name" required minlength="2" maxlength="60" value="' + esc(d.display_name || '') + '" autocomplete="name">') +
      field('Firm <em>optional</em>', '<input name="firm" maxlength="80" value="' + esc(d.firm || '') + '" autocomplete="organization">') +
      field('Registration', '<select name="reg_kind" data-reg>' + regOptions(d.reg_kind || 'none') + '</select>') +
      field('Registration number', '<input name="registration" maxlength="20" value="' + esc(d.registration || '') + '" placeholder="INP000000000" autocapitalize="characters">', 'Checked for its shape — INP, INA or INH and nine digits, or ARN-.') +
      '</div>';
  }

  function settingsView() {
    var b = S.book, d = b.desk;
    var notes = (d.notes || []).map(function (n) { return '<div class="wd-demo" style="border-color:var(--dn)"><span>⚠️ ' + esc(n) + '</span></div>'; }).join('');
    var prices = (b.prices || []).length ? '<ul class="wd-stl">' + b.prices.map(function (p) {
      return '<li><span><b>' + esc(p.symbol) + '</b><small>set ' + esc(day(p.as_of)) + '</small></span><span class="amt">' + esc(px(p.price)) + '</span>' +
        '<span class="acts" style="display:flex;gap:6px;justify-content:flex-end"><button type="button" class="wd-btn sm" data-act="price" data-sym="' + esc(p.symbol) + '">Change</button></span></li>';
    }).join('') + '</ul>' : '<p class="wd-muted" style="margin:0">None. Anything listed on the NSE is priced live; set a price here for an unlisted share, a fund or a bond (from a holding’s ⋯ menu).</p>';
    return '<div class="wd-sec" style="margin-top:4px"><div><h2>Your desk</h2><p>Who you are, and the terms a new client starts on.</p></div></div>' + notes +
      '<form class="wd-panel" data-form="desk"><h3>Profile</h3>' + deskFields(d) +
      '<fieldset class="wd-fieldset" style="margin-top:14px"><legend>Default terms for new clients</legend>' + termsFields(d.terms, 't_') + '</fieldset>' +
      '<div class="wd-acts" style="margin-top:14px"><button type="submit" class="wd-btn primary">' + ic('check') + 'Save</button><span class="wd-err" role="alert"></span></div>' +
      '<p class="wd-note">' + esc(b.fee_note) + '</p></form>' +
      '<div class="wd-grid2" style="margin-top:16px"><div class="wd-panel"><h3>Privacy</h3>' +
        '<label class="wd-toggle"><input type="checkbox" data-act="privacy-toggle"' + (S.priv ? ' checked' : '') + '> Hide amounts and names on this screen</label>' +
        '<p class="wd-note">For screen-sharing and working in public. Hover over a blurred figure to read it. Remembered on this browser.</p></div>' +
      '<div class="wd-panel"><h3>Export</h3><p style="margin:0 0 12px;color:var(--ink-2);font-size:14px">Spreadsheets of the whole desk, for your accountant or your own records.</p>' +
        '<div class="wd-acts"><button type="button" class="wd-btn" data-act="export" data-what="holdings">' + ic('download') + 'Holdings</button>' +
        '<button type="button" class="wd-btn" data-act="export" data-what="ledger">' + ic('download') + 'Ledger</button>' +
        '<button type="button" class="wd-btn" data-act="export" data-what="fees">' + ic('download') + 'Fees</button></div></div></div>' +
      '<div class="wd-panel" style="margin-top:16px"><h3>Hand-set prices</h3>' + prices + '</div>' +
      '<div class="wd-panel wd-danger" style="margin-top:16px"><h3>Close this desk</h3><p style="margin:0 0 12px;color:var(--ink-2);font-size:14px">' +
        'Deletes the desk and everything on it — every client, trade, call and settlement. Export first if you want a copy. This cannot be undone.</p>' +
        '<button type="button" class="wd-btn danger" data-act="del-desk">' + ic('trash') + 'Delete the desk</button></div>' +
      '<p class="wd-note">' + esc(b.disclaimer) + '</p>';
  }

  /* ── Shared with me (a client's own view) ────────────────────────────── */

  function mineView() {
    var list = S.shared || [];
    if (!list.length) return '<div class="wd-empty"><p style="margin:0">Nobody has shared a portfolio with you.</p></div>';
    var idx = Math.min(S.mine, list.length - 1), p = list[idx];
    var pick = list.length > 1 ? '<div class="wd-tools"><div class="wd-seg">' + list.map(function (x, i) {
      return '<button type="button" data-act="mine" data-v="' + i + '" class="' + (i === idx ? 'on' : '') + '">' + esc(x.desk.display_name) + '</button>';
    }).join('') + '</div></div>' : '';
    var d = p.desk;
    return pick + '<div class="wd-demo" style="border-style:solid"><span>' + ic('lock') + ' <b>' + esc(d.display_name) + '</b>' + (d.firm ? ' · ' + esc(d.firm) : '') +
      (d.reg_short ? ' · ' + esc(d.reg_short) + ' ' + esc(d.registration) : '') + ' shares this portfolio with you. It is read-only, and only you can see it.</span></div>' +
      clientView(p.client, true);
  }

  function portalFrame() {
    var me = (auth() && auth().user && auth().user()) || {};
    return '<header class="wd-bar"><span class="wd-mono" aria-hidden="true">' + esc(String(me.email || 'Y').charAt(0).toUpperCase()) + '</span>' +
      '<div class="wd-who"><p class="wd-kick">Your portfolio</p><h1>Managed for you</h1><small>' + esc(me.email || '') + '</small></div>' +
      '<div class="wd-bar-r"><button type="button" class="wd-ic" data-act="privacy" aria-pressed="' + S.priv + '" aria-label="Hide or show amounts">' + ic(S.priv ? 'eyeoff' : 'eye') + '</button>' +
      '<button type="button" class="wd-btn" data-act="start-setup">I manage money — set up a desk</button></div></header>' +
      '<section id="wd-view">' + (S.shared ? mineView() : '<div class="wd-skel"><i style="height:300px"></i></div>') + '</section>';
  }

  /* ── Landing, setup, failure ─────────────────────────────────────────── */

  function landing() {
    S.mode = 'landing';
    var root = $('wd');
    root.classList.remove('wd-private');
    root.innerHTML = '<section class="wd-land">' +
      '<div><p class="wd-kick">Altaha Wealth desk · for portfolio managers</p>' +
        '<h1>Every client. Every holding. <em>Your commission,</em> to the rupee.</h1>' +
        '<p class="lede">Keep each client’s portfolio live, with the price you recommended beside the price they bought at. ' +
        'Book one call for many clients at once. Profit-share fees are worked out for you — high-water mark, hurdle, fixed fee and GST — with every step shown, ready to settle and mark paid.</p>' +
        '<div class="wd-land-cta"><a class="wd-btn primary" href="signin.html?next=wealth.html">' + ic('lock') + 'Sign in to open your desk</a>' +
        '<a class="wd-btn" href="wealth.html?demo=1">' + ic('spark') + 'Explore a sample desk</a></div>' +
        '<p class="wd-note">Free. Your book is private to your account — a client sees their own portfolio only if you switch that on.</p></div>' +
      '<div class="wd-stage" aria-hidden="true">' +
        '<div class="wd-float f1 dark c-gold"><p class="wd-kick" style="color:#F2D58A">Book value</p><p class="wd-big" style="font-size:44px">₹7,62,56,240</p>' +
          '<div class="wd-hero-sub"><span class="wd-pill up">▲ +₹1,24,800 today</span><span class="wd-pill">42 clients</span></div></div>' +
        '<div class="wd-float f2 c-rose"><div class="wd-card-top"><span class="wd-av">AK</span><span class="wd-card-n"><b>Ayesha Kapoor</b><small>AK-01 · Mumbai</small></span></div>' +
          '<div class="wd-card-v" style="margin-top:10px"><b>₹28.9 L</b><span class="ret up">+15.4%</span></div>' + spark([10, 12, 11, 14, 13, 16, 18, 17, 20, 22]) + '</div>' +
        '<div class="wd-float f3"><p class="wd-kick">Your share this quarter</p><ol class="wd-steps" style="margin-top:6px">' +
          '<li class="wd-step"><span><b>New profit</b><small>₹3,85,141 − ₹3,00,410</small></span><span class="v">₹84,731</span></li>' +
          '<li class="wd-step"><span><b>Hurdle 8%</b><small>₹25,00,000 × 36/365</small></span><span class="v">₹19,726</span></li>' +
          '<li class="wd-step total"><span><b>20% share</b></span><span class="v">₹13,001</span></li></ol></div>' +
      '</div></section>' +
      '<div class="wd-feats">' +
        feat('users', 'Client by client', 'Holdings, cash, profit, XIRR and a thirty-session chart for each client — and the whole book at a glance.') +
        feat('target', 'Recommended vs bought', 'Every holding shows the price you called and the price the client got, and how each call has done since.') +
        feat('coins', 'Profit share, worked out', 'High-water mark, hard or soft hurdle, fixed fee, GST, booked or on-paper — with the working shown, settled and tracked to paid.') +
      '</div>';
  }

  function feat(icon, h, p) {
    return '<div class="wd-feat"><span class="ic">' + ic(icon) + '</span><h3>' + esc(h) + '</h3><p>' + esc(p) + '</p></div>';
  }

  function failView(msg) {
    var root = $('wd');
    root.innerHTML = '<div class="wd-empty" style="margin-top:20px"><div class="wd-art">🌥️</div><h3>The desk did not open</h3><p>' + esc(msg) + '</p>' +
      '<button type="button" class="wd-btn primary" data-act="retry">Try again</button></div>';
  }

  function setupView() {
    S.mode = 'setup';
    var root = $('wd'), st = S.setup, step = S.step;
    var me = (auth() && auth().user && auth().user()) || {};
    var terms = st.terms || (S.info && S.info.default_terms) || { share_pct: 20, hurdle_pct: 0, hurdle_type: 'hard', hwm: true, fixed_pct: 0, basis: 'total', gst_pct: 0, period: 'quarterly' };
    var body = step === 1
      ? '<h3>About you</h3><p class="wd-muted" style="margin:-6px 0 14px">This is how your desk and your clients’ statements are headed.</p>' + deskFields(st)
      : '<h3>How you charge</h3><p class="wd-muted" style="margin:-6px 0 14px">The terms a new client starts on. You can change them for any client later.</p>' + termsFields(terms, 't_') +
        '<p class="wd-note">' + esc((S.info && S.info.fee_note) || '') + '</p>';
    root.innerHTML = '<div class="wd-setup wd-rise"><p class="wd-kick">Set up your wealth desk · step ' + step + ' of 2</p>' +
      '<h1 style="font:400 clamp(36px,5vw,54px)/1.05 \'Instrument Serif\',Georgia,serif;margin:6px 0 10px">' + (step === 1 ? 'Your book, in one place.' : 'Your commission, worked out.') + '</h1>' +
      '<p class="wd-muted" style="margin:0 0 16px">Signed in as ' + esc(me.email || '') + '. Only you will see your clients.</p>' +
      '<div class="wd-steps-top"><i class="on"></i><i class="' + (step === 2 ? 'on' : '') + '"></i></div>' +
      '<form class="wd-panel" data-form="setup">' + body +
        '<div class="wd-acts" style="margin-top:16px">' + (step === 2 ? '<button type="button" class="wd-btn" data-act="setup-back">' + ic('back') + 'Back</button>' : '') +
        '<button type="submit" class="wd-btn primary">' + (step === 1 ? 'Next' : ic('check') + 'Open my desk') + '</button><span class="wd-err" role="alert"></span></div></form>' +
      '<p class="wd-note" style="text-align:center">Want to look around first? <a class="wd-link" href="wealth.html?demo=1">Open the sample desk</a>.</p></div>';
    wireTerms(root);
  }

  /* ── Forms ───────────────────────────────────────────────────────────── */

  function field(label, input, hint, cls) {
    return '<label class="wd-f' + (cls ? ' ' + cls : '') + '"><span>' + label + '</span>' + input + (hint ? '<small>' + esc(hint) + '</small>' : '') + '</label>';
  }
  function opt(v, label, cur) { return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(label) + '</option>'; }

  function termsFields(t, p) {
    t = t || {};
    p = p || '';
    return '<div class="wd-form" data-terms>' +
      field('Profit share', '<input name="' + p + 'share_pct" inputmode="decimal" value="' + esc(t.share_pct != null ? t.share_pct : 20) + '">', '% of profit. 0 for none.') +
      field('Fixed fee', '<input name="' + p + 'fixed_pct" inputmode="decimal" value="' + esc(t.fixed_pct || 0) + '">', '% a year on capital, for the days it is invested.') +
      field('Hurdle', '<input name="' + p + 'hurdle_pct" inputmode="decimal" value="' + esc(t.hurdle_pct || 0) + '">', '% a year the client keeps before any share.') +
      field('Hurdle type', '<select name="' + p + 'hurdle_type">' + opt('hard', 'Hard — share only above the hurdle', t.hurdle_type) + opt('soft', 'Soft — share on all of it once cleared', t.hurdle_type) + '</select>') +
      field('Measured on', '<select name="' + p + 'basis">' + opt('total', 'All profit — booked and on paper', t.basis) + opt('realised', 'Booked profit only', t.basis) + '</select>') +
      field('Billing period', '<select name="' + p + 'period">' + ['monthly', 'quarterly', 'half-yearly', 'yearly'].map(function (x) { return opt(x, x.charAt(0).toUpperCase() + x.slice(1), t.period || 'quarterly'); }).join('') + '</select>',
        'Periods end with the financial year: 30 Jun, 30 Sep, 31 Dec, 31 Mar.') +
      field('GST', '<select name="' + p + 'gst_pct">' + opt(0, 'No GST', t.gst_pct || 0) + opt(18, '18% — I am GST-registered', t.gst_pct || 0) + '</select>') +
      '<div class="wd-f"><span>High-water mark</span><label class="wd-toggle"><input type="checkbox" name="' + p + 'hwm"' + (t.hwm !== false ? ' checked' : '') + '> A loss must be made back before any share</label></div>' +
      '<div class="wd-ex full" data-example></div></div>';
  }

  function readTerms(fd, p) {
    p = p || '';
    function g(k) { return numv(fd.get(p + k)); }
    return { share_pct: g('share_pct') === '' ? 0 : +g('share_pct'), fixed_pct: g('fixed_pct') === '' ? 0 : +g('fixed_pct'),
             hurdle_pct: g('hurdle_pct') === '' ? 0 : +g('hurdle_pct'), hurdle_type: fd.get(p + 'hurdle_type') || 'hard',
             basis: fd.get(p + 'basis') || 'total', period: fd.get(p + 'period') || 'quarterly', gst_pct: +(fd.get(p + 'gst_pct') || 0),
             hwm: fd.get(p + 'hwm') === 'on' };
  }

  /* The example under the terms: one year, ₹10 lakh, 15% — what it earns. */
  function wireTerms(root) {
    (root || document).querySelectorAll('[data-terms]').forEach(function (box) {
      var form = box.closest('form');
      if (!form) return;
      var p = (box.querySelector('[name$="share_pct"]').name || '').replace('share_pct', '');
      function run() {
        var t = readTerms(new FormData(form), p);
        ['share_pct', 'fixed_pct', 'hurdle_pct', 'gst_pct'].forEach(function (k) { if (!isFinite(t[k])) t[k] = 0; });
        var m = feeMath(t, 150000, 0, 1000000 * 365, 365);
        box.querySelector('[data-example]').innerHTML = 'On a client’s <b>₹10,00,000</b> that makes <b>15%</b> in a year, you earn <b>' + esc(inr(m.total, 0)) + '</b>' +
          (m.gst ? ' including ' + esc(inr(m.gst, 0)) + ' GST' : '') + ' and the client keeps <b>' + esc(inr(150000 - m.fee, 0)) + '</b>.' +
          (t.share_pct && !t.hwm ? ' <span style="color:var(--dn)">Without a high-water mark a client can pay twice for the same gain after a fall.</span>' : '');
      }
      form.addEventListener('input', run);
      form.addEventListener('change', run);
      run();
    });
  }

  function clientFields(c) {
    c = c || {};
    var d = (S.book && S.book.desk) || {};
    var t = c.terms || d.terms;
    return '<div class="wd-form">' +
      field('Name', '<input name="name" required minlength="2" maxlength="80" value="' + esc(c.name || '') + '" autocomplete="off">') +
      field('Client code <em>optional</em>', '<input name="code" maxlength="16" value="' + esc(c.code || '') + '" placeholder="Made for you if blank">') +
      field('Email <em>optional</em>', '<input name="email" type="email" maxlength="254" value="' + esc(c.email || '') + '" autocomplete="off">', 'Needed only to show them their portfolio.') +
      field('Phone <em>optional</em>', '<input name="phone" type="tel" maxlength="20" value="' + esc(c.phone || '') + '" autocomplete="off">') +
      field('City <em>optional</em>', '<input name="city" maxlength="40" value="' + esc(c.city || '') + '">') +
      field('Client since', '<input name="since" type="date" max="' + today() + '" value="' + esc(c.since || today()) + '">') +
      field('Risk profile', '<select name="risk">' + opt('conservative', 'Conservative', c.risk || 'moderate') + opt('moderate', 'Moderate', c.risk || 'moderate') + opt('aggressive', 'Aggressive', c.risk || 'moderate') + '</select>') +
      field('Status', '<select name="status">' + opt('active', 'Active', c.status || 'active') + opt('paused', 'Paused', c.status || 'active') + opt('closed', 'Closed — kept for the record', c.status || 'active') + '</select>') +
      '<div class="wd-f"><span>Colour</span><div class="wd-colors">' + COLORS.map(function (k) {
        return '<label class="c-' + k + '"><input type="radio" name="color" value="' + k + '"' + ((c.color || 'gold') === k ? ' checked' : '') + ' aria-label="' + k + '"><i></i></label>';
      }).join('') + '</div></div>' +
      field('Tags <em>optional</em>', '<input name="tags" maxlength="200" value="' + esc((c.tags || []).join(', ')) + '" placeholder="HNI, Family, Retirement">', 'Separated by commas.') +
      field('Private notes <em>optional</em>', '<textarea name="notes" maxlength="2000">' + esc(c.notes || '') + '</textarea>', 'Only you see these — never the client.', 'full') +
      '<fieldset class="wd-fieldset full"><legend>Fee terms</legend>' + termsFields(t, 't_') + '</fieldset>' +
      '<fieldset class="wd-fieldset full"><legend>Show the client</legend><label class="wd-toggle"><input type="checkbox" name="portal"' + (c.portal ? ' checked' : '') +
        '> Let this client see their own portfolio, read-only</label><p class="wd-note">They sign in on Altaha with the email above and see their holdings, ledger and fees — not your notes, and nobody else’s portfolio.</p></fieldset>' +
      '</div>';
  }

  function readClient(fd) {
    return { name: fd.get('name'), code: fd.get('code'), email: fd.get('email'), phone: fd.get('phone'), city: fd.get('city'),
             since: fd.get('since'), risk: fd.get('risk'), status: fd.get('status'), color: fd.get('color') || 'gold',
             tags: String(fd.get('tags') || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean),
             notes: fd.get('notes'), portal: fd.get('portal') === 'on', terms: readTerms(fd, 't_') };
  }

  /* ── The modal ───────────────────────────────────────────────────────── */

  var M = null;

  function modal(o) {
    var m = $('wd-modal');
    if (!m) return;
    M = o;
    m.className = 'wd-modal' + (o.wide ? ' wide' : '');
    m.innerHTML = '<form method="dialog" novalidate>' +
      '<div class="wd-mh"><div><h3 id="wd-mt">' + o.title + '</h3>' + (o.sub ? '<p>' + o.sub + '</p>' : '') + '</div>' +
        '<button type="button" class="wd-ic" data-close aria-label="Close">✕</button></div>' +
      '<div class="wd-mb">' + o.body + '</div>' +
      '<div class="wd-mf"><span class="wd-err" role="alert"></span>' + (o.extra || '') +
        '<button type="button" class="wd-btn ghost" data-close>Cancel</button>' +
        (o.submit ? '<button type="submit" class="wd-btn ' + (o.danger ? 'danger armed' : 'primary') + '">' + o.submit + '</button>' : '') + '</div></form>';
    m.classList.toggle('c-' + (o.color || 'gold'), true);
    try { m.showModal(); } catch (e) { m.setAttribute('open', ''); }
    wireTerms(m);
    if (o.wire) o.wire(m.querySelector('form'));
    var first = m.querySelector('.wd-mb input:not([type=hidden]):not([type=checkbox]):not([type=radio]), .wd-mb select, .wd-mb textarea');
    // Focused now, not on a timer: a deferred focus fired after the reader had
    // already tapped another field and pulled the cursor back, so what they
    // typed landed in the first box ("10" became part of the stock symbol).
    if (first && !o.noFocus) { try { first.focus({ preventScroll: true }); } catch (e) {} }
  }

  function closeModal() {
    var m = $('wd-modal');
    if (m && m.open) { try { m.close(); } catch (e) { m.removeAttribute('open'); } }
    M = null;
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || !form.closest) return;
    if (form.closest('#wd-modal')) {
      e.preventDefault();
      if (!M || !M.onSubmit) return;
      var err = form.querySelector('.wd-err'), btn = form.querySelector('[type=submit]');
      err.textContent = '';
      if (btn) btn.disabled = true;
      Promise.resolve().then(function () { return M.onSubmit(new FormData(form), form); }).then(function (msg) {
        closeModal();
        if (msg !== false) return reload(typeof msg === 'string' ? msg : '');
      }).catch(function (x) {
        if (x && x.demo) { closeModal(); toast(x.message); return; }
        err.textContent = (x && x.message) || 'That did not work. Try again.';
      }).then(function () { if (btn) btn.disabled = false; });
      return;
    }
    var kind = form.dataset.form;
    if (!kind) return;
    e.preventDefault();
    var fd = new FormData(form), errEl = form.querySelector('.wd-err'), sb = form.querySelector('[type=submit]');
    if (errEl) errEl.textContent = '';
    if (sb) sb.disabled = true;
    var job;
    if (kind === 'setup') job = setupSubmit(fd);
    else if (kind === 'desk') {
      job = api('/wealth/desk', { method: 'PUT', body: { display_name: fd.get('display_name'), firm: fd.get('firm'), reg_kind: fd.get('reg_kind'),
        registration: fd.get('registration'), terms: readTerms(fd, 't_') } }).then(function () { return reload('Desk saved.'); });
    } else if (kind === 'client') {
      job = api('/wealth/clients/' + form.dataset.id, { method: 'PUT', body: readClient(fd) }).then(function () { return reload('Saved.'); });
    }
    if (!job) return;
    job.catch(function (x) {
      if (x && x.demo) { toast(x.message); return; }
      if (errEl) errEl.textContent = x.message;
      else toast(x.message, true);
    }).then(function () { if (sb) sb.disabled = false; });
  });

  function setupSubmit(fd) {
    if (S.step === 1) {
      var name = String(fd.get('display_name') || '').trim();
      if (name.length < 2) return Promise.reject(new Error('Your name: at least two characters.'));
      S.setup = Object.assign(S.setup, { display_name: name, firm: fd.get('firm'), reg_kind: fd.get('reg_kind'), registration: fd.get('registration') });
      var kind = S.setup.reg_kind;
      var pat = { pms: /^INP\d{9}$/i, ria: /^INA\d{9}$/i, ra: /^INH\d{9}$/i, mfd: /^ARN-\d{1,7}$/i }[kind];
      if (pat && !pat.test(String(S.setup.registration || '').replace(/\s/g, ''))) {
        var hint = { pms: 'INP followed by nine digits', ria: 'INA followed by nine digits', ra: 'INH followed by nine digits', mfd: 'ARN- followed by its digits' }[kind];
        return Promise.reject(new Error('Registration number: ' + hint + '.'));
      }
      S.step = 2;
      setupView();
      return Promise.resolve();
    }
    S.setup.terms = readTerms(fd, 't_');
    return api('/wealth/desk', { method: 'PUT', body: S.setup }).then(function () {
      if (window.AltahaTrack) window.AltahaTrack('wealth_desk_created', {});
      S.step = 1;
      location.hash = '#overview';
      readHash();
      return loadBook(false).then(function () {
        toast('Your desk is open. Add your first client.');
        setTimeout(function () { clientModal(null); }, 500);
      });
    });
  }

  /* ── Modals, one per action ──────────────────────────────────────────── */

  function clientModal(c) {
    var stmt = null;
    var start = c ? '' : '<fieldset class="wd-fieldset full" style="margin-bottom:6px"><legend>Start from a holdings statement · optional</legend>' +
      '<label class="wd-drop sm"><input type="file" name="statement" accept=".xlsx,.csv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden>' +
      '<span class="wd-drop-ic">' + ic('in') + '</span><b data-stmt>Choose the client’s statement (.xlsx or .csv)</b><small>Fills in the name; you review the holdings after the client is added.</small></label></fieldset>';
    modal({
      title: c ? 'Edit ' + esc(c.name) : 'Add a client', wide: true, submit: c ? 'Save' : ic('plus') + 'Add client',
      sub: c ? '' : 'A name is enough to start. Fee terms start from your desk’s defaults.',
      body: start + clientFields(c),
      wire: function (form) {
        if (!form.statement) return;
        form.statement.addEventListener('change', function () {
          var f = form.statement.files[0], label = form.querySelector('[data-stmt]');
          if (!f) return;
          label.textContent = 'Reading ' + f.name + '…';
          readStatement(f).then(function (st) {
            if (!st.holdings.length) throw new Error('No holdings found in ' + f.name + '.');
            stmt = st;
            if (st.meta.client && !String(form.name.value).trim()) form.name.value = titleCase(st.meta.client);
            if (st.meta.as_of && form.since && form.since.value === today()) form.since.value = st.meta.as_of;
            label.textContent = plural(st.holdings.length, 'holding') + (st.meta.as_of ? ', as on ' + day(st.meta.as_of) : '') + ' — reviewed after the client is added.';
          }).catch(function (e) { stmt = null; label.textContent = e.message; });
        });
      },
      onSubmit: function (fd) {
        var body = readClient(fd);
        if (c) return api('/wealth/clients/' + c.id, { method: 'PUT', body: body }).then(function () { return 'Saved.'; });
        return api('/wealth/clients', { method: 'POST', body: body }).then(function (d) {
          S.after = 'client/' + d.client.id;
          if (stmt) {
            var st = stmt;
            S.then = function () {
              var nc = clientById(d.client.id);
              if (nc) resolveStatement(st).then(function (x) { reviewModal(nc, x); }).catch(function (e) { toast(e.message, true); });
            };
            return d.client.name + ' added. Review the holdings from the statement.';
          }
          return d.client.name + ' added. Record what they hold.';
        });
      }
    });
  }

  function universe() {
    if (S.uni) return Promise.resolve(S.uni);
    var cached = readJSON(UNI_KEY);
    if (cached && Array.isArray(cached.rows) && cached.rows.length) { S.uni = cached.rows; return Promise.resolve(S.uni); }
    return fetch(API + '/universe').then(function (r) { return r.ok ? r.json() : { rows: [] }; }).then(function (d) {
      S.uni = (d && d.rows) || [];
      try { localStorage.setItem(UNI_KEY, JSON.stringify({ day: today(), rows: S.uni })); } catch (e) {}
      return S.uni;
    }).catch(function () { return []; });
  }

  function fillSymbols() {
    var dl = $('wd-syms');
    if (!dl || dl.childElementCount) return;
    var seen = {}, html = '';
    clients().forEach(function (c) { c.holdings.forEach(function (h) { if (!seen[h.symbol]) { seen[h.symbol] = 1; html += '<option value="' + esc(h.symbol) + '">' + esc(h.name || '') + '</option>'; } }); });
    dl.innerHTML = html;
    universe().then(function (rows) {
      var more = '';
      rows.forEach(function (r) {
        var s = String(r.s || r.symbol || '');
        if (s && !seen[s]) { seen[s] = 1; more += '<option value="' + esc(s) + '">' + esc(r.n || r.name || '') + '</option>'; }
      });
      dl.insertAdjacentHTML('beforeend', more);
    });
  }

  var EVKINDS = [['buy', 'Buy'], ['sell', 'Sell'], ['deposit', 'Money in'], ['withdrawal', 'Money out'], ['dividend', 'Dividend'], ['split', 'Bonus / split']];

  function eventModal(c, kind, sym, ev) {
    fillSymbols();
    if (ev) { kind = ev.kind; sym = ev.symbol; }
    var autoPick = !ev;
    var open = (S.book.recs || []).filter(function (r) { return r.status === 'open'; });
    var held = {};
    c.holdings.forEach(function (h) { held[h.symbol] = h.qty; });
    var body = '<div class="wd-kinds" role="radiogroup" aria-label="What happened">' + EVKINDS.map(function (k) {
      return '<label><input type="radio" name="kind" value="' + k[0] + '"' + (k[0] === kind ? ' checked' : '') + '><span>' + k[1] + '</span></label>';
    }).join('') + '</div>' +
      '<div class="wd-form">' +
      field('Stock', '<input name="symbol" list="wd-syms" autocapitalize="characters" spellcheck="false" maxlength="20" value="' + esc(sym || '') + '" placeholder="e.g. TCS">', '', 'ev-sym') +
      field('Quantity', '<input name="qty" inputmode="decimal" placeholder="Shares">', '', 'ev-trade') +
      field('Price per share', '<input name="price" inputmode="decimal" placeholder="₹">', '', 'ev-trade') +
      field('Recommendation <em>optional</em>', '<select name="rec_id"><option value="">None</option></select>', 'Links the trade to your call.', 'ev-trade') +
      field('Recommended price <em>optional</em>', '<input name="rec_price" inputmode="decimal" placeholder="₹ — what you told them to pay">', '', 'ev-trade') +
      field('Charges <em>optional</em>', '<input name="charges" inputmode="decimal" placeholder="Brokerage, STT…">', '', 'ev-trade') +
      field('Amount', '<input name="amount" inputmode="decimal" placeholder="₹">', '', 'ev-money') +
      field('Every old share became', '<select name="factor">' + opt('2', '2 — a 1:1 bonus, or a 2-for-1 split', '2') + opt('1.5', '1.5 — a 1:2 bonus', '2') + opt('3', '3 — a 2:1 bonus', '2') +
        opt('5', '5 — a 5-for-1 split', '2') + opt('10', '10 — a 10-for-1 split', '2') + opt('0.2', '0.2 — a 1-for-5 consolidation', '2') + '</select>', 'Yahoo adjusts past prices for these, so record them or the holding will look like a loss.', 'ev-split') +
      field('Date', '<input name="on_date" type="date" max="' + today() + '" value="' + today() + '">') +
      field('Note <em>optional</em>', '<input name="note" maxlength="200">') +
      '</div><p class="wd-note" data-hint></p>';
    modal({
      title: ev ? 'Edit this entry' : 'Add to ' + esc(c.name) + '’s ledger', color: c.color,
      sub: ev ? 'Holdings, cash, profit and fees are worked out again with the change. If it would break a later entry, nothing is saved.' : '',
      submit: ic('check') + (ev ? 'Save' : 'Add'), body: body,
      wire: function (form) {
        if (ev) {
          var set = function (n, v) { if (form[n] && v !== null && v !== undefined) form[n].value = v; };
          set('symbol', ev.symbol); set('qty', ev.kind === 'split' ? '' : ev.qty); set('price', ev.price);
          set('rec_price', ev.rec_price); set('charges', ev.charges || ''); set('amount', ev.amount);
          set('on_date', ev.on_date); set('note', ev.note);
          if (ev.kind === 'split' && form.factor) {
            if (!form.factor.querySelector('option[value="' + ev.qty + '"]')) form.factor.insertAdjacentHTML('beforeend', opt(String(ev.qty), String(ev.qty), ''));
            form.factor.value = String(ev.qty);
          }
          form.symbol.addEventListener('input', function () { autoPick = true; }, { once: true });
        }
        function show() {
          var k = form.querySelector('[name=kind]:checked').value;
          var trade = k === 'buy' || k === 'sell';
          form.querySelectorAll('.ev-sym').forEach(function (x) { x.hidden = !(trade || k === 'split'); });
          form.querySelectorAll('.ev-trade').forEach(function (x) { x.hidden = !trade; });
          form.querySelectorAll('.ev-money').forEach(function (x) { x.hidden = trade || k === 'split'; });
          form.querySelectorAll('.ev-split').forEach(function (x) { x.hidden = k !== 'split'; });
          recs();
        }
        function recs() {
          var s = String(form.symbol.value || '').trim().toUpperCase();
          var k = form.querySelector('[name=kind]:checked').value;
          var mine = open.filter(function (r) { return r.symbol === s && r.action === k; });
          var sel = form.rec_id, was = sel.value;
          sel.innerHTML = '<option value="">None</option>' + mine.map(function (r) {
            return '<option value="' + r.id + '">' + esc(r.action.toUpperCase() + ' at ' + px(r.price) + ' · ' + day(r.on_date)) + '</option>';
          }).join('');
          // Typing rebuilds the list on every keystroke; a call already chosen
          // stays chosen while it still applies, and the first one is picked
          // for you when nothing was.
          if (ev && ev.rec_id && s === ev.symbol && !mine.some(function (r) { return r.id === ev.rec_id; })) {
            var lr = recById(ev.rec_id);
            sel.insertAdjacentHTML('beforeend', '<option value="' + ev.rec_id + '">' + esc(lr ? lr.action.toUpperCase() + ' at ' + px(lr.price) + ' · ' + day(lr.on_date) : 'The linked call') + '</option>');
            mine.push({ id: ev.rec_id });
          }
          if (ev && !was && !autoPick) was = ev.rec_id ? String(ev.rec_id) : '';
          var keep = was && mine.some(function (r) { return String(r.id) === was; });
          if (keep) sel.value = was;
          else if (mine.length && autoPick) { sel.value = String(mine[0].id); sel.dispatchEvent(new Event('change')); }
          var hint = form.querySelector('[data-hint]');
          hint.innerHTML = held[s] && (k === 'sell' || k === 'split') ? esc(c.name) + ' holds <b>' + esc(qty(held[s])) + '</b> ' + esc(s) +
            (k === 'sell' ? ' · <button type="button" class="wd-link" data-all>Sell all</button>' : '') : '';
          var all = hint.querySelector('[data-all]');
          if (all) all.addEventListener('click', function () { form.qty.value = held[s]; });
        }
        form.addEventListener('change', function (e) { if (e.target.name === 'kind') show(); });
        form.symbol.addEventListener('input', recs);
        form.rec_id.addEventListener('change', function () {
          var r = recById(+form.rec_id.value);
          if (r) { form.rec_price.value = r.price; if (!form.price.value) form.price.value = r.price; }
        });
        show();
      },
      onSubmit: function (fd) {
        var k = fd.get('kind'), out = { kind: k, on_date: fd.get('on_date'), note: fd.get('note') };
        if (k === 'buy' || k === 'sell') {
          Object.assign(out, { symbol: fd.get('symbol'), qty: numv(fd.get('qty')), price: numv(fd.get('price')), charges: numv(fd.get('charges')),
                               rec_price: numv(fd.get('rec_price')) || null, rec_id: fd.get('rec_id') || null });
        } else if (k === 'split') {
          Object.assign(out, { symbol: fd.get('symbol'), qty: fd.get('factor') });
        } else out.amount = numv(fd.get('amount'));
        if (ev) {
          return api('/wealth/clients/' + c.id + '/events/' + ev.id, { method: 'PUT', body: out }).then(function (d) {
            if (d.warning) toast(d.warning);
            return d.warning ? '' : 'Saved.';
          });
        }
        return api('/wealth/clients/' + c.id + '/events', { method: 'POST', body: { events: [out] } }).then(function (d) {
          if (d.warning) toast(d.warning);
          return d.warning ? '' : 'Added.';
        });
      }
    });
  }

  /* ── Correcting a holding ───────────────────────────────────────────── */

  function holdingEditModal(c, sym) {
    var h = c.holdings.filter(function (x) { return x.symbol === sym; })[0];
    if (!h) return;
    var open = {};
    (h.lots || []).forEach(function (l) { if (l.id) open[l.id] = (open[l.id] || 0) + l.qty; });
    var buys = c.events.filter(function (e) { return e.kind === 'buy' && e.symbol === sym; }).slice().reverse();
    var split = c.events.some(function (e) { return e.kind === 'split' && e.symbol === sym; });
    var rows = buys.map(function (e) {
      var held = open[e.id] || 0;
      var tag = held > 0.0001 ? (Math.abs(held - e.qty) < 0.0001 || split ? 'Held' : 'Held ' + qty(held) + ' of ' + qty(e.qty)) : 'Sold';
      return '<tr data-eid="' + e.id + '"><td><input type="date" max="' + today() + '" data-f="on_date" value="' + esc(e.on_date) + '" aria-label="Date"></td>' +
        '<td><input inputmode="decimal" data-f="qty" value="' + esc(e.qty) + '" aria-label="Quantity"></td>' +
        '<td><input inputmode="decimal" data-f="price" value="' + esc(e.price) + '" aria-label="Buying price"></td>' +
        '<td><input inputmode="decimal" data-f="rec_price" value="' + esc(e.rec_price == null ? '' : e.rec_price) + '" placeholder="—" aria-label="Recommended price"></td>' +
        '<td><span class="wd-pst ' + (tag === 'Sold' ? 'nil' : 'paid') + '">' + esc(tag) + '</span></td></tr>';
    }).join('');
    modal({
      title: 'Edit ' + esc(sym), color: c.color, wide: true, submit: ic('check') + 'Save',
      sub: esc(c.name) + ' holds ' + esc(qty(h.qty)) + ' shares' + (h.name ? ' of ' + esc(h.name) : '') + '.',
      body: '<input type="hidden" name="pane" value="avg">' +
        '<div class="wd-seg" role="tablist" aria-label="How to edit"><button type="button" class="on" data-pane="avg" aria-selected="true">Set the average</button>' +
          '<button type="button" data-pane="each" aria-selected="false">Each purchase (' + buys.length + ')</button></div>' +
        '<div data-panel="avg"><div class="wd-form">' +
          field('Average buying price', '<input name="avg" inputmode="decimal" value="' + esc(h.avg) + '">', 'What the client paid per share, on average — the broker’s “avg. price”.') +
          field('Recommended price', '<input name="rec" inputmode="decimal" value="' + esc(h.rec_price == null ? '' : h.rec_price) + '" placeholder="—">', 'The price you told them to buy at. Leave empty to remove it.') +
        '</div><div class="wd-sum" data-prev></div>' +
        (buys.length > 1 ? '<p class="wd-note">The ' + buys.length + ' purchases this holding is made of are all corrected by the same factor, so their proportions stay as recorded. Use “Each purchase” to change one on its own.</p>' : '') +
        '</div>' +
        '<div data-panel="each" hidden><div class="wd-table-wrap"><table class="wd-table wd-lots"><thead><tr><th scope="col">Date</th><th scope="col">Qty</th>' +
          '<th scope="col">Bought at</th><th scope="col">Recommended</th><th scope="col"><span class="wd-sr">Still held</span></th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
          (split ? '<p class="wd-note">Quantities and prices as recorded on the day of each purchase, before the bonus or split since.</p>' : '') + '</div>',
      wire: function (form) {
        function prev() {
          var a = +numv(form.avg.value);
          var box = form.querySelector('[data-prev]');
          if (!a || a <= 0) { box.innerHTML = '<span>Enter a price above zero</span><b></b>'; return; }
          var cost = a * h.qty, val = h.priced ? h.ltp * h.qty : null;
          box.innerHTML = '<span>' + esc(qty(h.qty)) + ' × ' + esc(px(a)) + ' = <b class="pv">' + esc(inr(cost, 0)) + '</b> invested</span>' +
            (val !== null ? '<b class="' + tone(val - cost) + ' pv">' + esc(signed(val - cost, 0)) + ' at ' + esc(px(h.ltp)) + '</b>' : '<b></b>');
        }
        form.avg.addEventListener('input', prev);
        prev();
        form.querySelectorAll('[data-pane]').forEach(function (b) {
          b.addEventListener('click', function () {
            form.pane.value = b.dataset.pane;
            form.querySelectorAll('[data-pane]').forEach(function (x) { var on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-selected', on); });
            form.querySelectorAll('[data-panel]').forEach(function (p) { p.hidden = p.dataset.panel !== b.dataset.pane; });
          });
        });
      },
      onSubmit: function (fd, form) {
        if (fd.get('pane') === 'each') {
          var edits = [];
          form.querySelectorAll('tr[data-eid]').forEach(function (tr) {
            var e = buys.filter(function (x) { return String(x.id) === tr.dataset.eid; })[0], ch = { id: e.id }, any = false;
            tr.querySelectorAll('[data-f]').forEach(function (inp) {
              var f = inp.dataset.f, v = f === 'on_date' ? inp.value : numv(inp.value);
              var was = e[f] == null ? '' : String(e[f]);
              if (String(v) !== was && !(f !== 'on_date' && v !== '' && +v === +was)) { ch[f] = f === 'rec_price' && v === '' ? null : v; any = true; }
            });
            if (any) edits.push(ch);
          });
          if (!edits.length) return Promise.reject(new Error('Nothing was changed.'));
          return api('/wealth/clients/' + c.id + '/events', { method: 'PUT', body: { edits: edits } }).then(function (d) {
            if (d.warning) toast(d.warning);
            return d.warning ? '' : sym + ' corrected.';
          });
        }
        var body = {}, a = numv(fd.get('avg')), r = numv(fd.get('rec'));
        if (a !== '' && Math.abs(+a - h.avg) > 0.004) body.avg = a;
        if (r === '' && finite(h.rec_price)) body.rec_price = '';
        else if (r !== '' && !(finite(h.rec_price) && Math.abs(+r - h.rec_price) < 0.004)) body.rec_price = r;
        if (!Object.keys(body).length) return Promise.reject(new Error('Nothing was changed.'));
        return api('/wealth/clients/' + c.id + '/holdings/' + encodeURIComponent(sym), { method: 'PUT', body: body }).then(function (d) {
          if (d.warning) toast(d.warning);
          return d.warning ? '' : sym + ' corrected.';
        });
      }
    });
  }

  /* ── A broker's holdings statement ───────────────────────────────────── */

  function titleCase(s) {
    s = String(s || '').trim();
    return s && s === s.toUpperCase() ? s.toLowerCase().replace(/\b[a-z]/g, function (m) { return m.toUpperCase(); }) : s;
  }

  function readStatement(file) {
    var R = window.AltahaStatement;
    if (!R) return Promise.reject(new Error('The statement reader did not load. Reload the page and try again.'));
    return R.readFile(file).then(function (r) {
      var st = R.extract(r.rows, file.name);
      st.kind = r.kind;
      st.file = file.name;
      return st;
    });
  }

  function resolveStatement(st) {
    var R = window.AltahaStatement;
    var isins = st.holdings.map(function (h) { return h.isin; }).filter(Boolean);
    var lookup = isins.length && S.mode !== 'demo'
      ? api('/wealth/isin', { method: 'POST', body: { isins: isins } }).catch(function () { return { map: {} }; })
      : Promise.resolve({ map: {} });
    return Promise.all([lookup, universe()]).then(function (got) {
      var idx = R.indexUniverse(got[1]);
      st.idx = idx;
      st.rows = R.resolve(st.holdings, idx, (got[0] && got[0].map) || {});
      return st;
    });
  }

  function uploadModal(c, opts) {
    opts = opts || {};
    var accept = '.xlsx,.csv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    modal({
      title: 'Update ' + esc(c.name) + '’s portfolio', color: c.color, wide: true, noFocus: true,
      sub: 'From the holdings statement their broker gives — Groww, Zerodha, Upstox, Angel One, Dhan, ICICI Direct — or your own spreadsheet. You see every change before anything is saved.',
      body: '<label class="wd-drop" data-drop><input type="file" name="file" accept="' + accept + '" hidden>' +
          '<span class="wd-drop-ic">' + ic('in') + '</span><b>Drop the statement here, or choose a file</b>' +
          '<small>.xlsx or .csv · read on this device</small></label>' +
        '<p class="wd-err" data-status role="status"></p>' +
        '<details' + (opts.paste ? ' open' : '') + '><summary class="wd-link" style="display:inline-block;margin-bottom:8px">Or paste rows from a spreadsheet</summary>' +
          field('Rows', '<textarea name="text" rows="7" style="font-family:\'IBM Plex Mono\',monospace;font-size:13px" placeholder="Symbol, Qty, Avg price, Date, Reco price\nRELIANCE, 50, 1250.50, 03/01/2025, 1240\nTCS, 12, 3305"></textarea>',
            'A header row is recognised by its words; without one the columns are symbol, quantity, buying price, date, recommended price.', 'full') +
          '<button type="button" class="wd-btn sm" data-read>Read these rows</button></details>' +
        '<p class="wd-note">' + ic('lock') + ' The file is opened in this browser. Only each holding’s stock, quantity and prices are sent — not the name, client code or anything else in the statement.</p>',
      wire: function (form) {
        var status = form.querySelector('[data-status]'), drop = form.querySelector('[data-drop]');
        function go(p) {
          status.style.color = 'var(--mute)';
          status.textContent = 'Reading…';
          p.then(function (st) {
            if (!st.holdings.length) throw new Error('No holdings found. The file needs a column of quantities and one of stock names, symbols or ISINs.');
            status.textContent = 'Matching ' + plural(st.holdings.length, 'holding') + ' to NSE…';
            return resolveStatement(st);
          }).then(function (st) { reviewModal(c, st); }).catch(function (e) {
            status.style.color = '';
            status.textContent = e.message || 'That file could not be read.';
          });
        }
        form.file.addEventListener('change', function () { if (form.file.files[0]) go(readStatement(form.file.files[0])); });
        ['dragenter', 'dragover'].forEach(function (t) { drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
        ['dragleave', 'drop'].forEach(function (t) { drop.addEventListener(t, function () { drop.classList.remove('over'); }); });
        drop.addEventListener('drop', function (e) {
          e.preventDefault();
          var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (f) go(readStatement(f));
        });
        form.querySelector('[data-read]').addEventListener('click', function () {
          var R = window.AltahaStatement, text = form.text.value;
          if (!String(text).trim()) { status.textContent = 'Paste at least one row.'; return; }
          go(Promise.resolve().then(function () { var st = R.extract(R.parseCSV(text)); st.kind = 'paste'; return st; }));
        });
      }
    });
  }

  var PLAN_LABEL = { new: 'New', add: 'Add', more: 'More shares', fewer: 'Fewer shares', price: 'Price differs',
                     same: 'Matches', gone: 'Not in statement', error: 'Needs a price' };

  function opText(item) {
    var parts = (item.ops || []).map(function (o) {
      if (o.kind === 'buy') return 'Buy ' + qty(o.qty) + ' at ' + px(o.price);
      return 'Sell ' + qty(o.qty) + ' at ' + px(o.price) + (item.sell_price_from ? ' (' + item.sell_price_from + ')' : '');
    });
    if (item.fix_avg) parts.push('correct the buying price to ' + px(item.fix_avg));
    if (item.status === 'same') parts.push('Already matches');
    var t = parts.join(', then ');
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
  }

  function reviewModal(c, st) {
    var R = window.AltahaStatement;
    var rows = st.rows.map(function (r) { return Object.assign({}, r); });
    var held = c.holdings.length > 0;
    var P = { mode: 'sync', as_of: st.meta.as_of && st.meta.as_of <= today() ? st.meta.as_of : today(), buy_date: null,
              prices: {}, skip: {}, plan: null, seq: 0 };
    P.buy_date = held ? P.as_of : (c.since && c.since <= P.as_of ? c.since : P.as_of);
    var other = st.meta.client && !R.sameName(st.meta.client, c.name);
    var unresolved = rows.filter(function (r) { return !r.symbol; });
    var by = { isin: 0, symbol: 0, name: 0 };
    rows.forEach(function (r) { if (by[r.how] !== undefined) by[r.how]++; });
    var fixHtml = unresolved.length ? '<div class="wd-fix"><h4>' + plural(unresolved.length, 'holding') + ' to match by hand</h4>' + unresolved.map(function (r) {
      var i = rows.indexOf(r);
      return '<div class="wd-fixrow"><span><b>' + esc(r.label) + '</b><small>' + esc(qty(r.qty)) + ' at ' + esc(px(r.avg)) + (r.isin ? ' · ' + esc(r.isin) : '') + '</small></span>' +
        '<input data-sym="' + i + '" list="wd-syms" placeholder="NSE symbol" autocapitalize="characters" spellcheck="false" maxlength="20" aria-label="Symbol for ' + esc(r.label) + '">' +
        (r.candidates.length ? '<span class="wd-cands">' + r.candidates.slice(0, 4).map(function (s) { return '<button type="button" class="wd-chip" data-pick="' + i + '" data-v="' + esc(s) + '">' + esc(s) + '</button>'; }).join('') + '</span>' : '') +
        '</div>';
    }).join('') + '<p class="wd-note">Not listed on the NSE? Type any short name for it — it is added and priced by hand at the statement’s closing price, which you can change later. Leave it empty to skip it.</p></div>' : '';
    // What is sent: each matched holding's stock, quantity and prices.
    function payloadRows() {
      return rows.filter(function (r) { return r.symbol; }).map(function (r) {
        return { symbol: r.symbol, qty: r.qty, avg: r.avg, close: r.close, rec_price: r.rec };
      });
    }
    fillSymbols();
    modal({
      title: 'Review the changes', color: c.color, wide: true, submit: ic('check') + 'Update portfolio', noFocus: true,
      sub: 'Statement' + (st.meta.as_of ? ' as on <b>' + esc(day(st.meta.as_of)) + '</b>' : '') + ' · ' + plural(rows.length, 'holding') + ' read' +
        (by.isin ? ' · ' + by.isin + ' matched by ISIN' : '') + (by.name ? ' · ' + by.name + ' by name' : '') + '.',
      body: (other ? '<div class="wd-warn">' + ic('alert') + '<span>This statement is for <b>' + esc(st.meta.client) + '</b>, and this is <b>' + esc(c.name) + '</b>’s portfolio. Check it is the right file before you update.</span></div>' : '') +
        fixHtml +
        '<div class="wd-form">' +
          (held ? field('What to do', '<select name="mode">' + opt('sync', 'Update to match this statement', 'sync') + opt('add', 'Add every row as a new purchase', 'sync') + '</select>',
            'Matching buys what is new, sells what is gone, and corrects quantities and buying prices.') : '') +
          field('Statement date', '<input name="as_of" type="date" max="' + today() + '" value="' + esc(P.as_of) + '">', 'Sales are dated this day.') +
          field('New purchases dated', '<input name="buy_date" type="date" max="' + today() + '" value="' + esc(P.buy_date) + '">',
            held ? 'Usually the statement date.' : 'For a first statement, when the client started — returns and fees count from here.') +
        '</div>' +
        '<div class="wd-sum" data-summary><span>Working it out…</span><b></b></div>' +
        '<div class="wd-table-wrap"><table class="wd-table wd-plan"><thead><tr><th scope="col"><span class="wd-sr">Include</span></th><th scope="col">Stock</th>' +
          '<th scope="col">Change</th><th scope="col">Here now</th><th scope="col">Statement</th><th scope="col">What happens</th></tr></thead><tbody data-plan></tbody></table></div>',
      wire: function (form) {
        var timer = null;
        function draw() {
          var tb = form.querySelector('[data-plan]'), sum = form.querySelector('[data-summary]');
          if (!P.plan) return;
          var counts = {};
          tb.innerHTML = P.plan.items.map(function (it) {
            var on = it.include && !P.skip[it.symbol];
            if (on) counts[it.status] = (counts[it.status] || 0) + 1;
            var price = it.needs_price ? '<label class="wd-inl">Sold at <input inputmode="decimal" data-price="' + esc(it.symbol) + '" value="' + esc(P.prices[it.symbol] || '') + '" placeholder="₹"></label>' : '';
            return '<tr class="' + (on ? '' : 'off') + '"><td><input type="checkbox" data-take="' + esc(it.symbol) + '"' + (on ? ' checked' : '') +
                (it.include ? '' : ' disabled') + ' aria-label="Include ' + esc(it.symbol) + '"></td>' +
              '<td class="wd-sym"><b>' + esc(it.symbol) + '</b></td>' +
              '<td><span class="wd-ps ' + esc(it.status) + '">' + esc(PLAN_LABEL[it.status] || it.status) + '</span></td>' +
              '<td>' + (it.have ? esc(qty(it.have.qty)) + '<small>at ' + esc(px(it.have.avg)) + '</small>' : '<span class="wd-muted">—</span>') + '</td>' +
              '<td>' + (it.want ? esc(qty(it.want.qty)) + '<small>at ' + esc(px(it.want.avg)) + '</small>' : '<span class="wd-muted">—</span>') + '</td>' +
              '<td class="wd-what">' + esc(opText(it)) + (it.note ? '<small>' + esc(it.note) + '</small>' : '') + price + '</td></tr>';
          }).join('');
          var bits = ['new', 'add', 'more', 'fewer', 'price', 'gone'].filter(function (k) { return counts[k]; })
            .map(function (k) { return counts[k] + ' ' + PLAN_LABEL[k].toLowerCase(); });
          var same = P.plan.counts.same || 0;
          sum.innerHTML = '<span>' + (bits.length ? esc(bits.join(' · ')) : 'Nothing to change') + (same ? ' · ' + same + ' already match' : '') + '</span><b>' +
            (bits.length ? plural(bits.reduce(function (n, b) { return n + parseInt(b, 10); }, 0), 'holding') + ' to update' : '') + '</b>';
        }
        function local() {
          // The sample desk has nothing to compare with: show what was read.
          P.plan = { counts: {}, items: payloadRows().map(function (r) {
            return { symbol: r.symbol, status: 'new', include: true, have: null, want: { qty: r.qty, avg: r.avg },
                     ops: [{ kind: 'buy', qty: r.qty, price: r.avg }], note: '' };
          }) };
          draw();
        }
        function refresh() {
          clearTimeout(timer);
          timer = setTimeout(function () {
            var seq = ++P.seq, body = payloadRows();
            if (!body.length) { form.querySelector('[data-summary]').innerHTML = '<span>Match at least one holding to a symbol.</span><b></b>'; form.querySelector('[data-plan]').innerHTML = ''; return; }
            if (S.mode === 'demo') { local(); return; }
            api('/wealth/clients/' + c.id + '/statement/plan', { method: 'POST', body: { rows: body, mode: P.mode, as_of: P.as_of, buy_date: P.buy_date, prices: P.prices } })
              .then(function (d) { if (seq === P.seq) { P.plan = d; draw(); } })
              .catch(function (e) { if (seq === P.seq) form.querySelector('[data-summary]').innerHTML = '<span class="wd-err">' + esc(e.message) + '</span><b></b>'; });
          }, 250);
        }
        form.addEventListener('change', function (e) {
          var t = e.target;
          if (t.name === 'mode') { P.mode = t.value; refresh(); }
          else if (t.name === 'as_of') { P.as_of = t.value; refresh(); }
          else if (t.name === 'buy_date') { P.buy_date = t.value; refresh(); }
          else if (t.dataset.take) { if (t.checked) delete P.skip[t.dataset.take]; else P.skip[t.dataset.take] = 1; draw(); }
          else if (t.dataset.price) { P.prices[t.dataset.price] = numv(t.value); refresh(); }
        });
        form.addEventListener('input', function (e) {
          var t = e.target;
          if (t.dataset.sym !== undefined) { rows[+t.dataset.sym].symbol = R.cleanSymbol(t.value); refresh(); }
        });
        form.addEventListener('click', function (e) {
          var b = e.target.closest && e.target.closest('[data-pick]');
          if (!b) return;
          var inp = form.querySelector('[data-sym="' + b.dataset.pick + '"]');
          inp.value = b.dataset.v;
          rows[+b.dataset.pick].symbol = b.dataset.v;
          refresh();
        });
        refresh();
      },
      onSubmit: function () {
        if (S.mode === 'demo') return Promise.reject(Object.assign(new Error('This is the sample desk — nothing is saved. Sign in and set up your own desk to import statements.'), { demo: true }));
        if (!P.plan) return Promise.reject(new Error('The review is still being worked out.'));
        var body = payloadRows();
        // A symbol the NSE list does not know is priced by hand, at the
        // statement's closing price, so it is valued rather than left at cost.
        var manual = rows.filter(function (r) { return r.symbol && !r.how && st.idx && !st.idx.bySymbol[r.symbol] && finite(r.close); });
        var first = manual.reduce(function (p, r) {
          return p.then(function () { return api('/wealth/prices', { method: 'PUT', body: { symbol: r.symbol, price: r.close } }); });
        }, Promise.resolve());
        return first.then(function () {
          return api('/wealth/clients/' + c.id + '/statement/apply', { method: 'POST',
            body: { rows: body, mode: P.mode, as_of: P.as_of, buy_date: P.buy_date, prices: P.prices, skip: Object.keys(P.skip) } });
        }).then(function (d) {
          if (window.AltahaTrack) window.AltahaTrack('wealth_statement_applied', { holdings: d.holdings });
          if (d.warning) toast(d.warning);
          var n = (d.done.new || 0) + (d.done.add || 0), m = d.done.more || 0, f = (d.done.fewer || 0) + (d.done.gone || 0), p = d.done.price || 0;
          var parts = [];
          if (n) parts.push(n + ' added');
          if (m) parts.push(m + ' topped up');
          if (f) parts.push(f + ' sold');
          if (p) parts.push(plural(p, 'price') + ' corrected');
          return c.name + '’s portfolio updated' + (parts.length ? ': ' + parts.join(', ') : '') + '.';
        });
      }
    });
  }

  function recModal(r, closing) {
    fillSymbols();
    var body = closing
      ? '<div class="wd-form">' + field('Closed at', '<input name="close_price" inputmode="decimal" value="' + esc(r.ltp || '') + '" required>') +
          field('On', '<input name="closed_on" type="date" max="' + today() + '" value="' + today() + '">') + '</div>' +
          '<p class="wd-note">Closing a call stops it being tracked; the clients’ holdings are not touched. To sell for them, book a sell call or record the sale.</p>'
      : '<div class="wd-kinds" role="radiogroup" aria-label="Action">' + [['buy', 'Buy'], ['sell', 'Sell']].map(function (k) {
          return '<label><input type="radio" name="action" value="' + k[0] + '"' + (((r && r.action) || 'buy') === k[0] ? ' checked' : '') + '><span>' + k[1] + '</span></label>';
        }).join('') + '</div><div class="wd-form">' +
        field('Stock', '<input name="symbol" list="wd-syms" required autocapitalize="characters" spellcheck="false" maxlength="20" value="' + esc(r ? r.symbol : '') + '" placeholder="e.g. HAL">') +
        field('Recommended price', '<input name="price" inputmode="decimal" required value="' + esc(r ? r.price : '') + '" placeholder="₹">') +
        field('Target <em>optional</em>', '<input name="target" inputmode="decimal" value="' + esc(r && r.target || '') + '" placeholder="₹">') +
        field('Stop <em>optional</em>', '<input name="stop" inputmode="decimal" value="' + esc(r && r.stop || '') + '" placeholder="₹">') +
        field('Date', '<input name="on_date" type="date" max="' + today() + '" value="' + esc(r ? r.on_date : today()) + '">') +
        field('Horizon <em>optional</em>', '<input name="horizon" maxlength="40" value="' + esc(r && r.horizon || '') + '" placeholder="12–18 months">') +
        field('Why <em>optional</em>', '<textarea name="thesis" maxlength="600">' + esc(r && r.thesis || '') + '</textarea>', 'For you; a client sees the price, not this.', 'full') + '</div>';
    modal({
      title: closing ? 'Close the ' + esc(r.symbol) + ' call' : r ? 'Edit the ' + esc(r.symbol) + ' call' : 'New call', body: body,
      submit: closing ? 'Close call' : r ? 'Save' : ic('plus') + 'Make the call',
      extra: r && !closing ? '<button type="button" class="wd-btn ghost danger" data-act="del-rec" data-rid="' + r.id + '">Delete</button>' : '',
      onSubmit: function (fd) {
        if (closing) {
          return api('/wealth/recs/' + r.id, { method: 'PUT', body: { status: 'closed', close_price: numv(fd.get('close_price')), closed_on: fd.get('closed_on') } })
            .then(function () { return 'Call closed.'; });
        }
        var body2 = { symbol: fd.get('symbol'), action: fd.get('action'), price: numv(fd.get('price')), target: numv(fd.get('target')) || null,
                      stop: numv(fd.get('stop')) || null, on_date: fd.get('on_date'), horizon: fd.get('horizon'), thesis: fd.get('thesis') };
        if (r) return api('/wealth/recs/' + r.id, { method: 'PUT', body: body2 }).then(function () { return 'Saved.'; });
        return api('/wealth/recs', { method: 'POST', body: body2 }).then(function (d) {
          S.after = 'calls';
          S.then = function () { var x = recById(d.rec.id); if (x && clients().length) bookModal(x); };
          return 'Call made. Book it for the clients who acted on it.';
        });
      }
    });
  }

  function bookModal(r) {
    var sell = r.action === 'sell';
    var list = clients().filter(function (c) { return c.status !== 'closed'; });
    if (sell) list = list.filter(function (c) { return c.holdings.some(function (h) { return h.symbol === r.symbol; }); });
    if (!list.length) { toast(sell ? 'No client holds ' + r.symbol + '.' : 'Add a client first.', true); return; }
    var rows = list.map(function (c) {
      var h = c.holdings.filter(function (x) { return x.symbol === r.symbol; })[0];
      return '<div class="wd-pick c-' + esc(c.color) + '" data-cid="' + c.id + '"><input type="checkbox" aria-label="Book for ' + esc(c.name) + '" data-pick>' +
        '<span class="who"><span class="wd-av sm">' + esc(initials(c.name)) + '</span><span style="min-width:0"><b class="pv">' + esc(c.name) + '</b><small>' +
          (h ? 'holds ' + esc(qty(h.qty)) : 'cash ' + pv(esc(short(c.cash)))) + '</small></span></span>' +
        (sell ? '<input type="text" inputmode="decimal" placeholder="Qty" data-qty value="' + esc(h ? h.qty : '') + '">'
              : '<input type="text" inputmode="decimal" placeholder="₹ amount" data-amt>') +
        '<input type="text" inputmode="decimal" placeholder="' + (sell ? 'Price' : 'or qty') + '" ' + (sell ? 'data-price' : 'data-qty') + '></div>';
    }).join('');
    modal({
      title: 'Book ' + esc(r.action) + ' ' + esc(r.symbol) + ' for clients', wide: true, submit: ic('check') + 'Book', noFocus: true,
      sub: 'Called at ' + esc(px(r.price)) + '. Tick who acted on it, and how much. Every fill is checked before any is written.',
      body: '<div class="wd-form">' + field('Fill price', '<input name="price" inputmode="decimal" value="' + esc(r.price) + '">', 'What they paid. Change it per client for a different fill.') +
        field('Date', '<input name="on_date" type="date" max="' + today() + '" value="' + today() + '">') + '</div>' +
        '<div class="wd-tools" style="margin:0"><button type="button" class="wd-btn sm" data-all-pick>Tick everyone</button></div>' +
        '<div class="wd-picks">' + rows + '</div><div class="wd-sum" data-sum><span>Nobody ticked</span><b></b></div>',
      wire: function (form) {
        function sum() {
          var n = 0, tot = 0, p = +numv(form.price.value) || r.price;
          form.querySelectorAll('.wd-pick').forEach(function (row) {
            var on = row.querySelector('[data-pick]').checked;
            row.classList.toggle('on', on);
            if (!on) return;
            n++;
            var q = +numv((row.querySelector('[data-qty]') || {}).value), a = +numv((row.querySelector('[data-amt]') || {}).value);
            var pp = +numv((row.querySelector('[data-price]') || {}).value) || p;
            tot += q ? q * pp : a ? Math.floor(a / pp) * pp : 0;
          });
          var s = form.querySelector('[data-sum]');
          s.innerHTML = '<span>' + (n ? plural(n, 'client') : 'Nobody ticked') + '</span><b>' + (tot ? esc(inr(tot, 0)) : '') + '</b>';
        }
        form.addEventListener('input', function (e) {
          var row = e.target.closest('.wd-pick');
          if (row && !e.target.matches('[data-pick]') && e.target.value) row.querySelector('[data-pick]').checked = true;
          sum();
        });
        form.addEventListener('change', sum);
        form.querySelector('[data-all-pick]').addEventListener('click', function () {
          form.querySelectorAll('[data-pick]').forEach(function (x) { x.checked = true; });
          sum();
        });
      },
      onSubmit: function (fd, form) {
        var fills = [];
        form.querySelectorAll('.wd-pick').forEach(function (row) {
          if (!row.querySelector('[data-pick]').checked) return;
          var f = { client_id: +row.dataset.cid, on_date: fd.get('on_date'), price: numv(fd.get('price')) || r.price };
          var q = numv((row.querySelector('[data-qty]') || {}).value), a = numv((row.querySelector('[data-amt]') || {}).value);
          var pp = numv((row.querySelector('[data-price]') || {}).value);
          if (pp) f.price = pp;
          if (q) f.qty = q; else if (a) f.amount = a;
          fills.push(f);
        });
        if (!fills.length) return Promise.reject(new Error('Tick at least one client.'));
        return api('/wealth/recs/' + r.id + '/apply', { method: 'POST', body: { fills: fills } }).then(function (d) {
          return r.symbol + ' booked for ' + plural(d.booked.length, 'client') + '.';
        });
      }
    });
  }

  function settleModal(c) {
    var f = c.fee || {};
    modal({
      title: 'Settle ' + esc(c.name) + '’s fee', color: c.color, submit: ic('bill') + 'Settle',
      sub: 'Crystallises the period: the profit level becomes the mark the next period is measured from.',
      body: '<div class="wd-sum"><span>Due by your terms, ' + esc(day(f.period_start)) + ' → today</span><b class="pv">' + esc(inr(f.total)) + '</b></div>' +
        '<div class="wd-form">' + field('Settle as of', '<input name="as_of" type="date" max="' + today() + '" min="' + esc(f.period_start || '') + '" value="' + today() + '">',
          'A past date (a quarter end) is valued at that day’s closes — within about six weeks.') +
        field('Amount billed <em>optional</em>', '<input name="amount" inputmode="decimal" placeholder="' + esc(String(f.total)) + '">', 'Leave blank for what the terms say. Kept beside the computed figure.') +
        field('Note <em>optional</em>', '<input name="note" maxlength="200" placeholder="Invoice number, how it was paid…">', '', 'full') + '</div>',
      onSubmit: function (fd) {
        var as = fd.get('as_of');
        return api('/wealth/clients/' + c.id + '/settle', { method: 'POST', body: { as_of: as === today() ? null : as, amount: numv(fd.get('amount')) || null, note: fd.get('note') } })
          .then(function (d) { return d.settlement.status === 'nil' ? 'Period settled — nothing was due.' : 'Billed ' + inr(d.settlement.amount) + '. Mark it paid when it arrives.'; });
      }
    });
  }

  function pastModal(c) {
    modal({
      title: 'Record an earlier settlement', color: c.color, submit: ic('check') + 'Record',
      sub: 'For a client you billed before this desk existed, so those periods are not counted again.',
      body: '<div class="wd-form">' + field('Settled up to', '<input name="period_end" type="date" max="' + today() + '" required>') +
        field('Portfolio value that day', '<input name="value" inputmode="decimal" placeholder="₹ from the broker’s statement">', 'The profit level is this less the capital in by then.') +
        field('Or the profit level itself <em>optional</em>', '<input name="level" inputmode="decimal" placeholder="₹ — your high-water mark">') +
        field('Amount billed', '<input name="amount" inputmode="decimal" placeholder="₹ — 0 if nothing">') +
        field('Status', '<select name="status">' + opt('paid', 'Paid', 'paid') + opt('due', 'Not yet paid', 'paid') + '</select>') +
        field('Paid on <em>optional</em>', '<input name="paid_on" type="date" max="' + today() + '">') + '</div>',
      onSubmit: function (fd) {
        return api('/wealth/clients/' + c.id + '/past', { method: 'POST', body: { period_end: fd.get('period_end'), value: numv(fd.get('value')) || null,
          level: numv(fd.get('level')) || null, amount: numv(fd.get('amount')) || 0, status: fd.get('status'), paid_on: fd.get('paid_on') || null } })
          .then(function () { return 'Recorded. The next period starts from it.'; });
      }
    });
  }

  function markModal(sid) {
    modal({
      title: 'Mark the invoice', submit: ic('check') + 'Save',
      body: '<div class="wd-kinds" role="radiogroup">' + [['paid', 'Paid'], ['waived', 'Waived'], ['due', 'Still due']].map(function (k, i) {
        return '<label><input type="radio" name="status" value="' + k[0] + '"' + (i === 0 ? ' checked' : '') + '><span>' + k[1] + '</span></label>';
      }).join('') + '</div><div class="wd-form">' + field('Paid on', '<input name="paid_on" type="date" max="' + today() + '" value="' + today() + '">') + '</div>',
      onSubmit: function (fd) {
        return api('/wealth/settlements/' + sid, { method: 'POST', body: { status: fd.get('status'), paid_on: fd.get('paid_on') } }).then(function () { return 'Updated.'; });
      }
    });
  }

  function priceModal(sym) {
    var cur = (S.book.prices || []).filter(function (p) { return p.symbol === sym; })[0];
    modal({
      title: 'Set a price for ' + esc(sym), submit: ic('check') + 'Save',
      sub: 'For anything without a live quote — an unlisted share, a fund, a bond. A hand-set price replaces the live one everywhere on the desk until you clear it.',
      body: '<div class="wd-form">' + field('Price per unit', '<input name="price" inputmode="decimal" value="' + esc(cur ? cur.price : '') + '" placeholder="₹">') + '</div>',
      extra: cur ? '<button type="button" class="wd-btn ghost danger" data-act="clear-price" data-sym="' + esc(sym) + '">Clear — use live</button>' : '',
      onSubmit: function (fd) {
        return api('/wealth/prices', { method: 'PUT', body: { symbol: sym, price: numv(fd.get('price')) } }).then(function () { return sym + ' priced by hand.'; });
      }
    });
  }

  function splitModal(c, sym) {
    modal({
      title: 'Bonus or split in ' + esc(sym), submit: ic('check') + 'Apply',
      sub: 'Yahoo adjusts its past prices for these, so without one a holding bought before it looks like a loss.',
      body: '<div class="wd-form">' + field('Every old share became', '<select name="factor">' + opt('2', '2 — a 1:1 bonus, or a 2-for-1 split', '2') + opt('1.5', '1.5 — a 1:2 bonus', '2') +
          opt('3', '3 — a 2:1 bonus', '2') + opt('5', '5 — a 5-for-1 split', '2') + opt('10', '10 — a 10-for-1 split', '2') + opt('0.2', '0.2 — a 1-for-5 consolidation', '2') + '</select>') +
        field('Ex-date', '<input name="on_date" type="date" max="' + today() + '" value="' + today() + '">') + '</div>' +
        '<label class="wd-toggle"><input type="checkbox" name="all" checked> Apply to every client who held ' + esc(sym) + ' that day</label>',
      onSubmit: function (fd) {
        if (fd.get('all') === 'on') {
          return api('/wealth/corporate-action', { method: 'POST', body: { symbol: sym, factor: fd.get('factor'), on_date: fd.get('on_date') } })
            .then(function (d) { return 'Applied for ' + plural(d.clients.length, 'client') + '.'; });
        }
        return api('/wealth/clients/' + c.id + '/events', { method: 'POST', body: { events: [{ kind: 'split', symbol: sym, qty: fd.get('factor'), on_date: fd.get('on_date') }] } })
          .then(function () { return 'Applied.'; });
      }
    });
  }

  function holdingMenu(c, sym) {
    var h = c.holdings.filter(function (x) { return x.symbol === sym; })[0];
    if (!h) return;
    var b = function (act, icon, label) { return '<button type="button" class="wd-btn" style="justify-content:flex-start" data-act="' + act + '" data-id="' + c.id + '" data-sym="' + esc(sym) + '">' + ic(icon) + label + '</button>'; };
    modal({
      title: esc(sym), color: c.color, sub: esc((h.name || '') + ' · ' + qty(h.qty) + ' shares · ' + inr(h.value, 0)),
      body: '<div style="display:grid;gap:8px">' + b('edit-hold', 'edit', 'Edit buying or recommended price') +
        b('h-buy', 'up', 'Buy more') + b('h-sell', 'down', 'Sell') + b('h-split', 'split', 'Bonus or split') +
        b('price', 'rupee', h.price_source === 'manual' ? 'Change the hand-set price' : 'Set a price by hand') +
        '<a class="wd-btn" style="justify-content:flex-start" href="stock.html?ticker=' + encodeURIComponent(sym) + '">' + ic('call') + 'Open the stock page</a></div>'
    });
  }

  function confirmModal(title, text, label, fn) {
    modal({ title: title, body: '<p style="margin:0;color:var(--ink-2)">' + text + '</p>', submit: label, danger: true, onSubmit: fn });
  }

  /* ── The statement ───────────────────────────────────────────────────── */

  function statement(c, desk) {
    var f = c.fee || {}, t = c.terms || {};
    var html = '<div class="ph"><div><small>' + esc(desk.firm || '') + (desk.reg_short ? ' · ' + esc(desk.reg_short) + ' ' + esc(desk.registration || '') : '') + '</small>' +
      '<h1>' + esc(c.name) + '</h1><small>' + esc(c.code) + ' · client since ' + esc(day(c.since)) + '</small></div>' +
      '<div style="text-align:right"><b>Portfolio statement</b><br><small>As of ' + esc(day(S.book ? S.book.as_of : today())) + '<br>Prepared by ' + esc(desk.display_name || '') + '</small></div></div>' +
      '<div class="sum"><div><small>Value</small><b>' + esc(inr(c.value, 0)) + '</b></div><div><small>Capital in</small><b>' + esc(inr(c.capital, 0)) + '</b></div>' +
      '<div><small>Profit</small><b>' + esc(signed(c.profit, 0)) + '</b></div><div><small>Return · XIRR</small><b>' + esc(pct(c.profit_pct, 1)) + ' · ' + (c.xirr == null ? '—' : esc(pct(c.xirr, 1))) + '</b></div></div>' +
      '<h2>Holdings</h2><table><thead><tr><th>Stock</th><th>Qty</th><th>Recommended</th><th>Bought at</th><th>Price</th><th>Value</th><th>P&amp;L</th><th>Weight</th></tr></thead><tbody>' +
      c.holdings.map(function (h) {
        return '<tr><td>' + esc(h.symbol) + '</td><td>' + esc(qty(h.qty)) + '</td><td>' + (finite(h.rec_price) ? esc(px(h.rec_price)) : '—') + '</td><td>' + esc(px(h.avg)) + '</td>' +
          '<td>' + (h.priced ? esc(px(h.ltp)) : 'at cost') + '</td><td>' + esc(inr(h.value, 0)) + '</td><td>' + esc(signed(h.pnl, 0)) + ' (' + esc(pct(h.pnl_pct, 1)) + ')</td><td>' + (finite(h.weight) ? h.weight.toFixed(1) + '%' : '') + '</td></tr>';
      }).join('') + (num(c.cash) > 0.5 ? '<tr><td>Cash</td><td></td><td></td><td></td><td></td><td>' + esc(inr(c.cash, 0)) + '</td><td></td><td></td></tr>' : '') + '</tbody></table>' +
      '<h2>Fee for the current period</h2><p>' + esc(t ? c.terms_label : '') + '</p><table><tbody>' + (f.steps || []).map(function (s) {
        return '<tr><td>' + esc(s.label) + '<br><small style="color:#777">' + esc(s.formula) + '</small></td><td>' + (s.unit === 'days' ? esc(plural(s.value, 'day')) : esc(inr(s.value))) + '</td></tr>';
      }).join('') + '</tbody></table>';
    if ((c.settlements || []).length) {
      html += '<h2>Settlements</h2><table><thead><tr><th>Period</th><th>Billed</th><th>Status</th></tr></thead><tbody>' + c.settlements.map(function (s) {
        return '<tr><td>' + esc(day(s.period_start)) + ' → ' + esc(day(s.period_end)) + '</td><td>' + esc(inr(s.amount)) + '</td><td>' + esc(s.status === 'nil' ? 'nothing due' : s.status) + (s.paid_on ? ' ' + esc(day(s.paid_on)) : '') + '</td></tr>';
      }).join('') + '</tbody></table>';
    }
    html += '<p class="fine">Prices are delayed daily closes. Return is profit on time-weighted capital; XIRR is annualised and money-weighted. ' +
      'This statement was prepared by your portfolio manager using Altaha Screener, which does not advise on or hold your money.</p>';
    return html;
  }

  function printStatement(c, desk) {
    var p = $('wd-print');
    if (!p) return;
    p.innerHTML = statement(c, desk);
    document.body.classList.add('wd-printing');
    var done = function () { document.body.classList.remove('wd-printing'); window.removeEventListener('afterprint', done); };
    window.addEventListener('afterprint', done);
    setTimeout(function () { try { window.print(); } catch (e) {} setTimeout(done, 1500); }, 60);
  }

  function exportCsv(what) {
    if (S.mode === 'demo') { toast('The sample desk has nothing to export. Sign in to set up your own.'); return; }
    api('/wealth/export.csv?what=' + encodeURIComponent(what), { raw: true }).then(function (r) { return r.blob(); }).then(function (blob) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'wealth-' + what + '-' + today() + '.csv';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    }).catch(function (e) { toast(e.message, true); });
  }

  /* ── Clicks ──────────────────────────────────────────────────────────── */

  function setPrivacy(on) {
    S.priv = !!on;
    setLocal(PRIV_KEY, S.priv ? '1' : '');
    var root = $('wd');
    if (root) root.classList.toggle('wd-private', S.priv);
    document.querySelectorAll('[data-act=privacy]').forEach(function (b) {
      b.setAttribute('aria-pressed', S.priv);
      b.innerHTML = ic(S.priv ? 'eyeoff' : 'eye');
    });
    var t = document.querySelector('[data-act=privacy-toggle]');
    if (t) t.checked = S.priv;
  }

  function act(el) {
    var a = el.dataset.act, id = +el.dataset.id, c = id ? clientById(id) : null;
    if (S.mode === 'portal' && S.shared && a === 'statement') {
      var p = S.shared[Math.min(S.mine, S.shared.length - 1)];
      printStatement(p.client, p.desk);
      return;
    }
    switch (a) {
      case 'retry': location.reload(); return;
      case 'privacy': setPrivacy(!S.priv); return;
      case 'privacy-toggle': setPrivacy(el.checked); return;
      case 'add-client': clientModal(null); return;
      case 'new-rec': recModal(null); return;
      case 'add-event': if (c) eventModal(c, el.dataset.kind || 'buy'); return;
      case 'import': if (c) uploadModal(c, { paste: true }); return;
      case 'upload': if (c) uploadModal(c); return;
      case 'edit-hold': closeModal(); if (c) holdingEditModal(c, el.dataset.sym); return;
      case 'edit-event': {
        if (!c) return;
        var evx = c.events.filter(function (x) { return String(x.id) === String(el.dataset.eid); })[0];
        if (evx) eventModal(c, evx.kind, evx.symbol, evx);
        return;
      }
      case 'settle': if (c) settleModal(c); return;
      case 'past': if (c) pastModal(c); return;
      case 'statement':
        if (c) printStatement(c, S.book.desk);
        else if (S.view === 'mine' && S.shared) { var q = S.shared[Math.min(S.mine, S.shared.length - 1)]; printStatement(q.client, q.desk); }
        return;
      case 'hold': if (c) holdingMenu(c, el.dataset.sym); return;
      case 'h-buy': closeModal(); if (c) eventModal(c, 'buy', el.dataset.sym); return;
      case 'h-sell': closeModal(); if (c) eventModal(c, 'sell', el.dataset.sym); return;
      case 'h-split': closeModal(); if (c) splitModal(c, el.dataset.sym); return;
      case 'price': closeModal(); priceModal(el.dataset.sym); return;
      case 'clear-price':
        api('/wealth/prices', { method: 'PUT', body: { symbol: el.dataset.sym, price: null } }).then(function () { closeModal(); return reload('Back to the live price.'); })
          .catch(function (e) { toast(e.message, true); });
        return;
      case 'mark': markModal(+el.dataset.sid); return;
      case 'undo':
        confirmModal('Undo this settlement?', 'The period re-opens and is measured from the settlement before it. The invoice is removed.', 'Undo settlement', function () {
          return api('/wealth/settlements/' + el.dataset.sid, { method: 'DELETE' }).then(function () { return 'Settlement undone.'; });
        });
        return;
      case 'del-event':
        confirmModal('Remove this entry?', 'Holdings, cash, profit and fees are recalculated without it.', 'Remove', function () {
          return api('/wealth/clients/' + id + '/events/' + el.dataset.eid, { method: 'DELETE' }).then(function () { return 'Removed.'; });
        });
        return;
      case 'del-client':
        if (!c) return;
        confirmModal('Delete ' + esc(c.name) + '?', 'Every trade and settlement for this client goes too. To keep the record, set their status to Closed instead.', 'Delete for good', function () {
          return api('/wealth/clients/' + id, { method: 'DELETE' }).then(function () { S.after = 'clients'; return c.name + ' removed.'; });
        });
        return;
      case 'del-desk':
        modal({
          title: 'Delete the whole desk?', danger: true, submit: 'Delete everything',
          body: '<p style="margin:0;color:var(--ink-2)">Every client, trade, call and settlement. Export first if you want a copy. Type <b>DELETE</b> to confirm.</p>' +
            field('Confirm', '<input name="confirm" autocomplete="off" autocapitalize="characters">'),
          onSubmit: function (fd) {
            return api('/wealth/desk', { method: 'DELETE', body: { confirm: String(fd.get('confirm') || '').trim() } }).then(function () {
              S.book = null; location.hash = ''; setupView(); toast('The desk is gone.'); return false;
            });
          }
        });
        return;
      case 'book-rec': { var r = recById(+el.dataset.rid); if (r) bookModal(r); return; }
      case 'edit-rec': { var r2 = recById(+el.dataset.rid); if (r2) recModal(r2); return; }
      case 'close-rec': { var r3 = recById(+el.dataset.rid); if (r3) recModal(r3, true); return; }
      case 'del-rec':
        closeModal();
        confirmModal('Delete this call?', 'The clients’ trades stay — they happened — and keep the price you recommended. Only the call goes.', 'Delete call', function () {
          return api('/wealth/recs/' + el.dataset.rid, { method: 'DELETE' }).then(function () { return 'Call deleted.'; });
        });
        return;
      case 'export': exportCsv(el.dataset.what); return;
      case 'status': S.status = el.dataset.v; repaintCards(); segOn(el); return;
      case 'recfilter': S.recFilter = el.dataset.v; patch(); return;
      case 'stlfilter': S.stlFilter = el.dataset.v; patch(); return;
      case 'ledfilter': S.ledFilter = el.dataset.v; patch(); return;
      case 'mine': S.mine = +el.dataset.v; render(); return;
      case 'setup-back': S.step = 1; setupView(); return;
      case 'start-setup': S.step = 1; setupView(); return;
    }
  }

  function segOn(el) {
    var seg = el.closest('.wd-seg');
    if (!seg) return;
    seg.querySelectorAll('button').forEach(function (b) { var on = b === el; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
  }

  function repaintCards() {
    var g = $('wd-cardgrid');
    if (g) g.innerHTML = clientCards();
  }

  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    if (t.closest('[data-close]')) { e.preventDefault(); closeModal(); return; }
    var m = $('wd-modal');
    if (m && m.open && t === m) { closeModal(); return; }        // a click on the backdrop
    var g = t.closest('[data-go]');
    if (g && (t.closest('#wd') || t.closest('#wd-modal'))) {
      if (t.closest('a[href]') && !t.closest('a[href]').hasAttribute('data-go')) return;
      e.preventDefault();
      closeModal();
      go(g.dataset.go);
      return;
    }
    var ct = t.closest('[data-ctab]');
    if (ct) {
      S.ctab = ct.dataset.ctab;
      if (S.view === 'mine' || S.mode === 'portal') render();
      else go('client/' + S.cid + '/' + S.ctab);
      return;
    }
    var a = t.closest('[data-act]');
    if (a && (a.closest('#wd') || a.closest('#wd-modal'))) {
      if (a.type === 'checkbox') { act(a); return; }
      e.preventDefault();
      act(a);
    }
  });

  document.addEventListener('input', function (e) {
    if (e.target && e.target.id === 'wd-q') { S.q = e.target.value; repaintCards(); }
  });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.id === 'wd-sort') { S.sort = e.target.value; repaintCards(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && S.view === 'clients' && document.activeElement === document.body) {
      var q = $('wd-q');
      if (q) { e.preventDefault(); q.focus(); }
    }
  });

  window.addEventListener('altaha-auth', function () {
    // Signing out elsewhere leaves nothing private on this screen.
    if (!signedIn() && S.mode !== 'demo' && S.mode !== 'landing') { S.book = null; S.shared = null; landing(); }
  });

  window.AltahaWealth = { reload: function () { return loadBook(false); }, state: function () { return S; }, feeMath: feeMath };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
