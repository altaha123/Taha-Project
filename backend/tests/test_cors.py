"""
The browser must be allowed to send every method this API answers.

/me/portfolio and /me/watchlist are PUT. The CORS policy said "GET, POST". An
Authorization header makes a request non-simple, so the browser asks first,
was told PUT was not allowed, and never sent it — so "Save" saved nothing, to
the account, for the portfolio and for every watchlist edit.

Nothing failed. No request reached the server to fail. The only symptom was a
button that looked like it worked.

This reads the app's own routing table rather than a list written out by hand,
so a route added later with a method nobody thought about fails here instead of
silently in somebody's browser.
"""
import main


def served_methods() -> set:
    out = set()
    for route in main.app.routes:
        for method in getattr(route, "methods", None) or ():
            if method not in ("HEAD", "OPTIONS"):
                out.add(method)
    return out


def test_every_method_the_api_serves_is_allowed_through_cors():
    missing = served_methods() - set(main.ALLOWED_METHODS)
    assert not missing, (
        "these methods are served but a browser is not allowed to send them: "
        + ", ".join(sorted(missing))
    )


def test_the_two_put_routes_are_the_ones_that_save_to_an_account():
    """If these stop being PUT the comment above stops being true, and the
    next person reading it is misled about why this file exists."""
    puts = {r.path for r in main.app.routes
            if "PUT" in (getattr(r, "methods", None) or ())}
    assert puts == {"/me/portfolio", "/me/watchlist"}
    assert "PUT" in main.ALLOWED_METHODS


def test_the_allow_list_is_what_the_middleware_was_given():
    """A constant nothing reads is a constant that drifts."""
    cors = [m for m in main.app.user_middleware
            if "CORS" in m.cls.__name__]
    assert cors, "the CORS middleware is no longer installed"
    options = getattr(cors[0], "kwargs", None) or getattr(cors[0], "options", {})
    assert options.get("allow_methods") == main.ALLOWED_METHODS
