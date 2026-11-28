# Altaha Screener — Where Logic Meets Validations

Type any Indian (NSE main board, NSE SME or BSE) or US stock symbol. Get a 0–100 composite score built from a
validated technical engine (EMA structure, Hull MA, RSI, MACD, ADX, Supertrend, 52-week
position) and a fundamental engine (full 9-point Piotroski F-Score, ROCE, leverage,
growth, valuation). Every score expands into an audit trail: inputs → formula → points.
Every check teaches the concept in one plain-English line.

**Scores and evidence everywhere; calls in one place.** Stock pages, the scan, the
screener and the daily email show scores and evidence, never buy/sell directives.
The **portfolio review** is the exception: it gives every holding a rule-based call —
hold, trim, average down, add or exit — with stronger alternatives and industries to
move into (`backend/action_plan.py`). That was the owner's decision, taken knowing that
in India advice on someone's holdings is regulated by SEBI (Investment Advisers
Regulations) and stock recommendations are research (Research Analysts Regulations),
and that this project is not registered under either. The page says so in plain words
(`action_plan.DISCLAIMER`); keep that sentence true, and take legal advice before
charging for the calls.

---

## Three doors

Everything on the site sits behind one of three doors, each the answer to a
question somebody actually arrives with, plus a Me menu. Nothing was removed
when the doors replaced the old four menus: every tool still has its own tab
and its own address, in exactly one door.

| Door | The question it answers | What lives behind it |
|---|---|---|
| **Market** (`#discover`) | *What is happening today?* | A live overview — Nifty and the other indices, a three-month chart, FII/DII flows, every sector, the movers, headlines — then Alerts, Big trades, Order wins, Delivery trends, Results calendar, Filings & news, Options and the Market board |
| **Ideas** (`#research`) | *What should I look at?* | Stock picks for a week, a month, momentum and the long term — see [`research/IDEAS-STUDY.md`](research/IDEAS-STUDY.md) — then the Track record, the Screener, Investor styles (with the companies several styles agree on), the Forum ([`FORUM.md`](FORUM.md)), Who owns what and Fund houses, Charts, the Strategy lab ([`STRATEGY-LAB.md`](STRATEGY-LAB.md)) and Concalls |
| **Portfolio** (`#portfolio`) | *How am I doing, and what next?* | Your saved portfolio, the Watchlists, Your broker (connect Dhan or Zerodha, see funds, holdings and orders, and trade from any stock page — see [`BROKER.md`](BROKER.md)), the Portfolio review — see [`IC-REVIEW.md`](IC-REVIEW.md) — the Allocation plan ([`ALLOCATE-FLOW.md`](ALLOCATE-FLOW.md)), the Money planner (the month work becomes optional, and what moves it — see below), Advisors, and the Wealth desk for portfolio managers ([`WEALTH-DESK.md`](WEALTH-DESK.md)) |
| **Me** | Account, settings and learning | Sign in, Altaha Pro (plans and pricing: ₹5,000 a quarter or ₹15,000 a year), appearance, the watchlist, How the score works, the Glossary, Post drafts |

Each door opens on a page of its own (`frontend/doors.js`) that previews every
tool behind it with one live number or one line, and opens the tool on a tap.

**Each door has a menu.** On a screen wide enough to show the doors (above
1040px), resting the mouse on Market, Ideas or Portfolio opens one panel with
every tool behind that door: the door's question and a way to its own page on
the left (Market's also shows the indices as they stand), and the tools on the
right in named groups — *Live market*, *Money flow* and *Company news* behind
Market, for instance — each with an icon and its one-line hint. The tool that
is open is marked. The arrow beside each door opens the same menu for a
keyboard, a screen reader or a touch screen; the door's name still opens the
door's page. The groups are the `groups` list and each item's `g` on the door
map in `frontend/shell.js`.

Under the header, inside a tool, one line says where you are (*Market › Big
trades*, and what the tool is for) and carries the pin that puts the tool on
the desk on Market. On a door's own page that line is not shown. It replaced a
row of pills with the rest of the tools under **More**, which readers found
confusing.

**On a phone or a narrow window** (below 1040px) there are no doors in the
header to hang a menu from, so the same menu comes up as a sheet from the
bottom of the screen. The bar under the header is one button that says where
you are (*Portfolio › Watchlists*); it opens the sheet, which has the three
doors across its top and, under the one chosen, the door's own page and its
tools in the same groups with the same icons and hints. Any tool is two taps
from anywhere. The sheet closes on its cross, a tap or a pull on its handle,
a tap on the page behind it, Escape, or Android's Back button. It is built
by `sheetHTML` in `frontend/shell.js` from the same door map as the menus.

The first door was called *Today* and the third *My money* until Nov 2026.
Their ids were always `discover` and `portfolio`, so no address changed.

**One entry for one idea.** Two pairs in the Ideas menu were the same thing
listed twice, and each is one entry now:
- *Stock picks* was listed beside *Ideas*, whose own page leads with those
  picks. The full lists are still at `#research/ideas`, reached from the Ideas
  page's "See all" and from search; they are no longer a menu entry.
- *Convergence* (the companies several investor styles agree on) was listed
  beside *Investor styles*. It is a section of that page now, under the
  cards, at `#research/lenses/convergence`. The old `#research/convergence`
  addresses open the page at that section (`MOVED` in `frontend/nav.js`).

**The screener is two sections.** Two tabs sit under its title. *Pick what
you want* asks for no typing: ten cards for things a person might want from a
company — *Makes good money*, *Owes little*, *Not too pricey* — and six
ready-made ideas that switch a few of them on. Tapping a card runs it: the
count, a bar for each choice showing how it narrowed the list, and the table,
with no button to press. Each card has up to three settings, explained in
rupees on a hundred. *Make your own query* is the editor (examples, then
field, comparison, value and a text box); it was folded at the foot of the
cards as *Write your own rules* and is a section of its own now. The two are
one query: a choice writes its lines into the editor, a query typed or opened
from a link lights the cards it is made of, and one results table sits under
both. A query from a link, a saved screen or the last visit opens the editor
if any line is not a card's and the cards otherwise; nothing moves the reader
between sections while they work in one. The cards are `WISHES` in
`frontend/query.js`, and `backend/tests/test_query_wishes.py` puts every line
they can write through the server's parser. Every font size on the page is one
of the seven type tokens in `frontend/tokens.css` (see [THEME.md](THEME.md)).

**Built for the first visit.** People who were sent the site found it too
complex to find their way around, so three things changed (Nov 2026):
- Market opens with a *Start here* strip (`startHTML` in `doors.js`): one
  sentence on what the site does and three tasks: check a stock, get stock
  picks, check my portfolio. It stays hidden once the reader hides it.
- Ideas opens on the picks. It used to open on a picture of a planet.
- Less writing. Sixteen tool intros went from 452 words to 177.
- The door bars went from 9 and 13 pills to 5 and 6, plus More. They have
  since become the door menus above, and the sheet on a phone.
- A stock page shows its Altaha Score under the name; it used to be behind
  the Scores tab. The chip opens that section. One search box finds companies, tools and actions alike — "bulk"
finds Big trades, "pledge" finds the Screener — and opens with Ctrl+K or `/`.
On a phone the bottom bar is Market · Ideas · Search · Portfolio · Me.

`frontend/nav.js` holds the map and owns routing; `frontend/shell.js` renders
the header, the door menus, the door bar, search and Me from the same map. The section ids did
not change, and every address the site has ever published still resolves —
`#screener`, `#ideas`, `#planner`, `#portfolio`, `#social` and the
`#section/tab` pairs all land on the tool that now owns them.
`frontend/tests/nav-products-browser.cjs` asserts all of that in a real
browser, because none of it throws when it breaks. Every figure on the door
pages comes from an endpoint another view already uses; a sleeping feed blanks
its own card and nothing else. The motion (cards rising in, counts counting,
the chart drawing itself, the planets turning) stops for reduced motion and
the site's own motion switch, and `motion-off-browser.cjs` checks that nothing
is ever left invisible.

---

## Stock picks — five lists, tested

`#research` and `#research/ideas` (`backend/leaders.py`, `frontend/picks.js`).
The Ideas door opens on five tabs, with five setup tabs under them (see below): **This week**, **This month**, **After
results**, **Momentum** and **Long term**. Each shows what the list is in one
line, how it tested in three numbers, and the picks, each with up to four
reasons, a holding period and three prices: where it is, a target, and the
one price to leave at.

**How the panel reads.** The ten lists are two labelled rows of chips (*By
holding time*, *By chart setup*), each chip saying how long the list is held.
The three tested figures each carry a whole phrase ("of every 100 picks went
up", "average gain per pick, held about a month", "the market over the same
time"), and the first is also drawn as a bar. It replaced two unlabelled bars
of five tabs and a box of three numbers captioned in two words each.

**The target is a mark, not a rule.** A pick's target (`plan.aim` from
`leaders.plan`) is as far above the price as the exit line is below it. That
is the nearer of the two targets the study tested, and where it was tested
the page prints what selling there did, beside the picks: on the long-term
list, 64.9 of 100 picks ended up against 58.2, and the average fell from
+23.7% to +8.8%. The plan is still "hold, and leave below the exit line":
`plan.t1` stays empty, so the tracker and the call log close a call exactly
as before. Quick trades, which already say when to sell, carry no target.

| List | Hold | Exit line | Rose | Average | Nifty 500 | After costs |
|---|---|---|---|---|---|---|
| This week | 5 sessions | close 7% under | 52% | +0.4% | +0.3% | −0.1% |
| This month | 21 | close 12% under | 54% | +1.7% | +1.1% | +1.3% |
| After results | 21 | close 12% under | 54% | +1.8% | +1.0% | +1.3% |
| Momentum | 63 | close 15% under | 55.5% | +5.6% | +3.2% | +5.1% |
| Long term | 252 | close 30% under | 58% | +23.7% | +13.8% | +23.2% |

Tested on NSE's daily files for 2017–2026 (the results list from 2018, where
its filings start), delisted companies included, before tax; "after costs"
takes off a 0.49% round trip. The old list, replayed
the same way with its 8% stop: 38% rose and it did not beat the index. What was
wrong, what was tried, what was dropped and what the test does not show are in
[`research/IDEAS-STUDY.md`](research/IDEAS-STUDY.md).

**One stock, one list.** The lists as first built shared most of their names
(momentum and long term 12 of 15). Momentum now leaves out the long-term top
15, and this month buys a month's pullback in a market leader: about 46
different stocks in the 60 places, where it was 31. It cost this month and
momentum some of their average; all 20 trials are in
[`research/separation_lab.py`](research/separation_lab.py). A scan ranked
before a recipe changed still serves its lists after a deploy, without the
tested record, until the next scan (`leaders.RECIPE`).

**After results, younger companies, and what was tested and left out.**
*After results* ranks liquid companies on how their stock moved the day their
quarterly results were priced; it fills in the weeks companies report.
Companies listed six to twelve months are on the week and momentum lists,
ranked on six months of prices in place of twelve. Breakouts, RSI, MACD, ADX,
volume and a weak-market filter were each tested as a rule and none improved a
list, so each pick shows them as facts under a line saying they change no
rank, beside the result it was last priced on and any order it disclosed. All
of it is in [`research/signals_lab.py`](research/signals_lab.py) and the
study's "What a reader asked for, tested".

- **The page shows ten lists in two rows.** By holding period: This week,
  This month, After results, Momentum, Long term. By setup: Breakouts (a close
  above a tight 40-session base on twice the usual volume, with unbroken bases
  shown as *Setting up*), Technicals (seven of nine chart conditions), Quick
  trades (an oversold leader, sold on the first close above its 5-day
  average), Money flow (every NSE sector ranked on turnover share, breadth and
  its month; the strongest stocks in the top four) and Emerging (companies
  listed six to twelve months). Each prints its own replayed record. For a
  day the page was cut to two tabs (Short term, Long term); the ten were
  restored at the owner's request. The combined short-term list (a breakout
  passed through chart, industry, profit and results screens; 54 in 100 rose
  in the test) is still ranked and answers on `/ideas?horizon=short`, but has
  no tab.
- **A daily brief** (`brief.html`, `backend/policy_brief.py`,
  `GET /brief`) reads every new DGFT, RBI, SEBI and PIB circular for the
  sectors and stocks it touches: by Claude when `ANTHROPIC_API_KEY` is set,
  by a keyword table otherwise. It has no tested record and moves no rank.
- **The page prints only the study's numbers.** `research/ideas_study.py`
  writes them; `leaders.py` reads them; a test fails if the hold or exit line
  in the code differs from the one tested, and the study refuses to write
  anything unless the engine picks the same 810 stocks it did.
- **The lists stay fresh.** `.github/workflows/ideas.yml` runs the scan after
  each close, marks the tracker and attaches forward returns. It needs the
  `ALTAHA_ADMIN_KEY` repository secret.
- **A pick keeps its exit line.** The call log records it at the call and
  never redraws it.
- **No target.** A target sold the few large winners that carry each list.

The Altaha Score's three price pillars were re-weighted from the same data
([`SCORING-V4.md`](SCORING-V4.md)).

---

## The track record, the watchlists and the portfolio pulse

**Track record** (`#research/calls`, `backend/call_log.py`). The Ideas list is
rebuilt from the latest scan on every load, so on its own it cannot say when
an idea was generated. The record takes each scan's list once per horizon and
keeps every idea with the day, date, time (IST) and price it was generated at,
the stance and levels it carried, every change after (stance, redrawn levels)
and how the list closed it — stop, target, or dropped. Stops and targets are
judged against the levels a call carried *before* a new scan redrew them, so a
breached stop cannot be quietly moved. Each Universe scan row also carries a
stamp: "Called Mon 26 Oct · 10:40 IST at ₹101 · +4.9% since".

Every idea carries two returns. *Since the idea* runs from the price on the
day it was generated to the latest scan, as if it was bought that day and
nothing was done after; it is the figure the page leads with and averages, and
a closed call keeps one for as long as its stock is still scanned. Where the
list closed the call, the return at that close is shown beside it. With the
index's daily closes (the tracker's benchmark, read once a day off the request
thread) each idea also shows the index over the same days and the difference.

This is one page that used to be two. "Call log" dated the calls and "Track
record" (the Tracker tab) scored a separate ledger of ideas added by hand with
a Track button; both answered "what did the ideas do". The Tracker tab, its
script and the Track button are gone, `#research/tracker`, `#portfolio/tracker`
and `?go=tracker` open this page, and the share card (`/og/record.png`) and
the CSV (`/calls/export.csv`) are drawn from this record. `backend/tracker.py`
and its `/tracker/*` routes remain for the ledger already on disk
(`/tracker/export.csv`) and for the old lists' archetype record in
`ideas.py`; nothing in the interface adds to it any more.

**Watchlists** (`#portfolio/watchlists`, `frontend/watchlists.js`). Any number
of named lists with an emoji and a colour, renamed in place; live quotes for
the whole list in one request (`/watchlist/quotes`, cached, at most 25 new
names fetched per call); cards, a race and a heatmap; "since added" returns;
share links that open the list for anyone (`?go=watchlists&wl=…`); featured
lists everyone can see and copy (`/watchlist/featured`); and a daily game —
pick the stock you think ends the day highest, scored after the close. The
main list is still the one the ☆ Save button and the daily email use; the
other lists sync to the account through `/me/watchlists`.

**Holdings ledger** (`#portfolio`, `frontend/portfolio.js` section 3a). The
holdings editor is one line per stock under one header. Each line has a
coloured badge, the symbol with the company's name, and quantity and average
cost typed in place. After those come today's price, value, profit and a
30-session line, all from `/watchlist/quotes`. Above the list, a board shows
the portfolio's worth now, the amount invested, profit, today's move and an
allocation strip. The list sorts by size, return or A–Z, and the saved draft
keeps the order. Before, 21 holdings took about 2,300px on a laptop and 6,000px
on a phone; now they take 1,355px and 2,800px. A stock with no price shows a
dash and its invested amount, never an estimate. `portfolio-ledger-browser.cjs`
pins all of it.

**Portfolio pulse** (`backend/portfolio_pulse.py`). On the portfolio review:
which holdings are in profit and in loss, today's move, and a lean for each —
positive, mixed, negative or quiet — with every reason and its points.
Filings are read by category with the same table the Ideas list uses; press
counts only where its direction is verified. It is a tally of evidence, not a
forecast, and the page says so.

---

## Charts: a charting workspace

`#research/charts` (also `/?charts=RELIANCE`, and the `/share/chart/SYM` links)
is a full charting workspace on lightweight-charts 4.1.3. `frontend/charts.js`
loads two files: `charts-math.js`, every indicator and candle transform with no
DOM (tested by `charts-math.test.js` against pandas and `backend/engine.py`),
and `charts-workspace.js`, which builds the tab. They replace fifteen string
fragments that were joined and eval'd.

- **Timeframes** 1m to 1M. 3m, 30m, 2H and 1M are folded in the browser from the
  sizes `/chart` serves, never across a session close. Daily asks for `5Y`, so a
  reader can scroll back through all the history there is.
- **Chart types**: candles, hollow candles, Heikin Ashi, bars, line, step line,
  area, baseline.
- **Indicators**: forty-odd, any number of each, every input and colour
  editable, oscillators each in a pane of their own that can be resized. The
  catalogue is `INDICATORS` in `charts-math.js`: one entry says what an
  indicator is called, what it is tuned by and how it is drawn.
- **Drawing tools**: forty-four in seven flyouts on the rail (lines, channels
  and pitchforks, Fibonacci and Gann, chart patterns, forecast and measure,
  shapes, text and marks), with a weak or strong magnet, keep-drawing, lock
  all and hide all. Any drawing can be moved, reshaped, recoloured, restyled,
  extended, given text, locked, hidden, cloned, copied to another symbol, put
  in front or behind, and undone or redone. Drawings are anchored to time and
  price, so they hold across timeframes, and are kept per symbol in
  `localStorage` (`altaha.charts.v1.SYMBOL`, the key the old workspace used).
- **Also**: full screen (a fixed layer where the browser has no Fullscreen
  API, as on an iPhone), an object tree and data window, compare up to four
  symbols on a percent scale, log, percent and inverted scales, bar replay,
  price alerts on any horizontal line (a toast, and a browser notification if
  allowed), go to a date, range presets, a right-click menu, keyboard
  shortcuts (`?` lists them), and an image to download or copy.

`window.AltahaCharts.state()` reports what is on screen, for tests and for
anyone driving the chart from code. `frontend/tests/charts-browser.cjs` places
every tool and runs the rest on desktop and on a phone.

## Strategy lab — would a trading rule have beaten holding?

`#research/strategies` (`backend/strategy_lab.py`, `/strategies`,
`frontend/strategy-lab.js`). Pick any stock and eleven textbook rules run on
its own daily history: golden cross, the 200-day filter, MACD, twelve-month
momentum, RSI and Bollinger dips, a 20-day breakout, a trend with an ATR
trailing exit, and two volatility-sized rules. Each is measured by the six
numbers [quants.md](https://quants.md/) reports (return, CAGR, Sharpe,
worst fall, win rate, profit factor) and set beside buying and holding the
same stock.

What it adds for an Indian investor:
- **Costs:** 0.49% a round trip.
- **Tax:** an after-tax CAGR at today's short- and long-term capital gains
  rates.
- **Risk-free rate:** Sharpe measured above 6%, not 2%.
- **Consistency:** a two-halves check and every calendar year against
  holding.
- **A luck bar:** the Sharpe lead that the best of the few genuinely
  different rules would show by chance.

Rules decide at the close and fill at the next open; a test proves no rule
sees a later bar. Parameters are textbook and never fitted to the stock. The
report never says what a rule is doing today, because that would be a signal.
The Chart pane on every stock page links straight in. On the stocks tried so
far, no rule earned more than holding, and most had a shallower worst fall:
a smoother ride, not a richer one.

What quants.md is, what was taken from it, what was left out (bot building,
shorts, intraday, parameter optimisation) and why:
[`STRATEGY-LAB.md`](STRATEGY-LAB.md).

---

## Wealth desk — for portfolio managers

`wealth.html` (`backend/wealth.py`, `/wealth/*`, `frontend/wealth.js`).
Someone who manages other people's money signs in with their Altaha email
and sets up a desk once. From then on that account is a wealth manager's:

- **Every client's portfolio, live.** Value, profit, return, XIRR, today's
  move and a thirty-session chart, client by client and for the whole book.
- **Recommended beside bought.** Each holding shows the price the manager
  recommended next to the price the client actually bought at, the edge
  between them, and where the price sits between the call's stop and target.
  A call is made once and booked for many clients at once.
- **The commission, worked out.** Profit share, fixed fee, hard or soft
  hurdle, high-water mark, GST, on booked or total profit. Every step is shown
  with its formula, and a what-if slider sits beside it. Periods are settled,
  invoiced and marked paid, and the next period is measured from the last one.
- **Upload and edit.** A broker's holdings statement (`.xlsx` or CSV, from
  Groww, Zerodha and the rest) updates a client's portfolio. Stocks are
  matched by ISIN or name, every change is reviewed before it is saved, and
  the file is read in the browser, so the client's name and code never leave
  it. Any buying price, recommended price or ledger entry can be corrected.
- **For the meeting:** a privacy blur, a printable client statement, CSV
  exports.
- **For the client:** switched on per client, they sign in with their own
  email and see their portfolio read-only. They never see the manager's notes
  or anyone else's portfolio.

There is a sample desk anyone can open (`wealth.html?demo=1`). The engine,
every rule, the fee arithmetic, what is stored about a client and the SEBI
line on profit-sharing fees are all in [`WEALTH-DESK.md`](WEALTH-DESK.md).

---

## Advisors — talk to a person

`advisors.html` lists SEBI-registered investment advisers, registered research
analysts and well-known market educators, and lets any signed-in reader chat
with them about their portfolio, a stock, a fund, retirement or a career.
People register themselves; nobody is listed until the owner has checked the
registration number on SEBI's register (`advisors.html#admin`). Chats are free.

A call made in a chat is the adviser's, under their own registration — not
Altaha's. Educators are not registered, so a message from one that reads as a
buy or sell call is not sent; nobody may promise returns or move a reader to a
phone, a payment app or WhatsApp. A reader can show their saved portfolio to a
registered investment adviser and take it back at any time.

Everything — the three kinds and what each may do, what may be said, why it
polls instead of holding sockets, why there are no star ratings, and the
decisions paid chats would need — is in [`ADVISORS.md`](ADVISORS.md).

---

## Money planner — a date, not a form

The planner (`#portfolio/planner`) used to be fifteen empty boxes and a letter
grade that appeared once most of them were filled. It remembered nothing, so
nobody who finished it had a reason to come back.

It now opens with one answer: **the month your investments could pay your
bills**, after which working is a choice. Age, take-home, spending and what is
invested produce it. Everything else on the screen is a tool that moves that
date, and each is a reason to return:

| Tab | What it answers |
|---|---|
| **Your date** | The path year by year against the line it has to reach, and the moves that bring the date closer — tick any to see the date they would give together |
| **Price tag** | What a purchase or a monthly habit costs in working days and in days of freedom |
| **Goals** | Dated goals, paid from the same monthly saving: what each costs by then, what to set aside, and what it does to the date |
| **Check-in** | One figure a month: a streak, and whether you are ahead of your own plan or behind it |
| **Budget** | The itemised ledger, four health checks with their working, and the salary-day split — cushion, goals, the long run |
| **Tax** | Old regime against new |
| **Risk profile** | The questionnaire the Allocation plan also reads |

The model is compound interest in **today's rupees**, month by month: what is
invested grows at the assumed return less inflation, what is put away steps up
once a year, and the date is the first month the total reaches a multiple of a
year's spending. The defaults — 10% return, 6% inflation, 30× spending, saving
raised 5% a year — are dials on the page, labelled as assumptions rather than
forecasts. It recommends no product; it is arithmetic with the working shown.

**Nothing leaves the browser.** The numbers are kept in `localStorage` so the
page can greet somebody with their own date, and "Clear my numbers" removes
them. There is no request in `frontend/planner.js`, analytics carries which
tab was opened and never an amount, and the WhatsApp share text has the date
and two percentages in it and nothing else.

`frontend/planner-math.js` is the arithmetic and `frontend/planner-math.test.js`
pins it without a browser; `frontend/planner.js` is the screen and
`frontend/tests/planner-browser.cjs` drives it — the date on screen is the date
the arithmetic gives, a what-if never changes the saved plan, the three
salary-day figures add up to the rupee, a budget nobody itemised is not handed
a grade, and no typed figure appears in any request.

---

## The forum, the weekly brief and Pro pricing

- **The forum** (`forum.html`, under Ideas › *Talk it over*): discussions in
  seven categories, one of them a company at a time. Every stock page has a
  **Discussion** section listing that company's threads. Free to read; posting
  needs an account and a forum name. Tips (a price to trade at, a target, a
  stop-loss), promised returns and contact details are refused with the
  sentence that tripped the rule; three reports hide a post until the owner
  looks.
- **The weekly brief** (`weekly.html`): the week's market, FII/DII flows, the
  circulars that matter and the forum's busiest discussions, under the owner's
  own topics on any subject. Built every Saturday at 09:10 IST and mailed to
  daily-digest subscribers.
- **Pro pricing** (`pro.html`, also `/pricing`): ₹5,000 a quarter or ₹15,000 a
  year, still a founding list that charges nothing.

All three, where each sits and why: [`FORUM.md`](FORUM.md).

---

## The stock page — one company, nine sections

`frontend/stock.html`, `stock.js`, `stock.css`; `backend/stock_page.py`,
`backend/stock_news.py`, `announcements.for_company`.

The page had grown by addition: a name, a score chip, a strip of ten lens
badges, nine figures, a paragraph, and only then its own menu, whose first
section carried on down the same column. It showed three scores that did not
add up to each other, and a paragraph of method under most headings.

- **One bar, directly under the name:** Overview · Chart · Score · Ownership ·
  Financials · Peers · Delivery · News & filings · Discussion (the forum's
  threads about the company, read when the section is opened). Scrolled past the name, the
  bar carries the company's logo, symbol and price. A section is part of the
  address (`#peers`, or the older `?pane=owners`).
- **Switching sections moves nothing else.** The sections share a stage at
  least a screen tall, so the page cannot collapse under a reader who was deep
  in a long one; they land at the top of the new section with the bar still
  stuck. The company's name in the bar fades in at the bar's far end, so the
  tabs never shift, and a section arrives once, as a whole.
- **The Overview is cards**, each opening the section behind it: key figures
  with where each sits among peers, the year's price, the score's pillars, and
  the newest filings and headlines. The lenses are not on this page; they stay
  on the scanner.
- **Labels, figures and directions; no paragraphs.** A method note is a
  tooltip or it is gone.
- **Financials are drawn** (`/fundamentals?quarters=8`,
  `/fundamentals/position`). Three views: Income, Balance sheet, Cash flow.
  Each opens on a row of figures that are also buttons, every one with its
  change on the year and its own small trend line; the pressed one is charted
  as slim bars from zero against a scale of round figures, the latest in full
  colour, the period under the pointer read out above. Beside the chart is
  the second question: the two margins as lines on one scale; what funds the
  assets; how much operating cash was left after capital expenditure. Income
  ends on **where the money went**: revenue on the left, costs and EBITDA in
  the middle, every cost by name and the net profit on the right, the heights
  being the amounts. It is drawn only for an ordinary quarter (a profit, no
  negative cost, parts that come back to the whole); on a phone, and for any
  other quarter the split allows, one bar of ₹100 says it instead. Every line
  of the statement as filed is one tap away under "Full statement".
- **Three colours, each meaning one thing.** Blue is the size of the business
  (revenue, assets, operating cash), green is what is kept (profit, equity,
  free cash), orange is what is owed or spent (borrowings, capital
  expenditure); costs are grey. They are the first three steps of a palette
  checked for colour-blind separation on both card colours. A rise in a cost
  or in borrowings is marked as a rise, not as good news. Figures and card
  titles are set in the interface sans; the display serif is kept for the
  company's name and the section headings. The first version set numerals in
  the serif over fat tan bars, and was approved in a test browser that had
  web fonts blocked: previews now load the real fonts.
- **Ownership asks more than once** (`shareholding_filings.py`). The exchange
  refuses in bursts: a refused read is retried after a pause, the list of a
  company's filings is kept on disk so a restart does not need the exchange to
  answer first, an empty reply is believed for a minute (it used to be six
  hours) and never replaces a list already read, and once one document is
  refused the rest of that reading uses only what is already held. If nothing can be read, the quarters the scanner
  already stores are shown instead, marked "Stored copy", without the named
  holders; failing that the page asks once more itself and then offers "Try
  again".
- **One score, and its arithmetic.** The Score section prints what the engine
  did, from the payload it came from: each pillar's rank among peers, its
  weight, the points that makes, their sum, and the pull toward 50 for what
  could not be measured (`50 + (sum − 50) × confidence`). The three holding
  periods switch without a request. The older technical and fundamental checks
  are folded under "Other checks — not part of the score".
- **The word beside the score is the site's one scale** (`score_bands.py`,
  sent as `scoring.band`). The page used to cut at 72/55/40, which read
  "MIXED" for most of the market, because v4 scores bunch around 50.
- **A bank is not shown a debt-to-equity** or a ROCE, in its figures or among
  its peers. `/analyze` sends `business_model`.
- **Peers are named** (`GET /stock/peers`): the dozen companies nearest in
  market value in the same industry, every figure worked out one way from the
  stored filings and prices, sortable, with the peers' median. The medians
  table (`/fundamentals/peers`) sits under it.
- **News is two lists, filings a third, never merged** (`GET /stock/news`,
  `GET /stock/filings`). Company news is a news search by name, kept only
  where the headline names the company. Industry news is a search in the
  industry's own vocabulary, each headline tagged with the driver it mentions
  (a rate decision for a bank, crude for a refiner): keyword rules, printed in
  `stock_news.GROUPS`. Filings are the company's own, a year of them, from NSE;
  the first screen asks only for the ones already held (`held=1`), so opening
  a company is not a call to the exchange, and the year is read when the
  section is opened.
  Press never reaches a score. Both endpoints go out only for a company the
  server already knows (the scan, the stored profile, NSE's equity list), and
  the name searched is the server's own, never a request's. Searches are held
  for twenty minutes and filings for fifteen; three unanswered searches rest
  the search for five minutes and a refused exchange read rests it for two.
  The API must be able to reach `news.google.com`; when it cannot the page
  says the search was not answered, which is not the same as no news. The
  same section lists the company's bulk and block deals (`/deals/{ticker}`).
- **Logos** are the company's initials on a tinted tile, with its own mark over
  them when one loads at a usable size. For an NSE or BSE listing the browser
  first asks the image host the portfolio uses, keyed by symbol
  (`images.dhan.co/symbol/SYMBOL.png`), which has a mark for nearly every
  listed company whether or not a website is on file. Where it has none, and
  for a listing outside India (its symbols are Indian ones), the browser asks
  a favicon service for the company's website (the stored profile, else
  `stock_page.KNOWN_DOMAINS`). Both are asked with `no-referrer`; the API
  fetches no images. The search box in the header and the Market board's own
  list each company with the same mark, from the same host
  (`window.AltahaLogo`, `shell.js`).
- **Motion** is the tab marker sliding, a section fading in, bars growing to
  their value and the dial sweeping once. None of it runs under
  `prefers-reduced-motion`.

`backend/tests/make_stock_page_fixture.py` writes
`frontend/tests/fixtures/stock-page.json` from the real modules, and
`frontend/tests/stock-page-browser.cjs` reads it: the order of the page, the
points summing to the number on the dial, lazy loading, the bank's figures,
peer sorting, logo fallback, the marks in the search list, link safety, a switch from deep in one section to
the top of another, Ownership's second ask and stored copy, and a phone at
every section. `stock-fundamentals-browser.cjs` covers the drawn Financials.

## Company pages — one address per company, for search

`/stock-RELIANCE`, `/stocks` and `/sitemap.xml` (`backend/company_pages.py`,
the three routes after the share pages in `main.py`, `frontend/vercel.json`).

Every company used to be the same page: `stock.html` with the symbol in the
query string, an empty heading and a script that fetched the rest. A search
engine that asked for it was sent a title of "Stock — Altaha Screener" and no
words, so nobody could arrive by searching for a company.

- **`/stock-SYMBOL` is the stock page with the company already in it.** The
  API takes the deployed `stock.html` and writes in the title, the
  description, the canonical address, the heading, the last close, and one
  section at the foot: a paragraph, the filed figures, the last eight
  quarters and links to the twelve companies nearest it in size in its
  industry. The page's own scripts then draw the chart, the score and the
  panes as before. Two comments in `stock.html` (`ssr:head`, `ssr:glance`)
  mark where it writes; do not remove them.
- **`/stocks`** lists every company, A to Z, each linked to its page. The
  footer of every page links to it.
- **`/sitemap.xml`** lists the site's pages and one line per company.
  `robots.txt` names it.
- **Nothing leaves the machine for a page.** The figures are the query
  screener's snapshot row and the stored quarterly results. A crawler asking
  for every company costs lookups, not trips to NSE.
- **Why `/stock-SYMBOL` and not `/stock/SYMBOL`.** Every link and asset on the
  site is relative. One level down each is a 404, and the usual fix (a
  `<base>` tag) breaks `#` links and, in some browsers, the chart's gradient
  fills.
- **An empty snapshot is a 503, never a 404.** After a deploy the tables can
  be unread for a minute. "No such company" would tell a search engine that
  every page it had indexed was gone.
- **Quarters are on one accounting basis,** the one the snapshot row uses.
  No percentage is printed across a loss.
- **Figures, not advice.** The section states what the company filed and what
  the market paid. A test fails on any word that reads as an instruction.
- `/stock?ticker=SYMBOL` still works and is what the site's own links open.
  On the live site it names `/stock-SYMBOL` as its canonical address.

**Once, by hand, after this is live:** open
[Google Search Console](https://search.google.com/search-console), add
`altahascreener.in` as a property, verify it (a DNS record at the domain
registrar), then Sitemaps → enter `sitemap.xml` → Submit. Do the same in
[Bing Webmaster Tools](https://www.bing.com/webmasters). Search engines find
the pages without this, but slowly, and Search Console is the only place that
says which pages were indexed and which searches showed them.

**Check it is live:** `https://altahascreener.in/stock-RELIANCE` → View Source
(not Inspect) should show the company's name in `<title>` and `<h1>`.
`/sitemap.xml` should list one address per company. If `/stock-RELIANCE`
shows the figures with an "Open the chart…" link and no chart, the API could
not read `stock.html` from the site; it retries each minute.

`backend/tests/test_company_pages.py` and
`frontend/tests/company-page-browser.cjs` pin all of the above.

---

## Which companies are covered — NSE, NSE SME and BSE

The universe is four boards, about 5,450 companies (Nov 2026). Each is
labelled wherever it appears: the search boxes, the stock page and every scan row.

| Board | Where the list comes from | Key | Roughly |
|---|---|---|---|
| **NSE** (main board) | NSE's `EQUITY_L.csv`, series EQ | NSE symbol, `TCS` | 2,420 |
| **NSE SME** (Emerge) | NSE's `SME_EQUITY_L.csv`, series SM and ST | NSE symbol, `AAKAAR` | 580 |
| **BSE** (BSE only) | Dhan's instrument master, BSE equity shares whose ISIN is not on NSE | BSE scrip code, `500012` | 1,880 |
| **BSE SME** (BSE only) | the same, groups M, MT and MS | BSE scrip code, `534708` | 570 |

`backend/listings.py` holds the rules; the points that matter:

- **A company on both exchanges is covered once**, under its NSE symbol.
  NSE and BSE listings are matched by ISIN, so a dual listing is never added
  a second time.
- **A BSE-only company is keyed by its six-digit scrip code**, not BSE's
  short symbol. No NSE symbol is all digits, while seven BSE-only companies
  use a symbol NSE gives to a different company (BSE's ZEAL is Zeal Aqua,
  NSE's ZEAL is Zeal Global). The short symbol is kept beside the code, so
  you can search by either one or by the name.
  It is also what Yahoo knows the listing by (`ANDHRAPET.BO`; Yahoo has
  nothing under `500012.BO`). Dhan's BSE security id *is* the scrip code.
- **SME companies are scored, not picked.** They get the same 0–100 score as
  everything else, so a 70 means the same on either board. They are left out
  of the Ideas lists, breakout alerts and sector money flow, which read
  52-week highs and volume surges: on a stock that trades in lots of 1,200
  and can move 20% on a few trades, those signals mean the least. The
  scan ranks them in a list of their own (`/leaderboard?board=sme`).
  SME names may take at most 12% of the depth pass (`SCAN_SME_SHARE`).
- **SME companies report every six months.** The quarterly factors only
  accept a three-month period, so a half-year profit is never read as one
  quarter's. NSE files SME results and shareholding under `index=sme`.
  The results reader and the shareholding reader ask for that index, and
  never ask NSE about a BSE-only company.
- **Lots.** An SME share trades only in whole lots. The stock page says how
  many shares a lot is, and the order ticket and the server both refuse a
  quantity that is not a multiple of it.
- **BSE-only fundamentals** come from Yahoo (annual statements, through the
  Yahoo sweep of the fundamentals crawl), because those companies file with
  BSE, not NSE. Their quarterly XBRL factors and the holdings ledger are not
  filled for them yet.
- **The scan skips BSE groups Z and ZP** (companies BSE has flagged for not
  meeting listing or depository rules; `BSE_SCAN_SKIP_GROUPS`). They are
  still searchable and scored when someone opens one.
- **Cost.** One bulk quote call per segment drops the illiquid names before
  any history is read. Untraded BSE-only and SME names are dropped there
  too, so most of the 3,000 additions cost no request at all.

Switches: `UNIVERSE_SME=0` or `UNIVERSE_BSE=0` takes a board back out.
`GET /universe/status` shows what each list holds and how old the BSE list is.
The lists are saved to the data disk and read from the source once a day:
`listings_master.json` and `listings_nse_sme.json`.

---

## Folder map

```
altaha/
├── backend/          the scoring engine (Python / FastAPI)
│   ├── engine.py     all indicator math + scoring, fully commented
│   ├── main.py       the API server
│   ├── wealth.py     the Wealth desk: ledger, fees, high-water mark, book
│   └── requirements.txt
├── frontend/
│   ├── index.html    the whole website — one file, no build step
│   ├── wealth.html   the Wealth desk, for portfolio managers
│   ├── tokens.css    every colour, font and size ("Navy and Cognac", light and dark)
│   ├── theme.js      light or dark before first paint, and colours for charts
│   └── components.css  the one button, tab, table, card, chip and field
├── THEME.md          the design tokens and the rules for using them
└── README.md
```

**How it looks.** The visual system is documented in [THEME.md](THEME.md):
the palette, the seven text sizes, the components, and the check that keeps a
raw colour or font size out of the code (`node frontend/tools/check-theme.cjs`).

---

## Run it on your laptop first (10 minutes)

1. Install Python 3.11+ from python.org if you don't have it.
2. In a terminal:
   ```
   cd altaha/backend
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```
3. Open `frontend/index.html` in your browser (just double-click it).
4. Type `RELIANCE` and press Analyse. Done — it's talking to the engine on your machine.

---

## Put it on the internet, free (30 minutes, no credit card)

### Step 1 — Backend on Render
1. Create a free account at github.com. Create a new repository, upload the whole
   `altaha` folder.
2. Create a free account at render.com → **New → Web Service** → connect your GitHub repo.
3. Settings:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Set these environment variables** (Render → Environment). They are not
   optional on a 512 MB instance — without the first two the service will hit
   its memory limit and restart, which looks from the outside like the tabs
   being broken:

   | Variable | Value | Why |
   |---|---|---|
   | `MALLOC_ARENA_MAX` | `2` | glibc gives a threaded process up to 8 memory arenas **per CPU**. This app runs eight-plus threads. Measured on a scan-shaped workload: 93.2 MB unrestricted, 79.7 MB at 2. |
   | `WEB_CONCURRENCY` | `1` | One uvicorn worker. Two doubles the ~99 MB library floor (numpy + pandas + yfinance) before any data. |
   | `DATA_DIR` | `/data` | Must match the **mount path of your Render disk** (check Render → Disk; it cannot be changed after the disk is created). The tracker ledger, the point-in-time store and the Altaha Special delivery panels all live here and are otherwise rebuilt from nothing on every deploy. |
   | `ADMIN_KEY` | your own secret | Guards the control endpoints, and is the key that opens **Ask AI** on the query screener. |
   | `ANTHROPIC_API_KEY` | from console.anthropic.com | Optional. Switches on Ask AI on the query screener (Claude writes and checks queries; see FUNDAMENTALS.md) and the earnings-call summary. Billed per question; unset, both say they are off. |

   `render.yaml` in the repo root declares all of this — point Render at it as
   a Blueprint and it is applied for you.

5. Deploy. Render gives you a URL like `https://altaha-api.onrender.com`.
   Open `https://altaha-api.onrender.com/analyze?ticker=TCS` — if you see JSON, it's live.
   Then open `/health/memory`: it reports resident memory, the peak, the thread
   count, whether the arena cap is actually set, and which subsystem is holding
   what. Check it before assuming a slow site is a frontend problem.

### Step 2 — Frontend on Vercel or Netlify
1. Edit `frontend/index.html`: near the bottom, change
   `const API_BASE = "http://localhost:8000";`
   to your Render URL, e.g. `const API_BASE = "https://altaha-api.onrender.com";`
2. Create a free account at netlify.com → drag-and-drop the `frontend` folder onto the
   dashboard. That's it. You get `something.netlify.app` — rename it to
   `altaha-screener.netlify.app` in site settings.
3. Put the link in your Instagram bio.

### Free-tier honesty
- Render free tier sleeps after 15 min idle; first request after sleep takes ~30 s.
  The frontend already shows a friendly message for this. Upgrade ($7/mo) removes it.
- Data comes from Yahoo Finance via `yfinance` — free, unofficial, fine for launch.
  If traffic grows, swap in your Dhan/Fyers feed for India and Polygon for US — the
  engine only needs OHLCV + statements, so only `main.py` changes.

---

### Money flow

**Market › Money flow** shows where institutional money is moving: NSDL's
fortnightly FPI flow by sector as a heatmap, NSE's daily FII and DII figures,
each sector's eight-week rotation against the Nifty 50 (which plays), and the
sectors ranked on a **Sector Money Flow Score** out of 100 (FPI flow 40,
rotation 35, breadth 25). A sector opens into the stocks being accumulated
inside it: delivery against its own usual, volume, and bulk and block deals.

It is a ranking of published data, not a forecast, and it changes no Altaha
Score. A stock page and an Ideas pick print their sector's rank as context.

The page is empty until two years of history are read once:

```bash
python backend/backfill_money_flow.py --api https://taha-project.onrender.com --key "$ADMIN_KEY"
```

After that `.github/workflows/money-flow.yml` reads each evening's files. It
needs `ALTAHA_ADMIN_KEY`, like the other jobs. Optional settings on Render:
`MONEYFLOW_WEIGHTS` (the three weights), `IDEAS_MONEYFLOW_CAPS=on` (let the
score set how many names an Ideas list takes from one sector; off by default)
and `MONEYFLOW_TELEGRAM=off` (silence the sector alert).

[MONEY-FLOW.md](MONEY-FLOW.md) has the sources, the NSDL-to-NSE-index mapping
with every judgement in it named, the arithmetic, and what is missing.

### Delivery trends

`/delivery/trends` is what the **Delivery trends** tab opens on: where delivery
is running above a stock's own normal. Three lists, each a stock compared only
with itself, on the same panel as everything else in `backend/special.py`:

| List | Rule |
|---|---|
| **Spikes today** | The latest session delivered at least 2x the rupees of its usual day (median of the 20 sessions before), with the delivered share of volume at or above its own average |
| **Building all week** | The median day of the last 5 sessions delivered at least 1.5x the usual day of the 20 before them, so one loud session cannot qualify |
| **Quiet build-up** | Delivered share at least 5 points higher over 20 sessions than over the 60 before, on more rupees, with the price within 6% of where it started |

Above them, the market's own delivered share against its 20-session average;
below, the same week-against-usual comparison by industry, for the companies in
`nse_industries.csv`.

The multiple is on delivered **rupees**, not shares, so a split or bonus does
not read as a spike, and a name whose unadjusted price shows one inside the
window is left out and counted. The liquidity floor (Rs 2, 10 or 50 crore a
day) is measured on the sessions *before* the spike, so a spike cannot qualify
itself.

None of the thresholds was fitted to returns, and the tab does not claim an
edge: the page carries the caveats that a delivered share has a seller as well
as a buyer, that F&O expiry and block deals lift delivery for reasons that are
no view on the company, and that this repo's own test found the delivery
signal faded after 2023. It is a list of where to look.

The one-year Altaha Special ranking (`/special`) used to be the whole tab. It
skips the most recent month by design, so it could not show anything about
this week; it is now folded away beneath the lists and fetched only when
opened. `test_delivery_trends.py` pins the arithmetic,
`frontend/tests/delivery-trends-browser.cjs` the page.

### Delivery, per company

`/delivery?ticker=SYM` returns the delivered share of each session's volume for
one stock, and the Delivery pane on `stock.html` renders it. NSE publishes the
figure per stock per day in the full bhavcopy and no OHLCV feed carries it,
which is the same disclosure the Altaha Special book is ranked on — both read
the one panel in `backend/special.py`, so the book and the stock page can never
quote different numbers for the same session.

The store holds **every EQ symbol the bhavcopy lists** — about 2,665 a session,
not the ~820 that clear the book's turnover floor. It used to keep only the
liquid ones, on an argument inherited from the v2 long-format cache where the
saving was real; against wide float32 panels it was discarding roughly 1,845
companies to save some 11 MB on a 512 MB instance, and those are exactly the
small and mid caps somebody opens a screener to look up. The BOOK is narrowed
instead, at rank time, by `_rank_cols` — which matters more than it sounds,
because `_components` uses the cross-sectional median of the panel as its
market proxy, so a wider file would otherwise have re-scored every name in the
Altaha Special book. `test_store_the_whole_exchange.py` pins that: same names,
same order, same scores to floating-point equality, wide file or narrow.

Sessions stored before the widening carry only the liquid names. They are
detected per date by their coverage and handed back to the builder as if they
were missing, so the history backfills itself and an interrupted backfill
resumes; `/special/status` reports how many days are left as `backfilling`. A
company whose history is still filling says so on the page rather than
presenting a short average as a considered one.

The delivered QUANTITY is derived — traded quantity multiplied by the published share —
because storing NSE's `DELIV_QTY` would be a seventh float32 panel on a 512 MB
instance for a column that is the product of two already held. The percentage
is the exchange's own figure; the quantity carries that percentage's rounding,
and the page says so.

---

### Backups, and five years of NSE bhavcopy

Both live in one private Cloudflare R2 bucket, configured by the four `R2_*`
variables on Render. Both are run by the API (which holds the keys) and asked
for by a GitHub workflow (which needs only `ALTAHA_ADMIN_KEY`).

**The data disk, daily** (`backend/backup.py`, `.github/workflows/backup.yml`).
Every database and data file on the disk goes to `daily/YYYY-MM-DD/`, and 30 days
are kept. Each database is snapshotted with SQLite's backup API, so a copy taken
while something is writing still opens. The temporary copies are made **off the
data disk** whenever the instance has room elsewhere, and never in a folder held
in memory. From 8 to 13 November 2026 they were made on the 1 GB disk itself, and
every night the two largest databases failed with "disk is full". The job's log
now shows where each copy was made and how full the disk is. It warns at 85%.

**Every daily bhavcopy, five years back** (`backend/bhav_archive.py`,
`.github/workflows/bhavcopy.yml`). For each session the archive keeps NSE's
bhavcopy exactly as published (`bhavcopy/cm/YYYY/YYYYMMDD.csv.zip`), which has
ISIN, OHLC, previous close, volume and value for every security. It also keeps
`sec_bhavdata_full` (`bhavcopy/full/…csv.gz`), which adds delivery. The
workflow runs on weekday evenings after the close and fetches in slices until
nothing is missing. The first run backfills five years, and each run after
that adds the day. Days with no file (weekends, holidays) are recorded in
`bhavcopy/absent.json` and asked for only once. A refusal or timeout is never
recorded as a holiday. `bhav_archive.read(day)` returns any stored session as
one table, whichever of NSE's two formats it came in. The format changed on
8 July 2024. Prices are unadjusted for splits and bonuses, as NSE publishes
them. `GET /admin/bhavcopy` reports how many sessions the archive holds, their
span, their size and what is left to fetch. Nothing is written to the data
disk.

### The session that just closed, and trading holidays

**A price history never goes back a session** (`backend/settled_bars.py`).
After midnight in India the index feed's daily history ends on the session
*before* the one that just closed, and has it back by late morning. On the
night of 23 November 2026 `/market` read Friday's close and Friday's move from
00:07 IST. The last three settled sessions of every history fetched are now
kept, in memory and in `settled_bars.json` on the data disk, and put back when
a later fetch comes without them. The feed's own bar wins as soon as it
carries the session again, so a correction still lands. A kept bar is trusted
for four days. `/chart` names any session it put back in `kept_sessions`;
on most calls that is empty. What it cannot do: a symbol nobody asked for
between 16:00 IST and the feed going back has nothing kept.

Stocks had a second cause. Dhan's daily history was asked for up to the
server's date, which in UTC is still yesterday until 05:30 IST, and Dhan's
`toDate` is the first day not returned. It is asked by India's date now
(`dhan_source._india_today`).

**The site knows a trading holiday** (`backend/market_calendar.py`). The
holiday list is NSE's own, read twice a day and kept in `nse_holidays.json` on
the data disk. On a holiday `/market` answers `"status": "closed"` with the
day's name in `holiday`, no bar is built for the day, and the watchlist does
not call the market open. `/datasource` shows how many holidays are held and
when the list was last read. A special session on a listed holiday (Muhurat
trading) or on a weekend still reads as closed. The intraday scanner
(`intraday.market_open`) still goes by the weekday clock alone.

---

### "Explain this score" — plain English, free (optional)

Every scored stock page (`stock.html`) has a floating **Smart AI** button,
bottom right. It opens a small panel over the page that offers one question —
*"What does this score mean, in simple words?"* When a reader asks it,
`/explain?ticker=SYM&horizon=position` hands the numbers the
engine already computed — score, pillars, what helped, what hurt, the checks,
the ratios — to OpenAI's open-weight `gpt-oss-120b` on **Groq's free tier**,
and shows back three short paragraphs labelled as AI-written. The model sees
nothing else: not the news, and not the levels or observation plan, which it
would turn into entry and exit talk. Code: `backend/score_explain.py`.

**To switch it on:** create a free account at console.groq.com (no card),
create an API key, and add it in the Render dashboard → Environment as
`GROQ_API_KEY`. Unset, the section says it is off and nothing is called.

**Staying inside the free allowance** (about 200,000 tokens a day, roughly a
hundred fresh explanations):
- One explanation per stock, per horizon, per IST day, stored in
  `$DATA_DIR/explanations.db`. Every later reader that day costs nothing.
- The service stops at `EXPLAIN_DAILY_TOKENS` (default 180,000) — before the
  provider starts refusing — and says so on the page.
- One visitor can cause at most `EXPLAIN_PER_VISITOR` (default 15) fresh
  explanations a day, so a single person cannot spend everyone's allowance.
- `EXPLAIN_MODEL` swaps the model without a code change.

**The SEBI line holds here too.** The prompt forbids advice, and every reply is
checked again before it is shown: one that reads as a buy/sell call, target,
stop-loss or recommendation is withheld, not shown with a warning.
`backend/tests/test_score_explain.py` and
`frontend/tests/stock-explain-browser.cjs` pin all of the above.

### Alerts on Telegram — intraday breakouts, up and down

The **Alerts** page (Market → Alerts) and your Telegram get one kind of alert: a
liquid stock breaking a level *now*, as a day trade — entry, stop, half-off
point and target. Code: `backend/breakouts.py` (the rules) and
`backend/intraday.py` (the loop, the log and the record).

- **Levels.** After each close the universe scan reads every liquid stock's
  daily bars (no extra data calls) and keeps, for the 400 most-traded:
  yesterday's high and low, the 20-day and 52-week extremes, and the top and
  bottom of a base (40+ sessions inside 18%, or 120+ inside 25%). The session
  adds two of its own: the opening range (first 15 minutes) and a tight
  intraday range (40 minutes inside a third of the daily ATR).
- **Live.** One Dhan bulk quote every 20 seconds covers all 400. An alert
  fires only when the cross is fresh (the price was on the other side minutes
  ago — not a gap, not yesterday's break), the last five minutes traded 2× the
  stock's usual volume for that time of day, the price is on the right side of
  VWAP, the stop is 0.4–1.5% away, the next level is at least one risk away,
  and the index is not running hard the other way. One alert per stock per
  direction per day, 09:20–15:00, at most 15 a day, best score first.
- **The trade.** Stop just back inside the level (or the far side of the
  tight range); target two risks away; book half at one risk; flat by 15:15.
- **Two kinds of call.** Each alert is tagged `CONSOLIDATION` (it broke out of
  a base, or of a tight 40-minute range) or `INTRADAY` (every other level).
  Telegram and the page show them in plain words: Buy at / Stop loss / Target,
  and one sentence of why. No scores or ratios.
- **The record.** After the close every call is checked on 5-minute bars —
  hit the target, hit the stop loss, or closed at 3:15 pm — and Telegram gets
  the day's calls with each one's profit or loss in percent. The page shows
  the same counts and the average result per call, for each kind. **This is
  what decides whether it makes money:** nothing here was backtested on
  intraday history, so trade small for a few weeks and watch that record.

**Needs:** Dhan's Data API subscription (live quotes and daily bars) and
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` on Render. **Test alert** on the page
sends a sample card. If the levels are missing on a trading morning (first day
after a deploy, a scan that failed) they are rebuilt from Dhan automatically.

**The join button.** The Alerts page shows visitors a "Get alerts on
Telegram" button once the public channel is set: create a public channel in
Telegram, add your bot as an administrator, and set
`TELEGRAM_PUBLIC_CHAT_ID=@yourchannel` on Render (or `TELEGRAM_CHANNEL_URL`
for a private channel's invite link). The channel receives each call
facts-only — the stock, what it crossed, on what volume — without buy/sell,
stop loss or target; the full call goes to `TELEGRAM_CHAT_ID` only. The
owner's controls on the page appear after pressing "Owner" at the foot of the
page and entering the admin key.

**Tuning, without a redeploy** (Render → Environment): `BO_SURGE` (volume
burst, default 2.0), `BO_MIN_SCORE` (50), `BO_MAX_RISK` / `BO_MIN_RISK` (1.5 /
0.4 %), `BO_RR` (target in risks, 2), `BO_SHORTS=0` (longs only),
`BO_UNIVERSE` (400), `BO_MIN_TURNOVER_CR` (15), `MAX_ALERTS_DAY` (15),
`POLL_SECONDS` (20), `BO_END_MIN` (345 = 15:00). `BREAKOUT_ALERTS=0` turns it
off. The older volume-spike signals are off; `VOLUME_ALERTS=1` brings them
back. `GET /breakouts/status` and `GET /intraday/diag` say why it is quiet.

## Where the accuracy lives (read before you market it)

- "Accuracy" here means: textbook-correct indicator formulas (validated against
  synthetic trends in testing), real exchange data, and full transparency — every user
  can audit every point. It does **not** mean prediction. Never market it as predicting
  prices.
- Fundamental data on yfinance can be sparse for small/mid-cap NSE names. The engine
  detects this and falls back to technical-only scoring with a clear label rather than
  showing a misleading zero.
- Tune the scoring weights in `engine.py` — they're plainly commented. If you change
  them, the audit trail updates automatically because formulas are stored with each check.
