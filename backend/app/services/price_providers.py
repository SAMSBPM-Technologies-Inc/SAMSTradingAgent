"""
Price History Providers
───────────────────────
OHLCV bars, behind a seam so the source is a config change rather than a
rewrite.

Why this exists: price history was fetched by calling Yahoo's undocumented
`/v8/finance/chart` endpoint directly with a spoofed browser User-Agent. That
is a weaker position than the yfinance library it superficially resembles —
there is no licence, no terms permitting it, no SLA, and no support if the
shape changes. It also cannot legitimately back a product sold to anyone.

`fundamentals_providers.py` already made this move for fundamentals (Massive +
Alpha Vantage). This is the same move for prices, and deliberately leaves the
Yahoo path in place as the development default so nothing breaks before a
licensed plan exists.

    PRICE_PROVIDER=yahoo     development only — undocumented endpoint, no licence
    PRICE_PROVIDER=polygon   Massive/Polygon aggregates; needs MASSIVE_API_KEY
                             on a plan that includes daily aggregates

Both return the same DataFrame: a UTC DatetimeIndex with Open/High/Low/Close/
Volume columns, so `ingestion.py` does not care which ran.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
import pandas as pd

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MASSIVE_BASE = "https://api.massive.com"
_HTTP_TIMEOUT = 20.0

#: Columns every provider must return, in this order.
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class PriceProvider(Protocol):
    """Anything that can return daily OHLCV for a ticker."""

    name: str

    async def fetch(self, ticker: str, days: int) -> pd.DataFrame:
        ...


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], tz="UTC"))


class YahooChartProvider:
    """
    Yahoo's public chart endpoint.

    Development only. This is an undocumented endpoint accessed with a browser
    User-Agent; it is not licensed for commercial use and can change or start
    refusing requests without notice. Kept as the default so development works
    out of the box, and reported honestly in the UI as "Dev data".
    """

    name = "yahoo"

    async def fetch(self, ticker: str, days: int) -> pd.DataFrame:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        params = {"interval": "1d", "range": f"{days}d"}
        hosts = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

        last_exc: Exception | None = None
        data: dict = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt, host in enumerate(hosts):
                if attempt > 0:
                    await asyncio.sleep(1)
                try:
                    resp = await client.get(
                        f"https://{host}/v8/finance/chart/{ticker}",
                        headers=headers, params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except Exception as exc:
                    last_exc = exc
            else:
                raise last_exc  # type: ignore[misc]

        result = data.get("chart", {}).get("result", [])
        if not result:
            return _empty()

        chart = result[0]
        timestamps = chart.get("timestamp", [])
        ohlcv = chart.get("indicators", {}).get("quote", [{}])[0]
        adjclose = (
            chart.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
        )

        df = pd.DataFrame(
            {
                "Open": ohlcv.get("open", []),
                "High": ohlcv.get("high", []),
                "Low": ohlcv.get("low", []),
                # Adjusted close when present: splits and dividends otherwise
                # produce phantom gaps that every indicator downstream reads as
                # real price action.
                "Close": adjclose if adjclose else ohlcv.get("close", []),
                "Volume": ohlcv.get("volume", []),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True),
        )
        return df.dropna(subset=["Close"])


class PolygonAggregatesProvider:
    """
    Massive/Polygon daily aggregates — the licensed path.

    Requires `MASSIVE_API_KEY` on a plan that includes aggregates; the key used
    for fundamentals does not necessarily cover them. Returns adjusted bars
    (`adjusted=true`) to match the Yahoo path's use of adjusted close, so
    switching providers does not silently change what the indicators see.
    """

    name = "polygon"

    async def fetch(self, ticker: str, days: int) -> pd.DataFrame:
        settings = get_settings()
        key = settings.massive_api_key
        if not key:
            raise RuntimeError(
                "PRICE_PROVIDER=polygon but MASSIVE_API_KEY is unset."
            )

        end = datetime.now(tz=timezone.utc).date()
        # Calendar days, padded for weekends and holidays — asking for N trading
        # days by calendar range otherwise returns roughly 5/7 of them.
        start = end - timedelta(days=int(days * 1.5) + 10)

        url = (
            f"{_MASSIVE_BASE}/v2/aggs/ticker/{ticker.upper()}/range/1/day/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        headers = {"Authorization": f"Bearer {key}"}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
            resp = await client.get(url, params={"adjusted": "true", "limit": 50000})
            resp.raise_for_status()
            payload = resp.json()

        results = payload.get("results") or []
        if not results:
            logger.warning(
                "polygon_no_bars", ticker=ticker,
                status=payload.get("status"), count=payload.get("resultsCount"),
            )
            return _empty()

        df = pd.DataFrame(
            {
                "Open": [r.get("o") for r in results],
                "High": [r.get("h") for r in results],
                "Low": [r.get("l") for r in results],
                "Close": [r.get("c") for r in results],
                "Volume": [r.get("v") for r in results],
            },
            # `t` is epoch milliseconds at the start of the aggregate window.
            index=pd.to_datetime([r.get("t") for r in results], unit="ms", utc=True),
        )
        df = df.dropna(subset=["Close"]).sort_index()
        return df.tail(days)


_PROVIDERS: dict[str, PriceProvider] = {
    YahooChartProvider.name: YahooChartProvider(),
    PolygonAggregatesProvider.name: PolygonAggregatesProvider(),
}


def get_price_provider() -> PriceProvider:
    """The configured provider, falling back to Yahoo with a loud warning."""
    configured = (get_settings().price_provider or "yahoo").lower()
    provider = _PROVIDERS.get(configured)
    if provider is None:
        logger.error(
            "unknown_price_provider_falling_back",
            configured=configured, known=sorted(_PROVIDERS),
        )
        return _PROVIDERS["yahoo"]
    return provider


async def fetch_price_history(ticker: str, days: int) -> pd.DataFrame:
    """
    Bars from the configured provider.

    A licensed provider failing does NOT silently fall back to the unlicensed
    one — that would quietly reintroduce exactly the exposure the switch exists
    to remove. It raises, and the caller decides.
    """
    provider = get_price_provider()
    df = await provider.fetch(ticker, days)
    logger.debug("price_history_fetched", ticker=ticker, provider=provider.name, bars=len(df))
    return df
