/* Altaha Screener — the home page's data, asked for first

   The home page needs a dozen answers from the server, and it used to be
   unable to ask for the first one until every script on the page had arrived:
   about three seconds of nothing. This file is the first thing in <head>. It
   asks for all of them at once (GET /boot, one request) while the rest of the
   page is still loading, and when the page's own code later asks for one of
   them, it is handed the answer that is already here.

   Nothing else on the page changes. Every caller still calls fetch() exactly
   as before and still gets a Response; if /boot is slow, missing a part, or
   fails outright, the call simply goes to the network as it always did.

   The rules, so this can never show something wrong:
     - only plain GETs to the API with no headers and no body are answered here
       (anything signed in, anything that writes, goes to the network);
     - each answer is used once, and only in the first seconds after the page
       opens. A later refresh of the same thing is a real request;
     - a request never waits long for /boot. Past the wait it goes to the
       network. */
(function () {
  'use strict';
  var API = 'https://taha-project.onrender.com';
  // The exact requests /boot can answer. backend/tests/test_boot.py checks
  // this list against the server's, so the two cannot drift apart.
  var KEYS = [
    '/market',
    '/sector/overview?window=1D&stocks=1',
    '/sector/benchmarks?window=1D',
    '/market/week',
    '/results/calendar',
    '/ideas?horizon=short&limit=6',
    '/special?limit=6',
    '/deals?limit=6',
    '/announcements?limit=60&min_importance=medium',
    '/chart?ticker=%5ENSEI&range=3M',
    '/social/news/feed?limit=8&sort=latest',
    '/planner/questions',
    '/daily'
  ];
  var USE_FOR_MS = 20000;      // answers are for the page's opening only
  var WAIT_MS = 2500;          // the longest a request is held for /boot

  if (typeof window === 'undefined' || !window.fetch || !window.Promise ||
      !window.Response || !window.URL) return;

  var real = window.fetch.bind(window);
  var opened = Date.now();

  /* One spelling for a request, whatever order its parameters were written in. */
  function canon(url) {
    try {
      var u = new URL(url, API);
      if (u.origin !== API) return null;
      var q = [];
      u.searchParams.forEach(function (v, k) { q.push(encodeURIComponent(k) + '=' + encodeURIComponent(v)); });
      q.sort();
      return u.pathname + (q.length ? '?' + q.join('&') : '');
    } catch (e) { return null; }
  }

  var wanted = {};
  KEYS.forEach(function (k) { var c = canon(API + k); if (c) wanted[c] = true; });
  var used = {};

  var ready = real(API + '/boot', { cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (b) {
      var have = {};
      if (b && b.at && b.data && typeof b.data === 'object') {
        Object.keys(b.data).forEach(function (k) {
          var c = canon(API + k);
          if (c && wanted[c]) have[c] = b.data[k];
        });
      }
      return have;
    })
    .catch(function () { return {}; });

  function bounded() {
    return new Promise(function (resolve) {
      var t = setTimeout(function () { resolve(null); }, WAIT_MS);
      ready.then(function (have) { clearTimeout(t); resolve(have); });
    });
  }

  window.fetch = function (input, init) {
    try {
      if (typeof input === 'string' && Date.now() - opened < USE_FOR_MS &&
          (!init || (!init.headers && !init.body && (!init.method || String(init.method).toUpperCase() === 'GET')))) {
        var key = canon(input);
        if (key && wanted[key] && !used[key]) {
          return bounded().then(function (have) {
            if (have && Object.prototype.hasOwnProperty.call(have, key) && !used[key] &&
                !(init && init.signal && init.signal.aborted)) {
              used[key] = true;
              return new Response(JSON.stringify(have[key]),
                { status: 200, headers: { 'Content-Type': 'application/json' } });
            }
            return real(input, init);
          });
        }
      }
    } catch (e) { /* fall through to the network */ }
    return real(input, init);
  };

  window.AltahaBoot = { ready: ready, keys: KEYS.slice(), canon: canon };
})();
