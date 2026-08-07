"""
News & Sentiment Service
────────────────────────
Fetches recent company news from Finnhub (free tier: /company-news endpoint)
and computes sentiment locally using VADER on the headlines.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon-based
sentiment analyser that works well on short, finance-style news headlines
with no API key or model download required.

Finnhub free tier: 60 calls/min — fine for 5–20 tickers on a 5-min scheduler.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_FINNHUB_BASE = "https://finnhub.io/api/v1"


async def fetch_news_sentiment(ticker: str) -> dict:
    """
    Return a sentiment dict for *ticker* derived from real Finnhub headlines.

    Keys:
        score         float 0–1   (0 = very bearish, 1 = very bullish)
        article_count int
        bullish_pct   float 0–1
        bearish_pct   float 0–1
        buzz          float       (article_count / 10, capped at 1.0)
        source        str         ("finnhub+vader" | "no_api_key" | "error")
    """
    settings = get_settings()
    api_key = settings.finnhub_api_key

    if not api_key:
        logger.warning(
            "finnhub_key_missing",
            ticker=ticker,
            hint="Set FINNHUB_API_KEY in .env for real sentiment",
        )
        return _neutral("no_api_key")

    try:
        headlines = await _fetch_headlines(ticker, api_key, days=7)
        if not headlines:
            return _neutral("no_articles")
        return _vader_sentiment(ticker, headlines)
    except Exception as exc:
        logger.warning("news_sentiment_failed", ticker=ticker, error=str(exc))
        return _neutral("error")


async def fetch_recent_headlines(ticker: str, days: int = 7) -> list[dict]:
    """
    Return up to 20 recent news headlines for *ticker* from Finnhub.
    Returns an empty list if the API key is absent or the call fails.

    Each item: {headline, datetime, url, source, category}
    """
    settings = get_settings()
    api_key = settings.finnhub_api_key
    if not api_key:
        return []

    try:
        articles = await _fetch_raw_articles(ticker, api_key, days)
        return [
            {
                "headline": a.get("headline", ""),
                "datetime": datetime.fromtimestamp(
                    a.get("datetime", 0), tz=timezone.utc
                ).isoformat(),
                "url": a.get("url", ""),
                "source": a.get("source", ""),
                "category": a.get("category", ""),
            }
            for a in articles[:20]
        ]
    except Exception as exc:
        logger.warning("finnhub_headlines_failed", ticker=ticker, error=str(exc))
        return []


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_headlines(ticker: str, api_key: str, days: int) -> list[str]:
    """Return a list of headline strings from Finnhub /company-news."""
    articles = await _fetch_raw_articles(ticker, api_key, days)
    return [a["headline"] for a in articles if a.get("headline")]


async def _fetch_raw_articles(ticker: str, api_key: str, days: int) -> list[dict]:
    today = datetime.now(tz=timezone.utc)
    from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    params = {"symbol": ticker, "from": from_date, "to": to_date, "token": api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_FINNHUB_BASE}/company-news", params=params)
        resp.raise_for_status()
    return resp.json() or []


def _vader_sentiment(ticker: str, headlines: list[str]) -> dict:
    """Run VADER on the headline list and return a sentiment dict."""
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    sia = SentimentIntensityAnalyzer()
    scores = [sia.polarity_scores(h)["compound"] for h in headlines]

    # compound is -1 to +1; normalise to 0–1
    avg_compound = sum(scores) / len(scores)
    normalised = round((avg_compound + 1) / 2, 4)   # -1→0, 0→0.5, +1→1

    bullish = sum(1 for s in scores if s > 0.05)
    bearish = sum(1 for s in scores if s < -0.05)
    total = len(scores)

    bullish_pct = round(bullish / total, 4)
    bearish_pct = round(bearish / total, 4)
    buzz = round(min(total / 10, 1.0), 4)   # 10+ articles = max buzz

    logger.info(
        "vader_sentiment_ok",
        ticker=ticker,
        score=normalised,
        articles=total,
        bullish_pct=bullish_pct,
        bearish_pct=bearish_pct,
    )
    return {
        "score": normalised,
        "article_count": total,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "buzz": buzz,
        "source": "finnhub+vader",
    }


def _neutral(reason: str) -> dict:
    return {
        "score": 0.5,
        "article_count": 0,
        "bullish_pct": 0.5,
        "bearish_pct": 0.5,
        "buzz": 0.0,
        "source": reason,
    }
