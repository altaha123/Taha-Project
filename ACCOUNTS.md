# Accounts and the daily email

A reader signs in with their email, saves what they hold, and gets one message
after the close: what their holdings did, what was filed on them, what is worth
a look.

Nothing here is a gate. Signed out, every tool works exactly as before —
a screener that demands a login before it will do arithmetic is a screener
people leave.

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
