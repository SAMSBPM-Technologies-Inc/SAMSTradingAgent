"""
The shape of "what is working right now".

Field discipline follows `ResearchVetoStatus`: **configured and working are
separate fields and must stay separate.** A source with no key is not broken,
and a model that collapsed the two into one boolean would make that impossible
to say — the same reason `blocking` and `would_block` are two fields rather than
one.

`impact` carries what the absence *costs*, in the words
`docs/12-how-a-trade-is-judged.md` uses, because it is served from the same
table the document quotes. A status row that says "FRED: failed" tells a trader
nothing they can act on.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: `ok` — working. `stale` — a real answer, served from a cache past its
#: freshness window. `degraded` — answering with less than it should.
#: `failed` — configured and erroring. `not_configured` — no key, which is a
#: choice rather than a fault. `never_run` — nothing recorded yet.
SourceState = Literal["ok", "stale", "degraded", "failed", "not_configured", "never_run"]


class CapabilityStatus(BaseModel):
    """One thing that can be working or not, and what it is worth."""

    id: str
    label: str
    #: `stops` (trading pauses), `behaviour` (a different decision path runs),
    #: `quiet` (a factor goes neutral and the verdict still publishes).
    tier: Literal["stops", "behaviour", "quiet"]
    #: The environment variable that switches it on, when one does.
    required_key: Optional[str] = None
    #: What the system does without it.
    impact: str
    #: Which factor it feeds, and that factor's default weight.
    feeds: Optional[str] = None
    #: Whether this deployment has switched it on at all.
    configured: bool
    state: SourceState
    #: What is happening, as opposed to what it would mean.
    detail: str
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    consecutive_failures: int = 0


class CycleStatus(BaseModel):
    """
    Whether the analysis loop itself is running.

    The precondition for reading anything else: every capability row describes
    the last cycle, so a cycle that has not run for six hours makes all of them
    meaningless. `stale` is judged against the market clock — outside trading
    hours the pipeline is not scheduled, and reporting that as an outage every
    night is the fastest way to build a page nobody believes.
    """

    last_run_at: Optional[datetime] = None
    age_minutes: Optional[int] = None
    stale: bool = False
    tickers_ok: Optional[int] = None
    tickers_total: Optional[int] = None
    failed_tickers: list[str] = []
    last_error: Optional[str] = None


class SystemStatusResponse(BaseModel):
    """
    The whole answer to "is this thing working".

    `overall` and `summary` are decided on the server and rendered verbatim by
    both clients. Neither composes its own sentence, so web and mobile cannot
    end up disagreeing about what "degraded" means — the same reasoning behind
    `restart_unavailable_reason`.
    """

    overall: Literal["ok", "degraded", "halted"]
    summary: str
    checked_at: datetime
    #: Reported so the client never has to guess why nothing has run since 16:00.
    market_open: bool
    cycle: CycleStatus
    capabilities: list[CapabilityStatus] = Field(default_factory=list)
