/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — auth.js
   Who is signed in, and how the rest of the site asks.

   A BEARER TOKEN, NOT A COOKIE
   The site is altahascreener.in and the API is on onrender.com — different
   origins. A session cookie across those would need SameSite=None, credentialed
   CORS with a fixed origin list in place of the "*" the API sends today, and a
   CSRF story on every write. A token in an Authorization header needs none of
   that, and no other site's page can attach it to a request.

   THE TRADE THAT COMES WITH IT
   A token in localStorage is readable by script running on this origin, so it
   is only as safe as the scripts this site loads. That is a real cost and it
   is accepted deliberately: this frontend has no build step, no npm tree and
   no third-party script beyond a charting library and the analytics loader.
   Sessions expire server-side, and signing out deletes the row rather than
   only forgetting the token here.

   IT IS FINE TO BE SIGNED OUT
   Every helper works when nobody is signed in — user() returns null, authed()
   is false, and nothing throws. Signing in adds saving across devices and the
   daily email; it is not a gate in front of the product.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var KEY = 'altaha-session-v1';
  var cached = null;              // the last /auth/me answer

  function readToken() {
    try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; }
  }
  function writeToken(t) {
    try {
      if (t) localStorage.setItem(KEY, t);
      else localStorage.removeItem(KEY);
    } catch (e) {}
  }

  function announce() {
    try {
      window.dispatchEvent(new CustomEvent('altaha-auth', { detail: cached }));
    } catch (e) {}
  }

  /* fetch with the token attached, and one rule: a 401 means the session is
     gone — expired, or signed out on another device — so it is cleared here
     rather than left to fail on every later call. */
  function authFetch(path, opts) {
    opts = opts || {};
    var headers = opts.headers || {};
    var token = readToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (opts.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    opts.headers = headers;
    return fetch(API + path, opts).then(function (r) {
      if (r.status === 401 && token) {
        writeToken('');
        cached = null;
        announce();
      }
      return r;
    });
  }

  function refresh() {
    if (!readToken()) {
      cached = null;
      announce();
      return Promise.resolve(null);
    }
    return authFetch('/auth/me')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (u) { cached = u; announce(); return u; })
      .catch(function () { return cached; });
  }

  function requestLink(email) {
    return fetch(API + '/auth/request-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: String(email || '').trim() })
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || 'That did not work.');
        return d;
      });
    });
  }

  function verify(token) {
    return fetch(API + '/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token })
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.detail || 'This link did not work.');
        writeToken(d.token);
        cached = d.user;
        announce();
        return d.user;
      });
    });
  }

  function signOut() {
    var done = authFetch('/auth/logout', { method: 'POST' }).catch(function () {});
    writeToken('');
    cached = null;
    announce();
    return done;
  }

  window.AltahaAuth = {
    api: API,
    token: readToken,
    user: function () { return cached; },
    authed: function () { return !!readToken(); },
    fetch: authFetch,
    refresh: refresh,
    requestLink: requestLink,
    verify: verify,
    signOut: signOut
  };

  // Ask once on load so anything that renders a signed-in state has an answer
  // without every module making its own call.
  if (readToken()) refresh();
})();
