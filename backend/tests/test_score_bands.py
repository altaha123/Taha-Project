"""
One scale for the whole portfolio review.

The review used to describe one score five ways. A holding at 42 was
"middling, keep it" on its plan card, "weak" in the holding list and a
"score floor breach" in the agenda, all on the same page; a 62 was
"one of your strongest" on the plan and merely "good" in the list. These
tests read the same holding through every part of the review and require
them to agree.
"""
import threading
import time

import pytest

import action_plan
import ic_review
import portfolio
import portfolio_intelligence as pi
import score_bands as B
import score_on_request as S
from test_portfolio_intelligence import row, report, NOW
from test_score_on_request import cohort, payload


# ── The scale itself ───────────────────────────────────────────────────────

@pytest.mark.parametrize("score, label", [
    (75, "Strong"), (60, "Strong"), (59.9, "Good"), (55, "Good"), (54, "Average"),
    (40, "Average"), (39.9, "Weak"), (33, "Weak"), (32.9, "Poor"), (0, "Poor"),
    (-1, "Poor"), (None, "Unscored"), (float("nan"), "Unscored"), ("x", "Unscored"),
])
def test_every_score_has_exactly_one_word(score, label):
    assert B.band(score) == label


def test_the_bands_are_ordered_and_cover_everything():
    floors = [f for f, _ in B.BANDS]
    assert floors == sorted(floors, reverse=True)
    assert floors[-1] == 0


# ── Every module reads the same cuts ───────────────────────────────────────

def test_no_module_keeps_a_private_scale():
    assert (action_plan.STRONG, action_plan.GOOD, action_plan.WEAK, action_plan.POOR) == \
        (B.STRONG, B.GOOD, B.WEAK, B.POOR)
    assert portfolio.STRONG_SCORE == B.STRONG and portfolio.WEAK_SCORE == B.WEAK
    assert pi.BANDS == B.BANDS
    assert portfolio.DEFAULT_POLICY["min_composite"] == B.WEAK


@pytest.mark.parametrize("score", [42, 38, 30, 56, 62])
def test_one_holding_reads_the_same_everywhere(score):
    rows = [row("A", 60_000, 50_000, 58), row("B", 40_000, 35_000, score, "Technology")]
    rep = report(rows)
    b = next(h for h in rep["holdings"] if h["symbol"] == "B")
    word = b["score_category"]
    assert word == B.band(score)

    plan = action_plan.plan(rep)
    act = next(a for a in plan["actions"] if a["symbol"] == "B")
    floor_breach = any(x["rule"] == "min_composite" and x.get("symbol") == "B" for x in rep["breaches"])

    if word in ("Weak", "Poor"):
        # Weak in the list is never "nothing to do" on the plan, and the
        # default floor flags it too.
        assert act["action"] in ("TRIM", "EXIT")
        assert floor_breach
    else:
        # Average or better is never a floor breach under the default rules,
        # and never a sell on evidence alone.
        assert not floor_breach
        assert act["action"] not in ("EXIT",)


def test_the_strong_observation_uses_the_strong_line():
    rep = report([row("A", 50_000, 40_000, 61), row("B", 50_000, 40_000, 59)])
    strong = next((o for o in rep["observations"] if o["title"] == "Strongest current evidence"), None)
    assert strong and "A (61)" in strong["text"] and "B (" not in strong["text"]


def test_the_grade_follows_the_band():
    assert B.grade(None) == "—"
    assert [B.grade(s) for s in (65, 57, 50, 35, 20)] == ["A", "B+", "B", "C", "D"]


def test_the_report_carries_the_cuts_for_the_browser():
    rep = report([row("A", 50_000, 40_000, 61)])
    assert rep["score_bands"]["strong"] == B.STRONG
    assert [b["label"] for b in rep["score_bands"]["bands"]] == [l for _, l in B.BANDS]


def test_the_distribution_has_one_bucket_per_band_and_unscored():
    rep = report([row("A", 50_000, 40_000, 61), row("B", 50_000, 40_000, None)])
    labels = [d["label"] for d in rep["score_distribution"]]
    assert labels == [l for _, l in B.BANDS] + ["Unscored"]


# ── A score still being computed is waited for, not dropped ────────────────

def test_join_returns_a_cached_score_without_fetching():
    sc = S.OnRequestScorer()
    p = payload(cohort())
    key = S.cohort_of(p)[1]
    sc._store(("NEWCO", key), {"position": {"final_score": 57.0}})
    assert sc.join("NEWCO.NS", p, wait=0)["position"]["final_score"] == 57.0


def test_join_never_starts_a_computation():
    sc = S.OnRequestScorer()
    assert sc.join("NEWCO.NS", payload(cohort()), wait=0.01) is None
    assert sc._inflight == {} and sc._pool is None


def test_join_waits_for_the_computation_already_running():
    gate = threading.Event()
    sc = S.OnRequestScorer(wait=0.01)
    p = payload(cohort())

    def fetch():
        gate.wait(2)
        raise RuntimeError("no network in tests")

    first = sc.score("NEWCO.NS", p, fetch)
    assert first.get("pending")
    started = time.monotonic()
    threading.Timer(0.1, gate.set).start()
    assert sc.join("NEWCO.NS", p, wait=2) is None       # it failed: nothing to show
    assert time.monotonic() - started >= 0.09           # but it was waited for


def test_a_pending_holding_is_told_to_rerun_not_to_wait_for_the_next_scan():
    r = {"symbol": "NEWCO", "composite": None, "weight_pct": 5.0, "qty": 10, "price": 100.0,
         "value": 1000.0, "score_pending": True}
    act = action_plan.call(r, 20_000.0, {})
    assert act["action"] == "HOLD"
    assert "run the review again" in act["why"] and "next scan" not in act["why"]
