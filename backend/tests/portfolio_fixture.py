"""Generate synthetic QA data; never imported by the production API."""
import json
from pathlib import Path
from test_portfolio_intelligence import row, frame, report, NOW


def fixture(count=12):
    names=['HDFCBANK','RELIANCE','TCS','ICICIBANK','LT','INFY','SUNPHARMA','ITC','TATAMOTORS','NTPC','BHARTIARTL','TATASTEEL']
    sectors=['Financial Services','Energy','Technology','Financial Services','Industrials','Technology','Healthcare','Consumer Defensive','Consumer Cyclical','Utilities','Communication Services','Basic Materials']
    weights=[24,16,12,10,8,7,6,5,4,3,3,2]
    rows=[]
    for i in range(count):
        sym=names[i] if i < len(names) else 'TEST'+str(i)
        w=weights[i] if i < len(weights) else 1
        r=row(sym,w*25000,w*23000 if i != 8 else None,[78,68,75,82,72,48,79,61,35,55,65,42][i%12],sectors[i%12])
        r.update(score_as_of=NOW.isoformat(),price_checked_at=NOW.isoformat(),trend='Above 200-day average',
                 moving_averages={'20':2.3,'50':4.1,'200':8.5}, technical_extras={'drawdown_from_high':-8.2,'range_position':72})
        r['altaha_score_v4']['position']['pillars'].update(momentum=55,financial_strength=65,acceleration=62,risk=60,participation=70)
        rows.append(r)
    histories={r['symbol']:frame(seed=i+1) for i,r in enumerate(rows)}
    mom={'available':True,'measured_at':NOW.isoformat(),'sectors':[{'sector':s,'state':'Improving','index_name':'Test index',
         'relative':{'3M':4.2},'returns':{'1M':2.1,'3M':7.2,'6M':11.4}} for s in set(sectors)]}
    news=[{'headline':'TEST FIXTURE: HDFC Bank quarterly update','source':'Test exchange feed','url':'https://example.com/test-filing',
           'published_at':'2026-09-10T10:00:00Z','symbols':['HDFCBANK'],'importance':'high'}]
    r=report(rows,histories=histories,news_items=news,sector_momentum=mom)
    r['stage']='Complete'
    return r


if __name__=='__main__':
    import sys
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    (out/'portfolio-12.json').write_text(json.dumps(fixture()))
    (out/'portfolio-50.json').write_text(json.dumps(fixture(50)))
