"""
Altaha Screener — Risk profiling

WHY THIS IS A MODULE AND NOT A FORM
Under the SEBI (Investment Advisers) Regulations a risk profile is not a
nicety before the interesting part; it is the thing that makes the advice
that follows defensible. The regulations name what it must weigh — age,
income, the purpose and the period of the investment, existing assets,
borrowings, and appetite for loss — so those are the questions here, and the
questionnaire lives on the server rather than in the page. One source of
truth, auditable, and the answers a reader gave reference question ids that
still mean the same thing five years later.

CAPACITY AND TOLERANCE ARE DIFFERENT THINGS, AND THE GAP IS THE POINT
Capacity is arithmetic: a 26-year-old with no dependents, eight months of
expenses in the bank and twenty years to go can absorb a bad decade. Tolerance
is temperament: what that person would actually do watching a third of their
money disappear.

The profile is the LOWER of the two, always. Advising to capacity when
tolerance is lower produces a portfolio somebody sells at the bottom, which is
how a good plan loses real money. Advising to tolerance when capacity is lower
recommends a risk they cannot afford, which is worse.

Neither number is discarded. Where they disagree, the distance between them is
reported, because that gap — not either figure — is the conversation worth
having with a person about their own money.

NOTHING HERE RECOMMENDS ANYTHING
This module answers "what kind of risk does this person's situation and
temperament describe". What to do about it is the adviser's, and lives
elsewhere.
"""
from __future__ import annotations

import datetime as dt

# Every question carries the weight it contributes and the axis it sits on, so
# a score can always be taken apart and shown back to the person who produced
# it. An opaque number about somebody's own money is not worth having.
CAPACITY = "capacity"
TOLERANCE = "tolerance"
CONTEXT = "context"          # recorded because the regulations require it,
                             # not scored

QUESTIONS = [
    {
        "id": "age",
        "axis": CAPACITY,
        "weight": 18,
        "kind": "choice",
        "label": "How old are you?",
        "why": "Years to retirement decide how long a bad decade has to recover in.",
        "options": [
            {"value": "under25", "label": "Under 25", "score": 100},
            {"value": "25_34", "label": "25 to 34", "score": 92},
            {"value": "35_44", "label": "35 to 44", "score": 74},
            {"value": "45_54", "label": "45 to 54", "score": 52},
            {"value": "55_64", "label": "55 to 64", "score": 30},
            {"value": "65plus", "label": "65 or older", "score": 15},
        ],
    },
    {
        "id": "horizon",
        "axis": CAPACITY,
        "weight": 24,
        "kind": "choice",
        "label": "When will you need this money?",
        "why": "The single strongest input. Money needed inside three years cannot "
               "be exposed to a market that has historically taken three years to "
               "recover.",
        "options": [
            {"value": "under1", "label": "Within a year", "score": 0},
            {"value": "1_3", "label": "1 to 3 years", "score": 18},
            {"value": "3_5", "label": "3 to 5 years", "score": 45},
            {"value": "5_10", "label": "5 to 10 years", "score": 75},
            {"value": "10plus", "label": "More than 10 years", "score": 100},
        ],
    },
    {
        "id": "surplus",
        "axis": CAPACITY,
        "weight": 16,
        "kind": "choice",
        "label": "What share of your monthly income is left after every expense and EMI?",
        "why": "Somebody saving a third of their income can keep investing through "
               "a fall. Somebody saving nothing has to sell into it.",
        "options": [
            {"value": "none", "label": "Nothing, or I borrow to cover the month", "score": 0},
            {"value": "under10", "label": "Under 10%", "score": 28},
            {"value": "10_25", "label": "10% to 25%", "score": 62},
            {"value": "25_40", "label": "25% to 40%", "score": 88},
            {"value": "over40", "label": "More than 40%", "score": 100},
        ],
    },
    {
        "id": "emergency",
        "axis": CAPACITY,
        "weight": 16,
        "kind": "choice",
        "label": "How many months of expenses could you cover from cash today?",
        "why": "An emergency fund is what stops a job loss becoming a forced sale "
               "at the worst possible price. Without one, every other answer here "
               "matters less.",
        "options": [
            {"value": "none", "label": "None", "score": 0},
            {"value": "under3", "label": "Less than 3 months", "score": 30},
            {"value": "3_6", "label": "3 to 6 months", "score": 72},
            {"value": "6_12", "label": "6 to 12 months", "score": 95},
            {"value": "over12", "label": "More than 12 months", "score": 100},
        ],
    },
    {
        "id": "emi",
        "axis": CAPACITY,
        "weight": 14,
        "kind": "choice",
        "label": "What share of your income goes to loan repayments?",
        "why": "Borrowings are a fixed claim on income that a falling market does "
               "not pause. The regulations require them to be weighed.",
        "options": [
            {"value": "none", "label": "None", "score": 100},
            {"value": "under20", "label": "Under 20%", "score": 80},
            {"value": "20_40", "label": "20% to 40%", "score": 48},
            {"value": "40_60", "label": "40% to 60%", "score": 18},
            {"value": "over60", "label": "More than 60%", "score": 0},
        ],
    },
    {
        "id": "dependents",
        "axis": CAPACITY,
        "weight": 12,
        "kind": "choice",
        "label": "How many people depend on your income?",
        "why": "Dependents raise the cost of being wrong.",
        "options": [
            {"value": "0", "label": "Nobody but me", "score": 100},
            {"value": "1_2", "label": "One or two", "score": 70},
            {"value": "3_4", "label": "Three or four", "score": 45},
            {"value": "5plus", "label": "Five or more", "score": 25},
        ],
    },
    {
        "id": "drawdown_action",
        "axis": TOLERANCE,
        "weight": 34,
        "kind": "choice",
        "label": "Six months after you invest ₹10 lakh it is worth ₹7 lakh. "
                 "What do you actually do?",
        "why": "The most honest question here, because it describes an action "
               "rather than an attitude. What somebody did in March 2020 predicts "
               "their next decade better than what they say about risk.",
        "options": [
            {"value": "sell_all", "label": "Sell everything and stop", "score": 0},
            {"value": "sell_some", "label": "Sell some to stop the bleeding", "score": 22},
            {"value": "hold", "label": "Hold, and wait it out", "score": 65},
            {"value": "hold_plan", "label": "Hold, and keep the monthly amount going", "score": 88},
            {"value": "buy_more", "label": "Put more in while it is cheaper", "score": 100},
        ],
    },
    {
        "id": "max_fall",
        "axis": TOLERANCE,
        "weight": 26,
        "kind": "choice",
        "label": "How far could this fall before you could not leave it alone?",
        "why": "Indian equity has fallen more than 38% inside a year and taken "
               "years to recover. A limit below that is a real constraint, not a "
               "failure of nerve.",
        "options": [
            {"value": "any", "label": "Any fall would worry me", "score": 0},
            {"value": "10", "label": "About 10%", "score": 25},
            {"value": "20", "label": "About 20%", "score": 55},
            {"value": "30", "label": "About 30%", "score": 82},
            {"value": "40plus", "label": "40% or more — I have sat through it", "score": 100},
        ],
    },
    {
        "id": "priority",
        "axis": TOLERANCE,
        "weight": 22,
        "kind": "choice",
        "label": "Which sentence is closer to true?",
        "why": "Growth and protection are a trade, not a menu. Asking which one "
               "somebody gives up is more useful than asking which they want.",
        "options": [
            {"value": "protect", "label": "I would rather protect what I have than grow it", "score": 0},
            {"value": "mostly_protect", "label": "Mostly protect, with a little growth", "score": 30},
            {"value": "balanced", "label": "Both matter about equally", "score": 58},
            {"value": "mostly_grow", "label": "Mostly grow, and I accept the swings", "score": 85},
            {"value": "grow", "label": "Grow it as fast as it will go", "score": 100},
        ],
    },
    {
        "id": "experience",
        "axis": TOLERANCE,
        "weight": 18,
        "kind": "choice",
        "label": "How long have you been investing in markets?",
        "why": "Somebody who has held through a real fall knows something about "
               "themselves that no questionnaire can establish.",
        "options": [
            {"value": "none", "label": "I have not started", "score": 20},
            {"value": "under3", "label": "Less than 3 years", "score": 42},
            {"value": "3_10", "label": "3 to 10 years", "score": 75},
            {"value": "over10", "label": "More than 10 years", "score": 100},
        ],
    },
    # Recorded, not scored. The regulations require the purpose and the amount
    # to be on file; neither tells you anything about risk on its own.
    {
        "id": "purpose",
        "axis": CONTEXT,
        "weight": 0,
        "kind": "choice",
        "label": "What is this money for?",
        "why": "Recorded because the same person carries different risk for a "
               "house deposit than for a retirement thirty years out.",
        "options": [
            {"value": "retirement", "label": "Retirement"},
            {"value": "house", "label": "A house"},
            {"value": "education", "label": "Education"},
            {"value": "wealth", "label": "Building wealth, no fixed purpose"},
            {"value": "income", "label": "Income to live on"},
            {"value": "other", "label": "Something else"},
        ],
    },
    {
        "id": "mode",
        "axis": CONTEXT,
        "weight": 0,
        "kind": "choice",
        "label": "How would you put money in?",
        "why": "A monthly amount and a single lump sum are the same money and "
               "very different risks.",
        "options": [
            {"value": "sip", "label": "A fixed amount every month"},
            {"value": "lumpsum", "label": "One lump sum"},
            {"value": "both", "label": "A lump sum now, then monthly"},
        ],
    },
    {
        "id": "amount",
        "axis": CONTEXT,
        "weight": 0,
        "kind": "amount",
        "label": "How much, in rupees?",
        "why": "The monthly figure for a SIP, or the one-time figure for a lump sum.",
    },
    {
        "id": "target",
        "axis": CONTEXT,
        "weight": 0,
        "kind": "amount",
        "label": "What would you like it to be worth? (optional)",
        "why": "Turns a plan into something that can be checked against arithmetic "
               "rather than hope.",
        "optional": True,
    },
]

BY_ID = {q["id"]: q for q in QUESTIONS}

# Five bands rather than the usual three. "Moderate" covering everything from
# 35 to 70 is the band that tells a person nothing.
BANDS = [
    (0, 20, "Conservative",
     "Capital preservation comes first. A fall of more than a few percent would "
     "be a problem, by circumstance or by temperament or both."),
    (20, 40, "Moderately conservative",
     "Some growth, but not at the cost of a fall that would force a sale."),
    (40, 60, "Balanced",
     "Growth and protection weighed about equally, and swings accepted as the "
     "cost of the first."),
    (60, 80, "Growth",
     "Long horizon and the means to sit through a bad stretch; drawdowns are "
     "expected rather than tolerated."),
    (80, 101, "Aggressive",
     "Time, surplus and temperament all point the same way. The constraint is "
     "no longer risk but patience."),
]


def _axis_score(answers: dict, axis: str) -> tuple:
    """(score 0-100, [per-question contribution]) for one axis."""
    total_weight, earned, detail = 0, 0.0, []
    for q in QUESTIONS:
        if q["axis"] != axis or not q["weight"]:
            continue
        chosen = answers.get(q["id"])
        option = next((o for o in q.get("options", []) if o["value"] == chosen), None)
        if option is None:
            continue
        total_weight += q["weight"]
        earned += q["weight"] * option["score"]
        detail.append({"id": q["id"], "label": q["label"],
                       "answer": option["label"], "score": option["score"],
                       "weight": q["weight"]})
    if not total_weight:
        return None, detail
    return round(earned / total_weight, 1), detail


def band(score: float) -> tuple:
    for low, high, name, note in BANDS:
        if low <= score < high:
            return name, note
    return BANDS[-1][2], BANDS[-1][3]


def required_ids() -> list:
    return [q["id"] for q in QUESTIONS
            if q["weight"] or (q["axis"] == CONTEXT and not q.get("optional"))]


def missing(answers: dict) -> list:
    out = []
    for qid in required_ids():
        value = answers.get(qid)
        if value in (None, "", []):
            out.append(qid)
            continue
        q = BY_ID[qid]
        if q["kind"] == "choice" and not any(o["value"] == value for o in q["options"]):
            out.append(qid)
        elif q["kind"] == "amount":
            try:
                if float(value) <= 0:
                    out.append(qid)
            except (TypeError, ValueError):
                out.append(qid)
    return out


def assess(answers: dict) -> dict:
    """The profile, and everything that produced it."""
    gaps = missing(answers or {})
    if gaps:
        return {"error": "Some answers are missing.", "missing": gaps}

    capacity, cap_detail = _axis_score(answers, CAPACITY)
    tolerance, tol_detail = _axis_score(answers, TOLERANCE)

    # The lower of the two, always. Advising to capacity past tolerance builds a
    # portfolio that gets sold at the bottom; advising to tolerance past
    # capacity recommends a risk the person cannot afford to carry.
    score = min(capacity, tolerance)
    name, note = band(score)
    gap = round(abs(capacity - tolerance), 1)

    if capacity > tolerance:
        binding = ("tolerance",
                   "Your circumstances could carry more risk than you would be "
                   "comfortable holding. The comfort is the binding constraint, "
                   "and it is the right one to respect — a plan abandoned "
                   "halfway costs more than a cautious one kept.")
    elif tolerance > capacity:
        binding = ("capacity",
                   "You are willing to carry more risk than your circumstances "
                   "can absorb today. Horizon, surplus or the emergency fund is "
                   "the limit, and each of those can be changed — which "
                   "makes this the more useful of the two gaps to have.")
    else:
        binding = ("both", "Circumstances and temperament agree.")

    return {
        "capacity": capacity,
        "tolerance": tolerance,
        "score": score,
        "band": name,
        "band_note": note,
        "gap": gap,
        "binding": binding[0],
        "binding_note": binding[1],
        "detail": {"capacity": cap_detail, "tolerance": tol_detail},
        "context": {q["id"]: answers.get(q["id"])
                    for q in QUESTIONS if q["axis"] == CONTEXT},
        "assessed_at": dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0).isoformat(),
    }
