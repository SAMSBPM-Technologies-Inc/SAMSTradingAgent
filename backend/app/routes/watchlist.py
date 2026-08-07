"""
GET    /watchlist       — current user's tickers ranked by conviction → score
POST   /ticker          — add ticker to the user's watch list
DELETE /ticker/{ticker} — remove ticker from the user's watch list
"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.db import COLL_SIGNALS, COLL_WATCHED, get_db
from app.dependencies import get_current_user
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


@router.get("/watchlist", response_model=WatchlistResponse, summary="Current user's watchlist ranked by conviction")
async def get_watchlist(current_user: dict = Depends(get_current_user)) -> WatchlistResponse:
    user_id = str(current_user["_id"])
    db = await get_db()

    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    tickers = [d["ticker"] for d in watched]
    if not tickers:
        return WatchlistResponse(count=0, items=[])

    docs = await db[COLL_SIGNALS].find({"ticker": {"$in": tickers}}).to_list(length=2000)

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

    items.sort(key=lambda x: (_CONVICTION_RANK[x.conviction], x.score), reverse=True)
    return WatchlistResponse(count=len(items), items=items)


@router.post("/ticker", response_model=TickerAddResponse, summary="Add a ticker to the watch list")
async def add_ticker(
    body: TickerAddRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> TickerAddResponse:
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    user_id = str(current_user["_id"])
    db = await get_db()
    await db[COLL_WATCHED].update_one(
        {"user_id": user_id, "ticker": ticker},
        {"$set": {"user_id": user_id, "ticker": ticker}},
        upsert=True,
    )

    background_tasks.add_task(_run_pipeline_bg, ticker)
    logger.info("ticker_added", ticker=ticker, user_id=user_id)
    return TickerAddResponse(
        ticker=ticker,
        status="accepted",
        message=f"{ticker} added to watch list. Analysis is running in the background.",
    )


@router.delete("/ticker/{ticker}", summary="Remove a ticker from the watch list")
async def remove_ticker(ticker: str, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper().strip()
    user_id = str(current_user["_id"])
    db = await get_db()
    result = await db[COLL_WATCHED].delete_one({"user_id": user_id, "ticker": ticker})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in your watch list.")
    logger.info("ticker_removed", ticker=ticker, user_id=user_id)
    return {"ticker": ticker, "status": "removed"}


async def _run_pipeline_bg(ticker: str) -> None:
    try:
        from app.services.pipeline import run_pipeline
        await run_pipeline(ticker)
        logger.info("bg_pipeline_complete", ticker=ticker)
    except Exception as exc:
        logger.error("bg_pipeline_failed", ticker=ticker, error=str(exc))
