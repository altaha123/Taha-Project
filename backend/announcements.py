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
        r = requests.get(NSE_LIST, headers={"User-Agent": HEAD["User-Agent"],
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
        r = requests.get(BSE_SCRIPS, headers=HEAD, timeout=25)
        if r.status_code == 200:
            for row in (r.json() or []):
                if not isinstance(row, dict):
                    continue
                isin = str(row.get("ISIN_NUMBER") or row.get("ISIN") or "").strip().upper()
                code = str(row.get("SCRIP_CD") or row.get("Scrip_Code") or "").strip()
                if isin and code:
                    scrip_isin[code] = isin
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


def _norm(row):
    """One BSE announcement row -> our shape. Returns None when unusable."""
    if not isinstance(row, dict):
        return None
    code = row.get("SCRIP_CD") or row.get("SCRIPCD")
    head = (row.get("HEADLINE") or row.get("NEWSSUB") or "").strip()
    if not head:
        return None
    # BSE sometimes wraps the headline in HTML.
    head = re.sub(r"<[^>]+>", " ", head)
    head = re.sub(r"\s+", " ", head).strip()

    when = _parse_dt(row.get("NEWS_DT") or row.get("DT_TM") or row.get("News_submission_dt"))
    cat, imp, weight = classify(head + " " + str(row.get("CATEGORYNAME") or ""))
    att = (row.get("ATTACHMENTNAME") or "").strip()
    sym = symbol_for(code)

    return {
        "symbol": sym,
        "scrip_code": str(code or ""),
        "company": (row.get("SLONGNAME") or row.get("SHORTNAME") or "").strip(),
        "headline": head[:400],
        "exchange_category": (row.get("CATEGORYNAME") or "").strip(),
        "category": cat,
        "importance": imp,
        "weight": weight,
        "at": when.isoformat() if when else None,
        "epoch": when.timestamp() if when else 0,
        "pdf": (BSE_PDF + att) if att else None,
    }


def poll(days: int = None) -> dict:
    """
    Pull recent announcements. Safe to call on a timer; results are merged and
    de-duplicated, so overlapping windows cost nothing.
    """
    _build_maps()
    days = days or LOOKBACK_DAYS
    to_d = dt.datetime.now(IST).date()
    from_d = to_d - dt.timedelta(days=days)
    got, pages = [], 0

    try:
        for page in range(1, 4):        # 3 pages is ~150 filings, plenty per poll
            params = {
                "pageno": page, "strCat": "-1", "strPrevDate": from_d.strftime("%Y%m%d"),
                "strScrip": "", "strSearch": "P", "strToDate": to_d.strftime("%Y%m%d"),
                "strType": "C", "subcategory": "",
            }
            r = requests.get(BSE_ANN, headers=HEAD, params=params, timeout=25)
            if r.status_code != 200:
                _state["error"] = f"BSE announcements HTTP {r.status_code}"
                break
            payload = r.json() or {}
            rows = payload.get("Table") or payload.get("table") or []
            if not rows:
                break
            pages += 1
            for row in rows:
                item = _norm(row)
                if item:
                    got.append(item)
            time.sleep(0.4)
    except Exception as e:
        _state["error"] = f"BSE announcements: {str(e)[:140]}"

    if got:
        _state["error"] = None
        with _lock:
            seen = {(i["scrip_code"], i["headline"], i["at"]) for i in _state["items"]}
            fresh = [i for i in got
                     if (i["scrip_code"], i["headline"], i["at"]) not in seen]
            merged = fresh + _state["items"]
            merged.sort(key=lambda i: i["epoch"], reverse=True)
            _state["items"] = merged[:MAX_STORED]

            idx = {}
            for i in _state["items"]:
                if i["symbol"]:
                    idx.setdefault(i["symbol"], []).append(i)
            _state["by_symbol"] = idx
            _state["fetched"] = len(_state["items"])

    _state["last_poll"] = dt.datetime.now(IST).isoformat()
    _state["polls"] += 1
    return {"pages": pages, "new": len(got), "stored": len(_state["items"]),
            "error": _state["error"]}


def poll_if_stale(seconds: int = None):
    """Cheap guard so callers can poll on every scan pass without spamming BSE."""
    seconds = seconds or POLL_SECONDS
    last = _state["last_poll"]
    if last:
        try:
            age = (dt.datetime.now(IST) - dt.datetime.fromisoformat(last)).total_seconds()
            if age < seconds:
                return None
        except Exception:
            pass
    return poll()


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


def diagnose() -> dict:
    return {
        "isin_to_symbol_entries": len(_state["isin_to_symbol"]),
        "bse_scrip_entries": len(_state["scrip_to_isin"]),
        "maps_built_on": _state["maps_built"],
        "announcements_stored": len(_state["items"]),
        "mapped_to_nse_symbol": sum(1 for i in _state["items"] if i["symbol"]),
        "symbols_with_filings": len(_state["by_symbol"]),
        "polls_run": _state["polls"],
        "last_poll": _state["last_poll"],
        "error": _state["error"],
        "hint": ("If isin_to_symbol_entries is 0 the NSE list is unreachable from this "
                 "server; if bse_scrip_entries is 0 BSE is blocking the request. Filings "
                 "still show with company names but cannot be joined to your watchlist."),
    }
