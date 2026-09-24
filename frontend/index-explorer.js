(function(root,factory){var api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AltahaIndex=api;})(typeof window!=='undefined'?window:this,function(){
'use strict';
var dialog, state={index:'',level:'basic',window:'1D',group:null,c:null,p:null,catalog:[],error:'',loading:false},seq=0,timer,opener;
var esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
var pct=v=>v==null?'—':(v>0?'+':'')+Number(v).toFixed(2)+'%';
var tone=v=>v==null?'unknown':v>0?'up':v<0?'down':'flat';
function layout(items,x=0,y=0,w=100,h=100){
 if(!items.length)return[]; if(items.length===1)return[{...items[0],x,y,w,h}];
 var total=items.reduce((s,r)=>s+r.weight_pct,0),sum=0,cut=1;
 for(var i=0;i<items.length-1;i++){sum+=items[i].weight_pct;cut=i+1;if(sum>=total/2)break;}
 var ratio=total?sum/total:cut/items.length;
 return w>=h?layout(items.slice(0,cut),x,y,w*ratio,h).concat(layout(items.slice(cut),x+w*ratio,y,w*(1-ratio),h)):
 layout(items.slice(0,cut),x,y,w,h*ratio).concat(layout(items.slice(cut),x,y+h*ratio,w,h*(1-ratio)));
}
function groupReturn(group,stocks){
 var known=group.stocks.filter(s=>stocks[s.symbol]&&stocks[s.symbol].change_pct!=null);
 if(known.length!==group.stocks.length)return null;
 var total=known.reduce((s,r)=>s+r.weight_pct,0);
 return total?known.reduce((s,r)=>s+r.weight_pct*stocks[r.symbol].change_pct,0)/total:null;
}
function entries(){var c=state.c||{},stocks=(state.p||{}).stocks||{},g=(c.groups||[]).find(g=>g.name===state.group);
 return (g?g.stocks.map(s=>({...s,name:s.symbol,change:stocks[s.symbol]?.change_pct,stock:true})):(c.groups||[]).map(g=>({...g,change:groupReturn(g,stocks)}))).sort((a,b)=>b.weight_pct-a.weight_pct);
}
function render(){
 if(!dialog)return;
 var focus=dialog.contains(document.activeElement)?document.activeElement?.dataset.key:null;
 var c=state.c||{},p=state.p||{},items=entries(),rects=layout(items.filter(r=>r.weight_pct>0));
 var controls='<div class="ix-controls"><label>Index<select data-key="index" aria-label="Choose NSE index">'+state.catalog.map(r=>'<option value="'+esc(r.id)+'"'+(r.id===state.index?' selected':'')+'>'+esc(r.name)+'</option>').join('')+'</select></label><label>Group by<select data-key="level">'+[['macro','Macro sector'],['sector','Sector'],['industry','Industry'],['basic','Basic industry']].map(r=>'<option value="'+r[0]+'"'+(state.level===r[0]?' selected':'')+'>'+r[1]+'</option>').join('')+'</select></label></div>';
 dialog.innerHTML='<header class="ix-top"><span>ALTAHA / INDEX EXPLORER</span><button data-key="close" aria-label="Close index explorer">×</button></header>'+controls+
 '<section class="ix-hero"><div><span class="ix-kicker">INSIDE THE INDEX</span><h2>'+esc(c.name||state.index)+'</h2><span class="ix-level">'+(p.index_level==null?'Level unavailable':Number(p.index_level).toLocaleString('en-IN',{maximumFractionDigits:2})+' index points')+'</span></div><div class="ix-return '+tone(p.change_pct)+'"><strong>'+pct(p.change_pct)+'</strong><span>'+({ '1D':'Day','1W':'7-day','1M':'30-day'}[state.window])+' price change</span></div></section>'+
 '<div class="ix-periods" aria-label="Return period">'+[['1D','Day'],['1W','Week · 7D'],['1M','Month · 30D']].map(r=>'<button data-window="'+r[0]+'" data-key="'+r[0]+'" aria-pressed="'+(state.window===r[0])+'">'+r[1]+'</button>').join('')+'</div>'+
 '<p class="ix-status" role="status">'+(state.loading?'Refreshing exchange data…':esc(state.error||((c.stale||p.stale)?'Refresh failed · dated last available data shown':'Published NSE composition and price data')) )+'</p>'+
 '<div class="ix-map-head"><button data-key="back"'+(!state.group?' disabled':'')+'>← '+(state.group?'All groups':'Composition')+'</button><span>'+esc(state.group||'Tap a group to explore its stocks')+'</span></div>'+
 '<p class="ix-legend">Tile area = index weight · Colour = '+(state.group?'stock price change':'weighted member price change')+'</p>'+
 (items.length?'<div class="ix-map" aria-label="Index composition map">'+rects.map((r,i)=>{
 var small=r.w*r.h<500;
 return '<button class="ix-cell '+tone(r.change)+(small?' ix-small':'')+'" style="left:'+r.x+'%;top:'+r.y+'%;width:'+r.w+'%;height:'+r.h+'%;--ix-delay:'+Math.min(i*30,240)+'ms" data-item="'+esc(r.name)+'" aria-label="'+esc(r.name)+', weight '+r.weight_pct.toFixed(2)+' percent, return '+pct(r.change)+'"><span>'+esc(r.name)+'</span><strong>'+r.weight_pct.toFixed(2)+'<small>% weight</small></strong><em>'+pct(r.change)+'<small> return</small></em></button>';}).join('')+'</div>':'<div class="ix-empty">'+(state.loading?'Loading the published composition…':'NSE composition is unavailable for this index or grouping. Try another grouping; weights are never estimated.')+'</div>')+
 '<div class="ix-list">'+items.map(r=>'<div class="ix-row"><button data-item="'+esc(r.name)+'">'+esc(r.name)+(r.stock?' ↗':' →')+'</button><div><strong>'+r.weight_pct.toFixed(2)+'%</strong><small>index weight</small></div><div class="'+tone(r.change)+'"><strong>'+pct(r.change)+'</strong><small>return</small></div></div>').join('')+'</div>'+
 '<footer class="ix-foot"><p>Composition effective '+esc(c.as_of||'date unavailable')+'. Index quote '+esc(p.index_as_of||'unavailable')+'. Stock quotes '+esc(p.stocks_as_of||'unavailable')+'.</p>'+
 (p.baseline_date?'<p>Index comparison close: '+esc(p.baseline_date)+'. Stock comparison close: '+esc(p.stock_baseline_date||'unavailable')+'.</p>':'')+
 '<p>Weights are checked hourly while viewed and retain their published effective date. Group returns are averages using current weights, not official subgroup index returns. Missing member prices leave the group return unavailable. Stock returns are unadjusted for corporate actions.</p>'+ 
 '<a href="https://www.niftyindices.com/indices/equity" target="_blank" rel="noopener">NSE index definitions ↗</a></footer>';
 if(focus)dialog.querySelector('[data-key="'+focus+'"]')?.focus({preventScroll:true});
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
 dialog.addEventListener('close',()=>{seq++;clearInterval(timer);opener?.focus?.({preventScroll:true});});
 dialog.addEventListener('click',e=>{var b=e.target.closest('button');if(!b)return;
 if(b.dataset.key==='close'){dialog.close();return;}
 if(b.dataset.key==='back'){state.group=null;render();return;}
 if(b.dataset.window){state.window=b.dataset.window;state.p=null;load();return;}
 if(b.dataset.item){if(state.group){location.href='stock.html?ticker='+encodeURIComponent(b.dataset.item);}else{state.group=b.dataset.item;render();dialog.querySelector('[data-key="back"]')?.focus();}}});
 dialog.addEventListener('change',e=>{if(e.target.dataset.key==='index'){state.index=e.target.value;state.group=null;state.c=null;state.p=null;load();}if(e.target.dataset.key==='level'){state.level=e.target.value;state.group=null;state.c=null;load();}});
 }
 opener=document.activeElement;state.index=String(index||'NIFTY 50').toUpperCase();state.c=null;state.p=null;state.group=null;state.loading=true;
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
return {open,layout,groupReturn};
});
