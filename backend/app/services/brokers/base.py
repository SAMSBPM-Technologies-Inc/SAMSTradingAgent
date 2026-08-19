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
    ) -> str | None:
        """
        Submit a day limit order. Returns the venue order ID, or None on failure.

        CIRO: only US-listed securities may be traded through an automated API
        route. Callers are responsible for enforcing that (see
        `trade_manager._is_canadian_listed`).
        """

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by venue order ID."""

    # ── Read-only state ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_account_summary(self, account_id: str = "") -> AccountSummary:
        """Account equity snapshot. Returns a disconnected summary on failure."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Open positions as reported by the venue (not the local trades collection)."""
