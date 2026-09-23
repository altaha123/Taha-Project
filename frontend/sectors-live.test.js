/* Exercise the board's real fetch/render/window handlers without a network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {}, calls = [];
const host = {innerHTML:'', contains:node=>!!node, querySelectorAll:()=>[]};
let failure = false;
const payload = {
  available:true, source:'NSE', as_of:'23-Sep-2026 15:30:00',
  rows:[{sector:'Nifty Financial Services', index_level:105, change_pct:5, relative_pp:3, icon:'bank'},
        {sector:'Nifty IT', index_level:null, change_pct:null, relative_pp:null, icon:'chip'}],
  method:'Published NSE price indices.'
};
const context = {
  console, setTimeout:f=>f(), setInterval:()=>1, requestAnimationFrame:f=>f(),
  matchMedia:()=>({matches:false}), getComputedStyle:()=>({display:'block'}),
  document:{readyState:'complete',hidden:false,activeElement:null,
    documentElement:{dataset:{}}, getElementById:id=>id==='sb-board'?host:null,
    querySelector:()=>null, addEventListener:(type,f)=>listeners[type]=f},
  fetch:async url=>{calls.push(url); if(failure) throw new Error('offline');
    return {ok:true,json:async()=>({...payload,window:new URL(url).searchParams.get('window')})};}
};
context.window = context;
const settle = ()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  vm.runInNewContext(fs.readFileSync('frontend/sectors-live.js','utf8'),context);
  await settle();
  assert.match(calls[0],/\/sector\/benchmarks\?window=1D$/);
  assert.match(host.innerHTML,/Nifty Financial Services/);
  assert.match(host.innerHTML,/\+5.00%/);
  assert.match(host.innerHTML,/3.00 pp vs Nifty 50/);
  assert.match(host.innerHTML,/Return unavailable/);
  assert.doesNotMatch(host.innerHTML,/advancing|equal-weight|Live feed/);
  listeners.click({target:{closest:sel=>sel.includes('sb-tile')?{getAttribute:()=> 'Nifty Financial Services'}:null}});
  assert.match(host.innerHTML,/Benchmark calculation/);
  assert.match(host.innerHTML,/Exchange timestamp: 23-Sep-2026 15:30:00 IST/);
  host.contains=()=>true;
  listeners.click({target:{closest:sel=>sel.includes('sb-win')?{getAttribute:()=> '1W'}:null}});
  await settle();
  assert.match(calls.at(-1),/window=1W$/);
  failure=true;
  // Exercise a refresh error with an existing snapshot through the timer callback.
  // Reload clears the old snapshot intentionally; it must show the error state.
  context.AltahaSectors.reload();
  await settle();
  assert.match(host.innerHTML,/Engine unreachable/);
  console.log('NSE board rendering, unavailable values, details and window switching passed');
})().catch(e=>{console.error(e);process.exitCode=1});
