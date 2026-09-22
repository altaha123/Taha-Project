# Allocate — the guided card

Three questions in the only order that makes them answerable: **how much**,
then **what kind of risk that money can carry**, then **which asset classes
that implies**. One card, one stage at a time, each stage replacing the last.

It is the whole of Allocate → Allocation plan.

A five-step sequence used to sit under it — cushion, costly debt, dated money,
the split, position size — carrying a genuine argument about order. It was
removed, because next to the card it had stopped earning its space: three of
its five steps could say nothing at all until the Money Planner had been
filled in, so they read as three paragraphs of theory pointing at another
screen; the fourth repeated the card's own split back in percentages where the
card gives rupees; and the fifth asked the reader to retype the growth sleeve
the card had just worked out for them. The Money Planner is still its own tab
for the household numbers.

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

**Why round numbers, and why not while you drag.** A slider that reports
₹1,03,477 is reporting its own pixel width, not an intention, so a settled
value snaps to a step matching its size — ₹500 under a lakh, ₹25,000 over ten
lakh, ₹1 lakh over a crore — and `rupeesToSlider` lands on the handle position
that reads back *exactly* what was picked, so choosing ₹1 Cr and then nudging
the slider does not first jump to ₹99.5 lakh.

While the handle is **moving**, that step is too coarse to be the step: at
₹18.5 lakh it is ₹25,000 against ₹10,000 of displayed resolution, so eight
consecutive handle positions read identically and the ninth jumped two or
three readings at once. A drag therefore steps by a thousandth of the figure's
own size and settles onto the round one when it is let go — the reading moves
with the handle instead of lurching behind it.

**Why the figure keeps its shape.** `words` trims trailing zeros, which is
right for a chip or an axis mark and wrong for a number in motion: "19 L" is
two characters and "18.75 L" is seven, so the reading changed length as it
moved and the digits shuffled sideways under a fixed-width font. The moving
figure uses a fixed number of decimals for whatever unit it is in, so the
digits change and the string does not.

**Why the sparkle waits for a commit.** The ₹ spring and the sheen fire when a
figure is *chosen* — a quick pick, a release, a typed number — never on every
frame of a drag. Firing them per input event restarted a 420ms spring dozens
of times a second, so the symbol never finished a movement and the sheen
strobed; both read as jitter rather than as motion. For the same reason a drag
throws two or three coins per batch and the full spray belongs to the commit,
and the fill tracks the handle with its transition off rather than easing
towards it from behind.

**Why the state is written late.** `saveState` is debounced by 300ms.
`localStorage.setItem` is synchronous, and one write per mouse move is disk
work inside the frame budget — it showed up as the drag stuttering rather than
as anything obviously wrong. A stage change still writes immediately, since a
reader can navigate away inside that window.

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

**One dot per question, under the card.** Filled when answered, ringed when
current, hollow when still to come. Hovering or focusing one names the
question it stands for, and clicking it goes there — which is what somebody
wanting to change an earlier answer reaches for, rather than pressing Back
eight times. The name appears in a line of its own rather than a floating
tooltip: twelve tooltips at phone width would be clipped by the card, and a
line is readable on a touch screen, which has no hover at all.

**The question holds its place while the answers scroll.** A six-option
question is taller than a laptop window, so scrolling to reach the last option
used to carry the question and its picture off the top of the screen, leaving a
column of answers to nothing. The question, its picture and the progress line
are now sticky inside the card.

That took fixing something older and larger. `premium.css` set
`overflow-x: hidden` on the **body**, which makes the body a scroll container —
and the used value of `overflow-y` then becomes `auto`. So every
`position: sticky` element inside the body was resolving against the body's
scrollport, which never scrolls, while the document scrolled underneath.
Sticky silently did nothing anywhere on the site, including the rules already
written for it in `stock.css` and `experience.css`. `overflow-x: clip` holds
back the same horizontal overflow without becoming a scroll container. The
browser test asserts the body's `overflow-y` is not `auto`, because the symptom
is invisible: sticky simply stops working and nothing throws.

**And each new screen starts at its own top.** Pressing Continue at the bottom
of one stage left the page scrolled there, so the next stage opened halfway
down its own options. A new screen now pulls the card back into view — but only
when the top of the card has gone behind the site chrome, since scrolling
somebody who is already looking at the top of the card is the page fighting
them.

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

## Stage 3 — the answer

The payoff screen, so the least wordy one. A reader who has put in ₹10 lakh
and answered ten questions is owed numbers, not two paragraphs about
temperament. The order on the card:

1. **What has a prior claim on the money.** Before a rupee is split, two
   things come off the top. A **cushion** of six months' expenses, sized in
   rupees from the household numbers — the planner's if it has published
   them this session, otherwise a monthly-expenses field on the card itself,
   asked for rather than assumed. And **costly loans**: anything above about
   10% a year (cards, personal loans; a home loan at 8–9% is not costly debt)
   is a certain return no sleeve can match, so what is outstanding on them is
   closed first. Both are capped at what is left, and what remains is printed
   as **Free to invest**. First calls plus sleeves equal exactly what was put
   in; `frontend/risk-math.test.js` asserts it.

2. **The sleeves as numbers.** Grows, Stays put, Gold — a rupee figure, one
   line on what each does, and a bar. A toggle reads the same figures as
   twelve monthly ones, because that is how a salaried person will actually
   do it.

3. **What it is likely to become.** Each sleeve compounded over a years
   slider (opening on the horizon that was answered): a range from long-run
   published Indian series — 10–13% for broad equity, 6–7.5% for deposits
   and short debt, 7–10% for gold in rupees — and the fall each has actually
   taken inside a year, in rupees. A total, and the total in today's money
   at 6% inflation. A range, before tax, never a promise; the card says so
   on the row.

4. **How to do it.** Every category carries the *kind* of instrument (an
   index fund tracking the Nifty 50; a bank deposit of one to three years;
   Sovereign Gold Bonds when a tranche is open), the *route* to it (which
   sort of app, bank or account), and *what to look for* on the label
   (direct plan, expense ratio, DICGC cover, occupancy). That is enough to
   walk into any app and judge what is on offer. It names no fund, no house
   and no platform — a category is education, a name is advice this project
   is not registered to give, and the test greps for both the brands and the
   directive verbs.

5. **Considered, and left out.** Property, private funds, start-ups and
   crypto are asset classes too, so their absence is said with the reason in
   the reader's own numbers: a ₹1 crore AIF minimum is "more than all of this
   money" or "33% of what is free"; a flat is one thing, in one place, with
   7–8% to enter and leave. Listed real estate does get in — REITs and InvITs
   join the growth sleeve at 5–10% of it once the sum passes ₹5 lakh.

6. **The flags, one line each.** Then, behind a tap, why this profile: the
   band note, capacity and temperament, and how the split is built.

**Money with a date gets no growth sleeve.** A horizon inside three years is
not a risk to be sized; it is the reason equity does not apply to this money
at all. The whole free sum goes to deposits and short-duration debt — not to
long-locked savings either — and the stop flag says why.

**Alternatives enter only when everything allows it.** A fourth sleeve,
carved out of growth rather than added on top, when the band is Growth or
Aggressive, the horizon is ten-plus years, the reader has three or more
years in the market, and the sum is large enough that the minimum ticket is
a minority: AIFs (Category II & III, ₹1 crore per fund) from ₹5 crore free,
angel investing (₹25 lakh cheques) from ₹2 crore for an Aggressive reader
with a decade behind them. 10% of the free sum for Growth, 15% for
Aggressive. No outcome range is invented for them: there is no reliable
public series, and the row says so.

**The rupee figures add up, exactly.** The sleeve ranges are independent
guardrails, so their midpoints do not sum to 100% on their own — Balanced
centres on 50 + 45 + 7.5. The midpoints are scaled to what is free, each
scaled share still lands inside its own published range, figures are rounded
to a unit matching the size of the sum, and the drift is pushed onto the
largest line so the parts total what was put in.

**The ring.** The free sum as one circle, divided. Each arc sweeps out from
twelve o'clock in the order the money is committed, and then coins fly from
the middle into each sleeve in proportion. The centre reads a headline
(₹5.5 L); the sleeves carry every digit.

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
| Slider scale, first calls, the split, alternatives, outcomes, routes, the card | `frontend/allocate-flow.js` |
| Coins, the sheen, the arcs | `frontend/money-fx.js` |
| The figure, its three poses and its four ages | `frontend/adviser.js` |
| A scene per question | `frontend/question-art.js` |
| Styling and the reduced-motion promise | `frontend/products.css` |
| The questions, and the recorded assessment | `backend/risk_profile.py` |
| Tests | `frontend/risk-math.test.js`, `frontend/tests/allocate-flow-browser.cjs` |
