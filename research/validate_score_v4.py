"""Reproducible representative validation. --live adds read-only NSE checks.

Synthetic examples test arithmetic, not predictive performance. No production
write, scan or deployment is triggered. Live statements reuse the XML cache.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import factors as F
import multifactor as M

CASES=[('RELIANCE','Energy','Oil & Gas Refining & Marketing',None),
       ('TCS','Technology','Information Technology Services',None),
       ('HDFCBANK','Financial Services','Banks - Private',None),
       ('TATASTEEL','Basic Materials','Steel',None),
       ('HINDUNILVR','Consumer Defensive','Household & Personal Products',None),
       ('NTPC','Utilities','Utilities - Regulated Electric',None),
       ('DLF','Real Estate','Real Estate - Development',None),
       ('PAYTM','Technology','Software - Infrastructure',-1.)]


def synthetic():
    rows=[]
    for group,(symbol,sector,industry,eps) in enumerate(CASES):
        for i in range(30):
            factors={n:float((i*(j+1)+group)%31) for j,n in enumerate(F.SPEC)}
            row=dict(symbol=symbol if i==15 else f'{symbol}_PEER_{i}',sector=sector,industry=industry,
                     trailing_eps=eps,market_cap=(i+1)*1e9, factors=factors,
                     data_quality=dict(as_of='2026-09-09',period_age_days=71,history_quarters=16,source_valid=True))
            rows.append(row)
    import time
    before=time.perf_counter(); result=M.rank(rows,'position');elapsed=time.perf_counter()-before
    selected=[]
    for symbol,_,_,_ in CASES:
        r=next(r for r in result['rows'] if r['symbol']==symbol)
        assert all(0<=r[h+'_score']<=100 for h in ('trade','position','invest'))
        selected.append(dict(symbol=symbol,model=r['altaha_score_v4']['business_model'],
            raw=round(r['raw_factor_score'],2), confidence=round(r['confidence_score'],3),
            final=round(r['factor_score'],2),trade=round(r['trade_score'],2),invest=round(r['invest_score'],2),
            unavailable=r['altaha_score_v4']['data_quality']['missing_factors']))
    return dict(kind='SYNTHETIC arithmetic examples; not actual company scores or a backtest',
                universe=240,elapsed_seconds=round(elapsed,3),rows=selected)


def live():
    import xbrl
    result=[]
    for symbol,sector,industry,eps in CASES:
        qs=xbrl.scoring_statements(symbol)
        raw=F.compute(None,quarters=qs)
        dq=F.data_quality(qs)
        model=M._model(dict(sector=sector,industry=industry,trailing_eps=(qs[0].get('eps_basic') if qs else None)))['key']
        eligible={n:raw[n] for n in F.SPEC if n not in F.PRICE_FACTORS and F.eligible(n,model)}
        result.append(dict(symbol=symbol,model=model,quality=dq,fundamentals=eligible))
        print(json.dumps(result[-1],allow_nan=False),flush=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--output')
    args=parser.parse_args(); result={'synthetic':synthetic()}
    if args.live:result['live']=live()
    if args.output:Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    else:print(json.dumps(result,indent=2,allow_nan=False))
