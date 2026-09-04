"""
Signal Generator
────────────────
Applies rule-based logic on top of composite score + risk assessment
to produce a BUY / SELL / HOLD signal with confidence and entry/exit hints.

Rules:
  BUY  → score > 0.70  AND  risk_score < 6
  SELL → score < 0.30
  HOLD → everything else

Confidence = distance of the score from the nearest decision boundary,
scaled to [0, 1].
"""
from datetime import datetime, timezone

from app.db import COLL_FEATURES, COLL_SIGNALS, get_db
from app.services.cross_section import cohort_for
from app.services.risk_engine import RISK_MAX_FOR_BUY, assess_risk
from app.utils.helpers import clamp, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Canonical signal thresholds. `scoring.compute_personalized_score` imports
#: these rather than restating them: it used to hold its own copies, so tuning
#: one place left any user with custom weights on a different model from the
#: stored signal, silently. RISK_MAX_FOR_BUY comes from risk_engine, which owns
#: the risk scale it belongs to.
BUY_THRESHOLD = 0.70
SELL_THRESHOLD = 0.30

#: How far back through a threshold the score must travel before an established
#: verdict is given up. A score does not sit still: it is recomputed every
#: ingestion cycle from live prices, so one hovering within a rounding error of
#: 0.70 crosses back and forth all session, and a bare comparison turns that
#: noise into a stream of contradictory verdicts. Entering BUY still requires
#: clearing 0.70; leaving it requires falling under 0.67. The band is one-sided
#: on purpose — it makes an existing verdict sticky, never easier to acquire.
SIGNAL_HYSTERESIS = 0.03

# ── Relative thresholds ───────────────────────────────────────────────────────
#
# The rule applied when a `Cohort` is supplied — see `services/cross_section.py`
# for why an absolute cutoff selects badly on this score's distribution. These
# live here, beside the absolute thresholds, because this module owns the rule
# and everything else imports it rather than restating it. Config carries only
# the on/off switch.

#: Rank a BUY needs: the top fifth of the field. Not a decile, because the
#: watchlist is around a dozen names and a decile of twelve is one ticker —
#: which makes the verdict a function of one peer's data outage.
RANK_BUY_PERCENTILE = 0.80
#: Rank a SELL needs: the bottom fifth, symmetrically.
RANK_SELL_PERCENTILE = 0.20

#: The absolute level a BUY needs *as well as* the rank. Somebody is always in
#: the top fifth, so without this the rule buys the least-bad name in a
#: uniformly bad field every single day. Set just under the typical composite
#: (~0.567): "the best of these, and not itself below average".
RANK_BUY_FLOOR = 0.55
#: The absolute level a SELL needs as well as the rank, for the same reason
#: inverted — the worst name in a strong field is not a sell.
RANK_SELL_CEILING = 0.50

#: How far the rank may slip before an established verdict is given up, in
#: percentile points. Same one-sided stickiness as `SIGNAL_HYSTERESIS`, applied
#: to the rank rather than the score, because under this rule the rank is what
#: moves — a ticker can hold its score exactly and change quintile because a
#: peer reported earnings.
RANK_HYSTERESIS = 0.10

#: Smallest field worth ranking in. Below this a percentile is mostly noise
#: about which peers happened to ingest: at four tickers each rank step is 33
#: percentile points, so one failed fetch moves a name two quintiles. Under it
#: the absolute rule applies, which is the stricter of the two.
RANK_MIN_COHORT = 5

__all__ = ["BUY_THRESHOLD", "SELL_THRESHOLD", "SIGNAL_HYSTERESIS",
           "RANK_BUY_PERCENTILE", "RANK_SELL_PERCENTILE", "RANK_BUY_FLOOR",
           "RANK_SELL_CEILING", "RANK_HYSTERESIS", "RANK_MIN_COHORT",
           "RISK_MAX_FOR_BUY", "generate_signal", "generate_signals_all",
           "classify_signal", "boundary_confidence"]


def classify_signal(
    score: float,
    risk_score: float,
    previous_signal: str | None = None,
    cohort=None,
    exit_score: float | None = None,
) -> str:
    """
    The BUY / SELL / HOLD rule, in one place.

    BUY is the only verdict gated on risk. That asymmetry is deliberate: the
    gate answers "is it safe to take on this exposure", which has no bearing on
    whether to leave one you already hold. Refusing to exit a position because
    conditions are dangerous would be exactly backwards.

    `previous_signal` engages the hysteresis band: a verdict already in force is
    held until the score retreats `SIGNAL_HYSTERESIS` past the threshold that
    produced it. Omit it (the default) to get the raw rule — that is what
    calibration and threshold sweeps want, since a replay has no "previous".

    `cohort` (a `cross_section.Cohort`) switches on the **relative** rule: the
    score must be in the top or bottom quintile of the watchlist *and* clear an
    absolute floor. Omit it — as calibration replays and
    `compute_personalized_score` do — and the absolute rule applies unchanged.
    That fallback direction matters: the absolute rule is the harder bar, so
    every path that cannot supply a cohort ends up stricter rather than looser.

    Only the *entry* conditions differ between the two rules. Risk still vetoes
    only BUY, SELL is still ungated, and the band is still one-sided. Nothing
    below makes an exit harder than it was.

    `exit_score` (`scoring.exit_score`) is the number the **SELL** test reads.
    The BUY test always reads `score`. The two answer different questions and
    the composite only ever answered the first: `_technical_score` floors an
    extended name near zero because an oversold oscillator is the *entry* timer,
    so a leader running away from its cost basis walked the composite down into
    SELL for a reason that said nothing about the company. Measured on the real
    functions, the composite had the two cases backwards — an extended leader
    scored 0.297 and a name with a broken trend, negative relative strength and
    weak fundamentals scored 0.340.

    Because they are two numbers, the exit clause is tested first — see the
    comment at the branch. This is not a brake. It changes which number the exit
    is measured against,
    upstream of the verdict; it adds no veto, no delay and no gate. A
    deteriorating name still sells immediately and unconditionally. Omit it and
    the SELL test falls back to `score`, which is the rule exactly as it was —
    the same convention `cohort` and `previous_signal` follow, and what
    calibration replays want.
    """
    sell_basis = score if exit_score is None else exit_score

    if cohort is not None and cohort.size >= RANK_MIN_COHORT:
        return _classify_relative(
            score, risk_score, previous_signal, cohort, sell_basis,
        )

    buy_exit = BUY_THRESHOLD - SIGNAL_HYSTERESIS if previous_signal == "BUY" else BUY_THRESHOLD
    sell_exit = SELL_THRESHOLD + SIGNAL_HYSTERESIS if previous_signal == "SELL" else SELL_THRESHOLD

    # The exit is tested FIRST, and it outranks the entry clause. While both
    # sides read one number this was unobservable — nothing can be above 0.70
    # and below 0.30 at once — but they are two numbers now, and the order is
    # the same asymmetry as everywhere else here: `_classify_relative` tests
    # the absolute exit before the rank, and `_gate_analyst_signal` tests the
    # exit clause before the BUY clause. When the exit reading says leave and
    # the composite says enter, leaving wins.
    if sell_basis < sell_exit:
        return "SELL"
    if score > buy_exit and risk_score < RISK_MAX_FOR_BUY:
        return "BUY"
    return "HOLD"


def _classify_relative(
    score: float, risk_score: float, previous_signal: str | None, cohort,
    sell_basis: float | None = None,
) -> str:
    """
    The rank-based rule. Reached only from `classify_signal`, never directly.

    **The relative rule replaces the BUY test and only ever adds to the SELL
    one.** That asymmetry is not a detail; it is the same rule that exempts
    SELL from the risk gate, from confirmations and dwell, and from both vetoes.

    Reshaping entries is the entire point of ranking, so an absolute BUY that
    is only mid-field no longer buys. Reshaping *exits* the same way would be a
    brake on the exit path: a name at 0.20 sitting in a field of even worse
    names is not in the bottom quintile, and a pure rank rule would hold it —
    turning "everything I watch is falling" into a reason to sell nothing. So
    the absolute exit is tested first and is never withdrawn; the rank can only
    trigger an exit the absolute rule would have missed.

      SELL → score < SELL_THRESHOLD (the absolute exit, unchanged)
              OR (bottom quintile of the field AND score <= RANK_SELL_CEILING)
      BUY  → top quintile of the field, AND score >= RANK_BUY_FLOOR,
              AND risk < RISK_MAX_FOR_BUY

    The rank is banded by `RANK_HYSTERESIS` for a standing verdict; **the floor
    is not**. Relaxing the rank keeps a name that is still one of the better
    things on the list from being dropped over a peer's one-cycle wobble, which
    is noise about the field. Relaxing the floor would keep holding something
    whose own score had fallen through the level at which it stopped being
    worth owning, which is information about the name. The band exists to
    ignore the first kind of movement, not the second.
    """
    sell_exit = (
        SELL_THRESHOLD + SIGNAL_HYSTERESIS if previous_signal == "SELL"
        else SELL_THRESHOLD
    )
    # The exit reading, where one was supplied; the composite otherwise. Both
    # absolute exits below use it, and the rank still ranks on `score`, which is
    # what the cohort's percentile was computed from — mixing the two would
    # compare a name's exit reading against its peers' entry readings.
    sell_basis = score if sell_basis is None else sell_basis
    # First, and unconditionally: whatever the field is doing, a score under
    # the absolute sell threshold is an exit. Ranking may add exits; it may
    # never take one away.
    if sell_basis < sell_exit:
        return "SELL"

    buy_rank = (
        RANK_BUY_PERCENTILE - RANK_HYSTERESIS if previous_signal == "BUY"
        else RANK_BUY_PERCENTILE
    )
    sell_rank = (
        RANK_SELL_PERCENTILE + RANK_HYSTERESIS if previous_signal == "SELL"
        else RANK_SELL_PERCENTILE
    )

    if (
        cohort.percentile >= buy_rank
        and score >= RANK_BUY_FLOOR
        and risk_score < RISK_MAX_FOR_BUY
    ):
        return "BUY"
    if cohort.percentile <= sell_rank and sell_basis <= RANK_SELL_CEILING:
        return "SELL"
    return "HOLD"


def boundary_confidence(score: float, signal: str, cohort=None) -> float:
    """
    How far *score* sits from the nearest boundary that would change *signal*,
    scaled to [0, 1].

    This is DISTANCE FROM THE DECISION BOUNDARY, not a probability. It says how
    far from flipping the verdict is, which is not the same as how often
    verdicts at this level have been right — nothing has ever compared it
    against `stocks_signal_history`. Read it as conviction in the arithmetic,
    not as a hit rate.

    Extracted so the analyst path can use it. When the analyst's BUY is
    refused by the gate, the verdict that gets published is the rule's, and a
    confidence derived from the model's conviction would describe a verdict
    nobody published — "85% confident HOLD" for a model that wanted to buy.

    `cohort` must be the same one the verdict was classified with, and for the
    same reason: under the relative rule the boundary that decides the verdict
    is a *rank*, and measuring distance from `BUY_THRESHOLD` would report a BUY
    at 0.60 as 0% confident. Measuring the wrong boundary is the identical
    mistake the analyst clause above exists to prevent.
    """
    if cohort is not None and cohort.size >= RANK_MIN_COHORT:
        return _relative_confidence(score, signal, cohort)

    if signal == "BUY":
        return clamp((score - BUY_THRESHOLD) / (1.0 - BUY_THRESHOLD))
    if signal == "SELL":
        return clamp((SELL_THRESHOLD - score) / SELL_THRESHOLD)
    # Certainty of being in the middle band.
    return clamp(
        min(abs(score - BUY_THRESHOLD), abs(score - SELL_THRESHOLD)) / 0.40
    )


def _relative_confidence(score: float, signal: str, cohort) -> float:
    """
    Distance from the rank boundary, for a verdict decided on rank.

    A BUY is measured on how far into the top quintile it sits; a SELL on how
    far into the bottom. Both are the rank distance alone: the floor is a
    yes/no admission test rather than a scale, and folding "how far above 0.55"
    into a conviction figure would import the very compression the relative
    rule exists to get out from under.

    HOLD reports distance from whichever entry boundary is nearer, normalised
    over the widest gap either side, so the number keeps its meaning — "how
    settled is this verdict" — across both rules.
    """
    if signal == "BUY":
        headroom = 1.0 - RANK_BUY_PERCENTILE
        return clamp((cohort.percentile - RANK_BUY_PERCENTILE) / headroom) if headroom else 1.0
    if signal == "SELL":
        headroom = RANK_SELL_PERCENTILE
        return clamp((RANK_SELL_PERCENTILE - cohort.percentile) / headroom) if headroom else 1.0
    nearest = min(
        abs(cohort.percentile - RANK_BUY_PERCENTILE),
        abs(cohort.percentile - RANK_SELL_PERCENTILE),
    )
    span = max(
        RANK_BUY_PERCENTILE - RANK_SELL_PERCENTILE,
        1e-9,
    ) / 2.0
    return clamp(nearest / span)


async def generate_signal(ticker: str, previous_signal: str | None = None) -> dict:
    """
    Load feature doc → assess risk → apply signal rules → persist + return signal dict.
    """
    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    if feat is None:
        raise ValueError(f"No features found for {ticker}. Run the pipeline first.")

    score: float = feat.get("composite_score", 0.5)
    risk_dict = assess_risk(feat)
    risk_score: float = risk_dict["risk_score"]

    # Where this score sits in the watchlist it was scored alongside. None
    # whenever ranking is switched off or the field cannot be read, in which
    # case every call below falls back to the absolute rule — see
    # `services/cross_section.py`.
    cohort = await cohort_for(ticker, score)

    # Imported here rather than at module scope: `scoring` imports
    # `classify_signal` back out of this module, and the cycle is broken the
    # same way `compute_personalized_score` breaks it.
    from app.services.scoring import exit_score

    # The number the SELL test reads. The composite ranks entry opportunity, and
    # its low end was being read as "this is bad to own" — see
    # `scoring.exit_score`. The BUY test is untouched and still reads `score`.
    exit_reading = exit_score(feat)

    # ── Signal decision ───────────────────────────────────────────────────────
    signal = classify_signal(
        score, risk_score, previous_signal, cohort, exit_score=exit_reading,
    )

    confidence = boundary_confidence(score, signal, cohort)

    # ── Entry / exit suggestions ──────────────────────────────────────────────
    price = feat.get("current_price", 0.0)
    entry_suggestion, exit_suggestion = _price_suggestions(signal, price, feat)

    # ── Explanation ───────────────────────────────────────────────────────────
    explanation = _build_explanation(ticker, signal, score, risk_dict, feat, cohort)

    signal_doc = {
        "ticker": ticker,
        "generated_at": utcnow(),
        "score": round(score, 4),
        # The exit reading behind the SELL test, stored rather than recomputed
        # so a replay judges the verdict by the number that produced it — the
        # `score_percentile` rule. Absent, never null, on a document written
        # before 1.31.0: absent means "this row predates the exit reading and
        # says nothing about it", which is not the same fact as a row where it
        # was computed and agreed. Same distinction as `analyst_override`.
        "exit_score": round(exit_reading, 4),
        "risk": risk_dict,
        "signal": signal,
        "confidence": round(confidence, 4),
        "entry_suggestion": entry_suggestion,
        "exit_suggestion": exit_suggestion,
        "explanation": explanation,
        # The rank this verdict was decided on, and the field it was measured
        # in. Stored rather than recomputed at read time for the same reason
        # `inputs` is: the cohort moves every cycle, so a percentile computed
        # twenty days later during a calibration replay would describe a
        # different watchlist. Absent — not null — on a document written
        # before ranking existed or while it is switched off; a consumer that
        # cannot tell those apart reads "ranked bottom" for every historical
        # row. Same distinction as `analyst_override`.
        **(
            {"score_percentile": cohort.percentile, "cohort_size": cohort.size}
            if cohort is not None else {}
        ),
    }

    # Upsert – keep only the latest signal per ticker
    await db[COLL_SIGNALS].replace_one(
        {"ticker": ticker},
        signal_doc,
        upsert=True,
    )

    logger.info(
        "signal_generated",
        ticker=ticker,
        signal=signal,
        score=score,
        risk=risk_score,
        confidence=round(confidence, 4),
        rule="relative" if cohort is not None else "absolute",
        percentile=cohort.percentile if cohort is not None else None,
        cohort_size=cohort.size if cohort is not None else None,
    )
    return signal_doc


async def generate_signals_all(tickers: list[str]) -> dict[str, str]:
    """Generate signals for multiple tickers; returns ticker → 'ok' | error."""
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await generate_signal(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            logger.warning("signal_failed", ticker=ticker, error=str(exc))
            results[ticker] = str(exc)
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _price_suggestions(signal: str, price: float, feat: dict):
    """Return (entry_suggestion, exit_suggestion) strings."""
    if price <= 0:
        return None, None

    atr_approx = price * (feat.get("volatility_20d") or 0.02) / 16  # rough intraday ATR

    if signal == "BUY":
        entry = f"${price:.2f} (current) or limit near ${price * 0.99:.2f}"
        stop_loss = price - 2 * atr_approx
        take_profit = price + 3 * atr_approx
        exit_s = f"Stop-loss ~${stop_loss:.2f} | Take-profit ~${take_profit:.2f}"
        return entry, exit_s

    if signal == "SELL":
        # SELL means "exit the position", never "open a short". It previously
        # read "Short entry near $X | Cover ~$Y", which contradicted both the
        # account and the code: shorting is not permitted in a TFSA, and
        # trade_manager only ever sells to close what the broker actually holds
        # — it has no path that opens a short.
        limit = price * 1.005
        exit_s = (
            f"Exit at ${price:.2f} (current) or limit near ${limit:.2f}. "
            f"No position — no action; this is not a short signal."
        )
        return None, exit_s

    return None, f"Monitor; consider re-evaluating if price moves ±5% from ${price:.2f}"


def _build_explanation(
    ticker: str, signal: str, score: float, risk: dict, feat: dict, cohort=None
) -> str:
    # Technical
    rsi = feat.get("rsi_14")
    rsi_str = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"
    ma_bull = feat.get("ma_cross_bullish")
    trend = "bullish" if ma_bull else ("bearish" if ma_bull is False else "neutral")
    macd_bull = feat.get("macd_bullish")
    macd_str = "MACD↑" if macd_bull else ("MACD↓" if macd_bull is False else "")
    bb_pct = feat.get("bb_pct")
    bb_str = f"BB={bb_pct:.0%}" if bb_pct is not None else ""

    # Sub-scores
    tech  = feat.get("technical_score",   0.5)
    fund  = feat.get("fundamental_score", 0.5)
    sent  = feat.get("sentiment_score",   0.5)
    macro = feat.get("macro_score",       0.5)

    indicators = " | ".join(filter(None, [rsi_str, macd_str, bb_str, f"MA={trend}"]))
    scores_str = (
        f"tech={tech:.2f} fund={fund:.2f} sent={sent:.2f} macro={macro:.2f}"
    )

    # Under the relative rule the score alone does not explain the verdict —
    # a BUY at 0.60 reads as a mistake until you know it was the best of
    # thirteen. Stated as a position in the field rather than as a percentile,
    # since "top of 13" is what a reader can check and 0.92 is not.
    rank_str = ""
    if cohort is not None:
        place = round((1.0 - cohort.percentile) * (cohort.size - 1)) + 1
        rank_str = f" | rank {place} of {cohort.size} watched"

    return (
        f"{ticker} → {signal} | score={score:.2f}{rank_str} | "
        f"Risk={risk['risk_level']} ({risk['risk_score']:.1f}/10) | "
        f"{indicators} | [{scores_str}]. {risk['explanation']}"
    )
