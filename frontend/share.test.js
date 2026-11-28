/* Node test for share.js — run by CI, no browser needed.
 *
 * Two guards, and the second is the one with consequences beyond a bug report.
 *
 * 1. The link handed out points at the SITE, never at the API's hosting
 *    provider. A posted link is permanent in a way infrastructure is not, and
 *    onrender.com on the front of the product is the first thing a stranger
 *    reads. vercel.json proxies /share and /og through from the site's own
 *    domain so both hosts serve the same documents; this asserts the one that
 *    goes out in public is the site.
 *
 * 2. The composed post carries scores and never a price level or a directive.
 *    The card has the same test on the Python side; this is the other half,
 *    because the post text is composed here.
 */

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

// Minimal DOM so the module can load and register itself.
const sandbox = {
  window: {}, document: {
    readyState: "complete",
    getElementById: () => null,
    createElement: () => ({ style: {}, setAttribute() {}, addEventListener() {} }),
    addEventListener: () => {},
  },
  navigator: {}, setTimeout, console,
};
sandbox.window.API_BASE = "https://api.example";
sandbox.window.SITE_URL = "https://site.example";
sandbox.window.document = sandbox.document;
sandbox.window.location = { origin: "https://site.example", search: "" };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__dirname + "/share.js", "utf8"), sandbox);

const S = sandbox.window.AltahaShare;
assert.ok(S, "share.js did not register window.AltahaShare");

/* ── the scorecard ─────────────────────────────────────────────────────── */

const analysis = {
  kind: "stock",
  ticker: "RELIANCE.NS", name: "Reliance Industries Limited",
  scoring: { score: 42, label: "MIXED" },
  technical: { score: 9 },
  fundamental: { score: 75, f_score: 6 },
  setup: { name: "Quality at Discount" },
  // Present in the payload, and must not survive into the post.
  plan: { entry: 1995.98, stop: 1836.31, t1: 2315.34, rr: 2 },
};

const text = S.compose(analysis);
const url = S.link(analysis);
const blob = text + " " + url;

for (const want of ["RELIANCE", "42/100", "Technical 9", "Fundamental 75",
                    "Piotroski 6/9", "Quality at Discount"]) {
  assert.ok(blob.includes(want), `post is missing "${want}":\n${blob}`);
}

assert.strictEqual(url, "https://site.example/share/RELIANCE",
  "the shared link must be the site's own /share page");
assert.strictEqual(S.card(analysis),
  "https://site.example/og/stock.png?ticker=RELIANCE",
  "the card image must be requested from the site, not the API host");

/* ── every kind produces a link, a card and a post ─────────────────────── */

// A results card as /results returns it, filed with NSE.
const RESULTS = {
  kind: "results", ticker: "TARIL", symbol: "TARIL",
  name: "Transformers And Rectifiers (India) Limited",
  quarter: "Q2 FY27", as_of: "2026-09-30", filed_at: "13-Oct-2026 16:34:09",
  pat_cr: 81.38, pat_yoy_pct: 117.9, revenue_cr: 739.44, revenue_yoy_pct: 60.7,
  net_margin_pct: 11.0, net_margin_yoy_pct: 8.1,
};

const CONCALL = {
  kind: "concall", ticker: "TARIL", company: "Transformers And Rectifiers (India) Ltd",
  quarter: "Q2 FY27", headline: "Order book at \u20B95,472 crore; FY27 revenue guidance held",
};

const ORDER = {
  kind: "wow", ticker: "PACEDIGITK", id: "6eed6d67e567", company: "Pace Digitek Limited",
  value_cr: 2691.3, pct_of_market_cap: 75.4, market_cap_cr: 3569.3,
  customer: "NTPC Green Energy Limited", order_kind: "Letter of award",
};

const cases = [
  { d: { kind: "stock", ticker: "TCS" },
    link: "https://site.example/share/TCS",
    card: "https://site.example/og/stock.png?ticker=TCS" },
  { d: { kind: "chart", ticker: "INFY", range: "1W",
         pattern: { name: "Cup and Handle", status: "forming", confidence: 71 } },
    link: "https://site.example/share/chart/INFY?range=1W",
    card: "https://site.example/og/chart.png?ticker=INFY&range=1W" },
  { d: { kind: "idea", ticker: "HDFCBANK", horizon_key: "medium", conviction: 68,
         conviction_band: "High", setup: "Momentum Breakout", horizon: "3–6 months" },
    link: "https://site.example/share/idea/HDFCBANK?horizon=medium",
    card: "https://site.example/og/idea.png?ticker=HDFCBANK&horizon=medium" },
  { d: { kind: "holding", ticker: "ITC", return_pct: 8.4, alpha_pct: 3.1,
         bench_return_pct: 5.3, added_on: "2026-01-04", days_held: 61 },
    link: "https://site.example/share/holding/ITC",
    card: "https://site.example/og/holding.png?ticker=ITC" },
  { d: { kind: "record", calls: 96, up_since_pct: 58.5, avg_since_pct: 2.31,
         avg_vs_index_pct: 1.15 },
    link: "https://site.example/share/record",
    card: "https://site.example/og/record.png" },
  { d: RESULTS,
    link: "https://site.example/share/results/TARIL?period=Q2-FY27",
    card: "https://site.example/og/results.png?ticker=TARIL&period=Q2-FY27" },
  { d: CONCALL,
    link: "https://site.example/share/concall/TARIL?period=Q2-FY27",
    card: "https://site.example/og/concall.png?ticker=TARIL&period=Q2-FY27" },
  { d: ORDER,
    link: "https://site.example/share/wow/PACEDIGITK?id=6eed6d67e567",
    card: "https://site.example/og/wow.png?ticker=PACEDIGITK&id=6eed6d67e567" },
  { d: { kind: "research", slug: "capital-goods-order-books", version: 3,
         title: "Capital goods: why the order book matters this year",
         summary: "Order inflows have doubled in two years. Execution, not demand, is the constraint.",
         tickers: ["LT", "SIEMENS"] },
    link: "https://site.example/share/research/capital-goods-order-books?v=3",
    card: "https://site.example/og/research.png?slug=capital-goods-order-books&v=3" },
];

for (const c of cases) {
  assert.strictEqual(S.link(c.d), c.link, `${c.d.kind}: wrong link`);
  assert.strictEqual(S.card(c.d), c.card, `${c.d.kind}: wrong card URL`);
  const t = S.compose(c.d);
  assert.ok(t && t.length > 20, `${c.d.kind}: empty post`);
  assert.ok(!/undefined|NaN|\[object/.test(t), `${c.d.kind}: leaked a raw value:\n${t}`);
  assert.ok(!/onrender\.com/.test(t + S.link(c.d) + S.card(c.d)),
    `${c.d.kind}: the API host reached a public link`);
}

/* ── the chart post says what was found, or honestly that nothing was ──── */

assert.ok(S.compose(cases[1].d).includes("Cup and Handle"),
  "the chart post drops the pattern it found");
assert.ok(/no textbook pattern/i.test(S.compose({ kind: "chart", ticker: "X", range: "1D" })),
  "a chart with no pattern must say so rather than say nothing");

/* ── a results post carries the quarter's own numbers ─────────────────── */

const rpost = S.compose(RESULTS);
for (const want of ["TARIL", "Q2 FY27", "as filed with NSE", "\u20B981.38 Cr",
                    "+117.9% YoY", "\u20B9739.44 Cr", "+60.7% YoY", "11.0%", "8.1%"]) {
  assert.ok(rpost.includes(want), `results post is missing "${want}":\n${rpost}`);
}
const lossPost = S.compose(Object.assign({}, RESULTS, { pat_cr: -12.5, pat_yoy_pct: null }));
assert.ok(lossPost.includes("Net loss \u20B912.5 Cr"), `a loss must say so:\n${lossPost}`);
assert.ok(!/undefined|NaN|null/.test(S.compose({ kind: "results", ticker: "X" })),
  "a sparse results payload leaked a raw value");

/* ── a concall post is the company, the quarter and what was said ──────── */

const cpost = S.compose(CONCALL);
assert.strictEqual(cpost,
  "Transformers And Rectifiers (India) Ltd: Q2 FY27 earnings call\n" +
  "Order book at \u20B95,472 crore; FY27 revenue guidance held\n\n" +
  "AI summary of the transcript the company filed.");
/* A long headline is cut at a word and says it was cut; the closing line is
   what goes first, and the whole post still leaves room for the link. */
const longCall = S.compose(Object.assign({}, CONCALL, {
  company: "Solarworld Energy Solutions Limited",
  headline: "Management cut FY27 guidance to \u20B91,600\u20131,700 crore revenue and " +
            "5\u20136% profit margin on fixed-price government contracts, and said the " +
            "order book supports \u20B93,000 crore of revenue in FY28 and beyond that",
}));
assert.ok(longCall.length <= 240, `a long concall post is ${longCall.length} chars`);
assert.ok(longCall.endsWith("\u2026"), `a cut headline must say so:\n${longCall}`);
assert.ok(!/\s\u2026$/.test(longCall) && !longCall.includes("AI summary"), longCall);
assert.ok(longCall.startsWith("Solarworld Energy Solutions Limited: Q2 FY27 earnings call\n" +
  "Management cut FY27 guidance to \u20B91,600\u20131,700 crore"), longCall);
for (const d of [{ kind: "concall", ticker: "X" },
                 { kind: "concall", ticker: "X", company: "W".repeat(300), headline: "H ".repeat(300) }]) {
  const t = S.compose(d);
  assert.ok(t.length <= 240 && !/undefined|NaN|null/.test(t), `sparse concall post:\n${t}`);
}
assert.strictEqual(S.link({ kind: "concall", ticker: "M&M", quarter: "Q1 FY27" }),
  "https://site.example/share/concall/M%26M?period=Q1-FY27");
assert.strictEqual(S.link({ kind: "concall", ticker: "X" }), "https://site.example/share/concall/X");

/* ── an order post is who won what from whom, and how big it is ────────── */

assert.strictEqual(S.compose(ORDER),
  "Pace Digitek Limited: \u20B92,691 cr letter of award from NTPC Green Energy Limited\n" +
  "That is 75% of the company\u2019s market cap (\u20B93,569 cr).\n\n" +
  "From the company\u2019s filing with the exchange.");
/* A customer's name can be a sentence. It is what gives; the size never does. */
const longOrder = S.compose(Object.assign({}, ORDER, {
  customer: "Overseas entity situated in Ghana (the Customer\u2019s name is withheld due to " +
            "confidentiality obligations under the agreement between the parties and will be " +
            "disclosed in due course as and when permitted)",
}));
assert.ok(longOrder.length <= 240, `a long order post is ${longOrder.length} chars`);
assert.ok(longOrder.includes("That is 75% of the company\u2019s market cap"), longOrder);
assert.ok(longOrder.includes("\u2026"), `a cut name must say so:\n${longOrder}`);
for (const d of [{ kind: "wow", ticker: "X" },
                 { kind: "wow", ticker: "X", value_cr: 0.4, pct_of_market_cap: 0.02 },
                 { kind: "wow", ticker: "X", company: "W".repeat(300), customer: "C ".repeat(300),
                   value_cr: 5, pct_of_market_cap: 12, market_cap_cr: 41 }]) {
  const t = S.compose(d);
  assert.ok(t.length <= 240 && !/undefined|NaN|null/.test(t), `sparse order post:\n${t}`);
}
assert.strictEqual(S.link({ kind: "wow", ticker: "M&M", id: "AB12-zz" }),
  "https://site.example/share/wow/M%26M?id=ab12");
assert.strictEqual(S.link({ kind: "wow", ticker: "X" }), "https://site.example/share/wow/X");

/* ── every network gets the link, and the card travels with it ─────────── */

const rlink = encodeURIComponent(S.link(RESULTS));
const nets = {
  x: "https://x.com/intent/post?text=",
  wa: "https://wa.me/?text=",
  tg: "https://t.me/share/url?url=",
  li: "https://www.linkedin.com/sharing/share-offsite/?url=",
  fb: "https://www.facebook.com/sharer/sharer.php?u=",
};
for (const [net, prefix] of Object.entries(nets)) {
  const u = S.shareUrl(net, RESULTS);
  assert.ok(u && u.startsWith(prefix), `${net}: wrong share address ${u}`);
  assert.ok(u.includes(rlink), `${net}: the share address drops the card's link`);
}
assert.strictEqual(S.shareUrl("myspace", RESULTS), null);

/* ── every network has its logo ────────────────────────────────────────── */

for (const name of ["x", "whatsapp", "telegram", "linkedin", "facebook"]) {
  const svg = S.icon(name);
  assert.ok(/^<svg[^>]*viewBox="0 0 24 24"[^>]*aria-hidden="true"/.test(svg),
    `${name}: no decorative svg`);
  assert.ok(/<path fill="currentColor" d="M[^"]{40,}"/.test(svg), `${name}: no mark`);
}
for (const name of ["share", "download", "image", "copy", "link"]) {
  assert.ok(S.icon(name).includes('stroke="currentColor"'), `${name}: no glyph`);
}
assert.strictEqual(S.icon("nope"), "");

/* ── the tracked position posts its loss as readily as its gain ────────── */

const loser = S.compose({ kind: "holding", ticker: "X", return_pct: -12.5,
                          alpha_pct: -8.2, bench_return_pct: -4.3 });
assert.ok(loser.includes("-12.50%"), `a loss must render:\n${loser}`);

/* ── no level, no directive, in any post ───────────────────────────────── */

const everything = [text, ...cases.map(c => S.compose(c.d))].join("\n");
for (const bad of ["1995", "1836", "2315", "1,995", "1,836", "2,315"]) {
  assert.ok(!everything.includes(bad), `a price level reached a post: ${bad}`);
}
for (const word of ["BUY", "SELL", "TARGET", "STOP", "ENTRY"]) {
  assert.ok(!everything.toUpperCase().includes(word),
    `a directive reached a post: ${word}`);
}

/* ── a sparse payload degrades rather than printing undefined ──────────── */

const sparse = S.compose({ ticker: "X" });
assert.ok(!/undefined|NaN|null/.test(sparse), `sparse payload leaked: ${sparse}`);

/* ── X's limit ─────────────────────────────────────────────────────────── */

for (const t of [text, ...cases.map(c => S.compose(c.d))]) {
  assert.ok(t.length <= 240, `post text is ${t.length} chars, too long with a URL:\n${t}`);
}

console.log("share.js: all assertions passed");
console.log("--- composed post ---\n" + text + "\n" + url);

/* ── a research post fits on X with its link, however long the article ─── */

for (const d of [{ kind: "research", slug: "x", version: 1 },
                 { kind: "research", slug: "x", version: 1, title: "T ".repeat(200),
                   summary: "S ".repeat(400), tickers: ["A", "B", "C", "D"] }]) {
  const t = S.compose(d);
  assert.ok(t.length <= 240, "a research post leaves no room for the link: " + t.length);
  assert.ok(!/undefined|NaN|null/.test(t), "a research post leaked a raw value:\n" + t);
}
assert.ok(S.compose(cases[cases.length - 1].d).includes("$LT"),
  "the research post drops the stocks it is about");
