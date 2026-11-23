/* Altaha — Your broker (broker.html): connect a broker account, see its
   funds, today's orders, positions and holdings, cancel an open order, copy
   the holdings into the Altaha portfolio, pause trading, disconnect.

   COMING BACK FROM THE BROKER
   After the member logs in on Dhan's page, Dhan sends them here with a
   one-time tokenId, in the query string (?tokenId=) or, as Dhan's docs also
   allow, as the last part of the path (/broker/<tokenId>). It is handed to
   the server once and taken out of the address bar straight away, so a
   reload or a shared link never carries it. The server only accepts it for
   a login this member started here in the last fifteen minutes. */

(function () {
  'use strict';

  var B = window.AltahaBroker;
  var esc = B.esc, rupees = B.rupees;
  var view = document.getElementById('bk-view');
  var S = { cfg: null, link: null, msg: '', msgKind: '' };

  function say(m, kind) { S.msg = m || ''; S.msgKind = kind || ''; var n = document.getElementById('bk-msg'); if (n) { n.textContent = S.msg; n.className = 'bk-msg' + (kind ? ' is-' + kind : ''); } }
  function track(name, props) { if (window.AltahaTrack) window.AltahaTrack(name, props || {}); }

  function tokenFromAddress() {
    var t = '';
    try { t = new URLSearchParams(location.search).get('tokenId') || ''; } catch (e) {}
    if (!t) {
      var m = /\/broker\/([A-Za-z0-9._~-]{8,})\/?$/.exec(location.pathname);
      if (m) t = m[1];
    }
    return t;
  }
  function cleanAddress() {
    try {
      var p = /\/broker(\.html)?\//.test(location.pathname)
        ? location.pathname.replace(/\/broker(\.html)?\/.*$/, '/broker$1') : location.pathname;
      history.replaceState(history.state, '', p + location.hash);
    } catch (e) {}
  }

  function when(iso) {
    var t = Date.parse(iso || '');
    if (!isFinite(t)) return '';
    return new Date(t).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  }

  /* ── Not connected ───────────────────────────────────────────────────── */

  function paintIntro() {
    var c = S.cfg || {};
    var dhan = (c.brokers || []).filter(function (b) { return b.id === 'dhan'; })[0];
    var can = c.connect && dhan && dhan.available && c.allowed !== false;
    view.innerHTML =
      '<section class="bk-card bk-hero">' +
        '<h2>Connect your Dhan account</h2>' +
        '<ul class="bk-why">' +
          '<li><b>You log in on Dhan\'s own page.</b> Altaha never sees your password, PIN or OTP.</li>' +
          '<li><b>Orders land in your Dhan account.</b> They show up in the Dhan app like any other order.</li>' +
          '<li><b>Your holdings, funds and orders, here.</b> Copy your real holdings into your Altaha portfolio in one tap.</li>' +
          '<li><b>Disconnect any time.</b> Dhan also ends the session itself every day.</li>' +
        '</ul>' +
        (can ? '<button type="button" class="bk-btn is-gold" id="bk-connect">Connect Dhan</button>'
             : '<p class="bk-p">' + (!c.connect ? 'Broker connections are coming soon.'
                 : 'Broker connections are open to a few members while they are tested.') + '</p>') +
        '<p class="bk-msg" id="bk-msg" role="alert"></p>' +
        '<p class="bk-fine">More brokers will follow. Dhan comes first because Altaha\'s market data already runs on it.</p>' +
      '</section>';
    var b = document.getElementById('bk-connect');
    if (b) b.addEventListener('click', function () {
      b.disabled = true;
      B.connect('dhan', document.referrer && /altahascreener|localhost|127\.0\.0\.1/.test(document.referrer) ? document.referrer : '')
        .catch(function (e) { b.disabled = false; say(e.message, 'err'); });
    });
  }

  /* ── Connected ───────────────────────────────────────────────────────── */

  function paintLinked() {
    var L = S.link, c = S.cfg || {};
    var back = '';
    try { back = sessionStorage.getItem(B.RETURN_KEY) || ''; } catch (e) {}
    var backLink = /\/stock/.test(back) ? '<a class="bk-btn is-small" href="' + esc(back) + '">Back to the stock</a>' : '';
    view.innerHTML =
      '<section class="bk-card bk-acct">' +
        '<div class="bk-acct-id"><span class="bk-logo" aria-hidden="true">' + esc(L.label.charAt(0)) + '</span>' +
          '<div><b>' + esc(L.label) + (L.client_name ? ' · ' + esc(L.client_name) : '') + '</b>' +
          '<span>Client ' + esc(L.client_id) + ' · connected ' + esc(when(L.connected_at)) + '</span>' +
          '<span class="' + (L.expired ? 'is-fail' : '') + '">' + (L.expired ? 'Session ended. Log in to Dhan again.'
              : L.expires_at ? 'Dhan session ends ' + esc(when(L.expires_at)) : '') + '</span></div></div>' +
        '<div class="bk-acts">' + backLink +
          (L.expired ? '<button type="button" class="bk-btn is-gold is-small" data-a="reconnect">Log in to Dhan</button>' : '') +
          '<button type="button" class="bk-btn is-small" data-a="pause">' + (L.paused ? 'Resume trading' : 'Pause trading') + '</button>' +
          '<button type="button" class="bk-btn is-small" data-a="disconnect">Disconnect</button>' +
        '</div>' +
        '<p class="bk-msg" id="bk-msg" role="alert"></p>' +
      '</section>' +
      (!c.trading ? '<p class="bk-note">' + (c.halted ? 'Orders from Altaha are paused just now.' :
        'Placing orders from Altaha is not switched on yet.') + ' You can see your account here; place orders in the Dhan app.</p>'
        : L.paused ? '<p class="bk-note">You paused trading from Altaha. Orders cannot be placed here until you resume.</p>'
        : '<p class="bk-note">To place an order, open any stock and press <b>Trade</b> beside its price.</p>') +
      '<div class="bk-cols">' +
        '<section class="bk-card" id="bk-funds"><h3>Funds</h3><p class="bk-wait">Loading…</p></section>' +
        '<section class="bk-card bk-span" id="bk-orders"><h3>Today\'s orders</h3><p class="bk-wait">Loading…</p></section>' +
        '<section class="bk-card bk-span" id="bk-positions"><h3>Positions</h3><p class="bk-wait">Loading…</p></section>' +
        '<section class="bk-card bk-span" id="bk-holdings"><h3>Holdings</h3><p class="bk-wait">Loading…</p></section>' +
      '</div>' +
      '<p class="bk-fine">' + esc(c.disclaimer || '') + '</p>';
    view.querySelector('.bk-acct').addEventListener('click', onAccount);
    if (L.expired) {
      ['bk-funds', 'bk-orders', 'bk-positions', 'bk-holdings'].forEach(function (id) {
        document.getElementById(id).querySelector('.bk-wait').textContent = 'Log in to Dhan again to see this.';
      });
      return;
    }
    loadFunds(); loadOrders(); loadPositions(); loadHoldings();
  }

  function failed(id, e) {
    var box = document.getElementById(id);
    if (!box) return;
    var p = box.querySelector('.bk-wait') || box.appendChild(document.createElement('p'));
    p.className = 'bk-wait is-fail';
    p.textContent = e.message;
    if (e.reconnect && S.link && !S.link.expired) { S.link.expired = true; paintLinked(); }
  }

  function loadFunds() {
    B.api('/me/broker/funds').then(function (d) {
      var f = d.funds || {};
      document.getElementById('bk-funds').innerHTML = '<h3>Funds</h3><dl class="bk-sum">' +
        '<div><dt>Available to trade</dt><dd>' + rupees(f.available) + '</dd></div>' +
        '<div><dt>Used today</dt><dd>' + rupees(f.used) + '</dd></div>' +
        '<div><dt>At the start of the day</dt><dd>' + rupees(f.opening) + '</dd></div>' +
        '<div><dt>Withdrawable</dt><dd>' + rupees(f.withdrawable) + '</dd></div></dl>';
    }).catch(function (e) { failed('bk-funds', e); });
  }

  var LABEL = { sending: 'Sending', open: 'Open', part_filled: 'Part filled', filled: 'Filled',
                rejected: 'Rejected', cancelled: 'Cancelled', expired: 'Expired', unknown: 'Not confirmed' };
  var KIND = { filled: 'pass', rejected: 'fail', part_filled: 'part', unknown: 'part' };

  function table(head, rows) {
    return '<div class="bk-tbl-wrap"><table class="bk-tbl"><thead><tr>' + head.map(function (h) {
      return '<th' + (h[1] ? ' class="num"' : '') + '>' + esc(h[0]) + '</th>';
    }).join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>';
  }

  function loadOrders() {
    B.api('/me/broker/orders').then(function (d) {
      var rows = (d.orders || []).map(function (o) {
        var open = o.status === 'open' || o.status === 'part_filled';
        var px = o.type === 'MARKET' ? 'Market' : o.type === 'SL-M' ? 'SL-M ' + rupees(o.trigger)
               : rupees(o.price) + (o.trigger ? ' / ' + rupees(o.trigger) : '');
        return '<tr><td>' + esc((o.time || '').replace(/^\d{4}-\d{2}-\d{2}[ T]/, '').slice(0, 5)) + '</td>' +
          '<td><b>' + esc(o.symbol) + '</b>' + (o.via_altaha ? ' <span class="bk-tag">Altaha</span>' : '') + '</td>' +
          '<td class="' + (o.side === 'BUY' ? 'is-buy' : 'is-sell') + '">' + esc(o.side === 'BUY' ? 'Buy' : 'Sell') + '</td>' +
          '<td class="num">' + (o.filled_qty ? o.filled_qty + '/' : '') + esc(o.qty) + '</td>' +
          '<td class="num">' + px + '</td>' +
          '<td><span class="bk-st is-' + (KIND[o.status] || '') + '"' + (o.message ? ' title="' + esc(o.message) + '"' : '') + '>' +
            esc(LABEL[o.status] || o.status) + '</span>' + (o.message && o.status !== 'filled' ? '<small>' + esc(o.message) + '</small>' : '') + '</td>' +
          '<td>' + (open && o.broker_order_id ? '<button type="button" class="bk-btn is-small" data-cancel="' + esc(o.broker_order_id) + '">Cancel</button>' : '') + '</td></tr>';
      });
      var box = document.getElementById('bk-orders');
      box.innerHTML = '<h3>Today\'s orders</h3>' + (rows.length
        ? table([['Time'], ['Stock'], ['Side'], ['Qty', 1], ['Price', 1], ['Status'], ['']], rows).replace('class="bk-tbl"', 'class="bk-tbl is-orders"')
        : '<p class="bk-wait">No orders today.</p>');
      box.onclick = function (e) {
        var b = e.target.closest('[data-cancel]');
        if (!b) return;
        if (!confirm('Cancel this order in your Dhan account?')) return;
        b.disabled = true;
        B.post('/me/broker/orders/cancel', { broker_order_id: b.getAttribute('data-cancel') })
          .then(function () { track('broker_order_cancelled'); loadOrders(); loadFunds(); })
          .catch(function (err) { b.disabled = false; alert(err.message); });
      };
    }).catch(function (e) { failed('bk-orders', e); });
  }

  function loadPositions() {
    B.api('/me/broker/positions').then(function (d) {
      var rows = (d.positions || []).filter(function (p) { return p.net_qty || p.realized; }).map(function (p) {
        var pl = (p.realized || 0) + (p.unrealized || 0);
        return '<tr><td><b>' + esc(p.symbol) + '</b></td><td>' + esc(p.product === 'CNC' ? 'Delivery' : p.product === 'INTRADAY' ? 'Intraday' : p.product) + '</td>' +
          '<td class="num">' + esc(p.net_qty) + '</td><td class="num">' + rupees(p.net_qty >= 0 ? p.buy_avg : p.sell_avg) + '</td>' +
          '<td class="num ' + (pl >= 0 ? 'is-buy' : 'is-sell') + '">' + rupees(pl) + '</td></tr>';
      });
      document.getElementById('bk-positions').innerHTML = '<h3>Positions</h3>' + (rows.length
        ? table([['Stock'], ['Product'], ['Net qty', 1], ['Average', 1], ['P&L', 1]], rows)
        : '<p class="bk-wait">No open positions today.</p>');
    }).catch(function (e) { failed('bk-positions', e); });
  }

  function loadHoldings() {
    B.api('/me/broker/holdings').then(function (d) {
      var hs = d.holdings || [];
      var rows = hs.map(function (h) {
        return '<tr><td><b><a href="stock.html?ticker=' + encodeURIComponent(h.symbol) + '">' + esc(h.symbol) + '</a></b></td>' +
          '<td class="num">' + esc(h.qty) + '</td><td class="num">' + rupees(h.avg_price) + '</td>' +
          '<td class="num">' + rupees(h.avg_price && h.qty ? h.avg_price * h.qty : null, 0) + '</td></tr>';
      });
      var box = document.getElementById('bk-holdings');
      box.innerHTML = '<div class="bk-card-h"><h3>Holdings</h3>' +
        (hs.length ? '<button type="button" class="bk-btn is-small" id="bk-copy">Copy to my Altaha portfolio</button>' : '') + '</div>' +
        (rows.length ? table([['Stock'], ['Qty', 1], ['Average cost', 1], ['Invested', 1]], rows)
                     : '<p class="bk-wait">No holdings in this account.</p>') +
        '<p class="bk-msg" id="bk-copy-msg" role="status"></p>';
      var c = document.getElementById('bk-copy');
      if (c) c.addEventListener('click', function () {
        if (!confirm('Replace the portfolio saved on your Altaha account with these ' + hs.length + ' holdings from Dhan?')) return;
        c.disabled = true;
        B.post('/me/broker/holdings/copy').then(function (r) {
          track('broker_holdings_copied', { n: r.saved });
          var m = document.getElementById('bk-copy-msg');
          m.className = 'bk-msg is-good';
          m.innerHTML = 'Saved ' + r.saved + ' holding' + (r.saved === 1 ? '' : 's') + ' to your portfolio. ' +
            '<a href="./#portfolio/portfolio">Open the portfolio review ›</a>';
          c.disabled = false;
        }).catch(function (e) {
          c.disabled = false;
          var m = document.getElementById('bk-copy-msg'); m.className = 'bk-msg is-err'; m.textContent = e.message;
        });
      });
    }).catch(function (e) { failed('bk-holdings', e); });
  }

  function onAccount(e) {
    var b = e.target.closest('[data-a]');
    if (!b) return;
    var a = b.getAttribute('data-a');
    if (a === 'reconnect') {
      b.disabled = true;
      B.connect('dhan', '').catch(function (err) { b.disabled = false; say(err.message, 'err'); });
    } else if (a === 'pause') {
      b.disabled = true;
      B.post('/me/broker/pause', { paused: !S.link.paused }).then(function (d) {
        S.link = d.link; track('broker_paused', { paused: S.link.paused }); paintLinked();
      }).catch(function (err) { b.disabled = false; say(err.message, 'err'); });
    } else if (a === 'disconnect') {
      if (!confirm('Disconnect Dhan from Altaha? Altaha forgets the session; nothing changes in your Dhan account.')) return;
      b.disabled = true;
      B.post('/me/broker/disconnect').then(function () {
        S.link = null; track('broker_disconnected'); paintIntro();
      }).catch(function (err) { b.disabled = false; say(err.message, 'err'); });
    }
  }

  /* ── Start ───────────────────────────────────────────────────────────── */

  function load() {
    if (!(window.AltahaAuth && window.AltahaAuth.authed())) return;   // gate.js shows the sign-in card
    var token = tokenFromAddress();
    if (token) cleanAddress();
    var finish = token
      ? B.post('/me/broker/complete', { broker: 'dhan', token_id: token }).then(function (d) {
          track('broker_connected', { broker: 'dhan' });
          return { link: d.link, done: true };
        }).catch(function (e) { return { err: e }; })
      : Promise.resolve({});
    view.innerHTML = '<p class="bk-wait">' + (token ? 'Finishing your Dhan login…' : 'Loading your broker…') + '</p>';
    finish.then(function (f) {
      return B.api('/me/broker').then(function (d) {
        S.cfg = d.config; S.link = d.link;
        if (S.link) paintLinked(); else paintIntro();
        if (f.done) say('Connected to Dhan.', 'good');
        if (f.err) say(f.err.message, 'err');
      });
    }).catch(function (e) {
      view.innerHTML = '<section class="bk-card"><p class="bk-msg is-err">' + esc(e.message) + '</p>' +
        '<button type="button" class="bk-btn" onclick="location.reload()">Try again</button></section>';
    });
  }

  var started = false;
  function start() { if (!started && window.AltahaAuth && window.AltahaAuth.authed()) { started = true; load(); } }
  start();
  window.addEventListener('altaha-auth', start);
})();
