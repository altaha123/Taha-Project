/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Money planner

   WHAT THIS SCREEN IS FOR
   It used to be a form: fifteen empty boxes, and a verdict that appeared only
   after most of them were filled. Somebody who arrived saw a form, and
   somebody who finished had no reason to return — nothing was remembered, and
   the answer was a letter.

   It now opens with an answer and keeps it: the month this household's
   investments could pay its bills. Four numbers produce it. Everything else
   on the screen is a tool that moves it, and each is a reason to come back:

     Your date   the path, and the moves that bring the date closer
     Price tag   what a purchase or a habit costs in days of freedom
     Goals       dated goals, paid from the same pot, with the date they cost
     Check-in    one figure a month; a streak, and ahead-or-behind the plan
     Budget      the itemised household ledger and the salary-day split
     Tax         old regime against new
     Risk        the questionnaire (planner-risk.js, unchanged)

   NOTHING LEAVES THIS BROWSER
   The numbers are kept in localStorage so the screen can greet somebody with
   their own date instead of an empty form. They are never sent anywhere —
   there is no request in this file — and "Clear my numbers" removes them.
   Analytics events from here carry which tab and which preset, never a rupee.

   THE ARITHMETIC IS NOT HERE. It is in planner-math.js, where node can test
   it. This file turns its answers into words, a chart and a few lists.

   ALLOCATE READS WHAT THIS PUBLISHES. `window.AltahaPlannerState` keeps the
   shape the old planner gave it, so the cushion in the Allocation plan is
   sized from these numbers without asking for them twice.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var M = window.AltahaPlannerMath;
  var doc = document;
  var KEY = 'altaha-planner-v1';

  var TABS = [
    { id: 'date',    label: 'Your date' },
    { id: 'tag',     label: 'Price tag' },
    { id: 'goals',   label: 'Goals' },
    { id: 'checkin', label: 'Check-in' },
    { id: 'budget',  label: 'Budget' },
    { id: 'tax',     label: 'Tax' },
    { id: 'risk',    label: 'Risk profile' }
  ];
  /* id, label, a starting cost in today's rupees, years away. Starting points
     to edit, not estimates of anybody's life. */
  var GOAL_KINDS = [
    ['home', 'Home deposit', 2000000, 5], ['car', 'Car', 1000000, 3],
    ['school', 'Child’s education', 2500000, 12], ['wedding', 'Wedding', 1500000, 4],
    ['trip', 'Big trip', 300000, 1], ['other', 'Something else', '', 3]
  ];
  var TAG_IDEAS = [
    ['New phone', 80000, false], ['Holiday', 200000, false], ['Car', 1000000, false],
    ['Daily coffee', 4500, true], ['Streaming', 1500, true]
  ];
  var EXAMPLE = { age: '32', salary: '150000', spend: '85000', invested: '1800000', liquid: '300000' };
  var BUCKET = {
    safe:   ['Kept safe', 'Needed inside three years, so it is assumed to earn what deposits earn. A fall in the year you need it would end the plan.'],
    mixed:  ['Part safe, part growth', 'Three to seven years out: assumed to earn between deposits and long-run growth.'],
    growth: ['Long-run growth', 'More than seven years out, so it is assumed to earn what the long run earns.']
  };

  var ICON = {
    arrow: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"/></svg>',
    check: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 5"/></svg>',
    share: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 10V2M5 4.5L8 2l3 2.5M3 9v4h10V9"/></svg>',
    x: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    up: '<svg class="arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13V3M4 7l4-4 4 4"/></svg>',
    cal: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="12" height="11" rx="2"/><path d="M2 6.5h12M5 1.5v3M11 1.5v3"/></svg>'
  };

  function $(id) { return doc.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function track(ev, props) { if (window.AltahaTrack) window.AltahaTrack(ev, props || {}); }
  function still() {
    try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    catch (e) { return true; }
  }
  function today() { return new Date(); }
  function isoDay(dt) {
    return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
  }
  function dayLabel(iso) {
    var p = String(iso || '').split('-');
    return p.length === 3 ? Number(p[2]) + ' ' + M.monthName(p[0] + '-' + p[1], true).split(' ')[0] : '';
  }
  function uid() { return 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function digits(v) { return String(v == null ? '' : v).replace(/\D/g, '').replace(/^0+(?=\d)/, '').slice(0, 12); }
  /* What a rupee box shows: the digits, grouped the way they are said. */
  function shown(v) {
    var s = digits(v);
    return s ? Number(s).toLocaleString('en-IN') : '';
  }
  function pctText(n) { return String(Number(Number(n).toFixed(1))); }

  /* ── What is kept ────────────────────────────────────────────────────────── */

  function fresh() {
    return { v: 1, age: '', salary: '', other: '', spend: '', invested: '', liquid: '', put: '',
             cats: {}, stepUp: '', ret: '', infl: '', multiple: '', after: '',
             goals: [], log: [], tags: [], tax: {}, example: false, seen: null, prev: null };
  }
  function load() {
    try {
      var s = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (s && s.v === 1) {
        var f = fresh(), k;
        for (k in s) if (Object.prototype.hasOwnProperty.call(s, k)) f[k] = s[k];
        ['goals', 'log', 'tags'].forEach(function (key) { if (!Array.isArray(f[key])) f[key] = []; });
        ['cats', 'tax'].forEach(function (key) { if (!f[key] || typeof f[key] !== 'object') f[key] = {}; });
        return f;
      }
    } catch (e) {}
    return fresh();
  }
  var saveTimer = null, stored = null;
  /* Writes only what has changed since the last write. Two reasons, both
     silent when wrong: a visitor who never opens the planner should not have
     an empty record left in their browser by the page merely loading, and a
     second tab left open on old numbers must not overwrite newer ones with
     them as it closes. */
  function flush() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    var json = JSON.stringify(state);
    if (json === stored) return;
    try { localStorage.setItem(KEY, json); stored = json; } catch (e) {}
  }
  /* Debounced: a slider emits an event per pixel and localStorage is
     synchronous. `flush` runs on blur and on leaving the page, so the last
     keystroke before a reload is never the one that is lost. */
  function save() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, 220);
  }
  function get(path) {
    var p = path.split('.');
    return p.length === 2 ? (state[p[0]] || {})[p[1]] : state[path];
  }
  function set(path, v) {
    var p = path.split('.');
    if (p.length === 2) {
      if (!state[p[0]] || typeof state[p[0]] !== 'object') state[p[0]] = {};
      state[p[0]][p[1]] = v;
    } else state[path] = v;
  }

  var host = null;
  var state = load();
  stored = JSON.stringify(state);
  var d = null;                       // everything derived from `state`
  var ticked = [];                    // what-if moves; a thought, so never saved
  var drafts = {                      // forms that are not the plan until submitted
    tag: { name: '', cost: '', monthly: false },
    goal: { id: null, kind: 'other', name: '', cost: '', years: '', saved: '' },
    ck: { invested: '', liquid: '' }
  };
  var announced = false;

  /* ── Field builders ──────────────────────────────────────────────────────── */

  /* A rupee box. The note sits beside the label, not inside it: a note can
     hold a link ("Edit it"), and a control inside a <label> is a click that
     lands in two places. It is tied to the box by aria-describedby instead. */
  var boxes = 0;
  function moneyField(path, label, o) {
    o = o || {};
    var draft = o.draft, id = o.id || 'mp-box-' + (++boxes), noteId = o.noteId || id + '-note';
    return '<div class="mp-field"><label class="k" for="' + id + '"><span>' + label + '</span>' +
        '<em data-short="' + (draft ? 'd:' : '') + path + '"></em></label>' +
      '<span class="mp-inr"><i aria-hidden="true">₹</i>' +
      '<input class="mp-in" type="text" inputmode="numeric" autocomplete="off" data-kind="inr" id="' + id + '" ' +
        (draft ? 'data-d="' : 'data-f="') + path + '"' + (o.note ? ' aria-describedby="' + noteId + '"' : '') +
        ' placeholder="' + esc(o.ph || '0') + '" value="' +
        esc(shown(draft ? drafts[path.split('.')[0]][path.split('.')[1]] : get(path))) + '"></span>' +
      (o.note ? '<span class="mp-note" id="' + noteId + '">' + (o.note === true ? '' : o.note) + '</span>' : '') +
      '</div>';
  }
  function dialField(path, label, min, max, step) {
    return '<label class="mp-field mp-dial"><span class="k"><span>' + label + '</span>' +
      '<b data-out="' + path + '"></b></span>' +
      '<input type="range" data-f="' + path + '" data-kind="dial" id="mp-' + path.toLowerCase() + '" min="' + min +
      '" max="' + max + '" step="' + step + '" value="' + M.dial(get(path), M.DEFAULTS[path]) + '"></label>';
  }

  /* ── The frame: built once, so nothing typed is ever re-rendered away ────── */

  function frame() {
    var needs = M.CATS.filter(function (c) { return c.kind === 'need'; });
    var wants = M.CATS.filter(function (c) { return c.kind === 'want'; });
    function cat(c) { return moneyField('cats.' + c.id, esc(c.label)); }

    return '' +
    '<section class="mp-hero" id="mp-hero" aria-labelledby="mp-when"></section>' +
    '<p class="mp-sr" id="mp-live" role="status" aria-live="polite"></p>' +

    '<div class="mp-tabs" role="tablist" aria-label="Planner tools" id="mp-tabs">' +
      TABS.map(function (t) {
        return '<button type="button" class="mp-tab" role="tab" id="mp-tab-' + t.id + '" data-tab="' + t.id +
          '" aria-controls="mp-panel-' + t.id + '" aria-selected="false" tabindex="-1">' +
          '<span>' + t.label + '</span><span class="mp-badge" data-badge="' + t.id + '"></span></button>';
      }).join('') +
      '<span class="mp-pin" id="mp-pin" aria-hidden="true"></span>' +
    '</div>' +

    /* ── Your date ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-date" aria-labelledby="mp-tab-date" hidden>' +
      '<div class="mp-card" id="mp-numbers">' +
        '<div class="mp-card-h"><h3>Your numbers</h3><span>Monthly, in hand</span></div>' +
        '<div class="mp-fields">' +
          '<label class="mp-field"><span class="k"><span>Your age</span></span>' +
            '<input class="mp-in" type="text" inputmode="numeric" autocomplete="off" maxlength="2" data-f="age" ' +
            'data-kind="age" id="mp-age" placeholder="e.g. 32" value="' + esc(digits(state.age)) + '"></label>' +
          moneyField('salary', 'Take-home pay', { id: 'mp-salary', ph: 'e.g. 1,20,000', note: true, noteId: 'mp-salary-note' }) +
          moneyField('spend', 'You spend', { id: 'mp-spend', ph: 'e.g. 70,000', note: true, noteId: 'mp-spend-note' }) +
          moneyField('invested', 'Invested so far', { id: 'mp-invested', ph: 'e.g. 8,00,000',
            note: 'Funds, shares, EPF, PPF, NPS. Not the home you live in.' }) +
        '</div>' +
        '<div class="mp-fields is-2">' +
          moneyField('put', 'Put away each month', { id: 'mp-put', note: true, noteId: 'mp-put-note' }) +
          dialField('stepUp', 'Raise it every year by', 0, 20, 1) +
        '</div>' +
        '<details class="mp-assume" id="mp-assume">' +
          '<summary id="mp-assume-sum"></summary>' +
          '<div class="mp-fields">' +
            dialField('ret', 'Investments earn', 4, 15, 0.5) +
            dialField('infl', 'Prices rise', 3, 10, 0.5) +
            dialField('multiple', 'Freedom takes', 20, 40, 1) +
            dialField('after', 'Life after work costs', 50, 150, 5) +
          '</div>' +
          '<div class="mp-working" id="mp-working"></div>' +
          '<div class="mp-acts"><button type="button" class="mp-link" data-act="defaults">Back to the defaults</button></div>' +
        '</details>' +
      '</div>' +
      '<div class="mp-card" data-ready>' +
        '<div class="mp-card-h"><h3>The path</h3><span>In today’s rupees</span></div>' +
        '<ul class="mp-legend" id="mp-path-legend"></ul>' +
        '<div class="mp-chart" id="mp-path-chart"></div>' +
        '<p class="mp-quiet" id="mp-path-note"></p>' +
        '<details class="mp-data" id="mp-path-data"><summary>Show these numbers as a table</summary>' +
          '<div class="mp-scroll" id="mp-path-table"></div></details>' +
      '</div>' +
      '<div class="mp-card" data-ready>' +
        '<div class="mp-card-h"><h3>What moves your date</h3><span>Tick to try</span></div>' +
        '<p class="mp-sub">Each line is your plan with one thing changed. Tick any of them to see the date they would give you together. Ticking changes nothing you have saved.</p>' +
        '<div id="mp-moves"></div>' +
      '</div>' +
      '<div class="mp-next" id="mp-next"></div>' +
    '</section>' +

    /* ── Price tag ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-tag" aria-labelledby="mp-tab-tag" hidden>' +
      '<div class="mp-card">' +
        '<div class="mp-card-h"><h3>What does it really cost?</h3><span>In days, not rupees</span></div>' +
        '<p class="mp-sub">Everything with a price has a second price: the days you work to pay for it, and how far it moves the month work becomes optional. Type the first price and read the second.</p>' +
        '<div class="mp-tagform">' +
          '<label class="mp-field"><span class="k"><span>What is it?</span></span>' +
            '<input class="mp-in is-text" type="text" maxlength="40" autocomplete="off" data-d="tag.name" id="mp-tag-name" placeholder="A new phone"></label>' +
          moneyField('tag.cost', 'It costs', { id: 'mp-tag-cost', ph: 'e.g. 80,000', draft: true }) +
          '<div class="mp-seg" role="group" aria-label="How often">' +
            '<button type="button" data-act="tag-mode" data-mode="once" aria-pressed="true">Once</button>' +
            '<button type="button" data-act="tag-mode" data-mode="monthly" aria-pressed="false">Every month</button>' +
          '</div>' +
        '</div>' +
        '<div class="mp-picks" aria-label="Examples">' +
          TAG_IDEAS.map(function (t, i) {
            return '<button type="button" class="mp-pick" data-act="tag-idea" data-i="' + i + '">' + esc(t[0]) +
              ' · ' + M.inr(t[1]) + (t[2] ? ' a month' : '') + '</button>';
          }).join('') +
        '</div>' +
        '<div id="mp-tag-out"></div>' +
      '</div>' +
      '<div class="mp-card" id="mp-kept-card" hidden>' +
        '<div class="mp-card-h"><h3>Things you priced</h3><span id="mp-kept-count"></span></div>' +
        '<ul class="mp-kept" id="mp-kept"></ul>' +
        '<p class="mp-quiet" id="mp-kept-sum"></p>' +
      '</div>' +
    '</section>' +

    /* ── Goals ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-goals" aria-labelledby="mp-tab-goals" hidden>' +
      '<div id="mp-goals-sum"></div>' +
      '<div class="mp-goals" id="mp-goals-list"></div>' +
      '<div class="mp-card" id="mp-goal-form">' +
        '<div class="mp-card-h"><h3 id="mp-goal-title">Add a goal</h3><span>Costs in today’s rupees</span></div>' +
        '<p class="mp-sub">A goal is money with a date on it. Give it today’s price and how far off it is; the planner works out what it will cost by then, what to set aside each month, and what it does to your date.</p>' +
        '<div class="mp-picks" id="mp-goal-kinds">' +
          GOAL_KINDS.map(function (k) {
            return '<button type="button" class="mp-pick" data-act="goal-kind" data-kind="' + k[0] + '" aria-pressed="false">' + esc(k[1]) + '</button>';
          }).join('') +
        '</div>' +
        '<div class="mp-fields" style="margin-top:18px">' +
          '<label class="mp-field"><span class="k"><span>Call it</span></span>' +
            '<input class="mp-in is-text" type="text" maxlength="40" autocomplete="off" data-d="goal.name" id="mp-goal-name" placeholder="Home deposit"></label>' +
          moneyField('goal.cost', 'Costs today', { id: 'mp-goal-cost', ph: 'e.g. 20,00,000', draft: true }) +
          '<label class="mp-field"><span class="k"><span>Years from now</span></span>' +
            '<input class="mp-in" type="text" inputmode="numeric" maxlength="2" autocomplete="off" data-d="goal.years" data-kind="age" id="mp-goal-years" placeholder="e.g. 5"></label>' +
          moneyField('goal.saved', 'Already set aside', { id: 'mp-goal-saved', draft: true }) +
        '</div>' +
        '<div class="mp-acts">' +
          '<button type="button" class="mp-btn" data-act="goal-save" id="mp-goal-save">Add this goal</button>' +
          '<button type="button" class="mp-btn is-ghost" data-act="goal-cancel" id="mp-goal-cancel" hidden>Cancel</button>' +
          '<span class="mp-msg" id="mp-goal-msg" role="status"></span>' +
        '</div>' +
      '</div>' +
    '</section>' +

    /* ── Check-in ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-checkin" aria-labelledby="mp-tab-checkin" hidden>' +
      '<div class="mp-card">' +
        '<div class="mp-card-h"><h3>Once a month, one minute</h3><span id="mp-ck-status"></span></div>' +
        '<p class="mp-sub">Type what your statements say today. It keeps your date honest, and it is the only way to know whether you are ahead of your own plan or behind it.</p>' +
        '<div class="mp-fields is-2">' +
          moneyField('ck.invested', 'Invested as of today', { id: 'mp-ck-invested', ph: 'e.g. 8,40,000', draft: true,
            note: 'Funds, shares, EPF, PPF, NPS: what the statements say.' }) +
          moneyField('ck.liquid', 'Your cushion', { id: 'mp-ck-liquid', draft: true, note: 'Savings account, FDs, liquid funds.' }) +
        '</div>' +
        '<div class="mp-acts">' +
          '<button type="button" class="mp-btn" data-act="ck-log" id="mp-ck-go"></button>' +
          '<button type="button" class="mp-btn is-ghost" data-act="ck-ics">' + ICON.cal + 'Remind me on the 1st of every month</button>' +
          '<span class="mp-msg" id="mp-ck-msg" role="status"></span>' +
        '</div>' +
        '<div id="mp-ck-out"></div>' +
      '</div>' +
      '<div class="mp-card" id="mp-ck-card" hidden>' +
        '<div class="mp-card-h"><h3>You against your plan</h3><span>Rupees of the day</span></div>' +
        '<ul class="mp-legend">' +
          '<li><i class="mp-key"></i>What you logged</li>' +
          '<li><i class="mp-key quiet"></i>Your plan, from your first check-in</li></ul>' +
        '<div class="mp-chart" id="mp-ck-chart"></div>' +
        '<p class="mp-quiet">The plan line climbs at your assumed return every single month. Markets do not. One month below the line says little; a year below it is worth a look.</p>' +
        '<div class="mp-scroll"><table class="mp-log" id="mp-ck-log"></table></div>' +
      '</div>' +
    '</section>' +

    /* ── Budget ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-budget" aria-labelledby="mp-tab-budget" hidden>' +
      '<div class="mp-two">' +
        '<div>' +
          '<div class="mp-card">' +
            '<div class="mp-card-h"><h3>Income</h3><span>Monthly, in hand</span></div>' +
            '<div class="mp-fields is-2">' +
              moneyField('salary', 'Take-home pay', { ph: 'e.g. 1,20,000' }) +
              moneyField('other', 'Other income', { note: 'Rent, interest, side income.' }) +
            '</div>' +
          '</div>' +
          '<div class="mp-card">' +
            '<div class="mp-card-h"><h3>Spending</h3><span>Monthly</span></div>' +
            '<p class="mp-sub">Optional. Itemise and the planner can judge your EMI load and your needs-and-wants split, and offer a trim that is yours rather than generic.</p>' +
            '<div class="mp-group"><span>Needs</span><b id="mp-needs-sum"></b></div>' +
            '<div class="mp-fields is-2">' + needs.map(cat).join('') + '</div>' +
            '<div class="mp-group"><span>Wants</span><b id="mp-wants-sum"></b></div>' +
            '<div class="mp-fields is-2">' + wants.map(cat).join('') + '</div>' +
            '<p class="mp-quiet" id="mp-bud-total"></p>' +
          '</div>' +
          '<div class="mp-card">' +
            '<div class="mp-card-h"><h3>Cushion</h3><span>For the emergency check</span></div>' +
            '<div class="mp-fields is-2">' +
              moneyField('liquid', 'Liquid savings today', { ph: 'e.g. 2,00,000', note: 'Savings account, FDs, liquid funds.' }) +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div>' +
          '<div class="mp-card" id="mp-health"></div>' +
          '<div class="mp-card" id="mp-payday"></div>' +
        '</div>' +
      '</div>' +
    '</section>' +

    /* ── Tax ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-tax" aria-labelledby="mp-tab-tax" hidden>' +
      '<div class="mp-card">' +
        '<div class="mp-card-h"><h3>Old regime or new?</h3><span>AY 2026-27</span></div>' +
        '<p class="mp-sub">Annual figures, per the Finance Act 2025 slabs. Surcharge above ₹50L income is not modelled.</p>' +
        '<div class="mp-fields is-3">' +
          moneyField('tax.gross', 'Gross annual salary', { id: 'mp-tax-gross', ph: 'e.g. 15,00,000' }) +
          moneyField('tax.c80', '80C', { note: 'PF, ELSS, LIC. Capped at ₹1.5 L.' }) +
          moneyField('tax.d80', '80D', { note: 'Health insurance premiums.' }) +
          moneyField('tax.nps', 'NPS 80CCD(1B)', { note: 'Capped at ₹50,000.' }) +
          moneyField('tax.hl', 'Home loan interest 24(b)', { note: 'Capped at ₹2 L.' }) +
          moneyField('tax.hra', 'HRA exemption', { note: 'The computed amount.' }) +
        '</div>' +
        '<div id="mp-tax-out"></div>' +
      '</div>' +
    '</section>' +

    /* ── Risk profile: the existing section is moved in here on mount ── */
    '<section class="mp-panel" role="tabpanel" id="mp-panel-risk" aria-labelledby="mp-tab-risk" hidden></section>' +

    '<p class="mp-foot"><span>Arithmetic on your own numbers, not investment advice. Saved in this browser only; nothing you type here is sent anywhere.</span>' +
      '<button type="button" class="mp-link" data-act="reset">Clear my numbers</button></p>';
  }

  /* ── A small line chart ──────────────────────────────────────────────────────
     Two of them on this screen and no library worth loading for either. Drawn
     at the pixel width it is given, so the labels are the size they say they
     are on a phone; redrawn when that width changes. The hover layer reads a
     value at any year, and the same figures are in a table under each chart,
     so nothing is gated on being able to hover. */

  /* A round step that gives three to five gridlines, and the first multiple
     of it past the data. Rounding the top itself to 1-2-5 left half the plot
     empty whenever the data ended just past a round number. */
  function niceStep(v) {
    if (!(v > 0)) return 1;
    var raw = v / 4, pow = Math.pow(10, Math.floor(Math.log10(raw)));
    var steps = [1, 1.5, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * pow >= raw) return steps[i] * pow;
    return 10 * pow;
  }

  function drawChart(box, cfg) {
    var W = Math.max(280, Math.round(box.clientWidth || 640));
    var H = W < 520 ? 240 : 300;
    var mL = 54, mR = 18, mT = 30, mB = 30, pw = W - mL - mR, ph = H - mT - mB;
    var y0 = cfg.y0 || 0, stepY = niceStep(cfg.top - y0);
    var yMax = y0 + stepY * Math.max(1, Math.ceil((cfg.top - y0) / stepY - 1e-9));
    function X(v) { return mL + (cfg.x1 === cfg.x0 ? 0 : (v - cfg.x0) / (cfg.x1 - cfg.x0)) * pw; }
    function Y(v) { return mT + (1 - (Math.max(y0, v) - y0) / (yMax - y0)) * ph; }
    function n(v) { return v.toFixed(1); }
    var out = [], i;

    out.push('<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H +
      '" role="img" tabindex="0" aria-label="' + esc(cfg.label) + '">');
    for (i = 0; y0 + stepY * i <= yMax + 1e-6; i++) {
      var gv = y0 + stepY * i, gy = Y(gv);
      out.push('<line class="' + (i ? 'grid' : 'axis') + '" x1="' + mL + '" x2="' + (W - mR) + '" y1="' + n(gy) + '" y2="' + n(gy) + '"/>');
      out.push('<text x="' + (mL - 8) + '" y="' + n(gy + 3.5) + '" text-anchor="end">' + esc(M.short(gv)) + '</text>');
    }
    if (cfg.xTitle) out.push('<text x="' + (mL - 8) + '" y="' + (H - 9) + '" text-anchor="end">' + esc(cfg.xTitle) + '</text>');
    cfg.xTicks.forEach(function (t, k) {
      var tx = X(t.x), anchor = k === 0 ? 'start' : (tx > W - mR - t.label.length * 3.4 ? 'end' : 'middle');
      out.push('<text x="' + n(tx) + '" y="' + (H - 9) + '" text-anchor="' + anchor + '">' + esc(t.label) + '</text>');
    });

    /* Direct labels are placed, not hoped for: each tries its positions in
       order and takes the first that is inside the plot and clear of every
       label already down. One that fits nowhere is left out — the legend,
       the hover readout and the table all still carry it. */
    var taken = [], labels = [];
    function place(text, cls, spots) {
      var w = text.length * 6.4 + 6;
      for (var k = 0; k < spots.length; k++) {
        var sp = spots[k], x0 = sp.end ? sp.x - w : sp.x, x1 = x0 + w;
        if (x0 < mL || x1 > W - 2 || sp.y < mT - 12 || sp.y > H - mB - 4) continue;
        if (taken.some(function (b) { return x0 < b.x1 + 8 && x1 > b.x0 - 8 && Math.abs(b.y - sp.y) < 16; })) continue;
        taken.push({ x0: x0, x1: x1, y: sp.y });
        labels.push('<text class="' + cls + '" x="' + n(sp.x) + '" y="' + n(sp.y) + '" text-anchor="' +
          (sp.end ? 'end' : 'start') + '">' + esc(text) + '</text>');
        return true;
      }
      return false;
    }

    // Threshold lines: dashed because they are thresholds, not data.
    (cfg.lines || []).forEach(function (ln) {
      var ly = Y(ln.y);
      out.push('<line class="goal ' + (ln.cls || '') + '" x1="' + mL + '" x2="' + (W - mR) + '" y1="' + n(ly) + '" y2="' + n(ly) + '"/>');
    });

    cfg.series.forEach(function (s) {
      if (!s.pts.length) return;
      var path = s.pts.map(function (p, k) { return (k ? 'L' : 'M') + n(X(p.x)) + ' ' + n(Y(p.y)); }).join(' ');
      if (s.wash) {
        out.push('<path class="wash" d="' + path + ' L' + n(X(s.pts[s.pts.length - 1].x)) + ' ' + n(Y(y0)) +
          ' L' + n(X(s.pts[0].x)) + ' ' + n(Y(y0)) + ' Z"/>');
      }
      out.push('<path class="line ' + s.cls + '" d="' + path + '"/>');
      if (s.dots) s.pts.forEach(function (p) {
        out.push('<circle class="mp-pt ' + s.cls + '" r="4.5" cx="' + n(X(p.x)) + '" cy="' + n(Y(p.y)) + '"/>');
      });
    });

    // The crossing itself, labelled — the one point on the chart that is the
    // story, so it is placed before the lines it sits on are named.
    (cfg.marks || []).forEach(function (mk) {
      var mx = X(mk.x), my = Y(mk.y);
      out.push('<circle class="mp-pt ' + mk.cls + '" r="5.5" cx="' + n(mx) + '" cy="' + n(my) + '"/>');
      var up = my - 12, down = my + 22, text = (W < 520 && mk.brief) ? mk.brief : mk.label;
      if (text) place(text, 'mp-lbl', mk.below
        ? [{ x: mx + 10, y: down }, { x: mx - 10, y: down, end: true }, { x: mx - 10, y: up, end: true }, { x: mx + 10, y: up }]
        : [{ x: mx - 10, y: up, end: true }, { x: mx + 10, y: up }, { x: mx + 10, y: down }, { x: mx - 10, y: down, end: true }]);
    });
    (cfg.lines || []).forEach(function (ln, k) {
      var ly = Y(ln.y), over = ly - 8, under = ly + 17;
      place(ln.label, 'mp-lbl is-quiet', k
        ? [{ x: mL + 6, y: under }, { x: W - mR - 4, y: under, end: true }, { x: mL + 6, y: over }, { x: W - mR - 4, y: over, end: true }]
        : [{ x: mL + 6, y: over }, { x: W - mR - 4, y: over, end: true }, { x: mL + 6, y: under }, { x: W - mR - 4, y: under, end: true }]);
    });
    out.push(labels.join(''));

    out.push('<g class="hover" visibility="hidden"><line class="hair" y1="' + mT + '" y2="' + (H - mB) + '"/>');
    cfg.series.forEach(function (s) { out.push('<circle class="mp-pt ' + s.cls + '" r="4.5" data-s="' + s.cls + '"/>'); });
    out.push('</g></svg>');

    box.innerHTML = out.join('');
    var tip = doc.createElement('div');
    tip.className = 'mp-tip';
    tip.hidden = true;
    box.appendChild(tip);

    var svg = box.querySelector('svg'), hover = svg.querySelector('.hover');
    var hair = hover.querySelector('.hair'), at = -1;

    function show(k) {
      var s = cfg.samples[k];
      if (!s) return;
      at = k;
      var sx = X(s.x);
      hair.setAttribute('x1', n(sx)); hair.setAttribute('x2', n(sx));
      hover.setAttribute('visibility', 'visible');
      hover.querySelectorAll('circle').forEach(function (c) {
        var row = s.rows.filter(function (r) { return r.cls === c.getAttribute('data-s'); })[0];
        if (row && row.value != null) {
          c.setAttribute('cx', n(sx)); c.setAttribute('cy', n(Y(row.value)));
          c.removeAttribute('visibility');
        } else c.setAttribute('visibility', 'hidden');
      });
      tip.replaceChildren();
      var head = doc.createElement('span');
      head.className = 'h'; head.textContent = s.head;
      tip.appendChild(head);
      s.rows.forEach(function (r) {
        if (r.value == null) return;
        var line = doc.createElement('span'), key = doc.createElement('i'), val = doc.createElement('b');
        line.className = 'r';
        key.className = 'mp-key ' + (r.key || r.cls);
        val.textContent = M.short(r.value);
        line.append(key, doc.createTextNode(r.name), val);
        tip.appendChild(line);
      });
      tip.hidden = false;
      var scale = svg.getBoundingClientRect().width / W || 1;
      var left = sx * scale + 14;
      if (left + tip.offsetWidth > box.clientWidth) left = sx * scale - tip.offsetWidth - 14;
      tip.style.transform = 'translate(' + Math.max(0, Math.round(left)) + 'px,' + (mT + 4) + 'px)';
    }
    function hide() { hover.setAttribute('visibility', 'hidden'); tip.hidden = true; }
    function nearest(clientX) {
      var r = svg.getBoundingClientRect(), px = (clientX - r.left) * (W / (r.width || W)), best = 0, gap = Infinity;
      cfg.samples.forEach(function (s, k) {
        var g = Math.abs(X(s.x) - px);
        if (g < gap) { gap = g; best = k; }
      });
      return best;
    }
    svg.addEventListener('pointermove', function (e) { show(nearest(e.clientX)); });
    svg.addEventListener('pointerdown', function (e) { show(nearest(e.clientX)); });
    svg.addEventListener('pointerleave', function () { if (doc.activeElement !== svg) hide(); });
    svg.addEventListener('focus', function () { show(at > -1 ? at : (cfg.start != null ? cfg.start : cfg.samples.length - 1)); });
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        show(Math.max(0, Math.min(cfg.samples.length - 1, (at < 0 ? 0 : at) + (e.key === 'ArrowLeft' ? -1 : 1))));
      } else if (e.key === 'Escape') hide();
    });
    box._w = W;
  }

  /* ── Painting ────────────────────────────────────────────────────────────── */

  function pctLabel(progress) {
    var pct = Math.round(progress * 100);
    return progress > 0 && pct === 0 ? '&lt;1%' : pct + '%';
  }
  /* The same reading as the ring, for a screen too narrow to seat it beside
     the date. Only one of the two is ever displayed. */
  function bar(progress) {
    return '<div class="mp-bar" role="img" aria-label="' + (Math.round(progress * 100) || 'Under 1') + ' percent of the way there">' +
      '<div class="mp-meter"><i style="width:' + Math.max(progress > 0 ? 1.5 : 0, progress * 100).toFixed(1) + '%"></i></div>' +
      '<span>' + pctLabel(progress) + ' of the way</span></div>';
  }
  function ring(progress) {
    var C = 2 * Math.PI * 60, pct = Math.round(progress * 100);
    var label = pctLabel(progress);
    return '<div class="mp-ring" role="img" aria-label="' + (pct || 'Under 1') + ' percent of the way there">' +
      '<svg viewBox="0 0 140 140"><circle class="track" cx="70" cy="70" r="60"/>' +
      '<circle class="fill" cx="70" cy="70" r="60" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' +
      (C * (1 - Math.max(progress, progress > 0 ? 0.012 : 0))).toFixed(1) + '"/></svg>' +
      '<div class="mp-ring-in"><b>' + label + '</b><span>of the way</span></div></div>';
  }

  function paintHero() {
    var s = M.streak(state.log, d.now), month = M.monthOnly(d.now), html, chips = '';
    var example = state.example
      ? '<div class="mp-example"><b>Example</b><span>These are sample numbers, not yours.</span>' +
        '<button type="button" data-act="mine">Use my own numbers</button></div>' : '';

    if (d.status === 'empty') {
      html = '<div><span class="mp-eyebrow">Four numbers, one date</span>' +
        '<h3 class="mp-when is-words" id="mp-when">When does work become optional?</h3>' +
        '<p>Type what you earn, what you spend and what you have invested. You get the month your investments could pay your bills. From then on a raise, a holiday or a new phone has a price in time, not only in rupees.</p>' +
        '<div class="mp-chips">' +
          '<button type="button" class="mp-chip is-gold" data-act="start">Start with my numbers' + ICON.arrow + '</button>' +
          '<button type="button" class="mp-chip" data-act="example">See an example first</button>' +
        '</div></div>' +
        '<svg class="mp-sketch" viewBox="0 0 190 120" aria-hidden="true">' +
          '<path d="M6 38h178" stroke="rgba(251,248,241,.45)" stroke-width="1.5" stroke-dasharray="5 5"/>' +
          '<path d="M6 110C70 106 120 84 150 38s24-30 34-34" stroke="#D9BC6A" stroke-width="2.5"/>' +
          '<circle cx="150" cy="38" r="6" fill="#D9BC6A" stroke="#15120C" stroke-width="2"/></svg>';
      $('mp-hero').innerHTML = html;
      return;
    }

    if (s.due) {
      chips += '<button type="button" class="mp-chip is-due" data-act="tab" data-tab="checkin" id="mp-chip-checkin">' +
        (state.log.length ? esc(month) + ' check-in due' : 'Log your first check-in') + ICON.arrow + '</button>';
    } else {
      chips += '<button type="button" class="mp-chip" data-act="tab" data-tab="checkin" id="mp-chip-checkin">' + ICON.check +
        'Checked in for ' + esc(month) + (s.count > 1 ? ' · ' + s.count + ' months running' : '') + '</button>';
    }
    if (d.income > 0 && d.put > 0) {
      chips += '<span class="mp-chip">Putting away ' + Math.round(100 * d.put / d.income) + '% of take-home</span>';
    }
    // Not on the example: that date is nobody's to share.
    if ((d.status === 'dated' || d.status === 'free') && !state.example) {
      chips += '<button type="button" class="mp-chip" data-act="share">' + ICON.share + 'Share</button>';
    }

    var since = '';
    if (state.prev && state.prev.when && d.when && state.prev.when !== d.when && !state.example) {
      var moved = M.monthsBetween(d.when, state.prev.when);
      since = '<p class="mp-since">' + M.span(moved) + (moved > 0 ? ' closer' : ' further off') +
        ' than when you last looked, on ' + esc(dayLabel(state.prev.on)) + '.' +
        (moved < 0 && s.due ? ' A check-in brings it up to date.' : '') + '</p>';
    }

    if (d.status === 'dated') {
      html = '<div><span class="mp-eyebrow">Work becomes optional in</span>' +
        '<h3 class="mp-when" id="mp-when">' + esc(M.monthName(d.when)) + '</h3>' +
        '<p>' + (d.ageThen ? 'You would be about <b>' + d.ageThen + '</b>, <b>' + M.span(d.sim.months) + '</b> from now. '
                           : 'That is <b>' + M.span(d.sim.months) + '</b> from now. ') +
        'In today’s money it takes <b>' + M.short(d.sim.target) + '</b>; you have <b>' + M.short(d.invested) + '</b>.</p>' +
        since + bar(d.progress) + '<div class="mp-chips">' + chips + '</div></div>' + ring(d.progress);
    } else if (d.status === 'free') {
      html = '<div><span class="mp-eyebrow">You are already there</span>' +
        '<h3 class="mp-when is-words" id="mp-when">Work is optional</h3>' +
        '<p>Your <b>' + M.short(d.invested) + '</b> invested is more than <b>' + d.a.multiple + '×</b> a year of your spending, which is <b>' +
        M.short(d.sim.target) + '</b> in today’s money. From here the question is not when, but what the years are for.</p>' +
        '<div class="mp-chips">' + chips + '</div></div>' + ring(1);
    } else {
      var head, body;
      if (d.why === 'overspend') {
        head = 'You spend ' + M.inr(-d.leftover) + ' more than you take home';
        body = 'A date appears the month something is left over. The <b>Budget</b> tab shows where it goes.';
      } else if (d.why === 'nothing') {
        head = 'Nothing is being put away yet';
        body = 'The plan needs something to compound. Even a small monthly amount puts a date on the page; the moves below show how much each one buys.';
      } else {
        head = 'More than sixty years away at this pace';
        body = 'The path below climbs, but not fast enough to reach <b>' + M.short(d.sim.target) + '</b>. The moves under it show what would put a date on this.';
      }
      html = '<div><span class="mp-eyebrow">No date on this path yet</span>' +
        '<h3 class="mp-when is-words" id="mp-when">' + esc(head) + '</h3><p>' + body + '</p>' +
        bar(d.progress) + '<div class="mp-chips">' + chips + '</div></div>' + ring(d.progress);
    }
    $('mp-hero').innerHTML = example + html;
  }

  /* Choosing a tool scrolls the hero away, and the hero is where the date
     is. So the date rides along at the end of the tab strip: add a goal, and
     the number that matters is still on screen to be seen moving. The hero
     says it properly for a screen reader; this is its echo, hidden from one. */
  function paintPin() {
    var pin = $('mp-pin');
    pin.textContent = d.status === 'dated' ? M.monthName(d.when, true)
      : d.status === 'free' ? 'Already there' : d.status === 'none' ? 'No date yet' : '';
  }

  /* Every bound box shows what is saved, except the one being typed in. */
  function syncInputs() {
    // The check-in opens on the figures the plan already holds, so a month
    // with no change is one press. Once somebody types there it is theirs.
    if (!drafts.ck.touched) {
      drafts.ck.invested = digits(state.invested);
      drafts.ck.liquid = digits(state.liquid);
      [['mp-ck-invested', drafts.ck.invested], ['mp-ck-liquid', drafts.ck.liquid]].forEach(function (pair) {
        var box = $(pair[0]);
        if (box && box !== doc.activeElement) box.value = shown(pair[1]);
      });
    }
    host.querySelectorAll('[data-f]').forEach(function (el) {
      if (el === doc.activeElement) return;
      var kind = el.getAttribute('data-kind'), path = el.getAttribute('data-f'), v = get(path);
      if (path === 'spend' && d.itemised) return;       // painted by paintNumbers
      if (kind === 'inr') el.value = shown(v);
      else if (kind === 'age') el.value = digits(v);
      else if (kind === 'dial') el.value = M.dial(v, M.DEFAULTS[path]);
    });
    host.querySelectorAll('[data-short]').forEach(function (em) {
      var key = em.getAttribute('data-short'), v;
      if (key.indexOf('d:') === 0) { var p = key.slice(2).split('.'); v = M.num(drafts[p[0]][p[1]]); }
      else v = key === 'spend' ? d.expenses : M.num(get(key));
      em.textContent = v >= 100000 ? M.short(v) : '';
    });
  }

  function paintNumbers() {
    var spend = $('mp-spend'), note = $('mp-spend-note');
    if (d.itemised) {
      spend.readOnly = true;
      spend.value = shown(d.expenses);
      note.innerHTML = 'The total of your itemised budget. <button type="button" class="mp-link" data-act="tab" data-tab="budget">Edit it</button>';
    } else {
      spend.readOnly = false;
      note.textContent = 'Everything: rent, EMIs, food, fun.';
    }
    var other = M.num(state.other);
    $('mp-salary-note').textContent = other > 0 ? 'Plus ' + M.inr(other) + ' other income, from your budget.' : '';

    var put = $('mp-put'), putNote = $('mp-put-note');
    put.placeholder = d.leftover > 0 ? 'All ' + M.inr(d.leftover) + ' left over' : 'What is left over';
    if (d.leftover < 0) putNote.textContent = 'You spend ' + M.inr(-d.leftover) + ' more than you take home.';
    else if (d.putSet && d.leftover > 0 && d.put > d.leftover) putNote.textContent = 'More than the ' + M.inr(d.leftover) + ' left after spending. Fine, if a bonus covers it.';
    else if (d.putSet && d.put < d.leftover) putNote.textContent = M.inr(d.leftover - d.put) + ' a month is left over and not put away.';
    else putNote.textContent = d.leftover > 0 ? 'Left blank, everything left over counts.' : '';

    var a = d.a, draw = 100 / a.multiple;
    var outs = {
      stepUp: pctText(a.stepUp) + '% a year', ret: pctText(a.ret) + '% a year', infl: pctText(a.infl) + '% a year',
      multiple: a.multiple + '× a year’s spending', after: a.after + '% of today’s'
    };
    host.querySelectorAll('[data-out]').forEach(function (b) { b.textContent = outs[b.getAttribute('data-out')] || ''; });
    $('mp-assume-sum').innerHTML = 'Assumes investments earn <b>' + pctText(a.ret) + '%</b> a year, prices rise <b>' +
      pctText(a.infl) + '%</b>, and freedom takes <b>' + a.multiple + '×</b> a year’s spending. ' +
      'Assumptions, not forecasts. <u>Change them</u>';

    var real = ((1 + a.ret / 100) / (1 + a.infl / 100) - 1) * 100, w = [];
    if (d.ready) {
      w.push('<b>FREEDOM FIGURE</b>  ' + M.inr(d.params.spend) + ' a month × 12 × ' + a.multiple + ' = ' + M.short(d.sim.target) +
        ', in today’s rupees. Drawing ' + pctText(draw) + '% of it a year covers the spending.');
      w.push('<b>REAL GROWTH</b>  ' + pctText(a.ret) + '% return against ' + pctText(a.infl) + '% inflation = ' + real.toFixed(2) + '% a year after prices.');
      w.push('<b>PUT AWAY</b>  ' + M.inr(d.put) + ' a month, raised ' + pctText(a.stepUp) + '% each year' +
        (d.split.cushion > 0 ? '; ' + M.inr(d.split.cushion) + ' of it fills the cushion for ' + M.span(d.cushion.months) : '') +
        (d.split.goals > 0 ? '; ' + M.inr(d.split.goals) + ' of it goes to dated goals' : '') + '.');
      w.push('<b>RESULT</b>  ' + M.short(d.invested) + ' today ' + (d.sim.months === null
        ? 'does not reach ' + M.short(d.sim.target) + ' inside sixty years.'
        : d.sim.months === 0 ? 'is already past ' + M.short(d.sim.target) + '.'
        : 'reaches ' + M.short(d.sim.target) + ' in ' + M.span(d.sim.months) + '.'));
    } else {
      w.push('The working appears here once there is a spending figure to work from.');
    }
    $('mp-working').innerHTML = w.join('<br>');
  }

  function combo() { return (d.ready && ticked.length) ? M.combine(d, ticked) : null; }

  function paintPath() {
    var box = $('mp-path-chart'), legend = $('mp-path-legend'), note = $('mp-path-note'), data = $('mp-path-data');
    if (!d.ready) { box.innerHTML = ''; box._w = 0; return; }
    var wi = combo(), base = d.sim, year0 = Number(d.now.split('-')[0]);
    var endM = Math.max(base.months || 0, (wi && wi.sim.months) || 0);
    var years = (base.months === null && !(wi && wi.sim.months !== null)) ? 40
      : Math.min(60, Math.max(10, Math.ceil(endM / 12) + 3));
    function pts(sim) {
      return sim.path.filter(function (p) { return p.m <= years * 12; })
        .map(function (p) { return { x: p.m / 12, y: Math.max(0, p.v) }; });
    }
    var plan = pts(base), alt = wi ? pts(wi.sim) : [];
    var top = Math.max(base.target, wi ? wi.sim.target : 0, plan[plan.length - 1].y, alt.length ? alt[alt.length - 1].y : 0);
    var step = years <= 12 ? 2 : years <= 30 ? 5 : 10, ticks = [], t;
    for (t = 0; t <= years; t += step) {
      ticks.push({ x: t, label: String(d.age ? d.age + t : year0 + t) });
    }
    var differs = wi && Math.abs(wi.sim.target - base.target) > 1;
    var lines = [{ y: base.target, label: 'Freedom line · ' + M.short(base.target) }];
    if (differs) lines.push({ y: wi.sim.target, cls: 's2', label: 'With your moves · ' + M.short(wi.sim.target) });
    var marks = [];
    if (base.months !== null && base.months > 0) {
      marks.push({ x: base.months / 12, y: base.target, cls: 's1', brief: M.monthName(d.when, true),
                   label: M.monthName(d.when, true) + (d.ageThen ? ' · age ' + d.ageThen : '') });
    }
    if (wi && wi.sim.months !== null && wi.sim.months > 0) {
      marks.push({ x: wi.sim.months / 12, y: wi.sim.target, cls: 's2', label: M.monthName(wi.when, true), below: !differs });
    }
    var series = [{ cls: 's1', name: 'Your plan', pts: plan, wash: true }];
    if (wi) series.push({ cls: 's2', name: 'With your moves', pts: alt });

    var samples = plan.map(function (p, k) {
      var rows = [{ cls: 's1', name: 'Your plan', value: p.y }];
      if (wi && alt[k]) rows.push({ cls: 's2', name: 'With your moves', value: alt[k].y });
      rows.push({ cls: 'line', key: 'dash', name: 'Freedom line', value: base.target });
      return { x: p.x, head: (year0 + p.x) + (d.age ? ' · age ' + (d.age + p.x) : ''), rows: rows };
    });
    drawChart(box, {
      x0: 0, x1: years, top: top * 1.04, xTicks: ticks, xTitle: d.age ? 'Age' : '', series: series, lines: lines, marks: marks,
      samples: samples, start: Math.min(samples.length - 1, Math.round((base.months || 0) / 12)),
      label: 'Your investments in today’s rupees, year by year, against the ' + M.short(base.target) +
        ' it takes for work to be optional' + (d.when && d.status === 'dated' ? '. They cross in ' + M.monthName(d.when) + '.' : '.')
    });

    legend.innerHTML = '<li><i class="mp-key"></i>Your plan</li>' +
      (wi ? '<li><i class="mp-key s2"></i>With the moves you ticked</li>' : '') +
      '<li><i class="mp-key dash"></i>Freedom line: ' + d.a.multiple + '× a year’s spending</li>';
    note.textContent = 'Everything is in today’s rupees, so a rupee on the right buys what a rupee buys now. ' +
      'The curve assumes ' + pctText(d.a.ret) + '% a year on investments and ' + pctText(d.a.infl) +
      '% inflation, every year, which no real year delivers. It is a planning line, not a promise.';
    data.hidden = false;
    $('mp-path-table').innerHTML = '<table><thead><tr><th>Year</th>' + (d.age ? '<th>Age</th>' : '') +
      '<th>Your plan</th>' + (wi ? '<th>With your moves</th>' : '') + '<th>Freedom line</th></tr></thead><tbody>' +
      plan.map(function (p, k) {
        return '<tr><td>' + (year0 + p.x) + '</td>' + (d.age ? '<td>' + (d.age + p.x) + '</td>' : '') +
          '<td>' + M.short(p.y) + '</td>' + (wi ? '<td>' + (alt[k] ? M.short(alt[k].y) : '') + '</td>' : '') +
          '<td>' + M.short(base.target) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function moveText(mv) {
    switch (mv.id) {
      case 'more':   return ['Put away ' + M.inr(mv.amount) + ' more a month', ''];
      case 'stepup': return ['Raise what you put away by ' + mv.to + '% every year' + (mv.from ? ', not ' + pctText(mv.from) + '%' : ''),
                             'Most of a pay rise, before it becomes lifestyle.'];
      case 'trim':   return ['Trim ' + mv.name + ' by a quarter: ' + M.inr(mv.amount) + ' a month',
                             'It counts twice: more is invested, and life costs less to fund.'];
      case 'lean':   return ['Live on 10% less once work is optional', 'The finish line moves closer; nothing changes today.'];
      case 'keep':   return ['Keep 1% a year more of your returns', 'What lower costs on the same investments are worth.'];
      case 'creep':  return ['Let spending creep up 10%', 'Less is invested, and the finish line moves away.'];
      case 'wait':   return ['Put nothing away for the next year', ''];
      case 'costs':  return ['Lose 1% a year of your returns to costs', ''];
    }
    return ['', ''];
  }

  function paintMoves() {
    var box = $('mp-moves');
    if (!d.ready) { box.innerHTML = ''; return; }
    var list = M.moves(d);
    ticked = ticked.filter(function (id) { return list.some(function (x) { return x.id === id && x.kind === 'sooner'; }); });
    var max = 1;
    list.forEach(function (x) { if (x.delta !== null) max = Math.max(max, Math.abs(x.delta)); });

    function effect(mv) {
      if (mv.unlocks) return 'puts a date on it<small>' + esc(M.monthName(M.addMonths(d.now, Math.ceil(mv.sim.months)), true)) + '</small>';
      if (mv.delta === null) return d.sim.months === null ? 'still no date' : 'no date at all';
      if (Math.abs(mv.delta) * 30.44 < 1) return 'no change';
      return M.span(mv.delta) + '<small>' + (mv.delta > 0 ? 'sooner' : 'later') + '</small>';
    }
    function width(mv) { return mv.delta === null ? (mv.unlocks ? 100 : 0) : Math.max(2, Math.round(Math.abs(mv.delta) / max * 100)); }

    var sooner = list.filter(function (x) { return x.kind === 'sooner'; });
    var later = list.filter(function (x) { return x.kind === 'later'; });
    var html = '<ul class="mp-moves">' + sooner.map(function (mv) {
      var text = moveText(mv);
      return '<li><label class="mp-move"><input type="checkbox" data-move="' + mv.id + '"' +
        (ticked.indexOf(mv.id) > -1 ? ' checked' : '') + '>' +
        '<span class="what">' + esc(text[0]) + (text[1] ? '<small>' + esc(text[1]) + '</small>' : '') + '</span>' +
        '<span class="eff">' + effect(mv) + '</span>' +
        '<span class="bar"><i style="width:' + width(mv) + '%"></i></span></label></li>';
    }).join('') + '</ul>';

    var wi = combo();
    if (wi) {
      html += '<div class="mp-combo" id="mp-combo" role="status">';
      if (wi.when && d.sim.months !== null) {
        html += 'With ' + (ticked.length === 1 ? 'that move' : 'those ' + ticked.length + ' moves') + ', work becomes optional in<br><b>' +
          esc(M.monthName(wi.when)) + '</b><br>' + M.span(wi.delta) + ' sooner than ' + esc(M.monthName(d.when, true)) +
          (d.age ? ', at about ' + Math.round(d.age + wi.sim.months / 12) : '') + '.';
      } else if (wi.when) {
        html += 'With ' + (ticked.length === 1 ? 'that move' : 'those ' + ticked.length + ' moves') +
          ', there is a date:<br><b>' + esc(M.monthName(wi.when)) + '</b>';
      } else {
        html += 'Even with ' + (ticked.length === 1 ? 'that move' : 'those moves') + ', the path does not reach the line inside sixty years.';
      }
      html += '</div>';
    }

    html += '<h4 class="mp-h4">What pushes it away</h4><ul class="mp-moves">' + later.map(function (mv) {
      var text = moveText(mv);
      return '<li><div class="mp-move is-still">' + ICON.up.replace('class="arrow"', 'class="arrow" style="transform:rotate(180deg)"') +
        '<span class="what">' + esc(text[0]) + (text[1] ? '<small>' + esc(text[1]) + '</small>' : '') + '</span>' +
        '<span class="eff">' + effect(mv) + '</span>' +
        '<span class="bar"><i style="width:' + width(mv) + '%"></i></span></div></li>';
    }).join('') + '</ul>';
    box.innerHTML = html;
  }

  function paintNext() {
    var box = $('mp-next');
    if (!d.ready) { box.innerHTML = ''; return; }
    var long = d.split.longRun;
    box.innerHTML =
      '<button type="button" data-goto="portfolio/allocate"><span class="k">Next</span>' +
        '<b>' + (long > 0 ? 'Decide where the ' + M.inr(long) + ' a month for the long run goes' : 'Decide how your money is split by risk') + '</b>' +
        '<span class="s">The Allocation plan sizes it to your risk profile.</span></button>' +
      '<button type="button" data-goto="portfolio/portfolio"><span class="k">Already invested</span>' +
        '<b>Check what you already hold</b><span class="s">A hold, trim, add or exit call on every stock.</span></button>' +
      '<a href="advisors.html"><span class="k">A second opinion</span>' +
        '<b>Have a registered adviser look at this plan</b><span class="s">SEBI-registered advisers, free to chat.</span></a>';
  }

  /* ── Price tag ───────────────────────────────────────────────────────────── */

  function workText(days) {
    if (days === null) return null;
    if (days < 1) {
      var hours = Math.round(days * 8);
      return hours < 1 ? 'under an hour of work' : hours + (hours === 1 ? ' hour' : ' hours') + ' of work';
    }
    return (days < 10 ? Number(days.toFixed(1)) : Math.round(days)) + ' working day' + (days === 1 ? '' : 's');
  }
  function delayText(t) {
    if (t.lost) return 'the date itself';
    if (t.delay === null) return null;
    return t.delay * 30.44 < 1 ? 'under a day' : M.span(t.delay);
  }

  function paintTag() {
    var out = $('mp-tag-out'), tg = drafts.tag, cost = M.num(tg.cost);
    host.querySelectorAll('[data-act="tag-mode"]').forEach(function (b) {
      b.setAttribute('aria-pressed', String((b.getAttribute('data-mode') === 'monthly') === !!tg.monthly));
    });
    if (!cost) {
      out.innerHTML = '';
    } else if (!(d.income > 0) || !d.ready) {
      out.innerHTML = '<p class="mp-empty" style="margin-top:18px">A price in time needs your time: add your take-home and spending first. ' +
        '<button type="button" class="mp-link" data-act="start">Add my numbers</button></p>';
    } else {
      var t = M.priceTag(d, cost, tg.monthly), name = (tg.name || '').trim();
      var subject = name ? esc(name.charAt(0).toUpperCase() + name.slice(1)) : (tg.monthly ? 'That habit' : 'That');
      var work = workText(t.workDays), delay = delayText(t), every = tg.monthly ? ' every month' : '';
      var say = '<em>' + subject + '</em> costs <em>' + work + '</em>' + every +
        (t.lost ? ', and on this plan it takes the date off the page.'
          : delay ? (tg.monthly ? ', and <em>' : ' and <em>') + delay + '</em> of freedom.' : '.');
      var horizon = t.dated ? 'by ' + M.monthName(d.when, true) : 'over the next 20 years';
      var newWhen = (t.delay !== null && d.sim.months !== null) ? M.addMonths(d.now, Math.ceil(d.sim.months + t.delay)) : null;

      out.innerHTML = '<p class="mp-say" id="mp-tag-say">' + say + '</p>' +
        '<div class="mp-stats">' +
          '<div class="mp-stat"><span class="k">Of your pay</span><span class="v">' + work.replace(' of work', '') + '</span>' +
            '<span class="s">' + (tg.monthly ? 'Of the 22 you work each month.' : (t.workDays >= 22
              ? Number((t.workDays / 22).toFixed(1)) + ' months of take-home.' : 'At ' + M.inr(d.income / M.WORK_DAYS) + ' a working day.')) + '</span></div>' +
          '<div class="mp-stat"><span class="k">Your date moves</span><span class="v" id="mp-tag-delay">' +
            (t.lost ? 'Off the page' : delay ? delay + ' later' : 'No date yet') + '</span>' +
            '<span class="s">' + (t.lost ? 'The path no longer reaches the line inside sixty years.'
              : !delay ? 'There is no date to move until the plan has one.'
              : newWhen && newWhen !== d.when ? M.monthName(d.when, true) + ' becomes ' + M.monthName(newWhen, true) + '.'
              : 'Still ' + M.monthName(d.when, true) + ', a little later in it.') + '</span></div>' +
          '<div class="mp-stat"><span class="k">Invested instead</span><span class="v">' + M.short(t.grown) + '</span>' +
            '<span class="s">What it would be ' + horizon + ', in today’s rupees.</span></div>' +
        '</div>' +
        (tg.monthly ? '<p class="mp-quiet">A habit is priced twice. ' + M.inr(cost) + ' a month is not invested, and it is also ' +
          M.inr(cost) + ' a month your investments must one day pay for: ' + M.short(t.extraCorpus) + ' more on the freedom line.</p>' : '') +
        '<div class="mp-acts"><button type="button" class="mp-btn is-ghost" data-act="tag-keep" id="mp-tag-keep">Keep it on my list</button>' +
          '<span class="mp-msg">Worth it or not is yours to say. Now you know the price.</span></div>';
    }

    var card = $('mp-kept-card');
    card.hidden = !state.tags.length;
    if (!state.tags.length) return;
    $('mp-kept-count').textContent = state.tags.length + ' priced';
    $('mp-kept').innerHTML = state.tags.map(function (k) {
      var t = d.ready ? M.priceTag(d, k.cost, k.monthly) : null, dl = t ? delayText(t) : null;
      return '<li><span class="n">' + esc(k.name) + '<small>' + M.inr(k.cost) + (k.monthly ? ' a month' : ' once') + '</small></span>' +
        '<span class="e">' + (t && t.lost ? 'takes the date away' : dl ? dl + ' later' : '—') + '</span>' +
        '<button type="button" class="mp-x" data-act="tag-drop" data-id="' + esc(k.id) + '" aria-label="Remove ' + esc(k.name) + '">' + ICON.x + '</button></li>';
    }).join('');
    var all = d.ready ? M.priceList(d, state.tags) : null;
    $('mp-kept-sum').textContent = !all ? ''
      : all.lost ? 'All of it together takes the date off the page.'
      : all.delay !== null && state.tags.length > 1 ? 'All of it together: ' + M.span(all.delay) + ' later. The list is a way to see prices side by side, not a bill.'
      : '';
  }

  /* ── Goals ───────────────────────────────────────────────────────────────── */

  function paintGoals() {
    var sum = $('mp-goals-sum'), list = $('mp-goals-list'), badge = host.querySelector('[data-badge="goals"]');
    badge.className = d.goals.length ? 'n' : 'mp-badge';
    badge.textContent = d.goals.length ? String(d.goals.length) : '';

    if (!d.goals.length) {
      sum.innerHTML = '';
      list.innerHTML = '';
    } else {
      var without = M.derive(Object.assign({}, state, { goals: [] }), today());
      var delay = (d.sim.months !== null && without.sim.months !== null) ? d.sim.months - without.sim.months : null;
      var room = d.put - d.split.cushion;
      sum.innerHTML = '<div class="mp-card"><div class="mp-card-h"><h3>Do they fit?</h3><span>Each month</span></div>' +
        '<div class="mp-stats" style="margin-top:8px">' +
          '<div class="mp-stat"><span class="k">Your goals need</span><span class="v" id="mp-goals-need">' + M.inr(d.goalsMonthly) + '</span>' +
            '<span class="s">' + d.goals.length + (d.goals.length === 1 ? ' goal' : ' goals') + ', each paid by its own date.</span></div>' +
          '<div class="mp-stat"><span class="k">You put away</span><span class="v">' + M.inr(d.put) + '</span>' +
            '<span class="s">' + (d.split.cushion > 0 ? M.inr(d.split.cushion) + ' of it is filling your cushion first.' : 'Your cushion is full, so all of it is free.') + '</span></div>' +
          '<div class="mp-stat"><span class="k">' + (d.split.short > 0 ? 'Short by' : 'Left for the long run') + '</span>' +
            '<span class="v">' + M.inr(d.split.short > 0 ? d.split.short : d.split.longRun) + '</span>' +
            '<span class="s">' + (d.split.short > 0 ? 'A month. Something has to give: a later date, a smaller goal, or more put away.' : 'A month, after cushion and goals.') + '</span></div>' +
        '</div>' +
        (d.split.short > 0 ? '<p class="mp-flag is-stop" id="mp-goals-short"><b>These goals ask for ' + M.inr(d.split.short) +
          ' a month more than you have.</b> With ' + M.inr(Math.max(0, room)) + ' available, nothing reaches the long run until a goal is paid for or moved.</p>' : '') +
        (delay !== null && delay * 30.44 >= 1 ? '<p class="mp-quiet" id="mp-goals-delay">Together they move your date ' + M.span(delay) +
          ' later. That is what they cost, not a reason to drop them: a goal met is the point of the money.</p>' : '') +
        '</div>';

      list.innerHTML = d.goals.map(function (g) {
        var b = BUCKET[g.bucket], pct = Math.round(g.progress * 100);
        return '<article class="mp-goal" data-goal="' + esc(g.id) + '">' +
          '<div class="mp-goal-h"><div><h4>' + esc(g.name) + '</h4><span>by ' + esc(M.monthName(g.due, true)) + ' · ' +
            (g.months <= 1 ? 'due now' : M.span(g.months) + ' away') + '</span></div>' +
            '<button type="button" class="mp-x" data-act="goal-drop" data-id="' + esc(g.id) + '" aria-label="Remove ' + esc(g.name) + '">' + ICON.x + '</button></div>' +
          '<div class="amt">' + (g.monthly > 0 ? M.inr(g.monthly) + ' <small>a month</small>' : 'Paid for') + '</div>' +
          '<div class="mp-meter s2" role="img" aria-label="' + pct + ' percent set aside"><i style="width:' + Math.max(pct, g.saved > 0 ? 2 : 0) + '%"></i></div>' +
          '<p>' + M.short(g.future) + ' by then: ' + M.short(g.cost) + ' today, with prices rising ' + pctText(d.a.infl) + '% a year. ' +
            (g.saved > 0 ? M.short(g.saved) + ' set aside covers ' + pct + '% of it.' : 'Nothing set aside yet.') + '</p>' +
          '<span class="mp-gtag" title="' + esc(b[1]) + '">' + b[0] + ' · assumed ' + pctText(g.rate) + '%</span>' +
          '<div class="acts"><button type="button" class="mp-link" data-act="goal-edit" data-id="' + esc(g.id) + '">Edit</button></div>' +
        '</article>';
      }).join('');
    }

    var gd = drafts.goal;
    host.querySelectorAll('[data-act="goal-kind"]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-kind') === gd.kind && (gd.name !== '' || gd.cost !== '')));
    });
    $('mp-goal-title').textContent = gd.id ? 'Edit this goal' : (d.goals.length ? 'Add another goal' : 'Add a goal');
    $('mp-goal-save').textContent = gd.id ? 'Save changes' : 'Add this goal';
    $('mp-goal-cancel').hidden = !gd.id;
  }

  function fillGoalForm() {
    var gd = drafts.goal;
    $('mp-goal-name').value = gd.name;
    $('mp-goal-cost').value = shown(gd.cost);
    $('mp-goal-years').value = gd.years;
    $('mp-goal-saved').value = shown(gd.saved);
  }

  /* ── Check-in ────────────────────────────────────────────────────────────── */

  function sortedLog() {
    return state.log.slice().sort(function (a, b) { return a.ym < b.ym ? -1 : a.ym > b.ym ? 1 : 0; });
  }

  function paintCheckin() {
    var s = M.streak(state.log, d.now), month = M.monthOnly(d.now), log = sortedLog();
    var badge = host.querySelector('[data-badge="checkin"]');
    badge.className = (s.due && d.ready) ? 'dot' : 'mp-badge';
    badge.setAttribute('aria-label', (s.due && d.ready) ? 'due' : '');
    $('mp-ck-status').textContent = s.due
      ? month + ': due' + (s.count ? ' · ' + s.count + (s.count === 1 ? ' month' : ' months') + ' running' : '')
      : month + ': done · ' + s.count + (s.count === 1 ? ' month' : ' months') + ' running';
    $('mp-ck-go').textContent = s.due ? 'Log ' + month : 'Update ' + month;

    var out = $('mp-ck-out'), html = '';
    if (log.length === 1) {
      html = '<p class="mp-flag"><b>First dot on the chart.</b> Come back in ' + esc(M.monthOnly(M.addMonths(log[0].ym, 1))) +
        ' for the second: that is when this starts telling you whether you are ahead of your plan.</p>';
    } else if (log.length > 1) {
      var last = log[log.length - 1], prev = log[log.length - 2];
      var gap = M.monthsBetween(prev.ym, last.ym);
      var expected = M.project(prev.invested, gap, d.params), diff = last.invested - expected;
      html = '<div class="mp-stats">' +
        '<div class="mp-stat"><span class="k">Since ' + esc(M.monthName(prev.ym, true)) + '</span><span class="v">' +
          (last.invested >= prev.invested ? '+' : '') + M.short(last.invested - prev.invested) + '</span>' +
          '<span class="s">' + M.short(prev.invested) + ' to ' + M.short(last.invested) + '.</span></div>' +
        '<div class="mp-stat"><span class="k">Against your plan</span><span class="v" id="mp-ck-diff">' + M.short(Math.abs(diff)) +
          (diff >= 0 ? ' ahead' : ' behind') + '</span><span class="s">The plan put you at ' + M.short(expected) + ' by now.</span></div>' +
        '<div class="mp-stat"><span class="k">Streak</span><span class="v">' + s.count + (s.count === 1 ? ' month' : ' months') + '</span>' +
          '<span class="s">' + (s.due ? 'Log ' + esc(month) + ' to keep it.' : 'Next one: ' + esc(M.monthOnly(M.addMonths(d.now, 1))) + '.') + '</span></div>' +
        '</div>';
    }
    out.innerHTML = html;

    var card = $('mp-ck-card');
    card.hidden = !log.length;
    if (!log.length) return;
    $('mp-ck-log').innerHTML = '<thead><tr><th>Month</th><th>Invested</th><th>Cushion</th><th>Change</th><th></th></tr></thead><tbody>' +
      log.slice().reverse().map(function (e, k, arr) {
        var before = arr[k + 1];
        return '<tr><td>' + esc(M.monthName(e.ym, true)) + '</td><td>' + M.inr(e.invested) + '</td><td>' +
          (e.liquid ? M.inr(e.liquid) : '—') + '</td><td>' +
          (before ? (e.invested >= before.invested ? '+' : '') + M.inr(e.invested - before.invested) : '—') + '</td>' +
          '<td><button type="button" class="mp-x" data-act="ck-drop" data-ym="' + esc(e.ym) + '" aria-label="Remove ' +
          esc(M.monthName(e.ym)) + '">' + ICON.x + '</button></td></tr>';
      }).join('') + '</tbody>';
    paintCheckinChart();
  }

  function paintCheckinChart() {
    var box = $('mp-ck-chart'), log = sortedLog();
    if (log.length < 2) {
      box.innerHTML = '<p class="mp-empty">One check-in is a dot. The second makes a line, and the line is what tells you something.</p>';
      box._w = 0;
      return;
    }
    var first = log[0], span = M.monthsBetween(first.ym, log[log.length - 1].ym), end = span + 3;
    var planPts = [], k;
    for (k = 0; k <= end; k++) planPts.push({ x: k, y: M.project(first.invested, k, d.params) });
    var actual = log.map(function (e) { return { x: M.monthsBetween(first.ym, e.ym), y: e.invested }; });
    var all = planPts.concat(actual).map(function (p) { return p.y; });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = Math.max((hi - lo) * 0.15, hi * 0.01);
    var floorStep = niceStep(hi + pad - Math.max(0, lo - pad));
    var y0 = Math.max(0, Math.floor((lo - pad) / floorStep) * floorStep);
    var step = Math.max(1, Math.ceil(end / 6)), ticks = [];
    for (k = 0; k <= end; k += step) ticks.push({ x: k, label: M.monthName(M.addMonths(first.ym, k), true) });
    var byX = {};
    actual.forEach(function (p) { byX[p.x] = p.y; });
    drawChart(box, {
      x0: 0, x1: end, y0: y0, top: hi + pad, xTicks: ticks,
      series: [{ cls: 'quiet', name: 'Your plan', pts: planPts }, { cls: 's1', name: 'What you logged', pts: actual, dots: true }],
      samples: planPts.map(function (p) {
        return { x: p.x, head: M.monthName(M.addMonths(first.ym, p.x), true),
                 rows: [{ cls: 's1', name: 'You logged', value: byX[p.x] != null ? byX[p.x] : null },
                        { cls: 'quiet', name: 'Your plan', value: p.y }] };
      }),
      start: span,
      label: 'What you logged each month against where your plan put you, from ' + M.monthName(first.ym) + '.'
    });
  }

  /* ── Budget ──────────────────────────────────────────────────────────────── */

  function ledgerRow(name, pass, value, working, learn) {
    var mark = pass === true ? '✓' : pass === false ? '✕' : pass === 'na' ? '—' : '◐';
    var cls = pass === true ? 'm-full' : pass === false ? 'm-zero' : pass === 'na' ? 'm-na' : 'm-part';
    return '<details class="row"><summary><span class="mark ' + cls + '">' + mark + '</span><span>' + name + '</span>' +
      '<span class="pts">' + value + '</span></summary><div class="body">' +
      '<div class="audit"><span class="k">WORKING  </span>' + working + '</div>' +
      '<div class="learn">' + learn + '</div></div></details>';
  }

  function paintBudget() {
    $('mp-needs-sum').textContent = d.needs ? M.inr(d.needs) : '';
    $('mp-wants-sum').textContent = d.wants ? M.inr(d.wants) : '';
    $('mp-bud-total').innerHTML = d.itemised
      ? 'Itemised spending is <b>' + M.inr(d.expenses) + '</b> a month. It replaces the single spending figure on Your date. ' +
        '<button type="button" class="mp-link" data-act="bud-clear">Clear the itemised budget</button>'
      : (M.num(state.spend) ? 'Leave these blank and the planner keeps using your single figure of ' + M.inr(M.num(state.spend)) + ' a month.' : '');

    var h = d.health, health = $('mp-health'), pay = $('mp-payday');
    if (!h) {
      health.innerHTML = '<div class="mp-card-h"><h3>Household health</h3><span>Four checks</span></div>' +
        '<p class="mp-empty">Add a take-home figure and this fills in: what you keep each month, and four checks with their working shown.</p>';
      pay.innerHTML = '<div class="mp-card-h"><h3>On salary day</h3><span>Where it goes</span></div>' +
        '<p class="mp-empty">What you put away, split three ways: the cushion first, dated goals second, the long run with the rest.</p>';
      return;
    }
    var judged = ['rate', 'cover', 'emi', 'split'].filter(function (k) { return h.pass[k] !== 'na'; }).length;
    var rows =
      ledgerRow('Savings rate', h.pass.rate, h.rate.toFixed(1) + '%',
        '(' + M.inr(d.income) + ' income − ' + M.inr(d.expenses) + ' spending) / income = ' + h.rate.toFixed(1) + '% · benchmark ≥ 20%',
        'The single number that decides how fast the date arrives. 20% is the classic benchmark; below 10%, any shock forces borrowing.') +
      ledgerRow('Emergency cushion', h.pass.cover, h.cover === null ? 'add spending' : h.cover.toFixed(1) + ' months covered',
        M.inr(d.liquid) + ' liquid savings / ' + M.inr(d.expenses) + ' monthly spending · target 6 months',
        'Six months of spending within reach is what lets a job loss or a hospital bill pass without breaking an investment or taking a personal loan at 14%.') +
      ledgerRow('Rent and EMI load', h.pass.emi, h.emiRatio === null ? 'itemise to judge' : h.emiRatio.toFixed(1) + '% of income',
        h.emiRatio === null ? 'Needs the rent and EMI lines of the itemised budget. Not judged, so not counted for or against you.'
          : M.inr(d.emis) + ' rent and EMIs / ' + M.inr(d.income) + ' income = ' + h.emiRatio.toFixed(1) + '% · lender red line 40%',
        'Lenders cap fixed payments near 40% of income for a reason: above it, one bad month cascades. Over the line, nothing new is borrowed until something is closed.') +
      ledgerRow('Needs and wants', h.pass.split,
        h.wantsPct === null ? 'itemise to judge' : h.needsPct.toFixed(0) + '% needs · ' + h.wantsPct.toFixed(0) + '% wants · ' + Math.max(0, h.rate).toFixed(0) + '% kept',
        h.wantsPct === null ? 'Needs the itemised budget. Not judged, so not counted for or against you.'
          : 'Benchmark 50 / 30 / 20 (needs / wants / kept). The category mapping is approximate; reclassify in your head where your life differs.',
        'The 50/30/20 rule is a diagnostic, not a law. What it catches well: wants quietly swelling past 30% while savings absorb the squeeze.');

    var splitBar = '';
    if (d.itemised && d.income > 0) {
      var kept = Math.max(0, d.leftover);
      splitBar = '<h4 class="mp-h4">Where a month goes</h4>' +
        '<div class="mp-split" role="img" aria-label="Needs ' + Math.round(h.needsPct) + ' percent, wants ' + Math.round(h.wantsPct) +
          ' percent, kept ' + Math.round(Math.max(0, h.rate)) + ' percent">' +
          (d.needs ? '<i class="s3" style="flex-grow:' + d.needs + '"></i>' : '') +
          (d.wants ? '<i class="s2" style="flex-grow:' + d.wants + '"></i>' : '') +
          (kept ? '<i class="s1" style="flex-grow:' + kept + '"></i>' : '') + '</div>' +
        '<ul class="mp-rows">' +
          '<li><i class="mp-sw s3"></i><span class="n">Needs</span><span class="a">' + M.inr(d.needs) + '<small>' + h.needsPct.toFixed(0) + '% · benchmark 50%</small></span></li>' +
          '<li><i class="mp-sw s2"></i><span class="n">Wants</span><span class="a">' + M.inr(d.wants) + '<small>' + h.wantsPct.toFixed(0) + '% · benchmark 30%</small></span></li>' +
          '<li><i class="mp-sw s1"></i><span class="n">Kept</span><span class="a">' + M.inr(kept) + '<small>' + Math.max(0, h.rate).toFixed(0) + '% · benchmark 20%</small></span></li>' +
        '</ul>';
    }

    health.innerHTML = '<div class="mp-card-h"><h3>Household health</h3><span>Four checks</span></div>' +
      '<div class="mp-grade"><div><span class="k">You keep every month</span>' +
        '<span class="big ' + (d.leftover >= 0 ? 'up' : 'down') + '" id="mp-keep">' + M.inr(d.leftover) + '</span>' +
        '<span class="s">' + h.rate.toFixed(1) + '% of ' + M.inr(d.income) + ' · spending ' + M.inr(d.expenses) + '</span></div>' +
        '<div class="letter"><span class="k">Grade</span><span class="big' + (h.grade ? '' : ' is-none') + '" id="mp-grade">' + (h.grade || '—') + '</span>' +
        '<span class="s">' + (h.grade ? 'on all four checks' : judged + ' of 4 judged') + '</span></div></div>' +
      (h.grade ? '' : '<p class="mp-flag">No grade yet. Two of the four checks need your spending itemised, and a check that cannot be judged is not a pass.</p>') +
      '<div id="mp-ledger">' + rows + '</div>' + splitBar;

    var sp = d.split, goalNames = d.goals.filter(function (g) { return g.monthly > 0; }).map(function (g) { return esc(g.name); });
    if (!(sp.put > 0)) {
      pay.innerHTML = '<div class="mp-card-h"><h3>On salary day</h3><span>Where it goes</span></div>' +
        '<p class="mp-empty">Nothing is left to split yet. The split appears the month something is put away.</p>';
      return;
    }
    pay.innerHTML = '<div class="mp-card-h"><h3>On salary day</h3><span>' + M.inr(sp.put) + ' a month</span></div>' +
      '<p class="mp-sub">One standing instruction a month, in this order. The order is the plan: structure and reasoning, never specific products.</p>' +
      '<div class="mp-split" role="img" aria-label="Cushion ' + M.inr(sp.cushion) + ', dated goals ' + M.inr(sp.goals) + ', the long run ' + M.inr(sp.longRun) + '">' +
        (sp.cushion ? '<i class="s3" style="flex-grow:' + sp.cushion + '"></i>' : '') +
        (sp.goals ? '<i class="s2" style="flex-grow:' + sp.goals + '"></i>' : '') +
        (sp.longRun ? '<i class="s1" style="flex-grow:' + sp.longRun + '"></i>' : '') + '</div>' +
      '<ul class="mp-rows" id="mp-pay-rows">' +
        '<li><i class="mp-sw s3"></i><span class="n">1 · The cushion<small>' + (sp.cushion > 0
          ? 'For ' + M.span(d.cushion.months) + ', until it holds six months of spending (' + M.short(d.cushion.target) + '). Savings account, sweep-in FD or liquid fund: boring on purpose.'
          : d.cushion.gap > 0 ? 'Short by ' + M.short(d.cushion.gap) + ', with nothing spare to fill it.' : 'Full. Six months of spending is already within reach.') +
          '</small></span><span class="a" data-part="cushion">' + M.inr(sp.cushion) + '</span></li>' +
        '<li><i class="mp-sw s2"></i><span class="n">2 · Dated goals<small>' + (goalNames.length ? goalNames.join(', ') + '. Money with a date does not belong where a 30% fall can meet it.'
          : 'None yet. <button type="button" class="mp-link" data-act="tab" data-tab="goals">Add one</button>') +
          '</small></span><span class="a" data-part="goals">' + M.inr(sp.goals) + '</span></li>' +
        '<li><i class="mp-sw s1"></i><span class="n">3 · The long run<small>Everything else, raised ' + pctText(d.a.stepUp) +
          '% a year. Ten-year-plus money is what moves your date. Monthly and automatic beats lump-sum and heroic.</small></span>' +
          '<span class="a" data-part="longRun">' + M.inr(sp.longRun) + '</span></li>' +
      '</ul>' +
      (sp.short > 0 ? '<p class="mp-flag is-stop">Your goals ask for ' + M.inr(sp.short) + ' a month more than this.</p>' : '') +
      '<div class="mp-acts"><button type="button" class="mp-btn is-ghost" data-act="pay-copy">Copy this plan</button>' +
        '<button type="button" class="mp-link" data-goto="portfolio/allocate">Split the long run by risk</button>' +
        '<span class="mp-msg" id="mp-pay-msg" role="status"></span></div>';
  }

  /* ── Tax ─────────────────────────────────────────────────────────────────── */

  function paintTax() {
    var out = $('mp-tax-out'), t = M.tax(state.tax);
    if (!t) { out.innerHTML = ''; return; }
    out.innerHTML = '<div class="ptaxcols">' +
      '<div class="ptaxcol' + (t.winner === 'old' ? ' win' : '') + '" id="mp-tax-old"><span class="k">Old regime</span>' +
        '<span class="ptv">' + M.inr(t.old.tax) + '</span><span class="ptd">Taxable ' + M.inr(t.old.taxable) + ' after ' +
        M.inr(t.deductions) + ' deductions · incl. 4% cess</span></div>' +
      '<div class="ptaxcol' + (t.winner === 'new' ? ' win' : '') + '" id="mp-tax-new"><span class="k">New regime</span>' +
        '<span class="ptv">' + M.inr(t.neu.tax) + '</span><span class="ptd">Taxable ' + M.inr(t.neu.taxable) +
        ' after ₹75,000 standard deduction · incl. 4% cess</span></div></div>' +
      '<p class="ptaxverdict" id="mp-tax-verdict">' + (t.winner === 'either' ? 'Both regimes produce the same tax at these numbers.'
        : 'The ' + t.winner + ' regime saves you ' + M.inr(t.saving) + ' this year at these numbers.') + '</p>' +
      (t.winner === 'new' ? '<p class="ptaxlink">Rough flip point: if your total old-regime deductions crossed about ' + M.inr(t.flip) +
          ', the old regime would start winning — exact point depends on which slab the extra deduction lands in.</p>'
        : t.winner === 'old' ? '<p class="ptaxlink">Your ' + M.inr(t.deductions) + ' of deductions is what’s carrying the old regime here — if any of those lapse next year, re-run this.</p>'
        : '');
  }

  /* ── One pass over everything derived ────────────────────────────────────── */

  function publish() {
    var h = d.health;
    window.AltahaPlannerState = h ? {
      rate: h.rate, grade: h.grade, efMonths: h.cover, emiRatio: h.emiRatio,
      income: d.income, expenses: d.expenses, savings: d.leftover, liquid: d.liquid,
      efTarget: d.cushion.target, efGap: d.cushion.gap, put: d.put, when: d.when
    } : null;
    try { window.dispatchEvent(new CustomEvent('altaha:planner')); } catch (e) {}
  }

  var sayTimer = null;
  function announce() {
    if (sayTimer) clearTimeout(sayTimer);
    sayTimer = setTimeout(function () {
      var live = $('mp-live');
      if (!live) return;
      live.textContent = d.status === 'dated' ? 'Work becomes optional in ' + M.monthName(d.when) + (d.ageThen ? ', at about ' + d.ageThen : '') + '.'
        : d.status === 'free' ? 'Work is already optional.'
        : d.status === 'none' ? 'No date on this path yet.' : '';
    }, 700);
  }

  /* The last visit's date is kept so a returning reader is told how far it
     has moved, rather than left to remember what it used to say. */
  function remember() {
    if (!d.ready) return;
    var day = isoDay(today());
    if (!state.seen || state.seen.on !== day) {
      state.prev = (state.seen && state.seen.when) ? state.seen : state.prev;
      state.seen = { on: day, when: d.when };
    } else state.seen.when = d.when;
  }

  function update() {
    d = M.derive(state, today());
    remember();
    host.querySelectorAll('[data-ready]').forEach(function (n) { n.hidden = !d.ready; });
    syncInputs();
    paintHero();
    paintPin();
    paintNumbers();
    paintPath();
    paintMoves();
    paintNext();
    paintTag();
    paintGoals();
    paintCheckin();
    paintBudget();
    paintTax();
    publish();
    announce();
    if (d.status === 'dated' && !announced && !state.example) { announced = true; track('planner_dated', {}); }
    save();
  }

  /* ── Tabs ────────────────────────────────────────────────────────────────── */

  var current = 'date';
  function open(id, quiet) {
    if (!host) return;
    if (!TABS.some(function (t) { return t.id === id; })) id = 'date';
    current = id;
    TABS.forEach(function (t) {
      var on = t.id === id, btn = $('mp-tab-' + t.id), panel = $('mp-panel-' + t.id);
      btn.setAttribute('aria-selected', String(on));
      btn.tabIndex = on ? 0 : -1;
      panel.hidden = !on;
      if (on && btn.scrollIntoView && !quiet) {
        try { btn.scrollIntoView({ block: 'nearest', inline: 'center', behavior: still() ? 'auto' : 'smooth' }); } catch (e) {}
      }
    });
    // A chart drawn while its tab was hidden was drawn at no width.
    if (id === 'date') redraw('mp-path-chart', paintPath);
    if (id === 'checkin') redraw('mp-ck-chart', paintCheckinChart);
    if (!quiet) { bringUp(); track('planner_tab_opened', { tab: id }); }
  }
  /* Under the hero a chosen tool starts two-thirds of the way down a laptop
     screen and off the bottom of a phone; deep in a long tool, the next one
     would open scrolled past its own heading. Either way the strip is brought
     to the top, where it sticks, and the tool gets the screen. */
  function bringUp() {
    var strip = $('mp-tabs'), panel = $('mp-panel-' + current);
    if (!strip || !panel || !strip.getBoundingClientRect) return;
    var top = panel.getBoundingClientRect().top, stripBox = strip.getBoundingClientRect();
    var low = top > window.innerHeight * 0.5, under = top < stripBox.bottom - 2;
    if (!low && !under) return;
    /* Measured from the panel, not the strip: a stuck sticky element reports
       itself as already in view, so asking the browser to scroll to it does
       nothing — and leaving a long tool for a short one then lands the reader
       in the site footer. */
    var chrome = doc.querySelector('.sh-chrome');
    var gap = parseFloat(getComputedStyle(strip).marginBottom) || 0;
    var y = top + window.scrollY - (chrome ? chrome.offsetHeight : 0) - strip.offsetHeight - gap;
    try { window.scrollTo({ top: Math.max(0, y), behavior: still() ? 'auto' : 'smooth' }); }
    catch (e) { window.scrollTo(0, Math.max(0, y)); }
  }
  function redraw(id, fn) {
    var box = $(id);
    if (box && box.clientWidth && Math.abs((box._w || 0) - Math.max(280, Math.round(box.clientWidth))) > 1) fn();
  }

  /* ── Actions ─────────────────────────────────────────────────────────────── */

  function dateNow() {
    return d.status === 'dated' ? 'Your date is now ' + M.monthName(d.when) + '.'
      : d.status === 'free' ? 'Work is already optional.' : 'There is no date on this path yet.';
  }
  function flash(id, text) {
    var n = $(id);
    if (!n) return;
    n.textContent = text;
    setTimeout(function () { if (n.textContent === text) n.textContent = ''; }, 4000);
  }

  function share() {
    var s = M.streak(state.log, d.now);
    var lines = [
      '*My money plan, on Altaha*',
      d.status === 'free' ? 'Work is already optional.' : 'Work becomes optional: ' + M.monthName(d.when),
      Math.round(d.progress * 100) + '% of the way there' +
        (d.income > 0 && d.put > 0 ? ' · putting away ' + Math.round(100 * d.put / d.income) + '% of take-home' : ''),
      s.count > 1 ? s.count + ' monthly check-ins in a row' : null,
      '',
      'Find your date: ' + location.origin + '/#portfolio/planner'
    ].filter(function (x) { return x !== null; });
    track('share_clicked', { kind: 'planner', action: 'whatsapp' });
    window.open('https://wa.me/?text=' + encodeURIComponent(lines.join('\n')), '_blank', 'noopener');
  }

  /* A calendar entry, because the planner has no way to tap anybody on the
     shoulder and no business holding an address to do it with. */
  function reminder() {
    var n = today(), first = new Date(n.getFullYear(), n.getMonth() + 1, 1);
    function ymd(dt) { return isoDay(dt).replace(/-/g, ''); }
    var url = location.origin + '/#portfolio/planner';
    var ics = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Altaha Screener//Money planner//EN', 'BEGIN:VEVENT',
      'UID:money-check-in@altahascreener.in',
      'DTSTAMP:' + n.toISOString().replace(/[-:]/g, '').replace(/\.\d+/, ''),
      'DTSTART;VALUE=DATE:' + ymd(first), 'RRULE:FREQ=MONTHLY;BYMONTHDAY=1',
      'SUMMARY:Money check-in: one minute',
      'DESCRIPTION:Log what you have invested this month and see whether you are ahead of your plan.\\n' + url,
      'URL:' + url,
      'BEGIN:VALARM', 'TRIGGER:PT9H', 'ACTION:DISPLAY', 'DESCRIPTION:Money check-in', 'END:VALARM',
      'END:VEVENT', 'END:VCALENDAR'
    ].join('\r\n');
    var a = doc.createElement('a');
    a.href = URL.createObjectURL(new Blob([ics], { type: 'text/calendar' }));
    a.download = 'money-check-in.ics';
    doc.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    flash('mp-ck-msg', 'Open the file to add it to your calendar.');
  }

  function copyPlan() {
    var sp = d.split, text = [
      'Salary-day plan: ' + M.inr(sp.put) + ' a month',
      '1. Cushion: ' + M.inr(sp.cushion),
      '2. Dated goals: ' + M.inr(sp.goals),
      '3. The long run: ' + M.inr(sp.longRun)
    ].join('\n');
    var done = function () { flash('mp-pay-msg', 'Copied.'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { flash('mp-pay-msg', 'Could not copy from here.'); });
    } else flash('mp-pay-msg', 'Could not copy from here.');
  }

  function act(el) {
    var a = el.getAttribute('data-act'), id = el.getAttribute('data-id');
    switch (a) {
      case 'start':
        open('date');
        var first = ['mp-age', 'mp-salary', 'mp-spend', 'mp-invested'].map($)
          .filter(function (n) { return n && !n.value && !n.readOnly; })[0] || $('mp-age');
        first.focus();
        break;
      case 'example': {
        var keep = { log: state.log, goals: state.goals, tags: state.tags, tax: state.tax };
        state = fresh();
        Object.keys(EXAMPLE).forEach(function (k) { state[k] = EXAMPLE[k]; });
        Object.keys(keep).forEach(function (k) { state[k] = keep[k]; });
        state.example = true;
        track('planner_example', {});
        update();
        break;
      }
      case 'mine':
        Object.keys(EXAMPLE).forEach(function (k) { state[k] = ''; });
        state.example = false;
        update();
        open('date');
        $('mp-age').focus();
        break;
      case 'tab': open(el.getAttribute('data-tab')); break;
      case 'share': share(); break;
      case 'defaults':
        ['stepUp', 'ret', 'infl', 'multiple', 'after'].forEach(function (k) { state[k] = ''; });
        update();
        break;

      case 'tag-mode':
        drafts.tag.monthly = el.getAttribute('data-mode') === 'monthly';
        paintTag();
        break;
      case 'tag-idea': {
        var idea = TAG_IDEAS[Number(el.getAttribute('data-i'))];
        drafts.tag = { name: idea[0], cost: String(idea[1]), monthly: idea[2] };
        $('mp-tag-name').value = idea[0];
        $('mp-tag-cost').value = shown(idea[1]);
        syncInputs();
        paintTag();
        break;
      }
      case 'tag-keep': {
        var cost = M.num(drafts.tag.cost);
        if (!cost) break;
        state.tags.unshift({ id: uid(), name: (drafts.tag.name || '').trim() || (drafts.tag.monthly ? 'A monthly cost' : 'A purchase'),
                             cost: cost, monthly: !!drafts.tag.monthly });
        state.tags = state.tags.slice(0, 8);
        track('planner_price_kept', { monthly: !!drafts.tag.monthly });
        drafts.tag = { name: '', cost: '', monthly: drafts.tag.monthly };
        $('mp-tag-name').value = ''; $('mp-tag-cost').value = '';
        update();
        break;
      }
      case 'tag-drop':
        state.tags = state.tags.filter(function (t) { return t.id !== id; });
        update();
        break;

      case 'goal-kind': {
        var kind = GOAL_KINDS.filter(function (k) { return k[0] === el.getAttribute('data-kind'); })[0];
        drafts.goal.kind = kind[0];
        drafts.goal.name = kind[0] === 'other' ? '' : kind[1];
        if (!drafts.goal.id) { drafts.goal.cost = String(kind[2]); drafts.goal.years = String(kind[3]); }
        fillGoalForm(); syncInputs(); paintGoals();
        $(kind[0] === 'other' ? 'mp-goal-name' : 'mp-goal-cost').focus();
        break;
      }
      case 'goal-save': {
        var g = drafts.goal, price = M.num(g.cost), years = Math.round(M.num(g.years));
        if (!price) { flash('mp-goal-msg', 'It needs a cost in today’s rupees.'); $('mp-goal-cost').focus(); break; }
        if (!years) { flash('mp-goal-msg', 'It needs a number of years.'); $('mp-goal-years').focus(); break; }
        years = Math.min(60, years);
        var label = (g.name || '').trim() || (GOAL_KINDS.filter(function (k) { return k[0] === g.kind; })[0] || [])[1] || 'A goal';
        var existing = g.id ? state.goals.filter(function (x) { return x.id === g.id; })[0] : null;
        if (existing) {
          existing.name = label; existing.cost = price; existing.saved = M.num(g.saved); existing.kind = g.kind;
          // Only a changed number of years moves the date; saving an edit a
          // month later must not quietly push the goal out by that month.
          if (String(years) !== g.yearsWas) existing.due = M.addMonths(d.now, years * 12);
        } else {
          state.goals.push({ id: uid(), name: label, kind: g.kind, cost: price, saved: M.num(g.saved), due: M.addMonths(d.now, years * 12) });
          track('planner_goal_added', { kind: g.kind });
        }
        drafts.goal = { id: null, kind: 'other', name: '', cost: '', years: '', saved: '' };
        fillGoalForm();
        update();
        flash('mp-goal-msg', (existing ? 'Saved. ' : 'Added. ') + dateNow());
        break;
      }
      case 'goal-edit': {
        var was = state.goals.filter(function (x) { return x.id === id; })[0];
        if (!was) break;
        var yrs = String(Math.max(1, Math.round(M.monthsBetween(d.now, was.due) / 12)));
        drafts.goal = { id: was.id, kind: was.kind || 'other', name: was.name, cost: String(was.cost),
                        years: yrs, yearsWas: yrs, saved: was.saved ? String(was.saved) : '' };
        fillGoalForm(); syncInputs(); paintGoals();
        $('mp-goal-form').scrollIntoView({ block: 'nearest', behavior: still() ? 'auto' : 'smooth' });
        $('mp-goal-name').focus();
        break;
      }
      case 'goal-cancel':
        drafts.goal = { id: null, kind: 'other', name: '', cost: '', years: '', saved: '' };
        fillGoalForm(); syncInputs(); paintGoals();
        break;
      case 'goal-drop':
        state.goals = state.goals.filter(function (x) { return x.id !== id; });
        if (drafts.goal.id === id) { drafts.goal = { id: null, kind: 'other', name: '', cost: '', years: '', saved: '' }; fillGoalForm(); }
        update();
        break;

      case 'ck-log': {
        var inv = M.num(drafts.ck.invested);
        if (!inv) { flash('mp-ck-msg', 'Type what you have invested today.'); $('mp-ck-invested').focus(); break; }
        var liq = drafts.ck.liquid === '' ? M.num(state.liquid) : M.num(drafts.ck.liquid);
        state.log = state.log.filter(function (e) { return e.ym !== d.now; });
        state.log.push({ ym: d.now, invested: inv, liquid: liq, on: isoDay(today()) });
        state.log = sortedLog().slice(-120);
        state.invested = String(Math.round(inv));
        state.liquid = liq ? String(Math.round(liq)) : state.liquid;
        state.example = false;
        drafts.ck.touched = false;
        update();
        var st = M.streak(state.log, d.now);
        track('planner_checkin', { streak: st.count });
        flash('mp-ck-msg', 'Logged. ' + dateNow());
        break;
      }
      case 'ck-drop':
        state.log = state.log.filter(function (e) { return e.ym !== el.getAttribute('data-ym'); });
        update();
        break;
      case 'ck-ics': reminder(); break;

      case 'bud-clear':
        state.cats = {};
        update();
        break;
      case 'pay-copy': copyPlan(); break;

      case 'reset':
        if (!window.confirm('Clear every number the planner has saved in this browser? This cannot be undone.')) break;
        state = fresh();
        ticked = [];
        drafts.tag = { name: '', cost: '', monthly: false };
        drafts.goal = { id: null, kind: 'other', name: '', cost: '', years: '', saved: '' };
        drafts.ck = { invested: '', liquid: '' };
        try { localStorage.removeItem(KEY); } catch (e) {}
        stored = JSON.stringify(state);
        host.querySelectorAll('[data-d]').forEach(function (n) { n.value = ''; });
        update();
        open('date', true);
        break;
    }
  }

  /* Group the digits as they are typed without moving the caret: count the
     digits to its right before, and put it back with as many after. */
  function liveFormat(el) {
    var raw = el.value, pos = el.selectionStart == null ? raw.length : el.selectionStart;
    var right = raw.slice(pos).replace(/\D/g, '').length;
    var out = shown(raw);
    if (out === raw) return;
    el.value = out;
    var i = out.length, seen = 0;
    while (i > 0 && seen < right) { i--; if (/\d/.test(out.charAt(i))) seen++; }
    try { el.setSelectionRange(i, i); } catch (e) {}
  }

  function wire() {
    host.addEventListener('input', function (e) {
      var el = e.target, kind = el.getAttribute && el.getAttribute('data-kind');
      var path = el.getAttribute && (el.getAttribute('data-f') || el.getAttribute('data-d'));
      if (!path) return;
      if (kind === 'inr') liveFormat(el);
      else if (kind === 'age') { var only = digits(el.value).slice(0, 2); if (only !== el.value) el.value = only; }

      if (el.hasAttribute('data-d')) {
        var p = path.split('.');
        drafts[p[0]][p[1]] = (kind === 'inr' || kind === 'age') ? digits(el.value) : el.value;
        if (p[0] === 'ck') drafts.ck.touched = true;
        syncInputs();
        if (p[0] === 'tag') paintTag();
        return;
      }
      if (kind === 'dial') set(path, Number(el.value));
      else set(path, digits(el.value));
      // Editing an example makes it theirs.
      if (state.example && /^(age|salary|spend|invested|put|other|liquid|cats\.)/.test(path)) state.example = false;
      update();
    });
    host.addEventListener('change', function (e) {
      var el = e.target;
      if (el.getAttribute && el.getAttribute('data-move')) {
        var id = el.getAttribute('data-move'), k = ticked.indexOf(id);
        if (el.checked && k < 0) ticked.push(id);
        if (!el.checked && k > -1) ticked.splice(k, 1);
        paintMoves();
        paintPath();
        var again = host.querySelector('[data-move="' + id + '"]');
        if (again) again.focus();
        return;
      }
      flush();
    });
    host.addEventListener('click', function (e) {
      var tab = e.target.closest && e.target.closest('.mp-tab');
      if (tab && host.contains(tab)) { open(tab.getAttribute('data-tab')); return; }
      var el = e.target.closest && e.target.closest('[data-act]');
      if (el && host.contains(el)) act(el);
    });
    $('mp-tabs').addEventListener('keydown', function (e) {
      var i = TABS.map(function (t) { return t.id; }).indexOf(current), to = -1;
      if (e.key === 'ArrowRight') to = (i + 1) % TABS.length;
      else if (e.key === 'ArrowLeft') to = (i - 1 + TABS.length) % TABS.length;
      else if (e.key === 'Home') to = 0;
      else if (e.key === 'End') to = TABS.length - 1;
      if (to < 0) return;
      e.preventDefault();
      open(TABS[to].id);
      $('mp-tab-' + TABS[to].id).focus();
    });
    window.addEventListener('pagehide', flush);
    // The same planner open in two tabs: the one being typed in is the truth.
    window.addEventListener('storage', function (e) {
      if (e.key !== KEY) return;
      state = load();
      stored = JSON.stringify(state);
      update();
    });
    doc.addEventListener('visibilitychange', function () { if (doc.visibilityState === 'hidden') flush(); });

    // The view is display:none until the planner is opened, and a phone can
    // be turned. Either way the charts are redrawn at the width they now have.
    if (window.ResizeObserver) {
      var pending = null;
      var ro = new ResizeObserver(function () {
        if (pending) return;
        pending = requestAnimationFrame(function () {
          pending = null;
          if (current === 'date') redraw('mp-path-chart', paintPath);
          if (current === 'checkin') redraw('mp-ck-chart', paintCheckinChart);
        });
      });
      ro.observe($('mp-path-chart'));
      ro.observe($('mp-ck-chart'));
    }
  }

  function mount() {
    host = $('mp');
    if (!host || !M) return;
    host.innerHTML = frame();
    // The questionnaire keeps its markup and its script; it is only housed.
    var risk = $('riskprofile');
    if (risk) $('mp-panel-risk').appendChild(risk);
    wire();
    update();
    open('date', true);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', mount);
  else mount();

  window.AltahaPlanner = {
    open: function (id) { open(id, true); },
    /* For the Portfolio overview card: the date, and whether a check-in is due,
       without that file knowing how either is worked out. */
    summary: function () {
      if (!M) return null;
      var x = M.derive(state, today()), st = M.streak(state.log, x.now);
      return { status: x.status, when: x.when, progress: x.progress, due: st.due, streak: st.count, example: !!state.example };
    }
  };
})();
