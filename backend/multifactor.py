"""
Altaha Screener — cross-sectional multi-factor ranking

THE TWO DEFECTS THIS FIXES

1. SATURATION. The engine's composite is an absolute rating being used as a
   relative ranking. Everything that survives a scan already scores 88-97 on
   setup fit, so a factor carrying 32 nominal points delivers about three
   points of actual separation. A live short-term list scored 71.0, 70.8,
   69.9, 68.5, 68.5, 68.1, 67.8, 67.6 — a 3.4-point spread with an exact tie
   in it. A ranking where every name scores the same is not ranking anything.

   The fix is to rank within the universe being scored rather than against a
   fixed scale. A percentile cannot saturate. It is also the only honest form
   for a factor whose absolute level means nothing: an earnings yield of 6% is
   good or bad only relative to what else is available today.

2. DOUBLE COUNTING. Trend structure and 52-week position correlate at 0.86 —
   they are one measurement, and between them they carry 40 of the technical
   score's 132 points. Correlated inputs given separate weights do not add
   information, they add confidence, which is the expensive kind of wrong.

   The fix is to score families, not factors. Every factor inside a family is
   averaged first, so adding a second momentum measure sharpens the momentum
   estimate instead of doubling momentum's vote.

ABOUT THE WEIGHTS
They are PRIORS, and the docstring says so because the code cannot. They come
from what is well established about equity factors — short-horizon reversal,
medium-horizon momentum, the persistence of value and quality — not from
fitting anything to this universe. Fitting weights on the same three months
used to measure them is how a backtest becomes fiction.

They are meant to be replaced. factor_lab.py measures every factor's own
information coefficient from banked point-in-time data; once that has survived
a regime it did not start in, these numbers should be revised to match it, by
a human who has read the caveats. Until then a stated prior beats a fitted
illusion.
"""

import math

try:
    import numpy as np
except Exception:                                  # pragma: no cover
    np = None

import factors as F


# Family weights per horizon. Each column sums to 100.
#
# Short is deliberately reversal-led and momentum-light. Over one to four weeks
# stocks mean-revert; over six to twelve months they trend. Running one
# momentum score across both horizons mixes a positive signal with a negative
# one, which is the most likely reason the current engine measures near zero
# at a month.
WEIGHTS = {
    "short": {"reversal": 25, "momentum": 15, "volatility": 15, "quality": 15,
              "attention": 10, "growth": 10, "value": 10},
    "medium": {"momentum": 25, "value": 20, "quality": 20, "growth": 15,
               "volatility": 10, "attention": 5, "reversal": 5},
}

# A family scored from nothing is not neutral, it is unknown. Below this share
# of a stock's families present, no rank is published for it at all — a row
# ranked on two of seven families sitting beside one ranked on seven, with
# nothing to distinguish them, is the quiet failure this project keeps making.
MIN_FAMILY_COVERAGE = 0.5

NEUTRAL = 50.0


def _percentiles(values):
    """
    Cross-sectional percentile, ties shared, None passed through.

    None means "not knowable for this stock", never zero. Scoring a missing
    factor as zero ranks the stock last on it, which is a claim the data does
    not support.
    """
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if len(idx) < 3:
        return out
    xs = np.array([float(values[i]) for i in idx])
    order = np.argsort(xs, kind="mergesort")
    ranks = np.empty(len(xs), dtype=float)
    ranks[order] = np.arange(len(xs), dtype=float)
    uniq, first, counts = np.unique(xs[order], return_index=True, return_counts=True)
    for start, n in zip(first, counts):
        if n > 1:
            ranks[order[start:start + n]] = ranks[order[start:start + n]].mean()
    pct = ranks / max(1, len(xs) - 1) * 100.0
    for k, i in enumerate(idx):
        out[i] = float(pct[k])
    return out


def rank(rows, horizon="short", weights=None):
    """
    Score a whole universe against itself.

    `rows` is [{"symbol": str, "factors": {name: value_or_None}}, ...] —
    normally straight out of factors.compute().

    Returns the same rows with `factor_score` (0-100), the family percentiles
    behind it, and a per-factor ledger. Every number carries the working, same
    as everywhere else in this project.
    """
    if np is None:
        return {"available": False, "message": "numpy unavailable"}
    rows = [r for r in (rows or []) if r.get("symbol")]
    if len(rows) < 5:
        return {"available": False,
                "message": "A cross-sectional rank needs a cross-section. "
                           "Five names is not one."}

    w = dict(weights or WEIGHTS.get(horizon) or WEIGHTS["short"])
    total_w = sum(w.values()) or 1

    names = list(F.REGISTRY)
    pct = {n: _percentiles([(r.get("factors") or {}).get(n) for r in rows]) for n in names}

    # Which factors actually varied. A factor that is None for everyone, or
    # identical for everyone, is reported as absent rather than silently
    # contributing a flat 50 to every row.
    live = {n: any(v is not None for v in pct[n]) for n in names}

    out = []
    for i, r in enumerate(rows):
        fam_vals, ledger = {}, []
        for n in names:
            family, label = F.REGISTRY[n]
            p = pct[n][i]
            ledger.append({"factor": n, "family": family, "label": label,
                           "value": (r.get("factors") or {}).get(n),
                           "percentile": None if p is None else round(p, 1)})
            if p is not None:
                fam_vals.setdefault(family, []).append(p)

        present = [f for f in w if fam_vals.get(f)]
        coverage = len(present) / max(1, len(w))

        fam_scores = {}
        score, used_w = 0.0, 0.0
        for family, weight in w.items():
            vals = fam_vals.get(family)
            if not vals:
                continue
            # Average WITHIN the family first. This is the deduplication: two
            # correlated momentum measures sharpen one estimate rather than
            # casting two votes.
            fs = float(np.mean(vals))
            fam_scores[family] = round(fs, 1)
            score += fs * weight
            used_w += weight

        row = dict(r)
        row["families"] = fam_scores
        row["factor_ledger"] = ledger
        row["family_coverage_pct"] = round(coverage * 100, 1)

        if used_w <= 0 or coverage < MIN_FAMILY_COVERAGE:
            row["factor_score"] = None
            row["factor_score_note"] = (
                f"Ranked on {len(present)} of {len(w)} factor families — too "
                "little to place this name against the others, so it is not "
                "given a score rather than given a misleading one.")
        else:
            # Renormalised over the families that were actually available, so a
            # stock missing its fundamentals is not silently pushed down by the
            # weight of the families it could not be scored on.
            row["factor_score"] = round(score / used_w, 1)
            row["factor_score_note"] = (
                f"Percentile rank against {len(rows)} names scanned today, "
                f"across {len(fam_scores)} factor families weighted for the "
                f"{horizon} horizon.")
        out.append(row)

    ranked = [r for r in out if r.get("factor_score") is not None]
    ranked.sort(key=lambda r: -r["factor_score"])
    for i, r in enumerate(ranked):
        r["factor_rank"] = i + 1

    return {
        "available": True,
        "horizon": horizon,
        "universe": len(rows),
        "ranked": len(ranked),
        "weights": w,
        "families": sorted(w),
        "factors_live": {n: live[n] for n in names},
        "rows": out,
        "method": (
            "Each factor is turned into a percentile against every other name "
            "scanned today, factors are averaged within their family, and the "
            "families are weighted for the horizon. Percentiles cannot "
            "saturate the way an absolute 0-100 score does, and averaging "
            "within a family stops two measurements of the same thing counting "
            "twice."),
        "caveat": (
            "These family weights are priors from published factor research, "
            "not values fitted to this universe. The Factor Lab replaces them "
            "with measured information coefficients once enough point-in-time "
            "history exists to measure honestly."),
    }
