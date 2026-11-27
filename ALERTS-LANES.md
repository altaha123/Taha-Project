# Live alerts: two lanes

The intraday alerts now run as **two lanes on the same live prices**. Nothing you
already had was taken away.

| | **Classic** | **★ Select** |
|---|---|---|
| What it is | Today's breakout alerts, unchanged | Fewer, stronger calls, spread across the day |
| How many | Up to 15 a day | Up to 8 a day: 3 in the opening hour, 3 mid-morning, 3 in the afternoon |
| When | 9:20 am to 3:00 pm | 9:25 am to 2:45 pm |
| Fires | On the first quote that breaks the level | Only if the break still holds 20 seconds later |
| Settings | `BO_*` | `BOS_*` |

Both lanes read the same quote request every 20 seconds, so the second lane costs
no extra Dhan calls. Each lane keeps its own record, so after a few weeks the
numbers show which one makes more money.

## What you will see

**Telegram (your private chat)**
- A Classic call arrives exactly as before.
- If ★ Select confirms the same break a few seconds later, you get a short extra
  line: "★ Select confirms the 10:02 am call". That means both systems agree,
  and it is one of the day's strongest setups.
- A ★ Select call on its own (for example a midday setup Classic does not have)
  arrives as a full card with a ★ Select line.
- Optional follow-ups when a call reaches half-book (move the stop loss to cost),
  hits its target or hits its stop loss. Off by default: set `ALERT_UPDATES_TG`.

**Telegram (public channel)**: facts only, as before. No buy or sell, no
entry, stop or target. A break both lanes called is posted once, not twice.

**The Alerts page**
- Each call card shows its score, its setup ("Base breakout", "Fresh day high",
  "VWAP reclaim"…), volume, sector and lane, the half-book level, and a live
  status: `LIVE · ₹418.40 (+1.0%)`, `T1 HIT · Move SL to cost`, `TARGET HIT ✓`
  or `STOPPED OUT ✕`.
- A day timeline shows when each call fired, so you can see the calls spread out.
- "Testing a level right now" lists stocks at a breakout level this minute and
  what they still need ("confirming 1/2", "volume 1.9x, needs 2.5x").
- Filters: All · ★ Select · Classic · Active · BUY · SELL · Score 75+.
- The record compares Classic and ★ Select side by side.

## How ★ Select decides

On top of everything Classic checks:

1. **The break must hold.** A wick through the level at 9:31 that falls back
   20 seconds later is not a call.
2. **Volume against the stock's own habits.** "3x normal volume" is measured
   against what *this* stock trades at this time of day over its last five
   sessions, not one curve for every stock. Open-heavy stocks stop looking
   exciting every morning, and afternoon volume is judged fairly.
3. **Quality checks.**
   - It sits near the top of the day's range (the bottom, for a sell).
   - It is not stretched more than about 1.6% past VWAP.
   - It is not buying into a wall of sell orders.
   - Its sector is not falling against it.
   - Yesterday's high on its own needs extra volume.
4. **Sector and money flow count in the score.** A sector moving with the call,
   and money flowing into it, add points.
5. **Two setups the day makes later on.** These keep the afternoon alive:
   - **Fresh day high.** The day's high has stood for 30+ minutes, the pause
     held above VWAP, and the stock now breaks out on volume.
   - **VWAP reclaim.** A stock trending with the day pulls back to VWAP, holds
     it, and breaks its 15-minute high.
6. **A budget.** The 9:30 rush can use at most 3 calls. There are 2 calls at
   most at once and 2 per sector, and within one moment only the sector's
   leader goes.

## What got more reliable (both lanes)

- **Live results.** Every call's price, profit or loss, best and worst point and
  half-book hit are tracked every 20 seconds from the live price. The 4 pm
  check against 5-minute candles still has the final word.
- **Restarts.** The session's memory is saved every 3 minutes
  (`breakout_day.npz`), so a redeploy carries on where it was. An opening range
  missed by a late start is rebuilt from 5-minute candles in the background.
- **History.** The alert log no longer drops old rows. Older days move to
  `signal_log_archive.jsonl`, and the file is written safely, so a crash
  mid-write cannot wipe it.
- **Sectors** are filled in even when the morning had to rebuild the levels.
- **Volume clock.** The older volume curve read five minutes ahead and made
  mornings look busier than they were. Fixed.

## Judging the two lanes

`/intraday/stats` now has:

- `calls_by_engine`: Classic vs ★ Select in plain counts and average % per call.
- `engines.<lane>.by_setup`, `by_window` (opening / mid-morning / afternoon) and
  `by_direction`: win rate, expectancy, and average best and worst point.
- `by_shadow`: every Classic call records which ★ Select filters it would have
  failed. This shows, from Classic's own trades, whether each filter actually
  removes losers.

Under about 30 closed calls a row is noise. After that, switch off what loses.

## Settings

Change these on Render. No redeploy needed.

**Turning lanes on and off**

| Variable | Default | What it does |
|---|---|---|
| `BO_LANES` | `classic,select` | `classic` keeps only today's alerts. `select` keeps only ★ Select |
| `TELEGRAM_PUBLIC_LANES` | `classic,select` | Which lanes the public channel posts. `select` posts only ★ calls |
| `ALERT_UPDATES_TG` | `off` | Follow-ups in your private chat: `target`, `t1` (half-book + target) or `all` (also stops) |
| `MAX_ALERTS_DAY` | `15` | Classic's daily cap, as before |

**★ Select** (each `BOS_*` falls back to the Classic value where noted)

| Variable | Default | |
|---|---|---|
| `BOS_MAX_DAY` | 8 | Calls a day |
| `BOS_SLOT_OPEN` / `BOS_SLOT_MID` / `BOS_SLOT_PM` | 3 / 3 / 3 | Calls per session window |
| `BOS_MAX_PER_PASS` | 2 | Calls at the same moment |
| `BOS_MAX_PER_SECTOR` / `BOS_MAX_PER_SECTOR_PASS` | 2 / 1 | Per sector a day, and at the same moment |
| `BOS_START_MIN` / `BOS_END_MIN` | 10 / 330 | Minutes after 9:15: 9:25 am to 2:45 pm |
| `BOS_CONFIRM_PASSES` | 2 | Passes the break must hold |
| `BOS_SURGE` | 2.5 | Last-5-minute volume vs the stock's usual |
| `BOS_MIN_SCORE` | 66 | Score needed, 0–100 |
| `BOS_UNIVERSE` | 250 | The most-traded stocks it watches |
| `BOS_MIN_RPOS` | 0.72 | Share of the day's range below the price |
| `BOS_MAX_VWAP_EXT` | 1.6 | Most % past VWAP |
| `BOS_MAX_BOOK_AGAINST` / `BOS_BOOK_REJECT` | 3.0 / 6.0 | Sell orders vs buy orders: points off, then refused |
| `BOS_SECTOR_AGAINST` | 0.6 | Sector % against the call that holds it |
| `BOS_PDH_SURGE` / `BOS_PDH_PACE` | 3.0 / 1.1 | Extra volume for a plain yesterday's-high break |
| `BOS_HOD` / `BOS_VWAP` | on / on | The two day-made setups |
| `BOS_MONEY_FLOW` | on | ±5 for the sector's money-flow quadrant |
| `BOS_REENTRY` | on | A second call later in the day, only on a new day-made setup |
| `BOS_MIN_RISK`, `BOS_MAX_RISK`, `BOS_RR`, `BOS_CHASE_MIN`, `BOS_CHASE_PCT`, `BOS_BUFFER_PCT`, `BOS_REGIME`, `BOS_SHORTS` | Classic's | Set only to differ from Classic |

**The two day-made setups** (whichever lane uses them)

| Variable | Default | |
|---|---|---|
| `BO_HOD_FROM_MIN` / `BO_HOD_PAUSE_MIN` | 75 / 30 | From 10:30 am; the old high must have stood 30 minutes |
| `BO_VWAP_FROM_MIN` / `BO_VWAP_TO_MIN` | 45 / 315 | 10:00 am to 2:30 pm |
| `BO_VWAP_TREND` / `BO_VWAP_TOUCH` / `BO_VWAP_HOLD` | 0.8 / 0.35 / 0.15 | Up 0.8% on the day; came within 0.35% of VWAP; never more than 0.15% through it |
| `BO_VWAP_STOP` | 0.25 | Stop this % across VWAP |

**Classic can borrow any ★ Select idea.** Every Select setting also exists for
Classic under `BO_*`, switched off: `BO_CONFIRM_PASSES=2` makes Classic wait for
the break to hold, `BO_USE_PROFILE=1` gives it the per-stock volume profiles,
and so on.

**Plumbing**

| Variable | Default | |
|---|---|---|
| `BO_TAPE` | 1200 | Passes of tape kept: the whole session |
| `BO_CHECKPOINT_SEC` | 180 | How often the session's memory is saved (0 = never) |
| `BO_RESTORE_GAP_MIN` | 10 | After a longer blind gap, breaks already under way are treated as old news |
| `BO_PROFILE_MAX_AGE` | 7 | Days a stock's volume profile stays usable |
| `ALERT_HOT_DAYS` | 60 | Days kept in `signal_log.json`; older days move to the archive |
| `LIVE_SAVE_SEC` | 120 | How often live prices are written to the log between events |
