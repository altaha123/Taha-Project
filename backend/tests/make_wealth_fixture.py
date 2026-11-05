"""
Writes the Wealth desk fixture the browser test serves for /wealth/book and
/wealth/demo.

The book is the real one, from wealth.sample_data() and compute_book(), on a
seeded thirty-session price walk for every sample symbol — so the page is
tested against exactly the shape the server sends. Rebuild it after changing
that shape:

    python backend/tests/make_wealth_fixture.py
"""
import datetime as dt
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import wealth as W                       # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend", "tests", "fixtures",
                   "wealth-demo.json")

AS_OF = dt.date(2026, 11, 5)
SECTORS = {"RELIANCE": "Energy", "HDFCBANK": "Banks", "ICICIBANK": "Banks", "TCS": "IT", "INFY": "IT",
           "LT": "Capital goods", "BHARTIARTL": "Telecom", "ITC": "FMCG", "TITAN": "Consumer",
           "BAJFINANCE": "NBFC", "SUNPHARMA": "Pharma", "POLYCAB": "Capital goods", "TRENT": "Retail",
           "HAL": "Defence", "SBIN": "Banks"}
NAMES = {"RELIANCE": "Reliance Industries", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank",
         "TCS": "Tata Consultancy Services", "INFY": "Infosys", "LT": "Larsen & Toubro",
         "BHARTIARTL": "Bharti Airtel", "ITC": "ITC", "TITAN": "Titan Company", "BAJFINANCE": "Bajaj Finance",
         "SUNPHARMA": "Sun Pharmaceutical", "POLYCAB": "Polycab India", "TRENT": "Trent",
         "HAL": "Hindustan Aeronautics", "SBIN": "State Bank of India"}


def sessions(n=30):
    out, d = [], AS_OF
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return list(reversed(out))


def quotes():
    rnd = random.Random(7)
    dates = sessions()
    q = {}
    for i, (s, p) in enumerate(sorted(W._SAMPLE_PRICE.items())):
        drift = (rnd.random() - 0.45) * 0.004
        closes, x = [], p * (1 - drift * 30)
        for _ in dates:
            x *= 1 + drift + rnd.gauss(0, 0.011)
            closes.append(round(x, 2))
        q[s] = {"symbol": s, "ltp": closes[-1], "prev_close": closes[-2],
                "change_pct": round(100 * (closes[-1] / closes[-2] - 1), 2),
                "week_pct": round(100 * (closes[-1] / closes[-6] - 1), 2),
                "month_pct": round(100 * (closes[-1] / closes[0] - 1), 2),
                "spark": closes, "spark_dates": dates, "last_date": dates[-1],
                "source": "Yahoo Finance (daily, delayed)", "name": NAMES[s], "sector": SECTORS[s],
                "score": round(40 + rnd.random() * 45, 1), "label": None, "tone": None}
    return q


def build():
    # The book is valued "today"; pinning today to the fixture's own date
    # makes the file the same whichever day it is rebuilt or checked.
    real = W.today
    W.today = lambda: AS_OF
    try:
        q = quotes()
        data = W.sample_data(q, on=AS_OF.isoformat())
        return W.compute_book(data, q, on=AS_OF.isoformat(), demo=True)
    finally:
        W.today = real


if __name__ == "__main__":
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
            return None
        return o

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(build()), fh, separators=(",", ":"))
    print(OUT, os.path.getsize(OUT), "bytes")
