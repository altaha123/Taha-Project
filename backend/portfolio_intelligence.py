"""Pure, evidence-linked portfolio analytics. No network, trades or persistence.

Weights use priced capital; missing prices make the report explicitly partial.
Factor averages exclude unavailable observations and disclose their denominator.
"""
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import sectors

VERSION = 'portfolio-intelligence-1'
WINDOWS = {'1M': 21, '3M': 63, '6M': 126, '1Y': 252}
BANDS = [(80, 'Exceptional'), (70, 'Strong'), (60, 'Good'), (50, 'Average'),
         (40, 'Weak'), (0, 'High concern')]


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (float,np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.bool_): return bool(value)
    return value


def stamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        try:
            d = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    # Legacy source strings without a timezone are India exchange timestamps.
    if d.tzinfo is None:
        from datetime import timedelta
        d = d.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return d.astimezone(timezone.utc)


def safe_url(value):
    try:
        p = urlparse(str(value or ''))
        return str(value) if p.scheme in ('https', 'http') and p.netloc and not p.username else None
    except ValueError:
        return None


def weighted(rows, getter):
    pairs = [(number(getter(r)), r['value']) for r in rows]
    pairs = [(v, w) for v, w in pairs if v is not None and w > 0]
    den = sum(w for v, w in pairs)
    total = sum(r['value'] for r in rows)
    return {'value': round(sum(v*w for v, w in pairs)/den, 2) if den else None,
            'coverage_pct': round(100*den/total, 2) if total else None,
            'count': len(pairs)}


def band(score):
    return next((label for floor, label in BANDS if score >= floor), 'Unavailable') if score is not None else 'Unscored'


def price_series(frame):
    """Require dated, explicitly adjusted closes. No invented trading dates."""
    if frame is None or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    if frame.attrs.get('adjustment') != 'adjusted':
        return None
    s = pd.to_numeric(frame['Close'], errors='coerce').copy()
    s.index = s.index.tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep='last')].sort_index()
    # Keep invalid dates as gaps; dropping them creates synthetic multi-day returns.
    return s.where(np.isfinite(s) & (s > 0)).tail(300)


def history_analytics(rows, histories, now=None):
    now = now or datetime.now(timezone.utc)
    series = {}
    for r in rows:
        try:
            s = price_series((histories or {}).get(r['symbol']))
            if s is not None and len(s) and (now.date()-s.index[-1].date()).days <= 7:
                series[r['symbol']] = s
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    windows = {}
    for label, n in WINDOWS.items():
        points = []
        for r in rows:
            s = series.get(r['symbol'])
            if s is None or len(s) < n+1:
                continue
            w = s.iloc[-n-1:]
            # No back/forward filling. Reject sparse calendar spans too.
            if w.isna().any() or (w.index[-1]-w.index[0]).days > n*1.8+10:
                continue
            ret = w.pct_change(fill_method=None).iloc[1:]
            vol = number(ret.std(ddof=1)*math.sqrt(252)*100)
            points.append({'symbol': r['symbol'], 'weight_pct': r['weight_pct'],
                           'score': r.get('composite'), 'return_pct': round(100*(w.iloc[-1]/w.iloc[0]-1), 2),
                           'volatility_pct': round(vol, 2) if vol is not None else None,
                           'max_drawdown_pct': round(100*(w/w.cummax()-1).min(), 2),
                           'observations': n, 'from': str(w.index[0].date()), 'to': str(w.index[-1].date())})
        windows[label] = {'points': points, 'coverage_pct': round(sum(p['weight_pct'] for p in points), 2)}
    # Outer align PRICES first. A missing trading date cannot turn a two-day
    # stock return into the counterpart of a one-day return in another stock.
    matrix, pairs = [], []
    names = [r['symbol'] for r in rows if r['symbol'] in series]
    if names:
        prices = pd.concat({s: series[s] for s in names}, axis=1).sort_index().tail(127)
        returns = prices.pct_change(fill_method=None).iloc[1:]
        for i, a in enumerate(names):
            cells = []
            for j, b in enumerate(names):
                aligned = returns[[a, b]].dropna() if a != b else returns[[a]].dropna()
                count = len(aligned)
                val = None
                if count >= 60:
                    if a == b:
                        val = 1.0 if aligned.iloc[:, 0].std() > 0 else None
                    elif (aligned.std() > 0).all():
                        val = number(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                cells.append({'value': round(val, 3) if val is not None else None, 'observations': count})
                if j > i and val is not None and val >= .8:
                    pairs.append({'a': a, 'b': b, 'correlation': round(val, 3), 'observations': count})
            matrix.append(cells)
        dates = {'from': str(prices.index[0].date()), 'to': str(prices.index[-1].date())}
    else:
        dates = {'from': None, 'to': None}
    correlated = {p[k] for p in pairs for k in ('a', 'b')}
    exposure = sum(r['weight_pct'] for r in rows if r['symbol'] in correlated)
    return {'windows': windows, 'correlation': {'symbols': names, 'matrix': matrix, 'high_pairs': pairs,
            'high_correlation_exposure_pct': round(exposure, 2), 'minimum_observations': 60, **dates},
            'method': 'Adjusted close returns; sample daily volatility × √252. Correlation: up to 126 daily returns, at least 60 overlapping dates. No filling missing prices. Historical holdings returns, not realised portfolio performance.',
            'unavailable_reason': 'Requires fresh, dated, explicitly adjusted price history. Dhan adjustment status is currently unverified; those series are withheld.'}


def news_intelligence(rows, items, now=None, status=None):
    now = now or datetime.now(timezone.utc)
    held = {r['symbol']: r for r in rows}
    events, seen = [], set()
    for raw in items or []:
        date = stamp(raw.get('published_at') or raw.get('when_iso') or raw.get('at'))
        url = safe_url(raw.get('url') or raw.get('pdf'))
        headline = str(raw.get('headline') or raw.get('title') or '').strip()
        source = raw.get('source')
        if not date or not url or not headline or not source:
            continue
        age = (now-date).total_seconds()/3600
        if age < -1 or age > 7*24:
            continue
        direct = set(raw.get('symbols') or ([raw['symbol']] if raw.get('symbol') else [])) & set(held)
        sec = set(raw.get('sectors') or [])
        mapped = direct or {s for s, r in held.items() if r.get('sector') in sec}
        if not mapped:
            continue
        key = headline.casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        weight = sum(held[s]['weight_pct'] for s in mapped)
        importance = raw.get('importance') or 'medium'
        materiality = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'routine': .5}.get(importance, 1)
        # Existing feeds provide category rules, not verified directional
        # interpretation. Never turn headline vocabulary into sentiment.
        interpretation = raw.get('interpretation') or {}
        group = 'Neutral / Informational'
        evidence = interpretation.get('evidence')
        if interpretation.get('verified_context') is True and evidence and interpretation.get('source_url') == url:
            group = {'positive': 'Positive Catalyst', 'negative': 'Potential Risk'}.get(interpretation.get('sentiment'), group)
        events.append({'id': hashlib.sha256((url+headline).encode()).hexdigest()[:20],
                       'headline': headline, 'source': source, 'url': url, 'published_at': date.isoformat(),
                       'symbols': sorted(mapped), 'mapping': 'company' if direct else 'sector context',
                       'category': raw.get('category') or 'Market development',
                       'materiality': importance, 'materiality_method': 'Source category rules; not a verified impact estimate',
                       'group': group, 'sentiment': interpretation.get('sentiment') if group != 'Neutral / Informational' else None,
                       'interpretation': evidence if group != 'Neutral / Informational' else 'Directional impact unverified; read the source for context.',
                       'exposure_pct': round(weight, 2),
                       'relevance': round(weight*materiality*math.exp(-max(0, age)/72), 3)})
    events.sort(key=lambda x: (-x['relevance'], x['id']))
    return {'events': events[:100], 'checked_at': now.isoformat() if status is not None else None, 'source_status': status or {},
            'method': 'Exposed portfolio weight × category materiality × exp(−age in hours / 72); seven-day window. Company mapping takes precedence over sector context.'}


def enrich(report, histories=None, news_items=None, news_status=None, now=None, scan=None):
    now = now or datetime.now(timezone.utc)
    rows, total = report['holdings'], report['total_value']
    score = weighted(rows, lambda r: r.get('composite'))
    confidence = weighted(rows, lambda r: (r.get('altaha_score_v4') or {}).get('position', {}).get('confidence'))
    cost_rows = [r for r in rows if r.get('cost') is not None]
    quality = {'scored_value_pct': score['coverage_pct'], 'scored_holdings': score['count'],
               'sector_value_pct': round(100*sum(r['value'] for r in rows if r.get('sector') != 'Unclassified')/total, 2) if total else None,
               'cost_holdings_pct': round(100*len(cost_rows)/len(rows), 2) if rows else None,
               'cost_value_pct': round(100*sum(r['value'] for r in cost_rows)/total, 2) if total else None,
               'priced_holdings': len(rows), 'requested_holdings': len(rows)+len(report['failed']),
               'valuation_complete': not report['failed'] and bool(rows),
               'score_as_of': (scan or {}).get('scanned_at'),
               'weighted_confidence_pct': round(confidence['value']*100, 1) if confidence['value'] is not None else None,
               'confidence_coverage_pct': confidence['coverage_pct'],
               'price_dates': sorted({str(r.get('price_as_of')) for r in rows if r.get('price_as_of')}),
               'price_sources': sorted({r.get('price_source', 'Unspecified') for r in rows}),
               'price_timestamp_coverage_pct': weighted(rows, lambda r: 1 if r.get('price_as_of') else None)['coverage_pct'],
               'warnings': []}
    if report['failed']:
        quality['warnings'].append('Market value, weights and exposure refer only to priced holdings. Unpriced exposure cannot be measured.')
    if score['value'] is None or (score['coverage_pct'] or 0) < 80:
        quality['warnings'].append('Less than 80% of priced capital has an Altaha Score; portfolio health is provisional.')
    if (quality['cost_value_pct'] or 0) < 100:
        quality['warnings'].append('P&L includes only positions with known purchase costs; unknown costs are never treated as zero.')
    score_date = stamp(quality['score_as_of'])
    if score_date is None:
        try:
            # Legacy scans use a human-readable server date without a zone.
            # Freshness is day-based; do not invent an exchange timestamp.
            legacy = str(quality['score_as_of']).split(' (')[0]
            score_date = datetime.strptime(legacy, '%d %b %Y, %H:%M').replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    quality['score_stale'] = score_date is None or (now.date()-score_date.date()).days > 7
    if quality['score_stale']:
        quality['warnings'].append('Score scan is older than seven days or its timestamp is unavailable.')
    if any(r.get('price_source') == 'Universe scan' for r in rows):
        quality['warnings'].append('Some valuations use dated universe-scan prices; these are not live quotes.')
    history = history_analytics(rows, histories, now)
    news = news_intelligence(rows, news_items, now, news_status)
    bench = {'name': 'Nifty 500', 'as_of': sectors.BENCH_WEIGHTS_ASOF, 'kind': 'approximate bundled proxy',
             'note': 'Manually maintained approximate sector weights; not live constituent weights. Momentum uses Nifty 50 and named sector-index proxies.'}
    existing = {s['sector']: s for s in report['sectors']}
    comparison = []
    for sector in sorted(set(sectors.BENCH_WEIGHTS) | set(existing)):
        s = existing.get(sector, {})
        bw = sectors.benchmark_weight(sector)
        pw = s.get('weight_pct', 0.)
        comparison.append({'sector': sector, 'weight_pct': pw, 'benchmark_weight_pct': bw,
                           'active_weight_pct': round(pw-bw, 2) if bw is not None else None,
                           'avg_score': s.get('avg_score'), 'momentum': (s.get('relative') or {}).get('3M')})
    factors = []
    families = ('quality', 'acceleration', 'financial_strength', 'momentum', 'participation', 'risk')
    labels = {'acceleration': 'Earnings & growth acceleration', 'participation': 'Volume participation',
              'risk': 'Risk resilience', 'financial_strength': 'Financial strength'}
    for family in families:
        val = weighted(rows, lambda r: (r.get('altaha_score_v4') or {}).get('position', {}).get('pillars', {}).get(family))
        factors.append({'key': family, 'label': labels.get(family, family.title()), **val, 'benchmark': None})
    factors.append({'key': 'technical', 'label': 'Technical strength (checks)', **weighted(rows, lambda r:r.get('technical')), 'benchmark': None})
    distribution = []
    for floor, label in BANDS:
        members = [r for r in rows if band(r.get('composite')) == label]
        distribution.append({'label': label, 'floor': floor, 'count': len(members), 'value': round(sum(r['value'] for r in members), 2),
                             'weight_pct': round(sum(r['weight_pct'] for r in members), 2)})
    unscored = [r for r in rows if r.get('composite') is None]
    distribution.append({'label': 'Unscored', 'floor': None, 'count': len(unscored), 'value': sum(r['value'] for r in unscored),
                         'weight_pct': round(sum(r['weight_pct'] for r in unscored), 2)})
    pol, conc = report['policy'], report['concentration']
    weak = sum(r['weight_pct'] for r in rows if r.get('composite') is not None and r['composite'] < pol['min_composite'])
    deep = sum(r['weight_pct'] for r in rows if number((r.get('technical_extras') or {}).get('drawdown_from_high')) is not None and float(r['technical_extras']['drawdown_from_high']) <= -pol['review_drawdown'])
    measures = [
        ('Single-stock concentration', conc['top1_pct'], pol['max_stock_pct'], 'above', 'A larger position has more influence on every portfolio move.'),
        ('Sector concentration', max((s['weight_pct'] for s in report['sectors'] if s['sector'] != 'Unclassified'), default=None), pol['max_sector_pct'], 'above', 'Shared industry shocks can affect several holdings together.'),
        ('Effective holdings', conc['effective_n'], pol['min_holdings'], 'below', 'Unequal weights reduce diversification relative to the raw holding count.'),
        ('Below-score-floor exposure', round(weak, 2) if score['count'] else None, 20, 'above', 'A material share of capital has weak measured research evidence.'),
        ('High-drawdown exposure', round(deep, 2) if any(number((r.get('technical_extras') or {}).get('drawdown_from_high')) is not None for r in rows) else None, 20, 'above', 'Capital in stocks well below their observed highs is exposed to continued trend weakness.'),
        ('Highly correlated exposure', history['correlation']['high_correlation_exposure_pct'] if any(c['value'] is not None for i,row in enumerate(history['correlation']['matrix']) for j,c in enumerate(row) if i != j) else None, 50, 'above', 'These holdings have historical pairwise correlation ≥0.8; their risks may overlap.')]
    rules = [{'name': name, 'measured': value, 'limit': limit, 'direction': direction,
              'triggered': value is not None and (value > limit if direction == 'above' else value < limit), 'why': why} for name, value, limit, direction, why in measures]
    hits = sum(r['triggered'] for r in rules)
    risk_grade = ('High' if hits >= 3 else 'Elevated' if hits >= 2 else 'Moderate' if hits else 'Low observed') if rows else 'Unavailable'
    provisional = not quality['valuation_complete'] or (score['coverage_pct'] or 0) < 80 or quality['score_stale'] or (quality['weighted_confidence_pct'] or 0) < 50
    health = 'Insufficient data' if score['value'] is None else 'High Risk' if hits >= 3 else 'Needs Attention' if score['value'] < 50 or hits >= 2 else 'Strong' if score['value'] >= 80 and hits == 0 else 'Healthy' if score['value'] >= 60 and hits <= 1 else 'Mixed'
    # Each ranking uses distinct, disclosed evidence; missing values are omitted
    # rather than imputed as bad fundamentals or a neutral score.
    groups = {'strength': [], 'weak': [], 'risk': [], 'monitor': []}
    h3 = {p['symbol']: p for p in history['windows']['3M']['points']}
    for r in rows:
        s = r.get('composite'); w = r['weight_pct']; sec = existing.get(r['sector'], {})
        pillars = (r.get('altaha_score_v4') or {}).get('position', {}).get('pillars', {})
        r['score_category'] = band(s)
        r['contribution_pct'] = round(100*r['pnl']/total, 3) if total and r.get('pnl') is not None else None
        r['news'] = [n for n in news['events'] if r['symbol'] in n['symbols']][:5]
        r['historical'] = h3.get(r['symbol'])
        facts = [f"{r['symbol']} represents {w:.1f}% of priced capital ({r['sector']})."]
        if s is not None:
            facts.append(f"Altaha Score is {s:.1f}/100 ({band(s).lower()}), from the universe scan dated {quality['score_as_of'] or 'unknown'}.")
        else:
            facts.append('No comparable Altaha v4 universe score is available.')
        for field, label in [('technical', 'Technical checks'), ('fundamental', 'Fundamental checks')]:
            if r.get(field) is not None:
                facts.append(f"{label} score {r[field]:.1f}/100.")
        helped = (r.get('altaha_score_v4') or {}).get('what_helped') or []
        hurt = (r.get('altaha_score_v4') or {}).get('what_hurt') or []
        for entries, prefix in [(helped, 'Strongest factor'), (hurt, 'Weakest factor')]:
            if entries and entries[0].get('explanation'):
                facts.append(prefix+': '+entries[0]['explanation']+'.')
        if w > pol['max_stock_pct']:
            facts.append(f"Its size exceeds your {pol['max_stock_pct']:g}% stock limit, increasing dependence on this company.")
        rel = number((sec.get('relative') or {}).get('3M'))
        if rel is not None:
            facts.append(f"The sector index proxy is {rel:+.1f} percentage points relative to Nifty 50 over 3M.")
        if r['news']:
            facts.append(f"{len(r['news'])} sourced recent developments merit review at this position size; direction is unverified unless stated.")
        r['altaha_view'] = ' '.join(facts)
        r['view_evidence'] = ['weight_pct', 'composite', 'score_as_of', 'technical', 'fundamental', 'altaha_score_v4.factor_ledger', 'news']
        def entry(priority, reasons):
            return {'symbol': r['symbol'], 'weight_pct': w, 'score': s, 'priority': round(priority, 3), 'reasons': reasons}
        if s is not None and s >= 70:
            support = sum(max(0, number(v)-50)/100 for v in [r.get('technical'), pillars.get('quality'), pillars.get('momentum')] if number(v) is not None)
            groups['strength'].append(entry(w*s/100*(1+support), [f'Score {s:.1f}; {w:.1f}% capital', 'Quality, momentum and technical support included where measured']))
        weakness = sum(max(0, 50-number(v))/100 for v in [s, r.get('technical'), r.get('fundamental')] if number(v) is not None)
        if weakness:
            groups['weak'].append(entry(w*weakness, ['Weight × measured shortfall below 50 across score, technical and fundamental checks']))
        hist = h3.get(r['symbol'], {})
        risk_parts = [w/pol['max_stock_pct'], weakness]
        if hist.get('volatility_pct') is not None: risk_parts.append(hist['volatility_pct']/100)
        if hist.get('max_drawdown_pct') is not None: risk_parts.append(abs(hist['max_drawdown_pct'])/100)
        if any(r['symbol'] in (p['a'],p['b']) for p in history['correlation']['high_pairs']): risk_parts.append(.5)
        risk_events = [n for n in r['news'] if n['group'] == 'Potential Risk']
        groups['risk'].append(entry(w*sum(risk_parts)+sum(n['relevance'] for n in risk_events)/10, ['Concentration + measured weakness, volatility, drawdown, correlation and verified risk events when available; heuristic priority, not variance attribution']))
        material = sum(n['relevance'] for n in r['news'])
        groups['monitor'].append(entry(w+material+ (w*.5 if r.get('technical') is not None and r['technical'] < 40 else 0), [f'{w:.1f}% capital; {len(r["news"])} mapped developments', 'Position weight + event relevance + major technical weakness']))
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda r:(-r['priority'], r['symbol']))[:5]
    for s in report['sectors']:
        members = sorted([r for r in rows if r['sector'] == s['sector']], key=lambda r:-r['weight_pct'])
        scored = [r for r in members if r.get('composite') is not None]
        s['best'] = max(scored, key=lambda r:r['composite'])['symbol'] if scored else None
        s['weakest'] = min(scored, key=lambda r:r['composite'])['symbol'] if scored else None
        s['score_coverage_pct'] = weighted(members, lambda r:r.get('composite'))['coverage_pct']
        s['news'] = [n for n in news['events'] if set(s['symbols']) & set(n['symbols'])][:3]
        s['benchmark_weight_pct'] = sectors.benchmark_weight(s['sector'])
        s['active_weight_pct'] = round(s['weight_pct']-s['benchmark_weight_pct'],2) if s['benchmark_weight_pct'] is not None else None
        narrative = [f"{s['sector']} carries {s['weight_pct']:.1f}% of priced capital across {s['count']} holdings, led by {', '.join(r['symbol'] for r in members[:2])}."]
        if s['active_weight_pct'] is not None:
            narrative.append(f"The active weight is {s['active_weight_pct']:+.1f} percentage points versus the approximate Nifty 500 sector mix ({bench['as_of']}).")
        if s.get('avg_score') is not None: narrative.append(f"Its value-weighted score is {s['avg_score']:.1f}, covering {s['score_coverage_pct']:.1f}% of sector value.")
        if s.get('state'):
            narrative.append(f"The {s.get('index_name') or 'sector'} proxy is {s['state'].lower()} on the stated momentum windows.")
        narrative.append(f"A hypothetical 10% equal decline in these holdings changes priced portfolio value by −{s['weight_pct']*.1:.2f}%, before other effects.")
        s['interpretation'] = ' '.join(narrative)
    scenarios = [{'name':'All priced holdings −5%', 'exposure_pct':100., 'shock_pct':-5., 'impact_pct':-5., 'impact_inr':round(-total*.05,2), 'arithmetic':'100% × −5% = −5%'}] if total else []
    for s in report['sectors']:
        scenarios.append({'name':s['sector']+' −10%', 'exposure_pct':s['weight_pct'], 'shock_pct':-10.,
                          'impact_pct':round(-s['weight_pct']*.1,3), 'impact_inr':round(-s['value']*.1,2),
                          'arithmetic':f"{s['weight_pct']:.2f}% × −10% = −{s['weight_pct']*.1:.3f}%"})
    sentences = []
    if rows:
        sentences.append(f"The portfolio's {len(rows)} priced holdings have the concentration of approximately {conc['effective_n']:.1f} equally weighted positions; the top three account for {conc['top3_pct']:.1f}% of capital.")
        active = [s for s in comparison if s['active_weight_pct'] is not None]
        if active:
            over, under = max(active,key=lambda s:s['active_weight_pct']), min(active,key=lambda s:s['active_weight_pct'])
            sentences.append(f"{over['sector']} is the largest active sector weight ({over['active_weight_pct']:+.1f} pp), while {under['sector']} is the smallest ({under['active_weight_pct']:+.1f} pp), against approximate Nifty 500 weights dated {bench['as_of']}.")
        sentences.append(f"The weighted Altaha Score is {score['value']:.1f}/100 on {score['coverage_pct']:.1f}% of priced capital." if score['value'] is not None else 'A weighted Altaha Score cannot be calculated because scored capital is unavailable.')
        triggered = [r['name'].lower() for r in rules if r['triggered']]
        sentences.append(f"Observed risk is {risk_grade.lower()}, with flagged measures in {', '.join(triggered)}." if triggered else 'No available risk measure breaches the disclosed thresholds; unmeasured risks remain unknown.')
        if cost_rows:
            top = max(cost_rows, key=lambda r:abs(r['pnl']))
            sentences.append(f"{top['symbol']} has the largest absolute unrealised P&L contribution (₹{top['pnl']:,.0f}); cost coverage is {quality['cost_value_pct']:.1f}% of priced capital.")
        sentences.append(f"{len(news['events'])} sourced developments match the portfolio within seven days; prominence reflects exposure, materiality and recency." if news['events'] else 'The available feed cache contains no matching sourced developments within seven days; this does not establish an absence of events.')
        sentences.append(f"Portfolio health is {health.lower()}{' and provisional because coverage, confidence or freshness is incomplete' if provisional else ''}.")
    else:
        sentences = ['No holdings could be valued. Review the individual errors and retry; portfolio metrics are unavailable.']
    report.update({'intelligence_version': VERSION, 'generated_at': now.isoformat(), 'data_quality': quality,
                   'weighted_score': score['value'], 'grade': ('—' if score['value'] is None else 'A' if score['value'] >= 72 else 'B+' if score['value'] >= 60 else 'B' if score['value'] >= 50 else 'C' if score['value'] >= 40 else 'D'), 'health': {'label':health, 'provisional':provisional},
                   'risk': {'grade':risk_grade, 'rules':rules, 'triggered_count':hits, 'method':'0 triggers: Low observed; 1: Moderate; 2: Elevated; 3+: High. Missing inputs are unassessed. Risk is not a loss probability.',
                            'unassessed':['Market beta', 'Oil / FX / interest-rate sensitivity', 'Official market-cap classification']},
                   'benchmark':bench, 'sector_comparison':comparison, 'factor_exposure':factors,
                   'score_distribution':distribution, 'history':history, 'developments':news,
                   'groups':groups, 'scenarios':scenarios, 'committee_summary':' '.join(sentences),
                   'summary':{'text':' '.join(sentences)},
                   'snapshot_basis':{'version':VERSION, 'score_method':'v4-position', 'benchmark_as_of':bench['as_of']}})
    return json_safe(report)
