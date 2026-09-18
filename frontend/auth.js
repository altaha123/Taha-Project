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
    } catch (e) {
      if (t) throw new Error('Your browser could not save your sign-in. Allow site storage and request a new link.');
    }
  }

  // Bound both the response and body read; never retry a one-time token automatically.
  function request(path, opts) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 30000);
    opts = Object.assign({}, opts || {}, { signal: controller.signal });
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail :
          'Sign-in is temporarily unavailable. Please try again shortly.');
        return d;
      });
    }).catch(function (err) {
      if (err.name === 'AbortError') throw new Error('The server took too long to respond. Please try again.');
      if (err instanceof TypeError) throw new Error('Could not connect. Check your connection and try again.');
      throw err;
    }).finally(function () { clearTimeout(timer); });
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
      if (r.status === 401 && token && readToken() === token) {
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
    var token = readToken();
    return authFetch('/auth/me')
      .then(function (r) {
        if (!r.ok && r.status !== 401) throw new Error('Could not check your session.');
        return r.ok ? r.json() : null;
      })
      .then(function (u) {
        if (readToken() !== token) return cached;
        cached = u; announce(); return u;
      })
      .catch(function () { return cached; });
  }

  function requestLink(email) {
    return request('/auth/request-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: String(email || '').trim() })
    }).then(function (d) {
      if (d.sent !== true) throw new Error('Your sign-in email could not be sent. Please try again.');
      return d;
    });
  }

  /* Storage is checked before anything single-use is spent. A browser that
     cannot keep the session would otherwise consume the link or the code and
     leave the reader signed out with nothing left to try. */
  function storageReady() {
    try {
      localStorage.setItem(KEY + '-check', '1');
      localStorage.removeItem(KEY + '-check');
      return true;
    } catch (e) { return false; }
  }

  function adopt(d, whatToAskFor) {
    if (!d || !d.token || !d.user || !d.user.email) {
      throw new Error('The server returned an incomplete sign-in. Please request a new ' +
                      (whatToAskFor || 'link') + '.');
    }
    writeToken(d.token);
    cached = d.user;
    announce();
    return d.user;
  }

  function post(path, body, whatToAskFor) {
    if (!storageReady()) {
      return Promise.reject(new Error('Allow site storage in your browser before signing in.'));
    }
    return request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (d) { return adopt(d, whatToAskFor); });
  }

  function verify(token) {
    return post('/auth/verify', { token: token }, 'link');
  }

  /* The code, not the link. A link is opened by whichever browser the mail app
     hands it to; a code is typed into the page already open in this one. */
  function verifyCode(email, code) {
    return post('/auth/verify-code', {
      email: String(email || '').trim(),
      code: String(code || '').replace(/\D/g, '')
    }, 'code');
  }

  /* Google hands the page a signed assertion; the server decides whether to
     believe it. Nothing here is trusted on this side of the wire. */
  function google(credential) {
    return post('/auth/google', { credential: String(credential || '') }, 'sign-in');
  }

  /* Which methods this deployment actually has. A Google button that cannot
     work is worse than no Google button. */
  function config() {
    return request('/auth/config', { method: 'GET' })
      .catch(function () { return { google_client_id: '', email: true }; });
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
    verifyCode: verifyCode,
    google: google,
    config: config,
    signOut: signOut
  };

  window.addEventListener('storage', function (event) {
    if (event.key === KEY || event.key === null) {
      cached = null;
      refresh();
    }
  });

  // Ask once on load so anything that renders a signed-in state has an answer
  // without every module making its own call.
  if (readToken()) refresh();
})();
