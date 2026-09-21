/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Risk arithmetic, shared

   WHY THIS IS ITS OWN FILE
   Two screens now compute a profile without the server: the questionnaire in
   the planner, and the guided card in Allocate. A person who answers the same
   questions in two places and is handed two different bands has been told
   nothing, so the arithmetic lives in one file and both screens call it.

   THE SERVER'S ASSESSMENT IS STILL THE ONE THAT COUNTS. This exists so a
   reader who has not signed in — and therefore has nobody to record a profile
   against — still gets an answer instead of a sign-in wall. It mirrors
   `backend/risk_profile.py`; that file is the specification.

   CAPACITY AND TOLERANCE, AND THE LOWER OF THE TWO
   Capacity is what somebody's circumstances can absorb. Tolerance is what
   their temperament can sit through. The profile is the LOWER, always:
   advising to capacity when tolerance is lower builds a portfolio that gets
   sold at the bottom, and advising to tolerance when capacity is lower
   recommends a risk they cannot afford. Neither number is thrown away — the
   distance between them is the conversation worth having.

   NOTHING HERE RECOMMENDS ANYTHING. It describes a person back to themselves.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var DEFAULT_BANDS = [
    { from: 0,  to: 20,  band: 'Conservative' },
    { from: 20, to: 40,  band: 'Moderately conservative' },
    { from: 40, to: 60,  band: 'Balanced' },
    { from: 60, to: 80,  band: 'Growth' },
    { from: 80, to: 101, band: 'Aggressive' }
  ];

  /* One axis: the weighted average of the scores actually answered. Questions
     left blank are excluded from the denominator rather than scored zero —
     an unanswered question is not evidence of caution. */
  function axis(answers, questions, name) {
    var weight = 0, earned = 0, counted = 0;
    (questions || []).forEach(function (q) {
      if (q.axis !== name || !q.weight) return;
      var chosen = (answers || {})[q.id];
      var option = (q.options || []).filter(function (o) { return o.value === chosen; })[0];
      if (!option || typeof option.score !== 'number') return;
      weight += q.weight;
      earned += q.weight * option.score;
      counted++;
    });
    if (!weight) return { value: null, answered: 0 };
    return { value: Math.round(earned / weight * 10) / 10, answered: counted };
  }

  function bandFor(score, bands) {
    var list = (bands && bands.length) ? bands : DEFAULT_BANDS;
    var hit = list.filter(function (b) { return score >= b.from && score < b.to; })[0];
    return hit || list[list.length - 1];
  }

  /* The scored questions only. Context questions (purpose, mode, amount) are
     recorded by the server because the regulations require them; they carry no
     weight and must never move a band. */
  function required(questions) {
    return (questions || []).filter(function (q) { return q.weight > 0; });
  }

  function remaining(answers, questions) {
    return required(questions).filter(function (q) {
      var v = (answers || {})[q.id];
      return v === undefined || v === '';
    });
  }

  function assess(answers, questions, bands) {
    var capacity = axis(answers, questions, 'capacity');
    var tolerance = axis(answers, questions, 'tolerance');
    if (capacity.value === null || tolerance.value === null) return null;

    var score = Math.min(capacity.value, tolerance.value);
    var hit = bandFor(score, bands);
    var binding = capacity.value > tolerance.value ? 'tolerance'
                : tolerance.value > capacity.value ? 'capacity' : 'both';

    return {
      capacity: capacity.value,
      tolerance: tolerance.value,
      score: score,
      band: hit.band,
      band_note: hit.note || '',
      gap: Math.round(Math.abs(capacity.value - tolerance.value) * 10) / 10,
      binding: binding,
      binding_note: binding === 'tolerance'
        ? 'Your circumstances could carry more risk than you would be comfortable holding.'
        : binding === 'capacity'
          ? 'You are willing to carry more risk than your circumstances can absorb today.'
          : 'Circumstances and temperament agree.',
      answered: capacity.answered + tolerance.answered
    };
  }

  var api = { assess: assess, axis: axis, bandFor: bandFor,
              required: required, remaining: remaining, DEFAULT_BANDS: DEFAULT_BANDS };

  root.AltahaRiskMath = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
