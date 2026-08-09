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
from app.db import COLL_SIGNAL_HISTORY, COLL_SIGNALS, COLL_USERS, COLL_WATCHED, get_db
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

    # Capture previous signal before overwriting (for change detection)
    db = await get_db()
    prev_doc = await db[COLL_SIGNALS].find_one({"ticker": ticker}, {"signal": 1, "analyst_output": 1})
    prev_signal = prev_doc.get("signal") if prev_doc else None

    raw_doc = await ingest_ticker(ticker)
    await compute_features(ticker)
    await score_ticker(ticker)

    data_sources = _build_data_sources(raw_doc)
    settings = get_settings()
    signal = None

    current_price = raw_doc.get("current_price")
    day_change_pct = raw_doc.get("day_change_pct")
    alternative_data = raw_doc.get("alternative_data")

    if settings.enable_ai_analyst and settings.anthropic_api_key:
        from app.services.analyst import run_analysis
        try:
            signal = await run_analysis(ticker)
            if signal:
                signal["data_sources"] = data_sources
                signal["analyst_used"] = True
                signal["current_price"] = current_price
                signal["day_change_pct"] = day_change_pct
                signal["alternative_data"] = alternative_data
                await db[COLL_SIGNALS].update_one(
                    {"ticker": ticker},
                    {"$set": {"current_price": current_price, "day_change_pct": day_change_pct}},
                )
                await _append_history(signal, raw_doc)
                logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst", signal=signal.get("signal"))
                await _fire_alerts(ticker, prev_signal, signal)
                await _execute_trades(ticker, signal)
                return signal
        except Exception as exc:
            logger.warning("analyst_failed_falling_back", ticker=ticker, error=str(exc))

    signal = await generate_signal(ticker)
    signal["data_sources"] = data_sources
    signal["analyst_used"] = False
    signal["current_price"] = current_price
    signal["day_change_pct"] = day_change_pct
    signal["alternative_data"] = alternative_data
    await db[COLL_SIGNALS].update_one(
        {"ticker": ticker},
        {"$set": {"current_price": current_price, "day_change_pct": day_change_pct}},
    )
    await _append_history(signal, raw_doc)
    logger.info("pipeline_complete", ticker=ticker, mode="rule_based", signal=signal.get("signal"))
    await _fire_alerts(ticker, prev_signal, signal)
    await _execute_trades(ticker, signal)
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


async def _execute_trades(ticker: str, signal: dict) -> None:
    """
    Attempt automated trade execution for all users watching this ticker
    who have auto-trading enabled. Runs fire-and-forget — never raises.
    Global kill-switch: AUTO_TRADE_ENABLED must be True in env.
    """
    try:
        settings = get_settings()
        if not settings.auto_trade_enabled:
            return

        new_sig = signal.get("signal", "HOLD")
        score = signal.get("score", 0.0)
        current_price = signal.get("current_price")

        # Only act on BUY signals (SELL signals are handled via EXIT_ALERT from dip-buy scan)
        if new_sig != "BUY":
            return

        from bson import ObjectId
        from app.services.trade_manager import execute_entry

        db = await get_db()
        watchers = await db[COLL_WATCHED].find({"ticker": ticker}, {"user_id": 1}).to_list(length=500)
        for w in watchers:
            user_id = w["user_id"]
            await execute_entry(user_id, ticker, score, current_price)

    except Exception as exc:
        logger.warning("execute_trades_failed", ticker=ticker, error=str(exc))


async def _fire_alerts(ticker: str, prev_signal: str | None, new_signal: dict) -> None:
    """
    Notify users watching this ticker if the signal flipped or conviction is HIGH.
    Runs fire-and-forget — never raises.
    """
    try:
        new_sig = new_signal.get("signal", "HOLD")
        ao = new_signal.get("analyst_output") or {}
        conviction = ao.get("conviction")
        signal_flipped = prev_signal is not None and prev_signal != new_sig
        is_high_conviction = conviction == "HIGH"

        if not signal_flipped and not is_high_conviction:
            return

        db = await get_db()
        watchers = await db[COLL_WATCHED].find({"ticker": ticker}, {"user_id": 1}).to_list(length=500)
        if not watchers:
            return

        user_ids_str = [w["user_id"] for w in watchers]
        from bson import ObjectId
        user_ids = []
        for uid in user_ids_str:
            try:
                user_ids.append(ObjectId(uid))
            except Exception:
                pass

        users = await db[COLL_USERS].find(
            {"_id": {"$in": user_ids}},
            {"alert_settings": 1},
        ).to_list(length=500)

        from app.services.notifier import send_signal_alert
        for user in users:
            prefs = user.get("alert_settings") or {}
            webhook = prefs.get("slack_webhook_url")
            wa_phone = prefs.get("whatsapp_phone")
            wa_apikey = prefs.get("whatsapp_apikey")
            if not webhook and not (wa_phone and wa_apikey):
                continue
            if signal_flipped and not prefs.get("notify_on_signal_flip", True):
                continue
            if is_high_conviction and not signal_flipped and not prefs.get("notify_on_high_conviction", True):
                continue
            await send_signal_alert(
                webhook_url=webhook,
                ticker=ticker,
                old_signal=prev_signal if signal_flipped else None,
                new_signal=new_sig,
                score=new_signal.get("score", 0.0),
                conviction=conviction,
                confidence=new_signal.get("confidence", 0.0),
                price_target=ao.get("price_target"),
                stop_loss=ao.get("stop_loss"),
                whatsapp_phone=wa_phone,
                whatsapp_apikey=wa_apikey,
            )
    except Exception as exc:
        logger.warning("fire_alerts_failed", ticker=ticker, error=str(exc))
