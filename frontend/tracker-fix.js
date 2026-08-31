/* ============================================================================
   Altaha — Tracker repairs
   ----------------------------------------------------------------------------
   Three things were wrong with the Tracker tab, and they had different causes.

   1. EVERY PRICE COLUMN WAS BLANK.
      The columns are filled by tracker.update_all(), which is called from
      exactly one place: /cron/tick, and only after 16:00 IST. With no external
      cron pointed at that endpoint, it had never run — so every row showed
      "Now ₹—, Return —, Index —, 0 days" forever. There is now a Refresh
      prices button that calls the marking routine directly, and the tab says
      how many rows are still unmarked instead of leaving you to guess.

   2. STOCKS APPEARED WITHOUT BEING ADDED.
      That is deliberate in the engine — recording only the ideas someone
      chooses to save turns a hit rate into a highlight reel. It is the right
      default for measuring the engine and the wrong one for a watchlist. The
      My picks filter separates the two, and Clear auto-recorded removes the
      scan's rows in one go. Set AUTOTRACK=0 on Render to stop new ones.

   3. THERE WAS NO WAY TO REMOVE ANYTHING.
      The backend has had /tracker/remove all along; nothing in the interface
      ever called it. Each row now carries a Remove control.

   This file replaces the page's own loadTracker(). It does not modify it in
   place, so deleting this one <script> line restores the original behaviour
   exactly.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_TRACKERFIX__) return;
  window.__ALTAHA_TRACKERFIX__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function pct(v) { return v == null ? "\u2014" : (v > 0 ? "+" : "") + v + "%"; }
  function sign(v) { return v == null ? "" : (v > 0 ? "pos" : (v < 0 ? "neg" : "")); }
  function rupee(v) { return v == null ? "\u2014" : "\u20B9" + Number(v).toLocaleString("en-IN"); }

  /* "manual" = only what you pressed Add on, "" = the whole ledger.
     BUGFIX: this started as "" and the request then omitted the source
     parameter entirely — but the backend defaults /tracker/list to "manual",
     so the tab was already showing manual rows while claiming to show
     everything. Pressing "My picks only" filtered a list that was already
     filtered and visibly did nothing. The filter now starts where the backend
     actually starts, the button says which way it will move, and the source is
     always sent explicitly so the two ends cannot drift apart again. */
  var srcFilter = "manual";

  /* ---- styles, on the existing tokens ---------------------------------- */

  var css = document.createElement("style");
  css.textContent = [
    /* Scoped: a bare .tk also matches every item in the market ticker strip. */
    "#tkrows .tk{position:relative}",
    ".tkrm{position:absolute;top:10px;right:10px;border:1px solid var(--rule);",
    "  background:var(--paper);color:var(--mute);border-radius:999px;cursor:pointer;",
    "  font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;",
    "  padding:4px 10px;transition:border-color 150ms,color 150ms,background 150ms}",
    ".tkrm:hover{border-color:var(--fail);color:var(--fail)}",
    ".tkrm[disabled]{opacity:.5;cursor:default}",
    "#tkrows .tk .tkt{padding-right:86px}",
    ".tkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}",
    ".tkflag{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--mute);",
    "  border-left:2px solid var(--gold);padding:2px 0 2px 10px;margin:0 0 12px;line-height:1.7}",
    ".tksrc{font-family:var(--mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;",
    "  color:var(--mute);border:1px solid var(--rule-2);border-radius:999px;padding:2px 7px;margin-left:8px}",
    /* The mobile override used to unset position:absolute. Remove is the first
       child of the card, so going static put the button ABOVE the company
       name — which is where the screenshot showed it. It stays pinned
       top-right at every width; only its size changes. */
    "@media(max-width:560px){.tkrm{top:8px;right:8px;padding:3px 8px;font-size:8px}",
    "  #tkrows .tk .tkt{padding-right:74px}}"
  ].join("\n");
  document.head.appendChild(css);

  /* ---- toolbar --------------------------------------------------------- */

  function toolbar() {
    var host = $("view-tracker");
    if (!host || $("tkbar2")) return;
    var bar = document.createElement("div");
    bar.className = "tkbar";
    bar.id = "tkbar2";
    bar.innerHTML =
      '<button class="act solid" id="tkrefresh" type="button">Refresh prices</button>' +
      '<button class="act solid" id="tkmine" type="button">Showing my picks</button>' +
      '<button class="act" id="tkclearauto" type="button">Clear auto-recorded</button>' +
      '<button class="act" id="tkdiag" type="button">Diagnose</button>';
    var anchor = $("tkstats");
    host.insertBefore(bar, anchor);

    $("tkrefresh").addEventListener("click", refresh);
    $("tkmine").addEventListener("click", function () {
      srcFilter = srcFilter === "manual" ? "" : "manual";
      this.classList.toggle("solid", srcFilter === "manual");
      this.textContent = srcFilter === "manual" ? "Showing my picks" : "Showing everything";
      render();
    });
    $("tkclearauto").addEventListener("click", clearAuto);
    $("tkdiag").addEventListener("click", diagnose);
  }

  /* ---- diagnostics -----------------------------------------------------
     When marking produces nothing there are six places it can be failing and
     no way to tell them apart from the outside: the backend may be the old
     build, the admin guard may be closed, both price feeds may be refusing
     the symbol, the request may be timing out, or the rows may be getting
     wiped between the write and the read. This runs one small batch and puts
     the raw answer on the page. */

  async function diagnose() {
    var b = $("tkdiag");
    b.disabled = true; b.textContent = "Checking\u2026";
    var box = $("tkdiagout");
    if (!box) {
      box = document.createElement("pre");
      box.id = "tkdiagout";
      box.style.cssText = "white-space:pre-wrap;word-break:break-word;font-family:var(--mono);" +
        "font-size:11px;line-height:1.7;background:var(--paper-2);border:1px solid var(--rule);" +
        "border-radius:9px;padding:14px 16px;margin:0 0 16px;max-height:420px;overflow:auto;color:var(--ink-2)";
      $("view-tracker").insertBefore(box, $("tkstats"));
    }
    var out = [];
    function log(k, v) { out.push(k + ": " + v); box.textContent = out.join("\n"); }

    log("api", API);
    log("time", new Date().toISOString());

    async function get(path) {
      var t0 = Date.now();
      try {
        var r = await fetch(API + path);
        var txt = await r.text();
        return { ok: r.ok, status: r.status, ms: Date.now() - t0, txt: txt };
      } catch (e) {
        return { ok: false, status: 0, ms: Date.now() - t0, txt: String(e && e.message || e) };
      }
    }

    var ds = await get("/datasource");
    log("GET /datasource", ds.status + " in " + ds.ms + "ms");
    log("  ", ds.txt.slice(0, 420));

    var stt = await get("/tracker/stats");
    log("GET /tracker/stats", stt.status + " in " + stt.ms + "ms");
    try {
      var sj = JSON.parse(stt.txt);
      log("  total_tracked", sj.total_tracked);
      log("  unmarked", sj.unmarked === undefined ? "FIELD MISSING -> backend is the OLD tracker.py" : sj.unmarked);
      log("  mark_errors", sj.mark_errors === undefined ? "n/a" : sj.mark_errors);
      log("  autotrack", sj.autotrack === undefined ? "n/a" : sj.autotrack);
      log("  ephemeral_storage", sj.storage_is_ephemeral);
    } catch (e) { log("  parse failed", stt.txt.slice(0, 200)); }

    log("POST /tracker/update?limit=2", "running, please wait\u2026");
    var t0 = Date.now();
    try {
      var ctrl = new AbortController();
      var bail = setTimeout(function () { ctrl.abort(); }, 70000);
      var r = await fetch(API + "/tracker/update?limit=2&force=true", { method: "POST", signal: ctrl.signal });
      clearTimeout(bail);
      var txt = await r.text();
      log("  status", r.status + " in " + (Date.now() - t0) + "ms");
      log("  body", txt.slice(0, 500));
      if (r.status === 401) {
        log("  VERDICT", "admin key rejected \u2014 this endpoint should no longer need one, so Render is running an older build");
      } else if (r.status === 409) {
        log("  VERDICT", "a marking pass is already running \u2014 wait for it and re-run");
      } else if (txt.indexOf("remaining") === -1) {
        log("  VERDICT", "no 'remaining' field \u2014 Render is still running the OLD tracker.py, so Refresh prices stops after one batch");
      }
    } catch (e) {
      log("  FAILED after", (Date.now() - t0) + "ms \u2014 " +
          (e && e.name === "AbortError" ? "timed out" : String(e && e.message || e)));
      log("  VERDICT", "the request never completed \u2014 the price feed is hanging on Render");
    }

    var lst = await get("/tracker/list?limit=3");
    log("GET /tracker/list", lst.status + " in " + lst.ms + "ms");
    try {
      var lj = JSON.parse(lst.txt), row = (lj.rows || [])[0] || {};
      log("  first row", JSON.stringify({
        symbol: row.symbol, added_on: row.added_on, added_price: row.added_price,
        last_price: row.last_price, return_pct: row.return_pct,
        updated_on: row.updated_on, mark_error: row.mark_error, source: row.source
      }));
    } catch (e) { log("  parse failed", lst.txt.slice(0, 200)); }

    log("", "\n\u2014 send this whole block as a screenshot or copy-paste \u2014");
    b.disabled = false; b.textContent = "Diagnose";
    await render();
  }

  /* ---- actions --------------------------------------------------------- */

  /* Marking is roughly two seconds per symbol, because the fallback feed is a
     network lookup per name. Asking for forty-two in one request takes over a
     minute, and the browser gives up long before the server finishes — which
     is why the first version of this button appeared to do nothing at all.
     Small batches, looped, with the count on the button so it never looks
     stalled. */
  var BATCH = 6;
  var MAX_ROUNDS = 40;

  /* Nothing on this tab is behind the admin guard any more. /tracker/update
     used to be, which meant Refresh prices opened a password prompt and then
     returned 401 for everyone who had not set ADMIN_KEY on Render — the single
     most common reason this button "did nothing". Marking reads public closes
     and writes the price columns of rows you already own; the server protects
     it with a lock and a batch cap instead, which is the risk actually worth
     protecting against. keyed() is kept for anything that genuinely is
     guarded. */
  function keyed(url, needsKey) {
    if (!needsKey) return url;
    try { if (typeof withKey === "function") return withKey(url); } catch (e) {}
    return url;
  }

  /* A key typed wrong would otherwise be cached for the rest of the session
     and every retry would fail the same way with no explanation. */
  function forgetKey() {
    try { ADMIN_KEY = ""; } catch (e) {}
  }

  async function post(url, ms, needsKey) {
    var ctrl = new AbortController();
    var bail = setTimeout(function () { ctrl.abort(); }, ms || 45000);
    try {
      var r = await fetch(keyed(API + url, needsKey), { method: "POST", signal: ctrl.signal });
      var j = await r.json().catch(function () { return {}; });
      return { ok: r.ok, status: r.status, body: j };
    } finally { clearTimeout(bail); }
  }

  var marking = false;

  async function refresh() {
    if (marking) return;
    marking = true;
    var b = $("tkrefresh");
    b.disabled = true;

    var done = 0, rounds = 0, stop = "", left = null;
    try {
      while (rounds++ < MAX_ROUNDS) {
        b.textContent = (left == null) ? ("Marking\u2026 " + done)
                                       : ("Marking\u2026 " + done + ", " + left + " to go");
        /* force=true is what makes this a refresh rather than a no-op: without
           it the server skips every row it already marked today, so a press
           after the daily cron run returned "updated: 0" and the button
           flashed and did nothing. */
        var res = await post("/tracker/update?force=true&limit=" + BATCH, 60000, false);

        if (!res.ok) {
          if (res.status === 409) {
            stop = "Already refreshing";
          } else if (res.status === 401) {
            forgetKey();
            stop = "Wrong admin key \u2014 try again";
          } else {
            stop = ((res.body && res.body.detail) || "Server refused").slice(0, 38);
          }
          break;
        }
        var j = res.body || {};

        /* A backend older than this build has no "remaining" field and cannot
           say how far there is to go, so one pass is all we can safely do —
           looping would repeat the same batch for ever. This was the bug that
           made the button useless: the field did not exist on ANY build, so
           every press stopped after six rows and reported "old backend". */
        if (j.remaining === undefined) {
          done = j.updated || 0;
          stop = "Update the backend to finish";
          break;
        }

        done = j.marked != null ? j.marked : done + (j.updated || 0);
        left = j.remaining;
        if (!j.remaining) break;
        if (!j.updated) { stop = "stalled at " + j.remaining; break; }
        await render();                       // show progress as it lands
      }
      b.textContent = stop ? stop : "Marked " + done;
      await render();
    } catch (e) {
      b.textContent = (e && e.name === "AbortError")
        ? "Timed out \u2014 press again" : "Engine unreachable";
    }
    marking = false;
    setTimeout(function () { b.disabled = false; b.textContent = "Refresh prices"; }, 3200);
  }

  async function remove(id, el) {
    el.disabled = true;
    el.textContent = "Removing";
    try {
      await post("/tracker/remove?id=" + encodeURIComponent(id), 15000);
      var card = el.closest(".tk");
      if (card) { card.style.transition = "opacity 200ms"; card.style.opacity = "0"; }
      setTimeout(render, 220);
    } catch (e) {
      el.disabled = false; el.textContent = "Remove";
    }
  }

  /* BUGFIX: this listed /tracker/list with no source parameter and then
     filtered the result for source === "auto". The backend defaults that
     endpoint to "manual", so the list it searched could not contain a single
     auto row by construction, and the button answered "Nothing auto-recorded"
     however many there were. It now asks for the auto rows explicitly, and
     deletes them in one server-side call instead of one request per row. */
  async function clearAuto() {
    var b = $("tkclearauto");
    try {
      var d = await (await fetch(API + "/tracker/list?limit=1000&source=auto")).json();
      var auto = d.rows || [];
      var n = d.count != null ? d.count : auto.length;
      if (!n) { b.textContent = "Nothing auto-recorded"; return; }
      if (!window.confirm(
        "Remove " + n + " automatically recorded ideas?\n\n" +
        "Anything you added yourself is kept. This also resets the hit-rate " +
        "statistics, because those are computed from the rows that remain."
      )) return;
      b.disabled = true;
      b.textContent = "Removing " + n + "\u2026";

      var purge = await post("/tracker/purge-auto", 45000);
      if (purge.ok) {
        b.textContent = "Removed " + (((purge.body || {}).removed != null)
          ? purge.body.removed : n);
      } else {
        /* purge-auto is admin-guarded when ADMIN_KEY is set. Fall back to the
           unguarded per-row route rather than leaving the user stuck. */
        for (var i = 0; i < auto.length; i++) {
          b.textContent = "Removing " + (i + 1) + "/" + auto.length;
          await post("/tracker/remove?id=" + encodeURIComponent(auto[i].id), 15000);
        }
        b.textContent = "Removed " + auto.length;
      }
      await render();
    } catch (e) {
      b.textContent = "Couldn't clear";
    }
    setTimeout(function () { b.disabled = false; b.textContent = "Clear auto-recorded"; }, 2600);
  }

  /* ---- one row -----------------------------------------------------------
     The old row printed "Now ₹— Return — Index — Best — Worst — 0 days" as a
     single run-on line of unlabelled values, and on a phone it was the first
     thing to disappear. Every number now sits in a labelled cell, in the order
     the question is actually asked: when did I add it, at what price, what is
     it now, what has it done — then the same against the index, then the plan
     the idea came with and whether the target was reached. */

  function dmy(iso) {
    if (!iso) return "\u2014";
    var p = String(iso).split("-");
    if (p.length !== 3) return esc(iso);
    var M = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return p[2] + " " + (M[Number(p[1]) - 1] || p[1]) + " " + p[0].slice(2);
  }

  function cellHTML(label, value, cls) {
    return '<div class="tkcell"><b>' + label + '</b>' +
           '<span class="' + (cls || "") + '">' + value + '</span></div>';
  }

  /* The plan strip. An idea recorded before the plan was snapshotted says so,
     rather than showing an empty target that reads as "never got there". */
  function planHTML(r) {
    var out = r.outcome || (r.target_price || r.stop_price ? "OPEN" : "NO_PLAN");
    var bits = [];
    if (out === "NO_PLAN") {
      bits.push('<span class="tkout NO_PLAN">No plan recorded</span>');
      bits.push("Added before the entry/stop/target were saved with the idea.");
    } else {
      if (out === "TARGET") {
        bits.push('<span class="tkout TARGET">Target hit</span>');
        if (r.target_hit && r.target_hit.on) bits.push("reached " + dmy(r.target_hit.on));
      } else if (out === "STOP") {
        bits.push('<span class="tkout STOP">Stop hit</span>');
        if (r.stop_hit && r.stop_hit.on) bits.push("broke " + dmy(r.stop_hit.on));
      } else {
        bits.push('<span class="tkout OPEN">Open</span>');
      }
      if (r.target_price) bits.push("Target " + rupee(r.target_price));
      if (r.stop_price) bits.push("Stop " + rupee(r.stop_price));
      if (r.plan_rr) bits.push("R:R 1:" + r.plan_rr);
    }
    return '<div class="tkplan">' + bits.join("<span>\u00B7</span>") + "</div>";
  }

  function card(r, i) {
    var src = (r.source || "auto") === "manual" ? "ADDED BY YOU" : "FROM SCAN";
    var unmarked = r.last_price == null;

    /* Distance still to run to the target, which is the number you actually
       want when deciding whether to keep holding. */
    var toGo = "\u2014";
    if (r.target_price && r.last_price) {
      var g = (r.target_price - r.last_price) / r.last_price * 100;
      toGo = g <= 0 ? "reached" : "+" + g.toFixed(1) + "% to go";
    }

    return '<div class="tk rise" style="--i:' + Math.min(i, 10) + '">' +
      '<button class="tkrm" type="button" data-id="' + esc(r.id) + '">Remove</button>' +
      '<div class="tkt"><span class="tknm">' + esc(r.name || r.symbol) +
        '<span class="tkstat ' + esc(r.status) + '">' + esc(r.status) + '</span>' +
        '<span class="tksrc">' + src + '</span>' +
        '<small>' + esc(r.symbol) + ' \u00B7 ' + esc(r.setup || "\u2014") +
        (r.sector ? ' \u00B7 ' + esc(r.sector) : "") + '</small></span>' +
      '<span class="tkret ' + sign(r.alpha_pct) + '">' + pct(r.alpha_pct) +
        '<small>alpha vs index</small></span></div>' +

      '<div class="tkgrid">' +
        cellHTML("Added on", dmy(r.added_on), "sm") +
        cellHTML("Price at addition", rupee(r.added_price)) +
        cellHTML("Price now", unmarked ? '<span class="dim">not marked</span>' : rupee(r.last_price)) +
        cellHTML("Return", pct(r.return_pct), sign(r.return_pct)) +
      '</div>' +
      '<div class="tkgrid">' +
        cellHTML("Index, same days", pct(r.bench_return_pct), "sm " + sign(r.bench_return_pct)) +
        cellHTML("Best it reached", pct(r.max_gain_pct), "sm " + sign(r.max_gain_pct)) +
        cellHTML("Worst dip", pct(r.max_drawdown_pct), "sm " + sign(r.max_drawdown_pct)) +
        cellHTML("Held", (r.days_held || 0) + (r.days_held === 1 ? " day" : " days"), "sm") +
      '</div>' +
      (r.target_price ? '<div class="tkgrid"><div class="tkcell" style="grid-column:1/-1">' +
         '<b>To target</b><span class="sm">' + toGo + '</span></div></div>' : "") +

      planHTML(r) +
      (r.added_price_source && r.added_price_source !== "scan price"
        ? '<div class="tkplan" style="margin-top:6px">Entry anchored on the ' +
          esc(r.added_price_source) + ' at the moment you added it.</div>' : "") +
      (unmarked ? '<div class="warnbox">No prices yet \u2014 press Refresh prices above.</div>' : "") +
      (r.mark_error ? '<div class="warnbox">Could not price this symbol: ' + esc(r.mark_error) + '</div>' : "") +
      (r.invalidated_by ? '<div class="warnbox">' + esc(r.invalidated_by) + '</div>' : "") +
    '</div>';
  }

  /* ---- render ---------------------------------------------------------- */

  async function render() {
    toolbar();
    var rowsEl = $("tkrows");
    if (!rowsEl) return;
    var csv = $("tkcsv");
    if (csv) csv.href = API + "/tracker/export.csv";

    var status = (typeof tkFilter !== "undefined" && tkFilter) ? tkFilter : "";
    rowsEl.innerHTML = (typeof SKEL === "function") ? SKEL(3) : "Loading\u2026";

    try {
      /* The source is always sent, on BOTH calls. Sending it on the list but
         not on the stats is how the tab ended up showing six of your own rows
         under a headline counting ninety-two ideas, beside a warning about
         twenty-three unpriced rows that were not in the list at all. */
      var src = "&source=" + encodeURIComponent(srcFilter);
      var q = "/tracker/list?status=" + encodeURIComponent(status) + "&limit=400" + src;
      var res = await Promise.all([
        fetch(API + q),
        fetch(API + "/tracker/stats?source=" + encodeURIComponent(srcFilter))
      ]);
      var d = await res[0].json();
      var st = await res[1].json();

      var o = st.overall;
      var stats = $("tkstats");
      if (stats) {
        stats.innerHTML = o ? [
          cell(0, st.total_tracked, "ideas recorded"),
          cell(1, pct(o.avg_alpha_pct), "avg alpha vs index", sign(o.avg_alpha_pct)),
          cell(2, o.beat_index_pct != null ? o.beat_index_pct + "%" : "\u2014", "beat the index"),
          cell(3, pct(o.avg_return_pct), "avg return", sign(o.avg_return_pct)),
          cell(4, pct(o.avg_max_drawdown_pct), "avg worst dip", "neg"),
          cell(5, o.median_days_held, "median days held"),
          (o.target_hit_pct != null
            ? cell(6, o.target_hit_pct + "%", "reached their target (" + o.ideas_with_plan + " with a plan)",
                   o.target_hit_pct >= 50 ? "pos" : "")
            : "")
        ].join("") :
          '<div class="statcell" style="grid-column:1/-1"><b>' + (st.total_tracked || 0) +
          '</b><span>recorded, none marked yet \u2014 press Refresh prices</span></div>';
      }

      /* The honest status line. Previously the tab was silent about the one
         thing that mattered: whether marking had ever run. */
      var flags = [];
      if (st.unmarked) {
        flags.push("<b>" + st.unmarked + " row" + (st.unmarked === 1 ? "" : "s") +
          " in this list " + (st.unmarked === 1 ? "has" : "have") + " no prices yet.</b> " +
          "Press Refresh prices \u2014 it walks the whole list in batches. Marking " +
          "otherwise runs once after 16:00 IST, and only if an external cron is " +
          "calling /cron/tick.");
      }
      if (st.mark_errors) {
        flags.push(st.mark_errors + " row" + (st.mark_errors === 1 ? "" : "s") +
          " could not be priced from either feed \u2014 usually a delisted or renamed symbol.");
      }
      if (st.autotrack === false) {
        flags.push("Automatic recording is off. Only names you press Add on are tracked.");
      } else if (st.autotrack === true) {
        flags.push("Every scan records its ideas automatically, so this list grows on its own. " +
          "Set AUTOTRACK=0 on Render to record only what you add by hand.");
      }
      if (st.storage_is_ephemeral) {
        flags.push("<b>DATA_DIR is not set to a Render disk</b>, so this record is wiped on every deploy.");
      }
      if (st.last_marked_at) {
        flags.push("Prices last marked " + esc(String(st.last_marked_at).replace("T", " ")) + ".");
      }
      var note = $("tknote");
      if (note) {
        note.innerHTML = flags.map(function (f) { return '<div class="tkflag">' + f + "</div>"; }).join("") +
          "<div>" + esc(st.note || "") + "</div>";
      }

      if (!d.rows || !d.rows.length) {
        rowsEl.innerHTML = '<div class="ideas-note" style="padding:14px 0">' +
          (srcFilter === "manual"
            ? "You have not added anything by hand yet. Open the Ideas tab and press <b>Track</b> on a name, or analyse a stock and add it from there."
            : "Nothing recorded yet. Run a universe scan, or press <b>Record current ideas</b> above.") +
          "</div>";
        return;
      }

      rowsEl.innerHTML = d.rows.map(function (r, i) {
        return card(r, i);
      }).join("");

      rowsEl.querySelectorAll(".tkrm").forEach(function (b) {
        b.addEventListener("click", function () { remove(b.dataset.id, b); });
      });
    } catch (e) {
      rowsEl.innerHTML = '<div class="ideas-note" style="padding:14px 0">Engine unreachable \u2014 it may be waking from sleep. Try again in about 30 seconds.</div>';
    }
  }

  function cell(i, val, label, cls) {
    return '<div class="statcell rise" style="--i:' + i + '"><b class="' + (cls || "") + '">' +
           val + "</b><span>" + label + "</span></div>";
  }

  /* Replace the page's own function. It is a top-level declaration, so it is a
     writable property of window and every existing caller — switchTab, the
     filter buttons, the backfill button — picks this up with no other edit. */
  window.loadTracker = render;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", toolbar);
  else toolbar();
})();
