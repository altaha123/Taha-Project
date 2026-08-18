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

  var srcFilter = "";        // "" = everything, "manual" = only what you added

  /* ---- styles, on the existing tokens ---------------------------------- */

  var css = document.createElement("style");
  css.textContent = [
    ".tk{position:relative}",
    ".tkrm{position:absolute;top:10px;right:10px;border:1px solid var(--rule);",
    "  background:var(--paper);color:var(--mute);border-radius:999px;cursor:pointer;",
    "  font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;",
    "  padding:4px 10px;transition:border-color 150ms,color 150ms,background 150ms}",
    ".tkrm:hover{border-color:var(--fail);color:var(--fail)}",
    ".tkrm[disabled]{opacity:.5;cursor:default}",
    ".tk .tkt{padding-right:86px}",
    ".tkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}",
    ".tkflag{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--mute);",
    "  border-left:2px solid var(--gold);padding:2px 0 2px 10px;margin:0 0 12px;line-height:1.7}",
    ".tksrc{font-family:var(--mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;",
    "  color:var(--mute);border:1px solid var(--rule-2);border-radius:999px;padding:2px 7px;margin-left:8px}",
    "@media(max-width:560px){.tk .tkt{padding-right:0}.tkrm{position:static;margin-top:10px;display:inline-block}}"
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
      '<button class="act" id="tkmine" type="button">My picks only</button>' +
      '<button class="act" id="tkclearauto" type="button">Clear auto-recorded</button>' +
      '<button class="act" id="tkdiag" type="button">Diagnose</button>';
    var anchor = $("tkstats");
    host.insertBefore(bar, anchor);

    $("tkrefresh").addEventListener("click", refresh);
    $("tkmine").addEventListener("click", function () {
      srcFilter = srcFilter === "manual" ? "" : "manual";
      this.classList.toggle("solid", srcFilter === "manual");
      this.textContent = srcFilter === "manual" ? "Showing my picks" : "My picks only";
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
      var r = await fetch(API + "/tracker/update?limit=2", { method: "POST", signal: ctrl.signal });
      clearTimeout(bail);
      var txt = await r.text();
      log("  status", r.status + " in " + (Date.now() - t0) + "ms");
      log("  body", txt.slice(0, 500));
      if (r.status === 401 || r.status === 503) {
        log("  VERDICT", "the admin guard is closed \u2014 ADMIN_KEY is set on Render");
      } else if (txt.indexOf("remaining") === -1) {
        log("  VERDICT", "no 'remaining' field \u2014 Render is still running the OLD tracker.py");
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

  async function post(url, ms) {
    var ctrl = new AbortController();
    var bail = setTimeout(function () { ctrl.abort(); }, ms || 45000);
    try {
      var r = await fetch(API + url, { method: "POST", signal: ctrl.signal });
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

    var done = 0, rounds = 0, stop = "";
    try {
      while (rounds++ < MAX_ROUNDS) {
        b.textContent = "Marking\u2026 " + done;
        var res = await post("/tracker/update?limit=" + BATCH);

        if (!res.ok) {
          stop = res.status === 401 || res.status === 503
            ? "Needs admin key"
            : ((res.body && res.body.detail) || "Server refused").slice(0, 38);
          break;
        }
        var j = res.body || {};

        /* An older backend has no "remaining" field. Falling back to a single
           pass there is correct: it means tracker.py was not updated, and
           looping would just repeat the same batch for ever. */
        if (j.remaining === undefined) { done = j.updated || 0; stop = "old backend"; break; }

        done = j.marked != null ? j.marked : done + (j.updated || 0);
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

  async function clearAuto() {
    var b = $("tkclearauto");
    try {
      var d = await (await fetch(API + "/tracker/list?limit=1000")).json();
      var auto = (d.rows || []).filter(function (r) { return (r.source || "auto") === "auto"; });
      if (!auto.length) { b.textContent = "Nothing auto-recorded"; return; }
      if (!window.confirm(
        "Remove " + auto.length + " automatically recorded ideas?\n\n" +
        "Anything you added yourself is kept. This also resets the hit-rate " +
        "statistics, because those are computed from the rows that remain."
      )) return;
      b.disabled = true;
      for (var i = 0; i < auto.length; i++) {
        b.textContent = "Removing " + (i + 1) + "/" + auto.length;
        await post("/tracker/remove?id=" + encodeURIComponent(auto[i].id), 15000);
      }
      b.textContent = "Removed " + auto.length;
      await render();
    } catch (e) {
      b.textContent = "Couldn't clear";
    }
    setTimeout(function () { b.disabled = false; b.textContent = "Clear auto-recorded"; }, 2600);
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
      var q = "/tracker/list?status=" + encodeURIComponent(status) + "&limit=400" +
              (srcFilter ? "&source=" + srcFilter : "");
      var res = await Promise.all([
        fetch(API + q),
        fetch(API + "/tracker/stats")
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
          cell(5, o.median_days_held, "median days held")
        ].join("") :
          '<div class="statcell" style="grid-column:1/-1"><b>' + (st.total_tracked || 0) +
          '</b><span>recorded, none marked yet \u2014 press Refresh prices</span></div>';
      }

      /* The honest status line. Previously the tab was silent about the one
         thing that mattered: whether marking had ever run. */
      var flags = [];
      if (st.unmarked) {
        flags.push("<b>" + st.unmarked + " row" + (st.unmarked === 1 ? "" : "s") +
          " have no prices yet.</b> Press Refresh prices. Marking otherwise only " +
          "runs after 16:00 IST, and only if an external cron is calling /cron/tick.");
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
        var src = (r.source || "auto") === "manual" ? "ADDED BY YOU" : "FROM SCAN";
        return '<div class="tk rise" style="--i:' + Math.min(i, 10) + '">' +
          '<button class="tkrm" type="button" data-id="' + esc(r.id) + '">Remove</button>' +
          '<div class="tkt"><span class="tknm">' + esc(r.name || r.symbol) +
            '<span class="tkstat ' + esc(r.status) + '">' + esc(r.status) + '</span>' +
            '<span class="tksrc">' + src + '</span>' +
            '<small>' + esc(r.symbol) + ' \u00B7 ' + esc(r.setup || "\u2014") +
            ' \u00B7 added ' + esc(r.added_on) + ' at ' + rupee(r.added_price) + '</small></span>' +
          '<span class="tkret ' + sign(r.alpha_pct) + '">' + pct(r.alpha_pct) + '<small>alpha</small></span></div>' +
          '<div class="tkln">' +
            '<span>Now ' + rupee(r.last_price) + '</span>' +
            '<span class="' + sign(r.return_pct) + '">Return ' + pct(r.return_pct) + '</span>' +
            '<span>Index ' + pct(r.bench_return_pct) + '</span>' +
            '<span>Best ' + pct(r.max_gain_pct) + '</span>' +
            '<span>Worst ' + pct(r.max_drawdown_pct) + '</span>' +
            '<span>' + (r.days_held || 0) + ' days</span>' +
            (r.sector ? '<span>' + esc(r.sector) + '</span>' : "") +
          '</div>' +
          (r.mark_error ? '<div class="warnbox">Could not price this symbol: ' + esc(r.mark_error) + '</div>' : "") +
          (r.invalidated_by ? '<div class="warnbox">' + esc(r.invalidated_by) + '</div>' : "") +
        '</div>';
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
