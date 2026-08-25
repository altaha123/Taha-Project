"""
social_posts.py — the posting layer for the Social surface.

WHAT THIS IS NOT: an announcement fetcher. announcements.py already does that,
and does it better than my first attempt did. It handles the BSE session, the
scrip master, ISIN -> NSE symbol mapping, day-by-day paging, importance
classification, probe() and diagnose(). None of that is repeated here.

This module takes the rows announcements.feed() already produces and adds the
three things it deliberately does not do:

  1. A plain-English RESTATEMENT of the filing. announcements.py says outright
     in its own note that nothing there is a summary of the filing. This is
     that summary — templated, deterministic, no model in the loop.
  2. A DROP FILTER. announcements.py classifies everything and labels the dull
     ones "Other / low"; it never throws anything away, which is correct for a
     screener. For posting you need the opposite: a hard no on trading-window
     notices and newspaper intimations.
  3. An X POST plus a review queue with approve / skip / posted status.

Two things I got wrong on the first pass, both fixed by deleting my code:

  - I wrote a second BSE fetcher that asked for a DATE RANGE. BSE's endpoint
    accepts a single day; a range returns HTTP 200 with a body of "{}", which
    is indistinguishable from a quiet day. announcements.py has that lesson
    written into a comment above its fetch loop. My fetcher would have
    returned nothing, forever, silently. It is gone.
  - I duplicated symbol resolution. announcements.py maps scrip code to NSE
    symbol through the ISIN master. Mine guessed from a BSE URL slug.

Nothing here imports engine, profiles, archetypes or alerts. It cannot move a
score or a threshold.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import announcements as ann

IST = timezone(timedelta(hours=5, minutes=30))


def _resolve_store_dir() -> str:
    explicit = os.getenv("ALTAHA_SOCIAL_DIR")
    if explicit:
        return explicit
    pit = os.getenv("ALTAHA_PIT_DB")
    if pit and os.path.dirname(pit):
        return os.path.dirname(pit)
    return os.getenv("DATA_DIR") or "/tmp"


STORE_DIR = _resolve_store_dir()
STORE_PATH = os.path.join(STORE_DIR, "social_posts.json")
MAX_KEEP = int(os.getenv("SOCIAL_MAX_KEEP", "1200"))
LOOKBACK_HOURS = int(os.getenv("SOCIAL_LOOKBACK_HOURS", "36"))

_lock = threading.RLock()
_state: Dict[str, Any] = {
    "items": {},
    "counters": {"seen": 0, "dropped": 0, "kept": 0},
    "recent_drops": [],
    "last_build": None,
}
_loaded = False
_mtime = 0.0

ALLOWED_ADJECTIVES = {"largest", "single", "domestic", "international", "consolidated", "standalone"}


# ============================================================================
# 1. THE NOISE FILTER
# ============================================================================
# BSE and NSE together push roughly 1,500-2,000 rows a day. Over 90% is
# compliance plumbing. These patterns kill it. Each one carries the reason so
# /social/status can show you what it threw away and why — if the filter is
# eating something it shouldn't, you will be able to see it rather than guess.

DROP_RULES: List[Tuple[str, str]] = [
    (r"trading\s+window", "trading window closure"),
    (r"closure\s+of\s+trading", "trading window closure"),
    (r"newspaper\s+(publication|advertisement|clipping)", "newspaper publication"),
    (r"publication\s+(of|in)\s+.{0,30}newspaper", "newspaper publication"),
    (r"regulation\s*7\s*\(\s*3\s*\)", "RTA compliance certificate"),
    (r"regulation\s*74\s*\(\s*5\s*\)", "RTA compliance certificate"),
    (r"regulation\s*40\s*\(\s*9\s*\)", "share transfer certificate"),
    (r"regulation\s*76\b", "reconciliation of share capital"),
    (r"reconciliation\s+of\s+share\s+capital", "reconciliation of share capital"),
    (r"certificate\s+under\s+regulation", "routine compliance certificate"),
    (r"compliance\s+certificate", "routine compliance certificate"),
    (r"(loss|duplicate|issue)\s+of\s+share\s+certificate", "duplicate share certificate"),
    (r"letter\s+of\s+confirmation", "duplicate share certificate"),
    (r"investor\s+(meet|presentation|conference)\s+(intimation|schedule)", "investor meet schedule"),
    (r"intimation\s+of\s+(analyst|investor)", "investor meet schedule"),
    (r"schedule\s+of\s+(analyst|investor)", "investor meet schedule"),
    (r"audio\s*(-|\s)?\s*recording", "call recording upload"),
    (r"(transcript|recording)\s+of\s+(the\s+)?(earnings|analyst|investor|conference)", "call transcript"),
    (r"corrigendum\s+to\s+newspaper", "newspaper publication"),
    (r"change\s+in\s+registered\s+office", "administrative"),
    (r"change\s+of\s+(name\s+and\s+)?address", "administrative"),
    (r"appointment\s+of\s+(registrar|rta|share\s+transfer)", "administrative"),
    (r"grievance\s+redressal", "administrative"),
    (r"statement\s+of\s+investor\s+complaints", "administrative"),
    (r"shareholding\s+pattern", "quarterly shareholding filing"),
    (r"corporate\s+governance\s+report", "quarterly governance filing"),
    (r"annual\s+secretarial\s+compliance", "annual compliance filing"),
    (r"(notice|intimation)\s+of\s+record\s+date\s+for\s+(agm|e-?voting)", "AGM logistics"),
    (r"(e-?voting|remote\s+voting)\s+(results?|facility|intimation)", "AGM logistics"),
    (r"proceedings\s+of\s+(the\s+)?(agm|annual\s+general)", "AGM logistics"),
    (r"scrutinizer", "AGM logistics"),
    (r"annual\s+report\s+(for|submission|of)", "annual report upload"),
    (r"notice\s+of\s+(the\s+)?annual\s+general\s+meeting", "AGM logistics"),
    (r"disclosure\s+under\s+regulation\s*30\s*\(\s*(11|12)\s*\)", "clarification on news item"),
    (r"clarification\s+(on|sought|w\.?r\.?t)", "exchange clarification request"),
    (r"price\s+movement", "exchange clarification request"),
    (r"esop|employee\s+stock\s+option.{0,40}allotment", "routine ESOP allotment"),
    (r"listing\s+and\s+trading\s+approval", "routine listing formality"),
    (r"in-?principle\s+approval", "routine listing formality"),
    (r"\bunit\s+of\s+measurement\b", "administrative"),
    (r"\bISIN\b", "administrative"),
]

DROP_COMPILED = [(re.compile(p, re.I), why) for p, why in DROP_RULES]


# ============================================================================
# 2. WHAT ACTUALLY MATTERS
# ============================================================================
# Tier A  — posts on its own merit.
# Tier B  — posts only if a material number was parsed out of it.
# Order matters: first match wins, so the specific rules sit above the generic.

CATEGORY_RULES: List[Dict[str, Any]] = [
    {
        "key": "order_win",
        "label": "Order win",
        "tier": "A",
        "patterns": [
            r"\b(receipt|received|award(ed)?|bagg?ed|secur(ed|ing)|win(s|ning)?)\b.{0,40}\b(orders?|contracts?|loa|letters?\s+of\s+award|work\s+orders?|tenders?)\b",
            r"\borders?\s+(win|book|inflow|received)\b",
            r"\bletters?\s+of\s+(award|intent|acceptance)\b",
        ],
        # A tax demand order is also an "order received". Without this, a GST
        # penalty gets posted as a business win — the single worst thing this
        # pipeline could do. Caught in fixture testing; keep it.
        # NOTE: do not add "sebi" here. Nearly every filing opens with
        # "pursuant to Regulation 30 of SEBI (LODR) Regulations, 2015", so
        # excluding on it silently kills every order win. Learned the hard way.
        "exclude": [
            r"\b(demand\s+(order|notice)|penalty|show\s+cause|adjudicat|prosecut)\w*",
            r"\b(gst|income\s+tax|customs|excise\s+duty|assessment\s+order)\b",
            r"\b(garnishee|attachment\s+order|recovery\s+proceeding)\b",
        ],
    },
    {
        "key": "credit_rating",
        "label": "Credit rating",
        "tier": "A",
        "patterns": [r"credit\s+rating", r"\b(crisil|icra|care\s+ratings?|india\s+ratings|brickwork|acuite)\b"],
    },
    {
        "key": "pledge",
        "label": "Promoter pledge",
        "tier": "A",
        "patterns": [
            r"\b(pledg|encumbr)\w*",
            r"regulation\s*31\s*\(\s*1\s*\)",
            r"\brelease\s+of\s+(pledge|shares)\b",
        ],
    },
    {
        "key": "board_change",
        "label": "Leadership change",
        "tier": "A",
        "patterns": [
            r"\b(resignation|cessation|appointment|re-?appointment|demise)\b.{0,60}\b(managing\s+director|whole[-\s]?time|chief\s+executive|chief\s+financial|ceo|cfo|md\b|chairman|auditor|company\s+secretary)\b",
            r"\b(managing\s+director|chief\s+executive|chief\s+financial|statutory\s+auditor)\b.{0,40}\b(resign|appoint|step\s+down|cease)",
            r"\bresignation\s+of\s+(statutory\s+)?auditor",
        ],
    },
    {
        "key": "fundraise",
        "label": "Fundraise",
        "tier": "A",
        "patterns": [
            r"\b(qip|qualified\s+institution)", r"preferential\s+(issue|allotment)",
            r"\brights\s+issue\b", r"\b(ncd|non-?convertible\s+deben)",
            r"\braising?\s+of\s+funds?\b", r"\bfund\s+rais", r"\bissue\s+of\s+(equity\s+)?shares?\s+on\s+a?\s*preferential",
            r"\bconvertible\s+warrants?\b",
        ],
    },
    {
        "key": "ma",
        "label": "M&A / restructuring",
        "tier": "A",
        "patterns": [
            r"scheme\s+of\s+(arrangement|amalgamation|merger|demerger)",
            r"\b(acquisition|acquire[sd]?|acquiring)\b", r"\bdemerger\b", r"\bamalgamation\b",
            r"\bslump\s+sale\b", r"\bdivestment\b", r"\bstake\s+(sale|purchase)\b",
            r"\b(joint\s+venture|jv\s+agreement)\b", r"\bshare\s+purchase\s+agreement\b",
            r"\bopen\s+offer\b", r"\bsubsidiar(y|ies)\b.{0,30}\b(incorporat|acquisition|sale)",
        ],
    },
    {
        "key": "buyback",
        "label": "Buyback",
        "tier": "A",
        "patterns": [r"\bbuy-?back\b"],
    },
    {
        "key": "capex",
        "label": "Capex / expansion",
        "tier": "A",
        "patterns": [
            r"\b(capex|capital\s+expenditure)\b",
            r"\b(commission(ing|ed)?|expansion|new\s+plant|greenfield|brownfield|capacity\s+(addition|expansion|enhancement))\b",
            r"\bsetting\s+up\s+(of\s+)?(a\s+)?(new\s+)?(plant|facility|unit)",
        ],
    },
    {
        "key": "disruption",
        "label": "Operations disruption",
        "tier": "A",
        "patterns": [
            r"\b(fire|explosion|accident|mishap|flood|breakdown)\b",
            r"\b(shutdown|shut\s+down|suspension\s+of\s+operations|plant\s+closure|lock-?out|strike)\b",
            r"\bforce\s+majeure\b", r"\bcyber\s*(-|\s)?(security\s+)?(incident|attack|breach)\b",
        ],
    },
    {
        "key": "regulatory",
        "label": "Regulatory action",
        "tier": "A",
        "patterns": [
            r"\b(penalt(y|ies)|fine[sd]?|show\s+cause|adjudicat|prosecution|search\s+and\s+seiz|raid|summons)\b",
            r"\b(gst|income\s+tax|sebi|rbi|cci|enforcement\s+directorate|nclt|nclat)\b.{0,50}\b(order|notice|penalty|demand|action)\b",
            r"regulation\s*30.{0,30}\b(tax\s+demand|penalty)",
            r"\bdemand\s+(orders?|notices?)\b",
        ],
    },
    {
        "key": "insolvency",
        "label": "Insolvency",
        "tier": "A",
        "patterns": [r"\b(insolvency|ibc\b|cirp\b|liquidation|resolution\s+plan|moratorium)\b"],
    },
    {
        "key": "results",
        "label": "Results",
        "tier": "A",
        "patterns": [
            r"\b(un-?)?audited\s+(standalone|consolidated)?\s*financial\s+results?\b",
            r"\bfinancial\s+results?\s+for\s+the\s+(quarter|year|half)",
            r"\bquarterly\s+results?\b",
        ],
    },
    {
        "key": "business_update",
        "label": "Business update",
        "tier": "A",
        "patterns": [
            r"\b(quarterly|monthly)\s+(business|operational|sales)\s+update\b",
            r"\b(sales|production|offtake|dispatch)\s+(figures?|volume|update|data)\s+for\b",
            r"\bpre-?quarter\s+update\b",
        ],
    },
    {
        "key": "dividend",
        "label": "Dividend",
        "tier": "B",
        "patterns": [r"\bdividend\b"],
    },
    {
        "key": "bonus_split",
        "label": "Bonus / split",
        "tier": "A",
        "patterns": [r"\bbonus\s+(issues?|shares?)", r"\b(stock\s+)?split\b", r"\bsub-?division\s+of\s+(equity\s+)?shares?\b"],
    },
    {
        "key": "related_party",
        "label": "Related party",
        "tier": "B",
        "patterns": [r"related\s+part(y|ies)", r"\bloan\s+to\s+(subsidiary|related)"],
    },
]

for _r in CATEGORY_RULES:
    _r["compiled"] = [re.compile(p, re.I) for p in _r["patterns"]]
    _r["excluded"] = [re.compile(p, re.I) for p in _r.get("exclude", [])]


# ============================================================================
# 3. NUMBER EXTRACTION
# ============================================================================

_NUM = r"(?:\d{1,3}(?:,\d{2,3})*|\d+)(?:\.\d+)?"

MONEY_PATTERNS = [
    (re.compile(r"(?:rs\.?|inr|₹)\s*(" + _NUM + r")\s*(crore|cr\b|crores)", re.I), 1.0),
    (re.compile(r"(?:rs\.?|inr|₹)\s*(" + _NUM + r")\s*(lakhs?|lacs?)", re.I), 0.01),
    (re.compile(r"(?:rs\.?|inr|₹)\s*(" + _NUM + r")\s*(million|mn\b)", re.I), 0.1),
    (re.compile(r"(?:rs\.?|inr|₹)\s*(" + _NUM + r")\s*(billion|bn\b)", re.I), 100.0),
    (re.compile(r"(" + _NUM + r")\s*(crore|crores|cr)\b", re.I), 1.0),
    (re.compile(r"(?:usd|us\$|\$)\s*(" + _NUM + r")\s*(million|mn\b)", re.I), 8.7),   # ~83/USD
    (re.compile(r"(?:usd|us\$|\$)\s*(" + _NUM + r")\s*(billion|bn\b)", re.I), 8700.0),
]

PCT_RE = re.compile(r"(" + _NUM + r")\s*(?:%|per\s*cent)", re.I)
DATE_RE = re.compile(
    r"\b(\d{1,2})[\s\-/](jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-/,]*(\d{2,4})\b", re.I
)

LEGALESE = [
    (re.compile(r"pursuant\s+to\s+(the\s+provisions\s+of\s+)?regulation\s*[\d\(\)\s,and]+of\s+.{0,90}?regulations,?\s*\d{4}[,\.]?", re.I), ""),
    (re.compile(r"pursuant\s+to\s+regulation\s*[\d\(\)\s,and]+", re.I), ""),
    (re.compile(r"in\s+(terms|compliance)\s+of\s+regulation\s*[\d\(\)\s,and]+", re.I), ""),
    (re.compile(r"we\s+(would\s+like\s+to|wish\s+to|hereby)\s+(inform|intimate|submit|notify)\s+(you\s+)?that\s*", re.I), ""),
    (re.compile(r"this\s+is\s+to\s+inform\s+(you\s+)?that\s*", re.I), ""),
    (re.compile(r"(kindly|please)\s+(take\s+the\s+same\s+on\s+record|note\s+the\s+same|acknowledge).{0,60}", re.I), ""),
    (re.compile(r"you\s+are\s+requested\s+to\s+take\s+.{0,40}on\s+record.{0,40}", re.I), ""),
    (re.compile(r"\bthe\s+(said\s+)?(intimation|disclosure)\s+is\s+(enclosed|attached).{0,40}", re.I), ""),
    (re.compile(r"\b(dear\s+sir|madam|sir/madam|respected\s+sir)[,\s/]*", re.I), ""),
    (re.compile(r"\bref[:\.]\s*(scrip|symbol)\s*code.{0,30}", re.I), ""),
    (re.compile(r"\bsub(ject)?\s*[:\-]\s*", re.I), ""),
    (re.compile(r"\bthe\s+company\s+hereby\s+", re.I), "the company "),
    (re.compile(r"\bintimation\s+(regarding|of|under)\b", re.I), ""),
    (re.compile(r"\bdisclosure\s+under\s+regulation\s*[\d\(\)\s]+", re.I), ""),
    (re.compile(r"\bBSE\s+Ltd.{0,60}Dalal\s+Street.{0,40}", re.I), ""),
    (re.compile(r"\bNational\s+Stock\s+Exchange\s+of\s+India.{0,60}", re.I), ""),
    (re.compile(r"\s{2,}"), " "),
]


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    for rx, rep in LEGALESE:
        s = rx.sub(rep, s)
    s = re.sub(r"\s+", " ", s).strip(" .,;:-")
    if s:
        s = s[0].upper() + s[1:]
    return s


def extract_money_cr(text: str) -> Optional[float]:
    """Largest rupee figure in the text, normalised to crore. Largest, because the
    headline number in a filing is almost always the biggest one in it."""
    best = None
    for rx, mult in MONEY_PATTERNS:
        for m in rx.finditer(text or ""):
            try:
                val = float(m.group(1).replace(",", "")) * mult
            except ValueError:
                continue
            if val <= 0 or val > 5_000_000:
                continue
            if best is None or val > best:
                best = val
    return best


def fmt_cr(v: Optional[float]) -> str:
    if v is None:
        return ""
    if v >= 100000:
        return f"Rs {v/100000:,.2f} lakh cr"
    if v >= 1:
        return f"Rs {v:,.0f} cr" if v >= 10 else f"Rs {v:,.1f} cr"
    return f"Rs {v*100:,.0f} lakh"


def extract_counterparty(text: str) -> Optional[str]:
    """Who the order/contract is from. Conservative — returns None rather than a guess."""
    pats = [
        r"\bfrom\s+((?:M/s\.?\s+)?[A-Z][\w&\.\-]*(?:\s+[A-Z][\w&\.\-]*){0,5}(?:\s+(?:Ltd|Limited|Corporation|Corp|Inc|LLP|Board|Authority|Railways?|Nigam|Ministry|Department))\.?)",
        r"\bby\s+((?:M/s\.?\s+)?[A-Z][\w&\.\-]*(?:\s+[A-Z][\w&\.\-]*){0,5}(?:\s+(?:Ltd|Limited|Corporation|Nigam|Board|Authority|Railways?))\.?)",
        r"\b(NTPC|NHPC|ONGC|IOCL|BPCL|HPCL|GAIL|SAIL|BHEL|NHAI|DMRC|DRDO|ISRO|Indian Railways|Coal India|Power Grid|RVNL|IRCON)\b",
    ]
    for p in pats:
        m = re.search(p, text or "")
        if m:
            name = m.group(1).strip(" .,")
            if 3 < len(name) < 70:
                return name
    return None


def extract_dates(text: str) -> List[str]:
    out = []
    for m in DATE_RE.finditer(text or ""):
        out.append(f"{m.group(1)} {m.group(2).title()} {m.group(3)}")
    return out[:2]

# ============================================================================
# 4. CLASSIFY
# ============================================================================

def classify(raw_text: str) -> Dict[str, Any]:
    t = raw_text or ""
    for rx, why in DROP_COMPILED:
        if rx.search(t):
            return {"keep": False, "reason": why, "key": None, "label": None, "tier": None}
    for rule in CATEGORY_RULES:
        if any(rx.search(t) for rx in rule["excluded"]):
            continue
        for rx in rule["compiled"]:
            if rx.search(t):
                return {"keep": True, "reason": None, "key": rule["key"],
                        "label": rule["label"], "tier": rule["tier"]}
    return {"keep": False, "reason": "no category matched", "key": None, "label": None, "tier": None}

# ============================================================================
# 5. PLAIN-LANGUAGE RESTATEMENT
# ============================================================================
# One template per category. Each fills only from parsed facts. If a fact is
# missing the clause is dropped, never invented and never reordered.

def _company_short(name: str) -> str:
    n = re.sub(r"\s*\b(Limited|Ltd\.?|Private|Pvt\.?|Corporation|Corp\.?)\b\.?", "", name or "", flags=re.I)
    return re.sub(r"\s+", " ", n).strip(" .,-") or (name or "").strip()


def restate(rec: Dict[str, Any]) -> Dict[str, str]:
    """Returns {'headline', 'body', 'figures'} — plain English, no interpretation."""
    key = rec.get("category_key")
    company = _company_short(rec.get("company", ""))
    text = rec.get("clean_text") or rec.get("headline") or ""
    money = rec.get("money_cr")
    cp = rec.get("counterparty")
    dates = rec.get("dates") or []
    pct = rec.get("pct")

    money_s = fmt_cr(money)
    figures: List[str] = []
    if money_s:
        figures.append(money_s)
    if rec.get("mcap_pct"):
        figures.append(f"{rec['mcap_pct']:.0f}% of market cap")

    def tail() -> str:
        return f" Timeline given: {dates[0]}." if dates else ""

    if key == "order_win":
        head = f"{company} has won an order"
        if money_s:
            head += f" worth {money_s}"
        if cp:
            head += f" from {cp}"
        body = head + "."
        if rec.get("mcap_pct"):
            body += f" That is about {rec['mcap_pct']:.0f}% of the company's current market value."
        body += tail()

    elif key == "credit_rating":
        direction = ""
        if re.search(r"\b(upgrad|revis\w+\s+upward|improve)", text, re.I):
            direction = "raised"
        elif re.search(r"\b(downgrad|revis\w+\s+downward|reduc)", text, re.I):
            direction = "lowered"
        elif re.search(r"\breaffirm|retain|maintain", text, re.I):
            direction = "left unchanged"
        agency = None
        am = re.search(r"\b(CRISIL|ICRA|CARE Ratings|CARE|India Ratings|Brickwork|Acuite)\b", text, re.I)
        if am:
            agency = am.group(1)
        rating = None
        rm = re.search(
            r"\b((?:CRISIL|ICRA|CARE|IND)?\s*"
            r"(?:AAA|AA|A1|A2|A3|A|BBB|BB|B|C|D)[+-]?"
            r"(?:\s*/\s*(?:Stable|Positive|Negative|Watch|Developing))?)(?![A-Za-z])",
            text)
        if rm:
            rating = rm.group(1)
        head = f"{company}'s credit rating"
        if agency:
            head += f" from {agency}"
        head += f" was {direction}" if direction else " was reviewed"
        if rating:
            head += f", now {rating}"
        body = head + "."

    elif key == "pledge":
        released = bool(re.search(r"\b(releas|revok|invoke\w*\s+revers|de-?pledg)", text, re.I))
        created = bool(re.search(r"\b(creat|invok)", text, re.I))
        what = "released pledged shares" if released and not created else (
            "pledged more shares" if created else "reported a change in pledged shares")
        body = f"A promoter of {company} has {what}."
        if pct:
            body += f" The filing puts the shares involved at {pct}% of the company."

    elif key == "board_change":
        who = None
        wm = re.search(r"\b(Managing Director|Chief Executive Officer|Chief Financial Officer|Whole[- ]?time Director|Chairman|Company Secretary|Statutory Auditors?)\b", text, re.I)
        if wm:
            who = wm.group(1)
        leaving = bool(re.search(r"\b(resign|cessation|step\s+down|ceas|demise|retire)", text, re.I))
        verb = "is leaving" if leaving else "has been appointed"
        role = f"The {who}" if who else "A senior officer"
        body = f"{role} of {company} {verb}."
        nm = re.search(r"\b(?:Mr\.?|Ms\.?|Mrs\.?|Shri|Smt\.?)\s+([A-Z][\w\.\-]*(?:\s+[A-Z][\w\.\-]*){0,3})", text)
        if nm:
            body = body[:-1] + f" ({nm.group(1).strip()})."
        body += tail()

    elif key == "fundraise":
        instrument = "shares"
        if re.search(r"\bqip|qualified\s+institution", text, re.I):
            instrument = "shares to institutions (QIP)"
        elif re.search(r"preferential", text, re.I):
            instrument = "shares to selected investors (preferential issue)"
        elif re.search(r"rights\s+issue", text, re.I):
            instrument = "shares to existing shareholders (rights issue)"
        elif re.search(r"\bncd|deben", text, re.I):
            instrument = "debentures"
        elif re.search(r"warrant", text, re.I):
            instrument = "convertible warrants"
        approved = "approved" if re.search(r"\b(approv|board\s+has)", text, re.I) else "proposed"
        body = f"{company}'s board {approved} raising money by issuing {instrument}"
        body += f" of up to {money_s}." if money_s else "."

    elif key == "ma":
        if re.search(r"demerger", text, re.I):
            body = f"{company} is splitting off part of its business into a separate company (demerger)."
        elif re.search(r"scheme\s+of\s+(arrangement|amalgamation|merger)", text, re.I):
            body = f"{company} has filed a merger or restructuring scheme."
        elif re.search(r"\bopen\s+offer", text, re.I):
            body = f"An open offer has been made for shares of {company}."
        elif re.search(r"\bacquir|acquisition|stake\s+purchase", text, re.I):
            body = f"{company} is buying a business or a stake in one"
            body += f" for {money_s}." if money_s else "."
        elif re.search(r"\b(divest|slump\s+sale|stake\s+sale)", text, re.I):
            body = f"{company} is selling a business or a stake"
            body += f" for {money_s}." if money_s else "."
        else:
            body = f"{company} has announced a corporate restructuring step."
        if pct and "stake" in body:
            body += f" Stake involved: {pct}%."

    elif key == "buyback":
        body = f"{company}'s board has taken up a share buyback"
        body += f" of up to {money_s}." if money_s else "."
        price = re.search(r"price\s+of\s+(?:rs\.?|₹)\s*(" + _NUM + r")", text, re.I)
        if price:
            body += f" Buyback price: Rs {price.group(1)} per share."

    elif key == "capex":
        body = f"{company} is expanding capacity or setting up a new facility"
        body += f", with spending of {money_s}." if money_s else "."
        if rec.get("mcap_pct"):
            body += f" That is about {rec['mcap_pct']:.0f}% of its market value."
        body += tail()

    elif key == "disruption":
        what = "a fire or accident" if re.search(r"fire|explosion|accident|mishap", text, re.I) else (
            "a cyber incident" if re.search(r"cyber", text, re.I) else "a halt in operations")
        where = "at one of its plants"
        if re.search(r"cyber", text, re.I):
            where = "affecting its systems"
        body = f"{company} has reported {what} {where}."
        if re.search(r"no\s+(loss\s+of\s+life|injur|casualt)", text, re.I):
            body += " The filing states there was no loss of life."
        if re.search(r"(suspend|halt|stopp?ed)", text, re.I):
            body += " Operations at the affected unit are suspended."
        if money_s:
            body += f" Loss or damage stated in the filing: {money_s}."

    elif key == "regulatory":
        auth = "a regulator"
        am = re.search(r"\b(GST|Income Tax|Customs|Excise|SEBI|RBI|CCI|NCLT|NCLAT|Enforcement Directorate|Competition Commission)\b", text, re.I)
        if am:
            auth = "the " + am.group(1).upper() if len(am.group(1)) <= 5 else "the " + am.group(1).title()
            auth += " authorities" if am.group(1).lower() in ("gst", "income tax", "customs", "excise") else ""
        if re.search(r"show\s+cause", text, re.I):
            kind = "a show-cause notice"
        elif re.search(r"demand", text, re.I):
            # "demand order ... including interest and penalty" — the demand is
            # the headline fact, the penalty is a component of it.
            kind = "a tax demand"
        elif re.search(r"\bpenalt|\bfine\b", text, re.I):
            kind = "a penalty"
        else:
            kind = "an order"
        body = f"{company} has received {kind} from {auth}"
        body += f" for {money_s}." if money_s else "."
        if re.search(r"\b(appeal|contest|challeng|rectif)", text, re.I):
            body += " The company says it will contest it."

    elif key == "insolvency":
        body = f"{company} has filed an update on an insolvency or resolution process."

    elif key == "results":
        period = "the quarter"
        pm = re.search(r"\b(quarter|half\s*year|year)\s+(and\s+\w+\s+)?ended\s+([A-Za-z]+\s*\d{0,4}|\d{1,2}[\.\-/]\d{1,2}[\.\-/]\d{2,4})", text, re.I)
        if pm:
            period = f"the {pm.group(1).lower()} ended {pm.group(3)}"
        body = f"{company} has filed its results for {period}."

    elif key == "business_update":
        body = f"{company} has published an operating update"
        if pct:
            what = "sales" if re.search(r"\bsales|revenue", text, re.I) else "volumes"
            direction = "down" if re.search(r"\b(decline|fell|de-?grow|drop)", text, re.I) else "up"
            body += f". It reports {what} {direction} {pct:g}% for the period."
        else:
            body += " with sales or production numbers."

    elif key == "dividend":
        per_share = re.search(r"(?:rs\.?|₹)\s*(" + _NUM + r")\s*(?:per\s+(?:equity\s+)?share)", text, re.I)
        kind = "final" if re.search(r"\bfinal\b", text, re.I) else ("interim" if re.search(r"interim", text, re.I) else "")
        body = f"{company} has declared {(kind + ' ') if kind else ''}dividend"
        body += f" of Rs {per_share.group(1)} per share." if per_share else "."
        if dates:
            body += f" Record date: {dates[0]}."

    elif key == "bonus_split":
        if re.search(r"bonus", text, re.I):
            ratio = re.search(r"(\d+)\s*:\s*(\d+)", text)
            body = f"{company} has announced a bonus issue"
            body += f" in the ratio {ratio.group(1)}:{ratio.group(2)}." if ratio else "."
        else:
            body = f"{company} has announced a split of its shares into smaller face value."

    elif key == "related_party":
        body = f"{company} has disclosed a transaction with a related party"
        body += f" of {money_s}." if money_s else "."

    else:
        body = clean_text(rec.get("headline", "")) or f"{company} has filed an announcement."

    headline = f"{company} — {rec.get('category_label') or 'Filing'}"
    return {"headline": headline, "body": body.strip(), "figures": " · ".join(figures)}

# ============================================================================
# 6. X POST BUILDER
# ============================================================================

X_LIMIT = 280
TAGS = {
    "order_win": "Order win", "credit_rating": "Rating", "pledge": "Pledge",
    "board_change": "Leadership", "fundraise": "Fundraise", "ma": "M&A",
    "buyback": "Buyback", "capex": "Capex", "disruption": "Operations",
    "regulatory": "Regulatory", "insolvency": "Insolvency", "results": "Results",
    "business_update": "Update", "dividend": "Dividend", "bonus_split": "Corporate action",
    "related_party": "Related party",
}


def build_x_post(rec: Dict[str, Any]) -> str:
    """Assembles the post and trims to 280 by dropping optional lines from the
    bottom up, never by cutting a sentence in half."""
    sym = rec.get("symbol") or ""
    tag = TAGS.get(rec.get("category_key"), "Filing")
    r = rec.get("restated") or {}
    body = r.get("body", "")
    figs = r.get("figures", "")
    when = rec.get("time_ist", "")
    ex = rec.get("exchange", "")

    ticker = f"#{sym}" if sym and re.fullmatch(r"[A-Z0-9&\-]{1,15}", sym) else ""
    lines = [f"{ticker} · {tag}".strip(" ·")]
    lines.append("")
    lines.append(body)
    optional = []
    if figs and figs not in body:
        optional.append(("figs", f"\n{figs}"))
    optional.append(("src", f"\nSource: {ex} filing{(', ' + when) if when else ''}"))

    def assemble(extra):
        return "\n".join(lines) + "".join(x[1] for x in extra)

    for drop in range(len(optional) + 1):
        candidate = assemble(optional[: len(optional) - drop] if drop else optional)
        if len(candidate) <= X_LIMIT:
            return candidate.strip()

    hard = f"{ticker} · {tag}\n\n{body}"
    if len(hard) > X_LIMIT:
        cut = hard[: X_LIMIT - 1]
        cut = cut[: cut.rfind(" ")] if " " in cut else cut
        hard = cut.rstrip(" ,.;") + "…"
    return hard.strip()

# ============================================================================
# 8. MARKET CAP CONTEXT (optional, Dhan-first)
# ============================================================================
# "Rs 450 cr order" means nothing on its own. "Rs 450 cr, about 12% of market
# value" is the whole point. This is arithmetic on two published numbers, so it
# stays on the factual side of the line.

def _market_cap_cr(symbol: str) -> Optional[float]:
    if not symbol:
        return None
    try:
        import dhan_source  # type: ignore
        for fn in ("market_cap_cr", "get_market_cap"):
            f = getattr(dhan_source, fn, None)
            if callable(f):
                v = f(symbol)
                if v:
                    return float(v)
    except Exception:
        pass
    return None


# ============================================================================
# FACT SUFFICIENCY — the fix for confidently wrong restatements
# ============================================================================
# The mistake in the first version: I wrote the templates for the full text of
# a filing, then fed them BSE's NEWSSUB field, which is frequently nothing but
# "Announcement under Regulation 30 (LODR)-Press Release / Media Release".
#
# A template given no facts still produces a fluent sentence. "X has won an
# order" from a headline that never said so is not a small error — it is a
# false statement about a listed company, published under Taha's name.
#
# So each category now declares what it must SEE before it is allowed to
# assert anything. If the evidence is not in the text, the restatement falls
# back to the exchange's own headline, verbatim, and the row is marked
# needs_pdf. Fewer confident cards, none of them invented.

REQUIRED_EVIDENCE: Dict[str, List[str]] = {
    "order_win":       [r"\b(orders?|contracts?|loa|letters?\s+of\s+(award|intent|acceptance)|work\s+orders?|tenders?)\b"],
    "credit_rating":   [r"\b(upgrad|downgrad|reaffirm|revis|assign|withdraw|rating\s+of|AAA|AA|BBB|\bA[+-]?\b)"],
    "pledge":          [r"\b(pledg|encumbr|invok|releas)"],
    "board_change":    [r"\b(resign|cessation|appoint|re-?appoint|demise|retire|step\s+down|ceas)"],
    "fundraise":       [r"\b(qip|preferential|rights\s+issue|ncd|deben|warrant|rais\w*\s+of\s+fund|fund\s+rais|issue\s+of\s+(equity\s+)?shares?)"],
    "ma":              [r"\b(scheme\s+of|acquir|acquisition|demerger|amalgamat|slump\s+sale|divest|stake|joint\s+venture|open\s+offer)"],
    "buyback":         [r"\bbuy-?back\b"],
    "capex":           [r"\b(capex|capital\s+expenditure|expansion|new\s+plant|greenfield|brownfield|capacity|commission|setting\s+up)"],
    "disruption":      [r"\b(fire|explosion|accident|mishap|shutdown|shut\s+down|suspension|closure|lock-?out|strike|force\s+majeure|cyber)"],
    "regulatory":      [r"\b(penalt|fine|show\s+cause|demand|adjudicat|prosecut|search|seiz|order\s+(from|by)|notice)"],
    "insolvency":      [r"\b(insolvency|ibc|cirp|liquidation|resolution\s+plan|moratorium)"],
    "results":         [r"\b(financial\s+results?|quarterly\s+results?|audited|un-?audited)"],
    "business_update": [r"\b(business|operational|sales|production|offtake|dispatch)\s+(update|figures?|volume|data)|\b(sales|production)\b.{0,20}\d"],
    "dividend":        [r"\bdividend\b"],
    "bonus_split":     [r"\b(bonus|split|sub-?division)\b"],
    "related_party":   [r"\brelated\s+part(y|ies)\b"],
}
REQUIRED_C = {k: [re.compile(p, re.I) for p in v] for k, v in REQUIRED_EVIDENCE.items()}

# Headlines that are pure envelope — the filing exists, its content does not
# appear in the text we were given.
ENVELOPE_ONLY = re.compile(
    r"^\s*(announcement|disclosure|intimation|submission|update|general\s+update)"
    r"[\s\-–:]*(under|pursuant|of|regarding)?[\s\-–:]*"
    r"(regulation\s*\d+[\s\(\)\d]*)?"
    r"[\s\-–:]*(\(?lodr\)?)?[\s\-–:]*"
    r"(press\s+release|media\s+release|newspaper)?\s*$", re.I)


def evidence_ok(rec: Dict[str, Any], text: str) -> Tuple[bool, str]:
    """Is the fact this template is about to assert actually present?"""
    key = rec.get("category_key")
    if ENVELOPE_ONLY.match((rec.get("headline") or "").strip()):
        return False, "headline is a Regulation 30 envelope with no content"
    rules = REQUIRED_C.get(key)
    if not rules:
        return True, ""
    if not any(rx.search(text) for rx in rules):
        return False, f"nothing in the headline evidences a {key.replace('_', ' ')}"
    # Categories whose whole point is a number are not worth asserting without one.
    if key in ("order_win", "capex", "buyback", "fundraise") and rec.get("money_cr") is None:
        return False, "no amount given in the headline"
    if key == "dividend" and not rec.get("per_share") and rec.get("money_cr") is None:
        return False, "no dividend amount given in the headline"
    return True, ""


# ============================================================================
# BUILD — read announcements.feed(), add restatement + post, store
# ============================================================================

def _digest(rec: Dict[str, Any]) -> str:
    base = f"{rec.get('symbol') or rec.get('company')}|{(rec.get('headline') or '')[:160]}"
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d.get("items"), dict):
                _state["items"] = d["items"]
                _state["counters"] = d.get("counters", _state["counters"])
        except Exception:
            pass


def _save() -> None:
    with _lock:
        if len(_state["items"]) > MAX_KEEP:
            ordered = sorted(_state["items"].items(),
                             key=lambda kv: kv[1].get("ingested_at", ""), reverse=True)
            _state["items"] = dict(ordered[:MAX_KEEP])
        try:
            os.makedirs(STORE_DIR, exist_ok=True)
            tmp = STORE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"items": _state["items"], "counters": _state["counters"]}, fh)
            os.replace(tmp, STORE_PATH)
            globals()['_mtime'] = os.path.getmtime(STORE_PATH)
        except Exception:
            pass


def process(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One row from announcements.feed()['rows'] -> a postable record, or None.

    The input already carries symbol, company, headline, category, importance,
    pdf and timestamp. This adds the drop filter, the parsed numbers, the
    restatement and the post.
    """
    blob = " ".join(str(row.get(k) or "") for k in ("headline", "category", "exchange_category"))
    verdict = classify(blob)
    _state["counters"]["seen"] += 1

    if not verdict["keep"]:
        _state["counters"]["dropped"] += 1
        _state["recent_drops"] = ([{"company": row.get("company"),
                                    "headline": (row.get("headline") or "")[:110],
                                    "reason": verdict["reason"]}] + _state["recent_drops"])[:60]
        return None

    money = extract_money_cr(blob)
    pctm = PCT_RE.search(blob)
    per_share = re.search(r"(?:rs\.?|₹)\s*(" + _NUM + r")\s*per\s+(?:equity\s+)?share", blob, re.I)

    when = None
    try:
        when = datetime.fromisoformat(row["at"]).astimezone(IST) if row.get("at") else None
    except Exception:
        when = None

    rec: Dict[str, Any] = {
        "id": "",
        "exchange": "BSE",
        "symbol": row.get("symbol") or "",
        "scrip_code": row.get("scrip_code") or "",
        "company": row.get("company") or "",
        "headline": row.get("headline") or "",
        "clean_text": clean_text(blob)[:1200],
        "category_key": verdict["key"],
        "category_label": verdict["label"],
        "tier": verdict["tier"],
        # carried straight through from announcements.py — its keyword rules,
        # not a second opinion from mine
        "ann_category": row.get("category"),
        "ann_importance": row.get("importance"),
        "money_cr": money,
        "pct": float(pctm.group(1).replace(",", "")) if pctm else None,
        "per_share": per_share.group(1) if per_share else None,
        "counterparty": extract_counterparty(blob),
        "dates": extract_dates(blob),
        "pdf": row.get("pdf") or "",
        "time_ist": when.strftime("%d %b, %H:%M IST") if when else "",
        "ingested_at": datetime.now(IST).isoformat(timespec="seconds"),
        "status": "pending",
        "mcap_pct": None,
    }

    if money and rec["symbol"]:
        mc = _market_cap_cr(rec["symbol"])
        if mc and mc > 0:
            share = 100.0 * money / mc
            if 0.5 <= share <= 400:
                rec["mcap_pct"] = share

    if rec["tier"] == "B" and money is None and rec["pct"] is None and not rec["per_share"]:
        _state["counters"]["dropped"] += 1
        return None

    ok, why = evidence_ok(rec, blob)
    rec["evidence_ok"] = ok
    rec["evidence_note"] = why
    if ok:
        rec["restated"] = restate(rec)
    else:
        # No invention. The exchange's own words, and a flag to go read the PDF.
        rec["restated"] = {
            "headline": f"{_company_short(rec['company'])} — filing",
            "body": rec["headline"],
            "figures": "",
        }
        rec["status"] = "needs_pdf"
    rec["x_post"] = build_x_post(rec) if ok else ""
    rec["ig_caption"] = build_ig_caption(rec) if ok else ""
    rec["id"] = _digest(rec)
    _state["counters"]["kept"] += 1
    return rec


def build(limit: int = 300, refresh: bool = False) -> Dict[str, Any]:
    """Pull the latest rows from announcements.py and turn the postable ones
    into drafts. Safe to call often — everything is deduped by digest."""
    _load()
    if refresh:
        try:
            ann.poll_if_stale(background=False)
        except Exception:
            pass
    try:
        data = ann.feed(limit=limit, min_importance="low")
    except Exception as e:
        return {"added": 0, "error": f"{type(e).__name__}: {e}"}

    added = 0
    for row in data.get("rows", []):
        rec = process(row)
        if not rec:
            continue
        with _lock:
            if rec["id"] in _state["items"]:
                continue
            _state["items"][rec["id"]] = rec
            added += 1
    with _lock:
        _state["last_build"] = datetime.now(IST).isoformat(timespec="seconds")
    _save()
    return {"added": added, "scanned": len(data.get("rows", [])),
            "source_last_poll": data.get("last_poll"),
            "source_error": data.get("error"),
            "counters": dict(_state["counters"])}



def _reload_if_changed() -> None:
    """Re-read the store when the file on disk is newer than what we hold.

    Why this is needed: _load() set a _loaded flag and never looked at the file
    again. If Render runs uvicorn with more than one worker — and the default
    for a paid instance often is — then each worker is a separate process with
    its own memory. The poller lives in worker A. A request served by worker B
    reads B's copy, which was loaded once at first request and never refreshed.
    Result: the feed populates once and then appears frozen forever, which is
    exactly the symptom.

    Checking mtime costs one stat call and makes the behaviour identical
    whether the app runs on one worker or six.
    """
    global _mtime
    try:
        m = os.path.getmtime(STORE_PATH)
    except OSError:
        return
    if m <= _mtime:
        return
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d.get("items"), dict):
            with _lock:
                _state["items"] = d["items"]
                _state["counters"] = d.get("counters", _state["counters"])
                _mtime = m
    except Exception:
        pass


def feed(limit: int = 60, status: Optional[str] = None,
         category: Optional[str] = None) -> List[Dict[str, Any]]:
    _load()
    _reload_if_changed()
    with _lock:
        items = list(_state["items"].values())
    cutoff = datetime.now(IST) - timedelta(hours=LOOKBACK_HOURS)

    def fresh(r):
        try:
            return datetime.fromisoformat(r.get("ingested_at", "")) >= cutoff
        except Exception:
            return True

    items = [r for r in items if fresh(r)]
    if status:
        items = [r for r in items if r.get("status") == status]
    if category:
        items = [r for r in items if r.get("category_key") == category]
    items.sort(key=lambda r: r.get("ingested_at", ""), reverse=True)
    return items[:limit]


def set_status(item_id: str, status: str, x_post: Optional[str] = None) -> Optional[Dict[str, Any]]:
    _load()
    with _lock:
        rec = _state["items"].get(item_id)
        if not rec:
            return None
        rec["status"] = status
        if x_post is not None:
            rec["x_post"] = x_post[:X_LIMIT]
        rec["status_at"] = datetime.now(IST).isoformat(timespec="seconds")
    _save()
    return rec


def status_report() -> Dict[str, Any]:
    _load()
    _reload_if_changed()
    _reload_if_changed()
    with _lock:
        items = list(_state["items"].values())
        by_cat: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for r in items:
            by_cat[r.get("category_label") or "?"] = by_cat.get(r.get("category_label") or "?", 0) + 1
            by_status[r.get("status") or "?"] = by_status.get(r.get("status") or "?", 0) + 1
        c = dict(_state["counters"])
    try:
        upstream = ann.feed(limit=1)
        src = {"last_poll": upstream.get("last_poll"), "stored": upstream.get("stored"),
               "mapped_to_nse": upstream.get("mapped_to_nse"), "error": upstream.get("error"),
               "refreshing": upstream.get("refreshing")}
    except Exception as e:
        src = {"error": f"{type(e).__name__}: {e}"}
    return {
        "store_path": STORE_PATH,
        "last_build": _state["last_build"],
        "upstream_announcements": src,
        "counters": c,
        "kept_pct": round(100.0 * c["kept"] / c["seen"], 2) if c.get("seen") else None,
        "held": len(items),
        "by_category": by_cat,
        "by_status": by_status,
        "recent_drops": _state["recent_drops"][:25],
    }


# ============================================================================
# INSTAGRAM CAPTION
# ============================================================================
# Different medium, different rules. No character pressure (2,200 limit), links
# are not clickable so they are pointless, and the image carries the headline —
# so the caption gives the context the card had no room for.
#
# Same SEBI line as everywhere else: restatement only, no view.

IG_BASE_TAGS = ["StockMarketIndia", "IndianStockMarket", "NSE", "BSE",
                "CorporateFilings", "Nifty50"]

IG_CATEGORY_TAGS = {
    "order_win": ["OrderWin", "OrderBook"],
    "credit_rating": ["CreditRating"],
    "pledge": ["PromoterPledge"],
    "board_change": ["Leadership"],
    "fundraise": ["Fundraise", "QIP"],
    "ma": ["MergersAndAcquisitions"],
    "buyback": ["Buyback"],
    "capex": ["Capex", "Expansion"],
    "disruption": ["Operations"],
    "regulatory": ["Regulatory"],
    "insolvency": ["Insolvency"],
    "results": ["Results", "Earnings"],
    "business_update": ["BusinessUpdate"],
    "dividend": ["Dividend"],
    "bonus_split": ["BonusIssue"],
    "related_party": ["RelatedParty"],
}

IG_DISCLAIMER = ("A plain-English restatement of the company's own filing. "
                 "Descriptive only — not a recommendation, not advice.")


def build_ig_caption(rec: Dict[str, Any]) -> str:
    r = rec.get("restated") or {}
    sym = rec.get("symbol") or ""
    lines: List[str] = []

    lines.append(r.get("body", ""))

    # Only add facts the restatement did not already carry — otherwise the
    # caption reads as if it is padding, which it would be.
    body_l = (r.get("body") or "").lower()
    extras: List[str] = []
    if r.get("figures") and r["figures"].lower() not in body_l:
        extras.append(r["figures"])
    if rec.get("counterparty") and rec["counterparty"].lower() not in body_l:
        extras.append(f"Counterparty: {rec['counterparty']}")
    if rec.get("dates") and rec["dates"][0].lower() not in body_l:
        extras.append(f"Date in the filing: {rec['dates'][0]}")
    if extras:
        lines.append("\n".join("· " + e for e in extras))

    src = f"Filed with {rec.get('exchange') or 'BSE'}"
    if rec.get("time_ist"):
        src += f" on {rec['time_ist']}"
    src += ". The full PDF is linked in our bio."
    lines.append(src)

    lines.append(IG_DISCLAIMER)

    tags = ([sym] if sym and re.fullmatch(r"[A-Z0-9&\-]{1,15}", sym) else []) \
        + IG_CATEGORY_TAGS.get(rec.get("category_key"), []) + IG_BASE_TAGS
    seen, ordered = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            ordered.append("#" + t)
    lines.append(" ".join(ordered[:10]))

    return "\n\n".join(x for x in lines if x).strip()[:2200]
