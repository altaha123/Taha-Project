"""
The Delivery trends scan: where delivery is unusual now.

What these guard, in order of how badly each would mislead a reader:

  1. A SPLIT IS NOT A SPIKE. On the ex-date of a 1:5 split the share count
     traded goes up fivefold and nothing has happened. The scan measures
     delivered RUPEES for exactly this reason, and a name whose unadjusted
     price shows the step is left out and counted, because its "price change"
     would be an artefact too.
  2. A VOLUME BURST IS NOT DELIVERY. Twice the rupees delivered on four times
     the volume is a day traders had, with a SMALLER share kept. The delivered
     share has to hold at or above the stock's own average.
  3. ONE LOUD SESSION IS NOT A WEEK. The week list is the median day of five,
     so a single block deal cannot put a name on it.
  4. "Quiet" means the price did not move. A stock up 20% on rising delivery
     is a rally, and belongs on a different list.
  5. Every comparison is a stock against itself — the planted names must come
     back with the arithmetic a reader could redo from the exchange file.
  6. A young store explains itself instead of returning an empty page.
"""
import numpy as np
import pandas as pd
import pytest

import special


@pytest.fixture(autouse=True)
def no_background_builder(monkeypatch):
    monkeypatch.setattr(special, "ensure_building", lambda *a, **k: None)


DAYS = pd.bdate_range(end="2026-11-19", periods=120)
FLAT = [f"FLAT{i:02d}" for i in range(30)]
PLANTED = ["SPIKEUP", "SPIKEDN", "CHURN", "SPLIT", "WEEKLY", "ONEDAY",
           "QUIET", "RALLY", "TINY", "GOLDBEES"]


def build_panel():
    """Every stock: 1,000,000 shares a day at Rs 500, 40% delivered — Rs 50 cr
    traded and Rs 20 cr delivered, every session, until a test says otherwise.
    Flat on purpose: any multiple a test asserts is then exact arithmetic."""
    syms = FLAT + PLANTED
    mk = lambda v: pd.DataFrame(float(v), index=DAYS, columns=syms)
    P = {"deliv": mk(40), "qty": mk(1_000_000), "vwap": mk(500), "close": mk(500),
         "high": mk(505), "low": mk(495), "schema": special.WIDE_SCHEMA}

    def put(field, sym, rows, value):
        P[field].iloc[rows, P[field].columns.get_loc(sym)] = value

    # Rs 20 cr usual -> 3,000,000 x 500 x 60% = Rs 90 cr: 4.5 times, on a rise.
    put("qty", "SPIKEUP", -1, 3_000_000); put("deliv", "SPIKEUP", -1, 60)
    put("close", "SPIKEUP", -1, 515); put("high", "SPIKEUP", -1, 516)
    # The same on a fall.
    put("qty", "SPIKEDN", -1, 3_000_000); put("deliv", "SPIKEDN", -1, 60)
    put("close", "SPIKEDN", -1, 480); put("low", "SPIKEDN", -1, 478)
    # Four times the volume, HALF the share: Rs 40 cr delivered is 2 times,
    # but 20% delivered against a usual 40% is churn.
    put("qty", "CHURN", -1, 4_000_000); put("deliv", "CHURN", -1, 20)
    put("close", "CHURN", -1, 510)
    # A 1:5 split three sessions ago: five times the shares at a fifth of the
    # price. Rupees are unchanged; the price series has a -80% step in it.
    put("qty", "SPLIT", slice(-3, None), 5_000_000)
    for f in ("vwap", "close", "high", "low"):
        put(f, "SPLIT", slice(-3, None), P[f]["SPLIT"].iloc[-4] / 5)
    # Four of the last five sessions at twice the rupees, share up.
    put("qty", "WEEKLY", slice(-5, -1), 1_600_000); put("deliv", "WEEKLY", slice(-5, -1), 50)
    put("close", "WEEKLY", slice(-5, None), 520)
    # One enormous session inside the week and nothing else.
    put("qty", "ONEDAY", -3, 9_000_000); put("deliv", "ONEDAY", -3, 70)
    # A month at 52% delivered against 40%, on more rupees, price unmoved.
    put("deliv", "QUIET", slice(-20, None), 52); put("qty", "QUIET", slice(-20, None), 1_200_000)
    # The same month of delivery, but the price ran 20%.
    put("deliv", "RALLY", slice(-20, None), 52); put("qty", "RALLY", slice(-20, None), 1_200_000)
    put("close", "RALLY", slice(-20, None), np.linspace(505, 600, 20))
    # A spike in a stock that trades Rs 1 cr a day.
    put("qty", "TINY", slice(None), 20_000)
    put("qty", "TINY", -1, 100_000); put("deliv", "TINY", -1, 80); put("close", "TINY", -1, 520)
    # A fund unit with the same spike as SPIKEUP.
    put("qty", "GOLDBEES", -1, 3_000_000); put("deliv", "GOLDBEES", -1, 60)
    put("close", "GOLDBEES", -1, 515)
    return {k: (v.astype("float32") if isinstance(v, pd.DataFrame) else v)
            for k, v in P.items()}


@pytest.fixture
def panel(monkeypatch):
    P = build_panel()
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    monkeypatch.setattr(special, "_company_names", lambda: {})
    return P


def syms(view):
    return [r["symbol"] for r in view["rows"]]


def row(view, sym):
    return next(r for r in view["rows"] if r["symbol"] == sym)


def test_a_spike_is_reported_with_arithmetic_a_reader_can_redo(panel):
    out = special.delivery_trends(min_turnover_cr=10)
    assert out["available"] is True and out["as_of"] == "2026-11-19"

    r = row(out["views"]["today"], "SPIKEUP")
    assert r["delivered_cr"] == 90.0          # 3,000,000 x Rs 500 x 60%
    assert r["usual_cr"] == 20.0              # 1,000,000 x Rs 500 x 40%
    assert r["mult"] == 4.5
    assert r["deliv_pct"] == 60.0 and r["usual_pct"] == 40.0 and r["pp"] == 20.0
    assert r["chg_pct"] == 3.0                # 500 -> 515
    assert r["close_loc"] == pytest.approx(20 / 21, abs=0.01)   # closed near the high
    assert len(r["spark_cr"]) == len(out["spark_dates"]) == 20
    assert r["spark_cr"][-1] == 90.0 and r["spark_cr"][0] == 20.0


def test_direction_is_the_price_not_a_guess(panel):
    today = special.delivery_trends()["views"]["today"]
    assert row(today, "SPIKEUP")["chg_pct"] > 0
    assert row(today, "SPIKEDN")["chg_pct"] == -4.0
    # The counts cover the whole list, not the page of it that was returned.
    assert today["up"] == 1 and today["down"] == 1 and today["total"] == 2


def test_a_volume_burst_with_a_smaller_share_is_not_a_delivery_spike(panel):
    assert "CHURN" not in syms(special.delivery_trends()["views"]["today"])


def test_a_split_is_neither_a_spike_nor_a_fall(panel):
    out = special.delivery_trends()
    for v in out["views"].values():
        assert "SPLIT" not in syms(v)
    assert out["excluded_corporate_action"] == 1


def test_the_week_needs_most_of_the_week(panel):
    week = special.delivery_trends()["views"]["week"]
    r = row(week, "WEEKLY")
    assert r["delivered_cr"] == 40.0 and r["mult"] == 2.0   # 1.6m x 500 x 50%
    assert r["days_above"] == 4
    assert r["week_cr"] == 180.0                            # four at 40, one at 20
    assert r["chg_pct"] == 4.0
    # Rs 315 cr in one session, and an ordinary day either side of it.
    assert "ONEDAY" not in syms(week)


def test_quiet_means_the_price_did_not_move(panel):
    quiet = special.delivery_trends()["views"]["quiet"]
    r = row(quiet, "QUIET")
    assert r["deliv_pct"] == 52.0 and r["usual_pct"] == 40.0 and r["pp"] == 12.0
    assert r["chg_pct"] == 0.0
    assert "RALLY" not in syms(quiet)


def test_the_liquidity_floor_is_measured_before_the_spike(panel):
    # TINY trades Rs 1 cr on a usual day and Rs 5 cr today. A floor measured
    # on today's turnover would let the spike qualify itself.
    assert "TINY" not in syms(special.delivery_trends(min_turnover_cr=2)["views"]["today"])
    # And the floor a reader picks is honoured, and clamped to something sane.
    assert special.delivery_trends(min_turnover_cr=60)["views"]["today"]["rows"] == []
    assert special.delivery_trends(min_turnover_cr="rubbish")["min_turnover_cr"] == 10.0
    assert special.delivery_trends(min_turnover_cr=-5)["min_turnover_cr"] == 2.0


def test_a_fund_unit_is_not_a_company(panel):
    out = special.delivery_trends()
    for v in out["views"].values():
        assert "GOLDBEES" not in syms(v)


def test_the_market_line_is_the_sum_of_its_stocks(panel):
    m = special.delivery_trends()["market"]
    # Redone here from the panel, the long way, for the latest session: every
    # company's rupees delivered over every company's rupees traded.
    cos = [c for c in panel["qty"].columns if c != "GOLDBEES"]
    traded = (panel["qty"][cos].iloc[-1].astype(float) * panel["vwap"][cos].iloc[-1]) / 1e7
    delivered = traded * panel["deliv"][cos].iloc[-1] / 100
    assert m["stocks"] == 39
    assert m["delivered_cr"] == round(float(delivered.sum()))
    assert m["share_pct"] == pytest.approx(float(delivered.sum() / traded.sum() * 100), abs=0.01)
    # SPIKEUP and SPIKEDN alone add Rs 140 cr to an ordinary session.
    assert m["delivered_cr"] > m["usual_cr"] and m["mult"] > 1
    assert m["pp"] == pytest.approx(m["share_pct"] - m["usual_share_pct"], abs=0.011)


def test_sectors_come_from_the_industry_file_and_need_enough_members(panel, monkeypatch):
    names = {s: (s.title() + " Ltd.", "Capital Goods") for s in FLAT[:6]}
    names.update({s: (s, "Chemicals") for s in FLAT[6:8]})          # only two
    names["WEEKLY"] = ("Weekly Ltd.", "Capital Goods")
    monkeypatch.setattr(special, "_company_names", lambda: names)
    out = special.delivery_trends()
    assert [s["industry"] for s in out["sectors"]] == ["Capital Goods"]
    s = out["sectors"][0]
    assert s["members"] == 7
    # Six flat names at Rs 20 cr and WEEKLY at 40 on the median day: 160 / 140.
    assert s["delivered_cr"] == 160 and s["usual_cr"] == 140
    assert s["mult"] == pytest.approx(1.14, abs=0.01)
    assert row(out["views"]["week"], "WEEKLY")["name"] == "Weekly Ltd."


def test_a_missing_reading_is_not_a_zero_and_never_serialises_as_nan(panel):
    import json
    panel["qty"].iloc[-1, panel["qty"].columns.get_loc("SPIKEUP")] = np.nan
    panel["deliv"].iloc[-8, panel["deliv"].columns.get_loc("SPIKEDN")] = np.nan
    out = special.delivery_trends()
    assert "SPIKEUP" not in syms(out["views"]["today"])     # no reading, no row
    r = row(out["views"]["today"], "SPIKEDN")
    assert r["spark_cr"][-8] is None and r["spark_pct"][-8] is None
    json.dumps(out, allow_nan=False)                        # raises on NaN


def test_a_young_store_says_so(monkeypatch):
    P = build_panel()
    short = {k: (v.tail(10) if isinstance(v, pd.DataFrame) else v) for k, v in P.items()}
    monkeypatch.setattr(special, "_load_cache", lambda: short)
    monkeypatch.setattr(special, "status", lambda: {"cached_sessions": 10, "build": {}})
    out = special.delivery_trends()
    assert out["available"] is False and out["building"] is True
    assert out["sessions"] == 10 and out["needed"] == special.TRENDS_MIN_SESSIONS


def test_the_month_view_waits_for_its_history(monkeypatch):
    P = build_panel()
    mid = {k: (v.tail(40) if isinstance(v, pd.DataFrame) else v) for k, v in P.items()}
    monkeypatch.setattr(special, "_load_cache", lambda: mid)
    monkeypatch.setattr(special, "_company_names", lambda: {})
    out = special.delivery_trends()
    assert "SPIKEUP" in syms(out["views"]["today"])         # today still works
    assert out["views"]["quiet"]["unavailable"] is True
    assert "60 sessions" in out["views"]["quiet"]["rule"]
