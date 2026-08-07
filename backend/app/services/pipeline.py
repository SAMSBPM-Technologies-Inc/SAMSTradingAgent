"""
Full Analysis Pipeline
──────────────────────
Orchestrates: ingest → features → score → [AI analyst | rule-based signal]

When ENABLE_AI_ANALYST=true and ANTHROPIC_API_KEY is set, the AI analyst
produces the signal. Otherwise (or on failure) falls back to the rule-based
signal_generator.

Every pipeline run appends a record to stocks_signal_history for performance
tracking (realized returns are filled in later by the performance tracker job).
"""
from app.config import get_settings
from app.db import COLL_SIGNAL_HISTORY, get_db
from app.services.feature_engineering import compute_features
from app.services.ingestion import ingest_ticker
from app.services.scoring import score_ticker
from app.services.signal_generator import generate_signal
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(ticker: str) -> dict:
    """
    Run the full pipeline for a single ticker.
    Returns the signal document and appends a history record.
    """
    ticker = ticker.upper()
    logger.info("pipeline_start", ticker=ticker)

    raw_doc = await ingest_ticker(ticker)
    await compute_features(ticker)
    await score_ticker(ticker)

    settings = get_settings()
    signal = None

    if settings.enable_ai_analyst and settings.anthropic_api_key:
        from app.services.analyst import run_analysis
        try:
            signal = await run_analysis(ticker)
            if signal:
                await _append_history(signal, raw_doc)
                logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst", signal=signal.get("signal"))
                return signal
        except Exception as exc:
            logger.warning("analyst_failed_falling_back", ticker=ticker, error=str(exc))

    signal = await generate_signal(ticker)
    await _append_history(signal, raw_doc)
    logger.info("pipeline_complete", ticker=ticker, mode="rule_based", signal=signal.get("signal"))
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


# ── History helpers ───────────────────────────────────────────────────────────

async def _append_history(signal: dict, raw_doc: dict) -> None:
    """Append a lightweight record to stocks_signal_history for perf tracking."""
    try:
        db = await get_db()
        ao = signal.get("analyst_output") or {}
        record = {
            "ticker":          signal["ticker"],
            "generated_at":    signal.get("generated_at", utcnow()),
            "signal":          signal.get("signal", "HOLD"),
            "score":           signal.get("score", 0.0),
            "confidence":      signal.get("confidence", 0.0),
            "conviction":      ao.get("conviction"),
            "price_at_signal": raw_doc.get("current_price"),
            # Filled by performance tracker after 20 trading days:
            "price_20d_later": None,
            "return_20d":      None,
            "was_correct":     None,
        }
        await db[COLL_SIGNAL_HISTORY].insert_one(record)
    except Exception as exc:
        logger.warning("history_append_failed", ticker=signal.get("ticker"), error=str(exc))
