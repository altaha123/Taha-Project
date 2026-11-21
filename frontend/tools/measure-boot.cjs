/* How long the homepage takes to become usable on a slow line.

     node frontend/tools/measure-boot.cjs [--root DIR] [--gzip] [--runs N]
                                          [--url /] [--cdn DIR] [--json]

   Serves DIR (default: frontend/) from a plain static server, opens it in
   Chromium throttled to 1.6 Mbit/s down, 750 kbit/s up and 150 ms latency
   with the cache off, and prints the median of N cold loads:

     first paint   the first frame with anything on it (the boot cover)
     DCL           DOMContentLoaded: every script the landing page needs has run
     finished      the boot cover is gone and the landing view is on show
     load          the load event: every script and stylesheet on the page is in
     to finished   requests completed and bytes received by `finished`
     in all        the same by `load`

   --gzip compresses text the way Vercel does (it serves brotli, which is a
   little smaller still). Without it the numbers are those of `python -m
   http.server`: about three and a half times the bytes production sends.

   The backend is answered at once with an empty reply, so the figures are
   the page's own weight and not the API's mood. Files from other sites (the
   chart library, the font stylesheet and fonts) are served through the same
   throttle from --cdn DIR when a copy is there, named by the last part of
   the address (the font stylesheet as fonts.css); without a copy the request
   fails, as it does offline. `--cdn DIR --fill` fetches those copies into
   DIR once. Serving them needs `openssl` on the path, for the throwaway
   certificate the stand-in for those sites is served under.               */
const fs=require('node:fs'), path=require('node:path'), http=require('node:http'), https=require('node:https'), zlib=require('node:zlib');
const os=require('node:os'), {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');

const args=process.argv.slice(2);
function opt(name,fallback){const i=args.indexOf('--'+name);return i<0?fallback:args[i+1];}
const root=path.resolve(opt('root',path.join(__dirname,'..')));
const GZIP=args.includes('--gzip'), RUNS=Number(opt('runs',5)), URL_PATH=opt('url','/');
const CDN=opt('cdn',null), JSON_OUT=args.includes('--json'), FILL=args.includes('--fill');
const NET={offline:false,latency:150,downloadThroughput:1.6e6/8,uploadThroughput:750e3/8};

const TYPES={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8',
  '.json':'application/json','.png':'image/png','.ico':'image/x-icon','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2'};
const TEXT=new Set(['.js','.css','.html','.json','.svg']);
const zipped=new Map();
function send(req,res,file){
  const ext=path.extname(file);
  let body=fs.readFileSync(file);
  res.setHeader('Content-Type',TYPES[ext]||'application/octet-stream');
  /* What Vercel sends for a static file. (Not no-store: Chromium will not
     reuse a preloaded file that says so, and fetches it a second time.) The
     browser's cache is switched off below, so every load is still cold. */
  res.setHeader('Cache-Control','public, max-age=0, must-revalidate');
  res.setHeader('Access-Control-Allow-Origin','*');
  if(GZIP&&TEXT.has(ext)&&/\bgzip\b/.test(req.headers['accept-encoding']||'')){
    if(!zipped.has(file))zipped.set(file,zlib.gzipSync(body,{level:9}));
    body=zipped.get(file);
    res.setHeader('Content-Encoding','gzip');
  }
  res.setHeader('Content-Length',body.length);
  res.end(body);
}
const server=http.createServer((req,res)=>{
  const url=decodeURIComponent(req.url.split('?')[0]);
  const file=path.join(root,url==='/'?'/index.html':url);
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){res.writeHead(404).end();return;}
  send(req,res,file);
});

/* Other sites' files. A request can only be re-addressed within its own
   protocol, and those are all https, so this needs a certificate. */
function cdnServer(){
  if(!CDN)return null;
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'measure-boot-'));
  try{
    execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=127.0.0.1',
      '-keyout',path.join(dir,'key.pem'),'-out',path.join(dir,'cert.pem')],{stdio:'ignore'});
  }catch(e){console.error('no openssl: files from other sites will fail to load');return null;}
  return https.createServer({key:fs.readFileSync(path.join(dir,'key.pem')),cert:fs.readFileSync(path.join(dir,'cert.pem'))},(req,res)=>{
    const file=path.join(path.resolve(CDN),path.basename(decodeURIComponent(req.url.split('?')[0])));
    if(!fs.existsSync(file)){res.writeHead(404).end();return;}
    send(req,res,file);
  });
}

/* Runs in the page from its first line: when did the cover come off? */
function probe(){
  window.__measure={finished:null,mark:function(){}};
  var seen=false;
  (function frame(){
    var up=!!document.documentElement&&document.documentElement.classList.contains('sh-boot');
    if(up)seen=true;
    if(seen&&!up&&window.__measure.finished===null){window.__measure.finished=performance.now();window.__measureFinished();return;}
    requestAnimationFrame(frame);
  })();
}

async function once(browser,origin,cdn){
  const context=await browser.newContext({viewport:{width:1280,height:800},ignoreHTTPSErrors:true});
  const page=await context.newPage();
  const cdp=await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
  await cdp.send('Network.emulateNetworkConditions',NET);
  const done=[]; let counting=true;
  cdp.on('Network.loadingFinished',e=>{if(counting)done.push(e.encodedDataLength);});
  await context.route(url=>!url.href.startsWith(origin),route=>{
    const type=route.request().resourceType(), u=new URL(route.request().url());
    if(['script','font','stylesheet','image'].includes(type)){
      if(!cdn||u.protocol!=='https:')return route.abort();
      /* Re-addressed, not answered here, so the throttle applies to it. */
      const name=u.hostname==='fonts.googleapis.com'?'fonts.css':path.basename(u.pathname);
      return route.continue({url:cdn+'/'+name});
    }
    return route.fulfill({json:{available:false,indices:[],rows:[],rankings:[],sectors:[],items:[],status:'closed'}});
  });
  let atFinished=null;
  await page.exposeFunction('__measureFinished',()=>{atFinished={requests:done.length,kb:done.reduce((a,b)=>a+b,0)/1024};});
  await page.addInitScript(probe);
  await page.goto(origin+URL_PATH,{waitUntil:'load',timeout:120000});
  await page.waitForFunction(()=>window.__measure.finished!==null,null,{timeout:30000}).catch(()=>{});
  counting=false;
  const result=await page.evaluate(()=>{
    const nav=performance.getEntriesByType('navigation')[0];
    const paint=name=>{const e=performance.getEntriesByName(name)[0];return e?e.startTime:null;};
    return {firstPaint:paint('first-paint'),fcp:paint('first-contentful-paint'),
      dcl:nav.domContentLoadedEventEnd,finished:window.__measure.finished,load:nav.loadEventEnd};
  });
  result.requestsToFinished=atFinished?atFinished.requests:null; result.kbToFinished=atFinished?atFinished.kb:null;
  result.requests=done.length; result.kb=done.reduce((a,b)=>a+b,0)/1024;
  await context.close();
  return result;
}

function median(list){const s=list.filter(v=>v!=null).sort((a,b)=>a-b);return s.length?s[Math.floor(s.length/2)]:null;}

/* The page's files from other sites, as index.html names them. */
async function fill(){
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8'), dir=path.resolve(CDN);
  fs.mkdirSync(dir,{recursive:true});
  const get=async(url,name)=>{
    const res=await fetch(url,{headers:{'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'}});
    if(!res.ok)throw new Error(url+' answered '+res.status);
    fs.writeFileSync(path.join(dir,name),Buffer.from(await res.arrayBuffer()));
  };
  const lib=/https:\/\/unpkg\.com\/[^"']+\.js/.exec(html), fonts=/https:\/\/fonts\.googleapis\.com\/[^"']+/.exec(html);
  if(lib)await get(lib[0],path.basename(new URL(lib[0]).pathname));
  if(fonts){
    await get(fonts[0].replace(/&amp;/g,'&'),'fonts.css');
    const faces=new Set(fs.readFileSync(path.join(dir,'fonts.css'),'utf8').match(/https:\/\/[^)]+\.woff2/g)||[]);
    for(const url of faces)await get(url,path.basename(new URL(url).pathname));
  }
  console.log('filled',dir,'with',fs.readdirSync(dir).length,'files');
}

(async()=>{
  if(FILL){if(!CDN)throw new Error('--fill needs --cdn DIR');await fill();}
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const other=cdnServer();
  if(other)await new Promise(resolve=>other.listen(0,'127.0.0.1',resolve));
  const cdn=other?'https://127.0.0.1:'+other.address().port:null;
  const browser=await chromium.launch({headless:true,executablePath:process.env.ALTAHA_CHROMIUM||process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
  try{
    const runs=[];
    for(let i=0;i<RUNS;i++)runs.push(await once(browser,origin,cdn));
    const out={};
    for(const key of Object.keys(runs[0]))out[key]=median(runs.map(r=>r[key]));
    if(JSON_OUT){console.log(JSON.stringify({root,gzip:GZIP,url:URL_PATH,runs:RUNS,median:out,all:runs}));return;}
    const s=ms=>ms==null?'    -':(ms/1000).toFixed(2).padStart(5)+' s';
    console.log(path.relative(process.cwd(),root)||'.',URL_PATH,GZIP?'(gzip)':'(uncompressed)','median of',RUNS);
    console.log('  first paint '+s(out.firstPaint)+'   DCL '+s(out.dcl)+'   finished '+s(out.finished)+'   load '+s(out.load));
    console.log('  to finished: '+Math.round(out.requestsToFinished)+' requests, '+Math.round(out.kbToFinished)+' KB   in all: '
      +Math.round(out.requests)+' requests, '+Math.round(out.kb)+' KB');
  }finally{
    await browser.close();
    server.close();
    if(other)other.close();
  }
})().catch(error=>{console.error(error);process.exit(1);});
