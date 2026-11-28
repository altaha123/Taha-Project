/* Altaha — Connect your broker: the order ticket, and the Trade button on
   the stock page. The rules live in backend/brokers.py; the member's own
   page is broker-page.js.

   WHAT THE TICKET TAKES FROM ALTAHA: THE STOCK, AND NOTHING ELSE
   The member types the quantity and the price. The limit price starts at the
   last price shown on the page, because that is the market, not an opinion;
   no score, level, target or pick ever fills a field here. A Buy button
   pre-filled from Altaha's research would be a recommendation to trade, which
   needs a SEBI registration this site does not have (README.md).

   TWO STEPS, ONE NAME
   Review shows the order in words before anything is sent. The order is named
   (client_ref) when Review is pressed, so a double tap on Place, a retry after
   a dropped connection or a second tab sends it once; the server keeps the
   first and returns it. Editing the order makes a new name.

   A BUTTON THAT CANNOT WORK IS NOT SHOWN
   The Trade button appears only when the server says connections are switched
   on, and only for a company listed in India. */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : 'https://taha-project.onrender.com';
  var RETURN_KEY = 'altaha-broker-return';
  var cfg = null, cfgAsked = null;

  /* ── Small things ────────────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function track(name, props) { if (window.AltahaTrack) window.AltahaTrack(name, props || {}); }
  function authed() { return !!(window.AltahaAuth && window.AltahaAuth.authed && window.AltahaAuth.authed()); }
  function rupees(n, dp) {
    if (n == null || !isFinite(n)) return '—';
    dp = dp == null ? 2 : dp;
    return '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function newRef() {
    var a = new Uint8Array(12);
    try { crypto.getRandomValues(a); } catch (e) { for (var i = 0; i < a.length; i++) a[i] = Math.random() * 256; }
    return 'o-' + Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  /* One way to ask the API. A broker session that has ended comes back as
     409 {reconnect: true}; the error carries that so the caller can offer
     the login rather than a dead end. */
  function api(path, opts) {
    opts = opts || {};
    var run = authed() ? window.AltahaAuth.fetch(path, opts)
      : fetch(API + path, opts);
    return run.then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok) return d;
        var det = d && d.detail, msg = typeof det === 'string' ? det : (det && det.message) || '';
        var err = new Error(msg || (r.status === 401 ? 'Sign in to continue.' :
          'Something went wrong (' + r.status + '). Try again in a moment.'));
        err.status = r.status;
        err.reconnect = !!(det && det.reconnect);
        throw err;
      });
    }, function () {
      throw new Error('Could not reach Altaha. If the site has been idle, it takes about thirty seconds to wake.');
    });
  }
  function post(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                       body: JSON.stringify(body || {}) });
  }

  function config(force) {
    if (cfg && !force) return Promise.resolve(cfg);
    if (cfgAsked && !force) return cfgAsked;
    cfgAsked = api('/broker/config').then(function (d) { cfg = d; return d; })
      .catch(function () { cfg = null; cfgAsked = null; return null; });
    return cfgAsked;
  }

  /* The broker's login page. Where to come back to is kept for the broker
     page, which is where the broker sends the member afterwards. */
  function connect(broker, back) {
    try { sessionStorage.setItem(RETURN_KEY, back || location.href); } catch (e) {}
    track('broker_connect_started', { broker: broker });
    return post('/me/broker/connect', { broker: broker }).then(function (d) {
      location.href = d.login_url;
      return d;
    });
  }

  /* ── The ticket ──────────────────────────────────────────────────────── */

  var T = null;        // the open ticket's state

  function shell() {
    var host = document.getElementById('bk-ticket');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'bk-ticket';
    host.className = 'bk-scrim';
    host.hidden = true;
    host.innerHTML = '<div class="bk-sheet" role="dialog" aria-modal="true" aria-labelledby="bk-t-h">' +
      '<button type="button" class="bk-x" data-bk="close" aria-label="Close">×</button>' +
      '<div id="bk-t-body"></div></div>';
    document.body.appendChild(host);
    host.addEventListener('click', function (e) {
      if (e.target === host) close();
      var b = e.target.closest('[data-bk]');
      if (b) act(b.getAttribute('data-bk'), b);
    });
    host.addEventListener('input', onInput);
    host.addEventListener('change', onInput);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !host.hidden) close();
    });
    return host;
  }

  function open(stock) {
    var host = shell();
    T = { stock: stock, step: 'loading', link: null, funds: null, side: 'BUY', type: 'LIMIT',
          product: 'CNC', qty: '', price: stock.price ? String(Number(stock.price).toFixed(2)) : '',
          trigger: '', ref: null, order: null, err: '', busy: false, polls: 0 };
    host.hidden = false;
    document.documentElement.classList.add('bk-open');
    track('broker_ticket_opened', { symbol: stock.symbol });
    paint();
    if (!authed()) { T.step = 'signin'; paint(); return; }
    Promise.all([config(true), api('/me/broker')]).then(function (r) {
      cfg = r[0] || cfg;
      T.link = r[1].link;
      if (!T.link) T.step = 'connect';
      else if (T.link.expired) T.step = 'reconnect';
      else if (!cfg || !cfg.trading) T.step = 'off';
      else if (T.link.paused) T.step = 'paused';
      else {
        T.step = 'form';
        api('/me/broker/funds').then(function (d) { if (T) { T.funds = d.funds; paint(); } })
          .catch(function (e) { if (T && e.reconnect) { T.step = 'reconnect'; paint(); } });
      }
      paint();
    }).catch(function (e) {
      T.step = e.status === 403 ? 'closed' : 'error';
      T.err = e.message;
      paint();
    });
  }

  function close() {
    var host = document.getElementById('bk-ticket');
    if (host) host.hidden = true;
    document.documentElement.classList.remove('bk-open');
    if (T && T.timer) clearTimeout(T.timer);
    T = null;
  }

  function onInput(e) {
    if (!T) return;
    var n = e.target.name;
    if (!n) return;
    if (n === 'side' || n === 'type' || n === 'product') T[n] = e.target.value;
    else if (n === 'qty' || n === 'price' || n === 'trigger') T[n] = e.target.value;
    T.err = '';
    if (n === 'side' || n === 'type' || n === 'product') paint();
    else paintEstimate();
  }

  function value() {
    var q = Number(T.qty);
    var p = T.type === 'MARKET' ? Number(T.stock.price) :
            T.type === 'SL-M' ? Number(T.trigger) : Number(T.price);
    return q > 0 && p > 0 ? q * p : null;
  }

  function paintEstimate() {
    var el = document.getElementById('bk-est');
    if (!el) return;
    var v = value();
    el.textContent = v ? (T.type === 'MARKET' ? 'About ' : '') + rupees(v) : '—';
  }

  function seg(name, opts, cur) {
    return '<div class="bk-seg" role="radiogroup">' + opts.map(function (o) {
      return '<label class="bk-seg-o' + (o[0] === cur ? ' on' : '') + (name === 'side' ? ' is-' + o[0].toLowerCase() : '') + '">' +
        '<input type="radio" name="' + name + '" value="' + o[0] + '"' + (o[0] === cur ? ' checked' : '') + '>' +
        '<span>' + esc(o[1]) + '</span></label>';
    }).join('') + '</div>';
  }

  function head() {
    var s = T.stock;
    return '<p class="bk-eyebrow">' + (T.link ? esc(T.link.label) + ' · ' + esc(T.link.client_id) : 'Trade') + '</p>' +
      '<h2 class="bk-h" id="bk-t-h">' + esc(s.symbol) + (s.price ? ' <span class="bk-ltp">' + rupees(s.price) + '</span>' : '') + '</h2>' +
      (s.name ? '<p class="bk-sub">' + esc(s.name) + '</p>' : '');
  }

  function fine() {
    return '<p class="bk-fine">' + esc((cfg && cfg.disclaimer) ||
      'Orders go to your broker exactly as you enter them. Altaha does not advise on any order.') + '</p>';
  }

  function words() {
    var side = T.side === 'BUY' ? 'Buy' : 'Sell';
    var how = T.type === 'MARKET' ? 'at the market price' :
              T.type === 'LIMIT' ? 'at ' + rupees(Number(T.price)) + ' or better' :
              T.type === 'SL' ? 'at ' + rupees(Number(T.price)) + ' once the price reaches ' + rupees(Number(T.trigger)) :
              'at the market price once it reaches ' + rupees(Number(T.trigger));
    return side + ' ' + Number(T.qty).toLocaleString('en-IN') + ' share' + (Number(T.qty) === 1 ? '' : 's') +
      ' of ' + T.stock.symbol + ' ' + how + ', ' + (T.product === 'CNC' ? 'for delivery' : 'intraday') + '.';
  }

  var STATUS = {
    sending: ['Sending', ''], open: ['Open at the exchange', ''], part_filled: ['Partly filled', 'part'],
    filled: ['Filled', 'pass'], rejected: ['Rejected', 'fail'], cancelled: ['Cancelled', ''],
    expired: ['Expired', ''], unknown: ['Not confirmed', 'part']
  };

  function paint() {
    var body = document.getElementById('bk-t-body');
    if (!body || !T) return;
    var h = '';
    var brokerPage = 'broker.html';
    switch (T.step) {
      case 'loading':
        h = head() + '<p class="bk-wait">Checking your broker connection…</p>';
        break;
      case 'signin':
        h = head() + '<p class="bk-p">Sign in to Altaha, then connect your broker to place orders from this page.</p>' +
          '<a class="bk-btn is-gold" href="signin.html?next=broker.html">Sign in</a>';
        break;
      case 'reconnect':
        h = head() + '<p class="bk-p">Your ' + esc(T.link.label) + ' session has ended (' + esc(T.link.label) +
            ' ends it every day). Log in to ' + esc(T.link.label) + ' again to place orders.</p>' +
          '<button type="button" class="bk-btn is-gold" data-bk="connect" data-broker="' + esc(T.link.broker) + '">Log in to ' + esc(T.link.label) + '</button>' +
          '<p class="bk-err" id="bk-err">' + esc(T.err) + '</p>';
        break;
      case 'connect':
        var open = ((cfg && cfg.brokers) || []).filter(function (b) { return b.available && b.allowed !== false; });
        h = head() + '<p class="bk-p">' + (open.length
            ? 'Connect your broker to place orders from Altaha. You log in on your broker\'s own page; Altaha never sees your password or PIN.'
            : 'Broker connections are open to a few members while they are tested.') + '</p>' +
          '<div class="bk-acts">' + open.map(function (b) {
            return '<button type="button" class="bk-btn is-gold" data-bk="connect" data-broker="' + esc(b.id) + '">Connect ' + esc(b.label) + '</button>';
          }).join('') + '</div>' +
          '<p class="bk-err" id="bk-err">' + esc(T.err) + '</p>';
        break;
      case 'off':
        h = head() + '<p class="bk-p">Your ' + esc(T.link.label) + ' account is connected. Placing orders from Altaha is not switched on yet; ' +
          'you can see your funds, holdings and orders on <a href="' + brokerPage + '">Your broker</a>.</p>';
        break;
      case 'paused':
        h = head() + '<p class="bk-p">You paused trading from Altaha. Resume it on <a href="' + brokerPage + '">Your broker</a>.</p>';
        break;
      case 'closed':
      case 'error':
        h = head() + '<p class="bk-p">' + esc(T.err || 'This is unavailable just now.') + '</p>';
        break;
      case 'form':
        h = head() +
          seg('side', [['BUY', 'Buy'], ['SELL', 'Sell']], T.side) +
          '<div class="bk-grid">' +
            '<label class="bk-f"><span>Quantity</span><input name="qty" inputmode="numeric" autocomplete="off" value="' + esc(T.qty) + '" placeholder="' + ((Number(T.stock.lot) || 1) > 1 ? 'Lots of ' + Number(T.stock.lot).toLocaleString('en-IN') : 'Shares') + '"></label>' +
            (T.type === 'LIMIT' || T.type === 'SL'
              ? '<label class="bk-f"><span>' + (T.type === 'SL' ? 'Limit price' : 'Price') + '</span><input name="price" inputmode="decimal" autocomplete="off" value="' + esc(T.price) + '"></label>' : '') +
            (T.type === 'SL' || T.type === 'SL-M'
              ? '<label class="bk-f"><span>Trigger price</span><input name="trigger" inputmode="decimal" autocomplete="off" value="' + esc(T.trigger) + '"></label>' : '') +
          '</div>' +
          '<div class="bk-row"><span class="bk-lbl">Order type</span>' +
            seg('type', [['LIMIT', 'Limit'], ['MARKET', 'Market'], ['SL', 'SL'], ['SL-M', 'SL-M']], T.type) + '</div>' +
          '<div class="bk-row"><span class="bk-lbl">Product</span>' +
            seg('product', [['CNC', 'Delivery'], ['INTRADAY', 'Intraday']], T.product) + '</div>' +
          '<dl class="bk-sum"><div><dt>Order value</dt><dd id="bk-est">—</dd></div>' +
            '<div><dt>Available in ' + esc(T.link.label) + '</dt><dd>' + (T.funds ? rupees(T.funds.available) : '…') + '</dd></div></dl>' +
          '<p class="bk-err" id="bk-err" role="alert">' + esc(T.err) + '</p>' +
          '<button type="button" class="bk-btn is-' + (T.side === 'BUY' ? 'buy' : 'sell') + ' is-wide" data-bk="review">Review order</button>' +
          fine();
        break;
      case 'review':
        h = head() +
          '<div class="bk-review"><p class="bk-words">' + esc(words()) + '</p>' +
          '<dl class="bk-sum"><div><dt>Order value</dt><dd>' + (T.type === 'MARKET' ? 'About ' : '') + rupees(value()) + '</dd></div>' +
          '<div><dt>Account</dt><dd>' + esc(T.link.label) + ' ' + esc(T.link.client_id) + '</dd></div></dl></div>' +
          '<p class="bk-err" id="bk-err" role="alert">' + esc(T.err) + '</p>' +
          '<div class="bk-acts"><button type="button" class="bk-btn" data-bk="edit">Edit</button>' +
          '<button type="button" class="bk-btn is-' + (T.side === 'BUY' ? 'buy' : 'sell') + '" data-bk="place"' + (T.busy ? ' disabled' : '') + '>' +
            (T.busy ? 'Sending…' : 'Place ' + (T.side === 'BUY' ? 'buy' : 'sell') + ' order') + '</button></div>' +
          fine();
        break;
      case 'done':
        var o = T.order || {}, st = STATUS[o.status] || [o.status, ''];
        h = head() +
          '<div class="bk-done"><p class="bk-words">' + esc(words()) + '</p>' +
          '<p class="bk-status is-' + st[1] + '"><b>' + esc(st[0]) + '</b>' +
            (o.status === 'filled' && o.avg_price ? ' at ' + rupees(o.avg_price) : '') +
            (o.status === 'part_filled' && o.filled_qty ? ' — ' + o.filled_qty + ' of ' + o.qty : '') + '</p>' +
          (o.message ? '<p class="bk-p">' + esc(o.message) + '</p>' : '') +
          (o.broker_order_id ? '<p class="bk-fine">' + esc(T.link.label) + ' order ' + esc(o.broker_order_id) + '. It is in your ' + esc(T.link.label) + ' app too.</p>' : '') +
          '</div>' +
          '<div class="bk-acts"><a class="bk-btn" href="' + brokerPage + '">Today\'s orders</a>' +
          '<button type="button" class="bk-btn is-gold" data-bk="another">New order</button></div>';
        break;
    }
    body.innerHTML = h;
    paintEstimate();
    var first = body.querySelector('input[name="qty"]');
    if (first && T.step === 'form' && !T.qty) { try { first.focus(); } catch (e) {} }
  }

  function check() {
    var q = Number(T.qty);
    if (!(q >= 1) || Math.floor(q) !== q) return 'Enter a whole number of shares.';
    // An SME share trades only in the exchange's lot. The server refuses any
    // other quantity too; this says so before the order is sent.
    var lot = Number(T.stock.lot) || 1;
    if (lot > 1 && q % lot) return 'This stock trades in lots of ' + lot.toLocaleString('en-IN') +
      ' shares. Choose a multiple of ' + lot.toLocaleString('en-IN') + '.';
    if ((T.type === 'LIMIT' || T.type === 'SL') && !(Number(T.price) > 0)) return 'Enter the price.';
    if ((T.type === 'SL' || T.type === 'SL-M') && !(Number(T.trigger) > 0)) return 'Enter the trigger price.';
    if (T.type === 'MARKET' && !(Number(T.stock.price) > 0)) return 'The price is not loaded yet. Use a limit order.';
    var lim = cfg && cfg.limits && cfg.limits.max_order_value, v = value();
    if (lim && v && v > lim) return 'Orders here are limited to ' + rupees(lim, 0) + ' each.';
    return '';
  }

  function act(what, el) {
    if (!T) return;
    if (what === 'close') return close();
    if (what === 'connect') {
      connect(el && el.getAttribute('data-broker')).catch(function (e) { T.err = e.message; paint(); });
      return;
    }
    if (what === 'review') {
      T.err = check();
      if (T.err) { paint(); return; }
      T.ref = newRef();             // this order's one name, until it is edited
      T.step = 'review';
      paint();
      return;
    }
    if (what === 'edit') { T.step = 'form'; T.ref = null; T.err = ''; paint(); return; }
    if (what === 'another') { T.step = 'form'; T.ref = null; T.order = null; T.qty = ''; paint(); return; }
    if (what === 'place') {
      if (T.busy) return;
      T.busy = true; T.err = ''; paint();
      var body = { symbol: T.stock.symbol, side: T.side, qty: Number(T.qty), type: T.type,
                   product: T.product, validity: 'DAY', client_ref: T.ref, ref_price: T.stock.price || null,
                   source: T.stock.source || 'stock' };
      if (T.type === 'LIMIT' || T.type === 'SL') body.price = Number(T.price);
      if (T.type === 'SL' || T.type === 'SL-M') body.trigger = Number(T.trigger);
      post('/me/broker/orders', body).then(function (d) {
        if (!T) return;
        T.busy = false; T.order = d.order; T.step = 'done';
        track('broker_order_placed', { status: d.order && d.order.status, side: T.side, type: T.type });
        paint();
        follow();
      }).catch(function (e) {
        if (!T) return;
        T.busy = false;
        if (e.reconnect) { T.step = 'reconnect'; T.err = ''; }
        T.err = e.message;
        paint();
      });
    }
  }

  /* An open order is asked about for a minute, then left to Today's orders. */
  function follow() {
    if (!T || !T.order || !T.order.id) return;
    var s = T.order.status;
    if (s !== 'sending' && s !== 'open' && s !== 'part_filled' && s !== 'unknown') return;
    if (T.polls++ > 20) return;
    T.timer = setTimeout(function () {
      if (!T || !T.order) return;
      api('/me/broker/orders/' + T.order.id).then(function (d) {
        if (!T || !T.order || d.order.id !== T.order.id) return;
        T.order = d.order;
        if (T.step === 'done') paint();
        follow();
      }).catch(function () { follow(); });
    }, T.polls < 5 ? 2000 : 4000);
  }

  /* ── The stock page ──────────────────────────────────────────────────── */

  function addTradeButton(d) {
    var px = document.querySelector('.stk-px');
    if (!px || document.getElementById('bk-trade')) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.id = 'bk-trade';
    b.className = 'bk-trade';
    b.textContent = 'Trade';
    b.setAttribute('aria-haspopup', 'dialog');
    b.addEventListener('click', function () {
      var price = d.price;
      var live = document.getElementById('px');
      var m = live && /([\d,]+\.?\d*)/.exec(live.textContent || '');
      if (m) { var n = Number(m[1].replace(/,/g, '')); if (n > 0) price = n; }
      open({ symbol: d.symbol, name: d.name, price: price, source: 'stock', lot: d.lot || 1 });
    });
    px.appendChild(b);
  }

  window.addEventListener('altaha-stock', function (e) {
    var d = e.detail || {};
    if (!d.symbol || (d.exchange !== 'NSE' && d.currency !== 'INR')) return;
    config().then(function (c) { if (c && c.connect) addTradeButton(d); });
  });

  window.AltahaBroker = { api: api, post: post, config: config, connect: connect, open: open,
                          close: close, rupees: rupees, esc: esc, RETURN_KEY: RETURN_KEY };
})();
