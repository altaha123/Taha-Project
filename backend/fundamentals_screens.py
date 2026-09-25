"""
fundamentals_screens.py — questions asked of every company at once

WHAT THIS IS
The fundamentals crawl holds every NSE company's filed statements. A question
like "whose revenue has grown more than 20% in each of the last four
quarters?" used to mean one exchange request per company per quarter; against
the tables it is one read. This module answers a short list of such questions
over the whole market.

The lenses (lens_engine.py) do the same for named investing philosophies,
built on full financial years. These are narrower and faster moving: what
changed in the latest quarters.

WHAT A MATCH IS, AND IS NOT
A company appears when the filed figures meet the stated condition, and every
match carries the figures that met it. Nothing is ranked by quality, nothing
is a recommendation, and a company without enough recent history is left out
rather than guessed at — so "not listed" never means "failed".

FRESHNESS
A company's newest stored quarter must have ended within FRESH_DAYS, or the
question is answered about a period that has since been superseded. The
balance sheet and cash-flow screens use their own, longer windows because
those are filed twice a year and once a year.

NO EXTERNAL DEPENDENCIES. Standard library only.
"""

import datetime as dt
import threading
import time

try:
    import fundamentals_store as store
except Exception:                                   # pragma: no cover
    store = None

FRESH_DAYS = 92 + 62            # a quarter plus the 60 days the March one gets
BALANCE_FRESH_DAYS = 183 + 92   # a half-year plus its filing window
CASHFLOW_FRESH_DAYS = 365 + 150
CACHE_SECONDS = 3600

SCREENS = [
    {"id": "steady_growers",
     "name": "Four quarters of 20%+ revenue growth",
     "rule": "Revenue up more than 20% on the same quarter a year earlier, in "
             "each of the last four quarters."},
    {"id": "turnarounds",
     "name": "Back to profit",
     "rule": "A profit after tax in the latest quarter, against a loss in the "
             "same quarter a year earlier."},
    {"id": "margin_expanders",
     "name": "Operating margin up 3 points or more",
     "rule": "Operating margin at least 3 percentage points above the same "
             "quarter a year earlier, with revenue also higher."},
    {"id": "net_cash",
     "name": "More cash than debt, and profitable",
     "rule": "Cash and current investments above total borrowings on the latest "
             "balance sheet, and a profit after tax in the latest full year."},
    {"id": "fcf_compounders",
     "name": "Three years of free cash flow",
     "rule": "Free cash flow positive in each of the last three full years, "
             "and operating cash flow above profit after tax in the latest one."},
]
_BY_ID = {s["id"]: s for s in SCREENS}

NOTICE = ("Screens are filters applied to the companies' filed statements. A "
          "company listed meets the stated condition on the figures shown; it "
          "is not a recommendation.")

_cache = {"at": 0.0, "key": None, "result": None}
_lock = threading.Lock()


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _one_basis(recs):
    held = {r["basis"] for r in recs}
    b = "consolidated" if "consolidated" in held else "standalone"
    return [r for r in recs if r["basis"] == b]


def _year_before(recs, r):
    end = _d(r["period_end"])
    for c in recs:
        e = _d(c["period_end"])
        if end and e and 350 <= (end - e).days <= 380:
            return c
    return None


def _consecutive(recs, n):
    """The newest n quarters, if they are n quarters in a row."""
    out = recs[:n]
    if len(out) < n:
        return None
    for a, b in zip(out, out[1:]):
        da, db = _d(a["period_end"]), _d(b["period_end"])
        if not da or not db or not 80 <= (da - db).days <= 100:
            return None
    return out


def _grouped(conn, sql):
    by = {}
    for r in conn.execute(sql):
        by.setdefault(r["symbol"], []).append(dict(r))
    return {s: _one_basis(v) for s, v in by.items()}


def evaluate(conn, today=None):
    """Every screen over the whole store: {screen_id: [match, ...]}."""
    today = today or dt.date.today()
    q_cut = (today - dt.timedelta(days=FRESH_DAYS)).isoformat()
    b_cut = (today - dt.timedelta(days=BALANCE_FRESH_DAYS)).isoformat()
    c_cut = (today - dt.timedelta(days=CASHFLOW_FRESH_DAYS)).isoformat()
    out = {s["id"]: [] for s in SCREENS}

    quarters = _grouped(conn, (
        "SELECT symbol, company, basis, period_end, label, revenue_cr, pat_cr,"
        " opm_pct, revenue_yoy_pct, pat_yoy_pct FROM income_statement"
        " WHERE freq='quarterly' ORDER BY symbol, period_end DESC"))
    years = _grouped(conn, (
        "SELECT symbol, company, basis, period_end, label, revenue_cr, pat_cr"
        " FROM income_statement WHERE freq='annual' ORDER BY symbol, period_end DESC"))
    sheets = _grouped(conn, (
        "SELECT symbol, company, basis, period_end, label, total_borrowings_cr,"
        " cash_and_equivalents_cr, current_investments_cr, net_debt_cr"
        " FROM balance_sheet ORDER BY symbol, period_end DESC"))
    flows = _grouped(conn, (
        "SELECT symbol, company, basis, period_end, label, cfo_cr, capex_cr, fcf_cr"
        " FROM cash_flow WHERE months=12 ORDER BY symbol, period_end DESC"))

    for sym, recs in quarters.items():
        top = recs[0]
        if str(top["period_end"]) < q_cut:
            continue
        base = {"symbol": sym, "company": top.get("company"), "as_of": top["label"]}

        run = _consecutive(recs, 4)
        if run and all(r["revenue_yoy_pct"] is not None and r["revenue_yoy_pct"] > 20
                       for r in run):
            out["steady_growers"].append({**base, "sort": min(r["revenue_yoy_pct"] for r in run),
                "figures": [{"label": "Revenue YoY, " + r["label"],
                             "value": r["revenue_yoy_pct"], "unit": "pct"} for r in run]})

        prior = _year_before(recs, top)
        if prior is None:
            continue
        if (top["pat_cr"] is not None and prior["pat_cr"] is not None
                and top["pat_cr"] > 0 and prior["pat_cr"] < 0):
            out["turnarounds"].append({**base, "sort": top["pat_cr"] - prior["pat_cr"],
                "figures": [{"label": "PAT, " + top["label"], "value": top["pat_cr"], "unit": "cr"},
                            {"label": "PAT, " + prior["label"], "value": prior["pat_cr"], "unit": "cr"}]})
        if (top["opm_pct"] is not None and prior["opm_pct"] is not None
                and top["opm_pct"] - prior["opm_pct"] >= 3
                and top["revenue_cr"] is not None and prior["revenue_cr"] is not None
                and top["revenue_cr"] > prior["revenue_cr"] > 0):
            out["margin_expanders"].append({**base, "sort": top["opm_pct"] - prior["opm_pct"],
                "figures": [{"label": "Operating margin, " + top["label"], "value": top["opm_pct"], "unit": "pct"},
                            {"label": "Operating margin, " + prior["label"], "value": prior["opm_pct"], "unit": "pct"},
                            {"label": "Revenue YoY", "value": top["revenue_yoy_pct"], "unit": "pct"}]})

    for sym, recs in sheets.items():
        b = recs[0]
        yrs = years.get(sym) or []
        if str(b["period_end"]) < b_cut or not yrs or str(yrs[0]["period_end"]) < c_cut:
            continue
        if b["basis"] != yrs[0]["basis"]:
            continue
        debt, cash = b["total_borrowings_cr"], b["cash_and_equivalents_cr"]
        if debt is None or cash is None or yrs[0]["pat_cr"] is None:
            continue
        liquid = cash + (b["current_investments_cr"] or 0)
        if liquid > debt and yrs[0]["pat_cr"] > 0:
            out["net_cash"].append({"symbol": sym, "company": b.get("company"),
                "as_of": b["label"], "sort": liquid - debt,
                "figures": [{"label": "Cash and current investments", "value": round(liquid, 2), "unit": "cr"},
                            {"label": "Total borrowings", "value": debt, "unit": "cr"},
                            {"label": "PAT, " + yrs[0]["label"], "value": yrs[0]["pat_cr"], "unit": "cr"}]})

    for sym, recs in flows.items():
        if str(recs[0]["period_end"]) < c_cut or len(recs) < 3:
            continue
        run = recs[:3]
        if any(_d(a["period_end"]) is None or _d(b["period_end"]) is None
               or not 350 <= (_d(a["period_end"]) - _d(b["period_end"])).days <= 380
               for a, b in zip(run, run[1:])):
            continue
        if not all(r["fcf_cr"] is not None and r["fcf_cr"] > 0 for r in run):
            continue
        year = next((y for y in years.get(sym) or []
                     if y["period_end"] == run[0]["period_end"] and y["basis"] == run[0]["basis"]), None)
        if not year or year["pat_cr"] is None or run[0]["cfo_cr"] is None \
                or run[0]["cfo_cr"] <= year["pat_cr"]:
            continue
        out["fcf_compounders"].append({"symbol": sym, "company": run[0].get("company"),
            "as_of": run[0]["label"], "sort": min(r["fcf_cr"] for r in run),
            "figures": [{"label": "Free cash flow, " + r["label"], "value": r["fcf_cr"], "unit": "cr"}
                        for r in run] + [
                       {"label": "Operating cash flow ÷ PAT, " + run[0]["label"],
                        "value": round(run[0]["cfo_cr"] / year["pat_cr"], 2)
                        if year["pat_cr"] > 0 else None, "unit": "x"}]})

    for rows in out.values():
        rows.sort(key=lambda r: (-(r["sort"] or 0), r["symbol"]))
    return out


def _run(today=None):
    """Every screen, cached for an hour and until the tables change."""
    conn = store._connect()
    key = conn.execute("SELECT MAX(updated_utc) FROM income_statement").fetchone()[0]
    with _lock:
        fresh = time.time() - _cache["at"] < CACHE_SECONDS
        if _cache["result"] is not None and fresh and _cache["key"] == key and today is None:
            return _cache["result"]
    res = evaluate(conn, today)
    held = conn.execute("SELECT COUNT(DISTINCT symbol) FROM income_statement").fetchone()[0]
    result = {"results": res, "companies_held": held,
              "computed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if today is None:
        with _lock:
            _cache.update(at=time.time(), key=key, result=result)
    return result


def index(today=None):
    """Every screen with how many companies meet it."""
    if store is None:
        return {"available": False, "message": "The fundamentals tables are not available."}
    r = _run(today)
    return {"available": True, "companies_held": r["companies_held"],
            "computed_utc": r["computed_utc"], "notice": NOTICE,
            "screens": [{**s, "count": len(r["results"][s["id"]])} for s in SCREENS]}


def detail(screen_id, limit=200, today=None):
    """One screen: its rule and every company that meets it, with the figures."""
    if store is None:
        return {"available": False, "message": "The fundamentals tables are not available."}
    s = _BY_ID.get(screen_id)
    if s is None:
        return None
    r = _run(today)
    rows = r["results"][screen_id]
    cap = max(1, min(int(limit or 200), 2000))
    return {"available": True, "screen": s, "count": len(rows),
            "companies_held": r["companies_held"], "computed_utc": r["computed_utc"],
            "notice": NOTICE,
            "matches": [{k: v for k, v in m.items() if k != "sort"} for m in rows[:cap]]}
