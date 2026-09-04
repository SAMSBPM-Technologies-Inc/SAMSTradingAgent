"""
AI Scoring Engine
─────────────────
Primary mode  : XGBoost model (ENABLE_ML_MODEL=true + model/xgb_scorer.json present).
Fallback mode : weighted linear scoring (always available).

XGBoost feature vector (14 features — must match training schema in scripts/train_xgb.py):
    rsi_14, macd_bullish, bb_pct, stoch_rsi, ma_cross_bullish,
    volume_anomaly, volatility_20d,
    technical_score, fundamental_score, sentiment_score,
    macro_score, volatility_score, catalyst_score,
    vix (from macro)

Weighted fallback:
    score = base(7 weights, sum=1.0) + weight_alt * (alt_score - 0.5)
"""
import os
from typing import Optional

from app.config import get_settings
from app.db import COLL_FEATURES, get_db
from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Path where a trained XGBoost model is expected (optional)
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "model", "xgb_scorer.json")
_xgb_model = None  # loaded lazily


#: The six base factors plus the additive alternative-data modifier, in the
#: order they are presented. `key` indexes user weight dicts, `feature` indexes
#: the feature document, `label` is what the UI shows.
FACTORS: tuple[tuple[str, str, str], ...] = (
    ("technical",        "technical_score",        "Technical"),
    ("fundamental",      "fundamental_score",      "Fundamental"),
    ("sentiment",        "sentiment_score",        "Sentiment"),
    ("macro",            "macro_score",            "Macro"),
    ("volatility",       "volatility_score",       "Volatility"),
    ("catalyst",         "catalyst_score",         "Catalyst"),
    ("momentum",         "momentum_score",         "Momentum"),
)

ALT_FACTOR = ("alternative_data", "alternative_data_score", "Alternative Data")


def effective_weights(user_weights: dict | None) -> dict[str, float]:
    """
    The weights a score would actually be computed with.

    Single source for the personalised path and the attribution breakdown —
    these used to be separate copies, which is how the UI ended up showing a
    volatility default the engine had abandoned. Fallbacks mirror the Settings
    defaults in config.py, including volatility at 0.0: volatility is priced at
    the risk gate rather than in the score. A user who has explicitly saved a
    volatility weight keeps it; that is their choice, and it reinstates the
    double-count knowingly.
    """
    settings = get_settings()
    defaults = {
        "technical":        settings.weight_technical,
        "fundamental":      settings.weight_fundamental,
        "sentiment":        settings.weight_sentiment,
        "macro":            settings.weight_macro,
        "volatility":       settings.weight_volatility,
        "catalyst":         settings.weight_catalyst,
        "momentum":         settings.weight_momentum,
        "alternative_data": settings.weight_alternative_data,
    }
    if not user_weights:
        return defaults
    return {k: float(user_weights.get(k, v)) for k, v in defaults.items()}


class _WeightView:
    """Adapts a weight dict to the attribute access `_weighted_score` expects."""

    def __init__(self, weights: dict[str, float]) -> None:
        for key, value in weights.items():
            setattr(self, f"weight_{key}", value)


def explain_score(feat: dict, user_weights: dict | None = None) -> dict:
    """
    Where the composite score came from, factor by factor.

    The sub-scores have always been computed and stored, and nothing ever
    returned them: the UI showed a 0–100 number with no attribution while
    offering sliders to reweight it. This is that attribution.

    `attributable` is False on the XGBoost path. The weights genuinely did not
    produce that score — the model did — so presenting a weighted decomposition
    beside it would be a fabrication, and the caller is told to say so instead.
    """
    weights = effective_weights(user_weights)
    method = feat.get("scoring_method") or (
        "xgboost" if get_settings().enable_ml_model else "weighted"
    )

    factors = []
    base_total = 0.0
    for key, feature_key, label in FACTORS:
        # `or 0.5` here would swallow a legitimate 0.0. Under `mean_reversion`
        # that is not a hypothetical: an extended name floors `technical_score`
        # at exactly 0.0 by design, and `_weighted_score` — which has no `or` —
        # would then report a composite 0.20 lower than the breakdown beside it.
        # A missing factor reads neutral; a measured zero reads zero.
        raw = feat.get(feature_key)
        score = 0.5 if raw is None else float(raw)
        weight = float(weights.get(key, 0.0))
        contribution = weight * score
        base_total += contribution
        factors.append({
            "key": key,
            "label": label,
            "score": round(score, 4),
            "weight": round(weight, 4),
            "contribution": round(contribution, 4),
        })

    alt_key, alt_feature, alt_label = ALT_FACTOR
    alt_raw = feat.get(alt_feature)
    alt_score = 0.5 if alt_raw is None else float(alt_raw)
    alt_weight = float(weights.get(alt_key, 0.0))
    # Additive modifier centred on 0.5: it nudges the base rather than being a
    # share of it, so its "contribution" is signed and can drag the score down.
    alt_contribution = alt_weight * (alt_score - 0.5)

    return {
        "method": method,
        "attributable": method != "xgboost",
        "personalized": bool(user_weights),
        "factors": factors,
        "alternative_data": {
            "key": alt_key,
            "label": alt_label,
            "score": round(alt_score, 4),
            "weight": round(alt_weight, 4),
            "contribution": round(alt_contribution, 4),
        },
        "base_total": round(base_total, 4),
        "composite": round(clamp(base_total + alt_contribution), 4),
    }


def compute_personalized_score(
    feat: dict, user_weights: dict | None, previous_signal: str | None = None
) -> tuple[float, str]:
    """
    Apply per-user scoring weights to a feature document and return
    (personalized_score, personalized_signal) without touching the database.

    Signal thresholds: BUY > 0.70 AND risk < 6, SELL < 0.30, else HOLD.
    Risk score is expected in feat["risk"]["score"] if available.

    `previous_signal` is the verdict already published for this ticker. Passing
    it engages the same hysteresis the pipeline uses, so a custom-weighted user
    does not see a verdict re-decided on every page load while the stored one
    holds steady — the two paths must agree about stickiness as well as about
    thresholds.
    """
    if user_weights:
        score = clamp(_weighted_score(feat, _WeightView(effective_weights(user_weights))))
    else:
        settings = get_settings()
        score = clamp(_weighted_score(feat, settings))

    # Imported, not restated. This function used to hold its own copies of the
    # thresholds, so tuning signal_generator left any user with custom weights
    # scored on a different model from the stored signal, with nothing to
    # surface the disagreement.
    from app.services.signal_generator import classify_signal

    risk_score = feat.get("risk", {}).get("score", 5) if isinstance(feat.get("risk"), dict) else 5
    # The exit reading is weighted too, so a user who has reweighted the
    # composite reweights what a SELL means alongside it. Omitting it here would
    # leave the personalised path on the old rule, and the two paths have to
    # agree about exits as well as about thresholds.
    return round(score, 4), classify_signal(
        score, risk_score, previous_signal,
        exit_score=exit_score(feat, user_weights),
    )


async def score_ticker(ticker: str) -> dict:
    """
    Read feature document for *ticker* and produce a composite score.
    Returns the (updated) feature document including composite_score.
    """
    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    if feat is None:
        raise ValueError(f"No features found for {ticker}. Run feature engineering first.")

    settings = get_settings()

    if settings.enable_ml_model:
        # The method is whatever actually ran, not whatever the flag asked for.
        # This used to read `method = "xgboost"` beside the call, which made the
        # feature document claim a model produced a number the weighted path
        # produced — the model file is gitignored and never reaches a deployed
        # box, so on a box with ENABLE_ML_MODEL=true that claim was false every
        # single cycle. `explain_score` reads this field and refuses to
        # decompose an "xgboost" score, so the mislabel silently withheld a
        # factor breakdown that was not merely available but exactly correct.
        composite, method = _ml_score(feat)
    else:
        composite = _weighted_score(feat, settings)
        method = "weighted"

    composite = clamp(composite)

    await db[COLL_FEATURES].update_one(
        {"ticker": ticker},
        {"$set": {"composite_score": round(composite, 4), "scoring_method": method}},
    )

    logger.info("scored", ticker=ticker, composite=composite, method=method)
    feat["composite_score"] = round(composite, 4)
    feat["scoring_method"] = method
    return feat


def _weighted_score(feat: dict, settings) -> float:
    """
    7-weight base score (weights sum to 1.0) plus an alternative-data modifier.
    alt_score=0.5 → no change; >0.5 → boost; <0.5 → drag.
    Max effect: ±weight_alternative_data/2 on the composite.
    """
    base = (
        settings.weight_technical   * feat.get("technical_score",   0.5)
        + settings.weight_fundamental * feat.get("fundamental_score", 0.5)
        + settings.weight_sentiment   * feat.get("sentiment_score",   0.5)
        + settings.weight_macro       * feat.get("macro_score",       0.5)
        + settings.weight_volatility  * feat.get("volatility_score",  0.5)
        + settings.weight_catalyst    * feat.get("catalyst_score",    0.5)
        + settings.weight_momentum    * feat.get("momentum_score",    0.5)
    )
    alt_modifier = settings.weight_alternative_data * (
        feat.get("alternative_data_score", 0.5) - 0.5
    )
    return base + alt_modifier


#: Weighting between the two condition inputs that stand in for the oscillator
#: reading on the exit side. Trend is the faster of the two and relative
#: strength the more durable, so they are close to even with a tilt to trend.
_CONDITION_WEIGHTS = (0.45, 0.55)   # (trend, momentum)


def exit_condition(feat: dict) -> tuple[float, float]:
    """
    How this name is *doing*, as opposed to whether it is a good time to enter.

    Returns `(score, coverage)`. Coverage is the share of the two inputs that
    had data, and it is what tells "the trend is broken" from "the trend is
    unknown" — the distinction `trend_confirmation` exists to preserve.

    Both inputs are already on the feature document, so this costs no read:
    `trend_confirmation` over the stored MACD and MA-cross flags, and
    `momentum_score`, which `services/momentum.py` computes every cycle and
    which is weighted 0.00 in the composite.

    **At zero coverage this returns 0.5, not `technical_score`.** SELL is the
    one verdict with no brakes — no risk gate, no confirmations, no dwell, no
    research veto, no analyst override — so the safe reading of an unknown
    condition is *do not manufacture an exit*. Falling back to the oscillator
    reading would reinstate the exact defect this replaces on precisely the
    documents that carry the least evidence. Same instinct as
    `classify_trigger`'s "missing trend inputs give NEUTRAL": fail closed on the
    side that prompts an order.
    """
    from app.services.setup_scan import trend_confirmation

    w_trend, w_mom = _CONDITION_WEIGHTS
    parts: list[tuple[float, float]] = []

    trend = trend_confirmation(feat.get("macd_bullish"), feat.get("ma_cross_bullish"))
    if trend is not None:
        parts.append((float(trend), w_trend))

    # Coverage, not presence: a momentum score computed with no benchmark is a
    # flat 0.5 at zero coverage and says nothing about the name.
    momentum = feat.get("momentum_score")
    if momentum is not None and float(feat.get("momentum_coverage") or 0.0) > 0:
        parts.append((float(momentum), w_mom))

    if not parts:
        return 0.5, 0.0

    total = sum(w for _, w in parts)
    return clamp(sum(v * w for v, w in parts) / total), total / (w_trend + w_mom)


def exit_score(feat: dict, user_weights: dict | None = None) -> float | None:
    """
    The composite as the *exit* side should read it.

    The composite answers "is this the better opportunity to enter". Its low end
    was being read as "this is bad to own", and under the production stance
    those are not the same question. `_technical_score` floors any extended name
    near zero by design — an oversold oscillator reading is the entry timer —
    so a leader running away from its cost basis walks the composite down toward
    `SELL_THRESHOLD` for a reason that says nothing about the company. AAPL
    published a SELL at `bb_pct` 1.03 / `stoch_rsi` 0.99 with a technical score
    of 0.066, up 24% in six months. That is a correct answer to "is there a dip
    to buy here" and a meaningless one to "should this be sold".

    So the exit reading swaps the oscillator component for a condition
    component — trend and relative strength — and leaves every other factor and
    weight exactly as they are. The number stays on the same 0–1 scale, so
    `SELL_THRESHOLD` keeps its meaning and nothing downstream is rescaled.

    **This is not a brake on the exit path.** It changes what the number means
    upstream of the verdict rather than adding a veto downstream. A name that is
    genuinely deteriorating — broken trend, negative relative strength, weak
    fundamentals, bad news — still scores low here and still sells, immediately
    and unconditionally. What stops is a winner being sold because the dip-buy
    timer says "do not enter here".

    Momentum decides exits; technical decides entries. That gives the factor
    1.30.0 built at weight 0.00 a job without touching `weight_momentum`, and so
    without narrowing the BUY spread that release measured.

    **Returns `None` on the XGBoost path**, where the weights did not produce
    the score and substituting a weighted recomputation would be a different
    number wearing the same name — the same refusal `explain_score` makes when
    it sets `attributable: false`. `classify_signal` then falls back to `score`,
    which is the rule exactly as it was. A fabricated exit reading is worse than
    no exit reading, because this one decides whether to sell.
    """
    if feat.get("scoring_method") == "xgboost":
        return None

    weights = effective_weights(user_weights)
    condition, _coverage = exit_condition(feat)
    view = dict(feat)
    view["technical_score"] = condition
    # Momentum is the condition input now; counting it again under its own
    # weight would double-weight the same reading. It is 0.00 by default, so
    # this matters only on a desk that has raised it.
    view["momentum_score"] = 0.5
    return clamp(_weighted_score(view, _WeightView(weights)))


def _ml_score(feat: dict) -> tuple[float, str]:
    """
    XGBoost inference path. Returns (score, method_that_actually_ran).

    Every failure here falls back to the weighted path and **says so in the
    returned method**. A fallback the caller cannot detect is worse than the
    failure it recovers from: the score is fine either way, but a document
    labelled "xgboost" tells `explain_score` to withhold an attribution that
    would have been true.
    Feature vector must match training schema in scripts/train_xgb.py.

    NOTE: fundamental_score and sentiment_score are frozen at 0.5 to match
    training data (train_xgb.py hardcodes both; historical values unavailable).
    Re-train xgb_scorer.json with real fundamental/sentiment data before unfreezing.

    VIX is read directly from feat["vix"] (stored by feature_engineering.py from
    raw macro data). Previously this defaulted to 20.0 due to a missing propagation.
    """
    global _xgb_model

    if _xgb_model is None:
        if not os.path.exists(_MODEL_PATH):
            # ERROR, not warning: ENABLE_ML_MODEL=true is an explicit statement
            # that the ML path should be running, and it silently is not. The
            # model file is gitignored, so it never reaches a deployed box no
            # matter what the flag says — every production run lands here and
            # scores on the weighted path while the config claims otherwise.
            logger.error(
                "xgb_model_missing_scoring_weighted_instead",
                path=_MODEL_PATH,
                enable_ml_model=True,
                hint="model/*.json is gitignored and never ships; set "
                     "ENABLE_ML_MODEL=false or commit and retrain the model",
            )
            return _weighted_score(feat, get_settings()), "weighted"
        try:
            import xgboost as xgb
            _xgb_model = xgb.XGBRegressor()
            _xgb_model.load_model(_MODEL_PATH)
            logger.info("xgb_model_loaded", path=_MODEL_PATH)
        except Exception as exc:
            logger.error("xgb_model_load_failed", error=str(exc))
            return _weighted_score(feat, get_settings()), "weighted"

    import numpy as np

    # 14-feature vector — must match training schema in scripts/train_xgb.py
    feature_vector = np.array(
        [[
            feat.get("rsi_14",           50.0) or 50.0,
            1.0 if feat.get("macd_bullish") else 0.0,
            feat.get("bb_pct",            0.5) or 0.5,
            feat.get("stoch_rsi",         0.5) or 0.5,
            1.0 if feat.get("ma_cross_bullish") else 0.0,
            feat.get("volume_anomaly",    1.0) or 1.0,
            feat.get("volatility_20d",    0.3) or 0.3,
            feat.get("technical_score",   0.5),
            0.5,  # fundamental_score frozen — matches training; retrain to unlock
            0.5,  # sentiment_score frozen — matches training; retrain to unlock
            feat.get("macro_score",       0.5),
            feat.get("volatility_score",  0.5),
            feat.get("catalyst_score",    0.5),
            float(feat.get("vix") or 20.0),  # read from feat directly (Fix 1)
        ]]
    )
    try:
        prediction = float(_xgb_model.predict(feature_vector)[0])
    except Exception as exc:
        # Inference used to be the one XGBoost path with no handler, so a
        # malformed vector or a schema drift took the whole ticker down for the
        # cycle — no score, no signal, no trade evaluation — when a perfectly
        # good weighted score was one line away. A model that cannot answer is
        # a reason to score without it, not a reason to stop.
        logger.error("xgb_predict_failed_scoring_weighted_instead", error=str(exc))
        return _weighted_score(feat, get_settings()), "weighted"
    return clamp(prediction), "xgboost"
