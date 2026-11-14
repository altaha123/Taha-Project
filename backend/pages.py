"""
Altaha Screener — pages a search engine can read

The site is one JavaScript application. A person sees a stock page; a crawler
that does not run the scripts sees an empty shell, and one that does has to
wait for seventy files and a dozen requests before there is anything to read.
So the site had no pages that could be found by somebody typing a company's
name into a search box, which is how nearly everybody starts.

These are those pages, written on the server as plain HTML with no script:

    /stock/RELIANCE   one company: its score, its last quarters, its peers
    /stocks           every company, grouped by industry
    /today            what the market did today, in sentences
    /sitemap.xml      the list of all of them, for crawlers

Each ends in one button that opens the live application on the same thing.

THE RULES THESE PAGES FOLLOW

  Nothing is fetched to build one. Every figure is read from what the nightly
  scan and the results crawl have already stored on this server's own disk. A
  crawler asking for two thousand pages in a minute costs two thousand small
  database reads and not one call to the exchange. Rendered pages are kept
  (swr.py) and marked cacheable, so the second request for a page usually
  never reaches this server at all.

  Nothing is said that the application does not show. The score is the stored
  score with its date. A company with no stored score has a page that says so.

  Nothing is advice. A page states the score, the label the engine gave it,
  and the reported results. It carries no entry, stop, target, "buy" or
  "sell", for the reason og.py gives: publishing analysis and publishing
  advice are different things in India, and only one needs a licence.
"""

import csv
import datetime as dt
import html
import json
import os
import threading

try:
    import pit_store
except Exception:                                     # pragma: no cover
    pit_store = None
try:
    import fundamentals_store
except Exception:                                     # pragma: no cover
    fundamentals_store = None

import daily

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_URL", "https://altahascreener.in").rstrip("/")
INDUSTRY_FILE = os.path.join(HERE, "nse_industries.csv")

CACHE_HEADERS = {"Cache-Control": "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"}
LABELS = {"STRONG PROFILE": "strong", "STRONG": "strong", "CONSTRUCTIVE": "constructive",
          "MIXED": "mixed", "WEAK PROFILE": "weak", "WEAK": "weak"}


def esc(text):
    return html.escape("" if text is None else str(text), quote=True)


def clean_symbol(raw):
    """An NSE symbol or nothing. Letters, digits, & and - only, 1 to 20 long."""
    s = (raw or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not 0 < len(s) <= 20 or any(not (c.isalnum() or c in "&-") for c in s):
        return None
    return s


def _date(iso):
    """'2026-11-13' -> '13 Nov 2026'. Anything else is returned as it came."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.day} {d.strftime('%b %Y')}"
    except (TypeError, ValueError):
        return str(iso or "")


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _cr(v):
    n = _num(v)
    return "—" if n is None else "₹" + daily.indian(n) + " cr"


def _pct(v, places=1):
    n = _num(v)
    if n is None:
        return "—"
    n = round(n, places)
    return f"{'+' if n > 0 else '−' if n < 0 else ''}{abs(n):.{places}f}%"


# ---------------------------------------------------------------------------
# What is stored
# ---------------------------------------------------------------------------

_ind_lock = threading.Lock()
_ind = {"rows": None}


def industries():
    """{symbol: {"name", "industry", "isin"}} from the carried NSE list."""
    with _ind_lock:
        if _ind["rows"] is None:
            out = {}
            try:
                with open(INDUSTRY_FILE, newline="", encoding="utf-8-sig") as f:
                    for r in csv.DictReader(f):
                        sym = clean_symbol(r.get("Symbol"))
                        if sym:
                            out[sym] = {"name": (r.get("Company Name") or sym).strip(),
                                        "industry": (r.get("Industry") or "").strip(),
                                        "isin": (r.get("ISIN Code") or "").strip()}
            except OSError:
                pass
            _ind["rows"] = out
        return _ind["rows"]


def scored_symbols():
    """Every symbol that has at least one stored score."""
    if pit_store is None:
        return []
    try:
        rows = pit_store._connect().execute(
            "SELECT DISTINCT symbol FROM factor_snapshots WHERE factor = 'composite'").fetchall()
        return sorted({clean_symbol(r[0]) for r in rows} - {None})
    except Exception:
        return []


def latest_scores():
    """{symbol: {"score", "label", "price", "date"}} from the newest scan."""
    if pit_store is None:
        return {}
    try:
        conn = pit_store._connect()
        last = conn.execute("SELECT MAX(as_of_date) FROM factor_snapshots"
                            " WHERE factor = 'composite'").fetchone()[0]
        if not last:
            return {}
        out = {}
        for r in conn.execute(
                "SELECT symbol, factor, value, text_value FROM factor_snapshots"
                " WHERE as_of_date = ? AND factor IN ('composite', 'label', 'price')", (last,)):
            slot = out.setdefault(r[0], {"date": last})
            if r[1] == "composite":
                slot["score"] = r[2]
            elif r[1] == "price":
                slot["price"] = r[2]
            else:
                slot["label"] = r[3]
        return {s: v for s, v in out.items() if v.get("score") is not None}
    except Exception:
        return {}


def _history(symbol):
    if pit_store is None:
        return []
    try:
        rows = pit_store.score_history(symbol, limit=120).get("rows") or []
        return [r for r in rows if _num(r.get("composite")) is not None]
    except Exception:
        return []


def _quarters(symbol, limit=5):
    if fundamentals_store is None:
        return []
    try:
        recs = fundamentals_store.rows("income", symbol=symbol, freq="quarterly")
        basis = fundamentals_store._latest_basis(recs)
        return [r for r in recs if r.get("basis") == basis][:limit] if basis else []
    except Exception:
        return []


def stock_info(symbol):
    """Everything stored about one company, or None if nothing is."""
    sym = clean_symbol(symbol)
    if not sym:
        return None
    base = industries().get(sym)
    hist = _history(sym)
    quarters = _quarters(sym)
    if not base and not hist and not quarters:
        return None
    name = (base or {}).get("name") or next(
        (q.get("company") for q in quarters if q.get("company")), None) or sym
    industry = (base or {}).get("industry") or next(
        (r.get("sector") for r in reversed(hist) if r.get("sector")), "") or ""
    peers = []
    if industry and base:
        peers = sorted(s for s, v in industries().items()
                       if v["industry"] == industry and s != sym)
    return {"symbol": sym, "name": name, "industry": industry,
            "isin": (base or {}).get("isin") or "", "history": hist,
            "quarters": quarters, "peers": peers}


# ---------------------------------------------------------------------------
# The page frame
# ---------------------------------------------------------------------------

CSS = """
:root{--paper:#FBFAF7;--card:#FFFDF8;--ink:#16130E;--ink2:#4A443A;--mute:#8B8477;--rule:#E2DACA;
--gold:#A8801C;--gold-dp:#8A6D1E;--up:#1F7A55;--dn:#B03A2B}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 Inter,system-ui,-apple-system,Segoe UI,sans-serif}
a{color:var(--gold-dp)}a:hover{color:var(--ink)}
.top{border-bottom:1px solid var(--rule);background:var(--card)}
.top div,.wrap,.foot div{max-width:920px;margin:0 auto;padding:0 20px}
.top div{display:flex;align-items:center;gap:22px;min-height:60px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:9px;font-weight:600;color:var(--ink);text-decoration:none;margin-right:auto}
.brand img{width:28px;height:28px}.brand i{font-family:'Instrument Serif',Georgia,serif;color:var(--gold);font-size:19px}
.top a.n{color:var(--ink2);text-decoration:none;font-weight:500;font-size:15px}
.wrap{padding-top:26px;padding-bottom:44px}
.crumb{font-size:13px;color:var(--mute);margin:0 0 14px}.crumb a{color:var(--mute)}
h1{font-family:'Instrument Serif',Georgia,serif;font-weight:400;font-size:clamp(32px,6vw,48px);line-height:1.05;margin:0}
h2{font-family:'Instrument Serif',Georgia,serif;font-weight:400;font-size:28px;line-height:1.15;margin:38px 0 12px}
.sub{color:var(--ink2);margin:8px 0 0}
.lead{font-size:17px;line-height:1.65;margin:18px 0 0;max-width:68ch}
.score{display:flex;flex-wrap:wrap;gap:14px;margin:24px 0 0}
.tile{flex:1 1 180px;padding:18px 20px;border:1px solid var(--rule);border-radius:16px;background:var(--card)}
.tile small{display:block;font:600 11px/1 'IBM Plex Mono',monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--mute)}
.tile b{display:block;margin-top:8px;font:400 40px/1 'Instrument Serif',Georgia,serif}
.tile b span{font-size:18px;color:var(--mute)}.tile em{display:block;margin-top:6px;font-style:normal;font-size:13.5px;color:var(--ink2)}
.spark{display:block;margin-top:10px;width:100%;height:36px}
.go{display:inline-flex;align-items:center;gap:8px;min-height:50px;margin:26px 0 0;padding:0 26px;border-radius:999px;background:var(--ink);
color:#fff;font-weight:600;text-decoration:none}.go:hover{background:var(--gold-dp);color:#fff}
.tw{overflow-x:auto;border:1px solid var(--rule);border-radius:14px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:11px 14px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{font:600 11px/1.4 'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
tr:last-child td{border-bottom:0}.up{color:var(--up)}.dn{color:var(--dn)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.chips a{display:inline-flex;align-items:center;min-height:38px;padding:0 14px;border:1px solid var(--rule);border-radius:999px;background:var(--card);
color:var(--ink);text-decoration:none;font-size:14.5px}.chips a:hover{border-color:var(--gold)}.chips a b{margin-left:8px;color:var(--mute);font-weight:500}
.lines{list-style:none;margin:18px 0 0;padding:0;border:1px solid var(--rule);border-left:4px solid var(--gold);border-radius:16px;background:var(--card)}
.lines li{padding:14px 20px;font-size:17px}.lines li+li{border-top:1px solid var(--rule)}
.lines b{display:block;font:600 11px/1.6 'IBM Plex Mono',monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
dl{margin:0}dt{font-weight:600;margin-top:16px}dd{margin:4px 0 0;color:var(--ink2);max-width:70ch}
.note{margin-top:34px;font-size:13px;color:var(--mute);max-width:72ch}
.foot{border-top:1px solid var(--rule);background:var(--card);font-size:13.5px;color:var(--mute)}
.foot div{padding-top:20px;padding-bottom:26px;display:flex;flex-wrap:wrap;gap:8px 20px}.foot a{color:var(--ink2)}
.cols{columns:3 220px;column-gap:26px;margin:0;padding:0;list-style:none}.cols li{break-inside:avoid;padding:3px 0}
.cols a{text-decoration:none}.cols a:hover{text-decoration:underline}.cols span{color:var(--mute);font-size:13px}
@media(max-width:560px){.top a.n.x{display:none}.lead{font-size:16px}h2{font-size:25px}.tile b{font-size:36px}}
"""


def frame(title, description, path, body, jsonld=None, image=None, status_noindex=False):
    """One whole document. `path` is the page's own address on the site."""
    url = SITE + path
    image = image or f"{SITE}/og/record.png"
    blocks = "".join(
        '<script type="application/ld+json">'
        + json.dumps(j, ensure_ascii=False).replace("<", "\\u003c") + "</script>\n"
        for j in (jsonld or []))
    robots = '<meta name="robots" content="noindex">\n' if status_noindex else ""
    return f"""<!doctype html>
<html lang="en-IN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{robots}<link rel="canonical" href="{esc(url)}">
<link rel="icon" href="{SITE}/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="{SITE}/apple-touch-icon.png">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Altaha Screener">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{esc(image)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=IBM+Plex+Mono:wght@600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
{blocks}</head>
<body>
<header class="top"><div>
<a class="brand" href="{SITE}/"><img src="{SITE}/icon-512.png" alt="" width="28" height="28">Altaha <i>Screener</i></a>
<a class="n" href="{SITE}/today">Today</a>
<a class="n x" href="{SITE}/?go=ideas">Ideas</a>
<a class="n" href="{SITE}/stocks">All stocks</a>
<a class="n x" href="{SITE}/brief.html">Morning brief</a>
</div></header>
<main class="wrap">
{body}
<p class="note">Altaha Screener publishes computed scores and reported figures for information only. Nothing on this page is investment advice or a recommendation to buy or sell any security. Prices and filings are from NSE and BSE and may be delayed.</p>
</main>
<footer class="foot"><div>
<span>© {dt.date.today().year} Altaha Screener</span>
<a href="{SITE}/">Home</a><a href="{SITE}/today">Today’s market</a><a href="{SITE}/stocks">All stocks</a>
<a href="{SITE}/brief.html">Morning brief</a>
</div></footer>
</body></html>"""


def _spark(values):
    """A small line of the score over time. Decorative: the numbers are in the text."""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    pts = " ".join(f"{i * 200 / (len(vals) - 1):.1f},{32 - (v - lo) * 28 / span:.1f}"
                   for i, v in enumerate(vals))
    return (f'<svg class="spark" viewBox="0 0 200 36" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="#A8801C" stroke-width="1.6" '
            f'vector-effect="non-scaling-stroke"/></svg>')


# ---------------------------------------------------------------------------
# /stock/SYMBOL
# ---------------------------------------------------------------------------

def _results_sentence(name, q):
    rev, pat = _num(q.get("revenue_cr")), _num(q.get("pat_cr"))
    if rev is None and pat is None:
        return ""
    when = f"In the quarter ended {_date(q.get('period_end'))}"
    bits = []
    if rev is not None:
        s = f"revenue of {_cr(rev)}"
        y = _num(q.get("revenue_yoy_pct"))
        if y is not None:
            s += f", {'up' if y >= 0 else 'down'} {abs(y):.1f}% on a year earlier"
        bits.append(s)
    if pat is not None:
        s = f"net profit of {_cr(pat)}" if pat >= 0 else f"a net loss of {_cr(abs(pat))}"
        y = _num(q.get("pat_yoy_pct"))
        if y is not None and pat >= 0:
            s += f", {'up' if y >= 0 else 'down'} {abs(y):.1f}%"
        bits.append(s)
    return f"{when} {name} reported " + (", and ".join(bits) if len(bits) > 1 else bits[0]) + "."


def render_stock(info, scores=None):
    sym, name, industry = info["symbol"], info["name"], info["industry"]
    hist, quarters = info["history"], info["quarters"]
    scores = scores or {}
    app_url = f"{SITE}/stock.html?ticker={sym}"
    last = hist[-1] if hist else None
    faq, lead, tiles = [], [], ""

    lead.append(f"{esc(name)} (NSE: {esc(sym)})"
                + (f" is a listed company in {esc(industry)}." if industry else " is listed on the NSE."))
    if last:
        score = round(float(last["composite"]))
        label = LABELS.get(str(last.get("label") or "").upper(), "")
        s = f"On {_date(last['date'])} its Altaha score was {score} out of 100"
        s += f", a {label} profile" if label else ""
        first = hist[0]
        if len(hist) > 1 and first["date"] != last["date"]:
            diff = round(float(last["composite"])) - round(float(first["composite"]))
            if diff:
                s += (f", {'up' if diff > 0 else 'down'} {abs(diff)} "
                      f"point{'s' if abs(diff) != 1 else ''} since {_date(first['date'])}")
            else:
                s += f", unchanged since {_date(first['date'])}"
        lead.append(s + ".")
        faq.append((f"What is the Altaha score of {name}?",
                    f"{name} scored {score} out of 100 on {_date(last['date'])}"
                    + (f", which the engine labels a {label} profile" if label else "")
                    + ". The score combines technical and fundamental checks, and every "
                      "calculation behind it is shown on the full analysis page."))
        tiles += (f'<div class="tile"><small>Altaha score</small><b>{score}<span> / 100</span></b>'
                  f'<em>{esc(label.capitalize() + " profile · " if label else "")}{_date(last["date"])}</em>'
                  + _spark([_num(r.get("composite")) for r in hist]) + "</div>")
        f = _num(last.get("f_score"))
        if f is not None:
            tiles += (f'<div class="tile"><small>Piotroski F-score</small><b>{int(round(f))}<span> / 9</span></b>'
                      f'<em>Nine checks of financial health</em></div>')
            lead.append(f"Its Piotroski F-score, a nine-point check of financial health, is {int(round(f))}.")
        price = _num(last.get("price"))
        if price is not None:
            tiles += (f'<div class="tile"><small>Share price</small><b>₹{daily.indian(price, 2 if price < 1000 else 0)}</b>'
                      f'<em>At the scan on {_date(last["date"])}</em></div>')
    else:
        lead.append("It has not been through the nightly scan yet, so there is no stored score; "
                    "the full analysis page scores it live.")

    table = ""
    if quarters:
        sentence = _results_sentence(name, quarters[0])
        if sentence:
            lead.append(esc(sentence))
            faq.append((f"How were {name}'s latest quarterly results?", sentence))
        rows = ""
        for q in quarters:
            def cell(v):
                n = _num(v)
                return f'<td class="{"up" if (n or 0) > 0 else "dn" if (n or 0) < 0 else ""}">{_pct(v)}</td>'
            margin = _num(q.get("net_margin_pct"))
            rows += (f"<tr><td>{esc(q.get('label') or _date(q.get('period_end')))}</td>"
                     f"<td>{_cr(q.get('revenue_cr'))}</td>{cell(q.get('revenue_yoy_pct'))}"
                     f"<td>{_cr(q.get('pat_cr'))}</td>{cell(q.get('pat_yoy_pct'))}"
                     f"<td>{'—' if margin is None else f'{margin:.1f}%'}</td></tr>")
        basis = quarters[0].get("basis") or ""
        table = (f"<h2>Quarterly results</h2><div class=\"tw\"><table><thead><tr><th>Quarter</th>"
                 f"<th>Revenue</th><th>YoY</th><th>Net profit</th><th>YoY</th><th>Net margin</th>"
                 f"</tr></thead><tbody>{rows}</tbody></table></div>"
                 f"<p class=\"sub\" style=\"font-size:13.5px\">As filed with the exchange"
                 f"{', ' + esc(basis) if basis else ''}. Figures in ₹ crore.</p>")
    if industry:
        faq.append((f"Which sector is {name} in?",
                    f"{name} is classified under {industry} in the NSE industry list."))

    peers_html = ""
    if info["peers"]:
        ranked = sorted(info["peers"], key=lambda s: -(_num((scores.get(s) or {}).get("score")) or -1))[:14]
        chips = "".join(
            f'<li><a href="{SITE}/stock/{esc(p)}">{esc(industries()[p]["name"])}'
            + (f'<b>{round(float(scores[p]["score"]))}</b>' if p in scores else "") + "</a></li>"
            for p in ranked)
        peers_html = (f"<h2>Other {esc(industry)} companies</h2><ul class=\"chips\">{chips}</ul>")

    faq_html = ""
    if faq:
        faq_html = "<h2>Questions people ask</h2><dl>" + "".join(
            f"<dt>{esc(q)}</dt><dd>{esc(a)}</dd>" for q, a in faq) + "</dl>"

    body = (f'<p class="crumb"><a href="{SITE}/">Home</a> › <a href="{SITE}/stocks">Stocks</a>'
            + (f" › {esc(industry)}" if industry else "") + "</p>"
            f"<h1>{esc(name)}</h1>"
            f'<p class="sub">NSE: {esc(sym)}'
            + (f" · {esc(industry)}" if industry else "")
            + (f" · ISIN {esc(info['isin'])}" if info.get("isin") else "") + "</p>"
            f'<p class="lead">{" ".join(lead)}</p>'
            + (f'<div class="score">{tiles}</div>' if tiles else "")
            + f'<a class="go" href="{esc(app_url)}">Open the full live analysis of {esc(sym)} →</a>'
            + table + peers_html + faq_html)

    if last:
        title = f"{name} ({sym}) share: score {round(float(last['composite']))}/100, results and peers"
    else:
        title = f"{name} ({sym}) share: score, results and peers"
    desc = html.unescape(" ".join(lead))[:300]
    jsonld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
        {"@type": "ListItem", "position": 2, "name": "Stocks", "item": SITE + "/stocks"},
        {"@type": "ListItem", "position": 3, "name": name, "item": f"{SITE}/stock/{sym}"}]}]
    if faq:
        jsonld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]})
    return frame(title + " | Altaha Screener", desc, f"/stock/{sym}", body, jsonld,
                 image=f"{SITE}/og/stock.png?ticker={sym}")


def stock_page(symbol):
    """HTML for one company, or None when nothing is stored about it."""
    info = stock_info(symbol)
    return None if info is None else render_stock(info, latest_scores())


def not_found(what="That page"):
    body = (f"<h1>{esc(what)} is not here.</h1>"
            f'<p class="lead">The address may be mistyped, or the company may not be listed on the NSE.</p>'
            f'<a class="go" href="{SITE}/stocks">See every stock →</a>')
    return frame("Page not found | Altaha Screener", "This page does not exist.", "/stocks",
                 body, status_noindex=True)


# ---------------------------------------------------------------------------
# /stocks
# ---------------------------------------------------------------------------

def stocks_page():
    ind, scores = industries(), latest_scores()
    groups = {}
    for sym, v in ind.items():
        groups.setdefault(v["industry"] or "Other", []).append(sym)
    listed = set(ind)
    extra = [s for s in scored_symbols() if s not in listed]
    sections = ""
    for industry in sorted(groups):
        items = "".join(
            f'<li><a href="{SITE}/stock/{esc(s)}">{esc(ind[s]["name"])}</a>'
            + (f' <span>{round(float(scores[s]["score"]))}</span>' if s in scores else "") + "</li>"
            for s in sorted(groups[industry], key=lambda s: ind[s]["name"].lower()))
        sections += f"<h2>{esc(industry)}</h2><ul class=\"cols\">{items}</ul>"
    if extra:
        items = "".join(
            f'<li><a href="{SITE}/stock/{esc(s)}">{esc(s)}</a>'
            + (f' <span>{round(float(scores[s]["score"]))}</span>' if s in scores else "") + "</li>"
            for s in extra)
        sections += f"<h2>More scored companies</h2><ul class=\"cols\">{items}</ul>"
    total = len(ind) + len(extra)
    body = (f'<p class="crumb"><a href="{SITE}/">Home</a> › Stocks</p>'
            f"<h1>Every stock, with its score</h1>"
            f'<p class="lead">{daily.indian(total)} NSE companies, grouped by industry. The number beside a '
            f"name is its latest Altaha score out of 100. Open any company for its score, its last "
            f"quarters and its peers.</p>" + sections)
    return frame("All NSE stocks with scores, by industry | Altaha Screener",
                 f"{daily.indian(total)} NSE-listed companies grouped by industry, each with its latest "
                 "Altaha score out of 100, quarterly results and peers.",
                 "/stocks", body)


# ---------------------------------------------------------------------------
# /today
# ---------------------------------------------------------------------------

def today_page(story, sectors=None):
    """`story` is daily.story(); `sectors` the sector map it was written from."""
    lines = story.get("lines") or []
    day = story.get("day") or ""
    known = industries()
    items = "".join(f"<li><b>{esc(l.get('label'))}</b>{esc(l['text'])}</li>" for l in lines)
    block = (f'<ul class="lines">{items}</ul>' if items else
             '<p class="lead">Today’s figures are not in yet. The live page has the market as it moves.</p>')

    sector_html = movers_html = ""
    rows = [r for r in (sectors or {}).get("rows") or [] if _num(r.get("change_pct")) is not None]
    if rows:
        rows = sorted(rows, key=lambda r: -float(r["change_pct"]))
        trs = "".join(
            f"<tr><td>{esc(r['sector'])}</td>"
            f"<td class=\"{'up' if float(r['change_pct']) > 0 else 'dn' if float(r['change_pct']) < 0 else ''}\">"
            f"{_pct(r['change_pct'], 2)}</td>"
            f"<td>{esc(r.get('up', '—'))} of {esc(r.get('total', '—'))}</td></tr>" for r in rows)
        sector_html = ("<h2>Sectors today</h2><div class=\"tw\"><table><thead><tr><th>Sector</th>"
                       "<th>Move</th><th>Stocks up</th></tr></thead><tbody>" + trs + "</tbody></table></div>")
        stocks = {}
        for r in rows:
            for s in r.get("stocks") or []:
                if clean_symbol(s.get("symbol")) and _num(s.get("change_pct")) is not None:
                    stocks[clean_symbol(s["symbol"])] = float(s["change_pct"])
        if len(stocks) >= 10:
            ranked = sorted(stocks.items(), key=lambda kv: -kv[1])

            def chips(pairs):
                return "".join(
                    f'<li><a href="{SITE}/stock/{esc(s)}">{esc((known.get(s) or {}).get("name") or s)}'
                    f"<b class=\"{'up' if v > 0 else 'dn'}\">{_pct(v, 2)}</b></a></li>" for s, v in pairs)
            gain = [p for p in ranked[:6] if p[1] > 0]
            lose = [p for p in ranked[::-1][:6] if p[1] < 0]
            if gain:
                movers_html += f"<h2>Biggest gainers</h2><ul class=\"chips\">{chips(gain)}</ul>"
            if lose:
                movers_html += f"<h2>Biggest fallers</h2><ul class=\"chips\">{chips(lose)}</ul>"
            if movers_html:
                movers_html += '<p class="sub" style="font-size:13.5px">Among the large companies tracked in each sector.</p>'

    headline = story.get("headline") or "Today in the market"
    body = (f'<p class="crumb"><a href="{SITE}/">Home</a> › Today</p>'
            f"<h1>{esc(headline)}</h1>"
            f'<p class="sub">Indian stock market, {esc(story.get("weekday") or "")} {esc(day)}</p>'
            + block
            + f'<a class="go" href="{SITE}/">Open the live market page →</a>'
            + sector_html + movers_html)
    desc = " ".join(l["text"] for l in lines)[:300] or \
        "What the Indian stock market did today: Nifty, Sensex, sectors, movers and fund flows."
    return frame(f"Stock market today, {day}: Nifty, Sensex, sectors, FII and DII | Altaha Screener",
                 desc, "/today", body)


# ---------------------------------------------------------------------------
# /sitemap.xml
# ---------------------------------------------------------------------------

def sitemap(today=None):
    today = today or dt.date.today().isoformat()
    scores = latest_scores()
    symbols = sorted(set(industries()) | set(scored_symbols()))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    def url(loc, lastmod=None, freq=None):
        out.append("<url><loc>" + esc(loc) + "</loc>"
                   + (f"<lastmod>{esc(lastmod)}</lastmod>" if lastmod else "")
                   + (f"<changefreq>{freq}</changefreq>" if freq else "") + "</url>")
    url(SITE + "/", today, "daily")
    url(SITE + "/today", today, "daily")
    url(SITE + "/stocks", today, "daily")
    url(SITE + "/brief.html", today, "daily")
    for s in symbols:
        url(f"{SITE}/stock/{s.replace('&', '%26')}", (scores.get(s) or {}).get("date"), "daily")
    out.append("</urlset>")
    return "\n".join(out)
