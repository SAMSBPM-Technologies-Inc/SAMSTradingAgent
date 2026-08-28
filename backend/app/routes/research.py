"""
GET/POST /research/{ticker} — deep-research dossier (auth required)

Two verbs, deliberately different in cost:

    GET   reads the latest stored dossier. Free, always fast, may be stale.
    POST  builds a new one. Five model calls, tens of seconds, rate limited.

The split exists because this path is nothing like `/analyze`. That endpoint is
backed by a 30-minute cache over a pipeline that runs anyway; this one spends
real money per call, so a GET must never silently trigger a build. A client
that wants fresh data has to say so.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.db import COLL_FUNDAMENTALS_CACHE, COLL_WATCHED, get_db
from app.dependencies import get_current_user
from app.models.stock import (
    CitationAudit, PriorRecordCoverage, ResearchDebate, ResearchDossier,
    ResearchOutcome, ResearchStances, ResearchVetoStatus,
)
from app.services.research.dossier import build_dossier, latest_dossier
from app.services.research.veto import evaluate_veto
from app.utils.logger import get_logger

router = APIRouter(tags=["research"])
logger = get_logger(__name__)


@router.get("/research/{ticker}", response_model=ResearchDossier,
            summary="Latest research dossier for a ticker")
async def get_research(ticker: str,
                       current_user: dict = Depends(get_current_user)) -> ResearchDossier:
    ticker = ticker.upper().strip()
    doc = await latest_dossier(ticker)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No research dossier for {ticker}. "
                f"POST /research/{ticker} to build one."
            ),
        )
    return _to_model(doc)


@router.post("/research/{ticker}", response_model=ResearchDossier,
             summary="Build a new research dossier (slow, costs API calls)")
async def create_research(ticker: str,
                          current_user: dict = Depends(get_current_user)
                          ) -> ResearchDossier:
    settings = get_settings()
    if not settings.research_agents_enabled:
        raise HTTPException(
            status_code=503,
            detail="Deep research is disabled. Set RESEARCH_AGENTS_ENABLED=true.",
        )

    ticker = ticker.upper().strip()
    watchlist = await _watchlist_context(str(current_user.get("_id") or ""))

    dossier = await build_dossier(ticker, user_id=str(current_user.get("_id") or ""),
                                  watchlist=watchlist)
    if not dossier:
        # The common cause is a cold ticker, not a broken agent: the dossier is
        # built entirely from cached provider data, and a symbol added minutes
        # ago has none of it yet.
        raise HTTPException(
            status_code=409,
            detail=(
                f"Not enough collected data to research {ticker} yet. "
                "Add it to a watchlist and let the daily fundamentals job run, "
                "then try again."
            ),
        )
    dossier["age_hours"] = 0.0
    dossier["stale"] = False
    return _to_model(dossier)


@router.get("/research/{ticker}/veto", response_model=ResearchVetoStatus,
            summary="Whether research currently blocks a BUY on this ticker")
async def get_research_veto(ticker: str,
                            current_user: dict = Depends(get_current_user)
                            ) -> ResearchVetoStatus:
    """
    The veto reading alone, without the dossier around it.

    This exists so an order ticket can warn before the Buy button is pressed.
    It could read `GET /research/{ticker}` instead, but that response carries
    the full evidence ledger and every prose field — kilobytes of report to
    render one line of warning, fetched on every ticker the user opens.

    Never 404s. A ticker with no dossier is not an error here; it is the
    ordinary case, and the answer to "does research block this" is a truthful
    no. Returning an error would push every client into treating a missing
    dossier as a failure, which is the opposite of how the guard itself
    behaves.
    """
    ticker = ticker.upper().strip()
    doc = await latest_dossier(ticker)
    return ResearchVetoStatus(**evaluate_veto(doc).to_dict())


async def _watchlist_context(user_id: str) -> list[dict]:
    """
    The user's other watched tickers, with sector and industry.

    Used only to assemble a peer set, and it is an honest convenience rather
    than a screen — a real comparable universe is not something this system
    has. The dossier labels it as such where it is shown.
    """
    if not user_id:
        return []
    try:
        db = await get_db()
        watched = await db[COLL_WATCHED].find(
            {"user_id": user_id}, {"ticker": 1, "_id": 0}
        ).to_list(length=500)
        symbols = [row["ticker"] for row in watched if row.get("ticker")]
        if not symbols:
            return []
        rows = await db[COLL_FUNDAMENTALS_CACHE].find(
            {"ticker": {"$in": symbols}},
            {"ticker": 1, "sector": 1, "industry": 1, "_id": 0},
        ).to_list(length=500)
        return rows
    except Exception as exc:
        logger.warning("research_watchlist_context_failed", error=str(exc))
        return []


def _to_model(doc: dict) -> ResearchDossier:
    """
    Shape the stored document for the client.

    The per-agent raw output is deliberately not returned. It is kept in Mongo
    so a bad reading can be traced to the agent that produced it, but it is
    unfiltered — sending it would hand the UI a second, uncited copy of every
    claim the citation filter just removed.
    """
    as_of = doc.get("as_of")
    if isinstance(as_of, datetime):
        as_of = as_of.isoformat()
    return ResearchDossier(
        ticker=doc.get("ticker", ""),
        as_of=str(as_of or datetime.now(tz=timezone.utc).isoformat()),
        stale=bool(doc.get("stale")),
        age_hours=doc.get("age_hours"),
        research_conviction=doc.get("research_conviction"),
        derived_research_conviction=doc.get("derived_research_conviction"),
        report=doc.get("report") or None,
        dimensions=doc.get("dimensions") or [],
        evidence=doc.get("evidence") or [],
        evidence_count=doc.get("evidence_count") or 0,
        data_gaps=doc.get("data_gaps") or [],
        agents_failed=doc.get("agents_failed") or [],
        agents_skipped=doc.get("agents_skipped") or [],
        synthesis_error=doc.get("synthesis_error"),
        citation_audit=(
            CitationAudit(**doc["citation_audit"]) if doc.get("citation_audit") else None
        ),
        # Computed on read rather than stored. The veto is a function of the
        # dossier *and* the current settings, and the settings can change
        # between the build and the reading — a status frozen at build time
        # would confidently describe a threshold that no longer applies.
        veto=ResearchVetoStatus(**evaluate_veto(doc).to_dict()),
        # Present only on dossiers old enough to have been graded. The one a
        # ticker page displays is normally today's, so `None` here is the usual
        # case rather than a gap — the settled series is what the research
        # calibration arm reads.
        outcome=(
            ResearchOutcome.model_validate(doc["outcome"]) if doc.get("outcome") else None
        ),
        debate=(
            ResearchDebate.model_validate(doc["debate"]) if doc.get("debate") else None
        ),
        stances=(
            ResearchStances.model_validate(doc["stances"]) if doc.get("stances") else None
        ),
        prior_record=(
            PriorRecordCoverage(**(doc.get("coverage") or {}).get("prior_record", {}))
            if isinstance((doc.get("coverage") or {}).get("prior_record"), dict)
            else None
        ),
    )
