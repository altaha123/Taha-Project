"""
Scoring a company the universe scan did not analyse.

The claim score_on_request.py makes is narrow and checkable: a company outside
the cohort gets *the score it would have had inside the scan*. Not a similar
score, not an estimate — the same number, because it is ranked by the same
function against the same peers on the same date. The first test here is that
claim, measured: take a company out of a cohort, score it on request against
the rest, and compare with the score the full cohort gave it.

The rest guard what makes that claim safe to rely on: the cohort is never
changed by being scored against, prices after the cohort's date are never
seen, a cohort member is never re-ranked, a new scan invalidates every cached
score, a slow first request answers honestly instead of hanging the page, and
a company the scan would have refused (too little history) is refused here.
"""
import copy
import threading
import time

import numpy as np
import pandas as pd
import pytest

import factors as F
import multifactor as M
import profiles as P
import score_on_request as S
from conftest import ohlcv, ramp

ASOF = "2026-09-29"


def cohort(n=41, seed=7, as_of=ASOF):
    """A scanned cohort with real spread in every factor and two sectors, so
    that sector, model, size and universe pools all come into play."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        tech = i % 2 == 0
        rows.append({
            "symbol": f"S{i:03d}",
            "sector": "Technology" if tech else "Industrials",
            "industry": "Software services" if tech else "Engineering & Construction",
            "market_cap": float(rng.lognormal(24, 1.2)),
            "trailing_eps": float(rng.normal(20, 8)),
            "factors": {k: float(rng.normal(0, 10)) for k in F.SPEC},
            "data_quality": {"as_of": as_of, "period_age_days": 91, "history_quarters": 16,
                             "source_valid": True},
        })
    return rows


def payload(rows, scanned_at="29 Sep 2026, 04:13"):
    return {"scanned_at": scanned_at, "factor_universe": rows}


# ── The claim ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pick", [0, 17, 40])
def test_scored_on_request_equals_the_score_it_would_have_had_in_the_scan(pick):
    rows = cohort()
    x = rows[pick]
    inside = next(r for r in M.rank(rows, "position")["rows"]
                  if r["symbol"] == x["symbol"])["altaha_score_v4"]
    outside = S.score_against([r for r in rows if r is not x], x)

    for hz in P.V4_WEIGHTS:
        assert outside[hz]["final_score"] == pytest.approx(inside[hz]["final_score"])
        assert outside[hz]["raw_score"] == pytest.approx(inside[hz]["raw_score"])
        assert outside[hz]["confidence"] == pytest.approx(inside[hz]["confidence"])
    got = [(e["factor"], e["percentile"], e["peer_group"], e["peer_count"]) for e in outside["factor_ledger"]]
    want = [(e["factor"], e["percentile"], e["peer_group"], e["peer_count"]) for e in inside["factor_ledger"]]
    assert got == want
    assert outside["business_model"] == inside["business_model"]
    assert outside["market_cap_bucket"] == inside["market_cap_bucket"]


def test_the_cohort_is_never_modified_by_being_scored_against():
    rows = cohort()
    before = copy.deepcopy(rows)
    newcomer = cohort(1, seed=99)[0] | {"symbol": "NEWCO"}
    S.score_against(rows, newcomer)
    assert rows == before


def test_a_cohort_member_is_never_re_ranked_on_request():
    rows = cohort()
    with pytest.raises(ValueError):
        S.score_against(rows, dict(rows[3]))


# ── The inputs ─────────────────────────────────────────────────────────────

def _history(end, n=300, tail=None):
    closes = ramp(100, 180, n) + (tail or [])
    return ohlcv(closes, end=pd.Timestamp(end) + pd.offsets.BDay(len(tail or [])))


def test_prices_after_the_cohort_date_are_never_seen():
    # The same company, once as it stood on the cohort's date and once with
    # a month of wild prices after it. Peers were measured on that date, so
    # the month after must change nothing.
    on_date = _history(ASOF)
    with_later = _history(ASOF, tail=[400, 20, 900, 5] * 5)
    assert with_later.index[-1] > pd.Timestamp(ASOF)
    a = S.build_row("NEWCO.NS", on_date, [], {}, ASOF)
    b = S.build_row("NEWCO.NS", with_later, [], {}, ASOF)
    assert a["factors"] == b["factors"]
    assert a["factors"]["momentum_12_1"] is not None, "enough history to measure every price factor"
    assert a["data_quality"]["as_of"] == ASOF


def test_the_row_carries_what_the_ranker_classifies_on():
    info = {"sector": "Energy", "industry": "Oil & Gas Refining & Marketing",
            "marketCap": 1.6e13, "trailingEps": 52.1}
    row = S.build_row("RELIANCE.NS", _history(ASOF), [], info, ASOF)
    assert row["symbol"] == "RELIANCE"
    assert (row["sector"], row["industry"], row["market_cap"], row["trailing_eps"]) == \
        ("Energy", "Oil & Gas Refining & Marketing", 1.6e13, 52.1)
    assert set(F.SPEC) <= set(row["factors"])


def test_the_history_floor_is_the_scans():
    import scan
    assert S.MIN_ROWS == scan.MIN_ROWS


# ── The cohort ─────────────────────────────────────────────────────────────

def test_no_usable_cohort_means_no_on_request_score():
    assert S.cohort_of(None) is None
    assert S.cohort_of({"factor_universe": cohort(M.MIN_PEERS - 1)}) is None
    legacy = [{k: v for k, v in r.items() if k != "factors"} for r in cohort()]
    assert S.cohort_of({"factor_universe": legacy}) is None


def test_the_cohort_key_changes_with_every_scan():
    rows = cohort()
    a = S.cohort_of(payload(rows, "28 Sep 2026, 04:10"))
    b = S.cohort_of(payload(rows, "29 Sep 2026, 04:13"))
    assert a[1] != b[1]
    assert a[2] == ASOF and len(a[0]) == len(rows)


# ── The scorer: cache, single flight, honest waiting ───────────────────────

class Fetch:
    def __init__(self, hist=None, gate=None, fail=False):
        self.calls, self.gate, self.fail = 0, gate, fail
        self.hist = hist if hist is not None else _history(ASOF)

    def __call__(self):
        self.calls += 1
        if self.gate is not None:
            assert self.gate.wait(5)
        if self.fail:
            raise RuntimeError("provider down")
        return self.hist, [], {"sector": "Technology", "industry": "Software services",
                               "marketCap": 5e10, "trailingEps": 12.0}


def test_a_us_listing_is_not_ranked_against_nse_peers():
    fetch = Fetch()
    out = S.OnRequestScorer().score("AAPL", payload(cohort()), fetch)
    assert out["available"] is False and out["reason"] == "no_cohort_for_market"
    assert fetch.calls == 0


def test_no_scan_yet_says_so():
    out = S.OnRequestScorer().score("NEWCO.NS", {}, Fetch())
    assert out["reason"] == "no_cohort"


def test_scored_once_per_scan_then_served_from_cache():
    scorer, fetch = S.OnRequestScorer(), Fetch()
    p = payload(cohort())
    first = scorer.score("NEWCO.NS", p, fetch)
    again = scorer.score("NEWCO.NS", p, fetch)
    assert "position" in first and first is again
    assert fetch.calls == 1
    assert first["cohort"]["basis"] == "on_request"
    assert first["cohort"]["peers"] == 41 and first["cohort"]["as_of"] == ASOF
    # A new scan is a new peer group: the old score is not reused.
    scorer.score("NEWCO.NS", payload(cohort(), "30 Sep 2026, 04:11"), fetch)
    assert fetch.calls == 2


def test_a_slow_first_score_answers_pending_and_finishes_behind_the_response():
    gate = threading.Event()
    scorer, fetch = S.OnRequestScorer(wait=0.05), Fetch(gate=gate)
    p = payload(cohort())
    one = scorer.score("NEWCO.NS", p, fetch)
    two = scorer.score("NEWCO.NS", p, fetch)
    assert one["pending"] and two["pending"] and one["reason"] == "pending"
    gate.set()
    key = S.cohort_of(p)[1]
    deadline = time.time() + 5
    while scorer.cached("NEWCO", key) is None and time.time() < deadline:
        time.sleep(0.01)
    done = scorer.score("NEWCO.NS", p, fetch)
    assert "position" in done
    assert fetch.calls == 1, "two readers during the first score share one computation"


def test_a_failed_fetch_is_retried_not_remembered():
    scorer, fetch = S.OnRequestScorer(), Fetch(fail=True)
    p = payload(cohort())
    assert scorer.score("NEWCO.NS", p, fetch)["reason"] == "fetch_failed"
    assert scorer.score("NEWCO.NS", p, fetch)["reason"] == "fetch_failed"
    assert fetch.calls == 2


def test_too_little_history_is_refused_as_the_scan_would():
    short = ohlcv(ramp(100, 120, S.MIN_ROWS - 1), end=pd.Timestamp(ASOF))
    out = S.OnRequestScorer().score("NEWLIST.NS", payload(cohort()), Fetch(hist=short))
    assert out["available"] is False and out["reason"] == "insufficient_data"


def test_the_cache_is_bounded():
    scorer = S.OnRequestScorer(cache_max=3)
    p = payload(cohort())
    for i in range(5):
        scorer.score(f"NEW{i}.NS", p, Fetch())
    assert len(scorer._cache) == 3


# ── Through /analyze ───────────────────────────────────────────────────────

@pytest.fixture
def main_mod(monkeypatch):
    import main
    before = main._state.get("payload")
    monkeypatch.setattr(main, "_on_request", S.OnRequestScorer())
    hist = ohlcv(ramp(100, 180, 300))
    info = {"sector": "Technology", "industry": "Software services", "marketCap": 5e10,
            "trailingEps": 12.0, "currency": "INR", "longName": "New Company Ltd",
            "dividendYield": 0.49}

    def resolve(ticker):
        t = ticker.upper()
        return (t if "." in t or t == "AAPL" else t + ".NS"), None, hist

    monkeypatch.setattr(main, "resolve", resolve)
    monkeypatch.setattr(main, "fundamentals", lambda sym, t: (None, None, None, dict(info)))
    monkeypatch.setattr(main, "shareholding", lambda t: {"published": False})
    if main.xbrl_source is not None:
        monkeypatch.setattr(main.xbrl_source, "scoring_statements", lambda s, *a, **k: [])
    # The cohort as the scan stores it: rows that have been through rank(),
    # carrying their own v4 block and per-horizon scores.
    today = pd.Timestamp.today().date().isoformat()
    main._state["payload"] = payload(M.rank(cohort(as_of=today), "position")["rows"])
    yield main
    main._state["payload"] = before


def test_analyze_scores_a_company_outside_the_cohort(main_mod):
    d = main_mod.analyze("NEWCO")
    assert d["scoring"]["score"] is not None
    assert d["altaha_score_v4"]["cohort"]["basis"] == "on_request"
    assert "ranked on request" in d["scoring"]["basis"]
    assert "ranked on request" in d["scoring"]["cohort_note"]
    assert d["horizons"] and all("ranked on request" in h["basis"] for h in d["horizons"].values())
    assert d["percentile"] is not None


def test_analyze_keeps_a_members_scan_score(main_mod):
    ranked = main_mod._state["payload"]["factor_universe"]
    member = ranked[5]["symbol"]
    d = main_mod.analyze(member)
    assert d["scoring"]["score"] == pytest.approx(ranked[5]["altaha_score_v4"]["position"]["final_score"])
    assert d["altaha_score_v4"]["cohort"]["basis"] == "scan"
    assert "ranked on request" not in d["scoring"]["basis"]
    # The shared cached row was not given a cohort block by being read.
    assert "cohort" not in ranked[5]["altaha_score_v4"]


def test_analyze_names_why_a_us_listing_has_no_score(main_mod):
    d = main_mod.analyze("AAPL")
    assert d["scoring"]["score"] is None
    assert d["scoring"]["label"] == "NOT RANKED"
    assert "NSE peers" in d["scoring"]["summary"]


# ── Dividend yield ─────────────────────────────────────────────────────────

from data_source import dividend_yield_pct


def test_dividend_yield_is_per_share_over_price():
    # Live Yahoo fields for RELIANCE on 29 Sep 2026.
    info = {"dividendYield": 0.49, "trailingAnnualDividendYield": 0.0,
            "dividendRate": 6.0, "trailingAnnualDividendRate": 0.0, "currentPrice": 1192.4}
    assert dividend_yield_pct(info) == pytest.approx(0.5)
    assert dividend_yield_pct(info, price=1200) == pytest.approx(0.5)


def test_a_sub_one_percent_yield_is_never_multiplied_by_a_hundred():
    # The old rule read anything at or below 1 as a fraction: 0.49% became 49%.
    assert dividend_yield_pct({"dividendYield": 0.49}) == pytest.approx(0.49)
    assert dividend_yield_pct({"dividendYield": 3.12}) == pytest.approx(3.12)


def test_dividend_yield_absent_or_nonsense_is_none():
    assert dividend_yield_pct({}) is None
    assert dividend_yield_pct(None) is None
    assert dividend_yield_pct({"dividendYield": "n/a"}) is None
    assert dividend_yield_pct({"dividendYield": float("nan")}) is None
    assert dividend_yield_pct({"dividendYield": -1}) is None
    # No dividend is 0%, not unknown.
    assert dividend_yield_pct({"dividendYield": 0}) == 0


def test_header_ratios_carry_the_corrected_yield(main_mod):
    d = main_mod.analyze("NEWCO")
    assert d["ratios"]["dividend_yield"] == pytest.approx(0.49)
