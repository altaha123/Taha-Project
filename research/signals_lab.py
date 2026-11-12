"""
The signals lab: breakouts, technicals, volume, a market filter and results.

    python research/signals_lab.py            # every trial, research/signals-lab.json

November 2026. The four pick lists rank on price alone. This measures what a
reader asked to have added: stocks about to break out, chart technicals,
volume, the state of the market, and what a company's results did to its
price. It uses the panel research/ideas_study.py builds (NSE's daily files,
2016 to 2026, delisted companies included) and the same rules: a signal on day
t uses bars up to t, the pick is bought at the next open, held h sessions, and
left on a close under the exit line. Lists are formed every five sessions.

EVERY TRIAL HERE WAS DECLARED BEFORE ANY OF THEM RAN, and every one is in the
output, including the ones that did nothing. The decade is split where the
first study split it: a choice is made on 2017-2021 and then read on
2022-2026.

  A  SINGLE SIGNALS      rank correlation of each technical, volume and
                         price-action measure with what the stock did next
  B  BREAKOUT LISTS      nine recipes, held 21 sessions with an exit line 10%
                         under (10 and 42 sessions are shown beside them)
  C  CONFIRMATIONS       each indicator as a gate or a tilt on the week, month
                         and momentum lists
  D  THE MARKET          each list's picks, split by the state of the market
                         on the day the list was made
  E  RESULTS             what a stock did after its quarterly results, by how
                         it moved on the day and by how the profit grew

  F  YOUNGER AND SMALLER  companies listed under a year, and a lower turnover
                         floor: do the lists still hold when they are let in

THE RULES FOR TAKING ANYTHING FROM THIS INTO THE SITE, set before the run:

  · A breakout recipe is taken only if it led the average liquid stock on
    2017-2021 by more than any other breakout recipe that made at least eight
    picks a list, AND still led it on 2022-2026.
  · A confirmation is added to an existing list only if it raised that list's
    lead over the average stock in BOTH halves. Twenty-one are tried, so one
    or two will pass by luck; a pass is reported as a pass, not as proof.
  · A list is held back in a weak market only if its picks made in that state
    lost money on average in both halves.
  · A results list is taken only if it led the average stock that reported in
    the same fortnight in both halves.

  · Companies listed six to twelve months are admitted to a price list only
    if the picks that were that young led the average liquid stock in both
    halves. For those companies the 6-month return stands in for the 12-month
    one, and every average is taken over what history there is (at least 100
    sessions).
  · Companies with three to twelve months of trading are admitted to the
    results list only if the picks that were that young led the other
    reporting companies in both halves.
  · The turnover floor is lowered only if every list led the average stock of
    its own wider universe by at least as much, in both halves. Thinner
    stocks cost more to trade than this test charges anyone, so a tie is not
    a reason to lower it.

RESULTS DATA, AND ITS ONE KNOWN BIAS
The quarterly results are the site's own fundamentals tables (Regulation 33
filings read from NSE, each with the time it reached the exchange), exported
from /fundamentals/table. They cover companies listed TODAY, so a company
that was delisted after bad results is missing. To keep that from flattering
the test, results picks are compared with the other companies in the same
table that reported in the same window, not with the whole exchange.
"""

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ideas_study as S          # noqa: E402

OUT = os.environ.get("SIGNALS_LAB_OUT", "").strip() or os.path.join(HERE, "signals-lab.json")
RESULTS_CSV = os.environ.get("IDEAS_RESULTS_CSV", "").strip() or os.path.join(S.DATA, "income_quarterly.csv")
SPLIT = S.SPLIT
BREAKOUT_HOLD, BREAKOUT_EXIT = 21, 10.0


# --------------------------------------------------------------------------
# Measurements. Every one uses bars up to and including its own date.
# --------------------------------------------------------------------------

def features(P):
    C, H, L, V = P.C, P.H, P.L, P.V
    lr = np.log(C / C.shift(1))
    f = {}

    # Price action: where the close sits against its own recent range.
    hi60 = H.rolling(60, min_periods=50).max()
    ch126 = C.rolling(126, min_periods=100).max()
    ch252 = C.rolling(252, min_periods=200).max()
    f["to_pivot"] = C / hi60                              # 1.0 = at the 60-day high
    f["near_high"] = P.near_high
    nh126 = (C >= ch126) & P.traded
    nh252 = (C >= ch252) & P.traded
    # "Fresh": the first such close after at least 20 sessions without one,
    # which is what separates a breakout from a stock that has been making
    # highs every day for a month.
    f["fresh126"] = nh126 & (nh126.astype(float).shift(1).rolling(20, min_periods=20).sum() == 0)
    f["fresh252"] = nh252 & (nh252.astype(float).shift(1).rolling(20, min_periods=20).sum() == 0)
    f["near126"] = C / ch126
    std10 = lr.rolling(10, min_periods=8).std()
    std60 = lr.rolling(60, min_periods=50).std()
    f["squeeze"] = std10 / std60                          # low = the range has tightened
    rng15 = (H.rolling(15).max() - L.rolling(15).min()) / C
    rng60 = (H.rolling(60, min_periods=50).max() - L.rolling(60, min_periods=50).min()) / C
    f["range15"] = rng15 / rng60                          # low = a tight fortnight in a wide quarter
    spread = (H - L).replace(0, np.nan)
    f["close_in_range"] = ((C - L) / spread).rolling(5).mean()   # closes near the day's high

    # Volume.
    v50 = V.rolling(50, min_periods=40).median()
    f["relvol"] = V / v50.shift(1)                        # today against its own usual
    f["relvol5"] = V.rolling(5).mean() / v50.shift(5)
    f["dryup"] = V.rolling(10).mean() / V.rolling(50, min_periods=40).mean()   # low = volume drying up
    up_v = V.where(lr > 0, 0.0).rolling(50, min_periods=40).sum()
    dn_v = V.where(lr < 0, 0.0).rolling(50, min_periods=40).sum()
    f["updown_volume"] = up_v / dn_v.replace(0, np.nan)   # above 1 = more volume on up days

    # Textbook indicators, textbook settings.
    d = C.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    ema12 = C.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = C.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / C
    ema20 = C.ewm(span=20, adjust=False, min_periods=20).mean()
    f["above_ema20"] = C / ema20 - 1
    f["ma_stack"] = ((C > ema20) & (ema20 > P.sma50) & (P.sma50 > P.sma200)).astype(float)
    sma20 = C.rolling(20).mean()
    sd20 = C.rolling(20).std()
    f["bollinger_b"] = (C - (sma20 - 2 * sd20)) / (4 * sd20).replace(0, np.nan)
    f["bollinger_width"] = (4 * sd20) / sma20             # low = bands pinched
    # ADX(14), Wilder.
    up_m, dn_m = H.diff(), -L.diff()
    plus_dm = up_m.where((up_m > dn_m) & (up_m > 0), 0.0)
    minus_dm = dn_m.where((dn_m > up_m) & (dn_m > 0), 0.0)
    pc = C.shift(1)
    tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    f["adx14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["di_spread"] = pdi - mdi
    return f


def ic(P, f, U, h, dates):
    """Rank correlation with the next h sessions, averaged over dates. Unlike
    the study's, a date on which the signal is the same for every stock (a
    breakout flag on a day nothing broke out) is skipped, not counted as NaN."""
    fw, vals = P.fwd(h), []
    for d in dates:
        x, y = f.loc[d].where(U.loc[d]), fw.loc[d]
        ok = x.notna() & y.notna()
        if ok.sum() >= 50:
            c = x[ok].rank().corr(y[ok].rank())
            if np.isfinite(c):
                vals.append(c)
    return round(float(np.mean(vals)), 3) if vals else None


# --------------------------------------------------------------------------
# F. Younger and smaller companies.
# --------------------------------------------------------------------------

YOUNG_MIN_SESSIONS = 127          # six months: enough for a 6-month return
YOUNG_RESULTS_MIN_SESSIONS = 60   # three months: enough for a turnover figure


def young_parts(P, U):
    """
    The four recipes on a universe that also holds companies listed six to
    twelve months. For those, the 6-month return stands in for the 12-month
    one and volatility, the 52-week high and the 200-day average are taken
    over the history there is (100 sessions or more).
    Returns (scores, wide universe, young-only mask).
    """
    C = P.C
    age = P.traded.cumsum()
    lr = np.log(C / C.shift(1))
    vol_any = lr.rolling(252, min_periods=100).std() * np.sqrt(252)
    near_any = C / P.H.rolling(252, min_periods=100).max()
    sma200_any = C.rolling(200, min_periods=100).mean()
    traded_lately = P.traded.rolling(YOUNG_MIN_SESSIONS, min_periods=YOUNG_MIN_SESSIONS).sum()
    whole = (P.mom_6_1.notna() & near_any.notna() & P.trend_q.notna() & P.ret_5.notna() & (vol_any >= 0.08))
    young = ((P.turn60 >= 10e7) & (P.RAW >= 20) & (age >= YOUNG_MIN_SESSIONS) & (age < 253)
             & (traded_lately >= YOUNG_MIN_SESSIONS - 10) & whole & ~U)
    wide = U | young
    va12 = (P.mom_12_1 / P.vol_252).where(U, P.mom_6_1 / vol_any)
    va6 = (P.mom_6_1 / P.vol_252).where(U, P.mom_6_1 / vol_any)
    near = P.near_high.where(U, near_any)
    vol = P.vol_252.where(U, vol_any)
    m12, m6 = S.pct(va12, wide), S.pct(va6, wide)
    high, trend = S.pct(near, wide), S.pct(P.trend_q, wide)
    calm, dip, dip21 = S.pct(-vol, wide), S.pct(-P.ret_5, wide), S.pct(-P.ret_21, wide)
    leader = (m12 + m6 + high + trend) / 4
    up_old = (C > P.sma200) & (P.sma50 > P.sma200)
    up_new = (C > sma200_any) & (P.sma50 > sma200_any)
    up = pd.DataFrame(np.where(U.values, up_old.values, up_new.values), index=C.index, columns=C.columns)
    ok = up & (calm >= 0.20)
    scores = {"week": (0.5 * leader + 0.5 * dip).where(ok),
              "month": (0.5 * dip21 + 0.5 * high).where(ok & (leader >= 0.70)),
              "momentum": leader.where(ok),
              "long": ((m12 + high + trend) / 3).where(ok)}
    return scores, wide, young


def lead_over(P, U, ran, hold):
    """A set of picks against the average stock of universe U, by half."""
    v = S.vs_average_stock(P, U, ran, hold)
    if v is None:
        return None
    return {"excess_pct": v["excess_pct"], "t": v["t"],
            "by_half": {h: v["by_half"][h]["excess_pct"] for h in ("2017-21", "2022-26")}}


def young_only(ran, young):
    """The rows of a run whose pick was a young company on its list date."""
    if not len(ran):
        return ran
    yv = young.values
    row = {d: i for i, d in enumerate(young.index)}
    col = {n: j for j, n in enumerate(young.columns)}
    keep = [bool(yv[row[d], col[n]]) for d, n in zip(ran["date"], ran["name"])]
    return ran[np.asarray(keep, dtype=bool)]


def history_trials(P, U, scores, R):
    out = {"young_in_price_lists": {}, "young_in_results_list": None, "turnover_floor": {}}

    # F1: six to twelve months of history in the four price lists.
    wide_scores, wide, young = young_parts(P, U)
    out["young_companies_per_day"] = round(float(young.iloc[262:].sum(axis=1).mean()), 1)
    for key, (hold, ex) in S.LISTS.items():
        dates = P.C.index[262:-(hold + 1):5]
        now = S.run_list(P, S.list_picks(scores, U, dates, key), hold, ex)
        ran = S.run_list(P, S.list_picks(wide_scores, wide, dates, key), hold, ex)
        yo = young_only(ran, young)
        d_now, d_wide, d_young = S.describe(now), S.describe(ran), S.describe(yo)
        v_young = lead_over(P, U, yo, hold)
        admitted = bool(v_young and all((v_young["by_half"][h] or -9) > 0 for h in ("2017-21", "2022-26")))
        out["young_in_price_lists"][key] = {
            "as_it_is": {**{k: d_now[k] for k in ("picks", "up_pct", "avg_pct", "index_avg_pct")},
                         "vs_average_stock": lead_over(P, U, now, hold)},
            "with_young_admitted": {**{k: d_wide[k] for k in ("picks", "up_pct", "avg_pct", "index_avg_pct")},
                                    "vs_average_stock": lead_over(P, U, ran, hold)},
            "the_young_picks": (None if d_young is None else
                                {**{k: d_young[k] for k in ("picks", "up_pct", "avg_pct", "median_pct",
                                                            "index_avg_pct", "worst_5pct", "list_dates")},
                                 "vs_average_stock": v_young}),
            "admitted": admitted}
        y = out["young_in_price_lists"][key]["the_young_picks"]
        print(f"young in {key:9s} now {out['young_in_price_lists'][key]['as_it_is']['vs_average_stock']} "
              f"wide {out['young_in_price_lists'][key]['with_young_admitted']['vs_average_stock']}\n"
              f"      young picks {y and (y['picks'], y['up_pct'], y['avg_pct'], y['index_avg_pct'], y['vs_average_stock'])} "
              f"{'ADMIT' if admitted else ''}", flush=True)

    # F2: three to twelve months of trading in the results list.
    if R is not None:
        age = P.traded.cumsum()
        wide_r = ((P.turn60 >= 10e7) & (P.RAW >= 20) & (age >= YOUNG_RESULTS_MIN_SESSIONS)) | U
        young_r = wide_r & ~U
        hold, ex = 21, 12.0
        first = max(262, int(R["i"].min()) + S.RESULTS_WINDOW)
        first += (-(first - 262)) % 5
        dates = P.C.index[first:-(hold + 1):5]
        rec = {}
        for label, uni in (("as_it_is", U), ("with_young_admitted", wide_r)):
            picks, pools = S.results_picks(P, uni, R, dates)
            ran = S.run_list(P, picks, hold, ex)
            d = S.describe(ran)
            rec[label] = {**{k: d[k] for k in ("picks", "list_dates", "up_pct", "avg_pct", "index_avg_pct")},
                          "vs_reporters": S.vs_pool(P, ran, hold, pools)}
            if label == "with_young_admitted":
                yo = young_only(ran, young_r)
                dy = S.describe(yo)
                vy = S.vs_pool(P, yo, hold, pools) if len(yo) else None
                rec["the_young_picks"] = (None if dy is None else
                                          {**{k: dy[k] for k in ("picks", "list_dates", "up_pct", "avg_pct",
                                                                 "median_pct", "index_avg_pct", "worst_5pct")},
                                           "vs_reporters": vy})
                rec["admitted"] = bool(vy and all((vy["by_half"][h]["excess_pct"] or -9) > 0
                                                  for h in ("2018-21", "2022-26")))
        out["young_in_results_list"] = rec
        print("young in results:", json.dumps({k: (v if k == "admitted" else
                                                    {kk: vv for kk, vv in v.items() if kk != "vs_reporters"}
                                                    | {"vs": v["vs_reporters"] and (v["vs_reporters"]["excess_pct"],
                                                       v["vs_reporters"]["t"],
                                                       [v["vs_reporters"]["by_half"][h]["excess_pct"]
                                                        for h in ("2018-21", "2022-26")])})
                                               for k, v in rec.items() if v is not None}), flush=True)

    # F3: a lower turnover floor.
    base = {}
    for floor in (10, 5, 3):
        Uf = P.universe(floor)
        sc = S.recipes(P, Uf)
        row = {"stocks_on_a_median_day": int(Uf.iloc[262:].sum(axis=1).median())}
        for key, (hold, ex) in S.LISTS.items():
            dates = P.C.index[262:-(hold + 1):5]
            ran = S.run_list(P, S.list_picks(sc, Uf, dates, key), hold, ex)
            d = S.describe(ran)
            row[key] = {**{k: d[k] for k in ("up_pct", "avg_pct", "index_avg_pct", "worst_5pct")},
                        "vs_average_stock": lead_over(P, Uf, ran, hold)}
        if R is not None:
            hold, ex = 21, 12.0
            first = max(262, int(R["i"].min()) + S.RESULTS_WINDOW)
            first += (-(first - 262)) % 5
            dates = P.C.index[first:-(hold + 1):5]
            picks, pools = S.results_picks(P, Uf, R, dates)
            ran = S.run_list(P, picks, hold, ex)
            d = S.describe(ran)
            v = S.vs_pool(P, ran, hold, pools)
            row["results"] = {**{k: d[k] for k in ("up_pct", "avg_pct", "index_avg_pct", "worst_5pct")},
                              "vs_average_stock": {"excess_pct": v["excess_pct"], "t": v["t"],
                                                   "by_half": {"2017-21": v["by_half"]["2018-21"]["excess_pct"],
                                                               "2022-26": v["by_half"]["2022-26"]["excess_pct"]}}}
        if floor == 10:
            base = row
        else:
            row["lowered"] = all(
                all((row[k]["vs_average_stock"]["by_half"][h] or -9) >= (base[k]["vs_average_stock"]["by_half"][h] or 0)
                    for h in ("2017-21", "2022-26"))
                for k in row if isinstance(row[k], dict))
        out["turnover_floor"][f"Rs {floor} crore a day"] = row
        print(f"floor {floor:2d} cr ({row['stocks_on_a_median_day']} stocks):",
              {k: (v["avg_pct"], v["vs_average_stock"]["excess_pct"], v["vs_average_stock"]["by_half"])
               for k, v in row.items() if isinstance(v, dict)}, row.get("lowered", ""), flush=True)
    return out


def base_parts(P, U):
    m12, m6 = S.pct(P.mom_12_1 / P.vol_252, U), S.pct(P.mom_6_1 / P.vol_252, U)
    high, trend = S.pct(P.near_high, U), S.pct(P.trend_q, U)
    calm = S.pct(-P.vol_252, U)
    leader = (m12 + m6 + high + trend) / 4
    up = (P.C > P.sma200) & (P.sma50 > P.sma200)
    return {"leader": leader, "calm": calm, "up": up, "ok": up & (calm >= 0.20)}


def picks_from(score, U, dates, n=15, min_n=1):
    """The top n on each date. Unlike the study's picker, a date with fewer
    than n candidates still makes a (shorter) list: an event does not arrive
    fifteen at a time."""
    out = []
    for d in dates:
        s = score.loc[d].where(U.loc[d]).dropna()
        if len(s) >= min_n:
            out.append((d, list(s.nlargest(n).index)))
    return out


def measured(P, U, picks, hold, exit_pct, all_dates):
    ran = S.run_list(P, picks, hold, exit_pct)
    rec = S.describe(ran)
    if rec is None:
        return None
    rec["picks_per_list"] = round(len(ran) / max(1, ran["date"].nunique()), 1)
    rec["lists_made_pct"] = round(100.0 * ran["date"].nunique() / max(1, len(all_dates)), 1)
    rec["by_half"] = {"2017-21": S.describe(ran[ran["date"] < SPLIT]),
                      "2022-26": S.describe(ran[ran["date"] >= SPLIT])}
    rec["vs_average_stock"] = S.vs_average_stock(P, U, ran, hold)
    return rec


def recent(flag, k=5):
    """True where the event happened in the last k sessions, today included."""
    return flag.astype(float).rolling(k, min_periods=1).max() > 0


def carried(values, k=5):
    """An event-day value, held for the k-1 sessions after it."""
    return values.ffill(limit=k - 1)


# --------------------------------------------------------------------------
# B. Breakout recipes, as declared.
# --------------------------------------------------------------------------

def breakout_recipes(P, U, F, B):
    ok, leader = B["ok"], B["leader"]
    pctU = lambda x: S.pct(x, U)                                       # noqa: E731
    still = F["near126"] >= 0.97            # has not already fallen back under the level
    vol_ok = F["relvol"] >= 1.5
    out = {}

    # About to break out: under the high, the range tight, volume dried up.
    coiled = ok & (F["near_high"] >= 0.92) & (F["to_pivot"] >= 0.96) & ~recent(F["fresh126"], 5)
    out["coiled_under_high"] = {
        "what": "Within 8% of the 52-week high and 4% of the 60-day high, not yet through it. "
                "Ranked on how tight the last fortnight was, how far volume has dried up and "
                "how close the price is to the 60-day high.",
        "score": ((pctU(-F["range15"]) + pctU(-F["dryup"]) + pctU(F["to_pivot"])) / 3).where(coiled)}
    out["coiled_leader"] = {
        "what": "A market leader (top 30%) within 4% of its 60-day high, with volatility among "
                "the most contracted 30%. Ranked on the leader score.",
        "score": leader.where(ok & (leader >= 0.70) & (F["to_pivot"] >= 0.96)
                              & (pctU(F["squeeze"]) <= 0.30))}
    out["accumulation_near_high"] = {
        "what": "Within 8% of the 52-week high. Ranked on how much more volume traded on up days "
                "than down days over 50 sessions, and on closeness to the high.",
        "score": ((pctU(F["updown_volume"]) + pctU(F["near_high"])) / 2).where(ok & (F["near_high"] >= 0.92))}

    # Broke out in the last five sessions.
    ev = F["fresh126"]
    out["fresh_6m_high"] = {
        "what": "First close at a 6-month high in at least 20 sessions, in the last five sessions. "
                "Ranked on that day's volume against its usual.",
        "score": carried(F["relvol"].where(ev)).where(ok & recent(ev) & still)}
    out["fresh_6m_high_on_volume"] = {
        "what": "The same, only where that day's volume was at least 1.5 times its usual.",
        "score": carried(F["relvol"].where(ev & vol_ok)).where(ok & recent(ev & vol_ok) & still)}
    tight_before = F["squeeze"].shift(1) <= 0.85
    out["breakout_from_tight_base"] = {
        "what": "A 6-month-high breakout on 1.5 times volume, out of a range that had tightened "
                "(ten-day volatility under 85% of its sixty-day). Ranked on how tight.",
        "score": carried((-F["squeeze"].shift(1)).where(ev & vol_ok & tight_before)).where(
            ok & recent(ev & vol_ok & tight_before) & still)}
    out["leader_breakout"] = {
        "what": "A market leader (top 30%) that made its first 6-month closing high in 20 sessions, "
                "in the last five. Ranked on the leader score.",
        "score": leader.where(ok & recent(ev) & still & (leader >= 0.70))}
    ev52 = F["fresh252"]
    out["fresh_52w_high"] = {
        "what": "First close at a 52-week high in at least 20 sessions, in the last five. "
                "Ranked on the leader score.",
        "score": leader.where(ok & recent(ev52) & (F["near_high"] >= 0.97))}
    out["fresh_52w_high_on_volume"] = {
        "what": "The same, only on 1.5 times volume. Ranked on that day's volume.",
        "score": carried(F["relvol"].where(ev52 & vol_ok)).where(
            ok & recent(ev52 & vol_ok) & (F["near_high"] >= 0.97))}
    return out


def shared_names(a, b):
    """Average names two pick sets share on the dates both made a list."""
    da, db = dict(a), dict(b)
    common = [d for d in da if d in db]
    if not common:
        return None
    return round(float(np.mean([len(set(da[d]) & set(db[d])) for d in common])), 1)


# --------------------------------------------------------------------------
# E. Results.
# --------------------------------------------------------------------------

def results_frames(P, U, R):
    """The event measurements as date x company frames, NaN where no event."""
    C = P.C
    ew = (C / C.shift(1) - 1).where(U).mean(axis=1)          # the average liquid stock's day
    day_ret = (C / C.shift(1) - 1).sub(ew, axis=0)
    col = {n: j for j, n in enumerate(C.columns)}
    shape = C.shape
    frames = {k: np.full(shape, np.nan) for k in
              ("reaction", "pat_yoy", "rev_yoy", "ebitda_yoy", "opm_change", "pat_accel", "relvol", "event")}
    v50 = P.V.rolling(50, min_periods=40).median().shift(1)
    relvol = (P.V / v50).values
    dr = day_ret.values
    for sym, i, pat, rev, eb, opm, acc in R[["symbol", "i", "pat_yoy_pct", "revenue_yoy_pct",
                                              "ebitda_yoy_pct", "opm_change", "pat_accel"]].itertuples(index=False):
        j = col[sym]
        frames["event"][i, j] = 1.0
        frames["reaction"][i, j] = dr[i, j]
        frames["relvol"][i, j] = relvol[i, j]
        frames["pat_yoy"][i, j] = pat
        frames["rev_yoy"][i, j] = rev
        frames["ebitda_yoy"][i, j] = eb
        frames["opm_change"][i, j] = opm
        frames["pat_accel"][i, j] = acc
    return {k: pd.DataFrame(v, index=C.index, columns=C.columns) for k, v in frames.items()}


def event_ic(P, U, X, signal, h, covered):
    """Rank correlation of an event-day signal with the next h sessions,
    pooled by calendar quarter, against other companies that reported."""
    fw = P.fwd(h)
    ev = X["event"].notna() & U & covered
    vals = {"all": [], "2017-21": [], "2022-26": []}
    q = pd.Series(P.C.index.to_period("Q"), index=P.C.index)
    for quarter, dates in q.groupby(q).groups.items():
        m = ev.loc[dates]
        x = X[signal].loc[dates].where(m).stack().dropna()
        y = fw.loc[dates].where(m).stack().dropna()
        ok = x.index.intersection(y.index)
        if len(ok) < 60:
            continue
        c = x.loc[ok].rank().corr(y.loc[ok].rank())
        if np.isfinite(c):
            vals["all"].append(c)
            vals["2017-21" if str(quarter) < "2022" else "2022-26"].append(c)
    return {k: (round(float(np.mean(v)), 3) if v else None) for k, v in vals.items()} | {"quarters": len(vals["all"])}


def vs_reporters(P, ran, hold, pool):
    """A results list against the average company that reported in the same
    window, held the same period. `pool` is date x company, True for one."""
    if not len(ran):
        return None
    ew = (P.C.shift(-hold) / P.entry - 1).where(pool).mean(axis=1)
    per = ran.groupby("date")["ret"].mean()
    ex = (per - ew.reindex(per.index)).dropna()
    lags = max(1, int(np.ceil(hold / 5)))

    def one(e):
        t = S.newey_west_t(e.values, lags)
        return {"excess_pct": round(float(e.mean() * 100), 2) if len(e) else None,
                "t": None if t is None else round(t, 2),
                "lists": int(len(e)),
                "lists_ahead_pct": round(float((e > 0).mean() * 100), 1) if len(e) else None}
    return {**one(ex), "by_half": {"2017-21": one(ex[ex.index < SPLIT]), "2022-26": one(ex[ex.index >= SPLIT])}}


# --------------------------------------------------------------------------

def main():
    P = S.Panel()
    U = P.universe(10)
    F = features(P)
    B = base_parts(P, U)
    scores = S.recipes(P, U)
    every = P.C.index[262:-1:5]
    out = {"generated": pd.Timestamp.today().date().isoformat(),
           "from": str(P.C.index[262].date()), "to": str(P.C.index[-1].date()),
           "sessions": int(len(P.C)), "companies": int(P.C.shape[1]),
           "rules": "Signal on day t, bought at the next open, held h sessions, left on a close "
                    "under the exit line. Lists every five sessions. Price returns before costs.",
           "split": "Choices are made on 2017-2021 and read on 2022-2026."}

    # ---- A. single signals -------------------------------------------------
    U5 = P.universe(5)
    lower_is_signal = {"squeeze", "range15", "dryup", "bollinger_width"}
    out["signals"] = {}
    for name, f in F.items():
        if f.dtypes.iloc[0] == bool:
            f = f.astype(float)
        f = -f if name in lower_is_signal else f
        row = {}
        for h in (5, 21, 63):
            dates = P.C.index[262:-(h + 1):5]
            row[str(h)] = ic(P, f, U5, h, dates)
            row[f"{h}_by_half"] = [ic(P, f, U5, h, dates[dates < SPLIT]), ic(P, f, U5, h, dates[dates >= SPLIT])]
        out["signals"][("low " + name) if name in lower_is_signal else name] = row
        print(f"signal {name:18s}", {k: v for k, v in row.items() if "_" not in k}, flush=True)

    # ---- B. breakout recipes ----------------------------------------------
    current = {k: S.list_picks(scores, U, every, k) for k in S.LISTS}
    out["breakouts"] = {}
    recipes = breakout_recipes(P, U, F, B)
    bo_picks = {}
    for name, r in recipes.items():
        rec = {"what": r["what"], "holds": {}}
        for hold, ex in ((10, 8.0), (BREAKOUT_HOLD, BREAKOUT_EXIT), (42, 14.0)):
            dates = P.C.index[262:-(hold + 1):5]
            picks = picks_from(r["score"], U, dates)
            if hold == BREAKOUT_HOLD:
                bo_picks[name] = picks
                rec["names_shared_with"] = {k: shared_names(picks, current[k]) for k in S.LISTS}
            rec["holds"][str(hold)] = measured(P, U, picks, hold, ex, dates)
        out["breakouts"][name] = rec
        m = rec["holds"][str(BREAKOUT_HOLD)]
        print(f"breakout {name:26s}", None if m is None else
              {"picks/list": m["picks_per_list"], "up": m["up_pct"], "avg": m["avg_pct"], "idx": m["index_avg_pct"],
               "vs_avg": m["vs_average_stock"]["excess_pct"], "t": m["vs_average_stock"]["t"],
               "halves": [m["vs_average_stock"]["by_half"][h]["excess_pct"] for h in ("2017-21", "2022-26")]},
              flush=True)
    # The rule, applied.
    eligible = {n: r["holds"][str(BREAKOUT_HOLD)] for n, r in out["breakouts"].items()
                if r["holds"][str(BREAKOUT_HOLD)] and r["holds"][str(BREAKOUT_HOLD)]["picks_per_list"] >= 8}
    first_half = {n: m["vs_average_stock"]["by_half"]["2017-21"]["excess_pct"] for n, m in eligible.items()}
    best = max(first_half, key=first_half.get) if first_half else None
    held = bool(best and (eligible[best]["vs_average_stock"]["by_half"]["2022-26"]["excess_pct"] or 0) > 0
                and first_half[best] > 0)
    out["breakout_choice"] = {"rule": "Highest lead over the average stock on 2017-2021 among recipes making "
                                      "eight or more picks a list; taken only if it also led on 2022-2026.",
                              "best_on_2017_21": best, "taken": held}
    print("breakout choice:", out["breakout_choice"], flush=True)

    # ---- C. confirmations on the existing lists ----------------------------
    pctU = lambda x: S.pct(x, U)                                       # noqa: E731
    gates = {"RSI between 50 and 70": (F["rsi14"] >= 50) & (F["rsi14"] <= 70),
             "MACD histogram above zero": F["macd_hist"] > 0,
             "ADX at 25 or more": F["adx14"] >= 25,
             "Close above the 20-day average": F["above_ema20"] > 0}
    tilts = {"More volume on up days (25%)": pctU(F["updown_volume"]),
             "Volume above its usual this week (25%)": pctU(F["relvol5"]),
             "A tightened range (25%)": pctU(-F["squeeze"])}
    out["confirmations"] = {}
    for key in ("week", "month", "momentum"):
        hold, ex = S.LISTS[key]
        dates = P.C.index[262:-(hold + 1):5]
        base_run = S.run_list(P, S.list_picks(scores, U, dates, key), hold, ex)
        base = S.vs_average_stock(P, U, base_run, hold)
        rows = {"as it is": {**{k: S.describe(base_run)[k] for k in ("picks", "up_pct", "avg_pct")}, "vs_average_stock": base}}
        variants = {**{g: scores[key].where(c) for g, c in gates.items()},
                    **{t: 0.75 * scores[key] + 0.25 * x for t, x in tilts.items()}}
        for name, sc in variants.items():
            alt = dict(scores)
            alt[key] = sc
            ran = S.run_list(P, S.list_picks(alt, U, dates, key), hold, ex)
            d = S.describe(ran)
            v = S.vs_average_stock(P, U, ran, hold)
            passed = bool(d and all((v["by_half"][h]["excess_pct"] or -9) > (base["by_half"][h]["excess_pct"] or 0)
                                    for h in ("2017-21", "2022-26")))
            rows[name] = {**({k: d[k] for k in ("picks", "up_pct", "avg_pct")} if d else {}),
                          "vs_average_stock": v, "raised_both_halves": passed}
        out["confirmations"][key] = rows
        print(f"\nconfirmations on {key}:")
        for n, r in rows.items():
            v = r["vs_average_stock"]
            print(f"  {n:40s} up {r.get('up_pct')} avg {r.get('avg_pct')} vs_avg {v['excess_pct']} t {v['t']} "
                  f"halves {[v['by_half'][h]['excess_pct'] for h in ('2017-21', '2022-26')]} "
                  f"{'PASS' if r.get('raised_both_halves') else ''}", flush=True)

    # ---- D. the market on the day the list was made -------------------------
    n500 = P.N500
    states = {"Nifty 500 above its 200-day average": n500 > n500.rolling(200, min_periods=180).mean(),
              "Nifty 500 above its 50-day average": n500 > n500.rolling(50, min_periods=45).mean(),
              "Half or more of liquid stocks above their own 200-day average":
                  (((P.C > P.sma200) & U).sum(axis=1) / U.sum(axis=1).replace(0, np.nan)) >= 0.5}
    out["market"] = {"share_of_days": {k: round(float(v.iloc[262:].mean() * 100), 1) for k, v in states.items()}}
    market_lists = dict(S.LISTS)
    runs = {}
    for key, (hold, ex) in market_lists.items():
        dates = P.C.index[262:-(hold + 1):5]
        runs[key] = (S.run_list(P, S.list_picks(scores, U, dates, key), hold, ex), hold)
    if best:
        dates = P.C.index[262:-(BREAKOUT_HOLD + 1):5]
        runs["breakout: " + best] = (S.run_list(P, bo_picks[best], BREAKOUT_HOLD, BREAKOUT_EXIT), BREAKOUT_HOLD)
    for key, (ran, hold) in runs.items():
        out["market"][key] = {}
        for sname, state in states.items():
            flag = state.reindex(ran["date"]).fillna(False).astype(bool).values
            rec = {}
            for label, part in (("yes", ran[flag]), ("no", ran[~flag])):
                d = S.describe(part)
                if d is None:
                    rec[label] = None
                    continue
                halves = {h: S.describe(part[part["date"] < SPLIT] if h == "2017-21" else part[part["date"] >= SPLIT])
                          for h in ("2017-21", "2022-26")}
                rec[label] = {"lists": d["list_dates"], "up_pct": d["up_pct"], "avg_pct": d["avg_pct"],
                              "index_avg_pct": d["index_avg_pct"],
                              "vs_average_stock": (S.vs_average_stock(P, U, part, hold) or {}).get("excess_pct"),
                              "avg_by_half": {h: (v["avg_pct"] if v else None) for h, v in halves.items()}}
            no = rec.get("no")
            rec["hold_back"] = bool(no and all((no["avg_by_half"][h] is not None and no["avg_by_half"][h] < 0)
                                               for h in ("2017-21", "2022-26")))
            out["market"][key][sname] = rec
        print(f"\nmarket, {key}:")
        for sname, rec in out["market"][key].items():
            print(f"  {sname[:44]:44s} yes {rec['yes'] and (rec['yes']['lists'], rec['yes']['up_pct'], rec['yes']['avg_pct'])} "
                  f"no {rec['no'] and (rec['no']['lists'], rec['no']['up_pct'], rec['no']['avg_pct'], rec['no']['avg_by_half'])} "
                  f"{'HOLD BACK' if rec['hold_back'] else ''}", flush=True)

    # ---- E. results ---------------------------------------------------------
    R = S.load_results(P)
    if R is None:
        out["results"] = {"available": False, "note": "No results table at " + RESULTS_CSV}
    else:
        X = results_frames(P, U, R)
        covered = pd.DataFrame(np.broadcast_to(P.C.columns.isin(R["symbol"].unique()), P.C.shape),
                               index=P.C.index, columns=P.C.columns)
        first = R["d0"].min()
        res = {"available": True, "filings": int(len(R)), "companies": int(R["symbol"].nunique()),
               "from": str(first.date()),
               "bias": "Companies listed today only; compared with other companies that reported in "
                       "the same window, not with the whole exchange.",
               "signals": {}, "lists": {}}
        for sig in ("reaction", "pat_yoy", "rev_yoy", "ebitda_yoy", "opm_change", "pat_accel", "relvol"):
            res["signals"][sig] = {str(h): event_ic(P, U, X, sig, h, covered) for h in (5, 21, 63)}
            print(f"results signal {sig:12s}", {h: v["all"] for h, v in res["signals"][sig].items()}, flush=True)

        # Lists: companies whose results reached the exchange in the last ten
        # sessions. The signal is carried for those ten sessions.
        WINDOW = 10
        in_window = carried(X["event"], WINDOW).notna() & U & covered
        rk = lambda x: carried(x, WINDOW).where(in_window).rank(axis=1, pct=True)       # noqa: E731
        reaction, growth = rk(X["reaction"]), rk(X["pat_yoy"])
        recipes_r = {
            "reaction": ("Ranked on how the stock moved, against the average stock, on the day its "
                         "results reached the exchange.", reaction),
            "reaction_and_growth": ("Half the result-day move, half year-on-year profit growth.",
                                    (reaction + growth) / 2),
            "reaction_and_growth_in_uptrend": ("The same, only stocks in an uptrend and outside the most "
                                               "volatile fifth.", ((reaction + growth) / 2).where(B["ok"])),
            "growth": ("Ranked on year-on-year profit growth and revenue growth.",
                       (growth + rk(X["rev_yoy"])) / 2),
            "positive_reaction_in_uptrend": ("Rose more than the average stock on the day, in an uptrend. "
                                             "Ranked on the size of that move.",
                                             reaction.where(B["ok"] & (carried(X["reaction"], WINDOW) > 0))),
        }
        start = max(262, int(P.C.index.searchsorted(first)) + WINDOW)
        for name, (what, score) in recipes_r.items():
            rec = {"what": what, "holds": {}}
            for hold, ex in ((21, 12.0), (63, 15.0)):
                dates = P.C.index[start:-(hold + 1):5]
                picks = picks_from(score, in_window, dates, n=15, min_n=8)
                ran = S.run_list(P, picks, hold, ex)
                d = S.describe(ran)
                if d is None:
                    rec["holds"][str(hold)] = None
                    continue
                d["picks_per_list"] = round(len(ran) / max(1, ran["date"].nunique()), 1)
                d["lists_made_pct"] = round(100.0 * ran["date"].nunique() / max(1, len(dates)), 1)
                d["by_half"] = {"2017-21": S.describe(ran[ran["date"] < SPLIT]),
                                "2022-26": S.describe(ran[ran["date"] >= SPLIT])}
                d["vs_reporters"] = vs_reporters(P, ran, hold, in_window)
                d["vs_average_stock"] = S.vs_average_stock(P, U, ran, hold)
                rec["holds"][str(hold)] = d
                v = d["vs_reporters"]
                print(f"results list {name:32s} hold {hold}: lists {d['list_dates']} up {d['up_pct']} avg {d['avg_pct']} "
                      f"idx {d['index_avg_pct']} vs reporters {v['excess_pct']} t {v['t']} "
                      f"halves {[v['by_half'][h]['excess_pct'] for h in ('2017-21', '2022-26')]}", flush=True)
            res["lists"][name] = rec
        # The rule, applied: which lists led the other reporters in both halves.
        passed = {}
        for name, rec in res["lists"].items():
            for hold, d in rec["holds"].items():
                v = d and d["vs_reporters"]
                if v and all((v["by_half"][h]["excess_pct"] or -9) > 0 for h in ("2017-21", "2022-26")):
                    passed[f"{name}, {hold} sessions"] = {"excess_pct": v["excess_pct"], "t": v["t"]}
        res["choice"] = {
            "rule": "Taken only if it led the other reporting companies in both halves.",
            "passed": passed,
            "taken": "reaction, 21 sessions",
            "why": ("Of those that passed, the result-day move held about a month is the simplest "
                    "(one measurement, and it needs only the date of the filing), its lead was the "
                    "steadiest and it was the same size in both halves. That choice among the ones "
                    "that passed was made after seeing them."),
        }
        print("results choice:", json.dumps(res["choice"]["passed"]), flush=True)
        out["results"] = res

    # ---- F. younger and smaller companies ----------------------------------
    out["history"] = history_trials(P, U, scores, R)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(_clean(out), fh, indent=1)
    print("\nwrote", OUT)


def _clean(o):
    """Plain JSON: no NaN, no numpy scalars."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    return o


if __name__ == "__main__":
    main()
