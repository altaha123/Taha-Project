/* Altaha — the forum (forum.html). The rules live in backend/forum.py; this
   file draws what the API returns and sends what the reader writes.

   ADDRESSES
   Every view is a hash, so a discussion can be shared and the sign-in page
   can bring a reader back to it (signin.html only returns to a page on this
   site by name and hash):

     forum.html                  the front page: every discussion, latest first
     forum.html#c/market         one category
     forum.html#stock/TCS        one company's discussions
     forum.html#t/42             one discussion
     forum.html#new              start one; #new/stock/TCS starts it on TCS

   READING NEEDS NOTHING, WRITING NEEDS A NAME
   Anyone can read. Writing needs an account and a forum name, chosen once;
   the email address is never shown. A post a house rule turns away comes
   back with the sentence that tripped it, and the page shows that sentence
   so the writer can see exactly what to change.

   EVERYTHING A MEMBER WROTE IS TEXT
   Posts are escaped, split into paragraphs, and their http(s) links made
   into links with rel="nofollow ugc noopener". Nothing a member wrote is
   ever read as markup. */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : 'https://taha-project.onrender.com';
  var view = document.getElementById('fm-view');
  var side = document.getElementById('fm-side');
  var state = { overview: null, me: null, meAsked: false, sort: 'latest', q: '', page: 1 };

  /* ── Small things ───────────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function track(name, props) { if (window.AltahaTrack) window.AltahaTrack(name, props || {}); }
  function authed() { return !!(window.AltahaAuth && window.AltahaAuth.authed && window.AltahaAuth.authed()); }
  function cleanSym(s) { return String(s || '').trim().toUpperCase().replace(/\.(NS|BO)$/, '').replace(/[^A-Z0-9&.\-]/g, '').slice(0, 20); }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function when(iso) {
    var t = Date.parse(iso || '');
    if (!isFinite(t)) return '';
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 86400) return Math.floor(s / 3600) + ' h ago';
    if (s < 86400 * 7) return Math.floor(s / 86400) + ' d ago';
    var d = new Date(t);
    return d.getDate() + ' ' + MONTHS[d.getMonth()] + (d.getFullYear() !== new Date().getFullYear() ? ' ' + d.getFullYear() : '');
  }
  function initial(name) { var m = /[A-Za-z0-9]/.exec(name || ''); return m ? m[0].toUpperCase() : '·'; }

  /* A post is text. Escaped first, then paragraphs, then links: the link
     pattern runs over escaped text, so it can never see a tag to open. */
  function bodyHTML(text) {
    return String(text || '').split(/\n{2,}/).map(function (para) {
      var html = esc(para).replace(/https?:\/\/[^\s<]+[^\s<.,;:!?)\]'"]/g, function (u) {
        return '<a href="' + u + '" target="_blank" rel="nofollow ugc noopener">' + u + '</a>';
      }).replace(/\n/g, '<br>');
      return '<p>' + html + '</p>';
    }).join('');
  }

  function api(path, opts) {
    opts = opts || {};
    var go = (window.AltahaAuth && window.AltahaAuth.fetch)
      ? window.AltahaAuth.fetch(path, opts)
      : fetch(API + path, Object.assign({}, opts, { headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}) }));
    return go.then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var detail = d && d.detail;
          var err = new Error(typeof detail === 'string' ? detail : (detail && detail.message) ||
            (r.status === 401 ? 'Sign in to post on the forum.' : 'The forum could not be reached just now. Try again in a minute.'));
          err.status = r.status;
          err.sentence = detail && detail.sentence;
          err.rule = detail && detail.rule;
          throw err;
        }
        return d;
      });
    }, function () {
      throw new Error('The forum could not be reached. Check your connection and try again.');
    });
  }
  function post(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body || {}) }); }

  function errHTML(err) {
    return esc(err.message) + (err.sentence ? '<blockquote>' + esc(err.sentence) + '</blockquote>' : '');
  }
  function showErr(el, err) {
    el.className = 'fm-msg is-err';
    el.innerHTML = errHTML(err);
    if (err.status === 422) track('forum_post_refused', { rule: err.rule || 'other' });
  }

  function signInHref(hash) {
    return 'signin.html?next=' + encodeURIComponent('forum.html' + (hash ? '#' + hash : ''));
  }

  /* ── Routing ────────────────────────────────────────────────────────── */

  function route() {
    var h = decodeURIComponent((location.hash || '').replace(/^#/, ''));
    var m;
    if ((m = /^t\/(\d+)$/.exec(h))) return { name: 'thread', id: +m[1] };
    if ((m = /^stock\/([^/]+)$/i.exec(h))) return { name: 'list', symbol: cleanSym(m[1]) };
    if ((m = /^c\/([a-z]+)$/.exec(h))) return { name: 'list', category: m[1] };
    if ((m = /^new(?:\/stock\/([^/]+)|\/c\/([a-z]+))?$/i.exec(h))) {
      return { name: 'new', symbol: m[1] ? cleanSym(m[1]) : '', category: m[2] || (m[1] ? 'stocks' : '') };
    }
    return { name: 'list' };
  }

  function render() {
    var r = route();
    var hero = r.name === 'list' && !r.category && !r.symbol;
    document.getElementById('fm-h1').hidden = !hero;
    document.getElementById('fm-lede').hidden = !hero;
    var newBtn = document.getElementById('fm-new');
    newBtn.hidden = r.name === 'new';
    newBtn.href = r.symbol ? '#new/stock/' + encodeURIComponent(r.symbol) : (r.category ? '#new/c/' + r.category : '#new');
    if (r.name === 'thread') renderThread(r.id);
    else if (r.name === 'new') renderNew(r);
    else renderList(r);
    renderSide(r);
  }

  window.addEventListener('hashchange', function () {
    state.page = 1;
    render();
    try { window.scrollTo(0, 0); } catch (e) {}
  });

  /* ── Who is reading ─────────────────────────────────────────────────── */

  function loadMe(force) {
    if (!authed()) { state.me = null; state.meAsked = true; return Promise.resolve(null); }
    if (state.meAsked && !force) return Promise.resolve(state.me);
    return api('/forum/me').then(function (me) {
      state.me = me; state.meAsked = true; return me;
    }, function () { state.me = null; state.meAsked = true; return null; });
  }

  /* What stands between this reader and writing: nothing, a forum name, or
     signing in. Returns HTML for the second two, '' for the first. */
  function gateHTML(hash) {
    if (!authed()) {
      return '<div class="fm-card fm-gate"><p>Sign in to post. Your email is never shown; you choose the name the forum sees.</p>' +
        '<a class="fm-btn is-gold" href="' + esc(signInHref(hash)) + '">Sign in to post</a></div>';
    }
    if (state.me && state.me.member && state.me.member.status === 'banned') {
      return '<div class="fm-card"><p class="fm-fine">This account can no longer post on the forum.</p></div>';
    }
    if (!state.me || !state.me.member) return nameFormHTML('Choose your forum name to post');
    return '';
  }

  function nameFormHTML(title, current) {
    return '<form class="fm-card fm-form" id="fm-name-form" novalidate>' +
      '<label class="fm-field">' + esc(title) +
        '<input id="fm-name" name="handle" maxlength="24" autocomplete="nickname" placeholder="e.g. Patient Compounder" value="' + esc(current || '') + '">' +
        '<small>3 to 24 characters. This is what other members see; your email never is.</small></label>' +
      '<div><button class="fm-btn is-gold" type="submit">Save name</button></div>' +
      '<p class="fm-msg" id="fm-name-msg" role="status"></p></form>';
  }

  function wireNameForm(after) {
    var form = document.getElementById('fm-name-form');
    if (!form) return;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var msg = document.getElementById('fm-name-msg'), btn = form.querySelector('button');
      btn.disabled = true;
      post('/forum/me/handle', { handle: document.getElementById('fm-name').value }).then(function (d) {
        state.me = { member: d.member, can_post: d.member.status === 'active' };
        state.meAsked = true;
        (after || render)();
      }, function (err) { btn.disabled = false; showErr(msg, err); });
    });
  }

  /* ── The list ───────────────────────────────────────────────────────── */

  function cats() { return (state.overview && state.overview.categories) || []; }
  function catLabel(id) {
    var c = cats().filter(function (x) { return x.id === id; })[0];
    return c ? c.label : id;
  }

  function rowHTML(t) {
    var tags = [];
    if (t.pinned) tags.push('<span class="fm-tag is-pin">Pinned</span>');
    tags.push('<span class="fm-tag">' + esc(t.category_label || catLabel(t.category)) + '</span>');
    if (t.symbol) tags.push('<span class="fm-tag is-stock">' + esc(t.symbol) + '</span>');
    if (t.locked) tags.push('<span class="fm-tag is-lock">Closed</span>');
    return '<li><a class="fm-row" href="#t/' + t.id + '">' +
      '<span class="fm-row-tags">' + tags.join('') + '</span>' +
      '<h3>' + esc(t.title) + '</h3>' +
      (t.excerpt ? '<p>' + esc(t.excerpt) + '</p>' : '') +
      '<span class="fm-meta"><span>by <b>' + esc(t.author || 'member') + '</b></span>' +
      '<span>' + t.replies + (t.replies === 1 ? ' reply' : ' replies') + '</span>' +
      (t.helpful ? '<span>' + t.helpful + ' found it helpful</span>' : '') +
      '<span>active ' + esc(when(t.last_post_at)) + '</span></span></a></li>';
  }

  function listQuery(r) {
    var p = ['sort=' + state.sort, 'page=' + state.page];
    if (r.category) p.push('category=' + encodeURIComponent(r.category));
    if (r.symbol) p.push('symbol=' + encodeURIComponent(r.symbol));
    if (state.q) p.push('q=' + encodeURIComponent(state.q));
    return '/forum?' + p.join('&');
  }

  function keepOverview(d) {
    state.overview = { categories: d.categories, rules: d.rules, disclaimer: d.disclaimer };
  }

  function renderList(r, preloaded) {
    if (!state.overview) {
      // The categories arrive with the first page of the list; draw once, with both.
      view.innerHTML = '<p class="fm-loading">Loading the forum. If the site has been idle this takes about thirty seconds.</p>';
      api(listQuery(r)).then(function (d) { keepOverview(d); renderSide(r); renderList(r, d); }, function (err) {
        view.innerHTML = '<div class="fm-empty"><p>' + esc(err.message) + '</p><button type="button" class="fm-btn" id="fm-retry">Try again</button></div>';
        document.getElementById('fm-retry').addEventListener('click', function () { renderList(r); });
      });
      return;
    }
    var heading = '';
    if (r.symbol) {
      heading = '<a class="fm-back" href="forum.html">← All discussions</a>' +
        '<div class="fm-thread-h"><span class="fm-tag is-stock">' + esc(r.symbol) + '</span>' +
        '<h2>Discussions about ' + esc(r.symbol) + '</h2>' +
        '<p class="fm-fine"><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">Open the ' + esc(r.symbol) + ' stock page ›</a></p></div>';
    }
    var chips = '<nav class="fm-chips" aria-label="Categories">' +
      '<a class="fm-chip" href="forum.html"' + (!r.category && !r.symbol ? ' aria-current="page"' : '') + '>All</a>' +
      cats().map(function (c) {
        return '<a class="fm-chip" href="#c/' + esc(c.id) + '"' + (r.category === c.id ? ' aria-current="page"' : '') + '>' + esc(c.label) + '</a>';
      }).join('') + '</nav>';
    var tools = '<div class="fm-tools"><div class="fm-sort" role="group" aria-label="Order">' +
      [['latest', 'Latest'], ['new', 'New'], ['top', 'Top']].map(function (s) {
        return '<button type="button" data-sort="' + s[0] + '" aria-pressed="' + (state.sort === s[0]) + '">' + s[1] + '</button>';
      }).join('') + '</div>' +
      '<form class="fm-search" id="fm-search" role="search"><input type="search" id="fm-q" placeholder="Search titles or a symbol" ' +
        'aria-label="Search discussions" value="' + esc(state.q) + '"></form></div>';
    view.innerHTML = heading + (r.symbol ? '' : chips) + tools + '<div id="fm-list"><p class="fm-loading">Loading…</p></div>';

    view.querySelectorAll('[data-sort]').forEach(function (b) {
      b.addEventListener('click', function () { state.sort = b.dataset.sort; state.page = 1; renderList(r); });
    });
    document.getElementById('fm-search').addEventListener('submit', function (e) {
      e.preventDefault();
      state.q = document.getElementById('fm-q').value.trim().slice(0, 80);
      state.page = 1;
      renderList(r);
    });
    fillList(r, false, preloaded);
  }

  function fillList(r, append, preloaded) {
    var box = document.getElementById('fm-list');
    (preloaded ? Promise.resolve(preloaded) : api(listQuery(r))).then(function (d) {
      var list = box.querySelector('.fm-list');
      var rows = (d.threads || []).map(rowHTML).join('');
      if (append && list) {
        list.insertAdjacentHTML('beforeend', rows);
        var more = box.querySelector('.fm-more');
        if (more) more.remove();
      } else if (!rows) {
        var newHref = r.symbol ? '#new/stock/' + encodeURIComponent(r.symbol) : (r.category ? '#new/c/' + r.category : '#new');
        box.innerHTML = '<div class="fm-empty"><p>' +
          (state.q ? 'No discussion matches “' + esc(state.q) + '”.' :
            r.symbol ? 'Nobody has started a discussion about ' + esc(r.symbol) + ' yet.' :
            'No discussions here yet.') +
          '</p><a class="fm-btn is-gold" href="' + newHref + '">Start the first one</a></div>';
        return;
      } else {
        box.innerHTML = '<ul class="fm-list">' + rows + '</ul>';
      }
      if (d.has_more) {
        box.insertAdjacentHTML('beforeend', '<div class="fm-more"><button type="button" class="fm-btn" id="fm-more">Show more</button></div>');
        document.getElementById('fm-more').addEventListener('click', function () { state.page += 1; fillList(r, true); });
      }
    }, function (err) {
      box.innerHTML = '<div class="fm-empty"><p>' + esc(err.message) + '</p><button type="button" class="fm-btn" id="fm-retry">Try again</button></div>';
      document.getElementById('fm-retry').addEventListener('click', function () { fillList(r, append); });
    });
  }

  /* ── One discussion ─────────────────────────────────────────────────── */

  function postHTML(p, i, locked) {
    var gone = p.status === 'removed' ? 'Removed by the author.' :
      p.status === 'hidden' ? 'Hidden while the forum’s owner reviews it.' : '';
    var acts = '';
    if (!gone) {
      var canVote = authed() && !p.mine;
      acts = '<div class="fm-acts">' +
        '<button type="button" class="fm-act" data-helpful="' + p.id + '" aria-pressed="' + !!p.voted + '"' +
          (canVote ? '' : ' disabled title="' + (p.mine ? 'Your own post' : 'Sign in to mark posts helpful') + '"') + '>' +
          'Helpful' + (p.helpful ? ' · ' + p.helpful : '') + '</button>' +
        (authed() && !p.mine ? '<button type="button" class="fm-act" data-report="' + p.id + '">Report</button>' : '') +
        (p.mine ? '<button type="button" class="fm-act" data-remove="' + p.id + '">Remove</button>' : '') +
        '</div>';
    }
    return '<li class="fm-post' + (i === 0 ? ' is-first' : '') + '" id="p' + p.id + '">' +
      '<div class="fm-post-h"><span class="fm-avatar" aria-hidden="true">' + esc(initial(p.author)) + '</span>' +
        '<div><b>' + esc(p.author) + '</b><br><time datetime="' + esc(p.created_at) + '">' + esc(when(p.created_at)) + '</time></div></div>' +
      (gone ? '<p class="fm-gone">' + gone + '</p>' : '<div class="fm-body">' + bodyHTML(p.body) + '</div>') +
      acts + '</li>';
  }

  function renderThread(id) {
    view.innerHTML = '<p class="fm-loading">Loading the discussion…</p>';
    Promise.all([api('/forum/threads/' + id), loadMe()]).then(function (res) {
      var d = res[0], t = d.thread;
      document.title = t.title + ' | Altaha Forum';
      var back = t.symbol ? '<a class="fm-back" href="#stock/' + encodeURIComponent(t.symbol) + '">← More on ' + esc(t.symbol) + '</a>'
        : '<a class="fm-back" href="#c/' + esc(t.category) + '">← ' + esc(t.category_label) + '</a>';
      var tags = '<span class="fm-tag">' + esc(t.category_label) + '</span>' +
        (t.symbol ? ' <a class="fm-tag is-stock" href="stock.html?ticker=' + encodeURIComponent(t.symbol) + '">' + esc(t.symbol) +
          (t.company ? ' · ' + esc(t.company) : '') + ' ›</a>' : '') +
        (t.locked ? ' <span class="fm-tag is-lock">Closed to replies</span>' : '');
      var reply;
      if (t.locked) reply = '<p class="fm-fine">This discussion is closed to new replies.</p>';
      else {
        var gate = gateHTML('t/' + t.id);
        reply = gate || '<form class="fm-card fm-form fm-reply" id="fm-reply" novalidate>' +
          '<label class="fm-field">Reply as ' + esc(state.me.member.handle) +
            '<textarea id="fm-reply-body" maxlength="5000" placeholder="Add what you know, or ask what you want to know."></textarea></label>' +
          '<div><button class="fm-btn is-gold" type="submit">Post reply</button></div>' +
          '<p class="fm-msg" id="fm-reply-msg" role="status"></p></form>';
      }
      view.innerHTML = back + '<div class="fm-thread-h">' + tags + '<h2>' + esc(t.title) + '</h2></div>' +
        '<ol class="fm-posts" id="fm-posts">' + d.posts.map(function (p, i) { return postHTML(p, i, t.locked); }).join('') + '</ol>' +
        '<div class="fm-reply">' + reply + '</div>' +
        '<p class="fm-disclaimer">' + esc(d.disclaimer) + '</p>';
      wireNameForm(function () { renderThread(id); });
      wirePosts(t);
      var form = document.getElementById('fm-reply');
      if (form) form.addEventListener('submit', function (e) {
        e.preventDefault();
        var msg = document.getElementById('fm-reply-msg'), btn = form.querySelector('button');
        btn.disabled = true; msg.textContent = ''; msg.className = 'fm-msg';
        post('/forum/threads/' + t.id + '/posts', { body: document.getElementById('fm-reply-body').value }).then(function (res) {
          track('forum_reply_posted', { category: t.category });
          var list = document.getElementById('fm-posts');
          list.insertAdjacentHTML('beforeend', postHTML(res.post, list.children.length, false));
          wirePosts(t);
          document.getElementById('fm-reply-body').value = '';
          btn.disabled = false;
          msg.textContent = 'Posted.';
        }, function (err) { btn.disabled = false; showErr(msg, err); });
      });
    }, function (err) {
      view.innerHTML = '<div class="fm-empty"><p>' + esc(err.message) + '</p><a class="fm-btn" href="forum.html">All discussions</a></div>';
    });
  }

  function wirePosts(t) {
    view.querySelectorAll('[data-helpful]:not([data-wired])').forEach(function (b) {
      b.setAttribute('data-wired', '1');
      b.addEventListener('click', function () {
        var on = b.getAttribute('aria-pressed') !== 'true';
        b.disabled = true;
        post('/forum/posts/' + b.dataset.helpful + '/helpful', { on: on }).then(function (d) {
          b.disabled = false;
          b.setAttribute('aria-pressed', String(d.mine));
          b.textContent = 'Helpful' + (d.helpful ? ' · ' + d.helpful : '');
        }, function (err) { b.disabled = false; alert(err.message); });
      });
    });
    view.querySelectorAll('[data-report]:not([data-wired])').forEach(function (b) {
      b.setAttribute('data-wired', '1');
      b.addEventListener('click', function () {
        var why = window.prompt('What is wrong with this post? (a tip, a scam, abuse, spam…)');
        if (!why) return;
        post('/forum/posts/' + b.dataset.report + '/report', { reason: why }).then(function (d) {
          b.disabled = true;
          b.textContent = d.hidden ? 'Reported · hidden for review' : 'Reported';
        }, function (err) { alert(err.message); });
      });
    });
    view.querySelectorAll('[data-remove]:not([data-wired])').forEach(function (b) {
      b.setAttribute('data-wired', '1');
      b.addEventListener('click', function () {
        if (!window.confirm('Remove your post? Others will see that it was removed.')) return;
        post('/forum/posts/' + b.dataset.remove + '/remove').then(function () { renderThread(t.id); },
          function (err) { alert(err.message); });
      });
    });
  }

  /* ── Starting a discussion ──────────────────────────────────────────── */

  function renderNew(r) {
    view.innerHTML = '<p class="fm-loading">…</p>';
    var hash = 'new' + (r.symbol ? '/stock/' + r.symbol : r.category ? '/c/' + r.category : '');
    Promise.all([loadMe(), state.overview ? Promise.resolve(null) : api('/forum?page=1').then(function (d) {
      keepOverview(d); renderSide(r);
    }, function () {})]).then(function () {
      var back = '<a class="fm-back" href="' + (r.symbol ? '#stock/' + encodeURIComponent(r.symbol) : 'forum.html') + '">← Back</a>';
      var gate = gateHTML(hash);
      if (gate) {
        view.innerHTML = back + '<div class="fm-thread-h"><h2>Start a discussion</h2></div>' + gate;
        wireNameForm(function () { renderNew(r); });
        return;
      }
      var cat = r.category || 'stocks';
      var opts = cats().map(function (c) {
        return '<option value="' + esc(c.id) + '"' + (c.id === cat ? ' selected' : '') + '>' + esc(c.label) + '</option>';
      }).join('');
      var rules = ((state.overview && state.overview.rules) || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('');
      view.innerHTML = back + '<div class="fm-thread-h"><h2>Start a discussion</h2></div>' +
        '<form class="fm-card fm-form" id="fm-new-form" novalidate>' +
        '<label class="fm-field">Where it belongs<select id="fm-cat">' + opts + '</select></label>' +
        '<label class="fm-field" id="fm-sym-field">Stock<input id="fm-sym" maxlength="20" autocapitalize="characters" ' +
          'placeholder="NSE symbol, e.g. TCS" value="' + esc(r.symbol) + '"></label>' +
        '<label class="fm-field">Title<input id="fm-title" maxlength="140" placeholder="What do you want to talk about?"></label>' +
        '<label class="fm-field">Your post<textarea id="fm-body" maxlength="5000" ' +
          'placeholder="Your reasoning, what you see in the numbers or the business, and what you would like to know."></textarea>' +
          '<small>Posting as ' + esc(state.me.member.handle) + '.</small></label>' +
        (rules ? '<ul class="fm-rules">' + rules + '</ul>' : '') +
        '<div><button class="fm-btn is-gold" type="submit">Post discussion</button></div>' +
        '<p class="fm-msg" id="fm-new-msg" role="status"></p></form>';
      var sel = document.getElementById('fm-cat'), symField = document.getElementById('fm-sym-field');
      function syncSym() { symField.hidden = sel.value !== 'stocks'; }
      sel.addEventListener('change', syncSym);
      syncSym();
      var form = document.getElementById('fm-new-form');
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var msg = document.getElementById('fm-new-msg'), btn = form.querySelector('button');
        btn.disabled = true; msg.textContent = ''; msg.className = 'fm-msg';
        post('/forum/threads', {
          category: sel.value,
          symbol: sel.value === 'stocks' ? cleanSym(document.getElementById('fm-sym').value) : '',
          title: document.getElementById('fm-title').value,
          body: document.getElementById('fm-body').value
        }).then(function (d) {
          track('forum_thread_started', { category: d.thread.category, from: r.symbol ? 'stock' : 'forum' });
          location.hash = 't/' + d.thread.id;
        }, function (err) { btn.disabled = false; showErr(msg, err); });
      });
    });
  }

  /* ── The side ───────────────────────────────────────────────────────── */

  function renderSide(r) {
    var o = state.overview;
    var me;
    if (!authed()) {
      me = '<section class="fm-card"><h2>Join in</h2><p>Reading is free. Sign in to start a discussion or reply.</p>' +
        '<a class="fm-btn is-gold is-small" href="' + esc(signInHref(location.hash.replace(/^#/, ''))) + '">Sign in</a></section>';
    } else if (state.me && state.me.member) {
      me = '<section class="fm-card fm-me"><h2>You</h2><p>Posting as <b>' + esc(state.me.member.handle) + '</b></p>' +
        '<button type="button" class="fm-btn is-small" id="fm-rename">Change name</button><div id="fm-rename-box"></div></section>';
    } else {
      me = '';
    }
    var catList = o ? '<section class="fm-card"><h2>Categories</h2><ul class="fm-cats">' + o.categories.map(function (c) {
      return '<li><a href="#c/' + esc(c.id) + '"' + (r && r.category === c.id ? ' aria-current="page"' : '') + ' title="' + esc(c.blurb) + '">' +
        esc(c.label) + '<span>' + c.threads + '</span></a></li>';
    }).join('') + '</ul></section>' : '';
    var rules = o ? '<section class="fm-card"><h2>House rules</h2><ul class="fm-rules">' +
      o.rules.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
      '<p class="fm-fine">' + esc(o.disclaimer) + '</p></section>' : '';
    var brief = '<section class="fm-card"><h2>This week</h2><p>The week’s market, money flows, new rules and the forum’s busiest discussions, in one page.</p>' +
      '<a href="weekly.html?from=forum">Read the weekly brief ›</a></section>';
    side.innerHTML = me + catList + rules + brief;
    var rename = document.getElementById('fm-rename');
    if (rename) rename.addEventListener('click', function () {
      document.getElementById('fm-rename-box').innerHTML = nameFormHTML('New forum name', state.me.member.handle);
      rename.hidden = true;
      wireNameForm(function () { renderSide(route()); render(); });
    });
  }

  /* ── Start ──────────────────────────────────────────────────────────── */

  function start() {
    loadMe().then(function () { render(); });
    // Signing in or out in another tab, or the session check finishing late.
    window.addEventListener('altaha-auth', function () { loadMe(true).then(function () { renderSide(route()); }); });
  }
  window.AltahaForum = { bodyHTML: bodyHTML, route: route };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
