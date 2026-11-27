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
BIG_WIN = 0.25                   # a "big winner": up 25% or more on the trade


# --------------------------------------------------------------------------
# Running a set of picks under a rule
# --------------------------------------------------------------------------

def run_rule(P, picks, max_hold, stop_pct=None, above_sma5=False, target_pct=None, sma5=None,
             trail=None, trail_after=15, bounce=None):
    """
    `picks` is [(date, [(name, level or None), ...])]. Bought at the next
    open. Left at the first of: a close under `level` (the base it broke out
    of), a close `stop_pct` under the entry, a high `target_pct` over it, a
    close above the 5-day average, a close under `trail` (a frame, e.g. the
    50-day average) once the pick has been held `trail_after` sessions, a
    close above `bounce` (a frame, e.g. the 10-day average: the bounce has
    happened), or `max_hold` sessions.
    """
    Cn, On, Hn = P.C.values, P.O.values, P.H.values
    S5 = sma5.values if sma5 is not None else None
    TR = trail.values if trail is not None else None
    BO = bounce.values if bounce is not None else None
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
                if BO is not None and c > BO[k, j]:
                    ret, k_out, why = c / e - 1, k, "bounced"
                    break
                if TR is not None and k - i >= trail_after and np.isfinite(TR[k, j]) and c < TR[k, j]:
                    ret, k_out, why = c / e - 1, k, "trend broke"
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
                # The share of picks that made 25% or more: the winners a
                # short hold or a tight stop cuts off.
                "big_winner_pct": round(float((x["ret"] >= BIG_WIN).mean() * 100), 1),
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



# ==========================================================================
# VERSION 2 (December 2026): early-stage setups, held for the move
#
#     python research/setups_lab.py --v2     # research/setups-lab-v2.json
#
# The first versions measured above, as shipped, had four faults a reader
# named: technicals and money flow bought stocks already far above their
# averages; every list left within 7 to 21 sessions on a 7-10% stop, cutting
# off the few large winners that carry an average; the quick trade lost money
# after a 0.49% round trip; and the breakout needed a base 18% wide or tighter
# in a stock already in the top half of 12-month leaders, which is the stock
# that has already moved. Explosive breakouts in Indian small and mid caps
# (RATNAVEER in July 2026, HFCL in late 2023, mid 2024 and January 2026) came
# out of 22-35% bases that tightened at the end, in stocks not yet leaders.
#
# Every version below was declared before any ran. THE RULE, set before the
# run, is the one above with two additions: (a) a version must have made
# money after a 0.49% round trip on 2017-2021 to be taken, and (b) the
# version is chosen among the NEW versions; the version the site ran until
# now is measured on the same data and printed beside it as the baseline,
# whether it is better or worse. The 2022-2026 record of whatever is taken is
# printed as it is.
#
#   breakout, technical, flow, emerging   best 2017-21 lead over the Nifty 500
#                                         among versions with a pick on 25% of
#                                         sessions or more, 150 picks or more
#                                         in 2017-21, and a profit after costs
#   quick                                 the most picks rising on 2017-21
#                                         among versions with a profit after
#                                         costs AND a lead over the index
#
# The market-weather check (the Nifty 500 above its 50-day average) is run
# on the taken breakout, emerging and quick versions with and without it. It
# is reported, and it changes the shipped list only if it improved BOTH the
# share of picks rising and the after-cost average in BOTH halves.
# ==========================================================================

V2_OUT = os.environ.get("SETUPS_LAB_V2_OUT", "").strip() or os.path.join(HERE, "setups-lab-v2.json")
# What the engine (backend/leaders.py) is told to use; kept here as the
# declared values the lab tested. Changing one is a new version.
V2 = {
    "ext50_max": 0.16, "ret3m_max": 0.55, "clv_min": 0.55,
    "a_width_max": 0.28, "a_tight_width": 0.20, "a_squeeze": 0.90, "a_range": 0.55, "a_dry": 0.95,
    "a_volume": 1.6, "a_leader": 0.45, "a_sector_top": 0.60,
    "b_width_max": 0.35, "b_range": 0.65, "b_squeeze": 0.95, "b_volume": 2.0, "b_clv": 0.60,
    "b_quiet": 20, "bad_pat": -10.0, "bad_reaction": -0.02,
    "t_leader": 0.55, "t_touch": 1.015, "t_ext_max": 0.06, "t_rsi": (48, 68), "t_sector_top": 0.50,
    "q_leader": 0.65, "q_rsi2": 10.0, "q_drop5": -0.04, "q_sma50_floor": 0.97,
    "f_sectors": 3, "f_per_sector": 5, "f_near_high": 0.85, "f_ext50_max": 0.16, "f_ret3m_max": 0.50,
    "e_min_age": 127, "e_max_age": 380, "e_near_high": 0.90, "e_leader": 0.60, "e_ext50_max": 0.18,
}


def fundamentals_frames(P, R, U):
    """Point-in-time quarterly facts, date x stock: profit and sales growth
    on the latest filing priced in the last 100 sessions, profit itself, and
    the results reaction (the stock's move on the session its results were
    first priced, less the average liquid stock's) for ten sessions after."""
    shape = P.C.shape
    pat, rev, patcr, react = (np.full(shape, np.nan) for _ in range(4))
    if R is not None and len(R):
        col = {n: j for j, n in enumerate(P.C.columns)}
        r1 = (P.C / P.C.shift(1) - 1).values
        mkt = np.nanmean(np.where(U.values, r1, np.nan), axis=1)
        for r in R.itertuples(index=False):
            j = col.get(r.symbol)
            if j is None:
                continue
            i = int(r.i)
            pat[i, j] = r.pat_yoy_pct
            rev[i, j] = r.revenue_yoy_pct
            patcr[i, j] = r.pat_cr
            if np.isfinite(r1[i, j]) and np.isfinite(mkt[i]):
                react[i, j] = r1[i, j] - mkt[i]
    idx, cols = P.C.index, P.C.columns

    def frame(a, limit):
        return pd.DataFrame(a, index=idx, columns=cols).ffill(limit=limit)
    return {"pat": frame(pat, 100), "rev": frame(rev, 100), "pat_cr": frame(patcr, 100),
            "reaction": frame(react, 9)}


def sector_frames(P, U, sector):
    """date x sector: the measures sector_flow() ranks, the old three-part
    score and the new rotation score, and each stock's sector standing (its
    sector's place from the top over the number of sectors, 1/N = first)."""
    C = P.C
    names = sorted(s for s in sector.dropna().unique())
    cols = {s: np.flatnonzero((sector == s).values) for s in names}
    Uv, VAL = U.values, P.VAL.values
    above50 = (C > P.sma50).values
    r21, r63 = P.ret_21.values, (C / C.shift(63) - 1).values
    total = np.where(Uv, VAL, 0.0).sum(axis=1)
    n = len(C)
    share, breadth, med21, med63, count = (np.full((n, len(names)), np.nan) for _ in range(5))
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
    enough = pd.DataFrame(count >= 8, index=idx, columns=names)
    share = pd.DataFrame(share, index=idx, columns=names)
    shift = (share.rolling(5).mean() / share.rolling(60, min_periods=40).mean()).where(enough)
    breadth = pd.DataFrame(breadth, index=idx, columns=names).where(enough)
    med21 = pd.DataFrame(med21, index=idx, columns=names).where(enough)
    med63 = pd.DataFrame(med63, index=idx, columns=names).where(enough)

    def rk(x):
        return x.rank(axis=1, pct=True)
    old = (rk(shift) + rk(breadth) + rk(med21)) / 3
    new = 0.45 * rk(med63) + 0.35 * rk(breadth) + 0.20 * rk(shift)

    def standing(score):
        place = score.rank(axis=1, ascending=False, method="first")
        frac = place.div(score.notna().sum(axis=1), axis=0)
        out = np.full(C.shape, np.nan)
        fv = frac.values
        for k, s in enumerate(names):
            out[:, cols[s]] = fv[:, [k]]
        return pd.DataFrame(out, index=idx, columns=C.columns)
    return {"names": names, "cols": cols, "old": old, "new": new,
            "stand_old": standing(old), "stand_new": standing(new)}


def young_leader(P, U):
    """The leader score of a company listed six to twelve months, placed
    against the established universe exactly as backend/leaders.rank places
    it (ideas_study.add_young), date x stock; NaN elsewhere. And its age."""
    Y, m = S.young_universe(P, U)
    Uv, Yv = U.values, Y.values
    va_y = (P.mom_6_1 / m["vol"]).values
    seasoned = {"m12": (P.mom_12_1 / P.vol_252).values, "m6": (P.mom_6_1 / P.vol_252).values,
                "high": P.near_high.values, "trend": P.trend_q.values}
    theirs = {"m12": va_y, "m6": va_y, "high": m["near"].values, "trend": P.trend_q.values}
    out = np.full(P.C.shape, np.nan)
    for i in range(262, len(P.C)):
        ys, us = np.flatnonzero(Yv[i]), np.flatnonzero(Uv[i])
        if not len(ys) or len(us) < 30:
            continue
        p = {k: np.maximum(1, np.searchsorted(np.sort(seasoned[k][i, us]), theirs[k][i, ys], side="right"))
             / len(us) for k in seasoned}
        out[i, ys] = (p["m12"] + p["m6"] + p["high"] + p["trend"]) / 4
    return Y, m, pd.DataFrame(out, index=P.C.index, columns=P.C.columns)


def v2_measures(P, U, M, F, B, R, sector):
    C = P.C
    X = {}
    X["ema10"] = C.ewm(span=10, adjust=False, min_periods=10).mean()
    X["sma50_up"] = P.sma50 > P.sma50.shift(10)
    X["sma200_up"] = P.sma200 > P.sma200.shift(20)
    X["ext50"] = C / P.sma50 - 1
    X["ext20"] = C / M["ema20"] - 1
    X["ret63"] = C / C.shift(63) - 1
    n5 = P.N500
    X["b21"] = n5 / n5.shift(21) - 1
    X["b63"] = n5 / n5.shift(63) - 1
    X["regime50"] = n5 > n5.rolling(50).mean()
    X["regime200"] = n5 > n5.rolling(200, min_periods=180).mean()
    # Measured on the bars BEFORE the breakout bar: did the base tighten?
    X["squeeze_pre"] = F["squeeze"].shift(1)
    X["range_pre"] = F["range15"].shift(1)
    X["dry_pre"] = F["dryup"].shift(1)
    X["fund"] = fundamentals_frames(P, R, U)
    X["sec"] = sector_frames(P, U, sector) if sector is not None else None
    return X


def _and_rows(df, ser):
    """A date x stock frame AND a date series, row by row."""
    return pd.DataFrame(df.values & np.asarray(ser.fillna(False).values, dtype=bool)[:, None],
                        index=df.index, columns=df.columns)


def listing_age(P):
    """Sessions since a company's first trade, that one included. A company
    already trading in the panel's first week was listed before 2016: its age
    is unknown and large, and it is never "newly listed"."""
    age = (P.traded.cumsum() > 0).cumsum().astype(float)
    old = P.traded.iloc[:5].any(axis=0)
    age.loc[:, old.values] = 1e4
    return age


def _beats(a, bench):
    """Stock return frame beats a benchmark series, row by row."""
    return a.gt(bench, axis=0)


def _lenient_le(x, limit):
    """x <= limit where x is known; True where it is not."""
    return x.isna() | (x <= limit)


def _lenient_ge(x, limit):
    return x.isna() | (x >= limit)


def breakout_v2(P, U, M, F, B, X, pattern="AB", anti_chase=True, regime=False):
    """
    The dual breakout. Returns (flag, level, rank_by, which) as date x stock
    frames: `level` the top of the base it broke out of, `which` 1 for the
    VCP launchpad (A), 2 for the base turnaround (B).
    """
    C = P.C
    v = V2
    leader = B["leader"]
    fund = X["fund"]
    stand = X["sec"]["stand_new"] if X["sec"] is not None else None
    sector_a = _lenient_le(stand, v["a_sector_top"]) if stand is not None else True
    # ---- the breakout day, pattern A: a VCP launchpad -----------------------
    contraction_bits = ((X["squeeze_pre"] <= v["a_squeeze"]) | (X["range_pre"] <= v["a_range"])
                        | (X["dry_pre"] <= v["a_dry"]))
    a40 = (C > M["top40"]) & (M["width40"] <= v["a_width_max"]) & ((M["width40"] <= v["a_tight_width"]) | contraction_bits)
    a60 = (C > M["top60"]) & (M["width60"] <= v["a_width_max"]) & ((M["width60"] <= v["a_tight_width"]) | contraction_bits)
    condA = ((a40 | a60) & (M["relvol"] >= v["a_volume"]) & (M["clv"] >= v["clv_min"])
             & (C > P.sma200) & (P.sma50 >= P.sma200 * 0.98) & (leader >= v["a_leader"]) & sector_a)
    levelA = M["top40"].where(a40, M["top60"])
    # ---- pattern B: a first 60-session high out of a long, wide base -------
    above60 = (C > M["top60"]).astype(float)
    quiet = above60.shift(1).rolling(v["b_quiet"], min_periods=v["b_quiet"]).sum() == 0
    known = fund["pat"].notna() | fund["rev"].notna()
    growing = (fund["pat"] > 0) | (fund["rev"] > 0)
    condB = ((C > M["top60"]) & quiet & (M["width60"] <= v["b_width_max"])
             & ((X["range_pre"] <= v["b_range"]) | (X["squeeze_pre"] <= v["b_squeeze"]))
             & (M["relvol"] >= v["b_volume"]) & (M["clv"] >= v["b_clv"])
             & (C > P.sma200) & (C > P.sma50) & X["sma50_up"] & (~known | growing))
    levelB = M["top60"]
    if pattern == "A":
        condB = condB & False
    if pattern == "B":
        condA = condA & False
    # ---- listed for up to five sessions after, while it holds ------------
    flag = pd.DataFrame(False, index=C.index, columns=C.columns)
    level = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    rank_by = level.copy()
    which = level.copy()
    for k in range(4, -1, -1):                          # the earliest breakout in the window wins
        a, b = condA.shift(k, fill_value=False), condB.shift(k, fill_value=False)
        lv = levelA.shift(k).where(a, levelB.shift(k))
        ok = (a | b) & (C >= lv) & ~flag
        flag |= ok
        level = level.where(~ok, lv)
        rank_by = rank_by.where(~ok, (5 - k) * 10.0 + M["relvol"].shift(k).clip(upper=9.9))
        which = which.where(~ok, np.where(a, 1.0, 2.0))
    shared = _beats(P.ret_21, X["b21"]) & ~(fund["pat"] < v["bad_pat"]) & ~(fund["reaction"] < v["bad_reaction"])
    if anti_chase:
        shared &= (X["ext50"] <= v["ext50_max"]) & (X["ret63"] <= v["ret3m_max"])
    if regime:
        shared = _and_rows(shared, X["regime50"])
    return flag & shared & U, level, rank_by, which


def technical_v2(P, U, M, F, B, X, sector_gate=True):
    C = P.C
    v = V2
    up = ((C > P.sma200) & (P.sma50 > P.sma200) & X["sma200_up"] & (B["leader"] >= v["t_leader"]))
    pull = ((P.L.rolling(3).min() <= M["ema20"] * v["t_touch"]) & (X["ext20"] >= 0) & (X["ext20"] <= v["t_ext_max"])
            & (C > P.O) & (C > M["ema20"]) & (F["rsi14"] >= v["t_rsi"][0]) & (F["rsi14"] <= v["t_rsi"][1]))
    ok = up & pull & ~(X["fund"]["pat"] < v["bad_pat"])
    stand = X["sec"]["stand_new"] if X["sec"] is not None else None
    if sector_gate and stand is not None:
        ok &= _lenient_le(stand, v["t_sector_top"])
    sec_part = (1 - stand.fillna(0.5)) if stand is not None else 0.5
    rank_by = B["leader"] + sec_part + S.pct(F["updown_volume"], U).fillna(0.5)
    return ok & U, rank_by


def quick_v2(P, U, M, B, X, regime=False):
    C = P.C
    v = V2
    up = (C > P.sma200) & (P.sma50 > P.sma200)
    dip = (M["rsi2"] < v["q_rsi2"]) | (P.ret_5 <= v["q_drop5"])
    ok = (up & dip & (B["leader"] >= v["q_leader"]) & (C >= P.sma50 * v["q_sma50_floor"])
          & ~(X["fund"]["reaction"] < v["bad_reaction"]))
    if regime:
        ok = _and_rows(ok, X["regime50"])
    return ok & U, -M["rsi2"]


def flow_v2(P, U, B, X, dates, score="new", anti_chase=True, top_sectors=3, per_sector=5):
    """The top sectors on rotation, and the strongest non-extended leaders in
    each that beat the Nifty 500 over one month and three."""
    v = V2
    sec = X["sec"]
    sc_frame = sec[score]
    lead = B["leader"].where(B["ok"])
    ok = B["ok"] & (P.near_high >= v["f_near_high"]) & _beats(P.ret_21, X["b21"]) & _beats(X["ret63"], X["b63"])
    if anti_chase:
        ok &= (X["ext50"] <= v["f_ext50_max"]) & (X["ret63"] <= v["f_ret3m_max"])
    lv, okv, Uv = lead.values, ok.values, U.values
    names = np.asarray(P.C.columns)
    row = {d: i for i, d in enumerate(P.C.index)}
    out = []
    for d in dates:
        i = row[d]
        sc = sc_frame.loc[d].dropna()
        if len(sc) < top_sectors:
            continue
        picks = []
        for s in sc.nlargest(top_sectors).index:
            js = sec["cols"][s]
            vals = np.where(Uv[i, js] & okv[i, js], lv[i, js], np.nan)
            order = [j for j in np.argsort(-np.nan_to_num(vals, nan=-1.0)) if np.isfinite(vals[j])][:per_sector]
            picks += [(names[js[j]], None) for j in order]
        if picks:
            out.append((d, picks[:MAX_PICKS]))
    return out


def emerging_v2(P, U, B, X, YL, regime=False, old=False):
    """6-18 months listed (old=True: the shipped 6-12 months rule)."""
    v = V2
    Y, m, yl = YL
    C = P.C
    age = listing_age(P)
    if old:
        ok = Y & (C > P.sma50) & (yl >= 0.50)
        return ok, yl
    leader = yl.where(Y, B["leader"])
    near = m["near"].where(Y, P.near_high)
    pool = (Y | (U & (age <= v["e_max_age"]))) & (age >= v["e_min_age"])
    fund = X["fund"]
    quality = ~(fund["pat_cr"] < 0) & ~(fund["rev"] < 0)
    ok = (pool & (C > P.sma50) & X["sma50_up"] & (near >= v["e_near_high"]) & (leader >= v["e_leader"])
          & _beats(P.ret_21, X["b21"]) & _beats(X["ret63"], X["b63"]) & (X["ext50"] <= v["e_ext50_max"]) & quality)
    if regime:
        ok = _and_rows(ok, X["regime50"])
    return ok, leader


def _choose_v2(table, measure, eligible):
    pool = {k: v for k, v in table.items() if v and v["by_half"]["2017-21"] and eligible(v)}
    if not pool:
        return None
    raw = "lead_raw" if measure == "lead_pct" else measure
    return max(pool, key=lambda k: (pool[k]["by_half"]["2017-21"].get(raw) or -9e9))


def _eligible_lead(v):
    h = v["by_half"]["2017-21"]
    return (v["days_with_a_pick_pct"] >= 25 and h["picks"] >= 150 and h["after_costs_pct"] > 0)


def _eligible_quick(v):
    h = v["by_half"]["2017-21"]
    return (v["days_with_a_pick_pct"] >= 25 and h["picks"] >= 150 and h["after_costs_pct"] > 0
            and (h.get("lead_raw") or -1) > 0)


def _regime_helps(without, with_):
    """The weather check's own rule: better on the share rising AND the
    after-cost average, in both halves."""
    if not without or not with_:
        return False
    for h in ("2017-21", "2022-26"):
        a, b = without["by_half"][h], with_["by_half"][h]
        if not a or not b or not (b["up_pct"] > a["up_pct"] and b["after_costs_pct"] > a["after_costs_pct"]):
            return False
    return True


def replay_names(P, out, X, M, F, B, U, names=("RATNAVEER", "HFCL")):
    """Every date the old and new breakout and technical rules fired on two
    stocks the reader named, the price it would have been bought at, and
    what it did over 63 sessions and under each list's own exit."""
    C, O = P.C, P.O
    old_flag = (M["break40"] & (M["width40"] <= 0.18) & (M["relvol"] >= 2.0) & (C > P.sma200) & (B["leader"] >= 0.5))
    old_box = pd.DataFrame(False, index=C.index, columns=C.columns)
    for k in range(5):                                # listed up to five sessions after, as the engine does
        old_box |= old_flag.shift(k, fill_value=False) & (C >= M["top40"].shift(k))
    conds = [C > M["ema20"], M["ema20"] > P.sma50, P.sma50 > P.sma200, F["rsi14"] > 55, F["macd_hist"] > 0,
             (F["adx14"] >= 25) & (F["di_spread"] > 0), F["updown_volume"] > 1.2, F["relvol5"] > 1.2,
             P.near_high >= 0.95]
    card = sum(c.astype(float) for c in conds)
    bo, lvl, _r, which = breakout_v2(P, U, M, F, B, X)
    tech, _tr = technical_v2(P, U, M, F, B, X)
    rules = {"breakout (old: 40-session box, 18% wide, leader top half)": (old_box & U, 21, 8.0, None),
             "breakout (new: VCP launchpad or base turnaround)": (bo, out["taken"]["breakout"]["hold"],
                                                                  out["taken"]["breakout"]["stop"],
                                                                  out["taken"]["breakout"].get("trail")),
             "technical (old: 7 of 9 chart conditions)": ((card >= 7) & U, 21, 10.0, None),
             "technical (new: Stage-2 pullback to the 20-day average)": (tech, out["taken"]["technical"]["hold"],
                                                                         out["taken"]["technical"]["stop"],
                                                                         out["taken"]["technical"].get("trail"))}
    res = {}
    for n in names:
        if n not in C.columns:
            res[n] = {"note": "not in the price panel"}
            continue
        j = C.columns.get_loc(n)
        rec = {}
        for label, (flag, hold, stop, trail) in rules.items():
            f = flag[n].fillna(False).values
            hits = []
            last = -99
            for i in np.flatnonzero(f):
                if i - last <= 5:                     # one line per signal, not one per session it stayed listed
                    last = i
                    continue
                last = i
                if i + 1 >= len(C):
                    continue
                e = float(O.iat[i + 1, j])
                h63 = min(i + 63, len(C) - 1)
                r63 = float(C.iat[h63, j]) / e - 1
                ran = run_rule(P, [(C.index[i], [(n, None)])], hold, stop_pct=stop,
                               trail=(P.sma50 if trail else None))
                row = {"signal": str(C.index[i].date()), "bought_at": round(e, 2),
                       "ret_63_sessions_pct": round(r63 * 100, 1),
                       "complete": bool(i + 63 < len(C)),
                       "under_its_exit_pct": round(float(ran["ret"].iloc[0]) * 100, 1) if len(ran) else None,
                       "exit": (ran["why"].iloc[0] + f" after {int(ran['days'].iloc[0])} sessions") if len(ran) else None}
                if "new: VCP" in label:
                    row["pattern"] = "VCP launchpad" if which.iat[i, j] == 1 else "Base turnaround"
                if C.index[i] >= pd.Timestamp("2022-01-01") or n == "RATNAVEER":
                    hits.append(row)
            rec[label] = hits
        res[n] = rec
    return res


def main_v2():
    P = S.Panel()
    U = P.universe(10)
    F = L.features(P)
    B = L.base_parts(P, U)
    M = measures(P)
    R = S.load_results(P)
    sector = load_sectors(P)
    X = v2_measures(P, U, M, F, B, R, sector)
    days = P.C.index[262:-1]
    grid = P.C.index[262:-1:5]
    nd, ng = len(days), len(grid)
    out = {"generated": pd.Timestamp.today().date().isoformat(),
           "from": str(days[0].date()), "to": str(P.C.index[-1].date()),
           "declared": V2, "big_winner": "a pick that made 25% or more on the trade",
           "rules": "Signal on day t, bought at the next open. Returns before costs; after_costs takes off "
                    "%.2f%% a round trip. index_pct and lead_pct are against the Nifty 500 over the sessions "
                    "each pick was held. Stops are read on the close." % COST,
           "choice_rule": ("Among the new versions: the best 2017-2021 lead over the Nifty 500 (breakout, "
                           "technical, flow, emerging) among versions with a pick on 25% of sessions, 150 "
                           "picks in 2017-2021 and a profit after costs there; for quick trades the most "
                           "picks rising on 2017-2021 among versions with a profit after costs and a lead "
                           "over the index there. The 2022-2026 record is printed whatever it is."),
           "results_on_file": bool(R is not None), "sectors_on_file": bool(sector is not None)}

    def show(tag, name, r):
        if r is None:
            print(f"{tag:10s} {name:44s} no picks", flush=True)
            return
        h = r["by_half"]

        def half(x):
            return ("-" if not x else
                    f"up {x['up_pct']:5.1f} net {x['after_costs_pct']:6.2f} lead {x['lead_pct']} big {x['big_winner_pct']}")
        print(f"{tag:10s} {name:44s} days {r['days_with_a_pick_pct']:5.1f}% n {r['picks']:6d} up {r['up_pct']:5.1f} "
              f"net {r['after_costs_pct']:6.2f} lead {r['lead_pct']} t {r['lead_t']} big {r['big_winner_pct']} "
              f"held {r['days_held']} | 17-21 {half(h['2017-21'])} | 22-26 {half(h['2022-26'])}", flush=True)

    EX_B = {"21 sessions, close 8% under (old)": dict(max_hold=21, stop_pct=8.0),
            "63 sessions, close 12% under": dict(max_hold=63, stop_pct=12.0),
            "63 sessions, close 12% under, or under the 50-day after 15": dict(max_hold=63, stop_pct=12.0, trail="sma50"),
            "90 sessions, close 12% under, or under the 50-day after 15": dict(max_hold=90, stop_pct=12.0, trail="sma50")}

    def run(picks, n_dates, kw):
        kw = dict(kw)
        if kw.pop("trail", None):
            kw["trail"] = P.sma50
        if kw.pop("bounce", None):
            kw["bounce"] = X["ema10"]
        return summary(run_rule(P, picks, sma5=M["sma5"], **kw), n_dates)

    # ---- 1. breakouts ------------------------------------------------------
    out["breakout"] = {}
    old_flag = M["break40"] & (M["width40"] <= 0.18) & (M["relvol"] >= 2.0) & (P.C > P.sma200) & (B["leader"] >= 0.5)
    versions = {
        "old: box_40_leader (shipped until now)": (old_flag & U, M["top40"], M["relvol"]),
    }
    for label, kw in (("new: A VCP launchpad only", dict(pattern="A")),
                      ("new: B base turnaround only", dict(pattern="B")),
                      ("new: A or B", dict(pattern="AB")),
                      ("new: A or B, without the anti-chasing gate", dict(pattern="AB", anti_chase=False))):
        f, lv, rb, _w = breakout_v2(P, U, M, F, B, X, **kw)
        versions[label] = (f, lv, rb)
    for name, (flag, lv, rb) in versions.items():
        picks = daily_picks(flag, rb, U, days)
        flat = [(d, [(n, None) for n, _l in names]) for d, names in picks]
        rec = {"exits": {lab: run(flat, nd, kw) for lab, kw in EX_B.items()}}
        out["breakout"][name] = rec
        for lab in EX_B:
            show("breakout", f"{name[:24]} | {lab[:17]}", rec["exits"][lab])
    table = {f"{k} | {lab}": r for k, v in out["breakout"].items() if k.startswith("new")
             for lab, r in v["exits"].items() if "(old)" not in lab}
    out["breakout_choice"] = _choose_v2(table, "lead_pct", _eligible_lead)
    print("breakout taken:", out["breakout_choice"], flush=True)

    # ---- 2. technicals -----------------------------------------------------
    out["technical"] = {}
    conds = [P.C > M["ema20"], M["ema20"] > P.sma50, P.sma50 > P.sma200, F["rsi14"] > 55, F["macd_hist"] > 0,
             (F["adx14"] >= 25) & (F["di_spread"] > 0), F["updown_volume"] > 1.2, F["relvol5"] > 1.2,
             P.near_high >= 0.95]
    card = sum(c.astype(float) for c in conds)
    old_score = (card + 0.5 * S.pct(P.near_high, U)).where(U & (card >= 7))
    EX_T = {"21 sessions, close 10% under (old)": dict(max_hold=21, stop_pct=10.0),
            "42 sessions, close 12% under": dict(max_hold=42, stop_pct=12.0),
            "63 sessions, close 12% under": dict(max_hold=63, stop_pct=12.0)}
    old_picks = grid_picks(old_score, U, grid)
    out["technical"]["old: 7 of 9 scorecard (shipped until now)"] = {
        "exits": {lab: run(old_picks, ng, kw) for lab, kw in EX_T.items()}}
    for label, kw in (("new: Stage-2 pullback to the 20-day", {}),
                      ("new: the same, without the sector gate", dict(sector_gate=False))):
        f, rb = technical_v2(P, U, M, F, B, X, **kw)
        picks = daily_picks(f, rb, U, days)
        out["technical"][label] = {"exits": {lab: run(picks, nd, kw2) for lab, kw2 in EX_T.items()}}
    for k, v in out["technical"].items():
        for lab in EX_T:
            show("technical", f"{k[:24]} | {lab[:17]}", v["exits"][lab])
    table = {f"{k} | {lab}": r for k, v in out["technical"].items() if k.startswith("new")
             for lab, r in v["exits"].items() if "(old)" not in lab}
    out["technical_choice"] = _choose_v2(table, "lead_pct", _eligible_lead)
    print("technical taken:", out["technical_choice"], flush=True)

    # ---- 3. quick trades ---------------------------------------------------
    out["quick"] = {}
    up = (P.C > P.sma200) & (P.sma50 > P.sma200)
    old_q = up & (M["rsi2"] < 10) & (B["leader"] >= 0.70) & U
    EX_Q = {"first close above the 5-day average, 7 sessions, close 7% under (old)":
            dict(max_hold=7, above_sma5=True, stop_pct=7.0),
            "21 sessions, close 10% under": dict(max_hold=21, stop_pct=10.0),
            "15 sessions, close 8% under": dict(max_hold=15, stop_pct=8.0),
            "first close above the 10-day EMA, 15 sessions, close 8% under":
                dict(max_hold=15, stop_pct=8.0, bounce=True)}
    qv = {"old: rsi2 under 10, leader top 30% (shipped until now)": (old_q, -M["rsi2"]),
          "new: leader swing dip": quick_v2(P, U, M, B, X)}
    for name, (flag, rb) in qv.items():
        picks = daily_picks(flag, rb, U, days)
        out["quick"][name] = {"exits": {lab: run(picks, nd, kw) for lab, kw in EX_Q.items()}}
        for lab in EX_Q:
            show("quick", f"{name[:24]} | {lab[:17]}", out["quick"][name]["exits"][lab])
    table = {f"{k} | {lab}": r for k, v in out["quick"].items() if k.startswith("new")
             for lab, r in v["exits"].items() if "(old)" not in lab}
    out["quick_choice"] = _choose_v2(table, "up_pct", _eligible_quick)
    print("quick taken:", out["quick_choice"], flush=True)

    # ---- 4. money flow -----------------------------------------------------
    out["flow"] = {}
    EX_F = {"21 sessions, close 10% under (old)": dict(max_hold=21, stop_pct=10.0),
            "63 sessions, close 15% under": dict(max_hold=63, stop_pct=15.0)}
    if X["sec"] is None:
        out["flow"] = {"available": False}
    else:
        old_scores, _names, cols = flows(P, U, B, sector)
        fv = {"old: four sectors x four leaders (shipped until now)":
              sector_leaders(P, U, B, old_scores["money_flow"], cols, grid),
              "new: top 3 rotation sectors, 5 non-extended leaders each": flow_v2(P, U, B, X, grid),
              "new: the same on the old sector score": flow_v2(P, U, B, X, grid, score="old"),
              "new: rotation sectors, without the anti-chasing gate": flow_v2(P, U, B, X, grid, anti_chase=False)}
        for name, picks in fv.items():
            out["flow"][name] = {"exits": {lab: run(picks, ng, kw) for lab, kw in EX_F.items()}}
            for lab in EX_F:
                show("flow", f"{name[:24]} | {lab[:17]}", out["flow"][name]["exits"][lab])
        table = {f"{k} | {lab}": r for k, v in out["flow"].items() if k.startswith("new")
                 for lab, r in v["exits"].items() if "(old)" not in lab}
        out["flow_choice"] = _choose_v2(table, "lead_pct", _eligible_lead)
        print("flow taken:", out["flow_choice"], flush=True)

    # ---- 5. emerging -------------------------------------------------------
    out["emerging"] = {}
    YL = young_leader(P, U)
    W = U | YL[0]
    EX_E = {"21 sessions, close 10% under (old)": dict(max_hold=21, stop_pct=10.0),
            "63 sessions, close 15% under": dict(max_hold=63, stop_pct=15.0),
            "90 sessions, close 15% under, or under the 50-day after 15":
                dict(max_hold=90, stop_pct=15.0, trail="sma50")}
    ev = {"old: listed 6-12 months, above the 50-day (shipped until now)": emerging_v2(P, U, B, X, YL, old=True),
          "new: listed 6-18 months, Stage-2 strength": emerging_v2(P, U, B, X, YL)}
    for name, (flag, rb) in ev.items():
        picks = grid_picks(rb.where(flag), W, grid)
        out["emerging"][name] = {"exits": {lab: run(picks, ng, kw) for lab, kw in EX_E.items()}}
        for lab in EX_E:
            show("emerging", f"{name[:24]} | {lab[:17]}", out["emerging"][name]["exits"][lab])
    table = {f"{k} | {lab}": r for k, v in out["emerging"].items() if k.startswith("new")
             for lab, r in v["exits"].items() if "(old)" not in lab}
    out["emerging_choice"] = _choose_v2(table, "lead_pct", _eligible_lead)
    print("emerging taken:", out["emerging_choice"], flush=True)

    # ---- the market-weather check -------------------------------------------
    def parse(choice, exits):
        if not choice:
            return None, None
        ver, lab = choice.split(" | ", 1)
        return ver, exits[lab]
    weather = {}
    ver, kw = parse(out["breakout_choice"], EX_B)
    if ver:
        pat = {"new: A VCP launchpad only": "A", "new: B base turnaround only": "B"}.get(ver, "AB")
        anti = "without the anti-chasing" not in ver
        rows = {}
        for reg in (False, True):
            f, lv, rb, _w = breakout_v2(P, U, M, F, B, X, pattern=pat, anti_chase=anti, regime=reg)
            picks = [(d, [(n, None) for n, _l in names]) for d, names in daily_picks(f, rb, U, days)]
            rows[reg] = run(picks, nd, kw)
        weather["breakout"] = {"without": rows[False], "with": rows[True], "adopted": _regime_helps(rows[False], rows[True])}
    ver, kw = parse(out["quick_choice"], EX_Q)
    if ver:
        rows = {}
        for reg in (False, True):
            f, rb = quick_v2(P, U, M, B, X, regime=reg)
            rows[reg] = run(daily_picks(f, rb, U, days), nd, kw)
        weather["quick"] = {"without": rows[False], "with": rows[True], "adopted": _regime_helps(rows[False], rows[True])}
    ver, kw = parse(out["emerging_choice"], EX_E)
    if ver:
        rows = {}
        for reg in (False, True):
            f, rb = emerging_v2(P, U, B, X, YL, regime=reg)
            rows[reg] = run(grid_picks(rb.where(f), W, grid), ng, kw)
        weather["emerging"] = {"without": rows[False], "with": rows[True], "adopted": _regime_helps(rows[False], rows[True])}
    out["market_weather"] = weather
    for k, w in weather.items():
        show("weather", f"{k} without", w["without"])
        show("weather", f"{k} with Nifty 500 > 50-day", w["with"])
        print("  adopted:", w["adopted"], flush=True)

    # ---- what was taken, as the engine needs it ------------------------------
    def spec(choice, exits):
        if not choice:
            return None
        ver, lab = choice.split(" | ", 1)
        kw = exits[lab]
        return {"version": ver, "exit": lab, "hold": kw["max_hold"], "stop": kw.get("stop_pct"),
                "trail": kw.get("trail"), "bounce": bool(kw.get("bounce"))}
    out["taken"] = {"breakout": spec(out["breakout_choice"], EX_B),
                    "technical": spec(out["technical_choice"], EX_T),
                    "quick": spec(out["quick_choice"], EX_Q),
                    "flow": spec(out.get("flow_choice"), EX_F),
                    "emerging": spec(out["emerging_choice"], EX_E)}
    print(json.dumps(out["taken"], indent=1), flush=True)

    # ---- the two stocks a reader named ---------------------------------------
    if out["taken"]["breakout"] and out["taken"]["technical"]:
        out["named_stocks"] = replay_names(P, out, X, M, F, B, U)
        print(json.dumps(out["named_stocks"], indent=1), flush=True)
    for k in ("breakout", "technical", "quick", "flow", "emerging"):
        for v in (out.get(k) or {}).values():
            if isinstance(v, dict):
                for r in (v.get("exits") or {}).values():
                    if r:
                        r.pop("lead_raw", None)
                        for h in r["by_half"].values():
                            if h:
                                h.pop("lead_raw", None)
    with open(V2_OUT, "w", encoding="utf-8") as fh:
        json.dump(L._clean(out), fh, indent=1)
    print("\nwrote", V2_OUT)



# ==========================================================================
# SECTOR BREAKOUT (December 2026)
#
#     python research/setups_lab.py --sector     # research/setups-lab-sector.json
#
# A reader pointed out that RATNAVEER and HFCL broke out while their whole
# industry was breaking out. Asked: does requiring the stock's SECTOR to be
# breaking out too improve the shipped lists? Two screens, declared before
# the run, each built from an equal-weight index of the industry's liquid
# stocks (NSE's industry list; a stock with no industry passes, as with
# every other sector screen):
#
#   new_high   the sector index made a new 60-session closing high in the
#              last 10 sessions
#   near_high  the sector index is within 3% of its 60-session high
#
# applied as a gate, and (breakouts only) as an order: sector breakouts first.
# Tried on the shipped breakout (pattern A), on A or B (the HFCL pattern) and
# on the shipped technical list, each with its shipped exit.
#
# THE RULE, set before the run: a screen is adopted on a list if, on
# 2017-2021, it raises the lead over the Nifty 500 above the list's own,
# keeps a profit after costs, a pick on 25% of sessions and 150 picks. Its
# 2022-2026 record is printed whatever it is.
# ==========================================================================

SECTOR_OUT = os.environ.get("SETUPS_LAB_SECTOR_OUT", "").strip() or os.path.join(HERE, "setups-lab-sector.json")
SECTOR_HIGH_WINDOW = 60
SECTOR_RECENT = 10
SECTOR_NEAR = 0.97


def sector_index_frames(P, U, sector):
    """date x stock: does the stock's industry index stand at (or near) a
    60-session high. The index is the mean daily return of the industry's
    liquid stocks, chained. NaN where the stock has no industry."""
    r1 = (P.C / P.C.shift(1) - 1).where(U)
    names = sorted(s for s in sector.dropna().unique())
    new_high = np.full(P.C.shape, np.nan)
    near_high = np.full(P.C.shape, np.nan)
    idx_out = {}
    for s in names:
        js = np.flatnonzero((sector == s).values)
        count = U.values[:, js].sum(axis=1)
        ret = np.nanmean(r1.values[:, js], axis=1) if len(js) else np.full(len(P.C), np.nan)
        ret = np.where(count >= 8, ret, 0.0)
        level = pd.Series(np.cumprod(1 + np.nan_to_num(ret)), index=P.C.index)
        top = level.rolling(SECTOR_HIGH_WINDOW, min_periods=SECTOR_HIGH_WINDOW).max()
        at = (level >= top).astype(float).where(top.notna())
        nh = at.rolling(SECTOR_RECENT, min_periods=1).max().values
        near = (level >= SECTOR_NEAR * top).astype(float).where(top.notna()).values
        ok = count >= 8
        new_high[:, js] = np.where(ok, nh, np.nan)[:, None]
        near_high[:, js] = np.where(ok, near, np.nan)[:, None]
        idx_out[s] = level
    f = lambda a: pd.DataFrame(a, index=P.C.index, columns=P.C.columns)
    return {"new_high": f(new_high), "near_high": f(near_high), "levels": idx_out}


def main_sector():
    P = S.Panel()
    U = P.universe(10)
    F = L.features(P)
    B = L.base_parts(P, U)
    M = measures(P)
    R = S.load_results(P)
    sector = load_sectors(P)
    X = v2_measures(P, U, M, F, B, R, sector)
    SB = sector_index_frames(P, U, sector)
    days = P.C.index[262:-1]
    nd = len(days)
    out = {"generated": pd.Timestamp.today().date().isoformat(),
           "from": str(days[0].date()), "to": str(P.C.index[-1].date()),
           "screens": {"new_high": "the sector index made a new 60-session closing high in the last 10 sessions",
                       "near_high": "the sector index is within 3% of its 60-session high"},
           "rule": ("Adopted on a list if, on 2017-2021, it raises the lead over the Nifty 500 above the list's own, "
                    "keeps a profit after costs, a pick on 25% of sessions and 150 picks. 2022-2026 printed "
                    "whatever it is."),
           "lists": {}}

    def run(picks, kw):
        return summary(run_rule(P, picks, **kw), nd)

    def gate(screen):
        g = SB[screen]
        return g.isna() | (g >= 1)                         # no industry: passes, as every sector screen does

    def show(name, r):
        h = r["by_half"]
        print(f"{name:52s} n {r['picks']:6d} days {r['days_with_a_pick_pct']:5.1f}% up {r['up_pct']:5.1f} "
              f"net {r['after_costs_pct']:6.2f} lead {r['lead_pct']} t {r['lead_t']} big {r['big_winner_pct']} | "
              f"17-21 up {h['2017-21']['up_pct']} net {h['2017-21']['after_costs_pct']} lead {h['2017-21']['lead_pct']} | "
              f"22-26 up {h['2022-26']['up_pct']} net {h['2022-26']['after_costs_pct']} lead {h['2022-26']['lead_pct']}",
              flush=True)

    ex = dict(max_hold=63, stop_pct=12.0)
    cases = {}
    for pat in ("A", "AB"):
        f, _lv, rb, _w = breakout_v2(P, U, M, F, B, X, pattern=pat)
        cases[f"breakout {pat}"] = (f, rb)
    f, rb = technical_v2(P, U, M, F, B, X)
    cases["technical (pullback)"] = (f, rb)
    for base, (flag, rb) in cases.items():
        rec = {}
        flat = lambda picks: [(d, [(n, None) for n, _l in names]) for d, names in picks]
        rec["as shipped"] = run(flat(daily_picks(flag, rb, U, days)), ex)
        for screen in ("new_high", "near_high"):
            rec[f"gate: {screen}"] = run(flat(daily_picks(flag & gate(screen), rb, U, days)), ex)
        if base.startswith("breakout"):
            boosted = rb + 1000.0 * (SB["new_high"].fillna(0) >= 1)
            rec["order: sector new highs first"] = run(flat(daily_picks(flag, boosted, U, days)), ex)
        for k, r in rec.items():
            show(f"{base} | {k}", r)
        mine = rec["as shipped"]["by_half"]["2017-21"]["lead_raw"]
        adopted = {k: r for k, r in rec.items() if k != "as shipped" and r and _eligible_lead(r)
                   and r["by_half"]["2017-21"]["lead_raw"] > mine}
        best = max(adopted, key=lambda k: adopted[k]["by_half"]["2017-21"]["lead_raw"]) if adopted else None
        print(f"  {base}: adopted -> {best}", flush=True)
        for r in rec.values():
            r.pop("lead_raw", None)
            for h in r["by_half"].values():
                if h:
                    h.pop("lead_raw", None)
        out["lists"][base] = {"versions": rec, "adopted": best}

    # The two stocks a reader named: was their industry breaking out the day the breakout fired?
    sector_of = sector.to_dict()
    named = {}
    for sym, d in (("RATNAVEER", "2026-07-27"), ("HFCL", "2026-04-09"), ("HFCL", "2023-08-07"),
                   ("HFCL", "2022-10-31")):
        if sym not in P.C.columns:
            continue
        sec = sector_of.get(sym)
        i = P.C.index.get_loc(pd.Timestamp(d))
        named[f"{sym} {d}"] = {"sector": sec,
                               "sector_new_high": (None if not sec else bool(SB["new_high"].at[P.C.index[i], sym] >= 1)),
                               "sector_near_high": (None if not sec else bool(SB["near_high"].at[P.C.index[i], sym] >= 1))}
    out["named_stocks"] = named
    print(json.dumps(named, indent=1), flush=True)
    with open(SECTOR_OUT, "w", encoding="utf-8") as fh:
        json.dump(L._clean(out), fh, indent=1)
    print("\nwrote", SECTOR_OUT)


if __name__ == "__main__":
    if "--v2" in sys.argv[1:]:
        main_v2()
    elif "--sector" in sys.argv[1:]:
        main_sector()
    else:
        main()
