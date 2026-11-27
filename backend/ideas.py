"""
Altaha Screener — Idea Selection

WHAT THIS LAYER IS FOR
----------------------
The scanner answers "which stocks score well". That is not the same question as
"which stocks are worth putting on a list today", and the gap between the two is
where every complaint about this tab came from. A stock can be a textbook
momentum breakout and still be a bad idea this week because the index is under
its 50-day average, its sector is the worst-performing on the exchange, and it
filed a USFDA import alert on Tuesday. The engine could see none of that.

So this module is a selection and evidence layer over the scan payload. It adds
no new scanning cost — it reads feeds the rest of the app already maintains —
and it turns a fit ranking into an auditable case:

  1. SETUP FIT          how well the chart and the filings match the archetype
  2. ENGINE COMPOSITE   the underlying 0-100 score
  3. SECTOR OUTLOOK     where the stock's industry sits against the Nifty 50,
                        from real sector-index relative strength (sectors.py)
  4. MARKET REGIME      the index against its own 50- and 200-day averages
  5. CATALYST           exchange filings and press coverage inside the horizon,
                        with adverse filings marked adverse rather than counted
                        as "news"
  6. LIQUIDITY          what you would actually face getting in and out
  7. TRACK RECORD       what this archetype has actually delivered, measured by
                        the tracker, and only once enough ideas have closed

Every one of those becomes a line in the row's evidence ledger — inputs, weight,
points — in the same style as the screener's audit trail. Nothing is asserted
without the number behind it, and any layer whose feed is unavailable scores
neutral and says so instead of silently pretending it agreed.

WHAT IS DELIBERATELY DIFFERENT PER HORIZON
------------------------------------------
Short and medium term are not the same question with a different holding period,
so they are not scored with the same weights.

  · SHORT  weights regime and fresh catalysts heavily, because a breakout
           depends on the tape and decays in days. News older than about three
           days is not a catalyst for it.
  · MEDIUM weights the business, the sector trend and the archetype's measured
           record, and deliberately ignores two-day news noise. Its catalysts
           are results, orders and capacity — things that change the earnings
           base, not the week's sentiment.

WHAT IT STILL WILL NOT DO
-------------------------
Pad the list. Fewer rows than the limit is the honest answer when fewer names
qualify, and a conviction floor means a bad week returns a short list rather
than a full one built from the least-bad names available.
"""

import datetime as dt
import math
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

try:
    import dhan_source as dhan
except Exception:
    dhan = None

try:
    import tracker
except Exception:
    tracker = None

try:
    import announcements as ann
except Exception:
    ann = None

try:
    import sectors as sector_mom
except Exception:
    sector_mom = None

try:
    import market_news
except Exception:
    market_news = None

try:
    import news_feed
except Exception:
    news_feed = None

try:
    import archetypes as A
except Exception:
    A = None

try:
    import wow_orders
except Exception:
    wow_orders = None

try:
    import concalls
except Exception:
    concalls = None

try:
    from data_source import resolve as _resolve
except Exception:
    _resolve = None

try:
    import leaders
except Exception:
    leaders = None

# Money Flow (money_flow.py): each sector's FPI flow, rotation and breadth as
# one score. Read here for two things and nothing else. It is printed beside a
# pick as its sector's tailwind, and, only when IDEAS_MONEYFLOW_CAPS=on, it
# decides how many names a list may take from one sector. It moves no rank and
# no conviction: every weight in this file is what it was.
try:
    import money_flow
except Exception:
    money_flow = None

BENCHMARK = os.environ.get("INDEX_PROXY", "NIFTYBEES").strip().upper()

SECTOR_CAP = int(os.environ.get("IDEAS_SECTOR_CAP", "3") or 3)
STALE_DAYS = int(os.environ.get("IDEAS_STALE_DAYS", "3") or 3)

# An adverse filing at this importance or above removes the name from the list
# outright rather than costing it points. A live USFDA import alert or a SEBI
# adjudication order is not a breakout with a caveat — it is a different
# situation, and ranking it third with a red box under it still puts it on a
# list headed "ideas".
HARD_EXCLUDE_ADVERSE = {"critical", "high"}

# Rows scoring below this are not shown. The point of a conviction score is
# that it can say no; without a floor it only ever reorders the same list.
MIN_CONVICTION = float(os.environ.get("IDEAS_MIN_CONVICTION", "45") or 45)

HORIZONS = {
    "short": {
        "keys": ["momentum_breakout", "institutional_accumulation"],
        "label": "Short-term setups",
        "note": ("Setups whose premise plays out in weeks to a few months: strong trends with "
                 "volume behind them, and accumulation footprints that haven't fully moved yet. "
                 "These decay fastest, so re-scan often."),
        # Weights sum to 100. Regime and fresh catalysts matter most here.
        "weights": {"fit": 32, "composite": 10, "sector": 14, "regime": 12,
                    "catalyst": 17, "liquidity": 8, "record": 7},
        "news_hours": 72,            # older than this is not a short-term catalyst
        "stale_penalty_per_day": 3.0,
        "max_stale_penalty": 18.0,
        "catalyst_categories": None,  # everything counts
        "horizon_note": ("Scored for the next few weeks: the market regime and any filing in the "
                         "last three days carry real weight, because a breakout that has to fight "
                         "the index usually loses."),
    },
    "medium": {
        "keys": ["quality_at_discount", "turnaround"],
        "label": "Medium-term setups",
        "note": ("Setups whose premise needs quarters, not weeks: quality businesses in a "
                 "drawdown, and companies whose fundamentals are inflecting. Judged mainly on "
                 "filings, so re-check after each results season."),
        # The business and its industry matter; this week's tape does not.
        "weights": {"fit": 30, "composite": 18, "sector": 16, "regime": 4,
                    "catalyst": 12, "liquidity": 8, "record": 12},
        "news_hours": 24 * 21,       # a quarter's worth of structural news
        "stale_penalty_per_day": 0.6,
        "max_stale_penalty": 6.0,
        # Only filings that change the earnings base count over quarters.
        "catalyst_categories": {"Results", "Order win", "M&A", "Capacity / capex",
                                "Credit rating", "Buyback", "Fundraise",
                                "Regulatory action", "Pledge"},
        "horizon_note": ("Scored for the next few quarters: what the business earns and where its "
                         "industry is heading dominate, and a quiet news week counts against "
                         "nothing. Re-check after each results season."),
    },
}

# Archetypes that depend on trend continuation. These are the ones that fail
# disproportionately when the index itself is under its 50-day average.
TREND_DEPENDENT = {"momentum_breakout", "institutional_accumulation"}

# A filing is not automatically good news. Counting a penalty order as a
# "catalyst" was the single most misleading thing this tab could do.
FILING_DIRECTION = {
    "Order win": "supportive",
    "Buyback": "supportive",
    "Capacity / capex": "supportive",
    "Bonus / Split": "supportive",
    "Dividend": "supportive",
    "Regulatory action": "adverse",
    "Pledge": "adverse",
    # Genuinely ambiguous without reading the document. Flagged as an event,
    # never scored as support.
    "Results": "event",
    "M&A": "event",
    "Fundraise": "event",
    "Credit rating": "event",
    "Management change": "event",
    "Board meeting": "event",
}

_regime_cache = {"day": None, "value": None}
_sector_cache = {"at": None, "value": None}

# ---------------------------------------------------------------------------
# Feed deadlines
#
# Every overlay this module reads is optional by design — the `layers` block at
# the bottom of select() already scores a missing feed as neutral and says so
# in the notes. But "missing" was only ever tested by exception. A feed that
# raises was handled; a feed that HANGS was not, and it holds the whole request
# open behind it.
#
# That is what /ideas was doing. sector_outlook() bulk-downloads twelve index
# symbols and market_regime() pulls a year of index history; both are cached,
# but a process that has just been deployed has neither, and on half a CPU the
# first request after a restart pays for all of it in series. From the browser
# that is indistinguishable from an engine that is down — which is exactly what
# the page reported.
#
# So the deadline is explicit. A feed that answers in time is used; a feed that
# does not is treated as unavailable AND LEFT RUNNING, so the work it has
# already started fills the cache for the request a few seconds behind this
# one. Nothing is wasted and nothing is waited on twice.
IDEAS_FEED_DEADLINE = float(os.environ.get("IDEAS_FEED_DEADLINE", "6") or 6)

_feed_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="altaha-ideas-feed")
_feed_inflight = {}
_feed_lock = threading.Lock()


def _soft(label, fn, default, seconds=None):
    """
    fn(), or `default` if it has not answered within the deadline.

    Returns (value, ok). ok=False means the caller should treat the feed as
    unavailable — the same state an exception would have produced, which the
    scoring already knows how to handle.

    A call that overruns is not cancelled and not repeated: the next request
    for the same label joins the future already in flight rather than starting
    a second copy of a slow download.
    """
    with _feed_lock:
        fut = _feed_inflight.get(label)
        if fut is None or fut.done():
            fut = _feed_pool.submit(fn)
            _feed_inflight[label] = fut
    try:
        return fut.result(timeout=IDEAS_FEED_DEADLINE if seconds is None else seconds), True
    except FuturesTimeout:
        return default, False
    except Exception:
        return default, False


# ---------------------------------------------------------------------------
# Liquidity tiers — label, never delete
# ---------------------------------------------------------------------------

def liquidity_tier(turnover_cr):
    """
    Turnover in crores -> (tier, one-line consequence).

    The old pipeline deleted anything under ~2 crore. Deleting hides the
    engine's reach; labelling shows it and still warns. The warning matters:
    names trading under a crore a day are where operator-driven moves live, and
    surfacing them without a flag is how a credibility tool becomes a liability.
    """
    if turnover_cr is None:
        return "unknown", "Turnover unknown. Treat position size with caution."
    try:
        t = float(turnover_cr)
    except (TypeError, ValueError):
        return "unknown", "Turnover unknown. Treat position size with caution."
    if t >= 10:
        return "liquid", "Trades freely, so entry and exit costs are small."
    if t >= 2:
        return "moderate", "Reasonable depth, but large orders will move the price."
    if t >= 0.5:
        return "thin", "Thin. Expect slippage; a full exit may take several days."
    return "untradeable", ("Barely trades. Wide spreads and a real chance you cannot exit "
                           "at anything near the screen price.")


TIER_RANK = {"liquid": 0, "moderate": 1, "thin": 2, "untradeable": 3, "unknown": 2}
TIER_QUALITY = {"liquid": 1.0, "moderate": 0.72, "thin": 0.3,
                "untradeable": 0.05, "unknown": 0.4}


# ---------------------------------------------------------------------------
# Market regime
# ---------------------------------------------------------------------------

def _index_frame(days=260):
    """
    Daily bars for the index proxy, from whichever feed answers.

    BUGFIX: this used to require Dhan. Anyone running without a Dhan token —
    which is the default, and the state a token spends every night in — got
    regime=None for ever, so no idea was ever regime-checked and the warning
    the tab promised never appeared once. The daily feed answers the same
    question perfectly well for a 50-day average.
    """
    try:
        if dhan is not None and dhan.configured():
            df = dhan.daily_ohlcv(BENCHMARK, days=days)
            if df is not None and len(df) > 60:
                return df, "Dhan"
    except Exception:
        pass
    if _resolve is None:
        return None, None
    for sym in (BENCHMARK, "^NSEI"):
        try:
            _s, _t, hist = _resolve(sym)
            if hist is not None and len(hist) > 60:
                return hist, "daily feed"
        except Exception:
            continue
    return None, None


def market_regime():
    """
    {'ok', 'pct_vs_50dma', 'pct_vs_200dma', 'change_5d_pct', 'label', 'stance'}
    or None when neither feed can answer. One fetch a day, cached.
    """
    today = dt.date.today().isoformat()
    if _regime_cache["day"] == today and _regime_cache["value"] is not None:
        return _regime_cache["value"]
    out = None
    try:
        df, src = _index_frame()
        if df is not None:
            close = df["Close"].dropna()
            if len(close) > 60:
                last = float(close.iloc[-1])
                ma50 = float(close.rolling(50).mean().iloc[-1])
                pct = (last - ma50) / ma50 * 100 if ma50 else 0.0
                ma200 = None
                if len(close) >= 200:
                    m = float(close.rolling(200).mean().iloc[-1])
                    ma200 = (last - m) / m * 100 if m else None
                chg5 = None
                if len(close) > 6:
                    prev = float(close.iloc[-6])
                    chg5 = (last - prev) / prev * 100 if prev else None

                if pct >= 2:
                    stance = "Tailwind"
                    label = ("Index comfortably above its 50-day average: trend setups have "
                             "tailwind.")
                elif pct >= 0:
                    stance = "Mixed"
                    label = "Index just above its 50-day average: mixed, not yet hostile."
                elif pct >= -3:
                    stance = "Headwind"
                    label = ("Index below its 50-day average. Trend setups fail more often here, "
                             "so momentum ideas are shown with a warning.")
                else:
                    stance = "Hostile"
                    label = ("Index well below its 50-day average. Breakouts fail at a much higher "
                             "rate in this regime; short-term ideas are suppressed.")
                out = {
                    "ok": pct >= 0,
                    "stance": stance,
                    "pct_vs_50dma": round(pct, 2),
                    "pct_vs_200dma": round(ma200, 2) if ma200 is not None else None,
                    "change_5d_pct": round(chg5, 2) if chg5 is not None else None,
                    "label": label,
                    "benchmark": BENCHMARK,
                    "source": src,
                }
    except Exception:
        out = None
    _regime_cache["day"] = today
    _regime_cache["value"] = out
    return out


def _regime_quality(regime, setup_key):
    """0..1 for the regime component, plus the sentence explaining it."""
    if not regime:
        return 0.6, "Index trend unavailable, so this factor scored neutral rather than assumed."
    pct = regime.get("pct_vs_50dma")
    if setup_key not in TREND_DEPENDENT:
        # A quality business in a drawdown does not need the index's permission,
        # but a falling market still drags valuations, so it is not ignored.
        q = 0.75 if (pct or 0) >= 0 else 0.55
        return q, (f"Index {pct:+.1f}% vs its 50-day average. This setup's premise is the "
                   "business, not the tape, so the regime is weighted lightly.")
    if pct is None:
        return 0.6, "Index trend unavailable."
    if pct >= 2:
        return 1.0, f"Index {pct:+.1f}% above its 50-day average: trend continuation has tailwind."
    if pct >= 0:
        return 0.78, f"Index {pct:+.1f}% above its 50-day average: workable, not strong."
    if pct >= -3:
        return 0.42, f"Index {pct:+.1f}% below its 50-day average. Breakouts fail more often here."
    return 0.15, (f"Index {pct:+.1f}% below its 50-day average, the worst regime for this setup, "
                  "and scored as such.")


# ---------------------------------------------------------------------------
# Sector outlook
# ---------------------------------------------------------------------------

# How much a sector state is worth, per horizon. A sector that is behind the
# index but closing the gap is a better medium-term home than a short-term one.
SECTOR_QUALITY = {
    "short":  {"Leading": 1.0, "Weakening": 0.55, "Improving": 0.68, "Lagging": 0.25},
    "medium": {"Leading": 0.92, "Weakening": 0.5, "Improving": 0.85, "Lagging": 0.3},
}


def sector_tailwind(symbol):
    """The stock's sector on Money Flow, or None. Never raises: a feed that
    is missing is a row without the line, not a list that fails."""
    if money_flow is None:
        return None
    try:
        return money_flow.tailwind(symbol)
    except Exception:
        return None


def sector_cap_for(symbol, default):
    """How many names a list may take from this stock's sector: `default`,
    unless the money-flow caps are switched on (money_flow.sector_cap)."""
    if money_flow is None:
        return default
    try:
        return int(money_flow.sector_cap(symbol, default))
    except Exception:
        return default


def money_flow_caps():
    """What the payload says about those caps, so the page can state them."""
    if money_flow is None:
        return {"on": False}
    try:
        return money_flow.caps_note()
    except Exception:
        return {"on": False}


def sector_outlook():
    """
    {canonical sector name: momentum row} from sectors.py, or {} when the
    sector indices cannot be reached. Cached inside sectors.py for six hours.
    """
    if sector_mom is None:
        return {}
    now = dt.datetime.now()
    if (_sector_cache["at"] and _sector_cache["value"] is not None
            and (now - _sector_cache["at"]).total_seconds() < 1800):
        return _sector_cache["value"]
    try:
        data = sector_mom.by_sector()
    except Exception:
        data = {}
    _sector_cache["at"] = now
    _sector_cache["value"] = data or {}
    return _sector_cache["value"]


def _sector_row(outlook, sector_name):
    """Match a yfinance sector label onto the sector-index table."""
    if not outlook or not sector_name:
        return None
    if sector_name in outlook:
        return outlook[sector_name]
    if sector_mom is not None:
        try:
            canon = sector_mom.normalise(sector_name)
            if canon and canon in outlook:
                return outlook[canon]
        except Exception:
            pass
    low = str(sector_name).strip().lower()
    for k, v in outlook.items():
        if k.strip().lower() == low:
            return v
    return None


def _sector_quality(row, horizon):
    if not row:
        return 0.55, "No sector index maps to this name. Scored neutral, not assumed."
    state = row.get("state") or "Unrated"
    q = SECTOR_QUALITY.get(horizon, SECTOR_QUALITY["short"]).get(state, 0.55)
    rel3 = (row.get("relative") or {}).get("3M")
    above = row.get("above_200dma_pct")
    bits = [f"{row.get('index_name') or 'Sector index'} is {state.lower()}"]
    if rel3 is not None:
        bits.append(f"{rel3:+.1f}% vs the Nifty 50 over 3 months")
    if above is not None:
        bits.append(f"{above:+.1f}% vs its own 200-day average")
    return q, "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# News and filings
# ---------------------------------------------------------------------------

def _news_index(hours):
    """
    Build {SYMBOL: [story, ...]} once per request instead of once per row.

    market_news.feed() clusters the whole store on every call, so asking it
    fifteen times — once per idea — did fifteen times the work to answer the
    same question. One pass, indexed.
    """
    idx, headlines = {}, []
    if market_news is not None:
        try:
            data = market_news.feed(limit=200, sort="latest")
            for c in data.get("clusters") or []:
                lead = c.get("lead") or {}
                story = {
                    "title": lead.get("title"),
                    "source": lead.get("source"),
                    "url": lead.get("url"),
                    "when": lead.get("when_iso") or c.get("newest_iso"),
                    "outlets": c.get("corroboration"),
                    "themes": c.get("themes") or lead.get("themes") or [],
                    "speculative": bool(lead.get("speculative")),
                    "kind": "press",
                }
                for sym in (c.get("symbols") or lead.get("symbols") or []):
                    idx.setdefault(sym.upper(), []).append(story)
                if not (c.get("symbols") or lead.get("symbols")):
                    headlines.append(story)      # market-wide, not company news
        except Exception:
            pass
    if news_feed is not None:
        try:
            for r in news_feed.feed(limit=200, max_age_hours=max(24, hours)) or []:
                story = {
                    "title": r.get("title"), "source": r.get("source"),
                    "url": r.get("url"),
                    "when": r.get("published") or r.get("when_iso"),
                    "age_minutes": r.get("age_minutes"),
                    "outlets": 1, "themes": [], "kind": "press",
                }
                for sym in (r.get("symbols") or []):
                    idx.setdefault(sym.upper(), []).append(story)
        except Exception:
            pass
    return idx, headlines[:8]


def _filing_for(symbol, hours, allowed_categories):
    if ann is None or not symbol:
        return None
    try:
        t = ann.tag(symbol, minutes=int(hours * 60))
    except Exception:
        return None
    if not t:
        return None
    cat = t.get("category")
    if allowed_categories and cat not in allowed_categories:
        return None
    t["direction"] = FILING_DIRECTION.get(cat, "event")
    return t


# Filing importance -> how much support it is worth, when the filing is one
# whose direction is actually favourable.
_FILING_SUPPORT = {"critical": 1.0, "high": 0.85, "medium": 0.6, "low": 0.35, "routine": 0.1}


def _catalyst_quality(filing, stories, hours):
    """
    0..1 for the catalyst component, plus the sentence and any adverse flag.

    Absence of news scores 0.35, not 0. A quiet name is not a bad idea — it is
    an idea with one fewer piece of evidence, and penalising silence would tilt
    the whole list towards whatever happened to be in the papers.
    """
    fresh = []
    for s in stories or []:
        age = s.get("age_minutes")
        if age is not None and age > hours * 60:
            continue
        fresh.append(s)
    fresh = fresh[:4]

    if filing and filing.get("direction") == "adverse":
        return (0.05,
                f"Adverse filing ({filing.get('category')}): {filing.get('line')}. "
                "Scored against this idea, not for it.",
                fresh, True)

    if filing and filing.get("direction") == "supportive":
        q = _FILING_SUPPORT.get(filing.get("importance"), 0.5)
        return (q, f"{filing.get('category')} filed with the exchange: {filing.get('line')}.",
                fresh, False)

    if filing:      # an "event": real, dated, but direction unknown from the tag
        q = 0.5 * _FILING_SUPPORT.get(filing.get("importance"), 0.5) + 0.25
        return (q, (f"{filing.get('category')} filed with the exchange: {filing.get('line')}. "
                    "A dated event inside the horizon; the direction is not readable from the "
                    "filing header, so it is scored as an event, not as support."),
                fresh, False)

    if fresh:
        outlets = max((s.get("outlets") or 1) for s in fresh)
        speculative = all(s.get("speculative") for s in fresh)
        q = 0.45 + min(outlets, 4) * 0.06
        if speculative:
            q -= 0.15
        note = (f"{len(fresh)} press item{'s' if len(fresh) > 1 else ''} inside the window, "
                f"carried by up to {outlets} outlet{'s' if outlets > 1 else ''}"
                + (", all of it speculative wording." if speculative else "."))
        return max(0.0, min(q, 0.8)), note, fresh, False

    return 0.35, "No filing or press inside the window: a quiet name, which is neutral.", [], False


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------

def _record_quality(detail, setup_key):
    d = (detail or {}).get(setup_key)
    if not d or not d.get("reliable"):
        n = (d or {}).get("ideas", 0)
        return 0.5, (f"Only {n} closed idea{'s' if n != 1 else ''} for this archetype so far. "
                     "That is not enough to say anything, so this factor scored neutral.")
    a = d["avg_alpha_pct"]
    q = max(0.0, min(1.0, (a + 5.0) / 10.0))
    return q, (f"This archetype has averaged {a:+.2f}% alpha over the index across "
               f"{d['ideas']} closed ideas.")


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def _scan_datetime(scanned_at):
    if not scanned_at:
        return None
    head = str(scanned_at).split(" (")[0].strip()
    for fmt in ("%d %b %Y, %H:%M", "%d %b %Y"):
        try:
            return dt.datetime.strptime(head, fmt)
        except Exception:
            continue
    return None


def _staleness(scanned_at):
    """Ideas carry a date. A momentum idea nine days old is a different object
    from a fresh one, and the old UI showed them identically."""
    d = _scan_datetime(scanned_at)
    if d is None:
        return None
    age_hours = (dt.datetime.now() - d).total_seconds() / 3600.0
    age = int(age_hours // 24)
    if age <= 0:
        return {"days": 0, "hours": round(age_hours, 1), "warn": False,
                "text": f"Scanned {int(age_hours)}h ago." if age_hours >= 1 else "Scanned just now."}
    if age <= STALE_DAYS:
        return {"days": age, "hours": round(age_hours, 1), "warn": False,
                "text": f"Scanned {age} day{'s' if age > 1 else ''} ago."}
    return {"days": age, "hours": round(age_hours, 1), "warn": True,
            "text": (f"Scanned {age} days ago. Short-term setups decay in days, so "
                     "re-run the universe scan before acting on these.")}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _band(score):
    if score >= 70:
        return "High", "Several independent lines of evidence agree."
    if score >= 58:
        return "Moderate", "The setup is there; at least one supporting factor is missing."
    return "Speculative", "Thin evidence. Size accordingly, or wait for confirmation."


def _fit_of(row):
    """Explicit None checks. `fit or composite` silently swapped in the
    composite whenever an archetype scored a genuine zero."""
    for key in ("setup_fit", "composite"):
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _sector_brief(r):
    return {"sector": r.get("sector"), "index_name": r.get("index_name"),
            "state": r.get("state"), "why": r.get("state_why"),
            "rel_3m": (r.get("relative") or {}).get("3M"),
            "rel_1m": (r.get("relative") or {}).get("1M"),
            "above_200dma_pct": r.get("above_200dma_pct")}


def _leaders_laggards(outlook):
    """
    Top and bottom sectors by 3-month relative strength.

    The two lists must not overlap. Taking a fixed four from each end of a
    short list printed the same sector as both a leader and a laggard, which
    reads as a bug even when the numbers behind it are right.
    """
    rows = [r for r in (outlook or {}).values()
            if (r.get("relative") or {}).get("3M") is not None]
    rows.sort(key=lambda r: r["relative"]["3M"], reverse=True)
    n = min(4, len(rows) // 2)
    if not n:
        return ([_sector_brief(r) for r in rows], [], len(rows))
    return ([_sector_brief(r) for r in rows[:n]],
            [_sector_brief(r) for r in rows[-n:][::-1]],
            len(rows))


def market_context(horizon: str = "short"):
    """
    The state of the market the ideas are being picked in: index regime,
    which sectors lead and lag, and the market-wide headlines that are not
    about any one company. Shown at the top of the Ideas tab, and served on
    its own so the tab can render the context before the scan payload has
    even been read.
    """
    # Same deadline as select(). This endpoint exists so the tab can show the
    # backdrop before a scan is even read; an endpoint that hangs defeats the
    # whole reason it was split out.
    outlook, _ok = _soft("sector_outlook", sector_outlook, {})
    leaders, laggards, measured = _leaders_laggards(outlook)
    (_idx, headlines), _ok = _soft(
        "news", lambda: _news_index(HORIZONS.get(horizon, HORIZONS["short"])["news_hours"]),
        ({}, []))
    regime, _ok = _soft("regime", market_regime, None)
    return {
        "regime": regime,
        "leaders": leaders,
        "laggards": laggards,
        "sectors_measured": measured,
        "headlines": headlines,
        "sector_method": ("Relative strength is the sector index return minus the Nifty 50 return "
                          "over the identical window. State compares 3-month relative strength "
                          "against 6-month, so a sector can be behind and still improving."),
    }


# ---------------------------------------------------------------------------
# The tested lists: Swing / This month, After results, Long-term compounders,
# and the setup lists
#
# leaders.py ranks every liquid stock in phase 1 of the scan and each analysed
# row carries the result. This is the layer that turns those ranks into a
# list: it removes names with a serious adverse filing, caps any one sector,
# writes the evidence in plain words and attaches the plan the test supports.
# It adds nothing to the score. The order on the page is the order the recipe
# gave, because that order is the thing that was measured.
# ---------------------------------------------------------------------------

PICK_SECTOR_CAP = int(os.environ.get("IDEAS_PICK_SECTOR_CAP", "4") or 4)
# How old a scan may be before a list warns that it is stale: about a quarter
# of each list's hold, and a day for a trade held a few days.
PICK_STALE_DAYS = {"month": 5, "results": 3, "long": 14,
                   "short": 2, "breakout": 2, "technical": 3, "quick": 1, "flow": 5, "emerging": 5}
PICK_STALE_DEFAULT = 5
# Horizon names that, on a scan from before the tested lists, meant the old
# short (weeks to a few months) archetype list.
_LEGACY_SHORT_NAMES = ("week", "momentum", "trade", "position")
# The long-term list used to drop, here, a pick with a Piotroski score under 4
# or a trailing loss, read from Yahoo and never tested. Since December 2026
# the long-term list's own gates in leaders.rank read the company's filings
# (an F-score of 5 or more, no loss over four quarters) and were replayed
# point in time, so that screen is gone.

# The mixes the three fundamental lists had before December 2026. A scan
# ranked then carries no breakdown, and its ledger is rebuilt from these so it
# still adds up to the score beside it until the next scan.
_EARLIER_MIX = {"month": {"dip21": 0.5, "high": 0.5},
                "long": {"m12": 1 / 3, "high": 1 / 3, "trend": 1 / 3},
                "results": {"reaction": 1.0}}

_EVIDENCE = (
    ("m12", "momentum_12m", "12-month return for its risk"),
    ("m6", "momentum_6m", "6-month return for its risk"),
    ("high", "near_high", "Closeness to the 52-week high"),
    ("trend", "steady_trend", "How steady the climb was"),
    ("calm", "calm", "Calm: low volatility"),
    ("dip", "dip", "Dip over the last five sessions"),
    ("dip21", "dip_month", "Dip over the last month"),
    ("reaction", "reaction", "Move on the day its results were priced"),
)

# What the chart and the tape say about a pick, in the reader's words. These
# are printed as facts and move no rank: research/signals_lab.py tried each of
# them as a gate or a tilt on the lists, and breakouts as lists of their own,
# and none earned a place (research/IDEAS-STUDY.md, "What did not earn a place").
CHART_NOTE = ("Facts about the chart, not reasons for the pick. Tested over ten years, none of "
              "these improved a list, so none of them changes a rank.")
_orders_cache = {"at": 0.0, "by_symbol": {}}
ORDER_LOOKBACK_DAYS = 45


def chart_facts(tech, facts=None, pattern=None, price=None):
    """Rows of (what, what it says) for a pick's Details, or []."""
    if not tech:
        return []
    out = []

    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    b = tech.get("breakout")
    if b:
        ago = b.get("sessions_ago")
        when = "today" if ago == 0 else ("yesterday" if ago == 1 else f"{ago} sessions ago")
        vol = f", on {b['rel_volume']:.1f} times its usual volume" if num(b.get("rel_volume")) else ""
        out.append({"k": "Breakout", "v": f"Closed at a six-month high {when}{vol}, the first in over 20 sessions."})
    elif num(tech.get("below_60d_high_pct")):
        gap = tech["below_60d_high_pct"]
        out.append({"k": "Price", "v": ("At its 60-day high." if gap < 0.5 else
                                         f"{gap:.0f}% under its 60-day high.")})
    f = facts or {}
    above = []
    if num(tech.get("above_20d_pct")):
        above.append(("20", tech["above_20d_pct"] > 0))
    if num(price) and num(f.get("sma50")):
        above.append(("50", price > f["sma50"]))
    if num(price) and num(f.get("sma200")):
        above.append(("200", price > f["sma200"]))
    if above:
        over = [n for n, ok in above if ok]
        under = [n for n, ok in above if not ok]

        def join(xs):
            return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
        text = (f"Above its {join(over)}-day average{'s' if len(over) > 1 else ''}" if over else "")
        if under:
            text += (", under" if text else "Under") + f" its {join(under)}-day"
            text += "" if over else f" average{'s' if len(under) > 1 else ''}"
        out.append({"k": "Averages", "v": text + "."})
    gauges = []
    if num(tech.get("rsi")):
        gauges.append(f"RSI {tech['rsi']:.0f}")
    if num(tech.get("macd_hist_pct")):
        side = "above" if tech["macd_hist_pct"] > 0 else "below"
        gauges.append(f"MACD {side} its signal line{' and rising' if tech.get('macd_rising') else ''}")
    if num(tech.get("adx")):
        gauges.append(f"ADX {tech['adx']:.0f}")
    if gauges:
        out.append({"k": "Indicators", "v": " · ".join(gauges) + "."})
    vol = []
    if num(tech.get("rel_volume")):
        vol.append(f"{tech['rel_volume']:.1f} times its usual volume in the last session")
    if num(tech.get("up_down_volume")):
        r = tech["up_down_volume"]
        vol.append(f"{r:.1f} times as much volume on rising days as on falling days over 50 sessions"
                   if r >= 1 else
                   f"more volume on falling days than rising days over 50 sessions ({r:.1f} to 1)")
    if vol:
        text = "; ".join(vol)
        out.append({"k": "Volume", "v": text[0].upper() + text[1:] + "."})
    if num(tech.get("squeeze")) and tech["squeeze"] <= 0.75:
        out.append({"k": "Range", "v": (f"Tightening: the last ten sessions moved {tech['squeeze'] * 100:.0f}% "
                                         "as much as the last sixty.")})
    if pattern and pattern.get("name"):
        status = str(pattern.get("status") or "").lower()
        text = f"{pattern['name']}, {status or 'seen'}"
        if status == "forming" and num(pattern.get("trigger")):
            away = pattern.get("distance_to_trigger_pct")
            text += f". It confirms on a close through \u20b9{pattern['trigger']:,.2f}"
            if num(away):
                text += f", {abs(away):.1f}% away"
        out.append({"k": "Pattern", "v": text + "."})
    return out


# ---- Live catalysts on the setup lists (December 2026) ---------------------
# A reader pointed out that RATNAVEER's and HFCL's moves came with news: an
# order, an earnings call that raised the outlook, a story in the press. The
# site reads all three as they arrive, but keeps no history of them, so they
# cannot be tested. They are shown beside a setup pick, and they move a pick
# up its own list; they never put a stock on a list or take one off.
CATALYST_LISTS = ("breakout", "technical", "quick", "flow", "emerging")
CONCALL_DAYS = 100        # an earnings call older than this is last quarter's news
CATALYST_NEWS_HOURS = 168 # a story older than a week is not a catalyst
CATALYST_ORDER_PCT = 1.0  # an order worth this share of the company's value or more


def _concall_for(symbol):
    """The company's newest earnings-call transcript read in the last
    CONCALL_DAYS, as {"date", "quarter", "headline", "weight", "said",
    "guidance_count"}, or None. "said" is a commitment management made on the
    call, quoted from the transcript (the brief checks quotes word for word);
    "weight" is how much the brief thought the call mattered."""
    if concalls is None or not symbol:
        return None
    try:
        rows = concalls.filed_since(symbol=str(symbol).upper(), limit=1)
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    if r.get("epoch") and time.time() - float(r["epoch"]) > CONCALL_DAYS * 86400:
        return None
    try:
        brief = concalls.briefs_for([r["pdf"]]).get(r["pdf"]) or {}
    except Exception:
        brief = {}
    dg = r.get("digest") or {}
    said = ((brief.get("commitments") or [{}])[0].get("said")
            or (dg.get("guidance") or [{}])[0].get("said"))
    return {"date": (r.get("at") or "")[:10] or None, "quarter": dg.get("quarter"),
            "headline": brief.get("headline") or r.get("headline"),
            "weight": brief.get("weight"), "guidance_count": dg.get("guidance_count"),
            "said": (said[:220] + "\u2026") if said and len(said) > 220 else said}


def _recent_news(stories, hours=CATALYST_NEWS_HOURS):
    """Stories from the last `hours`, rumours left out."""
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out = []
    for st in stories or []:
        if st.get("speculative"):
            continue
        when = str(st.get("when") or "")
        try:
            t = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if t >= cut:
            out.append(st)
    return out


def _finite_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def catalysts(symbol, stories=None, order=None):
    """
    What has happened to a company lately that the chart cannot show:
    {"order", "concall", "news", "lines", "score"}, or None when there is
    nothing. `lines` are the facts in words; `score` only orders a list's
    picks among themselves (an order worth 1% or more of the company 1 to 3,
    a call the brief rated high or medium 1 or 0.5, a week's news 0.3).
    """
    order = order if order is not None else _order_for(symbol)
    call = _concall_for(symbol)
    news = _recent_news(stories)
    lines, score = [], 0.0
    if order and _finite_num(order.get("value_cr")):
        pct = order.get("pct_of_market_cap")
        lines.append(f"Order worth \u20b9{float(order['value_cr']):,.0f} crore"
                     + (f", {float(pct):.1f}% of its market value" if _finite_num(pct) else "")
                     + (f", disclosed {order['date']}" if order.get("date") else ""))
        if _finite_num(pct) and float(pct) >= CATALYST_ORDER_PCT:
            score += min(3.0, 1.0 + float(pct) / 5.0)
    if call:
        lines.append("Earnings call" + (f" ({call['quarter']})" if call.get("quarter") else "")
                     + (f" on {call['date']}" if call.get("date") else "")
                     + (f": {call['headline']}" if call.get("headline") else ""))
        score += {"high": 1.0, "medium": 0.5}.get(call.get("weight"), 0.25)
    if news:
        lines.append(f"In the news: {news[0].get('title')}"
                     + (f" ({len(news)} stories this week)" if len(news) > 1 else ""))
        score += 0.3
    if not lines:
        return None
    return {"order": order, "concall": call, "news": news[:3], "lines": lines[:3], "score": round(score, 2)}


def _order_for(symbol):
    """The largest order this company disclosed in the last few weeks, with
    its size against the company's market value, or None. Read from the order
    ledger (wow_orders), which reads the amount out of the filing itself."""
    if wow_orders is None or not symbol:
        return None
    now = time.time()
    if now - _orders_cache["at"] > 600:
        by = {}
        try:
            today = dt.date.today()
            for r in wow_orders.history(today - dt.timedelta(days=ORDER_LOOKBACK_DAYS), today) or []:
                sym = str(r.get("symbol") or "").upper()
                pct = r.get("pct_of_market_cap")
                if not sym or r.get("value_cr") is None:
                    continue
                cur = by.get(sym)
                if cur is None or (pct or 0) > (cur.get("pct_of_market_cap") or 0):
                    by[sym] = {"date": r.get("date"), "value_cr": r.get("value_cr"),
                               "pct_of_market_cap": pct, "headline": r.get("headline"),
                               "pdf": r.get("pdf"), "confident": bool(r.get("value_confident"))}
        except Exception:
            by = _orders_cache["by_symbol"]
        _orders_cache.update(at=now, by_symbol=by)
    return _orders_cache["by_symbol"].get(str(symbol).upper())


def market_test(key, regime):
    """
    What the test found for this list in a market like today's, in a sentence,
    or None. The old Ideas page warned that trend setups fail when the index
    is weak. Measured on these lists, picks made while the Nifty 500 was under
    its 200-day average did not do worse, so the page says what was measured
    instead of repeating the warning.
    """
    rec = tested_record(key) or {}
    split = rec.get("market") or {}
    vs200 = (regime or {}).get("pct_vs_200dma")
    if vs200 is None or not split.get("above_200d") or not split.get("below_200d"):
        return None
    under = vs200 < 0
    here, other = (split["below_200d"], split["above_200d"]) if under else (split["above_200d"], split["below_200d"])
    where = "under" if under else "above"
    return {
        "state": "below_200d" if under else "above_200d",
        "text": (f"The index is {where} its 200-day average. In the test, picks made on days like "
                 f"this averaged {here['avg_pct']:+.1f}% ({here['up_pct']:.0f} in 100 rose), against "
                 f"{other['avg_pct']:+.1f}% on the other days. The list is not held back in either."),
        "lists": here.get("list_dates"),
    }


def has_picks(payload):
    """Does this scan carry the leader ranks the tested lists are built from?"""
    rows = (payload or {}).get("factor_universe") or (payload or {}).get("rankings") or []
    return any((r.get("leader") or {}).get("lists") for r in rows)


def _stamps(rows):
    """The leaders.RECIPE stamps a scan's ranked rows carry."""
    return {(r.get("leader") or {}).get("recipe") for r in rows or () if (r.get("leader") or {}).get("lists")}


def scan_recipe(payload):
    """The recipe a scan's leader ranks were made under: the one stamp its
    ranked rows carry, or None (no ranks, or rows of more than one stamp)."""
    rows = (payload or {}).get("factor_universe") or (payload or {}).get("rankings") or []
    stamps = _stamps(rows)
    return next(iter(stamps)) if len(stamps) == 1 else None


def breakout_pattern(block):
    """The pattern of the breakout a block's breakout pick was made on:
    "VCP launchpad" or "Base turnaround", by the same order the list uses
    (the earliest launch of the last five sessions of a pattern it picks
    from), or None."""
    t = (block or {}).get("technicals") or {}
    for L in t.get("launch") or []:
        if L.get("a") and "A" in leaders.LAUNCH_PATTERNS:
            return "VCP launchpad"
        if L.get("b") and "B" in leaders.LAUNCH_PATTERNS:
            return "Base turnaround"
    return None


def _setup_evidence(key, block):
    """The ledger for a setup list: what the setup measured, line by line.
    A line that is a pass or a fail carries points 1 of 1; a plain
    measurement carries none."""
    t, facts, parts = block.get("technicals") or {}, block.get("facts") or {}, block.get("parts") or {}
    n = block.get("universe")
    out = []

    def line(factor, detail, met=None):
        out.append({"factor": factor, "detail": detail, "share_pct": None,
                    "points": None if met is None else (1 if met else 0),
                    "of": None if met is None else 1})
    lead = f"Leader score ahead of {parts.get('leader')}% of {n} liquid stocks."
    if key == "short":
        b, f, q = t.get("box") or {}, block.get("sector_flow") or {}, block.get("quarter") or {}
        res = block.get("results") or {}
        ago = b.get("sessions_ago")
        line("Consolidation", f"{leaders.BOX_SESSIONS} sessions between \u20b9{b.get('low')} and \u20b9{b.get('top')}: "
                              f"a {b.get('width_pct')}% range.", True)
        line("Breakout", ("Closed" if not ago else f"{ago} session{'s' if ago != 1 else ''} ago it closed")
             + f" at \u20b9{b.get('close')}, above the range, on {b.get('rel_volume')} times its usual volume. "
               "Still above it.", True)
        met = t.get("scorecard_met") or []
        line("Technicals", f"{t.get('scorecard')} of 9 chart conditions: " + "; ".join(met) + ".", True)
        line("Trend", f"Above its 200-day average (\u20b9{facts.get('sma200')}). " + lead, True)
        line("Industry", f"{f.get('sector')} ranks {f.get('classic_rank') or f.get('rank')} of {f.get('of')} on money flow: "
                         f"{f.get('breadth_pct')}% of its stocks are above their 50-day average and its "
                         f"median stock moved {f.get('month_pct')}% this month.", True)
        if q.get("pat_yoy_pct") is not None:
            rv = q.get("revenue_yoy_pct")
            line("Fundamentals", f"Last quarter's profit {'rose' if q['pat_yoy_pct'] >= 0 else 'fell'} "
                                 f"{abs(q['pat_yoy_pct']):.0f}% on a year ago"
                                 + (f", sales {'rose' if rv >= 0 else 'fell'} {abs(rv):.0f}%" if rv is not None else "")
                                 + ".", q["pat_yoy_pct"] >= 0)
        else:
            line("Fundamentals", "No quarterly result on file in the last five months, so this screen passed it unread.")
        if res.get("move_pct") is not None:
            line("Results", f"Priced on {leaders._short_day(res.get('session'))}: {res['move_pct']:+.1f}% that day, "
                            f"the average stock {res['market_move_pct']:+.1f}%.", res.get("reaction_pct", 0) >= -2)
    elif key == "breakout":
        launch = (t.get("launch") or [])
        f, q = block.get("sector_flow") or {}, block.get("quarter") or {}
        # The breakout the list counted: the earliest of the last five still above its base.
        L = next((x for x in launch if (x.get("a") and "A" in leaders.LAUNCH_PATTERNS)
                  or (x.get("b") and "B" in leaders.LAUNCH_PATTERNS)), None) or {}
        pattern = breakout_pattern(block) or "VCP launchpad"
        base = (L.get("a") if pattern == "VCP launchpad" else L.get("b")) or {}
        line("Pattern", pattern + (": a base that tightened before it broke." if pattern == "VCP launchpad" else
                                   ": a first 60-session high after a long sideways base."), True)
        line("The base", f"{base.get('base')} sessions between \u20b9{base.get('low')} and \u20b9{base.get('top')}: "
                         f"a {base.get('width_pct')}% range. The list needs "
                         f"{leaders.LAUNCH_A_WIDTH * 100:.0f}% or tighter.", True)
        ago = L.get("sessions_ago")
        line("The breakout", ("Closed" if not ago else f"{ago} session{'s' if ago != 1 else ''} ago it closed")
             + f" at \u20b9{L.get('close')}, above the top of the base, on {L.get('rel_volume')} times its usual "
               "volume. Still above it.", True)
        ext = t.get("ext_50d_pct")
        line("Not stretched", (f"{ext}% above its 50-day average" if ext is not None else "Near its 50-day average")
             + f" and {facts.get('return_3m_pct')}% over three months. The list buys "
               f"{leaders.CHASE_EXT50:.0f}% or less over the 50-day and {leaders.CHASE_RET3M * 100:.0f}% or less "
               "in three months.", True)
        line("Long-term trend", f"Above its 200-day average (\u20b9{facts.get('sma200')}).", True)
        if f:
            line("Industry", f"{f.get('sector')} ranks {f.get('rank')} of {f.get('of')} on money flow.", True)
            if f.get("near_high") is not None:
                line("Industry breaking out",
                     (f"Its industry index made a new 60-session high in the last 10 sessions."
                      if f.get("breakout") else
                      f"Its industry index is {f.get('from_high_pct')}% under its 60-session high.")
                     + " The list wants it within 3%.", bool(f.get("near_high")))
        line("Strength", lead, True)
        if q.get("pat_yoy_pct") is not None:
            line("Last quarter", f"Profit {'rose' if q['pat_yoy_pct'] >= 0 else 'fell'} "
                                 f"{abs(q['pat_yoy_pct']):.0f}% on a year ago.", True)
    elif key == "technical":
        f = block.get("sector_flow") or {}
        line("Uptrend", "Price and its 50-day average are above a rising 200-day average.", True)
        line("Pullback", f"Dipped to its 20-day average (\u20b9{t.get('ema20')}) in the last three sessions and "
                         f"closed up, {t.get('ext_20d_pct')}% above it. The list buys "
                         f"{leaders.PULL_EXT_MAX:.0f}% or less above it.", True)
        line("RSI", f"{t.get('rsi')}: room to run. The list wants {leaders.PULL_RSI[0]:.0f} to "
                    f"{leaders.PULL_RSI[1]:.0f}.", True)
        if f:
            line("Industry", f"{f.get('sector')} ranks {f.get('rank')} of {f.get('of')} on money flow.", True)
        line("Strength", lead + f" The list needs {leaders.PULL_LEADER * 100:.0f} or more.", True)
    elif key == "quick":
        line("The dip", f"Two-day RSI {t.get('rsi2')}, {facts.get('return_5d_pct')}% over five sessions. The "
                        f"setup is an RSI under {leaders.DIP_RSI2:.0f} or a fall of "
                        f"{abs(leaders.DIP_DROP5) * 100:.0f}% or more.", True)
        line("Support", f"Still within 3% of its 50-day average (\u20b9{facts.get('sma50')}).", True)
        line("Uptrend", "Price and its 50-day average are above the 200-day average.", True)
        line("Strength", lead + f" The list needs the top {100 - leaders.DIP_LEADER * 100:.0f}%.", True)
        line("Sell at", "After about a month (21 sessions), or on a close 10% under the price it was bought at.")
    elif key == "flow":
        f = block.get("sector_flow") or {}
        line("Sector", f"{f.get('sector')}: ranked {f.get('rank')} of {f.get('of')} sectors on rotation.", True)
        line("Sector's three months", f"Its median stock moved {f.get('month3_pct')}% over the last 63 sessions.")
        line("Breadth", f"{f.get('breadth_pct')}% of its {f.get('stocks')} liquid stocks are above their 50-day average.")
        line("Turnover share", f"{f.get('shift')} times its sixty-session share of market turnover this week.")
        line("Ahead of the market", f"{facts.get('return_1m_pct')}% this month and {facts.get('return_3m_pct')}% "
                                    "over three months, both ahead of the Nifty 500.", True)
        line("Strength", lead + f" Among the {leaders.FLOW_PER_SECTOR} strongest in its sector.", True)
    elif key == "emerging":
        line("Listed", f"{block.get('listed_sessions')} sessions ago: six to eighteen months.", True)
        line("Stage-2 advance", "Above a rising 50-day average, within 10% of its high "
                                f"({facts.get('below_high_pct')}% below it).", True)
        line("Ahead of the market", f"{facts.get('return_1m_pct')}% this month and {facts.get('return_3m_pct')}% "
                                    "over three months, both ahead of the Nifty 500.", True)
        line("Strength", lead + (" Its 6-month return stands in for the 12-month one." if block.get("young") else ""),
             True)
        line("Sell at", "After about four months (90 sessions); after the first 15, on a close under the "
                        "50-day average; at any time on a close 15% under the price it was bought at.")
    return out


def _tab_evidence(key, block):
    """
    The ledger of one of the three fundamental lists, read from the
    breakdown leaders.rank wrote beside the score: one row per part of the
    mix (pull, high, fundmom, secflow, catalyst; reaction, volume, growth;
    quality, compounding, governance, valuation, trendq), each with what it
    read, its weight and the points it adds, so the rows add up to the
    conviction printed beside them. None for a block ranked before the lists
    carried a breakdown.
    """
    entry = (((block or {}).get("lists") or {}).get(key)) or {}
    rows = entry.get("breakdown")
    if rows is None:
        return None
    out = []
    for b in rows:
        k = b.get("factor")
        detail = str(b.get("detail") or "").strip().rstrip(".")
        out.append({"factor": b.get("label") or leaders.FACTOR_LABELS.get(k, k), "key": k,
                    "points": round(leaders._finite(b.get("points")) or 0.0, 1),
                    "of": round((leaders._finite(b.get("weight")) or 0.0) * 100, 1),
                    "share_pct": b.get("value"), "detail": (detail + ".") if detail else ""})
    return out


def _pick_evidence(key, block):
    """The ledger: each measurement's percentile and its share of the score."""
    spec = leaders.LISTS[key]
    if spec.get("kind") == "setup":
        return _setup_evidence(key, block)
    tab = _tab_evidence(key, block)
    if tab is not None:
        return tab
    mix = dict(_EARLIER_MIX.get(key) or spec["mix"])
    if "leader" in mix:                       # the leader score is four parts
        w = mix.pop("leader")
        for k in ("m12", "m6", "high", "trend"):
            mix[k] = mix.get(k, 0) + w / 4.0
    parts, facts, n = block.get("parts") or {}, block.get("facts") or {}, block.get("universe")
    detail = {
        "m12": ((f"Listed under a year, so its 6-month return ({facts.get('return_6m_pct')}%) stands in "
                 f"for the 12-month one, at {facts.get('volatility_pct')}% yearly volatility")
                if block.get("young") else
                f"{facts.get('return_12m_pct')}% over 12 months, at {facts.get('volatility_pct')}% yearly volatility"),
        "m6": "Return over the last six months, last month skipped, for the same volatility",
        "high": f"{facts.get('below_high_pct')}% below its 52-week high",
        "trend": f"Straightness {facts.get('trend_straightness')}/100 over 90 sessions",
        "calm": f"{facts.get('volatility_pct')}% yearly volatility",
        "dip": f"{facts.get('return_5d_pct')}% over the last five sessions",
        "dip21": f"{facts.get('return_1m_pct')}% over the last month",
    }
    res = block.get("results") or {}
    out = []
    for k, part_key, label in _EVIDENCE:
        w = mix.get(k)
        if not w:
            continue
        pct = parts.get(part_key)
        if pct is None:
            continue
        of = round(w * 100, 1)
        if k == "reaction":
            text = (f"{res.get('move_pct', 0):+.1f}% on {leaders._short_day(res.get('session'))}, the first session after its "
                    f"results reached the exchange; the average liquid stock moved "
                    f"{res.get('market_move_pct', 0):+.1f}%. Ahead of {pct}% of the "
                    f"{res.get('reported')} companies priced on results in the last ten sessions.")
        else:
            text = f"{detail[k]}. Ahead of {pct}% of {n} liquid stocks."
        out.append({"factor": label, "points": round(pct * w, 1), "of": of, "share_pct": pct,
                    "detail": text})
    return out


def _scan_date(scanned_at):
    d = _scan_datetime(scanned_at)
    return d.date() if d else dt.date.today()


def tested_record(key):
    """What the study measured for one list, or None when the file is absent."""
    if leaders is None:
        return None
    return (leaders.TESTED.get("lists") or {}).get(key)


def _choose_picks(rows_all, key, limit, hours, exclude=()):
    """
    Which rows one list shows, in order, before anything is decorated.

    Cheap on purpose (no news, no regime, no sector feed), so a list that
    gives way to another can work out what that list shows. Returns
    (chosen, excluded_adverse, capped, gave_way, per_sector, universe,
    considered), where each chosen item is (row, entry, filing, adverse).
    """
    pool, excluded_adverse, gave_way = [], [], []
    universe = None
    for r in rows_all:
        block = r.get("leader") or {}
        entry = (block.get("lists") or {}).get(key) or {}
        if not entry.get("rank"):
            continue
        universe = universe or block.get("universe")
        sym = (r.get("symbol") or "").upper()
        if sym in exclude:
            # Shown on the list this one gives way to. The engine already left
            # out that list's top 15; this catches the names its sector cap or
            # screens pulled up from further down.
            gave_way.append(sym)
            continue
        filing = _filing_for(sym, hours, None)
        adverse = bool(filing and filing.get("direction") == "adverse")
        if adverse and (filing or {}).get("importance") in HARD_EXCLUDE_ADVERSE:
            excluded_adverse.append({"symbol": sym, "name": r.get("name"),
                                     "category": filing.get("category"),
                                     "headline": filing.get("headline"),
                                     "line": filing.get("line"),
                                     "setup_fit": r.get("setup_fit")})
            continue
        pool.append((r, entry, filing, adverse))

    pool.sort(key=lambda t: t[1]["rank"])
    chosen, per_sector, capped = [], {}, 0
    for item in pool:
        if len(chosen) >= limit:
            break
        sec = item[0].get("sector") or "Unknown"
        # The money-flow list is four stocks from each of four sectors by
        # construction; a sector cap of its own would only cut that short.
        if (key != "flow" and sec != "Unknown"
                and per_sector.get(sec, 0) >= sector_cap_for(item[0].get("symbol"), PICK_SECTOR_CAP)):
            capped += 1
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
        chosen.append(item)
    return chosen, excluded_adverse, capped, gave_way, per_sector, universe, len(pool)


_REPLAYED = (" The record beside the list is this rule replayed on NSE prices from 2017 to 2026: "
             "the list as it stood every fifth session, bought at the next open.")
SETUP_METHOD = {
    "short": ("A stock is here when it spent 40 sessions inside a range 18% wide or tighter and then closed "
              "above it on at least twice its usual volume in the last five sessions, and is still above it. "
              "It must also pass five screens: above its 200-day average and in the stronger half of liquid "
              "stocks; six or more of nine chart conditions; its industry in the top half on money flow; no "
              "fall in profit last quarter; and results, if just out, not sold by the market. A serious "
              "adverse filing removes it. Picks are ordered on strength, chart, industry and profit growth "
              "together." + _REPLAYED),
    "breakout": ("A stock is here when it closed above the top of a 40- or 60-session base in the last five "
                 "sessions and is still above it. The base must be 28% wide or less and either 20% or tighter "
                 "or tightening before the break (a calmer last fortnight, or volume drying up): a VCP "
                 "launchpad. The breakout needs 1.6 times the usual volume and a close in the top 45% of the "
                 "day's range. The stock must be above its 200-day average, with a leader score of 45 or "
                 "more, its industry in the top 60% on money flow and its industry's own index within 3% of "
                 "its 60-session high, and a month better than the Nifty 500's. "
                 "It is left out if it is already more than 16% above its 50-day average or up 55% in three "
                 "months, if its last quarter's profit fell more than 10%, or if the market sold its results. "
                 "Newest breakouts first, then the heaviest volume. Held about three months." + _REPLAYED),
    "technical": ("A stock is here when it is in a confirmed uptrend (price and the 50-day average above a "
                  "rising 200-day average, leader score 55 or more), dipped to within 1.5% of its 20-day "
                  "average in the last three sessions, and closed up and back above it, no more than 6% over "
                  "it. Its RSI must be 48 to 68, its industry in the top half on money flow, and its last "
                  "quarter's profit not down more than 10%. Ordered on strength, industry and how much more "
                  "volume trades on up days. Held about three months." + _REPLAYED),
    "quick": ("A stock is here when it is in an uptrend, in the top 35% of liquid stocks on the leader score, "
              "and was sold off hard (a two-day RSI under 10, or 4% or more down in five sessions) while "
              "still within 3% of its 50-day average. A fall on its own results is left out. The most "
              "oversold come first. Held about a month: the old exit at the 5-day average lost money after "
              "costs in the test." + _REPLAYED),
    "flow": ("Every NSE sector with eight or more liquid stocks is ranked on rotation: 45% its median "
             "stock's move over three months, 35% how many of its stocks are above their 50-day average, 20% "
             "its share of market turnover this week against its share over sixty sessions. The list is the "
             "five strongest stocks in each of the top three sectors that are in an uptrend, within 15% of "
             "their high and ahead of the Nifty 500 over one month and three. Held about three months."
             + _REPLAYED),
    "emerging": ("Companies listed six to eighteen months, trading \u20b910 crore a day or more, above a "
                 "rising 50-day average and within 10% of their high, with a leader score of 60 or more, "
                 "ahead of the Nifty 500 over one month and three, and no more than 18% above the 50-day "
                 "average. A loss or a fall in sales in the last quarter, where one is on file, rules a "
                 "company out. Held about four months; after the first 15 sessions it is sold on a close "
                 "under its 50-day average." + _REPLAYED),
}
SETUP_EMPTY = {
    "short": ("No stock passes every screen today. A breakout from a tight base, in a strong industry, with "
              "profit not falling, is uncommon: in the test about one list in four was empty. An empty list "
              "is the answer, not a fault."),
    "breakout": ("No stock has broken out of a tightening base on heavy volume in the last five sessions "
                 "without already being stretched. The bases closest to breaking are listed below."),
    "technical": ("No stock in a rising trend has pulled back to its 20-day average and turned up in this "
                  "scan. That is common in a market falling hard and in one running hard."),
    "quick": ("No market leader is this oversold today. The setup needs a sharp fall in a stock that is in "
              "an uptrend and still holding its 50-day average; most days have a few, some have none."),
    "flow": "No sector could be ranked on money flow in this scan.",
    "emerging": "No company listed six to eighteen months passes the tests in this scan.",
}
SETUP_NOTE = {
    "short": ("Stocks on the verge of a breakout are shown under the list, to watch. In the test, buying "
              "before the breakout did no better than chance, so the list waits for it."),
    "quick": ("Held about a month. In the test about half the picks rose, but the average one made money "
              "after the cost of buying and selling, which the old few-day exit did not."),
    "breakout": ("Held about three months with no target: much of the average comes from the one pick in ten "
                 "that made 25% or more. Expect about half to fall."),
    "emerging": ("Listed six to eighteen months, so each has less history to judge by. Much of the average "
                 "comes from a few large winners; more than half the picks fell in the test."),
}


def _tab_method(key):
    """
    How one of the three fundamental lists is made, in words, from the recipe
    the engine is running now (leaders.MONTH, RESULTS, LONG), so the page
    never describes a threshold the engine does not use. None for any other
    list.
    """
    cfg = leaders.recipe_of(key)
    if cfg is None:
        return None
    if key == "month":
        floor = cfg["leader_floor"]
        pull = cfg.get("pull_mix") or {}
        pulled = (" and the week" if pull.get("dip") else "") if pull.get("dip21") else (
            " over the week" if pull.get("dip") else "")
        top = cfg.get("sector_top", 0.5)
        return (f"A stock is here when it is a market leader (a leader score of {floor * 100:.0f} or more out "
                "of 100), in an uptrend and outside the most volatile "
                "fifth" + ((", in an industry in the top half on money flow" if top == 0.5 else
                            f", in an industry in the top {top * 100:.0f}% on money flow")
                           if cfg["sector_gate"] else "")
                + (", with no loss and no fall in profit in its last quarter" if cfg["profit_guard"] else "")
                + (f", no results the market sold (more than {abs(cfg['bad_reaction']) * 100:.0f}% under the "
                   f"average stock that day) in the last {cfg['result_lookback']} sessions"
                   if cfg["result_guard"] else "")
                + f", and promoters pledging {cfg['pledge_max']:g}% of the company or less. It is ordered "
                + (f"on its pullback over the month{pulled}" if pull.get("dip21") else f"on its pullback{pulled}")
                + ", its closeness to the 52-week high, its last "
                "quarter's sales and margin growth (sales alone for a bank or lender), its industry's money flow and a live catalyst (heavy "
                "deliveries on a falling week, or a large order), with at most "
                f"{cfg['sector_cap']} stocks from one industry. A figure a company has not filed counts as "
                "the middle of the field.")
    if key == "results":
        floor = {"sma200_85": (f", nor more than {(1 - leaders.RESULTS_SMA200_FLOOR) * 100:.0f}% under its "
                               "200-day average"),
                 "sma50": ", nor under its 50-day average"}.get(cfg["floor"], "")
        return (f"Every liquid NSE company whose quarterly results were first priced in the last "
                f"{leaders.RESULTS_WINDOW} sessions is ranked against the others that reported, on how its "
                "stock moved that session against the average stock, the volume behind the move and the "
                "growth itself"
                + ((f". Only results that were real growth are listed: sales up {cfg['rev_min']:g}% or more on "
                    "a year ago, profit up and operating profit up with one-off items left out, other income "
                    f"no more than {cfg['other_income_max']:g}% of profit before tax, no exceptional gain over "
                    f"{cfg['exceptional_max'] * 100:.0f}% of it and cash from operations positive in the last "
                    "full year (for a bank or lender: sales, profit and the exceptional test only)")
                   if cfg["quality_gate"] else "")
                + f", and a stock not already up more than {cfg['chase_max'] * 100:.0f}% that day{floor}. With fewer "
                f"than {cfg['min_qualified']} such companies there is no list, and at most "
                f"{cfg['sector_cap']} come from one industry.")
    return ("A company is here when it is above its 200-day average and outside the most volatile fifth, made "
            f"money over the last four quarters, scores {cfg['f_score_min']} or more of 9 on Piotroski's "
            f"F-score and has promoters pledging {cfg['pledge_max']:g}% of it or less"
            + ((f"; it earns {cfg['roce_min']:g}% or more on its capital, with cash from operations at least "
                f"{cfg['cfo_to_pat_min']:g} times its profit and debt no more than {cfg['de_max']:g} times its "
                f"equity (a bank or lender: {cfg['roe_min_fin']:g}% or more on its equity), and its "
                "shareholders' equity is positive")
               if cfg["floors"] else "")
            + ((f"; and it is priced at a P/E of {cfg['pe_max']:g} or under, unless its PEG is "
                f"{cfg['peg_escape']:g} or under on profit growing {cfg['cagr_escape']:g}% a year")
               if cfg["valuation_ceiling"] else "")
            + ". It is ordered on returns and cash, three-year growth, pledges and holdings, its valuation "
            "against its own industry and its year-long trend, with at most "
            f"{cfg['sector_cap']} stocks from one industry. A figure a company has not filed counts as the "
            "middle of the field.")


def _study_current(key):
    """
    Is the record in the study file the record of the recipe running now?
    The setup lists' records are the engine's own replay and always are. The
    three fundamental lists were rebuilt in December 2026: their record is the
    one research/fundamental_ideas_lab.py stamps with leaders.RECIPE, and until
    the study file carries that stamp the page shows none rather than the
    replaced lists' record beside the new ones.
    """
    if leaders.recipe_of(key) is None:
        return True
    return (leaders.TESTED or {}).get("recipe") == leaders.RECIPE


def _results_empty_text(reported, qualified, day):
    """Why the After results list is empty, and when it fills in: during a
    results season as more results are priced, else from the next one."""
    start, running = leaders.next_results_season(day)
    season = ("Companies are reporting now; the list fills in as more results are priced and pass its tests."
              if running else
              f"Companies report again from about {start.day} {start.strftime('%B')}; this list fills in then.")
    window, pool = leaders.RESULTS_WINDOW, leaders.RESULTS_MIN_POOL
    if not reported:
        return f"No liquid company's results were priced in the last {window} sessions. {season}"
    if reported < pool:
        return (f"Only {reported} liquid compan{'y has' if reported == 1 else 'ies have'} had results priced in "
                f"the last {window} sessions, and the list needs {pool} to rank. {season}")
    need = leaders.RESULTS["min_qualified"]
    if qualified >= need:
        return "Nothing passed every test in this scan."
    return (f"{reported} liquid companies had results priced in the last {window} sessions and {qualified} "
            f"passed every test; the list needs {need}. {season}")


def _watch_with_catalysts(rows, news_idx):
    """The breakout watch list with each base's live catalyst, if any: a
    base with a fresh order or earnings call behind it is the one to watch."""
    out = []
    for r in rows:
        r = dict(r)
        c = catalysts(r.get("symbol"), (news_idx or {}).get(str(r.get("symbol") or "").upper()))
        r["catalyst"] = c["lines"][0] if c else None
        out.append(r)
    return out


def select_picks(payload: dict, key: str, limit: int = 15) -> dict:
    """One of the tested lists, from a scan that carries leader ranks."""
    spec = leaders.LISTS[key]
    rows_all = payload.get("factor_universe") or payload.get("rankings") or []
    regime, _ok = _soft("regime", market_regime, None)
    outlook, _ok = _soft("sector_outlook", sector_outlook, {})
    hours = max(72, spec["hold_days"] * 24)
    (news_idx, headlines), _ok = _soft("news", lambda: _news_index(hours), ({}, []))
    try:
        tracked = tracker.tracked_symbols(source="manual") if tracker else set()
    except Exception:
        tracked = set()
    _leaders = _leaders_laggards(outlook)
    stale = _staleness(payload.get("scanned_at"))
    if stale and stale.get("days") is not None:
        limit_days = PICK_STALE_DAYS.get(key, PICK_STALE_DEFAULT)
        stale = dict(stale, warn=stale["days"] > limit_days)
        if stale["warn"]:
            stale["text"] = (f"This list is {stale['days']} days old. "
                             "Run a new scan before using it.")
    called_on = _scan_date(payload.get("scanned_at"))

    exclude = set()
    other = spec.get("gives_way_to")
    if other in leaders.LISTS:
        o_hours = max(72, leaders.LISTS[other]["hold_days"] * 24)
        shown = _choose_picks(rows_all, other, limit, o_hours)[0]
        exclude = {(t[0].get("symbol") or "").upper() for t in shown}

    (picked, excluded_adverse, capped, gave_way, per_sector,
     universe, considered) = _choose_picks(rows_all, key, limit, hours, exclude)
    # A scan ranked under an earlier recipe (made before the last deploy) still
    # answers, but the tested record printed beside it would be another list's.
    stamps = _stamps(rows_all)
    recipe_current = stamps == {leaders.RECIPE}
    # And the study file must have measured the recipe this scan ran.
    study_current = _study_current(key)
    show_record = recipe_current and study_current
    chosen = []
    for r, entry, filing, adverse in picked:
        sym = (r.get("symbol") or "").upper()
        block = r.get("leader") or {}
        row = dict(r)
        tier, warn = liquidity_tier(row.get("avg_turnover_cr"))
        srow = _sector_row(outlook, row.get("sector"))
        row.update({
            "list": key,
            "chart_setup": row.get("setup"), "chart_setup_key": row.get("setup_key"),
            "setup": spec["setup"], "setup_key": spec["setup_key"],
            "horizon": spec["hold_text"],
            "liquidity_tier": tier, "liquidity_note": warn,
            "tracked": sym in tracked,
            "pick_rank": entry["rank"],
            "young": bool(block.get("young")),
            "conviction": entry["score"], "rank_score": entry["score"],
            "why": entry.get("why") or [],
            # The breakout pattern, for the badge on a breakout pick.
            "pattern": breakout_pattern(block) if key == "breakout" else None,
            "evidence": _pick_evidence(key, block),
            "plan": leaders.plan(key, row.get("price"), called_on),
            "catalyst": filing, "filing": filing, "adverse_filing": adverse,
            # The result this stock was last priced on (ranked on, for the
            # results list; a dated fact on every other).
            "results": block.get("results"),
            # An order it disclosed lately, with its size against the
            # company's market value. A fact beside the pick; not ranked.
            "order": _order_for(sym),
            # The chart and the tape, as facts (see CHART_NOTE).
            "technicals": block.get("technicals"),
            "chart": chart_facts(block.get("technicals"), block.get("facts"),
                                 row.get("chart_pattern"), row.get("price")),
            "news": (news_idx.get(sym) or [])[:3],
            "sector_outlook": ({"state": srow.get("state"), "index_name": srow.get("index_name"),
                                "rel_3m": (srow.get("relative") or {}).get("3M"),
                                "rel_1m": (srow.get("relative") or {}).get("1M"),
                                "above_200dma_pct": srow.get("above_200dma_pct"),
                                "why": srow.get("state_why")} if srow else None),
            # Its sector on Money Flow. A fact beside the pick; not ranked.
            "sector_tailwind": sector_tailwind(sym),
        })
        if key in CATALYST_LISTS:
            # An order, an earnings call, a week's news: live facts, untested,
            # that move a pick up its list and never put one on it.
            row["catalysts"] = catalysts(sym, row["news"], row["order"])
        band = "High" if entry["score"] >= 85 else ("Moderate" if entry["score"] >= 70 else "Speculative")
        row["conviction_band"] = band
        row["conviction_why"] = f"Ranked {entry['rank']} of the stocks that passed every gate."
        row["thesis"] = spec["idea"]
        chosen.append(row)

    if key in CATALYST_LISTS and any(r.get("catalysts") for r in chosen):
        # Picks with a fresh catalyst first, the strongest first; the rest keep
        # the list's own order. Which stocks are on the list does not change.
        chosen.sort(key=lambda r: (-((r.get("catalysts") or {}).get("score") or 0.0), r["pick_rank"]))
    notes = []
    if key in CATALYST_LISTS and any(r.get("catalysts") for r in chosen):
        notes.append("Picks with a fresh catalyst (an order worth 1% or more of the company, an earnings "
                     "call, a week's news) are shown first. Catalysts were not part of the test: there is "
                     "no history of them to test on, so they reorder the list and never choose it.")
    if excluded_adverse:
        notes.append("Removed for a serious adverse filing: "
                     + ", ".join(f"{e['symbol']} ({e['category']})" for e in excluded_adverse[:4]) + ".")
    caps = money_flow_caps()
    if capped:
        notes.append(f"{capped} more qualified but would have put more than "
                     f"{PICK_SECTOR_CAP} names in one sector."
                     if not caps.get("on") else
                     f"{capped} more qualified but would have put too many names in one sector "
                     f"(the cap is {caps.get('top')} for a sector in the top quarter on money "
                     f"flow, {caps.get('bottom')} for the bottom quarter, {PICK_SECTOR_CAP} otherwise).")
    if other in leaders.LISTS:
        notes.append(f"Stocks on the {leaders.LISTS[other]['label'].lower()} list are left off "
                     "this one, so the two lists show different stocks.")
    if not recipe_current:
        # Only the three lists by holding time were rebuilt: a setup list's
        # picks are chosen as they were, and only its record is held back.
        notes.append("This scan was ranked with an earlier recipe: these picks were chosen the earlier "
                     "way, not as described above, and its tested record is not shown. The next scan "
                     "ranks it the current way." if leaders.recipe_of(key) is not None else
                     "This scan was ranked with an earlier recipe, so its tested record is not shown. "
                     "The next scan ranks it the current way.")
    elif not study_current:
        notes.append("This list was rebuilt on company filings in December 2026 and the replay of the new "
                     "recipe is not in the study file yet, so no tested record is shown beside it.")
    event = spec.get("event") == "results"
    held = [((r.get("leader") or {}).get("results") or {}) for r in rows_all]
    reported = max([h.get("reported") or 0 for h in held] or [0])
    qualified = max([h.get("qualified") or 0 for h in held] or [0])
    empty_text = "Nothing passed every test in this scan."
    # An earlier recipe counted no results against the tests above, so its
    # counts would say none passed them.
    if event and not chosen and recipe_current:
        empty_text = _results_empty_text(reported, qualified, called_on)
    setup = spec.get("kind") == "setup"
    if setup and not chosen:
        empty_text = SETUP_EMPTY.get(key, empty_text)
    if setup and chosen and SETUP_NOTE.get(key):
        notes.append(SETUP_NOTE[key])
    young_shown = [r.get("symbol") for r in chosen if (r.get("leader") or {}).get("young")]
    if young_shown and not setup:
        notes.append("Listed under a year, ranked on six months of prices in place of twelve: "
                     + ", ".join(young_shown[:6]) + ". In the test such companies led the average "
                     "stock on this list in both halves.")
    if event and chosen and recipe_current:
        notes.append(f"{reported} liquid companies had results priced in the last "
                     f"{leaders.RESULTS_WINDOW} sessions and {qualified} passed every test of real growth; "
                     "these are ranked on the day's move against the average stock, the volume behind it "
                     "and the growth itself.")
    if not chosen:
        notes.append(empty_text)

    return {
        "available": True,
        "degraded": [],
        "method_key": "tested_lists",
        "list": key,
        "horizon": key,
        "label": spec["label"],
        "idea": spec["idea"],
        "hold_text": spec["hold_text"],
        "exit_pct": spec["exit_pct"],
        "note": spec["idea"],
        "horizon_note": ((f"{spec['idea']} Sell at the first close above the 5-day average or after "
                          f"{spec['hold_sessions']} sessions; leave on a close {spec['exit_pct']:.0f}% under the call price.")
                         if spec.get("sell_rule") == "sma5" else
                         (f"{spec['idea']} Hold {spec['hold_text']}; after the first "
                          f"{spec.get('trail_after', 15)} sessions sell on a close under the 50-day average; "
                          f"leave at any time on a close {spec['exit_pct']:.0f}% under the call price.")
                         if spec.get("sell_rule") == "sma50" else
                         (f"{spec['idea']} Hold {spec['hold_text']}; leave on a close "
                          f"{spec['exit_pct']:.0f}% under the call price.")),
        "tested": tested_record(key) if show_record else None,
        # Each pick carries a mark above its price (plan.aim). This is what the
        # study found on selling there, for the lists it tested that way.
        "target_test": leaders.target_tested(key) if show_record else None,
        "recipe_current": recipe_current,
        # The stamp the rows were ranked under, so the call log can date a
        # rebuilt list from its first scan (call_log.recipe_since).
        "recipe": next(iter(stamps)) if len(stamps) == 1 else None,
        "study_current": study_current,
        # The study's header only. Its tables are in research/ideas-study.json;
        # sending them with every list would triple the response for nobody.
        "study": {k: (leaders.TESTED or {}).get(k) for k in
                  ("generated", "source", "from", "to", "sessions", "companies",
                   "universe", "universe_median", "rules")},
        "lists": [{"key": k, "label": leaders.LISTS[k]["label"],
                   "hold_text": leaders.LISTS[k]["hold_text"],
                   "group": "setup" if k in leaders.SETUPS else "horizon"} for k in leaders.ALL],
        "kind": spec.get("kind") or "horizon",
        "sell_rule": spec.get("sell_rule"),
        # Every sector ranked on money flow, for the money-flow list's table.
        "sector_flow": (payload.get("sector_flow") or []) if key == "flow" else None,
        "flow_sectors": leaders.FLOW_SECTORS if key == "flow" else None,
        # Tight bases not yet broken, nearest their top first: the breakout
        # list's waiting room. Watched, not picked.
        "watch": (_watch_with_catalysts(payload.get("breakout_watch") or [], news_idx) if key == "breakout" else
                  # A scan from before December 2026 has no short_watch; its
                  # breakout_watch was the short list's own.
                  (payload.get("short_watch") if "short_watch" in payload else payload.get("breakout_watch") or [])
                  if key == "short" else None),
        "primary": [{"key": k, "label": leaders.LISTS[k]["label"]} for k in leaders.PRIMARY],
        "scanned_at": payload.get("scanned_at"),
        "staleness": stale,
        "partial": bool(payload.get("partial")),
        "scored": payload.get("scored"),
        "universe_source": payload.get("universe_source"),
        "universe": universe,
        "regime": regime,
        # What the test found for this list in a market like today's. The page
        # shows this where it used to show a warning the test did not bear out.
        "market_test": market_test(key, regime) if show_record else None,
        # On a setup list the chart IS the reason, so the disclaimer is dropped.
        "chart_note": None if spec.get("kind") == "setup" else CHART_NOTE,
        "empty_text": None if chosen else empty_text,
        "event": spec.get("event"),
        "market_context": {"regime": regime, "leaders": _leaders[0], "laggards": _leaders[1],
                           "sectors_measured": _leaders[2], "headlines": headlines},
        "weights": leaders.mix_of(key),
        "conviction_floor": 0,
        "layers": {"sector_outlook": bool(outlook), "market_regime": bool(regime),
                   "news": bool(news_idx or headlines), "filings": ann is not None,
                   "track_record": False},
        "sector_mix": sorted(per_sector.items(), key=lambda kv: -kv[1]),
        "sector_cap": PICK_SECTOR_CAP,
        "money_flow_caps": caps,
        "expectancy_applied": False,
        "selection_notes": notes,
        "excluded_adverse": excluded_adverse,
        "rows": chosen,
        "count": len(chosen),
        "considered": considered,
        "gives_way_to": other if other in leaders.LISTS else None,
        "gave_way": gave_way,
        "method": (SETUP_METHOD[key] if key in SETUP_METHOD else
                   _tab_method(key) or
                   ("Every liquid NSE stock is ranked on the measurements in the ledger. "
                    "The list is the top of that ranking after its gates.")),
    }


def select(payload: dict, horizon: str = "short", limit: int = 15,
           min_tier: str = "moderate", include_thin: bool = False,
           min_conviction: float = None) -> dict:
    """
    Build the Ideas list from an existing scan payload.

    Returns fewer rows than `limit` when fewer genuinely qualify. That is the
    point: an empty week is information, and padding destroys it.
    """
    # A scan that carries leader ranks serves the tested lists. A scan
    # from before they existed still answers with the old short and medium
    # lists, so a deploy never blanks the page while the next scan runs.
    key = leaders.resolve(horizon) if leaders is not None else None
    if key and has_picks(payload):
        return select_picks(payload, key, limit=limit)
    if key and horizon not in HORIZONS:
        # The old short list held what the weeks-to-months names meant when
        # that scan was made; week and momentum now resolve to month and
        # long, so they are read by the name they were asked for.
        asked = str(horizon or "").strip().lower()
        horizon = "short" if (key in ("month", "short") or asked in _LEGACY_SHORT_NAMES) else "medium"
    h = HORIZONS.get(horizon)
    if not h:
        raise ValueError("horizon must be one of " + ", ".join(leaders.ALL if leaders is not None else HORIZONS))

    floor = MIN_CONVICTION if min_conviction is None else float(min_conviction)
    weights = h["weights"]
    rankings = payload.get("rankings") or []

    # Each of these reaches a feed. None of them may hold the request open —
    # see the deadline note above. A feed that misses its deadline scores
    # neutral and is named in the notes, exactly as a feed that raises does.
    regime, regime_ok = _soft("regime", market_regime, None)
    outlook, outlook_ok = _soft("sector_outlook", sector_outlook, {})
    (news_idx, headlines), news_ok = _soft(
        "news", lambda: _news_index(h["news_hours"]), ({}, []))
    slow = [name for name, ok in (("market regime", regime_ok),
                                  ("sector outlook", outlook_ok),
                                  ("news", news_ok)) if not ok]
    # Local reads — the ledger is on disk, so these are not on a deadline. They
    # ARE guarded, which they were not: these two were the only calls in this
    # function that could take the whole endpoint down, because every other
    # feed here already fails soft. A ledger that will not parse should cost
    # the track-record factor and the Tracking labels, not the Ideas tab.
    try:
        record = tracker.expectancy_detail() if tracker else {}
    except Exception:
        record = {}
    # "manual" on purpose: the Add button must reflect YOUR tracker. Counting
    # the scanner's automatic rows marked names as tracked that the user had
    # never added and could not see in their own list.
    try:
        tracked = tracker.tracked_symbols(source="manual") if tracker else set()
    except Exception:
        tracked = set()
    stale = _staleness(payload.get("scanned_at"))
    _leaders = _leaders_laggards(outlook)

    stale_penalty = 0.0
    if stale and stale.get("days"):
        stale_penalty = min(h["max_stale_penalty"],
                            max(0, stale["days"] - STALE_DAYS) * h["stale_penalty_per_day"])

    max_rank = TIER_RANK.get(min_tier, 1)
    if include_thin:
        max_rank = 3

    pool, dropped_thin, dropped_unknown = [], 0, 0
    excluded_adverse = []
    for r in rankings:
        if r.get("setup_key") not in h["keys"]:
            continue
        tier, warn = liquidity_tier(r.get("avg_turnover_cr"))
        if TIER_RANK[tier] > max_rank:
            if tier == "unknown":
                dropped_unknown += 1
            else:
                dropped_thin += 1
            continue

        row = dict(r)
        sym = (row.get("symbol") or "").upper()
        key = row.get("setup_key")
        row["liquidity_tier"] = tier
        row["liquidity_note"] = warn
        row["tracked"] = sym in tracked

        # ---- the seven factors, each 0..1 with its own sentence -------------
        fit = _fit_of(row)
        fit_q = max(0.0, min(1.0, fit / 100.0))
        comp = row.get("composite")
        comp_q = max(0.0, min(1.0, (float(comp) if comp is not None else 0) / 100.0))

        srow = _sector_row(outlook, row.get("sector"))
        sec_q, sec_why = _sector_quality(srow, horizon)

        reg_q, reg_why = _regime_quality(regime, key)

        filing = _filing_for(sym, h["news_hours"], h["catalyst_categories"])
        stories = news_idx.get(sym) or []
        cat_q, cat_why, cat_stories, adverse = _catalyst_quality(filing, stories, h["news_hours"])

        if adverse and (filing or {}).get("importance") in HARD_EXCLUDE_ADVERSE:
            excluded_adverse.append({
                "symbol": sym, "name": row.get("name"),
                "category": filing.get("category"),
                "headline": filing.get("headline"),
                "line": filing.get("line"),
                "setup_fit": row.get("setup_fit"),
            })
            continue

        liq_q = TIER_QUALITY.get(tier, 0.4)
        rec_q, rec_why = _record_quality(record, key)

        factors = [
            ("Setup fit", "fit", fit_q, f"Fit {round(fit)}/100 against the {row.get('setup') or 'archetype'} template."),
            ("Engine composite", "composite", comp_q,
             f"Composite {comp if comp is not None else '—'}/100 from the technical and fundamental engines."),
            ("Sector outlook", "sector", sec_q, sec_why),
            ("Market regime", "regime", reg_q, reg_why),
            ("Catalyst", "catalyst", cat_q, cat_why),
            ("Liquidity", "liquidity", liq_q, warn),
            ("Archetype record", "record", rec_q, rec_why),
        ]

        evidence, total = [], 0.0
        for label, wkey, q, why in factors:
            w = weights[wkey]
            pts = round(q * w, 1)
            total += pts
            evidence.append({"factor": label, "points": pts, "of": w,
                             "share_pct": round(q * 100), "detail": why})

        # Never take off more than the row scored: clipping the total at zero
        # afterwards would leave the ledger adding up to something other than
        # the number printed beside it, which is exactly the kind of quiet
        # inconsistency an audit trail exists to prevent.
        applied = min(stale_penalty, total)
        conviction = round(total - applied, 1)
        if applied:
            evidence.append({"factor": "Scan freshness", "points": -round(applied, 1),
                             "of": 0, "share_pct": None,
                             "detail": (stale or {}).get("text", "")})

        v4 = row.get("altaha_score_v4")
        if v4:
            row["legacy_conviction"] = conviction
            hz = "trade" if horizon == "short" else "position"
            # v4 already rounds its published score; round again here so this
            # branch can never reintroduce the precision the legacy branch
            # above deliberately drops with round(total - applied, 1).
            conviction = round(v4[hz]["final_score"], 1)
            evidence = [{"factor": "Altaha Score v4", "points": conviction, "of": 100,
                         "share_pct": round(conviction),
                         "detail": f"{hz} score; confidence {v4[hz]['confidence']:.1%}; peer-relative as of {v4.get('as_of')}"}]
        band, band_why = _band(conviction)
        row["conviction"] = conviction
        row["conviction_band"] = band
        row["conviction_why"] = band_why
        row["evidence"] = evidence
        row["sector_outlook"] = ({"state": srow.get("state"),
                                  "index_name": srow.get("index_name"),
                                  "rel_3m": (srow.get("relative") or {}).get("3M"),
                                  "rel_1m": (srow.get("relative") or {}).get("1M"),
                                  "above_200dma_pct": srow.get("above_200dma_pct"),
                                  "why": srow.get("state_why")} if srow else None)
        row["catalyst"] = filing
        # Kept under its original name too: the row template and anything else
        # reading the old payload still looks for `filing`.
        row["filing"] = filing
        row["news"] = cat_stories
        row["adverse_filing"] = bool(adverse)
        if A is not None and key in getattr(A, "ARCHETYPES", {}):
            arch = A.ARCHETYPES[key]
            row["watch_for"] = arch["invalidation"][:3]
            row["thesis"] = arch["thesis"]
            row["risks"] = arch["risks"]

        # Kept for anything still reading the old field names.
        row["expectancy_alpha_pct"] = (record.get(key) or {}).get("avg_alpha_pct") \
            if (record.get(key) or {}).get("reliable") else None
        row["rank_score"] = conviction
        pool.append(row)

    below_floor = sum(1 for r in pool if r["conviction"] < floor)
    qualified = [r for r in pool if r["conviction"] >= floor]
    qualified.sort(key=lambda r: (r["conviction"], _fit_of(r), r.get("composite") or 0),
                   reverse=True)

    # Sector cap. Fifteen ideas that are really one sector bet is the failure
    # mode the Portfolio tab already warns users about; the Ideas tab should not
    # be exempt from its own rule.
    chosen, per_sector, capped = [], {}, 0
    for r in qualified:
        if len(chosen) >= limit:
            break
        sec = r.get("sector") or "Unknown"
        if per_sector.get(sec, 0) >= sector_cap_for(r.get("symbol"), SECTOR_CAP):
            capped += 1
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
        r["sector_tailwind"] = sector_tailwind(r.get("symbol"))
        chosen.append(r)

    # Regime warning on trend-dependent setups, applied per row so the reader
    # sees it where the decision is made rather than in a banner they scroll past.
    if regime and not regime["ok"]:
        for r in chosen:
            if r.get("setup_key") in TREND_DEPENDENT:
                r["regime_warning"] = (
                    f"Index is {abs(regime['pct_vs_50dma']):.1f}% below its 50-day average. "
                    "Breakout setups fail more often in this regime.")

    notes = []
    if excluded_adverse:
        n = len(excluded_adverse)
        notes.append(f"{n} name{'s' if n > 1 else ''} matching the setup {'were' if n > 1 else 'was'} "
                     "removed for a serious adverse filing in the window: "
                     + ", ".join(f"{e['symbol']} ({e['category']})" for e in excluded_adverse[:4])
                     + ". These are listed under 'removed for filings' rather than shown with a "
                       "warning, because a live regulatory action is not a setup with a caveat.")
    if below_floor:
        notes.append(f"{below_floor} name{'s' if below_floor > 1 else ''} matched the setup but "
                     f"scored under the {floor:.0f}-point conviction floor once sector, regime, "
                     "liquidity and news were taken into account.")
    if capped:
        notes.append(f"{capped} further name{'s' if capped > 1 else ''} met the setup but were "
                     f"held back by the {SECTOR_CAP}-per-sector cap.")
    if dropped_thin:
        notes.append(f"{dropped_thin} qualifying name{'s' if dropped_thin > 1 else ''} "
                     "excluded for thin liquidity. Switch on 'include thin' to see them.")
    if dropped_unknown:
        notes.append(f"{dropped_unknown} name{'s' if dropped_unknown > 1 else ''} excluded because "
                     "turnover could not be measured at all.")
    if len(chosen) < 5:
        notes.append("Few clean setups exist right now. The list is short because it is honest, "
                     "not because the scan failed.")

    layers = {
        "sector_outlook": bool(outlook),
        "market_regime": bool(regime),
        "news": bool(news_idx or headlines),
        "filings": ann is not None,
        "track_record": any(v.get("reliable") for v in record.values()) if record else False,
    }
    missing = [k.replace("_", " ") for k, v in layers.items() if not v]
    if missing:
        notes.append("Scored without " + ", ".join(missing) +
                     ". That feed was unavailable, so those factors scored neutral rather "
                     "than being guessed at.")
    if slow:
        notes.append("The " + ", ".join(slow) + " feed did not answer within "
                     f"{IDEAS_FEED_DEADLINE:.0f} seconds and is still loading. It is being "
                     "fetched now, so reload in a moment for the full picture rather than a "
                     "list that was scored without it.")

    return {
        "available": True,
        # Which feeds missed their deadline on THIS request. Empty is the
        # normal case; non-empty means the list is complete but under-informed,
        # and the caller can say so instead of presenting it as final.
        "degraded": slow,
        "horizon": horizon,
        "label": h["label"],
        "note": h["note"],
        "horizon_note": h["horizon_note"],
        "scanned_at": payload.get("scanned_at"),
        "staleness": stale,
        "partial": bool(payload.get("partial")),
        "scored": payload.get("scored"),
        "universe_source": payload.get("universe_source"),
        "regime": regime,
        "market_context": {
            "regime": regime,
            "leaders": _leaders[0],
            "laggards": _leaders[1],
            "sectors_measured": _leaders[2],
            "headlines": headlines,
        },
        "weights": weights,
        "conviction_floor": floor,
        "layers": layers,
        "sector_mix": sorted(per_sector.items(), key=lambda kv: -kv[1]),
        "sector_cap": SECTOR_CAP,
        "money_flow_caps": money_flow_caps(),
        "expectancy_applied": bool(record),
        "selection_notes": notes,
        "excluded_adverse": excluded_adverse,
        "rows": chosen,
        "count": len(chosen),
        "considered": len(pool),
        "method": ("Every row is scored out of 100 across seven factors weighted for this "
                   "horizon: setup fit, engine composite, sector outlook, market regime, "
                   "catalyst, liquidity and the archetype's measured record. Open a row to see "
                   "the points each factor contributed. A factor whose feed is unavailable "
                   "scores neutral and says so."),
    }
