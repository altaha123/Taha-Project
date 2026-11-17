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

## Where the file lives: `frontend/vercel.json`

The Vercel project's **Root Directory is `frontend`**, and Vercel reads
`vercel.json` from the Root Directory only. Until November 2026 the file sat at
the repo root, where Vercel never saw it. `/share/RELIANCE` on the live site
was Vercel's own 404, and the frontend's fallback to the API host (below) hid
it. `backend/tests/test_share_endpoints.py` now fails if a `vercel.json`
reappears at the root.

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

That last sentence is what lets the share pages carry the logo. Each one
advertises `/favicon.ico`, `/icon-512.png` and `/apple-touch-icon.png` on its
own domain, and because those files exist in `frontend/` no rewrite catches
them — Vercel serves them directly and the API never sees the request. The
card image itself carries the mark drawn into the PNG by `backend/og.py`, so
it survives clients that show the image and nothing else.

## After a custom domain

Point the domain at the same Vercel project and set two environment variables
on the Render service:

    SITE_URL=https://altahascreener.in
    SHARE_ORIGIN=https://altahascreener.in

`SHARE_ORIGIN` defaults to `SITE_URL`, so in practice only the first is
required, and `render.yaml` already carries it so a blueprint sync sets it
without a trip to the dashboard. Nothing in the code changes.

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

## Addresses without `.html`

The address bar reads `/stock?ticker=TCS`, `/signin`, `/wealth` rather than
`stock.html?ticker=TCS`. Two pieces do it, and neither is a redirect:

* **`frontend/vercel.json` rewrites** `/stock`, `/signin`, `/wealth`, `/advisors`,
  `/brief`, `/pro` and `/ownership-share` to their `.html` files, so a clean
  address works when it is reloaded, bookmarked or shared. Rewrites carry the
  query string, the same as the `/share` ones above.
* **`frontend/clean-url.js`**, the first script on every page, swaps the
  address shown with `history.replaceState` before anything paints. It keeps
  the query string and the `#hash`. `/index.html` becomes `/` on any server.
  The other pages are tidied only on `altahascreener.in` and `*.vercel.app`,
  the hosts that have these rewrites. Anywhere else (a local copy, the
  browser tests' static servers) a reload of `/stock` would 404.

The pages still link to each other as `stock.html`, `signin.html` and so on,
on purpose. That file loads directly, with no extra hop, and the address is
then tidied. Emailed and WhatsApp links the backend sends (`signin.html?token=`,
`advisors.html#chat/...`, `brief.html`) work the same way.

**Why not `"cleanUrls": true`:** it answers `/stock.html` with a 308 to `/stock`.
Vercel's own static server, `serve-handler`, drops the query string on that
redirect. Under it, `/stock.html?ticker=TCS` landed on an empty `/stock` and a
sign-in link lost its `?token=`. Production may behave differently, but sign-in
should not depend on it.

**Adding a page:** add its rewrite to `frontend/vercel.json` and load `clean-url.js` first in its
`<head>`. Code that reads its own address must accept both forms, `/stock` and
`/stock.html`. So far that is the stock-page check in `experience.js`, the
"no footer on the desks" check in `shell.js`, and `signin.html`, which uses
`location.pathname` when it clears the token from the address.
