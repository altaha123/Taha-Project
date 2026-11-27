"""
The fundamental Ideas lab: the three Ideas tabs, replayed point in time.

    python research/fundamental_ideas_lab.py --prepare   # candidates for every list date (slow, once)
    python research/fundamental_ideas_lab.py --replay    # every declared variant, through the engine itself
    python research/fundamental_ideas_lab.py --report    # the tables, the choice, research/fundamental-ideas-lab.json

WHAT IT TESTS
The Ideas page shows three lists (backend/leaders.py): a swing list of healthy
leaders pulling back in industries money is moving into, the companies whose
results the market rewarded for real reasons, and long-term compounders. All
three read a company's own filings. This file replays them on every fifth
session from 2017 to 2026 and measures what they did next, against what the
lists they replaced did over the same sessions.

THE ENGINE ITSELF, NOT A COPY OF IT
Every list date runs backend/leaders.rank() on candidates cut from the price
panel at that session (research/ideas_study.py's _engine_candidates) and on
fundamentals built by backend/fund_snapshot.py — the code the live scan runs.
So the record printed beside a list is the record of the code that makes the
list; there is no second implementation to drift away from it.

NO LOOK-AHEAD
A filing is seen from the first session whose close came after it reached the
exchange, as research/ideas_study.py's results list reads it: filed at or
before 15:30 on a trading day, that day's close; any later, the next
session's. Each company's snapshot on a list date is rebuilt from the rows
visible by then and no others. Two things still flatter the test, and the
study says so beside the numbers:

  · the fundamentals tables hold the LATEST filing for each period. A revised
    quarter is seen from the revision's date (later than the original, which
    delays it and never advances it) and with the revised numbers;
  · the tables hold companies listed today, so a company delisted after a bad
    year is missing from the fundamentals (not from prices).

WHAT IS NOT TESTED
Pledges, promoter and institutional holdings, delivery and order wins have no
history to replay; the live lists read them and here they are unknown, which
every list treats as neutral. Balance sheets exist in XBRL only from September
2022 and full-year cash flows from 2020-21, so before then the long list's
balance-sheet and cash checks are skipped as unknown. Its record is therefore
split where the data allow (see SELECTION).

THE CHOICE, DECLARED BEFORE ANY RUN (research/IDEAS-STUDY.md)
Each tab has a handful of declared versions (VARIANTS). One rule picks among
them on the first window, and the second window is then printed whatever it
says:
  month, results  first window 2018-06 to 2021-12, second 2022-01 to the end.
  long            first window 2022-11 to 2024-04, second 2024-05 to the last
                  list date whose year-long hold has completed.
The rule: the highest mean return over the average liquid stock after the
0.49% round trip, among versions with enough picks in the first window and a
positive mean after costs; within 0.05 points, the one with fewer rules.
"""

import argparse
import bisect
import datetime as dt
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

import ideas_study as S          # noqa: E402  (the panel, the replay helpers, the metrics)
import fund_snapshot as FS       # noqa: E402

DATA = S.DATA
OUT = os.path.join(HERE, "fundamental-ideas-lab.json")
CAND_DIR = os.path.join(DATA, "fil_candidates")
PICKS_FILE = os.path.join(DATA, "fil_picks.pkl")
TABLE_FILES = {"quarterly": "income_quarterly_full.csv", "annual": "income_annual.csv",
               "cashflow": "cashflow.csv", "balance": "balance.csv"}
FIRST_DAY = 262                  # the first session with a year of prices behind it (as ideas_study)
STEP = 5                         # a list every fifth session
COST = S.ROUND_TRIP_COST_PCT / 100.0
TABS = {"month": (21, 12.0), "results": (21, 12.0), "long": (252, 30.0)}

WINDOWS = {
    "month": (("2018-06-01", "2021-12-31"), ("2022-01-01", "2100-01-01")),
    "results": (("2018-06-01", "2021-12-31"), ("2022-01-01", "2100-01-01")),
    "long": (("2022-11-01", "2024-04-30"), ("2024-05-01", "2100-01-01")),
}
LONG_REFERENCE = ("2018-06-01", "2022-10-31")
MIN_FIRST_PICKS = {"month": 400, "results": 250, "long": 300}
TIE_PP = 0.05

# The declared versions. Each is a set of overrides of leaders.MONTH,
# leaders.RESULTS and leaders.LONG; `rules` counts what each adds, for the
# tie-break. The defaults in backend/leaders.py are M0, R4 and L1.
VARIANTS = {
    "month": {
        "M0": ({}, 7),
        "M1": ({"sector_gate": False}, 6),
        "M2": ({"profit_guard": False, "result_guard": False}, 5),
        "M3": ({"leader_floor": 0.70, "pull_mix": {"dip21": 1.0}}, 7),
    },
    "results": {
        "R1": ({"floor": None, "mix": {"reaction": 1.0, "volume": 0.0, "growth": 0.0}}, 2),
        "R2": ({"floor": "sma200_85", "mix": {"reaction": 1.0, "volume": 0.0, "growth": 0.0}}, 3),
        "R3": ({"floor": "sma50", "mix": {"reaction": 1.0, "volume": 0.0, "growth": 0.0}}, 3),
        "R4": ({}, 5),
        "R5": ({"floor": None}, 4),
    },
    "long": {
        "L1": ({}, 6),
        "L2": ({"_exit_pct": 25.0}, 6),
        "L3": ({"mix": {"quality": 0.30, "compounding": 0.25, "governance": 0.15,
                        "valuation": 0.0, "trendq": 0.30}}, 5),
        "L4": ({"mix": {"quality": 0.0, "compounding": 0.0, "governance": 0.0,
                        "valuation": 0.0, "trendq": 1.0}}, 4),
    },
}


# --------------------------------------------------------------------------
# Point in time: which filing was known on which session
# --------------------------------------------------------------------------

def visible_index(index, filed):
    """For each filing time, the position of the first session whose close
    came after it (len(index) when none has yet). Filed at or before 15:30 on
    a session: that session; later, or on a holiday: the next."""
    filed = pd.to_datetime(pd.Series(filed), errors="coerce")
    day = filed.dt.normalize()
    late = (filed.dt.hour * 60 + filed.dt.minute) > (15 * 60 + 30)
    pos = index.searchsorted(day.values, side="left")
    hit = (pos < len(index)) & (index[np.minimum(pos, len(index) - 1)] == day.values) & ~late.values
    pos = np.where(hit, pos, index.searchsorted(day.values, side="right"))
    return np.where(filed.isna().values, len(index), pos)


def _records(df):
    out = []
    for r in df.to_dict("records"):
        out.append({k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()})
    return out


def load_pit(P):
    """{SYMBOL: {table: (i_vis list ascending, rows in the same order)}}."""
    pit = {}
    for table, name in TABLE_FILES.items():
        path = os.path.join(DATA, name)
        df = pd.read_csv(path, low_memory=False)
        df = df[df["symbol"].isin(P.C.columns)]
        filed = pd.to_datetime(df["filed_at"], errors="coerce")
        end = pd.to_datetime(df["period_end"], errors="coerce")
        # A filing dated before its period ended is a data error, not news.
        df = df[(filed.notna()) & (end.notna()) & (filed >= end)].copy()
        df["i_vis"] = visible_index(P.C.index, df["filed_at"])
        df = df[df["i_vis"] < len(P.C.index)].sort_values(["symbol", "i_vis", "period_end"])
        for sym, g in df.groupby("symbol", sort=False):
            rows = _records(g)
            pit.setdefault(sym, {})[table] = ([int(r["i_vis"]) for r in rows], rows)
    return pit


def _seen(pit_sym, table, i):
    got = pit_sym.get(table)
    if not got:
        return []
    keys, rows = got
    return rows[:bisect.bisect_right(keys, i)]


def snapshot_at(pit, i, day, syms, sectors, raw_close):
    """{SYMBOL: snapshot with valuation} as the live scan would have built it
    on session i, from the filings visible by then."""
    out = {}
    col = {n: j for j, n in enumerate(raw_close.columns)}
    for sym in syms:
        p = pit.get(sym)
        if not p:
            continue
        snap = FS.build(_seen(p, "quarterly", i), _seen(p, "annual", i), _seen(p, "cashflow", i),
                        _seen(p, "balance", i), sector=sectors.get(sym), asof=day)
        if not snap:
            continue
        j = col.get(sym)
        price = float(raw_close.iat[i, j]) if j is not None else None
        out[sym] = FS.with_price(snap, price if price and np.isfinite(price) else None)
    return out


# --------------------------------------------------------------------------
# Candidates, cached: the slow part of a replay, the same for every variant
# --------------------------------------------------------------------------

def _dates(P):
    return list(range(FIRST_DAY, len(P.C) - 2, STEP))


def _stamp(P):
    """What the cached candidates depend on: the engine's own signals on a
    probe date. A changed signals() changes this and the cache is rebuilt."""
    S._AGE["age"] = S.listing_ages(P)
    h = hashlib.sha1(str(len(P.C)).encode())
    # Whole candidates, values and all, on three dates: a change to any number
    # signals() or technicals() produces shows up here.
    for i in (700, 1500, 2400):
        for c in S._engine_candidates(P, i)[:60]:
            h.update(repr((c["symbol"], sorted((c["leader_sig"] or {}).items()))).encode())
    return h.hexdigest()[:16]


_G = {}


def _make_cands(i):
    P = _G["P"]
    cands = S._engine_candidates(P, i)
    with open(os.path.join(_G["dir"], f"{i}.pkl"), "wb") as f:
        pickle.dump(cands, f, protocol=4)
    return i


def prepare(procs=4):
    import multiprocessing as mp
    P = S.Panel()
    stamp = _stamp(P)
    d = os.path.join(CAND_DIR, stamp)
    os.makedirs(d, exist_ok=True)
    todo = [i for i in _dates(P) if not os.path.exists(os.path.join(d, f"{i}.pkl"))]
    print(f"candidates: {len(_dates(P)) - len(todo)} cached, {len(todo)} to build under {stamp}")
    _G.update(P=P, dir=d)
    S._AGE["age"] = S.listing_ages(P)
    t0 = time.time()
    with mp.get_context("fork").Pool(procs) as pool:
        for n, _ in enumerate(pool.imap_unordered(_make_cands, todo, chunksize=4), 1):
            if n % 50 == 0:
                print(f"  {n}/{len(todo)} in {time.time() - t0:.0f}s", flush=True)
    with open(os.path.join(CAND_DIR, "current"), "w") as f:
        f.write(stamp)
    return stamp


# --------------------------------------------------------------------------
# The replay
# --------------------------------------------------------------------------

def _apply(overrides):
    """Set leaders.MONTH / RESULTS / LONG to their defaults plus overrides.
    A key the engine does not have is an error, not a silent default: a typo
    would otherwise measure the default recipe under a variant's name.
    Keys starting with "_" belong to the lab (an exit line, say)."""
    import leaders
    for tab, name in (("month", "MONTH"), ("results", "RESULTS"), ("long", "LONG")):
        base = _G["defaults"][name]
        cfg = dict(base)
        for k, v in (overrides.get(tab) or {}).items():
            if k.startswith("_"):
                continue
            if k not in base:
                raise KeyError(f"leaders.{name} has no '{k}': the variant would run the default")
            cfg[k] = v
        setattr(leaders, name, cfg)


def _replay_one(i):
    import leaders
    P, R, sectors, pit = _G["P"], _G["R"], _G["sectors"], _G["pit"]
    with open(os.path.join(_G["dir"], f"{i}.pkl"), "rb") as f:
        cands = pickle.load(f)
    day = P.C.index[i].date()
    known = R[R["i"] <= i].drop_duplicates("symbol", keep="last")
    filed = {r.symbol: {"filed_at": str(r.filed)[:19]} for r in known.itertuples(index=False)}
    growth = {r.symbol: {"pat_yoy_pct": None if pd.isna(r.pat_yoy_pct) else float(r.pat_yoy_pct),
                         "revenue_yoy_pct": None if pd.isna(r.revenue_yoy_pct) else float(r.revenue_yoy_pct),
                         "pat_cr": None if pd.isna(r.pat_cr) else float(r.pat_cr)}
              for r in known[known["i"] >= i - 100].itertuples(index=False)}
    syms = [c["symbol"] for c in cands]
    snap = snapshot_at(pit, i, day, syms, sectors, P.RAW)
    out = {}
    for name, overrides in _G["sets"]:
        _apply(overrides)
        blocks = leaders.rank(cands, results=filed, sectors=sectors, fundamentals=growth,
                              benchmark=S.benchmark_at(P, i), snapshot=snap)
        got = {}
        for tab in TABS:
            top = sorted((b["lists"][tab]["rank"], s) for s, b in blocks.items()
                         if b["lists"].get(tab) and (b["lists"][tab]["rank"] or 99) <= leaders.LIST_SIZE)
            got[tab] = [s for _r, s in top]
        out[name] = got
    return i, out


def variant_sets():
    """Variant k of every tab, run together: the tabs do not interact."""
    k = max(len(v) for v in VARIANTS.values())
    sets = []
    for n in range(k):
        name, ov = [], {}
        for tab, vs in VARIANTS.items():
            keys = list(vs)
            key = keys[min(n, len(keys) - 1)]
            name.append(key)
            ov[tab] = vs[key][0]
        sets.append(("/".join(name), ov))
    return sets


def replay(procs=4):
    import copy
    import multiprocessing as mp
    import leaders
    P = S.Panel()
    with open(os.path.join(CAND_DIR, "current")) as f:
        stamp = f.read().strip()
    R = S.load_results(P)
    sectors = {k: v for k, v in S.load_sectors().items()} or _sectors_fallback()
    pit = load_pit(P)
    _G.update(P=P, R=R, sectors=sectors, pit=pit, dir=os.path.join(CAND_DIR, stamp),
              sets=variant_sets(),
              defaults={n: copy.deepcopy(getattr(leaders, n)) for n in ("MONTH", "RESULTS", "LONG")})
    days = _dates(P)
    t0 = time.time()
    rows = []
    with mp.get_context("fork").Pool(procs) as pool:
        for n, r in enumerate(pool.imap_unordered(_replay_one, days, chunksize=4), 1):
            rows.append(r)
            if n % 50 == 0:
                print(f"  {n}/{len(days)} dates in {time.time() - t0:.0f}s", flush=True)
    rows.sort()
    picks = {}
    for i, out in rows:
        for name, got in out.items():
            for tab, names in got.items():
                if names:
                    picks.setdefault(name, {}).setdefault(tab, []).append((P.C.index[i], names))
    with open(PICKS_FILE, "wb") as f:
        pickle.dump({"stamp": stamp, "sets": [n for n, _ in _G["sets"]], "picks": picks}, f)
    return picks


def _sectors_fallback():
    path = os.path.join(HERE, "..", "backend", "nse_industries.csv")
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    return dict(zip(df["Symbol"].astype(str).str.strip(), df["Industry"].astype(str).str.strip()))


# --------------------------------------------------------------------------
# What the picks did
# --------------------------------------------------------------------------

def _avg_stock(P, U, hold):
    """Each date's average liquid stock, bought at the next open and held."""
    key = ("ew", hold)
    if key not in _G:
        _G[key] = (P.C.shift(-hold) / P.entry - 1).where(U).mean(axis=1)
    return _G[key]


def window_record(P, U, df, hold, start, end):
    """One list over one window: how many, how often up, the average before
    and after costs, the middle pick, the worst one in twenty, and the lead
    over the Nifty 500 and over the average liquid stock (Newey-West t)."""
    d = df[(df["date"] >= start) & (df["date"] <= end)]
    if not len(d):
        return {"picks": 0}
    out = S.describe(d)
    out["avg_net_pct"] = round(out["avg_pct"] - S.ROUND_TRIP_COST_PCT, 2)
    out["vs_index_pct"] = round(out["avg_pct"] - out["index_avg_pct"], 2)
    per = d.groupby("date")["ret"].mean()
    ex = (per - _avg_stock(P, U, hold).reindex(per.index)).dropna()
    t = S.newey_west_t(ex.values, max(1, int(np.ceil(hold / STEP))))
    out["vs_avg_stock_pct"] = round(float(ex.mean() * 100), 2) if len(ex) else None
    out["vs_avg_stock_net_pct"] = (round(float(ex.mean() * 100) - S.ROUND_TRIP_COST_PCT, 2)
                                   if len(ex) else None)
    out["vs_avg_stock_t"] = None if t is None else round(t, 2)
    out["lists_ahead_of_avg_stock_pct"] = round(float((ex > 0).mean() * 100), 1) if len(ex) else None
    return out


def overlap(picks_by_tab):
    """Names the three tabs share on the same date: per pair, the mean shared
    on dates both made a list, and the share of those dates with any."""
    tabs = [t for t in TABS if picks_by_tab.get(t)]
    by = {t: {d: set(n) for d, n in picks_by_tab[t]} for t in tabs}
    out = {}
    for a_i, a in enumerate(tabs):
        for b in tabs[a_i + 1:]:
            days = sorted(set(by[a]) & set(by[b]))
            shared = [len(by[a][d] & by[b][d]) for d in days]
            out[f"{a} / {b}"] = {"dates": len(days),
                                 "mean_shared": round(float(np.mean(shared)), 2) if shared else 0.0,
                                 "dates_with_any_pct": (round(float(np.mean([s > 0 for s in shared])) * 100, 1)
                                                        if shared else 0.0)}
    return out


def before_picks(P, U):
    """Today's lists, from research/ideas_study.py's vectorized recipes,
    which its parity check holds equal to the engine they came from."""
    scores = S.recipes(P, U)
    dates = P.C.index[_dates(P)]
    got = {k: S.list_picks(scores, U, dates, k) for k in ("week", "month", "momentum", "long")}
    R = S.load_results(P)
    if R is not None:
        got["results"], _pools = S.results_picks(P, U, R, dates)
    return got


def _rules(tab, key):
    return VARIANTS[tab][key][1]


def choose(records):
    """The declared rule, per tab, on the first window."""
    chosen = {}
    for tab in TABS:
        rows = []
        for key in VARIANTS[tab]:
            first = (records.get(tab, {}).get(key) or {}).get("first") or {}
            if (first.get("picks") or 0) < MIN_FIRST_PICKS[tab]:
                continue
            if (first.get("avg_net_pct") or -1) <= 0 or first.get("vs_avg_stock_pct") is None:
                continue
            rows.append((first["vs_avg_stock_pct"], -_rules(tab, key), key))
        if not rows:
            chosen[tab] = None
            continue
        best = max(r[0] for r in rows)
        near = [r for r in rows if best - r[0] <= TIE_PP]
        # Fewest rules first (r[1] is minus the count), then the larger lead.
        chosen[tab] = max(near, key=lambda r: (r[1], r[0]))[2]
    return chosen


def report():
    P = S.Panel()
    U = P.universe(10)
    with open(PICKS_FILE, "rb") as f:
        got = pickle.load(f)
    sets = got["sets"]
    picks = got["picks"]
    records = {}
    for tab, (hold, exit_pct) in TABS.items():
        (f0, f1), (s0, s1) = WINDOWS[tab]
        for key, (ov, _n) in VARIANTS[tab].items():
            name = next(n for n in sets if key in n.split("/"))
            p = (picks.get(name) or {}).get(tab) or []
            ex = ov.get("_exit_pct", exit_pct)
            df = S.run_list(P, p, hold, ex)
            rec = {"exit_pct": ex, "hold_sessions": hold,
                   "first": window_record(P, U, df, hold, f0, f1),
                   "second": window_record(P, U, df, hold, s0, s1),
                   "all": window_record(P, U, df, hold, "1900-01-01", "2100-01-01")}
            if tab == "long":
                rec["reference_2018_22"] = window_record(P, U, df, hold, *LONG_REFERENCE)
            records.setdefault(tab, {})[key] = rec
    chosen = choose(records)
    # Before: today's lists on the same windows.
    before = {}
    old = before_picks(P, U)
    for tab, keys in (("month", ("week", "month")), ("results", ("results",)), ("long", ("long", "momentum"))):
        (f0, f1), (s0, s1) = WINDOWS[tab]
        for k in keys:
            hold, ex = S.LISTS[k] if k in S.LISTS else S.RESULTS_LIST[1:]
            df = S.run_list(P, old.get(k) or [], hold, ex)
            before.setdefault(tab, {})[k] = {"exit_pct": ex, "hold_sessions": hold,
                                             "first": window_record(P, U, df, hold, f0, f1),
                                             "second": window_record(P, U, df, hold, s0, s1),
                                             "all": window_record(P, U, df, hold, "1900-01-01", "2100-01-01")}
    best_set = {tab: next((n for n in sets if (chosen.get(tab) or "-") in n.split("/")), None) for tab in TABS}
    ov = overlap({tab: (picks.get(best_set[tab]) or {}).get(tab) or [] for tab in TABS if best_set[tab]})
    result = {"generated": dt.date.today().isoformat(), "windows": WINDOWS, "long_reference": LONG_REFERENCE,
              "round_trip_cost_pct": S.ROUND_TRIP_COST_PCT, "rule": {
                  "min_first_picks": MIN_FIRST_PICKS, "tie_pp": TIE_PP,
                  "text": ("Highest first-window mean lead over the average liquid stock, among versions with "
                           "enough picks and a positive mean after a 0.49% round trip; within 0.05 points the "
                           "one with fewer rules. The second window is printed whatever it shows.")},
              "variants": {t: {k: {"overrides": v[0], "rules": v[1]} for k, v in vs.items()}
                           for t, vs in VARIANTS.items()},
              "records": records, "before": before, "chosen": chosen, "overlap": ov}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    if a.prepare:
        prepare(a.procs)
    if a.replay:
        replay(a.procs)
    if a.report:
        r = report()
        print(json.dumps({"chosen": r["chosen"], "overlap": r["overlap"]}, indent=1))


if __name__ == "__main__":
    main()
