/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Question art

   WHY EACH QUESTION GETS ITS OWN PICTURE
   The same figure beside twelve different questions tells a reader nothing
   about any of them. Each question here asks about one concrete thing — a
   date, a cushion, a fall, a loan — so each one draws that thing, and the
   drawing answers back: pick a different option and the picture changes to
   the option you are pointing at, before you have committed to it.

   That preview is the point. "How far could this fall before you could not
   leave it alone?" is abstract until a gauge drops to 40% and you can see how
   far down that is. "How old are you?" is a form field until the adviser
   across the desk goes grey.

   EVERY SCENE IS A PURE FUNCTION
   `scene(questionId, optionValue)` in, SVG string out. No DOM, no state, no
   clock. Which makes the whole library testable in node, and means the card
   can re-render a scene on hover without touching anything else.

   AND EVERY SCENE IS DECORATION
   `aria-hidden`, no text inside, nothing load-bearing. The question is a real
   heading and the options are real buttons; the art sits beside them. A
   reader with reduced motion gets the drawing and none of the movement, and a
   question this file has no art for falls back to the adviser taking notes.

   ONE FAMILY, ONE FRAME
   Every scene draws into the same 130×150 viewBox with the same ground line
   at y=136 and the same three inks — line, paper, one gold accent — so
   twelve different pictures still look like one set.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var GROUND = 136;

  function svg(kind, body, extra) {
    return '<div class="qa-scene is-' + kind + (extra ? ' ' + extra : '') + '" aria-hidden="true">' +
      '<svg viewBox="0 0 130 150" class="qa-svg" focusable="false">' + body + '</svg></div>';
  }

  function ground() {
    return '<path class="qa-ground" d="M6 ' + GROUND + 'h118"/>';
  }

  /* A coin, reused wherever money appears, so a rupee is the same object
     across the whole set rather than a different circle each time. */
  function coin(cx, cy, r, cls) {
    return '<g class="qa-coin ' + (cls || '') + '">' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '"/>' +
      '<text x="' + cx + '" y="' + (cy + r * 0.38) + '" font-size="' + (r * 1.25) + '">₹</text>' +
      '</g>';
  }

  function person(x, y, s, cls) {
    // The positioning transform lives on the outer group and the animation on
    // the inner one. A CSS `transform` on the same element would override the
    // `transform` attribute rather than compose with it, and the figure would
    // animate from the corner of the frame instead of from its own feet.
    return '<g transform="translate(' + x + ' ' + y + ') scale(' + s + ')">' +
      '<g class="qa-person ' + (cls || '') + '">' +
        '<circle class="qa-head" cx="0" cy="-16" r="8"/>' +
        '<path class="qa-body" d="M-11 0c0-7 5-12 11-12s11 5 11 12z"/>' +
      '</g></g>';
  }

  /* ── 1 · age ──────────────────────────────────────────────────────────────
     The adviser across the desk, at the reader's own stage of life. Drawn by
     adviser.js so it is the same person, not a lookalike. */
  var AGE_STEP = {
    under25: 'young', '25_34': 'young', '35_44': 'mid',
    '45_54': 'senior', '55_64': 'senior', '65plus': 'elder'
  };

  function age(value) {
    if (!root.AltahaAdviser) return null;
    return root.AltahaAdviser.figure('listen', { age: AGE_STEP[value] || 'young' });
  }

  /* ── 2 · horizon ──────────────────────────────────────────────────────────
     An hourglass. How much sand is still in the top bulb is how much time
     this money has, and the grains fall while the question is open. */
  var HORIZON_SAND = { under1: .08, '1_3': .3, '3_5': .5, '5_10': .75, '10plus': .96 };

  function horizon(value) {
    var share = HORIZON_SAND[value] == null ? .5 : HORIZON_SAND[value];
    var topH = 32 * share;
    var botH = 28 * (1 - share);
    return svg('horizon',
      ground() +
      // frame
      '<path class="qa-line" d="M34 30h62M34 132h62"/>' +
      '<path class="qa-glass" d="M40 30h50l-25 36 25 36v6H40v-6l25-36-25-36z"/>' +
      // sand, top bulb: a wedge that shrinks from the top down
      '<path class="qa-sand" d="M' + (65 - topH * 0.95) + ' ' + (64 - topH) +
        'h' + (topH * 1.9) + 'l-' + (topH * 0.95) + ' ' + topH + 'z"/>' +
      // sand, bottom bulb: a pile that grows
      '<path class="qa-sand" d="M' + (65 - botH * 1.05) + ' 124h' + (botH * 2.1) +
        'l-' + (botH * 1.05) + '-' + botH + 'z"/>' +
      // the grain in flight
      '<circle class="qa-grain" cx="65" cy="72" r="1.7"/>' +
      '<circle class="qa-grain qa-grain-2" cx="65" cy="72" r="1.5"/>',
      'is-' + (value || 'mid'));
  }

  /* ── 3 · surplus ──────────────────────────────────────────────────────────
     A month's income as a bar, and the part of it still there at the end of
     the month stacked on top as coins. */
  var SURPLUS = {
    none:     { share: 0,   coins: 0 },
    under10:  { share: .09, coins: 1 },
    '10_25':  { share: .18, coins: 2 },
    '25_40':  { share: .32, coins: 3 },
    over40:   { share: .5,  coins: 4 }
  };

  function surplus(value) {
    var step = SURPLUS[value] || SURPLUS['10_25'];
    var top = 52, span = 84;
    var left = span * step.share;                 // what is still there
    var stack = '';
    for (var i = 0; i < step.coins; i++) stack += coin(94, 124 - i * 16, 7.5, 'qa-rise qa-d' + i);
    return svg('surplus',
      ground() +
      // a month's income, with everything that has to go out shaded below
      '<rect class="qa-bar-spent" x="30" y="' + top + '" width="26" height="' + span + '" rx="3"/>' +
      (left > 0 ? '<rect class="qa-bar" x="30" y="' + top + '" width="26" height="' +
        left.toFixed(1) + '" rx="3"/>' : '') +
      '<path class="qa-line qa-arrow" d="M62 ' + (top + 30) + 'h18m-6-5 6 5-6 5"/>' +
      (step.coins ? stack
        : '<path class="qa-nil" d="M84 78l14 14m0-14-14 14"/>'));
  }

  /* ── 4 · emergency ────────────────────────────────────────────────────────
     An umbrella in the rain, and twelve pips for twelve months — the ones
     that are covered are filled. */
  var CUSHION = { none: 0, under3: 2, '3_6': 5, '6_12': 9, over12: 12 };

  function emergency(value) {
    var months = CUSHION[value] == null ? 5 : CUSHION[value];
    var pips = '';
    for (var i = 0; i < 12; i++) {
      pips += '<circle class="qa-pip' + (i < months ? ' is-on' : '') + '" cx="' +
        (20 + i * 8.2) + '" cy="128" r="2.6"/>';
    }
    var rain = '';
    for (var r = 0; r < 5; r++) {
      rain += '<path class="qa-rain qa-rain-' + r + '" d="M' + (24 + r * 21) + ' 20v9"/>';
    }
    return svg('emergency',
      rain +
      '<path class="qa-canopy" d="M22 78c0-24 19-42 43-42s43 18 43 42c-7-5-14-5-21 0-7-6-15-6-22 0-7-6-15-6-22 0-7-5-14-5-21 0z"/>' +
      '<path class="qa-line" d="M65 78v34q0 8-8 8t-8-7"/>' +
      pips);
  }

  /* ── 5 · emi ──────────────────────────────────────────────────────────────
     Income as a note, with the share a lender has a fixed claim on chained
     off the side of it. */
  var EMI_SHARE = { none: 0, under20: .2, '20_40': .4, '40_60': .6, over60: .8 };

  function emi(value) {
    var share = EMI_SHARE[value] == null ? .4 : EMI_SHARE[value];
    var w = 74 * share;
    return svg('emi',
      ground() +
      '<rect class="qa-note" x="28" y="60" width="74" height="42" rx="4"/>' +
      (w > 0 ? '<rect class="qa-note-claim" x="' + (102 - w) + '" y="60" width="' + w +
        '" height="42" rx="4"/>' : '') +
      coin(50, 81, 10) +
      (share > 0
        ? '<g class="qa-chain"><circle cx="96" cy="112" r="5"/><circle cx="96" cy="124" r="5"/>' +
          '<path class="qa-line" d="M96 102v5"/></g>'
        : '<path class="qa-tick" d="M88 114l6 7 12-14"/>'));
  }

  /* ── 6 · dependents ───────────────────────────────────────────────────────
     The reader, and the people whose outcome rides on this money with them. */
  var DEPENDENTS = { '0': 0, '1_2': 2, '3_4': 4, '5plus': 6 };
  var SEATS = [[62, GROUND], [84, GROUND], [106, GROUND],
               [62, GROUND - 34], [84, GROUND - 34], [106, GROUND - 34]];

  function dependents(value) {
    var n = DEPENDENTS[value] == null ? 2 : DEPENDENTS[value];
    var art = ground() + person(30, GROUND, 1.6, 'is-self');
    for (var i = 0; i < n && i < SEATS.length; i++) {
      art += person(SEATS[i][0], SEATS[i][1], 1, 'qa-arrive qa-d' + i);
    }
    if (!n) art += '<path class="qa-line qa-only" d="M62 ' + (GROUND - 14) + 'h46"/>';
    return svg('dependents', art);
  }

  /* ── 7 · drawdown_action ──────────────────────────────────────────────────
     ₹10 lakh becoming ₹7 lakh, and then what the reader does about it drawn
     as the next stroke of the same line. */
  var TAIL = {
    sell_all: 'M84 104h22',
    sell_some: 'M84 104l10 6 12-2',
    hold: 'M84 104l11 1 11-2',
    hold_plan: 'M84 104l11-6 11-9',
    buy_more: 'M84 104l11-14 11-22'
  };

  function drawdown(value) {
    var tail = TAIL[value] || TAIL.hold;
    return svg('drawdown',
      ground() +
      '<path class="qa-axis" d="M20 36v92h92"/>' +
      '<path class="qa-fall" d="M24 56l14 8 12-4 16 20 18 24"/>' +
      '<path class="qa-tail' + (value === 'buy_more' ? ' is-up' : value === 'sell_all' ? ' is-flat' : '') +
        '" d="' + tail + '"/>' +
      (value === 'buy_more' ? coin(108, 62, 7.5, 'qa-rise') : '') +
      (value === 'sell_all' ? '<path class="qa-nil" d="M100 98l12 12m0-12-12 12"/>' : '') +
      coin(24, 50, 6) + coin(84, 110, 6, 'qa-dim'));
  }

  /* ── 8 · max_fall ─────────────────────────────────────────────────────────
     A depth gauge. The waterline drops to the fall the reader says they could
     leave alone, against the 38% Indian equity has actually done. */
  var DEPTH = { any: .04, '10': .1, '20': .2, '30': .3, '40plus': .45 };

  function maxFall(value) {
    var depth = DEPTH[value] == null ? .2 : DEPTH[value];
    var top = 40, span = 84;
    var line = top + span * depth;
    return svg('maxfall',
      '<rect class="qa-tank" x="38" y="' + top + '" width="54" height="' + span + '" rx="4"/>' +
      '<rect class="qa-water" x="38" y="' + top + '" width="54" height="' + (span * depth) + '" rx="4"/>' +
      '<path class="qa-waterline" d="M32 ' + line + 'h66"/>' +
      // the 38% mark: measured history, not an opinion
      '<path class="qa-mark" d="M34 ' + (top + span * .38) + 'h60"/>' +
      '<path class="qa-line qa-scale" d="M38 ' + top + 'h-6M38 ' + (top + span) + 'h-6"/>' +
      '<path class="qa-down" d="M65 ' + (line + 8) + 'v14m-5-5 5 5 5-5"/>' +
      ground());
  }

  /* ── 9 · priority ─────────────────────────────────────────────────────────
     Growth and protection on the two ends of a beam, because they are a
     trade and not a menu. The beam tips to whichever the reader gives up
     less of. */
  var TILT = { protect: -11, mostly_protect: -6, balanced: 0, mostly_grow: 6, grow: 11 };

  function priority(value) {
    var tilt = TILT[value] == null ? 0 : TILT[value];
    return svg('priority',
      ground() +
      '<path class="qa-line" d="M65 132V74"/>' +
      '<path class="qa-post" d="M52 132h26"/>' +
      '<g class="qa-beam" style="transform:rotate(' + tilt + 'deg)">' +
        '<path class="qa-line" d="M28 74h74"/>' +
        '<path class="qa-line" d="M32 74v10M98 74v10"/>' +
        // protection: a shield
        '<path class="qa-shield" d="M32 84c-8 2-11 5-11 5 0 12 5 18 11 21 6-3 11-9 11-21 0 0-3-3-11-5z"/>' +
        // growth: a sprout
        '<path class="qa-sprout" d="M98 110V88"/>' +
        '<path class="qa-leaf" d="M98 92c-9 0-13-5-13-11 7 0 13 4 13 11z"/>' +
        '<path class="qa-leaf" d="M98 98c9 0 13-5 13-11-7 0-13 4-13 11z"/>' +
      '</g>');
  }

  /* ── 10 · experience ──────────────────────────────────────────────────────
     A market's own line, as far back as the reader has been standing in it.
     Somebody who has held through a real fall has seen more of this curve. */
  var SEEN = { none: .12, under3: .35, '3_10': .7, over10: 1 };

  function experience(value) {
    var seen = SEEN[value] == null ? .5 : SEEN[value];
    var full = 'M18 118c8-4 14 6 22-2s12-26 20-24 10 34 18 26 12-40 20-44';
    return svg('experience',
      ground() +
      '<path class="qa-axis" d="M14 128h104"/>' +
      '<path class="qa-cycle-ghost" d="' + full + '"/>' +
      '<path class="qa-cycle" d="' + full + '" style="stroke-dasharray:' +
        (170 * seen).toFixed(0) + ' 400"/>' +
      '<circle class="qa-now" cx="' + (18 + 100 * seen) + '" cy="' +
        (118 - 70 * seen * seen) + '" r="4"/>');
  }

  /* ── 11 · purpose ─────────────────────────────────────────────────────────
     What the money is for, as the thing itself. */
  function purpose(value) {
    var art = {
      retirement:
        '<circle class="qa-sun" cx="88" cy="50" r="14"/>' +
        '<path class="qa-line" d="M30 110c14-6 26-6 40 0"/>' +
        '<path class="qa-trunk" d="M50 110V74"/>' +
        '<path class="qa-leaf" d="M50 74c-14-8-22-4-26 4 10 4 20 2 26-4z"/>' +
        '<path class="qa-leaf" d="M50 74c14-8 22-4 26 4-10 4-20 2-26-4z"/>' +
        '<path class="qa-leaf" d="M50 74c-4-14 1-21 10-24 3 10-1 20-10 24z"/>',
      house:
        '<path class="qa-roof" d="M65 44l38 30H27z"/>' +
        '<rect class="qa-wall" x="38" y="74" width="54" height="52" rx="2"/>' +
        '<rect class="qa-door" x="56" y="96" width="18" height="30" rx="2"/>' +
        '<circle class="qa-knob" cx="70" cy="112" r="1.8"/>',
      education:
        '<path class="qa-roof" d="M65 48l40 18-40 18-40-18z"/>' +
        '<path class="qa-wall" d="M45 78v22c0 6 9 10 20 10s20-4 20-10V78l-20 9z"/>' +
        '<path class="qa-line" d="M99 70v26"/>' +
        '<circle class="qa-knob" cx="99" cy="100" r="4"/>',
      wealth:
        coin(65, 118, 14) + coin(65, 96, 14) + coin(65, 74, 14, 'qa-rise'),
      income:
        '<rect class="qa-note" x="26" y="70" width="78" height="46" rx="4"/>' +
        coin(65, 93, 13) +
        '<path class="qa-line qa-arrow" d="M65 128v12m-5-5 5 5 5-5"/>',
      other:
        '<circle class="qa-tank" cx="65" cy="88" r="34"/>' +
        '<path class="qa-line" d="M56 78q0-10 9-10 9 0 9 9 0 7-9 9v6"/>' +
        '<circle class="qa-knob" cx="65" cy="106" r="2.6"/>'
    }[value] || null;
    return art ? svg('purpose', ground() + art, 'is-' + value) : null;
  }

  /* ── 12 · mode ────────────────────────────────────────────────────────────
     One sum on one date, or the same money arriving month after month. The
     same rupees, and very different risks. */
  function mode(value) {
    if (value === 'sip') {
      var drips = '';
      for (var i = 0; i < 5; i++) drips += coin(26 + i * 20, 112, 8, 'qa-drip qa-d' + i);
      return svg('mode', ground() + drips, 'is-sip');
    }
    if (value === 'both') {
      var mix = coin(40, 100, 17, 'qa-drop');
      for (var j = 0; j < 3; j++) mix += coin(76 + j * 19, 116, 7.5, 'qa-drip qa-d' + j);
      return svg('mode', ground() + mix, 'is-both');
    }
    return svg('mode', ground() + coin(65, 98, 26, 'qa-drop') +
      '<path class="qa-line qa-arrow" d="M65 44v16m-5-5 5 5 5-5"/>', 'is-lumpsum');
  }

  var SCENES = {
    age: age, horizon: horizon, surplus: surplus, emergency: emergency,
    emi: emi, dependents: dependents, drawdown_action: drawdown,
    max_fall: maxFall, priority: priority, experience: experience,
    purpose: purpose, mode: mode
  };

  /* The only entry point. Returns null when there is no art for a question,
     which is the caller's cue to fall back to the adviser. */
  function scene(id, value) {
    var draw = SCENES[id];
    if (!draw) return null;
    try { return draw(value) || null; } catch (e) { return null; }
  }

  var api = { scene: scene, has: function (id) { return !!SCENES[id]; },
              ids: Object.keys(SCENES), AGE_STEP: AGE_STEP };
  root.AltahaQuestionArt = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
