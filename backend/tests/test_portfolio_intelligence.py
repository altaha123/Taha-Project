"""Network-free regressions; runs with unittest or the existing pytest CI."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import types
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio
import portfolio_intelligence as pi

NOW = datetime(2026,9,10,12,tzinfo=timezone.utc)
SCAN = {'scanned_at':'2026-09-10T09:00:00+00:00'}


def row(symbol='A', value=100, cost=80, score=70, sector='Energy'):
    return dict(symbol=symbol, name=symbol, qty=10, price=value/10, value=value, cost=cost,
                buy_price=cost/10 if cost else None, composite=score, sector=sector,
                technical=65, fundamental=70, price_as_of=NOW.isoformat(), price_source='Test fixture',
                altaha_score_v4={'position':{'confidence':.8,'pillars':{'quality':score}},'factor_ledger':[]})


def report(rows, **kwargs):
    return portfolio.build_report(rows, SCAN, now=NOW, **kwargs)


def frame(n=280, seed=1):
    rng=np.random.default_rng(seed)
    close=100*np.exp(np.cumsum(rng.normal(.0004,.01,n)))
    df=pd.DataFrame({'Close':close},index=pd.bdate_range(end='2026-09-10',periods=n))
    df.attrs['adjustment']='adjusted'
    return df


class ArithmeticTests(unittest.TestCase):
    def test_partial_cost_never_counts_unknown_cost_as_profit(self):
        r=report([row(),row('B',200,None,50)])
        self.assertEqual(r['total_pnl'],20)
        self.assertEqual(r['total_pnl_pct'],25)
        self.assertEqual(r['total_cost'],80)
        self.assertAlmostEqual(r['data_quality']['cost_value_pct'],33.33)
        self.assertAlmostEqual(r['holdings'][1]['contribution_pct'],6.667)

    def test_weighted_score_coverage_and_zero_score(self):
        r=report([row('A',900,score=80),row('B',100,score=0),row('C',1000,score=None)])
        self.assertEqual(r['weighted_score'],72)
        self.assertEqual(r['data_quality']['scored_value_pct'],50)
        self.assertEqual(r['score_distribution'][-1]['weight_pct'],50)
        self.assertEqual(sum(b['count'] for b in r['score_distribution']),3)
        self.assertTrue(r['health']['provisional'])

    def test_failed_holding_retains_partial_portfolio(self):
        r=report([row(),{'symbol':'FAIL','error':'unavailable','value':None}])
        self.assertEqual(r['total_value'],100)
        self.assertEqual(r['failed'][0]['symbol'],'FAIL')
        self.assertFalse(r['data_quality']['valuation_complete'])

    def test_all_failed_no_fake_metrics(self):
        r=report([{'symbol':'A','error':'unavailable','value':None}])
        self.assertIsNone(r['weighted_score'])
        self.assertIsNone(r['total_pnl'])
        self.assertIsNone(r['concentration']['hhi'])
        self.assertEqual(r['risk']['grade'],'Unavailable')

    def test_nonfinite_values_and_policy_are_rejected(self):
        r=report([row(score=float('nan')),row('BAD',float('inf'))])
        self.assertIsNone(r['weighted_score'])
        self.assertEqual(len(r['failed']),1)
        json.dumps(r,allow_nan=False)
        self.assertEqual(portfolio.clean_policy({'max_stock_pct':float('nan')})['max_stock_pct'],15)

    def test_hhi_uses_unrounded_weights(self):
        rows=[row(str(i),1) for i in range(50)]
        r=report(rows)
        self.assertEqual(r['concentration']['effective_n'],50)
        self.assertEqual(r['concentration']['hhi'],.02)
        self.assertEqual(r['concentration']['top5_pct'],10)

    def test_cap_arithmetic_reaches_limit_with_whole_shares(self):
        r=dict(qty=100,price=10,value=1000)
        out=portfolio._shares_to_cap(r,15,4000)
        self.assertEqual(out['shares'],48)
        self.assertLessEqual(out['resulting_weight_pct'],15)

    def test_legacy_scan_timestamp_is_not_falsely_stale(self):
        result=portfolio.build_report([row()],{'scanned_at':'10 Sep 2026, 09:15'},now=NOW)
        self.assertFalse(result['data_quality']['score_stale'])

    def test_input_is_not_mutated(self):
        rows=[row()];saved=deepcopy(rows);report(rows);self.assertEqual(rows,saved)

    def test_benchmark_survives_momentum_outage_includes_unheld(self):
        r=report([row()],sector_momentum={'available':False})
        finance=next(s for s in r['sector_comparison'] if s['sector']=='Financial Services')
        self.assertEqual(finance['weight_pct'],0)
        self.assertEqual(finance['active_weight_pct'],-30.4)
        self.assertEqual(r['benchmark']['kind'],'approximate bundled proxy')

    def test_scenarios_are_exposure_arithmetic(self):
        r=report([row('A',300),row('B',700,sector='Technology')])
        energy=next(s for s in r['scenarios'] if s['name']=='Energy −10%')
        self.assertEqual(energy['impact_pct'],-3)
        self.assertEqual(energy['impact_inr'],-30)

    def test_factor_denominator_and_missing_benchmark(self):
        a,b=row('A',100,score=80),row('B',300,score=None)
        r=report([a,b]);q=next(f for f in r['factor_exposure'] if f['key']=='quality')
        self.assertEqual(q['value'],80)
        self.assertEqual(q['coverage_pct'],25)
        self.assertIsNone(q['benchmark'])

    def test_contributors_rank_rupees_not_percentage_returns(self):
        r=report([row('SMALL',130,100),row('LARGE',1100,1000)])
        self.assertEqual(r['contributors'][0]['symbol'],'LARGE')

    def test_no_automatic_exit_and_distinct_rankings(self):
        r=report([row('BIG',900,score=80),row('WEAK',100,score=25)])
        self.assertEqual(r['groups']['strength'][0]['symbol'],'BIG')
        self.assertEqual(r['groups']['weak'][0]['symbol'],'WEAK')
        self.assertEqual(r['groups']['risk'][0]['symbol'],'BIG')
        self.assertNotIn('Exit ',r['committee_summary'])


class HistoryTests(unittest.TestCase):
    def test_windows_require_enough_history(self):
        rows=[dict(row(),weight_pct=100)]
        h=pi.history_analytics(rows,{'A':frame(64)},NOW)
        self.assertEqual(len(h['windows']['3M']['points']),1)
        self.assertEqual(h['windows']['6M']['points'],[])

    def test_volatility_formula(self):
        df=frame();h=pi.history_analytics([dict(row(),weight_pct=100)],{'A':df},NOW)
        expected=df.Close.iloc[-64:].pct_change().dropna().std(ddof=1)*np.sqrt(252)*100
        self.assertAlmostEqual(h['windows']['3M']['points'][0]['volatility_pct'],round(expected,2))

    def test_unverified_and_stale_histories_withheld(self):
        df=frame();df.attrs.clear()
        h=pi.history_analytics([dict(row(),weight_pct=100)],{'A':df},NOW)
        self.assertEqual(h['windows']['1M']['points'],[])
        df.attrs['adjustment']='adjusted';df.index-=pd.Timedelta(days=20)
        h=pi.history_analytics([dict(row(),weight_pct=100)],{'A':df},NOW)
        self.assertEqual(h['correlation']['symbols'],[])

    def test_overlap_correlations_and_no_fill(self):
        a=frame();b=a.copy();b.iloc[-20:-10]=np.nan
        rows=[dict(row('A'),weight_pct=50),dict(row('B'),weight_pct=50)]
        h=pi.history_analytics(rows,{'A':a,'B':b},NOW)
        cell=h['correlation']['matrix'][0][1]
        self.assertEqual(cell['observations'],115)
        self.assertEqual(cell['value'],1.)
        self.assertEqual(h['windows']['1M']['points'][0]['symbol'],'A')

    def test_short_overlap_and_constant_returns_no_correlation(self):
        a,b=frame(61),frame(60)
        h=pi.history_analytics([dict(row('A'),weight_pct=50),dict(row('B'),weight_pct=50)],{'A':a,'B':b},NOW)
        self.assertIsNone(h['correlation']['matrix'][0][1]['value'])
        b=frame();b['Close']=100
        h=pi.history_analytics([dict(row(),weight_pct=100)],{'A':b},NOW)
        self.assertIsNone(h['correlation']['matrix'][0][0]['value'])


class NewsTests(unittest.TestCase):
    def event(self,**kw):
        return {'headline':'Company raises ₹5,000 crore','source':'NSE filing','url':'https://nseindia.com/filing.pdf',
                'published_at':'2026-09-10T10:00:00Z','symbols':['A'],'importance':'high',**kw}

    def test_ambiguous_fundraising_is_not_positive_sentiment(self):
        n=pi.news_intelligence([dict(row(),weight_pct=100)],[self.event()],NOW)
        self.assertEqual(n['events'][0]['group'],'Neutral / Informational')
        self.assertIsNone(n['events'][0]['sentiment'])

    def test_require_source_date_and_url_and_filter_stale_future(self):
        items=[self.event(url='javascript:alert(1)'),self.event(source=None),self.event(published_at='2026-08-01'),self.event(published_at='2027-01-01')]
        self.assertEqual(pi.news_intelligence([dict(row(),weight_pct=100)],items,NOW)['events'],[])

    def test_weight_times_materiality_times_recency(self):
        rows=[dict(row('A'),weight_pct=90),dict(row('B'),weight_pct=10)]
        n=pi.news_intelligence(rows,[self.event(symbols=['B'],headline='Small holding event'),self.event()],NOW)
        self.assertEqual(n['events'][0]['symbols'],['A'])
        self.assertAlmostEqual(n['events'][0]['relevance']/n['events'][1]['relevance'],9,places=2)

    def test_sector_mapping_and_deduplication(self):
        rows=[dict(row('A'),weight_pct=90),dict(row('B',sector='Technology'),weight_pct=10)]
        ev=self.event(symbols=[],sectors=['Energy'])
        n=pi.news_intelligence(rows,[ev,dict(ev)],NOW)
        self.assertEqual(len(n['events']),1)
        self.assertEqual(n['events'][0]['mapping'],'sector context')
        self.assertEqual(n['events'][0]['exposure_pct'],90)

    def test_verified_context_requires_matching_source(self):
        ev=self.event(interpretation={'verified_context':True,'source_url':'https://nseindia.com/filing.pdf','sentiment':'negative','evidence':'Context verified against source'})
        self.assertEqual(pi.news_intelligence([dict(row(),weight_pct=100)],[ev],NOW)['events'][0]['group'],'Potential Risk')


# Compile the actual request/worker functions into a network-free namespace.
# This keeps unittest runnable without FastAPI; pytest CI also imports main.
def wire():
    source=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text())
    names={'_pf_inputs','_pf_row','_analyse_holding','portfolio_status'}
    nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in names]
    for n in nodes:n.decorator_list=[]
    class HTTPException(Exception):
        def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail
    env={'PI':pi,'sectors':pi.sectors,'MAX_HOLDINGS':50,'HTTPException':HTTPException,'datetime':datetime,'timezone':timezone,
         '_pf_lock':threading.Lock(),'_pf_jobs':{},'time':__import__('time')}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<portfolio production functions>','exec'),env)
    return types.SimpleNamespace(**env)


class WiringTests(unittest.TestCase):
    def test_duplicate_lots_are_coalesced(self):
        m=wire();rows=m._pf_inputs({'holdings':[{'symbol':'A.NS','qty':10,'buy_price':100},{'symbol':'A','qty':20,'buy_price':200}]})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['qty'],30);self.assertAlmostEqual(rows[0]['buy_price'],5000/30)

    def test_incomplete_lot_cost_is_never_zero(self):
        rows=wire()._pf_inputs({'holdings':[{'symbol':'A','qty':10,'buy_price':100},{'symbol':'A','qty':20}]})
        self.assertIsNone(rows[0]['buy_price'])

    def test_invalid_input_is_400(self):
        m=wire()
        for item in [None,{'symbol':'A','qty':'NaN'},{'symbol':'A','qty':0},{'symbol':'A','qty':1,'buy_price':-1},{'symbol':'A.BO','qty':1}]:
            with self.assertRaises(m.HTTPException) as cm:m._pf_inputs({'holdings':[item]})
            self.assertEqual(cm.exception.status_code,400)

    def test_new_quote_updates_value_but_does_not_relabel_score_as_live(self):
        m=wire();r=m._pf_row({'symbol':'A','qty':10,'buy_price':5},{'price':8}, {'ltp':10},'2026-08-01')
        self.assertEqual(r['value'],100);self.assertEqual(r['score_as_of'],'2026-08-01');self.assertIsNone(r['price_as_of'])

    def test_scoring_failure_retains_valuation(self):
        m=wire();g=m._analyse_holding.__globals__;df=frame();df.attrs['price_source']='Yahoo Finance'
        g['resolve']=lambda symbol:(symbol,None,df)
        g['technical_score']=lambda _: (_ for _ in ()).throw(ValueError())
        g['fundamentals']=lambda *args: (_ for _ in ()).throw(ValueError())
        r=m._analyse_holding({'symbol':'A','qty':10,'buy_price':5},m._pf_row({'symbol':'A','qty':10,'buy_price':5},{'price':8}))
        self.assertGreater(r['value'],0);self.assertIsNone(r['error']);self.assertIn('Technical scoring',r['warnings'][0])

    def test_status_includes_partial_report(self):
        m=wire();m._pf_jobs['job']={'status':'running','report':{'total_value':100},'revision':1}
        self.assertEqual(m.portfolio_status('job')['report']['total_value'],100)


if __name__=='__main__':unittest.main()
