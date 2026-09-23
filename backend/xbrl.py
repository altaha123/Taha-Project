"""
Altaha Screener — XBRL financial results, straight from the exchange

WHY
Fundamentals here come from yfinance, which is an unofficial scrape of Yahoo
and thin for small and mid-cap Indian names — the README already admits the
engine falls back to technical-only scoring when it cannot find them. That is
not a data availability problem. Every listed Indian company files its results
with the exchange in XBRL under LODR Regulation 33, quarterly, machine
readable and authoritative. Yahoo simply does not parse them well.

This module goes to the filing instead. It is also the answer to the question
any serious buyer asks first — where does your data come from — which "we
scrape a competitor" and "we scrape Yahoo" both fail.

WHAT IT CAN AND CANNOT GIVE YOU
A quarterly Reg 33 filing is an income statement. It carries revenue, every
expense line, tax, profit, EPS and the segment breakup — and it does NOT carry
the balance sheet or the cash flow statement. So this is a primary source for
what a company earned, and it cannot on its own compute the parts of the
Piotroski F-Score that need total assets, current ratio or operating cash
flow. Those still come from the existing provider, and the payload says which
number came from where rather than blurring the two.

THE TWO TRAPS
An XBRL document reports many periods at once, and getting this wrong is the
difference between a quarterly figure and a nine-month one:

  1. CONTEXTS. Reliance's Q3 filing carries RevenueFromOperations twice —
     ₹1,282bn against context OneD and ₹3,966bn against FourD. Both are true.
     One is the quarter and the other is the year to date. The reporting
     period is declared in the filing itself, so the context is matched
     against those dates rather than taken in document order.

  2. DIMENSIONS. Segment revenue, segment assets and the breakup of other
     expenses are tagged with the SAME element names as the totals, separated
     only by a dimension on their context. Reading those as company figures
     turns one segment's assets into the balance sheet. Dimensional contexts
     are excluded outright.

Filed XBRL never changes once published, so parsed results are cached on disk
indefinitely.
"""

import datetime as dt
import hashlib
import json
import os
import re
import threading
import xml.etree.ElementTree as ET

import nse_http

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
CACHE_DIR = os.path.join(DATA_DIR, "xbrl-cache")
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except Exception:
    CACHE_DIR = None

NSE_RESULTS = "https://www.nseindia.com/api/corporates-financial-results"
# SEBI's Integrated Filing regime replaced the standalone results filing from
# the quarter ending December 2024. Companies stopped filing under the old
# mechanism at exactly that point, which is why the legacy endpoint above
# looked "frozen at 31-Dec-2024" for every symbol in the universe: it was not
# broken, it was finished. Everything since is here.
NSE_INTEGRATED = "https://www.nseindia.com/api/integrated-filing-results"
NSE_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"


# ---------------------------------------------------------------------------
# Transport
#
# This module shipped talking to NSE through plain `requests`, and NSE's WAF
# answers a datacenter IP with 403 whatever headers it carries — it
# fingerprints the TLS handshake. Render is a datacenter IP. So in production
# every call here returned 403, `summary()` reported "no XBRL results filing
# found for this symbol", and the primary-source fundamentals path fell back
# to the provider without anything logging an error. It read as a coverage gap
# and was a transport failure.
#
# Measured from this project's host, identical URL, params and headers:
# requests 403, curl_cffi 200 with nineteen rows.
#
# nse_http carries the impersonating session, the cookie warm-up and the
# re-warm-once-on-401 that this had its own copy of.
# ---------------------------------------------------------------------------

def session():
    """Kept for callers and tests that reach for it; the pool is nse_http's."""
    return nse_http.session(NSE_REFERER)


def _warm_session(force=False):
    nse_http.warm(NSE_REFERER, force=force)


def available() -> bool:
    return nse_http.available()


# ---------------------------------------------------------------------------
# The filing index
# ---------------------------------------------------------------------------

def _api(url, params):
    """One authenticated NSE call. Returns the rows, or an empty list."""
    body = nse_http.get_json(url, params=params, referer=NSE_REFERER)
    return nse_http.rows(body) if body is not None else []


def _integrated_filings(sym):
    """
    Filings under SEBI's Integrated Filing regime — everything since the
    December 2024 quarter, and the only place recent results now appear.

    Two things must be filtered here. The feed carries a Governance filing
    alongside the Financials one for each quarter, and the governance document
    has no income statement in it; and it carries revisions, which are marked
    in `type` and are exactly what you want to keep, since a revised result
    supersedes the original.
    """
    out = []
    for row in _api(NSE_INTEGRATED, {"index": "equities", "symbol": sym,
                                     "period": "Quarterly"}):
        kind = str(row.get("type") or "")
        if "financ" not in kind.lower():
            continue                      # governance filings carry no numbers
        url = (row.get("xbrl") or "").strip()
        if not url.lower().endswith(".xml"):
            continue
        cons = str(row.get("consolidated") or "")
        out.append({
            "symbol": sym,
            "company": row.get("cmName") or row.get("smName"),
            "from": None,                 # the document declares its own period
            "to": row.get("qe_Date"),
            "period": "Quarterly",
            "relating_to": None,
            "financial_year": None,
            "consolidated": cons.lower().startswith("consol"),
            "audited": row.get("audited"),
            "filed_at": row.get("broadcast_Date") or row.get("creation_Date"),
            "xbrl": url,
            "regime": "integrated",
        })
    return out


def _legacy_filings(sym, period="Quarterly"):
    """
    Filings under the pre-Integrated regime. Historical only — nothing has
    been added here since the December 2024 quarter — but it is where the
    year-earlier comparatives for the first integrated quarters live, so it
    is still needed and not merely kept for sentiment.
    """
    out = []
    for row in _api(NSE_RESULTS, {"index": "equities", "symbol": sym,
                                  "period": period}):
        url = (row.get("xbrl") or "").strip()
        if not url.lower().endswith(".xml"):
            continue
        out.append({
            "symbol": row.get("symbol"),
            "company": row.get("companyName"),
            "from": row.get("fromDate"),
            "to": row.get("toDate"),
            "period": row.get("period"),
            "relating_to": row.get("relatingTo"),
            "financial_year": row.get("financialYear"),
            "consolidated": (row.get("consolidated") or "").lower().startswith("consol"),
            "audited": row.get("audited"),
            "filed_at": row.get("filingDate") or row.get("broadCastDate"),
            "xbrl": url,
            "regime": "legacy",
        })
    return out


def filings(symbol, period="Quarterly", retain_versions=False):
    """
    Every results filing NSE lists for one symbol, newest first, across both
    filing regimes.

    Reading only the legacy endpoint is what made this module report the
    December 2024 quarter as current twenty months later. It was not stale
    data — that endpoint had simply stopped being where results are filed.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not sym:
        return []

    def safely(fn, *a):
        """
        One regime failing must degrade the history, not empty it. The recent
        quarters and the year-earlier comparatives come from different
        endpoints, so an unguarded raise in either loses both.
        """
        try:
            return fn(*a) or []
        except Exception:
            return []

    merged, seen = [], set()
    # Integrated first so that where the two regimes overlap, the newer filing
    # wins the deduplication.
    for src in (safely(_integrated_filings, sym),
                safely(_legacy_filings, sym, period)):
        for row in src:
            end = _dparse(row.get("to"))
            key = ((end, bool(row.get("consolidated")), row.get("filed_at"), row.get("xbrl"))
                   if retain_versions else (end, bool(row.get("consolidated"))))
            if end and key in seen:
                continue
            if end:
                seen.add(key)
            merged.append(row)

    merged.sort(key=lambda r: (_dparse(r.get("to")) or dt.date.min,
                               _dparse(r.get("filed_at")) or dt.date.min),
                reverse=True)
    return merged


# The integrated feed labels a filing by its quarter-end date and nothing else,
# where the legacy feed carried "Third Quarter" in words. Growth is matched on
# the quarter label, so one has to be derived or every integrated filing would
# fail to find its year-earlier comparative.
_QUARTER_NAMES = {3: "Fourth Quarter", 6: "First Quarter",
                  9: "Second Quarter", 12: "Third Quarter"}


def _quarter_of(end):
    d = _dparse(end)
    return _QUARTER_NAMES.get(d.month) if d else None


def _dparse(s):
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return dt.datetime.strptime(str(s).strip(), fmt).date()
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _tag(el):
    """Element name without its namespace."""
    t = el.tag
    return t.rsplit("}", 1)[-1] if "}" in t else t


def _contexts(root):
    """
    {id: {"start", "end", "instant", "dimensional"}}.

    `dimensional` is the important one: a context carrying an explicitMember
    describes a segment or a breakup line, never the company total.
    """
    out = {}
    for el in root.iter():
        if _tag(el) != "context":
            continue
        cid = el.get("id")
        if not cid:
            continue
        info = {"start": None, "end": None, "instant": None, "dimensional": False}
        for sub in el.iter():
            name = _tag(sub)
            if name == "startDate":
                info["start"] = (sub.text or "").strip()
            elif name == "endDate":
                info["end"] = (sub.text or "").strip()
            elif name == "instant":
                info["instant"] = (sub.text or "").strip()
            elif name in ("explicitMember", "typedMember"):
                info["dimensional"] = True
        out[cid] = info
    return out


def _numeric(text):
    if text is None:
        return None
    t = str(text).strip().replace(",", "")
    if not t or not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse(xml_text):
    """
    One filing -> {"period": {...}, "facts": {name: value}, "text": {...}}.

    Only non-dimensional facts in the context matching the filing's own
    declared reporting period are returned, so a nine-month total and a
    segment's revenue can never arrive wearing the quarter's name.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return {"ok": False, "error": f"not parseable XBRL: {str(e)[:90]}"}

    ctx = _contexts(root)

    # Every fact, with its context, so the period can be read before choosing.
    raw = []
    for el in root.iter():
        cref = el.get("contextRef")
        if not cref:
            continue
        raw.append((_tag(el), cref, (el.text or "").strip()))

    def first_text(name):
        for n, c, v in raw:
            if n == name and v:
                return v
        return None

    p_start = first_text("DateOfStartOfReportingPeriod")
    p_end = first_text("DateOfEndOfReportingPeriod")

    # Filings made under the 2018 BSE taxonomy (TCS's, up to about 2020)
    # reference their company-level contexts — OneD, FourD, OneI — without
    # ever defining them; only the segment contexts are declared. Every fact
    # in those documents was being discarded, which is why the history
    # stopped short in 2020. Each undefined duration context states its own
    # period as facts inside it, so it can be rebuilt from those; an
    # undefined instant is the balance at the end of the reporting period.
    own = {}
    for n, c, v in raw:
        if n in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod") and v:
            own.setdefault(c, {})[n] = v
    # And where a context IS defined, the period its own facts state wins
    # over the definition: TCS's March 2024 filing defines FourD as January
    # to March while the facts inside it say April to March, which silently
    # turned the full year into a second copy of the quarter.
    for cref, stated in own.items():
        c = ctx.get(cref)
        if c and not c["dimensional"] and c["start"] and \
                stated.get("DateOfStartOfReportingPeriod") and \
                stated.get("DateOfEndOfReportingPeriod"):
            c["start"] = stated["DateOfStartOfReportingPeriod"]
            c["end"] = stated["DateOfEndOfReportingPeriod"]
    # Some filings (HDFC Bank's up to 2021) state only the END of each
    # period. The exchange's naming then carries the rest: One is the quarter
    # and Four the year to date, which starts where the filing says the
    # financial year starts.
    fy_start = first_text("DateOfStartOfFinancialYear")
    for cref in {c for _n, c, _v in raw} - set(ctx):
        if not re.fullmatch(r"[A-Z][a-z]+[DI]", cref):
            continue
        if cref.endswith("D") and cref in own:
            start = own[cref].get("DateOfStartOfReportingPeriod")
            end = own[cref].get("DateOfEndOfReportingPeriod")
            e = _dparse(end)
            if not start and e and cref == "OneD":
                m = e.month - 2 if e.month > 2 else e.month + 10
                start = dt.date(e.year if e.month > 2 else e.year - 1, m, 1).isoformat()
            elif not start and cref == "FourD":
                start = fy_start
            if not start:
                continue
            ctx[cref] = {"start": start, "end": end,
                         "instant": None, "dimensional": False}
        elif cref.endswith("I") and p_end:
            ctx[cref] = {"start": None, "end": None, "instant": p_end,
                         "dimensional": False}

    plain = {c: i for c, i in ctx.items() if not i["dimensional"]}

    # The duration context whose dates ARE the declared reporting period.
    duration = None
    if p_start and p_end:
        for cid, i in plain.items():
            if i["start"] == p_start and i["end"] == p_end:
                duration = cid
                break
    if duration is None:
        # No declaration to match: take the shortest plain duration, which is
        # the quarter rather than the year to date.
        spans = []
        for cid, i in plain.items():
            a, b = _dparse(i["start"]), _dparse(i["end"])
            if a and b:
                spans.append(((b - a).days, cid))
        if spans:
            duration = min(spans)[1]
            p_start = p_start or plain[duration]["start"]

    # Every plain duration ending on the reporting date, shortest first. The
    # shortest is the quarter; the longest is the year to date — six months in
    # a September filing, the full year in a March one — and it is where the
    # cash flow statement and the annual P&L live.
    ending = []
    if p_end:
        for cid, i in plain.items():
            a, b = _dparse(i["start"]), _dparse(i["end"])
            if a and b and i["end"] == p_end:
                ending.append(((b - a).days, cid))
    ending.sort()
    # A filing that declares its whole year as the reporting period still
    # carries the quarter; the quarter is what `facts` promises.
    if duration and ending and ending[0][1] != duration and ending[0][0] <= 130:
        cur = plain[duration]
        a, b = _dparse(cur["start"]), _dparse(cur["end"])
        if a and b and (b - a).days > 130:
            duration = ending[0][1]
            p_start = plain[duration]["start"]
    ytd = ending[-1][1] if ending and ending[-1][1] != duration \
        and ending[-1][0] > 130 else None

    instant = None
    for cid, i in plain.items():
        if i["instant"] and (p_end is None or i["instant"] == p_end):
            instant = cid
            break

    keep = {c for c in (duration, instant) if c}
    facts, text, facts_ytd, facts_instant = {}, {}, {}, {}
    for name, cref, value in raw:
        num = _numeric(value)
        if cref == ytd and num is not None:
            facts_ytd.setdefault(name, num)
        if cref == instant and num is not None:
            facts_instant.setdefault(name, num)
        if cref not in keep:
            continue
        if num is not None:
            facts.setdefault(name, num)
        elif value:
            text.setdefault(name, value)

    return {
        "ok": True,
        "period": {"from": p_start, "to": p_end,
                   "duration_context": duration, "instant_context": instant},
        "ytd": ({"from": plain[ytd]["start"], "to": plain[ytd]["end"],
                 "context": ytd} if ytd else None),
        "facts": facts,
        "facts_ytd": facts_ytd,
        "facts_instant": facts_instant,
        "text": text,
        "contexts": len(ctx),
        "dimensional_contexts_skipped": sum(1 for i in ctx.values() if i["dimensional"]),
    }


# ---------------------------------------------------------------------------
# Normalisation
#
# XBRL element names are precise and unreadable. These map onto the vocabulary
# the rest of the engine already speaks. Each key lists candidates in order of
# preference, because the taxonomy has changed and older filings use the
# earlier spelling.
# ---------------------------------------------------------------------------

FIELDS = {
    # Banks file under a format of their own: interest earned is the top
    # line, interest expended the finance cost. Ind AS names come first in
    # every list, so nothing a company files under Ind AS reads differently.
    "revenue":          ["RevenueFromOperations", "InterestEarned"],
    "other_income":     ["OtherIncome"],
    "total_income":     ["Income", "TotalIncome"],
    "materials":        ["CostOfMaterialsConsumed"],
    "purchases":        ["PurchasesOfStockInTrade"],
    "inventory_change": ["ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade"],
    "employee_cost":    ["EmployeeBenefitExpense", "EmployeesCost"],
    "finance_cost":     ["FinanceCosts", "InterestExpended"],
    "depreciation":     ["DepreciationDepletionAndAmortisationExpense"],
    "other_expenses":   ["OtherExpenses", "OtherOperatingExpenses"],
    "total_expenses":   ["Expenses", "TotalExpenses",
                         "ExpenditureExcludingProvisionsAndContingencies"],
    "operating_profit_pre_provision": ["OperatingProfitBeforeProvisionAndContingencies"],
    "provisions":       ["ProvisionsOtherThanTaxAndContingencies"],
    "pbt_before_exceptional": ["ProfitBeforeExceptionalItemsAndTax"],
    "exceptional":      ["ExceptionalItemsBeforeTax", "ExceptionalItems"],
    "pbt":              ["ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"],
    "current_tax":      ["CurrentTax"],
    "deferred_tax":     ["DeferredTax"],
    "tax":              ["TaxExpense"],
    "pat":              ["ProfitLossForPeriod", "ProfitLossForPeriodFromContinuingOperations",
                         "ProfitLossForThePeriod"],
    "comprehensive_income": ["ComprehensiveIncomeForThePeriod"],
    "eps_basic":        ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                         "BasicEarningsLossPerShareFromContinuingOperations",
                         "BasicEarningsPerShareAfterExtraordinaryItems"],
    "eps_diluted":      ["DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                         "DilutedEarningsLossPerShareFromContinuingOperations"],
    "equity_capital":   ["PaidUpValueOfEquityShareCapital"],
    "face_value":       ["FaceValueOfEquityShareCapital"],
    # From the segment reconciliation, which by construction balances to the
    # balance-sheet totals — NetSegmentAssets is total assets at period end and
    # NetSegmentLiabilities is equity plus liabilities. Not the full balance
    # sheet, but the denominator most ratios need, and it arrives quarterly.
    "total_assets":     ["NetSegmentAssets"],
    "total_liabilities": ["NetSegmentLiabilities"],
    "segment_assets_allocated": ["SegmentAssets"],
    "unallocable_assets": ["UnAllocableAssets"],
    "debt_equity":      ["DebtEquityRatio"],
    "debt_service_cover": ["DebtServiceCoverageRatio"],
    "interest_cover":   ["InterestServiceCoverageRatio"],
}


# The statement of assets and liabilities, filed with the half-year and
# annual results (September and March) since the September 2022 half-year.
# Candidates run Ind AS first, then the banking format (Advances, Deposits,
# Capital, Reserves and Surplus), then the NBFC one.
BALANCE_FIELDS = {
    "total_assets":          ["Assets"],
    "non_current_assets":    ["NoncurrentAssets"],
    "ppe":                   ["PropertyPlantAndEquipment", "FixedAssets"],
    "cwip":                  ["CapitalWorkInProgress"],
    "goodwill":              ["Goodwill"],
    "other_intangibles":     ["OtherIntangibleAssets"],
    "non_current_investments": ["NoncurrentInvestments"],
    "current_assets":        ["CurrentAssets"],
    "inventories":           ["Inventories"],
    "current_investments":   ["CurrentInvestments"],
    "investments":           ["Investments"],
    "trade_receivables":     ["TradeReceivablesCurrent", "TradeReceivables"],
    "cash_and_equivalents":  ["CashAndCashEquivalents", "CashAndBalancesWithReserveBankOfIndia"],
    "other_bank_balances":   ["BankBalanceOtherThanCashAndCashEquivalents",
                              "BalancesWithBanksAndMoneyAtCallAndShortNotice"],
    "loans":                 ["Loans", "Advances"],
    "total_equity":          ["Equity"],
    "equity_capital":        ["EquityShareCapital", "Capital"],
    "other_equity":          ["OtherEquity", "ReservesAndSurplus"],
    "equity_to_owners":      ["EquityAttributableToOwnersOfParent"],
    "minority_interest":     ["NonControllingInterest"],
    "total_liabilities":     ["Liabilities"],
    "non_current_liabilities": ["NoncurrentLiabilities"],
    "current_liabilities":   ["CurrentLiabilities"],
    "borrowings_non_current": ["BorrowingsNoncurrent"],
    "borrowings_current":    ["BorrowingsCurrent"],
    "borrowings":            ["Borrowings"],
    "debt_securities":       ["DebtSecurities"],
    "subordinated_liabilities": ["SubordinatedLiabilities"],
    "deposits":              ["Deposits"],
    "trade_payables":        ["TradePayablesCurrent"],
    "total_equity_and_liabilities": ["EquityAndLiabilities", "CapitalAndLiabilities"],
}

# The cash flow statement, year to date: six months in a September filing, the
# full year in a March one. Filed from the 2020-21 year. Payments — capex,
# dividends, interest — are filed as positive amounts.
CASHFLOW_FIELDS = {
    "cfo":                 ["CashFlowsFromUsedInOperatingActivities"],
    "cfi":                 ["CashFlowsFromUsedInInvestingActivities"],
    "cff":                 ["CashFlowsFromUsedInFinancingActivities"],
    "capex_ppe":           ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                            "PurchaseOfTangibleAssetsClassifiedAsInvestingActivities"],
    "capex_intangibles":   ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
    "asset_sale_proceeds": ["ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                            "ProceedsFromSalesOfTangibleAssetsClassifiedAsInvestingActivities"],
    "income_tax_paid":     ["IncomeTaxesPaidRefundClassifiedAsOperatingActivities"],
    "dividends_paid":      ["DividendsPaidClassifiedAsFinancingActivities"],
    "interest_paid":       ["InterestPaidClassifiedAsFinancingActivities"],
    "borrowings_raised":   ["ProceedsFromBorrowingsClassifiedAsFinancingActivities"],
    "borrowings_repaid":   ["RepaymentsOfBorrowingsClassifiedAsFinancingActivities"],
    "lease_payments":      ["PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities"],
    "share_buyback":       ["PaymentsToAcquireOrRedeemEntitysShares"],
    "shares_issued":       ["ProceedsFromIssuingSharesClassifiedAsFinancingActivities",
                            "ProceedsFromIssuingShares"],
    "net_change_in_cash":  ["IncreaseDecreaseInCashAndCashEquivalents"],
    "closing_cash":        ["CashAndCashEquivalentsCashFlowStatement"],
}

# Bumped whenever normalise() starts returning something new, so fetch() can
# tell a cached parse that predates it from one that does not.
SCHEMA = 5


def _pick(f, fields):
    out = {}
    for key, names in fields.items():
        for n in names:
            if n in f:
                out[key] = f[n]
                break
    return out


def _pnl(f):
    """The income statement lines, plus EBITDA and the margins that follow."""
    out = _pick(f, FIELDS)
    rev = out.get("revenue")
    if rev:
        pbt = out.get("pbt")
        if pbt is not None and all(out.get(k) is not None for k in ("finance_cost", "depreciation", "other_income")):
            ebitda = pbt + (out.get("finance_cost") or 0) + (out.get("depreciation") or 0) \
                     - (out.get("other_income") or 0)
            out["ebitda"] = round(ebitda, 2)
    return out


def normalise(parsed):
    """Friendly field names plus the margins that follow from them."""
    if not parsed.get("ok"):
        return dict(parsed)
    f = parsed["facts"]
    out = {}
    for key, names in FIELDS.items():
        for n in names:
            if n in f:
                out[key] = f[n]
                break

    rev = out.get("revenue")
    if rev:
        # EBITDA from the statement's own lines: profit before tax, add back
        # finance cost and depreciation, strip out non-operating income.
        pbt = out.get("pbt")
        if pbt is not None and all(out.get(k) is not None for k in ("finance_cost", "depreciation", "other_income")):
            ebitda = pbt + (out.get("finance_cost") or 0) + (out.get("depreciation") or 0) \
                     - (out.get("other_income") or 0)
            out["ebitda"] = round(ebitda, 2)
            out["ebitda_margin_pct"] = round(ebitda / rev * 100, 2)
            out["pbt_margin_pct"] = round(pbt / rev * 100, 2)
        if out.get("pat") is not None:
            out["net_margin_pct"] = round(out["pat"] / rev * 100, 2)

    # Return on assets, annualised from the quarter. Stated as derived so it
    # is never mistaken for a figure the company reported.
    ta, pat = out.get("total_assets"), out.get("pat")
    if ta and pat is not None:
        out["roa_annualised_pct"] = round(pat * 4 / ta * 100, 2)

    out["period"] = parsed.get("period")

    # The balance sheet at the reporting date, and the year to date — the
    # annual P&L in a March filing and the cash flow in March and September.
    # Kept apart from the quarter's lines above so nothing that reads those
    # can mistake a year's figure for a quarter's.
    bs = _pick(parsed.get("facts_instant") or {}, BALANCE_FIELDS)
    if bs:
        out["balance_sheet"] = bs
    y = parsed.get("ytd")
    if y and parsed.get("facts_ytd"):
        a, b = _dparse(y.get("from")), _dparse(y.get("to"))
        ytd = {"from": y.get("from"), "to": y.get("to"),
               "months": round((b - a).days / 30.44) if a and b else None}
        ytd.update(_pnl(parsed["facts_ytd"]))
        cf = _pick(parsed["facts_ytd"], CASHFLOW_FIELDS)
        if cf.get("cfo") is None:
            # Filings up to about 2021 tag the cash flow against the QUARTER's
            # context. Regulation 33 never asks for a quarterly cash flow — it
            # is filed for the half-year and the year only — so a cash flow
            # found there is the year to date, whatever its context says.
            # TCS's FY21 filing: ₹38,802 cr of operating cash flow, which is
            # the full year's figure, under OneD.
            cf = _pick(f, CASHFLOW_FIELDS)
        ytd.update(cf)
        out["ytd"] = ytd
    out["schema"] = SCHEMA
    return out


def _cache_path(url):
    if not CACHE_DIR:
        return None
    return os.path.join(CACHE_DIR, hashlib.sha1(("v4:" + url).encode()).hexdigest() + ".json")


def fetch(url, cache=True):
    """
    One filing, parsed and normalised. Cached on disk for good: a filed XBRL
    document is immutable, so re-fetching it is pure waste.

    A cached parse from before SCHEMA is read again, once, so it gains what
    normalise() has learned to extract since. `cache=False` is for the
    fundamentals crawl, whose tables are themselves the durable copy — caching
    eighty thousand documents beside them would fill the disk twice.
    """
    path = _cache_path(url)
    if path and os.path.exists(path):
        try:
            with open(path) as fh:
                hit = json.load(fh)
            if hit.get("schema", 0) >= SCHEMA:
                return hit
        except Exception:
            pass
    # The document lives on nsearchives and needs the same impersonating
    # handshake as the index call — a plain fetch is refused there too.
    r = nse_http.get(url, referer=nse_http.NSE_HOME)
    if r is None:
        return {"ok": False, "error": "could not fetch the filing"}
    try:
        out = normalise(parse(r.text))
    except Exception as e:
        return {"ok": False, "error": f"could not read the filing: {str(e)[:90]}"}
    if cache and path and out.get("period"):
        try:
            with open(path, "w") as fh:
                json.dump(out, fh)
        except Exception:
            pass
    return out


def statements(symbol, limit=8, consolidated=None, as_of=None, retain_versions=False):
    """
    The last `limit` quarters for one symbol, newest first, with year-on-year
    growth against the same quarter a year earlier — not against the previous
    quarter, which for most Indian businesses compares a festive season with a
    monsoon and calls the difference performance.
    """
    idx = filings(symbol, retain_versions=True) if retain_versions else filings(symbol)
    if as_of is not None:
        from factors import cutoff_date
        cutoff = cutoff_date(as_of)
        idx = [f for f in idx if _dparse(f.get("filed_at")) is not None and
               _dparse(f.get("filed_at")) <= cutoff]
    if consolidated is not None:
        want = [f for f in idx if f["consolidated"] == consolidated]
        idx = want or idx          # not every company files both
    if retain_versions:
        # Select metadata BEFORE fetching. Keep one known revision per period
        # and one accounting basis; at most limit documents hit the disk/network.
        from factors import known_quarters
        candidates = [{**f, "period": {"to": (_dparse(f.get("to")) or dt.date.min).isoformat()},
                       "source_url": f["xbrl"]} for f in idx]
        idx = known_quarters(candidates, as_of, consolidated)[:max(1, limit)]
    else:
        idx = idx[:max(1, limit)]

    rows = []
    for meta in idx:
        data = fetch(meta["xbrl"])
        if not data or data.get("ok") is False:
            continue
        row = dict(data)
        # The index and the document can each supply the period. Prefer the
        # index when it has one, because that is what the exchange indexed the
        # filing under — but an integrated filing only carries a quarter-end
        # date, and blindly overwriting would have replaced a period the
        # document declares for itself with None.
        declared = data.get("period") or {}
        row.update({"from": meta.get("from") or declared.get("from"),
                    "to": meta.get("to") or declared.get("to"),
                    "quarter": meta.get("relating_to") or _quarter_of(
                        meta.get("to") or declared.get("to")),
                    "financial_year": meta.get("financial_year"),
                    "consolidated": meta["consolidated"],
                    "audited": meta.get("audited"),
                    "filed_at": meta.get("filed_at"),
                    "regime": meta.get("regime"),
                    "source_url": meta["xbrl"]})
        rows.append(row)

    by_end = {r.get("to"): r for r in rows}
    for r in rows:
        end = _dparse(r.get("to"))
        if not end:
            continue
        for cand_end, cand in by_end.items():
            d = _dparse(cand_end)
            if not d:
                continue
            gap = (end - d).days
            if 300 <= gap <= 430:          # the same quarter, a year earlier
                for key in ("revenue", "pat", "ebitda"):
                    now, then = r.get(key), cand.get(key)
                    if now is not None and then:
                        r[f"{key}_yoy_pct"] = round((now - then) / abs(then) * 100, 2)
                r["yoy_against"] = cand_end
                break
    return rows


# ---------------------------------------------------------------------------
# Freshness
#
# WHY THIS EXISTS, AND WHAT IT IS NOT
# This module was reporting the December 2024 quarter as current, twenty
# months later, in complete silence. The parser was not at fault: NSE's
# corporates-financial-results API is itself frozen. Queried for the WHOLE
# equities universe it returns 3,816 rows whose newest toDate is 31-Dec-2024,
# and no combination of symbol, period or date-range parameters produces
# anything newer. There is nothing to fix upstream from here.
#
# What WAS ours to fix is that nothing said so. Stale fundamentals presented
# as current are worse than absent ones: a year-on-year growth factor computed
# from twenty-month-old filings is not weak, it is wrong, and it would have
# ranked the entire universe while looking perfectly healthy.
#
# So freshness is measured, published, and — in factors.py — enforced.
# ---------------------------------------------------------------------------

# A company filing quarterly under Reg 33 owes a result within 45 days of the
# quarter end. Allowing a full extra quarter on top of that is generous and
# still catches a source that has stopped moving.
STALE_AFTER_DAYS = int(os.environ.get("XBRL_STALE_DAYS", "135") or 135)


def _age_days(latest_end, today=None):
    d = _dparse(latest_end)
    if not d:
        return None
    return ((today or dt.date.today()) - d).days


def latest_bse_result(symbol, days=200):
    """
    When BSE last saw a results filing for this company.

    A cross-check, not a data source. BSE's announcement feed is live —
    verified current to within a day — while NSE's XBRL index is not, so the
    gap between them turns "our fundamentals might be old" into a fact with a
    date on it: NSE's newest XBRL for this symbol is from December 2024, BSE
    saw it file results in August 2026, therefore the XBRL is two quarters
    behind for THIS company rather than in general.

    Returns None on any failure. This must never be able to break a payload —
    it is a footnote, not a dependency.
    """
    try:
        import announcements as ann
    except Exception:
        return None
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    try:
        rows = (ann.feed(limit=200, symbol=sym) or {}).get("items") or []
    except Exception:
        return None
    best = None
    for r in rows:
        cat = str(r.get("category") or r.get("subcategory") or "")
        head = str(r.get("headline") or r.get("line") or "")
        if "result" not in (cat + " " + head).lower():
            continue
        when = _dparse(str(r.get("at") or r.get("date") or "")[:11])
        if when and (best is None or when > best):
            best = when
    return best.isoformat() if best else None


def freshness(rows, symbol=None, today=None):
    """
    How old the newest filing is, and whether that is a problem.

    Always returns a verdict, including when there is nothing to judge.
    """
    today = today or dt.date.today()
    latest = rows[0].get("to") if rows else None
    age = _age_days(latest, today)
    out = {
        "latest_period_end": latest,
        "latest_filed_at": (rows[0].get("filed_at") if rows else None),
        "age_days": age,
        "stale_after_days": STALE_AFTER_DAYS,
        "stale": bool(age is not None and age > STALE_AFTER_DAYS),
        "checked_on": today.isoformat(),
    }
    if age is None:
        out["note"] = "No dated filing to measure."
        return out
    if not out["stale"]:
        out["note"] = f"Newest filing covers a period ending {latest} — current."
        return out

    out["note"] = (
        f"The newest XBRL filing available covers a period ending {latest}, "
        f"{age} days ago. NSE's results index is not serving anything newer — "
        "for any symbol, not just this one — so growth and margin figures "
        "derived from it describe a period that has since been superseded.")
    if symbol:
        # Guarded here as well as inside. The docstring promises this is a
        # footnote rather than a dependency, and a promise a caller cannot
        # rely on is worse than one that was never made.
        try:
            seen = latest_bse_result(symbol)
        except Exception:
            seen = None
        if seen:
            out["bse_last_result_seen"] = seen
            out["note"] += (f" BSE's live announcement feed shows this company "
                            f"filing results as recently as {seen}, which is the "
                            "measure of how far behind the XBRL source is.")
    return out


def summary(symbol, limit=8, consolidated=None):
    rows = statements(symbol, limit=limit, consolidated=consolidated)
    if not rows:
        return {"available": False, "symbol": symbol,
                "message": ("No XBRL results filing found for this symbol on the "
                            "exchange. Fundamentals fall back to the existing "
                            "provider."),
                "source": "NSE corporate filings (XBRL, LODR Reg 33)"}
    fresh = freshness(rows, symbol)
    return {
        "available": True,
        "symbol": (symbol or "").upper(),
        "company": rows[0].get("company"),
        "quarters": rows,
        "count": len(rows),
        "freshness": fresh,
        "stale": fresh["stale"],
        "as_of": fresh["latest_period_end"],
        "source": "NSE corporate filings (XBRL, LODR Reg 33)",
        "covers": ("The income statement in full, plus total assets and total "
                   "liabilities from the segment reconciliation. A quarterly Reg 33 "
                   "filing does not carry the rest of the balance sheet or the cash "
                   "flow statement, so the current ratio and operating cash flow "
                   "still come from the existing provider."),
    }


_scoring_cache = {}
_scoring_lock = threading.Lock()


def scoring_statements(symbol, as_of=None, limit=16):
    """Bounded one-hour cache of PIT-selected history; reuse immutable XML cache.

    Callers running historical research must supply as_of. The key includes
    the cutoff; today's revisions can never satisfy a historical cache read.
    """
    import time
    from factors import cutoff_date
    key = (symbol, cutoff_date(as_of).isoformat(), limit)
    with _scoring_lock:
        cached = _scoring_cache.get(key)
        if cached and time.time()-cached[0] < 3600:
            return cached[1]
    rows = statements(symbol, limit=limit, as_of=key[1], retain_versions=True)
    try:
        import pit_store
        from factors import known_quarters
        pit_store.record_quarter_versions(symbol, rows)
        rows = known_quarters(pit_store.quarter_versions(symbol), key[1])[:limit]
    except Exception:
        # Live scoring survives storage failure; scan PIT health exposes durability.
        pass
    with _scoring_lock:
        if len(_scoring_cache) >= 256:
            oldest = min(_scoring_cache, key=lambda k:_scoring_cache[k][0])
            _scoring_cache.pop(oldest, None)
        _scoring_cache[key] = (time.time(), rows)
    return rows
