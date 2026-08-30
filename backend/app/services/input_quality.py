"""
Input Quality
─────────────
How much of a score was measured, and how much of it is the neutral fallback
standing in for data that never arrived.

Every external source in this system degrades to 0.5 rather than failing the
cycle, which is the right choice — a verdict built on four factors is more
useful than no verdict at all. But it has a consequence nobody had written
down, and `docs/10-due-diligence.md` §6.6 stated it plainly:

    a degraded score still produces a verdict, and a composite assembled from
    three fallbacks at 0.5 looks identical in the API to one assembled from
    live data

That is what this module fixes. It does not change a single score. It records
what the score was *made of*, so a 0.72 built from complete data and a 0.72
built from two live factors and four fallbacks stop being the same number to a
reader.

**Coverage is a fact; completeness is an opinion about it.** A factor's
coverage — how much of its own input arrived — is a property of the data and is
the same for every user, so it is computed once and stored on the feature
document. Completeness weights those coverages by *someone's* weights, and
weights are per-user (`users.scoring_weights`), so it is computed at read time
from `effective_weights` rather than frozen at write time. Storing a
completeness figure would silently be the server's opinion wearing a user's
label.
"""
from app.services.scoring import ALT_FACTOR, FACTORS

__all__ = [
    "MEASURED", "PARTIAL", "FALLBACK",
    "UNOBSERVED_SOURCES", "build_inputs", "completeness", "fallback_factors",
]

#: The whole of the input arrived.
MEASURED = "measured"
#: Some of it did. The rest is already blended toward 0.5 by the sub-score's
#: own coverage weighting, so a partial factor is nearer neutral by design.
PARTIAL = "partial"
#: None of it did. The factor is the flat 0.5 fallback and carries no
#: information about the company at all.
FALLBACK = "fallback"

#: `source` values meaning the fetch never happened or never returned. These
#: are the ones that make a factor a fallback.
#:
#: `no_articles` is deliberately absent: Finnhub answering "there is no news"
#: is a measurement, and a real one. The same distinction `catalyst.py` draws
#: for its news component, and for the same reason.
UNOBSERVED_SOURCES = frozenset({"no_api_key", "error", "exception", "none", "pending",
                                "unavailable", "unknown"})

#: Bumped when the meaning of a stored `inputs` document changes.
INPUTS_VERSION = 1


def _state(coverage: float) -> str:
    if coverage >= 0.999:
        return MEASURED
    if coverage <= 0.001:
        return FALLBACK
    return PARTIAL


def _observed(source: str | None) -> bool:
    return bool(source) and source not in UNOBSERVED_SOURCES


def build_inputs(
    raw_doc: dict,
    *,
    fundamental_coverage: float,
    catalyst_coverage: float,
    has_long_ma: bool,
) -> dict:
    """
    What each factor of this score was actually built from.

    Weight-independent by construction — nothing here consults a weight, so the
    same document is correct for every reader. `completeness()` applies weights
    later.
    """
    sentiment_raw = raw_doc.get("sentiment_raw") or {}
    macro = raw_doc.get("macro") or {}
    alt = raw_doc.get("alternative_data") or {}

    # Sentiment reports its own coverage (headlines found against the number
    # that counts as full cover), and has since it started blending thin reads
    # toward neutral. Read it rather than recomputing it.
    sentiment_cov = (
        float(sentiment_raw.get("coverage") or 0.0)
        if _observed(sentiment_raw.get("source")) else 0.0
    )

    # Macro is all-or-nothing at the source level — `_macro_score` short-circuits
    # to 0.5 on the failure sentinels — but a live FRED can still be missing a
    # series, and a missing series is a thinner reading, not a dead one.
    if _observed(macro.get("source")):
        series = ("vix", "yield_curve_spread", "cpi_yoy_pct")
        macro_cov = sum(1 for k in series if macro.get(k) is not None) / len(series)
    else:
        macro_cov = 0.0

    # Alternative data is an additive modifier centred on 0.5, so an absent one
    # moves the composite by exactly zero. Reported anyway: "it changed nothing"
    # is a different statement from "it agreed with everything else".
    alt_legs = ("options_flow", "insider_trades")
    alt_cov = sum(
        1 for leg in alt_legs if _observed((alt.get(leg) or {}).get("source"))
    ) / len(alt_legs)

    # Technical and volatility are computed from the bars themselves, and
    # `compute_features` refuses to run below 20 of them — so reaching this
    # point means both were measured. The one real gap is a listing too young
    # for a 50-day average, which costs the MA cross and its trend confirmation.
    technical_cov = 1.0 if has_long_ma else 0.75

    coverages = {
        "technical": technical_cov,
        "fundamental": float(fundamental_coverage),
        "sentiment": sentiment_cov,
        "macro": macro_cov,
        # Derived from the same bars as the technical factor; it has no external
        # dependency and therefore no way to be thin.
        "volatility": 1.0,
        "catalyst": float(catalyst_coverage),
        ALT_FACTOR[0]: alt_cov,
    }

    return {
        "version": INPUTS_VERSION,
        "factors": {
            key: {"coverage": round(cov, 4), "state": _state(cov)}
            for key, cov in coverages.items()
        },
    }


def completeness(inputs: dict | None, weights: dict[str, float]) -> float | None:
    """
    The share of this score that came from measured data, by *these* weights.

    `None` when the feature document predates the field — a signal from before
    this existed has no completeness figure and must not be given a flattering
    default. The same rule alpha follows: a number that cannot be computed
    stays absent rather than becoming 0.0 or 1.0, either of which would be a
    claim.

    Only the six base factors count toward the denominator. Alternative data is
    an additive modifier rather than a share of the composite, so folding it in
    would make the fraction sum to more than the score it describes.
    """
    factors = (inputs or {}).get("factors")
    if not factors:
        return None

    total = 0.0
    covered = 0.0
    for key, _feature_key, _label in FACTORS:
        weight = float(weights.get(key, 0.0))
        if weight <= 0.0:
            # A factor weighted at zero is not part of this score, so its
            # coverage is not part of this score's completeness. Volatility is
            # weighted 0.0 by default — priced at the risk gate instead — and
            # counting it would report a completeness the composite never had.
            continue
        total += weight
        covered += weight * float((factors.get(key) or {}).get("coverage", 0.0))

    if total <= 0.0:
        return None
    return round(covered / total, 4)


def fallback_factors(inputs: dict | None, weights: dict[str, float]) -> list[str]:
    """
    The weighted factors that carry no measured data at all, heaviest first.

    This is the list a sentence names — "macro and fundamentals were neutral
    fallbacks" — so it is ordered by what the reader should care about rather
    than by the order the factors happen to be declared in.
    """
    factors = (inputs or {}).get("factors")
    if not factors:
        return []

    ranked = []
    for key, _feature_key, label in FACTORS:
        weight = float(weights.get(key, 0.0))
        if weight <= 0.0:
            continue
        if (factors.get(key) or {}).get("state") == FALLBACK:
            ranked.append((weight, label))
    return [label for _weight, label in sorted(ranked, reverse=True)]
