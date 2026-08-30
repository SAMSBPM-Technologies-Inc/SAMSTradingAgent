"""
Tests for the live report of what is working.

Two failure modes are being guarded against, and neither is a wrong number:

  * **Calling an unset key a fault.** A source with no key is a configuration
    choice. Painting it red trains people to ignore the page, which costs more
    than the page was ever worth. Same distinction `ResearchVetoStatus` draws
    between `enabled` and `would_block`.
  * **Reporting a total outage every night.** The pipeline does not run outside
    market hours, so freshness judged against wall time says the system is dead
    from 16:00 Friday to 09:30 Monday. This is the single fastest way to ship a
    status page nobody believes.

`build_status` is a pure function over `(settings, health, now, market_open)`
for exactly this reason — every case below is interesting and none of them
should need a database.

Run with:  pytest backend/tests -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.services import source_health as sh  # noqa: E402
from app.services.system_status import (  # noqa: E402
    CAPABILITIES, TIERS, build_status,
)

NOW = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)


class _Settings:
    """Every capability configured, unless a test says otherwise."""

    finnhub_enabled = True
    fred_enabled = True
    fundamentals_enabled = True
    analyst_enabled = True
    research_agents_enabled = True
    enable_ml_model = False
    auto_trade_enabled = True


def settings(**overrides) -> _Settings:
    s = _Settings()
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def health(**overrides) -> dict:
    """Health records in which every source answered on a recent cycle."""
    base = {
        source: {"source": source, "last_status": sh.OK,
                 "last_success_at": NOW - timedelta(minutes=3),
                 "tickers_ok": 13, "tickers_total": 13}
        for source in sh.SOURCES
    }
    base["pipeline"] = {
        "source": "pipeline", "last_status": sh.OK,
        "last_cycle_at": NOW - timedelta(minutes=3),
        "tickers_ok": 13, "tickers_total": 13, "failed_tickers": [],
    }
    base.update(overrides)
    return base


def status(cfg=None, hp=None, *, market_open=True) -> dict:
    return build_status(
        cfg or settings(), health() if hp is None else hp,
        now=NOW, market_open=market_open,
    )


def row(result: dict, capability_id: str) -> dict:
    return next(r for r in result["capabilities"] if r["id"] == capability_id)


# ── An unset key is a choice, not a fault ─────────────────────────────────────

def test_a_source_with_no_key_is_not_broken():
    result = status(settings(fred_enabled=False))
    macro = row(result, "macro")
    assert macro["state"] == sh.NOT_CONFIGURED
    assert macro["state"] != sh.FAILED
    assert macro["configured"] is False
    # And it does not drag the whole system into "degraded".
    assert result["overall"] == "ok"


def test_an_unset_key_says_which_variable_switches_it_on():
    detail = row(status(settings(finnhub_enabled=False)), "sentiment")["detail"]
    assert "FINNHUB_API_KEY" in detail


def test_configured_and_working_stay_separate_fields():
    """
    A key can be present and the provider still failing. Collapsing the two
    into one boolean makes that state impossible to express.
    """
    result = status(hp=health(macro={"source": "macro", "last_status": sh.FAILED,
                                     "consecutive_failures": 3}))
    macro = row(result, "macro")
    assert macro["configured"] is True
    assert macro["state"] == sh.FAILED
    assert "3 cycles in a row" in macro["detail"]
    assert result["overall"] == "degraded"


# ── The market clock ──────────────────────────────────────────────────────────

def test_a_quiet_night_is_not_an_outage():
    """
    The same silence, judged twice. The pipeline is not scheduled outside
    market hours, so age alone cannot decide staleness.
    """
    stale = health(pipeline={"source": "pipeline", "last_status": sh.OK,
                             "last_cycle_at": NOW - timedelta(hours=3)})
    assert status(hp=stale, market_open=True)["overall"] == "degraded"
    assert status(hp=stale, market_open=False)["overall"] == "ok"


def test_a_stalled_cycle_during_market_hours_leads_the_summary():
    """
    Every capability row describes the last cycle, so a cycle that has not run
    makes all of them meaningless — it has to be said before anything else.
    """
    result = status(
        hp=health(pipeline={"source": "pipeline", "last_status": sh.OK,
                            "last_cycle_at": NOW - timedelta(hours=3)}),
        market_open=True,
    )
    assert result["cycle"]["stale"] is True
    assert result["cycle"]["age_minutes"] == 180
    assert "180 minutes ago" in result["summary"]


def test_a_fresh_cycle_is_not_stale():
    assert status()["cycle"]["stale"] is False


# ── Severity ──────────────────────────────────────────────────────────────────

def test_a_failing_price_feed_halts_rather_than_degrades():
    """
    Price is the only hard dependency: ingestion raises, so no score is written
    and no order is evaluated. That is a different fact from a neutral factor.
    """
    result = status(hp=health(price={"source": "price", "last_status": sh.FAILED}))
    assert result["overall"] == "halted"
    assert "Trading is paused" in result["summary"]


def test_a_failing_quiet_source_degrades_but_says_scores_still_publish():
    result = status(hp=health(sentiment={"source": "sentiment",
                                         "last_status": sh.FAILED}))
    assert result["overall"] == "degraded"
    assert "still publish" in result["summary"]


def test_a_stale_fundamentals_cache_is_not_a_failure():
    """A cache served past its window is a real provider answer, just not today's."""
    result = status(hp=health(fundamentals={"source": "fundamentals",
                                            "last_status": sh.STALE}))
    assert row(result, "fundamentals")["state"] == sh.STALE
    assert result["overall"] == "ok"


# ── A failure that changes no number does not set the banner ──────────────────
#
# The page read *degraded* on a server whose every weighted factor was live,
# because a Yahoo option chain had missed one symbol — and the summary it
# generated then contradicted that row's own impact line by claiming the factors
# it fed had gone neutral. Alternative data is an additive modifier centred on
# 0.50; an absent one moves the composite by 0.00.

def test_a_failure_that_cannot_change_a_score_does_not_degrade_the_banner():
    result = status(hp=health(alternative={"source": "alternative",
                                           "last_status": sh.FAILED}))
    assert row(result, "alternative")["state"] == sh.FAILED
    assert result["overall"] == "ok"


def test_but_it_is_still_named_in_the_summary():
    """Suppressed in the headline, never hidden. A silent red row is worse."""
    summary = status(hp=health(alternative={"source": "alternative",
                                            "last_status": sh.FAILED}))["summary"]
    assert "Options and insider flow" in summary
    assert "changes no score" in summary


def test_the_exemption_is_not_granted_by_tier():
    """
    Sentiment is `quiet` too, and it is 0.20 of every composite. The question
    the banner asks is whether a number moved, not how the row is grouped.
    """
    from app.services.system_status import alters_scores
    assert alters_scores("sentiment") is True
    assert alters_scores("alternative") is False
    # A capability nobody classified is assumed to matter.
    assert alters_scores("something_new") is True


# ── Partial failure is a degradation, not an outage ───────────────────────────

def test_one_ticker_of_thirteen_erroring_is_a_degradation():
    """
    Worst-wins decides *which* fault to name; it must not also decide how bad
    it is. Reporting `failed` for a source that answered twelve times is what
    kept the alternative row permanently red.
    """
    assert sh._resolved(
        {"status": sh.FAILED, "ok": 12, "total": 13, "detail": "error"}
    ) == sh.DEGRADED


def test_a_source_that_answered_for_nobody_has_failed():
    assert sh._resolved(
        {"status": sh.FAILED, "ok": 0, "total": 13, "detail": "error"}
    ) == sh.FAILED


def test_a_partial_answer_says_how_partial():
    detail = row(status(hp=health(alternative={
        "source": "alternative", "last_status": sh.DEGRADED,
        "tickers_ok": 12, "tickers_total": 13,
    })), "alternative")["detail"]
    assert "12 of 13" in detail


# ── The analyst and deep research report at all ───────────────────────────────
#
# Neither touches `stocks_raw`, so `observe` cannot see them, and nothing called
# `record_subsystem` for them either — their rows read "No reading yet"
# permanently on a server where both were working. That is the page reporting on
# its own instrumentation rather than on the system.

def test_a_recorded_analyst_reading_is_surfaced():
    result = status(hp=health(analyst={
        "source": "analyst", "last_status": sh.OK,
        "last_success_at": NOW - timedelta(minutes=8),
    }))
    assert row(result, "analyst")["state"] == sh.OK
    assert row(result, "analyst")["last_success_at"] is not None


def test_a_failing_analyst_degrades_because_conviction_gates_execution():
    result = status(hp=health(analyst={"source": "analyst",
                                       "last_status": sh.FAILED}))
    assert result["overall"] == "degraded"


def test_research_switched_on_with_nobody_opted_in_reads_as_a_setting():
    """
    `llm_settings.research_enabled` defaults false, so this server builds
    nothing while the feature flag is on. It is a setting, not a fault, and the
    status word alone cannot say which — hence the recorded sentence.
    """
    result = status(hp=health(research={
        "source": "research", "last_status": sh.NOT_CONFIGURED,
        "status_detail": "Switched on for this server, but no account has "
                         "enabled research in its LLM settings, so no dossiers "
                         "are built.",
    }))
    assert row(result, "research")["state"] == sh.NOT_CONFIGURED
    assert "no account has enabled research" in row(result, "research")["detail"]
    assert result["overall"] == "ok"


def test_a_recorded_sentence_cannot_outlive_its_condition():
    """It is written on every attempt, including as None."""
    from app.services.source_health import _update_for

    update = _update_for("research", sh.OK, NOW, detail=None)
    assert update["$set"]["last_detail"] is None


def test_a_failed_attempt_scrubs_its_error_and_extends_the_streak():
    from app.services.source_health import _update_for

    update = _update_for(
        "research", sh.FAILED, NOW,
        error="401 from https://api.anthropic.com/v1/messages?api_key=sk-live",
    )
    assert update["$inc"] == {"consecutive_failures": 1}
    assert "sk-live" not in update["$set"]["last_error"]


def test_a_successful_attempt_clears_the_streak():
    from app.services.source_health import _update_for

    update = _update_for("analyst", sh.OK, NOW)
    assert update["$set"]["consecutive_failures"] == 0
    assert "$inc" not in update


# ── The ML path reports what actually ran ─────────────────────────────────────

def test_the_weighted_path_is_a_first_class_state_not_an_absence():
    """ML off is the normal, supported configuration — not a missing feature."""
    scoring = row(status(settings(enable_ml_model=False)), "scoring")
    assert scoring["state"] == sh.OK
    assert "weighted" in scoring["detail"]


def test_ml_configured_but_not_running_is_surfaced():
    """
    The model file is gitignored and never reaches a deployed box, so this is
    what a server with ENABLE_ML_MODEL=true is really doing. It used to be
    visible only in a log line.
    """
    result = status(
        settings(enable_ml_model=True),
        health(scoring={"source": "scoring", "last_status": sh.OK,
                        "method": "weighted"}),
    )
    scoring = row(result, "scoring")
    assert scoring["state"] == sh.DEGRADED
    assert "not present on this server" in scoring["detail"]


def test_ml_actually_running_reads_clean():
    result = status(
        settings(enable_ml_model=True),
        health(scoring={"source": "scoring", "last_status": sh.OK,
                        "method": "xgboost"}),
    )
    assert row(result, "scoring")["state"] == sh.OK


# ── The database answers itself ───────────────────────────────────────────────

def test_the_database_is_not_reported_unknown_while_serving_the_request():
    """Reading the health records required a successful query."""
    assert row(status(hp={}), "database")["state"] == sh.OK


def test_an_empty_health_collection_does_not_claim_failure():
    """A fresh deployment has recorded nothing. That is not an outage."""
    result = status(hp={}, market_open=False)
    assert result["overall"] == "ok"
    assert row(result, "price")["state"] == sh.NEVER_RUN


# ── The table itself ──────────────────────────────────────────────────────────

def test_every_capability_says_what_its_absence_costs():
    """
    A row reading "FRED: failed" tells a trader nothing they can act on. The
    impact line is the reason the page is worth opening, and it is the same
    sentence docs/12 uses.
    """
    for cap in CAPABILITIES:
        assert cap.impact and len(cap.impact) > 40, cap.id
        assert cap.tier in TIERS, cap.id


def test_capability_ids_are_unique():
    ids = [c.id for c in CAPABILITIES]
    assert len(ids) == len(set(ids))


def test_the_analyst_row_names_the_semi_auto_consequence():
    """
    The most consequential silent degradation in the system: no Anthropic key
    means no conviction, and no conviction means a SEMI_AUTO account stops
    executing and starts queueing proposals. If this sentence goes missing the
    page has lost the one thing it most needed to say.
    """
    impact = next(c for c in CAPABILITIES if c.id == "analyst").impact
    assert "SEMI_AUTO" in impact
    assert "proposal" in impact.lower()


# ── Errors never carry credentials ────────────────────────────────────────────

def test_a_url_bearing_error_is_scrubbed_before_storage():
    """
    FRED and the fundamentals providers pass keys in query strings, so an
    exception that quotes the URL it was fetching would write a live key into a
    row a status page then renders. Stripped before storage, not before
    display: a secret that reached the database has already leaked.
    """
    dirty = "HTTPError fetching https://api.stlouisfed.org/fred/series?api_key=abc123secret&id=VIXCLS"
    clean = sh.scrub(dirty)
    assert "abc123secret" not in clean
    assert "api.stlouisfed.org" not in clean


def test_a_key_value_pair_is_redacted_even_without_a_url():
    assert "hunter2" not in sh.scrub("auth failed (api_key=hunter2)")


def test_error_text_is_capped():
    assert len(sh.scrub("x" * 5_000)) <= 200


def test_scrubbing_an_absent_error_yields_nothing():
    assert sh.scrub(None) is None
    assert sh.scrub("") is None


# ── The sentinel classifier ───────────────────────────────────────────────────

@pytest.mark.parametrize("sentinel,expected", [
    ("finnhub+vader+finlex", sh.OK),
    ("fred", sh.OK),
    ("massive+alphavantage", sh.OK),
    # Finnhub answering "no news this week" is a measurement, and a real one.
    ("no_articles", sh.OK),
    ("pending", sh.DEGRADED),
    ("none", sh.DEGRADED),
    ("no_api_key", sh.NOT_CONFIGURED),
    ("error", sh.FAILED),
    ("exception", sh.FAILED),
    ("unavailable", sh.FAILED),
    (None, sh.NEVER_RUN),
])
def test_each_sentinel_reads_as_the_right_state(sentinel, expected):
    assert sh.classify(sentinel) == expected


def test_a_stale_flag_downgrades_a_real_answer_without_failing_it():
    assert sh.classify("massive", stale=True) == sh.STALE
    assert sh.classify("massive", stale=False) == sh.OK


# ── Alerting fires on transitions, not on conditions ──────────────────────────
#
# A status page you have to open is not monitoring. These cover the job that
# reaches out — and, more importantly, the three cases where it must stay quiet,
# because a channel that pages about settled facts is a channel people mute.

import asyncio  # noqa: E402


def _watch(monkeypatch, health_docs, *, cfg=None):
    """Run one pass of the capability watch, capturing what it would send."""
    import app.jobs.scheduler as scheduler
    from app.services import source_health

    sent: list[dict] = []

    async def _read_all():
        return health_docs

    async def _notify(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(source_health, "read_all", _read_all)
    monkeypatch.setattr(scheduler, "_notify_capabilities", _notify)
    monkeypatch.setattr(scheduler, "get_settings", lambda: cfg or settings())
    asyncio.run(scheduler._capability_watch_job())
    return sent


@pytest.fixture(autouse=True)
def _clear_watch_state():
    import app.jobs.scheduler as scheduler
    scheduler._capability_states.clear()
    yield
    scheduler._capability_states.clear()


def _failing(source, failures=2) -> dict:
    return health(**{source: {"source": source, "last_status": sh.FAILED,
                              "consecutive_failures": failures}})


def test_a_confirmed_failure_alerts_once_not_every_cycle(monkeypatch):
    docs = _failing("macro")
    first = _watch(monkeypatch, docs)
    assert len(first) == 1
    assert first[0]["degraded"][0][0] == "Macro environment"

    # The condition persists. It was news once.
    assert _watch(monkeypatch, docs) == []


def test_a_single_bad_cycle_does_not_page_anyone(monkeypatch):
    """
    One transient 429 that the next cycle recovers from is not a condition —
    the same instinct as the signal stability layer's confirmations.
    """
    assert _watch(monkeypatch, _failing("macro", failures=1)) == []


def test_recovery_is_reported(monkeypatch):
    _watch(monkeypatch, _failing("macro"))
    sent = _watch(monkeypatch, health())
    assert len(sent) == 1
    assert sent[0]["recovered"] == ["Macro environment"]
    assert sent[0]["degraded"] == []


def test_an_unconfigured_source_is_never_an_alert(monkeypatch):
    """
    A key you chose not to set is settled fact, not an event. This is the
    difference between a channel people keep on and one they mute.
    """
    assert _watch(monkeypatch, health(), cfg=settings(fred_enabled=False)) == []


def test_a_fresh_deployment_with_no_records_says_nothing(monkeypatch):
    assert _watch(monkeypatch, {}) == []


def test_a_failure_that_changes_no_number_never_pages_anyone(monkeypatch):
    """
    The same judgement as the banner. Asking someone to act on a failure with
    no consequence is how a channel gets muted before the one that matters
    arrives.
    """
    assert _watch(monkeypatch, _failing("alternative")) == []


def test_the_alert_carries_what_the_failure_costs(monkeypatch):
    """
    "FRED is failing" is not actionable on a lock screen. The impact line is
    the whole reason the message is worth sending.
    """
    sent = _watch(monkeypatch, _failing("sentiment"))
    _label, impact = sent[0]["degraded"][0]
    assert "0.50" in impact
