/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Advisors
   Find a person, read who they are, and talk to them.

   ONE PAGE, SIX VIEWS, ROUTED BY THE HASH
     #               the directory
     #a/<slug>       one person's profile, and the box to start a chat
     #chats          the chats I started        (#inbox: the ones started with me)
     #chat/<id>      one conversation
     #join           apply to be listed, or manage my listing
     #admin          the owner's review queue (needs the admin key)
   A hash, not separate pages, so the notification email can link straight to
   #chat/<id> and the back button behaves like a messaging app's.

   POLLING, AND WHY IT SLOWS DOWN
   The API runs one worker with eight threads, so a socket per open chat is not
   on the table (advisors.py says why). An open chat asks "anything after
   message N?" every four seconds while things are happening, every ten after
   a quiet minute, every twenty after five, and not at all while the tab is in
   the background. A conversation in full flow feels live; a chat left open in
   a tab overnight costs almost nothing.

   EVERYTHING FROM THE SERVER IS TEXT
   Names, bios and messages are typed by strangers. Every one goes through
   esc() or textContent; nothing typed by a person is ever parsed as markup.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : 'https://taha-project.onrender.com';
  var view = document.getElementById('adv-view');
  var state = { dir: null, me: null, meAt: 0, chat: null, inbox: false };
  var ADMIN_KEY = 'altaha-admin-key';
  // Tests set this to run the poll quickly; nothing else does.
  var POLL_SCALE = (typeof window.ADV_POLL_SCALE === 'number') ? window.ADV_POLL_SCALE : 1;

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function track(ev, props) { if (window.AltahaTrack) window.AltahaTrack(ev, props || {}); }
  function auth() { return window.AltahaAuth || null; }
  function authed() { var a = auth(); return !!(a && a.authed && a.authed()); }
  function signinHref(hash) {
    return 'signin.html?next=' + encodeURIComponent('advisors.html' + (hash || ''));
  }

  function api(path, opts) {
    opts = opts || {};
    var a = auth();
    var req = (a && a.fetch) ? a.fetch(path, opts) : fetch(API + path, opts);
    return req.then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var det = d && d.detail;
          var err = new Error(typeof det === 'string' ? det
            : (det && det.message) || 'Something went wrong. Try again in a moment.');
          err.status = r.status;
          err.sentence = (det && det.sentence) || '';
          throw err;
        }
        return d;
      });
    }, function () {
      var e = new Error('Altaha could not be reached. If the site has been idle it may be waking up — try again in half a minute.');
      e.status = 0;
      throw e;
    });
  }
  function send(path, method, body) {
    return api(path, { method: method, body: JSON.stringify(body || {}) });
  }

  function initials(name) {
    var parts = String(name || '?').trim().split(/\s+/).filter(Boolean);
    var s = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] || '?').slice(0, 2);
    return s.toUpperCase();
  }
  function mono(e, big) {
    return '<span class="adv-mono' + (e.registered ? ' is-reg' : '') + (big ? ' is-big' : '') +
      '" aria-hidden="true">' + esc(initials(e.display_name)) +
      (e.online ? '<i class="adv-dot"></i>' : '') + '</span>';
  }
  function kindLine(e) {
    return '<span class="adv-kind is-' + esc(e.kind) + '">' + esc(e.kind_short) + '</span>' +
      (e.sebi_reg ? ' <span class="adv-reg">' + esc(e.sebi_reg) + '</span>' : '');
  }
  function replyLabel(m) {
    if (!m) return '';
    if (m < 60) return 'Usually replies within ' + m + ' min';
    if (m < 1440) return 'Usually replies within ' + Math.round(m / 60) + ' h';
    return 'Usually replies within ' + Math.round(m / 1440) + ' days';
  }
  function presence(e) {
    if (e.online) return '<span class="adv-presence is-on">Online now</span>';
    if (!e.accepting) return '<span class="adv-presence">Not taking new chats</span>';
    return '<span class="adv-presence">Taking chats</span>';
  }
  function ago(iso) {
    var t = Date.parse(iso || '');
    if (!t) return '';
    var s = (Date.now() - t) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min';
    if (s < 86400) return Math.floor(s / 3600) + ' h';
    if (s < 7 * 86400) return Math.floor(s / 86400) + ' d';
    return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
  function clock(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
  function day(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  }
  function paint(html) { view.innerHTML = html; }
  function loading(what) { paint('<p class="adv-loading">' + esc(what || 'Loading…') + '</p>'); }
  function failed(err, retry) {
    paint('<div class="adv-empty"><p>' + esc(err.message) + '</p>' +
      (retry ? '<button class="adv-btn" type="button" id="adv-retry">Try again</button>' : '') + '</div>');
    var b = $('#adv-retry');
    if (b) b.addEventListener('click', retry);
  }

  function directory() {
    if (state.dir) return Promise.resolve(state.dir);
    return api('/advisors').then(function (d) { state.dir = d; return d; });
  }
  function me(force) {
    if (!authed()) return Promise.resolve(null);
    if (!force && state.me && Date.now() - state.meAt < 20000) return Promise.resolve(state.me);
    return api('/advisors/me').then(function (d) {
      state.me = d; state.meAt = Date.now(); paintUnread(d.unread); return d;
    }).catch(function (e) { if (e.status === 401) state.me = null; return null; });
  }
  function paintUnread(n) {
    var b = document.getElementById('adv-unread');
    if (!b) return;
    b.hidden = !n;
    b.textContent = n > 99 ? '99+' : String(n || '');
  }

  /* ── Routing ─────────────────────────────────────────────────────────── */

  function route() {
    stopPoll();
    state.chat = null;
    var h = location.hash.replace(/^#/, '');
    var m;
    var tab = 'list';
    if ((m = h.match(/^a\/([a-z0-9-]+)$/))) renderProfile(m[1]);
    else if ((m = h.match(/^chat\/(\d+)$/))) { tab = 'chats'; renderChat(+m[1]); }
    else if (h === 'chats' || h === 'inbox') { tab = 'chats'; state.inbox = h === 'inbox'; renderChats(); }
    else if (h === 'join') { tab = 'join'; renderJoin(); }
    else if (h === 'admin') { tab = ''; renderAdmin(); }
    else renderList();
    document.querySelectorAll('.adv-tabs a').forEach(function (a) {
      if (a.dataset.view === tab) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    if (!/^chat\//.test(h)) me();
    window.scrollTo(0, 0);
  }

  /* ── The directory ───────────────────────────────────────────────────── */

  // A link can arrive pre-filtered: the portfolio plan sends readers to
  // ?kind=ria&topic=portfolio, the people who can actually review one.
  var filters = (function () {
    var f = { kind: '', topic: '', q: '' };
    try {
      var p = new URLSearchParams(location.search);
      if (/^(registered|ria|ra|educator)$/.test(p.get('kind') || '')) f.kind = p.get('kind');
      if (/^[a-z_]{1,20}$/.test(p.get('topic') || '')) f.topic = p.get('topic');
    } catch (e) {}
    return f;
  })();
  var KIND_CHIPS = [
    ['', 'Everyone'], ['registered', 'SEBI-registered'], ['ria', 'Investment advisers'],
    ['ra', 'Research analysts'], ['educator', 'Educators']
  ];

  function renderList() {
    loading('Finding advisers…');
    track('advisors_viewed', {});
    directory().then(function (d) {
      paint(
        '<section class="adv-hero">' +
          '<h1>Talk to someone who <em>knows money</em> — and has been checked.</h1>' +
          '<p class="adv-lede">SEBI-registered investment advisers, research analysts and well-known market educators. ' +
          'Ask about your portfolio, a stock, a fund, your retirement or a career in finance. Chats are free.</p>' +
        '</section>' +
        '<div class="adv-filters">' +
          '<div class="adv-chips" role="group" aria-label="Who">' +
            KIND_CHIPS.map(function (k) {
              return '<button type="button" class="adv-chip" data-kind="' + k[0] + '" aria-pressed="' +
                (filters.kind === k[0]) + '">' + esc(k[1]) + '</button>';
            }).join('') +
          '</div>' +
          '<div class="adv-search">' +
            '<label class="adv-sr" for="adv-topic">Topic</label>' +
            '<select id="adv-topic"><option value="">Any topic</option>' +
              d.topics.map(function (t) {
                return '<option value="' + esc(t.id) + '"' + (filters.topic === t.id ? ' selected' : '') + '>' +
                  esc(t.label) + '</option>';
              }).join('') +
            '</select>' +
            '<label class="adv-sr" for="adv-q">Search by name</label>' +
            '<input id="adv-q" type="search" placeholder="Search by name" value="' + esc(filters.q) + '" autocomplete="off">' +
          '</div>' +
        '</div>' +
        '<div class="adv-grid" id="adv-grid"></div>' +
        '<aside class="adv-note"><b>Read this once.</b> ' + esc(d.disclaimer) + '</aside>'
      );
      view.querySelectorAll('.adv-chip').forEach(function (b) {
        b.addEventListener('click', function () {
          filters.kind = b.dataset.kind;
          view.querySelectorAll('.adv-chip').forEach(function (x) {
            x.setAttribute('aria-pressed', String(x === b));
          });
          paintGrid(d);
        });
      });
      $('#adv-topic').addEventListener('change', function (e) { filters.topic = e.target.value; paintGrid(d); });
      $('#adv-q').addEventListener('input', function (e) { filters.q = e.target.value; paintGrid(d); });
      paintGrid(d);
    }).catch(function (e) { failed(e, renderList); });
  }

  function matches(e) {
    if (filters.kind === 'registered' && !e.registered) return false;
    if (filters.kind && filters.kind !== 'registered' && e.kind !== filters.kind) return false;
    if (filters.topic && !e.topics.some(function (t) { return t.id === filters.topic; })) return false;
    var q = filters.q.trim().toLowerCase();
    if (q && (e.display_name + ' ' + e.headline).toLowerCase().indexOf(q) < 0) return false;
    return true;
  }

  function card(e) {
    var facts = [];
    if (e.experience_years) facts.push(e.experience_years + (e.experience_years === 1 ? ' yr' : ' yrs'));
    if (e.languages.length) facts.push(e.languages.join(', '));
    if (e.reply_minutes) facts.push(replyLabel(e.reply_minutes));
    return '<a class="adv-card' + (e.featured ? ' is-featured' : '') + '" href="#a/' + esc(e.slug) + '">' +
      '<div class="adv-who">' + mono(e) +
        '<div><h3>' + esc(e.display_name) + '</h3><p class="adv-kindline">' + kindLine(e) + '</p></div>' +
      '</div>' +
      '<p class="adv-headline">' + esc(e.headline) + '</p>' +
      '<ul class="adv-topics">' + e.topics.slice(0, 4).map(function (t) {
        return '<li>' + esc(t.label) + '</li>';
      }).join('') + '</ul>' +
      '<p class="adv-facts">' + esc(facts.join(' · ')) + '</p>' +
      '<p class="adv-cardfoot">' + presence(e) + '<span class="adv-go">Chat →</span></p>' +
    '</a>';
  }

  function paintGrid(d) {
    var grid = $('#adv-grid');
    if (!grid) return;
    var shown = d.experts.filter(matches);
    if (!d.experts.length) {
      grid.innerHTML = '<div class="adv-empty"><p><b>Nobody is listed yet.</b> The first advisers are being checked.</p>' +
        '<p>Are you a SEBI-registered adviser, a research analyst or a market educator? ' +
        '<a href="#join">Apply to be listed →</a></p></div>';
      return;
    }
    grid.innerHTML = shown.length ? shown.map(card).join('')
      : '<div class="adv-empty"><p>Nobody matches that. Try another topic, or everyone.</p></div>';
  }

  /* ── One profile, and starting a chat ────────────────────────────────── */

  function renderProfile(slug) {
    loading();
    Promise.all([
      api('/advisors/profile/' + encodeURIComponent(slug)),
      me(),
      authed() ? api('/advisors/chats').catch(function () { return null; }) : null
    ]).then(function (r) {
      var e = r[0].expert, mine = r[1], chats = r[2];
      track('advisor_profile_viewed', { kind: e.kind });
      var open = chats && chats.as_seeker.filter(function (c) {
        return c.expert_slug === e.slug && c.status === 'open';
      })[0];
      var facts = [];
      if (e.experience_years) facts.push(['Experience', e.experience_years + ' years']);
      if (e.languages.length) facts.push(['Chats in', e.languages.join(', ')]);
      if (e.reply_minutes) facts.push(['Replies', replyLabel(e.reply_minutes).replace('Usually replies ', 'usually ')]);
      if (e.answered) facts.push(['Conversations', e.answered + ' answered']);
      paint(
        '<a class="adv-back" href="#">← Everyone</a>' +
        '<div class="adv-profile">' +
          '<section class="adv-about">' +
            '<div class="adv-who is-big">' + mono(e, true) +
              '<div><h1>' + esc(e.display_name) + '</h1>' +
              '<p class="adv-kindline">' + kindLine(e) + ' ' + presence(e) + '</p></div>' +
            '</div>' +
            '<p class="adv-headline is-big">' + esc(e.headline) + '</p>' +
            regNote(e) +
            '<div class="adv-bio">' + esc(e.bio) + '</div>' +
            (facts.length ? '<dl class="adv-dl">' + facts.map(function (f) {
              return '<div><dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd></div>';
            }).join('') + '</dl>' : '') +
            '<ul class="adv-topics">' + e.topics.map(function (t) { return '<li>' + esc(t.label) + '</li>'; }).join('') + '</ul>' +
            (e.links && e.links.length ? '<p class="adv-links">' + e.links.map(function (u) {
              return '<a href="' + esc(u) + '" target="_blank" rel="nofollow noopener noreferrer ugc">' +
                esc(u.replace(/^https:\/\/(www\.)?/, '').replace(/\/$/, '')) + ' ↗</a>';
            }).join('') + '</p>' : '') +
          '</section>' +
          '<section class="adv-start" id="adv-start">' + startBox(e, mine, open) + '</section>' +
        '</div>' +
        '<aside class="adv-note">' + esc(r[0].disclaimer) + '</aside>'
      );
      wireStart(e);
    }).catch(function (err) {
      if (err.status === 404) {
        paint('<a class="adv-back" href="#">← Everyone</a><div class="adv-empty"><p>' +
          'This person is not listed — the link may be old, or the profile is being re-checked.</p></div>');
      } else failed(err, function () { renderProfile(slug); });
    });
  }

  function regNote(e) {
    if (e.registered) {
      return '<p class="adv-regnote is-reg">' + esc(e.kind_label) + ', registration <b>' + esc(e.sebi_reg) +
        '</b>. Altaha checked this number before listing; ' +
        '<a href="' + esc(e.register_url) + '" target="_blank" rel="noopener noreferrer">check it on SEBI’s register ↗</a></p>';
    }
    return '<p class="adv-regnote">Educator — <b>not SEBI-registered</b>. Can teach and explain how they think; ' +
      'cannot tell you what to buy or sell.</p>';
  }

  function startBox(e, mine, open) {
    var first = e.display_name.split(' ')[0];
    if (!authed()) {
      return '<h2>Ask ' + esc(first) + '</h2><p class="adv-muted">Sign in with your email to start a chat. ' +
        'Your address is never shown to the person you talk to.</p>' +
        '<a class="adv-btn is-gold" href="' + esc(signinHref('#a/' + e.slug)) + '">Sign in to chat</a>';
    }
    if (open) {
      return '<h2>You are talking to ' + esc(first) + '</h2><p class="adv-muted">Your chat about ' +
        esc(open.topic_label.toLowerCase()) + ' is open.</p>' +
        '<a class="adv-btn is-gold" href="#chat/' + open.id + '">Continue the chat</a>';
    }
    if (mine && mine.expert && mine.expert.slug === e.slug) {
      return '<h2>This is you</h2><p class="adv-muted">This is how readers see your profile.</p>' +
        '<a class="adv-btn" href="#join">Edit your profile</a>';
    }
    if (!e.accepting) {
      return '<h2>Not taking new chats</h2><p class="adv-muted">' + esc(e.display_name) +
        ' has paused new chats. Look again later, or find someone else.</p>' +
        '<a class="adv-btn" href="#">Everyone</a>';
    }
    var share = '';
    if (e.can_see_portfolio) {
      var n = mine ? mine.holdings : 0;
      var risk = mine && mine.risk_profile;
      share = '<label class="adv-check"><input type="checkbox" id="adv-share"' + (n ? '' : ' disabled') + '>' +
        '<span><b>Share my portfolio</b> — ' + (n
          ? 'the ' + n + ' holding' + (n === 1 ? '' : 's') + ' saved to your account' +
            (risk ? ' and your risk profile (' + esc(risk.band) + ')' : '') +
            '. You can stop sharing at any time.'
          : 'you have no portfolio saved to your account yet. <a href="index.html#portfolio">Add one</a>.') +
        '</span></label>';
    }
    return '<h2>Ask ' + esc(first) + '</h2>' +
      '<form id="adv-start-form" novalidate>' +
        '<label class="adv-field">What is it about?<select id="adv-s-topic">' +
          e.topics.map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.label) + '</option>'; }).join('') +
        '</select></label>' +
        '<label class="adv-field">Your name, as ' + esc(first) + ' will see it' +
          '<input id="adv-s-name" maxlength="40" autocomplete="given-name" placeholder="Leave blank to stay anonymous"></label>' +
        '<label class="adv-field">Your question<textarea id="adv-s-msg" rows="5" maxlength="2000" ' +
          'placeholder="Say what you have, what you want, and what is worrying you."></textarea></label>' +
        share +
        '<button class="adv-btn is-gold is-wide" id="adv-s-go" type="submit">Start the chat</button>' +
        '<p class="adv-msg" id="adv-s-msg-out" role="status"></p>' +
        '<p class="adv-fine">Free. Your email stays private. Never pay anyone you meet here or share an OTP or password.</p>' +
      '</form>';
  }

  function wireStart(e) {
    var form = $('#adv-start-form');
    if (!form) return;
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var out = $('#adv-s-msg-out'), go = $('#adv-s-go');
      var msg = $('#adv-s-msg').value.trim();
      out.textContent = ''; out.className = 'adv-msg';
      if (!msg) { out.textContent = 'Write your question first.'; out.className = 'adv-msg is-err'; return; }
      go.disabled = true; go.textContent = 'Sending…';
      var share = $('#adv-share');
      send('/advisors/profile/' + encodeURIComponent(e.slug) + '/chat', 'POST', {
        topic: $('#adv-s-topic').value, message: msg, name: $('#adv-s-name').value.trim(),
        share_portfolio: !!(share && share.checked)
      }).then(function (chat) {
        track('advisor_chat_started', { kind: e.kind, shared: !!(share && share.checked) });
        location.hash = '#chat/' + chat.id;
      }).catch(function (err) {
        go.disabled = false; go.textContent = 'Start the chat';
        out.textContent = err.message; out.className = 'adv-msg is-err';
      });
    });
  }

  /* ── My chats ────────────────────────────────────────────────────────── */

  function renderChats() {
    if (!authed()) {
      paint('<div class="adv-empty"><p>Sign in to see your chats.</p>' +
        '<a class="adv-btn is-gold" href="' + esc(signinHref('#chats')) + '">Sign in</a></div>');
      return;
    }
    loading();
    api('/advisors/chats').then(function (d) {
      paintUnread(d.unread);
      var expert = d.as_expert !== null;
      var inbox = expert && state.inbox;
      var rows = inbox ? d.as_expert : d.as_seeker;
      var waiting = expert ? d.as_expert.reduce(function (n, c) { return n + c.unread; }, 0) : 0;
      paint(
        (expert ? '<div class="adv-seg" role="tablist">' +
          '<a href="#chats" role="tab" aria-selected="' + !inbox + '">Questions I asked</a>' +
          '<a href="#inbox" role="tab" aria-selected="' + inbox + '">People asking me' +
            (waiting ? ' <span class="adv-badge">' + waiting + '</span>' : '') + '</a>' +
        '</div>' : '') +
        (inbox ? acceptingBar(d.expert) : '') +
        (rows.length ? '<ul class="adv-list">' + rows.map(function (c) { return chatRow(c, inbox); }).join('') + '</ul>'
          : '<div class="adv-empty"><p>' + (inbox
              ? (d.expert.status === 'approved' ? 'Nobody has written to you yet.'
                : 'Your profile is not listed yet, so nobody can write to you. <a href="#join">See where it stands →</a>')
              : 'You have not started a chat yet. <a href="#">Find someone to talk to →</a>') + '</p></div>')
      );
      wireAccepting();
    }).catch(function (e) { failed(e, renderChats); });
  }

  function acceptingBar(x) {
    if (!x || x.status !== 'approved') return '';
    return '<label class="adv-toggle"><input type="checkbox" id="adv-accepting"' + (x.accepting ? ' checked' : '') + '>' +
      '<span>Taking new chats</span></label>';
  }
  function wireAccepting() {
    var t = $('#adv-accepting');
    if (!t) return;
    t.addEventListener('change', function () {
      t.disabled = true;
      send('/advisors/me/accepting', 'POST', { on: t.checked })
        .catch(function () { t.checked = !t.checked; })
        .then(function () { t.disabled = false; state.me = null; });
    });
  }

  function chatRow(c, inbox) {
    var who = { display_name: c['with'], registered: !inbox && c.expert_kind !== 'educator', online: c.online };
    var from = c.preview_from === (inbox ? 'expert' : 'seeker') ? 'You: ' : '';
    return '<li><a class="adv-row' + (c.unread ? ' is-unread' : '') + '" href="#chat/' + c.id + '">' + mono(who) +
      '<span class="adv-rowmain"><b>' + esc(c['with']) + '</b>' +
        '<span class="adv-rowtopic">' + esc(c.topic_label) + (c.status === 'closed' ? ' · closed' : '') + '</span>' +
        '<span class="adv-rowprev">' + esc(from + c.preview) + '</span></span>' +
      '<span class="adv-rowside"><time>' + esc(ago(c.last_message_at)) + '</time>' +
        (c.unread ? '<span class="adv-badge">' + c.unread + '</span>' : '') + '</span></a></li>';
  }

  /* ── One conversation ────────────────────────────────────────────────── */

  var poll = { timer: null, busy: false, lastNew: 0 };
  // A separator that disappears when the line wraps on a phone, rather than
  // starting the next line with a stray dot.
  var SEP = '<i class="adv-sep" aria-hidden="true">·</i>';

  function stopPoll() { clearTimeout(poll.timer); poll.timer = null; }
  function schedule() {
    clearTimeout(poll.timer);
    if (!state.chat || document.hidden) return;
    var quiet = Date.now() - poll.lastNew;
    var wait = quiet < 60000 ? 4000 : quiet < 300000 ? 10000 : 20000;
    poll.timer = setTimeout(tick, wait * POLL_SCALE);
  }
  function tick() {
    var c = state.chat;
    if (!c || poll.busy) return schedule();
    poll.busy = true;
    api('/advisors/chats/' + c.id + '?after=' + c.lastId).then(function (d) {
      if (state.chat === c) apply(d);
    }).catch(function () {}).then(function () { poll.busy = false; schedule(); });
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && state.chat) tick();
  });

  function renderChat(id) {
    if (!authed()) {
      paint('<div class="adv-empty"><p>Sign in to read this chat.</p>' +
        '<a class="adv-btn is-gold" href="' + esc(signinHref('#chat/' + id)) + '">Sign in</a></div>');
      return;
    }
    loading();
    api('/advisors/chats/' + id).then(function (d) {
      var c = state.chat = { id: d.id, role: d.role, lastId: 0, seen: {}, lastDay: '', data: d };
      poll.lastNew = Date.now();
      var e = d.expert;
      var title = d.role === 'seeker' ? e.display_name : d.seeker_name;
      paint(
        '<div class="adv-chat' + (d.role === 'expert' && d.share_portfolio ? ' has-side' : '') + '" id="adv-chat">' +
          '<header class="adv-chathead">' +
            '<a class="adv-back" href="' + (d.role === 'expert' ? '#inbox' : '#chats') + '" aria-label="Back to chats">←</a>' +
            mono(d.role === 'seeker' ? e : { display_name: d.seeker_name }) +
            '<div class="adv-chatwho"><h1>' + esc(title) + '</h1>' +
              '<p>' + (d.role === 'seeker' ? kindLine(e) + SEP : '') + '<span>' + esc(d.topic_label) + '</span>' +
              (d.role === 'seeker' ? SEP + presence(e) : '') + '</p></div>' +
            '<details class="adv-more"><summary aria-label="More actions">⋯</summary><div id="adv-actions"></div></details>' +
          '</header>' +
          '<p class="adv-banner" id="adv-banner">' + banner(d) + '</p>' +
          '<div class="adv-sharebar" id="adv-sharebar"></div>' +
          '<div class="adv-thread" id="adv-thread" role="log" aria-label="Messages"></div>' +
          '<aside class="adv-side" id="adv-side"></aside>' +
          '<form class="adv-compose" id="adv-compose" novalidate></form>' +
        '</div>'
      );
      apply(d);
      wireComposer();
      schedule();
    }).catch(function (err) {
      if (err.status === 404) {
        paint('<div class="adv-empty"><p>That chat does not exist, or it is not yours.</p>' +
          '<a class="adv-btn" href="#chats">Your chats</a></div>');
      } else failed(err, function () { renderChat(id); });
    });
  }

  function banner(d) {
    var e = d.expert;
    if (d.role === 'expert') {
      return e.kind === 'educator'
        ? 'You are listed as an educator: buy or sell calls, targets and stop-losses cannot be sent from your side.'
        : 'Your obligations as a registered ' + (e.kind === 'ria' ? 'investment adviser' : 'research analyst') +
          ' apply in this chat, and it is kept as your record.';
    }
    if (e.kind === 'educator') {
      return esc(e.display_name) + ' is an educator, not SEBI-registered — they can teach and explain, not tell you what to buy or sell.';
    }
    if (e.kind === 'ra') {
      return esc(e.display_name) + ' is a SEBI-registered research analyst (' + esc(e.sebi_reg) +
        '). For advice on your whole portfolio, talk to a registered investment adviser.';
    }
    return esc(e.display_name) + ' is a SEBI-registered investment adviser (' + esc(e.sebi_reg) +
      '). Advice here is theirs, under their registration — not Altaha’s.';
  }

  /* Everything a poll can change, applied in place: new messages, the other
     side's read pointer, closing, sharing, and what has been shared. */
  function apply(d) {
    var c = state.chat;
    c.data = d;
    var thread = $('#adv-thread');
    if (!thread) return;
    var nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
    var added = 0;
    d.messages.forEach(function (m) {
      if (c.seen[m.id]) return;
      c.seen[m.id] = true;
      c.lastId = Math.max(c.lastId, m.id);
      var dd = day(m.created_at);
      if (dd !== c.lastDay) {
        c.lastDay = dd;
        thread.insertAdjacentHTML('beforeend', '<p class="adv-day">' + esc(dd) + '</p>');
      }
      thread.insertAdjacentHTML('beforeend', bubble(m, c.role));
      added++;
    });
    if (added) poll.lastNew = Date.now();
    if (!thread.children.length) thread.innerHTML = '<p class="adv-day">No messages yet.</p>';
    if (added && (nearBottom || thread.dataset.ready !== '1')) thread.scrollTop = thread.scrollHeight;
    thread.dataset.ready = '1';
    paintSeen(d.their_read_id);
    paintActions(d);
    paintShare(d);
    paintSide(d);
    paintComposer(d);
  }

  function bubble(m, role) {
    if (m.sender === 'system') return '<p class="adv-sys" data-id="' + m.id + '">' + esc(m.body) + '</p>';
    var mine = m.sender === role;
    return '<div class="adv-bubble' + (mine ? ' is-mine' : '') + '" data-id="' + m.id + '">' +
      '<p>' + esc(m.body) + '</p><time>' + esc(clock(m.created_at)) + '</time></div>';
  }

  function paintSeen(readId) {
    var old = $('#adv-thread .adv-seen');
    if (old) old.remove();
    var mine = document.querySelectorAll('#adv-thread .adv-bubble.is-mine');
    var last = mine[mine.length - 1];
    if (last && readId >= +last.dataset.id) last.insertAdjacentHTML('beforeend', '<span class="adv-seen">Seen</span>');
  }

  function paintActions(d) {
    var box = $('#adv-actions');
    if (!box) return;
    var html = '';
    if (d.status === 'open') html += '<button type="button" data-act="close">Close this chat</button>';
    if (d.role === 'expert' && !d.blocked) html += '<button type="button" data-act="block">Close and block ' + esc(d.seeker_name) + '</button>';
    html += '<form id="adv-report"><label>Report this chat to Altaha<textarea rows="2" maxlength="500" ' +
      'placeholder="What happened?"></textarea></label><button type="submit">Send report</button><p role="status"></p></form>';
    if (box.dataset.sig === html) return;
    box.dataset.sig = html;
    box.innerHTML = html;
    box.querySelectorAll('button[data-act]').forEach(function (b) {
      b.addEventListener('click', function () {
        var block = b.dataset.act === 'block';
        if (!window.confirm(block ? 'Close this chat and stop ' + d.seeker_name + ' writing to you again?'
          : 'Close this chat? Neither of you can send more messages in it.')) return;
        send('/advisors/chats/' + d.id + '/close', 'POST', { block: block }).then(function (v) {
          if (state.chat && state.chat.id === d.id) apply(v);
          $('.adv-more').open = false;
        }).catch(function (e) { window.alert(e.message); });
      });
    });
    $('#adv-report').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var f = ev.target, out = f.querySelector('p');
      send('/advisors/chats/' + d.id + '/report', 'POST', { reason: f.querySelector('textarea').value })
        .then(function () {
          out.textContent = 'Reported. The owner of Altaha will read this chat.';
          f.querySelector('textarea').value = '';
          track('advisor_chat_reported', { role: d.role });
        })
        .catch(function (e) { out.textContent = e.message; });
    });
  }

  function paintShare(d) {
    var bar = $('#adv-sharebar');
    if (!bar) return;
    if (d.role !== 'seeker' || !d.expert.can_see_portfolio || d.read_only) { bar.innerHTML = ''; return; }
    var sig = 's' + d.share_portfolio;
    if (bar.dataset.sig === sig) return;
    bar.dataset.sig = sig;
    bar.innerHTML = '<label class="adv-toggle"><input type="checkbox" id="adv-share-live"' + (d.share_portfolio ? ' checked' : '') + '>' +
      '<span>' + (d.share_portfolio ? esc(d.expert.display_name) + ' can see your saved portfolio and risk profile'
        : 'Let ' + esc(d.expert.display_name) + ' see your saved portfolio and risk profile') + '</span></label>';
    $('#adv-share-live').addEventListener('change', function (ev) {
      ev.target.disabled = true;
      send('/advisors/chats/' + d.id + '/share', 'POST', { share: ev.target.checked }).then(function (v) {
        if (state.chat && state.chat.id === d.id) apply(v);
      }).catch(function (e) { ev.target.checked = !ev.target.checked; ev.target.disabled = false; window.alert(e.message); });
    });
  }

  function paintSide(d) {
    var side = $('#adv-side'), chat = $('#adv-chat');
    if (!side) return;
    var shared = d.role === 'expert' && d.shared;
    chat.classList.toggle('has-side', !!shared);
    if (!shared) { side.innerHTML = ''; side.dataset.sig = ''; return; }
    var sig = JSON.stringify(shared);
    if (side.dataset.sig === sig) return;
    side.dataset.sig = sig;
    var r = shared.risk_profile, h = shared.holdings;
    side.innerHTML = '<h2>Shared by ' + esc(d.seeker_name) + '</h2>' +
      (r ? '<p class="adv-risk"><b>' + esc(r.band) + '</b> risk profile · score ' + esc(Math.round(r.score)) +
        '<br><span class="adv-muted">capacity ' + esc(Math.round(r.capacity)) + ', tolerance ' + esc(Math.round(r.tolerance)) +
        ' · assessed ' + esc(day(r.assessed_at)) + '</span></p>'
        : '<p class="adv-muted">No risk profile on their account.</p>') +
      (h.length ? '<table class="adv-holdings"><thead><tr><th>Stock</th><th>Qty</th><th>Avg ₹</th></tr></thead><tbody>' +
        h.map(function (x) {
          return '<tr><td><a href="stock.html?ticker=' + encodeURIComponent(x.symbol) + '" target="_blank" rel="noopener">' +
            esc(x.symbol) + '</a></td><td>' + esc(+x.qty) + '</td><td>' +
            (x.avg_price == null ? '—' : esc((+x.avg_price).toLocaleString('en-IN', { maximumFractionDigits: 2 }))) + '</td></tr>';
        }).join('') + '</tbody></table>'
        : '<p class="adv-muted">No portfolio saved to their account.</p>') +
      '<p class="adv-fine">Shown live while they keep sharing. They can stop at any time.</p>';
  }

  function paintComposer(d) {
    var form = $('#adv-compose');
    if (!form) return;
    var sig = d.read_only ? 'ro' + d.status : 'rw';
    if (form.dataset.sig === sig) return;
    form.dataset.sig = sig;
    if (d.read_only) {
      form.innerHTML = '<p class="adv-closed">' + (d.status === 'closed'
        ? 'This chat is closed.' + (d.role === 'seeker' && !d.blocked
          ? ' <a href="#a/' + esc(d.expert.slug) + '">Start a new one</a>' : '')
        : 'This person is no longer listed, so the chat is read-only.') + '</p>';
      return;
    }
    form.innerHTML =
      '<label class="adv-sr" for="adv-input">Message</label>' +
      '<textarea id="adv-input" rows="1" maxlength="2000" placeholder="Write a message"></textarea>' +
      '<button class="adv-btn is-gold" type="submit" id="adv-send">Send</button>' +
      '<div class="adv-refused" id="adv-refused" hidden></div>' +
      '<p class="adv-fine">Phone numbers, UPI IDs, emails and WhatsApp or Telegram links cannot be sent. Never pay anyone or share an OTP.</p>';
  }

  function wireComposer() {
    var form = $('#adv-compose');
    form.addEventListener('input', function (ev) {
      if (ev.target.id !== 'adv-input') return;
      ev.target.style.height = 'auto';
      ev.target.style.height = Math.min(ev.target.scrollHeight, 180) + 'px';
    });
    form.addEventListener('keydown', function (ev) {
      // Enter sends on a keyboard; on a phone the return key is a new line.
      if (ev.target.id === 'adv-input' && ev.key === 'Enter' && !ev.shiftKey &&
          !(window.matchMedia && matchMedia('(pointer:coarse)').matches)) {
        ev.preventDefault();
        form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    });
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var c = state.chat, input = $('#adv-input'), btn = $('#adv-send'), refused = $('#adv-refused');
      if (!c || !input || btn.disabled) return;
      var body = input.value.trim();
      if (!body) return;
      btn.disabled = true;
      refused.hidden = true;
      send('/advisors/chats/' + c.id + '/messages', 'POST', { body: body }).then(function (r) {
        input.value = '';
        input.style.height = 'auto';
        track('advisor_message_sent', { role: c.role });
        if (state.chat === c) {
          var d = Object.assign({}, c.data, { messages: [r.message] });
          apply(d);
          $('#adv-thread').scrollTop = $('#adv-thread').scrollHeight;
        }
      }).catch(function (e) {
        refused.hidden = false;
        refused.innerHTML = '<p>' + esc(e.message) + '</p>' +
          (e.sentence ? '<blockquote>' + esc(e.sentence) + '</blockquote>' : '');
        if (e.status === 403) tick();
      }).then(function () { btn.disabled = false; input.focus(); });
    });
  }

  /* ── Joining, and managing a listing ─────────────────────────────────── */

  var STATUS_TEXT = {
    pending: ['Being checked', 'Altaha checks your registration number against SEBI’s register before listing you. This usually takes a day or two; you will see the result here.'],
    approved: ['Listed', 'Readers can find you and start chats.'],
    rejected: ['Not listed', 'Your application was not approved. Fix what the note below says and save again to be re-checked.'],
    suspended: ['Suspended', 'Your profile is hidden and your chats are read-only. Write to Altaha if you think this is wrong.']
  };

  function renderJoin() {
    loading();
    Promise.all([directory(), me(true)]).then(function (r) {
      var d = r[0], mine = r[1], x = mine && mine.expert;
      var intro =
        '<section class="adv-hero is-join">' +
          '<h1>Talk to investors who are <em>looking for you</em>.</h1>' +
          '<p class="adv-lede">List yourself on Altaha and readers can chat with you about their money. ' +
          'Free during the beta, for you and for them.</p>' +
        '</section>' +
        '<div class="adv-rules">' +
          '<div><h3>SEBI-registered investment adviser</h3><p>Your INA number is checked against SEBI’s register. ' +
            'You can take portfolio reviews, and readers can share their saved portfolio and risk profile with you.</p></div>' +
          '<div><h3>SEBI-registered research analyst</h3><p>Your INH number is checked. You can discuss stocks and research; ' +
            'advice on a reader’s whole portfolio is for investment advisers.</p></div>' +
          '<div><h3>Educator or well-known investor</h3><p>Not registered? You can still teach and share how you think. ' +
            'Buy or sell calls, targets and stop-losses cannot be sent from an educator’s side.</p></div>' +
        '</div>' +
        '<p class="adv-note">For everyone: no promises of returns, no payments, no moving readers to WhatsApp, Telegram or a phone. ' +
          'Messages that do are not sent. Chats are kept and cannot be deleted — a registered adviser needs that record, ' +
          'and so does anyone judging a report. No star ratings: SEBI’s advertising rules for advisers do not allow testimonials.</p>';
      if (authed() && !mine) {
        failed(new Error('Your profile could not be loaded just now.'), renderJoin);
        return;
      }
      if (!authed()) {
        paint(intro + '<div class="adv-empty"><p>Sign in with the email you want readers’ messages to reach you at.</p>' +
          '<a class="adv-btn is-gold" href="' + esc(signinHref('#join')) + '">Sign in to apply</a></div>');
        return;
      }
      var status = x ? STATUS_TEXT[x.status] || [x.status, ''] : null;
      paint(
        (x ? '' : intro) +
        (x ? '<section class="adv-status is-' + esc(x.status) + '">' +
          '<p class="adv-eyebrow">Your listing</p><h1>' + esc(status[0]) + '</h1><p>' + esc(status[1]) + '</p>' +
          (x.review_note ? '<p class="adv-reviewnote"><b>Note from Altaha:</b> ' + esc(x.review_note) + '</p>' : '') +
          (x.status === 'approved' ? '<div class="adv-statusrow">' + acceptingBar(x) +
            '<a class="adv-btn" href="#a/' + esc(x.slug) + '">See your public profile</a>' +
            '<a class="adv-btn" href="#inbox">People asking you</a></div>' : '') +
        '</section>' : '') +
        '<form class="adv-form" id="adv-join" novalidate>' +
          '<h2>' + (x ? 'Your profile' : 'Apply to be listed') + '</h2>' +
          joinFields(d, x) +
          '<button class="adv-btn is-gold is-wide" type="submit" id="adv-join-go">' + (x ? 'Save changes' : 'Send my application') + '</button>' +
          '<p class="adv-msg" id="adv-join-out" role="status"></p>' +
          (x && x.status === 'approved' ? '<p class="adv-fine">Changing your category or registration number takes your profile off the list until it is checked again.</p>' : '') +
        '</form>'
      );
      wireJoin(d);
      wireAccepting();
    }).catch(function (e) { failed(e, renderJoin); });
  }

  function joinFields(d, x) {
    x = x || {};
    var kind = x.kind || 'ria';
    var topics = (x.topics || []).map(function (t) { return t.id; });
    var links = (x.links || []).concat(['', '', '']).slice(0, 3);
    return '<fieldset class="adv-kinds"><legend>I am</legend>' +
        d.kinds.map(function (k) {
          return '<label class="adv-kindopt"><input type="radio" name="kind" value="' + esc(k.id) + '"' +
            (kind === k.id ? ' checked' : '') + '><span>' + esc(k.label) + '</span></label>';
        }).join('') +
      '</fieldset>' +
      '<label class="adv-field" id="adv-j-regfield">SEBI registration number' +
        '<input id="adv-j-reg" value="' + esc(x.sebi_reg || '') + '" placeholder="INA000012345" autocomplete="off" spellcheck="false"></label>' +
      '<label class="adv-field">Name readers will see<input id="adv-j-name" maxlength="60" value="' + esc(x.display_name || '') + '"></label>' +
      '<label class="adv-field">One line about what you do<input id="adv-j-head" maxlength="120" value="' + esc(x.headline || '') +
        '" placeholder="Fee-only adviser for salaried families"></label>' +
      '<label class="adv-field">About you<textarea id="adv-j-bio" rows="6" maxlength="2000" ' +
        'placeholder="Who you help, how you work, what you have done. At least a few sentences.">' + esc(x.bio || '') + '</textarea></label>' +
      '<fieldset class="adv-topicpick"><legend>People can ask me about</legend>' +
        d.topics.map(function (t) {
          return '<label data-kinds="' + esc(t.kinds.join(' ')) + '"><input type="checkbox" name="topic" value="' + esc(t.id) + '"' +
            (topics.indexOf(t.id) >= 0 ? ' checked' : '') + '><span>' + esc(t.label) + '</span></label>';
        }).join('') +
      '</fieldset>' +
      '<div class="adv-two">' +
        '<label class="adv-field">Languages you chat in<input id="adv-j-lang" value="' + esc((x.languages || ['English']).join(', ')) +
          '" placeholder="English, Hindi"></label>' +
        '<label class="adv-field">Years of experience<input id="adv-j-exp" type="number" min="0" max="60" inputmode="numeric" value="' +
          esc(x.experience_years == null ? '' : x.experience_years) + '"></label>' +
      '</div>' +
      '<fieldset class="adv-linkset"><legend>Public links <span class="adv-muted">— optional: website, X, YouTube, LinkedIn</span></legend>' +
        links.map(function (u, i) {
          return '<label class="adv-sr" for="adv-j-link' + i + '">Link ' + (i + 1) + '</label>' +
            '<input id="adv-j-link' + i + '" type="url" value="' + esc(u) + '" placeholder="https://">';
        }).join('') +
      '</fieldset>';
  }

  function wireJoin() {
    var form = $('#adv-join');
    if (!form) return;
    function sync() {
      var kind = (form.querySelector('input[name="kind"]:checked') || {}).value;
      $('#adv-j-regfield').hidden = kind === 'educator';
      $('#adv-j-reg').placeholder = kind === 'ra' ? 'INH000012345' : 'INA000012345';
      form.querySelectorAll('.adv-topicpick label').forEach(function (l) {
        var ok = l.dataset.kinds.split(' ').indexOf(kind) >= 0;
        var box = l.querySelector('input');
        box.disabled = !ok;
        if (!ok) box.checked = false;
        l.classList.toggle('is-off', !ok);
      });
    }
    form.addEventListener('change', function (ev) { if (ev.target.name === 'kind') sync(); });
    sync();
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var out = $('#adv-join-out'), go = $('#adv-join-go');
      var kind = (form.querySelector('input[name="kind"]:checked') || {}).value;
      var body = {
        kind: kind,
        sebi_reg: kind === 'educator' ? '' : $('#adv-j-reg').value,
        display_name: $('#adv-j-name').value, headline: $('#adv-j-head').value, bio: $('#adv-j-bio').value,
        topics: Array.prototype.map.call(form.querySelectorAll('input[name="topic"]:checked'), function (b) { return b.value; }),
        languages: $('#adv-j-lang').value.split(',').map(function (x) { return x.trim(); }).filter(Boolean),
        experience_years: $('#adv-j-exp').value,
        links: [0, 1, 2].map(function (i) { return $('#adv-j-link' + i).value.trim(); }).filter(Boolean)
      };
      out.textContent = ''; out.className = 'adv-msg';
      go.disabled = true;
      send('/advisors/me/profile', 'PUT', body).then(function (r) {
        track('advisor_profile_saved', { kind: kind, status: r.expert.status });
        state.me = null;
        renderJoin();
      }).catch(function (e) {
        go.disabled = false;
        out.textContent = e.message; out.className = 'adv-msg is-err';
      });
    });
  }

  /* ── The owner's review queue ────────────────────────────────────────── */

  function adminKey() { try { return sessionStorage.getItem(ADMIN_KEY) || ''; } catch (e) { return ''; } }
  function adminFetch(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ 'X-Admin-Key': adminKey() }, opts.body ? { 'Content-Type': 'application/json' } : {});
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw Object.assign(new Error(typeof d.detail === 'string' ? d.detail : 'Request failed'), { status: r.status });
        return d;
      });
    });
  }

  function renderAdmin(filter) {
    if (!adminKey()) {
      paint('<form class="adv-form" id="adv-key"><h2>Review advisers</h2>' +
        '<label class="adv-field">Admin key<input id="adv-key-in" type="password" autocomplete="off"></label>' +
        '<button class="adv-btn is-gold" type="submit">Open</button>' +
        '<p class="adv-fine">Kept in this tab only, and forgotten when it closes.</p></form>');
      $('#adv-key').addEventListener('submit', function (ev) {
        ev.preventDefault();
        try { sessionStorage.setItem(ADMIN_KEY, $('#adv-key-in').value.trim()); } catch (e) {}
        renderAdmin();
      });
      return;
    }
    loading();
    Promise.all([adminFetch('/admin/advisors' + (filter ? '?status=' + filter : '')), adminFetch('/admin/advisors/reports')])
      .then(function (r) {
        var d = r[0], reports = r[1].reports;
        paint('<section class="adv-admin"><h1>Advisers</h1>' +
          '<p class="adv-muted">' + d.chats + ' chats · ' + d.messages + ' messages · ' + d.open_reports + ' reports</p>' +
          '<div class="adv-chips">' + ['', 'pending', 'approved', 'rejected', 'suspended'].map(function (s) {
            return '<button type="button" class="adv-chip" data-status="' + s + '" aria-pressed="' + ((filter || '') === s) + '">' +
              (s ? esc(s) + ' (' + d.counts[s] + ')' : 'All') + '</button>';
          }).join('') + '</div>' +
          (d.experts.length ? d.experts.map(adminCard).join('') : '<p class="adv-empty">Nobody here.</p>') +
          '<h2>Reports</h2>' + (reports.length ? reports.map(reportCard).join('') : '<p class="adv-muted">No reports.</p>') +
          '<p><button class="adv-btn" type="button" id="adv-forget">Forget the key</button></p></section>');
        view.querySelectorAll('[data-status]').forEach(function (b) {
          b.addEventListener('click', function () { renderAdmin(b.dataset.status); });
        });
        view.querySelectorAll('[data-review]').forEach(function (b) {
          b.addEventListener('click', function () {
            var box = b.closest('.adv-admincard');
            b.disabled = true;
            adminFetch('/admin/advisors/review', { method: 'POST', body: JSON.stringify({
              expert_id: +box.dataset.id, action: b.dataset.review, note: box.querySelector('textarea').value
            }) }).then(function () { state.dir = null; renderAdmin(filter); })
              .catch(function (e) { b.disabled = false; window.alert(e.message); });
          });
        });
        $('#adv-forget').addEventListener('click', function () {
          try { sessionStorage.removeItem(ADMIN_KEY); } catch (e) {}
          renderAdmin();
        });
      }).catch(function (e) {
        if (e.status === 401) { try { sessionStorage.removeItem(ADMIN_KEY); } catch (x) {} }
        failed(e, function () { renderAdmin(filter); });
      });
  }

  function adminCard(x) {
    return '<article class="adv-admincard is-' + esc(x.status) + '" data-id="' + x.id + '">' +
      '<header><b>' + esc(x.display_name) + '</b> <span class="adv-kind is-' + esc(x.kind) + '">' + esc(x.kind_short) + '</span> ' +
        '<span class="adv-pill">' + esc(x.status) + (x.featured ? ' · featured' : '') + '</span></header>' +
      '<p class="adv-muted">' + esc(x.email) + ' · applied ' + esc(day(x.created_at)) + '</p>' +
      (x.sebi_reg ? '<p>Registration <b class="adv-reg">' + esc(x.sebi_reg) + '</b> — <a href="' + esc(x.register_url) +
        '" target="_blank" rel="noopener noreferrer">open SEBI’s register ↗</a> and search for this number before approving.</p>'
        : '<p>Educator — no registration to check. Make sure the profile does not claim one.</p>') +
      '<p><b>' + esc(x.headline) + '</b></p><div class="adv-bio">' + esc(x.bio) + '</div>' +
      '<p class="adv-muted">Topics: ' + esc(x.topics.map(function (t) { return t.label; }).join(', ')) +
        ' · Languages: ' + esc(x.languages.join(', ')) + (x.links.length ? ' · ' + esc(x.links.join(' ')) : '') + '</p>' +
      '<label class="adv-field">Note to the applicant (shown to them)<textarea rows="2">' + esc(x.review_note || '') + '</textarea></label>' +
      '<div class="adv-actions">' +
        (x.status !== 'approved' ? '<button class="adv-btn is-gold" type="button" data-review="approve">Approve</button>' : '') +
        (x.status === 'pending' ? '<button class="adv-btn" type="button" data-review="reject">Reject</button>' : '') +
        (x.status === 'approved' ? '<button class="adv-btn" type="button" data-review="suspend">Suspend</button>' : '') +
        '<button class="adv-btn" type="button" data-review="' + (x.featured ? 'unfeature">Unfeature' : 'feature">Feature') + '</button>' +
      '</div></article>';
  }

  function reportCard(r) {
    return '<article class="adv-admincard"><header><b>Chat ' + r.chat_id + '</b> — reported by the ' +
      esc(r.reporter === 'seeker' ? 'reader (' + r.seeker_name + ')' : 'adviser') + ' about ' + esc(r.expert.display_name) +
      ' <span class="adv-pill">' + esc(r.expert.status) + '</span></header>' +
      '<p><b>Reason:</b> ' + esc(r.reason) + '</p>' +
      '<div class="adv-transcript">' + r.messages.map(function (m) {
        return '<p><b>' + esc(m.sender) + '</b> <time>' + esc(day(m.created_at) + ' ' + clock(m.created_at)) + '</time><br>' + esc(m.body) + '</p>';
      }).join('') + '</div></article>';
  }

  /* ── Start ───────────────────────────────────────────────────────────── */

  window.addEventListener('hashchange', route);
  var wasAuthed = authed();
  window.addEventListener('altaha-auth', function () {
    // Signed in or out in another tab, or the session expired: whatever is
    // on screen may now be wrong, so draw it again. auth.js also announces
    // on every page load, which changes nothing and redraws nothing.
    if (authed() === wasAuthed) return;
    wasAuthed = authed();
    state.me = null;
    route();
  });
  route();
})();
