"""
The call log: every Ideas call dated once, judged once, never rewritten.

The failures these pin are the ones that would make the log flatter itself or
lie about time — a breached stop quietly redrawn below the price, a call that
re-opens with its old date, a page view recorded as a new call, a timestamp
shown in the server's clock instead of India's.
"""
import datetime as dt
import os
import tempfile
import time

import pytest


@pytest.fixture
def log(monkeypatch):
    import call_log
    # scan.py stamps scans with the host's naive clock, which is UTC on the
    # server. Pin it, so a laptop in IST reads the fixtures the same way.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    path = os.path.join(tempfile.mkdtemp(prefix="altaha-calls-"), "call_log.db")
    monkeypatch.setattr(call_log, "DB_PATH", path)
    return call_log


def idea(sym, stance="BUY ZONE", entry=100.0, stop=92.0, t1=118.0, price=101.0,
         setup_key="momentum_breakout", setup="Momentum breakout", conviction=71.0):
    return {"symbol": sym, "name": sym.title(), "sector": "Capital Goods",
            "setup_key": setup_key, "setup": setup, "horizon": "2–6 weeks",
            "price": price, "conviction": conviction, "conviction_band": "strong",
            "plan": {"stance": stance, "entry": entry, "stop": stop, "t1": t1, "rr": 2.1}}


SCAN1 = "26 Oct 2026, 05:10"      # a Monday, 10:40 IST
SCAN2 = "27 Oct 2026, 05:10"
SCAN3 = "28 Oct 2026, 05:10"


def test_a_new_call_is_dated_by_its_scan_in_ist(log):
    out = log.record("short", [idea("ABB")], SCAN1, {"ABB": 101.0})
    assert out["recorded"] and out["opened"] == 1
    row = log.listing()["rows"][0]
    assert row["called"]["weekday"] == "Monday"
    assert row["called"]["date"] == "2026-10-26"
    assert row["called"]["time"] == "10:40 IST"
    assert row["called_price"] == 101.0
    assert row["called_stance"] == "BUY ZONE"
    assert row["events"][0]["kind"] == "called"
    assert "stop ₹92.00" in row["events"][0]["note"]


def test_the_same_scan_is_recorded_once(log):
    log.record("short", [idea("ABB")], SCAN1, {})
    again = log.record("short", [idea("ABB"), idea("TCS")], SCAN1, {})
    assert again["recorded"] is False
    assert log.listing()["total"] == 1


def test_a_call_carried_forward_keeps_its_first_date_and_price(log):
    log.record("short", [idea("ABB", price=101.0)], SCAN1, {})
    log.record("short", [idea("ABB", price=106.0)], SCAN2, {"ABB": 106.0})
    rows = log.listing(prices={"ABB": 106.0})["rows"]
    assert len(rows) == 1
    r = rows[0]
    assert r["called"]["date"] == "2026-10-26"
    assert r["called_price"] == 101.0
    assert r["scans_seen"] == 2
    assert r["move_pct"] == pytest.approx(4.95, abs=0.01)


def test_a_stance_change_is_an_event_not_a_new_call(log):
    log.record("short", [idea("ABB", stance="BREAKOUT WATCH")], SCAN1, {})
    log.record("short", [idea("ABB", stance="BUY ZONE")], SCAN2, {})
    r = log.listing()["rows"][0]
    kinds = [e["kind"] for e in r["events"]]
    assert kinds == ["called", "stance"]
    assert r["events"][1]["note"] == "BREAKOUT WATCH → BUY ZONE"
    assert r["called_stance"] == "BREAKOUT WATCH" and r["stance"] == "BUY ZONE"


def test_a_stop_is_judged_against_the_levels_before_the_redraw(log):
    """The engine may redraw a lower stop and keep listing the name. Checking
    after the redraw would hide the loss for ever."""
    log.record("short", [idea("ABB", stop=92.0)], SCAN1, {})
    redrawn = idea("ABB", stop=80.0, price=90.0)
    out = log.record("short", [redrawn], SCAN2, {"ABB": 90.0})
    assert out["closed"]["stop"] == 1
    rows = log.listing(prices={"ABB": 90.0})["rows"]
    old = [r for r in rows if r["status"] == "closed"][0]
    new = [r for r in rows if r["status"] == "open"][0]
    assert old["outcome"] == "stop" and old["closed"]["date"] == "2026-10-27"
    assert old["called"]["date"] == "2026-10-26"
    # Still on the list, so it is called again — with its own date and price.
    assert new["called"]["date"] == "2026-10-27" and new["called_price"] == 90.0


def test_a_target_closes_the_call(log):
    log.record("short", [idea("ABB", t1=118.0)], SCAN1, {})
    out = log.record("short", [], SCAN2, {"ABB": 120.0})
    assert out["closed"]["target"] == 1
    r = log.listing()["rows"][0]
    assert r["outcome"] == "target" and r["price_now"] == 120.0
    assert r["move_pct"] == pytest.approx(18.81, abs=0.01)


def test_a_name_that_leaves_the_list_is_dropped_with_a_price(log):
    log.record("short", [idea("ABB")], SCAN1, {})
    log.record("short", [idea("TCS")], SCAN2, {"ABB": 99.0, "TCS": 101.0})
    rows = {r["symbol"]: r for r in log.listing()["rows"]}
    assert rows["ABB"]["status"] == "closed" and rows["ABB"]["outcome"] == "dropped"
    assert rows["ABB"]["price_now"] == 99.0
    assert rows["TCS"]["status"] == "open"


def test_horizons_are_separate_records(log):
    log.record("short", [idea("ABB")], SCAN1, {})
    log.record("medium", [idea("ABB", setup_key="quality_compounder")], SCAN1, {})
    log.record("short", [], SCAN2, {"ABB": 100.0})
    rows = log.listing()["rows"]
    by = {r["horizon"]: r for r in rows}
    assert by["short"]["status"] == "closed"
    assert by["medium"]["status"] == "open"


def test_a_partial_scan_is_never_recorded(log):
    out = log.record("short", [idea("ABB")], SCAN1 + " (partial — scan in progress)", {})
    assert out["recorded"] is False
    assert log.listing()["total"] == 0


def test_the_summary_counts_and_the_daily_strip(log):
    log.record("short", [idea("ABB"), idea("TCS")], SCAN1, {})
    log.record("short", [idea("TCS")], SCAN3, {"ABB": 95.0, "TCS": 110.0})
    now = dt.datetime(2026, 10, 29, 6, 0, tzinfo=dt.timezone.utc)
    out = log.listing(prices={"TCS": 110.0}, now=now)
    s = out["summary"]
    assert s["calls"] == 2 and s["open"] == 1 and s["closed"] == 1
    assert s["outcomes"]["dropped"] == 1
    assert s["in_profit"] == 1 and s["priced"] == 2
    assert s["first_logged"] == "2026-10-26"
    assert out["by_day"][-1]["date"] == "2026-10-29"
    monday = [d for d in out["by_day"] if d["date"] == "2026-10-26"][0]
    assert monday["calls"] == 2 and monday["weekday"] == "Mon"


def test_open_index_is_what_the_ideas_rows_read(log):
    log.record("short", [idea("ABB")], SCAN1, {})
    ix = log.open_index("short", {"ABB": 110.0})
    hit = ix[("ABB", "momentum_breakout")]
    assert hit["called"]["weekday"] == "Monday"
    assert hit["move_pct"] == pytest.approx(8.91, abs=0.01)


def test_export_has_the_day_and_time_columns(log):
    log.record("short", [idea("ABB")], SCAN1, {})
    text = log.export_csv()
    head, first = text.splitlines()[:2]
    assert head.startswith("called_date,called_weekday,called_time,symbol")
    assert first.startswith("2026-10-26,Monday,10:40 IST,ABB")


# --- the endpoints -----------------------------------------------------------

@pytest.fixture
def app_with_scan(log, monkeypatch):
    import main
    monkeypatch.setattr(main, "call_log", log)
    payload = {"scanned_at": SCAN1, "rankings": [idea("ABB")],
               "factor_universe": [idea("ABB"), {"symbol": "TCS", "price": 3200.0}]}
    monkeypatch.setitem(main._state, "payload", payload)
    return main


def test_ideas_records_the_default_list_and_tags_rows(app_with_scan, monkeypatch):
    main = app_with_scan
    monkeypatch.setattr(main.ideas_engine, "select",
                        lambda p, **k: {"rows": [idea("ABB")], "available": True})
    out = main.ideas(horizon="short", limit=15)
    assert out["rows"][0]["call"]["called"]["date"] == "2026-10-26"
    assert main.call_log.recorded("short", SCAN1)


def test_a_widened_list_is_not_the_list_of_record(app_with_scan, monkeypatch):
    main = app_with_scan
    monkeypatch.setattr(main.ideas_engine, "select",
                        lambda p, **k: {"rows": [idea("THIN")], "available": True})
    main.ideas(horizon="short", limit=15, include_thin=True)
    assert not main.call_log.recorded("short", SCAN1)
    assert main.call_log.listing()["total"] == 0


def test_calls_endpoint_answers_while_recording(app_with_scan, monkeypatch):
    main = app_with_scan
    monkeypatch.setattr(main.ideas_engine, "select",
                        lambda p, **k: {"rows": [idea("ABB")], "available": True})
    main.call_log.record("short", [idea("ABB")], SCAN1, {})
    out = main.calls()
    assert out["latest_scan"] == SCAN1
    assert out["total"] >= 1
    assert "disclaimer" in out and "method" in out
