/* Run with Playwright available: node frontend/tests/boot-cover-browser.cjs

   index.html's own markup is the site's first design; the page a reader is
   meant to see is built over it by deferred scripts that each run as they
   arrive. On a slow line every step in between used to be painted: the old
   masthead, then the old masthead under a new menu, then the new header over
   the old banner, and only then the page. This holds the scripts apart the
   way a slow line does and checks that no step but the last is ever on show. */
const fs=require('node:fs'), path=require('node:path'), http=require('node:http'), assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const TYPES={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.png':'image/png','.ico':'image/x-icon','.webp':'image/webp'};
/* The scripts that each redraw the page, held back by different amounts. */
const HOLD={'/nav.js':150,'/shell.js':500,'/doors.js':850,'/home-hero.js':1200};
const server=http.createServer((req,res)=>{
  const url=decodeURIComponent(req.url.split('?')[0]);
  const file=path.join(root,url==='/'?'/index.html':url);
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){res.writeHead(404).end();return;}
  setTimeout(()=>{
    res.setHeader('Content-Type',TYPES[path.extname(file)]||'application/octet-stream');
    res.end(fs.readFileSync(file));
  },HOLD[url]||0);
});

/* Recorded in the page, every frame from the first: is the cover up, and if
   it is not, is what stands behind it the finished page? */
function probe(){
  window.__boot={frames:[],covered:0,ended:null};
  function frame(){
    var b=document.body;
    if(b){
      var cover=document.getElementById('sh-bootcover');
      var up=!!cover&&getComputedStyle(cover).display!=='none'&&getComputedStyle(cover).visibility!=='hidden';
      if(up){
        var top=document.elementFromPoint(innerWidth/2,innerHeight/2);
        if(!top||!cover.contains(top))window.__boot.frames.push('cover is up but not on top');
        if(cover.getBoundingClientRect().width<innerWidth||cover.getBoundingClientRect().height<innerHeight)window.__boot.frames.push('cover does not fill the window');
        window.__boot.covered++;
      }else{
        var header=document.querySelector('header.wrap'), tabs=document.querySelector('.tabnav');
        var shown=function(el){return !!el&&getComputedStyle(el).display!=='none'&&getComputedStyle(el).visibility!=='hidden'&&el.getClientRects().length>0;};
        var problems=[];
        if(!b.classList.contains('sh-on'))problems.push('no header yet');
        if(shown(tabs))problems.push('the old tab pill is on show');
        if(shown(header)&&!header.classList.contains('hh-stage'))problems.push('the old masthead is on show');
        if(shown(header)&&document.documentElement.classList.contains('doors-on'))problems.push('a banner over a door view');
        ['today','ideahub','money'].forEach(function(w){
          var v=document.getElementById('view-'+w);
          if(v&&v.style.display!=='none'&&!v.firstChild)problems.push(w+' is open and empty');
        });
        if(window.__boot.ended===null)window.__boot.ended=Math.round(performance.now());
        if(problems.length)window.__boot.frames.push(problems.join(', '));
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const browser=await chromium.launch({headless:true,executablePath:process.env.ALTAHA_CHROMIUM||process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
  async function open(url,options,routes){
    const context=await browser.newContext(Object.assign({viewport:{width:1280,height:800}},options||{}));
    const page=await context.newPage(), errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      if(u.origin===origin)return route.continue();
      if(['script','font','stylesheet','image'].includes(route.request().resourceType()))return route.abort();
      return route.fulfill({json:{available:false,indices:[],rows:[],rankings:[],sectors:[],items:[],status:'closed'}});
    });
    if(routes)await routes(context);
    if(!options||options.javaScriptEnabled!==false)await page.addInitScript(probe);
    await page.goto(origin+url,{waitUntil:'load'});
    return {context,page,errors};
  }
  try{
    for(const [url,view] of [['/','view-today'],['/#portfolio','view-portfolio'],['/?go=filings','view-filings']]){
      const {context,page,errors}=await open(url);
      await page.waitForFunction(()=>!document.getElementById('sh-bootcover'),null,{timeout:8000});
      await page.waitForTimeout(700);
      const seen=await page.evaluate(()=>window.__boot);
      assert.deepEqual([...new Set(seen.frames)],[],url+': an unfinished page was shown');
      assert(seen.covered>20,url+': the cover was up while the page was built ('+seen.covered+' frames)');
      assert(seen.ended>=1200,url+': the cover came off before the last script had run ('+seen.ended+'ms)');
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-boot')),false,url+': the boot class is gone');
      assert.equal(await page.evaluate(id=>getComputedStyle(document.getElementById(id)).display!=='none',view),true,url+' opens '+view);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,url+': no sideways scroll');
      assert.deepEqual(errors,[],url+': no script errors');
      await context.close();
    }

    /* The header never arrives. The reader is owed the page that did. */
    {
      const {context,page}=await open('/',null,context=>context.route('**/shell.js*',route=>route.abort()));
      await page.waitForFunction(()=>!document.getElementById('sh-bootcover'),null,{timeout:8000});
      assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('sh-boot')),false,'the cover lifts without the header');
      await context.close();
    }

    /* Without JavaScript the markup is the whole page; there is nothing to wait for. */
    {
      const {context,page}=await open('/',{javaScriptEnabled:false});
      assert.equal(await page.locator('#sh-bootcover').isVisible(),false,'no cover without JavaScript');
      assert.equal(await page.locator('header.wrap .brand').isVisible(),true,'the page itself is shown');
      await context.close();
    }
    console.log('boot cover: only the finished page is ever shown');
  }finally{
    await browser.close();
    server.close();
  }
})().catch(error=>{console.error(error);process.exit(1);});
