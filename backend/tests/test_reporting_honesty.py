"""
Tests for three places where the system used to misreport itself.

None of these was a wrong *number*. Each was a correct number wearing a wrong
label, which is worse: a wrong number gets noticed, and a mislabelled one gets
believed. All three were found while writing `docs/12-how-a-trade-is-judged.md`,
which is the argument for writing that kind of document at all.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.catalyst import compute_catalyst_score  # noqa: E402
from app.services.pipeline import DATA_SOURCES_VERSION, _build_data_sources  # noqa: E402
from app.services.scoring import _ml_score, _weighted_score, explain_score  # noqa: E402


# ── Defect 1: scoring_method claimed a model that never ran ───────────────────

def _feat(**overrides) -> dict:
    base = {
        "technical_score": 0.8, "fundamental_score": 0.6, "sentiment_score": 0.7,
        "macro_score": 0.5, "volatility_score": 0.5, "catalyst_score": 0.6,
        "alternative_data_score": 0.5, "rsi_14": 55.0, "bb_pct": 0.5,
        "stoch_rsi": 0.5, "volume_anomaly": 1.0, "volatility_20d": 0.3,
        "vix": 18.0,
    }
    base.update(overrides)
    return base


def test_a_missing_model_file_reports_the_path_that_actually_ran(monkeypatch):
    """
    `model/*.json` is gitignored and never reaches a deployed box, so a server
    with ENABLE_ML_MODEL=true lands here on every single cycle. It used to
    stamp "xgboost" on a number the weighted path produced.
    """
    import app.services.scoring as sc
    monkeypatch.setattr(sc, "_MODEL_PATH", "/nonexistent/xgb_scorer.json")
    monkeypatch.setattr(sc, "_xgb_model", None)

    score, method = _ml_score(_feat())
    assert method == "weighted"
    assert score == pytest.approx(_weighted_score(_feat(), get_settings()), abs=1e-9)


def test_a_weighted_fallback_is_still_attributable(monkeypatch):
    """
    The mislabel was not cosmetic. `explain_score` refuses to decompose an
    "xgboost" score — correctly, because the weights did not produce it — so
    claiming the model ran withheld a factor breakdown that was exactly right,
    from the ticker page and from every trade rationale written on that path.
    """
    import app.services.scoring as sc
    monkeypatch.setattr(sc, "_MODEL_PATH", "/nonexistent/xgb_scorer.json")
    monkeypatch.setattr(sc, "_xgb_model", None)

    _, method = _ml_score(_feat())
    assert explain_score(_feat(scoring_method=method))["attributable"] is True


def test_an_inference_failure_falls_back_rather_than_losing_the_ticker(monkeypatch):
    """
    `predict` was the one XGBoost path with no handler, so a schema drift took
    down scoring, the signal, and the trade evaluation for that ticker — with a
    perfectly good weighted score one line away.
    """
    class _Exploding:
        def predict(self, _vector):
            raise RuntimeError("feature shape mismatch")

    import app.services.scoring as sc
    monkeypatch.setattr(sc, "_xgb_model", _Exploding())

    score, method = _ml_score(_feat())
    assert method == "weighted"
    assert 0.0 <= score <= 1.0


# ── Defect 2: data_sources named a provider that had been removed ─────────────

def test_a_massive_only_refresh_is_not_reported_as_no_data():
    """
    The regression pin. Every ticker past the Alpha Vantage daily budget gets
    exactly this shape — real revenue growth, free cash flow and debt/equity,
    no P/E — and the old code inferred provenance from `pe_ratio` alone and
    called it "none". It reported absence where there was data.
    """
    sources = _build_data_sources({
        "fundamentals": {
            "source": "massive", "pe_ratio": None,
            "revenue_growth_yoy": 0.31, "free_cash_flow": 4.2e9,
        },
    })
    assert sources["fundamentals"] == "massive"


def test_provenance_is_read_from_the_fetch_not_inferred_from_the_payload():
    raw = {
        "price_source": "polygon",
        "sentiment_raw": {"source": "finnhub+vader+finlex", "article_count": 9},
        "macro": {"source": "fred"},
        "fundamentals": {"source": "massive+alphavantage", "stale": True},
        "alternative_data": {"options_flow": {"source": "yfinance"}},
    }
    sources = _build_data_sources(raw)
    assert sources["price"] == "polygon"
    assert sources["sentiment"] == "finnhub+vader+finlex"
    assert sources["macro"] == "fred"
    assert sources["fundamentals"] == "massive+alphavantage"
    assert sources["alternative"] == "yfinance"
    # A cache served past its TTL is a real provider answer, but not today's.
    # Separate field: they are different questions.
    assert sources["fundamentals_stale"] is True


def test_the_record_is_versioned_so_a_corrected_row_is_recognisable():
    """
    Historical rows carry the old `"yfinance"` guess and cannot be backfilled —
    the provider that really answered is not recoverable. The marker is how a
    reader tells a corrected row from an uncorrected one.
    """
    assert _build_data_sources({})["version"] == DATA_SOURCES_VERSION
    assert DATA_SOURCES_VERSION >= 2


def test_an_empty_raw_document_still_answers():
    sources = _build_data_sources({})
    assert sources["fundamentals"] == "none"
    assert sources["price"] == "unknown"


# ── Defect 3: a missing key read as bearish news silence ──────────────────────

def _raw(sentiment: dict, **overrides) -> dict:
    base = {"ticker": "AVGO", "sentiment_raw": sentiment, "fundamentals": {}}
    base.update(overrides)
    return base


#: Volume at exactly the 20-day average, so the volume component sits at 0.5
#: and any movement in the score comes from the news component alone.
NEUTRAL_FEAT = {"volume_anomaly": 1.0, "current_price": 100.0}


def test_an_unconfigured_provider_is_not_a_bearish_fact_about_the_company():
    """
    The neutral stub `news.py` returns carries `article_count: 0`, and 0
    articles used to score 0.40 here — so an absent Finnhub key did not merely
    neutralise the sentiment factor, it dragged the catalyst factor down too,
    and with it the composite. On a server with no key that happened to every
    ticker, every cycle.
    """
    no_key = compute_catalyst_score(
        _raw({"score": 0.5, "article_count": 0, "source": "no_api_key"}),
        NEUTRAL_FEAT,
    )
    assert no_key == pytest.approx(0.5, abs=1e-9)


@pytest.mark.parametrize("source", ["no_api_key", "error", "exception"])
def test_every_unobserved_source_drops_the_component(source):
    score = compute_catalyst_score(
        _raw({"score": 0.5, "article_count": 0, "source": source}), NEUTRAL_FEAT,
    )
    assert score == pytest.approx(0.5, abs=1e-9)


def test_measured_silence_still_counts_against_the_score():
    """
    The distinction the fix rests on. `no_articles` means Finnhub answered and
    there was nothing — that is evidence, and a quiet tape is mildly negative
    for a *catalyst* score. Only "we never looked" is dropped.
    """
    measured = compute_catalyst_score(
        _raw({"score": 0.5, "article_count": 0, "source": "no_articles"}),
        NEUTRAL_FEAT,
    )
    assert measured < 0.5


def test_a_real_news_flow_is_unaffected_by_the_fix():
    busy = compute_catalyst_score(
        _raw({"score": 0.6, "article_count": 14, "source": "finnhub+vader+finlex"}),
        NEUTRAL_FEAT,
    )
    assert busy > 0.5
