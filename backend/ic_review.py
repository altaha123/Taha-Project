"""
Altaha Screener — Investment Committee Review

WHAT THIS ADDS TO THE EXISTING REPORT
`portfolio.py` measures the book against the rules the user set, and
`portfolio_intelligence.py` attaches coverage, history, factors and events to
that measurement. Both are honest and both are flat: a reader gets forty true
numbers and has to assemble the judgement themselves.

This module does the assembly. It is the difference between a spreadsheet and
the memo a senior person writes off the spreadsheet — the same arithmetic,
ordered by what actually decides the outcome, with the second-order numbers
that a professional reads first and a screener usually never computes:

  RISK BUDGET, not weight.   Capital weight says how much money sits in a
    name. Risk contribution says how much of the portfolio's movement that
    name causes, and the two are routinely far apart: a 9% position in a 40%-
    volatility stock that correlates with everything else can carry a quarter
    of total risk. The split is computed from the covariance matrix —
    marginal contribution σ⁻¹·Σw, contribution wᵢ·MCTRᵢ, which sums exactly
    to portfolio volatility — so every number in the table reconciles.

  DIVERSIFICATION EARNED, not counted.   The weighted average volatility of
    the holdings divided by the volatility of the portfolio is the
    diversification ratio: 1.0 means the book is one bet wearing many
    tickers. Effective holdings by capital (1/HHI) is already reported; this
    adds effective holdings by RISK, which is the number that matters.

  AGGREGATE VALUATION DONE CORRECTLY.   A weighted arithmetic mean of P/E is
    wrong and standard practice in retail tools — it over-weights expensive
    names without bound and breaks entirely on negative earnings. The
    portfolio multiple here is the reciprocal of the weighted earnings yield
    (a harmonic mean), which is what aggregating earnings actually gives.

  LOSS ARITHMETIC WITH A STATED DISTRIBUTION.   Value at risk from the
    realised return distribution of today's weights, alongside the parametric
    figure, plus the worst observed day and the drawdown those weights would
    have carried. Labelled for what it is: current weights applied to past
    prices, never a claim about what was actually earned.

  THE PRO-FORMA BOOK.   Every rule gap in the report already carries the
    share count that closes it. Nobody has ever added them up. This does, and
    then re-computes concentration, effective holdings and risk share on the
    resulting weights, so the reader sees what the book would look like, not
    just what is wrong with it.

FRAMING DISCIPLINE, UNCHANGED
Every sentence produced here is an observation with the arithmetic shown.
None of them is an instruction. "Two positions carry 38% of measured risk
against 21% of capital" is a fact about a covariance matrix; "reduce them" is
advice this platform is not registered to give. The verbs stay descriptive and
the questions at the end are questions, not steps.

PURITY
No network, no persistence, no clock beyond the `now` it is handed. Every
input arrives as an argument; every output discloses its coverage and the
denominator it was computed over. An input that is unavailable produces an
absent number and a named reason, never a default that quietly becomes a
conclusion.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

import portfolio_intelligence as pi

VERSION = 'ic-review-1'

TRADING_DAYS = 252
MIN_OBSERVATIONS = 60          # same floor the correlation matrix uses
LOOKBACK = 126                 # ~6 months of daily returns
VAR_Z = {95: 1.6449, 99: 2.3263}

# Conventional reference bands. They are disclosed wherever they are used and
# are deliberately wide: they exist to place a number, not to grade a company.
NEUTRAL_PE = (15.0, 28.0)
HIGH_RISK_VOL = 30.0           # annualised portfolio volatility, per cent
CROWDED_RISK_SHARE = 40.0      # top-two share of measured risk, per cent


def _num(value):
    return pi.number(value)


def _round(value, dp=2):
    v = _num(value)
    return round(v, dp) if v is not None else None


def _pct(value, dp=1):
    """
    Format for prose. Never prints a fabricated zero for a missing value.

    Rounds half away from zero rather than to even, because the browser's
    `toLocaleString` does, and a figure that reads 15.8% in the memo and 15.9%
    in the table beside it undermines every other number on the page.
    """
    v = _num(value)
    if v is None:
        return 'unavailable'
    quantum = Decimal(1).scaleb(-dp)
    return f'{Decimal(repr(v)).quantize(quantum, rounding=ROUND_HALF_UP):f}%'


def _inr(value):
    """Rupees, grouped the way they are read here: ₹10,00,000, not ₹1,000,000."""
    v = _num(value)
    if v is None:
        return 'unavailable'
    digits = f'{abs(v):.0f}'
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            head, part = head[:-2], head[-2:]
            parts.insert(0, part)
        digits = ','.join(([head] if head else []) + parts + [tail])
    return ('−' if v < 0 else '') + '₹' + digits


# ---------------------------------------------------------------------------
# Return sample
# ---------------------------------------------------------------------------

def _return_sample(rows, histories):
    """
    One aligned daily-return matrix for the holdings that can support one.

    Prices are outer-aligned before differencing — the same rule the existing
    correlation matrix follows — so a missing trading date can never pair a
    two-day return in one stock against a one-day return in another. Columns
    without enough observations are dropped before the common-date
    intersection is taken, because one short series would otherwise truncate
    the sample for everything else.

    Returns (returns_frame, weights_vector, meta) or (None, None, meta) with a
    stated reason.
    """
    series, short, unusable = {}, [], []
    for r in rows:
        if not r.get('symbol') or not _num(r.get('weight_pct')):
            continue
        try:
            s = pi.price_series((histories or {}).get(r['symbol']))
        except (TypeError, ValueError, KeyError, AttributeError):
            s = None
        if s is None:
            unusable.append(r['symbol'])
        elif s.notna().sum() <= MIN_OBSERVATIONS:
            short.append(r['symbol'])
        else:
            series[r['symbol']] = s

    if len(series) < 2:
        # Name the requirement that actually failed. "History unavailable" sends
        # a reader looking for a data-source problem when the real answer is
        # that the series is too young to say anything.
        reason = ('A risk budget needs at least two holdings priced against each other. '
                  f'{len(series)} qualified.')
        if short:
            reason += (f' {", ".join(sorted(short))} carry fewer than {MIN_OBSERVATIONS} '
                       f'observations, which is too small a sample to report a covariance from.')
        if unusable:
            reason += (f' {", ".join(sorted(unusable))} have no dated, explicitly adjusted price '
                       f'history; unverified-adjustment sources are withheld rather than mixed in.')
        return None, None, {'available': False, 'symbols': sorted(series), 'reason': reason}

    prices = pd.concat(series, axis=1, sort=True).sort_index()
    returns = prices.pct_change(fill_method=None).iloc[1:].tail(LOOKBACK)
    keep = [c for c in returns.columns if returns[c].notna().sum() >= MIN_OBSERVATIONS]
    returns = returns[keep].dropna(how='any')

    if len(returns.columns) < 2 or len(returns) < MIN_OBSERVATIONS:
        return None, None, {'available': False, 'symbols': list(returns.columns),
                            'reason': (f'Fewer than {MIN_OBSERVATIONS} trading dates are shared by at '
                                       f'least two holdings, so a covariance matrix would rest on a '
                                       f'sample too small to report.')}

    weights = {r['symbol']: _num(r.get('weight_pct')) or 0.0 for r in rows}
    covered = [s for s in returns.columns if weights.get(s, 0) > 0]
    returns = returns[covered]
    raw = np.array([weights[s] for s in covered], dtype=float)
    if raw.sum() <= 0:
        return None, None, {'available': False, 'symbols': covered,
                            'reason': 'No priced weight attaches to the holdings with usable history.'}

    meta = {
        'available': True,
        'symbols': covered,
        'coverage_pct': _round(raw.sum()),
        'observations': int(len(returns)),
        'from': str(returns.index[0].date()),
        'to': str(returns.index[-1].date()),
        'reason': None,
    }
    return returns, raw / raw.sum(), meta


# ---------------------------------------------------------------------------
# Risk budget
# ---------------------------------------------------------------------------

def risk_budget(rows, histories, benchmark=None):
    """
    Where the portfolio's movement actually comes from.

    Contribution to risk is wᵢ·(Σw)ᵢ/σₚ. The identity that makes it worth
    printing is that the contributions sum to σₚ exactly, so a reader can
    check the table against the headline rather than take it on faith. The
    gap between a holding's share of capital and its share of risk is the
    single most useful line a portfolio review can produce, and it is
    invisible in every weight table.
    """
    returns, w, meta = _return_sample(rows, histories)
    if returns is None:
        return {**meta, 'holdings': [], 'unassessed': ['Portfolio volatility', 'Risk contribution',
                                                       'Value at risk', 'Diversification ratio']}

    symbols = list(returns.columns)
    cov = returns.cov().to_numpy() * TRADING_DAYS
    variance = float(w @ cov @ w)
    if not math.isfinite(variance) or variance <= 0:
        return {**meta, 'available': False, 'holdings': [],
                'reason': 'The observed returns produce no positive portfolio variance.'}

    vol = math.sqrt(variance)
    marginal = (cov @ w) / vol                     # ∂σₚ/∂wᵢ
    contribution = w * marginal                    # sums to σₚ by construction
    standalone = np.sqrt(np.diag(cov))
    weighted_avg_vol = float(w @ standalone)

    by_symbol = {r['symbol']: r for r in rows}
    holdings = []
    for i, sym in enumerate(symbols):
        share = 100 * contribution[i] / vol
        cap = 100 * w[i]
        holdings.append({
            'symbol': sym,
            'weight_pct': _round(cap),
            'risk_share_pct': _round(share),
            'risk_vs_capital_pp': _round(share - cap),
            'volatility_pct': _round(standalone[i] * 100),
            'marginal_pct': _round(marginal[i] * 100),
            'contribution_pct': _round(contribution[i] * 100),
            'name': (by_symbol.get(sym) or {}).get('name'),
        })
    holdings.sort(key=lambda h: (-(h['risk_share_pct'] or 0), h['symbol']))

    shares = np.array([h['risk_share_pct'] or 0.0 for h in holdings]) / 100.0
    risk_hhi = float((shares ** 2).sum())

    # Today's weights applied to the observed return history. This is a
    # property of the current book, not a record of what the holder earned —
    # they did not hold these weights through this window.
    port = returns.to_numpy() @ w
    curve = np.cumprod(1 + port)
    drawdown = float((curve / np.maximum.accumulate(curve) - 1).min() * 100)
    downside = port[port < 0]

    out = {
        **meta,
        'volatility_pct': _round(vol * 100),
        'daily_volatility_pct': _round(float(port.std(ddof=1)) * 100),
        'weighted_average_volatility_pct': _round(weighted_avg_vol * 100),
        'diversification_ratio': _round(weighted_avg_vol / vol, 2),
        'diversification_benefit_pct': _round((weighted_avg_vol - vol) * 100),
        'effective_risk_positions': _round(1 / risk_hhi, 1) if risk_hhi > 0 else None,
        'risk_hhi': _round(risk_hhi, 4),
        'top1_risk_share_pct': holdings[0]['risk_share_pct'] if holdings else None,
        'top2_risk_share_pct': _round(sum(h['risk_share_pct'] or 0 for h in holdings[:2])),
        'top3_risk_share_pct': _round(sum(h['risk_share_pct'] or 0 for h in holdings[:3])),
        'downside_volatility_pct': _round(float(downside.std(ddof=1)) * math.sqrt(TRADING_DAYS) * 100)
                                   if len(downside) > 2 else None,
        'worst_day_pct': _round(float(port.min()) * 100),
        'best_day_pct': _round(float(port.max()) * 100),
        'window_drawdown_pct': _round(drawdown),
        'window_return_pct': _round(float(curve[-1] - 1) * 100),
        'holdings': holdings,
        'value_at_risk': {},
        'method': ('Annualised from daily adjusted-close returns (sample covariance × 252). '
                   'Risk contribution is wᵢ·(Σw)ᵢ/σₚ and sums to portfolio volatility. Weights '
                   'are renormalised over the holdings with usable history; the coverage figure '
                   'states how much priced capital that is.'),
        'basis': ('Current weights applied to past returns. It describes the book as it stands '
                  'today, not the return the holder actually experienced.'),
    }

    daily_vol = float(port.std(ddof=1))
    for level in (95, 99):
        historical = float(np.percentile(port, 100 - level))
        out['value_at_risk'][str(level)] = {
            'horizon': '1 trading day',
            'historical_pct': _round(-historical * 100),
            'parametric_pct': _round(VAR_Z[level] * daily_vol * 100),
            'monthly_parametric_pct': _round(VAR_Z[level] * daily_vol * math.sqrt(21) * 100),
        }
    out['value_at_risk']['method'] = (
        'Historical: the loss the observed daily distribution exceeded (100−level)% of the time. '
        'Parametric: z × daily volatility, assuming a normal distribution that real returns do not '
        'follow. Neither is a maximum loss, and both describe one day unless stated.')

    if benchmark is not None:
        out['benchmark'] = _benchmark_stats(returns, w, benchmark)
    return out


def _benchmark_stats(returns, w, benchmark):
    """
    Beta, correlation and capture against a supplied index series.

    Supplied, never fetched: this module stays pure, and a benchmark whose
    adjustment provenance is unknown is not silently accepted. Capture ratios
    are separated into up and down days because a single beta hides the
    asymmetry that actually decides how a drawdown feels.
    """
    try:
        bench = pi.price_series(benchmark)
        if bench is None:
            bench = pd.to_numeric(pd.Series(benchmark), errors='coerce').dropna()
            if not isinstance(bench.index, pd.DatetimeIndex):
                return {'available': False, 'reason': 'Benchmark series carries no usable dates.'}
            bench.index = bench.index.tz_localize(None).normalize()
            bench = bench[~bench.index.duplicated(keep='last')].sort_index()
    except (TypeError, ValueError, KeyError, AttributeError):
        return {'available': False, 'reason': 'Benchmark series could not be read.'}

    bench_ret = bench.pct_change(fill_method=None).dropna()
    port = pd.Series(returns.to_numpy() @ w, index=returns.index)
    joined = pd.concat({'p': port, 'b': bench_ret}, axis=1, sort=True).sort_index().dropna()
    if len(joined) < MIN_OBSERVATIONS:
        return {'available': False, 'observations': int(len(joined)),
                'reason': f'Fewer than {MIN_OBSERVATIONS} dates overlap with the benchmark.'}

    p, b = joined['p'].to_numpy(), joined['b'].to_numpy()
    var_b = float(b.var(ddof=1))
    beta = float(np.cov(p, b, ddof=1)[0][1] / var_b) if var_b > 0 else None
    active = p - b
    up, down = b > 0, b < 0

    def capture(mask):
        if mask.sum() < 10 or abs(b[mask].mean()) <= 0:
            return None
        return _round(100 * p[mask].mean() / b[mask].mean())

    return {
        'available': True,
        'name': (getattr(benchmark, 'attrs', {}) or {}).get('name') or 'the benchmark index',
        'symbol': (getattr(benchmark, 'attrs', {}) or {}).get('symbol'),
        'observations': int(len(joined)),
        'from': str(joined.index[0].date()),
        'to': str(joined.index[-1].date()),
        'beta': _round(beta, 2),
        'correlation': _round(float(np.corrcoef(p, b)[0][1]), 2),
        'r_squared': _round(float(np.corrcoef(p, b)[0][1] ** 2), 2),
        'tracking_error_pct': _round(float(active.std(ddof=1)) * math.sqrt(TRADING_DAYS) * 100),
        'active_return_pct': _round(float((np.cumprod(1 + p)[-1] - np.cumprod(1 + b)[-1]) * 100)),
        'up_capture_pct': capture(up),
        'down_capture_pct': capture(down),
        'up_days': int(up.sum()),
        'down_days': int(down.sum()),
        'method': ('Ordinary least-squares beta of daily portfolio returns on benchmark returns over '
                   'the shared window. Capture is mean portfolio return ÷ mean benchmark return on '
                   'the benchmark\'s up and down days, needing at least ten of each. Backward-looking '
                   'measurement on current weights; not a forecast of sensitivity.'),
    }


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def valuation_view(rows):
    """
    What the book pays for its earnings and its book value.

    The portfolio multiple is the reciprocal of the weighted earnings yield.
    Averaging P/E directly — which is what a naive weighted mean does — lets
    one 180× name drag an otherwise ordinary book into nonsense, because P/E
    is unbounded above and the reciprocal is not. Loss-making holdings have no
    meaningful multiple at all and are counted separately rather than dropped
    without mention.
    """
    priced = [r for r in rows if _num(r.get('value'))]
    total = sum(_num(r['value']) for r in priced) or 0.0
    if total <= 0:
        return {'available': False, 'reason': 'No priced capital to value.'}

    yields, books, negative, unavailable, names = [], [], [], [], []
    for r in priced:
        val = _num(r['value'])
        v = r.get('valuation') or {}
        pe, pb = _num(v.get('pe')), _num(v.get('pb'))
        if pe is None:
            unavailable.append(r['symbol'])
        elif pe <= 0:
            negative.append({'symbol': r['symbol'], 'weight_pct': _num(r.get('weight_pct'))})
        else:
            yields.append((val, 1.0 / pe))
            names.append({'symbol': r['symbol'], 'pe': _round(pe, 1), 'pb': _round(pb, 2),
                          'weight_pct': _num(r.get('weight_pct')),
                          'earnings_yield_pct': _round(100 / pe)})
        if pb is not None and pb > 0:
            books.append((val, 1.0 / pb))

    def harmonic(pairs):
        den = sum(v for v, _ in pairs)
        if den <= 0:
            return None, None
        y = sum(v * inv for v, inv in pairs) / den
        return (round(1 / y, 2) if y > 0 else None), round(100 * den / total, 2)

    pe, pe_cov = harmonic(yields)
    pb, pb_cov = harmonic(books)
    ranked = sorted(names, key=lambda n: -(n['pe'] or 0))
    median_pe = _round(float(np.median([n['pe'] for n in names])), 1) if names else None

    band = 'unavailable'
    if pe is not None:
        band = ('below the 15–28× reference band' if pe < NEUTRAL_PE[0] else
                'above the 15–28× reference band' if pe > NEUTRAL_PE[1] else
                'inside the 15–28× reference band')

    return {
        'available': pe is not None or pb is not None,
        'portfolio_pe': pe,
        'portfolio_pe_coverage_pct': pe_cov,
        'portfolio_pb': pb,
        'portfolio_pb_coverage_pct': pb_cov,
        'earnings_yield_pct': _round(100 / pe) if pe else None,
        'median_holding_pe': median_pe,
        'reference_band': list(NEUTRAL_PE),
        'band_position': band,
        'most_expensive': ranked[:3],
        'least_expensive': list(reversed(ranked[-3:])) if len(ranked) > 3 else [],
        'loss_making': negative,
        'loss_making_weight_pct': _round(sum(n['weight_pct'] or 0 for n in negative)),
        'unpriced_multiple_symbols': sorted(unavailable),
        'method': ('Portfolio P/E is 1 ÷ Σ(weightᵢ × 1/PEᵢ) over positive-earnings holdings — the '
                   'harmonic mean, which is what aggregating earnings gives. Trailing provider '
                   'figures; no forward estimate is used. The 15–28× band is a conventional '
                   'reference for placing the number, not a fair-value judgement.'),
    }


# ---------------------------------------------------------------------------
# The pro-forma book
# ---------------------------------------------------------------------------

def capital_plan(report):
    """
    What closing every rule gap would do to the shape of the book.

    The per-position arithmetic already exists in the breach list. Adding it
    up is not cosmetic: a reader who sees three separate "the gap is N shares"
    lines has no way to know whether acting on all three frees 4% of the book
    or 26% of it, and no way to see that the resulting portfolio still breaks
    the same ceiling somewhere else. The pro-forma weights answer both.
    """
    rows = report.get('holdings') or []
    total = _num(report.get('total_value')) or 0.0
    gaps = [b for b in (report.get('breaches') or [])
            if b.get('rule') == 'max_stock_pct' and b.get('arithmetic')]
    if total <= 0:
        return {'available': False, 'reason': 'No priced capital.'}
    if not gaps:
        return {'available': True, 'gaps': [], 'released_value': 0.0, 'released_pct': 0.0,
                'note': 'No single-stock ceiling is exceeded, so no gap arithmetic applies.'}

    release = {}
    for b in gaps:
        a = b['arithmetic']
        release[b['symbol']] = _num(a.get('value')) or 0.0
    released = sum(release.values())
    remaining_total = total - released

    proforma = []
    for r in rows:
        value = (_num(r.get('value')) or 0.0) - release.get(r['symbol'], 0.0)
        proforma.append({'symbol': r['symbol'],
                         'weight_pct': _round(100 * value / remaining_total) if remaining_total > 0 else None,
                         'was_pct': _num(r.get('weight_pct'))})
    weights = [p['weight_pct'] or 0.0 for p in proforma]
    fractions = [w / 100 for w in weights]
    hhi = sum(f * f for f in fractions)
    ordered = sorted(weights, reverse=True)

    return {
        'available': True,
        'gaps': [{'symbol': b['symbol'], 'rule': b['rule'], 'measured_pct': b.get('measured'),
                  'limit_pct': b.get('limit'), **b['arithmetic']} for b in gaps],
        'released_value': _round(released),
        'released_pct': _round(100 * released / total),
        'proforma': sorted(proforma, key=lambda p: -(p['weight_pct'] or 0)),
        'proforma_top1_pct': _round(ordered[0]) if ordered else None,
        'proforma_top3_pct': _round(sum(ordered[:3])),
        'proforma_effective_n': _round(1 / hhi, 1) if hhi > 0 else None,
        'proforma_total_value': _round(remaining_total),
        'note': ('Arithmetic against the ceilings in the reader\'s own rulebook, at today\'s prices, '
                 'ignoring taxes, charges and market impact. Released capital is shown as cash: no '
                 'destination is proposed and nothing here is an instruction to sell.'),
    }


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def _score_band(value, best, worst):
    """Linear 0–100 placement between a worst and a best reference point."""
    v = _num(value)
    if v is None:
        return None
    if best == worst:
        return None
    return round(max(0.0, min(100.0, 100 * (v - worst) / (best - worst))))


def scorecard(report, risk, valuation):
    """
    Six dimensions, each from measured inputs, each able to say 'unavailable'.

    The overall figure is the mean of the dimensions that could be computed,
    and it names its own denominator. A dimension with no data is never scored
    50 to keep the average tidy — that is how a data gap turns into a verdict.
    """
    conc = report.get('concentration') or {}
    pol = report.get('policy') or {}
    quality = report.get('data_quality') or {}
    rules = (report.get('risk') or {}).get('rules') or []
    rows = report.get('holdings') or []

    dims = []

    # Construction: how close the effective count and the largest position sit
    # to the reader's own structural limits.
    eff = _score_band(conc.get('effective_n'), best=max(pol.get('min_holdings', 8) * 1.5, 12), worst=1)
    top1 = _score_band(conc.get('top1_pct'), best=pol.get('max_stock_pct', 15) * 0.5,
                       worst=pol.get('max_stock_pct', 15) * 2.5)
    parts = [p for p in (eff, top1) if p is not None]
    dims.append({'key': 'construction', 'label': 'Portfolio construction',
                 'score': round(sum(parts) / len(parts)) if parts else None,
                 'inputs': {'effective_holdings': conc.get('effective_n'), 'top1_pct': conc.get('top1_pct'),
                            'min_holdings': pol.get('min_holdings'), 'max_stock_pct': pol.get('max_stock_pct')},
                 'method': 'Effective holdings and largest weight placed against the reader\'s own structural limits.'})

    # Evidence quality: the weighted Altaha score, which is the research view.
    dims.append({'key': 'quality', 'label': 'Research evidence',
                 'score': round(_num(report.get('weighted_score'))) if _num(report.get('weighted_score')) is not None else None,
                 'inputs': {'weighted_score': report.get('weighted_score'),
                            'coverage_pct': quality.get('scored_value_pct')},
                 'method': 'Value-weighted Altaha Score over covered capital, unmodified.'})

    # Risk posture: volatility, drawdown and how crowded the risk budget is.
    risk_parts = [p for p in (
        _score_band(risk.get('volatility_pct'), best=12, worst=45),
        _score_band(risk.get('top2_risk_share_pct'), best=25, worst=75),
        _score_band(risk.get('diversification_ratio'), best=1.6, worst=1.0),
    ) if p is not None]
    if not risk_parts:
        triggered = sum(1 for r in rules if r.get('triggered'))
        assessed = sum(1 for r in rules if r.get('measured') is not None)
        risk_parts = [round(100 * (1 - triggered / assessed))] if assessed else []
    dims.append({'key': 'risk', 'label': 'Risk posture',
                 'score': round(sum(risk_parts) / len(risk_parts)) if risk_parts else None,
                 'inputs': {'volatility_pct': risk.get('volatility_pct'),
                            'top2_risk_share_pct': risk.get('top2_risk_share_pct'),
                            'diversification_ratio': risk.get('diversification_ratio')},
                 'method': 'Annualised volatility, concentration of the risk budget and diversification ratio, '
                           'falling back to the count of triggered policy measures when history is unavailable.'})

    # Valuation: distance from the disclosed reference band, either side.
    pe = _num(valuation.get('portfolio_pe'))
    val_score = None
    if pe is not None and pe > 0:
        lo, hi = NEUTRAL_PE
        if lo <= pe <= hi:
            val_score = 75
        elif pe < lo:
            val_score = round(min(100, 75 + (lo - pe) * 2))
        else:
            val_score = _score_band(pe, best=hi, worst=hi * 2.5)
    dims.append({'key': 'valuation', 'label': 'Valuation discipline',
                 'score': val_score,
                 'inputs': {'portfolio_pe': valuation.get('portfolio_pe'),
                            'coverage_pct': valuation.get('portfolio_pe_coverage_pct'),
                            'reference_band': list(NEUTRAL_PE)},
                 'method': 'Placement of the aggregate earnings multiple against a disclosed conventional band. '
                           'A high multiple is a fact about price, not a verdict on the businesses.'})

    # Positioning: how far the sector mix sits from the benchmark proxy.
    active = [abs(_num(s.get('active_weight_pct')) or 0) for s in (report.get('sector_comparison') or [])
              if _num(s.get('active_weight_pct')) is not None]
    dims.append({'key': 'positioning', 'label': 'Benchmark positioning',
                 'score': _score_band(sum(active) / 2 if active else None, best=10, worst=60),
                 'inputs': {'sum_absolute_active_pp': _round(sum(active) / 2) if active else None},
                 'method': 'Half the sum of absolute active sector weights (the standard active-share '
                           'arithmetic) against the approximate benchmark proxy. A high reading means a '
                           'portfolio that will not track the index, which is a choice, not an error.'})

    # Evidence base: can any of the above be trusted at face value.
    cov = [_num(quality.get(k)) for k in ('scored_value_pct', 'sector_value_pct', 'cost_value_pct')]
    cov = [c for c in cov if c is not None]
    base = sum(cov) / len(cov) if cov else None
    if base is not None and quality.get('score_stale'):
        base *= 0.75
    dims.append({'key': 'evidence', 'label': 'Data completeness',
                 'score': round(base) if base is not None else None,
                 'inputs': {'scored_value_pct': quality.get('scored_value_pct'),
                            'sector_value_pct': quality.get('sector_value_pct'),
                            'cost_value_pct': quality.get('cost_value_pct'),
                            'score_stale': quality.get('score_stale')},
                 'method': 'Mean of score, sector and cost coverage, reduced by a quarter when the score scan '
                           'is stale or undated.'})

    scored = [d['score'] for d in dims if d['score'] is not None]
    overall = round(sum(scored) / len(scored)) if scored else None
    grade = ('—' if overall is None else 'A' if overall >= 75 else 'B+' if overall >= 65 else
             'B' if overall >= 55 else 'C' if overall >= 45 else 'D')
    return {'overall': overall, 'grade': grade, 'dimensions': dims,
            'dimensions_scored': len(scored), 'dimensions_total': len(dims),
            'holdings': len(rows),
            'method': 'Equal-weighted mean of the dimensions that could be computed. Dimensions without '
                      'data are omitted from the mean and reported as unavailable, never imputed.'}


# ---------------------------------------------------------------------------
# The memo
# ---------------------------------------------------------------------------

def _sector_lines(report):
    comparison = [s for s in (report.get('sector_comparison') or [])
                  if _num(s.get('active_weight_pct')) is not None]
    over = sorted(comparison, key=lambda s: -(s['active_weight_pct']))[:2]
    under = sorted(comparison, key=lambda s: (s['active_weight_pct']))[:2]
    return over, under


def memo(report, risk, valuation, plan, card, now):
    """
    The write-up. Ordered the way a committee actually reads a book: what it
    is, how it is built, what moves it, what it costs, where it sits against
    the index, and what the evidence will and will not support.
    """
    rows = report.get('holdings') or []
    conc = report.get('concentration') or {}
    pol = report.get('policy') or {}
    quality = report.get('data_quality') or {}
    total = _num(report.get('total_value'))
    sections = []

    def section(sid, heading, verdict, paragraphs, evidence):
        sections.append({'id': sid, 'heading': heading, 'verdict': verdict,
                         'paragraphs': [p for p in paragraphs if p], 'evidence': evidence})

    # 1. The book as it stands ------------------------------------------------
    top = sorted(rows, key=lambda r: -(_num(r.get('weight_pct')) or 0))[:3]
    top_txt = ', '.join(f"{r['symbol']} {_pct(r.get('weight_pct'))}" for r in top) or 'none'
    pnl_txt = ''
    if _num(report.get('total_pnl')) is not None:
        pnl_txt = (f"Unrealised profit and loss stands at {_inr(report.get('total_pnl'))} "
                   f"({_pct(report.get('total_pnl_pct'))}) on the "
                   f"{_pct(quality.get('cost_value_pct'))} of capital with a known purchase price.")
    section('standing', 'The book as it stands',
            f"{len(rows)} priced holdings, {_inr(total)}, led by {top[0]['symbol'] if top else '—'}.",
            [f"The portfolio carries {len(rows)} priced holdings worth {_inr(total)}. The three largest "
             f"are {top_txt}, together {_pct(conc.get('top3_pct'))} of capital. "
             f"{len(report.get('failed') or [])} position(s) could not be priced and are excluded from "
             f"every percentage in this memo.",
             pnl_txt],
            ['total_value', 'holdings.weight_pct', 'concentration.top3_pct', 'total_pnl'])

    # 2. Construction ---------------------------------------------------------
    eff = _num(conc.get('effective_n'))
    count = len(rows)
    construction = 'unavailable'
    if eff is not None and count:
        construction = (f"{eff:.1f} effective positions against {count} names"
                        + (' — the weights, not the count, decide what this book does'
                           if eff < count * 0.8 else ' — weights are close to even'))
    section('construction', 'How the book is built', construction,
            [f"Herfindahl concentration is {conc.get('hhi')}, which is the same concentration as "
             f"{_pct(100 / eff, 1) if eff else 'unavailable'} each in {eff:.1f} equally sized positions. "
             f"The largest single name is {_pct(conc.get('top1_pct'))} against the "
             f"{_pct(pol.get('max_stock_pct'), 0)} ceiling in the rulebook."
             if eff else 'Concentration arithmetic is unavailable without priced weights.',
             (f"Closing every single-stock gap at today's prices would release {_inr(plan.get('released_value'))}, "
              f"{_pct(plan.get('released_pct'))} of the book, and leave the largest position at "
              f"{_pct(plan.get('proforma_top1_pct'))} with {plan.get('proforma_effective_n')} effective holdings."
              ) if plan.get('gaps') else
             'No single-stock ceiling is currently exceeded, so there is no gap arithmetic to add up.'],
            ['concentration.hhi', 'concentration.effective_n', 'policy.max_stock_pct', 'capital_plan'])

    # 3. Risk budget ----------------------------------------------------------
    if risk.get('available'):
        lead = risk['holdings'][0] if risk.get('holdings') else {}
        var95 = (risk.get('value_at_risk') or {}).get('95', {})
        divergent = [h for h in risk.get('holdings') or []
                     if (h.get('risk_vs_capital_pp') or 0) >= 5][:3]
        div_txt = ''
        if divergent:
            div_txt = ('Risk and capital diverge most in ' +
                       ', '.join(f"{h['symbol']} ({_pct(h['weight_pct'])} of capital, "
                                 f"{_pct(h['risk_share_pct'])} of risk)" for h in divergent) + '.')
        section('risk', 'Where the movement comes from',
                (f"{_pct(risk.get('volatility_pct'))} annualised volatility; the top two names carry "
                 f"{_pct(risk.get('top2_risk_share_pct'))} of it."),
                [f"On {risk.get('observations')} shared trading dates to {risk.get('to')}, covering "
                 f"{_pct(risk.get('coverage_pct'))} of priced capital, the current weights produce "
                 f"{_pct(risk.get('volatility_pct'))} annualised volatility against a weighted average "
                 f"holding volatility of {_pct(risk.get('weighted_average_volatility_pct'))} — a "
                 f"diversification ratio of {risk.get('diversification_ratio')}, or "
                 f"{_pct(risk.get('diversification_benefit_pct'))} of volatility removed by the fact that "
                 f"the holdings do not move together.",
                 f"{lead.get('symbol', '—')} is the largest single source of movement at "
                 f"{_pct(lead.get('risk_share_pct'))} of portfolio risk on {_pct(lead.get('weight_pct'))} "
                 f"of capital. The book has {risk.get('effective_risk_positions')} effective positions "
                 f"measured by risk against {conc.get('effective_n')} measured by capital. {div_txt}",
                 f"On the observed distribution, a one-day loss of {_pct(var95.get('historical_pct'))} or "
                 f"worse occurred 5% of the time; the normal-distribution equivalent is "
                 f"{_pct(var95.get('parametric_pct'))}. The worst single day in the window was a fall of "
                 f"{_pct(abs(_num(risk.get('worst_day_pct')) or 0))} and these weights would have carried a "
                 f"peak-to-trough drawdown of {_pct(abs(_num(risk.get('window_drawdown_pct')) or 0))}. That is "
                 f"the shape of today's book applied to past prices, not a record of what was earned."],
                ['risk_budget.holdings', 'risk_budget.value_at_risk', 'risk_budget.diversification_ratio'])
    else:
        section('risk', 'Where the movement comes from', 'Not measurable from the available history.',
                [risk.get('reason') or 'Insufficient adjusted price history.',
                 'Weight-based concentration below remains valid; it simply cannot be translated into '
                 'volatility, correlation or loss arithmetic without dated adjusted prices.'],
                ['risk_budget.reason'])

    # 4. Benchmark sensitivity ------------------------------------------------
    bench = (risk.get('benchmark') or {}) if isinstance(risk.get('benchmark'), dict) else {}
    if bench.get('available'):
        index = bench.get('name') or 'the benchmark index'
        section('sensitivity', 'Sensitivity to the index',
                f"Beta {bench.get('beta')} against {index}.",
                [f"Over {bench.get('observations')} shared dates the book's beta to {index} is "
                 f"{bench.get('beta')} with an R² of {bench.get('r_squared')}, so "
                 f"{_pct((bench.get('r_squared') or 0) * 100, 0)} of daily movement is explained by the "
                 f"index and the remainder is specific to these holdings. Tracking error is "
                 f"{_pct(bench.get('tracking_error_pct'))} annualised.",
                 f"On {index}'s up days the portfolio captured {_pct(bench.get('up_capture_pct'), 0)} of "
                 f"the move; on down days {_pct(bench.get('down_capture_pct'), 0)}. Measured on "
                 f"{bench.get('up_days')} up and {bench.get('down_days')} down days, backward-looking."],
                ['risk_budget.benchmark'])

    # 5. Quality and valuation ------------------------------------------------
    weak_weight = sum(_num(r.get('weight_pct')) or 0 for r in rows
                      if _num(r.get('composite')) is not None and r['composite'] < (pol.get('min_composite') or 45))
    val_txt = 'Aggregate multiples are unavailable for this book.'
    if valuation.get('portfolio_pe'):
        val_txt = (f"The book trades at {valuation['portfolio_pe']}× trailing earnings — "
                   f"{valuation.get('band_position')} — on {_pct(valuation.get('portfolio_pe_coverage_pct'))} "
                   f"of capital, an earnings yield of {_pct(valuation.get('earnings_yield_pct'))}. "
                   f"The median holding sits at {valuation.get('median_holding_pe')}×, so the aggregate is "
                   f"{'pulled up by the larger positions' if (valuation.get('median_holding_pe') or 0) < valuation['portfolio_pe'] else 'below the typical holding'}.")
    if valuation.get('loss_making'):
        val_txt += (f" {_pct(valuation.get('loss_making_weight_pct'))} of capital sits in holdings with no "
                    f"positive trailing earnings, which carry no multiple and are excluded from that figure.")
    ws = _num(report.get('weighted_score'))
    score_txt = (f"The value-weighted Altaha Score is {ws:.1f}/100 ({report.get('grade')}) over "
                 f"{_pct(quality.get('scored_value_pct'))} of priced capital, from the universe scan "
                 f"dated {quality.get('score_as_of') or 'unknown'}. {_pct(weak_weight)} of the book "
                 f"scores below the {pol.get('min_composite')} floor in the rulebook."
                 if ws is not None else
                 'A value-weighted Altaha Score is unavailable: none of the priced capital carries a '
                 'comparable score from the universe scan, so no research verdict is asserted here.')
    section('quality', 'What the evidence says, and what it costs',
            ((f"Weighted score {ws:.1f}/100" if ws is not None else 'Weighted score unavailable')
             + (f" at {valuation['portfolio_pe']}× earnings." if valuation.get('portfolio_pe') else '.')),
            [score_txt,
             val_txt],
            ['weighted_score', 'data_quality.scored_value_pct', 'valuation.portfolio_pe'])

    # 6. Positioning ----------------------------------------------------------
    over, under = _sector_lines(report)
    if over:
        section('positioning', 'Where the book differs from the index',
                f"Largest active weight: {over[0]['sector']} {over[0]['active_weight_pct']:+.1f} pp.",
                [f"Against the approximate {report.get('benchmark', {}).get('name', 'benchmark')} mix dated "
                 f"{report.get('benchmark', {}).get('as_of')}, the largest overweights are "
                 + ', '.join(f"{s['sector']} ({s['active_weight_pct']:+.1f} pp)" for s in over)
                 + '; the largest underweights are '
                 + ', '.join(f"{s['sector']} ({s['active_weight_pct']:+.1f} pp)" for s in under)
                 + '. Those gaps, not the absolute weights, are what will make this book diverge from the '
                   'index in either direction.',
                 'The benchmark mix is a manually maintained approximate proxy, not live constituent '
                 'weights, so read the direction of each gap rather than its last decimal.'],
                ['sector_comparison', 'benchmark.as_of'])

    # 7. Events ---------------------------------------------------------------
    events = ((report.get('developments') or {}).get('events') or [])[:3]
    if events:
        section('catalysts', 'What has moved around the holdings',
                f"{len((report.get('developments') or {}).get('events') or [])} sourced developments in seven days.",
                ['Ranked by exposed weight, source category and recency: '
                 + '; '.join(f"{e['headline']} ({', '.join(e['symbols'])}, {_pct(e['exposure_pct'])} exposure)"
                             for e in events) + '.',
                 'Direction is not inferred from headline vocabulary. Read the primary source before '
                 'attaching any meaning to these at position size.'],
                ['developments.events'])

    # 8. Limits ---------------------------------------------------------------
    section('limits', 'What this review cannot tell you',
            f"{card.get('dimensions_scored')} of {card.get('dimensions_total')} dimensions could be scored.",
            [' '.join(quality.get('warnings') or []) or 'No coverage warnings were raised.',
             'Unassessed here: liquidity and the cost of moving these positions, promoter pledging, '
             'related-party exposure, currency and rate sensitivity, tax position, and everything the '
             'holder knows about their own circumstances that no file contains.'],
            ['data_quality.warnings'])

    return sections


def agenda(report, risk, valuation, plan, now):
    """
    The items a committee would actually put on the table, ranked.

    Each carries what was measured, the threshold it crossed and — where the
    report already computed one — the arithmetic. Each ends in a question,
    because the answer belongs to the person whose money it is.
    """
    items = []
    pol = report.get('policy') or {}
    conc = report.get('concentration') or {}

    for b in report.get('breaches') or []:
        a = b.get('arithmetic') or {}
        items.append({
            'priority': 100 + (_num(b.get('measured')) or 0) if b.get('rule') == 'max_stock_pct' else 60,
            'title': b.get('title'), 'rule': b.get('rule'),
            'measured': b.get('measured'), 'limit': b.get('limit'),
            'observation': b.get('text'),
            'arithmetic': (f"{a['shares']} of {int(a['of_shares'])} shares, {_inr(a['value'])} at "
                           f"₹{a['price']:,.2f}, leaving {a['resulting_weight_pct']:.1f}%.") if a else None,
            'question': {
                'max_stock_pct': 'Is this position deliberately sized above the ceiling, or has it drifted there?',
                'max_sector_pct': 'Is this sector weight a view being expressed, or an accumulation of separate decisions?',
                'min_composite': 'What does the holder know about this company that the measured evidence does not?',
                'review_drawdown': 'Has the reason for owning this changed, or only the price?',
                'min_holdings': 'Is the small number of names a concentration of conviction or of habit?',
                'max_unclassified_pct': 'Which of these holdings need a sector attached before the read is complete?',
            }.get(b.get('rule'), 'What does the holder want to do about this?'),
        })

    if risk.get('available'):
        crowded = [h for h in risk.get('holdings') or [] if (h.get('risk_vs_capital_pp') or 0) >= 8]
        if crowded:
            h = crowded[0]
            items.append({
                'priority': 90, 'title': f"Risk concentration · {h['symbol']}", 'rule': 'risk_share',
                'measured': h['risk_share_pct'], 'limit': h['weight_pct'],
                'observation': (f"{h['symbol']} is {_pct(h['weight_pct'])} of capital but "
                                f"{_pct(h['risk_share_pct'])} of measured portfolio risk, on "
                                f"{_pct(h['volatility_pct'])} annualised volatility over "
                                f"{risk.get('observations')} shared dates."),
                'arithmetic': None,
                'question': 'Is the risk this name contributes proportionate to the conviction behind it?',
            })
        if (_num(risk.get('top2_risk_share_pct')) or 0) > CROWDED_RISK_SHARE:
            items.append({
                'priority': 80, 'title': 'Risk budget concentration', 'rule': 'risk_budget',
                'measured': risk.get('top2_risk_share_pct'), 'limit': CROWDED_RISK_SHARE,
                'observation': (f"Two holdings account for {_pct(risk.get('top2_risk_share_pct'))} of "
                                f"portfolio risk; the book has {risk.get('effective_risk_positions')} "
                                f"effective positions by risk against {conc.get('effective_n')} by capital."),
                'arithmetic': None,
                'question': 'Would the holder accept this book if it were described only by its risk shares?',
            })
        if (_num(risk.get('volatility_pct')) or 0) > HIGH_RISK_VOL:
            var95 = (risk.get('value_at_risk') or {}).get('95', {})
            items.append({
                'priority': 70, 'title': 'Portfolio volatility', 'rule': 'volatility',
                'measured': risk.get('volatility_pct'), 'limit': HIGH_RISK_VOL,
                'observation': (f"Annualised volatility is {_pct(risk.get('volatility_pct'))}. On the "
                                f"observed distribution a one-day loss of {_pct(var95.get('historical_pct'))} "
                                f"or worse occurred on 5% of days."),
                'arithmetic': None,
                'question': 'Is a book that moves this much consistent with when this money is needed?',
            })

    if valuation.get('loss_making'):
        items.append({
            'priority': 50, 'title': 'Holdings without positive earnings', 'rule': 'valuation',
            'measured': valuation.get('loss_making_weight_pct'), 'limit': None,
            'observation': (f"{_pct(valuation.get('loss_making_weight_pct'))} of capital sits in "
                            + ', '.join(n['symbol'] for n in valuation['loss_making'])
                            + ', which report no positive trailing earnings and therefore no multiple.'),
            'arithmetic': None,
            'question': 'What has to happen for these to earn, and over what period?',
        })

    stale = (report.get('data_quality') or {}).get('score_stale')
    if stale:
        items.append({
            'priority': 40, 'title': 'Score freshness', 'rule': 'evidence',
            'measured': None, 'limit': None,
            'observation': ('The universe scan behind every score in this memo is older than seven days or '
                            'carries no usable timestamp.'),
            'arithmetic': None,
            'question': 'Should the scan be refreshed before any of this is acted on?',
        })

    items.sort(key=lambda i: (-i['priority'], str(i['title'])))
    for rank, item in enumerate(items, 1):
        item['rank'] = rank
    return items[:12]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build(report, histories=None, benchmark_history=None, now=None):
    """Assemble the review from an already-enriched report. Pure and total."""
    rows = report.get('holdings') or []
    if not rows:
        return {'version': VERSION, 'available': False,
                'reason': 'No priced holdings, so there is nothing to review.'}

    risk = risk_budget(rows, histories, benchmark_history)
    valuation = valuation_view(rows)
    plan = capital_plan(report)
    card = scorecard(report, risk, valuation)
    sections = memo(report, risk, valuation, plan, card, now)
    items = agenda(report, risk, valuation, plan, now)

    conc = report.get('concentration') or {}
    weighted = _num(report.get('weighted_score'))
    headline = (f"{len(rows)} holdings, {_inr(report.get('total_value'))}, "
                f"{_pct(conc.get('top3_pct'))} in the top three. "
                + (f"Weighted score {weighted:.1f}/100" if weighted is not None
                   else 'No weighted score available')
                + (f", {_pct(risk.get('volatility_pct'))} annualised volatility"
                   if risk.get('available') else '')
                + (f", {valuation['portfolio_pe']}× trailing earnings" if valuation.get('portfolio_pe') else '')
                + f". {len([i for i in items if i['priority'] >= 60])} item(s) for review.")

    return {
        'version': VERSION,
        'available': True,
        'headline': headline,
        'scorecard': card,
        'risk_budget': risk,
        'valuation': valuation,
        'capital_plan': plan,
        'sections': sections,
        'agenda': items,
        'unassessed': [
            'Liquidity, traded volume and the market impact of changing these positions',
            'Promoter pledging, related-party exposure and governance history',
            'Currency, commodity and interest-rate sensitivity',
            'Tax position, realised transactions, dividends and charges',
            'The holder\'s income, obligations, horizon and everything else no file contains',
        ],
        'framing': ('Observations with the arithmetic shown, measured against the reader\'s own '
                    'rulebook and disclosed reference bands. Nothing here is an instruction to buy, '
                    'sell or hold any security, and no outcome is forecast.'),
    }
