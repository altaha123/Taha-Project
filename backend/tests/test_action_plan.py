"""
The action plan: one call per holding, with the trade and the reason.

These calls tell people what to do with their money, so the tests are about
the ways a rule-based call goes wrong in public:

  · a threshold that fires on ordinary companies — "Exit Reliance" for a
    score of 43, which is where the median NSE company sits on v4;
  · arithmetic that does not do what the sentence says — a trim "to your
    15% limit" that leaves the stock at 15.9%;
  · a call with no reason attached, or a switch suggestion into something
    the reader already owns, or into a weaker company;
  · a plan that asks for new money in six places at once.
"""
import math
import types

import pytest

import action_plan as P

POLICY = {"max_stock_pct": 15.0, "min_composite": 45, "review_drawdown": 25.0}


def row(symbol="X", score=50.0, weight=8.0, pnl_pct=5.0, qty=10, price=100.0,
        total=None, sector="Technology", buy=None):
    total = total or (qty * price) / (weight / 100.0)
    value = qty * price
    buy = buy if buy is not None else (price / (1 + pnl_pct / 100.0) if pnl_pct is not None else None)
    return {"symbol": symbol, "name": symbol + " Ltd", "sector": sector, "composite": score,
            "weight_pct": weight, "pnl_pct": pnl_pct, "qty": qty, "price": price,
            "value": value, "buy_price": buy,
            "altaha_score_v4": {"position": {"final_score": score,
                                             "pillars": {"quality": 70, "momentum": 20}}}}, total


def c(r, total, **kw):
    return P.call(r, total, POLICY, **kw)


# ── Calibration ────────────────────────────────────────────────────────────

def test_an_ordinary_score_is_not_a_sell():
    """v4's median is about 51 and its random controls run 41-53. Reliance
    scored 43.3 on 29 Sep 2026: that is an ordinary company, not an exit."""
    r, t = row("RELIANCE", score=43.3, weight=10, pnl_pct=-4)
    out = c(r, t, sector_state="Improving", sector_rel_3m=1.2)
    assert out["action"] == "HOLD"


# ── Every rule, with its trade ────────────────────────────────────────────

def test_poor_evidence_is_an_exit_of_the_whole_position():
    r, t = row(score=28, weight=6, qty=12)
    out = c(r, t)
    assert out["action"] == "EXIT" and out["conviction"] == "high"
    assert out["move"]["side"] == "sell" and out["move"]["shares"] == 12 and out["move"]["all"]
    assert out["todo"].startswith("Sell all 12 shares")


@pytest.mark.parametrize("kw,expect", [
    (dict(sector_state="Lagging", sector_rel_3m=-5.0), "trailing the market"),
])
def test_weak_evidence_in_a_trailing_industry_is_an_exit(kw, expect):
    r, t = row(score=37, weight=8)
    out = c(r, t, **kw)
    assert out["action"] == "EXIT" and expect in out["why"]


def test_weak_evidence_past_the_readers_review_mark_is_an_exit():
    r, t = row(score=37, weight=8, pnl_pct=-31)
    out = c(r, t)
    assert out["action"] == "EXIT" and "25% mark you set" in out["why"]


def test_weak_and_tiny_is_tidied_up():
    r, t = row(score=38, weight=1.5)
    assert c(r, t)["action"] == "EXIT"


def test_weak_evidence_otherwise_sells_half():
    r, t = row(score=38, weight=8, qty=11)
    out = c(r, t)
    assert out["action"] == "TRIM" and out["move"]["shares"] == 5
    assert "half" in out["why"]


def test_a_single_weak_share_cannot_be_halved():
    r, t = row(score=38, weight=8, qty=1, price=5000)
    out = c(r, t)
    assert out["action"] == "EXIT" and out["move"]["all"]


def test_a_trim_to_the_limit_ends_at_or_under_the_limit():
    # 10 shares at 60,000 in a 25 lakh book: 24%. The limit is 15%.
    r, t = row("HDFCBANK", score=78, weight=24, qty=10, price=60000, total=2_500_000)
    out = c(r, t)
    assert out["action"] == "TRIM"
    assert out["move"]["after_weight_pct"] <= 15.0
    assert out["move"]["shares"] == 5
    # And not one share more than needed: selling 4 would leave it above.
    four = 100 * (600000 - 4 * 60000) / (2_500_000 - 4 * 60000)
    assert four > 15.0
    assert "good company" in out["why"].lower()


def test_averaging_down_states_the_new_average_cost():
    r, t = row(score=62, weight=6, pnl_pct=-20, qty=10, price=80.0, buy=100.0)
    out = c(r, t, sector_state="Improving", sector_rel_3m=2.0)
    assert out["action"] == "AVERAGE"
    m = out["move"]
    assert m["side"] == "buy" and m["shares"] >= 1 and m["shares"] <= 10
    expected = (10 * 100.0 + m["shares"] * 80.0) / (10 + m["shares"])
    assert m["avg_cost_after"] == pytest.approx(round(expected, 2))
    assert m["after_weight_pct"] <= 15.0
    assert "average cost falls from ₹100 to" in out["todo"]


def test_no_averaging_into_a_trailing_industry():
    r, t = row(score=62, weight=6, pnl_pct=-20)
    assert c(r, t, sector_state="Weakening", sector_rel_3m=-3.0)["action"] != "AVERAGE"


def test_a_strong_small_holding_is_added_to_up_to_the_target():
    r, t = row(score=66, weight=4, qty=10, price=100.0)
    out = c(r, t, sector_state="Leading", sector_rel_3m=4.0)
    assert out["action"] == "ADD" and out["conviction"] == "high"
    assert out["move"]["after_weight_pct"] <= P.ADD_TARGET_PCT
    assert out["todo"].startswith("Buy ")


def test_a_solid_holding_is_held_with_a_reason():
    r, t = row(score=57, weight=9)
    out = c(r, t)
    assert out["action"] == "HOLD" and out["why"] and out["todo"] == "No change needed"


def test_an_unscored_holding_is_held_unless_it_is_oversized():
    r, t = row(score=None, weight=8)
    r["altaha_score_v4"] = {}
    assert c(r, t)["action"] == "HOLD"
    r2, t2 = row(score=None, weight=30, qty=10, price=100)
    r2["altaha_score_v4"] = {}
    assert c(r2, t2)["action"] == "TRIM"


def test_every_call_says_why_and_shows_its_evidence():
    for score, weight, pnl in [(28, 6, 5), (38, 8, 5), (78, 24, 5), (62, 6, -20), (66, 4, 5), (57, 9, 5)]:
        r, t = row(score=score, weight=weight, pnl_pct=pnl)
        out = c(r, t)
        assert out["why"], out
        assert out["reasons"][0].startswith("Altaha Score")
        assert any("your limit for one stock is 15%" in x for x in out["reasons"])


# ── Where the money could go ──────────────────────────────────────────────

UNIVERSE = [
    {"symbol": "ICICIBANK", "name": "ICICI Bank", "sector": "Financial Services", "industry": "Banks - Regional", "position_score": 68},
    {"symbol": "KOTAKBANK", "name": "Kotak", "sector": "Financial Services", "industry": "Banks - Regional", "position_score": 58},
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Financial Services", "industry": "Banks - Regional", "position_score": 70},
    {"symbol": "WEAKBANK", "name": "Weak", "sector": "Financial Services", "industry": "Banks - Regional", "position_score": 44},
    {"symbol": "SUNPHARMA", "name": "Sun Pharma", "sector": "Healthcare", "industry": "Drug Manufacturers - Specialty & Generic", "position_score": 66},
    {"symbol": "CIPLA", "name": "Cipla", "sector": "Healthcare", "industry": "Drug Manufacturers - Specialty & Generic", "position_score": 61},
    {"symbol": "LOWPHARMA", "name": "Low", "sector": "Healthcare", "industry": "Drug Manufacturers - Specialty & Generic", "position_score": 40},
]


def test_a_switch_is_into_a_clearly_stronger_company_in_the_same_industry_not_already_held():
    uni = P._universe({"factor_universe": UNIVERSE})
    r, _ = row("YESBANK", score=38, sector="Financial Services")
    r["industry"] = "Banks - Regional"
    alts = P.alternatives_for(r, uni, held={"YESBANK", "HDFCBANK"})
    assert [a["symbol"] for a in alts] == ["ICICIBANK", "KOTAKBANK"]
    assert all(a["score"] >= max(P.GOOD, 38 + P.PEER_GAP) for a in alts)


STEEL = [
    {"symbol": "GNFC", "name": "GNFC", "sector": "Basic Materials", "industry": "Agricultural Inputs", "position_score": 68},
    {"symbol": "JSWSTEEL", "name": "JSW Steel", "sector": "Basic Materials", "industry": "Steel", "position_score": 60},
]


def test_a_switch_is_only_ever_into_the_same_industry():
    """Live, 29 Sep 2026: Tata Steel's switch was GNFC, a fertiliser maker,
    labelled "same industry" because both sit in Basic Materials. A steel
    maker is offered even when the fertiliser maker scores higher; with no
    steel maker to offer, there is no switch at all."""
    r, t = row("TATASTEEL", score=32, weight=4, pnl_pct=-20, sector="Basic Materials")
    r["industry"] = "Steel"
    alts = P.alternatives_for(r, P._universe({"factor_universe": STEEL}), held={"TATASTEEL"})
    assert [(a["symbol"], a["group"]) for a in alts] == [("JSWSTEEL", "Steel")]
    out = c(r, t, sector_state="Improving", sector_rel_3m=1.0, alternatives=alts)
    assert out["switch"] == "Consider switching to JSWSTEEL — same industry (Steel), score 60 vs 32 for TATASTEEL."

    assert P.alternatives_for(r, P._universe({"factor_universe": STEEL[:1]}), held={"TATASTEEL"}) == []
    r.pop("industry")
    assert P.alternatives_for(r, P._universe({"factor_universe": STEEL}), held={"TATASTEEL"}) == [], \
        "with no industry known there is no switch, not a sector guess"


def test_pace_digitek_is_never_offered_emudhra():
    """Reported by the owner: Pace Digitek (communication equipment — telecom
    towers) was offered eMudhra (application software — digital signatures).
    Both are Yahoo "Technology"; they are not the same business."""
    uni = [{"symbol": "EMUDHRA", "name": "eMudhra", "sector": "Technology",
            "industry": "Software - Application", "position_score": 70}]
    r, t = row("PACEDIGITK", score=30, weight=5, pnl_pct=-25, sector="Technology")
    r["industry"] = "Communication Equipment"
    assert P.alternatives_for(r, P._universe({"factor_universe": uni}), held={"PACEDIGITK"}) == []
    out = P.plan(_report([r], t), {"factor_universe": uni})
    assert out["actions"][0]["switch"] is None and out["actions"][0]["alternatives"] == []
    assert "EMUDHRA" not in str(out["actions"])


def test_one_classifier_names_both_sides():
    """The market-wide classifier (industry.py) names the holding and the
    candidates alike, and fills in a row that carries no industry of its own."""
    industries = {"PACEDIGITK": "Communication Equipment", "HFCL": "Communication Equipment",
                  "EMUDHRA": "Software - Application"}
    uni = [{"symbol": "HFCL", "name": "HFCL", "sector": "Technology", "position_score": 64},
           {"symbol": "EMUDHRA", "name": "eMudhra", "sector": "Technology", "position_score": 70}]
    r, t = row("PACEDIGITK", score=30, weight=5, pnl_pct=-25, sector="Technology")
    out = P.plan(_report([r], t), {"factor_universe": uni}, industries=industries)
    assert [x["symbol"] for x in out["actions"][0]["alternatives"]] == ["HFCL"]
    assert "same industry (Communication Equipment)" in out["actions"][0]["switch"]


def test_industries_doing_well_where_you_hold_little_come_with_their_best_stocks():
    uni = P._universe({"factor_universe": UNIVERSE})
    report = {
        "sector_momentum": {"sectors": [
            {"sector": "Healthcare", "state": "Leading", "relative": {"3M": 5.5}},
            {"sector": "Financial Services", "state": "Lagging", "relative": {"3M": -2.0}},
        ]},
        "sector_comparison": [
            {"sector": "Healthcare", "weight_pct": 1.0, "benchmark_weight_pct": 7.2},
            {"sector": "Financial Services", "weight_pct": 5.0, "benchmark_weight_pct": 30.4},
        ],
    }
    rot = P.rotation(report, uni, held={"SUNPHARMA"})
    assert [r_["sector"] for r_ in rot] == ["Healthcare"], "a lagging industry is never suggested"
    assert [s["symbol"] for s in rot[0]["stocks"]] == ["CIPLA"], "held and weak names are left out"
    assert "beating the Nifty 50 by 5.5%" in rot[0]["why"]


# ── The whole plan ────────────────────────────────────────────────────────

def _report(rows, total):
    return {"holdings": rows, "total_value": total, "policy": POLICY,
            "sectors": [], "sector_comparison": [], "sector_momentum": {"sectors": []}}


def test_the_plan_orders_exits_first_caps_the_adds_and_counts_the_money():
    total = 1_000_000
    rows = []
    for i, (score, weight) in enumerate([(28, 5), (66, 3), (67, 3), (68, 3), (69, 3), (57, 20)]):
        r, _ = row(f"S{i}", score=score, weight=weight, qty=10, price=weight * total / 100 / 10, total=total)
        rows.append(r)
    plan = P.plan(_report(rows, total), {"factor_universe": []})
    acts = [a["action"] for a in plan["actions"]]
    assert acts[0] == "EXIT"
    assert acts.count("ADD") == P.MAX_ADDS == 3
    assert [a["symbol"] for a in plan["actions"] if a["action"] == "ADD"] == ["S4", "S3", "S2"], "strongest first"
    assert plan["counts"]["EXIT"] == 1 and plan["counts"]["TRIM"] == 1
    assert plan["freed"] > 0 and plan["needed"] > 0
    assert "need a move" in plan["headline"]


def test_the_plan_says_plainly_that_it_is_not_registered_advice():
    r, t = row()
    plan = P.plan(_report([r], t), None)
    assert "not registered with SEBI" in plan["disclaimer"]
    assert "rules" in plan["method"].lower() or "exit" in plan["method"].lower()


def test_nothing_to_do_says_so():
    r, t = row(score=57, weight=9)
    assert P.plan(_report([r], t), None)["headline"].startswith("Hold everything")


def test_the_report_carries_the_plan():
    from portfolio import build_report
    rows = []
    for sym, score, qty, price, buy, sector in [("AAA", 70, 10, 100.0, 90.0, "Technology"),
                                                ("BBB", 30, 10, 100.0, 120.0, "Energy")]:
        rows.append({"symbol": sym, "name": sym, "qty": qty, "price": price, "buy_price": buy,
                     "value": qty * price, "cost": qty * buy, "sector": sector, "composite": score,
                     "error": None, "warnings": []})
    rep = build_report(rows, {"factor_universe": []}, POLICY)
    plan = rep["action_plan"]
    assert plan["available"] is True
    assert {a["symbol"]: a["action"] for a in plan["actions"]}["BBB"] == "EXIT"


# ── Every holding gets a score ────────────────────────────────────────────

def test_a_holding_outside_the_scan_is_scored_on_request(monkeypatch):
    import main
    from conftest import ohlcv, ramp
    hist = ohlcv(ramp(100, 150, 300))
    monkeypatch.setattr(main, "resolve", lambda s: ("NEWCO.NS", None, hist))
    monkeypatch.setattr(main, "fundamentals", lambda sym, t: (None, None, None, {"sector": "Technology", "industry": "Information Technology Services"}))
    seen = {}

    def fake_v4(sym, t, h, info, wait=None):
        seen["wait"] = wait
        return {"position": {"final_score": 61.5}, "cohort": {"basis": "on_request"}}
    monkeypatch.setattr(main, "_v4_for", fake_v4)
    row_ = main._analyse_holding({"symbol": "NEWCO", "qty": 5, "buy_price": 90.0})
    assert row_["composite"] == 61.5
    assert row_["score_source"].startswith("ranked on request")
    assert seen["wait"] == 4, "a portfolio must not spend its deadline waiting on one score"
    assert row_["industry"] == "Information Technology Services", "switches match on it"


def test_a_percentile_is_only_quoted_against_a_real_cohort():
    r, t = row(score=29, weight=6)
    small = c(r, t, cohort_scores=[40, 50, 60])
    assert "companies we track" not in small["why"] and "%" not in small["reasons"][0]
    big = c(r, t, cohort_scores=[30 + i * 0.2 for i in range(200)])
    assert "among the very weakest of the companies we track" in big["why"]
    assert "100%" not in big["why"]
