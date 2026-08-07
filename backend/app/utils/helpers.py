"""
General-purpose helpers used across services.
"""
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
