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

     · X, Telegram,    — link + text. Each network fetches the link's page
       LinkedIn,         and draws its og:image under the post, so the card
       Facebook          reaches the timeline without being uploaded.
     · Share…          — navigator.share() with the PNG attached, where the
                         browser supports files (every current mobile browser).
                         This opens the OS share sheet, and the image itself
                         travels into WhatsApp, Instagram, Signal, anywhere.
     · Copy image      — the PNG on the clipboard, for pasting into X,
                         Telegram or WhatsApp Web on a desktop, where no
                         network's share link can carry a picture.
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
    return "https://altahascreener.in";
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

  /* ---- the marks ---------------------------------------------------------
     Brand marks from Simple Icons (CC0), drawn on a 24-unit square. A bare
     word on a button makes a reader parse four of them to find the one they
     want; the logo is found before it is read. The utility glyphs are
     stroked line icons, so they never compete with a brand. */

  var BRAND = {
    x: "M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z",
    whatsapp: "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z",
    telegram: "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z",
    linkedin: "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z",
    facebook: "M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z"
  };

  var GLYPH = {
    share: "M12 3v12M7.5 7.5 12 3l4.5 4.5M5 12.5V19a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6.5",
    download: "M12 3v12M7.5 10.5 12 15l4.5-4.5M5 20h14",
    image: "M4 4h16v16H4zM4 16l4.5-4.5 3.5 3.5 2.5-2.5L20 18M15.5 8.5h.01",
    copy: "M9 9h11v11H9zM5 15H4V4h11v1",
    link: "M10 13.5a4.5 4.5 0 0 0 6.36.36l3-3a4.5 4.5 0 0 0-6.36-6.36l-1.5 1.5M14 10.5a4.5 4.5 0 0 0-6.36-.36l-3 3a4.5 4.5 0 0 0 6.36 6.36l1.5-1.5"
  };

  function icon(name) {
    if (BRAND[name]) {
      return '<svg class="shico shico-' + name + '" viewBox="0 0 24 24" aria-hidden="true" ' +
             'focusable="false"><path fill="currentColor" d="' + BRAND[name] + '"/></svg>';
    }
    if (GLYPH[name]) {
      return '<svg class="shico shico-line" viewBox="0 0 24 24" aria-hidden="true" ' +
             'focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.9" ' +
             'stroke-linecap="round" stroke-linejoin="round" d="' + GLYPH[name] + '"/></svg>';
    }
    return "";
  }

  /* Where a post goes. Each network's own share address, which takes the link
     (and, where it accepts one, the text) and fetches the card itself. */
  var NETS = {
    x: { label: "X", icon: "x",
         url: function (t, u) {
           /* x.com/intent/post is the current form; twitter.com/intent/tweet
              still redirects to it, so either works and this is the one that
              will not need changing again. */
           return "https://x.com/intent/post?text=" + encodeURIComponent(t)
                + "&url=" + encodeURIComponent(u);
         },
         win: "noopener,width=600,height=680",
         note: "X unfurls the link into the card above. Give it a second to fetch." },
    wa: { label: "WhatsApp", icon: "whatsapp",
          url: function (t, u) { return "https://wa.me/?text=" + encodeURIComponent(t + "\n" + u); },
          note: null },
    tg: { label: "Telegram", icon: "telegram",
          url: function (t, u) {
            return "https://t.me/share/url?url=" + encodeURIComponent(u)
                 + "&text=" + encodeURIComponent(t);
          },
          note: "Telegram shows the card under the link once it has fetched it." },
    li: { label: "LinkedIn", icon: "linkedin",
          url: function (t, u) {
            return "https://www.linkedin.com/sharing/share-offsite/?url=" + encodeURIComponent(u);
          },
          win: "noopener,width=640,height=680",
          note: "LinkedIn takes only the link and draws the card from it; add your own words there." },
    fb: { label: "Facebook", icon: "facebook",
          url: function (t, u) {
            return "https://www.facebook.com/sharer/sharer.php?u=" + encodeURIComponent(u);
          },
          win: "noopener,width=640,height=680",
          note: "Facebook draws the card from the link." }
  };
  var NET_ORDER = ["x", "wa", "tg", "li", "fb"];

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
    },

    /* A quarter as the company filed it. `period` is the quarter, in the URL
       only so that a new quarter is a new address — X and the CDN cache a
       card by URL, and the one posted the evening results land must not be
       the one rendered that morning. */
    results: {
      png: function (d) {
        return "/og/results.png" + qs({ ticker: clean(d.ticker || d.symbol), period: period(d) });
      },
      page: function (d) {
        return "/share/results/" + encodeURIComponent(clean(d.ticker || d.symbol))
             + qs({ period: period(d) });
      },
      file: function (d) {
        return "altaha-" + clean(d.ticker || d.symbol).toLowerCase()
             + (period(d) ? "-" + period(d).toLowerCase() : "") + "-results.png";
      },
      title: function (d) {
        return clean(d.ticker || d.symbol) + " — " + (d.quarter || "latest") + " results";
      },
      text: function (d) {
        function cr(v) {
          return "\u20B9" + Math.abs(Number(v)).toLocaleString("en-IN", { maximumFractionDigits: 2 })
               + " Cr";
        }
        function yoy(v) {
          return v == null ? "" : " (" + (Number(v) >= 0 ? "+" : "") + Number(v).toFixed(1) + "% YoY)";
        }
        var sym = clean(d.ticker || d.symbol);
        var lines = [sym + " — " + (d.quarter || "latest") + " results"
                     + (d.filed_at ? ", as filed with NSE." : ".")];
        var bits = [];
        if (d.pat_cr != null) {
          bits.push((Number(d.pat_cr) < 0 ? "Net loss " : "Profit ") + cr(d.pat_cr) + yoy(d.pat_yoy_pct));
        }
        if (d.revenue_cr != null) bits.push("Revenue " + cr(d.revenue_cr) + yoy(d.revenue_yoy_pct));
        if (bits.length) lines.push(bits.join(" · "));
        if (d.net_margin_pct != null) {
          lines.push("Net margin " + Number(d.net_margin_pct).toFixed(1) + "%"
                     + (d.net_margin_yoy_pct != null
                        ? ", from " + Number(d.net_margin_yoy_pct).toFixed(1) + "% a year earlier."
                        : "."));
        }
        return lines.join("\n");
      }
    }
  };

  function period(d) {
    return String((d && d.quarter) || "").trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9\-]/g, "");
  }

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

  /* The PNG, kept per card URL. Share image, Copy image and Download all
     need the bytes, a card takes a moment to render server-side, and asking
     twice would make the second button feel broken. Keyed by URL rather than
     held as "the current one" because the inline bar and the sheet can be
     looking at different cards. */
  var blobs = {};
  var blobOrder = [];

  function blobNow(d) {
    return d ? blobs[cardCandidates(d)[0]] || null : null;
  }

  function blobFor(d) {
    var key = cardCandidates(d)[0];
    if (blobs[key]) return Promise.resolve(blobs[key]);
    return fetchCard(d).then(function (res) {
      var b = res.blob.type === "image/png" ? res.blob
            : new Blob([res.blob], { type: "image/png" });
      blobs[key] = b;
      blobOrder.push(key);
      while (blobOrder.length > 8) delete blobs[blobOrder.shift()];
      return b;
    });
  }

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
        '<p class="shgrp">Post the card</p>' +
        '<div class="shbtns">' +
          NET_ORDER.map(function (k) {
            return '<button class="sharebtn shnet shnet-' + k + '" type="button" data-do="' + k +
                   '">' + icon(NETS[k].icon) + '<span class="lbl">' + NETS[k].label + '</span></button>';
          }).join("") +
        '</div>' +
        '<p class="shgrp">Or take the image</p>' +
        '<div class="shbtns">' +
          '<button class="sharebtn" type="button" data-do="native" hidden>' + icon("share") +
            '<span class="lbl">Share image…</span></button>' +
          '<button class="sharebtn" type="button" data-do="copyimg" hidden>' + icon("copy") +
            '<span class="lbl">Copy image</span></button>' +
          '<button class="sharebtn" type="button" data-do="dl">' + icon("download") +
            '<span class="lbl">Download image</span></button>' +
          '<button class="sharebtn" type="button" data-do="copy">' + icon("link") +
            '<span class="lbl">Copy link</span></button>' +
        '</div>' +
        '<p class="shnote" id="shnote"></p>' +
      '</div>';
    document.body.appendChild(sheet);

    sheet.addEventListener("click", function (ev) {
      if (ev.target.getAttribute && ev.target.getAttribute("data-shut")) { close(); return; }
      var btn = ev.target.closest ? ev.target.closest("[data-do]") : null;
      if (!btn) return;
      var act = btn.getAttribute("data-do");
      if (window.AltahaTrack) {
        window.AltahaTrack('share_clicked',
          { kind: (current && current.kind) || 'stock', action: act });
      }
      if (NETS[act]) post(act, current, btn);
      else if (act === "dl") onDownload(btn);
      else if (act === "copy") onCopy(btn);
      else if (act === "copyimg") onCopyImage(btn);
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
    /* Only the label changes: rewriting the whole button would take its
       logo with it. */
    var lbl = btn.querySelector ? btn.querySelector(".lbl") : null;
    if (!lbl && btn.querySelector && btn.querySelector("svg")) {
      // A logo with no words: the ring says it, and the logo stays put.
      btn.classList.add("done");
      clearTimeout(btn.__ring);
      btn.__ring = setTimeout(function () { btn.classList.remove("done"); }, 2200);
      return;
    }
    var target = lbl || btn;
    if (btn.__flashing) clearTimeout(btn.__flashing.t);
    var was = btn.__flashing ? btn.__flashing.was : target.textContent;
    target.textContent = text;
    btn.classList.add("done");
    btn.__flashing = { was: was, t: setTimeout(function () {
      target.textContent = was;
      btn.classList.remove("done");
      btn.__flashing = null;
    }, 2200) };
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

  /* Hand the post to a network. The card itself travels as the link's
     og:image, which every one of these fetches and draws under the post. */
  function post(net, d, btn) {
    var n = NETS[net];
    d = d || current;
    if (!n || !d) return;
    current = d;
    window.open(n.url(compose(d), link(d)), "_blank", n.win || "noopener");
    if (net === "wa") {
      note("WhatsApp previews links unreliably. For the picture itself, use " +
           (canShareFiles() ? "Share image…" : "Download image") + " and attach it.");
    } else {
      note(n.note || "");
    }
    if (btn) flash(btn, "Opened");
  }

  function onX() { post("x"); }

  function onWhatsApp() { post("wa"); }

  function onNative(btn, d) {
    d = d || current;
    if (!d || !navigator.share) return;
    var payload = { title: kindOf(d).title(d), text: compose(d), url: link(d) };
    var go = function (files) {
      var data = files ? { files: files, title: payload.title, text: payload.text } : payload;
      navigator.share(data).catch(function () { /* the user dismissed the sheet */ });
    };
    var ready = blobNow(d);
    if (ready && canShareFiles()) {
      try {
        go([new File([ready], kindOf(d).file(d), { type: "image/png" })]);
        return;
      } catch (e) { /* fall through to the link-only share */ }
    }
    flash(btn, "Preparing…");
    blobFor(d).then(function (b) {
      try { go([new File([b], kindOf(d).file(d), { type: "image/png" })]); }
      catch (e) { go(null); }
    }).catch(function () { go(null); });
  }

  function canCopyImage() {
    return !!(window.ClipboardItem && navigator.clipboard && navigator.clipboard.write);
  }

  /* The picture on the clipboard. On a desktop this is the only way to put
     the image itself into a post on X or Telegram — their share links carry
     text and a URL and nothing else. */
  function onCopyImage(btn, d) {
    d = d || current;
    if (!d || !canCopyImage()) return;
    var ready = blobNow(d);
    var item;
    try {
      // A ready Blob where there is one: older Chromium refuses a promise.
      item = new window.ClipboardItem({ "image/png": ready || blobFor(d) });
    } catch (e) {
      flash(btn, "Not supported here");
      return;
    }
    navigator.clipboard.write([item]).then(function () {
      flash(btn, "Copied");
      note("Paste it straight into a post on X, Telegram or WhatsApp Web.");
    }).catch(function () {
      flash(btn, "Blocked — use Download");
    });
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

  function onDownload(btn, d) {
    d = d || current;
    if (!d) return;
    var name = kindOf(d).file(d);
    var ready = blobNow(d);
    if (ready) { saveBlob(ready, name); flash(btn, "Saved"); return; }
    flash(btn, "Rendering…");
    blobFor(d).then(function (b) {
      saveBlob(b, name);
      flash(btn, "Saved");
    }).catch(function () {
      /* Some in-app browsers block both fetch and programmatic downloads.
         Opening the image directly still lets a long-press save it. */
      window.open(cardCandidates(d)[0], "_blank", "noopener");
      flash(btn, "Opened — long-press to save");
    });
  }

  function onCopy(btn, d) {
    d = d || current;
    if (!d) return;
    var url = link(d);
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
    record: "The whole ledger — every idea logged the day it was generated.",
    results: "The quarter as the company filed it — profit, revenue, margin and the " +
             "same quarter a year earlier. Every figure on it is the company's own."
  };

  function open(d) {
    if (!d) return;
    build();
    current = d;

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
    var cpi = sheet.querySelector('[data-do="copyimg"]');
    if (cpi) cpi.hidden = !canCopyImage();

    sheet.hidden = false;
    document.body.classList.add("sh-open");

    /* Warm the blob so Share… and Download are instant when they are pressed.
       Failure here is silent by design — the buttons handle it themselves. */
    blobFor(d).catch(function () {});
  }

  /* ---- a row of logos, on the card itself ---------------------------------
     For a card that is the whole point of its page — a quarter's results —
     the networks belong on the card, one press each, rather than behind a
     Share button. `getPayload` is asked at press time, so the row follows
     whatever the card is showing now. */

  function bar(host, getPayload) {
    if (!host || host.__shareBar) return;
    host.__shareBar = getPayload;
    var html = NET_ORDER.map(function (k) {
      return '<button class="shround shnet-' + k + '" type="button" data-to="' + k +
             '" title="Share on ' + NETS[k].label + '" aria-label="Share on ' + NETS[k].label +
             '">' + icon(NETS[k].icon) + '</button>';
    }).join("");
    html += '<span class="shlogos-gap" aria-hidden="true"></span>';
    if (navigator.share) {
      html += '<button class="shpill" type="button" data-to="native">' + icon("share") +
              '<span class="lbl">Share image</span></button>';
    }
    html += '<button class="shpill" type="button" data-to="sheet">' + icon("image") +
            '<span class="lbl">Image</span></button>';
    html += '<button class="shpill" type="button" data-to="copy">' + icon("link") +
            '<span class="lbl">Copy link</span></button>';
    host.innerHTML = html;
    host.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-to]") : null;
      if (!b) return;
      var d = host.__shareBar && host.__shareBar();
      if (!d) return;
      var to = b.getAttribute("data-to");
      if (window.AltahaTrack) {
        window.AltahaTrack("share_clicked", { kind: d.kind || "stock", action: to, from: "bar" });
      }
      if (NETS[to]) post(to, d, b);
      else if (to === "sheet") open(d);
      else if (to === "native") onNative(b, d);
      else if (to === "copy") onCopy(b, d);
    });
  }

  /* Fetch a card's image ahead of the press. Share image has to call
     navigator.share inside the tap that asked for it, and Safari forgets the
     tap while a render is in flight. */
  function prefetch(d) {
    if (d) blobFor(d).catch(function () {});
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
        if (row && row.__payload) { current = row.__payload; }
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
    close: close, post: post, bar: bar, prefetch: prefetch, icon: icon,
    shareUrl: function (net, d) { return NETS[net] ? NETS[net].url(compose(d), link(d)) : null; }
  };
})();
