"""
The portfolio action plan: what to do with each holding, and where the money
could go instead.

WHAT THIS IS
One call per holding — EXIT, TRIM, AVERAGE, ADD or HOLD — with the exact
number of shares and rupees, one plain sentence saying why, the evidence
behind it, and where a stronger stock exists in exactly the same industry,
its name.
Then the sectors that are doing well where the reader holds little, with
the best-scoring stocks in each.

This is advice, deliberately. The owner chose to show it to every visitor,
knowing that in India telling people what to do with their holdings is
activity SEBI regulates, and that this site is not registered as an
investment adviser or research analyst. The disclaimer below says exactly
that, and it is shown with every plan. Keep it true.

HOW A CALL IS REACHED
Fixed, written-down rules — no model, no fitted weights — over five inputs:

  score      the holding's Altaha Score v4 (0-100, peer-relative)
  size       its share of the reader's money, against THEIR per-stock limit
  P&L        how far it is above or below what they paid
  sector     whether its sector index is beating or trailing the Nifty 50
  stronger   whether a similar-sized company in exactly the same industry ("Steel",
             "Communication Equipment") scores clearly better. Never the broad
             sector: "Technology" holds a telecom-tower builder and a
             digital-signature software house, and offering one for the
             other is not a switch, it is a different bet

The thresholds come from where the scores actually fall. Across today's
analysed cohort the median is about 51, the top tenth starts near 62 and
the random control group's middle half runs 41-53 — v4 shrinks thin
evidence toward 50, so 45 is not "bad", it is ordinary. Calling EXIT below
45 would have told half the market to sell Reliance. Hence:

  STRONG  60+   top ~15%        GOOD  55+   top ~25%
  WEAK    <40   (or the reader's own floor, if lower)
  POOR    <33   bottom ~5%

  EXIT     POOR; or WEAK and (sector trailing, or down past the reader's
           review mark); or WEAK and too small to matter
  TRIM     WEAK (sell half); or above the reader's per-stock limit (sell
           down to it)
  AVERAGE  GOOD, 10%+ below cost, sector not trailing, room under the limit
  ADD      STRONG, under the add target, sector not trailing
  HOLD     everything else

Every figure a call prints is arithmetic on the report the reader already
has — shares, rupees, weights after the trade, the new average cost — so
each one can be checked by hand.
"""
from __future__ import annotations

import math

try:
    import sectors as _sectors
except Exception:                               # pragma: no cover
    _sectors = None

STRONG = 60.0
GOOD = 55.0
WEAK = 40.0
POOR = 33.0
SMALL_PCT = 3.0          # a position this small cannot move the portfolio
ADD_TARGET_PCT = 10.0    # ADD works up toward this, or the reader's limit if lower
AVERAGE_BELOW_PCT = 10.0 # averaging needs the price at least this far under cost
PEER_GAP = 8.0           # a stronger alternative must beat the holding by this much
SIZE_BAND = 5.0          # ...and be within this factor of its market value, either way
MAX_ADDS = 3             # new-money calls per plan, strongest first
TRAILING = ("Lagging", "Weakening")
LEADING = ("Leading", "Improving")
ORDER = ["EXIT", "TRIM", "AVERAGE", "ADD", "HOLD"]

DISCLAIMER = (
    "These calls come from fixed rules applied to each company's Altaha Score, its "
    "sector's trend and the limits you set — the rules are written out on the page. "
    "Altaha is not registered with SEBI as an investment adviser or research analyst, and "
    "the rules do not know your goals, tax position or other savings. Treat each call as a "
    "starting point, read its reasons, and decide for yourself. Markets carry risk of loss.")

METHOD = (
    "Strong = score 60+, good = 55+, weak = under 40 (or your own floor if lower), poor = "
    "under 33. Exit: poor, or weak with a trailing sector or a loss past your review "
    "mark. Trim: weak (sell half), or above your per-stock limit (sell down to it). "
    "Average down: good score, 10%+ below your cost, sector not trailing. Add: strong "
    "score, below 10% of your money (or your limit), sector not trailing. Otherwise hold.")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _canon(sector):
    if not sector:
        return None
    if _sectors is not None:
        try:
            return _sectors.normalise(sector) or str(sector)
        except Exception:
            pass
    return str(sector)


def _rupees(v) -> str:
    """₹1,23,456 — Indian grouping, whole rupees."""
    v = int(round(abs(v or 0)))
    s = str(v)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return "₹" + s


def _pct(v, nd=1) -> str:
    return f"{abs(v):.{nd}f}".rstrip("0").rstrip(".") + "%"


def _score_of(row):
    return _num((row.get("altaha_score_v4") or {}).get("position", {}).get("final_score")) \
        if row.get("altaha_score_v4") else _num(row.get("position_score") or row.get("composite"))


# ---------------------------------------------------------------------------
# Trade arithmetic
# ---------------------------------------------------------------------------

def _sell_to_weight(qty, price, value, total, target_pct):
    """Shares to sell so the position is target_pct of the book afterwards.
    Selling shrinks the book too: solve (V - x)/(T - x) = t."""
    t = target_pct / 100.0
    if not (price and value and total) or t >= 1:
        return None
    excess = (value - t * total) / (1 - t)
    # Rounded UP: "down to your limit" has to end at or under the limit, and
    # rounding down left HDFCBANK at 15.9% after a trim "to 15%".
    n = int(min(qty, math.ceil(excess / price - 1e-9))) if excess > 0 else 0
    return n if n >= 1 else None


def _buy_to_weight(qty, price, value, total, target_pct):
    """Shares to buy with NEW money so the position is target_pct afterwards:
    solve (V + x)/(T + x) = t."""
    t = target_pct / 100.0
    if not (price and total is not None) or t >= 1:
        return None
    need = (t * total - value) / (1 - t)
    n = int(math.floor(need / price)) if need > 0 else 0
    return n if n >= 1 else None


def _move(side, n, row, total):
    price, value, qty = row["price"], row["value"], row["qty"]
    amount = round(n * price, 2)
    if side == "sell":
        after_total = total - amount
        after_w = 100 * (value - amount) / after_total if after_total > 0 else 0.0
    else:
        after_total = total + amount
        after_w = 100 * (value + amount) / after_total if after_total > 0 else 0.0
    out = {"side": side, "shares": n, "of_shares": qty, "price": round(price, 2),
           "value": amount, "after_weight_pct": round(after_w, 1),
           "all": side == "sell" and n >= qty}
    buy = _num(row.get("buy_price"))
    if side == "buy" and buy:
        out["avg_cost_before"] = round(buy, 2)
        out["avg_cost_after"] = round((qty * buy + n * price) / (qty + n), 2)
    return out


# ---------------------------------------------------------------------------
# One holding
# ---------------------------------------------------------------------------

def _pillar_line(row):
    pillars = ((row.get("altaha_score_v4") or {}).get("position") or {}).get("pillars") or {}
    pillars = {k: v for k, v in pillars.items() if _num(v) is not None}
    if len(pillars) < 2:
        return None
    names = {"momentum": "price trend", "participation": "buying interest",
             "quality": "business quality", "value": "valuation", "growth": "growth",
             "acceleration": "momentum in results", "financial_strength": "balance sheet",
             "risk": "price stability"}
    best = max(pillars, key=pillars.get)
    worst = min(pillars, key=pillars.get)
    return (f"Best on {names.get(best, best)} ({pillars[best]:.0f}/100), "
            f"weakest on {names.get(worst, worst)} ({pillars[worst]:.0f}/100).")


MIN_COHORT = 30          # below this, "stronger than N% of companies" is arithmetic, not evidence


def _percentile(score, cohort_scores):
    if score is None or len(cohort_scores or []) < MIN_COHORT:
        return None
    below = sum(1 for s in cohort_scores if s < score)
    return round(100 * below / len(cohort_scores))


def call(row, total, policy, sector_state=None, sector_rel_3m=None,
         alternatives=None, cohort_scores=None) -> dict:
    """One holding in, one action out."""
    cap = _num((policy or {}).get("max_stock_pct")) or 15.0
    floor = _num((policy or {}).get("min_composite"))
    review = _num((policy or {}).get("review_drawdown")) or 25.0
    weak_below = min(WEAK, floor) if floor is not None else WEAK

    sym = row["symbol"]
    s = _num(row.get("composite"))
    w = _num(row.get("weight_pct")) or 0.0
    p = _num(row.get("pnl_pct"))
    qty = _num(row.get("qty")) or 0.0
    trailing = sector_state in TRAILING
    leading = sector_state in LEADING
    add_target = min(cap, ADD_TARGET_PCT)
    pctile = _percentile(s, cohort_scores or [])

    reasons = []
    if s is not None:
        rank = ("" if pctile is None else
                " — among the weakest of the companies we track" if pctile <= 2 else
                " — among the strongest of the companies we track" if pctile >= 98 else
                f" — stronger than {pctile}% of the companies we track")
        reasons.append(f"Altaha Score {s:.0f}/100{rank}.")
        pl = _pillar_line(row)
        if pl:
            reasons.append(pl)
    else:
        reasons.append("No Altaha Score yet — too little published data to rank it.")
    reasons.append(f"{w:.1f}% of your money (your limit for one stock is {cap:.0f}%).")
    if p is not None:
        reasons.append(f"{'Up' if p >= 0 else 'Down'} {_pct(p)} from what you paid.")
    if sector_state and sector_rel_3m is not None:
        side = "ahead of" if sector_rel_3m >= 0 else "behind"
        reasons.append(f"Its sector is {_pct(sector_rel_3m)} {side} the Nifty 50 over three months "
                       f"({sector_state.lower()}).")

    # ── The call ───────────────────────────────────────────────────────────
    action, conviction, why, move = "HOLD", "medium", "", None
    price_ok = bool(_num(row.get("price")) and _num(row.get("value")) and qty > 0)

    if s is None:
        if w > cap and price_ok:
            n = _sell_to_weight(qty, row["price"], row["value"], total, cap)
            if n:
                action, conviction, move = "TRIM", "medium", _move("sell", n, row, total)
                why = (f"At {w:.1f}% it is over your {cap:.0f}% limit for one stock, and there "
                       f"is no score to argue for keeping it that big.")
        if action == "HOLD":
            conviction = "low"
            why = ("We could not score it yet, so there is no case either way — keep it within "
                   "your limits and check back after the next scan.")
    elif s < POOR:
        action, conviction = "EXIT", "high"
        tail = ("." if pctile is None else
                ", among the very weakest of the companies we track." if pctile <= 2 else
                f", weaker than {100 - pctile}% of the companies we track.")
        why = f"Its evidence is poor: a score of {s:.0f}/100" + tail
    elif s < weak_below and trailing:
        action, conviction = "EXIT", "high"
        why = f"Weak evidence (score {s:.0f}) and its sector is trailing the market."
    elif s < weak_below and p is not None and p <= -review:
        action, conviction = "EXIT", "medium"
        why = (f"Weak evidence (score {s:.0f}) and it is {_pct(p)} below what you paid — past the "
               f"{review:.0f}% mark you set for a rethink.")
    elif s < weak_below and w < SMALL_PCT:
        action, conviction = "EXIT", "medium"
        why = (f"Weak evidence (score {s:.0f}) in a position too small ({w:.1f}%) to be worth "
               f"watching — tidying it up simplifies the portfolio.")
    elif s < weak_below and qty < 2:
        # Half of one share is not a trade: the only move is the whole position.
        action, conviction = "EXIT", "medium"
        why = f"Weak evidence (score {s:.0f}), and a single share cannot be trimmed."
    elif s < weak_below:
        action, conviction = "TRIM", "medium"
        why = (f"Weak evidence (score {s:.0f}). Selling half cuts the damage if it keeps slipping, "
               f"and keeps you in if it recovers.")
        if price_ok:
            n = int(qty // 2)
            move = _move("sell", n, row, total) if n >= 1 else None
    elif w > cap:
        action = "TRIM"
        conviction = "high" if s < GOOD else "medium"
        why = ((f"A good company, but at {w:.1f}% it is more than your {cap:.0f}% limit for one "
                f"stock — one bad quarter would hit your whole portfolio.")
               if s >= GOOD else
               (f"At {w:.1f}% it is over your {cap:.0f}% limit, and its evidence is only "
                f"average (score {s:.0f})."))
        if price_ok:
            n = _sell_to_weight(qty, row["price"], row["value"], total, cap)
            move = _move("sell", n, row, total) if n else None
            if move is None:
                # One share is worth more than the excess: any sale overshoots.
                action, conviction = "HOLD", "low"
                why = (f"At {w:.1f}% it is over your {cap:.0f}% limit, but selling even one share "
                       f"would take it well below — keep it, and do not add more.")
    elif s >= GOOD and p is not None and p <= -AVERAGE_BELOW_PCT and not trailing and w < cap and price_ok:
        n_cap = _buy_to_weight(qty, row["price"], row["value"], total, cap)
        n = int(min(qty, n_cap)) if n_cap else 0
        if n >= 1:
            action = "AVERAGE"
            conviction = "high" if s >= STRONG else "medium"
            move = _move("buy", n, row, total)
            why = (f"Strong evidence (score {s:.0f}) while the price is {_pct(p)} below what you "
                   f"paid — buying more now lowers your average cost.")
    if action == "HOLD" and s is not None and s >= STRONG and not trailing and w < add_target - 1 and price_ok:
        n = _buy_to_weight(qty, row["price"], row["value"], total, add_target)
        if n:
            action = "ADD"
            conviction = "high" if leading else "medium"
            move = _move("buy", n, row, total)
            why = (f"One of your strongest holdings (score {s:.0f}) but only {w:.1f}% of your money"
                   + (", in a sector beating the market." if leading else "."))
    if action == "HOLD" and not why:
        if s >= GOOD:
            conviction = "high"
            why = f"Solid evidence (score {s:.0f}) at a sensible size. Nothing to do."
        elif trailing:
            conviction = "low"
            why = (f"Middling evidence (score {s:.0f}) and its sector is trailing. Keep it for now, "
                   f"but it is first in line if you need to free money.")
        else:
            why = (f"Middling evidence (score {s:.0f}). Keep it, and look again after the next "
                   f"quarterly results.")

    if action == "EXIT" and price_ok and move is None:
        move = _move("sell", qty, row, total)

    # ── Headline and the stronger alternative ───────────────────────────────
    verb = {"EXIT": "Exit", "TRIM": "Trim", "AVERAGE": "Average down", "ADD": "Add to",
            "HOLD": "Hold"}[action]
    if move and move["side"] == "sell":
        todo = (f"Sell all {int(move['shares'])} shares · {_rupees(move['value'])}" if move["all"] else
                f"Sell {int(move['shares'])} of {int(move['of_shares'])} shares · {_rupees(move['value'])}"
                f" — leaves it at {move['after_weight_pct']:.1f}% of your money")
    elif move and move["side"] == "buy":
        todo = f"Buy {int(move['shares'])} more · {_rupees(move['value'])}"
        if action == "AVERAGE" and move.get("avg_cost_after"):
            todo += (f" — your average cost falls from {_rupees(move['avg_cost_before'])} to "
                     f"{_rupees(move['avg_cost_after'])}")
        else:
            todo += f" — takes it to {move['after_weight_pct']:.1f}% of your money"
    else:
        todo = "No change needed" if action == "HOLD" else "Sell the whole position"

    alts = alternatives or []
    offer = action in ("EXIT", "TRIM") and (s is None or s < GOOD) or (action == "HOLD" and s is not None and s < 50)
    alts = alts if offer else []
    switch = None
    if alts:
        best = alts[0]
        vs = f"score {best['score']:.0f} vs {s:.0f} for {sym}" if s is not None else f"score {best['score']:.0f}"
        switch = f"Consider switching to {best['symbol']} — same industry ({best['group']}), {vs}."

    return {
        "symbol": sym, "name": row.get("name") or sym, "sector": row.get("sector"),
        "action": action, "verb": verb, "conviction": conviction,
        "headline": f"{verb} {sym}", "todo": todo, "why": why, "reasons": reasons,
        "move": move, "score": s, "weight_pct": round(w, 2), "pnl_pct": p,
        "alternatives": alts[:3], "switch": switch,
    }


# ---------------------------------------------------------------------------
# The whole portfolio
# ---------------------------------------------------------------------------

def _industry(v):
    v = " ".join(str(v or "").split())
    return v if v and v.lower() not in {"unknown", "other", "n/a", "none"} else None


def _industry_of(row, industries=None):
    """One classifier for everybody where the market-wide one knows the
    company (industry.py), so a holding and a candidate are never named by
    two different schemes; the row's own provider field otherwise."""
    sym = str((row or {}).get("symbol") or "").upper()
    return _industry((industries or {}).get(sym)) or _industry((row or {}).get("industry"))


def _cap(v):
    v = _num(v)
    return v if v and v > 0 else None


def _similar_size(a, b):
    """Within SIZE_BAND of each other, or unknown. Tata Steel (about ₹2.3 lakh
    crore) was offered Steelcast (about a hundredth of that): same industry
    label, but swapping a giant for a small-cap is a different bet, not a
    better version of the same one."""
    return a is None or b is None or 1.0 / SIZE_BAND <= b / a <= SIZE_BAND


def _universe(scan_payload, industries=None):
    rows = (scan_payload or {}).get("factor_universe") or (scan_payload or {}).get("rankings") or []
    out = []
    for r in rows:
        s = _num(r.get("position_score"))
        if s is None:
            s = _score_of(r)
        if r.get("symbol") and s is not None:
            out.append({"symbol": r["symbol"], "name": r.get("name") or r["symbol"],
                        "sector": _canon(r.get("sector")), "industry": _industry_of(r, industries),
                        "market_cap": _cap(r.get("market_cap")), "score": s})
    return out


def alternatives_for(row, universe, held, limit=3, industries=None):
    """Stronger, similar-sized companies in exactly the same industry, or
    none. A broad sector is not a substitute: Pace Digitek (communication
    equipment) was once offered eMudhra (application software) because both
    are "Technology". No switch is better than a wrong one; the sectors doing
    well are suggested separately, as what they are."""
    s = _num(row.get("composite"))
    ind = _industry_of(row, industries)
    if not ind:
        return []
    cap = _cap((row.get("valuation") or {}).get("market_cap")) or _cap(row.get("market_cap"))
    floor = max(GOOD, (s or 0) + PEER_GAP)
    pool = [u for u in universe if u.get("industry") == ind and u["symbol"] not in held and u["score"] >= floor
            and _similar_size(cap, u.get("market_cap"))]
    pool.sort(key=lambda u: (-u["score"], u["symbol"]))
    return [{"symbol": u["symbol"], "name": u["name"], "score": round(u["score"], 1),
             "gap": round(u["score"] - (s or 0), 1) if s is not None else None,
             "match": "industry", "group": ind} for u in pool[:limit]]


def rotation(report, universe, held, limit=3):
    """Sectors doing well where the reader holds less than the market does,
    and the best-scoring stocks in each."""
    states = {_canon(m.get("sector")): m for m in ((report.get("sector_momentum") or {}).get("sectors") or [])}
    comp = report.get("sector_comparison") or []
    out = []
    for c in comp:
        sec = _canon(c.get("sector"))
        m = states.get(sec) or {}
        state = m.get("state")
        rel = _num((m.get("relative") or {}).get("3M"))
        if rel is None:
            rel = _num(c.get("momentum"))
        mine = _num(c.get("weight_pct")) or 0.0
        bench = _num(c.get("benchmark_weight_pct"))
        if state not in LEADING or rel is None or rel <= 0 or bench is None or mine > bench - 2:
            continue
        stocks = [u for u in universe if u["sector"] == sec and u["symbol"] not in held and u["score"] >= GOOD]
        stocks.sort(key=lambda u: (-u["score"], u["symbol"]))
        if not stocks:
            continue
        out.append({
            "sector": sec, "state": state, "relative_3m": round(rel, 1),
            "your_weight_pct": round(mine, 1), "market_weight_pct": round(bench, 1),
            "why": (f"{sec} is beating the Nifty 50 by {_pct(rel)} over three months, and you have "
                    f"{_pct(mine)} of your money there against about {_pct(bench)} in the market."),
            "stocks": [{"symbol": u["symbol"], "name": u["name"], "score": round(u["score"], 1)}
                       for u in stocks[:3]],
        })
    out.sort(key=lambda r: -r["relative_3m"])
    return out[:limit]


def plan(report, scan_payload=None, policy=None, industries=None) -> dict:
    """The action plan for a built portfolio report. `industries` is the
    market-wide {symbol: industry} map (industry.classification), passed in so
    this module stays pure."""
    rows = [r for r in (report or {}).get("holdings") or [] if r.get("value")]
    if not rows:
        return {"available": False, "message": "No priced holdings to plan for."}
    total = _num(report.get("total_value")) or sum(r["value"] for r in rows)
    policy = policy or report.get("policy") or {}
    universe = _universe(scan_payload, industries)
    held = {r["symbol"] for r in rows}
    cohort = [u["score"] for u in universe]
    states = {_canon(s.get("sector")): s for s in (report.get("sectors") or [])}

    actions = []
    for r in rows:
        sec = states.get(_canon(r.get("sector"))) or {}
        rel = _num((sec.get("relative") or {}).get("3M"))
        actions.append(call(r, total, policy, sec.get("state"), rel,
                            alternatives_for(r, universe, held, industries=industries), cohort))
    # At most MAX_ADDS adds, the strongest first: a plan that asks for new money
    # in six places at once is a shopping list, not a plan. The rest hold.
    adds = sorted((a for a in actions if a["action"] == "ADD"), key=lambda a: -(a["score"] or 0))
    for a in adds[MAX_ADDS:]:
        a.update(action="HOLD", verb="Hold", headline=f"Hold {a['symbol']}", conviction="high",
                 todo="No change needed", move=None,
                 why=(f"Strong evidence (score {a['score']:.0f}) — a candidate to add to once the "
                      f"stronger picks above are done."))
    rank = {a: i for i, a in enumerate(ORDER)}
    conv = {"high": 0, "medium": 1, "low": 2}
    # Within a call, the most consequential first: the strongest add, the
    # biggest trim or exit.
    actions.sort(key=lambda a: (rank[a["action"]], conv[a["conviction"]],
                                -((a["score"] or 0) if a["action"] == "ADD" else (a["weight_pct"] or 0))))

    counts = {a: sum(1 for x in actions if x["action"] == a) for a in ORDER}
    freed = sum(x["move"]["value"] for x in actions if x["move"] and x["move"]["side"] == "sell")
    needed = sum(x["move"]["value"] for x in actions if x["move"] and x["move"]["side"] == "buy")
    moves = counts["EXIT"] + counts["TRIM"] + counts["AVERAGE"] + counts["ADD"]
    if not moves:
        headline = "Hold everything. Nothing in your portfolio needs a change right now."
    else:
        bits = [f"{counts[a]} to {a.lower() if a != 'AVERAGE' else 'average down'}" for a in ORDER
                if a != "HOLD" and counts[a]]
        headline = (f"{moves} of your {len(actions)} holdings need a move: " + ", ".join(bits) + ".")
    money = []
    if freed:
        money.append(f"Selling as suggested frees about {_rupees(freed)}.")
    if needed:
        money.append(f"The buys use about {_rupees(needed)}.")

    return {
        "available": True,
        "counts": counts,
        "headline": headline,
        "money": " ".join(money),
        "freed": round(freed, 2), "needed": round(needed, 2),
        "actions": actions,
        "rotation": rotation(report, universe, held),
        "method": METHOD,
        "disclaimer": DISCLAIMER,
        "universe_size": len(universe),
    }
