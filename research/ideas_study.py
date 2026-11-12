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

THE RESULTS LIST'S OWN DATA
The fifth list ranks companies on how their stock moved the day their
quarterly results were priced, so it needs to know when each result reached
the exchange. That is the site's own fundamentals table (every Regulation 33
filing read from NSE, with its timestamp), downloaded by --fetch from
/fundamentals/table into income_quarterly.csv. It holds companies listed
TODAY, so one delisted after a bad quarter is missing; the list is therefore
compared with the other companies that had just reported, as well as with the
whole exchange. Without the file --study keeps the record it last wrote.

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
RESULTS_CSV = os.environ.get("IDEAS_RESULTS_CSV", "").strip() or os.path.join(DATA, "income_quarterly.csv")
RESULTS_URL = ("https://taha-project.onrender.com/fundamentals/table"
               "?table=income&freq=quarterly&format=csv")
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
    ok = _get(RESULTS_URL, RESULTS_CSV)
    print("quarterly results table:", "on disk" if ok else "could not be downloaded")


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
        self.ret_21 = C / C.shift(21) - 1
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


def recipes(P, U, shared=False):
    """
    The four lists, exactly as backend/leaders.py mixes them.

    shared=True gives the first version (November 2026, before "one stock, one
    list"): this month was three parts leader score and one part five-day dip,
    and nothing gave way. Kept so the cost of separating the lists is measured
    against what they replaced.
    """
    m12, m6 = pct(P.mom_12_1 / P.vol_252, U), pct(P.mom_6_1 / P.vol_252, U)
    high, trend = pct(P.near_high, U), pct(P.trend_q, U)
    calm, dip = pct(-P.vol_252, U), pct(-P.ret_5, U)
    dip21 = pct(-P.ret_21, U)
    leader = (m12 + m6 + high + trend) / 4
    up = (P.C > P.sma200) & (P.sma50 > P.sma200)
    ok = up & (calm >= 0.20)
    month = ((0.75 * leader + 0.25 * dip).where(ok) if shared
             else (0.5 * dip21 + 0.5 * high).where(ok & (leader >= 0.70)))
    return {"week": (0.5 * leader + 0.5 * dip).where(ok),
            "month": month,
            "momentum": leader.where(ok),
            "long": ((m12 + high + trend) / 3).where(ok)}


# Companies listed six to twelve months, as leaders.MIN_YOUNG_SESSIONS and
# leaders.YOUNG_LISTS: admitted to the week and momentum lists, placed against
# the established universe so that no established stock's score changes.
YOUNG_MIN, YOUNG_LISTS = 127, ("week", "momentum")


def young_universe(P, U):
    """(mask, measures) for liquid companies with 127 to 252 sessions since
    their first trade. Volatility, the 52-week high and the 200-day average
    are taken over the history there is."""
    C = P.C
    age = (P.traded.cumsum() > 0).cumsum()            # sessions since the first trade, that one included
    lr = np.log(C / C.shift(1))
    vol = lr.rolling(252, min_periods=100).std() * np.sqrt(252)
    near = C / P.H.rolling(252, min_periods=100).max()
    sma200 = C.rolling(200, min_periods=100).mean()
    whole = P.mom_6_1.notna() & near.notna() & P.trend_q.notna() & P.ret_5.notna() & (vol >= 0.08)
    Y = (P.turn60 >= 10e7) & (P.RAW >= 20) & (age >= YOUNG_MIN) & (age < 253) & whole & ~U
    return Y, {"vol": vol, "near": near, "sma200": sma200}


def add_young(P, U, scores):
    """
    The week and momentum scores with the young companies placed in them.

    A young company's percentile on each measure is the share of the
    ESTABLISHED universe at or below its figure, its 6-month return-for-risk
    standing in for the 12-month one. Returns (scores, the universe to pick
    from, the young mask).
    """
    Y, m = young_universe(P, U)
    Uv, Yv = U.values, Y.values
    va_y = (P.mom_6_1 / m["vol"]).values
    seasoned = {"m12": (P.mom_12_1 / P.vol_252).values, "m6": (P.mom_6_1 / P.vol_252).values,
                "high": P.near_high.values, "trend": P.trend_q.values,
                "calm": (-P.vol_252).values, "dip": (-P.ret_5).values}
    theirs = {"m12": va_y, "m6": va_y, "high": m["near"].values, "trend": P.trend_q.values,
              "calm": (-m["vol"]).values, "dip": (-P.ret_5).values}
    Cv, s50, s200 = P.C.values, P.sma50.values, m["sma200"].values
    week, mom = scores["week"].values.copy(), scores["momentum"].values.copy()
    for i in range(262, len(Cv)):
        ys, us = np.flatnonzero(Yv[i]), np.flatnonzero(Uv[i])
        if not len(ys) or len(us) < 30:
            continue
        p = {k: np.maximum(1, np.searchsorted(np.sort(seasoned[k][i, us]), theirs[k][i, ys], side="right"))
             / len(us) for k in seasoned}
        leader = (p["m12"] + p["m6"] + p["high"] + p["trend"]) / 4
        ok = (Cv[i, ys] > s200[i, ys]) & (s50[i, ys] > s200[i, ys]) & (p["calm"] >= 0.20)
        week[i, ys] = np.where(ok, 0.5 * leader + 0.5 * p["dip"], np.nan)
        mom[i, ys] = np.where(ok, leader, np.nan)
    out = dict(scores)
    out["week"] = pd.DataFrame(week, index=P.C.index, columns=P.C.columns)
    out["momentum"] = pd.DataFrame(mom, index=P.C.index, columns=P.C.columns)
    return out, (U | Y), Y


def young_only(df, Y):
    """The rows of a run whose pick was a young company on its list date."""
    if not len(df):
        return df
    yv = Y.values
    row = {d: i for i, d in enumerate(Y.index)}
    col = {n: j for j, n in enumerate(Y.columns)}
    return df[np.asarray([bool(yv[row[d], col[n]]) for d, n in zip(df["date"], df["name"])], dtype=bool)]


# A list that leaves out another list's top 15, as leaders.LISTS[...]["gives_way_to"].
GIVES_WAY = {"momentum": "long"}


def top_picks(score, U, dates, n=15, exclude=None):
    """The top n on each date; `exclude` maps a date to names left out."""
    out = []
    for d in dates:
        s = score.loc[d].where(U.loc[d]).dropna()
        if exclude and d in exclude:
            s = s.drop(list(exclude[d] & set(s.index)))
        if len(s) >= n:
            out.append((d, list(s.nlargest(n).index)))
    return out


def list_picks(scores, U, dates, key, n=15, gives_way=GIVES_WAY):
    """One list's picks, leaving out the top n of any list it gives way to."""
    other = gives_way.get(key)
    exclude = None
    if other:
        exclude = {d: set(names) for d, names in top_picks(scores[other], U, dates, n)}
    return top_picks(scores[key], U, dates, n, exclude)


def overlap(scores, U, dates, gives_way=GIVES_WAY, n=15):
    """Names two lists share on the same date, out of n, and distinct names in all four."""
    picks = {k: dict(list_picks(scores, U, dates, k, n, gives_way)) for k in LISTS}
    common = set.intersection(*(set(v) for v in picks.values()))
    out = {}
    keys = list(LISTS)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            out[f"{a} / {b}"] = round(float(np.mean(
                [len(set(picks[a][d]) & set(picks[b][d])) for d in common])), 1)
    out["distinct in all four"] = round(float(np.mean(
        [len(set().union(*(set(picks[k][d]) for k in keys))) for d in common])), 1)
    out["places"] = n * len(keys)
    out["dates"] = len(common)
    return out


# --------------------------------------------------------------------------
# The results list. backend/leaders.result_reactions is the engine's version;
# parity() below proves the two pick the same stocks.
# --------------------------------------------------------------------------

RESULTS_WINDOW, RESULTS_MIN_POOL = 10, 8


def load_results(P):
    """One row per quarterly filing, with `i`: the first session whose close
    came after the filing reached the exchange. None without the table."""
    if not os.path.exists(RESULTS_CSV):
        return None
    df = pd.read_csv(RESULTS_CSV, usecols=["symbol", "period_end", "filed_at", "revenue_yoy_pct",
                                           "ebitda_yoy_pct", "pat_yoy_pct", "pat_cr", "opm_pct"])
    df["filed"] = pd.to_datetime(df["filed_at"], errors="coerce")
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["filed", "period_end"])
    lag = (df["filed"] - df["period_end"]).dt.days
    # A filing later than this is a revision or a refiling, and its date is
    # not when the market learned the numbers.
    df = df[(lag >= 5) & (lag <= 130)]
    df = df[df["symbol"].isin(P.C.columns)]
    idx = P.C.index
    # Filed at or before 15:30 on a session: that session's close has seen it.
    # Anything later: the next session's.
    day = df["filed"].dt.normalize()
    after = (df["filed"].dt.hour * 60 + df["filed"].dt.minute) > (15 * 60 + 30)
    pos = idx.searchsorted(day.values, side="left")
    same_day = (pos < len(idx)) & (idx[np.minimum(pos, len(idx) - 1)] == day.values) & ~after.values
    pos = np.where(same_day, pos, idx.searchsorted(day.values, side="right"))
    df = df[pos < len(idx)].copy()
    pos = pos[pos < len(idx)]
    df["i"] = pos
    df["d0"] = idx[pos]
    df = df.sort_values(["symbol", "period_end"])
    df["opm_change"] = df["opm_pct"] - df.groupby("symbol")["opm_pct"].shift(4)
    df["pat_accel"] = df["pat_yoy_pct"] - df.groupby("symbol")["pat_yoy_pct"].shift(1)
    return df.drop_duplicates(["symbol", "d0"], keep="last").sort_values(["i", "filed"]).reset_index(drop=True)


def results_picks(P, U, R, dates, n=15):
    """
    The results list on each date, exactly as the engine builds it: the
    liquid companies whose results were first priced in the last ten
    sessions, ordered by that session's move less the average liquid stock's.
    Returns (picks, pools): pools maps a date to every company that was
    ranked, which is what the list is compared with.
    """
    ret = (P.C / P.C.shift(1) - 1).values
    Uv = U.values
    col = {name: j for j, name in enumerate(P.C.columns)}
    row = {d: i for i, d in enumerate(P.C.index)}
    pos_all, sym_all = R["i"].values, R["symbol"].values
    picks, pools = [], {}
    for d in dates:
        i = row[d]
        a, b = np.searchsorted(pos_all, i - (RESULTS_WINDOW - 1), "left"), np.searchsorted(pos_all, i, "right")
        latest = {}
        for k in range(a, b):                          # ordered by session: the later filing wins
            latest[sym_all[k]] = int(pos_all[k])
        members = np.flatnonzero(Uv[i])
        inside = set(members.tolist())
        market = {}
        cand = []
        for sym, pos in latest.items():
            j = col[sym]
            move = ret[pos, j]
            if j not in inside or not np.isfinite(move):
                continue
            if pos not in market:
                market[pos] = float(np.nanmean(ret[pos, members]))
            cand.append((float(move - market[pos]), sym))
        pools[d] = [sym for _r, sym in cand]
        if len(cand) >= RESULTS_MIN_POOL:
            cand.sort(key=lambda t: (-t[0], t[1]))
            picks.append((d, [sym for _r, sym in cand[:n]]))
    return picks, pools


def vs_pool(P, df, hold, pools):
    """A results list against every company it was chosen from that day, held
    the same period. Newey-West errors, as for the other lists."""
    if not len(df):
        return None
    fwd = P.C.shift(-hold) / P.entry - 1
    col = {name: j for j, name in enumerate(P.C.columns)}
    row = {d: i for i, d in enumerate(P.C.index)}
    fv = fwd.values
    base = {}
    for d in df["date"].unique():
        d = pd.Timestamp(d)
        vals = [fv[row[d], col[sym]] for sym in pools.get(d, [])]
        vals = [v for v in vals if np.isfinite(v)]
        if vals:
            base[d] = float(np.mean(vals))
    per = df.groupby("date")["ret"].mean()
    ex = (per - pd.Series(base).reindex(per.index)).dropna()
    lags = max(1, int(np.ceil(hold / 5)))

    def one(e):
        t = newey_west_t(e.values, lags)
        return {"excess_pct": round(float(e.mean() * 100), 2) if len(e) else None,
                "t": None if t is None else round(t, 2),
                "lists_ahead_pct": round(float((e > 0).mean() * 100), 1) if len(e) else None}
    return {**one(ex), "by_half": {"2018-21": one(ex[ex.index < SPLIT]), "2022-26": one(ex[ex.index >= SPLIT])}}


def by_market(P, df):
    """A list's picks split by where the Nifty 500 stood, against its own
    200-day average, on the day the list was made."""
    if not len(df):
        return None
    above = (P.N500 > P.N500.rolling(200, min_periods=180).mean())
    flag = above.reindex(df["date"]).fillna(False).astype(bool).values
    out = {}
    for label, part in (("above_200d", df[flag]), ("below_200d", df[~flag])):
        d = describe(part)
        out[label] = None if d is None else {k: d[k] for k in
                                             ("list_dates", "picks", "up_pct", "avg_pct", "index_avg_pct")}
    return out


def run_list(P, picks, hold, exit_pct=None, on_low=False, target_pct=None):
    """
    Hold each pick `hold` sessions from the next open. With `exit_pct`, leave
    at the first close that far under the entry (or, for the old method's
    stop, the first LOW through it, filled at the stop or a lower open).
    With `target_pct`, sell at the first HIGH that far above the entry.
    """
    Cn, On, Ln, Hn = P.C.values, P.O.values, P.L.values, P.H.values
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
            if exit_pct or target_pct:
                line = e * (1 - exit_pct / 100.0) if exit_pct else -1.0
                goal = e * (1 + target_pct / 100.0) if target_pct else None
                for k in range(i + 1, last + 1):
                    c = Cn[k, j]
                    if not np.isfinite(c):
                        continue
                    if goal and Hn[k, j] >= goal:
                        ret = (max(On[k, j], goal) if k > i + 1 else goal) / e - 1
                        out_early = True
                        break
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


def newey_west_t(x, lags):
    """Mean over its standard error, the error widened for overlapping holds."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return None
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(max(s, 1e-18) / n))


def vs_average_stock(P, U, df, hold, first="2017-21"):
    """
    Each list against the average liquid stock on the same dates, held the
    same period: the bar that matters, because the Nifty 500 is weighted to
    the largest companies and these lists are mostly not. The t-statistic is
    over list dates, with Newey-West errors because lists five sessions apart
    hold overlapping periods.
    """
    if not len(df):
        return None
    ew = (P.C.shift(-hold) / P.entry - 1).where(U).mean(axis=1)
    per = df.groupby("date")["ret"].mean()
    ex = (per - ew.reindex(per.index)).dropna()
    lags = max(1, int(np.ceil(hold / 5)))

    def one(e):
        t = newey_west_t(e.values, lags)
        return {"excess_pct": round(float(e.mean() * 100), 2),
                "t": None if t is None else round(t, 2),
                "lists_ahead_pct": round(float((e > 0).mean() * 100), 1)}
    return {**one(ex), "by_half": {first: one(ex[ex.index < SPLIT]),
                                   "2022-26": one(ex[ex.index >= SPLIT])}}


def with_breakdowns(df, first="2017-21"):
    out = describe(df)
    if out is None:
        return None
    out["by_half"] = {first: describe(df[df["date"] < SPLIT]), "2022-26": describe(df[df["date"] >= SPLIT])}
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
# The fifth list is made from results filings, not from the price recipes
# above, so it is run on its own in study() and joins the same output.
RESULTS_LIST = ("results", 21, 12.0)
# Brokerage, STT, exchange charges, stamp duty, GST and a little slippage for
# one buy and one sell of a delivery trade: the figure the Strategy lab uses.
ROUND_TRIP_COST_PCT = 0.49


def _engine_candidates(P, i, young=None):
    """Every stock the scan would have met on session i, as the engine's own
    signals() reads it from a frame cut at that session."""
    import leaders
    cands = []
    sl = slice(max(0, i - 299), i + 1)        # the first list date has only 263 sessions behind it
    # The scan's symbol list on that date: anything trading Rs 3 crore that
    # had not missed more than twenty of the last 260 sessions (the engine
    # reads that off the dates of a real feed; this panel has no gaps), and
    # the companies listed six to twelve months.
    listed = (P.turn60.iloc[i] >= 3e7) & (P.hist.iloc[i] >= 240)
    if young is not None:
        listed = listed | young.iloc[i]
    for n in P.C.columns[listed.values]:
        # Prices as a feed showed them THAT day: adjusted for every split
        # up to it and none after, so the last close is the traded price.
        j = P.C.columns.get_loc(n)
        k = P.RAW.iat[i, j] / P.C.iat[i, j]
        df = pd.DataFrame({"High": P.H[n].values[sl] * k, "Low": P.L[n].values[sl] * k,
                           "Close": P.C[n].values[sl] * k}, index=P.C.index[sl])
        df["Volume"] = P.VAL[n].values[sl] / df["Close"]
        cands.append({"symbol": n, "leader_sig": leaders.signals(df)})
    return cands


def parity(P, U, scores, R=None, results=None, W=None, Y=None):
    """backend/leaders.py must pick what this file picked, or the page is
    printing the record of a recipe the site does not run. `W` is the
    universe the lists are picked from (the established and the young), `Y`
    the young alone; `U` stays the established universe."""
    import leaders
    W = U if W is None else W
    same = total = 0
    spots = [400, 900, 1400, 1900, 2300, 2600]
    if Y is not None:
        # And six dates on which a young company made a list, so the path
        # that places them is under the same check as everything else.
        hit = [i for i in range(262, len(P.C) - 1, 5)
               if any(Y.iat[i, P.C.columns.get_loc(n)]
                      for k in YOUNG_LISTS
                      for n in (list_picks(scores, W, [P.C.index[i]], k) or [(0, [])])[0][1])]
        spots += [hit[int(k)] for k in np.linspace(0, len(hit) - 1, 6)] if hit else []
    for i in sorted(set(spots)):
        if i >= len(P.C):
            continue
        d = P.C.index[i]
        blocks = leaders.rank(_engine_candidates(P, i, Y))
        for key in scores:
            want = set((list_picks(scores, W, [d], key) or [(d, [])])[0][1])
            got = {s for s, b in blocks.items() if (b["lists"][key]["rank"] or 99) <= 15}
            same += len(want & got)
            total += 15
    # The results list, on six dates it made a list. The engine is told only
    # what had reached the exchange by each date, with the real timestamps.
    if R is not None and results:
        row = {d: i for i, d in enumerate(P.C.index)}
        made = dict(results)
        for d in [list(made)[int(k)] for k in np.linspace(0, len(made) - 1, 6)]:
            i = row[d]
            known = R[R["i"] <= i].drop_duplicates("symbol", keep="last")
            filed = {sym: {"filed_at": str(when)[:19]} for sym, when in zip(known["symbol"], known["filed"])}
            blocks = leaders.rank(_engine_candidates(P, i, Y), results=filed)
            want = set(made[d])
            got = {s for s, b in blocks.items() if (b["lists"]["results"]["rank"] or 99) <= 15}
            same += len(want & got)
            total += max(len(want), len(got))
    return same, total


def study():
    P = Panel()
    U = P.universe(10)
    plain = recipes(P, U)                      # the four lists on established companies alone
    scores, W, Y = add_young(P, U, plain)      # W: who a list may pick; U: who it is compared with
    try:
        with open(OUT, encoding="utf-8") as f:
            previous = json.load(f)
    except Exception:
        previous = {}
    R = load_results(P)
    r_key, r_hold, r_exit = RESULTS_LIST
    r_picks = r_pools = r_dates = None
    if R is not None:
        first = max(262, int(R["i"].min()) + RESULTS_WINDOW)
        first += (-(first - 262)) % 5                  # on the same five-session grid as the others
        r_dates = P.C.index[first:-(r_hold + 1):5]
        r_picks, r_pools = results_picks(P, U, R, r_dates)
    same, total = parity(P, U, scores, R, r_picks, W, Y)
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
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "lists": {}, "exits": {}, "before": {}, "score": {}, "factors": {},
    }

    # How many names the lists share, as run and as first built.
    shared = recipes(P, U, shared=True)
    every = P.C.index[262:-1:5]
    result["overlap"] = {"now": overlap(scores, W, every),
                         "first version": overlap(shared, U, every, gives_way={})}
    print("overlap:", json.dumps(result["overlap"], indent=1))
    result["first_version"] = {
        "what": ("The lists as first built: this month was three parts leader score and one "
                 "part five-day dip, and momentum did not give way to long term. Same dates, "
                 "same rules."),
        "lists": {},
    }

    for key, (hold, exit_pct) in LISTS.items():
        dates = P.C.index[262:-(hold + 1):5]
        picks = list_picks(scores, W, dates, key)
        ran = run_list(P, picks, hold, exit_pct)
        rec = with_breakdowns(ran)
        rec.update(hold_sessions=hold, exit_pct=exit_pct,
                   avg_after_costs_pct=round(rec["avg_pct"] - ROUND_TRIP_COST_PCT, 2),
                   vs_average_stock=vs_average_stock(P, U, ran, hold),
                   market=by_market(P, ran))
        if key in YOUNG_LISTS:
            # The list with companies listed six to twelve months let in,
            # beside the same list without them and the young picks alone.
            was = run_list(P, list_picks(plain, U, dates, key), hold, exit_pct)
            yo = young_only(ran, Y)
            d_yo, v_yo = describe(yo), vs_average_stock(P, U, yo, hold)
            rec["young"] = {
                "what": "Companies listed six to twelve months, their 6-month return standing in "
                        "for the 12-month one, placed against the established universe.",
                "picks": d_yo["picks"], "list_dates": d_yo["list_dates"], "up_pct": d_yo["up_pct"],
                "avg_pct": d_yo["avg_pct"], "median_pct": d_yo["median_pct"],
                "index_avg_pct": d_yo["index_avg_pct"], "worst_5pct": d_yo["worst_5pct"],
                "vs_average_stock": v_yo,
                "list_without_them": {**{k: describe(was)[k] for k in ("picks", "up_pct", "avg_pct")},
                                      "vs_average_stock": vs_average_stock(P, U, was, hold)},
            }
            led = all((v_yo["by_half"][h]["excess_pct"] or -9) > 0 for h in ("2017-21", "2022-26"))
            assert led, f"young companies did not lead on the {key} list in both halves; do not admit them"
        result["lists"][key] = rec
        first = run_list(P, top_picks(shared[key], U, dates), hold, exit_pct)
        result["first_version"]["lists"][key] = {**describe(first),
                                                 "vs_average_stock": vs_average_stock(P, U, first, hold)}
        result["exits"][key] = {"no exit line": describe(run_list(P, picks, hold))}
        for alt in sorted({exit_pct / 2, exit_pct, exit_pct * 1.5}):
            result["exits"][key][f"close {alt:g}% under"] = describe(run_list(P, picks, hold, alt))
        # A target as far above as the exit line is below, and one twice as far.
        for mult in (1, 2):
            result["exits"][key][f"close {exit_pct:g}% under, target {exit_pct * mult:g}% over"] = describe(
                run_list(P, picks, hold, exit_pct, target_pct=exit_pct * mult))
        print(f"\n{key}: hold {hold}, exit {exit_pct}%")
        print(json.dumps({k: v for k, v in rec.items() if k not in ("by_year",)}, indent=1))

    # The results list: made from filings, so it has its own picker.
    if r_picks is not None:
        ran = run_list(P, r_picks, r_hold, r_exit)
        rec = with_breakdowns(ran, first="2018-21")
        rec.update(hold_sessions=r_hold, exit_pct=r_exit,
                   avg_after_costs_pct=round(rec["avg_pct"] - ROUND_TRIP_COST_PCT, 2),
                   vs_average_stock=vs_average_stock(P, U, ran, r_hold, first="2018-21"),
                   vs_reporters=vs_pool(P, ran, r_hold, r_pools),
                   market=by_market(P, ran),
                   **{"from": str(r_dates[0].date()),
                      "dates_tried": int(len(r_dates)),
                      "filings": int(len(R)), "companies": int(R["symbol"].nunique()),
                      "window_sessions": RESULTS_WINDOW, "min_companies": RESULTS_MIN_POOL,
                      "what": ("Liquid companies whose quarterly results were first priced in the last "
                               f"{RESULTS_WINDOW} sessions, ordered by that session's move less the average "
                               "liquid stock's. A list is made only when eight or more qualify."),
                      "bias": ("The results table holds companies listed today. vs_reporters compares the "
                               "list with every company it was chosen from, which shares that bias.")})
        result["lists"][r_key] = rec
        result["exits"][r_key] = {"no exit line": describe(run_list(P, r_picks, r_hold))}
        for alt in sorted({r_exit / 2, r_exit, r_exit * 1.5}):
            result["exits"][r_key][f"close {alt:g}% under"] = describe(run_list(P, r_picks, r_hold, alt))
        print(f"\n{r_key}: hold {r_hold}, exit {r_exit}%")
        print(json.dumps({k: v for k, v in rec.items() if k not in ("by_year",)}, indent=1))
    elif (previous.get("lists") or {}).get(r_key):
        # No results table on this machine: keep the record last written, and say so.
        result["lists"][r_key] = dict(previous["lists"][r_key], carried_over=True)
        if (previous.get("exits") or {}).get(r_key):
            result["exits"][r_key] = previous["exits"][r_key]
        print(f"\n{r_key}: no results table at {RESULTS_CSV}; the last record is kept.")

    # Momentum held six months instead of three: the same picks, a wider line.
    dates = P.C.index[262:-(126 + 1):5]
    result["momentum_six_months"] = {
        "hold_sessions": 126, "exit_pct": 20.0,
        **describe(run_list(P, list_picks(scores, W, dates, "momentum"), 126, 20.0))}
    print("\nmomentum held six months:", json.dumps(result["momentum_six_months"], indent=1))

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
                P, list_picks(scores, W, [d for d, _ in op], "momentum"), 42, 8.0, on_low=True)),
        }
        print("\nbefore:", json.dumps(result["before"], indent=1))
    elif previous.get("before"):
        # The replay of the old method takes half an hour and its subject no
        # longer changes. Without it on disk, the last replay is kept.
        result["before"] = previous["before"]

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
