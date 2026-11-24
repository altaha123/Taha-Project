/* The market board (Market › Market board) in Chromium; deterministic provider fixtures, no live calls. */
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
 const page=await context.newPage(), errors=[], sectorRequests=[], searchPicks=[], logoAsks=[];
 // Big enough to be kept as a logo: the page drops anything under 24 pixels.
 const PNG64=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAUUlEQVR42u3PMQ0AMAgAMJgG1KEOqVPBQdI6aFZPXPbiOAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAYF9HyTJAY7THInWAAAAAElFTkSuQmCC','base64');
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
   // The logo host is keyed by Indian symbol. It has RELIANCE, and it has a
   // META that is not the company in New York; anything else is a 403.
   if(u.hostname==='images.dhan.co'){
     const sym=decodeURIComponent(u.pathname).replace(/^\/symbol\/|\.png$/g,'');
     logoAsks.push(sym);
     return ['RELIANCE','META'].includes(sym)?route.fulfill({contentType:'image/png',body:PNG64})
       :route.fulfill({status:403,contentType:'application/xml',body:'<Error/>'});
   }
   if(u.pathname==='/market') return route.fulfill({json:{indices,status:'closed',ist:'10 Sep 2026, 15:45 IST'}});
   if(u.pathname==='/sector/benchmarks') return route.fulfill({json:{
     source:'NSE',available:true,as_of:'23-Sep-2026 15:30:00',window:u.searchParams.get('window')||'1D',
     rows:[{sector:'Nifty Financial Services',icon:'bank',index_level:24000,change_pct:1.2,relative_pp:.2},
           {sector:'Nifty Healthcare Index',icon:'pill',index_level:null,change_pct:null,relative_pp:null}],
     method:'Published NSE price indices.'
   }});
   if(u.pathname==='/sector/overview') {
     sectorRequests.push(u.search);
     return route.fulfill({json:{...sector,window:u.searchParams.get('window')||'1D'}});
   }
   return route.fulfill({json:{available:false,rows:[],rankings:[],sectors:[],items:[],status:'idle'}});
 });
 // The market board and its search box used to be the landing view. The
 // landing view is the Market door now (doors.js) and the board is one tool
 // behind it, Market › Market board, at its own address.
 await page.goto('http://127.0.0.1:8766/#discover/screener',{waitUntil:'domcontentloaded'});
 await page.locator('#tk').waitFor();
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
   // Each suggestion leads with the company's initials, and its logo over
   // them once the host has answered. On a phone the tile sits beside the
   // symbol and the name, which stack; it does not push them down a line.
   assert.equal(await item.locator('.co-lg .co-lg-m').innerText(), 'RI');
   await item.locator('.co-lg[data-sym="RELIANCE"].has-img img').waitFor();
   assert.equal(await item.evaluate(n => {
     const l=n.querySelector('.co-lg').getBoundingClientRect(), s=n.querySelector('.tah-sym').getBoundingClientRect(),
           m=n.querySelector('.tah-name').getBoundingClientRect();
     return l.right<=s.left && l.right<=m.left && l.top<=s.top+1 && l.bottom>=s.bottom-1;
   }), true, 'the logo is not beside its row');
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
   // A company listed in New York keeps its initials. The host has a logo
   // under the same letters and it is another company's, so it is not asked.
   await input.fill('meta');
   const us = list.locator('.tah-item', { hasText: 'Meta Platforms' });
   await us.waitFor();
   assert.equal(await us.locator('.co-lg .co-lg-m').innerText(), 'MP');
   assert.equal(await us.locator('.co-lg[data-sym]').count(), 0);
   await page.waitForTimeout(400);
   assert.equal(await us.locator('.co-lg img').count(), 0);
   assert.ok(!logoAsks.includes('META'), 'a New York listing was looked up by an Indian symbol');
   await input.fill('zzzznomatch');
   await list.locator('.tah-empty').waitFor();
   await input.press('Escape');
   assert.equal(await input.getAttribute('aria-expanded'), 'false');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 }
 assert.deepEqual(searchPicks, ['RELIANCE','HDFCBANK','RELIANCE','HDFCBANK']);
 // Asked once, though it was listed at two widths and after every letter.
 assert.equal(logoAsks.filter(sym=>sym==='RELIANCE').length, 1, 'a logo was asked for again: '+logoAsks);
 await page.locator('#tk').fill('');
 await page.locator('.mb-card').first().waitFor();
 await page.locator('.sb-tile').first().waitFor();
 assert.equal(await page.locator('.hm-tools').count(),0,'research tool cards removed');
 assert.match(await page.locator('.mb-card').nth(2).innerText(),/—/);
 assert.doesNotMatch(await page.locator('.mb-card').nth(2).innerText(),/0\.00%/);
 assert.match(await page.locator('[data-sector="Nifty Healthcare Index"]').innerText(),/Return unavailable/i);
 assert.equal(await page.locator('[data-sector="Nifty Healthcare Index"] .sb-breadth').count(),0);
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
   }
 }
 // Exact labels during the animation; changes originate in received snapshots.
 await page.locator('.mb').scrollIntoViewIfNeeded();
 await page.evaluate(d=>window.dispatchEvent(new CustomEvent('altaha:market',{detail:d})),{indices:indices.map((x,i)=>i===0?{...x,change_pct:2.5}:x),sectors:sector});
 await page.waitForFunction(()=>document.querySelector('[data-motion-key="index:NIFTY 50"]').getAnimations().length>0);
 assert.match(await page.locator('.mb-card').first().innerText(),/\+2\.50%/);
 // A sector tile opens that index in the explorer, by tap and by keyboard,
 // and closing the explorer hands focus back to the tile. 2a7eb0f made the
 // tile open the explorer instead of expanding in place; this step still
 // expected the old disclosure, so it had been red on main ever since.
 const tileSel='[data-sector="Nifty Financial Services"]', atlas=page.locator('dialog.ix-dialog');
 assert.equal(await page.locator(tileSel).getAttribute('aria-haspopup'),'dialog');
 assert.equal(await page.locator(tileSel).getAttribute('aria-expanded'),null);
 await page.locator(tileSel).tap();
 await atlas.waitFor({state:'visible'});
 assert.match(await atlas.locator('.ix-hero h2').innerText(),/NIFTY FINANCIAL SERVICES/);
 await atlas.locator('[data-key="close"]').click();
 await atlas.waitFor({state:'hidden'});
 assert.equal(await page.evaluate(()=>document.activeElement.dataset.sector),'Nifty Financial Services');
 await page.keyboard.press('Enter');
 await atlas.waitFor({state:'visible'});
 await page.keyboard.press('Escape');
 await atlas.waitFor({state:'hidden'});
 assert.equal(await page.evaluate(()=>document.activeElement.dataset.sector),'Nifty Financial Services');
 await page.evaluate(()=>window.AltahaNav.go('screener','screener',true));
 // Motion stays enabled across navigation and ignores an obsolete stored pause.
 assert.equal(await page.locator('.hm-motion').count(),0);
 await page.evaluate(()=>localStorage.setItem('altaha-motion','off'));
 await page.reload({waitUntil:'domcontentloaded'});
 assert.equal(await page.locator('html').getAttribute('data-motion'),'on');
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.waitForFunction(()=>document.documentElement.dataset.motion==='off');
 assert.equal(await page.locator('.hm-motion').count(),0);
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
