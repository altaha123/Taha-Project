"""
Regenerate frontend/tests/fixtures/delivery-trends.json.

Same rule as make_delivery_fixture.py: the browser test reads a payload the
real `delivery_trends` produced, so a key renamed in special.py changes the
fixture and the page test fails, instead of passing against a hand-typed JSON
that still carries the old name.

    python backend/tests/make_delivery_trends_fixture.py

THE PANEL IS INVENTED. It uses real NSE symbols, so that names and industries
resolve from nse_industries.csv exactly as they do in production, but every
price, quantity and delivery share below comes from a seeded random generator
plus a handful of planted patterns. Nothing in the fixture is a statement
about any company, and nothing here should ever be shown as market data.

What is planted, and why each is there:

  · RELIANCE   a clean spike on a rise: 3,000,000 shares at Rs 1,400, 60%
               delivered against a flat 1,000,000 at 40%. Rs 252 cr against a
               usual Rs 56 cr is exactly 4.5 times, which the tests assert.
  · TCS        the same shape on a fall, so both directions have a row.
  · INFY       five times the volume at a lower share: churn, and absent.
  · WIPRO      a 1:1 bonus inside the window, so it is left out and counted.
  · LT         above normal on four of five sessions: the week list.
  · ITC        a month of higher delivery on a still price: the quiet list.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd

import special

OUT = ROOT / "frontend" / "tests" / "fixtures" / "delivery-trends.json"
SESSIONS = 120
N_SYMBOLS = 260
PLANTED = ["RELIANCE", "TCS", "INFY", "WIPRO", "LT", "ITC"]


def build_panel():
    names = special._company_names()
    assert all(s in names for s in PLANTED), "a planted symbol left the industry file"
    pool = sorted(s for s in names if s not in PLANTED and not special._is_fund(s))
    rng = np.random.default_rng(20261119)
    syms = PLANTED + list(rng.choice(pool, N_SYMBOLS - len(PLANTED), replace=False))
    days = pd.bdate_range(end="2026-11-19", periods=SESSIONS)
    n, m = len(days), len(syms)

    # Each stock has its own level of price, volume and delivered share, and
    # wanders around it. Volume is lognormal with fat days, as real volume is.
    base_px = rng.uniform(80, 4000, m)
    close = base_px * np.exp(np.cumsum(rng.normal(0.0004, 0.016, (n, m)), axis=0))
    base_qty = np.exp(rng.normal(13.2, 1.3, m))
    qty = base_qty * np.exp(rng.normal(0, 0.42, (n, m)))
    burst = rng.random((n, m)) < 0.025
    qty = np.where(burst, qty * rng.uniform(2.2, 6.0, (n, m)), qty)
    base_dp = rng.uniform(24, 68, m)
    deliv = np.clip(base_dp + rng.normal(0, 6.5, (n, m)) - np.where(burst, 6, 0), 3, 97)
    spread = np.abs(rng.normal(0.011, 0.005, (n, m))) + 0.003
    loc = rng.uniform(0.05, 0.95, (n, m))
    high = close * (1 + spread * (1 - loc))
    low = close * (1 - spread * loc)
    vwap = (high + low + close) / 3

    P = {k: pd.DataFrame(v, index=days, columns=syms) for k, v in
         (("deliv", deliv), ("qty", qty), ("vwap", vwap), ("close", close),
          ("high", high), ("low", low))}

    def flat(sym, px, q=1_000_000, share=40.0):
        for f, v in (("close", px), ("vwap", px), ("high", px * 1.01),
                     ("low", px * 0.99), ("qty", q), ("deliv", share)):
            P[f][sym] = float(v)

    def put(field, sym, rows, value):
        P[field].iloc[rows, P[field].columns.get_loc(sym)] = value

    flat("RELIANCE", 1400)
    put("qty", "RELIANCE", -1, 3_000_000); put("deliv", "RELIANCE", -1, 60)
    put("close", "RELIANCE", -1, 1442); put("high", "RELIANCE", -1, 1445)

    flat("TCS", 3200)
    put("qty", "TCS", -1, 2_600_000); put("deliv", "TCS", -1, 58)
    put("close", "TCS", -1, 3091); put("low", "TCS", -1, 3085)

    flat("INFY", 1500)
    put("qty", "INFY", -1, 5_000_000); put("deliv", "INFY", -1, 22)

    flat("WIPRO", 480)
    put("qty", "WIPRO", slice(-4, None), 2_000_000)
    for f in ("close", "vwap", "high", "low"):
        put(f, "WIPRO", slice(-4, None), P[f]["WIPRO"].iloc[-5] / 2)

    flat("LT", 3600)
    put("qty", "LT", slice(-5, -1), 1_700_000); put("deliv", "LT", slice(-5, -1), 51)
    put("close", "LT", slice(-5, None), 3708)

    flat("ITC", 430)
    put("deliv", "ITC", slice(-20, None), 53); put("qty", "ITC", slice(-20, None), 1_250_000)
    put("close", "ITC", slice(-20, None), 433)

    # A session the exchange published no quantity for, inside a spark window.
    put("qty", "TCS", -9, np.nan)

    out = {k: v.astype("float32") for k, v in P.items()}
    out["schema"] = special.WIDE_SCHEMA
    return out


def main():
    special.ensure_building = lambda *a, **k: None
    special._state["panel"] = build_panel()
    payload = special.delivery_trends(min_turnover_cr=10, limit=60)
    assert payload["available"] is True, payload
    v = payload["views"]
    top = {r["symbol"]: r for r in v["today"]["rows"]}
    assert top["RELIANCE"]["mult"] == 4.5 and top["RELIANCE"]["delivered_cr"] == 252.0
    assert "INFY" not in top and payload["excluded_corporate_action"] >= 1
    assert any(r["symbol"] == "LT" for r in v["week"]["rows"])
    assert any(r["symbol"] == "ITC" for r in v["quiet"]["rows"])
    payload["fixture_note"] = ("Invented data on real symbols. See "
                               "backend/tests/make_delivery_trends_fixture.py.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: as of {payload['as_of']}, "
          + ", ".join(f"{k} {x['total']}" for k, x in v.items())
          + f", {len(payload['sectors'])} industries")


if __name__ == "__main__":
    main()
