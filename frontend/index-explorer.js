(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AltahaIndex=api;})(typeof window!=='undefined'?window:this,function(){
'use strict';
var dialog, state={index:'',level:'basic',window:'1D',group:null,c:null,p:null,catalog:[],error:'',loading:false},seq=0,timer,opener;
var esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
var pct=v=>v==null?'—':(v>0?'+':'')+Number(v).toFixed(2)+'%';
var tone=v=>v==null?'unknown':v>0?'up':v<0?'down':'flat';
function groupReturn(group,stocks){
 var known=group.stocks.filter(s=>stocks[s.symbol]&&stocks[s.symbol].change_pct!=null);
 if(known.length!==group.stocks.length)return null;
 var total=known.reduce((s,r)=>s+r.weight_pct,0);
 return total?known.reduce((s,r)=>s+r.weight_pct*stocks[r.symbol].change_pct,0)/total:null;
}
function entries(){var c=state.c||{},stocks=(state.p||{}).stocks||{},g=(c.groups||[]).find(g=>g.name===state.group);
 return (g?g.stocks.map(s=>({...s,name:s.symbol,change:stocks[s.symbol]?.change_pct,stock:true})):(c.groups||[]).map(g=>({...g,change:groupReturn(g,stocks)}))).sort((a,b)=>b.weight_pct-a.weight_pct);
}
var COLORS=['#b99648','#588f88','#7985ac','#b78169','#899a60','#b88aa8','#648caa','#9a906e'];
function compositionView(items,group){
 var total=items.reduce((s,r)=>s+r.weight_pct,0),offset=0;
 var segments=items.map((r,i)=>{
  var share=total>0?r.weight_pct/total*100:0,start=offset;offset+=share;
  return '<circle class="ix-segment" data-segment="'+i+'" cx="150" cy="150" r="112" pathLength="100" style="--segment:'+COLORS[i%COLORS.length]+';--slice:'+share+';--delay:'+Math.min(i*35,350)+'ms" stroke-dasharray="'+share+' '+(100-share)+'" stroke-dashoffset="'+(-start)+'"><title>'+esc(r.name)+' · '+r.weight_pct.toFixed(2)+'% index weight</title></circle>';
 }).join('');
 var largest=items[0];
 return '<section class="ix-composition"><aside class="ix-observatory"><span class="ix-kicker">'+(group?'INSIDE THIS GROUP':'THE INDEX, UNPACKED')+'</span><div class="ix-orbit"><svg viewBox="0 0 300 300" role="img" aria-label="Composition by '+(group?'stock':'group')+' weight"><circle class="ix-orbit-guide" cx="150" cy="150" r="139"/><circle class="ix-orbit-guide" cx="150" cy="150" r="89"/><g transform="rotate(-90 150 150)">'+segments+'</g></svg><div class="ix-orbit-center"><strong>'+items.length+'</strong><span>'+(group?'constituents':'market groups')+'</span></div></div><p class="ix-orbit-caption">'+(group?'Segments show each stock’s share of this group.':'Each segment follows the published index weight.')+'</p>'+
 (largest?'<div class="ix-concentration"><span>LARGEST '+(group?'HOLDING':'GROUP')+'</span><strong>'+esc(largest.name)+'</strong><b>'+largest.weight_pct.toFixed(2)+'% <small>of the index</small></b></div>':'')+'</aside>'+
 '<div class="ix-holdings"><div class="ix-holdings-title"><h3>'+(group?'Meet the companies':'Explore the composition')+'</h3><p>'+(group?'Open a company to research it.':'Select a group to reveal its companies.')+'</p></div><div class="ix-cards">'+items.map((r,i)=>
 '<button class="ix-holding" data-item="'+esc(r.name)+'" data-highlight="'+i+'" style="--segment:'+COLORS[i%COLORS.length]+';--delay:'+Math.min(i*35,350)+'ms"><span class="ix-rank">'+String(i+1).padStart(2,'0')+'</span><span class="ix-holding-body"><span class="ix-holding-name">'+esc(r.name)+'<i aria-hidden="true">'+(r.stock?'↗':'→')+'</i></span><span class="ix-holding-metrics"><span><strong>'+r.weight_pct.toFixed(2)+'%</strong><small>index weight</small></span><span class="ix-badge '+tone(r.change)+'"><strong>'+pct(r.change)+'</strong><small>'+(r.stock?'price return':'member return')+'</small></span></span><span class="ix-weight-track" aria-hidden="true"><i style="width:'+Math.max(0,Math.min(100,r.weight_pct))+'%"></i></span></span></button>'
 ).join('')+'</div></div></section>';
}
var visualKey='';
function render(){
 if(!dialog)return;
 var active=dialog.contains(document.activeElement)?document.activeElement:null;
 var focus=active?.dataset.key, focusedItem=active?.dataset.item, scroll=dialog.scrollTop;
 var c=state.c||{},p=state.p||{},items=entries();
 var nextKey=state.index+'|'+state.level+'|'+state.group+'|'+JSON.stringify(items.map(r=>[r.name,r.weight_pct]));
 var retained=nextKey===visualKey?dialog.querySelector('.ix-composition'):null;visualKey=nextKey;
 var controls='<div class="ix-controls"><label>Index<select data-key="index" aria-label="Choose NSE index">'+state.catalog.map(r=>'<option value="'+esc(r.id)+'"'+(r.id===state.index?' selected':'')+'>'+esc(r.name)+'</option>').join('')+'</select></label><label>Group by<select data-key="level">'+[['macro','Macro sector'],['sector','Sector'],['industry','Industry'],['basic','Basic industry']].map(r=>'<option value="'+r[0]+'"'+(state.level===r[0]?' selected':'')+'>'+r[1]+'</option>').join('')+'</select></label></div>';
 dialog.innerHTML='<header class="ix-top"><span>ALTAHA <b>INDEX ATLAS</b></span><button data-key="close" aria-label="Close index explorer">×</button></header>'+controls+
 '<section class="ix-hero"><div><span class="ix-kicker">INSIDE THE INDEX</span><h2>'+esc(c.name||state.index)+'</h2><span class="ix-level">'+(p.index_level==null?'Level unavailable':Number(p.index_level).toLocaleString('en-IN',{maximumFractionDigits:2})+' index points')+'</span></div><div class="ix-return '+tone(p.change_pct)+'"><strong>'+pct(p.change_pct)+'</strong><span>'+({ '1D':'Day','1W':'7-day','1M':'30-day'}[state.window])+' price change</span></div></section>'+
 '<div class="ix-periods" aria-label="Return period">'+[['1D','Day'],['1W','Week · 7D'],['1M','Month · 30D']].map(r=>'<button data-window="'+r[0]+'" data-key="'+r[0]+'" aria-pressed="'+(state.window===r[0])+'">'+r[1]+'</button>').join('')+'</div>'+
 '<p class="ix-status" role="status">'+(state.loading?'Refreshing exchange data…':esc(state.error||((c.stale||p.stale)?'Refresh failed · dated last available data shown':'Published NSE composition and price data')) )+'</p>'+
 '<div class="ix-map-head"><button data-key="back"'+(!state.group?' disabled':'')+'>← '+(state.group?'All groups':'Composition')+'</button><span>'+esc(state.group||'Tap a group to explore its stocks')+'</span></div>'+
 (items.length?compositionView(items,state.group):'<div class="ix-empty">'+(state.loading?'Reading the published composition…':'Composition is unavailable for this index or grouping. Try another grouping.')+'</div>')+
 '<footer class="ix-foot"><p>Composition effective '+esc(c.as_of||'date unavailable')+'. Index quote '+esc(p.index_as_of||'unavailable')+'. Stock quotes '+esc(p.stocks_as_of||'unavailable')+'.</p>'+
 (p.baseline_date?'<p>Index comparison close: '+esc(p.baseline_date)+'. Stock comparison close: '+esc(p.stock_baseline_date||'unavailable')+'.</p>':'')+
 '<p>Weights are checked hourly while viewed and retain their published effective date. Group returns are averages using current weights, not official subgroup index returns. Missing member prices leave the group return unavailable. Stock returns are unadjusted for corporate actions.</p>'+ 
 '<a href="https://www.niftyindices.com/indices/equity" target="_blank" rel="noopener">NSE index definitions ↗</a></footer>';
 if(retained){
  dialog.querySelector('.ix-composition')?.replaceWith(retained);
  retained.querySelectorAll('[data-item]').forEach(card=>{var r=items.find(x=>x.name===card.dataset.item);if(!r)return;var badge=card.querySelector('.ix-badge');badge.className='ix-badge '+tone(r.change);badge.querySelector('strong').textContent=pct(r.change);});
 } else dialog.querySelector('.ix-composition')?.classList.add('ix-intro');
 if(focus)dialog.querySelector('[data-key="'+focus+'"]')?.focus({preventScroll:true});
 if(focusedItem)Array.from(dialog.querySelectorAll('[data-item]')).find(el=>el.dataset.item===focusedItem)?.focus({preventScroll:true});
 dialog.scrollTop=scroll;
}
async function get(path){var base=window.API_BASE||(typeof API_BASE!=='undefined'?API_BASE:'https://taha-project.onrender.com');var r=await fetch(base+path,{signal:AbortSignal.timeout(90000)});if(!r.ok)throw Error('Exchange data unavailable');return r.json();}
async function load(){
 var token=++seq;state.loading=true;state.error='';render();
 var q='?index='+encodeURIComponent(state.index);
 var results=await Promise.allSettled([get('/index/composition'+q+'&level='+state.level).then(v=>{if(token===seq&&dialog.open){state.c=v;render();}return v;}),get('/index/performance'+q+'&window='+state.window).then(v=>{if(token===seq&&dialog.open){state.p=v;render();}return v;})]);
 if(token!==seq||!dialog.open)return;
 state.c=results[0].status==='fulfilled'?results[0].value:null;state.p=results[1].status==='fulfilled'?results[1].value:null;
 state.loading=false;state.error=results.some(r=>r.status==='rejected')?'Some exchange data could not be loaded. Try another period or reopen to retry.':'';render();
}
async function open(index){
 if(!dialog){dialog=document.createElement('dialog');dialog.className='ix-dialog';dialog.setAttribute('aria-label','NSE index composition and returns');document.body.appendChild(dialog);
 dialog.addEventListener('pointerover',e=>highlight(e.target.closest('[data-highlight]')?.dataset.highlight));
 dialog.addEventListener('pointerleave',()=>highlight(null));
 dialog.addEventListener('focusin',e=>highlight(e.target.closest('[data-highlight]')?.dataset.highlight));
 function highlight(value){dialog.querySelectorAll('.ix-segment').forEach(el=>{el.classList.toggle('ix-dim',value!=null&&el.dataset.segment!==value);el.classList.toggle('ix-lit',value!=null&&el.dataset.segment===value);});}
 dialog.addEventListener('close',()=>{seq++;clearInterval(timer);opener?.focus?.({preventScroll:true});});
 dialog.addEventListener('click',e=>{var b=e.target.closest('button');if(!b)return;
 if(b.dataset.key==='close'){dialog.close();return;}
 if(b.dataset.key==='back'){state.group=null;render();return;}
 if(b.dataset.window){state.window=b.dataset.window;state.p=null;load();return;}
 if(b.dataset.item){if(state.group){location.href='stock.html?ticker='+encodeURIComponent(b.dataset.item);}else{state.group=b.dataset.item;render();dialog.querySelector('[data-key="back"]')?.focus();}}});
 dialog.addEventListener('change',e=>{if(e.target.dataset.key==='index'){state.index=e.target.value;state.group=null;state.c=null;state.p=null;load();}if(e.target.dataset.key==='level'){state.level=e.target.value;state.group=null;state.c=null;load();}});
 }
 opener=document.activeElement;visualKey='';state.index=String(index||'NIFTY 50').toUpperCase();state.c=null;state.p=null;state.group=null;state.loading=true;
 if(!dialog.open)dialog.showModal();render();
 var token=++seq;
 try{var catalog=await get('/index/catalog');if(token!==seq||!dialog.open)return;state.catalog=catalog.indices||[];var canon=v=>String(v).toUpperCase().replace(/ INDEX$/,'').replace('OIL AND GAS','OIL & GAS');var hit=state.catalog.find(r=>canon(r.id)===canon(state.index)||canon(r.name)===canon(state.index));if(hit){state.index=hit.id;state.level=hit.kind==='sc'?'basic':'sector';}await load();}
 catch(e){if(token===seq&&dialog.open){state.loading=false;state.error='NSE index catalogue is unavailable. Close and retry.';render();}}
 clearInterval(timer);timer=setInterval(()=>{if(dialog.open&&!document.hidden&&!state.loading)load();},60000);
}
if(typeof document!=='undefined') {
 var launch=e=>{var el=e.target.closest('[data-index-explore]');if(!el)return;if(e.type==='keydown'&&!['Enter',' '].includes(e.key))return;e.preventDefault();open(el.dataset.indexExplore);};
 document.addEventListener('click',launch);document.addEventListener('keydown',launch);
}
return {open,groupReturn,compositionView};
});
