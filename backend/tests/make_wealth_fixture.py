"""
Writes the Wealth desk fixtures the browser test serves: the book for
/wealth/book and /wealth/demo, and the week's news for /wealth/news and
/wealth/demo/news.

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
NEWS_OUT = os.path.join(os.path.dirname(OUT), "wealth-news.json")

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


# The news is built by the real wealth_news.build() from these rows, over the
# sample book. Invented filings on invented dates: the shape is what is tested.
NEWS_NOW = dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone.utc)
HAL_PDF = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/fixture-hal-results.pdf"


def news(book=None):
    import wealth_news as N
    book = book or build()

    def at(hours):
        return (NEWS_NOW - dt.timedelta(hours=hours)).isoformat()

    pdf = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/fixture-%s.pdf"
    filings = [
        {"symbol": "HAL", "company": "Hindustan Aeronautics Ltd", "category": "Results", "importance": "critical",
         "headline": "Unaudited financial results for the quarter ended 30 September 2026", "at": at(5), "pdf": HAL_PDF},
        {"symbol": "LT", "company": "Larsen & Toubro Ltd", "category": "Order win", "importance": "critical",
         "headline": "Letter of award for a metro rail package", "at": at(20), "pdf": pdf % "lt-order"},
        {"symbol": "TCS", "company": "Tata Consultancy Services Ltd", "category": "Board meeting", "importance": "low",
         "headline": "Board meeting on 12 November 2026 to consider an interim dividend", "at": at(30), "pdf": pdf % "tcs-board"},
        {"symbol": "SBIN", "company": "State Bank of India", "category": "Credit rating", "importance": "high",
         "headline": "<img src=x onerror=alert(1)> Credit rating reaffirmed", "at": at(50), "pdf": pdf % "sbin-rating"},
        {"symbol": "ITC", "company": "ITC Ltd", "category": "Trading window", "importance": "routine",
         "headline": "Closure of trading window", "at": at(3), "pdf": pdf % "itc-window"},
    ]
    press = [{"headline": "HDFC Bank shares rise after a loan growth update", "source": "Mint",
              "url": "https://news.example.com/hdfc-bank-loan-growth", "when_iso": at(8), "symbols": ["HDFCBANK"]}]
    briefs = {N.key_for(HAL_PDF): {"status": "ready", "text": (
        "Q2 revenue Rs 7,150 crore, up 14% from a year earlier; net profit Rs 1,690 crore against "
        "Rs 1,510 crore. No dividend was declared.")}}
    return N.build(N.holdings_from_book(book), filings, press, briefs=briefs, now=NEWS_NOW, configured=True,
                   status={"filings": {"first_load": False}})


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
    book = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(book), fh, separators=(",", ":"))
    print(OUT, os.path.getsize(OUT), "bytes")
    with open(NEWS_OUT, "w", encoding="utf-8") as fh:
        json.dump(clean(news(book)), fh, separators=(",", ":"))
    print(NEWS_OUT, os.path.getsize(NEWS_OUT), "bytes")
