/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — Risk profile

   THE QUESTIONS COME FROM THE SERVER
   Not because the page could not hold them, but because an answer recorded
   today has to still resolve to the same question years from now. One list,
   one place, and the ids stored against a person's answers keep their meaning.

   WHAT THIS DOES AND DOES NOT DO
   It describes somebody's situation and temperament back to them, with the
   working shown. It recommends nothing. What to do about a profile belongs to
   the adviser and lives elsewhere — and the server will not issue advice at
   all until the adviser's identity and registration are configured beside it.

   Signed out, everything works and nothing is stored: the profile is computed
   and shown. Signing in is what makes it a record.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) || '';
  var DRAFT = 'altaha-risk-answers-v1';

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function note(msg, kind) {
    var n = $('prisk_note');
    if (!n) return;
    n.textContent = msg || '';
    n.className = 'rnote' + (kind ? ' ' + kind : '');
  }

  var questions = [], answers = read();

  function read() {
    try { return JSON.parse(localStorage.getItem(DRAFT) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function write() {
    try { localStorage.setItem(DRAFT, JSON.stringify(answers)); } catch (e) {}
  }

  function answered() {
    return questions.filter(function (q) {
      return !q.optional && answers[q.id] !== undefined && answers[q.id] !== '';
    }).length;
  }
  function needed() {
    return questions.filter(function (q) { return !q.optional; }).length;
  }

  function render() {
    var body = $('prisk_body');
    if (!body) return;
    body.replaceChildren();

    questions.forEach(function (q) {
      var box = el('div', 'prq');
      box.append(el('p', 'q', q.label));
      // Every question says why it is being asked. Somebody handing over their
      // income and their fears is owed the reason for each one.
      box.append(el('p', 'why', q.why));

      if (q.kind === 'amount') {
        var input = el('input', 'prq-amt');
        input.type = 'number';
        input.min = '0';
        input.placeholder = q.optional ? 'Optional' : 'e.g. 25000';
        input.setAttribute('aria-label', q.label);
        if (answers[q.id] !== undefined) input.value = answers[q.id];
        input.addEventListener('input', function () {
          var v = Number(input.value);
          if (input.value === '') delete answers[q.id];
          else answers[q.id] = v;
          write(); refreshAction();
        });
        box.append(input);
      } else {
        var opts = el('div', 'prq-opts');
        q.options.forEach(function (o) {
          var b = el('button', 'prq-opt', o.label);
          b.type = 'button';
          b.setAttribute('aria-pressed', String(answers[q.id] === o.value));
          b.addEventListener('click', function () {
            answers[q.id] = o.value;
            write();
            opts.querySelectorAll('.prq-opt').forEach(function (x) {
              x.setAttribute('aria-pressed', 'false');
            });
            b.setAttribute('aria-pressed', 'true');
            refreshAction();
          });
          opts.append(b);
        });
        box.append(opts);
      }
      body.append(box);
    });

    var act = el('div', 'pffork-act');
    act.id = 'prisk_act';
    var go = el('button', 'pfbtn', 'See my profile');
    go.type = 'button';
    go.id = 'prisk_go';
    go.addEventListener('click', submit);
    var reset = el('button', 'pfbtn ghost', 'Start again');
    reset.type = 'button';
    reset.addEventListener('click', function () {
      answers = {};
      write();
      var old = $('prisk_result');
      if (old) old.remove();
      render();
      note('');
    });
    act.append(go, reset);
    body.append(act);
    refreshAction();
  }

  function refreshAction() {
    var go = $('prisk_go');
    if (!go) return;
    var left = needed() - answered();
    go.disabled = left > 0;
    go.textContent = left > 0
      ? left + ' question' + (left === 1 ? '' : 's') + ' to go'
      : 'See my profile';
  }

  function post(path, body) {
    var auth = window.AltahaAuth;
    if (auth && auth.authed()) return auth.fetch(path, { method: 'POST', body: body });
    return fetch(API + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body
    });
  }

  function submit() {
    var auth = window.AltahaAuth;
    // Signed out there is nobody to record it against, so it is computed and
    // shown and not kept. Said plainly rather than quietly not saving.
    if (!auth || !auth.authed()) {
      note('Sign in to keep this profile on your account — showing it here for now.', '');
      show(localAssess());
      return;
    }
    note('Working it out…');
    post('/me/risk-profile', JSON.stringify({ answers: answers }))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.d && res.d.detail ? res.d.detail : 'Could not save that.');
        note('Saved to your account.', 'good');
        show(res.d.profile);
      })
      .catch(function (e) {
        note(e && e.message ? e.message : 'Could not reach your account.', 'warn');
      });
  }

  /* Signed out, the same arithmetic without the record. Kept deliberately
     simple: the server's assessment is the one that counts, and this exists so
     a reader who has not signed in still sees an answer. */
  function localAssess() {
    function axis(name) {
      var w = 0, earned = 0;
      questions.forEach(function (q) {
        if (q.axis !== name || !q.weight) return;
        var o = (q.options || []).filter(function (x) { return x.value === answers[q.id]; })[0];
        if (!o) return;
        w += q.weight; earned += q.weight * o.score;
      });
      return w ? Math.round(earned / w * 10) / 10 : 0;
    }
    var capacity = axis('capacity'), tolerance = axis('tolerance');
    var score = Math.min(capacity, tolerance);
    var hit = (window.__ALTAHA_BANDS || []).filter(function (b) {
      return score >= b.from && score < b.to;
    })[0] || { band: '—', note: '' };
    return {
      capacity: capacity, tolerance: tolerance, score: score,
      band: hit.band, band_note: hit.note,
      gap: Math.round(Math.abs(capacity - tolerance) * 10) / 10,
      binding: capacity > tolerance ? 'tolerance' : tolerance > capacity ? 'capacity' : 'both',
      binding_note: capacity > tolerance
        ? 'Your circumstances could carry more risk than you would be comfortable holding.'
        : tolerance > capacity
          ? 'You are willing to carry more risk than your circumstances can absorb today.'
          : 'Circumstances and temperament agree.'
    };
  }

  function show(p) {
    var old = $('prisk_result');
    if (old) old.remove();
    var box = el('div', 'prres');
    box.id = 'prisk_result';

    box.append(el('h4', '', p.band));
    box.append(el('p', 'band-note', p.band_note || ''));

    var axes = el('div', 'prres-axes');
    [['Capacity', p.capacity], ['Temperament', p.tolerance], ['Profile', p.score]]
      .forEach(function (pair) {
        var a = el('div', 'prres-axis');
        a.append(el('span', 'k', pair[0]));
        a.append(el('span', 'v', pair[1]));
        axes.append(a);
      });
    box.append(axes);

    // The gap, spelled out. Two numbers and a band tell somebody less about
    // their own money than the sentence explaining which one is the limit.
    var gap = el('p', 'prres-gap');
    if (p.binding === 'both') {
      gap.textContent = p.binding_note;
    } else {
      gap.append(document.createTextNode('The lower of the two decides, so your profile is '));
      gap.append(el('b', '', String(p.score)));
      gap.append(document.createTextNode('. ' + (p.binding_note || '')));
    }
    box.append(gap);

    $('riskprofile').append(box);
    box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function load() {
    if (!$('prisk_body')) return;
    fetch(API + '/planner/questions')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.questions || !d.questions.length) {
          note('The questionnaire could not be loaded. Please refresh.', 'warn');
          return;
        }
        questions = d.questions;
        window.__ALTAHA_BANDS = d.bands || [];
        render();
      })
      .catch(function () {
        note('The questionnaire could not be loaded. Please refresh.', 'warn');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else { load(); }

  window.AltahaRisk = { assess: localAssess, answers: function () { return answers; } };
})();
