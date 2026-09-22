/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — The adviser

   WHY A PERSON
   "How much are you putting to work?" set in a heading is a form label. The
   same sentence coming out of somebody's mouth is a question, and a question
   gets answered. The figure exists to turn the card from a form into a
   conversation — one person, across a desk, asking.

   WHY DRAWN AND NOT PHOTOGRAPHED
   A stock photograph of a man in a tie would date the site, weigh several
   hundred kilobytes, need a licence, and pick a face for a reader who did not
   ask for one. This is a couple of kilobytes of inline SVG in the site's own
   palette: ink line, paper fill, one gold accent at the tie. It inherits the
   theme, so it draws in ink on cream and in cream on ink without a second
   asset, and it stays sharp at any size.

   WHY A DESK
   An earlier pass gave the figure free-floating arms. At 106 pixels a curved
   sleeve and a pale oval do not read as an arm; they read as a growth. Seated
   at a desk, the forearms have somewhere to be and the hands have something
   to rest on, which is both easier to draw honestly and what an adviser is
   actually doing. The desk line also gives the bust a base instead of leaving
   it floating in the card.

   IT IS DECORATION AND SAYS SO
   `aria-hidden`, always. The question is carried by the heading beside it,
   which is real text at the real heading level. A screen-reader user loses
   nothing; a reader with reduced motion gets the figure without the blink or
   the bob. Nothing on the card depends on any of it.

   THREE POSES, BECAUSE THE CARD HAS THREE STAGES
     ask      — hands resting, attention up. Stage one asks for a number.
     listen   — head tilted to a pad, pen moving. Stage two takes the answers.
     present  — one palm open towards the allocation. Stage three hands it over.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var POSES = { ask: 1, listen: 1, present: 1 };

  /* Head, shoulders and tie. Shared by every pose, so it is the same person
     sitting there the whole way through; only the hands change. */
  /* Ageing, four steps. Shown by hair — its colour and how far it has gone
     back — and by reading glasses, which is how age actually reads on a face
     at this size. Not by stooping, wrinkling or shrinking anybody: the point
     is a different person's circumstances, not a joke about being old. */
  var AGES = {
    young:  { tone: 'is-dark',  hair: 'full',   glasses: false },
    mid:    { tone: 'is-dark',  hair: 'full',   glasses: true },
    senior: { tone: 'is-salt',  hair: 'back',   glasses: true },
    elder:  { tone: 'is-white', hair: 'thin',   glasses: true }
  };

  var HAIR = {
    full: 'M43 52c0-19 10-30 22-30 13 0 22 10 23 29-3-9-9-15-17-17-7-2-12 2-18 4-4 2-8 6-10 14z',
    back: 'M45 48c1-16 10-26 20-26 12 0 20 9 22 25-4-8-11-12-19-12-8 0-15 3-19 9-2 2-3 3-4 4z',
    thin: 'M45 50c1-11 6-19 13-23-6 7-8 14-8 22zm40 0c-1-11-6-19-13-23 6 7 8 14 8 22z'
  };

  function glasses() {
    return '<g class="adv-specs">' +
      '<rect x="46" y="52" width="16" height="12" rx="5"/>' +
      '<rect x="68" y="52" width="16" height="12" rx="5"/>' +
      '<path d="M62 57h6M46 56l-5-2M84 56l5-2"/>' +
      '</g>';
  }

  function bust(tilt, age) {
    var turn = tilt ? ' transform="rotate(' + tilt + ' 65 96)"' : '';
    var years = AGES[age] || AGES.young;
    return '' +
      // jacket: sloped shoulders into a squared body, not a mound
      '<path class="adv-suit" d="M22 136c0-14 6-24 17-29l13-6 13 8 13-8 13 6c11 5 17 15 17 29z"/>' +
      // shirt behind the lapels
      '<path class="adv-shirt" d="M52 101l13 10 13-10 5 2-4 33H51l-4-33z"/>' +
      // lapels, meeting at the knot
      '<path class="adv-lapel" d="M52 101l13 10-5 25H48z"/>' +
      '<path class="adv-lapel" d="M78 101L65 111l5 25h12z"/>' +
      // collar points
      '<path class="adv-collar" d="M57 95l8 13-7 4-6-12z"/>' +
      '<path class="adv-collar" d="M73 95l-8 13 7 4 6-12z"/>' +
      // the tie: the one piece of colour on the whole figure
      '<path class="adv-gold" d="M65 108l-5 5 2 5h6l2-5z"/>' +
      '<path class="adv-gold" d="M62 120h6l2 12-5 6-5-6z"/>' +
      '<g class="adv-head"' + turn + '>' +
        // neck
        '<path class="adv-skin" d="M57 80h16v16l-8 9-8-9z"/>' +
        // ears, tucked close
        '<ellipse class="adv-skin" cx="42" cy="62" rx="3.4" ry="5.4"/>' +
        '<ellipse class="adv-skin" cx="88" cy="62" rx="3.4" ry="5.4"/>' +
        // head
        '<ellipse class="adv-skin" cx="65" cy="58" rx="23" ry="27"/>' +
        // hair: colour and hairline carry the age
        '<path class="adv-hair ' + years.tone + '" d="' + HAIR[years.hair] + '"/>' +
        // brows
        '<path class="adv-line" d="M51 49q6-3 11-1"/>' +
        '<path class="adv-line" d="M79 49q-6-3-11-1"/>' +
        '<g class="adv-eyes">' +
          '<ellipse class="adv-eye" cx="56" cy="58" rx="2.1" ry="2.8"/>' +
          '<ellipse class="adv-eye" cx="74" cy="58" rx="2.1" ry="2.8"/>' +
        '</g>' +
        // nose and mouth
        '<path class="adv-line" d="M65 59v7q0 2-3 2.5"/>' +
        '<path class="adv-line adv-mouth" d="M59 75q6 4.5 12 0"/>' +
        (years.glasses ? glasses() : '') +
      '</g>';
  }

  /* The desk: a surface the hands can rest on, and a base for the bust. */
  function desk() {
    return '<path class="adv-desk" d="M0 136h130v14H0z"/>' +
           '<path class="adv-desk-edge" d="M0 136h130"/>';
  }

  /* A forearm is a tapered wedge from under the jacket to the desk, not a
     curved stroke floating beside the body. */
  function forearm(d) { return '<path class="adv-sleeve" d="' + d + '"/>'; }

  function restingHand(x) {
    return '<path class="adv-skin" d="M' + x + ' 128q9-3 15 1 3 2 1 5-2 3-8 3h-8q-3 0-3-4z"/>' +
           '<path class="adv-line adv-knuckle" d="M' + (x + 4) + ' 130l-1 6M' +
             (x + 9) + ' 130l-1 6"/>';
  }

  function pose(name) {
    if (name === 'listen') {
      // Head down over the pad, pen moving: the answers are being written.
      return desk() +
        forearm('M46 118l10 2-4 18-14-2z') + restingHand(42) +
        forearm('M86 118l-10 2 5 18 13-3z') +
        '<g class="adv-pad-group">' +
          '<rect class="adv-pad" x="74" y="116" width="36" height="24" rx="2.5" ' +
            'transform="rotate(-7 92 128)"/>' +
          '<path class="adv-pad-line" d="M79 124h24M78 130h24M78 136h15" ' +
            'transform="rotate(-7 92 128)"/>' +
          '<g class="adv-pen">' +
            '<path class="adv-pen-body" d="M104 108l7 6-14 16-7-6z"/>' +
            '<path class="adv-pen-nib" d="M90 124l-4 9 8-3z"/>' +
          '</g>' +
        '</g>';
    }
    if (name === 'present') {
      // One palm open towards the allocation. The other stays on the desk, so
      // the gesture is one hand doing something rather than both waving.
      return desk() +
        forearm('M46 118l10 2-4 18-14-2z') + restingHand(42) +
        '<g class="adv-arm">' +
          // Out of the shoulder and up, so the forearm is visible against the
          // card rather than buried in the jacket silhouette. A hand that
          // cannot be traced back to an arm is just a pale oval.
          forearm('M94 128l10 5 18-28-10-5z') +
          '<ellipse class="adv-skin adv-palm" cx="119" cy="94" rx="8.5" ry="6.5" ' +
            'transform="rotate(-57 119 94)"/>' +
          '<path class="adv-line adv-knuckle" d="M116 90l5 3M112 95l5 3"/>' +
        '</g>';
    }
    // Asking: both hands on the desk, attention up.
    return desk() +
      forearm('M46 118l10 2-4 18-14-2z') + restingHand(42) +
      forearm('M86 118l-10 2 5 18 13-3z') + restingHand(74);
  }

  /* `pose` is the only input, and an unknown one falls back to asking rather
     than rendering an empty frame. */
  /* `pose` picks the hands, `options.age` picks the hair and the glasses.
     Both fall back rather than rendering an empty frame. */
  function figure(name, options) {
    var which = POSES[name] ? name : 'ask';
    var opts = options || {};
    var age = AGES[opts.age] ? opts.age : 'young';
    return '<div class="acf-adviser is-' + which + ' is-age-' + age + '" aria-hidden="true">' +
      '<svg viewBox="0 0 130 150" class="adv-svg" focusable="false">' +
        bust(which === 'listen' ? 7 : 0, age) + pose(which) +
      '</svg></div>';
  }

  var api = { figure: figure, poses: Object.keys(POSES), ages: Object.keys(AGES) };
  root.AltahaAdviser = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
