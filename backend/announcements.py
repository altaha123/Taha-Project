"""
Altaha Screener — Live Corporate Announcements

Where news actually starts. By the time a headline appears on a news site the
filing has been public for minutes; the exchange feed is the primary source and
it is free.

DESIGN DECISIONS WORTH KNOWING

  · BSE, not NSE. NSE's announcements endpoint needs a browser-like cookie
    handshake that fails often from a datacenter IP. BSE serves plain JSON.

  · Matched on ISIN, not company name. BSE keys announcements by its own scrip
    code; NSE keys everything by symbol. Fuzzy-matching "RELIANCE INDUSTRIES
    LTD" against "Reliance Industries Limited" is a bug generator. Both
    exchanges publish ISIN, so the join is exact.

  · Rule-based categories, not an LLM. Two reasons. It costs nothing, and an
    incorrect AI summary of a regulatory filing is worse than no summary — it
    invents confidence. This module reports the exchange's own headline and
    category, and adds a transparent keyword classification that can be read
    and argued with. It never paraphrases the filing.

  · Importance is a heuristic, and says so. It ranks what usually moves price:
    results, orders, fundraising, ratings, resignations. It is not a
    prediction, and the UI labels it as a sorting aid.

The high-value use is not the feed on its own — it is the JOIN. A stock trading
at four times normal volume with a filing eleven minutes old is a different
object from the same volume with no filing, and no retail tool in India puts
those two facts side by side.
"""

import datetime as dt
import os
import re
import threading
import time

import requests

BSE_ANN = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_SCRIPS = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
              "?Group=&Scripcode=&industry=&segment=Equity&status=Active")
BSE_PDF = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
NSE_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# BSE rejects requests without a browser-shaped Referer and Origin.
HEAD = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

# BSE's API sits behind a WAF that hands out cookies on the public site and
# then expects them on api.bseindia.com. The scrip-master endpoint tolerates a
# cold request; the announcements endpoint returns an empty JSON object — 200,
# no error, no data — which is precisely the symptom seen in production.
# Every request now goes through a session warmed on the public pages first.
_session = requests.Session()
_warm = {"at": 0.0}


def _warm_session(force=False):
    if not force and time.time() - _warm["at"] < 1800:
        return
    for url in ("https://www.bseindia.com/",
                "https://www.bseindia.com/corporates/ann.html"):
        try:
            _session.get(url, headers={"User-Agent": HEAD["User-Agent"],
                                       "Accept": "text/html,application/xhtml+xml"},
                         timeout=20)
        except Exception:
            pass
    _warm["at"] = time.time()


POLL_SECONDS = int(os.environ.get("ANN_POLL_SECONDS", "300") or 300)
MAX_STORED = int(os.environ.get("ANN_MAX_STORED", "1200") or 1200)
LOOKBACK_DAYS = int(os.environ.get("ANN_LOOKBACK_DAYS", "3") or 3)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

_lock = threading.Lock()
_state = {
    "items": [],            # newest first
    "by_symbol": {},        # SYMBOL -> [item, ...]
    "isin_to_symbol": {},
    "scrip_to_isin": {},
    "maps_built": None,
    "last_poll": None,
    "error": None,
    "polls": 0,
    "fetched": 0,
    "variant": None,
    "attempts": [],
}


# ---------------------------------------------------------------------------
# Classification — transparent keyword rules, no model
# ---------------------------------------------------------------------------

RULES = [
    # Order matters: the first match wins, so narrow and high-consequence rules
    # come before broad ones. "SEBI order" and "court order" would otherwise be
    # classified as an order WIN, which is close to the opposite of the truth.
    ("Regulatory action", 5, r"\b(penalt\w*|show cause|SEBI order|adjudicat\w*|prosecution|"
                             r"warning letter|USFDA|US ?FDA|import alert|Form 483|"
                             r"insolvency|NCLT|CIRP|freez\w* of|suspension of trading|"
                             r"search and seizure|income tax (raid|survey|search))\b"),
    ("Results", 5, r"\b(financial results?|quarterly results?|un-?audited results?|"
                   r"audited results?|earnings release|standalone and consolidated results?)\b"),
    ("M&A", 5, r"\b(acquisition|acquir\w*|merger|amalgamation|scheme of arrangement|"
               r"divest\w*|stake sale|slump sale|open offer)\b"),
    ("Buyback", 5, r"\bbuy-?back\b"),
    ("Order win", 5, r"\b(letter of (award|intent)|LoA|work order|purchase order|"
                     r"order (win|received|bagged)|receipt of order|bagged|"
                     r"awarded (a |the )?(contract|project|order)|new contract)\b"),
    ("Fundraise", 4, r"\b(fund ?rais\w*|preferential (issue|allotment)|QIP|rights issue|"
                     r"NCD|debenture|warrants|FCCB|raising of (funds|capital))\b"),
    ("Bonus / Split", 4, r"\b(bonus issue|stock split|sub-?division of (equity )?shares?)\b"),
    ("Credit rating", 4, r"\b(credit rating|rating (action|revision|upgrade|downgrade)|"
                         r"CRISIL|ICRA|CARE Ratings|India Ratings|Brickwork)\b"),
    ("Management change", 4, r"\b(resign\w*|cessation|appointment of|appointed as|"
                             r"managing director|chief (executive|financial|operating) officer|"
                             r"CFO|CEO|MD & CEO|company secretary|"
                             r"re-?designation|demise of)\b"),
    ("Pledge", 4, r"\b(pledge\w*|encumbrance|invocation|release of pledge)\b"),
    ("Dividend", 3, r"\bdividend\b"),
    ("Capacity / capex", 3, r"\b(commercial production|capacity expansion|new (plant|facility)|"
                            r"commission(ed|ing)|capex|greenfield|brownfield)\b"),
    ("Board meeting", 2, r"\bboard meeting\b"),
    ("Investor meet", 1, r"\b(investor (meet|conference|presentation|day)|analyst meet|"
                         r"earnings call|con-?call|schedule of analyst)\b"),
    ("Trading window", 0, r"\b(trading window|closure of trading window)\b"),
    ("Compliance", 0, r"\b(regulation 74|reconciliation of share capital|"
                      r"certificate under regulation|newspaper (publication|advertisement)|"
                      r"shareholding pattern|corporate governance report|"
                      r"related party transaction disclosure|loss of share certificate|"
                      r"duplicate share certificate|voting results|scrutinizer)\b"),
]

IMPORTANCE = {5: "critical", 4: "high", 3: "medium", 2: "low", 1: "low", 0: "routine"}


def classify(text: str):
    """(category, importance_label, weight). First matching rule wins."""
    t = text or ""
    for name, weight, pattern in RULES:
        if re.search(pattern, t, re.I):
            return name, IMPORTANCE[weight], weight
    return "Other", "low", 1


# ---------------------------------------------------------------------------
# Symbol mapping via ISIN
# ---------------------------------------------------------------------------

def _build_maps(force=False):
    """
    ISIN -> NSE symbol, and BSE scrip code -> ISIN.

    Both files are parsed line by line rather than with pandas. The BSE scrip
    list is ~5,000 rows and the NSE list ~2,000; loading either through a
    DataFrame is unnecessary memory pressure on a 512MB instance, and this
    service already crashed once from exactly that pattern.
    """
    today = dt.date.today().isoformat()
    if not force and _state["maps_built"] == today and _state["isin_to_symbol"]:
        return True

    isin_sym, scrip_isin = {}, {}

    try:
        r = _session.get(NSE_LIST, headers={"User-Agent": HEAD["User-Agent"],
                                            "Referer": "https://www.nseindia.com/"},
                         timeout=25)
        if r.status_code == 200 and "SYMBOL" in r.text[:200]:
            lines = r.text.splitlines()
            hdr = [c.strip().strip('"').upper() for c in lines[0].split(",")]
            try:
                i_sym = hdr.index("SYMBOL")
                i_isin = next(i for i, c in enumerate(hdr) if "ISIN" in c)
                i_ser = hdr.index("SERIES") if "SERIES" in hdr else None
            except (ValueError, StopIteration):
                i_sym = i_isin = None
            if i_sym is not None and i_isin is not None:
                for ln in lines[1:]:
                    parts = [p.strip().strip('"') for p in ln.split(",")]
                    if len(parts) <= max(i_sym, i_isin):
                        continue
                    if i_ser is not None and len(parts) > i_ser and parts[i_ser] != "EQ":
                        continue
                    isin, sym = parts[i_isin].upper(), parts[i_sym].upper()
                    if isin and sym:
                        isin_sym[isin] = sym
    except Exception as e:
        _state["error"] = f"NSE list: {str(e)[:120]}"

    try:
        _warm_session()
        r = _session.get(BSE_SCRIPS, headers=HEAD, timeout=25)
        if r.status_code == 200:
            for row in (r.json() or []):
                if not isinstance(row, dict):
                    continue
                isin = str(row.get("ISIN_NUMBER") or row.get("ISIN") or "").strip().upper()
                code = str(row.get("SCRIP_CD") or row.get("Scrip_Code") or "").strip()
                if isin and code:
                    scrip_isin[code] = isin
                name = (row.get("Scrip_Name") or row.get("Issuer_Name") or "").strip()
                if code and name:
                    _scrip_names[code] = name
    except Exception as e:
        _state["error"] = f"BSE scrip list: {str(e)[:120]}"

    if isin_sym or scrip_isin:
        with _lock:
            if isin_sym:
                _state["isin_to_symbol"] = isin_sym
            if scrip_isin:
                _state["scrip_to_isin"] = scrip_isin
            _state["maps_built"] = today
        return True
    return False


def symbol_for(scrip_code) -> str:
    isin = _state["scrip_to_isin"].get(str(scrip_code))
    if not isin:
        return ""
    return _state["isin_to_symbol"].get(isin, "")


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _parse_dt(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%d %b %Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(str(s)[:26], fmt).replace(tzinfo=IST)
        except Exception:
            continue
    return None


# scrip code -> clean company name, harvested from the scrip master we already
# fetch for the ISIN join. BSE's announcement rows do not reliably carry a
# company field; the name is buried in the subject line instead.
_scrip_names = {}


def _clean_headline(text, company=""):
    """
    NEWSSUB arrives as
        "Kilburn Engineering Ltd - 522101 - Announcement under Regulation 30..."
    The company and code are shown separately in the UI, so repeating them in
    the headline just wastes the line. Strip a leading "name - code - " prefix
    when one is present, and leave anything else untouched.
    """
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"^(.{2,90}?)\s*-\s*(\d{6})\s*-\s*(.+)$", t)
    if m:
        return m.group(3).strip(), m.group(1).strip()
    return t, company


def _norm(row):
    """One BSE announcement row -> our shape. Returns None when unusable."""
    if not isinstance(row, dict):
        return None
    code = row.get("SCRIP_CD") or row.get("SCRIPCD")
    raw = (row.get("NEWSSUB") or row.get("HEADLINE") or "").strip()
    if not raw:
        return None
    company = (row.get("SLONGNAME") or row.get("SHORTNAME") or "").strip()
    head, from_subject = _clean_headline(raw, company)
    company = company or _scrip_names.get(str(code or "")) or from_subject

    when = _parse_dt(row.get("NEWS_DT") or row.get("DT_TM") or row.get("News_submission_dt"))
    cat, imp, weight = classify(head + " " + str(row.get("CATEGORYNAME") or ""))
    att = (row.get("ATTACHMENTNAME") or row.get("AttachmentName") or "").strip()
    sym = symbol_for(code)

    return {
        "symbol": sym,
        "scrip_code": str(code or ""),
        "company": company,
        "headline": head[:400],
        "exchange_category": (row.get("CATEGORYNAME") or "").strip(),
        "category": cat,
        "importance": imp,
        "weight": weight,
        "at": when.isoformat() if when else None,
        "epoch": when.timestamp() if when else 0,
        "pdf": (BSE_PDF + att) if att else None,
    }


# ---------------------------------------------------------------------------
# Fetching
#
# BSE's announcements endpoint accepts a SINGLE DAY only. Ask for a range and
# it returns HTTP 200 with the body "{}" — no error, no rows, indistinguishable
# from a quiet day. That one behaviour cost several rounds of debugging: the
# scrip master worked, the session worked, the parameters looked right, and the
# feed stayed empty. Proven by probe: strPrevDate=strToDate=20260814 returned
# 50 rows and 56KB; the same request spanning three days returned two bytes.
#
# So: loop day by day, page within each day, and stop early on a quiet one.
# ---------------------------------------------------------------------------

BSE_ANN_ALT = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
PAGE_SIZE = 50                     # BSE's own page size
MAX_PAGES_PER_DAY = int(os.environ.get("ANN_MAX_PAGES", "4") or 4)


def _rows_from(payload):
    """BSE has used Table, table and Table1 — and returns a bare JSON string
    ("No Record Found!") from the older endpoint."""
    if isinstance(payload, str):
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for k in ("Table", "table", "Table1", "Data", "data"):
        v = payload.get(k)
        if isinstance(v, list) and v:
            return v
    return []


def _fetch_day(day, page):
    """One day, one page. Returns (rows, note)."""
    d = day.strftime("%Y%m%d")
    params = {"pageno": page, "strCat": "-1",
              "strPrevDate": d, "strToDate": d,      # same day, both ends
              "strScrip": "", "strSearch": "P", "strType": "C",
              "subcategory": "-1"}
    try:
        _warm_session()
        r = _session.get(BSE_ANN, headers=HEAD, params=params, timeout=25)
        if r.status_code != 200:
            return [], f"{d} p{page}: HTTP {r.status_code}"
        try:
            payload = r.json()
        except Exception:
            return [], f"{d} p{page}: non-JSON ({len(r.content)}B)"
        rows = _rows_from(payload)
        return rows, f"{d} p{page}: {len(rows)} rows"
    except Exception as e:
        return [], f"{d} p{page}: {type(e).__name__} {str(e)[:60]}"


def poll(days: int = None) -> dict:
    """
    Pull recent announcements, one day at a time. Safe to call on a timer;
    results are merged and de-duplicated, so overlapping windows cost nothing.
    """
    _build_maps()
    days = days or LOOKBACK_DAYS
    today = dt.datetime.now(IST).date()
    got, notes, fetched_days = [], [], 0

    for back in range(days):
        day = today - dt.timedelta(days=back)
        if day.weekday() >= 5 and back > 0:
            continue                       # exchanges are shut at weekends
        day_rows = 0
        for page in range(1, MAX_PAGES_PER_DAY + 1):
            rows, note = _fetch_day(day, page)
            if page == 1:
                notes.append(note)
            if not rows:
                break
            day_rows += len(rows)
            for row in rows:
                item = _norm(row)
                if item:
                    got.append(item)
            if len(rows) < PAGE_SIZE:
                break                      # last page for this day
            time.sleep(0.4)
        if day_rows:
            fetched_days += 1
        time.sleep(0.3)

    if got:
        _state["error"] = None
        _state["variant"] = "BSE single-day"
        with _lock:
            # De-duplicate against storage AND within this batch — pages overlap
            # when a filing lands mid-poll.
            seen = {(i["scrip_code"], i["headline"], i["at"]) for i in _state["items"]}
            fresh = []
            for i in got:
                k = (i["scrip_code"], i["headline"], i["at"])
                if k not in seen:
                    seen.add(k)
                    fresh.append(i)
            merged = fresh + _state["items"]
            merged.sort(key=lambda i: i["epoch"], reverse=True)
            _state["items"] = merged[:MAX_STORED]

            idx = {}
            for i in _state["items"]:
                if i["symbol"]:
                    idx.setdefault(i["symbol"], []).append(i)
            _state["by_symbol"] = idx
            _state["fetched"] = len(_state["items"])
    else:
        nse_rows, nse_note = _nse_rows()
        notes.append(nse_note)
        if nse_rows:
            got = nse_rows
            _state["variant"] = "NSE fallback"
            _state["error"] = None
            with _lock:
                seen = {(i["symbol"], i["headline"], i["at"]) for i in _state["items"]}
                fresh = []
                for i in got:
                    k = (i["symbol"], i["headline"], i["at"])
                    if k not in seen:
                        seen.add(k)
                        fresh.append(i)
                merged = fresh + _state["items"]
                merged.sort(key=lambda i: i["epoch"], reverse=True)
                _state["items"] = merged[:MAX_STORED]
                idx = {}
                for i in _state["items"]:
                    if i["symbol"]:
                        idx.setdefault(i["symbol"], []).append(i)
                _state["by_symbol"] = idx
                _state["fetched"] = len(_state["items"])

    _state["attempts"] = notes
    if not _state["items"]:
        _state["error"] = "No source returned rows. Attempts: " + " | ".join(notes[:8])

    _state["last_poll"] = dt.datetime.now(IST).isoformat()
    _state["polls"] += 1
    return {"days_with_rows": fetched_days, "new": len(got),
            "stored": len(_state["items"]), "variant": _state.get("variant"),
            "attempts": notes, "error": _state["error"]}


NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities"
_nse_warm = {"at": 0.0}


def _nse_rows():
    """
    Fallback source. NSE needs a browser-shaped session before its API answers,
    which is why BSE was chosen as primary — but a fallback that works only
    sometimes still beats a Filings tab that is permanently empty.

    NSE keys announcements by symbol directly, so no ISIN join is needed here.
    """
    try:
        if time.time() - _nse_warm["at"] > 900:
            _session.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements",
                         headers={"User-Agent": HEAD["User-Agent"],
                                  "Accept": "text/html,application/xhtml+xml",
                                  "Referer": "https://www.nseindia.com/"}, timeout=20)
            _nse_warm["at"] = time.time()
        r = _session.get(NSE_ANN, headers={"User-Agent": HEAD["User-Agent"],
                                           "Accept": "application/json",
                                           "Referer": "https://www.nseindia.com/companies-listing/"
                                                      "corporate-filings-announcements"},
                         timeout=25)
        if r.status_code != 200:
            return [], f"NSE: HTTP {r.status_code}"
        data = r.json()
        rows = data if isinstance(data, list) else _rows_from(data)
        if not rows:
            return [], "NSE: 200 but no rows"
        out = []
        for row in rows:
            head = (row.get("desc") or row.get("subject") or "").strip()
            sym = (row.get("symbol") or "").strip().upper()
            if not head or not sym:
                continue
            head = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", head)).strip()
            when = _parse_dt((row.get("an_dt") or row.get("sort_date") or "").replace(" ", "T"))
            cat, imp, weight = classify(head + " " + str(row.get("smIndustry") or ""))
            out.append({
                "symbol": sym, "scrip_code": "",
                "company": (row.get("sm_name") or sym).strip(),
                "headline": head[:400],
                "exchange_category": (row.get("attchmntText") or "")[:80],
                "category": cat, "importance": imp, "weight": weight,
                "at": when.isoformat() if when else None,
                "epoch": when.timestamp() if when else 0,
                "pdf": row.get("attchmntFile") or None,
            })
        return out, f"NSE: {len(out)} rows"
    except Exception as e:
        return [], f"NSE: {type(e).__name__} {str(e)[:80]}"


_polling = {"on": False}


def _poll_worker(days):
    try:
        poll(days=days)
    finally:
        _polling["on"] = False


def poll_if_stale(seconds: int = None, background: bool = True):
    """
    Kick off a refresh if the data is stale.

    Runs on a thread by default. A full pass builds the ISIN maps (a 1.7MB
    scrip master), then walks several days a page at a time with polite pauses
    between requests — comfortably half a minute on a cold start. Doing that
    inside the /announcements handler meant the browser sat on skeleton rows
    until the whole thing finished, which is exactly how it looked: permanently
    loading. The endpoint now answers instantly from memory and the refresh
    catches up behind it.
    """
    seconds = seconds or POLL_SECONDS
    last = _state["last_poll"]
    if last:
        try:
            age = (dt.datetime.now(IST) - dt.datetime.fromisoformat(last)).total_seconds()
            if age < seconds:
                return None
        except Exception:
            pass
    if not background:
        return poll()
    if _polling["on"]:
        return {"started": False, "reason": "a refresh is already running"}
    _polling["on"] = True
    threading.Thread(target=_poll_worker, args=(LOOKBACK_DAYS,),
                     daemon=True, name="altaha-filings").start()
    return {"started": True}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def feed(limit: int = 60, min_importance: str = "low", symbol: str = "",
         category: str = "") -> dict:
    order = ["routine", "low", "medium", "high", "critical"]
    floor = order.index(min_importance) if min_importance in order else 1

    rows = _state["by_symbol"].get(symbol.upper(), []) if symbol else _state["items"]
    out = [i for i in rows if order.index(i["importance"]) >= floor]
    if category:
        out = [i for i in out if i["category"].lower() == category.lower()]

    return {
        "rows": out[:max(1, min(limit, 200))],
        "count": len(out),
        "stored": len(_state["items"]),
        "mapped_to_nse": sum(1 for i in _state["items"] if i["symbol"]),
        "last_poll": _state["last_poll"],
        "refreshing": _polling["on"],
        "first_load": _state["last_poll"] is None,
        "error": _state["error"],
        "source": "BSE corporate announcements (primary exchange filing feed)",
        "note": ("Categories and importance are keyword rules applied to the exchange's own "
                 "headline — transparent, and wrong sometimes. Nothing here is a summary of "
                 "the filing; open the PDF for what the company actually said."),
    }


def recent_for(symbol: str, minutes: int = 120):
    """Filings for one symbol inside a time window. Used to tag live alerts."""
    rows = _state["by_symbol"].get((symbol or "").upper(), [])
    if not rows:
        return []
    cutoff = time.time() - minutes * 60
    return [i for i in rows if i["epoch"] and i["epoch"] >= cutoff]


def tag(symbol: str, minutes: int = 120):
    """One-line tag for a symbol, or None. The join that makes this worth having."""
    hits = recent_for(symbol, minutes)
    if not hits:
        return None
    top = max(hits, key=lambda i: i["weight"])
    mins = int((time.time() - top["epoch"]) / 60) if top["epoch"] else None
    return {
        "category": top["category"],
        "importance": top["importance"],
        "headline": top["headline"],
        "minutes_ago": mins,
        "pdf": top["pdf"],
        "count": len(hits),
        "line": (f"{top['category']} filed {mins} min ago"
                 if mins is not None and mins < 120
                 else f"{top['category']} filed recently"),
    }


def probe(days: int = 2) -> dict:
    """
    Fire a spread of candidate requests and report exactly what came back —
    status, byte count, content type and the first slice of raw text.

    Written after three rounds of guessing at parameters from the outside. A
    classifier that says "no rows" cannot distinguish a WAF challenge page from
    an empty result set; the raw bytes can. This is a diagnostic endpoint, not
    part of the polling path.
    """
    to_d = dt.datetime.now(IST).date()
    from_d = to_d - dt.timedelta(days=days)
    f, t = from_d.strftime("%Y%m%d"), to_d.strftime("%Y%m%d")
    base = {"pageno": 1, "strCat": "-1", "strPrevDate": f, "strToDate": t,
            "strScrip": "", "strSearch": "P", "strType": "C", "subcategory": "-1"}

    attempts = [
        ("warmed session, subcat=-1", BSE_ANN, dict(base), True, HEAD),
        ("cold, no session", BSE_ANN, dict(base), False, HEAD),
        ("warmed, no Origin header", BSE_ANN, dict(base), True,
         {k: v for k, v in HEAD.items() if k != "Origin"}),
        ("warmed, single day", BSE_ANN, dict(base, strPrevDate=t), True, HEAD),
        ("warmed, subcategory omitted", BSE_ANN,
         {k: v for k, v in base.items() if k != "subcategory"}, True, HEAD),
        ("AnnGetData warmed", BSE_ANN_ALT, dict(base), True, HEAD),
        ("scrip master (known good)", BSE_SCRIPS, None, True, HEAD),
    ]

    out = []
    for name, url, params, warm, hdrs in attempts:
        row = {"attempt": name}
        try:
            if warm:
                _warm_session()
                r = _session.get(url, headers=hdrs, params=params, timeout=25)
            else:
                r = requests.get(url, headers=hdrs, params=params, timeout=25)
            body = r.text or ""
            row.update({
                "status": r.status_code,
                "content_type": r.headers.get("Content-Type", "")[:60],
                "bytes": len(r.content or b""),
                "final_url": r.url[:220],
                "raw_head": body[:280].replace("\n", " ")[:280],
            })
            try:
                row["rows_found"] = len(_rows_from(r.json()))
            except Exception:
                row["rows_found"] = "not JSON"
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        out.append(row)

    return {"probed_at": dt.datetime.now(IST).isoformat(),
            "date_range": f"{f} to {t}",
            "session_cookies": sorted(_session.cookies.get_dict().keys())[:12],
            "attempts": out,
            "read_this": ("Look at raw_head. JSON starting with a bracket means the endpoint "
                          "works and the parameters are wrong. HTML, or a body mentioning a "
                          "challenge or access denial, means a WAF is refusing the request "
                          "and the fix is session or header related, not parameters.")}


def diagnose() -> dict:
    return {
        "isin_to_symbol_entries": len(_state["isin_to_symbol"]),
        "bse_scrip_entries": len(_state["scrip_to_isin"]),
        "maps_built_on": _state["maps_built"],
        "announcements_stored": len(_state["items"]),
        "mapped_to_nse_symbol": sum(1 for i in _state["items"] if i["symbol"]),
        "symbols_with_filings": len(_state["by_symbol"]),
        "polls_run": _state["polls"],
        "working_variant": _state.get("variant"),
        "last_attempts": _state.get("attempts"),
        "last_poll": _state["last_poll"],
        "error": _state["error"],
        "company_names_loaded": len(_scrip_names),
        "hint": ("If isin_to_symbol_entries is 0 the NSE list is unreachable from this "
                 "server; if bse_scrip_entries is 0 BSE is blocking the request. Filings "
                 "still show with company names but cannot be joined to your watchlist."),
    }
