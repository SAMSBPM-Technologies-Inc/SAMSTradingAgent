"""
GET /signals
────────────
Returns the latest signals for all tracked tickers stored in MongoDB.
Supports optional filtering by signal type or minimum confidence.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.db import COLL_SIGNALS, get_db
from app.models.stock import AnalyzeResponse, SignalListResponse, SignalSummary
from app.utils.logger import get_logger

router = APIRouter(tags=["signals"])
logger = get_logger(__name__)


@router.get("/signals", response_model=SignalListResponse, summary="List latest signals")
async def list_signals(
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = Query(
        None, description="Filter by signal type"
    ),
    min_confidence: float = Query(0.0, ge=0, le=1, description="Minimum confidence threshold"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> SignalListResponse:
    """
    Return the most recent signal for every tracked ticker.
    Optionally filter by signal type or confidence.
    """
    db = await get_db()
    query: dict = {}
    if signal:
        query["signal"] = signal
    if min_confidence > 0:
        query["confidence"] = {"$gte": min_confidence}

    cursor = db[COLL_SIGNALS].find(query).sort("generated_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)

    responses = [_doc_to_response(d) for d in docs]
    return SignalListResponse(count=len(responses), signals=responses)


@router.get("/signals/summary", response_model=SignalSummary, summary="Portfolio-level signal summary")
async def signals_summary() -> SignalSummary:
    """
    Return a portfolio-level snapshot: counts by signal type, average score,
    and a list of high-conviction tickers (conviction=HIGH or confidence≥0.75).
    """
    db = await get_db()
    docs = await db[COLL_SIGNALS].find({}).to_list(length=500)

    responses = [_doc_to_response(d) for d in docs]
    buy  = sum(1 for r in responses if r.signal == "BUY")
    sell = sum(1 for r in responses if r.signal == "SELL")
    hold = sum(1 for r in responses if r.signal == "HOLD")

    avg_score = round(sum(r.score for r in responses) / len(responses), 4) if responses else 0.0
    avg_conf  = round(sum(r.confidence for r in responses) / len(responses), 4) if responses else 0.0

    high_conviction = [
        r.ticker for r in responses
        if r.conviction == "HIGH" or r.confidence >= 0.75
    ]

    return SignalSummary(
        total_tickers=len(responses),
        buy_count=buy,
        sell_count=sell,
        hold_count=hold,
        avg_score=avg_score,
        avg_confidence=avg_conf,
        high_conviction_tickers=sorted(high_conviction),
        signals=sorted(responses, key=lambda r: r.score, reverse=True),
    )


def _doc_to_response(doc: dict) -> AnalyzeResponse:
    risk = doc.get("risk", {})
    generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
    if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    return AnalyzeResponse(
        ticker=doc["ticker"],
        score=doc.get("score", 0.0),
        risk=risk,
        signal=doc.get("signal", "HOLD"),
        confidence=doc.get("confidence", 0.0),
        entry_suggestion=doc.get("entry_suggestion"),
        exit_suggestion=doc.get("exit_suggestion"),
        explanation=doc.get("explanation", ""),
        generated_at=generated_at,
    )
