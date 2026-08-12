"""
GET /report/{ticker} — full AI analyst report (auth required)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.db import COLL_SIGNALS, get_db
from app.dependencies import require_tier
from app.models.stock import AnalystReport
from app.utils.logger import get_logger

router = APIRouter(tags=["report"])
logger = get_logger(__name__)


@router.get("/report/{ticker}", response_model=AnalystReport, summary="Full AI analyst report for a ticker")
async def get_report(ticker: str, current_user: dict = Depends(require_tier(2))) -> AnalystReport:
    ticker = ticker.upper().strip()
    db = await get_db()

    doc = await db[COLL_SIGNALS].find_one({"ticker": ticker})
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"No signal found for {ticker}. Run GET /analyze?ticker={ticker} first.",
        )

    ao = doc.get("analyst_output")
    if not ao:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No AI analyst output for {ticker}. "
                "Enable ENABLE_AI_ANALYST=true and run /analyze?force_refresh=true."
            ),
        )

    risk = doc.get("risk", {})
    generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
    if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    return AnalystReport(
        ticker=doc["ticker"],
        score=doc.get("score", 0.0),
        risk=risk,
        signal=doc.get("signal", "HOLD"),
        confidence=doc.get("confidence", 0.0),
        conviction=ao.get("conviction"),
        price_target=ao.get("price_target"),
        stop_loss=ao.get("stop_loss"),
        time_horizon=ao.get("time_horizon"),
        thesis=ao.get("thesis"),
        bull_case=ao.get("bull_case"),
        bear_case=ao.get("bear_case"),
        key_risks=ao.get("key_risks") or [],
        catalysts=ao.get("catalysts") or [],
        analyst_note=ao.get("analyst_note"),
        entry_suggestion=doc.get("entry_suggestion"),
        exit_suggestion=doc.get("exit_suggestion"),
        explanation=doc.get("explanation", ""),
        generated_at=generated_at,
    )
