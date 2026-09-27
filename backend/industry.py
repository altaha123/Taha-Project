"""
industry.py — which industry each company is in, from ONE classifier

WHY THIS EXISTS
Comparing a company with its peers needs an industry for every company, and
there are two places to get one. NSE's quote API carries the exchange's own
four-level classification, and the lens crawl reads it — but NSE refuses that
API from a datacenter address, so in production it has returned nothing for
any company. Yahoo Finance carries a sector and industry for almost every NSE
listing and can be read from anywhere; the Yahoo crawl stores it in
yf_profile.

WHY NEVER BOTH AT ONCE
The two name industries differently: NSE says "IT - Software", Yahoo says
"Information Technology Services". Classifying some companies by one and the
rest by the other would split a real industry into two half-groups, and every
median and rank computed over either half would be about a group that does not
exist. So one classifier is chosen for the whole market: NSE's where it covers
at least NSE_MIN_SHARE of the companies Yahoo covers, Yahoo's otherwise. The
choice is named in every payload that uses it.

The share counts and prices the lenses size companies by are different: a
company's issued shares are the same number whoever reports them, so Yahoo's
only fills in where NSE's is missing.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import threading
import time

try:
    import fundamentals_store
except Exception:                                   # pragma: no cover
    fundamentals_store = None
try:
    import lens_store
except Exception:                                   # pragma: no cover
    lens_store = None

NSE_MIN_SHARE = 0.8
CACHE_SECONDS = 900

NSE, YAHOO = "NSE", "Yahoo Finance"

_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _nse_profiles():
    if lens_store is None:
        return {}
    try:
        return lens_store.companies()
    except Exception:
        return {}


def _yahoo_profiles():
    if fundamentals_store is None:
        return {}
    try:
        return fundamentals_store.yf_profiles()
    except Exception:
        return {}


def choose(nse, yahoo):
    """
    (classifier, {symbol: industry}) from the two sources' profiles. Pure, so
    the rule is tested on its own.
    """
    by_nse = {s: p["industry"] for s, p in nse.items() if p.get("industry")}
    by_yahoo = {s: p["industry"] for s, p in yahoo.items() if p.get("industry")}
    if by_nse and len(by_nse) >= NSE_MIN_SHARE * len(by_yahoo):
        return NSE, by_nse
    if by_yahoo:
        return YAHOO, by_yahoo
    return None, {}


def classification(force=False):
    """(classifier, {symbol: industry}), cached for a quarter of an hour."""
    with _lock:
        if not force and _cache["value"] is not None and \
                time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["value"]
    value = choose(_nse_profiles(), _yahoo_profiles())
    with _lock:
        _cache.update(at=time.time(), value=value)
    return value


def members(symbol):
    """(classifier, industry, [every symbol in it]) for one company."""
    sym = (symbol or "").strip().upper()
    source, by = classification()
    ind = by.get(sym)
    if not ind:
        return source, None, []
    return source, ind, [s for s, i in by.items() if i == ind]


def merge(nse, yahoo):
    """
    Profiles for the lenses: NSE's row where there is one, with the industry
    replaced by the chosen classifier's, and Yahoo's company name, share count
    and price filling only what NSE left empty. Pure.
    """
    source, by = choose(nse, yahoo)
    out = {}
    for sym in set(nse) | set(yahoo):
        base = dict(nse.get(sym) or {"symbol": sym})
        y = yahoo.get(sym) or {}
        base["industry"] = by.get(sym)
        if source == YAHOO:
            # NSE's sub-levels belong to NSE's tree; beside a Yahoo industry
            # they would describe a different classification.
            base["macro"] = base["basic_industry"] = None
            base["sector"] = y.get("sector")
        for mine, theirs in (("company", "company"), ("issued_shares", "shares"),
                             ("last_price", "price")):
            if base.get(mine) in (None, "") and y.get(theirs) not in (None, ""):
                base[mine] = y[theirs]
        base["industry_source"] = source if base["industry"] else None
        out[sym] = base
    return out


def lens_profiles():
    return merge(_nse_profiles(), _yahoo_profiles())
