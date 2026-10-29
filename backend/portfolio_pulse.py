"""
Altaha Screener — Portfolio pulse

WHAT THIS ANSWERS
Two questions a reader asks of their portfolio before any other: which of my
stocks are up and which are down — since I bought them, and today — and is
the news on each one pointing anywhere?

WHAT "LEAN" MEANS, AND WHAT IT DOES NOT
Each holding gets a lean — positive, negative, mixed or quiet — and the list
of reasons behind it, every one with its points. It is a tally of evidence the
site already holds, not a forecast of the price:

  · Exchange filings in the last seven days, read by CATEGORY with the same
    table the Ideas list uses (ideas.FILING_DIRECTION). An order win or a
    buyback counts for; a regulatory action or a pledge counts against.
    Results, M&A, a fundraise or a rating action are real, dated events whose
    direction cannot be read from the exchange's headline, so they are listed
    with zero points and the reader is sent to the filing.
  · Press coverage counts only where its direction has been verified upstream
    (portfolio_intelligence keeps "Positive Catalyst" / "Potential Risk" for
    that). Everything else is listed as "in the news" with zero points:
    headline vocabulary is not turned into sentiment here either.
  · The Altaha Score and the 200-day trend add a small amount each, so a
    quiet name still says something about itself.

A holding with no filing or verified press in the window can still lean, but
only when the score and the trend agree (both for, or both against), and it
says so — "Leaning positive · no fresh news". Silence in a seven-day news
window is not evidence either way, so it is never counted as such.

Pure function of the finished report rows. No network, no persistence.
"""

from datetime import datetime, timezone

VERSION = "portfolio-pulse-1"

MATERIALITY = {"critical": 1.5, "high": 1.25, "medium": 1.0, "low": 0.6, "routine": 0.3}
FILING_FOR = 2.0
FILING_AGAINST = -2.5
PRESS_VERIFIED = 1.0
SCORE_STRONG, SCORE_WEAK = 70, 40
LEAN_AT = 1.5

LABELS = {"positive": "Leaning positive", "negative": "Leaning negative",
          "mixed": "Mixed signals", "quiet": "Quiet"}

METHOD = ("Lean = filings read by category (order win, buyback, capex, bonus, dividend count for; "
          "regulatory action and pledge count against; results, M&A, fundraise and ratings are listed "
          "unscored) × importance, plus verified press direction, plus ±1 for an Altaha Score at or "
          "above 70 or below 40, plus ±0.5 for the 200-day trend. ±1.5 points or more leans; "
          "seven-day window.")
DISCLAIMER = ("A tally of evidence the site holds, not a forecast. Prices can move against every "
              "reason listed here; read the filings before acting on any of them.")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _directions():
    try:
        from ideas import FILING_DIRECTION
        return FILING_DIRECTION
    except Exception:                                   # pragma: no cover
        return {}


def _is_filing(e):
    return "filing" in str(e.get("source") or "").lower()


def lean_for(row, events, directions=None):
    """(lean, points, reasons, news_backed) for one holding."""
    directions = _directions() if directions is None else directions
    reasons, points, evidence = [], 0.0, 0
    for e in events:
        if e.get("mapping") != "company":
            continue
        weight = MATERIALITY.get(str(e.get("materiality") or "medium"), 1.0)
        base = {"text": e.get("headline"), "url": e.get("url"), "at": e.get("published_at"),
                "source": e.get("source"), "category": e.get("category")}
        if _is_filing(e):
            evidence += 1
            d = directions.get(e.get("category"), "event")
            if d == "supportive":
                p = round(FILING_FOR * weight, 2)
                reasons.append({**base, "sign": 1, "points": p, "kind": "filing",
                                "why": f"{e.get('category')} filed — counts for the stock."})
            elif d == "adverse":
                p = round(FILING_AGAINST * weight, 2)
                reasons.append({**base, "sign": -1, "points": p, "kind": "filing",
                                "why": f"{e.get('category')} filed — counts against the stock."})
            else:
                p = 0.0
                reasons.append({**base, "sign": 0, "points": 0.0, "kind": "filing",
                                "why": f"{e.get('category') or 'Filing'} — a real event whose direction the "
                                       "exchange headline does not give. Open the filing."})
            points += p
        else:
            group = e.get("group")
            if group in ("Positive Catalyst", "Potential Risk"):
                evidence += 1
                sign = 1 if group == "Positive Catalyst" else -1
                points += sign * PRESS_VERIFIED
                reasons.append({**base, "sign": sign, "points": sign * PRESS_VERIFIED, "kind": "press",
                                "why": "Press coverage with a verified direction."})
            else:
                reasons.append({**base, "sign": 0, "points": 0.0, "kind": "press",
                                "why": "In the news — direction not verified, so it is not scored."})

    score = _num(row.get("composite"))
    if score is not None and score >= SCORE_STRONG:
        points += 1
        reasons.append({"sign": 1, "points": 1.0, "kind": "score",
                        "text": f"Altaha Score {score:.0f}/100", "why": "A strong score counts a little for it."})
    elif score is not None and score < SCORE_WEAK:
        points -= 1
        reasons.append({"sign": -1, "points": -1.0, "kind": "score",
                        "text": f"Altaha Score {score:.0f}/100", "why": "A weak score counts a little against it."})

    ma200 = _num((row.get("moving_averages") or {}).get("200"))
    if ma200 is not None:
        sign = 1 if ma200 > 0 else -1
        points += 0.5 * sign
        reasons.append({"sign": sign, "points": 0.5 * sign, "kind": "trend",
                        "text": f"{abs(ma200):.1f}% {'above' if sign > 0 else 'below'} its 200-day average",
                        "why": "The long trend counts half a point."})

    points = round(points, 2)
    if points >= LEAN_AT:
        lean = "positive"
    elif points <= -LEAN_AT:
        lean = "negative"
    else:
        lean = "mixed" if evidence else "quiet"
    # Scored reasons first, strongest first; unscored context after.
    reasons.sort(key=lambda r: (r["points"] == 0, -abs(r["points"])))
    return lean, points, reasons, evidence > 0


def build(rows, events=None, now=None):
    """The pulse for a finished set of report rows."""
    now = now or datetime.now(timezone.utc)
    directions = _directions()
    by_symbol = {}
    for e in events or []:
        for s in e.get("symbols") or []:
            by_symbol.setdefault(s, []).append(e)

    holdings, winners, losers, unknown = {}, [], [], []
    for r in rows or []:
        sym = r.get("symbol")
        if not sym:
            continue
        lean, points, reasons, news_backed = lean_for(r, by_symbol.get(sym, []), directions)
        label = LABELS[lean] + ("" if news_backed or lean == "quiet" else " · no fresh news")
        entry = {"symbol": sym, "name": r.get("name"), "weight_pct": _num(r.get("weight_pct")),
                 "pnl": _num(r.get("pnl")), "pnl_pct": _num(r.get("pnl_pct")),
                 "day_change_pct": _num(r.get("day_change_pct")), "price": _num(r.get("price")),
                 "buy_price": _num(r.get("buy_price")),
                 "lean": lean, "lean_label": label, "news_backed": news_backed, "points": points,
                 "tilt": max(-100, min(100, round(points / 4 * 100))),
                 "reasons": reasons[:8]}
        holdings[sym] = entry
        if entry["pnl_pct"] is None:
            unknown.append(sym)
        elif entry["pnl_pct"] > 0:
            winners.append(sym)
        elif entry["pnl_pct"] < 0:
            losers.append(sym)
        else:
            unknown.append(sym)
    winners.sort(key=lambda s: -holdings[s]["pnl_pct"])
    losers.sort(key=lambda s: holdings[s]["pnl_pct"])

    moved = [h for h in holdings.values() if h["day_change_pct"] is not None]
    today = {"up": sum(1 for h in moved if h["day_change_pct"] > 0),
             "down": sum(1 for h in moved if h["day_change_pct"] < 0),
             "flat": sum(1 for h in moved if h["day_change_pct"] == 0),
             "best": max(moved, key=lambda h: h["day_change_pct"])["symbol"] if moved else None,
             "worst": min(moved, key=lambda h: h["day_change_pct"])["symbol"] if moved else None}
    leans = {k: sorted((s for s, h in holdings.items() if h["lean"] == k),
                       key=lambda s: -abs(holdings[s]["points"])) for k in LABELS}
    return {"version": VERSION, "generated_at": now.isoformat(), "holdings": holdings,
            "winners": winners, "losers": losers, "no_cost": unknown, "today": today,
            "leans": leans, "method": METHOD, "disclaimer": DISCLAIMER}
