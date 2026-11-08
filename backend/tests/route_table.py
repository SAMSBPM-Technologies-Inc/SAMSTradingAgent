"""
The app's own route table, enumerated the same way on every FastAPI version.

Several tests here assert things about *every* route the app serves — which
verbs CORS must allow, which paths the plan check must cover — and they
enumerate the app rather than a hand-written list precisely so a route added
tomorrow is covered the day it lands.

That enumeration broke silently. Up to FastAPI 0.111 (the pinned version),
`include_router` copied each endpoint into `app.routes`, so walking that list
found everything. From roughly 0.120 it instead appends one `_IncludedRouter`
wrapper per `include_router` call and resolves the real endpoints at request
time. `app.routes` then contains 4 docs routes and 15 opaque wrappers, so a
walk of it finds almost nothing — and the tests built on it did not fail, they
*passed while testing nothing*. `test_cors` saw a single verb, `GET`, and could
no longer have caught the missing-`PATCH` bug it was written to prevent.

A silently-empty enumeration is worse than a broken one, so this module is
deliberately paranoid: it understands both layouts, and `tests/test_route_table.py`
asserts the result is not degenerate. If a future version changes the internals
again, that test fails loudly and these guards stay honest.
"""
from __future__ import annotations

#: Neither is something a client asks permission for: HEAD is derived from GET,
#: and OPTIONS is what the CORS middleware itself answers.
_IMPLICIT_METHODS = {"HEAD", "OPTIONS"}

#: A route table cannot nest this deeply. Bounded so a cyclic structure cannot
#: hang the suite.
_MAX_DEPTH = 10


def served_routes(app) -> list[tuple[str, str]]:
    """
    Every `(method, path)` the app answers, sorted, with the implicit verbs
    dropped. Works on both the flattened (<=0.111) and wrapped (>=0.120)
    layouts.
    """
    found: set[tuple[str, str]] = set()
    seen_routers: set[int] = set()

    def walk(routes, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        for route in routes or ():
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path and methods:
                for method in set(methods) - _IMPLICIT_METHODS:
                    found.add((method, path))
                continue

            # FastAPI >= ~0.120: one wrapper per include_router call, holding
            # the router it was given rather than its routes.
            inner = getattr(route, "original_router", None)
            if inner is not None:
                if id(inner) in seen_routers:
                    continue
                seen_routers.add(id(inner))
                walk(getattr(inner, "routes", None), depth + 1)
                continue

            # Mounts and sub-applications.
            nested = getattr(route, "routes", None)
            if nested:
                walk(nested, depth + 1)

    walk(getattr(app, "routes", None), 0)
    return sorted(found)


def served_methods(app) -> set[str]:
    """Every verb the app's route table answers, preflight aside."""
    return {method for method, _ in served_routes(app)}


def routes_under(app, prefix: str) -> list[tuple[str, str]]:
    """Every `(method, path)` the app serves beneath one path prefix."""
    return sorted((m, p) for m, p in served_routes(app) if p.startswith(prefix))
