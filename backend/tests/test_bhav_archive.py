"""
Five years of NSE's daily bhavcopy, kept in R2 (bhav_archive.py).

An archive like this fails quietly in a few known ways: a refusal from the
exchange written off as a holiday (so the day is never asked for again), a
page that is not a bhavcopy stored as if it were one, today's file written off
because it was not out yet, and a format change that a reader does not follow.
Each is tested here against a fake exchange and a fake bucket. Nothing here
touches the network.
"""
import datetime as dt
import gzip
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bhav_archive as A  # noqa: E402


# --- Files in each of NSE's three formats, with the real column names --------

OLD_CM_HEADER = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,"
                 "TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,")
UDIFF_HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
                "XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,"
                "LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
                "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,"
                "NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")
FULL_HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
               "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
               "NO_OF_TRADES, DELIV_QTY, DELIV_PER")


def _zip(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def old_cm(day, close=2500.5):
    tag = day.strftime("%d-%b-%Y").upper()
    rows = [OLD_CM_HEADER,
            "RELIANCE,EQ,2480,2510,2470,%s,2501,2475,1000000,2500000000,%s,50000,INE002A01018," % (close, tag),
            "TCS,EQ,3300,3350,3290,3340,3341,3310,200000,668000000,%s,20000,INE467B01029," % tag]
    return _zip("cm%sbhav.csv" % day.strftime("%d%b%Y").upper(), "\n".join(rows) + "\n")


def udiff_cm(day, close=2950.0):
    d = day.isoformat()
    rows = [UDIFF_HEADER,
            "%s,%s,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,,,,,RELIANCE INDUSTRIES LTD,"
            "2930,2960,2920,%s,2951,2925,,%s,,,1000000,2950000000,60000,F1,1,,,,," % (d, d, close, close),
            "%s,%s,CM,NSE,STK,11536,INE467B01029,TCS,EQ,,,,,TATA CONSULTANCY SERV LT,"
            "4000,4050,3990,4040,4041,4010,,4040,,,200000,808000000,30000,F1,1,,,,," % (d, d)]
    name = "BhavCopy_NSE_CM_0_0_0_%s_F_0000.csv" % day.strftime("%Y%m%d")
    return _zip(name, "\n".join(rows) + "\n")


def full(day):
    tag = day.strftime("%d-%b-%Y")
    rows = [FULL_HEADER,
            "RELIANCE, EQ, %s, 2475.00, 2480.00, 2510.00, 2470.00, 2501.00, 2500.50, "
            "2495.10, 1000000, 24951.00, 50000, 600000, 60.00" % tag,
            "TCS, EQ, %s, 3310.00, 3300.00, 3350.00, 3290.00, 3341.00, 3340.00, "
            "3330.00, 200000, 6660.00, 20000, 150000, 75.00" % tag]
    return ("\n".join(rows) + "\n").encode()


def cm(day):
    return old_cm(day) if day < A.UDIFF_FROM else udiff_cm(day)


# --- The fakes ---------------------------------------------------------------

class Resp:
    def __init__(self, code, body=b""):
        self.status_code, self.content = code, body


class FakeNSE:
    """
    An exchange archive. Weekdays trade unless listed as holidays; a weekend
    trades only if listed as a special session. `refuse` maps a day to how many
    times it is refused before it is served; `no_full_before` is the first day
    the delivery file exists.
    """
    def __init__(self, holidays=(), special=(), refuse=None, no_full_before=None,
                 not_out=(), html_for=()):
        self.holidays, self.special = set(holidays), set(special)
        self.refuse = dict(refuse or {})
        self.no_full_before = no_full_before
        self.not_out, self.html_for = set(not_out), set(html_for)
        self.calls = []

    def _day(self, url):
        name = url.rsplit("/", 1)[-1]
        for fmt, part in (("%d%m%Y", name.replace("sec_bhavdata_full_", "")[:8]),
                          ("%Y%m%d", name.replace("BhavCopy_NSE_CM_0_0_0_", "")[:8]),
                          ("%d%b%Y", name[2:11])):
            try:
                return dt.datetime.strptime(part, fmt).date()
            except ValueError:
                continue
        raise AssertionError("unrecognised url " + url)

    def get(self, url, timeout=None):
        self.calls.append(url)
        day = self._day(url)
        kind = "full" if "sec_bhavdata_full" in url else "cm"
        if self.refuse.get(day, 0) > 0:
            self.refuse[day] -= 1
            return Resp(403, b"<html>Access Denied</html>")
        if day in self.html_for:
            return Resp(200, b"<html>" + b"x" * 9000 + b"</html>")
        trades = (day.weekday() < 5 and day not in self.holidays) or day in self.special
        if not trades or day in self.not_out:
            return Resp(404, b"Not Found")
        if kind == "full":
            if self.no_full_before and day < self.no_full_before:
                return Resp(404, b"Not Found")
            return Resp(200, full(day))
        return Resp(200, cm(day))


class FakeBucket:
    def __init__(self):
        self.objects, self.puts = {}, []

    def put_bytes(self, key, body, content_type=None):
        self.objects[key] = body
        self.puts.append((key, content_type))

    def get(self, key):
        return self.objects.get(key)

    def list_objects(self, prefix):
        return [(k, len(v)) for k, v in self.objects.items() if k.startswith(prefix)]


TODAY = dt.date(2026, 11, 16)          # a Monday


def run(bucket, nse, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("years", 0)
    kw.setdefault("limit", 1000)
    return A.run(client=bucket, http=nse, sleep=lambda s: None, **kw)


@pytest.fixture()
def two_weeks(monkeypatch):
    """A window of the 21 days to TODAY, so a test walks a few dozen days."""
    real = A.window
    monkeypatch.setattr(A, "window", lambda today=None, years=None:
                        (today - dt.timedelta(days=20), today) if years == 0 else real(today, years))


# --- Where NSE keeps each file ------------------------------------------------

def test_each_format_is_asked_for_at_its_own_address():
    assert A.source_path("cm", dt.date(2024, 7, 5)) == \
        "/content/historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip"
    assert A.source_path("cm", dt.date(2024, 7, 8)) == \
        "/content/cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip"
    assert A.source_path("full", dt.date(2021, 11, 16)) == \
        "/products/content/sec_bhavdata_full_16112021.csv"


def test_the_window_is_five_years_to_the_day():
    assert A.window(dt.date(2026, 11, 16), 5) == (dt.date(2021, 11, 16), dt.date(2026, 11, 16))
    assert A.window(dt.date(2028, 2, 29), 5)[0] == dt.date(2023, 2, 28)


def test_keys_name_the_kind_and_the_day_and_read_back():
    k = A.key("cm", dt.date(2024, 7, 8))
    assert k == "bhavcopy/cm/2024/20240708.csv.zip"
    assert A.day_of(k) == ("cm", dt.date(2024, 7, 8))
    assert A.day_of("bhavcopy/full/2021/20211116.csv.gz") == ("full", dt.date(2021, 11, 16))
    assert A.day_of("bhavcopy/absent.json") is None
    assert A.day_of("daily/2026-11-16/altaha_pit.db.gz") is None


# --- The backfill -----------------------------------------------------------

def test_a_backfill_stores_both_files_for_every_session(two_weeks):
    b, nse = FakeBucket(), FakeNSE(holidays={dt.date(2026, 11, 5)})
    out = run(b, nse)
    sessions = [TODAY - dt.timedelta(days=i) for i in range(21)]
    trading = [d for d in sessions if d.weekday() < 5 and d != dt.date(2026, 11, 5)]
    assert out["ok"]
    assert out["stored"] == {"cm": len(trading), "full": len(trading)}
    for d in trading:
        assert A.key("cm", d) in b.objects and A.key("full", d) in b.objects
    assert out["remaining"] == 0


def test_the_bhavcopy_is_kept_exactly_as_nse_served_it(two_weeks):
    b, nse = FakeBucket(), FakeNSE()
    run(b, nse)
    d = dt.date(2026, 11, 13)
    assert b.objects[A.key("cm", d)] == udiff_cm(d)
    assert gzip.decompress(b.objects[A.key("full", d)]) == full(d)
    types = dict(b.puts)
    assert types[A.key("cm", d)] == "application/zip"
    assert types[A.key("full", d)] == "application/gzip"


def test_holidays_and_weekends_are_asked_for_once_and_never_again(two_weeks):
    b, nse = FakeBucket(), FakeNSE(holidays={dt.date(2026, 11, 5)})
    run(b, nse)
    absent = json.loads(b.objects[A.ABSENT_KEY])
    assert "2026-11-05" in absent["cm"] and "2026-11-08" in absent["cm"]   # holiday, Sunday
    # A day with no bhavcopy is not asked for its delivery file either.
    assert not any("sec_bhavdata_full_05112026" in u for u in nse.calls)
    nse.calls.clear()
    run(b, nse)
    # Only yesterday (a Sunday, young enough that its file could still be on
    # its way) is asked for again. Nothing older is.
    assert nse.calls == [A.HOSTS[0] + A.source_path("cm", dt.date(2026, 11, 15))]


def test_a_weekend_session_is_kept(two_weeks):
    muhurat = dt.date(2026, 11, 8)                         # a Sunday
    b = FakeBucket()
    run(b, FakeNSE(special={muhurat}))
    assert A.key("cm", muhurat) in b.objects


def test_a_refusal_is_never_written_off_as_a_holiday(two_weeks):
    refused = dt.date(2026, 11, 12)
    b, nse = FakeBucket(), FakeNSE(refuse={refused: 2})    # both hosts, once each
    out = run(b, nse)
    assert out["blocked"] == 1
    assert A.key("cm", refused) not in b.objects
    assert "2026-11-12" not in json.loads(b.objects[A.ABSENT_KEY])["cm"]
    assert out["remaining"] == 1
    out = run(b, nse)                                       # it answers now
    assert A.key("cm", refused) in b.objects and out["remaining"] == 0


def test_the_second_host_is_asked_only_when_the_first_refuses(two_weeks):
    d = dt.date(2026, 11, 13)
    nse = FakeNSE(refuse={d: 1})
    run(FakeBucket(), nse)
    cm_calls = [u for u in nse.calls if "20261113" in u]
    assert cm_calls == [A.HOSTS[0] + A.source_path("cm", d), A.HOSTS[1] + A.source_path("cm", d)]
    sunday = [u for u in nse.calls if "20261115" in u]
    assert len(sunday) == 1                                 # a 404 is an answer


def test_a_page_that_is_not_a_bhavcopy_is_not_stored(two_weeks):
    d = dt.date(2026, 11, 11)
    b = FakeBucket()
    out = run(b, FakeNSE(html_for={d}))
    assert A.key("cm", d) not in b.objects
    assert "2026-11-11" not in json.loads(b.objects[A.ABSENT_KEY])["cm"]
    assert out["blocked"] == 1


def test_todays_file_not_being_out_yet_is_not_a_holiday(two_weeks):
    b = FakeBucket()
    out = run(b, FakeNSE(not_out={TODAY}))
    assert A.key("cm", TODAY) not in b.objects
    assert TODAY.isoformat() not in json.loads(b.objects[A.ABSENT_KEY])["cm"]
    assert out["remaining"] == 0
    assert out["waiting_for_nse"] == 2                     # today, and Sunday
    run(b, FakeNSE())                                       # out the next evening
    assert A.key("cm", TODAY) in b.objects


def test_a_day_with_no_delivery_file_keeps_its_bhavcopy(two_weeks):
    first = dt.date(2026, 11, 10)
    b = FakeBucket()
    run(b, FakeNSE(no_full_before=first))
    old = dt.date(2026, 11, 6)
    assert A.key("cm", old) in b.objects and A.key("full", old) not in b.objects
    assert "2026-11-06" in json.loads(b.objects[A.ABSENT_KEY])["full"]
    st = A.status(client=b, today=TODAY, years=0)
    assert st["full"]["first"] == first.isoformat()
    assert st["complete"]


def test_a_slice_stops_at_its_limit_newest_first(two_weeks):
    b = FakeBucket()
    out = run(b, FakeNSE(), limit=4)
    # Monday stored, Sunday waiting (young), Saturday written off, Friday stored.
    assert out["stopped"] == "limit" and out["days_done"] == 3
    held = sorted({A.day_of(k)[1] for k in b.objects if A.day_of(k)})
    assert held == [dt.date(2026, 11, 13), TODAY]
    assert out["remaining"] > 0


def test_a_slice_gives_up_after_five_refusals_in_a_row(two_weeks):
    days = {TODAY - dt.timedelta(days=i): 99 for i in range(21)}
    b, nse = FakeBucket(), FakeNSE(refuse=days)
    out = run(b, nse)
    assert out["stopped"] == "refused" and out["blocked"] == A.BLOCKED_STOP
    assert len(nse.calls) == A.BLOCKED_STOP * len(A.HOSTS)


def test_recheck_asks_again_for_days_written_off(two_weeks):
    b = FakeBucket()
    wrongly = dt.date(2026, 11, 4)
    run(b, FakeNSE(holidays={wrongly}))
    assert wrongly.isoformat() in json.loads(b.objects[A.ABSENT_KEY])["cm"]
    run(b, FakeNSE(), recheck=True)
    assert A.key("cm", wrongly) in b.objects
    assert wrongly.isoformat() not in json.loads(b.objects[A.ABSENT_KEY])["cm"]


def test_a_failed_upload_leaves_the_day_to_do(two_weeks):
    class Flaky(FakeBucket):
        def put_bytes(self, key, body, content_type=None):
            if "20261113" in key:
                raise RuntimeError("R2 PUT: HTTP 500")
            super().put_bytes(key, body, content_type)
    b = Flaky()
    out = run(b, FakeNSE())
    assert not out["ok"] and out["errors"][0]["day"] == "2026-11-13"
    assert out["remaining"] == 1


# --- Reading what was stored -------------------------------------------------

@pytest.mark.parametrize("day", [dt.date(2024, 7, 5), dt.date(2024, 7, 8)])
def test_both_bhavcopy_formats_read_to_the_same_columns(day):
    df = A.frame("cm", cm(day))
    assert list(df["symbol"]) == ["RELIANCE", "TCS"]
    assert set(df["series"]) == {"EQ"}
    assert df["isin"].iloc[0] == "INE002A01018"
    for c in ("open", "high", "low", "close", "prev_close", "volume", "value", "trades"):
        assert df[c].notna().all(), c
    assert df["value"].iloc[0] > 1e9                       # rupees, not lakh


def test_the_delivery_file_reads_with_value_in_rupees():
    df = A.frame("full", gzip.compress(full(dt.date(2026, 11, 13))))
    r = df.set_index("symbol").loc["RELIANCE"]
    assert r["deliv_pct"] == 60.0 and r["deliv_qty"] == 600000
    assert r["close"] == 2500.5 and r["vwap"] == 2495.1
    assert r["value"] == pytest.approx(24951.0 * 1e5)


def test_read_returns_a_stored_day_and_none_for_a_missing_one(two_weeks):
    b = FakeBucket()
    run(b, FakeNSE())
    df = A.read(dt.date(2026, 11, 13), client=b)
    assert list(df["symbol"]) == ["RELIANCE", "TCS"]
    assert A.read(dt.date(2026, 11, 15), client=b) is None   # a Sunday


def test_something_that_is_not_a_bhavcopy_counts_no_rows():
    assert A.count_rows("cm", b"<html>Access Denied</html>") == 0
    assert A.count_rows("cm", _zip("x.csv", "A,B\n1,2\n")) == 0
    assert A.count_rows("full", full(dt.date(2026, 11, 13))) == 2


def test_status_reports_span_size_and_what_is_left(two_weeks):
    b = FakeBucket()
    run(b, FakeNSE(), limit=5)
    st = A.status(client=b, today=TODAY, years=0)
    assert st["cm"]["days"] == st["full"]["days"] > 0
    assert st["cm"]["last"] == TODAY.isoformat()
    assert st["cm"]["bytes"] > 0
    assert st["remaining"] > 0 and not st["complete"]
