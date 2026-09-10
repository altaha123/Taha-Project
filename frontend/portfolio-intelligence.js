/* Altaha Portfolio Intelligence. Plain browser JS; Chart.js is lazy-loaded
 * from our own origin. Tables remain useful when charts cannot initialise. */
(function (root) {
  'use strict';
  const SNAP_KEY = 'altaha-intelligence-snapshots-v1';
  const state = { report: null, charts: [], allocation: 'Sector', sort: 'weight', window: '3M', sector: '', generation: 0 };
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const num = (x, dp=1) => finite(x) ? x.toLocaleString('en-IN',{minimumFractionDigits:dp,maximumFractionDigits:dp}) : '—';
  const pct = x => finite(x) ? num(x)+'%' : '—';
  const money = x => finite(x) ? (x < 0 ? '−' : '')+'₹'+Math.abs(x).toLocaleString('en-IN',{maximumFractionDigits:0}) : '—';
  const sign = x => finite(x) ? (x > 0 ? '+' : '')+num(x) : '—';
  const tone = x => finite(x) ? x < 0 ? 'pi-negative' : x > 0 ? 'pi-positive' : '' : '';
  const date = x => { const d = new Date(x); return x && !isNaN(d) ? d.toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}) : x || 'Unavailable'; };
  const safeURL = x => { try {const u = new URL(x);return ['https:','http:'].includes(u.protocol) ? u.href : null;}catch(e){return null;} };
  const empty = text => '<p class="pi-empty">'+esc(text)+'</p>';
  function table(headers, rows) {
    return '<div class="pi-table-scroll" tabindex="0" role="region" aria-label="'+esc(headers.join(', '))+'"><table class="pi-table"><thead><tr>'+headers.map(h=>'<th scope="col">'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  }
  const dataTable = (headers, rows, flat) => rows.length ? (flat ? table(headers,rows) : '<details class="pi-data"><summary>View chart data</summary>'+table(headers,rows)+'</details>') : '';
  function card(id,title,question,content,controls='') {
    return '<section class="pi-card" id="'+id+'"><div class="pi-card-head"><div><h3>'+title+'</h3><p>'+question+'</p></div>'+controls+'</div>'+content+'</section>';
  }
  function chart(id,label,height=280) {return '<div class="pi-chart" style="height:'+height+'px"><canvas id="'+id+'" role="img" aria-label="'+esc(label)+'"></canvas></div>';}
  function select(id,label,options,value) {return '<label class="pi-control"><span>'+label+'</span><select id="'+id+'">'+options.map(([v,l])=>'<option value="'+v+'"'+(v===value?' selected':'')+'>'+l+'</option>').join('')+'</select></label>';}
  function metric(label,value,note,cls='') {return '<div class="pi-metric"><span>'+label+'</span><strong class="'+cls+'">'+value+'</strong><small>'+note+'</small></div>';}
  function allocation(d) {
    const rows = d.holdings || [];
    if(state.allocation === 'Stock') return rows.map(r=>({label:r.symbol,weight_pct:r.weight_pct,value:r.value,count:1,score:r.composite}));
    if(state.allocation === 'Market Cap') {
      const buckets = {};
      rows.forEach(r=>{const label=r.market_cap_bucket || 'Unclassified';const b=buckets[label] ||= {label,weight_pct:0,value:0,count:0,score:null};b.weight_pct+=r.weight_pct;b.value+=r.value;b.count++;});
      return Object.values(buckets);
    }
    return (d.sectors || []).map(s=>({label:s.sector,weight_pct:s.weight_pct,value:s.value,count:s.count,score:s.avg_score}));
  }
  function sectorComparison(d) {
    const field = {weight:'weight_pct',over:'active_weight_pct',under:'active_weight_pct',score:'avg_score',momentum:'momentum'}[state.sort];
    const direction=state.sort === 'under' ? 1 : -1;
    return [...(d.sector_comparison||[])].sort((a,b)=>finite(a[field])&&finite(b[field])?direction*(a[field]-b[field]):finite(a[field])?-1:finite(b[field])?1:a.sector.localeCompare(b.sector));
  }
  function newsCards(items,limit=12) {
    if (!items?.length) return empty('No matching sourced events in the available seven-day feed cache. Check source freshness below.');
    return '<div class="pi-news-list">'+items.slice(0,limit).map(n=>{
      const url=safeURL(n.url);
      return '<article class="pi-news"><div class="pi-news-meta"><span class="pi-badge">'+esc(n.group)+'</span><span>'+esc(n.materiality)+' relevance · '+pct(n.exposure_pct)+' exposure</span></div><h4>'+(url?'<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(n.headline)+'</a>':esc(n.headline))+'</h4><p>'+esc(n.interpretation)+'</p><small>'+esc(n.source)+' · '+esc(date(n.published_at))+' · '+esc(n.mapping)+' · '+esc(n.symbols?.join(', '))+'</small></article>';
    }).join('')+'</div>';
  }
  function holding(r,flat) {
    const f = r.fundamental_extras || {}, tx=r.technical_extras||{}, v=r.valuation||{};
    const checks = r.technical_checks || [];
    return '<details class="pi-holding" data-sector="'+esc(r.sector)+'" data-symbol="'+esc(r.symbol)+'"'+(flat?' open':'')+'><summary><span class="pi-company"><b>'+esc(r.symbol)+'</b><small>'+esc(r.name)+' · '+esc(r.sector)+'</small></span><span><b>'+money(r.value)+'</b><small>'+pct(r.weight_pct)+' weight</small></span><span class="'+tone(r.pnl)+'"><b>'+money(r.pnl)+'</b><small>'+pct(r.pnl_pct)+' from cost</small></span><span class="pi-score"><b>'+num(r.composite)+'</b><small>'+esc(r.score_category)+'</small></span></summary><div class="pi-holding-body"><h4>Altaha View</h4><p>'+esc(r.altaha_view)+'</p><div class="pi-facts">'+[
      ['Quantity',num(r.qty,2)],['Current price',money(r.price)],['Average cost',money(r.buy_price)],['Contribution / current value',pct(r.contribution_pct)],
      ['Technical checks',num(r.technical)],['Fundamental checks',num(r.fundamental)],['Trend',esc(r.trend||'Unavailable')],['52-week range position',pct(tx.range_position)],
      ['Distance / 20-day SMA',pct(r.moving_averages?.['20'])],['Distance / 50-day SMA',pct(r.moving_averages?.['50'])],['Distance / 200-day SMA',pct(r.moving_averages?.['200'])],['Drawdown / observed high',pct(tx.drawdown_from_high)],
      ['Trailing P/E',num(v.pe)],['Price / book',num(v.pb)],['Revenue growth (annual provider)',pct(f.rev_growth)],['ROCE (annual provider)',pct(f.roce)]]
      .map(([k,v])=>'<div><span>'+k+'</span><b>'+v+'</b></div>').join('')+'</div><p class="pi-note">Price: '+esc(r.price_source)+' · '+esc(date(r.price_as_of))+'; checked '+esc(date(r.price_checked_at))+'. Score scan: '+esc(date(r.score_as_of))+'. '+esc(r.fundamental_source||'Fundamental source metadata unavailable.')+'</p>'+
      (r.warnings||[]).map(w=>'<p class="pi-warning">'+esc(w)+'</p>').join('')+
      (r.peers?.length?'<p class="pi-note">Same-sector scan peers: '+r.peers.map(p=>esc(p.symbol)+' '+num(p.composite)).join(' · ')+'. Peer data is dated to the scan.</p>':'')+
      '<details class="pi-data"'+(flat?' open':'')+'><summary>Why these scores?</summary>'+table(['Technical check','Points','Observed evidence'],checks.map(c=>[esc(c.name),num(c.points,0)+' / '+num(c.max,0),esc(c.value)]))+
      table(['Altaha v4 factor','Percentile','Source evidence'],(r.altaha_score_v4?.factor_ledger||[]).map(e=>[esc(e.label),num(e.percentile),esc(e.explanation)]))+'</details>'+
      (r.news?.length?'<h4>Recent mapped developments</h4>'+newsCards(r.news,3):'')+'</div></details>';
  }
  function build(d,flat=false) {
    const q=d.data_quality||{}, c=d.concentration||{}, risk=d.risk||{}, health=d.health||{}, rows=d.holdings||[], alloc=allocation(d), comp=sectorComparison(d), factors=d.factor_exposure||[];
    let html='<div class="pi-root"><header class="pi-header"><div><span class="pi-eyebrow">ALTAHA / PORTFOLIO INTELLIGENCE</span><h2>Your capital. In perspective.</h2><p>Quality, concentration and the developments that matter to your holdings.</p></div><span class="pi-badge">'+esc(health.label||'Awaiting data')+(health.provisional?' · Provisional':'')+'</span></header>';
    if(d.stage && !d.stage.startsWith('Complete')) html+='<p class="pi-warning" role="status">'+esc(d.stage)+' · Research enrichment is still running. Values may update.</p>';
    if(d.enrichment_incomplete) html+='<p class="pi-warning">Some enrichment could not finish. Available valuations are retained; review holding notes and retry to refresh.</p>';
    if(d.failed?.length) html+='<div class="pi-warning" role="alert"><b>Partial valuation — '+d.failed.length+' holdings unavailable.</b> Weights use priced capital only. '+d.failed.map(r=>esc(r.symbol)+': '+esc(r.error)).join(' · ')+'</div>';
    html+='<div class="pi-metrics">'+metric(q.valuation_complete?'Portfolio value':'Priced portfolio value',money(d.total_value),rows.length+' priced holdings')+metric('Unrealised P&L',money(d.total_pnl),pct(d.total_pnl_pct)+' on known cost · '+pct(q.cost_value_pct)+' cost coverage',tone(d.total_pnl))+metric('Altaha Portfolio Score',num(d.weighted_score)+' <em>/ 100</em>','Grade '+esc(d.grade)+' · '+pct(q.scored_value_pct)+' capital scored')+metric('Observed portfolio risk',esc(risk.grade||'Unavailable'),(risk.triggered_count??0)+' disclosed thresholds triggered')+'</div>';
    html+=card('pi-committee','Portfolio Investment Committee Summary','The portfolio in 30 seconds','<p class="pi-committee">'+esc(d.committee_summary)+'</p><div class="pi-confidence"><span>Score confidence <b>'+pct(q.weighted_confidence_pct)+'</b></span><span>Effective holdings <b>'+num(c.effective_n)+'</b></span><span>Top 3 <b>'+pct(c.top3_pct)+'</b></span><span>Score scan <b>'+esc(date(q.score_as_of))+'</b></span></div>');
    if(d.changes?.length) html+=card('pi-changes','What Changed Recently','Compared with '+esc(date(d.previous_review_at))+' · '+esc(d.comparison_note||''),'<ul class="pi-changes">'+d.changes.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>');
    html+='<div class="pi-grid">';
    html+=card('pi-allocation','Portfolio allocation','Where is your capital committed?',(alloc.length?chart('pi-allocation-chart','Allocation by '+state.allocation,270):empty('No positive market values available.'))+
      '<div class="pi-allocation-legend">'+alloc.map((a,i)=>'<button type="button" data-allocation="'+esc(a.label)+'" class="pi-legend-item"><i style="background:'+palette(i)+'"></i><span>'+esc(a.label)+'</span><b>'+pct(a.weight_pct)+'</b></button>').join('')+'</div>'+
      (state.allocation==='Market Cap'?'<p class="pi-note">'+esc(rows[0]?.market_cap_note||'Official classifications unavailable. Unknown buckets remain unclassified.')+'</p>':'')+
      dataTable(['Allocation','Weight','Value','Stocks','Weighted score'],alloc.map(a=>[esc(a.label),pct(a.weight_pct),money(a.value),a.count,num(a.score)]),flat),flat?'':select('pi-allocation-mode','Group',[['Sector','Sector'],['Stock','Stock'],['Market Cap','Market Cap']],state.allocation));
    html+=card('pi-concentration','Stock concentration','Which positions have the most influence?',rows.length?chart('pi-concentration-chart','Holding weights and your maximum stock limit',Math.max(280,rows.length*32+50))+dataTable(['Holding','Weight','Limit','Score','P&L'],rows.map(r=>[esc(r.symbol),pct(r.weight_pct),pct(d.policy?.max_stock_pct),num(r.composite),money(r.pnl)]),flat):empty('Add holdings with available market prices.'));
    html+='</div>';
    html+=card('pi-sector-comparison','Sector vs Benchmark','Where does your portfolio differ from the broader market?',chart('pi-sector-chart','Portfolio, benchmark and active sector weights',Math.max(390,comp.length*62+60))+'<p class="pi-note">'+esc(d.benchmark?.name)+' · '+esc(d.benchmark?.kind)+' · '+esc(d.benchmark?.as_of)+'. '+esc(d.benchmark?.note)+'</p>'+dataTable(['Sector','Portfolio','Benchmark','Active (pp)','Score','3M relative (pp)'],comp.map(s=>[esc(s.sector),pct(s.weight_pct),pct(s.benchmark_weight_pct),sign(s.active_weight_pct),num(s.avg_score),sign(s.momentum)]),flat),flat?'':select('pi-sector-sort','Sort',[['weight','Portfolio weight'],['over','Overweight'],['under','Underweight'],['score','Sector score'],['momentum','Sector momentum']],state.sort));
    html+='<div class="pi-grid">';
    html+=card('pi-distribution','Portfolio score distribution','How much capital has strong or weak evidence?',rows.length?chart('pi-distribution-chart','Share of capital in Altaha Score bands')+dataTable(['Band','Weight','Holdings','Value'],(d.score_distribution||[]).map(b=>[esc(b.label),pct(b.weight_pct),b.count,money(b.value)]),flat):empty('No priced capital to distribute.'));
    const contributors=rows.filter(r=>finite(r.pnl)).sort((a,b)=>b.pnl-a.pnl);
    html+=card('pi-contribution','Contribution to P&L','Which holdings generated the actual rupee gain or loss?',contributors.length?chart('pi-contribution-chart','Rupee contribution to unrealised P&L',Math.max(280,contributors.length*32+50))+'<p class="pi-note">Contribution % = holding P&L ÷ current priced portfolio value. This is not time-weighted return attribution.</p>'+dataTable(['Holding','Contribution ₹','% current value','Stock return'],contributors.map(r=>[esc(r.symbol),money(r.pnl),pct(r.contribution_pct),pct(r.pnl_pct)]),flat):empty('Add purchase costs to see actual rupee contributions.'));
    html+='</div>';
    html+=card('pi-sectors','Sector Intelligence','The evidence behind each sector exposure','<div class="pi-sector-cards">'+(d.sectors||[]).map(s=>'<details class="pi-sector-detail"'+(flat?' open':'')+'><summary><b>'+esc(s.sector)+'</b><span>'+pct(s.weight_pct)+' weight · '+sign(s.active_weight_pct)+' pp active</span></summary><div><p>'+esc(s.interpretation)+'</p><div class="pi-facts">'+[
      ['Exposure',money(s.value)],['Holdings',s.count],['Weighted score',num(s.avg_score)],['Score coverage',pct(s.score_coverage_pct)],['Best / weakest',esc(s.best||'—')+' / '+esc(s.weakest||'—')],['Momentum',esc(s.state||'Unavailable')],['1M proxy return',pct(s.returns?.['1M'])],['3M proxy return',pct(s.returns?.['3M'])],['6M proxy return',pct(s.returns?.['6M'])],['3M vs Nifty 50',sign(s.relative?.['3M'])+' pp']]
      .map(([k,v])=>'<div><span>'+k+'</span><b>'+v+'</b></div>').join('')+'</div><p class="pi-note">'+esc(s.index_name||'Index data unavailable')+' · Measured '+esc(date(d.sector_momentum?.measured_at))+'. '+esc(s.proxy_note||'')+'</p>'+(s.news?.length?newsCards(s.news,2):empty('No sourced recent sector development in the available feed.'))+'</div></details>').join('')+'</div>');
    html+='<div class="pi-grid">';
    const points=d.history?.windows?.[state.window]?.points||[];
    html+=card('pi-risk-return','Risk / Return Map','Which positions paired return with higher volatility?',points.length?chart('pi-risk-return-chart','Annualised daily volatility versus holding return')+'<p class="pi-note">Bubble area reflects position weight. '+state.window+' history coverage: '+pct(d.history.windows[state.window].coverage_pct)+'. Historical returns are not forecasts.</p>'+dataTable(['Holding','Return','Volatility / year','Weight','Dates'],points.map(p=>[esc(p.symbol),pct(p.return_pct),pct(p.volatility_pct),pct(p.weight_pct),esc(p.from+' – '+p.to)]),flat):empty(d.history?.unavailable_reason||'Sufficient adjusted price history unavailable.'),flat?'':select('pi-window','Window',[['1M','1M'],['3M','3M'],['6M','6M'],['1Y','1Y']],state.window));
    html+=card('pi-factors','Portfolio Factor Exposure','What supports the score — and where is evidence missing?',factors.some(f=>finite(f.value))?chart('pi-factors-chart','Value weighted Altaha factor exposures')+'<p class="pi-note">V4 position-horizon peer percentiles, weighted by covered capital; higher is stronger, including risk resilience. Technical strength is a separate check score. No benchmark factor series is available.</p>'+dataTable(['Factor','Score / 100','Value coverage','Holdings'],factors.map(f=>[esc(f.label),num(f.value),pct(f.coverage_pct),f.count]),flat):empty('No comparable factor observations in the current scan.'));
    html+='</div>';
    const groupNames={strength:'Portfolio Strength Leaders',weak:'Portfolio Weak Links',risk:'Largest Risk Contributors',monitor:'Most Important Holdings to Monitor'};
    html+='<div class="pi-grid">'+Object.entries(groupNames).map(([k,title])=>card('pi-group-'+k,title,k==='risk'?'Heuristic monitoring priority, not a volatility attribution':k==='weak'?'Weak evidence is a review signal, not an automatic sell instruction':'Ranked by portfolio relevance',d.groups?.[k]?.length?'<ol class="pi-ranking">'+d.groups[k].map(r=>'<li><div><a href="#pi-holdings" data-focus-symbol="'+esc(r.symbol)+'">'+esc(r.symbol)+'</a><span>'+pct(r.weight_pct)+' · score '+num(r.score)+'</span></div><p>'+esc(r.reasons.join('. '))+'</p></li>').join('')+'</ol>':empty('No holdings meet this category’s available evidence requirements.'))).join('')+'</div>';
    const corr=d.history?.correlation||{}, hasCorr=corr.matrix?.some((row,i)=>row.some((c,j)=>i!==j&&finite(c.value)));
    let heat=empty('At least 60 overlapping adjusted daily return observations per pair are required. Missing or unverified history is not filled.');
    if(hasCorr) heat='<div class="pi-heat-scroll" tabindex="0" role="region" aria-label="Correlation matrix"><table class="pi-heat"><thead><tr><th></th>'+corr.symbols.map(s=>'<th scope="col">'+esc(s)+'</th>').join('')+'</tr></thead><tbody>'+corr.matrix.map((row,i)=>'<tr><th scope="row">'+esc(corr.symbols[i])+'</th>'+row.map((c,j)=>'<td style="background:'+(finite(c.value)?'rgba(76,122,158,'+(.08+Math.abs(c.value)*.5)+')':'transparent')+'" title="'+esc(corr.symbols[i]+' / '+corr.symbols[j])+': '+c.observations+' overlapping returns">'+num(c.value,2)+'<small>n='+c.observations+'</small></td>').join('')+'</tr>').join('')+'</tbody></table></div><p>'+esc(corr.high_pairs?.length?corr.high_pairs.length+' pairs have correlation ≥0.8 and involve '+pct(corr.high_correlation_exposure_pct)+' of priced capital. These holdings may provide less diversification than their count suggests.':'No measured pair exceeds 0.8 correlation in this window. This does not establish independence.')+'</p>';
    html+=card('pi-correlation','Correlation & Hidden Concentration','Do different holdings behave alike?',heat+'<p class="pi-note">'+esc(corr.from||'—')+' to '+esc(corr.to||'—')+'. '+esc(d.history?.method||'')+'</p>');
    html+=card('pi-scenarios','Hypothetical Stress Scenarios','What would an equal decline in an exposed sleeve mean?',table(['Hypothetical shock','Exposure','Arithmetic','Change in value'],(d.scenarios||[]).map(s=>[esc(s.name),pct(s.exposure_pct),esc(s.arithmetic),money(s.impact_inr)]))+'<p class="pi-note">Exposure arithmetic only. Other holdings are assumed unchanged. No estimated beta, forecast, second-order effect, oil, currency or rate sensitivity is implied.</p>');
    html+=card('pi-developments','Latest Portfolio Developments','What changed in the world around your holdings?',newsCards(d.developments?.events)+'<p class="pi-note">Feed cache checked '+esc(date(d.developments?.checked_at))+'. '+esc(d.developments?.method)+'</p>');
    html+=card('pi-holdings','Holding-level Review','Tap a holding to inspect its evidence, contribution and source dates','<p id="pi-filter-note" class="pi-note"></p>'+(flat?'':'<button class="pi-reset" type="button" id="pi-reset-filter">Show all holdings</button>')+rows.map(r=>holding(r,flat)).join(''));
    html+=card('pi-risk-rules','Risk, Diversification & Your Policy','Each threshold is visible and explainable','<div class="pi-confidence"><span>Holdings <b>'+num(c.count,0)+'</b></span><span>Effective <b>'+num(c.effective_n)+'</b></span><span>Top 1 <b>'+pct(c.top1_pct)+'</b></span><span>Top 3 <b>'+pct(c.top3_pct)+'</b></span><span>Top 5 <b>'+pct(c.top5_pct)+'</b></span><span>HHI <b>'+num(c.hhi,4)+'</b></span></div><p class="pi-note">HHI = sum of squared weight fractions; effective holdings = 1 ÷ HHI. These measure weight concentration, not statistical independence.</p>'+table(['Measure','Observed','Threshold','Status / Why it matters'],(risk.rules||[]).map(r=>[esc(r.name),num(r.measured),esc(r.direction)+' '+num(r.limit),'<b>'+(!finite(r.measured)?'Unavailable':r.triggered?'Flagged':'Within threshold')+'</b> · '+esc(r.why)]))+'<p class="pi-note">'+esc(risk.method)+'</p><details class="pi-data"><summary>Policy findings and arithmetic</summary>'+(d.breaches||[]).map(b=>'<p>'+esc(b.text)+'</p>').join('')+'</details>');
    html+=card('pi-quality','Data Quality','Coverage and freshness set the limits of this review','<div class="pi-confidence"><span>Scored capital <b>'+pct(q.scored_value_pct)+'</b></span><span>Sector classified <b>'+pct(q.sector_value_pct)+'</b></span><span>Holdings with costs <b>'+pct(q.cost_holdings_pct)+'</b></span><span>Confidence coverage <b>'+pct(q.confidence_coverage_pct)+'</b></span></div>'+(q.warnings||[]).map(w=>'<p class="pi-warning">'+esc(w)+'</p>').join('')+'<p class="pi-note">Valuation sources: '+esc(q.price_sources?.join(', '))+'. Price dates: '+esc(q.price_dates?.join(', ')||'Unavailable')+'. Score scan: '+esc(date(q.score_as_of))+'. Benchmark weights: '+esc(d.benchmark?.as_of)+'.</p><p class="pi-note">Filings last poll: '+esc(date(d.developments?.source_status?.filings?.last_poll))+'. '+esc(d.developments?.source_status?.filings?.error||'')+' Press cache age: '+num(d.developments?.source_status?.press?.age_seconds,0)+' seconds. '+esc((d.developments?.source_status?.press?.errors||[]).join?.('; ')||d.developments?.source_status?.press?.error||'')+'</p><p class="pi-note">'+esc(d.snapshot_note||'Review history is saved only in this browser. Clearing browser data removes it; it is not synced across devices.')+'</p>');
    return html+'</div>';
  }
  function palette(i) {return ['#A38338','#447D9F','#518E7A','#9A729B','#B37452','#718294'][i%6];}
  let loader;
  function loadChart() {
    if(root.Chart) return Promise.resolve(root.Chart);
    if(loader) return loader;
    loader = new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='vendor/chart.umd.min.js';s.onload=()=>root.Chart?resolve(root.Chart):reject(new Error('Chart library unavailable'));s.onerror=()=>reject(new Error('Chart library unavailable'));document.head.appendChild(s);});
    return loader;
  }
  function destroy() {state.charts.forEach(c=>c.destroy());state.charts=[];}
  function chartFailure(canvas) {if(canvas?.parentElement){canvas.parentElement.innerHTML=empty('Chart unavailable. Open “View chart data” below for the full figures.');}}
  function draw(d) {
    destroy();
    const style=getComputedStyle(document.documentElement), ink=style.getPropertyValue('--ink').trim()||'#242627', mute=style.getPropertyValue('--mute').trim()||'#69706E';
    const dark=document.documentElement.dataset.theme==='dark';
    function create(id,type,labels,datasets,extra={}) {
      const canvas=document.getElementById(id);if(!canvas)return;
      const grid=dark?'rgba(255,255,255,.10)':'rgba(0,0,0,.08)';
      const options={responsive:true,maintainAspectRatio:false,animation:matchMedia('(prefers-reduced-motion: reduce)').matches?false:{duration:350},color:ink,
        events:['mousemove','mouseout','click','touchstart','touchmove'],
        plugins:{legend:{display:datasets.length>1,position:'bottom',labels:{color:ink,boxWidth:10,padding:16,font:{size:12}}},tooltip:{callbacks:{label:ctx=>ctx.dataset.label+': '+num(typeof ctx.parsed==='number'?ctx.parsed:ctx.parsed.x)}}},
        scales:type==='doughnut'?{}:{x:{grid:{color:grid},ticks:{color:mute,font:{size:11}}},y:{grid:{display:false},ticks:{color:ink,font:{size:12},autoSkip:false}}},...extra};
      try {const c=new root.Chart(canvas,{type,data:{labels,datasets},options,plugins:extra._plugins||[]});state.charts.push(c);}catch(e){chartFailure(canvas);}
    }
    const a=allocation(d);
    create('pi-allocation-chart','doughnut',a.map(x=>x.label),[{label:'Weight',data:a.map(x=>x.weight_pct),backgroundColor:a.map((_,i)=>palette(i)),borderWidth:2,borderColor:dark?'#181D22':'#fff'}],{cutout:'72%',onClick:(e,points)=>{if(points[0])filterAllocation(a[points[0].index].label);},plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>{const v=a[c.dataIndex];return [pct(v.weight_pct)+' · '+money(v.value),v.count+' holdings · score '+num(v.score)];}}}}});
    const rows=d.holdings||[], cap=d.policy?.max_stock_pct||15;
    const capLine={id:'stockPolicy',afterDraw(c){const {ctx,chartArea,scales}=c;if(!chartArea)return;const x=scales.x.getPixelForValue(cap);ctx.save();ctx.setLineDash([4,4]);ctx.strokeStyle=ink;ctx.beginPath();ctx.moveTo(x,chartArea.top);ctx.lineTo(x,chartArea.bottom);ctx.stroke();ctx.restore();}};
    create('pi-concentration-chart','bar',rows.map(r=>r.symbol),[{label:'Portfolio weight %',data:rows.map(r=>r.weight_pct),backgroundColor:rows.map(r=>r.weight_pct>cap?'#AF6157':'#447D9F'),borderRadius:3}],{indexAxis:'y',scales:{x:{min:0,max:Math.min(100,Math.max(cap,...rows.map(r=>r.weight_pct))*1.1),ticks:{color:mute}},y:{ticks:{color:ink,autoSkip:false},grid:{display:false}}},_plugins:[capLine],plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>{const r=rows[c.dataIndex];return [pct(r.weight_pct)+' · policy limit '+pct(cap),'Score '+num(r.composite)+' · P&L '+money(r.pnl)];}}}}});
    const comp=sectorComparison(d);
    create('pi-sector-chart','bar',comp.map(s=>s.sector),[{label:'Portfolio %',data:comp.map(s=>s.weight_pct),backgroundColor:'#A38338',borderRadius:2},{label:'Nifty 500 proxy %',data:comp.map(s=>s.benchmark_weight_pct),backgroundColor:'#447D9F',borderRadius:2},{label:'Active weight (pp)',data:comp.map(s=>s.active_weight_pct),backgroundColor:comp.map(s=>s.active_weight_pct>=0?'#518E7A':'#AF6157'),borderRadius:2}],{indexAxis:'y'});
    const bands=d.score_distribution||[];
    create('pi-distribution-chart','bar',bands.map(b=>b.label),[{label:'Capital %',data:bands.map(b=>b.weight_pct),backgroundColor:bands.map((_,i)=>i<3?'#518E7A':i<5?'#A38338':i===5?'#AF6157':'#718294'),borderRadius:3}],{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>pct(bands[c.dataIndex].weight_pct)+' · '+bands[c.dataIndex].count+' holdings'}}}});
    const pnl=rows.filter(r=>finite(r.pnl)).sort((a,b)=>b.pnl-a.pnl);
    create('pi-contribution-chart','bar',pnl.map(r=>r.symbol),[{label:'P&L ₹',data:pnl.map(r=>r.pnl),backgroundColor:pnl.map(r=>r.pnl>=0?'#518E7A':'#AF6157'),borderRadius:3}],{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>[money(pnl[c.dataIndex].pnl),pct(pnl[c.dataIndex].contribution_pct)+' of current portfolio value']}}}});
    const points=d.history?.windows?.[state.window]?.points||[];
    create('pi-risk-return-chart','bubble',[],[{label:'Holding',data:points.map(p=>({x:p.volatility_pct,y:p.return_pct,r:Math.max(3,Math.sqrt(p.weight_pct)*3)})),backgroundColor:points.map(p=>finite(p.score)?p.score>=70?'#518E7Ab0':p.score<40?'#AF6157b0':'#447D9Fb0':'#718294b0')}],{scales:{x:{title:{display:true,text:'Annualised volatility %',color:ink},ticks:{color:mute}},y:{title:{display:true,text:state.window+' return %',color:ink},ticks:{color:mute}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>{const p=points[c.dataIndex];return [p.symbol+' · '+pct(p.weight_pct)+' weight','Return '+pct(p.return_pct)+' · volatility '+pct(p.volatility_pct),p.from+' to '+p.to];}}}}});
    const f=d.factor_exposure||[];
    create('pi-factors-chart','bar',f.map(x=>x.label),[{label:'Score / 100',data:f.map(x=>x.value),backgroundColor:'#447D9F',borderRadius:3}],{indexAxis:'y',scales:{x:{min:0,max:100,ticks:{color:mute}},y:{ticks:{color:ink,autoSkip:false},grid:{display:false}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>num(f[c.dataIndex].value)+' · '+pct(f[c.dataIndex].coverage_pct)+' capital covered'}}}});
  }
  function focus(symbol) {const r=[...document.querySelectorAll('.pi-holding')].find(r=>r.dataset.symbol===symbol);if(r){r.hidden=false;r.open=true;r.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}}
  function filterAllocation(value) {
    if(state.allocation==='Stock'){focus(value);return;}
    if(state.allocation!=='Sector')return;
    state.sector=value;
    document.querySelectorAll('.pi-holding').forEach(r=>{r.hidden=r.dataset.sector!==value;});
    const note=document.getElementById('pi-filter-note');if(note)note.textContent='Showing '+value+' holdings. Use “Show all holdings” to clear.';
    document.getElementById('pi-holdings')?.scrollIntoView({behavior:'smooth',block:'start'});
  }
  function mount(d) {
    state.report=d;state.generation++;const gen=state.generation;destroy();
    const host=document.getElementById('pf_report');if(!host)return;
    host.innerHTML=build(d);host.style.display='block';
    [['pi-allocation-mode','allocation'],['pi-sector-sort','sort'],['pi-window','window']].forEach(([id,key])=>document.getElementById(id)?.addEventListener('change',e=>{state[key]=e.target.value;const y=window.scrollY;mount(d);window.scrollTo(0,y);}));
    host.querySelectorAll('[data-allocation]').forEach(b=>b.addEventListener('click',()=>filterAllocation(b.dataset.allocation)));
    host.querySelectorAll('[data-focus-symbol]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();focus(b.dataset.focusSymbol);}));
    document.getElementById('pi-reset-filter')?.addEventListener('click',()=>{state.sector='';host.querySelectorAll('.pi-holding').forEach(r=>r.hidden=false);document.getElementById('pi-filter-note').textContent='Showing all holdings.';});
    loadChart().then(()=>{if(gen===state.generation)requestAnimationFrame(()=>{if(gen===state.generation)draw(d);});}).catch(()=>{if(gen===state.generation)host.querySelectorAll('canvas').forEach(chartFailure);});
  }
  function snapshot(d) {
    return {at:d.generated_at,basis:d.snapshot_basis,score:d.weighted_score,coverage:d.data_quality?.scored_value_pct,policy:d.policy,
      holdings:(d.holdings||[]).map(r=>({symbol:r.symbol,qty:r.qty,score:r.composite,weight:r.weight_pct})),sectors:(d.sectors||[]).map(s=>({sector:s.sector,weight:s.weight_pct})),events:(d.developments?.events||[]).map(n=>({id:n.id,group:n.group}))};
  }
  function compare(previous,current) {
    if(!previous||JSON.stringify(previous.basis)!==JSON.stringify(current.basis)||new Date(previous.at)>=new Date(current.at))return [];
    const out=[],sameHoldings=JSON.stringify(previous.holdings.map(h=>h.symbol).sort())===JSON.stringify(current.holdings.map(h=>h.symbol).sort());
    if(finite(previous.score)&&finite(current.score)&&Math.abs((previous.coverage||0)-(current.coverage||0))<.01&&Math.abs(current.score-previous.score)>=.1)out.push('Portfolio Altaha Score '+num(previous.score)+' → '+num(current.score)+'. This includes any changes in holdings, prices and weights.');
    current.sectors.forEach(s=>{const p=previous.sectors.find(p=>p.sector===s.sector);const before=p?p.weight:0;if(Math.abs(s.weight-before)>=1)out.push(s.sector+' exposure '+pct(before)+' → '+pct(s.weight)+'.');});
    previous.sectors.filter(s=>!current.sectors.some(c=>c.sector===s.sector)).forEach(s=>out.push(s.sector+' exposure '+pct(s.weight)+' → 0.0%.'));
    current.holdings.forEach(h=>{const p=previous.holdings.find(p=>p.symbol===h.symbol);if(p&&finite(p.score)&&finite(h.score)&&Math.abs(h.score-p.score)>=5)out.push(h.symbol+' score '+num(p.score)+' → '+num(h.score)+'. Inspect the current factor ledger; historical factor attribution is unavailable.');});
    if(!sameHoldings)out.push('The holdings list changed; portfolio-level changes include composition effects.');
    const newRisk=current.events.filter(e=>e.group==='Potential Risk'&&!previous.events.some(p=>p.id===e.id));if(newRisk.length)out.push(newRisk.length+' new sourced risk developments since the previous review.');
    return out;
  }
  function acceptSnapshot(d,key) {
    if(!d.data_quality?.valuation_complete||d.enrichment_incomplete||!key)return d;
    try {
      const store=JSON.parse(localStorage.getItem(SNAP_KEY)||'{}'), list=Array.isArray(store[key])?store[key]:[], current=snapshot(d),prev=list[list.length-1];
      d.changes=compare(prev,current);if(d.changes.length){d.previous_review_at=prev.at;d.comparison_note='Same methodology and benchmark vintage';}
      if(prev && JSON.stringify(prev.basis)===JSON.stringify(current.basis)) {
        (d.holdings||[]).forEach(h=>{const p=prev.holdings.find(p=>p.symbol===h.symbol);if(p&&finite(p.score)&&finite(h.composite)){h.score_change=h.composite-p.score;if(Math.abs(h.score_change)>=5)h.altaha_view+=' Since '+date(prev.at)+', its score changed '+sign(h.score_change)+' points. Historical factor attribution is unavailable.';}});
        if(d.groups) d.groups.monitor=(d.holdings||[]).map(h=>({symbol:h.symbol,weight_pct:h.weight_pct,score:h.composite,
          priority:h.weight_pct+(h.news||[]).reduce((s,n)=>s+n.relevance,0)+(finite(h.score_change)?Math.abs(h.score_change)*h.weight_pct/100:0)+(finite(h.technical)&&h.technical<40?h.weight_pct*.5:0),
          reasons:[pct(h.weight_pct)+' capital; '+(h.news||[]).length+' mapped developments'+(finite(h.score_change)?'; score change '+sign(h.score_change)+' points':''), 'Position weight + events + measured score change + major technical weakness']})).sort((a,b)=>b.priority-a.priority).slice(0,5);
      }
      if(!prev||prev.at!==current.at){list.push(current);store[key]=list.slice(-10);}
      const keys=Object.keys(store).sort((a,b)=>new Date(store[b].at(-1)?.at)-new Date(store[a].at(-1)?.at));
      keys.slice(20).forEach(k=>delete store[k]);localStorage.setItem(SNAP_KEY,JSON.stringify(store));
    }catch(e){d.snapshot_note='Review history could not be saved in this browser. The current report remains available.';}
    return d;
  }
  function exportHTML(d,css) {
    const box=document.createElement('div');box.innerHTML=build(d,true);
    box.querySelectorAll('canvas').forEach(canvas=>{const live=document.getElementById(canvas.id);try{if(!live||!live.width)throw Error();const img=document.createElement('img');img.src=live.toDataURL('image/png');img.alt=canvas.getAttribute('aria-label');img.style='max-width:100%;height:auto';canvas.parentElement.replaceWith(img);}catch(e){canvas.parentElement.remove();}});
    box.querySelectorAll('details').forEach(el=>el.open=true);box.querySelectorAll('button').forEach(el=>{const span=document.createElement('span');span.className=el.className;span.innerHTML=el.innerHTML;el.replaceWith(span);});
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Altaha Portfolio Intelligence</title><style>'+css+'\n.pi-root{max-width:1180px;margin:auto}.pi-grid{display:block}.pi-card{margin-bottom:20px}body{background:#fff;color:#202824;padding:20px}details{break-inside:avoid}</style><body>'+box.innerHTML+'</body></html>';
  }
  root.PortfolioIntelligence={mount,build,compare,snapshot,acceptSnapshot,exportHTML,destroy};
  if(typeof module!=='undefined')module.exports={compare,snapshot,build,allocation,sectorComparison,safeURL};
  if(typeof MutationObserver!=='undefined'&&typeof document!=='undefined')new MutationObserver(()=>{if(state.report&&root.Chart)draw(state.report);}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
})(typeof window!=='undefined'?window:globalThis);
