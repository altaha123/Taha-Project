"""
Every route the API serves is written down here, and the two must agree.

Twelve routes left main.py in one edit: a scripted change aimed at something
else matched more than it meant to and took seven /fundamentals endpoints
(screens, query, table, statements, coverage) and the five /admin backup,
bhavcopy and crawl ones with it. The whole suite still passed. test_cors.py
names the PUT and DELETE routes and nothing else; test_admin_auth.py asks what
the admin routes that exist will answer without a key. So a GET or a POST that
was gone was one fewer thing to check, not a failure. It was caught by reading
the diff, which is not a thing to rely on twice.

So the list is typed out, which test_cors.py rightly avoids for methods and
which is the point here: a route that disappears fails with its name, and a
route that arrives fails until somebody adds its line on purpose.

What is in the list, and what is not:

  * The routers main.py mounts inside try/except (advisor_routes,
    wealth_routes, query_ai_routes) ARE in it. They are guarded so that a
    feature which fails to import costs that feature and not the site, and
    that guard is exactly what makes losing one silent: the app starts, prints
    one line and answers 404. All three import in a test run with no keys set
    (test_cors.py already counts on the advisor and wealth ones), so here a
    router that did not mount is a failure, and the message says which one
    would not import and why.
  * FastAPI's own documentation routes (/openapi.json, /docs,
    /docs/oauth2-redirect, /redoc) are not. They are read from the app's
    settings, not typed here.
  * HEAD and OPTIONS are not. OPTIONS belongs to the CORS middleware. HEAD is
    declared only beside GET on the three pages a crawler reads
    (_PAGE_METHODS in main.py), so this test would not notice one of those
    going back to GET alone; test_company_pages.py sends a HEAD to the
    company page.
"""
import importlib

import main

# One line per method and path, sorted by path and then by method. When the
# test fails it prints the lines to delete or add in this same form.
EXPECTED_ROUTES = """
GET     /
GET     /admin/advisors
GET     /admin/advisors/reports
POST    /admin/advisors/review
GET     /admin/backup
POST    /admin/backup
GET     /admin/bhavcopy
POST    /admin/bhavcopy/archive
POST    /admin/fundamentals/crawl
GET     /admin/funds/directory
POST    /admin/funds/ingest
POST    /admin/holdings/crawl
GET     /admin/holdings/progress
POST    /admin/holdings/repair
POST    /admin/holdings/start
POST    /admin/holdings/stop
GET     /admin/holdings/unclaimed
POST    /admin/lenses/compute
POST    /admin/lenses/crawl
POST    /admin/lenses/run
POST    /admin/lenses/run/stop
GET     /admin/pro-waitlist
GET     /admin/query/ai
POST    /admin/query/ai
GET     /adviser
GET     /advisors
GET     /advisors/chats
GET     /advisors/chats/{chat_id}
POST    /advisors/chats/{chat_id}/close
POST    /advisors/chats/{chat_id}/messages
POST    /advisors/chats/{chat_id}/report
POST    /advisors/chats/{chat_id}/share
GET     /advisors/me
POST    /advisors/me/accepting
PUT     /advisors/me/profile
GET     /advisors/profile/{slug}
POST    /advisors/profile/{slug}/chat
GET     /alerts/test
GET     /analyze
GET     /announcements
GET     /announcements/diag
GET     /announcements/probe
GET     /announcements/refresh
GET     /api/lenses
GET     /api/lenses/convergence
GET     /api/lenses/coverage
GET     /api/lenses/run
GET     /api/lenses/stock/{symbol}
GET     /api/lenses/{lens_id}
GET     /attention
GET     /auth/config
POST    /auth/google
POST    /auth/logout
GET     /auth/me
POST    /auth/request-link
POST    /auth/verify
POST    /auth/verify-code
GET     /breakouts/status
GET     /brief
GET     /calls
GET     /calls/export.csv
GET     /chart
GET     /concall
GET     /concalls
GET     /cron/tick
GET     /datasource
GET     /deals
GET     /deals/{ticker}
GET     /delivery
GET     /digest/preview
GET     /explain
GET     /factors
GET     /factors/rank
GET     /fund
GET     /fundamentals
GET     /fundamentals/coverage
GET     /fundamentals/peers
GET     /fundamentals/position
GET     /fundamentals/query
GET     /fundamentals/query/fields
GET     /fundamentals/screens
GET     /fundamentals/screens/{screen_id}
GET     /fundamentals/statements
GET     /fundamentals/table
GET     /fundamentals/xbrl
GET     /funds
GET     /health
GET     /health/memory
GET     /holders
GET     /ideas
GET     /ideas/context
GET     /ideas/export.csv
GET     /index/catalog
GET     /index/composition
GET     /index/performance
GET     /intraday/diag
POST    /intraday/mark
POST    /intraday/scan
POST    /intraday/start
GET     /intraday/stats
GET     /intraday/status
POST    /intraday/stop
GET     /investor
GET     /investors
GET     /investors/coverage
POST    /jobs/concalls
POST    /jobs/daily-digest
POST    /jobs/policy-brief
POST    /jobs/wow-backfill
GET     /leaderboard
GET     /market
GET     /market/week
POST    /me/digest/send-test
POST    /me/digest/settings
GET     /me/portfolio
PUT     /me/portfolio
GET     /me/risk-profile
POST    /me/risk-profile
GET     /me/screens
PUT     /me/screens
DELETE  /me/screens/{screen_id}
GET     /me/watchlist
PUT     /me/watchlist
POST    /me/watchlist/merge
GET     /me/watchlists
PUT     /me/watchlists
GET     /news/press
GET     /news/status
GET     /og/chart.png
GET     /og/holding.png
GET     /og/idea.png
GET     /og/record.png
GET     /og/results.png
GET     /og/stock.png
GET     /options/chain
GET     /options/expiries
GET     /pages/company/{symbol}
GET     /pages/stocks
GET     /patterns
GET     /pit/correlations
GET     /pit/coverage
GET     /pit/ic
GET     /pit/label
GET     /pit/suggested-weights
GET     /planner/questions
POST    /portfolio
GET     /portfolio/policy
POST    /portfolio/start
GET     /portfolio/status
POST    /pro/waitlist
GET     /pro/waitlist/me
GET     /quote
GET     /results
GET     /results/calendar
GET     /scan/start
POST    /scan/start
GET     /scan/status
GET     /score-history
GET     /sector/benchmarks
GET     /sector/overview
GET     /sector/story
GET     /sectors
GET     /share/chart/{ticker}
GET     /share/holding/{ticker}
GET     /share/idea/{ticker}
GET     /share/record
GET     /share/results/{ticker}
GET     /share/{ticker}
GET     /shareholding
GET     /shareholding/compare
GET     /shareholding/peers
GET     /sitemap.xml
POST    /social/approve
GET     /social/categories
GET     /social/feed
GET     /social/health
GET     /social/news/feed
POST    /social/news/refresh
POST    /social/news/skip
GET     /social/news/status
GET     /social/news/themes
POST    /social/post
POST    /social/refresh
POST    /social/skip
GET     /social/status
GET     /special
POST    /special/refresh
GET     /special/status
GET     /stock/filings
GET     /stock/news
GET     /stock/peers
GET     /strategies
GET     /stream/quotes
GET     /stream/status
POST    /tracker/add
POST    /tracker/backfill
GET     /tracker/export.csv
GET     /tracker/list
POST    /tracker/purge-auto
POST    /tracker/remove
GET     /tracker/stats
POST    /tracker/update
GET     /universe
GET     /unsubscribe
POST    /unsubscribe
GET     /watchlist/featured
GET     /watchlist/quotes
GET     /wealth/book
POST    /wealth/clients
DELETE  /wealth/clients/{client_id}
PUT     /wealth/clients/{client_id}
POST    /wealth/clients/{client_id}/events
PUT     /wealth/clients/{client_id}/events
DELETE  /wealth/clients/{client_id}/events/{event_id}
PUT     /wealth/clients/{client_id}/events/{event_id}
PUT     /wealth/clients/{client_id}/holdings/{symbol}
POST    /wealth/clients/{client_id}/import
POST    /wealth/clients/{client_id}/past
POST    /wealth/clients/{client_id}/settle
POST    /wealth/clients/{client_id}/statement/apply
POST    /wealth/clients/{client_id}/statement/plan
POST    /wealth/corporate-action
GET     /wealth/demo
GET     /wealth/demo/news
DELETE  /wealth/desk
GET     /wealth/desk
PUT     /wealth/desk
GET     /wealth/export.csv
POST    /wealth/isin
GET     /wealth/news
PUT     /wealth/prices
POST    /wealth/recs
DELETE  /wealth/recs/{rec_id}
PUT     /wealth/recs/{rec_id}
POST    /wealth/recs/{rec_id}/apply
DELETE  /wealth/settlements/{settlement_id}
POST    /wealth/settlements/{settlement_id}
GET     /wealth/shared
GET     /wow-orders
"""

# The routers main.py carries on without if they fail to import.
GUARDED_ROUTERS = ("advisor_routes", "wealth_routes", "query_ai_routes")


def served_routes(app) -> set:
    """(method, path) for everything the app answers, less the exclusions in
    the docstring. A route with no HTTP methods (a websocket, a mount) goes
    under its class name, so that the first one to arrive is not invisible."""
    own_docs = {app.openapi_url, app.docs_url,
                app.swagger_ui_oauth2_redirect_url, app.redoc_url}
    out = set()
    for route in app.routes:
        if route.path in own_docs:
            continue
        for method in getattr(route, "methods", None) or (type(route).__name__,):
            if method not in ("HEAD", "OPTIONS"):
                out.add((method, route.path))
    return out


def listed_routes() -> list:
    """EXPECTED_ROUTES as (method, path) pairs, in the order written."""
    out = []
    for line in EXPECTED_ROUTES.splitlines():
        if line.strip():
            parts = line.split()
            assert len(parts) == 2, f"not a 'METHOD /path' line: {line!r}"
            out.append((parts[0], parts[1]))
    return out


def _order(route):
    method, path = route
    return (path, method)


def _line(route) -> str:
    return "    %-7s %s" % route


def _lines(routes) -> str:
    return "\n".join(_line(r) for r in sorted(routes, key=_order)) or "    (none)"


def _routers_that_do_not_import() -> list:
    out = []
    for name in GUARDED_ROUTERS:
        try:
            importlib.import_module(name)
        except Exception as e:
            out.append(f"    {name}: {type(e).__name__}: {e}")
    return out


def _report(missing, new) -> str:
    out = ["main.app does not serve exactly the routes in EXPECTED_ROUTES.",
           "",
           f"MISSING, listed but no longer served ({len(missing)}):",
           _lines(missing),
           "",
           f"NEW, served but not listed ({len(new)}):",
           _lines(new),
           "",
           "A route lost by accident needs putting back. For a change that was "
           "meant, delete or add",
           "those lines in EXPECTED_ROUTES in backend/tests/test_routes_present.py, "
           "which is sorted by path."]
    broken = _routers_that_do_not_import()
    if broken:
        out += ["",
                "main.py mounts these inside try/except and they do not import, "
                "so their routes are gone:"] + broken
    return "\n".join(out)


def test_the_routes_served_are_the_routes_listed():
    served, listed = served_routes(main.app), set(listed_routes())
    missing, new = listed - served, served - listed
    assert not missing and not new, _report(missing, new)


def test_the_list_is_in_order_with_nothing_twice():
    """Sorted, so a route's line is where its path says it is and two branches
    that each add one do not both add it at the bottom."""
    listed = listed_routes()
    twice = {r for r in listed if listed.count(r) > 1}
    assert not twice, "listed more than once:\n" + _lines(twice)
    for before, after in zip(listed, listed[1:]):
        assert _order(before) < _order(after), (
            "EXPECTED_ROUTES is sorted by path, then method, and this line\n"
            + _line(after) + "\nis written after this one, which it belongs before:\n"
            + _line(before))
