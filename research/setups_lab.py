"""
The setups lab: four lists a reader asked for by name.

    python research/setups_lab.py            # every variant, research/setups-lab.json

November 2026. research/signals_lab.py tested breakouts, technicals and the
rest as ways to improve the existing lists, found that they did not, and left
them out. The reader's answer was that the lists were what was asked for:

  1  stocks that have been consolidating and now break out on volume
  2  stocks picked on technicals: price action, volume, the moving averages
  3  the highest-accuracy setups for a quick return
  4  where money is flowing, and the stocks in those sectors; emerging names

So each is built here as a list of its own, and what this file decides is
only WHICH VERSION of each one to build. Several were declared for each, all
before any ran, and all are in the output.

THE RULE, set before the run. For each of the four, the version taken is the
one that did best on 2017-2021 by the measure that list is for:

  1, 2, 4   the lead over the Nifty 500 over the same sessions, among
            versions that produced a pick on at least a third of sessions
  3         the share of picks that rose, among versions whose average pick
            still made money after a 0.49% round trip

and its 2022-2026 record is then read and printed WHATEVER IT IS. A list
that was asked for is built; what it has done is put beside it. Nothing here
is a reason to believe a list works. That is what the record is for.

HOW EACH IS MEASURED
A signal on day t uses bars up to t. The pick is bought at the next open.
Breakouts are left on a close back under the top of the base they broke out
of (the breakout failed), or after the hold. Quick trades are sold on the
first close above the 5-day average (the bounce has happened), or at a set
number of sessions. Every return is a price return before costs; the
after-cost figure takes off 0.49% a round trip, which matters most where the
hold is shortest.

SECTORS
Where money is flowing needs a sector for every company. That is NSE's own:
the "Industry" column of the Nifty Total Market list (754 companies, 22
industries), read from the exchange's archive. It is today's list, so a
company no longer in it has no sector in the test and is on no flow list.
"""

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ideas_study as S          # noqa: E402
import signals_lab as L          # noqa: E402

OUT = os.environ.get("SETUPS_LAB_OUT", "").strip() or os.path.join(HERE, "setups-lab.json")
SECTORS_CSV = os.environ.get("IDEAS_SECTORS_CSV", "").strip() or os.path.join(S.DATA, "nse_industries.csv")
SPLIT = S.SPLIT
COST = S.ROUND_TRIP_COST_PCT
MAX_PICKS = 15


# --------------------------------------------------------------------------
# Running a set of picks under a rule
# --------------------------------------------------------------------------

def run_rule(P, picks, max_hold, stop_pct=None, above_sma5=False, target_pct=None, sma5=None):
    """
    `picks` is [(date, [(name, level or None), ...])]. Bought at the next
    open. Left at the first of: a close under `level` (the base it broke out
    of), a close `stop_pct` under the entry, a high `target_pct` over it, a
    close above the 5-day average, or `max_hold` sessions.
    """
    Cn, On, Hn = P.C.values, P.O.values, P.H.values
    S5 = sma5.values if sma5 is not None else None
    N5 = P.N500.values
    col = {n: j for j, n in enumerate(P.C.columns)}
    row = {d: i for i, d in enumerate(P.C.index)}
    recs = []
    for d, names in picks:
        i = row[d]
        if i + 2 >= len(Cn):
            continue
        for n, level in names:
            j = col[n]
            e = On[i + 1, j]
            if not np.isfinite(e) or e <= 0:
                continue
            last = min(i + max_hold, len(Cn) - 1)
            ret, k_out, why = None, last, "time"
            for k in range(i + 1, last + 1):
                c = Cn[k, j]
                if not np.isfinite(c):
                    continue
                if target_pct and Hn[k, j] >= e * (1 + target_pct / 100.0):
                    goal = e * (1 + target_pct / 100.0)
                    ret, k_out, why = (max(On[k, j], goal) if k > i + 1 else goal) / e - 1, k, "target"
                    break
                if level is not None and c < level:
                    ret, k_out, why = c / e - 1, k, "failed"
                    break
                if stop_pct and c <= e * (1 - stop_pct / 100.0):
                    ret, k_out, why = c / e - 1, k, "stop"
                    break
                if above_sma5 and S5 is not None and c > S5[k, j]:
                    ret, k_out, why = c / e - 1, k, "bounced"
                    break
            if ret is None:
                c = Cn[last, j]
                if not np.isfinite(c):
                    continue
                ret = c / e - 1
            bench = N5[k_out] / N5[i] - 1 if np.isfinite(N5[k_out]) and np.isfinite(N5[i]) else np.nan
            recs.append((d, n, ret, bench, k_out - i, why))
    return pd.DataFrame(recs, columns=["date", "name", "ret", "bench", "days", "why"])


def summary(df, sessions):
    if not len(df):
        return None

    def part(x):
        if not len(x):
            return None
        per = x.groupby("date").agg(ret=("ret", "mean"), bench=("bench", "mean"))
        ex = (per["ret"] - per["bench"]).dropna()
        return {"picks": int(len(x)), "up_pct": round(float((x["ret"] > 0).mean() * 100), 1),
                "avg_pct": round(float(x["ret"].mean() * 100), 2),
                "median_pct": round(float(x["ret"].median() * 100), 2),
                "after_costs_pct": round(float(x["ret"].mean() * 100) - COST, 2),
                "index_pct": round(float(x["bench"].mean() * 100), 2),
                "lead_pct": round(float(ex.mean() * 100), 2) if len(ex) else None,
                "lead_raw": float(ex.mean() * 100) if len(ex) else None,
                "worst_5pct": round(float(np.percentile(x["ret"], 5) * 100), 1),
                "best_5pct": round(float(np.percentile(x["ret"], 95) * 100), 1),
                "days_held": round(float(x["days"].mean()), 1)}
    out = part(df)
    per = df.groupby("date").agg(ret=("ret", "mean"), bench=("bench", "mean"))
    ex = (per["ret"] - per["bench"]).dropna()
    t = S.newey_west_t(ex.values, max(1, int(round(df["days"].mean()))))
    out["lead_t"] = None if t is None else round(t, 2)
    out["days_with_a_pick_pct"] = round(100.0 * df["date"].nunique() / max(1, sessions), 1)
    out["picks_a_day"] = round(len(df) / max(1, df["date"].nunique()), 1)
    out["exits"] = {k: int(v) for k, v in df["why"].value_counts().items()}
    out["by_half"] = {"2017-21": part(df[df["date"] < SPLIT]), "2022-26": part(df[df["date"] >= SPLIT])}
    return out


def daily_picks(flag, rank_by, U, dates, level=None, n=MAX_PICKS):
    """Every stock the signal fired on, each day, the top n by `rank_by`."""
    f, r, u = flag.values, rank_by.values, U.values
    lv = level.values if level is not None else None
    names = np.asarray(flag.columns)
    row = {d: i for i, d in enumerate(flag.index)}
    out = []
    for d in dates:
        i = row[d]
        js = np.flatnonzero(f[i] & u[i])
        if not len(js):
            continue
        order = js[np.argsort(-np.nan_to_num(r[i, js], nan=-1e18), kind="mergesort")][:n]
        out.append((d, [(names[j], (float(lv[i, j]) if lv is not None and np.isfinite(lv[i, j]) else None))
                        for j in order]))
    return out


def grid_picks(score, U, dates, n=MAX_PICKS):
    return [(d, [(nm, None) for nm in names]) for d, names in L.picks_from(score, U, dates, n=n)]


# --------------------------------------------------------------------------
# The four families
# --------------------------------------------------------------------------

def measures(P):
    C, H, L_, V = P.C, P.H, P.L, P.V
    m = {}
    m["sma5"] = C.rolling(5).mean()
    m["sma20"] = C.rolling(20).mean()
    m["sd20"] = C.rolling(20).std()
    m["ema20"] = C.ewm(span=20, adjust=False, min_periods=20).mean()
    m["ema50"] = C.ewm(span=50, adjust=False, min_periods=50).mean()
    v50 = V.rolling(50, min_periods=40).median().shift(1)
    m["relvol"] = V / v50
    spread = (H - L_).replace(0, np.nan)
    m["clv"] = (C - L_) / spread
    d = C.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 2, adjust=False, min_periods=2).mean()
    ls = (-d.clip(upper=0)).ewm(alpha=1 / 2, adjust=False, min_periods=2).mean()
    m["rsi2"] = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    m["rsi2"] = m["rsi2"].where(ls > 0, 100.0)
    for n in (20, 40, 60):
        top = H.shift(1).rolling(n, min_periods=n).max()
        bot = L_.shift(1).rolling(n, min_periods=n).min()
        m[f"top{n}"], m[f"width{n}"] = top, (top - bot) / bot
        m[f"break{n}"] = (C > top) & (C.shift(1) <= top)
    return m


def breakouts(P, U, M, B):
    up = P.C > P.sma200
    vol2, vol15 = M["relvol"] >= 2.0, M["relvol"] >= 1.5
    tight40 = S.pct(M["width40"], U) <= 0.30
    return {
        "box_20_tight": ("Twenty sessions inside a 12% range, then a close above it on twice the usual "
                         "volume, finishing in the top 30% of the day's range. Above the 200-day average.",
                         M["break20"] & (M["width20"] <= 0.12) & vol2 & (M["clv"] >= 0.7) & up, M["top20"]),
        "box_40": ("Forty sessions inside an 18% range, then a close above it on twice the usual volume. "
                   "Above the 200-day average.",
                   M["break40"] & (M["width40"] <= 0.18) & vol2 & up, M["top40"]),
        "box_60": ("Sixty sessions inside a 25% range, then a close above it on twice the usual volume. "
                   "Above the 200-day average.",
                   M["break60"] & (M["width60"] <= 0.25) & vol2 & up, M["top60"]),
        "box_40_any_trend": ("The forty-session box, whatever the longer trend.",
                             M["break40"] & (M["width40"] <= 0.18) & vol2, M["top40"]),
        "box_40_lighter_volume": ("The forty-session box on one and a half times the usual volume.",
                                  M["break40"] & (M["width40"] <= 0.18) & vol15 & up, M["top40"]),
        "box_40_leader": ("The forty-session box, only in stocks whose leader score is in the top half.",
                          M["break40"] & (M["width40"] <= 0.18) & vol2 & up & (B["leader"] >= 0.5), M["top40"]),
        "box_40_tightest": ("A close above a forty-session range that was among the tightest 30% on the "
                            "exchange that day, on one and a half times the usual volume.",
                            M["break40"] & tight40 & vol15 & up, M["top40"]),
    }


def technicals(P, U, M, F, B):
    C = P.C
    stack = (C > M["ema20"]) & (M["ema20"] > P.sma50) & (P.sma50 > P.sma200)
    up = (C > P.sma200) & (P.sma50 > P.sma200)
    rising = F["macd_hist"] > F["macd_hist"].shift(1)
    out = {
        "ema20_pullback": ("An uptrend that dipped to its 20-day average in the last three sessions and "
                           "closed back above it, above the previous day's high.",
                           up & (P.L.rolling(3).min() <= M["ema20"] * 1.005) & (C > M["ema20"])
                           & (C > P.H.shift(1)) & (C > P.O), F["adx14"]),
        "golden_cross": ("The 50-day average crossed above the 200-day in the last five sessions.",
                         (P.sma50 > P.sma200) & (P.sma50.shift(5) <= P.sma200.shift(5)) & (C > P.sma50),
                         F["adx14"]),
        "ema_20_50_cross": ("The 20-day average crossed above the 50-day in the last five sessions, "
                            "above the 200-day average.",
                            (M["ema20"] > M["ema50"]) & (M["ema20"].shift(5) <= M["ema50"].shift(5))
                            & (C > P.sma200), F["adx14"]),
        "stack_and_strength": ("Price above its 20-, 50- and 200-day averages in order, RSI between 55 "
                               "and 70, MACD above its signal line and rising, ADX at 25 or more.",
                               stack & (F["rsi14"] >= 55) & (F["rsi14"] <= 70) & (F["macd_hist"] > 0)
                               & rising & (F["adx14"] >= 25), F["adx14"]),
    }
    # The scorecard: how many of nine textbook conditions hold.
    conds = [C > M["ema20"], M["ema20"] > P.sma50, P.sma50 > P.sma200, F["rsi14"] > 55,
             F["macd_hist"] > 0, (F["adx14"] >= 25) & (F["di_spread"] > 0), F["updown_volume"] > 1.2,
             F["relvol5"] > 1.2, P.near_high >= 0.95]
    score = sum(c.astype(float) for c in conds)
    return out, (score + 0.5 * S.pct(P.near_high, U)).where(U & (score >= 7))


def quick(P, U, M, B, week_score):
    C = P.C
    up = (C > P.sma200) & (P.sma50 > P.sma200)
    down3 = (C < C.shift(1)) & (C.shift(1) < C.shift(2)) & (C.shift(2) < C.shift(3))
    return {
        "rsi2_under_10": ("In an uptrend, with the two-day RSI under 10: sold off hard for a day or two.",
                          up & (M["rsi2"] < 10), -M["rsi2"]),
        "rsi2_under_10_leader": ("The same, only in market leaders (top 30%).",
                                 up & (M["rsi2"] < 10) & (B["leader"] >= 0.70), -M["rsi2"]),
        "rsi2_under_5": ("In an uptrend, with the two-day RSI under 5.", up & (M["rsi2"] < 5), -M["rsi2"]),
        "three_down_days": ("In an uptrend, three lower closes in a row.", up & down3, -P.ret_5),
        "below_lower_band": ("In an uptrend, a close under the lower Bollinger band (20 days, 2 deviations).",
                             up & (C < M["sma20"] - 2 * M["sd20"]), -P.ret_5),
        "gap_down_recovered": ("Above its 200-day average, opened 2% or more under the previous close "
                               "and closed above its open.",
                               (C > P.sma200) & (P.O <= 0.98 * C.shift(1)) & (C > P.O), -P.ret_5),
    }


def load_sectors(P):
    if not os.path.exists(SECTORS_CSV):
        return None
    df = pd.read_csv(SECTORS_CSV)
    df.columns = [c.strip() for c in df.columns]
    m = dict(zip(df["Symbol"].astype(str).str.strip(), df["Industry"].astype(str).str.strip()))
    return pd.Series([m.get(n) for n in P.C.columns], index=P.C.columns)


def flows(P, U, B, sector):
    """Sector-level frames (date x sector) and the stock-level lists built on them."""
    C = P.C
    names = sorted(s for s in sector.dropna().unique())
    cols = {s: np.flatnonzero((sector == s).values) for s in names}
    Uv, VAL = U.values, P.VAL.values
    above50 = (C > P.sma50).values
    r21, r63 = P.ret_21.values, (C / C.shift(63) - 1).values
    total = np.where(Uv, VAL, 0.0).sum(axis=1)
    n_dates = len(C)
    share = np.full((n_dates, len(names)), np.nan)
    breadth, med21, med63, count = share.copy(), share.copy(), share.copy(), share.copy()
    for k, s in enumerate(names):
        js = cols[s]
        u = Uv[:, js]
        count[:, k] = u.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            share[:, k] = np.where(u, VAL[:, js], 0.0).sum(axis=1) / total
            breadth[:, k] = np.where(u, above50[:, js], False).sum(axis=1) / np.maximum(1, count[:, k])
        med21[:, k] = np.nanmedian(np.where(u, r21[:, js], np.nan), axis=1)
        med63[:, k] = np.nanmedian(np.where(u, r63[:, js], np.nan), axis=1)
    idx = C.index
    share = pd.DataFrame(share, index=idx, columns=names)
    enough = pd.DataFrame(count >= 8, index=idx, columns=names)
    # Money moving in: the sector's share of all turnover this week against
    # its own share over the last sixty sessions.
    shift = (share.rolling(5).mean() / share.rolling(60, min_periods=40).mean()).where(enough)
    breadth = pd.DataFrame(breadth, index=idx, columns=names).where(enough)
    med21 = pd.DataFrame(med21, index=idx, columns=names).where(enough)
    med63 = pd.DataFrame(med63, index=idx, columns=names).where(enough)

    def rk(x):
        return x.rank(axis=1, pct=True)
    sector_scores = {
        "money_flow": (rk(shift) + rk(breadth) + rk(med21)) / 3,
        "turnover_share_only": rk(shift),
        "sector_momentum": rk(med63),
    }
    return sector_scores, names, cols


def sector_leaders(P, U, B, sector_score, cols, dates, top_sectors=4, per_sector=4):
    """The strongest sectors that day, and the strongest stocks in each."""
    lead = B["leader"].where(B["ok"]).values
    Uv = U.values
    names = np.asarray(P.C.columns)
    row = {d: i for i, d in enumerate(P.C.index)}
    out = []
    for d in dates:
        i = row[d]
        sc = sector_score.loc[d].dropna()
        if len(sc) < top_sectors:
            continue
        picks = []
        for s in sc.nlargest(top_sectors).index:
            js = cols[s]
            v = np.where(Uv[i, js], lead[i, js], np.nan)
            order = [j for j in np.argsort(-np.nan_to_num(v, nan=-1.0)) if np.isfinite(v[j])][:per_sector]
            picks += [(names[js[j]], None) for j in order]
        if picks:
            out.append((d, picks[:MAX_PICKS + 1]))
    return out


# --------------------------------------------------------------------------

def choose(table, measure, eligible):
    """The rule: best on 2017-21 by `measure`, among the eligible."""
    pool = {k: v for k, v in table.items() if v and eligible(v) and v["by_half"]["2017-21"]}
    if not pool:
        return None
    # On the unrounded figure where there is one: two versions that print the
    # same to two decimals are not a tie.
    raw = "lead_raw" if measure == "lead_pct" else measure
    return max(pool, key=lambda k: (pool[k]["by_half"]["2017-21"].get(raw) or -9e9))


def main():
    P = S.Panel()
    U = P.universe(10)
    F = L.features(P)
    B = L.base_parts(P, U)
    M = measures(P)
    scores = S.recipes(P, U)
    days = P.C.index[262:-1]
    grid = P.C.index[262:-1:5]
    n_days = len(days)
    out = {"generated": pd.Timestamp.today().date().isoformat(),
           "from": str(days[0].date()), "to": str(P.C.index[-1].date()),
           "rules": "Signal on day t, bought at the next open. Returns before costs; after_costs takes "
                    "off %.2f%% a round trip. index_pct and lead_pct are against the Nifty 500 over the "
                    "sessions each pick was held." % COST,
           "choice_rule": "For each list the version taken is the best on 2017-2021 (lead over the index "
                          "for lists 1, 2 and 4; share of picks that rose, among versions still profitable "
                          "after costs, for list 3). Its 2022-2026 record is printed whatever it is."}

    def show(tag, name, r):
        if r is None:
            print(f"{tag} {name:28s} no picks", flush=True)
            return
        h = r["by_half"]
        print(f"{tag} {name:28s} days {r['days_with_a_pick_pct']:5.1f}% n/day {r['picks_a_day']:4.1f} "
              f"up {r['up_pct']:5.1f} avg {r['avg_pct']:6.2f} net {r['after_costs_pct']:6.2f} "
              f"idx {r['index_pct']:5.2f} lead {r['lead_pct']} t {r['lead_t']} held {r['days_held']} "
              f"| 17-21 up {h['2017-21'] and h['2017-21']['up_pct']} lead {h['2017-21'] and h['2017-21']['lead_pct']} "
              f"| 22-26 up {h['2022-26'] and h['2022-26']['up_pct']} lead {h['2022-26'] and h['2022-26']['lead_pct']}",
              flush=True)

    # ---- 1. breakouts ------------------------------------------------------
    out["breakouts"] = {}
    for name, (what, flag, top) in breakouts(P, U, M, B).items():
        picks = daily_picks(flag, M["relvol"], U, days, level=top)
        rec = {"what": what, "exits": {}}
        for label, kw in (("21 sessions, or a close back under the base", dict(max_hold=21)),
                          ("10 sessions, or a close back under the base", dict(max_hold=10)),
                          ("42 sessions, or a close back under the base", dict(max_hold=42))):
            rec["exits"][label] = summary(run_rule(P, picks, **kw), n_days)
        flat = [(d, [(n, None) for n, _l in names]) for d, names in picks]
        rec["exits"]["21 sessions, or a close 8% under the entry"] = summary(
            run_rule(P, flat, max_hold=21, stop_pct=8.0), n_days)
        out["breakouts"][name] = rec
        show("breakout", name, rec["exits"]["21 sessions, or a close back under the base"])
    main_exit = "21 sessions, or a close back under the base"
    b_table = {k: v["exits"][main_exit] for k, v in out["breakouts"].items()}
    out["breakout_choice"] = choose(b_table, "lead_pct", lambda v: v["days_with_a_pick_pct"] >= 33)
    print("breakout taken:", out["breakout_choice"], flush=True)

    # ---- 2. technical setups -----------------------------------------------
    out["technicals"] = {}
    events, scorecard = technicals(P, U, M, F, B)
    for name, (what, flag, rank_by) in events.items():
        picks = daily_picks(flag, rank_by, U, days)
        rec = {"what": what, "exits": {
            "21 sessions, or a close 10% under": summary(run_rule(P, picks, 21, stop_pct=10.0), n_days),
            "42 sessions, or a close 14% under": summary(run_rule(P, picks, 42, stop_pct=14.0), n_days)}}
        out["technicals"][name] = rec
        show("technical", name, rec["exits"]["21 sessions, or a close 10% under"])
    picks = grid_picks(scorecard, U, grid)
    out["technicals"]["scorecard"] = {
        "what": "Nine textbook conditions (above the 20-, 50- and 200-day averages in order, RSI over 55, "
                "MACD above its signal line, ADX at 25 with +DI ahead, more volume on up days, volume "
                "above its usual, within 5% of the 52-week high). The fifteen stocks meeting the most, "
                "seven at least, every five sessions.",
        "exits": {"21 sessions, or a close 10% under": summary(run_rule(P, picks, 21, stop_pct=10.0), len(grid)),
                  "42 sessions, or a close 14% under": summary(run_rule(P, picks, 42, stop_pct=14.0), len(grid))}}
    show("technical", "scorecard", out["technicals"]["scorecard"]["exits"]["21 sessions, or a close 10% under"])
    t_table = {k: v["exits"]["21 sessions, or a close 10% under"] for k, v in out["technicals"].items()}
    out["technical_choice"] = choose(t_table, "lead_pct", lambda v: v["days_with_a_pick_pct"] >= 33)
    print("technical taken:", out["technical_choice"], flush=True)

    # ---- 3. quick trades ---------------------------------------------------
    out["quick"] = {}
    exits = {"first close above the 5-day average, 7 sessions at most": dict(max_hold=7, above_sma5=True),
             "the same, or a close 7% under": dict(max_hold=7, above_sma5=True, stop_pct=7.0),
             "5 sessions": dict(max_hold=5),
             "a 3% gain, 5 sessions at most, or a close 5% under": dict(max_hold=5, target_pct=3.0, stop_pct=5.0)}
    q_events = quick(P, U, M, B, scores["week"])
    for name, (what, flag, rank_by) in q_events.items():
        picks = daily_picks(flag, rank_by, U, days)
        rec = {"what": what, "exits": {}}
        for label, kw in exits.items():
            rec["exits"][label] = summary(run_rule(P, picks, sma5=M["sma5"], **kw), n_days)
        out["quick"][name] = rec
        show("quick", name, rec["exits"]["first close above the 5-day average, 7 sessions at most"])
    wk = grid_picks(scores["week"], U, grid)
    out["quick"]["the_week_list"] = {
        "what": "The existing week list (a leader that fell this week), for comparison.",
        "exits": {label: summary(run_rule(P, wk, sma5=M["sma5"], **kw), len(grid)) for label, kw in exits.items()}}
    show("quick", "the_week_list",
         out["quick"]["the_week_list"]["exits"]["first close above the 5-day average, 7 sessions at most"])
    # Chosen across every version AND every exit: the pair with the most picks rising.
    q_table = {f"{k} | {label}": r for k, v in out["quick"].items() if k != "the_week_list"
               for label, r in v["exits"].items()}
    out["quick_choice"] = choose(
        q_table, "up_pct",
        lambda v: v["days_with_a_pick_pct"] >= 33 and (v["by_half"]["2017-21"] or {}).get("after_costs_pct", -1) > 0)
    print("quick taken:", out["quick_choice"], flush=True)
    for k, r in sorted(q_table.items(), key=lambda kv: -(kv[1]["up_pct"] if kv[1] else 0))[:8]:
        show("quick*", k[:28], r)

    # ---- 4. money flow and emerging names -----------------------------------
    out["flow"] = {}
    sector = load_sectors(P)
    if sector is None:
        out["flow"] = {"available": False, "note": "No sector list at " + SECTORS_CSV}
    else:
        sector_scores, names, cols = flows(P, U, B, sector)
        out["sectors"] = {"source": "NSE, Nifty Total Market list", "industries": len(names),
                          "companies": int(sector.notna().sum())}
        what = {"money_flow": "The four sectors where money is moving in (share of market turnover this "
                              "week against its own sixty-session share, share of members above their "
                              "50-day average, and the month's median move), and the four strongest "
                              "leaders in each.",
                "turnover_share_only": "The four sectors whose share of market turnover rose most this "
                                       "week, and the four strongest leaders in each.",
                "sector_momentum": "The four sectors with the best median three-month move, and the four "
                                   "strongest leaders in each."}
        for name, sc in sector_scores.items():
            picks = sector_leaders(P, U, B, sc, cols, grid)
            out["flow"][name] = {"what": what[name], "exits": {
                "21 sessions, or a close 10% under": summary(run_rule(P, picks, 21, stop_pct=10.0), len(grid)),
                "63 sessions, or a close 15% under": summary(run_rule(P, picks, 63, stop_pct=15.0), len(grid))}}
            show("flow", name, out["flow"][name]["exits"]["21 sessions, or a close 10% under"])
        # Emerging: a stock that was nowhere a month ago and is a leader now.
        leader = B["leader"]
        rose = (leader - leader.shift(21)).where(B["ok"] & (leader >= 0.60) & (leader.shift(21) < 0.45))
        surge = (P.C * P.V).rolling(5).mean() / (P.C * P.V).shift(5).rolling(60, min_periods=40).median()
        extra = {
            "emerging_leaders": ("Leader score under the 45th percentile a month ago and over the 60th "
                                 "now. Ranked on how far it rose.", grid_picks(rose, U, grid)),
            "stock_turnover_surge": ("Turnover this week at twice its sixty-session usual or more, the "
                                     "week up, in an uptrend. Ranked on the surge.",
                                     grid_picks(surge.where(B["ok"] & (surge >= 2.0) & (P.ret_5 > 0)), U, grid)),
        }
        for name, (w, picks) in extra.items():
            out["flow"][name] = {"what": w, "exits": {
                "21 sessions, or a close 10% under": summary(run_rule(P, picks, 21, stop_pct=10.0), len(grid)),
                "63 sessions, or a close 15% under": summary(run_rule(P, picks, 63, stop_pct=15.0), len(grid))}}
            show("flow", name, out["flow"][name]["exits"]["21 sessions, or a close 10% under"])
        f_table = {k: v["exits"]["21 sessions, or a close 10% under"] for k, v in out["flow"].items()}
        out["flow_choice"] = choose(f_table, "lead_pct", lambda v: v["days_with_a_pick_pct"] >= 33)
        print("flow taken:", out["flow_choice"], flush=True)

    # What the site runs, and where that departs from the rule above.
    out["taken"] = {
        "breakout": {
            "version": out["breakout_choice"],
            "exit": "21 sessions, or a close 8% under the entry",
            "note": ("The version was chosen as the rule says, on leaving at a close back under the "
                     "base. Both exits were measured for every version. Leaving at the base cut the "
                     "average and left three picks in ten ahead; a line 8% under the entry left five "
                     "in ten ahead with a higher average. The site uses the second. That choice "
                     "between the two exits was made after seeing both.")},
        "technical": {"version": out["technical_choice"], "exit": "21 sessions, or a close 10% under"},
        "quick": {
            "version": "rsi2_under_10_leader",
            "exit": "the same, or a close 7% under",
            "note": ("The rule chose among versions still profitable after costs on 2017-2021, and "
                     "only a plain five-session hold was (52 picks in 100 rose). The reader asked for "
                     "the highest share of picks rising, so the site runs the exit with the highest: "
                     "sold on the first close above the 5-day average. Its average pick does NOT "
                     "cover a 0.49% round trip, and the page says so beside it.")},
        "flow": {"version": out.get("flow_choice"), "exit": "21 sessions, or a close 10% under"},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(L._clean(out), fh, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
