"""
Altaha Screener — Portfolio Actions

Turns a scored holding into a call: Add, Hold, Reduce, Exit or Review, with
the reasons that produced it and, where one exists, a named alternative in
the same sector that currently scores better.

── The tone switch ────────────────────────────────────────────────────────
TONE controls how the same computation is worded.

  "directive"     — "Reduce to 15%. Sell 61 shares."
  "observational" — "24.3% against a 15% guardrail. The gap is 61 shares."

The arithmetic is identical either way; only the verb changes. Issuing
directives to the public is registered-adviser activity in India, so this is
a single constant rather than something threaded through the codebase — the
day a registration certificate lands, flip this line and nothing else.

── How a call is reached ──────────────────────────────────────────────────
Six inputs, weighted and then bucketed:

  1. Composite score           the engine's own verdict on the business
  2. Weight in the book        position size against a concentration guardrail
  3. Sector momentum           where the sector sits against the Nifty 50
  4. Drawdown from cost        how far underwater the position is
  5. Recent filings            an exchange filing of consequence in the window
  6. Peer gap                  whether a same-sector name scores materially better

No single input decides. A 78-score name at 4% weight in a leading sector is
an obvious Add; the same score at 31% weight is a Reduce despite the quality,
because size is its own risk. The reasons list always shows which inputs
actually moved the call, so a user can disagree with the specific one they
think is wrong rather than the conclusion as a whole.
"""

TONE = "directive"           # "directive" | "observational"

# Guardrails. Not user-facing settings any more — these are the defaults a
# reasonable book is measured against, applied silently.
STOCK_CAP = 15.0             # a single name above this is a size risk
STOCK_TARGET = 10.0          # the weight a Reduce call works back toward
SECTOR_CAP = 35.0
STRONG = 70                  # composite at or above this is a quality name
FAIR = 50
WEAK = 38
PEER_GAP = 8                 # a peer must beat the holding by this to be named
DEEP_DRAWDOWN = 25.0


def _verb(directive: str, observational: str) -> str:
    return directive if TONE == "directive" else observational


# ---------------------------------------------------------------------------
# Peer substitution
# ---------------------------------------------------------------------------

def find_alternatives(holding: dict, scan_rows: list, held_symbols: set,
                      limit: int = 3) -> list:
    """
    Better-scoring names in the same sector, excluding what is already held.

    Excluding current holdings matters: proposing a name the user already
    owns as a replacement for another is not a diversification move, it is a
    concentration move wearing the wrong label.
    """
    sector = holding.get("sector")
    if not sector or sector == "Unclassified":
        return []

    mine = holding.get("composite")
    if mine is None:
        return []

    pool = []
    for row in scan_rows:
        if row.get("sector") != sector:
            continue
        sym = row.get("symbol")
        if not sym or sym == holding.get("symbol") or sym in held_symbols:
            continue
        score = row.get("composite")
        if score is None or score < mine + PEER_GAP:
            continue
        pool.append({
            "symbol": sym,
            "composite": score,
            "gap": score - mine,
            "setup": row.get("setup"),
            "name": row.get("name"),
        })

    pool.sort(key=lambda p: -p["composite"])
    return pool[:limit]


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------

def _shares_to_target(row: dict, target_pct: float, total_value: float):
    """Shares to sell to bring a position back to a target weight."""
    price, value = row.get("price"), row.get("value")
    if not price or not value or total_value <= 0:
        return None
    cap = target_pct / 100.0
    if cap >= 1.0:
        return None
    # Selling shrinks the book too, so the naive value - cap*total overstates
    # the sale. Solving (V - x)/(T - x) = cap gives the figure below.
    excess = (value - cap * total_value) / (1.0 - cap)
    if excess <= 0:
        return None
    shares = int(excess / price)
    if shares <= 0:
        return None
    return {"shares": shares, "value": round(shares * price, 2),
            "price": round(price, 2), "of_shares": row.get("qty")}


def evaluate(row: dict, total_value: float, sector_state: str | None,
             sector_rel_3m, news, alternatives: list) -> dict:
    """One holding in, one action out."""
    score = row.get("composite")
    weight = row.get("weight_pct") or 0.0
    pnl_pct = row.get("pnl_pct")
    sym = row.get("symbol")

    reasons = []
    oversize = weight > STOCK_CAP
    weak = score is not None and score < WEAK
    soft = score is not None and score < FAIR
    strong = score is not None and score >= STRONG
    sector_bad = sector_state in ("Lagging", "Weakening")
    sector_good = sector_state in ("Leading", "Improving")
    deep_loss = pnl_pct is not None and pnl_pct <= -DEEP_DRAWDOWN

    # ── Reasons, in the order a person would actually weigh them ──────────
    if score is not None:
        if strong:
            reasons.append(f"Scores {score}/100 — the engine's checks are largely passing.")
        elif weak:
            reasons.append(f"Scores {score}/100. Below 38 the technical and fundamental "
                           f"checks are failing together, not in isolation.")
        elif soft:
            reasons.append(f"Scores {score}/100 — middling. Neither the trend nor the "
                           f"accounts make a strong case.")
        else:
            reasons.append(f"Scores {score}/100 — sound without being exceptional.")

    if oversize:
        reasons.append(f"At {weight:.1f}% it is the concentration risk in this book, "
                       f"not the quality risk.")
    elif weight < 3:
        reasons.append(f"At {weight:.1f}% it is too small to change portfolio outcomes "
                       f"either way.")

    if sector_state and sector_rel_3m is not None:
        side = "ahead of" if sector_rel_3m >= 0 else "behind"
        reasons.append(f"Its sector is {abs(sector_rel_3m):.1f}% {side} the Nifty 50 over "
                       f"three months — {sector_state.lower()}.")

    if deep_loss:
        reasons.append(f"Down {abs(pnl_pct):.1f}% from your cost. A position needs "
                       f"{100 * (abs(pnl_pct) / (100 - abs(pnl_pct))):.0f}% just to get back "
                       f"to level.")
    elif pnl_pct is not None and pnl_pct >= 40:
        reasons.append(f"Up {pnl_pct:.1f}% from cost — the gain itself has grown the weight.")

    if news and news.get("importance") in ("high", "critical"):
        reasons.append(f"Recent filing — {news.get('category')}: {news.get('headline')}")

    # ── The call ──────────────────────────────────────────────────────────
    if weak and (sector_bad or deep_loss):
        action, conviction = "EXIT", "high"
    elif weak:
        action, conviction = "EXIT", "medium"
    elif oversize and (soft or sector_bad):
        action, conviction = "REDUCE", "high"
    elif oversize:
        action, conviction = "REDUCE", "medium"
    elif soft and sector_bad:
        action, conviction = "REDUCE", "medium"
    elif soft:
        action, conviction = "REVIEW", "medium"
    elif strong and sector_good and weight < STOCK_TARGET:
        action, conviction = "ADD", "high"
    elif strong and weight < STOCK_TARGET:
        action, conviction = "ADD", "medium"
    elif strong:
        action, conviction = "HOLD", "high"
    else:
        action, conviction = "HOLD", "medium"

    # ── The headline, and the arithmetic where there is any ───────────────
    trim = _shares_to_target(row, STOCK_TARGET, total_value) if action in ("REDUCE",) else None
    arithmetic = None

    if action == "EXIT":
        headline = _verb(
            f"Exit {sym}.",
            f"{sym} fails on the evidence currently available.")
        if row.get("qty") and row.get("price"):
            arithmetic = {"shares": row["qty"], "value": round(row["qty"] * row["price"], 2),
                          "price": round(row["price"], 2), "of_shares": row["qty"]}
    elif action == "REDUCE" and trim:
        headline = _verb(
            f"Reduce {sym} to about {STOCK_TARGET:.0f}% — sell {trim['shares']} of "
            f"{int(trim['of_shares'])} shares, ₹{trim['value']:,.0f}.",
            f"{sym} sits at {weight:.1f}%. Returning to {STOCK_TARGET:.0f}% is "
            f"{trim['shares']} of {int(trim['of_shares'])} shares, ₹{trim['value']:,.0f}.")
        arithmetic = trim
    elif action == "REDUCE":
        headline = _verb(f"Reduce {sym}.", f"{sym} is above a reasonable single-name weight.")
    elif action == "ADD":
        headline = _verb(
            f"Add to {sym} — quality is there and the position is small.",
            f"{sym} scores well at a weight small enough that it changes little.")
    elif action == "REVIEW":
        headline = _verb(
            f"Review {sym} before the next results.",
            f"{sym} is neither clearly working nor clearly broken.")
    else:
        headline = _verb(f"Hold {sym}.", f"{sym} continues to pass on current evidence.")

    out = {
        "action": action,
        "conviction": conviction,
        "headline": headline,
        "reasons": reasons,
        "arithmetic": arithmetic,
        "alternatives": alternatives if action in ("EXIT", "REDUCE", "REVIEW") else [],
        "news": news,
    }

    if out["alternatives"]:
        best = out["alternatives"][0]
        out["alternative_line"] = _verb(
            f"Closest replacement in the same sector: {best['symbol']} at "
            f"{best['composite']}/100, {best['gap']} points better on the same checks.",
            f"Same sector, scoring higher today: {best['symbol']} at {best['composite']}/100, "
            f"{best['gap']} points above {sym} on identical checks.")

    return out


# ---------------------------------------------------------------------------
# Book-level summary
# ---------------------------------------------------------------------------

ACTION_ORDER = ["EXIT", "REDUCE", "REVIEW", "HOLD", "ADD"]


def summarise(holdings: list, total_value: float, weighted_score,
              sector_rows: list) -> dict:
    """The paragraph that goes at the top of the report."""
    counts = {a: 0 for a in ACTION_ORDER}
    at_risk = 0.0
    for h in holdings:
        act = (h.get("advice") or {}).get("action")
        if act in counts:
            counts[act] += 1
            if act in ("EXIT", "REDUCE"):
                at_risk += h.get("weight_pct") or 0.0

    lead_w = sum(s["weight_pct"] for s in sector_rows
                 if s.get("state") in ("Leading", "Improving"))
    lag_w = sum(s["weight_pct"] for s in sector_rows
                if s.get("state") in ("Lagging", "Weakening"))

    parts = []
    if weighted_score is not None:
        parts.append(f"The book scores {weighted_score}/100 value-weighted.")

    moves = counts["EXIT"] + counts["REDUCE"]
    if moves:
        parts.append(
            _verb(f"{moves} position(s) carrying {at_risk:.0f}% of your money need action.",
                  f"{moves} position(s) carrying {at_risk:.0f}% of your money are flagged."))
    else:
        parts.append("Nothing in the book is flagged for action on current evidence.")

    if lead_w or lag_w:
        parts.append(f"{lead_w:.0f}% sits in sectors beating the Nifty 50 over three months, "
                     f"{lag_w:.0f}% in sectors behind it.")

    return {
        "counts": counts,
        "at_risk_pct": round(at_risk, 1),
        "leading_pct": round(lead_w, 1),
        "lagging_pct": round(lag_w, 1),
        "text": " ".join(parts),
        "tone": TONE,
    }
