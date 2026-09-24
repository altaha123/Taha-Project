"""
The Lens engine: one company's metrics against one lens's rules.

The failures that matter are quiet ones: a missing figure counted as a fail
(or worse, a pass), a company judged on one rule of four and shown as meeting
a lens, or a near miss that is really two misses. Each has a test here.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lens_engine as E  # noqa: E402

LENS = {
    "id": "t", "name": "Test", "originator": "Tests", "idea": "Four rules.",
    "min_coverage": 0.75,
    "rules": [
        {"field": "roce", "operator": ">", "threshold": 20, "lookback_years": 1, "label": "ROCE > 20%"},
        {"field": "revenue_cagr", "operator": ">", "threshold": 15, "lookback_years": 5, "label": "5y CAGR > 15%"},
        {"field": "eps_growth", "operator": "between", "threshold": [20, 50], "lookback_years": 1, "label": "EPS 20–50%"},
        {"field": "size_band", "operator": "in", "threshold": ["small", "mid"], "lookback_years": 0, "label": "Small or mid"},
    ],
}


def metrics(**kw):
    keys = {"roce": "roce@1", "cagr": "revenue_cagr@5", "eps": "eps_growth@1", "size": "size_band@0"}
    return {keys[k]: v for k, v in kw.items()}


def results(res):
    return [r["result"] for r in res["rules"]]


def test_every_rule_met_is_a_pass_and_carries_the_values():
    res = E.evaluate_lens(LENS, metrics(roce=25, cagr={"value": 18.2, "display": "18.2%"},
                                        eps=30, size="mid"))
    assert res["status"] == "pass"
    assert (res["passed"], res["failed"], res["na"], res["total"]) == (4, 0, 0, 4)
    assert res["coverage"] == 1.0
    assert res["rules"][1]["value"] == 18.2 and res["rules"][1]["display"] == "18.2%"


def test_two_misses_are_a_fail():
    res = E.evaluate_lens(LENS, metrics(roce=12, cagr=9, eps=30, size="small"))
    assert results(res) == ["fail", "fail", "pass", "pass"]
    assert res["status"] == "fail"


def test_exactly_one_miss_is_a_near_miss():
    res = E.evaluate_lens(LENS, metrics(roce=25, cagr=18, eps=62, size="small"))
    assert results(res) == ["pass", "pass", "fail", "pass"]
    assert res["status"] == "near_miss"


def test_a_one_rule_lens_has_no_near_misses():
    lens = dict(LENS, rules=LENS["rules"][:1])
    assert E.evaluate_lens(lens, metrics(roce=12))["status"] == "fail"
    assert E.evaluate_lens(lens, metrics(roce=25))["status"] == "pass"


def test_a_missing_value_is_na_never_a_fail_or_a_pass():
    res = E.evaluate_lens(LENS, metrics(roce=25, cagr=None, eps=30, size="mid"))
    assert results(res) == ["pass", "na", "pass", "pass"]
    assert res["rules"][1]["note"]
    assert (res["passed"], res["failed"], res["na"]) == (3, 0, 1)


def test_coverage_at_the_threshold_is_judged():
    # 3 of 4 judged is exactly 0.75: judged, and all three passed.
    res = E.evaluate_lens(LENS, metrics(roce=25, eps=30, size="mid"))
    assert res["coverage"] == 0.75
    assert res["status"] == "pass"


def test_coverage_below_the_threshold_is_insufficient_whatever_was_judged():
    # 2 of 4 judged. Both passed, and it is still not shown as meeting the lens.
    res = E.evaluate_lens(LENS, metrics(roce=25, cagr=18))
    assert res["coverage"] == 0.5
    assert res["status"] == "insufficient"
    # ...and two fails on half the rules is not a "fail" either.
    res = E.evaluate_lens(LENS, metrics(roce=5, cagr=2))
    assert res["status"] == "insufficient"


def test_min_coverage_comes_from_the_lens_then_the_default():
    lens = dict(LENS, min_coverage=0.5)
    assert E.evaluate_lens(lens, metrics(roce=25, cagr=18))["status"] == "pass"
    lens = {k: v for k, v in LENS.items() if k != "min_coverage"}
    assert E.evaluate_lens(lens, metrics(roce=25, cagr=18), 0.5)["status"] == "pass"
    assert E.evaluate_lens(lens, metrics(roce=25, cagr=18))["status"] == "insufficient"


def test_a_metric_can_decide_a_fail_without_a_value():
    m = metrics(roce=25, cagr=18, eps=30, size="mid")
    m["eps_growth@1"] = {"value": None, "fail": "EPS moved from a profit to a loss"}
    res = E.evaluate_lens(LENS, m)
    assert res["rules"][2]["result"] == "fail"
    assert res["rules"][2]["note"] == "EPS moved from a profit to a loss"
    assert res["status"] == "near_miss"


@pytest.mark.parametrize("op,value,threshold,expected", [
    (">", 20.0001, 20, True), (">", 20, 20, False), (">=", 20, 20, True),
    ("<", -2.1, -2, True), ("<=", 0, 0, True), ("==", 0.0, 0, True), ("==", 0.01, 0, False),
    ("between", 20, [20, 50], True), ("between", 50, [20, 50], True), ("between", 50.1, [20, 50], False),
    ("in", "mid", ["small", "mid"], True), ("in", "large", ["small", "mid"], False),
    ("abs_lte", -1.9, 2, True), ("abs_lte", 2.1, 2, False),
    (">", None, 20, None), (">", float("nan"), 20, None), (">", "n/a", 20, None), (">", True, 0, None),
])
def test_operators(op, value, threshold, expected):
    assert E.compare(value, op, threshold) is expected


def test_the_shipped_config_is_valid_and_every_field_is_computed():
    import lens_metrics
    cfg = E.load_config()
    assert len(cfg["lenses"]) == 10
    fields = {r["field"] for l in cfg["lenses"] for r in l["rules"]}
    assert fields <= lens_metrics.fields_known()
    live = {l["id"] for l in cfg["lenses"] if l.get("status", "live") == "live"}
    assert live == {"gorilla", "tenbagger", "qglp", "akre", "nomad", "cannibal", "owner"}
    for l in cfg["lenses"]:
        if l["status"] == "coming_soon":
            assert l["coming_soon_reason"]


@pytest.mark.parametrize("bad", [
    {"operator": "~"},
    {"operator": "between", "threshold": 5},
    {"operator": "in", "threshold": "small"},
    {"label": ""},
])
def test_a_bad_config_edit_is_refused(bad):
    lens = json.loads(json.dumps(LENS))
    lens["rules"][0].update(bad)
    with pytest.raises(ValueError):
        E.validate({"lenses": [lens]})


def test_duplicate_ids_are_refused():
    with pytest.raises(ValueError):
        E.validate({"lenses": [LENS, LENS]})


def test_banned_words_do_not_appear_in_lens_copy():
    text = (Path(E.CONFIG_PATH).read_text(encoding="utf-8")).lower()
    for word in ("buy", "sell", "target", "recommend", "top picks", "best stocks",
                 "should", "opportunity"):
        assert word not in text, word
