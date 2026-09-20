const test = require('node:test');
const assert = require('node:assert/strict');
const {estimateRemaining,stateOf} = require('./universe-scan.js');
test('ETA needs measured progress and enough observations',()=>{
  assert.equal(estimateRemaining([],100),null);
  assert.equal(estimateRemaining([{elapsed:1,done:1}],100),null);
  const samples=[{elapsed:45,done:10},{elapsed:50,done:20},{elapsed:55,done:30},{elapsed:60,done:40}];
  assert.equal(estimateRemaining(samples,100),30);
  assert.equal(estimateRemaining(samples,40),null);
});
test('ETA disappears when recent progress stalls',()=>{
  const samples=[{elapsed:45,done:10},{elapsed:50,done:20},{elapsed:55,done:20},{elapsed:60,done:20}];
  assert.equal(estimateRemaining(samples,100),null);
});
test('backend done with error or partial results is never celebrated as complete',()=>{
  assert.equal(stateOf({status:'done',error:'memory limit'}),'partial');
  assert.equal(stateOf({status:'done',stopped_early:true}),'partial');
  assert.equal(stateOf({status:'done'}),'done');
  assert.equal(stateOf({status:'running',stopped_early:true}),'running');
  for(const status of ['cached','error','reconnecting','starting','idle']) assert.equal(stateOf({status}),status);
});
