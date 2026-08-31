"""
GET /analyze?ticker=PLTR  — run or return cached analysis for a ticker
GET /quote/{ticker}       — one live price, no pipeline
GET /ticker/search?q=     — search ticker symbols via Finnhub
GET /backtest             — backtest stub
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS, get_db
from app.dependencies import get_current_user, tier_refusal
from app.models.stock import (
    AnalyzeResponse, FactorInput, QuoteResponse, ScoreBreakdown, SignalGate,
    SignalInputs,
)
from app.services import rate_limit
from app.services.entitlements import entitlements_for
from app.services.pipeline import run_pipeline
from app.services.risk_engine import RISK_MAX_FOR_BUY
from app.services.scoring import compute_personalized_score, explain_score
from app.services.signal_generator import BUY_THRESHOLD, SELL_THRESHOLD
from app.services.signal_stability import STABILITY_FIELD
from app.utils.logger import get_logger

router = APIRouter(tags=["analysis"])
logger = get_logger(__name__)

_CACHE_TTL_MINUTES = 30


#: Query parameters that carry a credential. httpx renders the full request URL
#: into `HTTPStatusError`, so `str(exc)` on a failed provider call writes the key
#: straight into the log — where it outlives the process, gets shipped off the
#: box, and ends up pasted into an issue.
_SECRET_PARAMS = ("token", "apikey", "api_key")
_SECRET_RE = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_PARAMS) + r")=[^&\s\"']+"
)


def _safe_error(exc: Exception) -> str:
    """The exception message with any credential in it masked, not dropped."""
    return _SECRET_RE.sub(r"\1=***", str(exc))


@router.get("/ticker/search", summary="Search ticker symbols")
async def ticker_search(
    q: str = Query(..., min_length=1, description="Company name or ticker symbol"),
    current_user: dict = Depends(get_current_user),
):
    settings = get_settings()
    if not settings.finnhub_api_key:
        raise HTTPException(status_code=503, detail="Ticker search unavailable: no Finnhub API key configured")
    url = "https://finnhub.io/api/v1/search"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"q": q, "token": settings.finnhub_api_key})
            resp.raise_for_status()
            results = resp.json().get("result", [])
    except Exception as exc:
        logger.warning("ticker_search_failed", query=q, error=_safe_error(exc))
        raise HTTPException(status_code=502, detail="Ticker search temporarily unavailable")

    # Filter to US common stocks only and return clean shape
    filtered = [
        {"symbol": r["symbol"], "name": r["description"]}
        for r in results
        if r.get("type") in ("Common Stock", "EQS") and "." not in r.get("symbol", "")
    ]
    return filtered[:10]


@router.get("/quote/{ticker}", response_model=QuoteResponse, summary="Live price for one ticker")
async def quote(
    ticker: str,
    current_user: dict = Depends(get_current_user),
) -> QuoteResponse:
    """
    One price, fetched now, costing one HTTP call.

    This exists so the ticker page can separate two things that were welded
    together: what the engine concluded, which is a stored judgement that may be
    hours old and is still worth reading, and what the stock is worth, which is
    only worth reading if it is current. Before this, seeing a fresh price meant
    re-running the whole pipeline.

    Not a health probe, and not a violation of the "observed, never probed" rule
    in CLAUDE.md — that rule protects the Alpha Vantage daily cap and answers
    "did this source build the score". This is one user-initiated Finnhub call
    per ticker view, on a different budget, answering "what is it worth now".

    It never raises. No key, an error, or a timeout falls back to the price the
    pipeline last wrote and says so in `source`, because a quote provider being
    down must not blank the page.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    settings = get_settings()
    if settings.finnhub_api_key:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": ticker, "token": settings.finnhub_api_key},
                )
                resp.raise_for_status()
                q = resp.json()
            # Finnhub answers an unknown symbol with a 200 and a body of zeros,
            # so a zero price is "no such ticker", not a stock worth nothing.
            price = _positive(q.get("c"))
            if price is not None:
                return QuoteResponse(
                    ticker=ticker,
                    price=price,
                    day_change_pct=_number(q.get("dp")),
                    open=_positive(q.get("o")),
                    high=_positive(q.get("h")),
                    low=_positive(q.get("l")),
                    prev_close=_positive(q.get("pc")),
                    as_of=_quote_time(q.get("t")),
                    source="live",
                )
            note = "No live quote for this symbol"
        except Exception as exc:
            logger.warning("quote_failed", ticker=ticker, error=_safe_error(exc))
            note = "Live quote unavailable"
    else:
        note = "No Finnhub API key configured"

    return await _stored_quote(ticker, note)


async def _stored_quote(ticker: str, note: str) -> QuoteResponse:
    """The last price the pipeline wrote, labelled as such."""
    db = await get_db()
    raw = await db[COLL_RAW].find_one(
        {"ticker": ticker},
        {"current_price": 1, "day_change_pct": 1, "ingested_at": 1},
    )
    if not raw or raw.get("current_price") is None:
        return QuoteResponse(ticker=ticker, source="unavailable", note=note)

    as_of = raw.get("ingested_at")
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return QuoteResponse(
        ticker=ticker,
        price=_number(raw.get("current_price")),
        day_change_pct=_number(raw.get("day_change_pct")),
        as_of=as_of if isinstance(as_of, datetime) else None,
        source="stored",
        note=note,
    )


def _number(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _positive(v) -> Optional[float]:
    """A price of zero is Finnhub's way of saying it has no idea."""
    n = _number(v)
    return n if n is not None and n > 0 else None


def _quote_time(v) -> Optional[datetime]:
    """Finnhub's `t` is a Unix second stamp; 0 means it did not say."""
    n = _number(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


@router.get("/analyze", response_model=AnalyzeResponse, summary="Analyse a stock ticker")
async def analyze(
    ticker: str = Query(..., description="Stock ticker symbol, e.g. PLTR"),
    force_refresh: bool = Query(False),
    stored_only: bool = Query(
        False,
        description="Return the stored analysis whatever its age, and never run the pipeline.",
    ),
    current_user: dict = Depends(get_current_user),
) -> AnalyzeResponse:
    """
    Three modes, and the difference between them is what a caller is willing to
    wait for.

    `stored_only` reads the last analysis and returns it at any age. It is the
    one mode that cannot start a pipeline run, which is what makes it safe to
    call on every ticker click: a full run is yfinance, Finnhub, FRED,
    fundamentals and an LLM call, and someone glancing at a name did not ask for
    any of that. Nothing stored is a 404 the client renders as an empty state,
    not an error — the same GET-reads-stored / explicit-rebuild split
    `/research/{ticker}` already draws.

    `force_refresh` is the explicit run. Plain `/analyze` keeps its original
    behaviour — stored if fresh, rebuild if not — because the report export and
    the watchlist warm-up still want it.

    **A caller who may not spend tokens gets the stored reading rather than a
    refusal.** See the note on the degradation below; it is the one gate in the
    tier system that does not raise.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    if stored_only and force_refresh:
        raise HTTPException(
            status_code=400,
            detail="stored_only and force_refresh ask for opposite things",
        )

    ent = entitlements_for(current_user)

    # This route cannot be gated by a dependency: whether it costs anything
    # depends on the query string. Two checks, deliberately different in kind.
    if force_refresh and not ent.may_spend_tokens:
        # The explicit run — what the "Run full analysis" button calls. A
        # refusal is the honest answer to something deliberately asked for.
        raise tier_refusal("may_spend_tokens", ent)

    if not ent.may_spend_tokens:
        # The subtle half. Plain `/analyze` rebuilds whenever the cached signal
        # is older than the TTL — a full pipeline run plus an analyst call
        # nobody asked for. But 403ing it would break the report export and the
        # watchlist warm-up, which both call it, so it degrades to the stored
        # reading instead of failing.
        #
        # Removing this does not fail loudly. It just means readers quietly
        # start running pipelines again on the deployment's key — the same
        # silent-regression shape `tests/test_stored_analysis.py` exists to
        # catch, and it is tested in that style.
        stored_only = True

    if force_refresh:
        # The quota, not the entitlement — see `services/rate_limit`. The
        # analyst call inside `run_pipeline` carries no user_id and writes one
        # shared document per ticker, so this spend belongs to the deployment
        # however it was triggered.
        user_key = str(current_user.get("_id") or "")
        decision = rate_limit.check_analysis_allowed(user_key)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="You have used today's full-analysis runs. "
                       "Stored readings are still available.",
                headers={"Retry-After": str(decision.retry_after)},
            )
        rate_limit.record_analysis_run(user_key)

    db = await get_db()

    if not force_refresh:
        cached = await db[COLL_SIGNALS].find_one({"ticker": ticker})
        if cached:
            generated_at = cached.get("generated_at")
            # Age only decides anything when the caller is willing to rebuild.
            if stored_only:
                logger.info("stored_read", ticker=ticker)
                return await _personalized_response(cached, current_user, db)
            if isinstance(generated_at, datetime):
                age = datetime.now(tz=timezone.utc) - generated_at.replace(tzinfo=timezone.utc)
                if age < timedelta(minutes=_CACHE_TTL_MINUTES):
                    logger.info("cache_hit", ticker=ticker, age_seconds=age.seconds)
                    return await _personalized_response(cached, current_user, db)
        if stored_only:
            raise HTTPException(
                status_code=404,
                detail=f"No stored analysis for {ticker}",
            )

    try:
        signal_doc = await run_pipeline(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("analyze_error", ticker=ticker, error=_safe_error(exc))
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    return await _personalized_response(signal_doc, current_user, db)


@router.get("/backtest", summary="Run backtest for a ticker (stub)")
async def backtest(
    ticker: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    from app.config import get_settings
    if not get_settings().enable_backtesting:
        raise HTTPException(status_code=403, detail="Backtesting is disabled. Set ENABLE_BACKTESTING=true.")

    ticker = ticker.upper().strip()
    db = await get_db()
    raw_doc = await db["stocks_raw"].find_one({"ticker": ticker})
    if not raw_doc:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}. Run /analyze first.")

    from app.services.backtesting import run_backtest
    return run_backtest(ticker, raw_doc.get("bars", []))


async def _personalized_response(doc: dict, current_user: dict, db) -> AnalyzeResponse:
    """
    Apply per-user weights, then attach the attribution behind the number.

    The feature document is now fetched unconditionally. It used to be read only
    when the user had custom weights, which meant the default-weight majority
    got a bare composite score with nothing explaining it.
    """
    user_weights = current_user.get("scoring_weights")
    feat = await db[COLL_FEATURES].find_one({"ticker": doc["ticker"]})

    if feat and user_weights:
        feat["risk"] = doc.get("risk", {})
        score, signal = compute_personalized_score(
            feat, user_weights, previous_signal=doc.get("signal")
        )
        doc = {**doc, "score": score, "signal": signal}

    breakdown = explain_score(feat, user_weights) if feat else None
    # The feature document is the live one; the signal document may be a cached
    # analyst verdict from up to an hour ago. Input provenance describes *the
    # score in front of the reader*, so it comes from whichever of the two
    # carries it — preferring the signal, which is what was actually published.
    if not doc.get("inputs") and feat and feat.get("inputs"):
        doc = {**doc, "inputs": feat["inputs"]}
    return _doc_to_response(doc, breakdown=breakdown, user_weights=user_weights)


def _build_gate(doc: dict) -> SignalGate:
    """
    The thresholds behind the verdict, read from the engine rather than restated.

    The dashboard's setup legend hardcodes its thresholds in TSX and will drift;
    this exists so the ticker page does not repeat that mistake.
    """
    score = float(doc.get("score", 0.0) or 0.0)
    risk = doc.get("risk") or {}
    risk_score = float(risk.get("risk_score", 10.0) or 0.0)
    return SignalGate(
        buy_threshold=BUY_THRESHOLD,
        sell_threshold=SELL_THRESHOLD,
        risk_max_for_buy=RISK_MAX_FOR_BUY,
        score_passes_buy=score > BUY_THRESHOLD,
        risk_passes_buy=risk_score < RISK_MAX_FOR_BUY,
    )


def _build_inputs(doc: dict, user_weights: dict | None) -> Optional[SignalInputs]:
    """
    What this score was made of, weighted by the caller's own weights.

    Returns None for a signal generated before this was recorded. A missing
    completeness figure must stay missing rather than defaulting to 1.0, which
    would claim every historical verdict was built on complete data — the same
    rule alpha follows when it cannot be computed.
    """
    stored = doc.get("inputs")
    if not stored or not stored.get("factors"):
        return None

    from app.services.input_quality import completeness, fallback_factors
    from app.services.scoring import ALT_FACTOR, FACTORS, effective_weights

    weights = effective_weights(user_weights)
    labels = {key: label for key, _feature_key, label in FACTORS}
    labels[ALT_FACTOR[0]] = ALT_FACTOR[2]

    factors = [
        FactorInput(
            key=key, label=labels.get(key, key),
            state=entry.get("state", "fallback"),
            coverage=float(entry.get("coverage", 0.0)),
        )
        for key, entry in (stored.get("factors") or {}).items()
        if key in labels
    ]
    return SignalInputs(
        factors=factors,
        completeness=completeness(stored, weights),
        fallback_factors=fallback_factors(stored, weights),
    )


def _doc_to_response(
    doc: dict,
    breakdown: Optional[dict] = None,
    user_weights: dict | None = None,
) -> AnalyzeResponse:
    risk = doc.get("risk", {})
    generated_at = doc.get("generated_at", datetime.now(tz=timezone.utc))
    if isinstance(generated_at, datetime) and generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    ao = doc.get("analyst_output") or {}
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
        conviction=ao.get("conviction"),
        price_target=ao.get("price_target"),
        stop_loss=ao.get("stop_loss"),
        time_horizon=ao.get("time_horizon"),
        thesis=ao.get("thesis"),
        analyst_note=ao.get("analyst_note"),
        bull_case=ao.get("bull_case"),
        bear_case=ao.get("bear_case"),
        bull_points=ao.get("bull_points") or [],
        bear_points=ao.get("bear_points") or [],
        key_risks=ao.get("key_risks") or [],
        catalysts=ao.get("catalysts") or [],
        alternative_data=doc.get("alternative_data"),
        current_price=doc.get("current_price"),
        day_change_pct=doc.get("day_change_pct"),
        analyst_used=bool(doc.get("analyst_used", False)),
        analyst_model=_analyst_model(),
        pending_signal=(doc.get(STABILITY_FIELD) or {}).get("pending_signal"),
        breakdown=ScoreBreakdown(**breakdown) if breakdown else None,
        gate=_build_gate(doc),
        data_sources=doc.get("data_sources"),
        inputs=_build_inputs(doc, user_weights),
    )


def _analyst_model() -> Optional[str]:
    """
    The model this server would call, or None when the analyst is switched off.

    Reported from config rather than from the stored document: the pipeline
    never persisted which model produced a given report, and a stale name is
    worse than an honest "the analyst did not run" (`analyst_used`).
    """
    settings = get_settings()
    if not settings.enable_ai_analyst:
        return None
    return settings.analyst_model
