/* Landing presentation. Decorative motion shares the site's single preference.
   The illustration contains no prices, scores, or fabricated live data. */
(function () {
  'use strict';
  function start() {
    var header=document.querySelector('header.wrap');
    if(!header||!document.getElementById('view-screener')||header.classList.contains('hh-stage'))return;
    var root=document.documentElement,reduce=matchMedia('(prefers-reduced-motion: reduce)');
    header.classList.add('hh-stage');
    var backdrop=document.createElement('div');backdrop.className='hh-atmosphere';backdrop.setAttribute('aria-hidden','true');
    backdrop.innerHTML='<div class="hh-halo hh-halo-one"></div><div class="hh-halo hh-halo-two"></div><div class="hh-grid"></div>';
    header.appendChild(backdrop);
    var layout=document.createElement('div');layout.className='hh-layout';
    layout.innerHTML='<section class="hh-hero" aria-labelledby="hh-title">'+
      '<p class="hh-label"><span aria-hidden="true"></span>Your investment research workspace</p>'+
      '<h1 id="hh-title" class="hh-head">Better research.<br><em>Clearer decisions.</em></h1>'+
      '<p class="hh-sub">Understand a company. See how your portfolio fits together. Give every investment a reason.</p>'+
      '<div class="hh-cta"><a class="hh-btn hh-btn-gold" href="index.html?go=research" data-hh-go="search">Research a stock <span aria-hidden="true">↗</span></a>'+
      '<a class="hh-btn" href="index.html?go=allocate" data-hh-go="allocate">Plan allocation <span aria-hidden="true">→</span></a></div>'+
      '<p class="hh-note">Stocks, portfolios and allocation. One connected view.</p>'+
      '<div class="hh-explore"><span>Start exploring</span><a href="index.html?go=ideas" data-hh-go="ideas">Find stock ideas ↗</a><a href="index.html?go=portfolio" data-hh-go="portfolio">Review my portfolio ↗</a></div></section>'+
      '<div class="hh-visual"><svg aria-hidden="true" class="hh-connections" viewBox="0 0 520 440" focusable="false">'+
      '<defs><linearGradient id="hh-line"><stop stop-color="#b69239" stop-opacity=".08"/><stop offset=".5" stop-color="#bd963c"/><stop offset="1" stop-color="#b69239" stop-opacity=".08"/></linearGradient></defs>'+
      '<ellipse class="hh-orbit-line" cx="260" cy="218" rx="196" ry="158"/><ellipse class="hh-orbit-line" cx="260" cy="218" rx="134" ry="106"/>'+
      '<g class="hh-wires"><path d="M120 103C220 103 170 218 260 218S330 342 415 342"/><path d="M419 112C320 112 350 218 260 218S190 346 100 346"/></g>'+
      '<g class="hh-signals"><path pathLength="100" d="M120 103C220 103 170 218 260 218S330 342 415 342"/><path pathLength="100" d="M419 112C320 112 350 218 260 218S190 346 100 346"/></g></svg>'+
      '<div class="hh-core" aria-hidden="true"><span class="hh-core-mark">A</span><strong>ALTAHA</strong><span>Connect the evidence</span></div>'+
      '<button type="button" class="hh-insight hh-quality" data-hh-go="search" aria-label="Research a company"><span class="hh-card-label">Company research</span><strong>Find the substance.</strong><div class="hh-bars"><i></i><i></i><i></i><i></i><i></i><i></i></div></button>'+
      '<button type="button" class="hh-insight hh-portfolio" data-hh-go="portfolio" aria-label="Review your portfolio"><span class="hh-card-label">Portfolio review</span><div class="hh-donut"></div><strong>See the whole picture.</strong></button>'+
      '<button type="button" class="hh-insight hh-evidence" data-hh-go="search" aria-label="Find a company and inspect its score evidence"><span class="hh-card-label">Behind every score</span><strong>Evidence. In focus.</strong><div class="hh-lines"><i></i><i></i><i></i></div></button>'+
      '<span class="hh-visual-caption">Research → Perspective → Decisions</span></div>';
    header.appendChild(layout);
    var motionButton=header.querySelector('.hm-motion');if(motionButton)header.appendChild(motionButton);
    var visible=true;
    function moving(){return visible&&!document.hidden&&!reduce.matches&&root.dataset.motion!=='off';}
    function sync(){header.classList.toggle('hh-active',moving());}
    var observer=new MutationObserver(sync);observer.observe(root,{attributes:true,attributeFilter:['data-motion']});
    var intersection=typeof IntersectionObserver!=='undefined'?new IntersectionObserver(function(entries){visible=entries[0].isIntersecting;sync();}):null;
    if(intersection)intersection.observe(header);
    reduce.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);sync();
    layout.addEventListener('click',function(e){
      var a=e.target.closest('[data-hh-go]');if(!a)return;
      var destination=a.dataset.hhGo;
      if(destination!=='search'){
        var targets={allocate:['allocate','allocate'],portfolio:['portfolio','portfolio'],ideas:['discover','ideas']};
        if(window.AltahaNav&&targets[destination]){e.preventDefault();window.AltahaNav.go(targets[destination][0],targets[destination][1],true);}return;
      }
      e.preventDefault();
      if(window.AltahaNav)window.AltahaNav.go('research','screener',false);
      // The shell search is the primary visible search. The legacy field can
      // live in a hidden tab; focusing it without activating that tab does nothing.
      var candidates=[document.getElementById('sh-q'),document.getElementById('tk')];
      var input=candidates.find(function(el){return el&&!el.disabled&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';});
      if(!input){window.location.href='index.html?go=research';return;}
      input.scrollIntoView({behavior:'auto',block:'center'});input.focus({preventScroll:true});
      var search=input.closest('.sh-search,.searchrow');
      if(search){search.classList.remove('hh-search-target');void search.offsetWidth;search.classList.add('hh-search-target');}

    });
    var input=document.getElementById('tk');
    function keepListVisible(){
      var row=input.closest('.searchrow');if(!row)return;
      var bar=document.querySelector('.ux-bottom');
      var bottom=bar&&getComputedStyle(bar).display!=='none'?bar.offsetHeight:0;
      var r=row.getBoundingClientRect(),extra=r.bottom+Math.min(330,innerHeight*.42)+12-(innerHeight-bottom);
      if(extra>0)window.scrollBy(0,Math.min(extra,Math.max(0,r.top-12)));
    }
    if(input)input.addEventListener('focus',keepListVisible);
    function cleanup(event){
      if(event.persisted)return;
      observer.disconnect();if(intersection)intersection.disconnect();reduce.removeEventListener('change',sync);
      document.removeEventListener('visibilitychange',sync);if(input)input.removeEventListener('focus',keepListVisible);
      window.removeEventListener('pagehide',cleanup);
    }
    window.addEventListener('pagehide',cleanup);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();

