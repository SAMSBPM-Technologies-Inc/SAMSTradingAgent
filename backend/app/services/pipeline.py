"""
Full Analysis Pipeline
──────────────────────
Orchestrates: ingest → features → score → signal for one ticker.
Used by both the /analyze API endpoint and the background scheduler.
"""
from app.services.feature_engineering import compute_features
from app.services.ingestion import ingest_ticker
from app.services.scoring import score_ticker
from app.services.signal_generator import generate_signal
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(ticker: str) -> dict:
    """
    Run the full pipeline for a single ticker.
    Returns the signal document (which contains scores and risk info).
    """
    ticker = ticker.upper()
    logger.info("pipeline_start", ticker=ticker)

    await ingest_ticker(ticker)
    await compute_features(ticker)
    await score_ticker(ticker)
    signal = await generate_signal(ticker)

    logger.info("pipeline_complete", ticker=ticker, signal=signal.get("signal"))
    return signal


async def run_pipeline_all(tickers: list[str]) -> dict[str, str]:
    """Run the pipeline for a list of tickers; returns ticker → 'ok' | error."""
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await run_pipeline(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            logger.error("pipeline_failed", ticker=ticker, error=str(exc))
            results[ticker] = str(exc)
    return results
