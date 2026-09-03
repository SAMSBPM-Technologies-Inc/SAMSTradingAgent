"""
Momentum / Relative Strength
────────────────────────────
The one thing the composite could not say: *this is working*.

Why this module exists
──────────────────────
Every trend input in this system was consumed as a discount. Under the
production stance (`technical_stance=mean_reversion`) `_technical_score` gates
its oscillators as `osc × (0.40 + 0.60 × trend)` — a multiplier whose ceiling
is 1.0 — and the stance weights for MACD (0.15) and the MA cross (0.10) are
discarded on that path entirely. Trend could therefore only ever subtract.
Measured on the real function, an extended market leader scored **0.037**
technically while a stock in free fall scored **0.391**: the composite ranked a
collapsing name ten times above a leader, and no amount of fundamental or news
strength could reach `BUY_THRESHOLD` from 0.037 × 0.30.

Nothing else filled the gap. There is no rate-of-change, relative-strength or
52-week-position term anywhere in `feature_engineering`, `scoring` or
`catalyst`; `week52_high` is fetched by the Alpha Vantage provider and scored by
nothing. The engine was structurally incapable of agreeing with a momentum
market — correctly or otherwise.

Deliberately return-based, not indicator-based
──────────────────────────────────────────────
MACD and the MA cross are already read by `trend_confirmation`, inside both the
technical score and the setup scan's ENTRY badge. Reading them a third time here
would not add a factor, it would re-weight one that already exists. Every
component below is a *return* or a *price position*, which is information the
composite has never carried in any form.

Relative, not absolute — every component, without exception
───────────────────────────────────────────────────────────
All three components are measured **against the benchmark**, and when the
benchmark is unavailable the factor returns a flat 0.5 at zero coverage rather
than falling back to raw readings. This is the `_macro_score` lesson applied
before it can be repeated: in a rising market every absolute return is
positive, so an absolute momentum factor would move the whole book in one
direction and rank nothing — a market-timing overlay wearing a stock-picking
label. Excess return over the benchmark is the same reading with the common
mode removed, which is the part that discriminates.

The range component had to be *made* relative, and the correction is worth
recording. It was written as a plain 52-week range position on the argument
that a stock's own range has no common mode to remove. That is false, and a
deterministic test said so immediately: on monotone paths every advancing name
scored 1.000, so a stock merely matching the index scored 0.625 overall instead
of 0.500. In a bull market almost everything sits near its high — that *is* a
common mode, and it is the same one twice, since a market near its high is why
its constituents are. Measuring the gap between the stock's range position and
the benchmark's removes it.

It cancels against mean-reversion, and that is the point
────────────────────────────────────────────────────────
This factor scores high where `_technical_score` scores low. Under an additive
composite the two partially cancel — which is the exact failure the technical
score's own docstring records, where a 60/40 oscillator/trend blend separated a
dip from a knife by 0.045.

The difference is that the cancellation is no longer hidden inside one number at
a fixed ratio. These are two named factors with two weights, two `breakdown`
rows and two sliders; a desk that wants a dip-buyer sets `weight_momentum` to 0,
one that wants trend-following sets `weight_technical` to 0, and one that wants
both chooses the ratio and can see what it chose. An invisible 60/40 was never a
decision anybody made.

Ships at weight 0.00
────────────────────
Like `weight_volatility`, and for the reason `RESEARCH_VETO_ENABLED` and
`TRAILING_STOP_ENABLED` ship off: this changes which names an agent with real
money buys, and nothing has yet measured whether it ranks outcomes better. The
score is computed and stored on every cycle regardless, so
`/performance/calibration` can settle roughly twenty trading days of history
under it before anyone argues from it. `config.Settings` includes it in the
sum-to-1.0 check, so raising it forces an explicit rebalance rather than
silently inflating every score by its weight.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Trading-day lookbacks. 63 ≈ 3 months, 126 ≈ 6 months, 21 ≈ 1 month.
_SHORT_LOOKBACK = 63
_LONG_LOOKBACK = 126

#: The long horizon skips the most recent month. This is the standard 12-1
#: construction, narrowed to 6-1 by the history actually available: the last
#: few weeks of a run carry short-term *reversal*, not continuation, so
#: including them measures the one part of the window that tends to work
#: against the signal. Skipping it also stops this factor and the oscillators
#: in `_technical_score` reading the same days in opposite directions.
_SKIP_RECENT = 21

#: Range position needs a window long enough to have a meaningful high and low.
#: A "52-week" position computed over six weeks is a restatement of the
#: Bollinger reading `_technical_score` already has.
_RANGE_MIN_BARS = 120
_RANGE_LOOKBACK = 252

#: Band for the range-position *gap* against the benchmark. A stock sitting 35
#: points of its own range above where the index sits in its own is decisively
#: leading; the same distance below is decisively lagging. Narrower than the
#: return bands because range position is bounded 0–1 to begin with, so the
#: achievable gaps are smaller.
_RANGE_BAND = 0.35

#: Excess-return bands, chosen to *grade* rather than saturate — the mistake
#: `_macro_score` had to be widened to fix, where VIX 14, a +0.8 curve and 2.3%
#: CPI each hit their ceiling in a perfectly ordinary market and the component
#: stopped telling "fine" from "exceptional".
#:
#: Three-month excess return against SPY has a cross-sectional standard
#: deviation around 12–15% for large-cap equities, so ±25% is roughly ±1.7σ:
#: a genuinely exceptional quarter reaches the ceiling and an ordinary one
#: lands mid-range, which is where a ranking factor earns its weight.
_SHORT_BAND = 0.25
_LONG_BAND = 0.40

#: Component weights within the factor.
_W_SHORT = 0.40      # 3-month relative strength
_W_LONG = 0.35       # 6-month relative strength, most recent month skipped
_W_RANGE = 0.25      # position within the trailing range


def _normalise_index(series: pd.Series) -> pd.Series:
    """
    Strip time and timezone so two series fetched from different providers can
    be aligned on the calendar date. yfinance hands back tz-aware midnight
    stamps for daily bars and tz-naive ones for some tickers; an unnormalised
    join silently produces an all-NaN reindex rather than an error.
    """
    idx = pd.to_datetime(series.index)
    try:
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(None)
    except (TypeError, AttributeError):
        pass
    return pd.Series(series.to_numpy(dtype=float), index=idx.normalize()).sort_index()


def _pct_change(series: pd.Series, lookback: int, skip: int = 0) -> Optional[float]:
    """
    Fractional return from `lookback + skip` bars ago to `skip` bars ago.

    Returns None rather than a partial reading when the series is too short.
    A momentum score computed over whatever history happened to be present
    would mean something different for every ticker, which is the failure
    coverage weighting exists to make visible elsewhere.
    """
    needed = lookback + skip + 1
    if len(series) < needed:
        return None
    end = series.iloc[-(skip + 1)]
    start = series.iloc[-(lookback + skip + 1)]
    if start is None or start <= 0 or pd.isna(start) or pd.isna(end):
        return None
    return float(end) / float(start) - 1.0


def _excess(
    closes: pd.Series,
    bench: Optional[pd.Series],
    lookback: int,
    skip: int,
    band: float,
) -> Optional[float]:
    """
    One relative-strength component, scaled to 0–1 by `band`.

    None when either leg is unavailable. The benchmark leg is **not** optional
    and does not degrade to the raw return — see the module docstring; an
    absolute return in a rising market ranks nothing.
    """
    if bench is None:
        return None
    mine = _pct_change(closes, lookback, skip)
    theirs = _pct_change(bench, lookback, skip)
    if mine is None or theirs is None:
        return None
    return clamp((mine - theirs + band) / (2.0 * band))


def _raw_range_position(closes: pd.Series) -> Optional[float]:
    """
    Where the last close sits between the trailing low and high, 0–1.

    Distance from the 52-week high is one of the few momentum measures with an
    independent evidence base, and it is not a restatement of trailing return:
    a name can be up strongly over the window and still well off its high, and
    the two readings disagree exactly when a run has rolled over.
    """
    if len(closes) < _RANGE_MIN_BARS:
        return None
    window = closes.iloc[-_RANGE_LOOKBACK:]
    low = float(window.min())
    high = float(window.max())
    if not (high > low):
        return None
    return clamp((float(window.iloc[-1]) - low) / (high - low))


def _relative_range(closes: pd.Series, bench: Optional[pd.Series]) -> Optional[float]:
    """
    How much nearer its own high this stock sits than the benchmark sits to
    its own, scaled to 0–1. 0.5 means both are equally extended.

    Both legs are measured over the same number of bars, taken from whichever
    series is shorter — otherwise a ticker with less history is compared
    against a benchmark range that covers a longer and usually more favourable
    period, and the gap reports the calendar rather than the stock.
    """
    if bench is None or bench.empty:
        return None
    n = min(len(closes), len(bench))
    if n < _RANGE_MIN_BARS:
        return None
    mine = _raw_range_position(closes.iloc[-n:])
    theirs = _raw_range_position(bench.iloc[-n:])
    if mine is None or theirs is None:
        return None
    return clamp((mine - theirs + _RANGE_BAND) / (2.0 * _RANGE_BAND))


def compute_momentum(
    closes: pd.Series,
    benchmark_closes: Optional[pd.Series] = None,
) -> tuple[float, float, dict]:
    """
    Score sustained relative strength in [0, 1]. Higher = stronger.

    Returns `(score, coverage, diagnostics)`.

    Coverage weighting follows `_fundamental_score` exactly: the unmeasured
    share is pulled to 0.5 rather than re-normalised over what is present, so a
    ticker with only one component available lands near neutral instead of
    inheriting that component's conviction whole. Returns `(0.5, 0.0, ...)` when
    nothing is computable — including whenever the benchmark is missing, since
    every component depends on it. Never a 0.0, which would read as *weak*
    rather than as *unknown* and would be the one direction of error that makes
    this factor argue against every name it cannot measure.

    `diagnostics` carries the raw components alongside the score, for the same
    reason `setup_trigger` is stored beside the five indicators behind it: the
    bands here are tunable, so a replay that recomputed the score from a later
    set of constants would describe a rule that never ran, while the raw
    excess returns are what a *different* rule can be tested against.
    """
    closes = _normalise_index(closes)
    bench = _normalise_index(benchmark_closes) if benchmark_closes is not None else None
    if bench is not None:
        # Align the benchmark onto this ticker's own trading calendar. Forward
        # fill covers a date the ticker traded and the index did not (a rare
        # provider gap); an unalignable benchmark yields NaNs, which
        # `_pct_change` reports as None rather than scoring.
        bench = bench.reindex(closes.index, method="ffill").dropna()

    components: list[tuple[float, float]] = []

    short = _excess(closes, bench, _SHORT_LOOKBACK, 0, _SHORT_BAND)
    if short is not None:
        components.append((short, _W_SHORT))

    long_ = _excess(closes, bench, _LONG_LOOKBACK, _SKIP_RECENT, _LONG_BAND)
    if long_ is not None:
        components.append((long_, _W_LONG))

    rng = _relative_range(closes, bench)
    if rng is not None:
        components.append((rng, _W_RANGE))

    diagnostics = {
        "rs_3m": round(short, 4) if short is not None else None,
        "rs_6m_skip_1m": round(long_, 4) if long_ is not None else None,
        "range_position": round(rng, 4) if rng is not None else None,
        "range_position_raw": (
            round(_raw_range_position(closes), 4)
            if _raw_range_position(closes) is not None else None
        ),
        "excess_return_3m": _pct_change(closes, _SHORT_LOOKBACK, 0),
        "benchmark_available": bench is not None and not bench.empty,
        "bars_available": int(len(closes)),
    }
    if bench is not None and not bench.empty:
        mine = _pct_change(closes, _SHORT_LOOKBACK, 0)
        theirs = _pct_change(bench, _SHORT_LOOKBACK, 0)
        if mine is not None and theirs is not None:
            diagnostics["excess_return_3m"] = round(mine - theirs, 4)

    if not components:
        return 0.5, 0.0, diagnostics

    coverage = sum(w for _, w in components)
    raw = sum(s * w for s, w in components) / coverage
    score = clamp(raw * coverage + 0.5 * (1.0 - coverage))
    return score, coverage, diagnostics
