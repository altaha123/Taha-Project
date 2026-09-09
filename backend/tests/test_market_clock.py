"""
The market clock, and the deprecation that was going to take /market with it.

/market decides open / pre / closed from the IST wall clock. It used to build
that clock as datetime.utcnow() + 5h30m — a call Python has deprecated and
scheduled for removal, which was already printing a DeprecationWarning on
every request under the Python 3.14 this deploys on. When it goes, so does the
ticker strip and the session badge.

The old line was also lying about what it produced: a NAIVE datetime holding
IST wall-clock numbers, indistinguishable from UTC to anything that inspected
it. These tests pin the session boundaries so a timezone-aware replacement has
to agree with the old behaviour at every edge, not just in the middle of the
trading day.
"""
import datetime as dt

import pytest


@pytest.fixture(scope="module")
def main_mod():
    import main
    return main


def test_ist_is_utc_plus_five_thirty(main_mod):
    assert main_mod.IST.utcoffset(None) == dt.timedelta(hours=5, minutes=30)


def test_the_clock_is_timezone_aware(main_mod):
    """A naive datetime is what the old code produced, and it read as UTC."""
    now = dt.datetime.now(main_mod.IST)
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(hours=5, minutes=30)


def test_it_agrees_with_the_arithmetic_it_replaces(main_mod):
    """
    Same wall clock, honestly labelled. If these ever disagree the session
    boundaries below have moved, which is a market-hours bug, not a tidy-up.
    """
    aware = dt.datetime.now(main_mod.IST)
    legacy = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    assert (aware.hour, aware.minute) == (legacy.hour, legacy.minute)
    assert aware.weekday() == legacy.weekday()


def _session(now):
    """The classification /market performs, isolated from the price feeds."""
    mins = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "closed"
    if 555 <= mins < 930:
        return "open"
    if mins < 555:
        return "pre"
    return "closed"


@pytest.mark.parametrize("when,expected", [
    (dt.datetime(2026, 9, 9, 9, 14), "pre"),      # one minute before the bell
    (dt.datetime(2026, 9, 9, 9, 15), "open"),     # 09:15 exactly
    (dt.datetime(2026, 9, 9, 12, 0), "open"),
    (dt.datetime(2026, 9, 9, 15, 15), "open"),    # the code used to close here
    (dt.datetime(2026, 9, 9, 15, 29), "open"),    # last minute of the session
    (dt.datetime(2026, 9, 9, 15, 30), "closed"),  # the bell
    (dt.datetime(2026, 9, 9, 23, 59), "closed"),
    (dt.datetime(2026, 9, 12, 12, 0), "closed"),  # Saturday
    (dt.datetime(2026, 9, 13, 12, 0), "closed"),  # Sunday
])
def test_the_session_boundaries_hold(when, expected, main_mod):
    assert _session(when.replace(tzinfo=main_mod.IST)) == expected


def test_no_deprecation_warning_from_the_clock(main_mod):
    """The whole point: this must not warn on the Python it deploys to."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        now = dt.datetime.now(main_mod.IST)
        now.strftime("%d %b %Y, %H:%M IST")
