"""
The track record: every idea dated once, judged once, never rewritten, and
measured from the day it was generated.

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
    out = log.record("short", [idea("ABB")], SCAN1 + " (partial, scan in progress)", {})
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


# --- since the idea: the return the record leads with ------------------------

NOW = dt.datetime(2026, 10, 29, 6, 0, tzinfo=dt.timezone.utc)      # Thursday
INDEX = [("2026-10-23", 250.0), ("2026-10-26", 250.0), ("2026-10-27", 252.5),
         ("2026-10-28", 255.0), ("2026-10-29", 257.5)]


def test_an_open_idea_is_measured_from_its_day_to_the_latest_scan(log):
    log.record("short", [idea("ABB", price=100.0)], SCAN1, {})
    r = log.listing(prices={"ABB": 112.0}, now=NOW)["rows"][0]
    assert r["since_pct"] == 12.0 and r["since_price"] == 112.0
    assert r["since_basis"] == "latest" and r["since_days"] == 3
    # Nothing has been done to it, so the two returns are one number.
    assert r["move_pct"] == r["since_pct"]


def test_a_closed_idea_keeps_running_as_if_nothing_was_done(log):
    """The list dropped it at 99. Whoever bought it on the day of the idea and
    did nothing holds it at today's price, and that is the return to show."""
    log.record("short", [idea("ABB", price=100.0)], SCAN1, {})
    log.record("short", [], SCAN2, {"ABB": 99.0})
    r = log.listing(prices={"ABB": 120.0}, now=NOW)["rows"][0]
    assert r["status"] == "closed" and r["outcome"] == "dropped"
    assert r["move_pct"] == -1.0 and r["price_now"] == 99.0      # where the list left it
    assert r["since_pct"] == 20.0 and r["since_price"] == 120.0   # where it is now
    assert r["since_basis"] == "latest"
    assert r["days"] == 1 and r["since_days"] == 3


def test_a_stock_that_left_the_scan_is_measured_to_its_close(log):
    """No latest price exists for it. It stays in the average at the price it
    closed at; leaving it out would drop exactly the ideas that went wrong."""
    log.record("short", [idea("ABB", price=100.0, stop=92.0)], SCAN1, {})
    log.record("short", [], SCAN2, {"ABB": 90.0})
    out = log.listing(prices={}, now=NOW)
    r = out["rows"][0]
    assert r["outcome"] == "stop"
    assert r["since_pct"] == -10.0 and r["since_basis"] == "close"
    assert r["since_days"] == 1
    assert out["summary"]["since_priced"] == 1 and out["summary"]["avg_since_pct"] == -10.0


def test_the_index_is_measured_over_the_same_days(log):
    log.record("short", [idea("ABB", price=100.0)], SCAN1, {})
    out = log.listing(prices={"ABB": 112.0}, now=NOW, index=INDEX, index_name="NIFTYBEES")
    r = out["rows"][0]
    assert r["index_pct"] == 3.0                  # 250 on the 26th to 257.5 on the 29th
    assert r["vs_index_pct"] == 9.0
    assert out["index_name"] == "NIFTYBEES"
    assert "NIFTYBEES over the same days" in out["method"]
    # A {date: close} mapping reads the same as the pairs.
    assert log.listing(prices={"ABB": 112.0}, now=NOW,
                       index=dict(INDEX))["rows"][0]["index_pct"] == 3.0


def test_an_idea_made_today_has_no_index_figure_yet(log):
    """One close is not a window. 0.00% there would say the market did
    nothing, when the truth is that nothing has been measured."""
    log.record("short", [idea("ABB", price=100.0)], "29 Oct 2026, 05:10", {})
    r = log.listing(prices={"ABB": 101.0}, now=NOW, index=INDEX)["rows"][0]
    assert r["since_pct"] == 1.0
    assert r["index_pct"] is None and r["vs_index_pct"] is None


def test_without_index_closes_the_record_still_reads(log):
    log.record("short", [idea("ABB", price=100.0)], SCAN1, {})
    out = log.listing(prices={"ABB": 112.0}, now=NOW)
    assert out["index_name"] is None
    assert out["rows"][0]["index_pct"] is None
    assert out["summary"]["index_priced"] == 0 and out["summary"]["avg_vs_index_pct"] is None
    assert "over the same days" not in out["method"]


def test_the_summary_leads_with_the_return_since_the_idea(log):
    log.record("short", [idea("ABB", price=100.0), idea("TCS", price=100.0),
                         idea("INFY", price=100.0)], SCAN1, {})
    log.record("short", [idea("TCS", price=104.0)], SCAN2, {"ABB": 99.0, "INFY": 98.0})
    out = log.listing(prices={"ABB": 120.0, "TCS": 106.0, "INFY": 91.0}, now=NOW, index=INDEX)
    s = out["summary"]
    assert s["calls"] == 3 and s["since_priced"] == 3
    assert s["up_since"] == 2 and s["up_since_pct"] == 66.7
    assert s["avg_since_pct"] == pytest.approx((20 + 6 - 9) / 3, abs=0.01)
    assert s["median_since_pct"] == 6.0
    assert s["median_days"] == 3
    # The index rose 3% over the same three days, so two of the three beat it.
    assert s["index_priced"] == 3 and s["beat_index"] == 2 and s["beat_index_pct"] == 66.7
    assert s["avg_index_pct"] == 3.0
    assert s["avg_vs_index_pct"] == pytest.approx((17 + 3 - 12) / 3, abs=0.01)
    # What the list itself did with them is still counted, separately.
    assert s["outcomes"]["dropped"] == 2 and s["open"] == 1


def test_the_listing_names_the_lists_it_holds(log):
    log.record("week", [idea("ABB", setup_key="pick_week")], SCAN1, {})
    log.record("short", [idea("TCS")], SCAN1, {})
    out = log.listing(now=NOW)
    assert [h["key"] for h in out["horizons"]] == ["week", "short"]
    assert out["horizons"][0]["label"] == "This week"


def test_the_export_carries_the_return_since_the_idea(log):
    log.record("short", [idea("ABB", price=100.0)], SCAN1, {})
    text = log.export_csv(prices={"ABB": 112.0}, index=INDEX)
    head, first = text.splitlines()[:2]
    cols = head.split(",")
    row = dict(zip(cols, first.split(",")))
    assert row["called_price"] == "100.0" and row["since_price"] == "112.0"
    assert row["since_pct"] == "12.0" and row["since_basis"] == "latest"
    assert "index_pct" in cols and "vs_index_pct" in cols


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


def test_the_endpoint_measures_to_the_latest_scan_and_against_the_index(app_with_scan, monkeypatch):
    main = app_with_scan
    monkeypatch.setattr(main.ideas_engine, "select",
                        lambda p, **k: {"rows": [idea("ABB")], "available": True})
    monkeypatch.setattr(main, "_index_closes", lambda: INDEX)
    # Every list of this scan is recorded up front. Otherwise calls() records
    # the missing ones on a background thread, and whether that lands before
    # or after _record_summary() below is a race: the card read 2 calls
    # where the page had read 1, on one CI run in many.
    for h in main._call_horizons(main._state["payload"]):
        main.call_log.record(h, [idea("ABB", price=101.0)], SCAN1, {})
    monkeypatch.setitem(main._state["payload"], "factor_universe",
                        [{"symbol": "ABB", "price": 111.1}])
    out = main.calls()
    assert out["rows"][0]["since_pct"] == 10.0
    assert out["index_name"] == main.tracker.BENCHMARK
    assert "since_priced" in out["summary"]
    # The share card is drawn from the same summary the page shows.
    card = main._record_summary()
    assert card["calls"] == out["summary"]["calls"]
    assert card["avg_since_pct"] == out["summary"]["avg_since_pct"]


def test_the_index_closes_never_hold_up_the_record(app_with_scan, monkeypatch):
    """The feed read happens on its own thread. The first request gets no
    index figures, not a wait; a feed that fails is left alone for a while."""
    import threading
    main = app_with_scan
    monkeypatch.setattr(main, "_index_cache", {"day": None, "closes": None, "retry_at": 0.0})
    gate, done = threading.Event(), threading.Event()

    def slow():
        gate.wait(5)
        done.set()
        raise RuntimeError("feed down")

    monkeypatch.setattr(main.tracker, "_benchmark_frame", slow)
    assert main._index_closes() is None          # answered before the feed did
    gate.set()
    assert done.wait(5)
    for _ in range(200):
        if main._index_cache["retry_at"]:
            break
        time.sleep(0.01)
    assert main._index_cache["retry_at"] > time.time()
    monkeypatch.setattr(main.tracker, "_benchmark_frame",
                        lambda: pytest.fail("the feed was asked again inside the back-off"))
    assert main._index_closes() is None


def test_index_closes_are_read_once_a_day(app_with_scan, monkeypatch):
    import pandas as pd
    main = app_with_scan
    monkeypatch.setattr(main, "_index_cache", {"day": None, "closes": None, "retry_at": 0.0})
    frame = pd.DataFrame({"Close": [250.0, float("nan"), 255.0]},
                         index=pd.to_datetime(["2026-10-26", "2026-10-27", "2026-10-28"]).tz_localize("Asia/Kolkata"))
    monkeypatch.setattr(main.tracker, "_benchmark_frame", lambda: frame)
    main._index_closes()
    for _ in range(200):
        if main._index_cache["closes"]:
            break
        time.sleep(0.01)
    assert main._index_closes() == [("2026-10-26", 250.0), ("2026-10-28", 255.0)]
    monkeypatch.setattr(main.tracker, "_benchmark_frame",
                        lambda: pytest.fail("the feed was read twice in one day"))
    assert main._index_closes() == [("2026-10-26", 250.0), ("2026-10-28", 255.0)]


# --- the lists folded into the fundamental ones (December 2026) ---------------

def test_the_lists_logged_are_month_and_long_and_the_replaced_ones_keep_their_labels(log):
    assert log.PICK_HORIZONS == ("month", "long")
    assert {"week", "momentum", "short", "medium"} <= set(log.HORIZONS)
    # The listing names each horizon it holds from this table, so one missing
    # here would take the whole record down.
    assert set(log.HORIZON_LABEL) == set(log.HORIZONS)
    assert (log.HORIZON_LABEL["week"], log.HORIZON_LABEL["momentum"]) == ("This week", "Momentum")
    assert (log.HORIZON_LABEL["month"], log.HORIZON_LABEL["long"]) == ("Swing / This month", "Long-term compounders")
    log.record("momentum", [idea("ABB", setup_key="pick_momentum")], SCAN1, {})
    out = log.listing(now=NOW)
    assert out["horizons"] == [{"key": "momentum", "label": "Momentum"}]


def test_logging_a_tested_list_closes_what_week_and_momentum_left_open(app_with_scan, monkeypatch):
    main = app_with_scan
    main.call_log.record("week", [idea("ABB", setup_key="pick_week")], "20 Oct 2026, 05:10", {})
    main.call_log.record("momentum", [idea("TCS", setup_key="pick_momentum")], "20 Oct 2026, 05:10", {})
    monkeypatch.setattr(main.ideas_engine, "select",
                        lambda p, **k: {"rows": [idea("ABB", setup_key="pick_month")], "available": True,
                                        "list": "month"})
    main.ideas(horizon="week")
    rows = {r["horizon"]: r for r in main.call_log.listing()["rows"]}
    assert rows["week"]["status"] == rows["momentum"]["status"] == "closed"
    assert rows["week"]["outcome"] == rows["momentum"]["outcome"] == "dropped"
    assert rows["month"]["status"] == "open"
    assert main.call_log.recorded("month", SCAN1) and not main.call_log.recorded("week", SCAN1)
    # Once: the next scan finds nothing left open there to close.
    assert main.call_log.retire_replaced(SCAN2, {}) == 0
