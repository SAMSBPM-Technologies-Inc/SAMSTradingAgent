"""
Tests for the research veto guard.

This is the only part of the research work that can stop money moving, so the
properties worth pinning are mostly about what it must NOT do.

The veto may block a BUY. It may never create one, enlarge one, or reach the
exit path — the same asymmetry that exempts SELL from every other delay in this
system, because refusing to buy costs an opportunity and refusing to sell costs
money. And every uncertain path must allow the trade: a stale dossier, a
missing one, an unreadable database. A guard that halts all buying when a
scheduler misfires is a worse failure than one that occasionally lets a trade
through unchecked.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services import trade_manager as TM  # noqa: E402


@pytest.fixture
def veto_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "research_veto_enabled", True, raising=False)
    monkeypatch.setattr(settings, "research_veto_min_conviction", 35.0, raising=False)
    monkeypatch.setattr(settings, "research_veto_max_age_hours", 48, raising=False)
    return settings


def _dossier(conviction=70.0, assessment="BULLISH", age_hours=2.0):
    return {
        "ticker": "EXMP",
        "conviction": conviction,
        "age_hours": age_hours,
        "report": {"assessment": assessment},
    }


def _patch_dossier(monkeypatch, value, raises=False):
    """
    Patch the lookup at its source module.

    `_research_veto` imports `latest_dossier` inside the function, so the name
    is resolved at call time from `app.services.research.dossier` — patching
    the attribute on `trade_manager` would have no effect and the test would
    pass for the wrong reason.
    """
    import app.services.research.dossier as D

    async def fake(_ticker):
        if raises:
            raise RuntimeError("mongo is down")
        return value

    monkeypatch.setattr(D, "latest_dossier", fake)


def _veto(ticker="EXMP"):
    return asyncio.run(TM._research_veto(ticker))


# ── Blocking ──────────────────────────────────────────────────────────────────

def test_low_conviction_blocks(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, _dossier(conviction=20.0))
    reason = _veto()
    assert reason is not None
    assert "conviction" in reason.lower()
    assert "20" in reason


def test_a_bearish_assessment_blocks_regardless_of_conviction(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, _dossier(conviction=80.0, assessment="BEARISH"))
    reason = _veto()
    assert reason is not None
    assert "BEARISH" in reason


@pytest.mark.parametrize("age_hours,expected", [
    (0.5, "current"),
    (20.0, "20h-old"),
    (30.0, "1d-old"),
    (72.0, "3d-old"),
])
def test_the_reason_says_how_fresh_the_dossier_was(veto_on, monkeypatch,
                                                   age_hours, expected):
    """A skip a user cannot date is a skip they cannot judge."""
    monkeypatch.setattr(get_settings(), "research_veto_max_age_hours", 999,
                        raising=False)
    _patch_dossier(monkeypatch, _dossier(conviction=10.0, age_hours=age_hours))
    assert expected in _veto()


# ── Allowing ──────────────────────────────────────────────────────────────────

def test_healthy_conviction_allows(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, _dossier(conviction=70.0))
    assert _veto() is None


def test_conviction_exactly_at_the_floor_allows(veto_on, monkeypatch):
    """The floor is a minimum to clear, not a value to fail on."""
    _patch_dossier(monkeypatch, _dossier(conviction=35.0))
    assert _veto() is None


# ── Fail-open paths — each of these must allow the trade ──────────────────────

def test_disabled_allows_without_reading_anything(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "research_veto_enabled", False, raising=False)

    import app.services.research.dossier as D

    async def explode(_ticker):
        raise AssertionError("must not be consulted while disabled")

    monkeypatch.setattr(D, "latest_dossier", explode)
    assert _veto() is None


def test_no_dossier_allows(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, None)
    assert _veto() is None


def test_a_stale_dossier_never_vetoes(veto_on, monkeypatch):
    """
    The important one. A scheduler outage ages every dossier past the window;
    if that blocked trading, one broken cron job would silently halt the agent.
    """
    _patch_dossier(monkeypatch, _dossier(conviction=5.0, age_hours=200.0))
    assert _veto() is None


def test_an_undated_dossier_never_vetoes(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, _dossier(conviction=5.0, age_hours=None))
    assert _veto() is None


def test_a_dossier_with_no_conviction_allows(veto_on, monkeypatch):
    """Failing to reach a view is not the same as reaching a negative one."""
    _patch_dossier(monkeypatch, _dossier(conviction=None, assessment="NEUTRAL"))
    assert _veto() is None


def test_a_dossier_with_no_report_allows(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, {"ticker": "EXMP", "age_hours": 1.0,
                                 "conviction": None, "report": None})
    assert _veto() is None


def test_a_database_failure_allows(veto_on, monkeypatch):
    _patch_dossier(monkeypatch, None, raises=True)
    assert _veto() is None


# ── Scope: the veto must not reach the exit path ──────────────────────────────

def test_the_exit_path_does_not_run_the_entry_guard_chain():
    """
    Structural, not behavioural, and deliberately so.

    `_research_veto` is called from `_prepare_entry` and nowhere else, and
    `execute_exit` does not run that chain. If someone later wires a research
    check into the exit path, this fails — which is the point. Delaying an exit
    costs money, and no amount of research is worth that trade.
    """
    import inspect

    source = inspect.getsource(TM)
    entry_source = inspect.getsource(TM._prepare_entry)
    exit_source = inspect.getsource(TM.execute_exit)

    assert "_research_veto" in entry_source
    assert "_research_veto" not in exit_source
    # One call site plus the definition and this test's own reference.
    assert source.count("await _research_veto(") == 1


def test_the_veto_can_only_return_a_reason_or_none(veto_on, monkeypatch):
    """
    It blocks; it never sizes, enlarges or approves.

    The return contract is the enforcement: `_prepare_entry` reads a truthy
    value as "refuse" and nothing else, so there is no shape this function
    could return that would increase exposure.
    """
    for dossier in (_dossier(conviction=5.0), _dossier(conviction=95.0), None):
        _patch_dossier(monkeypatch, dossier)
        result = _veto()
        assert result is None or isinstance(result, str)
