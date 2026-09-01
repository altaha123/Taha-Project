"""
Altaha Screener — retail attention, as a risk flag

THE INVERSION THAT MAKES THIS WORTH BUILDING
Social chatter is usually sold as a buy signal. For Indian small and mid caps
it is closer to the opposite. A sudden spike in retail mentions of an illiquid
name is, far more often than not, a pump in progress or the late stage of one
— the crowd arrives after the move, and the operator wants it to.

So this module does not produce alpha and does not feed the score. It produces
a WARNING: unusual attention, be careful, look at who is buying. That is the
form in which this data is actually reliable, and shipping it as a buy signal
would be shipping the part that does not work.

WHAT IS ACTUALLY AVAILABLE, WITHOUT PRETENDING
Reddit's free JSON endpoints answer 403 to datacenter IPs — they now require
OAuth. X's read API is paid. Neither is reachable from a server without
credentials, and a module that quietly returns nothing because it cannot
authenticate is worse than one that says so.

So the default source is the market itself, which is free, needs no keys, and
is arguably the better measure anyway: turnover against a stock's own history,
plus how much the exchange feed and the press have said about it this week.
Money moving is attention; a post is only a proxy for it.

Reddit and X plug in behind credentials when you have them. Each source is
independent — one being unavailable degrades the reading, never breaks it, and
the payload always names which sources actually answered.
"""

import datetime as dt
import math
import os

# Turnover this far above a stock's own median is unusual enough to say so.
# Log ratio: ln(3) is roughly 1.1, so a stock trading three times its normal
# value clears the first threshold.
ELEVATED = math.log(2.5)
EXTREME = math.log(5.0)

TIERS = ("normal", "elevated", "extreme")


def _env(*names):
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return None


def sources_available():
    """
    Which attention sources this deployment can actually read, and why not.

    Surfaced rather than hidden. A flag computed from one source of three is a
    weaker flag, and the reader is entitled to know which.
    """
    reddit = bool(_env("REDDIT_CLIENT_ID") and _env("REDDIT_CLIENT_SECRET"))
    x = bool(_env("X_BEARER_TOKEN", "TWITTER_BEARER_TOKEN"))
    return {
        "market": {"available": True,
                   "note": "Turnover against the stock's own history. Free, needs no keys."},
        "filings": {"available": True,
                    "note": "Exchange announcements already ingested by announcements.py."},
        "reddit": {"available": reddit,
                   "note": "Reads r/IndianStockMarket and similar." if reddit else
                           "Needs REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET. Reddit's "
                           "free JSON endpoints answer 403 to datacenter IPs, so a "
                           "free app registration at reddit.com/prefs/apps is required."},
        "x": {"available": x,
              "note": "Reads recent posts mentioning the symbol." if x else
                      "Needs X_BEARER_TOKEN. X's read API is a paid tier; this stays "
                      "off until one is configured rather than degrading silently."},
    }


def _tier(shock):
    if shock is None:
        return None
    if shock >= EXTREME:
        return "extreme"
    if shock >= ELEVATED:
        return "elevated"
    return "normal"


def market_attention(df):
    """
    Turnover over the last week against the stock's own six-month median.

    Log ratio, because turnover is lognormal — a raw ratio lets one frantic
    session dominate an entire universe, which is how an attention measure
    turns into a single-stock detector.
    """
    try:
        import factors
        shock = factors.volume_shock(df)
    except Exception:
        shock = None
    if shock is None:
        return {"available": False,
                "message": "Not enough turnover history to say what normal is."}
    shock = shock / 100.0                       # factors returns it scaled
    return {"available": True, "log_ratio": round(shock, 3),
            "times_normal": round(math.exp(shock), 2), "tier": _tier(shock)}


def assess(symbol, df=None, filings=None, stories=None, liquidity_tier=None):
    """
    One stock's attention reading, and what it should make a reader do.

    Never raises and never blocks a page: every input is optional and an
    absent one narrows the reading rather than failing it.
    """
    sym = str(symbol or "").upper()
    src = sources_available()
    market = market_attention(df) if df is not None else {"available": False}

    n_filings = len(filings or [])
    n_stories = len(stories or [])

    tier = market.get("tier") or "normal"
    reasons = []
    if market.get("available") and tier != "normal":
        reasons.append(f"Turnover is running {market['times_normal']}× its six-month normal.")
    if n_filings:
        reasons.append(f"{n_filings} exchange filing{'s' if n_filings != 1 else ''} this week.")
    if n_stories:
        reasons.append(f"{n_stories} press stor{'ies' if n_stories != 1 else 'y'} this week.")

    # The combination that actually matters. Heavy attention on a name that is
    # easy to move is the pattern behind most retail losses in this market —
    # the crowd is the exit liquidity, not the reason to enter.
    thin = liquidity_tier in ("thin", "untradeable")
    flag = None
    if tier == "extreme" and thin:
        flag = ("Extreme attention on a thinly traded stock. This is the shape a "
                "pump has. Whatever the story is, the people arriving now are the "
                "ones providing the exit.")
    elif tier == "extreme":
        flag = ("Turnover is far above this stock's own normal. Something has "
                "happened — find out what before reading the price move as a "
                "verdict on it.")
    elif tier == "elevated" and thin:
        flag = ("Raised attention on a thinly traded stock. Position size is the "
                "risk here, not the thesis.")
    elif tier == "elevated":
        flag = "Turnover is above normal. Worth knowing what has drawn people in."

    return {
        "symbol": sym,
        "tier": tier,
        "market": market,
        "filings_this_week": n_filings,
        "stories_this_week": n_stories,
        "reasons": reasons,
        "flag": flag,
        "sources": src,
        "social_configured": bool(src["reddit"]["available"] or src["x"]["available"]),
        "direction": "risk",
        "note": (
            "Attention is not a direction. A crowded stock is not a good one or a "
            "bad one — it is a stock where the price is being set by people who "
            "arrived recently. This never touches a score; it sits beside one."),
        "as_of": dt.date.today().isoformat(),
    }
