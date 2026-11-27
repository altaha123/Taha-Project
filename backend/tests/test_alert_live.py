"""
The loop around the breakout engine, now that it runs two lanes
(intraday.py), and the Telegram messages it sends (alerts.py).

What matters:
  * a call is followed to the last traded price after it fires — never to
    the quote's day high or low — and `outcome` stays the after-close
    verdict from 5-minute candles;
  * the log keeps every row, written whole or not at all, with old rows
    moved once to an archive the record still counts;
  * Classic's daily cap is Classic's; one break is one full card and one
    public post, whichever lane called it first;
  * Classic's record keeps its meaning, Select's sits beside it;
  * the slow, per-stock Dhan work runs in the background, never in a pass.

breakouts.py is stubbed throughout: these tests pin down the loop, not the
engine, which has its own tests in test_breakouts.py.
"""
import datetime as dt
import json
import os
import sys
import threading
import types

import numpy as np
import pandas as pd
import pytest

import alerts
import intraday

IST = intraday.IST
DAY = dt.date(2026, 11, 17)          # a Tuesday
TODAY = DAY.isoformat()


def at(h, m, s=0, day=DAY):
    return dt.datetime(day.year, day.month, day.day, h, m, s, tzinfo=IST)


# ---------------------------------------------------------------------------
# Stand-ins
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def set(self, h, m, s=0, day=DAY):
        self.t = at(h, m, s, day)


class Dhan:
    """Counts every call made to it — by any name — so a test can prove
    which ones a pass made. Quotes come from `self.quotes`."""

    def __init__(self, quotes=None):
        self.calls = {}
        self.quotes = dict(quotes or {})
        self.requested = []

    def _count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def configured(self):
        return True

    def bulk_quotes(self, syms, mode="ohlc"):
        self._count("bulk_quotes")
        self.requested.append((list(syms), mode))
        return {s: dict(self.quotes.get(s) or {"ltp": 100.0, "volume": 1, "prev_close": 99.0})
                for s in syms}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def fn(*a, **k):
            self._count(name)
            return None
        return fn


class Notify:
    """What would reach Telegram, worded by the real formatters."""

    def __init__(self, log_file=None):
        self.batches = []          # (private rows, public rows)
        self.plain = []
        self.log_file = log_file
        self.flags_on_disk = []    # what the log said when each line went out

    def send_batch(self, rows, index_pct=None, total_today=None, clock=None, public_rows=None):
        self.batches.append(([dict(a) for a in rows],
                             None if public_rows is None else [dict(a) for a in public_rows]))
        return True

    def send_plain(self, text):
        self.plain.append(text)
        if self.log_file and os.path.exists(self.log_file):
            with open(self.log_file) as f:
                self.flags_on_disk.append([{k: v for k, v in a.items() if k.startswith("tg_")}
                                           for a in json.load(f)])
        return True

    format_update = staticmethod(alerts.format_update)
    format_confirm = staticmethod(alerts.format_confirm)
    format_day_open = staticmethod(alerts.format_day_open)

    def configured(self):
        return True


def engine(batches=(), **extra):
    """A breakouts stand-in shaped like the one test_breakouts.py uses:
    check_live hands out the next prepared batch of calls."""
    seen = {"calls": []}
    queue = [list(b) for b in batches]

    def check_live(snap, index_pct=None, fired=None, log=None):
        seen["calls"].append({"fired": set(fired or ()), "log": list(log or []),
                              "symbols": sorted(snap)})
        return [dict(a) for a in (queue.pop(0) if queue else [])]

    ns = types.SimpleNamespace(watch_symbols=lambda: ["NEAR"], check_live=check_live,
                               status=lambda: {"stocks": 1, "usable": True, "asof": "2026-11-16"})
    for k, v in extra.items():
        setattr(ns, k, v)
    return ns, seen


def call(symbol="NEAR", direction="UP", time="10:00", engine=None, level=100.0,
         entry=100.5, stop=99.5, target=102.5, t1=101.5, score=70, kind="BO_PDH",
         date=TODAY, **kw):
    """A logged breakout call: one risk is 1.00 from a 100.50 entry."""
    if direction == "DOWN" and entry == 100.5:
        entry, stop, target, t1 = 99.5, 100.5, 97.5, 98.5
    a = {"date": date, "time": time, "symbol": symbol, "kind": kind, "direction": direction,
         "call": "INTRADAY", "level_name": "Yesterday's high",
         "headline": "crossed above 100.00, yesterday's high", "level": level, "price": entry,
         "rvol": 2.6, "day_rvol": 1.4, "range_pos": 0.9, "vwap": None, "entry": entry,
         "stop": stop, "t1": t1, "target": target, "rr": 2.0,
         "risk_pct": round(abs(entry - stop) / entry * 100, 2) if stop is not None else None,
         "move_pct": 1.0, "score": score,
         "regime": 0.2, "sector": "Power", "why": "Crossed above 100.00. Exit by 3:15 pm.",
         "outcome": None, "closed_at": None}
    if engine:
        a["engine"] = engine
    a.update(kw)
    return a


def quotes(**px):
    """Quotes whose day high and low sit far outside every stop and target:
    a tracker that read them would close every call on the first pass."""
    return {s: {"ltp": p, "volume": 1_000, "prev_close": 99.0, "high": p + 50, "low": p - 50}
            for s, p in px.items()}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(intraday, "LOG_FILE", str(tmp_path / "signal_log.json"))
    monkeypatch.setattr(intraday, "ARCHIVE_FILE", str(tmp_path / "signal_log_archive.jsonl"))
    monkeypatch.setattr(intraday, "MARKS_FILE", str(tmp_path / "intraday_marks.json"))
    monkeypatch.setattr(intraday, "PROFILE_FILE", str(tmp_path / "vol_profiles.json"))
    for key, value in (("alerts", []), ("watch", []), ("heartbeat_day", None), ("error", None),
                       ("regime", None), ("last_run", None), ("scanned", 0), ("running", False)):
        monkeypatch.setitem(intraday._state, key, value)
    monkeypatch.setattr(intraday, "HEARTBEAT", False)
    monkeypatch.setattr(intraday, "ann", None)
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "off")
    monkeypatch.setattr(intraday, "TELEGRAM_PUBLIC_LANES", ("classic", "select"))
    monkeypatch.setattr(intraday, "_live", {"saved": 0.0})
    monkeypatch.setattr(intraday, "_jobs", {})
    monkeypatch.setattr(intraday, "_arch", {"sig": None, "rows": [], "keys": frozenset()})
    monkeypatch.setattr(intraday, "JOB_PACE_SEC", 0.0)
    return tmp_path


@pytest.fixture
def clock(monkeypatch):
    c = Clock(at(10, 30))
    monkeypatch.setattr(intraday, "now_ist", c)
    return c


@pytest.fixture
def loop(monkeypatch, clock, isolated):
    """A pass with stand-ins all round. Returns (dhan, notify, set_engine)."""
    d = Dhan()
    n = Notify(log_file=intraday.LOG_FILE)
    monkeypatch.setattr(intraday, "dhan", d)
    monkeypatch.setattr(intraday, "notify", n)
    holder = {}

    def set_engine(batches=(), **extra):
        ns, seen = engine(batches, **extra)
        monkeypatch.setattr(intraday, "breakouts", ns)
        holder["seen"] = seen
        return seen

    set_engine()
    return d, n, set_engine


def logged():
    return intraday._state["alerts"]


# ---------------------------------------------------------------------------
# 1. Live tracking
# ---------------------------------------------------------------------------

def test_a_call_is_followed_to_the_last_price_never_the_days_high_or_low(clock):
    a = call(time="10:00")
    logged().append(a)
    clock.set(10, 1)
    # The day's high is past the target and its low past the stop — both
    # made before the call. Only the last price counts.
    intraday._track_live(quotes(NEAR=101.0))
    assert (a["live_price"], a["live_pnl_pct"], a["live_r"]) == (101.0, 0.5, 0.5)
    assert (a["mfe_pct"], a["mae_pct"], a["mfe_r"], a["mae_r"]) == (0.5, 0.0, 0.5, 0.0)
    assert a["live_outcome"] is None and a["t1_hit"] is False and a["live_at"] == "10:01:00"

    clock.set(10, 2)
    intraday._track_live(quotes(NEAR=100.0))              # a dip: the worst point moves, the best holds
    assert (a["mfe_r"], a["mae_r"], a["mae_pct"]) == (0.5, -0.5, -0.5)

    clock.set(10, 5)
    intraday._track_live(quotes(NEAR=101.6))              # the half-book level trades
    assert a["t1_hit"] is True and a["t1_time"] == "10:05" and a["mfe_r"] == 1.1
    clock.set(10, 6)
    intraday._track_live(quotes(NEAR=101.0))
    assert a["t1_time"] == "10:05"                        # set once

    clock.set(11, 5)
    intraday._track_live(quotes(NEAR=103.0))              # through the target
    assert (a["live_outcome"], a["live_time"], a["live_exit"]) == ("TARGET", "11:05", 102.5)
    assert a["live_r"] == 2.0 and a["live_pnl_pct"] == 1.99          # out at the level, not the price
    assert a["mfe_r"] == 2.5 and a["mfe_pct"] == 2.49 and a["live_price"] == 103.0
    assert a["outcome"] is None and a["closed_at"] is None          # the candles' verdict is not ours

    clock.set(11, 6)
    intraday._track_live(quotes(NEAR=99.0))               # a closed call is left alone
    assert a["live_price"] == 103.0 and a["mae_r"] == -0.5 and a["live_outcome"] == "TARGET"


def test_a_short_is_signed_its_way_and_the_stop_is_checked_before_the_target(clock):
    short = call(symbol="FAR", direction="DOWN", time="10:00")
    # Levels a single price crosses both ways (only a malformed call can):
    # the stop wins, as it does in the candle reconciliation.
    both = call(symbol="BOTH", time="10:00", entry=100.0, stop=101.0, target=100.5, t1=None)
    logged().extend([short, both])
    clock.set(10, 10)
    intraday._track_live(quotes(FAR=99.0, BOTH=100.8))
    assert (short["live_pnl_pct"], short["live_r"], short["mfe_r"]) == (0.5, 0.5, 0.5)
    assert both["live_outcome"] == "STOP" and both["live_exit"] == 101.0
    assert "t1_hit" not in both                           # no half-book level, no flag

    clock.set(10, 20)
    intraday._track_live(quotes(FAR=100.6))
    assert (short["live_outcome"], short["live_exit"], short["live_r"]) == ("STOP", 100.5, -1.0)
    assert short["live_pnl_pct"] == -1.01 and short["mae_r"] == -1.1
    assert short["outcome"] is None


def test_the_first_pass_from_315_closes_whatever_is_still_open(clock):
    a = call(time="14:00")
    b = call(symbol="FAR", time="14:10")
    logged().extend([a, b])
    clock.set(15, 14, 50)
    intraday._track_live(quotes(NEAR=101.0, FAR=100.2))
    assert a["live_outcome"] is None and b["live_outcome"] is None
    clock.set(15, 15, 10)
    intraday._track_live(quotes(NEAR=101.2))              # FAR's quote did not come back
    assert (a["live_outcome"], a["live_exit"], a["live_time"], a["live_r"]) == \
        ("OPEN_AT_CLOSE", 101.2, "15:15", 0.7)
    assert (b["live_outcome"], b["live_exit"]) == ("OPEN_AT_CLOSE", 100.2)   # the last price seen
    assert a["outcome"] is None and b["outcome"] is None


def test_only_todays_calls_already_made_are_followed(clock):
    yesterday = call(date="2026-11-16", time="10:00")
    later = call(symbol="FAR", time="11:00")             # fired after this quote was taken
    no_plan = call(symbol="BARE", time="10:00", stop=None)
    logged().extend([yesterday, later, no_plan])
    clock.set(10, 30)
    intraday._track_live(quotes(NEAR=101.0, FAR=101.0, BARE=101.0))
    assert all("live_price" not in a for a in (yesterday, later, no_plan))


def test_a_call_is_first_marked_on_the_pass_after_it_fires(loop, clock):
    d, n, set_engine = loop
    set_engine([[call(time="10:00")]])
    d.quotes["NEAR"] = {"ltp": 100.5, "volume": 1}
    clock.set(10, 0)
    fired = intraday.scan_once()
    assert [a["symbol"] for a in fired] == ["NEAR"] and "live_price" not in fired[0]
    d.quotes["NEAR"] = {"ltp": 101.0, "volume": 2, "high": 140.0, "low": 60.0}
    clock.set(10, 0, 20)
    assert intraday.scan_once() == []
    a = logged()[0]
    assert (a["live_price"], a["live_r"], a["live_at"]) == (101.0, 0.5, "10:00:20")
    clock.set(10, 0, 40)
    d.quotes["NEAR"] = {"ltp": 101.7, "volume": 3}
    intraday.scan_once()
    assert a["t1_hit"] is True and a["mfe_r"] == 1.2
    on_disk = json.load(open(intraday.LOG_FILE))[0]       # a transition is saved at once
    assert on_disk["t1_hit"] is True and on_disk["t1_time"] == "10:00"


def test_between_events_the_log_is_saved_at_most_every_live_save_sec(monkeypatch, clock):
    monkeypatch.setattr(intraday, "LIVE_SAVE_SEC", 120)
    saves = []
    monkeypatch.setattr(intraday, "_save_log", lambda: saves.append(1))
    now = {"t": 1_000.0}
    monkeypatch.setattr(intraday.time, "time", lambda: now["t"])
    logged().append(call(time="10:00"))
    for k in range(6):                                    # two minutes of quiet 20-second passes
        clock.set(10, 1, 20 * k % 60)
        intraday._track_live(quotes(NEAR=100.8))
        now["t"] += 20
    assert len(saves) == 1
    now["t"] += 1
    intraday._track_live(quotes(NEAR=100.8))
    assert len(saves) == 2
    intraday._track_live(quotes(NEAR=101.6))              # the half-book level: saved at once
    assert len(saves) == 3


# ---------------------------------------------------------------------------
# 2. Follow-ups on Telegram
# ---------------------------------------------------------------------------

ICON = {"✅": "t1", "🎯": "target", "🛑": "stop", "⏰": "close"}


@pytest.mark.parametrize("mode, expect", [
    ("off", []),
    ("target", ["target"]),
    ("t1", ["t1", "target"]),
    ("all", ["t1", "target", "stop"]),
    ("nonsense", []),                                     # an unknown mode is off
])
def test_follow_ups_go_by_alert_updates_tg(loop, clock, monkeypatch, mode, expect):
    d, n, _ = loop
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", mode)
    logged().extend([call(symbol="WIN", time="10:00"), call(symbol="LOSE", time="10:00"),
                     call(symbol="HOLD", time="10:00")])
    for hm, win, lose in (((10, 5), 101.6, 100.0), ((10, 30), 102.6, 99.4), ((15, 16), 99.0, 99.0)):
        clock.set(*hm)
        d.quotes.update(quotes(WIN=win, LOSE=lose, HOLD=100.9))
        intraday.scan_once()
    # The close at 3:15 pm is in the day's result, not a message of its own.
    assert logged()[2]["live_outcome"] == "OPEN_AT_CLOSE"
    assert [ICON[t[0]] for t in n.plain] == expect
    if "t1" in expect:
        assert n.plain[0] == ("✅ <b>WIN</b> BUY reached half-book ₹101.50 (+1.0%) · "
                              "move the stop loss to cost ₹100.50")
    if "target" in expect:
        assert "🎯 <b>WIN</b> BUY hit the target ₹102.50 (+2.0%) at 10:30 am" in n.plain
    if "stop" in expect:
        assert "🛑 <b>LOSE</b> BUY hit the stop loss ₹99.50 (−1.0%)" in n.plain
    win, lose, _hold = logged()
    assert bool(win.get("tg_t1")) == ("t1" in expect)
    assert bool(win.get("tg_target")) == ("target" in expect)
    assert bool(lose.get("tg_stop")) == ("stop" in expect)
    assert win["live_outcome"] == "TARGET" and lose["live_outcome"] == "STOP"


def test_half_book_reached_as_the_trade_ends_is_not_a_message(loop, clock, monkeypatch):
    d, n, _ = loop
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "all")
    logged().extend([call(symbol="JUMP", time="10:00"), call(symbol="LATE", time="14:00")])
    clock.set(10, 5)
    d.quotes.update(quotes(JUMP=103.0, LATE=100.8))       # straight through half-book to the target
    intraday.scan_once()
    clock.set(15, 15, 5)
    d.quotes.update(quotes(JUMP=103.0, LATE=101.6))       # half-book on the closing pass
    intraday.scan_once()
    assert [ICON[t[0]] for t in n.plain] == ["target"]
    jump, late = logged()
    assert jump["t1_hit"] and late["t1_hit"] and late["live_outcome"] == "OPEN_AT_CLOSE"


def test_a_follow_up_is_saved_before_it_is_sent_and_never_sent_twice(loop, clock, monkeypatch):
    d, n, _ = loop
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "all")
    logged().append(call(time="10:00"))
    clock.set(10, 5)
    d.quotes.update(quotes(NEAR=101.6))
    intraday.scan_once()
    assert len(n.plain) == 1 and n.flags_on_disk[0] == [{"tg_t1": True}]

    # The process restarts: the day's log is read back from the disk.
    monkeypatch.setitem(intraday._state, "alerts", intraday._load_log())
    a = logged()[0]
    assert a["t1_hit"] is True and a["tg_t1"] is True
    clock.set(10, 6)
    intraday.scan_once()
    assert len(n.plain) == 1                              # nothing sent again

    # Even a half-book event seen again (a save lost after the send) is
    # not sent twice: the flag is what decides.
    a["t1_hit"] = False
    clock.set(10, 7)
    intraday.scan_once()
    assert a["t1_hit"] is True and len(n.plain) == 1


def test_follow_ups_track_the_record_whose_card_was_sent(loop, clock, monkeypatch):
    d, n, _ = loop
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "all")
    carried = call(time="10:00", tg_card=False)           # its pair's card was the one sent
    shown = call(symbol="FAR", time="10:00", tg_card=True)
    logged().extend([carried, shown])
    clock.set(10, 5)
    d.quotes.update(quotes(NEAR=101.6, FAR=101.6))
    intraday.scan_once()
    assert len(n.plain) == 1 and "<b>FAR</b>" in n.plain[0]
    assert carried["t1_hit"] is True and not carried.get("tg_t1")


def test_a_notify_without_the_new_formatters_is_left_alone(loop, clock, monkeypatch):
    d, _n, set_engine = loop
    sent = []
    # The shape test_breakouts.py stubs notify with: no format_update or
    # format_confirm, a send_batch that takes no public_rows.
    monkeypatch.setattr(intraday, "notify", types.SimpleNamespace(
        send_batch=lambda rows, index_pct=None, total_today=None, clock=None: sent.append(rows),
        send_plain=lambda t: sent.append(t), format_day_open=lambda **k: "",
        configured=lambda: True))
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "all")
    logged().append(call(symbol="OLD", time="09:50", level=100.0))
    set_engine([[call(symbol="OLD", time="10:10", engine="select", level=100.0)],
                [call(symbol="NEW", time="10:11")]])
    clock.set(10, 10)
    d.quotes.update(quotes(OLD=101.6))
    intraday.scan_once()                                  # t1 + a Select confirm: neither can be worded
    assert sent == []
    clock.set(10, 11)
    intraday.scan_once()
    assert len(sent) == 1 and sent[0][0]["symbol"] == "NEW"


# ---------------------------------------------------------------------------
# 3. The log: atomic, archived, counted
# ---------------------------------------------------------------------------

def _archive_rows(tmp):
    path = tmp / "signal_log_archive.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def test_old_rows_move_to_the_archive_once_and_the_record_still_counts_them(clock, isolated, monkeypatch):
    monkeypatch.setattr(intraday, "ALERT_HOT_DAYS", 60)
    clock.set(16, 30)
    old = [call(symbol="OLD1", date="2026-08-03", outcome="TARGET", closed_at=102.5),
           call(symbol="OLD2", date="2026-09-17", outcome="STOP", closed_at=99.5)]   # 61 days back
    edge = call(symbol="EDGE", date="2026-09-18", outcome="STOP", closed_at=99.5)    # 60 days: hot
    recent = call(symbol="NEW", date=TODAY, outcome="OPEN_AT_CLOSE", closed_at=101.0)
    rows = old + [edge, recent]
    monkeypatch.setitem(intraday._state, "alerts", rows)
    intraday._save_log()
    hot = json.load(open(intraday.LOG_FILE))
    assert [a["symbol"] for a in hot] == ["EDGE", "NEW"]
    assert [a["symbol"] for a in logged()] == ["EDGE", "NEW"]
    assert [a["symbol"] for a in _archive_rows(isolated)] == ["OLD1", "OLD2"]

    intraday._save_log()                                  # saved again: archived once
    assert len(_archive_rows(isolated)) == 2

    # A crash between the archive's append and the hot file's rewrite: the
    # hot file still holds the old rows. The next save only trims them.
    with open(intraday.LOG_FILE, "w") as f:
        json.dump(old + [edge, recent], f)
    monkeypatch.setitem(intraday._state, "alerts", intraday._load_log())
    assert len(intraday._all_alerts()) == 4                # counted once, not twice
    intraday._save_log()
    assert len(_archive_rows(isolated)) == 2
    assert [a["symbol"] for a in json.load(open(intraday.LOG_FILE))] == ["EDGE", "NEW"]

    # The record reads the archive and the hot log together.
    s = intraday.stats()
    assert s["total_closed"] == 4 and s["overall"]["trades"] == 4
    assert s["overall"]["targets"] == 1 and s["overall"]["stops"] == 2
    assert intraday.call_record()["intraday"]["calls"] == 4


def test_past_alert_log_max_the_oldest_rows_are_archived_but_never_todays(clock, isolated, monkeypatch):
    monkeypatch.setattr(intraday, "ALERT_LOG_MAX", 3)
    clock.set(12, 0)
    rows = [call(symbol=f"D{k}", date=f"2026-11-1{k}", time="10:00") for k in (3, 4, 6)]
    rows += [call(symbol=f"T{k}", time=f"10:0{k}") for k in range(4)]
    monkeypatch.setitem(intraday._state, "alerts", rows)
    intraday._save_log()
    assert [a["symbol"] for a in json.load(open(intraday.LOG_FILE))] == ["T0", "T1", "T2", "T3"]
    assert [a["symbol"] for a in _archive_rows(isolated)] == ["D3", "D4", "D6"]


def test_a_torn_last_archive_line_is_skipped_and_the_next_append_starts_clean(clock, isolated, monkeypatch):
    clock.set(16, 30)
    path = isolated / "signal_log_archive.jsonl"
    good = call(symbol="KEPT", date="2026-07-01", outcome="TARGET", closed_at=102.5)
    path.write_text(json.dumps(good) + "\n" + '{"date": "2026-07-02", "symb')   # a crash mid-append
    assert [a["symbol"] for a in intraday._all_alerts()] == ["KEPT"]
    monkeypatch.setitem(intraday._state, "alerts",
                        [call(symbol="LATE", date="2026-07-03", outcome="STOP", closed_at=99.5)])
    intraday._save_log()
    assert [a["symbol"] for a in intraday._all_alerts()] == ["KEPT", "LATE"]
    lines = path.read_text().split("\n")
    assert lines[1] == '{"date": "2026-07-02", "symb' and json.loads(lines[2])["symbol"] == "LATE"
    assert intraday.stats()["overall"]["trades"] == 2


def test_the_log_is_written_whole_or_not_at_all(isolated, clock, monkeypatch):
    row = call()
    with open(intraday.LOG_FILE, "w") as f:
        json.dump([row], f)
    monkeypatch.setitem(intraday._state, "alerts", [row, call(symbol="FAR")])
    # The write itself fails (here: its temporary file cannot be opened).
    # The file on disk is the old one, whole; the old code had truncated it.
    monkeypatch.setattr(intraday, "_tid", lambda: 7)
    blocker = f"{intraday.LOG_FILE}.{os.getpid()}.7.tmp"
    os.mkdir(blocker)
    intraday._save_log()
    os.rmdir(blocker)
    assert json.load(open(intraday.LOG_FILE)) == [row]

    # A crash between the write and the rename: the same, and no debris.
    def crash(src, dst):
        raise OSError("disk went away")
    with monkeypatch.context() as m:
        m.setattr(intraday.os, "replace", crash)
        intraday._save_log()
    assert json.load(open(intraday.LOG_FILE)) == [row]
    assert not [p for p in os.listdir(isolated) if p.endswith(".tmp")]

    # numpy numbers from the engine are written as numbers, and a value
    # nothing knows how to write is kept as its text, not a lost day.
    monkeypatch.setitem(intraday._state, "alerts",
                        [dict(row, score=np.int64(71), rvol=np.float32(2.5), shadow={"rpos"},
                              odd=dt.time(10, 5))])
    intraday._save_log()
    back = json.load(open(intraday.LOG_FILE))[0]
    assert back["score"] == 71 and back["rvol"] == 2.5 and back["shadow"] == ["rpos"]
    assert back["odd"] == "10:05:00"


def test_an_archive_that_cannot_be_written_keeps_its_rows_hot(isolated, clock, monkeypatch):
    clock.set(16, 30)
    old, new = call(symbol="OLD", date="2026-06-01"), call(symbol="NEW")
    monkeypatch.setitem(intraday._state, "alerts", [old, new])
    monkeypatch.setattr(intraday, "ARCHIVE_FILE", str(isolated / "no-such-dir" / "a.jsonl"))
    intraday._save_log()
    assert [a["symbol"] for a in json.load(open(intraday.LOG_FILE))] == ["OLD", "NEW"]
    assert [a["symbol"] for a in logged()] == ["OLD", "NEW"]


def test_a_log_that_does_not_parse_is_set_aside_not_overwritten(isolated):
    with open(intraday.LOG_FILE, "w") as f:
        f.write('[{"date": "2026-11-10", "symbol": "HALF"')
    assert intraday._load_log() == []
    assert open(intraday.LOG_FILE + ".bad").read().startswith('[{"date"')
    assert not os.path.exists(intraday.LOG_FILE)


# ---------------------------------------------------------------------------
# 4. The daily cap is Classic's
# ---------------------------------------------------------------------------

def test_select_calls_neither_use_up_the_classic_cap_nor_the_classic_fired_set(loop, clock, monkeypatch):
    d, n, set_engine = loop
    monkeypatch.setattr(intraday, "MAX_ALERTS_DAY", 3)
    earlier = [call(symbol="C1", time="09:40"),
               call(symbol="S1", time="09:45", engine="select"),
               call(symbol="S2", time="09:50", engine="select", direction="DOWN"),
               call(symbol="V1", time="09:55", kind="RVOL")]      # a legacy volume alert
    logged().extend(earlier)
    seen = set_engine([[call(symbol="A", time="10:30", score=80),
                        call(symbol="B", time="10:30", score=60),
                        call(symbol="S3", time="10:30", engine="select", score=75)]])
    clock.set(10, 30)
    fired = intraday.scan_once()
    # Room for one more Classic call (C1 and V1 count; S1 and S2 do not):
    # the best one, and the Select call beside it.
    assert [(a["symbol"], a.get("engine", "classic")) for a in fired] == \
        [("A", "classic"), ("S3", "select")]
    got = seen["calls"][0]
    assert got["fired"] == {("C1", "UP")}                 # Classic's own calls only
    assert [a["symbol"] for a in got["log"]] == ["C1", "S1", "S2"]   # today's breakout rows
    assert sorted(intraday.status()["lanes"].items()) == [("classic", 3), ("select", 3)]


def test_a_full_classic_day_still_lets_select_through(loop, clock, monkeypatch):
    _d, _n, set_engine = loop
    monkeypatch.setattr(intraday, "MAX_ALERTS_DAY", 1)
    logged().append(call(symbol="C1", time="09:40"))
    set_engine([[call(symbol="A", time="10:30"),
                 call(symbol="S", time="10:30", engine="select")]])
    clock.set(10, 30)
    assert [a["symbol"] for a in intraday.scan_once()] == ["S"]


def test_select_has_only_a_runaway_guard_here(loop, clock, monkeypatch):
    _d, _n, set_engine = loop
    monkeypatch.setattr(intraday, "SELECT_HARD_CAP", 2)
    logged().append(call(symbol="S0", time="09:40", engine="select"))
    set_engine([[call(symbol=f"S{k}", time="10:30", engine="select", score=60 + k)
                 for k in range(1, 4)]])
    clock.set(10, 30)
    assert [a["symbol"] for a in intraday.scan_once()] == ["S3"]


def test_an_engine_without_the_log_argument_is_still_called(loop, clock, monkeypatch):
    _d, _n, _set = loop
    got = {}

    def old_check_live(snap, now=None, index_pct=None, fired=None):
        got["fired"] = fired
        return [call(symbol="A", time="10:30")]
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        watch_symbols=lambda: ["A"], check_live=old_check_live, status=lambda: {}))
    clock.set(10, 30)
    assert [a["symbol"] for a in intraday.scan_once()] == ["A"] and got["fired"] == set()


# ---------------------------------------------------------------------------
# 5. One break: one full card, one public post
# ---------------------------------------------------------------------------

def test_both_lanes_in_one_pass_send_one_card_select_s(loop, clock):
    _d, n, set_engine = loop
    set_engine([[call(symbol="X", time="10:30", level=100.0, score=70),
                 call(symbol="X", time="10:30", level=100.1, score=82, engine="select",
                      entry=100.6, stop=99.9, target=102.0, t1=101.3)]])
    clock.set(10, 30)
    fired = intraday.scan_once()
    assert len(fired) == 2 and len(n.batches) == 1 and n.plain == []
    private, public = n.batches[0]
    assert [a.get("engine") for a in private] == ["select"]
    assert [a.get("engine") for a in public] == ["select"]
    by = {a.get("engine", "classic"): a for a in logged()}
    assert by["classic"]["select_time"] == "10:30" and by["classic"]["select_score"] == 82
    assert by["select"]["pair_time"] == "10:30"
    assert (by["classic"]["tg_card"], by["select"]["tg_card"]) == (False, True)
    assert (by["classic"]["tg_public"], by["select"]["tg_public"]) == (False, True)


def test_select_confirming_an_earlier_classic_call_is_a_short_line(loop, clock):
    _d, n, set_engine = loop
    earlier = call(symbol="X", time="10:02", level=100.0, tg_card=True, tg_public=True)
    logged().append(earlier)
    set_engine([[call(symbol="X", time="10:20", level=100.05, score=85, engine="select",
                      entry=100.7, stop=100.0, target=102.1)]])
    clock.set(10, 20)
    intraday.scan_once()
    assert n.batches == []                                # no second card, no second public post
    assert n.plain == ["★ <b>X</b> · Select confirms the 10:02 am call\n"
                       "💰 Buy at <b>₹100.70</b> · 🛑 Stop loss <b>₹100.00</b> · "
                       "🎯 Target <b>₹102.10</b>"]
    sel = logged()[1]
    assert (earlier["select_time"], earlier["select_score"], sel["pair_time"]) == ("10:20", 85, "10:02")
    assert sel["tg_card"] is False and sel["tg_public"] is False


@pytest.mark.parametrize("lanes", [("select",), "select"])     # a tuple, or the env's text
def test_a_select_only_public_channel_gets_the_select_call_and_never_twice(loop, clock, monkeypatch, lanes):
    _d, n, set_engine = loop
    monkeypatch.setattr(intraday, "TELEGRAM_PUBLIC_LANES", lanes)
    set_engine([[call(symbol="Y", time="10:00", level=100.0)],
                [call(symbol="Y", time="10:15", level=100.0, engine="select")],
                [call(symbol="Z", time="10:20", engine="select", level=250.0)]])
    clock.set(10, 0)
    intraday.scan_once()
    assert [(len(p), len(q)) for p, q in n.batches] == [(1, 0)]       # the card, not the channel
    clock.set(10, 15)
    intraday.scan_once()
    assert len(n.plain) == 1 and "Select confirms the 10:00 am call" in n.plain[0]
    assert n.batches[1][0] == [] and [a["symbol"] for a in n.batches[1][1]] == ["Y"]
    assert n.batches[1][1][0]["engine"] == "select"
    clock.set(10, 20)
    intraday.scan_once()
    assert [a["symbol"] for a in n.batches[2][1]] == ["Z"]


def test_classic_after_an_earlier_select_call_sends_no_second_card(loop, clock):
    _d, n, set_engine = loop
    first = call(symbol="Q", time="10:00", engine="select", level=100.0, tg_card=True, tg_public=True)
    logged().append(first)
    set_engine([[call(symbol="Q", time="10:30", level=100.1)]])
    clock.set(10, 30)
    intraday.scan_once()
    assert n.batches == [] and n.plain == []
    classic = logged()[1]
    assert classic["tg_card"] is False and classic["select_time"] == "10:00"
    assert first["pair_time"] == "10:30"


def test_different_levels_are_different_breaks(loop, clock):
    _d, n, set_engine = loop
    set_engine([[call(symbol="X", time="10:30", level=100.0),
                 call(symbol="X", time="10:30", level=101.0, engine="select"),
                 call(symbol="X", time="10:30", level=100.0, direction="DOWN", engine="select")]])
    clock.set(10, 30)
    intraday.scan_once()
    private, public = n.batches[0]
    assert len(private) == 3 and len(public) == 3
    assert not any(a.get("pair_time") or a.get("select_time") for a in logged())


def test_a_classic_only_day_routes_exactly_as_before(loop, clock):
    _d, n, set_engine = loop
    set_engine([[call(symbol="A", time="10:30", score=60), call(symbol="B", time="10:30", score=90)]])
    clock.set(10, 30)
    intraday.scan_once()
    private, public = n.batches[0]
    assert [a["symbol"] for a in private] == ["B", "A"] == [a["symbol"] for a in public]


def test_send_batch_posts_public_rows_and_a_public_only_batch(monkeypatch):
    posts = []
    monkeypatch.setattr(alerts, "TG_PUBLIC", "@chan")
    monkeypatch.setattr(alerts, "TG_CHAT", "me")
    monkeypatch.setattr(alerts, "WA_TOKEN", "")
    monkeypatch.setattr(alerts, "_post", lambda chat, text, html_mode=True: posts.append((chat, text)) or (True, "sent"))
    monkeypatch.setitem(alerts._LAST, "last_hash", None)
    a, b = call(symbol="AAA"), call(symbol="BBB", engine="select")
    assert alerts.send_batch([a, b], public_rows=[b]) is True
    assert [c for c, _t in posts] == ["me", "@chan"] and "<b>BBB</b>" in posts[1][1]
    posts.clear()
    assert alerts.send_batch([], public_rows=[a]) is False   # no private digest, still posted
    assert [c for c, _t in posts] == ["@chan"]
    posts.clear()
    alerts.send_batch([call(symbol=f"S{k}") for k in range(7)])
    assert [c for c, _t in posts].count("@chan") == 5        # still at most five


# ---------------------------------------------------------------------------
# 6. The record: Classic's as it was, Select's beside it
# ---------------------------------------------------------------------------

def _record_rows():
    base = {"date": "2026-11-17", "time": "10:42", "symbol": "X", "kind": "BO_BASE",
            "entry": 100.0, "stop": 99.0, "target": 102.0, "rr": 2.0, "score": 70, "rvol": 2.5}
    return [dict(base, direction="UP", outcome="TARGET", closed_at=102.0),
            dict(base, direction="UP", outcome="STOP", closed_at=99.0),
            dict(base, direction="UP", outcome="OPEN_AT_CLOSE", closed_at=100.5),
            dict(base, direction="DOWN", kind="BO_PDL", stop=101.0, target=98.0,
                 outcome="OPEN_AT_CLOSE", closed_at=99.5)]


def _page_rows():
    base = {"date": "2026-11-17", "time": "10:42", "symbol": "X", "kind": "BO_BASE",
            "call": "CONSOLIDATION", "direction": "UP", "entry": 100.0, "stop": 99.0, "target": 102.0}
    return [dict(base, outcome="TARGET", closed_at=102.0),
            dict(base, outcome="STOP", closed_at=99.0),
            dict(base, kind="BO_PDL", call="INTRADAY", direction="DOWN", stop=101.0, target=98.0,
                 outcome="OPEN_AT_CLOSE", closed_at=99.5),
            dict(base, kind="RVOL", call=None, outcome="STOP", closed_at=99.0)]


def _select_rows():
    base = {"date": "2026-11-17", "time": "11:05", "symbol": "S", "kind": "BO_HOD", "engine": "select",
            "call": "INTRADAY", "direction": "UP", "entry": 100.0, "stop": 99.0, "target": 102.0,
            "score": 88, "rvol": 9.0}
    return [dict(base, outcome="TARGET", closed_at=102.0), dict(base, outcome="TARGET", closed_at=103.0),
            dict(base, outcome="STOP", closed_at=98.0, direction="DOWN", stop=101.0, target=98.0)]


OLD_KEYS = ("by_signal", "by_direction", "by_hour", "by_rvol_bucket", "by_score_bucket",
            "overall", "calls", "total_closed", "note")


def test_select_rows_change_nothing_in_the_record_classic_always_had(monkeypatch):
    for rows in (_record_rows(), _page_rows()):
        monkeypatch.setitem(intraday._state, "alerts", rows)
        before = {k: intraday.stats()[k] for k in OLD_KEYS}
        monkeypatch.setitem(intraday._state, "alerts", rows + _select_rows())
        after = {k: intraday.stats()[k] for k in OLD_KEYS}
        assert before == after
    # And what test_breakouts.py pins, still true with Select in the log.
    monkeypatch.setitem(intraday._state, "alerts", _record_rows() + _select_rows())
    s = intraday.stats()
    assert s["overall"] == {"trades": 4, "win_rate": 75, "targets": 1, "stops": 1,
                            "expectancy_R": 0.5, "total_R": 2.0}
    assert s["by_signal"]["BO_BASE"]["trades"] == 3 and s["by_direction"]["DOWN"]["trades"] == 1
    monkeypatch.setitem(intraday._state, "alerts", _page_rows() + _select_rows())
    rec = intraday.stats()["calls"]
    assert rec["consolidation"] == {"calls": 2, "target": 1, "stop": 1, "closed": 0,
                                    "profitable": 1, "avg_pct": 0.5}
    assert rec["intraday"] == {"calls": 1, "target": 0, "stop": 0, "closed": 1,
                               "profitable": 1, "avg_pct": 0.5}


def test_each_lane_keeps_its_own_record(monkeypatch):
    c = {"date": "2026-11-17", "symbol": "C", "direction": "UP", "entry": 100.0, "stop": 99.0,
         "target": 102.0, "score": 70, "rvol": 2.5, "call": "INTRADAY"}
    rows = [
        dict(c, time="09:40", kind="BO_BASE", call="CONSOLIDATION", window="open", setup="Base breakout",
             outcome="TARGET", closed_at=102.0, shadow=["rpos"], mfe_pct=2.3, mae_pct=-0.2,
             mfe_r=2.3, mae_r=-0.2, t1_hit=True),
        dict(c, time="11:00", kind="BO_PDH", window="mid", setup="Yesterday's high", outcome="STOP",
             closed_at=99.0, shadow=["rpos", "pdh"], mfe_pct=0.4, mae_pct=-1.1, mfe_r=0.4,
             mae_r=-1.1, t1_hit=False),
        # Logged before the lanes: no window, setup, shadow or live fields.
        dict(c, time="13:00", kind="BO_PDH", outcome="OPEN_AT_CLOSE", closed_at=100.5),
        dict(c, time="10:10", kind="RVOL", outcome="STOP", closed_at=99.0),   # legacy volume alert
        dict(c, time="09:50", kind="BO_BASE", engine="select", window="open", setup="Base breakout",
             outcome="TARGET", closed_at=102.0, mfe_r=2.1, mae_r=-0.3, mfe_pct=2.1, mae_pct=-0.3,
             t1_hit=True, score=84),
        dict(c, time="11:20", kind="BO_HOD", engine="select", window="mid", setup="Fresh day high",
             outcome="STOP", closed_at=99.0, t1_hit=False, score=79),
    ]
    monkeypatch.setitem(intraday._state, "alerts", rows)
    s = intraday.stats()
    assert s["overall"]["trades"] == 4                    # Classic and the legacy alert, not Select

    xkeys = {"trades", "win_rate", "targets", "stops", "expectancy_R", "total_R",
             "avg_mfe_pct", "avg_mae_pct", "avg_mfe_r", "avg_mae_r", "t1_rate"}
    cl, se = s["engines"]["classic"], s["engines"]["select"]
    assert set(cl) == set(se) == {"overall", "by_setup", "by_window", "by_direction",
                                  "by_score_bucket", "calls"}
    assert set(cl["overall"]) == xkeys
    assert cl["overall"]["trades"] == 3 and cl["overall"]["t1_rate"] == 50
    assert (cl["overall"]["avg_mfe_r"], cl["overall"]["avg_mae_r"]) == (1.35, -0.65)
    assert list(cl["by_window"]) == ["open", "mid", "pm"]            # session order; old row by its time
    assert list(cl["by_setup"]) == ["Yesterday's high", "Base breakout"]   # busiest first; old by its kind
    assert cl["by_setup"]["Yesterday's high"]["trades"] == 2
    assert cl["by_window"]["pm"]["avg_mfe_r"] is None and cl["by_window"]["pm"]["t1_rate"] is None
    assert se["overall"]["trades"] == 2 and se["overall"]["t1_rate"] == 50
    assert list(se["by_setup"]) == ["Base breakout", "Fresh day high"]
    assert se["by_score_bucket"] == {"80+": se["by_score_bucket"]["80+"],
                                     "65-79": se["by_score_bucket"]["65-79"]}
    assert s["by_window"] == cl["by_window"] and s["by_setup"] == cl["by_setup"]

    sh = s["by_shadow"]
    assert set(sh) == {"rpos", "extended", "book", "sector", "pdh"}
    assert sh["rpos"]["failed"]["trades"] == 2 and sh["rpos"]["passed"] is None
    assert sh["pdh"]["failed"]["stops"] == 1 and sh["pdh"]["passed"]["targets"] == 1
    assert sh["book"]["failed"] is None and sh["book"]["passed"]["trades"] == 2

    assert s["calls_by_engine"]["classic"] == s["calls"]
    assert s["calls_by_engine"]["select"]["intraday"]["calls"] == 2
    assert s["calls_by_engine"]["classic"]["consolidation"]["calls"] == 1
    assert cl["calls"] == s["calls"] and se["calls"] == s["calls_by_engine"]["select"]


# ---------------------------------------------------------------------------
# 7. Marking outcomes after the close
# ---------------------------------------------------------------------------

def _bars(day, start=(10, 0), end=(15, 10), high=103.0, low=100.0, close=101.0):
    t = pd.Timestamp(f"{day} {start[0]:02d}:{start[1]:02d}")
    stop = pd.Timestamp(f"{day} {end[0]:02d}:{end[1]:02d}")
    idx = pd.date_range(t, stop, freq="5min")
    n = len(idx)
    return pd.DataFrame({"Open": [close] * n, "High": [high] * n, "Low": [low] * n,
                         "Close": [close] * n, "Volume": [1000.0] * n}, index=idx)


def test_with_no_candles_a_live_result_is_used_before_the_daily_bar(clock, monkeypatch):
    clock.set(16, 5)
    daily = pd.DataFrame({"Open": [100.0], "High": [103.0], "Low": [99.0], "Close": [101.0],
                          "Volume": [1.0]}, index=[pd.Timestamp(TODAY)])
    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(
        intraday_ohlcv=lambda *a, **k: None, daily_ohlcv=lambda *a, **k: daily))
    won = call(time="10:00", live_outcome="TARGET", live_exit=102.5, live_time="11:00")
    flat = call(symbol="FLAT", time="14:00", live_outcome="OPEN_AT_CLOSE", live_exit=100.9)
    blind = call(symbol="BLIND", time="10:00")
    logged().extend([won, flat, blind])
    assert intraday.mark_outcomes() == 3
    assert (won["outcome"], won["approx"], won["source"], won["r"], won["pnl_pct"]) == \
        ("TARGET", True, "live", 2.0, 1.99)
    assert (flat["outcome"], flat["closed_at"], flat["r"], flat["source"]) == \
        ("OPEN_AT_CLOSE", 100.9, 0.4, "live")
    # Nothing live: the daily bar, as before — whose low (99) is under the stop.
    assert (blind["outcome"], blind["approx"], blind["source"]) == ("STOP", True, "daily")
    assert json.load(open(intraday.LOG_FILE))[0]["source"] == "live"


def test_candles_still_overrule_the_live_result(clock, monkeypatch):
    clock.set(16, 5)
    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(
        intraday_ohlcv=lambda *a, **k: _bars(TODAY, high=103.0, low=100.0),
        daily_ohlcv=lambda *a, **k: None))
    a = call(time="10:00", live_outcome="STOP", live_exit=99.5)
    logged().append(a)
    assert intraday.mark_outcomes() == 1
    assert (a["outcome"], a["approx"], a["source"]) == ("TARGET", False, "candles")
    assert a["live_outcome"] == "STOP"                    # the live record is left as it was


# ---------------------------------------------------------------------------
# 8. Volume profiles keyed by the bar's end
# ---------------------------------------------------------------------------

def _session(day, vol, bars=75, tz=None):
    idx = pd.date_range(pd.Timestamp(f"{day} 09:15"), periods=bars, freq="5min")
    if tz:
        idx = idx.tz_localize(IST).tz_convert(tz)
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                         "Volume": float(vol)}, index=idx)


def _week(tz=None):
    return pd.concat([_session("2026-11-12", 100, tz=tz), _session("2026-11-13", 200, tz=tz),
                      _session("2026-11-16", 300, tz=tz),
                      _session("2026-11-17", 10_000, bars=30, tz=tz)])   # today, half-formed


@pytest.mark.parametrize("tz", [None, "UTC"])
def test_a_profile_is_keyed_by_bar_end_from_whole_sessions(monkeypatch, tz):
    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(intraday_ohlcv=lambda *a, **k: _week(tz)))
    prof = intraday.build_profile("ANY")
    assert 0 not in prof and prof[5] == 200.0             # the 09:15 bar has traded by minute 5
    assert prof[10] == 400.0 and prof[375] == 15_000.0    # median of 100/200/300 a bar, summed
    vals = intraday.build_bo_profile("ANY")
    assert len(vals) == 75 and vals[0] == 200.0 and vals[-1] == 15_000.0
    assert intraday.expected_volume(prof, 5) == 200.0


def test_a_half_formed_session_is_not_a_profile(monkeypatch):
    one = pd.concat([_session("2026-11-16", 300), _session("2026-11-17", 300, bars=59)])
    monkeypatch.setattr(intraday, "dhan", types.SimpleNamespace(intraday_ohlcv=lambda *a, **k: one))
    assert intraday.build_profile("ANY") is None and intraday.build_bo_profile("ANY") is None


def test_a_profile_file_from_the_old_clock_is_not_read(monkeypatch, isolated, clock):
    clock.set(9, 30)
    with open(intraday.PROFILE_FILE, "w") as f:
        json.dump({"day": TODAY, "profiles": {"X": {"0": 1.0}}, "levels": {}}, f)
    monkeypatch.setitem(intraday._state, "profiles", {})
    intraday._load_profiles()
    assert intraday._state["profiles"] == {}
    monkeypatch.setitem(intraday._state, "profile_day", TODAY)
    monkeypatch.setitem(intraday._state, "profiles", {"X": {5: 1.0}})
    monkeypatch.setitem(intraday._state, "levels", {})
    intraday._save_profiles()
    monkeypatch.setitem(intraday._state, "profiles", {})
    intraday._load_profiles()
    assert intraday._state["profiles"] == {"X": {5: 1.0}}


# ---------------------------------------------------------------------------
# 9. The messages
# ---------------------------------------------------------------------------

SAMPLE = {"date": "", "time": "10:42", "symbol": "TESTMSG", "kind": "BO_BASE", "direction": "UP",
          "call": "CONSOLIDATION", "level_name": "The top of a 64-day consolidation",
          "headline": "crossed above 412.50, the top of a 64-day consolidation",
          "level": 412.50, "price": 414.10, "rvol": 2.6, "day_rvol": 1.4, "range_pos": None,
          "vwap": 410.85, "entry": 414.10, "stop": 411.25, "t1": 416.95, "target": 419.80,
          "rr": 2.0, "risk_pct": 0.69, "move_pct": 1.8, "score": 74, "regime": 0.35,
          "sector": "Power",
          "why": ("Crossed above 412.50, the top of a 64-day consolidation, on 2.6 times its "
                  "normal volume. Exit by 3:15 pm."),
          "outcome": None, "closed_at": None}
SELL = dict(SAMPLE, symbol="M&M", direction="DOWN", call="INTRADAY", kind="BO_PDL",
            level_name="Yesterday's low", move_pct=-1.2,
            filing={"line": "Board meeting outcome", "category": "Outcome", "importance": "high"})
SELECT = dict(SAMPLE, engine="select", setup="Base breakout", window="mid", score=81,
              range_pos=0.94, confirm_passes=2, shadow=[])

# What alerts.py printed for these before there were two lanes, byte for byte.
GOLDEN = {
    "call": ("🟢 BUY <b>TESTMSG</b>\n🚀 <b>Consolidation breakout</b>  ·  10:42 am\n"
             "━━━━━━━━━━━━━━━\n💰 Buy at  <b>₹414.10</b>\n🛑 Stop loss  <b>₹411.25</b>\n"
             "🎯 Target  <b>₹419.80</b>\n━━━━━━━━━━━━━━━\n📈 Crossed above <b>₹412.50</b>\n"
             "🧱 The top of a 64-day consolidation\n🔊 Volume <b>2.6×</b> normal\n"
             "⏰ Exit by 3:15 pm\n\n#TESTMSG"),
    "call_sell": ("🔴 SELL <b>M&amp;M</b>\n⚡ <b>Intraday call</b>  ·  10:42 am\n━━━━━━━━━━━━━━━\n"
                  "💰 Sell at  <b>₹414.10</b>\n🛑 Stop loss  <b>₹411.25</b>\n🎯 Target  <b>₹419.80</b>\n"
                  "━━━━━━━━━━━━━━━\n📉 Fell below <b>₹412.50</b>\n📍 Yesterday's low\n"
                  "🔊 Volume <b>2.6×</b> normal\n⏰ Exit by 3:15 pm\n📎 Board meeting outcome\n\n#MM"),
    "public": ("<b>TESTMSG</b>  🟢 ▲ +1.8%\n🚀 <b>Consolidation breakout</b>  ·  10:42 am\n"
               "━━━━━━━━━━━━━━━\n📈 Crossed above <b>₹412.50</b>\n🧱 The top of a 64-day consolidation\n"
               "🔊 Volume <b>2.6×</b> normal\n💹 Now <b>₹414.10</b>\n━━━━━━━━━━━━━━━\n"
               "#TESTMSG #Breakout #NSE\n<i>Altaha Screener · a market observation, not a recommendation.</i>"),
    "public_sell": ("<b>M&amp;M</b>  🔴 ▼ −1.2%\n⚡ <b>Intraday call</b>  ·  10:42 am\n━━━━━━━━━━━━━━━\n"
                    "📉 Fell below <b>₹412.50</b>\n📍 Yesterday's low\n🔊 Volume <b>2.6×</b> normal\n"
                    "💹 Now <b>₹414.10</b>\n📎 Board meeting outcome\n━━━━━━━━━━━━━━━\n#MM #Intraday #NSE\n"
                    "<i>Altaha Screener · a market observation, not a recommendation.</i>"),
    "day_result": ("<b>ALTAHA · today's calls</b> · 18 Nov\n"
                   "3 calls: 1 hit target, 1 hit stop loss, 1 closed at 3:15 pm\n"
                   "<code>BUY  A            +1.4%\nSELL B            -0.4%\nBUY  C            +0.3%</code>"),
    "day_open": ("<b>ALTAHA · live</b>\nWatching 400 stocks, checked every 20 seconds. "
                 "Calls come from 9:20 am to 3:00 pm."),
}


@pytest.mark.parametrize("engine_", [None, "classic"])
def test_a_classic_card_is_byte_for_byte_what_it_was(engine_):
    def lane(a):
        return dict(a, engine=engine_) if engine_ else dict(a)
    assert alerts.format_call(lane(SAMPLE)) == GOLDEN["call"]
    assert alerts.format_call(lane(SELL)) == GOLDEN["call_sell"]
    assert alerts.format_public(lane(SAMPLE)) == GOLDEN["public"]
    assert alerts.format_public(lane(SELL)) == GOLDEN["public_sell"]
    assert alerts.format_digest([lane(SAMPLE)]) == GOLDEN["call"] + "\n\n<i>Not investment advice.</i>"
    rows = [dict(lane(SAMPLE), symbol="A", outcome="TARGET", pnl_pct=1.38),
            dict(lane(SAMPLE), symbol="B", direction="DOWN", outcome="STOP", pnl_pct=-0.44),
            dict(lane(SAMPLE), symbol="C", outcome="OPEN_AT_CLOSE", pnl_pct=0.3)]
    assert alerts.format_day_result("18 Nov", rows) == GOLDEN["day_result"]
    assert alerts.format_day_open(stocks=400, levels_asof="2026-11-16", index_pct=0.2) == GOLDEN["day_open"]


def test_a_select_card_says_so_on_one_line_under_the_title():
    text = alerts.format_call(SELECT)
    lines = text.split("\n")
    assert lines[0] == "🟢 BUY <b>TESTMSG</b>"
    assert lines[1] == "★ <b>Select</b> · one of today's strongest setups"
    assert lines[2] == "🚀 <b>Consolidation breakout</b>  ·  10:42 am"
    assert "\n".join(lines[:1] + lines[2:]) == GOLDEN["call"]          # and nothing else differs
    for jargon in ("score", "VWAP", "index", "1:2", "R "):
        assert jargon not in text
    vwap = dict(SELECT, kind="BO_VWAP", level_name="Reclaimed VWAP after a pullback")
    assert "VWAP" not in alerts.format_call(vwap)
    assert "the day's average price" in alerts.format_call(vwap)


@pytest.mark.parametrize("kind", sorted(k for k in alerts.KIND_LABEL if k.startswith("BO_")))
@pytest.mark.parametrize("engine_", ["classic", "select"])
def test_a_public_post_never_carries_a_trade(kind, engine_):
    assert {"BO_HOD", "BO_LOD", "BO_VWAP", "BO_VWAP_DN"} <= set(alerts.KIND_LABEL)
    for side in ("UP", "DOWN"):
        a = dict(SAMPLE, kind=kind, engine=engine_, direction=side,
                 call="INTRADAY" if kind.endswith(("HOD", "LOD", "VWAP", "VWAP_DN")) else "CONSOLIDATION")
        text = alerts.format_public(a)
        for trade in ("BUY", "SELL", "Entry", "Stop", "Target", "Exit", "411.25", "419.80", "416.95"):
            assert trade not in text, (kind, engine_, side, trade)
        assert "not a recommendation" in text
        assert ("★ <b>Select</b>" in text) == (engine_ == "select")


def test_the_follow_up_lines_read_right():
    a = dict(SAMPLE, live_time="11:05", live_exit=416.0)
    assert alerts.format_update(a, "t1") == ("✅ <b>TESTMSG</b> BUY reached half-book ₹416.95 (+0.7%) · "
                                             "move the stop loss to cost ₹414.10")
    assert alerts.format_update(a, "target") == "🎯 <b>TESTMSG</b> BUY hit the target ₹419.80 (+1.4%) at 11:05 am"
    assert alerts.format_update(a, "stop") == "🛑 <b>TESTMSG</b> BUY hit the stop loss ₹411.25 (−0.7%)"
    assert alerts.format_update(a, "close") == "⏰ <b>TESTMSG</b> BUY closed at 3:15 pm · ₹416.00 (+0.5%)"
    short = dict(SELL, entry=100.0, stop=101.0, t1=99.0, target=98.0)
    assert alerts.format_update(short, "t1").startswith("✅ <b>M&amp;M</b> SELL reached half-book ₹99.00 (+1.0%)")
    assert alerts.format_update(short, "stop").endswith("hit the stop loss ₹101.00 (−1.0%)")
    assert alerts.format_update(dict(SELECT), "t1").startswith("✅ ★ <b>TESTMSG</b> BUY")
    assert alerts.format_update(dict(SAMPLE, t1=None), "t1") == ""      # nothing to say, nothing sent
    assert alerts.format_update(SAMPLE, "teleport") == ""


def test_the_confirm_line_carries_selects_own_numbers():
    text = alerts.format_confirm(dict(SELECT, pair_time="10:02", entry=414.6, stop=412.0, target=419.8))
    assert text == ("★ <b>TESTMSG</b> · Select confirms the 10:02 am call\n"
                    "💰 Buy at <b>₹414.60</b> · 🛑 Stop loss <b>₹412.00</b> · 🎯 Target <b>₹419.80</b>")
    assert "Sell at" in alerts.format_confirm(dict(SELECT, direction="DOWN"))
    assert "the earlier call" in alerts.format_confirm(SELECT)


def test_the_days_result_keeps_each_lanes_calls_apart():
    rows = [dict(SAMPLE, symbol="A", outcome="TARGET", pnl_pct=1.38),
            dict(SELECT, symbol="S1", outcome="TARGET", pnl_pct=2.0),
            dict(SELECT, symbol="S2", direction="DOWN", outcome="STOP", pnl_pct=-0.7),
            dict(SELECT, symbol="S3", outcome="OPEN_AT_CLOSE", pnl_pct=0.4)]
    text = alerts.format_day_result("18 Nov", rows)
    lines = text.split("\n")
    assert lines[1] == "1 call: 1 hit target, 0 hit stop loss, 0 closed at 3:15 pm"
    assert "★ Select: 3 calls: 1 hit target, 1 hit stop loss, 1 closed at 3:15 pm" in lines
    assert "SELL S2" in text and "-0.7%" in text
    only = alerts.format_day_result("18 Nov", rows[1:])
    assert "No call today" not in only and only.split("\n")[1].startswith("★ Select: 3 calls")
    assert "No call today" in alerts.format_day_result("18 Nov", [])


def test_the_morning_line_names_the_select_lane_when_it_is_on():
    plain = alerts.format_day_open(400, "2026-11-16", 0.2)
    text = alerts.format_day_open(400, "2026-11-16", 0.2, select={"cap_day": 6, "from": "09:30", "to": "14:30"})
    assert text == plain + "\n★ Select: up to 6 high-conviction calls, 9:30 am to 2:30 pm."
    assert alerts.format_day_open(400, None, None, select=True).endswith(
        "★ Select: up to 8 high-conviction calls, 9:25 am to 2:45 pm.")
    assert alerts.format_day_open(400, None, None, select=None) == plain


def test_the_heartbeat_passes_the_select_window(monkeypatch, clock):
    sent = []
    monkeypatch.setattr(intraday, "HEARTBEAT", True)
    clock.set(9, 18)
    lanes = {"select": {"enabled": True, "label": "★ Select", "window": "09:25–14:45", "cap_day": 8}}
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        status=lambda: {"stocks": 400, "usable": True, "asof": "2026-11-16", "lanes": lanes}))
    monkeypatch.setattr(intraday, "notify", types.SimpleNamespace(
        send_plain=sent.append, format_day_open=alerts.format_day_open))
    intraday._heartbeat()
    assert sent[0].endswith("★ Select: up to 8 high-conviction calls, 9:25 am to 2:45 pm.")
    # A formatter without the new argument is called without it.
    monkeypatch.setitem(intraday._state, "heartbeat_day", None)
    monkeypatch.setattr(intraday, "notify", types.SimpleNamespace(
        send_plain=sent.append,
        format_day_open=lambda stocks, levels_asof, index_pct, poll_seconds=20: f"open {stocks}"))
    intraday._heartbeat()
    assert sent[1] == "open 400"


# ---------------------------------------------------------------------------
# 10. The work that needs Dhan per stock: background only
# ---------------------------------------------------------------------------

def test_a_pass_makes_one_dhan_call_and_starts_no_background_work(loop, clock, monkeypatch):
    d, _n, set_engine = loop
    asked = []
    seen = set_engine([[call(symbol="A", time="10:30"), call(symbol="A", time="10:30", engine="select")],
                       []],
                      orb_missing=lambda now=None: asked.append("orb") or True,
                      profiles_fresh=lambda now=None: asked.append("profiles") or False,
                      profile_symbols=lambda: asked.append("symbols") or ["A"],
                      set_money_flow=lambda m, day: asked.append("flow"))
    logged().append(call(symbol="OPEN", time="09:45"))    # a call still being tracked
    clock.set(10, 30)
    intraday.scan_once()
    clock.set(10, 30, 20)
    intraday.scan_once()
    assert d.calls == {"bulk_quotes": 2}                  # nothing else, by any name
    assert asked == [] and intraday._jobs == {}
    syms, mode = d.requested[0]
    assert mode == "quote" and "OPEN" in syms and "NEAR" in syms and len(seen["calls"]) == 2


def test_the_loop_starts_the_background_jobs(monkeypatch):
    order = []
    monkeypatch.setattr(intraday, "_ensure_levels", lambda: order.append("levels"))
    monkeypatch.setattr(intraday, "_ensure_background", lambda now=None: order.append("background"))
    monkeypatch.setattr(intraday, "market_open", lambda t=None: True)
    monkeypatch.setattr(intraday, "scan_once", lambda: order.append("pass"))
    monkeypatch.setitem(intraday._state, "running", True)

    def nap(_s):
        intraday._state["running"] = False
    monkeypatch.setattr(intraday.time, "sleep", nap)
    intraday._loop()
    assert order == ["levels", "background", "pass"]


def _five_min(day, starts, hi, lo):
    idx = pd.DatetimeIndex([pd.Timestamp(f"{day} {s}") for s in starts])
    return pd.DataFrame({"Open": 1.0, "High": hi, "Low": lo, "Close": 1.0, "Volume": 1.0}, index=idx)


def test_a_missed_opening_range_is_rebuilt_from_candles_once_a_day(monkeypatch):
    frames = {
        "AAA": _five_min(TODAY, ["09:15", "09:20", "09:25", "09:30"], [101.0, 103.0, 102.0, 109.0],
                         [99.0, 100.0, 98.5, 90.0]),               # the 09:30 bar is not the range
        "BBB": None,
        "CCC": _five_min("2026-11-16", ["09:15", "09:20"], [5.0, 6.0], [4.0, 3.0]),   # yesterday's
        "DDD": _five_min(TODAY, ["09:20"], [51.0], [50.0]),
    }
    d = Dhan()
    d.intraday_ohlcv = lambda s, interval="5", days=5: d._count("intraday_ohlcv") or frames[s]
    monkeypatch.setattr(intraday, "dhan", d)
    got, asked = [], []
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        orb_missing=lambda now=None: asked.append(now) or True,
        set_orb=lambda day, mapping: got.append((day, mapping)) or len(mapping),
        watch_symbols=lambda now=None: list(frames)))
    assert intraday._ensure_orb(now=at(9, 50), sync=True) is True
    assert got == [(TODAY, {"AAA": (103.0, 98.5), "DDD": (51.0, 50.0)})]
    assert asked == [at(9, 50)] and d.calls["intraday_ohlcv"] == 4
    assert intraday._jobs["orb"]["result"] == 2
    assert intraday._ensure_orb(now=at(10, 30), sync=True) is False    # once a day
    assert len(got) == 1
    monkeypatch.setattr(intraday.breakouts, "orb_missing", lambda now=None: False)
    assert intraday._ensure_orb(now=at(9, 50, day=dt.date(2026, 11, 18)), sync=True) is False


def test_volume_profiles_are_built_in_the_morning_with_one_retry(monkeypatch):
    week = _week()
    fail = {"BBB", "CCC"}
    d = Dhan()
    fetched = []
    d.intraday_ohlcv = lambda s, interval="5", days=5: fetched.append(s) or (None if s in fail else week)
    monkeypatch.setattr(intraday, "dhan", d)
    saved = []
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        profiles_fresh=lambda now=None: False,
        profile_symbols=lambda: ["AAA", "BBB", "CCC"],
        save_profiles=lambda profiles, built_for: saved.append((dict(profiles), built_for)),
        last_close=lambda now=None: dt.date(2026, 11, 16)))
    clock = {"t": 50_000.0}
    monkeypatch.setattr(intraday.time, "time", lambda: clock["t"])
    assert intraday._ensure_bo_profiles(now=at(7, 0), sync=True) is False     # before 07:30
    assert intraday._ensure_bo_profiles(now=at(8, 0), sync=True) is True
    (profiles, built_for), = saved
    assert built_for == "2026-11-16" and list(profiles) == ["AAA"]
    assert len(profiles["AAA"]) == 75 and profiles["AAA"][0] == 200.0
    assert fetched == ["AAA", "BBB", "CCC"]
    # One of three is under half: one retry, half an hour on, for the rest.
    clock["t"] += 10 * 60
    assert intraday._ensure_bo_profiles(now=at(8, 10), sync=True) is False
    clock["t"] += 21 * 60
    fail.discard("BBB")
    assert intraday._ensure_bo_profiles(now=at(8, 31), sync=True) is True
    assert fetched[3:] == ["BBB", "CCC"] and sorted(saved[-1][0]) == ["AAA", "BBB"]
    clock["t"] += 3600
    assert intraday._ensure_bo_profiles(now=at(9, 31), sync=True) is False   # no third try
    assert len(saved) == 2


def test_profiles_wait_for_their_day_and_their_need(monkeypatch):
    built = []
    monkeypatch.setattr(intraday, "dhan", Dhan())
    monkeypatch.setattr(intraday, "build_bo_profile", lambda s: built.append(s) or [1.0] * 75)
    ns = types.SimpleNamespace(profiles_fresh=lambda now=None: True, profile_symbols=lambda: ["A"],
                               save_profiles=lambda p, b: None, last_close=lambda now=None: DAY)
    monkeypatch.setattr(intraday, "breakouts", ns)
    assert intraday._ensure_bo_profiles(now=at(8, 0), sync=True) is False     # already fresh
    ns.profiles_fresh = lambda now=None: False
    saturday = dt.date(2026, 11, 21)
    assert intraday._ensure_bo_profiles(now=at(8, 0, day=saturday), sync=True) is False
    assert intraday._ensure_bo_profiles(now=at(15, 30), sync=True) is False   # after 15:00
    ns.profile_symbols = lambda: []
    assert intraday._ensure_bo_profiles(now=at(8, 0), sync=True) is False     # no levels yet
    assert intraday._jobs["profiles"]["tries"] == 0                           # and that was no try
    assert built == []


def test_money_flow_quadrants_are_read_once_a_day(monkeypatch):
    reads, got = [], []
    page = {"sectors": [{"sector": "Automobile and Auto Components", "short": "Auto", "quadrant": "Leading"},
                        {"sector": "Power", "short": "Power", "quadrant": None}],
            "unscored": [{"sector": "Textiles", "short": "Textiles", "quadrant": "Lagging"},
                         {"sector": "Automobile and Auto Components", "short": "Auto",
                          "quadrant": "Lagging"}]}
    monkeypatch.setitem(sys.modules, "money_flow",
                        types.SimpleNamespace(overview=lambda: reads.append(1) or page))
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        set_money_flow=lambda m, day: got.append((m, day))))
    assert intraday._ensure_money_flow(now=at(7, 59), sync=True) is False
    assert intraday._ensure_money_flow(now=at(8, 5), sync=True) is True
    assert got == [({"automobile and auto components": "Leading", "auto": "Leading",
                     "textiles": "Lagging"}, TODAY)]
    assert intraday._ensure_money_flow(now=at(12, 0), sync=True) is False
    assert len(reads) == 1


def test_a_background_job_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(intraday, "dhan", Dhan())
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(
        orb_missing=boom, set_orb=boom, watch_symbols=boom, profiles_fresh=boom,
        profile_symbols=boom, save_profiles=boom, last_close=boom, set_money_flow=boom))
    monkeypatch.setitem(sys.modules, "money_flow", types.SimpleNamespace(overview=boom))
    assert intraday._ensure_orb(now=at(9, 50), sync=True) is False
    assert intraday._ensure_bo_profiles(now=at(8, 0), sync=True) is False
    assert intraday._ensure_money_flow(now=at(9, 0), sync=True) is True     # started; the read failed
    assert intraday._jobs["money_flow"]["error"] == "nope"
    assert intraday._jobs["orb"]["error"] == "nope" and intraday._jobs["profiles"]["error"] == "nope"
    intraday._ensure_background(now=at(9, 50))           # all three at once: still nothing raised
    # An engine with none of the new functions: nothing to do, nothing raised.
    monkeypatch.setattr(intraday, "breakouts", types.SimpleNamespace(watch_symbols=lambda: []))
    assert not any(fn(now=at(9, 50), sync=True) for fn in
                   (intraday._ensure_orb, intraday._ensure_bo_profiles, intraday._ensure_money_flow))


def test_a_job_still_running_is_not_started_again():
    gate = threading.Event()
    runs = []

    def slow():
        runs.append(1)
        gate.wait(5)
    assert intraday._spawn("slow", slow) is True
    assert intraday._spawn("slow", slow) is False
    gate.set()
    intraday._jobs["slow"]["thread"].join(5)
    assert intraday._spawn("slow", slow) is True
    intraday._jobs["slow"]["thread"].join(5)
    assert len(runs) == 2 and intraday._jobs["slow"]["thread"].daemon


# ---------------------------------------------------------------------------
# The page's view: status() and diagnose()
# ---------------------------------------------------------------------------

def test_status_adds_the_lanes_and_keeps_what_it_had(loop, clock, monkeypatch):
    _d, _n, set_engine = loop
    paced = []
    set_engine(pacing=lambda log=None, now=None: paced.append((len(log), now)) or
               {"lane": "select", "line": "Mid-morning session · 1/3 ★ slots used · Live 11:42 IST",
                "used_today": np.int64(1)},
               status=lambda: {"lanes": {"select": {"enabled": True}}, "profiles": {"ready": 3},
                               "checkpoint": {"restored": True}, "gates": {"select": {"rpos": 2}}})
    monkeypatch.setattr(intraday, "ALERT_UPDATES_TG", "t1")
    logged().extend([call(symbol="A", time="10:00"), call(symbol="B", time="11:00", engine="select"),
                     call(symbol="C", time="11:50"), call(symbol="D", time="09:30", date="2026-11-16")])
    clock.set(11, 42)
    st = intraday.status()
    for key in ("running", "market_open", "watchlist_size", "quotes_last_pass", "last_run",
                "profiles_built", "profiles_pending", "index_change_pct", "alerts_today",
                "top_rvol_now", "profiles_given_up", "in_alert_window", "alerts_configured",
                "volume_alerts_on", "poll_seconds", "daily_cap", "error"):
        assert key in st
    assert [a["symbol"] for a in st["alerts_today"]] == ["C", "B", "A"]          # newest first
    assert st["clock"] == "11:42" and st["lanes"] == {"classic": 2, "select": 1}
    assert st["updates_tg"] == "t1" and st["live_tracked"] == 2                  # C fires at 11:50
    assert st["pacing"]["used_today"] == 1 and type(st["pacing"]["used_today"]) is int
    assert paced == [(3, at(11, 42))]
    st["alerts_today"][0]["symbol"] = "CHANGED"           # a copy: the log is untouched
    assert logged()[2]["symbol"] == "C"
    diag = intraday.diagnose()
    assert diag["lanes"] == {"select": {"enabled": True}} and diag["profiles"] == {"ready": 3}
    assert diag["checkpoint"] == {"restored": True} and diag["gates"] == {"select": {"rpos": 2}}
    assert diag["archive_path"].endswith("signal_log_archive.jsonl") and diag["log_rows"] == 4


def test_status_without_a_pacing_engine_says_none(loop, clock):
    st = intraday.status()
    assert st["pacing"] is None and st["lanes"] == {"classic": 0, "select": 0}
    assert intraday.diagnose()["lanes"] is None
