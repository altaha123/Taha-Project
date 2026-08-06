"""
Altaha Screener — Setup Archetypes

A single composite score flattens genuinely different situations. A stock at 82
because momentum is hot is not the same object as one at 82 because it's a
quality compounder in a drawdown. This module:

  1. Rolls the individual checks into five factor pillars (0-100 each)
  2. Classifies the stock into a setup archetype
  3. Re-scores it using that archetype's own weight vector
  4. States the thesis, the confirming evidence, and the observable conditions
     that would invalidate the setup

Invalidation is expressed as observable events, never price targets or
instructions. The tool describes evidence; the reader decides.
"""

# ---------------------------------------------------------------------------
# Pillars — built by grouping named checks from the engine
# ---------------------------------------------------------------------------

PILLAR_MAP = {
    "momentum": [
        "Trend structure", "Hull MA direction", "RSI(14) regime", "MACD momentum",
        "ADX trend strength", "Supertrend", "Bollinger position",
        "Volatility squeeze", "52-week range position",
    ],
    "participation": [
        "Volume trend", "Accumulation vs distribution", "On-Balance Volume",
        "Institutional holding (FII + DII)", "Promoter holding",
    ],
    "quality": [
        "F-Score · Positive ROA", "F-Score · Positive operating cash flow",
        "F-Score · CFO exceeds net income", "F-Score · No dilution",
        "ROCE", "Debt / Equity",
        "G-Score · Cash return on assets", "G-Score · Low accruals",
        "G-Score · Reinvestment intensity", "G-Score · Gross margin level",
        "G-Score · Earnings consistency",
    ],
    "improvement": [
        "F-Score · ROA improving", "F-Score · Leverage falling",
        "F-Score · Liquidity improving", "F-Score · Gross margin expanding",
        "F-Score · Asset turnover rising", "Revenue growth (YoY)",
        "G-Score · Sales growth quality",
    ],
    "valuation": ["Valuation (P/E)"],
}

PILLAR_LABEL = {
    "momentum": "Momentum",
    "participation": "Participation",
    "quality": "Quality",
    "improvement": "Improvement",
    "valuation": "Valuation",
}


def pillars(tech: dict, fund: dict) -> dict:
    """Roll checks into 0-100 pillar scores. None where no data supports a pillar."""
    by_name = {c["name"]: c for c in tech.get("checks", []) + fund.get("checks", [])}

    out = {}
    for pillar, names in PILLAR_MAP.items():
        earned = possible = 0
        for n in names:
            c = by_name.get(n)
            if c:
                earned += c["points"]
                possible += c["max"]
        out[pillar] = round(100 * earned / possible) if possible else None

    # Valuation on P/E alone is thin. "Quality at a discount" is really about
    # drawdown, so blend in how far the stock sits below its 52-week high.
    dd = tech.get("extras", {}).get("drawdown_from_high")
    if dd is not None:
        depth = min(100, max(0, -float(dd) * 2.2))       # -20% drawdown -> 44
        base = out.get("valuation")
        out["valuation"] = round(0.55 * base + 0.45 * depth) if base is not None else round(depth)

    return out


# ---------------------------------------------------------------------------
# Archetype definitions
# ---------------------------------------------------------------------------

ARCHETYPES = {
    "momentum_breakout": {
        "name": "Momentum Breakout",
        "weights": {"momentum": .48, "participation": .27, "quality": .15,
                    "improvement": .07, "valuation": .03},
        "horizon": "3–8 weeks",
        "thesis": ("Price is trending with force and volume is confirming it. The premise is "
                   "continuation: strong trends persist more often than they reverse, and the volume "
                   "behind this one suggests real participation rather than a thin drift."),
        "reads": ["Bollinger %B", "ADX", "Supertrend", "Hull MA slope", "volume expansion"],
        "invalidation": [
            "Daily close back below the Supertrend band — the trend regime has flipped",
            "ADX falling under 20, meaning the trend has lost force and price is going choppy",
            "Price returning inside the Bollinger mid-band on rising volume — the breakout failed",
            "Volume drying up while price holds — the move is running on fumes",
        ],
        "risks": ("Momentum setups fail fast and the failure is usually sharp. This archetype has the "
                  "shortest useful life of the four — the evidence justifying it can be gone in a week."),
    },
    "institutional_accumulation": {
        "name": "Institutional Accumulation",
        "weights": {"participation": .45, "momentum": .24, "quality": .21,
                    "improvement": .07, "valuation": .03},
        "horizon": "2–6 months",
        "thesis": ("Volume patterns and the shareholding register suggest larger holders are building "
                   "positions before price has fully moved. The premise is that institutional buying "
                   "leaves a footprint in volume before it shows up in headline returns."),
        "reads": ["accumulation vs distribution", "OBV", "volume trend", "FII/DII stake", "promoter stake"],
        "invalidation": [
            "Accumulation ratio turning below 1.0 — more volume now trading on down days than up days",
            "OBV rolling over while price holds up, the classic divergence that precedes a fall",
            "Institutional stake falling in the next quarterly filing",
            "Promoter stake declining across two consecutive quarters",
        ],
        "risks": ("Shareholding data is quarterly and lags by up to three months. Heavy volume can also "
                  "reflect index rebalancing or a single block deal rather than considered accumulation."),
    },
    "quality_at_discount": {
        "name": "Quality at Discount",
        "weights": {"quality": .42, "valuation": .28, "improvement": .12,
                    "momentum": .12, "participation": .06},
        "horizon": "6–18 months",
        "thesis": ("The business scores well on durable quality measures — returns on capital, cash "
                   "conversion, balance sheet strength — while price sits meaningfully below its recent "
                   "high. The premise is that quality reasserts itself and the discount closes over time."),
        "reads": ["ROCE", "Piotroski F-Score", "G-Score", "debt/equity", "drawdown from 52-week high"],
        "invalidation": [
            "ROCE or gross margin deteriorating in the next reported results — the quality premise itself breaks",
            "Debt rising materially against assets, changing the risk profile",
            "Operating cash flow falling below net income, signalling earnings quality decay",
            "Drawdown deepening on accelerating volume, suggesting the market knows something the filings don't yet show",
        ],
        "risks": ("The hardest archetype to hold, because it asks you to buy weakness. A cheap quality "
                  "business can stay cheap for years, and 'discount' and 'value trap' look identical at entry."),
    },
    "turnaround": {
        "name": "Turnaround",
        "weights": {"improvement": .44, "quality": .20, "momentum": .18,
                    "participation": .12, "valuation": .06},
        "horizon": "4–12 months",
        "thesis": ("The absolute numbers aren't impressive yet, but the direction of travel is — margins "
                   "expanding, leverage falling, returns improving off a low base. The premise is that "
                   "rate of change matters more than level when a business is inflecting."),
        "reads": ["ROA delta", "margin expansion", "debt reduction", "liquidity trend", "asset turnover"],
        "invalidation": [
            "Any improving metric reversing for a single reported period — the inflection was noise",
            "Debt resuming its rise after the reduction that formed the thesis",
            "Revenue stalling while margins expand, which usually means cost-cutting rather than genuine recovery",
            "Equity dilution to fund the recovery, which transfers upside away from existing holders",
        ],
        "risks": ("Turnarounds fail more often than they succeed, and improvement off a low base can be a "
                  "single good period rather than a trend. Two consecutive confirmations are worth far "
                  "more than one."),
    },
    "no_clear_setup": {
        "name": "No Clear Setup",
        "weights": {"momentum": .25, "quality": .25, "improvement": .20,
                    "participation": .20, "valuation": .10},
        "horizon": "—",
        "thesis": ("No single factor dominates strongly enough to define a coherent setup. The evidence "
                   "is mixed or middling across the board. That is a legitimate finding, not a failure of "
                   "the analysis — most stocks, most of the time, are not in a distinct setup."),
        "reads": ["all pillars, evenly weighted"],
        "invalidation": [
            "Any pillar moving decisively — re-running after the next results or a volume expansion may classify it clearly",
        ],
        "risks": ("Forcing a thesis onto an unclear picture is how conviction gets manufactured. The "
                  "honest reading is that this name isn't presenting an edge right now."),
    },
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _v(p, key, default=0):
    val = p.get(key)
    return default if val is None else val


def classify(p: dict, tech_extras: dict) -> tuple:
    """
    Assign an archetype. Returns (key, matched_conditions).
    Rules are checked in priority order; the first clean match wins.
    """
    mom = _v(p, "momentum")
    par = _v(p, "participation")
    qua = _v(p, "quality")
    imp = _v(p, "improvement")
    val = _v(p, "valuation")

    dd = tech_extras.get("drawdown_from_high")
    dd = float(dd) if dd is not None else 0.0
    adx = float(tech_extras.get("adx") or 0)
    st_bull = bool(tech_extras.get("supertrend_bull"))
    squeeze = bool(tech_extras.get("squeeze"))
    pct_b = tech_extras.get("pct_b")
    pct_b = float(pct_b) if pct_b is not None else 0.5

    # 1. Institutional accumulation takes priority when participation clearly
    #    LEADS momentum — that ordering is the accumulation signature: the
    #    volume footprint appears before the price move, not alongside it.
    if par >= 66 and (par - mom) >= 12 and qua >= 45:
        return "institutional_accumulation", [
            f"Participation pillar {par}/100 leading momentum at {mom}/100",
            "Volume footprint is running ahead of price — the accumulation signature",
            f"Quality pillar {qua}/100 supports the positioning being deliberate",
        ]

    # 2. Momentum breakout — trend force confirmed by participation
    if mom >= 68 and adx >= 22 and st_bull and par >= 45:
        why = [f"Momentum pillar {mom}/100 with ADX at {adx:.0f}",
               "Price trading above the Supertrend band",
               f"Participation pillar {par}/100 confirming the move"]
        if pct_b > 0.75:
            why.append(f"Bollinger %B at {pct_b:.2f} — riding the upper band")
        if squeeze:
            why.append("Bandwidth still compressed — expansion may have room to run")
        return "momentum_breakout", why

    # 3. Accumulation, softer case — strong participation, momentum not yet extended
    if par >= 66 and 40 <= mom < 78 and qua >= 45:
        return "institutional_accumulation", [
            f"Participation pillar {par}/100 — the strongest signal present",
            f"Momentum still moderate at {mom}/100, so the move may be early",
            f"Quality pillar {qua}/100 supports the positioning being deliberate",
        ]

    # 4. Quality at discount — good business, price below its high
    if qua >= 62 and val >= 52 and dd <= -8:
        why = [f"Quality pillar {qua}/100",
               f"Trading {abs(dd):.0f}% below the 52-week high",
               f"Valuation pillar {val}/100 reflecting that discount"]
        if imp >= 55:
            why.append(f"Fundamentals also improving ({imp}/100) — not merely cheap")
        return "quality_at_discount", why

    # 5. Turnaround — direction of travel beats the level
    if imp >= 62 and qua < 68:
        why = [f"Improvement pillar {imp}/100 — the deltas are the story",
               f"Quality still {qua}/100, so this is inflection rather than excellence"]
        if dd <= -15:
            why.append(f"Still {abs(dd):.0f}% below the 52-week high — recovery not yet priced")
        return "turnaround", why

    # 6. Dominant-pillar fallback — if something is genuinely strong, classify
    #    by what leads. "No clear setup" should mean nothing dominates, not
    #    that the stock narrowly missed a threshold. Each archetype still has
    #    to honour its own defining condition: "Quality at Discount" is not a
    #    valid label for a stock trading at its highs.
    ranked = sorted(
        [("momentum", mom), ("participation", par), ("quality", qua), ("improvement", imp)],
        key=lambda kv: kv[1], reverse=True,
    )
    preconditions = {
        "momentum": lambda: st_bull or mom >= 75,
        "participation": lambda: True,
        "quality": lambda: dd <= -8,          # a discount must actually exist
        "improvement": lambda: qua < 68,      # turnaround means improving off a low base
    }
    mapping = {
        "momentum": "momentum_breakout",
        "participation": "institutional_accumulation",
        "quality": "quality_at_discount",
        "improvement": "turnaround",
    }

    for i, (pk, pv) in enumerate(ranked):
        if pv >= 68 and preconditions[pk]():
            others = [v for k, v in ranked if k != pk]
            lead = "clearly leads" if (pv - max(others)) >= 10 else "narrowly leads"
            note = ("Classified on the dominant factor — not every textbook condition "
                    "for this setup is present")
            if i > 0:
                note = ("Classified on the strongest factor whose defining condition is "
                        "actually met — stronger pillars didn't qualify")
            return mapping[pk], [
                f"{PILLAR_LABEL[pk]} pillar at {pv}/100 {lead} the other factors",
                note,
                f"Momentum {mom} · Participation {par} · Quality {qua} · Improvement {imp} · Valuation {val}",
            ]

    return "no_clear_setup", [
        f"Momentum {mom} · Participation {par} · Quality {qua} · Improvement {imp} · Valuation {val}",
        "No pillar dominant enough to define a coherent setup",
    ]


def archetype_score(p: dict, key: str) -> int:
    """Re-score with the archetype's own weight vector, renormalised for missing pillars."""
    w = ARCHETYPES[key]["weights"]
    num = den = 0.0
    for pillar, weight in w.items():
        val = p.get(pillar)
        if val is not None:
            num += weight * val
            den += weight
    return round(num / den) if den else 0


def evaluate(tech: dict, fund: dict) -> dict:
    """Full archetype analysis for one stock."""
    p = pillars(tech, fund)
    key, why = classify(p, tech.get("extras", {}))
    a = ARCHETYPES[key]
    fit = archetype_score(p, key)

    if fit >= 75:
        strength = "Textbook example of this setup"
    elif fit >= 62:
        strength = "Solid example, with the gaps noted below"
    elif fit >= 48:
        strength = "Partial fit — the shape is there but the evidence is thin"
    else:
        strength = "Weak fit — classified by elimination rather than conviction"

    return {
        "key": key,
        "name": a["name"],
        "fit": fit,
        "strength": strength,
        "horizon": a["horizon"],
        "thesis": a["thesis"],
        "reads": a["reads"],
        "why": why,
        "invalidation": a["invalidation"],
        "risks": a["risks"],
        "pillars": [{"key": k, "label": PILLAR_LABEL[k], "value": p.get(k),
                     "weight": round(100 * a["weights"].get(k, 0))}
                    for k in ("momentum", "participation", "quality", "improvement", "valuation")],
    }
