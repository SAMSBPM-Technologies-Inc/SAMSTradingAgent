"""
Data Ingestion Service
─────────────────────
Fetches OHLCV data from Yahoo Finance, real sentiment from Finnhub,
fundamentals from yfinance, and macro data from FRED, then persists
raw records to `stocks_raw` in MongoDB.
"""
from datetime import datetime, timezone

import asyncio

import httpx
import pandas as pd

from app.db import COLL_RAW, get_db
from app.services.fundamentals import fetch_fundamentals
from app.services.macro import fetch_macro_data
from app.services.news import fetch_news_sentiment, fetch_recent_headlines
from app.services.price_providers import fetch_price_history, get_price_provider
from app.utils.helpers import safe_float, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many calendar days of history to pull on each ingestion run.
#
# Raised from 90 for the momentum factor, and matched to
# `benchmark._SERIES_DAYS` deliberately: relative strength subtracts one series
# from the other, so a ticker holding less history than the benchmark simply
# cannot be measured over the longer horizon. 90 calendar days is roughly 62
# trading bars — short of the 148 the 6-month-skip-1-month component needs and
# short of the 120 the range position needs, so at 90 the factor could only
# ever return its 3-month leg, marginally, and coverage-weight the rest to
# neutral for every ticker forever.
#
# It is one provider call either way; only the row count changes. The cost is
# that `stocks_raw.bars` grows roughly fourfold, and that document is read on
# every ticker on the 5-minute cycle — a few tens of KB per ticker, which is
# why this is a considered number rather than "as much as possible".
#
# Fixed-window indicators (RSI-14, MACD, Bollinger-20, ATR-14, MA-20/50,
# volatility-20d) are unchanged by the extra warm-up; `/chart/{ticker}/series`
# slices to the window the client asked for and can now actually serve a
# request longer than three months.
HISTORY_DAYS = 400


async def ingest_ticker(ticker: str) -> dict:
    """
    Fetch price history, real sentiment, fundamentals, and macro data for *ticker*.
    Upserts a document in `stocks_raw` keyed by ticker.
    Returns the stored document dict.
    """
    ticker = ticker.upper()
    logger.info("ingestion_start", ticker=ticker)

    try:
        df = await _fetch_price_history(ticker)
    except Exception as exc:
        logger.error("ingestion_fetch_failed", ticker=ticker, error=str(exc))
        raise

    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")

    # Build list of OHLCV bars
    bars = []
    for ts, row in df.iterrows():
        bars.append(
            {
                "date": ts.to_pydatetime().replace(tzinfo=timezone.utc),
                "open": safe_float(row.get("Open")),
                "high": safe_float(row.get("High")),
                "low": safe_float(row.get("Low")),
                "close": safe_float(row.get("Close")),
                "volume": safe_float(row.get("Volume")),
            }
        )

    current_price = bars[-1]["close"]
    prev_close = bars[-2]["close"] if len(bars) > 1 else current_price
    day_change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0.0

    # Fetch real data from all enrichment sources (all degrade gracefully)
    sentiment_raw, headlines, fundamentals, macro, alternative_data = await _fetch_enrichment(ticker)

    doc = {
        "ticker": ticker,
        "ingested_at": utcnow(),
        # Which provider these bars came from. Recorded because it is the one
        # input that can stop a cycle outright, and because `yahoo` carries a
        # licensing statement that `polygon` does not — a reader of a signal
        # deserves to know which one produced the prices behind it.
        "price_source": get_price_provider().name,
        "bars": bars,
        "current_price": current_price,
        "day_change_pct": round(day_change_pct, 4),
        "sentiment_raw": sentiment_raw,
        "recent_headlines": headlines,
        "fundamentals": fundamentals,
        "macro": macro,
        "alternative_data": alternative_data,
    }

    db = await get_db()
    await db[COLL_RAW].replace_one({"ticker": ticker}, doc, upsert=True)

    logger.info(
        "ingestion_complete",
        ticker=ticker,
        bars=len(bars),
        current_price=current_price,
        day_change_pct=round(day_change_pct, 4),
        sentiment_source=sentiment_raw.get("source"),
        macro_source=macro.get("source"),
    )
    return doc


async def ingest_all(tickers: list[str]) -> dict[str, str]:
    """
    Ingest a list of tickers sequentially.
    Returns a mapping of ticker → "ok" | error message.
    """
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await ingest_ticker(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            results[ticker] = str(exc)
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_enrichment(ticker: str) -> tuple[dict, list, dict, dict, dict]:
    """
    Fetch sentiment, headlines, fundamentals, macro, and alternative data concurrently.
    Any individual failure returns a safe default so the pipeline keeps running.
    """
    import asyncio
    from app.services.alternative_data import fetch_alternative_data

    sentiment_task    = fetch_news_sentiment(ticker)
    headlines_task    = fetch_recent_headlines(ticker)
    fundamentals_task = fetch_fundamentals(ticker)
    macro_task        = fetch_macro_data()
    alt_task          = fetch_alternative_data(ticker)

    sentiment, headlines, fundamentals, macro, alternative = await asyncio.gather(
        sentiment_task,
        headlines_task,
        fundamentals_task,
        macro_task,
        alt_task,
        return_exceptions=True,
    )

    # Replace any unexpected exception with a safe default
    if isinstance(sentiment, Exception):
        logger.warning("sentiment_exception", ticker=ticker, error=str(sentiment))
        sentiment = {"score": 0.5, "article_count": 0, "source": "exception"}
    if isinstance(headlines, Exception):
        headlines = []
    if isinstance(fundamentals, Exception):
        logger.warning("fundamentals_exception", ticker=ticker, error=str(fundamentals))
        fundamentals = {"ticker": ticker, "source": "exception"}
    if isinstance(macro, Exception):
        logger.warning("macro_exception", error=str(macro))
        macro = {"source": "exception"}
    if isinstance(alternative, Exception):
        logger.warning("alternative_data_exception", ticker=ticker, error=str(alternative))
        alternative = {}

    return sentiment, headlines, fundamentals, macro, alternative


async def _fetch_price_history(ticker: str) -> pd.DataFrame:
    """
    OHLCV history from the configured provider.

    The Yahoo-specific fetch that used to live here moved to
    `services/price_providers.py` behind a seam, so replacing the unlicensed
    development source with a licensed one is a `PRICE_PROVIDER` change rather
    than an edit to the ingestion path.
    """
    return await fetch_price_history(ticker, HISTORY_DAYS)
