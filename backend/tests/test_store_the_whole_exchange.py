"""
The store keeps every EQ symbol; the book still only ranks the liquid ones.

The prune this replaces was written against the v2 long-format cache, where
it genuinely mattered. Against wide float32 panels it was discarding about
1,845 of 2,665 companies — every small and mid cap on the exchange — to save
around 11 MB on a 512 MB instance. Those are the names somebody opens a
screener to look up.

The risk in widening it is not memory, it is the BOOK. `_components` takes
the cross-sectional MEDIAN return of the panel as its market proxy for the
residual-momentum regression, so putting 1,845 illiquid stocks into the file
would move that median and quietly re-score every name in the book. These
tests exist to prove that did not happen.
"""
import numpy as np
import pandas as pd
import pytest

import special


DAYS = pd.bdate_range(end="2026-09-18", periods=300)
# The book refuses to rank a cross-section of fewer than twenty names, and it
# only considers stocks trading above their own 200-day average, so the liquid
# side has to be a real cohort with a real uptrend rather than a token pair.
LIQUID = [f"BIG{i:02d}" for i in range(40)]
THIN = [f"TINY{i:02d}" for i in range(30)]


def _panel(symbols, turnover_cr, seed, drift=0.0009):
    """A panel with a gentle uptrend, at a turnover either side of the floor."""
    rng = np.random.default_rng(seed)
    n = len(DAYS)
    steps = rng.normal(drift, 0.011, (n, len(symbols)))
    close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    frame = lambda arr: pd.DataFrame(arr, index=DAYS, columns=symbols).astype("float32")
    qty = (turnover_cr * 1e7) / close
    return {
        "deliv": frame(rng.uniform(34, 66, (n, len(symbols)))),
        "qty": frame(qty * rng.uniform(.95, 1.05, (n, len(symbols)))),
        "vwap": frame(close),
        "close": frame(close),
        "high": frame(close * 1.02),
        "low": frame(close * 0.98),
    }


def _widen(a, b):
    """Two panels side by side, as the store now holds them."""
    return {k: pd.concat([a[k], b[k]], axis=1) for k in special.PANEL_FIELDS}


@pytest.fixture
def wide():
    liquid = _panel(LIQUID, turnover_cr=90, seed=3)
    # Far below the floor, and drifting the other way, so that if these ever
    # reached the market-proxy median the book's scores would visibly move.
    thin = _panel(THIN, turnover_cr=2, seed=4, drift=-0.0012)
    return _widen(liquid, thin), liquid


def test_the_book_draws_only_from_the_liquid_names(wide, monkeypatch):
    P, _ = wide
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    assert sorted(special._rank_cols(P)) == sorted(LIQUID)


def test_fund_units_are_stored_but_never_ranked():
    # A fund unit is structurally calm and almost fully delivered, so it wins
    # signals it has no business winning. It stays OUT of the book — but a
    # reader who searches it should still get its delivery record.
    P = _panel(LIQUID + ["NIFTYBEES"], turnover_cr=90, seed=5)
    assert "NIFTYBEES" in P["deliv"].columns
    assert "NIFTYBEES" not in special._rank_cols(P)


def test_widening_the_store_does_not_move_the_book(wide, monkeypatch):
    """The one that matters. Same liquid names, same scores, whether or not
    1,845 illiquid companies are sitting in the file beside them."""
    P, liquid_only = wide

    monkeypatch.setattr(special, "_load_cache", lambda: liquid_only)
    before = special.rank_universe(limit=20)
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    after = special.rank_universe(limit=20)

    assert before.get("available") is True, before.get("message")
    assert after.get("available") is True, after.get("message")

    # The size of the cross-section the book was chosen from must not move:
    # 1,845 illiquid companies entering the file must not enter the ranking.
    assert after["universe_ranked"] == before["universe_ranked"]

    # Same names, same order.
    assert [r["symbol"] for r in after["book"]] == [r["symbol"] for r in before["book"]]

    # And the same numbers, to floating-point equality. This is the assertion
    # that catches a moved market proxy: the residual-momentum regression uses
    # the cross-sectional median return, so a wider panel would shift every
    # score by a little without changing any name.
    for a, b in zip(after["book"], before["book"]):
        assert set(a) == set(b)
        for key, value in b.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                assert a[key] == value, key
            else:
                assert a[key] == pytest.approx(value, rel=1e-9, abs=1e-9), key

    # The published diagnostics too — they are computed off the same frame.
    assert after["measured"] == before["measured"]


def test_a_thin_company_now_has_a_delivery_record(wide, monkeypatch):
    # The whole point. Before this change TINY00 was not in the file at all.
    P, _ = wide
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    out = special.daily_delivery("TINY00", days=20)

    assert out["available"] is True
    assert len(out["rows"]) == 20
    assert out["summary"]["avg_20"] is not None
    assert all(r["deliv_pct"] is not None for r in out["rows"])


def test_days_held_from_before_the_widening_are_asked_for_again(wide):
    """The migration. Old sessions are on file for the liquid names only, so
    they are handed back to the builder as missing and replaced on merge —
    measured per date, so an interrupted backfill resumes."""
    P, _ = wide
    # Make the oldest ten sessions look like they were fetched under the prune.
    thin_dates = P["deliv"].index[:10]
    P["deliv"].loc[thin_dates, THIN] = np.nan

    flagged = special._thin_days(P)
    assert flagged == {d.date() for d in thin_dates}

    missing = special._missing(P, days_back=500, blanks=set())
    assert set(flagged).issubset(set(missing)), "thin days must be refetched"
    # Days that already carry the whole exchange are not fetched again.
    full = {d.date() for d in P["deliv"].index[10:]}
    assert not (full & set(missing))


def test_a_store_that_is_already_complete_asks_for_nothing_back(wide):
    P, _ = wide
    assert special._thin_days(P) == set()


def test_status_separates_what_is_held_from_what_is_rankable(wide, monkeypatch):
    P, _ = wide
    monkeypatch.setattr(special, "_load_cache", lambda: P)
    st = special.status()
    assert st["symbols"] == len(LIQUID) + len(THIN)
    assert st["rankable"] == len(LIQUID)
    assert st["backfilling"] == 0
