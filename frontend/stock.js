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
      : (d.verdict && d.verdict.score != null ? d.verdict.score : null);
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
        'Distance below the 52-week high'],
      ['Market cap', d.profile && d.profile.market_cap
        ? compact(d.profile.market_cap, d.currency) : '—', 'As published by the data provider']
    ];
    $('nums').innerHTML = cells.map(function (c, i) {
      return '<div class="num d3-card tilt reveal" data-i="' + i + '">' +
        '<div class="k">' + esc(c[0]) + '</div>' +
        '<div class="v tnum">' + esc(c[1]) + '</div>' +
        '<div class="h">' + esc(c[2]) + '</div></div>';
    }).join('');
  }

  function compact(v, cur) {
    var n = Number(v);
    if (!n || isNaN(n)) return '—';
    var sym = cur === 'INR' ? '₹' : '$';
    if (cur === 'INR') {
      if (n >= 1e7) return sym + (n / 1e7).toFixed(2) + ' cr';
      if (n >= 1e5) return sym + (n / 1e5).toFixed(2) + ' L';
    }
    if (n >= 1e12) return sym + (n / 1e12).toFixed(2) + 'T';
    if (n >= 1e9) return sym + (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return sym + (n / 1e6).toFixed(2) + 'M';
    return sym + n.toLocaleString();
  }

  /* ── The ledger ──────────────────────────────────────────────────────────── */

  function paintLedger(d) {
    var groups = [
      ['Technical checks', (d.technical && d.technical.checks) || []],
      ['Fundamental checks', (d.fundamental && d.fundamental.checks) || []]
    ];
    var html = '';
    groups.forEach(function (g) {
      if (!g[1].length) return;
      html += '<h3 style="margin:26px 0 12px;font:600 10.5px/1 \'IBM Plex Mono\',monospace;' +
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
      '<p style="color:var(--mute);font-size:13.5px">No checks were returned for this company.</p>';
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
        '<div class="h" style="font-size:11.5px;color:var(--mute);margin-top:7px">' +
          (z.distance_pct == null ? '' : pct(z.distance_pct, 1) + ' away') +
          (z.touches ? ' · ' + z.touches + ' touches' : '') + '</div></div>';
    }).join('');
  }

  /* ── About ───────────────────────────────────────────────────────────────── */

  function paintAbout(d) {
    var p = d.profile || {};
    if (!p.description) { $('s-about').hidden = true; return; }
    var meta = [];
    if (p.employees) meta.push(Number(p.employees).toLocaleString() + ' employees');
    if (p.website) meta.push('<a href="' + esc(p.website) + '" target="_blank" rel="noopener noreferrer" ' +
      'style="color:var(--gold)">' + esc(String(p.website).replace(/^https?:\/\//, '')) + '</a>');
    $('about').innerHTML = '<div>' + esc(p.description) + '</div>' +
      (meta.length ? '<div style="margin-top:14px;font-size:12.5px;color:var(--mute)">' +
        meta.join(' · ') + '</div>' : '') +
      '<div class="src">' + esc(p.source || 'Source: data provider') + '</div>';
  }

  /* ── Chart ───────────────────────────────────────────────────────────────
     A line, drawn from the same closes the engine scored. Deliberately not a
     charting library: this page needs one honest series, and pulling 200 KB
     of candlestick engine over a mobile connection to draw it would be a poor
     trade. The full workspace still lives on the Charts tab.               */

  var RANGES = [['1D', '1 day'], ['1W', '1 week'], ['1M', '1 month'],
                ['6M', '6 months'], ['1Y', '1 year']];
  var chartRange = '6M';

  function paintRanges() {
    $('ranges').innerHTML = RANGES.map(function (r) {
      return '<button type="button" data-r="' + r[0] + '"' +
        (r[0] === chartRange ? ' class="on"' : '') + '>' + esc(r[0]) + '</button>';
    }).join('');
    $('ranges').onclick = function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      chartRange = b.dataset.r;
      paintRanges();
      loadChart();
    };
  }

  /* The number under the price is today's move and only ever today's move. It
     is fetched separately from the chart for exactly that reason: the chart's
     range is a browsing choice, and letting it rewrite the headline change
     meant selecting "1Y" printed a year's return where a reader looks for the
     day's. */
  function loadDayChange() {
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=1D')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.change_pct == null) return;
        var c = $('chg');
        c.className = 'chg tnum ' + tone(d.change_pct);
        c.textContent = pct(d.change_pct) + ' today';
      })
      .catch(function () {});
  }

  function loadChart() {
    var box = $('chartbox');
    box.innerHTML = '<div class="skel" style="height:250px"></div>';
    fetch(API + '/chart?ticker=' + encodeURIComponent(TICKER) + '&range=' + chartRange)
      .then(function (r) { if (!r.ok) throw new Error('x'); return r.json(); })
      .then(function (d) { drawChart(d, box); })
      .catch(function () {
        box.innerHTML = '<div style="padding:60px 0;text-align:center;color:var(--mute);' +
          'font-size:13px">Price history is not available right now.</div>';
      });
  }

  function drawChart(d, box) {
    var rows = (d && d.candles) || [];
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

    if (!REDUCED) {
      var path = box.querySelector('.spark-draw');
      if (path && path.getTotalLength) {
        var len = path.getTotalLength();
        path.style.setProperty('--len', len);
      }
    }
  }

  /* ── The rail's scroll spy ───────────────────────────────────────────────── */

  function spy() {
    var links = [].slice.call(document.querySelectorAll('.stk-rail a'));
    var secs = links.map(function (a) { return document.querySelector(a.getAttribute('href')); });
    if (!('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var i = secs.indexOf(en.target);
        if (i < 0) return;
        links.forEach(function (a, j) { a.classList.toggle('on', i === j); });
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    secs.forEach(function (s) { if (s) io.observe(s); });
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
        if (r.status === 404) throw new Error('notfound');
        if (!r.ok) throw new Error('down');
        return r.json();
      })
      .then(function (d) {
        $('state').innerHTML = '';
        $('body').hidden = false;
        paintHead(d);
        paintScore(d);
        paintNumbers(d);
        paintLedger(d);
        paintLevels(d);
        paintAbout(d);
        $('disc').textContent = d.disclaimer ||
          'Educational tool. Scores and evidence only — never a recommendation to buy or sell.';
        paintRanges();
        loadChart();
        loadDayChange();
        spy();
        if (window.AltahaShell) window.AltahaShell.reveal();
      })
      .catch(function (e) {
        failed(e && e.message === 'notfound'
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
