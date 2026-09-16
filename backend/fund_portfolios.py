"""
fund_portfolios.py — what the fund houses hold, from their monthly disclosures

WHERE THIS DATA ACTUALLY LIVES
Not in one place. SEBI requires every asset manager to publish each scheme's
full portfolio monthly, within ten days of month end, and AMFI lists who must
do it — but AMFI aggregates nothing. Its portfolio-disclosure page carries one
link per AMC and all 53 point at 53 different websites. Measured across all of
them: 22 serve the workbook link in plain HTML, 10 build the list in
JavaScript, 19 hide it behind something else again, 2 did not answer.

So this reaches what it can reach, records which AMCs it got, and the coverage
is published rather than implied. A page that shows 22 fund houses while
looking like it shows the industry is the failure mode here.

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
import json
import os
import re
import tempfile

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


def _http(url, timeout=40):
    """A plain fetch with a browser user agent. AMC sites are ordinary web
    servers — it is NSE, not them, that needs an impersonated handshake."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


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


_WORKBOOK = re.compile(r'href="([^"]+\.(?:xlsx|xls))"', re.I)
_MONTHLY_HINT = re.compile(r"month|portfolio", re.I)


def find_workbooks(page_url):
    """
    Workbook links on an AMC's disclosure page, most likely first.

    Static HTML only. Roughly two fifths of AMCs build this list in JavaScript
    and return nothing here; that is a coverage gap, and it is reported as one
    rather than being silently treated as "this AMC published nothing".
    """
    blob = _http(page_url)
    if not blob:
        return []
    html = blob.decode("utf-8", "replace")
    seen, out = set(), []
    for href in _WORKBOOK.findall(html):
        url = href if href.startswith("http") else _absolute(page_url, href)
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


def month_end_from(text):
    """
    The month a pack describes, from its filename or a header line.

    Reads 31-08-2026, 2026-08-31, 31Aug2026 and August 2026, and returns the
    LAST day of that month — which is the date the portfolio is as at,
    whatever day the file happens to be named for.
    """
    s = str(text or "")
    m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", s)
    if m:
        return _month_end(int(m.group(1)), int(m.group(2)))
    m = re.search(r"(\d{1,2})[-_/](\d{1,2})[-_/](20\d{2})", s)
    if m:
        return _month_end(int(m.group(3)), int(m.group(2)))
    m = re.search(r"(%s)[a-z]*[-_ ,]*(20\d{2})" % "|".join(_MONTHS), s, re.I)
    if m:
        return _month_end(int(m.group(2)), _MONTHS.index(m.group(1)[:3].lower()) + 1)
    return None


def _month_end(year, month):
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        return None
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_url(amc_id, amc_name, url, as_of=None, mapping=None, keep_debt=False):
    """
    Read one workbook into the ledger.

    Downloaded to a temporary file rather than held in memory: these packs run
    to fifteen megabytes, and the web instance this may run on has 512.
    """
    out = {"amc_id": amc_id, "url": url, "ok": False, "rows": 0,
           "schemes": 0, "unmapped": 0, "as_of": as_of, "note": ""}
    if store is None or fund_workbook is None:
        out["note"] = "the workbook reader is not available"
        return out
    blob = _http(url, timeout=120)
    if not blob:
        out["note"] = "could not download the workbook"
        return out
    if not fund_workbook.looks_like_xlsx(blob):
        # AMCs serve .xlsx under an .xls name routinely; the reverse — a real
        # legacy .xls — this does not read, and says so rather than failing
        # with an opaque zip error.
        out["note"] = "not an xlsx workbook (the legacy .xls format is not read)"
        return out

    as_of = as_of or month_end_from(url)
    if mapping is None:
        mapping, _meta = isin_map()

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as fh:
            fh.write(blob)
            path = fh.name
        del blob
        names = {}
        try:
            names = fund_workbook.scheme_names(path)
        except Exception:
            pass
        packs = fund_workbook.parse_workbook(path)
    except Exception as e:
        out["note"] = ("could not read the workbook: %s" % e)[:160]
        return out
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass

    if not as_of:
        # The filename carried no date — about one AMC in eight. Fall back to
        # the line inside the pack, which reads "Monthly Portfolio Statement as
        # on 31-Aug-2026" or some wording of it. Filing August's portfolio
        # under the wrong month would put one house's positions beside
        # another's from a different date and call the difference a change, so
        # the pack is refused rather than guessed at when neither says.
        for pack in packs[:6]:
            as_of = month_end_from(pack.get("as_on"))
            if as_of:
                break
    if not as_of:
        out["note"] = ("could not tell which month this pack describes — "
                       "neither the filename nor the sheets carry a date")
        return out

    shaped = []
    for p in packs:
        rows = p["holdings"]
        if not keep_debt:
            rows = [h for h in rows if h["isin"][7:9] == EQUITY_SEGMENT]
        if not rows:
            continue
        shaped.append({"scheme": names.get(p["sheet"], p["sheet"]),
                       "holdings": rows})

    if not shaped:
        # A real outcome, not a failure to report: a debt-only house, or a
        # workbook that is a scheme factsheet rather than a portfolio. Saying
        # so beats an empty note that reads like a crash.
        out["note"] = ("the workbook was read but held no listed equity "
                       "(%d sheets, %d rows, all non-equity)"
                       % (len(packs), sum(len(p["holdings"]) for p in packs)))
        out["as_of"] = as_of
        return out

    res = store.record_fund_pack(amc_id, amc_name, as_of, shaped,
                                 source_url=url,
                                 symbol_for=lambda i: mapping.get(i))
    out.update({"ok": bool(res["seen"]), "rows": res["rows"],
                "schemes": res["schemes"], "unmapped": res["unmapped"],
                "as_of": as_of})
    if not res["seen"]:
        out["note"] = "the workbook parsed but produced no rows"
    return out


def ingest_amc(amc, mapping=None):
    """Find an AMC's newest monthly pack and read it."""
    out = {"amc_id": amc.get("amc_id"), "name": amc.get("name"),
           "ok": False, "rows": 0, "note": ""}
    page = amc.get("monthly_url")
    if not page:
        out["note"] = "AMFI lists no monthly disclosure page for this AMC"
        return out
    links = find_workbooks(page)
    if not links:
        out["note"] = ("no workbook link in the page's HTML — this AMC most "
                       "likely builds its download list in JavaScript")
        return out
    # Newest first where the filename carries a date.
    dated = [(month_end_from(u) or "", u) for u in links]
    dated.sort(reverse=True)
    for as_of, url in dated[:3]:
        r = ingest_url(amc["amc_id"], amc.get("name"), url,
                       as_of=as_of or None, mapping=mapping)
        if r["ok"]:
            out.update(r)
            return out
        out["note"] = r["note"]
    return out


def run(limit=6, amcs=None, mapping=None, progress=None):
    """
    A slice of the monthly sweep.

    Bounded the same way the shareholding crawl is, and for a blunter reason:
    each pack is a fifteen-megabyte download and a few seconds of parsing, and
    doing fifty-three in one request would exhaust both the memory and the
    patience of a 512 MB instance.
    """
    started = dt.datetime.now(dt.timezone.utc)
    out = {"attempted": 0, "ok": 0, "rows": 0, "results": [], "note": ""}
    if store is None or fund_workbook is None:
        out["note"] = "the workbook reader is not available"
        return out
    directory = amcs if amcs is not None else amc_directory()
    if not directory:
        out["note"] = "the AMFI directory could not be read"
        return out
    if mapping is None:
        mapping, meta = isin_map()
        out["isin_map"] = meta
    todo = [a for a in directory if a.get("monthly_url")][: max(1, int(limit))]
    for i, amc in enumerate(todo):
        r = ingest_amc(amc, mapping=mapping)
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            out["rows"] += r["rows"]
        if progress:
            try:
                progress(i + 1, len(todo), r)
            except Exception:
                pass
    out["seconds"] = round(
        (dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1)
    return out
