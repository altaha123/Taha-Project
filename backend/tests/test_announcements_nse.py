"""
The NSE fallback feed, which is what production runs on whenever BSE's WAF
refuses the datacenter IP.

Three things broke the WOW view at once when it did, and each has a test:
  · NSE's timestamp ("25-Sep-2026 08:28:51") was not parsed, so every filing
    had no date and an order could not be placed in a week or a quarter.
  · NSE files orders under a fixed subject ("Bagging/Receiving of
    orders/contracts") that the keyword rules never matched.
  · A week of NSE filings is thousands of rows; order wins must survive the
    cap on the general feed.
"""
import announcements as A


class _Resp:
    def __init__(self, rows, status=200):
        self._rows, self.status_code = rows, status

    def json(self):
        return self._rows


def _row(desc, text, sym="ABC", when="25-Sep-2026 08:28:51"):
    return {"desc": desc, "attchmntText": text, "symbol": sym, "sm_name": sym + " Ltd",
            "an_dt": when, "sort_date": "2026-09-25 08:28:51",
            "attchmntFile": "https://nsearchives.nseindia.com/corporate/%s.pdf" % sym}


def _feed(monkeypatch, rows):
    calls = []

    def get(url, **kw):
        calls.append((url, kw.get("params")))
        return _Resp(rows) if "api/corporate-announcements" in url else _Resp([])
    monkeypatch.setattr(A._session, "get", get)
    monkeypatch.setitem(A._nse_warm, "at", 0.0)
    return calls


def test_nse_timestamps_are_parsed():
    d = A._parse_dt("25-Sep-2026 08:28:51")
    assert d is not None and (d.year, d.month, d.day, d.hour) == (2026, 9, 25, 8)


def test_nse_order_subjects_are_order_wins(monkeypatch):
    _feed(monkeypatch, [
        _row("Bagging/Receiving of orders/contracts",
             "XYZ Limited has informed the Exchange about Bagging/Receiving of orders/contracts"),
        _row("Awarding of order(s)/contract(s)", "XYZ secured a contract", sym="DEF"),
        _row("Trading Window", "Closure of trading window", sym="GHI"),
    ])
    out, note = A._nse_rows(7)
    assert note == "NSE: 3 rows"
    cats = {r["symbol"]: r["category"] for r in out}
    assert cats == {"ABC": "Order win", "DEF": "Order win", "GHI": "Trading window"}
    assert all(r["at"] and r["epoch"] for r in out)
    # The company's own sentence is the headline, not NSE's generic subject.
    assert out[1]["headline"] == "XYZ secured a contract"


def test_nse_is_asked_for_the_whole_window(monkeypatch):
    calls = _feed(monkeypatch, [_row("Updates", "x")])
    A._nse_rows(7)
    params = [p for u, p in calls if "api/corporate-announcements" in u][0]
    assert set(params) == {"from_date", "to_date"}


def test_orders_survive_the_general_feed_cap(monkeypatch):
    monkeypatch.setitem(A._state, "items", [])
    monkeypatch.setitem(A._state, "orders", [])
    monkeypatch.setattr(A, "MAX_STORED", 5)
    import time
    now = time.time()
    order = {"symbol": "ORD", "headline": "order", "at": "a", "epoch": now - 3600,
             "category": "Order win"}
    noise = [{"symbol": "N%d" % i, "headline": "tw", "at": str(i), "epoch": now - i,
              "category": "Trading window"} for i in range(50)]
    A._merge([order] + noise, lambda i: (i["symbol"], i["headline"], i["at"]))
    assert order not in A._state["items"]
    assert A.orders(7) == [order]
