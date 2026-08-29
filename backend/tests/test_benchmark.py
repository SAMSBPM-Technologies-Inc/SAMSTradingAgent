"""
Tests for benchmark-relative measurement.

The engine had no concept of a benchmark. A signal that returned +6% over
twenty days was recorded as correct and fed to the calibration report, in a
month the index rose 8% — and nothing anywhere could tell skill from beta.

The rule these tests exist to protect is the one that is easy to write wrongly
and impossible to notice afterwards: **an alpha we cannot compute stays None,
never 0.0.** A zero benchmark reports a position's whole return as alpha, and
does it in the flattering direction every time the market rose. `commission_paid`
follows the same rule for the same reason.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import benchmark as bm  # noqa: E402


def series(start: datetime, closes: list[float], step_days: int = 1) -> pd.Series:
    """A daily close series indexed in UTC, oldest first."""
    index = pd.DatetimeIndex(
        [start + timedelta(days=i * step_days) for i in range(len(closes))],
        tz=timezone.utc,
    )
    return pd.Series(closes, index=index)


BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)


# ── alpha() ───────────────────────────────────────────────────────────────────

def test_alpha_is_the_difference():
    assert bm.alpha(0.06, 0.08) == pytest.approx(-0.02)
    assert bm.alpha(0.06, -0.02) == pytest.approx(0.08)


def test_alpha_is_none_when_the_benchmark_is_unknown():
    """
    The whole point. `(realised or 0) - (benchmark or 0)` reads as defensive
    and would report 6% of alpha here.
    """
    assert bm.alpha(0.06, None) is None


def test_alpha_is_none_when_the_return_is_unknown():
    assert bm.alpha(None, 0.08) is None


def test_alpha_of_zero_benchmark_is_still_a_number():
    """A market that went nowhere is a measurement, not a gap."""
    assert bm.alpha(0.06, 0.0) == pytest.approx(0.06)


# ── close_on_or_before() ──────────────────────────────────────────────────────

def test_exact_day_returns_that_close():
    s = series(BASE, [100.0, 101.0, 102.0])
    assert bm.close_on_or_before(s, BASE + timedelta(days=1)) == 101.0


def test_walks_back_to_the_previous_trading_day():
    """
    A signal generated on a Sunday has no bar of its own. Pairing it with the
    *next* bar would measure a window the position did not have.
    """
    s = series(BASE, [100.0, 101.0], step_days=3)  # gap between the two bars
    got = bm.close_on_or_before(s, BASE + timedelta(days=2))
    assert got == 100.0


def test_refuses_to_reach_back_further_than_the_lookback_bound():
    """
    Beyond a long weekend plus a holiday the series is wrong rather than
    sparse, and inventing a pairing across a month would silently mismeasure.
    """
    s = series(BASE, [100.0])
    far = BASE + timedelta(days=bm._MAX_LOOKBACK_DAYS + 5)
    assert bm.close_on_or_before(s, far) is None


def test_before_the_series_starts_is_none():
    s = series(BASE, [100.0, 101.0])
    assert bm.close_on_or_before(s, BASE - timedelta(days=3)) is None


def test_empty_series_is_none_not_zero():
    assert bm.close_on_or_before(pd.Series(dtype=float), BASE) is None


def test_naive_index_is_treated_as_utc_rather_than_raising():
    """Fixtures and older stored frames are not always tz-aware."""
    naive = pd.Series(
        [100.0, 104.0],
        index=pd.DatetimeIndex([BASE.replace(tzinfo=None),
                                (BASE + timedelta(days=1)).replace(tzinfo=None)]),
    )
    assert bm.close_on_or_before(naive, BASE + timedelta(days=1)) == 104.0


# ── benchmark_return() ────────────────────────────────────────────────────────
# The suite convention is `asyncio.run` in a sync test rather than a plugin
# marker — pytest-asyncio is not a dependency here.

def test_return_is_measured_over_the_window_given(monkeypatch):
    s = series(BASE, [100.0, 102.0, 108.0])
    monkeypatch.setattr(bm, "benchmark_closes", lambda: _async(s))
    got = asyncio.run(bm.benchmark_return(BASE, BASE + timedelta(days=2)))
    assert got == pytest.approx(0.08)


def test_return_is_none_when_the_series_cannot_be_read(monkeypatch):
    """A settlement pass must not fail because the benchmark provider is down."""
    monkeypatch.setattr(bm, "benchmark_closes", lambda: _async(None))
    assert asyncio.run(bm.benchmark_return(BASE)) is None


def test_return_is_none_when_the_window_opens_outside_the_series(monkeypatch):
    s = series(BASE, [100.0, 102.0])
    monkeypatch.setattr(bm, "benchmark_closes", lambda: _async(s))
    got = asyncio.run(
        bm.benchmark_return(BASE - timedelta(days=30), BASE + timedelta(days=1))
    )
    assert got is None


# ── the fetch path ────────────────────────────────────────────────────────────

def test_a_provider_failure_is_swallowed_into_none(monkeypatch):
    """
    `fetch_price_history` raises rather than falling back to an unlicensed
    source. That is correct there and must not propagate here: the caller is
    settling records, and an unknown alpha is a state the schema carries.
    """
    bm.reset_cache()

    async def boom(ticker, days):
        raise RuntimeError("provider down")

    monkeypatch.setattr(bm, "fetch_price_history", boom)
    assert asyncio.run(bm.benchmark_closes()) is None
    bm.reset_cache()


def test_an_empty_frame_is_none_rather_than_an_empty_series(monkeypatch):
    bm.reset_cache()

    async def empty(ticker, days):
        return pd.DataFrame()

    monkeypatch.setattr(bm, "fetch_price_history", empty)
    assert asyncio.run(bm.benchmark_closes()) is None
    bm.reset_cache()


def test_the_series_is_fetched_once_and_reused(monkeypatch):
    """
    A settlement pass touches hundreds of records across dozens of dates. A
    per-record fetch would be hundreds of identical requests, which the
    licensed provider's rate limit does not allow.
    """
    bm.reset_cache()
    calls = {"n": 0}

    async def counted(ticker, days):
        calls["n"] += 1
        return pd.DataFrame({"Close": [100.0, 101.0]},
                            index=pd.DatetimeIndex(
                                [BASE, BASE + timedelta(days=1)], tz=timezone.utc))

    monkeypatch.setattr(bm, "fetch_price_history", counted)

    async def three_times():
        await bm.benchmark_closes()
        await bm.benchmark_closes()
        await bm.benchmark_closes()

    asyncio.run(three_times())
    assert calls["n"] == 1
    bm.reset_cache()


async def _async(value):
    return value
