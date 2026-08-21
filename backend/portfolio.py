"""
Altaha Screener — Portfolio Review

Takes a list of holdings already scored by the engine and builds the
portfolio-level picture: weights, sector tilt against the index, concentration
arithmetic, contribution to profit and loss, and an audit of the book against
the user's own stated policy.

── On the rulebook ────────────────────────────────────────────────────────
The user sets the limits — maximum weight in one stock, maximum in one sector,
minimum acceptable score, the drawdown at which a position gets re-examined.
This module then reports, with the arithmetic shown, where the book breaches
those limits and exactly what returning to them involves: the share count, the
rupee value, the resulting weight.

That is deliberately more useful than a hedge and more defensible than a call.
"Consider trimming HDFCBANK" is an opinion the platform is not registered to
give. "HDFCBANK is 24.3% against your own 15% ceiling; the gap is 61 shares,
₹1,04,700 at today's price" is arithmetic against a limit the user chose. The
judgement stays where it belongs and the output gets sharper, not vaguer.

Every finding therefore carries: the rule, the measured value, the limit, and
the arithmetic to close the gap. None of them carry an instruction.

── Framing discipline ─────────────────────────────────────────────────────
Findings are observations with the working shown, never instructions to buy or
sell. Sector context comes from measured index returns over stated windows and
says which window. Peer context comes from the last universe scan and says so.
"""

import advice

MAX_HOLDINGS = 50            # raised from 20; prices are now fetched in one batch
WORKERS = 4

WEAK_SCORE = 40              # composite below this is a weak holding
STRONG_SCORE = 72

# ---------------------------------------------------------------------------
# The rulebook
# ---------------------------------------------------------------------------
#
# Defaults are conventional rather than prescriptive — a 15% single-stock cap
# and a 35% sector cap are common retail guardrails, not the only defensible
# ones. Every value is user-editable and the payload echoes back what was
# actually applied, so a report can always be read against the rules that
# produced it.

DEFAULT_POLICY = {
    "max_stock_pct":   15.0,   # no single holding above this share of the book
    "max_sector_pct":  35.0,   # no single sector above this share
    "min_composite":   45,     # holdings scoring below this get flagged
    "review_drawdown": 25.0,   # positions down more than this get flagged
    "min_holdings":    8,      # below this, single-stock risk dominates
    "max_unclassified_pct": 20.0,   # too much unsectored book weakens the read
}

POLICY_BOUNDS = {
    "max_stock_pct":   (2.0, 100.0),
    "max_sector_pct":  (5.0, 100.0),
    "min_composite":   (0, 100),
    "review_drawdown": (5.0, 90.0),
    "min_holdings":    (1, 50),
    "max_unclassified_pct": (0.0, 100.0),
}


def clean_policy(raw: dict | None) -> dict:
    """Merge user policy over defaults, clamping each value to a sane range."""
    out = dict(DEFAULT_POLICY)
    for key, value in (raw or {}).items():
        if key not in DEFAULT_POLICY:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        lo, hi = POLICY_BOUNDS[key]
        value = max(lo, min(hi, value))
        out[key] = int(value) if isinstance(DEFAULT_POLICY[key], int) else round(value, 2)
    return out


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------

def _concentration(weights: list) -> dict:
    """
    Herfindahl index and the numbers that make it legible.

    HHI is the sum of squared weights. Its reciprocal is the effective number
    of holdings — the count of equally-weighted positions that would carry the
    same concentration. A twelve-stock book with one position at 40% behaves
    far more like a four-stock book than a twelve-stock one, and the effective
    count is the cheapest way to show that.
    """
    if not weights:
        return {"hhi": None, "effective_n": None, "top1_pct": None,
                "top3_pct": None, "top5_pct": None, "count": 0}

    fractions = [w / 100.0 for w in weights]
    hhi = sum(f * f for f in fractions)
    ordered = sorted(weights, reverse=True)

    return {
        "hhi": round(hhi, 4),
        "effective_n": round(1.0 / hhi, 1) if hhi > 0 else None,
        "top1_pct": round(ordered[0], 2),
        "top3_pct": round(sum(ordered[:3]), 2),
        "top5_pct": round(sum(ordered[:5]), 2),
        "count": len(weights),
    }


def _shares_to_cap(row: dict, cap_pct: float, total_value: float) -> dict | None:
    """
    Arithmetic for returning one position to a weight cap.

    Solving for the value that sits exactly at the cap once the sale itself
    shrinks the book: the position holds V of total T, and selling x rupees
    leaves (V - x) / (T - x) = cap. That rearranges to
    x = (V - cap*T) / (1 - cap), which is the figure a user can actually act
    on — the naive V - cap*T overstates the sale because it forgets that the
    denominator moves too.
    """
    price = row.get("price")
    value = row.get("value")
    if not price or not value or total_value <= 0:
        return None

    cap = cap_pct / 100.0
    if cap >= 1.0:
        return None

    excess_value = (value - cap * total_value) / (1.0 - cap)
    if excess_value <= 0:
        return None

    shares = int(excess_value / price)
    if shares <= 0:
        return None

    remaining_value = value - shares * price
    remaining_total = total_value - shares * price

    return {
        "shares": shares,
        "of_shares": row.get("qty"),
        "value": round(shares * price, 2),
        "price": round(price, 2),
        "resulting_weight_pct": round(100 * remaining_value / remaining_total, 2)
                                if remaining_total > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(rows: list, scan_payload: dict | None,
                 policy: dict | None = None,
                 sector_momentum: dict | None = None,
                 news_by_symbol: dict | None = None) -> dict:
    """rows: per-holding dicts already scored. Assembles the portfolio view."""
    pol = clean_policy(policy)

    ok = [r for r in rows if r and r.get("error") is None]
    failed = [r for r in rows if r and r.get("error") is not None]

    total_value = sum(r["value"] for r in ok) or 0.0
    total_cost = sum(r["cost"] for r in ok if r.get("cost") is not None)
    has_cost = any(r.get("cost") is not None for r in ok)

    for r in ok:
        r["weight_pct"] = round(100 * r["value"] / total_value, 2) if total_value else 0.0
        r["pnl"] = round(r["value"] - r["cost"], 2) if r.get("cost") is not None else None

    # ── Sector aggregation, with the index overlay where available ─────────
    sec_mom = sector_momentum or {}
    mom_rows = {s["sector"]: s for s in sec_mom.get("sectors", [])}

    sectors = {}
    for r in ok:
        s = r.get("sector") or "Unclassified"
        bucket = sectors.setdefault(s, {"sector": s, "value": 0.0, "count": 0,
                                        "symbols": [], "pnl": 0.0, "_has_pnl": False,
                                        "_score_sum": 0.0, "_score_value": 0.0})
        bucket["value"] += r["value"]
        bucket["count"] += 1
        bucket["symbols"].append(r["symbol"])
        if r.get("pnl") is not None:
            bucket["pnl"] += r["pnl"]
            bucket["_has_pnl"] = True
        if r.get("composite") is not None:
            bucket["_score_sum"] += r["composite"] * r["value"]
            bucket["_score_value"] += r["value"]

    sector_rows = sorted(sectors.values(), key=lambda x: x["value"], reverse=True)
    for s in sector_rows:
        s["weight_pct"] = round(100 * s["value"] / total_value, 2) if total_value else 0.0
        s["value"] = round(s["value"], 2)
        s["pnl"] = round(s["pnl"], 2) if s["_has_pnl"] else None
        s["avg_score"] = round(s["_score_sum"] / s["_score_value"]) if s["_score_value"] else None
        for key in ("_score_sum", "_score_value", "_has_pnl"):
            s.pop(key, None)

        mom = mom_rows.get(s["sector"])
        bench = mom.get("benchmark_weight_pct") if mom else None
        s["benchmark_weight_pct"] = bench
        s["active_weight_pct"] = round(s["weight_pct"] - bench, 2) if bench is not None else None
        s["index_name"] = mom.get("index_name") if mom else None
        s["state"] = mom.get("state") if mom else None
        s["state_why"] = mom.get("state_why") if mom else None
        s["relative"] = mom.get("relative") if mom else None
        s["returns"] = mom.get("returns") if mom else None
        s["rank_3m"] = mom.get("rank_3m") if mom else None
        s["proxy_note"] = mom.get("proxy_note") if mom else None

    # ── Weighted portfolio score ──────────────────────────────────────────
    #
    # A zero base falls back to a simple average, which is the honest answer
    # when weights carry no information — a book of fully-sold positions left
    # in the sheet would otherwise divide by zero.
    scored = [r for r in ok if r.get("composite") is not None]
    scored_value = sum(r["value"] for r in scored)
    if not scored:
        wscore = None
    elif scored_value > 0:
        wscore = round(sum(r["composite"] * r["value"] for r in scored) / scored_value)
    else:
        wscore = round(sum(r["composite"] for r in scored) / len(scored))

    if wscore is None:
        grade = "—"
    elif wscore >= 72:
        grade = "A"
    elif wscore >= 60:
        grade = "B+"
    elif wscore >= 50:
        grade = "B"
    elif wscore >= 40:
        grade = "C"
    else:
        grade = "D"

    conc = _concentration([r["weight_pct"] for r in ok])

    # ── Rulebook audit ────────────────────────────────────────────────────
    #
    # Each entry names the rule, the measured value, the limit that was set,
    # and the arithmetic to close the gap. No entry contains an instruction.
    breaches = []

    for r in sorted(ok, key=lambda x: -x["weight_pct"]):
        if r["weight_pct"] > pol["max_stock_pct"]:
            trim = _shares_to_cap(r, pol["max_stock_pct"], total_value)
            detail = ""
            if trim:
                detail = (f" The gap to your ceiling is {trim['shares']} of "
                          f"{int(trim['of_shares'])} shares — ₹{trim['value']:,.0f} at "
                          f"today's ₹{trim['price']:,.2f}, which would leave the position "
                          f"at {trim['resulting_weight_pct']:.1f}%.")
            breaches.append({
                "rule": "max_stock_pct", "level": "breach", "symbol": r["symbol"],
                "title": f"Single-stock cap · {r['symbol']}",
                "measured": r["weight_pct"], "limit": pol["max_stock_pct"],
                "arithmetic": trim,
                "text": (f"{r['symbol']} is {r['weight_pct']:.1f}% of the book against your "
                         f"{pol['max_stock_pct']:.0f}% ceiling.{detail}")
            })

    for s in sector_rows:
        if s["sector"] == "Unclassified":
            continue
        if s["weight_pct"] > pol["max_sector_pct"]:
            bench_txt = ""
            if s["benchmark_weight_pct"] is not None:
                bench_txt = (f" The Nifty 500 carries roughly "
                             f"{s['benchmark_weight_pct']:.1f}%, so the book is "
                             f"{s['active_weight_pct']:+.1f} points active here.")
            mom_txt = ""
            rel3 = (s.get("relative") or {}).get("3M")
            if s.get("state") and rel3 is not None:
                direction = "ahead of" if rel3 >= 0 else "behind"
                mom_txt = (f" {s['index_name']} is {abs(rel3):.1f}% {direction} the "
                           f"Nifty 50 over three months — {s['state'].lower()}.")
            breaches.append({
                "rule": "max_sector_pct", "level": "breach", "sector": s["sector"],
                "title": f"Sector cap · {s['sector']}",
                "measured": s["weight_pct"], "limit": pol["max_sector_pct"],
                "arithmetic": None,
                "text": (f"{s['sector']} is {s['weight_pct']:.1f}% across {s['count']} "
                         f"holding(s) against your {pol['max_sector_pct']:.0f}% ceiling."
                         f"{bench_txt}{mom_txt}")
            })

    for r in ok:
        comp = r.get("composite")
        if comp is not None and comp < pol["min_composite"]:
            breaches.append({
                "rule": "min_composite", "level": "breach", "symbol": r["symbol"],
                "title": f"Score floor · {r['symbol']}",
                "measured": comp, "limit": pol["min_composite"], "arithmetic": None,
                "text": (f"{r['symbol']} scores {comp}/100 against your floor of "
                         f"{int(pol['min_composite'])}, carrying {r['weight_pct']:.1f}% of the "
                         f"book ({r.get('setup') or 'no clear setup'}). The Screener shows "
                         f"which individual checks fail.")
            })

    for r in ok:
        pnl_pct = r.get("pnl_pct")
        if pnl_pct is not None and pnl_pct <= -pol["review_drawdown"]:
            breaches.append({
                "rule": "review_drawdown", "level": "breach", "symbol": r["symbol"],
                "title": f"Drawdown review · {r['symbol']}",
                "measured": round(pnl_pct, 2), "limit": -pol["review_drawdown"],
                "arithmetic": None,
                "text": (f"{r['symbol']} is {abs(pnl_pct):.1f}% below your average cost, past "
                         f"the {pol['review_drawdown']:.0f}% mark you set for review. "
                         f"Unrealised loss ₹{abs(r.get('pnl') or 0):,.0f}. It currently scores "
                         f"{r.get('composite') if r.get('composite') is not None else '—'}/100.")
            })

    if len(ok) and len(ok) < pol["min_holdings"]:
        breaches.append({
            "rule": "min_holdings", "level": "breach",
            "title": "Breadth floor", "measured": len(ok),
            "limit": pol["min_holdings"], "arithmetic": None,
            "text": (f"{len(ok)} holding(s) against your floor of {int(pol['min_holdings'])}. "
                     f"At this count the largest position drives portfolio behaviour more than "
                     f"the quality of any individual name — the effective count is "
                     f"{conc['effective_n']}.")
        })

    uncl = next((s for s in sector_rows if s["sector"] == "Unclassified"), None)
    if uncl and uncl["weight_pct"] > pol["max_unclassified_pct"]:
        breaches.append({
            "rule": "max_unclassified_pct", "level": "note",
            "title": "Unclassified weight", "measured": uncl["weight_pct"],
            "limit": pol["max_unclassified_pct"], "arithmetic": None,
            "text": (f"{uncl['weight_pct']:.1f}% of the book "
                     f"({', '.join(uncl['symbols'][:5])}) has no sector from the data "
                     f"provider or the bundled map, so the sector read below covers only "
                     f"{100 - uncl['weight_pct']:.0f}% of your money.")
        })

    # ── Observations that are not rule breaches ───────────────────────────
    observations = []

    strong = [r for r in ok if (r.get("composite") or 0) >= STRONG_SCORE]
    if strong:
        names = ", ".join(f"{r['symbol']} ({r['composite']})" for r in strong[:5])
        observations.append({
            "level": "good", "title": "Strongest current evidence",
            "text": (f"{names} — composite {STRONG_SCORE}+ on today's data, "
                     f"{sum(r['weight_pct'] for r in strong):.1f}% of the book combined.")
        })

    if conc["effective_n"] and conc["count"] >= 5:
        observations.append({
            "level": "note", "title": "Effective breadth",
            "text": (f"{conc['count']} holdings, but the weights concentrate them into an "
                     f"effective {conc['effective_n']} equally-sized positions. Your top three "
                     f"carry {conc['top3_pct']:.1f}% between them.")
        })

    if sec_mom.get("available"):
        placed = [s for s in sector_rows if s.get("state") and s["weight_pct"] > 0]
        lagging = [s for s in placed if s["state"] in ("Lagging", "Weakening")]
        leading = [s for s in placed if s["state"] in ("Leading", "Improving")]
        lag_w = sum(s["weight_pct"] for s in lagging)
        lead_w = sum(s["weight_pct"] for s in leading)
        if placed:
            observations.append({
                "level": "note", "title": "Money versus momentum",
                "text": (f"{lead_w:.0f}% of the book sits in sectors currently leading or "
                         f"improving against the Nifty 50 over three months; {lag_w:.0f}% sits "
                         f"in sectors lagging or weakening. Measured on index returns over the "
                         f"stated window, not a forecast.")
            })

    if not breaches:
        observations.insert(0, {
            "level": "good", "title": "No rule breaches",
            "text": ("At current prices and weights the book sits inside every limit "
                     "in your rulebook.")
        })

    # ── Contribution to profit and loss ───────────────────────────────────
    contributors = []
    if has_cost:
        with_pnl = [r for r in ok if r.get("pnl") is not None]
        contributors = [{
            "symbol": r["symbol"], "pnl": r["pnl"],
            "pnl_pct": r.get("pnl_pct"), "weight_pct": r["weight_pct"],
            "sector": r.get("sector"),
        } for r in sorted(with_pnl, key=lambda r: r["pnl"], reverse=True)]

    # ── Peer context from the last universe scan ──────────────────────────
    peers_note = None
    scan_rows = (scan_payload or {}).get("rankings") or []
    by_sec = {}
    for sr in scan_rows:
        sec = sr.get("sector")
        if sec:
            by_sec.setdefault(sec, []).append(sr)
    if not by_sec:
        peers_note = ("Peer comparison needs a universe scan that includes sector data — "
                      "run one from the Ideas tab and re-analyse.")
    for r in ok:
        pool = [p for p in by_sec.get(r.get("sector") or "", [])
                if p["symbol"] != r["symbol"]]
        pool.sort(key=lambda p: p.get("composite") or 0, reverse=True)
        r["peers"] = [{"symbol": p["symbol"], "composite": p.get("composite"),
                       "setup": p.get("setup")} for p in pool[:3]]

    # ── Per-holding action ────────────────────────────────────────────────
    #
    # Every input the call rests on is already computed above: the score, the
    # weight, the sector's state against the index, the drawdown. This joins
    # them, adds the filing feed, and asks advice.py for a verdict.
    held = {r["symbol"] for r in ok}
    news_map = news_by_symbol or {}
    sector_by_name = {s["sector"]: s for s in sector_rows}

    for r in ok:
        sec = sector_by_name.get(r.get("sector") or "Unclassified", {})
        alts = advice.find_alternatives(r, scan_rows, held)
        r["advice"] = advice.evaluate(
            r, total_value,
            sec.get("state"),
            (sec.get("relative") or {}).get("3M"),
            news_map.get(r["symbol"]),
            alts)

    action_rank = {a: i for i, a in enumerate(advice.ACTION_ORDER)}
    ordered = sorted(ok, key=lambda r: (
        action_rank.get((r.get("advice") or {}).get("action"), 9),
        -r["weight_pct"]))

    summary = advice.summarise(ok, total_value, wscore, sector_rows)

    return {
        "summary": summary,
        "holdings": ordered,
        "failed": [{"symbol": r["symbol"], "error": r["error"]} for r in failed],
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if has_cost else None,
        "total_pnl": round(total_value - total_cost, 2) if has_cost else None,
        "total_pnl_pct": round(100 * (total_value - total_cost) / total_cost, 2)
                          if has_cost and total_cost else None,
        "weighted_score": wscore,
        "grade": grade,
        "sectors": sector_rows,
        "concentration": conc,
        "policy": pol,
        "policy_defaults": DEFAULT_POLICY,
        "breaches": breaches,
        "breach_count": len([b for b in breaches if b["level"] == "breach"]),
        "observations": observations,
        "contributors": contributors,
        "sector_momentum": {
            "available": bool(sec_mom.get("available")),
            "message": sec_mom.get("message"),
            "benchmark": sec_mom.get("benchmark"),
            "sectors": sec_mom.get("sectors", []),
            "benchmark_weights_asof": sec_mom.get("benchmark_weights_asof"),
            "measured_at": sec_mom.get("measured_at"),
            "method": sec_mom.get("method"),
        },
        "peers_note": peers_note,
        "peer_source": (scan_payload or {}).get("scanned_at"),
    }
