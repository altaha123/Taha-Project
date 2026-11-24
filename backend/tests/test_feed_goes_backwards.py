"""
The night of Monday 23 November 2026, replayed through the code a reader's
request goes through.

Read from the live API every five minutes that night:

    up to 23:57 IST Mon   last daily bar 2026-11-23   Nifty 25,349.65  Reliance 1,351.00
    00:07 IST Tue onward  last daily bar 2026-11-20   Nifty 25,800.60  Reliance 1,377.50

At 00:18 /market read "NIFTY 50 25800.6, +1.12%": Friday's close and Friday's
move, when Monday had closed at 25,349.65, down 1.75%.

Two feeds, two causes.
  · The index comes from Yahoo, whose own history lost Monday at midnight and
    had it back by late morning. data_source.resolve now puts the lost session
    back (settled_bars.py; the memory itself is pinned in
    test_settled_bars.py).
  · A stock comes from Dhan, and that was this code: the history was asked for
    up to the SERVER's date, which in UTC is still Monday until 05:30 IST, and
    Dhan's `toDate` is the first day not wanted.

The same hour is then checked on the watchlist, whose daily rows come from
their own Yahoo download.
"""
import datetime as dt
import importlib.util
import os
import types

import pandas as pd
import pytest

import market_calendar
import settled_bars

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
THU, FRI, MON = "2026-11-19", "2026-11-20", "2026-11-23"
NIFTY = {THU: 25514.30, FRI: 25800.60, MON: 25349.65}
RELIANCE = {THU: 1375.60, FRI: 1377.50, MON: 1351.00}


def at(day, hour, minute=0):
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=IST)


def history(closes, upto, tz="Asia/Kolkata", quiet=80):
    """A daily frame ending on `upto`: `quiet` flat sessions, then `closes`."""
    days = [d for d in sorted(closes) if d <= upto]
    before = pd.bdate_range(end=pd.Timestamp(days[0]) - pd.Timedelta(days=1), periods=quiet)
    idx = before.append(pd.DatetimeIndex(days))
    vals = [closes[days[0]]] * quiet + [closes[d] for d in days]
    return pd.DataFrame({"Open": vals, "High": vals, "Low": vals, "Close": vals,
                         "Volume": [300_000] * len(vals)},
                        index=idx.tz_localize(tz) if tz else idx)


class Night:
    """One data layer with a clock and a scripted feed.

    `yahoo` and `dhan` map a symbol to the date its history ends on right
    now; a test moves the clock and changes what the feed has."""

    def __init__(self, monkeypatch):
        spec = importlib.util.spec_from_file_location(
            "data_source_night", os.path.join(BACKEND, "data_source.py"))
        self.ds = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ds)
        self.now = at(23, 23, 57)
        self.yahoo, self.dhan, self.fetched = {}, None, []
        night = self

        class Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period="1y", auto_adjust=True):
                night.fetched.append(self.sym)
                upto = night.yahoo.get(self.sym)
                if upto is None:
                    raise RuntimeError("no such symbol")
                return history(NIFTY, upto)

        def daily_ohlcv(base):
            night.fetched.append("dhan:" + base)
            return history(RELIANCE, night.dhan[base], tz=None)

        monkeypatch.setattr(self.ds, "yf", types.SimpleNamespace(Ticker=Ticker))
        monkeypatch.setattr(self.ds, "dhan", types.SimpleNamespace(
            configured=lambda: night.dhan is not None, daily_ohlcv=daily_ohlcv))
        monkeypatch.setattr(self.ds, "time", types.SimpleNamespace(
            time=lambda: night.now.timestamp()))
        monkeypatch.setattr(self.ds, "_px_ttl", lambda now=None: self.ds._TTL)
        monkeypatch.setattr(settled_bars, "_now", lambda: night.now)
        monkeypatch.setattr(market_calendar, "now", lambda: night.now)

    def to(self, day, hour, minute=0):
        self.now = at(day, hour, minute)

    def last(self, symbol):
        frame = self.ds.resolve(symbol)[2]
        return str(frame.index[-1])[:10], round(float(frame["Close"].iloc[-1]), 2)


@pytest.fixture
def night(monkeypatch):
    return Night(monkeypatch)


# ── The index, from Yahoo ───────────────────────────────────────────────────

def test_the_index_does_not_go_back_to_friday_after_midnight(night):
    night.yahoo["^NSEI"] = MON
    assert night.last("^NSEI") == (MON, 25349.65)          # 23:57, as the feed had it

    night.to(24, 0, 2)
    night.yahoo["^NSEI"] = FRI                             # the feed has lost Monday
    assert night.last("^NSEI") == (MON, 25349.65)          # still the cached frame
    assert night.fetched == ["^NSEI"]

    night.to(24, 0, 27)                                    # the half hour is up
    assert night.last("^NSEI") == (MON, 25349.65)          # refetched, and not Friday
    assert night.fetched == ["^NSEI", "^NSEI"]
    assert night.ds.resolve("^NSEI")[2].attrs["kept_sessions"] == [MON]

    night.to(24, 5, 17)                                    # still behind before dawn
    assert night.last("^NSEI") == (MON, 25349.65)


def test_then_the_feed_catches_up_and_is_believed_again(night):
    night.yahoo["^NSEI"] = MON
    night.last("^NSEI")
    night.to(24, 0, 30)
    night.yahoo["^NSEI"] = FRI
    night.last("^NSEI")

    night.to(24, 11, 16)
    night.yahoo["^NSEI"] = MON
    frame = night.ds.resolve("^NSEI")[2]
    assert str(frame.index[-1])[:10] == MON
    assert "kept_sessions" not in frame.attrs              # the feed's own bar
    assert frame.index.is_unique


def test_a_deploy_during_the_gap_still_serves_monday(night, monkeypatch):
    night.yahoo["^NSEI"] = MON
    night.last("^NSEI")

    night.ds._CACHE.clear()                                # a new process: no cache,
    settled_bars._mem["bars"] = None                       # no memory, only the disk
    night.to(24, 1, 0)
    night.yahoo["^NSEI"] = FRI
    assert night.last("^NSEI") == (MON, 25349.65)


def test_nobody_looked_after_the_close_so_there_is_nothing_to_put_back(night):
    """The limit of it, stated: the memory holds what was fetched once the
    close had settled. A symbol first asked for in the gap gets what the feed
    has."""
    night.to(24, 1, 0)
    night.yahoo["^NSEI"] = FRI
    assert night.last("^NSEI") == (FRI, 25800.60)


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def test_market_at_0018_reads_mondays_close_and_mondays_move(night, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve", night.ds.resolve)
    night.yahoo["^NSEI"] = MON
    main_mod.market()                                      # somebody looked that evening

    night.to(24, 0, 48)
    night.yahoo["^NSEI"] = FRI
    out = main_mod.market()
    nifty = next(r for r in out["indices"] if r["label"] == "NIFTY 50")
    assert (nifty["level"], nifty["change"], nifty["change_pct"]) == (25349.65, -450.95, -1.75)
    assert out["ist"] == "24 Nov 2026, 00:48 IST"


def test_the_chart_ends_on_monday_and_says_the_bar_was_kept(night, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod, "resolve", night.ds.resolve)
    night.yahoo["^NSEI"] = MON
    before = main_mod.chart(ticker="^NSEI", range="3M")
    assert before["as_of"][:10] == MON and before["kept_sessions"] == []

    night.to(24, 0, 48)
    night.yahoo["^NSEI"] = FRI
    out = main_mod.chart(ticker="^NSEI", range="3M")
    assert out["as_of"][:10] == MON and out["last"] == 25349.65
    assert out["prev_close"] == 25800.60 and out["day_change_pct"] == -1.75
    assert out["kept_sessions"] == [MON]
    assert len(out["candles"]) == len(before["candles"])


# ── A stock, from Dhan ──────────────────────────────────────────────────────

def test_a_stock_keeps_mondays_bar_when_dhans_history_has_not_got_it_yet(night):
    """After midnight Dhan's history is the only source of yesterday's bar
    (the quote builds today's from 09:15). If its own end-of-day run is late,
    the bar built from the quote that evening is what is served."""
    night.to(23, 20, 0)
    night.dhan = {"RELIANCE": MON}                         # Friday's history + today's quote
    assert night.last("RELIANCE") == (MON, 1351.00)

    night.to(24, 0, 37)
    night.dhan = {"RELIANCE": FRI}
    assert night.last("RELIANCE") == (MON, 1351.00)
    frame = night.ds.resolve("RELIANCE")[2]
    assert frame.attrs["kept_sessions"] == [MON] and frame.attrs["price_source"] == "Dhan"
    assert frame.index.tz is None


def test_todays_bar_put_back_makes_the_frame_whole(night):
    """Monday 16:45: the quote that builds today's bar does not arrive, and the
    frame comes back marked. The bar from 16:10 is today's, settled, so the
    frame is complete and is cached as one, not refetched every minute."""
    night.to(23, 16, 10)
    night.dhan = {"RELIANCE": MON}
    night.last("RELIANCE")

    night.to(23, 16, 45)
    real = night.ds.dhan.daily_ohlcv

    def without_today(base):
        frame = real(base)
        frame.attrs["today_missing"] = True
        return frame
    night.ds.dhan.daily_ohlcv = without_today
    night.dhan = {"RELIANCE": FRI}

    frame = night.ds.resolve("RELIANCE")[2]
    assert str(frame.index[-1])[:10] == MON and "today_missing" not in frame.attrs
    asked = len(night.fetched)
    night.to(23, 16, 50)                                   # five minutes, not one
    night.ds.resolve("RELIANCE")
    assert len(night.fetched) == asked


# ── The date Dhan is asked with ─────────────────────────────────────────────

@pytest.fixture
def dhan_at(monkeypatch):
    """dhan_source with India's clock at one moment, the server's date at
    another, and a Dhan that honours `toDate` the way its documentation says:
    the first day NOT returned."""
    spec = importlib.util.spec_from_file_location(
        "dhan_source_dates", os.path.join(BACKEND, "dhan_source.py"))
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    asked = []

    def set_clock(india, server_date):
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return india

        class ServerDate(dt.date):
            @classmethod
            def today(cls):
                return server_date
        monkeypatch.setattr(d, "dt", types.SimpleNamespace(
            datetime=Clock, date=ServerDate, timedelta=dt.timedelta, timezone=dt.timezone))

    sessions = pd.bdate_range(end=MON, periods=90)

    class Reply:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            days = [s for s in sessions if s < pd.Timestamp(self.body["toDate"])]
            stamp = lambda s: int((s - pd.Timedelta(hours=5, minutes=30)).timestamp())
            closes = [1300.0 + i for i in range(len(days))]
            return {"open": closes, "high": closes, "low": closes, "close": closes,
                    "volume": [1_000_000] * len(days), "timestamp": [stamp(s) for s in days]}

    def post(url, json=None, headers=None, timeout=None):
        asked.append((url, dict(json)))
        return Reply(json)

    monkeypatch.setattr(d, "requests", types.SimpleNamespace(post=post))
    monkeypatch.setattr(d, "CLIENT_ID", "1000000001")
    monkeypatch.setitem(d._token, "value", "token")
    monkeypatch.setattr(d, "security_id", lambda symbol: "2885")
    monkeypatch.setattr(d, "HIST_GAP", 0)
    return d, set_clock, asked


def test_after_midnight_in_india_dhan_is_asked_by_indias_date(dhan_at):
    """00:30 IST on Tuesday is 19:00 UTC on Monday. Asked up to the server's
    Monday, Dhan leaves Monday out."""
    d, set_clock, asked = dhan_at
    set_clock(india=at(24, 0, 30), server_date=dt.date(2026, 11, 23))

    frame = d.daily_ohlcv("RELIANCE")
    assert asked[-1][1]["toDate"] == "2026-11-24"
    assert frame.index[-1] == pd.Timestamp(MON)            # the session that just closed
    assert "today_missing" not in frame.attrs              # before 09:15 no bar is owed


def test_in_the_evening_the_request_is_what_it_always_was(dhan_at, monkeypatch):
    d, set_clock, asked = dhan_at
    set_clock(india=at(23, 20, 0), server_date=dt.date(2026, 11, 23))
    monkeypatch.setattr(d, "bulk_quotes", lambda *a, **k: {"RELIANCE": {
        "ltp": 1351.0, "open": 1381.0, "high": 1390.0, "low": 1346.9, "volume": 15_392_522}})

    frame = d.daily_ohlcv("RELIANCE")
    assert asked[-1][1]["toDate"] == "2026-11-23"          # everything before today
    assert frame.index[-2] == pd.Timestamp(FRI)
    assert frame.index[-1] == pd.Timestamp(MON) and frame["Close"].iloc[-1] == 1351.0


def test_intraday_and_the_token_probe_use_indias_date_too(dhan_at):
    d, set_clock, asked = dhan_at
    set_clock(india=at(24, 0, 30), server_date=dt.date(2026, 11, 23))
    d.intraday_ohlcv("RELIANCE", interval="5", days=7)
    assert asked[-1][0].endswith("/charts/intraday") and asked[-1][1]["toDate"] == "2026-11-24"
    d.is_live(force=True)
    assert asked[-1][0].endswith("/charts/historical") and asked[-1][1]["toDate"] == "2026-11-24"


# ── The watchlist's rows ────────────────────────────────────────────────────

@pytest.fixture
def WQ(monkeypatch):
    import watchlist_quotes as W
    monkeypatch.setattr(W, "_cache", {})
    monkeypatch.setattr(W, "_live", {})
    monkeypatch.setattr(W, "_dhan_overlay", lambda syms: {})
    return W


def row_ending(W, day, last_close):
    idx = pd.bdate_range(end=day, periods=30)
    return W._row_from_closes("RELIANCE", pd.Series([1377.5] * 29 + [last_close], index=idx))


def test_a_watchlist_row_does_not_go_back_a_session(WQ, monkeypatch):
    feed = {"row": row_ending(WQ, MON, 1351.0)}
    fetch = lambda batch: {"RELIANCE": feed["row"]}
    stale = lambda: WQ._cache.update(RELIANCE=(0, WQ._cache["RELIANCE"][1]))   # its time is up

    out = WQ.quotes(["RELIANCE"], fetch=fetch, now=at(23, 23, 57))
    assert out["rows"][0]["ltp"] == 1351.0 and out["rows"][0]["last_date"] == MON

    feed["row"] = row_ending(WQ, FRI, 1377.5)              # the feed has lost Monday
    stale()
    out = WQ.quotes(["RELIANCE"], fetch=fetch, now=at(24, 0, 30))
    assert out["rows"][0]["last_date"] == MON and out["rows"][0]["ltp"] == 1351.0
    assert out["rows"][0]["spark_dates"][-1] == MON

    feed["row"] = row_ending(WQ, MON, 1351.2)              # it is back, corrected
    stale()
    out = WQ.quotes(["RELIANCE"], fetch=fetch, now=at(24, 11, 16))
    assert out["rows"][0]["ltp"] == 1351.2

    feed["row"] = row_ending(WQ, FRI, 1377.5)              # and a week on, the feed is believed
    stale()
    out = WQ.quotes(["RELIANCE"], fetch=fetch, now=at(30, 12, 0))
    assert out["rows"][0]["last_date"] == FRI
