/* Delivery visuals use exchange observations only. No synthetic chart points. */
(function(root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AltahaDelivery = api;
})(typeof window !== 'undefined' ? window : this, function() {
  'use strict';
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function num(v) { return v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null; }
  function percent(v) { var n=num(v); return n !== null && n>=0 && n<=100 ? n : null; }
  function pct(v) { var n=percent(v); return n===null ? '—' : n.toFixed(2)+'%'; }
  function qty(v) { var n=num(v); return n===null ? '—' : n>=1e7 ? (n/1e7).toFixed(2)+' cr' : n>=1e5 ? (n/1e5).toFixed(2)+' L' : n.toLocaleString('en-IN'); }
  function pp(v) { return (v>0?'+':'')+v.toFixed(2)+' pp'; }
  function day(v) { var d = new Date(String(v)+'T12:00:00Z'); return Number.isFinite(d.getTime()) ? d.toLocaleDateString('en-IN',{day:'numeric',month:'short',timeZone:'UTC'}) : String(v || 'Date unavailable'); }
  function tile(label,value,note) { return '<div class="dv-tile"><div class="k">'+esc(label)+'</div><div class="v tnum">'+value+'</div><div class="n">'+note+'</div></div>'; }
  function session(r, i, avg, derived) {
    var p=percent(r.deliv_pct), diff=p!==null && percent(avg)!==null ? p-Number(avg) : null;
    return '<article class="dv-session" style="--dv-delay:'+Math.min(i*30,240)+'ms">'+
      '<div class="dv-session-head"><time datetime="'+esc(r.date)+'">'+esc(day(r.date))+'</time><strong>'+pct(p)+'</strong></div>'+
      '<div class="dv-meter" aria-hidden="true"><i style="width:'+(p===null?0:p)+'%"></i></div>'+
      '<p class="dv-session-compare">'+(diff===null?'Average comparison unavailable':pp(diff)+' vs 20-session average')+'</p>'+
      '<dl><div><dt>Delivered'+(derived?' · est.':'')+'</dt><dd>'+qty(r.delivered_qty)+'</dd></div><div><dt>Traded</dt><dd>'+qty(r.traded_qty)+'</dd></div><div><dt>Close · ₹</dt><dd>'+(num(r.close)===null?'—':Number(r.close).toLocaleString('en-IN',{maximumFractionDigits:2,minimumFractionDigits:2}))+'</dd></div></dl></article>';
  }
  function chart(rows, average) {
    var sorted=rows.slice().sort(function(a,b){return String(a.date).localeCompare(String(b.date));});
    var avg=percent(average), path='', prior=false;
    var dots=sorted.map(function(r,i) {
      var p=percent(r.deliv_pct), x=46+(sorted.length>1?i/(sorted.length-1):.5)*626;
      if(p===null){prior=false; return '';}
      var y=20+(100-p)*2;
      path+=(prior?' L':' M')+x.toFixed(2)+' '+y.toFixed(2);prior=true;
      return '<circle cx="'+x.toFixed(2)+'" cy="'+y.toFixed(2)+'" r="'+(sorted.length<30?3:2)+'"><title>'+esc(r.date)+': '+pct(p)+'</title></circle>';
    }).join('');
    var grid=[0,25,50,75,100].map(function(p){var y=20+(100-p)*2;return '<line class="dv-gridline" x1="46" x2="672" y1="'+y+'" y2="'+y+'"/><text x="35" y="'+(y+4)+'" text-anchor="end">'+p+'%</text>';}).join('');
    return '<div class="dv-chart"><svg viewBox="0 0 700 252" role="img" aria-label="Delivered share by session on a zero to one hundred percent scale. Dashed line shows the current 20-session average.">'+grid+
      (avg===null?'':'<line class="dv-average" x1="46" x2="672" y1="'+(20+(100-avg)*2)+'" y2="'+(20+(100-avg)*2)+'"/>')+
      '<path class="dv-trend-line" pathLength="1" d="'+path+'"/><g class="dv-chart-dots">'+dots+'</g>'+
      (sorted.length?'<text x="46" y="246">'+esc(day(sorted[0].date))+'</text><text x="672" y="246" text-anchor="end">'+esc(day(sorted[sorted.length-1].date))+'</text>':'')+
      '</svg></div>';
  }
  function render(d) {
    var s=d.summary||{}, rows=(d.rows||[]).slice().sort(function(a,b){return String(b.date).localeCompare(String(a.date));});
    var latest=percent(s.latest), avg=percent(s.avg_20), diff=latest!==null&&avg!==null?latest-avg:null;
    var state=diff===null?'Delivery overview':Math.abs(diff)<.005?'In line with its average':diff>0?'Above its usual share':'Below its usual share';
    var note=diff===null?'A comparison appears when both readings are available.':pp(diff)+' compared with the 20-session average. This measures delivered share, not buying or selling direction.';
    var ring='<svg viewBox="0 0 180 180" aria-hidden="true"><circle class="dv-ring-track" cx="90" cy="90" r="72"/>'+
      (latest===null?'':'<circle class="dv-ring-fill" cx="90" cy="90" r="72" pathLength="100" stroke-dasharray="'+latest+' 100"/>')+'</svg>';
    var hero='<section class="dv-hero"><div class="dv-hero-copy"><span class="dv-eyebrow">DELIVERY PULSE · '+esc(d.symbol)+'</span><h3>'+state+'</h3><p>'+esc(note)+'</p><span class="dv-date">Latest session · '+esc(d.as_of||'Date unavailable')+'</span></div><div class="dv-ring">'+ring+'<div><strong>'+pct(latest)+'</strong><span>delivered share</span></div></div></section>';
    var tiles='<div class="dv-tiles">'+tile('Latest session',pct(latest),'Of traded quantity')+tile('5-session average',pct(s.avg_5),'Recent sessions')+tile('20-session average',pct(avg),'Your comparison baseline')+tile('Longer average',pct(s.avg_year),esc(s.year_sessions||0)+' sessions held')+'</div>';
    var filling=d.backfilling?'<p class="dv-filling">Older sessions are still being loaded. Averages currently cover '+esc(d.sessions_held)+' sessions held.</p>':'';
    var trend='<section class="dv-trend"><div class="dv-section-head"><div><span class="dv-eyebrow">THE BIGGER PICTURE</span><h3>How delivery is changing</h3></div><span>'+rows.length+' sessions shown</span></div><div class="dv-legend"><span><i></i>Delivered share</span><span><i class="dv-dashed"></i>20-session average · '+pct(avg)+'</span></div>'+chart(rows,avg)+
      (rows.length?'<label class="dv-scrub-label" for="dv-session-slider">Explore a session <span>Drag or use arrow keys</span></label><input id="dv-session-slider" class="dv-slider" type="range" min="0" max="'+(rows.length-1)+'" value="'+(rows.length-1)+'" aria-valuetext="'+esc(rows[0].date+' · '+pct(rows[0].deliv_pct))+'"/><div class="dv-selected" aria-live="polite">'+session(rows[0],0,avg,d.delivered_qty_derived)+'</div>':'<p class="dv-note">No session history is available for this window.</p>')+'</section>';
    var cards='<section class="dv-history"><div class="dv-section-head"><div><span class="dv-eyebrow">SESSION BY SESSION</span><h3>The latest readings</h3></div><span>Bars use a 0–100% scale</span></div><div class="dv-session-grid">'+rows.slice(0,6).map(function(r,i){return session(r,i,avg,d.delivered_qty_derived);}).join('')+'</div>'+
      (rows.length>6?'<details class="dv-more"><summary>Show '+(rows.length-6)+' earlier sessions</summary><div class="dv-session-grid">'+rows.slice(6).map(function(r,i){return session(r,i,avg,d.delivered_qty_derived);}).join('')+'</div></details>':'')+'</section>';
    var tbody=rows.map(function(r){return '<tr><th scope="row" class="dv-d">'+esc(r.date)+'</th><td>'+pct(r.deliv_pct)+'</td><td title="'+esc(num(r.delivered_qty)===null?'Quantity unavailable':Number(r.delivered_qty).toLocaleString('en-IN')+' shares'+(d.delivered_qty_derived?', derived':''))+'">'+qty(r.delivered_qty)+'</td><td>'+qty(r.traded_qty)+'</td><td>'+(num(r.close)===null?'—':Number(r.close).toFixed(2))+'</td></tr>';}).join('');
    return '<div class="dv-experience">'+hero+tiles+filling+trend+cards+
      '<details class="dv-data"><summary>View full data table <span>'+rows.length+' sessions</span></summary><div class="fu-wrap"><table class="fu-table dv-table"><caption class="fu-vh">Daily delivery for '+esc(d.symbol)+'</caption><thead><tr><th scope="col">Session</th><th scope="col">Delivered share</th><th scope="col">Delivered</th><th scope="col">Traded</th><th scope="col">Close</th></tr></thead><tbody>'+tbody+'</tbody></table></div></details>'+
      '<p class="dv-note">Source: '+esc(d.source||'NSE full bhavcopy')+'. '+(d.delivered_qty_derived?'Delivered quantity is derived from traded quantity × published delivery percentage and inherits its rounding. “Est.” labels this derived quantity. ':'')+'A higher delivery share does not identify who bought or sold. Missing values are shown as —.</p></div>';
  }
  function mount(host,d) {
    host.innerHTML=render(d);
    var slider=host.querySelector('#dv-session-slider'), selected=host.querySelector('.dv-selected');
    var rows=(d.rows||[]).slice().sort(function(a,b){return String(a.date).localeCompare(String(b.date));});
    if(slider) slider.addEventListener('input',function(){var r=rows[Number(slider.value)];if(!r)return; slider.setAttribute('aria-valuetext',r.date+' · '+pct(r.deliv_pct));selected.innerHTML=session(r,0,(d.summary||{}).avg_20,d.delivered_qty_derived);});
  }
  return {render:render,mount:mount,chart:chart,percent:percent};
});
