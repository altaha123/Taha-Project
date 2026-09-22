/* Run with Playwright available: node frontend/tests/home-hero-browser.cjs
   Optional ALTAHA_CHROMIUM points to an installed Chromium executable.
   Exercises the landing components with the application's complete stylesheet stack. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'index.html'),'utf8');
const head=source.slice(source.indexOf('<head>')+6,source.indexOf('</head>')).replace(/<script\b[\s\S]*?<\/script>/g,'');
const start=source.indexOf('<header class="wrap">');
const header=source.slice(start,source.indexOf('</header>',start)+9);
const fixture='<!doctype html><html data-theme="light"><head>'+head+'</head><body class="sh-on" data-tab="screener">'+'<div class="sh-search"><input id="sh-q" aria-label="Search a stock"></div>'+header+
 '<main id="view-screener" class="wrap"><div class="searchrow"><input id="tk"><button id="go">Analyse</button></div></main><script src="home-motion.js"></script><script src="home-hero.js"></script></body></html>';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ALTAHA_CHROMIUM||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='altaha.test')return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fixture});
   const file=path.join(root,url.pathname.slice(1));
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   return route.fulfill({contentType:file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'application/octet-stream',body:fs.readFileSync(file)});
  });
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:900});await page.goto('http://altaha.test/');
   await page.locator('.hh-head').waitFor();
   assert(await page.locator('.hh-head').isVisible());
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no overflow at '+width);
   const heading=await page.locator('.hh-head').evaluate(el=>({size:parseFloat(getComputedStyle(el).fontSize),font:getComputedStyle(el).fontFamily}));
   assert(heading.size>=34);assert(!heading.font.includes('Serif'));
  }
  await page.evaluate(()=>{window.AltahaNav={go(...args){window.destination=args}}});
  await page.locator('[data-hh-go=allocate]').click();assert.equal(await page.evaluate(()=>window.destination[0]),'allocate');
  await page.evaluate(()=>document.getElementById('view-screener').style.display='none');
  await page.locator('.hh-btn-gold').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'sh-q','hidden legacy field must not receive focus');
  assert.equal(await page.evaluate(()=>window.destination[0]),'research');
  await page.evaluate(()=>{document.getElementById('sh-q').style.display='none';document.getElementById('view-screener').style.display='block'});
  await page.locator('.hh-btn-gold').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'tk','legacy fallback');
  await page.evaluate(()=>document.getElementById('sh-q').style.display='block');
  await page.locator('.hm-route[data-home-destination=search]').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'sh-q','lower research card');
  await page.locator('.hh-portfolio').click({force:true});assert.equal(await page.evaluate(()=>window.destination[0]),'portfolio');
  await page.locator('[data-hh-go=ideas]').click();assert.equal(await page.evaluate(()=>window.destination[1]),'ideas');
  await page.locator('.hm-motion').click();
  assert.equal(await page.locator('html').getAttribute('data-motion'),'off');
  assert.equal(await page.locator('.hh-signals').evaluate(el=>getComputedStyle(el).animationName),'none');
  assert(await page.locator('.hh-head').isVisible());assert(await page.locator('.hh-btn-gold').isVisible());
  await page.reload();assert.equal(await page.locator('html').getAttribute('data-motion'),'off');
  await page.locator('.hm-motion').click();
  await page.locator('.hh-head').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.querySelector('.hh-stage').classList.contains('hh-active'));
  assert.equal(await page.locator('.hh-signals').evaluate(el=>getComputedStyle(el).animationName),'hhFlow');
  const before=await page.locator('.hh-signals').evaluate(el=>getComputedStyle(el).strokeDashoffset);
  await page.waitForTimeout(150);
  assert.notEqual(await page.locator('.hh-signals').evaluate(el=>getComputedStyle(el).strokeDashoffset),before,'signal actually moves');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.hh-signals').evaluate(el=>getComputedStyle(el).animationName),'none');
  assert(await page.locator('.hh-head').isVisible());
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  assert(await page.locator('.hh-head').isVisible());
  const colors=await page.locator('.hh-insight').first().evaluate(el=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el.querySelector('strong')).color}));
  const rgb=s=>s.match(/[\d.]+/g).slice(0,3).map(Number);
  assert(rgb(colors.bg).reduce((a,b)=>a+b,0)<300,'dark cards use dark surfaces');
  assert(rgb(colors.fg).reduce((a,b)=>a+b,0)>450,'dark cards retain legible text');
  assert.deepEqual(errors,[]);console.log('Responsive widths, hidden legacy search, shell focus, fallback, research cards, exploration links, real motion and preferences passed.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});

