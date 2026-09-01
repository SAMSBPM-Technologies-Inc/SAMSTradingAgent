"""
Timing-setup classification — is this ticker at a dip-buy entry, extended into
profit-taking territory, or neither?

This used to live inline in the /signals/dip-buy route that backed the Alpha
Radar page. Alpha Radar and the watchlist were never two sets of tickers: both
read the same `watchlists` collection, one joining stocks_signals for the
verdict and the other joining stocks_features for the timing. Now that the two
views are merged into a single page, the thresholds live here so /watchlist and
the deprecated /signals/dip-buy cannot drift apart.

Thresholds encode the mean-reversion stance declared in config.technical_stance.
Under a momentum stance the entry/exit sense would need to invert, which is why
they are named for the strategy rather than the indicator.

`trend_confirmation` lives here and is imported by `feature_engineering`, not
the other way round. The badge this module draws and the score that module
computes must answer "is this a dip or a falling knife" the same way; they did
not, for as long as both existed, because the gate was written into the score
alone. One definition, in the module with no dependencies.
"""
from datetime import datetime, timezone
from typing import Any, Optional

# ── Entry thresholds (dip-buy strategy) ───────────────────────────────────────
ENTRY_RSI_MAX   = 45.0   # RSI not yet overbought
ENTRY_STOCH_MAX = 0.20   # oversold on Stochastic RSI
ENTRY_BB_MAX    = 0.35   # near or below lower Bollinger Band
ENTRY_TREND_MIN = 0.5    # at least one of MACD / the MA cross still bullish

# ── Exit-alert thresholds ─────────────────────────────────────────────────────
EXIT_RSI_MIN    = 70.0   # overbought
EXIT_BB_MIN     = 0.90   # near upper Bollinger Band

#: Projection needed from stocks_features to classify a ticker.
FEATURE_PROJECTION = {
    "ticker": 1, "current_price": 1, "computed_at": 1,
    "rsi_14": 1, "stoch_rsi": 1, "bb_pct": 1,
    "macd_bullish": 1, "ma_cross_bullish": 1,
    "ma_20": 1, "volume_anomaly": 1, "technical_score": 1,
}


def trend_confirmation(
    macd_bullish: Optional[bool],
    ma_cross_bullish: Optional[bool],
) -> Optional[float]:
    """
    0–1 reading of whether price structure supports the oscillators.

    Returns None when neither input is available, so a caller can tell "the
    trend is broken" from "the trend is unknown". Those are different facts and
    the safe reading of each points the opposite way, so they must never be
    collapsed into a single number.

    This lives here rather than in `feature_engineering`, which is its other
    consumer, for one reason: the two must read trend the same way. It existed
    only inside `_technical_score`, and this module — the one that draws the
    badge — never got it, so for as long as both existed the score and the
    badge disagreed about what a dip is. This module has no dependencies and
    can be imported from anywhere; the scoring module cannot.
    """
    parts = [1.0 if v else 0.0 for v in (macd_bullish, ma_cross_bullish) if v is not None]
    return sum(parts) / len(parts) if parts else None


def classify_trigger(
    rsi: Optional[float],
    stoch: Optional[float],
    bb: Optional[float],
    macd_bullish: Optional[bool] = None,
    ma_cross_bullish: Optional[bool] = None,
) -> str:
    """
    Entry     — rsi ≤ 45 AND stoch ≤ 0.20 AND bb ≤ 0.35, AND at least one of
                MACD / the MA cross still bullish (all four must hold)
    Exit      — rsi ≥ 70 OR bb ≥ 0.90 (either fires)
    Neutral   — has data, meets neither

    A missing indicator can never satisfy a condition, so a partially-computed
    feature document degrades to NEUTRAL rather than firing a false entry.

    **Oversold is a reason to buy only when the trend is still intact.** Without
    the trend condition the three oscillators cannot tell a pullback from a
    stock in free fall — both read deeply oversold, and only the first is worth
    buying. `_technical_score` was rewritten to gate on exactly this and scores
    the two 0.388 against 0.907; this scan kept the ungated rule and printed the
    same green ENTRY badge on both, at the top of the watchlist, where it is the
    most prominent thing on the page.

    The bar is one confirmation rather than two because that is where the
    engine's own reading puts it: one bullish leg scores 0.662, neither scores
    0.388. A discounted signal still ranks; an unconfirmed one does not prompt.

    Missing trend inputs give NEUTRAL, which is the opposite of what
    `_technical_score` does with them — it falls back to the additive blend.
    The two differ because a score must return a number for every ticker and
    gating against an invented neutral would scale every score down, whereas a
    badge has a third answer that costs nothing. Fail closed on the side that
    prompts a purchase.

    The exit side is deliberately NOT trend-gated. It is advisory, and a trend
    condition there would suppress warnings rather than prompts — the same
    asymmetry as everywhere else here: never put a brake on the exit path.
    """
    trend = trend_confirmation(macd_bullish, ma_cross_bullish)
    is_entry = (
        (rsi is not None and rsi <= ENTRY_RSI_MAX)
        and (stoch is not None and stoch <= ENTRY_STOCH_MAX)
        and (bb is not None and bb <= ENTRY_BB_MAX)
        and (trend is not None and trend >= ENTRY_TREND_MIN)
    )
    if is_entry:
        return "ENTRY"

    is_exit = (
        (rsi is not None and rsi >= EXIT_RSI_MIN)
        or (bb is not None and bb >= EXIT_BB_MIN)
    )
    if is_exit:
        return "EXIT_ALERT"

    return "NEUTRAL"


def setup_from_feature_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce a stocks_features document to the timing fields the watchlist row
    carries, plus its trigger. Returns kwargs ready to splat onto WatchlistItem.
    """
    rsi   = doc.get("rsi_14")
    stoch = doc.get("stoch_rsi")
    bb    = doc.get("bb_pct")
    ma20  = doc.get("ma_20")
    price = doc.get("current_price") or 0.0

    computed = doc.get("computed_at") or datetime.now(tz=timezone.utc)
    if isinstance(computed, datetime) and computed.tzinfo is None:
        computed = computed.replace(tzinfo=timezone.utc)

    return {
        "trigger": classify_trigger(
            rsi, stoch, bb,
            doc.get("macd_bullish"), doc.get("ma_cross_bullish"),
        ),
        "rsi_14": rsi,
        "stoch_rsi": stoch,
        "bb_pct": bb,
        "ma_20": ma20,
        "volume_anomaly": doc.get("volume_anomaly"),
        "pct_from_ma20": round((price - ma20) / ma20 * 100, 2) if ma20 else None,
        "computed_at": computed,
    }


#: Order the merged watchlist surfaces triggers in — actionable setups first,
#: then things that merely have data, then things still being computed.
TRIGGER_RANK = {"ENTRY": 3, "EXIT_ALERT": 2, "NEUTRAL": 1, "PENDING": 0}
