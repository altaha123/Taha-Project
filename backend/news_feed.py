"""
Altaha Screener — Market Press Feed

WHY THIS EXISTS, AND WHAT IT IS NOT
-----------------------------------
announcements.py reads the exchange feed: the filing itself, from the primary
source, in the company's own words. That is evidence.

This module reads the financial press: Moneycontrol, Economic Times, Business
Standard, Mint. That is *reporting about* evidence — written by a journalist,
after the fact, sometimes wrong, frequently a rewrite of the same filing the
other module already has, and occasionally a rewrite of a rumour.

Both are useful. They are not the same thing, and the whole credibility of
this product rests on never blurring them. So three rules are enforced here
rather than left to the caller:

  1  PRESS NEVER TOUCHES A SCORE. Nothing in this file feeds profiles.py,
     engine.py or the alert thresholds. Not now, not later. A headline is
     context for a human reading a screen; the moment it moves a number the
     tool stops being auditable.

  2  PRESS IS ALWAYS LABELLED AS PRESS. Every row carries its publication and
     is returned in a separate list from filings, never merged into one feed.
     The UI must render them apart.

  3  NO PARAPHRASE. The headline is passed through as published, with a link.
     This module never summarises a story, because a wrong summary of market
     news is worse than no summary — it invents confidence.

MATCHING
--------
Headlines are matched to companies by a curated alias table covering the
sector heavyweights, not by fuzzy-matching against the full 2,000-name NSE
list. Fuzzy matching produces "Bajaj" hitting three different companies and
"Vedanta" hitting a hospital chain, and a wrong attribution is worse than no
attribution. Unmatched headlines are still returned under their sector when a
sector keyword fires, and dropped otherwise.

DEPENDENCIES
------------
Standard library only. xml.etree parses RSS perfectly well and feedparser
would be another package on a 512 MB instance for no gain.
"""

import datetime as dt
import html as _html
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
      "Accept": "application/rss+xml, application/xml, text/xml, */*"}

# Each source is one RSS endpoint. Adding a source is a one-line change; the
# parser handles both RSS 2.0 and Atom shapes.
SOURCES = [
    {"name": "Moneycontrol",      "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
    {"name": "Moneycontrol",      "url": "https://www.moneycontrol.com/rss/results.xml"},
    {"name": "Economic Times",    "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"name": "Business Standard", "url": "https://www.business-standard.com/rss/markets-106.rss"},
    {"name": "Mint",              "url": "https://www.livemint.com/rss/markets"},
]

TTL = 900                  # 15 minutes. Press is not a latency game; filings are.
TIMEOUT = 12

_cache = {"rows": [], "at": 0, "errors": [], "lock": threading.Lock(),
          "refreshing": False}


# ---------------------------------------------------------------------------
# Company aliases
#
# Only the sector heavyweights. Deliberately narrow — see the module docstring
# on why fuzzy matching against the full NSE list is a bug generator.
# ---------------------------------------------------------------------------

ALIASES = {
    "TCS": ["tata consultancy", "tcs"],
    "INFY": ["infosys"], "HCLTECH": ["hcl tech", "hcltech"],
    "WIPRO": ["wipro"], "TECHM": ["tech mahindra"], "LTIM": ["ltimindtree"],
    "PERSISTENT": ["persistent systems"], "COFORGE": ["coforge"],
    "MPHASIS": ["mphasis"], "LTTS": ["l&t technology"],
    "HDFCBANK": ["hdfc bank"], "ICICIBANK": ["icici bank"],
    "SBIN": ["state bank of india", "sbi "], "KOTAKBANK": ["kotak mahindra bank", "kotak bank"],
    "AXISBANK": ["axis bank"], "INDUSINDBK": ["indusind"],
    "BAJFINANCE": ["bajaj finance"], "BAJAJFINSV": ["bajaj finserv"],
    "PNB": ["punjab national"], "BANKBARODA": ["bank of baroda"],
    "IDFCFIRSTB": ["idfc first"], "FEDERALBNK": ["federal bank"],
    "SUNPHARMA": ["sun pharma"], "CIPLA": ["cipla"], "DRREDDY": ["dr reddy", "dr. reddy"],
    "DIVISLAB": ["divi's", "divis lab"], "LUPIN": ["lupin"],
    "AUROPHARMA": ["aurobindo"], "TORNTPHARM": ["torrent pharma"],
    "ALKEM": ["alkem"], "ZYDUSLIFE": ["zydus"], "GLENMARK": ["glenmark"],
    "HINDUNILVR": ["hindustan unilever", "hul "], "ITC": ["itc "],
    "NESTLEIND": ["nestle india"], "BRITANNIA": ["britannia"],
    "DABUR": ["dabur"], "GODREJCP": ["godrej consumer"], "MARICO": ["marico"],
    "COLPAL": ["colgate"], "TATACONSUM": ["tata consumer"], "UBL": ["united breweries"],
    "MARUTI": ["maruti"], "M&M": ["mahindra & mahindra", "m&m"],
    "TATAMOTORS": ["tata motors"], "BAJAJ-AUTO": ["bajaj auto"],
    "EICHERMOT": ["eicher"], "HEROMOTOCO": ["hero motocorp"],
    "TVSMOTOR": ["tvs motor"], "ASHOKLEY": ["ashok leyland"],
    "BALKRISIND": ["balkrishna"], "MOTHERSON": ["samvardhana", "motherson"],
    "TATASTEEL": ["tata steel"], "JSWSTEEL": ["jsw steel"],
    "HINDALCO": ["hindalco"], "VEDL": ["vedanta"], "JINDALSTEL": ["jindal steel"],
    "SAIL": ["sail ", "steel authority"], "NATIONALUM": ["nalco", "national aluminium"],
    "HINDZINC": ["hindustan zinc"], "APLAPOLLO": ["apl apollo"], "NMDC": ["nmdc"],
    "RELIANCE": ["reliance industries", "ril "], "ONGC": ["ongc", "oil and natural gas"],
    "NTPC": ["ntpc"], "POWERGRID": ["power grid"], "COALINDIA": ["coal india"],
    "BPCL": ["bharat petroleum", "bpcl"], "IOC": ["indian oil"],
    "GAIL": ["gail"], "TATAPOWER": ["tata power"], "ADANIGREEN": ["adani green"],
    "TORNTPOWER": ["torrent power"], "JSWENERGY": ["jsw energy"],
    "NHPC": ["nhpc"], "SJVN": ["sjvn"],
    "LT": ["larsen & toubro", "larsen and toubro", "l&t "],
    "SIEMENS": ["siemens"], "ABB": ["abb india"], "BHEL": ["bhel"],
    "CUMMINSIND": ["cummins india"], "THERMAX": ["thermax"],
    "BEL": ["bharat electronics"], "HAL": ["hindustan aeronautics"],
    "GRINDWELL": ["grindwell"], "AIAENG": ["aia engineering"],
    "DLF": ["dlf"], "GODREJPROP": ["godrej properties"],
    "OBEROIRLTY": ["oberoi realty"], "PRESTIGE": ["prestige estates"],
    "PHOENIXLTD": ["phoenix mills"], "BRIGADE": ["brigade enterprises"],
    "SOBHA": ["sobha"], "MAHLIFE": ["mahindra lifespace"],
    "BHARTIARTL": ["bharti airtel", "airtel"], "IDEA": ["vodafone idea", "vi "],
    "ZEEL": ["zee entertainment"], "SUNTV": ["sun tv"],
    "PVRINOX": ["pvr inox"], "NAZARA": ["nazara"], "TV18BRDCST": ["tv18"],
}

# Sector keywords catch stories that are about the sector without naming a
# single company — "steel prices", "IT hiring", "bank credit growth".
SECTOR_WORDS = {
    "Technology": ["it sector", "it stocks", "it services", "software exports",
                   "nasscom", "it hiring", "nifty it"],
    "Financial Services": ["bank nifty", "banking stocks", "credit growth",
                           "rbi ", "repo rate", "npa", "nbfc", "lending"],
    "Healthcare": ["pharma stocks", "usfda", "drug approval", "nifty pharma", "api "],
    "Consumer Defensive": ["fmcg", "rural demand", "consumer staples"],
    "Consumer Cyclical": ["auto sales", "auto stocks", "vehicle sales",
                          "passenger vehicle", "two-wheeler", "nifty auto"],
    "Basic Materials": ["steel price", "metal stocks", "iron ore", "aluminium",
                        "commodity prices", "nifty metal", "china stimulus"],
    "Energy": ["crude", "brent", "opec", "oil prices", "gas price", "refining margin"],
    "Utilities": ["power demand", "electricity", "discom", "tariff order"],
    "Industrials": ["capex", "order inflow", "infrastructure spending",
                    "capital goods", "defence order"],
    "Real Estate": ["housing sales", "realty stocks", "property prices", "home loan"],
    "Communication Services": ["telecom", "arpu", "spectrum", "5g "],
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _text(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None and (found.text or "").strip():
            return _html.unescape(found.text.strip())
        # Atom puts the link in an attribute rather than the body
        if found is not None and found.get("href"):
            return found.get("href")
    return ""


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%a, %d %b %Y %H:%M:%S"):
        try:
            d = dt.datetime.strptime(s.strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _fetch_source(src):
    """One RSS endpoint -> list of normalised rows. Never raises."""
    try:
        r = requests.get(src["url"], headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return [], f"{src['name']}: HTTP {r.status_code}"
        root = ET.fromstring(r.content)
    except Exception as e:
        return [], f"{src['name']}: {str(e)[:70]}"

    items = root.findall(".//item")
    if not items:                                   # Atom
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    rows = []
    for it in items[:40]:
        title = _text(it, "title", "{http://www.w3.org/2005/Atom}title")
        if not title:
            continue
        link = _text(it, "link", "{http://www.w3.org/2005/Atom}link")
        when = _parse_date(_text(it, "pubDate", "published", "updated",
                                 "{http://purl.org/dc/elements/1.1/}date"))
        rows.append({
            "headline": title,
            "url": link,
            "source": src["name"],
            "when_iso": when.isoformat() if when else None,
            "age_minutes": (int((dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 60)
                            if when else None),
            "kind": "press",          # never "filing" — the distinction is load-bearing
        })
    return rows, None


def _match(row):
    """Attach symbols and sectors. A row that matches nothing is dropped."""
    text = " " + row["headline"].lower() + " "
    syms = [sym for sym, words in ALIASES.items()
            if any(w in text for w in words)]
    sectors = set()
    for sector, words in SECTOR_WORDS.items():
        if any(w in text for w in words):
            sectors.add(sector)
    # A company match implies its sector, resolved by the caller's constituent
    # map rather than duplicated here.
    row["symbols"] = syms
    row["sectors"] = sorted(sectors)
    return bool(syms or sectors)


def _refresh():
    rows, errors = [], []
    for src in SOURCES:
        got, err = _fetch_source(src)
        if err:
            errors.append(err)
        rows.extend(got)

    seen, deduped = set(), []
    for r in rows:
        key = re.sub(r"[^a-z0-9]+", "", r["headline"].lower())[:70]
        if key in seen:
            continue
        seen.add(key)
        if _match(r):
            deduped.append(r)

    deduped.sort(key=lambda r: r["when_iso"] or "", reverse=True)
    with _cache["lock"]:
        _cache.update({"rows": deduped, "at": time.time(), "errors": errors})
    return deduped


def _refresh_worker():
    try:
        _refresh()
    finally:
        _cache["refreshing"] = False


def poll_if_stale(background: bool = True):
    """Refresh at most once per TTL. Non-blocking by default."""
    if time.time() - _cache["at"] < TTL:
        return
    if _cache["refreshing"]:
        return
    _cache["refreshing"] = True
    if background:
        threading.Thread(target=_refresh_worker, daemon=True,
                         name="altaha-press").start()
    else:
        _refresh_worker()


def feed(limit: int = 40, symbols=None, sector: str = "", max_age_hours: int = 48):
    """
    Press rows, newest first, optionally filtered to a set of symbols or a
    sector. Always returns the `kind: "press"` label on every row.
    """
    poll_if_stale()
    want = {s.upper() for s in (symbols or [])}
    out = []
    for r in _cache["rows"]:
        if r.get("age_minutes") is not None and r["age_minutes"] > max_age_hours * 60:
            continue
        if want and not (want & set(r.get("symbols") or [])):
            if not (sector and sector in (r.get("sectors") or [])):
                continue
        elif sector and not want:
            if sector not in (r.get("sectors") or []) and not r.get("symbols"):
                continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def status() -> dict:
    return {
        "sources": [s["name"] for s in SOURCES],
        "cached_rows": len(_cache["rows"]),
        "age_seconds": int(time.time() - _cache["at"]) if _cache["at"] else None,
        "errors": _cache["errors"],
        "ttl_seconds": TTL,
        "note": ("Press coverage, kept separate from exchange filings on purpose. "
                 "Nothing in this feed influences any score or alert threshold."),
    }
