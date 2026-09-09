"""Altaha Score v4: one cross-sectional ranker; no fitted production weights.

See SCORING-V4.md. Raw factors are higher-is-better. Winsorise inside the
eligible peer pool, midrank ties, average groups then families, apply profile
priors and shrink the result towards 50 using observable data confidence.
"""
import math
import numpy as np
import factors as F
import profiles as P

NEUTRAL = 50.0
MIN_PEERS = 10
FULL_PEERS = 30
WEIGHTS = {**P.V4_WEIGHTS, "short": P.V4_WEIGHTS["trade"],
           "medium": P.V4_WEIGHTS["position"]}


def _percentiles(values, min_peers=MIN_PEERS):
    out = [None] * len(values)
    idx = [i for i, v in enumerate(values) if F.finite(v) is not None]
    if len(idx) < min_peers:
        return out
    xs = np.asarray([float(values[i]) for i in idx])
    lo, hi = np.quantile(xs, [.02, .98])
    xs = np.clip(xs, lo, hi)
    from factor_lab import _ranks
    pct = _ranks(xs) / (len(xs)-1) * 100
    for j, i in enumerate(idx):
        out[i] = float(pct[j])
    return out


def _model(row):
    # Historical callers must pass contemporaneous metadata, never current info.
    return P.classify({"sector": row.get("sector"), "industry": row.get("industry"),
                       "trailingEps": row.get("trailing_eps")})


def rank(rows, horizon="short", weights=None):
    rows = [dict(r) for r in (rows or []) if isinstance(r, dict) and r.get("symbol")]
    if len({r["symbol"] for r in rows}) != len(rows):
        raise ValueError("Duplicate symbols would distort peer ranks")
    if len(rows) < MIN_PEERS:
        return {"available": False, "message": f"A scan needs at least {MIN_PEERS} distinct peers.", "rows": []}
    h = {"short": "trade", "medium": "position"}.get(horizon, horizon)
    if h not in P.V4_WEIGHTS:
        h = "trade"
    models = [_model(r) for r in rows]
    caps = [F.finite(r.get("market_cap")) for r in rows]
    caps = [v if v is not None and v > 0 else None for v in caps]
    cpct = _percentiles(caps)
    sizes = [None if v is None else "large" if v >= 70 else "mid" if v >= 30 else "small" for v in cpct]
    ledgers = [[] for r in rows]
    # Precompute each peer distribution once, not once per stock/request.
    for name, spec in F.SPEC.items():
        vals = []
        for r, m in zip(rows, models):
            val = F.finite((r.get("factors") or {}).get(name))
            if not F.eligible(name, m["key"]) or (name not in F.PRICE_FACTORS and
                    ((r.get("factors") or {}).get("_fundamentals_stale") or (r.get("data_quality") or {}).get("stale"))):
                val = None
            vals.append(val)
        pools = {}
        def keys(i):
            # Never broaden lender accounting metrics to non-financials.
            domain = "market" if name in F.PRICE_FACTORS else ("lender" if models[i]["key"] == "lender" else "corporate")
            keys = [(domain, "model", models[i]["key"])]
            if rows[i].get("sector"):
                keys.append((domain, "sector", rows[i]["sector"]))
            if sizes[i]:
                keys.append((domain, "size", sizes[i]))
            keys.append((domain, "universe", "eligible"))
            return keys
        for i, v in enumerate(vals):
            if v is not None:
                for key in keys(i):
                    pools.setdefault(key, []).append(i)
        stats = {}
        for key, ids in pools.items():
            if len(ids) >= MIN_PEERS:
                stats[key] = dict(zip(ids, _percentiles([vals[i] for i in ids])))
        for i, r in enumerate(rows):
            applicable = F.eligible(name, models[i]["key"])
            key = next((k for k in keys(i) if k in stats), None) if vals[i] is not None else None
            p = stats[key].get(i) if key else None
            reason = None if p is not None else ("not applicable to business model" if not applicable else
                     "missing, invalid, stale, or insufficient history" if vals[i] is None else "fewer than 10 eligible peers")
            ledgers[i].append({"factor": name, "family": spec.family, "group": spec.group,
                "label": spec.label, "value": vals[i], "percentile": p, "applicable": applicable,
                "peer_group": ":".join(key) if key else None, "peer_count": len(pools[key]) if key else 0,
                "missing_reason": reason, "transformation": spec.winsorisation,
                "explanation": (f"{spec.label}: {vals[i]:.4g} — {p:.1f} percentile among {len(pools[key])} {key[1]} peers"
                                if p is not None else f"{spec.label}: {reason}")})
    out = []
    for i, row in enumerate(rows):
        ledger, model = ledgers[i], models[i]
        groups = {}
        for e in ledger:
            if e["percentile"] is not None:
                groups.setdefault(e["family"], {}).setdefault(e["group"], []).append(e["percentile"])
        group_scores = {f: {g: float(np.mean(v)) for g, v in gs.items()} for f, gs in groups.items()}
        dq = dict(row.get("data_quality") or {})
        age = F.finite(dq.get("period_age_days"))
        fresh = 0. if age is None or age > F.STALE_AFTER_DAYS else max(.5, 1 - max(0, age-135) / 180)
        source = 1. if dq.get("source_valid") is True else .5
        history = min(1., max(0., (F.finite(dq.get("history_quarters")) or 0) / 13))
        reasons = []
        if fresh < 1: reasons.append("Fundamentals are missing, ageing or stale")
        if source < 1: reasons.append("Filing source provenance is incomplete")
        if history < 1: reasons.append("Quarterly history is incomplete for persistence/surprise")
        if model["key"] == "lender": reasons.append("Lender P/B, NPA, NIM and capital adequacy inputs are unavailable")
        v4 = {"methodology_version": "v4", "business_model": model["key"], "model": model,
              "market_cap_bucket": sizes[i], "peer_group": row.get("sector") or model["key"],
              "factor_ledger": ledger, "data_quality": dq, "as_of": dq.get("as_of")}
        for hz in P.V4_WEIGHTS:
            fs = {}
            for family, gs in group_scores.items():
                # Reversal is strongest at days/weeks; fixed subweights prevent
                # adding duplicate risk metrics from creating another vote.
                if family == "risk":
                    rw = {"reversal": .65 if hz == "trade" else .20 if hz == "position" else 0.,
                          "volatility": .35 if hz == "trade" else .80 if hz == "position" else 1.}
                    den = sum(rw[g] for g in gs)
                    if den: fs[family] = sum(v*rw[g] for g,v in gs.items()) / den
                else:
                    fs[family] = float(np.mean(list(gs.values())))
            w = P.v4_weights(model["key"], hz)
            if weights is not None and hz == h:
                if any(k not in w or F.finite(v) is None or v < 0 for k,v in weights.items()) or sum(weights.values()) <= 0:
                    raise ValueError("Weights must be finite non-negative v4 pillar priors")
                w = {k: float(weights.get(k,0))/sum(weights.values()) for k in w}
            present = [f for f in w if f in fs and w[f] > 0]
            total = sum(w[f] for f in present)
            raw = sum(fs[f] * w[f] for f in present)/total if total else 50.
            coverage = len(present)/len(w)
            # Confidence is based on REQUIRED groups, never a renormalised denominator.
            # An inapplicable pillar (e.g. missing banking strength toolkit) remains unknown.
            confidence = 0.
            contributions = []
            for family in w:
                required = {s.group for n,s in F.SPEC.items() if s.family == family and F.eligible(n, model["key"])}
                if hz == "invest" and family == "risk": required.discard("reversal")
                have = {g for g in group_scores.get(family,{}) if g in required}
                group_cov = len(have)/len(required) if required else 0.
                entries = [e for e in ledger if e["family"] == family and e["percentile"] is not None and e["group"] in required]
                peer = float(np.mean([min(1., e["peer_count"]/FULL_PEERS) for e in entries])) if entries else 0.
                is_price = family in ("momentum", "risk", "participation")
                reliability = 1. if is_price else fresh * source * (.5 + .5*history)
                confidence += w[family] * group_cov * peer * reliability
                if family in present:
                    contributions.append({"pillar": family, "pillar_score": fs[family],
                        "weight": w[family]/total, "points": fs[family]*w[family]/total})
            confidence = max(0., min(1., confidence))
            final = 50 + (raw-50)*confidence
            v4[hz] = {"raw_score": raw, "final_score": final, "confidence": confidence,
                      "family_coverage_pct": coverage*100, "weights": w, "pillars": fs,
                      "contribution": contributions}
        selected = v4[h]
        missing = [e["factor"] for e in ledger if e["applicable"] and e["percentile"] is None]
        if missing: reasons.append(f"{len(missing)} applicable factors unavailable")
        if any(0 < e["peer_count"] < FULL_PEERS for e in ledger): reasons.append("Some peer groups have fewer than 30 observations")
        dq.update(confidence_reasons=reasons, missing_factors=missing,
                  factor_coverage_pct=100*sum(e["percentile"] is not None for e in ledger)/max(1,sum(e["applicable"] for e in ledger)))
        v4["pillars"] = selected["pillars"]
        v4["families"] = selected["pillars"]
        positives = sorted([e for e in ledger if e["percentile"] is not None and e["percentile"] > 50], key=lambda e:-e["percentile"])
        negatives = sorted([e for e in ledger if e["percentile"] is not None and e["percentile"] < 50], key=lambda e:e["percentile"])
        v4["what_helped"], v4["what_hurt"] = positives[:3], negatives[:3]
        row.update(altaha_score_v4=v4, factor_score=selected["final_score"],
                   raw_factor_score=selected["raw_score"], final_factor_score=selected["final_score"],
                   confidence_score=selected["confidence"], family_coverage_pct=selected["family_coverage_pct"],
                   families=selected["pillars"], factor_ledger=ledger,
                   factor_score_note="Altaha Score v4; confidence shrinks missing families toward 50.")
        for hz in P.V4_WEIGHTS: row[hz+"_score"] = v4[hz]["final_score"]
        out.append(row)
    ordered = sorted(out, key=lambda r: (-r["factor_score"], r["symbol"]))
    previous, rank_no = None, 0
    for j,r in enumerate(ordered):
        if r["factor_score"] != previous: rank_no = j+1
        r["factor_rank"] = rank_no
        previous = r["factor_score"]
    return {"available": True, "horizon": horizon if horizon in WEIGHTS else "short", "rows": out,
            "universe": len(rows), "ranked": len(rows), "methodology_version": "v4",
            "families": F.FAMILIES, "weights": P.V4_WEIGHTS[h],
            "factors_live": {n:any(e["factor"] == n and e["percentile"] is not None for ls in ledgers for e in ls) for n in F.SPEC},
            "method": "Peer percentiles, group means, family priors, confidence shrinkage to 50.",
            "caveat": "Fixed prior weights, not fitted. Scores are research rankings, not probabilities of profit."}


def presentation(v4, horizon="position"):
    """Compatibility adapter for the existing scoring frontend, from v4 only."""
    h = horizon if horizon in P.V4_WEIGHTS else "position"
    s = v4[h]
    value = s["final_score"]
    label, tone = ("STRONG", "strong") if value >= 72 else ("CONSTRUCTIVE", "constructive") if value >=55 else ("MIXED", "mixed") if value >=40 else ("WEAK", "weak")
    missing = v4["data_quality"]["missing_factors"]
    return {"score": value, "label": label, "tone": tone, "methodology_version": "v4",
            "confidence": round(100*s["confidence"],1), "model": v4["model"], "horizon": h,
            "horizon_label": P.HORIZONS[h]["label"], "horizon_note": P.HORIZONS[h]["note"],
            "basis": "Altaha Score v4 · peer-relative · as of " + str(v4.get("as_of") or "scan date"),
            "summary": "; ".join(v4["data_quality"]["confidence_reasons"]),
            "pillars": s["pillars"], "weights": s["weights"], "contribution": s["contribution"],
            "factor_ledger": v4["factor_ledger"], "raw_score": s["raw_score"],
            "coverage": {"present": sum(e["percentile"] is not None for e in v4["factor_ledger"]),
                         "total": sum(e["applicable"] for e in v4["factor_ledger"]), "missing": missing},
            "dropped": [{"check":e["label"], "reason":e["missing_reason"]} for e in v4["factor_ledger"] if not e["applicable"]]}
