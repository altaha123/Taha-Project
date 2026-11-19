"""
Altaha Screener — the press, for one company and for its industry

WHAT WAS MISSING
news_feed.py reads four market feeds and matches headlines to about a hundred
heavyweights by a curated alias table. Open any of the other two thousand
companies and its news list was empty, and even for a heavyweight the list held
only what those four feeds happened to carry that afternoon.

A stock page needs two lists the feeds cannot give it:

  ABOUT THE COMPANY   what has been reported about this company lately
  ABOUT ITS INDUSTRY  what has been reported about the things that move it:
                      a rate decision for a bank, crude for a refiner, a
                      USFDA action for a drug maker

Both come from a news search, asked by name. The first is asked for the
company. The second is asked for the industry's own vocabulary, and each
headline that comes back is tagged with the driver it mentions, so a reader
sees why a story about the repo rate is on a bank's page.

THE THREE RULES, CARRIED OVER FROM news_feed.py
  1  PRESS NEVER TOUCHES A SCORE. Nothing here is imported by the engine.
  2  PRESS IS LABELLED AS PRESS. Every row carries its publication and
     `kind: "press"`, and the page keeps it apart from filings.
  3  NO PARAPHRASE. The headline is passed through as published, linked.

PRECISION OVER RECALL
A search for "Vedanta" returns a hospital chain. So a company row is kept only
when its headline names the company: the full name, a curated alias, or the
first two words of the name where those are distinctive. A story that fails the
check is dropped, because a wrong attribution on a company's own page is worse
than a missing one. The driver tags are keyword rules, printed in this file,
and wrong sometimes; they say what a headline mentions, not what it means for
the share price.

Nothing here raises. A search that fails returns what the market feeds had,
which may be nothing, and says the search was not answered.
"""

import datetime as dt
import html as _html
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

try:
    import requests
except Exception:                                    # pragma: no cover
    requests = None

try:
    import news_feed
except Exception:                                    # pragma: no cover
    news_feed = None

try:
    import market_news
except Exception:                                    # pragma: no cover
    market_news = None

SEARCH = "https://news.google.com/rss/search"
SEARCH_PARAMS = {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
      "Accept": "application/rss+xml, application/xml, text/xml, */*"}

TIMEOUT = 8                    # one search; the page is waiting on it
WAIT = 10                      # both searches together
TTL = 20 * 60                  # press is not a latency game
TTL_FAILED = 3 * 60            # ask again soon, but not on every view
MEMO_MAX = 400

COMPANY_DAYS = 21
INDUSTRY_DAYS = 7
COMPANY_LIMIT = 14
INDUSTRY_LIMIT = 14

# Three searches in a row unanswered and the search engine is having a bad
# five minutes, or has stopped answering this address. Either way the next
# company's page should not spend eight seconds of a request thread finding
# that out again.
TRIP_AFTER = 3
TRIP_FOR = 5 * 60

_memo = OrderedDict()          # query -> (at, rows or None)
_lock = threading.Lock()
_trip = {"fails": 0, "until": 0.0}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="altaha-news")


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

_SUFFIX = re.compile(r"[\s,]+(limited|ltd\.?|inc\.?|plc|corp\.?)\s*$", re.I)

# Words that do not single a company out. A name's first two words become an
# alias only when neither is one of these: "Bank of" is not Bank of Baroda.
_OPENERS = {"the", "of", "and", "bank", "state", "national", "new", "general",
            "united", "indian", "india", "oil", "life", "great", "first", "shree", "sri"}
_GENERIC = {"bank", "of", "india", "indian", "the", "and", "&", "national", "state",
            "united", "general", "new", "power", "steel", "oil", "life", "insurance",
            "finance", "financial", "industries", "international", "global", "housing",
            "first", "standard", "limited", "company", "corporation", "enterprises",
            "holdings", "group", "infrastructure", "energy", "capital", "services",
            "technologies", "products", "projects", "systems", "solutions"}


def _norm(text):
    """Lower case, no dots or apostrophes, single spaces: "Dr. Reddy's" and
    "Dr Reddys" are the same company in a headline."""
    t = _html.unescape(str(text or "")).lower()
    t = re.sub(r"[.'’`]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_name(name):
    """'State Bank of India Limited' -> 'State Bank of India'."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    for _ in range(2):
        n = _SUFFIX.sub("", n).strip()
    return n


def aliases_for(symbol, name):
    """
    The ways a headline names this company, as compiled patterns.

    The full name always. The curated tables' aliases where the company is in
    them. And the first two words of a longer name when both are distinctive:
    "Adani Green" for Adani Green Energy, but never "State Bank" or "Bank of".
    """
    sym = re.sub(r"\.(NS|BO)$", "", str(symbol or "").strip().upper())
    plain, patterns = [], []
    full = _norm(clean_name(name))
    if len(full) >= 4 and full != _norm(sym):
        plain.append(full)
    words = full.split()
    if len(words) >= 3 and words[0] not in _OPENERS and words[1] not in _GENERIC \
            and len(words[0]) > 2 and len(words[1]) > 2:
        plain.append(" ".join(words[:2]))
    if news_feed is not None:
        for a in news_feed.ALIASES.get(sym, []):
            a = _norm(a)
            if len(a) >= 3:
                plain.append(a)
    for a in dict.fromkeys(plain):
        patterns.append(re.compile(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(a)))
    if market_news is not None:
        patterns.extend(market_news.ALIASES_C.get(sym, []))
    return patterns, list(dict.fromkeys(plain))


def mentions(headline, patterns):
    text = _norm(headline)
    return any(p.search(text) for p in patterns)


def company_query(symbol, name):
    """The search asked for a company: its name as a phrase, or any curated
    short form people actually write ("SBI", "L&T")."""
    _patterns, plain = aliases_for(symbol, name)
    full = clean_name(name)
    terms = ['"%s"' % full] if len(full) >= 4 else []
    for a in plain[1:] if terms else plain:
        if 3 <= len(a) <= 30 and a not in _norm(full):
            terms.append('"%s"' % a.upper() if len(a) <= 5 else '"%s"' % a)
    if not terms:
        return None
    return "%s when:%dd" % (" OR ".join(terms[:3]), COMPANY_DAYS)


# ---------------------------------------------------------------------------
# What moves an industry
#
# One row per kind of business: the substrings that pick it out of a provider's
# industry name (Yahoo's and NSE's are both covered), the search asked for it,
# and the drivers a headline is tagged with. First match wins, so the narrow
# rows come before the broad ones: "electrical equipment" has to be read as
# capital goods before "electric" reads it as a power utility.
# ---------------------------------------------------------------------------

GROUPS = [
    ("Banks", ("bank",),
     'Indian banks (RBI OR "credit growth" OR deposits OR NPA OR "repo rate")', [
         ("Interest rates", r"repo rate|rate cut|rate hike|\bmpc\b|monetary policy|\bcrr\b|bond yields?|\bmclr\b|lending rates?"),
         ("Asset quality", r"\bnpas?\b|bad loans?|slippages?|stressed (assets?|loans?)|write-?offs?|provision"),
         ("Credit and deposits", r"credit growth|loan growth|deposit|\bcasa\b|advances|liquidity"),
         ("Regulation", r"\brbi\b|norms\b|circular|regulat|capital adequacy|\bsebi\b|penalt"),
     ]),
    ("Insurance", ("insurance",),
     'India insurance sector (IRDAI OR premium OR "GST" OR claims)', [
         ("Regulation", r"\birdai\b|regulat|norms\b|\bgst\b|commission"),
         ("Premium growth", r"premium|new business|\bape\b|\bvnb\b|persistency"),
         ("Claims", r"claims?|loss ratio|combined ratio"),
     ]),
    ("Capital markets", ("capital markets", "asset management", "brokerage", "stock exchange",
                         "depositor", "financial data"),
     'India (brokerages OR "mutual funds" OR SEBI) (volumes OR inflows OR norms OR "F&O")', [
         ("Regulation", r"\bsebi\b|norms\b|regulat|\bf&o\b|derivative"),
         ("Flows and volumes", r"inflows?|outflows?|\bsip\b|volumes?|turnover|demat|\baum\b"),
     ]),
    ("Lenders and NBFCs", ("credit services", "nbfc", "housing finance", "mortgage", "microfinance",
                           "financ"),
     'India (NBFC OR "housing finance" OR microfinance) (RBI OR "borrowing costs" OR "asset quality")', [
         ("Interest rates", r"repo rate|rate cut|rate hike|\bmpc\b|borrowing costs?|bond yields?|cost of funds"),
         ("Asset quality", r"\bnpas?\b|bad loans?|delinquenc|stress|collection|write-?offs?|provision"),
         ("Regulation", r"\brbi\b|norms\b|risk weights?|circular|regulat"),
         ("Loan growth", r"loan growth|disbursement|\baum\b|credit growth"),
     ]),
    ("IT services", ("information technology", "software", "it services", "it - ", "it enabled",
                     "computer"),
     'Indian IT services (deal wins OR "US clients" OR hiring OR "H-1B" OR rupee)', [
         ("Client spending", r"deal wins?|\btcv\b|order book|client spend|discretionary|\bus\b.{0,24}(demand|recession|slowdown)|\bai\b"),
         ("Visas and tariffs", r"h-?1b|visa|tariff|outsourcing (tax|bill)|\bhire act\b"),
         ("Currency", r"rupee|dollar"),
         ("Hiring and wages", r"hiring|attrition|layoffs?|wage hike|headcount|freshers"),
     ]),
    ("Pharma", ("drug", "pharma", "biotech"),
     'Indian pharma (USFDA OR "price control" OR generics OR tariffs OR API)', [
         ("USFDA", r"\bus ?fda\b|form 483|warning letter|import alert|inspection|observations"),
         ("US pricing and tariffs", r"tariff|generic (drug )?pric|price erosion|\bmfn\b|drug pric"),
         ("Domestic pricing", r"\bnppa\b|price control|\bnlem\b|ceiling price"),
         ("Approvals", r"approval|\banda\b|launch"),
     ]),
    ("Hospitals and diagnostics", ("medical care", "hospital", "diagnostic", "health"),
     'India (hospitals OR diagnostics) (occupancy OR "price caps" OR insurance OR expansion)', [
         ("Regulation and pricing", r"price cap|regulat|\bnpp?a\b|\bcghs\b|ayushman"),
         ("Capacity", r"beds?|expansion|acquisition|occupancy|\barpob\b"),
     ]),
    ("Oil and gas", ("oil & gas", "oil and gas", "refiner", "petroleum", "gas util", "lpg",
                     "exploration"),
     'India (crude OR Brent OR OPEC OR "refining margins" OR "fuel prices" OR "windfall tax")', [
         ("Crude prices", r"crude|brent|\bwti\b|opec|oil prices?"),
         ("Refining and marketing margins", r"refining margins?|\bgrm\b|marketing margins?|under-?recover"),
         ("Fuel pricing and tax", r"petrol|diesel|\blpg\b|excise|windfall|fuel prices?|subsid"),
         ("Gas", r"natural gas|\blng\b|\bcng\b|gas prices?|\bapm\b"),
     ]),
    ("Metals and mining", ("steel", "alumin", "copper", "metal", "mining", "coal", "iron", "zinc"),
     'India (steel OR aluminium OR "iron ore" OR coal) (prices OR "China" OR "import duty" OR safeguard)', [
         ("Metal prices", r"steel prices?|aluminium prices?|\blme\b|iron ore|coking coal|zinc|copper prices?"),
         ("China", r"china|chinese"),
         ("Trade duties", r"import dut|safeguard|anti-?dumping|export dut|tariff"),
         ("Demand", r"demand|production|output|infrastructure"),
     ]),
    ("Cement", ("building materials", "cement"),
     'India cement (prices OR demand OR "fuel costs" OR capacity)', [
         ("Cement prices", r"cement prices?|price hike|per bag"),
         ("Demand", r"demand|volumes?|housing|infrastructure|monsoon"),
         ("Costs", r"pet ?coke|coal|fuel|freight|power costs?"),
         ("Capacity", r"capacity|acquisition|consolidation"),
     ]),
    ("Chemicals", ("chemical", "fertil", "agro"),
     'India (chemicals OR agrochemicals OR fertilisers) (China OR dumping OR prices OR demand OR subsidy)', [
         ("China and dumping", r"china|chinese|dumping|anti-?dumping"),
         ("Prices and inputs", r"prices?|crude|feedstock|spreads?"),
         ("Policy", r"subsid|import dut|\bpli\b|\bmsp\b"),
         ("Demand", r"demand|destocking|inventory|monsoon|sowing"),
     ]),
    ("Automobiles", ("auto", "vehicle", "wheeler", "passenger car", "tractor", "truck", "tyre",
                     "tire", "motorcycle"),
     'India auto (sales OR "vehicle registrations" OR EV OR "GST" OR "rare earth")', [
         ("Sales volumes", r"sales|dispatches|registrations?|\bfada\b|\bsiam\b|bookings?|inventory"),
         ("Electric vehicles", r"\bevs?\b|electric|battery|charging|\bfame\b|\bpm e-?drive\b"),
         ("Tax and policy", r"\bgst\b|cess|emission|\bcafe\b|scrappage|\bpli\b"),
         ("Input costs", r"commodit|steel prices?|rubber|rare earth|chip|semiconductor"),
     ]),
    ("Consumer goods", ("packaged food", "household", "personal", "beverage", "tobacco", "confection",
                        "fmcg", "food", "dairy", "sugar", "edible"),
     'India FMCG ("rural demand" OR "price hikes" OR "input costs" OR GST OR monsoon)', [
         ("Demand", r"rural|urban demand|volume growth|demand|consumption"),
         ("Input costs", r"palm oil|wheat|input costs?|inflation|commodit|raw material|sugar prices?"),
         ("Tax and policy", r"\bgst\b|cess|\bmsp\b|excise"),
         ("Pricing", r"price hikes?|price cuts?|grammage"),
     ]),
    ("Retail and apparel", ("retail", "apparel", "luxury", "department", "footwear", "jewel",
                            "textile", "garment"),
     'India (retail OR apparel OR jewellery) (demand OR "festive sales" OR GST OR "gold prices" OR tariffs)', [
         ("Demand", r"festive|footfall|same-?store|demand|consumption|wedding"),
         ("Gold and cotton", r"gold prices?|cotton|yarn"),
         ("Tax and tariffs", r"\bgst\b|tariff|import dut|export"),
     ]),
    ("Real estate", ("real estate", "realty", "residential", "housing"),
     'India real estate ("housing sales" OR "home loans" OR launches OR prices OR RERA)', [
         ("Housing demand", r"housing sales|bookings?|pre-?sales|launches|unsold|inventory"),
         ("Interest rates", r"home loans?|repo rate|rate cut|rate hike|\bemi\b"),
         ("Prices and regulation", r"property prices?|\brera\b|stamp duty|circle rates?"),
     ]),
    ("Capital goods and infrastructure", ("machinery", "electrical equipment", "engineering",
                                          "construction", "aerospace", "defen", "infrastructure",
                                          "conglomerate", "railway", "cable", "industrial"),
     'India (capex OR "order inflows" OR "defence orders" OR infrastructure OR railways) companies', [
         ("Orders", r"order (book|inflow|win)|orders? worth|bags|contract|letter of award"),
         ("Government spending", r"capex|budget|infrastructure|tender|allocation|\bnhai\b|railways?"),
         ("Defence", r"defence|defense|\bdac\b|\bdrdo\b|indigenis"),
     ]),
    ("Power and utilities", ("utilit", "power", "electric", "renewable", "solar", "wind"),
     'India power sector (demand OR tariffs OR coal OR renewables OR discoms)', [
         ("Power demand", r"power demand|peak demand|electricity (demand|consumption)|heat ?wave"),
         ("Tariffs and discoms", r"tariff|discom|\bcerc\b|\bserc\b|dues|regulator"),
         ("Fuel and renewables", r"coal|renewable|solar|wind|storage|\bgas\b"),
     ]),
    ("Telecom", ("telecom",),
     'India telecom (tariffs OR ARPU OR spectrum OR AGR OR subscribers)', [
         ("Tariffs and ARPU", r"tariff|\barpu\b|price hike|plans?"),
         ("Spectrum and dues", r"spectrum|\bagr\b|dues|auction|\btrai\b|\bdot\b"),
         ("Subscribers", r"subscriber|users? (add|los)|5g"),
     ]),
    ("Travel and hotels", ("airline", "lodging", "travel", "hotel", "restaurant", "leisure"),
     'India (airlines OR hotels OR travel) (fares OR "jet fuel" OR occupancy OR traffic OR DGCA)', [
         ("Demand", r"traffic|passengers?|occupancy|bookings?|fares?|room rates?"),
         ("Fuel costs", r"jet fuel|\batf\b|crude"),
         ("Regulation", r"\bdgca\b|regulat|norms\b|slots?"),
     ]),
    ("Media", ("entertainment", "broadcast", "publish", "media", "advertis"),
     'India (media OR broadcasting OR streaming) (advertising OR TRAI OR subscriptions OR merger)', [
         ("Advertising", r"advertis|ad (revenue|spend)"),
         ("Regulation", r"\btrai\b|regulat|tariff order"),
     ]),
    ("Logistics and ports", ("logistic", "shipping", "marine", "railroad", "trucking", "port",
                             "freight", "courier"),
     'India (logistics OR ports OR shipping) (freight OR cargo OR volumes OR "Red Sea" OR rates)', [
         ("Freight and cargo", r"freight|cargo|container|volumes?|rates?"),
         ("Routes and trade", r"red sea|suez|tariff|exports?|imports?"),
     ]),
]

# Where the industry is not named, or names nothing above, the sector says
# enough to ask a useful search.
SECTOR_GROUP = {
    "Technology": "IT services", "Healthcare": "Pharma",
    "Consumer Defensive": "Consumer goods", "Basic Materials": "Metals and mining",
    "Energy": "Oil and gas", "Utilities": "Power and utilities",
    "Industrials": "Capital goods and infrastructure", "Real Estate": "Real estate",
    "Communication Services": "Telecom", "Financial Services": "Lenders and NBFCs",
}

_BY_LABEL = {g[0]: g for g in GROUPS}
_DRIVERS = {g[0]: [(n, re.compile(rx, re.I)) for n, rx in g[3]] for g in GROUPS}


def group_for(sector, industry, free=True):
    """
    (label, search, drivers) for a company's kind of business, or the
    industry's own name as the search when no row fits it.

    `free=False` leaves that last step out. A caller passes it when the
    industry came from a request and not from the server's own records: the
    words in a query string are allowed to pick one of the searches written
    in this file, never to become a search themselves.
    """
    ind = str(industry or "").strip().lower()
    for label, words, query, _drivers in GROUPS:
        if ind and any(w in ind for w in words):
            return label, query, _DRIVERS[label]
    label = SECTOR_GROUP.get(str(sector or "").strip())
    if label:
        return label, _BY_LABEL[label][2], _DRIVERS[label]
    named = str(industry or sector or "").strip()
    if not named or not free:
        return None, None, []
    return named, '"%s" India' % re.sub(r'["\\]', "", named)[:60], []


def driver_of(headline, drivers):
    for name, rx in drivers:
        if rx.search(headline or ""):
            return name
    return None


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------

def _when(text):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = dt.datetime.strptime((text or "").strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _safe_url(url):
    u = str(url or "").strip()
    return u if re.match(r"^https?://[^\s<>\"']+$", u) else None


def parse(xml_bytes, now=None):
    """A search's RSS -> rows in news_feed's shape. Returns [] for anything
    that is not RSS; never raises."""
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for it in root.iter("item"):
        title = _html.unescape((it.findtext("title") or "").strip())
        url = _safe_url(it.findtext("link"))
        if not title or not url:
            continue
        source = _html.unescape((it.findtext("source") or "").strip())
        # The search writes "Headline - Publication". The publication has its
        # own field, so it is taken off the headline rather than shown twice.
        if source and title.endswith(" - " + source):
            title = title[:-(len(source) + 3)].strip()
        when = _when(it.findtext("pubDate"))
        rows.append({
            "headline": title[:300],
            "url": url,
            "source": source[:60] or "Press",
            "when_iso": when.isoformat() if when else None,
            "age_minutes": int((now - when).total_seconds() / 60) if when else None,
            "kind": "press",
        })
    return rows


def _fetch(query):
    """One search. Rows, or None when it was not answered."""
    if requests is None:
        return None
    try:
        r = requests.get(SEARCH, params=dict(SEARCH_PARAMS, q=query), headers=UA,
                         timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return parse(r.content)
    except Exception:
        return None


def search(query, fetch=None):
    """A search, remembered for twenty minutes. A failed one is remembered for
    three, so a search engine having a bad minute is not asked on every view."""
    if not query:
        return None
    now = time.time()
    with _lock:
        hit = _memo.get(query)
        if hit and now - hit[0] < (TTL if hit[1] is not None else TTL_FAILED):
            _memo.move_to_end(query)
            return hit[1]
    if fetch is None and now < _trip["until"]:
        return None
    rows = (fetch or _fetch)(query)
    if fetch is None:
        if rows is None:
            _trip["fails"] += 1
            if _trip["fails"] >= TRIP_AFTER:
                _trip.update(fails=0, until=now + TRIP_FOR)
        else:
            _trip["fails"] = 0
    with _lock:
        _memo[query] = (now, rows)
        _memo.move_to_end(query)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return rows


def _key(headline):
    return re.sub(r"[^a-z0-9]+", "", _norm(headline))[:64]


def _fresh(rows, days):
    cap = days * 24 * 60
    return [r for r in rows if r.get("age_minutes") is None or 0 <= r["age_minutes"] <= cap] \
        if rows else []


def _newest_first(rows):
    return sorted(rows, key=lambda r: r.get("when_iso") or "", reverse=True)


def _dedupe(rows, seen=None):
    seen = set() if seen is None else seen
    out = []
    for r in rows:
        k = _key(r["headline"])
        if k and k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _feed_rows(symbols=None, sector=""):
    """What the four market feeds already hold, without waiting on them."""
    if news_feed is None:
        return []
    try:
        return [dict(r) for r in news_feed.feed(limit=40, symbols=symbols, sector=sector,
                                                max_age_hours=COMPANY_DAYS * 24)]
    except Exception:
        return []


def for_stock(symbol, name=None, sector=None, industry=None, fetch=None, parallel=True,
              free_industry=True):
    """
    The two press lists for one company's page.

    `company.rows` are headlines that name the company. `industry.rows` are
    headlines about its kind of business, each with the `driver` it mentions
    where it mentions one; the ones that do come first. A headline in the
    first list is never repeated in the second.

    `name` is the server's own record of the company's name: it becomes a
    search, so it is never taken from a request. With no name there is no
    company search. `free_industry=False` says the sector and industry are a
    request's, and may only choose among the searches in GROUPS.
    """
    sym = re.sub(r"\.(NS|BO)$", "", str(symbol or "").strip().upper())
    patterns, _plain = aliases_for(sym, name or sym)
    cq = company_query(sym, name or "")
    label, iq, drivers = group_for(sector, industry, free=free_industry)

    if parallel and fetch is None:
        jobs = [_pool.submit(search, q) if q else None for q in (cq, iq)]
        got = []
        deadline = time.time() + WAIT
        for j in jobs:
            try:
                got.append(j.result(timeout=max(0.1, deadline - time.time())) if j else None)
            except Exception:
                got.append(None)
        c_found, i_found = got
    else:
        c_found = search(cq, fetch) if cq else None
        i_found = search(iq, fetch) if iq else None

    seen = set()
    c_rows = [r for r in _fresh(c_found, COMPANY_DAYS) if mentions(r["headline"], patterns)]
    c_rows += [r for r in _feed_rows(symbols=[sym]) if sym in (r.get("symbols") or [])]
    c_rows = _dedupe(_newest_first(c_rows), seen)[:COMPANY_LIMIT]

    i_rows = list(_fresh(i_found, INDUSTRY_DAYS))
    if sector:
        i_rows += [r for r in _feed_rows(sector=sector)
                   if sector in (r.get("sectors") or []) and
                   (r.get("age_minutes") or 0) <= INDUSTRY_DAYS * 24 * 60]
    i_rows = [r for r in i_rows if not mentions(r["headline"], patterns)]
    i_rows = _dedupe(_newest_first(i_rows), seen)
    for r in i_rows:
        r["driver"] = driver_of(r["headline"], drivers)
    # Stable: newest first inside each half, the tagged half on top.
    i_rows = ([r for r in i_rows if r["driver"]] + [r for r in i_rows if not r["driver"]])
    i_rows = i_rows[:INDUSTRY_LIMIT]

    def clean(r):
        return {k: r.get(k) for k in ("headline", "url", "source", "when_iso", "age_minutes",
                                      "kind", "driver") if k in r}

    return {
        "symbol": sym,
        "kind": "press",
        "company": {"rows": [clean(r) for r in c_rows], "searched": c_found is not None,
                    "days": COMPANY_DAYS},
        "industry": {"label": label, "rows": [clean(r) for r in i_rows],
                     "searched": i_found is not None, "days": INDUSTRY_DAYS,
                     "drivers": [n for n, _rx in drivers]},
        "note": ("Press coverage as published, with the publication named. "
                 "Company filings are listed separately."),
    }
