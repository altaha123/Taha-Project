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
import os

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
    from data_source import resolve as _resolve
except Exception:
    _resolve = None

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
                 "These decay fastest — re-scan often."),
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
        return "unknown", "Turnover unknown — treat position size with caution."
    try:
        t = float(turnover_cr)
    except (TypeError, ValueError):
        return "unknown", "Turnover unknown — treat position size with caution."
    if t >= 10:
        return "liquid", "Trades freely — entry and exit costs are small."
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
                    label = ("Index comfortably above its 50-day average — trend setups have "
                             "tailwind.")
                elif pct >= 0:
                    stance = "Mixed"
                    label = "Index just above its 50-day average — mixed, not yet hostile."
                elif pct >= -3:
                    stance = "Headwind"
                    label = ("Index below its 50-day average — trend setups fail more often here, "
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
        return 0.6, "Index trend unavailable — this factor scored neutral rather than assumed."
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
        return 1.0, f"Index {pct:+.1f}% above its 50-day average — trend continuation has tailwind."
    if pct >= 0:
        return 0.78, f"Index {pct:+.1f}% above its 50-day average — workable, not strong."
    if pct >= -3:
        return 0.42, f"Index {pct:+.1f}% below its 50-day average — breakouts fail more often here."
    return 0.15, (f"Index {pct:+.1f}% below its 50-day average — the worst regime for this setup, "
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
        return 0.55, "No sector index maps to this name — scored neutral, not assumed."
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
                f"Adverse filing: {filing.get('category')} — {filing.get('line')}. "
                "Scored against this idea, not for it.",
                fresh, True)

    if filing and filing.get("direction") == "supportive":
        q = _FILING_SUPPORT.get(filing.get("importance"), 0.5)
        return (q, f"{filing.get('category')} filed with the exchange — {filing.get('line')}.",
                fresh, False)

    if filing:      # an "event": real, dated, but direction unknown from the tag
        q = 0.5 * _FILING_SUPPORT.get(filing.get("importance"), 0.5) + 0.25
        return (q, (f"{filing.get('category')} filed with the exchange — {filing.get('line')}. "
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
                + (" — all of it speculative wording." if speculative else "."))
        return max(0.0, min(q, 0.8)), note, fresh, False

    return 0.35, "No filing or press inside the window — a quiet name, which is neutral.", [], False


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------

def _record_quality(detail, setup_key):
    d = (detail or {}).get(setup_key)
    if not d or not d.get("reliable"):
        n = (d or {}).get("ideas", 0)
        return 0.5, (f"Only {n} closed idea{'s' if n != 1 else ''} for this archetype so far — "
                     "not enough to say anything, so this factor scored neutral.")
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
            "text": (f"Scanned {age} days ago. Short-term setups decay in days — "
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
    outlook = sector_outlook()
    leaders, laggards, measured = _leaders_laggards(outlook)
    _idx, headlines = _news_index(HORIZONS.get(horizon, HORIZONS["short"])["news_hours"])
    return {
        "regime": market_regime(),
        "leaders": leaders,
        "laggards": laggards,
        "sectors_measured": measured,
        "headlines": headlines,
        "sector_method": ("Relative strength is the sector index return minus the Nifty 50 return "
                          "over the identical window. State compares 3-month relative strength "
                          "against 6-month, so a sector can be behind and still improving."),
    }


def select(payload: dict, horizon: str = "short", limit: int = 15,
           min_tier: str = "moderate", include_thin: bool = False,
           min_conviction: float = None) -> dict:
    """
    Build the Ideas list from an existing scan payload.

    Returns fewer rows than `limit` when fewer genuinely qualify. That is the
    point: an empty week is information, and padding destroys it.
    """
    h = HORIZONS.get(horizon)
    if not h:
        raise ValueError("horizon must be 'short' or 'medium'")

    floor = MIN_CONVICTION if min_conviction is None else float(min_conviction)
    weights = h["weights"]
    rankings = payload.get("rankings") or []

    regime = market_regime()
    outlook = sector_outlook()
    news_idx, headlines = _news_index(h["news_hours"])
    record = tracker.expectancy_detail() if tracker else {}
    # "manual" on purpose: the Add button must reflect YOUR tracker. Counting
    # the scanner's automatic rows marked names as tracked that the user had
    # never added and could not see in their own list.
    tracked = tracker.tracked_symbols(source="manual") if tracker else set()
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
        if per_sector.get(sec, 0) >= SECTOR_CAP:
            capped += 1
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
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
                     "removed for a serious adverse filing in the window — "
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
                     "excluded for thin liquidity — switch on 'include thin' to see them.")
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
                     " — that feed was unavailable, so those factors scored neutral rather "
                     "than being guessed at.")

    return {
        "available": True,
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
