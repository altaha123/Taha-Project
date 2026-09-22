/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Allocate · the guided card

   WHAT THIS IS
   Three questions asked in the only order that makes them answerable: how
   much money, what kind of risk that money can carry, and only then which
   asset classes the answer implies. One card, one question at a time, each
   stage replacing the last.

   WHY A SLIDER FROM ₹1 TO ₹20 CRORE, ON A LOG SCALE
   A linear slider across that range is unusable: ₹50,000 and ₹5,00,000 sit
   within one pixel of each other, so everybody below a crore is handed the
   same answer. The scale here is logarithmic, which gives every order of
   magnitude the same width of track — the sum a person actually has is always
   reachable, whether it is five figures or nine. The exact figure stays
   typeable beside it, because a slider is for exploring and a keyboard is for
   meaning it.

   WHY THE PROFILE COMES SECOND AND THE ASSET CLASSES LAST
   An amount without a profile is a number. A profile without an amount is a
   description. Neither is an allocation. The questions are the ones the server
   already serves — same ids, same weights, same draft — so answering them here
   is answering them in the planner, and nobody is asked twice.

   WHAT IT WILL NOT DO
   It names categories, never products. It gives ranges, never a single number
   presented as the right one. It issues no instruction to buy or sell
   anything. Under the SEBI adviser regulations what to buy is not this
   project's to say, and the profile is what makes anything downstream of it
   defensible at all.

   EVERYTHING COMPUTES IN THIS BROWSER. The only network calls are the
   questionnaire itself and, for a signed-in reader, recording their own
   profile against their own account.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var doc = root.document;

  /* ── The money scale ───────────────────────────────────────────────────── */

  var MIN_RUPEES = 1;
  var MAX_RUPEES = 200000000;          // ₹20 crore
  var TRACK = 10000;                   // slider positions, not rupees

  /* Two log segments, not one. A single log scale from ₹1 spends three fifths
     of the track on sums below a lakh — amounts nobody is allocating — and
     squeezes ₹1 lakh to ₹20 crore, the range this card is actually for, into
     the last two fifths. The knee gives the first five decades a fifth of the
     track and the remaining three and a bit decades the other four fifths.
     Still monotonic, still exactly invertible, and ₹1 is still reachable. */
  var KNEE_POS = 0.2;
  var KNEE_RUPEES = 100000;            // ₹1 lakh
  var LOG_MIN = Math.log(MIN_RUPEES);
  var LOG_KNEE = Math.log(KNEE_RUPEES);
  var LOG_MAX = Math.log(MAX_RUPEES);

  /* Rounded to something a person would actually say out loud. A slider that
     reports ₹1,03,477 is reporting its own pixel width, not an intention. */
  function snap(value) {
    var v = Math.max(MIN_RUPEES, Math.min(MAX_RUPEES, value));
    var step = v < 1000 ? 1
             : v < 100000 ? 500
             : v < 1000000 ? 5000
             : v < 10000000 ? 25000
             : v < 100000000 ? 100000
             : 500000;
    return Math.max(MIN_RUPEES, Math.min(MAX_RUPEES, Math.round(v / step) * step));
  }

  function sliderToRupees(pos) {
    var t = Math.max(0, Math.min(TRACK, Number(pos) || 0)) / TRACK;
    var log = t <= KNEE_POS
      ? LOG_MIN + (t / KNEE_POS) * (LOG_KNEE - LOG_MIN)
      : LOG_KNEE + ((t - KNEE_POS) / (1 - KNEE_POS)) * (LOG_MAX - LOG_KNEE);
    return snap(Math.exp(log));
  }

  function rupeesToSlider(value) {
    var v = Math.max(MIN_RUPEES, Math.min(MAX_RUPEES, Number(value) || MIN_RUPEES));
    var log = Math.log(v);
    var t = log <= LOG_KNEE
      ? (log - LOG_MIN) / (LOG_KNEE - LOG_MIN) * KNEE_POS
      : KNEE_POS + (log - LOG_KNEE) / (LOG_MAX - LOG_KNEE) * (1 - KNEE_POS);
    var pos = Math.round(t * TRACK);
    // Snapping means several positions can share a value. Land on the one that
    // reads back closest, so picking ₹1 Cr and then nudging the slider does not
    // first jump to ₹99.5 lakh.
    var best = pos, gap = Math.abs(sliderToRupees(pos) - v);
    [pos - 2, pos - 1, pos + 1, pos + 2].forEach(function (candidate) {
      if (candidate < 0 || candidate > TRACK) return;
      var d = Math.abs(sliderToRupees(candidate) - v);
      if (d < gap) { gap = d; best = candidate; }
    });
    return best;
  }

  function inr(value) {
    if (value == null || !isFinite(value)) return '—';
    return '₹' + Math.round(value).toLocaleString('en-IN');
  }

  /* Crore and lakh, because that is how the amount will be said back to
     somebody by every other person in the country. */
  function words(value) {
    var v = Number(value);
    if (!isFinite(v)) return '—';
    if (v >= 10000000) return '₹' + trim(v / 10000000) + ' Cr';
    if (v >= 100000) return '₹' + trim(v / 100000) + ' L';
    if (v >= 1000) return '₹' + trim(v / 1000) + 'K';
    return '₹' + Math.round(v);
  }
  function plain(value) { return words(value).replace('₹', ''); }

  function trim(n) {
    var s = n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2);
    return s.replace(/\.0+$/, '').replace(/(\.\d)0$/, '$1');
  }

  /* ── The split, by band ────────────────────────────────────────────────────
     Numeric twins of the ranges the step list already shows in words.
     `frontend/risk-math.test.js` asserts the two never drift apart.
     Wide on purpose: a band describes a person, not a portfolio. */

  var SPLIT = {
    'Conservative':             { growth: [10, 25], stable: [65, 85], gold: [0, 10] },
    'Moderately conservative':  { growth: [25, 40], stable: [55, 70], gold: [0, 10] },
    'Balanced':                 { growth: [40, 60], stable: [35, 55], gold: [5, 10] },
    'Growth':                   { growth: [60, 80], stable: [15, 35], gold: [5, 10] },
    'Aggressive':               { growth: [75, 90], stable: [5, 20],  gold: [0, 10] }
  };

  /* Inside each sleeve, the shape shifts with the band: the same 50% in
     equities is a different thing held as broad-market index exposure than
     held in mid and small companies. Shares are of the sleeve, not the book. */
  var GROWTH_MIX = {
    'Conservative':            [['Broad-market Indian equity', 75], ['International equity', 25]],
    'Moderately conservative': [['Broad-market Indian equity', 70], ['Mid & small-cap Indian equity', 10], ['International equity', 20]],
    'Balanced':                [['Broad-market Indian equity', 60], ['Mid & small-cap Indian equity', 20], ['International equity', 20]],
    'Growth':                  [['Broad-market Indian equity', 50], ['Mid & small-cap Indian equity', 30], ['International equity', 20]],
    'Aggressive':              [['Broad-market Indian equity', 45], ['Mid & small-cap Indian equity', 40], ['International equity', 15]]
  };
  var STABLE_MIX = {
    'Conservative':            [['Deposits & short-duration debt', 60], ['Government-backed long-term savings', 40]],
    'Moderately conservative': [['Deposits & short-duration debt', 55], ['Government-backed long-term savings', 45]],
    'Balanced':                [['Deposits & short-duration debt', 55], ['Government-backed long-term savings', 45]],
    'Growth':                  [['Deposits & short-duration debt', 60], ['Government-backed long-term savings', 40]],
    'Aggressive':              [['Deposits & short-duration debt', 65], ['Government-backed long-term savings', 35]]
  };

  var WHY = {
    'Broad-market Indian equity':
      'The whole market rather than a view about part of it. The cheapest way to own the growth sleeve and the hardest to be badly wrong with.',
    'Mid & small-cap Indian equity':
      'Higher expected return and materially deeper falls. It is the part of the sleeve that decides whether a bad year is sat through.',
    'International equity':
      'The Indian market is one economy and one currency. Exposure elsewhere is diversification, and it carries currency movement and its own tax treatment.',
    'Deposits & short-duration debt':
      'The money that has to still be there. Short duration because a long bond falls when rates rise, which is exactly the wrong moment.',
    'Government-backed long-term savings':
      'Sovereign-backed, long-locked and usually tax-favoured. The lock is the cost, and it is only a cost if the money was needed sooner.',
    'Gold':
      'A diversifier held in a minority. It earns nothing and has gone a decade sideways; its job is to behave differently from the rest, not to grow.'
  };

  var BAND_NOTE = {
    'Conservative': 'The job of this money is to still be there. The growth sleeve stays small enough that a bad year is survivable without selling.',
    'Moderately conservative': 'Some growth, but not at the cost of a fall that would force a sale at the wrong moment.',
    'Balanced': 'Growth and protection weighed about equally. Swings are the price of the first, which only works if they were expected before they arrived.',
    'Growth': 'A long horizon and the means to sit through a bad stretch. Drawdowns are expected rather than tolerated — the plan assumes them.',
    'Aggressive': 'Both the circumstances and the temperament to hold through a deep fall. The limit is rarely arithmetic; it is whether the last bad year was actually sat through.'
  };

  /* The three ranges are independent guardrails, so their midpoints do not add
     to 100% — Balanced centres on 50 + 45 + 7.5. Handing somebody three rupee
     figures that sum to 102.5% of their money is the kind of error a reader
     finds with a calculator, so the midpoints are scaled to the amount and the
     scaling is stated on the card. Each scaled share still lands inside its
     own published range. */
  function slice(amount, range, scale) {
    var mid = (range[0] + range[1]) / 2 * (scale || 1);
    return { low: range[0], high: range[1], mid: Math.round(mid * 10) / 10,
             rupees_low: Math.round(amount * range[0] / 100),
             rupees_high: Math.round(amount * range[1] / 100),
             rupees_mid: Math.round(amount * mid / 100) };
  }

  /* ₹48,78,049 claims a precision that a 40–60% guardrail does not have. The
     figures are rounded to a unit that matches the size of the sum, and the
     rounding drift is pushed onto the largest line so the parts still add to
     exactly what the reader put in. */
  function unitFor(total) {
    return total >= 10000000 ? 10000
         : total >= 1000000 ? 5000
         : total >= 100000 ? 1000
         : total >= 10000 ? 100 : 1;
  }

  function reconcile(parts, target, unit) {
    if (!parts.length) return parts;
    parts.forEach(function (p) { p.rupees = Math.round(p.rupees / unit) * unit; });
    var drift = target - parts.reduce(function (sum, p) { return sum + p.rupees; }, 0);
    var biggest = parts.reduce(function (a, b) { return b.rupees > a.rupees ? b : a; }, parts[0]);
    biggest.rupees += drift;
    return parts;
  }

  function midScale(split) {
    var raw = ['growth', 'stable', 'gold'].reduce(function (sum, key) {
      return sum + (split[key][0] + split[key][1]) / 2;
    }, 0);
    return raw > 0 ? 100 / raw : 1;
  }

  function sleeves(amount, share, mix) {
    var rows = (mix || []).map(function (pair) {
      var pctOfTotal = share.mid * pair[1] / 100;
      return { label: pair[0], share_of_sleeve_pct: pair[1],
               pct_of_total: Math.round(pctOfTotal * 10) / 10,
               rupees: Math.round(amount * pctOfTotal / 100),
               why: WHY[pair[0]] || '' };
    });
    return reconcile(rows, share.rupees_mid, unitFor(amount));
  }

  /* ── The plan ──────────────────────────────────────────────────────────────
     Pure: band + amount + the answers already given, in, one object out. The
     flags are the part that matters most — an allocation handed to somebody
     whose money is needed next year, or who has no cushion, is arithmetic
     wrapped around a mistake. */

  function plan(band, amount, answers) {
    var split = SPLIT[band];
    if (!split || !(amount > 0)) return null;
    var a = answers || {};

    var scale = midScale(split);
    var growth = slice(amount, split.growth, scale);
    var stable = slice(amount, split.stable, scale);
    var gold = slice(amount, split.gold, scale);

    // Round the three sleeves against the total first, so the sleeve figures
    // inside each one are built from the number actually shown above them.
    var unit = unitFor(amount);
    reconcile([growth, stable, gold].map(function (sh) {
      return { get rupees() { return sh.rupees_mid; }, set rupees(v) { sh.rupees_mid = v; } };
    }), amount, unit);

    var groups = [
      { key: 'growth', label: 'Growth-type', kind: 'Equity and equity-linked categories',
        share: growth, sleeves: sleeves(amount, growth, GROWTH_MIX[band]) },
      { key: 'stable', label: 'Stable', kind: 'Deposits and debt-type categories',
        share: stable, sleeves: sleeves(amount, stable, STABLE_MIX[band]) },
      { key: 'gold', label: 'Gold', kind: 'A diversifier, in a minority',
        share: gold, sleeves: sleeves(amount, gold, [['Gold', 100]]) }
    ];

    var flags = [];

    if (a.horizon === 'under1' || a.horizon === '1_3') {
      flags.push({ level: 'stop', title: 'This money has a date on it',
        text: 'You said it is needed within three years. Indian equity has fallen more than a '
            + 'third inside a year and taken years to come back, so a date that close is not a '
            + 'risk to be sized — it is a reason the growth sleeve does not apply to this money '
            + 'at all. Deposits and short-duration debt exist for exactly this. The split below '
            + 'describes only the part of this sum that is genuinely long-term.' });
    } else if (a.horizon === '3_5') {
      flags.push({ level: 'warn', title: 'Three to five years is the awkward middle',
        text: 'Long enough that deposits alone cost you, short enough that one bad year lands on '
            + 'the date you need it. Whatever is needed at a fixed moment inside this window '
            + 'belongs in the stable sleeve regardless of the profile.' });
    }

    if (a.emergency === 'none' || a.emergency === 'under3') {
      flags.push({ level: 'warn', title: 'The cushion is not there yet',
        text: 'You said you hold under three months of expenses in cash. Until six months exist, '
            + 'the first call on this money is that cushion — its job is to stop a job loss or a '
            + 'medical event turning into a forced sale at the worst price. That is step 1 below, '
            + 'and it outranks everything on this card.' });
    }

    if (a.emi === '40_60' || a.emi === 'over60') {
      flags.push({ level: 'warn', title: 'Borrowings are taking a large share of income',
        text: 'Repaying a loan at 14% is a guaranteed 14% saved. Nothing in the sleeves below is '
            + 'guaranteed anything, and a falling market does not pause an EMI.' });
    }

    if (a.mode === 'lumpsum' && growth.rupees_mid > 0) {
      flags.push({ level: 'note', title: 'One lump sum into the growth sleeve',
        text: 'About ' + inr(growth.rupees_mid) + ' would go in on a single date. Staging it over '
            + 'several months spreads that date out; on average it gives up a little expected '
            + 'return to do so. Both are defensible — the question is which mistake you would '
            + 'rather live with.' });
    }

    return {
      band: band, amount: amount, groups: groups, flags: flags,
      band_note: BAND_NOTE[band] || '',
      split_pct: { growth: split.growth, stable: split.stable, gold: split.gold }
    };
  }

  /* ── Presentation ──────────────────────────────────────────────────────── */

  var DRAFT_KEY = 'altaha-risk-answers-v1';      // shared with the planner
  var STATE_KEY = 'altaha-allocate-flow-v1';
  var API = (typeof root.API_BASE !== 'undefined' && root.API_BASE)
    ? root.API_BASE : (root.API_BASE || 'https://taha-project.onrender.com');

  /* The adviser and the question, side by side. The heading stays a real
     heading in the real order — the figure is seated beside it, never in
     place of it, so nothing that carries meaning lives in a drawing. */
  function asking(pose, block) {
    var who = root.AltahaAdviser ? root.AltahaAdviser.figure(pose) : '';
    return '<div class="acf-ask" data-stagger>' + who + block + '</div>';
  }

  /* The picture for a question, at a given option. Falls back to the adviser
     taking notes when this question has no art of its own, so the slot is
     never empty and never jumps in size. */
  function sceneFor(question, value) {
    var art = root.AltahaQuestionArt;
    var drawn = (art && question) ? art.scene(question.id, value) : null;
    if (drawn) return drawn;
    return root.AltahaAdviser ? root.AltahaAdviser.figure('listen') : '';
  }

  function $(id) { return doc.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function still() {
    try {
      return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }

  /* What the slider opens on. It has to be in `state`, not just drawn: a
     reader who agrees with the default and presses Continue without touching
     the handle was otherwise carried all the way to the allocation with no
     amount at all — "allocating ₹0" in the header and a dead end at the end.
     `chosen` keeps the distinction between this default and a figure somebody
     actually picked, so an existing profile cannot skip them past a number
     they never saw. */
  var DEFAULT_AMOUNT = 500000;

  var state = {
    stage: 'amount', amount: DEFAULT_AMOUNT, chosen: false, index: 0,
    questions: [], bands: [], answers: {}, profile: null, recorded: null,
    busy: false, error: ''
  };

  function readDraft() {
    try { return JSON.parse(root.localStorage.getItem(DRAFT_KEY) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function writeDraft() {
    try { root.localStorage.setItem(DRAFT_KEY, JSON.stringify(state.answers)); } catch (e) {}
  }
  function readState() {
    try { return JSON.parse(root.localStorage.getItem(STATE_KEY) || '{}') || {}; }
    catch (e) { return {}; }
  }
  function saveState() {
    try {
      root.localStorage.setItem(STATE_KEY, JSON.stringify({
        amount: state.chosen ? state.amount : null, stage: state.stage
      }));
    } catch (e) {}
  }

  /* Count a number up rather than swapping it. The movement is what makes a
     slider feel like it is moving money instead of setting a form field.

     Every tween runs on a named channel and a newer one on the same channel
     cancels the older. Without that, clicking ₹1 Cr and then immediately
     dragging the slider leaves a four-hundred-millisecond animation writing
     ₹1 Cr over the figure the handle is now on — the display disagreeing with
     the control, which is the one thing a number on a slider must never do. */
  var tweens = {};

  function cancel(channel) {
    tweens[channel] = (tweens[channel] || 0) + 1;
    return tweens[channel];
  }

  function tween(from, to, ms, step, channel) {
    var key = channel || 'default';
    var mine = cancel(key);
    if (still() || !root.requestAnimationFrame) { step(to); return; }
    var start = null;
    function frame(now) {
      if (tweens[key] !== mine) return;          // a newer value took over
      if (start === null) start = now;
      var t = Math.min(1, (now - start) / ms);
      var eased = 1 - Math.pow(1 - t, 3);
      step(from + (to - from) * eased);
      if (t < 1) root.requestAnimationFrame(frame);
    }
    root.requestAnimationFrame(frame);
  }

  function animate(node, frames, options) {
    if (!node || still() || !node.animate) return null;
    try { return node.animate(frames, options); } catch (e) { return null; }
  }

  /* Height is animated explicitly because the stages are different sizes and
     a card that jumps by 300px between them reads as a page reload. */
  function swap(html, direction) {
    var card = $('acf-card');
    var body = $('acf-body');
    if (!body) return;
    var from = body.offsetHeight;
    body.innerHTML = html;
    var to = body.offsetHeight;
    if (still()) { bind(); return; }
    animate(card, [{ height: from + 'px' }, { height: to + 'px' }],
            { duration: 320, easing: 'cubic-bezier(.22,1,.36,1)' });
    var dx = direction === 'back' ? -28 : 28;
    animate(body, [{ opacity: 0, transform: 'translateX(' + dx + 'px)' },
                   { opacity: 1, transform: 'none' }],
            { duration: 300, delay: 40, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
    Array.prototype.slice.call(body.querySelectorAll('[data-stagger]')).forEach(function (n, i) {
      animate(n, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }],
              { duration: 340, delay: 90 + i * 55, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
    });
    bind();
  }

  /* ── Stage 1 · the amount ──────────────────────────────────────────────── */

  var CHIPS = [50000, 500000, 2500000, 10000000, 50000000];

  function stageAmount() {
    var amount = state.amount || DEFAULT_AMOUNT;
    var pos = rupeesToSlider(amount);
    var marks = [1, 100000, 1000000, 10000000, 200000000];
    return '' +
      asking('ask',
        '<div class="acf-head acf-bubble">' +
          '<span class="acf-step">Step 1 of 3</span>' +
          '<h3>How much are you putting to work?</h3>' +
          '<p>Everything after this is a share of this number. It is the sum you are allocating — ' +
          'not your net worth, and not money you have already committed elsewhere.</p>' +
        '</div>') +
      '<div class="acf-amount" data-stagger>' +
        '<output class="acf-big" id="acf_big" for="acf_slider">' +
          '<i class="acf-sym" id="acf_sym">₹</i><span id="acf_num">' + esc(plain(amount)) + '</span>' +
        '</output>' +
        '<span class="acf-exact" id="acf_exact">' + esc(inr(amount)) + '</span>' +
      '</div>' +
      '<div class="acf-slider" data-stagger>' +
        '<div class="acf-track"><i id="acf_fill" style="width:' + (pos / TRACK * 100) + '%"></i></div>' +
        '<input type="range" id="acf_slider" min="0" max="' + TRACK + '" step="1" value="' + pos + '" ' +
          'aria-label="Amount to allocate" aria-valuetext="' + esc(inr(amount)) + '">' +
        '<div class="acf-marks">' + marks.map(function (m) {
          return '<span style="left:' + (rupeesToSlider(m) / TRACK * 100) + '%">' + esc(words(m)) + '</span>';
        }).join('') + '</div>' +
        '<p class="acf-scale">The track is logarithmic, so every ten-fold step gets the same room. ' +
        '₹1 to ₹20 crore.</p>' +
      '</div>' +
      '<div class="acf-chips" data-stagger>' +
        CHIPS.map(function (c) {
          return '<button type="button" class="acf-chip" data-amount="' + c + '">' + esc(words(c)) + '</button>';
        }).join('') +
        '<label class="acf-type"><span>Exact</span>' +
          '<input type="number" id="acf_type" min="1" max="' + MAX_RUPEES + '" step="1" ' +
          'value="' + amount + '" aria-label="Exact amount in rupees"></label>' +
      '</div>' +
      '<div class="acf-act" data-stagger>' +
        '<button type="button" class="acf-go" id="acf_next">Continue to risk profile</button>' +
        '<span class="acf-hint">Nothing is sent anywhere. Ten questions, about two minutes.</span>' +
      '</div>';
  }

  function setAmount(value, animateNumber, spend) {
    var v = snap(value);
    var was = state.amount;
    state.amount = v;
    state.chosen = true;
    if (spend !== false && was != null && v !== was) coins(v, was);
    var big = $('acf_big'), exact = $('acf_exact'), fill = $('acf_fill'),
        slider = $('acf_slider'), typed = $('acf_type');
    if (fill) fill.style.width = (rupeesToSlider(v) / TRACK * 100) + '%';
    if (slider) {
      if (Number(slider.value) !== rupeesToSlider(v)) slider.value = rupeesToSlider(v);
      slider.setAttribute('aria-valuetext', inr(v));
    }
    if (typed && doc.activeElement !== typed) typed.value = v;
    if (exact) exact.textContent = inr(v);
    var num = $('acf_num');
    if (!big || !num) return;
    if (animateNumber) {
      var from = Number(String(big.dataset.value || v));
      tween(from, v, 420, function (n) { num.textContent = plain(n); }, 'amount');
      animate(big, [{ transform: 'scale(1.07)' }, { transform: 'scale(1)' }],
              { duration: 300, easing: 'cubic-bezier(.34,1.56,.64,1)' });
    } else {
      cancel('amount');                          // a drag outranks a running count
      num.textContent = plain(v);
    }
    // The symbol takes the hit on every change, counted or not: it is the one
    // glyph on the card that means money, so it is the one that reacts.
    var sym = $('acf_sym');
    animate(sym, [{ transform: 'scale(1) rotate(0deg)' },
                  { transform: 'scale(1.3) rotate(-9deg)', offset: .4 },
                  { transform: 'scale(1) rotate(0deg)' }],
            { duration: 420, easing: 'cubic-bezier(.34,1.56,.64,1)' });
    big.dataset.value = v;
    saveState();
  }

  /* ── Coins ────────────────────────────────────────────────────────────────
     Off the slider handle, scaled to the size of the sum, and throttled so a
     drag across the whole track sprays rather than floods. Up when the figure
     grows, down when it shrinks: the direction is the whole point, and a
     reader picks it up before they have read a digit. */
  var lastCoins = 0;

  function coins(value, previous, origin) {
    var fx = root.AltahaMoneyFx;
    var card = $('acf-card');
    if (!fx || !card || fx.still()) return;
    var now = Date.now();
    if (now - lastCoins < 110) return;
    lastCoins = now;
    var host = fx.layer(card);
    var from = origin || fx.thumb($('acf_slider'));
    if (!from || (!from.x && !from.y)) from = fx.centre($('acf_big'));
    if (value >= previous) {
      // The spray follows the magnitude of the sum, not the size of the drag:
      // sliding into a crore should feel like more money, because it is.
      fx.fountain(host, from, { count: Math.round(fx.countFor(value) * 0.55) + 1, rise: 130 });
      fx.sheen($('acf_big'));
    } else {
      fx.drain(host, from, { count: 3 });
    }
  }

  /* ── Stage 2 · the questions ───────────────────────────────────────────── */

  /* The scored questions, then the two context ones the regulations want on
     file. `amount` is not asked: the slider answered it. */
  function asked() {
    var scored = state.questions.filter(function (q) { return q.weight > 0; });
    var context = state.questions.filter(function (q) {
      return !q.weight && (q.id === 'purpose' || q.id === 'mode');
    });
    return scored.concat(context);
  }

  function stageQuestions() {
    var list = asked();
    if (!list.length) {
      return '<div class="acf-head" data-stagger><h3>The questionnaire could not be loaded</h3>' +
             '<p>' + esc(state.error || 'The question list comes from the server so that an answer ' +
             'recorded today still means the same thing years from now.') + '</p></div>' +
             '<div class="acf-act" data-stagger><button type="button" class="acf-go" id="acf_retry">Try again</button>' +
             '<button type="button" class="acf-back" id="acf_back">Back to the amount</button></div>';
    }
    var i = Math.max(0, Math.min(list.length - 1, state.index));
    var q = list[i];
    var chosen = state.answers[q.id];
    return '' +
      '<div class="acf-progress" data-stagger>' +
        '<div class="acf-bar"><i style="width:' + ((i) / list.length * 100) + '%" id="acf_bar"></i></div>' +
        '<span class="acf-step">Step 2 of 3 · question ' + (i + 1) + ' of ' + list.length +
        ' · allocating ' + esc(words(state.amount)) + '</span>' +
      '</div>' +
      '<div class="acf-ask" data-stagger>' +
        '<div class="acf-art" id="acf_art">' + sceneFor(q, chosen) + '</div>' +
        '<div class="acf-q acf-bubble">' +
          '<h3>' + esc(q.label) + '</h3>' +
          '<p class="acf-why">' + esc(q.why || '') + '</p>' +
        '</div>' +
      '</div>' +
      '<div class="acf-opts" data-stagger>' +
        (q.options || []).map(function (o) {
          return '<button type="button" class="acf-opt' + (chosen === o.value ? ' is-on' : '') + '" ' +
            'data-answer="' + esc(o.value) + '" aria-pressed="' + (chosen === o.value) + '">' +
            '<span>' + esc(o.label) + '</span></button>';
        }).join('') +
      '</div>' +
      '<div class="acf-act" data-stagger>' +
        (i > 0 ? '<button type="button" class="acf-back" id="acf_prev">Back</button>'
               : '<button type="button" class="acf-back" id="acf_back">Change the amount</button>') +
        (chosen !== undefined
          ? '<button type="button" class="acf-go" id="acf_forward">' +
            (i === list.length - 1 ? 'See the asset classes' : 'Next') + '</button>'
          : '<span class="acf-hint">Pick the closest one. There is no right answer, and you can change it.</span>') +
      '</div>';
  }

  /* Pointing at an option previews it. Re-rendering only when the value
     actually changes keeps the entrance animation from replaying on every
     pixel of mouse movement across a button. */
  function paintArt(value) {
    var slot = $('acf_art');
    if (!slot) return;
    var list = asked();
    var q = list[state.index];
    if (!q) return;
    var key = q.id + '|' + String(value);
    if (slot.dataset.art === key) return;
    slot.dataset.art = key;
    slot.innerHTML = sceneFor(q, value);
  }

  function selectedValue() {
    var list = asked();
    var q = list[state.index];
    return q ? state.answers[q.id] : undefined;
  }

  function answer(value, node) {
    var list = asked();
    var q = list[state.index];
    if (!q) return;
    state.answers[q.id] = value;
    writeDraft();
    if (node) {
      node.classList.add('is-on');
      node.setAttribute('aria-pressed', 'true');
      animate(node, [{ transform: 'scale(1)' }, { transform: 'scale(.97)' }, { transform: 'scale(1)' }],
              { duration: 200, easing: 'ease-out' });
    }
    // The picture changes to the answer that was just given, and the card
    // holds there for a beat before advancing. Without the pause a reader on
    // a phone — who never hovers — would never see the art respond at all.
    paintArt(value);
    var art = root.AltahaQuestionArt;
    var hold = still() ? 0 : (art && art.has(q.id) ? 620 : 230);
    if (state.index < list.length - 1) {
      root.setTimeout(function () { state.index++; paint('next'); }, hold);
    } else {
      root.setTimeout(function () { paint('next'); }, hold ? 340 : 0);
    }
  }

  /* ── Stage 3 · the asset classes ───────────────────────────────────────── */

  function stageResult() {
    if (state.busy) {
      return '<div class="acf-head" data-stagger><h3>Working out your profile…</h3>' +
             '<p>Capacity and temperament, and the lower of the two.</p></div>';
    }
    var p = state.profile;
    if (!p || !p.band) {
      return '<div class="acf-head" data-stagger><h3>Not enough answers yet</h3>' +
             '<p>' + esc(state.error || 'The profile needs both halves of the questionnaire — what your ' +
             'circumstances can absorb and what your temperament can sit through.') + '</p></div>' +
             '<div class="acf-act" data-stagger><button type="button" class="acf-go" id="acf_again">Back to the questions</button></div>';
    }
    var result = plan(p.band, state.amount, state.answers);
    if (result) state.lastShares = result.groups.map(function (g) { return g.share.mid; });
    if (!result) {
      return '<div class="acf-head" data-stagger><h3>' + esc(p.band) + '</h3>' +
             '<p>An allocation needs an amount above zero.</p></div>' +
             '<div class="acf-act" data-stagger><button type="button" class="acf-back" id="acf_back">Set the amount</button></div>';
    }

    var html = asking('present',
      '<div class="acf-head acf-bubble">' +
        '<span class="acf-step">Step 3 of 3 · ' + esc(inr(state.amount)) + ' allocated</span>' +
        '<h3>' + esc(p.band) + '</h3>' +
        '<p>' + esc(result.band_note) + '</p>' +
        '<p class="acf-why">' + esc(p.binding_note || '') +
          (state.recorded === false
            ? ' This one was worked out in this browser and not recorded. Sign in to keep it.'
            : state.recorded === true ? ' Recorded to your account.' : '') +
        '</p>' +
      '</div>') +
      '<div class="acf-axes" data-stagger>' +
        axis('Capacity', p.capacity, 'What your circumstances can absorb') +
        axis('Temperament', p.tolerance, 'What you could sit through') +
        axis('Profile', p.score, 'The lower of the two — always') +
      '</div>';

    html += donut(result);

    html += result.flags.map(function (f) {
      return '<div class="acf-flag is-' + f.level + '" data-stagger>' +
        '<b>' + esc(f.title) + '</b><p>' + esc(f.text) + '</p></div>';
    }).join('');

    html += '<div class="acf-groups">' + result.groups.map(function (g, i) {
      return '<div class="acf-group" data-stagger>' +
        '<div class="acf-group-head">' +
          '<div><b><i class="acf-swatch is-' + g.key + '" aria-hidden="true"></i>' + esc(g.label) +
            '</b><small>' + esc(g.kind) + '</small></div>' +
          '<div class="acf-group-num">' +
            '<span class="acf-money" data-count="' + g.share.rupees_mid + '">' + esc(inr(0)) + '</span>' +
            '<small>' + g.share.low + '–' + g.share.high + '% · ' +
              esc(inr(g.share.rupees_low)) + ' to ' + esc(inr(g.share.rupees_high)) + '</small>' +
          '</div>' +
        '</div>' +
        '<div class="acf-bar wide"><i data-grow="' + g.share.mid + '" style="width:0"></i></div>' +
        '<ul class="acf-sleeves">' + g.sleeves.map(function (s) {
          return '<li><div class="acf-sleeve-t"><span>' + esc(s.label) + '</span>' +
            '<b>' + esc(inr(s.rupees)) + '</b></div>' +
            '<small>' + s.pct_of_total + '% of the total · ' + esc(s.why) + '</small></li>';
        }).join('') + '</ul>' +
      '</div>';
    }).join('') + '</div>';

    html += '<p class="acf-disc" data-stagger>The three ranges are independent guardrails, so ' +
      'their midpoints do not add to 100% on their own; the rupee figures are those midpoints ' +
      'scaled to your ' + esc(inr(state.amount)) + ', and each one still sits inside its own ' +
      'published range. Categories, never products. Which specific fund, scheme ' +
      'or security sits inside any of these is between you and a registered adviser — it is not this ' +
      'site\'s to say. The ranges are conventional guardrails for a profile, not a recommendation, ' +
      'and the midpoint is shown because a range needs a number to be legible, not because it is ' +
      'the right one.</p>';

    html += '<div class="acf-act" data-stagger>' +
      '<button type="button" class="acf-back" id="acf_back">Change the amount</button>' +
      '<button type="button" class="acf-back" id="acf_again">Re-answer the questions</button>' +
      '</div>';
    return html;
  }

  /* The whole sum as one ring, divided. Three cards in a column state the
     split; a ring shows it, and it is the shape a reader remembers after the
     numbers have gone. Drawn with stroke-dasharray so each arc can sweep out
     from twelve o'clock in turn, in the order the money is committed. */
  var RING_R = 54, RING_C = 2 * Math.PI * 54;

  function donut(result) {
    var offset = 0;
    var arcs = result.groups.map(function (g) {
      var fraction = Math.max(0, (g.share.mid || 0) / 100);
      var arc = '<circle class="acf-arc is-' + g.key + '" cx="70" cy="70" r="' + RING_R + '" ' +
        'stroke-dasharray="0 ' + RING_C.toFixed(1) + '" ' +
        'stroke-dashoffset="' + (-offset * RING_C).toFixed(1) + '" ' +
        'data-arc="' + (fraction * RING_C).toFixed(1) + ' ' + RING_C.toFixed(1) + '"></circle>';
      offset += fraction;
      return arc;
    }).join('');

    var label = result.groups.map(function (g) {
      return g.label + ' ' + g.share.mid + '%';
    }).join(', ');

    return '<div class="acf-ring" data-stagger>' +
      '<svg viewBox="0 0 140 140" role="img" aria-label="' + esc(label) + '">' +
        '<circle class="acf-arc-bg" cx="70" cy="70" r="' + RING_R + '"></circle>' + arcs +
      '</svg>' +
      '<div class="acf-ring-mid">' +
        '<span class="acf-total-line">' +
          '<i class="acf-sym">₹</i>' +
          '<b class="acf-total" data-count="' + result.amount + '" data-format="words">0</b>' +
        '</span>' +
        '<small>across three sleeves</small>' +
      '</div>' +
    '</div>';
  }

  function axis(label, value, why) {
    return '<div class="acf-axis"><span class="k">' + esc(label) + '</span>' +
      '<span class="v">' + (value == null ? '—' : esc(String(value))) + '</span>' +
      '<small>' + esc(why) + '</small></div>';
  }

  /* The bars grow and the rupee figures count up once, after the stage has
     landed. Re-running it on every repaint would be a fidget, not a signal. */
  function playResult() {
    var fx = root.AltahaMoneyFx;
    var card = $('acf-card');

    // The ring sweeps out one arc at a time, in the order the money is
    // committed, rather than appearing already divided.
    Array.prototype.slice.call(doc.querySelectorAll('#acf-body .acf-arc')).forEach(function (n, i) {
      var to = n.dataset.arc;
      if (still()) { n.setAttribute('stroke-dasharray', to); return; }
      root.setTimeout(function () {
        n.style.transition = 'stroke-dasharray 680ms cubic-bezier(.22,1,.36,1)';
        n.setAttribute('stroke-dasharray', to);
      }, 120 + i * 220);
    });

    // And then it is handed out: coins fly from the middle of the ring into
    // each sleeve, in the proportion that sleeve receives. The split stops
    // being a table and becomes something that happens.
    if (fx && card && !fx.still()) {
      var ring = doc.querySelector('#acf-body .acf-ring');
      var groups = Array.prototype.slice.call(doc.querySelectorAll('#acf-body .acf-group'));
      if (ring && groups.length) {
        root.setTimeout(function () {
          if (!doc.querySelector('#acf-body .acf-ring')) return;   // stage moved on
          fx.transfer(fx.layer(card), fx.centre(ring), groups.map(function (g, i) {
            var point = fx.centre(g.querySelector('.acf-group-head') || g);
            return { x: point.x, y: point.y,
                     share: Number((state.lastShares || [])[i]) || 1 };
          }), { count: 21 });
        }, 620);
      }
    }

    Array.prototype.slice.call(doc.querySelectorAll('#acf-body [data-grow]')).forEach(function (n, i) {
      var to = Number(n.dataset.grow) || 0;
      if (still()) { n.style.width = to + '%'; return; }
      n.style.width = '0%';
      root.setTimeout(function () {
        n.style.transition = 'width 760ms cubic-bezier(.22,1,.36,1)';
        n.style.width = to + '%';
      }, 140 + i * 110);
    });
    Array.prototype.slice.call(doc.querySelectorAll('#acf-body [data-count]')).forEach(function (n, i) {
      var to = Number(n.dataset.count) || 0;
      // The ring's centre is a headline, not a ledger line: it reads ₹5 Cr
      // while the sleeve figures below it carry every digit.
      var show = n.dataset.format === 'words' ? plain : inr;
      // `data-settled` is the signal that the figure on screen is the final
      // one. A number mid-count is not a number anybody should read off, and
      // the browser test would otherwise be racing the animation.
      n.removeAttribute('data-settled');
      if (still()) { n.textContent = show(to); n.setAttribute('data-settled', '1'); return; }
      root.setTimeout(function () {
        tween(0, to, 900, function (v) {
          n.textContent = show(v);
          if (v === to) n.setAttribute('data-settled', '1');
        }, 'count' + i);
      }, 140 + i * 110);
    });
  }

  /* ── Profile resolution ────────────────────────────────────────────────── */

  function post(path, body) {
    var auth = root.AltahaAuth;
    if (auth && auth.authed && auth.authed()) {
      return auth.fetch(path, { method: 'POST', body: body });
    }
    return root.fetch(API + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body
    });
  }

  function resolveProfile() {
    var math = root.AltahaRiskMath;
    var local = math ? math.assess(state.answers, state.questions, state.bands) : null;
    var auth = root.AltahaAuth;

    // Signed out there is nobody to record it against, so it is computed here
    // and said plainly to be unrecorded rather than quietly not saved.
    if (!auth || !auth.authed || !auth.authed()) {
      state.profile = local;
      state.recorded = local ? false : null;
      if (!local) state.error = 'Some scored questions are still unanswered.';
      publish();
      return Promise.resolve();
    }

    state.busy = true;
    // The amount the slider set is part of the record: the regulations want
    // the sum on file, and the server's own questionnaire asks for it.
    var answers = {};
    Object.keys(state.answers).forEach(function (k) { answers[k] = state.answers[k]; });
    if (state.amount) answers.amount = state.amount;

    return post('/me/risk-profile', JSON.stringify({ answers: answers }))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        state.busy = false;
        if (!res.ok || !res.d || !res.d.profile) throw new Error((res.d && res.d.detail) || 'save failed');
        state.profile = res.d.profile;
        state.recorded = true;
        publish();
      })
      .catch(function () {
        state.busy = false;
        state.profile = local;
        state.recorded = local ? false : null;
        state.error = local ? '' : 'Your account could not be reached and some answers are missing.';
        publish();
      });
  }

  /* Allocate's step list keys its split off this, so it is published the same
     way the planner's questionnaire publishes its own result. */
  function publish() {
    if (!state.profile) return;
    root.AltahaRiskProfile = state.profile;
    try {
      root.dispatchEvent(new CustomEvent('altaha:risk', { detail: state.profile }));
    } catch (e) {}
  }

  /* ── Wiring ────────────────────────────────────────────────────────────── */

  function paint(direction) {
    var html = state.stage === 'amount' ? stageAmount()
             : state.stage === 'questions' ? stageQuestions()
             : stageResult();
    swap(html, direction || 'next');
    if (state.stage === 'result' && !state.busy) playResult();
    saveState();
  }

  function bind() {
    var slider = $('acf_slider');
    if (slider) {
      slider.addEventListener('input', function () { setAmount(sliderToRupees(slider.value), false); });
      slider.addEventListener('change', function () {
        // Letting go is the moment somebody has chosen a number, so it gets a
        // spray sized to that number rather than to the last nudge.
        var value = sliderToRupees(slider.value);
        setAmount(value, false, false);
        var fx = root.AltahaMoneyFx, card = $('acf-card');
        if (fx && card) {
          lastCoins = 0;
          fx.fountain(fx.layer(card), fx.thumb(slider), { count: fx.countFor(value), rise: 150 });
          fx.sheen($('acf_big'));
        }
      });
    }
    var typed = $('acf_type');
    if (typed) {
      typed.addEventListener('input', function () {
        var v = Number(typed.value);
        if (isFinite(v) && v > 0) setAmount(v, false);
      });
    }
    Array.prototype.slice.call(doc.querySelectorAll('#acf-body .acf-chip')).forEach(function (b) {
      b.addEventListener('click', function () {
        var value = Number(b.dataset.amount);
        setAmount(value, true, false);
        var fx = root.AltahaMoneyFx, card = $('acf-card');
        if (fx && card) {
          lastCoins = 0;                         // a pick is never throttled away
          fx.fountain(fx.layer(card), fx.centre(b),
                      { count: fx.countFor(value), rise: 150, spread: 240 });
          fx.sheen($('acf_big'));
        }
      });
    });
    Array.prototype.slice.call(doc.querySelectorAll('#acf-body .acf-opt')).forEach(function (b) {
      b.addEventListener('click', function () { answer(b.dataset.answer, b); });
      // Pointing at an answer shows what it looks like. Focus does the same,
      // so arrowing through the options with a keyboard previews them too.
      b.addEventListener('mouseenter', function () { paintArt(b.dataset.answer); });
      b.addEventListener('focus', function () { paintArt(b.dataset.answer); });
      b.addEventListener('mouseleave', function () { paintArt(selectedValue()); });
      b.addEventListener('blur', function () { paintArt(selectedValue()); });
    });

    var next = $('acf_next');
    if (next) next.addEventListener('click', function () {
      // The money goes in. One throw off the button as the stage turns, so
      // the step from a figure to a questionnaire is something committed
      // rather than a page swap.
      var fx = root.AltahaMoneyFx, card = $('acf-card');
      if (fx && card && !fx.still()) {
        lastCoins = 0;
        fx.fountain(fx.layer(card), fx.centre(next),
                    { count: fx.countFor(state.amount), rise: 210, spread: 300 });
      }
      go('questions');
    });
    var forward = $('acf_forward');
    if (forward) forward.addEventListener('click', function () {
      var list = asked();
      if (state.index < list.length - 1) { state.index++; paint('next'); }
      else { go('result'); }
    });
    var prev = $('acf_prev');
    if (prev) prev.addEventListener('click', function () { state.index--; paint('back'); });
    var back = $('acf_back');
    if (back) back.addEventListener('click', function () { state.stage = 'amount'; paint('back'); });
    var again = $('acf_again');
    if (again) again.addEventListener('click', function () {
      state.index = 0; state.stage = 'questions'; paint('back');
    });
    var retry = $('acf_retry');
    if (retry) retry.addEventListener('click', function () { load(true); });
  }

  function go(stage) {
    if (stage === 'questions') {
      state.stage = 'questions';
      var list = asked();
      // Resume at the first unanswered question rather than making somebody
      // click through answers they already gave in the planner.
      var first = 0;
      for (var i = 0; i < list.length; i++) {
        if (state.answers[list[i].id] === undefined) { first = i; break; }
        first = i;
      }
      state.index = first;
      paint('next');
      return;
    }
    if (stage === 'result') {
      state.stage = 'result';
      state.error = '';
      paint('next');
      resolveProfile().then(function () { paint('next'); });
      return;
    }
    state.stage = stage;
    paint('next');
  }

  function shell() {
    var host = $('alc-flow');
    if (!host) return false;
    if ($('acf-card')) return true;
    host.innerHTML = '<section class="acf-card" id="acf-card" aria-live="polite">' +
      '<div class="acf-body" id="acf-body"></div></section>';
    var card = $('acf-card');
    if (root.AltahaMoneyFx) root.AltahaMoneyFx.layer(card);
    animate(card, [{ opacity: 0, transform: 'translateY(16px) scale(.985)' },
                   { opacity: 1, transform: 'none' }],
            { duration: 460, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
    return true;
  }

  function load(force) {
    if (state.questions.length && !force) { paint('next'); return; }
    state.error = '';
    root.fetch(API + '/planner/questions')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.questions || !d.questions.length) throw new Error('empty');
        state.questions = d.questions;
        state.bands = d.bands || [];
        paint('next');
      })
      .catch(function () {
        state.error = 'The question list could not be loaded. It is served rather than held in ' +
          'this page so that an answer recorded today still resolves to the same question years ' +
          'from now — which means this needs the network.';
        paint('next');
      });
  }

  var painted = false;

  function open(force) {
    if (!shell()) return;
    if (painted && !force) return;
    painted = true;

    var saved = readState();
    state.answers = readDraft();
    var picked = saved.amount && saved.amount > 0 ? snap(saved.amount) : null;
    state.amount = picked || DEFAULT_AMOUNT;
    state.chosen = !!picked;

    // Somebody who already has an amount and a profile is shown the answer,
    // not the first question again. An amount they never picked does not
    // count: it would skip them past the one number the rest is a share of.
    var known = root.AltahaRiskProfile;
    if (state.chosen && known && known.band && SPLIT[known.band]) {
      state.profile = known;
      state.recorded = known.recorded === false ? false : null;
      state.stage = 'result';
    } else {
      state.stage = state.chosen && saved.stage === 'questions' ? 'questions' : 'amount';
    }

    if (state.stage === 'amount') { paint('next'); load(false); }
    else load(false);
  }

  root.AltahaAllocateFlow = {
    open: open,
    reset: function () { painted = false; state.stage = 'amount'; open(true); },
    // Pure, and exported for the tests and for anything else that needs the
    // same arithmetic without the card around it.
    sliderToRupees: sliderToRupees, rupeesToSlider: rupeesToSlider,
    snap: snap, words: words, plan: plan, SPLIT: SPLIT,
    MIN_RUPEES: MIN_RUPEES, MAX_RUPEES: MAX_RUPEES
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.AltahaAllocateFlow;

  if (doc) {
    root.addEventListener('altaha-auth', function () { if (painted) resolveProfile(); });
    var boot = function () {
      var v = $('view-allocate');
      if (v && v.style.display !== 'none') open(false);
    };
    if (doc.readyState === 'loading') {
      doc.addEventListener('DOMContentLoaded', function () { root.setTimeout(boot, 300); });
    } else { root.setTimeout(boot, 300); }
    root.setInterval(boot, 2000);
  }
})(typeof window !== 'undefined' ? window : globalThis);
