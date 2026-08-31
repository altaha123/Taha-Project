/* Node test for share.js — run by CI, no browser needed.
 *
 * The guard that matters: the composed post carries scores and never a price
 * level or a directive. The card has the same test on the Python side; this
 * is the other half, because the post text is composed here and a target
 * price reaching a public timeline is the one failure with consequences
 * beyond a bug report. */

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

// Minimal DOM so the module can load and register itself.
const sandbox = {
  window: {}, document: {
    readyState: "complete",
    getElementById: () => null,
    addEventListener: () => {},
  },
  navigator: {}, setTimeout, console,
};
sandbox.window.API_BASE = "https://api.example";
sandbox.window.document = sandbox.document;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__dirname + "/share.js", "utf8"), sandbox);

const S = sandbox.window.AltahaShare;
assert.ok(S, "share.js did not register window.AltahaShare");

const analysis = {
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

// --- the scores are there --------------------------------------------------
for (const want of ["RELIANCE", "42/100", "Technical 9", "Fundamental 75",
                    "Piotroski 6/9", "Quality at Discount"]) {
  assert.ok(blob.includes(want), `post is missing "${want}":\n${blob}`);
}

// --- no level, no directive ------------------------------------------------
for (const bad of ["1995", "1836", "2315", "1,995", "1,836", "2,315"]) {
  assert.ok(!blob.includes(bad), `a price level reached the post: ${bad}\n${blob}`);
}
for (const word of ["BUY", "SELL", "TARGET", "STOP", "ENTRY"]) {
  assert.ok(!blob.toUpperCase().includes(word), `a directive reached the post: ${word}`);
}

// --- the link points at the crawler-readable page --------------------------
assert.strictEqual(url, "https://api.example/share/RELIANCE",
  "the shared link must be the /share page, not the app URL");

// --- a sparse payload degrades rather than printing undefined --------------
const sparse = S.compose({ ticker: "X" });
assert.ok(!/undefined|NaN|null/.test(sparse), `sparse payload leaked: ${sparse}`);

// --- X's limit ------------------------------------------------------------
assert.ok(text.length <= 240, `post text is ${text.length} chars, too long with a URL`);

console.log("share.js: all assertions passed");
console.log("--- composed post ---\n" + text + "\n" + url);
