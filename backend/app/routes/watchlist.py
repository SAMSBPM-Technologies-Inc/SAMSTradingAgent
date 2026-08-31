"""
GET    /watchlist       — current user's tickers ranked by conviction → score
POST   /ticker          — add ticker to the user's watch list
DELETE /ticker/{ticker} — remove ticker from the user's watch list
"""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS, COLL_WATCHED, get_db
from app.dependencies import get_current_user
from app.services.entitlements import entitlements_for
from app.models.stock import (
    TickerAddRequest,
    TickerAddResponse,
    WatchlistItem,
    WatchlistResponse,
    WatchlistSetupCounts,
)
from app.services.scoring import compute_personalized_score
from app.services.setup_scan import TRIGGER_RANK, setup_from_feature_doc
from app.utils.logger import get_logger

router = APIRouter(tags=["watchlist"])
logger = get_logger(__name__)

_CONVICTION_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, None: 0}


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    summary="Current user's watchlist — verdict and timing setup per ticker",
)
async def get_watchlist(current_user: dict = Depends(get_current_user)) -> WatchlistResponse:
    """
    One row per watched ticker, carrying both the scored verdict
    (signal/score/conviction/thesis, from stocks_signals) and the timing setup
    (ENTRY/EXIT_ALERT/NEUTRAL plus its indicators, from stocks_features).

    This is the single source for the merged home page; the dip-buy scan that
    used to back /alpha-radar is the same data under a different projection.
    Tickers with no signal document yet are returned as signal="PENDING" so a
    freshly-added ticker is visible while the pipeline runs.
    """
    user_id = str(current_user["_id"])
    db = await get_db()

    cap = entitlements_for(current_user).watchlist_cap

    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    tickers = [d["ticker"] for d in watched]
    if not tickers:
        return WatchlistResponse(count=0, items=[], setups=WatchlistSetupCounts(), cap=cap)

    user_weights = current_user.get("scoring_weights")

    # Features are now always needed — they carry the timing setup, not just the
    # inputs to a personalised re-score.
    docs, raw_docs, feat_docs = await asyncio.gather(
        db[COLL_SIGNALS].find({"ticker": {"$in": tickers}}).to_list(length=2000),
        db[COLL_RAW].find(
            {"ticker": {"$in": tickers}},
            {"ticker": 1, "current_price": 1, "day_change_pct": 1},
        ).to_list(length=2000),
        db[COLL_FEATURES].find({"ticker": {"$in": tickers}}).to_list(length=2000),
    )
    feat_by_ticker = {f["ticker"]: f for f in feat_docs}
    raw_by_ticker = {r["ticker"]: r for r in raw_docs}
    signal_by_ticker = {d["ticker"]: d for d in docs}

    items: list[WatchlistItem] = []
    for ticker in tickers:
        feat = feat_by_ticker.get(ticker)
        raw = raw_by_ticker.get(ticker, {})
        setup = setup_from_feature_doc(feat) if feat else {"trigger": "PENDING"}

        doc = signal_by_ticker.get(ticker)
        if doc is None:
            # Watched but never scored — the pipeline has not produced a signal
            # document yet. Previously these vanished from the list entirely.
            items.append(WatchlistItem(
                ticker=ticker,
                signal="PENDING",
                score=0.0,
                confidence=0.0,
                current_price=raw.get("current_price") or (feat or {}).get("current_price"),
                day_change_pct=raw.get("day_change_pct"),
                generated_at=datetime.now(tz=timezone.utc),
                **setup,
            ))
            continue

        ao = doc.get("analyst_output") or {}
        generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
        if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        # Apply per-user weights if set, otherwise use stored global score/signal
        if user_weights and feat is not None:
            # Merge risk from signal doc into feat for threshold check
            feat["risk"] = doc.get("risk", {})
            score, signal = compute_personalized_score(feat, user_weights)
        else:
            score = doc.get("score", 0.0)
            signal = doc.get("signal", "HOLD")

        items.append(WatchlistItem(
            ticker=ticker,
            signal=signal,
            score=score,
            confidence=doc.get("confidence", 0.0),
            conviction=ao.get("conviction"),
            current_price=raw.get("current_price") or doc.get("current_price"),
            day_change_pct=raw.get("day_change_pct") or doc.get("day_change_pct"),
            price_target=ao.get("price_target"),
            thesis=ao.get("thesis"),
            generated_at=generated_at,
            **setup,
        ))

    # Actionable setups float to the top, then conviction, then score — a dip
    # entry is time-sensitive in a way a high-conviction HOLD is not.
    items.sort(
        key=lambda x: (TRIGGER_RANK.get(x.trigger, 0), _CONVICTION_RANK[x.conviction], x.score),
        reverse=True,
    )

    setups = WatchlistSetupCounts(
        entry=sum(1 for i in items if i.trigger == "ENTRY"),
        exit_alert=sum(1 for i in items if i.trigger == "EXIT_ALERT"),
        neutral=sum(1 for i in items if i.trigger == "NEUTRAL"),
        pending=sum(1 for i in items if i.trigger == "PENDING"),
    )
    return WatchlistResponse(count=len(items), items=items, setups=setups, cap=cap)


@router.post("/ticker", response_model=TickerAddResponse, summary="Add a ticker to the watch list")
async def add_ticker(
    body: TickerAddRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> TickerAddResponse:
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    user_id = str(current_user["_id"])
    db = await get_db()

    # ── The plan's ticker cap ────────────────────────────────────────────────
    #
    # The question is "would this add a row", not "is the list full". Re-adding
    # a watched ticker is a no-op upsert and the UI does it deliberately — the
    # web dashboard re-adds the currently selected name. A bare `count >= cap`
    # refuses that, and only once a user is *exactly* at their limit, which is
    # the worst possible time to discover it.
    #
    # Unlimited pays nothing: `cap is None` short-circuits before either query.
    #
    # The race is real and accepted. Two concurrent adds can both pass the
    # count and give cap+1. The unique `(user_id, ticker)` index constrains
    # duplicates, not the total, so nothing here is secretly holding the line —
    # and a transaction to close a benign over-by-one under a double-click is
    # not worth what it costs.
    cap = entitlements_for(current_user).watchlist_cap
    if cap is not None:
        already = await db[COLL_WATCHED].find_one(
            {"user_id": user_id, "ticker": ticker}, {"_id": 1}
        )
        if already is None:
            watching = await db[COLL_WATCHED].count_documents({"user_id": user_id})
            if watching >= cap:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "watchlist_cap",
                        "capability": "watchlist_cap",
                        "cap": cap,
                        "watching": watching,
                        # Names the number and the way out. "Limit reached"
                        # leaves somebody with nothing they can do.
                        "message": f"Your plan covers {cap} tickers. "
                                   f"Remove one to add {ticker}.",
                    },
                )

    await db[COLL_WATCHED].update_one(
        {"user_id": user_id, "ticker": ticker},
        {"$set": {"user_id": user_id, "ticker": ticker}},
        upsert=True,
    )

    # Only run the pipeline for a name the engine has never scored. Every
    # watched ticker joins the 5-minute union anyway, so a name somebody else
    # already watches needs nothing here — and that spend is on the
    # deployment's key, which is the whole reason readers are capped at all.
    if not await db[COLL_SIGNALS].find_one({"ticker": ticker}, {"_id": 1}):
        background_tasks.add_task(_run_pipeline_bg, ticker)
    logger.info("ticker_added", ticker=ticker, user_id=user_id)
    return TickerAddResponse(
        ticker=ticker,
        status="accepted",
        message=f"{ticker} added to watch list. Analysis is running in the background.",
    )


@router.delete("/ticker/{ticker}", summary="Remove a ticker from the watch list")
async def remove_ticker(ticker: str, current_user: dict = Depends(get_current_user)):
    ticker = ticker.upper().strip()
    user_id = str(current_user["_id"])
    db = await get_db()
    result = await db[COLL_WATCHED].delete_one({"user_id": user_id, "ticker": ticker})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in your watch list.")
    logger.info("ticker_removed", ticker=ticker, user_id=user_id)
    return {"ticker": ticker, "status": "removed"}


async def _run_pipeline_bg(ticker: str) -> None:
    try:
        from app.services.pipeline import run_pipeline
        await run_pipeline(ticker)
        logger.info("bg_pipeline_complete", ticker=ticker)
    except Exception as exc:
        logger.error("bg_pipeline_failed", ticker=ticker, error=str(exc))
