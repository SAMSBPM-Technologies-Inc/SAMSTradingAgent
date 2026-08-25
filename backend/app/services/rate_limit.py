"""
Login Rate Limiting
───────────────────
`/auth/login` had no limit of any kind: an attacker with a known email could
guess passwords at whatever rate the network allowed. bcrypt makes each attempt
slow, which helps and is not a substitute.

Deliberately in-process rather than Redis-backed. This deploys as a single API
container, so a shared store would add a dependency and a failure mode to buy
correctness the topology does not currently need. The trade is stated rather
than hidden: **counters reset when the process restarts, and a second replica
would each keep their own.** If this ever runs more than one instance, move the
store behind the same interface rather than leaving it silently weakened.

Two keys are tracked per attempt, and both must pass:

    email   stops a slow grind against one account from many addresses
    client  stops one address spraying many accounts

Failures count; successes clear the email's record immediately, so a legitimate
user who mistypes twice and then succeeds is not carrying a penalty afterwards.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Attempts allowed inside the window before a key is locked out.
MAX_ATTEMPTS = 8
#: Sliding window, seconds.
WINDOW_SECONDS = 300
#: How long a key stays locked once it trips.
#:
#: Long enough to make guessing pointless, short enough that locking yourself
#: out is an inconvenience rather than an incident — there is no admin console
#: to clear it, so a lockout measured in hours would mean a server restart.
LOCKOUT_SECONDS = 900


@dataclass
class LimitDecision:
    allowed: bool
    retry_after: int = 0


class _SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def check(self, key: str) -> LimitDecision:
        now = time.monotonic()

        locked_until = self._locked_until.get(key)
        if locked_until is not None:
            if now < locked_until:
                return LimitDecision(False, int(locked_until - now) + 1)
            # Lockout expired — clear it and the history that caused it, so the
            # user gets a full fresh window rather than tripping again instantly.
            del self._locked_until[key]
            self._hits.pop(key, None)

        return LimitDecision(True)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        hits.append(now)
        cutoff = now - WINDOW_SECONDS
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= MAX_ATTEMPTS:
            self._locked_until[key] = now + LOCKOUT_SECONDS
            hits.clear()

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)
        self._locked_until.pop(key, None)

    def prune(self) -> None:
        """
        Drop keys with nothing live in them.

        Without this the dicts grow once per distinct email or address seen —
        an unauthenticated endpoint, so an attacker controls how many. Called
        opportunistically rather than on a timer.
        """
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            if key not in self._locked_until:
                self._hits.pop(key, None)
        for key in [k for k, until in self._locked_until.items() if until <= now]:
            self._locked_until.pop(key, None)
            self._hits.pop(key, None)


_by_email = _SlidingWindow()
_by_client = _SlidingWindow()

_prune_counter = 0
_PRUNE_EVERY = 200


def check_login_allowed(email: str, client_ip: str) -> LimitDecision:
    """Whether this login attempt may proceed. Does not record anything."""
    global _prune_counter
    _prune_counter += 1
    if _prune_counter % _PRUNE_EVERY == 0:
        _by_email.prune()
        _by_client.prune()

    for window, key in ((_by_email, email.lower()), (_by_client, client_ip)):
        decision = window.check(key)
        if not decision.allowed:
            return decision
    return LimitDecision(True)


def record_login_failure(email: str, client_ip: str) -> None:
    """Count a failed attempt against both keys."""
    _by_email.record_failure(email.lower())
    _by_client.record_failure(client_ip)


def record_login_success(email: str, client_ip: str) -> None:
    """
    Clear the email's history on success.

    The client key is deliberately *not* cleared: one valid credential should
    not buy an address unlimited guesses at every other account.
    """
    _by_email.clear(email.lower())


def reset_for_tests() -> None:
    """Drop all state. Test seam only."""
    _by_email.__init__()   # type: ignore[misc]
    _by_client.__init__()  # type: ignore[misc]
