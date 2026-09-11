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
    var cur = d.currency;
    var tx = (d.technical && d.technical.extras) || {};

    var hi = r.high_52w != null ? r.high_52w : tx.high_52w;
    var lo = r.low_52w  != null ? r.low_52w  : tx.low_52w;
    var band = (hi == null && lo == null) ? '—'
             : money(hi, cur) + ' / ' + money(lo, cur);

    var cells = [
      ['Market Cap',     compactMoney(r.market_cap, cur)],
      ['Current Price',  money(r.price != null ? r.price : d.price, cur)],
      ['High / Low',     band],
      ['Stock P/E',      plain(r.pe, '', 1)],
      ['Book Value',     r.book_value == null ? '—' : money(r.book_value, cur)],
      ['Dividend Yield', plain(r.dividend_yield, ' %', 2)],
      ['ROCE',           plain(r.roce, ' %', 1)],
      ['ROE',            plain(r.roe, ' %', 1)],
      ['Debt / Equity',  plain(r.debt_to_equity, '', 2)]
    ];

    $('kgrid').innerHTML = cells.map(function (c) {
      return '<div class="kcell"><span class="k">' + esc(c[0]) + '</span>' +
             '<span class="v tnum">' + esc(c[1]) + '</span></div>';
    }).join('');
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
     workspace, where the control is explicitly a bar size. */
  var RANGES = [['1M', '1 month'], ['3M', '3 months'], ['6M', '6 months'],
                ['1Y', '1 year'], ['5Y', '5 years']];
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
    var asked = chartRange;
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=' + chartRange)
      .then(function (r) {
        if (!r.ok) {
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
          'font-size:13px">Price history is not available right now.</div>';
      });
  }

  function drawChart(d, box) {
    var rows = ((d && d.candles) || []).filter(function (r) { return r && typeof r[4] === 'number' && isFinite(r[4]); });
    if (rows.length < 2) {
      box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
        'font-size:13px">Not enough history to draw this range.</div>';
      return;
    }
    var closes = rows.map(function (r) { return r[4]; }).filter(function (v) { return v != null; });
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;

    var W = 1000, H = 250;
    var x = function (i) { return (i / (closes.length - 1)) * W; };
    var y = function (v) { return H - ((v - lo) / (hi - lo)) * H; };

    var pts = closes.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    var line = 'M' + pts.join(' L');
    var area = line + ' L' + W + ',' + H + ' L0,' + H + ' Z';
    var rising = closes[closes.length - 1] >= closes[0];
    var stroke = rising ? 'var(--sh-up)' : 'var(--sh-dn)';

    box.innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" ' +
      'aria-label="Price line for ' + esc(TICKER) + '">' +
      '<defs><linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0" stop-color="' + stroke + '" stop-opacity=".26"/>' +
        '<stop offset="1" stop-color="' + stroke + '" stop-opacity="0"/>' +
      '</linearGradient></defs>' +
      '<path class="spark-fill" d="' + area + '"/>' +
      '<path class="spark-line' + (REDUCED ? '' : ' spark-draw') + '" d="' + line +
        '" style="stroke:' + stroke + '"/>' +
      '</svg>' +
      '<div style="display:flex;justify-content:space-between;margin-top:12px;' +
        'font:500 11px/1 \'IBM Plex Mono\',monospace;color:var(--mute)">' +
        '<span>' + money(lo + pad, d.currency) + '</span>' +
        '<span>' + esc(d.source || '') + (d.as_of ? ' · ' + esc(d.as_of) : '') + '</span>' +
        '<span>' + money(hi - pad, d.currency) + '</span></div>';


    // A scrubber exposes the same closes to touch and keyboard users.
    var output = document.createElement('output');
    output.className = 'ux-chart-value';
    output.id = 'chart-close-value';
    var scrub = document.createElement('input');
    scrub.type = 'range'; scrub.min = '0'; scrub.max = String(rows.length - 1);
    scrub.step = '1'; scrub.value = String(rows.length - 1);
    scrub.setAttribute('aria-label', 'Inspect closing prices');
    scrub.setAttribute('aria-describedby', output.id);
    function inspect() {
      var row = rows[Number(scrub.value)];
      var raw = row[0];
      var date = String(raw == null ? 'Date unavailable' : raw);
      if (typeof raw === 'number') {
        var parsed = new Date(raw > 1e12 ? raw : raw * 1000);
        date = isNaN(parsed.getTime()) ? 'Date unavailable' : parsed.toISOString();
      }
      output.textContent = date + ' · Close ' + money(row[4], d.currency);
      scrub.setAttribute('aria-valuetext', output.textContent);
    }
    scrub.addEventListener('input', inspect);
    box.appendChild(output); box.appendChild(scrub); inspect();

    if (!REDUCED) {
      var path = box.querySelector('.spark-draw');
      if (path && path.getTotalLength) {
        var len = path.getTotalLength();
        path.style.setProperty('--len', len);
      }
    }
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
    ['info', 'chart', 'scores'].forEach(function (p) {
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
        paintLevels(d);
        $('disc').textContent = d.disclaimer ||
          'Educational tool. Scores and evidence only — never a recommendation to buy or sell.';
        // The chart pane draws itself when it is first opened; only the
        // headline day-change is needed up front.
        loadDayChange();
        wirePanes();
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
