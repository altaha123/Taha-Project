"""
Regenerate frontend/tests/fixtures/fundamentals-reliance.json.

The browser test needs a /fundamentals payload, and hand-writing one is how a
fixture drifts from the endpoint it stands for: a key renamed in
fundamentals.py keeps passing against a JSON literal that still has the old
name, and the bug ships. So the fixture is produced by the real module, from
stubbed filings, and checked in.

    python backend/tests/make_fundamentals_fixture.py

Reliance's real figures for the last six quarters, with one deliberate
alteration: the June 2025 quarter is made a loss, so the turnaround wording —
which must never be a percentage — is exercised on screen and not only in a
unit test. Standalone rows are included at roughly the real ratio to the
consolidated ones, because the basis-mixing bug is invisible in a fixture that
only has one basis.
"""

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

OUT = ROOT / "frontend" / "tests" / "fixtures" / "fundamentals-reliance.json"

ENDS = ["2026-06-30", "2026-03-31", "2025-12-31",
        "2025-09-30", "2025-06-30", "2025-03-31"]
STARTS = ["2026-04-01", "2026-01-01", "2025-10-01",
          "2025-07-01", "2025-04-01", "2025-01-01"]
REVENUE = [269496e7, 264573e7, 248160e7, 240357e7, 243832e7, 236533e7]
PAT = [22290e7, 22611e7, 21930e7, 18165e7, -4300e7, 18951e7]


def _quarter(i, consolidated):
    r = REVENUE[i] * (1.0 if consolidated else 0.45)
    p = PAT[i] * (1.0 if consolidated else 0.42)
    return {
        "to": ENDS[i], "from": STARTS[i], "consolidated": consolidated,
        "filed_at": "20-Jul-2026 19:41:02",
        "company": "Reliance Industries Limited", "audited": "Unaudited",
        "source_url": "https://nsearchives.nseindia.com/corporate/xbrl/RESULT_%s_%s.xml"
                      % (ENDS[i], "C" if consolidated else "S"),
        "revenue": r, "other_income": r * 0.0185, "total_income": r * 1.0185,
        "materials": r * 0.4058, "employee_cost": r * 0.0290,
        "finance_cost": r * 0.0233, "depreciation": r * 0.0509,
        "other_expenses": r * 0.1613, "total_expenses": r * 0.9086,
        "ebitda": r * 0.1708, "pbt_before_exceptional": p * 1.294,
        "exceptional": 0.0, "pbt": p * 1.294, "tax": p * 0.294, "pat": p,
        "eps_basic": round(p / 1.353e9, 2),
    }


def main():
    quarters = [_quarter(i, con) for i in range(len(ENDS)) for con in (True, False)]

    stub = types.ModuleType("xbrl")
    stub.available = lambda: True
    stub.filings = lambda symbol: quarters

    def statements(symbol, limit=8, consolidated=None):
        want = [q for q in quarters if consolidated is None
                or q.get("consolidated") is consolidated]
        return (want or quarters)[:limit]

    stub.statements = statements
    sys.modules["xbrl"] = stub

    import fundamentals
    payload = fundamentals.series("RELIANCE", quarters=6)
    assert payload["available"] and payload["count"] == 6, payload.get("message")
    assert payload["basis"] == "consolidated"
    assert payload["rows"][0]["yoy"]["pat"]["kind"] == "loss_to_profit"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print("wrote %s (%d quarters, %s)"
          % (OUT.relative_to(ROOT), payload["count"], payload["basis"]))


OUT_POSITION = OUT.with_name("fundamentals-reliance-position.json")
OUT_PEERS = OUT.with_name("fundamentals-reliance-peers.json")


def stored():
    """
    The balance sheet, cash flow and industry payloads, from the real module
    reading a real (temporary) store. A September half-year cash flow is
    included so the browser test can assert it never sits beside the years.
    """
    import datetime as dt
    import os
    import tempfile
    os.environ["ALTAHA_FUNDAMENTALS_DB"] = os.path.join(tempfile.mkdtemp(), "f.db")
    sys.modules.pop("fundamentals_store", None)
    import fundamentals_store as st
    import fundamentals

    def meta(sym, end, **kw):
        return {"symbol": sym, "company": sym.title() + " Limited", "basis": "consolidated",
                "label": kw.pop("label", end), "period_end": end,
                "filed_at": "2026-05-01", "source_url": "https://x/%s-%s.xml" % (sym, end), **kw}

    sheets = [("2026-03-31", "Mar 2026", 1950000, 850000, 370000, 115000),
              ("2025-09-30", "Sep 2025", 1880000, 820000, 360000, 98000),
              ("2025-03-31", "Mar 2025", 1810000, 790000, 352000, 106000),
              ("2024-09-30", "Sep 2024", 1760000, 760000, 341000, 91000)]
    st.upsert("balance", [st.to_row("balance", meta("RELIANCE", e, label=l), {
        "total_assets": a * 1e7, "total_equity": q * 1e7, "total_borrowings": d * 1e7,
        "cash_and_equivalents": c * 1e7, "net_debt": (d - c) * 1e7,
        "ppe": a * 0.42e7, "inventories": a * 0.08e7, "trade_receivables": a * 0.02e7,
        "current_assets": a * 0.26e7, "current_liabilities": a * 0.24e7,
        "debt_equity_x": round(d / q, 2), "current_ratio_x": round(0.26 / 0.24, 2)})
        for e, l, a, q, d, c in sheets])
    flows = [("2026-03-31", "FY26", 12, 178000, 131000),
             ("2025-09-30", "H1 FY26", 6, 82000, 64000),
             ("2025-03-31", "FY25", 12, 158000, 138000),
             ("2024-03-31", "FY24", 12, 159000, 152000)]
    st.upsert("cashflow", [st.to_row("cashflow", meta("RELIANCE", e, label=l, months=m), {
        "cfo": o * 1e7, "capex": x * 1e7, "fcf": (o - x) * 1e7, "dividends_paid": 6800e7})
        for e, l, m, o, x in flows])
    st.upsert("income", [st.to_row("income", meta("RELIANCE", e, label=l, freq="annual", months=12),
                                    {"revenue": r * 1e7, "pat": p * 1e7})
                         for e, l, r, p in (("2026-03-31", "FY26", 1017000, 84997),
                                            ("2025-03-31", "FY25", 964693, 81309),
                                            ("2024-03-31", "FY24", 901064, 79020))])
    position = fundamentals.position_from_store("RELIANCE")
    assert position["available"]
    assert [r["label"] for r in position["cashflow"]["rows"]] == ["FY26", "FY25", "FY24"]

    peers = ["IOC", "BPCL", "HINDPETRO", "MRPL", "CHENNPETRO", "GULFOILLUB"]
    q = []
    for i, s in enumerate(["RELIANCE"] + peers):
        opm = 17.1 if s == "RELIANCE" else 6 + i * 1.5
        q.append(st.to_row("income", meta(s, "2026-06-30", label="Q1 FY27", freq="quarterly",
                                          months=3), {"revenue": 1e11, "pat": 8e9}))
        q[-1].update(opm_pct=opm, net_margin_pct=opm / 2, revenue_yoy_pct=4 + i,
                     pat_yoy_pct=10 - i)
        if s != "RELIANCE":
            st.upsert("balance", [st.to_row("balance", meta(s, "2026-03-31"), {
                "total_equity": 1e12, "debt_equity_x": 0.3 + i / 10, "current_ratio_x": 1 + i / 10})])
            q.append(st.to_row("income", meta(s, "2026-03-31", freq="annual", months=12),
                               {"revenue": 4e11, "pat": 1e11 + i * 1e10}))
    st.upsert("income", q)
    out = fundamentals.peers_from_store("RELIANCE", "Refineries & Marketing",
                                        ["RELIANCE"] + peers, today=dt.date(2026, 9, 25))
    assert out["available"] and out["peers_read"] == 6

    OUT_POSITION.write_text(json.dumps(position, indent=1) + "\n", encoding="utf-8")
    OUT_PEERS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("wrote %s and %s" % (OUT_POSITION.relative_to(ROOT), OUT_PEERS.relative_to(ROOT)))


OUT_SCREENS = OUT.with_name("fundamentals-screens.json")


def screens():
    """
    The screens index and every screen's matches, from the real module over a
    temporary store holding:

      · two growers, one on each route (four quarters above 20%; two of 16%
        with the margin up 3 points), and a lender on the first route, which
        is shown without an operating margin;
      · one operational turnaround, whose year-ago loss is printed;
      · two compounders, one with a stored price (so a free cash flow yield)
        and one without, which follows it;
      · a stale company that would be a grower and a turnaround if its
        quarter were current.

    No scan is on record, so no turnover test runs.
    """
    import datetime as dt
    import os
    import tempfile
    os.environ["ALTAHA_FUNDAMENTALS_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
    for m in ("fundamentals_store", "fundamentals_screens"):
        sys.modules.pop(m, None)
    import fundamentals_store as st
    import fundamentals_screens as sc
    import fundamentals as F
    sc._scan_market = lambda today: {}
    today = dt.date(2026, 9, 25)

    def meta(sym, co, end, freq=None, months=None):
        e = dt.date.fromisoformat(end)
        label = F.quarter_label(e) if freq == "quarterly" else "FY%s" % end[2:4]
        return {"symbol": sym, "company": co, "basis": "consolidated", "freq": freq,
                "label": label, "period_end": end, "months": months,
                "filed_at": (e + dt.timedelta(days=45)).isoformat() + " 18:00:00",
                "source_url": "https://x/%s-%s.xml" % (sym, end)}

    def q(sym, co, end, rev, pat, opm=15.0, oi=None, pbt=None, eps=None):
        pbt = pat * 1.3 if pbt is None else pbt
        r = st.to_row("income", meta(sym, co, end, "quarterly", 3), {
            "revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": rev * opm / 100 * 1e7,
            "exceptional": 0.0, "pbt": pbt * 1e7, "pbt_before_exceptional": pbt * 1e7,
            "other_income": (rev * 0.005 if oi is None else oi) * 1e7,
            "eps_basic": eps if eps is not None else round(pat / 10, 2)})
        r["opm_pct"] = opm
        return r

    ends = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
            "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
    rows = [q("TRENT", "Trent Limited", e, 5200 if i < 4 else 4100, 420,
              opm=17.0 if i < 4 else 15.5) for i, e in enumerate(ends)]
    rows += [q("KPITTECH", "KPIT Technologies Limited", e,
               (1650, 1650, 1500, 1500)[i] if i < 4 else 1420, 210,
               opm=21.0 if i == 0 else 18.0) for i, e in enumerate(ends)]
    # A lender's "operating margin" says nothing about it; 70% is what the
    # formula gives a bank, and it is never shown or tested.
    rows += [q("BAJFINANCE", "Bajaj Finance Limited", e, 12500 if i < 4 else 10000, 4200,
               opm=70.0 if i < 4 else 74.0) for i, e in enumerate(ends)]
    rows += [q("VODAIDEA", "Vodafone Idea Limited", ends[0], 11100, 310, opm=43.2,
               oi=50, pbt=400),
             q("VODAIDEA", "Vodafone Idea Limited", ends[4], 10500, -6400, opm=40.0,
               oi=60, pbt=-6400)]
    rows += [q("OLDCO", "Old Company Limited", e, 900 if i < 4 else 700, 40 if i < 4 else -20)
             for i, e in enumerate(["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30",
                                    "2024-06-30", "2024-03-31", "2023-12-31", "2023-09-30"])]
    years = ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]
    for sym, co, revs, pat, pbt, fcfs, eq, debt, cash in (
            ("PAGEIND", "Page Industries Limited", (5000, 4600, 4250, 3900), 700, 940,
             (750, 600, 520), 1900, 50, 700),
            ("ECLERX", "eClerx Services Limited", (3600, 3150, 2900, 2600), 520, 700,
             (480, 410, 360), 1800, 40, 600)):
        rows += [st.to_row("income", meta(sym, co, e, "annual", 12),
                           {"revenue": r * 1e7, "pat": (pat if i == 0 else pat * 0.9) * 1e7,
                            "pbt": pbt * 1e7, "finance_cost": 20e7})
                 for i, (e, r) in enumerate(zip(years, revs))]
        st.upsert("cashflow", [st.to_row("cashflow", {**meta(sym, co, e, None, 12)}, {
            "cfo": (f + 150) * 1e7, "capex": 150e7, "fcf": f * 1e7})
            for e, f in zip(years, fcfs)])
        st.upsert("balance", [st.to_row("balance", meta(sym, co, e), {
            "total_assets": (eq + debt) * 1.6e7, "total_equity": eq * k * 1e7,
            "total_borrowings": debt * 1e7, "cash_and_equivalents": cash * 1e7,
            "net_debt": (debt - cash) * 1e7, "debt_equity_x": round(debt / (eq * k), 2)})
            for e, k in ((years[0], 1.0), (years[1], 0.88))])
        # The latest quarter: its profit and EPS give the share count a
        # market value is worked out from.
        rows.append(q(sym, co, ends[0], revs[0] / 4, pat / 4, eps={"PAGEIND": 156.9,
                                                                   "ECLERX": 27.1}[sym]))
    st.upsert("income", rows)
    for s_ in ("TRENT", "KPITTECH", "BAJFINANCE", "VODAIDEA", "OLDCO", "PAGEIND", "ECLERX"):
        st.recompute_yoy(s_)
    st.record_yf_profile("PAGEIND", {"longName": "Page Industries Limited",
                                     "sector": "Consumer Cyclical",
                                     "industry": "Apparel Manufacturing",
                                     "sharesOutstanding": 11153874, "currentPrice": 45000,
                                     "currency": "INR"})
    idx = sc.index(today=today)
    detail = {s["id"]: sc.detail(s["id"], today=today) for s in sc.SCREENS}
    names = {k: [m["symbol"] for m in d["matches"]] for k, d in detail.items()}
    assert sorted(names["steady_growers"]) == ["BAJFINANCE", "KPITTECH", "TRENT"], names
    assert names["turnarounds"] == ["VODAIDEA"], names
    assert names["fcf_compounders"] == ["PAGEIND", "ECLERX"], names
    OUT_SCREENS.write_text(json.dumps({"index": idx, "detail": detail}, indent=1) + "\n", encoding="utf-8")
    print("wrote %s" % OUT_SCREENS.relative_to(ROOT))


if __name__ == "__main__":
    main()
    stored()
    screens()
