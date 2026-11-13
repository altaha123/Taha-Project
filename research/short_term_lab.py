"""
The short-term list: which version, decided before looking at 2022-26.

WHAT WAS ASKED FOR
One short-term list: stocks that have consolidated and are breaking out or
on the verge of it, picked on fundamentals, technicals, the industry and
the news together, with the highest hit rate that can honestly be had.

WHAT IS TRIED (all declared here, before any is run)
Two pools, alone and together:
  BRK    closed above a tight 40-session range on 2x volume in the last
         five sessions and is still above it
  VERGE  still inside a tight 40-session range, within 3% of its top
Five screens, added one at a time and all together:
  base   above the 200-day average, leader score in the top half
  tech   six or more of the nine chart conditions
  sector its industry in the top half on money flow
  fund   latest quarterly profit AND sales up on a year ago (as filed by
         that date); "lenient" only refuses a known fall in profit
  news   no results in the last ten sessions that the market sold
         (a reaction worse than -2% against the average stock)
Two exits: 21 sessions with a close 8% under; 10 sessions with 6%.
Picks are the top 12 a list date, ordered by one score: the mean of the
leader percentile, the chart conditions met, the sector's rank and the
profit-growth rank.

THE RULE FOR CHOOSING
Among versions with at least 400 picks in 2017-21 and a positive lead
over the index there, the one with the most picks that rose in 2017-21.
Its 2022-26 record is printed whatever it is.

    IDEAS_DATA=... python research/short_term_lab.py
"""
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ideas_study as S          # noqa: E402
import setups_lab as SL          # noqa: E402
import signals_lab as L          # noqa: E402

OUT = os.path.join(HERE, "short-term-lab.json")
N = 12


def fundamentals(P, R):
    """(profit growth, sales growth, results reaction) as known each session."""
    idx, cols = P.C.index, P.C.columns
    shape = (len(idx), len(cols))
    pv, rv, wv = (np.full(shape, np.nan) for _ in range(3))
    ci = {c: j for j, c in enumerate(cols)}
    for r in R.itertuples(index=False):
        j = ci.get(r.symbol)
        if j is None:
            continue
        pv[r.i, j], rv[r.i, j], wv[r.i, j] = r.pat_yoy_pct, r.revenue_yoy_pct, r.i
    pat, rev, when = (pd.DataFrame(x, index=idx, columns=cols) for x in (pv, rv, wv))
    # A quarter's numbers stand until the next quarter's, for 100 sessions at most.
    pat, rev = pat.ffill(limit=100), rev.ffill(limit=100)
    known = when.ffill(limit=100).notna()
    day = P.C / P.C.shift(1) - 1
    react = day.sub(day.where(P.universe(10)).mean(axis=1), axis=0).where(when.notna())
    return pat, rev, known, react.ffill(limit=9)


def main():
    P = S.Panel()
    U = P.universe(10)
    F, B, M = L.features(P), L.base_parts(P, U), SL.measures(P)
    R = S.load_results(P)
    C = P.C
    grid = C.index[262:-1:5]

    brk0 = M["break40"] & (M["width40"] <= 0.18) & (M["relvol"] >= 2.0)
    level = M["top40"].where(brk0).ffill(limit=4)
    BRK = (brk0.astype(float).rolling(5, min_periods=1).max() > 0) & (C > level)
    VERGE = (M["width40"] <= 0.18) & (C <= M["top40"]) & (C >= M["top40"] * 0.97) & ~BRK
    pools = {"BRK": BRK, "VERGE": VERGE, "BOTH": BRK | VERGE}

    conds = [C > M["ema20"], M["ema20"] > P.sma50, P.sma50 > P.sma200, F["rsi14"] > 55,
             F["macd_hist"] > 0, (F["adx14"] >= 25) & (F["di_spread"] > 0), F["updown_volume"] > 1.2,
             F["relvol5"] > 1.2, P.near_high >= 0.95]
    card = sum(c.astype(float) for c in conds)

    sector = SL.load_sectors(P)
    sec_scores, names, cols = SL.flows(P, U, B, sector)
    sec = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    for s in names:
        sec.iloc[:, cols[s]] = np.repeat(sec_scores["money_flow"][s].values[:, None], len(cols[s]), axis=1)

    pat, rev, known, react = fundamentals(P, R)
    screens = {
        "base": (C > P.sma200) & (B["leader"] >= 0.5),
        "tech": card >= 6,
        "sector": sec >= 0.5,
        "fund": (pat > 0) & (rev > 0),
        "fund_lenient": ~(known & (pat < 0)),
        "news": ~(react < -0.02),
    }
    growth = S.pct(pat.clip(-100, 300), U).fillna(0.5)
    score = (B["leader"] + card / 9.0 + sec.fillna(0.5) + growth) / 4.0

    combos = [("base",), ("base", "tech"), ("base", "sector"), ("base", "fund"), ("base", "fund_lenient"),
              ("base", "news"), ("base", "tech", "sector"), ("base", "tech", "fund_lenient", "news"),
              ("base", "tech", "sector", "fund", "news"), ("base", "tech", "sector", "fund_lenient", "news")]
    exits = {"21s_8pct": (21, 8.0), "10s_6pct": (10, 6.0)}
    out = {"generated": pd.Timestamp.today().date().isoformat(), "to": str(C.index[-1].date()),
           "docstring": __doc__.split("    IDEAS_DATA")[0].strip(), "trials": {}}
    for (pname, pool), combo, (ename, (hold, stop)) in itertools.product(pools.items(), combos, exits.items()):
        flag = pool.copy()
        for k in combo:
            flag &= screens[k]
        picks = SL.daily_picks(flag.fillna(False), score, U, grid, n=N)
        rec = SL.summary(SL.run_rule(P, picks, hold, stop_pct=stop), len(grid))
        key = f"{pname}|{'+'.join(combo)}|{ename}"
        out["trials"][key] = rec
        if rec:
            h = rec["by_half"]
            a, b = h["2017-21"] or {}, h["2022-26"] or {}
            print(f"{key:58s} n {rec['picks']:5d} up {rec['up_pct']:5.1f} avg {rec['avg_pct']:5.2f} "
                  f"lead {rec['lead_pct']:5.2f} t {rec['lead_t']} | 17-21 n {a.get('picks')} up {a.get('up_pct')} "
                  f"lead {a.get('lead_pct')} | 22-26 n {b.get('picks')} up {b.get('up_pct')} lead {b.get('lead_pct')}",
                  flush=True)

    def ok(v):
        a = v["by_half"]["2017-21"]
        return a and a["picks"] >= 400 and (a["lead_pct"] or -9) > 0
    pool = {k: v for k, v in out["trials"].items() if v and ok(v)}
    best = max(pool, key=lambda k: pool[k]["by_half"]["2017-21"]["up_pct"]) if pool else None
    out["chosen"] = best
    print("\nchosen on 2017-21:", best)
    if best:
        print(json.dumps({k: v for k, v in out["trials"][best].items() if k != "exits"}, indent=1))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
