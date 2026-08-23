/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — Scoring v3 front end

   THE PROBLEM THIS FIXES
   The backend has been returning the new business-model-weighted score since
   Update 2, under the key `scoring`. The page was still reading `verdict` —
   the old flat 50% technical / 50% fundamental average — so the new engine ran
   on every request and its answer was thrown away. What you saw was
   (42 + 75) / 2 = 58, which is exactly the arithmetic v3 was built to replace.

   HOW IT WORKS
   Same approach as nav.js: this file does not rewrite the page, it wraps what
   the page already defines.

     fetch()    gains the chosen horizon on the /analyze request only
     render()   has d.verdict swapped for d.scoring before the original runs,
                so the existing drawing code needs no changes at all, then the
                new panels are added underneath

   If anything here fails, the try/catch hands control back to the original
   function and the page behaves exactly as it did before. Deleting the one
   <script> line restores the old behaviour completely.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var KEY = 'altaha-horizon';
  var HORIZONS = [
    { id: 'trade',    label: 'Days',   full: 'Days to weeks' },
    { id: 'position', label: 'Months', full: 'Weeks to months' },
    { id: 'invest',   label: 'Years',  full: 'One year and beyond' }
  ];

  var PILLAR = {
    momentum:      'Price trend',
    participation: 'Volume & ownership',
    quality:       'Business quality',
    improvement:   'Direction of travel',
    valuation:     'What you pay'
  };

  function get() {
    try { return localStorage.getItem(KEY) || 'position'; }
    catch (e) { return 'position'; }
  }
  function set(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ── 1 · the horizon switch ─────────────────────────────────────────────
     Placed directly above the score, because it is the control that changes
     the score. Putting it anywhere else makes the number look arbitrary. */

  function buildSwitch() {
    if ($('hzswitch')) return;
    var verdict = document.querySelector('#result .verdict');
    if (!verdict) return;

    var wrap = document.createElement('div');
    wrap.className = 'hzswitch';
    wrap.id = 'hzswitch';
    wrap.innerHTML =
      '<span class="hzlbl">Scoring for</span>' +
      '<span class="hzseg" role="tablist">' +
      HORIZONS.map(function (h) {
        return '<button type="button" role="tab" data-h="' + h.id + '" title="' +
               esc(h.full) + '"' + (h.id === get() ? ' class="on" aria-selected="true"' :
               ' aria-selected="false"') + '>' + h.label + '</button>';
      }).join('') +
      '</span><span class="hzhint" id="hzhint"></span>';

    verdict.parentNode.insertBefore(wrap, verdict);

    wrap.addEventListener('click', function (e) {
      var t = e.target;
      var b = null;
      while (t && t !== wrap) {
        if (t.tagName === 'BUTTON' && t.getAttribute('data-h')) { b = t; break; }
        t = t.parentNode;
      }
      if (!b || b.classList.contains('on')) return;
      set(b.getAttribute('data-h'));
      var btns = wrap.querySelectorAll('button');
      for (var i = 0; i < btns.length; i++) {
        var on = btns[i] === b;
        btns[i].classList.toggle('on', on);
        btns[i].setAttribute('aria-selected', on ? 'true' : 'false');
      }
      var sym = ($('tk') || {}).value;
      if (sym && typeof window.analyse === 'function') window.analyse(sym);
    });
  }

  /* ── 2 · the pillar strip ───────────────────────────────────────────────
     Replaces the old "Technical 42 / Fundamental 75" pair, which was the
     visible face of the 50/50 average. Five pillars, each showing its score
     and the weight it was actually given, so the arithmetic can be followed
     across the row and add up to the headline. */

  function pillarStrip(s) {
    var sched = document.querySelector('#result .sched');
    if (!sched || !s || !s.contribution || !s.contribution.length) return;

    // The original .sched holds #tscore and #fscore, and render() writes to
    // both by id on EVERY analysis. Overwriting its innerHTML would delete
    // those two elements, and the next analysis would throw on a null before
    // it drew anything. So the old strip is hidden and left intact, and the
    // pillar strip is a new sibling.
    sched.style.display = 'none';

    var strip = $('altaha-pillars');
    if (!strip) {
      strip = document.createElement('div');
      strip.id = 'altaha-pillars';
      strip.className = 'sched sched-v3';
      sched.parentNode.insertBefore(strip, sched.nextSibling);
    }

    strip.innerHTML = s.contribution.map(function (c) {
      var pct = Math.round(c.weight * 100);
      return '<div class="cell v3cell">' +
             '<span class="lbl">' + esc(PILLAR[c.pillar] || c.pillar) + '</span>' +
             '<span class="num">' + c.pillar_score + '<small> /100</small></span>' +
             '<span class="wt"><i style="width:' + pct + '%"></i></span>' +
             '<span class="wtx">' + pct + '% weight</span>' +
             '</div>';
    }).join('');
  }

  /* ── 3 · why this score ─────────────────────────────────────────────────
     The audit trail for the weighting itself. Without this the new score is
     just a different black box, which would be worse than the old one because
     at least 50/50 was guessable. */

  function whyPanel(s) {
    var host = $('altaha-why');
    if (!host) {
      // Anchor to the pillar strip when it exists, so the order on screen is
      // score -> pillars -> why. Falling back to .sched keeps this working if
      // the strip could not be built.
      var anchor = $('altaha-pillars') || document.querySelector('#result .sched');
      if (!anchor) return;
      host = document.createElement('div');
      host.id = 'altaha-why';
      host.className = 'whywrap';
      anchor.parentNode.insertBefore(host, anchor.nextSibling);
    }
    if (!s || s.score == null) { host.innerHTML = ''; return; }

    var m = s.model || {};
    var conf = s.confidence;
    var confTone = conf >= 75 ? 'ok' : (conf >= 50 ? 'mid' : 'low');
    var parts = [];

    parts.push(
      '<div class="whyhead">' +
        '<div class="whytitle">' +
          '<span class="wk">Scored as</span>' +
          '<span class="wv">' + esc(m.name || 'General') + '</span>' +
          '<span class="wsub">' + esc(m.examples || '') + '</span>' +
        '</div>' +
        '<div class="whytitle">' +
          '<span class="wk">Held for</span>' +
          '<span class="wv">' + esc(s.horizon_label || '') + '</span>' +
          '<span class="wsub">' + esc(s.basis || '') + '</span>' +
        '</div>' +
        '<div class="whytitle">' +
          '<span class="wk">Confidence</span>' +
          '<span class="wv conf-' + confTone + '">' + conf + '%</span>' +
          '<span class="wsub">' +
            (s.coverage ? esc(s.coverage.present + ' of ' + s.coverage.total +
             ' figures published') : 'how much of the evidence exists') +
          '</span>' +
        '</div>' +
      '</div>');

    if (m.matters) parts.push('<p class="whymatters">' + esc(m.matters) + '</p>');
    if (s.cycle_note) {
      parts.push('<p class="whycycle"><b>Where in the cycle.</b> ' +
                 esc(s.cycle_note) + '</p>');
    }
    if (s.valuation_note) {
      parts.push('<p class="whynote">' + esc(s.valuation_note) + '</p>');
    }

    if (s.dropped && s.dropped.length) {
      parts.push(
        '<details class="whydrop"><summary>' + s.dropped.length +
        ' check' + (s.dropped.length === 1 ? '' : 's') +
        ' deliberately ignored for this kind of business</summary><ul>' +
        s.dropped.map(function (d) {
          return '<li><b>' + esc(d.check) + '</b><span>' + esc(d.reason) + '</span></li>';
        }).join('') + '</ul></details>');
    }

    if (m.missing) {
      parts.push('<p class="whymissing"><b>What this cannot see.</b> ' +
                 esc(m.missing) + '</p>');
    }

    if (s.coverage && s.coverage.missing && s.coverage.missing.length) {
      parts.push(
        '<details class="whydrop"><summary>' + s.coverage.missing.length +
        ' figure' + (s.coverage.missing.length === 1 ? '' : 's') +
        ' the data source did not publish</summary><ul>' +
        s.coverage.missing.slice(0, 14).map(function (x) {
          return '<li><b>' + esc(x) + '</b></li>';
        }).join('') + '</ul></details>');
    }

    if (m.source) {
      parts.push('<p class="whysrc">Classified from ' + esc(m.source) + '.</p>');
    }

    host.innerHTML = parts.join('');
  }

  /* ── 4 · wrap render() ──────────────────────────────────────────────── */

  function install() {
    if (typeof window.render !== 'function' || window.render.__v3) return;
    var orig = window.render;
    var patched = function (d) {
      var s = null;
      try {
        s = (d && d.scoring && d.scoring.score != null) ? d.scoring : null;
        if (s) {
          // The original render() draws from d.verdict. Swapping the object
          // means the score, label, summary, basis and the animated arc all
          // pick up v3 with no change to the drawing code.
          d.verdict = {
            score: s.score, label: s.label, tone: s.tone,
            summary: s.summary || '',
            basis: s.basis + ' · confidence ' + s.confidence + '%'
          };
        }
      } catch (e) { s = null; }

      var out = orig.apply(this, arguments);

      try {
        buildSwitch();
        var hint = $('hzhint');
        if (hint && s) hint.textContent = s.horizon_note || '';
        if (s) { pillarStrip(s); whyPanel(s); }
      } catch (e) { /* never let the extras break the page */ }

      return out;
    };
    patched.__v3 = true;
    window.render = patched;
  }

  /* ── 5 · append the horizon to the analyse request ────────────────────
     Wrapping fetch is narrower than rewriting analyse(): it touches exactly
     the one URL and leaves every other request on the page alone. */

  var origFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var url = (typeof input === 'string') ? input : (input && input.url);
      if (url && url.indexOf('/analyze?ticker=') !== -1 &&
          url.indexOf('horizon=') === -1) {
        var next = url + '&horizon=' + encodeURIComponent(get());
        if (typeof input === 'string') { input = next; }
        else { input = new Request(next, input); }
      }
    } catch (e) { /* fall through with the original request */ }
    return origFetch.call(this, input, init);
  };

  /* ── 6 · styles ───────────────────────────────────────────────────────
     Injected rather than shipped as a sixth stylesheet, so this whole feature
     is one file to upload and one line to remove. Every colour comes from the
     page's own tokens, so light and dark both work with no extra rules. */

  var CSS = [
    '.hzswitch{display:flex;align-items:center;gap:12px;flex-wrap:wrap;',
    '  margin:0 0 22px}',
    '.hzswitch .hzlbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;',
    '  text-transform:uppercase;color:var(--mute)}',
    '.hzseg{display:inline-flex;padding:3px;background:var(--paper-2);',
    '  border:1px solid var(--rule-2);border-radius:999px;gap:2px}',
    '.hzseg button{border:0;background:none;cursor:pointer;border-radius:999px;',
    '  padding:7px 15px;font-family:var(--mono);font-size:11.5px;letter-spacing:.06em;',
    '  color:var(--ink-2);transition:color var(--t-fast) var(--ease),',
    '  background var(--t-fast) var(--ease)}',
    '.hzseg button:hover:not(.on){color:var(--ink)}',
    '.hzseg button.on{background:var(--ink);color:var(--paper)}',
    '.hzseg button:focus-visible{outline:none;box-shadow:var(--ring)}',
    '.hzhint{font-size:12.5px;color:var(--mute);flex:1;min-width:200px;',
    '  line-height:1.5}',
    '@media(max-width:600px){.hzhint{display:none}}',

    '.sched.sched-v3{display:grid;',
    '  grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0}',
    '.sched-v3 .v3cell{display:flex;flex-direction:column;gap:5px;padding:16px 14px;',
    '  border-left:1px solid var(--rule-2)}',
    '.sched-v3 .v3cell:first-child{border-left:0}',
    '.sched-v3 .v3cell .lbl{font-family:var(--mono);font-size:9.5px;',
    '  letter-spacing:.1em;text-transform:uppercase;color:var(--mute)}',
    '.sched-v3 .v3cell .num{font-family:var(--serif);font-size:30px;line-height:1;',
    '  font-variant-numeric:tabular-nums;color:var(--ink)}',
    '.sched-v3 .v3cell .num small{font-family:var(--mono);font-size:10px;',
    '  color:var(--mute)}',
    '.sched-v3 .v3cell .wt{display:block;height:3px;border-radius:2px;',
    '  background:var(--rule-2);overflow:hidden;margin-top:4px}',
    '.sched-v3 .v3cell .wt i{display:block;height:100%;background:var(--gold-line);',
    '  border-radius:2px;transition:width var(--t) var(--ease-soft)}',
    '.sched-v3 .v3cell .wtx{font-family:var(--mono);font-size:10px;color:var(--mute);',
    '  font-variant-numeric:tabular-nums}',

    '.whywrap{margin:26px 0 0;padding:20px 0 0;border-top:1px solid var(--rule-2)}',
    '.whyhead{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));',
    '  gap:18px;margin-bottom:18px}',
    '.whytitle{display:flex;flex-direction:column;gap:3px;min-width:0}',
    '.whytitle .wk{font-family:var(--mono);font-size:9.5px;letter-spacing:.11em;',
    '  text-transform:uppercase;color:var(--mute)}',
    '.whytitle .wv{font-family:var(--serif);font-size:23px;line-height:1.15;',
    '  color:var(--ink)}',
    '.whytitle .wv.conf-ok{color:var(--pass)}',
    '.whytitle .wv.conf-mid{color:var(--gold-dp,var(--gold))}',
    '.whytitle .wv.conf-low{color:var(--fail)}',
    '.whytitle .wsub{font-size:12.5px;color:var(--mute);line-height:1.5}',
    '.whymatters{font-size:15px;line-height:1.62;color:var(--ink-2);',
    '  max-width:70ch;margin:0 0 14px}',
    '.whycycle,.whynote,.whymissing{font-size:13.5px;line-height:1.6;',
    '  color:var(--ink-2);max-width:70ch;margin:0 0 12px;padding-left:14px;',
    '  border-left:2px solid var(--gold-line)}',
    '.whysrc{font-family:var(--mono);font-size:10.5px;color:var(--mute);',
    '  letter-spacing:.03em;margin:14px 0 0}',
    '.whydrop{margin:0 0 12px;border:1px solid var(--rule-2);border-radius:9px;',
    '  background:var(--paper-2)}',
    '.whydrop summary{cursor:pointer;padding:11px 14px;font-family:var(--mono);',
    '  font-size:11.5px;letter-spacing:.04em;color:var(--ink-2);list-style:none}',
    '.whydrop summary::-webkit-details-marker{display:none}',
    '.whydrop summary::before{content:"+ ";color:var(--gold)}',
    '.whydrop[open] summary::before{content:"\\2212 "}',
    '.whydrop summary:hover{color:var(--ink)}',
    '.whydrop ul{margin:0;padding:0 14px 14px;list-style:none}',
    '.whydrop li{padding:9px 0;border-top:1px solid var(--rule-2)}',
    '.whydrop li b{display:block;font-family:var(--mono);font-size:12px;',
    '  font-weight:500;color:var(--ink);margin-bottom:2px}',
    '.whydrop li span{font-size:13px;color:var(--mute);line-height:1.55}'
  ].join('\n');

  try {
    var st = document.createElement('style');
    st.id = 'altaha-scoring-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  } catch (e) { /* styles are a nicety; the data still renders without them */ }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
  // render() is defined in the page's own script, which may load after this
  // file. Two retry passes cover that ordering without a timer that never stops.
  setTimeout(install, 0);
  setTimeout(install, 800);
})();
