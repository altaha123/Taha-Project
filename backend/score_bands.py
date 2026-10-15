"""
score_bands.py — the one place an Altaha Score becomes a word.

WHY THIS EXISTS
The portfolio review used to carry five different scales for the same
number. The action plan called 60 "strong"; the holding list called 60
"good" and needed 70 for "strong"; the story counted only 70+; the
rulebook floor sat at 45 while the plan's "weak" line sat at 40; and two
letter grades were cut at different places. A holding scoring 42 was
"middling, keep it" on the plan card, "weak" in the list and a "score
floor breach" in the agenda — on one page, at one time.

V4 scores are peer percentiles shrunk toward 50 by confidence, so they do
not spread over 0-100. Across the analysed cohort the median is about 51,
the top tenth starts near 62, and the random control group's middle half
runs 41-53 (see action_plan.py). A scale that waits for 70 to say
"strong" almost never says it. These cuts follow where the scores
actually fall, and every module reads them from here.

  STRONG   60+     roughly the top 15%
  GOOD     55-60   roughly the next 10%
  AVERAGE  40-55   the ordinary middle; v4 puts thin evidence here
  WEAK     33-40
  POOR     under 33, roughly the bottom 5%

Change a number here and the plan, the list, the story, the charts and the
rulebook default all move together.
"""

STRONG = 60.0
GOOD = 55.0
WEAK = 40.0          # below this is weak
POOR = 33.0          # below this is poor

# Highest floor first; the first floor a score reaches names it.
BANDS = [(STRONG, "Strong"), (GOOD, "Good"), (WEAK, "Average"), (POOR, "Weak"), (0.0, "Poor")]

# The value-weighted portfolio score uses the same cuts, as a letter.
GRADES = {"Strong": "A", "Good": "B+", "Average": "B", "Weak": "C", "Poor": "D"}

# The rulebook's default "minimum Altaha Score" is the weak line, so the
# default floor and the plan agree about which holdings are weak.
DEFAULT_FLOOR = WEAK


def band(score):
    """The word for a score, 'Unscored' for None."""
    if score is None:
        return "Unscored"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "Unscored"
    if s != s:                        # NaN
        return "Unscored"
    return next((label for floor, label in BANDS if s >= floor), BANDS[-1][1])


def grade(score):
    """A letter for a value-weighted portfolio score; '—' without one."""
    b = band(score)
    return GRADES.get(b, "—")


def as_payload():
    """The cuts, for the browser, so no page hard-codes its own."""
    return {"strong": STRONG, "good": GOOD, "weak": WEAK, "poor": POOR,
            "bands": [{"floor": f, "label": l} for f, l in BANDS]}
