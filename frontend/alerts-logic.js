/* Altaha — the Alerts page's decisions (Market → Alerts)

   WHAT THIS IS
   The parts of the Alerts page that are rules rather than drawing: which
   record a card is built from when both lanes called the same break, which
   calls a filter keeps, what a call's live state says, where a call sits on
   the day's timeline, which stock on the radar is nearest to firing, and how
   the record of the two lanes adds up. index.html draws; this decides. It is
   kept apart so a node test (alerts-logic.test.js) can pin every rule without
   a browser, the way share.test.js pins share.js.

   TWO LANES
   Every call carries `engine`: "classic" (today's calls, exactly as they have
   always been) or "select" (fewer, stronger calls, paced through the day). A
   row without `engine` is Classic: the log is older than the second lane.
   When both lanes flag the same break the reader is shown ONE card: the
   record whose full card went out on Telegram (the trade the owner was
   sent), or, where the log does not say, the one that fired first. The
   other lane rides on it as a badge: "★ Select confirmed 10:02 am" on a
   Classic call, "Classic called it 10:02 am" on a Select one. Never two
   cards for one break: that would read as two trades.

   A LIVE PRICE is the tracker's last 20-second price (`live_at` says when).
   One more than two minutes old is not live: the quotes have stopped, and
   the card says what the last price was and when.

   TIME
   Calls are stamped in India time ("HH:MM", IST, no seconds). The reader's
   own clock may be anywhere, so "now" is always converted to IST by adding
   five and a half hours to UTC, never by trusting the browser's zone.

   No DOM, no storage of its own (the page hands its storage in), no network.
   Loaded as a plain script (window.AltahaAlertsLogic) and by node
   (module.exports). */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AltahaAlertsLogic = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var IST_MS = 330 * 60000;         // India is UTC+5:30 all year: no daylight saving
  var OPEN = 9 * 60 + 15;           // 09:15, the session's first minute
  var CLOSE = 15 * 60 + 30;         // 15:30, its last
  var STALE_MS = 2 * 60000;         // a live price older than this is no longer live

  /* Select's three sessions, as breakouts.pacing() describes them. Used when
     the server has not said (an older backend, or no answer yet): the
     timeline still shows where the windows are. */
  var SLOTS = [
    { key: 'open', label: 'Opening', from: '09:25', to: '10:15', cap: 3 },
    { key: 'mid', label: 'Mid-morning', from: '10:15', to: '12:30', cap: 3 },
    { key: 'pm', label: 'Afternoon', from: '12:30', to: '14:45', cap: 3 }
  ];

  /* ── small things ───────────────────────────────────────────────────── */

  function num(v) {
    if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* "HH:MM" (or "HH:MM:SS") to minutes after midnight; null for anything else. */
  function mins(t) {
    if (typeof t === 'number') return isFinite(t) ? t : null;
    var m = /^(\d{1,2}):(\d{2})/.exec(String(t == null ? '' : t));
    if (!m) return null;
    var h = +m[1], mm = +m[2];
    return h < 24 && mm < 60 ? h * 60 + mm : null;
  }

  /* "10:02" → "10:02 am", "15:15" → "3:15 pm". The page speaks in the same
     clock the Telegram cards do. */
  function clock12(t) {
    var v = mins(t);
    if (v === null) return '';
    var h = Math.floor(v / 60), m = Math.round(v % 60);
    return (h % 12 || 12) + ':' + pad(m) + ' ' + (h >= 12 ? 'pm' : 'am');
  }

  /* "09:20–15:00" → "9:20 am to 3 pm". A window is read aloud, not typeset. */
  function span12(s) {
    var parts = String(s || '').split(/\s*[–-]\s*/);
    if (parts.length !== 2 || mins(parts[0]) === null || mins(parts[1]) === null) return '';
    var short = function (t) { return clock12(t).replace(':00 ', ' '); };
    return short(parts[0]) + ' to ' + short(parts[1]);
  }

  /* ₹ with Indian digit grouping and two decimals, like the cards. */
  function money(v) {
    var n = num(v);
    if (n === null) return '—';
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /* A signed percentage to one decimal, with a true minus sign. Rounded
     first, so −0.04 reads 0.0% and not "−0.0%". */
  function pct(v, dp) {
    var n = num(v);
    if (n === null) return '';
    var d = dp === undefined ? 1 : dp, f = Math.pow(10, d), r = Math.round(n * f) / f;
    return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r).toFixed(d) + '%';
  }

  /* The same, in R: one R is the distance from entry to stop loss. */
  function rmult(v) {
    var n = num(v);
    if (n === null) return '';
    var r = Math.round(n * 100) / 100;
    return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r).toFixed(2) + 'R';
  }

  /* ── time in India ──────────────────────────────────────────────────── */

  /* Now (or `ms`), in India: the date and the minutes after midnight. */
  function ist(ms) {
    var d = new Date((ms === undefined || ms === null ? Date.now() : ms) + IST_MS);
    var h = d.getUTCHours(), m = d.getUTCMinutes();
    return {
      date: d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()),
      mins: h * 60 + m + d.getUTCSeconds() / 60,
      hhmm: pad(h) + ':' + pad(m)
    };
  }

  /* When a call fired, as a timestamp (ms): its IST date and minute. */
  function callAt(a) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((a && a.date) || ''), t = mins(a && a.time);
    if (!m || t === null) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], 0, t) - IST_MS;
  }

  /* "just now", "12m ago", "1h 5m ago". Empty when it is not a sensible
     sentence: no stamp, or more than a day ago (the time on the card says
     enough). A call stamped a minute ahead of a slow clock is "just now",
     not "in the future". */
  function ago(at, nowMs) {
    if (at === null || at === undefined) return '';
    var m = Math.floor(((nowMs === undefined || nowMs === null ? Date.now() : nowMs) - at) / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return m + 'm ago';
    var h = Math.floor(m / 60), r = m % 60;
    if (h >= 24) return '';
    return h + 'h' + (r ? ' ' + r + 'm' : '') + ' ago';
  }

  /* ── the two lanes ──────────────────────────────────────────────────── */

  function engineOf(a) { return a && a.engine === 'select' ? 'select' : 'classic'; }
  function isSelect(a) { return engineOf(a) === 'select'; }

  /* One call's identity. The lane is part of it: both lanes can call the
     same stock, the same way, in the same minute. */
  function keyOf(a) {
    a = a || {};
    return [a.date || '', a.time || '', a.symbol || '', a.direction === 'DOWN' ? 'DOWN' : 'UP', engineOf(a)].join('|');
  }

  /* Which Select record confirmed which Classic one. The server marks both
     sides when it pairs them (select.pair_time is the Classic call's time,
     classic.select_time is Select's), so an exact match is claimed first;
     a Classic row marked as confirmed whose partner carries no pair_time
     (an older row, or a half-written one) is matched second, by symbol and
     side. Each record pairs at most once. */
  function pairs(rows) {
    var classic = [], select = [], byClassic = {}, bySelect = {};
    (rows || []).forEach(function (a) { if (a && a.symbol) (isSelect(a) ? select : classic).push(a); });
    var same = function (c, s) {
      return c.symbol === s.symbol && (c.direction === 'DOWN') === (s.direction === 'DOWN') &&
             (!c.date || !s.date || c.date === s.date);
    };
    var link = function (c, s) { byClassic[keyOf(c)] = s; bySelect[keyOf(s)] = c; };
    var free = function (c) { return !byClassic[keyOf(c)]; };
    select.forEach(function (s) {
      var hit = classic.filter(function (c) {
        return free(c) && same(c, s) &&
               ((s.pair_time && c.time === s.pair_time) || (c.select_time && c.select_time === s.time));
      })[0];
      if (hit) link(hit, s);
    });
    select.forEach(function (s) {
      if (bySelect[keyOf(s)]) return;
      var hit = classic.filter(function (c) { return free(c) && same(c, s) && !!c.select_time; })
        .sort(function (x, y) { return (mins(y.time) || 0) - (mins(x.time) || 0); })[0];
      if (hit) link(hit, s);
    });
    return { byClassic: byClassic, bySelect: bySelect };
  }

  /* Of the two records of one break, the one its card is built from: the
     one whose full card went out on Telegram (intraday.py marks the other
     tg_card false: a Select call carried a Classic one in the same pass, or
     the later call got only a short line), so the page shows the trade the
     owner was sent. Where the log does not say, the one that fired first;
     Classic on a tie. */
  function primary(classic, select) {
    var c = classic.tg_card !== false, s = select.tg_card !== false;
    if (c !== s) return c ? classic : select;
    var tc = mins(classic.time), ts = mins(select.time);
    return tc !== null && ts !== null && ts < tc ? select : classic;
  }

  /* The cards for a lane, in the order the rows came (the server sends the
     newest first). `all` is one card per break: a break both lanes called
     is its primary() record with the other lane's folded in as `pair`, plus
     every call the other lane did not make. `classic` and `select` are each
     lane's own records, each still knowing its partner. */
  function items(rows, lane) {
    var p = pairs(rows), out = [];
    (rows || []).forEach(function (a) {
      if (!a || !a.symbol) return;
      var sel = isSelect(a), k = keyOf(a);
      if (lane === 'select' && !sel) return;
      if (lane === 'classic' && sel) return;
      var pair = (sel ? p.bySelect[k] : p.byClassic[k]) || null;
      if (lane !== 'select' && lane !== 'classic' && pair) {
        var main = sel ? primary(pair, a) : primary(a, pair);
        if (main !== a) return;                        // folded into its partner's card
      }
      out.push({ key: k, rec: a, pair: pair, lane: sel ? 'select' : 'classic' });
    });
    return out;
  }

  /* The badge a card's partner earns. A Select call made after the Classic
     one "confirmed" it: a later minute, or the same minute where the routing
     gave Select only the short confirm line. One made before "called it"
     too, as does a Classic call on a Select card. */
  function partnerNote(it) {
    if (!it || !it.pair || !it.rec) return null;
    var pair = it.pair, sel = isSelect(pair), tp = mins(pair.time), tr = mins(it.rec.time);
    var later = tp !== null && tr !== null &&
                (tp > tr || (tp === tr && pair.tg_card === false && it.rec.tg_card !== false));
    return {
      lane: sel ? 'select' : 'classic', time: pair.time || '', later: later,
      text: sel ? (later ? 'Select confirmed ' : 'Select called it ') + clock12(pair.time)
                : 'Classic called it ' + clock12(pair.time)
    };
  }

  /* Calls made today, a break called by both lanes counted once. The same
     rule doors.js uses for Market's Alerts card. */
  function countCalls(rows) {
    return (rows || []).filter(function (a) { return a && !(a.engine === 'select' && a.pair_time); }).length;
  }

  /* Today's figures, one per card, each read from the record the card
     shows (a break both lanes called is one card, and its own result is
     the one counted), so the hero's numbers and the timeline's line agree
     with the cards under them. `live` leaves out a call whose price has
     stopped coming (isStale). */
  function dayCounts(rows, nowMs) {
    var cards = items(rows, 'all');
    var n = function (fn) { return cards.filter(fn).length; };
    return {
      calls: cards.length,
      both: n(function (it) { return !!it.pair; }),
      select: (rows || []).filter(isSelect).length,
      hit: n(function (it) { return isWin(it.rec); }),
      stopped: n(function (it) { return isStopped(it.rec); }),
      live: n(function (it) { return isLive(it.rec, nowMs); })
    };
  }

  /* ── what a call's state is ─────────────────────────────────────────── */

  /* When the tracker last priced a call (`live_at`, "HH:MM:SS" IST on the
     call's date), as a timestamp; null when the row does not say. */
  function liveAt(a) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((a && a.date) || '');
    var t = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(String((a && a.live_at) || ''));
    if (!m || !t) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +t[1], +t[2], +(t[3] || 0)) - IST_MS;
  }

  /* A live price that has not moved on for two minutes is not live: the
     quotes stopped (an expired token, a lapsed subscription, the scanner
     down). Without a clock, or a row that never said when, nothing is stale. */
  function isStale(a, nowMs) {
    if (nowMs === undefined || nowMs === null || !a || a.live_outcome || a.outcome) return false;
    var at = liveAt(a);
    return at !== null && num(a.live_price) !== null && nowMs - at > STALE_MS;
  }

  /* The 5-minute-candle check after the close (`outcome`) is the authority,
     so once it has run its line is the one shown. Before that the live
     tracker's 20-second fields say where the trade stands. An exit beats a
     half-book, and a half-book beats a plain price. `nowMs` (the server's
     clock, where the page knows it) decides whether that price is still
     live: an old one reads "Last ₹… · 10:29 am", never LIVE. */
  function liveState(a, nowMs) {
    a = a || {};
    var pnl = num(a.live_pnl_pct), px = num(a.live_price);
    var stale = isStale(a, nowMs), seen = stale ? clock12(a.live_at) : '';
    if (a.outcome === 'TARGET' || a.outcome === 'STOP' || a.outcome === 'OPEN_AT_CLOSE') {
      var fp = num(a.pnl_pct);
      return {
        key: 'final', outcome: a.outcome, pnl: fp,
        tone: a.outcome === 'TARGET' ? 'won' : a.outcome === 'STOP' ? 'lost' : fp > 0 ? 'won' : fp < 0 ? 'lost' : 'flat',
        label: { TARGET: 'Hit the target', STOP: 'Hit the stop loss', OPEN_AT_CLOSE: 'Closed at 3:15 pm' }[a.outcome]
      };
    }
    if (a.live_outcome === 'TARGET') return { key: 'target', tone: 'won', label: 'TARGET HIT ✓', pnl: pnl, at: a.live_time || null };
    if (a.live_outcome === 'STOP') return { key: 'stop', tone: 'lost', label: 'STOPPED OUT ✕', pnl: pnl, at: a.live_time || null, t1: !!a.t1_hit };
    if (a.live_outcome === 'OPEN_AT_CLOSE') {
      return { key: 'closed', tone: pnl > 0 ? 'won' : pnl < 0 ? 'lost' : 'flat', label: 'CLOSED 3:15 pm', pnl: pnl };
    }
    if (a.t1_hit) {
      return { key: 't1', tone: 'hl', label: 'T1 HIT · Move SL to cost', pnl: pnl, price: px, at: a.t1_time || null,
               stale: stale, seen: seen };
    }
    if (px !== null && px > 0) {
      var fig = money(px) + (pnl !== null ? ' (' + pct(pnl) + ')' : '');
      if (stale) return { key: 'last', tone: 'flat', label: 'Last ' + fig + ' · ' + seen, pnl: pnl, price: px, stale: true, seen: seen };
      return { key: 'live', tone: 'info', label: 'LIVE · ' + fig, pnl: pnl, price: px, stale: false };
    }
    return { key: 'none', tone: 'flat', label: '', pnl: null };
  }

  /* Still in play: neither the live tracker nor the close has ended it. */
  function isActive(a) { return !!a && !a.outcome && !a.live_outcome; }

  /* In play and priced within the last two minutes: what "N live" counts. */
  function isLive(a, nowMs) { return isActive(a) && !isStale(a, nowMs); }

  /* Hit its target, by either account. Counted once per card. */
  function isWin(a) { return !!a && (a.outcome === 'TARGET' || (!a.outcome && a.live_outcome === 'TARGET')); }

  /* Ended at its stop. The card is dimmed (still readable). */
  function isStopped(a) { return !!a && (a.outcome === 'STOP' || (!a.outcome && a.live_outcome === 'STOP')); }

  /* Where the trade stands between its stop and its target, in risk units:
     the stop is −1R, the entry 0, the half-book +1R, the target +RR. The
     band is how far it has travelled either way since the entry (MAE to
     MFE), from the live tracker's own samples. Null without a live price:
     the rail shows a trade in progress, not a plan. */
  function rail(a) {
    if (!a) return null;
    var entry = num(a.entry), stop = num(a.stop), rr = num(a.rr) || 2;
    var risk = entry !== null && stop !== null ? Math.abs(entry - stop) : null;
    var sign = a.direction === 'DOWN' ? -1 : 1;
    var r = num(a.live_r);
    if (r === null) {
      var px = num(a.live_exit) !== null && a.live_outcome ? num(a.live_exit) : num(a.live_price);
      if (px === null || !risk) return null;
      r = sign * (px - entry) / risk;
    }
    var lo = num(a.mae_r), hi = num(a.mfe_r);
    lo = Math.min(lo === null ? 0 : lo, r, 0);
    hi = Math.max(hi === null ? 0 : hi, r, 0);
    var at = function (x) { return Math.round(clamp((x + 1) / (rr + 1), 0, 1) * 1000) / 10; };
    return { r: r, rr: rr, now: at(r), entry: at(0), t1: at(1), lo: at(lo), hi: at(hi), best: hi, worst: lo };
  }

  /* What the score is made of, for the score pill's tooltip: the parts
     breakouts.py added up, the ones that counted, biggest first. */
  var PART_WORDS = { volume: 'volume', level: 'level', risk: 'risk', range: 'tight range', index: 'index',
                     strength: 'strength', sector: 'sector', flow: 'money flow', book: 'order book' };
  function scoreTitle(a) {
    var sc = num(a && a.score);
    if (sc === null) return '';
    var parts = (a && a.score_parts) || {};
    var bits = Object.keys(parts).map(function (k) { return [k, num(parts[k])]; })
      .filter(function (x) { return x[1] !== null && Math.round(x[1]) !== 0; })
      .sort(function (x, y) { return y[1] - x[1]; })
      .map(function (x) { return (PART_WORDS[x[0]] || x[0]) + ' ' + (x[1] > 0 ? '+' : '−') + Math.abs(Math.round(x[1])); });
    return 'Score ' + Math.round(sc) + ' out of 100' + (bits.length ? ': ' + bits.join(', ') : '');
  }

  /* On a Classic call, what Select's own quality checks said about it (the
     `shadow` list: the checks it would have failed). The owner's running
     measure of whether those checks help. Null when the row does not say. */
  var SHADOW_WORDS = { rpos: 'not near the day’s extreme', extended: 'too far past VWAP', book: 'order book against it',
                       sector: 'sector against it', pdh: 'yesterday’s level on its own' };
  function shadowWords(a) {
    if (!a || !Array.isArray(a.shadow) || isSelect(a)) return null;
    return a.shadow.map(function (c) { return SHADOW_WORDS[c] || String(c); });
  }

  /* The owner's line under a Classic call Select did not make. `shadow`
     only covers Select's five quality filters, so an empty list says those
     passed, never that Select would have taken the call: what held Select
     back on the same pass (breakouts.py notes it as `select_wait`), or, for
     an older row, what Select's radar says about the stock now (`waiting`,
     /breakouts/status), is said beside it. Null when the row says nothing. */
  function shadowNote(a, waiting) {
    var sw = shadowWords(a);
    if (!sw) return null;
    var held = a.select_wait && a.select_wait.why ? String(a.select_wait.why) : '', now = false;
    if (!held) {
      var side = a.direction === 'DOWN' ? 'DOWN' : 'UP';
      var w = (waiting || []).filter(function (r) {
        return r && r.lane === 'select' && r.symbol === a.symbol && (r.dir === 'DOWN' ? 'DOWN' : 'UP') === side && r.why;
      })[0];
      if (w) { held = String(w.why); now = true; }
    }
    var held_ = held ? (now ? 'Select is holding it: ' : 'Select held it: ') + held : '';
    if (sw.length) return { failed: sw, held: held, text: 'Select’s quality filters would have skipped it: ' + sw.join(', ') + (held_ ? ' · ' + held_ : '') };
    if (held) return { failed: [], held: held, text: held_ + ' · its quality filters passed' };
    return { failed: [], held: '', text: 'Select’s quality filters: all passed' };
  }

  /* ── filters ────────────────────────────────────────────────────────── */

  var FILTER = { lane: 'all', side: null, active: false, score: false };

  function normFilter(f) {
    f = f && typeof f === 'object' ? f : {};
    return {
      lane: f.lane === 'select' || f.lane === 'classic' ? f.lane : 'all',
      side: f.side === 'BUY' || f.side === 'SELL' ? f.side : null,
      active: f.active === true,
      score: f.score === true
    };
  }

  /* Pressing a pill. The lane pills are one choice of three; BUY and SELL
     are one choice of two that can also be neither; Active and Score 75+
     each switch on and off. Returns a new filter. */
  function press(f, pill) {
    var n = normFilter(f);
    if (pill === 'all' || pill === 'select' || pill === 'classic') n.lane = pill;
    else if (pill === 'buy' || pill === 'sell') { var s = pill.toUpperCase(); n.side = n.side === s ? null : s; }
    else if (pill === 'active') n.active = !n.active;
    else if (pill === 'score') n.score = !n.score;
    return n;
  }

  /* What a pill's aria-pressed says. */
  function pressed(f, pill) {
    var n = normFilter(f);
    if (pill === 'all' || pill === 'select' || pill === 'classic') return n.lane === pill;
    if (pill === 'buy') return n.side === 'BUY';
    if (pill === 'sell') return n.side === 'SELL';
    if (pill === 'active') return n.active;
    if (pill === 'score') return n.score;
    return false;
  }

  function keep(item, f) {
    var a = item && item.rec;
    if (!a) return false;
    if (f.side === 'BUY' && a.direction === 'DOWN') return false;
    if (f.side === 'SELL' && a.direction !== 'DOWN') return false;
    if (f.active && !isActive(a)) return false;
    if (f.score && !((num(a.score) || 0) >= 75)) return false;
    return true;
  }

  /* The cards a filter shows. */
  function view(rows, f) {
    var n = normFilter(f);
    return items(rows, n.lane).filter(function (it) { return keep(it, n); });
  }

  /* In words, for an empty column: "★ Select · BUY". */
  function describe(f) {
    var n = normFilter(f), bits = [];
    if (n.lane === 'select') bits.push('★ Select');
    if (n.lane === 'classic') bits.push('Classic');
    if (n.active) bits.push('Active');
    if (n.side) bits.push(n.side);
    if (n.score) bits.push('Score 75+');
    return bits.join(' · ');
  }

  /* The reader's choices, kept on this browser. `store` is localStorage or
     anything shaped like it; every touch of it is guarded, because private
     windows and locked-down browsers throw on access. */
  var PREFS_KEY = 'altaha-alerts-prefs-v1';
  function loadPrefs(store) {
    var out = { filter: normFilter(null), chime: false };
    try {
      var raw = store && store.getItem(PREFS_KEY);
      if (raw) {
        var p = JSON.parse(raw);
        out.filter = normFilter(p && p.filter);
        out.chime = !!(p && p.chime === true);
      }
    } catch (e) { /* nothing stored, or storage is off: the defaults stand */ }
    return out;
  }
  function savePrefs(store, prefs) {
    try {
      if (store) store.setItem(PREFS_KEY, JSON.stringify({ filter: normFilter(prefs && prefs.filter), chime: !!(prefs && prefs.chime) }));
      return true;
    } catch (e) { return false; }
  }

  /* Calls in `rows` not yet in `seen` (a Set of keyOf values). The chime
     rings for these, and only after the first paint. */
  function unseen(seen, rows) {
    return (rows || []).filter(function (a) { return a && a.symbol && !(seen && seen.has(keyOf(a))); });
  }

  /* Fifteen seconds while someone is watching a live market; thirty
     otherwise. A hidden tab is not asked for anything until it is shown. */
  function pollDelay(visible, marketOpen) { return visible && marketOpen ? 15000 : 30000; }

  /* ── the day's timeline ─────────────────────────────────────────────── */

  /* Percent along 09:15 → 15:30. */
  function tlPos(t) {
    var v = mins(t);
    return v === null ? null : Math.round(clamp((v - OPEN) / (CLOSE - OPEN), 0, 1) * 1000) / 10;
  }

  /* Where "now" falls on the strip, or null outside the session. */
  function tlNow(nowMs) {
    var n = ist(nowMs).mins;
    return n < OPEN || n > CLOSE ? null : Math.round((n - OPEN) / (CLOSE - OPEN) * 1000) / 10;
  }

  /* Select is switched off today (BO_LANES): the server's pacing says
     enabled false, or /breakouts/status's lanes do. */
  function selectOff(pacing, lanes) {
    return !!((pacing && pacing.enabled === false) ||
              (lanes && lanes.select && lanes.select.enabled === false));
  }

  /* Select's three windows, shaded on the strip, each with its ★ slots used.
     The server's pacing says it best; without it the windows are the
     defaults and the use is counted from today's Select rows. None at all
     while Select is switched off: it has no slots to spend. */
  function tlBands(pacing, rows) {
    if (pacing && pacing.enabled === false) return [];
    var given = pacing && Array.isArray(pacing.slots) && pacing.slots.length ? pacing.slots : null;
    var now = pacing && pacing.session && pacing.session.key;
    return (given || SLOTS).map(function (s) {
      var a = tlPos(s.from), b = tlPos(s.to);
      if (a === null || b === null) return null;
      var used = num(s.used);
      if (used === null) {
        used = (rows || []).filter(function (r) {
          if (!isSelect(r)) return false;
          if (r.window) return r.window === s.key;
          var t = mins(r.time);
          return t !== null && t >= mins(s.from) && t < mins(s.to);
        }).length;
      }
      return {
        key: s.key, label: s.label || s.key, from: s.from, to: s.to,
        left: a, width: Math.round((b - a) * 10) / 10,
        used: used, cap: num(s.cap) === null ? 3 : num(s.cap),
        current: !!now && now === s.key
      };
    }).filter(Boolean);
  }

  var STATE_WORDS = { live: 'live', none: 'live', last: 'no fresh price', t1: 'half-book reached', target: 'target hit',
                      stop: 'stopped out', closed: 'closed at 3:15 pm' };

  function dotTone(st) {
    if (st.key === 'final') return st.outcome === 'TARGET' ? 'won' : st.outcome === 'STOP' ? 'lost' : st.tone === 'won' ? 'won' : st.tone === 'lost' ? 'lost' : 'flat';
    if (st.key === 'target') return 'won';
    if (st.key === 'stop') return 'lost';
    if (st.key === 'closed') return st.tone;
    if (st.key === 't1') return 't1';
    return 'open';
  }

  /* One mark per call (both lanes; ★ for Select), on its own row by lane,
     oldest first so a later mark draws over an earlier one. Marks closer
     than `gap` percent on the same row are lifted onto the next of three
     levels so a busy minute still shows how many calls it held; past three,
     a mark goes a gap to the right of the level that frees up first, never
     on top of another, where neither could be seen or pressed. `opts.now`
     is the clock liveState() judges a price's freshness by. */
  function tlDots(rows, opts) {
    var gap = (opts && opts.gap) || 3, now = opts && opts.now, levels = { classic: [], select: [] };
    return (rows || []).filter(function (a) { return a && a.symbol && mins(a.time) !== null; })
      .slice().sort(function (x, y) { return mins(x.time) - mins(y.time); })
      .map(function (a) {
        var lane = engineOf(a), left = tlPos(a.time), lv = levels[lane], k = 0;
        while (k < lv.length && left - lv[k] < gap) k++;
        if (k > 2) {
          k = 0;
          for (var j = 1; j < 3; j++) if (lv[j] < lv[k]) k = j;
          left = Math.min(100, Math.round((lv[k] + gap) * 10) / 10);
        }
        lv[k] = left;
        var st = liveState(a, now), tone = dotTone(st);
        var words = st.key === 'final'
          ? { TARGET: 'target hit', STOP: 'stopped out', OPEN_AT_CLOSE: 'closed at 3:15 pm' }[st.outcome]
          : STATE_WORDS[st.key] || 'live';
        return {
          key: keyOf(a), lane: lane, star: lane === 'select', left: left, stack: k, tone: tone,
          time: a.time, symbol: a.symbol,
          label: clock12(a.time) + ', ' + (a.direction === 'DOWN' ? 'Sell ' : 'Buy ') + a.symbol + ', ' +
                 (lane === 'select' ? 'Select' : 'Classic') + ', ' + words   // read aloud: no star glyph
        };
      });
  }

  /* The hours under the strip. */
  function tlHours() {
    var out = [{ t: '09:15', label: '9:15', edge: 'start' }];
    for (var h = 10; h <= 15; h++) out.push({ t: pad(h) + ':00', label: String(h % 12 || 12) });
    out.push({ t: '15:30', label: '3:30', edge: 'end' });
    return out.map(function (x) { x.left = tlPos(x.t); return x; });
  }

  /* ── the radar: testing a level right now ───────────────────────────── */

  /* Why a stock at a level has not fired yet, as a chip. `tone` picks the
     colour: the one about to fire is cognac, a full slot is a warning, the
     two that are a matter of degree (volume, score) are information, and
     everything else is quiet. `rank` orders the radar the way
     breakouts.status() does: confirming first, then the ones only the slot
     budget held back, then score, then volume; after those, the deeper a
     stock got through the checks (volume is the first, the order book the
     last before the score), the nearer it is. */
  var REASONS = {
    confirm:  { label: 'Confirming', tone: 'hl', rank: 0 },
    cap:      { label: 'Slots full', tone: 'warn', rank: 1 },
    score:    { label: 'Score short', tone: 'info', rank: 2 },
    volume:   { label: 'Needs volume', tone: 'info', rank: 3 },
    book:     { label: 'Sellers heavier', labelDn: 'Buyers heavier', tone: 'muted', rank: 4 },
    room:     { label: 'No room to target', tone: 'muted', rank: 5 },
    risk:     { label: 'Stop too wide', tone: 'muted', rank: 6 },
    spent:    { label: 'Already moved', tone: 'muted', rank: 7 },
    sector:   { label: 'Sector against', tone: 'muted', rank: 8 },
    index:    { label: 'Index against', tone: 'muted', rank: 9 },
    rpos:     { label: 'Low in its range', labelDn: 'High in its range', tone: 'muted', rank: 10 },
    extended: { label: 'Stretched', tone: 'muted', rank: 11 },
    vwap:     { label: 'Wrong side of VWAP', tone: 'muted', rank: 12 },
    novwap:   { label: 'No VWAP on the quote', tone: 'muted', rank: 13 }
  };

  function reason(code, dir) {
    var r = REASONS[code];
    if (!r) return { code: code || '', label: 'Waiting', tone: 'muted', rank: 20 };
    return { code: code, label: dir === 'DOWN' && r.labelDn ? r.labelDn : r.label, tone: r.tone, rank: r.rank };
  }

  /* How close a waiting stock is to its threshold, 0..2 (1 = there). */
  function progress(w) {
    var have = num(w && (w.code === 'score' ? w.score : w.rvol)), need = num(w && w.need);
    return have !== null && need ? clamp(have / need, 0, 2) : 0;
  }

  /* Nearest to firing first: by reason, then Select before Classic (its
     checks are the stricter, so getting that far means more), then the
     share of the threshold reached, then score, then name, so the order
     holds still between passes. */
  function radarSort(rows) {
    return (rows || []).filter(function (w) { return w && w.symbol; })
      .map(function (w, i) { return { w: w, i: i, rank: reason(w.code).rank }; })
      .sort(function (x, y) {
        return x.rank - y.rank ||
          (y.w.lane === 'select') - (x.w.lane === 'select') ||
          progress(y.w) - progress(x.w) ||
          (num(y.w.score) || 0) - (num(x.w.score) || 0) ||
          (x.w.symbol < y.w.symbol ? -1 : x.w.symbol > y.w.symbol ? 1 : x.i - y.i);
      })
      .map(function (x) { return x.w; });
  }

  /* How far past its level the price is, in the direction of the break. */
  function pastLevel(w) {
    var lv = num(w && w.level), px = num(w && w.price);
    if (!lv || px === null) return null;
    return (w.dir === 'DOWN' ? -1 : 1) * (px / lv - 1) * 100;
  }

  /* ── sectors ────────────────────────────────────────────────────────── */

  /* NSE's industry names as a badge has room for them: the same short names
     breakouts.SECTOR_SHORT gives (sectors_live carries them as `short`), so
     a card and the sector tape agree. Any other name is short already. */
  var SECTOR_SHORT = {
    'automobile and auto components': 'Auto', 'fast moving consumer goods': 'FMCG',
    'information technology': 'IT', 'oil gas & consumable fuels': 'Oil & Gas',
    'financial services': 'Financials', 'consumer services': 'Consumer',
    'consumer durables': 'Durables', 'construction materials': 'Cement',
    'metals & mining': 'Metals', 'capital goods': 'Capital goods',
    'telecommunication': 'Telecom', 'media entertainment & publication': 'Media',
    'forest materials': 'Forest'
  };
  function sectorShort(name) {
    var s = String(name == null ? '' : name).trim();
    return s ? SECTOR_SHORT[s.toLowerCase()] || s : '';
  }

  /* The day's leaders and laggards: the top `n` up and the top `n` down. */
  function sectorTape(list, n) {
    var k = n || 3, rows = (list || []).filter(function (x) { return x && x.sector && num(x.pct) !== null; });
    return {
      up: rows.filter(function (x) { return num(x.pct) > 0; }).sort(function (a, b) { return b.pct - a.pct; }).slice(0, k),
      down: rows.filter(function (x) { return num(x.pct) < 0; }).sort(function (a, b) { return a.pct - b.pct; }).slice(0, k)
    };
  }

  /* ── the record ─────────────────────────────────────────────────────── */

  /* One lane's record as one summary. call_record() splits a lane into its
     two kinds of call (intraday, consolidation); the head-to-head adds them
     back up, averaging the result per call by the number of calls. */
  function record(rec) {
    if (!rec || typeof rec !== 'object') return null;
    if (num(rec.calls) !== null) return rec.calls ? rec : null;
    var parts = [], split = {};
    Object.keys(rec).forEach(function (k) {
      var p = rec[k];
      if (p && typeof p === 'object' && num(p.calls)) { parts.push(p); split[k] = p.calls; }
    });
    if (!parts.length) return null;
    var sum = function (f) { return parts.reduce(function (s, p) { return s + (num(p[f]) || 0); }, 0); };
    var calls = sum('calls');
    return {
      calls: calls, target: sum('target'), stop: sum('stop'), closed: sum('closed'), profitable: sum('profitable'),
      avg_pct: Math.round(parts.reduce(function (s, p) { return s + (num(p.avg_pct) || 0) * p.calls; }, 0) / calls * 100) / 100,
      split: split
    };
  }

  /* Classic against ★ Select. Classic falls back to `calls`, which is what
     an older backend sends and means the same thing. */
  function lanesRecord(stats) {
    var by = (stats && stats.calls_by_engine) || {};
    return {
      classic: record(by.classic || (stats && stats.calls)),
      select: record(by.select),
      hasSelect: !!by.select
    };
  }

  var WINDOWS = [
    { key: 'early', label: 'Opening minutes', span: 'before 9:25', extra: true },
    { key: 'open', label: 'Opening', span: '9:25–10:15' },
    { key: 'mid', label: 'Mid-morning', span: '10:15–12:30' },
    { key: 'pm', label: 'Afternoon', span: '12:30–2:45' },
    { key: 'late', label: 'Wind-down', span: 'after 2:45', extra: true }
  ];

  /* The by-session table: Select's three windows always, the minutes
     either side of them only when a lane traded there. Empty until either
     lane has a closed trade in some window. */
  function sessionRows(stats) {
    var e = stats && stats.engines;
    if (!e) return [];
    var c = (e.classic && e.classic.by_window) || {}, s = (e.select && e.select.by_window) || {};
    var has = function (b) { return !!(b && num(b.trades)); };
    var rows = WINDOWS.map(function (w) {
      return { key: w.key, label: w.label, span: w.span, extra: !!w.extra,
               classic: has(c[w.key]) ? c[w.key] : null, select: has(s[w.key]) ? s[w.key] : null };
    });
    if (!rows.some(function (r) { return r.classic || r.select; })) return [];
    return rows.filter(function (r) { return !r.extra || r.classic || r.select; });
  }

  /* Would Select's checks have helped Classic? stats().by_shadow splits
     Classic's closed trades, check by check, into the ones that failed it
     and the ones that passed. A check earns its place when the failed side
     does worse. Rows only for checks with a trade on either side. */
  function shadowRows(stats) {
    var by = (stats && stats.by_shadow) || {};
    var has = function (b) { return !!(b && num(b.trades)); };
    var codes = ['rpos', 'extended', 'book', 'sector', 'pdh'];
    Object.keys(by).forEach(function (k) { if (codes.indexOf(k) < 0) codes.push(k); });
    return codes.filter(function (k) { return by[k] && (has(by[k].failed) || has(by[k].passed)); })
      .map(function (k) {
        return { code: k, label: GATE_LABEL[k] || k,
                 failed: has(by[k].failed) ? by[k].failed : null, passed: has(by[k].passed) ? by[k].passed : null };
      });
  }

  /* ── the owner's funnel ─────────────────────────────────────────────── */

  var GATE_LABEL = {
    volume: 'Volume not there yet', vwap: 'Wrong side of VWAP', score: 'Score below the bar',
    rpos: 'Not near the day’s extreme', sector: 'Sector not moving with it', extended: 'Too far past VWAP',
    book: 'Order book leaning against it', confirm: 'Did not hold for a second pass', risk: 'Stop too wide',
    room: 'No room to the next level', index: 'Index against it', spent: 'Already moved too far today',
    cap: 'Held back by the slot budget', pdh: 'Yesterday’s high or low on its own',
    novwap: 'No VWAP on the quote yet'
  };

  /* breakouts.status() counts, per check, the stocks (one per stock and
     side) it held back today. Biggest first, each with its share of the
     biggest so the bars can be drawn. */
  function funnel(gates) {
    var rows = Object.keys(gates || {}).map(function (k) {
      return { code: k, label: GATE_LABEL[k] || k, n: Math.max(0, Math.round(num(gates[k]) || 0)) };
    }).filter(function (r) { return r.n > 0; })
      .sort(function (a, b) { return b.n - a.n || (a.code < b.code ? -1 : 1); });
    var top = rows.length ? rows[0].n : 1;
    rows.forEach(function (r) { r.w = Math.max(2, Math.round(r.n / top * 100)); });
    return rows;
  }

  return {
    IST_MS: IST_MS, OPEN: OPEN, CLOSE: CLOSE, STALE_MS: STALE_MS, SLOTS: SLOTS, PREFS_KEY: PREFS_KEY, FILTER: FILTER,
    REASONS: REASONS,
    num: num, mins: mins, clock12: clock12, span12: span12, money: money, pct: pct, rmult: rmult,
    ist: ist, callAt: callAt, ago: ago,
    engineOf: engineOf, isSelect: isSelect, keyOf: keyOf, pairs: pairs, primary: primary, items: items,
    partnerNote: partnerNote, countCalls: countCalls, dayCounts: dayCounts,
    liveAt: liveAt, isStale: isStale, liveState: liveState, isActive: isActive, isLive: isLive, isWin: isWin,
    isStopped: isStopped, rail: rail,
    scoreTitle: scoreTitle, shadowWords: shadowWords, shadowNote: shadowNote,
    normFilter: normFilter, press: press, pressed: pressed, view: view, describe: describe,
    loadPrefs: loadPrefs, savePrefs: savePrefs, unseen: unseen, pollDelay: pollDelay,
    selectOff: selectOff, tlPos: tlPos, tlNow: tlNow, tlBands: tlBands, tlDots: tlDots, tlHours: tlHours,
    reason: reason, progress: progress, radarSort: radarSort, pastLevel: pastLevel,
    sectorShort: sectorShort, sectorTape: sectorTape,
    record: record, lanesRecord: lanesRecord, sessionRows: sessionRows, shadowRows: shadowRows, funnel: funnel
  };
});
