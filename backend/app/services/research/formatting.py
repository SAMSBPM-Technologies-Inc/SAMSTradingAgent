"""
Value formatting for the evidence ledger.

Every helper returns None for a missing input rather than a placeholder string.
That is deliberate and load-bearing: `Ledger.add` drops a None value, so a
formatter that returned "N/A" would smuggle absent data into the ledger with an
id attached, and an agent would cite it. The prompt's `next_earnings_date: N/A`
line is exactly that failure in its earlier form — a field the model was
invited to reason about that had never once carried a value.
"""
from __future__ import annotations

from typing import Optional


def pct(value: Optional[float], digits: int = 1) -> Optional[str]:
    """A fraction (0.604) as a percentage string ("60.4%")."""
    if value is None:
        return None
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return None


def pct_points(value: Optional[float], digits: int = 1) -> Optional[str]:
    """A change in a fraction, rendered in percentage points with a sign."""
    if value is None:
        return None
    try:
        return f"{float(value) * 100:+.{digits}f}pp"
    except (TypeError, ValueError):
        return None


def ratio(value: Optional[float], digits: int = 2, suffix: str = "") -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return None


def money(value: Optional[float]) -> Optional[str]:
    """
    A dollar figure at human scale.

    Statement values arrive in raw dollars, so a revenue line is a 12-digit
    integer. Rendering it as "$130,497,000,000" in a prompt spends tokens on
    digits nobody reads and makes two companies harder to compare, not easier.
    """
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None

    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    for cutoff, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if amount >= cutoff:
            return f"{sign}${amount / cutoff:.2f}{unit}"
    return f"{sign}${amount:,.2f}"


def count(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return None
