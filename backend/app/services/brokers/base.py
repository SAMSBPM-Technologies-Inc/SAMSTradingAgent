"""
Broker Adapter Interface
────────────────────────
A narrow, broker-agnostic contract that `trade_manager` and the `/trading`
routes code against, so the execution venue can be swapped without touching
any signal, risk, or persistence logic.

Implementations:
  - `ibkr.IbkrAdapter`    — Interactive Brokers via IB Gateway + ib_async (TCP)
  - `alpaca.AlpacaAdapter` — Alpaca via REST (no gateway process, no session expiry)

Design notes
────────────
* Every method is `async`. Nothing in this interface may block the event loop —
  that was the defect in the previous ib_insync implementation, which called
  ib_insync's *synchronous* helpers (`accountSummary()`, `positions()`) from
  inside async request handlers.
* `order_id` is a `str` at this boundary. IBKR emits ints and Alpaca emits
  UUIDs; normalising to `str` here keeps callers venue-agnostic.
* Methods return `None` / empty rather than raising when the venue is simply
  unavailable. Callers treat that as "skip this trade", never as a crash.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AccountSummary:
    """Normalised account snapshot. `connected=False` means "no usable data"."""
    connected: bool = False
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    buying_power: float = 0.0
    #: Broker account this snapshot describes. Surfaced in the UI so it is
    #: always obvious which account the agent is trading — this login manages
    #: more than one.
    account_id: str = ""
    #: Market value of all open positions ("funds in trade").
    gross_position_value: float = 0.0

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "net_liquidation": self.net_liquidation,
            "total_cash": self.total_cash,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "buying_power": self.buying_power,
            "account_id": self.account_id,
            "gross_position_value": self.gross_position_value,
        }


@dataclass
class Position:
    ticker: str
    qty: float
    avg_cost: float
    market_value: float | None = None
    unrealized_pnl: float | None = None

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "qty": self.qty,
            "avg_cost": self.avg_cost,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
        }


@dataclass
class OrderStatus:
    """
    What the venue currently believes about one submitted order.

    `status` is the venue's own string, normalised to upper case. Callers should
    branch on the `is_*` helpers rather than matching venue vocabulary, so a new
    adapter can report "accepted" or "PreSubmitted" without breaking anything.
    """
    order_id: str
    status: str = ""
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    avg_fill_price: float = 0.0

    #: Venue strings that mean "this order is done and will not fill further".
    _DEAD = frozenset({
        "CANCELLED", "CANCELED", "APICANCELLED", "INACTIVE",
        "EXPIRED", "REJECTED", "VALIDATIONERROR",
    })

    @property
    def is_filled(self) -> bool:
        return self.filled_qty > 0 and self.remaining_qty <= 0

    @property
    def is_partial(self) -> bool:
        return self.filled_qty > 0 and self.remaining_qty > 0

    @property
    def is_dead(self) -> bool:
        """Terminal without a full fill — cancelled, rejected, or expired."""
        return self.status.upper().replace(" ", "") in self._DEAD


@dataclass
class Fill:
    """
    A single execution report.

    Used to price an exit the agent never submitted itself: when a bracket's
    stop or target triggers, the position simply disappears and the only record
    of what it went out at is the venue's execution log.
    """
    ticker: str
    side: str            # "BUY" | "SELL"
    qty: float
    price: float
    executed_at: datetime | None = None
    order_id: str = ""
    exec_id: str = ""


@dataclass
class BrokerConfig:
    """Connection parameters, populated from `app.config.Settings`."""
    host: str = "127.0.0.1"
    port: int = 4004
    client_id: int = 1
    account_id: str = ""
    paper: bool = True
    # Alpaca-only
    api_key: str = ""
    api_secret: str = ""
    base_url: str = ""
    extra: dict = field(default_factory=dict)


class BrokerAdapter(ABC):
    """Contract every execution venue must satisfy."""

    #: Short venue identifier used in logs and the /trading/account response.
    name: str = "base"

    def __init__(self, config: BrokerConfig) -> None:
        self.config = config

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Establish a session. Returns True on success. Must never raise."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the session. Must be idempotent and must never raise."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Cheap, synchronous liveness check — safe to call per request."""

    # ── Trading ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def place_limit_order(
        self,
        ticker: str,
        action: str,
        qty: int,
        limit_price: float,
        account_id: str = "",
        exchange: str = "SMART",
        currency: str = "USD",
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> str | None:
        """
        Submit a day limit order. Returns the venue order ID, or None on failure.
        For a bracket the ID returned is the PARENT (entry) order's.

        When both `stop_loss_price` and `take_profit_price` are supplied, the
        order is submitted as a bracket: entry plus a linked stop and target, so
        that a fill on one cancels the other. Protection then lives at the
        broker and survives this process dying — which matters because nothing
        here closes a position automatically otherwise.

        Implementations MUST validate the levels against the entry side and
        refuse rather than submit an inverted bracket.

        CIRO: only US-listed securities may be traded through an automated API
        route. Callers are responsible for enforcing that (see
        `trade_manager._is_canadian_listed`).
        """

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by venue order ID."""

    @abstractmethod
    async def cancel_open_orders(self, ticker: str, account_id: str = "") -> int:
        """
        Cancel every working order for `ticker`. Returns how many were cancelled.

        Required before submitting a manual exit on a bracketed position: the
        bracket's stop and target are still live, so an additional sell would
        risk closing the position twice — once by our order and again when the
        stop triggers, leaving an unintended short.
        """

    @abstractmethod
    async def has_open_orders(self, ticker: str, account_id: str = "") -> bool:
        """
        True if any order for `ticker` is still working.

        Used to confirm a bracket was actually cancelled before a closing order
        is submitted. Cancellation can silently fail — a read-only API session
        refuses cancels just as it refuses orders — and submitting a sell while
        a stop leg is still live risks closing the position twice.
        """

    # ── Read-only state ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_account_summary(self, account_id: str = "") -> AccountSummary:
        """Account equity snapshot. Returns a disconnected summary on failure."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Open positions as reported by the venue (not the local trades collection)."""

    @abstractmethod
    async def get_order_statuses(self, account_id: str = "") -> dict[str, OrderStatus]:
        """
        Current state of every order the venue still knows about, keyed by
        order ID.

        Submission and fill are separate events, and nothing pushes the second
        one to us — an order logged as PENDING stays PENDING forever unless
        something asks. That gap left every trade record stuck at PENDING with
        no fill price, so realised P&L was never computed and the daily-loss
        guard summed an empty set.

        Absence from the mapping is not "unfilled": venues age orders out of
        their working set once complete. Callers must treat a missing ID as
        unknown and fall back to position state, never as a cancellation.
        """

    @abstractmethod
    async def get_fills(self, lookback_minutes: int = 1440) -> list[Fill]:
        """
        Executions from roughly the last `lookback_minutes`, newest last.

        Needed to price exits the agent did not submit: a bracket leg firing
        closes the position without any order of ours completing, so the fill
        log is the only place the exit price exists.

        Best-effort and bounded — IBKR only serves same-session executions over
        the API, so a long-closed trade may never be priced this way. Callers
        must tolerate an empty list.
        """
