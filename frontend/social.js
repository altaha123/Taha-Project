/* ===========================================================================
   cards.js — Instagram card renderer.

   Pure Canvas 2D. No html2canvas, no SVG-to-image, no server rendering.

   Why not SVG. The obvious approach is to build an <svg>, load it into an
   <img>, and drawImage it. It silently loses every custom font: an SVG loaded
   through an img tag cannot reach the page's fonts, so Instrument Serif comes
   out as Times and the whole identity evaporates. There is no error. You just
   get an ugly card.

   Why not server-side. Rendering PNGs on the 512 MB Render instance means
   Pillow plus font files plus memory per request, on a box already running a
   scanner and two pollers. The browser has the fonts loaded and an idle GPU.

   So: draw directly on a canvas at 1080 wide, export with toBlob. The only
   real cost is that everything — word wrap, fitting, alignment — is manual.
   That is what most of this file is.

   Exposes window.AltahaCards = { render, download, FORMATS }.
   =========================================================================== */
(function (global) {
  'use strict';

  var FORMATS = {
    portrait: { w: 1080, h: 1350, label: 'Feed 4:5' },
    square:   { w: 1080, h: 1080, label: 'Square' },
    story:    { w: 1080, h: 1920, label: 'Story' }
  };

  /* Ledger palette. Hard-coded rather than read from CSS variables: an
     exported PNG must look the same whoever generates it, and must not flip
     when the site is in dark mode. */
  var LIGHT = {
    paper: '#F6F2E9', ink: '#1A1712', mute: '#726B5D',
    gold: '#8A6D1E', goldLine: '#B08D2E', rule: 'rgba(120,110,90,0.28)'
  };
  var DARK = {
    paper: '#16150F', ink: '#F2EDE1', mute: '#8A919F',
    gold: '#C9A63E', goldLine: '#B08D2E', rule: 'rgba(200,190,160,0.22)'
  };

  var SERIF = '"Instrument Serif", Georgia, serif';
  var MONO  = '"IBM Plex Mono", ui-monospace, monospace';
  var SANS  = '"Inter", system-ui, sans-serif';

  function font(size, family, weight) {
    return (weight ? weight + ' ' : '') + Math.round(size) + 'px ' + family;
  }

  /* ---- text measurement and wrapping ---------------------------------- */

  function wrap(ctx, text, maxWidth) {
    var words = String(text || '').split(/\s+/).filter(Boolean);
    var lines = [], line = '';
    for (var i = 0; i < words.length; i++) {
      var probe = line ? line + ' ' + words[i] : words[i];
      if (ctx.measureText(probe).width > maxWidth && line) {
        lines.push(line);
        line = words[i];
      } else {
        line = probe;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  /* Shrink until the block fits the space it has been given. A filing
     restatement can be one clause or four; a fixed size would either clip the
     long ones or make the short ones look lost. */
  function fitText(ctx, text, opts) {
    var size = opts.max;
    while (size >= opts.min) {
      ctx.font = font(size, opts.family, opts.weight);
      var lines = wrap(ctx, text, opts.width);
      var lh = size * (opts.lineHeight || 1.28);
      if (lines.length * lh <= opts.height) {
        return { size: size, lines: lines, lineHeight: lh, height: lines.length * lh };
      }
      size -= 2;
    }
    ctx.font = font(opts.min, opts.family, opts.weight);
    var l = wrap(ctx, text, opts.width);
    var lhm = opts.min * (opts.lineHeight || 1.28);
    var maxLines = Math.max(1, Math.floor(opts.height / lhm));
    if (l.length > maxLines) {
      l = l.slice(0, maxLines);
      l[maxLines - 1] = l[maxLines - 1].replace(/[\s,.;:]+$/, '') + '…';
    }
    return { size: opts.min, lines: l, lineHeight: lhm, height: l.length * lhm };
  }

  function drawLines(ctx, block, x, y, color) {
    ctx.fillStyle = color;
    ctx.font = font(block.size, block._family, block._weight);
    for (var i = 0; i < block.lines.length; i++) {
      ctx.fillText(block.lines[i], x, y + block.lineHeight * (i + 0.78));
    }
    return y + block.height;
  }

  function measured(ctx, text, opts) {
    var b = fitText(ctx, text, opts);
    b._family = opts.family; b._weight = opts.weight;
    return b;
  }

  /* ---- chrome --------------------------------------------------------- */

  function drawEyebrow(ctx, parts, x, y, P, size) {
    ctx.font = font(size, MONO, '500');
    ctx.textBaseline = 'alphabetic';
    var cx = x;
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (!p || !p.text) continue;
      ctx.fillStyle = p.gold ? P.gold : P.mute;
      var t = String(p.text).toUpperCase();
      ctx.fillText(t, cx, y);
      var w = ctx.measureText(t).width;
      if (p.gold) {
        ctx.fillStyle = P.goldLine;
        ctx.fillRect(cx, y + size * 0.34, w, 2);
      }
      cx += w;
      if (i < parts.length - 1) {
        ctx.fillStyle = P.mute;
        ctx.fillText('  ·  ', cx, y);
        cx += ctx.measureText('  ·  ').width;
      }
    }
  }

  function drawRule(ctx, x, y, w, P) {
    ctx.fillStyle = P.rule;
    ctx.fillRect(x, y, w, 1);
  }

  /* The one deliberate flourish: a gold arc in the corner, echoing the
     --gold-line stroke role from the design system. Strokes and arcs only,
     never text — that is what the token is for. */
  function drawMark(ctx, W, H, P, pad) {
    ctx.save();
    ctx.strokeStyle = P.goldLine;
    ctx.lineWidth = 2;
    ctx.globalAlpha = 0.42;
    ctx.beginPath();
    ctx.arc(W + 40, -40, 250, Math.PI * 0.5, Math.PI * 1.0);
    ctx.stroke();
    ctx.globalAlpha = 0.18;
    ctx.beginPath();
    ctx.arc(W + 40, -40, 320, Math.PI * 0.5, Math.PI * 1.0);
    ctx.stroke();
    ctx.restore();
  }

  function drawFooter(ctx, W, H, P, pad, handle) {
    var fy = H - pad;
    drawRule(ctx, pad, fy - 74, W - pad * 2, P);
    ctx.font = font(25, MONO, '500');
    ctx.fillStyle = P.mute;
    ctx.textAlign = 'left';
    ctx.fillText(handle || '@altaha.screener', pad, fy - 26);
    ctx.textAlign = 'right';
    ctx.font = font(22, MONO, '400');
    ctx.fillText('NOT INVESTMENT ADVICE', W - pad, fy - 26);
    ctx.textAlign = 'left';
  }

  /* ---- filing card ---------------------------------------------------- */

  function renderFiling(ctx, item, F, P, opts) {
    var W = F.w, H = F.h, pad = 88;
    var inner = W - pad * 2;
    var r = item.restated || {};

    ctx.fillStyle = P.paper;
    ctx.fillRect(0, 0, W, H);
    drawMark(ctx, W, H, P, pad);

    var y = pad + 34;
    drawEyebrow(ctx, [
      { text: item.category_label || 'Filing', gold: true },
      { text: item.exchange || 'BSE' },
      { text: item.time_ist || '' }
    ], pad, y, P, 24);

    y += 62;

    // Ticker, the largest thing on the card. It is what someone scrolling sees.
    var ticker = item.symbol || '';
    if (ticker) {
      ctx.font = font(104, SERIF, '400');
      ctx.fillStyle = P.ink;
      ctx.fillText(ticker, pad, y + 82);
      y += 110;
    }

    // Company name, quiet, under the ticker.
    var nameBlock = measured(ctx, item.company || '', {
      family: SANS, weight: '400', min: 26, max: 32,
      width: inner, height: 84, lineHeight: 1.3
    });
    y = drawLines(ctx, nameBlock, pad, y, P.mute) + 40;

    drawRule(ctx, pad, y, inner, P);
    y += 54;

    // The restatement, optically centred between the rule and the source line.
    var regionTop = y;
    var regionBottom = H - pad - 150;
    var figs = (r.figures || '').trim();
    var figsHeight = figs ? 96 : 0;
    var regionHeight = regionBottom - regionTop - figsHeight;

    var body = measured(ctx, r.body || item.headline || '', {
      family: SERIF, weight: '400', min: 38, max: 78,
      width: inner, height: regionHeight, lineHeight: 1.22
    });

    var contentHeight = body.height + figsHeight;
    y = regionTop + Math.max(0, (regionBottom - regionTop - contentHeight) / 2);
    y = drawLines(ctx, body, pad, y, P.ink);

    if (figs) {
      y += 58;
      ctx.font = font(34, MONO, '500');
      ctx.fillStyle = P.goldLine;
      ctx.fillRect(pad, y - 34, 3, 46);
      ctx.fillStyle = P.gold;
      ctx.fillText(figs, pad + 24, y);
    }

    // Source line sits on the footer rule, not floating after the body.
    ctx.font = font(23, MONO, '400');
    ctx.fillStyle = P.mute;
    var src = 'SOURCE: ' + (item.exchange || 'BSE') + ' FILING' +
              (item.pdf ? ' · PDF LINKED IN BIO' : '');
    ctx.fillText(src, pad, H - pad - 108);

    drawFooter(ctx, W, H, P, pad, opts.handle);
  }

  /* ---- news card ------------------------------------------------------ */

  function renderNews(ctx, c, F, P, opts) {
    var W = F.w, H = F.h, pad = 88;
    var inner = W - pad * 2;
    var lead = c.lead || {};

    ctx.fillStyle = P.paper;
    ctx.fillRect(0, 0, W, H);
    drawMark(ctx, W, H, P, pad);

    var y = pad + 34;
    drawEyebrow(ctx, [
      { text: (c.themes && c.themes[0]) || 'Markets', gold: true },
      { text: lead.when_ist || '' }
    ], pad, y, P, 24);

    y += 74;

    /* The corroboration count, given real estate. It is the only thing on this
       card that is mine rather than the publication's, so it gets the number
       treatment: big figure, small label. */
    var n = c.corroboration || 1;
    ctx.font = font(150, SERIF, '400');
    ctx.fillStyle = n >= 3 ? P.gold : P.mute;
    ctx.fillText(String(n), pad, y + 118);
    var nw = ctx.measureText(String(n)).width;
    ctx.font = font(30, MONO, '500');
    ctx.fillStyle = P.mute;
    ctx.fillText(n === 1 ? 'OUTLET' : 'OUTLETS', pad + nw + 28, y + 76);
    ctx.font = font(24, MONO, '400');
    ctx.fillText(n >= 3 ? 'CARRYING THIS' : (c.speculative ? 'UNCONFIRMED' : 'SO FAR'),
                 pad + nw + 28, y + 112);
    y += 170;

    drawRule(ctx, pad, y, inner, P);
    y += 58;

    // Centre the whole block — headline, attribution and the "also carried by"
    // line together. Centring only the headline reserved the trailing space
    // twice and left a third of the card empty.
    var sourceTop = H - pad - 170;
    var alsoText = (c.publications && c.publications.length > 1)
      ? 'Also carried by ' + c.publications.slice(1).join(', ') + '.' : '';

    var head = measured(ctx, '\u201C' + (lead.title || '') + '\u201D', {
      family: SERIF, weight: '400', min: 40, max: 76,
      width: inner, height: sourceTop - y - 120, lineHeight: 1.2
    });

    var alsoBlock = null;
    if (alsoText) {
      alsoBlock = measured(ctx, alsoText, {
        family: SANS, weight: '400', min: 20, max: 24,
        width: inner, height: 80, lineHeight: 1.35
      });
    }

    var attribGap = 52, attribH = 30;
    var total = head.height + attribGap + attribH + (alsoBlock ? 16 + alsoBlock.height : 0);
    y = y + Math.max(0, (sourceTop - y - total) / 2);

    y = drawLines(ctx, head, pad, y, P.ink);

    y += attribGap;
    ctx.font = font(28, SANS, '400');
    ctx.fillStyle = P.mute;
    ctx.fillText('\u2014 ' + (lead.publication || ''), pad, y);

    if (alsoBlock) {
      y += 16;
      drawLines(ctx, alsoBlock, pad, y, P.mute);
    }

    ctx.font = font(23, MONO, '400');
    ctx.fillStyle = P.mute;
    ctx.fillText('HEADLINE AS PUBLISHED · LINK IN BIO', pad, H - pad - 108);

    drawFooter(ctx, W, H, P, pad, opts.handle);
  }

  /* ---- daily wrap ----------------------------------------------------- */

  function renderWrap(ctx, data, F, P, opts) {
    var W = F.w, H = F.h, pad = 88;
    var inner = W - pad * 2;

    ctx.fillStyle = P.paper;
    ctx.fillRect(0, 0, W, H);
    drawMark(ctx, W, H, P, pad);

    var y = pad + 34;
    drawEyebrow(ctx, [{ text: 'Daily wrap', gold: true }, { text: data.date || '' }], pad, y, P, 24);

    y += 84;
    ctx.font = font(88, SERIF, '400');
    ctx.fillStyle = P.ink;
    ctx.fillText('Today’s filings', pad, y + 68);
    y += 128;

    drawRule(ctx, pad, y, inner, P);
    y += 30;

    var rows = data.rows || [];
    for (var i = 0; i < rows.length && i < 7; i++) {
      var rowY = y + 92;
      ctx.font = font(58, SERIF, '400');
      ctx.fillStyle = P.gold;
      var num = String(rows[i].count);
      ctx.fillText(num, pad, rowY);
      ctx.font = font(31, SANS, '400');
      ctx.fillStyle = P.ink;
      ctx.fillText(rows[i].label, pad + Math.max(ctx.measureText(num).width, 78) + 34, rowY - 4);
      y += 104;
      drawRule(ctx, pad, y, inner, P);
    }

    if (data.note) {
      var noteBlock = measured(ctx, data.note, {
        family: SANS, weight: '400', min: 24, max: 30,
        width: inner, height: 120, lineHeight: 1.4
      });
      drawLines(ctx, noteBlock, pad, H - pad - 250, P.mute);
    }

    drawFooter(ctx, W, H, P, pad, opts.handle);
  }

  /* ---- public --------------------------------------------------------- */

  function render(canvas, kind, data, options) {
    var opts = options || {};
    var F = FORMATS[opts.format || 'portrait'] || FORMATS.portrait;
    var P = opts.theme === 'dark' ? DARK : LIGHT;

    canvas.width = F.w;
    canvas.height = F.h;
    var ctx = canvas.getContext('2d');
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';

    if (kind === 'news') renderNews(ctx, data, F, P, opts);
    else if (kind === 'wrap') renderWrap(ctx, data, F, P, opts);
    else renderFiling(ctx, data, F, P, opts);

    return canvas;
  }

  function download(canvas, filename) {
    return new Promise(function (resolve, reject) {
      if (!canvas.toBlob) { reject(new Error('canvas export unsupported')); return; }
      canvas.toBlob(function (blob) {
        if (!blob) { reject(new Error('export failed')); return; }
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename || 'altaha.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
        resolve(blob);
      }, 'image/png');
    });
  }

  global.AltahaCards = { render: render, download: download, FORMATS: FORMATS,
                         _wrap: wrap, _fitText: fitText };

})(typeof window !== 'undefined' ? window : globalThis);


/* ===========================================================================
   social.js — the Social surface for Altaha Screener
   ---------------------------------------------------------------------------
   Same pattern as nav.js and scoring.js: a wrapper layer. It does not rewrite
   index.html, it does not touch the analysis page, and it injects its own CSS
   built entirely from the page's existing Ledger tokens.

   v2 adds the News tab. This file REPLACES the v1 from Update 5 — it is not a
   layer on top of it. The design audit already flagged five script layers
   patching one page as the reason F-03 regressed on its own; a sixth would be
   worse. One <script> line in index.html and this file is the whole feature.

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
    background:var(--paper-2,#F4F1EB);overflow-y:auto;-webkit-overflow-scrolling:touch}
  #altaha-social-panel.open{display:block}
  .as-wrap{max-width:940px;margin:0 auto;padding:0 0 120px;background:var(--paper,#FBFAF7);min-height:100vh;border-left:1px solid var(--rule-2,#EBE6DC);border-right:1px solid var(--rule-2,#EBE6DC)}
  .as-pad{padding:0 40px}
  @media(max-width:620px){.as-pad{padding:0 18px}}
  .as-top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
    border-bottom:1px solid var(--gold,#B08D2E);padding-bottom:12px;margin-bottom:6px}
  .as-title{font-family:var(--serif,'Instrument Serif',Georgia,serif);
    font-size:clamp(26px,5vw,34px);line-height:1.05;color:var(--ink,#16130E);margin:0}
  .as-sub{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;
    letter-spacing:.08em;text-transform:uppercase;color:var(--mute,#8B8477)}
  .as-close{margin-left:auto;background:none;border:1px solid var(--mute,#8B8477);
    color:var(--ink,#16130E);border-radius:999px;width:34px;height:34px;font-size:17px;
    cursor:pointer;line-height:1;transition:background var(--t-fast,150ms) var(--ease,ease)}
  .as-close:hover{background:rgba(0,0,0,.05)}
  .as-close:focus-visible{outline:2px solid var(--gold,#B08D2E);outline-offset:2px}

  .as-note{font-size:12.5px;line-height:1.55;color:var(--mute,#8B8477);
    margin:12px 0 16px;padding:10px 12px;border-left:2px solid var(--gold,#B08D2E)}

  .as-tabs{display:flex;gap:0;margin:14px 0 4px;border-bottom:1px solid var(--rule,#DDD6C9)}
  .as-tab{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11.5px;letter-spacing:.09em;
    text-transform:uppercase;padding:9px 16px;background:none;border:none;cursor:pointer;
    color:var(--mute,#8B8477);border-bottom:2px solid transparent;margin-bottom:-1px;
    transition:color var(--t-fast,150ms) var(--ease,ease)}
  .as-tab[aria-selected="true"]{color:var(--ink,#16130E);border-bottom-color:var(--gold,#B08D2E)}
  .as-tab:focus-visible{outline:2px solid var(--gold,#B08D2E);outline-offset:-2px}

  .as-corro{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;
    letter-spacing:.06em;padding:2px 8px;border-radius:999px;
    border:1px solid var(--gold,#B08D2E);color:var(--gold-dp,#8A6D1E)}
  .as-corro.solo{border-color:var(--mute,#8B8477);color:var(--mute,#8B8477)}
  .as-spec{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;
    letter-spacing:.06em;color:#9A5B00;text-transform:uppercase}
  .as-also{font-size:12px;color:var(--mute,#8B8477);line-height:1.5;margin:6px 0 2px}
  .as-also a{color:var(--mute,#8B8477)}
  .as-headline{font-size:16px;line-height:1.45;color:var(--ink,#16130E);margin:0 0 6px}
  .as-headline a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule,#DDD6C9)}
  .as-headline a:hover{border-bottom-color:var(--gold,#B08D2E)}

  .as-bar{display:flex;gap:12px;align-items:center;padding:14px 0 4px}
  .as-chips{display:flex;gap:7px;overflow-x:auto;flex:1 1 auto;padding-bottom:6px;scrollbar-width:none;-ms-overflow-style:none}
  .as-chips::-webkit-scrollbar{display:none}
  .as-fetch{flex:0 0 auto}
  .as-chip{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;
    letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;flex:0 0 auto;padding:6px 12px;border-radius:999px;cursor:pointer;
    border:1px solid var(--mute,#8B8477);background:transparent;color:var(--mute,#8B8477);
    transition:all var(--t-fast,150ms) var(--ease,ease)}
  .as-chip[aria-pressed="true"]{background:var(--ink,#16130E);color:var(--paper,#FBFAF7);
    border-color:var(--ink,#16130E)}
  .as-chip:focus-visible{outline:2px solid var(--gold,#B08D2E);outline-offset:2px}

  .as-row{border-bottom:1px solid var(--rule-2,#EBE6DC);padding:24px 0;
    opacity:0;transform:translateY(8px);
    animation:asArrive var(--t-slow,460ms) var(--ease-soft,cubic-bezier(.16,1,.3,1)) forwards}
  @keyframes asArrive{to{opacity:1;transform:none}}
  @media (prefers-reduced-motion:reduce){.as-row{animation:none;opacity:1;transform:none}}

  .as-eyebrow{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;
    letter-spacing:.1em;text-transform:uppercase;color:var(--mute,#8B8477);margin-bottom:7px}
  .as-tag{color:var(--gold-dp,#8A6D1E);border-bottom:1px solid var(--gold,#B08D2E);padding-bottom:1px}
  .as-dot{width:4px;height:4px;border-radius:50%;background:var(--gold,#B08D2E);flex:0 0 auto}
  .as-pill{border:1px solid var(--rule,#DDD6C9);border-radius:999px;padding:2px 8px}
  .as-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:10px}
  .as-tick{font-family:var(--serif,'Instrument Serif',Georgia,serif);font-size:30px;line-height:1;color:var(--ink,#16130E)}
  .as-co{font-size:13px;color:var(--mute,#8B8477)}
  .as-hold{display:inline-block;font-family:var(--mono,monospace);font-size:11px;color:var(--part,#9A7B1F);border:1px dashed var(--gold-lt,#D9BC6A);border-radius:4px;padding:5px 10px;margin-bottom:12px}
  .as-edit{margin-top:12px}
  .as-edit[hidden]{display:none}
  .as-btn.quiet{background:transparent;border-color:transparent;color:var(--mute,#8B8477);padding:8px 6px}
  .as-body{font-size:16px;line-height:1.5;color:var(--ink,#16130E);margin:0 0 8px}
  .as-figs{display:inline-block;font-family:var(--mono,'IBM Plex Mono',monospace);font-size:12.5px;
    color:var(--gold-dp,#8A6D1E);border:1px solid var(--gold-lt,#D9BC6A);border-radius:999px;
    padding:4px 11px;margin-bottom:12px}

  .as-post{width:100%;box-sizing:border-box;min-height:112px;resize:vertical;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:12.5px;line-height:1.55;
    color:var(--ink,#16130E);background:rgba(0,0,0,.025);
    border:1px solid var(--rule,#DDD6C9);border-radius:4px;padding:10px 11px}
  .as-post:focus{outline:none;border-color:var(--gold,#B08D2E)}

  .as-acts{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
  .as-btn{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;letter-spacing:.06em;
    text-transform:uppercase;padding:7px 14px;border-radius:3px;cursor:pointer;
    border:1px solid var(--ink,#16130E);background:var(--ink,#16130E);color:var(--paper,#FBFAF7);
    transition:opacity var(--t-fast,150ms) var(--ease,ease)}
  .as-btn.ghost{background:transparent;color:var(--mute,#8B8477);border-color:var(--mute,#8B8477)}
  .as-btn:hover{opacity:.82}
  .as-btn:focus-visible{outline:2px solid var(--gold,#B08D2E);outline-offset:2px}
  .as-count{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;
    color:var(--mute,#8B8477);margin-left:auto}
  .as-count.over{color:#B3261E}
  .as-src{font-size:11.5px;color:var(--mute,#8B8477);margin-top:7px}
  .as-src a{color:var(--gold-dp,#8A6D1E)}

  .as-shot{margin-top:12px;border:1px solid var(--rule,#DDD6C9);border-radius:4px;
    padding:12px;background:rgba(0,0,0,.02)}
  .as-shot[hidden]{display:none}
  .as-shot-opts{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
  .as-opt{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10.5px;letter-spacing:.05em;
    text-transform:uppercase;padding:4px 10px;border-radius:999px;cursor:pointer;
    border:1px solid var(--mute,#8B8477);background:transparent;color:var(--mute,#8B8477)}
  .as-opt[aria-pressed="true"]{background:var(--ink,#16130E);color:var(--paper,#FBFAF7);
    border-color:var(--ink,#16130E)}
  .as-opt:focus-visible{outline:2px solid var(--gold,#B08D2E);outline-offset:2px}
  .as-canvas{display:block;width:100%;max-width:270px;height:auto;margin:0 auto 10px;
    border:1px solid var(--rule,#DDD6C9);border-radius:2px}
  .as-cap{width:100%;box-sizing:border-box;min-height:130px;resize:vertical;
    font-family:var(--sans,'Inter',system-ui,sans-serif);font-size:12.5px;line-height:1.5;
    color:var(--ink,#16130E);background:transparent;border:1px solid var(--rule,#DDD6C9);
    border-radius:4px;padding:9px 10px;margin-bottom:8px}
  .as-cap:focus{outline:none;border-color:var(--gold,#B08D2E)}

  .as-skel{height:74px;border-radius:4px;margin:14px 0;
    background:linear-gradient(90deg,rgba(0,0,0,.04) 25%,rgba(0,0,0,.08) 37%,rgba(0,0,0,.04) 63%);
    background-size:400% 100%;animation:asSkel 1.4s ease-in-out infinite}
  @keyframes asSkel{0%{background-position:100% 0}100%{background-position:0 0}}
  .as-empty{padding:56px 0 40px;max-width:52ch;color:var(--mute,#8B8477);font-size:14px;line-height:1.6}
  .as-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:9900;
    background:var(--ink,#16130E);color:var(--paper,#FBFAF7);padding:9px 16px;border-radius:999px;
    font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11.5px;letter-spacing:.05em;
    opacity:0;transition:opacity var(--t,280ms) var(--ease,ease);pointer-events:none}
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
      + '<div class="as-wrap"><div class="as-pad">'
      + '  <div class="as-top">'
      + '    <h2 class="as-title">Social</h2>'
      + '    <span class="as-sub" id="as-status">loading</span>'
      + '    <button class="as-close" id="as-close" aria-label="Close Social">&times;</button>'
      + '  </div>'
      + '  <p class="as-note">Plain restatements of what companies filed with BSE and NSE today. '
      + '  No view, no target, no recommendation — that stays out until the RA registration is in hand. '
      + '  Read the filing before you post anything.</p>'
      + '  <div class="as-tabs" role="tablist">'
      + '    <button class="as-tab" id="as-tab-filings" role="tab">Filings</button>'
      + '    <button class="as-tab" id="as-tab-news" role="tab">News</button>'
      + '  </div>'
      + '  <div class="as-bar"><div class="as-chips" id="as-filters"></div>'
      + '    <button class="as-chip as-fetch" id="as-fetch" type="button">\u21BB Fetch now</button></div>'
      + '  <div id="as-list"><div class="as-skel"></div><div class="as-skel"></div><div class="as-skel"></div></div>'
      + '</div></div>';
    document.body.appendChild(panel);
    listEl = panel.querySelector('#as-list');
    statusEl = panel.querySelector('#as-status');
    panel.querySelector('#as-close').addEventListener('click', close);
    panel.querySelector('#as-fetch').addEventListener('click', refreshNow);
    panel.querySelector('#as-tab-filings').addEventListener('click', function () { setTab('filings'); });
    panel.querySelector('#as-tab-news').addEventListener('click', function () { setTab('news'); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('open')) close();
    });
  }

  var TAB_STORE = 'altaha-social-tab';
  var activeTab = 'filings';
  try { activeTab = localStorage.getItem(TAB_STORE) || 'filings'; } catch (e) {}

  function setTab(tab) {
    activeTab = tab;
    try { localStorage.setItem(TAB_STORE, tab); } catch (e) {}
    panel.querySelector('#as-tab-filings').setAttribute('aria-selected', String(tab === 'filings'));
    panel.querySelector('#as-tab-news').setAttribute('aria-selected', String(tab === 'news'));
    activeFilter = 'all';
    renderFilters();
    load();
  }

  var NEWS_FILTERS = [
    ['all', 'All'], ['Policy', 'Policy'], ['Macro', 'Macro'], ['Flows', 'Flows'],
    ['Currency & commodities', 'FX & commodities'], ['Global', 'Global'],
    ['Sector policy', 'Sector policy'], ['Primary market', 'IPO'], ['Corporate', 'Corporate'],
  ];

  var FILTERS = [
    ['all', 'All'], ['order_win', 'Orders'], ['ma', 'M&A'], ['fundraise', 'Fundraise'],
    ['credit_rating', 'Ratings'], ['pledge', 'Pledge'], ['board_change', 'Leadership'],
    ['capex', 'Capex'], ['regulatory', 'Regulatory'], ['results', 'Results'],
  ];

  function renderFilters() {
    var bar = panel.querySelector('#as-filters');
    bar.innerHTML = '';
    (activeTab === 'news' ? NEWS_FILTERS : FILTERS).forEach(function (f) {
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
    row.style.animationDelay = Math.min(idx * 40, 400) + 'ms';

    var r = item.restated || {};
    var held = item.evidence_ok === false;

    var eyebrow = '<div class="as-eyebrow">'
      + '<span class="as-tag">' + esc(item.category_label || 'Filing') + '</span>'
      + (item.tier === 'A' && !held ? '<span class="as-dot"></span>' : '')
      + '<span>' + esc(item.exchange || 'BSE') + '</span>'
      + '<span>' + esc(item.time_ist || '') + '</span>'
      + (item.status && item.status !== 'pending' && !held
          ? '<span class="as-pill">' + esc(item.status) + '</span>' : '')
      + '</div>';

    var head = '<div class="as-head">'
      + (item.symbol ? '<span class="as-tick">' + esc(item.symbol) + '</span>' : '')
      + '<span class="as-co">' + esc(item.company || '') + '</span></div>';

    var badge = held
      ? '<div class="as-hold">Headline does not carry the facts \u2014 read the PDF before posting</div>'
      : (r.figures ? '<div class="as-figs">' + esc(r.figures) + '</div>' : '');

    var acts = held
      ? '<div class="as-acts">'
        + (item.pdf ? '<a class="as-btn ghost" href="' + esc(item.pdf) + '" target="_blank" rel="noopener">Open filing</a>' : '')
        + '<button class="as-btn quiet" data-act="skip">Dismiss</button></div>'
      : '<div class="as-acts">'
        + '<button class="as-btn" data-act="copy">Copy for X</button>'
        + '<button class="as-btn ghost" data-act="image">Instagram</button>'
        + '<button class="as-btn quiet" data-act="edit">Edit post</button>'
        + '<button class="as-btn quiet" data-act="approve">Posted</button>'
        + '<button class="as-btn quiet" data-act="skip">Skip</button>'
        + '<span class="as-count"></span></div>';

    var edit = held ? '' : '<div class="as-edit" hidden>'
      + '<textarea class="as-post" spellcheck="false" aria-label="Post text">'
      + esc(item.x_post || '') + '</textarea></div>';

    var src = (item.pdf && !held)
      ? '<div class="as-src"><a href="' + esc(item.pdf) + '" target="_blank" rel="noopener">Open the filing</a></div>' : '';

    row.innerHTML = eyebrow + head
      + '<p class="as-body">' + esc(r.body || item.headline || '') + '</p>'
      + badge + acts + edit + src;

    var composer = null;
    var ta = row.querySelector('.as-post');
    var counter = row.querySelector('.as-count');
    function tick() {
      if (!ta || !counter) return;
      var n = ta.value.length;
      counter.textContent = n + '/280';
      counter.classList.toggle('over', n > 280);
    }
    if (ta) { ta.addEventListener('input', tick); tick(); }

    row.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-act]');
      if (!btn) return;
      var act = btn.getAttribute('data-act');
      if (act === 'copy') {
        copyText(ta ? ta.value : (item.x_post || ''));
      } else if (act === 'edit') {
        var box = row.querySelector('.as-edit');
        box.hidden = !box.hidden;
        btn.textContent = box.hidden ? 'Edit post' : 'Hide post';
      } else if (act === 'image') {
        if (!composer) { composer = attachComposer(row, 'filing', item, item.symbol || item.company); }
        composer.box.hidden = !composer.box.hidden;
        btn.textContent = composer.box.hidden ? 'Instagram' : 'Hide image';
        if (!composer.box.hidden) composer.refresh();
      } else if (act === 'approve') {
        send('/social/approve', { id: item.id, x_post: ta ? ta.value : item.x_post }, 'Marked posted');
        row.style.opacity = '.45';
      } else if (act === 'skip') {
        send('/social/skip', { id: item.id }, 'Skipped');
        row.style.opacity = '.35';
      }
    });
    return row;
  }

  function newsRowFor(c, idx) {
    var lead = c.lead || {};
    var row = document.createElement('article');
    row.className = 'as-row';
    row.style.animationDelay = Math.min(idx * 45, 420) + 'ms';

    var corroClass = c.corroboration >= 3 ? 'as-corro' : 'as-corro solo';
    var corroText = c.corroboration === 1 ? '1 outlet' : c.corroboration + ' outlets';

    var eyebrow = '<div class="as-eyebrow">'
      + '<span class="as-tag">' + esc((c.themes && c.themes[0]) || 'Markets') + '</span>'
      + '<span>' + esc(lead.publication || '') + '</span>'
      + '<span>' + esc(lead.when_ist || '') + '</span>'
      + '<span class="' + corroClass + '">' + corroText + '</span>'
      + (c.speculative ? '<span class="as-spec">unconfirmed</span>' : '')
      + '</div>';

    var headline = lead.link
      ? '<p class="as-headline"><a href="' + esc(lead.link) + '" target="_blank" rel="noopener">'
        + esc(lead.title || '') + '</a></p>'
      : '<p class="as-headline">' + esc(lead.title || '') + '</p>';

    var also = '';
    if (c.members && c.members.length > 1) {
      also = '<div class="as-also">Also carried by ' + esc(
        c.publications.slice(1).join(', ')) + '.</div>';
    }
    var syms = (c.symbols || []).length
      ? '<div class="as-figs">' + esc(c.symbols.join(' · ')) + '</div>' : '';

    row.innerHTML = eyebrow + headline + also + syms
      + '<div class="as-acts">'
      + '  <button class="as-btn" data-act="copy">Copy for X</button>'
      + '  <button class="as-btn ghost" data-act="image">Instagram</button>'
      + '  <button class="as-btn quiet" data-act="edit">Edit post</button>'
      + '  <button class="as-btn quiet" data-act="skip">Skip</button>'
      + '  <span class="as-count"></span>'
      + '</div>'
      + '<div class="as-edit" hidden><textarea class="as-post" spellcheck="false" '
      + 'aria-label="Post text">' + esc(c.x_post || '') + '</textarea></div>';

    var composer = null;
    var ta = row.querySelector('.as-post');
    var counter = row.querySelector('.as-count');
    function tick() {
      // X counts every link as 23 characters however long it really is.
      var n = ta.value.length;
      if (lead.link && ta.value.indexOf(lead.link) !== -1) n -= (lead.link.length - 23);
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
      } else if (act === 'edit') {
        var box = row.querySelector('.as-edit');
        box.hidden = !box.hidden;
        btn.textContent = box.hidden ? 'Edit post' : 'Hide post';
      } else if (act === 'image') {
        if (!composer) { composer = attachComposer(row, 'news', c, (c.symbols || [])[0] || 'news'); }
        composer.box.hidden = !composer.box.hidden;
        btn.textContent = composer.box.hidden ? 'Instagram' : 'Hide image';
        if (!composer.box.hidden) composer.refresh();
      } else {
        send('/social/news/skip', { id: c.id }, 'Skipped');
        row.style.opacity = '.35';
      }
    });
    return row;
  }

  /* ---- Instagram composer ------------------------------------------- */
  var IG_PREFS = 'altaha-ig-prefs';
  function igPrefs() {
    try { return JSON.parse(localStorage.getItem(IG_PREFS)) || {}; } catch (e) { return {}; }
  }
  function saveIgPrefs(p) {
    try { localStorage.setItem(IG_PREFS, JSON.stringify(p)); } catch (e) {}
  }

  /* Instrument Serif and IBM Plex Mono must be loaded before the first draw.
     Canvas silently falls back to a default serif if they are not, and the
     card comes out looking like nothing — no error, just a wrong-looking PNG.
     document.fonts.ready is the only reliable gate. */
  var fontsReady = (document.fonts && document.fonts.ready)
    ? document.fonts.ready.catch(function () { return null; })
    : Promise.resolve(null);

  function attachComposer(row, kind, data, nameHint) {
    var box = document.createElement('div');
    box.className = 'as-shot';
    box.hidden = true;

    var prefs = igPrefs();
    var state = { format: prefs.format || 'portrait', theme: prefs.theme || 'light' };

    var opts = document.createElement('div');
    opts.className = 'as-shot-opts';
    [['portrait', 'Feed 4:5'], ['square', 'Square'], ['story', 'Story']].forEach(function (f) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'as-opt'; b.textContent = f[1];
      b.setAttribute('aria-pressed', String(state.format === f[0]));
      b.addEventListener('click', function () {
        state.format = f[0]; saveIgPrefs(state); refresh();
      });
      opts.appendChild(b);
    });
    var themeBtn = document.createElement('button');
    themeBtn.type = 'button'; themeBtn.className = 'as-opt';
    themeBtn.style.marginLeft = 'auto';
    opts.appendChild(themeBtn);
    themeBtn.addEventListener('click', function () {
      state.theme = state.theme === 'dark' ? 'light' : 'dark'; saveIgPrefs(state); refresh();
    });

    var canvas = document.createElement('canvas');
    canvas.className = 'as-canvas';

    var cap = document.createElement('textarea');
    cap.className = 'as-cap';
    cap.spellcheck = false;
    cap.setAttribute('aria-label', 'Instagram caption');
    cap.value = data.ig_caption || '';

    var acts = document.createElement('div');
    acts.className = 'as-acts';
    acts.innerHTML = '<button class="as-btn" data-ig="png">Download image</button>'
      + '<button class="as-btn ghost" data-ig="caption">Copy caption</button>';

    box.appendChild(opts); box.appendChild(canvas); box.appendChild(cap); box.appendChild(acts);

    function refresh() {
      [].forEach.call(opts.querySelectorAll('.as-opt'), function (b, i) {
        if (i < 3) b.setAttribute('aria-pressed',
          String(['portrait', 'square', 'story'][i] === state.format));
      });
      themeBtn.textContent = state.theme === 'dark' ? 'Dark' : 'Light';
      fontsReady.then(function () {
        try {
          window.AltahaCards.render(canvas, kind, data,
            { format: state.format, theme: state.theme, handle: prefs.handle });
        } catch (e) { toast('Could not draw the card'); }
      });
    }

    acts.addEventListener('click', function (e) {
      var b = e.target.closest('[data-ig]');
      if (!b) return;
      if (b.getAttribute('data-ig') === 'caption') { copyText(cap.value); return; }
      var name = 'altaha-' + (nameHint || 'card').toLowerCase().replace(/[^a-z0-9]+/g, '-')
        + '-' + state.format + '.png';
      window.AltahaCards.download(canvas, name).then(function () {
        toast('Saved — post it from your phone');
      }, function () { toast('Download failed'); });
    });

    row.appendChild(box);
    return { box: box, refresh: refresh };
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
    var path = activeTab === 'news' ? '/social/news/refresh' : '/social/refresh';
    fetch(API + path, { method: 'POST', headers: { 'X-Admin-Key': k } })
      .then(function (r) { return r.json(); })
      .then(function (d) { toast((d.added || 0) + ' new'); load(); })
      .catch(function () { statusEl.textContent = 'fetch failed'; });
  }

  function load() {
    if (activeTab === 'news') return loadNews();
    return loadFilings();
  }

  function loadFilings() {
    listEl.innerHTML = '<div class="as-skel"></div><div class="as-skel"></div><div class="as-skel"></div>';
    var q = '?limit=60' + (activeFilter !== 'all' ? '&category=' + encodeURIComponent(activeFilter) : '');
    fetch(API + '/social/feed' + q)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var items = (d && d.items) || [];
        listEl.innerHTML = '';
        statusEl.textContent = items.length + ' filings · ' + (d.posting_mode || 'draft') + ' mode';
        if (!items.length) {
          listEl.innerHTML = '<div class="as-empty">Nothing has cleared the filter yet. '
            + 'Press <strong>Fetch now</strong> to pull the latest filings from BSE and NSE. '
            + 'On a quiet afternoon an empty list is the correct answer.</div>';
          return;
        }
        items.forEach(function (it, i) { listEl.appendChild(rowFor(it, i)); });
      })
      .catch(offline);
  }

  function loadNews() {
    listEl.innerHTML = '<div class="as-skel"></div><div class="as-skel"></div><div class="as-skel"></div>';
    var q = '?limit=40' + (activeFilter !== 'all' ? '&theme=' + encodeURIComponent(activeFilter) : '');
    fetch(API + '/social/news/feed' + q)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var cs = (d && d.clusters) || [];
        listEl.innerHTML = '';
        var multi = cs.filter(function (c) { return c.corroboration >= 3; }).length;
        statusEl.textContent = cs.length + ' stories · ' + multi + ' in three or more outlets';
        if (!cs.length) {
          listEl.innerHTML = '<div class="as-empty">No stories have cleared the relevance filter yet. '
            + 'Press <strong>Fetch now</strong> to pull the feeds.</div>';
          return;
        }
        cs.forEach(function (c, i) { listEl.appendChild(newsRowFor(c, i)); });
      })
      .catch(offline);
  }

  function offline() {
    listEl.innerHTML = '<div class="as-empty">Could not reach the service. '
      + 'If the backend has been idle it may still be starting — give it about thirty seconds and try again.</div>';
    statusEl.textContent = 'offline';
  }

  function open() {
    injectCSS();
    if (!panel) { buildPanel(); }
    panel.querySelector('#as-tab-filings').setAttribute('aria-selected', String(activeTab === 'filings'));
    panel.querySelector('#as-tab-news').setAttribute('aria-selected', String(activeTab === 'news'));
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

  window.AltahaSocial = { open: open, close: close, reload: load, tab: setTab };
})();
