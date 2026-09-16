"""
Regenerate frontend/tests/fixtures/funds-*.json.

Produced by the real modules from a workbook shaped exactly like the ones the
AMCs publish, so a key renamed in fund_portfolios.py cannot keep passing
against a stale JSON literal. Includes the three cases the page exists to get
right: a company held by several schemes, a debt row that must not become an
equity position, and a holding whose ISIN is not on NSE's equity list.

    python backend/tests/make_funds_fixture.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "frontend" / "tests" / "fixtures"

MAP = {
    "INE002A01018": "RELIANCE", "INE040A01034": "HDFCBANK",
    "INE090A01021": "ICICIBANK", "INE257A01026": "BHEL",
    "INE018A01030": "LT",
}


def _h(isin, name, industry, qty, value, pct, scheme):
    return {"isin": isin, "name": name, "industry": industry, "quantity": qty,
            "value_lakh": value, "pct_nav": pct, "scheme": scheme}


SHEETS = [
    {"sheet": "T0ME04", "as_on": "31-Aug-2026", "holdings": [
        _h("INE090A01021", "ICICI Bank Limited", "Banks", 1_000_000, 16619.22, 6.29, "T0ME04"),
        _h("INE002A01018", "Reliance Industries Limited", "Petroleum Products", 900_000, 14366.25, 5.44, "T0ME04"),
        _h("INE040A01034", "HDFC Bank Limited", "Banks", 1_400_000, 14038.20, 5.32, "T0ME04"),
        _h("INE257A01026", "Bharat Heavy Electricals Limited", "Electrical Equipment", 1_200_000, 5310.00, 2.01, "T0ME04"),
        # Debt in the same sheet: must never become an equity position.
        _h("INE557F08FY4", "7.59% National Housing Bank (14/07/2028)", "AAA", 2500, 2503.45, 0.95, "T0ME04"),
    ]},
    {"sheet": "T0ME02", "as_on": "31-Aug-2026", "holdings": [
        _h("INE257A01026", "Bharat Heavy Electricals Limited", "Electrical Equipment", 2_000_000, 8853.00, 3.33, "T0ME02"),
        _h("INE018A01030", "Larsen & Toubro Limited", "Construction", 200_000, 7000.00, 2.63, "T0ME02"),
        _h("INE090A01021", "ICICI Bank Limited", "Banks", 300_000, 4985.77, 1.87, "T0ME02"),
    ]},
    {"sheet": "T0MF01", "as_on": "31-Aug-2026", "holdings": [
        # A fund-of-fund line: a valid equity-series ISIN that is not on NSE's
        # equity list. Kept and shown separately so the weights reconcile.
        _h("INE0J1901017", "Baroda BNP Paribas Gold ETF-RG", None, 5_000_000, 19181.00, 1.00, "T0MF01"),
    ]},
]

NAMES = {"T0ME04": "Baroda BNP Paribas Large Cap Fund",
         "T0ME02": "Baroda BNP Paribas Mid Cap Fund",
         "T0MF01": "Baroda BNP Paribas Gold ETF Fund of Fund"}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ALTAHA_HOLDINGS_DB"] = str(Path(tmp) / "f.db")
        os.environ["DATA_DIR"] = tmp
        for m in ("holdings_store", "fund_portfolios", "fund_workbook"):
            sys.modules.pop(m, None)
        import fund_portfolios as fp
        import fund_workbook

        fp._http = lambda url, timeout=40: b"PK\x03\x04fake"
        fund_workbook.looks_like_xlsx = lambda b: True
        fund_workbook.parse_workbook = lambda path, **kw: SHEETS
        fund_workbook.scheme_names = lambda path: NAMES

        r = fp.ingest_url("20", "Baroda BNP Paribas Mutual Fund",
                          "https://www.barodabnpparibasmf.in/assets/"
                          "BOBBNPMF_Monthly_Portfolio_31-08-2026.xlsx",
                          mapping=MAP)
        assert r["ok"], r
        assert r["as_of"] == "2026-08-31"
        assert r["unmapped"] == 1, r

        from fastapi.testclient import TestClient
        import main
        c = TestClient(main.app)

        OUT.mkdir(parents=True, exist_ok=True)
        directory = c.get("/funds").json()
        (OUT / "funds-directory.json").write_text(
            json.dumps(directory, indent=1) + "\n", encoding="utf-8")

        one = c.get("/fund", params={"amc": "20"}).json()
        (OUT / "funds-20.json").write_text(
            json.dumps(one, indent=1) + "\n", encoding="utf-8")

        bhel = next(p for p in one["positions"] if p["symbol"] == "BHEL")
        assert bhel["scheme_count"] == 2, "BHEL is held by two schemes"
        assert all(p["symbol"] != "INE557F08FY4" for p in one["positions"])
        assert len(one["not_on_nse"]) == 1
        names = {p["name"] for p in one["positions"]}
        assert not any("National Housing Bank" in n for n in names), \
            "a debenture must never appear as an equity position"
        print("wrote 2 fixtures to %s (%d companies)"
              % (OUT.relative_to(ROOT), one["count"]))


if __name__ == "__main__":
    main()
