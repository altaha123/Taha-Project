"""
The point-in-time store.

Its whole value is that it cannot be rebuilt: a score computed today is not
what the engine believed in March, so a lost database is lost permanently.
That makes where the file lives a correctness question, not a deployment
detail — which is what these tests pin.
"""
import importlib
import os
import sys

import pytest


def _fresh(monkeypatch, tmp_path, data_dir=None, override=None):
    """Re-import pit_store with a chosen environment."""
    monkeypatch.delenv("ALTAHA_PIT_DB", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    if data_dir is not None:
        monkeypatch.setenv("DATA_DIR", str(data_dir))
    if override is not None:
        monkeypatch.setenv("ALTAHA_PIT_DB", str(override))
    sys.modules.pop("pit_store", None)
    return importlib.import_module("pit_store")


def test_the_database_lives_on_the_mounted_disk(monkeypatch, tmp_path):
    """
    Regression. This was a bare relative filename, so on Render the database
    landed next to the code — a directory replaced wholesale on every deploy.
    Every scan wrote snapshots into it and every deploy destroyed them.
    """
    disk = tmp_path / "data"
    disk.mkdir()
    ps = _fresh(monkeypatch, tmp_path, data_dir=disk)
    assert ps.DB_PATH == str(disk / "altaha_pit.db")
    assert os.path.isabs(ps.DB_PATH), "a relative path follows the working directory"


def test_an_explicit_override_still_wins(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.db"
    ps = _fresh(monkeypatch, tmp_path, data_dir=tmp_path, override=target)
    assert ps.DB_PATH == str(target)


def test_without_a_disk_it_falls_back_beside_the_code(monkeypatch, tmp_path):
    ps = _fresh(monkeypatch, tmp_path)
    assert ps.DB_PATH.endswith("altaha_pit.db")
    assert os.path.isabs(ps.DB_PATH)


def test_score_history_aligns_factors_by_date(monkeypatch, tmp_path):
    disk = tmp_path / "d"
    disk.mkdir()
    ps = _fresh(monkeypatch, tmp_path, data_dir=disk)
    ps.init_db()

    ps.snapshot("ACME", {"composite": 74, "technical": 80, "sector": "Energy"},
                as_of="2026-03-02")
    ps.snapshot("ACME", {"composite": 42, "technical": 35, "sector": "Energy"},
                as_of="2026-08-31")

    hist = ps.score_history("ACME")
    rows = hist["rows"]
    assert [r["date"] for r in rows] == ["2026-03-02", "2026-08-31"]
    assert rows[0]["composite"] == 74 and rows[1]["composite"] == 42
    # a text factor rides along with the numbers on the same row
    assert rows[0]["sector"] == "Energy"

    change = ps.score_change("ACME")
    assert change["change"] == -32
    assert change["from"]["date"] == "2026-03-02"
    assert change["to"]["value"] == 42


def test_one_observation_is_not_a_history(monkeypatch, tmp_path):
    disk = tmp_path / "d2"
    disk.mkdir()
    ps = _fresh(monkeypatch, tmp_path, data_dir=disk)
    ps.init_db()
    ps.snapshot("SOLO", {"composite": 60}, as_of="2026-08-31")
    assert ps.score_change("SOLO") is None, \
        "reporting a change from a single reading would be a different claim"


def test_a_snapshot_never_overwrites_what_was_believed_then(monkeypatch, tmp_path):
    """The point of the store: the past is not editable."""
    disk = tmp_path / "d3"
    disk.mkdir()
    ps = _fresh(monkeypatch, tmp_path, data_dir=disk)
    ps.init_db()
    ps.snapshot("HIST", {"composite": 88}, as_of="2026-01-05")
    ps.snapshot("HIST", {"composite": 11}, as_of="2026-01-05")
    assert ps.factor_history("HIST", "composite") == [("2026-01-05", 88)]


def test_unknown_symbol_returns_an_empty_series(monkeypatch, tmp_path):
    disk = tmp_path / "d4"
    disk.mkdir()
    ps = _fresh(monkeypatch, tmp_path, data_dir=disk)
    ps.init_db()
    assert ps.score_history("NOSUCH")["rows"] == []
