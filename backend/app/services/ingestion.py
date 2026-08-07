"""
Data Ingestion Service
─────────────────────
Fetches OHLCV data from yfinance, generates mock sentiment,
and persists raw records to `stocks_raw` in MongoDB.
"""
import random
from datetime import datetime, timezone

import yfinance as yf

from app.db import COLL_RAW, get_db
from app.utils.helpers import safe_float, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How many calendar days of history to pull on each ingestion run
HISTORY_DAYS = 90


async def ingest_ticker(ticker: str) -> dict:
    """
    Fetch price history + mock sentiment for *ticker*.
    Upserts a document in `stocks_raw` keyed by (ticker, date of latest bar).
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

    doc = {
        "ticker": ticker,
        "ingested_at": utcnow(),
        "bars": bars,
        "current_price": current_price,
        "day_change_pct": round(day_change_pct, 4),
        # Mock sentiment: real pipeline would call a news API here
        "sentiment_raw": _mock_sentiment(ticker),
    }

    db = await get_db()
    # Replace the most-recent document for this ticker (one live doc per ticker)
    await db[COLL_RAW].replace_one(
        {"ticker": ticker},
        doc,
        upsert=True,
    )

    logger.info(
        "ingestion_complete",
        ticker=ticker,
        bars=len(bars),
        current_price=current_price,
        day_change_pct=day_change_pct,
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

def _fetch_price_history(ticker: str):
    """Download OHLCV history via Yahoo Finance v8 chart API. Returns a DataFrame."""
    import time
    import requests
    import pandas as pd

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

    df = pd.DataFrame({
        "Open": ohlcv.get("open", []),
        "High": ohlcv.get("high", []),
        "Low": ohlcv.get("low", []),
        "Close": adjclose if adjclose else ohlcv.get("close", []),
        "Volume": ohlcv.get("volume", []),
    }, index=pd.to_datetime(timestamps, unit="s", utc=True))

    return df.dropna(subset=["Close"])


def _mock_sentiment(ticker: str) -> dict:
    """
    Return a mock sentiment object.
    Replace with a real news-API call (e.g. NewsAPI, Finnhub) when available.
    Scores are seeded from the ticker string for reproducibility in dev.
    """
    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed + int(datetime.now(tz=timezone.utc).timestamp() // 3600))
    return {
        "score": round(rng.uniform(0.2, 0.8), 3),   # 0=very negative, 1=very positive
        "article_count": rng.randint(1, 20),
        "source": "mock",
    }
