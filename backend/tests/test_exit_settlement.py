"""
Tests for exits the agent or the user submitted.

`execute_exit` stamps `closed_at` the moment it sends the sell. Reconciliation's
open-trade query requires `closed_at: None`, so those trades fell outside every
phase of it and nothing ever settled them: they sat at PENDING with an estimated
P&L forever, invisible to `/performance/trades` (which counts `status ==
CLOSED`) while Order History showed a "pending" pill for a position sold days
ago. Every agent SELL and every press of the Close button landed there.

Two properties carry the weight:

  * A trade settles only when it is genuinely finished. A working sell order or
    a position the venue still reports means the shares are still at risk, and
    booking a result for them would report a P&L that has not happened.
  * The reason a position closed is preserved, never re-guessed. `execute_exit`
    is the only code that knows whether a stop fired, the score fell, or a
    person pressed Close, and reconciliation stamping `bracket_or_manual` over
    that claims a stop fired when the agent did the selling.

Run with:  pytest backend/tests -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.trade import TradeStatus  # noqa: E402
from app.services.brokers.base import Fill  # noqa: E402
from app.services.trade_manager import _settle_exit_update  # noqa: E402
from app.services.trade_rationale import exit_rationale  # noqa: E402

ENTRY_AT = datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc)
EXIT_AT = ENTRY_AT + timedelta(days=6)


def sell(price, qty=12, *, commission=1.20, exec_id="x1", ticker="AVGO"):
    return Fill(
        ticker=ticker, side="SELL", qty=qty, price=price, executed_at=EXIT_AT,
        order_id="EXIT-1", exec_id=exec_id,
        commission=commission, commission_currency="USD",
    )


def submitted_exit(**over):
    """A trade `execute_exit` has sent the sell for and stamped closed_at on."""
    trade = {
        "_id": "t1", "ticker": "AVGO", "action": "BUY", "qty": 12,
        "filled_qty": 12, "entry_price": 298.10, "limit_price": 298.40,
        "opened_at": ENTRY_AT, "filled_at": ENTRY_AT, "closed_at": EXIT_AT,
        "status": TradeStatus.PENDING,
        "exit_order_id": "EXIT-1",
        "exit_qty_submitted": 12,
        "exit_price": 195.27, "pnl": -1234.00, "exit_price_estimated": True,
        "exit_trigger": "SELL_SIGNAL",
        "exit_reason": "Score fell below the sell threshold — scored 24/100 "
                       "against the 30 that triggers a sell",
    }
    trade.update(over)
    return trade


# ── It settles, which is the whole bug ───────────────────────────────────────

def test_a_submitted_exit_reaches_closed():
    """
    The defect this file exists for. Without settlement the trade stays PENDING
    and `/performance/trades` — which counts `status == CLOSED` — never sees it,
    so a position the agent sold is missing from realised P&L for good.
    """
    update = _settle_exit_update(submitted_exit(), [sell(195.27)], {}, {})
    assert update is not None
    assert update["status"] == TradeStatus.CLOSED


def test_the_real_fill_replaces_the_submitted_estimate():
    """
    `execute_exit` writes the price it is *asking* for. Settlement must adopt
    what actually filled, and say the figure is no longer an estimate.
    """
    update = _settle_exit_update(submitted_exit(), [sell(196.50)], {}, {})
    assert update["exit_price"] == 196.50
    assert update["pnl"] == round((196.50 - 298.10) * 12, 2)
    assert update["exit_price_estimated"] is False


def test_commission_is_folded_into_net():
    update = _settle_exit_update(
        submitted_exit(), [sell(196.50, commission=1.20)], {}, {},
    )
    assert update["commission_paid"] == 1.20
    assert update["pnl_net"] == round(update["pnl"] - 1.20, 2)


def test_an_incomplete_fee_total_leaves_net_unstated():
    """
    A partial commission would make the trade look cheaper than it was, in the
    same direction every time.
    """
    update = _settle_exit_update(
        submitted_exit(), [sell(196.50, commission=None)], {}, {},
    )
    assert update.get("pnl_net") is None
    assert update["commission_complete"] is False


# ── It waits when the trade is not actually finished ─────────────────────────

def test_a_working_sell_order_is_not_settled():
    """
    The exit order is still live at the venue. Nothing has been realised, and
    closing the record here would book a P&L for shares still at risk.
    """
    statuses = {"EXIT-1": object()}
    assert _settle_exit_update(submitted_exit(), [sell(195.27)], statuses, {}) is None


def test_a_position_the_venue_still_reports_is_not_settled():
    """
    The sell did not fill, or filled only partially. Either way shares are still
    held, so this is not a closed trade.
    """
    assert _settle_exit_update(submitted_exit(), [sell(195.27)], {}, {"AVGO": 12}) is None


def test_a_flat_position_with_no_working_order_does_settle():
    """The complement of the two guards above — nothing held, nothing working."""
    update = _settle_exit_update(submitted_exit(), [sell(195.27)], {}, {"AVGO": 0})
    assert update is not None


# ── The estimate is dropped, not promoted ────────────────────────────────────

def test_an_unpriceable_exit_discards_the_estimate_rather_than_banking_it():
    """
    IB serves only the current session, so a trade closed on an earlier day
    cannot be priced. The estimate `execute_exit` wrote came from the limit we
    asked for — and on a manual close that limit is the position's own average
    cost, making the figure ~0 every time. Banking it would drag the whole
    record toward break-even.
    """
    update = _settle_exit_update(submitted_exit(), [], {}, {})
    assert update["status"] == TradeStatus.CLOSED
    assert update["pnl"] is None
    assert update["exit_price"] is None
    assert update["exit_price_estimated"] is False


def test_a_manual_close_priced_at_average_cost_is_not_recorded_as_break_even():
    """
    The concrete shape of the bug above: /trading/close passes avg_cost as the
    current price, so the estimated P&L is almost exactly zero. That must never
    reach the record as a realised result.
    """
    flat = submitted_exit(pnl=0.0, exit_price=298.10, exit_trigger="MANUAL_CLOSE")
    update = _settle_exit_update(flat, [], {}, {})
    assert update["pnl"] is None


# ── The reason survives ──────────────────────────────────────────────────────

def test_a_recorded_reason_is_never_overwritten():
    """
    Reconciliation can see that a position went flat but not why. Stamping
    `bracket_or_manual` over a reason the exit path recorded would claim a stop
    fired when the agent or the user did the selling.
    """
    update = _settle_exit_update(submitted_exit(), [sell(195.27)], {}, {})
    assert "exit_reason" not in update


def test_a_row_from_before_reasons_were_recorded_is_labelled_honestly():
    legacy = submitted_exit()
    legacy.pop("exit_reason")
    update = _settle_exit_update(legacy, [sell(195.27)], {}, {})
    assert update["exit_reason"] == "closed_reason_unrecorded"


def test_the_sell_signal_reason_carries_the_score_it_acted_on():
    text = exit_rationale("SELL_SIGNAL", 0.24)
    assert "24/100" in text
    assert "30" in text


def test_every_trigger_produces_a_sentence_not_a_code():
    for trigger in ("SELL_SIGNAL", "EXIT_ALERT", "MANUAL_CLOSE"):
        text = exit_rationale(trigger, None)
        assert text and text != trigger
        assert " " in text


def test_an_unknown_trigger_still_says_something():
    """A new trigger must not produce an empty reason on a closed trade."""
    assert exit_rationale("LIQUIDATION", None) == "Closed on LIQUIDATION"
