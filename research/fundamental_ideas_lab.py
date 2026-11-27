"""
The fundamental Ideas lab: the three Ideas tabs, replayed point in time.

    python research/fundamental_ideas_lab.py --prepare   # candidates for every list date (slow, once)
    python research/fundamental_ideas_lab.py --replay    # every declared variant, through the engine itself
    python research/fundamental_ideas_lab.py --report    # the tables, the choice, research/fundamental-ideas-lab.json
    python research/fundamental_ideas_lab.py --publish   # the chosen versions' records, into the study file

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

PUBLISHING
--publish turns the chosen versions' picks into the record the Ideas page
prints beside each list, in the schema research/ideas-study.json uses for
every other list (research/ideas_study.py's run_list, with_breakdowns,
vs_average_stock, by_market and vs_pool), with the exit lines
leaders.target_tested reads, and writes it into both copies of that file.
Before it writes anything it checks that the engine as it stands ranks what
the replay picked: the candidates' signals against the cache's stamp, and
leaders.rank() with today's defaults against the chosen versions' picks on
a handful of list dates. A recipe changed since the replay stops it there.
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

# The recipe as specified before the run, which every version below
# overrides. When the lab ran, backend/leaders.py's defaults were this
# specification (M0, R4 and L1); the rule then chose M3 for the month list
# and its two values were written back as the defaults. Pinning the
# specification here keeps a replay run today on the versions declared,
# whatever the defaults have become; with the defaults the lab ran on it
# changes nothing.
SPEC = {"month": {"leader_floor": 0.65, "pull_mix": {"dip21": 0.5, "dip": 0.5}},
        "results": {}, "long": {}}

# The declared versions. Each is a set of overrides of SPEC, itself one of
# leaders.MONTH, leaders.RESULTS and leaders.LONG; `rules` counts what each
# adds, for the tie-break. The defaults in backend/leaders.py are now the
# chosen M3, R4 and L1.
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
    """Set leaders.MONTH / RESULTS / LONG to their defaults, then SPEC, then
    overrides. A key the engine does not have is an error, not a silent
    default: a typo would otherwise measure the default recipe under a
    variant's name. Keys starting with "_" belong to the lab (an exit line,
    say)."""
    import leaders
    for tab, name in (("month", "MONTH"), ("results", "RESULTS"), ("long", "LONG")):
        base = _G["defaults"][name]
        cfg = dict(base)
        for k, v in list((SPEC.get(tab) or {}).items()) + list((overrides.get(tab) or {}).items()):
            if k.startswith("_"):
                continue
            if k not in base:
                raise KeyError(f"leaders.{name} has no '{k}': the variant would run the default")
            cfg[k] = v
        setattr(leaders, name, cfg)


def _inputs(R, i):
    """What had reached the exchange by session i, as the scan hands it to
    rank(): each company's latest filing time (`results`) and its latest
    quarter from the last hundred sessions (`fundamentals`, which the setup
    lists read)."""
    known = R[R["i"] <= i].drop_duplicates("symbol", keep="last")
    filed = {r.symbol: {"filed_at": str(r.filed)[:19]} for r in known.itertuples(index=False)}
    growth = {r.symbol: {"pat_yoy_pct": None if pd.isna(r.pat_yoy_pct) else float(r.pat_yoy_pct),
                         "revenue_yoy_pct": None if pd.isna(r.revenue_yoy_pct) else float(r.revenue_yoy_pct),
                         "pat_cr": None if pd.isna(r.pat_cr) else float(r.pat_cr)}
              for r in known[known["i"] >= i - 100].itertuples(index=False)}
    return filed, growth


def _tops(blocks):
    """Each tab's top LIST_SIZE, in rank order."""
    import leaders
    got = {}
    for tab in TABS:
        top = sorted((b["lists"][tab]["rank"], s) for s, b in blocks.items()
                     if b["lists"].get(tab) and (b["lists"][tab]["rank"] or 99) <= leaders.LIST_SIZE)
        got[tab] = [s for _r, s in top]
    return got


def _replay_one(i):
    import leaders
    P, R, sectors, pit = _G["P"], _G["R"], _G["sectors"], _G["pit"]
    with open(os.path.join(_G["dir"], f"{i}.pkl"), "rb") as f:
        cands = pickle.load(f)
    day = P.C.index[i].date()
    filed, growth = _inputs(R, i)
    syms = [c["symbol"] for c in cands]
    snap = snapshot_at(pit, i, day, syms, sectors, P.RAW)
    out = {}
    for name, overrides in _G["sets"]:
        _apply(overrides)
        blocks = leaders.rank(cands, results=filed, sectors=sectors, fundamentals=growth,
                              benchmark=S.benchmark_at(P, i), snapshot=snap)
        out[name] = _tops(blocks)
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


# --------------------------------------------------------------------------
# Publishing: the chosen versions' records, into the file the page reads
# --------------------------------------------------------------------------

STUDY_FILES = (S.OUT, os.path.join(HERE, "..", "backend", "ideas_study.json"))
# The first half's label, as the page and the tests read it: the results
# list's filings begin in 2018.
FIRST_HALF = {"month": "2017-21", "results": "2018-21", "long": "2017-21"}
CHECK_DATES = 8                  # list dates the engine is re-ranked on before publishing

REPLAY_TEXT = ("The site's own engine (backend/leaders.rank) run on every fifth session from 2017, on prices "
               "and filings cut at that session; its top fifteen bought at the next open.")
NOTES = {
    "month": {
        "what": ("Market leaders (leader score in the top 30%) in an uptrend and outside the most volatile "
                 "fifth, in an industry in the top half on money flow, with no loss and no fall in profit last "
                 "quarter, no results the market sold in the last month and no more than 10% of the company "
                 "pledged. Ranked on the month's pullback, closeness to the 52-week high, the last quarter's "
                 "sales and margin growth, the industry's money flow and a live catalyst; at most four from one "
                 "industry."),
        "bias": ("Pledges, deliveries and orders have no history to replay: they were unknown here, which the "
                 "list counts as neutral, and the live list reads them. Industries are NSE's list as it stands "
                 "today. Quarterly filings start in 2018 and cover companies listed today; a stock with none is "
                 "never refused for it, and a revised quarter is seen from the revision's date."),
    },
    "results": {
        "what": ("Liquid companies whose quarterly results were first priced in the last 10 sessions and showed "
                 "real growth: sales up 8% or more, profit and operating profit up, other income no more than "
                 "35% and an exceptional gain no more than 30% of profit before tax, and cash from operations "
                 "positive in the last full year. Not already up 18% on the day, nor more than 15% under the "
                 "200-day average. Ranked half on that session's move less the average liquid stock's, a "
                 "quarter on the volume behind it and a quarter on the growth; at most four from one industry. "
                 "A list is made only when eight or more pass every test."),
        "bias": ("The results tables hold companies listed today, so one delisted after a bad quarter is "
                 "missing, and a revised quarter is seen from the revision's date with the revised figures. "
                 "vs_reporters compares the list with every liquid company whose results were priced in the "
                 "same ten sessions, which shares that bias."),
    },
    "long": {
        "what": ("Above the 200-day average and outside the most volatile fifth, a profit over the last four "
                 "quarters, an F-score of 5 or more, no more than 5% pledged, a return on capital of 14% or more, "
                 "cash from operations positive and at least 0.7 times profit, debt no more than equity (a "
                 "lender: a return on equity of 13% or more), and a P/E under 90 unless its PEG is 1.5 or under "
                 "on profit growing 35% a year. Ranked on quality, three-year compounding, governance, valuation "
                 "against its own industry and the year-long trend; at most four from one industry."),
        "bias": ("Balance sheets are on file from September 2022 and full-year cash flows from 2020-21. Before "
                 "then the return, debt, F-score and cash checks were skipped as unknown and the list ranked "
                 "mostly on its trend, which is why its version was chosen on 2022-11 to 2024-04. Pledges and "
                 "holdings have no history and were unknown throughout. The tables hold companies listed today, "
                 "and a revised filing is seen from the revision's date."),
    },
}
OVERLAP_TEXT = ("Names two of the three lists share on the same list date, out of 15: mean_shared over the dates "
                "both made a list, dates_with_any_pct the share of those dates with one or more in common. No "
                "list gives way to another.")


def _clean(x):
    """NaN and infinity to None, numpy numbers to Python ones, all the way down."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    return x


def chosen_picks(got, lab):
    """{tab: (version, replay set, [(date, [names])])} for the version the
    declared rule chose, found as --report found it."""
    out = {}
    for tab in TABS:
        key = (lab.get("chosen") or {}).get(tab)
        name = next((n for n in got["sets"] if key and key in n.split("/")), None)
        if not key or name is None:
            raise SystemExit(f"the lab chose no replayed version of {tab}: nothing to publish")
        out[tab] = (key, name, (got["picks"].get(name) or {}).get(tab) or [])
    return out


def engine_check(P, R, sectors, chosen, stamp, n=CHECK_DATES):
    """
    The engine as it stands must rank what the chosen versions' replay
    picked, or the record published beside a list is another recipe's.
    The candidates' signals are checked against the stamp the replay was
    cached under, and leaders.rank() with today's defaults (no override) is
    run on n list dates, half of them dates the results list was made, and
    its top fifteen of each tab held equal to the picks on file.
    """
    import leaders
    if _stamp(P) != stamp:
        raise SystemExit("signals() has changed since the replay: run --prepare, --replay and --report again")
    pit = load_pit(P)
    row = {d: i for i, d in enumerate(P.C.index)}

    def spread(ds, k):
        return [ds[int(x)] for x in np.linspace(0, len(ds) - 1, k)] if ds and k else []
    by = {tab: dict(rows) for tab, (_k, _n, rows) in chosen.items()}
    days = sorted(set(spread(sorted(by["results"]), n // 2) + spread(sorted(by["month"]), n - n // 2)))
    same = total = 0
    for d in days:
        i = row[d]
        cached = os.path.join(CAND_DIR, stamp, f"{i}.pkl")
        if os.path.exists(cached):
            with open(cached, "rb") as f:
                cands = pickle.load(f)
        else:
            # The cache is gone; the stamp above says signals() would give it back.
            cands = S._engine_candidates(P, i)
        filed, growth = _inputs(R, i)
        snap = snapshot_at(pit, i, d.date(), [c["symbol"] for c in cands], sectors, P.RAW)
        got = _tops(leaders.rank(cands, results=filed, sectors=sectors, fundamentals=growth,
                                 benchmark=S.benchmark_at(P, i), snapshot=snap))
        for tab in TABS:
            want = by[tab].get(d, [])
            total += 1
            same += got[tab] == want
            if got[tab] != want:
                print(f"  {d.date()} {tab}: the engine ranks {got[tab][:5]}..., the replay picked {want[:5]}...")
    print(f"engine check: {same} of {total} lists identical on {len(days)} dates")
    if same != total:
        raise SystemExit("backend/leaders.py no longer ranks what the chosen versions picked: run --replay and "
                         "--report again, or write the chosen versions back as the defaults")
    return same, total


def list_record(P, U, tab, key, picks, lab, R=None):
    """One list's record in the schema of every other list in the study
    file, from the chosen version's picks, plus what the lab measured (lab)."""
    import leaders
    hold, exit_pct = TABS[tab]
    exit_pct = VARIANTS[tab][key][0].get("_exit_pct", exit_pct)
    spec = leaders.LISTS[tab]
    if (hold, exit_pct) != (spec["hold_sessions"], spec["exit_pct"]):
        raise SystemExit(f"{tab}: the chosen version holds {hold} sessions with a {exit_pct:g}% line and the "
                         f"engine's plan {spec['hold_sessions']} with {spec['exit_pct']:g}%")
    first = FIRST_HALF[tab]
    ran = S.run_list(P, picks, hold, exit_pct)
    rec = S.with_breakdowns(ran, first=first)
    rec.update(hold_sessions=hold, exit_pct=exit_pct,
               avg_after_costs_pct=round(rec["avg_pct"] - S.ROUND_TRIP_COST_PCT, 2),
               vs_average_stock=S.vs_average_stock(P, U, ran, hold, first=first))
    if tab == "results":
        # Against every liquid company whose results were priced in the same
        # ten sessions: what the list was chosen from.
        dates = pd.DatetimeIndex([d for d, _n in picks])
        _p, pools = S.results_picks(P, U, R, dates)
        rec["vs_reporters"] = S.vs_pool(P, ran, hold, pools)
    rec["market"] = S.by_market(P, ran)
    if tab == "results":
        grid = [P.C.index[i] for i in _dates(P) if i + hold < len(P.C)]
        rec.update({"from": str(picks[0][0].date()),
                    "dates_tried": int(sum(d >= picks[0][0] for d in grid)),
                    "filings": int(len(R)), "companies": int(R["symbol"].nunique()),
                    "window_sessions": leaders.RESULTS_WINDOW, "min_companies": leaders.RESULTS_MIN_POOL})
    rec.update(what=NOTES[tab]["what"], bias=NOTES[tab]["bias"], replay=REPLAY_TEXT)

    # The lab's own two windows, measured again from the same picks: the
    # lab's file and the picks file must be one run.
    measured = lab["records"][tab][key]
    (f0, f1), (s0, s1) = WINDOWS[tab]
    for name, (a, b) in (("first", (f0, f1)), ("second", (s0, s1))):
        if _clean(window_record(P, U, ran, hold, a, b)) != measured[name]:
            raise SystemExit(f"{tab} {key}: {OUT} was not written from {PICKS_FILE}; run --report again")
    last = str(ran["date"].max().date())
    rec["lab"] = {
        "variant": key,
        "overrides": lab["variants"][tab][key]["overrides"],
        "windows": {"first": [f0, f1], "second": [s0, min(s1, last)]},
        "first": measured["first"], "second": measured["second"],
        "before": {k: {"hold_sessions": v["hold_sessions"], "exit_pct": v["exit_pct"],
                       "first": v["first"], "second": v["second"]}
                   for k, v in (lab["before"].get(tab) or {}).items()},
        "rule": lab["rule"]["text"], "min_first_picks": lab["rule"]["min_first_picks"][tab],
        "file": "research/fundamental-ideas-lab.json", "generated": lab["generated"],
    }
    if "reference_2018_22" in measured:
        rec["lab"]["reference_2018_22"] = measured["reference_2018_22"]
    return _clean(rec)


def list_exits(P, tab, picks, hold, exit_pct):
    """The same picks on other exit lines, as research/ideas_study.py runs
    every list: none, half, the list's own, one and a half times; and for
    the lists whose plan marks a target (leaders.target_tested), sold at a
    high as far above the entry as the line is below it, and twice as far."""
    out = {"no exit line": S.describe(S.run_list(P, picks, hold))}
    for alt in sorted({exit_pct / 2, exit_pct, exit_pct * 1.5}):
        out[f"close {alt:g}% under"] = S.describe(S.run_list(P, picks, hold, alt))
    if tab != "results":
        for mult in (1, 2):
            out[f"close {exit_pct:g}% under, target {exit_pct * mult:g}% over"] = S.describe(
                S.run_list(P, picks, hold, exit_pct, target_pct=exit_pct * mult))
    return _clean(out)


def published_overlap(chosen, lab):
    """The three lists' overlap, as --report measured it, with the distinct
    names on the dates all three made a list."""
    by = {tab: rows for tab, (_k, _n, rows) in chosen.items()}
    ov = overlap(by)
    if ov != lab["overlap"]:
        raise SystemExit(f"the overlap in {OUT} is not the chosen versions' picks'; run --report again")
    sets = {tab: {d: set(n) for d, n in rows} for tab, rows in by.items()}
    common = sorted(set.intersection(*(set(v) for v in sets.values())))
    distinct = [len(set().union(*(sets[t][d] for t in sets))) for d in common]
    return {**ov, "distinct in all three": round(float(np.mean(distinct)), 1) if distinct else None,
            "dates in all three": len(common), "what": OVERLAP_TEXT}


def published(P, U, R=None, check=True):
    """{"lists", "exits", "overlap"} for the three lists, from the replay on
    disk and the lab's file. research/ideas_study.py --study calls this too."""
    import leaders
    with open(PICKS_FILE, "rb") as f:
        got = pickle.load(f)
    with open(OUT, encoding="utf-8") as f:
        lab = json.load(f)
    R = S.load_results(P) if R is None else R
    if R is None:
        raise SystemExit(f"no results table at {S.RESULTS_CSV}: the replay cannot be checked")
    chosen = chosen_picks(got, lab)
    if check:
        sectors = S.load_sectors() or _sectors_fallback()
        engine_check(P, R, sectors, chosen, got["stamp"])
    lists, exits = {}, {}
    for tab, (key, _name, picks) in chosen.items():
        rec = list_record(P, U, tab, key, picks, lab, R)
        lists[tab] = rec
        exits[tab] = list_exits(P, tab, picks, rec["hold_sessions"], rec["exit_pct"])
        print(f"\n{tab} ({key}): hold {rec['hold_sessions']}, exit {rec['exit_pct']:g}%")
        print(json.dumps({k: v for k, v in rec.items() if k not in ("by_year", "lab", "what", "bias")}, indent=1))
    return {"lists": lists, "exits": exits, "overlap": published_overlap(chosen, lab),
            "recipe": leaders.RECIPE}


def merged(study, part):
    """The study file with the three lists' records in place of the ones it
    held. The week and momentum records move under `retired`, beside what
    replaced each; the old overlap block is kept as `overlap_before`; every
    other key is left exactly as it was. Running it twice changes nothing."""
    old_lists, old_exits = study.get("lists") or {}, study.get("exits") or {}
    retired = dict(study.get("retired") or {})
    for key, (to, note) in S.RETIRED.items():
        if key in old_lists:
            retired[key] = {"replaced_by": to, "note": note, "record": old_lists[key],
                            "exits": old_exits.get(key)}
    lists = dict(part["lists"])
    lists.update((k, v) for k, v in old_lists.items() if k not in lists and k not in S.RETIRED)
    exits = dict(part["exits"])
    exits.update((k, v) for k, v in old_exits.items() if k not in exits and k not in S.RETIRED)
    before = study.get("overlap_before")
    if before is None and "now" in (study.get("overlap") or {}):
        before = study["overlap"]
    out = {}
    for k, v in study.items():
        if k in ("recipe", "lists_note", "retired", "overlap_before"):
            continue
        if k == "lists":
            out["recipe"] = part["recipe"]
            out["lists_note"] = S.LISTS_NOTE
            out["lists"] = lists
        elif k == "exits":
            out["exits"] = exits
            out["retired"] = retired
        elif k == "overlap":
            out["overlap"] = part["overlap"]
            if before is not None:
                out["overlap_before"] = before
        else:
            out[k] = v
    # A file written before any of these keys existed still gets them.
    for k, v in (("recipe", part["recipe"]), ("lists_note", S.LISTS_NOTE), ("lists", lists),
                 ("exits", exits), ("retired", retired), ("overlap", part["overlap"])):
        out.setdefault(k, v)
    return out


def publish():
    """Write the chosen versions' records into research/ideas-study.json and
    its byte-identical copy beside the code that serves it."""
    P = S.Panel()
    U = P.universe(10)
    with open(S.OUT, encoding="utf-8") as f:
        study = json.load(f)
    out = merged(study, published(P, U))
    text = json.dumps(out, indent=1)
    for path in STUDY_FILES:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print("\nwrote", ", ".join(STUDY_FILES))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    if a.prepare:
        prepare(a.procs)
    if a.replay:
        replay(a.procs)
    if a.report:
        r = report()
        print(json.dumps({"chosen": r["chosen"], "overlap": r["overlap"]}, indent=1))
    if a.publish:
        publish()


if __name__ == "__main__":
    main()
