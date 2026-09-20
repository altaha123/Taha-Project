/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Allocate

   THE QUESTION THIS PRODUCT ANSWERS
   "What should I do with my money?" — which, answered honestly, is a question
   about ORDER before it is a question about products. Somebody with no
   emergency fund and a personal loan at 14% does not have a stock-picking
   problem, and handing them a shortlist first is how a tool does damage while
   looking helpful.

   SO THE ORDER IS THE PRODUCT
   Five steps, always in the same sequence, each showing where the reader
   actually stands against it: cushion, costly debt, money with a date on it,
   the long-term split, and only then the size of a single position. A step is
   never marked done on an assumption — unknown is a state, it is shown as
   one, and it says which screen would fill it in.

   IT NAMES NO PRODUCTS AND GIVES NO ADVICE
   Categories and arithmetic only, the same line the planner and the risk
   profile already hold. Under the SEBI adviser regulations, what to buy is
   not this project's to say, and the risk profile is what makes anything
   downstream of it defensible in the first place.

   IT COMPUTES IN THIS BROWSER
   The household numbers come from the planner's published state and the
   holdings from the portfolio's local store. The only network call is the
   recorded risk profile of a signed-in reader, which is their own record
   being read back.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';
  if (window.AltahaAllocate) return;

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE
    : (window.API_BASE || 'https://taha-project.onrender.com');

  var STORE_KEY = 'altaha-portfolios';
  var SIZE_KEY = 'altaha-allocate-size-v1';
  var MONEY_KEY = 'altaha-allocate-money-v1';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function inr(n) {
    if (n == null || isNaN(n)) return '—';
    return '₹' + Math.round(Number(n)).toLocaleString('en-IN');
  }

  /* ₹5,00,000 is the number being used; "5 lakh" is how it gets checked. A
     mistyped zero is invisible in the first and obvious in the second, and
     this page asks for the figure exactly once. */
  function words(n) {
    n = Number(n);
    if (!isFinite(n) || n <= 0) return '';
    function cut(x, unit) {
      var v = (n / x);
      return (v % 1 ? v.toFixed(2).replace(/0$/, '').replace(/\.$/, '') : v) + ' ' + unit;
    }
    if (n >= 1e7) return cut(1e7, 'crore');
    if (n >= 1e5) return cut(1e5, 'lakh');
    if (n >= 1e3) return cut(1e3, 'thousand');
    return '';
  }

  function planner() {
    return window.AltahaPlannerState || null;
  }

  /* The portfolio keeps named books in this browser. All that is wanted here
     is "is there a book, and roughly how big", so a shape that has drifted is
     treated as no book rather than as a crash. */
  function book() {
    try {
      var all = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {};
      var names = Object.keys(all);
      var best = null;
      names.forEach(function (n) {
        var rows = (all[n] && all[n].rows) || all[n];
        if (!Array.isArray(rows) || !rows.length) return;
        var value = 0, counted = 0;
        rows.forEach(function (r) {
          var qty = Number(r && (r.qty || r.quantity));
          var px = Number(r && (r.avg || r.avg_price || r.price));
          if (isFinite(qty) && isFinite(px) && qty > 0 && px > 0) { value += qty * px; counted++; }
        });
        if (!best || rows.length > best.holdings) {
          best = { name: n, holdings: rows.length, value: counted ? value : null };
        }
      });
      return best;
    } catch (e) { return null; }
  }

  /* ── The split, by profile band ─────────────────────────────────────────
     Ranges, not a number, and categories, not products. These are the
     conventional retail guardrails that sit behind the bands the risk
     questionnaire already returns — wide on purpose, because a band is a
     description of a person, not an instruction to a portfolio. */

  var SPLIT = {
    'Conservative': {
      growth: '10–25%', stable: '65–85%', gold: '0–10%',
      note: 'The job of this money is to still be there. A fall of more than a few percent would be a problem, so the growth sleeve stays small enough that a bad year is survivable without selling.'
    },
    'Moderately conservative': {
      growth: '25–40%', stable: '55–70%', gold: '0–10%',
      note: 'Some growth, but not at the cost of a fall that would force a sale at the wrong moment.'
    },
    'Balanced': {
      growth: '40–60%', stable: '35–55%', gold: '5–10%',
      note: 'Growth and protection weighed about equally. Swings are accepted as the price of the first, which only works if they were expected before they arrived.'
    },
    'Growth': {
      growth: '60–80%', stable: '15–35%', gold: '5–10%',
      note: 'A long horizon and the means to sit through a bad stretch. Drawdowns are expected rather than tolerated — the plan assumes them.'
    },
    'Aggressive': {
      growth: '75–90%', stable: '5–20%', gold: '0–10%',
      note: 'Both the circumstances and the temperament to hold through a deep fall. The limit here is usually not arithmetic; it is whether the last bad year was actually sat through.'
    }
  };

  /* ── What the reader has to allocate ─────────────────────────────────────
     Asked once, before the sequence, because every number below it is either
     a rupee figure derived from this or a rule of thumb that is not. The
     cushion gap, the growth sleeve and the size of one position are all the
     same arithmetic run against one input, and a page that never asks for it
     can only ever state the rules.

     "I'd rather not say" is a real answer and is recorded as one. The whole
     sequence works without the figure — every step already has an unknown
     state and says which screen fills it in — so refusing costs the reader
     precision, never access, and the question is never asked twice. */

  var lastProfile = null;

  function money() {
    try {
      var d = JSON.parse(localStorage.getItem(MONEY_KEY) || 'null');
      if (!d || typeof d !== 'object') return null;
      if (d.skipped) return { skipped: true };
      var a = Number(d.amount);
      return isFinite(a) && a > 0 ? { amount: a } : null;
    } catch (e) { return null; }
  }

  /* The total is NOT the sleeve. What buys individual stocks is the growth
     share of the long-term money, and which share that is comes from the
     recorded profile — so the calculator is seeded from the LOW end of the
     band, never from everything the reader just said they have. Without a
     profile there is no defensible fraction, so nothing is seeded and step 4
     says why. */
  function sleeveFrom(total) {
    if (!(total > 0)) return null;
    var sp = lastProfile && lastProfile.band && SPLIT[lastProfile.band];
    if (!sp) return null;
    var low = parseFloat(String(sp.growth).split(/[–-]/)[0]);
    return isFinite(low) ? Math.round(total * low / 100) : null;
  }

  function setMoney(amount, skipped) {
    var rec = skipped ? { skipped: true } : { amount: Number(amount) };
    try { localStorage.setItem(MONEY_KEY, JSON.stringify(rec)); } catch (e) {}
    /* Answering has to move a number further down the page, or the question
       was a toll booth. The calculator's own saved capital is overwritten
       with the sleeve this implies; the reader can still type over it, and
       that edit saves in the usual way. */
    if (!skipped) {
      var sleeve = sleeveFrom(Number(amount));
      if (sleeve != null) {
        try {
          var saved = JSON.parse(localStorage.getItem(SIZE_KEY) || '{}') || {};
          saved.capital = sleeve;
          localStorage.setItem(SIZE_KEY, JSON.stringify(saved));
        } catch (e) {}
      }
    }
    try {
      window.dispatchEvent(new CustomEvent('altaha:allocate-money', { detail: rec }));
    } catch (e) {}
  }

  function moneyBanner() {
    var m = money();
    if (!m) return '';
    if (m.skipped) {
      return '<div class="alc-money is-skip">' +
        '<div class="alc-money-l"><span class="k">To allocate</span>' +
          '<span class="v">Not said</span></div>' +
        '<p class="alc-money-n">The sequence below is the same either way. A figure ' +
          'turns the cushion gap and the size of one position into rupees instead of ' +
          'rules of thumb.</p>' +
        '<button class="act" type="button" data-money="1">Enter an amount</button>' +
      '</div>';
    }
    var w = words(m.amount);
    var sleeve = sleeveFrom(m.amount);
    return '<div class="alc-money">' +
      '<div class="alc-money-l"><span class="k">To allocate</span>' +
        '<span class="v">' + inr(m.amount) + '</span>' +
        (w ? '<span class="s">' + esc(w) + '</span>' : '') + '</div>' +
      '<p class="alc-money-n">' +
        (sleeve != null
          ? 'Your <b>' + esc(lastProfile.band) + '</b> profile puts ' +
            esc(SPLIT[lastProfile.band].growth) + ' of the long-term money in ' +
            'growth-type categories, so the calculator below starts from the low end ' +
            'of that — <b>' + inr(sleeve) + '</b> — and not from the whole amount.'
          : 'How much of this reaches individual stocks at all is what steps one to ' +
            'four decide. The calculator below sizes a position out of what survives ' +
            'them, never out of the total.') +
      '</p>' +
      '<button class="act" type="button" data-money="1">Change</button>' +
    '</div>';
  }

  /* ── The question ────────────────────────────────────────────────────────
     A modal, because it is the one thing on this page that has to be answered
     before the rest of it means anything in rupees, and a field at the top of
     a long page is a field that gets scrolled past.

     The quick amounts are there because this is read on a phone and nobody
     wants to type 500000 with a thumb. They are round numbers in the units
     Indian readers actually speak in — lakh, not hundred thousand. */

  var QUICK = [
    { v: 25000, t: '₹25,000' },
    { v: 100000, t: '₹1 lakh' },
    { v: 500000, t: '₹5 lakh' },
    { v: 1000000, t: '₹10 lakh' },
    { v: 2500000, t: '₹25 lakh' }
  ];

  var sheet = null;
  var restoreTo = null;

  function sheetEcho() {
    var box = $('alc-ask-e');
    var input = $('alc-ask');
    if (!box || !input) return;
    var v = Number(input.value);
    var go = $('alc-ask-go');
    var ok = isFinite(v) && v > 0;
    if (go) go.disabled = !ok;
    if (!input.value) { box.textContent = ''; return; }
    if (!ok) { box.textContent = 'An amount above zero, or “I’d rather not say”.'; return; }
    var w = words(v);
    box.textContent = inr(v) + (w ? ' · ' + w : '');
  }

  function buildSheet() {
    if (sheet) return sheet;
    sheet = document.createElement('div');
    sheet.className = 'alc-sheet';
    sheet.id = 'alc-sheet';
    sheet.hidden = true;
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-labelledby', 'alc-ask-t');

    sheet.innerHTML =
      '<div class="alc-back" data-shut="1"></div>' +
      '<div class="alc-box">' +
        '<button class="alc-x" type="button" data-shut="1" aria-label="Close">&times;</button>' +
        '<div class="alc-cash" aria-hidden="true">' +
          '<span>💰</span><span>💵</span><span>🪙</span><span>💸</span><span>💰</span>' +
        '</div>' +
        '<h4 class="alc-ask-t" id="alc-ask-t">How much money do you have?</h4>' +
        '<p class="alc-ask-s">The money you are deciding about — savings you could put ' +
          'to work, not your monthly income. Everything on this page is worked out from ' +
          'it, it stays in this browser, and it is never sent anywhere.</p>' +
        '<div class="alc-quick">' +
          QUICK.map(function (q) {
            return '<button class="alc-q" type="button" data-amt="' + q.v + '">' +
              esc(q.t) + '</button>';
          }).join('') +
        '</div>' +
        '<label class="alc-ask-f" for="alc-ask"><span>Or type the amount</span></label>' +
        '<div class="alc-ask-in"><i aria-hidden="true">₹</i>' +
          '<input id="alc-ask" type="number" inputmode="numeric" min="0" step="1000" ' +
            'placeholder="0" aria-describedby="alc-ask-e"></div>' +
        '<p class="alc-ask-e" id="alc-ask-e" aria-live="polite"></p>' +
        '<div class="alc-ask-b">' +
          '<button class="alc-go" id="alc-ask-go" type="button" data-go="1" disabled>' +
            'Start the plan</button>' +
          '<button class="alc-skip" type="button" data-skip="1">I’d rather not say</button>' +
        '</div>' +
        '<p class="alc-ask-d">Structure and arithmetic only. No product is named here ' +
          'and nothing on this page is investment advice.</p>' +
      '</div>';

    document.body.appendChild(sheet);

    sheet.addEventListener('click', function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      if (t.getAttribute && t.getAttribute('data-shut')) { closeSheet(); return; }
      var q = t.closest('[data-amt]');
      if (q) {
        var input = $('alc-ask');
        if (input) { input.value = q.getAttribute('data-amt'); sheetEcho(); input.focus(); }
        sheet.querySelectorAll('.alc-q').forEach(function (n) {
          n.classList.toggle('on', n === q);
        });
        return;
      }
      if (t.closest('[data-go]')) { commitSheet(); return; }
      if (t.closest('[data-skip]')) { setMoney(null, true); closeSheet(); render(); }
    });

    sheet.addEventListener('input', function (ev) {
      if (ev.target && ev.target.id === 'alc-ask') {
        sheet.querySelectorAll('.alc-q.on').forEach(function (n) { n.classList.remove('on'); });
        sheetEcho();
      }
    });

    /* Enter is what a number pad offers instead of a button. */
    sheet.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && ev.target && ev.target.id === 'alc-ask') {
        ev.preventDefault();
        commitSheet();
      }
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && sheet && !sheet.hidden) closeSheet();
    });

    return sheet;
  }

  function commitSheet() {
    var input = $('alc-ask');
    var v = input ? Number(input.value) : NaN;
    if (!isFinite(v) || v <= 0) { sheetEcho(); if (input) input.focus(); return; }
    setMoney(v, false);
    closeSheet();
    render();
  }

  function closeSheet() {
    if (!sheet) return;
    sheet.hidden = true;
    document.body.classList.remove('alc-open');
    if (restoreTo && restoreTo.focus) { try { restoreTo.focus(); } catch (e) {} }
    restoreTo = null;
  }

  function askMoney() {
    buildSheet();
    restoreTo = document.activeElement;
    var m = money();
    var input = $('alc-ask');
    if (input) {
      input.value = (m && m.amount) ? m.amount : '';
      sheet.querySelectorAll('.alc-q').forEach(function (n) {
        n.classList.toggle('on', m && Number(n.getAttribute('data-amt')) === m.amount);
      });
    }
    sheetEcho();
    sheet.hidden = false;
    document.body.classList.add('alc-open');
    if (input) setTimeout(function () { try { input.focus(); } catch (e) {} }, 40);
  }

  var asked = false;

  /* Once per page load, and only when the figure has never been given or
     refused. A modal that reappears on every visit is a modal people learn to
     dismiss without reading. */
  function maybeAsk() {
    if (asked || money()) return;
    asked = true;
    askMoney();
  }

  function chip(state) {
    var label = { done: 'On track', part: 'In progress', todo: 'Not started', unknown: 'Not known yet' }[state];
    return '<span class="alc-chip is-' + state + '">' + label + '</span>';
  }

  /* `reading` is a sentence, `extra` is whatever block belongs under it. Two
     parameters rather than one string of HTML, so no caller has to close a
     paragraph it did not open. */
  function step(n, title, state, reading, action, extra) {
    return '<li class="alc-step is-' + state + '">' +
      '<span class="alc-n">' + n + '</span>' +
      '<div class="alc-body">' +
        '<div class="alc-t"><h3>' + esc(title) + '</h3>' + chip(state) + '</div>' +
        '<p class="alc-read">' + reading + '</p>' +
        (extra || '') +
        (action || '') +
      '</div></li>';
  }

  function act(label, goto_) {
    return '<button class="act" type="button" data-goto="' + esc(goto_) + '">' +
      esc(label) + '</button>';
  }

  /* ── The sequence ───────────────────────────────────────────────────────── */

  function steps(profile) {
    var p = planner();
    var b = book();
    var out = [];

    /* 1 · The cushion. Unconditionally first: its job is to stop every other
       decision on this page from being unwound by one bad month. */
    if (!p) {
      out.push(step(1, 'Build the cushion first', 'unknown',
        'Six months of expenses, somewhere you can reach the same day. Until the ' +
        'planner has your monthly numbers there is nothing to measure this against.',
        act('Open the money planner', 'allocate/planner')));
    } else if (p.efMonths == null) {
      out.push(step(1, 'Build the cushion first', 'unknown',
        'Enter your monthly expenses and what you hold in liquid savings, and this ' +
        'becomes a number instead of a rule of thumb.',
        act('Open the money planner', 'allocate/planner')));
    } else if (p.efMonths >= 6) {
      out.push(step(1, 'Build the cushion first', 'done',
        'You hold <b>' + p.efMonths.toFixed(1) + ' months</b> of expenses in liquid savings, ' +
        'past the six-month mark. This is what lets a job loss or a medical event ' +
        'happen without a single holding being sold to pay for it.', ''));
    } else {
      out.push(step(1, 'Build the cushion first', p.efMonths >= 3 ? 'part' : 'todo',
        'You hold <b>' + p.efMonths.toFixed(1) + ' months</b> of expenses against a six-month target — ' +
        '<b>' + inr(p.efGap) + '</b> still to go. Until it exists, it outranks every ' +
        'investment on this site, because its job is to keep the investments from ' +
        'ever being broken into during a crisis.',
        act('Open the money planner', 'allocate/planner')));
    }

    /* 2 · Costly debt. A guaranteed 14% saved beats an uncertain 12% earned,
       and no screener on this site changes that arithmetic. */
    if (!p || !isFinite(p.emiRatio)) {
      out.push(step(2, 'Clear the expensive debt', 'unknown',
        'Any borrowing costing more than a portfolio can be expected to earn is ' +
        'repaid before it is invested around. Paying off a 14% loan is a guaranteed ' +
        '14%; nothing on this site is guaranteed anything.',
        act('Open the money planner', 'allocate/planner')));
    } else if (p.emiRatio <= 40) {
      out.push(step(2, 'Clear the expensive debt', 'done',
        'EMIs take <b>' + p.emiRatio.toFixed(1) + '%</b> of income, inside the 40% line ' +
        'lenders themselves use. Personal loans and revolving card balances still go ' +
        'first if you carry any — a guaranteed saving beats an uncertain return.', ''));
    } else {
      out.push(step(2, 'Clear the expensive debt', 'todo',
        'EMIs take <b>' + p.emiRatio.toFixed(1) + '%</b> of income, past the 40% line lenders ' +
        'use. Above it, one bad month cascades. New investing waits until something ' +
        'is closed.',
        act('Open the money planner', 'allocate/planner')));
    }

    /* 3 · Money with a date on it. No arithmetic can make this one safe, so it
       is stated rather than scored. */
    out.push(step(3, 'Park money that has a date on it', 'unknown',
      'A car, a wedding, a deposit, school fees — anything needed inside about five ' +
      'years does not belong in equities. A 30% drawdown in the year you need the ' +
      'money is a plan-ending event, and no amount of being right eventually fixes ' +
      'it. Fixed deposits, recurring deposits and debt-type categories exist for ' +
      'exactly this. Only you know which goals you have, so this step is never ' +
      'marked complete for you.',
      act('See the planner’s bucket sequence', 'allocate/planner')));

    /* 4 · The split. Driven by the recorded profile, never by what the reader
       hopes it is. */
    if (!profile || !profile.band || !SPLIT[profile.band]) {
      out.push(step(4, 'Decide the long-term split', 'unknown',
        'How much of the long-term money carries equity risk is the one decision ' +
        'that explains most of what happens to it afterwards, and it follows from ' +
        'your profile — the lower of what your circumstances can carry and what your ' +
        'temperament can sit through. Answer the questionnaire and this step fills in.',
        act('Take the risk profile', 'allocate/planner')));
    } else {
      var sp = SPLIT[profile.band];
      out.push(step(4, 'Decide the long-term split', 'part',
        'Your profile is <b>' + esc(profile.band) + '</b>' +
        (profile.score != null ? ' (' + profile.score + ' of 100)' : '') + '. ' + esc(sp.note) +
        (profile.recorded === false
          ? ' This one was worked out in this browser and not recorded — sign in on the ' +
            'planner if you want it kept.'
          : ''),
        act('Re-take the risk profile', 'allocate/planner'),
        '<div class="alc-split">' +
          '<div><span class="k">Growth-type</span><span class="v">' + sp.growth + '</span>' +
            '<small>Equity and equity-linked categories</small></div>' +
          '<div><span class="k">Stable</span><span class="v">' + sp.stable + '</span>' +
            '<small>Deposits and debt-type categories</small></div>' +
          '<div><span class="k">Gold</span><span class="v">' + sp.gold + '</span>' +
            '<small>A diversifier, in a minority</small></div>' +
        '</div>' +
        '<p class="alc-read">Categories, never products. Which specific fund or ' +
        'scheme is between you and a registered adviser.</p>'));
    }

    /* 5 · Position size. The step where this site's own research finally
       becomes relevant, and not one step earlier. */
    if (b && b.holdings) {
      out.push(step(5, 'Size one position at a time', 'part',
        'You are holding <b>' + b.holdings + '</b> ' + (b.holdings === 1 ? 'stock' : 'stocks') +
        (b.value ? ' worth about <b>' + inr(b.value) + '</b> at your entry prices' : '') +
        '. Below eight holdings, one company decides the outcome of the whole book. ' +
        'The calculator below turns the growth sleeve into a per-position number.',
        act('Review the holdings', 'portfolio/portfolio')));
    } else {
      out.push(step(5, 'Size one position at a time', 'todo',
        'Only what is left after the four steps above buys individual stocks, and it ' +
        'buys them in pieces small enough that being wrong about one is survivable. ' +
        'The calculator below turns the growth sleeve into a per-position number.',
        act('Open the stock screener', 'research/ideas')));
    }

    return '<ol class="alc-steps">' + out.join('') + '</ol>';
  }

  /* ── The sizing calculator ──────────────────────────────────────────────
     Two conventional caps, both editable, both echoed back in the arithmetic
     so the reader can disagree with the inputs rather than with the answer:
     no single holding past a share of the book, and no single entry risking
     more than a small share of it once the stop is hit. */

  function sizer() {
    var host = $('alc-size');
    if (!host) return;
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(SIZE_KEY) || '{}') || {}; } catch (e) {}
    var p = planner();
    var b = book();
    /* What the reader said they have, reduced to the growth sleeve, beats both
       older guesses: the book is what they already bought and twelve months of
       savings is a projection. Their own edit to this field still wins. */
    var m = money();
    var sleeve = (m && m.amount) ? sleeveFrom(m.amount) : null;
    var seed = saved.capital != null ? saved.capital
             : sleeve != null ? sleeve
             : (b && b.value ? Math.round(b.value) : (p && p.savings > 0 ? Math.round(p.savings * 12) : ''));

    host.innerHTML =
      '<div class="psec">' +
        '<div class="lh"><h3>How much in one position</h3><span>Arithmetic, in this browser</span></div>' +
        '<p class="lsub">Two limits decide it, and the smaller one wins. The first caps ' +
          'how much of the book any single company can be. The second caps what you lose ' +
          'if the stop is hit — which is the one that actually keeps a bad year from ' +
          'becoming a bad decade.</p>' +
        '<div class="pgrid pgrid3">' +
          '<label class="pfield"><span class="k">Money for individual stocks <i>the growth sleeve, not everything you own</i></span>' +
            '<input type="number" class="pin alc-in" id="alc_cap" min="0" placeholder="e.g. 500000" value="' + esc(seed) + '"></label>' +
          '<label class="pfield"><span class="k">Cap per stock <i>share of the book</i></span>' +
            '<input type="number" class="pin alc-in" id="alc_cap_pct" min="1" max="100" step="0.5" value="' + esc(saved.capPct != null ? saved.capPct : 15) + '"></label>' +
          '<label class="pfield"><span class="k">Risk per entry <i>share of the book lost if stopped</i></span>' +
            '<input type="number" class="pin alc-in" id="alc_risk_pct" min="0.1" max="10" step="0.1" value="' + esc(saved.riskPct != null ? saved.riskPct : 1) + '"></label>' +
          '<label class="pfield"><span class="k">Stop distance <i>how far below entry the stop sits</i></span>' +
            '<input type="number" class="pin alc-in" id="alc_stop_pct" min="0.5" max="50" step="0.5" value="' + esc(saved.stopPct != null ? saved.stopPct : 8) + '"></label>' +
        '</div>' +
        '<div id="alc_out"></div>' +
      '</div>';

    host.querySelectorAll('.alc-in').forEach(function (n) {
      n.addEventListener('input', compute);
    });
    compute();
  }

  function val(id) {
    var n = $(id);
    var v = n ? Number(n.value) : NaN;
    return isFinite(v) ? v : NaN;
  }

  function compute() {
    var out = $('alc_out');
    if (!out) return;
    var cap = val('alc_cap'), capPct = val('alc_cap_pct'),
        riskPct = val('alc_risk_pct'), stopPct = val('alc_stop_pct');

    if (!isFinite(cap) || cap <= 0) {
      out.innerHTML = '<p class="lsub">Enter what you have set aside for individual ' +
        'stocks and the two limits resolve into rupees.</p>';
      return;
    }
    if (!(capPct > 0) || !(riskPct > 0) || !(stopPct > 0)) {
      out.innerHTML = '<p class="lsub">Every limit has to be above zero for this to mean anything.</p>';
      return;
    }

    var byCap = cap * capPct / 100;
    var rupeesAtRisk = cap * riskPct / 100;
    var byRisk = rupeesAtRisk / (stopPct / 100);
    var size = Math.min(byCap, byRisk);
    var binding = byRisk < byCap ? 'risk' : 'cap';
    var positions = Math.max(1, Math.floor(cap / size));

    out.innerHTML =
      '<div class="alc-res">' +
        '<div class="alc-big"><span class="k">One position</span>' +
          '<span class="v">' + inr(size) + '</span>' +
          '<span class="s">' + (size / cap * 100).toFixed(1) + '% of the sleeve</span></div>' +
        '<div class="alc-big"><span class="k">At risk if stopped</span>' +
          '<span class="v">' + inr(rupeesAtRisk) + '</span>' +
          '<span class="s">' + riskPct.toFixed(1) + '% of the sleeve</span></div>' +
        '<div class="alc-big"><span class="k">Room for</span>' +
          '<span class="v">' + positions + '</span>' +
          '<span class="s">position' + (positions === 1 ? '' : 's') + ' this size</span></div>' +
      '</div>' +
      '<p class="lsub"><b>' + (binding === 'risk' ? 'The stop is the binding limit.' : 'The per-stock cap is the binding limit.') + '</b> ' +
        (binding === 'risk'
          ? 'A ' + stopPct.toFixed(1) + '% stop and ' + riskPct.toFixed(1) + '% of ' + inr(cap) +
            ' at risk allows ' + inr(byRisk) + '; the ' + capPct.toFixed(1) + '% cap would have allowed ' + inr(byCap) +
            '. A wider stop does not earn a bigger position — it buys a smaller one.'
          : 'The ' + capPct.toFixed(1) + '% cap allows ' + inr(byCap) + '; the stop would have allowed ' +
            inr(byRisk) + '. Concentration, not the stop, is what is limiting you here.') +
      '</p>' +
      (positions < 8
        ? '<p class="alc-warn">At this size the sleeve holds ' + positions + ' position' +
          (positions === 1 ? '' : 's') + '. Below about eight, one company decides the ' +
          'outcome of the whole book — which is a bet on being right once, not a portfolio.</p>'
        : '') +
      '<p class="lsub">Position size follows from the stop, never from conviction. ' +
        'That ordering is the whole of what separates a plan from a hunch, and it is ' +
        'not this site telling you to buy anything.</p>';

    try {
      localStorage.setItem(SIZE_KEY, JSON.stringify({
        capital: cap, capPct: capPct, riskPct: riskPct, stopPct: stopPct
      }));
    } catch (e) {}
  }

  /* ── Risk profile ───────────────────────────────────────────────────────
     Signed in, the recorded assessment is read back — it is the reader's own
     record. Signed out, nothing is invented: step 4 stays "not known yet" and
     says which screen fills it in. */

  function profile() {
    var a = window.AltahaAuth;
    if (!a || !a.authed || !a.authed()) {
      /* Signed out, the questionnaire still computes a profile and publishes
         it. Using it beats inventing a second copy of that arithmetic here,
         and step 4 says plainly that it was never recorded. */
      var local = window.AltahaRiskProfile;
      if (local && local.band) {
        return Promise.resolve({ band: local.band, score: local.score, recorded: false });
      }
      return Promise.resolve(null);
    }
    return a.fetch('/me/risk-profile')
      .then(function (r) { return r && r.ok ? r.json() : null; })
      .then(function (d) { return (d && d.profile) ? d.profile : null; })
      .catch(function () { return null; });
  }

  /* ── Mounting ───────────────────────────────────────────────────────────── */

  function render() {
    var host = $('alc-steps');
    if (!host) return;
    profile().then(function (p) {
      /* Held because the sleeve arithmetic needs the band, and both the banner
         and the calculator are painted from it after this resolves. */
      lastProfile = p;
      host.innerHTML = moneyBanner() + steps(p);
      sizer();
      maybeAsk();
    });
    var disc = $('alc-disc');
    if (disc) {
      disc.textContent = 'Structure and arithmetic only. No product is named here, ' +
        'no security is recommended, and nothing on this page is investment advice. ' +
        'Everything computes in this browser.';
    }
  }

  var painted = false;

  function open(force) {
    if (!$('alc-steps')) return;
    if (painted && !force) return;
    painted = true;
    render();
  }

  /* The household numbers change while somebody types in the planner, and a
     sequence showing yesterday's cushion is worse than one showing none. */
  window.addEventListener('altaha:planner', function () {
    if (painted) render();
  });
  window.addEventListener('altaha-auth', function () {
    if (painted) render();
  });
  window.addEventListener('altaha:risk', function () {
    if (painted) render();
  });

  /* Delegated once on the document rather than rebound on every repaint —
     the banner is replaced wholesale each render and a listener attached to it
     would be re-added with every planner keystroke. */
  document.addEventListener('click', function (ev) {
    var b = ev.target && ev.target.closest && ev.target.closest('[data-money]');
    if (b) { ev.preventDefault(); askMoney(); }
  });

  window.AltahaAllocate = {
    open: open,
    refresh: function () { open(true); },
    ask: askMoney,
    money: money
  };

  function boot() {
    var v = $('view-allocate');
    if (v && v.style.display !== 'none') open(false);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 400); });
  } else {
    setTimeout(boot, 400);
  }
  setInterval(boot, 2000);
})();
