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
  var DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday'], week = null, weekReq = null, weekFailed = false, weekNote = '';
  var discoveries = [], selected = -1, paused = false, observed = false, lastPct = 0, voyage;
  function node(tag, cls, text) {
    var el = document.createElement(tag); if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text; return el;
  }
  function mount() {
    var host = document.getElementById('scan-universe');
    if (!host || host.firstChild) return host;
    host.className = 'scan-universe';
    host.innerHTML = '<div class="su-scene">' +
      DAYS.map(function (d, i) { return '<button type="button" class="su-planet su-planet-' + i + '" aria-label="' + d + ' market synopsis" aria-expanded="false"><i></i><span><b>' + d.slice(0,3).toUpperCase() + '</b><small></small></span></button>'; }).join('') +
      '<button type="button" class="su-motion">Pause motion</button></div><div class="su-copy"><span class="su-eyebrow">DISCOVER / UNIVERSE SCAN</span><h3>Discover stocks.<br>Understand their potential.</h3><p class="su-status" role="status" aria-live="polite"></p><div class="su-meter"><progress class="su-progress" max="100" value="0" aria-label="Universe scan progress"></progress><b class="su-percent"></b></div><p class="su-detail"></p><p class="su-timing"></p><p class="su-milestone" role="status"></p><div class="su-controls"></div><span class="su-footnote">Tap a checkpoint to view stock findings. Preview scores may change as analysis continues.</span></div><section class="su-discoveries" aria-label="Live discoveries"><div class="su-discovery-head"><h4>Discoveries as they happen</h4><span>PRELIMINARY</span></div><p class="su-discovery-note">Detailed stock cards appear at analysis checkpoints. Early checks screen the universe first.</p><div class="su-cards"></div></section>';
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
    checkpoints.setAttribute('aria-label','This week, Monday to Friday');
    scene.querySelectorAll('.su-planet').forEach(function(el){checkpoints.appendChild(el);}); scene.appendChild(checkpoints);
    if(window.AltahaVoyage) voyage=window.AltahaVoyage.create(host,canvas);
    // Move existing controls, retaining their IDs and event handlers.
    var controls = host.querySelector('.su-controls');
    ['.hzrow','.brun'].forEach(function (sel) { var el = document.querySelector('#view-ideas ' + sel); if (el) controls.appendChild(el); });
    host.querySelectorAll('.su-planet').forEach(function (planet, i) {
      planet.addEventListener('click', function () { selected = selected === i ? -1 : i; renderDay(host); });
    });
    host.addEventListener('keydown', function (e) { if (e.key === 'Escape' && selected >= 0) { var p = host.querySelectorAll('.su-planet')[selected]; selected = -1; renderDay(host); if (p) p.focus(); } });
    loadWeek(host);
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
    if (row.sector) summary.appendChild(node('span','su-card-sector',row.sector));
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
  /* ── The week: five weekday planets, each opening that session's synopsis,
     told by a small cartoon bull in a space helmet. ─────────────────────── */
  function api() { return typeof API_BASE !== 'undefined' ? API_BASE : 'https://taha-project.onrender.com'; }
  function loadWeek(host) {
    if (week || weekReq || typeof fetch !== 'function') return weekReq;
    weekReq = fetch(api() + '/market/week').then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { week = (d && d.sessions) || []; weekNote = d && d.flows_source; labelPlanets(host); })
      .catch(function () { week = null; weekFailed = true; })
      .then(function () { weekReq = null; renderDay(host); });
    return weekReq;
  }
  // Sessions are matched to planets by weekday, so a holiday leaves its planet empty rather than shifting the week.
  function sessionFor(i) { return (week || []).filter(function (s) { return s.weekday === DAYS[i].slice(0,3); }).pop(); }
  function labelPlanets(host) {
    host.querySelectorAll('.su-planet').forEach(function (p, i) {
      var s = sessionFor(i), ch = s && s.indices && s.indices['NIFTY 50'] && s.indices['NIFTY 50'].change_pct;
      p.querySelector('small').textContent = s ? s.label.split(' ')[1] : '';
      p.classList.toggle('is-up', ch > 0); p.classList.toggle('is-down', ch < 0);
      p.setAttribute('aria-label', DAYS[i] + (s ? ' ' + s.label.slice(4) : '') + ' market synopsis');
    });
  }
  var MOUTH = {up:'M40 63 Q48 71 56 63', down:'M40 68 Q48 60 56 68', flat:'M41 66 L55 66', wait:'M44 66 Q48 68 52 66'};
  function mascot(mood) {
    return '<svg viewBox="0 0 96 110" aria-hidden="true">' +
      '<ellipse class="m-shadow" cx="48" cy="106" rx="22" ry="3"/>' +
      '<path class="m-arm" d="M78 70 q12 -6 12 -20" />' +
      '<rect class="m-body" x="30" y="78" width="36" height="24" rx="10"/>' +
      '<circle class="m-helmet" cx="48" cy="50" r="38"/>' +
      '<path class="m-horn" d="M26 38 q-10 -4 -10 -16 q8 6 16 8z"/><path class="m-horn" d="M70 38 q10 -4 10 -16 q-8 6 -16 8z"/>' +
      '<ellipse class="m-ear" cx="22" cy="48" rx="7" ry="4"/><ellipse class="m-ear" cx="74" cy="48" rx="7" ry="4"/>' +
      '<ellipse class="m-face" cx="48" cy="54" rx="24" ry="25"/>' +
      '<ellipse class="m-snout" cx="48" cy="66" rx="14" ry="9"/>' +
      '<circle class="m-nostril" cx="43" cy="65" r="1.6"/><circle class="m-nostril" cx="53" cy="65" r="1.6"/>' +
      '<g class="m-eyes"><circle cx="39" cy="47" r="3.4"/><circle cx="57" cy="47" r="3.4"/></g>' +
      '<path class="m-mouth" d="' + (MOUTH[mood] || MOUTH.flat) + '" transform="translate(0 6)"/>' +
      '<path class="m-glare" d="M24 30 q10 -16 28 -18"/></svg>';
  }
  function fmt(v, dp) { return Number(v).toLocaleString('en-IN', {maximumFractionDigits: dp == null ? 0 : dp}); }
  // A rising VIX is fear rising, so its colours are inverted.
  function pctSpan(v, invert) { var good = invert ? v < 0 : v > 0, bad = invert ? v > 0 : v < 0;
    return v == null ? '<em>—</em>' : '<em class="' + (good ? 'up' : bad ? 'dn' : '') + '">' + (v > 0 ? '+' : '') + v.toFixed(2) + '%</em>'; }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function dayBody(s) {
    var idx = s.indices || {}, f = s.flows;
    var cells = ['NIFTY 50','SENSEX','BANK NIFTY','INDIA VIX'].filter(function (k) { return idx[k]; }).map(function (k) {
      return '<div><b>' + k + '</b><span>' + fmt(idx[k].close, k === 'INDIA VIX' ? 2 : 0) + '</span>' + pctSpan(idx[k].change_pct, k === 'INDIA VIX') + '</div>'; }).join('');
    var flows;
    if (f && f.fii && f.dii && f.fii.net != null && f.dii.net != null) {
      var max = Math.max(Math.abs(f.fii.net), Math.abs(f.dii.net)) || 1;
      flows = [['FII / FPI', f.fii], ['DII', f.dii]].map(function (r) {
        var n = r[1].net, w = Math.round(Math.abs(n) / max * 50);
        return '<div class="su-flow"><b>' + r[0] + '</b><span class="su-flow-bar"><i class="' + (n >= 0 ? 'buy' : 'sell') + '" style="--w:' + w + '%"></i></span>' +
          '<em class="' + (n >= 0 ? 'up' : 'dn') + '">' + (n >= 0 ? '+' : '−') + '₹' + fmt(Math.abs(n)) + ' cr</em></div>'; }).join('');
    } else {
      flows = '<p class="su-flow-none">FII/DII flows weren’t recorded for this session. NSE publishes only the latest day, so the week fills in as each session is captured.</p>';
    }
    return '<span class="su-day-date">' + esc(s.label) + '</span><p class="su-day-syn">' + esc(s.synopsis) + '</p>' +
      '<div class="su-day-idx">' + cells + '</div><div class="su-flows"><span class="su-flows-h">Institutional flows · net</span>' + flows + '</div>' +
      (weekNote ? '<small class="su-day-src">' + esc(weekNote) + '</small>' : '');
  }
  function renderDay(host) {
    var scene = host.querySelector('.su-scene'), box = scene.querySelector('.su-day');
    host.querySelectorAll('.su-planet').forEach(function (p, i) { p.setAttribute('aria-expanded', String(i === selected)); });
    host.classList.toggle('su-day-open', selected >= 0);
    if (selected < 0) { if (box) { box.classList.add('leaving'); setTimeout(function () { if (box.classList.contains('leaving')) box.remove(); }, 260); } return; }
    var s = sessionFor(selected), mood = s ? s.mood : 'wait';
    var html = s ? dayBody(s) : '<span class="su-day-date">' + DAYS[selected] + '</span><p class="su-day-syn">' +
      (weekReq ? 'Checking the tape…' : weekFailed ? 'Couldn’t reach the market data just now. Tap the planet again to retry.' :
       week ? 'No session on record for this day — likely a market holiday.' : 'Checking the tape…') + '</p>';
    if (!s && weekFailed && !weekReq) { weekFailed = false; loadWeek(host); }
    var key = selected + '|' + mood + '|' + html;
    if (box && box.dataset.key === key && !box.classList.contains('leaving')) return;
    var fresh = !box || box.classList.contains('leaving') || box.dataset.sel !== String(selected);
    if (box && fresh) box.remove();
    if (fresh) { box = node('div', 'su-day'); box.setAttribute('role', 'dialog'); scene.appendChild(box); }
    box.dataset.key = key; box.dataset.sel = String(selected); box.dataset.mood = mood;
    box.setAttribute('aria-label', DAYS[selected] + ' market synopsis');
    box.innerHTML = '<div class="su-mascot">' + mascot(mood) + '</div><div class="su-bubble"><button type="button" class="su-day-x" aria-label="Close">×</button>' + html + '</div>';
    box.querySelector('.su-day-x').addEventListener('click', function () { var p = host.querySelectorAll('.su-planet')[selected]; selected = -1; renderDay(host); if (p) p.focus(); });
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
      samples=[];milestone=0;discoveries=[];
      if(s.run_id) runId=s.run_id;
    }
    if(state==='cached'||state==='idle') discoveries=[];
    if(Array.isArray(s.discoveries)&&state!=='cached'&&state!=='idle') discoveries=s.discoveries.slice(0,6);
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
    renderCards(host.querySelector('.su-cards'),discoveries);
    host.querySelector('.su-discovery-note').textContent=discoveries.length?'Real checkpoint discoveries · expand a card for the finding. Final ranking may change.':
      complete?'No checkpoint discoveries were available. See the final results below.':'Detailed stock cards appear at analysis checkpoints. Early checks screen the universe first.';
    if(state!==previous){
      if(complete && observed){var note=document.getElementById('su-complete-note');if(!note){note=node('div','su-sr');note.id='su-complete-note';note.setAttribute('role','status');document.body.appendChild(note);}note.textContent='Universe scan complete. Your stocks are ready in Discover.';}
      previous=state;
    }
    syncDock();
  }
  window.AltahaUniverse={update:update};
  document.addEventListener('DOMContentLoaded',function(){update(pending);});
})();
