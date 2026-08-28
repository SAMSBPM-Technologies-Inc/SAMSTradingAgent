"""
Whether a research dossier blocks a BUY — and, separately, whether it would.

The decision used to live inside `trade_manager._research_veto`, tangled with
the database read and the logging, and it returned a bare string. That was
enough for the guard chain and nothing else: the only way to discover that
research was standing on a ticker was to attempt a buy and read the refusal
afterwards, in an order-history row. A standing condition that can only be
observed by tripping over it is not a condition anyone can plan around.

So the judgement is a pure function over a dossier and the settings, and it
reports more than a verdict:

    blocking     what actually stops a BUY right now
    would_block  what the dossier says, ignoring whether the veto is switched on

Those two are deliberately separate. `RESEARCH_VETO_ENABLED` defaults to false,
so on most deployments the interesting answer is the second one — "research
reads this name as BEARISH, and would refuse the entry if you turned the veto
on" is exactly the sentence a user needs before deciding to turn it on. Folding
the flag into a single boolean would hide it.

Nothing here reads a database or a clock. `age_hours` arrives on the dossier
from `latest_dossier`, which is the only place staleness is measured.
"""
from dataclasses import dataclass, asdict
from typing import Any, Optional

from app.config import get_settings


@dataclass(frozen=True)
class VetoStatus:
    """
    The veto's reading of one dossier.

    `blocking` is the only field the guard chain consults. Everything else
    exists so a client can explain the state rather than assert it.
    """

    #: RESEARCH_VETO_ENABLED. When false, `blocking` is always false no matter
    #: what the dossier says.
    enabled: bool
    #: A dossier exists and is fresh enough to be capable of vetoing. False for
    #: a missing, undated, or stale dossier — each of which allows the trade.
    considered: bool
    #: The dossier meets a blocking trigger, regardless of the flag.
    would_block: bool
    #: `enabled and would_block`. What `_prepare_entry` acts on.
    blocking: bool
    #: Present whenever `would_block`. Phrased as the refusal a user would see.
    reason: Optional[str] = None
    #: Which trigger fired: "bearish" | "low_conviction" | None.
    trigger: Optional[str] = None
    assessment: Optional[str] = None
    research_conviction: Optional[float] = None
    #: The floor conviction must clear, so a client can show the distance to it
    #: rather than a number with no scale.
    min_conviction: float = 0.0
    age_hours: Optional[float] = None
    max_age_hours: int = 0
    #: Why the dossier was not considered: "no_dossier" | "undated" | "stale".
    #: None when it was.
    not_considered_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_veto(dossier: Optional[dict], settings: Any = None) -> VetoStatus:
    """
    Read *dossier* and report whether it blocks a BUY.

    Two triggers, both explicit statements rather than absences: an assessment
    of BEARISH, and conviction below the configured floor. A dossier that
    merely failed to reach a view blocks nothing — failing to form an opinion
    is not the same as forming a negative one.

    Every uncertain path allows the trade. No dossier, an undated one, a stale
    one, a conviction that could not be derived: all return `blocking=False`.
    That is a deliberate choice rather than laziness — the alternative is that
    a scheduler outage or an empty collection silently halts all buying, and a
    system that stops trading for a reason nobody can see is a worse failure
    than one that trades without an extra opinion.
    """
    env = settings or get_settings()
    enabled = bool(env.research_veto_enabled)
    floor = float(env.research_veto_min_conviction)
    max_age = int(env.research_veto_max_age_hours)

    def _allow(not_considered: Optional[str], **extra: Any) -> VetoStatus:
        return VetoStatus(
            enabled=enabled, considered=not_considered is None,
            would_block=False, blocking=False,
            min_conviction=floor, max_age_hours=max_age,
            not_considered_reason=not_considered, **extra,
        )

    if not dossier:
        return _allow("no_dossier")

    age_hours = dossier.get("age_hours")
    conviction = research_conviction_of(dossier)
    report = dossier.get("report") or {}
    assessment = (report.get("assessment") or "").upper() or None

    if age_hours is None:
        return _allow("undated", assessment=assessment,
                      research_conviction=conviction)
    if age_hours > max_age:
        return _allow("stale", assessment=assessment,
                      research_conviction=conviction, age_hours=age_hours)

    def _block(trigger: str, reason: str) -> VetoStatus:
        return VetoStatus(
            enabled=enabled, considered=True, would_block=True,
            # The flag is the only thing standing between a reading and a
            # refusal. Keeping them separate is what lets the UI say "this
            # would be blocked" on a deployment where the veto is off.
            blocking=enabled,
            reason=reason, trigger=trigger, assessment=assessment,
            research_conviction=conviction, min_conviction=floor,
            age_hours=age_hours, max_age_hours=max_age,
        )

    if assessment == "BEARISH":
        # Named rather than implied: this sentence is stored on a SKIPPED trade
        # row and read later, out of the context that produced it.
        subject = dossier.get("ticker")
        return _block(
            "bearish",
            f"Research veto: the {age_phrase(age_hours)} dossier"
            + (f" for {subject}" if subject else "")
            + " reads BEARISH",
        )

    # A floor is a minimum to clear, not a value to fail on — conviction
    # exactly at the floor passes.
    if conviction is not None and conviction < floor:
        return _block(
            "low_conviction",
            f"Research veto: conviction {conviction:.0f}/100 is below the "
            f"{floor:.0f} floor ({age_phrase(age_hours)} dossier)",
        )

    return VetoStatus(
        enabled=enabled, considered=True, would_block=False, blocking=False,
        assessment=assessment, research_conviction=conviction,
        min_conviction=floor, age_hours=age_hours, max_age_hours=max_age,
    )


def research_conviction_of(dossier: dict) -> Optional[float]:
    """
    The dossier's 0-100 conviction, whichever key it was stored under.

    Dossiers written before the field was renamed carry `conviction`; the
    analyst's own HIGH/MEDIUM/LOW conviction now owns that bare name, and this
    one is `research_conviction` everywhere it leaves the research module. The
    fallback is not permanent scaffolding so much as an acknowledgement that
    dossiers are a retained series — old documents are still read, and a veto
    that silently stopped evaluating them would look identical to a veto that
    found nothing wrong.
    """
    value = dossier.get("research_conviction")
    if value is None:
        value = dossier.get("conviction")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def age_phrase(age_hours: Optional[float]) -> str:
    """Human phrasing for dossier age, so a skip reason says how fresh it was."""
    if age_hours is None:
        return "undated"
    if age_hours < 1:
        return "current"
    if age_hours < 24:
        return f"{age_hours:.0f}h-old"
    return f"{age_hours / 24:.0f}d-old"
