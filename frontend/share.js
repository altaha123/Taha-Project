/* ============================================================================
   Altaha — sharing an analysis

   Turns a finished analysis into a post. The link handed out is the backend's
   /share/SYMBOL page rather than the app URL, because no social crawler runs
   JavaScript: a crawler fetching the single-page app reads whatever meta tags
   sit in the static file and every stock previews identically. /share renders
   the tags for that one stock and forwards a human to the app.

   WHAT THE POST MAY CONTAIN
   The same rule the card itself follows. Scores, the setup archetype, and the
   line that the arithmetic is on the page. No entry, no stop, no target, no
   "buy" — those exist on the site next to their own ledger, and on a public
   post they would be a recommendation rather than analysis. In India that is
   the line between an educational tool and one that needs SEBI Research
   Analyst registration, so it is drawn here in code and not left to whoever
   is composing the post that morning.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_SHARE__) return;
  window.__ALTAHA_SHARE__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");
  var $ = function (id) { return document.getElementById(id); };

  var current = null;

  function clean(sym) {
    return String(sym || "").toUpperCase().replace(".NS", "").replace(".BO", "")
      .replace(/[^A-Z0-9&.\-]/g, "");
  }

  function num(v) {
    if (v && typeof v === "object") v = v.score;
    var f = Number(v);
    return isFinite(f) ? Math.round(f) : null;
  }

  /* The post body. Deliberately plain: a wall of hashtags reads as promotion,
     and the interesting claim here is that the workings are published. */
  function compose(d) {
    var sym = clean(d.ticker || d.symbol);
    var scoring = d.scoring || d.verdict || {};
    var comp = num(scoring.score !== undefined ? scoring.score : d.composite);
    var label = (scoring.label || "").toLowerCase();
    var tech = num(d.technical);
    var fund = num(d.fundamental);
    var fsc = (d.fundamental && d.fundamental.f_score != null) ? d.fundamental.f_score : null;
    var setup = d.setup && d.setup.name ? d.setup.name : d.setup;

    var lines = [];
    lines.push(sym + " — " + (comp == null ? "—" : comp) + "/100"
               + (label ? " (" + label + ")" : "") + " on the Altaha Screener.");

    var bits = [];
    if (tech != null) bits.push("Technical " + tech);
    if (fund != null) bits.push("Fundamental " + fund);
    if (fsc != null) bits.push("Piotroski " + fsc + "/9");
    if (bits.length) lines.push(bits.join(" · "));
    if (setup) lines.push("Setup: " + setup);

    lines.push("");
    lines.push("Every number opens into the arithmetic behind it.");
    return lines.join("\n");
  }

  function link(d) {
    return API + "/share/" + encodeURIComponent(clean(d.ticker || d.symbol));
  }

  function cardSrc(d) {
    return API + "/og/stock.png?ticker=" + encodeURIComponent(clean(d.ticker || d.symbol));
  }

  function flash(btn, text) {
    var was = btn.textContent;
    btn.textContent = text;
    btn.classList.add("done");
    setTimeout(function () {
      btn.textContent = was;
      btn.classList.remove("done");
    }, 2000);
  }

  function onX() {
    if (!current) return;
    /* x.com/intent/post is the current form; twitter.com/intent/tweet still
       redirects to it, so either works and this is the one that will not need
       changing again. */
    var url = "https://x.com/intent/post?text=" + encodeURIComponent(compose(current))
            + "&url=" + encodeURIComponent(link(current));
    window.open(url, "_blank", "noopener,width=600,height=640");
  }

  function onWhatsApp() {
    if (!current) return;
    var text = compose(current) + "\n" + link(current);
    window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank", "noopener");
  }

  async function onCopy(ev) {
    if (!current) return;
    var btn = ev.currentTarget;
    var url = link(current);
    try {
      await navigator.clipboard.writeText(url);
      flash(btn, "Copied");
    } catch (e) {
      /* Clipboard access needs a secure context and a user gesture, and is
         refused outright in some in-app browsers. Select the text instead so
         a long-press still works. */
      var box = document.createElement("input");
      box.value = url;
      box.setAttribute("readonly", "");
      box.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(box);
      box.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e2) {}
      document.body.removeChild(box);
      flash(btn, ok ? "Copied" : "Press and hold to copy");
    }
  }

  function show(d) {
    var row = $("sharerow");
    if (!row || !d) return;
    current = d;
    row.hidden = false;

    /* Show the actual card, so nobody has to post blind to find out what it
       looks like. It is lazy and failure is silent — a preview that will not
       load must not take the buttons down with it. */
    var img = $("sharecard");
    if (img) {
      img.hidden = true;
      img.onload = function () { img.hidden = false; };
      img.onerror = function () { img.hidden = true; };
      img.alt = "Share card for " + clean(d.ticker || d.symbol);
      img.src = cardSrc(d);
    }
  }

  function wire() {
    var x = $("sharex"), wa = $("sharewa"), cp = $("sharecopy");
    if (x && !x.dataset.wired) { x.dataset.wired = "1"; x.addEventListener("click", onX); }
    if (wa && !wa.dataset.wired) { wa.dataset.wired = "1"; wa.addEventListener("click", onWhatsApp); }
    if (cp && !cp.dataset.wired) { cp.dataset.wired = "1"; cp.addEventListener("click", onCopy); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  window.AltahaShare = { show: show, compose: compose, link: link };
})();
