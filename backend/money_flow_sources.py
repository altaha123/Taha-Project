"""
money_flow_sources.py — reading the public files Money Flow is built on

WHAT IS READ, AND FROM WHERE
  NSDL   the fortnightly sector-wise FPI report. One static HTML page per
         fortnight, linked from a dropdown on FPI_Fortnightly_Selection.aspx.
         The dropdown is the only reliable index: the file names are typed by
         hand ("FIIInvestSector_June302026.html" beside "..._Jul152026.html",
         and one early "FIIInvestSecor_"), so a URL is never built from a
         date, only read from that list.
  NSE    ind_close_all_DDMMYYYY.csv, every index's close for one session;
         bulk.csv and block.csv, the latest session's large deals; and the
         FII/DII provisional figures, which NSE serves for the latest session
         only (market_week.py already reads and parses those).

WHY THE PARSERS DO NOT COUNT COLUMNS
The NSDL table has changed shape three times: Debt VRR arrived in April 2020,
the sector list was replaced in April 2022, and Debt-FAR, Mutual Funds and
AIFs arrived in August 2024, taking a block from 5 columns to 12. A parser
that reads "column 26" is right until the next change and then wrong without
saying so. This one rebuilds the header: every column is given the labels
above it (colspans and rowspans expanded), and a figure is found by what it is
called: the block named "Net Investment <period>", in "INR", the first column
headed "Equity". A report whose header cannot be read that way raises
ParseError and is not stored, so a changed format is a failed job with a
reason, never a quietly wrong number.

Each report carries TWO fortnights: the one it is dated for and the one
before. So every fortnight is published twice, and money_flow.py compares the
two copies when it stores them.

PARSING NEEDS NO NETWORK. Every parse_* function takes text and returns plain
data, which is what backend/tests/test_money_flow_sources.py exercises against
trimmed copies of the real files. The fetch_* functions are thin: a URL, a
retry, a parse.
"""

import csv
import datetime as dt
import io
import re
import time
from html import unescape
from html.parser import HTMLParser

NSDL_BASE = "https://www.fpi.nsdl.co.in/web/"
NSDL_INDEX_URL = NSDL_BASE + "Reports/FPI_Fortnightly_Selection.aspx"
NSE_ARCHIVE_HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
INDEX_PATH = "/content/indices/ind_close_all_%s.csv"
DEALS_PATH = {"bulk": "/content/equities/bulk.csv", "block": "/content/equities/block.csv"}
NSE_DEALS_HISTORY = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
NSE_DEALS_REFERER = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 40
TRIES = 3
BACKOFF = 2.0
NOT_FOUND_BYTES = 600           # the archive's not-found page is a short stub

OK, ABSENT, BLOCKED = "ok", "absent", "blocked"


class ParseError(ValueError):
    """The file was read but is not in a shape this module understands."""


# ---------------------------------------------------------------------------
# Small readers
# ---------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9


def month_number(word):
    """'October', 'OCT', 'Sept.' -> 10, 10, 9. None when it is not a month."""
    return _MONTHS.get(re.sub(r"[^a-z]", "", str(word or "").lower()))


def number(value):
    """
    A figure as NSDL and NSE print them: '4,77,593', '-6,533', '(6,533)',
    ' 12.5 '. None for a blank, a dash or anything that is not a number, so a
    missing cell is never read as zero.
    """
    s = str(value if value is not None else "").replace("\xa0", " ").strip()
    if not s or s in ("-", "--", "NA", "N.A.", "nil", "Nil"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace(" ", "")
    try:
        n = float(s)
    except ValueError:
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return -n if neg else n


def _clean(text):
    return re.sub(r"\s+", " ", unescape(str(text or "")).replace("\xa0", " ")).strip()


def loose_date(text):
    """'NOV 15, 2026', 'March 15, 2012 ', 'October 31, 2026' -> date, or None."""
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*,?\s*(\d{4})", str(text or ""))
    if not m:
        return None
    mon = month_number(m.group(1))
    if not mon:
        return None
    try:
        return dt.date(int(m.group(3)), mon, int(m.group(2)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# HTML tables, with their spans
# ---------------------------------------------------------------------------

class _Tables(HTMLParser):
    """Every <table> in a page as rows of (text, colspan, rowspan). Nested
    tables are kept apart: a cell's text never includes an inner table's."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._stack = []          # open tables: {"rows": [], "row": None, "cell": None}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "table":
            self._stack.append({"rows": [], "row": None, "cell": None})
            return
        if not self._stack:
            return
        t = self._stack[-1]
        if tag == "tr":
            self._close_row(t)
            t["row"] = []
        elif tag in ("td", "th"):
            self._close_cell(t)
            if t["row"] is None:
                t["row"] = []
            a = dict(attrs)
            t["cell"] = {"text": [], "colspan": _span(a.get("colspan")),
                         "rowspan": _span(a.get("rowspan"))}
        elif tag == "br" and t["cell"] is not None:
            t["cell"]["text"].append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if not self._stack:
            return
        t = self._stack[-1]
        if tag in ("td", "th"):
            self._close_cell(t)
        elif tag == "tr":
            self._close_row(t)
        elif tag == "table":
            self._close_row(t)
            self.tables.append(self._stack.pop()["rows"])

    def handle_data(self, data):
        if self._skip or not self._stack:
            return
        cell = self._stack[-1]["cell"]
        if cell is not None:
            cell["text"].append(data)

    @staticmethod
    def _close_cell(t):
        c = t["cell"]
        if c is not None:
            t["row"].append((_clean("".join(c["text"])), c["colspan"], c["rowspan"]))
            t["cell"] = None

    def _close_row(self, t):
        self._close_cell(t)
        if t["row"] is not None:
            t["rows"].append(t["row"])
            t["row"] = None

    def close(self):
        super().close()
        while self._stack:                      # a page cut off mid-table
            t = self._stack[-1]
            self._close_row(t)
            self.tables.append(self._stack.pop()["rows"])


def _span(v):
    try:
        return max(1, min(int(str(v).strip()), 500))
    except (TypeError, ValueError):
        return 1


def tables(html):
    p = _Tables()
    p.feed(html or "")
    p.close()
    return p.tables


def grid(rows):
    """Rows of (text, colspan, rowspan) -> a rectangle of text, every span
    filled with the text of the cell that spans it."""
    out, carry = [], {}                         # carry: col -> (text, rows left)
    for row in rows:
        line, col = [], 0
        cells = list(row)
        while cells or any(c >= col for c in carry):
            if col in carry:
                text, left = carry[col]
                line.append(text)
                if left <= 1:
                    del carry[col]
                else:
                    carry[col] = (text, left - 1)
                col += 1
                continue
            if not cells:
                break
            text, cs, rs = cells.pop(0)
            for _ in range(cs):
                line.append(text)
                if rs > 1:
                    carry[col] = (text, rs - 1)
                col += 1
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# NSDL: the list of reports
# ---------------------------------------------------------------------------

_OPTION = re.compile(r"<option[^>]*\bvalue\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)(?=<)", re.I | re.S)


def parse_nsdl_index(html):
    """
    The reports NSDL lists, newest first:
    [{"url", "label", "report_date" (ISO)}].

    Read from the dropdown's own values. An entry whose label is not a date,
    or whose value is not a report page, is left out; a page with no usable
    entry at all raises ParseError, because that is the page having changed.
    """
    out, seen = [], set()
    for _q, value, label in _OPTION.findall(html or ""):
        value, label = unescape(value).strip(), _clean(label)
        if not re.search(r"\.html?$", value, re.I) or "sector" not in value.lower().replace("secor", "sector"):
            continue
        day = loose_date(label)
        if day is None:
            continue
        url = value
        if url.startswith("~/"):
            url = NSDL_BASE + url[2:]
        elif url.startswith("/"):
            url = "https://www.fpi.nsdl.co.in" + url
        elif not url.lower().startswith("http"):
            url = NSDL_BASE + "Reports/" + url
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "label": label, "report_date": day.isoformat()})
    if not out:
        raise ParseError("NSDL's report list has no fortnightly report in it")
    out.sort(key=lambda r: r["report_date"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# NSDL: one fortnightly report
# ---------------------------------------------------------------------------

_NET = re.compile(
    r"Net\s+Investment\s+(?:for\s+)?([A-Za-z]+)\.?\s+(\d{1,2})\s*(?:-|–|—|to)\s*"
    r"(?:([A-Za-z]+)\.?\s+)?(\d{1,2})\s*,?\s*(\d{4})", re.I)
_AUC = re.compile(r"AUC\s+as\s+on\s+(.+)", re.I)


def _period(label):
    """'Net Investment October 16-31, 2026' -> (date(2026,10,16), date(2026,10,31))."""
    m = _NET.search(label or "")
    if not m:
        return None
    m1, d1, m2, d2, year = m.groups()
    mon1, mon2 = month_number(m1), month_number(m2 or m1)
    if not mon1 or not mon2:
        return None
    try:
        end = dt.date(int(year), mon2, int(d2))
        start_year = int(year) - 1 if mon1 > mon2 else int(year)
        start = dt.date(start_year, mon1, int(d1))
    except ValueError:
        return None
    return (start, end) if start <= end else None


def _is_serial(text):
    return bool(re.fullmatch(r"\d{1,3}\.?", (text or "").strip()))


def _find_report_table(html):
    best = None
    for rows in tables(html):
        g = grid(rows)
        text = " ".join(c for line in g[:8] for c in line)
        if "Net Investment" in text and re.search(r"\bSectors?\b", text, re.I):
            width = max((len(line) for line in g), default=0)
            if best is None or width > best[0]:
                best = (width, g)
    if best is None:
        raise ParseError("no table with 'Net Investment' and 'Sectors' in its header")
    return best[1]


def parse_nsdl_report(html):
    """
    One fortnightly page ->

        {"periods": [{"start", "end", "label"}, ...],     oldest first
         "rows": [{"sector", "period_start", "period_end",
                   "equity_net_inr_cr", "equity_net_usd_mn",
                   "total_net_inr_cr", "equity_auc_inr_cr"}, ...],
         "grand_total": {period_end: equity_net_inr_cr},
         "warnings": [...]}

    `equity_auc_inr_cr` is the equity assets under custody on period_end, when
    the page states AUC for that date (it does for the later of its two
    fortnights; the earlier one's closing AUC is the page's opening AUC).

    Raises ParseError when the header cannot be read by name.
    """
    g = _find_report_table(html)
    width = max(len(line) for line in g)
    g = [line + [""] * (width - len(line)) for line in g]

    first = next((i for i, line in enumerate(g)
                  if _is_serial(line[0]) and len([c for c in line if c]) > 3), None)
    if first is None or first == 0:
        raise ParseError("the report has a header but no numbered sector rows")
    header = g[:first]

    sector_col = 1
    for line in header:
        for c, text in enumerate(line[:4]):
            if re.fullmatch(r"Sectors?", text, re.I):
                sector_col = c

    # What each column is, read from the labels stacked above it.
    cols = []
    for c in range(width):
        labels = [line[c] for line in header if line[c]]
        block = next((x for x in labels if _NET.search(x) or _AUC.search(x)), None)
        cur = next(("INR" if "INR" in x.upper() else "USD" for x in labels
                    if "INR" in x.upper() or "USD" in x.upper()), None)
        rest = [x for x in labels if x != block and "INR" not in x.upper() and "USD" not in x.upper()]
        cols.append({"block": block, "cur": cur, "labels": rest})

    def group(block_label, cur):
        return [c for c in range(width) if cols[c]["block"] == block_label and cols[c]["cur"] == cur]

    def equity_col(idx):
        # The first column headed Equity that is not inside the mutual-fund
        # group (which has an "Equity" scheme column of its own).
        for c in idx:
            labs = [x.lower() for x in cols[c]["labels"]]
            if labs and labs[0] == "equity" and not any("mutual" in x for x in labs):
                return c
        return None

    def total_col(idx):
        for c in reversed(idx):
            if any(x.lower() == "total" for x in cols[c]["labels"]):
                return c
        return None

    blocks = []
    for c in range(width):
        b = cols[c]["block"]
        if b and b not in blocks:
            blocks.append(b)
    nets, aucs = [], {}
    for b in blocks:
        per = _period(b)
        if per:
            nets.append((b, per))
            continue
        m = _AUC.search(b)
        day = loose_date(m.group(1)) if m else None
        if day:
            aucs[day] = b
    if not nets:
        raise ParseError("no 'Net Investment <month> <d>-<d>, <year>' block in the header")
    nets.sort(key=lambda t: t[1][1])

    plan, warnings = [], []
    for label, (start, end) in nets:
        inr, usd = group(label, "INR"), group(label, "USD")
        eq = equity_col(inr)
        if eq is None:
            raise ParseError("no Equity column under %r in INR" % label)
        auc_col = None
        if end in aucs:
            auc_col = equity_col(group(aucs[end], "INR"))
        plan.append({"start": start, "end": end, "label": label, "eq_inr": eq,
                     "eq_usd": equity_col(usd), "tot_inr": total_col(inr), "auc_inr": auc_col})

    rows, grand = [], {}
    for line in g[first:]:
        name = line[sector_col].strip()
        low = name.lower()
        if not name:
            # NSDL prints the total with the label in the serial column on
            # some pages and in the sector column on others.
            name, low = line[0].strip(), line[0].strip().lower()
        is_total = low in ("grand total", "total")
        if not is_total and not _is_serial(line[0]):
            if rows:
                break                              # the notes under the table
            continue
        for p in plan:
            net = number(line[p["eq_inr"]])
            if is_total:
                if net is not None:
                    grand[p["end"].isoformat()] = net
                continue
            rows.append({
                "sector": name,
                "period_start": p["start"].isoformat(),
                "period_end": p["end"].isoformat(),
                "equity_net_inr_cr": net,
                "equity_net_usd_mn": number(line[p["eq_usd"]]) if p["eq_usd"] is not None else None,
                "total_net_inr_cr": number(line[p["tot_inr"]]) if p["tot_inr"] is not None else None,
                "equity_auc_inr_cr": number(line[p["auc_inr"]]) if p["auc_inr"] is not None else None,
            })
        if is_total:
            break

    if len({r["sector"] for r in rows}) < 10:
        raise ParseError("only %d sectors read from the report" % len({r["sector"] for r in rows}))
    # The page's own total is the check that the right column was read.
    for p in plan:
        key = p["end"].isoformat()
        got = [r["equity_net_inr_cr"] for r in rows if r["period_end"] == key]
        if key in grand and all(v is not None for v in got):
            diff = abs(sum(got) - grand[key])
            # Each cell is rounded to a crore, so a couple of dozen sectors can
            # differ from the printed total by a few crore and still be right.
            if diff > max(30.0, 0.002 * abs(grand[key])):
                warnings.append("sectors sum to %.0f for %s, the page's total is %.0f"
                                % (sum(got), key, grand[key]))
        elif key not in grand:
            warnings.append("no grand total on the page for %s" % key)
    return {
        "periods": [{"start": p["start"].isoformat(), "end": p["end"].isoformat(),
                     "label": p["label"]} for p in plan],
        "rows": rows, "grand_total": grand, "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# NSE: every index's close for one session
# ---------------------------------------------------------------------------

def _row_date(text):
    text = str(text or "").strip()
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text[:11].strip(), fmt).date()
        except ValueError:
            pass
    return None


def index_key(name):
    """One spelling per index: NSE writes 'Nifty Auto' and 'NIFTY Midcap 100'."""
    return " ".join(str(name or "").upper().split())


def parse_index_csv(text):
    """
    ind_close_all_DDMMYYYY.csv -> (date, {INDEX NAME: close}).

    An HTML error page, a file with no usable row, or rows carrying more than
    one date raise ParseError. Zero and negative closes are dropped.
    """
    body = (text or "").lstrip("﻿").strip()
    if not body or body[:1] == "<":
        raise ParseError("the index file is not CSV")
    closes, days = {}, {}
    for raw in csv.DictReader(io.StringIO(body)):
        row = {(k or "").strip(): v for k, v in raw.items()}
        key = index_key(row.get("Index Name"))
        close = number(row.get("Closing Index Value"))
        day = _row_date(row.get("Index Date"))
        if not key or close is None or close <= 0 or day is None:
            continue
        closes[key] = close
        days[day] = days.get(day, 0) + 1
    if not closes:
        raise ParseError("no index row with a name, a date and a close")
    if len(days) > 1:
        raise ParseError("the index file carries %d different dates" % len(days))
    return next(iter(days)), closes


# ---------------------------------------------------------------------------
# NSE: bulk and block deals
# ---------------------------------------------------------------------------

def _iso_day(text):
    s = str(text or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s.title() if "-" in s and not s[:4].isdigit() else s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def deal_row(date, symbol, name, client, side, qty, price, kind, remarks=None):
    """One disclosure in the stored shape, or None when it is not usable."""
    day = _iso_day(date)
    q, p = number(qty), number(price)
    s = str(side or "").strip().upper()
    side = "BUY" if s.startswith("B") else "SELL" if s.startswith("S") else None
    symbol = str(symbol or "").strip().upper()
    client = re.sub(r"\s+", " ", str(client or "")).strip().upper()
    if not (day and symbol and client and side and q and p and q > 0 and p > 0):
        return None
    rem = str(remarks or "").strip()
    return {"date": day, "symbol": symbol, "name": str(name or "").strip(), "client": client,
            "side": side, "qty": q, "price": p, "kind": kind,
            "remarks": None if rem in ("", "-") else rem}


def parse_deals_csv(text, kind):
    """
    bulk.csv / block.csv -> [deal rows]. "NO RECORDS" (a session with no
    block deal is common) is an empty list; anything that is not the expected
    CSV raises ParseError.
    """
    body = (text or "").lstrip("﻿").strip()
    if not body or body[:1] == "<":
        raise ParseError("the %s deals file is not CSV" % kind)
    reader = csv.reader(io.StringIO(body))
    try:
        head = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        raise ParseError("the %s deals file is empty" % kind)

    def col(*needles):
        for i, h in enumerate(head):
            if all(n in h for n in needles):
                return i
        return None

    ix = {"date": col("date"), "symbol": col("symbol"), "name": col("security"),
          "client": col("client"), "side": col("buy"), "qty": col("quantity"),
          "price": col("price"), "remarks": col("remark")}
    missing = [k for k in ("date", "symbol", "client", "side", "qty", "price") if ix[k] is None]
    if missing:
        raise ParseError("the %s deals file has no %s column" % (kind, ", ".join(missing)))
    out = []
    for line in reader:
        if not line or "NO RECORDS" in " ".join(line).upper():
            continue
        get = lambda k: line[ix[k]] if ix[k] is not None and ix[k] < len(line) else None
        row = deal_row(get("date"), get("symbol"), get("name"), get("client"), get("side"),
                       get("qty"), get("price"), kind, get("remarks"))
        if row:
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _transports():
    """Ways to make a GET, most ordinary first. Each returns (status, bytes).

    Plain requests is tried first because it is what answers on most days.
    curl_cffi with a Chrome handshake is the fallback for the days NSE's edge
    refuses a datacenter address (nse_http.py has the measurements), and
    urllib is there so the module still works where neither is installed.
    """
    out = []
    try:
        import requests

        def via_requests(url, referer):
            h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
            if referer:
                h["Referer"] = referer
            r = requests.get(url, headers=h, timeout=TIMEOUT)
            return r.status_code, r.content
        out.append(via_requests)
    except Exception:
        pass
    try:
        from curl_cffi import requests as cr

        def via_curl(url, referer):
            r = cr.get(url, impersonate="chrome", timeout=TIMEOUT,
                       headers={"Referer": referer} if referer else None)
            return r.status_code, r.content
        out.append(via_curl)
    except Exception:
        pass

    def via_urllib(url, referer):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        h = {"User-Agent": UA, "Accept": "*/*"}
        if referer:
            h["Referer"] = referer
        try:
            with urlopen(Request(url, headers=h), timeout=TIMEOUT) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            return e.code, b""
    out.append(via_urllib)
    return out


def http_get(url, referer=None, tries=TRIES, sleep=time.sleep):
    """
    (state, bytes): "ok" with the body, "absent" for a 404, "blocked" when
    every try was refused or failed. Retries with a growing pause, moving to
    the next transport each time, so one refused handshake is not the answer.
    """
    ways = _transports()
    last = BLOCKED
    for attempt in range(max(1, tries)):
        way = ways[attempt % len(ways)]
        try:
            status, body = way(url, referer)
        except Exception:
            status, body = None, b""
        if status == 200 and body:
            return OK, body
        if status == 404:
            last = ABSENT
            # A 404 from the archive is an answer, not a refusal: ask once
            # more by another route and then believe it.
            if attempt >= 1:
                return ABSENT, b""
        else:
            last = BLOCKED
        # A refusal is waited out; a 404 is asked again at once, by the next
        # route, because there is nothing to wait for.
        if attempt < tries - 1 and status != 404:
            sleep(BACKOFF * (attempt + 1))
    return last, b""


def _text(body):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            pass
    return body.decode("utf-8", "replace")


def fetch_nsdl_index(get=http_get):
    state, body = get(NSDL_INDEX_URL)
    if state != OK:
        raise ConnectionError("NSDL's report list did not answer (%s)" % state)
    return parse_nsdl_index(_text(body))


def fetch_nsdl_report(url, get=http_get):
    state, body = get(url, referer=NSDL_INDEX_URL)
    if state != OK:
        raise ConnectionError("NSDL report did not answer (%s): %s" % (state, url))
    return parse_nsdl_report(_text(body))


def fetch_index_day(day, get=http_get):
    """(state, {NAME: close}) for one calendar day. "absent" is a day NSE has
    no file for; "blocked" is a day to ask for again."""
    worst = ABSENT
    for host in NSE_ARCHIVE_HOSTS:
        state, body = get(host + INDEX_PATH % day.strftime("%d%m%Y"),
                          referer="https://www.nseindia.com/")
        if state == OK:
            if len(body) < NOT_FOUND_BYTES:
                continue
            try:
                got, closes = parse_index_csv(_text(body))
            except ParseError:
                worst = BLOCKED
                continue
            if got != day:
                worst = BLOCKED
                continue
            return OK, closes
        if state == BLOCKED:
            worst = BLOCKED
        elif state == ABSENT and worst != BLOCKED:
            return ABSENT, {}
    return worst, {}


def fetch_deals_latest(get=http_get):
    """The latest session's bulk and block deals from the archive's CSVs.
    Returns (rows, errors): one kind failing does not lose the other."""
    rows, errors = [], []
    for kind, path in DEALS_PATH.items():
        got = None
        for host in NSE_ARCHIVE_HOSTS:
            state, body = get(host + path, referer="https://www.nseindia.com/")
            if state != OK:
                continue
            try:
                got = parse_deals_csv(_text(body), kind)
                break
            except ParseError as e:
                errors.append(str(e))
        if got is None:
            errors.append("%s deals file did not answer" % kind)
        else:
            rows += got
    return rows, errors


def fetch_deals_history(kind, start, end):
    """
    Past disclosures between two dates from NSE's history API, through
    nse_http (the Chrome handshake that API needs).

    Asked for as CSV, which is the site's own download and returns the whole
    window. The JSON answer of the same API stops at 70 rows without saying
    so: one busy session is more than that, so a month read as JSON is the
    first day of the month and nothing after it.

    None when NSE refuses, which from a datacenter address it often does: the
    caller records that the window was not read, and the daily file fills the
    record from then on.
    """
    import nse_http
    opt = {"bulk": "bulk_deals", "block": "block_deals"}[kind]
    r = nse_http.get(NSE_DEALS_HISTORY, referer=NSE_DEALS_REFERER, params={
        "optionType": opt, "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y"),
        "csv": "true"})
    if r is None:
        return None
    try:
        return parse_deals_csv(_text(r.content), kind)
    except ParseError:
        return None
