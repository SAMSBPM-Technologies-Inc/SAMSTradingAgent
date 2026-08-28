"""
Benchmark Returns
─────────────────
What the market did over the same window, so a return can be read as a result
rather than as a number.

This module exists because the engine had no concept of a benchmark at all. A
signal that returned +6% over twenty days was recorded as correct, filed as a
win, and fed to the calibration report — in a month the index rose 8%. Nothing
anywhere could have told the difference between skill and beta, which means
every threshold argued from that record was argued from the wrong quantity.

Three rules, and they are the whole module:

**An alpha we cannot compute stays `None`.** Never `0.0`. A missing benchmark
bar and a benchmark that went nowhere are different facts, and folding the
first into the second understates the market's contribution in one direction
every single time. This is the same rule `commission_paid` follows, for the
same reason.

**The window is the position's window, not a nominal one.** The settlement job
resolves a record once it is ≥28 calendar days old, so its realised return is
measured from the signal date to whenever settlement happened to run. The
benchmark must be measured over exactly that span or the subtraction is
comparing two different periods.

**The series is fetched once and reused.** A settlement pass touches hundreds
of records across dozens of dates; a per-record fetch would be hundreds of
identical requests, and the rate limits on the licensed provider do not allow
it. One cached series covers them all.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app.config import get_settings
from app.services.price_providers import fetch_price_history
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: How much history to hold. Comfortably covers the longest settlement window
#: (28 days) and a slow trade held for a season, with room for the lookup to
#: walk backwards over a long market closure.
_SERIES_DAYS = 400

#: How long a fetched series stays usable. Daily bars change once a day; an
#: hour-old series is the same series. Short enough that a settlement run late
#: in the day sees today's close.
_CACHE_TTL_SECONDS = 3600

#: How far back `close_on_or_before` will walk to find a trading day. Covers a
#: long weekend plus a holiday plus a data gap; beyond that the series is wrong
#: rather than sparse, and returning None is the honest answer.
_MAX_LOOKBACK_DAYS = 10


class _Cache:
    """One fetched series, its ticker, and when it landed."""

    def __init__(self) -> None:
        self.ticker: Optional[str] = None
        self.series: Optional[pd.Series] = None
        self.fetched_at: Optional[datetime] = None
        self.lock = asyncio.Lock()


_cache = _Cache()


def reset_cache() -> None:
    """Drop the cached series. For tests and for a ticker change at runtime."""
    _cache.ticker = None
    _cache.series = None
    _cache.fetched_at = None


def benchmark_ticker() -> str:
    return (get_settings().benchmark_ticker or "SPY").upper()


async def benchmark_closes() -> Optional[pd.Series]:
    """
    Daily closes for the configured benchmark, indexed by UTC date.

    Returns None rather than raising. Every caller here is settling or
    reporting, and neither is worth failing a job over — the alpha simply stays
    unknown, which is a state the schema already carries.
    """
    ticker = benchmark_ticker()
    now = datetime.now(tz=timezone.utc)

    if (
        _cache.series is not None
        and _cache.ticker == ticker
        and _cache.fetched_at is not None
        and (now - _cache.fetched_at).total_seconds() < _CACHE_TTL_SECONDS
    ):
        return _cache.series

    async with _cache.lock:
        # Re-check: another coroutine may have filled it while we waited.
        if (
            _cache.series is not None
            and _cache.ticker == ticker
            and _cache.fetched_at is not None
            and (datetime.now(tz=timezone.utc) - _cache.fetched_at).total_seconds()
            < _CACHE_TTL_SECONDS
        ):
            return _cache.series

        try:
            frame = await fetch_price_history(ticker, _SERIES_DAYS)
        except Exception as exc:
            logger.warning("benchmark_fetch_failed", ticker=ticker, error=str(exc))
            return None

        if frame is None or frame.empty or "Close" not in frame.columns:
            logger.warning("benchmark_series_empty", ticker=ticker)
            return None

        series = frame["Close"].dropna()
        if series.empty:
            logger.warning("benchmark_series_all_null", ticker=ticker)
            return None

        series = series.sort_index()
        _cache.ticker = ticker
        _cache.series = series
        _cache.fetched_at = datetime.now(tz=timezone.utc)
        logger.debug("benchmark_series_cached", ticker=ticker, bars=len(series))
        return series


def _as_utc(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def close_on_or_before(series: pd.Series, when: datetime) -> Optional[float]:
    """
    The benchmark close on `when`, or the most recent trading day before it.

    Walking backwards is not a convenience: a signal generated on a Sunday, a
    holiday, or before the open has no bar of its own, and pairing it with the
    *next* bar would measure a window the position did not have. Bounded by
    `_MAX_LOOKBACK_DAYS` so a truncated series returns None instead of silently
    reaching back a month.
    """
    if series is None or series.empty:
        return None

    target = _as_utc(when)
    index = series.index
    try:
        # `index` is tz-aware UTC from every provider; normalise defensively so
        # a naive index from a fixture does not raise on comparison.
        if getattr(index, "tz", None) is None:
            index = index.tz_localize(timezone.utc)
            series = pd.Series(series.values, index=index)
    except (TypeError, AttributeError):
        return None

    window = series[series.index <= target]
    if window.empty:
        return None

    last_stamp = window.index[-1]
    if (target - last_stamp.to_pydatetime()) > timedelta(days=_MAX_LOOKBACK_DAYS):
        return None
    return float(window.iloc[-1])


async def benchmark_return(start: datetime, end: Optional[datetime] = None) -> Optional[float]:
    """
    Fractional benchmark return between two instants, or None if unmeasurable.

    `end` defaults to now, which is what settlement wants: the realised return
    it pairs this with is also measured to the moment the job ran.
    """
    series = await benchmark_closes()
    if series is None:
        return None

    open_close = close_on_or_before(series, start)
    close_close = close_on_or_before(series, end or datetime.now(tz=timezone.utc))
    if open_close is None or close_close is None or open_close == 0:
        return None
    return (close_close - open_close) / open_close


def alpha(realised: Optional[float], benchmark: Optional[float]) -> Optional[float]:
    """
    Excess return over the benchmark, or None when either side is unknown.

    A one-line function with a comment longer than itself, because the mistake
    it prevents is the one this module was written for: `(realised or 0) -
    (benchmark or 0)` reads as defensive and is not. It reports a full alpha for
    a position whose benchmark never loaded, every time the market was up.
    """
    if realised is None or benchmark is None:
        return None
    return realised - benchmark
