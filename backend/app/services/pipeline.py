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
(ticker, hour_bucket, signal): one row per *published verdict* per hour, so a
repeated verdict dedupes while a change within the hour records itself.
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
from app.services.setup_scan import classify_trigger
from app.services import source_health
from app.services.cross_section import cohort_for
from app.services.signal_generator import (
    BUY_THRESHOLD,
    RANK_BUY_PERCENTILE,
    RANK_HYSTERESIS,
    RANK_SELL_PERCENTILE,
    SELL_THRESHOLD,
    generate_signal,
)
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
    # Every sentinel each fetch already wrote is in that one document. Reading
    # them is the whole of health recording — nothing is probed, and nothing
    # here can fail the cycle.
    source_health.observe(raw_doc)
    await compute_features(ticker)
    scored = await score_ticker(ticker)
    await source_health.record_subsystem(
        "scoring", source_health.OK, method=scored.get("scoring_method"),
    )
    await source_health.flush()

    data_sources = _build_data_sources(raw_doc)
    # What each factor of this score was actually built from. Carried onto the
    # signal so a reader — and, twenty days later, the calibration replay — can
    # tell a verdict built on live data from one built on neutral fallbacks.
    # `score_ticker` returns the feature document it just scored, so this costs
    # no read.
    inputs = scored.get("inputs")
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
                # The published verdict goes in so the analyst's answer is
                # reconciled against the same hysteresis band the rule-based
                # path below uses — see `analyst._gate_analyst_signal`.
                signal = await run_analysis(ticker, previous_signal=prev_signal)
                if signal:
                    signal["data_sources"] = data_sources
                    signal["inputs"] = inputs
                    signal["analyst_used"] = True
                    signal["current_price"] = current_price
                    signal["day_change_pct"] = day_change_pct
                    signal["alternative_data"] = alternative_data
                    changed = await _publish_verdict(
                        ticker, signal, prev_signal, prev_stability,
                        extra={"current_price": current_price,
                               "day_change_pct": day_change_pct},
                        feat=feat_doc,
                    )
                    await _append_history(signal, raw_doc, scored)
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
    signal["inputs"] = inputs
    signal["analyst_used"] = False
    signal["current_price"] = current_price
    signal["day_change_pct"] = day_change_pct
    signal["alternative_data"] = alternative_data
    changed = await _publish_verdict(
        ticker, signal, prev_signal, prev_stability,
        extra={"current_price": current_price, "day_change_pct": day_change_pct},
        feat=scored,
    )
    await _append_history(signal, raw_doc, scored)
    logger.info("pipeline_complete", ticker=ticker, mode="rule_based", signal=signal.get("signal"))
    await _fire_alerts(ticker, prev_signal, signal,
                       changed=changed, prev_conviction=prev_conviction)
    await _execute_trades(ticker, signal)
    return signal


async def run_pipeline_all(tickers: list[str]) -> dict[str, str]:
    """Run the pipeline for a list of tickers; returns ticker → 'ok' | error."""
    results: dict[str, str] = {}
    started = utcnow()
    for ticker in tickers:
        try:
            await run_pipeline(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            logger.error("pipeline_failed", ticker=ticker, error=str(exc))
            results[ticker] = str(exc)

    # This map was built, logged and dropped. Without it a status page cannot
    # tell "FRED is down" from "the pipeline has not run for six hours", which
    # are the two things a reader most needs told apart — and every other
    # number on that page is uninterpretable until they are.
    failed = {t: err for t, err in results.items() if err != "ok"}
    await source_health.record_subsystem(
        "pipeline",
        source_health.FAILED if failed and len(failed) == len(results)
        else source_health.DEGRADED if failed
        else source_health.OK,
        last_cycle_at=started,
        last_cycle_finished_at=utcnow(),
        tickers_ok=len(results) - len(failed),
        tickers_total=len(results),
        last_error=source_health.scrub(next(iter(failed.values()), None)),
        failed_tickers=sorted(failed),
    )
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

    **Each boundary is measured on the number that decides it.** The BUY side
    reads the composite; the SELL side reads `scoring.exit_score`, because
    since 1.31.0 that is what `classify_signal` tests. Measuring the SELL band
    on the composite skipped the call on a name one tick from an exit — a
    falling knife at exit reading 0.2925 behind a composite of 0.4125 reported
    `mid_range` — and spent it on a name nowhere near one, an extended leader
    whose composite of 0.3750 sat inside the SELL band on an exit reading of
    0.6435. Both cases are pinned in `tests/test_exit_boundary_readers.py`.
    Holdings are covered either way by `analyst_always_analyse_holdings`; the
    names this stranded were the advisory SELLs on things watched but not held.

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

    # Local import: `scoring` imports `classify_signal` back out of
    # `signal_generator`, and this module sits downstream of both — the same
    # cycle `generate_signal` breaks the same way. `exit_score` is a pure
    # function over the document already in hand, so this costs no read.
    from app.services.scoring import exit_score as _exit_score

    exit_reading = _exit_score(feat_doc)
    sell_basis = float(score) if exit_reading is None else exit_reading

    if settings.enable_rank_signals:
        # Proximity has to be measured against the boundary that will actually
        # decide the verdict. Under the relative rule that is a rank, so a name
        # at 0.60 sitting just outside the top quintile is exactly the live
        # call this gate exists to pay for, while one at 0.68 in the middle of
        # the field is not. Measuring the absolute distance would spend the
        # budget on the second and skip the first.
        cohort = await cohort_for(ticker, float(score))
        if cohort is None:
            # No cohort means the rule-based path will fall back to the
            # absolute rule, so the absolute band below is the right one.
            pass
        else:
            # `analyst_gate_margin` is in score units; the rank band is in
            # percentile points. `RANK_HYSTERESIS` is the system's own
            # statement of what counts as a meaningful move in rank, so it is
            # reused rather than a second tunable being invented.
            if cohort.percentile >= RANK_BUY_PERCENTILE - RANK_HYSTERESIS:
                return True, f"near_buy_rank_{cohort.percentile:.2f}"
            if cohort.percentile <= RANK_SELL_PERCENTILE + RANK_HYSTERESIS:
                return True, f"near_sell_rank_{cohort.percentile:.2f}"
            # `_classify_relative` tests the absolute exit before the rank and
            # it can fire on a name that is mid-field, so proximity to it is a
            # live call under the relative rule too.
            if sell_basis <= SELL_THRESHOLD + margin:
                return True, f"near_sell_exit_{sell_basis:.2f}"
            if settings.analyst_always_analyse_holdings and await _has_open_position(ticker):
                return True, f"position_open_{score:.2f}"
            return False, f"mid_field_{cohort.percentile:.2f}"

    if score >= BUY_THRESHOLD - margin:
        return True, f"near_buy_{score:.2f}"
    if sell_basis <= SELL_THRESHOLD + margin:
        return True, f"near_sell_{sell_basis:.2f}"

    if settings.analyst_always_analyse_holdings and await _has_open_position(ticker):
        return True, f"position_open_{score:.2f}"

    return False, f"mid_range_{score:.2f}"


async def _has_open_position(ticker: str) -> bool:
    """
    Whether anyone is holding *ticker* right now.

    **Returns True when it cannot tell.** An unreadable trades collection means
    capital may still be committed, and the failure that matters here is
    declining to form a view on an open position — not the cost of one extra
    analyst call. Extracted so the absolute and relative gate branches cannot
    answer this question differently.
    """
    try:
        db = await get_db()
        held = await db[COLL_TRADES].find_one({
            "ticker": ticker,
            "action": "BUY",
            "status": {"$in": list(TradeStatus.OPEN)},
            "closed_at": None,
        })
        return held is not None
    except Exception as exc:
        logger.warning("analyst_gate_position_check_failed", ticker=ticker, error=str(exc))
        return True


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
    feat: dict | None = None,
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

    **Every derived field describes the published verdict**, which is the rule
    `_gate_analyst_signal` already follows one layer down and which this
    function was breaking. `confidence`, `entry_suggestion` and
    `exit_suggestion` are computed by the signal path *for the candidate* and
    persisted by its own upsert before this runs — so a held-back BUY under a
    published HOLD left a full buy plan, entry price, stop and target, on the
    document. That is the exact defect the analyst gate exists to prevent,
    reintroduced by the layer above it. The candidate's confidence also reached
    the history row against the published signal, where the calibration buckets
    read it.

    So when the published verdict differs from the candidate, the three derived
    fields are recomputed for what was actually published. On the analyst path
    that replaces model-derived suggestions with rule-derived ones: deliberate,
    and the same trade the gate makes — a suggestion describing a verdict nobody
    published is worse than a blunter one describing the verdict they got.

    `feat` is the feature document the suggestions are derived from. Optional
    only so existing callers and tests that do not exercise an override keep
    working; both pipeline call sites pass it.
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
        _rederive_for_published(signal, decision.signal, feat or {})
        # Only on an override. Both signal paths write these three for their own
        # candidate, so persisting them otherwise is a no-op that says nothing;
        # here it is the correction itself.
        rederived = {
            "confidence":        signal.get("confidence"),
            "entry_suggestion":  signal.get("entry_suggestion"),
            "exit_suggestion":   signal.get("exit_suggestion"),
        }
    else:
        rederived = {}

    signal[STABILITY_FIELD] = decision.state.to_doc()

    await db[COLL_SIGNALS].update_one(
        {"ticker": ticker},
        {"$set": {
            **extra,
            "signal": decision.signal,
            "explanation": signal.get("explanation", ""),
            **rederived,
            STABILITY_FIELD: decision.state.to_doc(),
        }},
    )
    return decision.changed


def _rederive_for_published(signal: dict, published: str, feat: dict) -> None:
    """
    Recompute the fields that describe a verdict, for the verdict published.

    Mutates `signal` in place, like its caller. Reads the cohort back off the
    document rather than recomputing it: the rank the verdict was classified
    with is stored there for exactly this reason, and re-reading the watchlist
    half a second later could rank against a different field.

    `sell_basis` is the stored exit reading, so the confidence of a published
    SELL is measured against the number that decides a SELL — the same
    correction made in `boundary_confidence` itself. Absent on rows written
    before 1.31.0, where `None` gives the pre-split rule unchanged.
    """
    from app.services.cross_section import Cohort
    from app.services.signal_generator import _price_suggestions, boundary_confidence

    cohort = None
    if "score_percentile" in signal and "cohort_size" in signal:
        cohort = Cohort(
            percentile=signal["score_percentile"], size=signal["cohort_size"]
        )

    score = float(signal.get("score") or 0.5)
    signal["confidence"] = round(
        boundary_confidence(
            score, published, cohort, sell_basis=signal.get("exit_score")
        ),
        4,
    )

    price = float(signal.get("current_price") or feat.get("current_price") or 0.0)
    entry, exit_s = _price_suggestions(published, price, feat)
    signal["entry_suggestion"] = entry
    signal["exit_suggestion"] = exit_s


#: Bumped whenever the meaning of a `data_sources` value changes.
#:
#: Version 1 reported `fundamentals` as `"yfinance"` or `"none"`, inferred from
#: whether a P/E was present. Both halves were wrong: yfinance has not been in
#: the fundamentals chain since it was replaced by Massive and Alpha Vantage,
#: and a Massive-only refresh — which is exactly what every ticker past the
#: Alpha Vantage daily budget gets — carries real revenue growth, free cash
#: flow and debt/equity but no P/E, so it was reported as `"none"`. The field
#: claimed absence where there was data.
#:
#: Historical rows are **not** backfilled. The provider that actually answered
#: on 21 August cannot be recovered from a row that never recorded it, and a
#: guess written into a provenance field is worse than a gap in one. The
#: version marker is how a reader tells a corrected row from an uncorrected
#: one — the same discipline as trades closed before commissions were accrued.
DATA_SOURCES_VERSION = 2


def _build_data_sources(raw_doc: dict) -> dict:
    """
    Which provider actually supplied each input to this signal.

    Every value here is the fetch's own report of what it did, never inferred
    from whether some field came back populated. `stocks_raw` already carries a
    `source` sentinel on each enrichment — `finnhub+vader+finlex`, `no_api_key`,
    `error`, `massive+alphavantage`, `pending` — because each fetcher writes one
    on the way past. Reading them is the whole of this function; guessing was
    the whole of the bug.
    """
    fund = raw_doc.get("fundamentals") or {}
    alt = raw_doc.get("alternative_data") or {}

    return {
        "version": DATA_SOURCES_VERSION,
        # The only hard dependency, and the one with a licensing question
        # attached — yahoo is evaluation-only. Absent before version 2, which
        # left the most consequential provenance fact in the system unrecorded.
        "price": raw_doc.get("price_source") or "unknown",
        "sentiment": (raw_doc.get("sentiment_raw") or {}).get("source", "none"),
        "macro": (raw_doc.get("macro") or {}).get("source", "none"),
        "fundamentals": fund.get("source") or "none",
        # A cache served past its TTL is still a real provider answer, but it is
        # not today's. Kept beside the source rather than folded into it: they
        # are different questions and a reader needs both.
        "fundamentals_stale": bool(fund.get("stale")),
        # Three independent yfinance calls that fail independently; the options
        # leg is the one that feeds the score.
        "alternative": (alt.get("options_flow") or {}).get("source", "none"),
    }


async def _append_history(signal: dict, raw_doc: dict, feat_doc: dict) -> None:
    """
    Append a history record, keyed on (ticker, hour_bucket, **signal**).

    One row per published verdict per hour. A cycle that republishes the same
    verdict dedupes onto the existing row, which is what the hour bucket is
    for — the pipeline runs every five minutes and twelve identical HOLDs an
    hour is noise, not evidence.

    **The verdict is part of the key, and that is the whole point.** Keyed on
    (ticker, hour_bucket) alone with `$setOnInsert`, only the *first*
    evaluation of each clock-hour was ever retained. But trades execute on
    every cycle and SELL publishes immediately — it skips confirmations and
    dwell — so a SELL at :35 closed a real position and left the :05 HOLD
    standing as the hour's record. `stocks_signal_history` is the only retained
    series and the sole basis for `override_counterfactual`, the setup replay
    and every settled outcome; it was under-sampling exactly the
    decision-bearing rows it exists to hold.

    A later-in-hour analyst override under an *unchanged* published verdict is
    the same loss in miniature — same key, so `$setOnInsert` writes nothing —
    and is handled below by promoting the gate fields onto the standing row.

    `feat_doc` is the document `score_ticker` just returned, so the setup fields
    below cost no read.
    """
    try:
        db = await get_db()
        ao = signal.get("analyst_output") or {}
        now = signal.get("generated_at", utcnow())

        # Idempotency key: same ticker, same clock-hour, same published
        # verdict = same record. A verdict *change* within the hour is a
        # different observation and gets its own row.
        hour_bucket = now.replace(minute=0, second=0, microsecond=0)

        # What the gate made of the analyst's verdict, flattened.
        #
        # `analyst_gate` is written to `stocks_signals`, which holds ONE
        # document per ticker and is replaced every cycle — so an override
        # survived about five minutes and left nothing behind but a log line.
        # This series is the only retained record of what the engine decided,
        # and until the override reached it there was no sample to ask the
        # question the gate exists to raise: were these refusals worth making?
        #
        # Flattened to three scalars rather than stored whole. The prose
        # `reason` is reconstructible from the other fields and would otherwise
        # be written ~24 times a day per ticker to say the same sentence.
        gate = signal.get("analyst_gate") or {}
        trigger = classify_trigger(
            feat_doc.get("rsi_14"), feat_doc.get("stoch_rsi"),
            feat_doc.get("bb_pct"), feat_doc.get("macd_bullish"),
            feat_doc.get("ma_cross_bullish"),
        )
        await _stamp_exit_alert(signal["ticker"], trigger, signal.get("current_price"))

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
            # Stored so a calibration replay can ask whether thin inputs
            # predicted worse outcomes — the question the completeness figure
            # exists to make answerable, and one no stored row could support
            # before this.
            "inputs":          signal.get("inputs"),
            "analyst_used":    signal.get("analyst_used", False),
            # None here is "no override", and it is only meaningful alongside
            # `analyst_used`. A row from before this shipped has the key absent
            # entirely, which means "never recorded" — a different fact, and
            # one a consumer must exclude rather than count as agreement.
            "analyst_override": gate.get("override"),
            "analyst_wanted":   gate.get("model_signal"),
            "rule_signal":      gate.get("rule_signal"),
            # The number the SELL test was measured against, retained for the
            # same reason `score_percentile` is: the exit reading is recomputed
            # from sub-scores, and a replay twenty days later would recompute it
            # from whatever the weights and thresholds are by then, describing a
            # rule that never ran. Storing it is the only way "was this exit
            # right" can ever be asked of the rule that actually decided it.
            #
            # `None` means the reading could not be derived — an XGBoost score,
            # where the weights did not produce the composite. Absent means the
            # row predates 1.31.0. Same convention as `analyst_override`.
            "exit_score":       signal.get("exit_score"),
            # ── The dip-buy setup this verdict was produced on ─────────────
            # The declared strategy is mean-reversion (config.technical_stance)
            # and nothing retained what the reversion actually looked like at
            # the moment of the verdict. `score` is a blend of six factors and
            # cannot be taken apart twenty days later, so the one question the
            # strategy rests on — did an entry setup predict forward alpha —
            # could not be asked however long anyone waited. The analyst gate
            # and the research veto both have a counterfactual; this did not.
            #
            # The trigger is stored ALONGSIDE its inputs, not instead of them:
            # the thresholds are tunable, so a replay recomputing the trigger
            # from today's constants would describe a rule that never ran,
            # while the raw indicators are what a different rule can be tested
            # against.
            #
            # Same absent-vs-None convention as `analyst_override`. `None`
            # means this code wrote the row and the indicator was not computed;
            # the key being ABSENT means the row predates this and must be
            # excluded rather than read as a missing indicator.
            "technical_score":   feat_doc.get("technical_score"),
            "rsi_14":            feat_doc.get("rsi_14"),
            "stoch_rsi":         feat_doc.get("stoch_rsi"),
            "bb_pct":            feat_doc.get("bb_pct"),
            "macd_bullish":      feat_doc.get("macd_bullish"),
            "ma_cross_bullish":  feat_doc.get("ma_cross_bullish"),
            "setup_trigger":     trigger,
            # Filled by performance tracker after ~20 trading days:
            "price_20d_later": None,
            "return_20d":      None,
            "was_correct":     None,
        }
        key = {
            "ticker": signal["ticker"],
            "hour_bucket": hour_bucket,
            "signal": record["signal"],
        }
        result = await db[COLL_SIGNAL_HISTORY].update_one(
            key,
            {"$setOnInsert": record, "$set": {"hour_bucket": hour_bucket}},
            upsert=True,
        )

        # An override that lands later in the hour under an unchanged verdict
        # matches the standing row, so `$setOnInsert` writes nothing and the
        # gate's decision is lost — the same hole the key change closes, one
        # size down. Promote the three gate fields onto the row when it is
        # carrying nothing and this cycle has something to say. Absent stays
        # absent; `None` (the gate ran and agreed) is never overwritten by a
        # later `None`, and never overwrites a recorded override.
        if result.matched_count and record.get("analyst_override") is not None:
            await db[COLL_SIGNAL_HISTORY].update_one(
                {**key, "analyst_override": None},
                {"$set": {
                    "analyst_override": record["analyst_override"],
                    "analyst_wanted":   record.get("analyst_wanted"),
                    "rule_signal":      record.get("rule_signal"),
                }},
            )
    except Exception as exc:
        logger.warning("history_append_failed", ticker=signal.get("ticker"), error=str(exc))


async def _stamp_exit_alert(ticker: str, trigger: str, price: float | None) -> None:
    """
    Record, on any open position in this ticker, that the setup scan called it
    overbought — and what it was worth at the time.

    Nothing here sells. The overbought flag stays advisory, and
    `trade_rationale._EXIT_REASON` still has no `EXIT_ALERT` entry, because a
    reason string for an exit that cannot happen is a lie the same shape as a
    gate panel contradicting the badge beside it.

    What this adds is the evidence to argue about it. `setup_trigger` is already
    retained on the *signal* row, which answers "did an ENTRY predict forward
    alpha" — but the exit question is about a position's path, not a ticker's,
    and nothing recorded where the alert fell relative to the trade. With
    `first_exit_alert_price` on the record, `_excursion_summary` can report what
    the position was worth at the alert, and `/performance/trades` can put that
    beside what it actually exited at. That comparison is what wiring this to
    `execute_exit` has to be argued from.

    The first alert is written once and never revised — it is the moment the
    flag first fired, not the most recent time it was still firing. The counter
    is separate, because "flagged once and kept running" and "flagged twenty
    times" are different stories about the same peak.

    Fire-and-forget: never raises, and never blocks a verdict from publishing.
    """
    if trigger != "EXIT_ALERT" or not price or price <= 0:
        return
    try:
        from app.models.trade import TradeStatus

        db = await get_db()
        held = {
            "ticker": ticker,
            "action": "BUY",
            "status": {"$in": list(TradeStatus.OPEN)},
            "closed_at": None,
        }
        await db[COLL_TRADES].update_many(
            {**held, "first_exit_alert_at": {"$exists": False}},
            {"$set": {
                "first_exit_alert_at": utcnow(),
                "first_exit_alert_price": round(float(price), 4),
            }},
        )
        await db[COLL_TRADES].update_many(held, {"$inc": {"exit_alert_count": 1}})
    except Exception as exc:
        logger.warning("exit_alert_stamp_failed", ticker=ticker, error=str(exc))


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
            # Which rule produced this verdict, read off the document rather
            # than off config. A signal classified relatively must not be
            # re-examined against an absolute bar half an hour later because
            # somebody switched the flag — the order has to be judged by the
            # rule that decided it. Absent means the absolute rule, including
            # on every document written before ranking existed.
            rank_decided = "score_percentile" in signal
            for w in watchers:
                await execute_entry(
                    w["user_id"], ticker, score, current_price,
                    analyst_stop_loss=ao.get("stop_loss"),
                    analyst_price_target=ao.get("price_target"),
                    # Drives the SEMI_AUTO gate: how strongly the analyst
                    # believed this setup decides whether the agent may act
                    # unattended or has to ask.
                    conviction=ao.get("conviction"),
                    rank_decided=rank_decided,
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
