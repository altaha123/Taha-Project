"""
The fundamental Ideas lab: the three Ideas tabs, replayed point in time.

    python research/fundamental_ideas_lab.py --prepare   # candidates for every list date (slow, once)
    python research/fundamental_ideas_lab.py --replay    # every declared variant, through the engine itself
    python research/fundamental_ideas_lab.py --report    # the tables, the choice, research/fundamental-ideas-lab.json
    python research/fundamental_ideas_lab.py --publish   # the chosen versions' records, into the study file

WHAT IT TESTS
The Ideas page shows three lists (backend/leaders.py): a swing list of market
leaders in industries money is moving into, ranked higher the further they
pulled back over the month, the companies whose
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
every list treats as neutral. A check whose figure cannot be worked out is
skipped, and the long list's figures arrive late: balance sheets are filed in
XBRL from September 2022, return on capital needs a year-end sheet beside
that year's results and the F-score two year-ends running. So --report does
not assume when its checks ran: on every long list date it counts how many of
the companies the engine ranks had each figure (`coverage`), and the list's
note is written from those counts.

THE MONTH LIST'S OWN UNIVERSE
The month list refuses a stock whose industry cannot be ranked, and the
replay hands the engine NSE's industry list as it stands today, so it could
pick only companies still in that list. Those beat the average liquid stock
on their own, which flatters a lead measured against every liquid stock. The
month records therefore also carry the lead over the average liquid stock in
the same industry map (vs_eligible) and how far that average ran ahead of
every liquid stock's on the same dates (member_premium). The liquid stocks in
the map are more than the list could pick: it also refuses an industry with
too few liquid stocks to rank on money flow.

THE CHOICE, DECLARED BEFORE ANY RUN (research/IDEAS-STUDY.md)
Each tab has a handful of declared versions (VARIANTS). One rule picks among
them on the first window, and the second window is then printed whatever it
says:
  month, results  first window 2018-06 to 2021-12, second 2022-01 to the end.
  long            first window 2022-11 to 2024-04, second 2024-05 to the last
                  list date whose year-long hold has completed.
The rule: the highest mean return over the average liquid stock after the
0.49% round trip, among versions with enough picks in the first window and a
positive mean after costs; within 0.05 points, the one with fewer rules. The
lead over the liquid stocks in the industry map and the long list's coverage
are reported beside it and never used to choose.

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
COVERAGE_DIR = os.path.join(DATA, "fil_coverage")
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

# The long list's checks that read the filings (backend/leaders.py's _long
# and _long_floor), as the coverage counts name them and the note prints them.
CHECKS = {"roce_pct": "return on capital", "debt_equity_x": "debt to equity",
          "cfo_to_pat": "cash from operations against profit", "f_score": "the F-score"}
# A check made on fewer than one company in ten, on average over a window,
# did not test the list there.
UNTESTED_PCT = 10.0

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
    sectors = replay_sectors()
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
    # The industry map goes with the picks: the liquid stocks in it, the
    # month list's second bar, are read from the very map the engine was
    # handed (_replay_map).
    with open(PICKS_FILE, "wb") as f:
        pickle.dump({"stamp": stamp, "sets": [n for n, _ in _G["sets"]], "picks": picks,
                     "sectors": sectors}, f)
    return picks


def _sectors_fallback():
    path = os.path.join(HERE, "..", "backend", "nse_industries.csv")
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    return dict(zip(df["Symbol"].astype(str).str.strip(), df["Industry"].astype(str).str.strip()))


def replay_sectors():
    """The industry map the replay hands the engine on every date: NSE's
    list as it stands today (IDEAS_SECTORS_CSV, else the copy in backend/)."""
    return dict(S.load_sectors()) or _sectors_fallback()


def _replay_map(got):
    """The map the replay on file ran with. One written before the map was
    kept beside the picks ran with replay_sectors(), as this does."""
    return got.get("sectors") or replay_sectors()


def eligible_universe(U, sectors):
    """The liquid stocks in the industry map: U, less every company the
    engine cannot place in an industry. rank() reads the map's keys in
    capitals and drops a symbol with an empty industry, and a stock with
    none fails the month list's industry test. More than the list could
    pick: its gate also refuses an industry too small to rank on money flow
    (leaders.FLOW_MIN_MEMBERS liquid stocks), which this does not judge."""
    have = {str(k).upper() for k, v in (sectors or {}).items() if v}
    return U & pd.Series([str(c).upper() in have for c in U.columns], index=U.columns)


# --------------------------------------------------------------------------
# What the picks did
# --------------------------------------------------------------------------

def _avg_stock(P, U, hold):
    """Each date's average stock in the mask U (every liquid stock, or the
    liquid stocks in the industry map), bought at the next open and held.
    Kept per panel and mask; the cache holds both, so neither id can be
    reused while it is kept."""
    key = ("ew", hold, id(P), id(U))
    if key not in _G:
        _G[key] = (P, U, (P.C.shift(-hold) / P.entry - 1).where(U).mean(axis=1))
    return _G[key][2]


def window_record(P, U, df, hold, start, end, eligible=None):
    """One list over one window: how many, how often up, the average before
    and after costs, the middle pick, the worst one in twenty, and the lead
    over the Nifty 500 and over the average liquid stock (Newey-West t).
    With `eligible`, the liquid stocks in the industry map (a mask like U,
    eligible_universe), the lead over their average as well (eligible_lead)."""
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
    if eligible is not None:
        out.update(eligible_lead(P, U, eligible, per, hold))
    return out


def eligible_lead(P, U, eligible, per, hold):
    """`per` (each list date's mean pick) against the average stock in
    `eligible`, after costs too, and member_premium_pct: that average less
    every liquid stock's on the same list dates, the part of the lead over
    the average liquid stock that the stocks in the map earned on their own.
    Per hold, in percent, with Newey-West t's as for vs_avg_stock."""
    lags = max(1, int(np.ceil(hold / STEP)))
    theirs = _avg_stock(P, eligible, hold).reindex(per.index)
    ex = (per - theirs).dropna()
    gap = (theirs - _avg_stock(P, U, hold).reindex(per.index)).dropna()
    t, t_gap = S.newey_west_t(ex.values, lags), S.newey_west_t(gap.values, lags)
    lead = float(ex.mean() * 100) if len(ex) else None
    return {"vs_eligible_pct": None if lead is None else round(lead, 2),
            "vs_eligible_net_pct": None if lead is None else round(lead - S.ROUND_TRIP_COST_PCT, 2),
            "vs_eligible_t": None if t is None else round(t, 2),
            "lists_ahead_of_eligible_pct": round(float((ex > 0).mean() * 100), 1) if len(ex) else None,
            "member_premium_pct": round(float(gap.mean() * 100), 2) if len(gap) else None,
            "member_premium_t": None if t_gap is None else round(t_gap, 2)}


def member_premium(P, U, eligible, df, hold, first):
    """How far the average liquid stock in the industry map (`eligible`)
    ran ahead of the average liquid stock over a list's dates, per hold in
    percent: on the whole record and by half, as S.vs_average_stock splits
    it."""
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    gap = (_avg_stock(P, eligible, hold) - _avg_stock(P, U, hold)).reindex(dates).dropna()

    def one(g):
        return round(float(g.mean() * 100), 2) if len(g) else None
    return {"pct": one(gap), "by_half": {first: one(gap[gap.index < S.SPLIT]),
                                         "2022-26": one(gap[gap.index >= S.SPLIT])}}


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


# --------------------------------------------------------------------------
# When the long list's checks had data: counted, not assumed
# --------------------------------------------------------------------------

COVERAGE_TEXT = ("On every long list date. companies: the liquid companies listed a year that the engine ranks for "
                 "the long list, less the ones it judges as lenders (a company with no filings counts as none, as "
                 "the list reads it); with_filings: how many of them had any filing visible that session; and for "
                 "each check, how many had its figure. most_from is the list date from which a figure was known "
                 "for at least half of them on every list date after (None if not on the last); first_pct and "
                 "second_pct are its mean share known over each window's list dates, and first_half_pct over the "
                 "list dates of the record's first half (first_half), as the page splits the record.")


def _known(v):
    """A figure as the engine reads one (leaders._fig): a finite number."""
    try:
        return bool(np.isfinite(float(v)))
    except (TypeError, ValueError):
        return False


def count_known(firms, snaps):
    """Of `firms`, the ones the long list judges as other than lenders (one
    with no snapshot is no lender, as _long reads it): how many there are,
    how many have filings on file, and how many have each check's figure."""
    rest = [s for s in firms if not (snaps.get(s) or {}).get("is_financial")]
    out = {"companies": len(rest), "with_filings": sum(1 for s in rest if snaps.get(s))}
    for k in CHECKS:
        out[k] = sum(1 for s in rest if _known((snaps.get(s) or {}).get(k)))
    return out


def _long_pool(cands):
    """The candidates the long list ranks: rank()'s pool, the liquid
    universe less the companies listed under a year (refused the list)."""
    import leaders
    return [c["symbol"] for c in cands
            if leaders.in_universe(c["leader_sig"]) and not c["leader_sig"].get("young")]


def _candidates_at(P, i, folder):
    """The replay's candidates on session i, from its cache; rebuilt by the
    engine's own signals() if the file is gone, as engine_check does."""
    path = os.path.join(folder, f"{i}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    if "age" not in S._AGE:
        S._AGE["age"] = S.listing_ages(P)
    return S._engine_candidates(P, i)


def _count_one(i):
    """One list date's counts, on the snapshots _replay_one hands the engine."""
    P = _G["P"]
    firms = _long_pool(_candidates_at(P, i, _G["dir"]))
    snaps = snapshot_at(_G["pit"], i, P.C.index[i].date(), firms, _G["sectors"], P.RAW)
    return {"date": str(P.C.index[i].date()), **count_known(firms, snaps)}


def _coverage_key(P, stamp, sectors, days):
    """What the counts depend on: the candidates (their cache's stamp), the
    sessions and the dates, the industry map (it marks lenders), the four
    tables, and the code that turns those into counts, read as source: this
    file (the 15:30 rule, the pool, the counting), the study helpers it calls
    (ideas_study.py), the engine's universe rule (leaders.py) and the
    snapshot (fund_snapshot.py). A change to any of them counts again."""
    import leaders
    h = hashlib.sha1(repr((stamp, len(P.C), str(P.C.index[0]), str(P.C.index[-1]), days,
                           sorted(sectors.items()), list(CHECKS))).encode())
    code = [os.path.abspath(__file__), S.__file__, leaders.__file__, FS.__file__]
    for path in code + [os.path.join(DATA, n) for n in TABLE_FILES.values()]:
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def long_coverage(P, stamp, sectors, procs=4):
    """count_known() on every long list date, the same dates the record is
    made on, from the replay's own candidates (cached under `stamp`) and the
    filings visible that session. Cached in DATA under everything the counts
    depend on (_coverage_key), so --report and --publish read one count."""
    import multiprocessing as mp
    days = _dates(P)
    path = os.path.join(COVERAGE_DIR, _coverage_key(P, stamp, sectors, days) + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    _G.update(P=P, pit=load_pit(P), sectors=sectors, dir=os.path.join(CAND_DIR, stamp))
    t0 = time.time()
    with mp.get_context("fork").Pool(procs) as pool:
        rows = sorted(pool.map(_count_one, days, chunksize=4), key=lambda r: r["date"])
    print(f"long coverage: {len(rows)} list dates counted in {time.time() - t0:.0f}s")
    os.makedirs(COVERAGE_DIR, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(rows, f)
    os.replace(path + ".tmp", path)
    return rows


def _held_from(rows, k):
    """The first of `rows` (in date order) from which every later one had
    k's figure for at least half its companies, so that "from" that date is
    true; None when the last did not. Read from the end: a check that
    reached half and fell back below it counts from after the fall."""
    out = None
    for r in reversed(rows):
        if 2 * r[k] < r["companies"]:
            break
        out = r["date"]
    return out


def coverage_summary(rows, windows, last=None, half=None):
    """From long_coverage()'s rows: for each check, the list date from which
    its figure was known for at least half the companies (most_from,
    _held_from), and its mean share known, in percent, over each window's
    list dates and over the record's first half. `last`, the last list date
    whose hold had run, ends the second window as it ends the record; `half`
    is (the first half's label, the date it ends before), as the page splits
    the record (FIRST_HALF, S.SPLIT)."""
    label, split = half or (FIRST_HALF["long"], S.SPLIT)
    rows = sorted((r for r in rows if r["companies"]), key=lambda r: r["date"])
    (a0, b0), (a1, b1) = windows
    spans = {"first": [a0, b0], "second": [a1, min(b1, last) if last else b1]}
    inside = {w: [r for r in rows if a <= r["date"] <= b] for w, (a, b) in spans.items()}
    early = [r for r in rows if r["date"] < split]

    def mean_pct(rs, k):
        return round(float(np.mean([r[k] / r["companies"] for r in rs]) * 100), 1) if rs else None
    checks = {k: {"most_from": _held_from(rows, k), "first_pct": mean_pct(inside["first"], k),
                  "second_pct": mean_pct(inside["second"], k), "first_half_pct": mean_pct(early, k)}
              for k in CHECKS}
    return {"from": rows[0]["date"] if rows else None, "to": rows[-1]["date"] if rows else None,
            "windows": spans, "list_dates": {w: len(rs) for w, rs in inside.items()},
            "first_half": {"label": label, "before": split, "list_dates": len(early)}, "checks": checks}


def _last_held(P, hold):
    """The last list date whose hold had run by the end of the data (run_list
    keeps a date only when its last session is on file)."""
    return str(P.C.index[max(i for i in _dates(P) if i + hold < len(P.C))].date())


def coverage_record(P, stamp, sectors, procs=4):
    """The long list's coverage as the lab's file keeps it: the summary,
    what it counts, and every list date's counts."""
    rows = long_coverage(P, stamp, sectors, procs)
    out = coverage_summary(rows, WINDOWS["long"], _last_held(P, TABS["long"][0]), (FIRST_HALF["long"], S.SPLIT))
    cols = ["date", "companies", "with_filings"] + list(CHECKS)
    out.update(what=COVERAGE_TEXT, by_date={"columns": cols, "rows": [[r[c] for c in cols] for r in rows]})
    return out


ELIGIBLE_TEXT = ("The month list refuses a stock with no industry, and the replay handed the engine NSE's list "
                 "as it stands today, so it could pick only companies in that list. Beside the lead over every "
                 "liquid stock, its records measure the lead over the liquid stocks in that list: "
                 "vs_eligible_pct (after the round trip, vs_eligible_net_pct; Newey-West t, vs_eligible_t) and "
                 "lists_ahead_of_eligible_pct, with member_premium_pct, how far their average ran ahead of "
                 "every liquid stock's over the same list dates, per hold. Those stocks are more than the list "
                 "could pick: it also refuses an industry with too few liquid stocks to rank on money flow. "
                 "Reported beside the rule, never used by it.")


def report(procs=4):
    P = S.Panel()
    U = P.universe(10)
    with open(PICKS_FILE, "rb") as f:
        got = pickle.load(f)
    sets = got["sets"]
    picks = got["picks"]
    # The month tab is also measured against the liquid stocks in the
    # industry map the replay ran with: it could pick no others.
    sectors = _replay_map(got)
    elig = {"month": eligible_universe(U, sectors)}
    records = {}
    for tab, (hold, exit_pct) in TABS.items():
        (f0, f1), (s0, s1) = WINDOWS[tab]
        E = elig.get(tab)
        for key, (ov, _n) in VARIANTS[tab].items():
            name = next(n for n in sets if key in n.split("/"))
            p = (picks.get(name) or {}).get(tab) or []
            ex = ov.get("_exit_pct", exit_pct)
            df = S.run_list(P, p, hold, ex)
            rec = {"exit_pct": ex, "hold_sessions": hold,
                   "first": window_record(P, U, df, hold, f0, f1, E),
                   "second": window_record(P, U, df, hold, s0, s1, E),
                   "all": window_record(P, U, df, hold, "1900-01-01", "2100-01-01", E)}
            if tab == "long":
                rec["reference_2018_22"] = window_record(P, U, df, hold, *LONG_REFERENCE)
            records.setdefault(tab, {})[key] = rec
    chosen = choose(records)
    # Before: today's lists on the same windows.
    before = {}
    old = before_picks(P, U)
    for tab, keys in (("month", ("week", "month")), ("results", ("results",)), ("long", ("long", "momentum"))):
        (f0, f1), (s0, s1) = WINDOWS[tab]
        E = elig.get(tab)
        for k in keys:
            hold, ex = S.LISTS[k] if k in S.LISTS else S.RESULTS_LIST[1:]
            df = S.run_list(P, old.get(k) or [], hold, ex)
            before.setdefault(tab, {})[k] = {"exit_pct": ex, "hold_sessions": hold,
                                             "first": window_record(P, U, df, hold, f0, f1, E),
                                             "second": window_record(P, U, df, hold, s0, s1, E),
                                             "all": window_record(P, U, df, hold, "1900-01-01", "2100-01-01", E)}
    best_set = {tab: next((n for n in sets if (chosen.get(tab) or "-") in n.split("/")), None) for tab in TABS}
    ov = overlap({tab: (picks.get(best_set[tab]) or {}).get(tab) or [] for tab in TABS if best_set[tab]})
    grid = P.C.index[_dates(P)]
    share = (elig["month"].sum(axis=1) / U.sum(axis=1).replace(0, np.nan)).reindex(grid)
    result = {"generated": dt.date.today().isoformat(), "windows": WINDOWS, "long_reference": LONG_REFERENCE,
              "round_trip_cost_pct": S.ROUND_TRIP_COST_PCT, "rule": {
                  "min_first_picks": MIN_FIRST_PICKS, "tie_pp": TIE_PP,
                  "text": ("Highest first-window mean lead over the average liquid stock, among versions with "
                           "enough picks and a positive mean after a 0.49% round trip; within 0.05 points the "
                           "one with fewer rules. The second window is printed whatever it shows.")},
              "variants": {t: {k: {"overrides": v[0], "rules": v[1]} for k, v in vs.items()}
                           for t, vs in VARIANTS.items()},
              "records": records, "before": before, "chosen": chosen, "overlap": ov,
              "eligible": {"month": {"companies_in_map": len(sectors),
                                     "share_of_liquid_pct": round(float(share.mean() * 100), 1),
                                     "what": ELIGIBLE_TEXT}},
              "coverage": {"long": coverage_record(P, got["stamp"], sectors, procs)}}
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
# What flatters each list's record, as the page prints it under "how". A
# {name} is filled at publish time (bias_text) with what the same run
# measured, so no figure is typed here; what each list is, is written from
# its recipe (what_text).
BIAS = {
    "month": ("Pledges, deliveries and orders have no history to replay: they were unknown here, which the list "
              "counts as neutral, and the live list reads them. {members} Quarterly filings start in "
              "{quarters_from} and cover companies listed today; a stock with none is never refused for it, and "
              "a revised quarter is seen from the revision's date."),
    "results": ("The results tables hold companies listed today, so one delisted after a bad quarter is missing, "
                "and a revised quarter is seen from the revision's date with the revised figures. {reporters}"),
    "long": ("{checks} Pledges and holdings have no history and were unknown throughout. The tables hold "
             "companies listed today, and a revised filing is seen from the revision's date."),
}


def _month_year(iso):
    return dt.date.fromisoformat(str(iso)[:10]).strftime("%B %Y")


def _day(iso):
    """A list date as the page writes one: 21 May 2024."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f"{d.day} {d.strftime('%B %Y')}"


def _pc(x):
    """A share to the decimal the lab keeps it to: 0.4, 85.9, 86."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _signed(x):
    """A lead as the page prints one (picks.js signed(v, 2)): +0.55%, \u22120.13%."""
    return ("+" if x > 0 else "\u2212" if x < 0 else "") + f"{abs(x):.2f}%"


def _and(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _have(x):
    return x is not None and bool(np.isfinite(x))


# --------------------------------------------------------------------------
# What each list is: its recipe in words, from the dictionary the engine
# reads (leaders.MONTH, RESULTS, LONG, as _recipe sets them for a version),
# so a threshold changed in backend/leaders.py changes the words with it.
# --------------------------------------------------------------------------

def _calm():
    """The volatility gate: leaders.CALM_FLOOR is the share of liquid stocks
    it leaves out, the most volatile."""
    import leaders
    return "the most volatile " + ("fifth" if leaders.CALM_FLOOR == 0.2 else f"{leaders.CALM_FLOOR * 100:.0f}%")


def _parts(mix, words):
    """A score's parts in words, in the order of its weights; a part weighted
    zero is not ranked on and is left out."""
    return [words[k] for k, w in mix.items() if w and w > 0]


def _weighted(mix, words):
    """"half on a, a quarter on b and a quarter on c", or "on a" alone."""
    parts = [(w, words[k]) for k, w in mix.items() if w and w > 0]
    if len(parts) == 1:
        return "on " + parts[0][1]
    share = {0.5: "half", 0.25: "a quarter", 0.75: "three quarters"}
    return _and([f"{share.get(round(w, 4)) or f'{w * 100:.0f}%'} on {t}" for w, t in parts])


def _what_month(cfg):
    pull = [w for k, w in (("dip21", "the month's"), ("dip", "the week's")) if (cfg.get("pull_mix") or {}).get(k)]
    top = cfg["sector_top"]
    # The gate compares the industry's rank with its count (leaders._month).
    gate = ((f"in an industry ranked in the top {'half' if top == 0.5 else f'{top * 100:.0f}%'} on money "
             "flow, ") if cfg["sector_gate"] else "")
    rules = ((["no loss and no fall in profit last quarter"] if cfg["profit_guard"] else [])
             + ([f"no results the market sold (more than {abs(cfg['bad_reaction']) * 100:.0f}% under the average "
                 f"stock that day) in the last {cfg['result_lookback']} sessions"]
                if cfg["result_guard"] else [])
             + [f"no more than {cfg['pledge_max']:g}% of the company pledged"])
    words = {"pull": _and(pull or ["the"]) + " pullback", "high": "closeness to the 52-week high",
             # A lender's margin is not read (leaders._snapshot_pcts).
             "fundmom": "the last quarter's sales and margin growth (a lender's sales alone)",
             "secflow": "the industry's money flow", "catalyst": "a live catalyst"}
    return (f"Market leaders (a leader score of {cfg['leader_floor'] * 100:.0f} or more out of 100) in an uptrend and "
            f"outside {_calm()}, {gate}with " + _and(rules) + ". Ranked on " + _and(_parts(cfg["mix"], words))
            + f"; at most {cfg['sector_cap']} from one industry.")


def _what_results(cfg):
    import leaders
    under = (1 - leaders.RESULTS_SMA200_FLOOR) * 100
    floor = {"sma200_85": f", nor more than {under:.0f}% under the 200-day average",
             "sma50": ", nor under the 50-day average"}.get(cfg["floor"], "")
    # leaders._result_quality: a lender's other income, operating profit and
    # cash flow are its business, so it is not tested on them.
    real = ((f" and showed real growth: sales up {cfg['rev_min']:g}% or more on a year ago, a profit and an "
             "operating profit, both up on a year ago (one-off items left out of the operating profit), other "
             f"income no more than {cfg['other_income_max']:g}% and an exceptional gain no more than "
             f"{cfg['exceptional_max'] * 100:.0f}% of profit before tax, and cash from operations positive in the "
             "last full year. A lender is tested on its sales, profit and exceptional gain only")
            if cfg["quality_gate"] else "")
    words = {"reaction": "that session's move less the average liquid stock's", "volume": "the volume behind it",
             "growth": "the growth"}
    return (f"Liquid companies whose quarterly results were first priced in the last {leaders.RESULTS_WINDOW} "
            f"sessions{real}. Not already up more than {cfg['chase_max'] * 100:.0f}% on the day{floor}. Ranked "
            + _weighted(cfg["mix"], words) + f"; at most {cfg['sector_cap']} from one industry. A list is made "
            f"only when {cfg['min_qualified']} or more pass every test.")


def _what_long(cfg):
    de = "equity" if cfg["de_max"] == 1 else f"{cfg['de_max']:g} times equity"
    # leaders._long_floor: a lender is judged on its return on equity alone,
    # and a negative equity fails every company.
    floors = ((f", a return on capital of {cfg['roce_min']:g}% or more, cash from operations positive and at "
               f"least {cfg['cfo_to_pat_min']:g} times profit, debt no more than {de} (a lender instead: a return "
               f"on equity of {cfg['roe_min_fin']:g}% or more) and positive shareholders' equity")
              if cfg["floors"] else "")
    ceiling = ((f", and a P/E of {cfg['pe_max']:g} or under unless its PEG is {cfg['peg_escape']:g} or under on "
                f"three-year profit growth of {cfg['cagr_escape']:g}% a year or more")
               if cfg["valuation_ceiling"] else "")
    words = {"quality": "quality", "compounding": "three-year compounding", "governance": "governance",
             "valuation": "valuation against its own industry", "trendq": "the year-long trend"}
    return (f"Above the 200-day average and outside {_calm()}, a profit over the last four quarters, an F-score "
            f"of {cfg['f_score_min']:g} or more, no more than {cfg['pledge_max']:g}% pledged{floors}{ceiling}. "
            "Ranked on " + _and(_parts(cfg["mix"], words)) + f"; at most {cfg['sector_cap']} from one industry.")


WHAT = {"month": _what_month, "results": _what_results, "long": _what_long}


def what_text(tab, cfg):
    """What a list is, as the page prints it under "how", from the recipe
    `cfg` (a version's, _recipe)."""
    return WHAT[tab](cfg)


# --------------------------------------------------------------------------
# What flatters each record, with what the same run measured
# --------------------------------------------------------------------------

def _lead(lead):
    """A lead in vs_average_stock's shape, as the page writes its own:
    "+0.55% a pick (2017-21 +1.05%, 2022-26 +0.04%)"."""
    halves = [f"{k} {_signed(v['excess_pct'])}" for k, v in (lead.get("by_half") or {}).items()
              if v and _have(v.get("excess_pct"))]
    return f"{_signed(lead['excess_pct'])} a pick" + (f" ({', '.join(halves)})" if halves else "")


def month_members(premium, lead=None, gated=True):
    """The month note's sentences on the industry map, with what the same
    run measured: `premium`, how far the average liquid stock in the map ran
    ahead of the average liquid stock on the list's dates (member_premium()
    ["pct"]), and `lead`, the list against the liquid stocks in the map
    (vs_eligible_stock: the record's and each half's). `gated`: the version
    refuses a stock with no industry, so it could pick no other."""
    said = ("Industries are NSE's list as it stands today, and a stock without one fails the industry test, so "
            "the replay could pick only companies in that list." if gated else
            "Industries are NSE's list as it stands today, and this version does not need one.")
    parts = []
    if _have(premium):
        parts.append("the liquid stocks in that list " + (
            f"did better than the average liquid stock by {premium:.2f}%" if premium >= 0.005 else
            f"did worse than the average liquid stock by {-premium:.2f}%" if premium <= -0.005 else
            "did as well as the average liquid stock"))
    if lead and _have(lead.get("excess_pct")):
        parts.append(f"the list's lead over {'them' if parts else 'the liquid stocks in that list'} was "
                     + _lead(lead))
    return said + (" On the same days " + ", and ".join(parts) + "." if parts else "")


def reporters_text(lead):
    """The results note's sentence on vs_reporters, the list against every
    liquid company whose results were priced in the same sessions."""
    import leaders
    if not lead or not _have(lead.get("excess_pct")):
        return ""
    return (f"Against every liquid company whose results were priced in the same {leaders.RESULTS_WINDOW} "
            f"sessions, which shares that bias, the list's lead was {_lead(lead)}.")


def _untested(pct):
    """A mean share known under UNTESTED_PCT: the check did not test the
    list there."""
    return _have(pct) and pct < UNTESTED_PCT


def _early_checks(cov, who):
    """The record's first half (before S.SPLIT, cov["first_half"]): the
    checks known for almost none of the companies there, with their shares,
    and, when that was every check, what the list was ranked on instead."""
    c = cov["checks"]
    low = [k for k in sorted(CHECKS, key=lambda k: c[k]["most_from"] or "9999")
           if _untested(c[k].get("first_half_pct"))]
    if not low:
        return ""
    shares = _and([f"{CHECKS[k]} {'was known ' if n == 0 else ''}for {_pc(c[k]['first_half_pct'])}%"
                   + (" on average" if n == 0 else "") for n, k in enumerate(low)])
    # The checks' figures are three of quality's four inputs and governance
    # has no history; compounding and valuation read the income tables,
    # which begin in 2018. With every check this rare, the trend is most of
    # what the list could rank on.
    so = ("so there the list was ranked mostly on its trend and the growth in its filed income"
          if len(low) == len(CHECKS) else
          "so " + ("that check was" if len(low) == 1 else "those checks were") + " effectively untested there")
    return f"In {cov['first_half']['label']}, of {who} {shares}, {so}."


def _held_checks(cov, who):
    """From when each check had its figure for at least half the companies
    on every later list date (most_from), and the ones short of half on the
    last list date, which have no such date."""
    c = cov["checks"]
    held = sorted((k for k in CHECKS if c[k]["most_from"]), key=lambda k: c[k]["most_from"])
    out = []
    if held:
        out.append(f"At least half of {who} had " + _and([
            f"{CHECKS[k]} from {_day(c[k]['most_from'])}{' on' if n == 0 else ''}" for n, k in enumerate(held)])
            + ".")
    never = [CHECKS[k] for k in CHECKS if not c[k]["most_from"]]
    if never:
        out.append(f"Fewer than half of {'them' if held else who} had {_and(never)} on the last list date, "
                   f"{_day(cov['to'])}.")
    return " ".join(out)


def _chosen_window(cov):
    """The checks known for almost none of the companies in the window that
    chose the version, with each one's share in the window after it."""
    c = cov["checks"]
    low = [k for k in sorted(CHECKS, key=lambda k: c[k]["most_from"] or "9999") if _untested(c[k]["first_pct"])]
    if not low:
        return ""
    (a, b), (s0, s1) = cov["windows"]["first"], cov["windows"]["second"]
    said = []
    for n, k in enumerate(low):
        later = "" if not _have(c[k]["second_pct"]) else (
            f" ({_pc(c[k]['second_pct'])}% from {_month_year(s0)} to {_month_year(s1)})" if n == 0 else
            f" ({_pc(c[k]['second_pct'])}% then)")
        said.append(f"{CHECKS[k]} {'was known ' if n == 0 else ''}for {_pc(c[k]['first_pct'])}%"
                    + (" of them on average" if n == 0 else "") + later)
    return (f"From {_month_year(a)} to {_month_year(b)}, the period this version was chosen on, " + _and(said)
            + ", so " + ("that check was" if len(low) == 1 else "those checks were") + " effectively untested there.")


def long_checks(cov):
    """The long note's sentences on its checks, from coverage_summary(), in
    the order the record runs: the first half, when each check had its
    figure for most of the companies the list ranks, and the window that
    chose the version. Every figure is cov's."""
    who = "the liquid companies the list ranks, lenders aside,"
    text = ["A check is made only where its figure is known.", _early_checks(cov, who)]
    text.append(_held_checks(cov, "them" if text[-1] else who))
    text.append(_chosen_window(cov))
    return " ".join(t for t in text if t)


def _recipe(tab, key):
    """One declared version's settings as _apply hands them to the engine,
    on the engine's defaults as they stand now."""
    import leaders
    cfg = dict(getattr(leaders, tab.upper()))
    for k, v in list(SPEC[tab].items()) + list(VARIANTS[tab][key][0].items()):
        if not k.startswith("_"):
            cfg[k] = v
    return cfg


def bias_text(tab, key, rec, coverage=None, R=None):
    """What flatters a list, as the page prints it under "how": its note,
    with what this run measured put in where the note needs a figure (the
    month record's member_premium and vs_eligible_stock and the year of the
    first quarterly filing the replay could see, in R; the results record's
    vs_reporters; the long list's coverage)."""
    if tab == "month":
        gated = _recipe(tab, key).get("sector_gate", True)
        members = month_members(rec["member_premium"]["pct"], rec.get("vs_eligible_stock"), gated)
        return BIAS[tab].format(members=members, quarters_from=int(R["d0"].min().year))
    if tab == "results":
        return BIAS[tab].format(reporters=reporters_text(rec.get("vs_reporters"))).strip()
    return BIAS[tab].format(checks=long_checks(coverage))


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


def list_record(P, U, tab, key, picks, lab, R=None, eligible=None, coverage=None):
    """One list's record in the schema of every other list in the study
    file, from the chosen version's picks, plus what the lab measured (lab).
    The month list is also measured against `eligible`, the liquid stocks in
    the industry map (eligible_universe), and the long list's note is
    written from `coverage` (coverage_record)."""
    import leaders
    if (tab == "month" and (eligible is None or R is None)) or (tab == "long" and coverage is None):
        raise ValueError(f"{tab}: the month record needs the liquid stocks in the industry map and the results "
                         "table, the long one its coverage")
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
    if tab == "month":
        # Against the liquid stocks in the industry map, which ran ahead of
        # every liquid stock on their own (THE MONTH LIST'S OWN UNIVERSE).
        rec["vs_eligible_stock"] = S.vs_average_stock(P, eligible, ran, hold, first=first)
        rec["member_premium"] = member_premium(P, U, eligible, ran, hold, first)
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
    rec.update(what=what_text(tab, _recipe(tab, key)), bias=bias_text(tab, key, rec, coverage, R),
               replay=REPLAY_TEXT)

    # The lab's own two windows, measured again from the same picks: the
    # lab's file and the picks file must be one run.
    measured = lab["records"][tab][key]
    (f0, f1), (s0, s1) = WINDOWS[tab]
    for name, (a, b) in (("first", (f0, f1)), ("second", (s0, s1))):
        got = window_record(P, U, ran, hold, a, b, eligible if tab == "month" else None)
        if _clean(got) != measured[name]:
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
    if tab == "long":
        # When its checks had data, as the note says it (the dates' counts
        # stay in the lab's file).
        rec["lab"]["coverage"] = {k: v for k, v in coverage.items() if k != "by_date"}
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
        engine_check(P, R, replay_sectors(), chosen, got["stamp"])
    # The liquid stocks in the industry map the replay ran with, and the long
    # list's coverage counted again: the notes print those figures, so they
    # must be the ones on disk now.
    sectors = _replay_map(got)
    eligible = eligible_universe(U, sectors)
    coverage = coverage_record(P, got["stamp"], sectors)
    if coverage != (lab.get("coverage") or {}).get("long"):
        raise SystemExit(f"the long list's coverage in {OUT} is not what the data on disk give; run --report again")
    lists, exits = {}, {}
    for tab, (key, _name, picks) in chosen.items():
        rec = list_record(P, U, tab, key, picks, lab, R, eligible=eligible, coverage=coverage)
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
            out["lists_note"] = S.LISTS_NOTE.format(recipe=part["recipe"])
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
    for k, v in (("recipe", part["recipe"]), ("lists_note", S.LISTS_NOTE.format(recipe=part["recipe"])), ("lists", lists),
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


def print_measures(r):
    """What --report measures beside the rule: the month tab against the
    liquid stocks in the industry map, and when the long list's checks had
    data."""
    cols = ("vs_avg_stock_pct", "vs_eligible_pct", "vs_eligible_t", "member_premium_pct")
    print("\nmonth tab, first window | second:  " + "  ".join(cols))
    for group in ("records", "before"):
        for k, rec in r[group]["month"].items():
            cells = ["  ".join(str((rec[w] or {}).get(c)) for c in cols) for w in ("first", "second")]
            print(f"  {group:8s}{k:7s}" + " | ".join(cells))
    cov = r["coverage"]["long"]
    half = cov["first_half"]
    print(f"\nlong list's checks, {cov['from']} to {cov['to']}: known for half from, and mean % known over "
          f"{half['label']} and the first and second windows ({half['list_dates']}, {cov['list_dates']['first']} "
          f"and {cov['list_dates']['second']} list dates)")
    for k, c in cov["checks"].items():
        print(f"  {k:14s}{c['most_from']}  {c['first_half_pct']}%  {c['first_pct']}%  {c['second_pct']}%")


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
        r = report(a.procs)
        print(json.dumps({"chosen": r["chosen"], "overlap": r["overlap"]}, indent=1))
        print_measures(r)
    if a.publish:
        publish()


if __name__ == "__main__":
    main()
