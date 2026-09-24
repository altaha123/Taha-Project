"""
lens_data_crawl.py — the per-company inputs the fundamentals tables lack

Three lenses need facts that are not in a results filing:

  industry        Gorilla ranks a company within its industry and compares its
                  margin with the industry median. NSE classifies every listed
                  company on four levels (macro-sector, sector, industry, basic
                  industry); the quote API carries it per symbol.
  size            Tenbagger asks for small or mid caps, which is a rank by
                  market value: issued shares (same quote API) times price.
  ownership       Akre, Owner-Operator and Tenbagger read promoter, FII and DII
                  holdings and the promoter pledge, from the quarterly
                  shareholding filing (shareholding_filings.py, which already
                  caches every parse to disk).

This crawl reads both for a slice of companies per call, like the
fundamentals and holdings crawls, and records what it tried in lens_coverage
so each slice continues the last. It is driven by the Run button (lens_runner.py).
"""

import time

import lens_store

try:
    import nse_http
except Exception:        # pragma: no cover
    nse_http = None
try:
    import shareholding_filings as shp
except Exception:        # pragma: no cover
    shp = None

QUOTE_URL = "https://www.nseindia.com/api/quote-equity"
QUARTERS = 6              # the latest six quarter-end filings: enough for 4-quarter changes
DEFAULT_LIMIT = 25
PAUSE = 1.0
GIVE_UP_AFTER = 6


def _f(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def parse_quote(sym, body):
    """The fields lens_company keeps, from one quote-equity response."""
    if not isinstance(body, dict):
        return None
    info = body.get("info") or {}
    ind = body.get("industryInfo") or {}
    sec = body.get("securityInfo") or {}
    price = body.get("priceInfo") or {}
    meta = body.get("metadata") or {}
    row = {
        "symbol": sym,
        "company": info.get("companyName"),
        "macro": ind.get("macro"),
        "sector": ind.get("sector"),
        "industry": ind.get("industry") or meta.get("industry") or info.get("industry"),
        "basic_industry": ind.get("basicIndustry"),
        "issued_shares": _f(sec.get("issuedSize")),
        "face_value": _f(sec.get("faceValue")),
        "last_price": _f(price.get("lastPrice")),
        "price_date": meta.get("lastUpdateTime") or body.get("lastUpdateTime"),
    }
    if not any(row[k] for k in ("industry", "issued_shares", "last_price")):
        return None
    return row


def shareholding_rows(sym, parsed_filings):
    """lens_shareholding rows from parsed filings (newest first)."""
    out = []
    for p in parsed_filings:
        cats = p.get("categories") or {}
        if not cats:
            continue

        def pct(key):
            return (cats.get(key) or {}).get("pct")

        promoter = pct("promoter")
        # A company with no promoter omits the line rather than filing a zero.
        # The filing's own total says whether that is what happened.
        if promoter is None and pct("total") is not None and pct("public_total") is not None \
                and abs(pct("public_total") - pct("total")) < 0.2:
            promoter = 0.0
        pledge = p.get("pledge") or {}
        out.append({
            "symbol": sym,
            "period_end": p.get("period") or p.get("period_end"),
            "promoter_pct": promoter,
            "fii_pct": pct("fii"),
            "dii_pct": pct("dii"),
            "public_pct": pct("public_total"),
            "pledged": pledge.get("pledged"),
            "pledge_pct": pledge.get("pledge_pct"),
            "dii_derived": bool((cats.get("dii") or {}).get("derived")),
            "source_url": p.get("source"),
        })
    return out


def crawl_symbol(sym):
    out = {"symbol": sym, "ok": False, "profile": False, "quarters": 0, "status": "error",
           "note": ""}
    try:
        body = nse_http.get_json(QUOTE_URL, params={"symbol": sym},
                                 referer="https://www.nseindia.com/get-quotes/equity?symbol=" + sym)
        prof = parse_quote(sym, body)
        if prof:
            lens_store.upsert_company(prof)
            out["profile"] = True
    except Exception as e:
        out["note"] = "quote: %s" % type(e).__name__

    try:
        rows = [r for r in shp.index(sym) if r.get("quarter_end")][:QUARTERS]
        parsed = []
        for i, r in enumerate(rows):
            # The pledge is read from the latest filing; an older parse cached
            # before the pledge was parsed is read again only for that one.
            p = shp.filing(r["xbrl"], period=r["period"], filed=r["filed"],
                           revised=r["revised"], need=("pledge",) if i == 0 else ())
            if p:
                parsed.append(p)
        recs = shareholding_rows(sym, parsed)
        out["quarters"] = lens_store.upsert_shareholding(recs)
    except Exception as e:
        out["note"] = (out["note"] + " shareholding: %s" % type(e).__name__).strip()

    out["ok"] = out["profile"] or out["quarters"] > 0
    out["status"] = "ok" if (out["profile"] and out["quarters"]) else \
        ("partial" if out["ok"] else "unreadable")
    lens_store.mark_coverage(sym, out["status"], out["note"], ok=out["ok"])
    return out


def universe():
    try:
        import fundamentals_crawl
        return fundamentals_crawl.universe()
    except Exception:
        return []


def run(limit=DEFAULT_LIMIT, symbols=None, pause=PAUSE):
    started = time.time()
    out = {"attempted": 0, "ok": 0, "failed": 0, "stopped_early": None, "results": []}
    if nse_http is None or shp is None or not nse_http.available():
        out["stopped_early"] = ("the exchange reader is not installed on this instance "
                                "(curl_cffi is required to reach NSE)")
        return out
    queue = [s.strip().upper() for s in symbols if s] if symbols else \
        lens_store.due_symbols(universe(), limit=limit)
    if not queue:
        out["stopped_early"] = "nothing due"
        return out
    misses = 0
    for sym in queue[: max(1, int(limit))]:
        r = crawl_symbol(sym)
        out["attempted"] += 1
        out["results"].append(r)
        if r["ok"]:
            out["ok"] += 1
            misses = 0
        else:
            out["failed"] += 1
            misses += 1
        if misses >= GIVE_UP_AFTER:
            out["stopped_early"] = ("%d companies in a row could not be read — stopping rather "
                                    "than continuing to hammer a rate limiter" % misses)
            break
        if pause:
            time.sleep(pause)
    out["seconds"] = round(time.time() - started, 1)
    out["store"] = lens_store.stats()
    return out
