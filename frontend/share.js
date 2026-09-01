/* ============================================================================
   Altaha — sharing anything on the site

   Every card the site draws can be published: a scorecard, a chart with the
   shape drawn on it, an idea with its conviction ledger, a tracked position
   marked to market, the track record. Winners and losers render identically
   and neither is easier to post than the other, which is the only reason
   posting the winners is honest.

   THREE WAYS OUT, AND WHY THERE ARE THREE
   A link is not enough. X unfurls a link into a card because Twitterbot
   fetches the page and reads its meta tags; WhatsApp's preview is best-effort
   and frequently just doesn't appear for a domain it has never seen, so a
   WhatsApp share that hands over only a URL arrives as a bare blue link. So:

     · Post on X       — link + text. X does the unfurling.
     · Share…          — navigator.share() with the PNG attached, where the
                         browser supports files (every current mobile browser).
                         This opens the OS share sheet, and the image itself
                         travels into WhatsApp, Instagram, Signal, anywhere.
     · Download card   — the image on disk, to attach by hand. The one route
                         that works in every browser ever written, including
                         the in-app ones that block both of the above.

   WHERE THE LINK POINTS
   At the site's own domain, never at the API's hosting provider. vercel.json
   proxies /share/* and /og/* through to the backend so both hosts serve the
   same documents; this file asks the site first and falls back to the API only
   if that request fails, which covers the window between the two deploys.

   WHAT MAY GO OUT
   Scores, archetypes, historical prices, realised returns. No entry, no stop,
   no target, no "buy". Those live on the site beside their own ledger and
   disclaimer; on a public post they would be a recommendation rather than
   analysis, which in India is the line between an educational tool and one
   that needs SEBI Research Analyst registration. The line is drawn here in
   code rather than left to whoever is composing the post that morning.
   ========================================================================== */

(function () {
  "use strict";
  if (window.__ALTAHA_SHARE__) return;
  window.__ALTAHA_SHARE__ = 1;

  var API = (typeof API_BASE !== "undefined" && API_BASE) ? API_BASE
          : (window.API_BASE || "https://taha-project.onrender.com");

  /* The host that appears in public. The site's own origin when the page is
     actually being served from one; the configured site otherwise, so a card
     opened from a file:// copy still produces a link somebody can click. */
  var SITE = (function () {
    var configured = (window.SITE_URL || "").replace(/\/+$/, "");
    if (configured) return configured;
    var o = (window.location && window.location.origin) || "";
    if (/^https?:/.test(o) && !/localhost|127\.0\.0\.1|0\.0\.0\.0/.test(o)) return o;
    return "https://taha-project-one.vercel.app";
  })();

  var $ = function (id) { return document.getElementById(id); };

  function clean(sym) {
    return String(sym || "").toUpperCase().replace(".NS", "").replace(".BO", "")
      .replace(/[^A-Z0-9&.\-]/g, "");
  }

  function num(v) {
    if (v && typeof v === "object") v = v.score;
    var f = Number(v);
    return isFinite(f) ? Math.round(f) : null;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function qs(obj) {
    var out = [];
    for (var k in obj) {
      if (!Object.prototype.hasOwnProperty.call(obj, k)) continue;
      if (obj[k] == null || obj[k] === "") continue;
      out.push(encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]));
    }
    return out.length ? "?" + out.join("&") : "";
  }

  /* ---- what each kind of card is ---------------------------------------
     One table rather than five branches scattered through the file. Adding a
     card is adding a row: the image path, the crawler page, the post text and
     the filename all come from here. */

  var KINDS = {
    stock: {
      png: function (d) { return "/og/stock.png" + qs({ ticker: clean(d.ticker || d.symbol) }); },
      page: function (d) { return "/share/" + encodeURIComponent(clean(d.ticker || d.symbol)); },
      file: function (d) { return "altaha-" + clean(d.ticker || d.symbol).toLowerCase() + "-scorecard.png"; },
      title: function (d) { return clean(d.ticker || d.symbol) + " — scorecard"; },
      text: function (d) {
        var scoring = d.scoring || d.verdict || {};
        var comp = num(scoring.score !== undefined ? scoring.score : d.composite);
        var label = (scoring.label || "").toLowerCase();
        var tech = num(d.technical), fund = num(d.fundamental);
        var fsc = (d.fundamental && d.fundamental.f_score != null) ? d.fundamental.f_score : null;
        var setup = d.setup && d.setup.name ? d.setup.name : d.setup;
        var lines = [clean(d.ticker || d.symbol) + " — " + (comp == null ? "—" : comp) + "/100"
                     + (label ? " (" + label + ")" : "") + " on the Altaha Screener."];
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
    },

    chart: {
      png: function (d) {
        return "/og/chart.png" + qs({ ticker: clean(d.ticker || d.symbol), range: d.range || "1D" });
      },
      page: function (d) {
        return "/share/chart/" + encodeURIComponent(clean(d.ticker || d.symbol))
             + qs({ range: d.range || "1D" });
      },
      file: function (d) {
        return "altaha-" + clean(d.ticker || d.symbol).toLowerCase() + "-"
             + String(d.range || "1D").toLowerCase() + "-chart.png";
      },
      title: function (d) { return clean(d.ticker || d.symbol) + " — " + (d.range || "1D") + " chart"; },
      text: function (d) {
        var sym = clean(d.ticker || d.symbol);
        var p = d.pattern || null;
        var lines = [sym + " on the " + (d.range || "1D") + " chart."];
        if (p && p.name) {
          lines.push(p.name + " — " + (p.status || "forming")
                     + (p.confidence != null ? ", " + p.confidence + " shape match" : "") + ".");
          lines.push("The checks behind that reading, and how the same shape resolved "
                     + "here before, are published beside it.");
        } else {
          lines.push("No textbook pattern right now — which is the usual answer, and a "
                     + "detector that always finds one has stopped detecting.");
        }
        return lines.join("\n");
      }
    },

    idea: {
      png: function (d) {
        return "/og/idea.png" + qs({ ticker: clean(d.ticker || d.symbol), horizon: d.horizon_key || "short" });
      },
      page: function (d) {
        return "/share/idea/" + encodeURIComponent(clean(d.ticker || d.symbol))
             + qs({ horizon: d.horizon_key || "short" });
      },
      file: function (d) { return "altaha-" + clean(d.ticker || d.symbol).toLowerCase() + "-idea.png"; },
      title: function (d) { return clean(d.ticker || d.symbol) + " — conviction"; },
      text: function (d) {
        var conv = num(d.conviction);
        var lines = [clean(d.ticker || d.symbol) + " — " + (conv == null ? "—" : conv)
                     + "/100 conviction"
                     + (d.conviction_band ? " (" + String(d.conviction_band).toLowerCase() + ")" : "")
                     + " on the Altaha Screener."];
        if (d.setup) lines.push(d.setup + (d.horizon ? " · typical hold " + d.horizon : ""));
        lines.push("");
        lines.push("The seven weighted inputs that add up to that number are published "
                   + "next to it.");
        return lines.join("\n");
      }
    },

    holding: {
      png: function (d) { return "/og/holding.png" + qs({ ticker: clean(d.ticker || d.symbol) }); },
      page: function (d) { return "/share/holding/" + encodeURIComponent(clean(d.ticker || d.symbol)); },
      file: function (d) { return "altaha-" + clean(d.ticker || d.symbol).toLowerCase() + "-tracked.png"; },
      title: function (d) { return clean(d.ticker || d.symbol) + " — tracked"; },
      text: function (d) {
        function p(v) {
          return v == null ? "—" : (Number(v) > 0 ? "+" : "") + Number(v).toFixed(2) + "%";
        }
        var lines = [clean(d.ticker || d.symbol) + " — " + p(d.return_pct)
                     + " since the idea was recorded"
                     + (d.added_on ? " on " + d.added_on : "") + "."];
        lines.push("Index did " + p(d.bench_return_pct) + " over the same window · alpha "
                   + p(d.alpha_pct));
        lines.push("");
        lines.push("Logged in advance and marked automatically — losers included.");
        return lines.join("\n");
      }
    },

    record: {
      png: function () { return "/og/record.png"; },
      page: function () { return "/share/record"; },
      file: function () { return "altaha-track-record.png"; },
      title: function () { return "Altaha — track record"; },
      text: function (d) {
        var o = d.overall || d || {};
        var lines = ["Does the Altaha engine work? Here is the ledger."];
        var bits = [];
        if (d.total_tracked != null) bits.push(d.total_tracked + " ideas recorded");
        if (o.beat_index_pct != null) bits.push(o.beat_index_pct + "% beat the index");
        if (o.avg_alpha_pct != null) {
          bits.push("avg alpha " + (o.avg_alpha_pct > 0 ? "+" : "")
                    + Number(o.avg_alpha_pct).toFixed(2) + "%");
        }
        if (bits.length) lines.push(bits.join(" · "));
        lines.push("");
        lines.push("Every idea is logged the day it is generated. Winners and losers.");
        return lines.join("\n");
      }
    }
  };

  function kindOf(d) {
    return KINDS[(d && d.kind) || "stock"] || KINDS.stock;
  }

  /* ---- URLs -------------------------------------------------------------
     Two candidates for the image, in order. The site's own domain is the one
     that should be used and the one that appears in a link; the API host is
     the fallback for the window in which the backend has shipped and the
     rewrite has not. Nothing about the fallback is visible to a reader — it
     is only ever used to fetch bytes, never handed out. */

  function cardCandidates(d) {
    var path = kindOf(d).png(d);
    return [SITE + path, API + path];
  }

  function link(d) {
    return SITE + kindOf(d).page(d);
  }

  function compose(d) {
    return kindOf(d).text(d || {});
  }

  /* ---- the sheet -------------------------------------------------------- */

  var sheet = null;
  var current = null;
  var currentBlob = null;

  function build() {
    if (sheet) return sheet;
    sheet = document.createElement("div");
    sheet.className = "shsheet";
    sheet.id = "shsheet";
    sheet.hidden = true;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", "Share this card");
    sheet.innerHTML =
      '<div class="shback" data-shut="1"></div>' +
      '<div class="shbox">' +
        '<button class="shx" type="button" data-shut="1" aria-label="Close">&times;</button>' +
        '<h4 class="shttl" id="shttl">Share</h4>' +
        '<p class="shsub" id="shsub"></p>' +
        '<div class="shcardwrap"><div class="shspin" id="shspin">Rendering the card…</div>' +
          '<img class="shcard" id="shcardimg" alt="" hidden></div>' +
        '<div class="shbtns">' +
          '<button class="sharebtn x" type="button" data-do="x">Post on X</button>' +
          '<button class="sharebtn" type="button" data-do="native" hidden>Share…</button>' +
          '<button class="sharebtn" type="button" data-do="wa">WhatsApp</button>' +
          '<button class="sharebtn" type="button" data-do="dl">Download card</button>' +
          '<button class="sharebtn" type="button" data-do="copy">Copy link</button>' +
        '</div>' +
        '<p class="shnote" id="shnote"></p>' +
      '</div>';
    document.body.appendChild(sheet);

    sheet.addEventListener("click", function (ev) {
      if (ev.target.getAttribute && ev.target.getAttribute("data-shut")) { close(); return; }
      var btn = ev.target.closest ? ev.target.closest("[data-do]") : null;
      if (!btn) return;
      var act = btn.getAttribute("data-do");
      if (act === "x") onX();
      else if (act === "wa") onWhatsApp();
      else if (act === "dl") onDownload(btn);
      else if (act === "copy") onCopy(btn);
      else if (act === "native") onNative(btn);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && sheet && !sheet.hidden) close();
    });
    return sheet;
  }

  function close() {
    if (!sheet) return;
    sheet.hidden = true;
    document.body.classList.remove("sh-open");
  }

  function flash(btn, text) {
    if (!btn) return;
    var was = btn.textContent;
    btn.textContent = text;
    btn.classList.add("done");
    setTimeout(function () { btn.textContent = was; btn.classList.remove("done"); }, 2200);
  }

  function note(msg) {
    var n = $("shnote");
    if (n) n.textContent = msg || "";
  }

  /* Fetch the PNG once, and keep it. Both "Share…" and "Download card" need
     the bytes, and a card takes a moment to render server-side — asking twice
     would make the second button feel broken. Falls through the candidate
     hosts in order and gives up quietly: the link buttons must keep working
     even when the image cannot be fetched. */
  function fetchCard(d) {
    var urls = cardCandidates(d);
    var i = 0;
    return new Promise(function (resolve, reject) {
      (function attempt() {
        if (i >= urls.length) { reject(new Error("card unavailable")); return; }
        var url = urls[i++];
        fetch(url, { mode: "cors", credentials: "omit" })
          .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.blob();
          })
          .then(function (b) {
            if (!b || !b.size) throw new Error("empty");
            resolve({ blob: b, url: url });
          })
          .catch(attempt);
      })();
    });
  }

  function canShareFiles() {
    try {
      return !!(navigator.canShare && navigator.share &&
                navigator.canShare({ files: [new File([new Blob(["x"])], "x.png", { type: "image/png" })] }));
    } catch (e) { return false; }
  }

  function onX() {
    if (!current) return;
    /* x.com/intent/post is the current form; twitter.com/intent/tweet still
       redirects to it, so either works and this is the one that will not need
       changing again. */
    var url = "https://x.com/intent/post?text=" + encodeURIComponent(compose(current))
            + "&url=" + encodeURIComponent(link(current));
    window.open(url, "_blank", "noopener,width=600,height=680");
    note("X unfurls the link into the card above. Give it a second to fetch.");
  }

  function onWhatsApp() {
    if (!current) return;
    var text = compose(current) + "\n" + link(current);
    window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank", "noopener");
    note("WhatsApp previews links unreliably. For the picture itself, use " +
         (canShareFiles() ? "Share…" : "Download card") + " and attach it.");
  }

  function onNative(btn) {
    if (!current || !navigator.share) return;
    var d = current;
    var payload = { title: kindOf(d).title(d), text: compose(d), url: link(d) };
    var go = function (files) {
      var data = files ? { files: files, title: payload.title, text: payload.text } : payload;
      navigator.share(data).catch(function () { /* the user dismissed the sheet */ });
    };
    if (currentBlob && canShareFiles()) {
      try {
        go([new File([currentBlob], kindOf(d).file(d), { type: "image/png" })]);
        return;
      } catch (e) { /* fall through to the link-only share */ }
    }
    flash(btn, "Preparing…");
    fetchCard(d).then(function (res) {
      currentBlob = res.blob;
      try { go([new File([res.blob], kindOf(d).file(d), { type: "image/png" })]); }
      catch (e) { go(null); }
    }).catch(function () { go(null); });
  }

  function saveBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function onDownload(btn) {
    if (!current) return;
    var d = current;
    var name = kindOf(d).file(d);
    if (currentBlob) { saveBlob(currentBlob, name); flash(btn, "Saved"); return; }
    flash(btn, "Rendering…");
    fetchCard(d).then(function (res) {
      currentBlob = res.blob;
      saveBlob(res.blob, name);
      flash(btn, "Saved");
    }).catch(function () {
      /* Some in-app browsers block both fetch and programmatic downloads.
         Opening the image directly still lets a long-press save it. */
      window.open(cardCandidates(d)[0], "_blank", "noopener");
      flash(btn, "Opened — long-press to save");
    });
  }

  function onCopy(btn) {
    if (!current) return;
    var url = link(current);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () { flash(btn, "Copied"); })
        .catch(function () { fallbackCopy(url, btn); });
    } else {
      fallbackCopy(url, btn);
    }
  }

  function fallbackCopy(url, btn) {
    /* Clipboard access needs a secure context and a user gesture, and is
       refused outright in some in-app browsers. Select the text instead so a
       long-press still works. */
    var box = document.createElement("input");
    box.value = url;
    box.setAttribute("readonly", "");
    box.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(box);
    box.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(box);
    flash(btn, ok ? "Copied" : "Press and hold to copy");
  }

  /* ---- opening it ------------------------------------------------------- */

  var SUBS = {
    stock: "The scorecard, as a picture. Post the link and X draws the card; " +
           "attach the file anywhere else.",
    chart: "The candles with the shape drawn on them. The trigger and the " +
           "measured move stay on the site, beside the base rate that qualifies them.",
    idea: "The conviction number and the seven weighted inputs that add up to it.",
    holding: "Marked to market against the index over the identical window.",
    record: "The whole ledger — every idea logged the day it was generated."
  };

  function open(d) {
    if (!d) return;
    build();
    current = d;
    currentBlob = null;

    var k = kindOf(d);
    $("shttl").textContent = k.title(d);
    $("shsub").textContent = SUBS[d.kind || "stock"] || "";
    note("");

    var img = $("shcardimg"), spin = $("shspin");
    var urls = cardCandidates(d);
    var tried = 0;
    img.hidden = true;
    if (spin) { spin.hidden = false; spin.textContent = "Rendering the card…"; }
    img.alt = k.title(d) + " share card";
    img.onload = function () { img.hidden = false; if (spin) spin.hidden = true; };
    img.onerror = function () {
      tried += 1;
      if (tried < urls.length) { img.src = urls[tried]; return; }
      img.hidden = true;
      if (spin) {
        spin.hidden = false;
        spin.textContent = "The card could not be rendered — the engine may be waking up. " +
                           "The link still works.";
      }
    };
    img.src = urls[0];

    var nat = sheet.querySelector('[data-do="native"]');
    if (nat) nat.hidden = !(navigator.share);

    sheet.hidden = false;
    document.body.classList.add("sh-open");

    /* Warm the blob so Share… and Download are instant when they are pressed.
       Failure here is silent by design — the buttons handle it themselves. */
    fetchCard(d).then(function (res) { currentBlob = res.blob; }).catch(function () {});
  }

  /* ---- the button that appears on every card ----------------------------
     One delegated listener rather than a listener per row: the ideas list and
     the tracker redraw themselves wholesale on every refresh, and per-row
     wiring is exactly the kind of thing that survives the first render and
     quietly stops working after the second. */

  function payloadFrom(el) {
    var raw = el.getAttribute("data-share");
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-share]") : null;
    if (!el) return;
    var d = payloadFrom(el);
    if (!d) return;
    ev.preventDefault();
    ev.stopPropagation();
    open(d);
  }, true);

  /* ---- the analysis page's own row (kept, and now opens the sheet) ------ */

  function show(d) {
    var row = $("sharerow");
    if (!row || !d) return;
    row.hidden = false;
    row.__payload = Object.assign({ kind: "stock" }, d);

    var img = $("sharecard");
    if (img) {
      var urls = cardCandidates(row.__payload);
      var tried = 0;
      img.hidden = true;
      img.onload = function () { img.hidden = false; };
      img.onerror = function () {
        tried += 1;
        if (tried < urls.length) { img.src = urls[tried]; return; }
        img.hidden = true;
      };
      img.alt = "Share card for " + clean(d.ticker || d.symbol);
      img.src = urls[0];
    }
  }

  function wire() {
    var row = $("sharerow");
    var openBtn = $("shareopen");
    if (openBtn && !openBtn.dataset.wired) {
      openBtn.dataset.wired = "1";
      openBtn.addEventListener("click", function () {
        if (row && row.__payload) open(row.__payload);
      });
    }
    var pairs = [["sharex", onX], ["sharewa", onWhatsApp]];
    pairs.forEach(function (p) {
      var b = $(p[0]);
      if (!b || b.dataset.wired) return;
      b.dataset.wired = "1";
      b.addEventListener("click", function () {
        if (row && row.__payload) { current = row.__payload; }
        p[1]();
      });
    });
    var cp = $("sharecopy");
    if (cp && !cp.dataset.wired) {
      cp.dataset.wired = "1";
      cp.addEventListener("click", function () {
        if (row && row.__payload) current = row.__payload;
        onCopy(cp);
      });
    }
    var dl = $("sharedl");
    if (dl && !dl.dataset.wired) {
      dl.dataset.wired = "1";
      dl.addEventListener("click", function () {
        if (row && row.__payload) { current = row.__payload; currentBlob = null; }
        onDownload(dl);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
  setTimeout(wire, 800);

  window.AltahaShare = {
    show: show, open: open, compose: compose, link: link,
    card: function (d) { return cardCandidates(d)[0]; },
    close: close
  };
})();
