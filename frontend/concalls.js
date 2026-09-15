/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — concalls.js

   Earnings call transcripts, digested.

   THE LINE THIS VIEW HOLDS
   Everything rendered here is EXTRACTED from the transcript. Forward-looking
   lines are quoted verbatim and carry the name of the person who said them,
   because a commitment attributed to management that management did not make
   is the worst thing this page could print — so the moderator's script and an
   analyst's question are never shown as guidance.

   When no model is configured, the page says there is no written summary. It
   does not relabel the extraction as one.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var loaded = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function when(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('en-IN',
        { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (e) { return String(iso).slice(0, 10); }
  }

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

  function digestBlock(d, pdf) {
    if (!d || !d.quarter && !d.words) {
      return '<div class="cc-empty">This transcript could not be read.</div>';
    }
    var mgmt = (d.management || []).map(function (m) {
      return '<li><b>' + esc(m.name) + '</b>' +
        (m.role ? '<span>' + esc(m.role) + '</span>' : '') + '</li>';
    }).join('');
    var analysts = (d.analysts || []).map(function (a) {
      return '<li>' + esc(a.name) + (a.firm ? '<span>' + esc(a.firm) + '</span>' : '') + '</li>';
    }).join('');
    var guidance = (d.guidance || []).map(function (g) {
      return '<blockquote class="cc-quote">' + esc(g.said) +
        (g.by ? '<cite>' + esc(g.by) + '</cite>' : '') + '</blockquote>';
    }).join('');

    return '<div class="cc-facts">' +
      '<span><b class="tnum">' + (d.words || 0).toLocaleString('en-IN') + '</b>words</span>' +
      '<span><b class="tnum">' + (d.analyst_count || 0) + '</b>analysts</span>' +
      '<span><b class="tnum">' + (d.guidance_count || 0) + '</b>forward-looking lines</span>' +
      (d.prepared_remarks_share != null
        ? '<span><b class="tnum">' + d.prepared_remarks_share + '%</b>prepared remarks</span>' : '') +
      '</div>' +
      (guidance
        ? '<h4 class="cc-h4">What management committed to, in their words</h4>' + guidance
        : '<p class="cc-none">No forward-looking statement was made in terms this reader recognises. ' +
          'That is a fact about the call, not a gap in the transcript.</p>') +
      (Object.keys(d.topics || {}).length
        ? '<h4 class="cc-h4">What the call was spent on</h4>' + topicBars(d.topics) : '') +
      '<div class="cc-people">' +
        (mgmt ? '<div><h4 class="cc-h4">On the call</h4><ul class="cc-list">' + mgmt + '</ul></div>' : '') +
        (analysts ? '<div><h4 class="cc-h4">Analysts who asked</h4><ul class="cc-list">' + analysts + '</ul></div>' : '') +
      '</div>' +
      (pdf ? '<a class="cc-pdf" href="' + esc(pdf) + '" target="_blank" rel="noopener">Read the full transcript →</a>' : '');
  }

  function summaryBlock(configured) {
    if (configured) return '';
    return '<div class="cc-nosum">' +
      '<b>No written summary on this instance.</b> Everything below is ' +
      'extracted from the transcript itself — participants, management’s own ' +
      'forward-looking sentences quoted verbatim, and what the call spent its ' +
      'time on against last quarter. A written summary needs a language model, ' +
      'and none is configured here.</div>';
  }

  function paint(d) {
    var box = $('concalls-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="cc-empty">' +
        esc((d && d.message) || 'Transcripts could not be read.') + '</div>';
      return;
    }
    var rows = d.rows || [];
    if (!rows.length) {
      box.innerHTML = summaryBlock(d.summary_configured) +
        '<div class="cc-empty">No transcript has been filed in this window. ' +
        'Calls cluster in the weeks after results — this fills up in earnings season.</div>';
      return;
    }
    box.innerHTML = summaryBlock(d.summary_configured) +
      rows.map(function (r) {
        var dg = r.digest || {};
        return '<article class="cc">' +
          '<header class="cc-head">' +
            '<div class="cc-co">' +
              (r.symbol
                ? '<a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.company || r.symbol) + '</a>'
                : esc(r.company || 'Unnamed company')) +
              (dg.quarter ? '<em>' + esc(dg.quarter) + '</em>' : '') +
            '</div>' +
            '<span class="cc-when">' + esc(dg.call_date ? when(dg.call_date) : when(r.at)) + '</span>' +
          '</header>' +
          (r.readable
            ? digestBlock(dg, r.pdf) + shiftBlock(r.versus_previous)
            : '<div class="cc-empty">The filed PDF could not be read as text — ' +
              'it is most likely a scan.' +
              (r.pdf ? ' <a href="' + esc(r.pdf) + '" target="_blank" rel="noopener">Open it →</a>' : '') +
              '</div>') +
          '</article>';
      }).join('') +
      '<p class="cc-src">' + esc(d.source) + '</p>';
  }

  function load() {
    var box = $('concalls-body');
    if (box) {
      box.innerHTML = '<div class="cc-empty is-loading" aria-busy="true">' +
        'Reading the transcripts…</div>';
    }
    fetch(API + '/concalls?days=10')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paint)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="cc-empty">The engine is unreachable. ' +
            'If it has been idle it takes about thirty seconds to wake — try again.</div>';
        }
      });
  }

  /* Transcripts are twenty-page PDFs. Nothing is fetched until asked for. */
  function watch() {
    var view = $('view-concalls');
    if (!view) return;
    var obs = new MutationObserver(function () {
      if (view.style.display !== 'none' && !loaded) { loaded = true; load(); }
    });
    obs.observe(view, { attributes: true, attributeFilter: ['style'] });
    if (view.style.display !== 'none' && !loaded) { loaded = true; load(); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch);
  } else { watch(); }

  window.AltahaConcalls = { shiftBlock: shiftBlock };
})();
