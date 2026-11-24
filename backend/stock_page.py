"""
Altaha Screener — what the stock page needs that no other endpoint was shaped for

    peer_table()   the company beside the named companies in its industry
    domain_for()   where a company's logo can be asked for

WHY A NAMED TABLE AS WELL AS THE MEDIANS
/fundamentals/peers answers "is 14% a good return on equity for a bank" with a
median and a rank. That is the right answer to that question and the wrong one
to the question a reader asks next, which is "against whom". A median has no
names in it. This puts the names beside the company: the dozen nearest to it
in market value in the same industry, every figure worked out the same way for
each of them.

ONE SOURCE, SO THE COLUMNS COMPARE
Every row is built from the same two places: the stored filings (the trailing
year, the latest quarter, the latest balance sheet) and the stored profile
(shares and a price). The company's own row is built that way too, not from
the live figures in the page header, because a P/E from one provider beside
eleven from another is not a comparison. The header's P/E and this table's can
therefore differ by a day's price move, and the table says what date its
prices are from.

WHAT IS LEFT BLANK
A P/E against a loss, a price-to-book against negative equity, a trailing year
with a quarter missing. None of them is a number; each is None and the page
prints a dash.

LOGOS
A company's mark is its own. The page asks for it by symbol first, from the
image host the portfolio uses, which has one for nearly every listed company.
What this module adds is the second place to ask: the company's own website,
through a favicon service the browser calls, for the few the first has none
of and for a listing outside India. The site comes from the stored profile; a
short curated table covers the names people open most until the profile crawl
has reached them. Nothing here fetches an image. With no mark from either the
page draws the company's initials, which is also what it draws while an image
is on its way.
"""

import datetime as dt
import re

try:
    import fundamentals as F
except Exception:                                    # pragma: no cover
    F = None

try:
    import fundamentals_store as store
except Exception:                                    # pragma: no cover
    store = None

try:
    import score_bands
except Exception:                                    # pragma: no cover
    score_bands = None

# A dozen is what fits on a laptop without scrolling the table, and enough to
# show the company's neighbours on both sides.
PEER_LIMIT = 12

# Fewer named peers than this and it is a list of two or three companies, not
# a comparison. The page says so instead.
PEER_NAMED_MIN = 3

CRORE = 1e7

# The columns a median is drawn under, in table order.
MEASURES = [
    # key, label, unit, higher is better (None: neither)
    ("market_cap_cr",   "Market cap",     "cr",  None),
    ("pe",              "P/E",            "x",   False),
    ("pb",              "P/B",            "x",   False),
    ("roe_pct",         "ROE",            "%",   True),
    ("opm_pct",         "Operating margin", "%", True),
    ("revenue_yoy_pct", "Sales growth",   "%",   True),
    ("pat_yoy_pct",     "Profit growth",  "%",   True),
    ("debt_equity_x",   "Debt / equity",  "x",   False),
]


def _base(symbol):
    return re.sub(r"\.(NS|BO)$", "", str(symbol or "").strip().upper())


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    n = len(vals)
    if not n:
        return None
    mid = n // 2
    return round(vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0, 2)


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

# The companies people open most, so their pages carry a mark before the
# profile crawl has stored a website for them. Each is the company's own
# domain. A stored website always wins over this table.
KNOWN_DOMAINS = {
    "RELIANCE": "ril.com", "TCS": "tcs.com", "HDFCBANK": "hdfcbank.com",
    "ICICIBANK": "icicibank.com", "INFY": "infosys.com", "SBIN": "sbi.co.in",
    "BHARTIARTL": "airtel.in", "ITC": "itcportal.com", "LT": "larsentoubro.com",
    "AXISBANK": "axisbank.com", "KOTAKBANK": "kotak.com", "HINDUNILVR": "hul.co.in",
    "MARUTI": "marutisuzuki.com", "TATAMOTORS": "tatamotors.com",
    "TATASTEEL": "tatasteel.com", "WIPRO": "wipro.com", "HCLTECH": "hcltech.com",
    "TECHM": "techmahindra.com", "SUNPHARMA": "sunpharma.com",
    "DRREDDY": "drreddys.com", "CIPLA": "cipla.com", "ONGC": "ongcindia.com",
    "NTPC": "ntpc.co.in", "POWERGRID": "powergrid.in", "COALINDIA": "coalindia.in",
    "BPCL": "bharatpetroleum.in", "IOC": "iocl.com", "JSWSTEEL": "jsw.in",
    "HINDALCO": "hindalco.com", "ULTRACEMCO": "ultratechcement.com",
    "GRASIM": "grasim.com", "ASIANPAINT": "asianpaints.com", "NESTLEIND": "nestle.in",
    "BAJFINANCE": "bajajfinserv.in", "BAJAJFINSV": "bajajfinserv.in",
    "BAJAJ-AUTO": "bajajauto.com", "HEROMOTOCO": "heromotocorp.com",
    "EICHERMOT": "eichermotors.com", "M&M": "mahindra.com", "TITAN": "titancompany.in",
    "ADANIENT": "adanienterprises.com", "ADANIPORTS": "adaniports.com",
    "LICI": "licindia.in", "BANKBARODA": "bankofbaroda.in", "PNB": "pnbindia.in",
    "CANBK": "canarabank.com", "UNIONBANK": "unionbankofindia.co.in",
    "INDUSINDBK": "indusind.com", "IDFCFIRSTB": "idfcfirstbank.com",
    "FEDERALBNK": "federalbank.co.in", "YESBANK": "yesbank.in",
    "BANKINDIA": "bankofindia.co.in", "DMART": "dmartindia.com", "PAYTM": "paytm.com",
    "NYKAA": "nykaa.com", "IRCTC": "irctc.co.in", "HAL": "hal-india.co.in",
    "BEL": "bel-india.in", "BHEL": "bhel.com", "SAIL": "sail.co.in",
    "VEDL": "vedantalimited.com", "DLF": "dlf.in", "INDIGO": "goindigo.in",
    "PIDILITIND": "pidilite.com", "DABUR": "dabur.com", "BRITANNIA": "britannia.co.in",
    "MARICO": "marico.com", "GODREJCP": "godrejcp.com", "TATACONSUM": "tataconsumer.com",
    "TATAPOWER": "tatapower.com", "LTIM": "ltimindtree.com", "DIVISLAB": "divislabs.com",
    "LUPIN": "lupin.com", "APOLLOHOSP": "apollohospitals.com", "HDFCLIFE": "hdfclife.com",
    "SBILIFE": "sbilife.co.in", "ICICIPRULI": "iciciprulife.com",
    "ICICIGI": "icicilombard.com", "SHRIRAMFIN": "shriramfinance.in",
    "CHOLAFIN": "cholamandalam.com", "TVSMOTOR": "tvsmotor.com",
    "ASHOKLEY": "ashokleyland.com", "UBL": "unitedbreweries.com",
    "TRENT": "trentlimited.com", "HAVELLS": "havells.com",
    "AMBUJACEM": "ambujacement.com", "ACC": "acclimited.com",
    "SHREECEM": "shreecement.com", "GAIL": "gailonline.com",
    "HINDPETRO": "hindustanpetroleum.com", "SUZLON": "suzlon.com",
    "IRFC": "irfc.co.in", "PFC": "pfcindia.com", "NHPC": "nhpcindia.com",
    "MUTHOOTFIN": "muthootfinance.com", "PERSISTENT": "persistent.com",
    "COFORGE": "coforge.com", "MPHASIS": "mphasis.com", "POLYCAB": "polycab.com",
    "VBL": "varunbeverages.com", "TORNTPHARM": "torrentpharma.com",
    "ZYDUSLIFE": "zyduslife.com", "AUROPHARMA": "aurobindo.com", "BIOCON": "biocon.com",
    "MOTHERSON": "motherson.com", "MRF": "mrftyres.com", "NAUKRI": "infoedge.in",
    "HINDZINC": "hzlindia.com", "NMDC": "nmdc.co.in", "COLPAL": "colgatepalmolive.co.in",
}

# A hostname and nothing else: letters, digits, dots and hyphens, with a dot
# in it. The value ends up inside a URL the browser requests.
_HOST = re.compile(r"^(?=.{4,100}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def domain_of(website):
    """'https://www.sbi.co.in/web/home' -> 'sbi.co.in'. None for anything that
    is not plainly a hostname."""
    host = str(website or "").strip().lower()
    if not host:
        return None
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host)
    host = re.split(r"[/?#\s]", host, maxsplit=1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    host = re.sub(r"^www\d?\.", "", host)
    return host if _HOST.match(host) else None


def domain_for(symbol, website=None):
    """The domain to ask for a company's logo when the symbol's own host has
    none: its stored or published website, else the curated table, else
    None."""
    return domain_of(website) or KNOWN_DOMAINS.get(_base(symbol))


# ---------------------------------------------------------------------------
# The named peers
# ---------------------------------------------------------------------------

def _row(sym, profile, held, year, close, score):
    """One company's line. Everything from the store, worked out one way."""
    profile, held, year = profile or {}, held or {}, year or {}
    q, b = held.get("quarter") or {}, held.get("balance") or {}

    shares = _f(profile.get("shares"))
    price, price_date = _f(profile.get("price")), str(profile.get("updated_utc") or "")[:10]
    cap = _f(profile.get("market_cap"))
    # A close from the exchange's own daily file is newer than a profile read
    # up to a month ago, and with a share count it gives a market value as of
    # the same day.
    if close and close[0] and shares:
        price, price_date = close[0], close[1]
        cap = shares * price
    elif cap is None and shares and price:
        cap = shares * price
    cap_cr = round(cap / CRORE, 0) if cap else None

    pat, equity = _f(year.get("pat_cr")), _f(b.get("total_equity_cr"))
    values = F._peer_values(held) if (F is not None and held) else {}
    return {
        "symbol": sym,
        "company": profile.get("company") or (q.get("company") if q else None) or sym,
        "price": round(price, 2) if price else None,
        "price_date": price_date or None,
        "market_cap_cr": cap_cr,
        "pe": round(cap_cr / pat, 1) if cap_cr and pat and pat > 0 else None,
        "pb": round(cap_cr / equity, 2) if cap_cr and equity and equity > 0 else None,
        "roe_pct": values.get("roe_pct"),
        "opm_pct": values.get("opm_pct"),
        "revenue_yoy_pct": values.get("revenue_yoy_pct"),
        "pat_yoy_pct": values.get("pat_yoy_pct"),
        "debt_equity_x": values.get("debt_equity_x"),
        "quarter": q.get("label"),
        "basis": held.get("basis"),
        "score": round(score, 1) if score is not None else None,
        "band": score_bands.band(score) if (score_bands and score is not None) else None,
        "domain": domain_for(sym, profile.get("website")),
    }


def closes_from_panel(panel, symbols):
    """
    {symbol: (close, date)} from the exchange's daily panel, where the
    delivery store already has it in memory. Never loads it: reading a year of
    the whole market's prices to refresh a dozen market values is a poor trade
    on a small instance, and the stored profile's price is the fallback.
    """
    try:
        close = panel.get("close") if isinstance(panel, dict) else None
        if close is None or not len(close):
            return {}
        # A name that did not trade on the last session keeps its last close,
        # but only from the few sessions before it.
        tail = close.tail(5).ffill()
        last, day = tail.iloc[-1], str(tail.index[-1])[:10]
        out = {}
        for s in symbols or []:
            if s in last.index:
                v = _f(last[s])
                if v and v > 0:
                    out[s] = (v, day)
        return out
    except Exception:
        return {}


def _nearest(rows, me, limit):
    """`limit` companies around `me` in market value, largest first.

    The whole industry when it is small. Otherwise a window on the list sorted
    by size with the company inside it: an industry's five giants are not who
    a ₹900 crore company is measured against, and the top of the list is all a
    plain "largest twelve" would ever show for it.
    """
    sized = sorted((r for r in rows if r["market_cap_cr"]),
                   key=lambda r: (-r["market_cap_cr"], r["symbol"]))
    unsized = sorted((r for r in rows if not r["market_cap_cr"]), key=lambda r: r["symbol"])
    if len(sized) + len(unsized) <= limit:
        return sized + unsized
    if me is None or not me.get("market_cap_cr"):
        return (sized + unsized)[:limit]
    at = next(i for i, r in enumerate(sized) if r["symbol"] == me["symbol"])
    lo = max(0, min(at - limit // 2, len(sized) - limit))
    return sized[lo:lo + limit]


def peer_table(symbol, industry, members, classifier="NSE", scores=None,
               closes=None, today=None, limit=PEER_LIMIT):
    """
    The company and the named companies of its industry, side by side.

    `members` is every symbol the classifier puts in `industry`. `scores` is
    {symbol: Altaha Score} for the companies the last scan ranked; `closes` is
    {symbol: (close, date)} from the exchange's daily file where it is in
    memory. Both are optional and a company without one simply has a blank.
    """
    sym = _base(symbol)
    out = {"symbol": sym, "industry": industry, "classifier": classifier,
           "available": False, "rows": [], "medians": {}}
    if not industry:
        out["message"] = "The industry for %s is not held yet." % sym
        return out
    if store is None or F is None:
        out["message"] = "The stored statements are not available."
        return out

    today = today or dt.date.today()
    fresh = (today - dt.timedelta(days=F.STORE_FRESH_DAYS)).isoformat()
    names = sorted({_base(s) for s in (members or []) if s} | {sym})
    try:
        held = store.latest_for(names, fresh_after=fresh)
        years = store.trailing_year(names)
        profiles = store.profiles_for(names)
    except Exception:
        out["message"] = "The stored statements are not available."
        return out

    scores, closes = scores or {}, closes or {}
    rows = [_row(s, profiles.get(s), held.get(s), years.get(s), closes.get(s), scores.get(s))
            for s in names if s in profiles or s in held]
    me = next((r for r in rows if r["symbol"] == sym), None)
    others = [r for r in rows if r["symbol"] != sym]
    if len(others) < PEER_NAMED_MIN:
        out["message"] = ("Too few of %s's peers in %s have figures held to set "
                          "beside it." % (sym, industry))
        return out

    shown = _nearest(rows, me, limit + (1 if me else 0))
    if me is not None and me not in shown:
        shown.append(me)
    for r in shown:
        r["is_self"] = r["symbol"] == sym
    peers = [r for r in shown if not r["is_self"]]

    dates = sorted(r["price_date"] for r in shown if r.get("price_date"))
    out.update({
        "available": True,
        "rows": shown,
        "medians": {k: _median([r.get(k) for r in peers]) for k, _l, _u, _h in MEASURES},
        "measures": [{"key": k, "label": l, "unit": u, "higher_is_better": h}
                     for k, l, u, h in MEASURES],
        "peers_shown": len(peers),
        "industry_members": len([s for s in names if s != sym]),
        # Both ends, because the rows are not all priced on the same day: a
        # close from the exchange's file is yesterday's, a stored profile's
        # can be a month old. The page prints the range when they differ.
        "prices_as_of": dates[-1] if dates else None,
        "prices_oldest": dates[0] if dates else None,
        "selection": ("Every company %s classes in %s with figures held."
                      % (classifier, industry)
                      if len(others) <= limit else
                      "The %d companies nearest to it in market value, of the %d %s "
                      "classes in %s." % (len(peers), len(others), classifier, industry)),
        "note": ("P/E is market value over the last four quarters' profit; P/B is "
                 "market value over the latest balance sheet's equity. Each company "
                 "is on the basis it files."),
    })
    return out
