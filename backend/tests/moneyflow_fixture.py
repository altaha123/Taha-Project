"""
An invented market for the Money Flow tests: three sectors with known flows,
index paths and stocks, so every assertion can be worked out by hand.

    Information Technology      FPIs buying more each fortnight, index beating
                                the Nifty 50, most stocks above their 50-day
    Fast Moving Consumer Goods  FPIs turned from selling to buying in the last
                                fortnight, index roughly in line
    Metals & Mining             FPIs selling more each fortnight, index
                                trailing, most stocks below their 50-day

Nothing here is real data. backend/tests/make_money_flow_fixture.py writes the
browser tests' fixture from the same market.
"""
import datetime as dt

import numpy as np
import pandas as pd

IT, FMCG, METAL = "Information Technology", "Fast Moving Consumer Goods", "Metals & Mining"
TODAY = dt.date(2026, 11, 20)

FORTNIGHTS = [("2026-08-16", "2026-08-31"), ("2026-09-01", "2026-09-15"),
              ("2026-09-16", "2026-09-30"), ("2026-10-01", "2026-10-15"),
              ("2026-10-16", "2026-10-31"), ("2026-11-01", "2026-11-15")]
FLOWS = {      # equity net investment, Rs crore, per fortnight above
    IT:    [200, 400, 800, 1200, 2000, 3000],
    FMCG:  [-900, -700, -600, -500, -400, 600],
    METAL: [300, -100, -400, -800, -1200, -2000],
}
AUC = {IT: 400000.0, FMCG: 250000.0, METAL: 200000.0}
INDEX = {IT: "NIFTY IT", FMCG: "NIFTY FMCG", METAL: "NIFTY METAL"}


def _drift(name, i, n):
    """Each index's move on session i of n. The Nifty climbs steadily. IT's
    lead over it widens every session and Metal's lag deepens, so neither sits
    still on the rotation chart; FMCG trails for months and turns up in the
    last eight sessions: still behind, and closing the gap (Improving)."""
    base = 0.0004
    if name == "NIFTY IT":
        return base + 0.0004 + 0.000004 * i
    if name == "NIFTY METAL":
        return base - 0.0004 - 0.000004 * i
    if name == "NIFTY FMCG":
        return base + (0.002 if i >= n - 8 else -0.0012)
    return base


def members():
    out = {}
    for prefix, sector in (("IT", IT), ("FM", FMCG), ("MT", METAL)):
        for n in range(1, 9):
            out["%s%d" % (prefix, n)] = sector
    return out


def sessions(n, end=TODAY):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(days))


def fpi_rows():
    rows = []
    for sector, nets in FLOWS.items():
        auc = AUC[sector]
        for (start, end), net in zip(FORTNIGHTS, nets):
            auc += net
            rows.append({"sector": sector, "period_start": start, "period_end": end,
                         "equity_net_inr_cr": float(net), "equity_net_usd_mn": round(net / 9.5, 0),
                         "total_net_inr_cr": float(net), "equity_auc_inr_cr": auc})
    return rows


def index_closes(n=300):
    """{iso day: {INDEX: close}} for the Nifty 50 and the three sector indices."""
    out, level = {}, {name: 1000.0 for name in ("NIFTY 50", "NIFTY IT", "NIFTY FMCG", "NIFTY METAL")}
    for i, day in enumerate(sessions(n)):
        for name in level:
            level[name] *= 1.0 + _drift(name, i, n)
        out[day.isoformat()] = {name: round(v, 4) for name, v in level.items()}
    return out


def panel(n=90):
    """special.py-shaped panels for the 24 invented stocks."""
    idx = pd.to_datetime(sessions(n))
    cols = sorted(members())
    close = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    deliv = pd.DataFrame(40.0, index=idx, columns=cols)
    qty = pd.DataFrame(1_000_000.0, index=idx, columns=cols)
    for sym in cols:
        k = int(sym[2:])
        if sym.startswith("IT"):
            step = 0.004 if k <= 7 else -0.004          # 7 of 8 above the 50-day
        elif sym.startswith("FM"):
            step = 0.004 if k <= 4 else -0.004          # 4 of 8
        else:
            step = 0.004 if k <= 1 else -0.004          # 1 of 8
        close[sym] = 100.0 * (1.0 + step) ** np.arange(n)
    # IT1 is being accumulated: delivery up, and the last five sessions closed
    # up on twice the usual volume.
    deliv.loc[idx[-5:], "IT1"] = 64.0
    qty.loc[idx[-5:], "IT1"] = 2_000_000.0
    # IT2 split two-for-one a week ago: a 50% one-session drop that is not a fall.
    close.loc[idx[-6:], "IT2"] = close.loc[idx[-6:], "IT2"] / 2.0
    # MT8 barely trades.
    qty["MT8"] = 500.0
    vwap = close.copy()
    f32 = lambda f: f.astype("float32")
    return {"close": f32(close), "deliv": f32(deliv), "qty": f32(qty), "vwap": f32(vwap),
            "high": f32(close * 1.01), "low": f32(close * 0.99), "schema": 4}


def flow_days(n=30):
    out = {}
    for i, day in enumerate(sessions(n)):
        fii = 500.0 + 100.0 * i if i % 3 else -1500.0
        dii = -0.5 * fii + 200.0
        out[day.isoformat()] = {"fii": {"buy": 12000.0 + fii, "sell": 12000.0, "net": fii},
                                "dii": {"buy": 9000.0 + dii, "sell": 9000.0, "net": dii}}
    return out


def deal_rows():
    day = sessions(3)[0].isoformat()
    return [
        {"date": day, "symbol": "IT1", "name": "IT One Ltd", "client": "LONG HORIZON MUTUAL FUND",
         "side": "BUY", "qty": 500000.0, "price": 140.0, "kind": "bulk", "remarks": None},
        {"date": day, "symbol": "IT3", "name": "IT Three Ltd", "client": "EARLY HOLDER LLP",
         "side": "SELL", "qty": 400000.0, "price": 140.0, "kind": "block", "remarks": None},
        # A market maker on both sides: no view, and it must not count.
        {"date": day, "symbol": "IT4", "name": "IT Four Ltd", "client": "GRAVITON RESEARCH CAPITAL LLP",
         "side": "BUY", "qty": 900000.0, "price": 140.0, "kind": "bulk", "remarks": None},
        {"date": day, "symbol": "IT4", "name": "IT Four Ltd", "client": "GRAVITON RESEARCH CAPITAL LLP",
         "side": "SELL", "qty": 900000.0, "price": 140.1, "kind": "bulk", "remarks": None},
    ]


def seed(store):
    """Write the whole invented market into an (empty) store."""
    store.upsert_fpi(fpi_rows(), source_url="fixture")
    for day, closes in index_closes().items():
        store.upsert_index_day(day, closes)
    store.upsert_flows(flow_days())
    store.upsert_deals(deal_rows())
