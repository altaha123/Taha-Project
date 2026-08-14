"""
Altaha Screener — Idea Selection

The old /ideas endpoint filtered the ranking by archetype, sorted by fit, cut
at 15, and — if fewer than eight names matched — quietly padded the list with
the highest composites regardless of setup. Four things were wrong with that.

  1. It was loudest when it should have been quietest. A market with no clean
     setups produced fifteen rows anyway, because the padding only triggered
     when real matches were scarce.

  2. Fifteen momentum names in a hot tape cluster into two or three sectors.
     That is one bet with fifteen tickers, and it is the most likely mechanical
     explanation for a whole idea list falling together.

  3. Fit measures how neatly a stock matches a template. It says nothing about
     whether the template works. Ranking by fit ranks tidiness.

  4. Nothing knew what the market was doing. Momentum breakouts fail far more
     often below the index's 50-day average, and the engine had no idea.

This module fixes those four. It is deliberately a selection layer over the
existing scan payload — no rescanning, no new data source, no new cost.
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

BENCHMARK = os.environ.get("INDEX_PROXY", "NIFTYBEES").strip().upper()

SECTOR_CAP = int(os.environ.get("IDEAS_SECTOR_CAP", "3") or 3)
STALE_DAYS = int(os.environ.get("IDEAS_STALE_DAYS", "3") or 3)

HORIZONS = {
    "short": {
        "keys": ["momentum_breakout", "institutional_accumulation"],
        "label": "Short-term setups",
        "note": ("Setups whose premise plays out in weeks to a few months: strong trends with "
                 "volume behind them, and accumulation footprints that haven't fully moved yet. "
                 "These decay fastest — re-scan often."),
    },
    "medium": {
        "keys": ["quality_at_discount", "turnaround"],
        "label": "Medium-term setups",
        "note": ("Setups whose premise needs quarters, not weeks: quality businesses in a "
                 "drawdown, and companies whose fundamentals are inflecting. Judged mainly on "
                 "filings, so re-check after each results season."),
    },
}

# Archetypes that depend on trend continuation. These are the ones that fail
# disproportionately when the index itself is under its 50-day average.
TREND_DEPENDENT = {"momentum_breakout", "institutional_accumulation"}

_regime_cache = {"day": None, "value": None}


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
    t = float(turnover_cr)
    if t >= 10:
        return "liquid", "Trades freely — entry and exit costs are small."
    if t >= 2:
        return "moderate", "Reasonable depth, but large orders will move the price."
    if t >= 0.5:
        return "thin", "Thin. Expect slippage; a full exit may take several days."
    return "untradeable", ("Barely trades. Wide spreads and a real chance you cannot exit "
                           "at anything near the screen price.")


TIER_RANK = {"liquid": 0, "moderate": 1, "thin": 2, "untradeable": 3, "unknown": 2}


# ---------------------------------------------------------------------------
# Market regime
# ---------------------------------------------------------------------------

def market_regime():
    """
    {'ok': bool, 'pct_vs_50dma': float, 'label': str} or None when unavailable.
    One Dhan call a day, cached.
    """
    today = dt.date.today().isoformat()
    if _regime_cache["day"] == today and _regime_cache["value"] is not None:
        return _regime_cache["value"]
    out = None
    try:
        if dhan is not None and dhan.configured():
            df = dhan.daily_ohlcv(BENCHMARK, days=200)
            if df is not None and len(df) > 60:
                close = df["Close"].dropna()
                ma50 = float(close.rolling(50).mean().iloc[-1])
                last = float(close.iloc[-1])
                pct = (last - ma50) / ma50 * 100
                if pct >= 2:
                    label = "Index comfortably above its 50-day average — trend setups have tailwind."
                elif pct >= 0:
                    label = "Index just above its 50-day average — mixed, not yet hostile."
                elif pct >= -3:
                    label = ("Index below its 50-day average — trend setups fail more often here, "
                             "so momentum ideas are shown with a warning.")
                else:
                    label = ("Index well below its 50-day average. Breakouts fail at a much higher "
                             "rate in this regime; short-term ideas are suppressed.")
                out = {"ok": pct >= 0, "pct_vs_50dma": round(pct, 2), "label": label}
    except Exception:
        out = None
    _regime_cache["day"] = today
    _regime_cache["value"] = out
    return out


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _staleness(scanned_at):
    """Ideas carry a date. A momentum idea nine days old is a different object
    from a fresh one, and the old UI showed them identically."""
    if not scanned_at:
        return None
    for fmt in ("%d %b %Y, %H:%M", "%d %b %Y"):
        try:
            d = dt.datetime.strptime(scanned_at.split(" (")[0], fmt)
            age = (dt.datetime.now() - d).days
            if age <= 0:
                return {"days": 0, "warn": False, "text": "Scanned today."}
            if age <= STALE_DAYS:
                return {"days": age, "warn": False,
                        "text": f"Scanned {age} day{'s' if age > 1 else ''} ago."}
            return {"days": age, "warn": True,
                    "text": (f"Scanned {age} days ago. Short-term setups decay in days — "
                             "re-run the universe scan before acting on these.")}
        except Exception:
            continue
    return None


def select(payload: dict, horizon: str = "short", limit: int = 15,
           min_tier: str = "moderate", include_thin: bool = False) -> dict:
    """
    Build the Ideas list from an existing scan payload.

    Returns fewer rows than `limit` when fewer genuinely qualify. That is the
    point: an empty week is information, and padding destroys it.
    """
    h = HORIZONS.get(horizon)
    if not h:
        raise ValueError("horizon must be 'short' or 'medium'")

    rankings = payload.get("rankings") or []
    regime = market_regime()
    expectancy = tracker.expectancy_by_archetype() if tracker else {}

    max_rank = TIER_RANK.get(min_tier, 1)
    if include_thin:
        max_rank = 3

    pool, dropped_thin = [], 0
    for r in rankings:
        if r.get("setup_key") not in h["keys"]:
            continue
        tier, warn = liquidity_tier(r.get("avg_turnover_cr"))
        if TIER_RANK[tier] > max_rank:
            dropped_thin += 1
            continue
        row = dict(r)
        row["liquidity_tier"] = tier
        row["liquidity_note"] = warn

        # Rank on fit adjusted by what this archetype has actually delivered.
        # Until roughly 20 marked ideas exist for an archetype the adjustment is
        # neutral, so early behaviour is identical to plain fit ranking.
        fit = float(r.get("setup_fit") or r.get("composite") or 0)
        adj = expectancy.get(r.get("setup_key"))
        row["expectancy_alpha_pct"] = adj
        row["rank_score"] = round(fit * (1 + (adj / 100.0)), 1) if adj is not None else round(fit, 1)
        pool.append(row)

    pool.sort(key=lambda r: (r["rank_score"], r.get("composite") or 0), reverse=True)

    # Sector cap. Fifteen ideas that are really one sector bet is the failure
    # mode the Portfolio tab already warns users about; the Ideas tab should not
    # be exempt from its own rule.
    chosen, per_sector, capped = [], {}, 0
    for r in pool:
        sec = r.get("sector") or "Unknown"
        if per_sector.get(sec, 0) >= SECTOR_CAP:
            capped += 1
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
        chosen.append(r)
        if len(chosen) >= limit:
            break

    # Attach any filing from the last three days. A score that jumped because
    # the company won an order is a different object from one that drifted up,
    # and the old tab could not tell the reader which had happened.
    if ann is not None:
        try:
            for r in chosen:
                t = ann.tag(r.get("symbol", ""), minutes=72 * 60)
                if t:
                    r["filing"] = t
        except Exception:
            pass

    # Regime warning on trend-dependent setups, applied per row so the reader
    # sees it where the decision is made rather than in a banner they scroll past.
    if regime and not regime["ok"]:
        for r in chosen:
            if r.get("setup_key") in TREND_DEPENDENT:
                r["regime_warning"] = (
                    f"Index is {abs(regime['pct_vs_50dma']):.1f}% below its 50-day average. "
                    "Breakout setups fail more often in this regime.")

    notes = []
    if capped:
        notes.append(f"{capped} further name{'s' if capped > 1 else ''} met the setup but were "
                     f"held back by the {SECTOR_CAP}-per-sector cap.")
    if dropped_thin:
        notes.append(f"{dropped_thin} qualifying name{'s' if dropped_thin > 1 else ''} "
                     "excluded for thin liquidity — switch on 'include thin' to see them.")
    if len(chosen) < 5:
        notes.append("Few clean setups exist right now. The list is short because it is honest, "
                     "not because the scan failed.")

    return {
        "available": True,
        "horizon": horizon,
        "label": h["label"],
        "note": h["note"],
        "scanned_at": payload.get("scanned_at"),
        "staleness": _staleness(payload.get("scanned_at")),
        "partial": bool(payload.get("partial")),
        "scored": payload.get("scored"),
        "universe_source": payload.get("universe_source"),
        "regime": regime,
        "sector_mix": sorted(per_sector.items(), key=lambda kv: -kv[1]),
        "sector_cap": SECTOR_CAP,
        "expectancy_applied": bool(expectancy),
        "selection_notes": notes,
        "rows": chosen,
        "count": len(chosen),
    }
