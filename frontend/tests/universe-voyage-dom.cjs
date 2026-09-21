/* Run with jsdom available on NODE_PATH. A controlled clock verifies animation
   lifecycle and scan truthfulness without timing-dependent screenshot assertions. */
const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
function fixture({reduced=false,noCanvas=false}={}){
  const dom=new JSDOM('<body><div id="view-ideas"><div class="hzrow"><button id="horizon">Short term</button></div><div class="brun"><button id="genbtn2">Scan</button></div><div id="scan-universe"></div></div><div id="scan-results"></div></body>',{runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,queue=new Map();let id=0,draws=0,now=0,intersect,changePreference;
  const media={matches:reduced,addEventListener(_,fn){changePreference=fn},removeEventListener(){}};
  w.matchMedia=()=>media;
  w.IntersectionObserver=class{constructor(fn){intersect=fn}observe(){}disconnect(){}};
  w.ResizeObserver=class{observe(){}disconnect(){}};
  w.requestAnimationFrame=fn=>{queue.set(++id,fn);return id};w.cancelAnimationFrame=id=>queue.delete(id);
  w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden]')?[]:[{}]};
  w.HTMLCanvasElement.prototype.getBoundingClientRect=()=>({width:390,height:470});
  const gradient={addColorStop(){}};
  const ctx=new Proxy({}, {get(_,key){if(key==='createRadialGradient'||key==='createLinearGradient')return ()=>gradient;if(key==='fillRect')return ()=>draws++;return ()=>{}},set(){return true}});
  w.HTMLCanvasElement.prototype.getContext=()=>noCanvas?null:ctx;
  const button=w.document.querySelector('#genbtn2');let clicks=0;button.onclick=()=>clicks++;
  for(const name of ['universe-voyage','universe-scan'])w.eval(fs.readFileSync(path.join(__dirname,'../'+name+'.js'),'utf8'));
  const update=s=>w.AltahaUniverse.update(s);
  const advance=(frames=5)=>{for(let i=0;i<frames;i++){now+=40;const pending=[...queue.values()];queue.clear();pending.forEach(fn=>fn(now))}};
  const $=selector=>w.document.querySelector(selector);
  return {dom,w,queue,update,advance,$,get draws(){return draws},setVisible(v){intersect([{isIntersecting:v}])},setReduced(v){media.matches=v;changePreference()},get clicks(){return clicks}};
}
const f=fixture();
try{
  f.update({status:'cached'});let before=f.draws;f.advance();assert(f.draws>before,'saved universe must animate');assert.equal(f.queue.size,1,'only one animation loop');
  assert.equal(f.$('#scan-results').hidden,false);assert.equal(f.$('.su-card'),null,'space tour cannot invent stock discoveries');
  assert.match(f.$('.su-voyage-place').textContent,/Entering the galaxy/);
  f.advance(180);assert.equal(f.$('.su-voyage-place').textContent,'Jupiter');
  assert.equal(f.$('#scan-universe').dataset.voyage,'planet');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'Venus');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'Saturn');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'Mars');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'Neptune');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'An undiscovered world');
  f.advance(300);assert.equal(f.$('.su-voyage-place').textContent,'Jupiter','journey loops');
  f.$('#genbtn2').click();assert.equal(f.clicks,1,'moved scan control retains handler');
  f.$('.su-motion').click();before=f.draws;f.advance();assert.equal(f.draws,before,'pause freezes drawing');assert.equal(f.queue.size,0);
  f.update({status:'running',run_id:'one',done:30,total:100});assert.equal(f.queue.size,0,'engine polling cannot override pause');assert.equal(f.$('progress').value,30);assert.equal(f.$('#scan-results').hidden,true);
  f.$('.su-motion').click();f.advance();assert(f.draws>before);assert.equal(f.queue.size,1);
  for(let i=0;i<5;i++)f.update({status:'running',run_id:'one',done:30,total:100});assert.equal(f.queue.size,1,'polling cannot multiply animation loops');
  f.setVisible(false);assert.equal(f.queue.size,0);before=f.draws;f.advance();assert.equal(f.draws,before);f.setVisible(true);f.advance();assert(f.draws>before);
  f.setReduced(true);before=f.draws;f.advance();assert.equal(f.draws,before);assert.equal(f.queue.size,0);f.setReduced(false);assert.equal(f.queue.size,1);
  const row={symbol:'TEST',name:'Test stock',sector:'Test',score:75,finding:'Fixture finding'};
  f.update({status:'running',run_id:'one',done:60,total:100,discoveries:[row],planet_batches:[{number:1,count:8,rows:[row]}]});f.$('.su-planet').click();assert.match(f.$('.su-batch').textContent,/Checkpoint 1/);assert.match(f.$('.su-batch').textContent,/TEST/);
  f.update({status:'starting'});assert.equal(f.$('.su-card'),null);assert.equal(f.$('.su-batch').hidden,true,'new run resets previous checkpoint');
  f.update({status:'done',error:'interrupted'});assert.equal(f.$('#scan-universe').dataset.state,'partial');assert.doesNotMatch(f.$('.su-status').textContent,/universe is ready/);
  f.update({status:'reconnecting'});assert.match(f.$('.su-voyage-mode').textContent,/INTERRUPTED/);
  f.w.dispatchEvent(new f.w.PageTransitionEvent('pagehide',{persisted:false}));assert.equal(f.queue.size,0,'destroy cancels loop');
}finally{f.dom.window.close()}
for(const options of [{reduced:true},{noCanvas:true}]){
  const f=fixture(options);try{f.update({status:'cached'});assert.equal(f.queue.size,0);assert(f.$('#genbtn2'));f.$('#genbtn2').click();assert.equal(f.clicks,1);assert.equal(f.$('#scan-results').hidden,false)}finally{f.dom.window.close()}
}
console.log('Universe motion, pause, reduced motion, offscreen, loop cleanup, scan state and checkpoint tests passed.');
