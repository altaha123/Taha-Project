const assert=require('node:assert/strict');const ui=require('./index-explorer.js');
for(const weights of [[60,40],[1,1,98],[20,20,20,20,20],[100]]){
 const rects=ui.layout(weights.map((w,i)=>({name:String(i),weight_pct:w})));
 assert.equal(rects.length,weights.length);
 assert(Math.abs(rects.reduce((s,r)=>s+r.w*r.h,0)-10000)<1e-6);
 rects.forEach(r=>{assert(r.x>=0&&r.y>=0&&r.x+r.w<=100.0001&&r.y+r.h<=100.0001);assert(Math.abs(r.w*r.h/100-r.weight_pct)<1e-6);});
}
const g={stocks:[{symbol:'A',weight_pct:60},{symbol:'B',weight_pct:40}]};
assert.equal(ui.groupReturn(g,{A:{change_pct:10},B:{change_pct:-5}}),4);
assert.equal(ui.groupReturn(g,{A:{change_pct:0},B:{change_pct:0}}),0);
assert.equal(ui.groupReturn(g,{A:{change_pct:10}}),null);
assert.equal(ui.groupReturn(g,{A:{change_pct:null},B:{change_pct:2}}),null);
console.log('Index explorer: proportional layout, bounds, weighted returns and missing data passed');
