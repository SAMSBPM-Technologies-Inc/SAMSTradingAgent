"""
Full Analysis Pipeline
──────────────────────
Orchestrates: ingest → features → score → [AI analyst | rule-based signal]

When ENABLE_AI_ANALYST=true and ANTHROPIC_API_KEY is set, the AI analyst
produces the signal. Otherwise (or on failure) falls back to the rule-based
signal_generator.
"""
from app.config import get_settings
from app.services.feature_engineering import compute_features
from app.services.ingestion import ingest_ticker
from app.services.scoring import score_ticker
from app.services.signal_generator import generate_signal
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(ticker: str) -> dict:
    """
    Run the full pipeline for a single ticker.
    Returns the signal document (scores, risk, signal, analyst output if enabled).
    """
    ticker = ticker.upper()
    logger.info("pipeline_start", ticker=ticker)

    await ingest_ticker(ticker)
    await compute_features(ticker)
    await score_ticker(ticker)

    settings = get_settings()
    signal = None

    if settings.enable_ai_analyst and settings.anthropic_api_key:
        from app.services.analyst import run_analysis
        try:
            signal = await run_analysis(ticker)
            if signal:
                logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst", signal=signal.get("signal"))
                return signal
        except Exception as exc:
            logger.warning("analyst_failed_falling_back", ticker=ticker, error=str(exc))

    # Fallback: rule-based signal generator
    signal = await generate_signal(ticker)
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
