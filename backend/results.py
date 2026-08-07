"""
Altaha Screener — Quarterly Results

Builds a results card from the latest reported quarterly statements.
Indian fiscal labelling: Apr–Jun = Q1 of FY(year+1), Jul–Sep = Q2,
Oct–Dec = Q3, Jan–Mar = Q4 of FY(year).

Data honesty: our source publishes quarterly statements with a lag of days
after the exchange filing, and older comparison quarters are sometimes
missing. Anything not computable is reported as unavailable, never derived
from the wrong base.
"""

import math
import pandas as pd


def _fq_label(ts) -> str:
    m, y = ts.month, ts.year
    if 4 <= m <= 6:
        return f"Q1 FY{(y + 1) % 100:02d}"
    if 7 <= m <= 9:
        return f"Q2 FY{(y + 1) % 100:02d}"
    if 10 <= m <= 12:
        return f"Q3 FY{(y + 1) % 100:02d}"
    return f"Q4 FY{y % 100:02d}"


def _row(frame: pd.DataFrame, keys):
    if frame is None or frame.empty:
        return None
    for k in keys:
        if k in frame.index:
            return frame.loc[k]
    return None


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _cr(v):
    return round(v / 1e7, 2) if v is not None else None


def _pct(new, old):
    if new is None or old is None or old == 0:
        return None
    # A sign flip makes a plain percentage meaningless; report separately.
    if old < 0:
        return None
    return round(100 * (new - old) / abs(old), 1)


def quarterly_results(qfin: pd.DataFrame, name: str, sym: str) -> dict:
    """Build the results payload from a quarterly income statement frame."""
    rev = _row(qfin, ["Total Revenue", "Operating Revenue"])
    pat = _row(qfin, ["Net Income", "Net Income Common Stockholders"])
    if rev is None and pat is None:
        return {"available": False,
                "message": "Quarterly statements for this stock aren't published by our data source."}

    # Columns newest-first, keep only dated ones
    cols = [c for c in qfin.columns if isinstance(c, pd.Timestamp)]
    cols.sort(reverse=True)
    if not cols:
        return {"available": False, "message": "No dated quarterly columns available."}

    latest = cols[0]
    label = _fq_label(latest)

    def series(row):
        out = []
        if row is None:
            return out
        for c in cols[:5]:
            v = _num(row.get(c))
            out.append({"period": _fq_label(c), "date": str(c.date()), "value_cr": _cr(v)})
        return out

    rev_s, pat_s = series(rev), series(pat)

    def latest_v(s):
        return s[0]["value_cr"] if s and s[0]["value_cr"] is not None else None

    def find_yoy(s):
        """Same fiscal quarter, previous year — matched by label, not position."""
        if not s:
            return None
        want_q = s[0]["period"].split()[0]
        want_fy = int(s[0]["period"].split("FY")[1])
        for item in s[1:]:
            q = item["period"].split()[0]
            fy = int(item["period"].split("FY")[1])
            if q == want_q and fy == want_fy - 1:
                return item["value_cr"]
        return None

    rev_now, rev_yoy_base = latest_v(rev_s), find_yoy(rev_s)
    pat_now, pat_yoy_base = latest_v(pat_s), find_yoy(pat_s)
    rev_prev_q = rev_s[1]["value_cr"] if len(rev_s) > 1 else None
    pat_prev_q = pat_s[1]["value_cr"] if len(pat_s) > 1 else None

    margin_now = round(100 * pat_now / rev_now, 1) if pat_now is not None and rev_now else None
    margin_yoy = (round(100 * pat_yoy_base / rev_yoy_base, 1)
                  if pat_yoy_base is not None and rev_yoy_base else None)

    # Computed-facts bullets — only what the numbers themselves say
    bullets = []
    if pat_now is not None and pat_yoy_base is not None:
        g = _pct(pat_now, pat_yoy_base)
        if g is not None:
            direction = "rose" if g >= 0 else "fell"
            bullets.append(f"Net profit {direction} from ₹{pat_yoy_base:,.2f} Cr to ₹{pat_now:,.2f} Cr YoY ({g:+.1f}%)")
        elif pat_yoy_base < 0 <= pat_now:
            bullets.append(f"Swung to a net profit of ₹{pat_now:,.2f} Cr from a loss of ₹{abs(pat_yoy_base):,.2f} Cr a year earlier")
        elif pat_now < 0 <= pat_yoy_base:
            bullets.append(f"Swung to a net loss of ₹{abs(pat_now):,.2f} Cr from a profit of ₹{pat_yoy_base:,.2f} Cr a year earlier")
    if rev_now is not None and rev_yoy_base is not None:
        g = _pct(rev_now, rev_yoy_base)
        if g is not None:
            bullets.append(f"Revenue {'grew' if g >= 0 else 'declined'} {g:+.1f}% YoY to ₹{rev_now:,.2f} Cr")
    if margin_now is not None and margin_yoy is not None:
        d = round(margin_now - margin_yoy, 1)
        bullets.append(f"Net margin {'expanded' if d >= 0 else 'compressed'} to {margin_now}% from {margin_yoy}% a year earlier")
    if pat_now is not None and pat_prev_q is not None and pat_yoy_base is None:
        bullets.append(f"Sequential comparison only: PAT ₹{pat_prev_q:,.2f} Cr → ₹{pat_now:,.2f} Cr QoQ (year-ago quarter not published)")

    return {
        "available": True,
        "symbol": sym, "name": name,
        "quarter": label,
        "as_of": str(latest.date()),
        "basis": "Consolidated/standalone as published by the source",
        "pat_cr": pat_now, "pat_yoy_pct": _pct(pat_now, pat_yoy_base),
        "pat_yoy_base_cr": pat_yoy_base, "pat_qoq_base_cr": pat_prev_q,
        "revenue_cr": rev_now, "revenue_yoy_pct": _pct(rev_now, rev_yoy_base),
        "revenue_yoy_base_cr": rev_yoy_base,
        "net_margin_pct": margin_now, "net_margin_yoy_pct": margin_yoy,
        "revenue_series": rev_s, "pat_series": pat_s,
        "bullets": bullets,
        "note": ("Figures from the latest quarterly statements our data source has "
                 "published, which can lag the exchange filing by several days. "
                 "Segment-level detail isn't available from this source. For the "
                 "authoritative version, see the company's filing on NSE/BSE."),
    }
