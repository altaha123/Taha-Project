/* Node test for alerts-logic.js, run by CI. No browser needed.
 *
 * The Alerts page shows two lanes of calls: Classic (every call, as always)
 * and ★ Select (fewer, stronger). Everything that page decides rather than
 * draws is in alerts-logic.js, and pinned here:
 *
 *   1. One break called by both lanes is ONE card, never two, and is
 *      counted once.
 *   2. A call's live state reads in the exact words the owner asked for,
 *      and the after-the-close check outranks the live tracker.
 *   3. Filters and the reader's stored choices survive a browser that
 *      throws on storage.
 *   4. The timeline, the radar and the record put things where they belong.
 */

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

/* ── it registers itself on window, as the page loads it ───────────────── */
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__dirname + "/alerts-logic.js", "utf8"), sandbox);
const W = sandbox.window.AltahaAlertsLogic;
assert.ok(W, "alerts-logic.js did not register window.AltahaAlertsLogic");

const L = require("./alerts-logic.js");
assert.deepStrictEqual(Object.keys(W).sort(), Object.keys(L).sort(), "window and module.exports differ");

/* A day of calls in the shape /intraday/status serves (newest first). */
const D = "2026-11-27";
const C1 = { date: D, time: "09:31", symbol: "TATAMOTORS", direction: "UP", call: "INTRADAY", engine: "classic", score: 78,
  entry: 1013.90, stop: 1006.80, t1: 1021.00, target: 1028.10, rr: 2,
  live_outcome: "TARGET", live_time: "10:48", live_exit: 1028.10, live_pnl_pct: 1.40, live_r: 2.0, t1_hit: true };
const C2 = { date: D, time: "09:47", symbol: "HINDALCO", direction: "DOWN", call: "INTRADAY", engine: "classic", score: 69,
  entry: 652.40, stop: 656.30, live_outcome: "STOP", live_time: "10:21", live_pnl_pct: -0.60, live_r: -1.0 };
const C3 = { date: D, time: "10:02", symbol: "BEL", direction: "UP", call: "CONSOLIDATION", score: 82,   // no engine: an old row is Classic
  entry: 414.10, stop: 411.25, t1: 416.95, target: 419.80, rr: 2, select_time: "10:05", select_score: 86,
  live_price: 417.60, live_pnl_pct: 0.85, live_r: 1.23, t1_hit: true, t1_time: "10:31", mfe_r: 1.75, mae_r: -0.18 };
const C4 = { date: D, time: "10:54", symbol: "INFY", direction: "UP", call: "INTRADAY", engine: "classic", score: 74,
  live_price: 1998.60, live_pnl_pct: 0.37, live_r: 0.58 };
const C5 = { date: D, time: "11:36", symbol: "DLF", direction: "DOWN", call: "CONSOLIDATION", engine: "classic", score: 71,
  live_price: 815.90, live_pnl_pct: 0.15, live_r: 0.23 };
const S1 = { date: D, time: "10:05", symbol: "BEL", direction: "UP", call: "CONSOLIDATION", engine: "select", score: 86,
  pair_time: "10:02", live_price: 417.60, live_pnl_pct: 0.58, live_r: 0.77, t1_hit: true };
const S2 = { date: D, time: "11:12", symbol: "SBIN", direction: "UP", call: "INTRADAY", engine: "select", score: 81,
  window: "mid", live_price: 816.30, live_pnl_pct: 0.33 };
const S3 = { date: D, time: "11:28", symbol: "LT", direction: "UP", call: "INTRADAY", engine: "select", score: 84,
  window: "mid", live_price: 3611.40, live_pnl_pct: -0.36 };
const ROWS = [C5, S3, S2, C4, S1, C3, C2, C1];

/* ── words and numbers ─────────────────────────────────────────────────── */
assert.strictEqual(L.clock12("10:02"), "10:02 am");
assert.strictEqual(L.clock12("09:25"), "9:25 am");
assert.strictEqual(L.clock12("12:30"), "12:30 pm");
assert.strictEqual(L.clock12("15:15"), "3:15 pm");
assert.strictEqual(L.clock12("00:05"), "12:05 am");
assert.strictEqual(L.clock12("junk"), "");
assert.strictEqual(L.span12("09:20–15:00"), "9:20 am to 3 pm");
assert.strictEqual(L.span12("09:25-14:45"), "9:25 am to 2:45 pm");
assert.strictEqual(L.span12(""), "");
assert.strictEqual(L.money(418.4), "₹418.40");
assert.strictEqual(L.money(11852), "₹11,852.00");
assert.strictEqual(L.money(null), "—");
assert.strictEqual(L.pct(1.04), "+1.0%");
assert.strictEqual(L.pct(-0.36), "−0.4%");
assert.strictEqual(L.pct(-0.04), "0.0%", "a figure that rounds to nothing has no sign");
assert.strictEqual(L.pct(undefined), "");
assert.strictEqual(L.rmult(0.38), "+0.38R");
assert.strictEqual(L.rmult(-1), "−1.00R");
assert.strictEqual(L.num(true), null, "a boolean is not a number here");

/* ── India time, whatever the reader's clock says ─────────────────────── */
const AT = Date.parse("2026-11-27T11:42:30+05:30");
assert.deepStrictEqual(L.ist(AT), { date: "2026-11-27", mins: 11 * 60 + 42.5, hhmm: "11:42" });
assert.strictEqual(L.ist(Date.parse("2026-11-26T19:00:00Z")).date, "2026-11-27", "00:30 IST is already the next day");
assert.strictEqual(L.callAt(C5), Date.parse("2026-11-27T11:36:00+05:30"));
assert.strictEqual(L.callAt({ date: "bad", time: "10:00" }), null);
assert.strictEqual(L.ago(L.callAt(C5), AT), "6m ago");
assert.strictEqual(L.ago(L.callAt(C5), Date.parse("2026-11-27T11:36:40+05:30")), "just now");
assert.strictEqual(L.ago(L.callAt(C5), Date.parse("2026-11-27T11:35:00+05:30")), "just now", "a clock that runs slow never says 'in the future'");
assert.strictEqual(L.ago(L.callAt(C5), Date.parse("2026-11-27T12:41:10+05:30")), "1h 5m ago");
assert.strictEqual(L.ago(L.callAt(C5), Date.parse("2026-11-27T13:36:00+05:30")), "2h ago");
assert.strictEqual(L.ago(L.callAt(C5), Date.parse("2026-11-28T11:40:00+05:30")), "", "yesterday's call: the time says enough");
assert.strictEqual(L.ago(null, AT), "");

/* ── two lanes, one card per break ─────────────────────────────────────── */
assert.strictEqual(L.engineOf(C3), "classic", "a row without engine is Classic");
assert.strictEqual(L.engineOf(S1), "select");
assert.notStrictEqual(L.keyOf(C3), L.keyOf({ ...C3, engine: "select" }), "the lane is part of a call's identity");

const all = L.items(ROWS, "all");
assert.strictEqual(all.length, 7, "eight records, one break called by both lanes: seven cards");
const bel = all.filter(i => i.rec.symbol === "BEL");
assert.strictEqual(bel.length, 1, "BEL is one card in All");
assert.strictEqual(bel[0].rec, C3, "the card is the Classic call, which came first");
assert.strictEqual(bel[0].pair, S1, "and carries its ★ Select partner for the badge");
assert.deepStrictEqual(all.map(i => i.rec.time), ["11:36", "11:28", "11:12", "10:54", "10:02", "09:47", "09:31"], "newest first, as served");

const sel = L.items(ROWS, "select");
assert.deepStrictEqual(sel.map(i => i.rec.symbol), ["LT", "SBIN", "BEL"], "★ Select shows its own three records");
assert.strictEqual(sel[2].pair, C3, "a Select card still knows the Classic call it confirmed");
const cls = L.items(ROWS, "classic");
assert.strictEqual(cls.length, 5, "Classic shows its own five");
assert.strictEqual(cls.find(i => i.rec === C3).pair, S1);
assert.strictEqual(L.countCalls(ROWS), 7, "a paired Select record is not counted twice");

// Paired only from the Classic side (no pair_time on the Select row): still one card.
{
  const c = { date: D, time: "10:40", symbol: "ITC", direction: "UP", engine: "classic", select_time: "10:44" };
  const s = { date: D, time: "10:44", symbol: "ITC", direction: "UP", engine: "select" };
  assert.strictEqual(L.items([s, c], "all").length, 1);
  // A Select call on the other side of the same stock is its own call.
  const other = { date: D, time: "13:10", symbol: "ITC", direction: "DOWN", engine: "select" };
  assert.strictEqual(L.items([other, s, c], "all").length, 2);
  // A second Select call on the same stock, same side, later: the exact match is claimed first.
  const later = { date: D, time: "13:20", symbol: "ITC", direction: "UP", engine: "select" };
  const p = L.pairs([later, s, c]);
  assert.strictEqual(p.byClassic[L.keyOf(c)], s, "the exact match wins over the later call");
  assert.strictEqual(p.bySelect[L.keyOf(later)], undefined, "and the later Select call stands alone");
  // A Select row naming a Classic time nobody has, on a stock nobody else called, stands alone.
  assert.strictEqual(L.items([{ date: D, time: "11:00", symbol: "NTPC", direction: "UP", engine: "select", pair_time: "10:58" }], "all").length, 1);
}

/* ── live state, in the owner's words ──────────────────────────────────── */
{
  const st = L.liveState({ live_price: 418.40, live_pnl_pct: 1.04 });
  assert.strictEqual(st.key, "live");
  assert.strictEqual(st.label, "LIVE · ₹418.40 (+1.0%)");
  assert.strictEqual(L.liveState({ live_price: 3611.4, live_pnl_pct: -0.36 }).label, "LIVE · ₹3,611.40 (−0.4%)");
  assert.strictEqual(L.liveState(C3).label, "T1 HIT · Move SL to cost");
  assert.strictEqual(L.liveState(C3).key, "t1");
  assert.strictEqual(L.liveState(C1).label, "TARGET HIT ✓");
  assert.strictEqual(L.liveState(C1).tone, "won");
  assert.strictEqual(L.liveState(C2).label, "STOPPED OUT ✕");
  assert.strictEqual(L.liveState(C2).tone, "lost");
  assert.strictEqual(L.liveState({ live_outcome: "OPEN_AT_CLOSE", live_time: "15:16", live_pnl_pct: 0.4 }).label, "CLOSED 3:15 pm");
  assert.strictEqual(L.liveState({ live_outcome: "OPEN_AT_CLOSE", live_pnl_pct: -0.2 }).tone, "lost");
  // After mark_outcomes the authoritative line wins, whatever the tracker said.
  const fin = L.liveState({ outcome: "TARGET", pnl_pct: 1.4, live_outcome: "STOP" });
  assert.strictEqual(fin.key, "final");
  assert.strictEqual(fin.label, "Hit the target");
  assert.strictEqual(L.liveState({ outcome: "OPEN_AT_CLOSE", pnl_pct: -0.3 }).tone, "lost");
  assert.strictEqual(L.liveState({}).key, "none", "no live fields (an older backend): no pill");
  assert.strictEqual(L.liveState({ live_price: 0 }).key, "none", "a zero price is no price");
  assert.ok(L.isActive(C4) && !L.isActive(C1) && !L.isActive(C2) && !L.isActive({ outcome: "STOP" }));
  assert.ok(L.isWin(C1) && !L.isWin(C3) && L.isWin({ outcome: "TARGET" }) && !L.isWin({ outcome: "STOP", live_outcome: "TARGET" }));
  assert.ok(L.isStopped(C2) && !L.isStopped(C1));
}

/* ── the rail: stop −1R, entry 0, half-book +1R, target +2R ───────────── */
{
  const r = L.rail(C3);
  assert.strictEqual(r.entry, 33.3);
  assert.strictEqual(r.t1, 66.7);
  assert.strictEqual(r.now, 74.3);
  assert.strictEqual(r.lo, 27.3, "the worst it went, below the entry");
  assert.strictEqual(r.hi, 91.7, "the best it went");
  // No live_r: worked out from the price.
  const p = L.rail({ direction: "DOWN", entry: 100, stop: 101, rr: 2, live_price: 99 });
  assert.strictEqual(p.r, 1);
  assert.strictEqual(p.now, 66.7, "a fall is progress for a SELL");
  assert.strictEqual(L.rail({ entry: 100, stop: 99, live_r: 3.5 }).now, 100, "beyond the target sits at the end");
  assert.strictEqual(L.rail({ entry: 100, stop: 99, live_r: -1.6 }).now, 0, "beyond the stop sits at the start");
  assert.strictEqual(L.rail({ entry: 100, stop: 99 }), null, "a plan with no price yet has no rail");
}

/* ── what the score is made of, and what Select's checks said ────────── */
{
  assert.strictEqual(L.scoreTitle({ score: 78, score_parts: { volume: 23, level: 15, risk: 3, range: 0, index: 10, book: -2 } }),
    "Score 78 out of 100: volume +23, level +15, index +10, risk +3, order book −2", "biggest first, nothing that counted for nothing");
  assert.strictEqual(L.scoreTitle({ score: 71 }), "Score 71 out of 100");
  assert.strictEqual(L.scoreTitle({}), "");
  assert.deepStrictEqual(L.shadowWords({ shadow: [] }), [], "passed every Select check");
  assert.deepStrictEqual(L.shadowWords({ shadow: ["rpos", "sector", "newcheck"] }),
    ["not near the day’s extreme", "sector against it", "newcheck"]);
  assert.strictEqual(L.shadowWords({ engine: "select", shadow: [] }), null, "a Select call needs no second opinion");
  assert.strictEqual(L.shadowWords({}), null, "an older row says nothing");
}

/* ── filters ───────────────────────────────────────────────────────────── */
{
  let f = L.normFilter(null);
  assert.deepStrictEqual(f, { lane: "all", side: null, active: false, score: false });
  assert.ok(L.pressed(f, "all") && !L.pressed(f, "select") && !L.pressed(f, "buy"));
  f = L.press(f, "select");
  assert.ok(L.pressed(f, "select") && !L.pressed(f, "all"), "the lane pills are one choice of three");
  assert.strictEqual(L.press(f, "select").lane, "select", "pressing the chosen lane keeps it");
  f = L.press(f, "buy");
  assert.strictEqual(f.side, "BUY");
  f = L.press(f, "sell");
  assert.strictEqual(f.side, "SELL", "BUY and SELL are one choice of two");
  assert.strictEqual(L.press(f, "sell").side, null, "or neither");
  assert.strictEqual(L.press(L.press(f, "active"), "active").active, false);
  assert.strictEqual(L.describe({ lane: "select", side: "BUY", active: true, score: true }), "★ Select · Active · BUY · Score 75+");
  assert.deepStrictEqual(L.normFilter({ lane: "evil", side: "x", active: "yes", score: 1 }),
    { lane: "all", side: null, active: false, score: false }, "anything stored that is not a choice is dropped");

  assert.deepStrictEqual(L.view(ROWS, { lane: "select" }).map(i => i.rec.symbol), ["LT", "SBIN", "BEL"]);
  assert.deepStrictEqual(L.view(ROWS, { side: "SELL" }).map(i => i.rec.symbol), ["DLF", "HINDALCO"]);
  assert.deepStrictEqual(L.view(ROWS, { active: true }).map(i => i.rec.symbol), ["DLF", "LT", "SBIN", "INFY", "BEL"],
    "Active drops the target hit and the stop");
  assert.deepStrictEqual(L.view(ROWS, { score: true }).map(i => i.rec.symbol), ["LT", "SBIN", "BEL", "TATAMOTORS"]);
  assert.deepStrictEqual(L.view(ROWS, { lane: "classic", side: "BUY", score: true }).map(i => i.rec.symbol), ["BEL", "TATAMOTORS"]);
}

/* ── stored choices: a browser that throws on storage still works ─────── */
{
  const throwing = { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceededError"); } };
  assert.deepStrictEqual(L.loadPrefs(throwing), { filter: L.normFilter(null), chime: false });
  assert.strictEqual(L.savePrefs(throwing, { chime: true }), false, "a refused write is reported, not thrown");
  assert.deepStrictEqual(L.loadPrefs(null), { filter: L.normFilter(null), chime: false });
  const mem = new Map();
  const store = { getItem: k => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, String(v)) };
  assert.strictEqual(L.loadPrefs(store).chime, false, "the chime is off until the reader turns it on");
  assert.strictEqual(L.savePrefs(store, { filter: { lane: "select", side: "SELL" }, chime: true }), true);
  assert.deepStrictEqual(L.loadPrefs(store), { filter: { lane: "select", side: "SELL", active: false, score: false }, chime: true });
  mem.set(L.PREFS_KEY, "{not json");
  assert.deepStrictEqual(L.loadPrefs(store), { filter: L.normFilter(null), chime: false });
}

/* ── the chime, and the pace of polling ────────────────────────────────── */
{
  const seen = new Set(ROWS.slice(1).map(L.keyOf));
  assert.deepStrictEqual(L.unseen(seen, ROWS), [C5], "only the call that arrived after the first paint");
  assert.deepStrictEqual(L.unseen(new Set(ROWS.map(L.keyOf)), ROWS), []);
  assert.strictEqual(L.pollDelay(true, true), 15000);
  assert.strictEqual(L.pollDelay(true, false), 30000);
  assert.strictEqual(L.pollDelay(false, true), 30000);
}

/* ── the day's timeline ────────────────────────────────────────────────── */
{
  assert.strictEqual(L.tlPos("09:15"), 0);
  assert.strictEqual(L.tlPos("15:30"), 100);
  assert.strictEqual(L.tlPos("10:15"), 16);
  assert.strictEqual(L.tlPos("12:30"), 52);
  assert.strictEqual(L.tlPos("14:45"), 88);
  assert.strictEqual(L.tlPos("08:00"), 0, "before the open sits at the start");
  assert.strictEqual(L.tlPos("nope"), null);
  assert.strictEqual(L.tlNow(AT), 39.3, "11:42:30 is 147.5 of the session's 375 minutes");
  assert.strictEqual(L.tlNow(Date.parse("2026-11-27T08:59:00+05:30")), null, "no 'now' tick before the open");
  assert.strictEqual(L.tlNow(Date.parse("2026-11-27T16:00:00+05:30")), null, "or after the close");

  const pacing = { session: { key: "mid" }, slots: [
    { key: "open", label: "Opening", from: "09:25", to: "10:15", used: 1, cap: 3 },
    { key: "mid", label: "Mid-morning", from: "10:15", to: "12:30", used: 2, cap: 3 },
    { key: "pm", label: "Afternoon", from: "12:30", to: "14:45", used: 0, cap: 3 }] };
  const bands = L.tlBands(pacing, ROWS);
  assert.deepStrictEqual(bands.map(b => [b.key, b.left, b.width, b.used, b.cap, b.current]),
    [["open", 2.7, 13.3, 1, 3, false], ["mid", 16, 36, 2, 3, true], ["pm", 52, 36, 0, 3, false]]);
  // No pacing from the server: the default windows, slots counted from the rows.
  const guessed = L.tlBands(null, ROWS);
  assert.deepStrictEqual(guessed.map(b => [b.key, b.used]), [["open", 1], ["mid", 2], ["pm", 0]],
    "S1 (10:05, no window field) counted by its time, S2 and S3 by theirs");

  const dots = L.tlDots(ROWS);
  assert.strictEqual(dots.length, 8, "one mark per call, both lanes");
  assert.deepStrictEqual(dots.map(d => d.time), ["09:31", "09:47", "10:02", "10:05", "10:54", "11:12", "11:28", "11:36"], "oldest first");
  const bySym = s => dots.filter(d => d.symbol === s);
  assert.deepStrictEqual(bySym("BEL").map(d => [d.lane, d.star, d.tone]), [["classic", false, "t1"], ["select", true, "t1"]]);
  assert.strictEqual(bySym("TATAMOTORS")[0].tone, "won");
  assert.strictEqual(bySym("HINDALCO")[0].tone, "lost");
  assert.strictEqual(bySym("INFY")[0].tone, "open");
  assert.strictEqual(bySym("BEL")[0].label, "10:02 am, Buy BEL, Classic, half-book reached");
  assert.strictEqual(bySym("HINDALCO")[0].label, "9:47 am, Sell HINDALCO, Classic, stopped out");
  assert.strictEqual(bySym("SBIN")[0].label, "11:12 am, Buy SBIN, Select, live", "a label is read aloud: no star glyph in it");
  // A busy few minutes lifts marks onto the next level; a fourth goes back to the first.
  const busy = ["10:00", "10:02", "10:04", "10:05"].map((t, i) => ({ date: D, time: t, symbol: "S" + i, direction: "UP" }));
  assert.deepStrictEqual(L.tlDots(busy).map(d => d.stack), [0, 1, 2, 0]);
  // The other lane's row does not crowd this one.
  assert.deepStrictEqual(L.tlDots([busy[0], { ...busy[1], engine: "select" }]).map(d => d.stack), [0, 0]);
  assert.deepStrictEqual(L.tlHours().map(h => h.label), ["9:15", "10", "11", "12", "1", "2", "3", "3:30"]);
}

/* ── the radar: testing a level right now ──────────────────────────────── */
{
  const waiting = [
    { symbol: "ICICIBANK", dir: "UP", code: "volume", lane: "select", rvol: 1.6, need: 2.5, score: 64 },
    { symbol: "HDFCLIFE", dir: "DOWN", code: "vwap", lane: "classic", score: 58 },
    { symbol: "TATAPOWER", dir: "UP", code: "confirm", lane: "select", rvol: 2.9, need: 2.5, score: 77 },
    { symbol: "MARUTI", dir: "UP", code: "extended", lane: "select", score: 73 },
    { symbol: "JSWSTEEL", dir: "DOWN", code: "score", lane: "select", score: 68, need: 72 },
    { symbol: "COALINDIA", dir: "DOWN", code: "cap", lane: "select", score: 79 },
    { symbol: "AXISBANK", dir: "UP", code: "volume", lane: "classic", rvol: 1.9, need: 2.0, score: 70 },
    { symbol: "WIPRO", dir: "UP", code: "volume", lane: "select", rvol: 2.2, need: 2.5, score: 61 },
  ];
  assert.deepStrictEqual(L.radarSort(waiting).map(w => w.symbol),
    ["TATAPOWER", "COALINDIA", "JSWSTEEL", "WIPRO", "ICICIBANK", "AXISBANK", "MARUTI", "HDFCLIFE"],
    "as breakouts.status() ranks them: confirming, slots full, score, volume, then the deeper checks; " +
    "within volume, Select first and the nearer one first");
  assert.strictEqual(waiting[0].symbol, "ICICIBANK", "the server's list is not reordered in place");
  assert.deepStrictEqual(L.reason("confirm"), { code: "confirm", label: "Confirming", tone: "hl", rank: 0 });
  assert.strictEqual(L.reason("cap").tone, "warn");
  assert.strictEqual(L.reason("spent").label, "Already moved", "spent is a stock that has already run, not one already called");
  assert.strictEqual(L.reason("volume").tone, "info");
  assert.strictEqual(L.reason("score").tone, "info");
  assert.strictEqual(L.reason("sector").tone, "muted");
  assert.strictEqual(L.reason("book", "UP").label, "Sellers heavier");
  assert.strictEqual(L.reason("book", "DOWN").label, "Buyers heavier", "the order book reads the other way for a SELL");
  assert.strictEqual(L.reason("mystery").label, "Waiting", "a code this page does not know yet is still shown");
  assert.strictEqual(Math.round(L.pastLevel({ dir: "UP", level: 412.8, price: 413.6 }) * 100) / 100, 0.19);
  assert.strictEqual(Math.round(L.pastLevel({ dir: "DOWN", level: 902.3, price: 901.1 }) * 100) / 100, 0.13);
  assert.strictEqual(L.pastLevel({ dir: "UP", level: 0, price: 1 }), null);
  assert.strictEqual(L.radarSort(null).length, 0);
}

/* ── sectors ───────────────────────────────────────────────────────────── */
{
  assert.strictEqual(L.sectorShort("Automobile and Auto Components"), "Auto");
  assert.strictEqual(L.sectorShort("Fast Moving Consumer Goods"), "FMCG");
  assert.strictEqual(L.sectorShort("Oil Gas & Consumable Fuels"), "Oil & Gas");
  assert.strictEqual(L.sectorShort("Capital Goods"), "Capital goods", "the same words breakouts.SECTOR_SHORT uses");
  assert.strictEqual(L.sectorShort("Power"), "Power", "a short name stays as it is");
  assert.strictEqual(L.sectorShort(null), "");
  const tape = L.sectorTape([
    { sector: "Realty", pct: -0.62 }, { sector: "Power", pct: 0.2 }, { sector: "Information Technology", pct: 0.93 },
    { sector: "Metals & Mining", pct: -0.84 }, { sector: "Capital Goods", pct: 0.71 }, { sector: "Healthcare", pct: 0.12 },
    { sector: "Flat", pct: 0 }, { sector: "Broken", pct: null }]);
  assert.deepStrictEqual(tape.up.map(x => x.sector), ["Information Technology", "Capital Goods", "Power"]);
  assert.deepStrictEqual(tape.down.map(x => x.sector), ["Metals & Mining", "Realty"]);
}

/* ── the record: Classic against ★ Select ──────────────────────────────── */
{
  const classic = { intraday: { calls: 152, target: 44, stop: 63, closed: 45, profitable: 74, avg_pct: 0.11 },
                    consolidation: { calls: 62, target: 17, stop: 25, closed: 20, profitable: 30, avg_pct: 0.09 } };
  const r = L.record(classic);
  assert.deepStrictEqual([r.calls, r.target, r.stop, r.closed, r.profitable], [214, 61, 88, 65, 104]);
  assert.strictEqual(r.avg_pct, 0.1, "averaged per call, not per kind");
  assert.deepStrictEqual(r.split, { intraday: 152, consolidation: 62 });
  assert.strictEqual(L.record({ intraday: { calls: 0 }, consolidation: { calls: 0 } }), null, "no calls checked yet");
  assert.strictEqual(L.record({ calls: 5, target: 2, stop: 2, closed: 1, avg_pct: 0.2 }).calls, 5, "one flat summary passes through");
  assert.strictEqual(L.record(null), null);

  const both = L.lanesRecord({ calls: classic, calls_by_engine: { classic, select: { intraday: { calls: 4, target: 2, stop: 1, closed: 1, profitable: 3, avg_pct: 0.4 } } } });
  assert.strictEqual(both.classic.calls, 214);
  assert.strictEqual(both.select.calls, 4);
  assert.strictEqual(both.hasSelect, true);
  const old = L.lanesRecord({ calls: classic });
  assert.strictEqual(old.classic.calls, 214, "an older backend's `calls` is Classic's record");
  assert.strictEqual(old.select, null);
  assert.strictEqual(old.hasSelect, false);

  assert.deepStrictEqual(L.sessionRows({}), []);
  assert.deepStrictEqual(L.sessionRows({ engines: { classic: { by_window: { open: { trades: 0 } } } } }), [], "no closed trade anywhere: no table");
  const rows = L.sessionRows({ engines: {
    classic: { by_window: { early: { trades: 21, win_rate: 43 }, open: { trades: 68, win_rate: 51 }, mid: { trades: 74 } } },
    select: { by_window: { open: { trades: 10, win_rate: 60 }, pm: { trades: 5 } } } } });
  assert.deepStrictEqual(rows.map(r => r.key), ["early", "open", "mid", "pm"], "the three sessions, plus the opening minutes Classic traded in");
  assert.strictEqual(rows[1].select.win_rate, 60);
  assert.strictEqual(rows[2].select, null);
}

/* ── would Select's checks have helped Classic? ─────────────────────── */
{
  assert.deepStrictEqual(L.shadowRows({}), []);
  const rows = L.shadowRows({ by_shadow: {
    rpos: { failed: { trades: 31, win_rate: 39 }, passed: { trades: 183, win_rate: 52 } },
    extended: { failed: null, passed: null },
    pdh: { failed: { trades: 0 }, passed: { trades: 12, win_rate: 50 } },
    later: { failed: { trades: 2 }, passed: null } } });
  assert.deepStrictEqual(rows.map(r => r.code), ["rpos", "pdh", "later"], "checks with no trade either side are left out");
  assert.strictEqual(rows[0].label, "Not near the day’s extreme");
  assert.strictEqual(rows[1].failed, null);
  assert.strictEqual(rows[1].passed.trades, 12);
}

/* ── the owner's funnel ────────────────────────────────────────────────── */
{
  const f = L.funnel({ volume: 41, rpos: 12, cap: 2, zero: 0, newcheck: 5 });
  assert.deepStrictEqual(f.map(r => [r.code, r.n, r.w]), [["volume", 41, 100], ["rpos", 12, 29], ["newcheck", 5, 12], ["cap", 2, 5]]);
  assert.strictEqual(f[0].label, "Volume not there yet");
  assert.strictEqual(f[2].label, "newcheck", "a check this page does not know is shown by its code");
  assert.deepStrictEqual(L.funnel(null), []);
}

console.log("alerts-logic.test.js: all good");
