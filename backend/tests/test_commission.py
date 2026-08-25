"""
Tests for net-of-commission accounting.

Gross P&L is what the position did; net is what reached the account. On a small
account the gap is not a rounding detail — a $200 entry pays the same fixed
ticket as a $20,000 one, so a round trip can cost 0.5% against 0.005%, and a
strategy that looks profitable gross can lose money net.

Two properties carry the weight here, and both are about *not flattering the
record*:

  * A missing commission is recorded as missing, never as zero. Zero would
    understate cost in one direction every time.
  * Accrual is idempotent. `reconcile_trades` re-reads a 24-hour fill window
    every two minutes, so a total that double-counts would climb on its own for
    as long as the app stayed up — fastest on the busiest trades.

Run with:  pytest backend/tests -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.brokers.base import Fill  # noqa: E402
from app.services.trade_manager import (  # noqa: E402
    _accrue_commission, _closing_sell_fills,
)


def fill(exec_id, *, commission=None, side="BUY", qty=10, price=100.0,
         ticker="HXL", executed_at=None):
    return Fill(
        ticker=ticker, side=side, qty=qty, price=price,
        executed_at=executed_at, order_id="ORD-1", exec_id=exec_id,
        commission=commission, commission_currency="USD" if commission else "",
    )


# ── A missing commission is missing, not free ────────────────────────────────

def test_an_unreported_commission_is_not_counted_as_zero():
    """
    IB delivers commission in a report separate from the execution and can lag
    it. Reading "not told yet" as "free" understates exactly the cost this is
    meant to expose.
    """
    update = _accrue_commission({}, [fill("e1", commission=None)])
    assert update.get("commission_paid") is None
    assert update["commission_complete"] is False


def test_a_genuine_zero_commission_is_counted():
    """
    Commission-free venues report 0.0, which is a real figure. Suppressing it
    would make every Alpaca trade unnettable.
    """
    update = _accrue_commission({}, [fill("e1", commission=0.0)])
    assert update["commission_paid"] == 0.0
    assert update["commission_complete"] is True


def test_one_unpriced_execution_taints_the_whole_total():
    """
    A partial fee total is a floor, not a figure. Stating net from it would
    make the trade look cheaper than it was.
    """
    update = _accrue_commission({}, [
        fill("e1", commission=1.00),
        fill("e2", commission=None),
    ])
    assert update["commission_paid"] == 1.00
    assert update["commission_complete"] is False


def test_a_trade_cannot_recover_completeness_once_it_has_a_gap():
    """
    A later clean pass must not overwrite a known gap with a confident-looking
    total — the missing execution is still missing.
    """
    tainted = {"commission_paid": 1.0, "commission_exec_ids": ["e1"],
               "commission_complete": False}
    update = _accrue_commission(tainted, [fill("e2", commission=2.0)])
    assert update["commission_paid"] == 3.0
    assert update["commission_complete"] is False


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_re_reading_the_same_fill_does_not_double_charge():
    """
    Reconcile re-reads a 24h window every two minutes. Without this the fee
    total climbs on its own for as long as the app stays up.
    """
    trade = {}
    first = _accrue_commission(trade, [fill("e1", commission=1.35)])
    trade.update(first)

    second = _accrue_commission(trade, [fill("e1", commission=1.35)])
    assert second == {}
    assert trade["commission_paid"] == 1.35


def test_a_new_execution_on_a_seen_order_still_accrues():
    """A partial fill prints in pieces; later pieces are new, not repeats."""
    trade = {}
    trade.update(_accrue_commission(trade, [fill("e1", commission=1.00)]))
    trade.update(_accrue_commission(trade, [
        fill("e1", commission=1.00), fill("e2", commission=0.50),
    ]))
    assert trade["commission_paid"] == 1.50
    assert sorted(trade["commission_exec_ids"]) == ["e1", "e2"]


def test_both_legs_of_a_round_trip_are_charged():
    """
    A round trip pays twice. Counting only the entry would halve the very cost
    being measured.
    """
    trade = {}
    trade.update(_accrue_commission(trade, [fill("e1", commission=1.00)]))
    trade.update(_accrue_commission(
        trade, [fill("e2", side="SELL", commission=1.00)]))
    assert trade["commission_paid"] == 2.00
    assert trade["commission_complete"] is True


def test_a_scale_in_adds_its_own_ticket():
    """
    Every add is a second ticket on one position — the whole reason adds are
    rationed. The cost has to land on the trade that incurred it.
    """
    trade = {}
    for i, c in enumerate([1.00, 1.00, 1.00], start=1):   # entry + two adds
        trade.update(_accrue_commission(trade, [fill(f"e{i}", commission=c)]))
    trade.update(_accrue_commission(
        trade, [fill("x1", side="SELL", commission=1.00)]))
    assert trade["commission_paid"] == 4.00


# ── The number that should drive the thresholds ──────────────────────────────

def test_fees_can_turn_a_gross_win_into_a_net_loss():
    """
    The case the whole feature exists to surface: a 2-share add on a small
    account clears its spread and still loses money once the ticket is paid.
    """
    gross = round((86.40 - 86.00) * 2, 2)          # +$0.80 on two shares
    trade = {}
    trade.update(_accrue_commission(trade, [fill("e1", commission=1.00)]))
    trade.update(_accrue_commission(
        trade, [fill("e2", side="SELL", commission=1.00)]))
    net = round(gross - trade["commission_paid"], 2)
    assert gross > 0 > net
    assert net == -1.20


def test_the_same_move_on_a_larger_position_survives_the_fee():
    """Identical price move, 200 shares: the fixed ticket stops mattering."""
    gross = round((86.40 - 86.00) * 200, 2)        # +$80
    net = round(gross - 2.00, 2)
    assert net == 78.00


# ── Exit fills are selected consistently with the exit price ─────────────────

def test_the_fills_charged_are_the_fills_priced():
    """
    Exit commission must come from the same executions that set the exit price;
    a different set would charge fees for a trade that was priced elsewhere.
    """
    t0 = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
    fills = [
        fill("old", side="SELL", executed_at=t0 - timedelta(hours=2), commission=9.0),
        fill("a", side="SELL", executed_at=t0 + timedelta(minutes=1), commission=1.0),
        fill("b", side="SELL", executed_at=t0 + timedelta(minutes=2), commission=1.0),
        fill("buy", side="BUY", executed_at=t0 + timedelta(minutes=1), commission=5.0),
    ]
    matched = _closing_sell_fills(fills, "HXL", t0)
    assert [f.exec_id for f in matched] == ["a", "b"]

    update = _accrue_commission({}, matched)
    assert update["commission_paid"] == 2.0  # not 11.0, not 16.0
