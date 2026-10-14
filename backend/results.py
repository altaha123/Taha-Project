"""
Altaha Screener — Quarterly Results

Builds a results card from the latest reported quarterly statements.
Indian fiscal labelling: Apr–Jun = Q1 of FY(year+1), Jul–Sep = Q2,
Oct–Dec = Q3, Jan–Mar = Q4 of FY(year).

Two sources, one card:

  filed_results()      the company's own Regulation 33 filing on NSE, read
                       when the card is asked for. A result filed this
                       afternoon is on the card this afternoon.
  quarterly_results()  Yahoo's quarterly statements, for anything the
                       exchange read cannot answer (a US ticker, a BSE-only
                       listing, NSE refusing the call). Yahoo publishes days
                       after the exchange filing, which is why it is the
                       fallback and not the source: TARIL filed its September
                       2026 quarter on 13 October and the card still showed
                       June the next day.

Data honesty: older comparison quarters are sometimes missing. Anything not
computable is reported as unavailable, never derived from the wrong base.
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
    out = _card(rev_s, pat_s, name=name, sym=sym, quarter=label,
                as_of=str(latest.date()))
    out.update({
        "source": "Yahoo Finance quarterly statements",
        "basis": "Consolidated/standalone as published by the source",
        "note": ("Figures from the latest quarterly statements our data source has "
                 "published, which can lag the exchange filing by several days. "
                 "Segment-level detail isn't available from this source. For the "
                 "authoritative version, see the company's filing on NSE/BSE."),
    })
    return out


def filed_results(filed: dict, sym: str = None) -> dict:
    """
    The results card from the company's own exchange filing.

    `filed` is what fundamentals.series() returns: rows newest first, one
    accounting basis, money in rupees. The card is built by the same code as
    the Yahoo one, so the two can never disagree on a percentage or a bullet.
    """
    rows = [r for r in (filed or {}).get("rows") or [] if r.get("period_end")]
    if not filed or not filed.get("available") or not rows:
        return {"available": False,
                "message": (filed or {}).get("message")
                or "No quarterly results filing could be read for this stock."}

    def series(key):
        out = []
        for r in rows[:5]:
            v = _num((r.get("values") or {}).get(key))
            out.append({"period": r.get("label"), "date": r["period_end"],
                        "value_cr": _cr(v)})
        return out

    top = rows[0]
    basis = filed.get("basis") or "reported"
    out = _card(series("revenue"), series("pat"),
                name=filed.get("company") or sym or filed.get("symbol"),
                sym=sym or filed.get("symbol"),
                quarter=top.get("label"), as_of=top["period_end"])
    out.update({
        "source": "NSE corporate filing (XBRL, LODR Reg 33)",
        "basis": basis,
        "pat_label": "%s profit after tax (as filed)" % basis.capitalize(),
        "filed_at": top.get("filed_at"),
        "audited": top.get("audited"),
        "source_url": top.get("source"),
        "note": ("Figures as the company filed them with NSE under Regulation "
                 "33, on a %s basis, read from the exchange when you asked. "
                 "Profit is the profit for the period, before any split between "
                 "the parent's owners and minority shareholders." % basis),
    })
    # The index lists a quarter newer than any document that could be read:
    # NSE throttled the fetch. Saying so beats passing the older quarter off
    # as the latest, which is the exact failure this source replaced.
    newer = filed.get("filed_latest")
    if newer and newer > top["period_end"]:
        out["newer_filing"] = newer
        out["note"] = ("The exchange lists results for the quarter ended %s, but "
                       "that filing could not be read just now, so this card shows "
                       "the quarter before it. Try again in a minute. "
                       % newer) + out["note"]
    return out


def _period_parts(label):
    """
    Split a period label like 'Q2 FY26' into ('Q2', 26).

    BUGFIX: this used to be inline as int(label.split("FY")[1]), which
    threw IndexError on any label without 'FY' and ValueError on anything
    non-numeric after it ('FY26-27', 'FY 26', 'Q1 CY2026'). One oddly
    formatted filing took the whole results endpoint down. Now an
    unparseable label just returns None and that row is skipped.
    """
    try:
        if not label or "FY" not in label:
            return None, None
        quarter = label.split()[0]
        tail = label.split("FY")[1].strip()
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None, None
        return quarter, int(digits)
    except Exception:
        return None, None


def _find_yoy(s):
    """Same fiscal quarter, previous year — matched by label, not position."""
    if not s:
        return None
    want_q, want_fy = _period_parts(s[0].get("period"))
    if want_q is None or want_fy is None:
        return None
    for item in s[1:]:
        q, fy = _period_parts(item.get("period"))
        if q is None or fy is None:
            continue
        if q == want_q and fy == want_fy - 1:
            return item["value_cr"]
    return None


def _card(rev_s, pat_s, name, sym, quarter, as_of) -> dict:
    """The card, from revenue and profit series in crore, newest first."""
    def latest_v(s):
        return s[0]["value_cr"] if s and s[0]["value_cr"] is not None else None

    rev_now, rev_yoy_base = latest_v(rev_s), _find_yoy(rev_s)
    pat_now, pat_yoy_base = latest_v(pat_s), _find_yoy(pat_s)
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
        "quarter": quarter,
        "as_of": as_of,
        "pat_cr": pat_now, "pat_yoy_pct": _pct(pat_now, pat_yoy_base),
        "pat_yoy_base_cr": pat_yoy_base, "pat_qoq_base_cr": pat_prev_q,
        "revenue_cr": rev_now, "revenue_yoy_pct": _pct(rev_now, rev_yoy_base),
        "revenue_yoy_base_cr": rev_yoy_base,
        "net_margin_pct": margin_now, "net_margin_yoy_pct": margin_yoy,
        "revenue_series": rev_s, "pat_series": pat_s,
        "bullets": bullets,
    }
