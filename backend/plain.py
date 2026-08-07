"""
Altaha Screener — Plain Language Layer

The engine produces 25+ audited checks. That depth is the product's value and
also what overwhelms a beginner. This module condenses the same evidence into:

  1. A one-sentence verdict with no jargon
  2. The three strongest and three weakest findings, translated

Nothing here computes anything new. It only rephrases what the checks already
established, so the plain summary and the full ledger can never disagree.
"""

# Plain-language rewrites, keyed by check name.
# (positive phrasing, negative phrasing)
PHRASING = {
    "Trend structure": ("The share price is in a clear uptrend",
                        "The share price is drifting down or sideways"),
    "Hull MA direction": ("Short-term direction is upward",
                          "Short-term direction has turned down"),
    "RSI(14) regime": ("Buying pressure is healthy without being overheated",
                       "Momentum is either weak or the stock looks overheated"),
    "MACD momentum": ("Upward momentum is building, not fading",
                      "Momentum is fading"),
    "ADX trend strength": ("The trend has real force behind it",
                           "There's no strong trend — price is choppy and directionless"),
    "Supertrend": ("Price is on the bullish side of its trend band",
                   "Price is on the bearish side of its trend band"),
    "Bollinger position": ("Price is trading in the strong half of its range",
                           "Price is trading in the weak half of its range"),
    "Volatility squeeze": ("Volatility has compressed — often a build-up before a big move",
                           "Volatility is unremarkable right now"),
    "52-week range position": ("Trading near its one-year high, which tends to continue",
                               "Trading near its one-year low, fighting overhead selling"),
    "Volume trend": ("More people are trading it lately — interest is rising",
                     "Trading interest is thinning out"),
    "Accumulation vs distribution": ("More shares change hands on up days than down days — buyers are in control",
                                     "More shares change hands on down days — sellers are in control"),
    "On-Balance Volume": ("Buying volume is genuinely supporting the price",
                          "Volume is not supporting the price move"),
    "Institutional holding (FII + DII)": ("Large professional investors hold a meaningful stake",
                                          "Professional investors hold very little of it"),
    "Promoter holding": ("The founding family has a large stake — their money is on the line too",
                         "The founding family holds a small stake"),
    "ROCE": ("The business earns strong profits on the money invested in it",
             "The business earns poor profits on the money invested in it"),
    "Debt / Equity": ("Very little debt — it can survive a bad year",
                      "Carries heavy debt, which is risky if business slows"),
    "Revenue growth (YoY)": ("Sales are growing well",
                             "Sales are flat or shrinking"),
    "Valuation (P/E)": ("The price looks reasonable for what you get",
                        "The price is expensive relative to earnings"),
    "F-Score · Positive ROA": ("It is profitable", "It is not profitable"),
    "F-Score · Positive operating cash flow": ("The business generates real cash",
                                               "The business is not generating cash"),
    "F-Score · ROA improving": ("Profitability is improving year on year",
                                "Profitability is slipping"),
    "F-Score · CFO exceeds net income": ("Profits are backed by actual cash, not accounting adjustments",
                                         "Reported profit is not fully backed by cash"),
    "F-Score · Leverage falling": ("Debt is coming down", "Debt is rising"),
    "F-Score · Liquidity improving": ("Better able to pay short-term bills than last year",
                                      "Less able to pay short-term bills than last year"),
    "F-Score · No dilution": ("No new shares issued — your stake isn't being watered down",
                              "New shares issued, diluting existing shareholders"),
    "F-Score · Gross margin expanding": ("Making more profit on each rupee of sales",
                                         "Making less profit on each rupee of sales"),
    "F-Score · Asset turnover rising": ("Using its assets more efficiently",
                                        "Using its assets less efficiently"),
    "G-Score · Cash return on assets": ("Generates strong cash from its asset base",
                                        "Generates weak cash from its asset base"),
    "G-Score · Low accruals": ("Earnings quality is high", "Earnings quality is questionable"),
    "G-Score · Reinvestment intensity": ("Investing in future growth",
                                         "Investing little in future capacity"),
    "G-Score · Gross margin level": ("Healthy profit margins suggest pricing power",
                                     "Thin margins suggest little pricing power"),
    "G-Score · Earnings consistency": ("Consistently profitable, not erratic",
                                       "Earnings have been erratic"),
    "G-Score · Sales growth quality": ("Growing at a steady, repeatable pace",
                                       "Growth is either absent or unsustainably fast"),
}


def _phrase(check):
    pair = PHRASING.get(check["name"])
    if not pair:
        return None
    strong = check["points"] >= check["max"] * 0.6
    return pair[0] if strong else pair[1]


def highlights(tech: dict, fund: dict, n: int = 3) -> dict:
    """Return the n strongest and n weakest findings in plain language."""
    checks = list(tech.get("checks", [])) + list(fund.get("checks", []))
    scored = []
    for c in checks:
        if not c.get("max"):
            continue
        ratio = c["points"] / c["max"]
        text = _phrase(c)
        if text:
            scored.append({"name": c["name"], "ratio": ratio, "text": text,
                           "points": c["points"], "max": c["max"]})

    strong = [s for s in scored if s["ratio"] >= 0.6]
    weak = [s for s in scored if s["ratio"] <= 0.34]
    strong.sort(key=lambda s: (-s["ratio"], -s["max"]))
    weak.sort(key=lambda s: (s["ratio"], -s["max"]))

    seen = set()
    def dedupe(items):
        out = []
        for i in items:
            if i["text"] in seen:
                continue
            seen.add(i["text"])
            out.append({"name": i["name"], "text": i["text"]})
            if len(out) == n:
                break
        return out

    return {"good": dedupe(strong), "bad": dedupe(weak)}


def plain_verdict(tech: dict, fund: dict, verdict: dict, setup: dict | None) -> str:
    """One sentence, no jargon, describing what the evidence says overall."""
    t = tech.get("score")
    f = fund.get("score")

    if f is None:
        base = ("We could only check the price behaviour for this one — its financial "
                "statements aren't published by our data source.")
        if t >= 65:
            return base + " On price alone, it's behaving strongly."
        if t >= 45:
            return base + " On price alone, it's behaving unremarkably."
        return base + " On price alone, it's behaving weakly."

    strong_biz = f >= 62
    strong_px = t >= 62
    weak_biz = f < 45
    weak_px = t < 45

    if strong_biz and strong_px:
        core = ("This is a good business and the share price is behaving well too — "
                "the two agree, which is the most comfortable situation to find.")
    elif strong_biz and weak_px:
        core = ("The underlying business looks solid, but the share price is weak right now. "
                "Either the market knows something the numbers don't yet show, or it's simply "
                "out of favour.")
    elif weak_biz and strong_px:
        core = ("The share price is running, but the underlying business doesn't yet justify it. "
                "Moves like this depend on sentiment continuing rather than on the numbers.")
    elif weak_biz and weak_px:
        core = ("Both the business numbers and the share price are weak. There's little here "
                "supporting a case at the moment.")
    else:
        core = ("A mixed picture — parts of the business and the price action look fine, "
                "parts don't, and nothing dominates strongly enough to be clear-cut.")

    if setup and setup.get("key") and setup["key"] != "no_clear_setup":
        hold = setup.get("horizon")
        core += (f" The pattern here resembles a {setup['name'].lower()}"
                 + (f", which typically plays out over {hold}." if hold and hold != "—" else "."))

    return core
