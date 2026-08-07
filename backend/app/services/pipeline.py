"""
Full Analysis Pipeline
──────────────────────
Orchestrates: ingest → features → score → [AI analyst | rule-based signal]

When ENABLE_AI_ANALYST=true and ANTHROPIC_API_KEY is set, the AI analyst
produces the signal. Otherwise (or on failure) falls back to the rule-based
signal_generator.

Every pipeline run upserts a record to stocks_signal_history keyed on
(ticker, hour_bucket) to prevent duplicates within the same hour.
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
    Returns the signal document and upserts a history record.
    """
    ticker = ticker.upper()
    logger.info("pipeline_start", ticker=ticker)

    raw_doc = await ingest_ticker(ticker)
    await compute_features(ticker)
    await score_ticker(ticker)

    data_sources = _build_data_sources(raw_doc)
    settings = get_settings()
    signal = None

    if settings.enable_ai_analyst and settings.anthropic_api_key:
        from app.services.analyst import run_analysis
        try:
            signal = await run_analysis(ticker)
            if signal:
                signal["data_sources"] = data_sources
                signal["analyst_used"] = True
                await _append_history(signal, raw_doc)
                logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst", signal=signal.get("signal"))
                return signal
        except Exception as exc:
            logger.warning("analyst_failed_falling_back", ticker=ticker, error=str(exc))

    signal = await generate_signal(ticker)
    signal["data_sources"] = data_sources
    signal["analyst_used"] = False
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_data_sources(raw_doc: dict) -> dict:
    """Extract provenance from raw_doc — indicates which sources were real vs. fallback."""
    sentiment_source = (raw_doc.get("sentiment_raw") or {}).get("source", "none")
    macro_source     = (raw_doc.get("macro") or {}).get("source", "none")
    fund             = raw_doc.get("fundamentals") or {}
    fund_source      = "yfinance" if fund.get("pe_ratio") is not None else "none"
    return {"sentiment": sentiment_source, "macro": macro_source, "fundamentals": fund_source}


async def _append_history(signal: dict, raw_doc: dict) -> None:
    """
    Upsert a history record to stocks_signal_history keyed on (ticker, hour_bucket).
    Prevents duplicate records when pipeline is triggered multiple times within one hour.
    """
    try:
        db = await get_db()
        ao = signal.get("analyst_output") or {}
        now = signal.get("generated_at", utcnow())

        # Idempotency key: same ticker within the same clock-hour = same record
        hour_bucket = now.replace(minute=0, second=0, microsecond=0)

        record = {
            "ticker":          signal["ticker"],
            "generated_at":    now,
            "signal":          signal.get("signal", "HOLD"),
            "score":           signal.get("score", 0.0),
            "confidence":      signal.get("confidence", 0.0),
            "conviction":      ao.get("conviction"),
            "price_at_signal": raw_doc.get("current_price"),
            "data_sources":    signal.get("data_sources", {}),
            "analyst_used":    signal.get("analyst_used", False),
            # Filled by performance tracker after ~20 trading days:
            "price_20d_later": None,
            "return_20d":      None,
            "was_correct":     None,
        }
        await db[COLL_SIGNAL_HISTORY].update_one(
            {"ticker": signal["ticker"], "hour_bucket": hour_bucket},
            {"$setOnInsert": record, "$set": {"hour_bucket": hour_bucket}},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("history_append_failed", ticker=signal.get("ticker"), error=str(exc))
