/* Real Chromium integration tests. Run via the dedicated PR workflow. */
const fs=require('node:fs'), path=require('node:path'), http=require('node:http'), assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve('frontend'), fixtures=path.resolve(process.env.PF_FIXTURES||'/tmp/portfolio-fixtures');
const report=JSON.parse(fs.readFileSync(path.join(fixtures,'portfolio-12.json')));
const report50=JSON.parse(fs.readFileSync(path.join(fixtures,'portfolio-50.json')));
let activeReport=report;
const output=path.resolve('test-results/portfolio');fs.mkdirSync(output,{recursive:true});
// Serve the real shell and production scripts. Only API responses and external
// assets are intercepted; no dashboard markup is recreated by the test.
const server=http.createServer((req,res)=>{
 const name=path.join(root,decodeURIComponent(req.url.split('?')[0]==='/'?'/index.html':req.url.split('?')[0]));
 if(!name.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 try{res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.html')?'text/html':'application/octet-stream');res.end(fs.readFileSync(name));}catch(e){res.writeHead(404).end();}
});
(async()=>{
 await new Promise(resolve=>server.listen(8765,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1280,height:900}}), page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(String(e.stack)));
 const routeRequest=route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/portfolio/start')return route.fulfill({json:{job_id:'fixture',total:12}});
   if(url.pathname==='/portfolio/status')return route.fulfill({json:{status:'done',done:12,total:12,revision:1,report:activeReport}});
   if(url.hostname!=='127.0.0.1'){
     if(route.request().resourceType()==='script'||route.request().resourceType()==='font'||route.request().resourceType()==='stylesheet')return route.abort();
     return route.fulfill({json:{available:false,rows:[],rankings:[],sectors:[],items:[],status:'idle'}});
   }
   return route.continue();
 };
 await page.route('**/*',routeRequest);
 await page.goto('http://127.0.0.1:8765/?go=portfolio',{waitUntil:'domcontentloaded'});
 await page.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
 await page.locator('#pf_rows .pf_qty').first().fill('10');
 await page.locator('#pf_go').click();
 await page.locator('#pi-allocation-chart').waitFor();
 await page.waitForFunction(()=>window.Chart&&Object.keys(Chart.instances).length===7);
 for(const width of [320,390,768,1280]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['light','dark']){
     await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
     await page.waitForTimeout(450);
     const layout=await page.evaluate(()=>({
       overflow:document.documentElement.scrollWidth>innerWidth+1,
       charts:[...document.querySelectorAll('#pf_report canvas')].map(c=>({id:c.id,width:c.getBoundingClientRect().width,height:c.getBoundingClientRect().height,painted:c.getContext('2d').getImageData(0,0,c.width,c.height).data.some(v=>v!==0)})),
       active:document.querySelectorAll('#pf_report .pi-root').length
     }));
     assert.equal(layout.active,1);
     assert.equal(layout.overflow,false,`${width}/${theme} page overflow`);
     assert.equal(layout.charts.length,7);
     for(const c of layout.charts){assert.ok(c.width>100&&c.height>100,JSON.stringify(c));assert.ok(c.painted,c.id+' blank');}
     await page.locator('.pi-header').scrollIntoViewIfNeeded();
     await page.screenshot({path:path.join(output,`${width}-${theme}.png`)});
     if(width===390||width===1280){
       for(const id of ['pi-allocation','pi-sector-comparison']){
         await page.locator('#'+id).screenshot({path:path.join(output,`${width}-${theme}-${id}.png`)});
       }
     }
   }
 }
 await page.setViewportSize({width:390,height:844});
 await page.locator('[data-allocation="Financial Services"]').click();
 assert.equal(await page.locator('.pi-holding:visible').count(),2);
 await page.getByRole('button',{name:'Show all holdings',exact:true}).click();
 assert.equal(await page.locator('.pi-holding:visible').count(),12);
 await page.locator('.pi-holding[data-symbol="HDFCBANK"] > summary').click();
 assert.ok(await page.locator('.pi-holding[data-symbol="HDFCBANK"] .pi-holding-body').isVisible());
 await page.locator('#pi-allocation-mode').selectOption('Stock');
 await page.locator('#pi-sector-sort').selectOption('under');
 await page.locator('#pi-window').selectOption('1Y');
 await page.waitForTimeout(400);
 assert.equal(await page.locator('#pi-allocation-mode').inputValue(),'Stock');
 // Use actual report download, not private UI state.
 const downloadPromise=page.waitForEvent('download');await page.locator('#pf_dl').click();const download=await downloadPromise;
 const exportPath=path.join(output,'report.html');await download.saveAs(exportPath);
 const html=fs.readFileSync(exportPath,'utf8');assert.ok(html.includes('data:image/png'));assert.ok(!html.includes('<canvas'));assert.ok(html.includes('Holding-level Review'));
 // 50 holdings: actual analysis button runs the same render path.
 activeReport=report50;await page.locator('#pf_go').click();await page.waitForFunction(()=>document.querySelectorAll('.pi-holding').length===50);
 await page.waitForTimeout(450);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 // Loss of Chart.js: data must remain readable and no blank canvas survives.
 activeReport=report;
 const fallback=await context.newPage();
 await fallback.route('**/*',r=>new URL(r.request().url()).pathname.includes('chart.umd.min.js')?r.abort():routeRequest(r));
 await fallback.goto('http://127.0.0.1:8765/?go=portfolio',{waitUntil:'domcontentloaded'});
 await fallback.locator('#pf_rows .pf_sym').first().fill('HDFCBANK');
 await fallback.locator('#pf_rows .pf_qty').first().fill('10');
 await fallback.locator('#pf_go').click();
 await fallback.getByText('Chart unavailable. Open “View chart data” below for the full figures.').first().waitFor();
 assert.equal(await fallback.locator('#pf_report canvas').count(),0);
 assert.ok(await fallback.locator('#pf_report').getByText('View chart data',{exact:true}).count()>=5);
 // Ignore known unrelated optional shell failures; portfolio errors fail CI.
 const relevant=errors.filter(e=>/portfolio(?:-intelligence)?\.js/.test(e));assert.deepEqual(relevant,[]);
 fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({viewports:[320,390,768,1280],themes:['light','dark'],charts:7,holdings:[12,50],tapFiltering:true,exports:true,chartFailureFallback:true,portfolioErrors:relevant,otherShellErrors:errors},null,2));
 await browser.close();server.close();console.log('Portfolio Chromium checks passed');
})().catch(e=>{console.error(e);server.close();process.exit(1);});
