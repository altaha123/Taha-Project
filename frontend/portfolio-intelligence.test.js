'use strict';
const assert = require('node:assert/strict');
const {compare,snapshot,build,safeURL}=require('./portfolio-intelligence.js');
function snap(overrides={}){return {at:'2026-09-10T10:00:00Z',basis:{version:1,benchmark:'March 2026'},score:70,coverage:100,holdings:[{symbol:'A',score:70,qty:1}],sectors:[{sector:'Energy',weight:100}],events:[],...overrides};}
assert.deepEqual(compare(null,snap()),[]);
assert.deepEqual(compare(snap(),snap()),[]);
assert.deepEqual(compare(snap(),snap({at:'2026-09-11',basis:{version:2}})),[]);
assert.deepEqual(compare(snap(),snap({at:'2026-09-11',coverage:50,score:80})),[]);
assert.ok(compare(snap(),snap({at:'2026-09-11',score:80}))[0].includes('70.0 → 80.0'));
assert.ok(compare(snap(),snap({at:'2026-09-11',holdings:[{symbol:'B',score:70}],sectors:[{sector:'Technology',weight:100}]})).some(x=>x.includes('Energy exposure 100.0% → 0.0%')));
assert.equal(safeURL('javascript:alert(1)'),null);
assert.equal(safeURL('https://nseindia.com/a.pdf'),'https://nseindia.com/a.pdf');
const html=build({holdings:[],failed:[{symbol:'<script>alert(1)</script>',error:'Unavailable'}],data_quality:{},risk:{},history:{},sectors:[],sector_comparison:[]});
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('<script>alert'));
assert.ok(html.includes('Partial valuation'));
assert.ok(html.includes('No positive market values available'));
assert.ok(!html.includes('NaN'));
assert.ok(!html.includes('What Changed Recently'));
console.log('Portfolio Intelligence: 14 frontend assertions passed');
const sample={holdings:[{symbol:'LARGE',weight_pct:60,pnl:-500,value:6000},{symbol:'SMALL',weight_pct:40,pnl:100,value:4000}],total_value:10000,sectors:[{sector:'Energy',weight_pct:100}],data_quality:{valuation_complete:true,cost_value_pct:100,scored_value_pct:100},policy:{max_stock_pct:20,max_sector_pct:40}};
const simple=build(sample);
assert.ok(simple.includes('pi-mode-simple'));
assert.ok(simple.includes('About ₹60 of every ₹100'));
assert.ok(simple.includes('Loss ₹500'));
assert.ok(simple.includes('Gain ₹100'));
assert.ok(simple.includes('above your 20.0% stock limit'));
assert.ok(simple.includes('above your 40.0% sector limit'));
assert.ok(build({...sample,data_quality:{}}).includes('not your complete portfolio return'));
assert.ok(build({...sample,holdings:[]}).includes('Add purchase prices'));
assert.ok(build(sample,true).includes('pi-mode-advanced'));
assert.ok(!build(sample,true).includes('data-review-mode'));
console.log('Simple portfolio: missing data, priorities, gain/loss and export assertions passed');

/* Investment Committee review. The payload is computed in ic_review.py; these
   assertions pin what the page must do with it — render every part it is
   given, escape it, and say why a part is missing rather than dropping the
   card and leaving a reader to assume the measurement was fine. */
const ic={...sample,ic_review:{available:true,headline:'4 holdings, ₹10,00,000.',framing:'Nothing here is an instruction to buy, sell or hold any security.',
  scorecard:{overall:54,grade:'C',dimensions_scored:5,dimensions_total:6,method:'Equal-weighted mean of the dimensions that could be computed.',
    dimensions:[{key:'construction',label:'Portfolio construction',score:8,method:'Effective holdings and largest weight.'},
                {key:'valuation',label:'Valuation discipline',score:null,method:'Aggregate multiple against a disclosed band.'}]},
  risk_budget:{available:true,observations:126,coverage_pct:100,from:'2026-03-19',to:'2026-09-10',volatility_pct:14.02,
    diversification_ratio:1.85,diversification_benefit_pct:11.8,effective_risk_positions:2.9,top3_risk_share_pct:98.3,
    method:'Annualised from daily adjusted-close returns.',basis:'Current weights applied to past returns.',
    value_at_risk:{'95':{historical_pct:1.27,parametric_pct:1.45},method:'Historical and parametric.'},
    holdings:[{symbol:'LARGE',weight_pct:60,risk_share_pct:42.9,risk_vs_capital_pp:-17.1,volatility_pct:17.4},
              {symbol:'SMALL',weight_pct:40,risk_share_pct:57.1,risk_vs_capital_pp:17.1,volatility_pct:36.4}],
    benchmark:{available:true,name:'Nifty 50',beta:0.92,r_squared:0.71,tracking_error_pct:9.5,up_capture_pct:97,down_capture_pct:104,observations:126}},
  valuation:{available:true,portfolio_pe:23.99,portfolio_pe_coverage_pct:85,portfolio_pb:2.82,earnings_yield_pct:4.17,
    median_holding_pe:22,band_position:'inside the 15–28× reference band',method:'Harmonic mean of the earnings yield.',
    most_expensive:[{symbol:'SMALL',pe:48,pb:6,weight_pct:40,earnings_yield_pct:2.08}],least_expensive:[],
    loss_making:[{symbol:'<img>',weight_pct:5}],loss_making_weight_pct:5,unpriced_multiple_symbols:['LARGE']},
  capital_plan:{available:true,released_value:450000,released_pct:45,proforma_top1_pct:35.3,proforma_top3_pct:88,proforma_effective_n:3.6,
    note:'Arithmetic against your own ceilings, at today’s prices.',
    gaps:[{symbol:'LARGE',measured_pct:60,limit_pct:20,shares:9,of_shares:10,value:450000,price:50000,resulting_weight_pct:35.3}]},
  agenda:[{rank:1,title:'Single-stock cap · LARGE',rule:'max_stock_pct',measured:60,limit:20,observation:'LARGE is 60.0% of the book.',
           arithmetic:'9 of 10 shares, ₹4,50,000.',question:'Is this position deliberately sized above the ceiling?'}],
  unassessed:['Liquidity and the cost of moving these positions']}};
const memo=build(ic,true);
assert.ok(memo.includes('Investment Committee Review'));
assert.ok(memo.includes('4 holdings, ₹10,00,000.'));
assert.ok(memo.includes('Portfolio construction'));
assert.ok(memo.includes('Valuation discipline'));      // a dimension with no score still appears
assert.ok(memo.includes('Risk Budget'));
assert.ok(memo.includes('Share of risk'));
assert.ok(memo.includes('Beta vs Nifty 50'));
assert.ok(memo.includes('Review Agenda'));
assert.ok(memo.includes('Is this position deliberately sized above the ceiling?'));
assert.ok(memo.includes('Nothing here is an instruction'));
assert.ok(memo.includes('&lt;img&gt;'));               // symbols from an uploaded file are escaped
// Scoped to the review's own markup — the cards on either side are the
// existing report's and are asserted above.
const memoOnly=memo.slice(memo.indexOf('Investment Committee Review'),memo.indexOf('Portfolio allocation'));
assert.ok(!memoOnly.includes('NaN'));
assert.ok(!memoOnly.includes('undefined'));
const noRisk=build({...ic,ic_review:{...ic.ic_review,risk_budget:{available:false,reason:'Fewer than 60 shared dates.'},
  valuation:{available:false,reason:'No usable trailing multiple.'}}},true);
assert.ok(noRisk.includes('Fewer than 60 shared dates.'));   // the card states its own reason
assert.ok(noRisk.includes('No usable trailing multiple.'));
assert.ok(build({...sample,ic_review:{available:false,reason:'No priced holdings.'}},true).includes('No priced holdings.'));
assert.ok(!build(sample,true).includes('Investment Committee Review'));  // absent payload renders nothing
console.log('Investment Committee review: 18 frontend assertions passed');
