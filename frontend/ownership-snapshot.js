/* Public filing snapshots. The URL carries a compact, fixed copy, not live values.
   No account data, credentials, PANs, external images or HTML are serialized. */
(function () {
  'use strict';
  var KEYS = ['promoter', 'fii', 'dii', 'public_non_institutional'];
  var LABELS = {promoter:'Promoters', fii:'Foreign institutions', dii:'Domestic institutions', public_non_institutional:'Non-institutional'};
  var COLORS = {promoter:'#ae831f', fii:'#277bb1', dii:'#278467', public_non_institutional:'#a97192'};
  function text(s, max) { return String(s == null ? '' : s).replace(/[\u0000-\u001f]/g, ' ').slice(0, max || 180); }
  function numeric(n, min, max) { return typeof n === 'number' && isFinite(n) && n >= min && n <= max ? Math.round(n * 100) / 100 : null; }
  function source(s) { try { var u = new URL(s); return u.protocol === 'https:' && /(^|\.)nseindia\.com$/.test(u.hostname) ? u.href.slice(0, 1000) : ''; } catch (_) { return ''; } }
  function pct(n) { return n == null ? 'Unavailable' : n.toFixed(2) + '%'; }
  function pp(n) { return n == null ? 'Comparison unavailable' : (n > 0 ? '+' : '') + n.toFixed(2) + ' pp'; }
  function normalize(raw) {
    if (!raw || typeof raw !== 'object') throw new Error('Invalid snapshot');
    var d = {version:1, symbol:text(raw.symbol,20), company:text(raw.company,120), period:text(raw.period,10),
      source:source(raw.source), retrieved:text(raw.retrieved,32), finding:text(raw.finding,270),
      peerMetric:['institutions','promoter','fii','dii'].indexOf(raw.peerMetric) >= 0 ? raw.peerMetric : 'institutions', peerPeriod:text(raw.peerPeriod,10), sector:text(raw.sector,60), peerFinding:text(raw.peerFinding,200)};
    if (!/^[A-Z0-9&.\-]{1,20}$/.test(d.symbol) || !/^\d{4}-\d{2}-\d{2}$/.test(d.period)) throw new Error('Invalid snapshot identity');
    d.split = (Array.isArray(raw.split) ? raw.split : []).filter(function (s) { return s && KEYS.indexOf(s.key) >= 0; }).slice(0,4).map(function (s) { return {key:s.key,pct:numeric(s.pct,0,100),change_qoq:numeric(s.change_qoq,-100,100),derived:s.derived === true}; });
    d.names = (Array.isArray(raw.names) ? raw.names : []).filter(Boolean).slice(0,3).map(function (n) { return {name:text(n.name,120),kind:text(n.kind,40),pct:numeric(n.pct,0,100),change_qoq:numeric(n.change_qoq,-100,100),new_in_table:n.new_in_table === true}; });
    d.peers = (Array.isArray(raw.peers) ? raw.peers : []).filter(function (p) { return p && p.available && p.period === d.peerPeriod; }).slice(0,6).map(function (p) {
      var m = (p.metrics || {})[d.peerMetric] || {};
      var row = {symbol:text(p.symbol,20), period:d.peerPeriod, source:source(p.source),available:true,metrics:{}};
      row.metrics[d.peerMetric] = {pct:numeric(m.pct,0,100),derived:m.derived === true}; return row;
    });
    return d;
  }
  function encode(d) { var bytes = new TextEncoder().encode(JSON.stringify(d)); var binary = ''; bytes.forEach(function (b) { binary += String.fromCharCode(b); }); return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }
  function decode(hash) { if (hash.length > 24000) throw new Error('Snapshot is too large'); var b = hash.replace(/-/g,'+').replace(/_/g,'/'); return normalize(JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(b), function (c) { return c.charCodeAt(0); })))); }
  function link(d) { var u = new URL('ownership-share.html', location.href); u.search = ''; u.hash = encode(d); return u.href; }
  function render(d, portrait) {
    var c = document.createElement('canvas'); c.width = 1080; c.height = portrait ? 1350 : 1080;
    var x = c.getContext('2d'), W = c.width, H = c.height;
    x.fillStyle = '#f7f5ef'; x.fillRect(0,0,W,H); x.fillStyle = '#ae831f'; x.fillRect(0,0,W,10);
    function line(s, px, py, size, color, maxWidth, lines, font) {
      x.fillStyle = color || '#20271f'; x.font = (font || '') + size + 'px Arial, sans-serif';
      var words = String(s).split(/\s+/), out = '', row = 0;
      for (var i=0; i<words.length; i++) {
        var next = out ? out + ' ' + words[i] : words[i];
        if (x.measureText(next).width > maxWidth && out) {
          if (row >= (lines || 1)-1) { while (x.measureText(out+'…').width > maxWidth) out=out.slice(0,-1); x.fillText(out+'…',px,py+row*size*1.3); return; }
          x.fillText(out,px,py+row*size*1.3); row++; out=words[i];
        } else out=next;
      }
      while(x.measureText(out).width > maxWidth && out.length>1) out=out.slice(0,-2)+'…';
      x.fillText(out,px,py+row*size*1.3);
    }
    function rule(y) { x.fillStyle='#dddcd3'; x.fillRect(54,y,972,1); }
    line('ALTAHA SCREENER  /  OWNERSHIP SNAPSHOT',54,57,20,'#756744',960,1,'600 ');
    line(d.symbol,54,122,48,'#20271f',950,1,'600 ');
    line(d.company,54,159,24,'#565c54',950,1);
    line('Reporting period '+d.period+'  ·  NSE company disclosure',54,196,20,'#565c54',950,1);
    var cols = 4, cw = 243;
    KEYS.forEach(function (key,i) {
      var s=d.split.find(function (p) { return p.key===key; }) || {}, px=54+i*cw;
      x.fillStyle='#e4e0d5'; x.fillRect(px,225,cw-24,5); x.fillStyle=COLORS[key]; x.fillRect(px,225,(s.pct || 0)/100*(cw-24),5);
      line(LABELS[key]+(s.derived?'*':''),px,254,17,'#565c54',cw-16,1);
      line(pct(s.pct==null?null:s.pct),px,296,s.pct==null?22:34,'#20271f',cw-18,1,'600 ');
      line(pp(s.change_qoq==null?null:s.change_qoq),px,325,15,'#565c54',cw-16,1);
    });
    rule(348);
    var extra=portrait?90:0;
    line('DISCLOSED INSTITUTIONAL INVESTORS',54,389,19,'#756744',960,1,'600 ');
    if (!d.names.length) line('Named institutional holders are unavailable in this snapshot.',54,440,23,'#565c54',950,2);
    d.names.forEach(function(n,i) {
      var y=431+i*(56+extra/3);
      line(n.name,54,y,22,'#20271f',645,1,'500 ');
      line(n.kind,54,y+23,15,'#565c54',645,1);
      line(pct(n.pct),738,y,25,'#20271f',288,1,'600 ');
      line(n.new_in_table?'Newly disclosed':pp(n.change_qoq),738,y+23,15,'#565c54',288,1);
    });
    rule(603+extra);
    line('WHAT STANDS OUT',54,638+extra,18,'#756744',960,1,'600 ');
    line(d.finding || 'Compare disclosed holdings with their source filings.',54,673+extra,23,'#20271f',965,3);
    var peerY=773+extra+(portrait?40:0);
    if (d.peers.length>1) {
      line((d.peerMetric==='institutions'?'Institutional holding':LABELS[d.peerMetric])+(d.sector?' · '+d.sector:'')+' · '+d.peerPeriod,54,peerY,18,'#756744',950,1,'600 ');
      // Three per row in portrait; compact six across in square.
      d.peers.forEach(function(p,i) {
        var col=portrait?i%3:i, row=portrait?Math.floor(i/3):0, pw=portrait?324:162, px=54+col*pw, py=peerY+34+row*73;
        var m=p.metrics[d.peerMetric];
        line(p.symbol,px,py,16,'#565c54',pw-14,1);
        line(pct(m.pct)+(m.derived?'*':''),px,py+28,23,'#20271f',pw-14,1,'600 ');
        x.fillStyle='#e4e0d5'; x.fillRect(px,py+41,pw-20,5); x.fillStyle='#ae831f'; x.fillRect(px,py+41,(m.pct || 0)/100*(pw-20),5);
      });
    } else line('Peer comparison not included — load peers before sharing.',54,peerY,19,'#565c54',950,2);
    if(d.peerFinding) line(d.peerFinding,54,H-185,16,'#565c54',965,2);
    rule(H-142);
    line('Source: NSE Reg 31 filing · * derived where marked · Changes in percentage points',54,H-112,16,'#565c54',965,1);
    line('Disclosed holdings are not proof of trades. Newly disclosed does not mean newly invested.',54,H-86,16,'#565c54',965,1);
    line('altahascreener.in  ·  '+d.symbol+'  ·  '+d.period,54,H-43,20,'#756744',965,1,'600 ');
    return c;
  }
  function open(raw) {
    var d;
    try { d=normalize(raw); } catch (_) { return; }
    var dialog=document.createElement('dialog'); dialog.className='oi-dialog'; dialog.setAttribute('aria-labelledby','oi-share-title');
    dialog.innerHTML='<div class="oi-section-head"><h3 id="oi-share-title">Ownership snapshot</h3><button type="button" class="oi-btn" data-close>Close</button></div><label class="oi-meta">Image format <select aria-label="Snapshot image format"><option value="portrait">Portrait · 1080 × 1350</option><option value="square">Square · 1080 × 1080</option></select></label><img alt="Ownership snapshot preview"><div class="oi-actions"><button type="button" class="oi-btn oi-primary" data-share>Share image…</button><button type="button" class="oi-btn" data-download>Download PNG</button><button type="button" class="oi-btn" data-copy>Copy snapshot link</button></div><p role="status" class="oi-meta"></p><label class="oi-meta">Snapshot link<input readonly class="oi-snapshot-link" aria-label="Snapshot link"></label><p class="oi-meta">This link preserves the displayed figures. Named institutions and loaded peer comparisons are included; unavailable data is not replaced with zero.</p>';
    document.body.appendChild(dialog); var url='', blob=null, seq=0;
    var status=dialog.querySelector('[role=status]'), input=dialog.querySelector('input'); input.value=link(d);
    function paint() {
      var ticket=++seq; blob=null; dialog.querySelector('[data-share]').disabled=true; dialog.querySelector('[data-download]').disabled=true;
      render(d,dialog.querySelector('select').value==='portrait').toBlob(function(b) {
        if(ticket!==seq || !dialog.isConnected) return;
        if(!b) { status.textContent='Could not create image. You can still copy the snapshot link.'; return; }
        if(url) URL.revokeObjectURL(url); blob=b; url=URL.createObjectURL(b); dialog.querySelector('img').src=url;
        dialog.querySelector('[data-share]').disabled=false; dialog.querySelector('[data-download]').disabled=false;
      },'image/png');
    }
    dialog.querySelector('select').addEventListener('change',paint);
    dialog.querySelector('[data-close]').addEventListener('click',function(){dialog.close();});
    dialog.addEventListener('close',function(){ seq++; if(url) URL.revokeObjectURL(url); dialog.remove(); });
    dialog.querySelector('[data-download]').addEventListener('click',function(){ if(!blob)return;var a=document.createElement('a');a.href=url;a.download=d.symbol+'-ownership-'+d.period+'-'+dialog.querySelector('select').value+'.png';a.click();status.textContent='PNG ready to attach to your post.'; });
    dialog.querySelector('[data-share]').addEventListener('click',async function(){
      if(!blob)return;var f=new File([blob],d.symbol+'-ownership.png',{type:'image/png'});
      try { if(navigator.canShare && navigator.canShare({files:[f]})) await navigator.share({files:[f],title:d.symbol+' ownership · '+d.period,text:d.symbol+' ownership snapshot · '+d.period+'\n'+input.value});
        else status.textContent='Image sharing is unavailable in this browser. Download the PNG or copy the snapshot link.';
      }catch(e){if(e.name!=='AbortError')status.textContent='Sharing failed. Download the PNG or copy the link instead.';}
    });
    dialog.querySelector('[data-copy]').addEventListener('click',async function(){try{await navigator.clipboard.writeText(input.value);status.textContent='Snapshot link copied.';}catch(_){input.focus();input.select();status.textContent='Select and copy the snapshot link below.';} });
    dialog.showModal(); paint();
  }
  function sharedPage() {
    var root=document.getElementById('snapshot-view');if(!root)return;
    try {
      var d=decode(location.hash.slice(1));
      root.querySelector('h1').textContent=d.symbol+' · Ownership snapshot';
      var canvas=render(d,true), image=root.querySelector('img'); image.src=canvas.toDataURL('image/png'); image.alt=d.company+' ownership snapshot for '+d.period;
      root.querySelector('[data-description]').textContent=d.finding;
      var details=root.querySelector('[data-data]');
      var rows=d.split.map(function(s){return LABELS[s.key]+': '+pct(s.pct)+(s.derived?' (derived)':'')+'; '+pp(s.change_qoq);}).concat(d.names.map(function(n){return n.name+': '+pct(n.pct)+'; '+(n.new_in_table?'newly disclosed':pp(n.change_qoq));}));
      d.peers.forEach(function(p){var m=p.metrics[d.peerMetric];rows.push(p.symbol+' peer '+d.peerPeriod+': '+pct(m.pct)+(m.derived?' (derived)':''));});
      rows.forEach(function(t){var li=document.createElement('li');li.textContent=t;details.appendChild(li);});
      d.peers.forEach(function(p){ if(!p.source)return; var li=document.createElement('li'), a=document.createElement('a'); a.href=p.source; a.target='_blank'; a.rel='noopener noreferrer'; a.textContent=p.symbol+' · '+p.period+' · peer source filing'; li.appendChild(a); details.appendChild(li); });
      var anchor=root.querySelector('[data-source]'); if(d.source)anchor.href=d.source;else anchor.hidden=true;
      root.querySelector('[data-live]').href='stock.html?ticker='+encodeURIComponent(d.symbol)+'&pane=owners';
      root.querySelector('[data-open]').addEventListener('click',function(){open(d);});
      root.querySelector('[data-asof]').textContent='Reporting period '+d.period+(d.retrieved?' · Retrieved '+d.retrieved:'')+'. Shared copy of filing data; check the source for revisions.';
      root.hidden=false; document.getElementById('snapshot-error').hidden=true;
    }catch(_){document.getElementById('snapshot-error').textContent='This snapshot link is incomplete or invalid. Open a company’s Ownership tab to create a new one.';}
  }
  window.OwnershipSnapshot={open:open};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sharedPage);else sharedPage();
})();
