/* The portfolio report — the one you read on the page, download, and print.

   WHY THIS EXISTS
   The old download was the detailed analysis written to a file: fourteen
   cards of tables, a correlation matrix, HHI, "Investment Committee Summary".
   Accurate, and unreadable by anybody who is not an analyst. This report is
   built for the owner of the portfolio, and answers their questions in the
   order they ask them:

     1. How am I doing?                     the cover: value, gain, score
     2. What should I do?                   the plan, and the money it moves
     3. What exactly, stock by stock?       one line each: the trade and why
     4. What does that change?              each stock's size now vs after
     5. Where is my money?                  a pie by industry, and vs the market
     6. How good are my stocks?             every score on one scale
     7. What made or lost me money?         rupees won and lost, per stock
     8. Where could new money go?           industries doing well that you lack
     9. How were these calls made?          the rules, the dates, the disclaimer

   Every chart is plain HTML or inline SVG: no chart library, no canvas, no
   network. The same markup is on the page, in the downloaded file (which
   opens offline, years later) and on paper. Every figure it shows is one the
   report already carries — nothing here computes a new opinion.

   Colors: the five calls use one validated set (Exit, Trim, Add, Average,
   Hold in that order around any shared edge: checked for colour-blind
   separation in light and dark), and every call mark also carries its name,
   so colour is never the only cue. Industries use the reference categorical
   slots in fixed order, the rest folded into "Other". Motion runs only on the
   page (`live`), fills `backwards` only, and is off for reduced motion or
   the site's motion switch. */
(function (root) {
  'use strict';

  var ACT = {
    EXIT:    { label: 'Exit',         tag: 'Exit',     cls: 'exit' },
    TRIM:    { label: 'Trim',         tag: 'Trim',     cls: 'trim' },
    AVERAGE: { label: 'Average down', tag: 'Avg down', cls: 'avg' },
    ADD:     { label: 'Add',          tag: 'Add',      cls: 'add' },
    HOLD:    { label: 'Hold',         tag: 'Hold',     cls: 'hold' }
  };
  // Urgency, for anything read as a list.
  var LIST = ['EXIT', 'TRIM', 'AVERAGE', 'ADD', 'HOLD'];
  // Where call colours touch (the stacked bar), this order is the one the
  // palette was validated in: no two neighbours are hard to tell apart.
  var EDGE = ['EXIT', 'TRIM', 'ADD', 'AVERAGE', 'HOLD'];
  var SLICES = 6;          // at most six slices in the pie, the rest "Other"
  var SITE = 'https://altahascreener.in/';

  // ── Formatting ──────────────────────────────────────────────────────────
  function esc(v) {
    return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function finite(v) { return typeof v === 'number' && isFinite(v); }
  function num(v) { var n = typeof v === 'string' ? parseFloat(v) : v; return finite(n) ? n : null; }
  function group(n) {
    // Indian grouping without relying on the runtime's locale data.
    var s = String(Math.round(Math.abs(n))), last = s.slice(-3), rest = s.slice(0, -3);
    if (rest) last = ',' + last;
    return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + last;
  }
  function inr(v) { v = num(v); return v === null ? '—' : (v < 0 ? '−' : '') + '₹' + group(v); }
  function short(v) {
    v = num(v);
    if (v === null) return '—';
    var a = Math.abs(v), s = v < 0 ? '−' : '';
    if (a >= 1e7) return s + '₹' + (a / 1e7).toFixed(a >= 1e9 ? 0 : 2).replace(/\.?0+$/, '') + '\u00a0Cr';
    if (a >= 1e5) return s + '₹' + (a / 1e5).toFixed(2).replace(/\.?0+$/, '') + '\u00a0L';
    return s + '₹' + group(a);
  }
  function pct(v, d) { v = num(v); return v === null ? '—' : v.toFixed(d === undefined ? 1 : d).replace(/\.0$/, '') + '%'; }
  function signed(v, fmt) { v = num(v); return v === null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v)); }
  function when(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d)) return null;
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  }
  function stockHref(sym, base) { return (base || '') + 'stock.html?ticker=' + encodeURIComponent(sym); }
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

  // ── Building blocks ─────────────────────────────────────────────────────
  function section(n, id, q, lede, body) {
    return '<section class="ar-sec" id="' + id + '"><header class="ar-sec-head"><span class="ar-num">' +
      (n < 10 ? '0' + n : n) + '</span><div><h2>' + esc(q) + '</h2>' + (lede ? '<p>' + lede + '</p>' : '') +
      '</div></header>' + body + '</section>';
  }
  // Every chart has its numbers one tap away: the table is the chart's
  // accessible twin, and the only way to read a value without hovering.
  function numbers(head, rows) {
    if (!rows.length) return '';
    return '<details class="ar-data"><summary>See the numbers</summary><div class="ar-scroll"><table>' +
      '<thead><tr>' + head.map(function (h) { return '<th scope="col">' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (r) { return '<tr>' + r.map(function (c, i) { return i ? '<td>' + esc(c) + '</td>' : '<th scope="row">' + esc(c) + '</th>'; }).join('') + '</tr>'; }).join('') +
      '</tbody></table></div></details>';
  }
  function figure(cls, label, inner, caption) {
    return '<figure class="ar-fig ' + cls + '" aria-label="' + esc(label) + '">' + inner +
      (caption ? '<figcaption>' + caption + '</figcaption>' : '') + '</figure>';
  }
  function tile(label, value, note, tone) {
    return '<div class="ar-tile"><span>' + esc(label) + '</span><b class="' + (tone || '') + '">' + value + '</b>' +
      (note ? '<small>' + note + '</small>' : '') + '</div>';
  }
  function empty(text) { return '<p class="ar-empty">' + esc(text) + '</p>'; }

  // ── Derived figures (read from the report, never re-scored) ─────────────
  function holdings(d) {
    return (d.holdings || []).filter(function (r) { return r && num(r.value) > 0; });
  }
  function planOf(d) {
    var p = d.action_plan;
    return p && p.available && (p.actions || []).length ? p : null;
  }
  function callBy(plan) {
    var m = {};
    ((plan && plan.actions) || []).forEach(function (a) { m[a.symbol] = a; });
    return m;
  }
  // Each holding's value after EVERY move in the plan, as a share of what is
  // then invested. (A card's "leaves it at" is that one trade alone; this is
  // the whole plan, so the report quotes only this one.)
  function after(d, plan) {
    var rows = holdings(d), calls = callBy(plan), out = [], total = 0;
    rows.forEach(function (r) {
      var a = calls[r.symbol], m = a && a.move, v = num(r.value);
      if (m && num(m.value) !== null) v = m.side === 'sell' ? Math.max(0, v - m.value) : v + m.value;
      out.push({ symbol: r.symbol, now: num(r.weight_pct), value: v, action: a ? a.action : null });
      total += v;
    });
    out.forEach(function (x) { x.after = total > 0 ? 100 * x.value / total : null; });
    return out;
  }
  function moneyByCall(d, plan) {
    var calls = callBy(plan), by = {};
    EDGE.forEach(function (k) { by[k] = { weight: 0, count: 0, symbols: [] }; });
    holdings(d).forEach(function (r) {
      var a = calls[r.symbol];
      var k = a ? a.action : 'HOLD';
      by[k].weight += num(r.weight_pct) || 0;
      by[k].count += 1;
      by[k].symbols.push(r.symbol);
    });
    return by;
  }

  // ── 0 · The cover ───────────────────────────────────────────────────────
  function ring(score) {
    var s = num(score), v = s === null ? 0 : clamp(s, 0, 100);
    return '<div class="ar-ring" role="img" aria-label="Portfolio score ' + (s === null ? 'unavailable' : Math.round(s) + ' out of 100') + '">' +
      '<svg viewBox="0 0 42 42" aria-hidden="true"><circle class="ar-ring-bg" cx="21" cy="21" r="16" pathLength="100"></circle>' +
      '<circle class="ar-ring-fg" cx="21" cy="21" r="16" pathLength="100" style="stroke-dasharray:' + v.toFixed(1) + ' 100"></circle></svg>' +
      '<div><b>' + (s === null ? '—' : Math.round(s)) + '</b><span>out of 100</span></div></div>';
  }
  function cover(d, plan, opts) {
    var rows = holdings(d), c = d.concentration || {}, top = rows.slice().sort(function (a, b) { return (b.weight_pct || 0) - (a.weight_pct || 0); })[0];
    var cap = num((d.policy || {}).max_stock_pct);
    var pnl = num(d.total_pnl);
    var date = when(d.generated_at) || when(new Date().toISOString());
    var tiles =
      tile('Your portfolio is worth', short(d.total_value), rows.length + ' stock' + (rows.length === 1 ? '' : 's') + (num(d.total_cost) ? ' · you put in ' + short(d.total_cost) : '')) +
      tile('Gain or loss so far', pnl === null ? '—' : signed(pnl, short), pnl === null ? 'Add buy prices to see this' : signed(d.total_pnl_pct, pct) + ' on what you paid', pnl === null ? '' : pnl >= 0 ? 'up' : 'down') +
      tile('Biggest single stock', top ? '<span class="ar-sym">' + esc(top.symbol) + '</span>' : '—', top ? pct(top.weight_pct) + ' of your money' + (cap && top.weight_pct > cap ? ' — above your ' + pct(cap, 0) + ' limit' : '') : '', top && cap && top.weight_pct > cap ? 'warn' : '') +
      tile('Spread', num(c.effective_n) !== null ? num(c.effective_n).toFixed(1) : '—', 'Your money behaves like this many equal-sized stocks');
    return '<header class="ar-cover">' +
      '<div class="ar-brand"><span class="ar-mark" aria-hidden="true">A</span><span>Altaha <i>Screener</i></span><em>Portfolio report' + (date ? ' · ' + esc(date) : '') + '</em></div>' +
      '<div class="ar-cover-main">' + ring(d.weighted_score) +
        '<div><span class="ar-eyebrow">Your portfolio, explained</span>' +
        '<h1>' + esc(plan ? plan.headline : 'Your portfolio review') + '</h1>' +
        (plan && plan.money ? '<p class="ar-money">' + esc(plan.money) + '</p>' : '') +
        '<p class="ar-scoreline">Portfolio score <b>' + (num(d.weighted_score) === null ? '—' : Math.round(d.weighted_score)) + '/100</b>' +
          (d.grade ? ' · grade <b>' + esc(d.grade) + '</b>' : '') + ' — a typical company scores about 50.</p></div></div>' +
      (opts.live ? '<div class="ar-tools"><button type="button" data-ar="download">Download this report</button>' +
        '<button type="button" data-ar="print">Print or save as PDF</button></div>' : '') +
      '<div class="ar-tiles">' + tiles + '</div></header>';
  }

  // ── 1 · Three things that matter ────────────────────────────────────────
  function things(d, plan) {
    var out = [], rows = holdings(d), pol = d.policy || {};
    var first = plan && plan.actions.filter(function (a) { return a.action !== 'HOLD'; })[0];
    if (first) {
      out.push(['Start with ' + first.symbol, ACT[first.action].label + ': ' + plainTrade(first) + '. ' + first.why]);
    } else if (plan) {
      out.push(['Nothing to change', plan.headline]);
    }
    var top = rows.slice().sort(function (a, b) { return (b.weight_pct || 0) - (a.weight_pct || 0); })[0];
    var sec = (d.sectors || []).filter(function (s) { return s.sector && s.sector !== 'Unclassified'; })
      .sort(function (a, b) { return (b.weight_pct || 0) - (a.weight_pct || 0); })[0];
    if (top && num(pol.max_stock_pct) && top.weight_pct > pol.max_stock_pct) {
      out.push(['Too much in one stock', top.symbol + ' is ' + pct(top.weight_pct) + ' of your money, above your own ' +
        pct(pol.max_stock_pct, 0) + ' limit. One bad quarter there would hit your whole portfolio.']);
    } else if (sec && num(pol.max_sector_pct) && sec.weight_pct > pol.max_sector_pct) {
      out.push(['Too much in one sector', sec.sector + ' is ' + pct(sec.weight_pct) + ' of your money, above your ' +
        pct(pol.max_sector_pct, 0) + ' limit. News that hits that sector hits you several times over.']);
    } else if (top) {
      out.push(['Well spread', 'No single stock is above your ' + pct(pol.max_stock_pct || 15, 0) + ' limit. Your biggest, ' +
        top.symbol + ', is ' + pct(top.weight_pct) + ' of your money.']);
    }
    var withPnl = rows.filter(function (r) { return num(r.pnl) !== null; });
    if (withPnl.length) {
      var best = withPnl.slice().sort(function (a, b) { return b.pnl - a.pnl; })[0];
      var worst = withPnl.slice().sort(function (a, b) { return a.pnl - b.pnl; })[0];
      var text = best.pnl > 0 ? best.symbol + ' has made you the most: ' + signed(best.pnl, short) + '.' : '';
      if (worst.pnl < 0) text += (text ? ' ' : '') + worst.symbol + ' has cost you the most: ' + signed(worst.pnl, short) + '.';
      if (text) out.push(['Winners and losers', text]);
    } else {
      out.push(['Add your buy prices', 'Without what you paid, the report cannot say which stocks made or lost you money.']);
    }
    return '<ol class="ar-things">' + out.slice(0, 3).map(function (t, i) {
      return '<li style="--i:' + i + '"><span>' + (i + 1) + '</span><div><h3>' + esc(t[0]) + '</h3><p>' + esc(t[1]) + '</p></div></li>';
    }).join('') + '</ol>';
  }

  // ── 2 · The plan, and the money it touches ──────────────────────────────
  function planSection(d, plan) {
    if (!plan) return empty('No action plan is available for this review yet.');
    var by = moneyByCall(d, plan), counts = plan.counts || {};
    var bar = '<div class="ar-stack" role="img" aria-label="Share of your money by call">' + EDGE.map(function (k, i) {
      var w = by[k].weight;
      if (!(w > 0)) return '';
      return '<span class="ar-seg t-' + ACT[k].cls + '" style="flex-grow:' + w.toFixed(3) + ';--i:' + i + '" title="' +
        esc(ACT[k].label + ': ' + by[k].count + ' stock' + (by[k].count === 1 ? '' : 's') + ', ' + pct(w) + ' of your money') + '"></span>';
    }).join('') + '</div>';
    var legend = '<ul class="ar-legend">' + EDGE.map(function (k) {
      var n = counts[k] || 0;
      return '<li class="' + (n ? '' : 'zero') + '"><i class="t-' + ACT[k].cls + '"></i>' + esc(ACT[k].label) +
        ' <b>' + n + '</b><small>' + (n ? pct(by[k].weight) + ' of your money' : 'none') + '</small></li>';
    }).join('') + '</ul>';
    var freed = num(plan.freed) || 0, needed = num(plan.needed) || 0, net = needed - freed;
    var flow = '<div class="ar-tiles three">' +
      tile('You would sell', freed ? short(freed) : '—', freed ? 'from the stocks to exit or trim' : 'nothing to sell') +
      tile('You would buy', needed ? short(needed) : '—', needed ? 'to add to or average down' : 'nothing to buy') +
      tile(net > 0 ? 'New money needed' : 'Cash left over', short(Math.abs(net)),
        net > 0 ? 'if you make every buy' : 'after every sale and buy') + '</div>';
    return figure('ar-planfig', 'How much of your money each call touches', bar + legend,
      'Each band is the share of your money in stocks with that call. ' +
      'Hover a band, or open the numbers below, for the stocks in it.') +
      numbers(['Call', 'Stocks', 'Share of your money', 'Which'], EDGE.filter(function (k) { return by[k].count; }).map(function (k) {
        return [ACT[k].label, by[k].count, pct(by[k].weight), by[k].symbols.join(', ')];
      })) + flow;
  }

  // ── 3 · Stock by stock ──────────────────────────────────────────────────
  function plainTrade(a) {
    var m = a.move;
    if (!m) return a.action === 'HOLD' ? 'no change needed' : String(a.todo || '');
    return (m.side === 'sell' ? (m.all ? 'sell all ' + m.shares + ' shares' : 'sell ' + m.shares + ' of ' + m.of_shares + ' shares')
      : 'buy ' + m.shares + ' more') + ' (' + inr(m.value) + ')';
  }
  function trade(a) {
    var m = a.move;
    if (!m) return a.action === 'HOLD' ? 'No change needed' : esc(a.todo || '');
    var s = m.side === 'sell'
      ? (m.all ? 'Sell all ' + m.shares + ' shares' : 'Sell ' + m.shares + ' of ' + m.of_shares + ' shares')
      : 'Buy ' + m.shares + ' more';
    s += ' · ' + inr(m.value);
    if (a.action === 'AVERAGE' && num(m.avg_cost_after) !== null) {
      s += ' — your average cost falls from ' + inr(m.avg_cost_before) + ' to ' + inr(m.avg_cost_after);
    }
    return esc(s);
  }
  function actionsSection(d, plan, base) {
    if (!plan) return empty('No calls to show.');
    var rows = holdings(d), info = {};
    rows.forEach(function (r) { info[r.symbol] = r; });
    var html = '<div class="ar-calls">';
    LIST.forEach(function (k) {
      var list = plan.actions.filter(function (a) { return a.action === k; });
      if (!list.length) return;
      html += '<h3 class="ar-callhead t-' + ACT[k].cls + '"><i></i>' + esc(ACT[k].label) + ' <small>' + list.length +
        ' stock' + (list.length === 1 ? '' : 's') + '</small></h3><ul class="ar-rows">';
      list.forEach(function (a) {
        var r = info[a.symbol] || {};
        var score = num(a.score);
        html += '<li class="ar-row">' +
          '<div class="ar-who"><a href="' + esc(stockHref(a.symbol, base)) + '" target="_blank" rel="noopener">' + esc(a.symbol) + '</a>' +
            '<small>' + esc([r.name && r.name !== a.symbol ? r.name : null, r.industry || a.sector].filter(Boolean).join(' · ')) + '</small></div>' +
          '<div class="ar-meter" title="Altaha Score ' + (score === null ? 'unavailable' : Math.round(score) + ' out of 100') + '">' +
            '<b>' + (score === null ? '—' : Math.round(score)) + '</b><span><i style="width:' + (score === null ? 0 : clamp(score, 0, 100)) + '%"></i></span></div>' +
          '<div class="ar-what"><p class="ar-trade t-' + ACT[k].cls + '">' + trade(a) + '</p><p>' + esc(a.why) + '</p>' +
            (a.switch ? '<p class="ar-switch">⇄ ' + esc(a.switch) + '</p>' : '') + '</div></li>';
      });
      html += '</ul>';
    });
    return html + '</div>';
  }

  // ── 4 · Now vs after the plan ───────────────────────────────────────────
  function beforeAfter(d, plan) {
    if (!plan) return '';
    var rows = after(d, plan).filter(function (x) { return x.now !== null; })
      .sort(function (a, b) { return b.now - a.now; }).slice(0, 15);
    if (!rows.length) return '';
    var cap = num((d.policy || {}).max_stock_pct);
    var hi = Math.max.apply(null, rows.map(function (x) { return Math.max(x.now, x.after || 0); }).concat([cap || 0]));
    hi = Math.ceil(hi * 1.12 / 5) * 5 || 10;
    var x = function (v) { return (100 * clamp(v, 0, hi) / hi).toFixed(2) + '%'; };
    var body = '<div class="ar-dumb">' +
      (cap ? '<div class="ar-ref ar-limit" style="--f:' + (clamp(cap, 0, hi) / hi).toFixed(4) + '"><span>Your limit ' + pct(cap, 0) + '</span></div>' : '') +
      rows.map(function (r, i) {
        var moved = r.action && r.action !== 'HOLD' && r.after !== null && Math.abs(r.after - r.now) >= 0.05;
        var lo = Math.min(r.now, r.after), cls = r.action ? ACT[r.action].cls : 'hold';
        return '<div class="ar-drow" style="--i:' + i + '" title="' + esc(r.symbol + ': ' + pct(r.now) + ' now' + (moved ? ', ' + pct(r.after) + ' after the plan' : ', unchanged')) + '">' +
          '<span class="ar-dlab">' + esc(r.symbol) + '</span><span class="ar-dtrack">' +
          (moved ? '<i class="ar-dline t-' + cls + '" style="left:' + x(lo) + ';width:calc(' + x(Math.max(r.now, r.after)) + ' - ' + x(lo) + ')"></i>' : '') +
          '<i class="ar-dot now" style="left:' + x(r.now) + '"></i>' +
          (moved ? '<i class="ar-dot then t-' + cls + '" style="left:' + x(r.after) + '"></i>' : '') +
          '</span><span class="ar-dval">' + pct(r.now) + (moved ? ' → <b>' + pct(r.after) + '</b>' : r.after !== null ? ' → ' + pct(r.after) : '') + '</span></div>';
      }).join('') + '</div>';
    var freed = num(plan.freed) || 0, needed = num(plan.needed) || 0;
    return figure('ar-dumbfig', 'Each stock as a share of your money, now and after the plan',
      '<ul class="ar-legend small"><li><i class="now"></i>Now</li><li><i class="then"></i>After every move (coloured by its call)</li>' +
      (cap ? '<li><i class="lim"></i>Your limit for one stock</li>' : '') + '</ul>' + body,
      'If you make every move — sell ' + short(freed) + ', buy ' + short(needed) + ' — this is how big each stock would be. ' +
      'Largest ' + rows.length + ' shown.') +
      numbers(['Stock', 'Now', 'After the plan', 'Call'], rows.map(function (r) {
        return [r.symbol, pct(r.now), r.after === null ? '—' : pct(r.after), r.action ? ACT[r.action].label : '—'];
      }));
  }

  // ── 5 · Where is my money? ──────────────────────────────────────────────
  function slices(d) {
    var list = (d.sectors || []).filter(function (s) { return num(s.weight_pct) > 0; })
      .map(function (s) { return { name: s.sector || 'Unclassified', w: s.weight_pct, n: s.count || 0 }; })
      .sort(function (a, b) { return b.w - a.w; });
    if (list.length <= SLICES) return list;
    var keep = list.slice(0, SLICES - 1), rest = list.slice(SLICES - 1);
    keep.push({ name: 'Other (' + rest.length + ')', w: rest.reduce(function (t, s) { return t + s.w; }, 0),
                n: rest.reduce(function (t, s) { return t + s.n; }, 0), other: true, members: rest.map(function (s) { return s.name; }) });
    return keep;
  }
  function donut(parts, center, sub) {
    var total = parts.reduce(function (t, p) { return t + p.w; }, 0) || 1, at = 0, gap = parts.length > 1 ? 0.7 : 0;
    var arcs = parts.map(function (p, i) {
      var len = Math.max(0.01, 100 * p.w / total - gap);
      var c = '<circle class="ar-arc s' + (p.other ? 'x' : i + 1) + '" cx="21" cy="21" r="15.9155" pathLength="100" ' +
        'style="stroke-dasharray:' + len.toFixed(3) + ' ' + (100 - len).toFixed(3) + ';stroke-dashoffset:' + (-at).toFixed(3) + ';--i:' + i + '">' +
        '<title>' + esc(p.name + ': ' + pct(p.w) + ' of your money, ' + p.n + ' stock' + (p.n === 1 ? '' : 's')) + '</title></circle>';
      at += 100 * p.w / total;
      return c;
    }).join('');
    return '<div class="ar-donut"><svg viewBox="0 0 42 42" role="img" aria-label="Your money by sector">' +
      '<g transform="rotate(-90 21 21)">' + arcs + '</g></svg><div><b>' + esc(center) + '</b><span>' + esc(sub) + '</span></div></div>';
  }
  function moneyMap(d) {
    var parts = slices(d);
    if (!parts.length) return empty('No priced holdings to map.');
    var legend = '<ul class="ar-pielegend">' + parts.map(function (p, i) {
      return '<li><i class="s' + (p.other ? 'x' : i + 1) + '"></i><span>' + esc(p.name) + '</span><b>' + pct(p.w) + '</b></li>';
    }).join('') + '</ul>';
    var pie = figure('ar-piefig', 'Your money by sector', '<div class="ar-pie">' +
      donut(parts, String((d.sectors || []).length), 'sector' + ((d.sectors || []).length === 1 ? '' : 's')) + legend + '</div>',
      parts.some(function (p) { return p.other; }) ? 'Smaller sectors are grouped as "Other" so the pie stays readable.' : '');

    // You vs the market: the same industries, side by side.
    var comp = (d.sector_comparison || []).filter(function (s) { return num(s.weight_pct) !== null || num(s.benchmark_weight_pct) !== null; })
      .map(function (s) { return { name: s.sector, you: num(s.weight_pct) || 0, mkt: num(s.benchmark_weight_pct) || 0 }; })
      .sort(function (a, b) { return Math.max(b.you, b.mkt) - Math.max(a.you, a.mkt); }).slice(0, 9);
    var hi = Math.max.apply(null, comp.map(function (s) { return Math.max(s.you, s.mkt); }).concat([1]));
    var bench = (d.benchmark && d.benchmark.name) || 'the market';
    var pairs = comp.length ? figure('ar-vsfig', 'Your share of each sector against ' + bench,
      '<ul class="ar-legend small"><li><i class="you"></i>You</li><li><i class="mkt"></i>' + esc(bench) + '</li></ul>' +
      '<div class="ar-pairs">' + comp.map(function (s, i) {
        var diff = s.you - s.mkt;
        return '<div class="ar-pair" style="--i:' + i + '"><span class="ar-plab">' + esc(s.name) +
          '<small>' + (Math.abs(diff) < 2 ? 'about the same as the market' : diff > 0 ? 'more than the market' : 'less than the market') + '</small></span>' +
          '<span class="ar-pbars"><i class="you" style="width:' + (100 * s.you / hi).toFixed(2) + '%" title="You: ' + pct(s.you) + '"></i>' +
          '<i class="mkt" style="width:' + (100 * s.mkt / hi).toFixed(2) + '%" title="' + esc(bench) + ': ' + pct(s.mkt) + '"></i></span>' +
          '<span class="ar-pval"><b>' + pct(s.you) + '</b><small>' + pct(s.mkt) + '</small></span></div>';
      }).join('') + '</div>',
      'Longer gold bar than grey: you own more of that sector than the market does. Market weights: ' +
        esc([bench, d.benchmark && d.benchmark.as_of].filter(Boolean).join(', ')) + ', approximate.') : '';
    return '<div class="ar-two">' + pie + pairs + '</div>' +
      numbers(['Sector', 'Your money', 'Stocks', bench], (d.sectors || []).slice().sort(function (a, b) { return (b.weight_pct || 0) - (a.weight_pct || 0); })
        .map(function (s) { return [s.sector, pct(s.weight_pct), s.count || 0, pct(s.benchmark_weight_pct)]; }));
  }

  // ── 6 · How good are my stocks? ─────────────────────────────────────────
  var BANDS = [
    ['Exceptional', 'b1'], ['Strong', 'b2'], ['Good', 'b3'], ['Average', 'b4'],
    ['Weak', 'b5'], ['High concern', 'b6'], ['Unscored', 'b7']
  ];
  function quality(d, plan) {
    var calls = callBy(plan);
    var rows = holdings(d).filter(function (r) { return num(r.composite) !== null; })
      .sort(function (a, b) { return b.composite - a.composite; });
    if (!rows.length) return empty('No holding has an Altaha Score yet.');
    var bars = '<div class="ar-scores"><div class="ar-ref ar-typical" style="--f:.5"><span>Typical company ≈ 50</span></div>' + rows.map(function (r, i) {
      var s = clamp(r.composite, 0, 100), a = calls[r.symbol];
      return '<div class="ar-srow" style="--i:' + i + '" title="' + esc(r.symbol + ': ' + Math.round(r.composite) + ' out of 100') + '">' +
        '<span class="ar-slab">' + esc(r.symbol) + (a ? '<em class="t-' + ACT[a.action].cls + '">' + esc(ACT[a.action].tag) + '</em>' : '') + '</span>' +
        '<span class="ar-strack"><i class="ar-bar" style="width:' + s.toFixed(1) + '%"></i></span>' +
        '<b class="ar-sval">' + Math.round(r.composite) + '</b></div>';
    }).join('') + '</div>';
    var dist = (d.score_distribution || []).filter(function (b) { return num(b.weight_pct) > 0; });
    var cls = {};
    BANDS.forEach(function (b) { cls[b[0]] = b[1]; });
    var stack = dist.length ? '<h3 class="ar-subhead">How much of your money sits in each score band</h3>' +
      '<div class="ar-stack bands" role="img" aria-label="Share of your money by score band">' + dist.map(function (b, i) {
        return '<span class="ar-seg ' + (cls[b.label] || 'b7') + '" style="flex-grow:' + b.weight_pct.toFixed(3) + ';--i:' + i + '" title="' +
          esc(b.label + ': ' + pct(b.weight_pct) + ' of your money, ' + b.count + ' stock' + (b.count === 1 ? '' : 's')) + '">' +
          (b.weight_pct >= 11 ? '<em>' + pct(b.weight_pct, 0) + '</em>' : '') + '</span>';
      }).join('') + '</div><ul class="ar-legend">' + dist.map(function (b) {
        return '<li><i class="' + (cls[b.label] || 'b7') + '"></i>' + esc(b.label) + (b.floor !== null && b.floor !== undefined ? ' <small>' + (b.floor ? b.floor + '+' : 'under 40') + '</small>' : '') +
          ' <b>' + pct(b.weight_pct) + '</b></li>';
      }).join('') + '</ul>' : '';
    return figure('ar-scorefig', 'Every holding\'s Altaha Score out of 100', bars + stack,
      'The Altaha Score ranks a company against about two hundred others on quality, growth, value, momentum and risk. ' +
      'It measures evidence, not the chance of a profit.') +
      numbers(['Stock', 'Score', 'Call', 'Share of your money'], rows.map(function (r) {
        var a = calls[r.symbol];
        return [r.symbol, Math.round(r.composite), a ? ACT[a.action].label : '—', pct(r.weight_pct)];
      }));
  }

  // ── 7 · What made or lost me money? ─────────────────────────────────────
  function winners(d) {
    var rows = holdings(d).filter(function (r) { return num(r.pnl) !== null; });
    if (!rows.length) return empty('Add the price you paid for each stock to see what made or lost you money.');
    rows.sort(function (a, b) { return b.pnl - a.pnl; });
    var shown = rows.length <= 14 ? rows : rows.slice(0, 7).concat(rows.slice(-7));
    var hi = Math.max.apply(null, shown.map(function (r) { return Math.abs(r.pnl); }).concat([1]));
    var up = rows.filter(function (r) { return r.pnl > 0; }).reduce(function (t, r) { return t + r.pnl; }, 0);
    var down = rows.filter(function (r) { return r.pnl < 0; }).reduce(function (t, r) { return t + r.pnl; }, 0);
    var body = '<div class="ar-div">' + shown.map(function (r, i) {
      var w = (50 * Math.abs(r.pnl) / hi).toFixed(2);
      return '<div class="ar-vrow" style="--i:' + i + '" title="' + esc(r.symbol + ': ' + signed(r.pnl, inr) + ' (' + signed(r.pnl_pct, pct) + ')') + '">' +
        '<span class="ar-vlab">' + esc(r.symbol) + '</span><span class="ar-vtrack"><i class="ar-vbar ' + (r.pnl >= 0 ? 'up' : 'down') + '" style="width:' + w + '%"></i></span>' +
        '<span class="ar-vval ' + (r.pnl >= 0 ? 'up' : 'down') + '">' + signed(r.pnl, short) + '<small>' + signed(r.pnl_pct, pct) + '</small></span></div>';
    }).join('') + '</div>';
    return '<div class="ar-tiles three">' +
      tile('Made on winners', up ? signed(up, short) : '—', rows.filter(function (r) { return r.pnl > 0; }).length + ' stocks up', 'up') +
      tile('Lost on losers', down ? signed(down, short) : '—', rows.filter(function (r) { return r.pnl < 0; }).length + ' stocks down', down ? 'down' : '') +
      tile('Overall', signed(d.total_pnl, short), signed(d.total_pnl_pct, pct) + ' on what you paid', num(d.total_pnl) >= 0 ? 'up' : 'down') + '</div>' +
      figure('ar-divfig', 'Gain or loss in rupees on each stock since you bought it', body,
        'Gains to the right, losses to the left. These are gains and losses on paper — nothing is locked in until you sell.' +
        (shown.length < rows.length ? ' The seven biggest gains and losses are shown.' : '')) +
      numbers(['Stock', 'Gain or loss', 'Return', 'Paid'], rows.map(function (r) {
        return [r.symbol, signed(r.pnl, inr), signed(r.pnl_pct, pct), inr(r.cost)];
      }));
  }

  // ── 8 · Where could new money go? ───────────────────────────────────────
  function whereNext(d, plan, base) {
    var rot = (plan && plan.rotation) || [], swaps = [];
    ((plan && plan.actions) || []).forEach(function (a) {
      (a.alternatives || []).slice(0, 1).forEach(function (x) { swaps.push([a, x]); });
    });
    var html = '';
    if (rot.length) {
      html += '<div class="ar-rots">' + rot.map(function (r, i) {
        var hi = Math.max(r.your_weight_pct || 0, r.market_weight_pct || 0, 1);
        return '<article class="ar-rot" style="--i:' + i + '"><span class="ar-up">▲ ' + pct(r.relative_3m) + ' ahead of the Nifty 50 · 3 months</span>' +
          '<h3>' + esc(r.sector) + '</h3><p>' + esc(r.why) + '</p>' +
          '<div class="ar-mini"><span>You</span><i class="you" style="width:' + (100 * (r.your_weight_pct || 0) / hi).toFixed(1) + '%"></i><b>' + pct(r.your_weight_pct) + '</b>' +
          '<span>Market</span><i class="mkt" style="width:' + (100 * (r.market_weight_pct || 0) / hi).toFixed(1) + '%"></i><b>' + pct(r.market_weight_pct) + '</b></div>' +
          '<p class="ar-picks">Best-scoring there: ' + r.stocks.map(function (s) {
            return '<a href="' + esc(stockHref(s.symbol, base)) + '" target="_blank" rel="noopener">' + esc(s.symbol) + ' <b>' + Math.round(s.score) + '</b></a>';
          }).join(' ') + '</p></article>';
      }).join('') + '</div>';
    }
    if (swaps.length) {
      html += '<h3 class="ar-subhead">Stronger companies in the same industry as ones you own</h3><ul class="ar-swaps">' + swaps.map(function (p) {
        return '<li><span class="ar-from">' + esc(p[0].symbol) + ' <small>' + Math.round(p[0].score || 0) + '</small></span><i aria-hidden="true">→</i>' +
          '<a href="' + esc(stockHref(p[1].symbol, base)) + '" target="_blank" rel="noopener">' + esc(p[1].symbol) + ' <small>' + Math.round(p[1].score) + '</small></a>' +
          (p[1].group ? '<em>' + esc(p[1].group) + '</em>' : '') + '</li>';
      }).join('') + '</ul>';
    }
    return html || empty('Nothing stands out: the sectors beating the market are ones you already hold in proportion, and no holding has a clearly stronger company in exactly its own industry among those we score.');
  }

  // ── 9 · How the calls were made ─────────────────────────────────────────
  function method(d, plan) {
    var q = d.data_quality || {};
    var dates = [
      q.score_as_of && when(q.score_as_of) ? 'Scores as of ' + when(q.score_as_of) : null,
      (q.price_dates || []).length ? 'Prices from ' + q.price_dates.map(function (x) { return when(x) || x; })
        .filter(function (x, i, all) { return all.indexOf(x) === i; }).join(', ') : null,
      d.benchmark && d.benchmark.name ? 'Market weights: ' + d.benchmark.name + (d.benchmark.as_of ? ' (' + d.benchmark.as_of + ', approximate)' : '') : null
    ].filter(Boolean);
    return '<div class="ar-method">' +
      (plan && plan.method ? '<h3>The rules</h3><p>' + esc(plan.method) + '</p>' : '') +
      '<h3>Switch ideas</h3><p>Only ever a company in exactly the same industry, of a similar size (within five times its market value either way), ' +
      'that scores clearly higher and that you do not already own. Where none exists, there is no switch idea.</p>' +
      (dates.length ? '<h3>The data</h3><p>' + esc(dates.join(' · ')) + '.</p>' : '') +
      '<p class="ar-disclaimer">' + esc((plan && plan.disclaimer) || d.disclaimer ||
        'Altaha is not registered with SEBI as an investment adviser or research analyst. This report is information, not advice.') + '</p></div>';
  }

  // ── The report ──────────────────────────────────────────────────────────
  function build(d, opts) {
    opts = opts || {};
    d = d || {};
    var plan = planOf(d), base = opts.base === undefined ? '' : opts.base, n = 0;
    var parts = [
      section(++n, 'ar-now', 'The three things that matter most', null, things(d, plan)),
      section(++n, 'ar-plan', 'What should I do?', 'Every stock gets one call: exit, trim, average down, add or hold.', planSection(d, plan)),
      section(++n, 'ar-calls', 'What exactly, stock by stock?', 'Most urgent first. Each line is the trade, the Altaha Score, and the reason.', actionsSection(d, plan, base))
    ];
    var ba = beforeAfter(d, plan);
    if (ba) parts.push(section(++n, 'ar-after', 'What does the plan change?', 'Each stock\'s share of your money today, and after every move.', ba));
    parts.push(
      section(++n, 'ar-money', 'Where is my money?', 'By sector, and against the market as a whole.', moneyMap(d)),
      section(++n, 'ar-quality', 'How good are my stocks?', 'Every holding\'s Altaha Score on one scale.', quality(d, plan)),
      section(++n, 'ar-pnl', 'What made or lost me money?', 'In rupees, since you bought each stock.', winners(d)),
      section(++n, 'ar-next', 'Where could new money go?', 'Sectors beating the market where you own less than the market does, and stronger companies in exactly the same industry as ones you own.', whereNext(d, plan, base)),
      section(++n, 'ar-how', 'How were these calls made?', null, method(d, plan))
    );
    return '<article class="ar-root' + (opts.live ? ' ar-live' : '') + '">' + cover(d, plan, opts) + parts.join('') +
      '<footer class="ar-foot">Altaha Screener · altahascreener.in · Scores are computed from public data with disclosed rules. ' +
      'Markets carry risk of loss.</footer></article>';
  }

  // ── Styles (one copy: injected on the page, embedded in the file) ───────
  var CSS = [
    '.ar-root{--ar-bg:#FFFDF8;--ar-panel:#F6F1E6;--ar-ink:#17140E;--ar-ink2:#4A4539;--ar-mute:#7A7263;--ar-rule:#E6DFCF;--ar-track:#EFE9DC;',
    '--ar-gold:#A38338;--ar-mkt:#B4AD9E;--ar-up:#1F7A55;--ar-down:#B03A2B;--ar-warn:#9A6400;',
    '--ar-exit:#B03A2B;--ar-trim:#C98500;--ar-add:#1F7A55;--ar-avg:#3F6FB0;--ar-hold:#9A9384;',
    '--ar-s1:#2a78d6;--ar-s2:#eb6834;--ar-s3:#1baf7a;--ar-s4:#eda100;--ar-s5:#e87ba4;--ar-s6:#008300;--ar-sx:#B4AD9E;',
    '--ar-b1:#184f95;--ar-b2:#2a78d6;--ar-b3:#86b6ef;--ar-b4:#D8D3C6;--ar-b5:#EC8A7F;--ar-b6:#B03A2B;--ar-b7:#CFC9BB;',
    '--ar-serif:var(--serif,Georgia,"Times New Roman",serif);--ar-sans:var(--sans,Inter,system-ui,-apple-system,"Segoe UI",sans-serif);--ar-mono:var(--mono,"IBM Plex Mono",ui-monospace,monospace);',
    'background:var(--ar-bg);color:var(--ar-ink);font:15px/1.6 var(--ar-sans);max-width:1000px;margin:0 auto;border-radius:24px;overflow:hidden;',
    'box-shadow:0 1px 0 var(--ar-rule),0 18px 44px rgba(23,20,14,.08)}',
    ':root[data-theme="dark"] .ar-root{--ar-bg:#17150F;--ar-panel:#201D16;--ar-ink:#F3EEE3;--ar-ink2:#CFC7B6;--ar-mute:#A59C8A;--ar-rule:#2F2B22;--ar-track:#2A261E;',
    '--ar-gold:#D9BC6A;--ar-mkt:#6F6858;--ar-up:#3FBF87;--ar-down:#E0614F;--ar-warn:#E0A526;',
    '--ar-exit:#C4364F;--ar-trim:#B88A12;--ar-add:#2E9E6E;--ar-avg:#5B87CC;--ar-hold:#A8A08E;',
    '--ar-s1:#3987e5;--ar-s2:#d95926;--ar-s3:#199e70;--ar-s4:#c98500;--ar-s5:#d55181;--ar-s6:#008300;--ar-sx:#6F6858;',
    '--ar-b1:#86b6ef;--ar-b2:#3987e5;--ar-b3:#1c5cab;--ar-b4:#4A463C;--ar-b5:#A8483C;--ar-b6:#E0614F;--ar-b7:#3A362D;box-shadow:none}',
    '.ar-root *{box-sizing:border-box}',
    '.pf-visual-host{max-width:1000px;margin:28px auto 8px;scroll-margin-top:150px}.pf-visual-host[hidden]{display:none}',
    '.ar-root a{color:inherit;text-decoration-color:var(--ar-gold);text-underline-offset:3px}',
    '.t-exit{--t:var(--ar-exit)}.t-trim{--t:var(--ar-trim)}.t-avg{--t:var(--ar-avg)}.t-add{--t:var(--ar-add)}.t-hold{--t:var(--ar-hold)}',

    /* Cover */
    '.ar-cover{background:radial-gradient(120% 140% at 0% 0%,#3a2f14 0%,#17140E 58%),#17140E;color:#FBF8F1;padding:clamp(22px,4vw,44px)}',
    '.ar-brand{display:flex;flex-wrap:wrap;align-items:center;gap:10px;font:500 20px/1 var(--ar-serif)}',
    '.ar-brand i{color:#D9BC6A}.ar-brand em{font:500 11px/1 var(--ar-mono);letter-spacing:.14em;text-transform:uppercase;color:rgba(251,248,241,.62);font-style:normal;margin-left:auto}',
    '.ar-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:#D9BC6A;color:#17140E;font:700 17px/1 var(--ar-serif)}',
    '.ar-cover-main{display:grid;grid-template-columns:auto minmax(0,1fr);gap:clamp(18px,4vw,40px);align-items:center;margin:clamp(22px,4vw,36px) 0 24px}',
    '.ar-ring{position:relative;width:clamp(116px,16vw,160px);aspect-ratio:1}',
    '.ar-ring svg{width:100%;height:100%;transform:rotate(-90deg)}.ar-ring circle{fill:none;stroke-width:4.2}',
    '.ar-ring-bg{stroke:rgba(251,248,241,.14)}.ar-ring-fg{stroke:#D9BC6A;stroke-linecap:round}',
    '.ar-ring div{position:absolute;inset:0;display:grid;place-content:center;text-align:center}',
    '.ar-ring b{font:600 clamp(34px,4.6vw,48px)/1 var(--ar-sans);letter-spacing:-.02em}',
    '.ar-ring span{font:500 10px/1.3 var(--ar-mono);letter-spacing:.1em;text-transform:uppercase;color:rgba(251,248,241,.7);margin-top:4px}',
    '.ar-eyebrow{font:500 11px/1 var(--ar-mono);letter-spacing:.16em;text-transform:uppercase;color:#D9BC6A}',
    '.ar-cover h1{font:400 clamp(24px,3.3vw,36px)/1.15 var(--ar-serif);letter-spacing:-.015em;margin:10px 0 10px;color:#FBF8F1}',
    '.ar-money,.ar-scoreline{margin:0 0 6px;color:rgba(251,248,241,.8)}.ar-scoreline b{color:#FBF8F1}',
    '.ar-tools{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}',
    '.ar-tools button{font:600 13px/1 var(--ar-sans);padding:11px 16px;border-radius:999px;border:1px solid rgba(217,188,106,.55);background:transparent;color:#FBF8F1;cursor:pointer;min-height:40px}',
    '.ar-tools button:first-child{background:#D9BC6A;color:#17140E;border-color:#D9BC6A}',
    '.ar-tools button:focus-visible{outline:2px solid #D9BC6A;outline-offset:2px}',
    '.ar-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}',
    '.ar-tiles.three{grid-template-columns:repeat(3,minmax(0,1fr));margin:18px 0 4px}',
    '.ar-tiles.three+.ar-fig{margin-top:22px}',
    '.ar-tile{padding:14px 16px;border-radius:14px;background:rgba(251,248,241,.07);border:1px solid rgba(251,248,241,.1);min-width:0}',
    '.ar-tile span{display:block;font:500 11px/1.3 var(--ar-mono);letter-spacing:.08em;text-transform:uppercase;color:rgba(251,248,241,.62)}',
    '.ar-tile b{display:block;font:600 clamp(20px,2.4vw,26px)/1.15 var(--ar-sans);margin:6px 0 2px;overflow-wrap:anywhere}',
    '.ar-tile small{display:block;font-size:12.5px;line-height:1.4;color:rgba(251,248,241,.66)}',
    '.ar-cover .ar-tile b.up{color:#7FD9AE}.ar-cover .ar-tile b.down{color:#F08A7A}.ar-cover .ar-tile b.warn{color:#F2C46A}',
    '.ar-sec .ar-tile{background:var(--ar-panel);border-color:var(--ar-rule)}',
    '.ar-sec .ar-tile span{color:var(--ar-mute)}.ar-sec .ar-tile small{color:var(--ar-mute)}',
    '.ar-sec .ar-tile b.up{color:var(--ar-up)}.ar-sec .ar-tile b.down{color:var(--ar-down)}',

    /* Sections */
    '.ar-sec{padding:clamp(22px,4vw,40px) clamp(18px,4vw,44px);border-top:1px solid var(--ar-rule)}',
    '.ar-sec-head{display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;align-items:start;margin-bottom:18px}',
    '.ar-num{font:500 12px/1 var(--ar-mono);color:var(--ar-gold);letter-spacing:.1em;padding-top:9px}',
    '.ar-sec h2{font:400 clamp(22px,2.8vw,30px)/1.2 var(--ar-serif);letter-spacing:-.01em;margin:0}',
    '.ar-sec-head p{margin:6px 0 0;color:var(--ar-ink2)}',
    '.ar-subhead{font:600 14px/1.4 var(--ar-sans);margin:26px 0 10px}',
    '.ar-empty{color:var(--ar-mute);margin:0}',
    '.ar-fig{margin:0}.ar-fig figcaption{font-size:13px;color:var(--ar-mute);margin-top:12px;line-height:1.5}',

    /* Three things */
    '.ar-things{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}',
    '.ar-things li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;padding:16px;border-radius:16px;background:var(--ar-panel);border:1px solid var(--ar-rule)}',
    '.ar-things li>span{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--ar-ink);color:var(--ar-bg);font:600 14px/1 var(--ar-sans)}',
    '.ar-things h3{font:600 15px/1.3 var(--ar-sans);margin:4px 0 4px}.ar-things p{margin:0;font-size:14px;color:var(--ar-ink2)}',

    /* Stacked bars and legends */
    '.ar-stack{display:flex;gap:2px;height:44px;border-radius:10px;overflow:hidden;background:var(--ar-track)}',
    '.ar-stack.bands{height:30px}',
    '.ar-seg{flex:1 1 0;min-width:4px;background:var(--t,var(--ar-hold));display:flex;align-items:center;justify-content:center;transform-origin:left center}',
    '.ar-seg em{font:600 12.5px/1 var(--ar-sans);font-style:normal;color:#fff;white-space:nowrap;overflow:visible;padding:0 6px}',
    '.ar-stack.bands .ar-seg em{font-size:11.5px}',
    '.ar-stack.bands .b3 em,.ar-stack.bands .b4 em,.ar-stack.bands .b5 em,.ar-stack.bands .b7 em{color:#17140E}',
    '.ar-seg.b1{background:var(--ar-b1)}.ar-seg.b2{background:var(--ar-b2)}.ar-seg.b3{background:var(--ar-b3)}.ar-seg.b4{background:var(--ar-b4)}',
    '.ar-seg.b5{background:var(--ar-b5)}.ar-seg.b6{background:var(--ar-b6)}.ar-seg.b7{background:var(--ar-b7)}',
    '.ar-legend{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13.5px;color:var(--ar-ink2)}',
    '.ar-legend li{display:flex;align-items:center;gap:7px}.ar-legend li.zero{opacity:.55}',
    '.ar-legend b{color:var(--ar-ink)}.ar-legend small{color:var(--ar-mute);font-size:12px}',
    '.ar-legend i{width:12px;height:12px;border-radius:3px;background:var(--t,var(--ar-hold));flex:none}',
    '.ar-legend i.b1{background:var(--ar-b1)}.ar-legend i.b2{background:var(--ar-b2)}.ar-legend i.b3{background:var(--ar-b3)}.ar-legend i.b4{background:var(--ar-b4)}',
    '.ar-legend i.b5{background:var(--ar-b5)}.ar-legend i.b6{background:var(--ar-b6)}.ar-legend i.b7{background:var(--ar-b7)}',
    '.ar-legend.small{margin:0 0 12px;font-size:12.5px}',
    '.ar-legend i.now{border-radius:50%;background:var(--ar-bg);box-shadow:inset 0 0 0 2.5px var(--ar-mute)}',
    '.ar-legend i.then{border-radius:50%;background:conic-gradient(var(--ar-exit) 0 25%,var(--ar-trim) 0 50%,var(--ar-add) 0 75%,var(--ar-avg) 0)}',
    '.ar-legend i.lim{width:3px;height:14px;border-radius:2px;background:var(--ar-trim)}',
    '.ar-legend i.you{background:var(--ar-gold)}.ar-legend i.mkt{background:var(--ar-mkt)}',

    /* Stock by stock */
    '.ar-callhead{display:flex;align-items:center;gap:9px;font:600 13px/1 var(--ar-mono);letter-spacing:.1em;text-transform:uppercase;margin:26px 0 8px;color:var(--ar-ink)}',
    '.ar-callhead:first-child{margin-top:0}.ar-callhead i{width:12px;height:12px;border-radius:3px;background:var(--t)}',
    '.ar-callhead small{font:500 12px/1 var(--ar-sans);letter-spacing:0;text-transform:none;color:var(--ar-mute)}',
    '.ar-rows{list-style:none;margin:0;padding:0;border-top:1px solid var(--ar-rule)}',
    '.ar-row{display:grid;grid-template-columns:minmax(120px,1.1fr) 92px minmax(0,3fr);gap:16px;padding:14px 0;border-bottom:1px solid var(--ar-rule);align-items:start;break-inside:avoid}',
    '.ar-who a{font:700 15px/1.2 var(--ar-sans);text-decoration:none}.ar-who a:hover{text-decoration:underline}',
    '.ar-who small{display:block;font-size:12.5px;color:var(--ar-mute);line-height:1.35;margin-top:3px}',
    '.ar-meter b{font:600 18px/1 var(--ar-sans)}.ar-meter span{display:block;height:6px;border-radius:3px;background:var(--ar-track);margin-top:7px;overflow:hidden}',
    '.ar-meter i{display:block;height:100%;border-radius:3px;background:var(--ar-gold)}',
    '.ar-what p{margin:0 0 4px;font-size:14px;color:var(--ar-ink2)}',
    '.ar-trade{font-weight:700;color:var(--ar-ink)!important;border-left:3px solid var(--t);padding-left:9px}',
    '.ar-switch{font-weight:600;color:var(--ar-ink)!important}',

    /* Before / after */
    '.ar-dumb,.ar-scores,.ar-div{--lab:116px;--val:118px;--gap:12px}',
    '.ar-dumb,.ar-scores{position:relative;padding-top:24px}',
    '.ar-ref{position:absolute;top:0;bottom:0;width:0;left:calc(var(--lab) + var(--gap) + (100% - var(--lab) - var(--val) - 2 * var(--gap)) * var(--f,0))}',
    '.ar-ref span{position:absolute;top:0;left:6px;white-space:nowrap;font:600 11.5px/1 var(--ar-sans);color:var(--ar-ink2)}',
    '.ar-limit{border-left:2px solid var(--ar-trim)}.ar-typical{border-left:1px solid var(--ar-mute)}',
    '.ar-typical span{color:var(--ar-mute)}',
    '.ar-drow,.ar-srow,.ar-vrow{display:grid;grid-template-columns:var(--lab) minmax(0,1fr) var(--val);gap:var(--gap);align-items:center;min-height:32px;position:relative}',
    '.ar-srow{min-height:40px}',
    '.ar-dlab,.ar-slab,.ar-vlab{font:600 13px/1.2 var(--ar-sans);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.ar-dtrack{position:relative;height:22px;border-bottom:1px solid var(--ar-rule)}',
    '.ar-dline{position:absolute;top:50%;height:3px;margin-top:-1.5px;background:var(--t);opacity:.45;border-radius:2px}',
    '.ar-dot{position:absolute;top:50%;width:13px;height:13px;margin:-6.5px 0 0 -6.5px;border-radius:50%}',
    '.ar-dot.now{background:var(--ar-bg);box-shadow:inset 0 0 0 2.5px var(--ar-mute)}',
    '.ar-dot.then{background:var(--t);box-shadow:0 0 0 2px var(--ar-bg)}',
    '.ar-dval{font-size:13px;color:var(--ar-mute);white-space:nowrap}.ar-dval b{color:var(--ar-ink)}',

    /* Pie and pairs */
    '.ar-two{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(18px,3vw,36px);align-items:start}',
    '.ar-pie{display:grid;grid-template-columns:minmax(120px,190px) minmax(0,1fr);gap:18px;align-items:center}',
    '.ar-donut{position:relative;aspect-ratio:1}.ar-donut svg{width:100%;height:100%;display:block}',
    '.ar-arc{fill:none;stroke-width:7.2}',
    '.ar-arc.s1{stroke:var(--ar-s1)}.ar-arc.s2{stroke:var(--ar-s2)}.ar-arc.s3{stroke:var(--ar-s3)}.ar-arc.s4{stroke:var(--ar-s4)}.ar-arc.s5{stroke:var(--ar-s5)}.ar-arc.s6{stroke:var(--ar-s6)}.ar-arc.sx{stroke:var(--ar-sx)}',
    '.ar-arc:hover{stroke-width:8.4}',
    '.ar-donut>div{position:absolute;inset:0;display:grid;place-content:center;text-align:center}',
    '.ar-donut b{font:600 30px/1 var(--ar-sans)}.ar-donut span{font-size:12px;color:var(--ar-mute)}',
    '.ar-pielegend{list-style:none;margin:0;padding:0;display:grid;gap:8px;font-size:13.5px}',
    '.ar-pielegend li{display:grid;grid-template-columns:12px minmax(0,1fr) auto;gap:9px;align-items:center}',
    '.ar-pielegend i{width:12px;height:12px;border-radius:3px}.ar-pielegend b{font-variant-numeric:tabular-nums}',
    '.ar-pielegend i.s1{background:var(--ar-s1)}.ar-pielegend i.s2{background:var(--ar-s2)}.ar-pielegend i.s3{background:var(--ar-s3)}.ar-pielegend i.s4{background:var(--ar-s4)}.ar-pielegend i.s5{background:var(--ar-s5)}.ar-pielegend i.s6{background:var(--ar-s6)}.ar-pielegend i.sx{background:var(--ar-sx)}',
    '.ar-pairs{display:grid;gap:10px}',
    '.ar-pair{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1.3fr) 60px;gap:10px;align-items:center}',
    '.ar-plab{font:600 13px/1.25 var(--ar-sans)}.ar-plab small{display:block;font-weight:400;font-size:11.5px;color:var(--ar-mute)}',
    '.ar-pbars{display:grid;gap:3px}.ar-pbars i{display:block;height:9px;border-radius:0 4px 4px 0;min-width:2px}',
    '.ar-pbars i.you{background:var(--ar-gold)}.ar-pbars i.mkt{background:var(--ar-mkt)}',
    '.ar-pval{text-align:right;font-variant-numeric:tabular-nums;font-size:13px;line-height:1.25}.ar-pval small{display:block;color:var(--ar-mute)}',

    /* Scores */
    '.ar-slab em{display:block;font:600 10.5px/1.2 var(--ar-mono);font-style:normal;letter-spacing:.06em;text-transform:uppercase;color:var(--ar-mute);margin-top:2px}',
    '.ar-slab em::before{content:"";display:inline-block;width:7px;height:7px;border-radius:2px;background:var(--t);margin-right:5px;vertical-align:0}',
    '.ar-strack{position:relative;height:14px;background:var(--ar-track);border-radius:0 7px 7px 0}',
    '.ar-bar{display:block;height:100%;background:var(--ar-gold);border-radius:0 7px 7px 0;transform-origin:left center}',
    '.ar-sval{font:600 15px/1 var(--ar-sans)}',

    /* Gains and losses */
    '.ar-div{display:grid;gap:4px}',
    '.ar-vtrack{position:relative;height:16px}',
    '.ar-vtrack::before{content:"";position:absolute;left:50%;top:-4px;bottom:-4px;border-left:1px solid var(--ar-rule)}',
    '.ar-vbar{position:absolute;top:0;height:100%}',
    '.ar-vbar.up{left:50%;background:var(--ar-up);border-radius:0 5px 5px 0;transform-origin:left center}',
    '.ar-vbar.down{right:50%;background:var(--ar-down);border-radius:5px 0 0 5px;transform-origin:right center}',
    '.ar-vval{font:600 13.5px/1.2 var(--ar-sans);white-space:nowrap}.ar-vval small{display:block;font-weight:400;font-size:12px;color:var(--ar-mute)}',
    '.ar-vval.up{color:var(--ar-up)}.ar-vval.down{color:var(--ar-down)}',

    /* Where next */
    '.ar-rots{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}',
    '.ar-rot{padding:18px;border-radius:16px;background:var(--ar-panel);border:1px solid var(--ar-rule)}',
    '.ar-rot h3{font:400 22px/1.2 var(--ar-serif);margin:6px 0}.ar-rot p{margin:0 0 10px;font-size:14px;color:var(--ar-ink2)}',
    '.ar-up{font:600 11.5px/1.3 var(--ar-mono);color:var(--ar-up);letter-spacing:.04em}',
    '.ar-mini{display:grid;grid-template-columns:52px minmax(0,1fr) 48px;gap:6px 8px;align-items:center;font-size:12.5px;color:var(--ar-mute);margin:10px 0 12px}',
    '.ar-mini i{display:block;height:9px;border-radius:0 4px 4px 0;min-width:2px}.ar-mini i.you{background:var(--ar-gold)}.ar-mini i.mkt{background:var(--ar-mkt)}',
    '.ar-mini b{color:var(--ar-ink);text-align:right;font-variant-numeric:tabular-nums}',
    '.ar-picks a,.ar-swaps a{display:inline-block;padding:5px 10px;border-radius:999px;border:1px solid var(--ar-rule);background:var(--ar-bg);font:600 12.5px/1.2 var(--ar-mono);text-decoration:none;margin:2px 2px 0 0}',
    '.ar-picks a b{color:var(--ar-up)}',
    '.ar-swaps{list-style:none;margin:0;padding:0;display:grid;gap:8px}',
    '.ar-swaps li{display:flex;flex-wrap:wrap;align-items:center;gap:10px;font-size:14px}',
    '.ar-from{text-decoration:line-through;text-decoration-color:var(--ar-exit);color:var(--ar-mute);font:600 13px/1 var(--ar-mono)}',
    '.ar-swaps small{color:var(--ar-mute);font-weight:400}.ar-swaps em{font-size:12.5px;color:var(--ar-mute)}',

    /* Method */
    '.ar-method h3{font:600 14px/1.4 var(--ar-sans);margin:18px 0 4px}.ar-method h3:first-child{margin-top:0}',
    '.ar-method p{margin:0;color:var(--ar-ink2);font-size:14px}',
    '.ar-disclaimer{margin-top:18px!important;padding:14px 16px;border-radius:12px;background:var(--ar-panel);border-left:3px solid var(--ar-gold);color:var(--ar-ink)!important}',
    '.ar-foot{padding:18px clamp(18px,4vw,44px) 26px;border-top:1px solid var(--ar-rule);font-size:12px;color:var(--ar-mute)}',

    /* The numbers behind each chart */
    '.ar-data{margin-top:12px;font-size:13px}.ar-data summary{cursor:pointer;color:var(--ar-ink2);font-weight:600;width:max-content;max-width:100%}',
    '.ar-scroll{overflow-x:auto;margin-top:8px}',
    '.ar-data table{border-collapse:collapse;width:100%;min-width:420px}',
    '.ar-data th,.ar-data td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--ar-rule);font-variant-numeric:tabular-nums}',
    '.ar-data thead th{font:600 11px/1.3 var(--ar-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ar-mute)}',

    /* Motion: the page only, entrance only, fills backwards only */
    '.ar-live .ar-sec.in .ar-seg{animation:ar-grow .7s cubic-bezier(.22,.61,.36,1) backwards;animation-delay:calc(var(--i,0) * 90ms)}',
    '.ar-live .ar-sec.in .ar-bar,.ar-live .ar-sec.in .ar-vbar,.ar-live .ar-sec.in .ar-pbars i,.ar-live .ar-sec.in .ar-mini i{animation:ar-grow .8s cubic-bezier(.22,.61,.36,1) backwards;animation-delay:calc(var(--i,0) * 45ms + 120ms)}',
    '.ar-live .ar-sec.in .ar-arc{animation:ar-draw 1s cubic-bezier(.22,.61,.36,1) backwards;animation-delay:calc(var(--i,0) * 110ms)}',
    '.ar-live .ar-sec.in .ar-dot.then,.ar-live .ar-sec.in .ar-dline{animation:ar-fade .6s ease-out backwards;animation-delay:calc(var(--i,0) * 50ms + 300ms)}',
    '.ar-live .ar-sec.in .ar-things li,.ar-live .ar-sec.in .ar-rot{animation:ar-rise .55s ease-out backwards;animation-delay:calc(var(--i,0) * 110ms)}',
    '.ar-live .ar-ring-fg{animation:ar-ring 1.2s cubic-bezier(.22,.61,.36,1) .15s backwards}',
    '@keyframes ar-grow{from{transform:scaleX(0)}}',
    '@keyframes ar-draw{from{stroke-dasharray:0 100}}',
    '@keyframes ar-ring{from{stroke-dasharray:0 100}}',
    '@keyframes ar-fade{from{opacity:0}}',
    '@keyframes ar-rise{from{opacity:0;transform:translateY(12px)}}',
    '@media (prefers-reduced-motion:reduce){.ar-root *,.ar-root *::before{animation:none!important}}',
    'html[data-motion="off"] .ar-root *{animation:none!important}',

    /* Phones */
    '@media (max-width:760px){',
    '.ar-root{border-radius:18px;font-size:14.5px}',
    '.ar-cover-main{grid-template-columns:1fr}.ar-ring{width:136px}.ar-ring span{font-size:9px;letter-spacing:.06em}',
    '.ar-brand em{margin-left:0;width:100%}',
    '.ar-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.ar-tiles.three{grid-template-columns:1fr}',
    '.ar-tile b{font-size:19px}.ar-sym{font-size:clamp(13px,4.2vw,17px);letter-spacing:-.01em;overflow-wrap:normal}',
    '.ar-tiles.three .ar-tile{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:baseline;gap:0 12px;padding:12px 14px}',
    '.ar-tiles.three .ar-tile b{grid-row:span 2;margin:0;text-align:right}',
    '.ar-things{grid-template-columns:1fr}',
    '.ar-row{grid-template-columns:minmax(0,1fr) 72px;gap:6px 12px}.ar-what{grid-column:1 / -1}',
    '.ar-two{grid-template-columns:1fr}.ar-pie{grid-template-columns:130px minmax(0,1fr)}',
    '.ar-dumb,.ar-scores,.ar-div{--lab:92px;--val:88px;--gap:8px}',
    '.ar-dlab,.ar-slab,.ar-vlab{font-size:12px}',
    '.ar-pair{grid-template-columns:minmax(0,1fr) 56px;gap:4px 10px}.ar-plab{grid-column:1 / -1}',
    '.ar-plab small{display:inline;margin-left:6px}',
    '}',
    '@media (max-width:380px){.ar-tiles,.ar-tiles.three{grid-template-columns:1fr}.ar-pie{grid-template-columns:1fr}.ar-donut{max-width:180px}}',

    /* Paper */
    '@media print{',
    '.ar-root{box-shadow:none;border-radius:0;max-width:none}',
    '.ar-tools,.ar-data{display:none!important}',
    '.ar-cover{-webkit-print-color-adjust:exact;print-color-adjust:exact}',
    '.ar-root *{-webkit-print-color-adjust:exact;print-color-adjust:exact;animation:none!important}',
    '.ar-sec{break-inside:auto}.ar-fig,.ar-things,.ar-rot,.ar-row,.ar-tiles,.ar-sec-head{break-inside:avoid}',
    '.ar-sec-head{break-after:avoid}',
    '}'
  ].join('\n');

  // Standalone: styles inline, links absolute, light, no script. Opens in any
  // browser offline, prints to PDF, attaches to a message.
  function documentHTML(d) {
    var date = when((d || {}).generated_at) || when(new Date().toISOString());
    return '<!DOCTYPE html><html lang="en" data-theme="light"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Altaha portfolio report' + (date ? ' — ' + esc(date) : '') + '</title>' +
      '<style>html{background:#EFE9DC}body{margin:0;padding:clamp(0px,3vw,32px) clamp(0px,2vw,24px)}' +
      '@page{size:A4;margin:12mm}@media print{html{background:#fff}body{padding:0}}\n' + CSS + '</style></head><body>' +
      build(d, { base: SITE }) + '</body></html>';
  }

  // ── The page ────────────────────────────────────────────────────────────
  function still() {
    var d = root.document && root.document.documentElement;
    return !!(d && d.getAttribute('data-motion') === 'off') ||
      !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  function style() {
    if (!root.document || root.document.getElementById('ar-style')) return;
    var s = root.document.createElement('style');
    s.id = 'ar-style';
    s.textContent = CSS;
    root.document.head.appendChild(s);
  }
  // Sections get their entrance as they come into view. A section nobody has
  // scrolled to is fully drawn: the animation only runs once it is seen.
  function reveal(host) {
    var secs = host.querySelectorAll('.ar-sec');
    if (still() || !('IntersectionObserver' in root)) return;
    var io = new root.IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('in');
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -12% 0px' });
    secs.forEach(function (s) { io.observe(s); });
    host.__arObserver = io;
  }
  function mount(host, d, opts) {
    if (!host) return false;
    opts = opts || {};
    if (!d || !holdings(d).length) { host.innerHTML = ''; host.__arHTML = ''; return false; }
    style();
    // A staged update that changes nothing the reader can see does not
    // rebuild the page under them (and does not replay its entrance).
    var html = build(d, { live: true, base: '' });
    if (host.__arHTML === html) return true;
    if (host.__arObserver) host.__arObserver.disconnect();
    host.__arHTML = html;
    host.innerHTML = html;
    if (!host.__arBound) {
      host.__arBound = true;
      host.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-ar]');
        if (!b) return;
        var cb = host.__arOpts && host.__arOpts[b.getAttribute('data-ar') === 'print' ? 'onPrint' : 'onDownload'];
        if (cb) cb();
      });
    }
    host.__arOpts = opts;
    reveal(host);
    return true;
  }

  var api = { build: build, documentHTML: documentHTML, mount: mount, CSS: CSS, ACT: ACT, EDGE: EDGE,
              _after: after, _slices: slices, _short: short, _inr: inr };
  root.PortfolioReport = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
