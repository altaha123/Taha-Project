"""
NSE SME and BSE-only companies in the universe (listings.py and the modules
that route a symbol to its exchange).

The rules these lock in:
  * a BSE-only company is keyed by its six-digit scrip code, which no NSE
    symbol can be, and is reached as CODE.BO on Yahoo and BSE_EQ on Dhan;
  * a company on both exchanges is covered once, by its NSE listing;
  * SME companies are scored but ranked apart from the main boards;
  * an SME share is ordered only in whole lots;
  * NSE's corporate APIs are asked with index=sme for an SME company, and not
    at all for a BSE-only one.
"""
import datetime as dt
import importlib.util
import os
import struct

import pytest

import listings


MASTER_CSV = """EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,INSTRUMENT_TYPE,SERIES,LOT_SIZE
NSE,E,2885,INE002A01018,EQUITY,,RELIANCE,RELIANCE INDUSTRIES LTD,Reliance Industries,ES,EQ,1.0
BSE,E,500325,INE002A01018,EQUITY,,RELIANCE,RELIANCE INDUSTRIES LTD.,Reliance Industries,ES,A,1.0
NSE,E,767261,INE11NS01011,EQUITY,,WATRANA,WATRANA RENTALS LIMITED,Watrana Rentals,ES,ST,600.0
NSE,E,9999,INE999Z01011,EQUITY,,ZEAL,ZEAL GLOBAL SERVICES LTD,Zeal Global,ES,EQ,1.0
BSE,E,534708,INE892L01019,EQUITY,,SHANTIGURU,SHANTI GURU INDUSTRIES,Shanti Guru Industries,ES,M,3000.0
BSE,E,500012,INE714B01016,EQUITY,,ANDHRAPET,ANDHRA PETROCHEMICALS,Andhra Petrochemicals,ES,X,1.0
BSE,E,539963,INE00KT01014,EQUITY,,ZEAL,ZEAL AQUA LTD,Zeal Aqua,ES,X,1.0
BSE,E,500285,INE285B01017,EQUITY,,SPICEJET,SPICEJET LTD,Spicejet,ES,Z,1.0
BSE,E,500286,INE285B01017,EQUITY,,SPICEJETPP,SPICEJET PARTLY PAID,Spicejet PP,ES,Z,1.0
BSE,E,890123,INE123X08011,EQUITY,,SOMEBOND,SOME BOND,Some Bond,DEB,F,1.0
BSE,E,590001,INE590A01010,EQUITY,,NIFTYBETF,SOME ETF,Some ETF,ETF,B,1.0
BSE,E,512345,,EQUITY,,NOISIN,NO ISIN LTD,No Isin,ES,X,1.0
"""

SME_CSV = """SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,ISIN_NUMBER,FACE_VALUE,
WATRANA,Watrana Rentals Limited,ST,27-Nov-26,10,INE11NS01011,10,
AAKAAR,Aakaar Medical Technologies Limited,SM,01-Jan-24,10,INE1GYP01013,10,
BADSME,Not Complying Limited,SZ,01-Jan-24,10,INE000000001,10,
"""


@pytest.fixture
def loaded(monkeypatch, tmp_path):
    """listings with the two lists above loaded and nothing on disk."""
    monkeypatch.setattr(listings, "MASTER_FILE", str(tmp_path / "m.json"))
    monkeypatch.setattr(listings, "SME_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(listings, "INCLUDE_SME", True)
    monkeypatch.setattr(listings, "INCLUDE_BSE", True)
    m = listings.parse_master(MASTER_CSV.splitlines())
    monkeypatch.setattr(listings, "_master", {"at": 9e18, "data": m, "error": None, "next_try": 0.0})
    sme = listings.parse_sme(SME_CSV, lots=m["nse_lots"])
    monkeypatch.setattr(listings, "_sme_cache", {"at": 9e18, "rows": sme})
    monkeypatch.setattr(listings, "_index", {"map": None})
    return listings


# ---------------------------------------------------------------------------
# Keys and routing
# ---------------------------------------------------------------------------

def test_a_scrip_code_is_bse_and_everything_else_is_nse():
    assert listings.is_bse_code("534708") and listings.is_bse_code("534708.BO")
    for s in ("TCS", "3MINDIA", "20MICRONS", "360ONE", "M&M", "12345", "1234567"):
        assert not listings.is_bse_code(s), s
    assert listings.ticker_key("534708") == "534708.BO"
    assert listings.ticker_key("TCS") == "TCS.NS"
    assert listings.ticker_key("TCS.BO") == "TCS.BO"        # an explicit suffix stands
    assert listings.yahoo_ticker("TCS") == "TCS.NS"
    assert listings.dhan_segment("534708.BO") == "BSE_EQ"
    assert listings.dhan_segment("WATRANA") == "NSE_EQ"


def test_yahoo_is_asked_by_the_bse_symbol_and_the_site_keeps_the_code(loaded, monkeypatch):
    """Yahoo names a BSE listing by its short symbol (SHANTIGURU.BO), and
    knows nothing by its code. The site's own ticker stays the code: Zeal
    Aqua's short symbol is ZEAL, which on NSE is a different company."""
    assert listings.yahoo_ticker("534708") == "SHANTIGURU.BO"
    assert listings.yahoo_ticker("539963.BO") == "ZEAL.BO"
    assert listings.yahoo_ticker("999999") == "999999.BO"        # unknown: never guessed
    import data_source
    import pandas as pd
    asked = []

    class T:
        def __init__(self, name):
            asked.append(name)

        def history(self, **kw):
            n = 80
            return pd.DataFrame({"Open": [1.0] * n, "High": [1.0] * n, "Low": [1.0] * n,
                                 "Close": [1.0] * n, "Volume": [1] * n},
                                index=pd.bdate_range("2026-01-01", periods=n))
    monkeypatch.setattr(data_source, "yf", type("Y", (), {"Ticker": T}))
    monkeypatch.setattr(data_source, "dhan", None)
    monkeypatch.setattr(data_source, "_CACHE", {})
    monkeypatch.setattr(data_source.settled_bars, "keep", lambda k, df: df)
    sym, _t, _h = data_source.resolve("539963")
    assert sym == "539963.BO" and asked == ["ZEAL.BO"]


def test_no_nse_symbol_in_the_fallback_list_looks_like_a_scrip_code():
    import scan
    assert not [s for s in scan.FALLBACK.split() if listings.is_bse_code(s)]


# ---------------------------------------------------------------------------
# The lists
# ---------------------------------------------------------------------------

def test_the_master_keeps_equity_shares_only():
    m = listings.parse_master(MASTER_CSV.splitlines())
    codes = {b["code"] for b in m["bse"]}
    assert "890123" not in codes and "590001" not in codes      # a bond, an ETF
    assert {"500325", "534708", "500012", "539963"} <= codes
    assert "INE002A01018" in m["nse_isins"]
    assert m["nse_lots"] == {"WATRANA": 600}


def test_sme_list_keeps_sm_and_st_with_their_lots(loaded):
    rows = {r["s"]: r for r in loaded.nse_sme(fetch=False)}
    assert set(rows) == {"WATRANA", "AAKAAR"}                    # SZ left out, as BZ is
    assert rows["WATRANA"]["x"] == listings.NSE_SME and rows["WATRANA"]["lot"] == 600
    assert "lot" not in rows["AAKAAR"]                           # not in the master: unknown


def test_bse_only_drops_dual_listings_and_keys_by_code(loaded):
    rows = {r["s"]: r for r in loaded.bse_only(fetch=False)}
    assert "500325" not in rows                 # Reliance is on NSE: covered once, there
    assert "512345" not in rows                 # no ISIN, cannot be told from a dual listing
    assert rows["534708"]["x"] == listings.BSE_SME and rows["534708"]["lot"] == 3000
    assert rows["534708"]["t"] == "SHANTIGURU"
    # Zeal Aqua shares NSE's symbol ZEAL with a different company; the code
    # keeps them apart.
    assert rows["539963"]["t"] == "ZEAL" and rows["539963"]["n"] == "Zeal Aqua"
    # The partly-paid line has the same ISIN as the fully paid one: one row.
    assert ("500285" in rows) != ("500286" in rows)


def test_an_isin_from_nses_own_list_also_counts_as_listed_on_nse(loaded):
    assert "500012" in {r["s"] for r in loaded.bse_only(fetch=False)}
    assert "500012" not in {r["s"] for r in loaded.bse_only(["INE714B01016"], fetch=False)}


def test_the_scan_skips_bse_groups_z_and_zp(loaded):
    rows = {r["s"]: r for r in loaded.bse_only(fetch=False)}
    spice = rows.get("500285") or rows.get("500286")
    assert not listings.scan_eligible(spice)
    assert listings.scan_eligible(rows["500012"]) and listings.scan_eligible(rows["534708"])


def test_describe_gives_the_board_and_the_lot(loaded):
    assert listings.describe("534708")["board"] == listings.BSE_SME
    assert listings.describe("534708")["exchange"] == "BSE"
    assert listings.describe("534708")["bse_symbol"] == "SHANTIGURU"
    assert listings.describe("WATRANA.NS") == {"board": listings.NSE_SME, "exchange": "NSE",
                                               "sme": True, "lot": 600, "series": "ST"}
    assert listings.describe("TCS") == {"board": listings.NSE, "exchange": "NSE",
                                        "sme": False, "lot": 1}
    assert listings.board("999999") == listings.BSE         # a code not in the list is still BSE


def test_the_lists_survive_a_restart_from_disk(loaded, monkeypatch):
    listings._write_disk(1.0, listings._master["data"])
    listings._write_json(listings.SME_FILE, 2.0, listings._sme_cache["rows"])
    monkeypatch.setattr(listings, "_master", {"at": 0.0, "data": None, "error": None, "next_try": 0.0})
    monkeypatch.setattr(listings, "_sme_cache", {"at": 0.0, "rows": None})
    monkeypatch.setattr(listings, "_index", {"map": None})
    assert listings.board("WATRANA") == listings.NSE_SME
    assert listings.board("534708") == listings.BSE_SME
    assert listings.lot_size("534708") == 3000


def test_a_failed_master_download_is_not_retried_on_every_call(monkeypatch, tmp_path):
    monkeypatch.setattr(listings, "MASTER_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(listings, "_master", {"at": 0.0, "data": None, "error": None, "next_try": 0.0})
    calls = []
    monkeypatch.setattr(listings, "_download_master", lambda: calls.append(1))
    assert listings.master() is None and listings.master() is None
    assert len(calls) == 1


def test_nse_is_asked_with_the_right_index(loaded, monkeypatch):
    assert listings.nse_indexes("WATRANA") == ["sme"]
    assert listings.nse_indexes("534708") == []
    assert listings.nse_indexes("TCS") == ["equities"]             # SME list loaded: it is not SME
    monkeypatch.setattr(listings, "_sme_cache", {"at": 9e18, "rows": []})
    monkeypatch.setattr(listings, "SME_FILE", "/nonexistent/x.json")
    monkeypatch.setattr(listings, "_index", {"map": None})
    assert listings.nse_indexes("NEWSME") == ["equities", "sme"]   # not known yet: try both


# ---------------------------------------------------------------------------
# The universe
# ---------------------------------------------------------------------------

def test_the_universe_adds_sme_and_bse_only_once_each(loaded, monkeypatch):
    import scan
    monkeypatch.setattr(scan, "fetch_nse_list", lambda: (["RELIANCE", "TCS", "ZEAL"], "NSE official list"))
    monkeypatch.setattr(scan, "_nse_isins", lambda: {"INE002A01018"})
    syms, source = scan.fetch_universe()
    assert syms[:3] == ["RELIANCE", "TCS", "ZEAL"]
    assert "WATRANA" in syms and "AAKAAR" in syms
    assert "534708" in syms and "539963" in syms and "500012" in syms
    assert "500325" not in syms                                    # Reliance once, on NSE
    assert "500285" not in syms and "500286" not in syms           # group Z skipped
    assert len(syms) == len(set(syms))
    assert "NSE SME (2)" in source and "BSE-only (3)" in source


def test_switching_both_off_is_the_old_universe(loaded, monkeypatch):
    import scan
    monkeypatch.setattr(listings, "INCLUDE_SME", False)
    monkeypatch.setattr(listings, "INCLUDE_BSE", False)
    monkeypatch.setattr(scan, "fetch_nse_list", lambda: (["TCS"], "NSE official list"))
    monkeypatch.setattr(scan, "_nse_isins", lambda: set())
    assert scan.fetch_universe() == (["TCS"], "NSE official list")


def test_sme_rows_are_ranked_apart(monkeypatch):
    import scan
    import multifactor

    def rank(rows, horizon):
        out = []
        for i, r in enumerate(rows):
            out.append(dict(r, position_score=90 - i, altaha_score_v4={"score": 90 - i}))
        return {"rows": out}
    monkeypatch.setattr(multifactor, "rank", rank)
    monkeypatch.setattr(multifactor, "presentation", lambda v: {"label": "x", "tone": "y"})
    rows = [{"symbol": "SMEA", "board": listings.NSE_SME, "sme": True},
            {"symbol": "TCS", "board": listings.NSE},
            {"symbol": "534708", "board": listings.BSE_SME, "sme": True},
            {"symbol": "500012", "board": listings.BSE}]
    p = scan._build_payload(rows, "src", 4, 0, 4, 0, 0, 4, [])
    assert [r["symbol"] for r in p["rankings"]] == ["TCS", "500012"]
    assert [r["symbol"] for r in p["sme_rankings"]] == ["SMEA", "534708"]
    assert len(p["factor_universe"]) == 4                     # everyone is still scored
    assert p["scored_by_board"] == {listings.NSE_SME: 1, listings.NSE: 1,
                                    listings.BSE_SME: 1, listings.BSE: 1}


def test_an_untraded_bse_or_sme_name_is_dropped_before_its_history_is_read(loaded, monkeypatch):
    import scan

    class D:
        @staticmethod
        def configured():
            return True

        @staticmethod
        def bulk_quotes(symbols, mode="quote"):
            return {s: {"ltp": 50.0, "volume": 0} for s in symbols}
    monkeypatch.setattr(scan, "dhan", D)
    keep, dropped = scan.prefilter_by_quote(["TCS", "500012", "WATRANA"], {}, None)
    assert keep == ["TCS"] and dropped == 2


# ---------------------------------------------------------------------------
# Dhan
# ---------------------------------------------------------------------------

@pytest.fixture
def realdhan(tmp_path):
    """The real dhan_source (conftest stubs the import), loaded on its own."""
    path = os.path.join(os.path.dirname(listings.__file__), "dhan_source.py")
    spec = importlib.util.spec_from_file_location("dhan_source_listings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._PREV_FILE = str(tmp_path / "prev_close.json")
    return mod


def test_bulk_quotes_ask_each_segment_separately(realdhan, monkeypatch):
    d = realdhan
    monkeypatch.setattr(d, "configured", lambda: True)
    # An NSE id and a BSE code can be the same number for two companies (here
    # Reliance's NSE id is made to equal Shanti Guru's code), so the answer
    # must be read back per segment.
    monkeypatch.setattr(d, "load_scrip", lambda force=False: {"RELIANCE": "534708", "534708": "534708"})
    asked = []

    def call(path, ids, segment="NSE_EQ"):
        asked.append((segment, list(ids)))
        return {"534708": {"last_price": 100.0 if segment == "NSE_EQ" else 7.5}}
    monkeypatch.setattr(d, "_quote_call", call)
    monkeypatch.setattr(d, "_settle_prev_close", lambda out, now=None: None)
    out = d.bulk_quotes(["RELIANCE", "534708"], mode="ltp")
    assert sorted(asked) == [("BSE_EQ", ["534708"]), ("NSE_EQ", ["534708"])]
    assert out["RELIANCE"]["ltp"] == 100.0 and out["534708"]["ltp"] == 7.5


def test_history_for_a_scrip_code_is_asked_on_bse(realdhan, monkeypatch):
    d = realdhan
    monkeypatch.setattr(d, "configured", lambda: True)
    monkeypatch.setattr(d, "security_id", lambda s: "534708")
    monkeypatch.setattr(d, "_throttle_hist", lambda: None)
    sent = []

    class R:
        status_code = 500
        text = ""

    def post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return R()
    monkeypatch.setattr(d.requests, "post", post)
    monkeypatch.setattr(d, "_headers", lambda: {})
    d.daily_ohlcv("534708")
    d.intraday_ohlcv("534708")
    d.daily_ohlcv("TCS")
    assert [b["exchangeSegment"] for b in sent] == ["BSE_EQ", "BSE_EQ", "NSE_EQ"]


def test_options_are_never_looked_up_for_a_bse_code(realdhan, monkeypatch):
    d = realdhan
    monkeypatch.setattr(d, "security_id", lambda s: "534708")
    assert d.underlying_ref("534708") == (None, None)


def test_the_live_feed_matches_a_price_by_segment_and_id(monkeypatch):
    import livefeed
    feed = livefeed._Feed()
    ids = {"RELIANCE": "534708", "534708": "534708"}
    monkeypatch.setattr(livefeed.D, "security_id", lambda s: ids.get(s), raising=False)
    feed.want(["RELIANCE", "534708.BO"])
    assert feed.sym_to_sid == {"RELIANCE": "1:534708", "534708": "4:534708"}

    def packet(seg, sid, ltp):
        return struct.pack("<BhBif", livefeed.FEED_TICKER, 16, seg, sid, ltp) + b"\0" * 4
    feed._decode(packet(1, 534708, 2900.0) + packet(4, 534708, 41.5))
    assert feed.prices["RELIANCE"]["ltp"] == 2900.0
    assert feed.prices["534708"]["ltp"] == 41.5


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _order(**kw):
    o = {"symbol": "WATRANA", "side": "BUY", "qty": 600, "type": "LIMIT", "price": 100,
         "client_ref": "r" * 24}
    o.update(kw)
    return o


def test_an_sme_order_must_be_whole_lots(loaded):
    import brokers
    if not brokers.REF_RE.match("r" * 24):
        pytest.skip("reference format changed")
    assert brokers.clean_order(_order(qty=1200), 100)["qty"] == 1200
    with pytest.raises(ValueError, match="lots of 600"):
        brokers.clean_order(_order(qty=601), 100)
    # A main-board share still trades one at a time.
    assert brokers.clean_order(_order(symbol="TCS", qty=7), 100)["qty"] == 7


def test_a_bse_only_order_goes_to_bse(loaded, monkeypatch):
    import broker_dhan
    import broker_zerodha
    assert broker_dhan._segment("534708") == "BSE_EQ"
    assert broker_zerodha.instrument("534708") == "SHANTIGURU"
    assert broker_zerodha.instrument("999999") is None           # an unknown code is never guessed
    assert broker_zerodha.instrument("TCS") == "TCS"
    sent = {}
    monkeypatch.setattr(broker_zerodha, "_call",
                        lambda method, path, sess, data=None, timeout=None: sent.update(data) or {"order_id": "1"})
    broker_zerodha.place({}, {"symbol": "534708", "security_id": "SHANTIGURU", "side": "BUY",
                              "type": "LIMIT", "qty": 3000, "product": "CNC", "validity": "DAY",
                              "correlation_id": "alt1x00", "price": 10})
    assert sent["exchange"] == "BSE" and sent["tradingsymbol"] == "SHANTIGURU"


# ---------------------------------------------------------------------------
# NSE's corporate APIs
# ---------------------------------------------------------------------------

def test_results_for_an_sme_company_are_read_from_the_sme_index(loaded, monkeypatch):
    import xbrl
    asked = []

    def api(url, params):
        asked.append(params["index"])
        return []
    monkeypatch.setattr(xbrl, "_api", api)
    xbrl.filings("WATRANA")
    assert set(asked) == {"sme"}
    asked.clear()
    assert xbrl.filings("534708") == [] and asked == []          # BSE-only: NSE is not asked


def test_a_half_year_filing_is_never_taken_for_a_quarter():
    """An SME company reports every six months. The quarterly factors must
    not read a six-month profit as one quarter's."""
    import factors
    q = {"period": {"from": "2026-04-01", "to": "2026-09-30"}, "filed_at": "2026-10-30",
         "revenue": 437.0, "pat": 35.0, "consolidated": False}
    assert factors.known_quarters([q], as_of=dt.date(2026, 11, 28)) == []
    import fundamentals
    assert not fundamentals._is_quarterly({"from": "2026-04-01", "to": "2026-09-30"})


def test_shareholding_documents_on_nses_new_archive_host_are_accepted():
    import shareholding_filings as sf
    ok = "https://nsearchives.nseindia.in/corporate/xbrl/SHP_1739215_15102026060516_WEB.xml"
    assert sf._safe_doc_url(ok) == ok
    assert sf._safe_doc_url("https://nsearchives.nseindia.com/corporate/xbrl/a.xml")
    for bad in ("https://evil.nseindia.in/a.xml", "https://nseindia.in.evil.com/a.xml",
                "http://nsearchives.nseindia.in/a.xml"):
        assert sf._safe_doc_url(bad) is None, bad
