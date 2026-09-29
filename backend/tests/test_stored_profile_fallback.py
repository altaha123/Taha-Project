"""
A refused Yahoo `info` read must not cost a company its identity.

When the live read failed, the scan banked the company with no sector, no
industry and its ticker for a name, and the Universe Scan printed "Sector
unavailable" on the row. The stored Yahoo profile carries the same fields in
the same taxonomy, so it fills what the live read left empty — and never
overrides what the live read did return.
"""
import sys

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    sys.modules.pop("fundamentals_store", None)
    import fundamentals_store
    fundamentals_store.record_yf_profile("MACPOWER", {
        "longName": "Macpower CNC Machines Limited", "sector": "Industrials",
        "industry": "Specialty Industrial Machinery", "sharesOutstanding": 10_000_000,
        "currentPrice": 900.0, "marketCap": 9_000_000_000, "currency": "INR"})
    yield fundamentals_store
    sys.modules.pop("fundamentals_store", None)


def test_an_empty_live_read_is_filled_from_the_stored_profile(store):
    from data_source import with_stored_profile
    out = with_stored_profile("MACPOWER.NS", {}, price=1000.0)
    assert out["sector"] == "Industrials"
    assert out["industry"] == "Specialty Industrial Machinery"
    assert out["longName"] == "Macpower CNC Machines Limited"
    # Today's price times the stored share count, not the stored market cap.
    assert out["marketCap"] == pytest.approx(10_000_000 * 1000.0)
    assert out["profile_source"] == "stored Yahoo profile"


def test_a_live_value_is_never_overridden(store):
    from data_source import with_stored_profile
    live = {"sector": "Technology", "industry": "Software", "longName": "Live Name", "marketCap": 5.0}
    assert with_stored_profile("MACPOWER.NS", live, price=1000.0) == live


def test_only_missing_fields_are_filled(store):
    from data_source import with_stored_profile
    out = with_stored_profile("MACPOWER", {"sector": "Live Sector"})
    assert out["sector"] == "Live Sector"
    assert out["industry"] == "Specialty Industrial Machinery"
    assert out["marketCap"] == 9_000_000_000, "no price given: the stored market cap"


def test_unknown_company_and_foreign_listing_are_left_alone(store):
    from data_source import with_stored_profile
    assert with_stored_profile("NOSUCH.NS", {}) == {}
    assert with_stored_profile("AAPL.US", {}) == {}
    assert with_stored_profile("^NSEI", {}) == {}


def test_the_scan_preview_never_prints_a_fault_for_a_missing_sector():
    from scan_preview import preview_row
    row = preview_row({"symbol": "X", "name": "X", "composite": 50.0, "fundamental": 60})
    assert row["sector"] == ""
    assert preview_row({"symbol": "Y", "sector": "Energy"})["sector"] == "Energy"
