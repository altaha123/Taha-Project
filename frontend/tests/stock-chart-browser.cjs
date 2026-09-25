// Run from repository root: node frontend/tests/stock-chart-browser.cjs
// Uses deterministic chart responses; requires Playwright and Chromium.
const {chromium}=require('playwright');
const fs=require('fs'),http=require('http'),assert=require('assert/strict');
const root=process.cwd()+'/frontend';
let values=[100,105,102,110,120,115],base=98;
const server=http.createServer((req,res)=>{let p=root+new URL(req.url,'http://localhost').pathname;try{res.setHeader('Content-Type',p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(p));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(8779,r));const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',route=>{let u=new URL(route.request().url());if(u.hostname==='localhost')return route.continue();if(u.pathname==='/analyze')return route.fulfill({json:{ticker:'TEST',name:'Test Company',currency:'INR',price:115,scoring:{score:61,pillars:{},checks:[]},profile:{sector:'Energy'}}});if(u.pathname==='/chart')return route.fulfill({json:{currency:'INR',base_close:base,candles:values.map((v,i)=>['2026-09-'+String(i+10).padStart(2,'0'),v,v,v,v,1000])}});return route.fulfill({json:{available:false,rows:[],items:[]}});});
await page.goto('http://localhost:8779/stock.html?ticker=TEST');await page.locator('[data-p="chart"]').click();await page.locator('.sc-insights').waitFor();assert.match(await page.locator('.sc-insights').innerText(),/-4.17%/);
for(const w of [360,390,768,1440]){await page.setViewportSize({width:w,height:1100});await page.waitForTimeout(100);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+w);await page.screenshot({path:require('path').join(require('os').tmpdir(),'altaha-chart-'+w+'.png'),fullPage:true});}
await page.locator('.sc-plot').focus();await page.keyboard.press('Home');assert.match(await page.locator('.sc-price').innerText(),/100/);await page.keyboard.press('Shift+ArrowRight');assert.match(await page.locator('.sc-chg').innerText(),/5%/);await page.locator('.sc-reset').click();assert.match(await page.locator('.sc-price').innerText(),/115/);
values=[120,110,100];await page.locator('[data-r="1M"]').click();await page.waitForTimeout(150);assert(await page.locator('.sc-plot.fall').count());
values=[100,100,100];await page.locator('[data-r="3M"]').click();await page.waitForTimeout(150);assert.match(await page.locator('.sc-position').innerText(),/Unchanged throughout/);
await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.sc-latest i').evaluate(e=>getComputedStyle(e).animationName),'none');
values=[];await page.locator('[data-r="1Y"]').click();await page.waitForTimeout(150);assert.match(await page.locator('#chartbox').innerText(),/Not enough history/);
assert.deepEqual(errors,[]);console.log('PASS: four widths, rising/falling/flat/empty data, keyboard measurement, reset, reduced motion; no page errors.');await browser.close();server.close();})().catch(e=>{console.error(e);process.exit(1)});
