/* Altaha — Your portfolio, told as a story

   WHY THIS EXISTS
   The portfolio review was correct and unreadable. The "simple" view ran to
   6,700 pixels on a desktop and 10,000 on a phone; the advanced one to thirty
   sections. It opened on "Herfindahl concentration is 0.1268" and asked
   whether "the holder would accept this book if it were described only by
   its risk shares". Its own author found it confusing. Every number in it is
   right, and almost nobody was going to reach the ones that mattered.

   So the review now opens as a story: one idea per screen, one big picture,
   one plain sentence, and a line on why it matters. Ten short chapters —
   what you have, where it lives, your biggest bet, how spread out you really
   are, who is moving your money, how strong the evidence is, what a rough
   patch looks like, what is new, and the questions worth asking — then a
   recap. The full report is one button away for anyone who wants the rest.

   RULES THIS FILE KEEPS
   · Every figure comes from the report the API already sent. Nothing here
     fetches, and nothing is estimated that the report did not measure.
   · Rupee amounts always show their real value. Only the pictures animate —
     a counter ticking up through wrong numbers is still a wrong number on
     screen. Same rule as home-motion.js.
   · Observations and questions, never instructions. Nothing says buy, sell,
     add or trim: that is investment advice, which this site is not
     registered to give (see README). A chapter says "HDFCBANK is 24% of your
     money; you set 15% as the most" and asks whether that was a choice.
   · Motion off means no motion: prefers-reduced-motion or the site's own
     data-motion="off" show every chapter in its final state. Animations use
     `backwards` fill only, so nothing is ever held invisible by a paused
     animation (see frontend/tests/motion-off-browser.cjs for why that
     matters here).
   · A chapter with no data is left out, not shown empty.

   chapters(report) is pure and exported for node tests; mount() draws the
   player. */

(function (root) {
  'use strict';

  var finite = function (v) { return typeof v === 'number' && isFinite(v); };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  // **bold** inside an escaped sentence, and nothing else.
  function rich(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); }

  function trimNum(x) {
    var s = x >= 100 ? x.toFixed(0) : x >= 10 ? x.toFixed(1) : x.toFixed(2);
    return s.indexOf('.') < 0 ? s : s.replace(/0+$/, '').replace(/\.$/, '');
  }
  // ₹25,00,000 — the full figure, Indian grouping.
  function inr(v) {
    return (v < 0 ? '−' : '') + '₹' + Math.round(Math.abs(v)).toLocaleString('en-IN');
  }
  // ₹1.92 lakh — how people say it.
  function words(v) {
    var a = Math.abs(v), s = v < 0 ? '−' : '';
    if (a >= 1e7) return s + '₹' + trimNum(a / 1e7) + ' crore';
    if (a >= 1e5) return s + '₹' + trimNum(a / 1e5) + ' lakh';
    return s + '₹' + Math.round(a).toLocaleString('en-IN');
  }
  function signed(v) { return (v >= 0 ? '+' : '−') + words(Math.abs(v)); }
  function pct(v, nd) {
    var n = Number(Math.abs(v).toFixed(nd == null ? 1 : nd));
    return (v < 0 ? '−' : '') + n + '%';
  }
  function per100(w) { return Math.round(w); }
  function label(sym, name) {
    return name && name !== sym ? name : sym;
  }
  function monthYear(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return null;
    return d.toLocaleString('en-IN', { month: 'short', year: 'numeric' });
  }
  function ago(iso, now) {
    var t = new Date(iso).getTime();
    if (!isFinite(t)) return '';
    var h = Math.max(0, ((now || Date.now()) - t) / 36e5);
    if (h < 1) return 'within the hour';
    if (h < 24) return Math.round(h) + 'h ago';
    var d = Math.round(h / 24);
    return d === 1 ? 'yesterday' : d + ' days ago';
  }
  function safeURL(u) {
    try {
      var x = new URL(String(u));
      return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null;
    } catch (e) { return null; }
  }

  /* ── The chapters ─────────────────────────────────────────────────────── */

  function chapters(d, opts) {
    d = d || {};
    var now = (opts && opts.now) || Date.now();
    var rows = (d.holdings || []).filter(function (r) { return finite(r.value) && r.value > 0; });
    if (!rows.length) return [];
    var n = rows.length;
    var total = finite(d.total_value) && d.total_value > 0 ? d.total_value
      : rows.reduce(function (s, r) { return s + r.value; }, 0);
    var policy = d.policy || {};
    var byWeight = rows.slice().sort(function (a, b) { return (b.weight_pct || 0) - (a.weight_pct || 0); });
    var top = byWeight[0];
    var out = [];

    // 1 · Your money
    var covered = rows.filter(function (r) { return finite(r.pnl); }).length;
    var hasPnl = finite(d.total_pnl) && finite(d.total_cost) && d.total_cost > 0 && covered > 0;
    var money = {
      id: 'money', kicker: 'Your money',
      title: 'Your portfolio is worth ' + inr(total),
      visual: { type: 'money', n: n, hasPnl: hasPnl }
    };
    if (hasPnl) {
      var worth = d.total_cost + d.total_pnl;
      var pnlPct = finite(d.total_pnl_pct) ? d.total_pnl_pct : d.total_pnl / d.total_cost * 100;
      money.big = (d.total_pnl >= 0 ? 'Up ' : 'Down ') + words(Math.abs(d.total_pnl)) + ' · ' + pct(Math.abs(pnlPct));
      money.tone = d.total_pnl >= 0 ? 'up' : 'down';
      money.lede = covered === n
        ? 'You put in **' + words(d.total_cost) + '** across ' + n + ' companies. Today it is worth **' + words(worth) + '**.'
        : 'On the ' + covered + ' of your ' + n + ' holdings with a buy price, you put in **' + words(d.total_cost) +
          '**. Today they are worth **' + words(worth) + '**.';
      money.why = 'These gains and losses are on paper: nothing is locked in until you sell. Dividends, fees and taxes are not included.';
      money.visual.cost = d.total_cost;
      money.visual.worth = worth;
      money.visual.pnl = d.total_pnl;
    } else {
      money.lede = n + ' companies make up your portfolio. Add the price you paid for each, and this chapter shows what you have gained or lost.';
      money.why = 'Without a buy price there is no gain or loss to show — the value today is still exact.';
    }
    out.push(money);

    // 2 · Where your money lives
    var secs = (d.sectors || []).filter(function (s) { return finite(s.weight_pct) && s.weight_pct > 0; })
      .sort(function (a, b) { return b.weight_pct - a.weight_pct; });
    if (secs.length) {
      var s0 = secs[0];
      var name0 = s0.sector === 'Unclassified' ? 'companies whose industry is unknown' : s0.sector;
      var top3s = secs.slice(0, 3).reduce(function (s, x) { return s + x.weight_pct; }, 0);
      var lede = '**₹' + per100(s0.weight_pct) + ' of every ₹100** sits in ' + name0 + '.';
      if (secs.length > 2) lede += ' Your top three industries hold ₹' + per100(top3s) + ' of every ₹100.';
      if (finite(policy.max_sector_pct) && s0.sector !== 'Unclassified' && s0.weight_pct > policy.max_sector_pct) {
        lede += ' That is above the ' + pct(policy.max_sector_pct, 0) + ' industry limit you set.';
      }
      var parts = secs.slice(0, 5).map(function (s) {
        return { label: s.sector === 'Unclassified' ? 'Unknown industry' : s.sector, w: s.weight_pct };
      });
      var rest = secs.slice(5).reduce(function (s, x) { return s + x.weight_pct; }, 0);
      if (rest > 0.05) parts.push({ label: 'Everything else', w: rest });
      out.push({
        id: 'sectors', kicker: 'Where it lives', title: 'Where your money lives', lede: lede,
        why: 'Companies in one industry tend to rise and fall together — on the same news, the same interest rates, the same government policy.',
        visual: { type: 'sectors', parts: parts }
      });
    }

    // 3 · Your biggest bet
    if (top && finite(top.weight_pct) && n > 1) {
      var w = top.weight_pct, hit = total * w / 100 * 0.10;
      var lede3 = '**₹' + per100(w) + ' of every ₹100** you have invested is in this one company. If it fell 10%, your whole portfolio would fall about **' +
        pct(w / 10) + '** — roughly **' + words(hit) + '**.';
      if (finite(policy.max_stock_pct) && w > policy.max_stock_pct) {
        lede3 += ' You set ' + pct(policy.max_stock_pct, 0) + ' as the most for any one stock; this is ' + pct(w) + '.';
      }
      out.push({
        id: 'biggest', kicker: 'Your biggest bet', title: 'Your biggest bet: ' + label(top.symbol, top.name),
        lede: lede3,
        why: 'The bigger one holding is, the more a single bad quarter or bad headline can move everything you own.',
        visual: { type: 'ring', weight: w, symbol: top.symbol, cap: finite(policy.max_stock_pct) ? policy.max_stock_pct : null }
      });
    }

    // 4 · How spread out are you, really?
    var c = d.concentration || {};
    var rb = (d.ic_review || {}).risk_budget || {};
    if (finite(c.effective_n) && n > 1) {
      var eff = c.effective_n, effR = Math.max(1, Math.round(eff));
      var even = eff >= n * 0.85;
      var lede4 = even
        ? 'Your money is spread fairly evenly: your ' + n + ' stocks work like **' + trimNum(eff) + ' equal-sized holdings**.'
        : 'A few big holdings dominate, so your ' + n + ' stocks are only as spread out as **about ' + effR + ' equal-sized ones**.';
      if (finite(c.top3_pct) && n > 3) lede4 += ' Your top three hold ₹' + per100(c.top3_pct) + ' of every ₹100.';
      var riskTop = (rb.holdings || []).slice().sort(function (a, b) { return (b.risk_share_pct || 0) - (a.risk_share_pct || 0); })[0];
      if (rb.available && finite(rb.effective_risk_positions) && riskTop && finite(riskTop.risk_share_pct) &&
          riskTop.risk_share_pct > (riskTop.weight_pct || 0) + 5) {
        lede4 += ' And by how the prices actually move, **' + riskTop.symbol + '** alone drives ' + per100(riskTop.risk_share_pct) +
          '% of the ups and downs.';
      }
      out.push({
        id: 'spread', kicker: 'How spread out', title: n + ' stocks. How many real bets?', lede: lede4,
        why: 'The more evenly your money is spread across companies that do not move together, the less any one of them can hurt you.',
        visual: { type: 'dots', weights: byWeight.slice(0, 40).map(function (r) { return r.weight_pct || 0; }), eff: eff }
      });
    }

    // 5 · Who is moving your money
    // Only alongside a portfolio gain or loss the first chapter could state,
    // and only with two or more companies to compare.
    var pn = rows.filter(function (r) { return finite(r.pnl) && r.pnl !== 0; });
    if (hasPnl && pn.length >= 2) {
      var gains = pn.filter(function (r) { return r.pnl > 0; }).sort(function (a, b) { return b.pnl - a.pnl; });
      var losses = pn.filter(function (r) { return r.pnl < 0; }).sort(function (a, b) { return a.pnl - b.pnl; });
      var g = gains[0], l = losses[0], lede5;
      if (g && l) lede5 = '**' + g.symbol + '** has added the most: **' + signed(g.pnl) + '**. **' + l.symbol + '** has cost the most: **' + signed(l.pnl) + '**.';
      else if (g) lede5 = 'Every holding with a buy price is above what you paid. **' + g.symbol + '** leads with **' + signed(g.pnl) + '**.';
      else lede5 = 'Every holding with a buy price is below what you paid. **' + l.symbol + '** is down the most: **' + signed(l.pnl) + '**.';
      var items = gains.slice(0, losses.length ? 3 : 5).concat(losses.slice(0, gains.length ? 3 : 5))
        .map(function (r) { return { symbol: r.symbol, pnl: r.pnl }; });
      out.push({
        id: 'movers', kicker: 'Who moves your money', title: 'Who is making — and losing — you money', lede: lede5,
        why: 'Ranked in rupees, not percent: a small slip in a big holding can cost more than a big jump in a small one earns.',
        visual: { type: 'movers', items: items }
      });
    }

    // 6 · How strong is the evidence
    var scored = rows.filter(function (r) { return finite(r.composite); });
    if (finite(d.weighted_score) && scored.length) {
      var q = d.data_quality || {};
      var strong = scored.filter(function (r) { return r.composite >= 70; }).length;
      var lede6 = 'Weighted by the money in each, your companies score **' + trimNum(d.weighted_score) + ' out of 100**. ' +
        strong + ' of ' + scored.length + (strong === 1 ? ' is' : ' are') + ' rated Strong or better.';
      if (finite(q.scored_value_pct) && q.scored_value_pct < 99.5) {
        lede6 += ' Scores cover ' + pct(q.scored_value_pct, 0) + ' of your money; the rest is unknown, not bad.';
      }
      var floors = (d.score_distribution || []).filter(function (b) { return finite(b.floor); })
        .sort(function (a, b) { return b.floor - a.floor; });
      if (!floors.length) floors = [{ label: 'Strong', floor: 70 }, { label: 'Mixed', floor: 40 }, { label: 'Weak', floor: 0 }];
      var bands = floors.map(function (b) { return { label: b.label, floor: b.floor, symbols: [] }; });
      scored.slice().sort(function (a, b) { return b.composite - a.composite; }).forEach(function (r) {
        var band = bands.filter(function (b) { return r.composite >= b.floor; })[0];
        if (band) band.symbols.push(r.symbol);
      });
      out.push({
        id: 'score', kicker: 'The evidence', title: 'How strong is the evidence?', lede: lede6,
        why: 'The Altaha Score reads each company’s quality, growth, value, price trend and risk from its own filings and prices. It measures evidence — not the chance of making a profit.',
        visual: { type: 'gauge', score: d.weighted_score, bands: bands.filter(function (b) { return b.symbols.length; }) }
      });
    }

    // 7 · What a rough patch looks like
    var v95 = ((rb.value_at_risk || {})['95'] || {}).historical_pct;
    if (rb.available && finite(rb.worst_day_pct)) {
      var since = monthYear(rb.from);
      var dips = [];
      if (finite(v95) && v95 > 0) dips.push({ label: 'A bad day (1 in 20)', pct: -v95, inr: -total * v95 / 100 });
      dips.push({ label: 'The worst day' + (since ? ' since ' + since : ''), pct: rb.worst_day_pct, inr: total * rb.worst_day_pct / 100 });
      if (finite(rb.window_drawdown_pct) && rb.window_drawdown_pct < 0) {
        dips.push({ label: 'The deepest dip from a high', pct: rb.window_drawdown_pct, inr: total * rb.window_drawdown_pct / 100 });
      }
      var lede7 = finite(v95) && v95 > 0
        ? 'On about **1 day in 20**, your portfolio lost more than **' + words(total * v95 / 100) + '**. '
        : '';
      lede7 += 'Its worst single day' + (since ? ' since ' + since : '') + ' was **' + pct(rb.worst_day_pct) + '** — about **' +
        words(Math.abs(total * rb.worst_day_pct / 100)) + '** at today’s size.';
      out.push({
        id: 'rough', kicker: 'A rough patch', title: 'What a rough patch looks like', lede: lede7,
        why: 'Worked out by replaying the stocks you hold today over past prices. It describes what already happened — it is not a forecast, and not the most you could lose.',
        visual: { type: 'dips', items: dips }
      });
    } else {
      var sc = (d.scenarios || []).filter(function (s) { return finite(s.impact_inr) && s.impact_inr < 0; });
      if (sc.length) {
        var a = sc[0], b2 = sc[1];
        out.push({
          id: 'rough', kicker: 'A rough patch', title: 'If the market has a bad week',
          lede: 'If ' + scenarioPhrase(a.name) + ', you would be down about **' + words(Math.abs(a.impact_inr)) + '**.' +
            (b2 ? ' If ' + scenarioPhrase(b2.name) + ', about **' + words(Math.abs(b2.impact_inr)) + '**.' : ''),
          why: 'Simple arithmetic on what you hold today — not a prediction of what will happen.',
          visual: { type: 'dips', items: sc.slice(0, 3).map(function (s) { return { label: s.name, pct: s.impact_pct, inr: s.impact_inr }; }) }
        });
      }
    }

    // 8 · What is new
    if (d.developments && Array.isArray(d.developments.events)) {
      var ev = d.developments.events.filter(function (e) { return e && e.headline; }).slice(0, 3);
      out.push({
        id: 'news', kicker: 'What is new',
        title: ev.length ? 'What is new with your companies' : 'A quiet week for your companies',
        lede: ev.length
          ? (ev.length === 1 ? 'One filing or story' : ev.length + ' filings and stories') + ' touched your holdings recently.'
          : 'No filings or news turned up for your holdings in the last seven days.',
        why: 'Headlines are shown as published. Whether one matters to you depends on the detail — open the source before reading anything into a headline.',
        visual: {
          type: 'news', items: ev.map(function (e) {
            return { headline: e.headline, source: e.source || '', symbols: (e.symbols || []).slice(0, 3),
                     when: ago(e.published_at, now), url: safeURL(e.url) };
          })
        }
      });
    }

    // 9 · Questions worth asking
    var qs = questions(d, rb);
    if (qs.length) {
      out.push({
        id: 'questions', kicker: 'Worth asking',
        title: (qs.length === 1 ? 'One question' : ['', '', 'Two', 'Three'][qs.length] + ' questions') + ' worth asking yourself',
        lede: 'Not instructions. Each comes from a limit you set or a measurement in your report, and only you know the answer.',
        why: 'Your portfolio policy — the limits these are measured against — can be changed under “Your portfolio policy” above.',
        visual: { type: 'questions', items: qs }
      });
    }

    // 10 · In one breath
    var facts = [['Worth today', inr(total)]];
    if (hasPnl) facts.push(['Gain or loss', signed(d.total_pnl)]);
    if (top && n > 1 && finite(top.weight_pct)) facts.push(['Biggest bet', top.symbol + ' · ' + pct(top.weight_pct)]);
    if (secs.length) facts.push(['Biggest industry', (secs[0].sector === 'Unclassified' ? 'Unknown' : secs[0].sector) + ' · ' + pct(secs[0].weight_pct)]);
    if (finite(c.effective_n) && n > 1) facts.push(['Spread like', Math.max(1, Math.round(c.effective_n)) + ' equal stocks']);
    if (finite(d.weighted_score)) facts.push(['Evidence score', trimNum(d.weighted_score) + ' / 100']);
    out.push({
      id: 'recap', kicker: 'In one breath', title: 'Your portfolio, in one breath',
      lede: 'That is the story. The full report has every number behind it — each holding, each measurement, and how it was worked out.',
      why: 'Educational analysis of what you hold — not a recommendation to buy or sell anything.',
      visual: { type: 'recap', facts: facts }
    });

    return out;
  }

  // "All priced holdings −5%" → "every holding fell 5%";
  // "Financial Services −10%" → "Financial Services alone fell 10%".
  function scenarioPhrase(name) {
    var s = String(name || ''), m = /^All priced holdings\s*[−-]\s*(\d+(?:\.\d+)?)%$/.exec(s);
    if (m) return 'every holding fell ' + m[1] + '%';
    m = /^(.+?)\s*[−-]\s*(\d+(?:\.\d+)?)%$/.exec(s);
    return m ? m[1] + ' alone fell ' + m[2] + '%' : s;
  }

  /* The review agenda, reworded. The agenda's own questions are written for
     an investment committee ("Would the holder accept this book if it were
     described only by its risk shares?"); these ask the same thing of a
     person. The measurements are the agenda's, unchanged. */
  function questions(d, rb) {
    var ag = ((d.ic_review || {}).agenda || []).slice().sort(function (a, b) { return (a.rank || 99) - (b.rank || 99); });
    var weightOf = {};
    (d.holdings || []).forEach(function (r) { weightOf[r.symbol] = r.weight_pct; });
    // One question per kind of finding: two stocks over the same limit are
    // one question about that limit, not the same question asked twice.
    var groups = [], byRule = {};
    ag.forEach(function (a) {
      var subject = String(a.title || '').split('·').slice(1).join('·').trim();
      var key = a.rule === 'risk_budget' ? 'risk_share' : a.rule;
      if (!byRule[key]) { byRule[key] = { rule: key, items: [] }; groups.push(byRule[key]); }
      byRule[key].items.push({ subject: subject, measured: a.measured, limit: a.limit, a: a });
    });
    function names(items, fmt) {
      var shown = items.slice(0, 2).map(fmt);
      var more = items.length - shown.length;
      return shown.length === 1 ? shown[0]
        : more > 0 ? shown.join(', ') + ' and ' + more + ' more'
        : shown.join(' and ');
    }
    var out = [];
    groups.forEach(function (g) {
      if (out.length >= 3) return;
      var items = g.items.filter(function (x) { return x.subject && finite(x.measured) && finite(x.limit); });
      var first = items[0], many = items.length > 1;
      if (g.rule === 'max_stock_pct' && first) {
        out.push({ head: many ? names(items, function (x) { return x.subject + ' (' + pct(x.measured) + ')'; }) + ' are above your per-stock limit'
                              : first.subject + ' is ' + pct(first.measured) + ' of your money',
                   fact: 'You set ' + pct(first.limit, 0) + ' as the most for any one stock.' +
                     (many ? ' Together these hold ₹' + per100(items.reduce(function (s, x) { return s + x.measured; }, 0)) + ' of every ₹100.' : ''),
                   question: many ? 'Did you mean for them to be this big, or have they grown there on their own?'
                                  : 'Did you mean for it to be this big, or has it grown there on its own?' });
      } else if (g.rule === 'max_sector_pct' && first) {
        out.push({ head: many ? names(items, function (x) { return x.subject; }) + ' are above your industry limit'
                              : first.subject + ' is ' + pct(first.measured) + ' of your money',
                   fact: 'Your limit for any one industry is ' + pct(first.limit, 0) + '.',
                   question: 'Is this much in one industry a choice you made?' });
      } else if (g.rule === 'min_composite' && first) {
        out.push({ head: many ? names(items, function (x) { return x.subject + ' (' + Math.round(x.measured) + ')'; }) + ' score below your floor of ' + Math.round(first.limit)
                              : first.subject + ' scores ' + Math.round(first.measured) + ' — below your floor of ' + Math.round(first.limit),
                   fact: (many ? 'Their' : 'Its') + ' filings and price trend give weak evidence right now.',
                   question: 'What do you know about ' + (many ? 'these companies' : 'this company') + ' that the numbers do not show?' });
      } else if (g.rule === 'risk_share') {
        var named = g.items.filter(function (x) { return x.a.rule === 'risk_share' && x.subject && finite(x.measured); })[0];
        var who = named && named.subject;
        out.push({ head: who ? who + ' causes ' + per100(named.measured) + '% of the swings' : 'A few stocks cause most of the swings',
                   fact: who && finite(weightOf[who])
                     ? 'It is ' + pct(weightOf[who]) + ' of your money, but moves the whole portfolio more than that.'
                     : 'How much a stock moves your portfolio depends on its size and on how jumpy it is.',
                   question: 'Are you comfortable with this much of your ups and downs coming from so few places?' });
      } else {
        var a = g.items[0].a;
        if (a.question) out.push({ head: String(a.title || '').replace('·', '—'), fact: a.arithmetic || '', question: a.question });
      }
    });
    return out;
  }

  /* ── The pictures ─────────────────────────────────────────────────────── */

  var PALETTE = 6;

  function visual(v) {
    switch (v.type) {
      case 'money': return moneyVis(v);
      case 'sectors': return sectorVis(v);
      case 'ring': return ringVis(v);
      case 'dots': return dotsVis(v);
      case 'movers': return moversVis(v);
      case 'gauge': return gaugeVis(v);
      case 'dips': return dipsVis(v);
      case 'news': return newsVis(v);
      case 'questions': return questionsVis(v);
      case 'recap': return recapVis(v);
    }
    return '';
  }

  function moneyVis(v) {
    if (!v.hasPnl) {
      var coins = '';
      for (var i = 0; i < Math.min(v.n, 40); i++) coins += '<i style="--i:' + i + '"></i>';
      return '<div class="ps-coins" aria-hidden="true">' + coins + '</div>';
    }
    var max = Math.max(v.cost, v.worth);
    var cw = v.cost / max * 100, ww = v.worth / max * 100;
    var up = v.pnl >= 0;
    return '<div class="ps-money">' +
      '<div class="ps-mrow"><span class="ps-mlab">You put in</span><span class="ps-mbar"><i style="--w:' + cw.toFixed(2) + '%"></i></span><b>' + esc(words(v.cost)) + '</b></div>' +
      '<div class="ps-mrow is-now"><span class="ps-mlab">Worth today</span><span class="ps-mbar"><i class="' + (up ? 'up' : 'down') + '" style="--w:' + ww.toFixed(2) + '%"></i></span><b>' + esc(words(v.worth)) + '</b></div>' +
      '<p class="ps-mdelta ' + (up ? 'up' : 'down') + '"><span aria-hidden="true">' + (up ? '▲' : '▼') + '</span> ' + esc(signed(v.pnl)) + '</p>' +
    '</div>';
  }

  function sectorVis(v) {
    var segs = v.parts.map(function (p, i) {
      return '<span class="ps-seg c' + (i % PALETTE) + '" style="--w:' + p.w.toFixed(2) + '%" title="' + esc(p.label + ': ' + pct(p.w)) + '"></span>';
    }).join('');
    var legend = v.parts.map(function (p, i) {
      return '<li style="--i:' + i + '"><i class="c' + (i % PALETTE) + '"></i><span>' + esc(p.label) + '</span><b>₹' + per100(p.w) + '</b></li>';
    }).join('');
    return '<div class="ps-sectors"><div class="ps-stack" role="img" aria-label="' +
      esc(v.parts.map(function (p) { return p.label + ' ' + pct(p.w); }).join(', ')) + '">' + segs + '</div>' +
      '<p class="ps-cap">Of every ₹100 you have invested</p><ul class="ps-legend">' + legend + '</ul></div>';
  }

  function ringVis(v) {
    var w = Math.max(0, Math.min(100, v.weight));
    var cap = v.cap != null && v.cap > 0 && v.cap < 100
      ? '<circle class="ps-ring-cap" cx="60" cy="60" r="50" pathLength="100" style="--cap:' + v.cap + '"></circle>' : '';
    return '<div class="ps-ringwrap"><svg class="ps-ring" viewBox="0 0 120 120" role="img" aria-label="' +
      esc(v.symbol + ' is ' + pct(w) + ' of your portfolio') + '">' +
      '<circle class="ps-ring-bg" cx="60" cy="60" r="50"></circle>' +
      '<circle class="ps-ring-fg" cx="60" cy="60" r="50" pathLength="100" style="--w:' + w.toFixed(2) + '"></circle>' + cap +
      '</svg><div class="ps-ring-mid"><b>' + esc(pct(w)) + '</b><span>' + esc(v.symbol) + '</span></div>' +
      (v.cap != null ? '<p class="ps-cap"><i class="ps-key cap"></i> your ' + esc(pct(v.cap, 0)) + ' limit per stock</p>' : '') +
    '</div>';
  }

  function dotsVis(v) {
    var maxW = Math.max.apply(null, v.weights.concat([1]));
    var size = function (w) { return (10 + 36 * Math.sqrt(Math.max(0, w) / maxW)).toFixed(1); };
    var mine = v.weights.map(function (w, i) { return '<i style="--s:' + size(w) + 'px;--i:' + i + '"></i>'; }).join('');
    var k = Math.max(1, Math.round(v.eff));
    var eqW = 100 / Math.max(1, v.eff), eq = '';
    for (var i = 0; i < Math.min(k, 40); i++) eq += '<i style="--s:' + size(eqW) + 'px;--i:' + (i + v.weights.length) + '"></i>';
    return '<div class="ps-dots">' +
      '<div class="ps-drow"><span class="ps-dlab">What you own · ' + v.weights.length + '</span><div class="ps-dset">' + mine + '</div></div>' +
      '<div class="ps-darrow" aria-hidden="true">↓</div>' +
      '<div class="ps-drow is-eq"><span class="ps-dlab">How spread out it really is · about ' + k + '</span><div class="ps-dset">' + eq + '</div></div>' +
    '</div>';
  }

  function moversVis(v) {
    var max = Math.max.apply(null, v.items.map(function (m) { return Math.abs(m.pnl); }).concat([1]));
    return '<ul class="ps-movers">' + v.items.map(function (m, i) {
      var up = m.pnl >= 0, w = (Math.abs(m.pnl) / max * 100).toFixed(1);
      return '<li class="' + (up ? 'up' : 'down') + '" style="--i:' + i + '"><span class="ps-sym">' + esc(m.symbol) + '</span>' +
        '<span class="ps-track"><span class="ps-half l">' + (up ? '' : '<i style="--w:' + w + '%"></i>') + '</span>' +
        '<span class="ps-half r">' + (up ? '<i style="--w:' + w + '%"></i>' : '') + '</span></span>' +
        '<b>' + esc(signed(m.pnl)) + '</b></li>';
    }).join('') + '</ul>';
  }

  function gaugeVis(v) {
    var s = Math.max(0, Math.min(100, v.score));
    var bands = v.bands.map(function (b, i) {
      var chips = b.symbols.slice(0, 8).map(function (sym, j) {
        return '<span class="ps-chip" style="--i:' + (i * 2 + j) + '">' + esc(sym) + '</span>';
      }).join('') + (b.symbols.length > 8 ? '<span class="ps-chip more">+' + (b.symbols.length - 8) + '</span>' : '');
      return '<div class="ps-band"><span class="ps-bl">' + esc(b.label) + ' <small>' + b.floor + '+</small></span><div class="ps-chips">' + chips + '</div></div>';
    }).join('');
    return '<div class="ps-gauge"><div class="ps-gtrack" role="img" aria-label="' + esc('Weighted score ' + trimNum(s) + ' out of 100') + '">' +
      '<span class="ps-gneedle" style="--x:' + s.toFixed(1) + '%"><b>' + esc(trimNum(s)) + '</b></span></div>' +
      '<div class="ps-gscale" aria-hidden="true"><span>0</span><span>50</span><span>100</span></div></div>' +
      '<div class="ps-bands">' + bands + '</div>';
  }

  function dipsVis(v) {
    var max = Math.max.apply(null, v.items.map(function (x) { return Math.abs(x.pct); }).concat([0.01]));
    return '<ul class="ps-dips">' + v.items.map(function (x, i) {
      return '<li style="--i:' + i + '"><span class="ps-dl">' + esc(x.label) + '</span>' +
        '<span class="ps-dtrack"><i style="--w:' + (Math.abs(x.pct) / max * 100).toFixed(1) + '%"></i></span>' +
        '<b>' + esc(pct(x.pct)) + ' <small>' + esc(words(Math.abs(x.inr))) + '</small></b></li>';
    }).join('') + '</ul>';
  }

  function newsVis(v) {
    if (!v.items.length) {
      return '<div class="ps-calm" aria-hidden="true"><svg viewBox="0 0 200 60"><path d="M0 40 Q 25 30 50 40 T 100 40 T 150 40 T 200 40"></path></svg></div>';
    }
    return '<ul class="ps-news">' + v.items.map(function (x, i) {
      var head = x.url ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.headline) + '</a>' : '<span>' + esc(x.headline) + '</span>';
      return '<li style="--i:' + i + '"><span class="ps-ntag">' + esc(x.symbols.join(' · ')) + '</span>' + head +
        '<small>' + esc([x.source, x.when].filter(Boolean).join(' · ')) + '</small></li>';
    }).join('') + '</ul>';
  }

  function questionsVis(v) {
    return '<ol class="ps-qs">' + v.items.map(function (q, i) {
      return '<li style="--i:' + i + '"><span class="ps-qn">' + (i + 1) + '</span><div><b>' + esc(q.head) + '</b>' +
        (q.fact ? '<p>' + esc(q.fact) + '</p>' : '') + '<q>' + esc(q.question) + '</q></div></li>';
    }).join('') + '</ol>';
  }

  function recapVis(v) {
    return '<dl class="ps-recap">' + v.facts.map(function (f, i) {
      return '<div style="--i:' + i + '"><dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd></div>';
    }).join('') + '</dl><div class="ps-end"><button type="button" class="ps-btn primary" data-ps="full">Read the full report</button>' +
      '<button type="button" class="ps-btn" data-ps="replay">Watch again</button></div>';
  }

  /* ── The player ───────────────────────────────────────────────────────── */

  function shell(chs, idx) {
    return '<div class="ps" role="region" aria-roledescription="carousel" aria-label="Your portfolio story" tabindex="-1">' +
      '<div class="ps-head"><span class="ps-eyebrow">Your portfolio story</span>' +
        '<span class="ps-count" aria-live="polite"></span></div>' +
      '<div class="ps-progress" aria-hidden="true">' + chs.map(function (c, i) {
        return '<button type="button" tabindex="-1" class="ps-pip" data-ps-go="' + i + '" title="' + esc(c.kicker) + '"><i></i></button>';
      }).join('') + '</div>' +
      '<div class="ps-stage">' + chs.map(function (c, i) {
        return '<article class="ps-ch" data-ch="' + esc(c.id) + '" aria-roledescription="slide" aria-label="' +
          esc((i + 1) + ' of ' + chs.length + ': ' + c.kicker) + '"' + (i === idx ? '' : ' hidden') + '>' +
          '<div class="ps-copy"><span class="ps-kicker">' + esc(c.kicker) + '</span>' +
            '<h3>' + esc(c.title) + '</h3>' +
            (c.big ? '<p class="ps-big ' + esc(c.tone || '') + '">' + esc(c.big) + '</p>' : '') +
            '<p class="ps-lede">' + rich(c.lede) + '</p>' +
            (c.why ? '<p class="ps-why">' + esc(c.why) + '</p>' : '') +
          '</div><div class="ps-visual">' + visual(c.visual) + '</div></article>';
      }).join('') + '</div>' +
      '<div class="ps-nav">' +
        '<button type="button" class="ps-btn ps-prev" data-ps="prev"><span aria-hidden="true">←</span> Back</button>' +
        '<button type="button" class="ps-skip" data-ps="full">Skip to the full report</button>' +
        '<button type="button" class="ps-btn primary ps-next" data-ps="next">Next <span aria-hidden="true">→</span></button>' +
      '</div></div>';
  }

  var mounted = typeof WeakMap === 'function' ? new WeakMap() : null;

  function show(host, st, idx, animate) {
    var arts = host.querySelectorAll('.ps-ch');
    idx = Math.max(0, Math.min(arts.length - 1, idx));
    st.idx = idx;
    st.id = st.chs[idx].id;
    for (var i = 0; i < arts.length; i++) {
      var on = i === idx;
      arts[i].hidden = !on;
      if (!on) arts[i].classList.remove('is-on');
    }
    var cur = arts[idx];
    if (animate) {
      cur.classList.remove('is-on');
      void cur.offsetWidth;            // restart the chapter's entrance
    }
    // On a phone a chapter is taller than the screen and Next sits at its
    // foot: turning the page should show the new page from its top.
    if (st.userTurned && host.getBoundingClientRect && host.getBoundingClientRect().top < 0 && host.scrollIntoView) {
      var still = root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches;
      host.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' });
    }
    cur.classList.add('is-on');
    var pips = host.querySelectorAll('.ps-pip');
    for (var j = 0; j < pips.length; j++) {
      pips[j].classList.toggle('done', j < idx);
      pips[j].classList.toggle('now', j === idx);
    }
    var count = host.querySelector('.ps-count');
    if (count) count.textContent = 'Chapter ' + (idx + 1) + ' of ' + arts.length;
    var prev = host.querySelector('.ps-prev'), next = host.querySelector('.ps-next');
    if (prev) prev.disabled = idx === 0;
    if (next) {
      var last = idx === arts.length - 1;
      next.hidden = last;
    }
    var skip = host.querySelector('.ps-skip');
    if (skip) skip.hidden = idx === arts.length - 1;
    if (!st.seen[st.id] && root.AltahaTrack) {
      st.seen[st.id] = 1;
      root.AltahaTrack('portfolio_story_viewed', { chapter: st.id, index: idx + 1, total: arts.length });
    }
  }

  function wire(host) {
    if (host.__psWired) return;
    host.__psWired = true;
    function state() { return mounted && mounted.get(host); }
    host.addEventListener('click', function (e) {
      var st = state();
      if (!st) return;
      var t = e.target.closest ? e.target.closest('[data-ps],[data-ps-go]') : null;
      if (!t || !host.contains(t)) return;
      var act = t.getAttribute('data-ps');
      st.userTurned = true;
      if (t.hasAttribute('data-ps-go')) show(host, st, Number(t.getAttribute('data-ps-go')), true);
      else if (act === 'next') show(host, st, st.idx + 1, true);
      else if (act === 'prev') show(host, st, st.idx - 1, true);
      else if (act === 'replay') { show(host, st, 0, true); var p = host.querySelector('.ps'); if (p && p.focus) p.focus({ preventScroll: true }); }
      else if (act === 'full' && st.onFull) st.onFull(t.classList.contains('ps-skip') ? 'story_skip' : 'story_end');
    });
    host.addEventListener('keydown', function (e) {
      var st = state();
      if (!st || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight') { show(host, st, st.idx + 1, true); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { show(host, st, st.idx - 1, true); e.preventDefault(); }
    });
    // A horizontal swipe on a touch screen turns the page; a vertical one
    // still scrolls the page, and a tap still follows a link.
    var x0 = null, y0 = null;
    host.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'touch') return;
      x0 = e.clientX; y0 = e.clientY;
    });
    host.addEventListener('pointerup', function (e) {
      var st = state();
      if (x0 == null || !st) return;
      var dx = e.clientX - x0, dy = e.clientY - y0;
      x0 = y0 = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) show(host, st, st.idx + (dx < 0 ? 1 : -1), true);
    });
  }

  /* Draw the story into `host`. Returns false (and hides the host) when the
     report has nothing to tell yet. Called again for every staged update of
     the same portfolio — cached valuation, then prices, then the complete
     report — so a reader part-way through keeps their chapter, and nothing
     replays under them. */
  function mount(host, d, opts) {
    if (!host) return false;
    var chs = chapters(d);
    if (!chs.length) { host.hidden = true; host.innerHTML = ''; return false; }
    var key = (d.holdings || []).map(function (r) { return r.symbol; }).sort().join(',');
    var prev = mounted && mounted.get(host);
    var same = !!(prev && prev.key === key);
    var idx = 0;
    if (same) {
      var j = chs.map(function (c) { return c.id; }).indexOf(prev.id);
      idx = j >= 0 ? j : Math.min(prev.idx, chs.length - 1);
    }
    host.innerHTML = shell(chs, idx);
    host.hidden = false;
    var st = { key: key, idx: idx, id: chs[idx].id, chs: chs, seen: same ? prev.seen : {},
               onFull: opts && opts.onFull };
    if (mounted) mounted.set(host, st);
    wire(host);
    show(host, st, idx, !same);
    return true;
  }

  function destroy(host) {
    if (!host) return;
    host.innerHTML = '';
    host.hidden = true;
    if (mounted) mounted.delete(host);
  }

  root.PortfolioStory = { chapters: chapters, mount: mount, destroy: destroy };
  if (typeof module !== 'undefined') module.exports = { chapters: chapters, questions: questions, words: words, inr: inr,
    html: function (chs) { return shell(chs, 0); } };
})(typeof window !== 'undefined' ? window : globalThis);
