"""
The Ideas study: what picked well on NSE from 2017 to 2026, and what did not.

    python research/ideas_study.py --fetch      # NSE daily files, ~2,700 of them (slow, once)
    python research/ideas_study.py --build      # adjusted price panel
    python research/ideas_study.py --baseline   # replay the OLD ranking (slow: ~30 min on 4 cores)
    python research/ideas_study.py --study      # every table, and research/ideas-study.json

Everything the Ideas page prints about its own record comes out of --study.
backend/leaders.py reads the JSON; it holds no number of its own.

DATA
The exchange's own daily bhavcopy, one file per session, read from
archives.nseindia.com. It lists every security that traded that day, so a
company that was later delisted is in the test for as long as it traded. A
list of today's survivors would flatter every method tested on it.

Only company shares are kept (ISIN beginning INE). The same files carry
exchange-traded funds, which are not what the lists are for and which a
risk-adjusted ranking would put first.

The bhavcopy is unadjusted and its PREVCLOSE is the raw previous close (ITC's
1:2 bonus on 1 Jul 2016 prints 252.35 against 368.40). Every NSE stock outside
F&O has a price band of at most 20%, so a session that OPENS more than 21%
away from the previous close is a corporate action, not a move. That gap is
removed; gaps within 5% of a simple split or bonus ratio are snapped to it.
Dividends are not adjusted for: every figure is a price return and the
benchmark is the Nifty 500 price index, which is not adjusted for them either.

RULES OF THE TEST
A signal on day t uses bars up to and including t. The pick is bought at the
OPEN of t+1 and held h sessions; an exit line is read on the close. Lists are
formed every five sessions. No costs, no tax: both are the reader's and both
matter most on the one-week list.

Recipes were chosen on 2017-2021 and then checked on 2022-2026.
"""

import argparse
import datetime as dt
import glob
import json
import os
import pickle
import sys
import time
import urllib.request
import warnings
import zipfile

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("IDEAS_DATA", "").strip() or os.path.join(HERE, ".ideas-data")
OUT = os.path.join(HERE, "ideas-study.json")
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

START = dt.date(2016, 1, 1)
NEW_FORMAT_FROM = dt.date(2024, 7, 8)
SPLIT = "2022-01-01"                         # chosen before, checked after
FRACS = sorted({a / b for b in range(1, 21) for a in range(1, b + 1)}
               | {1 / 25, 1 / 50, 1 / 100, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0, 20.0})


# --------------------------------------------------------------------------
# 1. Fetch
# --------------------------------------------------------------------------

def _get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "altaha-research/1.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read()
        with open(path + ".part", "wb") as f:
            f.write(body)
        os.replace(path + ".part", path)
        return True
    except Exception:
        return False                         # a holiday, or a day the archive lacks


def fetch():
    os.makedirs(os.path.join(DATA, "bhav"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "idx"), exist_ok=True)
    day, got = START, 0
    while day <= dt.date.today():
        if day.weekday() < 5:
            tag = day.strftime("%Y%m%d")
            if day < NEW_FORMAT_FROM:
                url = ("https://archives.nseindia.com/content/historical/EQUITIES/"
                       f"{day.year}/{day.strftime('%b').upper()}/cm{day.strftime('%d%b%Y').upper()}bhav.csv.zip")
            else:
                url = f"https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{tag}_F_0000.csv.zip"
            got += _get(url, os.path.join(DATA, "bhav", tag + ".zip"))
            _get(f"https://archives.nseindia.com/content/indices/ind_close_all_{day.strftime('%d%m%Y')}.csv",
                 os.path.join(DATA, "idx", tag + ".csv"))
            time.sleep(0.15)                 # one reader, politely
        day += dt.timedelta(days=1)
    print("sessions on disk:", got)


# --------------------------------------------------------------------------
# 2. Build the adjusted panel
# --------------------------------------------------------------------------

def _read_day(path):
    try:
        z = zipfile.ZipFile(path)
        df = pd.read_csv(z.open(z.namelist()[0]))
    except Exception:
        return None
    if "TckrSymb" in df.columns:
        df = df[(df["Sgmt"] == "CM") & df["SctySrs"].isin(["EQ", "BE", "BZ"])]
        out = pd.DataFrame({"sym": df["TckrSymb"].astype(str).str.strip(), "ser": df["SctySrs"],
                            "isin": df["ISIN"], "o": df["OpnPric"], "h": df["HghPric"],
                            "l": df["LwPric"], "c": df["ClsPric"], "pc": df["PrvsClsgPric"],
                            "v": df["TtlTradgVol"], "val": df["TtlTrfVal"]})
    else:
        df.columns = [c.strip() for c in df.columns]
        df = df[df["SERIES"].isin(["EQ", "BE", "BZ"])]
        out = pd.DataFrame({"sym": df["SYMBOL"].astype(str).str.strip(), "ser": df["SERIES"],
                            "isin": df["ISIN"], "o": df["OPEN"], "h": df["HIGH"], "l": df["LOW"],
                            "c": df["CLOSE"], "pc": df["PREVCLOSE"], "v": df["TOTTRDQTY"],
                            "val": df["TOTTRDVAL"]})
    # Company shares only. The bhavcopy's EQ series also carries exchange-traded
    # funds, and a liquid-fund ETF (a cash fund that creeps up in a straight
    # line at 1% volatility) ranks first on every momentum-for-its-risk measure
    # there is. Mutual-fund units carry an INF ISIN; a company's is INE.
    out = out[out["isin"].astype(str).str.startswith("INE")]
    if not len(out):
        return None
    out = out.sort_values("ser").drop_duplicates("sym", keep="last")
    out["date"] = pd.Timestamp(os.path.basename(path)[:8])
    return out


class _Union:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build():
    files = sorted(glob.glob(os.path.join(DATA, "bhav", "*.zip")))
    days = [d for d in (_read_day(f) for f in files) if d is not None]
    rows = pd.concat(days, ignore_index=True)
    del days
    # One company, whatever it was called: a rename keeps the ISIN, a split
    # keeps the symbol, so linking both follows it through either.
    uf = _Union()
    for s, i in rows[["sym", "isin"]].drop_duplicates().itertuples(index=False):
        uf.union("S:" + s, "I:" + str(i))
    rows["ent"] = [uf.find("S:" + s) for s in rows["sym"]]
    rows["name"] = rows["ent"].map(rows.sort_values("date").groupby("ent")["sym"].last())
    rows = rows.sort_values(["date", "name", "val"]).drop_duplicates(["date", "name"], keep="last")
    dates, names = np.sort(rows["date"].unique()), np.sort(rows["name"].unique())

    def piv(col):
        return rows.pivot(index="date", columns="name", values=col).reindex(index=dates, columns=names).astype("float64")
    O, H, L, C, PC, V, VAL = (piv(c) for c in ["o", "h", "l", "c", "pc", "v", "val"])
    gap = (O / PC).where((PC >= 5) & (O > 0))
    ca = (gap < 0.79) | (gap > 1.27)
    fr, factor, events = np.array(FRACS), pd.DataFrame(1.0, index=dates, columns=names), []
    for name in names[ca.any(axis=0).values]:
        for d in gap.index[ca[name].values]:
            g = float(gap.at[d, name])
            j = int(np.argmin(np.abs(np.log(fr / g))))
            f = float(fr[j]) if abs(fr[j] / g - 1) <= 0.05 else g
            factor.at[d, name] = f
            events.append((str(pd.Timestamp(d).date()), name, round(g, 4), round(f, 4)))
    pd.DataFrame(events, columns=["date", "name", "gap", "factor"]).to_csv(
        os.path.join(DATA, "corporate_actions.csv"), index=False)
    logf = np.log(factor.values)
    adj = pd.DataFrame(np.exp(np.cumsum(logf[::-1], axis=0)[::-1] - logf), index=dates, columns=names)
    panel = {"open": (O * adj).astype("float32"), "high": (H * adj).astype("float32"),
             "low": (L * adj).astype("float32"), "close": (C * adj).astype("float32"),
             "volume": (V / adj).astype("float32"), "value": VAL.astype("float32"),
             "raw_close": C.astype("float32")}
    with open(os.path.join(DATA, "panel.pkl"), "wb") as f:
        pickle.dump(panel, f, protocol=4)

    idx = []
    for f in sorted(glob.glob(os.path.join(DATA, "idx", "*.csv"))):
        try:
            df = pd.read_csv(f)
        except Exception:
            continue
        df.columns = [c.strip() for c in df.columns]
        df["date"] = pd.Timestamp(os.path.basename(f)[:8])
        idx.append(df[["Index Name", "date", "Closing Index Value"]])
    x = pd.concat(idx)
    x["Index Name"] = x["Index Name"].str.strip().str.upper().replace({"CNX NIFTY": "NIFTY 50", "CNX 500": "NIFTY 500"})
    x["Closing Index Value"] = pd.to_numeric(x["Closing Index Value"], errors="coerce")
    x.pivot_table(index="date", columns="Index Name", values="Closing Index Value",
                  aggfunc="last").to_pickle(os.path.join(DATA, "index.pkl"))
    print(f"panel {C.shape[0]} sessions x {C.shape[1]} companies · {len(events)} corporate actions removed")


# --------------------------------------------------------------------------
# 3. Signals, vectorised. The same definitions as backend/leaders.py, which
#    parity() below proves by running that module on the same dates.
# --------------------------------------------------------------------------

class Panel:
    def __init__(self):
        p = pickle.load(open(os.path.join(DATA, "panel.pkl"), "rb"))
        C = p["close"].astype("float64")
        self.traded = C.notna()
        self.C = C.ffill(limit=10)           # a missed session is not a missing company
        self.O = p["open"].astype("float64").fillna(self.C)
        self.H = p["high"].astype("float64").fillna(self.C)
        self.L = p["low"].astype("float64").fillna(self.C)
        self.V = p["volume"].astype("float64").fillna(0)
        self.VAL = p["value"].astype("float64").fillna(0)
        self.RAW = p["raw_close"].astype("float64").ffill(limit=10)
        idx = pd.read_pickle(os.path.join(DATA, "index.pkl")).reindex(self.C.index).ffill()
        self.N500 = idx["NIFTY 500"]
        C = self.C
        lr = np.log(C / C.shift(1))
        self.turn60 = self.VAL.rolling(60, min_periods=40).median()
        self.turn_mean60 = self.VAL.rolling(60, min_periods=40).mean()
        self.hist = self.traded.rolling(260, min_periods=1).sum()
        self.mom_12_1 = C.shift(21) / C.shift(252) - 1
        self.mom_6_1 = C.shift(21) / C.shift(126) - 1
        self.ret_5 = C / C.shift(5) - 1
        self.vol_252 = lr.rolling(252, min_periods=200).std() * np.sqrt(252)
        self.vol_60 = lr.rolling(60, min_periods=50).std() * np.sqrt(252)
        self.sma50 = C.rolling(50, min_periods=45).mean()
        self.sma200 = C.rolling(200, min_periods=180).mean()
        self.near_high = C / self.H.rolling(252, min_periods=200).max()
        t = pd.Series(np.arange(len(C), dtype=float), index=C.index)
        r = np.log(C).rolling(90, min_periods=90).corr(t)
        self.trend_q = (r ** 2) * np.sign(r) * 100
        turn = C * self.V
        self.vol_shock = np.log(turn.rolling(5).mean()
                                / turn.shift(5).rolling(60, min_periods=40).median().replace(0, np.nan)) * 100
        self.entry = self.O.shift(-1)

    def fwd(self, h):
        return self.C.shift(-h) / self.entry - 1

    def bench(self, h):
        return self.N500.shift(-h) / self.N500 - 1

    def universe(self, min_cr=10, min_price=20):
        # vol_252 >= 8%: the engine's own guard against a cash fund that slips
        # into a symbol list (leaders.MIN_VOLATILITY). No company share is that still.
        # Every signal measurable, as leaders.in_universe requires: a company
        # listed for under a year has no 12-month return and is not compared.
        whole = (self.mom_12_1.notna() & self.mom_6_1.notna() & self.near_high.notna()
                 & self.trend_q.notna() & self.ret_5.notna() & (self.vol_252 >= 0.08))
        return (self.turn60 >= min_cr * 1e7) & (self.RAW >= min_price) & (self.hist >= 240) & whole


def pct(f, U):
    return f.where(U).rank(axis=1, pct=True)


def recipes(P, U):
    """The four lists, exactly as backend/leaders.py mixes them."""
    m12, m6 = pct(P.mom_12_1 / P.vol_252, U), pct(P.mom_6_1 / P.vol_252, U)
    high, trend = pct(P.near_high, U), pct(P.trend_q, U)
    calm, dip = pct(-P.vol_252, U), pct(-P.ret_5, U)
    leader = (m12 + m6 + high + trend) / 4
    up = (P.C > P.sma200) & (P.sma50 > P.sma200)
    ok = up & (calm >= 0.20)
    return {"week": (0.5 * leader + 0.5 * dip).where(ok),
            "month": (0.75 * leader + 0.25 * dip).where(ok),
            "momentum": leader.where(ok),
            "long": ((m12 + high + trend) / 3).where(ok)}


def top_picks(score, U, dates, n=15):
    out = []
    for d in dates:
        s = score.loc[d].where(U.loc[d]).dropna()
        if len(s) >= n:
            out.append((d, list(s.nlargest(n).index)))
    return out


def run_list(P, picks, hold, exit_pct=None, on_low=False):
    """
    Hold each pick `hold` sessions from the next open. With `exit_pct`, leave
    at the first close that far under the entry (or, for the old method's
    stop, the first LOW through it, filled at the stop or a lower open).
    """
    Cn, On, Ln = P.C.values, P.O.values, P.L.values
    col = {n: i for i, n in enumerate(P.C.columns)}
    row = {d: i for i, d in enumerate(P.C.index)}
    recs = []
    for d, names in picks:
        i = row[d]
        last = i + hold
        if last >= len(Cn):
            continue
        b = P.N500.iloc[last] / P.N500.iloc[i] - 1
        for n in names:
            j = col[n]
            e = On[i + 1, j]
            if not np.isfinite(e) or e <= 0:
                continue
            ret, out_early = None, False
            if exit_pct:
                line = e * (1 - exit_pct / 100.0)
                for k in range(i + 1, last + 1):
                    c = Cn[k, j]
                    if not np.isfinite(c):
                        continue
                    if on_low and Ln[k, j] <= line:
                        ret = (min(On[k, j], line) if k > i + 1 else line) / e - 1
                        out_early = True
                        break
                    if not on_low and c <= line:
                        ret, out_early = c / e - 1, True
                        break
            if ret is None:
                c = Cn[last, j]
                if not np.isfinite(c):
                    continue
                ret = c / e - 1
            recs.append((d, n, ret, b, out_early))
    return pd.DataFrame(recs, columns=["date", "name", "ret", "bench", "exited"])


def describe(df):
    if not len(df):
        return None
    per_date = df.groupby("date").agg(ret=("ret", "mean"), bench=("bench", "first"))
    return {
        "list_dates": int(per_date.shape[0]),
        "picks": int(len(df)),
        "up_pct": round(float((df["ret"] > 0).mean() * 100), 1),
        "beat_index_pct": round(float((df["ret"] > df["bench"]).mean() * 100), 1),
        "avg_pct": round(float(df["ret"].mean() * 100), 2),
        "median_pct": round(float(df["ret"].median() * 100), 2),
        "index_avg_pct": round(float(per_date["bench"].mean() * 100), 2),
        "worst_5pct": round(float(np.percentile(df["ret"], 5) * 100), 1),
        "best_5pct": round(float(np.percentile(df["ret"], 95) * 100), 1),
        "exit_hit_pct": round(float(df["exited"].mean() * 100), 1),
        "lists_ahead_of_index_pct": round(float((per_date["ret"] > per_date["bench"]).mean() * 100), 1),
    }


def with_breakdowns(df):
    out = describe(df)
    if out is None:
        return None
    out["by_half"] = {"2017-21": describe(df[df["date"] < SPLIT]), "2022-26": describe(df[df["date"] >= SPLIT])}
    out["by_year"] = {}
    for y, g in df.groupby(df["date"].dt.year):
        d = describe(g)
        out["by_year"][str(y)] = {k: d[k] for k in ("avg_pct", "index_avg_pct", "up_pct", "picks")}
    return out


def ic(P, f, U, h, dates):
    fw, vals = P.fwd(h), []
    for d in dates:
        x, y = f.loc[d].where(U.loc[d]), fw.loc[d]
        ok = x.notna() & y.notna()
        if ok.sum() >= 50:
            vals.append(x[ok].rank().corr(y[ok].rank()))
    return round(float(np.mean(vals)), 3) if vals else None


# --------------------------------------------------------------------------
# 4. The previous method, replayed
# --------------------------------------------------------------------------

def baseline(step=10, procs=4):
    """engine.technical_score on a one-year frame cut at each date: the old phase 1."""
    from multiprocessing import Pool
    global _BP
    _BP = Panel()
    idxs = list(range(262, len(_BP.C) - 1, step))
    t0, res = time.time(), []
    with Pool(procs) as pool:
        for k, r in enumerate(pool.imap_unordered(_baseline_date, idxs, chunksize=2)):
            res.extend(r)
            if k % 20 == 0:
                print(k, "/", len(idxs), round(time.time() - t0), "s", flush=True)
    pd.DataFrame(res, columns=["date", "name", "tech", "setup"]).to_pickle(os.path.join(DATA, "baseline.pkl"))


def _baseline_date(i):
    from engine import technical_score
    import archetypes as A
    P, out = _BP, []
    ok = (P.turn_mean60.iloc[i] >= 5e6) & (P.traded.rolling(250, min_periods=1).sum().iloc[i] >= 120) \
        & (P.C.iloc[i] > P.sma50.iloc[i])     # nothing under its 50-day average reaches the top 150
    sl = slice(i - 249, i + 1)
    for n in P.C.columns[ok.values]:
        df = pd.DataFrame({"Open": P.O[n].values[sl], "High": P.H[n].values[sl], "Low": P.L[n].values[sl],
                           "Close": P.C[n].values[sl], "Volume": P.V[n].values[sl]},
                          index=P.C.index[sl]).dropna(subset=["Close"])
        if len(df) < 120:
            continue
        try:
            t = technical_score(df)
            out.append((P.C.index[i], n, float(t["score"]), (A.evaluate(t, {"checks": []}) or {}).get("key")))
        except Exception:
            continue
    return out


def old_picks(P, base):
    """
    The old short-term list, as closely as prices alone allow: the 150 highest
    technical scores on the exchange, kept if the chart reads as a momentum or
    accumulation setup and a day trades Rs 2 crore, ordered by the price part
    of the old trade score ranked inside that cohort.
    """
    out = []
    base = base[base["name"].isin(P.C.columns)]          # company shares only
    for d, g in base.groupby("date"):
        pool = g.nlargest(150, "tech")
        pool = pool[pool["setup"].isin(["momentum_breakout", "institutional_accumulation"])]
        names = [n for n in pool["name"] if P.turn_mean60.at[d, n] >= 2e7]
        if len(names) < 15:
            continue
        cohort = list(g.nlargest(150, "tech")["name"])

        def r(series, sign=1.0):
            return (sign * series.loc[d, cohort]).rank(pct=True)
        score = (0.30 * (0.65 * r(P.ret_5, -1) + 0.35 * r(P.vol_60, -1))
                 + 0.20 * (r(P.mom_12_1) + r(P.trend_q)) / 2 + 0.20 * r(P.vol_shock))
        out.append((d, list(score.reindex(names).dropna().nlargest(15).index)))
    return out


# --------------------------------------------------------------------------
# 5. The study
# --------------------------------------------------------------------------

LISTS = {"week": (5, 7.0), "month": (21, 12.0), "momentum": (63, 15.0), "long": (252, 30.0)}


def parity(P, U, scores):
    """backend/leaders.py must pick what this file picked, or the page is
    printing the record of a recipe the site does not run."""
    import leaders
    same = total = 0
    for i in (400, 900, 1400, 1900, 2300, 2600):
        if i >= len(P.C):
            continue
        d, cands = P.C.index[i], []
        sl = slice(i - 299, i + 1)
        # The scan's symbol list on that date: anything trading Rs 3 crore that
        # had not missed more than twenty of the last 260 sessions (the engine
        # reads that off the dates of a real feed; this panel has no gaps).
        listed = (P.turn60.iloc[i] >= 3e7) & (P.hist.iloc[i] >= 240)
        for n in P.C.columns[listed.values]:
            # Prices as a feed showed them THAT day: adjusted for every split
            # up to it and none after, so the last close is the traded price.
            k = P.RAW.iat[i, P.C.columns.get_loc(n)] / P.C.iat[i, P.C.columns.get_loc(n)]
            df = pd.DataFrame({"High": P.H[n].values[sl] * k, "Close": P.C[n].values[sl] * k},
                              index=P.C.index[sl])
            df["Volume"] = P.VAL[n].values[sl] / df["Close"]
            cands.append({"symbol": n, "leader_sig": leaders.signals(df)})
        blocks = leaders.rank(cands)
        for key, sc in scores.items():
            want = set(sc.loc[d].where(U.loc[d]).dropna().nlargest(15).index)
            got = {s for s, b in blocks.items() if (b["lists"][key]["rank"] or 99) <= 15}
            same += len(want & got)
            total += 15
    return same, total


def study():
    P = Panel()
    U = P.universe(10)
    scores = recipes(P, U)
    same, total = parity(P, U, scores)
    print(f"engine parity: {same} of {total} picks identical")
    assert same == total, "backend/leaders.py no longer matches the tested recipes"

    result = {
        "generated": dt.date.today().isoformat(),
        "source": "NSE daily bhavcopy, every session, delisted companies included",
        "from": str(P.C.index[262].date()), "to": str(P.C.index[-1].date()),
        "sessions": int(len(P.C)), "companies": int(P.C.shape[1]),
        "universe": "NSE stocks trading Rs 10 crore a day or more, priced Rs 20 or more",
        "universe_median": int(U.iloc[262:].sum(axis=1).median()),
        "rules": "Bought at the next session's open, held for the period, left on a close "
                 "under the exit line. Price returns before costs and tax. Index: Nifty 500.",
        "engine_parity": f"{same}/{total}",
        "lists": {}, "exits": {}, "before": {}, "score": {}, "factors": {},
    }

    for key, (hold, exit_pct) in LISTS.items():
        dates = P.C.index[262:-(hold + 1):5]
        picks = top_picks(scores[key], U, dates)
        rec = with_breakdowns(run_list(P, picks, hold, exit_pct))
        rec.update(hold_sessions=hold, exit_pct=exit_pct)
        result["lists"][key] = rec
        result["exits"][key] = {"no exit line": describe(run_list(P, picks, hold))}
        for alt in sorted({exit_pct / 2, exit_pct, exit_pct * 1.5}):
            result["exits"][key][f"close {alt:g}% under"] = describe(run_list(P, picks, hold, alt))
        print(f"\n{key}: hold {hold}, exit {exit_pct}%")
        print(json.dumps({k: v for k, v in rec.items() if k not in ("by_year",)}, indent=1))

    # What a random pick did: the bar every list has to clear.
    rng = np.random.default_rng(7)
    rnd = pd.DataFrame(rng.random(P.C.shape), index=P.C.index, columns=P.C.columns)
    result["random"] = {key: describe(run_list(P, top_picks(rnd, U, P.C.index[262:-(h + 1):5]), h))
                        for key, (h, _e) in LISTS.items()}

    # The old method, where its replay exists.
    bpath = os.path.join(DATA, "baseline.pkl")
    if os.path.exists(bpath):
        op = old_picks(P, pd.read_pickle(bpath))
        result["before"] = {
            "what": "The 150 highest technical scores on the exchange, momentum and accumulation "
                    "setups, Rs 2 crore a day, ordered by the old trade score. Its targets cannot "
                    "be replayed from prices, so it is shown WITHOUT them, which flatters it.",
            "list_dates": len(op),
            "held_42_sessions_stop_8pct": describe(run_list(P, op, 42, 8.0, on_low=True)),
            "held_42_sessions_no_stop": describe(run_list(P, op, 42)),
            "held_63_sessions_no_stop": describe(run_list(P, op, 63)),
            "new_momentum_list_same_dates_stop_8pct": describe(run_list(
                P, top_picks(scores["momentum"], U, [d for d, _ in op]), 42, 8.0, on_low=True)),
        }
        print("\nbefore:", json.dumps(result["before"], indent=1))

    # The price part of the score, before and after the re-weighting.
    U5 = P.universe(5)
    rev, lv = pct(-P.ret_5, U5), pct(-P.vol_60, U5)
    trend = (pct(P.mom_12_1, U5) + pct(P.trend_q, U5)) / 2
    vs, nh = pct(P.vol_shock, U5), pct(P.near_high, U5)
    mom = (trend + nh) / 2
    parts = {
        "trade": (21, .30 * (.65 * rev + .35 * lv) + .20 * trend + .20 * vs,
                  .35 * (.25 * rev + .75 * lv) + .30 * mom + .05 * vs),
        "position": (63, .05 * (.2 * rev + .8 * lv) + .15 * trend + .05 * vs, .05 * lv + .20 * mom),
        "invest": (252, .05 * lv + .08 * trend + .02 * vs, .05 * lv + .10 * mom),
    }
    for hz, (h, old, new) in parts.items():
        dates = P.C.index[262:-(h + 1):5]
        early, late = dates[dates < SPLIT], dates[dates >= SPLIT]
        result["score"][hz] = {
            "sessions_ahead": h,
            "rank_correlation_before": ic(P, old, U5, h, dates), "rank_correlation_after": ic(P, new, U5, h, dates),
            "before_by_half": [ic(P, old, U5, h, early), ic(P, old, U5, h, late)],
            "after_by_half": [ic(P, new, U5, h, early), ic(P, new, U5, h, late)],
        }
    print("\nscore:", json.dumps(result["score"], indent=1))

    singles = {"12-month return, last month skipped": P.mom_12_1, "closeness to the 52-week high": P.near_high,
               "low volatility": -P.vol_252, "straightness of the trend": P.trend_q,
               "one-week reversal": -P.ret_5, "turnover against its own history": P.vol_shock}
    for name, f in singles.items():
        result["factors"][name] = {str(h): ic(P, f, U5, h, P.C.index[262:-(h + 1):5]) for h in (5, 21, 63, 126)}
    print("\nfactors:", json.dumps(result["factors"], indent=1))

    # Two copies, identical: this one for the reader, and one beside the code
    # that prints it, because the API is deployed from backend/ alone.
    for path in (OUT, os.path.join(HERE, "..", "backend", "ideas_study.json")):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in ("fetch", "build", "baseline", "study"):
        ap.add_argument("--" + flag, action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    if a.build:
        build()
    if a.baseline:
        baseline()
    if a.study:
        study()
    if not (a.fetch or a.build or a.baseline or a.study):
        ap.print_help()
