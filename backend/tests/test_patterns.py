"""
Pattern detection, against charts built to contain a known shape.

The two properties that matter are opposite in sign: the detector must FIND
the textbook shape, and it must NOT invent one in noise. A detector that
always finds something has stopped detecting, so the random-walk case is as
load-bearing as the seven positive ones.
"""
import numpy as np
import pytest

from conftest import ohlcv, ramp, arc

import patterns


def _seeded(fn):
    """Same noise for every fixture, so a pass or a fail is reproducible."""
    rng = np.random.default_rng(7)
    closes = fn()
    n = len(closes)
    jitter = 1 + rng.normal(0, 0.004, n)
    return ohlcv(np.asarray(closes) * jitter,
                 volume=rng.integers(800_000, 1_200_000, n).astype(float))


def cup_and_handle():
    return ramp(80, 100, 60) + arc(100, 74, 70) + ramp(100, 92, 12) + ramp(92, 96, 4)

def double_bottom():
    return (ramp(120, 100, 40) + ramp(100, 78, 25) + ramp(78, 96, 20) +
            ramp(96, 79, 20) + ramp(79, 93, 18) + ramp(93, 95, 6))

def head_and_shoulders():
    return (ramp(70, 100, 40) + ramp(100, 88, 12) + ramp(88, 118, 16) +
            ramp(118, 87, 16) + ramp(87, 101, 14) + ramp(101, 90, 12) + ramp(90, 88, 5))

def inverse_head_and_shoulders():
    return (ramp(130, 100, 40) + ramp(100, 84, 12) + ramp(84, 96, 14) +
            ramp(96, 70, 16) + ramp(70, 97, 16) + ramp(97, 85, 12) + ramp(85, 95, 8))

def ascending_triangle():
    out, lo = ramp(60, 100, 55), 84
    for _ in range(4):
        out += ramp(100, lo, 9) + ramp(lo, 100, 9)
        lo += 3.4
    return out

def bull_flag():
    return ramp(55, 70, 70) + ramp(70, 104, 12) + ramp(104, 97, 10) + ramp(97, 99, 3)

def rectangle():
    out = ramp(60, 100, 50)
    for _ in range(4):
        out += ramp(100, 84, 9) + ramp(84, 100, 9)
    return out


SHAPES = [
    ("Cup and handle", cup_and_handle),
    ("Double bottom", double_bottom),
    ("Head and shoulders", head_and_shoulders),
    ("Inverse head and shoulders", inverse_head_and_shoulders),
    ("Ascending triangle", ascending_triangle),
    ("Bull flag", bull_flag),
    ("Rectangle range", rectangle),
]


@pytest.mark.parametrize("name,builder", SHAPES, ids=[s[0] for s in SHAPES])
def test_finds_the_shape(name, builder):
    out = patterns.analyse(_seeded(builder), with_base_rates=False)
    assert out["available"], out.get("message")
    assert name in [p["name"] for p in out["patterns"]]


def test_no_pattern_in_a_random_walk():
    rng = np.random.default_rng(7)
    walk = 100 + np.cumsum(rng.normal(0, 0.8, 200))
    out = patterns.analyse(ohlcv(walk), with_base_rates=False)
    assert out["patterns"] == [], [p["name"] for p in out["patterns"]]


def test_every_pattern_carries_its_levels_and_audit():
    out = patterns.analyse(_seeded(cup_and_handle), with_base_rates=False)
    p = next(x for x in out["patterns"] if x["name"] == "Cup and handle")
    assert p["trigger"] and p["invalidation"] and p["target"]
    assert p["status"] in ("forming", "confirmed", "failed")
    assert p["checks"] and all("check" in c and "ok" in c for c in p["checks"])
    # A bullish measured move must sit above the trigger, not below it.
    assert p["target"] > p["trigger"]


def test_base_rate_refuses_to_quote_a_tiny_sample():
    out = patterns.analyse(_seeded(double_bottom), with_base_rates=True)
    for p in out["patterns"]:
        br = p.get("base_rate")
        if br and not br.get("reliable"):
            assert br["instances"] < patterns.MIN_SAMPLE
            assert "too few" in br["note"]
