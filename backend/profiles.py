"""
Altaha Screener — Business-Model Profiles  (scoring v3)

THE PROBLEM THIS SOLVES
-----------------------
Until now every stock was scored 50% technical, 50% fundamental, using the
same checks with the same weights. That is wrong in two separate ways, and a
Chartered Accountant will recognise both immediately.

1. THE SAME RATIO DOES NOT MEAN THE SAME THING IN EVERY INDUSTRY.
   Debt/Equity of 8 is a distress signal for a cement company and completely
   normal for a bank, because for a bank leverage IS the business model.
   Gross margin is meaningful for a branded consumer company and undefined
   for a lender. Asset turnover is a real measure for a manufacturer and
   noise for a software firm. Piotroski's F-Score was built and validated on
   non-financial firms; applying all nine bits to HDFC Bank is not rigour,
   it is a category error that produces a confident-looking wrong number.

2. LOW P/E ON A CYCLICAL IS A WARNING, NOT A BARGAIN.
   A steel company at the top of the cycle trades at 5x trailing earnings
   precisely because those earnings are about to fall. The old engine gave
   it full marks for cheapness. This module detects where operating margin
   sits inside its own multi-year range and inverts the valuation signal at
   the top of the cycle — which is what the textbook says to do and what the
   previous version did the opposite of.

WHAT IT PRODUCES
----------------
Nothing is hidden. score() returns the weights it used, the reason for each
weight, every check it deliberately ignored and why, and a confidence figure
based on how much data was actually available. The audit trail is the
product; this module extends it rather than adding a black box on top.

HORIZON
-------
Weights also depend on how long the reader intends to hold. A three-day trade
does not care about return on capital; a three-year holding does not care
about RSI. Pretending one number serves both is the second-biggest flaw in
the old design. Three horizons are supported and the caller picks.

WHAT THIS MODULE IS NOT
-----------------------
It is not a prediction and it does not become one by being better weighted.
It is a structured, disclosed opinion about which evidence deserves more
attention for this kind of business over this length of time.
"""

import math

# ---------------------------------------------------------------------------
# 1 · The five pillars
#
# Reused from archetypes.py so there is one definition of what a pillar is.
# momentum      — is price trending, with force
# participation — is volume and the shareholding register confirming it
# quality       — is the business durably good right now
# improvement   — is it getting better, regardless of the level
# valuation     — what is being paid for it
# ---------------------------------------------------------------------------

PILLARS = ("momentum", "participation", "quality", "improvement", "valuation")


# ---------------------------------------------------------------------------
# 2 · Horizon base weights
#
# These are the weights before the business model adjusts them. They encode
# one idea: the further out you look, the less price action tells you and the
# more the business tells you.
# ---------------------------------------------------------------------------

HORIZONS = {
    "trade": {
        "label": "Days to weeks",
        "note": ("Over days, the business barely changes — only the tape does. "
                 "Quality is kept as a floor so the scanner does not surface junk "
                 "that happens to be moving, but it cannot carry a score."),
        "weights": {"momentum": .44, "participation": .28, "quality": .16,
                    "improvement": .06, "valuation": .06},
    },
    "position": {
        "label": "Weeks to months",
        "note": ("The middle distance, where a business inflecting and a chart "
                 "turning tend to happen together. This is the only horizon "
                 "where all five pillars genuinely deserve a seat."),
        "weights": {"momentum": .26, "participation": .20, "quality": .24,
                    "improvement": .20, "valuation": .10},
    },
    "invest": {
        "label": "One year and beyond",
        "note": ("Over years, entry timing washes out and what remains is what "
                 "the business earns on its capital and what you paid. Momentum "
                 "is kept only to flag buying into a collapsing trend."),
        "weights": {"momentum": .10, "participation": .08, "quality": .36,
                    "improvement": .21, "valuation": .25},
    },
}

DEFAULT_HORIZON = "position"


# ---------------------------------------------------------------------------
# 3 · Business models
#
# Eight buckets covering the Indian listed market. Each carries:
#
#   bias        multipliers applied to the horizon weights, then renormalised
#   suppress    checks that do not apply to this kind of business, with the
#               reason — these are removed from the scoring base entirely
#               rather than scored as failures, which is what the old engine
#               did and why lenders scored badly for being lenders
#   valuation   which measure means anything here: pe, pb, or cycle
#   matters     plain-English statement of what actually drives this business,
#               shown to the reader
#   missing     what this data source cannot see, stated openly
# ---------------------------------------------------------------------------

_F = "F-Score · "
_G = "G-Score · "

BUSINESS_MODELS = {

    "lender": {
        "name": "Lender",
        "examples": "banks, NBFCs, housing finance, microfinance",
        "bias": {"quality": 1.35, "improvement": 1.25, "valuation": 1.10,
                 "momentum": 0.85, "participation": 0.90},
        "valuation": "pb",
        "matters": ("For a lender the balance sheet is the product, not a means of "
                    "funding one. What decides the outcome is the quality of the loan "
                    "book, the margin between what it pays for deposits and earns on "
                    "advances, and how much capital sits behind the risk. Growth "
                    "without asset quality is how lenders fail."),
        "suppress": {
            "Debt / Equity": ("Leverage is the business model for a lender, not a "
                              "warning sign. A bank with low debt to equity is a bank "
                              "that is not lending."),
            _G + "Gross margin level": "Lenders do not report a gross margin.",
            _G + "Reinvestment intensity": ("Capex to revenue is meaningless for a "
                                            "lender — its growth spending is capital, "
                                            "not plant."),
            _F + "Gross margin expanding": "No gross margin is reported.",
            _F + "Asset turnover rising": ("Revenue over assets for a lender is just "
                                           "yield on advances, and is read directly "
                                           "rather than as a turnover ratio."),
            "Valuation (P/E)": ("Lenders are valued on price to book against return "
                                "on equity, not on earnings multiples."),
            _F + "Positive operating cash flow": (
                "Operating cash flow for a bank is dominated by deposit and advance "
                "movements. A fast-growing, perfectly healthy lender routinely reports "
                "negative CFO because it lent the money out."),
            _F + "CFO exceeds net income": (
                "The same reason — the comparison is not meaningful when lending itself "
                "is the operating cash outflow."),
            _G + "Cash return on assets": (
                "Cash flow over assets does not describe a lender's productivity; return "
                "on equity against cost of funds does."),
            _G + "Low accruals": (
                "Accrual analysis assumes an operating cycle that converts sales to cash. "
                "A loan book does not work that way."),
        },
        "missing": ("This data source does not publish gross NPA, provision coverage, "
                    "net interest margin, CASA ratio or capital adequacy. Those are the "
                    "five numbers that matter most for a lender, so treat this score as "
                    "a partial view and read the results filing itself."),
    },

    "compounder": {
        "name": "Asset-light compounder",
        "examples": "IT services, branded pharma, exchanges, asset managers, platforms",
        "bias": {"quality": 1.30, "improvement": 1.10, "valuation": 0.85,
                 "momentum": 0.95, "participation": 1.00},
        "valuation": "pe",
        "matters": ("These businesses need very little capital to grow, so the test is "
                    "whether high returns on capital persist and whether reported profit "
                    "turns into cash. They rarely look cheap, and demanding a low "
                    "multiple from one is how people miss the entire category — so "
                    "valuation is deliberately given less weight here than elsewhere."),
        "suppress": {
            _G + "Reinvestment intensity": ("Low capex is the point of an asset-light "
                                            "business, not a failure to invest. "
                                            "Penalising it inverts the logic."),
        },
        "missing": ("Client concentration, attrition and order pipeline are the real "
                    "risks in services businesses and none of them appear in the "
                    "financial statements."),
    },

    "cyclical": {
        "name": "Cyclical / commodity",
        "examples": "metals, cement, sugar, commodity chemicals, shipping, refining",
        "bias": {"quality": 0.90, "improvement": 1.15, "valuation": 1.30,
                 "momentum": 1.10, "participation": 1.05},
        "valuation": "cycle",
        "matters": ("Earnings here are a function of a commodity price the company does "
                    "not control. The single most useful question is not whether margins "
                    "are high but where they sit inside their own history — because the "
                    "cheapest-looking multiple in this category almost always appears at "
                    "the exact top of the cycle, and the most expensive at the bottom."),
        "suppress": {},
        "missing": ("Capacity utilisation, realisation per tonne and input cost hedging "
                    "decide the next two years and none are in the filings this reads."),
    },

    "capex": {
        "name": "Capex / execution",
        "examples": "capital goods, EPC, construction, defence, engineering",
        "bias": {"quality": 1.15, "improvement": 1.20, "valuation": 1.00,
                 "momentum": 0.95, "participation": 1.00},
        "valuation": "pe",
        "matters": ("An order book is not revenue and revenue is not cash. These "
                    "businesses fail on the working capital cycle far more often than on "
                    "demand — profit is booked on percentage completion while the money "
                    "sits in receivables. Cash conversion is weighted heavily here for "
                    "exactly that reason."),
        "suppress": {},
        "missing": ("Order book, order inflow and receivable days are the three numbers "
                    "that decide this category. None are published in a machine-readable "
                    "form here — read the investor presentation."),
    },

    "utility": {
        "name": "Regulated / utility",
        "examples": "power generation and transmission, gas distribution, road and port assets",
        "bias": {"quality": 1.10, "improvement": 0.90, "valuation": 1.15,
                 "momentum": 0.80, "participation": 0.85},
        "valuation": "pb",
        "matters": ("Returns are set by a regulator inside a band, so the upside is "
                    "capped by design and the questions become different ones: is the "
                    "debt serviceable, are receivables from state distribution companies "
                    "being collected, and is the dividend covered. High leverage here is "
                    "structural, not reckless."),
        "suppress": {
            "Debt / Equity": ("Regulated asset owners are financed with debt by design "
                              "and the regulator sets an allowed return on that "
                              "structure. The absolute ratio is not the risk; the "
                              "coverage of it is."),
        },
        "missing": "Regulatory orders, tariff revisions and receivable ageing from state discoms.",
    },

    "staple": {
        "name": "Consumer staple",
        "examples": "FMCG, packaged foods, household and personal care, paints",
        "bias": {"quality": 1.35, "improvement": 1.05, "valuation": 0.70,
                 "momentum": 0.90, "participation": 0.95},
        "valuation": "pe",
        "matters": ("The moat is distribution and brand, and it shows up as returns on "
                    "capital that stay high for decades with very little debt. These "
                    "companies are essentially never statistically cheap. Weighting "
                    "valuation normally would mark down the entire category permanently, "
                    "so it is weighted down here and the burden shifts onto whether "
                    "quality is holding."),
        "suppress": {
            _G + "Reinvestment intensity": ("Staples grow through distribution and "
                                            "advertising, which are expensed, not "
                                            "through capex."),
        },
        "missing": "Volume growth versus price-led growth — the distinction that matters most, and one the income statement hides.",
    },

    "realty": {
        "name": "Real estate developer",
        "examples": "residential and commercial developers, REIT sponsors",
        "bias": {"quality": 1.05, "improvement": 1.25, "valuation": 1.10,
                 "momentum": 1.00, "participation": 1.05},
        "valuation": "pb",
        "matters": ("Revenue recognition here is a timing choice, not an event — a "
                    "developer can report a weak year while selling more than ever, or a "
                    "strong year on projects sold three years ago. Pre-sales and "
                    "collections tell the truth; the profit and loss account lags them "
                    "by years. Debt at the wrong point in the cycle is what actually "
                    "kills developers."),
        "suppress": {
            _F + "Asset turnover rising": ("Inventory for a developer is land and "
                                           "work-in-progress held for years by design, "
                                           "so turnover ratios do not describe "
                                           "efficiency."),
        },
        "missing": "Pre-sales, collections, unsold inventory and land bank cost — the entire operating picture.",
    },

    "emerging": {
        "name": "Loss-making growth",
        "examples": "new-age platforms, recently listed technology businesses",
        "bias": {"quality": 0.65, "improvement": 1.55, "valuation": 0.55,
                 "momentum": 1.10, "participation": 1.20},
        "valuation": "none",
        "matters": ("With no profit there is no return on capital, no earnings multiple "
                    "and no F-Score worth reading — most of the standard toolkit returns "
                    "zero and a zero here means 'not applicable', not 'bad'. What can be "
                    "measured is the direction of travel: is the loss narrowing, is gross "
                    "margin improving, is cash being consumed more slowly."),
        "suppress": {
            "Valuation (P/E)": "No earnings, so no earnings multiple exists.",
            "ROCE": "Return on capital is undefined while the business loses money.",
            _F + "Positive ROA": ("Loss-making by design at this stage — scoring it as a "
                                  "failure says nothing the reader does not know."),
            _F + "ROA improving": "Reported through the improvement pillar instead.",
        },
        "missing": "Cash runway, unit economics and contribution margin — the only three things that matter here.",
    },

    "general": {
        "name": "General manufacturer",
        "examples": "auto ancillaries, textiles, packaging, diversified industrials",
        "bias": {"quality": 1.00, "improvement": 1.00, "valuation": 1.00,
                 "momentum": 1.00, "participation": 1.00},
        "valuation": "pe",
        "matters": ("The standard toolkit applies here as written: returns on capital, "
                    "leverage, margin direction and cash conversion, with an earnings "
                    "multiple that means what it appears to mean."),
        "suppress": {},
        "missing": "Segment-level detail, which is where diversified manufacturers hide both their best and worst businesses.",
    },
}


# ---------------------------------------------------------------------------
# 4 · Classification
#
# yfinance returns GICS-style sector and industry strings. They are patchy for
# Indian mid- and small-caps, so classification runs in three passes: explicit
# industry keywords, then sector fallback, then a financial-shape test that
# catches loss-making companies whatever their label says.
# ---------------------------------------------------------------------------

_INDUSTRY_RULES = [
    ("lender", ("bank", "credit services", "mortgage", "capital markets",
                "financial data", "financial conglomerate", "insurance",
                "asset management", "savings")),
    ("utility", ("utilit", "power", "electric", "gas distribution",
                 "renewable", "waste management")),
    ("realty", ("real estate", "reit")),
    ("cyclical", ("steel", "aluminum", "aluminium", "copper", "metal", "mining",
                  "coking coal", "cement", "building materials", "sugar",
                  "commodity chemicals", "agricultural inputs", "shipping",
                  "marine", "oil & gas refining", "paper", "lumber",
                  "coal", "gold", "silver")),
    ("capex", ("engineering & construction", "infrastructure operations",
               "aerospace & defense", "industrial machinery",
               "specialty industrial machinery", "electrical equipment",
               "conglomerates", "railroads", "farm & heavy construction")),
    ("staple", ("packaged foods", "household & personal", "beverages",
                "confectioners", "tobacco", "farm products",
                "specialty chemicals" , "food distribution")),
    ("compounder", ("software", "information technology", "it services",
                    "semiconductor", "internet content", "drug manufacturers",
                    "biotechnology", "healthcare plans", "medical",
                    "diagnostics", "education", "consulting", "advertising",
                    "telecom")),
]

_SECTOR_FALLBACK = {
    "Financial Services": "lender",
    "Technology": "compounder",
    "Healthcare": "compounder",
    "Communication Services": "compounder",
    "Consumer Defensive": "staple",
    "Basic Materials": "cyclical",
    "Energy": "cyclical",
    "Utilities": "utility",
    "Real Estate": "realty",
    "Industrials": "capex",
    "Consumer Cyclical": "general",
}


def classify(info: dict, fund: dict = None) -> dict:
    """
    Decide which business model this company belongs to.
    Returns {key, name, why, source} — `source` names the evidence used, so
    a misclassification is visible rather than silent.
    """
    industry = str((info or {}).get("industry") or "").lower()
    sector = str((info or {}).get("sector") or "").strip()

    key = None
    source = None

    for candidate, words in _INDUSTRY_RULES:
        if any(w in industry for w in words):
            key, source = candidate, f'industry "{(info or {}).get("industry")}"'
            break

    if key is None and sector in _SECTOR_FALLBACK:
        key, source = _SECTOR_FALLBACK[sector], f'sector "{sector}"'

    if key is None:
        key, source = "general", "no sector or industry published — general treatment applied"

    # A loss-making company is an emerging-growth object whatever its label,
    # because most of the profitability toolkit returns nothing for it. This
    # test runs last and overrides, but never for lenders or utilities, where
    # a single loss-making year is a cycle event rather than a business stage.
    if key not in ("lender", "utility"):
        margins = (info or {}).get("profitMargins")
        eps = (info or {}).get("trailingEps")
        loss = (margins is not None and margins < 0) or (eps is not None and eps < 0)
        if loss:
            key, source = "emerging", f"{source}, overridden — the company is currently loss-making"

    model = BUSINESS_MODELS[key]
    return {"key": key, "name": model["name"], "examples": model["examples"],
            "matters": model["matters"], "missing": model["missing"],
            "source": source}


# ---------------------------------------------------------------------------
# 5 · Cycle position
#
# Where does the current operating margin sit inside its own multi-year range?
# 1.0 means the best margin in the available history, 0.0 the worst. For a
# cyclical this is the difference between cheap and dangerous.
# ---------------------------------------------------------------------------

def cycle_position(fin) -> dict:
    """Returns {position, margins, years, note} or {position: None, ...}."""
    out = {"position": None, "margins": [], "years": 0, "note": ""}
    try:
        if fin is None or getattr(fin, "empty", True):
            out["note"] = "No multi-year income statement available."
            return out

        def row(names):
            for n in names:
                if n in fin.index:
                    return fin.loc[n]
            return None

        rev = row(["Total Revenue", "Operating Revenue"])
        op = row(["EBIT", "Operating Income"])
        if rev is None or op is None:
            out["note"] = "Operating income or revenue not reported in a comparable form."
            return out

        margins = []
        for col in fin.columns:
            try:
                r, o = float(rev[col]), float(op[col])
                if r and not math.isnan(r) and not math.isnan(o):
                    margins.append(round(100 * o / r, 2))
            except Exception:
                continue

        margins = [m for m in margins if abs(m) < 200]
        if len(margins) < 3:
            out["note"] = f"Only {len(margins)} comparable years — too few to place the cycle."
            out["margins"] = margins
            out["years"] = len(margins)
            return out

        cur = margins[0]                      # yfinance orders newest first
        lo, hi = min(margins), max(margins)
        pos = 0.5 if hi == lo else (cur - lo) / (hi - lo)
        out.update({
            "position": round(pos, 2), "margins": margins, "years": len(margins),
            "current": cur, "low": lo, "high": hi,
            "note": (f"Operating margin is {cur}%, against a {len(margins)}-year range "
                     f"of {lo}% to {hi}%."),
        })
        return out
    except Exception as e:
        out["note"] = f"Cycle position could not be computed ({str(e)[:60]})."
        return out



# ---------------------------------------------------------------------------
# 5b · Data coverage
#
# The engine renders a missing input as "0.0%" inside an explanatory sentence,
# so a check with no data behind it is indistinguishable from a check that
# genuinely failed — which is how the first version of this module reported
# 100% confidence for every company including ones with no statements at all.
# Coverage is therefore measured against the raw line items.
# ---------------------------------------------------------------------------

_REQUIRED = {
    "fin": ["Total Revenue|Operating Revenue", "Net Income|Net Income Common Stockholders",
            "EBIT|Operating Income", "Gross Profit"],
    "bs":  ["Total Assets", "Stockholders Equity|Total Stockholder Equity|Common Stock Equity",
            "Current Assets|Total Current Assets",
            "Current Liabilities|Total Current Liabilities",
            "Long Term Debt|Long Term Debt And Capital Lease Obligation",
            "Ordinary Shares Number|Share Issued"],
    "cf":  ["Operating Cash Flow|Total Cash From Operating Activities",
            "Capital Expenditure"],
}


def _has(frame, spec) -> bool:
    if frame is None or getattr(frame, "empty", True):
        return False
    for name in spec.split("|"):
        if name in frame.index:
            try:
                v = frame.loc[name].iloc[0]
                return v is not None and not (isinstance(v, float) and math.isnan(v))
            except Exception:
                continue
    return False


def data_coverage(fin, bs, cf, info: dict, suppress: dict) -> dict:
    """
    What fraction of the evidence this model intends to use was actually
    published. Suppressed checks are excluded — a lender is not marked down
    for a missing gross margin it was never going to be scored on.
    """
    skip_gross = any("Gross" in k for k in suppress)
    skip_capex = any("Reinvestment" in k for k in suppress)

    present, missing = [], []
    for frame, specs, obj in ((fin, _REQUIRED["fin"], "income statement"),
                              (bs, _REQUIRED["bs"], "balance sheet"),
                              (cf, _REQUIRED["cf"], "cash flow")):
        for spec in specs:
            label = spec.split("|")[0]
            if skip_gross and "Gross" in label:
                continue
            if skip_capex and "Capital Expenditure" in label:
                continue
            (present if _has(frame, spec) else missing).append(f"{label} ({obj})")

    for field, label in (("trailingPE", "price/earnings"),
                         ("priceToBook", "price/book"),
                         ("institutions_pct", "institutional holding"),
                         ("insiders_pct", "promoter holding")):
        if field == "trailingPE" and "Valuation (P/E)" in suppress:
            continue
        ((present if (info or {}).get(field) is not None else missing)
         .append(f"{label} (market data)"))

    total = len(present) + len(missing)
    pct = round(100 * len(present) / total) if total else 0
    return {"pct": pct, "present": len(present), "total": total, "missing": missing}


# ---------------------------------------------------------------------------
# 6 · Scoring
# ---------------------------------------------------------------------------

def _rebuild_pillars(tech: dict, fund: dict, suppress: dict) -> dict:
    """
    Recompute the five pillar scores with suppressed checks removed from the
    base entirely. This is the heart of the fix: a lender is no longer marked
    down for the checks that do not apply to lenders — those checks are not
    scored at all, and the score is out of what remains.
    """
    from archetypes import PILLAR_MAP

    by_name = {c["name"]: c for c in
               (tech.get("checks") or []) + (fund.get("checks") or [])}

    pillars, dropped = {}, []
    for pillar, names in PILLAR_MAP.items():
        earned = possible = 0
        for n in names:
            if n in suppress:
                if n in by_name:
                    dropped.append({"check": n, "reason": suppress[n]})
                continue
            c = by_name.get(n)
            if c:
                earned += c["points"]
                possible += c["max"]
        pillars[pillar] = round(100 * earned / possible) if possible else None

    # Valuation on a single P/E check is thin, so blend in how far the price
    # sits below its own 52-week high — the same adjustment archetypes.py
    # makes, kept here so both paths agree.
    #
    # But when no earnings multiple exists at all, what is left is only the
    # drawdown, and a drawdown is a position in a price range, not a
    # valuation. Saying otherwise let a stock with no published earnings be
    # scored as "expensive" purely for sitting near its high. The flag is
    # returned so score() can weight it as the weaker evidence it is.
    priced = pillars.get("valuation") is not None
    dd = (tech.get("extras") or {}).get("drawdown_from_high")
    if dd is not None:
        depth = min(100, max(0, -float(dd) * 2.2))
        base = pillars.get("valuation")
        pillars["valuation"] = (round(.55 * base + .45 * depth)
                                if base is not None else round(depth))
    return pillars, dropped, priced


def _apply_cycle(pillars: dict, model_key: str, cyc: dict) -> tuple:
    """
    Two corrections at the top of a commodity cycle, and the mirror image at
    the bottom. Both are things a first-year analyst is taught and most retail
    screeners get backwards.

    1  VALUATION. A steel company at 5x trailing earnings is not cheap; it is
       priced for the earnings to fall. At the peak the valuation reading is
       capped rather than rewarded.

    2  QUALITY. Return on capital and operating margin at the top of a cycle
       are cycle-peak numbers, not through-cycle numbers. Reading them as
       durable quality is how people buy commodity businesses at the worst
       possible moment. The quality reading is damped in proportion to how
       extended the cycle is.

    At the bottom both corrections reverse: trailing multiples look expensive
    because earnings are depressed, and quality looks poor for the same reason.
    """
    if model_key != "cyclical" or cyc.get("position") is None:
        return pillars, None

    pos = float(cyc["position"])
    out = dict(pillars)
    val, qua = out.get("valuation"), out.get("quality")
    pct = int(round(pos * 100))

    if pos >= 0.70:
        # How far into the top third of the range, 0 -> 1.
        extend = (pos - 0.70) / 0.30
        notes = []
        if val is not None:
            cap = round(100 - 60 * extend)          # pos 1.0 -> cap 40
            if val > cap:
                out["valuation"] = cap
                notes.append(f"the valuation reading is capped at {cap} (from {val})")
        if qua is not None:
            damp = round(30 * extend)               # pos 1.0 -> -30
            out["quality"] = max(0, qua - damp)
            if damp:
                notes.append(f"business quality is damped by {damp} points "
                             f"(from {qua} to {out['quality']})")
        note = (f"Operating margin sits at {pct}% of its own {cyc.get('years', '?')}-year "
                f"range — near the top of the cycle. These are peak-cycle earnings, so "
                + " and ".join(notes) + ". A low earnings multiple on peak earnings is "
                "the market pricing in the fall, not a discount."
                if notes else
                f"Margins sit at {pct}% of their own range — near the cycle top.")
        return out, note

    if pos <= 0.30:
        depress = (0.30 - pos) / 0.30
        notes = []
        if val is not None:
            floor = round(40 + 25 * depress)        # pos 0 -> floor 65
            if val < floor:
                out["valuation"] = floor
                notes.append(f"the valuation reading is floored at {floor} (from {val})")
        if qua is not None:
            lift = round(18 * depress)
            out["quality"] = min(100, qua + lift)
            if lift:
                notes.append(f"business quality is eased up by {lift} points "
                             f"(from {qua} to {out['quality']})")
        note = (f"Operating margin sits at {pct}% of its own {cyc.get('years', '?')}-year "
                f"range — near the bottom of the cycle, where trailing multiples look "
                f"expensive and returns look poor precisely because earnings are "
                f"depressed. To correct for that, " + " and ".join(notes) + "."
                if notes else
                f"Margins sit at {pct}% of their own range — near the cycle low.")
        return out, note

    return pillars, (f"Operating margin sits mid-range at {pct}% of its own history. "
                     f"No cycle adjustment applied.")


def weights_for(model_key: str, horizon: str) -> dict:
    """Horizon weights adjusted by business model, renormalised to sum to 1."""
    base = HORIZONS.get(horizon, HORIZONS[DEFAULT_HORIZON])["weights"]
    bias = BUSINESS_MODELS.get(model_key, BUSINESS_MODELS["general"])["bias"]
    raw = {p: base[p] * bias.get(p, 1.0) for p in PILLARS}
    total = sum(raw.values()) or 1.0
    return {p: round(raw[p] / total, 4) for p in PILLARS}


def score(tech: dict, fund: dict, info: dict, fin=None, bs=None, cf=None,
          horizon: str = DEFAULT_HORIZON) -> dict:
    """
    The headline number, and every input that produced it.

    Returns a dict the frontend can render as an audit trail:
      score, label, model, horizon, weights (with reasons), pillars,
      dropped checks, cycle note, confidence, and the contribution of each
      pillar in points so the arithmetic can be followed.
    """
    if horizon not in HORIZONS:
        horizon = DEFAULT_HORIZON

    model = classify(info, fund)
    spec = BUSINESS_MODELS[model["key"]]

    pillars, dropped, priced = _rebuild_pillars(tech, fund, spec["suppress"])
    cyc = cycle_position(fin) if spec["valuation"] == "cycle" else {"position": None}
    pillars, cycle_note = _apply_cycle(pillars, model["key"], cyc)

    w = weights_for(model["key"], horizon)

    # Missing pillars are redistributed across the ones that have data, so a
    # stock with no fundamentals is scored out of what exists rather than
    # being marked down for a gap in the data source.
    live = {p: v for p, v in pillars.items() if v is not None}
    if not live:
        return {"score": None, "label": "NO DATA", "model": model,
                "horizon": horizon, "confidence": 0,
                "basis": "Neither price nor statement data could be scored."}

    # A valuation pillar with no earnings multiple behind it carries half
    # weight, because all it really measures is distance from the 52-week high.
    w = dict(w)
    if not priced and "valuation" in live:
        w["valuation"] = w["valuation"] * 0.5

    live_w_total = sum(w[p] for p in live) or 1.0
    contrib, total = [], 0.0
    for p in PILLARS:
        if p not in live:
            continue
        eff = w[p] / live_w_total
        pts = live[p] * eff
        total += pts
        contrib.append({"pillar": p, "pillar_score": live[p],
                        "weight": round(eff, 4), "points": round(pts, 1)})
    contrib.sort(key=lambda c: -c["points"])
    final = int(round(max(0, min(100, total))))

    # Confidence: half from how many pillars had any data at all, half from how
    # many of the underlying line items the data source actually published.
    cov = data_coverage(fin, bs, cf, info, spec["suppress"])
    conf = round(100 * (0.4 * len(live) / len(PILLARS) + 0.6 * cov["pct"] / 100))

    if final >= 72:
        label, tone = "STRONG", "strong"
    elif final >= 55:
        label, tone = "CONSTRUCTIVE", "constructive"
    elif final >= 40:
        label, tone = "MIXED", "mixed"
    else:
        label, tone = "WEAK", "weak"

    lead = contrib[0] if contrib else None
    drag = contrib[-1] if len(contrib) > 1 else None

    basis = (f"Weighted for a {spec['name'].lower()} over "
             f"{HORIZONS[horizon]['label'].lower()}")

    summary_bits = []
    if lead:
        summary_bits.append(
            f"{_PILLAR_WORD[lead['pillar']]} contributes most of this score "
            f"({lead['pillar_score']}/100 at {int(lead['weight'] * 100)}% weight)")
    if drag and drag["pillar_score"] < 45:
        summary_bits.append(
            f"{_PILLAR_WORD[drag['pillar']].lower()} is the weakest link at "
            f"{drag['pillar_score']}/100")
    if conf < 60:
        summary_bits.append(
            f"confidence is only {conf}% because much of the statement data is missing")

    return {
        "score": final,
        "label": label,
        "tone": tone,
        "basis": basis,
        "summary": ". ".join(summary_bits) + "." if summary_bits else "",
        "model": model,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon]["label"],
        "horizon_note": HORIZONS[horizon]["note"],
        "weights": w,
        "pillars": pillars,
        "contribution": contrib,
        "dropped": dropped,
        "cycle": cyc if spec["valuation"] == "cycle" else None,
        "cycle_note": cycle_note,
        "valuation_basis": spec["valuation"] if priced else "drawdown_only",
        "valuation_note": (
            None if priced else
            "No usable earnings multiple was published for this company, so the "
            "valuation reading is based only on how far price sits below its "
            "52-week high — a position in a range, not a valuation. It has been "
            "given half its normal weight for that reason."),
        "confidence": conf,
        "coverage": cov,
        "confidence_note": (
            "Confidence measures how much of the intended evidence was actually "
            "available for this company — not how likely the score is to be right."),
    }


_PILLAR_WORD = {
    "momentum": "Price trend",
    "participation": "Volume and ownership",
    "quality": "Business quality",
    "improvement": "Direction of travel",
    "valuation": "What you pay",
}


def compare_horizons(tech, fund, info, fin=None, bs=None, cf=None) -> dict:
    """All three horizons at once — the switch the frontend offers."""
    return {h: score(tech, fund, info, fin, bs, cf, horizon=h) for h in HORIZONS}
