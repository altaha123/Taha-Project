# Allocate — the guided card

Three questions in the only order that makes them answerable: **how much**,
then **what kind of risk that money can carry**, then **which asset classes
that implies**. One card, one stage at a time, each stage replacing the last.

It sits at the top of Allocate → Allocation plan, above the five-step sequence
that was already there. The sequence answers "what should the next rupee do".
This answers "and how much of it, in what".

---

## Stage 1 — the amount

A slider from **₹1 to ₹20 crore**, an exact figure typeable beside it, and
five quick picks.

**Why the scale has a knee.** A single logarithmic track from ₹1 spends three
fifths of its length on sums below a lakh — amounts nobody is allocating — and
squeezes ₹1 lakh to ₹20 crore into the last two fifths. A linear track is
worse: at that range every sum under ₹20 lakh lands within a few pixels of
zero. So the scale is two log segments joined at ₹1 lakh, which gets the first
five decades a fifth of the track and the remaining three and a bit decades
the other four fifths. Still monotonic, still exactly invertible, and ₹1 is
still reachable.

**Why round numbers.** A slider that reports ₹1,03,477 is reporting its own
pixel width, not an intention. Values snap to a step that matches their size —
₹500 under a lakh, ₹25,000 over ten lakh, ₹1 lakh over a crore — and
`rupeesToSlider` lands on the handle position that reads back *exactly* what
was picked, so choosing ₹1 Cr and then nudging the slider does not first jump
to ₹99.5 lakh.

**Animation.** The figure counts rather than swaps, the fill follows the
handle, the card and its rows stagger in. Every tween runs on a named channel
and a newer value on the same channel cancels the older one — without that,
clicking a quick pick and immediately dragging leaves a 400ms animation
writing the old figure over the new one, which is the display disagreeing with
the control.

## Stage 2 — the profile

The questions come from `GET /planner/questions`, which is the same list the
planner's questionnaire renders — same ids, same weights, **same draft in
`localStorage`**. Answering here is answering there, and the card resumes at
the first unanswered question rather than making anybody click through answers
they already gave.

Asked: every scored question, plus `purpose` and `mode`, which the regulations
want on file and which carry no weight. **Not** asked: `amount` — the slider
answered it, and asking twice is asking twice.

One question per screen, with the reason it is being asked printed under it.
Choosing an answer advances; the last one waits for a deliberate click.

The profile is the **lower** of capacity and temperament, always. That
arithmetic lives in `frontend/risk-math.js` because two screens now compute it
without the server, and a person handed two different bands for one set of
answers has been told nothing. Signed in, the server's assessment is used and
recorded against the account. Signed out, it is computed here and the card
says plainly that it was not kept.

## Stage 3 — the asset classes

Three sleeves — growth-type, stable, gold — as a range from the profile band,
a rupee figure, and the categories inside each one, which shift with the band:
the same 50% in equities is a different thing held as broad-market exposure
than held in mid and small companies.

**The rupee figures add up, exactly.** The three ranges are independent
guardrails, so their midpoints do not sum to 100% on their own — Balanced
centres on 50 + 45 + 7.5. Handing somebody three figures adding to 102.5% of
their money is an error a reader finds with a calculator, so the midpoints are
scaled to the amount, each scaled share still lands inside its own published
range, and the card says on its face that this is what it did. Figures are
then rounded to a unit matching the size of the sum, with the rounding drift
pushed onto the largest line so the parts still total what was put in.

**The flags matter more than the split.** An allocation handed to somebody
whose money is needed next year, or who has no emergency fund, is arithmetic
wrapped around a mistake. A horizon under three years is flagged however brave
the rest of the profile reads; so is a missing cushion, borrowings taking a
large share of income, and a lump sum about to go in on a single date.

---

## What it will not do

Categories, never products. Ranges, never a single number presented as the
right one. No instruction to buy or sell anything. Under the SEBI adviser
regulations what to buy is not this project's to say, and the profile is what
makes anything downstream of it defensible at all. The browser test asserts
the rendered card contains no directive verb.

Everything computes in this browser. The only network calls are the
questionnaire itself and, for a signed-in reader, recording their own profile
against their own account.

## Where it lives

| Concern | File |
|---|---|
| Capacity, temperament, the lower of the two | `frontend/risk-math.js` |
| Slider scale, the split, the flags, the card | `frontend/allocate-flow.js` |
| Styling and the reduced-motion promise | `frontend/products.css` |
| The five-step sequence below it | `frontend/allocate.js` |
| The questions, and the recorded assessment | `backend/risk_profile.py` |
| Tests | `frontend/risk-math.test.js`, `frontend/tests/allocate-flow-browser.cjs` |
