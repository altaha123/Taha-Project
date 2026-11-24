"""
money_flow_config.py — the mapping table and every weight Money Flow uses

Nothing in money_flow.py is a number typed where it is used. The sector
mapping, the score weights and the thresholds are all here, so changing one is
a one-line diff with its reason beside it.

THE MAPPING, AND WHY ONE HALF OF IT IS EXACT
NSDL files FPI money under the 22 sectors of the industry classification NSE
and BSE adopted in March 2022 (plus "Sovereign" and "Others", which are not
equity sectors). backend/nse_industries.csv, the classification this site's
stock universe already carries, is NSE's own copy of the same 22. So

    NSDL sector  ->  our stocks        is the SAME LIST, one to one. NSDL
                                       writes two names with commas ("Oil, Gas
                                       & Consumable Fuels") and NSE without.

    NSDL sector  ->  an NSE index      is a judgement, and each row below
                                       says how good a fit it is.

`fit` is one of:
    clean      the index is that sector.
    broad      the index is the sector plus something else, or a part of it.
    ambiguous  two indices could be argued; the note says which and why.
    none       NSE publishes no index for it. Relative strength comes from a
               basket of the sector's own stocks, weighted by rupees traded.

A sector whose index has under MIN_INDEX_SESSIONS of history stored (six of
the indices below were launched after November 2024) is also measured on the
basket until the index has enough, and its card says which it used.
"""

import os
import re

BENCHMARK = "NIFTY 50"
BENCHMARK_LABEL = "Nifty 50"

# name    the classification's spelling (nse_industries.csv), used everywhere
# short   what a card has room for
# index   NSE's name for the index, upper case as money_flow_sources.index_key
SECTORS = [
    {"name": "Automobile and Auto Components", "short": "Auto",
     "index": "NIFTY AUTO", "fit": "clean"},
    {"name": "Capital Goods", "short": "Capital Goods",
     "index": "NIFTY CAPITAL GOODS", "fit": "clean",
     "note": "A new index: not in NSE's daily file in November 2024."},
    {"name": "Chemicals", "short": "Chemicals",
     "index": "NIFTY CHEMICALS", "fit": "clean",
     "note": "A new index: not in NSE's daily file in November 2024."},
    {"name": "Construction", "short": "Construction",
     "index": "NIFTY INFRASTRUCTURE", "fit": "ambiguous",
     "note": "NSE has no construction index. Nifty Infrastructure is the nearest, but its "
             "largest weights are Reliance, Bharti Airtel, L&T and the power companies, "
             "so it is an infrastructure index and not a construction one. Nifty Realty "
             "and Nifty Housing were the alternatives and fit worse."},
    {"name": "Construction Materials", "short": "Cement",
     "index": "NIFTY CEMENT", "fit": "broad",
     "note": "Cement is nearly all of this sector by value, but not all of it. A new "
             "index: not in NSE's daily file in November 2024."},
    {"name": "Consumer Durables", "short": "Durables",
     "index": "NIFTY CONSUMER DURABLES", "fit": "clean"},
    {"name": "Consumer Services", "short": "Consumer Services",
     "index": "NIFTY CONSUMER SERVICES", "fit": "clean",
     "note": "A new index: not in NSE's daily file in November 2024."},
    {"name": "Diversified", "short": "Diversified",
     "index": None, "fit": "none",
     "note": "No index, and one company in our universe."},
    {"name": "Fast Moving Consumer Goods", "short": "FMCG",
     "index": "NIFTY FMCG", "fit": "clean"},
    {"name": "Financial Services", "short": "Financials",
     "index": "NIFTY FINANCIAL SERVICES", "fit": "clean",
     "note": "NSDL reports banks, NBFCs, insurers and brokers as one sector, so FPI flow "
             "cannot be split between Nifty Bank, Private Bank and PSU Bank. Those are "
             "shown as themes, on price only."},
    {"name": "Forest Materials", "short": "Forest",
     "index": None, "fit": "none",
     "note": "No index, and one company in our universe."},
    {"name": "Healthcare", "short": "Healthcare",
     "index": "NIFTY HEALTHCARE INDEX", "fit": "clean",
     "note": "Healthcare is pharma plus hospitals and diagnostics. Nifty Pharma is a "
             "part of it and is shown as a theme."},
    {"name": "Information Technology", "short": "IT",
     "index": "NIFTY IT", "fit": "clean"},
    {"name": "Media Entertainment & Publication", "short": "Media",
     "index": "NIFTY MEDIA", "fit": "clean"},
    {"name": "Metals & Mining", "short": "Metals",
     "index": "NIFTY METAL", "fit": "clean"},
    {"name": "Oil Gas & Consumable Fuels", "short": "Oil & Gas",
     "index": "NIFTY OIL & GAS", "fit": "clean",
     "note": "Nifty Energy was the other candidate; it also holds the power companies, "
             "which NSDL reports under Power."},
    {"name": "Power", "short": "Power",
     "index": "NIFTY POWER", "fit": "clean",
     "note": "A new index: not in NSE's daily file in November 2024."},
    {"name": "Realty", "short": "Realty",
     "index": "NIFTY REALTY", "fit": "clean"},
    {"name": "Services", "short": "Services",
     "index": "NIFTY TRANSPORTATION & LOGISTICS", "fit": "ambiguous",
     "note": "The classification's Services sector is transport, logistics, ports and "
             "commercial services. Nifty Services Sector sounds right and is not: it is "
             "banks, IT and telecom. Nifty Transportation & Logistics is used, though it "
             "also holds the automobile makers."},
    {"name": "Telecommunication", "short": "Telecom",
     "index": "NIFTY TELECOMMUNICATIONS", "fit": "clean",
     "note": "A new index: not in NSE's daily file in November 2024."},
    {"name": "Textiles", "short": "Textiles",
     "index": None, "fit": "none",
     "note": "NSE publishes no textiles index."},
    {"name": "Utilities", "short": "Utilities",
     "index": None, "fit": "none",
     "note": "No index, and four companies in our universe."},
]

# NSDL rows that are not equity sectors. Kept in the store, left off the page.
NOT_SECTORS = ("Sovereign", "Others")

# Indices people ask for that cut ACROSS the classification, so no NSDL sector
# stands behind them: a public-sector company is filed under what it does, not
# who owns it. They are drawn on the rotation chart from price alone and get
# no FPI flow and no Money Flow Score.
THEMES = [
    {"name": "Banks", "index": "NIFTY BANK", "part_of": "Financial Services"},
    {"name": "Private Banks", "index": "NIFTY PRIVATE BANK", "part_of": "Financial Services"},
    {"name": "PSU Banks", "index": "NIFTY PSU BANK", "part_of": "Financial Services"},
    {"name": "Pharma", "index": "NIFTY PHARMA", "part_of": "Healthcare"},
    {"name": "PSE", "index": "NIFTY PSE", "part_of": None},
    {"name": "Energy", "index": "NIFTY ENERGY", "part_of": None},
]


def _key(name):
    return re.sub(r"[^a-z0-9&]+", " ", str(name or "").lower().replace(",", " ")).strip()


_BY_KEY = {_key(s["name"]): s for s in SECTORS}
_BY_KEY.update({_key(n): {"name": n, "short": n, "index": None, "fit": "none", "not_sector": True}
                for n in NOT_SECTORS})


def canonical(name):
    """NSDL's or NSE's spelling -> the one name used in the store, or None for
    a sector this table does not know (which the caller reports, loudly)."""
    hit = _BY_KEY.get(_key(name))
    return hit["name"] if hit else None


def sector(name):
    hit = _BY_KEY.get(_key(name))
    return None if not hit or hit.get("not_sector") else hit


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


_BY_SLUG = {slug(s["name"]): s for s in SECTORS}


def by_slug(value):
    return _BY_SLUG.get(slug(value)) or sector(value)


def mapping_table():
    """The table as the page and the PR print it."""
    return ([{"nsdl_sector": s["name"], "short": s["short"], "nse_index": s["index"],
              "fit": s["fit"], "note": s.get("note")} for s in SECTORS]
            + [{"nsdl_sector": n, "short": n, "nse_index": None, "fit": "excluded",
                "note": "Not an equity sector."} for n in NOT_SECTORS])


# ---------------------------------------------------------------------------
# The Sector Money Flow Score
# ---------------------------------------------------------------------------

def _env_weights(name, default):
    """MONEYFLOW_WEIGHTS="fpi=40,rs=35,breadth=25" overrides the default. A
    value that cannot be read, or names a part that does not exist, is
    ignored whole: a half-applied weight change is worse than none."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return dict(default)
    try:
        got = {k.strip(): float(v) for k, v in (p.split("=") for p in raw.split(",") if p.strip())}
    except ValueError:
        return dict(default)
    if set(got) != set(default) or any(v < 0 for v in got.values()) or sum(got.values()) <= 0:
        return dict(default)
    return got


# The three parts of the score, out of 100 between them.
SCORE_WEIGHTS = _env_weights("MONEYFLOW_WEIGHTS", {"fpi": 40.0, "rs": 35.0, "breadth": 25.0})

# Inside the FPI part. Each is a percentile rank among the scored sectors of a
# flow measured as a share of the sector's assets under custody, so a large
# sector does not win on size:
#   sum3    the last three fortnights together
#   latest  the latest fortnight
#   change  the latest fortnight less the one before
FPI_BLEND = {"sum3": 0.5, "latest": 0.3, "change": 0.2}

# Inside the relative-strength part: where the sector sits on the rotation
# chart, and its return against the Nifty 50 over three months and one.
RS_BLEND = {"quadrant": 0.4, "rs_3m": 0.35, "rs_1m": 0.25}
QUADRANT_VALUE = {"Leading": 1.0, "Improving": 0.75, "Weakening": 0.4, "Lagging": 0.1}

FPI_ROLLING = 3                 # fortnights in the rolling sum
HEATMAP_FORTNIGHTS = 12
DETAIL_FORTNIGHTS = 24
FLAT_CR = 1.0                   # a net flow smaller than this has no direction

RS_1M, RS_3M = 21, 63           # sessions
RRG_RATIO_WEEKS = 10            # RS-ratio: relative strength over its own 10-week mean
RRG_MOMENTUM_WEEKS = 4          # RS-momentum: RS-ratio over its own 4-week mean
RRG_TRAIL_WEEKS = 8
MIN_INDEX_SESSIONS = 130        # about six months; under it the basket is used
BREADTH_DMA = 50
BREADTH_MIN_OBS = 40
MIN_MEMBERS = 5                 # stocks a sector needs for breadth and for a score
CA_DROP, CA_JUMP = -0.30, 0.45  # a one-session move this large is a split or bonus
BASKET_MAX_WEIGHT = 0.25        # no stock is more than this much of a basket

# ---------------------------------------------------------------------------
# Accumulation, stock by stock, inside a sector
# ---------------------------------------------------------------------------
ACC_TOP = 10                    # rows kept per sector
ACC_BASE = 20                   # sessions in "its usual"
ACC_RECENT = 5
ACC_MIN_TURNOVER_CR = 2.0       # a usual day's turnover below this is left out
ACC_DELIVERY_PTS = 45.0         # delivery share: last 5 sessions against the 20 before
ACC_DELIVERY_LOW, ACC_DELIVERY_HIGH = 0.9, 1.5   # that ratio, mapped onto 0..45
ACC_PRICE_VOLUME_PTS = 40.0     # 8 per session of the last 5 up on above-usual volume
ACC_DEAL_PTS = 15.0             # +15 net bought in bulk/block deals, -15 net sold
ACC_DEAL_DAYS = 30
ACC_DEAL_MIN_CR = 1.0

FLOW_SESSIONS = 60              # sessions of FII/DII the hero chart carries

# ---------------------------------------------------------------------------
# Ideas: sector caps that follow the score. OFF unless IDEAS_MONEYFLOW_CAPS=on.
# ---------------------------------------------------------------------------
CAPS_ON = os.environ.get("IDEAS_MONEYFLOW_CAPS", "").strip().lower() in ("1", "on", "true", "yes")
CAP_TOP = int(os.environ.get("IDEAS_MONEYFLOW_CAP_TOP", "5") or 5)        # top quarter of sectors
CAP_BOTTOM = int(os.environ.get("IDEAS_MONEYFLOW_CAP_BOTTOM", "2") or 2)  # bottom quarter

# Telegram, when a sector moves into Improving or Leading with FPIs buying.
# On whenever Telegram itself is configured; MONEYFLOW_TELEGRAM=off silences it.
ALERTS_ON = os.environ.get("MONEYFLOW_TELEGRAM", "on").strip().lower() not in ("0", "off", "false", "no")
ALERT_REQUIRE_FLIP = os.environ.get("MONEYFLOW_ALERT_REQUIRE_FLIP", "").strip().lower() in ("1", "on", "true", "yes")

BACKFILL_MONTHS = int(os.environ.get("MONEYFLOW_BACKFILL_MONTHS", "24") or 24)
SETTLE_DAYS = 2                 # a file this young may simply not be out yet
