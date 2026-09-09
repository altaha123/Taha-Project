"""
Altaha Screener — the Factor Lab

Answers one question for every factor the engine records: does it predict
anything?

THE STATISTIC, AND WHY THIS ONE
The information coefficient. On each date, rank every stock by the factor,
rank the same stocks by what they went on to do relative to the index, and
correlate the two rankings. Average that across dates.

It is the right measure because it matches the claim. This engine does not
forecast a price; it orders a list. IC asks exactly whether that ordering was
better than shuffling, and nothing else.

WHAT A GOOD NUMBER LOOKS LIKE — WORTH KNOWING BEFORE READING ANY OUTPUT
A serious, professionally traded equity factor runs an IC of 0.03 to 0.05.
That is a signal which is right about 52% of the time. It is not a typo and it
is not a weak result: money is made from it by applying it across hundreds of
names, hundreds of times, not by being right about any one of them. Anything
above 0.10 sustained over years is either a genuine discovery or, far more
often, a bug — a lookahead leak, a survivorship filter, or a factor that has
quietly been fitted to the sample it is being tested on.

WHAT THIS MODULE REFUSES TO DO
It does not fit weights. Choosing weights on the same data used to measure them
is how a backtest becomes fiction, and this file is the one place in the
project that must not lie. It reports; the reweighting is a decision made
elsewhere, deliberately, by a human who has read the caveats.

NO SCIPY
Spearman here is Pearson on ranks, computed in numpy. Adding a scientific
stack to a web service to avoid twelve lines of arithmetic is not a trade
worth making.
"""

import math

try:
    import numpy as np
except Exception:                                  # pragma: no cover
    np = None

import pit_store

# Below this, a date's cross-section is too thin to rank meaningfully. Ranking
# eight stocks against each other produces an IC that swings between +1 and -1
# on noise and averages into the result as though it were a real observation.
MIN_CROSS_SECTION = 25

# Below this many dates, no summary is offered at all. Not a soft warning —
# the number is withheld, because a mean IC over three overlapping fortnights
# is a number people will quote and nobody will caveat.
MIN_DATES = 8


def _ranks(a):
    """Average ranks, ties shared — the ordinary Spearman convention."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(len(a), dtype=float)
    # Share ranks across ties so a check scored 0 or 10 for everyone does not
    # invent an ordering out of array position.
    _, first, counts = np.unique(a[order], return_index=True, return_counts=True)
    for start, n in zip(first, counts):
        if n > 1:
            ranks[order[start:start + n]] = ranks[order[start:start + n]].mean()
    return ranks


def _spearman(x, y):
    if len(x) < 3 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        return None
    rx, ry = _ranks(np.asarray(x, float)), _ranks(np.asarray(y, float))
    sx, sy = rx.std(), ry.std()
    if sx <= 0 or sy <= 0:
        return None
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def evaluate(factor, horizon_days=21, min_cross_section=MIN_CROSS_SECTION):
    """
    One factor, one horizon.

    Returns per-date detail as well as the summary. The detail is the honest
    part: a mean IC of +0.04 built from dates of +0.31, -0.22 and +0.03 is a
    different object from one built from +0.05, +0.03 and +0.04, and only the
    second is worth acting on.
    """
    if np is None:
        return {"available": False, "message": "numpy unavailable"}

    rows = pit_store.training_set(factor, horizon_days)
    if not rows:
        return {"available": False, "factor": factor, "horizon_days": horizon_days,
                "message": "No labelled observations yet for this factor and horizon."}

    by_date = {}
    for as_of, _sym, x, y in rows:
        if math.isfinite(x) and math.isfinite(y):
            by_date.setdefault(as_of, []).append((x, y))

    dates = []
    for as_of in sorted(by_date):
        pairs = by_date[as_of]
        if len(pairs) < min_cross_section:
            continue
        xs = np.array([p[0] for p in pairs], float)
        ys = np.array([p[1] for p in pairs], float)
        ic = _spearman(xs, ys)
        if ic is None:
            continue
        q = _ranks(xs) / max(1, len(xs) - 1)
        top = ys[q > 0.8]
        bot = ys[q <= 0.2]
        dates.append({
            "date": as_of, "n": len(pairs), "ic": round(ic, 4),
            "top_quintile_pct": round(float(top.mean()), 3) if len(top) else None,
            "bottom_quintile_pct": round(float(bot.mean()), 3) if len(bot) else None,
        })

    out = {"available": True, "factor": factor, "horizon_days": horizon_days,
           "dates_measured": len(dates), "observations": sum(d["n"] for d in dates),
           "observations_available": len(rows), "statistically_validated": False,
           "per_date": dates}

    if len(dates) < MIN_DATES:
        out["reliable"] = False
        out["message"] = (
            f"Only {len(dates)} date{'s' if len(dates) != 1 else ''} measured. "
            f"No average is reported below {MIN_DATES} — an information "
            "coefficient from a handful of overlapping windows is noise with a "
            "decimal point, and it would be quoted as though it were not.")
        return out

    ics = np.array([d["ic"] for d in dates], float)
    mean, sd = float(ics.mean()), float(ics.std(ddof=1))
    spreads = [d["top_quintile_pct"] - d["bottom_quintile_pct"] for d in dates
               if d["top_quintile_pct"] is not None and d["bottom_quintile_pct"] is not None]

    out.update({
        "reliable": True,
        "mean_ic": round(mean, 4),
        "ic_sd": round(sd, 4),
        "ic_information_ratio": round(mean / sd, 4) if sd > 0 else None,
        "top_quintile_pct": _mean_present([d["top_quintile_pct"] for d in dates]),
        "bottom_quintile_pct": _mean_present([d["bottom_quintile_pct"] for d in dates]),
        "hit_rate_pct": round(100.0 * float((ics > 0).mean()), 1),
        "quintile_spread_pct": round(float(np.mean(spreads)), 3) if spreads else None,
        "t_stat": round(mean / sd * math.sqrt(len(ics)), 2) if sd > 0 else None,
        "verdict": _verdict(mean, len(ics)),
        "caveat": (
            "Windows overlap, so the t-statistic is optimistic — treat it as a "
            "rough guide, never as a significance test. An IC is only worth "
            "acting on after it has survived a market regime it was not "
            "measured in."),
    })
    return out


def _mean_present(values):
    vs = [v for v in values if v is not None]
    return round(float(np.mean(vs)), 4) if vs else None


def _verdict(ic, n_dates):
    if ic > .01:
        return "Positive sample rank association; out-of-sample validation is still required."
    if ic >= -.01:
        return "No measurable signal on this sample; absence of evidence is not evidence of absence."
    return "Negative sample association: ranks ran backwards; this does not establish future behaviour."


def sweep(horizon_days=21, factors=None, min_cross_section=MIN_CROSS_SECTION):
    """
    Every factor at one horizon, ranked by measured IC.

    This is the table that decides what the engine should stop scoring.
    """
    names = factors or pit_store.factor_names()
    out = []
    for f in names:
        r = evaluate(f, horizon_days, min_cross_section)
        if not r.get("available"):
            continue
        out.append({
            "factor": f,
            "dates": r.get("dates_measured"),
            "observations": r.get("observations"),
            "mean_ic": r.get("mean_ic"),
            "ic_sd": r.get("ic_sd"),
            "ic_information_ratio": r.get("ic_information_ratio"),
            "top_quintile_pct": r.get("top_quintile_pct"),
            "bottom_quintile_pct": r.get("bottom_quintile_pct"),
            "hit_rate_pct": r.get("hit_rate_pct"),
            "quintile_spread_pct": r.get("quintile_spread_pct"),
            "reliable": r.get("reliable", False),
            "verdict": r.get("verdict") or r.get("message"),
        })
    out.sort(key=lambda r: (r["mean_ic"] is None, -(r["mean_ic"] or -9)))
    return {"available": True, "horizon_days": horizon_days,
            "factors": out, "count": len(out)}


def correlations(names=None, min_cross_section=MIN_CROSS_SECTION, max_dates=126):
    """Date-wise Spearman correlations; bounded to the latest 126 scan dates.

    Warning requires >=8 dates and |rho|>=.85 on >=75% of dates. Correlation
    is diagnostic only and never changes production weights automatically.
    """
    import factors as F
    from itertools import combinations
    names = names or ["v4_raw_" + n for n in F.SPEC]
    pairs = {}
    dates = pit_store.snapshot_dates()[-max_dates:]
    for date in dates:
        snapshot = pit_store.get_snapshot(date)
        for a,b in combinations(names, 2):
            obs = [(r.get(a),r.get(b)) for r in snapshot.values()
                   if F.finite(r.get(a)) is not None and F.finite(r.get(b)) is not None]
            if len(obs) < min_cross_section: continue
            rho = _spearman([x for x,y in obs],[y for x,y in obs])
            if rho is not None: pairs.setdefault((a,b), []).append(rho)
    rows = []
    for (a,b), rs in pairs.items():
        enough = len(rs) >= MIN_DATES
        frequency = sum(abs(r) >= .85 for r in rs)/len(rs)
        rows.append({"factor_a":a, "factor_b":b, "dates":len(rs),
                     "mean_correlation":float(np.mean(rs)) if enough else None,
                     "high_correlation_frequency":frequency if enough else None,
                     "warning":enough and frequency >= .75})
    return {"available":True, "pairs":rows, "dates_examined":len(dates),
            "threshold":.85, "minimum_dates":MIN_DATES, "automatic_changes":False}


def suggested_weights(horizon_days=63):
    """Research-only suggestions with chronological held-out observations.

    At least 60 NON-overlapping evaluation dates per pillar, after 126 warm-up
    dates, are required. No optimizer, no production consumer, no activation.
    Even this gate does not establish significance or remove survivorship bias.
    """
    import profiles as P
    import datetime as dt
    dates = pit_store.snapshot_dates()
    if len(dates) < 127:
        return {"available":False, "automatic_changes":False,
                "message":"Need 126 warm-up dates plus sufficient held-out non-overlapping history."}
    start = dates[126]
    measurements = {}
    for family in P.V4_WEIGHTS["position"]:
        report = evaluate("v4_position_family_" + family, horizon_days)
        chosen, last = [], None
        for row in report.get("per_date", []):
            date = dt.date.fromisoformat(row["date"])
            if row["date"] < start or (last and (date-last).days < math.ceil(horizon_days*1.55)+2):
                continue
            chosen.append(row["ic"]); last = date
        if len(chosen) < 60:
            return {"available":False, "automatic_changes":False,
                    "message":"Need 60 held-out non-overlapping dates per pillar; fixed priors remain active."}
        measurements[family] = max(0., float(np.mean(chosen)))
    den = sum(measurements.values())
    if den <= 0:
        return {"available":False,"automatic_changes":False,"message":"No positive held-out association."}
    prior = P.V4_WEIGHTS["position"]
    return {"available":True, "automatic_changes":False, "research_only":True,
            "held_out_from":start, "suggested_weights":{
                f:.7*prior[f]/100 + .3*v/den for f,v in measurements.items()},
            "caveat":"Requires human review and further independent validation; not deployed weights."}
