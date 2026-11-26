/* Run with Playwright available: node frontend/tests/late-load-browser.cjs

   The homepage shows Market, and Market is drawn by a dozen of the page's
   sixty scripts and half of its stylesheets. The rest sit in <template>
   elements in index.html and load after Market is on show (see WHAT LOADS
   FIRST there). Everything that can go wrong with that is silent:

     - a file Market needs is put in a <template>, and the first screen
       changes under the reader when it lands
     - a tool is opened before its script has arrived, and stays empty
     - the later scripts run in a different order from the one written
     - an address that names a tool (#portfolio, ?go=filings) stops loading
       the way it always has
     - the charting library is fetched twice, or never

   This holds the later files back the way a slow line does and checks each. */
const fs=require('node:fs'), path=require('node:path'), http=require('node:http'), assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const TYPES={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.png':'image/png','.ico':'image/x-icon','.webp':'image/webp','.jpg':'image/jpeg'};

/* What index.html says loads later: numbered groups, listed once at the top
   of the head, each put back where AltahaBoot.late(n) stands. `whole` is the
   page with every group back in its place, which is the order things load in. */
const groups=new Map([...html.matchAll(/^<template id="later-(\d+)">\n([\s\S]*?)^<\/template>\n/gm)].map(m=>[m[1],m[2]]));
const placed=[...html.matchAll(/^<script>AltahaBoot\.late\((\d+)\)<\/script>$/gm)].map(m=>m[1]);
const whole=html.replace(/^<template id="later-\d+">\n[\s\S]*?^<\/template>\n/gm,'')
  .replace(/^<script>AltahaBoot\.late\((\d+)\)<\/script>\n/gm,(all,n)=>groups.get(n)||'');
const laterFiles=[], laterScripts=[], laterStyles=[];
for(const n of placed){
  for(const tag of (groups.get(n)||'').matchAll(/<(script|link)\b[^>]*?(?:src|href)="([^"]+)"/g)){
    laterFiles.push(tag[2]);
    (tag[1]==='script'?laterScripts:laterStyles).push(tag[2]);
  }
}
const isLater=new Set(laterFiles.map(f=>'/'+f.split('?')[0]));
const HOLD=900;
let hold=true;
const server=http.createServer((req,res)=>{
  const url=decodeURIComponent(req.url.split('?')[0]);
  const file=path.join(root,url==='/'?'/index.html':url);
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){res.writeHead(404).end();return;}
  setTimeout(()=>{
    res.setHeader('Content-Type',TYPES[path.extname(file)]||'application/octet-stream');
    res.end(fs.readFileSync(file));
  },hold&&isLater.has(url)?HOLD:0);
});

/* Every page here is told it is eight in the evening in India, on a trading
   day, and its clock runs on from there. Market goes by the wall clock, and
   so did this test: while NSE is trading the session bar grows a pixel about
   once a minute (doors.js, startClock), and a run that took its two pictures
   either side of that pixel failed with nothing having moved (CI, 23 Nov 2026
   at 12:53 IST: 212 px, then 213). Until /market answers, the tag at the head
   of the tape goes by the clock as well (shell.js, paintTape): on a weekday
   before 15:30 it says Live or Pre-open, then Closed when the answer served
   here arrives, and the tape beside it moves over. At eight the bar is full
   and the tag says Closed whoever is asked.

   Only Date is replaced. Playwright's page.clock also takes over the timers
   the page loads by, and gives it a `performance` whose getEntriesByType() is
   always empty, so "no later file had arrived" would pass whatever had. */
const EVENING=Date.parse('2026-11-23T20:00:00+05:30');
function pinClock(at){
  const Real=Date, began=Real.now(), now=()=>at+(Real.now()-began);
  window.Date=class extends Real{
    constructor(...args){super(...(args.length?args:[now()]));}
    static now(){return now();}
  };
}

/* The page as a reader has it: every element that is on show, where it is
   and how it is drawn. Compared before and after the later files land.

   Not the session clock: it counts the seconds, whatever the hour. */
function picture(){
  var out=[];
  document.querySelectorAll('body *').forEach(function(el){
    if(/^(SCRIPT|TEMPLATE|LINK|STYLE)$/.test(el.tagName)||el.id==='drt-clock'||el.closest('svg')&&el.tagName!=='svg')return;
    var r=el.getBoundingClientRect();
    if(!el.getClientRects().length||r.bottom<0||r.top>innerHeight*3)return;
    var c=getComputedStyle(el);
    /* Not its classes: doors.js retires an entrance class on a timer of its own. */
    out.push([el.tagName.toLowerCase()+(el.id?'#'+el.id:''),
      Math.round(r.left),Math.round(r.top+scrollY),Math.round(r.width),Math.round(r.height),
      c.color,c.backgroundColor,c.fontSize,c.fontWeight,c.display,c.opacity,c.borderTopColor].join(' '));
  });
  return out;
}

(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({headless:true,executablePath:process.env.ALTAHA_CHROMIUM||process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
  async function open(url,options,more){
    const context=await browser.newContext(Object.assign({viewport:{width:1280,height:800},reducedMotion:'reduce'},options||{}));
    // Big trades and friends are member tools (gate.js); open them signed in.
    await context.addInitScript(()=>localStorage.setItem('altaha-session-v1','tok-test'));
    await context.addInitScript(pinClock,EVENING);
    const page=await context.newPage(), errors=[], asked=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{const u=new URL(r.url());asked.push(u.origin===origin?u.pathname:u.href);});
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      if(u.origin===origin)return route.continue();
      if(['script','font','stylesheet','image'].includes(route.request().resourceType()))return route.abort();
      return route.fulfill({json:{available:false,indices:[{label:'NIFTY 50',level:25227.95,change_pct:-0.63}],rows:[],rankings:[],sectors:[],items:[],status:'closed'}});
    });
    if(more)await more(context,page);
    await page.goto(origin+url,{waitUntil:'domcontentloaded'});
    return {context,page,errors,asked};
  }
  const revealed=page=>page.waitForFunction(()=>!document.getElementById('sh-bootcover'),null,{timeout:8000});
  const ready=page=>page.waitForFunction(()=>window.AltahaBoot.ready===true,null,{timeout:15000});

  try{
    /* What the page declares. */
    assert(laterScripts.length>30,'most scripts load later ('+laterScripts.length+')');
    assert(laterStyles.length>15,'the stylesheets of other tools load later ('+laterStyles.length+')');
    assert.deepEqual(placed,[...groups.keys()],'every group is listed once and placed once, in order');
    assert(html.indexOf('<script>AltahaBoot.declared()</script>')>html.lastIndexOf('<template id="later-')&&
      html.indexOf('<script>AltahaBoot.declared()</script>')<html.indexOf('<link rel="stylesheet"',html.lastIndexOf('</template>')),
      'the groups are declared before the first stylesheet, so nothing holds up asking for them');
    for(const f of laterFiles)assert(fs.existsSync(path.join(root,f.split('?')[0])),f+' is on disk');
    for(const f of ['nav.js','shell.js','doors.js','shell.css','doors.css'])
      assert.equal(laterFiles.some(l=>l.split('?')[0]===f),false,f+' draws Market and loads first');
    assert.equal(/<head>[\s\S]*<script[^>]+src="https?:[^"]*lightweight-charts[\s\S]*<\/head>/.test(html),false,'no charting library in the head');

    for(const [url,viewport] of [['/',{width:1280,height:800}],['/?utm_source=newsletter&utm_medium=email',{width:390,height:844}]]){
      /* The homepage: Market is shown before a single later file has arrived. */
      const {context,page,errors,asked}=await open(url,{viewport});
      assert.equal(await page.evaluate(()=>window.AltahaBoot.plain),true,url+' is the homepage');
      assert(Math.abs(await page.evaluate(()=>Date.now())-EVENING)<60000,url+': the page has the clock it was given');
      await revealed(page);
      assert.equal(await page.evaluate(()=>window.AltahaBoot.ready),false,url+': Market is on show before the later files are in');
      assert.equal(await page.evaluate(()=>!!document.getElementById('view-today').firstChild&&document.body.classList.contains('sh-on')),true,url+': Market is drawn');
      const arrived=await page.evaluate(()=>performance.getEntriesByType('resource').filter(e=>e.responseEnd>0).map(e=>new URL(e.name).pathname));
      assert.deepEqual(arrived.filter(p=>isLaterIn(p)),[],url+': no later file had arrived');
      assert.equal(asked.some(u=>/lightweight-charts/.test(u)),false,url+': no charting library asked for');
      await page.waitForTimeout(250);
      const before=await page.evaluate(picture);

      /* They land, in the order written, and the first screen does not move. */
      await ready(page);
      await page.waitForTimeout(600);
      const after=await page.evaluate(picture);
      assert.deepEqual(after,before,url+': the first screen changed when the later files landed');
      const ran=await page.evaluate(()=>[...document.querySelectorAll('body > script[src]')].filter(s=>!s.defer).map(s=>s.getAttribute('src')));
      assert.deepEqual(ran,laterScripts,url+': the later scripts are run in the order written');
      const sheets=await page.evaluate(()=>[...document.styleSheets].map(s=>s.ownerNode&&s.ownerNode.getAttribute&&s.ownerNode.getAttribute('href')).filter(Boolean));
      for(const f of laterStyles)assert(sheets.includes(f),url+': '+f+' is applied');
      /* A later stylesheet takes the place its <template> holds in the cascade. */
      const order=await page.evaluate(()=>[...document.querySelectorAll('link[rel=stylesheet][href]')].map(l=>l.getAttribute('href').split('?')[0]).filter(h=>!/^https?:/.test(h)));
      const written=[...whole.matchAll(/<link rel="stylesheet" href="([^"?]+)/g)].map(m=>m[1]).filter(h=>!/^https?:/.test(h));
      assert.deepEqual(order,written,url+': stylesheets stand in the order written');
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-wait')),false,url+': nothing was waiting');
      assert.equal(await page.evaluate(()=>getComputedStyle(document.getElementById('view-today')).display!=='none'),true,url+': still on Market');
      assert.deepEqual(twice(asked),[],url+': nothing is fetched twice');
      /* The three fonts the first screen is set in are preloaded on every
         page (tokens.css): a ticker symbol that swapped face after the first
         paint moved the tape by a pixel. Those are for Market itself.
         Anything else preloaded would be a later file jumping the queue. */
      assert.equal(await page.evaluate(()=>document.querySelectorAll('link[rel=preload]:not([as=font])').length),0,url+': nothing later is asked for ahead of Market');
      assert.equal(await page.evaluate(()=>document.querySelectorAll('link[rel=preload][as=font]').length),3,url+': the three first-screen fonts are preloaded');
      assert.deepEqual(errors,[],url+': no script errors');
      await context.close();
    }

    /* A tool asked for before its files are in opens when they are. */
    for(const [how,ask,view,alive] of [
      ['a call',()=>{window.AltahaNav.go('portfolio','portfolio',true);},'view-portfolio','AltahaPortfolio'],
      ['a link',()=>{location.hash='#research/query';},'view-query','AltahaQuery'],
      ['a card on Market',()=>{document.querySelector('#view-today [data-goto="discover/deals"]').click();},'view-deals','AltahaDeals']]){
      const {context,page,errors}=await open('/');
      await revealed(page);
      await page.waitForSelector('#view-today [data-goto="discover/deals"]');
      await page.evaluate(ask);
      assert.equal(await page.evaluate(()=>window.AltahaBoot.ready),false,how+': asked before the later files were in');
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-wait')),true,how+': the page says it is fetching');
      assert.equal(await page.evaluate(()=>getComputedStyle(document.getElementById('view-today')).display!=='none'),true,how+': Market stays until the tool can open');
      await ready(page);
      await page.waitForFunction(id=>getComputedStyle(document.getElementById(id)).display!=='none',view,{timeout:5000});
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-wait')),false,how+': the wait is over');
      assert.equal(await page.evaluate(()=>getComputedStyle(document.getElementById('view-today')).display),'none',how+': Market has made way');
      assert.equal(await page.evaluate(name=>typeof window[name],alive),'object',how+': '+alive+' is there to fill the view');
      if(how==='a call')assert.equal(await page.evaluate(()=>location.hash),'#portfolio',how+': the address names the tool');
      await page.waitForTimeout(400);
      assert.deepEqual(errors,[],how+': no script errors');
      await context.close();
    }

    /* Asked for twice while waiting, the last one wins and nothing opens twice. */
    {
      const {context,page,errors}=await open('/');
      await revealed(page);
      await page.evaluate(()=>{window.__opened=[];window.addEventListener('altaha:navigate',e=>window.__opened.push(e.detail.tab));
        window.AltahaNav.go('research','lenses',true);window.AltahaNav.go('discover','deals',true);});
      await ready(page);
      await page.waitForFunction(()=>getComputedStyle(document.getElementById('view-deals')).display!=='none',null,{timeout:5000});
      assert.deepEqual(await page.evaluate(()=>window.__opened.filter(t=>t!=='today')),['lenses','deals'],'each is opened once, in the order asked');
      assert.deepEqual(errors,[],'two asks: no script errors');
      await context.close();
    }

    /* A later file that never arrives is not waited for for ever. */
    {
      const {context,page}=await open('/',null,context=>context.route('**/strategy-lab.js*',route=>route.abort()));
      await ready(page);
      await page.evaluate(()=>window.AltahaNav.go('research','calls',true));
      await page.waitForFunction(()=>getComputedStyle(document.getElementById('view-calls')).display!=='none',null,{timeout:5000});
      await context.close();
    }

    /* An address that names a tool loads as it always has: every script on
       the page as a deferred tag, in the order written, before the page says
       it is ready. */
    hold=false;
    const writtenScripts=[...whole.slice(whole.indexOf('<body>')).matchAll(/<script src="([^"]+)"( defer)?><\/script>/g)].map(m=>m[1]);
    for(const [url,view,alive] of [['/#portfolio','view-portfolio','AltahaPortfolio'],['/?go=filings','view-filings',null],['/#research/query','view-query','AltahaQuery']]){
      const {context,page,errors,asked}=await open(url,null,(context,page)=>page.addInitScript(()=>{
        document.addEventListener('DOMContentLoaded',()=>{window.__atReady={ready:window.AltahaBoot.ready,
          hints:[...document.querySelectorAll('link[rel=preload][as=style]')].map(l=>l.getAttribute('href')),
          scripts:[...document.querySelectorAll('body script[src]')].map(s=>s.getAttribute('src')+(s.defer?'':' NOT DEFERRED')),
          styles:[...document.querySelectorAll('link[rel=stylesheet][href]')].filter(l=>l.sheet).length,
          names:['AltahaPortfolio','AltahaQuery','AltahaPicks','AltahaUniverse','AltahaStrategyLab'].filter(n=>!window[n])};});
      }));
      await page.waitForLoadState('load');
      const at=await page.evaluate(()=>window.__atReady);
      assert.equal(await page.evaluate(()=>window.AltahaBoot.plain),false,url+' names a tool');
      assert.equal(at.ready,true,url+': nothing is held back');
      assert.deepEqual(at.scripts,writtenScripts,url+': every script is a deferred tag, in the order written');
      assert.deepEqual(at.names,[],url+': every script had run by DOMContentLoaded');
      /* A tag written by script is one the browser cannot see coming; asked
         for one group at a time, the stylesheets took a second longer. */
      assert.deepEqual(at.hints,laterStyles,url+': the later stylesheets are all asked for at the top of the page');
      assert.deepEqual(twice(asked),[],url+': nothing is fetched twice');
      assert(at.styles>=laterStyles.length+10,url+': every stylesheet was applied by DOMContentLoaded ('+at.styles+')');
      assert.equal(await page.evaluate(id=>getComputedStyle(document.getElementById(id)).display!=='none',view),true,url+' opens '+view);
      if(alive)assert.equal(await page.evaluate(name=>typeof window[name],alive),'object',url+': '+alive);
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-wait')),false,url+': no wait');
      assert.deepEqual(errors,[],url+': no script errors');
      await context.close();
    }

    /* Without JavaScript nothing in a <template> is fetched, and the page is whole. */
    {
      const {context,page,asked}=await open('/',{javaScriptEnabled:false});
      await page.waitForLoadState('load');
      assert.deepEqual(asked.filter(p=>isLaterIn(p)),[],'nothing later is fetched without JavaScript');
      assert.equal(await page.locator('header.wrap .brand').isVisible(),true,'the page itself is shown');
      await context.close();
    }

    /* The charting library: fetched once, by whoever first needs it, from the
       second CDN when the first fails, and wrapped before anyone is told. */
    {
      const calls=[];
      const {context,page,errors}=await open('/',null,context=>context.route(/lightweight-charts/,route=>{
        calls.push(new URL(route.request().url()).hostname);
        if(/unpkg/.test(route.request().url()))return route.abort();
        return route.fulfill({contentType:'text/javascript',body:'window.LightweightCharts={createChart:function(){return {}}};'});
      }));
      await ready(page);
      await page.waitForFunction(()=>typeof window.LightweightCharts==='object',null,{timeout:8000});
      const told=await page.evaluate(()=>new Promise(resolve=>{const got=[];
        window.AltahaBoot.chartLib(ok=>got.push(ok));window.AltahaBoot.chartLib(ok=>{got.push(ok);resolve(got);});}));
      assert.deepEqual(told,[true,true],'a caller is told the library is there');
      assert.deepEqual(calls,['unpkg.com','cdn.jsdelivr.net'],'one attempt at each CDN, the second after the first failed');
      assert.deepEqual(errors,[],'chart library: no script errors');
      await context.close();
    }
    {
      const {context,page}=await open('/',null,context=>context.route(/lightweight-charts/,route=>route.abort()));
      await ready(page);
      assert.equal(await page.evaluate(()=>new Promise(resolve=>window.AltahaBoot.chartLib(resolve))),false,'a caller is told when neither CDN sends it');
      await context.close();
    }
    /* ?chart=SYMBOL is a chart and nothing else. The library used to be in
       the head; it is asked for by the chart now, and the chart is drawn
       when it arrives. */
    {
      const calls=[];
      const {context,page,errors}=await open('/?chart=RELIANCE',null,context=>context.route(/lightweight-charts/,route=>{
        calls.push(new URL(route.request().url()).hostname);
        return route.fulfill({contentType:'text/javascript',body:
          'var any=new Proxy(function(){},{get:function(t,k){return k==="then"?undefined:any;},apply:function(){return any;}});'+
          'window.__charts=0;window.LightweightCharts={createChart:function(){window.__charts++;return any;},CrosshairMode:{Normal:0}};'});
      }));
      await page.waitForFunction(()=>window.__charts>0,null,{timeout:8000});
      assert.deepEqual(calls,['unpkg.com'],'?chart=: the library is fetched once');
      assert.equal(await page.evaluate(()=>document.body.classList.contains('fullchart')),true,'?chart= is the full-window chart');
      assert.deepEqual(errors,[],'?chart=: no script errors');
      await context.close();
    }
    console.log('late load: Market first, every other tool behind it, in the order written');
  }finally{
    await browser.close();
    server.close();
  }
  function isLaterIn(p){return isLater.has(p);}
  function twice(asked){const seen=new Map();for(const u of asked)seen.set(u,(seen.get(u)||0)+1);return [...seen].filter(e=>e[1]>1&&!/^https?:/.test(e[0])).map(e=>e[0]);}
})().catch(error=>{console.error(error);process.exit(1);});
