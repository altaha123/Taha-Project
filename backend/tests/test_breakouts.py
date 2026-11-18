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
    monkeypatch.setattr(bo, "_mem", {"feed": None, "day": None})
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

    def check_live(snap, index_pct=None, fired=None):
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
    assert "<b>BUY TESTMSG</b>" in text and "Consolidation breakout" in text
    for label, value in (("Buy at", "414.10"), ("Stop loss", "411.25"), ("Target", "419.80")):
        assert label in text and value in text
    assert "Exit by 3:15 pm" in text
    # Nothing a reader has to decode.
    for jargon in ("score", "VWAP", "1:2", "index", "R "):
        assert jargon not in text
    sell = alerts.format_digest([dict(bo.sample(), direction="DOWN", call="INTRADAY")])
    assert "<b>SELL TESTMSG</b>" in sell and "Intraday call" in sell and "Sell at" in sell


def test_the_public_message_carries_no_entry_stop_or_target():
    text = alerts.format_public(bo.sample())
    assert "TESTMSG" in text and "Consolidation breakout" in text
    assert "Crossed above 412.50, the top of a 64-day consolidation, on 2.6 times" in text
    for trade in ("411.25", "419.80", "BUY", "SELL", "Exit", "Stop", "Target"):
        assert trade not in text
    assert "Not a recommendation" in text


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
