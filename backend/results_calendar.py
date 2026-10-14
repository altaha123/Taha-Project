"""
Altaha Screener — the results calendar

Who reports when: yesterday, today, tomorrow, this week and next. Two exchange
sources, joined on the NSE symbol.

  SCHEDULED   NSE's event calendar. A company must tell the exchange in
              advance when its board meets to approve results (LODR Reg 29),
              so this is the date announced by the company itself, not an
              estimate.
  DECLARED    NSE's Integrated Filing index, filtered to the Financials
              filing. This is the results document itself reaching the
              exchange, timestamped, which is what "results are out" means.

A row therefore says one of four things, and never more than the two sources
can support:

  declared    the filing is on NSE, with the time it arrived
  today       the board meets today and nothing has been filed yet
  scheduled   the board meets on a later date
  awaited     the board met and the filing has not reached NSE yet

COSTS
Two calls cover the whole window, whatever the season: measured in a peak
week, 722 filings and 976 meetings across two weeks, each in about two
seconds. The answer is held for five minutes, because filings land all
evening and a page that is a day stale is the exact complaint this replaced.
"""

import datetime as dt
import re
import threading
import time

import nse_http

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

EVENTS = "https://www.nseindia.com/api/event-calendar"
EVENTS_REF = "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"
FILINGS = "https://www.nseindia.com/api/integrated-filing-results"
FILINGS_REF = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"

# The index pages twenty rows at a time unless asked for more; the largest
# week measured was 722, so this is one page with room to spare, and the
# reader still pages if a season ever outgrows it.
PAGE = 5000
MAX_PAGES = 5
TTL = 300

# A filing that lands this many days after the board met is still that
# meeting's result: the XBRL is due within a day, and some companies file it
# the next morning.
LATE_FILING_DAYS = 3

_lock = threading.Lock()
_memo = {}


def today_ist(now=None):
    return (now or dt.datetime.now(IST)).astimezone(IST).date()


def _d(s):
    s = str(s or "").strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _nse(d):
    return d.strftime("%d-%m-%Y")


def quarter_label(end):
    """'Q2 FY27' for the Indian fiscal quarter ending on `end`."""
    if not end:
        return None
    q = {3: 4, 6: 1, 9: 2, 12: 3}.get(end.month)
    if not q:
        return None
    fy = end.year + 1 if end.month >= 4 else end.year
    return "Q%d FY%02d" % (q, fy % 100)


# ---------------------------------------------------------------------------
# The two sources
# ---------------------------------------------------------------------------

_RESULTS = re.compile(r"financial\s+results?", re.I)


def meetings(start, end):
    """
    Board meetings that will consider results, start..end inclusive.
    None when NSE could not be read, which is different from an empty list.
    """
    body = nse_http.get_json(EVENTS, params={"index": "equities",
                                             "from_date": _nse(start), "to_date": _nse(end)},
                             referer=EVENTS_REF)
    if body is None:
        return None
    out = []
    for r in nse_http.rows(body):
        purpose = str(r.get("purpose") or "")
        if not _RESULTS.search(purpose + " " + str(r.get("bm_desc") or "")):
            continue
        when = _d(r.get("date"))
        sym = str(r.get("symbol") or "").strip().upper()
        if not when or not sym:
            continue
        out.append({"symbol": sym, "company": str(r.get("company") or sym).strip(),
                    "date": when.date(), "purpose": purpose.strip()})
    return out


def filings(start, end):
    """
    Results filings that reached NSE start..end inclusive, one row per
    company per day with both accounting bases folded together.
    None when NSE could not be read.
    """
    rows, page = [], 0
    while page < MAX_PAGES:
        params = {"index": "equities", "type": "Integrated Filing- Financials",
                  "from_date": _nse(start), "to_date": _nse(end), "size": PAGE}
        if page:
            params["page"] = page + 1
        body = nse_http.get_json(FILINGS, params=params, referer=FILINGS_REF)
        if body is None:
            return None if not rows else _fold(rows)
        got = nse_http.rows(body)
        rows.extend(got)
        total = body.get("totalCount") if isinstance(body, dict) else None
        if not got or not isinstance(total, int) or len(rows) >= total:
            break
        page += 1
    return _fold(rows)


def _fold(rows):
    by = {}
    for r in rows:
        if "financ" not in str(r.get("type") or "").lower():
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        at = _d(r.get("broadcast_Date") or r.get("creation_Date"))
        if not sym or not at:
            continue
        qe = _d(r.get("qe_Date"))
        key = (sym, at.date(), qe.date() if qe else None)
        cur = by.get(key)
        basis = str(r.get("consolidated") or "").strip().lower()
        revised = str(r.get("type_Sub") or "").strip().lower().startswith("revis")
        if cur is None:
            cur = by[key] = {"symbol": sym,
                             "company": str(r.get("cmName") or r.get("smName") or sym).strip(),
                             "at": at, "quarter_end": key[2], "bases": set(),
                             "revised": True}
        # The first filing of the day is when the result became public.
        cur["at"] = min(cur["at"], at)
        if basis in ("consolidated", "standalone"):
            cur["bases"].add(basis)
        # A day that carries an original filing is that result's day, even
        # if a revision of it arrived the same evening.
        cur["revised"] = cur["revised"] and revised
    return list(by.values())


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

def window(today=None):
    """Yesterday (or this Monday, if earlier) to the end of next week."""
    today = today or today_ist()
    monday = today - dt.timedelta(days=today.weekday())
    start = min(today - dt.timedelta(days=1), monday)
    end = monday + dt.timedelta(days=13)
    return start, end


def _row_from_filing(f):
    out = {"symbol": f["symbol"], "company": f["company"], "status": "declared",
           "filed_at": f["at"].strftime("%Y-%m-%dT%H:%M:%S"),
           "quarter": quarter_label(f["quarter_end"]),
           "bases": sorted(f["bases"])}
    if f["revised"]:
        out["revised"] = True
    return out


def build(meets, files, start, end, today):
    """
    One entry per day, start..end, each with its rows. Pure: the network is
    the caller's, so this is what the tests exercise.
    """
    meets = meets or []
    files = files or []

    # Each company's filings in time order, for matching a meeting to the
    # filing it produced.
    by_sym = {}
    for f in files:
        by_sym.setdefault(f["symbol"], []).append(f)
    for v in by_sym.values():
        v.sort(key=lambda f: f["at"])

    days = {}
    for i in range((end - start).days + 1):
        d = start + dt.timedelta(days=i)
        days[d] = {}

    claimed = set()      # (symbol, filed date) shown under a meeting's day
    for m in meets:
        d = m["date"]
        if d not in days:
            continue
        match = None
        for f in by_sym.get(m["symbol"], []):
            gap = (f["at"].date() - d).days
            if 0 <= gap <= LATE_FILING_DAYS:
                match = f
                break
        if match:
            row = _row_from_filing(match)
            row["company"] = match["company"] or m["company"]
            claimed.add((match["symbol"], match["at"].date()))
        else:
            status = "scheduled" if d > today else ("today" if d == today else "awaited")
            row = {"symbol": m["symbol"], "company": m["company"], "status": status}
        row["meeting"] = d.isoformat()
        row["purpose"] = m["purpose"]
        days[d][m["symbol"]] = row

    # Filings with no meeting in the window: a company that met before it
    # began, or one the calendar never listed. Shown on the day they arrived.
    for f in files:
        d = f["at"].date()
        if d not in days or (f["symbol"], d) in claimed or f["symbol"] in days[d]:
            continue
        days[d][f["symbol"]] = _row_from_filing(f)

    order = {"today": 0, "awaited": 1, "scheduled": 2}
    out = []
    for d in sorted(days):
        rows = list(days[d].values())
        # The newest filing first — on a results evening that is the news —
        # then everyone still to file, by name.
        filed = sorted((r for r in rows if r["status"] == "declared"),
                       key=lambda r: r["filed_at"], reverse=True)
        rest = sorted((r for r in rows if r["status"] != "declared"),
                      key=lambda r: (order.get(r["status"], 9), r["company"].lower()))
        out.append({"date": d.isoformat(), "declared": len(filed), "pending": len(rest),
                    "rows": filed + rest})
    return out


def calendar(now=None, force=False):
    """The window around today, from NSE, held for TTL seconds."""
    today = today_ist(now)
    start, end = window(today)
    key = (start, end)
    with _lock:
        hit = _memo.get(key)
        if hit and not force and time.time() - hit[0] < TTL:
            return hit[1]

    meets = meetings(start, end)
    files = filings(start, min(end, today))
    notes = []
    if meets is None:
        notes.append("NSE's board-meeting calendar could not be read just now, so "
                     "companies yet to file are missing. Try again in a minute.")
    if files is None:
        notes.append("NSE's results filings could not be read just now, so nothing "
                     "is shown as filed. Try again in a minute.")
    if meets is None and files is None:
        return {"available": False, "today": today.isoformat(),
                "message": "NSE could not be reached just now. Try again in a minute."}

    out = {
        "available": True,
        "today": today.isoformat(),
        "from": start.isoformat(), "to": end.isoformat(),
        "days": build(meets, files, start, end, today),
        "checked_at": dt.datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S"),
        "source": ("NSE event calendar (board meetings to approve results) and NSE "
                   "Integrated Filing — Financials (the results as filed)"),
        "notes": notes,
    }
    if not notes:
        with _lock:
            if len(_memo) > 8:
                _memo.clear()
            _memo[key] = (time.time(), out)
    return out
