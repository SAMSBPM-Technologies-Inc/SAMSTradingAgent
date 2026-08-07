"""
Data Ingestion Service
─────────────────────
Fetches OHLCV data from Yahoo Finance, real sentiment from Finnhub,
fundamentals from yfinance, and macro data from FRED, then persists
raw records to `stocks_raw` in MongoDB.
"""
from datetime import datetime, timezone

import pandas as pd
import requests

from app.db import COLL_RAW, get_db
from app.services.fundamentals import fetch_fundamentals
from app.services.macro import fetch_macro_data
from app.services.news import fetch_news_sentiment, fetch_recent_headlines
from app.utils.helpers import safe_float, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many calendar days of history to pull on each ingestion run
HISTORY_DAYS = 90


async def ingest_ticker(ticker: str) -> dict:
    """
    Fetch price history, real sentiment, fundamentals, and macro data for *ticker*.
    Upserts a document in `stocks_raw` keyed by ticker.
    Returns the stored document dict.
    """
    ticker = ticker.upper()
    logger.info("ingestion_start", ticker=ticker)

    try:
        df = _fetch_price_history(ticker)
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

    # Fetch real data from all three enrichment sources (all degrade gracefully)
    sentiment_raw, headlines, fundamentals, macro = await _fetch_enrichment(ticker)

    doc = {
        "ticker": ticker,
        "ingested_at": utcnow(),
        "bars": bars,
        "current_price": current_price,
        "day_change_pct": round(day_change_pct, 4),
        "sentiment_raw": sentiment_raw,
        "recent_headlines": headlines,
        "fundamentals": fundamentals,
        "macro": macro,
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

async def _fetch_enrichment(ticker: str) -> tuple[dict, list, dict, dict]:
    """
    Fetch sentiment, headlines, fundamentals, and macro data concurrently.
    Any individual failure returns a safe default so the pipeline keeps running.
    """
    import asyncio

    sentiment_task = fetch_news_sentiment(ticker)
    headlines_task = fetch_recent_headlines(ticker)
    fundamentals_task = fetch_fundamentals(ticker)
    macro_task = fetch_macro_data()

    sentiment, headlines, fundamentals, macro = await asyncio.gather(
        sentiment_task,
        headlines_task,
        fundamentals_task,
        macro_task,
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

    return sentiment, headlines, fundamentals, macro


def _fetch_price_history(ticker: str) -> pd.DataFrame:
    """Download OHLCV history via Yahoo Finance v8 chart API. Returns a DataFrame."""
    import time

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    params = f"?interval=1d&range={HISTORY_DAYS}d"
    hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

    last_exc = None
    for attempt, host in enumerate(hosts):
        if attempt > 0:
            time.sleep(2)
        try:
            url = f"https://{host}/v8/finance/chart/{ticker}{params}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_exc = exc
    else:
        raise last_exc

    result = data.get("chart", {}).get("result", [])
    if not result:
        return pd.DataFrame()

    chart = result[0]
    timestamps = chart.get("timestamp", [])
    ohlcv = chart.get("indicators", {}).get("quote", [{}])[0]
    adjclose = chart.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])

    df = pd.DataFrame(
        {
            "Open": ohlcv.get("open", []),
            "High": ohlcv.get("high", []),
            "Low": ohlcv.get("low", []),
            "Close": adjclose if adjclose else ohlcv.get("close", []),
            "Volume": ohlcv.get("volume", []),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    return df.dropna(subset=["Close"])
