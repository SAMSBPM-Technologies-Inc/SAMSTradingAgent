"""
Pydantic models for automated trade execution.
"""
from datetime import datetime
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

# Imported, not restated. `min_signal_score` below is the *second* score bar a
# BUY has to clear, and the two must be set relative to each other or the first
# one silently stops meaning anything — see the field's own comment. This is a
# model reaching into a service, which is the wrong direction in general; the
# alternative is a copy of the number, and this codebase has already been bitten
# twice by copies of a threshold drifting apart (`compute_personalized_score`,
# `_build_gate`). signal_generator imports nothing from `app.models`, so there
# is no cycle.
from app.services.signal_generator import BUY_THRESHOLD

# Venue order IDs: IBKR emits ints, Alpaca emits UUID strings. A union keeps
# trade documents written before the multi-broker change readable — Pydantic v2
# does not coerce int → str, so narrowing to `str` would break historical rows.
OrderId = Union[int, str]


class TradingMode(str, Enum):
    """
    How much autonomy the agent has.

    The product previously offered only AUTO: the agent traded or it did
    nothing, and there was no way for a user to act on a signal from the UI at
    all. Nobody funds an account to a fully autonomous agent on day one, so the
    ladder is suggest → confirm → automate and new users start at the bottom.
    """

    #: The agent never places an order. Every entry it would have taken is
    #: recorded as a proposal for the user to approve or reject.
    MANUAL = "MANUAL"

    #: The agent places orders only at or above `auto_execute_conviction`.
    #: Everything else it would have taken becomes a proposal.
    SEMI_AUTO = "SEMI_AUTO"

    #: The agent places every entry that clears its risk guards.
    AUTO = "AUTO"


#: Analyst conviction, strongest first. Ordered so SEMI_AUTO can compare.
CONVICTION_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class AutoTradeSettings(BaseModel):
    """Per-user settings for automated trade execution."""
    enabled: bool = False
    #: Defaults to MANUAL: an agent that can move money should be opted into,
    #: not defaulted into. Documents written before this field existed load as
    #: MANUAL too, which is the safe direction for a silent migration —
    #: `enabled` still gates whether the agent acts at all.
    mode: TradingMode = TradingMode.MANUAL
    #: SEMI_AUTO only: the weakest conviction the agent may act on unattended.
    auto_execute_conviction: Literal["HIGH", "MEDIUM", "LOW"] = "HIGH"
    paper_trading: bool = True                    # True = paper account; False = live (requires explicit opt-in)
    #: The score bar the *order path* holds a BUY to, on top of the bar the
    #: verdict already cleared. It defaults to `BUY_THRESHOLD` rather than to a
    #: number of its own, because anything higher voids a band of published
    #: BUYs without saying so anywhere a reader would look.
    #:
    #: It shipped at 0.75 against a 0.70 `BUY_THRESHOLD`. Nothing enforced a
    #: relationship between them, and the composite's realistic ceiling is
    #: around 0.75 — so every BUY the engine actually produced landed in
    #: [0.70, 0.75) and was refused at `execute_entry` with a SKIPPED row, while
    #: the ticker page's gate panel showed the BUY gate passing. The panel was
    #: right about the verdict and silent about the order, which is how a
    #: system ends up looking like it has no signals rather than like it has a
    #: threshold set above its own range.
    #:
    #: Raising it above `BUY_THRESHOLD` is a legitimate choice — "I want the
    #: agent to be pickier than the badge" — and is still allowed. What is no
    #: longer allowed is arriving there by default and finding out from an
    #: empty trade history. `SignalGate.order_threshold` now reports it beside
    #: the verdict, and `db._migrate_min_signal_score` reset the accounts that
    #: were only ever on it by default.
    min_signal_score: float = Field(default=BUY_THRESHOLD, ge=0.0, le=1.0)
    position_size_pct: float = Field(default=0.05, ge=0.001, le=0.25)  # fraction of account equity per trade
    max_open_positions: int = Field(default=5, ge=1, le=50)
    max_daily_loss_pct: float = Field(default=0.02, ge=0.001, le=0.20)  # daily drawdown kill-switch
    allowed_tickers: list[str] = []               # empty = all watchlist tickers; non-empty = whitelist

    def may_auto_execute(self, conviction: Optional[str]) -> bool:
        """Whether the agent may place this entry itself, unattended."""
        if not self.enabled:
            return False
        if self.mode is TradingMode.AUTO:
            return True
        if self.mode is TradingMode.MANUAL:
            return False
        # SEMI_AUTO. An absent conviction is not evidence of a strong setup —
        # the analyst may not have run — so it queues rather than executes.
        if conviction is None:
            return False
        return (
            CONVICTION_RANK.get(conviction.upper(), -1)
            >= CONVICTION_RANK[self.auto_execute_conviction]
        )


class AutoTradeSettingsResponse(AutoTradeSettings):
    connected: bool = False   # whether IB Gateway is reachable right now


class TradeStatus:
    PENDING   = "PENDING"    # order submitted, awaiting fill
    FILLED    = "FILLED"     # order fully filled, position open
    PARTIAL   = "PARTIAL"    # order partially filled
    CANCELLED = "CANCELLED"  # order cancelled
    REJECTED  = "REJECTED"   # rejected by broker
    SKIPPED   = "SKIPPED"    # risk guard prevented submission
    CLOSED    = "CLOSED"     # position exited, realised P&L recorded
    #: The broker has no record of this order and holds no matching position,
    #: and the execution log no longer reaches back far enough to say what
    #: happened. Terminal, but explicitly NOT a trade outcome — distinguished
    #: from CLOSED so an unknowable record is never counted as a real result.
    UNRECONCILED = "UNRECONCILED"
    #: The agent would have taken this entry but its mode does not let it act
    #: unattended. Awaiting a human decision. Deliberately NOT in OPEN: nothing
    #: has been committed, no money is at risk, and it must not consume a
    #: position slot or appear in realised performance.
    PROPOSED = "PROPOSED"
    #: A proposal the user declined. Terminal, and not a trade outcome.
    DECLINED = "DECLINED"

    #: Statuses that represent a live commitment — an order that may still fill,
    #: or a position that is open. Anything here counts against position limits.
    OPEN = (PENDING, FILLED, PARTIAL)


class TradeRecord(BaseModel):
    """A single automated trade (entry or exit)."""
    user_id: str
    ticker: str
    action: str                         # "BUY" or "SELL"
    qty: int
    limit_price: float
    order_id: Optional[OrderId] = None  # venue order ID (IBKR int / Alpaca UUID)
    stop_loss: Optional[float] = None   # protective stop submitted with the entry
    take_profit: Optional[float] = None # target submitted with the entry
    status: str = TradeStatus.PENDING
    reason: Optional[str] = None        # skip/reject reason
    signal_score: Optional[float] = None
    signal_type: Optional[str] = None   # "BUY" | "SELL" | "EXIT_ALERT"
    #: Why this position was opened, in the few words a person reads: the score
    #: against the threshold it had to clear, the factors that actually moved
    #: it, and the analyst's conviction. Written by `trade_rationale` from the
    #: same arithmetic that produced the score — never by a model, and never
    #: naming a factor on the XGBoost path, where the weights did not produce
    #: the number. Distinct from `reason`, which says why an order was *not*
    #: placed or how its size was adjusted.
    entry_reason: Optional[str] = None
    #: How much of the score behind this entry came from measured data, 0–1,
    #: by the weights it was actually sized on. Frozen at entry for the same
    #: reason `size_basis_equity` is: read live it would describe today's data
    #: rather than the data the decision was made on. `None` on a manual order
    #: (no score decided it) and on any entry taken before this was recorded.
    input_completeness: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    is_paper: bool = True
    opened_at: datetime
    closed_at: Optional[datetime] = None
    # ── Written by reconciliation, not at submission time ──────────────────
    filled_qty: Optional[float] = None   # shares actually filled (may be < qty)
    filled_at: Optional[datetime] = None
    #: Why the position closed, in the words a person reads. Written by
    #: `execute_exit` when the agent or the user did the selling; guessed by
    #: reconciliation (`bracket_or_manual`) only when a position was found flat
    #: with no submitted exit behind it, which genuinely is a stop, a target, or
    #: a hand-placed order at the broker.
    exit_reason: Optional[str] = None
    #: The stable code behind `exit_reason` — SELL_SIGNAL / EXIT_ALERT /
    #: MANUAL_CLOSE. Absent on exits nobody here submitted.
    exit_trigger: Optional[str] = None
    #: True while `exit_price` and `pnl` are the levels we asked for rather than
    #: what filled. Settlement clears it; performance must not count a trade as
    #: a realised result while it is set.
    exit_price_estimated: Optional[bool] = None


class TradeResponse(BaseModel):
    """API response shape for a trade record."""
    id: str
    user_id: str
    ticker: str
    action: str
    qty: int
    limit_price: float
    order_id: Optional[OrderId] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: str
    reason: Optional[str] = None
    signal_score: Optional[float] = None
    signal_type: Optional[str] = None
    #: The analyst's HIGH/MEDIUM/LOW, written to the document by both the entry
    #: and the proposal path. `ProposalResponse` has always exposed it and this
    #: model did not, so a proposal read through /trading/orders lost the one
    #: field that says how strongly the agent felt about it.
    conviction: Optional[str] = None
    entry_reason: Optional[str] = None
    input_completeness: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    is_paper: bool
    opened_at: datetime
    closed_at: Optional[datetime] = None
    filled_qty: Optional[float] = None
    filled_at: Optional[datetime] = None
    exit_reason: Optional[str] = None
    exit_trigger: Optional[str] = None
    exit_price_estimated: Optional[bool] = None


class ManualOrderRequest(BaseModel):
    """
    A user-initiated order.

    `qty` is a request, not an instruction: the server re-derives the fundable
    quantity from live account state and takes the smaller of the two. A client
    that asks for more than the account can fund gets the funded amount, not a
    rejection and not the number it asked for.
    """
    ticker: str = Field(..., min_length=1, max_length=12)
    action: Literal["BUY", "SELL"] = "BUY"
    qty: Optional[int] = Field(
        default=None, ge=1, le=1_000_000,
        description="Requested share count. Omit to let the server size the "
                    "position from position_size_pct and volatility.",
    )
    limit_price: Optional[float] = Field(
        default=None, gt=0, le=1_000_000,
        description="Limit price. Omit to use the last known price.",
    )
    #: Confirms the user understands this order routes to a live-money account.
    #: Ignored in paper mode; required when the server is in live trading.
    confirm_live: bool = False
    #: Client-supplied de-duplication token. Two requests carrying the same key
    #: place one order — a double-clicked Buy button must not buy twice.
    idempotency_key: Optional[str] = Field(default=None, max_length=64)


class OrderPlacementResponse(BaseModel):
    """Outcome of a manual order attempt. `placed=False` is a normal answer."""
    placed: bool
    status: str
    ticker: str
    action: str
    qty: int = 0
    limit_price: float = 0.0
    order_id: Optional[OrderId] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    is_paper: bool = True
    trade_id: Optional[str] = None
    #: Why an order was not placed, or how the quantity was adjusted.
    reason: Optional[str] = None
    #: Why the order was taken — returned so the confirmation the user sees
    #: says what the record will say.
    entry_reason: Optional[str] = None
    #: True when this request matched an earlier one by idempotency key and no
    #: new order was sent.
    duplicate: bool = False


class ProposalResponse(BaseModel):
    """An entry the agent wanted to take but was not permitted to take alone."""
    id: str
    ticker: str
    action: str
    qty: int
    limit_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    signal_score: Optional[float] = None
    conviction: Optional[str] = None
    reason: Optional[str] = None
    #: Why the agent wanted this entry — the same justification the trade would
    #: carry had it placed the order itself. A proposal asks a person to commit
    #: money; it has to say what for.
    entry_reason: Optional[str] = None
    proposed_at: datetime
    is_paper: bool = True


class AccountSummaryResponse(BaseModel):
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    buying_power: float = 0.0
    connected: bool = False
    account_id: str = ""              # broker account being traded
    gross_position_value: float = 0.0  # market value of open positions
