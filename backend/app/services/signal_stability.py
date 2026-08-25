"""
Signal Stability
────────────────
Decides which verdict is *published* — shown in the UI, alerted on, and acted
on — given the verdict this cycle produced.

Why this layer exists
─────────────────────
On 24 Aug 2026 HXL alerted eight times in sixty-five minutes, alternating
BUY → HOLD → BUY → HOLD, with the composite score reported as 61 and confidence
as 55% in every single message. Nothing about the stock had changed. Two
separate mechanisms produced that:

  * The analyst cache never hit (`analyst_used` was not persisted), so Claude
    was re-run every ingestion cycle. Re-sampling a language model on unchanged
    inputs is a coin flip whenever the setup is genuinely borderline, and it
    re-drew the price target each time — $101, $102, $103, $104 — which is what
    made the alerts look arbitrary.
  * Nothing anywhere required a verdict to be *stable* before it was published.
    A single evaluation, however marginal, went straight to the user's phone and
    into the proposal queue.

Fixing the cache reduces the sampling rate. It cannot make a marginal call
stable, because the underlying score really is sitting on a threshold — and at
that point flipping is the honest reading of the data. The right response is to
say nothing until the reading holds, not to broadcast every oscillation.

The rules
─────────
  1. A verdict that agrees with the published one is published immediately and
     clears any pending candidate.
  2. A *new* verdict becomes a pending candidate. It publishes only once it has
     been produced by `confirmations` consecutive fresh evaluations AND the
     currently published verdict has stood for `min_dwell_minutes`.
  3. SELL is exempt from both. A stop-out is not a matter of taste and delaying
     it costs real money, so the same asymmetry that governs the risk gate in
     `signal_generator.classify_signal` governs the delay: never make it harder
     to leave a position than to enter one.
  4. A ticker with no published verdict yet publishes immediately — the first
     reading is not a flip.

"Fresh evaluation" means a cycle that actually recomputed a verdict. Cycles
served from the analyst cache never reach this function, so `confirmations` is
counted in analyses, not in wall-clock ticks, and a 5-minute cache-hit does not
quietly confirm anything.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Fields this module owns on a `stocks_signals` document. Grouped under one
#: key so a signal doc can be read at a glance without the debounce bookkeeping
#: mixed into the verdict fields.
STABILITY_FIELD = "stability"

#: Verdicts that publish the moment they are produced, no confirmation, no
#: dwell. See rule 3.
_IMMEDIATE = ("SELL",)


@dataclass(frozen=True)
class StabilityState:
    """The debounce bookkeeping carried on a signal document."""

    pending_signal: str | None = None
    pending_since: datetime | None = None
    pending_count: int = 0
    last_published_change: datetime | None = None

    @classmethod
    def from_doc(cls, doc: dict | None) -> "StabilityState":
        raw = ((doc or {}).get(STABILITY_FIELD) or {}) if doc else {}
        return cls(
            pending_signal=raw.get("pending_signal"),
            pending_since=_aware(raw.get("pending_since")),
            pending_count=int(raw.get("pending_count") or 0),
            last_published_change=_aware(raw.get("last_published_change")),
        )

    def to_doc(self) -> dict:
        return {
            "pending_signal": self.pending_signal,
            "pending_since": self.pending_since,
            "pending_count": self.pending_count,
            "last_published_change": self.last_published_change,
        }


@dataclass(frozen=True)
class StabilityDecision:
    """What to publish, and why."""

    signal: str
    #: True when `signal` differs from what was previously published. The only
    #: thing that may fire an alert or reach the trade path.
    changed: bool
    state: StabilityState
    reason: str

    @property
    def held_back(self) -> str | None:
        """The candidate being withheld, if any — for the UI and for logs."""
        return self.state.pending_signal


def stabilise(
    *,
    published: str | None,
    candidate: str,
    now: datetime,
    state: StabilityState,
    confirmations: int,
    min_dwell_minutes: int,
) -> StabilityDecision:
    """
    Resolve this cycle's `candidate` verdict against the `published` one.

    Pure: every input is passed in and the caller persists `decision.state`.
    """
    # Rule 4 — nothing published yet.
    if published is None:
        return StabilityDecision(
            signal=candidate,
            changed=False,
            state=StabilityState(last_published_change=now),
            reason="first_signal",
        )

    # Rule 1 — agreement. Any half-formed candidate is abandoned; a flip that
    # did not survive to confirmation must not linger and combine with an
    # unrelated one an hour later.
    if candidate == published:
        return StabilityDecision(
            signal=published,
            changed=False,
            state=StabilityState(
                last_published_change=state.last_published_change or now
            ),
            reason="unchanged",
        )

    # Rule 3 — exits are never delayed.
    if candidate in _IMMEDIATE:
        return StabilityDecision(
            signal=candidate,
            changed=True,
            state=StabilityState(last_published_change=now),
            reason=f"immediate_{candidate.lower()}",
        )

    # Rule 2 — accumulate confirmation for a new candidate.
    if candidate == state.pending_signal:
        count = state.pending_count + 1
        pending_since = state.pending_since or now
    else:
        count = 1
        pending_since = now

    dwell_ok, dwell_reason = _dwell_satisfied(
        state.last_published_change, now, min_dwell_minutes
    )

    if count >= max(1, confirmations) and dwell_ok:
        return StabilityDecision(
            signal=candidate,
            changed=True,
            state=StabilityState(last_published_change=now),
            reason=f"confirmed_after_{count}",
        )

    return StabilityDecision(
        signal=published,
        changed=False,
        state=StabilityState(
            pending_signal=candidate,
            pending_since=pending_since,
            pending_count=count,
            last_published_change=state.last_published_change,
        ),
        reason=(
            f"awaiting_confirmation_{count}_of_{max(1, confirmations)}"
            if count < max(1, confirmations)
            else dwell_reason
        ),
    )


def _dwell_satisfied(
    last_change: datetime | None, now: datetime, min_dwell_minutes: int
) -> tuple[bool, str]:
    """Has the published verdict stood long enough to be replaced?"""
    if min_dwell_minutes <= 0 or last_change is None:
        return True, "no_dwell_required"
    elapsed = now - _aware(last_change)
    if elapsed >= timedelta(minutes=min_dwell_minutes):
        return True, "dwell_satisfied"
    remaining = timedelta(minutes=min_dwell_minutes) - elapsed
    return False, f"dwell_{int(remaining.total_seconds() // 60)}min_remaining"


def _aware(value):
    """
    Normalise a Mongo datetime to UTC-aware.

    Motor returns naive datetimes for values written as aware ones, and
    subtracting a naive from an aware raises — inside a fire-and-forget pipeline
    step that would be swallowed and the debounce would silently never engage.
    """
    from datetime import timezone

    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
