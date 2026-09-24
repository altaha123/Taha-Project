const assert=require('node:assert/strict');const ui=require('./index-explorer.js');
for(const weights of [[60,40],[1,1,98],[20,20,20,20,20],[100]]){
 const html=ui.compositionView(weights.map((w,i)=>({name:'Group '+i,weight_pct:w,change:null})),null);
 const spans=[...html.matchAll(/stroke-dasharray="([\d.]+) ([\d.]+)"/g)].map(m=>Number(m[1]));
 assert.equal(spans.length,weights.length);
 assert(Math.abs(spans.reduce((a,b)=>a+b,0)-100)<1e-6);
 spans.forEach((s,i)=>assert(Math.abs(s-weights[i])<1e-6));
 assert(!html.includes('ix-cell'));assert(!html.includes('ix-map'));
 assert(html.includes('index weight'));assert(html.includes('member return'));
}
const subgroup=ui.compositionView([{name:'A',weight_pct:20,change:2,stock:true},{name:'B',weight_pct:30,change:null,stock:true}],'Group');
assert(subgroup.includes('stroke-dasharray="40 60"'));
assert(subgroup.includes('20.00%'));
assert(subgroup.includes('Segments show each stock’s share of this group.'));
assert(subgroup.includes('price return'));
assert(!subgroup.includes('undefined'));
const escaped=ui.compositionView([{name:'<script>"test',weight_pct:100,change:null}],null);
assert(!escaped.includes('<script>'));assert(escaped.includes('&lt;script&gt;'));
const g={stocks:[{symbol:'A',weight_pct:60},{symbol:'B',weight_pct:40}]};
assert.equal(ui.groupReturn(g,{A:{change_pct:10},B:{change_pct:-5}}),4);
assert.equal(ui.groupReturn(g,{A:{change_pct:0},B:{change_pct:0}}),0);
assert.equal(ui.groupReturn(g,{A:{change_pct:10}}),null);
assert.equal(ui.groupReturn(g,{A:{change_pct:null},B:{change_pct:2}}),null);
console.log('Index explorer: ring proportions, subgroup scale, escaping, weighted returns and missing data passed');
