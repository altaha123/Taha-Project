"""
The daily portfolio digest — what happened to the stocks somebody owns.

WHAT THIS IS FOR
A person who has told us what they hold should not have to come and look. Once
a day, after the close, this assembles the answer to "what happened to my
money today, and does anything need my attention" — and something else sends
it. Email first; the channel is deliberately not this file's business.

FACTS, NEVER VERDICTS
Nothing here says buy or sell, and nothing here should learn to. Telling the
public what to trade is investment advice, which in India needs SEBI
registration this project does not have — the README has said so from the
start. So a line reads "crossed above its 50-day average" or "closed at a
52-week high": observations a reader can check against their own chart, and
act on with their own judgement. That is also the better product. A verdict
ages badly; a fact does not.

RANKED BY RUPEES, NOT PERCENT
The movers list is ordered by what each holding CONTRIBUTED to the day in
rupees. A 9% jump in a position worth ₹4,000 is not the story when a 1% slip
in a ₹6 lakh position quietly took more away. Percent is what a screener
shows; rupees is what the holder felt.

ONE FETCH PER SYMBOL
symbol_facts_bulk() takes the whole set of symbols at once and returns a dict
keyed by symbol, so a hundred subscribers who all hold RELIANCE cost one
lookup rather than a hundred. That is the difference between a job that
finishes on a 512 MB instance and one that does not — and it is much harder to
retrofit than to build in now.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# How far back a filing still counts as "today's news". The digest goes out
# after the close; a filing from yesterday evening is news the reader has not
# seen yet, so the window is a day and a half rather than a calendar day.
FILING_WINDOW_MINUTES = 36 * 60


def _num(v):
    try:
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _sym(s) -> str:
    return str(s or "").strip().upper().replace(".NS", "").replace(".BO", "")


# ---------------------------------------------------------------------------
# Per-symbol facts
# ---------------------------------------------------------------------------

def _observations(df) -> list:
    """Plain observations from one daily frame. Each is checkable on a chart.

    Every one of these is computed from the SAME frame that priced the
    holding, so the whole digest costs one history fetch per symbol.
    """
    out = []
    try:
        close = df["Close"].dropna()
        if len(close) < 2:
            return out
        last, prev = float(close.iloc[-1]), float(close.iloc[-2])

        # Moving-average crossings. Stated as what happened, in the order a
        # reader would check it: the line, then the side it ended on.
        for period in (50, 200):
            if len(close) < period + 1:
                continue
            ma = close.rolling(period).mean()
            ma_now, ma_prev = float(ma.iloc[-1]), float(ma.iloc[-2])
            if ma_now != ma_now or ma_prev != ma_prev:
                continue
            if prev <= ma_prev and last > ma_now:
                out.append(f"crossed above its {period}-day average")
            elif prev >= ma_prev and last < ma_now:
                out.append(f"crossed below its {period}-day average")

        # 52-week extremes, on closing basis — a close is a fact everyone can
        # agree on, an intraday spike depends on whose feed you read.
        #
        # Measured against the year BEFORE today and with a strict >, so it
        # takes exceeding the old high to earn the line. Comparing today
        # against a window that includes today makes every flat series a
        # 52-week high AND a 52-week low, which is how an alert feed teaches
        # people to ignore it.
        prior = close.tail(253).iloc[:-1]
        if len(prior) >= 60:
            if last > float(prior.max()):
                out.append("closed at a 52-week high")
            elif last < float(prior.min()):
                out.append("closed at a 52-week low")

        # Volume, against its own recent median rather than a mean: one
        # delivery-day spike would drag a mean and make every later day look
        # quiet by comparison.
        if "Volume" in df.columns:
            vol = df["Volume"].dropna()
            if len(vol) >= 21:
                typical = float(vol.tail(21).iloc[:-1].median())
                today = float(vol.iloc[-1])
                if typical > 0 and today >= 2 * typical:
                    out.append(f"traded {today / typical:.1f}× its usual volume")

        # A gap is the part of the move that happened while the market was
        # shut, which is where filings and results land.
        if "Open" in df.columns and prev:
            op = _num(df["Open"].iloc[-1])
            if op is not None:
                gap = 100 * (op - prev) / prev
                if abs(gap) >= 2:
                    out.append(f"opened {abs(gap):.1f}% {'above' if gap > 0 else 'below'} "
                               "the previous close")
    except Exception:
        return out
    return out


def symbol_facts_bulk(symbols: Iterable[str], *, resolve, filings_for=None) -> dict:
    """Price and observations for every symbol, one fetch each.

    resolve and filings_for are passed in rather than imported so this module
    stays testable without a data provider — and so main.py keeps owning the
    caching layer that resolve() already has.
    """
    out = {}
    for raw in symbols:
        sym = _sym(raw)
        if not sym or sym in out:
            continue
        entry = {"symbol": sym, "price": None, "prev_close": None,
                 "day_change_pct": None, "observations": [], "filings": [],
                 "error": None}
        try:
            _s, _t, hist = resolve(sym)
            close = hist["Close"].dropna()
            if len(close) < 2:
                entry["error"] = "not enough price history"
            else:
                last, prev = float(close.iloc[-1]), float(close.iloc[-2])
                entry["price"] = round(last, 2)
                entry["prev_close"] = round(prev, 2)
                entry["day_change_pct"] = round(100 * (last - prev) / prev, 2) if prev else None
                entry["observations"] = _observations(hist)
        except Exception as e:
            entry["error"] = f"{type(e).__name__}"

        if filings_for is not None:
            try:
                entry["filings"] = list(filings_for(sym) or [])
            except Exception:
                entry["filings"] = []
        out[sym] = entry
    return out


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------

def build_digest(holdings: list, *, resolve, filings_for=None, now=None,
                 index_pct=None, movers: int = 3) -> dict:
    """One reader's day.

    holdings: [{"symbol": "INFY", "qty": 10, "avg_price": 1400.0}, ...]
    avg_price is optional — plenty of people know what they hold and not what
    they paid, and a digest that refuses to work without a cost basis is a
    digest most people never see.
    """
    now = now or dt.datetime.now(IST)
    rows, missing = [], []

    wanted = [_sym(h.get("symbol")) for h in holdings if isinstance(h, dict)]
    facts = symbol_facts_bulk(wanted, resolve=resolve, filings_for=filings_for)

    for h in holdings:
        if not isinstance(h, dict):
            continue
        sym = _sym(h.get("symbol"))
        qty = _num(h.get("qty"))
        if not sym or qty is None or qty <= 0:
            continue
        f = facts.get(sym) or {}
        if f.get("error") or f.get("price") is None:
            missing.append({"symbol": sym, "reason": f.get("error") or "no price"})
            continue

        price, prev = f["price"], f["prev_close"]
        value = round(qty * price, 2)
        day_change = round(qty * (price - prev), 2) if prev is not None else None
        avg = _num(h.get("avg_price"))
        cost = round(qty * avg, 2) if avg else None

        rows.append({
            "symbol": sym, "qty": qty, "price": price, "prev_close": prev,
            "value": value,
            "day_change": day_change,
            "day_change_pct": f.get("day_change_pct"),
            "cost": cost,
            "pnl": round(value - cost, 2) if cost else None,
            "pnl_pct": round(100 * (value - cost) / cost, 2) if cost else None,
            "observations": f.get("observations") or [],
            "filings": f.get("filings") or [],
        })

    total_value = round(sum(r["value"] for r in rows), 2)
    day_change = round(sum(r["day_change"] or 0 for r in rows), 2)
    costed = [r for r in rows if r["cost"]]
    total_cost = round(sum(r["cost"] for r in costed), 2) if costed else None
    opening_value = total_value - day_change

    # Movers by rupee contribution. Ties broken by percent so the list is
    # stable rather than dependent on dict ordering.
    by_rupees = sorted([r for r in rows if r["day_change"] is not None],
                       key=lambda r: (r["day_change"], r["day_change_pct"] or 0),
                       reverse=True)
    up = [r for r in by_rupees if r["day_change"] > 0][:movers]
    down = [r for r in by_rupees if r["day_change"] < 0][-movers:][::-1]

    # Events worth a reader's attention, most important first. A filing on a
    # position worth ₹5,000 and one on a position worth ₹5,00,000 are not the
    # same news, so weight ties by what is actually at stake.
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "routine": 0}
    events = []
    for r in rows:
        for fil in r["filings"]:
            events.append({
                "symbol": r["symbol"],
                "category": fil.get("category"),
                "importance": fil.get("importance"),
                "headline": fil.get("headline"),
                "pdf": fil.get("pdf"),
                "value": r["value"],
            })
    events.sort(key=lambda e: (order.get(e.get("importance"), 0), e.get("value") or 0),
                reverse=True)

    notes = []
    for r in rows:
        for line in r["observations"]:
            notes.append({"symbol": r["symbol"], "line": line, "value": r["value"]})
    notes.sort(key=lambda n: n["value"], reverse=True)

    return {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "holdings_counted": len(rows),
        "totals": {
            "value": total_value,
            "day_change": day_change,
            "day_change_pct": (round(100 * day_change / opening_value, 2)
                               if opening_value else None),
            "cost": total_cost,
            "pnl": round(total_value - total_cost, 2) if total_cost else None,
            "pnl_pct": (round(100 * (total_value - total_cost) / total_cost, 2)
                        if total_cost else None),
        },
        "index_change_pct": _num(index_pct),
        "movers": {"up": up, "down": down},
        "events": events[:8],
        "observations": notes[:8],
        "rows": sorted(rows, key=lambda r: r["value"], reverse=True),
        "missing": missing,
    }


def is_worth_sending(digest: dict, *, min_move_pct: float = 0.0) -> bool:
    """Whether this digest earns its place in an inbox.

    A daily email that says nothing is how a subscription becomes spam and how
    a sender's reputation goes. With min_move_pct at 0 everything sends, which
    is the right default while there is a person deciding; raise it and a flat
    day with no filings and no observations stays unsent.
    """
    if not digest or not digest.get("holdings_counted"):
        return False
    if digest.get("events") or digest.get("observations"):
        return True
    move = abs(_num(digest.get("totals", {}).get("day_change_pct")) or 0)
    return move >= min_move_pct
