"""
The delivery cache builds itself.

The bug these cover: the cache was filled only by an admin-only POST that
nothing ever called, so the Special tab read "not ready" on a fresh disk
forever — and when the exchange archive answered a request with 403, the day
was recorded as a holiday and never asked for again.
"""
import datetime as dt
import os
import time
import types

import pandas as pd
import pytest

import special


HEADER = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, "
          "LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, "
          "TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER")


def _csv(day):
    """A bhavcopy big enough to clear the module's 5 KB floor."""
    rows = [HEADER]
    for i in range(400):
        rows.append(f"SYM{i:03d}, EQ, {day:%d-%b-%Y}, 100, 100, 105, 95, 102, "
                    f"102, 101, 5000000, 5050, 900, 3000000, 61.5")
    return "\n".join(rows) + "\n"


class _Reply:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text
        self.content = text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Archive:
    """The exchange, scripted: refusals, holidays and good days."""

    def __init__(self, refuse=(), holiday=()):
        self.refuse = set(refuse)
        self.holiday = set(holiday)
        self.asked = []
        self.headers = {}

    def get(self, url, timeout=None):
        tag = url.rsplit("_", 1)[-1].split(".")[0]
        day = dt.datetime.strptime(tag, "%d%m%Y").date()
        self.asked.append(day)
        if day in self.refuse:
            self.refuse.discard(day)          # refuses once, then relents
            return _Reply(403, "Access Denied")
        if day in self.holiday:
            return _Reply(404, "not found")
        return _Reply(200, _csv(day))

    def update(self, *a, **k):
        pass


@pytest.fixture
def cache(monkeypatch, tmp_path):
    """Point the module at an empty directory and give it back afterwards."""
    monkeypatch.setattr(special, "CACHE", str(tmp_path / "panels.pkl"))
    monkeypatch.setattr(special, "BLANKS", str(tmp_path / "blanks.json"))
    monkeypatch.setattr(special, "_state",
                        {"panel": None, "built_at": None, "days": 0, "error": None})
    monkeypatch.setattr(special, "MIN_TURNOVER_CR", 0.0)
    yield tmp_path


def _install(monkeypatch, archive):
    """Serve the scripted archive, and take the politeness pauses out.

    The clock is swapped inside the module rather than on the time module
    itself, so the test's own waiting still works.
    """
    monkeypatch.setattr(special, "_session", lambda: archive)
    monkeypatch.setattr(special, "time",
                        types.SimpleNamespace(sleep=lambda *_a: None,
                                              time=time.time))


def test_missing_skips_weekends_and_known_holidays(cache):
    blanks = {(dt.date.today() - dt.timedelta(days=6)).isoformat()}
    days = special._missing(None, 10, blanks)
    assert days == sorted(days)
    assert all(d.weekday() < 5 for d in days)
    assert all(d.isoformat() not in blanks for d in days)


def test_refresh_stores_what_it_fetched(cache, monkeypatch):
    _install(monkeypatch, _Archive())
    out = special.refresh(days_back=6)
    assert out["fetched"] >= 1
    assert out["remaining"] == 0
    assert os.path.exists(special.CACHE)
    assert special.status()["cached_sessions"] == out["fetched"]


def test_a_refused_day_is_retried_not_written_off(cache, monkeypatch):
    """A 403 is the archive being busy, not a market holiday."""
    wanted = special._missing(None, 6, set())
    refused = wanted[0]
    arch = _Archive(refuse=[refused])
    _install(monkeypatch, arch)

    first = special.refresh(days_back=6)
    assert first["blocked"] == 1
    assert first["remaining"] == 1
    assert refused not in set(pd.Index(special._load_cache()["close"].index).date)
    assert refused.isoformat() not in special._load_blanks()

    second = special.refresh(days_back=6)
    assert second["remaining"] == 0
    assert refused in set(pd.Index(special._load_cache()["close"].index).date)


def test_a_settled_holiday_is_remembered(cache, monkeypatch):
    """A day with no file is recorded once, so later passes stop asking."""
    wanted = special._missing(None, 20, set())
    holiday = wanted[0]                       # oldest, so well past settling
    arch = _Archive(holiday=[holiday])
    _install(monkeypatch, arch)

    special.refresh(days_back=20)
    assert holiday.isoformat() in special._load_blanks()

    arch.asked.clear()
    special.refresh(days_back=20)
    assert holiday not in arch.asked


def test_builder_fills_the_cache_without_an_admin_call(cache, monkeypatch):
    """The whole point: nobody has to POST anything for a book to exist."""
    _install(monkeypatch, _Archive())
    monkeypatch.setattr(special, "BUILD_CHUNK", 2)
    special._build.update({"running": False, "last_start": 0.0})

    special.ensure_building(days_back=12)
    for _ in range(200):
        if not special._build["running"]:
            break
        time.sleep(0.05)
    assert not special._build["running"]
    assert special._build["error"] is None
    assert special._build["remaining"] == 0
    assert special.status()["cached_sessions"] >= 5


def test_not_ready_reports_progress_rather_than_a_dead_end(cache, monkeypatch):
    _install(monkeypatch, _Archive())
    monkeypatch.setattr(special, "ensure_building", lambda *a, **k: None)
    out = special.rank_universe()
    assert out["available"] is False
    assert out["building"] is True
    assert out["needed"] == special.MIN_SESSIONS
    assert out["sessions"] == 0
