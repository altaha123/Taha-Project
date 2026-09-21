/* Decorative space flight. Only universe-scan.js may display engine progress/findings. */
(function () {
  'use strict';
  function create(host, canvas) {
    var ctx;
    try { ctx=canvas.getContext('2d',{alpha:false}); } catch (_) { return null; }
    if(!ctx) return null; // The CSS nebula and checkpoint controls remain usable.
    var width=0,height=0,time=0,last=0,frame=0,visible=true,destroyed=false;
    var reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
    var place=host.querySelector('.su-voyage-place'), lastPlace=-1;
    var seed=718;
    function random(){seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;}
    var stars=Array.from({length:240},function(){return {x:random()*2-1,y:random()*2-1,z:random(),size:.4+random()*1.3};});
    var dust=Array.from({length:1500},function(_,i){
      var radius=Math.pow(random(),.65);
      return {r:radius,a:(i%4)*Math.PI/2+radius*6+(random()-.5)*.65,s:.4+random()*1.35,c:i%3};
    });
    var worlds=[
      {name:'Jupiter',base:'#ab7954',light:'#f7dfb9',kind:'gas'},
      {name:'Venus',base:'#ba8845',light:'#ffedb3',kind:'cloud'},
      {name:'Saturn',base:'#ad9265',light:'#f5dfaa',kind:'rings'},
      {name:'Mars',base:'#a7472c',light:'#efae79',kind:'rock'},
      {name:'Neptune',base:'#2255ad',light:'#79beff',kind:'cloud'},
      {name:'Earth',base:'#247b76',light:'#b5f4db',kind:'ocean'}
    ];
    function smooth(value){value=Math.max(0,Math.min(1,value));return value*value*(3-2*value);}
    // Pre-render textured spheres once, avoiding gradients/noise on every frame.
    var sprites=worlds.map(function(world){
      var tile=document.createElement('canvas');tile.width=tile.height=256;
      var p=tile.getContext('2d'); if(!p)return tile;
      p.save();p.beginPath();p.arc(128,128,120,0,Math.PI*2);p.clip();
      var g=p.createRadialGradient(75,60,0,128,128,150);
      g.addColorStop(0,world.light);g.addColorStop(.48,world.base);g.addColorStop(1,'#02050e');p.fillStyle=g;p.fillRect(0,0,256,256);
      for(var i=0;i<95;i++){
        p.globalAlpha=.04+random()*.14;p.fillStyle=i%2?world.light:'#03121d';
        if(world.kind==='rings'||world.kind==='gas'||world.kind==='cloud'){
          p.save();p.translate(128,128);p.rotate(-.2);p.fillRect(-160,random()*280-140,320,2+random()*10);p.restore();
        }else{
          p.beginPath();p.ellipse(random()*256,random()*256,3+random()*28,2+random()*12,random()*6,0,Math.PI*2);p.fill();
        }
      }
      if(world.kind==='gas'){
        p.globalAlpha=.7;p.fillStyle='#a64d32';p.beginPath();p.ellipse(155,157,24,12,-.2,0,Math.PI*2);p.fill();
        p.strokeStyle='#e8ba85';p.lineWidth=4;p.stroke();
      }
      p.globalAlpha=1;
      var shade=p.createLinearGradient(10,0,240,180);shade.addColorStop(0,'#0000');shade.addColorStop(.45,'#0000');shade.addColorStop(1,'#000e');p.fillStyle=shade;p.fillRect(0,0,256,256);
      p.restore();return tile;
    });
    var renderer=window.AltahaPlanets?window.AltahaPlanets.create(textureReady):null;
    function textureReady(restored){
      if(destroyed)return;
      if(restored){if(renderer)renderer.destroy();renderer=window.AltahaPlanets.create(textureReady);}
      draw();
    }
    function glow(x,y,r,color){
      var g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,color);g.addColorStop(1,'#0000');ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2);
    }
    function galaxy(x,y,r,turn,alpha,blue){
      ctx.save();ctx.translate(x,y);ctx.rotate(-.38+Math.sin(time*.025)*.08);ctx.scale(1,.48);
      glow(0,0,r*.85,blue?'#244d843a':'#91644135');
      // Broad translucent arms give the star clusters a visible nebula body.
      for(var arm=0;arm<4;arm++){
        for(var layer=3;layer>0;layer--){
          ctx.beginPath();
          for(var step=0;step<=55;step++){
            var spread=step/55,angle=arm*Math.PI/2+spread*6+turn;
            var ax=Math.cos(angle)*spread*r,ay=Math.sin(angle)*spread*r;
            if(step===0)ctx.moveTo(ax,ay);else ctx.lineTo(ax,ay);
          }
          ctx.strokeStyle=blue?'#739ddb':'#b99aaf';ctx.globalAlpha=alpha*.025;
          ctx.lineWidth=r*.022*layer;ctx.stroke();
        }
      }
      ctx.globalAlpha=alpha;
      dust.forEach(function(d){
        var a=d.a+turn,px=Math.cos(a)*d.r*r,py=Math.sin(a)*d.r*r;
        ctx.fillStyle=blue?['#a6c8f1','#608ebc','#e2eafb'][d.c]:['#e7ba79','#ad8792','#f8e8c6'][d.c];
        ctx.globalAlpha=alpha*(1-d.r*.65);ctx.fillRect(px,py,d.s,d.s);
      });
      ctx.globalAlpha=alpha;glow(0,0,r*.24,blue?'#d5eaffac':'#ffe6b9cf');glow(0,0,r*.08,'#fff2dede');ctx.restore();
    }
    function planet(index,x,y,r,opacity,spin){
      if(opacity<=0)return;
      // GPU ray-traced globe: the surface rotates around its axis under a fixed sun.
      var globe=renderer&&r>18?renderer.render(index,time,r*5*Math.min(window.devicePixelRatio||1,1.5)):null;
      if(globe){ctx.save();ctx.globalAlpha=opacity;ctx.drawImage(globe,x-r*2.5,y-r*2.5,r*5,r*5);ctx.restore();return;}
      var world=worlds[index];ctx.save();ctx.globalAlpha=opacity;
      glow(x,y,r*1.3,index===1?'#66c9eb28':'#bbad9120');
      function ring(front){
        ctx.save();ctx.translate(x,y);ctx.rotate(-.35);ctx.scale(1,.32);
        for(var band=0;band<9;band++){
          ctx.beginPath();ctx.strokeStyle=band%2?'#cbb59488':'#806c5155';ctx.lineWidth=r*.035;
          ctx.ellipse(0,0,r*(1.35+band*.06),r*(1.35+band*.06),0,front?0:Math.PI,front?Math.PI:Math.PI*2);ctx.stroke();
        }ctx.restore();
      }
      if(world.kind==='rings')ring(false);
      ctx.save();ctx.translate(x,y);ctx.rotate(spin);ctx.drawImage(sprites[index],-r,-r,r*2,r*2);ctx.restore();
      if(world.kind==='rings')ring(true);
      ctx.restore();
    }
    function draw(){
      if(!width||!height)return;
      ctx.fillStyle='#050914';ctx.fillRect(0,0,width,height);
      // Each chapter visibly dives into the galaxy, approaches a world, then flies past it.
      var chapter=Math.floor(time/12)%worlds.length,phase=time%12;
      var approach=smooth((phase-2)/5),depart=smooth((phase-9)/3);
      var encounter=smooth((phase-1.8)/1.5)*(1-depart);
      var label=phase<2?'Entering the galaxy':phase<6?'Approaching '+worlds[chapter].name:worlds[chapter].name;
      if(label!==lastPlace){place.textContent=label;lastPlace=label;}
      host.dataset.voyage=phase<2?'galaxy':'planet';
      canvas.dataset.world=worlds[chapter].name;
      glow(width*.68,height*.5,width*.65,chapter%2?'#15364b75':'#34213a70');
      glow(width*.18,height*.85,width*.5,'#6c4e251f');
      var cx=width*.53,cy=height*.46;
      stars.forEach(function(s){
        var z=1-((s.z+time*.032)%1),f=.35+1.1/z;
        var x=cx+s.x*width*.48*f,y=cy+s.y*height*.48*f;
        if(x<0||x>width||y<0||y>height)return;
        ctx.globalAlpha=Math.min(.85,z*2+.12);ctx.fillStyle='#d9e8ff';
        ctx.beginPath();ctx.arc(x,y,Math.min(2.3,s.size*(.45+.25/z)),0,Math.PI*2);ctx.fill();
        if(z<.25){ctx.strokeStyle='#c4ddff38';ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+(x-cx)*.018,y+(y-cy)*.018);ctx.stroke();}
      });ctx.globalAlpha=1;
      var radius=Math.min(width*.39,height*.62);
      var zoom=1+smooth(phase/6)*2.8;
      var galaxyOpacity=1-encounter*.85;
      galaxy(width*(.56-approach*.12),height*.49,radius*zoom,time*.16,galaxyOpacity,false);
      galaxy(width*.87,height*.19,radius*.34,-time*.12,.45,true);
      galaxy(width*.12,height*.68,radius*.24,time*.21,.3,true);
      // A large recognisable destination occupies the open centre of the scene.
      var mobile=width<700;
      var heroRadius=Math.min(width*(mobile?.30:.20),height*.28)*(chapter===2?.70:1);
      var x=width*(mobile?.55:.69)-depart*width*.8;
      var y=height*(mobile?.47:.49);
      var r=12+approach*heroRadius+depart*heroRadius*.8;
      planet(chapter,x,y,r,encounter,Math.sin(time*.12)*.09);
      // Small moons establish depth around Jupiter and Saturn.
      if(chapter===0||chapter===2){
        for(var moon=0;moon<3;moon++){
          var orbit=time*.22+moon*2.1;
          planet(3,x+Math.cos(orbit)*r*1.65,y+Math.sin(orbit)*r*.5,r*.065,encounter*.8,0);
        }
      }
      // A faint moving signal, never interpreted as a progress percentage.
      if(host.dataset.state==='running'){
        var sweep=time*.65;ctx.strokeStyle='#e4c68a45';ctx.lineWidth=1;
        ctx.beginPath();ctx.ellipse(cx,cy,radius*.95,radius*.48,-.38,sweep,sweep+1.7);ctx.stroke();
      }
      var edge=ctx.createLinearGradient(0,0,0,height);edge.addColorStop(0,'#05091480');edge.addColorStop(.32,'#05091400');edge.addColorStop(.65,'#05091400');edge.addColorStop(1,'#050914f0');ctx.fillStyle=edge;ctx.fillRect(0,0,width,height);
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
    reduced.addEventListener('change',preference);document.addEventListener('visibilitychange',sync);
    function destroy(){destroyed=true;if(renderer)renderer.destroy();cancelAnimationFrame(frame);if(resizeObserver)resizeObserver.disconnect();if(intersection)intersection.disconnect();tabObserver.disconnect();window.removeEventListener('resize',resize);reduced.removeEventListener('change',preference);document.removeEventListener('visibilitychange',sync);window.removeEventListener('pagehide',pagehide);}
    function pagehide(event){if(!event.persisted)destroy();}
    window.addEventListener('pagehide',pagehide);
    resize();return {sync:sync,destroy:destroy};
  }
  window.AltahaVoyage={create:create};
})();
