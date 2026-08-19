"""
Altaha Screener — Portfolio Analysis

Takes a list of holdings, runs each through the full engine, and builds a
portfolio-level picture: weights, sector mix, weighted score, health grade,
and findings.

Framing discipline: findings are observations with the arithmetic shown
("HDFCBANK is 22% of your portfolio; a single-stock shock hits you at twice
the weight of a diversified book"), never instructions to buy or sell.
Peer context comes from the last universe scan where available, and says so.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_HOLDINGS = 20
WORKERS = 3

SECTOR_CONC_LIMIT = 40.0     # % of portfolio in one sector worth flagging
STOCK_CONC_LIMIT = 15.0      # % in a single stock worth flagging
WEAK_SCORE = 40              # composite below this is a weak holding


def build_report(rows: list, scan_payload: dict | None) -> dict:
    """rows: per-holding dicts already scored. Assembles the portfolio view."""
    ok = [r for r in rows if r.get("error") is None]
    failed = [r for r in rows if r.get("error") is not None]

    total_value = sum(r["value"] for r in ok) or 0.0
    total_cost = sum(r["cost"] for r in ok if r["cost"] is not None)
    has_cost = any(r["cost"] is not None for r in ok)

    for r in ok:
        r["weight_pct"] = round(100 * r["value"] / total_value, 2) if total_value else 0.0

    # Sector aggregation
    sectors = {}
    for r in ok:
        s = r.get("sector") or "Unclassified"
        sectors.setdefault(s, {"sector": s, "value": 0.0, "count": 0})
        sectors[s]["value"] += r["value"]
        sectors[s]["count"] += 1
    sector_rows = sorted(sectors.values(), key=lambda x: x["value"], reverse=True)
    for s in sector_rows:
        s["weight_pct"] = round(100 * s["value"] / total_value, 1) if total_value else 0.0
        s["value"] = round(s["value"], 2)

    # Weighted portfolio score
    #
    # BUGFIX: this used to divide by sum(value) without checking it. A book
    # holding only zero-value rows — a fully-sold position left in the sheet,
    # a cash line, offsetting entries — made that sum zero and crashed the
    # whole report. Now a zero base falls back to a simple average, which is
    # the honest answer when weights carry no information.
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

    # Findings — observations with the arithmetic
    findings = []
    for r in ok:
        if r["weight_pct"] >= STOCK_CONC_LIMIT:
            findings.append({"kind": "concentration", "level": "flag",
                "text": f"{r['symbol']} is {r['weight_pct']:.0f}% of the portfolio. A stock-specific "
                        f"shock — results miss, governance issue, sector news — moves your whole book "
                        f"at {r['weight_pct']/10:.1f}× the impact it would have at a 10% weight."})
    top_sector = sector_rows[0] if sector_rows else None
    if top_sector and top_sector["weight_pct"] >= SECTOR_CONC_LIMIT:
        findings.append({"kind": "sector", "level": "flag",
            "text": f"{top_sector['sector']} is {top_sector['weight_pct']:.0f}% of the portfolio "
                    f"across {top_sector['count']} holding(s). One sector-wide event — a rate move, "
                    f"a regulation, a cycle turn — touches nearly half your money at once."})
    weak = [r for r in ok if (r.get("composite") or 100) < WEAK_SCORE]
    for r in weak:
        findings.append({"kind": "weak", "level": "flag",
            "text": f"{r['symbol']} scores {r['composite']}/100 on current evidence "
                    f"({r.get('setup') or 'no clear setup'}). Its full ledger in the Screener shows "
                    f"exactly which checks fail — worth reading before the next results."})
    strong = [r for r in ok if (r.get("composite") or 0) >= 72]
    if strong:
        names = ", ".join(r["symbol"] for r in strong[:4])
        findings.append({"kind": "strong", "level": "good",
            "text": f"Strongest current evidence: {names} — composite 72+ with "
                    f"setup classifications shown per holding."})
    if len(ok) < 5 and len(ok) > 0:
        findings.append({"kind": "breadth", "level": "note",
            "text": f"Only {len(ok)} holding(s). Below roughly 8–10 names, single-stock risk dominates "
                    f"portfolio behaviour regardless of how good each name is."})
    if not findings:
        findings.append({"kind": "clean", "level": "good",
            "text": "No concentration or weakness flags at current weights and scores."})

    # Peer context from the last universe scan
    peers_note = None
    scan_rows = (scan_payload or {}).get("rankings") or []
    by_sector = {}
    for sr in scan_rows:
        sec = sr.get("sector")
        if sec:
            by_sector.setdefault(sec, []).append(sr)
    if not by_sector:
        peers_note = ("Peer comparison needs a universe scan that includes sector data — "
                      "run one from the Ideas tab and re-analyse.")
    for r in ok:
        r["peers"] = []
        pool = by_sector.get(r.get("sector") or "", [])
        pool = [p for p in pool if p["symbol"] != r["symbol"]]
        pool.sort(key=lambda p: p.get("composite") or 0, reverse=True)
        r["peers"] = [{"symbol": p["symbol"], "composite": p.get("composite"),
                       "setup": p.get("setup")} for p in pool[:3]]

    return {
        "holdings": ok,
        "failed": [{"symbol": r["symbol"], "error": r["error"]} for r in failed],
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if has_cost else None,
        "total_pnl": round(total_value - total_cost, 2) if has_cost else None,
        "total_pnl_pct": round(100 * (total_value - total_cost) / total_cost, 2)
                          if has_cost and total_cost else None,
        "weighted_score": wscore,
        "grade": grade,
        "sectors": sector_rows,
        "findings": findings,
        "peers_note": peers_note,
        "peer_source": (scan_payload or {}).get("scanned_at"),
    }
