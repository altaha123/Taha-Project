/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Stock picks

   WHAT THIS IS
   The lists the Ideas door leads with. Three by how long a pick is held,
   each ranked on the company's filings as well as its chart (December
   2026): Swing / This month, After results and Long term. Five more by what
   the chart or the money is doing. One tab each. Under the tabs, one line
   saying what the list is and one saying how it did when tested, then the
   picks.

   "After results" is ranked on a filing, not on price alone: companies whose
   stock moved most the day their quarterly results were priced, among those
   whose results were real growth. It is empty between results seasons and
   says when the next one starts (the server's `empty_text`).

   It is drawn in two places from one set of functions, so the two can never
   describe the same pick differently:

     · the Ideas door (doors.js)       the top five, in #dri-picks
     · the Stock picks tab (index.html) all fifteen, each with its ledger

   WHERE THE NUMBERS COME FROM
   /ideas?horizon=month|results|long, or a setup list's key. The order is the
   server's. The tested record (`tested`) is read from the study file the API
   ships (backend/ideas_study.json); nothing here computes or rounds a return
   it was not given.

   A LIST NOT MEASURED YET
   The three lists by holding time were rebuilt in December 2026. Until the
   study has replayed the new recipes (`study_current` false) the server sends
   no record for them, and this says plainly that the record is being
   measured. It prints no record of the lists they replaced beside them, and
   no tally of live calls those lists made.

   OLD NAMES
   This week and Momentum were folded into Swing / This month and Long term.
   A choice remembered on this browser, or an address, that names one of
   them (or the older trade, position, medium, invest) opens the list that
   took its place, as the server does (leaders.ALIASES).

   A SCAN FROM BEFORE THE LISTS
   Until the first scan with leader ranks finishes, the API answers with the
   old short and medium lists (`method_key` is absent). Those rows are drawn
   by the page as they always were; this file says so in one line and stays
   out of the way.

   WORDS
   A reader told us the site had too much writing. Each pick gets at most
   four facts of a few words, each a measurement, never advice. Everything
   longer is behind "Details": the company's figures and the ledger of how
   its score was made.

   HOW THE PANEL READS
   Top to bottom it is three questions, in the order a newcomer asks them.
   Which list? Eight of them, in two labelled rows (by holding time, by chart
   setup), each chip saying how long it is held; the three by holding time
   share their row equally. Is it any good? Three figures from the test, each
   with a label that is a whole phrase. Which stocks? Five, each with its
   price, a target and the price to leave at. It replaced two unlabelled bars
   of five tabs and a box of three numbers captioned in two words each, which
   a reader found confusing.

   THE TARGET
   A pick shows a target because a reader asked where a good result would
   be. It is the server's `plan.aim`: as far above the price as the exit
   line is below it, the nearer of the two targets the study tested. It is
   a mark, not a rule: the plan is still "hold, and leave below the exit",
   and where the study tested selling at it (`target_test`) the panel prints
   what that did, in the study's figures, next to the cards.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';
  if (typeof window !== 'undefined' && window.AltahaPicks) return;

  var LISTS = [
    /* By holding time: the three lists that read the company's filings. The
       chip says how long a pick is held; `hold` is the plan's own words, for
       an answer that does not say. A phone drops the name's `tail`. */
    { key: 'month',   label: 'Swing / This month', short: 'Swing', tail: ' / This month', chip: '~ 2\u20134 weeks', hold: 'about a month' },
    { key: 'results', label: 'After results', chip: '~ 1 month',    hold: 'about a month' },
    { key: 'long',    label: 'Long term',     chip: '~ 1 year',     hold: 'about a year' },
    /* The setup lists: picked on what the chart or the tape is doing now. */
    /* Rebuilt December 2026 (research/setups_lab.py --v2): held long enough
       for the large winners, so the holds below are the tested ones. */
    { key: 'breakout',  label: 'Breakouts',    group: 'setup', hold: 'about 3 months' },
    { key: 'technical', label: 'Technicals',   group: 'setup', hold: 'about 3 months' },
    { key: 'quick',     label: 'Swing dips',   lead: 'Swing ', short: 'dips', group: 'setup', hold: 'about a month' },
    { key: 'flow',      label: 'Money flow',   lead: 'Money ', short: 'flow', group: 'setup', hold: 'about 3 months' },
    { key: 'emerging',  label: 'Emerging',     group: 'setup', hold: 'about 4 months' }
  ];
  var KEYS = LISTS.map(function (l) { return l.key; });
  /* Lists folded into others, and older names still in links: each opens
     the list that took its place (the server's leaders.ALIASES). */
  var ALIASES = { week: 'month', trade: 'month', momentum: 'long', position: 'long', medium: 'long', invest: 'long' };
  var STORE = 'altaha-pick-list';
  var DEFAULT = 'month';
  var FRESH_MS = 120000;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function finite(v) { return v != null && v !== '' && isFinite(Number(v)); }
  function inr(v) {
    if (!finite(v)) return '—';
    var n = Number(v);
    return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: n >= 1000 ? 0 : 2 });
  }
  /* A price in a column of prices: two decimals under ₹1,000 and none above,
     so the three levels on a card line up and none looks more exact than
     its neighbour (881.3 beside 987.06 did). */
  function px(v) {
    if (!finite(v)) return '—';
    var n = Number(v), dp = n >= 1000 ? 0 : 2;
    return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function signed(v, dp) {
    if (!finite(v)) return '—';
    var n = Number(v);
    return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(dp == null ? 1 : dp) + '%';
  }
  function valid(key) { return KEYS.indexOf(key) !== -1; }

  /* The list a name opens: its own, the one that replaced it, or null. */
  function resolve(name) {
    var k = String(name == null ? '' : name).trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(ALIASES, k)) k = ALIASES[k];
    return valid(k) ? k : null;
  }

  /* The chosen list is a convenience, never state the page depends on. A
     choice made before the lists changed ("week") is read as the list that
     replaced it, and kept that way. Storage that throws, or is not there,
     leaves the first list. */
  function chosen() {
    var raw = null;
    try { raw = localStorage.getItem(STORE); } catch (e) { raw = null; }
    var k = resolve(raw);
    if (k && k !== raw) remember(k);
    return k || DEFAULT;
  }
  function remember(key) { try { localStorage.setItem(STORE, key); } catch (e) {} }

  /* A list named in an address: #research/ideas/long, or #ideas/week from
     before the lists changed. The list it opens, or null when it names none. */
  function fromAddress(hash) {
    var p = String(hash == null ? '' : hash).replace(/^#/, '').split('/');
    var name = p[0] === 'ideas' ? p[1] : (p[0] === 'research' && p[1] === 'ideas' ? p[2] : null);
    if (!name) return null;
    try { name = decodeURIComponent(name); } catch (e) { return null; }
    return resolve(name);
  }

  /* The parts the three lists by holding time are scored on, in the
     page's own words: each says what was measured, never what to do. A part
     the page does not know keeps the server's label. */
  var FACTORS = {
    pull: 'How far it pulled back', high: 'Closeness to its 52-week high',
    fundmom: 'Sales and margin growth last quarter', secflow: 'Money flow into its industry',
    catalyst: 'A live catalyst: deliveries or an order',
    reaction: 'Move on the day its results were priced', volume: 'Volume on that day',
    growth: 'Growth in the quarter it reported',
    quality: 'Returns on capital, backed by cash', compounding: 'Growth over three years',
    governance: 'Pledges and changes in holdings', valuation: 'Price against its own industry',
    trendq: 'The year-long trend'
  };
  function factorLabel(e) {
    var key = e && e.key;
    if (key && Object.prototype.hasOwnProperty.call(FACTORS, key)) return FACTORS[key];
    return e && e.factor != null ? String(e.factor) : String(key || '');
  }

  /* ── What a pick says ──────────────────────────────────────────────────── */

  function whyHTML(s) {
    /* A breakout's pattern is its badge (patternHTML), so it is not said twice. */
    var why = ((s && s.why) || []).filter(function (w) { return !(s.pattern && w === s.pattern); });
    if (!why.length) return '';
    return '<div class="pk-why">' + why.slice(0, 4).map(function (w) {
      return '<span>' + esc(w) + '</span>';
    }).join('') + '</div>';
  }

  /* Live catalysts beside a setup pick: an order worth a share of the company,
     an earnings call, a week's news. The server's words. They were not part
     of the test (there is no history of them) and they only move a pick up
     its own list, which the list's note says. */
  function catalystHTML(s) {
    var c = s && s.catalysts;
    if (!c || !(c.lines || []).length) return '';
    return c.lines.map(function (l) {
      return '<div class="pk-fact pk-catalyst"><b>Catalyst</b> ' + esc(l) + '</div>';
    }).join('');
  }
  function catalystBadge(s) {
    return s && s.catalysts && (s.catalysts.lines || []).length
      ? '<span class="pk-badge pk-cat" title="' + esc(s.catalysts.lines[0]) + '">Catalyst</span>' : '';
  }

  /* Which breakout pattern a pick is: a VCP launchpad (a base that tightened
     before it broke) or a base turnaround (a first 60-session high after a
     long sideways base). The server's word; nothing here decides it. */
  function patternHTML(s) {
    return s && s.pattern ? '<span class="pk-badge">' + esc(s.pattern) + '</span>' : '';
  }

  /* Hold, the mark of a good result, and the one price that ends it. The
     target is a mark and not a rule (the test found selling at a target was
     the most expensive rule a plan could carry), so "Hold" still leads. */
  function planHTML(p) {
    if (!p || p.style !== 'hold' || !finite(p.stop)) return '';
    return '<div class="pk-plan">' +
      (p.sell_rule === 'sma5'
        ? '<span><b>Sell</b> first close above its 5-day average</span>'
        : '<span><b>Hold</b> ' + esc(p.hold_text || '') + '</span>') +
      (p.sell_rule === 'sma50'
        ? '<span><b>Sell</b> on a close under its 50-day average, after 15 sessions</span>' : '') +
      (finite(p.aim) ? '<span><b>Target</b> ' + inr(p.aim) +
        (finite(p.aim_pct) ? ' <small class="up">+' + Number(p.aim_pct).toFixed(0) + '%</small>' : '') + '</span>' : '') +
      '<span><b>Exit below</b> ' + inr(p.stop) +
        (finite(p.risk_pct) ? ' <small>−' + Number(p.risk_pct).toFixed(0) + '%</small>' : '') + '</span>' +
    '</div>';
  }

  /* What the target is, said once under the picks, and what selling at it
     did in the test where the study ran that. Every figure is the study's. */
  function aimHTML(d) {
    if (!d || !isTested(d) || d.sell_rule || !finite(d.exit_pct)) return '';
    if (!(d.rows || []).some(function (r) { return r.plan && finite(r.plan.aim); })) return '';
    var pct = Number(d.exit_pct).toFixed(0), t = d.target_test;
    var one = function (v) { return Number(v).toFixed(1).replace(/\.0$/, ''); };
    /* A list not measured yet says nothing about what its test found. */
    var tested = d.study_current === false ? ''
      : t && t.sold && t.held && finite(t.sold.up_pct) && finite(t.held.up_pct) &&
        finite(t.sold.avg_pct) && finite(t.held.avg_pct)
      ? 'In the test, selling at the target: <b>' + one(t.sold.up_pct) + '</b> of 100 picks ended up, average <b>' +
        signed(t.sold.avg_pct, 2) + '</b> a pick. Holding to the end: <b>' + one(t.held.up_pct) + '</b> of 100, average <b>' +
        signed(t.held.avg_pct, 2) + '</b>.'
      : 'This list was tested held to the end. Selling at a target was not tested for it.';
    return '<p class="pk-aimnote"><b>Target</b> is ' + pct + '% above the price, as far as the exit line is below it. ' +
      'It marks a good result; it is not an order to sell.' + (tested ? ' ' + tested : '') + '</p>';
  }

  /* ── Facts beside a pick: its results, an order, the chart ────────────── */

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  /* "2026-10-28" as "28 Oct". Anything else is passed through as it came. */
  function shortDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    return m && MONTHS[Number(m[2]) - 1] ? Number(m[3]) + ' ' + MONTHS[Number(m[2]) - 1] : String(iso || '');
  }

  /* The result a stock was last priced on. Ranked on, for the results list;
     a dated fact on every other. */
  function resultsHTML(s) {
    var r = s && s.results;
    if (!r || !finite(r.move_pct)) return '';
    var growth = finite(r.pat_yoy_pct) && Math.abs(r.pat_yoy_pct) < 1000
      ? ' · profit ' + (r.pat_yoy_pct >= 0 ? 'up ' : 'down ') + Math.abs(Number(r.pat_yoy_pct)).toFixed(0) + '% on a year ago' : '';
    return '<div class="pk-fact"><b>Results</b> Priced on ' + esc(shortDay(r.session)) + ': ' + signed(r.move_pct, 1) +
      ' that day, the average stock ' + signed(r.market_move_pct, 1) + growth + '</div>';
  }

  /* An order the company disclosed, against its own market value. */
  function orderHTML(s) {
    var o = s && s.order;
    if (!o || !finite(o.value_cr)) return '';
    return '<div class="pk-fact"><b>Order</b> \u20b9' + Number(o.value_cr).toLocaleString('en-IN', { maximumFractionDigits: 0 }) + ' crore' +
      (finite(o.pct_of_market_cap) ? ', ' + Number(o.pct_of_market_cap).toFixed(1) + '% of its market value' : '') +
      (o.date ? ' · ' + esc(shortDay(o.date)) : '') + '</div>';
  }

  /* The stock's sector on Money Flow (FPI flow, rotation, breadth). A fact
     beside the pick: it moves no rank. The sentence is the server's. */
  function flowHTML(s) {
    var t = s && s.sector_tailwind;
    if (!t || !t.line) return '';
    return '<div class="pk-fact"><b>Sector money flow</b> ' + esc(t.line) + '</div>';
  }

  /* The chart and the tape. Facts, with one line saying they rank nothing:
     each was tested as a rule and none improved a list. */
  function chartHTML(s, note) {
    var rows = (s && s.chart) || [];
    if (!rows.length) return '';
    return '<div class="pk-chart"><h6>Chart and volume</h6><dl>' + rows.map(function (c) {
      return '<dt>' + esc(c.k) + '</dt><dd>' + esc(c.v) + '</dd>';
    }).join('') + '</dl>' + (note ? '<p>' + esc(note) + '</p>' : '') + '</div>';
  }

  /* What the company's filings say, in Details beside a pick
     (`leader.fundamentals`, carried by every ranked stock that has filings):
     the figures the three lists by holding time are ranked on, each only
     where the company filed it, in the server's numbers. A lender is shown
     its return on equity; cash flow and debt describe a lender's lending,
     not the business, so they are left out. Facts, not reasons: the ledger
     below says what each counted for on this list. */
  var GROWTH_TEXT_MAX = 1000;   // growth past this is a near-zero base, not news (leaders.PROFIT_TEXT_MAX)
  function fundamentalsHTML(s) {
    var f = s && s.leader && s.leader.fundamentals;
    if (!f || typeof f !== 'object') return '';
    var fin = f.is_financial === true;
    function n(v) { return finite(v) ? Number(v) : null; }
    /* Whole numbers from ten up and one decimal under it, as the server
       writes its facts; a minus is a minus sign. */
    function size(v) { var a = Math.abs(v); return a >= 10 ? a.toFixed(0) : a.toFixed(1).replace(/\.0$/, ''); }
    function pc(v) { return (v < 0 ? '−' : '') + size(v) + '%'; }
    function grew(v) { return (v > 0 ? '+' : '') + pc(v); }
    function two(v) { return (v < 0 ? '−' : '') + Math.abs(v).toFixed(2).replace(/0$/, '').replace(/\.0$/, ''); }
    function times(v) { return two(v) + '×'; }
    var rows = [];
    function add(k, parts) {
      parts = parts.filter(Boolean);
      if (parts.length) rows.push([k, parts.join(', ')]);
    }
    var rev = n(f.revenue_yoy_pct), opm = n(f.opm_yoy_chg), pat = n(f.pat_yoy_pct);
    var quarter = [rev !== null && Math.abs(rev) < GROWTH_TEXT_MAX && 'sales ' + grew(rev),
                   opm !== null && 'operating margin ' + (Math.round(opm * 10) > 0 ? '+' : Math.round(opm * 10) < 0 ? '−' : '') +
                     Math.abs(opm).toFixed(1) + ' pts',
                   pat !== null && Math.abs(pat) < GROWTH_TEXT_MAX && 'profit ' + grew(pat)].filter(Boolean);
    if (quarter.length) {
      quarter[0] = quarter[0].charAt(0).toUpperCase() + quarter[0].slice(1);
      rows.push(['Last quarter' + (f.quarter ? ' (' + f.quarter + ')' : ''), quarter.join(', ') + ' on a year ago']);
    }
    if (f.earnings_quality_ok === true || f.earnings_quality_ok === false) {
      rows.push(['Profit', f.earnings_quality_ok ? 'Made by the business itself'
        : 'A loss, or much of it from other income or a one-off gain']);
    }
    var roce = n(f.roce_pct), roe = n(f.roe_pct);
    add('Returns', fin ? [roe !== null && 'Return on equity ' + pc(roe) + ' (a lender)']
                       : [roce !== null && 'ROCE ' + pc(roce), roe !== null && 'ROE ' + pc(roe)]);
    if (!fin) {
      var c2p = n(f.cfo_to_pat), fcf = n(f.fcf_pos_years_3y), de = n(f.debt_equity_x);
      add('Cash', [c2p !== null && 'From operations ' + times(c2p) + ' profit',
                   fcf !== null && 'free cash flow in ' + fcf.toFixed(0) + ' of the last 3 years']);
      add('Debt', [de !== null && times(de) + ' equity']);
    }
    var pe = n(f.pe), peg = n(f.peg);
    add('Valuation', [pe !== null && pe > 0 && 'P/E ' + pe.toFixed(0), peg !== null && peg > 0 && 'PEG ' + two(peg)]);
    if (n(f.f_score) !== null) rows.push(['F-score', Number(f.f_score).toFixed(0) + ' of 9']);
    var pledge = n(f.pledge_pct);
    if (pledge !== null) rows.push(['Pledged', pledge === 0 ? 'No shares pledged' : pc(pledge) + ' of the company, by its promoters']);
    if (f.sector_mf_quadrant) rows.push(['Industry on Money Flow', String(f.sector_mf_quadrant)]);
    if (!rows.length) return '';
    return '<div class="pk-funds"><h6>Fundamentals</h6><dl>' + rows.map(function (r) {
      return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>';
    }).join('') + '</dl></div>';
  }

  /* What the test found in a market like today's. Shown only when the index
     is under its 200-day average, which is when a reader wonders. */
  function marketHTML(d) {
    var m = d && d.market_test;
    return m && m.state === 'below_200d' && m.text ? '<p class="pk-market">' + esc(m.text) + '</p>' : '';
  }

  /* ── The tested record ─────────────────────────────────────────────────── */

  function isTested(d) { return !!(d && d.method_key === 'tested_lists'); }

  function recordHTML(d) {
    var t = d && d.tested;
    if (!t || !finite(t.up_pct)) return '';
    var st = d.study || {};
    /* A list with its own start (the results list: filings begin in 2018)
       says that year, not the study's. */
    var from = t.from || st.from;
    var years = (from && st.to) ? String(from).slice(0, 4) + '-' + String(st.to).slice(0, 4) : '';
    /* The rebuilt setup lists are held for the few large winners, so their
       record says how many there were. A list held a month or a year to its
       exit line is not, and three figures keep a phone's first screen for
       the picks. */
    var big = d.kind === 'setup' && finite(t.big_winner_pct);
    var h = t.by_half || {};
    var halves = Object.keys(h).map(function (k) {
      var x = h[k] || {};
      return '<li><b>' + esc(k) + '</b> ' + Math.round(x.up_pct) + ' in 100 rose · ' +
        signed(x.avg_pct) + ' · market ' + signed(x.index_avg_pct) +
        (big && finite(x.big_winner_pct) ? ' · ' + Number(x.big_winner_pct).toFixed(0) + '% made 25% or more' : '') + '</li>';
    }).join('');
    var up = Math.max(0, Math.min(100, Math.round(t.up_pct)));
    return '<div class="pk-record">' +
      '<p class="pk-record-h">How this list did when tested</p>' +
      '<div class="pk-record-n' + (big ? ' four' : '') + '">' +
        '<span><b>' + Math.round(t.up_pct) + '</b><small>of every 100 picks went up</small>' +
          /* The same figure as a bar: the part that went up, and the rest. */
          '<i class="pk-meter" aria-hidden="true"><i style="width:' + up + '%"></i></i></span>' +
        '<span><b class="' + (t.avg_pct >= 0 ? 'up' : 'dn') + '">' + signed(t.avg_pct) + '</b><small>average ' +
          (t.avg_pct >= 0 ? 'gain' : 'loss') + ' per pick' + (d.hold_text ? ', held ' + esc(d.hold_text) : '') + '</small></span>' +
        '<span><b>' + signed(t.index_avg_pct) + '</b><small>the market over the same time</small></span>' +
        (big ? '<span><b>' + Number(t.big_winner_pct).toFixed(0) + '%</b><small>of picks made 25% or more</small></span>' : '') +
      '</div>' +
      '<details class="pk-how"><summary>Tested on NSE prices' + (years ? ', ' + esc(years) : '') + '</summary>' +
        '<ul>' +
          '<li>' + Number(t.picks).toLocaleString('en-IN') + ' picks from ' + Number(t.list_dates).toLocaleString('en-IN') +
            ' past lists. Bought next morning, held ' + esc(d.hold_text || '') + '.</li>' +
          halves +
          '<li>Half the picks made less than ' + signed(t.median_pct) + '. One in twenty lost more than ' +
            Math.abs(Number(t.worst_5pct)).toFixed(0) + '%.</li>' +
          (finite(t.avg_sessions_held) ? '<li>The average pick was held ' + Number(t.avg_sessions_held).toFixed(1) + ' sessions.</li>' : '') +
          (t.vs_average_stock && finite(t.vs_average_stock.excess_pct)
            ? '<li>Against the average liquid stock on the same days: ' + signed(t.vs_average_stock.excess_pct, 2) + ' a pick.</li>' : '') +
          (finite(t.avg_after_costs_pct) ? '<li>After about 0.5% for buying and selling, the average pick made ' +
            signed(t.avg_after_costs_pct, 2) + '.</li>' : '') +
          (t.what ? '<li>' + esc(t.what) + '</li>' : '') +
          (t.bias ? '<li>' + esc(t.bias) + '</li>' : '') +
          '<li>Before costs and tax. The past does not promise the future.</li>' +
        '</ul></details>' +
      costHTML(t) +
    '</div>';
  }

  /* A list whose average gain did not cover the cost of trading it says so
     in the open, not inside a fold. */
  function costHTML(t) {
    if (!t || !finite(t.avg_after_costs_pct) || t.avg_after_costs_pct >= 0) return '';
    return '<p class="pk-cost">After about 0.5% for buying and selling, the average pick in the test lost ' +
      Math.abs(Number(t.avg_after_costs_pct)).toFixed(2) + '%. More picks rose than fell, but the gains were small.</p>';
  }

  /* Money flow: every sector, ranked. The top ones are where the list picks. */
  function sectorsHTML(d) {
    var rows = (d && d.sector_flow) || [];
    if (!rows.length) return '';
    var top = d.flow_sectors || 3;
    var three = rows.some(function (r) { return finite(r.month3_pct); });
    /* The industry's own index against its 60-session high: a sector breakout. */
    var idx = rows.some(function (r) { return r.near_high != null; });
    function idxCell(r) {
      if (r.near_high == null) return '—';
      return r.breakout ? 'New high' : (finite(r.from_high_pct) ? Number(r.from_high_pct).toFixed(1) + '% under' : '—');
    }
    return '<details class="pk-sectors" open><summary>Where money is moving: ' + rows.length + ' sectors ranked</summary>' +
      '<div class="pk-sectors-scroll"><table><thead><tr><th>Sector</th>' +
      (three ? '<th title="Median stock, last 63 sessions">3 months</th>' : '') +
      (idx ? '<th title="The industry\u2019s own index against its 60-session high">Index</th>' : '') +
      '<th title="Stocks above their 50-day average">Above 50-day</th>' +
      '<th title="Share of market turnover this week against its share over sixty sessions">Turnover</th>' +
      '<th title="Median stock, last 21 sessions">Month</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr' + (r.rank <= top ? ' class="on"' : '') + '><td><b>' + r.rank + '</b> ' + esc(r.sector) +
          ' <small>' + r.stocks + '</small></td>' + (three ? '<td>' + signed(r.month3_pct) + '</td>' : '') +
          (idx ? '<td>' + idxCell(r) + '</td>' : '') +
          '<td>' + (finite(r.breadth_pct) ? Math.round(r.breadth_pct) + '%' : '—') + '</td><td>' +
          (finite(r.shift) ? Number(r.shift).toFixed(2) + '×' : '—') + '</td><td>' + signed(r.month_pct) + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p>Sectors are ranked on rotation: their median stock\u2019s three months counts most, then how many of their stocks ' +
      'are above the 50-day average, then their share of trading this week against their usual share (above 1× means ' +
      'money is moving in). The list takes the strongest stocks from the top ' + top + '.' +
      (idx ? ' Index is the sector\u2019s own: \u201cNew high\u201d means it broke out to a 60-session high in the last ' +
        'ten sessions. The breakouts list wants a stock\u2019s industry within 3% of that high.' : '') + '</p></details>';
  }

  /* Breakouts: tight bases that have not broken yet. Watched, not picked. */
  function watchHTML(d) {
    var rows = (d && d.watch) || [];
    if (!rows.length) return '';
    var patterns = rows.some(function (r) { return r.pattern; });
    var cats = rows.some(function (r) { return r.catalyst; });
    return '<details class="pk-sectors pk-watch"><summary>Setting up: ' + rows.length + ' bases not yet broken</summary>' +
      '<div class="pk-sectors-scroll"><table><thead><tr><th>Stock</th>' + (patterns ? '<th>Pattern</th>' : '') +
      '<th>Top of base</th><th>Away</th><th>Range</th>' + (cats ? '<th>Catalyst</th>' : '') + '</tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr><td><a href="stock.html?ticker=' + encodeURIComponent(r.symbol) + '">' + esc(r.symbol) + '</a>' +
          (r.sector ? ' <small>' + esc(r.sector) + '</small>' : '') + '</td>' +
          (patterns ? '<td>' + esc(r.pattern || '') + '</td>' : '') + '<td>' + inr(r.top) + '</td><td>' +
          (finite(r.to_top_pct) ? Number(r.to_top_pct).toFixed(1) + '%' : '—') + '</td><td>' +
          (finite(r.width_pct) ? Number(r.width_pct).toFixed(0) + '%' : '—') + '</td>' +
          (cats ? '<td>' + esc(r.catalyst || '') + '</td>' : '') + '</tr>';
      }).join('') + '</tbody></table></div>' +
      (patterns
        ? '<p>Within 3% of the top of a base. A VCP launchpad is a base 28% wide or less that tightened; a base turnaround ' +
          'is a 60-session base 35% wide or less, in a stock not yet a leader. None has broken out: a launchpad joins the ' +
          'list above only after it closes over the top on 1.6 times its usual volume. Turnarounds are watched only.</p>'
        : '<p>Forty sessions inside a range 18% wide or tighter, within 3% of its top. None has broken out: ' +
          'a stock joins the list above only after it closes over the top on twice its usual volume.</p>') + '</details>';
  }

  /* A scan ranked before the recipes last changed. Its record would be another
     list's, so the server sends none (`recipe_current` false); this says why. */
  function recipeHTML(d) {
    return d && d.recipe_current === false
      ? '<p class="pk-quiet">Ranked with the previous recipe, so no tested record is shown. ' +
        'The next scan, after the close, ranks it the current way.</p>'
      : '';
  }

  /* A list rebuilt since the study last ran (`study_current` false). Its
     record in the study file is the record of the recipe it replaced, so the
     server sends none; this says so, plainly, in its place. A scan ranked
     with an earlier recipe already says why it has none (recipeHTML). */
  function studyHTML(d) {
    return d && d.study_current === false && d.recipe_current !== false
      ? '<p class="pk-quiet pk-measuring">Rebuilt in December 2026 to read company filings as well as prices. ' +
        'Its tested record is being measured, so none is shown yet.</p>'
      : '';
  }

  /* What the list's own calls have done since it went live. Shown only once
     there is something to show: five closed calls. Not on a list that is
     being measured again: those calls were made by the list it replaced. */
  function liveHTML(d) {
    var l = d && d.live;
    if (!l || d.study_current === false || !finite(l.closed) || l.closed < 5) return '';
    return '<p class="pk-live">Live since ' + esc(l.since || '') + ': ' + l.closed_up + ' of ' + l.closed +
      ' closed calls rose' + (finite(l.closed_avg_pct) ? ', average ' + signed(l.closed_avg_pct) : '') + '.</p>';
  }

  function tabsHTML(active, cls) {
    var pre = cls ? cls + ' ' : '';
    return '<div class="pk-chooser">' +
      tabRow(active, pre + 'hold', false, 'Holding period', 'By holding time') +
      tabRow(active, pre + 'setups', true, 'Setup', 'By chart setup') + '</div>';
  }
  /* How long a list is held, as its chip says it: the list's own `chip`, or
     its hold shortened ("about 3 months" as "~ 3 months"). */
  function holdShort(l) { return l.chip || String(l.hold || '').replace(/^about /, '~ '); }
  /* A tab's name. On a phone the setup row drops a two-word name's first
     word ("Money flow" reads "flow"), where five full names do not fit; the
     holding row has room for its three and drops only the tail of the
     longest ("Swing / This month" reads "Swing"). */
  function tabText(l) {
    if (!l.short) return esc(l.label);
    return (l.lead ? '<i>' + esc(l.lead) + '</i>' : '') + esc(l.short) +
      (l.tail ? '<i class="pk-tail">' + esc(l.tail) + '</i>' : '');
  }
  function tabRow(active, cls, setups, label, heading) {
    return '<div class="pk-group"><span class="pk-group-h" aria-hidden="true">' + heading + '</span>' +
      '<div class="pk-tabs ' + (cls || '') + '" role="tablist" aria-label="' + label + '">' +
      LISTS.filter(function (l) { return (l.group === 'setup') === setups; }).map(function (l) {
        var on = l.key === active;
        return '<button type="button" role="tab" class="pk-tab' + (on ? ' on' : '') + '" data-pick="' + l.key +
          '" aria-selected="' + on + '" aria-label="' + esc(l.label) + '"><span>' + tabText(l) + '</span>' +
          '<small>' + esc(holdShort(l)) + '</small></button>';
      }).join('') + '</div></div>';
  }

  function updatedText(d) {
    if (!d || !d.scanned_at) return '';
    var days = d.staleness && finite(d.staleness.days) ? Number(d.staleness.days) : null;
    var when = days === 0 ? 'today' : days === 1 ? 'yesterday' : days != null ? days + ' days ago'
      : String(d.scanned_at).split(',')[0];
    return 'Updated ' + when;
  }

  /* ── The door panel: top five ──────────────────────────────────────────── */

  var cache = {};
  var API = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE
    : ((typeof window !== 'undefined' && window.API_BASE) || 'https://taha-project.onrender.com');

  function load(key) {
    var hit = cache[key];
    if (hit && Date.now() - hit.at < FRESH_MS) return Promise.resolve(hit.data);
    var ctl = null, timer = null;
    try { ctl = new AbortController(); } catch (e) {}
    if (ctl) timer = setTimeout(function () { try { ctl.abort(); } catch (e) {} }, 45000);
    return fetch(API + '/ideas?horizon=' + key + '&limit=15', ctl ? { signal: ctl.signal } : {})
      .then(function (r) { if (timer) clearTimeout(timer); return r.ok ? r.json() : null; })
      .then(function (d) { if (d) cache[key] = { at: Date.now(), data: d }; return d; })
      .catch(function () { if (timer) clearTimeout(timer); return null; });
  }

  function cardHTML(s, i) {
    var p = s.plan || {};
    return '<a class="pk-card" href="stock.html?ticker=' + encodeURIComponent(s.symbol) + '" data-t="' + esc(s.symbol) + '">' +
      '<span class="pk-rank">' + (i + 1) + '</span>' +
      '<span class="pk-main">' +
        '<span class="pk-name">' + esc(s.name || s.symbol) + '</span>' +
        '<span class="pk-sym">' + esc(s.symbol) + '</span>' + patternHTML(s) + catalystBadge(s) +
        whyHTML(s) +
      '</span>' +
      /* Three prices in a row, read left to right: where it is, where a good
         result would be, and where to leave. The last two only on a list
         that is held (a legacy scan has no plan to show). */
      '<span class="pk-levels">' +
        '<span class="pk-lv"><small>Price</small><b>' + px(s.price) + '</b></span>' +
        (p.style === 'hold' && finite(p.aim)
          ? '<span class="pk-lv pk-aim"><small>Target</small><b>' + px(p.aim) + '</b>' +
            (finite(p.aim_pct) ? '<i>+' + Number(p.aim_pct).toFixed(0) + '%</i>' : '') + '</span>' : '') +
        (p.style === 'hold' && finite(p.stop)
          ? '<span class="pk-lv pk-exit"><small>Exit below</small><b>' + px(p.stop) + '</b>' +
            (finite(p.risk_pct) ? '<i>−' + Number(p.risk_pct).toFixed(0) + '%</i>' : '') + '</span>' : '') +
      '</span>' +
    '</a>';
  }

  function bodyHTML(key, d) {
    if (!d) {
      return '<p class="pk-quiet">The picks could not be loaded. If the site has been idle it takes about thirty seconds to wake. ' +
        '<button type="button" class="pk-retry" data-pick="' + key + '">Try again</button></p>';
    }
    if (!d.available) return '<p class="pk-quiet">No scan has run yet, so there are no picks to show.</p>';
    var rows = d.rows || [];
    var meta = LISTS[KEYS.indexOf(key)] || {};
    var out = '';
    if (isTested(d)) {
      out += '<p class="pk-idea">' + esc(d.idea || '') + ' <span>Hold ' + esc(d.hold_text || meta.hold || '') + '.</span></p>' +
        recordHTML(d) + studyHTML(d) + recipeHTML(d) + liveHTML(d) + marketHTML(d);
    } else {
      out += '<p class="pk-quiet">These are from the last scan, made the old way. The tested lists appear after the next scan.</p>';
    }
    if (d.staleness && d.staleness.warn) {
      out += '<p class="pk-stale">' + esc(d.staleness.text || 'This list is old.') + '</p>';
    }
    out += rows.length
      ? '<h3 class="pk-cards-h">Top ' + Math.min(5, rows.length) + ' today</h3>' +
        '<div class="pk-cards">' + rows.slice(0, 5).map(cardHTML).join('') + '</div>' + aimHTML(d)
      : '<p class="pk-quiet">' + esc(d.empty_text || 'Nothing passed every test in this scan.') + '</p>';
    out += '<div class="pk-foot">' +
      (rows.length ? '<button type="button" class="pk-all" data-goto="research/ideas">See all ' + rows.length + ' picks</button>' : '') +
      '<span class="pk-updated">' + esc(updatedText(d)) + '</span></div>';
    return out;
  }

  function mount(host) {
    if (!host || host.dataset.pkBuilt) return;
    host.dataset.pkBuilt = '1';
    var key = chosen();
    host.innerHTML = '<div class="pk-head"><h2 class="pk-title">Stock picks</h2>' +
      '<p class="pk-sub">Choose a list, see how it did when tested, then open a stock.</p></div>' +
      tabsHTML(key) + '<div class="pk-body" aria-live="polite"></div>';
    var body = host.querySelector('.pk-body');

    function show(k) {
      key = k;
      remember(k);
      host.querySelectorAll('.pk-tab').forEach(function (b) {
        var on = b.dataset.pick === k;
        b.classList.toggle('on', on);
        b.setAttribute('aria-selected', String(on));
      });
      body.innerHTML = '<div class="pk-skel"><i></i><i></i><i></i></div>';
      load(k).then(function (d) { if (key === k) body.innerHTML = bodyHTML(k, d); });
    }

    host.addEventListener('click', function (ev) {
      var tab = ev.target.closest('.pk-tab, .pk-retry');
      if (tab && host.contains(tab)) {
        if (tab.classList.contains('pk-retry')) delete cache[tab.dataset.pick];
        show(tab.dataset.pick);
        return;
      }
      var card = ev.target.closest('.pk-card');
      if (card && window.AltahaOpenStock) {
        ev.preventDefault();
        window.AltahaOpenStock(card.dataset.t, 'picks');
      }
    });
    show(key);
  }

  var api = {
    LISTS: LISTS, ALIASES: ALIASES, DEFAULT: DEFAULT, valid: valid, resolve: resolve, chosen: chosen,
    remember: remember, fromAddress: fromAddress, factorLabel: factorLabel,
    isTested: isTested, whyHTML: whyHTML, planHTML: planHTML, recordHTML: recordHTML, studyHTML: studyHTML,
    recipeHTML: recipeHTML, liveHTML: liveHTML, updatedText: updatedText, mount: mount, signed: signed, inr: inr,
    resultsHTML: resultsHTML, orderHTML: orderHTML, flowHTML: flowHTML, chartHTML: chartHTML, marketHTML: marketHTML,
    fundamentalsHTML: fundamentalsHTML,
    sectorsHTML: sectorsHTML, watchHTML: watchHTML, costHTML: costHTML, aimHTML: aimHTML, patternHTML: patternHTML,
    catalystHTML: catalystHTML, catalystBadge: catalystBadge
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.AltahaPicks = api;
})();
