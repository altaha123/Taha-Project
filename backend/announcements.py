"""
announcements.py — corporate announcement ingestion, filtering and plain-language
restatement for the Altaha Screener "Social" surface.

Design rules (do not relax these):

1. RESTATEMENT ONLY. This module never adds an opinion, an outlook, a target, a
   sentiment word or a "watch this". It restates what the company itself filed,
   in plain English, and it does arithmetic on published numbers. That keeps the
   output on the factual-reporting side of the SEBI line until RA registration
   lands. Every adjective this module can emit is in ALLOWED_ADJECTIVES below,
   and there are none that describe whether news is good or bad.

2. NEVER TOUCHES A SCORE. No import of engine.py, profiles.py, archetypes.py or
   alerts.py. The dependency arrow only points this way. Same rule as news_feed.py.

3. NOTHING AUTO-POSTS by default. Everything lands in a review queue. AUTO_POST
   must be explicitly turned on, and even then only tier-A categories with a
   confident parse go out.

4. NO LLM IN THE HOT PATH. Restatement is deterministic templating off a parsed
   structure. An LLM that misreads a scheme of arrangement puts a factual error
   about a listed company under Taha's name. Templates can be wrong in boring,
   visible ways; an LLM is wrong in confident, invisible ways.

Sources:
  BSE  — api.bseindia.com JSON, needs a Referer header. Straightforward.
  NSE  — www.nseindia.com JSON, needs cookie priming and gentle rate limiting.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

IST = timezone(timedelta(hours=5, minutes=30))

# ----------------------------------------------------------------------------
# Storage location
# ----------------------------------------------------------------------------
# Deliberately does NOT trust DATA_DIR on its own. Render currently has
# DATA_DIR=/data while ALTAHA_PIT_DB=/var/data/altaha_pit.db, and if the disk is
# mounted at /var/data then DATA_DIR is ephemeral. We prefer the directory the
# PIT database actually lives in, because that one is provably persistent.

def _resolve_store_dir() -> str:
    explicit = os.getenv("ALTAHA_SOCIAL_DIR")
    if explicit:
        return explicit
    pit = os.getenv("ALTAHA_PIT_DB")
    if pit:
        d = os.path.dirname(pit)
        if d:
            return d
    return os.getenv("DATA_DIR") or "/tmp"


STORE_DIR = _resolve_store_dir()
STORE_PATH = os.path.join(STORE_DIR, "announcements.json")

MAX_KEEP = int(os.getenv("ANN_MAX_KEEP", "1200"))
POLL_SECONDS = int(os.getenv("ANN_POLL_SECONDS", "300"))
LOOKBACK_HOURS = int(os.getenv("ANN_LOOKBACK_HOURS", "36"))
HTTP_TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_lock = threading.RLock()
_state: Dict[str, Any] = {
    "items": {},          # digest -> record
    "source_status": {},  # source -> {ok, error, count, at}
    "last_poll": None,
    "counters": {"seen": 0, "dropped": 0, "kept": 0},
}
_loaded = False

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
            r"\b(receipt|received|award(ed)?|bagg?ed|secur(ed|ing)|win(s|ning)?)\b.{0,40}\b(order|contract|loa|letter\s+of\s+award|work\s+order|tender)\b",
            r"\border\s+(win|book|inflow|received)\b",
            r"\bletter\s+of\s+(award|intent|acceptance)\b",
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
            r"\b(penalty|fine|show\s+cause|adjudicat|prosecution|search\s+and\s+seiz|raid|summons)\b",
            r"\b(gst|income\s+tax|sebi|rbi|cci|enforcement\s+directorate|nclt|nclat)\b.{0,50}\b(order|notice|penalty|demand|action)\b",
            r"regulation\s*30.{0,30}\b(tax\s+demand|penalty)",
            r"\bdemand\s+(order|notice)\b",
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
        "patterns": [r"\bbonus\s+(issue|share)", r"\b(stock\s+)?split\b", r"\bsub-?division\s+of\s+(equity\s+)?shares?\b"],
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
# 7. SOURCES
# ============================================================================

def _session() -> "requests.Session":
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


def fetch_bse(days: int = 2) -> List[Dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests not installed")
    s = _session()
    s.headers.update({
        "Referer": "https://www.bseindia.com/corporates/ann.html",
        "Origin": "https://www.bseindia.com",
        "Accept": "application/json, text/plain, */*",
    })
    today = datetime.now(IST)
    frm = (today - timedelta(days=days)).strftime("%Y%m%d")
    to = today.strftime("%Y%m%d")
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    out: List[Dict[str, Any]] = []
    for page in (1, 2, 3):
        params = {
            "pageno": page, "strCat": "-1", "strPrevDate": frm, "strScrip": "",
            "strSearch": "P", "strToDate": to, "strType": "C", "subcategory": "-1",
        }
        r = s.get(url, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        rows = (r.json() or {}).get("Table") or []
        if not rows:
            break
        for row in rows:
            attach = (row.get("ATTACHMENTNAME") or "").strip()
            out.append({
                "exchange": "BSE",
                "source_id": str(row.get("NEWSID") or "").strip(),
                "company": (row.get("SLONGNAME") or "").strip(),
                "symbol": (row.get("NSURL") or "").split("/")[-1].upper()[:15] or "",
                "scrip": str(row.get("SCRIP_CD") or "").strip(),
                "headline": (row.get("HEADLINE") or row.get("NEWSSUB") or "").strip(),
                "detail": (row.get("MORE") or row.get("NEWSSUB") or "").strip(),
                "category": (row.get("CATEGORYNAME") or "").strip(),
                "subcategory": (row.get("SUBCATNAME") or "").strip(),
                "posted": (row.get("DT_TM") or row.get("NEWS_DT") or "").strip(),
                "pdf": (f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach}" if attach else ""),
            })
        time.sleep(0.6)
    return out


def fetch_nse() -> List[Dict[str, Any]]:
    """NSE needs a real browsing session: hit the site, collect cookies, then the API."""
    if requests is None:
        raise RuntimeError("requests not installed")
    s = _session()
    s.headers.update({"Accept": "text/html,application/xhtml+xml"})
    s.get("https://www.nseindia.com/", timeout=HTTP_TIMEOUT)
    time.sleep(1.0)
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements", timeout=HTTP_TIMEOUT)
    time.sleep(1.0)
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        "X-Requested-With": "XMLHttpRequest",
    })
    r = s.get("https://www.nseindia.com/api/corporate-announcements",
              params={"index": "equities"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("rows") or []
    out = []
    for row in rows or []:
        out.append({
            "exchange": "NSE",
            "source_id": str(row.get("seqId") or row.get("attchmntFile") or row.get("sort_date") or "").strip(),
            "company": (row.get("sm_name") or row.get("comp") or "").strip(),
            "symbol": (row.get("symbol") or "").strip().upper(),
            "scrip": "",
            "headline": (row.get("desc") or row.get("subject") or "").strip(),
            "detail": (row.get("attchmntText") or row.get("smIndustry") or "").strip(),
            "category": (row.get("desc") or "").strip(),
            "subcategory": "",
            "posted": (row.get("an_dt") or row.get("sort_date") or "").strip(),
            "pdf": (row.get("attchmntFile") or "").strip(),
        })
    return out


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
# 9. PIPELINE
# ============================================================================

def _digest(rec: Dict[str, Any]) -> str:
    base = f"{rec.get('exchange')}|{rec.get('symbol') or rec.get('company')}|{(rec.get('headline') or '')[:160]}"
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("items"), dict):
                _state["items"] = data["items"]
                _state["counters"] = data.get("counters", _state["counters"])
        except Exception:
            pass


def _save() -> None:
    with _lock:
        items = _state["items"]
        if len(items) > MAX_KEEP:
            ordered = sorted(items.items(), key=lambda kv: kv[1].get("ingested_at", ""), reverse=True)
            _state["items"] = dict(ordered[:MAX_KEEP])
        try:
            os.makedirs(STORE_DIR, exist_ok=True)
            tmp = STORE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"items": _state["items"], "counters": _state["counters"]}, fh)
            os.replace(tmp, STORE_PATH)
        except Exception:
            pass


def process(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One raw row -> a stored, restated record. None if filtered out."""
    blob = " ".join(str(raw.get(k) or "") for k in ("headline", "detail", "category", "subcategory"))
    verdict = classify(blob)
    _state["counters"]["seen"] += 1

    if not verdict["keep"]:
        _state["counters"]["dropped"] += 1
        _state.setdefault("recent_drops", [])
        _state["recent_drops"] = ([{"company": raw.get("company"),
                                    "headline": (raw.get("headline") or "")[:110],
                                    "reason": verdict["reason"]}] + _state.get("recent_drops", []))[:60]
        return None

    ct = clean_text(blob)
    money = extract_money_cr(blob)
    pctm = PCT_RE.search(blob)
    rec: Dict[str, Any] = {
        "id": "",
        "exchange": raw.get("exchange"),
        "company": raw.get("company"),
        "symbol": raw.get("symbol") or "",
        "headline": raw.get("headline"),
        "clean_text": ct[:1200],
        "category_key": verdict["key"],
        "category_label": verdict["label"],
        "tier": verdict["tier"],
        "money_cr": money,
        "pct": float(pctm.group(1).replace(",", "")) if pctm else None,
        "counterparty": extract_counterparty(blob),
        "dates": extract_dates(blob),
        "pdf": raw.get("pdf") or "",
        "posted": raw.get("posted") or "",
        "time_ist": "",
        "ingested_at": datetime.now(IST).isoformat(timespec="seconds"),
        "status": "pending",
        "mcap_pct": None,
    }
    try:
        p = (rec["posted"] or "").replace("T", " ")[:19]
        rec["time_ist"] = datetime.strptime(p, "%Y-%m-%d %H:%M:%S").strftime("%d %b, %H:%M IST")
    except Exception:
        rec["time_ist"] = datetime.now(IST).strftime("%d %b, %H:%M IST")

    if money and rec["symbol"]:
        mc = _market_cap_cr(rec["symbol"])
        if mc and mc > 0:
            share = 100.0 * money / mc
            if 0.5 <= share <= 400:
                rec["mcap_pct"] = share

    per_share = re.search(r"(?:rs\.?|₹)\s*(" + _NUM + r")\s*per\s+(?:equity\s+)?share", blob, re.I)
    if per_share:
        rec["per_share"] = per_share.group(1)

    # Tier B needs a number to earn a slot.
    if rec["tier"] == "B" and money is None and rec["pct"] is None and not rec.get("per_share"):
        _state["counters"]["dropped"] += 1
        return None

    rec["restated"] = restate(rec)
    rec["x_post"] = build_x_post(rec)
    rec["id"] = _digest(rec)
    _state["counters"]["kept"] += 1
    return rec


def poll_once() -> Dict[str, Any]:
    _load()
    added, results = 0, {}
    for name, fn in (("bse", fetch_bse), ("nse", fetch_nse)):
        try:
            rows = fn()
            results[name] = {"ok": True, "count": len(rows), "error": None,
                             "at": datetime.now(IST).isoformat(timespec="seconds")}
            for raw in rows:
                rec = process(raw)
                if not rec:
                    continue
                with _lock:
                    if rec["id"] in _state["items"]:
                        continue
                    _state["items"][rec["id"]] = rec
                    added += 1
        except Exception as e:
            results[name] = {"ok": False, "count": 0, "error": f"{type(e).__name__}: {e}",
                             "at": datetime.now(IST).isoformat(timespec="seconds")}
    with _lock:
        _state["source_status"].update(results)
        _state["last_poll"] = datetime.now(IST).isoformat(timespec="seconds")
    _save()
    return {"added": added, "sources": results, "counters": dict(_state["counters"])}


def feed(limit: int = 60, status: Optional[str] = None,
         category: Optional[str] = None) -> List[Dict[str, Any]]:
    _load()
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
    order = {"A": 0, "B": 1}
    items.sort(key=lambda r: (order.get(r.get("tier"), 2),
                              -(r.get("mcap_pct") or 0),
                              r.get("ingested_at", "")), reverse=False)
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
    with _lock:
        items = list(_state["items"].values())
        by_cat: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for r in items:
            by_cat[r.get("category_label") or "?"] = by_cat.get(r.get("category_label") or "?", 0) + 1
            by_status[r.get("status") or "?"] = by_status.get(r.get("status") or "?", 0) + 1
        c = dict(_state["counters"])
        kept_pct = (100.0 * c.get("kept", 0) / c["seen"]) if c.get("seen") else None
        return {
            "store_path": STORE_PATH,
            "store_dir_persistent_hint": STORE_DIR,
            "last_poll": _state["last_poll"],
            "sources": _state["source_status"],
            "counters": c,
            "kept_pct": round(kept_pct, 2) if kept_pct is not None else None,
            "held": len(items),
            "by_category": by_cat,
            "by_status": by_status,
            "recent_drops": _state.get("recent_drops", [])[:25],
        }


# ============================================================================
# 10. BACKGROUND POLLER
# ============================================================================

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop() -> None:
    while not _stop.is_set():
        now = datetime.now(IST)
        # 08:00-18:00 IST, Mon-Fri. Filings land outside market hours constantly.
        if now.weekday() < 5 and 8 <= now.hour < 18:
            try:
                poll_once()
            except Exception:
                pass
            _stop.wait(POLL_SECONDS)
        else:
            _stop.wait(900)


def start_poller() -> bool:
    global _thread
    if os.getenv("ANN_POLLER", "1") not in ("1", "true", "True"):
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ann-poller", daemon=True)
    _thread.start()
    return True


def stop_poller() -> None:
    _stop.set()
