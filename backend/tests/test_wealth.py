"""
Wealth desk: the ledger, the fee, and who can see what.

The failures worth testing for are the quiet ones. A high-water mark that
forgets a loss bills a client for making back their own money. A hurdle on
the whole quarter's capital charges a rupee that arrived last week for ninety
days. A sale of shares never bought leaves a holding of minus ten that every
total then carries. One manager reading another's client by guessing an id.
None of these crash; every one of them is a wrong invoice or a leak.

Handlers are called directly, as test_advisors.py does.
"""
import datetime as dt
import json
import os
import tempfile

import pytest
from fastapi import HTTPException

import accounts
import wealth as W


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))
        yield
        accounts.reset_for_tests(os.path.join(d, "accounts.db"))


@pytest.fixture
def routes(monkeypatch):
    import wealth_routes
    monkeypatch.setattr(wealth_routes, "QUOTES", {})
    return wealth_routes


def person(email):
    done = accounts.complete_login(accounts.start_login(email)["token"])
    return "Bearer " + done["session"], accounts.user_for_session(done["session"])


def days_ago(n):
    return (W.today() - dt.timedelta(days=n)).isoformat()


def quote(sym, ltp, prev=None, closes=None, dates=None):
    return {"symbol": sym, "ltp": ltp, "prev_close": prev or ltp, "change_pct": 0.0,
            "spark": closes or [], "spark_dates": dates or [], "name": sym.title(), "sector": "Tests"}


def desk(uid, **terms):
    return W.save_desk(uid, {"display_name": "Nadia Rahman", "reg_kind": "pms",
                             "registration": "INP000001234", "terms": terms})


def client(uid, **kw):
    return W.create_client(uid, dict({"name": "Ayesha Kapoor", "since": days_ago(400)}, **kw))


def ev(kind, on, **kw):
    return dict({"kind": kind, "on_date": on}, **kw)


# ── The ledger ───────────────────────────────────────────────────────────

def test_profit_is_the_same_number_whichever_way_it_is_added_up():
    """Realised + on paper + dividends − charges must equal value − capital.
    If they ever differ, one of the screens is lying."""
    events = [ev("deposit", "2025-01-02", amount=100000, id=1),
              ev("buy", "2025-01-03", symbol="AAA", qty=100, price=500, charges=50, id=2),
              ev("buy", "2025-02-03", symbol="AAA", qty=50, price=600, id=3),
              ev("sell", "2025-03-03", symbol="AAA", qty=120, price=700, charges=60, id=4),
              ev("dividend", "2025-03-10", amount=900, id=5),
              ev("buy", "2025-04-01", symbol="BBB", qty=10, price=2000, id=6)]
    st = W.replay(events)
    # FIFO: 100 @ 500 then 20 @ 600 were sold.
    assert st.realised["AAA"] == pytest.approx(120 * 700 - (100 * 500 + 20 * 600))
    assert st.qty("AAA") == pytest.approx(30)
    lv = W._levels(st, {"AAA": 650, "BBB": 1900})
    value = lv["mv"] + st.cash
    assert lv["total"] == pytest.approx(value - st.capital)
    assert lv["total"] == pytest.approx(lv["realised"] + lv["unrealised"] + 900 - 110)


def test_a_buy_with_no_money_recorded_tops_the_capital_up_by_exactly_the_shortfall():
    """Most managers record trades, not money. Capital is then what the client
    had to put in: sale proceeds are spent before anything new is added."""
    events = [ev("buy", "2025-01-03", symbol="AAA", qty=10, price=1000, id=1),     # needs 10,000
              ev("sell", "2025-02-03", symbol="AAA", qty=10, price=1200, id=2),    # 12,000 back
              ev("buy", "2025-03-03", symbol="BBB", qty=10, price=1500, id=3)]     # 15,000: 3,000 more
    st = W.replay(events)
    assert st.capital == pytest.approx(13000)
    assert st.topups == pytest.approx(13000)
    assert st.cash == pytest.approx(0)
    assert [round(a) for _, a in st.flows] == [-10000, -3000]


def test_selling_shares_that_were_never_bought_is_refused_and_nothing_is_written():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(30), symbol="AAA", qty=10, price=100)])
    with pytest.raises(ValueError, match="only 10 were held"):
        W.add_events(u["id"], c["id"], [ev("buy", days_ago(5), symbol="BBB", qty=1, price=10),
                                         ev("sell", days_ago(4), symbol="AAA", qty=11, price=120)])
    # All or nothing: the valid buy in the same request did not land either.
    assert len(W._events_for(W._conn(), u["id"], c["id"])) == 1


def test_a_buy_that_a_later_sale_depends_on_cannot_be_deleted():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    r = W.add_events(u["id"], c["id"], [ev("buy", days_ago(30), symbol="AAA", qty=10, price=100),
                                         ev("sell", days_ago(10), symbol="AAA", qty=10, price=130)])
    with pytest.raises(ValueError, match="later entry"):
        W.delete_event(u["id"], c["id"], r["ids"][0])
    W.delete_event(u["id"], c["id"], r["ids"][1])
    W.delete_event(u["id"], c["id"], r["ids"][0])


def test_a_withdrawal_larger_than_the_cash_is_refused():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("deposit", days_ago(60), amount=50000),
                                     ev("buy", days_ago(50), symbol="AAA", qty=40, price=1000)])
    with pytest.raises(ValueError, match="was in cash"):
        W.add_events(u["id"], c["id"], [ev("withdrawal", days_ago(1), amount=20000)])


def test_a_bonus_doubles_the_shares_and_halves_the_cost_and_the_recommended_price():
    events = [ev("buy", "2025-01-03", symbol="AAA", qty=10, price=1000, rec_price=980, id=1),
              ev("split", "2025-05-01", symbol="AAA", qty=2, id=2)]
    st = W.replay(events)
    lot = st.lots["AAA"][0]
    assert (lot[0], lot[1], lot[3]) == (20, 500, 490)
    assert st.open_cost() == pytest.approx(10000)


# ── Returns ──────────────────────────────────────────────────────────────

def test_xirr_of_ten_percent_in_a_year_is_ten_percent():
    assert W.xirr([("2025-01-01", -100000), ("2026-01-01", 110000)]) == pytest.approx(0.10, abs=1e-4)
    assert W.xirr([("2025-01-01", -100)]) is None


def test_capital_is_counted_for_the_days_it_was_invested():
    """₹1,00,000 for the whole of a 90-day period and ₹90,000 more for the
    last ten days is 1,00,000×90 + 90,000×10 rupee-days, not 1,90,000×90."""
    events = [ev("deposit", "2026-01-01", amount=100000, id=1),
              ev("deposit", "2026-03-22", amount=90000, id=2)]
    st = W.replay(events)
    assert W.capital_days(st, "2026-01-01", "2026-04-01") == pytest.approx(100000 * 90 + 90000 * 10)


# ── The fee ──────────────────────────────────────────────────────────────

T = W.clean_terms({"share_pct": 20, "hurdle_pct": 0, "hwm": True, "period": "quarterly"})


def test_the_hard_hurdle_takes_the_share_only_from_profit_above_it():
    t = W.clean_terms({"share_pct": 20, "hurdle_pct": 10, "hurdle_type": "hard"})
    m = W.fee_math(t, level=30000, base=0, cap_days=1_000_000 * 182.5, days=182)
    assert m["hurdle"] == pytest.approx(50000)          # 10% a year on 10 lakh for half a year
    assert m["share"] == 0                               # 30,000 does not clear 50,000
    m = W.fee_math(t, level=80000, base=0, cap_days=1_000_000 * 182.5, days=182)
    assert m["share"] == pytest.approx(0.20 * 30000)


def test_the_soft_hurdle_takes_the_share_from_all_of_it_once_cleared():
    t = W.clean_terms({"share_pct": 20, "hurdle_pct": 10, "hurdle_type": "soft"})
    m = W.fee_math(t, level=80000, base=0, cap_days=1_000_000 * 182.5, days=182)
    assert m["share"] == pytest.approx(0.20 * 80000)
    m = W.fee_math(t, level=40000, base=0, cap_days=1_000_000 * 182.5, days=182)
    assert m["share"] == 0


def test_the_share_comes_after_the_fixed_fee_and_gst_goes_on_both():
    t = W.clean_terms({"share_pct": 10, "fixed_pct": 2, "gst_pct": 18})
    m = W.fee_math(t, level=100000, base=0, cap_days=1_000_000 * 365, days=365)
    assert m["fixed"] == pytest.approx(20000)
    assert m["share"] == pytest.approx(0.10 * 80000)
    assert m["gst"] == pytest.approx(0.18 * 28000)
    assert m["total"] == pytest.approx(28000 * 1.18)


def _settled_client(uid, terms):
    desk(uid)
    c = client(uid, since=days_ago(300), terms=terms)
    W.add_events(uid, c["id"], [ev("deposit", days_ago(300), amount=1_000_000),
                                ev("buy", days_ago(299), symbol="AAA", qty=1000, price=1000)])
    return c


def test_a_client_who_lost_money_pays_no_share_until_the_loss_is_made_back():
    """The whole point of a high-water mark. Billed at 1,00,000 of profit;
    then the book falls to 40,000; then recovers to 1,30,000. The share is on
    30,000 — the new ground — not on the 90,000 climb back."""
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20, "hwm": True})
    W.record_past(u["id"], c["id"], {"period_end": days_ago(200), "level": 100000, "amount": 20000,
                                    "status": "paid"})
    W.record_past(u["id"], c["id"], {"period_end": days_ago(100), "level": 40000})
    b = W.compute_book(W.load(u["id"]), {"AAA": quote("AAA", 1130)})
    fee = b["clients"][0]["fee"]
    assert fee["base"] == pytest.approx(100000)
    assert fee["gain"] == pytest.approx(30000)
    assert fee["share"] == pytest.approx(6000)
    # Below the mark: nothing due, and the gap is reported.
    b = W.compute_book(W.load(u["id"]), {"AAA": quote("AAA", 1060)})
    fee = b["clients"][0]["fee"]
    assert fee["total"] == 0 and fee["to_hwm"] == pytest.approx(40000)
    assert any(a["kind"] == "below_hwm" for a in b["alerts"])


def test_without_a_high_water_mark_the_share_is_on_the_rise_since_the_last_settlement():
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20, "hwm": False})
    W.record_past(u["id"], c["id"], {"period_end": days_ago(200), "level": 100000})
    W.record_past(u["id"], c["id"], {"period_end": days_ago(100), "level": 40000})
    fee = W.compute_book(W.load(u["id"]), {"AAA": quote("AAA", 1130)})["clients"][0]["fee"]
    assert fee["base"] == pytest.approx(40000)
    assert fee["share"] == pytest.approx(0.20 * 90000)


def test_booked_basis_ignores_gains_on_paper():
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20, "basis": "realised"})
    fee = W.compute_book(W.load(u["id"]), {"AAA": quote("AAA", 1500)})["clients"][0]["fee"]
    assert fee["total"] == 0
    W.add_events(u["id"], c["id"], [ev("sell", days_ago(3), symbol="AAA", qty=100, price=1400)])
    fee = W.compute_book(W.load(u["id"]), {"AAA": quote("AAA", 1500)})["clients"][0]["fee"]
    assert fee["share"] == pytest.approx(0.20 * 40000)


def test_settling_moves_the_mark_and_only_the_latest_can_be_undone():
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20, "hwm": True})
    # A past date is valued at that day's close, from the quote's history.
    dates = [days_ago(i) for i in (21, 20, 19)]
    q = {"AAA": quote("AAA", 1100, closes=[1040, 1050, 1060], dates=dates)}
    s1 = W.settle(u["id"], c["id"], q, as_of=days_ago(20))
    assert s1["level_total"] == pytest.approx(50000)          # 1,000 shares × ₹50
    assert s1["amount"] == pytest.approx(10000) and s1["status"] == "due"
    # A date the history does not reach is refused, not guessed.
    with pytest.raises(ValueError, match="not available"):
        W.settle(u["id"], c["id"], {"AAA": quote("AAA", 1100)}, as_of=days_ago(10))
    s2 = W.settle(u["id"], c["id"], q)                         # today, at ₹1,100
    assert s2["level_total"] == pytest.approx(100000)
    assert s2["amount"] == pytest.approx(0.20 * 50000)         # only the new ground
    with pytest.raises(ValueError, match="Only the most recent"):
        W.undo_settlement(u["id"], s1["id"])
    W.undo_settlement(u["id"], s2["id"])
    paid = W.mark_settlement(u["id"], s1["id"], "paid", days_ago(2))
    assert paid["status"] == "paid" and paid["paid_on"] == days_ago(2)
    b = W.compute_book(W.load(u["id"]), q)
    assert b["totals"]["due"] == 0
    fy_start, _ = W.fy_of(W.today())
    if W._d(days_ago(2)) >= fy_start:
        assert b["totals"]["collected_fy"] == pytest.approx(10000)


def test_a_settlement_cannot_be_measured_without_a_price():
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20})
    with pytest.raises(ValueError, match="No price yet"):
        W.settle(u["id"], c["id"], {})


def test_a_settlement_from_before_altaha_is_measured_from_the_value_that_day():
    _, u = person("nadia@example.com")
    c = _settled_client(u["id"], {"share_pct": 20})
    s = W.record_past(u["id"], c["id"], {"period_end": days_ago(100), "value": 1_120_000,
                                        "amount": 24000, "status": "paid"})
    assert s["level_total"] == pytest.approx(120000)
    assert s["status"] == "paid"


def test_quarters_end_where_the_financial_year_does():
    assert W.next_due("2026-08-14", "quarterly") == "2026-09-30"
    assert W.next_due("2026-09-30", "quarterly") == "2026-12-31"
    assert W.next_due("2026-10-01", "half-yearly") == "2027-03-31"
    assert W.next_due("2026-04-01", "yearly") == "2027-03-31"
    assert W.next_due("2026-01-15", "monthly") == "2026-01-31"


# ── Recommendations ──────────────────────────────────────────────────────

def test_one_call_is_booked_for_many_clients_with_the_recommended_price_kept():
    _, u = person("nadia@example.com")
    desk(u["id"])
    a = client(u["id"], name="Ayesha Kapoor")
    b = client(u["id"], name="Rohan Shah")
    r = W.create_rec(u["id"], {"symbol": "TCS", "action": "buy", "price": 3300, "target": 4000,
                               "stop": 3000, "on_date": days_ago(5)})
    W.apply_rec(u["id"], r["id"], [{"client_id": a["id"], "qty": 10, "price": 3280, "on_date": days_ago(4)},
                                   {"client_id": b["id"], "amount": 100000, "on_date": days_ago(4)}])
    book = W.compute_book(W.load(u["id"]), {"TCS": quote("TCS", 3500)})
    ha = book["clients"][0]["holdings"][0]
    assert ha["rec_price"] == 3300 and ha["avg"] == 3280
    assert ha["edge_pct"] == pytest.approx(100 * 20 / 3300, abs=0.01)
    assert ha["target"] == 4000
    assert book["clients"][1]["holdings"][0]["qty"] == 30        # ₹1,00,000 at ₹3,300
    rec = book["recs"][0]
    assert len(rec["fills"]) == 2 and rec["since_pct"] == pytest.approx(100 * (3500 / 3300 - 1), abs=0.01)


def test_a_sell_call_that_one_client_cannot_fill_books_nobody():
    _, u = person("nadia@example.com")
    desk(u["id"])
    a = client(u["id"], name="Ayesha Kapoor")
    b = client(u["id"], name="Rohan Shah")
    W.add_events(u["id"], a["id"], [ev("buy", days_ago(40), symbol="ITC", qty=100, price=400)])
    r = W.create_rec(u["id"], {"symbol": "ITC", "action": "sell", "price": 450, "on_date": days_ago(2)})
    with pytest.raises(ValueError, match="holds no ITC"):
        W.apply_rec(u["id"], r["id"], [{"client_id": a["id"], "all": True},
                                       {"client_id": b["id"], "all": True}])
    assert len(W._events_for(W._conn(), u["id"], a["id"])) == 1


def test_a_buy_target_below_the_price_is_refused():
    _, u = person("nadia@example.com")
    desk(u["id"])
    with pytest.raises(ValueError, match="target should be above"):
        W.create_rec(u["id"], {"symbol": "TCS", "price": 3300, "target": 3000})


# ── Import ───────────────────────────────────────────────────────────────

def test_a_pasted_holdings_file_is_read_with_or_without_a_header():
    rows = W.parse_import("Symbol\tQty\tAvg price\tDate\tReco price\n"
                          "RELIANCE\t10\t1,250.50\t03/01/2025\t1240\nTCS.NS\t5\t3300\t\t")
    assert [(r["symbol"], r["qty"], r["price"], r["rec_price"]) for r in rows] == \
        [("RELIANCE", 10, 1250.5, 1240), ("TCS", 5, 3300, None)]
    assert rows[0]["on_date"] == "2025-01-03"
    bare = W.parse_import("INFY,20,1500")
    assert bare[0]["symbol"] == "INFY" and bare[0]["kind"] == "buy"
    with pytest.raises(ValueError, match="Row 2"):
        W.parse_import("INFY,20,1500\nTCS,abc,10")


# ── Who can see what ─────────────────────────────────────────────────────

def test_one_manager_cannot_read_or_touch_anothers_client(routes):
    ta, a = person("nadia@example.com")
    tb, b = person("other@example.com")
    desk(a["id"])
    desk(b["id"])
    c = client(a["id"])
    for call in (lambda: routes.wealth_edit_client(c["id"], {"name": "Hijacked"}, authorization=tb),
                 lambda: routes.wealth_delete_client(c["id"], authorization=tb),
                 lambda: routes.wealth_add_events(c["id"], {"kind": "deposit", "amount": 1,
                                                            "on_date": days_ago(1)}, authorization=tb)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    assert routes.wealth_book(authorization=tb)["clients"] == []
    assert routes.wealth_book(authorization=ta)["clients"][0]["name"] == "Ayesha Kapoor"


def test_signed_out_is_401_and_no_desk_is_403(routes):
    with pytest.raises(HTTPException) as e:
        routes.wealth_book(authorization=None)
    assert e.value.status_code == 401
    tok, _ = person("nadia@example.com")
    with pytest.raises(HTTPException) as e:
        routes.wealth_book(authorization=tok)
    assert e.value.status_code == 403
    assert routes.wealth_desk(authorization=tok)["desk"] is None


def test_a_client_sees_their_own_portfolio_only_when_the_manager_switches_it_on(routes):
    tm, m = person("nadia@example.com")
    tc, _ = person("ayesha@example.com")
    desk(m["id"])
    c = client(m["id"], email="Ayesha@Example.com", notes="Nervous about banks; call monthly.")
    W.add_events(m["id"], c["id"], [ev("buy", days_ago(10), symbol="TCS", qty=1, price=3000,
                                       note="Talked her into it")])
    client(m["id"], name="Someone Else", email="else@example.com", portal=True)
    assert routes.wealth_shared(authorization=tc)["portfolios"] == []
    W.update_client(m["id"], c["id"], {"portal": True})
    got = routes.wealth_shared(authorization=tc)["portfolios"]
    assert len(got) == 1
    view = got[0]["client"]
    assert view["name"] == "Ayesha Kapoor" and "notes" not in view
    # The manager's own working on a trade is not part of the client's statement.
    assert "Talked her into it" not in json.dumps(view)
    assert all("note" not in e for e in view["events"] if not e.get("auto"))
    assert got[0]["desk"]["display_name"] == "Nadia Rahman"
    with pytest.raises(ValueError, match="email address"):
        W.update_client(m["id"], c["id"], {"email": "", "portal": True})


def test_a_desk_and_everything_on_it_can_be_deleted(routes):
    tok, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("deposit", days_ago(3), amount=100)])
    with pytest.raises(HTTPException):
        routes.wealth_delete_desk({"confirm": "yes"}, authorization=tok)
    out = routes.wealth_delete_desk({"confirm": "DELETE"}, authorization=tok)
    assert out["deleted"]["wm_clients"] == 1 and out["deleted"]["wm_events"] == 1
    assert W.get_desk(u["id"]) is None


def test_a_registration_number_must_look_like_one():
    _, u = person("nadia@example.com")
    with pytest.raises(ValueError, match="INP followed by nine digits"):
        W.save_desk(u["id"], {"display_name": "Nadia", "reg_kind": "pms", "registration": "INA000001234"})
    d = W.save_desk(u["id"], {"display_name": "Nadia", "reg_kind": "ria", "registration": "ina000001234",
                              "terms": {"share_pct": 20}})
    assert d["registration"] == "INA000001234"
    assert any("investment adviser" in n for n in d["notes"])


# ── The payloads ─────────────────────────────────────────────────────────

def _dates(n=30):
    out, d = [], W.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return list(reversed(out))


def test_the_sample_desk_is_a_whole_book_with_nothing_missing_or_infinite(routes, monkeypatch):
    dates = _dates()
    q = {}
    for s, p in W._SAMPLE_PRICE.items():
        closes = [round(p * (0.94 + 0.06 * i / 29), 2) for i in range(30)]
        q[s] = quote(s, closes[-1], closes[-2], closes, dates)
    monkeypatch.setattr(routes, "QUOTES", q)
    b = routes.wealth_demo()
    json.dumps(b, allow_nan=False)
    assert b["demo"] and len(b["clients"]) == 5
    assert b["totals"]["aum"] > 0 and b["totals"]["accrued"] >= 0
    assert len(b["spark"]["values"]) == 30
    for c in b["clients"]:
        assert c["holdings"] and c["fee"]["steps"][-1]["key"] == "total"
        assert c["profit"] == pytest.approx(c["value"] - c["capital"], abs=1)
    assert [s["move"] for s in b["commission"]["sensitivity"]] == [-20, -10, -5, 0, 5, 10, 20]


def test_the_book_never_fails_to_open_on_a_ledger_that_does_not_add_up():
    """A row written before a validation existed, or by hand, must not take
    the whole desk down: it is reported on the client instead."""
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    conn = W._conn()
    with conn:
        conn.execute("INSERT INTO wm_events(user_id, client_id, kind, symbol, qty, price, on_date, created_at) "
                     "VALUES(?,?,?,?,?,?,?,?)", (u["id"], c["id"], "sell", "AAA", 5, 100, days_ago(3), "x"))
    b = W.compute_book(W.load(u["id"]), {})
    assert b["clients"][0]["errors"]


def test_the_csv_exports_carry_every_client(routes, monkeypatch):
    tok, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(3), symbol="TCS", qty=2, price=3000)])
    monkeypatch.setattr(routes, "QUOTES", {"TCS": quote("TCS", 3100)})
    for what, head in (("holdings", "symbol"), ("ledger", "kind"), ("fees", "period_start")):
        body = routes.wealth_export(what, authorization=tok).body.decode()
        assert head in body.splitlines()[0] and "Ayesha Kapoor" in body


# ── The browser fixture ──────────────────────────────────────────────────

def test_the_browser_fixture_is_the_book_the_server_sends():
    """wealth-browser.cjs draws a committed book. If compute_book's output moves
    on and the fixture does not, the browser test goes on passing against a
    page nobody will ever see. Rebuild it with
    backend/tests/make_wealth_fixture.py."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from make_wealth_fixture import OUT, build

    with open(OUT, encoding="utf-8") as fh:
        committed = json.load(fh)
    fresh = json.loads(json.dumps(build()))
    assert committed == fresh, "rebuild frontend/tests/fixtures/wealth-demo.json"
    assert os.path.getsize(OUT) < 120_000


def test_a_name_that_looks_like_a_formula_is_exported_as_text(routes, monkeypatch):
    tok, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"], name="=HYPERLINK(\"http://x\")")
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(3), symbol="TCS", qty=2, price=3000)])
    monkeypatch.setattr(routes, "QUOTES", {"TCS": quote("TCS", 3100)})
    body = routes.wealth_export("holdings", authorization=tok).body.decode()
    assert "'=HYPERLINK" in body


# ── Correcting the ledger ────────────────────────────────────────────────

def _held(uid, cid, sym):
    st = W.replay(W._events_for(W._conn(), uid, cid))
    lots = st.lots.get(sym) or []
    q = sum(l[0] for l in lots)
    return q, (sum(l[0] * l[1] for l in lots) / q if q else None), st


def test_a_buying_price_typed_wrong_is_corrected_on_the_entry_and_everything_follows():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    r = W.add_events(u["id"], c["id"], [ev("buy", days_ago(60), symbol="TCS", qty=10, price=3500)])
    W.update_events(u["id"], c["id"], [{"id": r["ids"][0], "price": 3050, "rec_price": 3000}])
    q, avg, st = _held(u["id"], c["id"], "TCS")
    assert (q, avg) == (10, 3050)
    book = W.compute_book(W.load(u["id"]), {"TCS": quote("TCS", 3400)})
    h = book["clients"][0]["holdings"][0]
    assert h["avg"] == 3050 and h["rec_price"] == 3000 and h["pnl"] == pytest.approx(3500)
    # The capital follows the price: nothing was deposited, so the top-up is
    # the corrected cost, and value less capital is still the profit.
    cl = book["clients"][0]
    assert cl["capital"] == pytest.approx(30500)
    assert cl["profit"] == pytest.approx(cl["value"] - cl["capital"])


def test_an_edit_that_would_break_a_later_sale_is_refused_and_nothing_changes():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    r = W.add_events(u["id"], c["id"], [ev("buy", days_ago(60), symbol="TCS", qty=10, price=3500),
                                         ev("sell", days_ago(20), symbol="TCS", qty=8, price=3600)])
    with pytest.raises(ValueError, match="break the ledger"):
        W.update_events(u["id"], c["id"], [{"id": r["ids"][0], "qty": 5}])
    assert _held(u["id"], c["id"], "TCS")[0] == 2
    with pytest.raises(LookupError):
        W.update_events(u["id"], c["id"], [{"id": 999999, "price": 1}])


def test_a_holdings_average_is_corrected_across_every_purchase_it_draws_on():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(90), symbol="HAL", qty=10, price=4000),
                                     ev("buy", days_ago(60), symbol="HAL", qty=30, price=4400)])
    W.set_holding(u["id"], c["id"], "HAL", avg=4000)
    q, avg, _ = _held(u["id"], c["id"], "HAL")
    assert q == 40 and avg == pytest.approx(4000)
    prices = sorted(e["price"] for e in W._events_for(W._conn(), u["id"], c["id"]))
    assert prices[1] / prices[0] == pytest.approx(4400 / 4000)        # proportions kept


def test_a_recommended_price_set_after_a_bonus_lands_in_each_purchases_own_terms():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(90), symbol="ITC", qty=100, price=400),
                                     ev("split", days_ago(30), symbol="ITC", qty=2)])
    W.set_holding(u["id"], c["id"], "ITC", rec_price=195)            # today's terms, after the bonus
    buy = [e for e in W._events_for(W._conn(), u["id"], c["id"]) if e["kind"] == "buy"][0]
    assert buy["rec_price"] == pytest.approx(390)                     # the purchase's own day
    h = W.compute_book(W.load(u["id"]), {"ITC": quote("ITC", 210)})["clients"][0]["holdings"][0]
    assert h["rec_price"] == pytest.approx(195) and h["qty"] == 200


# ── A holdings statement ─────────────────────────────────────────────────

def _book_of(uid, cid):
    st = W.replay(W._events_for(W._conn(), uid, cid))
    out = {}
    for s, lots in st.lots.items():
        q = sum(l[0] for l in lots)
        if q > 1e-6:
            out[s] = (round(q, 4), round(sum(l[0] * l[1] for l in lots) / q, 2))
    return out


def test_a_statement_brings_the_book_to_match_it_holding_by_holding():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(200), symbol="AAA", qty=50, price=100),   # more
                                     ev("buy", days_ago(200), symbol="BBB", qty=40, price=200),   # fewer
                                     ev("buy", days_ago(200), symbol="CCC", qty=10, price=300),   # price
                                     ev("buy", days_ago(200), symbol="DDD", qty=5, price=400),    # same
                                     ev("buy", days_ago(200), symbol="EEE", qty=7, price=500)])   # gone
    rows = [{"symbol": "AAA", "qty": 80, "avg": 110, "close": 120},
            {"symbol": "BBB", "qty": 25, "avg": 200, "close": 260},
            {"symbol": "CCC", "qty": 10, "avg": 290, "close": 310},
            {"symbol": "DDD", "qty": 5, "avg": 400, "close": 420},
            {"symbol": "NEW", "qty": 12, "avg": 55.5, "close": 60}]
    plan = W.statement_plan(u["id"], c["id"], {"rows": rows, "as_of": days_ago(1)}, {"EEE": {"ltp": 520}})
    status = {it["symbol"]: it["status"] for it in plan["items"]}
    assert status == {"AAA": "more", "BBB": "fewer", "CCC": "price", "DDD": "same", "NEW": "new", "EEE": "gone"}
    more = [it for it in plan["items"] if it["symbol"] == "AAA"][0]
    assert more["ops"][0]["qty"] == 30
    assert more["ops"][0]["price"] == pytest.approx((80 * 110 - 50 * 100) / 30)   # makes the averages agree
    fewer = [it for it in plan["items"] if it["symbol"] == "BBB"][0]
    assert fewer["ops"][0] == dict(fewer["ops"][0], kind="sell", qty=15, price=260)
    assert _book_of(u["id"], c["id"])["AAA"] == (50, 100)                       # a plan writes nothing
    out = W.statement_apply(u["id"], c["id"], {"rows": rows, "as_of": days_ago(1)}, {"EEE": {"ltp": 520}})
    assert out["done"] == {"more": 1, "fewer": 1, "price": 1, "new": 1, "gone": 1}
    assert _book_of(u["id"], c["id"]) == {"AAA": (80, 110), "BBB": (25, 200), "CCC": (10, 290),
                                          "DDD": (5, 400), "NEW": (12, 55.5)}


def test_a_holding_left_out_or_with_no_price_is_not_touched():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    W.add_events(u["id"], c["id"], [ev("buy", days_ago(200), symbol="AAA", qty=50, price=100),
                                     ev("buy", days_ago(200), symbol="ZZZ", qty=3, price=900)])
    rows = [{"symbol": "AAA", "qty": 60, "avg": 100}, {"symbol": "NEW", "qty": 1, "avg": 10}]
    plan = W.statement_plan(u["id"], c["id"], {"rows": rows}, {})
    gone = [it for it in plan["items"] if it["symbol"] == "ZZZ"][0]
    assert gone["status"] == "gone" and not gone["include"] and gone["needs_price"]
    W.statement_apply(u["id"], c["id"], {"rows": rows, "skip": ["NEW"]}, {})
    assert _book_of(u["id"], c["id"]) == {"AAA": (60, 100), "ZZZ": (3, 900)}
    # With the sale price given, the gone holding is sold.
    W.statement_apply(u["id"], c["id"], {"rows": rows, "skip": ["NEW"], "prices": {"ZZZ": 950}}, {})
    assert "ZZZ" not in _book_of(u["id"], c["id"])


def test_a_first_statement_adds_every_row_and_the_same_stock_twice_is_one_holding():
    _, u = person("nadia@example.com")
    desk(u["id"])
    c = client(u["id"])
    rows = [{"symbol": "YESBANK", "qty": 548, "avg": 19.46}, {"symbol": "IDEA", "qty": 347, "avg": 12.94},
            {"symbol": "YESBANK", "qty": 52, "avg": 20.5}]
    out = W.statement_apply(u["id"], c["id"], {"rows": rows, "mode": "add", "as_of": days_ago(1),
                                               "buy_date": days_ago(300)}, {})
    assert out["added"] == 2
    b = _book_of(u["id"], c["id"])
    assert b["YESBANK"][0] == 600 and b["YESBANK"][1] == pytest.approx((548 * 19.46 + 52 * 20.5) / 600, abs=0.01)
    assert {e["on_date"] for e in W._events_for(W._conn(), u["id"], c["id"])} == {days_ago(300)}


def test_isins_map_to_symbols_and_nothing_else_is_asked(monkeypatch):
    import fund_portfolios
    monkeypatch.setattr(fund_portfolios, "isin_map", lambda *a, **k: ({"INE528G01035": "YESBANK",
                                                                       "INE669E01016": "IDEA"}, {"stale": False}))
    out = W.isin_symbols(["ine528g01035", "INE669E01016", "INE000000000", "not-an-isin"])
    assert out["map"] == {"INE528G01035": "YESBANK", "INE669E01016": "IDEA"}
    assert out["missing"] == ["INE000000000"]


def test_corrections_and_statements_answer_404_for_another_managers_client(routes):
    ta, a = person("nadia@example.com")
    tb, b = person("other@example.com")
    desk(a["id"])
    desk(b["id"])
    c = client(a["id"])
    r = W.add_events(a["id"], c["id"], [ev("buy", days_ago(30), symbol="TCS", qty=1, price=3000)])
    for call in (lambda: routes.wealth_edit_event(c["id"], r["ids"][0], {"price": 1}, authorization=tb),
                 lambda: routes.wealth_edit_holding(c["id"], "TCS", {"avg": 1}, authorization=tb),
                 lambda: routes.wealth_statement_plan(c["id"], {"rows": [{"symbol": "TCS", "qty": 1, "avg": 1}]},
                                                      authorization=tb)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    out = routes.wealth_edit_event(c["id"], r["ids"][0], {"price": 3100}, authorization=ta)
    assert out["changed"] == 1
