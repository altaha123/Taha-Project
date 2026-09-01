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
    if len(x) < 3:
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
           "dates_measured": len(dates), "observations": len(rows),
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


def _verdict(ic, n_dates):
    if ic >= 0.03:
        return ("Carries signal at the strength a real equity factor carries it. "
                "That means right about 52% of the time, which is how this works.")
    if ic >= 0.01:
        return "Weakly positive. Not yet distinguishable from noise on this sample."
    if ic > -0.01:
        return "No measurable signal. It is contributing points and no information."
    return ("Negative. On this sample the factor ranked backwards — every point "
            "it contributes is subtracted from the score's accuracy.")


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
            "hit_rate_pct": r.get("hit_rate_pct"),
            "quintile_spread_pct": r.get("quintile_spread_pct"),
            "reliable": r.get("reliable", False),
            "verdict": r.get("verdict") or r.get("message"),
        })
    out.sort(key=lambda r: (r["mean_ic"] is None, -(r["mean_ic"] or -9)))
    return {"available": True, "horizon_days": horizon_days,
            "factors": out, "count": len(out)}
