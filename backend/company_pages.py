"""
company_pages.py — one address per company, readable without JavaScript

WHY THIS EXISTS
Every company used to be the same page: stock.html, with the symbol in the
query string, an empty <h1> and a script that fetched everything. A search
engine that asked for it got a title of "Stock — Altaha Screener" and no
words. So nobody could arrive from a search for a company's name, which is
how people arrive at a screener.

This gives every company its own address, and puts the name, the price, the
figures it has filed and links to its peers in the HTML the server sends:

    /stock-RELIANCE     one company (render_company)
    /sector-technology  one sector, its companies largest first (render_sector)
    /stocks             every company, A to Z (render_directory)
    /sitemap.xml        the list a search engine is handed (sitemap)

The site's own domain serves all four; frontend/vercel.json proxies them to
the routes in main.py, as it does /share and /og.

IT IS THE STOCK PAGE, NOT A COPY OF IT
render_company() takes the deployed stock.html and fills it in: the title,
the description, the canonical address, the <h1>, the price, and one section
of filed figures at the foot. The page's own scripts then run as they always
have and draw the chart, the score and the panes. One page per company, so
there is nothing for a search engine to choose between and nothing to keep in
step. Two comment markers in stock.html say where the head tags and the
section go; test_company_pages.py fails if either is removed.

WHY THE ADDRESS IS /stock-SYMBOL AND NOT /stock/SYMBOL
Every asset and every link on the site is relative ("stock.css", "./",
"stock.html?ticker="). One level down, each of them resolves under /stock/
and is a 404. A <base> tag fixes that and breaks "#" links and, in some
browsers, the chart's url(#gradient) fills. A single path segment needs
neither. A sector is /sector-NAME for the same reason.

WHAT THE PAGE ANSWERS
People search for a company with a question: its revenue and profit, its ROE
and ROCE, who owns it, who its peers are. faq() answers those in sentences,
from the same row as everything else, and each answer is left out whole when
its figures are missing. The questions are printed on the page and repeated
as FAQPage structured data from the one list, so the two cannot disagree.

NOTHING HERE GOES OVER THE NETWORK FOR A PAGE
Every figure comes from fundamentals_query's snapshot row (the same row the
query screener filters) and the stored quarterly results, both local. A
crawler asking for two thousand pages must cost two thousand dictionary
lookups, not two thousand trips to an exchange. The one fetch is the
template, from the site, cached, and only when the file is not on disk.

FIGURES, NOT ADVICE
The section states what the company filed and what the market paid at the
last close. No verdict, no target, nothing to act on: the same line the rest
of the stock page holds.

NO EXTERNAL DEPENDENCIES beyond `requests` for the template, imported only
when it is needed.
"""

import datetime
import html
import json
import os
import re
import threading
import time
from urllib.parse import quote

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&.\-]{0,19}$")

HEAD_MARK = "<!-- ssr:head -->"
GLANCE_MARK = "<!-- ssr:glance -->"

# Static pages worth handing to a search engine beside the companies. Each is
# a file or a rewrite on the site (test_company_pages.py checks every one).
SITE_PAGES = ("/", "/stocks", "/brief", "/advisors", "/glossary", "/methodology", "/planner")

# A sector gets a page of its own once it has this many companies. Fewer is
# not a list, and a page of two links is one a search engine is right to skip.
SECTOR_MIN = 5

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def clean_symbol(raw):
    """'reliance.ns' -> 'RELIANCE'; None for anything that is not a symbol."""
    s = re.sub(r"\.(NS|BO)$", "", str(raw or "").strip().upper())
    return s if SYMBOL_RE.match(s) else None


def path_for(symbol):
    """/stock-M%26M. The ampersand is escaped so it survives every proxy."""
    return "/stock-" + quote(str(symbol), safe="-.")


def eligible(row):
    """A row that can carry a page: a real symbol and a name to put on it."""
    return bool(row and clean_symbol(row.get("symbol")) and row.get("name"))


def index(rows):
    """{symbol: row} for every company that gets a page."""
    return {r["symbol"]: r for r in (rows or []) if eligible(r)}


def slug_for(name):
    """'Financial Services' -> 'financial-services'; None for nothing usable."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:60].strip("-")
    return s or None


def sector_path(slug):
    return "/sector-" + slug


def _by_size(r):
    """Largest first; a company with no market value goes last, by symbol."""
    return (-(_num(r.get("market_cap")) or 0.0), r["symbol"])


def sectors(rows):
    """
    {slug: (name, [row, ...])} for every sector with a page, its companies
    largest first. Two spellings that make the same slug are one sector, under
    the first name seen.
    """
    found = {}
    for r in rows or []:
        s = slug_for(r.get("sector")) if eligible(r) else None
        if s:
            found.setdefault(s, (r["sector"], []))[1].append(r)
    out = {}
    for s, (name, members) in found.items():
        if len(members) >= SECTOR_MIN:
            out[s] = (name, sorted(members, key=_by_size))
    return out


def sector_of(row, rows):
    """(name, path, companies) for the row's sector page; None when it has none.
    A count, not a sort: this runs for every company page."""
    s = slug_for(row.get("sector"))
    if not s:
        return None
    n = sum(1 for r in rows or [] if eligible(r) and slug_for(r.get("sector")) == s)
    return (row["sector"], sector_path(s), n) if n >= SECTOR_MIN else None


# ---------------------------------------------------------------------------
# Figures as words
# ---------------------------------------------------------------------------

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def group_in(n, dp=0):
    """Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    neg = n < 0
    whole, _, frac = ("%.*f" % (dp, abs(n))).partition(".")
    if len(whole) > 3:
        head, tail, parts = whole[:-3], whole[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("−" if neg else "") + whole + ("." + frac if frac else "")


def _sign(n):
    """The minus goes before the rupee sign: −₹24, never ₹−24."""
    return "−" if n < 0 else ""


def rupees(v, dp=2):
    n = _num(v)
    return None if n is None else _sign(n) + "₹" + group_in(abs(n), dp)


def crore(v):
    """A ₹ crore amount for a table cell: no decimals once it is three digits."""
    n = _num(v)
    if n is None:
        return None
    return group_in(n, 0 if abs(n) >= 100 else (1 if abs(n) >= 10 else 2))


def crore_words(v):
    """A ₹ crore amount in a sentence: '₹16.21 lakh crore', '₹12,500 crore'."""
    n = _num(v)
    if n is None:
        return None
    if abs(n) >= 1e5:
        return "%s₹%.2f lakh crore" % (_sign(n), abs(n) / 1e5)
    return _sign(n) + "₹" + crore(abs(n)) + " crore"


def pct(v, dp=1):
    n = _num(v)
    return None if n is None else "%.*f%%" % (dp, n)


def signed_pct(v, dp=1):
    """A change: '+10.5%', '−2.4%'. The same minus the money columns use."""
    n = _num(v)
    if n is None:
        return None
    return ("+" if n > 0 else _sign(n)) + "%.*f%%" % (dp, abs(n))


def times(v, dp=1):
    n = _num(v)
    return None if n is None else "%.*f" % (dp, n)


def long_date(iso):
    """'2026-06-30' -> '30 June 2026'; None for anything else."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return "%d %s %s" % (int(m.group(3)), MONTHS[int(m.group(2)) - 1], m.group(1))


def _moved(growth):
    """', up 10.5% on a year earlier' — or nothing, when there is no honest
    percentage (the snapshot leaves growth across a loss as None)."""
    g = _num(growth)
    if g is None:
        return ""
    if abs(g) < 0.05:
        return ", level with a year earlier"
    return ", %s %s on a year earlier" % ("up" if g > 0 else "down", pct(abs(g)))


def _profit(v):
    """'a profit after tax of ₹22,290 crore' / 'a loss of ₹4,300 crore'."""
    n = _num(v)
    if n is None:
        return None
    return ("a profit after tax of " if n >= 0 else "a loss of ") + crore_words(abs(n))


def lede(row):
    """
    The paragraph: what the company is, what it is valued at, what it last
    reported. Each sentence is left out whole when its figures are missing, so
    a thinly covered company gets a shorter paragraph and never a blank in one.
    """
    sym, name = row["symbol"], row["name"]
    out = []

    where = "%s (NSE: %s) is listed on the National Stock Exchange of India" % (name, sym)
    if row.get("industry"):
        where += ", where it is classified under %s" % row["industry"]
        if row.get("sector") and row["sector"] != row["industry"]:
            where += " in the %s sector" % row["sector"]
    out.append(where + ".")

    price, mcap, pe = rupees(row.get("price")), crore_words(row.get("market_cap")), times(row.get("pe"))
    if price and mcap:
        s = "At its last close of %s a share the company is valued at %s" % (price, mcap)
        if pe:
            s += ", %s times its earnings over the last four quarters" % pe
        out.append(s + ".")
    elif price:
        out.append("Its last close was %s a share." % price)

    q_end = long_date(row.get("quarter"))
    q_sales, q_profit = crore_words(row.get("sales_qtr")), _profit(row.get("net_profit_qtr"))
    if q_end and (q_sales or q_profit):
        bits = []
        if q_sales:
            bits.append("revenue of %s%s" % (q_sales, _moved(row.get("sales_growth_qtr"))))
        if q_profit:
            bits.append(q_profit)
        out.append("For the quarter ended %s it reported %s." % (q_end, " and ".join(bits)))

    fy, sales, profit = row.get("fy"), crore_words(row.get("sales")), _profit(row.get("net_profit"))
    if fy and sales and profit:
        s = "Over %s, revenue was %s with %s" % (fy, sales, profit)
        roe, roce = pct(row.get("roe")), pct(row.get("roce"))
        if roe and roce:
            s += "; return on equity was %s and return on capital employed %s" % (roe, roce)
        out.append(s + ".")

    prom = pct(row.get("promoter_holding"), 2)
    if prom:
        s = "Promoters hold %s of the company" % prom
        pledged = _num(row.get("pledged"))
        if pledged is not None:
            s += (", with none of it pledged" if pledged <= 0
                  else ", and %s of all shares are pledged" % pct(pledged, 2))
        out.append(s + ".")
    return out


def facts(row):
    """[(label, value)] for the grid. A figure that is not known is left out."""
    fy = row.get("fy")
    of_year = " (%s)" % fy if fy else ""
    cells = [
        ("Market cap", crore_words(row.get("market_cap"))),
        ("P/E", times(row.get("pe"))),
        ("Price to book", times(row.get("pb"), 2)),
        ("Dividend yield", pct(row.get("dividend_yield"), 2)),
        ("ROE", pct(row.get("roe"))),
        ("ROCE", pct(row.get("roce"))),
        ("Debt to equity", times(row.get("debt_to_equity"), 2)),
        ("Operating margin", pct(row.get("opm"))),
        ("Revenue" + of_year, crore_words(row.get("sales"))),
        ("Profit after tax" + of_year, crore_words(row.get("net_profit"))),
        ("Revenue growth, 3 years", pct(row.get("sales_growth_3y"))),
        ("Profit growth, 3 years", pct(row.get("profit_growth_3y"))),
        ("Promoter holding", pct(row.get("promoter_holding"), 2)),
        ("FII holding", pct(row.get("fii_holding"), 2)),
        ("DII holding", pct(row.get("dii_holding"), 2)),
    ]
    return [(k, v) for k, v in cells if v]


def quarters_for(row, records, limit=8):
    """
    The company's last quarters, newest first, on ONE accounting basis.

    The store holds standalone and consolidated side by side, and a group's
    two differ by more than a factor of two (FUNDAMENTALS.md). The row already
    says which basis its figures use; a table that mixed them would print that
    difference as a collapse. Where the row names no basis, the first one seen
    is kept for the whole table.
    """
    basis, out = row.get("basis"), []
    for r in sorted(records or [], key=lambda r: str(r.get("period_end") or ""), reverse=True):
        if r.get("freq") not in (None, "quarterly"):
            continue
        basis = basis or r.get("basis")
        if r.get("basis") != basis:
            continue
        if _num(r.get("revenue_cr")) is None and _num(r.get("pat_cr")) is None:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def peers(row, rows, n=12):
    """
    Up to n companies in the same industry, the ones nearest it in size.

    Nearest, not largest: if every pharma company linked to the same twelve
    large ones, the small ones would have a page nobody links to. Taken as a
    window around the company in its industry's size order, every company in
    an industry is linked from its neighbours.
    """
    key = "industry" if row.get("industry") else ("sector" if row.get("sector") else None)
    if not key:
        return []
    pool = [r for r in rows if eligible(r) and r.get(key) == row[key]]
    pool.sort(key=_by_size)
    at = next((i for i, r in enumerate(pool) if r["symbol"] == row["symbol"]), 0)
    others = [r for r in pool if r["symbol"] != row["symbol"]]
    start = max(0, min(at - n // 2, len(others) - n))
    return others[start:start + n]


def _and(items):
    """['A', 'B', 'C'] -> 'A, B and C'."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def faq(row, rows, score=None):
    """
    [(question, answer, answer_html)]: what people ask a search engine about a
    company, answered from its row. The answer is plain text, for the
    structured data; the HTML is the same words with the companies linked.

    The rule is lede()'s: a question whose figures are missing is not asked.
    Nothing here is a view on the share, only what was filed and what was paid.
    """
    sym, name = row["symbol"], row["name"]
    whose = name + "’s"
    out = []

    def add(question, answer, answer_html=None):
        out.append((question, answer, esc(answer) if answer_html is None else answer_html))

    price, mcap, pe = rupees(row.get("price")), crore_words(row.get("market_cap")), times(row.get("pe"))
    if price:
        a = "%s (NSE: %s) last closed at %s a share" % (name, sym, price)
        if mcap:
            a += ", which values the company at %s" % mcap
        a += "."
        if pe:
            a += " Its P/E on the earnings of the last four quarters is %s." % pe
        add("What is %s share price%s?" % (whose, " and market cap" if mcap else ""), a)

    said = []
    q_end = long_date(row.get("quarter"))
    q_sales, q_profit = crore_words(row.get("sales_qtr")), _profit(row.get("net_profit_qtr"))
    if q_end and (q_sales or q_profit):
        bits = []
        if q_sales:
            bits.append("revenue of %s%s" % (q_sales, _moved(row.get("sales_growth_qtr"))))
        if q_profit:
            bits.append(q_profit)
        said.append("For the quarter ended %s, %s reported %s." % (q_end, name, " and ".join(bits)))
    fy, sales, profit = row.get("fy"), crore_words(row.get("sales")), _profit(row.get("net_profit"))
    if fy and sales and profit:
        said.append("Over %s, revenue was %s with %s." % (fy, sales, profit))
    if said:
        add("What is %s latest revenue and profit after tax (PAT)?" % whose, " ".join(said))

    roe, roce = pct(row.get("roe")), pct(row.get("roce"))
    when = "Over %s, " % fy if fy else ""
    if roe and roce:
        add("What is %s ROE and ROCE?" % whose,
            "%s%s return on equity (ROE) was %s and its return on capital employed (ROCE) was %s."
            % (when, whose, roe, roce))
    elif roe:
        add("What is %s ROE?" % whose, "%s%s return on equity (ROE) was %s." % (when, whose, roe))
    elif roce:
        add("What is %s ROCE?" % whose,
            "%s%s return on capital employed (ROCE) was %s." % (when, whose, roce))

    prom = pct(row.get("promoter_holding"), 2)
    if prom:
        a = "Promoters hold %s of %s" % (prom, name)
        others = ["%s hold %s" % (who, v) for who, v in (
            ("foreign institutional investors (FIIs)", pct(row.get("fii_holding"), 2)),
            ("domestic institutional investors (DIIs)", pct(row.get("dii_holding"), 2))) if v]
        if others:
            a += "; " + " and ".join(others)
        a += "."
        pledged = _num(row.get("pledged"))
        if pledged is not None:
            a += (" No part of the promoter holding is pledged." if pledged <= 0
                  else " %s of all shares are pledged." % pct(pledged, 2))
        add("What is %s shareholding pattern?" % whose, a)

    near = peers(row, rows, n=5)
    if near:
        group = row.get("industry") or row.get("sector")
        one = len(near) == 1
        lead = "%s is classified under %s. Its nearest %s there by market value %s " % (
            name, group, "peer" if one else "peers", "is" if one else "are")
        a = lead + _and(p["name"] for p in near) + "."
        h = esc(lead) + _and('<a href="%s">%s</a>' % (esc(path_for(p["symbol"])), esc(p["name"]))
                             for p in near) + "."
        hub = sector_of(row, rows)
        if hub:
            link = "%s sector page" % hub[0]
            rest = " lists all %s companies in the sector." % group_in(hub[2])
            a += " The " + link + rest
            h += ' The <a href="%s">%s</a>%s' % (esc(hub[1]), esc(link), esc(rest))
        add("Who are %s sector peers?" % whose, a, h)

    if score is not None:
        add("What is %s Altaha Score?" % whose,
            "%s Altaha Score was %d out of 100 at the last scan. It is a rank against peers on "
            "disclosed weights, not a forecast." % (whose, round(score)))
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def _json_script(obj):
    """JSON safe to sit inside <script>: nothing in it can close the element."""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def title_for(row):
    sym, name = row["symbol"], row["name"]
    who = name if name.upper() == sym else "%s (%s)" % (name, sym)
    return "%s share price, score and fundamentals | Altaha Screener" % who


def description_for(row):
    sym, name = row["symbol"], row["name"]
    bits = []
    for label, v in (("share price", rupees(row.get("price"))),
                     ("market cap", crore_words(row.get("market_cap"))),
                     ("P/E", times(row.get("pe"))),
                     ("ROE", pct(row.get("roe")))):
        if v:
            bits.append("%s %s" % (label, v))
    lead = "%s (NSE: %s)" % (name, sym) + (": " + ", ".join(bits) + ". " if bits else ". ")
    return (lead + "Quarterly results as filed, who owns it, delivery volumes and a "
            "0 to 100 Altaha Score with every calculation shown.")


def head_tags(row, site, score=None, qa=None):
    """
    Canonical, the share card, structured data and the flag stock.js reads.

    The structured data names the company as well as the page. schema.org
    writes a ticker with its exchange in front ("NSE ACME") and has no
    separate property for the exchange. The company's `url` would be its own
    website, which the row does not carry, so the node points back at this
    page instead. `qa` is faq()'s list: the questions printed on the page.
    """
    sym, name = row["symbol"], row["name"]
    url = site + path_for(sym)
    title, desc = title_for(row), description_for(row)
    image = "%s/og/stock.png?ticker=%s" % (site, quote(sym, safe=""))
    company = {"@type": "Corporation", "@id": url + "#company", "name": name,
               "tickerSymbol": "NSE " + sym}
    graph = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Altaha Screener", "item": site + "/"},
            {"@type": "ListItem", "position": 2, "name": "All companies", "item": site + "/stocks"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url}]},
        {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc,
         "isPartOf": {"@type": "WebSite", "name": "Altaha Screener", "url": site + "/"},
         "about": company},
        dict(company, mainEntityOfPage={"@id": url}),
    ]
    if qa:
        graph.append({"@type": "FAQPage", "@id": url + "#faq", "isPartOf": {"@id": url},
                      "mainEntity": [{"@type": "Question", "name": q,
                                      "acceptedAnswer": {"@type": "Answer", "text": a}}
                                     for q, a, _h in qa]})
    ld = {"@context": "https://schema.org", "@graph": graph}
    return "\n".join([
        '<link rel="canonical" href="%s" />' % esc(url),
        '<meta property="og:type" content="website" />',
        '<meta property="og:site_name" content="Altaha Screener" />',
        '<meta property="og:title" content="%s" />' % esc(title),
        '<meta property="og:description" content="%s" />' % esc(desc),
        '<meta property="og:url" content="%s" />' % esc(url),
        '<meta property="og:image" content="%s" />' % esc(image),
        '<meta name="twitter:card" content="summary_large_image" />',
        '<script type="application/ld+json">%s</script>' % _json_script(ld),
        "<script>window.ALTAHA_SSR=%s;</script>" % _json_script({"ticker": sym}),
    ])


def glance_html(row, rows, quarters=None, score=None, qa=None):
    """
    The section at the foot of the page: the paragraph, the figures, the last
    quarters, the questions and the neighbours. It is ordinary page content.
    A reader sees it under the panes; a crawler reads it as the page.
    """
    name = row["name"]
    out = ['<section class="stk-sec stk-glance" id="glance" aria-labelledby="glance-h">',
           '<h2 id="glance-h">%s at a glance</h2>' % esc(name)]
    basis = row.get("basis")
    out.append('<p class="sub">From the company’s own filings with NSE%s. '
               'Figures, not advice.</p>'
               % (", on a %s basis" % esc(basis) if basis in ("consolidated", "standalone") else ""))
    out.append('<p class="gl-lede">%s</p>' % " ".join(esc(s) for s in lede(row)))

    if score is not None:
        out.append('<p class="gl-score">Altaha Score: <b>%d</b> out of 100 at the last scan. '
                   'It ranks the company against its peers; it is not a forecast.</p>'
                   % round(score))

    cells = facts(row)
    if cells:
        out.append('<dl class="gl-facts">%s</dl>' % "".join(
            "<div><dt>%s</dt><dd>%s</dd></div>" % (esc(k), esc(v)) for k, v in cells))

    qs = quarters_for(row, quarters)
    if qs:
        body = []
        for q in qs:
            label = q.get("label") or long_date(q.get("period_end")) or ""
            body.append(
                "<tr><th scope=\"row\">%s</th><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    esc(label),
                    esc(crore(q.get("revenue_cr")) or "—"),
                    esc(crore(q.get("pat_cr")) or "—"),
                    esc(group_in(_num(q.get("eps_basic")), 2) if _num(q.get("eps_basic")) is not None else "—"),
                    esc(signed_pct(q.get("revenue_yoy_pct")) or "—")))
        out.append(
            '<h3>Quarterly results</h3>'
            '<div class="gl-scroll"><table class="gl-table">'
            '<caption>%s quarterly results, ₹ crore, as filed</caption>'
            '<thead><tr><th scope="col">Quarter</th><th scope="col">Revenue</th>'
            '<th scope="col">Profit after tax</th><th scope="col">EPS (₹)</th>'
            '<th scope="col">Revenue vs a year earlier</th></tr></thead>'
            '<tbody>%s</tbody></table></div>' % (esc(name), "".join(body)))

    qa = faq(row, rows, score) if qa is None else qa
    if qa:
        out.append('<h3>Questions about %s</h3><div class="gl-faq">%s</div>' % (
            esc(name), "".join('<div class="gl-qa"><h4>%s</h4><p>%s</p></div>' % (esc(q), h)
                               for q, _a, h in qa)))

    near = peers(row, rows)
    if near:
        group = row.get("industry") or row.get("sector")
        out.append('<h3>Other %s companies</h3><ul class="gl-peers">%s</ul>' % (
            esc(group), "".join(
                '<li><a href="%s">%s</a></li>' % (esc(path_for(p["symbol"])), esc(p["name"]))
                for p in near)))

    hub = sector_of(row, rows)
    out.append('<p class="gl-all">%s<a href="/stocks">All companies, A to Z</a></p>' % (
        '<a href="%s">All %s companies</a> · ' % (esc(hub[1]), esc(hub[0])) if hub else ""))
    out.append("</section>")
    return "\n".join(out)


def tags_html(row, rows):
    """
    The row under the name: the ticker as a search engine and a reader both
    write it ("NSE: ACME"), then the sector and the industry. The sector is a
    link when it has a page.
    """
    hub = sector_of(row, rows)
    out = ['<span class="stk-tag">NSE: %s</span>' % esc(row["symbol"])]
    if row.get("sector"):
        out.append('<a class="stk-tag" href="%s">%s</a>' % (esc(hub[1]), esc(row["sector"])) if hub
                   else '<span class="stk-tag">%s</span>' % esc(row["sector"]))
    if row.get("industry"):
        out.append('<span class="stk-tag">%s</span>' % esc(row["industry"]))
    return "".join(out)


def _sub(pattern, repl, text):
    """Replace the first match with a literal string; the text as it was if none."""
    return re.sub(pattern, lambda m: m.group(1) + repl + m.group(2), text, count=1, flags=re.S)


def render_company(template, row, rows, site, quarters=None, score=None):
    """stock.html, filled in for one company."""
    sym, name = row["symbol"], row["name"]
    page = template
    page = _sub(r"(<title>).*?(</title>)", esc(title_for(row)), page)
    page = _sub(r'(<meta name="description" content=")[^"]*(")', esc(description_for(row)), page)

    qa = faq(row, rows, score)
    page = page.replace(HEAD_MARK, head_tags(row, site, score, qa), 1)

    # What stock.js paints a moment later, already there: the name and the
    # last close. The tags are these ones for good: stock.js leaves the row
    # alone on this page, so the link to the sector stays a link.
    page = _sub(r'(<h1[^>]*\bid="nm"[^>]*>).*?(</h1>)', esc(name), page)
    page = _sub(r'(<span id="crumb">).*?(</span>)', esc(sym), page)
    page = _sub(r'(<div[^>]*\bid="tags"[^>]*>).*?(</div>)', tags_html(row, rows), page)
    if rupees(row.get("price")):
        page = _sub(r'(<div[^>]*\bid="px"[^>]*>).*?(</div>)', esc(rupees(row.get("price"))), page)

    return page.replace(GLANCE_MARK, glance_html(row, rows, quarters, score, qa), 1)


def _doc(site, api, title, description, body, path=None, robots="index,follow", head=""):
    """
    A page of the site's own, built here: the same stylesheets, the same
    header and footer (shell.js draws both), and whatever body it is given.
    Addresses are absolute so it reads the same from any path.
    """
    canonical = '<link rel="canonical" href="%s" />\n' % esc(site + path) if path else ""
    return """<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%(title)s</title>
<meta name="description" content="%(desc)s" />
<meta name="robots" content="%(robots)s" />
%(canonical)s<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" type="image/png" href="/icon-512.png" sizes="512x512" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<script src="/theme.js"></script>
<link rel="preload" as="font" type="font/woff2" href="/fonts/inter-latin.woff2" crossorigin>
<link rel="preload" as="font" type="font/woff2" href="/fonts/fraunces-latin.woff2" crossorigin>
<link rel="preload" as="font" type="font/woff2" href="/fonts/jetbrains-mono-latin.woff2" crossorigin>
<link rel="stylesheet" href="/tokens.css">
<link rel="stylesheet" href="/altaha-polish.css">
<link rel="stylesheet" href="/altaha-skin.css">
<link rel="stylesheet" href="/shell.css">
<link rel="stylesheet" href="/stock.css">
<link rel="stylesheet" href="/experience.css">
<link rel="stylesheet" href="/type.css">
<link rel="stylesheet" href="/components.css">
<script>
  var API_BASE = %(api)s;
</script>
%(head)s<script src="/analytics.js" defer></script>
<script src="/auth.js" defer></script>
</head>
<body>
<main class="stk-wrap">
%(body)s
</main>
<script src="/shell.js" defer></script>
<script src="/experience.js" defer></script>
</body>
</html>
""" % {"title": esc(title), "desc": esc(description), "robots": esc(robots),
       "canonical": canonical, "api": _json_script(api), "head": head, "body": body}


def render_plain(row, rows, site, api, quarters=None, score=None):
    """
    The company without stock.html, for the minute the template cannot be
    read. Everything a crawler needs is here; the chart and the panes are one
    link away. Never cached (main.py sends it no-store), so the full page
    returns as soon as the template does.
    """
    sym, name = row["symbol"], row["name"]
    qa = faq(row, rows, score)
    tags = tags_html(row, rows)
    body = (
        '<div class="stk-head">'
        '<div class="stk-crumb"><a href="/">Altaha Screener</a> · <a href="/stocks">All companies</a></div>'
        '<div class="stk-id"><div style="min-width:0"><h1 class="stk-name">%s</h1>'
        '<div class="stk-tags">%s</div></div>'
        '<div class="stk-px"><div class="now tnum">%s</div></div></div>'
        '<p class="gl-open"><a href="/stock?ticker=%s">Open the chart, the score and the full analysis</a></p>'
        '</div>%s' % (esc(name), tags, esc(rupees(row.get("price")) or "—"),
                      esc(quote(sym, safe="")), glance_html(row, rows, quarters, score, qa)))
    # The canonical is already in head_tags; _doc is given no path of its own.
    return _doc(site, api, title_for(row), description_for(row), body,
                head=head_tags(row, site, score, qa) + "\n")


def render_missing(raw, site, api):
    """A 404 that still says where to go. main.py sends it as a 404, noindex."""
    sym = clean_symbol(raw)
    body = ['<div class="stk-head"><div class="stk-crumb"><a href="/">Altaha Screener</a> · '
            '<a href="/stocks">All companies</a></div>',
            '<h1 class="stk-name">No company page for %s</h1></div>' % esc(sym or "that address"),
            '<section class="stk-sec"><p class="gl-lede">Company pages cover NSE-listed '
            'companies whose results have been read from the exchange. This one is not among them yet.</p>',
            '<p class="gl-all"><a href="/stocks">Find a company, A to Z</a></p>']
    if sym:
        body.append('<p class="gl-all"><a href="/stock?ticker=%s">Try the live analysis of %s</a></p>'
                    % (esc(quote(sym, safe="")), esc(sym)))
    body.append("</section>")
    return _doc(site, api, "No company page | Altaha Screener",
                "This address has no company page on Altaha Screener.",
                "\n".join(body), robots="noindex,follow")


def _median(values):
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2.0


def sector_title(name):
    return "%s stocks in India: NSE companies by market cap, P/E, ROE | Altaha Screener" % name


def render_sector(rows, slug, site, api):
    """
    One sector: every company in it, largest first, with the five figures a
    reader compares companies on, each linked to its page. None when there is
    no such sector, which main.py sends as a 404.

    It is the page for somebody who searched for a kind of company and not for
    one ("IT stocks in India"), and the shortest path from the front of the
    site to a small company's page: home, the list, its sector, the company.
    """
    found = sectors(rows)
    if slug not in found:
        return None
    name, members = found[slug]
    url, n = site + sector_path(slug), len(members)

    caps = [c for c in (_num(r.get("market_cap")) for r in members) if c and c > 0]
    pes = [p for p in (_num(r.get("pe")) for r in members) if p and p > 0]
    roes = [x for x in (_num(r.get("roe")) for r in members) if x is not None]
    said = ["%s NSE-listed companies are classified under %s." % (group_in(n), name)]
    if caps:
        said.append("Together they were valued at %s at their last close." % crore_words(sum(caps)))
    mid = []
    if len(pes) >= SECTOR_MIN:
        mid.append("P/E is %s" % times(_median(pes)))
    if len(roes) >= SECTOR_MIN:
        mid.append("return on equity is %s" % pct(_median(roes)))
    if mid:
        said.append("The median %s." % " and the median ".join(mid))
    said.append("They are listed largest first by market value, with figures from each "
                "company’s own filings.")

    by_industry = {}
    for r in members:
        if r.get("industry"):
            by_industry[r["industry"]] = by_industry.get(r["industry"], 0) + 1
    industries = sorted(by_industry.items(), key=lambda kv: (-kv[1], kv[0]))

    def cell(v):
        return esc(v or "—")

    body = ['<div class="stk-head"><div class="stk-crumb"><a href="/">Altaha Screener</a> · '
            '<a href="/stocks">All companies</a> · <span>%s</span></div>' % esc(name),
            '<h1 class="stk-name">%s stocks on NSE</h1>' % esc(name),
            '<p class="dir-sub">%s Figures, not advice.</p></div>' % esc(" ".join(said))]
    if len(industries) > 1:
        body.append('<p class="sec-inds"><b>Industries in this sector:</b> %s.</p>' % esc(
            ", ".join("%s (%s)" % (k, group_in(v)) for k, v in industries)))
    body.append(
        '<section class="sec-list" aria-label="%s companies"><div class="gl-scroll">'
        '<table class="gl-table sec-table"><caption>%s companies on NSE, largest first by '
        'market value. Price in ₹, market cap in ₹ crore.</caption>'
        '<thead><tr><th scope="col">Company</th><th scope="col">Industry</th>'
        '<th scope="col">Price</th><th scope="col">Market cap</th><th scope="col">P/E</th>'
        '<th scope="col">ROE</th><th scope="col">ROCE</th></tr></thead><tbody>%s</tbody></table>'
        '</div></section>' % (esc(name), esc(name), "".join(
            '<tr><th scope="row"><a href="%s">%s</a><span>%s</span></th><td>%s</td><td>%s</td>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(path_for(r["symbol"])), esc(r["name"]), esc(r["symbol"]),
                cell(r.get("industry")), cell(rupees(r.get("price"))), cell(crore(r.get("market_cap"))),
                cell(times(r.get("pe"))), cell(pct(r.get("roe"))), cell(pct(r.get("roce"))))
            for r in members)))
    others = [(s, v) for s, v in sorted(found.items(), key=lambda kv: kv[1][0]) if s != slug]
    more = "Other sectors" if others else "More companies"
    body.append('<nav class="dir-sectors" aria-label="%s"><h2>%s</h2><ul>%s'
                '<li><a href="/stocks">All companies, A to Z</a></li></ul></nav>' % (more, more, "".join(
                    '<li><a href="%s">%s</a><span>%s</span></li>' % (
                        esc(sector_path(s)), esc(v[0]), group_in(len(v[1]))) for s, v in others)))

    desc = ("%s NSE-listed %s companies ranked by market cap, with share price, P/E, ROE and "
            "ROCE from their filings. Open any company for quarterly results, shareholding and "
            "its Altaha Score." % (group_in(n), name))
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Altaha Screener", "item": site + "/"},
            {"@type": "ListItem", "position": 2, "name": "All companies", "item": site + "/stocks"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url}]},
        {"@type": "CollectionPage", "@id": url, "url": url, "name": sector_title(name),
         "description": desc,
         "isPartOf": {"@type": "WebSite", "name": "Altaha Screener", "url": site + "/"},
         # The largest thirty; the page itself links every one.
         "mainEntity": {"@type": "ItemList", "numberOfItems": n, "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "name": r["name"],
              "url": site + path_for(r["symbol"])} for i, r in enumerate(members[:30])]}},
    ]}
    return _doc(site, api, sector_title(name), desc, "\n".join(body), path=sector_path(slug),
                head='<script type="application/ld+json">%s</script>\n' % _json_script(ld))


def render_no_sector(site, api):
    """A 404 for a sector that is not one. main.py sends it noindex."""
    body = ('<div class="stk-head"><div class="stk-crumb"><a href="/">Altaha Screener</a> · '
            '<a href="/stocks">All companies</a></div>'
            '<h1 class="stk-name">No sector page at that address</h1></div>'
            '<section class="stk-sec"><p class="gl-lede">Sector pages list NSE-listed companies '
            'by the sector they are classified under. This address is not one of them.</p>'
            '<p class="gl-all"><a href="/stocks">Find a company or a sector</a></p></section>')
    return _doc(site, api, "No sector page | Altaha Screener",
                "This address has no sector page on Altaha Screener.", body,
                robots="noindex,follow")


def render_directory(rows, site, api):
    """Every company, A to Z, each linked to its page. The crawl's front door."""
    companies = sorted(index(rows).values(), key=lambda r: (r["name"].upper(), r["symbol"]))
    groups = {}
    for r in companies:
        first = r["name"].strip()[:1].upper()
        groups.setdefault(first if first.isalpha() else "0-9", []).append(r)
    letters = sorted(groups, key=lambda k: (k != "0-9", k))

    def anchor(letter):
        return "l-" + ("0" if letter == "0-9" else letter)

    body = ['<div class="stk-head"><div class="stk-crumb"><a href="/">Altaha Screener</a> · '
            '<span>All companies</span></div>',
            '<h1 class="stk-name">Every company, A to Z</h1>',
            '<p class="dir-sub">%s NSE-listed companies. Each page has the share price, the results '
            'the company filed, who owns it and its Altaha Score.</p></div>'
            % group_in(len(companies))]
    if not companies:
        body.append('<section class="stk-sec"><p class="gl-lede">The company list is being read. '
                    'Try again in a few minutes.</p></section>')
    else:
        body.append('<div class="dir-tools"><label class="dir-find"><span>Find a company</span>'
                    '<input type="search" id="dir-q" autocomplete="off" '
                    'placeholder="Name or symbol" /></label>'
                    '<nav class="dir-az" aria-label="Jump to a letter">%s</nav></div>'
                    % "".join('<a href="#%s">%s</a>' % (anchor(l), esc(l)) for l in letters))
        hubs = sorted(sectors(rows).items(), key=lambda kv: kv[1][0])
        if hubs:
            body.append('<nav class="dir-sectors" id="dir-sectors" aria-label="Browse by sector">'
                        '<h2>Browse by sector</h2><ul>%s</ul></nav>' % "".join(
                            '<li><a href="%s">%s</a><span>%s</span></li>' % (
                                esc(sector_path(s)), esc(v[0]), group_in(len(v[1]))) for s, v in hubs))
        body.append('<p class="dir-none" id="dir-none" hidden>No company matches that.</p>')
        for l in letters:
            items = "".join(
                '<li data-k="%s"><a href="%s">%s</a><span>%s</span></li>' % (
                    esc((r["name"] + " " + r["symbol"]).lower()), esc(path_for(r["symbol"])),
                    esc(r["name"]),
                    esc(" · ".join(x for x in (r["symbol"], r.get("industry")) if x)))
                for r in groups[l])
            body.append('<section class="dir-group" id="%s"><h2>%s</h2><ul class="dir-list">%s</ul></section>'
                        % (anchor(l), esc(l), items))
        # The filter only hides rows that are already in the page.
        body.append("""<script>
(function () {
  var q = document.getElementById('dir-q'), none = document.getElementById('dir-none');
  if (!q) return;
  q.addEventListener('input', function () {
    var want = q.value.trim().toLowerCase(), shown = 0;
    [].forEach.call(document.querySelectorAll('.dir-group'), function (g) {
      var n = 0;
      [].forEach.call(g.querySelectorAll('li'), function (li) {
        var hit = !want || li.getAttribute('data-k').indexOf(want) >= 0;
        li.hidden = !hit; if (hit) n++;
      });
      g.hidden = !n; shown += n;
    });
    none.hidden = shown > 0;
  });
})();
</script>""")
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Altaha Screener", "item": site + "/"},
        {"@type": "ListItem", "position": 2, "name": "All companies", "item": site + "/stocks"}]}
    return _doc(site, api, "All NSE companies, A to Z | Altaha Screener",
                "Every NSE-listed company on Altaha Screener, A to Z: share price, quarterly "
                "results as filed, shareholding and a 0 to 100 score with the working shown.",
                "\n".join(body), path="/stocks",
                head='<script type="application/ld+json">%s</script>\n' % _json_script(ld))


def _lastmod(raw, today=None):
    """'2026-08-12 18:04:11' -> '2026-08-12'; None unless it is a real day that
    has happened. A date in the future is a typing error at the exchange, and
    is worth less to a search engine than no date."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(raw or ""))
    if not m:
        return None
    try:
        day = datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    today = today or datetime.date.today()
    return day.isoformat() if datetime.date(2000, 1, 1) <= day <= today else None


def sitemap(rows, site, filed=None, today=None):
    """
    sitemap.xml: the site's own pages, the sectors, then one line per company.

    <lastmod> ONLY WHERE THERE IS A REAL DATE. A company's page changes in
    substance on the day it files results, and `filed` is {symbol: that day},
    read from the store (fundamentals_store.latest_filed). A company with no
    filing date on record gets no <lastmod>, and neither do the site's own
    pages or the sectors. A date that is always today is one search engines
    learn to ignore; none is better.
    """
    filed = filed or {}
    lines = [(site + p, None) for p in SITE_PAGES]
    lines += [(site + sector_path(s), None) for s in sorted(sectors(rows))]
    lines += [(site + path_for(s), _lastmod(filed.get(s), today)) for s in sorted(index(rows))]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n'
            % "".join("<url><loc>%s</loc>%s</url>\n" % (
                esc(u), "<lastmod>%s</lastmod>" % day if day else "") for u, day in lines))


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------

TEMPLATE_TTL = 600        # seconds a good copy is used before it is read again
TEMPLATE_RETRY = 60       # seconds before a failed read is tried again
_tpl = {"at": 0.0, "html": None, "source": None, "failed_at": 0.0}
_tpl_lock = threading.Lock()


def _usable(text):
    """
    stock.html with both markers in it. Not an error page that answered 200,
    and not the stock.html of a deploy before this one: that copy loads a
    stock.js that cannot read the company from /stock-SYMBOL, and would draw
    an empty page around the figures. Until the site has the new one, the
    plain page is sent instead.
    """
    return bool(text) and HEAD_MARK in text and GLANCE_MARK in text and 'id="nm"' in text


def _local_template():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.environ.get("COMPANY_TEMPLATE_PATH"),
              os.path.join(here, os.pardir, "frontend", "stock.html")):
        try:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    return fh.read(), "file"
        except OSError:
            continue
    return None, None


def _site_template(site):
    try:
        import requests
        r = requests.get(site + "/stock.html", timeout=6,
                         headers={"User-Agent": "altaha-company-pages"})
        if getattr(r, "status_code", 0) == 200:
            return r.text, "site"
    except Exception:
        pass
    return None, None


def template(site, now=None):
    """
    stock.html as it is deployed, or None.

    From the repository when the file is on this machine; otherwise from the
    site itself, which is where the page's scripts and styles come from too,
    so the two cannot disagree. A good copy is kept for ten minutes and goes
    on being used if a later read fails. With no copy at all, a failed read is
    not repeated for a minute: a crawler must not turn one slow fetch into
    hundreds.
    """
    now = time.time() if now is None else now
    with _tpl_lock:
        if _tpl["html"] and now - _tpl["at"] < TEMPLATE_TTL:
            return _tpl["html"]
        if not _tpl["html"] and now - _tpl["failed_at"] < TEMPLATE_RETRY:
            return None
        text, source = _local_template()
        if not _usable(text):
            text, source = _site_template(site)
        if _usable(text):
            _tpl.update(at=now, html=text, source=source)
        else:
            _tpl["failed_at"] = now
            if _tpl["html"]:
                _tpl["at"] = now - TEMPLATE_TTL + TEMPLATE_RETRY
        return _tpl["html"]


def template_status():
    with _tpl_lock:
        return {"loaded": bool(_tpl["html"]), "source": _tpl["source"],
                "age_seconds": round(time.time() - _tpl["at"]) if _tpl["html"] else None}
