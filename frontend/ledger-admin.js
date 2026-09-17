/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — ledger-admin.js

   The control that fills the holdings ledger, on the site rather than in a
   CI dashboard.

   WHY A BUTTON AT ALL
   The investor and fund-house pages are assembled from a ledger, and until
   something reads the filings into it they are correct and empty. A scheduled
   workflow does that nightly, but it needs a secret set on the repository, and
   when it is not set the pages sit empty with nothing on screen explaining
   why. Being able to start the sweep from the page it feeds removes that whole
   class of problem: whoever can see the empty page can fill it.

   WHY IT STARTS A JOB RATHER THAN DOING THE WORK
   Filling the ledger is roughly two thousand documents and over an hour. A
   request that long is cut off by every proxy in between, and driving it in
   slices from the browser needs the tab left open for the duration — which on
   a phone nobody can do. So this asks the API to start a background sweep and
   then polls it. Start it, close the tab, come back.

   THE KEY NEVER TOUCHES THE PAGE'S STORAGE
   It is held in memory for the session, prompted for once, and sent as a
   header rather than in the query string — a URL ends up in access logs and
   proxy logs, which is a poor place for the credential that starts a crawl.
   Nothing here is hidden: the control is visible to anyone, and does nothing
   at all without the key the API checks.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var KEY = '';
  var timer = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function n(v) { return Number(v || 0).toLocaleString('en-IN'); }

  function key(force) {
    if (!KEY || force) {
      KEY = window.prompt(
        'Admin key — the value set as ADMIN_KEY on Render.\n\n' +
        'It is kept for this browser tab only and sent as a header, never ' +
        'stored and never put in a URL.') || '';
    }
    return KEY;
  }

  function call(path, method) {
    var k = key();
    if (!k) return Promise.reject(new Error('no key'));
    return fetch(API + path, {
      method: method || 'GET',
      headers: { 'X-Admin-Key': k }
    }).then(function (r) {
      if (r.status === 401) { KEY = ''; throw new Error('unauthorised'); }
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  /* ── The panel ─────────────────────────────────────────────────────────── */

  function render(box, s, msg) {
    var led = (s && s.ledger) || {};
    var universe = (s && s.universe) || 0;
    var read = led.companies || 0;
    var pct = universe ? Math.min(100, Math.round((led.attempted || 0) * 100 / universe)) : 0;

    var bar = universe
      ? '<div class="lg-bar"><i style="width:' + pct + '%"></i></div>' +
        '<p class="lg-num"><b>' + n(read) + '</b> of ' + n(universe) +
        ' companies read &middot; <b>' + n(led.rows) + '</b> holdings' +
        (led.latest_period ? ' &middot; to ' + esc(led.latest_period) : '') +
        '</p>'
      : '';

    var running = s && s.alive;
    var status = '';
    if (running) {
      status = '<p class="lg-status is-on">Running &mdash; ' +
        n(s.read) + ' companies this run, ' + n(s.rows) + ' holdings found' +
        (s.last_symbol ? ' &middot; at ' + esc(s.last_symbol) : '') +
        '. You can close this tab; it keeps going.</p>';
    } else if (s && s.error) {
      status = '<p class="lg-status is-bad">Stopped: ' + esc(s.error) + '</p>';
    } else if (s && s.note) {
      status = '<p class="lg-status">' + esc(s.note) + '</p>';
    }
    if (msg) status = '<p class="lg-status is-bad">' + esc(msg) + '</p>' + status;

    /* A persistence warning matters more than anything else here: a sweep that
       takes an hour and is thrown away on the next deploy is worse than not
       running it. */
    var warn = (led.persistent === false)
      ? '<p class="lg-status is-bad">This instance is not storing the ledger ' +
        'between restarts &mdash; check DATA_DIR on the server before running ' +
        'a full sweep.</p>'
      : '';

    box.innerHTML =
      '<div class="lg-head"><b>Fill the ledger</b>' +
        '<span>reads company filings into the store these pages are built from</span>' +
      '</div>' + bar + warn + status +
      '<div class="lg-btns">' +
        (running
          ? '<button type="button" class="lg-btn" data-do="stop">Stop after this slice</button>'
          : '<button type="button" class="lg-btn is-go" data-do="start">Start the sweep</button>') +
        '<button type="button" class="lg-btn" data-do="refresh">Refresh</button>' +
      '</div>' +
      '<p class="lg-fine">A full sweep is about two thousand documents and over ' +
      'an hour. It runs on the server, continues from wherever it last reached, ' +
      'and is safe to stop and start again. It also runs nightly on its own.</p>';

    box.querySelectorAll('.lg-btn').forEach(function (b) {
      b.addEventListener('click', function () { act(box, b.getAttribute('data-do')); });
    });
  }

  function act(box, what) {
    if (what === 'refresh') return poll(box);
    if (what === 'start') {
      return call('/admin/holdings/start?quarters=2', 'POST')
        .then(function (d) {
          if (!d.started) return render(box, d.state, d.reason);
          watch(box);
        })
        .catch(function (e) { fail(box, e); });
    }
    if (what === 'stop') {
      return call('/admin/holdings/stop', 'POST')
        .then(function () { poll(box); })
        .catch(function (e) { fail(box, e); });
    }
  }

  function fail(box, e) {
    var m = String(e && e.message) === 'unauthorised'
      ? 'That key was not accepted. Click Start again to re-enter it.'
      : String(e && e.message) === 'no key'
        ? 'No key entered, so nothing was started.'
        : 'The engine could not be reached. If it has been idle it takes about thirty seconds to wake.';
    render(box, null, m);
  }

  function poll(box) {
    return call('/admin/holdings/progress')
      .then(function (s) { render(box, s); return s; })
      .catch(function (e) { fail(box, e); });
  }

  /* Polls while it runs, then stops — and reloads the page's own data once,
     so the cards behind the panel fill in rather than staying stale. */
  function watch(box) {
    if (timer) clearInterval(timer);
    var wasRunning = false;
    function tick() {
      poll(box).then(function (s) {
        if (!s) return;
        if (s.alive) { wasRunning = true; return; }
        clearInterval(timer); timer = null;
        if (wasRunning && typeof window.AltahaLedgerDone === 'function') {
          try { window.AltahaLedgerDone(); } catch (_) { /* nothing */ }
        }
      });
    }
    tick();
    timer = setInterval(tick, 15000);
  }

  /* ── Mounting ──────────────────────────────────────────────────────────── */

  function mount(id) {
    var box = document.getElementById(id);
    if (!box || box.dataset.mounted) return;
    box.dataset.mounted = '1';
    render(box, null);
    // Asks for the key only when a button is pressed, so an ordinary visitor
    // is never prompted for anything.
  }

  window.AltahaLedgerAdmin = { mount: mount, poll: poll, watch: watch };

  function boot() {
    ['ledger-admin', 'ledger-admin-funds'].forEach(mount);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
