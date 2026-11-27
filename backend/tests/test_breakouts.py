"""
Intraday breakout alerts (breakouts.py), the loop that carries them
(intraday.py) and the Telegram messages they send (alerts.py).

What matters is the definition holding: a level crossed minutes ago on a
burst of volume fires once, with a stop and a target; a stock that gapped
through, crossed on thin volume, or ran too far without its volume does
not; and the day's record counts every trade, not only the ones that
reached a stop or a target.
"""
import datetime as dt
import importlib.util
import os
import types

import numpy as np
import pandas as pd
import pytest

import alerts
import breakouts as bo
import intraday

IST = bo.IST
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = dt.date(2026, 11, 17)          # a Tuesday


def at(h, m, s=0):
    return dt.datetime(DAY.year, DAY.month, DAY.day, h, m, s, tzinfo=IST)


def frame(closes, volume=None, end="2026-11-16", spread=0.01):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(end=pd.Timestamp(end), periods=len(closes), freq="B")
    c = pd.Series(closes, index=idx)
    v = np.full(len(closes), 3_000_000.0) if volume is None else np.asarray(volume, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread),
                         "Close": c, "Volume": v}, index=idx)


def sideways(n=80, lo=100.0, hi=110.0, period=20):
    """A range that touches its top and bottom again and again."""
    t = np.arange(n)
    return list(lo + (hi - lo) * (0.5 + 0.5 * np.sin(2 * np.pi * t / period)))


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bo, "FEED_FILE", str(tmp_path / "feed.json"))
    monkeypatch.setattr(bo, "DAY_FILE", str(tmp_path / "breakout_day.npz"), raising=False)
    monkeypatch.setattr(bo, "PROFILE_FILE", str(tmp_path / "bo_vol_profiles.json"), raising=False)
    # A test that re-arms the day means a fresh day; the checkpoint tests
    # switch it back on for themselves.
    monkeypatch.setattr(bo, "CHECKPOINT_SEC", 0, raising=False)
    monkeypatch.setattr(bo, "_mem", {"feed": None, "day": None})
    # These tests pin down the Classic lane: today's rules, unchanged. The
    # Select lane has its own tests below and in test_alert_live.py.
    monkeypatch.setattr(bo, "LANES", ("classic",), raising=False)
    sent = []
    fake = types.SimpleNamespace(
        send_plain=lambda text: sent.append(text),
        format_levels_ready=alerts.format_levels_ready,
        health=lambda: {"configured": True})
    monkeypatch.setattr(bo, "notify", fake)
    return sent


# ---------------------------------------------------------------------------
# Daily bars -> levels
# ---------------------------------------------------------------------------

def test_read_daily_takes_the_levels_a_day_trade_needs():
    r = bo.read_daily(frame(sideways(80) + [108.0]), drop_partial=False)
    assert r["asof"] == "2026-11-16"
    assert r["pdh"] == pytest.approx(108 * 1.01) and r["pdl"] == pytest.approx(108 * 0.99)
    assert r["hi20"] == pytest.approx(110 * 1.01, rel=1e-3)
    assert r["base"]["sessions"] >= 40 and r["base"]["top"] == pytest.approx(111.1, rel=1e-3)
    assert r["atr_pct"] > 0 and r["turnover_cr"] > 15


def test_a_slow_uptrend_that_fits_the_box_is_not_a_base():
    # Up 15% in a straight line over 60 sessions: inside an 18% box, but the
    # older half never came near the top, so it is a trend, not a range.
    closes = list(np.linspace(80, 100, 200)) + list(np.linspace(100, 115, 60))
    assert bo.read_daily(frame(closes), drop_partial=False)["base"] is None


def test_a_long_wide_consolidation_counts_from_120_sessions():
    closes = sideways(150, 100, 121, period=30)          # about 23% wide
    h, low, _c, _v = bo._arrays(frame(closes))
    base = bo.find_base(h, low, end=len(closes))
    assert base["sessions"] >= bo.LONG_SESSIONS
    assert bo.MAX_WIDTH < base["width"] <= bo.LONG_MAX_WIDTH
    short = closes[-90:]
    h, low, _c, _v = bo._arrays(frame(short))
    assert bo.find_base(h, low, end=len(short)) is None


def test_todays_forming_candle_is_dropped_during_the_session():
    df = frame(sideways(80) + [114.0], end="2026-11-17")
    r = bo.read_daily(df, drop_partial=True, today="2026-11-17")
    assert r["asof"] == "2026-11-16"


def test_levels_at_one_price_are_one_level_named_for_the_biggest():
    # The last bar made the high of the whole base: yesterday's high, the
    # 20-day high and the base top are one price, and the alert says so once.
    r = bo.read_daily(frame(sideways(80) + [110.5]), drop_partial=False)
    up = bo._ladder(r, True)
    assert len(up) == 1 and up[0]["k"] == "BASE"
    assert set(up[0]["also"]) == {"PDH", "HIGH20"}
    assert [x["l"] for x in up] == sorted(x["l"] for x in up)
    dn = bo._ladder(r, False)
    assert [x["l"] for x in dn] == sorted((x["l"] for x in dn), reverse=True)


def test_day_fraction_is_u_shaped_not_a_straight_line():
    assert bo.day_fraction(15) == pytest.approx(0.10)
    assert bo.day_fraction(375) == pytest.approx(1.0)
    assert bo.day_fraction(60) > 60 / 375


# ---------------------------------------------------------------------------
# After the close
# ---------------------------------------------------------------------------

def _reads():
    reads = {"NEAR": bo.read_daily(frame(sideways(80) + [109.5]), drop_partial=False),
             "THIN": bo.read_daily(frame(sideways(80) + [108.0], [50_000.0] * 81), drop_partial=False),
             "PENNY": bo.read_daily(frame([x / 10 for x in sideways(80)] + [10.8]), drop_partial=False)}
    for i in range(4):
        reads[f"Q{i}"] = bo.read_daily(frame(sideways(80) + [104.0]), drop_partial=False)
    return reads


def test_ingest_keeps_only_stocks_a_day_trader_can_get_out_of(monkeypatch, fresh_state):
    monkeypatch.setattr(bo, "MIN_SCAN", 3)
    feed = bo.ingest(_reads(), meta={"NEAR": {"sector": "Power"}}, now=at(17, 5))
    assert "THIN" not in feed["levels"] and "PENNY" not in feed["levels"]
    lv = feed["levels"]["NEAR"]
    assert lv["sector"] == "Power" and lv["up"] and lv["dn"] and lv["base"]["n"] >= 40
    assert feed["near"][0]["symbol"] == "NEAR" and feed["near"][0]["dir"] == "UP"


def test_levels_ready_is_sent_once_and_only_after_a_close(monkeypatch, fresh_state):
    monkeypatch.setattr(bo, "MIN_SCAN", 3)
    reads = _reads()
    for r in reads.values():
        r["asof"] = "2026-11-17"
    bo.ingest(reads, now=at(11, 0))
    assert fresh_state == []                      # mid-session: nothing closed yet
    bo.ingest(reads, now=at(17, 5))
    bo.ingest(reads, now=at(17, 40))
    assert len(fresh_state) == 1 and "ready for tomorrow" in fresh_state[0]


def test_an_overnight_scan_still_says_the_levels_are_ready(monkeypatch, fresh_state):
    # GitHub's 16:50 schedule has been starting the scan around 01:30 IST.
    monkeypatch.setattr(bo, "MIN_SCAN", 3)
    reads = _reads()
    for r in reads.values():
        r["asof"] = "2026-11-17"
    overnight = dt.datetime(2026, 11, 18, 1, 24, tzinfo=IST)
    bo.ingest(reads, now=overnight)
    assert len(fresh_state) == 1 and "ready for tomorrow" in fresh_state[0]
    assert not bo.behind(now=dt.datetime(2026, 11, 18, 8, 45, tzinfo=IST))
    assert bo.behind(now=dt.datetime(2026, 11, 19, 8, 45, tzinfo=IST))


def test_last_close_skips_the_weekend():
    assert bo.last_close(at(16, 0)) == DAY                                   # Tuesday after the close
    assert bo.last_close(at(10, 0)) == dt.date(2026, 11, 16)                 # Tuesday morning: Monday
    monday = dt.datetime(2026, 11, 23, 9, 0, tzinfo=IST)
    assert bo.last_close(monday) == dt.date(2026, 11, 20)                    # Monday morning: Friday


def test_a_small_scan_does_not_replace_the_levels_but_a_rebuild_may(monkeypatch):
    monkeypatch.setattr(bo, "MIN_SCAN", 50)
    assert bo.ingest(_reads()) is None
    frames = {"NEAR": frame(sideways(80) + [109.5])}
    feed = bo.rebuild(["NEAR", "GONE"], lambda s: frames.get(s), now=at(8, 45))
    assert list(feed["levels"]) == ["NEAR"]
    assert bo.usable(now=at(9, 0)) and bo.watch_symbols(now=at(9, 0)) == ["NEAR"]


# ---------------------------------------------------------------------------
# During the session
# ---------------------------------------------------------------------------

def _arm(asof="2026-11-16"):
    """Levels left by Monday's close, traded on Tuesday. ATR 2%, a million
    shares a day."""
    bo._mem["feed"] = {"asof": asof, "levels": {"NEAR": {
        "c": 108.0, "atr": 2.0, "v": 1_000_000, "sector": "Power", "base": {"n": 80, "w": 12.1},
        "up": [{"l": 110.0, "k": "PDH", "s": 2, "also": []},
               {"l": 111.0, "k": "BASE", "s": 4, "also": ["HIGH20"]}],
        "dn": [{"l": 105.0, "k": "PDL", "s": 2, "also": []},
               {"l": 99.0, "k": "BASE_DN", "s": 4, "also": []}]}}}
    bo._mem["day"] = None


def q(px, vol, pc=108.0, opn=108.0, vwap=None, hi=None, lo=None):
    return {"NEAR": {"ltp": px, "volume": vol, "prev_close": pc, "open": opn,
                     "vwap": vwap, "high": hi or px, "low": lo or px}}


def quiet_tape(start, minutes, px=108.5, vol0=150_000, per_pass=1_000, step=20, **kw):
    """Passes every `step` seconds at an ordinary volume. Returns (time, volume)."""
    bo.check_live(q(108.0, 5_000, **kw), now=at(9, 16))          # seen before the window opens
    t, vol = start, vol0
    for _ in range(int(minutes * 60 / step)):
        assert bo.check_live(q(px, vol, **kw), now=t) == []
        t += dt.timedelta(seconds=step)
        vol += per_pass
    return t, vol


def test_a_fresh_cross_on_a_volume_burst_is_a_trade():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    fired = bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)
    assert len(fired) == 1
    a = fired[0]
    assert (a["symbol"], a["kind"], a["direction"]) == ("NEAR", "BO_BASE", "UP")
    assert a["level"] == 111.0 and a["entry"] == 111.3
    # The stop sits just back inside the level; the target is two risks away.
    assert 110.5 < a["stop"] < 111.0
    risk = a["entry"] - a["stop"]
    assert a["t1"] == pytest.approx(a["entry"] + risk, abs=0.02)
    assert a["target"] == pytest.approx(a["entry"] + 2 * risk, abs=0.02)
    assert bo.MIN_RISK <= a["risk_pct"] <= bo.MAX_RISK
    assert a["rvol"] >= bo.SURGE and a["score"] >= bo.MIN_SCORE
    assert a["call"] == "CONSOLIDATION"
    assert "80-day consolidation" in a["why"] and "Exit by 3:15 pm" in a["why"]
    # Once the caller has logged it, the same stock does not fire again.
    assert bo.check_live(q(111.5, vol + 90_000, vwap=109.0),
                         now=t + dt.timedelta(seconds=20), fired={("NEAR", "UP")}) == []


def test_a_cross_on_thin_volume_waits_and_says_why():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(q(111.3, vol + 1_000, vwap=109.0), now=t) == []
    w = bo.status(now=t)["waiting"]
    assert w and w[0]["symbol"] == "NEAR" and "volume" in w[0]["why"]


def test_volume_that_arrives_too_late_is_not_chased():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    for _ in range(40):                                   # 13 minutes over the level, no volume
        assert bo.check_live(q(111.3, vol, vwap=109.0), now=t) == []
        t += dt.timedelta(seconds=20)
        vol += 1_000
    assert bo.check_live(q(111.4, vol + 80_000, vwap=109.0), now=t) == []


def test_a_second_attempt_after_falling_back_is_a_fresh_break():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    for px in (111.3, 111.3, 109.0, 109.0):               # poke, then back inside
        assert bo.check_live(q(px, vol, vwap=109.0), now=t) == []
        t += dt.timedelta(minutes=8)
        vol += 20_000
    for _ in range(4):                                    # a few ordinary minutes back inside
        assert bo.check_live(q(109.0, vol, vwap=109.0), now=t) == []
        t += dt.timedelta(minutes=1)
        vol += 2_000
    fired = bo.check_live(q(111.3, vol + 80_000, vwap=109.0), now=t)
    assert [a["kind"] for a in fired] == ["BO_BASE"]


def test_a_gap_through_the_level_is_not_a_breakout():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5, px=112.0, opn=112.0)
    assert bo.check_live(q(112.4, vol + 80_000, opn=112.0, vwap=111.0), now=t) == []


def test_a_level_cleared_before_today_is_not_a_breakout():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5, px=111.5, pc=111.6)
    assert bo.check_live(q(111.9, vol + 80_000, pc=111.6, vwap=111.0), now=t) == []


def test_a_break_seen_only_after_a_restart_is_not_fresh():
    _arm()
    t = at(11, 0)                                         # first quote of the day, already through
    assert bo.check_live(q(111.3, 400_000, vwap=109.0), now=t) == []
    assert bo.check_live(q(111.4, 500_000, vwap=109.0), now=t + dt.timedelta(seconds=20)) == []


def test_a_breakdown_is_a_short():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    fired = bo.check_live(q(104.8, vol + 60_000, vwap=106.5), now=t)
    assert len(fired) == 1
    a = fired[0]
    assert (a["kind"], a["direction"], a["level"]) == ("BO_PDL", "DOWN", 105.0)
    assert a["stop"] > a["entry"] > a["t1"] > a["target"]
    assert a["call"] == "INTRADAY" and "Fell below 105.00, yesterday's low" in a["why"]


def test_shorts_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(bo, "SHORTS", False)
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(q(104.8, vol + 60_000, vwap=106.5), now=t) == []


def test_the_index_and_vwap_can_veto():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t, index_pct=-1.2) == []
    assert "index" in bo.status(now=t)["waiting"][0]["why"]
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(q(111.3, vol + 60_000, vwap=112.0), now=t) == []


def test_a_level_too_close_overhead_leaves_no_room():
    _arm()
    bo._mem["feed"]["levels"]["NEAR"]["up"].append({"l": 111.6, "k": "HIGH52", "s": 4, "also": []})
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t) == []
    assert "too close" in bo.status(now=t)["waiting"][0]["why"]


def test_a_tight_intraday_range_broken_on_volume_is_a_trade():
    _arm()
    bo.check_live(q(108.0, 5_000, pc=107.0), now=at(9, 16))
    t, vol = at(11, 0), 400_000
    for k in range(35):                                   # 35 minutes inside 0.3%
        px = 108.0 + 0.3 * (k % 2)
        assert bo.check_live(q(px, vol, pc=107.0, vwap=107.8), now=t) == []
        t += dt.timedelta(minutes=1)
        vol += 2_000
    fired = bo.check_live(q(108.5, vol + 40_000, pc=107.0, vwap=107.8), now=t)
    assert [a["kind"] for a in fired] == ["BO_RANGE"]
    a = fired[0]
    assert a["call"] == "CONSOLIDATION" and "tight 40-minute range" in a["why"]
    assert a["level"] == pytest.approx(108.3, abs=0.01)
    assert a["stop"] < 108.0                              # the far side of the range
    assert a["risk_pct"] < 0.8


def test_nothing_fires_outside_the_window_or_from_stale_levels():
    _arm()
    t, vol = quiet_tape(at(15, 1), 5)                     # after 15:00
    assert bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t) == []
    _arm(asof="2026-11-01")
    assert bo.watch_symbols(now=at(10, 0)) == []
    assert bo.check_live(q(111.3, 900_000), now=at(10, 0)) == []


# ---------------------------------------------------------------------------
# The loop that carries them (intraday.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def loop(monkeypatch, tmp_path):
    sent = []
    alert = dict(bo.sample(), symbol="NEAR", date=intraday._today())
    calls = {"n": 0}

    def check_live(snap, index_pct=None, fired=None, log=None):
        calls["n"] += 1
        calls["fired"] = fired
        return [] if ("NEAR", "UP") in (fired or set()) else [dict(alert)]

    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(
        configured=lambda: True,
        bulk_quotes=lambda syms, mode="ohlc": {s: {"ltp": 100.0, "volume": 1, "prev_close": 99.0}
                                               for s in syms}))
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        watch_symbols=lambda: ["NEAR"], check_live=check_live,
        status=lambda: {"stocks": 1, "usable": True, "asof": "2026-11-16"}))
    monkeypatch.setattr(intraday, "notify", types.SimpleNamespace(
        send_batch=lambda rows, **k: sent.append(rows), send_plain=lambda t: None,
        format_day_open=lambda **k: "", configured=lambda: True))
    monkeypatch.setattr(intraday, "ann", None)
    monkeypatch.setattr(intraday, "LOG_FILE", str(tmp_path / "log.json"))
    monkeypatch.setitem(intraday._state, "alerts", [])
    monkeypatch.setitem(intraday._state, "watch", [])
    return sent, calls


def test_the_loop_logs_and_sends_a_breakout_once(loop):
    sent, calls = loop
    fired = intraday.scan_once()
    assert [a["symbol"] for a in fired] == ["NEAR"]
    assert len(sent) == 1 and sent[0][0]["kind"] == "BO_BASE"
    assert intraday.scan_once() == []                     # the engine is told it already fired
    assert calls["fired"] == {("NEAR", "UP")} and len(sent) == 1
    assert intraday.status()["alerts_today"][0]["symbol"] == "NEAR"


def test_two_passes_at_once_do_not_both_run(loop):
    _sent, calls = loop
    assert intraday._pass_lock.acquire(blocking=False)
    try:
        assert intraday.scan_once() == []
    finally:
        intraday._pass_lock.release()
    assert calls["n"] == 0


def test_the_record_counts_every_trade_in_risks(monkeypatch):
    base = {"date": "2026-11-17", "time": "10:42", "symbol": "X", "kind": "BO_BASE",
            "entry": 100.0, "stop": 99.0, "target": 102.0, "rr": 2.0, "score": 70, "rvol": 2.5}
    rows = [dict(base, direction="UP", outcome="TARGET", closed_at=102.0),
            dict(base, direction="UP", outcome="STOP", closed_at=99.0),
            dict(base, direction="UP", outcome="OPEN_AT_CLOSE", closed_at=100.5),
            dict(base, direction="DOWN", kind="BO_PDL", stop=101.0, target=98.0,
                 outcome="OPEN_AT_CLOSE", closed_at=99.5)]
    assert [intraday._r_multiple(a) for a in rows] == [2.0, -1.0, 0.5, 0.5]
    monkeypatch.setitem(intraday._state, "alerts", rows)
    s = intraday.stats()
    assert s["overall"] == {"trades": 4, "win_rate": 75, "targets": 1, "stops": 1,
                            "expectancy_R": 0.5, "total_R": 2.0}
    assert s["by_signal"]["BO_BASE"]["trades"] == 3 and s["by_direction"]["DOWN"]["trades"] == 1


def test_the_page_record_is_in_plain_counts_and_percent(monkeypatch):
    base = {"date": "2026-11-17", "time": "10:42", "symbol": "X", "kind": "BO_BASE",
            "call": "CONSOLIDATION", "direction": "UP", "entry": 100.0, "stop": 99.0, "target": 102.0}
    rows = [dict(base, outcome="TARGET", closed_at=102.0),                    # +2.0%
            dict(base, outcome="STOP", closed_at=99.0),                       # -1.0%
            dict(base, kind="BO_PDL", call="INTRADAY", direction="DOWN", stop=101.0, target=98.0,
                 outcome="OPEN_AT_CLOSE", closed_at=99.5),                    # +0.5% on a short
            # The old volume scanner's history is a different system: not counted.
            dict(base, kind="RVOL", call=None, outcome="STOP", closed_at=99.0)]
    assert [intraday._pnl_pct(a) for a in rows[:3]] == [2.0, -1.0, 0.5]
    monkeypatch.setitem(intraday._state, "alerts", rows)
    rec = intraday.stats()["calls"]
    assert rec["consolidation"] == {"calls": 2, "target": 1, "stop": 1, "closed": 0,
                                    "profitable": 1, "avg_pct": 0.5}
    assert rec["intraday"] == {"calls": 1, "target": 0, "stop": 0, "closed": 1,
                               "profitable": 1, "avg_pct": 0.5}


# ---------------------------------------------------------------------------
# The Telegram messages
# ---------------------------------------------------------------------------

def test_a_call_reads_as_a_call():
    text = alerts.format_digest([bo.sample()], index_pct=0.35, total_today=1, clock="10:42")
    assert "🟢 BUY <b>TESTMSG</b>" in text and "🚀 <b>Consolidation breakout</b>  ·  10:42 am" in text
    for label, value in (("Buy at", "₹414.10"), ("Stop loss", "₹411.25"), ("Target", "₹419.80"),
                         ("Crossed above", "₹412.50")):
        assert label in text and value in text
    assert "The top of a 64-day consolidation" in text and "Volume <b>2.6×</b> normal" in text
    assert "⏰ Exit by 3:15 pm" in text and "#TESTMSG" in text
    # Nothing a reader has to decode.
    for jargon in ("score", "VWAP", "1:2", "index", "R "):
        assert jargon not in text
    sell = alerts.format_digest([dict(bo.sample(), direction="DOWN", call="INTRADAY")])
    assert "🔴 SELL <b>TESTMSG</b>" in sell and "⚡ <b>Intraday call</b>" in sell
    assert "Sell at" in sell and "📉 Fell below" in sell


def test_the_public_message_carries_no_entry_stop_or_target():
    text = alerts.format_public(bo.sample())
    assert "<b>TESTMSG</b>  🟢 ▲ +1.8%" in text and "🚀 <b>Consolidation breakout</b>" in text
    assert "📈 Crossed above <b>₹412.50</b>" in text and "The top of a 64-day consolidation" in text
    assert "Now <b>₹414.10</b>" in text and "#TESTMSG #Breakout #NSE" in text
    for trade in ("411.25", "419.80", "BUY", "SELL", "Exit", "Stop", "Target"):
        assert trade not in text
    assert "not a recommendation" in text


def test_a_hashtag_survives_a_symbol_telegram_cannot_tag():
    text = alerts.format_public(dict(bo.sample(), symbol="M&M", direction="DOWN", call="INTRADAY",
                                     level_name="Yesterday's low", move_pct=-1.2))
    assert "<b>M&amp;M</b>  🔴 ▼ −1.2%" in text and "#MM #Intraday #NSE" in text
    assert "📍 Yesterday's low" in text


def test_an_older_logged_call_still_names_its_level():
    old = {k: v for k, v in bo.sample().items() if k != "level_name"}
    assert "🧱 The top of a 64-day consolidation" in alerts.format_public(old)


@pytest.mark.parametrize("url, chat, expect", [
    ("", "@altaha_alerts", "https://t.me/altaha_alerts"),           # built from the channel name
    ("https://t.me/+AbCdEf12345", "-1001234", "https://t.me/+AbCdEf12345"),   # a private invite link
    ("@altaha_alerts", "", "https://t.me/altaha_alerts"),
    ("", "-1001234567", None),                                      # a numeric id has no public link
    ("https://evil.example/t.me/x", "", None),                      # only t.me links are ever shown
    ("javascript:alert(1)", "@x", None),                            # and no too-short names either
])
def test_the_join_button_only_ever_links_to_telegram(monkeypatch, url, chat, expect):
    monkeypatch.setattr(alerts, "TG_JOIN", url)
    monkeypatch.setattr(alerts, "TG_PUBLIC", chat)
    assert alerts.join_url() == expect


def test_the_days_result_is_in_plain_words():
    rows = [dict(bo.sample(), symbol="A", outcome="TARGET", pnl_pct=1.38),
            dict(bo.sample(), symbol="B", direction="DOWN", outcome="STOP", pnl_pct=-0.44),
            dict(bo.sample(), symbol="C", outcome="OPEN_AT_CLOSE", pnl_pct=0.3)]
    text = alerts.format_day_result("18 Nov", rows)
    assert "3 calls: 1 hit target, 1 hit stop loss, 1 closed at 3:15 pm" in text
    assert "SELL B" in text and "-0.4%" in text and "+1.4%" in text
    assert "No call today" in alerts.format_day_result("18 Nov", [])


# ---------------------------------------------------------------------------
# The daily bars the levels are read from (dhan_source.py)
# ---------------------------------------------------------------------------

def _real_dhan():
    spec = importlib.util.spec_from_file_location("dhan_source_real",
                                                  os.path.join(BACKEND, "dhan_source.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dhan_with(monkeypatch, stamps):
    d = _real_dhan()
    n = len(stamps)
    body = {"open": [1.0] * n, "high": [1.0] * n, "low": [1.0] * n, "close": [1.0] * n,
            "volume": [5] * n, "timestamp": stamps}
    resp = types.SimpleNamespace(status_code=200, json=lambda: body, text="")
    monkeypatch.setattr(d, "requests", types.SimpleNamespace(post=lambda *a, **k: resp))
    monkeypatch.setattr(d, "configured", lambda: True)
    monkeypatch.setattr(d, "security_id", lambda s: "1")
    monkeypatch.setattr(d, "_throttle_hist", lambda: None)
    return d


@pytest.mark.parametrize("offset", [
    pd.Timedelta(hours=18, minutes=30),       # 18:30 UTC on the trading day (midnight after it, IST)
    -pd.Timedelta(hours=5, minutes=30),       # 18:30 UTC the day before (midnight starting it, IST)
    pd.Timedelta(0),                          # UTC midnight
])
def test_dhan_daily_bars_land_on_their_trading_day_whichever_midnight(monkeypatch, offset):
    # A year of weekdays. Read the wrong way, the stamps of one convention
    # put every Friday on a Saturday — which is how the live levels on
    # 18 Nov 2026 lost Tuesday's candle.
    days = pd.bdate_range(end="2026-11-17", periods=260)
    stamps = [int((pd.Timestamp(x) + offset).timestamp()) for x in days]
    d = _dhan_with(monkeypatch, stamps)
    monkeypatch.setattr(d, "_append_today", lambda s, df: df)
    df = d.daily_ohlcv("ANY")
    assert list(df.index) == list(days)
    assert (df.index.dayofweek < 5).all()


def test_dhan_with_today_false_spends_no_quote_call(monkeypatch):
    days = pd.bdate_range(end="2026-11-17", periods=70)
    d = _dhan_with(monkeypatch, [int(pd.Timestamp(x).timestamp()) for x in days])
    called = []
    monkeypatch.setattr(d, "_append_today", lambda s, df: called.append(s) or df)
    d.daily_ohlcv("ANY", with_today=False)
    assert called == []
    d.daily_ohlcv("ANY")
    assert called == ["ANY"]


def test_dhan_todays_bar_carries_the_days_volume(monkeypatch):
    d = _real_dhan()
    seen = {}

    def quotes(symbols, mode="ohlc"):
        seen["mode"] = mode
        return {"ANY": {"ltp": 101.0, "open": 100.0, "high": 102.0, "low": 99.0,
                        "volume": 4_200_000 if mode == "quote" else None}}

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 11, 17, 16, 50, tzinfo=tz)

    monkeypatch.setattr(d, "bulk_quotes", quotes)
    monkeypatch.setattr(d, "dt", types.SimpleNamespace(datetime=Clock, date=dt.date,
                                                       timedelta=dt.timedelta, timezone=dt.timezone))
    df = frame([100.0] * 60, end="2026-11-16")
    out = d._append_today("ANY", df)
    assert seen["mode"] == "quote"
    assert out.index[-1] == pd.Timestamp("2026-11-17")
    assert out["Volume"].iloc[-1] == 4_200_000


def test_the_morning_rebuilds_levels_that_are_a_session_behind(monkeypatch):
    started = []

    class Thread:
        def __init__(self, target=None, args=(), **k):
            self.args = args

        def start(self):
            started.append(self.args[0])

    monkeypatch.setattr(intraday, "threading", types.SimpleNamespace(Thread=Thread))
    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(configured=lambda: True))
    monkeypatch.setattr(intraday, "now_ist", lambda: dt.datetime(2026, 11, 19, 8, 45, tzinfo=IST))
    monkeypatch.setitem(intraday._state, "levels_day", None)
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        usable=lambda: True, behind=lambda: True, universe=lambda: ["A", "B"], rebuild=None))
    intraday._ensure_levels()
    assert started == [["A", "B"]]
    intraday._ensure_levels()                     # once a day, not every pass
    assert len(started) == 1

    started.clear()
    monkeypatch.setitem(intraday._state, "levels_day", None)
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        usable=lambda: True, behind=lambda: False, universe=lambda: ["A"], rebuild=None))
    intraday._ensure_levels()
    assert started == []                          # up to date: nothing to do


def test_calls_run_until_three_pm():
    _arm()
    t, vol = quiet_tape(at(14, 50), 5, vol0=820_000)      # a break at 2:55 pm still calls
    fired = bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)
    assert [a["kind"] for a in fired] == ["BO_BASE"] and fired[0]["time"] == "14:55"


# ---------------------------------------------------------------------------
# The ★ Select lane: fewer, stronger calls, spread across the day
# ---------------------------------------------------------------------------

STEP = dt.timedelta(seconds=20)


def _lv(up=None, dn=None, sector=None, atr=2.0):
    return {"c": 108.0, "atr": atr, "v": 1_000_000, "sector": sector, "base": {"n": 80, "w": 12.1},
            "up": up if up is not None else [{"l": 110.0, "k": "PDH", "s": 2, "also": []},
                                              {"l": 111.0, "k": "BASE", "s": 4, "also": ["HIGH20"]}],
            "dn": dn if dn is not None else [{"l": 105.0, "k": "PDL", "s": 2, "also": []},
                                              {"l": 99.0, "k": "BASE_DN", "s": 4, "also": []}]}


def _arm_many(levels):
    bo._mem["feed"] = {"asof": "2026-11-16", "levels": levels}
    bo._mem["day"] = None


def quote(px, vol, pc=108.0, opn=108.0, vwap=None, hi=None, lo=None, bq=None, sq=None):
    return {"ltp": px, "volume": vol, "prev_close": pc, "open": opn, "vwap": vwap,
            "high": hi or px, "low": lo or px, "buy_qty": bq, "sell_qty": sq}


def play(names, start, minutes, px=108.5, vol0=150_000, per_pass=1_000):
    """Every stock in `names` at an ordinary price and volume, a pass every 20 s."""
    bo.check_live({s: quote(108.0, 5_000) for s in names}, now=at(9, 16))
    t, vol = start, vol0
    for _ in range(int(minutes * 3)):
        assert bo.check_live({s: quote(px, vol) for s in names}, now=t) == []
        t += STEP
        vol += per_pass
    return t, vol


def brk(px, vol, **kw):
    """NEAR breaking out the way the Select lane wants it: high in the day's
    range, a little above VWAP."""
    return q(px, vol, vwap=kw.pop("vwap", 110.5), lo=kw.pop("lo", 107.5), **kw)


@pytest.fixture
def select_only(monkeypatch):
    monkeypatch.setattr(bo, "LANES", ("select",))


def test_select_waits_one_more_pass_for_the_break_to_hold(select_only):
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t) == []
    w = bo.status(now=t)["waiting"][0]
    assert (w["code"], w["lane"], w["why"]) == ("confirm", "select", "confirming breakout (1/2 passes)")
    fired = bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)
    assert [(a["kind"], a["engine"], a["confirm_passes"]) for a in fired] == [("BO_BASE", "select", 2)]
    a = fired[0]
    assert a["setup"] == "Base breakout" and a["window"] == "open" and a["range_pos"] == 1.0
    assert a["score"] >= bo.SELECT["MIN_SCORE"] and a["shadow"] == [] and a["profile"] is False
    # Called once: the lane remembers it, with or without a caller's log.
    assert bo.check_live(brk(111.5, vol + 80_000), now=t + 2 * STEP) == []


def test_select_forgets_a_break_that_falls_back_inside(select_only):
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t) == []                # 1 of 2
    assert bo.check_live(brk(110.6, vol + 62_000), now=t + STEP) == []         # back under 111
    assert bo.check_live(brk(111.3, vol + 64_000), now=t + 2 * STEP) == []     # 1 of 2 again
    assert "(1/2 passes)" in bo.status(now=t + 2 * STEP)["waiting"][0]["why"]
    fired = bo.check_live(brk(111.4, vol + 70_000), now=t + 3 * STEP)
    assert [a["kind"] for a in fired] == ["BO_BASE"]


def test_the_opening_burst_cannot_spend_the_whole_day(select_only):
    names = [f"S{k}" for k in range(6)] + ["LATER"]
    _arm_many({s: _lv() for s in names})
    t, vol = play(names, at(9, 35), 5)
    burst = [s for s in names if s != "LATER"]

    def wave(px, v):
        return {**{s: quote(px, v, vwap=110.5, lo=107.5) for s in burst}, "LATER": quote(108.5, v)}
    assert bo.check_live(wave(111.3, vol + 60_000), now=t) == []              # all six must hold
    first = bo.check_live(wave(111.4, vol + 70_000), now=t + STEP)
    assert len(first) == 2                                                    # two at a time
    st = bo.status(now=t + STEP)
    assert sum(w["code"] == "cap" for w in st["waiting"]) == 4
    second = bo.check_live(wave(111.5, vol + 80_000), now=t + 2 * STEP)
    assert len(second) == 1                                                   # the opening's third slot
    assert any("session slots full (opening 3/3)" in w["why"]
               for w in bo.status(now=t + 2 * STEP)["waiting"])
    assert bo.check_live(wave(111.5, vol + 90_000), now=t + 3 * STEP) == []
    assert bo.pacing(now=t + 3 * STEP)["slots"][0]["used"] == 3

    # Mid-morning has slots of its own: a break at 11:00 is still a call.
    t2, vol2 = at(10, 55), vol + 200_000
    for _ in range(15):
        assert bo.check_live({s: quote(108.5, vol2) for s in names}, now=t2) == []
        t2 += STEP
        vol2 += 1_000
    late = {**{s: quote(108.5, vol2 + 60_000) for s in burst},
            "LATER": quote(111.3, vol2 + 60_000, vwap=110.5, lo=107.5)}
    assert bo.check_live(late, now=t2) == []
    late["LATER"] = quote(111.4, vol2 + 70_000, vwap=110.5, lo=107.5)
    fired = bo.check_live(late, now=t2 + STEP)
    assert [(a["symbol"], a["window"]) for a in fired] == [("LATER", "mid")]
    p = bo.pacing(now=t2 + STEP)
    assert [s["used"] for s in p["slots"]] == [3, 1, 0] and p["used_today"] == 4


def test_three_breaks_in_one_sector_send_its_leader_first(select_only):
    names = ["P0", "P1", "P2"]
    _arm_many({s: _lv(sector="Power") for s in names})
    t, vol = play(names, at(9, 35), 5)
    wave = lambda px, v: {s: quote(px, v, vwap=110.5, lo=107.5) for s in names}
    assert bo.check_live(wave(111.3, vol + 60_000), now=t) == []
    one = bo.check_live(wave(111.4, vol + 70_000), now=t + STEP)
    assert len(one) == 1 and one[0]["sector_pct"] == pytest.approx(3.15, abs=0.01)
    held = [w for w in bo.status(now=t + STEP)["waiting"] if w["code"] == "cap"]
    assert len(held) == 2 and all(w["why"] == "sector cap reached (leader already alerted)" for w in held)
    two = bo.check_live(wave(111.5, vol + 80_000), now=t + 2 * STEP)
    assert len(two) == 1 and two[0]["symbol"] != one[0]["symbol"]
    assert bo.check_live(wave(111.5, vol + 90_000), now=t + 3 * STEP) == []
    assert any(w["why"] == "sector cap reached (2 Power calls today)"
               for w in bo.status(now=t + 3 * STEP)["waiting"])


FAR = {"up": [{"l": 130.0, "k": "HIGH52", "s": 4, "also": []}],
       "dn": [{"l": 80.0, "k": "LOW52", "s": 4, "also": []}]}


def _pause_after_a_high(dip_at=None):
    """A high of 115 at 09:50, then 45 minutes between 114.2 and 114.9 above
    VWAP (113.9) — or, with `dip_at`, one pass under it."""
    _arm_many({"HOD1": _lv(**FAR)})
    bo.check_live({"HOD1": quote(112.0, 5_000, pc=112.0, opn=112.0)}, now=at(9, 16))
    bo.check_live({"HOD1": quote(115.0, 300_000, pc=112.0, opn=112.0, vwap=113.5, hi=115.0,
                                 lo=111.5)}, now=at(9, 50))
    t, vol, k = at(9, 50, 20), 301_000, 0
    while t < at(10, 35):
        px = 113.6 if (dip_at and t == dip_at) else 114.2 + 0.7 * (k % 2)
        assert bo.check_live({"HOD1": quote(px, vol, pc=112.0, opn=112.0, vwap=113.9, hi=115.0,
                                            lo=111.5)}, now=t) == []
        t += STEP
        vol += 1_000
        k += 1
    return t, vol


def _hod_break(px, vol):
    return {"HOD1": quote(px, vol, pc=112.0, opn=112.0, vwap=113.9, hi=px, lo=111.5)}


def test_select_calls_a_fresh_day_high_after_a_pause_that_held_vwap(select_only):
    t, vol = _pause_after_a_high()
    assert bo.check_live(_hod_break(115.3, vol + 60_000), now=t) == []          # held? one more pass
    fired = bo.check_live(_hod_break(115.4, vol + 70_000), now=t + STEP)
    assert [a["kind"] for a in fired] == ["BO_HOD"]
    a = fired[0]
    assert a["level"] == 115.0 and a["setup"] == "Fresh day high"
    assert a["call"] == "CONSOLIDATION"                   # the pause was a tight range
    assert a["level_name"].startswith("Today's high from 9:50 am, after a 45-minute pause")
    assert 114.6 < a["stop"] < 115.0                      # the tighter stop: just under the old high
    assert alerts.KIND_LABEL.get("BO_HOD")


def test_a_fresh_day_high_after_a_pause_that_lost_vwap_is_not_a_call(select_only):
    t, vol = _pause_after_a_high(dip_at=at(10, 20))
    assert bo.check_live(_hod_break(115.3, vol + 60_000), now=t) == []
    assert bo.check_live(_hod_break(115.4, vol + 70_000), now=t + STEP) == []


def _vwap_day(pierce=False):
    """Up 3% on the day; a high of 114.5 at 09:40; drifting at 114.0-114.4,
    a pullback to VWAP (113.2) by 10:30, a climb back to 113.95."""
    _arm_many({"VW1": _lv(atr=2.5, **FAR)})
    kw = dict(pc=111.0, opn=111.0, vwap=113.2, hi=114.5, lo=111.0)
    bo.check_live({"VW1": quote(111.0, 5_000, pc=111.0, opn=111.0)}, now=at(9, 16))
    bo.check_live({"VW1": quote(114.5, 300_000, **kw)}, now=at(9, 40))
    t, vol, k = at(9, 40, 20), 301_000, 0
    while t < at(10, 45):
        m = (t - at(9, 0)).total_seconds() / 60.0 - 60          # minutes after 10:00
        if m < 10:
            px = 114.0 + 0.4 * (k % 2)
        elif m < 30:
            px = 114.0 - (m - 10) / 20 * 0.75                 # 114.00 down to 113.25
            if pierce and 25 <= m < 26:
                px = 112.9
        else:
            px = 113.3 + (m - 30) / 15 * 0.65                 # back up to 113.95
        assert bo.check_live({"VW1": quote(round(px, 2), vol, **kw)}, now=t, index_pct=0.5) == []
        t += STEP
        vol += 1_000
        k += 1
    return t, vol, kw


def test_select_calls_a_pullback_to_vwap_that_breaks_out_again(select_only):
    t, vol, kw = _vwap_day()
    assert bo.check_live({"VW1": quote(114.1, vol + 60_000, **kw)}, now=t, index_pct=0.5) == []
    fired = bo.check_live({"VW1": quote(114.15, vol + 70_000, **kw)}, now=t + STEP, index_pct=0.5)
    assert [a["kind"] for a in fired] == ["BO_VWAP"]
    a = fired[0]
    assert a["setup"] == "VWAP reclaim" and a["call"] == "INTRADAY"
    assert a["stop"] == pytest.approx(113.2 * (1 - bo.VWAP_STOP / 100), abs=0.01)   # just across VWAP
    assert "VWAP" not in a["level_name"]                  # plain words on a phone


def test_a_pullback_that_lost_vwap_is_not_a_reclaim(select_only):
    t, vol, kw = _vwap_day(pierce=True)
    assert bo.check_live({"VW1": quote(114.1, vol + 60_000, **kw)}, now=t, index_pct=0.5) == []
    assert bo.check_live({"VW1": quote(114.15, vol + 70_000, **kw)}, now=t + STEP,
                         index_pct=0.5) == []


def test_select_measures_volume_against_the_stocks_own_profile(select_only):
    _arm()
    # This stock trades 50,000 shares every five minutes, all day: against
    # the generic curve today's burst reads 4.5x, against its own 1.5x.
    bo.save_profiles({"NEAR": [50_000.0 * (k + 1) for k in range(75)]}, "2026-11-16")
    assert bo.profiles_fresh(now=at(10, 0)) and bo.profile_symbols() == ["NEAR"]
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t) == []
    w = bo.status(now=t)["waiting"][0]
    assert w["code"] == "volume" and "needs 2.5x" in w["why"]
    assert bo.status(now=t)["profiles"]["ready"] == 1


def test_a_stock_without_a_profile_falls_back_to_the_curve(select_only):
    _arm()
    bo.save_profiles({"OTHER": [50_000.0 * (k + 1) for k in range(75)]}, "2026-11-16")
    t, vol = quiet_tape(at(9, 55), 5)
    bo.check_live(brk(111.3, vol + 60_000), now=t)
    fired = bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)
    assert [a["profile"] for a in fired] == [False]


def test_a_light_profile_is_used_and_a_stale_one_is_not(select_only):
    _arm()
    bo.save_profiles({"NEAR": [4_000.0 * (k + 1) for k in range(75)]}, "2026-11-16")
    t, vol = quiet_tape(at(9, 55), 5)
    bo.check_live(brk(111.3, vol + 60_000), now=t)
    assert [a["profile"] for a in bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)] == [True]
    _arm()
    bo.save_profiles({"NEAR": [50_000.0 * (k + 1) for k in range(75)]}, "2026-10-01")   # weeks old
    assert not bo.profiles_fresh(now=at(10, 0))
    t, vol = quiet_tape(at(9, 55), 5)
    bo.check_live(brk(111.3, vol + 60_000), now=t)
    assert [a["profile"] for a in bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)] == [False]


@pytest.mark.parametrize("quote_kw, code, words", [
    (dict(hi=114.0), "rpos", "only 58% up the day's range, needs 72%"),
    (dict(vwap=109.0), "extended", "extended 2.1% above VWAP, limit 1.5%"),
])
def test_select_wants_the_top_of_the_day_and_not_a_stretch(select_only, quote_kw, code, words):
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000, **quote_kw), now=t) == []
    w = bo.status(now=t)["waiting"][0]
    assert w["code"] == code and w["why"] == words


def test_a_wall_of_sell_orders_costs_points_and_a_bigger_one_stops_the_call(select_only):
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    wall = lambda px, v, sq: {"NEAR": quote(px, v, vwap=110.5, lo=107.5, bq=10_000, sq=sq)}
    assert bo.check_live(wall(111.3, vol + 60_000, 70_000), now=t) == []
    w = bo.status(now=t)["waiting"][0]
    assert w["code"] == "book" and "7.0x" in w["why"]
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    bo.check_live(wall(111.3, vol + 60_000, 40_000), now=t)
    a = bo.check_live(wall(111.4, vol + 70_000, 40_000), now=t + STEP)[0]
    assert a["score_parts"]["book"] == -6.0 and a["book_ratio"] == 4.0 and "book" in a["shadow"]


def test_a_sector_falling_against_the_call_holds_it(select_only):
    names = ["NEAR", "W1", "W2", "W3"]
    _arm_many({s: _lv(sector="Power") for s in names})
    t, vol = play(names, at(9, 35), 5)
    snap = {s: quote(106.5, vol) for s in ("W1", "W2", "W3")}          # the sector is 1.4% down
    snap["NEAR"] = quote(111.3, vol + 60_000, vwap=110.5, lo=107.5)
    assert bo.check_live(snap, now=t) == []
    w = [w for w in bo.status(now=t)["waiting"] if w["symbol"] == "NEAR"][0]
    assert w["code"] == "sector" and w["why"] == "Power stocks are -1.4% today, against it"


def test_money_flow_adds_its_tailwind_to_the_score(select_only):
    _arm()
    bo.set_money_flow({"power": "Leading", "it": "Lagging", "junk": "Sideways"}, "2026-11-17")
    assert bo.status(now=at(10, 0))["money_flow"]["sectors"] == 2
    t, vol = quiet_tape(at(9, 55), 5)
    bo.check_live(brk(111.3, vol + 60_000), now=t)
    a = bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)[0]
    assert a["money_flow_quadrant"] == "Leading" and a["score_parts"]["flow"] == 5.0


def test_the_select_lane_does_not_change_a_classic_call(monkeypatch):
    def run():
        _arm()
        t, vol = quiet_tape(at(9, 55), 5)
        return bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)
    classic_only = run()
    monkeypatch.setattr(bo, "LANES", ("classic", "select"))
    monkeypatch.setattr(bo, "_mem", {"feed": None, "day": None})
    both = run()
    # The call is Classic's own to the last figure; Select only notes, for
    # the owner, what held it back on the same pass.
    classic = [a for a in both if a["engine"] == "classic"]
    assert classic_only and [{k: v for k, v in a.items() if k != "select_wait"} for a in classic] == classic_only
    assert [a.get("select_wait") for a in classic] == [
        {"code": "extended", "why": "extended 2.1% above VWAP, limit 1.5%"}]
    assert "select_wait" not in classic_only[0]


def test_every_classic_call_carries_what_selects_filters_would_say():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    a = bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)[0]
    assert a["engine"] == "classic" and a["window"] == "open" and a["range_pos"] == 0.0
    assert set(a["shadow"]) == {"rpos", "extended"} and a["vwap_ext_pct"] == pytest.approx(2.11, abs=0.01)


def test_each_lane_reads_its_own_calls_from_the_log(monkeypatch):
    monkeypatch.setattr(bo, "LANES", ("classic", "select"))
    called = lambda engine: [{"date": "2026-11-17", "time": "09:58", "symbol": "NEAR", "kind": "BO_BASE",
                              "direction": "UP", "engine": engine, "window": "open"}]
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    fired = bo.check_live(brk(111.3, vol + 60_000), now=t, log=called("select"))
    assert [a["engine"] for a in fired] == ["classic"]          # Select had called it; Classic had not
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t, log=called("classic")) == []
    fired = bo.check_live(brk(111.4, vol + 70_000), now=t + STEP, log=called("classic"))
    assert [a["engine"] for a in fired] == ["select"]


def test_the_radar_shows_one_row_per_stock_with_both_lanes_reasons(monkeypatch):
    monkeypatch.setattr(bo, "LANES", ("classic", "select"))
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 15_000), now=t) == []
    st = bo.status(now=t)
    w = st["waiting"][0]
    assert (w["lane"], w["code"], w["need"]) == ("select", "volume", 2.5)
    assert "needs 2.5x" in w["why"] and "needs 2x" in w["classic_why"] and w["since"] == "10:00"
    assert st["gates"]["select"]["volume"] == 1 and st["gates"]["classic"]["volume"] == 1
    for key in ("lanes", "pacing", "session", "profiles", "checkpoint", "sectors_live", "money_flow"):
        assert key in st
    assert st["lanes"]["select"]["window"] == "09:25–14:45"
    assert st["rules"]["window"] == "09:20 to 15:00, one alert per stock per direction a day"


def test_the_page_reads_the_select_budget_in_words():
    log = [{"date": "2026-11-17", "time": "09:41", "symbol": "A", "kind": "BO_BASE", "engine": "select",
            "window": "open"},
           {"date": "2026-11-17", "time": "11:02", "symbol": "B", "kind": "BO_HOD", "engine": "select",
            "window": "mid"},
           {"date": "2026-11-17", "time": "11:05", "symbol": "C", "kind": "BO_BASE"}]    # classic
    p = bo.pacing(log=log, now=at(11, 42))
    assert p["session"]["key"] == "mid" and p["used_today"] == 2 and p["cap_day"] == 8
    assert [s["used"] for s in p["slots"]] == [1, 1, 0]
    assert p["line"] == "Mid-morning session · 1/3 ★ slots used · Live 11:42 IST"
    assert bo.pacing(now=at(9, 20))["line"] == "Opening minutes · ★ Select starts 9:25 am · Live 09:20 IST"
    saturday = dt.datetime(2026, 11, 21, 11, 0, tzinfo=IST)
    assert bo.pacing(now=saturday)["line"] == "Market closed · back at 9:15 am"


def test_a_second_select_call_needs_a_new_setup_later_in_the_day():
    assert bo._reentry_ok([{"window": "open"}], "mid")
    assert not bo._reentry_ok([{"window": "mid"}], "mid")
    assert not bo._reentry_ok([{"window": "open", "live_outcome": "STOP"}], "pm")
    assert not bo._reentry_ok([{"window": "open"}, {"window": "mid"}], "pm")


# ---------------------------------------------------------------------------
# The day's memory: a restart, a missed opening range, a mid-day rebuild
# ---------------------------------------------------------------------------

def test_a_restart_carries_the_day_on_from_its_checkpoint(monkeypatch):
    monkeypatch.setattr(bo, "CHECKPOINT_SEC", 60)
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert os.path.exists(bo.DAY_FILE) and bo.status(now=t)["checkpoint"]["saved_at"]
    bo._mem["day"] = None                                  # the process restarts
    fired = bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)
    assert [a["kind"] for a in fired] == ["BO_BASE"]       # still fresh: the stock was being watched
    st = bo.status(now=t)
    assert st["checkpoint"]["restored"] and st["checkpoint"]["restored_gap_min"] <= 1.5
    assert st["tape_minutes"] >= 44                        # 09:16 onwards, not from the restart


def test_after_a_long_blind_gap_a_break_under_way_is_not_fresh(monkeypatch):
    monkeypatch.setattr(bo, "CHECKPOINT_SEC", 60)
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    bo._mem["day"] = None
    later = t + dt.timedelta(minutes=15)
    assert bo.check_live(q(111.3, vol + 200_000, vwap=109.0), now=later) == []
    assert bo.status(now=later)["checkpoint"]["restored_gap_min"] >= 14


def test_a_checkpoint_from_another_day_is_ignored(monkeypatch):
    monkeypatch.setattr(bo, "CHECKPOINT_SEC", 60)
    _arm()
    quiet_tape(at(9, 55), 5)
    bo._mem["day"] = None
    assert bo._load_day("2026-11-18") is None and bo._load_day("2026-11-17") is not None


def test_a_missed_opening_range_is_backfilled_and_traded():
    _arm()
    bo.check_live(q(108.0, 5_000), now=at(9, 16))
    assert bo.orb_missing(now=at(10, 20))                  # nobody looked at 09:30
    assert bo.set_orb("2026-11-17", {"NEAR": (108.9, 107.0), "GONE": (1, 0)}, now=at(10, 20)) == 1
    assert not bo.orb_missing(now=at(10, 20)) and bo.status(now=at(10, 20))["opening_ranges"] == 1
    t, vol = at(10, 20), 300_000
    for _ in range(15):
        assert bo.check_live(q(108.5, vol), now=t) == []
        t += STEP
        vol += 1_000
    fired = bo.check_live(q(109.05, vol + 60_000, vwap=108.6), now=t)
    assert [a["kind"] for a in fired] == ["BO_ORB"]


def test_new_levels_mid_session_keep_the_days_tape():
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    n = bo._mem["day"]["n"]
    feed = dict(bo._mem["feed"])
    feed["levels"] = dict(feed["levels"], OTHER=dict(feed["levels"]["NEAR"]))
    bo._mem["feed"] = feed                                 # a rebuild landed: a longer list
    fired = bo.check_live(q(111.3, vol + 60_000, vwap=109.0), now=t)
    assert [a["kind"] for a in fired] == ["BO_BASE"]       # the five minutes before it were kept
    assert bo._mem["day"]["n"] == n + 1 and "OTHER" in bo._mem["day"]["row"]


def test_a_rebuild_without_the_scan_still_knows_each_stocks_sector(monkeypatch):
    monkeypatch.setattr(bo, "MIN_SCAN", 3)
    reads = _reads()
    reads["ABB"] = reads.pop("Q0")
    feed = bo.ingest(reads, now=at(17, 5))
    assert feed["levels"]["ABB"]["sector"] == "Capital Goods"


# ---------------------------------------------------------------------------
# Found in review of the two lanes, and pinned
# ---------------------------------------------------------------------------

def _two_stock_vwap_day():
    """_vwap_day() for VW1, with NEAR quoted beside it all morning at an
    ordinary price, so both are watched when the review's pass comes."""
    _arm_many({"VW1": _lv(atr=2.5, **FAR), "NEAR": _lv(sector="Power")})
    kw = dict(pc=111.0, opn=111.0, vwap=113.2, hi=114.5, lo=111.0)
    bo.check_live({"VW1": quote(111.0, 5_000, pc=111.0, opn=111.0), "NEAR": quote(108.0, 5_000)},
                  now=at(9, 16))
    bo.check_live({"VW1": quote(114.5, 300_000, **kw), "NEAR": quote(108.5, 300_000)}, now=at(9, 40))
    t, vol, k = at(9, 40, 20), 301_000, 0
    while t < at(10, 45):
        m = (t - at(9, 0)).total_seconds() / 60.0 - 60
        px = (114.0 + 0.4 * (k % 2) if m < 10 else
              114.0 - (m - 10) / 20 * 0.75 if m < 30 else 113.3 + (m - 30) / 15 * 0.65)
        assert bo.check_live({"VW1": quote(round(px, 2), vol, **kw), "NEAR": quote(108.5, vol)},
                             now=t, index_pct=0.5) == []
        t += STEP
        vol += 1_000
        k += 1
    return t, vol, kw


def test_a_vwap_reclaim_on_a_quote_without_vwap_waits_and_the_pass_goes_on(monkeypatch):
    monkeypatch.setattr(bo, "LANES", ("classic", "select"))
    t, vol, kw = _two_stock_vwap_day()
    log = []
    log += bo.check_live({"VW1": quote(114.1, vol + 60_000, **kw), "NEAR": quote(108.5, vol + 1_000)},
                         now=t, index_pct=0.5, log=log)
    assert log == []                                       # the reclaim is armed: 1 of 2
    # Dhan sends VW1's quote without an average price, on the very pass NEAR
    # breaks out: Classic's NEAR call is still made, VW1 says what it waits for.
    snap = {"VW1": quote(114.15, vol + 70_000, **dict(kw, vwap=None)),
            "NEAR": quote(111.3, vol + 61_000, vwap=109.0)}
    fired = bo.check_live(snap, now=t + STEP, index_pct=0.5, log=log)
    assert [(a["symbol"], a["engine"], a["kind"]) for a in fired] == [("NEAR", "classic", "BO_BASE")]
    log += fired
    st = bo.status(now=t + STEP)
    w = [r for r in st["waiting"] if r["symbol"] == "VW1"]
    assert [(r["lane"], r["code"], r["why"]) for r in w] == [("select", "novwap", "no VWAP on this quote")]
    assert st["errors"]["count"] == 0
    # VWAP is back on the next quote: the break held all along, so it is a call.
    fired = bo.check_live({"VW1": quote(114.2, vol + 80_000, **kw), "NEAR": quote(111.4, vol + 70_000, vwap=109.0)},
                          now=t + 2 * STEP, index_pct=0.5, log=log)
    assert [(a["symbol"], a["engine"], a["kind"]) for a in fired] == [("VW1", "select", "BO_VWAP")]
    assert fired[0]["stop"] == pytest.approx(113.2 * (1 - bo.VWAP_STOP / 100), abs=0.01)


def test_one_stock_whose_check_fails_costs_that_check_and_nothing_else(monkeypatch):
    monkeypatch.setattr(bo, "LANES", ("classic", "select"))
    names = ["BAD", "ODD", "NEAR"]
    _arm_many({s: _lv() for s in names})
    t, vol = play(names, at(9, 55), 5)
    bo._mem["feed"]["levels"]["BAD"]["v"] = None           # a level row the engine cannot read
    real = bo._side

    def side(c, L, d, lv, f, sign, *rest):
        if f["sym"] == "ODD":
            raise RuntimeError("a check that trips up")
        return real(c, L, d, lv, f, sign, *rest)
    monkeypatch.setattr(bo, "_side", side)
    snap = {s: quote(111.3, vol + 60_000, vwap=109.0) for s in names}
    fired = bo.check_live(snap, now=t)
    assert [(a["symbol"], a["engine"]) for a in fired] == [("NEAR", "classic")]
    err = bo.status(now=t)["errors"]
    # BAD once (its numbers), ODD once per side per lane; the pass itself went on.
    assert err["count"] == 5 and err["at"] == "10:00:00"
    assert err["last"].startswith("ODD DOWN select: RuntimeError")
    assert bo._mem["day"]["last"] == "10:00:00" and "NEAR" in bo._mem["day"]["seen"]


def _read(asof, pdh, hi20=113.0):
    """What read_daily() hands ingest() for NEAR."""
    return {"asof": asof, "close": 108.0, "pdh": pdh, "pdl": 105.0, "hi20": hi20, "lo20": 99.0,
            "atr_pct": 2.0, "vol_med50": 1_000_000, "turnover_cr": 100.0,
            "base": None, "high52": None, "low52": None}


def _behind_then_through():
    """Tuesday on Friday's levels (Monday's scan failed): NEAR crosses
    Monday's high of 111 at 09:45 and sits at 111.30 until 10:40."""
    bo.ingest({"NEAR": _read("2026-11-13", 113.0)}, now=at(8, 40), send=False, force=True)
    bo.check_live(q(108.0, 5_000), now=at(9, 16))
    t, vol = at(9, 20), 300_000
    while t < at(10, 40):
        px = 108.5 if t < at(9, 45) else 111.3
        assert bo.check_live(q(px, vol, vwap=110.0), now=t) == []
        t += STEP
        vol += 1_000
    return t, vol


def test_levels_rebuilt_mid_session_are_old_news_where_the_price_already_is():
    t, vol = _behind_then_through()
    # 10:40: the rebuild lands with Monday's levels. Yesterday's high (111)
    # was crossed 55 minutes ago: no call, as before the day was carried.
    bo.ingest({"NEAR": _read("2026-11-16", 111.0, hi20=112.5)}, now=at(10, 40), send=False, force=True)
    assert bo.check_live(q(111.3, vol + 60_000, vwap=110.0), now=t) == []
    assert ("NEAR", "UP", 111.0) in bo._mem["day"]["lanes"]["classic"]["dead"]
    # A new level the price has not reached yet trades as any other.
    t, vol = t + STEP, vol + 61_000
    for _ in range(9):
        assert bo.check_live(q(111.4, vol, vwap=110.0), now=t) == []
        t += STEP
        vol += 1_000
    fired = bo.check_live(q(112.7, vol + 60_000, vwap=110.5), now=t)
    assert [(a["kind"], a["level"]) for a in fired] == [("BO_HIGH20", 112.5)]


def test_a_restart_onto_rebuilt_levels_knows_which_are_new(monkeypatch):
    monkeypatch.setattr(bo, "CHECKPOINT_SEC", 60)
    t, vol = _behind_then_through()
    assert bo._load_day("2026-11-17")["ladders"]["NEAR"] == [[113.0], [99.0, 105.0]]
    bo.ingest({"NEAR": _read("2026-11-16", 111.0)}, now=at(10, 40), send=False, force=True)
    bo._mem["day"] = None                                  # and the process restarts
    assert bo.check_live(q(111.3, vol + 60_000, vwap=110.0), now=t) == []
    assert bo.status(now=t)["checkpoint"]["restored"]


def test_an_opening_range_backfilled_after_the_price_left_it_is_old_news():
    # Up at 09:50 with no checkpoint: NEAR has been over its 09:15-09:30 high
    # of 108.90 since before anyone watched. The backfill must not make that
    # a fresh opening-range breakout.
    _arm_many({"NEAR": _lv(up=[{"l": 112.0, "k": "PDH", "s": 2, "also": []}])})
    t, vol = at(9, 50), 300_000
    while t < at(9, 53):
        assert bo.check_live(q(109.3, vol, vwap=108.8, hi=109.4, lo=107.0), now=t) == []
        t += STEP
        vol += 1_000
    assert bo.orb_missing(now=t)
    assert bo.set_orb("2026-11-17", {"NEAR": (108.9, 107.0)}, now=t) == 1
    assert bo.check_live(q(109.35, vol + 60_000, vwap=108.8, hi=109.4, lo=107.0), now=t) == []
    dead = bo._mem["day"]["lanes"]["classic"]["dead"]
    assert ("NEAR", "UP", 108.9) in dead and ("NEAR", "DOWN", 107.0) not in dead


def _hod_day(log, first_call):
    """HOD1: a 115.00 high at 09:50 and a 45-minute pause above VWAP. At 10:35
    it breaks out, on a burst (`first_call`) or on ordinary volume, then
    climbs to a new high of 116.00 by 11:30 and pauses again under it, above
    VWAP, until 12:45."""
    _arm_many({"HOD1": _lv(**FAR)})
    kw = dict(pc=112.0, opn=112.0)

    def run(snap, t):
        out = bo.check_live(snap, now=t, log=log)
        log.extend(out)                                    # intraday logs every call it is handed
        return out
    run({"HOD1": quote(112.0, 5_000, **kw)}, at(9, 16))
    run({"HOD1": quote(115.0, 300_000, vwap=113.5, hi=115.0, lo=111.5, **kw)}, at(9, 50))
    t, vol, k = at(9, 50, 20), 301_000, 0
    while t < at(10, 35):
        assert run({"HOD1": quote(114.2 + 0.7 * (k % 2), vol, vwap=113.9, hi=115.0, lo=111.5, **kw)}, t) == []
        t, vol, k = t + STEP, vol + 1_000, k + 1
    calls = []
    if first_call:
        calls += run({"HOD1": quote(115.3, vol + 60_000, vwap=113.9, hi=115.3, lo=111.5, **kw)}, t)
        calls += run({"HOD1": quote(115.4, vol + 70_000, vwap=113.9, hi=115.4, lo=111.5, **kw)}, t + STEP)
        t, vol = t + 2 * STEP, vol + 71_000
    while t < at(11, 30):
        px = round(min(116.0, 115.3 + (t - at(10, 35)).total_seconds() / 3300 * 0.7), 2)
        calls += run({"HOD1": quote(px, vol, vwap=114.6, hi=max(px, 115.4), lo=111.5, **kw)}, t)
        t, vol = t + STEP, vol + 1_000
    k = 0
    while t < at(12, 45):
        calls += run({"HOD1": quote(115.6 + 0.3 * (k % 2), vol, vwap=115.0, hi=116.0, lo=111.5, **kw)}, t)
        t, vol, k = t + STEP, vol + 1_000, k + 1
    return t, vol, kw, run, calls


def _break_116(t, vol, kw, run):
    out = []
    for n in range(3):                                     # 12:45: over 116.00 on a burst, three passes
        px = 116.3 + 0.05 * n
        out += run({"HOD1": quote(px, vol + 60_000 + 10_000 * n, vwap=115.0, hi=px, lo=111.5, **kw)}, t)
        t += STEP
    return out


def test_a_fresh_day_high_that_ran_without_volume_does_not_block_the_next(select_only):
    log = []
    t, vol, kw, run, calls = _hod_day(log, first_call=False)
    assert calls == []
    assert 115.0 in bo._mem["day"]["lanes"]["select"]["late"][("HOD1", "UP")]   # the 10:35 break went late
    out = _break_116(t, vol, kw, run)
    assert [(a["time"], a["kind"], a["level"], a.get("reentry")) for a in out] == \
        [("12:45", "BO_HOD", 116.0, None)]


def test_a_second_select_call_comes_from_a_new_day_high_after_the_first_was_called(select_only):
    log = []
    t, vol, kw, run, calls = _hod_day(log, first_call=True)
    assert [(a["time"], a["kind"], a["level"], a["window"]) for a in calls] == [("10:35", "BO_HOD", 115.0, "mid")]
    out = _break_116(t, vol, kw, run)
    assert [(a["time"], a["kind"], a["level"], a["window"], a.get("reentry")) for a in out] == \
        [("12:45", "BO_HOD", 116.0, "pm", True)]


def test_a_called_setup_is_never_called_again_on_re_entry(select_only):
    # A fresh day high called at 12:25, late in the mid-morning session. Five
    # minutes on the afternoon's re-entry opens with the price still over that
    # same 115.00 and the volume still running: re-entry is for a setup the
    # day makes later, and this one has been called.
    _arm_many({"HOD1": _lv(**FAR)})
    kw = dict(pc=112.0, opn=112.0)
    log = []

    def run(snap, t):
        out = bo.check_live(snap, now=t, index_pct=0.5, log=log)
        log.extend(out)
        return out
    run({"HOD1": quote(112.0, 5_000, **kw)}, at(9, 16))
    run({"HOD1": quote(115.0, 300_000, vwap=113.5, hi=115.0, lo=111.5, **kw)}, at(11, 40))
    t, vol, k = at(11, 40, 20), 301_000, 0
    while t < at(12, 25):
        assert run({"HOD1": quote(114.2 + 0.7 * (k % 2), vol, vwap=113.9, hi=115.0, lo=111.5, **kw)}, t) == []
        t, vol, k = t + STEP, vol + 1_000, k + 1
    vol += 60_000                                          # 12:25: the burst
    calls, n = [], 0
    while t < at(12, 31):
        px = round(115.3 + 0.01 * n, 2)
        calls += run({"HOD1": quote(px, vol, vwap=113.9, hi=px, lo=111.5, **kw)}, t)
        t, vol, n = t + STEP, vol + 5_000, n + 1
    assert [(a["time"], a["kind"], a["level"], a["window"]) for a in calls] == [("12:25", "BO_HOD", 115.0, "mid")]


def _late_vwap_reclaim(second_pullback):
    """The reclaim of _vwap_day() breaks out at 10:45 on ordinary volume and
    goes late at 10:57. Then either the price keeps creeping up with no new
    pullback, or VWAP catches up and the price comes back to it."""
    t, vol, _kw = _vwap_day()
    start = t
    # Creeping on to 114.52 also lifts the day's high, so no fresh-day-high
    # setup stands ready for the jump: only a VWAP reclaim could call it.
    while t < at(10, 58 if second_pullback else 59):
        px = round(114.1 + (t - start).total_seconds() / 780 * (0.3 if second_pullback else 0.4), 2)
        assert bo.check_live({"VW1": quote(px, vol, pc=111.0, opn=111.0, vwap=113.7, hi=max(114.5, px),
                                           lo=111.0)}, now=t, index_pct=0.5) == []
        t += STEP
        vol += 1_000
    late = bo._mem["day"]["lanes"]["select"]["late"].get(("VW1", "UP")) or set()
    assert 113.94 in late
    vw = 113.7
    if second_pullback:
        vw = 114.05
        while t < at(11, 15):                             # eases back to VWAP, holds it, builds a high
            m = (t - at(10, 58)).total_seconds() / 60.0
            px = round(114.4 - min(m, 6) / 6 * 0.28 if m < 10 else 114.12 + (m - 10) / 7 * 0.18, 2)
            assert bo.check_live({"VW1": quote(px, vol, pc=111.0, opn=111.0, vwap=vw, hi=114.5, lo=111.0)},
                                 now=t, index_pct=0.5) == []
            t += STEP
            vol += 1_000
    out = []
    for n in range(3):                                     # a jump over the 15-minute high, on a burst
        px = (114.48 if second_pullback else 114.65) + 0.02 * n
        out += bo.check_live({"VW1": quote(px, vol + 60_000 + 10_000 * n, pc=111.0, opn=111.0, vwap=vw,
                                           hi=max(114.5, px), lo=111.0)}, now=t, index_pct=0.5)
        t += STEP
    return out


def test_after_a_late_vwap_reclaim_the_next_needs_a_pullback_of_its_own(select_only):
    assert _late_vwap_reclaim(second_pullback=False) == []      # a run with no new pullback is a chase
    _arm()
    assert [a["kind"] for a in _late_vwap_reclaim(second_pullback=True)] == ["BO_VWAP"]


def test_a_pass_seconds_after_the_last_does_not_confirm_a_break(select_only, monkeypatch):
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t) == []                       # 1 of 2
    # "Scan once now", or a cron tick, a second after the loop's pass.
    assert bo.check_live(brk(111.31, vol + 60_500), now=t + dt.timedelta(seconds=1)) == []
    assert "(1/2 passes)" in bo.status(now=t)["waiting"][0]["why"]
    fired = bo.check_live(brk(111.4, vol + 70_000), now=t + STEP)                      # the loop's next pass
    assert [(a["kind"], a["confirm_passes"]) for a in fired] == [("BO_BASE", 2)]
    # BOS_CONFIRM_MIN_GAP_SEC sets the gap.
    monkeypatch.setitem(bo.SELECT, "CONFIRM_MIN_GAP_SEC", 0.0)
    _arm()
    t, vol = quiet_tape(at(9, 55), 5)
    assert bo.check_live(brk(111.3, vol + 60_000), now=t) == []
    assert len(bo.check_live(brk(111.31, vol + 60_500), now=t + dt.timedelta(seconds=1))) == 1


def test_an_extra_pass_neither_confirms_nor_breaks_a_tight_range_run(select_only, monkeypatch):
    monkeypatch.setitem(bo.SELECT, "HOD", False)            # the range itself, not a fresh day high
    monkeypatch.setitem(bo.SELECT, "VWAP", False)           # nor a reclaim of its 15-minute high
    _arm()
    bo.check_live(q(108.0, 5_000, pc=107.0), now=at(9, 16))
    t, vol = at(11, 0), 400_000
    for k in range(35):                                    # 35 minutes inside 0.3%
        assert bo.check_live(q(108.0 + 0.3 * (k % 2), vol, pc=107.0, vwap=107.8, lo=107.0), now=t) == []
        t += dt.timedelta(minutes=1)
        vol += 2_000
    brk_ = lambda px, v: q(px, v, pc=107.0, vwap=107.8, lo=107.0)
    assert bo.check_live(brk_(108.5, vol + 40_000), now=t) == []                       # 1 of 2
    assert bo.check_live(brk_(108.52, vol + 41_000), now=t + dt.timedelta(seconds=1)) == []
    fired = bo.check_live(brk_(108.55, vol + 45_000), now=t + STEP)
    assert [(a["kind"], a["confirm_passes"]) for a in fired] == [("BO_RANGE", 2)]


def test_a_checkpoint_from_before_the_gap_was_kept_still_loads():
    L = bo._lane_from({"armed": [["NEAR", "UP", 111.0, 1000.0, 1, None]],
                       "rconf": [["NEAR", "UP", 108.3, 1, 7]]})
    assert L["armed"][("NEAR", "UP")][111.0] == {"t": 1000.0, "n": 1, "trig": None, "c": 1000.0}
    assert L["rconf"][("NEAR", "UP")]["c"] == 0.0
    L["armed"][("NEAR", "UP")][111.0]["c"] = 1020.0
    back = bo._lane_from(bo._lane_blob(L))
    assert back["armed"][("NEAR", "UP")][111.0]["c"] == 1020.0 and back["rconf"] == L["rconf"]
