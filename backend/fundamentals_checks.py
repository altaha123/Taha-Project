"""
fundamentals_checks.py — is what the three tables say actually right?

Nobody can compare two thousand companies against their annual reports by
hand, and nobody needs to: accounts are full of identities. Four quarters add
up to the year; assets equal equity plus liabilities; profit before tax, less
tax, plus a group's share of its associates and any discontinued business, is
the profit after tax; the owners' share plus the minority's is the whole. A
number read from the wrong context, the wrong line or in the wrong unit breaks
one of these, and the break says where to look. Only what fails needs a person.

WHAT A FAILURE MEANS
Not always our error. Measured on the first full sweep, most failures are the
COMPANY's: Aarti Industries' Q4 FY21 filing states a PAT of ₹692 cr whose
owners' and minority shares add to ₹139 cr — the ₹139 cr is right, the year
proves it — and Caplin Point's Q1 FY21 filing is a hundred times too small,
which its own EPS gives away. The checks do not correct anything. They say
which figure disagrees with what, and by how much, and the row carries the
filing link so a person can see which side is wrong.

WHAT IS CHECKED
  quarters_sum_revenue / quarters_sum_pat   four quarters vs the year
  balance_sheet_balances                    assets = equity + liabilities
  pat_reconciles                            pbt - tax + associates + discontinued
                                            + regulatory deferral = pat
  pat_split                                 owners + minority = pat
  total_income                              revenue + other income = total income
  cash_flow_sums                            cfo + cfi + cff + fx = change in cash
  unit_scale                                pat / eps (the implied share count)
                                            far from the company's own median
  yahoo_revenue / yahoo_pat / yahoo_assets  the year against Yahoo Finance

Results go to `data_checks` (the failures) and `check_runs` (what was tested
and the pass rate for each check), both in the fundamentals database.
"""

import datetime as dt
import json
import statistics

import fundamentals_store as store

TOLERANCE = 0.01          # 1% for identities the filing should satisfy exactly
ABS_TOLERANCE = 0.05      # ₹5 lakh: filings round to the lakh, stored figures to 0.01 cr
MAJOR = 0.05              # past 5% a gap is a misread or a misfiled number, not rounding
YAHOO_TOLERANCE = 0.05    # a second source that reclassifies: 5%, and only a warning
UNIT_FACTOR = 20          # an implied share count 20x off its median is a unit error
FLOOR_CR = 1.0            # below ₹1 cr, rounding in the filing dominates

# An IDENTITY must hold in a company's own filing, so a failure is an error —
# ours or the company's. A CROSS-CHECK against Yahoo is a second opinion:
# Yahoo reclassifies (a bank's revenue is net of interest, an oil marketer's
# net of excise) and reports some companies in dollars, so a disagreement is
# a warning to look, never a verdict.
CROSS_CHECKS = {"yahoo_revenue", "yahoo_pat", "yahoo_assets"}

CHECKS = {
    "quarters_sum_revenue": "Four quarters' revenue adds up to the year's",
    "quarters_sum_pat": "Four quarters' profit after tax adds up to the year's",
    "balance_sheet_balances": "Total assets equal equity plus liabilities",
    "pat_reconciles": ("Profit before tax, less tax, plus share of associates, "
                       "discontinued operations and regulatory deferral, is PAT"),
    "pat_split": "Owners' share plus minority share is PAT",
    "total_income": "Revenue plus other income is total income",
    "cash_flow_sums": "Operating + investing + financing + FX effect is the change in cash",
    "unit_scale": "Profit per share implies a share count in line with the company's own",
    "yahoo_revenue": "Annual revenue agrees with Yahoo Finance",
    "yahoo_pat": "Annual profit to shareholders agrees with Yahoo Finance",
    "yahoo_assets": "Total assets agree with Yahoo Finance",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS data_checks (
  symbol      TEXT NOT NULL,
  severity    TEXT NOT NULL,              -- major (>5%) | minor | warning (Yahoo)
  basis       TEXT NOT NULL,
  freq        TEXT NOT NULL,              -- quarterly | annual | half-year | balance
  period_end  TEXT NOT NULL,
  label       TEXT,
  check_id    TEXT NOT NULL,
  expected    REAL,                       -- what the identity says it should be
  actual      REAL,                       -- what the table holds
  gap_pct     REAL,
  note        TEXT,
  source_url  TEXT,
  run_utc     TEXT NOT NULL,
  PRIMARY KEY (symbol, basis, freq, period_end, check_id)
);
CREATE INDEX IF NOT EXISTS idx_checks_check ON data_checks (check_id, gap_pct);
CREATE INDEX IF NOT EXISTS idx_checks_symbol ON data_checks (symbol);
CREATE TABLE IF NOT EXISTS check_runs (
  run_utc   TEXT PRIMARY KEY,
  summary   TEXT NOT NULL
);
"""


def _gap(expected, actual, floor=FLOOR_CR):
    """Relative gap, against the larger magnitude and never below `floor`."""
    if expected is None or actual is None:
        return None
    return abs(expected - actual) / max(abs(expected), abs(actual), floor)


def _z(v):
    return v or 0.0


_SCALES = (10, 100, 1000, 100000)


def _near(a, b, tol=0.02):
    return b and abs(a - b) <= tol * abs(b)


def _diagnose(qv, annual, labels):
    """
    Why four quarters and a year disagree, where the numbers say so.

    The commonest cause on the first sweep was a company filing its March
    results — the fourth quarter AND the year, which share one document — in
    the wrong unit: Trent's FY22 filing is a hundred times too small, Marksans'
    FY25 ten. Then the year times the factor equals the first three quarters
    plus the fourth times the factor. Next, one quarter alone misfiled.
    Otherwise it is most often a restatement: a merger or a discontinued
    business, where the year is restated and the quarters are not.
    """
    first3, q4 = sum(qv[:3]), qv[3]
    for k in _SCALES:
        for f, word in ((k, "small"), (1.0 / k, "large")):
            if annual and _near(annual * f, first3 + q4 * f):
                return ("the %s filing (fourth quarter and year together) looks %sx too %s"
                        % (labels[3], k, word))
            if annual and _near(annual * f, sum(qv)):
                return "the year's figure looks %sx too %s" % (k, word)
        for i, v in enumerate(qv):
            for f, word in ((k, "small"), (1.0 / k, "large")):
                if v and _near(sum(qv) - v + v * f, annual):
                    return "%s looks %sx too %s" % (labels[i], k, word)
    if annual and q4 is not None and abs((annual - first3) - q4) > 0.05 * abs(annual):
        # Checked by hand on Aarey Drugs, Mirza International and Gujarat
        # Energy: the documents were read correctly and are inconsistent with
        # themselves or with the company's earlier filings.
        return ("the year less the first three quarters is %.2f, but the fourth quarter "
                "was filed as %.2f: a restatement at year end (a merger, a discontinued "
                "business, a reclassification) or an error in the company's filing — "
                "the annual report says which" % (annual - first3, q4))
    return None


class _Tally:
    def __init__(self):
        self.tested, self.failed, self.rows = {}, {}, []

    def test(self, check_id, row, expected, actual, tol=TOLERANCE, freq=None,
             note=None, floor=FLOOR_CR):
        g = _gap(expected, actual, floor)
        if g is None:
            return
        self.tested[check_id] = self.tested.get(check_id, 0) + 1
        if g <= tol or abs(expected - actual) <= ABS_TOLERANCE:
            return
        severity = ("warning" if check_id in CROSS_CHECKS
                    else "major" if g > MAJOR else "minor")
        self.add(severity, check_id, row, freq or row.get("freq") or "",
                 expected, actual, 100 * g, note)

    def add(self, severity, check_id, row, freq, expected, actual, gap_pct, note):
        key = (check_id, severity)
        self.failed[key] = self.failed.get(key, 0) + 1
        self.rows.append((row["symbol"], severity, row["basis"], freq,
                          row["period_end"], row.get("label"), check_id,
                          round(expected, 4), round(actual, 4), round(gap_pct, 2),
                          note, row.get("source_url")))


def _yahoo(conn):
    """{(symbol, period_end): {item: value in crore}} for the three items used."""
    names = ("Total Revenue", "Net Income Common Stockholders", "Net Income", "Total Assets")
    out = {}
    for r in conn.execute(
            "SELECT symbol, period_end, item, value FROM yf_statements_v "
            "WHERE freq='annual' AND item IN (%s)" % ",".join("?" * len(names)), names):
        out.setdefault((r["symbol"], r["period_end"]), {})[r["item"]] = r["value"] / store.CRORE
    return out


def run():
    """Every check over every row; replaces the previous run's failures."""
    conn = store._connect()
    conn.executescript(SCHEMA)
    t = _Tally()
    inc = [dict(r) for r in conn.execute("SELECT * FROM income_statement")]

    quarters = {}
    for r in inc:
        if r["freq"] == "quarterly":
            quarters.setdefault((r["symbol"], r["basis"]), []).append(r)

    for r in inc:
        # PAT from its parts. Only where the filing gave the parts at all:
        # rows read before the parser knew them hold None, not zero.
        if r["pbt_cr"] is not None and r["tax_cr"] is not None and r["pat_cr"] is not None \
                and r.get("pat_continuing_cr") is not None:
            t.test("pat_reconciles", r,
                   r["pbt_cr"] - r["tax_cr"] + _z(r.get("share_of_associates_cr"))
                   + _z(r.get("discontinued_pat_cr")) + _z(r.get("regulatory_deferral_cr")),
                   r["pat_cr"])
        if r.get("pat_owners_cr") is not None and r.get("pat_minority_cr") is not None \
                and r["pat_cr"] is not None:
            t.test("pat_split", r, r["pat_owners_cr"] + r["pat_minority_cr"], r["pat_cr"])
        if r["total_income_cr"] is not None and r["revenue_cr"] is not None:
            t.test("total_income", r, r["revenue_cr"] + _z(r["other_income_cr"]),
                   r["total_income_cr"])

        if r["freq"] != "annual" or not r["period_from"]:
            continue
        q = [x for x in quarters.get((r["symbol"], r["basis"]), [])
             if r["period_from"] <= x["period_end"] <= r["period_end"]]
        if len(q) != 4:
            continue
        q.sort(key=lambda x: x["period_end"])
        for col, cid in (("revenue_cr", "quarters_sum_revenue"), ("pat_cr", "quarters_sum_pat")):
            if r[col] is not None and all(x[col] is not None for x in q):
                t.test(cid, r, sum(x[col] for x in q), r[col],
                       note=_diagnose([x[col] for x in q], r[col], [x["label"] for x in q]))

    # The implied share count, PAT / EPS, is stable for a company except when
    # it issues or splits — and then by a known factor, not by a hundred. A
    # quarter far from the company's own median was filed in the wrong unit.
    for (sym, basis), rows in quarters.items():
        implied = [(r, (r["pat_owners_cr"] if r.get("pat_owners_cr") is not None else r["pat_cr"])
                    / r["eps_basic"])
                   for r in rows if r["eps_basic"] and abs(r["eps_basic"]) > 0.05
                   # Not FLOOR_CR: a quarter filed a hundred times too small
                   # is exactly the one that falls under it.
                   and (r["pat_cr"] or 0) and abs(r["pat_cr"]) >= 0.01]
        implied = [(r, v) for r, v in implied if v > 0]
        if len(implied) < 4:
            continue
        med = statistics.median(v for _r, v in implied)
        revs = [r["revenue_cr"] for r in rows if r["revenue_cr"] and r["revenue_cr"] > 0]
        rev_med = statistics.median(revs) if len(revs) >= 4 else None
        for r, v in implied:
            ratio = v / med
            t.tested["unit_scale"] = t.tested.get("unit_scale", 0) + 1
            # Which half of the ratio is wrong? If revenue is off the company's
            # own run-rate the same way, the money was filed in the wrong unit
            # — and then even 5x is enough, because a split or a bonus moves
            # the share count but never the revenue. Past 20x with revenue in
            # line, it is the EPS.
            rr = (r["revenue_cr"] / rev_med) if rev_med and r["revenue_cr"] else None
            # Money in the wrong unit moves PAT and revenue the same way, so
            # the implied share count and the revenue run-rate move together.
            money = rr is not None and ((ratio > 5 and rr > 5) or (ratio < 0.2 and rr < 0.2))
            if not money and UNIT_FACTOR ** -1 <= ratio <= UNIT_FACTOR:
                continue
            factor = round(ratio if ratio > 1 else 1 / ratio)
            note = ("implied shares %.4g crore vs the company's usual %.4g, about %sx off. "
                    % (v, med, factor)) + (
                "Revenue is off its run-rate too (%.3gx), so the money figures in this "
                "filing are in the wrong unit." % rr if money else
                "Revenue is in line, so it is the EPS that was filed in the wrong unit.")
            t.add("major", "unit_scale", r, "quarterly", med, v, 100 * abs(ratio - 1), note)

    bs = [dict(r) for r in conn.execute("SELECT * FROM balance_sheet")]
    for r in bs:
        if r["total_assets_cr"] is not None and r["total_equity_and_liabilities_cr"] is not None:
            t.test("balance_sheet_balances", r, r["total_equity_and_liabilities_cr"],
                   r["total_assets_cr"], freq="balance")
        elif r["total_assets_cr"] is not None and r["total_equity_cr"] is not None \
                and r["total_liabilities_cr"] is not None:
            t.test("balance_sheet_balances", r, r["total_equity_cr"] + r["total_liabilities_cr"],
                   r["total_assets_cr"], freq="balance")

    for r in conn.execute("SELECT * FROM cash_flow"):
        r = dict(r)
        if None in (r["cfo_cr"], r["cfi_cr"], r["cff_cr"], r["net_change_in_cash_cr"]):
            continue
        # Against the largest of the three flows, not the change: the change is
        # often a small difference of large numbers.
        size = max(abs(r["cfo_cr"]), abs(r["cfi_cr"]), abs(r["cff_cr"]), FLOOR_CR)
        expected = r["cfo_cr"] + r["cfi_cr"] + r["cff_cr"] + _z(r.get("fx_effect_on_cash_cr"))
        t.test("cash_flow_sums", r, expected, r["net_change_in_cash_cr"],
               freq="annual" if r["months"] == 12 else "half-year", floor=size)

    # Yahoo, as a second source. Consolidated rows only — Yahoo reports the group.
    try:
        yf = _yahoo(conn)
    except Exception:
        yf = {}
    in_dollars = set()
    for r in inc:
        if r["freq"] != "annual" or r["basis"] != "consolidated":
            continue
        y = yf.get((r["symbol"], r["period_end"]))
        if not y:
            continue
        # Yahoo reports Infosys, Wipro and a few others in US dollars. Ours
        # over theirs then sits at the exchange rate; that is a currency, not
        # a disagreement, and there is nothing to compare.
        if r["revenue_cr"] and y.get("Total Revenue") and \
                60 <= r["revenue_cr"] / y["Total Revenue"] <= 110:
            in_dollars.add(r["symbol"])
            continue
        is_bank = r.get("operating_profit_pre_provision_cr") is not None
        if r["revenue_cr"] and y.get("Total Revenue") and not is_bank:
            t.test("yahoo_revenue", r, y["Total Revenue"], r["revenue_cr"], tol=YAHOO_TOLERANCE)
        ours = r.get("pat_owners_cr") if r.get("pat_owners_cr") is not None else r["pat_cr"]
        theirs = y.get("Net Income Common Stockholders", y.get("Net Income"))
        if ours is not None and theirs is not None:
            t.test("yahoo_pat", r, theirs, ours, tol=YAHOO_TOLERANCE)
    for r in bs:
        if r["basis"] != "consolidated" or r["period_end"][5:7] != "03":
            continue
        y = yf.get((r["symbol"], r["period_end"]))
        if r["symbol"] in in_dollars:
            continue
        if y and y.get("Total Assets") and r["total_assets_cr"]:
            t.test("yahoo_assets", r, y["Total Assets"], r["total_assets_cr"],
                   freq="balance", tol=YAHOO_TOLERANCE)

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    def count(cid, sev):
        return t.failed.get((cid, sev), 0)
    checks = []
    for cid, what in CHECKS.items():
        n = t.tested.get(cid, 0)
        flagged = sum(count(cid, s) for s in ("major", "minor", "warning"))
        checks.append({"id": cid, "what": what,
                       "kind": "cross_check" if cid in CROSS_CHECKS else "identity",
                       "tested": n, "major": count(cid, "major"),
                       "minor": count(cid, "minor"), "warnings": count(cid, "warning"),
                       "pass_pct": round(100 * (1 - flagged / n), 2) if n else None})
    identity_rows = [row for row in t.rows if row[1] != "warning"]
    summary = {
        "run_utc": now,
        "checks": checks,
        "identity_tests": sum(c["tested"] for c in checks if c["kind"] == "identity"),
        "identity_pass_pct": round(100 * (1 - len(identity_rows) / max(1, sum(
            c["tested"] for c in checks if c["kind"] == "identity"))), 2),
        "companies_with_major": len({row[0] for row in t.rows if row[1] == "major"}),
        "companies_flagged": len({row[0] for row in identity_rows}),
        "yahoo_in_dollars": sorted(in_dollars),
        "failures": len(t.rows),
    }
    with store._tx() as c:
        c.execute("DELETE FROM data_checks")
        c.executemany("INSERT OR REPLACE INTO data_checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      [row + (now,) for row in t.rows])
        c.execute("INSERT OR REPLACE INTO check_runs VALUES (?,?)", (now, json.dumps(summary)))
    return summary


def latest_summary():
    conn = store._connect()
    conn.executescript(SCHEMA)
    r = conn.execute("SELECT summary FROM check_runs ORDER BY run_utc DESC LIMIT 1").fetchone()
    return json.loads(r["summary"]) if r else None


COLUMNS = ["symbol", "severity", "basis", "freq", "period_end", "label", "check_id", "expected",
           "actual", "gap_pct", "note", "source_url", "run_utc"]


def failures(symbol=None, check_id=None, severity=None, limit=200):
    """The failures, largest gap first."""
    conn = store._connect()
    conn.executescript(SCHEMA)
    sql, args, where = "SELECT %s FROM data_checks" % ", ".join(COLUMNS), [], []
    if severity:
        where.append("severity=?")
        args.append(severity)
    if symbol:
        where.append("symbol=?")
        args.append(symbol.strip().upper())
    if check_id:
        where.append("check_id=?")
        args.append(check_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY gap_pct DESC"
    if limit:
        sql += " LIMIT %d" % max(1, int(limit))
    return [dict(r) for r in conn.execute(sql, args)]
