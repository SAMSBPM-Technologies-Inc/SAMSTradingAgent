"""
GET /analyze?ticker=PLTR
────────────────────────
Runs (or re-uses cached) the full analysis pipeline for a ticker
and returns scores, risk, and trading signal.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.db import COLL_SIGNALS, get_db
from app.models.stock import AnalyzeResponse
from app.services.pipeline import run_pipeline
from app.utils.logger import get_logger

router = APIRouter(tags=["analysis"])
logger = get_logger(__name__)

# Use cached signal if it was generated within the last N minutes
_CACHE_TTL_MINUTES = 5


@router.get("/analyze", response_model=AnalyzeResponse, summary="Analyse a stock ticker")
async def analyze(
    ticker: str = Query(..., description="Stock ticker symbol, e.g. PLTR"),
    force_refresh: bool = Query(False, description="Force re-run even if cached"),
) -> AnalyzeResponse:
    """
    Run the full AI analysis pipeline for the given ticker and return:
    - Composite AI score (0–1)
    - Risk assessment
    - Trading signal (BUY / SELL / HOLD)
    - Entry / exit suggestions
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    db = await get_db()

    # ── Check cache ───────────────────────────────────────────────────────────
    if not force_refresh:
        cached = await db[COLL_SIGNALS].find_one({"ticker": ticker})
        if cached:
            generated_at = cached.get("generated_at")
            if isinstance(generated_at, datetime):
                age = datetime.now(tz=timezone.utc) - generated_at.replace(tzinfo=timezone.utc)
                if age < timedelta(minutes=_CACHE_TTL_MINUTES):
                    logger.info("cache_hit", ticker=ticker, age_seconds=age.seconds)
                    return _doc_to_response(cached)

    # ── Run fresh pipeline ────────────────────────────────────────────────────
    try:
        signal_doc = await run_pipeline(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("analyze_error", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    return _doc_to_response(signal_doc)


# ── Bonus: backtest endpoint ──────────────────────────────────────────────────

@router.get("/backtest", summary="Run backtest for a ticker (stub)")
async def backtest(
    ticker: str = Query(..., description="Ticker symbol"),
):
    """
    Run a simplified backtest on the stored price history.
    Requires ENABLE_BACKTESTING=true.
    """
    from app.config import get_settings
    if not get_settings().enable_backtesting:
        raise HTTPException(status_code=403, detail="Backtesting is disabled. Set ENABLE_BACKTESTING=true.")

    ticker = ticker.upper().strip()
    db = await get_db()
    raw_doc = await db["stocks_raw"].find_one({"ticker": ticker})
    if not raw_doc:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}. Run /analyze first.")

    from app.services.backtesting import run_backtest
    result = run_backtest(ticker, raw_doc.get("bars", []))
    return result


# ── Helper ────────────────────────────────────────────────────────────────────

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
