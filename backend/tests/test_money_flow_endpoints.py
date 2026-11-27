"""
Money Flow where it meets the rest of the site: its four routes, the line it
adds beside a stock and an idea, and the sector cap it may set.

The claim under test in the second half is a negative one. Money Flow is shown
beside the Altaha Score and the Ideas lists and changes neither: no weight in
ideas.py moved, the cap is the cap it was unless a flag is on, and a list
chosen with Money Flow loaded is the list chosen without it.
"""
import pytest

import ideas
import money_flow as M
import money_flow_config as C
import money_flow_store as store
import moneyflow_fixture as F


@pytest.fixture
def app(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "mf.db"))
    monkeypatch.setitem(M._members, "map", F.members())
    monkeypatch.setitem(M._names, "map", {})
    M._cache.update(at=0.0, payload=None)
    M._cards.update(at=0.0, date=None, cards={})
    assert main.money_flow is M, "main.py did not import money_flow"
    yield main
    M._cache.update(at=0.0, payload=None)
    M._cards.update(at=0.0, date=None, cards={})


@pytest.fixture
def filled(app):
    F.seed(store)
    M.recompute(today=F.TODAY, panel=F.panel())
    return app


def _status(fn, *a, **k):
    from fastapi import HTTPException
    try:
        fn(*a, **k)
    except HTTPException as e:
        return e.status_code
    return 200


# --- routes ------------------------------------------------------------------

def test_the_page_answers_before_any_job_has_run(app):
    out = app.moneyflow_overview()
    assert out["available"] is False and "backfill" in out["message"]
    assert out["coverage"]["fpi_fortnights"]["count"] == 0
    assert app.moneyflow_status()["coverage"]["snapshots"]["count"] == 0


def test_the_page_is_one_payload(filled):
    out = filled.moneyflow_overview()
    assert out["available"] is True
    for key in ("as_of", "market", "fpi", "heatmap", "sectors", "rrg", "weights", "method",
                "mapping", "gaps", "disclaimer", "built_utc"):
        assert key in out, key
    assert [c["short"] for c in out["sectors"]] == ["IT", "FMCG", "Metals"]
    assert len(out["mapping"]) == 24


def test_the_market_pages_card_gets_a_few_figures_not_the_page(app):
    assert app.moneyflow_brief()["available"] is False
    F.seed(store)
    M.recompute(today=F.TODAY, panel=F.panel())
    out = app.moneyflow_brief()
    assert out["available"] and out["inflow_sectors"] == 2 and out["outflow_sectors"] == 1
    assert [t["short"] for t in out["top"]] == ["IT", "FMCG", "Metals"]
    assert out["line"] == "Ranked first on money flow: IT, FMCG, Metals."
    assert out["flipped_to_inflow"] == ["FMCG"]
    assert "heatmap" not in out and "rrg" not in out


def test_a_sector_opens_and_an_unknown_one_is_a_404(filled):
    out = filled.moneyflow_sector("information-technology")
    assert out["sector"] == F.IT and out["stocks"] and len(out["fortnights"]) == 6
    assert _status(filled.moneyflow_sector, "atlantis") == 404
    assert _status(filled.moneyflow_sector, "x" * 81) == 400


def test_the_job_route_names_its_jobs(app, monkeypatch):
    called = []
    monkeypatch.setattr(M, "run_daily", lambda: called.append("daily") or {"ok": True})
    monkeypatch.setattr(M, "run_recompute", lambda: called.append("recompute") or {"ok": True})
    monkeypatch.setattr(M, "run_backfill",
                        lambda months=None, limit=40: called.append(("backfill", months, limit)) or {"ok": True})
    assert app.admin_moneyflow_run(job="daily", x_admin_key=None) == {"ok": True}
    app.admin_moneyflow_run(job="recompute", x_admin_key=None)
    app.admin_moneyflow_run(job="backfill", limit=5000, months=12, x_admin_key=None)
    assert called == ["daily", "recompute", ("backfill", 12, 200)]
    assert _status(app.admin_moneyflow_run, job="format-disk", x_admin_key=None) == 400


def test_a_job_that_raises_is_a_503_with_the_reason(app, monkeypatch):
    def boom():
        raise RuntimeError("disk is full")
    monkeypatch.setattr(M, "run_daily", boom)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        app.admin_moneyflow_run(job="daily", x_admin_key=None)
    assert e.value.status_code == 503 and "disk is full" in e.value.detail


# --- beside a stock ----------------------------------------------------------

def test_the_stock_page_gets_its_sectors_tailwind(filled):
    t = filled._sector_tailwind("IT1")
    assert t["sector"] == F.IT and t["rank"] == 1 and t["tier"] == "top"
    assert filled._sector_tailwind("NOTLISTED") is None


def test_a_broken_money_flow_costs_the_stock_page_nothing(app, monkeypatch):
    def boom(_sym):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(M, "tailwind", boom)
    assert app._sector_tailwind("IT1") is None
    assert ideas.sector_tailwind("IT1") is None
    assert ideas.sector_cap_for("IT1", 4) == 4


# --- the Ideas lists ---------------------------------------------------------

def _rows(n=6):
    """Six IT names ranked 1..6 on the long-term list, then one metal."""
    out = []
    for i in range(1, n + 1):
        out.append({"symbol": "IT%d" % i, "name": "IT %d" % i, "sector": "Technology",
                    "leader": {"lists": {"long": {"rank": i, "score": 90 - i}}, "universe": 600}})
    out.append({"symbol": "MT1", "name": "MT 1", "sector": "Basic Materials",
                "leader": {"lists": {"long": {"rank": 9, "score": 60}}, "universe": 600}})
    return out


def _chosen(monkeypatch):
    monkeypatch.setattr(ideas, "_filing_for", lambda *a, **k: None)
    picked = ideas._choose_picks(_rows(), "long", 15, 72)
    return [t[0]["symbol"] for t in picked[0]], picked[2]


def test_no_weight_in_ideas_changed():
    """The numbers this change promised not to touch, typed out."""
    assert ideas.HORIZONS["short"]["weights"] == {
        "fit": 32, "composite": 10, "sector": 14, "regime": 12, "catalyst": 17,
        "liquidity": 8, "record": 7}
    assert ideas.HORIZONS["medium"]["weights"] == {
        "fit": 30, "composite": 18, "sector": 16, "regime": 4, "catalyst": 12,
        "liquidity": 8, "record": 12}
    assert ideas.SECTOR_QUALITY["short"] == {"Leading": 1.0, "Weakening": 0.55,
                                             "Improving": 0.68, "Lagging": 0.25}
    assert (ideas.PICK_SECTOR_CAP, ideas.SECTOR_CAP) == (4, 3)


def test_with_the_flag_off_a_list_is_what_it_was(filled, monkeypatch):
    assert C.CAPS_ON is False
    with_mf = _chosen(monkeypatch)
    monkeypatch.setattr(ideas, "money_flow", None)
    without = _chosen(monkeypatch)
    assert with_mf == without == (["IT1", "IT2", "IT3", "IT4", "MT1"], 2)
    assert ideas.money_flow_caps() == {"on": False}


def test_with_the_flag_on_a_leading_sector_gives_five_and_a_lagging_one_two(filled, monkeypatch):
    monkeypatch.setattr(C, "CAPS_ON", True)
    symbols, capped = _chosen(monkeypatch)
    assert symbols == ["IT1", "IT2", "IT3", "IT4", "IT5", "MT1"] and capped == 1
    note = ideas.money_flow_caps()
    assert note["on"] is True and (note["top"], note["bottom"]) == (5, 2)
    assert ideas.sector_cap_for("MT1", 4) == 2 and ideas.sector_cap_for("FM1", 4) == 4


def test_the_money_flow_pick_list_is_never_capped_by_it(filled, monkeypatch):
    """That list is four stocks from each of four sectors by construction."""
    monkeypatch.setattr(C, "CAPS_ON", True)
    monkeypatch.setattr(ideas, "_filing_for", lambda *a, **k: None)
    rows = [dict(r, leader={"lists": {"flow": r["leader"]["lists"]["long"]}, "universe": 600})
            for r in _rows()]
    picked = ideas._choose_picks(rows, "flow", 15, 72)
    assert len(picked[0]) == 7 and picked[2] == 0
