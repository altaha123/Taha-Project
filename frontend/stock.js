/* ═══════════════════════════════════════════════════════════════════════════
   Altaha Screener — stock.js
   Renders one company at its own URL: stock.html?ticker=RELIANCE

   WHAT THIS PAGE IS FOR
   The score is the headline and the ledger is the product. Every other
   screener shows you a number; this page shows the number and then every
   check, value, formula and explanation that produced it. That section is
   rendered from the same payload the score came from, so the two can never
   drift apart — a page that could disagree with its own audit trail would be
   worse than one without an audit trail at all.

   WHAT IT DELIBERATELY DOES NOT RENDER
   No target, no entry, no stop, no instruction of any kind. The levels
   section is arithmetic on the price series and is labelled as observation.
   Issuing recommendations to the public in India requires SEBI registration;
   the framing here is not decoration, it is the constraint the whole product
   is built inside.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  var API = (typeof API_BASE !== 'undefined' && API_BASE)
    ? API_BASE : 'https://taha-project.onrender.com';

  var REDUCED = false;
  try { REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function num(v, d) {
    if (v == null || v === '' || isNaN(Number(v))) return null;
    return Number(Number(v).toFixed(d == null ? 2 : d));
  }
  function money(v, cur) {
    var n = num(v, 2);
    if (n == null) return '—';
    var sym = cur === 'INR' ? '₹' : (cur === 'USD' ? '$' : '');
    return sym + n.toLocaleString(cur === 'INR' ? 'en-IN' : 'en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pct(v, d) {
    var n = num(v, d == null ? 2 : d);
    if (n == null) return '—';
    return (n > 0 ? '+' : '') + n + '%';
  }
  function tone(v) { return v > 0 ? 'up' : (v < 0 ? 'dn' : ''); }

  function param(k) {
    try { return new URLSearchParams(location.search).get(k); } catch (e) { return null; }
  }

  var TICKER = (param('ticker') || '').trim().toUpperCase();

  /* ── States ──────────────────────────────────────────────────────────────── */

  function loading() {
    $('state').innerHTML =
      '<div class="stk-state"><div class="big">Reading the exchange feed…</div>' +
      '<div>If the engine has been idle it takes about thirty seconds to wake. ' +
      'It is not broken.</div></div>';
  }
  function failed(msg) {
    $('state').innerHTML =
      '<div class="stk-state"><div class="big">' + esc(msg) + '</div>' +
      '<div><a href="index.html" style="color:var(--gold)">Back to the screener</a></div></div>';
  }

  /* ── Identity ────────────────────────────────────────────────────────────── */

  function paintHead(d) {
    var base = String(d.ticker || TICKER).replace(/\.(NS|BO)$/, '');
    document.title = base + ' — ' + (d.name || 'Stock') + ' | Altaha Screener';
    $('crumb').textContent = base;
    $('nm').textContent = d.name || base;

    var tags = [];
    if (d.exchange) tags.push(d.exchange);
    tags.push(base);
    if (d.profile && d.profile.sector) tags.push(d.profile.sector);
    if (d.profile && d.profile.industry) tags.push(d.profile.industry);
    $('tags').innerHTML = tags.map(function (t) {
      return '<span class="stk-tag">' + esc(t) + '</span>';
    }).join('');

    $('px').textContent = money(d.price, d.currency);

    // The daily change is not in /analyze, so it is filled by the chart call
    // rather than invented here. An empty field beats a wrong one.
    $('chg').textContent = '';
  }

  /* ── Score ───────────────────────────────────────────────────────────────── */

  function paintScore(d) {
    var sc = d.scoring || {};
    var score = sc.score != null ? sc.score
      : (d.altaha_score_v4 ? null : (d.verdict && d.verdict.score != null ? d.verdict.score : null));
    var label = sc.label || (d.verdict && d.verdict.label) || '';

    if (score == null) {
      $('scoren').textContent = '—';
      $('scorelb').textContent = 'NOT SCORED';
    } else {
      if (window.AltahaShell) window.AltahaShell.countUp($('scoren'), score, 0, 1100);
      else $('scoren').textContent = Math.round(score);
      $('scorelb').textContent = label;

      var r = 84, circ = 2 * Math.PI * r;
      var arc = $('arc');
      arc.style.strokeDasharray = circ;
      arc.style.strokeDashoffset = circ;
      // One frame later, so the browser has the full-offset state to animate
      // away from. Setting both in the same tick renders no transition at all.
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          arc.style.strokeDashoffset = circ * (1 - Math.max(0, Math.min(100, score)) / 100);
        });
      });
    }

    if (sc.horizon_label) {
      $('score-sub').textContent =
        'Weighted for a ' + (sc.model && sc.model.name ? sc.model.name.toLowerCase() : 'business') +
        ', read over the ' + String(sc.horizon_label).toLowerCase() + ' horizon.';
    }

    var pillars = sc.pillars || {};
    var keys = Object.keys(pillars);
    $('pillars').innerHTML = keys.length
      ? keys.map(function (k) {
          var v = pillars[k];
          return '<div class="pill"><span class="nm">' + esc(k.replace(/_/g, ' ')) + '</span>' +
            '<span class="bar"><span class="fill" data-w="' + (v == null ? 0 : v) + '"></span></span>' +
            '<span class="vv">' + (v == null ? 'n/a' : Math.round(v)) + '</span></div>';
        }).join('')
      : '<p style="color:var(--mute);font-size:13px">Pillar detail is not available for this company.</p>';

    requestAnimationFrame(function () {
      document.querySelectorAll('.pill .fill').forEach(function (f) {
        f.style.width = Math.max(0, Math.min(100, +f.dataset.w)) + '%';
      });
    });

    // Each of these arrives from a different field and several do not end in a
    // full stop, so they were running into one another mid-sentence.
    function sentence(t) {
      t = String(t || '').trim();
      if (!t) return '';
      return /[.!?]$/.test(t) ? t : t + '.';
    }
    var bits = [];
    if (sc.basis) bits.push(esc(sentence(sc.basis)));
    if (sc.summary) bits.push(esc(sentence(sc.summary)));
    if (d.percentile != null) {
      bits.push('It ranks above <b>' + d.percentile + '%</b> of the names in the last universe scan.');
    }
    if (sc.valuation_note) bits.push(esc(sentence(sc.valuation_note)));
    $('basis').innerHTML = bits.join(' ') ||
      'Every point behind this number is itemised in the ledger below.';
  }

  /* ── Numbers ─────────────────────────────────────────────────────────────── */

  function paintNumbers(d) {
    var x = (d.technical && d.technical.extras) || {};
    var t = d.technical || {}, f = d.fundamental || {};
    var cells = [
      ['Technical', t.score == null ? '—' : Math.round(t.score), 'Price structure, out of 100'],
      ['Fundamental', f.score == null ? '—' : Math.round(f.score), 'Statements, out of 100'],
      ['F-Score', f.f_score == null ? '—' : f.f_score + ' / 9', 'Piotroski, nine binary tests'],
      ['ATR', d.atr_pct == null ? '—' : num(d.atr_pct, 1) + '%', 'Average daily range'],
      ['RSI', x.rsi == null ? '—' : x.rsi, 'Momentum, 0–100'],
      ['ADX', x.adx == null ? '—' : x.adx, 'Trend strength; above 25 is a real trend'],
      ['1 month', x.ret_1m == null ? '—' : pct(x.ret_1m, 1), 'Price return'],
      ['3 months', x.ret_3m == null ? '—' : pct(x.ret_3m, 1), 'Price return'],
      ['6 months', x.ret_6m == null ? '—' : pct(x.ret_6m, 1), 'Price return'],
      ['52-week range', x.range_position == null ? '—' : x.range_position + '%',
        'Where price sits between the year low and high'],
      ['From high', x.drawdown_from_high == null ? '—' : pct(x.drawdown_from_high, 1),
        'Distance below the 52-week high']
      // Market cap used to sit here as a twelfth cell. It is one of the nine
      // figures in the header grid now, and the same number printed twice on
      // one screen reads as two numbers that happen to agree.
    ];
    $('nums').innerHTML = cells.map(function (c, i) {
      return '<div class="num d3-card tilt reveal" data-i="' + i + '">' +
        '<div class="k">' + esc(c[0]) + '</div>' +
        '<div class="v tnum">' + esc(c[1]) + '</div>' +
        '<div class="h">' + esc(c[2]) + '</div></div>';
    }).join('');
  }

  /* A large-cap in rupees runs to seven figures of crore. Two decimal places
     on it produced "\u20B91912000.00 cr" \u2014 a string with no grouping, no
     meaning past the third digit, and wide enough to wrap its own card onto a
     second line. Decimals earn their place only while the number is small. */


  /* ── The ledger ──────────────────────────────────────────────────────────── */

  function paintLedger(d) {
    var groups = [
      ['Technical checks', (d.technical && d.technical.checks) || []],
      ['Fundamental checks', (d.fundamental && d.fundamental.checks) || []]
    ];
    var html = '';
    groups.forEach(function (g) {
      if (!g[1].length) return;
      html += '<h3 style="margin:26px 0 12px;font:600 11px/1 \'IBM Plex Mono\',monospace;' +
        'letter-spacing:.14em;text-transform:uppercase;color:var(--mute)">' + esc(g[0]) + '</h3>';
      html += g[1].map(function (c, i) {
        var mx = Number(c.max) || 0, p = Number(c.points) || 0;
        var share = mx > 0 ? Math.max(0, Math.min(1, p / mx)) : 0;
        var cls = mx > 0 && p >= mx ? 'full' : (p <= 0 ? 'zero' : '');
        return '<details class="chk reveal" data-i="' + i + '">' +
          '<summary>' +
            '<span class="cn">' + esc(c.name) + '</span>' +
            '<span class="cv">' + esc(c.value) + '</span>' +
            '<span class="pts"><span class="ptbar"><span class="ptfill ' + cls +
              '" style="width:' + (share * 100).toFixed(0) + '%"></span></span>' +
              '<span class="ptn">' + p + '/' + mx + '</span></span>' +
          '</summary>' +
          '<div class="body">' +
            '<div class="row"><span class="k">Measured</span><span class="v mono">' +
              esc(c.value) + '</span></div>' +
            '<div class="row"><span class="k">Formula</span><span class="v mono">' +
              esc(c.formula) + '</span></div>' +
            '<div class="row"><span class="k">Why</span><span class="v">' +
              esc(c.explain) + '</span></div>' +
          '</div></details>';
      }).join('');
    });
    $('ledger').innerHTML = html ||
      '<p style="color:var(--mute);font-size:14px">No checks were returned for this company.</p>';
  }

  /* ── Levels ──────────────────────────────────────────────────────────────── */

  /* ── Smart AI: the score in plain English ─────────────────────────────────
     A floating button, bottom right. Opening it offers one question; nothing
     is requested from the server until the reader asks it. Each fresh
     explanation spends part of a small free daily allowance, and most
     visitors never ask. The answer stays in the panel for the visit, so
     closing and reopening does not ask again. */

  var QUESTION = 'What does this score mean, in simple words?';

  function paintExplain(d) {
    var wrap = $('sai'), panel = $('sai-panel'), fab = $('sai-fab'), box = $('sai-body');
    if (!wrap || !panel || !fab || !box) return;
    var sc = d.scoring || {};
    // No score, nothing to explain — and the server would say the same after
    // analysing the stock again.
    if (sc.score == null) { wrap.hidden = true; return; }
    wrap.hidden = false;
    var horizon = sc.horizon || 'position';
    var name = d.name || TICKER;

    function setOpen(open) {
      panel.hidden = !open;
      fab.setAttribute('aria-expanded', open ? 'true' : 'false');
      wrap.classList.toggle('open', open);
      if (open) {
        var first = box.querySelector('button') || $('sai-x');
        if (first) first.focus();
      } else {
        fab.focus();
      }
    }

    function offer() {
      box.innerHTML =
        '<p class="sai-hi">Ask about the Altaha Score for <b>' + esc(name) + '</b>.</p>' +
        '<button type="button" class="sai-q" id="sai-q">' + esc(QUESTION) + '</button>';
      $('sai-q').addEventListener('click', ask);
    }

    function retry(message) {
      box.insertAdjacentHTML('beforeend', '<p class="sai-note">' + esc(message) + '</p>' +
        '<button type="button" class="sai-q" id="sai-q">Try again</button>');
      $('sai-q').addEventListener('click', ask);
    }

    function ask() {
      // The question stays on screen as the reader's side of the exchange.
      box.innerHTML = '<p class="sai-you">' + esc(QUESTION) + '</p>' +
        '<p class="sai-wait" role="status"><span class="sai-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
        'Reading the numbers…</p>';
      fetch(API + '/explain?ticker=' + encodeURIComponent(TICKER) +
            '&horizon=' + encodeURIComponent(horizon))
        .then(function (r) {
          if (!r.ok) throw new Error('down');
          return r.json();
        })
        .then(function (x) {
          if (window.AltahaTrack) {
            window.AltahaTrack('score_explained', {
              ticker: TICKER, ok: !!x.available, reason: x.reason || null, cached: !!x.cached
            });
          }
          var you = '<p class="sai-you">' + esc(QUESTION) + '</p>';
          if (!x.available) {
            box.innerHTML = you;
            if (x.reason === 'busy' || x.reason === 'error') {
              retry(x.message || 'No explanation is available right now.');
            } else {
              box.insertAdjacentHTML('beforeend', '<p class="sai-note">' +
                esc(x.message || 'No explanation is available.') + '</p>');
            }
            return;
          }
          var when = '';
          try {
            // Written in IST on the server, and shown in IST whatever the
            // reader's clock says — "written today" has to mean an Indian day.
            when = new Date(x.generated_at).toLocaleString('en-IN',
              { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
                timeZone: 'Asia/Kolkata' }) + ' IST';
          } catch (e) {}
          // A stored explanation is from earlier today, and the score it was
          // written against may have moved since. Say which score it read.
          var drift = (x.score != null && sc.score != null &&
                       Math.round(x.score) !== Math.round(sc.score))
            ? ' It was written when the score was ' + Math.round(x.score) + '.' : '';
          box.innerHTML = you +
            '<div class="sai-ans">' + (x.paragraphs || []).map(function (p) {
              return '<p>' + esc(p) + '</p>';
            }).join('') + '</div>' +
            '<p class="sai-meta"><span class="sai-tag">AI-written</span>' +
            esc((when ? 'Written ' + when + '. ' : '') + (x.disclaimer || '') + drift) + '</p>';
        })
        .catch(function () {
          box.innerHTML = '<p class="sai-you">' + esc(QUESTION) + '</p>';
          retry('The explanation could not be loaded.');
        });
    }

    offer();
    fab.addEventListener('click', function () { setOpen(panel.hidden); });
    $('sai-x').addEventListener('click', function () { setOpen(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) setOpen(false);
    });
  }

  function paintLevels(d) {
    var lv = d.levels;
    if (!lv || (!lv.supports && !lv.resistances)) {
      $('s-levels').hidden = true;
      return;
    }
    var zones = [].concat(lv.resistances || [], lv.supports || []);
    zones.sort(function (a, b) { return (b.level || 0) - (a.level || 0); });
    $('levels').innerHTML = zones.slice(0, 8).map(function (z, i) {
      return '<div class="lvl d3-card tilt reveal" data-i="' + i + '" title="' + esc(z.why || '') + '">' +
        '<div class="k">' + esc(z.kind) + ' · ' + (z.strength == null ? '' : z.strength + '/100') + '</div>' +
        '<div class="v tnum">' + money(z.level, d.currency) + '</div>' +
        '<div class="h" style="font-size:12px;color:var(--mute);margin-top:7px">' +
          (z.distance_pct == null ? '' : pct(z.distance_pct, 1) + ' away') +
          (z.touches ? ' · ' + z.touches + ' touches' : '') + '</div></div>';
    }).join('');
  }

  /* ── About ───────────────────────────────────────────────────────────────── */

  /* ── Above the fold ───────────────────────────────────────────────────────
     Nine figures and one paragraph, in that order, before any score. This is
     the shape every screener opens with and the reason is not fashion: a
     reader needs to know what the thing is worth and what it does before a
     number out of 100 means anything to them. All nine come from the
     backend's `ratios` block so there is one definition of each, and a figure
     the provider does not publish shows a dash rather than a zero. */

  function compactMoney(v, cur) {
    var n = Number(v);
    if (!n || isNaN(n)) return '—';
    var sym = cur === 'INR' ? '₹' : '$';
    function fig(x) {
      return x >= 1000 ? Math.round(x).toLocaleString('en-IN')
           : x >= 100  ? x.toFixed(0)
                       : x.toFixed(2);
    }
    if (cur === 'INR') {
      if (n >= 1e7) return sym + fig(n / 1e7) + ' Cr.';
      if (n >= 1e5) return sym + fig(n / 1e5) + ' L';
    }
    if (n >= 1e12) return sym + fig(n / 1e12) + 'T';
    if (n >= 1e9) return sym + fig(n / 1e9) + 'B';
    if (n >= 1e6) return sym + fig(n / 1e6) + 'M';
    return sym + n.toLocaleString();
  }

  function plain(v, unit, nd) {
    var n = num(v, nd == null ? 2 : nd);
    if (n == null) return '—';
    return n.toLocaleString() + (unit || '');
  }

  function paintKey(d) {
    var r = d.ratios || {};
    var peers = d.peers || {};
    var cur = d.currency;
    var tx = (d.technical && d.technical.extras) || {};

    var hi = r.high_52w != null ? r.high_52w : tx.high_52w;
    var lo = r.low_52w  != null ? r.low_52w  : tx.low_52w;
    var band = (hi == null && lo == null) ? '—'
             : money(lo, cur) + ' – ' + money(hi, cur);

    /* Labels are our own wording. "Stock P/E" is one particular screener's
       coinage; the ratio is called a P/E everywhere else, and borrowing a
       competitor's phrasing for a number neither of us invented is how a page
       ends up reading as a copy of theirs. `key` is the metric name the
       backend's peer block uses — null where a peer percentile is meaningless,
       as it is for a rupee amount like book value. */
    var tiles = [
      { label: 'Market cap',     value: compactMoney(r.market_cap, cur) },
      { label: 'Price',          value: money(r.price != null ? r.price : d.price, cur) },
      { label: '52-week range',  value: band, small: true },
      { label: 'P/E',            value: plain(r.pe, '', 1),             key: 'pe' },
      { label: 'Book value',     value: r.book_value == null ? '—' : money(r.book_value, cur) },
      { label: 'Dividend yield', value: plain(r.dividend_yield, '%', 2), key: 'dividend_yield' },
      { label: 'ROCE',           value: plain(r.roce, '%', 1),          key: 'roce' },
      { label: 'ROE',            value: plain(r.roe, '%', 1),           key: 'roe' },
      { label: 'Debt / equity',  value: plain(r.debt_to_equity, '', 2), key: 'debt_to_equity' }
    ];

    $('kgrid').innerHTML = tiles.map(function (t) {
      return '<div class="ktile">' +
        '<div class="k">' + esc(t.label) + '</div>' +
        '<div class="v' + (t.small ? ' range' : '') + '">' + esc(t.value) + '</div>' +
        meter(t.key ? peers[t.key] : null) +
      '</div>';
    }).join('');
  }

  /* The peer meter.

     One gold track per figure showing where it sits in its sector, with a tick
     at the 50th so the reader can see the peer median without being told what
     to think about it. Deliberately one hue and no red/green: whether a high
     P/E is bad is a judgement, and this page reports arithmetic. The phrase
     ("cheaper than 81%") is written by the backend so the words and the
     direction of the measurement can never disagree.

     A figure with no peer data renders a spacer of the same height, so the
     tiles in a row stay the same size whether or not a scan has run. */
  function meter(p) {
    if (!p || p.percentile == null) return '<div class="kmeter empty"></div>';
    var pc = Math.max(0, Math.min(100, p.percentile));
    return '<div class="kmeter">' +
      '<div class="track" role="img" aria-label="' +
        esc(p.phrase + ' of ' + p.peers + ' ' + p.group) + '">' +
        '<span class="fill" style="width:' + pc + '%"></span>' +
        '<span class="mid" aria-hidden="true"></span>' +
      '</div>' +
      '<div class="cap">' + esc(p.phrase) + ' of ' + p.peers + ' ' +
        esc(p.group) + '</div>' +
    '</div>';
  }


  /* The description the provider publishes runs to a thousand characters and
     is the last thing that should push the page down. It opens clamped to
     three lines with the rest one tap away. */
  function paintAbout(d) {
    var p = d.profile || {};
    var box = $('brief');
    if (!p.description) { box.hidden = true; return; }

    $('brief-body').textContent = p.description;

    var more = $('brief-more');
    // Clamped text is only worth a control when there is something hidden by
    // the clamp. scrollHeight is read after layout for the same reason.
    requestAnimationFrame(function () {
      var el = $('brief-body');
      if (el.scrollHeight - el.clientHeight > 4) {
        more.hidden = false;
        more.addEventListener('click', function () {
          var open = el.classList.toggle('open');
          more.textContent = open ? 'Show less' : 'Read more';
        });
      }
    });

    var meta = [];
    if (p.employees) meta.push(Number(p.employees).toLocaleString() + ' employees');
    if (p.website) meta.push('<a href="' + esc(p.website) + '" target="_blank" rel="noopener noreferrer">' +
      esc(String(p.website).replace(/^https?:\/\//, '').replace(/\/$/, '')) + '</a>');
    meta.push(esc(p.source || 'Source: data provider'));
    $('brief-meta').innerHTML = meta.join(' · ');
  }


  /* ── Chart ───────────────────────────────────────────────────────────────
     A line, drawn from the same closes the engine scored. Deliberately not a
     charting library: this page needs one honest series, and pulling 200 KB
     of candlestick engine over a mobile connection to draw it would be a poor
     trade. The full workspace still lives on the Charts tab.               */

  /* Windows of history, not candle sizes. The old list asked for '1D' and
     '1W', which on this API name daily and weekly BARS — four hundred and
     twelve hundred sessions of them — so a button labelled "1 day" drew a
     year and a half. '6M' and '1Y' were not ranges the API knew at all and
     came back 400, and '6M' is where this chart opens, so the stock page's
     chart drew nothing until you pressed something else. '1M' was worse than
     an error: it matched the one-MINUTE timeframe and returned intraday bars
     when the live feed was up, and 503 when it wasn't.

     All five are daily-resolution windows now, which need no live feed. The
     intraday timeframes still exist and still belong to the charting
     workspace, where the control is explicitly a bar size.

     1D and 5D are the exception: a day drawn from daily bars is one point.
     They ask for '1DAY' and '5DAY' — intraday bars trimmed to the last one
     and five sessions — because '1D' on this API is still the daily candle
     size. Those two need the live feed; the rest never do. */
  var RANGES = [['1D', '1 day', '1DAY'], ['5D', '5 days', '5DAY'],
                ['1M', '1 month'], ['3M', '3 months'], ['6M', '6 months'],
                ['1Y', '1 year'], ['5Y', '5 years']];
  function rangeKey(r) {
    var hit = RANGES.filter(function (x) { return x[0] === r; })[0];
    return (hit && hit[2]) || r;
  }
  function isIntraday(r) { return rangeKey(r) !== r; }
  var chartRange = '6M', chartRequest = 0;

  function paintRanges() {
    $('ranges').innerHTML = RANGES.map(function (r) {
      return '<button type="button" aria-label="' + r[1] + '" aria-pressed="' + (r[0] === chartRange) + '" data-r="' + r[0] + '"' +
        (r[0] === chartRange ? ' class="on"' : '') + '>' + esc(r[0]) + '</button>';
    }).join('');
    $('ranges').onclick = function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      chartRange = b.dataset.r;
      if (window.AltahaTrack) window.AltahaTrack('chart_range_changed', { range: chartRange });
      paintRanges();
      $('ranges').querySelector('[data-r="' + chartRange + '"]').focus();
      loadChart();
    };
  }

  /* The number under the price is today's move and only ever today's move. It
     is fetched separately from the chart for exactly that reason: the chart's
     range is a browsing choice, and letting it rewrite the headline change
     meant selecting "1Y" printed a year's return where a reader looks for the
     day's.

     Fetching it separately was not enough, because `range=1D` names a CANDLE
     SIZE on this API — daily bars, four hundred sessions of them — and
     `change_pct` is the move across whatever was drawn. So the headline read
     the full window: CAPLIPOINT printed "+26.37% today" on a day it moved
     +0.92%, the 26% being its return since the previous September. The day's
     move is `day_change_pct`, the last close against the one before it. There
     is no fallback to `change_pct`: printing a year's return as today's is
     worse than printing nothing, so when the day's number is missing the
     headline stays blank. */
  function loadDayChange() {
    /* `day_change_pct` does not depend on the range, so this asks for the
       shortest window there is rather than 1D — which is four hundred daily
       candles fetched, parsed and thrown away for one number. */
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=1M')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.day_change_pct == null) return;
        var c = $('chg');
        c.className = 'chg tnum ' + tone(d.day_change_pct);
        c.textContent = pct(d.day_change_pct) + ' today';
      })
      .catch(function () {});
  }

  function loadChart() {
    var box = $('chartbox');
    var request = ++chartRequest;
    box.setAttribute('aria-busy', 'true');
    box.innerHTML = '<div class="skel" style="height:250px"></div>';
    var asked = chartRange, failStatus = 0;
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=' + rangeKey(chartRange))
      .then(function (r) {
        if (!r.ok) {
          failStatus = r.status;
          if (window.AltahaTrack) {
            window.AltahaTrack('chart_failed', { range: asked, status: r.status });
            window.AltahaTrack('api_error', { endpoint: '/chart', status: r.status });
          }
          throw new Error('x');
        }
        return r.json();
      })
      .then(function (d) {
        if (request !== chartRequest) return;
        box.setAttribute('aria-busy', 'false');
        drawChart(d, box);
      })
      .catch(function () {
        if (request !== chartRequest) return;
        box.setAttribute('aria-busy', 'false');
        box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
          'font-size:13px">' + (isIntraday(asked) && failStatus
            ? 'Intraday prices for this stock are not available right now. Try 1M or longer.'
            : 'Price history is not available right now.') + '</div>';
      });
  }

  /* A candle's calendar date. The API stamps daily bars at the exchange's
     midnight — 18:30Z the evening before for NSE — so formatting the raw
     instant in UTC printed yesterday, and formatting it in the reader's zone
     only worked for readers in the exchange's zone. Six hours forward lands
     IST, New York and UTC midnights all on their own day, read in UTC. */
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function candleDate(raw) {
    var t = null;
    if (typeof raw === 'number') t = raw > 1e12 ? raw : raw * 1000;
    else if (raw != null) t = Date.parse(raw);
    if (t == null || isNaN(t)) return null;
    return new Date(t + 6 * 3600 * 1000);
  }
  function dayLabel(raw) {
    var dt = candleDate(raw);
    if (!dt) return 'Date unavailable';
    return dt.getUTCDate() + ' ' + MONTHS[dt.getUTCMonth()] + ' ' + dt.getUTCFullYear();
  }
  /* Intraday bars are stamped from naive exchange time read as UTC, so their
     wall-clock time is the UTC reading, unshifted. */
  function barTime(raw, withDate) {
    var t = typeof raw === 'number' ? (raw > 1e12 ? raw : raw * 1000) : Date.parse(raw);
    if (t == null || isNaN(t)) return 'Time unavailable';
    var dt = new Date(t), hh = dt.getUTCHours(), mm = dt.getUTCMinutes();
    var clock = (hh % 12 || 12) + ':' + (mm < 10 ? '0' : '') + mm + (hh < 12 ? ' am' : ' pm');
    return withDate ? dt.getUTCDate() + ' ' + MONTHS[dt.getUTCMonth()] + ', ' + clock : clock;
  }
  function span(a, b) {
    var ta = typeof a === 'number' ? a * (a > 1e12 ? 1 : 1000) : Date.parse(a);
    var tb = typeof b === 'number' ? b * (b > 1e12 ? 1 : 1000) : Date.parse(b);
    if (isNaN(ta) || isNaN(tb)) return '';
    var da = Math.floor(ta / 86400000), db = Math.floor(tb / 86400000);
    if (da !== db) { var k = Math.abs(db - da); return k + (k === 1 ? ' day' : ' days'); }
    var m = Math.round(Math.abs(tb - ta) / 60000);
    return (m >= 60 ? Math.floor(m / 60) + 'h ' : '') + (m % 60) + 'm';
  }
  function daysBetween(a, b) {
    var da = candleDate(a), db = candleDate(b);
    if (!da || !db) return null;
    return Math.round(Math.abs(db - da) / 86400000);
  }

  /* The line, plus the two things a reader does with it: hover to read a
     close off any day, and drag across a stretch to read the move between
     its ends — what Google Finance does, measured on the same closes. */
  function drawChart(d, box) {
    var rows = ((d && d.candles) || []).filter(function (r) { return r && typeof r[4] === 'number' && isFinite(r[4]); });
    if (rows.length < 2) {
      box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
        'font-size:13px">Not enough history to draw this range.</div>';
      return;
    }
    var closes = rows.map(function (r) { return r[4]; });
    var n = closes.length, cur = d.currency;
    var intraday = isIntraday(chartRange);
    /* What a move is measured from: the close before the window when the API
       sends one (the intraday windows), else the window's first close. On 1D
       that is yesterday's close, drawn as a dashed line, as a quote screen does. */
    var base = (intraday && typeof d.base_close === 'number') ? d.base_close : closes[0];
    var showBase = chartRange === '1D' && base !== closes[0];
    var lo = Math.min.apply(null, closes.concat(showBase ? [base] : []));
    var hi = Math.max.apply(null, closes.concat(showBase ? [base] : []));
    var pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;

    var W = 1000, H = 250;
    var x = function (i) { return (i / (n - 1)) * W; };
    var y = function (v) { return H - ((v - lo) / (hi - lo)) * H; };

    var pts = closes.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var area = line + ' L' + W + ',' + H + ' L0,' + H + ' Z';
    var rising = closes[n - 1] >= base;
    var stroke = rising ? 'var(--sh-up)' : 'var(--sh-dn)';
    var label = (RANGES.filter(function (r) { return r[0] === chartRange; })[0] || [])[1] || '';

    var periodLow = Math.min.apply(null, closes), periodHigh = Math.max.apply(null, closes);
    var last = closes[n - 1], position = periodHigh === periodLow ? 50 : 100 * (last - periodLow) / (periodHigh - periodLow);
    var pullback = periodHigh ? 100 * (last / periodHigh - 1) : null;
    var guides = [0.15, 0.5, 0.85].map(function (f) {
      return '<div class="sc-guide" style="top:' + (f * 100) + '%"><span>' + esc(money(hi - f * (hi - lo), cur)) + '</span></div>';
    }).join('');
    box.innerHTML =
      '<div class="sc-eyebrow"><span>PRICE JOURNEY</span><span>' + esc(cur || 'Price') + ' · ' + n + ' observations</span></div>' +
      '<div class="sc-read" aria-hidden="true">' +
        '<div class="sc-price tnum"></div>' +
        '<div class="sc-sub"><span class="sc-chg tnum"></span><span class="sc-when"></span></div>' +
      '</div>' +
      '<div class="sc-plot ' + (rising ? 'rise' : 'fall') + '" tabindex="0" role="application" ' +
        'aria-roledescription="price chart" aria-describedby="chart-close-value" ' +
        'aria-label="Closing prices for ' + esc(TICKER) + '. Arrow keys move through days; ' +
        'hold Shift to measure the change across a stretch.">' +
        '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<defs><linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0" stop-color="' + stroke + '" stop-opacity=".26"/>' +
          '<stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/>' +
        '</linearGradient>' +
        '<linearGradient id="scSelG" x1="0" y1="0" x2="0" y2="1">' +
          '<stop class="sc-sel-stop" offset="0" stop-opacity=".32"/>' +
          '<stop class="sc-sel-stop" offset="1" stop-opacity="0"/>' +
        '</linearGradient>' +
        '<clipPath id="scClip"><rect class="sc-clip" x="0" y="-10" width="0" height="' + (H + 20) + '"/></clipPath>' +
        '</defs>' +
        '<g class="sc-base">' +
          '<path class="spark-fill" d="' + area + '"/>' +
          '<path class="spark-line' + (REDUCED ? '' : ' spark-draw') + '" d="' + line +
            '" style="stroke:' + stroke + '"/>' +
        '</g>' +
        '<g class="sc-sel" clip-path="url(#scClip)">' +
          '<path class="sc-sel-fill" d="' + area + '" fill="url(#scSelG)"/>' +
          '<path class="sc-sel-line" d="' + line + '"/>' +
        '</g>' +
        '</svg>' + guides +
        '<div class="sc-latest" aria-hidden="true" style="top:' + (100 * y(last) / H).toFixed(2) + '%;color:' + stroke + '"><i></i></div>' +
        (showBase ? '<div class="sc-base-line" style="top:' + (100 * y(base) / H).toFixed(2) + '%">' +
          '<span>Prev close ' + esc(money(base, cur)) + '</span></div>' : '') +
        '<div class="sc-band"></div>' +
        '<div class="sc-x sc-x-a"></div><div class="sc-x sc-x-b"></div>' +
        '<div class="sc-dot sc-dot-a"></div><div class="sc-dot sc-dot-b"></div>' +
        '<div class="sc-tip" role="presentation"></div>' +
      '</div>' +
      '<div class="sc-foot"><span>' + esc(when(0)) + '</span><span>' + esc(when(n - 1)) + '</span></div>' +
      '<div class="sc-tools"><span class="sc-hint">Hover to inspect · drag to measure</span>' +
        '<button type="button" class="sc-reset">Reset view</button></div>' +
      '<div class="sc-insights">' +
        '<div><span>Lowest close</span><strong>' + esc(money(periodLow, cur)) + '</strong><small>' + esc(when(closes.indexOf(periodLow))) + '</small></div>' +
        '<div><span>Highest close</span><strong>' + esc(money(periodHigh, cur)) + '</strong><small>' + esc(when(closes.indexOf(periodHigh))) + '</small></div>' +
        '<div><span>From highest close</span><strong>' + esc(pct(pullback)) + '</strong><small>Latest close vs period high</small></div>' +
      '</div>' +
      '<div class="sc-position"><div><span>Latest close in this range</span><b>' + (periodHigh === periodLow ? 'Unchanged throughout' : Math.round(position) + '% of the way from low to high') + '</b></div>' +
        '<div class="sc-rail"><i style="--position:' + position.toFixed(2) + '%"></i></div>' +
      '</div><p class="sc-source">Latest observation: ' + esc(when(n - 1)) + '. Based on returned closing prices; not a live tick.</p>' +
      '<output class="ux-chart-value sc-sr" id="chart-close-value" aria-live="polite"></output>';

    var plot = box.querySelector('.sc-plot');
    var q = function (s) { return box.querySelector(s); };
    var el = {
      price: q('.sc-price'), chg: q('.sc-chg'), when: q('.sc-when'),
      band: q('.sc-band'), xa: q('.sc-x-a'), xb: q('.sc-x-b'),
      da: q('.sc-dot-a'), db: q('.sc-dot-b'), tip: q('.sc-tip'),
      clip: q('.sc-clip'), out: q('#chart-close-value')
    };

    function pctOf(a, b) { return closes[a] ? 100 * (closes[b] - closes[a]) / closes[a] : null; }
    function fromBase(i) { return base ? 100 * (closes[i] - base) / base : null; }
    function when(i) { return intraday ? barTime(rows[i][0], chartRange !== '1D') : dayLabel(rows[i][0]); }
    function signed(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + money(Math.abs(v), cur); }
    function arrow(v) { return v > 0 ? '▲ ' : v < 0 ? '▼ ' : ''; }
    function place(node, i) {
      node.style.left = (100 * i / (n - 1)) + '%';
      node.style.top = (100 * y(closes[i]) / H) + '%';
    }
    function setRead(price, chgV, chgP, when) {
      el.price.textContent = money(price, cur);
      el.chg.className = 'sc-chg tnum ' + tone(chgV);
      el.chg.textContent = chgP == null ? '' : arrow(chgV) + signed(chgV) + ' (' + pct(Math.abs(chgP)).replace('+', '') + ')';
      el.when.textContent = when;
    }
    function tipAt(i, html) {
      el.tip.innerHTML = html;
      var f = i / (n - 1);
      el.tip.style.left = (100 * f) + '%';
      // Keep the card inside the box at both edges.
      el.tip.style.transform = 'translateX(' + (f < 0.12 ? '0' : f > 0.88 ? '-100%' : '-50%') + ')';
      el.tip.classList.toggle('edge-l', f < 0.12);
      el.tip.classList.toggle('edge-r', f > 0.88);
    }

    function rest() {
      plot.classList.remove('hovering', 'measuring', 'up', 'dn');
      el.out.textContent = 'Latest close ' + money(last, cur) + ' · ' + when(n - 1);
      var ch = closes[n - 1] - base;
      setRead(closes[n - 1], ch, fromBase(n - 1),
        chartRange === '1D' ? 'today' : (label ? 'past ' + label : ''));
    }

    function hover(i) {
      plot.classList.remove('measuring', 'up', 'dn');
      plot.classList.add('hovering');
      place(el.xa, i); place(el.da, i);
      var date = when(i);
      var ch = closes[i] - base;
      setRead(closes[i], ch, fromBase(i), date);
      tipAt(i, '<b class="tnum">' + esc(money(closes[i], cur)) + '</b><span>' + esc(date) + '</span>');
      el.out.textContent = date + ' · Close ' + money(closes[i], cur);
    }

    function measure(a, b) {
      if (a === b) return hover(b);
      var from = Math.min(a, b), to = Math.max(a, b);
      var ch = closes[to] - closes[from], p = pctOf(from, to);
      var dir = ch >= 0 ? 'up' : 'dn';
      plot.classList.add('hovering', 'measuring');
      plot.classList.toggle('up', dir === 'up');
      plot.classList.toggle('dn', dir === 'dn');
      place(el.xa, a); place(el.da, a); place(el.xb, b); place(el.db, b);
      el.band.style.left = (100 * from / (n - 1)) + '%';
      el.band.style.width = (100 * (to - from) / (n - 1)) + '%';
      el.clip.setAttribute('x', x(from).toFixed(1));
      el.clip.setAttribute('width', (x(to) - x(from)).toFixed(1));
      var d0 = when(from), d1 = when(to);
      var gap = intraday ? span(rows[from][0], rows[to][0]) : '';
      if (!intraday) {
        var days = daysBetween(rows[from][0], rows[to][0]);
        gap = days == null ? '' : days + (days === 1 ? ' day' : ' days');
      }
      setRead(closes[to], ch, p, d0 + ' → ' + d1);
      tipAt((from + to) / 2,
        '<b class="tnum ' + tone(ch) + '">' + arrow(ch) + esc(pct(p)) + '</b>' +
        '<span class="tnum">' + esc(signed(ch)) + (gap ? ' · ' + esc(gap) : '') + '</span>');
      el.out.textContent = 'From ' + d0 + ' to ' + d1 + ': ' + pct(p) + ', ' + signed(ch);
    }

    // Pointer: move to read, press and drag to measure.
    var anchor = null, head = n - 1, dragging = false;
    function idxAt(e) {
      var r = plot.getBoundingClientRect();
      var f = Math.max(0, Math.min(1, (e.clientX - r.left) / (r.width || 1)));
      return Math.round(f * (n - 1));
    }
    plot.addEventListener('pointermove', function (e) {
      head = idxAt(e);
      if (dragging) measure(anchor, head); else if (e.pointerType === 'mouse') hover(head);
    });
    plot.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      dragging = true;
      anchor = head = idxAt(e);
      try { plot.setPointerCapture(e.pointerId); } catch (err) {}
      hover(head);
      if (window.AltahaTrack) window.AltahaTrack('chart_measure_started', { range: chartRange });
    });
    function release(e) {
      if (!dragging) return;
      dragging = false;
      try { plot.releasePointerCapture(e.pointerId); } catch (err) {}
      // A tap or click is not a measurement; a finished drag stays up to be read.
      if (anchor === head) { anchor = null; }
    }
    plot.addEventListener('pointerup', release);
    plot.addEventListener('pointercancel', function (e) { release(e); anchor = null; rest(); });
    plot.addEventListener('pointerleave', function (e) {
      if (dragging || e.pointerType !== 'mouse' || anchor !== null) return;
      rest();
    });

    // Keyboard: arrows move, Shift+arrows measure from where Shift was first held.
    plot.addEventListener('keydown', function (e) {
      var k = e.key, step = e.ctrlKey || e.metaKey ? Math.max(1, Math.round(n / 10)) : 1, next = head;
      if (k === 'ArrowLeft') next = head - step;
      else if (k === 'ArrowRight') next = head + step;
      else if (k === 'Home') next = 0;
      else if (k === 'End') next = n - 1;
      else if (k === 'Escape') { anchor = null; rest(); return; }
      else return;
      e.preventDefault();
      next = Math.max(0, Math.min(n - 1, next));
      if (e.shiftKey) { if (anchor == null) anchor = head; head = next; measure(anchor, head); }
      else { anchor = null; head = next; hover(head); }
    });
    plot.addEventListener('blur', function () { if (!dragging) { anchor = null; rest(); } });

    q('.sc-reset').addEventListener('click', function () { anchor = null; head = n - 1; rest(); });
    rest();

    if (!REDUCED) {
      var path = box.querySelector('.spark-draw');
      if (path && path.getTotalLength) {
        var len = path.getTotalLength();
        path.style.setProperty('--len', len);
      }
    }
  }

  /* ── Ownership ────────────────────────────────────────────────────────────
     The shareholding pattern, read from the company's own Reg 31 filing.

     THE ONE THING THIS SECTION MUST NOT DO
     In the exchange's format "Public" is the PARENT of the foreign, domestic
     and non-institutional lines, not their sibling. Drawing all four together
     double-counts roughly half the company. The API hands back `split` — the
     decomposition that does sum to 100 — and this renders only that. The
     reported public figure appears once, in prose, described as the total it
     is.

     COLOUR
     Four categorical hues, fixed per category and never cycled, validated for
     colour-vision deficiency against both surfaces rather than chosen by eye.
     Identity is never carried by colour alone: every series is directly
     labelled at its last point, repeated in the legend, and repeated again in
     the table under the chart. */

  var OWN_KEYS = ['promoter', 'dii', 'fii', 'public_non_institutional'];
  var OWN_SHORT = {
    promoter: 'Promoters',
    dii: 'DII',
    fii: 'FII',
    public_non_institutional: 'Public'
  };

  var ownLoaded = false;

  function pp(v, d) {
    var n = num(v, d == null ? 2 : d);
    if (n == null) return '—';
    return (n > 0 ? '+' : '') + n.toFixed(d == null ? 2 : d) + ' pp';
  }
  function crore(v) {
    var n = Number(v);
    if (!isFinite(n) || n === 0) return '—';
    if (Math.abs(n) >= 1e7) return (n / 1e7).toFixed(2) + ' cr';
    if (Math.abs(n) >= 1e5) return (n / 1e5).toFixed(2) + ' lakh';
    return n.toLocaleString('en-IN');
  }
  function holders(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return Math.round(n).toLocaleString('en-IN');
  }

  /* The composition bar. One row, six segments at most, 2px of surface between
     each so adjacent fills never read as one. */
  function ownBar(split) {
    var parts = split.filter(function (s) { return s.pct > 0.05; });
    return '<div class="own-bar" role="img" aria-label="Shareholding composition">' +
      parts.map(function (s) {
        return '<i class="seg s-' + esc(s.key) + '" style="flex:' + s.pct + '" ' +
          'title="' + esc(s.label) + ' ' + s.pct.toFixed(2) + '%"></i>';
      }).join('') + '</div>';
  }

  /* The trend. Four series on one percentage axis — never two scales. */
  /* One panel per category: the number, how it moved, and its own sparkline.
     Replaces a four-series line chart and a separate row list that showed the
     same four things twice.

     WHY SMALL MULTIPLES AND NOT ONE CHART
     Promoters sit near 62% and domestic institutions near 1%. On one linear
     axis that is a line at the top, two lines flattened onto the floor, and
     two-thirds of the plot empty in between — and the end labels of the two
     floor-level series land on top of each other. Each panel here gets its own
     scale, so a move from 3.17% to 1.36% is visible movement rather than a
     twitch, and no two labels can ever collide because no panel has more than
     one series. */
  function spark(points, key) {
    if (!points || points.length < 2) {
      return '<div class="op-nospark">Not enough quarter-ends to plot yet</div>';
    }
    var W = 260, H = 46, P = 3;
    var vals = points.map(function (p) { return p.v; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    // A dead-flat series would divide by zero and draw at the top edge; give
    // it a band so it reads as the flat line it is, centred.
    if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
    var pad = (hi - lo) * 0.18;
    lo -= pad; hi += pad;

    function x(i) { return P + (i / (points.length - 1)) * (W - P * 2); }
    function y(v) { return P + (1 - (v - lo) / (hi - lo)) * (H - P * 2); }

    var d = points.map(function (p, i) {
      return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.v).toFixed(1);
    }).join(' ');
    var area = d + ' L' + x(points.length - 1).toFixed(1) + ' ' + (H - P) +
               ' L' + x(0).toFixed(1) + ' ' + (H - P) + ' Z';
    var last = points[points.length - 1];

    var hits = points.map(function (p, i) {
      var bw = (W - P * 2) / Math.max(1, points.length - 1);
      return '<rect class="oh" x="' + (x(i) - bw / 2).toFixed(1) + '" y="0" width="' +
        bw.toFixed(1) + '" height="' + H + '" data-period="' + esc(p.label) +
        '" data-val="' + p.v.toFixed(2) + '"></rect>';
    }).join('');

    return '<svg class="op-spark s-' + esc(key) + '" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none" role="img" aria-label="' +
      points.length + ' quarters, ' + points[0].v.toFixed(2) + '% to ' +
      last.v.toFixed(2) + '%">' +
      '<path class="ar" d="' + area + '"/>' +
      '<path class="ln" d="' + d + '"/>' +
      '<circle class="dt" cx="' + x(points.length - 1).toFixed(1) + '" cy="' +
        y(last.v).toFixed(1) + '" r="2.6"/>' + hits + '</svg>';
  }

  /* A change chip. `fmt` decides how the magnitude reads, because percentage
     points and people are not the same quantity: 0.48 points is meaningful to
     two decimals, and "+230574.00 shareholders" is not a number anyone wrote. */
  function chip(v, unit, fmt) {
    if (v == null) return '<span class="op-chip none">—<b>' + unit + '</b></span>';
    var t = Math.abs(v) < (fmt ? 0.5 : 0.005) ? 'flat' : (v > 0 ? 'up' : 'dn');
    var sign = v > 0 ? '+' : (v < 0 ? '−' : '');
    var mag = fmt ? fmt(Math.abs(v)) : Math.abs(v).toFixed(2);
    return '<span class="op-chip ' + t + '">' + sign + mag +
      '<b>' + unit + '</b></span>';
  }

  function ownPanels(split, history) {
    // Only quarter-ends go on the line. An interim filing a fortnight after
    // the last one would otherwise occupy the same width as a full quarter.
    var qs = (history || []).filter(function (h) { return h.quarter_end !== false; });
    var by = {};
    OWN_KEYS.forEach(function (k) {
      by[k] = qs.filter(function (h) { return h[k] != null; })
               .map(function (h) { return { v: h[k], label: String(h.period).slice(0, 7) }; });
    });

    var order = OWN_KEYS.filter(function (k) {
      return split.some(function (s) { return s.key === k; });
    });
    // Anything outside the four main lines (government, custodian) still has a
    // row, just without a panel of its own.
    var extras = split.filter(function (s) { return OWN_KEYS.indexOf(s.key) < 0; });

    var panels = order.map(function (k) {
      var s = split.filter(function (x) { return x.key === k; })[0];
      var pts = by[k] || [];
      // Labelled "range", because a bare pair of numbers under a line reads as
      // first-and-last and these are lowest-and-highest.
      var vals = pts.map(function (p) { return p.v; });
      var range = pts.length > 1
        ? '<div class="op-range"><span>' + pts.length + ' quarters</span>' +
          '<span><b>range</b> ' + Math.min.apply(null, vals).toFixed(2) + '–' +
          Math.max.apply(null, vals).toFixed(2) + '</span></div>'
        : '';
      return '<article class="op s-' + esc(k) + '">' +
        '<header><i></i><h3>' + esc(s.label) + '</h3>' +
          (s.derived ? '<em class="drv" title="Not filed as its own line in this quarter’s format; derived from the totals the filing does report">derived</em>' : '') +
        '</header>' +
        '<div class="op-val tnum">' + s.pct.toFixed(2) + '<span>%</span></div>' +
        '<div class="op-chips">' + chip(s.change_qoq, 'QoQ') + chip(s.change_yoy, 'YoY') + '</div>' +
        spark(pts, k) + range +
        '<div class="op-holders">' +
          (s.holders == null ? '—' : holders(s.holders)) +
          '<b>' + (s.holders === 1 ? 'holder' : 'holders') + '</b>' +
          (s.holders_change_qoq
            ? '<em class="' + tone(s.holders_change_qoq) + '">' +
              (s.holders_change_qoq > 0 ? '+' : '−') +
              holders(Math.abs(s.holders_change_qoq)) + '</em>' : '') +
        '</div>' +
        '</article>';
    }).join('');

    var rest = extras.length
      ? '<div class="op-rest">' + extras.map(function (s) {
          return '<span><i class="s-' + esc(s.key) + '"></i>' + esc(s.label) +
            '<b class="tnum">' + s.pct.toFixed(2) + '%</b></span>';
        }).join('') + '</div>'
      : '';

    return '<div class="op-grid">' + panels + '</div>' + rest +
      '<div class="own-read" id="own-read" aria-live="polite"></div>';
  }

  function ownNames(list, heading, empty) {
    if (!list || !list.length) return '<div class="own-empty">' + esc(empty) + '</div>';
    return '<h3 class="own-h3">' + esc(heading) + '</h3>' +
      '<ul class="own-names">' + list.map(function (n) {
        var ch = n.change_qoq;
        var badge = n.new_in_table
          ? '<em class="new">new in table</em>'
          : (ch == null ? '<em class="flat">comparison unavailable</em>' : Math.abs(ch) < 0.005
              ? '<em class="flat">unchanged</em>'
              : '<em class="' + tone(ch) + '">' + pp(ch) + '</em>');
        return '<li><span class="nm">' + esc(n.name) + '</span>' +
          '<span class="kd">' + esc(n.kind || '') + '</span>' +
          '<span class="vv tnum">' + n.pct.toFixed(2) + '%</span>' + badge + '</li>';
      }).join('') + '</ul>';
  }

  /* The table the chart is an illustration of. Required, not a fallback: a
     reader who cannot separate two hues still gets every number. */
  function ownTable(history) {
    var rows = (history || []).slice().reverse();
    if (!rows.length) return '';
    return '<details class="own-more"><summary>All figures, quarter by quarter</summary>' +
      '<div class="own-tablewrap"><table class="own-table">' +
      '<caption>Shareholding by category, percent of total shares. Source column links the filing.</caption>' +
      '<thead><tr><th scope="col">Quarter ended</th>' +
      OWN_KEYS.map(function (k) { return '<th scope="col">' + esc(OWN_SHORT[k]) + '</th>'; }).join('') +
      '<th scope="col">Shareholders</th><th scope="col">Filed</th><th scope="col">Source</th></tr></thead><tbody>' +
      rows.map(function (h) {
        return '<tr><th scope="row">' + esc(h.period) + '</th>' +
          OWN_KEYS.map(function (k) {
            return '<td class="tnum">' + (h[k] == null ? '—' : h[k].toFixed(2) + '%') + '</td>';
          }).join('') +
          '<td class="tnum">' + holders(h.holders) + '</td>' +
          '<td>' + esc(h.filed || '—') + (h.revised ? ' <em>revised</em>' : '') + '</td>' +
          '<td>' + (h.source ? '<a href="' + esc(h.source) + '" target="_blank" rel="noopener">XBRL</a>' : '—') + '</td>' +
          '</tr>';
      }).join('') + '</tbody></table></div></details>';
  }

  function wireOwnHover() {
    var read = $('own-read');
    if (!read) return;
    [].slice.call(document.querySelectorAll('.op-spark')).forEach(function (svg) {
      function show(e) {
        var t = e.target;
        if (!t || !t.classList || !t.classList.contains('oh')) return;
        var panel = svg.closest ? svg.closest('.op') : null;
        var who = panel ? panel.querySelector('h3').textContent : '';
        read.innerHTML = '<b>' + esc(t.dataset.period) + '</b> · ' + esc(who) +
          ' ' + esc(t.dataset.val) + '%';
      }
      svg.addEventListener('mousemove', show);
      svg.addEventListener('focusin', show);
      svg.addEventListener('mouseleave', function () { read.innerHTML = ''; });
    });
  }

  function paintOwnership(d) {
    var box = $('own-body');
    if (!box) return;

    if (!d || !d.available) {
      box.innerHTML = '<div class="own-empty">' +
        esc((d && d.message) || 'No shareholding filing could be read for this company.') +
        '</div>';
      return;
    }

    var split = (d.split || []).filter(function (s) { return s.pct != null; });
    var t = d.totals || {};

    // Lead with the finding: the biggest mover this quarter, named in a
    // sentence, before any chart.
    var movers = split.filter(function (s) {
      return s.change_qoq != null && Math.abs(s.change_qoq) >= 0.05;
    }).sort(function (a, b) { return Math.abs(b.change_qoq) - Math.abs(a.change_qoq); });
    var lead;
    if (!movers.length) {
      lead = split.some(function (s) { return s.change_qoq != null; })
        ? 'No comparable category moved by more than a twentieth of a point over the quarter.'
        : 'Quarter-on-quarter comparison is unavailable for the filings read.';
    } else {
      var m = movers[0];
      lead = m.label + ' ' + (m.change_qoq > 0 ? 'rose' : 'fell') + ' ' +
        Math.abs(m.change_qoq).toFixed(2) + ' percentage points over the quarter, to ' +
        m.pct.toFixed(2) + '%.';
      if (movers.length > 1) {
        var n2 = movers[1];
        lead += ' ' + n2.label + ' ' + (n2.change_qoq > 0 ? 'rose' : 'fell') + ' ' +
          Math.abs(n2.change_qoq).toFixed(2) + '.';
      }
    }

    if (d.basis_period && d.basis_period !== d.period) {
      lead = 'Latest holdings are from the interim filing dated ' + d.period +
        '. Quarterly changes compare quarter-ends through ' + d.basis_period + '; they do not describe changes since the interim filing.';
    }

    var read = (d.quarters_read || 0) + ' quarter-end' +
      ((d.quarters_read === 1) ? '' : 's') +
      (d.interim_filings ? ' and ' + d.interim_filings + ' interim filing' +
        (d.interim_filings === 1 ? '' : 's') : '') + ' read';
    var head = '<p class="own-lead">' + esc(lead) + '</p>' +
      '<p class="own-asof">As filed for <b>' + esc(d.period || '—') + '</b>' +
      (d.filed ? ', filed ' + esc(d.filed) : '') + '. ' + esc(read) + '.' +
      (d.latest_source ? ' <a href="' + esc(d.latest_source) +
        '" target="_blank" rel="noopener">Open the filing</a>.' : '') + '</p>';

    var count = '';
    if (t.holders != null) {
      count = '<div class="own-count">' +
        '<div class="big tnum">' + holders(t.holders) + '</div>' +
        '<div class="lb">shareholders on the register</div>' +
        '<div class="ch">' +
          chip(t.holders_change_qoq, 'QoQ', holders) +
          chip(t.holders_change_yoy, 'YoY', holders) +
        '</div></div>';
    }

    var notes = (d.notes || []).length
      ? '<div class="own-notes">' + d.notes.map(function (n) {
          return '<p>' + esc(n) + '</p>';
        }).join('') + '</div>'
      : '';

    box.innerHTML = head + '<div id="own-intelligence"></div>' + ownBar(split) +
      ownPanels(split, d.history) + count + ownTable(d.history) +
      '<div class="own-namecols">' +
      '<div>' + ownNames(d.names && d.names.promoters, 'Promoter group',
        'This company reports no promoter holding.') + '</div>' +
      '<div>' + ownNames(d.names && d.names.public, 'Public holders above 1%',
        'No public holder crosses one per cent in this filing.') + '</div>' +
      '</div>' + notes;

    wireOwnHover();
    if (window.OwnershipInsights) window.OwnershipInsights.mount(d, {ticker:TICKER, api:API, name:$('nm').textContent});
  }

  function loadOwnership() {
    var box = $('own-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the filings…</div>';
    }
    fetch(API + '/shareholding?ticker=' + encodeURIComponent(TICKER) + '&quarters=8&names=40')
      .then(function (r) {
        if (!r.ok) throw new Error('down');
        return r.json();
      })
      .then(paintOwnership)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="own-empty">The filings could not be read ' +
            'just now. If the engine has been idle it takes about thirty seconds ' +
            'to wake — try again.</div>';
        }
      });
  }


  /* ── Fundamentals ─────────────────────────────────────────────────────────
     The quarterly P&L as filed, the ratios that follow from it, and a change
     column.

     A TABLE, DELIBERATELY
     Sixteen line items against six quarters with a change column is tabular
     data, and a reader comparing two quarters of "other expenses" wants the
     number, not a mark whose length they have to estimate. The sparklines in
     the ratio block earn their place because a trend is the question there;
     in the P&L the question is "what was it", and the answer is a figure.

     THE TWO THINGS THIS MUST NOT DO
     Mix accounting bases — the payload carries one basis and names it, and
     the basis is printed at the top rather than assumed. And print a
     percentage across zero: a company that lost money and then made money has
     not grown by a percentage, so the payload sends a `kind` and this renders
     the words instead of inventing a number. */

  var fundaLoaded = false;

  function cr(v) {
    if (v == null || isNaN(Number(v))) return '—';
    var n = Number(v) / 1e7;
    var a = Math.abs(n);
    var s = a >= 1000 ? n.toFixed(0) : (a >= 10 ? n.toFixed(1) : n.toFixed(2));
    return Number(s).toLocaleString('en-IN');
  }
  function plain(v, d) {
    if (v == null || isNaN(Number(v))) return '—';
    return Number(Number(v).toFixed(d == null ? 2 : d)).toLocaleString('en-IN');
  }

  /* The change cell. `kind` comes from the API precisely so this never has to
     infer a turnaround from a sign.

     Two vocabularies, because one does not fit. On profit after tax "to
     profit" is exactly the right phrase; on the tax line it is nonsense — tax
     going from a credit to a charge is not a company turning profitable. So
     the profit lines get the profit words and everything else gets the
     sign words, which are true of any line. */
  var PROFIT_LINES = {
    pbt_before_exceptional: 1, pbt: 1, pat: 1, eps_basic: 1, exceptional: 1
  };
  var KIND_WORDS = {
    loss_to_profit: 'to profit',
    profit_to_loss: 'to loss',
    loss_widened: 'loss wider',
    loss_narrowed: 'loss narrower',
    unavailable: '—',
    flat: 'flat'
  };
  var SIGN_WORDS = {
    loss_to_profit: 'to positive',
    profit_to_loss: 'to negative',
    loss_widened: 'more negative',
    loss_narrowed: 'less negative',
    unavailable: '—',
    flat: 'flat'
  };
  function words(key) { return PROFIT_LINES[key] ? KIND_WORDS : SIGN_WORDS; }

  function changeCell(c, key) {
    if (!c || c.kind === 'unavailable') return '<td class="fu-ch none">—</td>';
    /* Nil in both quarters — exceptional items, usually. "Flat" is true but it
       says a line moved nowhere when the line was never there. */
    if (c.pct == null && c.kind === 'flat' && !c.abs)
      return '<td class="fu-ch none">—</td>';
    if (c.pct == null) {
      var word = words(key)[c.kind] || 'changed';
      var t = (c.kind === 'loss_to_profit' || c.kind === 'loss_narrowed') ? 'up'
            : (c.kind === 'profit_to_loss' || c.kind === 'loss_widened') ? 'dn' : '';
      return '<td class="fu-ch word ' + t + '" title="A percentage change needs a ' +
        'positive base to mean anything">' + esc(word) + '</td>';
    }
    var tone2 = c.pct > 0.005 ? 'up' : (c.pct < -0.005 ? 'dn' : '');
    return '<td class="fu-ch ' + tone2 + ' tnum">' +
      (c.pct > 0 ? '+' : '') + c.pct.toFixed(1) + '%</td>';
  }

  function fundaTable(d) {
    var rows = d.rows || [];
    if (!rows.length) return '';
    var latest = rows[0];
    var older = rows.slice(1);

    var head = '<tr><th scope="col" class="fu-line">₹ crore</th>' +
      '<th scope="col" class="fu-now">' + esc(latest.label || '') + '</th>' +
      '<th scope="col" class="fu-chh">' +
        (latest.yoy_against ? 'vs ' + esc(latest.yoy_against) : 'YoY') + '</th>' +
      '<th scope="col" class="fu-chh">' +
        (latest.qoq_against ? 'vs ' + esc(latest.qoq_against) : 'QoQ') + '</th>' +
      older.map(function (r) {
        return '<th scope="col">' + esc(r.label || '') + '</th>';
      }).join('') + '</tr>';

    var body = (d.lines || []).map(function (ln) {
      var v = latest.values || {};
      var isKey = ln.key === 'revenue' || ln.key === 'ebitda' || ln.key === 'pat';
      var money = ln.unit !== 'rupees';
      var fmt = money ? cr : function (x) { return plain(x, 2); };
      /* The column header reads "₹ crore". EPS is rupees per share, so it says
         so on its own row rather than being read off by a factor of a crore. */
      return '<tr' + (isKey ? ' class="key"' : '') + '>' +
        '<th scope="row" class="fu-line">' + esc(ln.label) +
          (money ? '' : '<em>₹ per share</em>') + '</th>' +
        '<td class="fu-now tnum">' + fmt(v[ln.key]) + '</td>' +
        changeCell((latest.yoy || {})[ln.key], ln.key) +
        changeCell((latest.qoq || {})[ln.key], ln.key) +
        older.map(function (r) {
          return '<td class="tnum">' + fmt((r.values || {})[ln.key]) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    /* The note sits OUTSIDE the scroller. Inside it, it is as wide as the
       table and gets clipped at the viewport edge on a phone — which is where
       it matters most, because that is where the basis is least visible. */
    return '<p class="fu-cap" id="fu-cap-pl">Profit and loss as filed, ' +
      esc(d.basis) + ', in ₹ crore. The first change column compares the same ' +
      'quarter a year earlier — the comparison that means something for a ' +
      'seasonal business. The second is against the quarter just gone.</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table" aria-describedby="fu-cap-pl">' +
      '<caption class="fu-vh">Quarterly profit and loss, ' + esc(d.basis) +
      ' basis, in rupees crore</caption>' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div></div>';
  }

  function ratioSpark(rows, key) {
    var pts = rows.slice().reverse()
      .map(function (r) { return (r.ratios || {})[key]; })
      .filter(function (v) { return v != null; });
    if (pts.length < 2) return '';
    var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
    if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5; }
    var W = 96, H = 22;
    var d = pts.map(function (v, i) {
      var x = (i / (pts.length - 1)) * W;
      var y = (1 - (v - lo) / (hi - lo)) * (H - 4) + 2;
      return (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
    }).join(' ');
    return '<svg class="fu-spark" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none" aria-hidden="true"><path d="' + d + '"/></svg>';
  }

  function fundaRatios(d) {
    var rows = d.rows || [];
    if (!rows.length) return '';
    var latest = rows[0], older = rows.slice(1);
    var body = (d.ratio_defs || []).map(function (rd) {
      var unit = rd.key === 'interest_cover_x' ? '×' : '%';
      var val = (latest.ratios || {})[rd.key];
      /* The unit goes on the row label. Suffixing every cell in six columns is
         noise; suffixing only the latest leaves the older quarters looking
         like a different quantity. */
      return '<tr>' +
        '<th scope="row" class="fu-line">' + esc(rd.label) +
          '<em>' + esc(rd.formula) + ', ' + unit + '</em></th>' +
        '<td class="fu-now tnum">' + (val == null ? '—' : plain(val, 2) + unit) + '</td>' +
        '<td class="fu-sp">' + ratioSpark(rows, rd.key) + '</td>' +
        older.map(function (r) {
          var x = (r.ratios || {})[rd.key];
          return '<td class="tnum">' + (x == null ? '—' : plain(x, 2)) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    var head = '<tr><th scope="col" class="fu-line">Ratio</th>' +
      '<th scope="col" class="fu-now">' + esc(latest.label || '') + '</th>' +
      '<th scope="col" class="fu-sp">Trend</th>' +
      older.map(function (r) {
        return '<th scope="col">' + esc(r.label || '') + '</th>';
      }).join('') + '</tr>';

    return '<h3 class="fu-h3">Ratios</h3>' +
      '<p class="fu-cap" id="fu-cap-ratios">Computed from the lines above, the ' +
      'same way in every quarter. A ratio is left blank rather than shown where ' +
      'its denominator is zero or negative — an effective tax rate against a ' +
      'loss before tax is not a rate.</p>' +
      '<div class="fu-block"><div class="fu-wrap">' +
      '<table class="fu-table fu-ratios" aria-describedby="fu-cap-ratios">' +
      '<caption class="fu-vh">Quarterly ratios</caption>' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div></div>';
  }

  function paintFunda(d) {
    var box = $('funda-body');
    if (!box) return;
    if (!d || !d.available) {
      box.innerHTML = '<div class="own-empty">' +
        esc((d && d.message) || 'The filings could not be read.') + '</div>';
      return;
    }
    var rows = d.rows || [];
    var latest = rows[0] || {};
    var rev = (latest.yoy || {}).revenue || {};
    var pat = (latest.yoy || {}).pat || {};

    var LEAD_WORDS = {
      loss_to_profit: 'turned from a loss into a profit',
      profit_to_loss: 'turned from a profit into a loss',
      loss_widened: 'lost more',
      loss_narrowed: 'lost less',
      flat: 'was unchanged'
    };
    function phrase(c, what) {
      if (!c || c.kind === 'unavailable') return '';
      if (c.pct != null) {
        if (Math.abs(c.pct) < 0.05) return what + ' was flat';
        return what + ' ' + (c.pct > 0 ? 'grew' : 'fell') + ' ' +
          Math.abs(c.pct).toFixed(1) + '%';
      }
      return what + ' ' + (LEAD_WORDS[c.kind] || 'changed');
    }
    var bits = [phrase(rev, 'Revenue'), phrase(pat, 'profit after tax')]
      .filter(Boolean);
    var lead = bits.length
      ? bits.join(' and ') + ' against ' + (latest.yoy_against || 'a year earlier') + '.'
      : 'Not enough history yet to compare this quarter with a year earlier.';

    var alts = (d.basis_alternatives || []).filter(function (b) { return b !== d.basis; });
    var head = '<p class="own-lead">' + esc(lead) + '</p>' +
      '<p class="own-asof">' +
        '<b>' + esc(d.basis) + '</b> results — ' + esc(d.basis_reason) + '. ' +
        esc(String(d.count)) + ' quarter' + (d.count === 1 ? '' : 's') + ' read' +
        (d.partial ? ' of ' + esc(String(d.requested)) + ' asked for' : '') + '.' +
        (alts.length ? ' The company also files ' + esc(alts.join(' and ')) + '.' : '') +
        (latest.source ? ' <a href="' + esc(latest.source) +
          '" target="_blank" rel="noopener">Open the filing</a>.' : '') +
      '</p>';

    box.innerHTML = head + fundaTable(d) + fundaRatios(d) +
      ((d.notes || []).length
        ? '<div class="own-notes">' + d.notes.map(function (n) {
            return '<p>' + esc(n) + '</p>';
          }).join('') + '</div>'
        : '');
  }

  function loadFunda() {
    var box = $('funda-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the results filings…</div>';
    }
    fetch(API + '/fundamentals?ticker=' + encodeURIComponent(TICKER) + '&quarters=6')
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(paintFunda)
      .catch(function () {
        if (box) {
          box.innerHTML = '<div class="own-empty">The filings could not be read ' +
            'just now. If the engine has been idle it takes about thirty seconds ' +
            'to wake — try again.</div>';
        }
      });
  }

  /* ── Delivery ─────────────────────────────────────────────────────────────
     NSE publishes, per stock per session, what share of the traded volume was
     actually DELIVERED — settled into somebody's demat account — rather than
     bought and sold again before the close. It is in the full bhavcopy, it is
     free, and no OHLCV feed carries it, which is why almost nothing in retail
     tooling here shows it per company.

     This reads /delivery, which reads the same panel the Altaha Special book
     is ranked on. One store, so the book and this page can never quote
     different delivery figures for the same session.

     WHAT IT DOES NOT DO: say whether a number is good. A 70% day on a stock
     that normally delivers 65% is unremarkable; the same 70% on one that
     normally delivers 30% is the whole story. So every figure is shown
     against this company's own average and never against a threshold, and
     nothing here is phrased as a signal to act on. */

  var DV_RANGES = [['20', '20 sessions'], ['60', '60 sessions'], ['120', '120 sessions']];
  var dvDays = '60';
  var dvLoaded = false;
  var dvRequest = 0;

  function paintDelivery(d) {
    var box = $('dv-body');
    if (!box) return;

    if (!d || d.available !== true) {
      // Not covered, still building, or no sessions yet — each of which is a
      // fact about the data rather than a failure, and is written as one.
      var msg = (d && d.message) || 'Delivery data is unavailable just now.';
      box.innerHTML = '<div class="own-empty' + (d && d.building ? ' is-loading' : '') + '"' +
        (d && d.building ? ' aria-busy="true"' : '') + '>' + esc(msg) + '</div>';
      return;
    }

    window.AltahaDelivery.mount(box, d);
  }

  function paintDvRanges() {
    var host = $('dv-ranges');
    if (!host) return;
    host.innerHTML = DV_RANGES.map(function (r) {
      return '<button type="button" aria-label="' + r[1] + '" aria-pressed="' +
        (r[0] === dvDays) + '" data-d="' + r[0] + '"' +
        (r[0] === dvDays ? ' class="on"' : '') + '>' + esc(r[0]) + '</button>';
    }).join('');
    host.onclick = function (e) {
      var b = e.target.closest('button');
      if (!b || b.dataset.d === dvDays) return;
      dvDays = b.dataset.d;
      paintDvRanges();
      host.querySelector('[data-d="' + dvDays + '"]').focus();
      loadDelivery();
    };
  }

  function loadDelivery() {
    var request = ++dvRequest;
    var box = $('dv-body');
    if (box) {
      box.innerHTML = '<div class="own-empty is-loading" aria-busy="true">' +
        'Reading the exchange delivery record…</div>';
    }
    fetch(API + '/delivery?ticker=' + encodeURIComponent(TICKER) + '&days=' + encodeURIComponent(dvDays))
      .then(function (r) { if (!r.ok) throw new Error('down'); return r.json(); })
      .then(function(d) { if (request === dvRequest) paintDelivery(d); })
      .catch(function () {
        if (box && request === dvRequest) {
          box.innerHTML = '<div class="own-empty">The delivery record could not ' +
            'be read just now. If the engine has been idle it takes about thirty ' +
            'seconds to wake — try again.</div>';
        }
      });
  }

  /* ── The rail's scroll spy ───────────────────────────────────────────────── */

  /* ── Panes ────────────────────────────────────────────────────────────────
     Replaces the anchor rail and its scroll-spy. Six stacked sections and a
     menu that scrolled between them is a lot of page on a phone; three panes
     is the same content with only one of them asking to be read.

     The chart is drawn on first reveal, not on load. Its SVG scales to its
     container, and a container that is `hidden` measures zero. */

  var chartDrawn = false;

  function showPane(name) {
    ['info', 'chart', 'scores', 'owners', 'funda', 'deliv'].forEach(function (p) {
      var pane = $('pane-' + p), btn = $('pane-btn-' + p);
      if (!pane || !btn) return;
      var on = p === name;
      pane.hidden = !on;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    if (name === 'chart' && !chartDrawn) {
      chartDrawn = true;
      paintRanges();
      loadChart();
    }
    // Same reasoning as the chart: several filings' worth of fetching, paid
    // for only by a reader who asks for it.
    if (name === 'owners' && !ownLoaded) {
      ownLoaded = true;
      loadOwnership();
    }
    // Same reasoning: one network fetch per quarter, paid for only by a reader
    // who opens the pane.
    if (name === 'funda' && !fundaLoaded) {
      fundaLoaded = true;
      loadFunda();
    }
    // Same reasoning again: a few hundred sessions of exchange data, fetched
    // only for a reader who asks to see it.
    if (name === 'deliv' && !dvLoaded) {
      dvLoaded = true;
      paintDvRanges();
      loadDelivery();
    }
    if (window.AltahaTrack) window.AltahaTrack('stock_pane_shown', { pane: name });
  }

  function wirePanes() {
    var bar = $('panes');
    if (!bar) return;
    bar.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-p]') : null;
      if (b) showPane(b.dataset.p);
    });
    // Left/right arrows move between tabs, which is the half of the tablist
    // pattern a screen reader actually uses.
    var btns = [].slice.call(bar.querySelectorAll('[data-p]'));
    btns.forEach(function (b, i) {
      b.addEventListener('keydown', function (e) {
        var step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        if (!step) return;
        e.preventDefault();
        var n = btns[(i + step + btns.length) % btns.length];
        n.focus(); showPane(n.dataset.p);
      });
    });
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */

  function start() {
    if (!TICKER) {
      failed('No stock was named. Try searching for one.');
      return;
    }
    loading();
    fetch(API + '/analyze?ticker=' + encodeURIComponent(TICKER))
      .then(function (r) {
        if (!r.ok && window.AltahaTrack) {
          window.AltahaTrack('api_error', { endpoint: '/analyze', status: r.status });
        }
        if (r.status === 404) throw new Error('notfound');
        if (!r.ok) throw new Error('down');
        return r.json();
      })
      .then(function (d) {
        $('state').innerHTML = '';
        $('body').hidden = false;
        if (window.AltahaTrack) {
          var sc = (d.scoring && d.scoring.score != null) ? Math.round(d.scoring.score) : null;
          window.AltahaTrack('stock_viewed', {
            ticker: TICKER,
            sector: (d.profile && d.profile.sector) || null,
            score: sc
          });
        }
        paintHead(d);
        paintKey(d);
        paintAbout(d);
        paintScore(d);
        paintNumbers(d);
        paintLedger(d);
        paintExplain(d);
        paintLevels(d);
        $('disc').textContent = d.disclaimer ||
          'Educational tool. Scores and evidence only — never a recommendation to buy or sell.';
        // The chart pane draws itself when it is first opened; only the
        // headline day-change is needed up front.
        loadDayChange();
        wirePanes();
        if (param('pane') === 'owners') showPane('owners');
        if (window.AltahaShell) window.AltahaShell.reveal();
      })
      .catch(function (e) {
        var reason = (e && e.message === 'notfound') ? 'not_found' : 'engine_unreachable';
        if (window.AltahaTrack) window.AltahaTrack('stock_view_failed', { ticker: TICKER, reason: reason });
        failed(reason === 'not_found'
          ? "Couldn't find " + TICKER + '. Check the spelling.'
          : 'The engine is unreachable. If it has been idle it takes about thirty seconds to wake — try again.');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
