"""
Regenerate frontend/tests/fixtures/funds-*.json.

Produced by the real modules from a workbook shaped exactly like the ones the
AMCs publish, so a key renamed in fund_portfolios.py cannot keep passing
against a stale JSON literal. Includes the three cases the page exists to get
right: a company held by several schemes, a debt row that must not become an
equity position, and a holding whose ISIN is not on NSE's equity list.

It also writes backend/tests/fixtures/funds_legacy_pack.xls: a small pack in
the legacy binary .xls format, laid out the way Aditya Birla Sun Life's is
(an index sheet, then one sheet per scheme whose rows carry an internal code
before the name, so the header is one column off its data). Writing that
format needs xlwt, which is a development tool only and not in
requirements.txt; reading it needs xlrd, which is.

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

        def _download(url, timeout=180, headers=None):
            fh = tempfile.NamedTemporaryFile(suffix=".dl", delete=False)
            fh.write(b"PK\x03\x04fake")
            fh.close()
            return fh.name, None

        fp._download = _download
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
    write_legacy_xls(LEGACY_XLS)


LEGACY_XLS = ROOT / "backend" / "tests" / "fixtures" / "funds_legacy_pack.xls"

LEGACY_HEADER = ("Name of the Instrument / Issuer", "ISIN", "Industry^ / Rating",
                 "Quantity", "Market value\n(Rs. in Lakhs)", "% to AUM", "YTM %")

LEGACY_SCHEMES = {
    "BSL95F": ("ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND (FORMERLY KNOWN AS "
               "ADITYA BIRLA SUN LIFE EQUITY HYBRID '95 FUND)", [
        ("100012", "ICICI Bank Ltd.", "INE090A01021", "Banks", 3000001, 41940.01, 0.0621),
        ("100034", "Reliance Industries Ltd.", "INE002A01018", "Petroleum Products", 1500000, 21490.5, 0.0318),
        ("200001", "7.18% GOI 2033", "IN0020230085", "SOVEREIGN", 5000000, 5100.2, 0.0075),
    ]),
    "ADVG": ("ADITYA BIRLA SUN LIFE LARGE & MID CAP FUND", [
        ("100012", "ICICI Bank Ltd.", "INE090A01021", "Banks", 900000, 12582.0, 0.0512),
        ("100077", "Larsen & Toubro Ltd.", "INE018A01030", "Construction", 200000, 7000.0, 0.0285),
    ]),
}


def write_legacy_xls(path):
    """A two-scheme pack in the legacy .xls format. Needs xlwt (dev only)."""
    try:
        import xlwt
    except ImportError:
        print("skipped %s: pip install xlwt to regenerate it" % path.name)
        return
    wb = xlwt.Workbook()
    idx = wb.add_sheet("Index")
    idx.write(0, 0, "Index")
    for j, h in enumerate(("Scheme Code", "Scheme Short code", "Scheme Name")):
        idx.write(2, j, h)
    for i, (code, (name, _rows)) in enumerate(LEGACY_SCHEMES.items()):
        idx.write(3 + i, 0, "AB%03d" % (i + 1))
        idx.write(3 + i, 1, code)
        idx.write(3 + i, 2, name)
    for code, (name, rows) in LEGACY_SCHEMES.items():
        ws = wb.add_sheet(code)
        ws.write(0, 0, code)
        ws.write(0, 1, name)
        ws.write(2, 0, "Portfolio Statement as on October 31, 2026")
        for j, h in enumerate(LEGACY_HEADER):
            ws.write(3, j, h)
        ws.write(5, 0, "Equity & Equity Related")
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                ws.write(6 + i, j, v)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    print("wrote %s" % path.relative_to(ROOT))


if __name__ == "__main__":
    main()
