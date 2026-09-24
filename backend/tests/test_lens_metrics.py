"""
Lens metrics and the nightly compute, against real-shaped fundamentals rows.

What these guard against: a "5-year" figure computed over four years because
a filing was missing, a ratio across a zero or negative base, a peer rank
published when most of the industry has not been read, and a compute that
writes results nobody can read back.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TODAY = dt.date(2026, 9, 1)


def annual(sym, fy_end_year, revenue, ebitda, pbt, fin, dep, pat, eps, basis="consolidated"):
    return {"symbol": sym, "company": sym.title() + " Ltd", "basis": basis, "freq": "annual",
            "period_end": "%d-03-31" % fy_end_year, "months": 12, "revenue_cr": revenue,
            "ebitda_cr": ebitda, "pbt_cr": pbt, "pbt_before_exceptional_cr": pbt,
            "finance_cost_cr": fin, "depreciation_cr": dep, "pat_cr": pat, "eps_basic": eps,
            "tax_rate_pct": 25.0}


def quarter(sym, end, eps, basis="consolidated"):
    return {"symbol": sym, "company": sym.title() + " Ltd", "basis": basis, "freq": "quarterly",
            "period_end": end, "months": 3, "eps_basic": eps, "revenue_cr": 100.0,
            "ebitda_cr": 20.0, "pbt_cr": 15.0, "pbt_before_exceptional_cr": 15.0,
            "finance_cost_cr": 1.0, "depreciation_cr": 2.0, "pat_cr": 11.0, "tax_rate_pct": 25.0}


def balance(sym, year, ta, ca, cl, equity, capital, borrow=10.0, basis="consolidated"):
    return {"symbol": sym, "basis": basis, "period_end": "%d-03-31" % year,
            "total_assets_cr": ta, "current_assets_cr": ca, "current_liabilities_cr": cl,
            "total_equity_cr": equity, "equity_to_owners_cr": equity,
            "equity_capital_cr": capital, "total_borrowings_cr": borrow,
            "borrowings_current_cr": 5.0, "cash_and_equivalents_cr": 10.0,
            "current_investments_cr": 0.0, "other_bank_balances_cr": 0.0,
            "debt_equity_x": round(borrow / equity, 3)}


def cashflow(sym, year, capex, fcf, basis="consolidated"):
    return {"symbol": sym, "basis": basis, "period_end": "%d-03-31" % year, "months": 12,
            "capex_cr": capex, "fcf_cr": fcf, "cfo_cr": capex + fcf}


def grower(sym="GROW", start=2019, n=8, g=0.2):
    """A company growing revenue 20% a year with a steady 20% margin."""
    inc, rev, eps = [], 100.0, 5.0
    for i in range(n):
        y = start + i
        inc.append(annual(sym, y, round(rev, 4), round(rev * .2, 4), round(rev * .15, 4),
                          1.0, 2.0, round(rev * .11, 4), round(eps, 4)))
        rev *= 1 + g
        eps *= 1.25
    return inc


@pytest.fixture()
def M():
    import lens_metrics
    return lens_metrics


def company(M, inc, bal=(), cfs=()):
    return M.Company(inc[0]["symbol"], list(inc), list(bal), list(cfs), today=TODAY)


def test_years_are_arranged_latest_first_and_a_gap_is_kept_as_a_gap(M):
    inc = [r for r in grower() if r["period_end"] != "2021-03-31"]
    c = company(M, inc)
    assert c.years[0]["period_end"] == "2026-03-31"
    assert c.years[5] is None                       # FY21 is missing, not skipped over
    assert c.years[6]["period_end"] == "2020-03-31"
    assert M._revenue_cagr(c, 5, {}) is None        # so no 5-year CAGR is claimed
    assert M._revenue_cagr(c, 4, {})["value"] == pytest.approx(20.0, abs=0.01)
    assert M._revenue_growth_min(c, 5, {}) is None  # nor "every year" across the gap


def test_revenue_cagr_spans_exactly_n_years(M):
    c = company(M, grower())
    got = M._revenue_cagr(c, 5, {})
    assert got["value"] == pytest.approx(20.0, abs=0.01)
    assert "FY21" in got["note"] and "FY26" in got["note"]


def test_a_stale_company_has_no_years(M):
    c = M.Company("OLD", grower(start=2012, n=8), [], [], today=TODAY)   # latest FY19
    assert c.years == []


def test_one_basis_is_used_never_a_mix(M):
    inc = grower() + [annual("GROW", 2026, 99999, 1, 1, 1, 1, 1, 1, basis="standalone")]
    c = company(M, inc)
    assert c.basis == "consolidated"
    assert c.revenue(c.year(0)) != 99999


def test_a_missing_year_is_summed_from_its_four_quarters(M):
    inc = [r for r in grower() if r["period_end"] != "2026-03-31"]
    inc += [quarter("GROW", e, 1.5) for e in ("2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31")]
    c = company(M, inc)
    y0 = c.year(0)
    assert y0["period_end"] == "2026-03-31" and y0["derived_from_quarters"]
    assert y0["revenue_cr"] == 400.0 and y0["eps_basic"] == 6.0


def test_roce_roe_and_their_history(M):
    inc = grower()
    bal = [balance("GROW", y, ta=200 + 10 * i, ca=80, cl=40, equity=150, capital=10)
           for i, y in enumerate(range(2023, 2027))]
    c = company(M, inc, bal)
    y0 = c.year(0)
    ebit = y0["pbt_cr"] + y0["finance_cost_cr"]
    assert M._roce(c, 1, {})["value"] == pytest.approx(ebit / (230 - 40) * 100, abs=0.01)
    assert M._roe(c, 1, {})["value"] == pytest.approx(y0["pat_cr"] / 150 * 100, abs=0.01)
    assert M._roce_change(c, 3, {}) is not None
    assert M._roe_min(c, 10, {}) is None           # four balance sheets are not ten years


def test_eps_growth_uses_trailing_quarters_and_refuses_a_negative_base(M):
    ends = ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31",
            "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
    qs = [quarter("Q", e, 1.0) for e in ends[:4]] + [quarter("Q", e, 1.3) for e in ends[4:]]
    c = company(M, qs)
    assert M._eps_growth(c, 1, {})["value"] == pytest.approx(30.0)
    qs = [quarter("Q", e, -1.0) for e in ends[:4]] + [quarter("Q", e, 1.3) for e in ends[4:]]
    assert M._eps_growth(company(M, qs), 1, {}) is None


def test_peg_fails_outright_for_a_loss_and_is_na_without_a_price(M):
    inc = grower()
    c = company(M, inc)
    assert M._peg(c, 3, {"prices": {}}) is None
    got = M._peg(c, 3, {"prices": {"GROW": 100.0}})
    eps = inc[-1]["eps_basic"]
    assert got["value"] == pytest.approx((100.0 / eps) / 25.0, abs=1e-3)
    loss = grower()
    loss[-1] = dict(loss[-1], eps_basic=-2.0)
    got = M._peg(company(M, loss), 3, {"prices": {"GROW": 100.0}})
    assert got["value"] is None and "not positive" in got["fail"]


def test_share_count_from_paid_up_capital(M):
    inc = grower()
    bal = [balance("GROW", 2023, 200, 80, 40, 150, capital=10.0),
           balance("GROW", 2026, 200, 80, 40, 150, capital=9.0)]
    got = M._share_count_cagr(company(M, inc, bal), 3, {})
    assert got["value"] == pytest.approx(((9 / 10) ** (1 / 3) - 1) * 100, abs=0.01)


def test_pledge_and_promoter_change(M):
    rows = [{"period_end": "2026-06-30", "promoter_pct": 55.0, "fii_pct": 8, "dii_pct": 7,
             "pledged": 0, "pledge_pct": None},
            {"period_end": "2025-06-30", "promoter_pct": 54.0, "fii_pct": 8, "dii_pct": 7,
             "pledged": 0, "pledge_pct": None}]
    c = company(M, grower())
    ctx = {"shareholding": rows}
    assert M._pledge(c, 0, ctx)["value"] == 0.0
    assert M._promoter_change(c, 1, ctx)["value"] == pytest.approx(1.0)
    assert M._fii_dii(c, 0, ctx)["value"] == 15
    ctx = {"shareholding": [dict(rows[0], pledged=1)]}
    assert "pledged" in M._pledge(c, 0, ctx)["fail"]
    ctx = {"shareholding": [dict(rows[0], pledged=None)]}
    assert M._pledge(c, 0, ctx) is None


def test_reinvestment_rate(M):
    inc = grower()
    bal = [balance("GROW", y, 200, 80 + 5 * i, 40, 150, 10) for i, y in enumerate(range(2023, 2027))]
    cfs = [cashflow("GROW", y, capex=20.0, fcf=5.0) for y in range(2024, 2027)]
    got = M._reinvestment_rate(company(M, inc, bal, cfs), 3, {})
    assert got is not None and got["value"] > 0


def test_peer_ranks_wait_until_most_of_the_industry_is_read(M):
    req = [("industry_revenue_rank", 1)]
    profiles = {s: {"industry": "Cement"} for s in ("A", "B", "C", "D", "E")}
    summaries = [{"symbol": s, "company": s, "industry": "Cement", "revenue": r,
                  "revenue_fy": "FY26", "margins": {}, "mcap_cr": None, "stdev": {}}
                 for s, r in (("A", 500), ("B", 900))]
    out = M.peer_metrics(summaries, req, profiles, 5)
    assert out["A"]["industry_revenue_rank@1"]["value"] is None
    assert "2 of 5" in out["A"]["industry_revenue_rank@1"]["note"]
    summaries += [{"symbol": s, "company": s, "industry": "Cement", "revenue": r,
                   "revenue_fy": "FY26", "margins": {}, "mcap_cr": None, "stdev": {}}
                  for s, r in (("C", 100), ("D", 700))]
    out = M.peer_metrics(summaries, req, profiles, 5)
    assert out["B"]["industry_revenue_rank@1"]["value"] == 1
    assert out["D"]["industry_revenue_rank@1"]["value"] == 2
    assert out["A"]["industry_revenue_rank@1"]["display"] == "#3 of 4"


def test_size_band_by_market_value_rank(M):
    summaries = [{"symbol": "S%03d" % i, "company": "", "industry": None, "revenue": None,
                  "revenue_fy": None, "margins": {}, "mcap_cr": 1e6 - i, "stdev": {}}
                 for i in range(300)]
    out = M.peer_metrics(summaries, [("size_band", 0)], {}, 300)
    assert out["S000"]["size_band@0"]["value"] == "large"
    assert out["S150"]["size_band@0"]["value"] == "mid"
    assert out["S299"]["size_band@0"]["value"] == "small"
    out = M.peer_metrics(summaries[:100], [("size_band", 0)], {}, 300)
    assert out["S000"]["size_band@0"]["value"] is None


# ---------------------------------------------------------------------------
# End to end: fundamentals tables -> compute -> the cache the endpoints read
# ---------------------------------------------------------------------------

@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    monkeypatch.setenv("ALTAHA_LENS_DB", str(tmp_path / "l.db"))
    for mod in ("fundamentals_store", "lens_store", "lens_job"):
        sys.modules.pop(mod, None)
    import fundamentals_store as fs
    import lens_store as ls
    import lens_job
    return fs, ls, lens_job


def _load(fs, rows_by_table):
    conn = fs._connect()
    for table, rows in rows_by_table.items():
        for r in rows:
            cols = list(r)
            conn.execute("INSERT INTO %s (%s, updated_utc, first_seen_utc) VALUES (%s, 'x', 'x')"
                         % (table, ", ".join(cols), ", ".join("?" * len(cols))),
                         [r[c] for c in cols])
    conn.commit()


def test_migration_runs_once_and_is_recorded(stores):
    _fs, ls, _job = stores
    st = ls.stats()
    assert st["migrations"] == ["001_init.sql"]
    assert ls.migrate(ls._connect()) == []


def test_compute_writes_a_run_the_endpoints_can_read(stores):
    fs, ls, job = stores
    inc = grower("GROW")
    # Cannibal: paid-up capital down 12% over three years.
    bal = [balance("GROW", y, 200, 80, 40, 150, capital=c)
           for y, c in ((2023, 10.0), (2024, 9.6), (2025, 9.2), (2026, 8.8))]
    cfs = [cashflow("GROW", y, 20.0, 5.0) for y in range(2021, 2027)]
    _load(fs, {"income_statement": inc, "balance_sheet": bal, "cash_flow": cfs})
    ls.upsert_company({"symbol": "GROW", "company": "Grow Ltd", "industry": "Cement",
                       "issued_shares": 1e8, "last_price": 200.0})
    ls.upsert_shareholding([{"symbol": "GROW", "period_end": "2026-06-30", "promoter_pct": 60,
                             "fii_pct": 5, "dii_pct": 4, "pledged": 0},
                            {"symbol": "GROW", "period_end": "2025-06-30", "promoter_pct": 58,
                             "fii_pct": 5, "dii_pct": 4, "pledged": 0}])

    out = job.compute(today=TODAY, prices={}, universe_size=1)
    assert out["companies"] == 1
    assert set(out["lenses"]) == {"gorilla", "tenbagger", "qglp", "akre", "nomad", "cannibal", "owner"}
    run = ls.latest_run()
    assert run and run["run_id"] == out["run_id"]

    got = {r["lens_id"]: r for r in ls.results(run["run_id"], symbol="GROW")}
    assert got["cannibal"]["status"] == "pass"
    assert got["owner"]["status"] == "pass"
    assert all(r["result"] == "pass" for r in got["owner"]["rules"])
    assert "moat" not in got                          # coming soon: never computed
    assert ls.convergence(run["run_id"], 2)[0]["symbol"] == "GROW"


def test_an_old_run_is_pruned_after_newer_ones(stores):
    fs, ls, job = stores
    _load(fs, {"income_statement": grower("GROW")})
    ids = [job.compute(today=TODAY, prices={}, universe_size=1)["run_id"] for _ in range(ls.KEEP_RUNS + 1)]
    assert ls.results(ids[0]) == []
    assert ls.results(ids[-1])


# ---------------------------------------------------------------------------
# The inputs the crawl reads: the pledge in a shareholding filing, and NSE's
# industry, share count and price from the quote API.
# ---------------------------------------------------------------------------

FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize("name,flag,count", [
    ("shp_reliance_2021q2.xml", 0, 0.0),     # 2020 taxonomy: a filed share count
    ("shp_reliance_2026q1.xml", 0, None),    # 2025 taxonomy: a yes/no declaration
])
def test_the_pledge_is_read_from_both_filing_formats(name, flag, count):
    import shareholding_filings as sf
    import lens_data_crawl as ldc
    parsed = sf.parse((FIX / name).read_text(encoding="utf-8"))
    assert parsed["pledge"]["pledged"] == flag
    assert parsed["pledge"]["pledged_shares"] == count
    parsed.update(period="2026-06-30", source="https://x/shp.xml")
    (row,) = ldc.shareholding_rows("RELIANCE", [parsed])
    assert row["pledged"] == 0 and 50 < row["promoter_pct"] < 51
    assert row["fii_pct"] and row["dii_pct"]


def test_a_declared_pledge_is_a_yes():
    import shareholding_filings as sf
    xml = (FIX / "shp_reliance_2026q1.xml").read_text(encoding="utf-8")
    xml = xml.replace(">false<", ">true<")
    assert sf.parse(xml)["pledge"]["pledged"] == 1


def test_quote_parsing_keeps_industry_shares_and_price():
    import lens_data_crawl as ldc
    body = {"info": {"companyName": "Reliance Industries Limited"},
            "industryInfo": {"macro": "Energy", "sector": "Oil Gas & Consumable Fuels",
                             "industry": "Petroleum Products",
                             "basicIndustry": "Refineries & Marketing"},
            "securityInfo": {"issuedSize": 13532472634, "faceValue": 10},
            "priceInfo": {"lastPrice": 1412.5},
            "metadata": {"lastUpdateTime": "22-Sep-2026 16:00:00"}}
    row = ldc.parse_quote("RELIANCE", body)
    assert row["industry"] == "Petroleum Products"
    assert row["issued_shares"] == 13532472634 and row["last_price"] == 1412.5
    assert ldc.parse_quote("X", {}) is None
    assert ldc.parse_quote("X", None) is None


# ---------------------------------------------------------------------------
# The endpoints, reading a computed run
# ---------------------------------------------------------------------------

@pytest.fixture()
def api(stores, monkeypatch):
    from fastapi.testclient import TestClient
    fs, ls, job = stores
    import main
    monkeypatch.setattr(main, "lens_store", ls)
    monkeypatch.setattr(main, "lens_job", job)
    inc = grower("GROW")
    bal = [balance("GROW", y, 200, 80, 40, 150, capital=c)
           for y, c in ((2023, 10.0), (2024, 9.6), (2025, 9.2), (2026, 8.8))]
    _load(fs, {"income_statement": inc, "balance_sheet": bal})
    ls.upsert_shareholding([{"symbol": "GROW", "period_end": "2026-06-30", "promoter_pct": 60,
                             "fii_pct": 5, "dii_pct": 4, "pledged": 0},
                            {"symbol": "GROW", "period_end": "2025-06-30", "promoter_pct": 58,
                             "fii_pct": 5, "dii_pct": 4, "pledged": 0}])
    job.compute(today=TODAY, prices={}, universe_size=1)
    return TestClient(main.app)


def test_the_four_lens_endpoints(api):
    idx = api.get("/api/lenses").json()
    assert len(idx["lenses"]) == 10 and "not investment advice" in idx["notice"]
    by = {l["id"]: l for l in idx["lenses"]}
    assert by["cannibal"]["counts"]["pass"] == 1
    assert by["moat"]["status"] == "coming_soon" and by["moat"]["coming_soon_reason"]

    one = api.get("/api/lenses/cannibal").json()
    assert [r["symbol"] for r in one["passing"]] == ["GROW"]
    assert one["passing"][0]["rules"][0]["result"] == "pass"
    assert api.get("/api/lenses/moat").json()["passing"] == []
    assert api.get("/api/lenses/nope").status_code == 404

    stock = api.get("/api/lenses/stock/grow.ns").json()
    assert stock["symbol"] == "GROW" and stock["covered"]
    assert stock["meets"] >= 2 and stock["live_lenses"] == 7

    conv = api.get("/api/lenses/convergence?min_lenses=2").json()
    assert conv["stocks"][0]["symbol"] == "GROW"
    assert {l["id"] for l in conv["stocks"][0]["lenses"]} >= {"cannibal", "owner"}


# ---------------------------------------------------------------------------
# The Run button's job: compute, read inputs slice by slice, recompute
# ---------------------------------------------------------------------------

def test_the_run_job_computes_reads_and_recomputes(stores, monkeypatch):
    fs, ls, job = stores
    _load(fs, {"income_statement": grower("GROW")})
    for mod in ("lens_runner",):
        sys.modules.pop(mod, None)
    import lens_runner
    import lens_data_crawl
    slices = iter([{"attempted": 25, "ok": 25}] * 5 + [{"attempted": 0, "stopped_early": "nothing due"}])
    monkeypatch.setattr(lens_data_crawl, "run", lambda limit=25: next(slices))
    monkeypatch.setattr(lens_data_crawl, "universe", lambda: ["GROW"])
    import threading
    gate = threading.Event()

    def compute(**kw):
        gate.wait(5)                             # hold the job open for the second press
        return {"run_id": 7, "counts": {"cannibal": {"pass": 1}}}
    monkeypatch.setattr(job, "compute", compute)

    st = lens_runner.start()
    assert st["started"] is True
    again = lens_runner.start()
    assert again["started"] is False            # one job at a time
    gate.set()
    st = lens_runner.wait()
    assert st["phase"] == "done" and not st["running"] and st["error"] is None
    assert st["companies_read"] == 125 and st["slices"] == 6
    # Once at the start, once after four slices, once at the end.
    assert st["computes"] == 3
    assert st["last_run_id"] == 7


def test_the_run_job_stops_when_the_exchange_keeps_refusing(stores, monkeypatch):
    fs, ls, job = stores
    sys.modules.pop("lens_runner", None)
    import lens_runner
    import lens_data_crawl
    monkeypatch.setattr(lens_runner, "PAUSE_ON_REFUSAL", 0)
    monkeypatch.setattr(lens_data_crawl, "run",
                        lambda limit=25: {"attempted": 6, "ok": 0, "stopped_early": "refused"})
    monkeypatch.setattr(lens_data_crawl, "universe", lambda: [])
    monkeypatch.setattr(job, "compute", lambda **kw: {"run_id": 1, "counts": {}})
    lens_runner.start()
    st = lens_runner.wait()
    assert st["phase"] == "done" and "refused" in st["message"]
    assert st["slices"] == lens_runner.MAX_REFUSALS


def test_run_endpoints_need_the_key_to_start_but_not_to_watch(api, monkeypatch):
    import main
    monkeypatch.setattr(main, "ADMIN_KEY", "k")
    calls = []

    class Runner:
        def status(self):
            return {"running": False, "phase": "idle", "computes": 0}

        def start(self, **kw):
            calls.append(kw)
            return {"started": True, "running": True, "phase": "starting", "computes": 0}

        def stop(self):
            return {"running": False, "phase": "idle"}

    monkeypatch.setattr(main, "lens_runner", Runner())
    assert api.get("/api/lenses/run").json()["phase"] == "idle"
    assert api.post("/admin/lenses/run").status_code == 401
    r = api.post("/admin/lenses/run", headers={"X-Admin-Key": "k"})
    assert r.status_code == 200 and r.json()["started"] is True
    assert calls == [{"read_inputs": True, "max_slices": None}]
    assert api.post("/admin/lenses/run/stop", headers={"X-Admin-Key": "k"}).status_code == 200
