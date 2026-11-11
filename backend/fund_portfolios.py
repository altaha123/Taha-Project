"""
fund_portfolios.py — what the fund houses hold, from their monthly disclosures

WHERE THIS DATA ACTUALLY LIVES
Not in one place. SEBI requires every asset manager to publish each scheme's
full portfolio monthly, within ten days of month end, and AMFI lists who must
do it — but AMFI aggregates nothing. Its portfolio-disclosure page carries one
link per AMC and all of them point at different websites.

Measured on 11 November 2026, page by page: about twenty serve their workbook
links in plain HTML; the rest build the list in JavaScript, fetch it from an
API, hand out a zip, or refuse the request outright (HDFC's and Edelweiss's
CDNs answer 403, Kotak serves a bot challenge). A generic "find the .xlsx link"
reads the first group and nothing else — which is why the largest houses get a
per-AMC source below (SOURCES), each one the public endpoint or file path the
AMC's own page uses.

So this reaches what it can reach, records which AMCs it got and why the rest
failed, and the coverage is published rather than implied. A page that shows
twenty fund houses while looking like it shows the industry is the failure
mode here.

WHY THE FUND SIDE IS SAFER THAN THE INVESTOR SIDE
Every row carries an ISIN. Joining a holding to a listed company is an exact
lookup against NSE's own equity list, not a judgement about whether two
spellings of a name are the same person. There is no curated table here and
nothing is inferred — an ISIN maps or it does not.

WHAT IS AND IS NOT AN EQUITY POSITION
A monthly pack contains the whole portfolio: shares, debentures, government
securities, InvIT units, treasury bills. Only listed equity is kept, and the
filter is the NSE map itself rather than a guess about the instrument — a row
whose ISIN is not in the equity list is stored with no symbol and counted, so
the weights on screen can be reconciled against the fund's real book instead
of quietly adding up to less.

MONTHLY, AND LATE
Disclosures are due by the tenth of the following month. A position here can be
six weeks old. That is still far fresher than the quarterly shareholding
filings the individual-investor side reads, and it is complete rather than
truncated at 1% — but it is not live, and the API says so on every response.
"""

import datetime as dt
import html as _html
import json
import os
import re
import tempfile
import zipfile
from urllib.parse import quote, unquote, urlparse

try:
    import holdings_store as store
except Exception:                                   # pragma: no cover
    store = None

try:
    import fund_workbook
except Exception:                                   # pragma: no cover
    fund_workbook = None

try:
    import nse_http
except Exception:                                   # pragma: no cover
    nse_http = None

AMFI_DIRECTORY = "https://www.amfiindia.com/online-center/portfolio-disclosure"
NSE_EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_LIST_REFERER = ("https://www.nseindia.com/market-data/"
                    "securities-available-for-trading")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
ISIN_CACHE = os.path.join(_DATA_DIR, "nse-isin-map.json")

# An Indian ISIN's security-type segment sits at positions 7-8. "01" is equity
# shares; 07/08 are debentures, 14/16 commercial paper, 23 InvIT and REIT
# units. Used only to skip obvious non-equity before the authoritative lookup,
# so a workbook of four thousand debt rows is not four thousand map misses.
EQUITY_SEGMENT = "01"

# A pack is fifteen megabytes; ICICI Prudential's zip of 151 workbooks is
# twenty-six. Anything far past that is not a monthly portfolio.
MAX_DOWNLOAD = 120 * 1024 * 1024

# Why the last fetch of a URL failed, for the note an AMC's result carries.
# "No workbook link" and "the site refused us" are different problems with
# different fixes, and reporting both as the first sent people looking at
# JavaScript when the answer was a CDN blocking the instance's address.
_LAST_ERROR = {}


def _http(url, timeout=40, data=None, headers=None):
    """A plain fetch with a browser user agent. AMC sites are ordinary web
    servers — it is NSE, not them, that needs an impersonated handshake.
    `data` makes it a POST, which SBI's portfolio list needs."""
    try:
        import urllib.request
        h = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _LAST_ERROR.pop(url, None)
            return r.read()
    except Exception as e:
        _LAST_ERROR[url] = _describe_error(e)
        return None


def _describe_error(e):
    code = getattr(e, "code", None)
    if code:
        return "HTTP %s" % code
    reason = getattr(e, "reason", None) or e
    return str(reason)[:80]


def _download(url, timeout=180, headers=None):
    """
    Stream one file to a temporary path. Returns (path, None) or (None, why).

    To disk rather than into memory: ICICI Prudential's monthly zip is 26 MB,
    and the web instance this runs on has 512.
    """
    import urllib.request
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    path = None
    try:
        # Links from an API can carry raw spaces, which urllib refuses; this
        # leaves an already-escaped URL as it is.
        url = quote(url, safe=":/?&=%#+,;@!$'()*~[]")
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r, \
                tempfile.NamedTemporaryFile(suffix=".dl", delete=False) as fh:
            path = fh.name
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_DOWNLOAD:
                    raise ValueError("larger than %d MB" % (MAX_DOWNLOAD >> 20))
                fh.write(chunk)
        if not got:
            raise ValueError("empty response")
        return path, None
    except Exception as e:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass
        return None, _describe_error(e)


# ---------------------------------------------------------------------------
# The AMFI directory
# ---------------------------------------------------------------------------

# Whitespace-tolerant: the live payload is compact, but pinning the parse to
# that is the kind of assumption that breaks on a framework upgrade rather
# than on anything about the data.
_AMC_RECORD = re.compile(r'\{\s*"mf_id".*?"icons"\s*:\s*\[.*?\]\s*\}')


def amc_directory():
    """
    Every AMC AMFI lists, with the link to its own monthly disclosure page.

    AMFI's page is a JavaScript app that streams its data as escaped chunks
    inside the HTML, so the records are pulled out of the payload rather than
    scraped from the rendered table — there is no rendered table in the HTML.
    On 11 November 2026 this returned all 57 records (55 with a link), both
    from a workstation and from the deployed instance.
    """
    blob = _http(AMFI_DIRECTORY)
    if not blob:
        return []
    html = blob.decode("utf-8", "replace")
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        return []
    try:
        payload = "".join(chunks).encode().decode("unicode_escape", "replace")
    except Exception:
        return []
    out = []
    for raw in _AMC_RECORD.findall(payload):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        out.append({
            "amc_id": str(d.get("mf_id") or "").strip(),
            "name": (d.get("mf_name") or "").strip(),
            "amc_name": (d.get("amc_name") or "").strip(),
            "website": (d.get("amc_website") or "").strip(),
            "monthly_url": (d.get("amc_monthly_portfolio_disclosure") or "").strip(),
        })
    return [a for a in out if a["amc_id"] and a["name"]]


# Workbook and zip links, quoted either way, with or without a query string:
# SBI's carry "?sfvrsn=95fe7a7e_2", and a pattern that ended at the extension
# found none of them.
_WORKBOOK = re.compile(
    r'''href\s*=\s*["']([^"'<>]+?\.(?:xlsx|xlsm|xls|zip)(?:\?[^"'<>]*)?)["']''', re.I)
_MONTHLY_HINT = re.compile(r"month|portfolio", re.I)

# Things on a disclosure page that are workbooks but not the monthly
# portfolio. Nippon India's page interleaves its monthly packs with
# fortnightly ones, "Risk-Parameter" files and a "Weblink" zip of a hundred
# additional per-scheme disclosures, and the newest-dated file on the page is
# a fortnightly pack.
_NOT_MONTHLY = re.compile(
    r"fortnight|half[-_ ]?year|risk[-_ ]?(?:parameter|o[-_ ]?meter)|"
    r"fact[-_ ]?sheet|\bter\b|expense[-_ ]?ratio|dividend[-_ ]?(?:history|master)|"
    r"divmast|\bnav\b|overlap|\baum\b|commission|voting|stewardship|"
    r"transaction|futures?[-_ ]?disclo|weblink|dashboard|aaum|replication|"
    r"tracking[-_ ]?(?:error|difference)|performance|branches|bank[-_ ]?list|"
    r"summary[-_ ]?document|complaint|top[-_ ]?\d+[-_ ]?issuer|\bfmp\b|"
    r"fixed[-_ ]?maturity", re.I)

# What a bot-challenge or access-denied page looks like, so that a blocked
# request is reported as blocked and not as "this AMC uses JavaScript".
# Specific to challenge pages: a plain "captcha" also appears on ordinary
# pages with a contact form (Mirae's), and calling those blocked is as wrong
# as calling a blocked page JavaScript.
_CHALLENGE = re.compile(
    r"perfdrive|shieldsquare|<title>\s*access denied|"
    r"cf-browser-verification|<title>\s*just a moment\.\.\.", re.I)


def find_workbooks(page_url, html=None):
    """
    Workbook links on an AMC's disclosure page, most likely first.

    Static HTML only. Many AMCs build this list in JavaScript and return
    nothing here; that is a coverage gap, and it is reported as one rather
    than being silently treated as "this AMC published nothing".
    """
    if html is None:
        blob = _http(page_url)
        if not blob:
            return []
        html = blob.decode("utf-8", "replace")
    seen, out = set(), []
    if _CHALLENGE.search(html[:20000]) and not _WORKBOOK.search(html):
        _LAST_ERROR[page_url] = "bot challenge"
        return []
    for href in _WORKBOOK.findall(html):
        href = _html.unescape(href).strip()
        url = href if href.startswith("http") else _absolute(page_url, href)
        # Zerodha's links carry raw spaces ("All Schemes Dashboard - ..."),
        # which urllib refuses to request. Existing escapes are kept.
        url = quote(url, safe=":/?&=%#+,;@!$'()*~[]") if url else url
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    # A monthly pack usually says so in its filename. Ranked rather than
    # filtered, because some AMCs name the file after the scheme instead.
    out.sort(key=lambda u: (0 if _MONTHLY_HINT.search(u) else 1))
    return out


def _absolute(base, href):
    try:
        from urllib.parse import urljoin
        return urljoin(base, href)
    except Exception:
        return None


def _filename(url):
    """The file a link serves. Usually the last path segment; when that is a
    script (NJ's "viewfile.php?file=NJ-MF-Monthly-Portfolio-...xlsx"), the
    query value that names a workbook. Never the rest of the query string —
    PPFAS appends its upload date there ("?09112026")."""
    p = urlparse(url)
    name = unquote(p.path.rsplit("/", 1)[-1])
    if not re.search(r"\.(?:xlsx|xlsm|xls|zip)$", name, re.I) and p.query:
        for part in p.query.split("&"):
            value = unquote(part.split("=", 1)[-1])
            if re.search(r"\.(?:xlsx|xlsm|xls|zip)$", value, re.I):
                return value.rsplit("/", 1)[-1]
    return name


def month_candidates(urls, max_files=160, today=None):
    """
    A page's workbook links, grouped by the month they describe, newest first.

    Each group is the files to read for that month: the one all-schemes pack
    when the page offers one (SBI lists it beside a file per scheme), or
    every scheme's file when that is how the house publishes. Links whose
    month cannot be read from the filename come last, as one group whose
    month is read from the sheets' own date lines.
    """
    by_month, undated = {}, []
    latest = latest_possible_month(today)
    for u in urls:
        name = _filename(u)
        if _NOT_MONTHLY.search(name):
            continue
        # The file's name only, never the rest of the query string: PPFAS
        # appends the upload date ("?09112026"), which read as a date filed
        # October's pack under November.
        m, day = date_parts(name)
        if m and m > latest:
            continue                    # a month that has not ended yet
        if m:
            by_month.setdefault(m, []).append((u, day))
        else:
            undated.append(u)
    out = []
    for m in sorted(by_month, reverse=True):
        # A file dated mid-month is not the month-end portfolio: a fortnightly
        # pack dated the 15th, an FMP's interim statement.
        items = [(u, d) for u, d in by_month[m] if d is None or d >= 25]
        # A daily series — Old Bridge posts an "IR_..." file every working day
        # — keeps only its last day, beside the files that carry no day.
        days = {d for _u, d in items if d}
        if len(days) > 3:
            items = [(u, d) for u, d in items if d is None or d == max(days)]
        files = [u for u, _d in items]
        if not files:
            continue
        whole = [u for u in files if re.search(
            r"all[-_ ]?schemes?|consolidat|complete|combined", _filename(u), re.I)]
        files = whole[:1] if whole else files[:max_files]
        out.append({"as_of": m, "sources": [{"url": u} for u in files]})
    if undated:
        # One group: each file's month is read from its sheets and the newest
        # month among them is the one recorded (Quantum names its files by
        # UUID, Abakkus by scheme).
        out.append({"as_of": None, "sources": [{"url": u} for u in undated[:24]]})
    return out


# ---------------------------------------------------------------------------
# ISIN -> NSE symbol
# ---------------------------------------------------------------------------

def _load_cached_map():
    try:
        with open(ISIN_CACHE) as fh:
            d = json.load(fh)
        if isinstance(d, dict) and d.get("map"):
            return d
    except Exception:
        pass
    return None


def isin_map(refresh=False, max_age_days=14):
    """
    NSE's own equity list, as {ISIN: SYMBOL}.

    Cached on disk, because it changes by a handful of rows a week and the
    exchange throttles. When the fetch fails the cache is used however old it
    is and `stale` says so: an ISIN map from last month maps essentially every
    holding correctly, and refusing to map anything because the list could not
    be refreshed would be worse.
    """
    cached = _load_cached_map()
    fresh_enough = False
    if cached:
        try:
            age = (dt.datetime.now(dt.timezone.utc) -
                   dt.datetime.fromisoformat(cached["fetched_utc"])).days
            fresh_enough = age <= max_age_days
        except Exception:
            fresh_enough = False
    if cached and fresh_enough and not refresh:
        return cached["map"], {"stale": False, "rows": len(cached["map"]),
                               "fetched_utc": cached.get("fetched_utc")}

    text = None
    if nse_http is not None and nse_http.available():
        r = nse_http.get(NSE_EQUITY_LIST, referer=NSE_LIST_REFERER)
        if r is not None:
            text = r.text
    if not text:
        blob = _http(NSE_EQUITY_LIST)
        text = blob.decode("utf-8", "replace") if blob else None

    if not text or "ISIN" not in text[:400].upper():
        if cached:
            return cached["map"], {"stale": True, "rows": len(cached["map"]),
                                   "fetched_utc": cached.get("fetched_utc"),
                                   "note": "the equity list could not be refreshed"}
        return {}, {"stale": True, "rows": 0,
                    "note": "the NSE equity list could not be read"}

    out = {}
    lines = text.splitlines()
    head = [h.strip().strip('"').upper() for h in lines[0].split(",")]
    try:
        isin_col = next(i for i, h in enumerate(head) if "ISIN" in h)
        sym_col = next(i for i, h in enumerate(head) if h == "SYMBOL")
        series_col = next((i for i, h in enumerate(head) if h == "SERIES"), None)
    except StopIteration:
        return {}, {"stale": True, "rows": 0,
                    "note": "the equity list did not have the expected columns"}
    for line in lines[1:]:
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) <= max(isin_col, sym_col):
            continue
        if series_col is not None and len(parts) > series_col and \
                parts[series_col].upper() not in ("EQ", "BE"):
            continue
        code, sym = parts[isin_col].upper(), parts[sym_col].upper()
        if code and sym:
            out[code] = sym
    if out:
        try:
            os.makedirs(os.path.dirname(ISIN_CACHE) or ".", exist_ok=True)
            with open(ISIN_CACHE, "w") as fh:
                json.dump({"fetched_utc": dt.datetime.now(dt.timezone.utc)
                           .isoformat(timespec="seconds"), "map": out}, fh)
        except Exception:
            pass
    return out, {"stale": False, "rows": len(out)}


# ---------------------------------------------------------------------------
# Month ends
# ---------------------------------------------------------------------------

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
_MON = r"(?<![a-z])(%s)[a-z]*\.?" % "|".join(_MONTHS)


def month_end_from(text):
    """
    The month a pack describes, from its filename, link text or a header line.

    Reads 31-08-2026, 2026-08-31, 31.10.2026, 31Aug2026, 31st-october-2026,
    October 31, 2026, October_31_2026, August 2026, 31-Oct-26, Oct_26 and
    31102026, and returns the LAST day of that month — which is the date the
    portfolio is as at, whatever day the file happens to be named for.

    When a name carries more than one date the most specific one wins, and
    among those the last: HDFC's "Monthly HDFC Nifty G-Sec Dec 2026 Index
    Fund - 31 October 2026.xlsx" is October's portfolio of a fund named for
    December.
    """
    return date_parts(text)[0]


def date_parts(text):
    """(month end, day of month or None) — the day only when the text names
    one, which is what tells a month-end pack from a fortnightly one dated the
    15th or a daily file."""
    s = str(text or "")
    # A full numeric date that is impossible is refused outright rather than
    # read some other way: 31-13-2026 is a typo, not a hint.
    m = re.search(r"(20\d{2})[-_/.](\d{1,2})[-_/.](\d{1,2})", s)
    if m:
        return _month_end(int(m.group(1)), int(m.group(2))), int(m.group(3))
    m = re.search(r"(?<!\d)(\d{1,2})[-_/.](\d{1,2})[-_/.](20\d{2})", s)
    if m:
        return _month_end(int(m.group(3)), int(m.group(2))), int(m.group(1))

    found = []                          # (specificity, position, date, day)

    def add(spec, m, year, mon, day=None):
        d = _month_end(year, mon)
        if d:
            found.append((spec, m.start(), d, day))

    def mon(g):
        return _MONTHS.index(g[:3].lower()) + 1

    for m in re.finditer(_MON + r"[-_ ]*(\d{1,2})(?:st|nd|rd|th)?[-_ ]*,?[-_ ]*(20\d{2})",
                         s, re.I):              # October 31, 2026 / October_31_2026
        add(3, m, int(m.group(3)), mon(m.group(1)), int(m.group(2)))
    for m in re.finditer(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[-_ ]*" + _MON +
                         r"[-_ ,]*(20\d{2})", s, re.I):     # 31 October 2026
        add(3, m, int(m.group(3)), mon(m.group(2)), int(m.group(1)))
    for m in re.finditer(_MON + r"[-_ ,]*(20\d{2})", s, re.I):   # August 2026
        add(2, m, int(m.group(2)), mon(m.group(1)))
    if not found:
        # Two-digit years only when nothing better is there: Nippon India's
        # "NIMF-MONTHLY-PORTFOLIO-31-Oct-26.xls"...
        for m in re.finditer(r"(?<!\d)(\d{1,2})[-_ ]?" + _MON + r"[-_ ]?(\d{2})(?!\d)",
                             s, re.I):
            add(1, m, 2000 + int(m.group(3)), mon(m.group(2)), int(m.group(1)))
        # ...Aditya Birla Sun Life's "31102026_abslmf_monthlydisclosure.zip"...
        for m in re.finditer(r"(?<!\d)(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(20\d{2})(?!\d)", s):
            add(1, m, int(m.group(3)), int(m.group(2)), int(m.group(1)))
    if not found:
        # ...and, last of all, Old Bridge's "OBMF_Flexi_Cap_Portfolio_Oct_26".
        for m in re.finditer(_MON + r"[-_ ]?(\d{2})(?!\d)", s, re.I):
            add(0, m, 2000 + int(m.group(2)), mon(m.group(1)))
    if not found:
        return None, None
    found.sort(key=lambda f: f[:2])
    return found[-1][2], found[-1][3]


def _month_end(year, month):
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        return None
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


def recent_month_ends(today=None, n=2):
    """The last `n` month ends before `today`, newest first."""
    d = (today or dt.date.today()).replace(day=1)
    out = []
    for _ in range(n):
        d = d - dt.timedelta(days=1)
        out.append(d)
        d = d.replace(day=1)
    return out


def latest_possible_month(today=None):
    """No portfolio can be as at a month that has not ended."""
    return recent_month_ends(today, 1)[0].isoformat()


def oldest_current_month(today=None):
    """The oldest month still worth recording as a house's latest: three
    months before the one every house owes by now."""
    owed = dt.date.fromisoformat(expected_month(today))
    return recent_month_ends(owed + dt.timedelta(days=1), 4)[-1].isoformat()


def expected_month(today=None):
    """
    The newest month every AMC is obliged to have published by `today`.

    Disclosure is due within ten days of month end, so on 11 November this is
    October and on 5 November it is still September.
    """
    today = today or dt.date.today()
    last, before = recent_month_ends(today, 2)
    return (last if today.day > 10 else before).isoformat()


# ---------------------------------------------------------------------------
# Per-AMC sources
# ---------------------------------------------------------------------------
#
# What each of the largest houses actually serves, measured on 11 November
# 2026 against their live sites. Each source returns a list of month groups,
# newest first: {"as_of": "YYYY-MM-DD", "sources": [{"url": ...}, ...]}. A
# group is everything to read for one month, recorded as one pack.
#
#   SBI            the page builds its table from a POST; the response is plain
#                  HTML with an "All Schemes Monthly Portfolio" xlsx.
#   ICICI Pru      a single-page app behind a bot shield, and its API host
#                  resets connections; but the month's zip of 151 per-scheme
#                  workbooks sits at a fixed public path.
#   HDFC           the site's CDN refuses requests from cloud addresses (HTTP
#                  403, even for robots.txt); the per-scheme files on its file
#                  host do not, and are named by scheme and date.
#   Nippon India   plain HTML links — the generic reader works once it can
#                  read "31-Oct-26" and tell a monthly pack from a fortnightly.
#   UTI            an Angular app over a public JSON API returning the month's
#                  zip; the portfolio is one sheet holding every scheme.
#   Aditya Birla   the list comes from a public accordion API the page names
#                  in its HTML; the zip holds a legacy .xls, and its links
#                  point at an Azure CDN host that no longer resolves.
#   Kotak, Axis    not read — see GAPS.

SBI_SHEETS = "https://www.sbimf.com/ajaxcall/CMS/GetSchemePortfolioSheets"
SBI_PAGE = "https://www.sbimf.com/portfolios"
ICICI_ZIP = ("https://www.icicipruamc.com/blob/downloads/Files/"
             "Monthly%20Portfolio%20Disclosures/{y}/{mon}/"
             "Monthly-Portfolio-Disclosure-{month}-{y}.zip")
HDFC_FILE = "https://files.hdfcfund.com/s3fs-public/{folder}/{name}"
UTI_API = ("https://www.utimf.com/api/get-consolidate-portfolio-disclosure"
           "?year={y}&month={month}")
ABSL_BASE = "https://mutualfund.adityabirlacapital.com"
ABSL_MONTHLY_API = ("/postlogin/CustomApi/Resources/FactsheetAccordionById"
                    "?id=3ccab227-9de5-4494-b78d-2b4f7c0c054a"
                    "&ctype=%2Fsitecore%2Fcontent%2FRoot%2FBSL%2FLibrary%2FLists"
                    "%2FFAQ%2FCustomer%20Types%2FIndividual")

# HDFC publishes one workbook per scheme and its listing page is unreachable
# from a cloud address, so the files are asked for by name. These are the
# schemes that can hold listed equity — debt, liquid, gilt and fund-of-fund
# schemes are left out because nothing in them would be kept — each one
# confirmed to exist for October 2026 on 11 November. A scheme launched or
# renamed since is missed until it is added here; the result says how many
# were asked for and how many were found, so a shrinking count is visible.
HDFC_EQUITY_SCHEMES = (
    "HDFC Aggressive Hybrid Fund",
    "HDFC Arbitrage Fund",
    "HDFC Balanced Advantage Fund",
    "HDFC BSE 500 ETF",
    "HDFC BSE India Sector Leaders Index Fund",
    "HDFC BSE Sensex Index Fund",
    "HDFC Business Cycle Fund",
    "HDFC Conservative Hybrid Fund",
    "HDFC Consumption Fund",
    "HDFC Defence Fund",
    "HDFC Dividend Yield Fund",
    "HDFC ELSS - Tax Saver Fund",
    "HDFC Equity Savings Fund",
    "HDFC Flexi Cap Fund",
    "HDFC Focused Fund",
    "HDFC FTSE India Equity ETF",
    "HDFC Housing Opportunities Fund",
    "HDFC Infrastructure Fund",
    "HDFC Innovation Fund",
    "HDFC Large Cap Fund",
    "HDFC Long Term Fund",
    "HDFC Manufacturing Fund",
    "HDFC Mid Cap Fund",
    "HDFC MNC Fund",
    "HDFC Multi Asset Allocation Fund",
    "HDFC Multi Cap Fund",
    "HDFC NIFTY 100 Equal Weight Index Fund",
    "HDFC NIFTY 100 ETF",
    "HDFC NIFTY 100 Index Fund",
    "HDFC NIFTY 50 ETF",
    "HDFC Nifty 50 Index Fund",
    "HDFC Nifty Auto Index Fund",
    "HDFC NIFTY BANK ETF",
    "HDFC Nifty India Consumption Index Fund",
    "HDFC Nifty India Digital Index Fund",
    "HDFC NIFTY IT ETF",
    "HDFC Nifty LargeMidcap 250 Index Fund",
    "HDFC Nifty Metal ETF",
    "HDFC NIFTY NEXT 50 ETF",
    "HDFC NIFTY Next 50 Index Fund",
    "HDFC NIFTY Private Bank ETF",
    "HDFC NIFTY PSU BANK ETF",
    "HDFC NIFTY Top 20 Equal Weight Index Fund",
    "HDFC NIFTY100 Low Volatility 30 Index Fund",
    "HDFC Nifty100 Quality 30 Index Fund",
    "HDFC NIFTY200 MOMENTUM 30 ETF",
    "HDFC Pharma and Healthcare Fund",
    "HDFC Retirement Fund - Equity Plan",
    "HDFC Retirement Fund - Hybrid-Debt Plan",
    "HDFC Retirement Fund - Hybrid-Equity Plan",
    "HDFC Small Cap Fund",
    "HDFC Technology Fund",
    "HDFC Transportation and Logistics Fund",
    "HDFC Value Fund",
)


def _month_name(d):
    return MONTH_NAMES[d.month - 1]


def _page_groups(amc):
    """The generic reader: workbook links in the page's own HTML."""
    page = amc.get("monthly_url")
    if not page:
        return []
    return month_candidates(find_workbooks(page))


def _src_sbi(amc, today=None):
    out = []
    for me in recent_month_ends(today, 2):
        body = json.dumps({"FundId": "0", "PSYear": str(me.year),
                           "PSMonth": _month_name(me),
                           "PSFrequency": "Monthly"}).encode()
        blob = _http(SBI_SHEETS, timeout=60, data=body, headers={
            "Content-Type": "application/json;charset=utf-8",
            "X-Requested-With": "XMLHttpRequest", "Referer": SBI_PAGE})
        if not blob:
            continue
        links = find_workbooks(SBI_PAGE, html=blob.decode("utf-8", "replace"))
        for g in month_candidates(links):
            if g["as_of"] == me.isoformat():
                g["source"] = SBI_PAGE
                out.append(g)
                break
    return out


def _src_icici(amc, today=None):
    return [{"as_of": me.isoformat(), "sources": [{"url": ICICI_ZIP.format(
                y=me.year, mon=_month_name(me)[:3], month=_month_name(me))}]}
            for me in recent_month_ends(today, 2)]


def _src_hdfc(amc, today=None):
    # The listing page first, in case this instance's address is not one the
    # CDN refuses — then every scheme's file by name.
    groups = _page_groups(amc)
    if groups:
        return groups
    out = []
    for me in recent_month_ends(today, 2):
        nxt = me + dt.timedelta(days=1)
        stamp = "%d %s %d" % (me.day, _month_name(me), me.year)
        out.append({
            "as_of": me.isoformat(),
            "optional": True,            # a closed or renamed scheme is a miss, not a failure
            "source": amc.get("monthly_url"),
            "sources": [{"url": HDFC_FILE.format(
                            folder="%d-%02d" % (nxt.year, nxt.month),
                            name=quote("Monthly %s - %s.xlsx" % (n, stamp))),
                         "title": n} for n in HDFC_EQUITY_SCHEMES]})
    return out


def _src_uti(amc, today=None):
    out = []
    for me in recent_month_ends(today, 2):
        blob = _http(UTI_API.format(y=me.year, month=_month_name(me)),
                     headers={"Accept": "application/json"})
        try:
            rows = json.loads(blob)["rows"] if blob else []
        except Exception:
            rows = []
        srcs = [{"url": r.get("url") or r.get("doc"), "title": r.get("name"),
                 # The zip also carries futures exposure, a dividend master and
                 # a risk-o-meter; only the "Sebi Exposure" workbook is the
                 # portfolio.
                 "members": r"^(?!.*(?:fut|risk|div)).*(?:exposure|portfolio)"}
                for r in rows if (r.get("url") or r.get("doc"))]
        if srcs:
            out.append({"as_of": me.isoformat(), "sources": srcs})
    return out


def _absl_url(u):
    """Aditya Birla's links name abcscprod.azureedge.net, an Azure CDN host
    that no longer resolves; the same path is served from the main site."""
    p = urlparse(u or "")
    if p.hostname and p.hostname.endswith(".azureedge.net"):
        return ABSL_BASE + p.path + (("?" + p.query) if p.query else "")
    return u


def _src_absl(amc, today=None):
    api = ABSL_MONTHLY_API
    page = amc.get("monthly_url")
    blob = _http(page) if page else None
    if blob:
        # The page names its own API, one per accordion. Read the id from
        # there so a CMS re-publish that changes it does not silently break
        # this; fall back on the id measured in November 2026.
        html = blob.decode("utf-8", "replace")
        for m in re.finditer(r'data-accordian-api="([^"]+)"', html):
            start = html.find(">", m.end()) + 1          # past the rest of the tag
            label = re.sub(r"<[^>]+>", " ", html[start:start + 800])
            if re.match(r"\s*Monthly Portfolio\b", label, re.I):
                api = _html.unescape(m.group(1))
                break
    blob = _http(ABSL_BASE + api + "&month=%20&year=0",
                 headers={"Content-Type": "application/json",
                          "Accept": "application/json"})
    try:
        entries = (json.loads(blob).get("AccordionList") or []) if blob else []
    except Exception:
        entries = []
    out = []
    for e in entries[:3]:
        u = _absl_url(e.get("pdfUrl") or e.get("shareMedia"))
        if not u:
            continue
        title = e.get("ResourceLink") or ""
        out.append({"as_of": month_end_from(title) or month_end_from(_filename(u)),
                    "sources": [{"url": u, "title": title}]})
    return out


# Keyed by AMFI's mf_id, with the name as a fallback in case AMFI renumbers.
# Order is roughly assets under management, and it is the order the sweep
# tries them in: these eight are most of the industry's equity.
SOURCES = {
    "22": {"match": r"^SBI\b", "fetch": _src_sbi},
    "20": {"match": r"^ICICI Prudential", "fetch": _src_icici},
    "9": {"match": r"^HDFC\b", "fetch": _src_hdfc},
    "21": {"match": r"^Nippon India", "fetch": None},       # generic page works
    "17": {"match": r"^Kotak", "fetch": None},
    "53": {"match": r"^Axis\b", "fetch": None},
    "28": {"match": r"^UTI\b", "fetch": _src_uti},
    "3": {"match": r"^Aditya Birla", "fetch": _src_absl},
}

# Large houses this does not read, and why — said on the result instead of a
# generic "most likely JavaScript", which would send someone looking in the
# wrong place.
GAPS = {
    "17": ("Kotak serves its downloads page behind a ShieldSquare / hCaptcha "
           "bot challenge, and the file list comes from an API behind the "
           "same challenge. Not read."),
    "53": ("Axis lists its portfolios through a CMS API that requires a "
           "session token issued by the site, and its file paths carry random "
           "hashes, so they cannot be built from the month. Not read."),
}


def source_for(amc):
    """This AMC's entry in SOURCES, by AMFI id or by name."""
    spec = SOURCES.get(str(amc.get("amc_id") or ""))
    if spec and re.search(spec["match"], amc.get("name") or "", re.I):
        return spec
    for aid, spec in SOURCES.items():
        if re.search(spec["match"], amc.get("name") or "", re.I):
            return spec
    return None


def _gap_for(amc):
    spec = source_for(amc)
    if not spec:
        return None
    for aid, s in SOURCES.items():
        if s is spec:
            return GAPS.get(aid)
    return None


# ---------------------------------------------------------------------------
# Reading what was downloaded
# ---------------------------------------------------------------------------

_BOOK_EXT = re.compile(r"\.(?:xlsx|xlsm|xls)$", re.I)
MAX_MEMBER = 80 * 1024 * 1024


def _stem(name):
    base = unquote(str(name or "")).rsplit("/", 1)[-1].split("?")[0]
    return re.sub(r"\.[A-Za-z0-9]{2,4}$", "", base)


def _read_book(path, label=None):
    """One workbook -> [{"scheme", "holdings", "as_on"}], schemes named."""
    packs = fund_workbook.parse_workbook(path)
    names = {}
    try:
        names = fund_workbook.scheme_names(path)
    except Exception:
        pass
    clean = getattr(fund_workbook, "clean_scheme_name", lambda s: s)
    out = []
    for p in packs:
        scheme = (names.get(p["sheet"]) or p.get("title")
                  or (clean(label) if label and len(packs) == 1 else None)
                  or p["sheet"])
        out.append({"scheme": scheme, "holdings": p["holdings"],
                    "as_on": p.get("as_on")})
    return out


def _read_archive(path, members=None):
    """A zip of workbooks, read one member at a time through a temp file."""
    pat = re.compile(members, re.I) if members else None
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist()[:400]:
            name = info.filename.rsplit("/", 1)[-1]
            if info.is_dir() or not _BOOK_EXT.search(name):
                continue
            if pat and not pat.search(name):
                continue
            # A member that claims to be enormous, or is encrypted, is not a
            # portfolio — and reading it would be how a worker runs out of
            # memory on a malformed archive.
            if info.file_size > MAX_MEMBER or info.flag_bits & 0x1:
                continue
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".book", delete=False) as fh:
                    tmp = fh.name
                    with z.open(info) as src:
                        while True:
                            chunk = src.read(1 << 16)
                            if not chunk:
                                break
                            fh.write(chunk)
                out.extend(_read_book(tmp, label=_stem(name)))
            except Exception:
                continue            # one unreadable member is not the whole month
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
    return out


def _read_file(path, src):
    """Whatever one link served: a workbook (xlsx or legacy .xls) or a zip of
    them. Sniffed from the bytes — the extension is wrong often enough."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if fund_workbook.looks_like_xlsx(head):
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                is_book = "[Content_Types].xml" in z.namelist()
            if not is_book:
                return _read_archive(path, src.get("members"))
        return _read_book(path, label=src.get("title") or _stem(_filename(src["url"])))
    if getattr(fund_workbook, "looks_like_xls", lambda b: False)(head):
        return _read_book(path, label=src.get("title") or _stem(_filename(src["url"])))
    raise ValueError("not an xlsx workbook (nor the legacy .xls format) — "
                     "the link served something else")


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_month(amc_id, amc_name, group, mapping=None, keep_debt=False,
                 oldest=None):
    """
    Read one month's files for one AMC into the ledger, as one pack.

    A month is one file for most houses, a zip of 151 for ICICI Prudential and
    one file per scheme for HDFC — all recorded together, because the pack is
    per house and month and a second write for the same month would replace
    the first one's counts rather than add to them.
    """
    sources = [s for s in group.get("sources") or [] if s.get("url")]
    as_of = group.get("as_of")
    optional = bool(group.get("optional"))
    out = {"amc_id": amc_id, "url": sources[0]["url"] if sources else None,
           "ok": False, "rows": 0, "schemes": 0, "unmapped": 0,
           "as_of": as_of, "files": len(sources), "files_read": 0, "note": ""}
    if store is None or fund_workbook is None:
        out["note"] = "the workbook reader is not available"
        return out
    if not sources:
        out["note"] = "no file to read for this month"
        return out

    problems, read = [], []           # read: (month, [(scheme, rows)], label)
    missing = undated = not_portfolio = future = 0
    sheets = rows_seen = 0
    latest = latest_possible_month()
    for i, src in enumerate(sources):
        path, why = _download(src["url"])
        if not path:
            missing += 1
            problems.append("could not download %s (%s)" % (_stem(src["url"])[:70], why))
            # Built URLs for a month not yet published: three misses before
            # anything was found means the month is not there, and asking for
            # fifty more files that are not there either helps nobody.
            if optional and missing >= 3 and missing == i + 1:
                break
            continue
        try:
            packs = _read_file(path, src)
        except Exception as e:
            problems.append(("could not read the workbook: %s" % e)[:200])
            continue
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
        out["files_read"] += 1
        if not packs:
            # Opened fine and holds no table with an ISIN column: a scheme
            # summary, a branch list, a factsheet — not a portfolio.
            not_portfolio += 1
            continue

        month = as_of or month_end_from(src.get("title")) or month_end_from(_filename(src["url"]))
        if not month:
            # The filename carried no date — about one AMC in eight. Fall back
            # to the line inside the pack, which reads "Monthly Portfolio
            # Statement as on 31-Aug-2026" or some wording of it. Filing
            # August's portfolio under the wrong month would put one house's
            # positions beside another's from a different date and call the
            # difference a change, so the pack is refused rather than guessed
            # at when neither says.
            for p in packs[:6]:
                month = month_end_from(p.get("as_on"))
                if month:
                    break
        if not month:
            undated += 1
            continue
        if month > latest:
            future += 1
            continue
        kept = []
        for p in packs:
            sheets += 1
            rows_seen += len(p["holdings"])
            rows = p["holdings"]
            if not keep_debt:
                rows = [h for h in rows if h["isin"][7:9] == EQUITY_SEGMENT]
            if rows:
                kept.append((p["scheme"], rows))
        read.append((month, kept, _stem(src["url"])[:60]))

    if as_of is None and read:
        as_of = max(m for m, _k, _l in read)       # the newest month found
    shaped, seen_books = [], set()
    for month, kept, label in read:
        if month != as_of:
            problems.append("%s describes %s, not %s" % (label, month, as_of))
            continue
        for scheme, rows in kept:
            # The same book twice — a whole-house file listed beside the
            # per-scheme files it was assembled from — would put every
            # position in twice under two names, and the house view adds
            # positions up across schemes. Identical holdings are one scheme.
            book = frozenset((h["isin"], h.get("quantity")) for h in rows)
            if book in seen_books:
                continue
            seen_books.add(book)
            shaped.append({"scheme": scheme, "holdings": rows})

    out["as_of"] = as_of
    if not out["files_read"]:
        out["note"] = problems[0] if problems else "nothing could be downloaded"
        if missing == len(sources) and missing > 1:
            out["note"] = ("none of the %d files for %s could be downloaded "
                           "(first: %s)" % (len(sources), as_of, problems[0]))
        return out
    if not read and not_portfolio and not undated:
        out["note"] = ("read %d file%s but none is a portfolio — no table with "
                       "an ISIN column (a scheme summary, a list, a factsheet)"
                       % (not_portfolio, "" if not_portfolio == 1 else "s"))
        return out
    if not read and future:
        out["note"] = ("refused: the pack reads as a month that has not "
                       "ended — the date was taken from something that is not "
                       "the portfolio's")
        return out
    if not as_of or (undated and not shaped):
        out["note"] = ("could not tell which month this pack describes — "
                       "neither the filename nor the sheets carry a date")
        return out
    if as_of > latest:
        out["note"] = ("refused: the pack reads as %s, a month that has not "
                       "ended — the date was taken from something that is not "
                       "the portfolio's" % as_of)
        return out
    if oldest and as_of < oldest:
        # NJ's page lists packs back to 2021 among files with no date in the
        # name; the newest it could date was March 2024. Recorded, that would
        # sit in the ledger as this house's latest month.
        out["note"] = ("the newest portfolio found is for %s — too old to be "
                       "this house's current month; not recorded" % as_of)
        return out
    if not shaped:
        # A real outcome, not a failure to report: a debt-only house, or a
        # workbook that is a scheme factsheet rather than a portfolio. Saying
        # so beats an empty note that reads like a crash.
        out["note"] = ("the workbook was read but held no listed equity "
                       "(%d sheets, %d rows, all non-equity)" % (sheets, rows_seen))
        if problems:
            out["note"] += "; " + problems[0]
        return out

    if mapping is None:
        mapping, _meta = isin_map()
    res = store.record_fund_pack(amc_id, amc_name, as_of, shaped,
                                 source_url=group.get("source") or out["url"],
                                 symbol_for=lambda i: mapping.get(i))
    out.update({"ok": bool(res["seen"]), "rows": res["rows"],
                "schemes": res["schemes"], "unmapped": res["unmapped"]})
    if not res["seen"]:
        out["note"] = "the workbook parsed but produced no rows"
    elif len(sources) > 1 and out["files_read"] < len(sources):
        out["note"] = ("read %d of %d files for %s; %d not found"
                       % (out["files_read"], len(sources), as_of, missing))
    return out


def ingest_url(amc_id, amc_name, url, as_of=None, mapping=None, keep_debt=False):
    """
    Read one workbook — or one zip of them — into the ledger.

    Downloaded to a temporary file rather than held in memory: these packs run
    to fifteen megabytes, and the web instance this may run on has 512.
    """
    r = ingest_month(amc_id, amc_name, {"as_of": as_of, "sources": [{"url": url}]},
                     mapping=mapping, keep_debt=keep_debt)
    r["url"] = url
    return r


def _page_note(page):
    why = _LAST_ERROR.get(page)
    if why == "bot challenge":
        return ("the disclosure page served a bot challenge instead of its "
                "content, so its download list could not be read")
    if why and why.startswith("HTTP 403"):
        return ("the site refused the request (HTTP 403) — its CDN blocks "
                "this server's address, so the disclosure page could not be read")
    if why:
        return "the disclosure page could not be fetched (%s)" % why
    return ("no workbook link in the page's HTML — this AMC most likely builds "
            "its download list in JavaScript")


def ingest_amc(amc, mapping=None, today=None):
    """Find an AMC's newest monthly pack and read it."""
    out = {"amc_id": amc.get("amc_id"), "name": amc.get("name"),
           "ok": False, "rows": 0, "note": "", "via": None}
    spec = source_for(amc)
    gap = _gap_for(amc)
    groups, via = [], "page"
    if spec and spec.get("fetch"):
        try:
            groups = spec["fetch"](amc, today=today) or []
        except Exception as e:
            out["note"] = ("the per-AMC source failed: %s" % e)[:200]
        via = "per-AMC source"
    if not groups:
        page = amc.get("monthly_url")
        if not page:
            out["note"] = gap or "AMFI lists no monthly disclosure page for this AMC"
            return out
        links = find_workbooks(page)
        if not links:
            note = _page_note(page)
            out["note"] = ("%s. %s" % (note, gap)) if gap else note
            return out
        groups = month_candidates(links)
        via = "page"
        if not groups:
            out["note"] = ("the page links only to files that are not monthly "
                           "portfolios (fortnightly packs, risk parameters, "
                           "factsheets)")
            return out
    oldest = oldest_current_month(today)
    dated = [g for g in groups if g.get("as_of") is None or g["as_of"] >= oldest]
    if not dated:
        out["note"] = ("the newest monthly portfolio linked is for %s — too old "
                       "to be this house's current month" % groups[0]["as_of"])
        return out
    # The three newest months, then the undated files if those all failed.
    tries = [g for g in dated if g.get("as_of")][:3] + \
        [g for g in dated if not g.get("as_of")][:1]
    for g in tries:
        r = ingest_month(amc["amc_id"], amc.get("name"), g, mapping=mapping,
                         oldest=oldest)
        if r["ok"]:
            out.update(r)
            out["via"] = via
            return out
        out["note"] = r["note"]
        out["as_of"] = r.get("as_of")
    return out


def due_amcs(directory, want_month, retry_hours=20, now=None):
    """
    Which fund houses the sweep should try next, in order.

    Skips a house already read for `want_month`, and one tried within the last
    `retry_hours` — so one night's slices walk the whole directory once
    instead of retrying the same failures fourteen times. The largest houses
    (SOURCES) first, then never-tried, then longest since tried, and the
    houses known to be unreadable (GAPS) last.
    """
    tries = store.fund_tries() if store is not None else {}
    latest = store.fund_latest_by_amc() if store is not None else {}
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(hours=retry_hours)).isoformat(timespec="seconds")
    ranked = []
    for a in directory:
        aid = str(a.get("amc_id") or "")
        if not aid:
            continue
        spec = source_for(a)
        if not a.get("monthly_url") and not (spec and spec.get("fetch")):
            continue
        if (latest.get(aid) or "") >= want_month:
            continue
        t = tries.get(aid)
        if t and (t.get("last_try_utc") or "") > cutoff:
            continue
        # A house in GAPS is still tried — once a day costs one request, and
        # it is how this would notice the block lifting — but last.
        rank = 2 if _gap_for(a) else (0 if spec else 1)
        ranked.append((rank, (0 if t is None else 1),
                       (t or {}).get("last_try_utc") or "", a.get("name") or "", a))
    ranked.sort(key=lambda r: r[:4])
    return [r[4] for r in ranked]


def run(limit=6, amcs=None, mapping=None, progress=None, due_only=True, today=None):
    """
    A slice of the monthly sweep.

    Bounded the same way the shareholding crawl is, and for a blunter reason:
    each pack is a fifteen-megabyte download and a few seconds of parsing, and
    doing fifty-three in one request would exhaust both the memory and the
    patience of a 512 MB instance.

    Each slice continues the last: `due_amcs` reads what was already tried.
    Before it did, every slice took the first `limit` AMCs in the directory —
    alphabetically 360 ONE, Abakkus, Aditya Birla, AlphaGrep — so a nightly
    job of fourteen slices tried those four fourteen times and never reached
    the other fifty-one.
    """
    started = dt.datetime.now(dt.timezone.utc)
    want = expected_month(today)
    out = {"attempted": 0, "ok": 0, "rows": 0, "results": [], "note": "",
           "want_month": want, "remaining": 0}
    if store is None or fund_workbook is None:
        out["note"] = "the workbook reader is not available"
        return out
    directory = amcs if amcs is not None else amc_directory()
    if not directory:
        out["note"] = "the AMFI directory could not be read"
        return out
    out["listed"] = len(directory)
    if due_only:
        due = due_amcs(directory, want)
    else:
        due = [a for a in directory if a.get("monthly_url") or
               (source_for(a) or {}).get("fetch")]
    todo = due[: max(1, int(limit))]
    out["remaining"] = len(due) - len(todo)
    if not todo:
        out["note"] = ("nothing due — every reachable fund house has been read "
                       "for %s or was tried within the last day" % want)
        return out
    if mapping is None:
        mapping, meta = isin_map()
        out["isin_map"] = meta
    for i, amc in enumerate(todo):
        try:
            r = ingest_amc(amc, mapping=mapping, today=today)
        except Exception as e:                      # one house never stops the slice
            r = {"amc_id": amc.get("amc_id"), "name": amc.get("name"),
                 "ok": False, "rows": 0, "note": ("failed: %s" % e)[:200]}
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            out["rows"] += r["rows"]
        try:
            store.record_fund_try(amc.get("amc_id"), amc.get("name"), r["ok"],
                                  r.get("as_of"), r.get("note"))
        except Exception:
            pass
        if progress:
            try:
                progress(i + 1, len(todo), r)
            except Exception:
                pass
    out["seconds"] = round(
        (dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1)
    return out
