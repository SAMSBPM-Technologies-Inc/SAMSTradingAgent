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
"""
from datetime import datetime, timezone
from typing import Any, Optional

# ── Entry thresholds (dip-buy strategy) ───────────────────────────────────────
ENTRY_RSI_MAX   = 45.0   # RSI not yet overbought
ENTRY_STOCH_MAX = 0.20   # oversold on Stochastic RSI
ENTRY_BB_MAX    = 0.35   # near or below lower Bollinger Band

# ── Exit-alert thresholds ─────────────────────────────────────────────────────
EXIT_RSI_MIN    = 70.0   # overbought
EXIT_BB_MIN     = 0.90   # near upper Bollinger Band

#: Projection needed from stocks_features to classify a ticker.
FEATURE_PROJECTION = {
    "ticker": 1, "current_price": 1, "computed_at": 1,
    "rsi_14": 1, "stoch_rsi": 1, "bb_pct": 1,
    "ma_20": 1, "volume_anomaly": 1, "technical_score": 1,
}


def classify_trigger(
    rsi: Optional[float],
    stoch: Optional[float],
    bb: Optional[float],
) -> str:
    """
    Entry     — rsi ≤ 45 AND stoch ≤ 0.20 AND bb ≤ 0.35 (all three must hold)
    Exit      — rsi ≥ 70 OR bb ≥ 0.90 (either fires)
    Neutral   — has data, meets neither

    A missing indicator can never satisfy a condition, so a partially-computed
    feature document degrades to NEUTRAL rather than firing a false entry.
    """
    is_entry = (
        (rsi is not None and rsi <= ENTRY_RSI_MAX)
        and (stoch is not None and stoch <= ENTRY_STOCH_MAX)
        and (bb is not None and bb <= ENTRY_BB_MAX)
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
        "trigger": classify_trigger(rsi, stoch, bb),
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
