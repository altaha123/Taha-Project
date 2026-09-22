# Allocate — the guided card

Three questions in the only order that makes them answerable: **how much**,
then **what kind of risk that money can carry**, then **which asset classes
that implies**. One card, one stage at a time, each stage replacing the last.

It sits at the top of Allocate → Allocation plan, above the five-step sequence
that was already there. The sequence answers "what should the next rupee do".
This answers "and how much of it, in what".

---

## The adviser

A question set in a heading is a form label. The same sentence coming out of
somebody's mouth is a question, and a question gets answered. So each stage
seats a figure beside its heading, talking into a speech bubble: hands on the
desk while he asks for a number, head tilted to a pad while he takes the
answers down, one palm open towards the allocation while he hands it over.
Same person throughout — only the hands change.

**Drawn, not photographed.** A stock photograph of a man in a tie would date
the site, weigh several hundred kilobytes, need a licence, and pick a face for
a reader who did not ask for one. `frontend/adviser.js` is about two kilobytes
of inline SVG in the site's own tokens — ink line, paper fill, one gold accent
at the tie — so it draws in ink on cream and in cream on ink without a second
asset, and stays sharp at any size.

**Seated at a desk on purpose.** An earlier pass gave him free-floating arms.
At 106 pixels a curved sleeve and a pale oval do not read as an arm; they read
as a growth. A desk gives the forearms somewhere to be and the hands something
to rest on, which is easier to draw honestly and is what an adviser is
actually doing.

**He carries no meaning.** `aria-hidden`, always, and the browser test asserts
the figure contains no text of its own. The question stays a real heading at
the real level beside him, so a screen-reader user loses nothing and a reader
with reduced motion gets the figure without the blink or the bob. On a phone
he moves above the question and shrinks, and the bubble's tail flips to point
up at him.

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

**The money moves.** Gold ₹ coins spray off the slider handle as you drag,
arc, spin and fall away. The count follows the **order of magnitude of the
sum** — ₹50,000 throws a few, ₹5 crore throws a shower — so sliding into a
crore feels like more money, because it is, and a reader takes that in before
they have read a digit. Dragging down drains instead: fewer coins, heavier,
no spin, falling. A quick pick or letting go of the handle is a decision
rather than a nudge, so it gets a full spray sized to the number. The ₹ glyph
itself springs on every change, a sheen runs across the figure, and the figure
counts rather than swaps.

Every tween runs on a named channel and a newer value on the same channel
cancels the older one — without that, clicking a quick pick and immediately
dragging leaves a 400ms animation writing the old figure over the new one,
which is the display disagreeing with the control.

## Stage 2 — the profile, and a picture per question

The same figure beside twelve different questions tells a reader nothing about
any of them. Each question asks about one concrete thing — a date, a cushion,
a fall, a loan — so `frontend/question-art.js` draws that thing, and **the
drawing answers back**: point at a different option and the picture changes to
the option you are pointing at, before you have committed to it.

That preview is the point. "How far could this fall before you could not leave
it alone?" is abstract until a gauge drops to 40% and you can see how far down
that is.

| Question | What it draws |
|---|---|
| How old are you? | the adviser, at your stage of life — hair greying and going back, reading glasses arriving |
| When will you need this money? | an hourglass, sand still in the top bulb in proportion to the time this money has |
| What share of your income is left? | a month's income, with what is still there at the end stacked beside it as coins |
| Months of expenses in cash? | an umbrella in the rain, and twelve pips with the covered months filled |
| Share of income to loan repayments? | income as a note, with the lender's fixed claim chained off the side |
| How many people depend on you? | you, and the people whose outcome rides on this with you |
| ₹10 lakh is now ₹7 lakh — what do you do? | the fall, and your answer drawn as the next stroke of the same line |
| How far could it fall? | a depth gauge, against the 38% Indian equity has actually done |
| Protect or grow? | the two on the ends of a beam, because they are a trade and not a menu |
| How long have you been investing? | the market's own line, as far back as you have been standing in it |
| What is this money for? | the thing itself — a house, a cap, a palm and a sun |
| Lump sum or monthly? | one sum on one date, or the same money arriving month after month |

Every scene is a pure function — `scene(questionId, optionValue)` in, SVG
string out, no DOM and no state — so the whole library is asserted in node:
every option of every question renders, none of them leak an `undefined` into
the markup, none of them put words inside a drawing, and **each question draws
at least three different pictures across its options**, because a scene that
does not change with the answer is a decoration pretending to be an answer.

Selecting an answer holds the new picture for a beat before advancing, so a
reader on a phone — who never hovers — still sees it respond.

One question this file has no art for falls back to the adviser taking notes,
so the slot is never empty and the layout never jumps.

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

**The ring.** The whole sum as one circle, divided. Each arc sweeps out from
twelve o'clock in the order the money is committed, and then the money is
handed out: coins fly from the middle of the ring into each sleeve card, in
the proportion that sleeve receives. The split stops being a table and becomes
something that happens. The ring's centre reads the sum as a headline (₹5 Cr);
the sleeve figures below carry every digit.

**The flags matter more than the split.** An allocation handed to somebody
whose money is needed next year, or who has no emergency fund, is arithmetic
wrapped around a mistake. A horizon under three years is flagged however brave
the rest of the profile reads; so is a missing cushion, borrowings taking a
large share of income, and a lump sum about to go in on a single date.

---

## The effects are decoration, and the tests prove it

`frontend/money-fx.js` spawns everything into a layer that sits above the
card, takes no clicks, carries `aria-hidden`, and removes each particle when
it lands — with a timeout sweep behind that, because a tab backgrounded
mid-flight never fires `finish` and a coin that never lands is a leak. There
is a hard ceiling on coins alive at once.

`prefers-reduced-motion` switches the whole file off. The browser test drives
the entire flow in that mode — every figure, control and reading asserted with
not one coin on screen — and then re-drives it with motion on to assert the
coins actually fly, that a larger sum throws more of them, that the layer
takes no clicks, and that nothing leaks once they land. That is the contract:
the money effects are never load-bearing.

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
| Coins, the sheen, the arcs | `frontend/money-fx.js` |
| The figure, its three poses and its four ages | `frontend/adviser.js` |
| A scene per question | `frontend/question-art.js` |
| Styling and the reduced-motion promise | `frontend/products.css` |
| The five-step sequence below it | `frontend/allocate.js` |
| The questions, and the recorded assessment | `backend/risk_profile.py` |
| Tests | `frontend/risk-math.test.js`, `frontend/tests/allocate-flow-browser.cjs` |
