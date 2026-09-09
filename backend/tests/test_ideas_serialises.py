"""
/ideas must return something FastAPI can actually serialise.

This is the bug that broke the Ideas tab, and it is worth stating exactly
because three plausible wrong theories came before it: the instance was not
out of memory, the endpoint was not slow, and the engine was not asleep. A
single numpy scalar somewhere in the response — one sector figure, one
corroboration count — made jsonable_encoder raise, and the request 500'd.

Two properties made it hard to see:

  1. The failure happens in serialize_response, AFTER the route function has
     returned. No try/except inside the route can catch it. The endpoint
     succeeds and the response still 500s.

  2. That 500 reaches the browser without CORS headers, so the page reports
     an unreachable engine (see test_ideas_never_500.py).

main.py has had to_native() the whole time and twenty endpoints use it —
/market among them, which is why the ticker strip on the same page kept
updating while the ideas beneath it returned nothing. /ideas simply never
called it.
"""
import numpy as np
import pytest

from fastapi.encoders import jsonable_encoder


@pytest.fixture
def with_payload():
    import main
    before = main._state["payload"]
    main._state["payload"] = {"scanned_at": "31 Aug 2026, 04:31", "rankings": []}
    yield main
    main._state["payload"] = before


def test_numpy_in_the_response_still_serialises(with_payload, monkeypatch):
    """The shape from the traceback: response -> list -> dict -> dict -> np.int64."""
    main = with_payload

    monkeypatch.setattr(main.ideas_engine, "select", lambda *a, **k: {
        "available": True,
        "rows": [{"symbol": "RELIANCE",
                  "sector_outlook": {"rel_3m": np.float64(4.2),
                                     "outlets": np.int64(3)},
                  "evidence": [{"points": np.float32(7.5), "of": np.int32(20)}]}],
        "count": np.int64(1),
        "considered": np.int64(60),
    })
    out = main.ideas(horizon="short", limit=15)
    jsonable_encoder(out)          # this is what raised in production

    row = out["rows"][0]
    assert row["sector_outlook"]["outlets"] == 3
    assert isinstance(row["sector_outlook"]["outlets"], int)
    assert isinstance(row["evidence"][0]["points"], float)
    assert isinstance(out["count"], int)


def test_the_no_scan_answer_serialises(monkeypatch):
    import main

    before = main._state["payload"]
    main._state["payload"] = None
    monkeypatch.setattr(main, "_safe_context",
                        lambda h: {"regime": {"pct_vs_50dma": np.float64(-1.4)}})
    try:
        jsonable_encoder(main.ideas(horizon="short"))
    finally:
        main._state["payload"] = before


def test_the_error_answer_serialises(with_payload, monkeypatch):
    """Even the failure path carries market context, and that touches pandas."""
    main = with_payload

    def explode(*a, **k):
        raise KeyError("setup_fit")

    monkeypatch.setattr(main.ideas_engine, "select", explode)
    monkeypatch.setattr(main, "_safe_context",
                        lambda h: {"leaders": [{"rel": np.float64(2.0)}]})
    jsonable_encoder(main.ideas(horizon="short"))


def test_ideas_context_serialises(monkeypatch):
    import main

    monkeypatch.setattr(main, "_safe_context",
                        lambda h: {"leaders": [{"n": np.int64(4)}], "measured": np.int64(11)})
    out = main.ideas_context(horizon="short")
    jsonable_encoder(out)
    assert isinstance(out["measured"], int)


# --- to_native itself ------------------------------------------------------

def test_to_native_handles_the_numpy_scalar_that_broke_it():
    import main

    assert main.to_native(np.int64(7)) == 7
    assert isinstance(main.to_native(np.int64(7)), int)


def test_to_native_handles_sets_which_are_not_json_at_all():
    import main

    assert sorted(main.to_native({"a", "b"})) == ["a", "b"]


def test_to_native_handles_numpy_strings_and_arrays():
    """Neither satisfies the numeric branches, and both fail to encode."""
    import main

    assert main.to_native(np.str_("MOMENTUM")) == "MOMENTUM"
    assert main.to_native(np.array([1, 2, 3])) == [1, 2, 3]


def test_to_native_still_nulls_nan_and_infinity():
    """JSON has no NaN. This behaviour predates the fix and must survive it."""
    import main

    assert main.to_native(float("nan")) is None
    assert main.to_native(np.float64("inf")) is None
    assert main.to_native(np.float64(2.5)) == 2.5
