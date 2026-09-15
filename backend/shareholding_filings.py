"""
Altaha Screener — Who owns the company, from the company's own filing

WHY THIS EXISTS
Every listed Indian company files its shareholding pattern with the exchanges
each quarter under LODR Regulation 31. The filing is XBRL, machine readable,
free, and authoritative — it is the company's own submission, not a scrape of
somebody's summary page. It carries three things retail screeners in India
mostly flatten into one number:

  · the split between promoters, foreign institutions, domestic institutions
    and the rest of the public,
  · how many shareholders sit in each of those buckets, and
  · the name of every promoter entity and every public holder above 1%.

The change between quarters is the part worth reading. A promoter stake that
falls two points, or an FII line that has been cut in half over four quarters,
is a fact about the company that its reported profit will not tell you.

THE TRAP THIS MODULE IS BUILT AROUND
In the SEBI format "Public" is not a sibling of FII and DII — it is their
PARENT. Table III is public shareholding, and foreign institutions, domestic
institutions and non-institutional holders are all inside it. For Reliance's
June 2026 filing:

    promoter 50.48 + public 49.52                          = 100.00
    public 49.52 = FII 17.20 + DII 21.19 + non-inst 11.04 + govt 0.10

So a chart drawing promoter, FII, DII and public as four slices of one pie
double-counts roughly forty per cent of the company. This module never emits
that shape. `split` is the non-overlapping decomposition that sums to 100 and
is what the UI draws; `public_total` is the reported Table III figure and is
labelled as the parent it is.

TWO MORE THINGS THE FORMAT WILL CATCH YOU ON
  1. SCALE. Percentages are filed as fractions — 0.5048, not 50.48. Older
     taxonomy versions are not perfectly consistent about it, so the scale is
     detected from the grand total rather than assumed.
  2. NAMESPACES. A 2021 filing uses the 2020-09-30 taxonomy and a 2026 one the
     2025-10-31 taxonomy. The element and member LOCAL names are stable across
     both, so everything here matches on local name and ignores the namespace.

NAMED HOLDERS
A named row is split across two contexts by the filer: `D_<key>` carries the
name and PAN, `<key>` carries the numbers. They are joined on that key. A row
is a promoter if its descriptive context carries TypeOfPromoterShareholding —
which is what the format uses to mark Table II — rather than by guessing from
the category.

COST
A filing is ~500KB of XML and a company has five years of them. Parsing
twenty-two of those on a 512MB box to render one page is not acceptable, so
the PARSED result (about 2KB of JSON) is cached to disk per filing. A filed
document never changes once published, so that cache never expires. Only the
index of filings is re-fetched, and that on a TTL.
"""

import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", "").strip() or HERE
CACHE_DIR = os.path.join(DATA_DIR, "shp-cache")
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except Exception:
    CACHE_DIR = None

NSE_MASTER = "https://www.nseindia.com/api/corporate-share-holdings-master"
NSE_REFERER = ("https://www.nseindia.com/companies-listing/"
               "corporate-filings-shareholding-pattern")
NSE_HOME = "https://www.nseindia.com/"

TIMEOUT = 30
INDEX_TTL = 6 * 3600          # filings land quarterly; six hours is generous.
MAX_PARSE = 12                # quarters parsed for one page. Three years.
MAX_INDEXED = 400             # symbols held in the in-process index cache

_lock = threading.Lock()
_sess = {"s": None, "warm": 0.0}
_index_cache = {}             # SYMBOL -> (fetched_at, [row, ...])


# ---------------------------------------------------------------------------
# Transport
#
# NSE's WAF rejects a plain requests call from a datacenter IP with a 403 that
# no combination of headers gets past — it fingerprints the TLS handshake, not
# the headers. curl_cffi impersonates a real Chrome handshake, which is why it
# is already a dependency of this project (yfinance pulls it for the same
# reason). If it is missing the module reports itself unavailable rather than
# pretending to have data.
# ---------------------------------------------------------------------------

def _curl():
    try:
        from curl_cffi import requests as cr
        return cr
    except Exception:
        return None


def available() -> bool:
    return _curl() is not None


def session():
    """Built on first use. Parsing needs no network, so importing must not open one."""
    cr = _curl()
    if cr is None:
        return None
    with _lock:
        if _sess["s"] is None:
            _sess["s"] = cr.Session(impersonate="chrome")
        return _sess["s"]


def _warm_session(force=False):
    """NSE hands out cookies on the public site and expects them on /api."""
    if not force and time.time() - _sess["warm"] < 1800:
        return
    s = session()
    if s is None:
        return
    for url in (NSE_HOME, NSE_REFERER):
        try:
            s.get(url, timeout=TIMEOUT)
        except Exception:
            pass
    _sess["warm"] = time.time()


def _get(url, params=None, referer=NSE_REFERER):
    """One authenticated NSE call, with the cookie re-warm it periodically needs."""
    s = session()
    if s is None:
        return None
    _warm_session()
    try:
        r = s.get(url, timeout=TIMEOUT, params=params, headers={"Referer": referer})
        if r.status_code in (401, 403):
            _warm_session(force=True)
            r = s.get(url, timeout=TIMEOUT, params=params, headers={"Referer": referer})
        if r.status_code != 200:
            return None
        return r
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Disk cache — parsed filings only, never the raw XML
# ---------------------------------------------------------------------------

def _cache_path(url: str):
    if not CACHE_DIR:
        return None
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return os.path.join(CACHE_DIR, key + ".json")


def _cache_read(url: str):
    p = _cache_path(url)
    if not p or not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _cache_write(url: str, payload: dict):
    p = _cache_path(url)
    if not p:
        return
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, p)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The index of filings
# ---------------------------------------------------------------------------

def _clean_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")


def _safe_doc_url(value):
    """
    The document URL arrives in a response body, and it is both fetched here
    and rendered as a link on the page. Neither should ever be handed anything
    but an https URL on the exchange's own archive.
    """
    try:
        p = urlparse(str(value or ""))
    except ValueError:
        return None
    if p.scheme != "https" or p.username or not p.netloc:
        return None
    host = p.netloc.lower().split(":")[0]
    if host != "nseindia.com" and not host.endswith(".nseindia.com"):
        return None
    return str(value)


def _parse_nse_date(s: str):
    """'30-JUN-2026' or '16-JUL-2026 19:24:44' -> date. None rather than a guess."""
    if not s:
        return None
    head = str(s).strip().split(" ")[0]
    try:
        return dt.datetime.strptime(head, "%d-%b-%Y").date()
    except Exception:
        return None


def index(symbol: str, force=False):
    """
    Every shareholding filing NSE holds for this symbol, newest first.

    Each row carries the URL of the XBRL document it was filed as, which is
    what makes the rest of this module possible and what lets the UI link a
    number back to the page it came from.
    """
    sym = _clean_symbol(symbol)
    if not sym:
        return []
    hit = _index_cache.get(sym)
    if hit and not force and time.time() - hit[0] < INDEX_TTL:
        return hit[1]

    r = _get(NSE_MASTER, params={"index": "equities", "symbol": sym})
    if r is None:
        return hit[1] if hit else []
    try:
        body = r.json()
    except Exception:
        return hit[1] if hit else []
    if not isinstance(body, list):
        return hit[1] if hit else []

    rows = []
    for raw in body:
        if not isinstance(raw, dict):
            continue
        url = _safe_doc_url((raw.get("xbrl") or "").strip())
        period = _parse_nse_date(raw.get("date"))
        if not url or not period:
            continue
        rows.append({
            "period": period.isoformat(),
            # Both dates are kept. The period is what the figures describe; the
            # broadcast date is when the market could first have known them,
            # and they can be three weeks apart.
            "filed": (_parse_nse_date(raw.get("submissionDate")) or
                      _parse_nse_date(raw.get("broadcastDate")) or period).isoformat(),
            "xbrl": url,
            "record_id": str(raw.get("recordId") or ""),
            # A revised filing supersedes an earlier one for the same quarter.
            # Keeping the flag means the UI can say so instead of silently
            # showing a number that the company itself has since corrected.
            "revised": str(raw.get("revisedStatus") or "").strip().lower() in ("true", "yes", "y"),
        })
    rows.sort(key=lambda x: (x["period"], x["filed"]), reverse=True)
    # One row per quarter: the latest filing for a period wins, which after the
    # sort above is the first one seen.
    seen, uniq = set(), []
    for row in rows:
        if row["period"] in seen:
            continue
        seen.add(row["period"])
        uniq.append(row)
    with _lock:
        # Bounded, because this process has 512MB and the universe has a few
        # thousand symbols in it. Oldest entry out; the disk cache underneath
        # means a re-fetch is cheap anyway.
        if len(_index_cache) >= MAX_INDEXED:
            oldest = min(_index_cache, key=lambda k: _index_cache[k][0])
            _index_cache.pop(oldest, None)
        _index_cache[sym] = (time.time(), uniq)
    return uniq


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# The categories worth naming, each as a list of candidate member names.
#
# Five years of filings span two structurally different SEBI formats. The
# 2020-09-30 taxonomy has a single `Institutions` line; the domestic/foreign
# split that everyone means by "DII" and "FII" only arrives with the later
# format. Where the split is not in the document it is derived, once, from
# arithmetic the document itself verifies — and flagged as derived rather than
# presented as something the company filed.
#
# `GovermentsMember` is not a typo here. It is a typo in the 2020 taxonomy.
CATEGORIES = {
    "promoter": ["ShareholdingOfPromoterAndPromoterGroupMember"],
    "fii": ["InstitutionsForeignMember",
            "InstitutionsForeignPortfolioInvestorMember"],
    "dii": ["InstitutionsDomesticMember"],
    "institutions_total": ["InstitutionsMember"],
    "public_non_institutional": ["NonInstitutionsMember"],
    "government": ["GovernmentsMember", "GovermentsMember",
                   "CentralGovernmentOrStateGovernmentSOrPresidentOfIndiaMember"],
    "custodian": ["CustodianOrDRHolderMember"],
    "non_promoter_non_public": ["SharesHeldByNonPromoterNonPublicShareholdersMember"],
    # Parents — reported, but never drawn alongside their own children.
    "public_total": ["PublicShareholdingMember"],
    "total": ["ShareholdingPatternMember"],
}

# The institutional detail under FII and DII that people actually ask for.
SUB_CATEGORIES = {
    "mutual_funds": ["MutualFundsOrUTIMember", "MutualFundsOrUtiMember"],
    "banks": ["BanksMember", "FinancialInstitutionOrBanksMember",
              "IndianFinancialInstitutionsOrBanksMember"],
    "insurance": ["InsuranceCompaniesMember"],
    "pension_funds": ["ProvidentFundsOrPensionFundsMember"],
    "alternative_investment_funds": ["AlternativeInvestmentFundsMember"],
    "fpi_category_one": ["InstitutionsForeignPortfolioInvestorCategoryOneMember"],
    "fpi_category_two": ["InstitutionsForeignPortfolioInvestorCategoryTwoMember"],
    "foreign_direct_investment": ["ForeignDirectInvestmentMember"],
    "retail_upto_2lakh": [
        "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember",
        "IndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhMember"],
    "retail_above_2lakh": [
        "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakhMember",
        "IndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakhMember"],
    "bodies_corporate": ["BodiesCorporateMember"],
    "non_resident_indians": ["NonResidentIndiansMember",
                             "NonResidentIndividualsOrForeignIndividualsMember"],
}

# Which axis a named row sits on tells you what kind of holder it is, and
# whether it belongs to Table II (promoters) or Table III (public).
NAMED_AXES = {
    "DetailsSharesHeldByIndividualsOrHUFAxis": ("Individual", True),
    "DetailsOfSharesHeldByIndividualsOrHUFAxis": ("Individual", True),
    "DetailsOfSharesHeldByOthersIndianShareholdersAxis": ("Body corporate / other", True),
    "DetailsOfSharesHeldByOtherIndianShareholdersAxis": ("Body corporate / other", True),
    "DetailsOfSharesHeldByOtherForeignShareholdersAxis": ("Foreign promoter", True),
    "DetailsOfSharesHeldByOtherNonInstitutionsAxis": ("Non-institutional", False),
    "DetailsOfSharesHeldByMutualFundsOrUTIAxis": ("Mutual fund", False),
    "DetailsOfSharesHeldByMutualFundsOrUtiAxis": ("Mutual fund", False),
    "DetailsOfSharesHeldByInsuranceCompaniesAxis": ("Insurance", False),
    "DetailsOfSharesHeldByProvidentFundsOrPensionFundsAxis": ("Pension fund", False),
    "DetailsOfSharesHeldByOtherInstitutionsForeignAxis": ("Foreign institution", False),
    "DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorAxis": ("Foreign portfolio investor", False),
    "DetailsOfSharesHeldByOtherInstitutionsAxis": ("Institution", False),
    "DetailsOfSharesHeldByCustodianOrDRHolderAxis": ("Custodian / DR", False),
}

_PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
_SHARES = "NumberOfFullyPaidUpEquityShares"
_HOLDERS = "NumberOfShareholders"
_LOCKED = "NumberOfTheLockedInShares"
_DEMAT = "NumberOfEquitySharesHeldInDematerializedForm"


def _fnum(v):
    if v is None:
        return None
    try:
        s = str(v).strip().replace(",", "")
        if not s or s in ("-", "NA", "N.A.", "******"):
            return None
        return float(s)
    except Exception:
        return None


def _pair_key(cid: str):
    """
    The numeric context that belongs to a descriptive one.

    Two conventions are in the wild and both are in use across the five years
    a company has on file:
        2025 taxonomy:  D_Foo_Context12  ->  Foo_Context12
        2020 taxonomy:  Foo001D          ->  Foo001I
    """
    if cid.startswith("D_"):
        return cid[2:]
    if cid.endswith("D"):
        return cid[:-1] + "I"
    return None


def parse(xml_text: str) -> dict:
    """
    One shareholding filing -> normalized categories, holder counts and names.

    Namespace-agnostic by design: five years of filings span taxonomy versions
    whose namespace URIs differ and whose local names do not.
    """
    root = ET.fromstring(xml_text)

    # --- contexts -------------------------------------------------------
    # A context is useful here in one of two shapes: a single explicit member
    # on the category axis (a bucket), or a typed member (a named holder).
    cat_ctx, named_ctx = {}, {}
    period_end = None
    for ctx in root:
        if _local(ctx.tag) != "context":
            continue
        cid = ctx.get("id")
        if not cid:
            continue
        explicit, axis = [], None
        for el in ctx.iter():
            name = _local(el.tag)
            if name == "explicitMember":
                explicit.append(((el.get("dimension") or "").rsplit(":", 1)[-1],
                                 (el.text or "").rsplit(":", 1)[-1].strip()))
            elif name == "typedMember":
                axis = (el.get("dimension") or "").rsplit(":", 1)[-1]
            elif name == "instant" and period_end is None:
                period_end = (el.text or "").strip()
        if axis:
            named_ctx[cid] = axis
        elif len(explicit) == 1 and explicit[0][0] == "CategoryOfShareholdersAxis":
            cat_ctx[cid] = explicit[0][1]

    # --- facts ----------------------------------------------------------
    by_member, by_ctx = {}, {}
    for el in root:
        tag = _local(el.tag)
        cid = el.get("contextRef")
        if not cid or tag in ("context", "unit"):
            continue
        text = (el.text or "").strip()
        if cid in cat_ctx:
            by_member.setdefault(cat_ctx[cid], {})[tag] = text
        else:
            by_ctx.setdefault(cid, {})[tag] = text

    # --- scale ----------------------------------------------------------
    # The later format files a fraction (0.5048) and the earlier one a percent
    # (50.61). The grand total is a free check, so it is used rather than the
    # assumption — getting this wrong is a hundredfold error on every figure.
    total_pct = None
    for m in CATEGORIES["total"]:
        total_pct = _fnum((by_member.get(m) or {}).get(_PCT))
        if total_pct is not None:
            break
    scale = 1.0 if (total_pct is not None and total_pct > 50) else 100.0

    def bucket(members):
        for m in members:
            f = by_member.get(m)
            if not f:
                continue
            p = _fnum(f.get(_PCT))
            return {
                "pct": round(p * scale, 4) if p is not None else None,
                "shares": _fnum(f.get(_SHARES)),
                "holders": _fnum(f.get(_HOLDERS)),
                "locked_in": _fnum(f.get(_LOCKED)),
                "demat": _fnum(f.get(_DEMAT)),
                "derived": False,
                "member": m,
            }
        return None

    cats = {}
    for key, members in CATEGORIES.items():
        b = bucket(members)
        if b is not None:
            cats[key] = b
    subs = {}
    for key, members in SUB_CATEGORIES.items():
        b = bucket(members)
        if b is not None and (b["pct"] or b["shares"]):
            subs[key] = b

    # --- the domestic/foreign split the older format does not carry ------
    # Institutions minus foreign institutions is domestic institutions, and the
    # document proves it: the remainder equals the sum of the domestic lines it
    # does report. Flagged as derived so the UI never calls it a filed figure.
    if "dii" not in cats and "institutions_total" in cats and "fii" in cats:
        tot, foreign = cats["institutions_total"], cats["fii"]
        if tot["pct"] is not None and foreign["pct"] is not None:
            cats["dii"] = {
                "pct": round(tot["pct"] - foreign["pct"], 4),
                "shares": ((tot["shares"] - foreign["shares"])
                           if tot["shares"] is not None and foreign["shares"] is not None else None),
                "holders": ((tot["holders"] - foreign["holders"])
                            if tot["holders"] is not None and foreign["holders"] is not None else None),
                "locked_in": None, "demat": None,
                "derived": True,
                "member": "%s minus %s" % (tot["member"], foreign["member"]),
            }

    # --- named holders --------------------------------------------------
    # The filer splits a named row across two contexts: one carries the name
    # and PAN, its partner carries the numbers. They are joined on the key.
    names = []
    for cid, facts in by_ctx.items():
        who = facts.get("NameOfTheShareholder")
        if not who:
            continue
        partner = _pair_key(cid)
        nums = (by_ctx.get(partner) or {}) if partner else {}
        p = _fnum(nums.get(_PCT))
        axis = named_ctx.get(cid) or (named_ctx.get(partner) if partner else None) or ""
        kind, is_promoter = NAMED_AXES.get(axis, ("Other", False))
        names.append({
            "name": who.strip()[:120],
            "pct": round(p * scale, 4) if p is not None else None,
            "shares": _fnum(nums.get(_SHARES)),
            # The later format also marks a Table II row with
            # TypeOfPromoterShareholding. Where present it confirms the axis.
            "promoter": is_promoter or ("TypeOfPromoterShareholding" in facts),
            "kind": kind,
        })
    names = [n for n in names if n["name"] and n["pct"] is not None]
    names.sort(key=lambda n: (-(n["pct"] or 0), n["name"]))

    return {
        "period_end": period_end,
        "categories": cats,
        "sub_categories": subs,
        "names": names,
        "filed_as_percent": scale == 1.0,
    }


# ---------------------------------------------------------------------------
# One filing, fetched and parsed, with the parse cached rather than the source
# ---------------------------------------------------------------------------

def filing(url: str, period: str = "", filed: str = "", revised: bool = False):
    """
    The parsed content of one filing.

    A filed document never changes once published, so the parse is cached to
    disk forever. Caching the parse rather than the 500KB of XML is what keeps
    a five-year history affordable on a small instance: the cached object is
    about two kilobytes.
    """
    hit = _cache_read(url)
    if hit is not None:
        return hit
    r = _get(url, referer=NSE_HOME)
    if r is None:
        return None
    try:
        parsed = parse(r.text)
    except Exception:
        return None
    parsed["source"] = url
    parsed["period"] = period or parsed.get("period_end") or ""
    parsed["filed"] = filed or ""
    parsed["revised"] = bool(revised)
    _cache_write(url, parsed)
    return parsed


# ---------------------------------------------------------------------------
# The four lines that make up the company, and how they moved
# ---------------------------------------------------------------------------

# The non-overlapping decomposition. These sum to 100 because none of them
# contains another — which is exactly what `public_total` cannot say, since it
# is the parent of three of them.
SPLIT_KEYS = ("promoter", "fii", "dii", "public_non_institutional",
              "government", "custodian", "non_promoter_non_public")

LABELS = {
    "promoter": "Promoters",
    "fii": "Foreign institutions (FII/FPI)",
    "dii": "Domestic institutions (DII)",
    "public_non_institutional": "Public — non-institutional",
    "government": "Government",
    "custodian": "Custodian / depository receipts",
    "non_promoter_non_public": "Non-promoter, non-public",
}


def _delta(now, then):
    if now is None or then is None:
        return None
    return round(now - then, 4)


def summary(symbol: str, quarters: int = 8, names_limit: int = 12) -> dict:
    """
    Who owns this company, how that changed, and where every figure came from.

    The response is deliberately shaped so a caller cannot accidentally draw
    the overlapping categories together: `split` is the decomposition that
    sums to 100, and `public_total` sits outside it, labelled as the parent of
    three of the lines inside it.
    """
    sym = _clean_symbol(symbol)
    out = {
        "symbol": sym,
        "available": False,
        "source": "NSE — shareholding pattern filed under LODR Regulation 31",
        "split": [],
        "history": [],
        "names": {"promoters": [], "public": []},
        "notes": [],
    }
    if not sym:
        out["message"] = "No symbol was given."
        return out
    if not available():
        out["message"] = ("The shareholding reader is not installed on this "
                          "instance (curl_cffi is required to reach NSE).")
        return out

    rows = index(sym)
    if not rows:
        out["message"] = ("No shareholding filing could be read for " + sym +
                          " right now.")
        return out

    want = max(2, min(int(quarters or 8), MAX_PARSE))
    parsed = []
    for row in rows[:want]:
        one = filing(row["xbrl"], period=row["period"], filed=row["filed"],
                     revised=row["revised"])
        if one and one.get("categories"):
            parsed.append(one)
    if not parsed:
        out["message"] = "The filings for " + sym + " could not be read."
        return out

    latest = parsed[0]
    prev = parsed[1] if len(parsed) > 1 else None
    # A year ago means four quarters back, and only if that is really what the
    # row is — a company that skipped a filing must not have a five-quarter gap
    # silently labelled as a year.
    year_ago = None
    if len(parsed) > 4:
        cand = parsed[4]
        try:
            d0 = dt.date.fromisoformat(latest["period"])
            d4 = dt.date.fromisoformat(cand["period"])
            if 300 <= (d0 - d4).days <= 430:
                year_ago = cand
        except Exception:
            year_ago = None

    def cat(rec, key):
        return (rec or {}).get("categories", {}).get(key) or {}

    # A company with no promoter does not file a zero — it omits the line.
    # Read as a gap that is indistinguishable from a parse failure, which it is
    # not: when the filing's own total and public figures both come to 100, the
    # company is saying it has no promoter, and that is worth stating.
    no_promoter = (
        "promoter" not in latest.get("categories", {})
        and abs((cat(latest, "total").get("pct") or 0) - 100) < 0.5
        and abs((cat(latest, "public_total").get("pct") or 0) - 100) < 0.5
    )
    if no_promoter:
        out["notes"].append(
            "This company reports no promoter holding. Its shares are held "
            "entirely by the public, which the filing confirms by putting both "
            "the public total and the grand total at 100%.")

    for key in SPLIT_KEYS:
        now = cat(latest, key)
        if not now or now.get("pct") is None:
            if key == "promoter" and no_promoter:
                out["split"].append({
                    "key": key, "label": LABELS[key], "pct": 0.0,
                    "holders": 0, "shares": 0, "derived": False,
                    "reported_absent": True,
                    "change_qoq": None, "change_yoy": None,
                    "holders_change_qoq": None,
                })
            continue
        out["split"].append({
            "key": key,
            "label": LABELS[key],
            "pct": now.get("pct"),
            "holders": now.get("holders"),
            "shares": now.get("shares"),
            "derived": bool(now.get("derived")),
            "reported_absent": False,
            "change_qoq": _delta(now.get("pct"), cat(prev, key).get("pct")),
            "change_yoy": _delta(now.get("pct"), cat(year_ago, key).get("pct")),
            "holders_change_qoq": _delta(now.get("holders"), cat(prev, key).get("holders")),
        })

    total = cat(latest, "total")
    public = cat(latest, "public_total")
    out["totals"] = {
        "holders": total.get("holders"),
        "holders_change_qoq": _delta(total.get("holders"), cat(prev, "total").get("holders")),
        "holders_change_yoy": _delta(total.get("holders"), cat(year_ago, "total").get("holders")),
        "shares": total.get("shares"),
        "public_total_pct": public.get("pct"),
        "split_sums_to": round(sum(s["pct"] for s in out["split"] if s["pct"] is not None), 2),
    }
    # The filer rounds each line to two decimals, so the parts can miss 100 by
    # a hundredth or two. A miss bigger than that means a category this parser
    # does not know about, and the caller is told rather than shown a chart
    # that quietly does not add up.
    out["totals"]["reconciles"] = abs(out["totals"]["split_sums_to"] - 100) <= 0.15
    if not out["totals"]["reconciles"]:
        out["notes"].append(
            "The categories read from this filing come to %.2f%%, not 100%%. "
            "Some of the holding sits in a category this reader does not yet "
            "break out — treat the split as incomplete."
            % out["totals"]["split_sums_to"])

    for rec in parsed:
        row = {"period": rec.get("period"), "filed": rec.get("filed"),
               "revised": bool(rec.get("revised")), "source": rec.get("source")}
        for key in SPLIT_KEYS:
            c = cat(rec, key)
            if c.get("pct") is not None:
                row[key] = c["pct"]
        row["holders"] = cat(rec, "total").get("holders")
        out["history"].append(row)
    out["history"].reverse()          # oldest first, for charting

    lim = max(1, min(int(names_limit or 12), 40))
    named = latest.get("names") or []
    prev_named = {n["name"].strip().lower(): n.get("pct")
                  for n in (prev or {}).get("names", [])}
    for n in named:
        if n.get("pct") is None:
            continue
        before = prev_named.get(n["name"].strip().lower())
        entry = {
            "name": n["name"],
            "pct": n["pct"],
            "kind": n.get("kind"),
            "change_qoq": _delta(n["pct"], before),
            # A holder absent from the previous filing is not necessarily new:
            # the public table only names holders above 1%, so crossing that
            # line looks identical to buying in. The UI says "new in table".
            "new_in_table": before is None,
        }
        bucket_name = "promoters" if n.get("promoter") else "public"
        if len(out["names"][bucket_name]) < lim:
            out["names"][bucket_name].append(entry)

    if any(s["derived"] for s in out["split"]):
        out["notes"].append(
            "For older quarters the exchange format reported a single "
            "Institutions line. The domestic figure there is the reported "
            "total less foreign institutions, and is marked as derived.")
    out["notes"].append(
        "Public shareholding as the exchange reports it (%s%%) includes "
        "foreign institutions, domestic institutions and non-institutional "
        "holders. The four lines above do not overlap and sum to 100."
        % (public.get("pct") if public.get("pct") is not None else "—"))
    if latest.get("revised"):
        out["notes"].append(
            "The latest filing for this quarter is a revision of an earlier one.")

    out["available"] = True
    out["period"] = latest.get("period")
    out["filed"] = latest.get("filed")
    out["quarters_read"] = len(parsed)
    out["latest_source"] = latest.get("source")
    return out
