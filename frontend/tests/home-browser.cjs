/* Actual homepage in Chromium; deterministic provider fixtures, no live calls. */
const fs=require('node:fs'), path=require('node:path'), http=require('node:http'), assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve('frontend'), output=path.resolve('test-results/home');
fs.mkdirSync(output,{recursive:true});
const indices=[{label:'NIFTY 50',level:25150.75,change_pct:1.25},{label:'SENSEX',level:81900,change_pct:-.65},{label:'BANK NIFTY',level:54850,change_pct:null},{label:'INDIA VIX',level:14.4,change_pct:2.4}];
const rows=[
 {sector:'Financial Services',icon:'bank',change_pct:1.2,relative_pp:.2,up:2,total:3,stocks:[{symbol:'HDFCBANK',change_pct:2.2,ltp:2000},{symbol:'ICICIBANK',change_pct:1.3,ltp:1400},{symbol:'SBIN',change_pct:-.5,ltp:900}]},
 {sector:'Technology',icon:'chip',change_pct:-1.4,relative_pp:-2.4,up:1,total:2,stocks:[{symbol:'TCS',change_pct:-3.1,ltp:3400},{symbol:'INFY',change_pct:.3,ltp:1500}]},
 {sector:'Healthcare',icon:'pill',change_pct:.7,relative_pp:-.3,stocks:[]},
 {sector:'Energy',icon:'bolt',change_pct:.4,relative_pp:-.6,up:1,total:2,stocks:[{symbol:'RELIANCE',change_pct:.8,ltp:1400},{symbol:'ONGC',change_pct:0,ltp:220}]}
];
const sector={rows,source:'dhan',as_of:'2026-09-10T09:00:00Z',window:'1D'};
const server=http.createServer((req,res)=>{
 const file=path.join(root,decodeURIComponent(req.url.split('?')[0]==='/'?'/index.html':req.url.split('?')[0]));
 if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 try { res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript; charset=utf-8':file.endsWith('.css')?'text/css; charset=utf-8':file.endsWith('.html')?'text/html; charset=utf-8':'application/octet-stream');res.end(fs.readFileSync(file)); }
 catch(_){res.writeHead(404).end();}
});
(async()=>{
 await new Promise(resolve=>server.listen(8766,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true, executablePath: process.env.CHROMIUM_PATH || undefined});
 const context=await browser.newContext({viewport:{width:1280,height:900},hasTouch:true});
 await context.addInitScript(()=>localStorage.setItem('altaha-guide-dismissed','1'));
 const page=await context.newPage(), errors=[], sectorRequests=[], searchPicks=[];
 page.on('pageerror',e=>errors.push(String(e.stack)));
 await context.route('**/*',route=>{
   const u=new URL(route.request().url());
   if(u.hostname==='127.0.0.1'){
     // What picking a suggestion is FOR: home.js opens the stock page. The
     // symbol is recorded from the request itself, and 204 answers it so the
     // homepage stays put and the assertions below still have a page to read.
     //
     // This used to be a capture listener added to #go from the test, which
     // could never fire: home.js is deferred, so it binds #go while the
     // document is still 'interactive' — before waitUntil:'domcontentloaded'
     // returns — and its handler calls stopImmediatePropagation. Anything
     // added afterwards is unreachable, so every pick navigated away and the
     // next line found no #tk. The race was unwinnable and there was nothing
     // to win: the navigation IS the behaviour under test, so assert on it.
     // (abort() is not the same thing — Chromium commits an error page for a
     // cancelled navigation, which destroys the document just as thoroughly.)
     if(u.pathname==='/stock.html'){searchPicks.push(u.searchParams.get('ticker'));return route.fulfill({status:204,body:''});}
     return route.continue();
   }
   if(['script','font','stylesheet'].includes(route.request().resourceType())) return route.abort();
   if(u.pathname==='/market') return route.fulfill({json:{indices,status:'closed',ist:'10 Sep 2026, 15:45 IST'}});
   if(u.pathname==='/sector/overview') {
     sectorRequests.push(u.search);
     return route.fulfill({json:{...sector,window:u.searchParams.get('window')||'1D'}});
   }
   return route.fulfill({json:{available:false,rows:[],rankings:[],sectors:[],items:[],status:'idle'}});
 });
 await page.goto('http://127.0.0.1:8766/',{waitUntil:'domcontentloaded'});
 // Regression: suggestions must be hittable outside the rounded search bar.
 for (const width of [390, 1280]) {
   await page.setViewportSize({width, height:900});
   const input = page.locator('#tk');
   await input.fill('r');
   const list = page.locator('#' + await input.getAttribute('aria-controls'));
   await list.locator('.tah-item').first().waitFor();
   assert.equal(await input.getAttribute('aria-expanded'), 'true');
   await input.fill('Reliance');
   const item = list.locator('.tah-item').first();
   await item.scrollIntoViewIfNeeded();
   assert.equal(await item.evaluate(n => {
     const r=n.getBoundingClientRect();
     return n.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
   }), true, 'suggestion is clipped or covered');
   if (width === 390) await item.tap(); else await item.click();
   assert.equal(await input.inputValue(), 'RELIANCE');
   assert.equal(await input.getAttribute('aria-expanded'), 'false');
   await input.fill('hdf');
   await input.press('ArrowDown');
   await input.press('Enter');
   assert.equal(await input.inputValue(), 'HDFCBANK');
   await input.fill('zzzznomatch');
   await list.locator('.tah-empty').waitFor();
   await input.press('Escape');
   assert.equal(await input.getAttribute('aria-expanded'), 'false');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 }
 assert.deepEqual(searchPicks, ['RELIANCE','HDFCBANK','RELIANCE','HDFCBANK']);
 await page.locator('#tk').fill('');
 await page.locator('.mb-card').first().waitFor();
 await page.locator('.sb-tile').first().waitFor();
 assert.equal(await page.locator('.hm-route svg').count(),3);
 assert.match(await page.locator('.mb-card').nth(2).innerText(),/—/);
 assert.doesNotMatch(await page.locator('.mb-card').nth(2).innerText(),/0\.00%/);
 assert.match(await page.locator('[data-sector="Healthcare"]').innerText(),/Breadth unavailable/i);
 assert.equal(await page.locator('[data-sector="Healthcare"] .sb-breadth').count(),0);
 assert.ok(sectorRequests.every(q=>q.includes('stocks=1')));
 for(const width of [320,390,768,1280]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['light','dark']){
     await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
     await page.locator('.mb').scrollIntoViewIfNeeded(); await page.waitForTimeout(800);
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${width} ${theme} overflow`);
     const bars=await page.locator('.mb-card .spark').evaluateAll(list=>list.map(n=>({w:n.clientWidth,h:n.clientHeight})));
     bars.forEach(b=>assert.ok(b.w>60&&b.h>=6,JSON.stringify(b)));
     await page.screenshot({path:path.join(output,`${width}-${theme}-market.png`)});
     if(width===390||width===1280){
       await page.locator('.hm-tools').scrollIntoViewIfNeeded();
       await page.screenshot({path:path.join(output,`${width}-${theme}-research.png`)});
     }
   }
 }
 // Exact labels during the animation; changes originate in received snapshots.
 await page.locator('.mb').scrollIntoViewIfNeeded();
 await page.evaluate(d=>window.dispatchEvent(new CustomEvent('altaha:market',{detail:d})),{indices:indices.map((x,i)=>i===0?{...x,change_pct:2.5}:x),sectors:sector});
 await page.waitForFunction(()=>document.querySelector('[data-motion-key="index:NIFTY 50"]').getAnimations().length>0);
 assert.match(await page.locator('.mb-card').first().innerText(),/\+2\.50%/);
 // Tap disclosure and verify keyboard focus survives its redraw.
 await page.locator('[data-sector="Financial Services"]').tap();
 assert.equal(await page.locator('[data-sector="Financial Services"]').getAttribute('aria-expanded'),'true');
 assert.ok(await page.locator('.sb-detail').isVisible());
 await page.locator('[data-sector="Financial Services"]').focus();
 await page.keyboard.press('Enter');
 assert.equal(await page.evaluate(()=>document.activeElement.dataset.sector),'Financial Services');
 assert.equal(await page.locator('[data-sector="Financial Services"]').getAttribute('aria-expanded'),'false');
 await page.locator('[data-home-destination="search"]').tap();
 assert.equal(await page.evaluate(()=>document.activeElement.id),'tk');
 await page.locator('[data-home-destination="portfolio"]').tap();
 await page.locator('#pf_go').waitFor();
 assert.ok(await page.locator('#view-portfolio').isVisible());
 await page.evaluate(()=>window.AltahaNav.go('screener','screener',true));
 // Preference changes stop motion immediately and persist through navigation.
 await page.locator('.hm-motion').tap();
 assert.equal(await page.locator('html').getAttribute('data-motion'),'off');
 await page.reload({waitUntil:'domcontentloaded'});
 assert.equal(await page.locator('html').getAttribute('data-motion'),'off');
 await page.locator('.hm-motion').tap();
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.waitForFunction(()=>document.documentElement.dataset.motion==='off');
 assert.ok(await page.locator('.hm-motion').isDisabled());
 assert.equal(await page.locator('.sk-candle').first().evaluate(n=>getComputedStyle(n).animationName),'none');
 // A partial refresh recovers missing data without inventing a zero return.
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.locator('.mb-card').first().waitFor();
 await page.evaluate(()=>window.dispatchEvent(new CustomEvent('altaha:market',{detail:{indices:[{label:'NIFTY 50',level:25150,change_pct:null}],sectors:null}})));
 assert.match(await page.locator('.mb-card').innerText(),/—/);
 assert.equal(await page.locator('.mb-col').count(),0);
 const relevant=errors.filter(e=>/home(?:-motion)?\.js|sectors-live\.js|shell\.js/.test(e));
 assert.deepEqual(relevant,[]);
 fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({viewports:[320,390,768,1280],themes:['light','dark'],animatedBars:true,exactFinancialLabels:true,missingData:true,tapAndKeyboard:true,motionPreference:true,errors},null,2));
 await browser.close();server.close();console.log('Homepage Chromium checks passed');
})().catch(e=>{console.error(e);server.close();process.exit(1);});
