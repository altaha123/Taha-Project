/* A quiet orbit diagram behind the scan card: flat markers on hairline rings,
   coloured from the chart tokens. Decorative. Only universe-scan.js may display
   engine progress/findings. */
(function () {
  'use strict';
  function create(host, canvas) {
    var ctx;
    try { ctx=canvas.getContext('2d',{alpha:false}); } catch (_) { return null; }
    if(!ctx) return null; // The checkpoint controls remain usable without the drawing.
    var width=0,height=0,time=0,last=0,frame=0,visible=true,destroyed=false;
    var reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
    var place=host.querySelector('.su-voyage-place'), lastPlace=-1;
    // Research themes are decorative labels, not claims about live engine stages.
    var themes=["Quality & profitability","Earnings & growth","Valuation & value","Price momentum","Sector strength","Risk & resilience"];
    function smooth(value){value=Math.max(0,Math.min(1,value));return value*value*(3-2*value);}
    // Colours are tokens, read when drawn and read again when the theme changes.
    var palette=null;
    function token(name){
      var theme=window.AltahaTheme;
      if(theme)return theme.color(name);
      try{return getComputedStyle(document.documentElement).getPropertyValue(name).trim();}catch(_){return '';}
    }
    function colours(){
      if(!palette)palette={
        surface:token('--surface'),ring:token('--border'),hub:token('--border-strong'),signal:token('--highlight'),
        series:[1,2,3,4,5,6].map(function(i){return token('--chart-'+i);})
      };
      return palette;
    }
    function disc(x,y,r,colour){ctx.fillStyle=colour;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
    function draw(){
      if(!width||!height)return;
      var c=colours();
      ctx.globalAlpha=1;ctx.fillStyle=c.surface;ctx.fillRect(0,0,width,height);
      // One theme at a time comes forward: its marker grows, holds, then settles back.
      var chapter=Math.floor(time/12)%themes.length,phase=time%12;
      var depart=smooth((phase-9)/3);
      var encounter=smooth((phase-1.8)/1.5)*(1-depart);
      var label=themes[chapter];
      if(label!==lastPlace){place.textContent=label;lastPlace=label;}
      host.dataset.voyage=phase<2?'galaxy':'planet';
      // The diagram keeps clear of the heading and the labels on the left.
      var mobile=width<700;
      var radius=mobile?Math.min(width*.16,62):Math.min(width*.2,height*.34);
      var cx=mobile?width-radius-24:width*.69,cy=height*(mobile?.47:.46);
      var orbits=[.42,.71,1];
      ctx.lineWidth=1;ctx.strokeStyle=c.ring;
      orbits.forEach(function(scale){ctx.beginPath();ctx.arc(cx,cy,radius*scale,0,Math.PI*2);ctx.stroke();});
      disc(cx,cy,2.5,c.hub);
      // Six flat markers, one per research theme, in the chart series order.
      var base=Math.max(4,radius*.045);
      themes.forEach(function(_,i){
        var orbit=i%3,angle=i*Math.PI/3+time*(.10-orbit*.025);
        var r=base+(i===chapter?encounter*radius*.07:0);
        disc(cx+Math.cos(angle)*radius*orbits[orbit],cy+Math.sin(angle)*radius*orbits[orbit],r,c.series[i]);
      });
      // A faint moving signal, never interpreted as a progress percentage.
      if(host.dataset.state==='running'){
        var sweep=time*.65;ctx.strokeStyle=c.signal;ctx.lineWidth=1.5;
        ctx.beginPath();ctx.arc(cx,cy,radius,sweep,sweep+1.7);ctx.stroke();
      }
    }
    function canRun(){return !destroyed && visible && !document.hidden && !reduced.matches && !host.classList.contains('su-paused') && host.getClientRects().length>0;}
    function tick(now){
      frame=0;if(!canRun()){last=0;return;}
      if(!last)last=now;
      var delta=now-last;
      if(delta>=32){time+=Math.min(delta,80)/1000*(host.dataset.state==='running'?1.35:1);last=now;draw();}
      frame=requestAnimationFrame(tick);
    }
    function sync(){
      if(destroyed)return;
      if(canRun()){if(!frame){last=0;frame=requestAnimationFrame(tick);}}
      else {cancelAnimationFrame(frame);frame=0;last=0;}
    }
    function resize(){
      var rect=canvas.getBoundingClientRect();width=rect.width;height=rect.height;
      var dpr=Math.min(window.devicePixelRatio||1,1.5);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw();sync();
    }
    var resizeObserver=typeof ResizeObserver!=='undefined'?new ResizeObserver(resize):null;
    if(resizeObserver)resizeObserver.observe(canvas);else window.addEventListener('resize',resize);
    var intersection=typeof IntersectionObserver!=='undefined'?new IntersectionObserver(function(entries){visible=entries[0].isIntersecting;sync();},{rootMargin:'60px'}):null;
    if(intersection)intersection.observe(canvas);
    var tabObserver=new MutationObserver(sync);tabObserver.observe(document.body,{attributes:true,attributeFilter:['data-tab']});
    var view=document.getElementById('view-ideas');if(view)tabObserver.observe(view,{attributes:true,attributeFilter:['style','class','hidden']});
    function preference(){draw();sync();}
    function retheme(){palette=null;draw();}
    window.addEventListener('altaha:theme',retheme);
    reduced.addEventListener('change',preference);document.addEventListener('visibilitychange',sync);
    function destroy(){destroyed=true;window.removeEventListener('altaha:theme',retheme);cancelAnimationFrame(frame);if(resizeObserver)resizeObserver.disconnect();if(intersection)intersection.disconnect();tabObserver.disconnect();window.removeEventListener('resize',resize);reduced.removeEventListener('change',preference);document.removeEventListener('visibilitychange',sync);window.removeEventListener('pagehide',pagehide);}
    function pagehide(event){if(!event.persisted)destroy();}
    window.addEventListener('pagehide',pagehide);
    resize();return {sync:sync,destroy:destroy};
  }
  window.AltahaVoyage={create:create};
})();
