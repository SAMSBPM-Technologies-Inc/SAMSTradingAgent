"""
GET  /watchlist       — all tracked tickers ranked by conviction → score
POST /ticker          — add a new ticker to the watch list and run it immediately
DELETE /ticker/{t}    — remove a ticker from the watch list
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.db import COLL_SIGNALS, COLL_WATCHED, get_db
from app.models.stock import (
    TickerAddRequest,
    TickerAddResponse,
    WatchlistItem,
    WatchlistResponse,
)
from app.utils.logger import get_logger

router = APIRouter(tags=["watchlist"])
logger = get_logger(__name__)

_CONVICTION_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, None: 0}


@router.get("/watchlist", response_model=WatchlistResponse, summary="All tracked tickers ranked by conviction")
async def get_watchlist() -> WatchlistResponse:
    """
    Return all tickers that have a signal, ranked by:
      1. AI conviction (HIGH > MEDIUM > LOW > none)
      2. Composite score descending
    """
    db = await get_db()
    docs = await db[COLL_SIGNALS].find({}).to_list(length=500)

    items = []
    for doc in docs:
        ao = doc.get("analyst_output") or {}
        generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
        if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        items.append(WatchlistItem(
            ticker=doc["ticker"],
            signal=doc.get("signal", "HOLD"),
            score=doc.get("score", 0.0),
            confidence=doc.get("confidence", 0.0),
            conviction=ao.get("conviction"),
            price_target=ao.get("price_target"),
            thesis=ao.get("thesis"),
            generated_at=generated_at,
        ))

    items.sort(
        key=lambda x: (_CONVICTION_RANK[x.conviction], x.score),
        reverse=True,
    )
    return WatchlistResponse(count=len(items), items=items)


@router.post("/ticker", response_model=TickerAddResponse, summary="Add a ticker to the watch list")
async def add_ticker(
    body: TickerAddRequest,
    background_tasks: BackgroundTasks,
) -> TickerAddResponse:
    """
    Add a ticker to the permanent watch list (stored in MongoDB) and
    immediately trigger a background pipeline run for it.
    """
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    db = await get_db()
    await db[COLL_WATCHED].update_one(
        {"ticker": ticker},
        {"$set": {"ticker": ticker}},
        upsert=True,
    )

    # Kick off pipeline in background so the response is instant
    background_tasks.add_task(_run_pipeline_bg, ticker)
    logger.info("ticker_added", ticker=ticker)

    return TickerAddResponse(
        ticker=ticker,
        status="accepted",
        message=f"{ticker} added to watch list. Analysis is running in the background.",
    )


@router.delete("/ticker/{ticker}", summary="Remove a ticker from the watch list")
async def remove_ticker(ticker: str):
    """Remove a user-added ticker from the watch list."""
    ticker = ticker.upper().strip()
    db = await get_db()
    result = await db[COLL_WATCHED].delete_one({"ticker": ticker})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in the custom watch list.")
    logger.info("ticker_removed", ticker=ticker)
    return {"ticker": ticker, "status": "removed"}


async def _run_pipeline_bg(ticker: str) -> None:
    try:
        from app.services.pipeline import run_pipeline
        await run_pipeline(ticker)
        logger.info("bg_pipeline_complete", ticker=ticker)
    except Exception as exc:
        logger.error("bg_pipeline_failed", ticker=ticker, error=str(exc))
