"""
listings.py — which companies the site covers, on which board, and how to
reach each one

Until Nov 2026 the universe was NSE's main-board equity list and nothing else:
`EQUITY_L.csv`, series EQ, about 2,100 companies. Two groups were missing.

NSE SME (Emerge)
    About 580 companies on NSE's small and medium enterprise platform. Same
    exchange, same symbols, same price feeds, but a separate list
    (`SME_EQUITY_L.csv`, series SM and ST) that the main list never contains.
    They report results every six months rather than every quarter, and trade
    in lots that are often worth more than a lakh of rupees.

BSE-only companies
    About 2,450 companies listed on BSE and not on NSE at all: most of BSE's
    X and XT groups, its SME platform (groups M and MT) and a tail of B and Z.
    Every company on both exchanges is already covered by its NSE listing and
    is NOT added a second time.

HOW A BSE-ONLY COMPANY IS NAMED
By its six-digit BSE scrip code: 534708, not SHANTIGURU. Three reasons:
  * No NSE symbol is all digits, so a code can never collide with one. BSE's
    short symbols can: seven BSE-only companies use a symbol that NSE gives to
    a different company (ZEAL, SEL, MAL, FOCUS, KALYANI, GSTL, RAJPUTANA on
    the day this was written). Every page, store and cache in this codebase
    is keyed by the bare symbol, so a shared name would merge two companies.
  * Dhan's BSE_EQ security id IS the scrip code.
The short symbol travels with the row as `t`, so the search box finds a
BSE-only company by its symbol and its name as well as its code.

TWO TICKERS FOR ONE COMPANY
The site's own ticker for a BSE-only company is `534708.BO` (ticker_key):
that is what a page, a cache or a stored row is keyed by, and stripping the
suffix gives back the code. Yahoo does not know that name. It names a BSE
listing by BSE's short symbol, `SHANTIGURU.BO` (yahoo_ticker), measured on
28 Nov 2026: ANDHRAPET.BO, HOCL.BO and SHANTIGURU.BO answered with a
month of prices, 500012.BO, 500449.BO and 534708.BO with nothing. So every
Yahoo call goes through yahoo_ticker and everything else through ticker_key,
and the two never mix: a stock page keyed by `ZEAL` would be NSE's Zeal
Global, not BSE's Zeal Aqua.

Yahoo carries the NSE SME board only in part (ZEAL.NS a year of prices,
AAKAAR.NS none). Dhan carries every board and is the price source the scan
uses whenever it is configured; Yahoo is the fallback.

WHERE THE BSE LIST COMES FROM
Dhan's detailed instrument master: the one file that carries, for both
exchanges, the ISIN (what tells a dual listing from a BSE-only one), BSE's
group, and the lot size. It is about 36 MB, so it is streamed line by line,
kept to the few thousand rows that matter, and saved to disk for a day: a
restart does not download it again.

BOARDS
Every row carries `x`, one of BOARDS. NSE and BSE main-board rows are scored
and ranked together. SME rows are scored on the same scale, so a 70 means the
same thing on either board, but they are kept out of the main pick lists and
ranked in their own list (scan.py), because a company that trades in lots of
1,200 shares, reports twice a year and can move 20% on a handful of trades is
a different proposition from a Nifty 500 name.

Nothing here raises. A source that cannot be read gives an empty list, and the
universe is whatever could be read.
"""

import csv
import datetime as dt
import io
import json
import os
import re
import threading
import time

try:
    import requests
except Exception:                                   # pragma: no cover
    requests = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", "").strip() or _HERE

NSE = "NSE"
NSE_SME = "NSE SME"
BSE = "BSE"
BSE_SME = "BSE SME"
BOARDS = (NSE, NSE_SME, BSE, BSE_SME)
SME_BOARDS = (NSE_SME, BSE_SME)

# Switches, both on by default. Off puts the universe back to NSE main board.
INCLUDE_SME = os.environ.get("UNIVERSE_SME", "1").strip() not in ("0", "false", "no", "")
INCLUDE_BSE = os.environ.get("UNIVERSE_BSE", "1").strip() not in ("0", "false", "no", "")

# NSE SME series. SM trades normally; ST is trade-for-trade (every trade
# settles by delivery). SZ is the SME version of BZ, companies that have not
# complied with the listing rules, and is left out exactly as BZ is on the
# main board.
SME_SERIES = ("SM", "ST")

# BSE groups that are BSE's SME platform. M trades normally, MT is
# trade-for-trade, MS is the SME version of the suspended-compliance groups.
BSE_SME_GROUPS = ("M", "MT", "MS")

# BSE groups kept out of the universe scan, though still searchable and
# scorable on request. Z and ZP are companies that have not complied with the
# listing rules or the depositories' requirements; BSE itself puts them in a
# group of their own to warn investors off.
BSE_SCAN_SKIP = tuple(g.strip().upper() for g in
                      os.environ.get("BSE_SCAN_SKIP_GROUPS", "Z,ZP").split(",") if g.strip())

NSE_SME_URLS = [
    "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
    "https://archives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
]
NSE_SME_REFERER = "https://www.nseindia.com/market-data/sme-market"

DHAN_DETAILED_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
DHAN_HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0 Safari/537.36"),
                "Accept": "text/csv,*/*"}
MASTER_FILE = os.path.join(_DATA_DIR, "listings_master.json")
SME_FILE = os.path.join(_DATA_DIR, "listings_nse_sme.json")
MASTER_TTL = 24 * 3600
SME_TTL = 3600

UA = DHAN_HEADERS["User-Agent"]

_BSE_CODE = re.compile(r"^\d{6}$")


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

def clean(symbol):
    """The bare key every store uses: upper case, no .NS / .BO."""
    s = str(symbol or "").strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        s = s[:-3]
    return s


def is_bse_code(symbol):
    """True for a six-digit BSE scrip code, the key of a BSE-only company."""
    return bool(_BSE_CODE.match(clean(symbol)))


def exchange(symbol):
    """'BSE' for a scrip code, otherwise 'NSE'. Needs no list."""
    return BSE if is_bse_code(symbol) else NSE


def ticker_key(symbol):
    """The site's own ticker: 534708 -> 534708.BO, TCS -> TCS.NS. A ticker
    that already carries a suffix is returned as it is."""
    raw = str(symbol or "").strip().upper()
    if raw.endswith(".NS") or raw.endswith(".BO"):
        return raw
    return f"{raw}.BO" if is_bse_code(raw) else f"{raw}.NS"


def yahoo_ticker(symbol):
    """
    The name Yahoo knows a listing by. TCS -> TCS.NS; a BSE-only company's
    code, bare or as CODE.BO, -> its BSE short symbol, 534708 ->
    SHANTIGURU.BO. A code whose short symbol is not loaded stays CODE.BO,
    which Yahoo will not find: no answer is better than a guessed name that
    belongs to another company. Any other suffixed ticker is left as it is.
    """
    raw = str(symbol or "").strip().upper()
    if is_bse_code(raw):
        t = ((info(raw) or {}).get("t") or "").strip().upper()
        if t and re.fullmatch(r"[A-Z0-9&\-]{1,30}", t):
            return f"{t}.BO"
        return f"{clean(raw)}.BO"
    return ticker_key(raw)


def dhan_segment(symbol):
    """Dhan's exchange segment for a bare key."""
    return "BSE_EQ" if is_bse_code(symbol) else "NSE_EQ"


# ---------------------------------------------------------------------------
# NSE SME
# ---------------------------------------------------------------------------

_sme_cache = {"at": 0.0, "rows": None}
_sme_lock = threading.Lock()


def _sme_text():
    """NSE's SME equity list as CSV text, or None. Same two attempts as the
    main list in scan._nse_list_text: the impersonating client first (NSE's
    WAF refuses a datacenter handshake), then plain requests."""
    try:
        import nse_http
    except Exception:
        nse_http = None
    if nse_http is not None and nse_http.available():
        for url in NSE_SME_URLS:
            r = nse_http.get(url, referer=NSE_SME_REFERER)
            if r is not None and "SYMBOL" in (r.text or "")[:200]:
                return r.text
    if requests is None:
        return None
    for url in NSE_SME_URLS:
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*",
                                           "Referer": "https://www.nseindia.com/"},
                             timeout=20)
            if r.status_code == 200 and "SYMBOL" in r.text[:200]:
                return r.text
        except Exception:
            continue
    return None


def parse_sme(text, lots=None):
    """Rows of the NSE SME list, series SM and ST, sorted by symbol."""
    lots = lots or {}
    out, seen = [], set()
    if not text:
        return out
    try:
        reader = csv.DictReader(io.StringIO(text))
        for raw in reader:
            row = {str(k or "").strip().upper().replace(" ", "_"): str(v or "").strip()
                   for k, v in raw.items()}
            sym = row.get("SYMBOL", "").upper()
            series = row.get("SERIES", "").upper()
            if not sym or sym in seen or series not in SME_SERIES:
                continue
            seen.add(sym)
            name = row.get("NAME_OF_COMPANY") or sym
            isin = row.get("ISIN_NUMBER") or row.get("ISIN") or ""
            rec = {"s": sym, "n": name, "x": NSE_SME, "series": series, "isin": isin}
            lot = lots.get(sym)
            if lot and lot > 1:
                rec["lot"] = lot
            out.append(rec)
    except Exception:
        return []
    out.sort(key=lambda r: r["s"])
    return out


def nse_sme(fetch=True):
    """The NSE SME companies, as listing rows. Cached for an hour; [] when the
    list cannot be read or SME coverage is switched off."""
    if not INCLUDE_SME:
        return []
    if _sme_cache["rows"] is not None and (time.time() - _sme_cache["at"]) < SME_TTL:
        return _sme_cache["rows"]
    if _sme_cache["rows"] is None:
        # What the last process read, so a restart knows which symbols are
        # SME before NSE has answered, and a refusal still leaves a list.
        at, rows = _read_json(SME_FILE)
        if isinstance(rows, list) and rows:
            _sme_cache.update({"at": at, "rows": rows})
            _index_reset()
            if (time.time() - at) < SME_TTL:
                return rows
    if not fetch:
        return _sme_cache["rows"] or []
    with _sme_lock:
        if _sme_cache["rows"] is not None and (time.time() - _sme_cache["at"]) < SME_TTL:
            return _sme_cache["rows"]
        text = _sme_text()
        if not text:
            # Not cached: the next call may get through.
            return _sme_cache["rows"] or []
        rows = parse_sme(text, lots=(master(fetch=fetch) or {}).get("nse_lots"))
        if rows:
            at = time.time()
            _sme_cache.update({"at": at, "rows": rows})
            _write_json(SME_FILE, at, rows)
            _index_reset()
        return rows or _sme_cache["rows"] or []


# ---------------------------------------------------------------------------
# The Dhan master: BSE rows, NSE ISINs, lot sizes
# ---------------------------------------------------------------------------

_master = {"at": 0.0, "data": None, "error": None, "next_try": 0.0}
_master_lock = threading.Lock()


def parse_master(lines):
    """
    Read Dhan's detailed instrument master, given as an iterable of text
    lines, into what this module needs:

        {"bse":      [{code, sym, name, series, isin, lot}, ...]  # BSE equity shares
         "nse_isins": [...],                                     # every NSE equity ISIN
         "nse_lots":  {SYMBOL: lot}}                              # NSE lots above one

    Equity shares only (INSTRUMENT EQUITY, INSTRUMENT_TYPE ES): the same file
    lists ETFs, bonds, government securities and mutual-fund units under the
    EQUITY instrument too.
    """
    reader = csv.reader(lines)
    try:
        header = [h.strip().upper() for h in next(reader)]
    except StopIteration:
        return None

    def col(*names):
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_ex = col("EXCH_ID", "SEM_EXM_EXCH_ID")
    i_sid = col("SECURITY_ID", "SEM_SMST_SECURITY_ID")
    i_isin = col("ISIN")
    i_ins = col("INSTRUMENT", "SEM_INSTRUMENT_NAME")
    i_typ = col("INSTRUMENT_TYPE", "SEM_EXCH_INSTRUMENT_TYPE")
    i_sym = col("UNDERLYING_SYMBOL", "SEM_TRADING_SYMBOL")
    i_name = col("SYMBOL_NAME", "SM_SYMBOL_NAME")
    i_disp = col("DISPLAY_NAME", "SEM_CUSTOM_SYMBOL")
    i_ser = col("SERIES", "SEM_SERIES")
    i_lot = col("LOT_SIZE", "SEM_LOT_UNITS")
    if None in (i_ex, i_sid, i_isin, i_ins, i_sym):
        return None

    def cell(row, i):
        try:
            return row[i].strip() if i is not None else ""
        except IndexError:
            return ""

    def lot_of(row):
        try:
            return int(float(cell(row, i_lot) or 1))
        except ValueError:
            return 1

    bse, nse_isins, nse_lots, seen_codes = [], set(), {}, set()
    for row in reader:
        if not row or cell(row, i_ins).upper() != "EQUITY":
            continue
        if i_typ is not None and cell(row, i_typ).upper() != "ES":
            continue
        ex = cell(row, i_ex).upper()
        if ex == "NSE":
            isin = cell(row, i_isin).upper()
            if isin:
                nse_isins.add(isin)
            lot = lot_of(row)
            sym = cell(row, i_sym).upper()
            if sym and lot > 1 and sym not in nse_lots:
                nse_lots[sym] = lot
        elif ex == "BSE":
            try:
                code = str(int(float(cell(row, i_sid))))
            except ValueError:
                continue
            if not _BSE_CODE.match(code) or code in seen_codes:
                continue
            seen_codes.add(code)
            name = cell(row, i_disp) or cell(row, i_name) or cell(row, i_sym)
            bse.append({"code": code, "sym": cell(row, i_sym).upper(), "name": name,
                        "series": cell(row, i_ser).upper(), "isin": cell(row, i_isin).upper(),
                        "lot": lot_of(row)})
    if not bse and not nse_isins:
        return None
    return {"bse": bse, "nse_isins": sorted(nse_isins), "nse_lots": nse_lots}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and "data" in d:
            return float(d.get("at") or 0), d["data"]
    except Exception:
        pass
    return 0.0, None


def _write_json(path, at, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"at": at, "data": data}, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass


def _read_disk():
    at, data = _read_json(MASTER_FILE)
    return (at, data) if isinstance(data, dict) else (0.0, None)


def _write_disk(at, data):
    _write_json(MASTER_FILE, at, data)


def _download_master():
    if requests is None:
        return None
    try:
        with requests.get(DHAN_DETAILED_URL, headers=DHAN_HEADERS,
                          timeout=(15, 180), stream=True) as r:
            if r.status_code != 200:
                _master["error"] = f"HTTP {r.status_code} downloading the instrument master"
                return None
            r.encoding = r.encoding or "utf-8"
            lines = ((l.decode("utf-8", "replace") if isinstance(l, bytes) else l)
                     for l in r.iter_lines(decode_unicode=True) if l)
            return parse_master(lines)
    except Exception as e:
        _master["error"] = str(e)[:160]
        return None


def master(fetch=True):
    """The parsed master, from memory, then disk, then Dhan. A stale copy is
    served when a refresh fails: yesterday's BSE list beats none."""
    now = time.time()
    if _master["data"] is not None and (now - _master["at"]) < MASTER_TTL:
        return _master["data"]
    if _master["data"] is None:
        at, data = _read_disk()
        if data is not None:
            _master.update({"at": at, "data": data})
            _index_reset()
            if (now - at) < MASTER_TTL or not fetch:
                return data
    if not fetch or now < _master["next_try"]:
        return _master["data"]
    with _master_lock:
        if _master["data"] is not None and (time.time() - _master["at"]) < MASTER_TTL:
            return _master["data"]
        data = _download_master()
        if data is not None:
            at = time.time()
            _master.update({"at": at, "data": data, "error": None})
            _write_disk(at, data)
            _index_reset()
        else:
            # Hold off retrying for an hour rather than downloading 36 MB on
            # every call while the CDN is refusing.
            _master["next_try"] = time.time() + 3600
    return _master["data"]


def bse_only(nse_isins=(), fetch=True):
    """
    The BSE-only companies, as listing rows keyed by scrip code.

    A BSE company is BSE-only when its ISIN is not among NSE's equity ISINs —
    those in Dhan's master and any the caller adds from NSE's own lists. A
    row with no ISIN cannot be told apart from a dual listing and is left out.
    Duplicate ISINs (a partly-paid line beside the fully paid) keep the first.
    """
    if not INCLUDE_BSE:
        return []
    m = master(fetch=fetch)
    if not m:
        return []
    known = set(m.get("nse_isins") or ())
    known.update(str(i).strip().upper() for i in (nse_isins or ()) if i)
    out, seen = [], set()
    for b in m.get("bse") or ():
        isin = b.get("isin") or ""
        if not isin or isin in known or isin in seen:
            continue
        seen.add(isin)
        series = b.get("series") or ""
        rec = {"s": b["code"], "n": b.get("name") or b.get("sym") or b["code"],
               "x": BSE_SME if series in BSE_SME_GROUPS else BSE,
               "t": b.get("sym") or "", "series": series, "isin": isin}
        if (b.get("lot") or 1) > 1:
            rec["lot"] = int(b["lot"])
        out.append(rec)
    out.sort(key=lambda r: r["s"])
    return out


def scan_eligible(row):
    """Whether a listing row belongs in the universe scan."""
    if row.get("x") in (BSE, BSE_SME):
        return (row.get("series") or "") not in BSE_SCAN_SKIP
    return True


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_index = {"map": None}


def _index_reset():
    _index["map"] = None


def _build_index():
    m = {}
    for r in nse_sme(fetch=False):
        m[r["s"]] = r
    for r in bse_only(fetch=False):
        m[r["s"]] = r
    _index["map"] = m
    return m


def info(symbol):
    """The listing row for a symbol on an SME board or BSE only, or None for
    an NSE main-board symbol (and for anything not yet loaded). Never
    downloads: reads what the lists already hold in memory or on disk."""
    m = _index["map"]
    if m is None:
        m = _build_index()
    return m.get(clean(symbol))


def board(symbol):
    """One of BOARDS. A scrip code that is not in the loaded list is still
    BSE; anything else not in it is NSE main board."""
    row = info(symbol)
    if row:
        return row["x"]
    return BSE if is_bse_code(symbol) else NSE


def is_sme(symbol):
    return board(symbol) in SME_BOARDS


def nse_indexes(symbol):
    """
    The `index` values to ask NSE's corporate APIs (results, shareholding)
    for, in order. NSE files an SME company under index=sme and answers an
    index=equities request for it with an empty list, so:

      a known SME symbol             -> ["sme"]
      a BSE-only scrip code          -> []        (NSE holds nothing for it)
      any other, SME list loaded     -> ["equities"]
      any other, SME list not loaded -> ["equities", "sme"]

    The second try costs one request, and only when the first came back
    empty: it is what finds an SME company in a process that has not read
    the SME list (from NSE or from disk) yet.
    """
    if is_bse_code(symbol):
        return []
    if board(symbol) == NSE_SME:
        return ["sme"]
    if not INCLUDE_SME or nse_sme(fetch=False):
        return ["equities"]
    return ["equities", "sme"]


def lot_size(symbol):
    """The exchange's lot, or 1. Main-board shares trade one at a time; SME
    shares only in lots, which is why a quantity on an SME stock must be a
    multiple of this."""
    row = info(symbol)
    if row and row.get("lot"):
        return int(row["lot"])
    m = _master["data"] or {}
    return int((m.get("nse_lots") or {}).get(clean(symbol)) or 1)


def describe(symbol):
    """The facts a stock page prints about the listing:
    {"board", "exchange", "sme", "lot", "bse_symbol", "series"}."""
    row = info(symbol) or {}
    b = row.get("x") or board(symbol)
    out = {"board": b, "exchange": BSE if b in (BSE, BSE_SME) else NSE,
           "sme": b in SME_BOARDS, "lot": lot_size(symbol)}
    if row.get("t"):
        out["bse_symbol"] = row["t"]
    if row.get("series"):
        out["series"] = row["series"]
    return out


def status():
    """For the admin page: what each source holds."""
    m = _master["data"] or {}
    return {
        "sme_enabled": INCLUDE_SME, "bse_enabled": INCLUDE_BSE,
        "nse_sme": len(_sme_cache["rows"] or []),
        "bse_master_rows": len(m.get("bse") or []),
        "bse_only": len(bse_only(fetch=False)) if m else 0,
        "master_age_h": (round((time.time() - _master["at"]) / 3600, 1)
                         if _master["at"] and m else None),
        "master_error": _master["error"],
        "bse_scan_skip_groups": list(BSE_SCAN_SKIP),
    }
