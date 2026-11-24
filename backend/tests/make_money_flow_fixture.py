"""
Regenerate frontend/tests/fixtures/money-flow.json and money-flow-sectors.json.

Same rule as the other make_*_fixture.py files: the browser test reads a
payload the real backend produced, so a key renamed in money_flow.py changes
the fixture and the page test fails, instead of passing against a hand-typed
JSON that still carries the old name.

    python backend/tests/make_money_flow_fixture.py

EVERYTHING IN IT IS INVENTED. All 22 sectors of the classification are there,
with made-up companies (AUT1, AUT2, ...), fourteen fortnights of FPI flow, 300
sessions of index closes, 100 sessions of delivery panels, 60 sessions of
FII/DII and a handful of deals, all from a seeded random generator. Nothing in
the fixture is a statement about any sector or company, and nothing here
should ever be shown as market data.

A few things are planted, because the browser test asserts them:

  · Information Technology   FPIs buying more every fortnight, the index
                             pulling away from the Nifty: rank 1, Leading.
  · Metals & Mining          the mirror image: last, Lagging.
  · Fast Moving Consumer     FPIs sold for five fortnights and bought in the
    Goods                    sixth: "Turned to buying".
  · ITE1                     delivery and volume up for five sessions and a
                             fund buying in a bulk deal: top of IT's list.
  · Diversified, Forest      one company each, so they are not scored and say
    Materials, Utilities     why.
"""

import datetime as dt
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd

import money_flow as M
import money_flow_config as C
import money_flow_store as store

TODAY = dt.date(2026, 11, 20)
OUT = ROOT / "frontend" / "tests" / "fixtures"
SMALL = {"Diversified": 1, "Forest Materials": 1, "Utilities": 4}
IT, FMCG, METAL = "Information Technology", "Fast Moving Consumer Goods", "Metals & Mining"


def sessions(n, end=TODAY):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(days))


def fortnights(n):
    out, y, m, half = [], TODAY.year, TODAY.month, 1
    while len(out) < n:
        if half == 1:
            out.append((dt.date(y, m, 1), dt.date(y, m, 15)))
            half = 2
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        else:
            last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
            out.append((dt.date(y, m, 16), last))
            half = 1
    return list(reversed(out))


def members():
    out = {}
    for spec in C.SECTORS:
        tag = "".join(ch for ch in spec["short"].upper() if ch.isalpha())[:3]
        # Two letters make no ticker, and Construction already has CON.
        tag = {"Information Technology": "ITE", "Consumer Services": "CSV"}.get(spec["name"], tag)
        assert not any(k.startswith(tag) for k in out), tag
        for n in range(1, SMALL.get(spec["name"], 8) + 1):
            out["%s%d" % (tag, n)] = spec["name"]
    return out


def build():
    rng = random.Random(20261120)
    mem = members()
    # --- FPI: fourteen fortnights per sector ---------------------------------
    rows = []
    for spec in C.SECTORS + [{"name": n} for n in C.NOT_SECTORS]:
        name = spec["name"]
        size = rng.choice([8000, 20000, 60000, 150000, 400000]) * (5 if name == "Financial Services" else 1)
        auc, drift = float(size), rng.uniform(-0.004, 0.004)
        for i, (start, end) in enumerate(fortnights(14)):
            net = auc * (drift + rng.gauss(0, 0.006))
            if name == IT:
                net = 300.0 * (i + 1) ** 1.3
            elif name == METAL:
                net = -260.0 * (i + 1) ** 1.3
            elif name == FMCG:
                net = 700.0 if i == 13 else -200.0 - 40.0 * (i % 5)
            auc += net
            rows.append({"sector": name, "period_start": start.isoformat(), "period_end": end.isoformat(),
                         "equity_net_inr_cr": round(net), "equity_net_usd_mn": round(net / 9.5),
                         "total_net_inr_cr": round(net), "equity_auc_inr_cr": round(auc)})
    store.upsert_fpi(rows, source_url="fixture")

    # --- indices: 300 sessions -----------------------------------------------
    names = [C.BENCHMARK] + [s["index"] for s in C.SECTORS if s["index"]] + [t["index"] for t in C.THEMES]
    level = {n: 1000.0 for n in names}
    lean = {n: rng.uniform(-0.0007, 0.0007) for n in names}
    lean[C.BENCHMARK] = 0.0
    days = sessions(300)
    for i, day in enumerate(days):
        market = 0.0004 + rng.gauss(0, 0.006)
        for n in names:
            own = 0.0 if n == C.BENCHMARK else lean[n] * (0.4 + 1.2 * i / 300.0) + rng.gauss(0, 0.0035)
            if n == "NIFTY IT":
                own = 0.0006 + 0.000006 * i + rng.gauss(0, 0.001)
            if n == "NIFTY METAL":
                own = -0.0006 - 0.000006 * i + rng.gauss(0, 0.001)
            level[n] *= 1.0 + market + own
        store.upsert_index_day(day, {n: round(v, 2) for n, v in level.items()})

    # --- FII / DII: 60 sessions ----------------------------------------------
    flows = {}
    for i, day in enumerate(sessions(60)):
        fii = rng.gauss(400 + 30 * i, 2600)
        dii = -0.55 * fii + rng.gauss(500, 900)
        flows[day.isoformat()] = {"fii": {"buy": round(14000 + max(fii, 0)), "sell": round(14000 + max(-fii, 0)), "net": round(fii)},
                                  "dii": {"buy": round(11000 + max(dii, 0)), "sell": round(11000 + max(-dii, 0)), "net": round(dii)}}
    store.upsert_flows(flows)

    # --- the delivery panels: 100 sessions -----------------------------------
    idx = pd.to_datetime(sessions(100))
    cols = sorted(mem)
    close = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    deliv = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    qty = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    for sym in cols:
        tilt = {IT: 0.0025, METAL: -0.0025}.get(mem[sym], rng.uniform(-0.0015, 0.0015))
        steps = np.array([tilt + rng.gauss(0, 0.012) for _ in range(100)])
        close[sym] = rng.uniform(80, 2400) * np.cumprod(1.0 + steps)
        base_d, base_q = rng.uniform(28, 62), rng.uniform(2e5, 4e6)
        deliv[sym] = [min(95.0, max(5.0, base_d + rng.gauss(0, 4))) for _ in range(100)]
        qty[sym] = [max(1000.0, base_q * (1.0 + rng.gauss(0, 0.25))) for _ in range(100)]
    last5 = idx[-5:]
    close.loc[last5, "ITE1"] = close.loc[idx[-6], "ITE1"] * np.cumprod(np.full(5, 1.012))
    deliv.loc[last5, "ITE1"] = deliv.loc[idx[:-5], "ITE1"].tail(20).mean() * 1.6
    qty.loc[last5, "ITE1"] = qty.loc[idx[:-5], "ITE1"].tail(20).mean() * 2.4
    f32 = lambda f: f.astype("float32")
    panel = {"close": f32(close), "deliv": f32(deliv), "qty": f32(qty), "vwap": f32(close),
             "high": f32(close * 1.01), "low": f32(close * 0.99), "schema": 4}

    # --- deals ----------------------------------------------------------------
    d3 = sessions(4)[0].isoformat()
    px = lambda s: round(float(close[s].iloc[-4]), 2)
    store.upsert_deals([
        {"date": d3, "symbol": "ITE1", "name": "ITE One Ltd", "client": "LONG HORIZON MUTUAL FUND",
         "side": "BUY", "qty": 600000.0, "price": px("ITE1"), "kind": "bulk", "remarks": None},
        {"date": d3, "symbol": "ITE3", "name": "ITE Three Ltd", "client": "EARLY HOLDER LLP",
         "side": "SELL", "qty": 250000.0, "price": px("ITE3"), "kind": "block", "remarks": None},
        {"date": d3, "symbol": "MET2", "name": "MET Two Ltd", "client": "GRAVITON RESEARCH CAPITAL LLP",
         "side": "BUY", "qty": 900000.0, "price": px("MET2"), "kind": "bulk", "remarks": None},
        {"date": d3, "symbol": "MET2", "name": "MET Two Ltd", "client": "GRAVITON RESEARCH CAPITAL LLP",
         "side": "SELL", "qty": 900000.0, "price": px("MET2"), "kind": "bulk", "remarks": None},
    ])
    return mem, panel


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store.DB_PATH = str(Path(tmp) / "mf.db")
        mem, panel = build()
        M._members["map"] = mem
        M._names["map"] = {s: "%s %s Ltd" % (s[:3], s[3:]) for s in mem}
        M.recompute(today=TODAY, panel=panel)
        page = M.overview()
        page["built_utc"] = "2026-11-20T14:40:00+00:00"
        sectors = {C.slug(s["name"]): M.sector_detail(s["name"]) for s in C.SECTORS}
        brief = M.brief()
    assert page["sectors"][0]["sector"] == IT and page["sectors"][0]["quadrant"] == "Leading", page["sectors"][0]
    assert page["sectors"][-1]["sector"] == METAL, page["sectors"][-1]["sector"]
    assert "FMCG" in page["fpi"]["flipped_to_inflow"]
    assert sectors[C.slug(IT)]["stocks"][0]["symbol"] == "ITE1"
    assert {c["short"] for c in page["unscored"]} == {"Diversified", "Forest", "Utilities"}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in (("money-flow.json", page), ("money-flow-sectors.json", sectors),
                       ("money-flow-brief.json", brief)):
        # The page is indented so a change to it reads as a diff; the 22
        # sector panels are one line each, or the file is half as big again.
        text = (json.dumps(body, indent=1, sort_keys=True, allow_nan=False) if name != "money-flow-sectors.json"
                else "{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(v, sort_keys=True, allow_nan=False,
                                                                            separators=(",", ":"))
                                         for k, v in sorted(body.items())) + "\n}")
        (OUT / name).write_text(text + "\n", encoding="utf-8")
        print("wrote", OUT / name, "%d KB" % ((OUT / name).stat().st_size // 1024))


if __name__ == "__main__":
    main()
