"""
Full Analysis Pipeline
──────────────────────
Orchestrates: ingest → features → score → [AI analyst | rule-based signal]

When ENABLE_AI_ANALYST=true and ANTHROPIC_API_KEY is set, the AI analyst
produces the signal. Otherwise (or on failure) falls back to the rule-based
signal_generator.

AI Analyst Caching
──────────────────
Claude is expensive (~$0.10-0.15 per call with Opus + extended thinking).
Running it every 5-minute cycle for every ticker is unnecessary — market
conditions meaningful enough to change a signal don't shift that fast.

Claude is re-called only when one of these triggers fires:
  1. No existing AI signal for this ticker yet
  2. Last analysis is older than ANALYST_CACHE_MINUTES (default: 60 min)
  3. Price has moved >= ANALYST_PRICE_CHANGE_PCT since last analysis (default: 3%)
  4. Composite score has shifted >= ANALYST_SCORE_CHANGE_THRESHOLD (default: 0.12)
  5. VIX >= ANALYST_VIX_SPIKE_THRESHOLD (default: 30) — re-evaluate all tickers in fear regime

Otherwise the existing signal is kept and only the live price fields are refreshed.
This reduces Claude calls by ~90% at steady state (60-ticker watchlist → 1 call/hr
per ticker vs 12 calls/hr = ~$180/day vs ~$2,160/day).

Every pipeline run upserts a record to stocks_signal_history keyed on
(ticker, hour_bucket) to prevent duplicates within the same hour.
"""
from datetime import datetime, timezone

from app.config import get_settings
from app.db import (
    COLL_FEATURES,
    COLL_SIGNAL_HISTORY,
    COLL_SIGNALS,
    COLL_TRADES,
    COLL_USERS,
    COLL_WATCHED,
    get_db,
)
from app.models.trade import TradeStatus
from app.services.feature_engineering import compute_features
from app.services.ingestion import ingest_ticker
from app.services.scoring import score_ticker
from app.services.signal_generator import BUY_THRESHOLD, SELL_THRESHOLD, generate_signal
from app.services.signal_stability import (
    STABILITY_FIELD,
    StabilityState,
    stabilise,
)
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
    prev_doc = await db[COLL_SIGNALS].find_one(
        {"ticker": ticker},
        {"signal": 1, "analyst_output": 1, STABILITY_FIELD: 1},
    )
    prev_signal = prev_doc.get("signal") if prev_doc else None
    prev_stability = StabilityState.from_doc(prev_doc)
    prev_conviction = ((prev_doc or {}).get("analyst_output") or {}).get("conviction")

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

        feat_doc = await db[COLL_FEATURES].find_one({"ticker": ticker}) or {}

        # Is this ticker close enough to a decision for Claude's judgment to
        # matter? Checked before the cache triggers, because a mid-band ticker
        # should not be analysed however stale its last look was.
        worth_calling, gate_reason = await _analyst_worth_calling(ticker, feat_doc)
        if not worth_calling:
            logger.debug("analyst_gated", ticker=ticker, reason=gate_reason)

        needs_refresh, cache_reason = await _needs_analyst_refresh(ticker, raw_doc, feat_doc)

        # Only an *analyst* signal can be served from the analyst cache. A
        # gated ticker has no live analyst verdict to reuse, so it must fall
        # through to the rule-based path and be re-scored this cycle.
        #
        # Previously this read `needs_refresh and worth_calling`, which made a
        # gated ticker look like a cache hit: `not needs_refresh` was then true
        # and the branch below returned the existing document unchanged. The
        # fall-through at `if worth_calling` was therefore unreachable whenever
        # a signal document already existed, and the rule-based path never ran.
        #
        # The effect was silent and permanent. Once a ticker's composite fell
        # below the gate its score, signal and explanation froze for good —
        # only the price fields kept updating, so it still looked alive. On
        # 21 Aug 2026 five of eleven tickers (SOFI, RKLB, PLTR, NBIS, CBRS) had
        # been stuck for 19.5 hours on pre-fix arithmetic, still carrying
        # macro=0.50 and the retired catalyst-at-zero curve, while the six
        # above the gate updated normally.
        if worth_calling and not needs_refresh:
            # Serve cached signal — just refresh live price on the existing doc.
            existing = await db[COLL_SIGNALS].find_one({"ticker": ticker})
            if existing:
                await db[COLL_SIGNALS].update_one(
                    {"ticker": ticker},
                    {"$set": {"current_price": current_price, "day_change_pct": day_change_pct}},
                )
                existing["current_price"] = current_price
                existing["day_change_pct"] = day_change_pct
                logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst_cached",
                            signal=existing.get("signal"), cache_reason=cache_reason)
                # A cached verdict is not news, so no alert and no stability
                # bookkeeping — but it is still a standing instruction, and the
                # trade path must keep retrying it. An entry skipped because the
                # gateway was down, or because funds had not settled, otherwise
                # waited for the next *analysis* rather than the next cycle. That
                # was invisible while the cache was broken, because every cycle
                # was a fresh analysis; repairing the cache would have quietly
                # stretched the retry interval from 5 minutes to an hour. The
                # call is cheap and idempotent — every guard is re-tested, an
                # open position or an outstanding proposal blocks it, and a
                # repeated skip is no longer re-recorded.
                await _execute_trades(ticker, existing)
                return existing

        # Reached when the analyst cache is stale, when there is no cached doc,
        # or when the gate rejected this ticker. Calling run_analysis for a
        # rejected ticker would defeat the gate, so only the first two cases
        # take the analyst; the rest fall through to the rule-based path, which
        # reaches the same verdict away from the thresholds — and, unlike the
        # cached document, reflects the current cycle's features.
        if worth_calling:
            try:
                signal = await run_analysis(ticker)
                if signal:
                    signal["data_sources"] = data_sources
                    signal["analyst_used"] = True
                    signal["current_price"] = current_price
                    signal["day_change_pct"] = day_change_pct
                    signal["alternative_data"] = alternative_data
                    changed = await _publish_verdict(
                        ticker, signal, prev_signal, prev_stability,
                        extra={"current_price": current_price,
                               "day_change_pct": day_change_pct},
                    )
                    await _append_history(signal, raw_doc)
                    logger.info("pipeline_complete", ticker=ticker, mode="ai_analyst",
                                signal=signal.get("signal"), cache_reason=cache_reason)
                    await _fire_alerts(ticker, prev_signal, signal,
                                       changed=changed, prev_conviction=prev_conviction)
                    await _execute_trades(ticker, signal)
                    return signal
            except Exception as exc:
                logger.warning("analyst_failed_falling_back", ticker=ticker, error=str(exc))

    # The previous verdict engages the hysteresis band, so a score oscillating
    # within a few thousandths of 0.70 does not re-decide the ticker every five
    # minutes. The stability layer below handles the rest.
    signal = await generate_signal(ticker, previous_signal=prev_signal)
    signal["data_sources"] = data_sources
    signal["analyst_used"] = False
    signal["current_price"] = current_price
    signal["day_change_pct"] = day_change_pct
    signal["alternative_data"] = alternative_data
    changed = await _publish_verdict(
        ticker, signal, prev_signal, prev_stability,
        extra={"current_price": current_price, "day_change_pct": day_change_pct},
    )
    await _append_history(signal, raw_doc)
    logger.info("pipeline_complete", ticker=ticker, mode="rule_based", signal=signal.get("signal"))
    await _fire_alerts(ticker, prev_signal, signal,
                       changed=changed, prev_conviction=prev_conviction)
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

async def _analyst_worth_calling(ticker: str, feat_doc: dict) -> tuple[bool, str]:
    """
    Decide whether Claude's judgment can change this ticker's outcome.

    A research note costs real money and its only effect is the signal it
    produces. Away from the thresholds it cannot produce anything but the HOLD
    the rule-based path already returns — and that described nearly every call:
    of 602 recorded signals, 592 were HOLD, with every live composite score
    sitting between 0.38 and 0.56 against a 0.70 BUY / 0.30 SELL boundary.

    Two cases justify the spend:
      * the score is within `analyst_gate_margin` of a real threshold, so the
        verdict is genuinely live
      * a position is open, where the exit decision is worth paying for at any
        score because capital is already committed

    The margin is measured against signal_generator's own thresholds rather
    than a hard-coded band, so moving a threshold moves the gate with it.

    Returns (should_call, reason).
    """
    settings = get_settings()
    if not settings.analyst_gate_enabled:
        return True, "gate_disabled"

    score = feat_doc.get("composite_score")
    if score is None:
        # No score means scoring failed; let the analyst look rather than
        # silently downgrade a ticker on missing data.
        return True, "no_score"

    margin = settings.analyst_gate_margin
    if score >= BUY_THRESHOLD - margin:
        return True, f"near_buy_{score:.2f}"
    if score <= SELL_THRESHOLD + margin:
        return True, f"near_sell_{score:.2f}"

    if settings.analyst_always_analyse_holdings:
        try:
            db = await get_db()
            held = await db[COLL_TRADES].find_one({
                "ticker": ticker,
                "action": "BUY",
                "status": {"$in": list(TradeStatus.OPEN)},
                "closed_at": None,
            })
            if held:
                return True, f"position_open_{score:.2f}"
        except Exception as exc:
            # Can't confirm there's no position — analyse rather than stop
            # forming a view on capital that may still be committed.
            logger.warning("analyst_gate_position_check_failed", ticker=ticker, error=str(exc))
            return True, "position_check_failed"

    return False, f"mid_range_{score:.2f}"


async def _needs_analyst_refresh(ticker: str, raw_doc: dict, feat_doc: dict) -> tuple[bool, str]:
    """
    Decide whether to call Claude or serve the cached signal.
    Returns (should_refresh, reason_string).

    Triggers a refresh when ANY of:
      1. No existing AI-analyst signal
      2. Signal older than analyst_cache_minutes
      3. Price moved >= analyst_price_change_pct since last analysis
      4. Composite score shifted >= analyst_score_change_threshold
      5. VIX >= analyst_vix_spike_threshold (fear regime — re-evaluate everything)
    """
    settings = get_settings()
    db = await get_db()

    existing = await db[COLL_SIGNALS].find_one(
        {"ticker": ticker},
        {"generated_at": 1, "current_price": 1, "score": 1, "analyst_used": 1},
    )

    # Trigger 1 — no existing signal or not from AI analyst
    if not existing or not existing.get("analyst_used"):
        return True, "no_ai_signal"

    last_ts = existing.get("generated_at")
    if not last_ts:
        return True, "no_timestamp"

    # Normalise timezone
    if isinstance(last_ts, datetime) and last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)

    age_minutes = (utcnow() - last_ts).total_seconds() / 60

    # Trigger 2 — signal is stale
    if age_minutes >= settings.analyst_cache_minutes:
        return True, f"stale_{age_minutes:.0f}min"

    # Trigger 3 — significant price move since last analysis
    last_price = existing.get("current_price") or 0.0
    current_price = raw_doc.get("current_price") or 0.0
    if last_price > 0 and current_price > 0:
        price_move = abs(current_price - last_price) / last_price
        if price_move >= settings.analyst_price_change_pct:
            return True, f"price_move_{price_move:.1%}"

    # Trigger 4 — composite score has shifted materially
    last_score = existing.get("score") or 0.5
    current_score = feat_doc.get("composite_score") or 0.5
    score_shift = abs(current_score - last_score)
    if score_shift >= settings.analyst_score_change_threshold:
        return True, f"score_shift_{score_shift:.2f}"

    # Trigger 5 — VIX spike (fear regime)
    vix = (raw_doc.get("macro") or {}).get("vix") or 0.0
    if vix >= settings.analyst_vix_spike_threshold:
        return True, f"vix_spike_{vix:.1f}"

    return False, f"cached_{age_minutes:.0f}min_old"


async def _publish_verdict(
    ticker: str,
    signal: dict,
    prev_signal: str | None,
    prev_stability: StabilityState,
    *,
    extra: dict,
) -> bool:
    """
    Decide what this cycle actually publishes, and persist it.

    Both signal paths write their document before reaching here — `run_analysis`
    and `generate_signal` each upsert `stocks_signals` themselves — so the
    verdict is corrected with a `$set` rather than by rewriting the document.
    That deliberately keeps the *fresh* research (thesis, target, stop) on a
    document whose published verdict is the older one: the analysis is current
    even when the conclusion has not yet earned a change of mind, and the
    explanation says so rather than leaving the two silently contradicting.

    Mutates `signal` in place so the caller's history record, alert and trade
    path all see the published verdict, never the unconfirmed candidate.
    Returns whether the published verdict changed.
    """
    settings = get_settings()
    db = await get_db()
    now = utcnow()

    decision = stabilise(
        published=prev_signal,
        candidate=signal.get("signal", "HOLD"),
        now=now,
        state=prev_stability,
        confirmations=settings.signal_confirmations,
        min_dwell_minutes=settings.signal_min_dwell_minutes,
    )

    if decision.signal != signal.get("signal"):
        logger.info(
            "signal_held_back",
            ticker=ticker,
            published=decision.signal,
            candidate=signal.get("signal"),
            reason=decision.reason,
        )
        signal["signal"] = decision.signal
        held = decision.held_back
        if held:
            signal["explanation"] = (
                f"{signal.get('explanation', '')} "
                f"[{held} candidate not yet confirmed — {decision.reason}; "
                f"holding {decision.signal} until it does.]"
            ).strip()

    signal[STABILITY_FIELD] = decision.state.to_doc()

    await db[COLL_SIGNALS].update_one(
        {"ticker": ticker},
        {"$set": {
            **extra,
            "signal": decision.signal,
            "explanation": signal.get("explanation", ""),
            STABILITY_FIELD: decision.state.to_doc(),
        }},
    )
    return decision.changed


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
            # Stored so calibration can replay the BUY gate, not just the score
            # threshold. Without it a threshold sweep silently models a rule the
            # engine does not actually use.
            "risk_score":      (signal.get("risk") or {}).get("risk_score"),
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

        if new_sig not in ("BUY", "SELL"):
            return

        from app.services.trade_manager import execute_entry, execute_exit

        db = await get_db()
        watchers = await db[COLL_WATCHED].find({"ticker": ticker}, {"user_id": 1}).to_list(length=500)

        if new_sig == "BUY":
            # The analyst's own levels bracket the entry when they validate;
            # trade_manager falls back to configured percentages otherwise.
            ao = signal.get("analyst_output") or {}
            for w in watchers:
                await execute_entry(
                    w["user_id"], ticker, score, current_price,
                    analyst_stop_loss=ao.get("stop_loss"),
                    analyst_price_target=ao.get("price_target"),
                    # Drives the SEMI_AUTO gate: how strongly the analyst
                    # believed this setup decides whether the agent may act
                    # unattended or has to ask.
                    conviction=ao.get("conviction"),
                )
            return

        # SELL — close any open position.
        #
        # This was previously unwired: the code returned on anything that was not
        # a BUY, with a comment claiming SELL was "handled via EXIT_ALERT from
        # dip-buy scan". Nothing ever called the exit path from there — the scan
        # only builds display cards — so the agent opened positions automatically
        # and never closed them. execute_exit no-ops when no position is open.
        for w in watchers:
            await execute_exit(
                w["user_id"], ticker, current_price, trigger="SELL_SIGNAL",
                # Carried so the closed trade can say what it scored, not just
                # that something sold it.
                signal_score=score,
            )

    except Exception as exc:
        logger.warning("execute_trades_failed", ticker=ticker, error=str(exc))


async def _fire_alerts(
    ticker: str,
    prev_signal: str | None,
    new_signal: dict,
    *,
    changed: bool,
    prev_conviction: str | None = None,
) -> None:
    """
    Notify users watching this ticker when its *state* changes.
    Runs fire-and-forget — never raises.

    "State" is two things, and both are edges rather than levels:

      * the published verdict changed — `changed`, decided by the stability
        layer, not by comparing this cycle's raw verdict to the last one. An
        unconfirmed candidate is not news.
      * conviction newly reached HIGH. This used to alert on every cycle where
        conviction *was* HIGH, which meant the same "NVDA — BUY (High
        Conviction)" message repeated for as long as the analyst kept its view.
        A conviction that has not moved is not news either.
    """
    try:
        new_sig = new_signal.get("signal", "HOLD")
        ao = new_signal.get("analyst_output") or {}
        conviction = ao.get("conviction")
        signal_flipped = changed and prev_signal is not None
        is_high_conviction = conviction == "HIGH" and prev_conviction != "HIGH"

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
            {"alert_settings": 1, "auto_trade_settings": 1},
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
            ats = user.get("auto_trade_settings") or {}
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
                # Everything below exists so a target and a stop are readable
                # without opening the app. A bare "Target: $102.00" says nothing
                # until you know what it is measured from, how far the stop is,
                # which of the two is the bigger move, and how long the thesis is
                # supposed to take.
                current_price=new_signal.get("current_price"),
                risk_score=(new_signal.get("risk") or {}).get("risk_score"),
                time_horizon=ao.get("time_horizon"),
                position_size_pct=ats.get("position_size_pct"),
                whatsapp_phone=wa_phone,
                whatsapp_apikey=wa_apikey,
            )
    except Exception as exc:
        logger.warning("fire_alerts_failed", ticker=ticker, error=str(exc))
