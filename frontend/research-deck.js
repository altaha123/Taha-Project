/* Altaha — the Research Deck (research-deck.html). The rules live in
   backend/research_deck.py; this file draws what the API returns, and for the
   owner, sends what they write.

   ADDRESSES
   Every view is a query string, so an article has an address that can be
   posted and reloaded:

     /research-deck              every published article, newest first
     /research-deck?t=TCS        the articles tagged with one company
     /research-deck?a=<slug>     one article
     /research-deck?edit=new     the owner: write a new one
     /research-deck?edit=<id>    the owner: edit one (drafts included)

   THE OWNER
   Only the owner writes. "Owner sign-in" asks for the admin key, keeps it in
   this browser only (the same localStorage entry the Post drafts panel uses),
   and checks it against GET /admin/research before anything changes on
   screen. A wrong or revoked key is forgotten on the first 401. Nobody else
   ever sees an edit button, and the server refuses every write without the
   key whatever this page shows.

   EVERYTHING WRITTEN IS TEXT
   An article body is a small, safe Markdown: headings (#, ##, ###), lists,
   quotes, **bold**, *italic*, `code`, [links](https://…), --- rules, and
   photos as ![caption](media:<id>). It is escaped before any of that is
   applied, so nothing typed is ever read as markup. */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : 'https://taha-project.onrender.com';
  var KEY_STORE = 'altaha-admin-key';
  var view = document.getElementById('rd-view');
  var ownerBar = document.getElementById('rd-owner-bar');
  var ownerBtn = document.getElementById('rd-owner');
  var top = document.getElementById('rd-top');
  var state = { owner: false, list: null };

  /* ── Small things ───────────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function track(name, props) { if (window.AltahaTrack) window.AltahaTrack(name, props || {}); }
  function cleanSym(s) { return String(s || '').trim().toUpperCase().replace(/\.(NS|BO)$/, '').replace(/[^A-Z0-9&.\-]/g, '').slice(0, 20); }
  function adminKey() { try { return localStorage.getItem(KEY_STORE) || ''; } catch (e) { return ''; } }
  function setAdminKey(v) { try { if (v) localStorage.setItem(KEY_STORE, v); else localStorage.removeItem(KEY_STORE); } catch (e) {} }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function day(iso) {
    var t = Date.parse(iso || '');
    if (!isFinite(t)) return '';
    var d = new Date(t);
    return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  }

  function mediaUrl(id, draft) {
    var u = API + '/research/media/' + encodeURIComponent(id);
    return draft && state.owner ? u + '?key=' + encodeURIComponent(adminKey()) : u;
  }
  function mediaId(ref) {
    var m = /^media:([0-9a-f]{16})$/.exec(String(ref || '').trim());
    return m ? m[1] : null;
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { 'Accept': 'application/json' };
    if (opts.admin) headers['X-Admin-Key'] = adminKey();
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(API + path, {
      method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
      headers: headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401 && opts.admin) { setOwner(false); setAdminKey(''); }
        if (!r.ok) {
          var msg = j && j.detail;
          if (msg && typeof msg === 'object') msg = msg.message;
          var e = new Error(msg || ('The server said ' + r.status + '.'));
          e.status = r.status;
          throw e;
        }
        return j;
      });
    });
  }

  function params() { return new URLSearchParams(location.search); }
  function go(q, replace) {
    var url = location.pathname + (q ? '?' + q : '');
    if (replace) history.replaceState(null, '', url); else history.pushState(null, '', url);
    route();
    window.scrollTo(0, 0);
  }

  /* ── The body: a small Markdown, escaped first ─────────────────────── */

  function inline(s, draft) {
    // `s` is already escaped. Code first, so nothing inside it is formatted.
    var codes = [];
    s = s.replace(/`([^`]+)`/g, function (_, c) { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_, t, u) {
      return '<a href="' + u + '" rel="nofollow noopener" target="_blank">' + t + '</a>';
    });
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, function (_, pre, u) {
      return pre + '<a href="' + u + '" rel="nofollow noopener" target="_blank">' + u + '</a>';
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, '$1<em>$2</em>');
    s = s.replace(/\$([A-Z][A-Z0-9&]{1,19})\b/g, function (_, t) {
      return '<a class="rd-sym" href="stock.html?ticker=' + encodeURIComponent(t) + '">$' + t + '</a>';
    });
    return s.replace(/\u0000(\d+)\u0000/g, function (_, i) { return '<code>' + codes[+i] + '</code>'; });
  }

  function figure(cap, src, draft) {
    // `cap` and `src` arrive escaped; only a URL built here needs escaping.
    var id = mediaId(src);
    var url = id ? esc(mediaUrl(id, draft)) : (/^https:\/\//.test(src) ? src : null);
    if (!url) return '';
    return '<figure class="rd-fig"><img src="' + url + '" alt="' + cap + '" loading="lazy">' +
      (cap ? '<figcaption>' + cap + '</figcaption>' : '') + '</figure>';
  }

  function render(md, draft) {
    var lines = esc(md || '').split('\n');
    var out = [], para = [], list = null;
    function flushPara() { if (para.length) { out.push('<p>' + inline(para.join(' '), draft) + '</p>'); para = []; } }
    function flushList() { if (list) { out.push('<' + list.tag + '>' + list.items.join('') + '</' + list.tag + '>'); list = null; } }
    lines.forEach(function (raw) {
      var line = raw.replace(/\s+$/, '');
      var m;
      if (!line.trim()) { flushPara(); flushList(); return; }
      if ((m = /^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line))) {
        flushPara(); flushList(); out.push(figure(m[1], m[2], draft)); return;
      }
      if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) {
        flushPara(); flushList();
        var lvl = m[1].length + 1;
        out.push('<h' + lvl + '>' + inline(m[2], draft) + '</h' + lvl + '>'); return;
      }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flushPara(); flushList(); out.push('<hr>'); return; }
      if ((m = /^&gt;\s?(.*)$/.exec(line))) {
        flushPara(); flushList(); out.push('<blockquote>' + inline(m[1], draft) + '</blockquote>'); return;
      }
      if ((m = /^\s*(?:[-*•])\s+(.*)$/.exec(line)) || (m = /^\s*(\d+)[.)]\s+(.*)$/.exec(line))) {
        var ordered = m.length === 3;
        var tag = ordered ? 'ol' : 'ul';
        flushPara();
        if (!list || list.tag !== tag) { flushList(); list = { tag: tag, items: [] }; }
        list.items.push('<li>' + inline(ordered ? m[2] : m[1], draft) + '</li>');
        return;
      }
      flushList();
      para.push(line.trim());
    });
    flushPara(); flushList();
    return out.join('\n');
  }

  /* ── Owner ──────────────────────────────────────────────────────────── */

  function setOwner(on) {
    state.owner = !!on;
    ownerBar.hidden = !on;
    ownerBtn.textContent = on ? 'Owner: sign out' : 'Owner sign-in';
  }

  function checkOwner() {
    if (!adminKey()) { setOwner(false); return Promise.resolve(false); }
    return api('/admin/research?limit=1', { admin: true })
      .then(function () { setOwner(true); return true; })
      .catch(function () { setOwner(false); return false; });
  }

  ownerBtn.addEventListener('click', function () {
    if (state.owner) { setAdminKey(''); setOwner(false); state.list = null; route(); return; }
    var k = window.prompt('Admin key (kept in this browser only):') || '';
    if (!k.trim()) return;
    setAdminKey(k.trim());
    checkOwner().then(function (ok) {
      if (!ok) { window.alert('That key was not accepted.'); return; }
      track('research_owner_signin');
      state.list = null;
      route();
    });
  });

  /* ── Share ──────────────────────────────────────────────────────────── */

  function sharePayload(a) {
    return { kind: 'research', slug: a.slug, version: a.version, title: a.title,
             summary: a.summary, tickers: a.tickers || [] };
  }
  function shareX(a) {
    var S = window.AltahaShare;
    var url = S ? S.shareUrl('x', sharePayload(a))
      : 'https://x.com/intent/post?text=' + encodeURIComponent(a.title) + '&url=' + encodeURIComponent(a.share_url);
    track('share_clicked', { kind: 'research', action: 'x', from: 'deck' });
    window.open(url, '_blank', 'noopener,width=600,height=680');
  }
  function shareMore(a) {
    if (window.AltahaShare) window.AltahaShare.open(sharePayload(a));
  }
  function copyLink(a, btn) {
    var link = (window.AltahaShare && window.AltahaShare.link(sharePayload(a))) || a.share_url;
    var done = function (ok) {
      var was = btn.textContent;
      btn.textContent = ok ? 'Link copied' : 'Copy failed';
      setTimeout(function () { btn.textContent = was; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link).then(function () { done(true); }, function () { done(false); });
    } else { done(false); }
  }

  var X_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z"/></svg>';

  function shareBar(a) {
    return '<div class="rd-share" data-slug="' + esc(a.slug) + '">' +
      '<button type="button" class="rd-btn is-x" data-act="x">' + X_ICON + '<span>Share on X</span></button>' +
      '<button type="button" class="rd-btn" data-act="copy">Copy link</button>' +
      '<button type="button" class="rd-btn" data-act="more">More ways to share</button>' +
      '</div>';
  }
  function wireShare(root, a) {
    root.querySelectorAll('.rd-share [data-act]').forEach(function (b) {
      b.addEventListener('click', function () {
        var act = b.getAttribute('data-act');
        if (act === 'x') shareX(a);
        else if (act === 'copy') copyLink(a, b);
        else shareMore(a);
      });
    });
  }

  /* ── The deck ───────────────────────────────────────────────────────── */

  function tile(a) {
    var cover = mediaId('media:' + (a.cover || ''));
    var draft = a.status !== 'published';
    return '<article class="rd-tile' + (draft ? ' is-draft' : '') + '">' +
      '<a class="rd-tile-link" href="?' + (draft ? 'edit=' + a.id : 'a=' + encodeURIComponent(a.slug)) + '" data-nav>' +
        (cover ? '<div class="rd-tile-img"><img src="' + esc(mediaUrl(cover, draft)) + '" alt="" loading="lazy"></div>'
               : '<div class="rd-tile-img is-empty" aria-hidden="true"><span>Research</span></div>') +
        '<div class="rd-tile-body">' +
          '<p class="rd-meta">' + (draft ? '<span class="rd-tag is-draft">Draft</span> ' : '') +
            esc(day(a.published_at || a.updated_at)) + ' · ' + a.minutes + ' min read</p>' +
          '<h2 class="rd-tile-title">' + esc(a.title) + '</h2>' +
          (a.summary ? '<p class="rd-tile-sum">' + esc(a.summary) + '</p>' : '') +
          (a.tickers && a.tickers.length ? '<p class="rd-tags">' + a.tickers.map(function (t) {
            return '<span class="rd-tag">' + esc(t) + '</span>'; }).join('') + '</p>' : '') +
        '</div>' +
      '</a></article>';
  }

  function showList(ticker) {
    top.hidden = false;
    var path = state.owner ? '/admin/research' : '/research/articles' + (ticker ? '?ticker=' + encodeURIComponent(ticker) : '');
    view.innerHTML = '<p class="rd-loading">Loading the deck…</p>';
    api(path, { admin: state.owner }).then(function (j) {
      var items = j.items || [];
      if (state.owner && ticker) items = items.filter(function (a) { return (a.tickers || []).indexOf(ticker) >= 0; });
      var head = ticker ? '<p class="rd-filter">Articles on <strong>' + esc(ticker) + '</strong> · <a href="?" data-nav>All research</a></p>' : '';
      if (!items.length) {
        view.innerHTML = head + '<div class="rd-empty"><p>' +
          (state.owner ? 'Nothing here yet. Write the first article with <strong>New article</strong>.'
                       : 'No research has been published here yet. Check back soon.') + '</p></div>';
        return;
      }
      view.innerHTML = head + '<div class="rd-grid">' + items.map(tile).join('') + '</div>';
    }).catch(function (e) {
      view.innerHTML = '<div class="rd-empty"><p>The deck could not be loaded. ' + esc(e.message) + '</p></div>';
    });
  }

  /* ── One article ────────────────────────────────────────────────────── */

  function showArticle(slug) {
    top.hidden = true;
    view.innerHTML = '<p class="rd-loading">Loading the article…</p>';
    api('/research/articles/' + encodeURIComponent(slug)).then(function (a) {
      document.title = a.title + ' | Altaha Research';
      var cover = mediaId('media:' + (a.cover || ''));
      view.innerHTML =
        '<article class="rd-article">' +
          '<a class="rd-back" href="?" data-nav>← All research</a>' +
          '<p class="rd-eyebrow">Altaha Research · ' + esc(day(a.published_at)) + ' · ' + a.minutes + ' min read</p>' +
          '<h1 class="rd-title">' + esc(a.title) + '</h1>' +
          (a.summary ? '<p class="rd-summary">' + esc(a.summary) + '</p>' : '') +
          (a.tickers && a.tickers.length ? '<p class="rd-tags">' + a.tickers.map(function (t) {
            return '<a class="rd-tag is-stock" href="stock.html?ticker=' + encodeURIComponent(t) + '">' + esc(t) + '</a>'; }).join('') + '</p>' : '') +
          shareBar(a) +
          (cover ? '<figure class="rd-cover"><img src="' + esc(mediaUrl(cover)) + '" alt=""></figure>' : '') +
          '<div class="rd-body">' + render(a.body) + '</div>' +
          '<hr class="rd-rule">' +
          shareBar(a) +
          '<p class="rd-disclaimer">Research for education and information. It is not a recommendation to buy, sell or hold any security, and Altaha is not registered with SEBI as an investment adviser or research analyst. Do your own research and consult a registered adviser before investing.</p>' +
          (state.owner ? '<p class="rd-owner-actions"><a class="rd-btn" href="?edit=' + a.id + '" data-nav>Edit this article</a></p>' : '') +
        '</article>';
      wireShare(view, a);
      track('research_read', { slug: a.slug });
    }).catch(function (e) {
      view.innerHTML = '<div class="rd-empty"><p>' + (e.status === 404
        ? 'This article is not here. It may have been taken down.'
        : 'The article could not be loaded. ' + esc(e.message)) +
        '</p><p><a href="?" data-nav>See all research</a></p></div>';
    });
  }

  /* ── The editor (owner only) ───────────────────────────────────────── */

  /* A photo over 3 MB is redrawn at 2400 px before it is sent: the server
     would shrink it anyway, and a phone on mobile data should not have to
     upload twelve megabytes to get there. GIFs go as they are. */
  function readPhoto(file) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () {
        var dataUrl = fr.result;
        if (file.size <= 3 * 1024 * 1024 || /gif/.test(file.type)) { resolve(dataUrl); return; }
        var img = new Image();
        img.onload = function () {
          var scale = Math.min(1, 2400 / Math.max(img.width, img.height));
          var c = document.createElement('canvas');
          c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
          c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          resolve(c.toDataURL(/png/.test(file.type) ? 'image/png' : 'image/jpeg', 0.9));
        };
        img.onerror = function () { resolve(dataUrl); };
        img.src = dataUrl;
      };
      fr.onerror = function () { reject(new Error('The file could not be read.')); };
      fr.readAsDataURL(file);
    });
  }
  function uploadPhoto(file) {
    if (!file) return Promise.reject(new Error('Choose a photo.'));
    if (!/^image\//.test(file.type)) return Promise.reject(new Error('That is not a photo.'));
    return readPhoto(file).then(function (data) {
      return api('/admin/research/media', { admin: true, body: { data: data } });
    });
  }

  function editor(id) {
    top.hidden = true;
    if (!state.owner) {
      view.innerHTML = '<div class="rd-empty"><p>Only the owner can write here. Use <strong>Owner sign-in</strong> at the bottom of the page.</p><p><a href="?" data-nav>See all research</a></p></div>';
      return;
    }
    var load = id === 'new' ? Promise.resolve({ title: '', summary: '', body: '', tickers: [], cover: null, status: 'draft' })
                            : api('/admin/research?id=' + encodeURIComponent(id), { admin: true });
    view.innerHTML = '<p class="rd-loading">Opening the editor…</p>';
    load.then(function (a) { drawEditor(a); }).catch(function (e) {
      view.innerHTML = '<div class="rd-empty"><p>' + esc(e.message) + '</p><p><a href="?" data-nav>Back to the deck</a></p></div>';
    });
  }

  function drawEditor(a) {
    var cur = { id: a.id || null, cover: a.cover || null, status: a.status || 'draft', slug: a.slug, version: a.version };
    document.title = (cur.id ? 'Edit: ' + a.title : 'New article') + ' | Research Deck';
    view.innerHTML =
      '<form class="rd-ed" id="rd-ed" novalidate>' +
        '<a class="rd-back" href="?" data-nav>← The deck</a>' +
        '<div class="rd-ed-head"><h1 class="rd-ed-h">' + (cur.id ? 'Edit article' : 'New article') + '</h1>' +
          '<span class="rd-tag' + (cur.status === 'published' ? ' is-live' : ' is-draft') + '" id="ed-status">' +
            (cur.status === 'published' ? 'Published' : 'Draft') + '</span></div>' +
        '<label class="rd-field"><span>Title</span><input id="ed-title" maxlength="160" required value="' + esc(a.title) + '" placeholder="What did you find?"></label>' +
        '<label class="rd-field"><span>Summary <em id="ed-sumcount"></em></span><textarea id="ed-summary" rows="2" maxlength="300" placeholder="One or two sentences. This is what X shows under the card.">' + esc(a.summary) + '</textarea></label>' +
        '<label class="rd-field"><span>Stocks it is about <em>symbols, comma-separated, up to 10</em></span><input id="ed-tickers" value="' + esc((a.tickers || []).join(', ')) + '" placeholder="LT, SIEMENS, ABB"></label>' +
        '<div class="rd-field"><span>Cover photo <em>shown on the deck and on the X card</em></span>' +
          '<div class="rd-cover-ed" id="ed-cover"></div>' +
          '<div class="rd-row"><label class="rd-btn is-small rd-file">Upload cover<input type="file" accept="image/*" id="ed-cover-file" hidden></label>' +
          '<button type="button" class="rd-btn is-small" id="ed-cover-clear">Remove cover</button></div></div>' +
        '<div class="rd-field"><span>Article</span>' +
          '<div class="rd-toolbar">' +
            '<label class="rd-btn is-small rd-file">Add photo<input type="file" accept="image/*" id="ed-photo" hidden multiple></label>' +
            '<button type="button" class="rd-btn is-small" id="ed-preview-btn" aria-pressed="false">Preview</button>' +
            '<span class="rd-hint"># Heading · **bold** · *italic* · - list · &gt; quote · [link](https://…) · $TCS links a stock</span>' +
          '</div>' +
          '<textarea id="ed-body" rows="18" placeholder="Write the research. Photos you add appear where the cursor is.">' + esc(a.body) + '</textarea>' +
          '<div class="rd-body rd-preview" id="ed-preview" hidden></div>' +
        '</div>' +
        '<p class="rd-msg" id="ed-msg" role="status"></p>' +
        '<div class="rd-ed-actions">' +
          '<button type="button" class="rd-btn" id="ed-draft">Save draft</button>' +
          '<button type="button" class="rd-btn is-gold" id="ed-publish">' + (cur.status === 'published' ? 'Update' : 'Publish') + '</button>' +
          (cur.status === 'published' ? '<button type="button" class="rd-btn" id="ed-unpublish">Unpublish</button>' : '') +
          (cur.id ? '<button type="button" class="rd-btn is-danger" id="ed-delete">Delete</button>' : '') +
        '</div>' +
        '<div id="ed-after"></div>' +
      '</form>';

    var $ = function (s) { return document.getElementById(s); };
    var msg = $('ed-msg'), body = $('ed-body');

    function say(text, err) { msg.textContent = text || ''; msg.classList.toggle('is-err', !!err); }
    function drawCover() {
      var id = mediaId('media:' + (cur.cover || ''));
      $('ed-cover').innerHTML = id ? '<img src="' + esc(mediaUrl(id, true)) + '" alt="Cover photo">'
                                   : '<p class="rd-hint">No cover yet. Articles with a photo get noticed on X.</p>';
      $('ed-cover-clear').hidden = !id;
    }
    function count() { $('ed-sumcount').textContent = $('ed-summary').value.length + '/300'; }
    drawCover(); count();
    $('ed-summary').addEventListener('input', count);

    $('ed-cover-file').addEventListener('change', function (e) {
      var f = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!f) return;
      say('Uploading the cover…');
      uploadPhoto(f).then(function (m) { cur.cover = m.id; drawCover(); say('Cover uploaded. Save to keep it.'); })
        .catch(function (err) { say(err.message, true); });
    });
    $('ed-cover-clear').addEventListener('click', function () { cur.cover = null; drawCover(); });

    function insertAtCursor(text) {
      var s = body.selectionStart != null ? body.selectionStart : body.value.length;
      var e = body.selectionEnd != null ? body.selectionEnd : s;
      var before = body.value.slice(0, s), after = body.value.slice(e);
      var pre = before && !/\n\n$/.test(before) ? (/\n$/.test(before) ? '\n' : '\n\n') : '';
      var post = after && !/^\n/.test(after) ? '\n\n' : '\n';
      body.value = before + pre + text + post + after;
      var at = (before + pre + text + post).length;
      body.focus(); body.setSelectionRange(at, at);
    }
    $('ed-photo').addEventListener('change', function (e) {
      var files = Array.prototype.slice.call(e.target.files || []);
      e.target.value = '';
      if (!files.length) return;
      var i = 0;
      (function next() {
        if (i >= files.length) { say(files.length + (files.length === 1 ? ' photo' : ' photos') + ' added. Edit the caption in the brackets.'); return; }
        var f = files[i++];
        say('Uploading ' + f.name + '…');
        uploadPhoto(f).then(function (m) {
          insertAtCursor('![' + f.name.replace(/\.[^.]+$/, '').replace(/[\[\]]/g, '') + '](media:' + m.id + ')');
          if (!cur.cover) { cur.cover = m.id; drawCover(); }
          next();
        }).catch(function (err) { say(f.name + ': ' + err.message, true); });
      })();
    });

    $('ed-preview-btn').addEventListener('click', function () {
      var on = $('ed-preview').hidden;
      $('ed-preview').hidden = !on; body.hidden = on;
      this.setAttribute('aria-pressed', on ? 'true' : 'false');
      this.textContent = on ? 'Write' : 'Preview';
      if (on) $('ed-preview').innerHTML = render(body.value, true) || '<p class="rd-hint">Nothing written yet.</p>';
    });

    function payload(status) {
      return { id: cur.id, title: $('ed-title').value, summary: $('ed-summary').value,
               tickers: $('ed-tickers').value, body: body.value,
               cover: cur.cover ? 'media:' + cur.cover : null, status: status };
    }
    function save(status) {
      say(status === 'published' ? 'Publishing…' : 'Saving…');
      return api('/admin/research/save', { admin: true, body: payload(status) }).then(function (saved) {
        var first = !cur.id;
        cur.id = saved.id; cur.status = saved.status; cur.slug = saved.slug; cur.version = saved.version;
        state.list = null;
        history.replaceState(null, '', location.pathname + '?edit=' + saved.id);
        track('research_saved', { status: saved.status, first: first });
        if (saved.status === 'published') {
          drawEditor(saved);
          var after = document.getElementById('ed-after');
          after.innerHTML = '<div class="rd-published"><p><strong>Published.</strong> It is live at <a href="?a=' + encodeURIComponent(saved.slug) + '" data-nav>' + esc(saved.url) + '</a>. Post it:</p>' + shareBar(saved) + '</div>';
          wireShare(after, saved);
          document.getElementById('ed-msg').textContent = '';
        } else {
          drawEditor(saved);
          document.getElementById('ed-msg').textContent = 'Draft saved. Only you can see it.';
        }
      }).catch(function (err) { say(err.message, true); });
    }
    $('ed-draft').addEventListener('click', function () { save('draft'); });
    $('ed-publish').addEventListener('click', function () { save('published'); });
    if ($('ed-unpublish')) $('ed-unpublish').addEventListener('click', function () {
      if (window.confirm('Take this article off the public deck? Links already posted will stop showing it.')) save('draft');
    });
    if ($('ed-delete')) $('ed-delete').addEventListener('click', function () {
      if (!window.confirm('Delete this article and its photos for good? This cannot be undone.')) return;
      api('/admin/research/delete', { admin: true, body: { id: cur.id } }).then(function () {
        state.list = null; go('', true);
      }).catch(function (err) { say(err.message, true); });
    });
  }

  /* ── Routing ────────────────────────────────────────────────────────── */

  function route() {
    var p = params();
    if (p.get('edit')) { editor(p.get('edit')); return; }
    if (p.get('a')) { showArticle(p.get('a')); return; }
    document.title = 'Research Deck | Altaha Screener';
    showList(cleanSym(p.get('t')) || null);
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-nav]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault();
    go((a.getAttribute('href') || '').replace(/^\?/, ''));
  });
  window.addEventListener('popstate', route);
  document.getElementById('rd-new').addEventListener('click', function (e) { e.preventDefault(); go('edit=new'); });

  checkOwner().then(route, route);

  /* Exposed for the tests. */
  window.AltahaResearch = { render: render };
})();
