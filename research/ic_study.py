#!/usr/bin/env python3
"""
Offline information-coefficient study.

WHAT IT IS FOR
factor_lab.py measures factors from banked point-in-time data, which is the
right way and takes months to accumulate. This script answers the same
question today, by replaying the engine over price history that already
exists. It is how the engine was measured for the first time.

It is deliberately OUTSIDE the web service. Nothing here runs in production,
nothing here is imported by the app, and it may be as slow as it likes.

METHOD, AND WHY EACH PIECE OF IT
  · The score is computed on a frame TRUNCATED at each evaluation date. No bar
    after the date is visible to the calculation. This is the whole game — an
    indicator library that peeks one bar ahead produces a beautiful backtest
    and loses money.
  · Forward return is measured against the benchmark over the identical
    window, so what comes out is skill rather than the market.
  · The statistic is the cross-sectional Spearman rank IC, because the engine
    orders a list rather than forecasting a price, and that is the measure
    which asks whether the ordering beat shuffling.
  · Every check is scored separately as well as the total, because a score
    built from twelve collinear checks has one idea in it and the only way to
    see that is to look at the checks individually and at their correlation.

READING THE RESULT
A real, professionally traded equity factor runs an IC of 0.03 to 0.05 — right
about 52% of the time. Above 0.10 sustained is usually a bug: a lookahead
leak, a survivorship filter, or a factor fitted to the sample it is measured
on. And an IC from a handful of overlapping windows inside one market regime
is not a finding, it is a number.

USAGE
    python research/ic_study.py --fetch          # pull candles from the API
    python research/ic_study.py --study          # IC by horizon
    python research/ic_study.py --decompose      # per-check IC and collinearity

Data comes from the project's own /chart endpoint rather than a vendor,
because that is what the engine itself is fed and any difference between the
two would be measuring the wrong thing.
"""

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))

API = os.environ.get("ALTAHA_API", "https://taha-project.onrender.com")
CACHE = os.environ.get("ALTAHA_RESEARCH_DIR", os.path.join(HERE, ".cache"))
BENCH = "NIFTYBEES"

# Below this a stock is not one the engine is meant for, and including it
# measures the data provider rather than the signal.
MIN_TURNOVER = 1e7          # ₹1 crore median daily traded value
MIN_BARS = 230
WARMUP = 200                # EMA200 needs a run-up before it means anything


def _get(path, timeout=45):
    req = urllib.request.Request(API + path,
                                 headers={"User-Agent": "altaha-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch(sample=600, workers=6, seed=7):
    """Pull daily candles for a fixed random sample of the NSE universe."""
    import random
    os.makedirs(CACHE, exist_ok=True)
    rows = _get("/universe")["rows"]
    random.Random(seed).shuffle(rows)
    syms = [r["s"] for r in rows[:sample]] + [BENCH]

    out, lock, done = {}, threading.Lock(), [0]

    def one(sym):
        try:
            d = _get(f"/chart?ticker={sym}&range=1D")
            c = d.get("candles") or []
            if len(c) >= MIN_BARS:
                with lock:
                    out[sym] = c
        except Exception:
            pass
        with lock:
            done[0] += 1
            if done[0] % 50 == 0:
                print(f"  {done[0]}/{len(syms)} — {len(out)} usable", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, syms))
    path = os.path.join(CACHE, "candles.json")
    json.dump(out, open(path, "w"))
    print(f"{len(out)} symbols in {time.time() - t0:.0f}s -> {path}")
    return path


def _load():
    import pandas as pd
    raw = json.load(open(os.path.join(CACHE, "candles.json")))

    def frame(rows):
        df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close",
                                         "e20", "e50", "bu", "bl", "Volume"])
        df = df[["t", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        df.index = pd.to_datetime(df["t"], unit="s").dt.normalize()
        return df.drop(columns=["t"])

    frames = {s: frame(r) for s, r in raw.items()}
    bench = frames.pop(BENCH, None)
    if bench is None:
        raise SystemExit(f"no {BENCH} in the cache — rerun with --fetch")
    keep = {s: d for s, d in frames.items()
            if len(d) >= MIN_BARS and (d["Close"] * d["Volume"]).median() >= MIN_TURNOVER}
    return keep, bench


def _spearman(x, y):
    import numpy as np
    from scipy.stats import rankdata            # research only, not shipped
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def study(horizons=(10, 21), step=10):
    import numpy as np
    import pandas as pd
    from engine import technical_score

    keep, bench = _load()
    master = bench.index
    print(f"{len(keep)} liquid symbols · {len(master)} sessions "
          f"{master[0].date()} -> {master[-1].date()}")

    for H in horizons:
        print(f"\n=== horizon {H} sessions ===")
        per_date, allrows = [], []
        for ti in range(WARMUP, len(master) - H, step):
            d0, d1 = master[ti], master[ti + H]
            b0, b1 = bench["Close"].asof(d0), bench["Close"].asof(d1)
            if not (b0 and b1):
                continue
            bret = b1 / b0 - 1.0
            recs = []
            for s, df in keep.items():
                sub = df.loc[:d0]
                if len(sub) < WARMUP:
                    continue
                try:
                    out = technical_score(sub)
                except Exception:
                    continue
                fut = df.loc[:d1]
                if len(fut) == len(sub):
                    continue
                r = fut["Close"].iloc[-1] / sub["Close"].iloc[-1] - 1.0
                rec = {"sym": s, "score": out["score"], "excess": r - bret}
                for c in out["checks"]:
                    rec["chk::" + c["name"]] = c["points"]
                recs.append(rec)
            if len(recs) < 40:
                continue
            t = pd.DataFrame(recs)
            ic = _spearman(t["score"], t["excess"])
            q = t["score"].rank(pct=True)
            top = t.loc[q > 0.8, "excess"].mean() * 100
            bot = t.loc[q <= 0.2, "excess"].mean() * 100
            per_date.append(ic)
            t["date"] = d0
            allrows.append(t)
            print(f"  {d0.date()}  n={len(t):4d}  IC={ic:+.3f}  "
                  f"spread={top - bot:+6.2f}%  (index {bret * 100:+.2f}%)")

        if per_date:
            a = np.array(per_date)
            print(f"  ---- mean IC {a.mean():+.3f} · sd {a.std(ddof=1):.3f} over "
                  f"{len(a)} OVERLAPPING dates. Overlap makes any t-statistic "
                  f"optimistic; this is a point estimate, not a test.")
            pd.concat(allrows, ignore_index=True).to_csv(
                os.path.join(CACHE, f"rows_H{H}.csv"), index=False)


def decompose(H=10):
    """Per-check IC, and how much of the score is one idea wearing many hats."""
    import numpy as np
    import pandas as pd

    path = os.path.join(CACHE, f"rows_H{H}.csv")
    if not os.path.exists(path):
        raise SystemExit(f"run --study first ({path} missing)")
    df = pd.read_csv(path)
    checks = [c for c in df.columns if c.startswith("chk::")]

    out = []
    for c in checks:
        ics = []
        for _, g in df.groupby("date"):
            if g[c].nunique() < 2:
                continue
            ic = _spearman(g[c], g["excess"])
            if ic is not None:
                ics.append(ic)
        if ics:
            out.append({"check": c.replace("chk::", ""),
                        "max_pts": int(df[c].max()),
                        "mean_IC": round(float(np.mean(ics)), 3),
                        "dates_positive_pct": round(100 * float(np.mean(np.array(ics) > 0)))})
    print(pd.DataFrame(out).sort_values("mean_IC", ascending=False).to_string(index=False))

    corr = df[checks].corr(method="spearman")
    corr.index = [c.replace("chk::", "")[:26] for c in corr.index]
    corr.columns = [c.replace("chk::", "")[:11] for c in corr.columns]
    print("\n--- rank correlation between the checks ---")
    print(corr.round(2).to_string())

    v = df[checks].values.astype(float)
    v = (v - v.mean(0)) / (v.std(0) + 1e-9)
    ev = np.linalg.eigvalsh(np.corrcoef(v, rowvar=False))[::-1]
    ev = ev / ev.sum()
    print(f"\n1st principal component      {ev[0] * 100:.1f}% of variance")
    print(f"first three components       {ev[:3].sum() * 100:.1f}%")
    print(f"effective degrees of freedom {1 / np.sum(ev ** 2):.1f} of {len(checks)}")
    print("\nA score assembled from checks that move together has the predictive "
          "ceiling of however many independent ideas are actually in it.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--study", action="store_true")
    ap.add_argument("--decompose", action="store_true")
    ap.add_argument("--sample", type=int, default=600)
    ap.add_argument("--horizon", type=int, default=10)
    a = ap.parse_args()
    if a.fetch:
        fetch(sample=a.sample)
    if a.study:
        study()
    if a.decompose:
        decompose(a.horizon)
    if not (a.fetch or a.study or a.decompose):
        ap.print_help()
