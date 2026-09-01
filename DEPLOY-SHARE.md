# Why there is a `vercel.json`

Everything the public sees of this product arrives as a link, and until this
file existed every one of those links read

    https://taha-project.onrender.com/share/RELIANCE

That is the API's hosting provider, printed on the front of the product. Two
problems, one cosmetic and one not:

* A free-tier PaaS hostname in a shared link says "weekend project" before the
  card has finished loading. The card is the pitch; the hostname is the first
  half of it.
* Every link ever posted breaks the day the API moves. Links are permanent in
  a way infrastructure is not.

## What the file does

Vercel serves the site. Three rewrites proxy the two crawler-facing paths
straight through to the API, so the same documents answer on the site's own
domain:

| Public URL                          | Served by                                        |
| ----------------------------------- | ------------------------------------------------ |
| `/share/RELIANCE`                   | `…onrender.com/share/RELIANCE`                    |
| `/share/chart/RELIANCE?range=1D`    | `…onrender.com/share/chart/RELIANCE?range=1D`     |
| `/og/stock.png?ticker=RELIANCE`     | `…onrender.com/og/stock.png?ticker=RELIANCE`      |
| `/share`                            | the track-record page                             |

Query strings are forwarded by Vercel automatically. Everything else on the
domain is still the static site: rewrites only apply when no file matches.

## After a custom domain

Point the domain at the same Vercel project and set two environment variables
on the Render service:

    SITE_URL=https://altaha.example
    SHARE_ORIGIN=https://altaha.example

`SHARE_ORIGIN` defaults to `SITE_URL`, so in practice only the first is
required. Nothing in the code changes.

## If the rewrite is not live yet

The frontend asks the site's own origin for a card first and falls back to the
API host if that 404s, so sharing keeps working during the window between
deploying the backend and deploying this file. The fallback is a safety net,
not the intended path — a link that has already gone out cannot be corrected.

## One thing to watch

A crawler fetching `/og/stock.png` is proxied to Render, and Render renders the
card on demand. Twitterbot does not wait long. The card is cached per symbol
per day on the API side, so the first fetch of the day for a symbol is the slow
one — open the share sheet once before posting and the crawler gets a warm
cache. The site is on the paid Render tier, so there is no cold start on top of
that.
