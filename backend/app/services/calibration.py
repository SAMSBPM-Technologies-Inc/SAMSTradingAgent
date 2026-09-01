"""
Threshold Calibration
─────────────────────
Reads settled signal history and asks the question the engine has never asked
itself: **were the thresholds in the right place?**

Every pipeline run writes to `stocks_signal_history`, and the scheduler settles
each record with `return_20d` about twenty trading days later. Nothing consumed
either. The evidence needed to place BUY_THRESHOLD empirically was being
collected and thrown away, while the threshold stayed where it was originally
guessed.

This module reports; it does not tune. Auto-fitting a threshold to its own
history is how a system talks itself into whatever the last few months
happened to reward, and with a few hundred records the noise is larger than the
signal. The output is evidence for a human decision.

Three questions, each answerable from the same records:

  score_buckets       Does a higher score actually earn a higher return? If the
                      curve is flat, the composite is not ranking anything and
                      no threshold placement will help.
  threshold_sweep     What would BUY at each candidate cutoff have returned?
  confidence_buckets  Does stated confidence track being right? Confidence is
                      computed as distance from the decision boundary and has
                      never been checked against outcomes.

Every result carries `n`. With fewer than ~30 settled records in a bucket the
numbers are anecdote — `MIN_SAMPLES_FOR_SIGNAL` marks that line and the API
surfaces it rather than hiding it behind a confident-looking percentage.
"""
from statistics import median
from typing import Any, Iterable, Optional, Sequence

from app.config import get_settings
from app.db import COLL_DOSSIERS, COLL_SIGNAL_HISTORY, get_db
from app.services.benchmark import benchmark_ticker
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Below this, a bucket's win rate is noise. Not a hard filter — the caller
#: still sees the row, flagged — because "we have no evidence here" is itself
#: worth knowing.
MIN_SAMPLES_FOR_SIGNAL = 30

#: Default score bucket edges. Deliberately spans the whole range rather than
#: clustering near 0.70: if scores never reach the upper buckets, that is the
#: finding.
DEFAULT_SCORE_EDGES: tuple[float, ...] = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0)

#: Candidate BUY cutoffs to sweep. 0.70 is the incumbent.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def _settled(records: Iterable[dict]) -> list[dict]:
    """Records whose 20-day outcome is known. Anything else cannot inform this."""
    return [
        r for r in records
        if isinstance(r.get("return_20d"), (int, float))
        and isinstance(r.get("score"), (int, float))
    ]


def _stats(rows: Sequence[dict]) -> dict[str, Any]:
    """
    Win rate and central tendency for one group, raw and benchmark-relative.

    Both are reported because they answer different questions and can disagree.
    Raw return is what the account did. Alpha is whether the signal earned it,
    or whether holding the index would have. A run of buckets that rises on raw
    return and is flat on alpha is a composite that has learned to pick market
    exposure, which is not what it is for.

    Alpha carries its own `n`. Records settled before benchmark measurement
    existed have no `alpha_20d`, so the two samples are different sizes and
    `alpha_significant` has to be judged separately — reporting one `n` for
    both would let a three-record alpha inherit a three-hundred-record
    confidence.
    """
    returns = [r["return_20d"] for r in rows
               if isinstance(r.get("return_20d"), (int, float))]
    alphas = [r["alpha_20d"] for r in rows
              if isinstance(r.get("alpha_20d"), (int, float))]

    out: dict[str, Any] = {
        "n": len(returns),
        "win_rate": None,
        "avg_return": None,
        "median_return": None,
        "significant": len(returns) >= MIN_SAMPLES_FOR_SIGNAL,
        "alpha_n": len(alphas),
        "alpha_win_rate": None,
        "avg_alpha": None,
        "median_alpha": None,
        "alpha_significant": len(alphas) >= MIN_SAMPLES_FOR_SIGNAL,
    }
    if returns:
        out["win_rate"] = round(sum(1 for r in returns if r > 0) / len(returns), 4)
        out["avg_return"] = round(sum(returns) / len(returns), 6)
        out["median_return"] = round(median(returns), 6)
    else:
        out["significant"] = False
    if alphas:
        out["alpha_win_rate"] = round(sum(1 for a in alphas if a > 0) / len(alphas), 4)
        out["avg_alpha"] = round(sum(alphas) / len(alphas), 6)
        out["median_alpha"] = round(median(alphas), 6)
    else:
        out["alpha_significant"] = False
    return out


def score_buckets(
    records: Iterable[dict],
    edges: Sequence[float] = DEFAULT_SCORE_EDGES,
) -> list[dict]:
    """
    Realised outcome per score band.

    This is the first thing to look at. A composite that ranks well produces
    returns that rise with the bucket; a flat or non-monotonic curve means the
    score is not separating winners from losers, and moving the BUY threshold
    around would only be choosing a different arbitrary point on a flat line.
    """
    rows = _settled(records)
    out: list[dict] = []
    for lo, hi in zip(edges, edges[1:]):
        # Upper edge inclusive only in the final bucket, so 1.0 is not dropped.
        last = hi == edges[-1]
        group = [
            r for r in rows
            if lo <= r["score"] < hi or (last and r["score"] == hi)
        ]
        out.append({"lo": lo, "hi": hi, **_stats(group)})
    return out


def threshold_sweep(
    records: Iterable[dict],
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    risk_max: Optional[float] = None,
) -> list[dict]:
    """
    What a BUY at each candidate cutoff would have returned.

    `risk_max` applies the risk veto as well, but only to records that stored a
    risk score — history did not carry one until this module was written, so
    older rows are score-only and `risk_coverage` reports what fraction of the
    sample the veto could actually be applied to. Reading a sweep with low
    coverage as if it modelled the real gate would overstate it.
    """
    rows = _settled(records)
    with_risk = [r for r in rows if isinstance(r.get("risk_score"), (int, float))]
    coverage = round(len(with_risk) / len(rows), 4) if rows else 0.0

    out: list[dict] = []
    for t in thresholds:
        selected = []
        for r in rows:
            if r["score"] <= t:
                continue
            if risk_max is not None:
                rs = r.get("risk_score")
                if isinstance(rs, (int, float)) and rs >= risk_max:
                    continue
            selected.append(r)
        out.append({
            "threshold": t,
            "risk_filtered": risk_max is not None,
            "risk_coverage": coverage,
            **_stats(selected),
        })
    return out


def confidence_buckets(records: Iterable[dict], bins: int = 5) -> list[dict]:
    """
    Does stated confidence track being right?

    Confidence is distance from the decision boundary, which is not a hit rate
    and has never been compared to one. If win rate does not rise across these
    bands, the number is presentation rather than information — worth knowing
    before it is shown to anyone as though it means something.
    """
    rows = [r for r in _settled(records)
            if isinstance(r.get("confidence"), (int, float))]
    out: list[dict] = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        last = i == bins - 1
        group = [
            r for r in rows
            if lo <= r["confidence"] < hi or (last and r["confidence"] == 1.0)
        ]
        out.append({"lo": round(lo, 4), "hi": round(hi, 4), **_stats(group)})
    return out


def _recorded(rows: Sequence[dict]) -> list[dict]:
    """
    Rows whose analyst gate was actually written down.

    The key being **absent** means the row predates 1.24.0, when the override
    first reached `stocks_signal_history` — it says nothing either way. A
    `None` value means the gate ran and had nothing to override, which is
    evidence. Treating the first as the second is the one mistake that would
    quietly wreck every figure below, by loading the control group with every
    row ever written before the gate existed.
    """
    return [r for r in rows if "analyst_override" in r]


def _short_side(rows: Sequence[dict]) -> list[dict]:
    """
    The same rows with the sign of every outcome flipped.

    A SELL is *right* when the name falls, so `_stats`' `win_rate`
    (`return_20d > 0`) reads exactly backwards on an exit: a group that rose
    four times in five would report an 80% win rate on what was in fact an 80%
    failure. Rather than teach `_stats` a direction — a flag on a shared helper
    that silently mislabels everything that forgets to pass it — the outcomes
    are negated here and the block that uses them is marked
    `direction: "short"`.

    The effect is that **higher is better everywhere**, on both blocks and both
    sides of every comparison, which is the same discipline the six research
    dimensions follow where `risk` means *safer*.
    """
    out = []
    for r in rows:
        flipped = dict(r)
        for key in ("return_20d", "alpha_20d"):
            value = r.get(key)
            # `None` stays `None`. Negating a missing outcome into 0.0 would
            # invent a flat result for a row nothing is known about.
            if isinstance(value, (int, float)):
                flipped[key] = -value
        out.append(flipped)
    return out


def _edge(group: dict, control: dict) -> Optional[float]:
    """
    How much better the overridden group fared than its control, in alpha.

    `None` unless both sides produced a figure — the honest answer far more
    often than not, and never `0.0`, which would read as "no difference
    measured" when the truth is "nothing was measured".
    """
    if group["avg_alpha"] is None or control["avg_alpha"] is None:
        return None
    return round(group["avg_alpha"] - control["avg_alpha"], 6)


def override_counterfactual(records: Iterable[dict]) -> dict:
    """
    Were the analyst gate's refusals worth making?

    The number `_gate_analyst_signal` should be argued from, and the direct
    analogue of `veto_counterfactual` — same shape, same discipline, same
    refusal to tune anything. Until 1.22.0 the analyst's verdict was published
    unchecked; the gate now overrides it in two directions, and neither has ever
    been measured.

    Read each block as a pair, never on its own:

      * **buy_refused** — the analyst wanted to buy and the gate said no. The
        control is the analyst's BUYs that *passed*. The gate earns its place
        only if the refused names went on to do meaningfully **worse**; a
        refused group that performed in line with the allowed one means the
        gate is spending an opportunity on every single refusal.

      * **sell_restored** — the rule wanted out and the analyst wanted to stay,
        and the rule won. The control is the rule's SELLs the analyst agreed
        with. Sign-flipped (see `_short_side`), so a high figure means the name
        fell and leaving was right. A restored group that fared *better* than
        ordinary sells means the analyst was seeing something the score was not,
        and the cost of overruling it is what this measures.

    **`alpha_saved` is the only figure comparable across the two blocks**, and
    on both of them positive means the gate was justified — which is why
    `_edge` is called with its arguments in opposite orders below. Inside a
    block, `overridden` and `control` share an orientation, since that is what
    makes their difference mean anything; across blocks they do not, because on
    the buy side the overridden group is the one the gate made us *skip*. A
    surface showing the raw figures must say which block they belong to.

    **The two are never pooled.** Research calibration offers a pooled row
    because its segments converge slowly and the mixture is still informative.
    These are opposite bets on opposite sides of the book, one of them
    sign-inverted; a pooled figure would not be slow to interpret, it would be
    meaningless.

    Read off what was recorded at the time, never by re-deriving the verdict
    against today's thresholds — that would answer a different question, and one
    nobody asked.
    """
    rows = _recorded(_settled(records))

    refused = [r for r in rows if r.get("analyst_override") == "buy_refused"]
    restored = [r for r in rows if r.get("analyst_override") == "sell_restored"]

    # Controls are the same decision the gate left alone: the analyst asked for
    # this verdict and got it. Rows where the analyst never ran carry a null
    # `analyst_wanted` and belong to neither side — there was no opinion to
    # override, so they are evidence about the score, not about the gate.
    allowed = [r for r in rows
               if r.get("analyst_override") is None and r.get("analyst_wanted") == "BUY"]
    agreed = [r for r in rows
              if r.get("analyst_override") is None and r.get("analyst_wanted") == "SELL"]

    refused_stats, allowed_stats = _stats(refused), _stats(allowed)
    restored_stats = _stats(_short_side(restored))
    agreed_stats = _stats(_short_side(agreed))

    return {
        "recorded_records": len(rows),
        "buy_refused": {
            "direction": "long",
            "control_label": "analyst BUYs the gate allowed",
            "overridden": refused_stats,
            "control": allowed_stats,
            # Positive means the gate refused the worse names, which is the
            # only result that justifies keeping it this strict.
            "alpha_saved": _edge(allowed_stats, refused_stats),
            "conclusive": (refused_stats["alpha_significant"]
                           and allowed_stats["alpha_significant"]),
        },
        "sell_restored": {
            "direction": "short",
            "control_label": "rule SELLs the analyst agreed with",
            "overridden": restored_stats,
            "control": agreed_stats,
            # Positive means the names the gate forced out fell harder than the
            # ones both sides wanted out of — overruling the analyst was, if
            # anything, better than an ordinary exit.
            "alpha_saved": _edge(restored_stats, agreed_stats),
            "conclusive": (restored_stats["alpha_significant"]
                           and agreed_stats["alpha_significant"]),
        },
    }


def summarise(records: Iterable[dict], risk_max: Optional[float] = None) -> dict:
    """Everything above, plus the base rate the buckets should be judged against."""
    rows = _settled(records)
    base = _stats(rows)
    buckets = score_buckets(rows)

    # Does return rise with score? Compared across buckets that actually have
    # enough data to say — a monotonic run of three-sample buckets means nothing.
    usable = [b for b in buckets if b["significant"] and b["avg_return"] is not None]
    monotonic = (
        all(a["avg_return"] <= b["avg_return"] for a, b in zip(usable, usable[1:]))
        if len(usable) >= 2 else None
    )

    # The same question asked of alpha, on its own sample. This is the stricter
    # test and the one that matters: a score can rank raw returns simply by
    # preferring high-beta names in a rising market, and would look calibrated
    # right up to the month the market turns.
    alpha_usable = [
        b for b in buckets if b["alpha_significant"] and b["avg_alpha"] is not None
    ]
    alpha_monotonic = (
        all(a["avg_alpha"] <= b["avg_alpha"]
            for a, b in zip(alpha_usable, alpha_usable[1:]))
        if len(alpha_usable) >= 2 else None
    )

    return {
        "settled_records": len(rows),
        "benchmark_ticker": benchmark_ticker(),
        "alpha_records": sum(
            1 for r in rows if isinstance(r.get("alpha_20d"), (int, float))
        ),
        "base_rate": base,
        "score_buckets": buckets,
        "score_ranks_outcomes": monotonic,
        "score_ranks_alpha": alpha_monotonic,
        "usable_buckets": len(usable),
        "alpha_usable_buckets": len(alpha_usable),
        "threshold_sweep": threshold_sweep(rows, risk_max=risk_max),
        "confidence_buckets": confidence_buckets(rows),
        # Passed the settled list rather than `records`: `records` is typed as
        # an Iterable and `_settled` above has already consumed it if it was a
        # generator, which would silently hand this an empty sample. `_settled`
        # is idempotent, so re-filtering costs a pass and keeps the function
        # usable on its own.
        "analyst_gate": override_counterfactual(rows),
        "min_samples_for_signal": MIN_SAMPLES_FOR_SIGNAL,
    }


async def calibration_report(
    ticker: Optional[str] = None,
    risk_max: Optional[float] = None,
) -> dict:
    """Load settled history from MongoDB and summarise it."""
    db = await get_db()
    query: dict[str, Any] = {"return_20d": {"$ne": None}}
    if ticker:
        query["ticker"] = ticker.upper()

    records = await db[COLL_SIGNAL_HISTORY].find(
        query,
        {"ticker": 1, "score": 1, "signal": 1, "confidence": 1,
         "risk_score": 1, "return_20d": 1, "generated_at": 1,
         "alpha_20d": 1, "benchmark_return_20d": 1,
         # Carried so the analyst-override counterfactual has something to read.
         # This projection is an explicit field list: a field absent from it is
         # dropped silently, which would make a stored override look like a
         # missing one and read as agreement.
         "analyst_used": 1, "analyst_override": 1, "analyst_wanted": 1,
         "rule_signal": 1},
    ).to_list(length=100_000)

    report = summarise(records, risk_max=risk_max)
    report["ticker"] = ticker.upper() if ticker else None
    logger.info(
        "calibration_report",
        ticker=ticker or "ALL",
        settled=report["settled_records"],
        ranks=report["score_ranks_outcomes"],
    )
    return report


# ── The research arm ──────────────────────────────────────────────────────────
# Everything above asks whether the composite score's thresholds sit in the
# right place. This asks the same question of the research module, and it is
# the only thing in either project that can say whether the agent path is worth
# what it costs. The reference implementation this system is measured against
# has no equivalent: it reports backtest figures its own README says are not
# replicable, and never asks whether its debate improved anything.
#
# Same discipline as the rest of the file, and the same refusal. `n` and
# `significant` on every row, and no auto-tuning — `RESEARCH_VETO_MIN_CONVICTION`
# gets moved by a human reading this or it does not get moved.

#: Conviction bands. Spans the full 0-100 range rather than clustering near the
#: veto floor: if research conviction never reaches the upper bands, that is
#: the finding, and a sweep centred on 35 would hide it.
DEFAULT_CONVICTION_EDGES: tuple[float, ...] = (0.0, 20.0, 35.0, 50.0, 65.0, 80.0, 100.0)


def _graded(dossiers: Iterable[dict]) -> list[dict]:
    """Dossiers whose outcome is known. Anything else cannot inform this."""
    out = []
    for doc in dossiers:
        outcome = doc.get("outcome") or {}
        if isinstance(outcome.get("return"), (int, float)):
            out.append({**doc, "_outcome": outcome})
    return out


def _outcome_stats(rows: Sequence[dict]) -> dict[str, Any]:
    """Return and alpha for a group of graded dossiers, on separate counts."""
    return _stats([
        {"return_20d": r["_outcome"].get("return"),
         "alpha_20d": r["_outcome"].get("alpha")}
        for r in rows
    ])


def conviction_buckets(
    dossiers: Iterable[dict],
    edges: Sequence[float] = DEFAULT_CONVICTION_EDGES,
) -> list[dict]:
    """
    Does a higher research conviction earn a higher forward alpha?

    The first thing to look at, and the direct analogue of `score_buckets`. A
    flat curve means research conviction is not separating anything, and no
    veto floor is the right floor — the answer would be to fix the reading, not
    to move the line.
    """
    rows = [r for r in _graded(dossiers)
            if isinstance(r["_outcome"].get("research_conviction"), (int, float))]
    out: list[dict] = []
    for lo, hi in zip(edges, edges[1:]):
        last = hi == edges[-1]
        group = [
            r for r in rows
            if lo <= r["_outcome"]["research_conviction"] < hi
            or (last and r["_outcome"]["research_conviction"] == hi)
        ]
        out.append({"lo": lo, "hi": hi, **_outcome_stats(group)})
    return out


def assessment_accuracy(dossiers: Iterable[dict]) -> list[dict]:
    """
    How each verdict actually did.

    `graded` is smaller than `n` on purpose. A NEUTRAL reading declined to take
    a side and an unmeasurable window has no side to take; both are excluded
    from `accuracy` rather than counted as misses, which would make the number
    describe the sample's direction instead of the reading's quality.
    """
    rows = _graded(dossiers)
    out: list[dict] = []
    for verdict in ("BULLISH", "NEUTRAL", "BEARISH"):
        group = [r for r in rows
                 if (r["_outcome"].get("assessment") or "").upper() == verdict]
        graded = [r for r in group
                  if isinstance(r["_outcome"].get("assessment_correct"), bool)]
        correct = sum(1 for r in graded if r["_outcome"]["assessment_correct"])
        out.append({
            "assessment": verdict,
            "graded": len(graded),
            "correct": correct,
            "accuracy": round(correct / len(graded), 4) if graded else None,
            "significant": len(graded) >= MIN_SAMPLES_FOR_SIGNAL,
            **_outcome_stats(group),
        })
    return out


def veto_counterfactual(dossiers: Iterable[dict],
                        floor: Optional[float] = None) -> dict:
    """
    What the names research would have refused actually did.

    This is the number `RESEARCH_VETO_ENABLED` should be argued from, and
    nobody has ever had it. The veto has shipped with a floor of 35 that was
    chosen the way `BUY_THRESHOLD = 0.70` was chosen — by picking one — and
    with the feature off by default, no deployment has produced evidence either
    way.

    Read it as a pair. `would_block` is the group the veto would have refused;
    `allowed` is everything else. The veto earns its place only if the blocked
    group's forward alpha is meaningfully *worse* — a blocked group that
    performed in line with the rest means the guard is refusing trades for no
    return, which costs opportunity on every one of them.

    Applied to the recorded reading rather than by re-running `evaluate_veto`:
    a dossier's stored assessment and conviction are what it said at the time,
    and re-deriving them against today's settings would answer a different
    question.
    """
    env_floor = floor if floor is not None else float(
        get_settings().research_veto_min_conviction
    )
    rows = _graded(dossiers)

    blocked, allowed = [], []
    for row in rows:
        outcome = row["_outcome"]
        assessment = (outcome.get("assessment") or "").upper()
        conviction = outcome.get("research_conviction")
        trips = assessment == "BEARISH" or (
            isinstance(conviction, (int, float)) and conviction < env_floor
        )
        (blocked if trips else allowed).append(row)

    return {
        "floor": env_floor,
        "would_block": _outcome_stats(blocked),
        "allowed": _outcome_stats(allowed),
        # Positive means the veto refused the worse names, which is the only
        # result that justifies switching it on. None when either side is too
        # thin to compare — the honest answer far more often than not.
        "alpha_saved": (
            round(_outcome_stats(allowed)["avg_alpha"]
                  - _outcome_stats(blocked)["avg_alpha"], 6)
            if _outcome_stats(blocked)["avg_alpha"] is not None
            and _outcome_stats(allowed)["avg_alpha"] is not None
            else None
        ),
        "conclusive": (
            _outcome_stats(blocked)["alpha_significant"]
            and _outcome_stats(allowed)["alpha_significant"]
        ),
    }


def summarise_research(dossiers: Iterable[dict]) -> dict:
    """Everything above, plus the base rate the buckets should be judged against."""
    rows = _graded(dossiers)
    buckets = conviction_buckets(rows)

    usable = [b for b in buckets if b["alpha_significant"] and b["avg_alpha"] is not None]
    monotonic = (
        all(a["avg_alpha"] <= b["avg_alpha"] for a, b in zip(usable, usable[1:]))
        if len(usable) >= 2 else None
    )

    with_lesson = sum(
        1 for r in rows
        if ((r["_outcome"].get("reflection") or {}).get("lesson"))
    )

    return {
        "graded_dossiers": len(rows),
        "benchmark_ticker": benchmark_ticker(),
        "base_rate": _outcome_stats(rows),
        "conviction_buckets": buckets,
        "conviction_ranks_alpha": monotonic,
        "usable_buckets": len(usable),
        "assessment_accuracy": assessment_accuracy(rows),
        "veto_counterfactual": veto_counterfactual(rows),
        # How much of the loop is producing usable prose. A high graded count
        # with few lessons means the reflection is running and being filtered
        # away, which is a different problem from the loop not running.
        "lessons_recorded": with_lesson,
        "min_samples_for_signal": MIN_SAMPLES_FOR_SIGNAL,
    }


def _model_label(doc: dict) -> str:
    """
    The producer of a dossier, as one label.

    Falls back to `unknown` for documents written before provenance was
    recorded rather than guessing Anthropic — they *were* all Anthropic, but a
    bucket labelled with an assumption is exactly the kind of thing that gets
    read as measured later.
    """
    used = doc.get("models_used") or []
    if not used:
        return "unknown"
    return ", ".join(sorted(f"{u.get('provider')}/{u.get('model')}" for u in used))


async def research_calibration_report(ticker: Optional[str] = None,
                                      user_id: Optional[str] = None) -> dict:
    """
    Load this reader's graded dossiers and summarise them, per model.

    Two scopings, and both are corrections rather than features.

    **By user**, because dossiers are built on the trader's own key and their
    own chosen models. Pooling readers pools opinions that were never meant to
    be one opinion.

    **By model**, because that is the question this arm exists to answer.
    Bucketing conviction against forward alpha across a mixture of producers
    measures the mixture — a strong model and a weak one average into a middling
    curve that describes neither, and the conclusion drawn from it ("conviction
    doesn't rank alpha") would be wrong about both.

    The honest cost is stated in the payload rather than hidden: segmenting
    makes every `n` smaller, and on a small deployment the per-model rows may
    never reach `MIN_SAMPLES_FOR_SIGNAL`. `pooled` is returned alongside them
    and explicitly labelled as mixing producers, so there is something to look
    at while the segmented rows fill — never as the finding.
    """
    db = await get_db()
    query: dict[str, Any] = {
        "outcome": {"$ne": None},
        "user_id": str(user_id) if user_id else None,
    }
    if ticker:
        query["ticker"] = ticker.upper()

    dossiers = await db[COLL_DOSSIERS].find(
        query,
        {"_id": 0, "ticker": 1, "as_of": 1, "outcome": 1, "models_used": 1},
    ).to_list(length=100_000)

    by_model: dict[str, list[dict]] = {}
    for doc in dossiers:
        by_model.setdefault(_model_label(doc), []).append(doc)

    report = {
        "ticker": ticker.upper() if ticker else None,
        "graded_dossiers": len(dossiers),
        "min_samples_for_signal": MIN_SAMPLES_FOR_SIGNAL,
        #: One arm per producer. This is the answer; `pooled` is context.
        "by_model": [
            {"model": label, **summarise_research(docs)}
            for label, docs in sorted(by_model.items())
        ],
        #: Every graded dossier regardless of producer. Kept because a thin
        #: segmented view is unreadable for weeks and a reader needs something
        #: — and labelled, because a curve drawn across two models is not a
        #: statement about either of them.
        "pooled": {
            **summarise_research(dossiers),
            "mixes_producers": len(by_model) > 1,
        },
    }
    logger.info(
        "research_calibration_report",
        ticker=ticker or "ALL", user_id=user_id,
        graded=len(dossiers), models=len(by_model),
    )
    return report
