"""
The enumeration the other guards are built on.

`test_cors` and `test_tier_routes` assert things about every route the app
serves, enumerated from the app so a route added tomorrow is covered the day it
lands. That is only true while the enumeration works — and it stopped working
silently once, when FastAPI changed `include_router` to leave opaque
`_IncludedRouter` wrappers in `app.routes` instead of copying the endpoints in.
Walking that list then found 4 docs routes and nothing else. No test failed.
`test_cors` reported a single served verb and could no longer catch the missing
`PATCH` it was written for; every parametrised plan-check case collapsed to zero.

So the walker gets its own tests. A broken route table must fail here, loudly,
rather than draining the assertions elsewhere. The numbers below are floors, not
counts — they are meant to survive routes being added and to fail hard if the
walk degenerates.
"""
from app.main import app
from route_table import routes_under, served_methods, served_routes

#: The app had 62 routes across 5 verbs when this was written. A floor well
#: under that catches a degenerate walk without breaking every time a route is
#: added or removed.
_MIN_ROUTES = 40


def test_the_walk_finds_the_whole_surface():
    routes = served_routes(app)
    assert len(routes) >= _MIN_ROUTES, (
        f"only found {len(routes)} routes — the route table walk has broken "
        "again, and every enumerated guard in this suite is now vacuous"
    )


def test_every_verb_the_app_serves_is_discovered():
    """
    The CORS guard compares served verbs against the allowlist. If the walk
    reports only reads, that comparison cannot fail — which is precisely how it
    broke before.
    """
    methods = served_methods(app)
    assert {"GET", "POST", "PUT", "PATCH", "DELETE"} <= methods, (
        f"only discovered {sorted(methods)}; the app serves all five"
    )


def test_the_trading_surface_is_discovered():
    """
    The fifteen routes behind the single shared brokerage account. This is the
    enumeration `test_tier_routes` parametrises over, so an empty result there
    means nothing is checking who can reach them.
    """
    trading = routes_under(app, "/trading")
    assert len(trading) >= 15, f"only found {len(trading)} trading routes: {trading}"
    assert ("POST", "/trading/order") in trading


def test_no_route_is_discovered_twice():
    """
    The walk recurses and must not visit a router twice — a duplicated route
    would silently double every parametrised case built on it.
    """
    routes = served_routes(app)
    assert len(routes) == len(set(routes))


def test_the_implicit_verbs_are_excluded():
    """
    HEAD is derived from GET and OPTIONS is answered by the CORS middleware.
    Neither is something a client asks permission for, so neither belongs in a
    comparison against `allow_methods`.
    """
    assert not {"HEAD", "OPTIONS"} & served_methods(app)


def test_paths_are_returned_whole():
    """Guards against a walk that loses a router's prefix."""
    for _, path in served_routes(app):
        assert path.startswith("/"), path
