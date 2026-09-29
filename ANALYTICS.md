# What this site measures, and what it refuses to

Two tools, both optional, both failing silently when unavailable:

- **PostHog** — what people do here. `frontend/analytics.js`.
- **Sentry** — what breaks. `frontend/analytics.js` in the browser,
  `backend/main.py` on the server.

Nothing here is a growth hack. It exists because every product decision on
this project has been made blind, and because the CI header is right: every
bug this project has shipped was silent.

---

## The events

`track()` refuses any name not on this list, so **the list below is the whole
list** — a call site cannot start collecting something new without adding it
here first, and `frontend/analytics.test.js` fails CI if the two drift.

| Event | Properties | The question it answers |
|---|---|---|
| `stock_opened` | ticker, from | Which companies people come here for, and by what route |
| `stock_viewed` | ticker, sector, score | Which analyses actually render, and at what score |
| `stock_view_failed` | ticker, reason | How often a reader gets nothing — asleep engine vs. no such name |
| `stock_section_clicked` | section | Does anyone read past the score into the ledger and the levels |
| `chart_range_changed` | range | Which windows matter |
| `chart_failed` | range, status | A chart that refuses to draw — the 6M bug, caught next time |
| `search_no_match` | query | Names people search for that the universe does not carry |
| `watchlist_changed` | ticker, action, size | The closest thing to intent this site has without accounts |
| `sign_in_link_requested` | — | How many people ask for a sign-in link |
| `signed_in` | method | How many of those links get used — the drop-off between the two is the whole funnel |
| `portfolio_saved` | holdings, destination | Saved to the browser or to an account, and how much |
| `digest_opt_in_changed` | opt_in | Whether people keep the daily email on |
| `view_opened` | section, tab | Which of the forty-odd modules earn their keep |
| `share_clicked` | kind, action | Whether the growth loop turns at all |
| `portfolio_story_viewed` | chapter, index, total | How far people read the portfolio story, chapter by chapter |
| `portfolio_full_report_opened` | from | Whether anyone still wants the full report after the story, and from where |
| `portfolio_plan_viewed` | moves, holdings | Whether the action plan is seen, and how many of its calls ask for a move — counts only |
| `portfolio_story_opened` | from | Whether anyone opens the story once it is optional |
| `pro_cta_clicked` | from | Who looks at the Pro price, and from which page |
| `pro_waitlist_joined` | from, signed_in | Who would pay: the one number the Pro waitlist exists to measure |
| `api_error` | endpoint, status | The API's real error rate, seen from the browser |

Automatic on top of that: page views, page leaves, and autocapture (clicks on
buttons and links). Autocapture answers questions nobody thought to ask; it is
the first thing to switch off if the free quota ever tightens.

## What is never collected

- No names, emails, phone numbers or any other identifier a person types.
- No portfolio holdings, quantities or values. No planner inputs — savings,
  income, goals. The portfolio story reports which chapter was read, never
  a figure from it.
- The Pro waitlist address goes to our own API (`POST /pro/waitlist`), never
  to PostHog; `pro_waitlist_joined` carries only where it came from.
- No free text except the search box, capped at 40 characters.
- **No email addresses.** `signed_in` records the method, never the address.
  PostHog identifies people by an anonymous id, and nothing links it to an
  account.
- Every other property value is capped at 64 characters and coerced to a
  string, number or boolean.

**Session replays** are on. Every input is masked (`maskAllInputs`), and
anything inside a `data-private` element is masked as well — that marks
`#view-portfolio` and `#view-planner` in `index.html`. If a future view
renders somebody's money, put `data-private` on its container.

**Do Not Track is honoured** (`respect_dnt`). A visitor who has set it is not
recorded at all.

## Where it does not run

Only `altahascreener.in` and `www.altahascreener.in` report. Local files,
Vercel previews and anything else are silent, so the dashboard the decisions
come from is not polluted by our own testing. Add `?altaha_debug=1` to a URL
to force reporting on for a deliberate check.

---

## Keys and configuration

| What | Where it lives | Secret? |
|---|---|---|
| PostHog project key | `frontend/analytics.js`, in the page source | No — write-only ingest key, designed to be public |
| Sentry browser DSN | `frontend/analytics.js` (`CONFIG.sentryDsn`) | No — an address, not a credential |
| Sentry server DSN | `SENTRY_DSN` env var on Render | No, but it belongs with the deploy, not in git |

The one key that must **never** appear in this repository is PostHog's
**Personal API key**, which can read and delete. Nothing here needs it.

`GET /health` reports `"sentry": true` once the server DSN is set, so whether
crash reporting is live in production is a question with an answer.

## Turning any of it off

- **PostHog:** blank `CONFIG.posthogKey` in `frontend/analytics.js`.
- **Browser Sentry:** blank `CONFIG.sentryDsn`. Nothing is loaded.
- **Server Sentry:** unset `SENTRY_DSN` on Render. `main.py` does not import
  the SDK at all in that case.

All three are independent, and the site behaves identically with all three off.

## Uptime

Not in this repository, because it is not code: UptimeRobot (free) pings
`https://taha-project.onrender.com/health` every five minutes and messages
Telegram when it stops answering. The API returned 502 for a stretch on
2026-09-10 and nobody knew until somebody happened to call it by hand.
