"""
GET /analyze?ticker=PLTR  — run or return cached analysis for a ticker
GET /backtest             — backtest stub
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import COLL_SIGNALS, get_db
from app.dependencies import get_current_user
from app.models.stock import AnalyzeResponse
from app.services.pipeline import run_pipeline
from app.utils.logger import get_logger

router = APIRouter(tags=["analysis"])
logger = get_logger(__name__)

_CACHE_TTL_MINUTES = 5


@router.get("/analyze", response_model=AnalyzeResponse, summary="Analyse a stock ticker")
async def analyze(
    ticker: str = Query(..., description="Stock ticker symbol, e.g. PLTR"),
    force_refresh: bool = Query(False),
    current_user: dict = Depends(get_current_user),
) -> AnalyzeResponse:
    ticker = ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    db = await get_db()

    if not force_refresh:
        cached = await db[COLL_SIGNALS].find_one({"ticker": ticker})
        if cached:
            generated_at = cached.get("generated_at")
            if isinstance(generated_at, datetime):
                age = datetime.now(tz=timezone.utc) - generated_at.replace(tzinfo=timezone.utc)
                if age < timedelta(minutes=_CACHE_TTL_MINUTES):
                    logger.info("cache_hit", ticker=ticker, age_seconds=age.seconds)
                    return _doc_to_response(cached)

    try:
        signal_doc = await run_pipeline(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("analyze_error", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    return _doc_to_response(signal_doc)


@router.get("/backtest", summary="Run backtest for a ticker (stub)")
async def backtest(
    ticker: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    from app.config import get_settings
    if not get_settings().enable_backtesting:
        raise HTTPException(status_code=403, detail="Backtesting is disabled. Set ENABLE_BACKTESTING=true.")

    ticker = ticker.upper().strip()
    db = await get_db()
    raw_doc = await db["stocks_raw"].find_one({"ticker": ticker})
    if not raw_doc:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}. Run /analyze first.")

    from app.services.backtesting import run_backtest
    return run_backtest(ticker, raw_doc.get("bars", []))


def _doc_to_response(doc: dict) -> AnalyzeResponse:
    risk = doc.get("risk", {})
    generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
    if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    ao = doc.get("analyst_output") or {}
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
        conviction=ao.get("conviction"),
        price_target=ao.get("price_target"),
        stop_loss=ao.get("stop_loss"),
        time_horizon=ao.get("time_horizon"),
        thesis=ao.get("thesis"),
        analyst_note=ao.get("analyst_note"),
    )
