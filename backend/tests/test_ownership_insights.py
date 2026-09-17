"""Guard the misleading ownership stories: missing ≠ zero/new/exit, same quarter only."""
from types import SimpleNamespace
import pytest
import ownership_insights as oi


def holder(name, pct, promoter=False, kind="Mutual fund"):
    return {"name": name, "pct": pct, "promoter": promoter, "kind": kind}


def filing(period, names):
    return {"period": period, "source": "https://nsearchives.nseindia.com/" + period, "names": names}


def test_history_preserves_missing_disclosure_and_zero():
    a = filing("2025-12-31", [holder("Fund A", 2)])
    b = filing("2026-03-31", [holder("Fund B", 0)])
    c = filing("2026-06-30", [holder("Fund A", 3), holder("Fund B", 1)])
    out = oi.named_insights(c, [c, b, a], b)
    fund = out["public"][0]
    assert fund["new_in_table"] is True
    assert fund["change_qoq"] is None
    assert fund["first_seen"] == "2025-12-31"
    assert [p["pct"] for p in fund["history"]] == [2, None, 3]
    assert out["public"][1]["previous_pct"] == 0
    assert out["public"][1]["change_qoq"] == 1


def test_first_filing_does_not_claim_new_investor():
    a = filing("2026-06-30", [holder("Fund A", 2)])
    out = oi.named_insights(a, [a], None)["public"][0]
    assert not out["new_in_table"]
    assert out["status"] == "comparison_unavailable"


def test_interim_does_not_claim_quarter_change_or_new_holder():
    a = filing("2026-03-31", [holder("Fund A", 2)])
    b = filing("2026-06-30", [holder("Fund A", 3)])
    interim = filing("2026-07-15", [holder("Fund B", 2)])
    out = oi.named_insights(interim, [b, a], a)
    assert out["public"][0]["change_qoq"] is None
    assert not out["public"][0]["new_in_table"]
    assert not out["no_longer_disclosed"]


def test_missing_name_is_not_a_zero_or_a_complete_exit():
    a = filing("2026-03-31", [holder("Fund A", 2)])
    b = filing("2026-06-30", [])
    row = oi.named_insights(b, [b, a], a)["no_longer_disclosed"][0]
    assert row["pct"] is None and row["change_qoq"] is None
    assert row["previous_pct"] == 2
    assert row["status"] == "no_longer_disclosed"


def test_name_matching_is_conservative_and_group_sensitive():
    a = filing("2026-03-31", [holder("  FUND   A", 2), holder("Fund A Growth", 5)])
    b = filing("2026-06-30", [holder("Fund A", 3), holder("Fund A Growth", 4, True)])
    out = oi.named_insights(b, [b, a], a)
    assert out["public"][0]["change_qoq"] == 1
    assert out["promoters"][0]["change_qoq"] is None
    assert out["promoters"][0]["institutional"] is False


def test_peers_never_fall_back_to_unrelated_sectors():
    rows = [{"symbol":"ABC", "sector":"Energy"}, {"symbol":"DEF", "sector":"Energy"}, {"symbol":"XYZ", "sector":"Banks"}]
    assert oi.peer_candidates("ABC.NS", rows, {})["candidates"] == ["DEF"]
    assert oi.peer_candidates("MISSING", rows, {})["candidates"] == []
    assert oi.peer_candidates("ABC", [], {"ABC":"Energy", "DEF":"Energy"})["classification_source"] == "bundled sector map"


def reader_fixture():
    rows = [{"period":p,"filed":p,"revised":False,"xbrl":p} for p in ["2026-06-30","2026-05-31","2026-03-31"]]
    calls=[]
    def read(url, **kwargs):
        calls.append(url)
        return {"period":url, "source":"https://nsearchives.nseindia.com/"+url,
                "categories":{"fii":{"pct":10}, "dii":{"pct":20 if url=="2026-06-30" else 18,"derived":True}}}
    return SimpleNamespace(index=lambda s:rows, filing=read, is_quarter_end=lambda p:p.endswith(("03-31","06-30","09-30","12-31"))), calls


def test_comparison_uses_exact_quarter_and_skips_interim():
    reader,calls=reader_fixture()
    out=oi.comparison_at("ABC","2026-06-30",reader)
    assert calls==["2026-06-30","2026-03-31"]
    assert out["metrics"]["institutions"]=={"pct":30,"change_qoq":2,"derived":True}
    assert out["metrics"]["promoter"]["pct"] is None
    assert out["pledge_pct"] is None


def test_wrong_quarter_is_unavailable_not_latest():
    reader,calls=reader_fixture()
    out=oi.comparison_at("ABC","2025-12-31",reader)
    assert not out["available"]
    assert not calls
    with pytest.raises(ValueError):
        oi.comparison_at("ABC","2026-05-31",reader)
