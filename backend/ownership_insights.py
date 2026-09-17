"""Ownership comparisons from disclosed holdings; never infer trades or exits."""
import datetime as dt
import math
import re

INSTITUTION_KINDS = {"Mutual fund", "Insurance", "Pension fund", "Institution",
                     "Foreign institution", "Foreign portfolio investor"}


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def holder_key(row):
    # Whitespace/case only. Fuzzy matching can merge different fund schemes.
    return (bool(row.get("promoter")), " ".join(row["name"].casefold().split()))


def named_insights(latest, quarters, previous, limit=40):
    """History includes gaps, not invented zero holdings. No PANs leave parser."""
    records = sorted(quarters, key=lambda r: r["period"])
    current = {holder_key(n): n for n in latest.get("names", []) if number(n.get("pct")) is not None}
    before = {holder_key(n): n for n in (previous or {}).get("names", []) if number(n.get("pct")) is not None}
    can_compare = bool(previous and any(r["period"] == latest["period"] for r in quarters))
    histories = [(r, {holder_key(n): n for n in r.get("names", [])}) for r in records]
    result = {"promoters": [], "public": [], "no_longer_disclosed": []}
    for key, row in sorted(current.items(), key=lambda pair: -pair[1]["pct"]):
        old = before.get(key) if can_compare else None
        old_pct = number((old or {}).get("pct"))
        points = [{"period": r["period"], "pct": number((ns.get(key) or {}).get("pct")),
                   "source": r.get("source")} for r, ns in histories]
        seen = next((p["period"] for p in points if p["pct"] is not None), None)
        delta = round(row["pct"] - old_pct, 4) if old_pct is not None else None
        entry = {"name": row["name"], "kind": row.get("kind"), "pct": row["pct"],
                 "institutional": not key[0] and row.get("kind") in INSTITUTION_KINDS,
                 "previous_pct": old_pct, "change_qoq": delta,
                 "new_in_table": can_compare and key not in before,
                 "status": ("newly_disclosed" if can_compare and key not in before else
                            "comparison_unavailable" if delta is None else
                            "increased" if delta >= .005 else "reduced" if delta <= -.005 else "unchanged"),
                 "history": points, "first_seen": seen,
                 "source": latest.get("source")}
        bucket = "promoters" if key[0] else "public"
        if len(result[bucket]) < limit:
            result[bucket].append(entry)
    if can_compare:
        result["no_longer_disclosed"] = [
            {"name": row["name"], "kind": row.get("kind"), "previous_pct": row["pct"],
             "pct": None, "change_qoq": None, "status": "no_longer_disclosed",
             "source": previous.get("source")}
            for key, row in sorted(before.items(), key=lambda pair: -pair[1]["pct"])
            if key not in current and not key[0]][:limit]
    result["coverage"] = {"public_total": sum(not key[0] for key in current),
                          "promoter_total": sum(key[0] for key in current),
                          "limit_per_group": limit, "history_start": records[0]["period"] if records else None,
                          "comparison_period": previous.get("period") if can_compare else None}
    return result


def peer_candidates(symbol, rows, fallback):
    """Same sector only, deterministic alphabetical sample, no score ranking."""
    clean = lambda s: re.sub(r"\.(NS|BO)$", "", str(s or "").upper())
    symbol = clean(symbol)
    scan = {clean(r.get("symbol")): r for r in rows if r.get("symbol")}
    sector = (scan.get(symbol) or {}).get("sector")
    source = "latest universe scan"
    if sector and sector.lower() not in {"unknown", "unclassified", "other"}:
        peers = [s for s, r in scan.items() if s != symbol and r.get("sector") == sector]
    else:
        sector = fallback.get(symbol)
        source = "bundled sector map"
        peers = [s for s, sec in fallback.items() if s != symbol and sec == sector] if sector else []
    return {"sector": sector, "classification_source": source, "candidates": sorted(peers)[:20],
            "selection": "Alphabetical same-sector sample; sectors may include different business models."}


def comparison_at(symbol, period, reader):
    """Fetch only the requested quarter and preceding quarter (at most 2 XMLs)."""
    day = dt.date.fromisoformat(period)
    if not reader.is_quarter_end(period):
        raise ValueError("Comparison requires a quarter-end date.")
    unavailable = {"symbol": symbol, "period": period, "available": False}
    rows = reader.index(symbol)
    target = next((r for r in rows if r["period"] == period), None)
    if not target:
        return {**unavailable, "message": "No filing for the matching quarter."}
    older = next((r for r in rows if reader.is_quarter_end(r["period"]) and
                  60 <= (day - dt.date.fromisoformat(r["period"])).days <= 135), None)
    def read(row):
        return reader.filing(row["xbrl"], period=row["period"], filed=row["filed"], revised=row["revised"]) if row else None
    current, previous = read(target), read(older)
    if not current or not current.get("categories"):
        return {**unavailable, "message": "The matching filing could not be read."}
    def val(record, key):
        return number(((record or {}).get("categories", {}).get(key) or {}).get("pct"))
    metrics = {}
    for key in ("promoter", "fii", "dii"):
        now, old = val(current, key), val(previous, key)
        if key == "promoter" and now is None and val(current, "total") == 100 and val(current, "public_total") == 100:
            now = 0.0
        metrics[key] = {"pct": now, "change_qoq": round(now - old, 4) if now is not None and old is not None else None,
                        "derived": bool((current["categories"].get(key) or {}).get("derived"))}
    f, d = metrics["fii"], metrics["dii"]
    metrics["institutions"] = {"pct": round(f["pct"] + d["pct"], 4) if f["pct"] is not None and d["pct"] is not None else None,
        "change_qoq": round(f["change_qoq"] + d["change_qoq"], 4) if f["change_qoq"] is not None and d["change_qoq"] is not None else None,
        "derived": f["derived"] or d["derived"]}
    return {"symbol": symbol, "period": period, "available": True, "metrics": metrics,
            "source": current.get("source"), "filed": current.get("filed"),
            "pledge_pct": None, "pledge_message": "Not available from this reader."}
