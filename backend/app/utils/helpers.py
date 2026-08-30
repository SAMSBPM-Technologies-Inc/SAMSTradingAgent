"""
General-purpose helpers used across services.
"""
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

#: The exchange clock. Everything user-facing in this system is quoted in it.
ET = ZoneInfo("America/New_York")


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def is_market_hours(now: datetime | None = None) -> bool:
    """
    Whether the NYSE is open (approximate — no holiday calendar).

    Lives here rather than in the scheduler because two very different things
    need it: the job that decides whether to run a cycle, and anything judging
    how *stale* the last cycle is. Without the second, a status page reports a
    total outage every night and all weekend, which is the fastest way to build
    a page nobody believes.
    """
    now = (now or datetime.now(tz=ET)).astimezone(ET)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
