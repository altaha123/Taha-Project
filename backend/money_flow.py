"""
money_flow.py — where institutional money is moving, sector by sector

WHAT THIS ANSWERS
Three questions a price chart cannot: which sectors foreign portfolio
investors are buying and selling, whether the sector's price is confirming it
against the Nifty 50, and which stocks inside a favoured sector are being
taken to delivery. One number per sector, the Sector Money Flow Score, ranks
the answer, and every part of it is printed beside it.

THE FOUR INPUTS (money_flow_sources.py reads them, money_flow_store.py keeps them)
  NSDL    equity net investment by FPIs per sector, per fortnight. The core.
  NSE     every sector index's daily close, for relative strength.
  NSE     the full bhavcopy's delivered share and volume, per stock. Already
          kept by special.py as 400-session panels; read from there.
  NSE     bulk and block deals, and the daily FII/DII provisional figures.

THE SCORE, 0 TO 100 (weights in money_flow_config.SCORE_WEIGHTS)
  FPI flow   40   three percentile ranks among the scored sectors, of flow as
                  a share of the sector's assets under custody: the last three
                  fortnights together, the latest fortnight, and the change
                  from the fortnight before.
  Rotation   35   the sector's quadrant on the rotation chart, and its return
                  against the Nifty 50 over three months and one.
  Breadth    25   the share of the sector's stocks above their 50-day average.
A part that cannot be measured is left out and the rest re-weighted, and the
card says so: a missing input is not counted as a bad one.

THE ROTATION CHART IS RRG-STYLE, NOT THE LICENSED FORMULA
Relative Rotation Graphs are Julius de Kempenaer's, and the exact
normalisation is proprietary. What is drawn here is the open reading of it, on
weekly closes:  RS = sector / Nifty 50;  RS-ratio = RS over its own 10-week
mean;  RS-momentum = RS-ratio over its own 4-week mean; both times 100, so 100
is "in line". Leading is both above 100, Weakening is ratio above and momentum
below, Lagging both below, Improving ratio below and momentum above.

WHAT IT IS NOT
A forecast. FPI data arrives a fortnight at a time and about a week after the
fortnight ends; it includes primary-market and block purchases, not only what
was bought on screen; and "a sector FPIs bought" has been a sector that went
on to fall often enough. Nothing here changes an Altaha Score. The score is
shown beside a stock as its sector's tailwind, and may narrow or widen how
many names the Ideas lists take from one sector only when
IDEAS_MONEYFLOW_CAPS is switched on.

JOBS ARE IDEMPOTENT AND SAY WHAT FAILED
run_daily and run_backfill do bounded slices and report what remains, the way
bhav_archive does. Each step is caught on its own, so NSE refusing the deals
file does not lose the day's index closes, and every run is a row in job_runs
with what each step did.
"""

import csv
import datetime as dt
import math
import os
import threading
import time

import money_flow_config as C
import money_flow_sources as src
import money_flow_store as store

_HERE = os.path.dirname(os.path.abspath(__file__))
SECTORS_FILE = os.path.join(_HERE, "nse_industries.csv")

DISCLAIMER = ("Published data, arranged. FPI figures are NSDL's, fortnightly and about a week "
              "late; FII/DII figures are NSE's provisional numbers. A sector money moved into "
              "is not a sector that will rise. Not investment advice.")

_job_lock = threading.Lock()
_cache = {"at": 0.0, "key": None, "payload": None}
_cards = {"at": 0.0, "date": None, "cards": {}}
_members = {"map": None}
CACHE_SECONDS = 60


# ---------------------------------------------------------------------------
# Small arithmetic
# ---------------------------------------------------------------------------

def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _round(v, nd=2):
    f = _finite(v)
    return None if f is None else round(f, nd)


def pct_ranks(values):
    """
    Each value's place among the others, 0 (lowest) to 1 (highest); ties share
    the average place. None stays None, and one value alone is 0.5: with
    nothing to compare it with it is neither high nor low.
    """
    got = [(i, _finite(v)) for i, v in enumerate(values)]
    live = sorted(((v, i) for i, v in got if v is not None))
    out = [None] * len(values)
    n = len(live)
    if n == 1:
        out[live[0][1]] = 0.5
        return out
    j = 0
    while j < n:
        k = j
        while k + 1 < n and live[k + 1][0] == live[j][0]:
            k += 1
        place = (j + k) / 2.0 / (n - 1)
        for m in range(j, k + 1):
            out[live[m][1]] = place
        j = k + 1
    return out


def _blend(parts, weights):
    """Weighted mean of the parts that exist; None when none do."""
    tot = sum(weights[k] for k, v in parts.items() if v is not None)
    if tot <= 0:
        return None
    return sum(weights[k] * v for k, v in parts.items() if v is not None) / tot


# ---------------------------------------------------------------------------
# Which sector a stock is in
# ---------------------------------------------------------------------------

def sector_members(force=False):
    """{SYMBOL: canonical sector} from the classification beside this file."""
    if _members["map"] is not None and not force:
        return _members["map"]
    out = {}
    try:
        with open(SECTORS_FILE, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                sym = (row.get("Symbol") or "").strip().upper()
                sec = C.canonical(row.get("Industry"))
                if sym and sec:
                    out[sym] = sec
    except Exception:
        out = {}
    _members["map"] = out
    return out


def sector_of(symbol):
    sym = str(symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    return sector_members().get(sym)


# ---------------------------------------------------------------------------
# FPI flow
# ---------------------------------------------------------------------------

def fpi_by_sector(rows):
    """
    Stored rows -> {sector: [fortnight, ...]} oldest first, each fortnight
    {"period_start", "period_end", "net_cr", "auc_cr", "pct"}.

    `pct` is the flow as a share of the sector's equity assets under custody
    when the fortnight opened (the previous fortnight's closing figure, or
    this one's closing figure less the flow where that is not held). It is
    what lets a Rs 500 crore fortnight in Media be read beside a Rs 5,000
    crore one in Financials.
    """
    out = {}
    for r in sorted(rows or [], key=lambda r: (r["sector"], r["period_end"])):
        out.setdefault(r["sector"], []).append(r)
    series = {}
    for sector, items in out.items():
        prev_auc, line = None, []
        for r in items:
            net, auc = _finite(r.get("equity_net_inr_cr")), _finite(r.get("equity_auc_inr_cr"))
            base = prev_auc
            if base is None and auc is not None and net is not None:
                base = auc - net
            pct = (net / base * 100.0) if (net is not None and base and base > 0) else None
            line.append({"period_start": r.get("period_start"), "period_end": r["period_end"],
                         "net_cr": net, "auc_cr": auc, "pct": pct})
            prev_auc = auc if auc is not None else prev_auc
        series[sector] = line
    return series


def fpi_trend(series):
    """
    One sector's fortnights (oldest first) -> what the card says about them.

    direction   inflow | outflow | flat      the latest fortnight
    trend       accelerating   same direction as the fortnight before, larger
                decelerating   same direction, smaller
                reversing      the direction changed
                steady         only one fortnight held, or the latest is flat
    flipped_to_inflow / flipped_to_outflow   the reversal, named
    streak      fortnights in a row in the latest direction
    """
    line = [f for f in series or [] if f.get("net_cr") is not None]
    if not line:
        return None
    last = line[-1]
    prev = line[-2] if len(line) > 1 else None

    def sign(v):
        return 0 if v is None or abs(v) < C.FLAT_CR else (1 if v > 0 else -1)

    s, sp = sign(last["net_cr"]), sign(prev["net_cr"]) if prev else 0
    direction = "inflow" if s > 0 else "outflow" if s < 0 else "flat"
    if not prev or s == 0:
        trend = "steady"
    elif sp != 0 and sp != s:
        trend = "reversing"
    elif sp == 0:
        trend = "accelerating"
    else:
        trend = "accelerating" if abs(last["net_cr"]) > abs(prev["net_cr"]) else "decelerating"
    streak = 0
    for f in reversed(line):
        if s != 0 and sign(f["net_cr"]) == s:
            streak += 1
        else:
            break

    def rolling(items):
        nets = [f["net_cr"] for f in items]
        pcts = [f["pct"] for f in items if f["pct"] is not None]
        return (sum(nets) if nets else None,
                sum(pcts) if len(pcts) == len(items) and pcts else None)

    n = C.FPI_ROLLING
    sum_cr, sum_pct = rolling(line[-n:])
    prev_sum_cr, _ = rolling(line[-n - 1:-1]) if len(line) > n else (None, None)
    change_pct = None
    if prev and last["pct"] is not None and prev["pct"] is not None:
        change_pct = last["pct"] - prev["pct"]
    return {
        "period_start": last["period_start"], "period_end": last["period_end"],
        "latest_cr": _round(last["net_cr"], 0), "latest_pct": _round(last["pct"], 3),
        "prev_cr": _round(prev["net_cr"], 0) if prev else None,
        "prev_pct": _round(prev["pct"], 3) if prev else None,
        "change_pct": _round(change_pct, 3),
        "sum3_cr": _round(sum_cr, 0), "sum3_pct": _round(sum_pct, 3),
        "prev_sum3_cr": _round(prev_sum_cr, 0),
        "fortnights_in_sum": min(n, len(line)),
        "auc_cr": _round(last["auc_cr"], 0),
        "direction": direction, "trend": trend, "streak": streak,
        "flipped_to_inflow": bool(prev and s > 0 and sp < 0),
        "flipped_to_outflow": bool(prev and s < 0 and sp > 0),
    }


# ---------------------------------------------------------------------------
# Price: relative strength and rotation
# ---------------------------------------------------------------------------

def _series(points):
    """[(iso_date, close)] -> a float Series on a DatetimeIndex, oldest first."""
    import pandas as pd
    if points is None:
        return None
    if hasattr(points, "dropna"):                # already a Series (a basket)
        s = points.dropna().astype("float64")
    else:
        if not points:
            return None
        s = pd.Series([float(v) for _d, v in points],
                      index=pd.to_datetime([d for d, _v in points]), dtype="float64")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) else None


def _ret(s, sessions, back=0):
    """Return over `sessions`, ending `back` sessions before the last."""
    end = len(s) - 1 - back
    start = end - sessions
    if start < 0 or end < 0:
        return None
    a, b = float(s.iloc[start]), float(s.iloc[end])
    return (b / a - 1.0) * 100.0 if a > 0 else None


def relative_strength(sector, bench):
    """
    A sector series against the benchmark, on the sessions both have:

      rs_1m, rs_3m   the sector's return less the benchmark's, in points
      momentum       this month's rs_1m less the previous month's: is the
                     relative return getting better or worse
    """
    import pandas as pd
    a, b = _series(sector), _series(bench)
    if a is None or b is None:
        return None
    df = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(df) < 2:
        return None
    s, m = df.iloc[:, 0], df.iloc[:, 1]

    def rel(n, back=0):
        x, y = _ret(s, n, back), _ret(m, n, back)
        return None if x is None or y is None else x - y

    r1, r3, r1_before = rel(C.RS_1M), rel(C.RS_3M), rel(C.RS_1M, back=C.RS_1M)
    return {
        "rs_1m": _round(r1), "rs_3m": _round(r3),
        "momentum": _round(r1 - r1_before) if r1 is not None and r1_before is not None else None,
        "ret_1m": _round(_ret(s, C.RS_1M)), "ret_3m": _round(_ret(s, C.RS_3M)),
        "bench_1m": _round(_ret(m, C.RS_1M)), "bench_3m": _round(_ret(m, C.RS_3M)),
        "sessions": int(len(df)), "as_of": df.index[-1].date().isoformat(),
    }


def quadrant(ratio, momentum):
    r, m = _finite(ratio), _finite(momentum)
    if r is None or m is None:
        return None
    if r >= 100:
        return "Leading" if m >= 100 else "Weakening"
    return "Improving" if m >= 100 else "Lagging"


def rrg_points(sector, bench, trail=None):
    """
    The rotation trail: one point per week, oldest first, at most `trail` of
    them, each {"week" (the week's last session), "ratio", "momentum"}.
    [] when there is not yet enough history for a single point.
    """
    import pandas as pd
    trail = trail or C.RRG_TRAIL_WEEKS
    a, b = _series(sector), _series(bench)
    if a is None or b is None:
        return []
    df = pd.concat([a, b], axis=1, join="inner").dropna()
    if df.empty:
        return []
    weekly = df.groupby(df.index.to_period("W-FRI")).tail(1)
    rs = 100.0 * weekly.iloc[:, 0] / weekly.iloc[:, 1]
    ratio = 100.0 * rs / rs.rolling(C.RRG_RATIO_WEEKS).mean()
    mom = 100.0 * ratio / ratio.rolling(C.RRG_MOMENTUM_WEEKS).mean()
    out = []
    for ts in mom.dropna().index[-trail:]:
        out.append({"week": ts.date().isoformat(), "ratio": round(float(ratio[ts]), 3),
                    "momentum": round(float(mom[ts]), 3)})
    return out


# ---------------------------------------------------------------------------
# The stocks: breadth, baskets and accumulation, from the delivery panels
# ---------------------------------------------------------------------------

def _panel():
    """special.py's wide panels (deliv, qty, vwap, close ...), or None."""
    try:
        import special
        return special._load_cache()
    except Exception:
        return None


def _tail(P, key, cols, n):
    f = P.get(key)
    if f is None:
        return None
    return f.tail(n).reindex(columns=cols).astype("float64")


def stock_table(P, members=None, deal_nets=None):
    """
    One row per classified stock in the panel, from its last 70 sessions:
    whether it is above its 50-day average, its delivery and volume against
    its own usual, and what large deals say. {SYMBOL: row}. {} without a panel.
    """
    import numpy as np
    members = members if members is not None else sector_members()
    if not P or P.get("close") is None or not len(P["close"]):
        return {}
    cols = [c for c in P["close"].columns if c in members]
    if not cols:
        return {}
    close, deliv = _tail(P, "close", cols, 70), _tail(P, "deliv", cols, 70)
    qty, vwap = _tail(P, "qty", cols, 70), _tail(P, "vwap", cols, 70)
    n = len(close)
    with np.errstate(all="ignore"):
        step = close.pct_change(fill_method=None)
        corp = ((step.tail(C.BREADTH_DMA) <= C.CA_DROP) | (step.tail(C.BREADTH_DMA) >= C.CA_JUMP)).any()
        last = close.iloc[-1]
        dma = close.tail(C.BREADTH_DMA).mean()
        dma_n = close.tail(C.BREADTH_DMA).count()
        base = slice(max(0, n - C.ACC_BASE - C.ACC_RECENT), max(0, n - C.ACC_RECENT))
        recent = slice(max(0, n - C.ACC_RECENT), n)
        before = slice(max(0, n - C.ACC_BASE - 1), max(0, n - 1))
        d_recent = deliv.iloc[recent].mean() if deliv is not None else None
        d_base = deliv.iloc[base].mean() if deliv is not None else None
        d_base_n = deliv.iloc[base].count() if deliv is not None else None
        d_today = deliv.iloc[-1] if deliv is not None else None
        d_avg20 = deliv.iloc[before].mean() if deliv is not None else None
        q_base = qty.iloc[base].mean() if qty is not None else None
        q_before = qty.iloc[before].mean() if qty is not None else None
        q_today = qty.iloc[-1] if qty is not None else None
        q_recent = qty.iloc[recent].mean() if qty is not None else None
        up_vol = None
        if qty is not None:
            up_vol = ((step.iloc[recent] > 0) & (qty.iloc[recent].gt(q_base, axis=1))).sum()
        turn = (qty * vwap / 1e7).tail(C.ACC_BASE + C.ACC_RECENT).median() \
            if qty is not None and vwap is not None else None
        chg5 = (close.iloc[-1] / close.iloc[-1 - C.ACC_RECENT] - 1.0) * 100.0 if n > C.ACC_RECENT else None

    def at(frame, sym):
        if frame is None:
            return None
        return _finite(frame.get(sym))

    out = {}
    for sym in cols:
        px = at(last, sym)
        is_corp = bool(corp.get(sym, False))
        above = None
        if px is not None and not is_corp and at(dma_n, sym) and dma_n[sym] >= C.BREADTH_MIN_OBS:
            above = px > float(dma[sym])
        row = {"symbol": sym, "sector": members[sym], "price": _round(px), "above_50dma": above,
               "corporate_action": is_corp,
               "deliv_pct": _round(at(d_today, sym), 1), "deliv_avg20": _round(at(d_avg20, sym), 1),
               "deliv_5d": _round(at(d_recent, sym), 1), "deliv_base": _round(at(d_base, sym), 1),
               "vol_ratio": None, "vol_ratio_5d": None,
               "up_vol_days": None if up_vol is None else int(up_vol.get(sym, 0)),
               "chg_1d": _round(None if at(step.iloc[-1], sym) is None else step.iloc[-1][sym] * 100.0),
               "chg_5d": _round(at(chg5, sym)), "turnover_cr": _round(at(turn, sym)),
               "deals": (deal_nets or {}).get(sym)}
        qb, qt, qr, qbase = at(q_before, sym), at(q_today, sym), at(q_recent, sym), at(q_base, sym)
        if qb and qt is not None:
            row["vol_ratio"] = _round(qt / qb)
        if qbase and qr is not None:
            row["vol_ratio_5d"] = _round(qr / qbase)
        db, dr = at(d_base, sym), at(d_recent, sym)
        row["deliv_ratio"] = _round(dr / db, 3) if (db and dr is not None and d_base_n is not None
                                                     and d_base_n[sym] >= 12) else None
        out[sym] = row
    return out


def accumulation_score(row):
    """
    (score 0..100, [reasons]) for one stock_table row, or (None, []) when it
    cannot be read: a split or bonus in the window, too little traded, or no
    delivery baseline.

      delivery       up to 45   its delivered share over the last 5 sessions
                                against the 20 before; 0.9x scores 0, 1.5x all 45
      price, volume  up to 40   8 for each of the last 5 sessions it closed up
                                on more volume than its usual day
      deals          +/- 15     net bought (or sold) in bulk and block deals
                                over 30 days, market makers and same-day round
                                trips taken out
    """
    if row.get("corporate_action") or row.get("deliv_ratio") is None:
        return None, []
    if (row.get("turnover_cr") or 0) < C.ACC_MIN_TURNOVER_CR:
        return None, []
    reasons = []
    span = C.ACC_DELIVERY_HIGH - C.ACC_DELIVERY_LOW
    d = max(0.0, min(1.0, (row["deliv_ratio"] - C.ACC_DELIVERY_LOW) / span)) * C.ACC_DELIVERY_PTS
    if row["deliv_ratio"] >= 1.1:
        reasons.append("Delivered share %.0f%% over five sessions against a usual %.0f%%."
                       % (row["deliv_5d"], row["deliv_base"]))
    days = row.get("up_vol_days") or 0
    pv = C.ACC_PRICE_VOLUME_PTS * days / float(C.ACC_RECENT)
    if days:
        reasons.append("Closed up on above-usual volume in %d of the last %d sessions."
                       % (days, C.ACC_RECENT))
    deal = 0.0
    deals = row.get("deals") or {}
    net = _finite(deals.get("net_cr"))
    if net is not None and abs(net) >= C.ACC_DEAL_MIN_CR:
        deal = C.ACC_DEAL_PTS if net > 0 else -C.ACC_DEAL_PTS
        who = (deals.get("top_buyers") if net > 0 else deals.get("top_sellers")) or []
        reasons.append("Rs %.1f cr net %s in bulk and block deals over %d days%s."
                       % (abs(net), "bought" if net > 0 else "sold", C.ACC_DEAL_DAYS,
                          (" (" + who[0]["client"].title() + ")") if who else ""))
    return round(max(0.0, min(100.0, d + pv + deal)), 1), reasons


def sector_breadth(table, sector):
    """Share of a sector's stocks above their 50-day average."""
    rows = [r for r in table.values() if r["sector"] == sector and r["above_50dma"] is not None]
    if len(rows) < C.MIN_MEMBERS:
        return None
    above = sum(1 for r in rows if r["above_50dma"])
    return {"pct": round(100.0 * above / len(rows), 1), "above": above, "of": len(rows)}


def basket_series(P, symbols):
    """
    A stand-in index for a sector NSE publishes none for (or none with enough
    history yet): its own stocks from the panel's closes, base 100.

    Weighted by rupees traded over the last 60 sessions, no stock above
    BASKET_MAX_WEIGHT. Not equal weight, on purpose: the benchmark is the
    Nifty 50, which is weighted by size, and an equal-weight basket of a
    sector's mid and small caps measured against it mostly reports whether
    small caps beat large caps that month, for every sector at once. Rupees
    traded is the nearest thing to size the daily file carries.

    A one-session move the size of a split or bonus is left out of that
    session. None when the panel is missing or fewer than MIN_MEMBERS of the
    stocks are in it.
    """
    import numpy as np
    if not P or P.get("close") is None:
        return None
    wanted = set(symbols)
    cols = [c for c in P["close"].columns if c in wanted]
    if len(cols) < C.MIN_MEMBERS:
        return None
    close = P["close"].reindex(columns=cols).astype("float64")
    weight = None
    if P.get("qty") is not None and P.get("vwap") is not None:
        turn = (P["qty"].reindex(columns=cols).astype("float64")
                * P["vwap"].reindex(columns=cols).astype("float64")).tail(60).median()
        if turn.notna().sum() >= C.MIN_MEMBERS and float(turn.sum()) > 0:
            weight = (turn.fillna(0.0) / float(turn.sum())).clip(upper=C.BASKET_MAX_WEIGHT)
    if weight is None:
        weight = close.iloc[-1].notna().astype("float64")
    with np.errstate(all="ignore"):
        step = close.pct_change(fill_method=None)
        step = step.where((step > C.CA_DROP) & (step < C.CA_JUMP))
        live = step.notna()
        w = live.mul(weight, axis=1)
        total = w.sum(axis=1)
        mean = (step.fillna(0.0) * w).sum(axis=1) / total
        mean = mean.where((live.sum(axis=1) >= C.MIN_MEMBERS) & (total > 0))
    mean = mean.iloc[1:].fillna(0.0)
    if not len(mean):
        return None
    return (1.0 + mean).cumprod() * 100.0


def deal_nets(since, symbols=None):
    """{SYMBOL: net reading} of stored bulk and block deals since a date,
    netted the way deals.py nets a day: prop desks out, round trips marked."""
    rows = store.deals_since(since, symbols)
    if not rows:
        return {}
    try:
        import deals as D
        shaped = [D._row(r["symbol"], r.get("name"), r["client"], r["side"], r["qty"],
                         r["price"], r["date"], r["kind"], r.get("remarks")) for r in rows]
        nets = D.net_by_symbol(shaped)
    except Exception:
        return {}
    out = {}
    for n in nets:
        out[n["symbol"]] = {"net_cr": n["net_cr"], "buy_cr": n["buy_cr"], "sell_cr": n["sell_cr"],
                            "prop_cr": n["prop_cr"], "deals": n["deals"], "block": n["block"],
                            "crossed": n["crossed"], "top_buyers": n["top_buyers"][:2],
                            "top_sellers": n["top_sellers"][:2], "reading": n["reading"],
                            "days": C.ACC_DEAL_DAYS}
    return out


# ---------------------------------------------------------------------------
# The whole market: FII and DII, daily
# ---------------------------------------------------------------------------

def market_flow(rows, sessions=None):
    """
    Stored daily rows (oldest first) -> the hero chart and its four figures.
    Each day carries the running total since the window opened; the summary
    carries the last 5 and 20 sessions added up. Sessions the server never saw
    are not invented: `sessions` says how many there are.
    """
    sessions = sessions or C.FLOW_SESSIONS
    rows = [r for r in rows or [] if r.get("fii_net") is not None or r.get("dii_net") is not None]
    if not rows:
        return {"available": False, "days": [], "sessions": 0,
                "message": "No session of FII/DII figures has been recorded yet. NSE publishes "
                           "the latest session only, so the record starts with the first "
                           "evening job and fills from there."}

    def total(key, n):
        got = [r[key] for r in rows[-n:] if r.get(key) is not None]
        return _round(sum(got), 0) if len(got) == min(n, len(rows)) and got else None

    days, fc, dc = [], 0.0, 0.0
    for r in rows[-sessions:]:
        fc += r.get("fii_net") or 0.0
        dc += r.get("dii_net") or 0.0
        days.append({"date": r["date"], "fii": _round(r.get("fii_net"), 0),
                     "dii": _round(r.get("dii_net"), 0),
                     "fii_cum": round(fc, 0), "dii_cum": round(dc, 0)})
    last = rows[-1]
    n = len(rows)
    return {
        "available": True, "days": days, "sessions": n,
        "latest": {"date": last["date"], "fii": _round(last.get("fii_net"), 0),
                   "dii": _round(last.get("dii_net"), 0),
                   "fii_buy": _round(last.get("fii_buy"), 0), "fii_sell": _round(last.get("fii_sell"), 0),
                   "dii_buy": _round(last.get("dii_buy"), 0), "dii_sell": _round(last.get("dii_sell"), 0)},
        "fii_5d": total("fii_net", 5), "fii_20d": total("fii_net", 20),
        "dii_5d": total("dii_net", 5), "dii_20d": total("dii_net", 20),
        "sessions_in_5d": min(5, n), "sessions_in_20d": min(20, n),
        "from": days[0]["date"], "to": days[-1]["date"],
        "provisional": True,
        "note": ("Cash market, Rs crore, NSE's provisional figures." +
                 ("" if n >= 20 else " %d session%s recorded so far: NSE publishes the latest "
                                     "session only, so this fills one evening at a time."
                                     % (n, "" if n == 1 else "s"))),
    }


# ---------------------------------------------------------------------------
# One computed session
# ---------------------------------------------------------------------------

def _index_frames(since):
    names = [C.BENCHMARK] + [s["index"] for s in C.SECTORS if s["index"]] + [t["index"] for t in C.THEMES]
    return store.index_series(sorted(set(names)), since=since)


def build_snapshot(today=None, panel="load"):
    """
    Everything the page shows, worked out from the store and the panels:
    (payload, sector cards, accumulation rows). Pure with respect to the
    store: it reads, and save_snapshot writes.
    """
    today = today or dt.date.today()
    P = _panel() if panel == "load" else panel
    members = sector_members()
    by_sector = {}
    for sym, sec in members.items():
        by_sector.setdefault(sec, []).append(sym)

    # --- FPI -----------------------------------------------------------------
    periods = store.fpi_periods(limit=max(C.DETAIL_FORTNIGHTS, C.HEATMAP_FORTNIGHTS) + C.FPI_ROLLING + 1)
    fpi_rows = store.fpi_rows(periods) if periods else []
    series = fpi_by_sector(fpi_rows)
    trends = {sec: fpi_trend(line) for sec, line in series.items()}
    heat_periods = sorted(periods[:C.HEATMAP_FORTNIGHTS])
    starts = {r["period_end"]: r.get("period_start") for r in fpi_rows}

    # --- price ---------------------------------------------------------------
    since = (today - dt.timedelta(days=400)).isoformat()
    frames = _index_frames(since)
    bench = _series(frames.get(C.BENCHMARK))
    panel_last = None
    if P and P.get("close") is not None and len(P["close"]):
        panel_last = P["close"].index.max().date()

    since_deals = ((panel_last or today) - dt.timedelta(days=C.ACC_DEAL_DAYS)).isoformat()
    nets = deal_nets(since_deals)
    table = stock_table(P, members, nets)

    def price_for(spec):
        """(series, source) for a sector: its index when that has enough
        history, else the basket of its own stocks."""
        idx = _series(frames.get(spec["index"])) if spec.get("index") else None
        if idx is not None and len(idx) >= C.MIN_INDEX_SESSIONS:
            return idx, "index"
        basket = basket_series(P, by_sector.get(spec["name"], []))
        if basket is not None and len(basket) >= C.RS_1M + 2:
            return basket, "basket"
        if idx is not None and len(idx) >= C.RS_1M + 2:
            return idx, "index"
        return None, None

    # --- one card per sector -------------------------------------------------
    cards = []
    for spec in C.SECTORS:
        name = spec["name"]
        price, source = price_for(spec)
        rs = relative_strength(price, bench) if price is not None and bench is not None else None
        points = rrg_points(price, bench) if price is not None and bench is not None else []
        quad = quadrant(points[-1]["ratio"], points[-1]["momentum"]) if points else None
        breadth = sector_breadth(table, name)
        n_members = len(by_sector.get(name, []))
        cards.append({
            "sector": name, "short": spec["short"], "slug": C.slug(name),
            "members": n_members,
            "fpi": trends.get(name),
            "fpi_spark": [_round(f["net_cr"], 0) for f in (series.get(name) or [])[-C.HEATMAP_FORTNIGHTS:]],
            "rs": rs, "rrg": points[-1] if points else None, "trail": points, "quadrant": quad,
            "breadth": breadth,
            "index": {"name": spec["index"], "fit": spec["fit"], "note": spec.get("note"),
                      "source": source,
                      "label": (_index_label(spec["index"]) if source == "index" else
                                ("Basket of %d %s stocks" % (len([s for s in by_sector.get(name, [])
                                                                   if s in table]), spec["short"])
                                 if source == "basket" else None))},
        })

    scoreable = [c for c in cards if c["members"] >= C.MIN_MEMBERS]
    r_sum = pct_ranks([(c["fpi"] or {}).get("sum3_pct") for c in scoreable])
    r_latest = pct_ranks([(c["fpi"] or {}).get("latest_pct") for c in scoreable])
    r_change = pct_ranks([(c["fpi"] or {}).get("change_pct") for c in scoreable])
    r_rs3 = pct_ranks([(c["rs"] or {}).get("rs_3m") for c in scoreable])
    r_rs1 = pct_ranks([(c["rs"] or {}).get("rs_1m") for c in scoreable])
    for i, c in enumerate(scoreable):
        fpi = _blend({"sum3": r_sum[i], "latest": r_latest[i], "change": r_change[i]}, C.FPI_BLEND)
        rs = _blend({"quadrant": C.QUADRANT_VALUE.get(c["quadrant"]),
                     "rs_3m": r_rs3[i], "rs_1m": r_rs1[i]}, C.RS_BLEND)
        br = None if not c["breadth"] else c["breadth"]["pct"] / 100.0
        parts = {"fpi": fpi, "rs": rs, "breadth": br}
        have = [k for k, v in parts.items() if v is not None]
        score = _blend(parts, C.SCORE_WEIGHTS)
        used = sum(C.SCORE_WEIGHTS[k] for k in have)
        c["components"] = {k: {"score": None if parts[k] is None else round(parts[k] * 100.0, 1),
                               "weight": C.SCORE_WEIGHTS[k],
                               "points": None if parts[k] is None or not used else
                               round(parts[k] * 100.0 * C.SCORE_WEIGHTS[k] / used, 1)}
                           for k in ("fpi", "rs", "breadth")}
        c["missing"] = [k for k in ("fpi", "rs", "breadth") if parts[k] is None]
        c["partial"] = bool(c["missing"])
        # Two of the three parts are needed: one alone is that measurement,
        # not a score.
        c["score"] = round(score * 100.0, 1) if score is not None and len(have) >= 2 else None

    scored = sorted([c for c in scoreable if c.get("score") is not None],
                    key=lambda c: (-c["score"], c["sector"]))
    for n, c in enumerate(scored, 1):
        c["rank"], c["of"] = n, len(scored)
    unscored = [c for c in cards if c.get("score") is None]
    for c in unscored:
        c["rank"] = c["of"] = None
        c.setdefault("components", None)
        c["unscored_reason"] = (
            "Fewer than %d companies in our universe, so breadth and a basket cannot be measured."
            % C.MIN_MEMBERS if c["members"] < C.MIN_MEMBERS else
            "Not enough of the three measurements are available yet.")

    # --- accumulation --------------------------------------------------------
    stocks = []
    names = _company_names()
    for c in cards:
        rows = []
        for r in table.values():
            if r["sector"] != c["sector"]:
                continue
            score, reasons = accumulation_score(r)
            if score is None:
                continue
            rows.append(dict(r, score=score, reasons=reasons, name=names.get(r["symbol"])))
        rows.sort(key=lambda r: (-r["score"], -(r.get("turnover_cr") or 0), r["symbol"]))
        top = rows[:C.ACC_TOP]
        for n, r in enumerate(top, 1):
            r["rank"] = n
        stocks += top
        c["top_stocks"] = [{"symbol": r["symbol"], "score": r["score"]} for r in top[:3]]
        c["accumulating"] = sum(1 for r in rows if r["score"] >= 60)

    # --- heatmap -------------------------------------------------------------
    heat_rows = []
    for c in sorted(cards, key=lambda c: (c.get("rank") is None, c.get("rank") or 0, c["sector"])):
        line = {f["period_end"]: f for f in series.get(c["sector"]) or []}
        if not line:
            continue
        heat_rows.append({
            "sector": c["sector"], "short": c["short"], "slug": c["slug"],
            "cells": [{"net_cr": _round((line.get(p) or {}).get("net_cr"), 0),
                       "pct": _round((line.get(p) or {}).get("pct"), 3)} for p in heat_periods],
            "sum3_cr": (c["fpi"] or {}).get("sum3_cr"), "trend": (c["fpi"] or {}).get("trend"),
            "direction": (c["fpi"] or {}).get("direction"),
            "flipped_to_inflow": (c["fpi"] or {}).get("flipped_to_inflow", False),
        })
    totals = []
    for p in heat_periods:
        got = [r["equity_net_inr_cr"] for r in fpi_rows
               if r["period_end"] == p and r["equity_net_inr_cr"] is not None]
        totals.append(_round(sum(got), 0) if got else None)

    # --- rotation ------------------------------------------------------------
    rrg_series = [{"key": c["slug"], "name": c["short"], "full": c["sector"], "kind": "sector",
                   "quadrant": c["quadrant"], "score": c.get("score"), "source": c["index"]["source"],
                   "points": c["trail"]} for c in cards if c["trail"]]
    themes = []
    for t in C.THEMES:
        s = _series(frames.get(t["index"]))
        if s is None or bench is None or len(s) < C.RS_1M + 2:
            continue
        pts = rrg_points(s, bench)
        themes.append({"key": "theme-" + C.slug(t["name"]), "name": t["name"], "kind": "theme",
                       "index": _index_label(t["index"]), "part_of": t["part_of"],
                       "quadrant": quadrant(pts[-1]["ratio"], pts[-1]["momentum"]) if pts else None,
                       "rs": relative_strength(s, bench), "points": pts})
    rrg_series += [dict(t, full=t["name"], score=None, source="index") for t in themes if t["points"]]

    index_last = bench.index[-1].date() if bench is not None else None
    as_of = max([d for d in (index_last, panel_last) if d] or [today])
    flows = market_flow(store.flows())
    latest = heat_periods[-1] if heat_periods else None
    gaps = _gaps(flows, bench, P, periods, table)

    for c in cards:
        c.pop("trail", None)
    payload = {
        "available": bool(periods or bench is not None),
        "as_of": as_of.isoformat(),
        "market": flows,
        "fpi": {"latest_period": {"start": starts.get(latest), "end": latest} if latest else None,
                "fortnights_held": len(store.fpi_periods()),
                "inflow_sectors": sum(1 for c in cards if (c["fpi"] or {}).get("direction") == "inflow"),
                "outflow_sectors": sum(1 for c in cards if (c["fpi"] or {}).get("direction") == "outflow"),
                "flipped_to_inflow": [c["short"] for c in cards
                                      if (c["fpi"] or {}).get("flipped_to_inflow")],
                "total_cr": totals[-1] if totals else None,
                "source": "NSDL, fortnightly sector-wise FPI investment (equity)"},
        "heatmap": {"periods": [{"end": p, "start": starts.get(p)} for p in heat_periods],
                    "rows": heat_rows, "totals": totals},
        "sectors": scored,
        "unscored": unscored,
        "rrg": {"benchmark": C.BENCHMARK_LABEL, "series": rrg_series,
                "weeks": sorted({p["week"] for s in rrg_series for p in s["points"]})[-C.RRG_TRAIL_WEEKS:],
                "ratio_weeks": C.RRG_RATIO_WEEKS, "momentum_weeks": C.RRG_MOMENTUM_WEEKS},
        "themes": themes,
        "weights": C.SCORE_WEIGHTS,
        "method": METHOD,
        "mapping": C.mapping_table(),
        "gaps": gaps,
        "disclaimer": DISCLAIMER,
    }
    return payload, cards, stocks


METHOD = {
    "score": ("Sector Money Flow Score, 0 to 100: FPI flow, rotation against the Nifty 50, and "
              "breadth. A part that cannot be measured is left out and the rest re-weighted."),
    "fpi": ("FPI equity net investment per fortnight, as a share of the sector's assets under "
            "custody. Ranked among the scored sectors on the last three fortnights together, "
            "the latest, and the change from the one before."),
    "rs": ("The sector index's return less the Nifty 50's over 21 and 63 sessions, and its "
           "quadrant on the rotation chart."),
    "rrg": ("Weekly closes. RS-ratio is the sector over the Nifty 50, against its own 10-week "
            "mean; RS-momentum is that ratio against its own 4-week mean. 100 is in line. An "
            "RRG-style chart, not the licensed formula."),
    "breadth": "The share of the sector's stocks above their own 50-day average.",
    "accumulation": ("Per stock: delivered share over 5 sessions against the 20 before (up to "
                     "45), sessions closed up on above-usual volume (up to 40), and net buying "
                     "in bulk and block deals over 30 days (plus or minus 15)."),
}


def _index_label(name):
    if not name:
        return None
    small = {"IT", "FMCG", "PSE", "PSU", "MNC", "CPSE"}
    return " ".join(w if w in small or not w.isalpha() else w.capitalize() for w in name.split())


_names = {"map": None}


def _company_names():
    if _names["map"] is None:
        out = {}
        try:
            with open(SECTORS_FILE, encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    sym = (row.get("Symbol") or "").strip().upper()
                    if sym:
                        out[sym] = (row.get("Company Name") or "").strip() or None
        except Exception:
            out = {}
        _names["map"] = out
    return _names["map"]


def _gaps(flows, bench, P, periods, table):
    """What is missing, in sentences the page prints as they are."""
    out = []
    if not periods:
        out.append("No NSDL fortnight is stored yet, so FPI flow is not in any score. "
                   "Run the backfill.")
    elif len(periods) < C.FPI_ROLLING + 1:
        out.append("Only %d NSDL fortnight%s stored, so flow trends are provisional."
                   % (len(periods), "" if len(periods) == 1 else "s"))
    if bench is None:
        out.append("No Nifty 50 history is stored yet, so relative strength and the rotation "
                   "chart are empty. Run the backfill.")
    if not table:
        out.append("The delivery record is not loaded on this instance, so breadth and "
                   "stock-level accumulation are not shown. It fills itself from NSE's "
                   "daily file.")
    if flows.get("available") and flows.get("sessions", 0) < 20:
        out.append("FII/DII: %d session%s recorded. NSE publishes the latest session only, "
                   "so the 20-session total needs 20 evenings of record."
                   % (flows["sessions"], "" if flows["sessions"] == 1 else "s"))
    return out


def recompute(today=None, panel="load"):
    """Work the session out and store it. Returns a short summary."""
    payload, cards, stocks = build_snapshot(today=today, panel=panel)
    if not payload["available"]:
        return {"ok": False, "stored": False, "reason": "nothing to compute from yet"}
    payload["built_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    store.save_snapshot(payload["as_of"], payload, cards, stocks)
    _cache.update(at=0.0, payload=None)
    _cards.update(at=0.0)
    return {"ok": True, "stored": True, "as_of": payload["as_of"],
            "sectors_scored": len(payload["sectors"]), "stocks": len(stocks)}


# ---------------------------------------------------------------------------
# What the endpoints read
# ---------------------------------------------------------------------------

def overview():
    """The page. A read of the latest stored session; if none is stored but
    there is data to work from, it is worked out once here."""
    now = time.time()
    if _cache["payload"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["payload"]
    snap = store.latest_snapshot()
    if snap is None:
        try:
            recompute()
        except Exception:
            pass
        snap = store.latest_snapshot()
    if snap is None:
        return {"available": False, "coverage": store.coverage(),
                "message": "Money Flow has no data yet. The evening job fills it; the first "
                           "run needs the backfill (POST /admin/moneyflow/run?job=backfill).",
                "disclaimer": DISCLAIMER}
    payload = dict(snap["payload"])
    payload.setdefault("built_utc", snap["built_utc"])
    _cache.update(at=now, payload=payload)
    return payload


def sector_detail(slug_or_name):
    """One sector: its card, two years of fortnights, and its accumulation rows."""
    spec = C.by_slug(slug_or_name)
    if not spec:
        return None
    name = spec["name"]
    date, cards = store.sector_cards()
    card = cards.get(name)
    periods = store.fpi_periods(limit=C.DETAIL_FORTNIGHTS + 1)
    line = fpi_by_sector([r for r in store.fpi_rows(periods) if r["sector"] == name]).get(name, [])
    _d, rows = store.accumulation(name, date)
    return {
        "available": card is not None, "as_of": date, "sector": name, "short": spec["short"],
        "slug": C.slug(name), "card": card,
        "fortnights": [{"start": f["period_start"], "end": f["period_end"],
                        "net_cr": _round(f["net_cr"], 0), "pct": _round(f["pct"], 3),
                        "auc_cr": _round(f["auc_cr"], 0)} for f in line[-C.DETAIL_FORTNIGHTS:]],
        "stocks": rows,
        "history": store.score_history(name, limit=60),
        "method": METHOD["accumulation"],
        "index": {"name": _index_label(spec["index"]), "fit": spec["fit"], "note": spec.get("note")},
        "disclaimer": DISCLAIMER,
    }


def _latest_cards():
    now = time.time()
    if now - _cards["at"] > 300:
        try:
            date, cards = store.sector_cards()
        except Exception:
            date, cards = None, {}
        _cards.update(at=now, date=date, cards=cards)
    return _cards["date"], _cards["cards"]


def tailwind(symbol):
    """
    A stock's sector, as Money Flow reads it today: the context printed beside
    an Altaha Score. It is never part of one. None when the stock is not in
    the classification or its sector has no score.
    """
    sec = sector_of(symbol)
    if not sec:
        return None
    date, cards = _latest_cards()
    c = cards.get(sec)
    if not c or c.get("score") is None:
        return None
    f, rs = c.get("fpi") or {}, c.get("rs") or {}
    tier = _tier(c)
    return {
        "sector": sec, "short": c.get("short"), "slug": c.get("slug"), "as_of": date,
        "score": c["score"], "rank": c.get("rank"), "of": c.get("of"), "tier": tier,
        "quadrant": c.get("quadrant"),
        "fpi_direction": f.get("direction"), "fpi_trend": f.get("trend"),
        "fpi_latest_cr": f.get("latest_cr"), "fpi_sum3_cr": f.get("sum3_cr"),
        "fpi_period_end": f.get("period_end"), "flipped_to_inflow": f.get("flipped_to_inflow"),
        "rs_1m": rs.get("rs_1m"), "rs_3m": rs.get("rs_3m"),
        "breadth_pct": (c.get("breadth") or {}).get("pct"),
        "partial": c.get("partial"),
        "line": _tailwind_line(c, tier),
        "note": "Context beside the score. It does not change the Altaha Score.",
    }


def _tier(card):
    """Which quarter of the ranked sectors a card is in: top | middle | bottom."""
    rank, of = card.get("rank"), card.get("of")
    if not rank or not of:
        return None
    q = max(1, of // 4)
    return "top" if rank <= q else "bottom" if rank > of - q else "middle"


def _tailwind_line(c, tier):
    f = c.get("fpi") or {}
    word = {"top": "a tailwind", "middle": "neutral", "bottom": "a headwind"}.get(tier, "unrated")
    bits = ["%s ranks %s of %s on money flow (%s)" % (c.get("short"), c.get("rank"), c.get("of"), word)]
    if f.get("latest_cr") is not None:
        bits.append("FPIs net %s Rs %s cr in the latest fortnight"
                    % ("bought" if f["latest_cr"] >= 0 else "sold", "{:,.0f}".format(abs(f["latest_cr"]))))
    if c.get("quadrant"):
        bits.append("%s against the Nifty 50" % c["quadrant"].lower())
    return "; ".join(bits) + "."


def sector_cap(symbol, default):
    """
    How many names an Ideas list may take from this stock's sector. `default`
    unless IDEAS_MONEYFLOW_CAPS is on, and then CAP_TOP for a sector in the
    top quarter on money flow, CAP_BOTTOM for the bottom quarter.
    """
    if not C.CAPS_ON:
        return default
    sec = sector_of(symbol)
    _date, cards = _latest_cards()
    tier = _tier(cards.get(sec) or {}) if sec else None
    if tier == "top":
        return max(default, C.CAP_TOP)
    if tier == "bottom":
        return max(1, min(default, C.CAP_BOTTOM))
    return default


def caps_note():
    """What the Ideas payload says about the caps, so a reader can see them."""
    return {"on": C.CAPS_ON, "top": C.CAP_TOP, "bottom": C.CAP_BOTTOM,
            "rule": ("A sector in the top quarter on money flow may give %d names to a list, one "
                     "in the bottom quarter %d. Off unless IDEAS_MONEYFLOW_CAPS=on."
                     % (C.CAP_TOP, C.CAP_BOTTOM))}


def status():
    out = {"coverage": store.coverage(), "runs": store.job_runs(limit=8),
           "alerts": store.alerts(limit=8),
           "weights": C.SCORE_WEIGHTS, "caps": caps_note(),
           "telegram": {"on": C.ALERTS_ON, "require_flip": C.ALERT_REQUIRE_FLIP},
           "running": _job_lock.locked()}
    last = {}
    for r in out["runs"]:
        last.setdefault(r["job"], r)
    out["last"] = {k: {"finished_utc": v["finished_utc"], "ok": v["ok"]} for k, v in last.items()}
    return out


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def find_alerts(now_cards, before_cards):
    """
    Sectors that have just moved into Improving or Leading while FPIs are net
    buyers in the latest fortnight. [{key, sector, text}], one per sector per
    fortnight (the key carries both).
    """
    out = []
    for name, c in (now_cards or {}).items():
        quad = c.get("quadrant")
        was = (before_cards or {}).get(name, {}).get("quadrant")
        f = c.get("fpi") or {}
        if quad not in ("Improving", "Leading") or not was or was == quad:
            continue
        if was == "Leading":                      # Leading -> Improving is not good news
            continue
        if (f.get("latest_cr") or 0) <= 0:
            continue
        if C.ALERT_REQUIRE_FLIP and not f.get("flipped_to_inflow"):
            continue
        period = "%s to %s" % (f.get("period_start") or "?", f.get("period_end") or "?")
        flow = ("FPIs turned net buyers" if f.get("flipped_to_inflow") else "FPIs were net buyers")
        text = ("Money Flow: %s moved to %s (was %s). %s in %s: Rs %s cr%s. "
                "Score %s of 100, rank %s of %s."
                % (c.get("short") or name, quad, was, flow, period,
                   "{:+,.0f}".format(f["latest_cr"]),
                   (" after Rs %s cr" % "{:+,.0f}".format(f["prev_cr"])) if f.get("prev_cr") is not None else "",
                   "-" if c.get("score") is None else "{:.0f}".format(c["score"]),
                   c.get("rank") or "-", c.get("of") or "-"))
        out.append({"key": "%s|%s" % (name, f.get("period_end")), "sector": name, "text": text})
    return out


def send_alerts(as_of, send=None):
    """Announce what find_alerts found, once each. Returns what happened."""
    _date, now_cards = store.sector_cards(date=as_of)
    _before, before_cards = store.sector_cards(before=as_of)
    found = find_alerts(now_cards, before_cards)
    if not found:
        return {"found": 0, "sent": 0}
    if send is None:
        try:
            import alerts as notify
            send = notify.send_plain if (C.ALERTS_ON and notify.TG_TOKEN and notify.TG_CHAT) else None
        except Exception:
            send = None
    sent = 0
    for a in found:
        if not store.alert_claim(a["key"], a["text"]):
            continue
        ok = False
        if send is not None:
            try:
                ok = bool(send(a["text"]))
            except Exception:
                ok = False
        store.alert_delivered(a["key"], ok)
        sent += 1 if ok else 0
    return {"found": len(found), "sent": sent,
            "telegram": send is not None, "sectors": [a["sector"] for a in found]}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _canonical_rows(rows, url):
    """Parsed NSDL rows -> rows the store takes, plus names nobody recognised."""
    out, unknown = [], set()
    for r in rows:
        name = C.canonical(r["sector"])
        if not name:
            unknown.add(r["sector"])
            continue
        out.append(dict(r, sector=name, source_url=url))
    return out, sorted(unknown)


def step_nsdl(limit=4, since=None, fetch_index=None, fetch_report=None):
    """Read report pages NSDL lists that the store has not read. Newest first."""
    fetch_index = fetch_index or src.fetch_nsdl_index
    fetch_report = fetch_report or src.fetch_nsdl_report
    listed = fetch_index()
    done = store.reports_done()
    want = [r for r in listed if done.get(r["url"]) != "ok"
            and (since is None or r["report_date"] >= since)]
    read, errors, warnings, written, revised = 0, [], [], 0, 0
    for r in want[:max(0, int(limit))]:
        try:
            got = fetch_report(r["url"])
            rows, unknown = _canonical_rows(got["rows"], r["url"])
            res = store.upsert_fpi(rows, source_url=r["url"])
            written += res["written"]
            revised += res["revised"]
            note = "; ".join(got["warnings"] + (["unknown sectors: " + ", ".join(unknown)] if unknown else []))
            store.mark_report(r["url"], r["report_date"], "ok", note, len(rows))
            if note:
                warnings.append("%s: %s" % (r["report_date"], note))
            read += 1
        except Exception as e:
            store.mark_report(r["url"], r["report_date"], "error", "%s: %s" % (type(e).__name__, e))
            errors.append("%s: %s: %s" % (r["report_date"], type(e).__name__, str(e)[:160]))
    return {"ok": not errors, "listed": len(listed), "read": read, "rows": written,
            "revised": revised, "remaining": max(0, len(want) - read - len(errors)),
            "errors": errors, "warnings": warnings,
            "latest_listed": listed[0]["report_date"] if listed else None}


def _index_todo(start, end, today):
    """Calendar days between two dates not yet settled, newest first. A day
    too young to have a file is asked for but never written off."""
    settled = store.index_days()
    out, day = [], end
    while day >= start:
        if day.isoformat() not in settled:
            out.append(day)
        day -= dt.timedelta(days=1)
    return out


def step_indices(start, end, limit=15, budget_s=120, today=None, fetch=None):
    """Store index closes for the missing days in a window, newest first."""
    today = today or dt.date.today()
    fetch = fetch or src.fetch_index_day
    todo = _index_todo(start, min(end, today), today)
    t0, got, absent, blocked, run = time.time(), 0, 0, 0, 0
    done = 0
    for day in todo[:max(0, int(limit))]:
        if time.time() - t0 > budget_s or run >= 5:
            break
        state, closes = fetch(day)
        if state == src.OK and closes:
            store.upsert_index_day(day, closes)
            got += 1
            run = 0
            done += 1
        elif state == src.ABSENT:
            # Today's and yesterday's file may simply not be out: not written
            # off, so the next run asks again.
            if (today - day).days > C.SETTLE_DAYS:
                store.mark_index_absent(day)
                done += 1
            absent += 1
            run = 0
        else:
            blocked += 1
            run += 1
    young = sum(1 for d in todo if (today - d).days <= C.SETTLE_DAYS)
    return {"ok": blocked == 0, "stored": got, "absent": absent, "blocked": blocked,
            "remaining": max(0, len(todo) - done - young),
            "errors": ["NSE's archive refused %d index file%s" % (blocked, "" if blocked == 1 else "s")]
            if blocked else []}


def step_flows(fetch=None):
    """Today's FII/DII figures, plus whatever market_week.py already recorded."""
    try:
        import market_week
    except Exception:
        market_week = None
    wrote, errors = 0, []
    if market_week is not None:
        try:
            wrote += store.upsert_flows(market_week._load())
        except Exception as e:
            errors.append("existing record: %s" % type(e).__name__)
    try:
        if fetch is None:
            import nse_http
            body = nse_http.get_json(market_week.FLOWS_URL, referer=market_week.FLOWS_REFERER)
            parsed = market_week.parse_flows(body)
        else:
            parsed = fetch()
        if parsed:
            day, flows = parsed
            wrote += store.upsert_flows({day: flows})
        else:
            errors.append("NSE's FII/DII figures did not answer")
    except Exception as e:
        errors.append("FII/DII: %s: %s" % (type(e).__name__, str(e)[:120]))
    cov = store.coverage()["flow_sessions"]
    return {"ok": not errors, "written": wrote, "sessions": cov["count"], "latest": cov["to"],
            "errors": errors}


def step_deals(fetch=None):
    """The latest session's bulk and block deals: the archive's CSVs, and the
    live snapshot deals.py reads when that answers."""
    rows, errors = (fetch or src.fetch_deals_latest)()
    if fetch is None:
        try:
            import deals as D
            snap = D.today(force=True)
            for r in (snap or {}).get("rows") or []:
                if r.get("kind") in ("bulk", "block"):
                    row = src.deal_row(r.get("date"), r.get("symbol"), r.get("name"), r.get("client"),
                                       r.get("side"), r.get("qty"), r.get("price"), r["kind"],
                                       r.get("remarks"))
                    if row:
                        rows.append(row)
        except Exception:
            pass
    new = store.upsert_deals(rows)
    return {"ok": bool(rows) or not errors, "read": len(rows), "new": new, "errors": errors}


def step_deals_history(start, end, limit=3, fetch=None):
    """Past deals in 30-day windows, newest first. Stops at the first window
    NSE refuses and says so: that window is asked for again next time."""
    fetch = fetch or src.fetch_deals_history
    done = store.deals_windows()
    windows, hi = [], end
    while hi > start:
        lo = max(start, hi - dt.timedelta(days=29))
        windows.append((lo, hi))
        hi = lo - dt.timedelta(days=1)
    todo = [(k, lo, hi) for lo, hi in windows for k in ("bulk", "block")
            if (k, lo.isoformat()) not in done]
    read, new, refused = 0, 0, False
    for kind, lo, hi in todo[:max(0, int(limit))]:
        try:
            rows = fetch(kind, lo, hi)
        except Exception:
            rows = None
        if rows is None:
            refused = True
            break
        new += store.upsert_deals(rows)
        store.mark_deals_window(kind, lo.isoformat(), hi.isoformat(), len(rows))
        read += 1
    # A refusal is reported, not failed on: NSE refuses this API from most
    # datacenter addresses, and a job that can never pass teaches nobody
    # anything. Nothing is left "remaining" either, or the caller would loop.
    return {"ok": True, "windows_read": read, "new": new,
            "remaining": 0 if refused else max(0, len(todo) - read), "refused": refused,
            "notes": ["NSE's deals history refused this address; the daily file fills the "
                      "record from here on"] if refused else []}


def step_delivery():
    """Ask special.py to pick up the newest session. It works in the
    background; this only reports where the panels stand."""
    try:
        import special
        special.ensure_building()
        st = special.status()
        return {"ok": True, "sessions": st.get("cached_sessions"), "to": st.get("to"),
                "building": st.get("building")}
    except Exception as e:
        return {"ok": False, "errors": ["delivery panels: %s" % type(e).__name__]}


def _run(job, steps):
    """Run named steps, each caught on its own; log the run; return its summary."""
    if not _job_lock.acquire(blocking=False):
        return {"ok": False, "busy": True, "job": job,
                "message": "A Money Flow job is already running."}
    run_id = None
    try:
        run_id = store.job_start(job)
        out, errors, remaining = {}, [], 0
        for name, fn in steps:
            t0 = time.time()
            try:
                res = fn() or {}
            except Exception as e:
                res = {"ok": False, "errors": ["%s: %s" % (type(e).__name__, str(e)[:200])]}
            res["seconds"] = round(time.time() - t0, 1)
            out[name] = res
            errors += ["%s: %s" % (name, e) for e in res.get("errors") or []]
            remaining += int(res.get("remaining") or 0)
        ok = all(r.get("ok", True) for r in out.values())
        summary = {"ok": ok, "job": job, "steps": out, "errors": errors, "remaining": remaining}
        store.job_finish(run_id, ok, summary)
        for e in errors:
            print("[money-flow] %s: %s" % (job, e), flush=True)
        return summary
    except Exception as e:
        if run_id is not None:
            try:
                store.job_finish(run_id, False, {"ok": False, "errors": [str(e)[:300]]})
            except Exception:
                pass
        print("[money-flow] %s failed: %s: %s" % (job, type(e).__name__, e), flush=True)
        return {"ok": False, "job": job, "errors": ["%s: %s" % (type(e).__name__, str(e)[:300])],
                "remaining": 0}
    finally:
        _job_lock.release()


def _compute_and_alert(today):
    res = recompute(today=today)
    if res.get("stored"):
        try:
            res["alerts"] = send_alerts(res["as_of"])
        except Exception as e:
            res["alerts"] = {"error": type(e).__name__}
    res.setdefault("ok", True)
    if not res.get("stored"):
        res["ok"] = True                         # nothing to compute is not a failure
    return res


def run_daily(today=None):
    """
    The evening job: the last ten days of index closes, today's FII/DII and
    deals, any NSDL report not yet read, then the scores. Safe to run again
    the same evening, and the morning after for a file that landed late.
    """
    today = today or dt.date.today()
    start = today - dt.timedelta(days=10)
    return _run("daily", [
        ("indices", lambda: step_indices(start, today, limit=15, today=today)),
        ("flows", step_flows),
        ("deals", step_deals),
        ("nsdl", lambda: step_nsdl(limit=3, since=(today - dt.timedelta(days=120)).isoformat())),
        ("delivery", step_delivery),
        ("compute", lambda: _compute_and_alert(today)),
    ])


def run_backfill(months=None, limit=40, budget_s=200, today=None):
    """
    One bounded slice of history: index closes and NSDL reports for the last
    `months`, and what deal history NSE will give. Call it until `remaining`
    is 0; the scores are worked out at the end of every slice.
    """
    today = today or dt.date.today()
    months = int(months or C.BACKFILL_MONTHS)
    start = today - dt.timedelta(days=int(months * 30.5) + 20)
    limit = max(1, min(int(limit), 400))
    return _run("backfill", [
        ("nsdl", lambda: step_nsdl(limit=max(2, limit // 4), since=start.isoformat())),
        ("indices", lambda: step_indices(start, today, limit=limit, budget_s=budget_s, today=today)),
        ("flows", step_flows),
        ("deals_history", lambda: step_deals_history(start, today, limit=4)),
        ("compute", lambda: _compute_and_alert(today)),
    ])


def run_recompute(today=None):
    return _run("recompute", [("compute", lambda: _compute_and_alert(today or dt.date.today()))])
