/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — concalls.js

   Earnings calls: a written brief of each, the key calls first.

   TWO LAYERS, AND THE PAGE SAYS WHICH IS WHICH
   The brief is written by a model from the filed transcript: what management
   said about the quarter, what they committed to, what analysts pressed on,
   what went unanswered. Each card says a model wrote it and names the model.
   Under it, folded away, is the layer no model touches: participants, topic
   counts, and the comparison with the company's previous call.

   A commitment is always a quote with a name under it. The server checks each
   quote against the transcript and takes the name from the transcript's own
   speaker label, so this file only ever prints quotes that passed.

   When no model is configured, the page says there is no written summary and
   shows the extracted digest as what it is. It does not relabel it.

   NOTHING HERE WAITS ON THE SERVER READING A PDF
   /concalls answers from a ledger at once and says whether a background pass
   is still reading. While it is, this asks again every few seconds and the
   list fills in; it never sits on a spinner for the length of a download.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var WINDOW_DAYS = 21;
  var MAX_POLLS = 75;            // ten minutes of asking again, then stop
  var STALE_MS = 60 * 1000;      // re-opening the tab after this asks afresh
  var FETCH_MS = 25 * 1000;

  var loadedAt = 0, timer = null, polls = 0, lastPaint = '', busy = false;

  /* A shared card links to ?go=concalls&q=SYMBOL. `want` is that symbol,
     `pinned` its call when the list on the page does not already hold it, and
     `last` the list as it was last answered, so the page can be drawn again
     once the pinned call arrives. */
  var want = (function () {
    try {
      var P = new URLSearchParams(location.search);
      if ((P.get('go') || '').trim().toLowerCase() !== 'concalls') return '';
      return (P.get('q') || '').trim().toUpperCase().replace(/[^A-Z0-9&.\-]/g, '').slice(0, 20);
    } catch (e) { return ''; }
  })();
  var pinned = null, last = null, arrived = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function link(url) {
    return /^https?:\/\//i.test(String(url || '')) ? esc(url) : '';
  }
  function when(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('en-IN',
        { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) { return String(iso).slice(0, 10); }
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function visible() {
    var view = $('view-concalls');
    return !!view && view.style.display !== 'none';
  }

  /* ── The counted layer. No model is involved in anything below. ───────── */

  function topicBars(topics) {
    var keys = Object.keys(topics || {});
    if (!keys.length) return '';
    keys.sort(function (a, b) {
      return topics[b].per_1k_words - topics[a].per_1k_words;
    });
    var top = keys.slice(0, 7);
    var max = topics[top[0]].per_1k_words || 1;
    return '<div class="cc-topics">' + top.map(function (k) {
      var v = topics[k].per_1k_words;
      return '<div class="cc-topic">' +
        '<span class="k">' + esc(k) + '</span>' +
        '<span class="bar"><i style="width:' + Math.max(3, 100 * v / max) + '%"></i></span>' +
        '<span class="v tnum">' + topics[k].mentions + '</span>' +
        '</div>';
    }).join('') + '</div>';
  }

  function shiftBlock(v) {
    if (!v || !v.available) {
      return '<div class="cc-shift none">' +
        esc((v && v.reason) || 'No earlier call to compare with yet.') + '</div>';
    }
    var moves = (v.topic_shifts || []).slice(0, 6);
    return '<div class="cc-shift">' +
      '<h4>What changed since ' + esc(v.from_quarter || 'the last call') + '</h4>' +
      '<div class="cc-moves">' + moves.map(function (m) {
        var tag = m.new ? 'new' : (m.dropped ? 'gone' : m.direction);
        var label = m.new ? 'newly raised' : (m.dropped ? 'not raised' :
          (m.change > 0 ? '+' + m.change : String(m.change)));
        return '<span class="cc-move ' + tag + '"><b>' + esc(m.topic) + '</b>' +
          '<em>' + esc(label) + '</em></span>';
      }).join('') + '</div>' +
      '<div class="cc-shiftnums">' +
        '<span>Forward-looking lines <b class="tnum">' + v.guidance_count.before +
          ' → ' + v.guidance_count.now + '</b></span>' +
        '<span>Analysts on the call <b class="tnum">' + v.analysts_on_call.before +
          ' → ' + v.analysts_on_call.now + '</b></span>' +
        '<span>Call length <b class="tnum">' +
          (v.call_length_words.before || '—') + ' → ' +
          (v.call_length_words.now || '—') + ' words</b></span>' +
      '</div>' +
      '<p class="cc-note">' + esc(v.caveat) + '</p>' +
      '</div>';
  }

  function facts(d) {
    return '<div class="cc-facts">' +
      '<span><b class="tnum">' + (d.words || 0).toLocaleString('en-IN') + '</b>words</span>' +
      '<span><b class="tnum">' + (d.analyst_count || 0) + '</b>analysts</span>' +
      '<span><b class="tnum">' + (d.guidance_count || 0) + '</b>forward-looking lines</span>' +
      (d.prepared_remarks_share != null
        ? '<span><b class="tnum">' + d.prepared_remarks_share + '%</b>prepared remarks</span>' : '') +
      '</div>';
  }

  function people(d) {
    var mgmt = (d.management || []).map(function (m) {
      return '<li><b>' + esc(m.name) + '</b>' +
        (m.role ? '<span>' + esc(m.role) + '</span>' : '') + '</li>';
    }).join('');
    var analysts = (d.analysts || []).map(function (a) {
      return '<li>' + esc(a.name) + (a.firm ? '<span>' + esc(a.firm) + '</span>' : '') + '</li>';
    }).join('');
    if (!mgmt && !analysts) return '';
    return '<div class="cc-people">' +
      (mgmt ? '<div><h4 class="cc-h4">On the call</h4><ul class="cc-list">' + mgmt + '</ul></div>' : '') +
      (analysts ? '<div><h4 class="cc-h4">Analysts who asked</h4><ul class="cc-list">' + analysts + '</ul></div>' : '') +
      '</div>';
  }

  function quote(said, by, topic) {
    return '<blockquote class="cc-quote">' +
      (topic ? '<span class="cc-about">' + esc(topic) + '</span>' : '') +
      esc(said) + (by ? '<cite>' + esc(by) + '</cite>' : '') + '</blockquote>';
  }

  /* The digest as the whole card: what a call shows when it has no brief. */
  function digestBlock(d) {
    if (!d || !d.quarter && !d.words) {
      return '<div class="cc-empty">This transcript could not be read.</div>';
    }
    var guidance = (d.guidance || []).map(function (g) {
      return quote(g.said, g.by);
    }).join('');
    return facts(d) +
      (guidance
        ? '<h4 class="cc-h4">What management committed to, in their words</h4>' + guidance
        : '<p class="cc-none">No forward-looking statement was made in terms this reader recognises. ' +
          'That is a fact about the call, not a gap in the transcript.</p>') +
      (Object.keys(d.topics || {}).length
        ? '<h4 class="cc-h4">What the call was spent on</h4>' + topicBars(d.topics) : '') +
      people(d);
  }

  /* The digest folded under a brief: the counts, without repeating the quotes. */
  function countedBlock(r) {
    var d = r.digest || {};
    if (!d.words) return '';
    return '<details class="cc-more" data-k="more:' + esc(r.pdf) + '">' +
      '<summary>Counted from the transcript</summary>' +
      '<p class="cc-note first">No model is involved in anything in this section.</p>' +
      facts(d) +
      (Object.keys(d.topics || {}).length
        ? '<h4 class="cc-h4">What the call was spent on</h4>' + topicBars(d.topics) : '') +
      people(d) + shiftBlock(r.versus_previous) +
      '</details>';
  }

  /* ── The written layer ─────────────────────────────────────────────────── */

  function points(title, items) {
    if (!items || !items.length) return '';
    return '<h4 class="cc-h4">' + esc(title) + '</h4><ul class="cc-pts">' +
      items.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul>';
  }

  function briefBlock(r) {
    var b = r.brief || {};
    var said = (b.commitments || []).map(function (c) {
      return quote(c.said, c.by, c.topic);
    }).join('');
    var grade = b.weight_reason
      ? '<p class="cc-why' + (r.key ? ' key' : '') + '"><b>' +
          (r.key ? 'Why it is a key call' : 'How much the call added: ' + esc(b.weight || 'medium')) +
        '</b>' + esc(b.weight_reason) + '</p>'
      : '';
    var body = points('The quarter, as management told it', b.quarter) +
      (said
        ? '<h4 class="cc-h4">What management committed to, in their words</h4>' + said
        : '<h4 class="cc-h4">What management committed to</h4>' +
          '<p class="cc-none">No commitment is quoted for this call: none that the summary ' +
          'offered could be matched word for word to something management said in the transcript.</p>') +
      points('What analysts pressed on', b.pressed_on) +
      points('Left unanswered', b.not_answered);
    var fine = 'Summary by ' + esc(b.model || 'a language model') +
      ' from the filed transcript · quotes checked against it' +
      (b.quotes_dropped
        ? ' · ' + plural(b.quotes_dropped, 'quote', 'quotes') +
          ' offered by the model did not match and ' + (b.quotes_dropped === 1 ? 'was' : 'were') + ' left out'
        : '') +
      (b.partial ? ' · only the first part of a long transcript was read' : '');
    return (b.headline ? '<h3 class="cc-hl">' + esc(b.headline) + '</h3>' : '') +
      '<p class="cc-sum">' + esc(b.summary) + '</p>' + grade +
      '<details class="cc-full" data-k="full:' + esc(r.pdf) + '"' + (r.key ? ' open' : '') + '>' +
        '<summary>The full brief</summary>' + body +
      '</details>' +
      countedBlock(r) +
      '<p class="cc-by">' + fine + '</p>';
  }

  /* Where a brief would be, when there is none, and why. */
  function waitLine(status, reading) {
    var text = {
      pending: reading ? 'A summary of this call is being written.'
        : 'A summary of this call is queued and will be written on the next pass.',
      later: 'The summary could not be written just now. It is tried again within the hour.',
      declined: 'The model declined to summarise this document, so the extracted digest is shown instead.',
      unreadable: 'The model could not read this as an earnings call, so the extracted digest is shown instead.'
    }[status];
    return text ? '<p class="cc-wait' + (status === 'pending' && reading ? ' is-on' : '') + '">' +
      esc(text) + '</p>' : '';
  }

  /* The Share button, on a call that has a written brief and a symbol to
     address it by. share.js opens its sheet for anything carrying data-share;
     the server draws the card from the same brief this page is showing. */
  var SHARE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/>' +
    '<path d="M12 3v13"/><path d="M8 7l4-4 4 4"/></svg>';

  function shareButton(r) {
    var b = r.brief || {}, dg = r.digest || {};
    if (!r.symbol || b.status !== 'ready') return '';
    var payload = { kind: 'concall', ticker: r.symbol, company: r.company || r.symbol,
                    quarter: dg.quarter || '', headline: b.headline || '' };
    return '<button class="shbtn cc-share" type="button" data-share="' +
      esc(JSON.stringify(payload)) + '" aria-label="Share the summary of ' +
      esc(r.company || r.symbol) + '’s call">' + SHARE_ICON + 'Share</button>';
  }

  function card(r, reading) {
    var dg = r.digest || {}, b = r.brief || {}, pdf = link(r.pdf);
    var body;
    if (!r.readable) {
      body = '<div class="cc-empty">The filed PDF could not be read as text. ' +
        'It is most likely a scan.' +
        (pdf ? ' <a href="' + pdf + '" target="_blank" rel="noopener">Open it →</a>' : '') +
        '</div>';
    } else if (b.status === 'ready') {
      body = briefBlock(r);
    } else {
      body = waitLine(b.status, reading) + digestBlock(dg) + shiftBlock(r.versus_previous);
    }
    return '<article class="cc' + (r.key ? ' is-key' : '') + '"' +
      (r.symbol ? ' data-sym="' + esc(String(r.symbol).toUpperCase()) + '"' : '') + '>' +
      '<header class="cc-head">' +
        '<div class="cc-co">' +
          (r.symbol
            ? '<a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.company || r.symbol) + '</a>'
            : esc(r.company || 'Unnamed company')) +
          (dg.quarter ? '<em>' + esc(dg.quarter) + '</em>' : '') +
          (r.key ? '<em class="key">Key call</em>' : '') +
        '</div>' +
        '<span class="cc-when">' + esc(dg.call_date ? when(dg.call_date) : when(r.at)) + '</span>' +
        shareButton(r) +
      '</header>' + body +
      (r.readable && pdf
        ? '<a class="cc-pdf" href="' + pdf + '" target="_blank" rel="noopener">Read the full transcript →</a>' : '') +
      '</article>';
  }

  function summaryBlock(configured) {
    if (configured) return '';
    return '<div class="cc-nosum">' +
      '<b>No written summary on this instance.</b> Everything below is ' +
      'extracted from the transcript itself: participants, management’s own ' +
      'forward-looking sentences quoted verbatim, and what the call spent its ' +
      'time on against last quarter. A written summary needs a language model, ' +
      'and none is configured here.</div>';
  }

  /* One line on what the reader behind the page is doing, or why it stopped. */
  function statusLine(d) {
    var s = d.status || {}, c = d.counts || {};
    if (s.reading) {
      return s.phase === 'summarising' ? 'Writing summaries…' : 'Reading newly filed transcripts…';
    }
    if (s.error) return s.error;
    if (c.waiting && s.capped) {
      return plural(c.waiting, 'summary', 'summaries') + ' queued: the ' + s.capped +
        ' limit on summaries has been reached.';
    }
    if (c.waiting) return plural(c.waiting, 'summary', 'summaries') + ' queued for the next pass.';
    return '';
  }

  function countsBar(d) {
    var c = d.counts || {}, line = statusLine(d), s = d.status || {};
    var parts = ['<span><b class="tnum">' + (c.calls || 0) + '</b>' +
      (c.calls === 1 ? 'call' : 'calls') + ' in ' + (d.days || WINDOW_DAYS) + ' days</span>'];
    if (d.summary_configured) {
      parts.push('<span><b class="tnum">' + (c.key || 0) + '</b>key</span>');
      parts.push('<span><b class="tnum">' + (c.summarised || 0) + '</b>summarised</span>');
    }
    return '<div class="cc-counts">' + parts.join('') +
      (line ? '<span class="st' + (s.reading ? ' is-on' : (s.error ? ' is-bad' : '')) +
        '" role="status">' + esc(line) + '</span>' : '') +
      '</div>';
  }

  function keepOpen(box) {
    var state = {};
    box.querySelectorAll('details[data-k]').forEach(function (el) {
      state[el.getAttribute('data-k')] = el.open;
    });
    return state;
  }
  function restoreOpen(box, state) {
    box.querySelectorAll('details[data-k]').forEach(function (el) {
      var k = el.getAttribute('data-k');
      if (Object.prototype.hasOwnProperty.call(state, k)) el.open = state[k];
    });
  }

  function paint(d) {
    var box = $('concalls-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="cc-empty">' +
        esc((d && d.message) || 'Transcripts could not be read.') + '</div>';
      return;
    }
    // An unchanged answer is not repainted: a reader half-way down a brief
    // should not have the page rebuilt under them every few seconds.
    var sig = JSON.stringify([d.rows, d.counts, d.status, d.summary_configured, pinned]);
    if (sig === lastPaint) return;
    lastPaint = sig;

    var rows = d.rows || [], s = d.status || {}, open = keepOpen(box), html;
    if (!rows.length && !pinned) {
      html = summaryBlock(d.summary_configured) + (s.reading
        ? '<div class="cc-empty is-loading" aria-busy="true">Reading the transcripts filed in ' +
          'the last few days. The first pass takes a few minutes, and each call appears here ' +
          'as it is read, so there is no need to reload.</div>'
        : '<div class="cc-empty">' + (s.error ? esc(s.error) + ' ' : '') +
          'No transcript has been filed in this window. ' +
          'Calls cluster in the weeks after results, so this fills up in earnings season.</div>');
    } else {
      var key = rows.filter(function (r) { return r.key; });
      var rest = rows.filter(function (r) { return !r.key; });
      var one = function (r) { return card(r, !!s.reading); };
      html = summaryBlock(d.summary_configured) + countsBar(d) +
        (pinned
          ? '<h3 class="cc-group">The call you were sent</h3>' + card(pinned, false)
          : '') +
        (key.length
          ? '<h3 class="cc-group">Key calls</h3>' +
            '<p class="cc-groupnote">The calls that added the most to what the results filing ' +
            'already said: new or changed guidance, something announced, or a problem disclosed. ' +
            'This grades the information in the call, not the company or its share.</p>' +
            key.map(one).join('') +
            (rest.length ? '<h3 class="cc-group">Other calls</h3>' : '')
          : (pinned && rest.length ? '<h3 class="cc-group">Other calls</h3>' : '')) +
        rest.map(one).join('') +
        (d.disclaimer ? '<p class="cc-src">' + esc(d.disclaimer) + '</p>' : '') +
        '<p class="cc-src">' + esc(d.source) + '</p>';
    }
    box.innerHTML = html;
    restoreOpen(box, open);
  }

  /* ── Arriving from a shared card ──────────────────────────────────────── */

  function reveal() {
    var box = $('concalls-body');
    if (!box || !want || !visible()) return;
    var el = null;
    box.querySelectorAll('article.cc[data-sym]').forEach(function (a) {
      if (!el && a.getAttribute('data-sym') === want) el = a;
    });
    if (!el) return;
    var full = el.querySelector('details.cc-full');
    if (full) full.open = true;
    el.classList.add('is-arrived');
    var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    try { el.scrollIntoView({ block: 'start', behavior: calm ? 'auto' : 'smooth' }); }
    catch (e) { el.scrollIntoView(); }
  }

  /* Once, after the first list lands. The list holds forty calls and a link
     can be older than all of them, so a call that is not in it is asked for
     by name and shown above the list rather than quietly not being there. */
  function arrive(d) {
    if (!want || arrived || !d || !d.available) return;
    arrived = true;
    var here = (d.rows || []).some(function (r) {
      return String(r.symbol || '').toUpperCase() === want;
    });
    if (here) { setTimeout(reveal, 80); return; }
    fetch(API + '/concall?ticker=' + encodeURIComponent(want))
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function (c) {
        if (!c || !c.available) return;
        var b = c.brief || {};
        pinned = { symbol: c.symbol, company: c.company, at: c.filed_at, pdf: c.pdf,
                   readable: true, digest: c.digest || {}, brief: b,
                   versus_previous: c.versus_previous,
                   key: b.status === 'ready' && b.weight === 'high' };
        if (last) paint(last);
        setTimeout(reveal, 80);
      })
      .catch(function () { /* the list is still the page */ });
  }

  function again(seconds) {
    clearTimeout(timer);
    if (!seconds || polls >= MAX_POLLS) return;
    timer = setTimeout(function () {
      if (visible()) { polls++; load(true); }
    }, Math.max(3, seconds) * 1000);
  }

  function load(quiet) {
    var box = $('concalls-body');
    if (busy) return;
    busy = true;
    if (box && !quiet) {
      lastPaint = '';
      box.innerHTML = '<div class="cc-empty is-loading" aria-busy="true">' +
        'Opening the call ledger…</div>';
    }
    var ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var stop = ctl ? setTimeout(function () { ctl.abort(); }, FETCH_MS) : null;
    fetch(API + '/concalls?days=' + WINDOW_DAYS + '&limit=40', ctl ? { signal: ctl.signal } : undefined)
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function (d) {
        loadedAt = Date.now();
        last = d;
        paint(d);
        arrive(d);
        again(d && d.poll_seconds);
      })
      .catch(function () {
        // A background refresh that fails leaves what is on screen alone.
        if (quiet) { again(20); return; }
        if (box) {
          // data-nosnippet: not to be quoted by a search engine as the page.
          box.innerHTML = '<div class="cc-empty" data-nosnippet>The engine is unreachable. ' +
            'If it has been idle it takes about thirty seconds to wake. ' +
            '<button type="button" class="cc-retry">Try again</button></div>';
          var b = box.querySelector('.cc-retry');
          if (b) b.addEventListener('click', function () { load(false); });
        }
      })
      .then(function () { busy = false; if (stop) clearTimeout(stop); });
  }

  /* Nothing is fetched until the tab is opened, and coming back to it after a
     while asks afresh rather than showing a list from an hour ago. */
  function show() {
    if (!visible()) { clearTimeout(timer); return; }
    if (!loadedAt) { polls = 0; load(false); }
    else if (Date.now() - loadedAt > STALE_MS) { polls = 0; load(true); }
  }

  function watch() {
    var view = $('view-concalls');
    if (!view) return;
    new MutationObserver(show).observe(view, { attributes: true, attributeFilter: ['style'] });
    show();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }

  window.AltahaConcalls = { shiftBlock: shiftBlock, paint: paint };
})();
