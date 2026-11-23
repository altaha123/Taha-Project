# Accounts and the daily email

A reader signs in with their email, saves what they hold, and gets one message
after the close: what their holdings did, what was filed on them, what is worth
a look.

Most of the site stays open signed out: the market overview, the screener,
stock pages, charts, the portfolio tools. A set of **member tools** asks for
sign-in first (`frontend/gate.js`):

- Market › Alerts, Big trades, Delivery trends
- Ideas › Investor styles, Who owns what, Fund houses, Strategy lab
- Talk to an adviser (`advisors.html`) and the Wealth desk (`wealth.html`)

Opened signed out — from the menu, a door card, the search palette or a
shared `#hash` — each shows a sign-in card in its place. The card sends the
reader to `signin.html?next=…`, and once signed in they land back on the same
tool. The hiding is a stylesheet rule keyed on `html.gate-out`, set in the
`<head>` before the page draws, so a gated tool never flashes up first. To
gate or ungate a tool, edit `TOOLS` (tabs on the main page) or `PAGES` (pages
of their own, which load `gate.js` with `data-page=`) in that file.

This decides what the site shows, not what the API serves: the market data
behind these tools is public, while an account's own data (chats, a desk's
clients) is checked server-side by the session token, as before.

## What it looks like from outside

1. **Sign in** — `signin.html`. Type an email, get a six-digit code, type it
   into the page still open in front of them. No password: reaching the
   address proves they own the address, which is exactly what a product that
   emails you every day needs to establish anyway. The same email carries a
   link, and **Continue with Google** is offered when it is configured.
2. **Save a portfolio** — the Save button on the Portfolio tab now writes to
   the account as well as the browser.
3. **Keep a watchlist** — the star on any stock. Signed out it is saved on that
   browser, as it always was. Signed in it is saved to the account, so it is
   there on the next device and survives a cleared browser.
4. **The daily email** — on by default once there is a portfolio, off in one
   click, from a link in every message that needs no login.

## Switching it on

| Where | Setting | Why |
|---|---|---|
| Render → Environment | `EMAIL_PROVIDER` = `resend` or `brevo` | Without it nothing is delivered — see below |
| Render → Environment | `RESEND_API_KEY` / `BREVO_API_KEY` | The provider's key |
| Render → Environment | `EMAIL_FROM` | e.g. `Altaha Screener <hello@altahascreener.in>` |
| Render → Environment | `GOOGLE_CLIENT_ID` | Optional. Unset, the Google button is not rendered at all |
| GitHub → Secrets → Actions | `ALTAHA_ADMIN_KEY` | Same value as `ADMIN_KEY` on Render; the scheduled job authenticates with it |
| DNS for altahascreener.in | SPF, DKIM, DMARC | **Do this first** |

**The DNS step is not optional.** Whether these land in an inbox or a spam
folder is decided by whether the domain vouches for the sender, and no library
substitutes for that. Both providers walk you through the exact records.

With nothing configured, `EMAIL_PROVIDER` is `console` and public sign-in
returns HTTP 503 instead of claiming an email was sent. Missing provider
credentials and rejected sends also return a retryable error. Failed sends
remove their unused token so they do not exhaust the address's link quota.
An explicit request with the configured admin key can still obtain a debug
link in console mode for local testing; public users never receive one.

Email links open a confirmation button before verification, so automated link
previews do not immediately spend them. Open the link in the same browser
where you use Altaha; an email app's embedded browser has separate storage.
Existing sessions are checked before the sign-in page claims you are signed
in. Sessions remain stored during temporary API outages.

Before release, verify Render's `EMAIL_PROVIDER`, provider API key, verified
`EMAIL_FROM`, and `SITE_URL=https://altahascreener.in`. Confirm `DATA_DIR`
points at the persistent disk. Provider acceptance is not proof of inbox
delivery: complete one real sign-in using an address you control.

## Checking it works

```bash
# 1. Is a provider live?
curl https://taha-project.onrender.com/health          # → "sentry", "accounts"

# 2. Ask for a link (console mode hands it back with the admin key)
curl -X POST https://taha-project.onrender.com/auth/request-link \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@example.com","key":"<ADMIN_KEY>"}'

# 3. What would go out tonight, without sending it
curl -X POST 'https://taha-project.onrender.com/jobs/daily-digest?dry_run=true' \
     -H 'X-Admin-Key: <ADMIN_KEY>'
```

Or sign in on the site and press **Send me today's email** on the Portfolio
tab. A preview in a browser is not an inbox; that button is the only honest
check of what a subscriber actually receives.

## The schedule

`.github/workflows/daily-digest.yml` fires at 12:15 UTC (17:45 IST) on
weekdays — after the close, late enough for the daily feed to settle. Render's
own cron is a paid add-on and an in-process timer dies with the worker, which
is how a job silently stops running one afternoon.

The job is keyed on **the market's last session, not the calendar date**, so a
run on an Indian market holiday finds everybody already marked for that
session and mails nobody. Same mechanism makes a retry after a crash safe: it
sends to whoever was missed and to nobody else.

## Three ways in, one account

All three end at `_issue_session`, and the account is keyed on the email
address, so somebody who types a code today and presses the Google button
tomorrow lands on one account rather than two.

**The code is the one that works everywhere.** A link is opened by whichever
browser the mail app hands it to — on a phone, the mail app's own — so the
reader signs in and finds the browser they actually use still signed out.
That is not a bug in the link; it is what links do. The code goes back into
the page that is already open, which is the one they want.

The code and the link are the same row in `login_tokens`. Spending either
spends both, so a mail scanner that follows the link cannot leave a live code
behind it.

**Five wrong codes and it is spent.** Six digits is one of 900,000, which a
script gets through in minutes if it is allowed to keep guessing; the
fifteen-minute expiry is not what protects this, `MAX_CODE_ATTEMPTS` is. The
attempt is counted before it is judged, so a process that dies between the two
cannot hand the next caller a free guess.

**Google is verified server-side, or not at all.** The browser hands over an ID
token and the server checks it against Google's `tokeninfo` endpoint — a real
HTTPS call on every sign-in, rather than a JWT library, a JWKS cache and a
key-rotation story for a site signing in a few hundred people a day. Four
things are then checked and every one matters: the **audience** is this site's
client id (without it, a token minted for any other site using Google sign-in
would be accepted here), the issuer is Google, the address is one Google
reports as **verified**, and the token has not expired.

With `GOOGLE_CLIENT_ID` unset, `/auth/google` returns 503 and the page does not
render the button — a button that cannot work is worse than no button. It is
also the only third-party script this site loads, it loads only on
`signin.html`, and only when that client id is set.

**The database already had rows.** `CREATE TABLE IF NOT EXISTS` is a no-op
against a live table, so `code_hash` and `attempts` reach a fresh database and
never the one on the disk with real users in it. `_ensure_column` is what makes
the deployed database get them too, and there is a test that opens a
pre-codes database and signs in against it.

## The portfolio stays with its account

Signed in, the list on the Portfolio tab is a copy of the **account's**
portfolio, kept in `localStorage` so it draws at once. The API has always kept
accounts apart (`/me/portfolio` is read and written by the session's user id).
The browser's copy did not: it outlived the session it came from.

- Sign out, and the list stayed on the screen for whoever used the browser
  next.
- Sign in as somebody else with nothing saved, and the rule written for a list
  typed signed out ("an empty account takes what this browser holds") saved
  the first account's holdings into the second, where the daily email then
  reported on them.

So the copy now has an owner, the account it last agreed with
(`altaha-portfolio-synced`: `who`, `sig`, `out`), and it leaves with that
account (`portfolio.js`, *Whose list this is*):

| What happened | The list in the browser |
|---|---|
| Somebody signed out here since it last synced (`AltahaAuth.signOutMark()` has changed) | Goes, before anything is drawn |
| A different account is signed in | Goes, and is never sent |
| The session lapsed (a 401) | Goes, unless it holds a change the account never received, which is kept for its owner to send |
| It was typed signed out (no owner) | Kept, and saved to the first account that signs in with nothing saved, as before |

Nothing is lost by any of the first three: the account has the list, and it is
back on the next sign-in. A line under the table says why it went.

Until `/auth/me` has said whose session this is, a list with an owner is not
saved anywhere (`unconfirmed()`): the Save button and the email button say they
are still checking.

A portfolio saved **by name** is kept in the browser only. One saved while
signed in now carries its account and is offered only to that account; one
saved signed out, or before this change, has no owner and is offered to anybody
on that browser.

`frontend/tests/portfolio-accounts-browser.cjs` walks two accounts through one
browser, a lapsed session and a second open tab.

**Not covered:** the watchlists still merge whatever is in the browser into the
first account that signs in, including a list another account left there.

## The watchlist, and why it merges exactly once

The watchlist is the list most readers will ever build — following a stock
costs nothing, owning one is a decision. It lived in `localStorage`, which
meant a cleared browser or a new phone started an empty list and threw away
the only work a reader had done on the site.

It now syncs, with `localStorage` still the thing the screen reads: instant,
works offline, and all a signed-out reader has. The account is a copy that
follows behind.

The rule that matters is **merge once, replace after**:

- A reader stars six names signed out, then signs in. Replacing in either
  direction throws away a list somebody built, so the first sync after signing
  in **merges** — and the account's own list keeps its order, because it is the
  older one.
- Every edit after that **replaces**. A watchlist that merged on every load
  would push back a stock removed on another device, and a list that refuses to
  forget is worse than one that forgets everything.

Which account this browser has already merged into is remembered in
`altaha-watchlist-account-v1`, so the merge happens at the handoff and nowhere
else.

An edit that could not be sent — the tab was offline, the API was down — sets
`altaha-watchlist-unsent-v1` and says so on screen rather than showing a filled
star for something that never left the browser. It is on disk rather than in a
variable, because the reader closes the tab and comes back, and the account
copy, which never heard about that edit, would otherwise quietly overwrite it.
The next load retries it instead of adopting the older copy.

`frontend/tests/watchlist-browser.cjs` drives all three of those in a real
browser, because every one of them fails silently: the star still turns gold.

## The watchlist in the daily email

The daily email now ends with **On your watchlist**: the stocks a subscriber
follows but does not own, and only the ones that did something — a filing, one
of the checkable observations (a 52-week high, a moving-average crossing, a
volume spike, a gap), or a move of 3% or more. A list of every starred name
with a price beside it is a list nobody reads by the third day, so quiet stocks
are left out; at most six are shown, filings first (`digest.watchlist_section`).

Watched and held stocks are priced in the same pass, so a stock both owned and
followed is fetched once. **Who gets the email has not changed**: it still goes
to subscribers with a saved portfolio. Somebody who has only starred stocks gets
no email yet — turning that on would start mailing people who never received
one, and is a decision to make on purpose.

## Saved screens

The query screener can name and keep a screen (`/me/screens`: GET, PUT by name,
DELETE by id; 25 per account). Signed out, screens are kept in the browser;
the first sign-in on that browser moves them to the account. The DELETE is why
`ALLOWED_METHODS` in `main.py` now includes it — `test_cors.py` failed until it
did, which is exactly the failure that file exists to catch.

## The Pro waitlist

`pro.html` shows the price (₹5,000 a quarter or ₹15,000 a year since Nov
2026; see [`FORUM.md`](FORUM.md)) and collects an address — a fake door, on purpose:
the cheapest honest measure of whether anybody would pay before anything is
built to take the money. Nothing is charged, and the page says so.

- `plan` is `quarterly` or `yearly`. The ids the page used before, `annual`
  (₹1,999) and `monthly` (₹249), are still accepted and still counted apart,
  so a yes at the old price is never read as a yes at the new one.
- `POST /pro/waitlist` `{email, source, plan}`. Signed in, the account's
  address is used. Joining twice is one row; the first source and plan are
  kept. Five joins an hour per visitor.
- `GET /admin/pro-waitlist` with `X-Admin-Key` — the count, by source and by
  plan, and the addresses. **Closed when `ADMIN_KEY` is unset**, unlike the
  control endpoints, because it returns personal data.
- `source` says where the reader came from: `header`, `menu`, `story`
  (the portfolio story's last chapter), `direct`.

## Design decisions worth knowing

**Bearer tokens, not cookies.** The site and the API are on different origins.
A session cookie there needs `SameSite=None`, credentialed CORS with a fixed
origin list in place of the `"*"` the API sends today, and a CSRF story on
every write. A token in an `Authorization` header needs none of it, and no
other site's page can attach it to a request. The cost is that the token sits
in `localStorage`, readable by any script on this origin — accepted knowingly:
this frontend has no build step, no npm tree, and no third-party script beyond
a charting library.

**SQLite, on the disk that is already mounted.** `tracker.py` and
`pit_store.py` have kept the two datasets that cannot be rebuilt on that disk
for months. A hosted Postgres means an account, keys and a bill, and buys
nothing the first hundred users will notice. Every statement lives in
`accounts.py`, so moving later is one file.

**No passwords, ever.** No hashing choice to get wrong, no reset flow, no
breach to worry about, and nothing for a reader to reuse from another site.
Sign-in links work once and expire in fifteen minutes; tokens are stored as
SHA-256 digests, so a copy of the database is not a set of working links.

**One-click unsubscribe.** Both the link and the `List-Unsubscribe` header
Gmail and Yahoo look for. Anything harder and people press the spam button
instead, which costs the sending domain rather than one subscriber.

## What is deliberately not here

**WhatsApp.** Meta requires pre-approved templates for business-initiated
messages, per-message billing, and business verification with a long lead
time. Email first, and the digest content in `digest.py` is channel-agnostic
when that day comes.

**Buy and sell signals.** The digest reports facts — *"crossed above its
50-day average"*, *"your target of ₹1,650 was touched"* — and never a verdict.
Telling the public what to trade is investment advice and needs SEBI
registration this project does not have. A test reads the rendered email and
fails the build on that vocabulary, because the risk is not somebody deciding
to add advice; it is a helpful phrase creeping into a template one afternoon.

**A backup of the accounts database.** The Render disk is the system of record
and nothing copies it anywhere. Worth fixing before there are users whose data
would be missed.
