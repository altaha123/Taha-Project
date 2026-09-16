"""
Regenerate frontend/tests/fixtures/investors-*.json.

The browser test needs /investors and /investor payloads, and hand-writing
them is how a fixture drifts from the endpoint it stands for. These are
produced by the real modules from filings shaped exactly like the ones NSE
serves — including the three cases the page exists to get right:

  · a rolled-up total (Atul Auto: him, plus his company)
  · one name filed twice in one register (Titan: two folios)
  · a family trust whose trustee is named inside the string, worded the way
    Metro Brands actually words it

    python backend/tests/make_investors_fixture.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

OUT = ROOT / "frontend" / "tests" / "fixtures"


def _n(name, pct, shares=None, promoter=False, kind="Other"):
    return {"name": name, "pct": pct, "shares": shares, "kind": kind,
            "promoter": promoter}


FILINGS = {
    # symbol -> period -> rows.  The June quarter is the newest.
    "ATULAUTO": {
        "2026-06-30": [_n("VIJAY KEDIA", 18.20, 4_00_00_000),
                       _n("KEDIA SECURITIES PRIVATE LIMITED", 2.71, 59_00_000)],
        "2026-03-31": [_n("VIJAY KEDIA", 17.60, 3_86_00_000),
                       _n("KEDIA SECURITIES PRIVATE LIMITED", 2.71, 59_00_000)],
    },
    "REPRO": {
        "2026-06-30": [_n("Vijay Kishanlal Kedia", 6.32, 87_00_000)],
        "2026-03-31": [_n("Vijay Kishanlal Kedia", 6.32, 87_00_000)],
    },
    "ELECON": {
        "2026-06-30": [_n("Vijay Kishanlal Kedia", 1.00, 1_12_00_000)],
    },
    "VAIBHAVGBL": {
        "2026-03-31": [_n("VIJAY KEDIA", 2.80, 46_00_000)],
    },
    "TITAN": {
        "2026-06-30": [_n("Rekha Jhunjhunwala", 4.24), _n("Rekha Jhunjhunwala", 1.07),
                       _n("Life Insurance Corporation Of India", 2.34, kind="Insurance")],
        "2026-03-31": [_n("Rekha Jhunjhunwala", 4.24), _n("Rekha Jhunjhunwala", 1.07)],
    },
    "METROBRAND": {
        "2026-06-30": [
            _n("ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
            _n("ARYAVIR JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
            _n("NISHTHA JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
        ],
        "2026-03-31": [
            _n("ARYAMAN JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
            _n("ARYAVIR JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
            _n("NISHTHA JHUNJHUNWALA DISCRETIONARY TRUST (TRUSTEE - REKHA RAKESH JHUNJHUNWALA)", 4.79),
        ],
    },
    "STARHEALTH": {
        "2026-06-30": [_n("Rekha Jhunjhunwala", 3.04, promoter=True)],
        "2026-03-31": [_n("Rekha Jhunjhunwala", 3.51, promoter=True)],
    },
    "CRISIL": {
        "2026-03-31": [_n("Rekha Jhunjhunwala", 5.19)],
    },
}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        import os
        os.environ["ALTAHA_HOLDINGS_DB"] = str(Path(tmp) / "fixture.db")
        for m in ("holdings_store", "investors"):
            sys.modules.pop(m, None)
        import holdings_store as store
        import investors as inv

        for sym, byq in FILINGS.items():
            for period, rows in byq.items():
                store.record_filing(
                    sym, period, rows, filed=period,
                    source_url="https://nsearchives.nseindia.com/corporate/xbrl/SHP_%s_%s"
                               % (sym, period))

        OUT.mkdir(parents=True, exist_ok=True)

        directory = {"available": True, "investors": inv.listing(),
                     "ledger": {"companies_read": store.stats()["companies"],
                                "latest_period": store.latest_period(),
                                "rows": store.stats()["rows"],
                                "persistent": True}}
        (OUT / "investors-directory.json").write_text(
            json.dumps(directory, indent=1) + "\n", encoding="utf-8")

        for who in ("vijay-kedia", "rekha-jhunjhunwala", "rakesh-jhunjhunwala",
                    "dolly-khanna"):
            d = inv.portfolio(who)
            (OUT / ("investors-%s.json" % who)).write_text(
                json.dumps(d, indent=1) + "\n", encoding="utf-8")

        kedia = inv.portfolio("vijay-kedia")
        atul = next(p for p in kedia["positions"] if p["symbol"] == "ATULAUTO")
        assert abs(atul["pct"] - 20.91) < 1e-6 and atul["split"]
        rekha = inv.portfolio("rekha-jhunjhunwala")
        titan = next(p for p in rekha["positions"] if p["symbol"] == "TITAN")
        assert abs(titan["pct"] - 5.31) < 1e-6, "the two folios must be summed"
        metro = next(p for p in rekha["positions"] if p["symbol"] == "METROBRAND")
        assert abs(metro["pct"] - 14.37) < 1e-6
        assert all(p["relation"] == "trust" for p in metro["parts"])
        assert inv.portfolio("rakesh-jhunjhunwala")["redirected_from"]
        assert inv.portfolio("dolly-khanna")["available"] is False
        print("wrote %d fixtures to %s" % (5, OUT.relative_to(ROOT)))


if __name__ == "__main__":
    main()
