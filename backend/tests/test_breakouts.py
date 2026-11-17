"""
Breakout alerts (breakouts.py) and the Telegram messages they send.

What matters here is the definition holding: a sideways range broken on
volume fires, a slow uptrend that merely fits inside a box does not, a
stock already above its level before the open does not, and nothing fires
twice in a day.
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

IST = bo.IST
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def frame(closes, volume=None, end="2026-11-17", spread=0.01):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(end=pd.Timestamp(end), periods=len(closes), freq="B")
    c = pd.Series(closes, index=idx)
    v = np.full(len(closes), 1_000_000.0) if volume is None else np.asarray(volume, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread),
                         "Close": c, "Volume": v}, index=idx)


def sideways(n=80, lo=100.0, hi=110.0, period=20):
    """A range that touches its top and bottom again and again."""
    t = np.arange(n)
    return list(lo + (hi - lo) * (0.5 + 0.5 * np.sin(2 * np.pi * t / period)))


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, tmp_path):
    monkeypatch.setattr(bo, "FEED_FILE", str(tmp_path / "feed.json"))
    monkeypatch.setattr(bo, "LOG_FILE", str(tmp_path / "log.json"))
    monkeypatch.setattr(bo, "_mem", {"feed": None, "log": None, "pending": {}})
    sent = []
    fake = types.SimpleNamespace(
        send_breakouts=lambda rows, **k: sent.append(("live", rows, k)),
        send_plain=lambda text: sent.append(("plain", text, {})),
        format_breakout_close=alerts.format_breakout_close,
        health=lambda: {"configured": True})
    monkeypatch.setattr(bo, "notify", fake)
    return sent


# ---------------------------------------------------------------------------
# The definition
# ---------------------------------------------------------------------------

def test_a_range_broken_on_volume_is_a_fresh_base_breakout():
    closes = sideways(80) + [114.0]
    vol = [1_000_000.0] * 80 + [3_000_000.0]
    r = bo.read_daily(frame(closes, vol), drop_partial=False)
    assert r["fresh"]["kind"] == "BASE"
    assert r["fresh"]["sessions"] >= 40
    assert r["fresh"]["level"] == pytest.approx(110 * 1.01, rel=1e-3)
    assert r["rel_volume"] == pytest.approx(3.0)
    assert r["watch"] is None          # broke out today: not a setup for tomorrow


def test_a_slow_uptrend_that_fits_the_box_is_not_a_base():
    # Up 15% in a straight line over 60 sessions: inside an 18% box, but the
    # older half never came near the top, so it is a trend, not a range.
    closes = list(np.linspace(80, 100, 200)) + list(np.linspace(100, 115, 60)) + [116.0]
    r = bo.read_daily(frame(closes), drop_partial=False)
    assert r["fresh"] is None or r["fresh"]["kind"] != "BASE"


def test_a_long_wide_consolidation_counts_from_120_sessions():
    # About 23% wide: too loose for a short base, fine for a long one.
    closes = sideways(150, 100, 121, period=30)
    h, low, _c, _v = bo._arrays(frame(closes))
    base = bo.find_base(h, low, end=len(closes))
    assert base is not None and base["sessions"] >= bo.LONG_SESSIONS
    assert bo.MAX_WIDTH < base["width"] <= bo.LONG_MAX_WIDTH
    short = closes[-90:]
    h, low, _c, _v = bo._arrays(frame(short))
    assert bo.find_base(h, low, end=len(short)) is None


def test_a_stock_near_the_top_of_its_base_is_on_watch():
    closes = sideways(80) + [108.0]
    r = bo.read_daily(frame(closes), drop_partial=False)
    w = r["watch"]
    assert w and w["kind"] == "BASE"
    assert 0 < w["to_top_pct"] <= bo.NEAR_PCT
    # Eighty sessions is too little history for a 52-week high.
    assert "high52" not in w
    longer = bo.read_daily(frame([95.0] * 120 + sideways(80) + [108.0]), drop_partial=False)
    assert longer["watch"]["high52"] >= longer["watch"]["level"]


def test_a_stock_far_below_its_top_is_not_watched():
    closes = sideways(80) + [100.5]
    r = bo.read_daily(frame(closes, spread=0.0), drop_partial=False)
    assert r["watch"] is None


def test_a_fresh_52_week_high_after_a_quiet_spell():
    # A year of drifting under 130, then a close over it. Too wide for a base.
    closes = list(np.linspace(90, 130, 120)) + sideways(140, 95, 125, period=35) + [133.0]
    vol = [1e6] * 260 + [2.5e6]
    r = bo.read_daily(frame(closes, vol), drop_partial=False)
    assert r["fresh"] is not None
    assert r["fresh"]["level"] == pytest.approx(130 * 1.01, rel=1e-3)


def test_todays_forming_candle_is_dropped_during_the_session():
    closes = sideways(80) + [114.0]
    df = frame(closes, end="2026-11-17")
    r = bo.read_daily(df, drop_partial=True, today="2026-11-17")
    assert r["asof"] == "2026-11-16"
    assert r["fresh"] is None


def test_day_fraction_is_u_shaped_not_a_straight_line():
    assert bo.day_fraction(15) == pytest.approx(0.10)
    assert bo.day_fraction(375) == pytest.approx(1.0)
    assert bo.day_fraction(60) > 60 / 375          # the morning is heavier than average


# ---------------------------------------------------------------------------
# After the close
# ---------------------------------------------------------------------------

def _reads(monkeypatch, n_quiet=5):
    monkeypatch.setattr(bo, "MIN_SCAN", 3)
    up = bo.read_daily(frame(sideways(80) + [114.0], [1e6] * 80 + [3e6]), drop_partial=False)
    light = bo.read_daily(frame(sideways(80) + [114.0], [1e6] * 80 + [1.2e6]), drop_partial=False)
    near = bo.read_daily(frame(sideways(80) + [108.0]), drop_partial=False)
    reads = {"BRK": up, "LITE": light, "NEAR": near}
    for i in range(n_quiet):
        reads[f"Q{i}"] = bo.read_daily(frame(sideways(80) + [100.5], spread=0.0), drop_partial=False)
    return reads


def test_ingest_splits_confirmed_from_light_and_builds_the_watch(monkeypatch, fresh_state):
    after_close = dt.datetime(2026, 11, 17, 17, 5, tzinfo=IST)
    feed = bo.ingest(_reads(monkeypatch), meta={"BRK": {"sector": "Power", "leader": 71}},
                     now=after_close)
    assert [r["symbol"] for r in feed["fresh"]] == ["BRK"]
    assert feed["fresh"][0]["sector"] == "Power"
    assert [r["symbol"] for r in feed["light"]] == ["LITE"]
    assert [w["symbol"] for w in feed["watch"]] == ["NEAR"]
    # One summary, sent once, however many times the scan is re-run.
    assert [k for k, *_ in fresh_state] == ["plain"]
    bo.ingest(_reads(monkeypatch), now=after_close)
    assert [k for k, *_ in fresh_state] == ["plain"]


def test_a_mid_session_scan_sends_no_summary(monkeypatch, fresh_state):
    bo.ingest(_reads(monkeypatch), now=dt.datetime(2026, 11, 17, 11, 0, tzinfo=IST))
    assert fresh_state == []


def test_a_small_scan_does_not_replace_the_watch_list(monkeypatch):
    reads = _reads(monkeypatch)
    monkeypatch.setattr(bo, "MIN_SCAN", 50)
    assert bo.ingest(reads) is None


# ---------------------------------------------------------------------------
# During the session
# ---------------------------------------------------------------------------

def _armed(monkeypatch):
    """A watch list built after Monday's close, read on Tuesday."""
    feed = {"asof": "2026-11-16", "watch": [
        {"symbol": "NEAR", "kind": "BASE", "level": 111.0, "base_low": 99.0, "sessions": 80,
         "width_pct": 12.1, "to_top_pct": 2.7, "vol_med50": 1_000_000, "high52": 111.0},
        {"symbol": "OLD", "kind": "BASE", "level": 50.0, "base_low": 45.0, "sessions": 60,
         "width_pct": 11.0, "to_top_pct": 1.0, "vol_med50": 1_000_000}]}
    bo._mem["feed"] = feed
    return feed


def test_a_live_cross_on_volume_fires_once(monkeypatch, fresh_state):
    _armed(monkeypatch)
    at = dt.datetime(2026, 11, 17, 11, 15, tzinfo=IST)          # 120 minutes in: 42% of a day
    snap = {"NEAR": {"ltp": 112.0, "volume": 900_000, "prev_close": 108.0}}
    fired = bo.check_live(snap, now=at)
    assert [a["symbol"] for a in fired] == ["NEAR"]
    assert fired[0]["pace"] == pytest.approx(900_000 / (1_000_000 * 0.42), abs=0.06)
    assert fired[0]["exit"] == pytest.approx(112.0 * 0.92)
    assert len([k for k, *_ in fresh_state if k == "live"]) == 1
    # The next pass, and the cron tick's pass, see it already fired.
    assert bo.check_live(snap, now=at + dt.timedelta(minutes=1)) == []
    assert bo.status(now=at)["today"][0]["symbol"] == "NEAR"


def test_a_cross_on_thin_volume_waits(monkeypatch, fresh_state):
    _armed(monkeypatch)
    at = dt.datetime(2026, 11, 17, 11, 15, tzinfo=IST)
    snap = {"NEAR": {"ltp": 112.0, "volume": 200_000, "prev_close": 108.0}}
    assert bo.check_live(snap, now=at) == []
    assert bo.status(now=at)["pending"][0]["symbol"] == "NEAR"
    assert fresh_state == []


def test_already_above_before_the_open_is_not_a_breakout(monkeypatch):
    _armed(monkeypatch)
    at = dt.datetime(2026, 11, 17, 11, 15, tzinfo=IST)
    snap = {"OLD": {"ltp": 53.0, "volume": 5_000_000, "prev_close": 52.0}}
    assert bo.check_live(snap, now=at) == []


def test_nothing_fires_in_the_opening_minutes_or_from_a_stale_list(monkeypatch):
    feed = _armed(monkeypatch)
    snap = {"NEAR": {"ltp": 112.0, "volume": 5_000_000, "prev_close": 108.0}}
    assert bo.check_live(snap, now=dt.datetime(2026, 11, 17, 9, 18, tzinfo=IST)) == []
    feed["asof"] = "2026-11-01"
    assert bo.watch_symbols(now=dt.datetime(2026, 11, 17, 10, 0, tzinfo=IST)) == []
    assert bo.check_live(snap, now=dt.datetime(2026, 11, 17, 11, 0, tzinfo=IST)) == []


def test_watch_symbols_from_a_fresh_list(monkeypatch):
    _armed(monkeypatch)
    assert bo.watch_symbols(now=dt.datetime(2026, 11, 17, 9, 0, tzinfo=IST)) == ["NEAR", "OLD"]


def test_the_close_marks_live_alerts_held_or_faded(monkeypatch):
    _armed(monkeypatch)
    at = dt.datetime(2026, 11, 17, 11, 15, tzinfo=IST)
    bo.check_live({"NEAR": {"ltp": 112.0, "volume": 900_000, "prev_close": 108.0}}, now=at)
    reads = _reads(monkeypatch)
    reads["NEAR"] = dict(reads["NEAR"], asof="2026-11-17", close=109.5)
    for r in reads.values():
        r["asof"] = "2026-11-17"
    bo.ingest(reads, now=dt.datetime(2026, 11, 17, 17, 0, tzinfo=IST), send=False)
    row = bo.status(now=at)["today"][0]
    assert row["eod"] == "faded" and row["eod_close"] == 109.5


# ---------------------------------------------------------------------------
# The Telegram messages
# ---------------------------------------------------------------------------

def test_the_live_message_reads_on_a_phone():
    text = alerts.format_breakouts([bo.sample()], clock="10:42", index_pct=0.35, total_today=1)
    assert "TESTMSG" in text and "base breakout" in text
    assert "64-session (3-month) range" in text
    assert "<code>" in text and "412.50" in text and "384.74" in text
    assert "430.00 is 2.8% overhead" in text        # the 52-week high above the base
    assert "Live, not a close" in text


def test_the_public_message_carries_no_exit_or_target():
    text = alerts.format_breakout_public(bo.sample())
    assert "384.74" not in text and "463.00" not in text
    assert "Not a recommendation" in text


def test_the_close_summary_says_so_when_nothing_broke_out():
    text = alerts.format_breakout_close("2026-11-17", [], [], [], [], [])
    assert "No stock closed above" in text


def test_the_close_summary_lists_breakouts_and_the_watch():
    fresh = [{"symbol": "BRK", "kind": "BASE", "sessions": 80, "rel_volume": 3.0}]
    watch = [{"symbol": "NEAR", "kind": "BASE", "sessions": 80, "to_top_pct": 2.7, "level": 111.0}]
    text = alerts.format_breakout_close("2026-11-17", fresh, [], [], [], watch)
    assert "BRK" in text and "80d base" in text and "3.0x" in text
    assert "Watching 1 for tomorrow" in text and "NEAR" in text


# ---------------------------------------------------------------------------
# The daily bars the after-close pass reads (dhan_source.py)
# ---------------------------------------------------------------------------

def _real_dhan():
    spec = importlib.util.spec_from_file_location("dhan_source_real",
                                                  os.path.join(BACKEND, "dhan_source.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dhan_daily_bars_are_dated_by_the_indian_session(monkeypatch):
    d = _real_dhan()
    # Dhan stamps a daily candle at midnight IST: 18:30 UTC the day before.
    days = pd.bdate_range(end="2026-11-17", periods=70)
    stamps = [int((pd.Timestamp(x) - pd.Timedelta(hours=5, minutes=30)).timestamp()) for x in days]
    body = {"open": [1.0] * 70, "high": [1.0] * 70, "low": [1.0] * 70, "close": [1.0] * 70,
            "volume": [5] * 70, "timestamp": stamps}
    resp = types.SimpleNamespace(status_code=200, json=lambda: body, text="")
    monkeypatch.setattr(d, "requests", types.SimpleNamespace(post=lambda *a, **k: resp))
    monkeypatch.setattr(d, "configured", lambda: True)
    monkeypatch.setattr(d, "security_id", lambda s: "1")
    monkeypatch.setattr(d, "_throttle_hist", lambda: None)
    monkeypatch.setattr(d, "_append_today", lambda s, df: df)
    df = d.daily_ohlcv("ANY")
    assert df.index[-1] == pd.Timestamp("2026-11-17")
    assert df.index[0] == pd.Timestamp(days[0])


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
