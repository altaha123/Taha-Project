"""
One stock, one list: every trial behind the separation of the four Ideas lists.

    python research/separation_lab.py      # needs the panel: ideas_study.py --fetch --build

The four lists as first built shared most of their names (momentum and long
term 12 of 15 on the same date, this week and this month 10). This file runs
every alternative that was tried to make them different, and reports all of
them, chosen or not, in research/separation-lab.json. The count matters: the
more variants are tried, the more one of them looks good by luck, so the
trials are listed rather than only the winner (Bailey and Lopez de Prado,
"The deflated Sharpe ratio", 2014).

Same rules as ideas_study.py, whose Panel, universe and run_list this reuses:
NSE daily bhavcopy 2016-2026 with delisted companies, bought at the next open,
exit line read on the close, price returns before costs and tax. Each list is
also measured against the average liquid stock held over the same dates.

ORDER OF WORK, so the reader can judge what was chosen after seeing what
  1. Ten alternative recipes (R*) and momentum held six months: declared
     together, run together. None beat the first version on 2017-21.
  2. Three ways to give each stock one list (E1-E3): declared together.
  3. Post hoc, after seeing 2: E4 (another order) and P1 (only the two heavy
     pairs separated).
  4. Post hoc, after seeing 3: F1-F3, the month recipe R6 in place of the
     first one. F1 is what the site runs: it led on 2017-21 among the options
     that separate this week from this month.
"""

import itertools
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ideas_study as S  # noqa: E402

OUT = os.path.join(HERE, "separation-lab.json")
N = 15
HOLD = S.LISTS


def recipes(P, U):
    pct = lambda f: S.pct(f, U)
    m12, m6 = pct(P.mom_12_1 / P.vol_252), pct(P.mom_6_1 / P.vol_252)
    high, trend = pct(P.near_high), pct(P.trend_q)
    calm, dip = pct(-P.vol_252), pct(-P.ret_5)
    dip21 = pct(-P.ret_21)
    dipz = pct(-P.ret_5 / (P.vol_60 / math.sqrt(252) * math.sqrt(5)))
    quiet = pct(-P.vol_shock)
    t = pd.Series(np.arange(len(P.C), dtype=float), index=P.C.index)
    r252 = np.log(P.C).rolling(252, min_periods=240).corr(t)
    t252 = pct((r252 ** 2) * np.sign(r252) * 100)
    leader = (m12 + m6 + high + trend) / 4
    up = (P.C > P.sma200) & (P.sma50 > P.sma200)
    ok = up & (calm >= 0.20)
    strong = ok & (leader >= 0.70)
    first = S.recipes(P, U, shared=True)
    return {
        "week: first version": first["week"],
        "month: first version": first["month"],
        "momentum: first version": first["momentum"],
        "long: first version": first["long"],
        "week: R1 five-day dip in a leader": dip.where(strong),
        "week: R2 dip in its own volatility, in a leader": dipz.where(strong),
        "week: R3 quiet dip in a leader": ((dipz + quiet) / 2).where(strong),
        "month: R4 52-week high and calm": ((high + calm) / 2).where(ok),
        "month: R5 52-week high, calm and dip": ((high + calm + dip) / 3).where(ok),
        "month: R6 month dip in a leader, 52-week high": ((dip21 + high) / 2).where(strong),
        "momentum: R7 12-1, 6-1, straightness": ((m12 + m6 + trend) / 3).where(ok),
        "momentum: R8 6-1 and straightness": ((m6 + trend) / 2).where(ok),
        "long: R9 12-1, year straightness, calm": ((m12 + t252 + calm) / 3).where(ok),
        "long: R10 12-1, year straightness, 52-week high": ((m12 + t252 + high) / 3).where(ok),
    }


def ranked(score, U, dates, depth):
    out = {}
    for d in dates:
        s = score.loc[d].where(U.loc[d]).dropna()
        if len(s) >= N:
            out[d] = list(s.nlargest(depth).index)
    return out


def exclusive(lists, order):
    """Fill lists in `order`; a later one takes its next names for any already taken."""
    out = {k: {} for k in order}
    for d in set.intersection(*(set(lists[k]) for k in order)):
        taken = set()
        for k in order:
            out[k][d] = [s for s in lists[k][d] if s not in taken][:N]
            taken.update(out[k][d])
    return out


def best_fit(lists):
    """Each stock to the list it ranks highest on; a tie to the longer list."""
    later = {k: i for i, k in enumerate(HOLD)}
    out = {k: {} for k in lists}
    for d in set.intersection(*(set(lists[k]) for k in lists)):
        where = {}
        for k in lists:
            for i, s in enumerate(lists[k][d]):
                where.setdefault(s, {})[k] = i
        home = {s: min(w, key=lambda k: (w[k], -later[k])) for s, w in where.items()}
        for k in lists:
            out[k][d] = [s for s in lists[k][d] if home[s] == k][:N]
    return out


def overlap(lists):
    keys = list(HOLD)
    common = set.intersection(*(set(lists[k]) for k in keys))
    out = {f"{a} / {b}": round(float(np.mean([len(set(lists[a][d][:N]) & set(lists[b][d][:N]))
                                               for d in common])), 1)
           for a, b in itertools.combinations(keys, 2)}
    out["distinct in all four"] = round(float(np.mean(
        [len(set().union(*(set(lists[k][d][:N]) for k in keys))) for d in common])), 1)
    return out


def measure(P, U, picks, key, hold=None, exit_pct=None):
    h, e = HOLD[key]
    h, e = hold or h, exit_pct or e
    ok = [(d, v[:N]) for d, v in sorted(picks.items()) if P.C.index.get_loc(d) < len(P.C) - h - 1]
    df = S.run_list(P, ok, h, e)
    d = S.describe(df)
    v = S.vs_average_stock(P, U, df, h)
    return {"up_pct": d["up_pct"], "avg_pct": d["avg_pct"], "index_avg_pct": d["index_avg_pct"],
            "worst_5pct": d["worst_5pct"], "excess_pct": v["excess_pct"], "t": v["t"],
            "excess_2017_21": v["by_half"]["2017-21"]["excess_pct"],
            "excess_2022_26": v["by_half"]["2022-26"]["excess_pct"]}


def main():
    t0 = time.time()
    P = S.Panel()
    U = P.universe(10)
    R = recipes(P, U)
    dates = P.C.index[262:-1:5]
    ranks = {name: ranked(sc, U, dates, 90) for name, sc in R.items()}
    out = {"generated": time.strftime("%Y-%m-%d"),
           "rules": ("As research/ideas_study.py: bought at the next open, held for the list's "
                     "period, left on a close under its exit line, before costs and tax. "
                     "excess_pct is the list's average pick less the average liquid stock "
                     "held over the same dates; t is its Newey-West t-statistic."),
           "trials": 0, "recipes": {}, "separation": {}}

    for name in R:
        key = name.split(":")[0]
        out["recipes"][name] = measure(P, U, ranks[name], key)
    for name in ("momentum: first version", "momentum: R7 12-1, 6-1, straightness"):
        out["recipes"][name + ", held six months, line 20%"] = measure(P, U, ranks[name], "momentum", 126, 20.0)
    out["trials"] += len(out["recipes"]) - 4            # the four first-version rows are the baseline

    first = {k: ranks[f"{k}: first version"] for k in HOLD}
    r6 = ranks["month: R6 month dip in a leader, 52-week high"]
    lm = exclusive({"long": first["long"], "momentum": first["momentum"]}, ["long", "momentum"])
    schemes = {
        "first version: shared": {k: {d: v[:N] for d, v in first[k].items()} for k in HOLD},
        "E1 longest first": exclusive(first, ["long", "momentum", "month", "week"]),
        "E2 shortest first": exclusive(first, ["week", "month", "momentum", "long"]),
        "E3 best fit": best_fit(first),
        "E4 long, momentum, week, month (post hoc)": exclusive(first, ["long", "momentum", "week", "month"]),
        "P1 momentum gives way to long, month to week (post hoc)": {
            **exclusive({"week": first["week"], "month": first["month"]}, ["week", "month"]),
            "momentum": lm["momentum"], "long": first["long"]},
        "F1 R6 for month, momentum gives way to long (post hoc; the site runs this)": {
            "week": first["week"], "month": r6, "momentum": lm["momentum"], "long": first["long"]},
        "F2 F1, and month gives way to week (post hoc)": {
            "week": first["week"], "month": exclusive({"week": first["week"], "month": r6},
                                                      ["week", "month"])["month"],
            "momentum": lm["momentum"], "long": first["long"]},
        "F3 R6 for month, every list gives way, long first (post hoc)": exclusive(
            {"long": first["long"], "momentum": first["momentum"], "week": first["week"], "month": r6},
            ["long", "momentum", "week", "month"]),
    }
    for name, lists in schemes.items():
        lists = {k: {d: v[:N] for d, v in lists[k].items()} for k in HOLD}
        out["separation"][name] = {"overlap": overlap(lists),
                                   "lists": {k: measure(P, U, lists[k], k) for k in HOLD}}
        print(name, json.dumps(out["separation"][name]["overlap"]), flush=True)
    out["trials"] += len(schemes) - 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("wrote", OUT, "in", round(time.time() - t0), "s;", out["trials"], "trials")


if __name__ == "__main__":
    main()
