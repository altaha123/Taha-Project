# Accounts and the daily email

A reader signs in with their email, saves what they hold, and gets one message
after the close: what their holdings did, what was filed on them, what is worth
a look.

Nothing here is a gate. Signed out, every tool works exactly as before —
a screener that demands a login before it will do arithmetic is a screener
people leave.

## What it looks like from outside

1. **Sign in** — `signin.html`. Type an email, get a link, click it. No
   password: a link to the address proves they own the address, which is
   exactly what a product that emails you every day needs to establish anyway.
2. **Save a portfolio** — the Save button on the Portfolio tab now writes to
   the account as well as the browser.
3. **The daily email** — on by default once there is a portfolio, off in one
   click, from a link in every message that needs no login.

## Switching it on

| Where | Setting | Why |
|---|---|---|
| Render → Environment | `EMAIL_PROVIDER` = `resend` or `brevo` | Without it nothing is delivered — see below |
| Render → Environment | `RESEND_API_KEY` / `BREVO_API_KEY` | The provider's key |
| Render → Environment | `EMAIL_FROM` | e.g. `Altaha Screener <hello@altahascreener.in>` |
| GitHub → Secrets → Actions | `ALTAHA_ADMIN_KEY` | Same value as `ADMIN_KEY` on Render; the scheduled job authenticates with it |
| DNS for altahascreener.in | SPF, DKIM, DMARC | **Do this first** |

**The DNS step is not optional.** Whether these land in an inbox or a spam
folder is decided by whether the domain vouches for the sender, and no library
substitutes for that. Both providers walk you through the exact records.

With nothing configured, `EMAIL_PROVIDER` is `console`: every message is
printed to Render's log and delivered nowhere. The whole flow still works —
which is what makes it testable before a provider exists.

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
