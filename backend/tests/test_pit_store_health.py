"""
The point-in-time store's own health.

This exists because the store failed in production with sqlite's famously
unhelpful "unable to open database file", the endpoint answered 503 with that
string, and there was no way to tell from outside whether DATA_DIR was unset,
the directory was missing, or the disk was read-only. Months of evidence were
not being recorded and nothing said so.
"""
import os

import pytest

import pit_store


def test_diagnostics_never_raises_and_names_the_path():
    d = pit_store.diagnostics()
    assert d["active_path"]
    assert "dir_exists" in d and "dir_writable" in d
    assert isinstance(d["persistent"], bool)


def test_a_non_persistent_store_warns_loudly(monkeypatch):
    """
    Without DATA_DIR the store lives next to the code and is wiped on every
    deploy. That must be stated, not inferred — it is the difference between
    a research record and a scratch file.
    """
    monkeypatch.setitem(pit_store._state, "data_dir_from_env", False)
    d = pit_store.diagnostics()
    assert d["persistent"] is False
    assert "lost on the next deploy" in d["warning"]


def test_coverage_reports_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setitem(pit_store._state, "active_path", str(tmp_path / "c.db"))
    if hasattr(pit_store._local, "conn"):
        del pit_store._local.conn
    out = pit_store.coverage_report()
    assert out["ok"] is True
    assert out["snapshot_dates"] == 0
    assert "diagnostics" in out
    if hasattr(pit_store._local, "conn"):
        pit_store._local.conn.close()
        del pit_store._local.conn


def test_an_unopenable_path_falls_back_rather_than_recording_nothing(tmp_path,
                                                                     monkeypatch):
    """
    An ephemeral store that records today is worth more than no store at all —
    provided the fallback is reported, so it cannot quietly become permanent.
    """
    dead = tmp_path / "not-a-dir"
    dead.write_text("this is a file, not a directory")
    monkeypatch.setitem(pit_store._state, "active_path", str(dead / "x.db"))
    monkeypatch.setitem(pit_store._state, "fell_back", False)
    if hasattr(pit_store._local, "conn"):
        del pit_store._local.conn

    pit_store.init_db()
    assert pit_store._state["fell_back"] is True
    assert pit_store._state["last_error"]
    assert pit_store.diagnostics()["persistent"] is False

    if hasattr(pit_store._local, "conn"):
        pit_store._local.conn.close()
        del pit_store._local.conn


def test_the_work_list_only_offers_unlabelled_pairs(tmp_path, monkeypatch):
    monkeypatch.setitem(pit_store._state, "active_path", str(tmp_path / "w.db"))
    if hasattr(pit_store._local, "conn"):
        del pit_store._local.conn
    pit_store.init_db()

    pit_store.snapshot_many({"A": {"composite": 1}, "B": {"composite": 2}},
                            as_of="2026-01-01")
    todo = pit_store.unlabelled(21)
    assert sorted(s for _d, s in todo) == ["A", "B"]

    pit_store.record_forward_return("2026-01-01", "A", 21, 5.0, 1.0)
    todo = pit_store.unlabelled(21)
    assert [s for _d, s in todo] == ["B"]
    # A different horizon is still outstanding for both.
    assert len(pit_store.unlabelled(63)) == 2
    assert pit_store.label_counts() == {21: 1}
    assert "composite" in pit_store.factor_names()

    if hasattr(pit_store._local, "conn"):
        pit_store._local.conn.close()
        del pit_store._local.conn
