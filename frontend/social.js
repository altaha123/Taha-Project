/* ===========================================================================
   social.js — the Social surface for Altaha Screener
   ---------------------------------------------------------------------------
   Same pattern as nav.js and scoring.js: a wrapper layer. It does not rewrite
   index.html, it does not touch the analysis page, and it injects its own CSS
   built entirely from the page's existing Ledger tokens.

   One <script> line in index.html and this file is the whole feature.

   Everything here is read-and-copy by default. Approving or posting needs the
   admin key, which is typed once and kept in this browser only.
   =========================================================================== */
(function () {
  'use strict';
  if (window.__altahaSocial) return;
  window.__altahaSocial = true;

  /* ---------- where the backend lives -------------------------------- */
  function apiBase() {
    var cands = [window.API_BASE, window.API, window.BASE, window.BACKEND, window.API_URL];
    for (var i = 0; i < cands.length; i++) {
      if (typeof cands[i] === 'string' && /^https?:\/\//.test(cands[i])) {
        return cands[i].replace(/\/+$/, '');
      }
    }
    if (/localhost|127\.0\.0\.1/.test(location.host)) return 'http://127.0.0.1:8000';
    return 'https://taha-project.onrender.com';
  }
  var API = apiBase();

  var KEY_STORE = 'altaha-admin-key';
  var FILTER_STORE = 'altaha-social-filter';
  function adminKey() { try { return localStorage.getItem(KEY_STORE) || ''; } catch (e) { return ''; } }
  function setAdminKey(v) { try { localStorage.setItem(KEY_STORE, v || ''); } catch (e) {} }

  /* ---------- styles, all from existing tokens ----------------------- */
  var CSS = `
  #altaha-social-panel{position:fixed;inset:0;z-index:9800;display:none;
    background:var(--paper,#F6F2E9);overflow-y:auto;-webkit-overflow-scrolling:touch}
  #altaha-social-panel.open{display:block}
  .as-wrap{max-width:820px;margin:0 auto;padding:22px 18px 90px}
  .as-top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
    border-bottom:1px solid var(--gold-line,#B08D2E);padding-bottom:12px;margin-bottom:6px}
  .as-title{font-family:var(--display,'Instrument Serif',Georgia,serif);
    font-size:clamp(26px,5vw,34px);line-height:1.05;color:var(--ink,#1A1712);margin:0}
  .as-sub{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;
    letter-spacing:.08em;text-transform:uppercase;color:var(--mute,#726B5D)}
  .as-close{margin-left:auto;background:none;border:1px solid var(--mute,#726B5D);
    color:var(--ink,#1A1712);border-radius:999px;width:34px;height:34px;font-size:17px;
    cursor:pointer;line-height:1;transition:background var(--t1,140ms) var(--ease,ease)}
  .as-close:hover{background:rgba(0,0,0,.05)}
  .as-close:focus-visible{outline:2px solid var(--gold-line,#B08D2E);outline-offset:2px}

  .as-note{font-size:12.5px;line-height:1.55;color:var(--mute,#726B5D);
    margin:12px 0 16px;padding:10px 12px;border-left:2px solid var(--gold-line,#B08D2E)}

  .as-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
  .as-chip{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;
    letter-spacing:.05em;padding:5px 11px;border-radius:999px;cursor:pointer;
    border:1px solid var(--mute,#726B5D);background:transparent;color:var(--mute,#726B5D);
    transition:all var(--t1,140ms) var(--ease,ease)}
  .as-chip[aria-pressed="true"]{background:var(--ink,#1A1712);color:var(--paper,#F6F2E9);
    border-color:var(--ink,#1A1712)}
  .as-chip:focus-visible{outline:2px solid var(--gold-line,#B08D2E);outline-offset:2px}

  .as-row{border-top:1px solid rgba(120,110,90,.22);padding:18px 0;
    opacity:0;transform:translateY(8px);
    animation:asArrive var(--t3,640ms) var(--ease-soft,cubic-bezier(.16,1,.3,1)) forwards}
  @keyframes asArrive{to{opacity:1;transform:none}}
  @media (prefers-reduced-motion:reduce){.as-row{animation:none;opacity:1;transform:none}}

  .as-eyebrow{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;
    letter-spacing:.1em;text-transform:uppercase;color:var(--mute,#726B5D);margin-bottom:7px}
  .as-tag{color:var(--gold,#8A6D1E);border-bottom:1px solid var(--gold-line,#B08D2E);padding-bottom:1px}
  .as-tierA::after{content:'●';color:var(--gold-line,#B08D2E);font-size:8px}
  .as-body{font-size:16px;line-height:1.5;color:var(--ink,#1A1712);margin:0 0 8px}
  .as-figs{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:12.5px;
    color:var(--gold,#8A6D1E);margin-bottom:10px}

  .as-post{width:100%;box-sizing:border-box;min-height:112px;resize:vertical;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:12.5px;line-height:1.55;
    color:var(--ink,#1A1712);background:rgba(0,0,0,.025);
    border:1px solid rgba(120,110,90,.3);border-radius:4px;padding:10px 11px}
  .as-post:focus{outline:none;border-color:var(--gold-line,#B08D2E)}

  .as-acts{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
  .as-btn{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;letter-spacing:.06em;
    text-transform:uppercase;padding:7px 14px;border-radius:3px;cursor:pointer;
    border:1px solid var(--ink,#1A1712);background:var(--ink,#1A1712);color:var(--paper,#F6F2E9);
    transition:opacity var(--t1,140ms) var(--ease,ease)}
  .as-btn.ghost{background:transparent;color:var(--mute,#726B5D);border-color:var(--mute,#726B5D)}
  .as-btn:hover{opacity:.82}
  .as-btn:focus-visible{outline:2px solid var(--gold-line,#B08D2E);outline-offset:2px}
  .as-count{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;
    color:var(--mute,#726B5D);margin-left:auto}
  .as-count.over{color:#B3261E}
  .as-src{font-size:11.5px;color:var(--mute,#726B5D);margin-top:7px}
  .as-src a{color:var(--gold,#8A6D1E)}

  .as-skel{height:74px;border-radius:4px;margin:14px 0;
    background:linear-gradient(90deg,rgba(0,0,0,.04) 25%,rgba(0,0,0,.08) 37%,rgba(0,0,0,.04) 63%);
    background-size:400% 100%;animation:asSkel 1.4s ease-in-out infinite}
  @keyframes asSkel{0%{background-position:100% 0}100%{background-position:0 0}}
  .as-empty{padding:34px 0;color:var(--mute,#726B5D);font-size:14px;line-height:1.6}
  .as-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:9900;
    background:var(--ink,#1A1712);color:var(--paper,#F6F2E9);padding:9px 16px;border-radius:999px;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11.5px;letter-spacing:.05em;
    opacity:0;transition:opacity var(--t2,300ms) var(--ease,ease);pointer-events:none}
  .as-toast.show{opacity:1}
  #altaha-social-open{font:inherit}
  @media(max-width:560px){.as-wrap{padding:16px 14px 90px}.as-body{font-size:15px}}
  `;

  function injectCSS() {
    if (document.getElementById('altaha-social-css')) return;
    var s = document.createElement('style');
    s.id = 'altaha-social-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ---------- toast ---------------------------------------------------- */
  var toastEl;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'as-toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function () { toastEl.classList.remove('show'); }, 2000);
  }

  /* ---------- panel ---------------------------------------------------- */
  var panel, listEl, statusEl, activeFilter = 'all';
  try { activeFilter = localStorage.getItem(FILTER_STORE) || 'all'; } catch (e) {}

  function buildPanel() {
    panel = document.createElement('div');
    panel.id = 'altaha-social-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Social — announcement feed');
    panel.innerHTML = ''
      + '<div class="as-wrap">'
      + '  <div class="as-top">'
      + '    <h2 class="as-title">Social</h2>'
      + '    <span class="as-sub" id="as-status">loading</span>'
      + '    <button class="as-close" id="as-close" aria-label="Close Social">&times;</button>'
      + '  </div>'
      + '  <p class="as-note">Plain restatements of what companies filed with BSE and NSE today. '
      + '  No view, no target, no recommendation — that stays out until the RA registration is in hand. '
      + '  Read the filing before you post anything.</p>'
      + '  <div class="as-bar" id="as-filters"></div>'
      + '  <div id="as-list"><div class="as-skel"></div><div class="as-skel"></div><div class="as-skel"></div></div>'
      + '</div>';
    document.body.appendChild(panel);
    listEl = panel.querySelector('#as-list');
    statusEl = panel.querySelector('#as-status');
    panel.querySelector('#as-close').addEventListener('click', close);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('open')) close();
    });
  }

  var FILTERS = [
    ['all', 'All'], ['order_win', 'Orders'], ['ma', 'M&A'], ['fundraise', 'Fundraise'],
    ['credit_rating', 'Ratings'], ['pledge', 'Pledge'], ['board_change', 'Leadership'],
    ['capex', 'Capex'], ['regulatory', 'Regulatory'], ['results', 'Results'],
  ];

  function renderFilters() {
    var bar = panel.querySelector('#as-filters');
    bar.innerHTML = '';
    FILTERS.forEach(function (f) {
      var b = document.createElement('button');
      b.className = 'as-chip';
      b.type = 'button';
      b.textContent = f[1];
      b.setAttribute('aria-pressed', String(activeFilter === f[0]));
      b.addEventListener('click', function () {
        activeFilter = f[0];
        try { localStorage.setItem(FILTER_STORE, activeFilter); } catch (e) {}
        renderFilters();
        load();
      });
      bar.appendChild(b);
    });
    var refresh = document.createElement('button');
    refresh.className = 'as-chip';
    refresh.type = 'button';
    refresh.textContent = '↻ Fetch now';
    refresh.style.marginLeft = 'auto';
    refresh.addEventListener('click', refreshNow);
    bar.appendChild(refresh);
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function rowFor(item, idx) {
    var row = document.createElement('article');
    row.className = 'as-row';
    row.style.animationDelay = Math.min(idx * 45, 420) + 'ms';

    var eyebrow = '<div class="as-eyebrow">'
      + '<span class="as-tag' + (item.tier === 'A' ? ' as-tierA' : '') + '">'
      + esc(item.category_label || 'Filing') + '</span>'
      + '<span>' + esc(item.exchange || '') + '</span>'
      + '<span>' + esc(item.time_ist || '') + '</span>'
      + (item.status && item.status !== 'pending' ? '<span>' + esc(item.status) + '</span>' : '')
      + '</div>';

    var r = item.restated || {};
    var figs = r.figures ? '<div class="as-figs">' + esc(r.figures) + '</div>' : '';
    var src = item.pdf
      ? '<div class="as-src">Filing: <a href="' + esc(item.pdf) + '" target="_blank" rel="noopener">open the PDF</a></div>'
      : '<div class="as-src">' + esc(item.company || '') + '</div>';

    row.innerHTML = eyebrow
      + '<p class="as-body">' + esc(r.body || item.headline || '') + '</p>'
      + figs
      + '<textarea class="as-post" spellcheck="false" aria-label="Post text">' + esc(item.x_post || '') + '</textarea>'
      + '<div class="as-acts">'
      + '  <button class="as-btn" data-act="copy">Copy for X</button>'
      + '  <button class="as-btn ghost" data-act="approve">Mark posted</button>'
      + '  <button class="as-btn ghost" data-act="skip">Skip</button>'
      + '  <span class="as-count"></span>'
      + '</div>'
      + src;

    var ta = row.querySelector('.as-post');
    var counter = row.querySelector('.as-count');
    function tick() {
      var n = ta.value.length;
      counter.textContent = n + '/280';
      counter.classList.toggle('over', n > 280);
    }
    ta.addEventListener('input', tick);
    tick();

    row.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.getAttribute('data-act');
      if (act === 'copy') {
        copyText(ta.value);
      } else if (act === 'approve') {
        send('/social/approve', { id: item.id, x_post: ta.value }, 'Marked posted');
        row.style.opacity = '.45';
      } else if (act === 'skip') {
        send('/social/skip', { id: item.id }, 'Skipped');
        row.style.opacity = '.35';
      }
    });
    return row;
  }

  function copyText(text) {
    function fallback() {
      var t = document.createElement('textarea');
      t.value = text;
      t.style.position = 'fixed';
      t.style.opacity = '0';
      document.body.appendChild(t);
      t.select();
      try { document.execCommand('copy'); toast('Copied — paste into X'); }
      catch (e) { toast('Select the text and copy manually'); }
      document.body.removeChild(t);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast('Copied — paste into X');
      }, fallback);
    } else { fallback(); }
  }

  function needKey() {
    var k = adminKey();
    if (k) return k;
    k = window.prompt('Admin key (stored in this browser only):') || '';
    if (k) setAdminKey(k);
    return k;
  }

  function send(path, body, okMsg) {
    var k = needKey();
    if (!k) { toast('Admin key needed for that'); return; }
    fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Key': k },
      body: JSON.stringify(body),
    }).then(function (r) {
      if (r.status === 401) { setAdminKey(''); toast('Admin key rejected'); return; }
      if (!r.ok) { toast('Server said ' + r.status); return; }
      toast(okMsg);
    }).catch(function () { toast('Could not reach the server'); });
  }

  function refreshNow() {
    var k = needKey();
    if (!k) { toast('Admin key needed to fetch'); return; }
    statusEl.textContent = 'fetching';
    fetch(API + '/social/refresh', { method: 'POST', headers: { 'X-Admin-Key': k } })
      .then(function (r) { return r.json(); })
      .then(function (d) { toast((d.added || 0) + ' new'); load(); })
      .catch(function () { statusEl.textContent = 'fetch failed'; });
  }

  function load() {
    listEl.innerHTML = '<div class="as-skel"></div><div class="as-skel"></div><div class="as-skel"></div>';
    var q = '?limit=60' + (activeFilter !== 'all' ? '&category=' + encodeURIComponent(activeFilter) : '');
    fetch(API + '/social/feed' + q)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var items = (d && d.items) || [];
        listEl.innerHTML = '';
        statusEl.textContent = items.length + ' held · ' + (d.posting_mode || 'draft') + ' mode';
        if (!items.length) {
          listEl.innerHTML = '<div class="as-empty">Nothing has cleared the filter yet. '
            + 'Press <strong>Fetch now</strong> to pull the latest filings from BSE and NSE. '
            + 'On a quiet afternoon an empty list is the correct answer.</div>';
          return;
        }
        items.forEach(function (it, i) { listEl.appendChild(rowFor(it, i)); });
      })
      .catch(function () {
        listEl.innerHTML = '<div class="as-empty">Could not reach the announcements service. '
          + 'If the backend has been idle it may still be starting — give it about thirty seconds and try again.</div>';
        statusEl.textContent = 'offline';
      });
  }

  function open() {
    injectCSS();
    if (!panel) { buildPanel(); }
    renderFilters();
    panel.classList.add('open');
    document.body.style.overflow = 'hidden';
    load();
  }
  function close() {
    panel.classList.remove('open');
    document.body.style.overflow = '';
  }

  /* ---------- nav entry ------------------------------------------------ */
  function addNavEntry() {
    var host = document.querySelector('nav') || document.querySelector('[class*="nav"]');
    var sibling = host && host.querySelector('a, button');
    if (sibling) {
      var el = sibling.cloneNode(true);
      el.textContent = 'Social';
      el.removeAttribute('href');
      el.id = 'altaha-social-open';
      el.setAttribute('role', 'button');
      el.setAttribute('tabindex', '0');
      el.style.cursor = 'pointer';
      el.addEventListener('click', function (e) { e.preventDefault(); open(); });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
      sibling.parentNode.appendChild(el);
      return true;
    }
    return false;
  }

  function addFallbackButton() {
    var b = document.createElement('button');
    b.id = 'altaha-social-open';
    b.type = 'button';
    b.textContent = 'Social';
    b.style.cssText = 'position:fixed;right:16px;bottom:76px;z-index:9700;'
      + 'font-family:var(--mono,monospace);font-size:11px;letter-spacing:.08em;'
      + 'text-transform:uppercase;padding:9px 15px;border-radius:999px;cursor:pointer;'
      + 'border:1px solid var(--gold-line,#B08D2E);background:var(--paper,#F6F2E9);'
      + 'color:var(--ink,#1A1712);box-shadow:0 2px 10px rgba(0,0,0,.1)';
    b.addEventListener('click', open);
    document.body.appendChild(b);
  }

  function boot() {
    injectCSS();
    if (!addNavEntry()) addFallbackButton();
    if (location.hash === '#social') open();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.AltahaSocial = { open: open, close: close, reload: load };
})();
