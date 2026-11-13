"""
The daily brief: every new government and regulator circular, read for what
it does to listed companies.

WHAT IT READS, each run:

  DGFT        notifications, public notices, circulars and trade notices:
              export and import policy, by product and HS code
  RBI         press releases and notifications: rates, bank and NBFC rules
  SEBI        circulars, orders and press releases: market rules
  PIB         government press releases in English: cabinet decisions,
              duties, schemes, trade agreements, export figures

WHAT IT SAYS about each one: a two-line summary, whether it helps or hurts,
which sectors, and which listed stocks, with the reason. Every circular is
read once, on the day it appears, and kept for thirty days.

WHO READS IT. With ANTHROPIC_API_KEY set, Claude reads each circular (the
PDF itself for DGFT, the title and summary for the others) and returns the
impact as structured data; the stocks it names are checked against NSE's
list and anything not on it is dropped. Without a key, or when a read fails,
a keyword table does the job: it knows about sixty products and policy words
and maps them to sectors. That reading is cruder and is labelled as such.

WHAT IT IS NOT. A circular's effect on a share price is a judgement, not a
measurement: none of this has a tested record, and the page says so. It
changes no rank on any Ideas list; it sits beside them.
"""

import base64
import datetime as dt
import hashlib
import html as html_mod
import json
import os
import re
import threading
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE
STORE = os.path.join(_DATA_DIR, "policy_brief.json")
SECTORS_FILE = os.path.join(_HERE, "nse_industries.csv")

MODEL = os.environ.get("BRIEF_MODEL", "claude-opus-5-5")
KEEP_DAYS = 30
NEW_WITHIN_DAYS = 4            # an item older than this on first sight is backlog, not news
MAX_PER_RUN = int(os.environ.get("BRIEF_MAX_PER_RUN", "40") or 40)
MAX_PDF_BYTES = 6 * 1024 * 1024
UA = {"User-Agent": "Mozilla/5.0 (compatible; brief-reader)"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_lock = threading.Lock()

DGFT_PAGES = (
    ("DGFT notification", "https://www.dgft.gov.in/CP/?opt=notification"),
    ("DGFT public notice", "https://www.dgft.gov.in/CP/?opt=public-notice"),
    ("DGFT circular", "https://www.dgft.gov.in/CP/?opt=circular"),
    ("DGFT trade notice", "https://www.dgft.gov.in/CP/?opt=trade-notice"),
)
RSS_FEEDS = (
    ("RBI press release", "https://www.rbi.org.in/pressreleases_rss.xml"),
    ("RBI notification", "https://www.rbi.org.in/notifications_rss.xml"),
    ("SEBI", "https://www.sebi.gov.in/sebirss.xml"),
    ("PIB", "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3&reg=3"),
)

# ---- the keyword reading, used when nobody else can read ---------------------
# (words in the title) -> NSE industries it touches. Direction is read
# separately from the policy words below.
TOPICS = (
    (("steel", "iron ore", "ferro", "coking coal", "pig iron"), ["Metals & Mining"]),
    (("aluminium", "copper", "zinc", "nickel", "scrap", "rare earth", "critical mineral"), ["Metals & Mining"]),
    (("rice", "wheat", "sugar", "onion", "pulses", "edible oil", "palm oil", "maize", "tur", "urad", "molasses"),
     ["Fast Moving Consumer Goods"]),
    (("tea", "coffee", "spice", "tobacco", "marine product", "shrimp", "dairy", "milk"), ["Fast Moving Consumer Goods"]),
    (("textile", "cotton", "yarn", "garment", "apparel", "fabric", "jute", "man-made fibre"), ["Textiles"]),
    (("pharma", "drug", "api ", "bulk drug", "medical device", "vaccine", "formulation"), ["Healthcare"]),
    (("urea", "fertiliser", "fertilizer", "dap", "potash", "pesticide", "agrochemical", "chemical", "soda ash",
      "caustic"), ["Chemicals"]),
    (("crude", "petrol", "diesel", "atf", "natural gas", "lng", "petroleum", "windfall"), ["Oil Gas & Consumable Fuels"]),
    (("automobile", "vehicle", "electric vehicle", "ev ", "auto component", "tyre", "lithium", "battery"),
     ["Automobile and Auto Components"]),
    (("electronics", "semiconductor", "laptop", "mobile phone", "it hardware", "solar module", "solar cell", "pcb"),
     ["Consumer Durables", "Capital Goods"]),
    (("defence", "drone", "railway", "capital goods", "machinery", "shipbuilding"), ["Capital Goods"]),
    (("cement", "clinker"), ["Construction Materials"]),
    (("gold", "silver", "jewellery", "diamond", "gems"), ["Consumer Durables"]),
    (("telecom", "spectrum"), ["Telecommunication"]),
    (("power", "electricity", "renewable", "coal ", "thermal"), ["Power"]),
    (("repo rate", "crr", "slr", "liquidity", "bank", "nbfc", "lending", "deposit", "priority sector", "kyc",
      "monetary policy"), ["Financial Services"]),
    (("mutual fund", "broker", "stock exchange", "depository", "aif", "portfolio manager", "ipo", "listing"),
     ["Financial Services"]),
    (("housing", "real estate", "rera"), ["Realty"]),
    (("highway", "infrastructure", "port", "airport", "construction"), ["Construction"]),
    (("software", "it services", "data centre", "data protection"), ["Information Technology"]),
    (("paper", "pulp", "newsprint", "timber"), ["Forest Materials"]),
)
# Policy words, and what they do to a domestic producer of the product named.
HELPS = ("export allowed", "export permitted", "prohibition lifted", "removal of restriction", "restriction removed",
         "free export", "from restricted to free", "from prohibited to free", "duty drawback", "rodtep", "incentive",
         "pli", "anti-dumping", "anti dumping", "safeguard duty", "minimum import price", "import restricted",
         "import prohibited", "import curb", "rate cut", "reduces repo", "relaxation", "extension of", "subsidy",
         "free trade agreement", "trade agreement", "approves", "approval")
HURTS = ("export prohibited", "export banned", "export ban", "export restricted", "from free to restricted",
         "from free to prohibited", "minimum export price", "export duty", "stock limit", "import allowed",
         "import duty cut", "duty reduced", "from restricted to free import", "rate hike", "raises repo", "penalty",
         "tightens", "cap on", "ban on", "restriction on", "windfall tax")


# Procedural items that reach no share price: one person's appeal, a recovery
# certificate, a routine auction. They are not read at all.
NOISE = re.compile(
    r"^(appeal no|cancellation of recovery|recovery certificate|adjudication order|order in the matter|"
    r"final order|interim order|settlement order|corrigendum|notice of demand|attachment order|"
    r"release order|completion certificate|certificate of recovery|order in respect of|"
    r"revocation order|confirmatory order|summons|public notice.*untraceable|notice of attachment|"
    r"prohibitory order|sebi order for compliance|summary settlement order)"
    r"|treasury bill|auction of (state )?government|underwriting auction|money market operations|"
    r"result of .*auction|state government securities|conversion/switch|sovereign gold bond.*redemption|"
    r"reserve money|weekly statistical|lending and deposit rates of scheduled|foundation day|"
    r"gallantry|pays tribute|greets|condoles|felicitat|inaugurat", re.I)
# A PIB release is read only if it is about the economy at all.
ECONOMY = re.compile(
    r"\b(export|import|trade|tariff|duty|duties|customs|gst|tax|cabinet|ccea|pli|scheme|subsid|msp|"
    r"price|production|output|iip|inflation|cpi|wpi|fdi|invest|mineral|mining|coal|steel|power|energy|"
    r"oil|gas|petroleum|fertili[sz]er|pharma|textile|electronics|semiconductor|defence|railway|highway|"
    r"port|shipping|aviation|telecom|bank|credit|agreement|fta|procurement|auction|tender|policy|"
    r"manufactur|capacity|bids?)\b", re.I)


def _has(text, word):
    """A word or phrase as itself: 'port' is not in 'reporting'."""
    return re.search(r"(?<![a-z])" + re.escape(word.strip()) + r"(?![a-z])", text) is not None


def worth_reading(item):
    title = item.get("title") or ""
    if NOISE.search(title):
        return False
    if item.get("source") == "PIB" and not ECONOMY.search(title):
        return False
    return True


def _clean(s):
    s = html_mod.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    return re.sub(r"\s+", " ", s).strip()


def _item_id(source, title, link):
    return hashlib.sha1(f"{source}|{title}|{link}".encode("utf-8")).hexdigest()[:16]


def _parse_date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%a, %d %b %Y %H:%M:%S", "%d %b %Y", "%d %b, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s[:31].strip(), fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", s)
    if m:
        try:
            return dt.datetime.strptime(" ".join(m.groups()), "%d %b %Y").date()
        except ValueError:
            pass
    return None


def parse_dgft(page, source):
    """Rows of a DGFT listing page: number, year, subject, date, PDF."""
    out = []
    for row in re.findall(r"<tr>(.*?)</tr>", page or "", flags=re.S):
        cells = [_clean(c) for c in re.findall(r"<td(?![^>]*display:none)[^>]*>(.*?)</td>", row, flags=re.S)]
        link = re.search(r'href="([^"]+\.pdf)"', row, flags=re.I)
        if len(cells) < 5 or not cells[3]:
            continue
        day = _parse_date(cells[4])
        if day is None:
            continue
        url = link.group(1).replace(" ", "%20") if link else None
        out.append({"source": source, "number": cells[1], "title": cells[3], "summary": "",
                    "date": day.isoformat(), "link": url, "pdf": url})
    return out


def parse_rss(text, source):
    out = []
    try:
        root = ET.fromstring((text or "").lstrip("\ufeff").strip().encode("utf-8"))
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        # PIB's feed mixes languages; the brief reads English.
        if not title or sum(1 for ch in title if ord(ch) > 127) > len(title) * 0.2:
            continue
        day = _parse_date(it.findtext("pubDate") or "")
        out.append({"source": source, "number": "", "title": title,
                    "summary": _clean(it.findtext("description"))[:1500],
                    "date": day.isoformat() if day else None,
                    "link": (it.findtext("link") or "").strip() or None, "pdf": None})
    return out


def fetch_all(get=None):
    """Every source's current items, and which sources answered."""
    if get is None:
        import requests

        def get(url):
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            return r.content.decode("utf-8-sig", "replace")
    items, status = [], {}
    for source, url in DGFT_PAGES:
        try:
            got = parse_dgft(get(url), source)
            status[source] = len(got)
            items += got
        except Exception as e:
            status[source] = f"failed: {type(e).__name__}"
    for source, url in RSS_FEEDS:
        try:
            got = parse_rss(get(url), source)
            status[source] = len(got)
            items += got
        except Exception as e:
            status[source] = f"failed: {type(e).__name__}"
    for it in items:
        it["id"] = _item_id(it["source"], it["title"], it.get("link") or "")
    return items, status


_sector_cache = {}


def sector_members():
    """{industry: [(symbol, company)]} from NSE's list shipped with the code."""
    if _sector_cache:
        return _sector_cache
    import csv
    try:
        with open(SECTORS_FILE, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if row.get("Symbol") and row.get("Industry"):
                    _sector_cache.setdefault(row["Industry"], []).append((row["Symbol"].upper(), row.get("Company Name")))
    except Exception:
        pass
    return _sector_cache


def read_by_rules(item):
    """The keyword reading. Sectors from the product named, direction from
    the policy words; no stock is named, because a keyword cannot tell which
    company in a sector a rule reaches."""
    text = f" {item.get('title', '')} {item.get('summary', '')} ".lower()
    sectors = []
    for words, secs in TOPICS:
        if any(_has(text, w) for w in words):
            sectors += [s for s in secs if s not in sectors]
    up, down = any(_has(text, w) for w in HELPS), any(_has(text, w) for w in HURTS)
    impact = "mixed" if up and down else ("positive" if up else ("negative" if down else "unclear"))
    if not sectors:
        impact = "none"
    return {"read_by": "keywords", "summary": item.get("title", ""), "impact": impact,
            "importance": "medium" if sectors and impact in ("positive", "negative", "mixed") else "low",
            "sectors": sectors[:4], "stocks": [],
            "why": ("Matched on words in the title. A keyword cannot tell which way a rule cuts for each "
                    "company, so read the circular before acting.") if sectors else "",
            "watch": ""}


def configured():
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    import importlib.util
    return importlib.util.find_spec("anthropic") is not None


SYSTEM = (
    "You read Indian government and regulator circulars for an investor in NSE-listed shares. For the one "
    "circular given, say what it changes and which listed companies it helps or hurts.\n\n"
    "Be concrete and conservative. Most circulars are procedural and move no share price: say so with impact "
    "\"none\" and importance \"low\", and name no stocks. Name a stock only when the link is direct: the "
    "company makes, exports, imports or is regulated on the very thing the circular changes, and the change is "
    "large enough to matter to its earnings. Think about direction carefully: an export curb hurts exporters "
    "of that product and can help domestic buyers of it; an import curb or anti-dumping duty helps domestic "
    "producers and hurts users of the import. Use NSE trading symbols. Sectors must come from the list given. "
    "If the text is too thin to judge, say impact \"unclear\". Write the summary in plain English, two "
    "sentences at most, no jargon the circular itself does not use."
)


def _schema(industries):
    return {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "impact", "importance", "sectors", "stocks", "why", "watch"],
        "properties": {
            "summary": {"type": "string"},
            "impact": {"type": "string", "enum": ["positive", "negative", "mixed", "none", "unclear"]},
            "importance": {"type": "string", "enum": ["high", "medium", "low"]},
            "sectors": {"type": "array", "items": {"type": "string", "enum": sorted(industries)}},
            "stocks": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["symbol", "direction", "reason"],
                "properties": {"symbol": {"type": "string"},
                               "direction": {"type": "string", "enum": ["helped", "hurt"]},
                               "reason": {"type": "string"}}}},
            "why": {"type": "string"},
            "watch": {"type": "string"},
        },
    }


def _fetch_pdf(url):
    try:
        import requests
        r = requests.get(url, headers=UA, timeout=30)
        if r.ok and r.content[:4] == b"%PDF" and len(r.content) <= MAX_PDF_BYTES:
            return base64.standard_b64encode(r.content).decode("ascii")
    except Exception:
        pass
    return None


def read_with_claude(item, client=None, pdf_b64=None):
    """One circular, read by Claude. Returns the analysis, or None when the
    read failed or was declined (the caller then falls back to keywords)."""
    import anthropic
    members = sector_members()
    known = {sym for rows in members.values() for sym, _name in rows}
    client = client or anthropic.Anthropic(timeout=120.0, max_retries=2)
    content = []
    if pdf_b64:
        content.append({"type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}})
    content.append({"type": "text", "text": (
        f"Source: {item['source']}\nNumber: {item.get('number') or '-'}\nDate: {item.get('date') or '-'}\n"
        f"Title: {item['title']}\nSummary: {item.get('summary') or '-'}\n\n"
        + ("The circular itself is attached." if pdf_b64 else
           "Only the title and summary are available; judge from those and say \"unclear\" if they are not enough.")
        + "\n\nSectors you may name: " + ", ".join(sorted(members)) + ".")})
    try:
        response = client.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema(members)}},
            messages=[{"role": "user", "content": content}])
    except anthropic.APIError:
        return None
    if response.stop_reason != "end_turn":
        return None
    try:
        data = json.loads(next(b.text for b in response.content if b.type == "text"))
    except (StopIteration, ValueError):
        return None
    # A symbol NSE does not list is a guess; it is dropped, not shown.
    stocks = []
    for s in data.get("stocks") or []:
        sym = str(s.get("symbol") or "").upper().strip()
        if sym in known and sym not in {x["symbol"] for x in stocks}:
            stocks.append({"symbol": sym, "direction": s.get("direction"), "reason": _clean(s.get("reason"))[:300]})
    return {"read_by": "claude", "read_from": "the circular" if pdf_b64 else "title and summary",
            "summary": _clean(data.get("summary"))[:600], "impact": data.get("impact"),
            "importance": data.get("importance"),
            "sectors": [s for s in data.get("sectors") or [] if s in members][:5],
            "stocks": stocks[:8], "why": _clean(data.get("why"))[:600], "watch": _clean(data.get("watch"))[:300]}


def load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": {}, "runs": []}


def _save(state):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STORE)


def refresh(today=None, fetch=None, reader=None, pdf=None):
    """
    Read what is new. Each circular is analysed once; a later run only picks
    up what appeared since. `fetch`, `reader` and `pdf` are for tests.
    Returns a short report of the run.
    """
    today = today or dt.datetime.now(IST).date()
    with _lock:
        state = load()
        items, status = (fetch or fetch_all)()
        use_claude = reader is not None or configured()
        new = 0
        for it in sorted(items, key=lambda x: x.get("date") or "", reverse=True):
            if it["id"] in state["items"] or new >= MAX_PER_RUN or not worth_reading(it):
                continue
            day = _parse_date(it.get("date") or "") or today
            if (today - day).days > NEW_WITHIN_DAYS:
                continue
            analysis = None
            if use_claude:
                try:
                    doc = (pdf or _fetch_pdf)(it["pdf"]) if it.get("pdf") else None
                    analysis = (reader or read_with_claude)(it, pdf_b64=doc)
                except Exception:
                    analysis = None
            if analysis is None:
                analysis = read_by_rules(it)
            state["items"][it["id"]] = dict(it, date=day.isoformat(), first_seen=today.isoformat(), **analysis)
            new += 1
        cutoff = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
        state["items"] = {k: v for k, v in state["items"].items() if (v.get("first_seen") or "") >= cutoff}
        run = {"at": dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "new": new, "sources": status,
               "reader": "claude" if use_claude else "keywords"}
        state["runs"] = (state.get("runs") or [])[-20:] + [run]
        _save(state)
    return run


_RANK = {"high": 0, "medium": 1, "low": 2}


def brief(days=1, today=None):
    """The brief for the last `days` days: what matters first."""
    today = today or dt.datetime.now(IST).date()
    state = load()
    since = (today - dt.timedelta(days=max(1, days) - 1)).isoformat()
    rows = [v for v in state["items"].values() if (v.get("first_seen") or "") >= since]
    rows.sort(key=lambda v: (_RANK.get(v.get("importance"), 3), v.get("impact") in ("none", "unclear"),
                             -(dt.date.fromisoformat(v["date"]).toordinal() if v.get("date") else 0), v["title"]))
    matter = [r for r in rows if r.get("impact") in ("positive", "negative", "mixed")]
    stocks = {}
    for r in matter:
        for s in r.get("stocks") or []:
            stocks.setdefault(s["symbol"], []).append(
                {"direction": s["direction"], "reason": s["reason"], "source": r["source"], "title": r["title"]})
    sectors = {}
    for r in matter:
        for sec in r.get("sectors") or []:
            sectors.setdefault(sec, {"positive": 0, "negative": 0, "mixed": 0})[r["impact"]] += 1
    last = (state.get("runs") or [None])[-1]
    return {
        "date": today.isoformat(), "days": days, "count": len(rows), "matter": len(matter),
        "items": rows, "stocks": [{"symbol": k, "mentions": v} for k, v in sorted(stocks.items())],
        "sectors": [{"sector": k, **v} for k, v in sorted(sectors.items())],
        "last_run": last, "reader": (last or {}).get("reader"),
        "claude": configured(),
        "note": ("How a circular moves a share price is a judgement, not a measurement. Nothing here has a "
                 "tested record and none of it changes a rank on the Ideas lists. Read the circular itself "
                 "before acting on it."),
    }


def email_lines(b, limit=8):
    """The brief as short lines for the daily email: what matters only."""
    out = []
    for r in b.get("items") or []:
        if r.get("impact") not in ("positive", "negative", "mixed"):
            continue
        names = ", ".join(f"{s['symbol']} ({s['direction']})" for s in (r.get("stocks") or [])[:4])
        out.append({"source": r["source"], "title": r["title"], "summary": r.get("summary") or "",
                    "impact": r["impact"], "sectors": r.get("sectors") or [], "stocks": names,
                    "link": r.get("link")})
        if len(out) >= limit:
            break
    return out


def email_subject(b):
    n = b.get("matter") or 0
    return f"Policy brief, {b['date']}: {n} circular{'s' if n != 1 else ''} that matter{'s' if n == 1 else ''}"


def email_text(b, site="", unsubscribe_url=""):
    lines = [email_subject(b), ""]
    for r in email_lines(b, limit=12):
        lines += [f"{r['source']}: {r['title']}", f"  {r['impact'].upper()}. {r['summary']}"]
        if r["sectors"]:
            lines.append("  Sectors: " + ", ".join(r["sectors"]))
        if r["stocks"]:
            lines.append("  Stocks: " + r["stocks"])
        if r.get("link"):
            lines.append("  " + r["link"])
        lines.append("")
    lines += [b["note"], "", f"All of today's circulars: {site}/brief.html" if site else ""]
    if unsubscribe_url:
        lines += ["", "Unsubscribe: " + unsubscribe_url]
    return "\n".join(lines)


def email_html(b, site="", unsubscribe_url=""):
    e = html_mod.escape
    tone = {"positive": "#1a7f4b", "negative": "#b3261e", "mixed": "#8a6d1a"}
    rows = []
    for r in email_lines(b, limit=12):
        title = e(r["title"])
        if r.get("link"):
            title = f'<a href="{e(r["link"])}" style="color:#1a1a1a">{title}</a>'
        rows.append(
            '<div style="padding:12px 0;border-top:1px solid #e5e1d8">'
            f'<div style="font-size:12px;color:#6b665c">{e(r["source"])} \u00b7 '
            f'<b style="color:{tone.get(r["impact"], "#6b665c")}">{e(r["impact"])}</b></div>'
            f'<div style="font-weight:600;margin:4px 0">{title}</div>'
            f'<div style="font-size:14px;line-height:1.45">{e(r["summary"])}</div>'
            + (f'<div style="font-size:13px;color:#6b665c;margin-top:4px">Sectors: {e(", ".join(r["sectors"]))}</div>'
               if r["sectors"] else "")
            + (f'<div style="font-size:13px;margin-top:2px">Stocks: {e(r["stocks"])}</div>' if r["stocks"] else "")
            + "</div>")
    return (
        '<div style="font-family:Georgia,serif;max-width:620px;margin:0 auto;color:#1a1a1a">'
        f'<h2 style="font-size:20px;margin:0 0 4px">{e(email_subject(b))}</h2>'
        f'<div style="font-size:13px;color:#6b665c">{b.get("count", 0)} circulars read today.</div>'
        + "".join(rows)
        + f'<p style="font-size:12px;color:#6b665c;border-top:1px solid #e5e1d8;padding-top:12px">{e(b["note"])}</p>'
        + (f'<p style="font-size:13px"><a href="{e(site)}/brief.html">All of today\u2019s circulars</a></p>' if site else "")
        + (f'<p style="font-size:11px;color:#6b665c"><a href="{e(unsubscribe_url)}">Unsubscribe</a></p>'
           if unsubscribe_url else "")
        + "</div>")
