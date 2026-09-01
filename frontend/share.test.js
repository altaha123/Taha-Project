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
  { d: { kind: "record", total_tracked: 96,
         overall: { beat_index_pct: 56, avg_alpha_pct: 1.15 } },
    link: "https://site.example/share/record",
    card: "https://site.example/og/record.png" },
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
