"""
Shared fixtures.

The backend modules reach for the network at import time — yfinance, Dhan,
requests — so every test run would otherwise depend on a data provider being
up and on the machine having credentials. These stubs cut that dependency:
the tests exercise the analysis, not the feeds.
"""
import os
import sys
import types
import tempfile

import numpy as np
import pandas as pd
import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _OfflineSession:
    """
    A requests.Session that refuses rather than reaches.

    Several modules build a Session at import time — announcements warms one
    against the exchange's public pages before it will fetch anything — so the
    stub has to be shaped enough to construct. Every actual call raises, which
    is the point: a test that silently starts hitting the NSE is a test that
    passes on a good day and fails on a Sunday.
    """

    def __init__(self, *a, **k):
        self.headers = {}
        self.cookies = {}

    def _refuse(self, *a, **k):
        raise RuntimeError("network access is disabled in tests")

    get = post = put = head = request = mount = _refuse

    def close(self):
        pass


class _RequestException(Exception):
    pass


for _n in ("yfinance", "curl_cffi", "requests"):
    if _n not in sys.modules:
        _stub(_n, Ticker=lambda *a, **k: None,
              Session=_OfflineSession,
              get=_OfflineSession._refuse, post=_OfflineSession._refuse,
              RequestException=_RequestException,
              exceptions=types.SimpleNamespace(
                  RequestException=_RequestException,
                  Timeout=_RequestException,
                  ConnectionError=_RequestException,
                  HTTPError=_RequestException))
_stub("dhan_source", configured=lambda: False, daily_ohlcv=lambda *a, **k: None,
      intraday_ohlcv=lambda *a, **k: None)

# Every run gets its own ledger directory, so tests can never touch a real one.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="altaha-tests-"))
os.environ.setdefault("AUTOTRACK", "")


def ohlcv(closes, volume=None, tz=None, end=None):
    """
    A well-formed daily frame from a list of closes, ending TODAY by default.

    Ending today matters: anything that windows by date — marking a tracked
    idea, measuring a return since it was added — finds nothing in a frame
    whose last bar is months in the past, and the test fails for a reason that
    has nothing to do with the code under test.
    """
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(end=(end or pd.Timestamp.today().normalize()),
                        periods=len(closes), freq="B", tz=tz)
    c = pd.Series(closes, index=idx)
    if volume is None:
        volume = np.full(len(closes), 1_000_000.0)
    return pd.DataFrame({"Open": c.shift(1).fillna(c.iloc[0]),
                         "High": c * 1.02, "Low": c * 0.98, "Close": c,
                         "Volume": np.asarray(volume, dtype=float)}, index=idx)


def ramp(a, b, n):
    return list(np.linspace(a, b, n))


def arc(rim, low, n):
    """A rounded U — the shape a cup is supposed to have."""
    t = np.linspace(-1, 1, n)
    return list(low + (rim - low) * t ** 2)


@pytest.fixture
def uptrend():
    return ohlcv(ramp(80, 160, 260))


@pytest.fixture
def clean_tracker():
    """A tracker module with an empty ledger, restored afterwards."""
    import tracker
    before = tracker._cache["rows"]
    tracker._cache["rows"] = []
    tracker._save()
    yield tracker
    tracker._cache["rows"] = before if before is not None else []
    tracker._save()
