/* ═══════════════════════════════════════════════════════════════════════════
   Altaha — Planner arithmetic

   WHY THE PLANNER ANSWERS WITH A DATE
   The planner used to answer with a savings rate and a letter grade. Both are
   true and neither is a reason to come back. The one figure a household
   actually steers by is WHEN: the month its investments could pay its bills,
   after which working is a choice. Everything on the screen is priced in that
   one currency — a raise, a holiday, a goal, a habit all move the date by
   some number of months, and this file is where that number is worked out.

   THE MODEL, IN FULL
   Month by month, in TODAY'S rupees, so nobody is shown a frightening nominal
   figure forty years out and asked to guess what it buys:

     corpus  = corpus × (1 + return) / (1 + inflation)  +  what was put in
     freedom = the first month corpus ≥ multiple × a year's spending

   What is put in steps up once a year, and is reduced while the cushion is
   being filled and while dated goals are being paid for — one pot of monthly
   saving, split three ways, which is the sequence the planner has always
   described in words.

   EVERY ASSUMPTION IS A DIAL, NOT A FORECAST
   Return 10% a year, inflation 6%, freedom at 30× a year's spending, saving
   raised 5% a year. They are defaults the reader can see and change, and the
   screen says so beside the answer. Nothing here predicts a market.

   NOTHING HERE RECOMMENDS A PRODUCT. It is compound interest and a
   subtraction, with the working available on request.

   Shared by planner.js (the screen) and planner-math.test.js (node), so the
   figures the screen shows are the figures the tests pin.
   ═══════════════════════════════════════════════════════════════════════════ */

(function (root) {
  'use strict';

  var DEFAULTS = { stepUp: 5, ret: 10, infl: 6, multiple: 30, after: 100 };
  var SAFE_RATE = 6.5;      // what dated money is assumed to earn: deposits, not markets
  var HORIZON = 720;        // sixty years of months; past that there is no date worth printing
  var WORK_DAYS = 22;       // working days in a month, for "days of your pay"

  /* id, label, kind, and the lower-case name used mid-sentence. `kind` is the
     50/30/20 mapping and is approximate on purpose — the screen says so. */
  var CATS = [
    ['e_rent',   'Rent / home-loan EMI',         'need', 'rent'],
    ['e_emi',    'Other EMIs / loans',           'need', 'loan EMIs'],
    ['e_groc',   'Groceries & household',        'need', 'groceries'],
    ['e_util',   'Utilities & bills',            'need', 'bills'],
    ['e_trans',  'Transport & fuel',             'need', 'transport'],
    ['e_edu',    'School / education',           'need', 'education'],
    ['e_help',   'Domestic help & staff',        'need', 'domestic help'],
    ['e_health', 'Health & insurance premiums',  'need', 'insurance'],
    ['e_eat',    'Eating out & entertainment',   'want', 'eating out'],
    ['e_shop',   'Shopping & lifestyle',         'want', 'shopping'],
    ['e_subs',   'Subscriptions',                'want', 'subscriptions'],
    ['e_misc',   'Everything else',              'want', 'everything else']
  ].map(function (c) { return { id: c[0], label: c[1], kind: c[2], name: c[3] }; });

  /* ── Small tools ─────────────────────────────────────────────────────────── */

  /* A rupee field holds whatever was typed: "1,20,000", "₹95000", "". All of
     them are a non-negative number or nothing. */
  function num(v) {
    if (typeof v === 'number') return isFinite(v) && v > 0 ? v : 0;
    var n = Number(String(v == null ? '' : v).replace(/[^\d.]/g, ''));
    return isFinite(n) && n > 0 ? n : 0;
  }
  /* A dial: blank means the default, and zero is a real answer. */
  function dial(v, fallback) {
    if (v === '' || v == null) return fallback;
    var n = Number(v);
    return isFinite(n) ? n : fallback;
  }
  function monthlyRate(pct) { return Math.pow(1 + pct / 100, 1 / 12) - 1; }
  function clone(p) {
    var q = {}, k;
    for (k in p) if (Object.prototype.hasOwnProperty.call(p, k)) q[k] = p[k];
    q.drains = (p.drains || []).slice();
    return q;
  }

  /* ── Months as 'YYYY-MM' ─────────────────────────────────────────────────── */
  function ymOf(date) {
    var d = date instanceof Date ? date : new Date(date);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }
  function ymIndex(ym) {
    var p = String(ym || '').split('-');
    return Number(p[0]) * 12 + (Number(p[1]) - 1);
  }
  function addMonths(ym, n) {
    var i = ymIndex(ym) + n;
    return Math.floor(i / 12) + '-' + String((i % 12 + 12) % 12 + 1).padStart(2, '0');
  }
  function monthsBetween(a, b) { return ymIndex(b) - ymIndex(a); }
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];
  function monthName(ym, brief) {
    var p = String(ym || '').split('-'), name = MONTHS[Number(p[1]) - 1] || '';
    return (brief ? name.slice(0, 3) : name) + ' ' + p[0];
  }
  function monthOnly(ym) { return MONTHS[Number(String(ym || '').split('-')[1]) - 1] || ''; }

  /* ── The date ────────────────────────────────────────────────────────────── */

  /* Everything in today's rupees. `months` is fractional — the crossing is
     interpolated inside its month — because a ₹5,000 purchase moves the date
     by days, and rounding to whole months would call that nothing. */
  function simulate(p) {
    var target = num(p.spend) * 12 * (dial(p.multiple, DEFAULTS.multiple) || DEFAULTS.multiple);
    var corpus = Number(p.corpus) || 0;          // may be negative: see priceTag
    var out = { target: target, months: null, path: [{ m: 0, v: corpus }] };
    if (!(target > 0)) return out;

    var growth = (1 + monthlyRate(dial(p.ret, DEFAULTS.ret))) /
                 (1 + monthlyRate(dial(p.infl, DEFAULTS.infl)));
    var prices = 1 + monthlyRate(dial(p.infl, DEFAULTS.infl));
    var step = 1 + dial(p.stepUp, 0) / 100;
    var drains = (p.drains || []).filter(function (d) { return d && d.monthly > 0 && d.months > 0; });
    var nominal = Math.max(0, Number(p.monthly) || 0);
    var deflator = 1, c = corpus;

    if (c >= target) out.months = 0;
    for (var m = 1; m <= HORIZON; m++) {
      if (m > 1 && (m - 1) % 12 === 0) nominal *= step;
      deflator *= prices;
      var pay = nominal;
      for (var i = 0; i < drains.length; i++) if (m <= drains[i].months) pay -= drains[i].monthly;
      if (pay < 0) pay = 0;
      var before = c;
      c = c * growth + pay / deflator;
      if (out.months === null && c >= target) {
        out.months = (m - 1) + (c > before ? (target - before) / (c - before) : 1);
      }
      if (m % 12 === 0) out.path.push({ m: m, v: c });
    }
    return out;
  }

  /* The same plan in the rupees of the day, `months` ahead. A check-in is
     typed off a statement, which is nominal, so the figure it is held against
     has to be nominal too. */
  function project(corpus, months, p) {
    var rm = monthlyRate(dial(p.ret, DEFAULTS.ret));
    var step = 1 + dial(p.stepUp, 0) / 100;
    var drains = (p.drains || []).filter(function (d) { return d && d.monthly > 0 && d.months > 0; });
    var nominal = Math.max(0, Number(p.monthly) || 0), c = Number(corpus) || 0;
    for (var m = 1; m <= months; m++) {
      if (m > 1 && (m - 1) % 12 === 0) nominal *= step;
      var pay = nominal;
      for (var i = 0; i < drains.length; i++) if (m <= drains[i].months) pay -= drains[i].monthly;
      c = c * (1 + rm) + Math.max(0, pay);
    }
    return c;
  }

  /* ── Goals ───────────────────────────────────────────────────────────────── */

  /* The date decides the bucket, never the other way round: money needed
     inside three years is assumed to sit in deposits, because a fall the year
     it is needed ends the plan. Longer money is assumed to earn more. */
  function goalPlan(goal, nowYM, a) {
    var ret = dial(a && a.ret, DEFAULTS.ret), infl = dial(a && a.infl, DEFAULTS.infl);
    var months = Math.max(1, monthsBetween(nowYM, goal.due));
    var bucket = months < 36 ? 'safe' : months <= 84 ? 'mixed' : 'growth';
    var rate = bucket === 'safe' ? SAFE_RATE : bucket === 'mixed' ? (SAFE_RATE + ret) / 2 : ret;
    var cost = num(goal.cost), saved = num(goal.saved);
    var future = cost * Math.pow(1 + infl / 100, months / 12);
    var rm = monthlyRate(rate), grow = Math.pow(1 + rm, months);
    var savedThen = saved * grow;
    var gap = Math.max(0, future - savedThen);
    var monthly = gap <= 0 ? 0 : (rm > 0 ? gap * rm / (grow - 1) : gap / months);
    return {
      months: months, bucket: bucket, rate: rate, future: future, savedThen: savedThen,
      gap: gap, monthly: monthly,
      progress: future > 0 ? Math.min(1, savedThen / future) : 1
    };
  }

  /* ── The cushion, and the salary-day split ───────────────────────────────── */

  /* Six months of spending, filled over a year where that is affordable and
     never with more than half of what is saved — the long run should slow
     down for the cushion, not stop. */
  function cushion(expenses, liquid, put) {
    var target = 6 * expenses, gap = Math.max(0, target - liquid);
    // Rounded so that twelve payments do fill it: 18,333 a month leaves a
    // year-long plan four rupees short and the screen saying "13 months".
    var monthly = (gap > 0 && put > 0) ? Math.min(Math.ceil(gap / 12), Math.floor(put / 2)) : 0;
    return {
      target: target, gap: gap, monthly: monthly,
      months: monthly > 0 ? Math.ceil(gap / monthly) : 0,
      cover: expenses > 0 ? liquid / expenses : null
    };
  }

  /* Cushion first, dated goals second, the long run gets the rest. The three
     always add up to `put` exactly; `short` is what the goals asked for and
     did not get. */
  function split(put, cushionMonthly, goalsMonthly) {
    put = Math.max(0, Math.round(put));
    var c = Math.min(put, Math.round(cushionMonthly));
    var g = Math.min(put - c, Math.round(goalsMonthly));
    return { put: put, cushion: c, goals: g, longRun: put - c - g,
             short: Math.max(0, Math.round(goalsMonthly) - (put - c)) };
  }

  /* ── Household health ────────────────────────────────────────────────────── */

  /* Four checks. Two of them — the rent-and-EMI load and the needs/wants
     split — cannot be judged from a single spending total, and a check that
     cannot be judged is `null`, never a pass. No grade is issued until all
     four have something to stand on. */
  function health(h) {
    var income = h.income, expenses = h.expenses;
    if (!(income > 0)) return null;
    var rate = 100 * (income - expenses) / income;
    var cover = expenses > 0 ? h.liquid / expenses : null;
    var emiRatio = h.itemised ? 100 * h.emis / income : null;
    var needsPct = h.itemised ? 100 * h.needs / income : null;
    var wantsPct = h.itemised ? 100 * h.wants / income : null;

    var score = 0;
    score += rate >= 20 ? 40 : rate >= 10 ? 25 : rate > 0 ? 12 : 0;
    score += cover === null ? 0 : cover >= 6 ? 25 : cover >= 3 ? 15 : cover >= 1 ? 6 : 0;
    var grade = null;
    if (h.itemised) {
      score += emiRatio <= 40 ? 25 : emiRatio <= 50 ? 12 : 0;
      score += wantsPct <= 30 ? 10 : wantsPct <= 40 ? 5 : 0;
      grade = score >= 85 ? 'A' : score >= 68 ? 'B+' : score >= 52 ? 'B' : score >= 36 ? 'C' : 'D';
    }
    return {
      rate: rate, cover: cover, emiRatio: emiRatio, needsPct: needsPct, wantsPct: wantsPct,
      score: h.itemised ? score : null, grade: grade,
      pass: {
        rate: rate >= 20 ? true : rate > 0 ? null : false,
        cover: cover === null ? 'na' : cover >= 6 ? true : cover >= 3 ? null : false,
        emi: emiRatio === null ? 'na' : emiRatio <= 40 ? true : emiRatio <= 50 ? null : false,
        split: wantsPct === null ? 'na'
          : (needsPct <= 55 && wantsPct <= 32) ? true : (wantsPct <= 42 ? null : false)
      }
    };
  }

  /* ── Everything the screen shows, from what was typed ────────────────────── */

  function derive(s, now) {
    s = s || {};
    var nowYM = ymOf(now || new Date());
    var a = {
      stepUp: dial(s.stepUp, DEFAULTS.stepUp), ret: dial(s.ret, DEFAULTS.ret),
      infl: dial(s.infl, DEFAULTS.infl),
      multiple: dial(s.multiple, DEFAULTS.multiple) || DEFAULTS.multiple,
      after: dial(s.after, DEFAULTS.after)
    };

    var cats = s.cats || {}, needs = 0, wants = 0, topWant = null;
    CATS.forEach(function (c) {
      var v = num(cats[c.id]);
      if (c.kind === 'need') needs += v;
      else {
        wants += v;
        if (v > 0 && (!topWant || v > topWant.amount)) topWant = { id: c.id, name: c.name, amount: v };
      }
    });
    var emis = num(cats.e_rent) + num(cats.e_emi);
    var itemised = needs + wants > 0;

    var income = num(s.salary) + num(s.other);
    var expenses = itemised ? needs + wants : num(s.spend);
    var leftover = income - expenses;
    var putSet = s.put !== '' && s.put != null && num(s.put) >= 0 && /\d/.test(String(s.put));
    var put = Math.round(putSet ? num(s.put) : Math.max(0, leftover));
    var invested = num(s.invested), liquid = num(s.liquid), age = num(s.age);

    var goals = (s.goals || []).map(function (g) {
      var plan = goalPlan(g, nowYM, a);
      return {
        id: g.id, name: g.name, kind: g.kind, due: g.due, cost: num(g.cost), saved: num(g.saved),
        months: plan.months, bucket: plan.bucket, rate: plan.rate, future: plan.future,
        savedThen: plan.savedThen, gap: plan.gap, monthly: plan.monthly, progress: plan.progress
      };
    });
    var goalsMonthly = goals.reduce(function (t, g) { return t + g.monthly; }, 0);

    var cush = cushion(expenses, liquid, put);
    var parts = split(put, cush.monthly, goalsMonthly);

    var drains = [];
    if (parts.cushion > 0) drains.push({ monthly: parts.cushion, months: cush.months });
    goals.forEach(function (g) {
      if (g.monthly > 0) drains.push({ monthly: g.monthly, months: g.months });
    });

    var params = {
      corpus: invested, monthly: put, stepUp: a.stepUp, ret: a.ret, infl: a.infl,
      spend: expenses * a.after / 100, multiple: a.multiple, drains: drains
    };
    var sim = simulate(params);
    var ready = expenses > 0 && (income > 0 || invested > 0);

    var status = !ready ? 'empty' : sim.months === 0 ? 'free' : sim.months !== null ? 'dated' : 'none';
    var why = status !== 'none' ? null
      : leftover < 0 ? 'overspend' : (put <= 0 && invested <= 0) ? 'nothing' : 'far';

    return {
      now: nowYM, a: a, income: income, expenses: expenses, needs: needs, wants: wants,
      emis: emis, itemised: itemised, leftover: leftover, put: put, putSet: putSet,
      invested: invested, liquid: liquid, age: age, topWant: topWant,
      goals: goals, goalsMonthly: goalsMonthly, cushion: cush, split: parts,
      params: params, sim: sim, ready: ready, status: status, why: why,
      when: status === 'dated' ? addMonths(nowYM, Math.ceil(sim.months))
          : status === 'free' ? nowYM : null,
      ageThen: (age > 0 && sim.months !== null) ? Math.round(age + sim.months / 12) : null,
      progress: sim.target > 0 ? Math.max(0, Math.min(1, invested / sim.target)) : 0,
      rate: income > 0 ? 100 * leftover / income : null,
      health: health({ income: income, expenses: expenses, needs: needs, wants: wants,
                       emis: emis, liquid: liquid, itemised: itemised })
    };
  }

  /* ── What moves the date ─────────────────────────────────────────────────── */

  /* Each move is the same plan with one thing changed, simulated again. The
     difference in months is the whole answer. `sooner` moves can be ticked and
     combined; `later` ones are the price of drift and are only shown. */
  function moveSet(d) {
    var p = d.params, after = d.a.after / 100, list = [];
    var extra = Math.max(1000, Math.round(d.income * 0.05 / 500) * 500);
    list.push({ id: 'more', kind: 'sooner', amount: extra,
                change: function (q) { q.monthly += extra; } });
    var to = p.stepUp < 10 ? 10 : p.stepUp + 5;
    list.push({ id: 'stepup', kind: 'sooner', from: p.stepUp, to: to,
                change: function (q) { q.stepUp = to; } });
    if (d.topWant && d.topWant.amount >= 2000) {
      var cut = Math.round(d.topWant.amount * 0.25 / 100) * 100;
      list.push({ id: 'trim', kind: 'sooner', amount: cut, name: d.topWant.name,
                  change: function (q) { q.monthly += cut; q.spend = Math.max(0, q.spend - cut * after); } });
    }
    list.push({ id: 'lean', kind: 'sooner', change: function (q) { q.spend *= 0.9; } });
    list.push({ id: 'keep', kind: 'sooner', change: function (q) { q.ret += 1; } });

    var creep = d.expenses * 0.1;
    list.push({ id: 'creep', kind: 'later', amount: creep,
                change: function (q) { q.monthly = Math.max(0, q.monthly - creep); q.spend += creep * after; } });
    list.push({ id: 'wait', kind: 'later',
                change: function (q) { q.drains = q.drains.concat([{ monthly: 1e15, months: 12 }]); } });
    list.push({ id: 'costs', kind: 'later', change: function (q) { q.ret -= 1; } });
    return list;
  }

  function moves(d) {
    return moveSet(d).map(function (mv) {
      var q = clone(d.params);
      mv.change(q);
      var sim = simulate(q);
      return {
        id: mv.id, kind: mv.kind, amount: mv.amount, name: mv.name, from: mv.from, to: mv.to,
        sim: sim,
        /* Positive is sooner. Null when either side has no date to compare. */
        delta: (d.sim.months !== null && sim.months !== null) ? d.sim.months - sim.months : null,
        /* The move that puts a date on a path that had none. */
        unlocks: d.sim.months === null && sim.months !== null
      };
    });
  }

  /* The ticked moves, all at once. Not the sum of their separate effects —
     saving more and raising it every year compound on each other. */
  function combine(d, ids) {
    var q = clone(d.params), used = 0;
    moveSet(d).forEach(function (mv) {
      if (mv.kind === 'sooner' && ids.indexOf(mv.id) > -1) { mv.change(q); used++; }
    });
    if (!used) return null;
    var sim = simulate(q);
    return {
      sim: sim, params: q,
      delta: (d.sim.months !== null && sim.months !== null) ? d.sim.months - sim.months : null,
      when: sim.months !== null ? addMonths(d.now, Math.ceil(sim.months)) : null
    };
  }

  /* ── The price of a thing, in time ───────────────────────────────────────── */

  /* A one-off purchase is money that leaves the pot. A monthly habit costs
     twice: it is not invested, AND it raises what life costs, so the finish
     line itself moves away. */
  function priceTag(d, amount, monthly) {
    var cost = num(amount), q = clone(d.params);
    if (monthly) { q.monthly = Math.max(0, q.monthly - cost); q.spend += cost; }
    else q.corpus -= cost;
    var alt = simulate(q), base = d.sim;
    var n = base.months !== null ? base.months : 240;
    var growth = (1 + monthlyRate(d.a.ret)) / (1 + monthlyRate(d.a.infl));
    var grown = monthly
      ? (growth === 1 ? cost * n : cost * (Math.pow(growth, n) - 1) / (growth - 1))
      : cost * Math.pow(growth, n);
    return {
      cost: cost, monthly: !!monthly,
      delay: (base.months !== null && alt.months !== null) ? alt.months - base.months : null,
      lost: base.months !== null && alt.months === null,
      workDays: d.income > 0 ? cost / (d.income / WORK_DAYS) : null,
      grown: grown, horizon: n, dated: base.months !== null,
      extraCorpus: monthly ? cost * 12 * d.a.multiple : 0
    };
  }

  /* A whole list of them at once — the kept list's bottom line. Not the sum
     of the separate delays, for the same reason moves are not. */
  function priceList(d, tags) {
    var q = clone(d.params), any = false;
    (tags || []).forEach(function (t) {
      var cost = num(t && t.cost);
      if (!cost) return;
      any = true;
      if (t.monthly) { q.monthly = Math.max(0, q.monthly - cost); q.spend += cost; }
      else q.corpus -= cost;
    });
    if (!any) return null;
    var alt = simulate(q);
    return {
      delay: (d.sim.months !== null && alt.months !== null) ? alt.months - d.sim.months : null,
      lost: d.sim.months !== null && alt.months === null
    };
  }

  /* ── The monthly check-in ────────────────────────────────────────────────── */

  /* A streak survives the month in progress: November's is not broken on the
     3rd just because November has not been logged yet. It is only `due`. */
  function streak(log, nowYM) {
    var seen = {}, last = null;
    (log || []).forEach(function (e) {
      if (!e || !e.ym) return;
      seen[e.ym] = true;
      if (!last || e.ym > last) last = e.ym;
    });
    var due = !seen[nowYM];
    var cursor = due ? addMonths(nowYM, -1) : nowYM, count = 0;
    while (seen[cursor]) { count++; cursor = addMonths(cursor, -1); }
    return { count: count, due: due, last: last };
  }

  /* ── Tax: old regime against new ─────────────────────────────────────────────
     AY 2026-27, the Finance Act 2025 slabs — carried over unchanged from the
     planner this file replaces, figure for figure. Salaried individual under
     60. Surcharge above ₹50 lakh is not modelled, and the screen says so. */
  var NEW_SLABS = [[0, 400000, 0], [400000, 800000, .05], [800000, 1200000, .10],
                   [1200000, 1600000, .15], [1600000, 2000000, .20],
                   [2000000, 2400000, .25], [2400000, Infinity, .30]];
  var OLD_SLABS = [[0, 250000, 0], [250000, 500000, .05], [500000, 1000000, .20],
                   [1000000, Infinity, .30]];

  function slabTax(taxable, slabs) {
    var due = 0;
    slabs.forEach(function (s) {
      if (taxable > s[0]) due += (Math.min(taxable, s[1]) - s[0]) * s[2];
    });
    return due;
  }

  function tax(t) {
    t = t || {};
    var gross = num(t.gross);
    if (!(gross > 0)) return null;

    // New regime: ₹75,000 standard deduction; nil up to ₹12 lakh taxable, with
    // marginal relief just above it.
    var newTaxable = Math.max(0, gross - 75000);
    var newTax = slabTax(newTaxable, NEW_SLABS);
    if (newTaxable <= 1200000) newTax = 0;
    else newTax = Math.min(newTax, newTaxable - 1200000);
    var newTotal = Math.round(newTax * 1.04);

    // Old regime: ₹50,000 standard deduction and the capped deductions; rebate
    // up to ₹5 lakh taxable.
    var deductions = 50000 + Math.min(num(t.c80), 150000) + num(t.d80) +
                     Math.min(num(t.nps), 50000) + Math.min(num(t.hl), 200000) + num(t.hra);
    var oldTaxable = Math.max(0, gross - deductions);
    var oldTax = slabTax(oldTaxable, OLD_SLABS);
    if (oldTaxable <= 500000) oldTax = Math.max(0, oldTax - 12500);
    var oldTotal = Math.round(oldTax * 1.04);

    var diff = oldTotal - newTotal;
    return {
      gross: gross, deductions: deductions,
      old: { tax: oldTotal, taxable: oldTaxable },
      neu: { tax: newTotal, taxable: newTaxable },
      winner: diff > 0 ? 'new' : diff < 0 ? 'old' : 'either',
      saving: Math.abs(diff),
      // Rough: assumes the extra deduction lands in the 30% band, plus cess.
      flip: diff > 0 ? deductions + diff / 0.312 : null
    };
  }

  /* ── Words and figures ───────────────────────────────────────────────────── */

  function inr(v) {
    var n = Math.round(Number(v) || 0);
    return (n < 0 ? '−' : '') + '₹' + Math.abs(n).toLocaleString('en-IN');
  }
  /* ₹2.52 Cr, ₹8 L, ₹45,000. Lakh and crore because that is how the sums on
     this screen are said aloud. */
  function short(v) {
    var n = Number(v) || 0, sign = n < 0 ? '−' : '', abs = Math.abs(n);
    function trim(x, places) { return String(Number(x.toFixed(places))); }
    if (abs >= 9995000) return sign + '₹' + trim(abs / 1e7, abs >= 1e9 ? 0 : abs >= 1e8 ? 1 : 2) + ' Cr';
    if (abs >= 99950)   return sign + '₹' + trim(abs / 1e5, abs >= 1e6 ? 1 : 2) + ' L';
    return inr(n);
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
  /* A length of time at the precision it deserves: days for a purchase,
     years and months for a plan. */
  function span(months) {
    var m = Math.abs(Number(months) || 0), days = m * 30.44;
    if (days < 1) return 'under a day';
    if (days < 14) return plural(Math.round(days), 'day');
    if (m < 2) return plural(Math.round(days / 7), 'week');
    var whole = Math.round(m);
    if (whole < 12) return plural(whole, 'month');
    var y = Math.floor(whole / 12), rest = whole % 12;
    return plural(y, 'year') + (rest ? ' ' + plural(rest, 'month') : '');
  }

  var api = {
    DEFAULTS: DEFAULTS, SAFE_RATE: SAFE_RATE, HORIZON: HORIZON, WORK_DAYS: WORK_DAYS, CATS: CATS,
    num: num, dial: dial, monthlyRate: monthlyRate,
    ymOf: ymOf, addMonths: addMonths, monthsBetween: monthsBetween,
    monthName: monthName, monthOnly: monthOnly,
    simulate: simulate, project: project, goalPlan: goalPlan, cushion: cushion, split: split,
    health: health, derive: derive, moves: moves, combine: combine, priceTag: priceTag,
    priceList: priceList, streak: streak, tax: tax, inr: inr, short: short, span: span
  };

  root.AltahaPlannerMath = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
