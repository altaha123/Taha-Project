"""
The three quarterly screens (fundamentals_screens.py) over a real, temporary
store: each one's rules, the order it lists in, the old ids that still
answer, and what happens when a figure is missing.

The failures that matter are quiet ones. A one-off gain counted as a business
turning round, because the stored EBITDA includes exceptional items. A bank
thrown off a growth screen for an operating margin it does not have, or put
on a free-cash-flow screen where its lending reads as cash. A missing figure
read as 0, so a company with no turnover figure "fails" a liquidity test, or a
company with no price is ranked as if its yield were nil. A list ordered by
size in ₹ crore, so the largest company always comes first. Each is pinned
here.
"""

import datetime as dt
import sys
import threading

import pytest

TODAY = dt.date(2026, 9, 25)
# Eight quarter-ends, newest first; the first four against the last four is
# "on the same quarter a year earlier".
QS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
      "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
FY = ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTAHA_FUNDAMENTALS_DB", str(tmp_path / "f.db"))
    for m in ("fundamentals_store", "fundamentals_screens"):
        sys.modules.pop(m, None)
    import fundamentals_store
    return fundamentals_store


@pytest.fixture()
def S(store, monkeypatch):
    """The module, with no scan on record and NSE's list shipped with the
    code standing for the industries, unless a test says otherwise."""
    import fundamentals_screens as S
    monkeypatch.setattr(S, "_scan_market", lambda today: {})
    return S


def _lenders(S, monkeypatch, *syms):
    """Mark these companies as NSE's Financial Services, as the shipped list
    marks a bank."""
    nse = dict(S._nse_industries())
    nse.update({s: "Financial Services" for s in syms})
    monkeypatch.setattr(S, "_nse_industries", lambda: nse)


# ── Rows, in the shape the crawl writes them ───────────────────────────────

def _quarter(store, sym, end, rev, pat, opm=15.0, ebitda=None, exc=0.0, oi=1.0, pbt=None,
             eps=None, bank=False):
    """One quarterly P&L row. The stored EBITDA includes exceptional items, as
    the crawl works it out, so pass `ebitda` with any gain inside it."""
    import fundamentals as F
    e = dt.date.fromisoformat(end)
    pbt = pat * 1.3 if pbt is None else pbt
    ebitda = rev * opm / 100.0 if ebitda is None else ebitda
    values = {"revenue": rev * 1e7, "pat": pat * 1e7, "ebitda": ebitda * 1e7,
              "exceptional": exc * 1e7, "pbt": pbt * 1e7,
              "pbt_before_exceptional": (pbt - exc) * 1e7, "other_income": oi * 1e7,
              "finance_cost": 5e7, "eps_basic": (pat / 10.0) if eps is None else eps}
    if pbt > 0:
        values["other_income_share_pct"] = round(oi / pbt * 100, 2)
    if bank:
        # The lines only a lender's format carries.
        values["operating_profit_pre_provision"] = pbt * 1.2e7
        values["provisions"] = pbt * 0.2e7
    row = store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "freq": "quarterly", "label": F.quarter_label(e),
        "period_from": (e - dt.timedelta(days=90)).isoformat(), "period_end": end,
        "months": 3, "filed_at": (e + dt.timedelta(days=40)).isoformat() + " 18:00:00",
        "source_url": "https://x/%s-%s.xml" % (sym, end)}, values)
    row["opm_pct"] = opm
    return row


def _put(store, rows):
    store.upsert("income", rows)
    for s in {r["symbol"] for r in rows}:
        store.recompute_yoy(s)


def _series(store, sym, revs, pats=None, opms=None, **kw):
    """Eight quarters, newest first."""
    pats = pats or [100.0] * 8
    opms = opms or [15.0] * 8
    _put(store, [_quarter(store, sym, e, r, p, opm=o, **kw)
                 for e, r, p, o in zip(QS, revs, pats, opms)])


def _year(store, sym, end, rev, pat, pbt=None, fin_cost=10.0):
    return store.to_row("income", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "freq": "annual", "label": "FY%s" % end[2:4], "period_end": end, "months": 12,
        "filed_at": end[:4] + "-05-20 18:00:00", "source_url": "https://x/%s-%s-y.xml" % (sym, end)},
        {"revenue": rev * 1e7, "pat": pat * 1e7, "pbt": (pat * 1.3 if pbt is None else pbt) * 1e7,
         "finance_cost": fin_cost * 1e7})


def _flow(store, sym, end, cfo, capex, months=12):
    return store.to_row("cashflow", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "label": "FY%s" % end[2:4], "period_end": end, "months": months,
        "filed_at": end[:4] + "-05-20 18:00:00", "source_url": "https://x/%s-%s-c.xml" % (sym, end)},
        {"cfo": cfo * 1e7, "capex": capex * 1e7, "fcf": (cfo - capex) * 1e7})


def _sheet(store, sym, end, equity, debt, cash, ci=0.0):
    return store.to_row("balance", {
        "symbol": sym, "company": sym.title() + " Ltd", "basis": "consolidated",
        "label": end, "period_end": end, "filed_at": end[:4] + "-05-20 18:00:00",
        "source_url": "https://x/%s-%s-b.xml" % (sym, end)},
        {"total_assets": (equity + debt) * 1.5e7, "total_equity": equity * 1e7,
         "total_borrowings": debt * 1e7, "cash_and_equivalents": cash * 1e7,
         "current_investments": ci * 1e7, "net_debt": (debt - cash - ci) * 1e7,
         "debt_equity_x": round(debt / equity, 2) if equity > 0 else None})


def _compounder(store, sym, cagr=10.0, pat=150.0, pbt=200.0, cfo=200.0, fcfs=(100.0, 90.0, 80.0),
                equity=1000.0, debt=100.0, cash=50.0, sheet_end=FY[0], quarter=True):
    """Four years of P&L growing `cagr`% a year, a full year of cash flow for
    each of `fcfs`, a balance sheet at `sheet_end` and the year before, and a
    quarter whose profit and EPS give 10 crore shares."""
    revs = [1000.0 * (1 + cagr / 100.0) ** k for k in (3, 2, 1, 0)]
    store.upsert("income", [_year(store, sym, FY[0], revs[0], pat, pbt=pbt)] +
                 [_year(store, sym, e, r, pat * 0.9) for e, r in zip(FY[1:], revs[1:])])
    store.upsert("cashflow", [_flow(store, sym, e, (cfo if i == 0 else f + 90.0), 90.0 if i else cfo - f)
                              for i, (e, f) in enumerate(zip(FY, fcfs))])
    prior = dt.date.fromisoformat(sheet_end).replace(year=int(sheet_end[:4]) - 1).isoformat()
    store.upsert("balance", [_sheet(store, sym, sheet_end, equity, debt, cash),
                             _sheet(store, sym, prior, equity * 0.9, debt, cash)])
    if quarter:
        _put(store, [_quarter(store, sym, QS[0], revs[0] / 4, 40.0, eps=4.0)])


def _names(S, res, screen):
    return [m["symbol"] for m in res[screen]]


def _match(res, screen, sym):
    return next(m for m in res[screen] if m["symbol"] == sym)


def _figs(m):
    return {f["label"]: (f["value"], f["unit"]) for f in m["figures"]}


# ── Fast growers with expanding margins ────────────────────────────────────

def test_growers_four_quarters_or_two_with_a_widening_margin(S, store):
    up25 = [1250.0] * 4 + [1000.0] * 4
    _series(store, "GROW", up25, opms=[16.0] * 4 + [15.0] * 4)
    # Two quarters of 16% with the margin up 3 points; the two before grew 5%.
    pair = [1160.0, 1160.0, 1050.0, 1050.0] + [1000.0] * 4
    _series(store, "PAIR", pair, opms=[18.0] + [15.0] * 7)
    _series(store, "PAIRFLAT", pair, opms=[16.0] + [15.0] * 7)          # margin up only 1
    _series(store, "DIP", [1250.0, 1250.0, 1180.0, 1250.0] + [1000.0] * 4)  # one quarter of 18%
    _series(store, "THIN", up25, opms=[6.0] * 8)                         # margin under 8%
    _series(store, "SQUEEZE", up25, opms=[13.0] * 4 + [15.0] * 4)        # margin down 2 points
    _series(store, "LOSS", up25, pats=[-10.0] + [100.0] * 7)             # a loss this quarter
    _series(store, "TTMLOSS", up25, pats=[10.0, -50.0, -50.0, -50.0] + [100.0] * 4)
    # Four quarters of 25%, but one quarter missing from the run of four.
    _put(store, [_quarter(store, "GAP", e, r, 100.0) for e, r in zip(QS, up25) if e != QS[3]])
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert sorted(_names(S, res, "steady_growers")) == ["GROW", "PAIR"]
    m = _match(res, "steady_growers", "GROW")
    assert m["as_of"] == "Q1 FY27" and "sort" in m
    figs = _figs(m)
    # Revenue growth for each of the four quarters, the margin and its change.
    assert [l for l in figs if l.startswith("Revenue YoY")] == [
        "Revenue YoY, Q1 FY27", "Revenue YoY, Q4 FY26", "Revenue YoY, Q3 FY26", "Revenue YoY, Q2 FY26"]
    assert figs["Revenue YoY, Q1 FY27"] == (25.0, "pct")
    assert figs["Operating margin, Q1 FY27"] == (16.0, "pct")
    assert figs["Operating margin vs a year earlier"] == (1.0, "pts")
    assert figs["PAT YoY, Q1 FY27"] == (0.0, "pct")
    assert _figs(_match(res, "steady_growers", "PAIR"))["Operating margin vs a year earlier"] == (3.0, "pts")


def test_growers_a_lender_is_never_judged_on_operating_margin(S, store, monkeypatch):
    up25 = [1250.0] * 4 + [1000.0] * 4
    # A bank's "operating margin" is not a figure its business has: 5%, and
    # falling 3 points, would fail both margin tests for anyone else.
    _series(store, "BANKA", up25, opms=[5.0] * 4 + [8.0] * 4)
    # The same, known as a lender from its own filing's lines, not its industry.
    _series(store, "BANKF", up25, opms=[5.0] * 4 + [8.0] * 4, bank=True)
    # The second route is moderate growth admitted by a widening margin; a
    # lender has no margin to show, so it needs the first.
    _series(store, "BANKB", [1160.0, 1160.0, 1050.0, 1050.0] + [1000.0] * 4,
            opms=[18.0] + [15.0] * 7)
    _lenders(S, monkeypatch, "BANKA", "BANKB")
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert sorted(_names(S, res, "steady_growers")) == ["BANKA", "BANKF"]
    for sym in ("BANKA", "BANKF"):
        labels = [f["label"] for f in _match(res, "steady_growers", sym)["figures"]]
        assert not [l for l in labels if "margin" in l.lower()], labels
        assert "Revenue YoY, Q1 FY27" in labels


def test_growers_turnover_is_tested_only_where_the_scan_measured_it(S, store):
    up25 = [1250.0] * 4 + [1000.0] * 4
    for s in ("ILLIQ", "LIQ", "UNMEASURED"):
        _series(store, s, up25)
    res = S.evaluate(store._connect(), today=TODAY,
                     market={"ILLIQ": {"turnover_cr": 1.5}, "LIQ": {"turnover_cr": 2.0},
                             "UNMEASURED": {"price": 400.0}})
    # A company with no traded value on record is not treated as trading 0.
    assert sorted(_names(S, res, "steady_growers")) == ["LIQ", "UNMEASURED"]


def test_growers_turnover_comes_from_the_latest_scan_on_record(store, monkeypatch, tmp_path):
    import fundamentals_screens as S
    import pit_store
    monkeypatch.setattr(pit_store, "_local", threading.local())
    monkeypatch.setitem(pit_store._state, "active_path", str(tmp_path / "pit.db"))
    pit_store.init_db()
    pit_store.snapshot_many({"ILLIQ": {"avg_turnover_cr": 0.8, "price": 50.0},
                             "LIQ": {"avg_turnover_cr": 30.0, "price": 900.0}},
                            as_of=TODAY - dt.timedelta(days=3))
    # A scan dated after the day asked about was not known on it.
    pit_store.snapshot_many({"ILLIQ": {"avg_turnover_cr": 9.0}}, as_of=TODAY + dt.timedelta(days=2))
    assert S._scan_market(TODAY) == {"ILLIQ": {"turnover_cr": 0.8, "price": 50.0},
                                     "LIQ": {"turnover_cr": 30.0, "price": 900.0}}
    assert S._scan_market(TODAY - dt.timedelta(days=4)) == {}
    # A scan from long ago describes another market.
    assert S._scan_market(TODAY + dt.timedelta(days=S.SCAN_FRESH_DAYS + 3)) == {}
    up25 = [1250.0] * 4 + [1000.0] * 4
    for s in ("ILLIQ", "LIQ"):
        _series(store, s, up25)
    res = S.evaluate(store._connect(), today=TODAY)
    assert _names(S, res, "steady_growers") == ["LIQ"]


def test_growers_are_ordered_on_growth_and_margin_never_on_size(S, store, monkeypatch):
    _series(store, "FAST", [1400.0] * 4 + [1000.0] * 4, opms=[19.0] * 4 + [15.0] * 4)
    _series(store, "GROW", [1250.0] * 4 + [1000.0] * 4, opms=[16.0] * 4 + [15.0] * 4)
    # The largest company, and the largest growth in ₹ crore by far.
    _series(store, "BIG", [121000.0] * 4 + [100000.0] * 4, pats=[10000.0] * 8,
            opms=[15.5] * 4 + [15.0] * 4)
    # One wild quarter against a near-empty base does not carry the order:
    # its middle quarter grew 22%.
    _series(store, "WILD", [5000.0, 1220.0, 1220.0, 1220.0] + [10.0, 1000.0, 1000.0, 1000.0],
            opms=[15.5] * 4 + [15.0] * 4)
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert _names(S, res, "steady_growers") == ["FAST", "GROW", "WILD", "BIG"]


# ── Operational turnarounds ────────────────────────────────────────────────

def _turn(store, sym, now, then, bank=False):
    """A quarter and the same quarter a year earlier, from two dicts of
    _quarter keyword arguments."""
    _put(store, [_quarter(store, sym, QS[0], bank=bank, **now),
                 _quarter(store, sym, QS[4], bank=bank, **then)])


AGO = {"rev": 480.0, "pat": -30.0, "ebitda": 20.0, "pbt": -39.0}


def test_turnarounds_need_the_business_itself_behind_the_profit(S, store, monkeypatch):
    good = {"rev": 500.0, "pat": 40.0, "ebitda": 60.0, "pbt": 52.0, "oi": 2.0}
    _turn(store, "TURN", good, AGO)
    _turn(store, "ONEOFF", {**good, "exc": 30.0}, AGO)        # a 58% one-off gain in PBT
    _turn(store, "TREASURY", {**good, "oi": 20.0}, AGO)       # other income 38% of PBT
    _turn(store, "SHRINK", {**good, "rev": 450.0}, AGO)       # on lower revenue
    _turn(store, "STILLLOSS", {**good, "pat": -1.0, "pbt": -1.0}, AGO)
    # The stored EBITDA rose (25 against 20), but only because a 10 crore gain
    # sits inside it: the business's own fell to 15.
    _turn(store, "COREFLAT", {**good, "ebitda": 25.0, "exc": 10.0}, AGO)
    # Positive stored EBITDA, made by the one-off; without it, a loss.
    _turn(store, "CORENEG", {**good, "ebitda": 8.0, "exc": 12.0}, {**AGO, "ebitda": -10.0})
    # A profit after tax on a loss before tax: a tax credit, not a turnaround.
    _turn(store, "TAXED", {**good, "pat": 3.0, "pbt": -5.0}, AGO)
    # A lender: its EBITDA fell and other income is 58% of PBT; neither
    # figure describes a lender's business, so neither is held against it.
    _turn(store, "LENDER", {**good, "ebitda": 5.0, "oi": 30.0}, {**AGO, "ebitda": 50.0}, bank=True)
    _lenders(S, monkeypatch, "LENDER")
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert sorted(_names(S, res, "turnarounds")) == ["LENDER", "TURN"]
    figs = _figs(_match(res, "turnarounds", "TURN"))
    assert figs["PAT, Q1 FY27"] == (40.0, "cr")
    assert figs["PAT, Q1 FY26"] == (-30.0, "cr"), "the year-ago loss is shown, not implied"
    assert figs["Revenue YoY"] == (4.17, "pct")
    assert figs["Net margin vs a year earlier"] == (14.25, "pts")
    assert figs["EBITDA excluding exceptional items, Q1 FY27"] == (60.0, "cr")
    assert not [l for l in _figs(_match(res, "turnarounds", "LENDER")) if "EBITDA" in l]


def test_turnarounds_are_ordered_on_the_margin_swing_not_rupees(S, store):
    # PAT swings of 20, 70 and 200 crore: by rupees BIGT would lead. As a
    # share of revenue SMALL moved most (+21 points) and BIGT least (+2).
    _turn(store, "SMALL", {"rev": 100.0, "pat": 10.0, "ebitda": 15.0, "pbt": 13.0},
          {"rev": 90.0, "pat": -10.0, "ebitda": 2.0, "pbt": -13.0})
    _turn(store, "TURN", {"rev": 500.0, "pat": 40.0, "ebitda": 60.0, "pbt": 52.0}, AGO)
    _turn(store, "BIGT", {"rev": 10000.0, "pat": 100.0, "ebitda": 900.0, "pbt": 130.0},
          {"rev": 9500.0, "pat": -100.0, "ebitda": 700.0, "pbt": -130.0})
    # A year-ago loss fifty times that quarter's revenue would lead on its own
    # (a swing of 5,050 points); a margin is ordered within ±100%, so a real
    # swing from a loss as large as revenue to a 60% margin leads it.
    _turn(store, "SHELL", {"rev": 30.0, "pat": 15.0, "ebitda": 22.0, "pbt": 19.0, "oi": 1.0},
          {"rev": 26.0, "pat": -1300.0, "ebitda": -1000.0, "pbt": -1300.0, "oi": 0.0})
    _turn(store, "REAL", {"rev": 100.0, "pat": 60.0, "ebitda": 75.0, "pbt": 78.0},
          {"rev": 50.0, "pat": -50.0, "ebitda": -40.0, "pbt": -50.0})
    # ₹2 crore of revenue in the quarter: under the screen's size floor, so a
    # few lakh of profit cannot open the list however far its margin swings.
    _turn(store, "TINY", {"rev": 2.0, "pat": 1.0, "ebitda": 1.5, "pbt": 1.3, "oi": 0.1},
          {"rev": 1.0, "pat": -50.0, "ebitda": -40.0, "pbt": -50.0, "oi": 0.0})
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert _names(S, res, "turnarounds") == ["REAL", "SHELL", "SMALL", "TURN", "BIGT"]
    shell = _figs(_match(res, "turnarounds", "SHELL"))
    assert shell["Net margin vs a year earlier"] == (5050.0, "pts"), "the figure shown is the real one"


# ── Cash-rich FCF compounders ──────────────────────────────────────────────

def test_compounders_rules(S, store, monkeypatch):
    _compounder(store, "FLOW")
    _compounder(store, "NETCASH", debt=800.0, cash=900.0, pbt=400.0, pat=300.0, cfo=350.0)
    _compounder(store, "LEVERED", debt=800.0, cash=100.0, pbt=400.0, pat=300.0, cfo=350.0)
    _compounder(store, "SLOW", cagr=5.0)
    _compounder(store, "LOWROCE", pbt=90.0, pat=70.0, cfo=100.0)        # ROCE 9%
    _compounder(store, "NOROCE", sheet_end="2025-09-30")                 # no year-end sheet
    _compounder(store, "FCFNEG", fcfs=(100.0, -10.0, 80.0))
    _compounder(store, "CFOLOW", cfo=140.0, fcfs=(40.0, 90.0, 80.0))     # cash 0.93x profit
    _compounder(store, "LENDERF")
    _lenders(S, monkeypatch, "LENDERF")
    # Two full years of cash flow are not three.
    _compounder(store, "TWOYEARS")
    store._connect().execute("DELETE FROM cash_flow WHERE symbol='TWOYEARS' AND period_end=?", (FY[2],))
    store._connect().commit()
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert sorted(_names(S, res, "fcf_compounders")) == ["FLOW", "NETCASH", "NOROCE"]
    flow = _match(res, "fcf_compounders", "FLOW")
    assert flow["as_of"] == "FY26"
    figs = _figs(flow)
    assert figs["Free cash flow, last 3 years"] == (270.0, "cr")
    assert figs["Operating cash flow ÷ PAT, FY26"] == (1.33, "x")
    assert figs["Debt ÷ equity"] == (0.1, "x")
    assert figs["ROCE"] == (19.09, "pct")
    assert figs["Revenue CAGR, 3 years"] == (10.0, "pct")
    assert "FCF yield" not in figs, "no price is held, so no yield is shown"
    assert _figs(_match(res, "fcf_compounders", "NETCASH"))["Net cash"] == (100.0, "cr")
    # Return on capital is tested where it can be worked out, and shown as
    # unknown, never as 0, where it cannot.
    assert _figs(_match(res, "fcf_compounders", "NOROCE"))["ROCE"] == (None, "pct")


def test_compounders_never_list_a_lender_known_by_its_filing(S, store):
    _compounder(store, "BANKF", quarter=False)
    _put(store, [_quarter(store, "BANKF", QS[0], 330.0, 40.0, eps=4.0, bank=True)])
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert res["fcf_compounders"] == []


def test_compounders_are_ordered_on_fcf_yield_then_return_on_capital(S, store):
    _compounder(store, "YA")                                  # 100 crore FCF on a 2,000 crore value
    _compounder(store, "YB")                                  # ...on a 5,000 crore value
    store.record_yf_profile("YB", {"sector": "Industrials", "industry": "Machinery",
                                   "sharesOutstanding": 1e8, "currentPrice": 500.0,
                                   "currency": "INR"})
    _compounder(store, "YC", pbt=430.0, pat=300.0, cfo=350.0)    # ROCE 40%, no price
    _compounder(store, "YD")                                     # ROCE 19%, no price
    _compounder(store, "YE", sheet_end="2025-09-30")             # no ROCE, no price
    # A price quoted in another currency is not a rupee price.
    store.record_yf_profile("YD", {"sector": "Industrials", "industry": "Machinery",
                                   "sharesOutstanding": 1e8, "currentPrice": 6.0,
                                   "currency": "USD"})
    res = S.evaluate(store._connect(), today=TODAY, market={"YA": {"price": 200.0}})
    assert _names(S, res, "fcf_compounders") == ["YA", "YB", "YC", "YD", "YE"]
    assert _figs(_match(res, "fcf_compounders", "YA"))["FCF yield"] == (5.0, "pct")
    assert _figs(_match(res, "fcf_compounders", "YB"))["FCF yield"] == (2.0, "pct")


# ── The old ids, the index and the detail ──────────────────────────────────

def test_the_old_ids_answer_with_the_screens_that_took_them_over(S, store):
    _series(store, "GROW", [1250.0] * 4 + [1000.0] * 4)
    _compounder(store, "FLOW")
    assert S.resolve("margin_expanders")["id"] == "steady_growers"
    assert S.resolve(" NET_CASH ")["id"] == "fcf_compounders"
    assert S._BY_ID["net_cash"] is S._BY_ID["fcf_compounders"]
    assert S.resolve("nope") is None and S.detail("nope", today=TODAY) is None
    idx = S.index(today=TODAY)
    assert [s["id"] for s in idx["screens"]] == ["steady_growers", "turnarounds", "fcf_compounders"]
    assert [s["name"] for s in idx["screens"]] == [
        "Fast growers with expanding margins", "Operational turnarounds", "Cash-rich FCF compounders"]
    assert {s["id"]: s["count"] for s in idx["screens"]} == {
        "steady_growers": 1, "turnarounds": 0, "fcf_compounders": 1}
    assert all(s["description"] and s["rule"] and s["order"] for s in idx["screens"])
    for old, new in S.ALIASES.items():
        d, canon = S.detail(old, today=TODAY), S.detail(new, today=TODAY)
        assert d["screen"]["id"] == new
        assert d["matches"] == canon["matches"] and d["count"] == canon["count"] == 1
        assert "sort" not in d["matches"][0]
    assert idx["notice"].endswith("it is not a recommendation.")


def test_the_old_addresses_still_answer_through_the_api(S, monkeypatch):
    """/fundamentals/screens/margin_expanders and /net_cash, saved before the
    five screens became three, open the screens that took them over; an
    unknown id is still a 404. The routes are plain functions, called
    directly, as the rest of the suite calls them."""
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main, "fundamentals_screens", S)
    assert [s["id"] for s in main.fundamentals_screens_index()["screens"]] == [
        "steady_growers", "turnarounds", "fcf_compounders"]
    for old, new in S.ALIASES.items():
        out = main.fundamentals_screen(old)
        assert out["available"] and out["screen"]["id"] == new and out["matches"] == []
    with pytest.raises(HTTPException) as e:
        main.fundamentals_screen("five_screens_ago")
    assert e.value.status_code == 404


def test_the_screens_say_nothing_a_reader_could_take_as_advice(S):
    import re
    banned = re.compile(r"\b(buy|sell|target|recommend|should|opportunity|top picks|best stocks)\b", re.I)
    for s in S.SCREENS:
        for k in ("name", "description", "rule", "order"):
            assert not banned.search(s[k]), (s["id"], k, s[k])
    # The numbers in the wording are the ones tested.
    rule = S._BY_ID["steady_growers"]["rule"]
    assert "more than 20%" in rule and "at least 15%" in rule and "2.5 points" in rule
    assert "₹2 crore" in rule and "at least 8%" in rule and "1.5 points" in rule
    assert "30%" in S._BY_ID["turnarounds"]["rule"] and "25%" in S._BY_ID["turnarounds"]["rule"]
    rule = S._BY_ID["fcf_compounders"]["rule"]
    assert "0.3× equity" in rule and "at least 8%" in rule and "at least 15%" in rule


# ── Missing figures ────────────────────────────────────────────────────────

def test_an_empty_store_answers_with_empty_screens(S, store):
    idx = S.index(today=TODAY)
    assert idx["available"] and idx["companies_held"] == 0
    assert [s["count"] for s in idx["screens"]] == [0, 0, 0]
    assert S.detail("turnarounds", today=TODAY)["matches"] == []


def test_missing_figures_never_raise_and_never_count_as_zero(S, store, monkeypatch):
    _series(store, "GROW", [1250.0] * 4 + [1000.0] * 4)
    # A company with one quarter, no year-ago and no trailing year; one whose
    # quarter has no revenue or profit at all; one with only a balance sheet;
    # one with only a year; one whose filing breaks the reader outright.
    _put(store, [_quarter(store, "ONEQ", QS[0], 500.0, 40.0)])
    bare = _quarter(store, "BARE", QS[0], 1.0, 1.0)
    bare.update(revenue_cr=None, pat_cr=None, ebitda_cr=None, opm_pct=None, pbt_cr=None)
    store.upsert("income", [bare])
    store.upsert("balance", [_sheet(store, "SHEETONLY", FY[0], 100.0, 0.0, 10.0)])
    store.upsert("income", [_year(store, "YEARONLY", FY[0], 100.0, 10.0)])
    _series(store, "BOOM", [1250.0] * 4 + [1000.0] * 4)
    import fund_snapshot

    real = fund_snapshot.build

    def build(quarters=(), *a, **k):
        if any(r.get("symbol") == "BOOM" for r in quarters):
            raise ValueError("a filing nobody can read")
        return real(quarters, *a, **k)

    monkeypatch.setattr(S.FS, "build", build)
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert _names(S, res, "steady_growers") == ["GROW"]
    assert res["turnarounds"] == [] and res["fcf_compounders"] == []
    # GROW's PAT growth is 0% and is shown as 0; ONEQ's would be unknown.
    assert _figs(_match(res, "steady_growers", "GROW"))["PAT YoY, Q1 FY27"] == (0.0, "pct")


def test_a_stale_quarter_lists_a_company_on_no_quarterly_screen(S, store):
    # A grower and a turnaround, a year ago: nothing filed since.
    ends = ["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30",
            "2024-06-30", "2024-03-31", "2023-12-31", "2023-09-30"]
    _put(store, [_quarter(store, "OLD", e, r, p) for e, r, p in
                 zip(ends, [1250.0] * 4 + [1000.0] * 4, [40.0] * 4 + [-30.0] * 4)])
    res = S.evaluate(store._connect(), today=TODAY, market={})
    assert res["steady_growers"] == [] and res["turnarounds"] == []
    # The same company asked about on the day its quarter was current.
    res = S.evaluate(store._connect(), today=dt.date(2025, 9, 25), market={})
    assert _names(S, res, "steady_growers") == ["OLD"] and _names(S, res, "turnarounds") == ["OLD"]


# ── How the tables are read ────────────────────────────────────────────────

class _Recorder:
    def __init__(self, conn):
        self.conn, self.calls = conn, []

    def execute(self, sql, args=()):
        self.calls.append((" ".join(sql.split()), list(args)))
        return self.conn.execute(sql, args)


def test_the_tables_are_read_in_chunks_with_only_what_is_needed(S, store):
    syms = ["C%03d" % i for i in range(2 * S.CHUNK + 100)]
    store.upsert("income", [_quarter(store, s, QS[0], 100.0, 10.0) for s in syms])
    rec = _Recorder(store._connect())
    S.evaluate(rec, today=TODAY, market={})
    reads = [(sql, args) for sql, args in rec.calls if "symbol IN (" in sql]
    # Five reads a chunk (quarters, years, cash flow, balance sheets, Yahoo
    # profiles), three chunks, none of more than CHUNK companies.
    assert len(reads) == 5 * 3
    for sql, args in reads:
        assert sql.count("?") - (1 if "period_end >= ?" in sql else 0) <= S.CHUNK
        assert not sql.startswith("SELECT *")
    statements = [sql for sql, _ in reads if "yf_profile" not in sql]
    assert all("period_end >= ?" in sql for sql in statements)
    # Every other read is one column across the table, never a row of figures.
    others = [sql for sql, _ in rec.calls if "symbol IN (" not in sql]
    assert others and all(sql.startswith("SELECT DISTINCT symbol FROM") for sql in others)
    # The windows: three years of quarters, five of years.
    q = next(args for sql, args in reads if "freq = 'quarterly'" in sql)
    assert q[-1] == (TODAY - dt.timedelta(days=S.QUARTERS_BACK_DAYS)).isoformat()
    a = next(args for sql, args in reads if "freq = 'annual'" in sql)
    assert a[-1] == (TODAY - dt.timedelta(days=S.ANNUALS_BACK_DAYS)).isoformat()


# ── The figures the screens added to fund_snapshot ─────────────────────────

def _snap_rows(revs, yoys, ends=QS, **kw):
    return [{"basis": "consolidated", "period_end": e, "label": e, "revenue_cr": r,
             "revenue_yoy_pct": y, "pat_cr": 10.0, **kw} for e, r, y in zip(ends, revs, yoys)]


def test_snapshot_revenue_growth_in_each_of_the_last_four_quarters():
    import fund_snapshot as FS
    rows = _snap_rows([125.0, 120.0, 118.0, 115.0, 100.0], [25.0, 22.0, None, 30.0, 4.0])
    snap = FS.build(rows, asof=TODAY)
    assert snap["revenue_yoy_4q"] == [25.0, 22.0, None, 30.0]
    # A quarter missing from the four: no run is claimed across the gap.
    gap = [r for r in rows if r["period_end"] != QS[2]]
    assert FS.build(gap, asof=TODAY)["revenue_yoy_4q"] is None
    assert FS.build(rows[:3], asof=TODAY)["revenue_yoy_4q"] is None


def test_snapshot_year_ago_revenue_and_ebitda_without_exceptional_items():
    import fund_snapshot as FS
    rows = _snap_rows([125.0, 120.0, 118.0, 115.0, 100.0], [25.0] * 5)
    rows[0].update(ebitda_cr=30.0, exceptional_cr=8.0)
    rows[4].update(ebitda_cr=-4.0, exceptional_cr=1.0)
    snap = FS.build(rows, asof=TODAY)
    assert snap["core_ebitda_cr"] == 22.0
    assert snap["revenue_yoy_cr_prev"] == 100.0
    assert snap["core_ebitda_yoy_cr_prev"] == -5.0
    # No exceptional line filed: the stored EBITDA is all there is.
    rows[4].pop("exceptional_cr")
    assert FS.build(rows, asof=TODAY)["core_ebitda_yoy_cr_prev"] == -4.0
    # No year-ago quarter: unknown, not 0.
    snap = FS.build(rows[:4], asof=TODAY)
    assert snap["revenue_yoy_cr_prev"] is None and snap["core_ebitda_yoy_cr_prev"] is None
