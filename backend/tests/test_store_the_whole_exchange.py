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


@pytest.fixture(autouse=True)
def no_background_builder(monkeypatch):
    """rank_universe and daily_delivery ask the builder to run on every call
    now, which is the point of that change — but in a test it spawns a thread
    that writes the shared cache and leaves a panel behind in module state for
    whatever runs next. It surfaced as an unrelated cache test counting 302
    sessions where it had fetched three. Same rule the conftest applies to the
    network: nothing reaches out unless the test asked it to."""
    calls = []
    monkeypatch.setattr(special, "ensure_building", lambda *a, **k: calls.append(True))
    return calls



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
    # Stamped, because these stand for a store written by the current builder.
    return {
        "schema": special.WIDE_SCHEMA,
        "deliv": frame(rng.uniform(34, 66, (n, len(symbols)))),
        "qty": frame(qty * rng.uniform(.95, 1.05, (n, len(symbols)))),
        "vwap": frame(close),
        "close": frame(close),
        "high": frame(close * 1.02),
        "low": frame(close * 0.98),
    }


def _widen(a, b):
    """Two panels side by side, as the store now holds them."""
    out = {k: pd.concat([a[k], b[k]], axis=1) for k in special.PANEL_FIELDS}
    out["schema"] = special.WIDE_SCHEMA
    return out


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


def test_a_store_written_before_the_widening_is_refetched_whole(wide):
    """A pruned store carries no schema marker, so every day it holds is
    thin — which is the case that matters, because on the live instance every
    one of its 297 sessions was written by the pruning builder and they were
    all equally narrow. Anything that compares days against each OTHER finds
    nothing there and reports a backfill of zero for ever."""
    P, _ = wide
    P.pop("schema")

    flagged = special._thin_days(P)
    assert flagged == {d.date() for d in P["deliv"].index}

    missing = special._missing(P, days_back=500, blanks=set())
    inside = {d for d in flagged if d in set(missing)}
    assert inside, "a store written before the widening must be refetched"


def test_a_partly_widened_store_refetches_only_what_is_still_narrow(wide):
    """Once any day has been rewritten the marker is set, and the relative
    test carries the rest: a pruned day sits well under half the coverage of
    a whole one. This is what stops the backfill when it is done."""
    P, _ = wide
    thin_dates = P["deliv"].index[:10]
    P["deliv"].loc[thin_dates, THIN] = np.nan

    flagged = special._thin_days(P)
    assert flagged == {d.date() for d in thin_dates}

    missing = set(special._missing(P, days_back=500, blanks=set()))
    assert flagged & missing, "still-narrow days must be refetched"
    # Days that already carry the whole exchange are not fetched again.
    assert not ({d.date() for d in P["deliv"].index[10:]} & missing)


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


def test_a_healthy_store_still_asks_the_builder_to_run(wide, monkeypatch,
                                                       no_background_builder):
    """The bug that kept the live store eighteen days stale.

    ensure_building used to be called only from inside the "cache is missing
    or too short" branches of these two functions. Nothing calls
    /special/refresh on a schedule either, so the moment the store passed
    MIN_SESSIONS nothing ever asked it to fetch another session again. It sat
    frozen and looked entirely healthy doing it: a stale book renders exactly
    like a current one, and `ready: true` was true.

    So the assertion is not about a short store. It is that a DEEP, current,
    complete one still asks — ensure_building is rate-limited and has its own
    memory ceiling, so being asked costs a comparison, and not being asked
    costs every session after the one that crossed the threshold.
    """
    P, _ = wide
    monkeypatch.setattr(special, "_load_cache", lambda: P)

    assert special.rank_universe(limit=20)["available"] is True
    assert no_background_builder, "a deep store must still ask the builder to run"

    no_background_builder.clear()
    assert special.daily_delivery("TINY00", days=20)["available"] is True
    assert no_background_builder, "a delivery lookup must ask the builder to run"
