/* Planets visualise progress and open real checkpoint snapshots. */
(function () {
  'use strict';
  function estimateRemaining(samples, total) {
    if (samples.length < 4) return null;
    var first = samples[0], last = samples[samples.length - 1];
    if (last.elapsed < 60 || last.elapsed - first.elapsed < 15 || last.done <= first.done || last.done >= total) return null;
    // No countdown when recent polls show no measurable progress.
    if (samples.slice(-3).every(function (s) { return s.done === last.done; })) return null;
    return Math.ceil((total - last.done) * (last.elapsed - first.elapsed) / (last.done - first.done));
  }
  function stateOf(s) {
    if ((s.stopped_early || s.error) && s.status === 'done') return 'partial';
    return s.status || 'ready';
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { estimateRemaining: estimateRemaining, stateOf: stateOf };
  if (typeof document === 'undefined') return;
  var pending = {status:'ready'}, samples = [], runId = null, previous = 'ready', milestone = 0;
  var batches = [], discoveries = [], selected = -1, paused = false, observed = false, lastPct = 0, voyage;
  function node(tag, cls, text) {
    var el = document.createElement(tag); if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text; return el;
  }
  function mount() {
    var host = document.getElementById('scan-universe');
    if (!host || host.firstChild) return host;
    host.className = 'scan-universe';
    host.innerHTML = '<div class="su-scene">' +
      Array.from({length:6}, function (_, i) { return '<button type="button" class="su-planet su-planet-' + i + '" aria-label="Checkpoint ' + (i+1) + ': awaiting discoveries" aria-expanded="false"><i></i><span>' + String(i+1).padStart(2,'0') + '</span></button>'; }).join('') +
      '<button type="button" class="su-motion">Pause motion</button></div><div class="su-copy"><span class="su-eyebrow">DISCOVER / UNIVERSE SCAN</span><h3>Discover stocks.<br>Understand their potential.</h3><p class="su-status" role="status" aria-live="polite"></p><div class="su-meter"><progress class="su-progress" max="100" value="0" aria-label="Universe scan progress"></progress><b class="su-percent"></b></div><p class="su-detail"></p><p class="su-timing"></p><p class="su-milestone" role="status"></p><div class="su-controls"></div><span class="su-footnote">Tap a checkpoint to view stock findings. Preview scores may change as analysis continues.</span></div><section class="su-discoveries" aria-label="Live discoveries"><div class="su-discovery-head"><h4>Discoveries as they happen</h4><span>PRELIMINARY</span></div><p class="su-discovery-note">Detailed stock cards appear at analysis checkpoints. Early checks screen the universe first.</p><div class="su-cards"></div><div class="su-batch" hidden></div></section>';
    var scene=host.querySelector('.su-scene');
    var canvas=node('canvas','su-cosmos'); canvas.setAttribute('aria-hidden','true'); scene.prepend(canvas);
    var heading=node('div','su-scene-heading');
    heading.appendChild(host.querySelector('.su-eyebrow'));
    var title=host.querySelector('h3'); title.textContent='Discover stocks. Understand their potential.'; heading.appendChild(title); scene.appendChild(heading);
    var hud=node('div','su-voyage-hud');
    hud.appendChild(node('span','su-voyage-mode','STOCK SCREENER'));
    hud.appendChild(node('strong','su-voyage-place','Quality & profitability'));
    hud.appendChild(node('span','su-voyage-note','Stock rankings and analysis appear below'));
    scene.appendChild(hud);
    var credit=node('a','su-texture-credit','Planet maps: Solar System Scope · CC BY 4.0');
    credit.href='https://www.solarsystemscope.com/textures/';credit.target='_blank';credit.rel='noopener noreferrer';
    host.appendChild(credit);
    var checkpoints=node('div','su-checkpoints');
    checkpoints.setAttribute('aria-label','Analysis checkpoints');
    scene.querySelectorAll('.su-planet').forEach(function(el){checkpoints.appendChild(el);}); scene.appendChild(checkpoints);
    if(window.AltahaVoyage) voyage=window.AltahaVoyage.create(host,canvas);
    // Move existing controls, retaining their IDs and event handlers.
    var controls = host.querySelector('.su-controls');
    ['.hzrow','.brun'].forEach(function (sel) { var el = document.querySelector('#view-ideas ' + sel); if (el) controls.appendChild(el); });
    host.querySelectorAll('.su-planet').forEach(function (planet, i) {
      planet.addEventListener('click', function () { selected = selected === i ? -1 : i; renderBatch(host); });
    });
    host.querySelector('.su-motion').addEventListener('click', function () {
      paused = !paused; host.classList.toggle('su-paused',paused);
      this.textContent = paused ? 'Resume motion' : 'Pause motion'; this.setAttribute('aria-pressed', String(paused));
      if(voyage) voyage.sync();
    });
    var dock = node('button','su-dock'); dock.id = 'su-dock'; dock.type = 'button'; dock.hidden = true;
    dock.addEventListener('click', function () {
      if (window.AltahaNav) window.AltahaNav.go('discover','ideas',true);
      host.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
    });
    document.body.appendChild(dock);
    if ('MutationObserver' in window) {
      new MutationObserver(syncDock).observe(document.body, {attributes:true,attributeFilter:['data-tab']});
      new MutationObserver(syncDock).observe(document.getElementById('view-ideas'), {attributes:true,attributeFilter:['style']});
    }
    document.addEventListener('visibilitychange', function () { host.classList.toggle('su-background',document.hidden); });
    return host;
  }
  function card(row, index) {
    var item = node('details','su-card'); item.style.setProperty('--card-i',String(index));
    var summary = node('summary');
    summary.appendChild(node('span','su-card-symbol',row.symbol));
    summary.appendChild(node('b','su-card-score',Number.isFinite(row.score) ? row.score + '/100' : 'Unscored'));
    summary.appendChild(node('span','su-card-name',row.name));
    summary.appendChild(node('span','su-card-sector',row.sector));
    summary.appendChild(node('span','su-card-open','Explore finding ↗'));
    item.appendChild(summary);
    item.appendChild(node('p','su-card-finding',row.finding));
    item.appendChild(node('small','','Position score · preliminary snapshot, not a final rank.'));
    var link = node('a','','Open company analysis ↗'); link.href = 'stock.html?ticker=' + encodeURIComponent(row.symbol); link.target = '_blank'; link.rel = 'noopener';
    item.appendChild(link); return item;
  }
  function renderCards(container, rows) {
    var key = JSON.stringify(rows); if (container.dataset.rows === key) return;
    var opened = Array.from(container.querySelectorAll('details[open]')).map(function (el) {return el.querySelector('.su-card-symbol').textContent;});
    container.replaceChildren(); rows.forEach(function (r,i) {var el=card(r,i);el.open=opened.includes(r.symbol);container.appendChild(el);}); container.dataset.rows = key;
  }
  function renderBatch(host) {
    var box=host.querySelector('.su-batch'); box.hidden=selected<0;
    host.querySelectorAll('.su-planet').forEach(function (p,i) {p.setAttribute('aria-expanded',String(i===selected));});
    if(selected<0) {box.replaceChildren();delete box.dataset.batch;return;}
    var batch=batches[selected], key=selected+JSON.stringify(batch);
    if(box.dataset.batch===key) return; box.dataset.batch=key; box.replaceChildren();
    if(!batch) { box.appendChild(node('p','','Stock findings for this checkpoint are not available yet.')); return; }
    box.appendChild(node('h4','','Checkpoint '+batch.number+' · '+batch.count+' newly analysed stocks'));
    box.appendChild(node('p','','A sample from this checkpoint. Scores are preliminary.'));
    var cards=node('div','su-cards'); box.appendChild(cards); renderCards(cards,batch.rows || []);
  }
  function syncDock() {
    var dock=document.getElementById('su-dock'), view=document.getElementById('view-ideas');
    if(!dock||!view) return;
    var away = document.body.dataset.tab ? document.body.dataset.tab !== 'ideas' : view.style.display === 'none';
    dock.hidden = !away || !observed;
    var state=stateOf(pending);
    dock.textContent = state==='running' ? '◌ Universe scan · '+lastPct+'% · View discoveries' :
      state==='done' ? '✓ Scan complete · View stocks' :
      state==='starting' ? '◌ Connecting to the stock scan…' :
      state==='reconnecting' ? '◌ Scan reconnecting · Check progress' : 'Universe scan · View status';
    if(!['running','starting','reconnecting','done','partial','error'].includes(state)) dock.hidden=true;
  }
  function update(s) {
    pending=s||pending; var host=mount(); if(!host) return; s=pending;
    var state=stateOf(s), running=state==='running', complete=state==='done';
    if(state==='starting'||(s.run_id && s.run_id!==runId)) {
      samples=[];milestone=0;discoveries=[];batches=[];selected=-1;
      if(s.run_id) runId=s.run_id;
    }
    if(state==='cached'||state==='idle') {discoveries=[];batches=[];selected=-1;}
    if(Array.isArray(s.discoveries)&&state!=='cached'&&state!=='idle') discoveries=s.discoveries.slice(0,6);
    if(Array.isArray(s.planet_batches)&&state!=='cached'&&state!=='idle') batches=s.planet_batches.slice(0,6);
    var total=Math.max(0,Number(s.total)||0),done=Math.max(0,Number(s.done)||0),elapsed=Math.max(0,Number(s.elapsed_seconds)||0);
    var pct=total?Math.min(100,Math.round(done/total*100)):0;
    if(complete) pct=100;
    if(running && elapsed>0 && (!samples.length || samples[samples.length-1].elapsed!==elapsed)) {
      if(samples.length && (total!==samples[samples.length-1].total || done<samples[samples.length-1].done)) samples=[];
      samples.push({elapsed:elapsed,done:done,total:total});samples=samples.slice(-12);
    }
    if(running||state==='starting') observed=true;
    host.dataset.state=state; lastPct=pct;
    host.querySelector('.su-voyage-mode').textContent=running?'LIVE SCAN · '+pct+'%':state==='starting'?'CONNECTING TO SCAN':state==='reconnecting'?'SCAN CONNECTION INTERRUPTED':'STOCK SCREENER';
    if(voyage) voyage.sync();
    var results=document.getElementById('scan-results');if(results) results.hidden=['starting','running','reconnecting'].includes(state);
    var title='Your next stock idea starts here.',detail='Choose a horizon, then start your universe scan.';
    if(state==='starting'){title='Starting your stock scan…';detail='Waiting for the engine to confirm the scan.';}
    if(running){title=discoveries.length?'New stock findings are available.':'Exploring the stock universe…';detail=total?done.toLocaleString('en-IN')+' / '+total.toLocaleString('en-IN')+' analysis checks · '+(Number(s.scored)||0).toLocaleString('en-IN')+' scored':'Preparing the stock scan. Waiting for engine progress.';}
    if(complete){title='Your stock rankings are ready.';detail='Explore your final shortlist below. Preview cards retain their checkpoint scores.';}
    if(state==='partial'){title='The scan stopped before completion.';detail='Available results are shown below. See the scan note for details.';}
    if(state==='cached'){title='Your saved stock rankings are ready.';detail='Saved rankings appear below. Refresh to request a new scan.';}
    if(state==='idle'){title='Ready for another discovery.';detail='Start a scan to build your shortlist. Any saved results appear below.';}
    if(state==='reconnecting'){title='Reconnecting to the engine…';detail='Progress is unconfirmed. These previews are from the last received checkpoint.';}
    if(state==='error'){title='The scan needs your attention.';detail='See the message below. Available checkpoint previews are retained.';}
    host.querySelector('.su-status').textContent=title;host.querySelector('.su-detail').textContent=detail;
    var progress=host.querySelector('progress');progress.hidden=!(running||complete||state==='starting');
    if(state==='starting'||(running&&!total))progress.removeAttribute('value');else progress.value=pct;
    host.querySelector('.su-percent').textContent=(running&&total)||complete?pct+'%':'';
    var eta=running?estimateRemaining(samples,total):null;
    host.querySelector('.su-timing').textContent=running?Math.floor(elapsed/60)+'m '+Math.floor(elapsed%60)+'s elapsed · '+(eta!==null?'roughly '+Math.max(1,Math.floor(eta/60))+'–'+Math.max(2,Math.ceil(eta/60)+1)+' min remaining; may change':'estimating remaining time…'):'';
    var mark=Math.min(3,Math.floor(pct/25));
    if(running && mark>milestone){milestone=mark;host.classList.remove('su-celebrate');void host.offsetWidth;host.classList.add('su-celebrate');}
    host.querySelector('.su-milestone').textContent=running&&milestone?['','A quarter explored. The search continues.','Halfway through the analysis checks.','Three quarters explored. Keep discovering.'][milestone]:'';
    host.querySelectorAll('.su-planet').forEach(function (planet,i) {
      planet.classList.toggle('is-scanned',(running||complete)&&pct>=(i+1)*100/6);
      planet.classList.toggle('is-scanning',running&&pct>=i*100/6&&pct<(i+1)*100/6);
      planet.classList.toggle('has-discovery',!!batches[i]);
      planet.setAttribute('aria-label','Checkpoint '+(i+1)+(batches[i]?': open checkpoint '+batches[i].number:': awaiting discoveries'));
    });
    renderCards(host.querySelector('.su-cards'),discoveries);
    host.querySelector('.su-discovery-note').textContent=discoveries.length?'Real checkpoint discoveries · expand a card for the finding. Final ranking may change.':
      complete?'No checkpoint discoveries were available. See the final results below.':'Detailed stock cards appear at analysis checkpoints. Early checks screen the universe first.';
    if(state!==previous){
      if(complete && observed){var note=document.getElementById('su-complete-note');if(!note){note=node('div','su-sr');note.id='su-complete-note';note.setAttribute('role','status');document.body.appendChild(note);}note.textContent='Universe scan complete. Your stocks are ready in Discover.';}
      previous=state;
    }
    renderBatch(host);syncDock();
  }
  window.AltahaUniverse={update:update};
  document.addEventListener('DOMContentLoaded',function(){update(pending);});
})();
