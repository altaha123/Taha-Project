"""
Regenerate frontend/tests/fixtures/stock-page.json from the real modules.

One made-up bank, opened as its stock page would open it. The real /analyze
runs over a synthetic price history and a ranked cohort; the real peer table
is built over a throwaway store; the real press and filings assemblers run
over canned search results and exchange rows. The browser test reads those
responses, so a key renamed in main.py, stock_page.py, stock_news.py or
announcements.py fails the browser test instead of passing against a stale
JSON literal.

Every company and every figure here is invented. The names are chosen so the
page can be looked at with something that reads like a bank and its peers.

    python backend/tests/make_stock_page_fixture.py
"""

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE.parents[1] / "frontend" / "tests" / "fixtures" / "stock-page.json"

SYMBOL, NAME = "NORTHBANK", "Northern Union Bank Limited"
SECTOR, INDUSTRY = "Financial Services", "Banks - Regional"
TODAY = dt.date(2026, 11, 18)

# name, market value in crore, quarterly profit, equity, score
BANKS = [
    ("HARBOURBK", "Harbour Bank Limited",          1480000, 17600, 512000, 61.8),
    ("CRESTBANK", "Crest Bank Limited",             986000, 11900, 301000, 57.2),
    ("NORTHBANK", NAME,                            1067000, 22600, 671000, None),
    ("MERIDIANB", "Meridian Bank Limited",          412000,  6900, 181000, 48.9),
    ("PENINSULA", "Peninsula Bank Limited",         338000,  4300, 152000, None),
    ("DELTABANK", "Delta Bank of India Limited",    151000,  4800, 139000, 53.4),
    ("UNIONCOOP", "Union Cooperative Bank Limited", 132000,  4100, 118000, 44.1),
    ("CANALBANK", "Canal Bank Limited",             119000,  4400, 104000, None),
    ("SUMMITFIN", "Summit First Bank Limited",       58000,   480,  39000, 36.7),
    ("LAKESHORE", "Lakeshore Bank Limited",          49000,  1050,  33000, 51.0),
    ("RIDGEBANK", "Ridge Small Finance Bank Limited", 21000,   310,   9800, None),
]
QS = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"]


def analyze_payload():
    import numpy as np
    import pandas as pd
    import conftest
    import factors as F
    import multifactor as M
    import main as api

    rng = np.random.default_rng(11)
    cohort = []
    for i in range(64):
        bank = i % 4 == 0
        cohort.append({
            "symbol": "C%03d" % i,
            "name": "Cohort %d Ltd" % i,
            "sector": SECTOR if bank else ("Technology" if i % 3 == 0 else "Industrials"),
            "industry": INDUSTRY if bank else ("Software services" if i % 3 == 0 else "Engineering"),
            "market_cap": float(rng.lognormal(24, 1.2)),
            "trailing_eps": float(rng.normal(20, 6)) + 30,
            "factors": {k: float(rng.normal(0, 10)) for k in F.SPEC},
            "grid_ratios": {"pe": float(rng.uniform(6, 40)), "roe": float(rng.uniform(4, 24)),
                            "roce": float(rng.uniform(5, 30)), "de": float(rng.uniform(0, 2)),
                            "dividend_yield": float(rng.uniform(0, 3))},
            "data_quality": {"as_of": TODAY.isoformat(), "period_age_days": 49,
                             "history_quarters": 16, "source_valid": True},
        })
    api._state["payload"] = {"scanned_at": "18 Nov 2026, 04:13",
                             "factor_universe": M.rank(cohort, "position")["rows"]}

    closes = conftest.ramp(820, 1010, 180) + conftest.ramp(1010, 940, 40) + conftest.ramp(940, 1156, 80)
    hist = conftest.ohlcv(closes, end=pd.Timestamp(TODAY))
    info = {"longName": NAME, "sector": SECTOR, "industry": INDUSTRY, "currency": "INR",
            "marketCap": 1.067059e13, "trailingEps": 97.9, "trailingPE": 11.8, "bookValue": 727.56,
            "priceToBook": 1.59, "returnOnEquity": 0.14, "dividendRate": 17.3,
            "fullTimeEmployees": 232296, "website": "https://www.northernunion.example/",
            "longBusinessSummary": (
                "Northern Union Bank Limited provides banking products and services to "
                "individuals, commercial enterprises, corporates, public bodies and "
                "institutional customers in India and internationally. It operates through "
                "Treasury, Corporate and Wholesale Banking, Retail Banking, and Other Banking "
                "Business segments. The company accepts savings, current and term deposits and "
                "offers home, personal, auto, education and gold loans, along with loans "
                "against securities and property. It also provides working capital finance, "
                "project and structured finance, cash management, trade finance and supply "
                "chain finance, as well as life and general insurance, mutual funds, cards "
                "and merchant payment services through its subsidiaries. The bank serves its "
                "customers through a network of branches, ATMs and digital channels.")}

    # Quarters with enough history that the bank's own growth and quality
    # factors are measured, so the page shows a score that rests on something.
    quarters = []
    for i in range(16):
        end = (pd.Timestamp("2026-09-30") - pd.offsets.QuarterEnd(i)).date()
        rev, pat = 132000e7 * (0.972 ** i), 22600e7 * (0.966 ** i)
        begin = (end - dt.timedelta(days=91)).isoformat()
        quarters.append({"period": {"from": begin, "to": end.isoformat()},
            "from": begin, "to": end.isoformat(),
            "filed_at": "%s 18:00:00" % (end + dt.timedelta(days=38)).strftime("%d-%b-%Y"),
            "consolidated": True, "source_url": "https://nsearchives.example/%s.xml" % end,
            "revenue": rev, "pat": pat, "eps_basic": pat / 8.92e9,
            "roa_annualised_pct": 1.05 + 0.01 * (16 - i)})

    api.resolve = lambda t: (t.upper() + ".NS", None, hist)
    api.fundamentals = lambda sym, t: (None, None, None, dict(info))
    api.shareholding = lambda t: {"published": False}
    if api.xbrl_source is not None:
        api.xbrl_source.scoring_statements = lambda s, *a, **k: quarters
    import score_on_request
    api._on_request = score_on_request.OnRequestScorer()
    d = api.analyze(SYMBOL)
    assert d["scoring"]["score"] is not None, d["scoring"]
    return json.loads(json.dumps(d, default=str))


def peers_payload():
    import fundamentals as F
    import fundamentals_store as fs
    import stock_page as S

    for sym, name, cap, pat, equity, _score in BANKS:
        fs.record_yf_profile(sym, {
            "longName": name, "sector": SECTOR, "industry": INDUSTRY, "currency": "INR",
            "sharesOutstanding": cap * 1e7 / 1000.0, "currentPrice": 1000.0, "marketCap": cap * 1e7,
            "website": "https://www.%s.example" % sym.lower()})
        rows = []
        for i, end in enumerate(QS):
            e = dt.date.fromisoformat(end)
            row = fs.to_row("income", {
                "symbol": sym, "company": name, "basis": "consolidated", "freq": "quarterly",
                "label": F.quarter_label(e), "period_from": (e - dt.timedelta(days=90)).isoformat(),
                "period_end": end, "months": 3, "filed_at": "2026-11-01", "audited": "Unaudited",
                "source_url": "https://x/%s-%s.xml" % (sym, end)},
                {"revenue": pat * 5.8e7 * (0.98 ** i), "pat": pat * 1e7 * (0.97 ** i)})
            if i == 0:
                row["revenue_yoy_pct"] = round(6 + (cap % 9), 1)
                row["pat_yoy_pct"] = round(-4 + (cap % 23), 1)
                row["net_margin_pct"] = round(100 / 5.8, 1)
            rows.append(row)
        rows.append(fs.to_row("income", {
            "symbol": sym, "company": name, "basis": "consolidated", "freq": "annual",
            "label": "FY26", "period_end": "2026-03-31", "months": 12, "filed_at": "2026-05-01",
            "source_url": "https://x/%s-y.xml" % sym}, {"revenue": pat * 23e7, "pat": pat * 3.9e7}))
        fs.upsert("income", rows)
        fs.upsert("balance", [fs.to_row("balance", {
            "symbol": sym, "company": name, "basis": "consolidated", "label": "2026-09-30",
            "period_end": "2026-09-30", "filed_at": "2026-11-01",
            "source_url": "https://x/%s-b.xml" % sym},
            {"total_assets": equity * 11e7, "total_equity": equity * 1e7})])
    scores = {sym: score for sym, _n, _c, _p, _e, score in BANKS if score is not None}
    out = S.peer_table(SYMBOL, INDUSTRY, [b[0] for b in BANKS], classifier="Yahoo Finance",
                       scores=scores, today=TODAY)
    assert out["available"], out
    return json.loads(json.dumps(out, default=str))


def _rss(items, now):
    body = "".join(
        "<item><title>%s - %s</title><link>https://news.example/%d</link><pubDate>%s</pubDate>"
        "<source url=\"https://p\">%s</source></item>"
        % (t, src, i, (now - dt.timedelta(hours=h)).strftime("%a, %d %b %Y %H:%M:%S GMT"), src)
        for i, (t, h, src) in enumerate(items))
    return ("<rss><channel>%s</channel></rss>" % body).encode()


def news_payload():
    import stock_news as N
    now = dt.datetime.now(dt.timezone.utc)
    company = _rss([
        ("Northern Union Bank Q2 net profit rises 10% to ₹22,600 crore; asset quality steady", 3, "Mint"),
        ("Northern Union Bank raises ₹7,500 crore through tier-2 bonds at 7.02%", 21, "Business Standard"),
        ("Northern Union Bank to open 500 branches this financial year, says chairman", 46, "Economic Times"),
        ("Northern Union Bank cuts MCLR by 5 basis points across tenors", 70, "Moneycontrol"),
        ("Why brokerages stay divided on Northern Union Bank after its September quarter", 96, "Financial Express"),
        ("Southern Union Bank names new chief executive", 5, "Mint"),
    ], now)
    industry = _rss([
        ("RBI keeps repo rate unchanged at 5.25%, retains neutral stance", 6, "Mint"),
        ("Banks' credit growth slows to 11.2% as deposits keep pace: RBI data", 18, "Business Standard"),
        ("Gross NPAs of banks at a multi-decade low of 2.1%, says Financial Stability Report", 30, "Economic Times"),
        ("RBI proposes easier norms for bank lending to NBFCs", 41, "Moneycontrol"),
        ("Deposit rates set to fall further as liquidity stays in surplus", 55, "Hindu BusinessLine"),
        ("Bank holidays in December: full list of days branches stay shut", 9, "Times of India"),
        ("Northern Union Bank chairman on deposit growth", 12, "CNBC"),
    ], now)
    N._memo.clear()
    out = N.for_stock(SYMBOL, NAME, SECTOR, INDUSTRY,
                      fetch=lambda q: N.parse(company if "Northern Union" in q else industry))
    assert len(out["company"]["rows"]) == 5 and out["industry"]["rows"], out
    return json.loads(json.dumps(out, default=str))


def filings_payload():
    import announcements as A
    now = dt.datetime.now(dt.timezone.utc)

    def row(text, days, subject="Updates", pdf=True):
        when = now - dt.timedelta(days=days, hours=3)
        return {"symbol": SYMBOL, "sm_name": NAME, "desc": subject, "attchmntText": text,
                "an_dt": when.astimezone(A.IST).strftime("%d-%b-%Y %H:%M:%S"),
                "attchmntFile": ("https://nsearchives.example/corporate/%s_%d.pdf" % (SYMBOL, days))
                if pdf else None}

    raw = [
        row("Northern Union Bank Limited has submitted the unaudited financial results for the "
            "quarter and half year ended September 30, 2026", 8, "Financial Result Updates"),
        row("Transcript of the earnings call for the quarter ended September 30, 2026", 6,
            "Analysts/Institutional Investor Meet/Con. Call Updates"),
        row("Northern Union Bank Limited has informed the Exchange about raising of funds through "
            "issue of Basel III compliant tier 2 debentures aggregating Rs 7,500 crore", 3,
            "Updates"),
        row("Intimation of revision in credit rating by ICRA Limited", 15, "Credit Rating"),
        row("Board meeting to consider and approve the financial results on November 8, 2026", 22,
            "Board Meeting Intimation"),
        row("Appointment of Managing Director with effect from October 1, 2026", 52,
            "Change in Directorate"),
        row("Declaration of dividend of Rs 17.30 per equity share for FY 2025-26", 176, "Dividend"),
        row("Closure of trading window", 49, "Trading Window", pdf=False),
        row("Newspaper publication of financial results", 7, "Copy of Newspaper Publication"),
    ]
    A._company_memo.clear()
    out = A.for_company(SYMBOL, fetch=lambda s, d: [A._nse_item(r) for r in raw])
    assert out["available"] and out["count"] == len(raw), out
    return json.loads(json.dumps(out, default=str))


def main():
    tmp = tempfile.mkdtemp()
    os.environ["ALTAHA_FUNDAMENTALS_DB"] = os.path.join(tmp, "f.db")
    import conftest  # noqa: F401  (offline stubs for the modules main imports)
    out = {"symbol": SYMBOL, "analyze": analyze_payload(), "peers": peers_payload(),
           "news": news_payload(), "filings": filings_payload()}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sc = out["analyze"]["scoring"]
    print("wrote %s: score %.1f (%s), %d peers, %d+%d headlines, %d filings" % (
        OUT.relative_to(HERE.parents[1]), sc["score"], sc["band"], out["peers"]["peers_shown"],
        len(out["news"]["company"]["rows"]), len(out["news"]["industry"]["rows"]),
        out["filings"]["count"]))


if __name__ == "__main__":
    main()
