/* ============================================================================
   Altaha — Motion layer

   Companion to motion.css. Three behaviours, all of which need JavaScript
   because CSS cannot see either the viewport or the value of a number:

     1. SCROLL REVEAL   cards animate as they reach the viewport, not when
                        they happen to be rendered
     2. COUNT-UP        scores, returns and prices climb to their value, so a
                        computed figure looks computed
     3. BAR FILL        the Ideas evidence bars run out from zero

   Written to survive the way this site actually renders. The Ideas and
   Tracker tabs rebuild their whole list on every filter change, so nothing
   here can be a one-shot pass at DOMContentLoaded — a MutationObserver picks
   up new rows and the observers are idempotent per element.

   It is entirely opt-out: if the reader has asked for reduced motion the file
   returns immediately and every element keeps its final value. Nothing here
   changes what any number says, only how it arrives — a count-up that ended
   on the wrong figure would be a far worse bug than no animation at all, so
   the final frame always writes back the exact original text.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_MOTION__) return;
  window.__ALTAHA_MOTION__ = 1;

  var reduce = false;
  try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}
  if (reduce || !("IntersectionObserver" in window)) return;

  /* ---- 1. scroll reveal ------------------------------------------------- */

  var REVEAL = ".idea, .tk, .statcell, .alertcard, .mktctx, .fitem, .vcard, .lrow";
  var seen = "__moSeen";

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add("mo-in");
      countInside(e.target);
      fillBars(e.target);
      io.unobserve(e.target);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });

  function watch(root) {
    var list = (root || document).querySelectorAll(REVEAL);
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el[seen]) continue;
      el[seen] = 1;
      el.classList.add("mo-reveal");
      io.observe(el);
    }
  }

  /* The one outcome this file must never produce is invisible content.
     .mo-reveal starts at opacity 0, so anything the observer fails to fire
     for — an element that mounted inside a display:none tab, a browser quirk,
     a callback that never ran — would stay blank for good.

     It only rescues elements actually IN the viewport. Rescuing everything
     with a height would defeat the point, since a long list is legitimately
     hidden below the fold waiting to be scrolled to. And it runs on its own
     interval rather than a timer reset by watch(), because the count-up
     rewrites text nodes, which trips the MutationObserver, which called
     watch() — a timer restarted there would have been pushed back for ever
     by the very animation it was meant to backstop. */
  function rescueVisible() {
    var stuck = document.querySelectorAll(".mo-reveal:not(.mo-in)");
    var h = window.innerHeight || 800;
    for (var i = 0; i < stuck.length; i++) {
      var el = stuck[i], r = el.getBoundingClientRect();
      if (r.height > 0 && r.top < h && r.bottom > 0) {
        el.classList.add("mo-in");
        countInside(el);
        fillBars(el);
        io.unobserve(el);
      }
    }
  }
  setInterval(rescueVisible, 1200);

  /* ---- 2. count-up ------------------------------------------------------
     Only ever touches a text node that is entirely a number, with an optional
     prefix (₹, +, −) and suffix (%, /100). Anything else — an em dash, a
     symbol, a sentence — is left exactly as it is. */

  var NUM = /^([^\d\-+.]*)([+\-−]?[\d,]*\.?\d+)(.*)$/;
  var counted = "__moCounted";

  function firstTextNode(el) {
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && n.nodeValue.trim()) return n;
    }
    return null;
  }

  function countInside(root) {
    var els = root.querySelectorAll(".statcell b, .conv, .fit, .tkret, .tkcell span, .nm .fit");
    for (var i = 0; i < els.length; i++) countUp(els[i]);
    if (root.matches && root.matches(".statcell, .conv")) countUp(root);
  }

  function countUp(el) {
    if (!el || el[counted]) return;
    var node = firstTextNode(el);
    if (!node) return;
    var raw = node.nodeValue.trim();
    var m = raw.match(NUM);
    if (!m) return;                                   // "—", "not marked", text
    /* A suffix containing a word means this is not a quantity: "30 Aug 26" is
       a date and "3 days" is a duration, and watching either tick up from
       zero is merely odd. Symbols are fine — "%", "/100", "cr/day". */
    if (/[A-Za-z]{2,}/.test(m[3])) return;
    var target = parseFloat(m[2].replace(/,/g, "").replace("−", "-"));
    if (!isFinite(target) || Math.abs(target) < 0.005) return;

    el[counted] = 1;
    el.classList.add("mo-num");
    var dp = (m[2].split(".")[1] || "").length;
    var grouped = m[2].indexOf(",") !== -1;
    var pre = m[1], post = m[3];
    var sign = /^[+]/.test(m[2]) ? "+" : "";
    var dur = 760, t0 = 0;

    function frame(t) {
      if (!t0) t0 = t;
      var p = Math.min(1, (t - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);            // easeOutCubic
      if (p < 1) {
        var v = target * eased;
        var txt = grouped ? Math.abs(v).toLocaleString("en-IN", {
                              minimumFractionDigits: dp, maximumFractionDigits: dp })
                          : Math.abs(v).toFixed(dp);
        node.nodeValue = pre + sign + (target < 0 ? "-" : "") + txt + post;
        requestAnimationFrame(frame);
      } else {
        node.nodeValue = raw;                        // exact original, always
      }
    }
    node.nodeValue = pre + sign + (target < 0 ? "-" : "") + (0).toFixed(dp) + post;
    requestAnimationFrame(frame);
  }

  /* ---- 3. evidence bars ------------------------------------------------- */

  function fillBars(root) {
    var bars = root.querySelectorAll(".evbar > i");
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      if (b[counted]) continue;
      /* The ledger is display:none until it is opened, so a bar filled while
         it was still closed would play its whole animation unseen and be at
         full width by the time anyone looked. Skip anything not laid out; the
         click handler below fills it when the panel actually opens. */
      if (!b.offsetParent) continue;
      b[counted] = 1;
      var w = b.style.width;
      b.style.width = "0%";
      (function (el, target) {
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { el.style.width = target; });
        });
      })(b, w);
    }
  }

  /* The ledger opens on a click, long after its row was revealed, so bars
     inside it are filled when the panel is actually shown. */
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest(".evbtn");
    if (!btn) return;
    setTimeout(function () {
      var wrap = btn.parentElement && btn.parentElement.querySelector(".evwrap.open");
      if (wrap) fillBars(wrap);
    }, 30);
  }, true);

  /* ---- keeping up with re-renders --------------------------------------- */

  var pending = null;
  var mo = new MutationObserver(function () {
    if (pending) return;
    pending = setTimeout(function () { pending = null; watch(document); }, 90);
  });

  function start() {
    watch(document);
    mo.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
