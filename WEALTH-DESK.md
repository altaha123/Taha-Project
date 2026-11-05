# Wealth desk — for portfolio managers

`wealth.html`. Somebody who looks after other people's money signs in with
their usual Altaha email, sets up a desk once, and from then on that account
is a wealth manager's. Every client's portfolio is live. The price each stock
was **recommended** at sits beside the price the client **bought** at. Where
the arrangement is a share of the profits, the commission is worked out step
by step, settled and tracked until it is paid.

It replaces the spreadsheet most managers keep: one tab per client, a column
for the recommended price, another for the buying price, and a formula for the
fee that is never quite right after a bad quarter.

Code: `backend/wealth.py` (every rule, all the arithmetic, every statement),
`backend/wealth_routes.py` (HTTP only), `frontend/wealth.html`,
`frontend/wealth.js`, `frontend/wealth.css`. Tests:
`backend/tests/test_wealth.py`, `frontend/tests/wealth-browser.cjs`, fixture
from `backend/tests/make_wealth_fixture.py`.

## What it looks like from outside

**Signed out:** what the desk does, a sign-in that comes back here
(`signin.html?next=wealth.html`), and **a sample desk** (`wealth.html?demo=1`).
The sample has five invented clients built around today's prices, so every
screen can be tried with no account. Nothing on it is saved.

**First time signed in:** two steps. *About you* asks for a name, a firm and a
registration (PMS `INP…`, RIA `INA…`, RA `INH…`, AMFI `ARN-…`, or none).
*How you charge* sets the default terms, with a live line: "on a client's
₹10,00,000 that makes 15% in a year, you earn ₹X". Then the first client.

**The desk**, five tabs:

| Tab | What it answers |
|---|---|
| **Overview** | The book's value and today's move, a thirty-session chart, profit since the start, commission accrued, collected this financial year; a list of what needs attention (fees overdue, invoices unpaid, calls at target or stop, clients below the high-water mark, one stock over 30% of a client, idle cash, holdings with no price); the largest clients; what the book holds across clients, and by sector |
| **Clients** | Every client as a card: value, return, today, a sparkline, commission accrued or the gap to the high-water mark. Search, filter by status, sort |
| **A client** | Value, profit, return, XIRR, today; holdings with **recommended / bought at / edge / price / P&L / weight / stop→target**; the ledger; the fee with its working and a what-if; their profile and terms; a printable statement |
| **Recommendations** | Each call: stock, price, target, stop, horizon, why; where the price sits between stop and target; which clients were booked on it, their average fill against the call; a scorecard |
| **Commission** | Accrued now, billed and awaiting payment, collected this year; twelve months billed vs received; what the book would accrue if every price moved ±5–20%; each client's current period; every invoice, marked paid in one click |
| **Desk** | Profile and default terms, privacy, hand-set prices, CSV exports (holdings, ledger, fees), and closing the desk |

**Recommend once, book many.** A call is made once. *Book for clients* lists
every client: tick who acted, give an amount in rupees (the shares are worked
out) or a quantity, and change the fill price per client if theirs differed.
Every fill is checked before any is written, so a call is booked for all of
them or for none. Each trade keeps the recommended price beside the fill.
Typing a stock into the trade form picks up the open call on it by itself.

**Paste holdings.** Rows from a broker's holdings file or a spreadsheet:
comma, tab or semicolon separated. A header row is recognised by its words
(symbol / qty / avg price / date / reco price). Without one the columns are
symbol, quantity, buy price, date, recommended price. One bad row and nothing
is added, and the row is named.

**Privacy.** The eye in the desk bar blurs every amount and name, for
screen-sharing in a client meeting. Hover over a figure to read it. It is
remembered on that browser.

**A client's own view.** Switch on *Show the client* and give their email.
When they sign in with that address they see their own portfolio, read-only:
holdings, ledger, fees and the working behind them, and a statement to print.
They never see the manager's notes, a note on any trade, or anybody else's
portfolio. The Me menu says "Your portfolio manager" for them and "Your
wealth desk" for a manager.

## The arithmetic

### One ledger, everything else computed

Each client has one list of events: **buy, sell, money in, money out,
dividend, bonus/split**. Holdings (FIFO lots), cash, capital, profit and fees
are all computed from it on every load. No total is stored, so none can drift
away from what happened. A sale of shares never held, or a withdrawal larger
than the cash, is refused with the reason. Removing a buy that a later sale
depends on is refused too.

### Profit is one number

    profit = sale proceeds + value of what is held − cost of every buy
             + dividends − charges

That equals realised + unrealised + dividends − charges, and it equals value
less capital. A test pins all three. Money moving in or out is not a gain or a
loss, so deposits and withdrawals never touch it. **Booked** profit is the same
without the unrealised part.

### Capital, when only trades are recorded

Most managers record trades and not the money behind them. A buy that costs
more than the cash on hand is counted as the client topping up exactly the
shortfall that day. It is shown in the ledger as an automatic "Topped up"
line. With deposits recorded this changes nothing. With none, capital is
simply what the client had to put in, so returns, the hurdle and the fixed
fee all have an honest base. Sale proceeds are spent before new money is
counted.

### Return and XIRR

**Return** is profit on time-weighted capital, which is the Modified Dietz
return since inception. A rupee that arrived last month weighs a twelfth of
one that has been in all year. **XIRR** is the annualised, money-weighted
return of the client's own flows. It is shown once money has been in for 90
days, because annualising three weeks turns a good fortnight into a
fantastical number.

### The fee

For the period since the last settlement:

| Step | |
|---|---|
| New profit | profit now − the high-water mark (or − profit at the last settlement, when there is no mark) |
| Fixed fee | fixed % a year × capital × days invested / 365 |
| Hurdle | hurdle % a year × capital × days invested / 365 |
| Profit the share is taken from | **hard:** new profit − fixed fee − hurdle · **soft:** new profit − fixed fee, in full once it clears the hurdle · never below zero |
| Your share | share % × that |
| GST | 18% on fixed fee + share, when the desk charges it |

- **High-water mark:** the highest profit level at any past settlement, never
  below zero. A client who lost money pays no share until the loss is made
  back. It is on by default. It is what SEBI requires of a registered
  portfolio manager's performance fee, and it is fair. Turning it off shows a
  warning in red under the terms.
- **Rupee-days:** capital is counted for the days it was invested. ₹90,000
  that arrived ten days before a quarter end carries ten days of hurdle, not
  ninety.
- **The share comes after the fixed fee,** the way performance fees are
  usually measured: on returns net of the management fee.
- **Booked or total:** an agreement on booked profit only ignores gains on
  paper until a sale.

Every step goes to the page with its formula and its numbers, the way every
score on this site does. The what-if slider (share, hurdle, a price move)
re-runs `fee_math`, which `wealth.js` copies line for line, on the four
numbers the server sent. Dragging it never needs a request and never
disagrees with the bill. The browser test checks they agree.

### Billing periods

Monthly, quarterly, half-yearly or yearly. Periods end where India's financial
year does: 30 Jun, 30 Sep, 31 Dec, 31 Mar. A yearly agreement ends on 31 March.

### Settling

*Settle* crystallises the period. Its profit level becomes the mark the next
period is measured from, and the fee becomes an invoice: **due**, then
**paid** (with the date), or **waived**. A period that earned nothing is
recorded as **nothing due**, so the next one still starts from it.

- **As of a past date:** a quarter end can be settled a few days late. It is
  valued at that day's closes from the quotes' thirty-session history, so
  about six weeks back. Further than that is refused, not guessed.
- **A different amount:** the billed figure can be overridden (a rounding, a
  waiver, a negotiated number). The computed one is kept beside it.
- **Refused without prices:** a settlement on total profit is refused while
  any holding has no price, rather than measuring the profit at cost.
- **Undo:** only the latest settlement for a client can be undone, because
  every later period was measured from it.
- **A settlement from before Altaha:** *Record an earlier settlement* takes the
  date and the portfolio's value that day (from the broker's statement). The
  level is that value less the capital the ledger says was in by then. Or it
  takes the level itself. A client brought over from a spreadsheet is then not
  billed again for periods already paid. **Do this when onboarding an existing
  client**, or their whole history counts as one unsettled period.

## Prices

Live quotes come from `watchlist_quotes.py`, the same batched, cached path the
watchlists use: Yahoo daily closes, overlaid with Dhan's live price when it is
connected, plus the Altaha Score, name and sector from the universe scan. A
book with more than 25 names not yet cached gets the rest as `pending`, and
the page asks again a few times.

A **hand-set price** is for anything without a quote: an unlisted share, a
fund, a bond. It replaces the live price on the whole desk until cleared, and
the symbol is no longer sent to Yahoo, which would only fail slowly on every
load. A holding with neither is valued at cost and flagged.

**Bonuses and splits** must be recorded (a holding's ⋯ menu → *Bonus or
split*, for one client or every client who held it that day). Yahoo adjusts
its past prices for them, so without one, a holding bought before a 1:1 bonus
shows a 50% loss.

## The API

| Route | |
|---|---|
| `GET /wealth/desk` | my desk or null, and how many managers share a portfolio with me |
| `PUT /wealth/desk` | set up or edit (name, firm, registration, default terms) |
| `DELETE /wealth/desk` `{confirm: "DELETE"}` | everything on it, gone |
| `GET /wealth/book` | the whole book, valued |
| `GET /wealth/demo` | the sample desk (public; nothing stored) |
| `POST /wealth/clients` · `PUT`/`DELETE /wealth/clients/{id}` | clients |
| `POST /wealth/clients/{id}/events` `{events: [...]}` | trades, money, dividends, splits — all or nothing |
| `POST /wealth/clients/{id}/import` `{text, date}` | pasted rows |
| `DELETE /wealth/clients/{id}/events/{eid}` | one entry |
| `POST /wealth/clients/{id}/settle` `{as_of, amount, note}` | crystallise the period |
| `POST /wealth/clients/{id}/past` | record an earlier settlement |
| `POST /wealth/settlements/{sid}` `{status, paid_on}` · `DELETE` | mark paid / waived / due; undo the latest |
| `POST /wealth/recs` · `PUT`/`DELETE /wealth/recs/{id}` | calls |
| `POST /wealth/recs/{id}/apply` `{fills: [...]}` | book a call for many clients |
| `PUT /wealth/prices` `{symbol, price}` | set or clear a hand price |
| `POST /wealth/corporate-action` `{symbol, factor, on_date}` | a bonus or split for every holder |
| `GET /wealth/shared` | the portfolios managers show me, read-only |
| `GET /wealth/export.csv?what=holdings\|ledger\|fees` | spreadsheets |

Anything not yours answers **404**, the same as something that does not exist,
so one manager cannot probe for another's client ids. Signed out is 401; signed
in with no desk is 403.

## Design decisions worth knowing

**The arithmetic is on the server.** It is the bill. It is tested in Python,
and a client looking at their own portfolio sees the same numbers their
manager does. The page draws it. The one copy, `fee_math` in `wealth.js`, is
four lines that a browser test checks against the server's output.

**One events table, not trades plus cash plus corporate actions.** Ordering on
a day is fixed: money in, dividends and splits, then trades in the order they
were entered, then money out. So replaying the ledger always gives the same
answer.

**Same database as accounts.** Every row belongs to an account, the nightly R2
backup already copies the file, and `advisors.py` set the pattern. The
statements live in `wealth.py`, so moving to Postgres is two files.

**What is stored about a client:** a name, and optionally an email, a phone, a
city, tags and the manager's notes. No PAN, no Aadhaar, no bank details, no
demat login. The email matters only for showing them their own portfolio.
Deleting a client deletes their ledger and settlements. Deleting the desk
deletes everything. Under India's Digital Personal Data Protection Act the
manager is responsible for their clients' data; this keeps the amount of it
small and the delete real.

**Export cells are neutralised.** A name or note beginning with `= + - @` is
quoted as text in the CSV, so a spreadsheet does not run it as a formula.

**Polling, not sockets**, as everywhere on this instance. A book reloads after
each write and a few times while prices are still arriving.

## The regulatory line

The page says it plainly (`wealth.FEE_NOTE`). Under SEBI's rules a share of
profits is a **portfolio manager's** fee, and it must be measured from a
high-water mark. A registered **investment adviser** may charge only a fixed fee
or a fee on assets under advice, not a share of profits. A desk registered as
an RIA with a profit share in its default terms gets a warning on the Desk tab.
Altaha does the arithmetic; whether an arrangement is allowed depends on the
manager's registration. Managing other people's money for a share of the
profits without the registration for it is a question for a lawyer, and the
page says to ask one.

## What is deliberately not here

**Mutual funds by NAV.** A fund can be held at a hand-set price today. Live
NAVs from AMFI's daily file would be the next step.

**Broker connections.** Contract notes and holdings arrive by paste, not by
logging into a broker on the client's behalf. Holding someone's broker
credentials is not something this site should do.

**Invoices as documents.** The statement prints. A GST invoice with a number
series and the manager's GSTIN is a format decision for the manager.

**Historical valuation past six weeks.** Settling a date further back needs
that day's prices for every holding. *Record an earlier settlement* is the way
to bring old periods in.
