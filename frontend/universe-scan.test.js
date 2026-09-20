const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  const planets = Array.from({length:6}, () => ({flags:{}, classList:{toggle(key,value){this.owner.flags[key]=value;}}}));
  planets.forEach(p => p.classList.owner=p);
  const nodes = {'.su-status':{}, '.su-detail':{}, progress:{removeAttribute(){delete this.value;}}};
  const host = {firstChild:true,dataset:{},querySelector:k=>nodes[k],querySelectorAll:()=>planets};
  const results={hidden:false};
  const context={window:{},document:{getElementById:id=>id==='scan-results'?results:host,addEventListener(){}}};
  vm.runInNewContext(fs.readFileSync('frontend/universe-scan.js','utf8'),context);
  return {update:context.window.AltahaUniverse.update,planets,nodes,results};
}
test('real scan progress hides old rankings, advances planets and reveals on completion',()=>{
  const {update,planets,nodes,results}=setup();
  update({status:'starting'}); assert.equal(results.hidden,true); assert.equal(nodes.progress.value,undefined);
  update({status:'running',done:50,total:100,scored:42});
  assert.equal(nodes.progress.value,50); assert.equal(planets.filter(p=>p.flags['is-scanned']).length,3);
  assert.equal(planets.filter(p=>p.flags['is-scanning']).length,1);
  update({status:'done'}); assert.equal(results.hidden,false); assert.equal(nodes.progress.value,100);
  assert.equal(planets.filter(p=>p.flags['is-scanned']).length,6);
});
test('cached, interrupted, failed and reconnecting scans do not claim completion',()=>{
  const {update,planets,nodes,results}=setup();
  for(const state of [{status:'cached'},{status:'done',stopped_early:true},{status:'error'},{status:'idle'},{status:'reconnecting'}]){
    update(state); assert.doesNotMatch(nodes['.su-status'].textContent,/Scan complete/);
    assert.equal(planets.filter(p=>p.flags['is-scanning']).length,0);
    assert.equal(results.hidden,state.status==='reconnecting');
  }
  update({status:'running',done:200,total:100}); assert.equal(nodes.progress.value,100);
  update({status:'running',total:0}); assert.equal(nodes.progress.value,undefined);
});
