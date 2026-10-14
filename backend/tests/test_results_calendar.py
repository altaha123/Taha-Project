"""
The results calendar: who reports yesterday, today, tomorrow and this week.

What must hold:
  · "declared" only ever means the filing is on NSE — a board meeting that has
    happened is "awaited" until the document arrives;
  · a filing the morning after the meeting still belongs to that meeting, and
    is not listed twice;
  · a company's two accounting bases are one row, not two;
  · NSE refusing one source says so instead of looking like a quiet day.
"""

import datetime as dt

import pytest

import results_calendar as rc

TODAY = dt.date(2026, 10, 14)          # a Wednesday


def _meet(sym, day, purpose="Financial Results", company=None):
    return {"symbol": sym, "company": company or sym.title() + " Ltd",
            "date": dt.date.fromisoformat(day), "purpose": purpose}


def _file(sym, at, qe="2026-09-30", bases=("consolidated",), revised=False, company=None):
    return {"symbol": sym, "company": company or sym.title() + " Ltd",
            "at": dt.datetime.fromisoformat(at), "quarter_end": dt.date.fromisoformat(qe),
            "bases": set(bases), "revised": revised}


def _day(days, iso):
    return next(d for d in days if d["date"] == iso)


def _row(day, sym):
    hits = [r for r in day["rows"] if r["symbol"] == sym]
    assert len(hits) <= 1, f"{sym} listed {len(hits)} times on {day['date']}"
    return hits[0] if hits else None


def test_the_window_runs_from_this_monday_to_the_end_of_next_week():
    assert rc.window(TODAY) == (dt.date(2026, 10, 12), dt.date(2026, 10, 25))
    # On a Monday, yesterday is the Sunday before the week began.
    assert rc.window(dt.date(2026, 10, 12)) == (dt.date(2026, 10, 11), dt.date(2026, 10, 25))


def test_each_status_says_only_what_the_sources_support():
    start, end = rc.window(TODAY)
    days = rc.build(
        [_meet("TARIL", "2026-10-13"),            # met yesterday, filed yesterday
         _meet("LATE", "2026-10-13"),             # met yesterday, filed this morning
         _meet("SLOW", "2026-10-13"),             # met yesterday, nothing yet
         _meet("NOW", "2026-10-14"),              # meets today, nothing yet
         _meet("SOON", "2026-10-15", "Financial Results/Dividend")],
        [_file("TARIL", "2026-10-13T16:34:06", bases=("consolidated", "standalone"),
               company="Transformers And Rectifiers (India) Limited"),
         _file("LATE", "2026-10-14T09:05:00"),
         _file("SOLO", "2026-10-14T11:00:00")],   # filed with no meeting in the window
        start, end, TODAY)

    tue, wed, thu = _day(days, "2026-10-13"), _day(days, "2026-10-14"), _day(days, "2026-10-15")
    taril = _row(tue, "TARIL")
    assert taril["status"] == "declared"
    assert taril["filed_at"] == "2026-10-13T16:34:06" and taril["quarter"] == "Q2 FY27"
    assert taril["bases"] == ["consolidated", "standalone"]
    assert taril["company"] == "Transformers And Rectifiers (India) Limited"
    assert taril["meeting"] == "2026-10-13"

    # Filed the morning after: under the meeting's day, and only there.
    assert _row(tue, "LATE")["status"] == "declared"
    assert _row(tue, "LATE")["filed_at"].startswith("2026-10-14")
    assert _row(wed, "LATE") is None

    assert _row(tue, "SLOW")["status"] == "awaited"
    assert _row(wed, "NOW")["status"] == "today"
    assert _row(thu, "SOON")["status"] == "scheduled"
    assert _row(thu, "SOON")["purpose"] == "Financial Results/Dividend"
    assert _row(wed, "SOLO")["status"] == "declared" and "meeting" not in _row(wed, "SOLO")

    assert (tue["declared"], tue["pending"]) == (2, 1)
    assert (wed["declared"], wed["pending"]) == (1, 1)


def test_a_meeting_never_reads_as_declared_without_a_filing():
    start, end = rc.window(TODAY)
    days = rc.build([_meet("X", "2026-10-12")], [], start, end, TODAY)
    assert _row(_day(days, "2026-10-12"), "X")["status"] == "awaited"


def test_a_filing_before_the_meeting_is_not_that_meetings_result():
    """A late Q1 filing on Monday is not the Q2 result of Thursday's meeting."""
    start, end = rc.window(TODAY)
    days = rc.build([_meet("X", "2026-10-15")],
                    [_file("X", "2026-10-12T18:00:00", qe="2026-06-30")], start, end, TODAY)
    assert _row(_day(days, "2026-10-15"), "X")["status"] == "scheduled"
    mon = _row(_day(days, "2026-10-12"), "X")
    assert mon["status"] == "declared" and mon["quarter"] == "Q1 FY27"


def test_the_newest_filing_leads_and_the_rest_follow_by_name():
    start, end = rc.window(TODAY)
    days = rc.build(
        [_meet("ZED", "2026-10-14", company="Zed Ltd"), _meet("ABC", "2026-10-14", company="Abc Ltd")],
        [_file("EARLY", "2026-10-14T10:00:00"), _file("LATER", "2026-10-14T18:30:00")],
        start, end, TODAY)
    assert [r["symbol"] for r in _day(days, "2026-10-14")["rows"]] == ["LATER", "EARLY", "ABC", "ZED"]


def test_every_day_in_the_window_is_present_even_when_empty():
    start, end = rc.window(TODAY)
    days = rc.build([], [], start, end, TODAY)
    assert [d["date"] for d in days][0] == "2026-10-12"
    assert len(days) == 14 and all(d["rows"] == [] for d in days)


# ---------------------------------------------------------------------------
# Reading NSE
# ---------------------------------------------------------------------------

def test_only_results_meetings_are_kept(monkeypatch):
    rows = [
        {"symbol": "A", "company": "A LTD", "purpose": "Financial Results", "date": "15-Oct-2026"},
        {"symbol": "B", "company": "B LTD", "purpose": "Fund Raising", "date": "15-Oct-2026",
         "bm_desc": "To consider raising funds"},
        {"symbol": "C", "company": "C LTD", "purpose": "Other business matters", "date": "16-Oct-2026",
         "bm_desc": "To consider and approve the financial results for the period ended September 30, 2026"},
    ]
    monkeypatch.setattr(rc.nse_http, "get_json", lambda *a, **k: rows)
    got = rc.meetings(dt.date(2026, 10, 15), dt.date(2026, 10, 16))
    assert [m["symbol"] for m in got] == ["A", "C"]
    assert got[0]["date"] == dt.date(2026, 10, 15)


def test_both_bases_fold_into_one_filing_and_revisions_are_marked(monkeypatch):
    rows = [
        {"symbol": "TARIL", "cmName": "Transformers And Rectifiers (India) Limited",
         "qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "type_Sub": "Original",
         "broadcast_Date": "13-Oct-2026 16:34:09", "type": "Integrated Filing- Financials"},
        {"symbol": "TARIL", "cmName": "Transformers And Rectifiers (India) Limited",
         "qe_Date": "30-SEP-2026", "consolidated": "Standalone", "type_Sub": "Original",
         "broadcast_Date": "13-Oct-2026 16:34:06", "type": "Integrated Filing- Financials"},
        {"symbol": "OLD", "cmName": "Old Ltd", "qe_Date": "30-JUN-2026",
         "consolidated": "Standalone", "type_Sub": "Revision",
         "broadcast_Date": "13-Oct-2026 11:00:00", "type": "Integrated Filing- Financials"},
        {"symbol": "GOV", "cmName": "Gov Ltd", "qe_Date": "30-SEP-2026",
         "broadcast_Date": "13-Oct-2026 11:00:00", "type": "Integrated Filing- Governance"},
    ]
    seen = {}

    def fake(url, params=None, referer=None):
        seen.update(params)
        return {"data": rows, "totalCount": len(rows)}

    monkeypatch.setattr(rc.nse_http, "get_json", fake)
    got = {f["symbol"]: f for f in rc.filings(dt.date(2026, 10, 13), dt.date(2026, 10, 13))}
    assert set(got) == {"TARIL", "OLD"}                  # governance carries no numbers
    assert got["TARIL"]["bases"] == {"consolidated", "standalone"}
    assert got["TARIL"]["at"] == dt.datetime(2026, 10, 13, 16, 34, 6)   # the first to land
    assert not got["TARIL"]["revised"] and got["OLD"]["revised"]
    # Asked for the financials filing only, in one page big enough for a peak week.
    assert seen["type"] == "Integrated Filing- Financials" and seen["size"] >= 1000


def test_a_season_bigger_than_a_page_is_read_to_the_end(monkeypatch):
    pages = []

    def fake(url, params=None, referer=None):
        pages.append(params.get("page"))
        n = len(pages)
        return {"data": [{"symbol": f"S{n}", "cmName": "x", "qe_Date": "30-SEP-2026",
                          "consolidated": "Standalone", "broadcast_Date": "13-Oct-2026 10:00:00",
                          "type": "Integrated Filing- Financials"}], "totalCount": 3}

    monkeypatch.setattr(rc.nse_http, "get_json", fake)
    got = rc.filings(dt.date(2026, 10, 13), dt.date(2026, 10, 13))
    assert sorted(f["symbol"] for f in got) == ["S1", "S2", "S3"]
    assert pages == [None, 2, 3]


NOW = dt.datetime(2026, 10, 14, 15, 0, tzinfo=rc.IST)


def test_nse_down_is_said_not_shown_as_a_quiet_day(monkeypatch):
    monkeypatch.setattr(rc, "_memo", {})
    monkeypatch.setattr(rc.nse_http, "get_json", lambda *a, **k: None)
    out = rc.calendar(now=NOW)
    assert out["available"] is False and "NSE" in out["message"]


def test_one_source_down_is_noted_and_not_held(monkeypatch):
    monkeypatch.setattr(rc, "_memo", {})
    calls = []

    def fake(url, params=None, referer=None):
        calls.append(url)
        if url == rc.FILINGS:
            return None
        return [{"symbol": "A", "company": "A LTD", "purpose": "Financial Results",
                 "date": "14-Oct-2026"}]

    monkeypatch.setattr(rc.nse_http, "get_json", fake)
    out = rc.calendar(now=NOW)
    assert out["available"] and out["notes"] and "filings" in out["notes"][0]
    assert _row(_day(out["days"], "2026-10-14"), "A")["status"] == "today"
    rc.calendar(now=NOW)
    assert len(calls) == 4, "a partial answer was held instead of read again"


def test_a_full_answer_is_held_briefly(monkeypatch):
    monkeypatch.setattr(rc, "_memo", {})
    calls = []

    def fake(url, params=None, referer=None):
        calls.append(url)
        return {"data": [], "totalCount": 0} if url == rc.FILINGS else []

    monkeypatch.setattr(rc.nse_http, "get_json", fake)
    first = rc.calendar(now=NOW)
    assert first["available"] and first["today"] == "2026-10-14" and not first["notes"]
    rc.calendar(now=NOW)
    assert len(calls) == 2
    rc.calendar(now=NOW, force=True)
    assert len(calls) == 4


def test_the_endpoint_answers_and_says_where_it_reads(monkeypatch):
    import main
    monkeypatch.setattr(rc, "_memo", {})
    monkeypatch.setattr(rc.nse_http, "get_json",
                        lambda url, params=None, referer=None:
                        {"data": [], "totalCount": 0} if url == rc.FILINGS else [])
    out = main.results_calendar_view()
    assert out["available"] and "NSE" in out["source"] and len(out["days"]) >= 8
