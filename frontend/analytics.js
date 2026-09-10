/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — analytics.js
   Product analytics (PostHog) and crash reporting (Sentry), in one file.

   WHY THIS EXISTS
   Nothing on this site has ever reported back. Every decision about what to
   build, what to keep and what to charge for has been a guess, and the CI
   header already says the quiet part: every bug this project shipped was
   silent. A user whose page throws sees a skeleton that never fills and
   closes the tab. Nobody finds out. This file ends both problems.

   A CLOSED SET OF EVENTS
   track() refuses any name not in EVENTS below. That is deliberate: it keeps
   ANALYTICS.md honest, because the list in the docs IS the list here, and it
   stops a stray call somewhere in fourteen thousand lines of frontend from
   quietly starting to collect something nobody agreed to.

   WHAT IS NEVER COLLECTED
   No names, no emails, no phone numbers, no portfolio values, no holdings.
   Property values are whitelisted per event and truncated. Session replays
   mask every input and every element marked data-private — which is what the
   portfolio and planner views carry, so a stranger's holdings can never end
   up in a recording. Do Not Track is honoured.

   IT FAILS SOFT, ALWAYS
   An ad blocker eats the PostHog script for a good share of Indian users.
   Every call here is inside a try/catch and the site does not care whether
   any of it loaded. Analytics that can break the product is worse than no
   analytics.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /* The PostHog project key is a WRITE-ONLY ingest key. It is meant to sit in
     public page source — it can send events and read nothing back. The key
     that must never appear here is the Personal API key, which is a password.
     Sentry DSNs are the same shape of thing: an address, not a credential. */
  var CONFIG = {
    posthogKey: 'phc_wMgTkEXQ96zFNkYqQcYSTA2wEHEpaPLEWAS2r6YuN3Pw',
    posthogHost: 'https://us.i.posthog.com',
    posthogAssets: 'https://us-assets.i.posthog.com',

    /* Browser DSN from the Sentry "javascript" project. A DSN is an address,
       not a credential: it can file a crash report and read nothing back,
       which is why it is allowed to sit in public page source. Blanking this
       line switches browser crash reporting off and loads nothing at all.

       The server has its own DSN, from a separate Sentry project, and it
       lives in the SENTRY_DSN environment variable on Render rather than
       here — not because it is more secret, but because it belongs with the
       deploy. */
    sentryDsn: 'https://c96a19b06d2aa898bc78c24f605661e4@o4512061262200832.ingest.us.sentry.io/4512061316923392',
    sentryVersion: '8.55.0'
  };

  /* Only the real site reports. Without this, every local file:// open and
     every Vercel preview build pollutes the numbers that decisions get made
     from — and the first thing you would do with a dashboard is trust it.
     ?altaha_debug=1 forces it on for a deliberate test. */
  var HOSTS = ['altahascreener.in', 'www.altahascreener.in'];

  function live() {
    try {
      if (String(location.search).indexOf('altaha_debug=1') > -1) return true;
      return HOSTS.indexOf(location.hostname) > -1;
    } catch (e) { return false; }
  }

  /* ── The event list ──────────────────────────────────────────────────────
     Name in snake_case, past tense: this is a record of something that
     already happened. The array is the whitelist of properties that event may
     carry; anything else is dropped before it leaves the browser.

     Each line notes the question it exists to answer, because an event that
     answers no question is quota spent on noise. */
  var EVENTS = {
    // Which companies people actually come here for.
    stock_opened:          ['ticker', 'from'],
    stock_viewed:          ['ticker', 'sector', 'score'],
    // How often the engine fails a reader, and how — asleep, or no such name.
    stock_view_failed:     ['ticker', 'reason'],

    // Does anyone read past the score? This is the whole paywall question:
    // the ledger and the levels are the work; the score is the headline.
    stock_section_clicked: ['section'],

    // Which windows matter, now that they all work.
    chart_range_changed:   ['range'],
    chart_failed:          ['range', 'status'],

    // Names people search for that the universe does not carry. This is a
    // list of stocks to add, written by the users themselves.
    search_no_match:       ['query'],

    // The closest thing to intent this site has without accounts.
    watchlist_changed:     ['ticker', 'action', 'size'],

    // Which of the forty-odd modules earn their keep — Deals, Social, Lab.
    view_opened:           ['section', 'tab'],

    // The growth loop: does anything actually get shared?
    share_clicked:         ['kind', 'action'],

    // Every non-200 the frontend sees, so the API's real error rate is known
    // from the browser's side and not only from the server's logs.
    api_error:             ['endpoint', 'status']
  };

  /* ── Property hygiene ────────────────────────────────────────────────────
     Values are coerced to string / number / boolean, and strings are cut
     short. A search box is free text: somebody will one day paste something
     personal into it, and a 40-character cap plus a whitelist is what stops
     that from being stored for ever. */
  function cleanValue(v, limit) {
    if (v == null) return null;
    if (typeof v === 'boolean') return v;
    if (typeof v === 'number') return isFinite(v) ? v : null;
    var s = String(v).trim();
    if (!s) return null;
    return s.slice(0, limit || 64);
  }

  function cleanProps(name, props) {
    var allowed = EVENTS[name];
    if (!allowed) return null;
    var out = {};
    for (var i = 0; i < allowed.length; i++) {
      var k = allowed[i];
      if (!props || !(k in props)) continue;
      var v = cleanValue(props[k], k === 'query' ? 40 : 64);
      if (v !== null) out[k] = v;
    }
    return out;
  }

  /* ── Sending ─────────────────────────────────────────────────────────────
     Events raised before PostHog finishes loading are queued, not lost: the
     first stock_viewed on a cold page load happens well before a script from
     a third-party CDN has parsed. The queue is capped so a blocked script
     cannot grow it without bound. */
  var ready = false, dead = false, queue = [];

  /* Events raised on the way out of the page. A normal capture is an async
     XHR the browser is free to cancel the moment navigation starts, which
     would lose exactly the clicks that matter most — the one that opens a
     stock, the one that shares a card. sendBeacon survives the unload. */
  var LEAVING = { stock_opened: 1, share_clicked: 1 };

  function send(name, props) {
    window.posthog.capture(name, props,
      LEAVING[name] ? { transport: 'sendBeacon' } : undefined);
  }

  function flush() {
    while (queue.length) {
      var e = queue.shift();
      try { send(e[0], e[1]); } catch (err) { return; }
    }
  }

  function track(name, props) {
    try {
      if (dead || !live()) return;
      var clean = cleanProps(name, props);
      if (!clean) {
        // A typo'd event name would otherwise vanish in silence, which is the
        // exact failure mode this whole file exists to remove.
        if (window.console && console.warn) console.warn('[analytics] unknown event: ' + name);
        return;
      }
      if (ready && window.posthog) send(name, clean);
      else if (queue.length < 50) queue.push([name, clean]);
    } catch (e) {}
  }

  /* ── PostHog ─────────────────────────────────────────────────────────── */

  function startPostHog() {
    var s = document.createElement('script');
    s.src = CONFIG.posthogAssets + '/static/array.js';
    s.async = true;
    s.onload = function () {
      try {
        window.posthog.init(CONFIG.posthogKey, {
          api_host: CONFIG.posthogHost,

          // Retention — "did anyone come back on day two" — is the single
          // most important number for a product with no accounts yet, and it
          // needs person profiles to be answerable.
          person_profiles: 'always',

          capture_pageview: true,
          capture_pageleave: true,

          // Autocapture records clicks nobody thought to instrument. Early on
          // that answers questions that have not been asked yet; if the free
          // quota ever tightens, this is the first line to turn off.
          autocapture: true,

          respect_dnt: true,

          session_recording: {
            // Every input, everywhere: the planner asks for savings and
            // income, and none of that is anybody's business but the user's.
            maskAllInputs: true,
            // Rendered numbers are not inputs. Anything inside a
            // data-private element is masked too — that is the portfolio and
            // the planner, marked in index.html.
            maskTextSelector: '[data-private], [data-private] *'
          }
        });
        ready = true;
        flush();
      } catch (e) { dead = true; queue.length = 0; }
    };
    s.onerror = function () {
      // Blocked by an extension. Expected, common, and not a problem.
      dead = true;
      queue.length = 0;
    };
    document.head.appendChild(s);
  }

  /* ── Sentry ──────────────────────────────────────────────────────────────
     Loaded only when a DSN is configured, so an unconfigured deploy pays
     nothing: no request, no bytes, no console noise. */
  function startSentry() {
    if (!CONFIG.sentryDsn) return;
    var s = document.createElement('script');
    s.src = 'https://browser.sentry-cdn.com/' + CONFIG.sentryVersion + '/bundle.min.js';
    s.crossOrigin = 'anonymous';
    s.async = true;
    s.onload = function () {
      try {
        window.Sentry.init({
          dsn: CONFIG.sentryDsn,
          // Performance tracing is off: it multiplies the request volume for
          // a question this site is not asking yet.
          tracesSampleRate: 0,
          sendDefaultPii: false,
          environment: location.hostname === 'altahascreener.in' ? 'production' : 'preview',
          // A stock page carries a ticker in the URL and nothing else. That
          // is safe to keep and it is most of what makes a report actionable.
          beforeSend: function (event) {
            try {
              if (event.request && event.request.url) {
                event.request.url = String(event.request.url).split('#')[0];
              }
            } catch (e) {}
            return event;
          }
        });
      } catch (e) {}
    };
    document.head.appendChild(s);
  }

  /* ── Boot ────────────────────────────────────────────────────────────── */

  if (typeof window !== 'undefined' && window.document) {
    window.AltahaTrack = track;
    window.AltahaTrack.EVENTS = EVENTS;
    if (live()) {
      startPostHog();
      startSentry();
    }
  }

  // The pure parts are exported so CI can check the event list without a
  // browser. Everything above only touches window inside a function.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EVENTS: EVENTS, cleanProps: cleanProps, cleanValue: cleanValue };
  }
})();
