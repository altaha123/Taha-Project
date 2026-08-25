"""
market_news.py — wide-net market news for the Social surface.

Relationship to news_feed.py (Update 3): that module stays exactly as it is. It
serves the sector screens and is imported by sector_story.py, so it is not
touched here. This module is a separate, wider net aimed at one job — finding
the handful of stories a day that are worth a post.

Three design rules, carried over from news_feed.py and extended:

1. NEWS NEVER TOUCHES A SCORE. No import of engine, profiles, archetypes,
   alerts or announcements. Nothing here can move a threshold.

2. NEWS AND FILINGS ARE NEVER MERGED. A filing is the company speaking. A news
   story is a journalist speaking. They are different kinds of fact and they
   live in separate lists with separate labels, always.

3. NO PARAPHRASE, EVER. A headline is passed through exactly as published, with
   the publication named and the link attached. This module does not reword
   somebody else's reporting and put it out under your name. That rule exists
   for two reasons — it is their work, and a reworded headline is how you
   accidentally turn "RBI may consider" into "RBI to cut".

The one thing this module adds that nobody else on Indian fintwit is doing:
CORROBORATION COUNT. The same story lands in six outlets within two hours
because it came off one PTI wire or one press conference. A story carried by
six outlets and a story carried by one are very different objects. The second
one is either a scoop or wrong. This module clusters near-identical headlines
across sources and tells you which you are looking at.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

IST = timezone(timedelta(hours=5, minutes=30))
HTTP_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; AltahaScreener/1.0; +https://taha-project-one.vercel.app)"


def _resolve_store_dir() -> str:
    explicit = os.getenv("ALTAHA_SOCIAL_DIR")
    if explicit:
        return explicit
    pit = os.getenv("ALTAHA_PIT_DB")
    if pit and os.path.dirname(pit):
        return os.path.dirname(pit)
    return os.getenv("DATA_DIR") or "/tmp"


STORE_PATH = os.path.join(_resolve_store_dir(), "market_news.json")
MAX_KEEP = int(os.getenv("NEWS_MAX_KEEP", "900"))
LOOKBACK_HOURS = int(os.getenv("NEWS_LOOKBACK_HOURS", "30"))
POLL_SECONDS = int(os.getenv("NEWS_POLL_SECONDS", "900"))


# ============================================================================
# 1. SOURCES
# ============================================================================
# "enabled" is the switch. Turn things off here rather than deleting them, so
# /social/news/status can still tell you what you chose not to fetch.
#
# On the Financial Times specifically: its feed is headlines only and the
# stories sit behind a hard paywall. Linking your followers to something they
# cannot read is a bad post, and FT's terms are stricter than the Indian
# outlets'. It is included and OFF. Turn it on only if you want it in the app
# for your own reading rather than for posting.

SOURCES: List[Dict[str, Any]] = [
    # ---- Indian markets and economy -------------------------------------
    {"key": "et_markets", "name": "Economic Times", "region": "IN", "enabled": True,
     "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"key": "et_economy", "name": "Economic Times", "region": "IN", "enabled": True,
     "url": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"},
    {"key": "mc_markets", "name": "Moneycontrol", "region": "IN", "enabled": True,
     "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
    {"key": "mc_business", "name": "Moneycontrol", "region": "IN", "enabled": True,
     "url": "https://www.moneycontrol.com/rss/business.xml"},
    {"key": "bs_markets", "name": "Business Standard", "region": "IN", "enabled": True,
     "url": "https://www.business-standard.com/rss/markets-106.rss"},
    {"key": "bs_economy", "name": "Business Standard", "region": "IN", "enabled": True,
     "url": "https://www.business-standard.com/rss/economy-102.rss"},
    {"key": "mint_markets", "name": "Mint", "region": "IN", "enabled": True,
     "url": "https://www.livemint.com/rss/markets"},
    {"key": "mint_companies", "name": "Mint", "region": "IN", "enabled": True,
     "url": "https://www.livemint.com/rss/companies"},
    {"key": "toi_business", "name": "Times of India", "region": "IN", "enabled": True,
     "url": "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"},
    {"key": "fe_market", "name": "Financial Express", "region": "IN", "enabled": True,
     "url": "https://www.financialexpress.com/market/feed/"},
    {"key": "bl_markets", "name": "Hindu BusinessLine", "region": "IN", "enabled": True,
     "url": "https://www.thehindubusinessline.com/markets/feeder/default.rss"},
    # ---- Global macro that moves Indian markets -------------------------
    {"key": "cnbc_world", "name": "CNBC", "region": "GLOBAL", "enabled": True,
     "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html"},
    {"key": "ft_home", "name": "Financial Times", "region": "GLOBAL", "enabled": False,
     "url": "https://www.ft.com/rss/home",
     "note": "headlines only, hard paywall — on for reading, poor for posting"},
    {"key": "ft_markets", "name": "Financial Times", "region": "GLOBAL", "enabled": False,
     "url": "https://www.ft.com/markets?format=rss",
     "note": "headlines only, hard paywall"},
]


# ============================================================================
# 2. RELEVANCE
# ============================================================================
# TOI Business alone runs a few hundred items a day and most of it is not a
# market story. Two gates: kill the obvious non-market sections outright, then
# require at least one real market term or a matched company.

KILL = [
    (r"\b(cricket|ipl\b|world\s+cup|olympic|football|kabaddi|t20|odi\b)", "sport"),
    (r"\b(bollywood|box\s+office|actor|actress|film|movie|web\s+series|celebrity|kapoor|khan\s+film)", "entertainment"),
    (r"\b(horoscope|zodiac|astrolog|numerolog|tarot)", "astrology"),
    (r"\b(recipe|weight\s+loss|skin\s?care|beauty\s+tips|fashion\s+week|lifestyle)", "lifestyle"),
    (r"\b(viral\s+video|watch:|shocking|netizens|goes\s+viral|trolled)", "viral"),
    (r"\b(murder|rape|assault|arrested\s+for|kidnap)", "crime"),
    (r"\b(dies\s+at|passes\s+away|obituary|condolence)", "obituary"),
    (r"\b(recruitment|admit\s+card|result\s+declared|exam\s+date|neet|jee\b|upsc)", "exams"),
    (r"\b(best\s+\d+|top\s+\d+\s+(phones|laptops|deals)|amazon\s+sale|flipkart\s+sale)", "shopping"),
    (r"\b(horoscope|panchang|rashifal)", "astrology"),
    (r"\b(live\s+updates?|blog:)\s*$", "rolling liveblog"),
]
KILL_C = [(re.compile(p, re.I), why) for p, why in KILL]

# Market vocabulary, grouped so the UI can filter by theme.
THEMES: Dict[str, List[str]] = {
    "Policy": [r"\brbi\b", r"repo\s+rate", r"monetary\s+polic", r"\bmpc\b", r"cash\s+reserve",
               r"\bsebi\b", r"\birdai\b", r"\bcci\b", r"regulator", r"\brbi\s+governor"],
    "Macro": [r"\binflation\b", r"\bcpi\b", r"\bwpi\b", r"\bgdp\b", r"\biip\b", r"\bpmi\b",
              r"gst\s+collection", r"fiscal\s+deficit", r"current\s+account", r"trade\s+deficit",
              r"\bbudget\b", r"industrial\s+(output|production)", r"unemployment"],
    "Flows": [r"\bfiis?\b", r"\bfpis?\b", r"\bdiis?\b", r"foreign\s+(investor|inflow|outflow)",
              r"mutual\s+fund\s+(inflow|outflow)", r"\bsip\s+(inflow|book)",
              r"(pull|pour)\w*\s+(out|in).{0,24}\bequit", r"\bnet\s+(buyers?|sellers?)\b"],
    "Currency & commodities": [r"\brupee\b", r"\bdollar\s+index\b", r"\bcrude\b", r"\bbrent\b",
                               r"\bwti\b", r"\bgold\s+price", r"\bopec\b", r"\bforex\s+reserve"],
    "Global": [r"\bfed\b", r"federal\s+reserve", r"\bfomc\b", r"\becb\b", r"bank\s+of\s+japan",
               r"\btariff", r"trade\s+war", r"\bus\s+(cpi|jobs|payroll)", r"treasury\s+yield",
               r"\bchina\s+(stimulus|gdp|data)"],
    "Markets": [r"\bsensex\b", r"\bnifty\b", r"\bbank\s?nifty\b", r"\bmidcap\b", r"\bsmallcap\b",
                r"\bbse\b", r"\bnse\b", r"market\s+cap", r"\brally\b", r"\bselloff\b", r"\bcircuit\b"],
    "Primary market": [r"\bipo\b", r"\bqip\b", r"\bofs\b", r"\bblock\s+deal", r"\banchor\s+investor",
                       r"\blisting\b", r"\bgrey\s+market", r"\bstake\s+(sale|buy)"],
    "Corporate": [r"\bearnings\b", r"\bq[1-4]\s+(results?|earnings)", r"\bguidance\b",
                  r"\border\s+book\b", r"\bmerger\b", r"\bacquisition\b", r"\bstake\s+sale\b",
                  r"\bdemerger\b", r"\bbuyback\b", r"\bdividend\b", r"\bdowngrade\b", r"\bupgrade\b",
                  r"\b(monthly|domestic|auto|total)\s+sales\b", r"\bsales\s+(ris|fall|jump|drop|grow|declin)",
                  r"\bin\s+talks\s+to\b", r"\bto\s+(acquire|buy|invest)\b", r"\bcapacity\b"],
    "Sector policy": [r"\bpli\b", r"production\s+linked", r"\bgst\s+(rate|council)", r"\bimport\s+duty",
                      r"\bexport\s+(ban|duty|curb)", r"\bspectrum\b", r"\bcoal\s+(auction|block)",
                      r"\bsubsid(y|ies)\b", r"\bmsp\b", r"\btelecom\s+tariff"],
}
THEMES_C = {k: [re.compile(p, re.I) for p in v] for k, v in THEMES.items()}

# Weight per theme. Policy and macro move the whole index; corporate news about
# one company usually only moves that company.
THEME_WEIGHT = {
    "Policy": 3.2, "Macro": 3.0, "Sector policy": 2.6, "Flows": 2.5,
    "Global": 2.2, "Currency & commodities": 2.0, "Primary market": 1.6,
    "Markets": 1.5, "Corporate": 1.4,
}

# Headline heavyweights, for tagging a story to a symbol. Deliberately short and
# curated — the same reasoning as Update 3. Fuzzy-matching the full 2,000-name
# NSE list turns "Bajaj" into three companies and "Vedanta" into a hospital.
COMPANY_ALIASES: Dict[str, List[str]] = {
    "RELIANCE": ["reliance industries", "ril\\b", "jio", "reliance retail"],
    "TCS": ["tata consultancy", "\\btcs\\b"],
    "HDFCBANK": ["hdfc bank"],
    "ICICIBANK": ["icici bank"],
    "INFY": ["infosys"],
    "SBIN": ["state bank of india", "\\bsbi\\b"],
    "BHARTIARTL": ["bharti airtel", "\\bairtel\\b"],
    "ITC": ["\\bitc\\b"],
    "LT": ["larsen\\s*&?\\s*toubro", "\\bl&t\\b"],
    "AXISBANK": ["axis bank"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak bank"],
    "HINDUNILVR": ["hindustan unilever", "\\bhul\\b"],
    "MARUTI": ["maruti suzuki", "\\bmaruti\\b"],
    "TATAMOTORS": ["tata motors", "\\bjlr\\b", "jaguar land rover"],
    "TATASTEEL": ["tata steel"],
    "ADANIENT": ["adani enterprises"],
    "ADANIPORTS": ["adani ports"],
    "ADANIGREEN": ["adani green"],
    "WIPRO": ["wipro"],
    "HCLTECH": ["hcl tech"],
    "TECHM": ["tech mahindra"],
    "SUNPHARMA": ["sun pharma"],
    "DRREDDY": ["dr\\.? reddy"],
    "CIPLA": ["cipla"],
    "ONGC": ["\\bongc\\b", "oil and natural gas"],
    "NTPC": ["\\bntpc\\b"],
    "POWERGRID": ["power grid corporation", "powergrid"],
    "COALINDIA": ["coal india"],
    "BPCL": ["\\bbpcl\\b", "bharat petroleum"],
    "IOC": ["indian oil"],
    "JSWSTEEL": ["jsw steel"],
    "HINDALCO": ["hindalco"],
    "VEDL": ["vedanta ltd", "vedanta limited", "vedanta resources"],
    "ULTRACEMCO": ["ultratech"],
    "GRASIM": ["grasim"],
    "ASIANPAINT": ["asian paints"],
    "NESTLEIND": ["nestle india"],
    "BAJFINANCE": ["bajaj finance"],
    "BAJAJFINSV": ["bajaj finserv"],
    "BAJAJ-AUTO": ["bajaj auto"],
    "HEROMOTOCO": ["hero motocorp"],
    "EICHERMOT": ["eicher motors", "royal enfield"],
    "M&M": ["mahindra\\s*&?\\s*mahindra", "\\bm&m\\b"],
    "TITAN": ["titan company", "tanishq"],
    "ZOMATO": ["zomato", "eternal ltd"],
    "PAYTM": ["paytm", "one97"],
    "NYKAA": ["nykaa", "fsn e-commerce"],
    "DMART": ["avenue supermarts", "\\bdmart\\b", "d-mart"],
    "IRCTC": ["\\birctc\\b"],
    "LICI": ["life insurance corporation", "\\blic\\b"],
    "SUZLON": ["suzlon"],
    "YESBANK": ["yes bank"],
    "IDEA": ["vodafone idea", "\\bvi\\b"],
    "DIXON": ["dixon technologies"],
    "HAL": ["hindustan aeronautics", "\\bhal\\b"],
    "BEL": ["bharat electronics"],
    "BHEL": ["\\bbhel\\b"],
    "SAIL": ["\\bsail\\b", "steel authority"],
    "IRFC": ["\\birfc\\b"],
    "RVNL": ["\\brvnl\\b", "rail vikas"],
    "PFC": ["power finance corporation"],
    "RECLTD": ["\\brec ltd\\b", "rural electrification"],
    "TATAPOWER": ["tata power"],
    "SIEMENS": ["siemens india", "siemens ltd"],
    "ABB": ["abb india"],
    "PIDILITIND": ["pidilite"],
    "TRENT": ["trent ltd", "westside"],
    "INDIGO": ["interglobe aviation", "indigo airlines"],
}
ALIASES_C = {sym: [re.compile(p, re.I) for p in pats] for sym, pats in COMPANY_ALIASES.items()}

STOPWORDS = set("""a an the of in on at to for from by with and or as is are was were be been
this that these those it its after before over under up down out new says say said may might
will would can could s t india indian crore lakh rs vs amid over
per cent pc points point year month week day today latest news""".split())


# ============================================================================
# 3. RSS PARSING (stdlib only, same reasoning as Update 3 — no feedparser)
# ============================================================================

def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
          .replace("&#39;", "'").replace("&lsquo;", "'").replace("&rsquo;", "'")
          .replace("&ldquo;", '"').replace("&rdquo;", '"').replace("&#8217;", "'"))
    return re.sub(r"\s+", " ", s).strip()


def parse_feed(xml_bytes: bytes) -> List[Dict[str, str]]:
    """Handles RSS 2.0 and Atom. Returns raw items, unfiltered."""
    out: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out

    # RSS 2.0
    for item in root.iter("item"):
        link = _text(item.find("link"))
        out.append({
            "title": _strip_html(_text(item.find("title"))),
            "link": link,
            "summary": _strip_html(_text(item.find("description")))[:400],
            "published": _text(item.find("pubDate")),
        })
    if out:
        return out

    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(ns + "entry"):
        link_el = entry.find(ns + "link")
        out.append({
            "title": _strip_html(_text(entry.find(ns + "title"))),
            "link": (link_el.get("href") if link_el is not None else "") or "",
            "summary": _strip_html(_text(entry.find(ns + "summary")))[:400],
            "published": _text(entry.find(ns + "updated")) or _text(entry.find(ns + "published")),
        })
    return out


def _parse_when(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(IST)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(s.strip(), fmt)
            return d.astimezone(IST) if d.tzinfo else d.replace(tzinfo=IST)
        except Exception:
            continue
    return None


# ============================================================================
# 4. SCORING
# ============================================================================

def score_item(title: str, summary: str = "") -> Dict[str, Any]:
    blob = f"{title} {summary}"

    for rx, why in KILL_C:
        if rx.search(blob):
            return {"keep": False, "reason": why, "themes": [], "symbols": [],
                    "score": 0.0, "speculative": False}

    themes: List[str] = []
    score = 0.0
    for theme, rxs in THEMES_C.items():
        if any(rx.search(blob) for rx in rxs):
            themes.append(theme)
            score += THEME_WEIGHT.get(theme, 1.0)

    symbols = [sym for sym, rxs in ALIASES_C.items() if any(rx.search(blob) for rx in rxs)]
    if symbols:
        score += 2.0
    # A headline naming five companies is a roundup, not a story.
    if len(symbols) > 4:
        score -= 2.0
        symbols = symbols[:4]

    speculative = bool(re.search(
        r"\b(may|could|likely|reportedly|sources\s+say|mulls|eyes|plans\s+to|in\s+talks)\b", title, re.I))
    if speculative:
        score -= 0.5

    if not themes and not symbols:
        return {"keep": False, "reason": "no market relevance", "themes": [], "symbols": [],
                "score": 0.0, "speculative": speculative}

    return {"keep": score >= 2.0, "reason": None if score >= 2.0 else "below relevance threshold",
            "themes": themes, "symbols": symbols, "score": round(score, 2),
            "speculative": speculative}


# ============================================================================
# 5. CLUSTERING — the corroboration count
# ============================================================================

def _tokens(title: str) -> set:
    # Keep decimals whole — "6.5" is one fact, not a 6 and a 5.
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", (title or "").lower())
    return {w for w in words if w not in STOPWORDS and (len(w) > 2 or w.replace(".", "").isdigit())}


def _similar(a: set, b: set) -> float:
    """Overlap coefficient, not Jaccard."""
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared < 3:
        return 0.0
    return shared / float(min(len(a), len(b)))


def cluster(items: List[Dict[str, Any]], threshold: float = 0.45) -> List[Dict[str, Any]]:
    """Greedy clustering on headline token overlap. O(n·k) with k = cluster count,
    which stays small because the input is already filtered down to tens of items."""
    clusters: List[Dict[str, Any]] = []
    for it in sorted(items, key=lambda x: x.get("score", 0), reverse=True):
        toks = _tokens(it["title"])
        placed = False
        for c in clusters:
            if _similar(toks, c["_tokens"]) >= threshold:
                c["members"].append(it)
                if it["publication"] not in c["publications"]:
                    c["publications"].append(it["publication"])
                placed = True
                break
        if not placed:
            clusters.append({
                "_tokens": toks,
                "lead": it,
                "members": [it],
                "publications": [it["publication"]],
            })
    for c in clusters:
        c.pop("_tokens", None)
        c["corroboration"] = len(c["publications"])
        c["themes"] = sorted({t for m in c["members"] for t in m.get("themes", [])})
        c["speculative"] = all(m.get("speculative") for m in c["members"])
        c["symbols"] = sorted({s for m in c["members"] for s in m.get("symbols", [])})
        # A story in four outlets outranks a marginally higher-scoring single item.
        c["rank"] = round(c["lead"]["score"] + 1.2 * (c["corroboration"] - 1), 2)
    clusters.sort(key=lambda c: c["rank"], reverse=True)
    return clusters


# ============================================================================
# 6. X POST
# ============================================================================
# The headline is quoted verbatim and the publication is named, because this is
# their reporting, not yours. The link goes back to them. What you add is the
# corroboration count and the theme tag — those are yours.

X_LIMIT = 280


def build_x_post(c: Dict[str, Any]) -> str:
    lead = c["lead"]
    # Pick the heaviest theme, not the alphabetically first one. An RBI rate
    # decision is Policy; it was coming out labelled "Macro".
    theme = max(c.get("themes") or ["Markets"], key=lambda t: THEME_WEIGHT.get(t, 1.0))
    syms = c.get("symbols") or []
    tag = " ".join(f"#{s}" for s in syms[:2]) if syms else "#Markets"

    head = f"{tag} · {theme}"
    quote = f'"{lead["title"]}"'
    attrib = f"— {lead['publication']}"
    corro = ""
    if c["corroboration"] >= 3:
        corro = f"\n\nAlso running in {c['corroboration'] - 1} other outlets."
    elif c["corroboration"] == 1 and c.get("speculative"):
        corro = "\n\nSingle source, and not confirmed by the company."

    link = f"\n\n{lead['link']}" if lead.get("link") else ""

    for parts in ([head, quote, attrib, corro, link],
                  [head, quote, attrib, link],
                  [head, quote, attrib]):
        body = f"{parts[0]}\n\n{parts[1]}\n{parts[2]}" + "".join(parts[3:])
        # X counts every URL as 23 characters regardless of real length.
        counted = len(body) - (len(lead.get("link", "")) - 23 if lead.get("link") and lead["link"] in body else 0)
        if counted <= X_LIMIT:
            return body.strip()

    trimmed = lead["title"]
    if len(trimmed) > 150:
        trimmed = trimmed[:147].rsplit(" ", 1)[0] + "…"
    return f'{head}\n\n"{trimmed}"\n— {lead["publication"]}'


# ============================================================================
# 7. FETCH + STATE
# ============================================================================

_lock = threading.RLock()
_state: Dict[str, Any] = {
    "items": {},
    "source_status": {},
    "last_poll": None,
    "counters": {"seen": 0, "dropped": 0, "kept": 0},
    "recent_drops": [],
}
_loaded = False


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
            os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
            tmp = STORE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"items": _state["items"], "counters": _state["counters"]}, fh)
            os.replace(tmp, STORE_PATH)
        except Exception:
            pass


def fetch_source(src: Dict[str, Any]) -> List[Dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests not installed")
    r = requests.get(src["url"], headers={"User-Agent": USER_AGENT,
                                          "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                     timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    raw = parse_feed(r.content)
    out = []
    for it in raw:
        if not it.get("title"):
            continue
        out.append({
            "title": it["title"],
            "link": it.get("link", ""),
            "summary": it.get("summary", ""),
            "published": it.get("published", ""),
            "publication": src["name"],
            "source_key": src["key"],
            "region": src["region"],
        })
    return out


def poll_once() -> Dict[str, Any]:
    _load()
    added = 0
    status: Dict[str, Any] = {}
    for src in SOURCES:
        if not src.get("enabled"):
            status[src["key"]] = {"ok": None, "skipped": True, "reason": src.get("note", "disabled")}
            continue
        try:
            rows = fetch_source(src)
            kept_here = 0
            for row in rows:
                _state["counters"]["seen"] += 1
                verdict = score_item(row["title"], row["summary"])
                if not verdict["keep"]:
                    _state["counters"]["dropped"] += 1
                    _state["recent_drops"] = ([{"title": row["title"][:110],
                                                "publication": row["publication"],
                                                "reason": verdict["reason"]}]
                                              + _state["recent_drops"])[:60]
                    continue
                when = _parse_when(row["published"])
                rid = hashlib.sha1((row["publication"] + "|" + row["title"]).encode("utf-8", "ignore")).hexdigest()[:16]
                rec = dict(row)
                rec.update({
                    "id": rid,
                    "themes": verdict["themes"],
                    "symbols": verdict["symbols"],
                    "score": verdict["score"],
                    "speculative": verdict.get("speculative", False),
                    "when_ist": when.strftime("%d %b, %H:%M IST") if when else "",
                    "when_iso": when.isoformat() if when else "",
                    "ingested_at": datetime.now(IST).isoformat(timespec="seconds"),
                    "status": "pending",
                })
                with _lock:
                    if rid not in _state["items"]:
                        _state["items"][rid] = rec
                        added += 1
                        kept_here += 1
                _state["counters"]["kept"] += 1
            status[src["key"]] = {"ok": True, "fetched": len(rows), "kept": kept_here,
                                  "publication": src["name"], "error": None}
        except Exception as e:
            status[src["key"]] = {"ok": False, "fetched": 0, "kept": 0,
                                  "publication": src["name"], "error": f"{type(e).__name__}: {e}"}
        time.sleep(0.4)   # be a polite client
    with _lock:
        _state["source_status"] = status
        _state["last_poll"] = datetime.now(IST).isoformat(timespec="seconds")
    _save()
    return {"added": added, "sources": status, "counters": dict(_state["counters"])}


def feed(limit: int = 40, theme: Optional[str] = None,
         symbol: Optional[str] = None, min_corroboration: int = 1) -> List[Dict[str, Any]]:
    _load()
    with _lock:
        items = list(_state["items"].values())
    cutoff = datetime.now(IST) - timedelta(hours=LOOKBACK_HOURS)

    def fresh(r):
        try:
            return datetime.fromisoformat(r.get("ingested_at", "")) >= cutoff
        except Exception:
            return True

    items = [r for r in items if fresh(r) and r.get("status") != "skipped"]
    if theme:
        items = [r for r in items if theme in (r.get("themes") or [])]
    if symbol:
        items = [r for r in items if symbol in (r.get("symbols") or [])]

    cs = cluster(items)
    cs = [c for c in cs if c["corroboration"] >= min_corroboration]
    for c in cs:
        c["x_post"] = build_x_post(c)
        c["id"] = c["lead"]["id"]
    return cs[:limit]


def set_status(item_id: str, status: str) -> Optional[Dict[str, Any]]:
    _load()
    with _lock:
        rec = _state["items"].get(item_id)
        if not rec:
            return None
        rec["status"] = status
    _save()
    return rec


def status_report() -> Dict[str, Any]:
    _load()
    with _lock:
        c = dict(_state["counters"])
        return {
            "store_path": STORE_PATH,
            "last_poll": _state["last_poll"],
            "sources": _state["source_status"],
            "sources_configured": [{"key": s["key"], "publication": s["name"],
                                    "enabled": s["enabled"], "region": s["region"],
                                    "note": s.get("note")} for s in SOURCES],
            "counters": c,
            "kept_pct": round(100.0 * c["kept"] / c["seen"], 2) if c.get("seen") else None,
            "held": len(_state["items"]),
            "themes": sorted(THEMES.keys()),
            "recent_drops": _state["recent_drops"][:25],
        }


# ============================================================================
# 8. POLLER
# ============================================================================

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop() -> None:
    while not _stop.is_set():
        now = datetime.now(IST)
        if 7 <= now.hour < 23:
            try:
                poll_once()
            except Exception:
                pass
            _stop.wait(POLL_SECONDS)
        else:
            _stop.wait(1800)


def start_poller() -> bool:
    global _thread
    if os.getenv("NEWS_POLLER", "1") not in ("1", "true", "True"):
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="news-poller", daemon=True)
    _thread.start()
    return True


def stop_poller() -> None:
    _stop.set()
