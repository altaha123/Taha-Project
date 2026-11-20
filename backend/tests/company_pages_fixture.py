"""
Made-up companies for the company pages, shaped as fundamentals_query's
snapshot rows and fundamentals_store's quarterly rows are.

Used twice: by test_company_pages.py, and by
frontend/tests/company-page-browser.cjs, which runs this file and loads the
pages it prints into a real browser:

    python backend/tests/company_pages_fixture.py > pages.json

Printing the pages from the real renderer, against the real stock.html, is
the point. A saved copy would go stale the day either file changed, and a
stale copy passes.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
REPO = os.path.dirname(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

SITE = "https://altahascreener.in"
API = "https://api.example"

ACME = {
    "symbol": "ACME", "name": "Acme Chemicals Ltd", "industry": "Specialty Chemicals",
    "sector": "Chemicals", "basis": "consolidated", "fy": "FY26",
    "price": 812.5, "market_cap": 12500.0, "pe": 24.1, "pb": 4.85, "dividend_yield": 0.62,
    "roe": 21.2, "roce": 28.4, "debt_to_equity": 0.12, "opm": 22.6,
    "sales": 4200.0, "net_profit": 518.4, "sales_growth_3y": 18.5, "profit_growth_3y": 24.0,
    "quarter": "2026-06-30", "sales_qtr": 1180.0, "net_profit_qtr": 151.25,
    "sales_growth_qtr": 10.5, "profit_growth_qtr": 14.2,
    "promoter_holding": 61.42, "pledged": 0.0, "fii_holding": 12.3, "dii_holding": 9.87,
}

# A loss, no percentage across it, a symbol with an ampersand, pledged shares.
GAMMA = {
    "symbol": "G&S", "name": "Gamma & Sons Ltd", "industry": "Textiles", "sector": "Textiles",
    "basis": "standalone", "fy": "FY26", "price": 95.2, "market_cap": 640.0, "pe": None,
    "roe": -3.0, "roce": 9.0, "debt_to_equity": 1.4, "sales": 800.0, "net_profit": -24.0,
    "quarter": "2026-06-30", "sales_qtr": 190.0, "net_profit_qtr": -4300.0,
    "sales_growth_qtr": None, "profit_growth_qtr": None,
    "promoter_holding": 48.0, "pledged": 12.5,
}

# Read from the exchange but thinly: no price, no quarter, no ownership.
DELTA = {
    "symbol": "DELTA", "name": "Delta Infra Ltd", "industry": "Construction",
    "sector": "Construction", "basis": "standalone", "fy": "FY26",
    "price": None, "market_cap": None, "pe": None, "roce": 26.0, "roe": None,
    "sales": 1500.0, "net_profit": None, "quarter": None,
}

# A large company: market value in lakh crore, and a name that starts with a digit.
GIANT = {
    "symbol": "3GIANT", "name": "3 Giants Industries Limited", "industry": "Refineries",
    "sector": "Energy", "basis": "consolidated", "fy": "FY26", "price": 1197.6,
    "market_cap": 1620649.0, "pe": 22.4, "roe": 8.7, "roce": 9.4, "sales": 964693.0,
    "net_profit": 81309.0, "quarter": "2026-06-30", "sales_qtr": 269496.0,
    "net_profit_qtr": 22290.0, "sales_growth_qtr": 10.5,
}

# Fourteen more chemical companies, so "the ones nearest in size" has a
# middle and two ends to be tested at.
CHEMS = [{
    "symbol": "CHEM%02d" % i, "name": "Chem %02d Ltd" % i, "industry": "Specialty Chemicals",
    "sector": "Chemicals", "basis": "consolidated", "fy": "FY26",
    "price": 100.0 + i, "market_cap": 1000.0 * i, "pe": 10.0 + i, "roe": 12.0, "roce": 15.0,
    "sales": 500.0 * i, "net_profit": 40.0 * i,
} for i in range(1, 15)]

# In the tables but with no name: no page, no link, no sitemap line.
NAMELESS = {"symbol": "NONAME", "name": None, "industry": "Textiles", "market_cap": 50.0}

ROWS = [ACME, GAMMA, DELTA, GIANT, NAMELESS] + CHEMS


def _quarter(symbol, basis, end, label, revenue, pat, eps, yoy):
    return {"symbol": symbol, "basis": basis, "freq": "quarterly", "label": label,
            "period_end": end, "revenue_cr": revenue, "pat_cr": pat, "eps_basic": eps,
            "revenue_yoy_pct": yoy}


# Both bases, interleaved, as the store returns them. The standalone figures
# are less than half the consolidated ones, as a group's are.
ACME_QUARTERS = [
    _quarter("ACME", "consolidated", "2026-06-30", "Q1 FY27", 1180.0, 151.25, 12.4, 10.5),
    _quarter("ACME", "standalone", "2026-06-30", "Q1 FY27", 470.0, 61.0, 5.0, 4.0),
    _quarter("ACME", "consolidated", "2026-03-31", "Q4 FY26", 1105.5, 139.0, 11.4, 8.25),
    _quarter("ACME", "standalone", "2026-03-31", "Q4 FY26", 455.0, 58.0, 4.75, 3.0),
    _quarter("ACME", "consolidated", "2025-12-31", "Q3 FY26", 1040.0, -12.5, -1.02, -2.4),
    _quarter("ACME", "consolidated", "2025-09-30", "Q2 FY26", 1010.0, 120.0, 9.84, None),
]


# When each company's newest results reached the exchange, as
# fundamentals_store.latest_filed() returns it. One real day, one in the
# future and one that is not a date: only the first may reach the sitemap.
FILED = {"ACME": "2026-08-12", "G&S": "2999-01-01", "DELTA": "not a date"}


def pages():
    import company_pages as CP
    with open(os.path.join(REPO, "frontend", "stock.html"), encoding="utf-8") as fh:
        template = fh.read()
    return {
        "company": CP.render_company(template, ACME, ROWS, SITE, ACME_QUARTERS, 61.4),
        "plain": CP.render_plain(ACME, ROWS, SITE, API, ACME_QUARTERS, 61.4),
        "directory": CP.render_directory(ROWS, SITE, API),
        "sector": CP.render_sector(ROWS, "chemicals", SITE, API),
        "missing": CP.render_missing("NOSUCH", SITE, API),
        "sitemap": CP.sitemap(ROWS, SITE, FILED),
    }


if __name__ == "__main__":
    json.dump(pages(), sys.stdout)
