"""
GET /signals         — latest signals for the current user's watchlist tickers
GET /signals/summary — portfolio-level snapshot for the current user
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from app.db import COLL_FEATURES, COLL_SIGNALS, COLL_WATCHED, get_db
from app.dependencies import get_current_user
from app.models.stock import AnalyzeResponse, DipBuyCandidate, DipBuyScanResponse, SignalListResponse, SignalSummary
from app.services.scoring import compute_personalized_score
from app.utils.logger import get_logger

router = APIRouter(tags=["signals"])
logger = get_logger(__name__)


async def _user_tickers(user_id: str, db) -> list[str]:
    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    return [d["ticker"] for d in watched]


async def _apply_user_weights(docs: list[dict], user_weights: dict | None, db) -> list[AnalyzeResponse]:
    """Re-score signal docs using the user's personal weights if set."""
    if not user_weights:
        return [_doc_to_response(d) for d in docs]

    tickers = [d["ticker"] for d in docs]
    feat_docs = await db[COLL_FEATURES].find({"ticker": {"$in": tickers}}).to_list(length=2000)
    feat_by_ticker = {f["ticker"]: f for f in feat_docs}

    responses = []
    for doc in docs:
        feat = feat_by_ticker.get(doc["ticker"])
        if feat:
            feat["risk"] = doc.get("risk", {})
            score, signal = compute_personalized_score(feat, user_weights)
            doc = {**doc, "score": score, "signal": signal}
        responses.append(_doc_to_response(doc))
    return responses


@router.get("/signals", response_model=SignalListResponse, summary="List latest signals for your watchlist")
async def list_signals(
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = Query(None),
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
) -> SignalListResponse:
    user_id = str(current_user["_id"])
    db = await get_db()
    tickers = await _user_tickers(user_id, db)

    query: dict = {"ticker": {"$in": tickers}}
    if min_confidence > 0:
        query["confidence"] = {"$gte": min_confidence}
    # Note: signal filter applied after re-scoring when user has custom weights
    if signal and not current_user.get("scoring_weights"):
        query["signal"] = signal

    cursor = db[COLL_SIGNALS].find(query).sort("generated_at", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    responses = await _apply_user_weights(docs, current_user.get("scoring_weights"), db)

    if signal:
        responses = [r for r in responses if r.signal == signal]
    return SignalListResponse(count=len(responses), signals=responses)


@router.get("/signals/summary", response_model=SignalSummary, summary="Portfolio-level signal summary")
async def signals_summary(current_user: dict = Depends(get_current_user)) -> SignalSummary:
    user_id = str(current_user["_id"])
    db = await get_db()
    tickers = await _user_tickers(user_id, db)

    docs = await db[COLL_SIGNALS].find({"ticker": {"$in": tickers}}).to_list(length=2000)
    responses = await _apply_user_weights(docs, current_user.get("scoring_weights"), db)

    buy  = sum(1 for r in responses if r.signal == "BUY")
    sell = sum(1 for r in responses if r.signal == "SELL")
    hold = sum(1 for r in responses if r.signal == "HOLD")
    avg_score = round(sum(r.score for r in responses) / len(responses), 4) if responses else 0.0
    avg_conf  = round(sum(r.confidence for r in responses) / len(responses), 4) if responses else 0.0
    high_conviction = [r.ticker for r in responses if r.conviction == "HIGH" or r.confidence >= 0.75]

    return SignalSummary(
        total_tickers=len(responses),
        buy_count=buy, sell_count=sell, hold_count=hold,
        avg_score=avg_score, avg_confidence=avg_conf,
        high_conviction_tickers=sorted(high_conviction),
        signals=sorted(responses, key=lambda r: r.score, reverse=True),
    )


# ── Entry thresholds (your dip-buy strategy) ──────────────────────────────────
_ENTRY_RSI_MAX       = 45.0   # RSI not yet overbought
_ENTRY_STOCH_MAX     = 0.20   # oversold on Stochastic RSI
_ENTRY_BB_MAX        = 0.35   # near or below lower Bollinger Band

# ── Exit-alert thresholds ─────────────────────────────────────────────────────
_EXIT_RSI_MIN        = 70.0   # overbought
_EXIT_BB_MIN         = 0.90   # near upper Bollinger Band


@router.get(
    "/signals/dip-buy",
    response_model=DipBuyScanResponse,
    summary="Scan watchlist for dip-buy entries and profit-taking alerts",
)
async def dip_buy_scan(current_user: dict = Depends(get_current_user)) -> DipBuyScanResponse:
    """
    Entry candidates  — stoch_rsi ≤ 0.20  AND  bb_pct ≤ 0.35  AND  rsi_14 ≤ 45
    Exit alerts       — rsi_14 ≥ 70  OR  bb_pct ≥ 0.90

    Results are pulled from the latest stocks_features documents so no
    re-analysis is triggered; call /analyze?ticker=X&force_refresh=true first
    if you want fresh data.
    """
    user_id = str(current_user["_id"])
    db = await get_db()
    tickers = await _user_tickers(user_id, db)

    if not tickers:
        return DipBuyScanResponse(entry_candidates=[], exit_alerts=[], scanned=0)

    # Fetch latest features doc per watched ticker
    docs = await db[COLL_FEATURES].find(
        {"ticker": {"$in": tickers}},
        {
            "ticker": 1, "current_price": 1, "computed_at": 1,
            "rsi_14": 1, "stoch_rsi": 1, "bb_pct": 1,
            "ma_20": 1, "volume_anomaly": 1, "technical_score": 1,
        },
    ).to_list(length=2000)

    entries: list[DipBuyCandidate] = []
    exits: list[DipBuyCandidate] = []
    neutrals: list[DipBuyCandidate] = []

    analyzed_tickers: set[str] = set()

    for doc in docs:
        rsi       = doc.get("rsi_14")
        stoch     = doc.get("stoch_rsi")
        bb        = doc.get("bb_pct")
        price     = doc.get("current_price", 0.0)
        ma20      = doc.get("ma_20")
        computed  = doc.get("computed_at", datetime.now(tz=timezone.utc))
        if isinstance(computed, datetime) and computed.tzinfo is None:
            computed = computed.replace(tzinfo=timezone.utc)

        ticker = doc["ticker"]
        analyzed_tickers.add(ticker)
        pct_from_ma20 = round((price - ma20) / ma20 * 100, 2) if ma20 else None

        candidate_base = dict(
            ticker=ticker,
            current_price=price,
            rsi_14=rsi,
            stoch_rsi=stoch,
            bb_pct=bb,
            ma_20=ma20,
            volume_anomaly=doc.get("volume_anomaly"),
            technical_score=doc.get("technical_score", 0.0),
            pct_from_ma20=pct_from_ma20,
            computed_at=computed,
        )

        # Entry: all three conditions must hold; None values are skipped safely
        is_entry = (
            (rsi is not None and rsi <= _ENTRY_RSI_MAX)
            and (stoch is not None and stoch <= _ENTRY_STOCH_MAX)
            and (bb is not None and bb <= _ENTRY_BB_MAX)
        )
        if is_entry:
            entries.append(DipBuyCandidate(**candidate_base, trigger="ENTRY"))
            continue

        # Exit alert: either condition fires
        is_exit = (
            (rsi is not None and rsi >= _EXIT_RSI_MIN)
            or (bb is not None and bb >= _EXIT_BB_MIN)
        )
        if is_exit:
            exits.append(DipBuyCandidate(**candidate_base, trigger="EXIT_ALERT"))
            continue

        # Neutral — has data but doesn't meet entry or exit criteria
        neutrals.append(DipBuyCandidate(**candidate_base, trigger="NEUTRAL"))

    # Tickers in watchlist but with no feature document yet
    unanalyzed = [t for t in tickers if t not in analyzed_tickers]

    # Most oversold first for entries; most overbought first for exits
    entries.sort(key=lambda c: (c.stoch_rsi or 1.0))
    exits.sort(key=lambda c: (c.rsi_14 or 0.0), reverse=True)
    neutrals.sort(key=lambda c: c.ticker)

    logger.info(
        "dip_buy_scan_complete",
        scanned=len(docs), entries=len(entries), exits=len(exits),
        neutral=len(neutrals), unanalyzed=len(unanalyzed),
    )
    return DipBuyScanResponse(
        entry_candidates=entries,
        exit_alerts=exits,
        neutral_tickers=neutrals,
        unanalyzed_tickers=unanalyzed,
        scanned=len(docs),
    )


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
