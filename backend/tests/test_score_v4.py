"""v4 behavioural regressions: PIT, peer economics, confidence and integration."""
import copy
import datetime as dt
import json
import numpy as np
import pytest
import factors as F
import multifactor as M
import profiles as P
import xbrl
from conftest import ohlcv, ramp


def quarters(n=16):
    rows = []
    for i in range(n):
        m = 2022*12+11 + i*3
        year, month = m//12, m%12+1
        import calendar
        end = dt.date(year, month, calendar.monthrange(year,month)[1])
        start = dt.date(year, month-2, 1)
        rows.append(dict(period={"from":start.isoformat(),"to":end.isoformat()},
            filed_at=(end+dt.timedelta(days=35)).isoformat(), consolidated=True,
            source_url=f"https://nsearchives.nseindia.com/{i}.xml", regime="integrated" if i>=8 else "legacy",
            pat=100+i*i, eps_basic=1+i*.1+i*i*.005, revenue=1000+i*50+i*i,
            ebitda_margin_pct=10+i*.3, roa_annualised_pct=5+i*.1,
            debt_equity=.5, interest_cover=3+i*.1, other_income=1, pbt=100))
    return list(reversed(rows))


ASOF = '2027-01-15'


def universe(n=40):
    return [dict(symbol=f"S{i:03d}", sector="Technology", industry="Software services",
                 market_cap=1e9*(i+1), factors={k:float(i) for k in F.SPEC},
                 data_quality=dict(as_of=ASOF,period_age_days=90,history_quarters=16,source_valid=True)) for i in range(n)]


def test_cutoff_and_revision_are_applied_before_selection():
    qs=quarters()
    original=copy.deepcopy(qs[0]); revision={**original,'pat':9999,'filed_at':'2027-02-01'}
    ks=F.known_quarters([revision]+qs,ASOF)
    assert ks[0]['pat']==original['pat']
    assert F.known_quarters([revision]+qs,'2027-03-01')[0]['pat']==9999
    assert F.known_quarters(qs,qs[0]['period']['to'])[0]['period'] != qs[0]['period']
    # Late revision of an old period doesn't become the latest quarter.
    old={**qs[-1],'filed_at':'2027-01-01'}
    assert F.known_quarters([old]+qs,ASOF)[0]['period']==qs[0]['period']


def test_future_period_bad_cutoff_and_accounting_basis():
    qs=quarters()
    assert not F.known_quarters([{**qs[0],'filed_at':'2020-01-01'}],ASOF)
    with pytest.raises(ValueError): F.known_quarters(qs,'bogus')
    standalone={**qs[0],'consolidated':False,'pat':99999}
    ks=F.known_quarters([standalone]+qs,ASOF)
    assert all(q['consolidated'] for q in ks)
    assert F.known_quarters([standalone]+qs,ASOF,False)==[standalone]


def test_matching_acceleration_formulas_and_missing_previous_quarter():
    qs=quarters(); now,prev=qs[:2]; py,ppy=qs[4:6]
    out=F.fundamental_factors(qs,100,ASOF)
    for factor,key in [('eps_acceleration','eps_basic'),('revenue_acceleration','revenue')]:
        expected=F._growth(now[key],py[key])-F._growth(prev[key],ppy[key])
        assert out[factor]==pytest.approx(expected)
    expected=(now['ebitda_margin_pct']-py['ebitda_margin_pct'])-(prev['ebitda_margin_pct']-ppy['ebitda_margin_pct'])
    assert out['margin_acceleration']==pytest.approx(expected)
    missing=F.fundamental_factors([qs[0]]+qs[2:],100,ASOF)
    assert missing['eps_acceleration'] is None
    assert missing['earnings_yield'] is None


def test_surprise_excludes_current_change_from_scale_and_handles_losses():
    qs=quarters(); qs[0]['eps_basic']=-3
    out=F.fundamental_factors(qs,100,ASOF)
    deltas=[qs[j]['eps_basic']-qs[j+4]['eps_basic'] for j in range(9)]
    hist=np.array(deltas[1:]); med=np.median(hist)
    want=(deltas[0]-med)/(1.4826*np.median(abs(hist-med)))
    assert out['earnings_surprise']==pytest.approx(want)
    assert out['eps_acceleration'] is None
    assert F.fundamental_factors(qs[:12],100,ASOF)['earnings_surprise'] is None
    for q in qs: q['eps_basic']=1
    assert F.fundamental_factors(qs,100,ASOF)['earnings_surprise'] is None


def test_consistency_bounded_changes_survive_loss_swings():
    qs=quarters()
    for i,q in enumerate(qs):q['pat']=(-1)**(i//3)*(.000001 if i%3 else 100)
    out=F.fundamental_factors(qs,100,ASOF)
    assert -220 < out['earnings_consistency'] <=0
    assert F._growth(100,1e-12) is None
    assert F._growth(10,-10) is None
    assert F._growth(float('inf'),1) is None
    assert F.fundamental_factors(qs[:7],100,ASOF)['earnings_consistency'] is None


def test_stale_withholds_every_fundamental_and_reduces_confidence():
    out=F.compute(ohlcv(ramp(100,200,300)),quarters(),100,'2029-01-01')
    assert out['_fundamentals_stale']
    assert all(out[n] is None for n in F.SPEC if n not in F.PRICE_FACTORS)
    rows=universe(); before=M.rank(rows)['rows'][-1]
    rows[-1]['data_quality']['stale']=True
    after=M.rank(rows)['rows'][-1]
    assert after['confidence_score'] < before['confidence_score']
    assert abs(after['factor_score']-50) < abs(before['factor_score']-50)


def test_percentiles_ties_nonfinite_winsor_and_permutation():
    assert M._percentiles([7]*10)==[50.]*10
    assert M._percentiles([1,2,3])==[None]*3
    assert M._percentiles([1]*9+[float('nan')])==[None]*10
    xs=list(range(100))+[1e90]
    p=M._percentiles(xs)
    assert p[-1]==p[-2] # winsorised top tail shares a rank
    assert min(p)>=0 and max(p)<=100
    assert M._percentiles(xs[::-1])==p[::-1]


def test_missing_shrinks_to_neutral_and_confidence_arithmetic():
    rows=universe(); rows[-1]['factors']={'momentum_12_1':10000}
    out=M.rank(rows)['rows'][-1]
    assert out['raw_factor_score']>90
    assert 50 < out['factor_score'] <65
    assert out['factor_score']==pytest.approx(50+(out['raw_factor_score']-50)*out['confidence_score'])
    rows[-1]['factors']={}
    empty=M.rank(rows)['rows'][-1]
    assert empty['factor_score']==50 and empty['confidence_score']==0
    assert all(e['percentile'] is None for e in empty['factor_ledger'])


def test_peer_fallback_sector_then_size_then_universe():
    rows=universe()
    # Tiny compounder bucket but adequate broad sector (emerging override).
    for r in rows[:35]:r['trailing_eps']=-1
    entry=M.rank(rows)['rows'][-1]['factor_ledger'][0]
    assert ':sector:' in entry['peer_group'] and entry['peer_count']==40
    for i,r in enumerate(rows):r['sector']=f'Sector{i}';r['industry']=''
    # General model is a valid broad fallback, so fragment models explicitly with a lender.
    rows[-1]['industry']='Bank'
    out=M.rank(rows)['rows'][-1]
    entry=out['factor_ledger'][0]
    assert ':size:' in entry['peer_group']
    for r in rows:r['market_cap']=None
    entry=M.rank(rows)['rows'][-1]['factor_ledger'][0]
    assert ':universe:' in entry['peer_group']


def test_lender_exclusions_and_no_corporate_accounting_fallback():
    rows=universe();rows[-1].update(sector='Financial Services',industry='Bank')
    out=M.rank(rows)['rows'][-1];led={e['factor']:e for e in out['factor_ledger']}
    for n in ('low_leverage','margin_level','margin_trend','margin_acceleration','interest_coverage','earnings_yield'):
        assert led[n]['applicable'] is False and led[n]['percentile'] is None
    assert led['return_on_assets']['percentile'] is None # one lender never ranked against software
    assert 'capital adequacy' in ' '.join(out['altaha_score_v4']['data_quality']['confidence_reasons'])


def test_cyclical_does_not_get_trailing_cheapness_votes_and_utility_leverage():
    rows=universe()
    for r in rows:r.update(sector='Basic Materials',industry='Steel')
    before=M.rank(rows)['rows'][-1]
    rows[-1]['factors']['earnings_yield']=1e10
    after=M.rank(rows)['rows'][-1]
    assert before['factor_score']==after['factor_score']
    assert not next(e for e in after['factor_ledger'] if e['factor']=='earnings_yield')['applicable']
    assert F.fundamental_factors(quarters()[:11],100,ASOF)['cycle_earnings_yield'] is None
    rows[-1].update(sector='Utilities',industry='Utilities')
    assert not next(e for e in M.rank(rows)['rows'][-1]['factor_ledger'] if e['factor']=='low_leverage')['applicable']


def test_registry_groups_deduplicate_and_all_horizons_bounded():
    rows=universe(); a=M.rank(rows)['rows'][-1]
    for r in rows:r['factors']['trend_quality']=None
    b=M.rank(rows)['rows'][-1]
    assert a['families']['momentum']==b['families']['momentum']
    assert a['confidence_score']==b['confidence_score'] # duplicate does not increase confidence
    for h in P.V4_WEIGHTS:
        s=b['altaha_score_v4'][h]
        assert 0<=s['final_score']<=100 and 0<=s['confidence']<=1
        assert sum(s['weights'].values())==pytest.approx(1)
        assert sum(c['points'] for c in s['contribution'])==pytest.approx(s['raw_score'])
    json.dumps(b,allow_nan=False)


def test_prices_are_truncated_at_evaluation_date():
    frame=ohlcv(ramp(100,200,300),end='2026-12-31')
    cut=frame.index[-40].date()
    assert F.compute(frame,as_of=cut)['reversal_5d']==F.compute(frame.iloc[:-39])['reversal_5d']


def test_other_income_tiny_pbt_and_missing_addbacks():
    qs=quarters();qs[0]['pbt']=.00001
    assert F.fundamental_factors(qs,100,ASOF)['other_income_quality'] is None
    norm=xbrl.normalise({'ok':True,'facts':{'RevenueFromOperations':100,'ProfitBeforeTax':10},'period':{}})
    assert 'ebitda_margin_pct' not in norm


def test_dual_regime_keeps_versions_until_cutoff(monkeypatch):
    old=dict(to='30-Jun-2026',filed_at='15-Jul-2026',consolidated=True,xbrl='old.xml',regime='legacy')
    rev={**old,'filed_at':'01-Aug-2026','xbrl':'revision.xml','regime':'integrated'}
    monkeypatch.setattr(xbrl,'_legacy_filings',lambda *a:[old])
    monkeypatch.setattr(xbrl,'_integrated_filings',lambda *a:[rev])
    assert len(xbrl.filings('ACME',retain_versions=True))==2
    monkeypatch.setattr(xbrl,'fetch',lambda url:{'period':{'from':'2026-04-01','to':'2026-06-30'},'pat':100 if url=='old.xml' else 999})
    known=xbrl.statements('ACME',as_of='2026-07-20',retain_versions=True)
    assert len(known)==1 and known[0]['pat']==100


def test_scan_ranks_full_cohort_before_trim_and_banks_v4(monkeypatch):
    import scan
    rows=universe(80)
    for r in rows:r.update(composite=90,technical=90,fundamental=90)
    payload=scan._build_payload(rows,'fixture',80,0,80,0,0,80,[])
    assert len(payload['factor_universe'])==80
    assert len(payload['rankings'])==scan.STORE_TOP
    assert payload['rankings'][0]['composite']==payload['rankings'][0]['position_score']
    captured={}
    monkeypatch.setattr(scan.pit_store,'start_run',lambda **k:1)
    monkeypatch.setattr(scan.pit_store,'snapshot_many',lambda r,**k:captured.update(r))
    scan._record_to_pit(payload['factor_universe'],80,80,0,0)
    assert len(captured)==80
    assert 'v4_position_family_acceleration' in captured['S079']
    assert 'v4_raw_earnings_surprise' in captured['S079']
    assert 'v4_audit' in captured['S079']


def test_version_store_keeps_original_and_revision(tmp_path,monkeypatch):
    import pit_store
    conn=__import__('sqlite3').connect(tmp_path/'versions.db')
    monkeypatch.setattr(pit_store,'_connect',lambda:conn)
    q=quarters()[0]; rev={**q,'filed_at':'2027-02-01','pat':999}
    pit_store.record_quarter_versions('A',[q,rev])
    pit_store.record_quarter_versions('A',[{**q,'pat':111}])
    rows=pit_store.quarter_versions('A')
    assert len(rows)==2
    assert F.known_quarters(rows,ASOF)[0]['pat']==q['pat']
    conn.close()


def test_analysis_and_rank_reuse_scan_score_without_truncated_reranking(monkeypatch):
    import main
    payload={'factor_universe':M.rank(universe(80),'position')['rows']}
    payload['rankings']=payload['factor_universe'][:10]
    monkeypatch.setitem(main._state,'payload',payload)
    v4=main._cached_v4('S079')
    assert v4['methodology_version']=='v4'
    assert main.factors_rank('position',limit=1)['rows'][0]['factor_score']==v4['position']['final_score']
    p=M.presentation(v4,'invest')
    assert p['score']==v4['invest']['final_score']
    assert main._cached_v4('UNKNOWN')['available'] is False


def test_correlation_warning_requires_persistent_history(monkeypatch):
    import factor_lab as L
    monkeypatch.setattr(L.pit_store,'snapshot_dates',lambda:[f'2026-01-{i:02d}' for i in range(1,10)])
    monkeypatch.setattr(L.pit_store,'get_snapshot',lambda d:{f'S{i}':{'a':i,'b':i*2} for i in range(40)})
    out=L.correlations(['a','b'])
    assert out['pairs'][0]['warning'] is True
    assert out['automatic_changes'] is False
    monkeypatch.setattr(L.pit_store,'snapshot_dates',lambda:['2026-01-01'])
    p=L.correlations(['a','b'])['pairs'][0]
    assert not p['warning'] and p['mean_correlation'] is None
    assert L.suggested_weights()['automatic_changes'] is False


def test_lab_reports_ic_ir_quintiles_and_used_observations(monkeypatch):
    import factor_lab as L
    rows=[(f'2026-01-{j:02d}',f'S{i}',float(i),float(i if j%2 else 40-i)) for j in range(1,10) for i in range(40)]
    rows.extend([('2026-02-01','TOO_THIN',1.,1.)])
    monkeypatch.setattr(L.pit_store,'training_set',lambda *a:rows)
    out=L.evaluate('test')
    assert out['observations']==360 and out['observations_available']==361
    assert out['ic_information_ratio']==pytest.approx(out['mean_ic']/out['ic_sd'],abs=.001)
    assert out['top_quintile_pct'] is not None and out['bottom_quintile_pct'] is not None
    assert out['statistically_validated'] is False


def test_forward_labels_refuse_mismatched_benchmark_window(monkeypatch):
    import forward_returns as FR
    stock=ohlcv(ramp(100,130,200),end='2026-09-01')['Close']
    bench=stock.drop(stock.index[100])
    monkeypatch.setattr(FR.pit_store,'init_db',lambda:None)
    monkeypatch.setattr(FR.pit_store,'unlabelled',lambda h:[(stock.index[100].date().isoformat(),'A')])
    monkeypatch.setattr(FR.pit_store,'label_counts',lambda:{})
    monkeypatch.setattr(FR,'_history',lambda s:bench if s==FR.BENCHMARK else stock)
    out=FR.run(horizons=(21,),today=dt.date(2026,9,1))
    assert out['written']==0 and out['skipped_not_ready']==1
    assert 126 in FR.HORIZONS


def test_ambiguous_ratio_tags_are_not_guessed_or_zero_filled():
    qs=quarters()
    qs[0].update(debt_equity=.004,interest_cover=.0467,pbt_before_exceptional=100,
                 finance_cost=10,other_income=20)
    out=F.fundamental_factors(qs,100,ASOF)
    assert out['low_leverage'] is None
    assert out['interest_coverage']==pytest.approx(9.)
    qs[0]['finance_cost']=0
    assert F.fundamental_factors(qs,100,ASOF)['interest_coverage'] is None
