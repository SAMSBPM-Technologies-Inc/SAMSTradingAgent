"""
Pydantic models for automated trade execution.
"""
from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel, Field

# Venue order IDs: IBKR emits ints, Alpaca emits UUID strings. A union keeps
# trade documents written before the multi-broker change readable — Pydantic v2
# does not coerce int → str, so narrowing to `str` would break historical rows.
OrderId = Union[int, str]


class AutoTradeSettings(BaseModel):
    """Per-user settings for automated trade execution."""
    enabled: bool = False
    paper_trading: bool = True                    # True = paper account; False = live (requires explicit opt-in)
    min_signal_score: float = Field(default=0.75, ge=0.0, le=1.0)
    position_size_pct: float = Field(default=0.05, ge=0.001, le=0.25)  # fraction of account equity per trade
    max_open_positions: int = Field(default=5, ge=1, le=50)
    max_daily_loss_pct: float = Field(default=0.02, ge=0.001, le=0.20)  # daily drawdown kill-switch
    allowed_tickers: list[str] = []               # empty = all watchlist tickers; non-empty = whitelist


class AutoTradeSettingsResponse(AutoTradeSettings):
    connected: bool = False   # whether IB Gateway is reachable right now


class TradeStatus:
    PENDING   = "PENDING"    # order submitted, awaiting fill
    FILLED    = "FILLED"     # order fully filled
    PARTIAL   = "PARTIAL"    # order partially filled
    CANCELLED = "CANCELLED"  # order cancelled
    REJECTED  = "REJECTED"   # rejected by broker
    SKIPPED   = "SKIPPED"    # risk guard prevented submission


class TradeRecord(BaseModel):
    """A single automated trade (entry or exit)."""
    user_id: str
    ticker: str
    action: str                         # "BUY" or "SELL"
    qty: int
    limit_price: float
    order_id: Optional[OrderId] = None  # venue order ID (IBKR int / Alpaca UUID)
    status: str = TradeStatus.PENDING
    reason: Optional[str] = None        # skip/reject reason
    signal_score: Optional[float] = None
    signal_type: Optional[str] = None   # "BUY" | "SELL" | "EXIT_ALERT"
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    is_paper: bool = True
    opened_at: datetime
    closed_at: Optional[datetime] = None


class TradeResponse(BaseModel):
    """API response shape for a trade record."""
    id: str
    user_id: str
    ticker: str
    action: str
    qty: int
    limit_price: float
    order_id: Optional[OrderId] = None
    status: str
    reason: Optional[str] = None
    signal_score: Optional[float] = None
    signal_type: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    is_paper: bool
    opened_at: datetime
    closed_at: Optional[datetime] = None


class AccountSummaryResponse(BaseModel):
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    buying_power: float = 0.0
    connected: bool = False
