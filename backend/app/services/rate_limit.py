"""
Rate Limiting — login attempts and contact-form submissions
────────────────────────────────────────────────────────────
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

from app.config import get_settings
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
    """
    A sliding window with a lockout.

    The thresholds are per-instance rather than module constants because the
    two things this file now protects want different numbers: password guessing
    needs a window measured in minutes and a generous allowance for typos,
    while a public contact form needs a small hourly allowance and no allowance
    for bursts at all.
    """

    def __init__(
        self,
        max_hits: int = MAX_ATTEMPTS,
        window_seconds: int = WINDOW_SECONDS,
        lockout_seconds: int = LOCKOUT_SECONDS,
    ) -> None:
        self._max_hits = max_hits
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
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
        cutoff = now - self._window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self._max_hits:
            self._locked_until[key] = now + self._lockout_seconds
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
        cutoff = now - self._window_seconds
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


# ── Contact form ──────────────────────────────────────────────────────────────
#
# `/contact` is unauthenticated and causes an outbound email, which makes it the
# one endpoint on this API that a stranger can use to generate cost and noise.
# Unlike login, *every* submission counts — there is no such thing as a
# successful attempt that should not be charged for.
#
# Three an hour is set for a human with a follow-up question and a correction,
# and is deliberately far below anything worth automating.

#: Submissions allowed per address per window.
CONTACT_MAX_SUBMISSIONS = 3
CONTACT_WINDOW_SECONDS = 3600
CONTACT_LOCKOUT_SECONDS = 3600

_by_contact = _SlidingWindow(
    max_hits=CONTACT_MAX_SUBMISSIONS,
    window_seconds=CONTACT_WINDOW_SECONDS,
    lockout_seconds=CONTACT_LOCKOUT_SECONDS,
)


def check_contact_allowed(client_ip: str) -> LimitDecision:
    """Whether this contact submission may proceed. Does not record anything."""
    _by_contact.prune()
    return _by_contact.check(client_ip)


def record_contact_submission(client_ip: str) -> None:
    """Count a submission. Called on every accepted message, not only failures."""
    _by_contact.record_failure(client_ip)


# ── Full analysis runs ────────────────────────────────────────────────────────
#
# `GET /analyze?force_refresh=true` is the one path where a user who is not
# entitled to the deployment's model key spends it anyway. The analyst call
# happens inside `run_pipeline`, which has no `user_id` and writes a single
# shared `stocks_signals` document per ticker — so the spend genuinely cannot
# be attributed to the person who asked for it without restructuring the
# pipeline.
#
# That makes this a *quota* rather than an *entitlement*, which is why it lives
# here with the other counters and not in `services/entitlements.py`. The
# entitlement answers "may you"; this answers "how often". Keeping them in
# different modules keeps either from being mistaken for the other.
#
# Note what this is and is not. `_SlidingWindow` counts hits and then applies a
# fixed lockout, so with both durations set to a day the shape is "N runs, then
# wait" rather than a true rolling allowance where the oldest run ages out on
# its own. That is a coarser rule than the name "per day" suggests, and it is
# the one being shipped: the decision carries `retry_after`, so the refusal can
# say exactly how long rather than leaving someone guessing.

_ANALYSIS_WINDOW_SECONDS = 86400

_by_analysis = _SlidingWindow(
    max_hits=get_settings().analysis_runs_per_day,
    window_seconds=_ANALYSIS_WINDOW_SECONDS,
    lockout_seconds=_ANALYSIS_WINDOW_SECONDS,
)


def check_analysis_allowed(user_id: str) -> LimitDecision:
    """Whether this user may start another full analysis run today."""
    _by_analysis.prune()
    return _by_analysis.check(user_id)


def record_analysis_run(user_id: str) -> None:
    """Count a run. Called on every accepted rebuild, successful or not."""
    _by_analysis.record_failure(user_id)


# ── Password reset requests ───────────────────────────────────────────────────
#
# `POST /auth/forgot-password` is unauthenticated and sends mail, which puts it
# in the same category as the contact form. It is keyed on **both** the address
# and the client, like login and unlike contact: the address stops one mailbox
# being flooded by somebody who knows it, and the client stops one machine
# walking a list of addresses to see which ones exist.
#
# Note that limiting per address does not leak existence, because the counter
# is charged whether or not an account matched — a rate-limited response says
# only that this address has been asked about recently.

RESET_MAX_REQUESTS = 5
RESET_WINDOW_SECONDS = 3600
RESET_LOCKOUT_SECONDS = 3600

_by_reset_email = _SlidingWindow(
    max_hits=RESET_MAX_REQUESTS,
    window_seconds=RESET_WINDOW_SECONDS,
    lockout_seconds=RESET_LOCKOUT_SECONDS,
)
_by_reset_client = _SlidingWindow(
    max_hits=RESET_MAX_REQUESTS * 3,
    window_seconds=RESET_WINDOW_SECONDS,
    lockout_seconds=RESET_LOCKOUT_SECONDS,
)


def check_reset_allowed(email: str, client_ip: str) -> LimitDecision:
    """Whether another reset link may be requested. Records nothing."""
    _by_reset_email.prune()
    _by_reset_client.prune()
    for window, key in ((_by_reset_email, email.lower()), (_by_reset_client, client_ip)):
        decision = window.check(key)
        if not decision.allowed:
            return decision
    return LimitDecision(True)


def record_reset_request(email: str, client_ip: str) -> None:
    """
    Count a request — every one, matched account or not.

    Charging only the ones that found an account would make the rate limit
    itself an oracle: an attacker could tell a real address from a fake one by
    which of them eventually got throttled.
    """
    _by_reset_email.record_failure(email.lower())
    _by_reset_client.record_failure(client_ip)


def reset_for_tests() -> None:
    """Drop all state. Test seam only."""
    _by_email.__init__()    # type: ignore[misc]
    _by_client.__init__()   # type: ignore[misc]
    _by_contact.__init__(   # type: ignore[misc]
        max_hits=CONTACT_MAX_SUBMISSIONS,
        window_seconds=CONTACT_WINDOW_SECONDS,
        lockout_seconds=CONTACT_LOCKOUT_SECONDS,
    )
    _by_analysis.__init__(  # type: ignore[misc]
        max_hits=get_settings().analysis_runs_per_day,
        window_seconds=_ANALYSIS_WINDOW_SECONDS,
        lockout_seconds=_ANALYSIS_WINDOW_SECONDS,
    )
    _by_reset_email.__init__(   # type: ignore[misc]
        max_hits=RESET_MAX_REQUESTS,
        window_seconds=RESET_WINDOW_SECONDS,
        lockout_seconds=RESET_LOCKOUT_SECONDS,
    )
    _by_reset_client.__init__(  # type: ignore[misc]
        max_hits=RESET_MAX_REQUESTS * 3,
        window_seconds=RESET_WINDOW_SECONDS,
        lockout_seconds=RESET_LOCKOUT_SECONDS,
    )
