"""
Broker Service — venue-agnostic facade
──────────────────────────────────────
Thin module-level API over a `BrokerAdapter`, so callers (`trade_manager`,
the `/trading` routes, app lifespan) stay unaware of which venue is active.
Swap venues with `BROKER_PROVIDER=ibkr|alpaca` — no caller changes.

One shared connection serves all auto-trade requests; auto-trading is
effectively single-account (the account configured on the server).

CIRO Note: API-based automated order submission is only permitted for
US-listed securities. Canadian-exchange securities must NOT be traded via
this service — enforced in `trade_manager._is_canadian_listed`.
"""
from __future__ import annotations

import asyncio
import random
from typing import Optional

from app.services.brokers import BrokerAdapter, BrokerConfig, build_adapter
from app.utils.logger import get_logger

logger = get_logger(__name__)

_adapter: Optional[BrokerAdapter] = None
_reconnect_task: Optional[asyncio.Task] = None

# Reconnect backoff. IB Gateway restarts daily (AUTO_RESTART_TIME) and takes
# ~2 minutes to come back, so retries start quick and then back off rather
# than hammering a gateway that is mid-login.
_RECONNECT_MIN_SECONDS = 15
_RECONNECT_MAX_SECONDS = 300


def _build_from_settings() -> tuple[str, BrokerConfig]:
    from app.config import get_settings

    s = get_settings()
    provider = getattr(s, "broker_provider", "ibkr")
    return provider, BrokerConfig(
        host=s.ibkr_host,
        port=s.ibkr_port,
        client_id=s.ibkr_client_id,
        account_id=s.ibkr_account_id,
        # Reflects which gateway session is actually running (TRADING_MODE), not
        # whether live trading is permitted (AUTO_TRADE_LIVE_ALLOWED). Deriving
        # it from the permission flag would log a live session as "paper".
        paper=not getattr(s, "is_live_trading", False),
        api_key=getattr(s, "alpaca_api_key", ""),
        api_secret=getattr(s, "alpaca_api_secret", ""),
        base_url=getattr(s, "alpaca_base_url", ""),
    )


def get_adapter() -> Optional[BrokerAdapter]:
    """Return the live adapter (None until `connect()` has been called)."""
    return _adapter


def provider_name() -> str:
    return _adapter.name if _adapter else "none"


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def connect(
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
) -> bool:
    """
    Build the configured adapter and open a session. Called on app startup.
    Returns True on success. Never raises.

    host/port/client_id are optional overrides retained for backwards
    compatibility with the previous call signature; when omitted the values
    come from settings.
    """
    global _adapter

    provider, config = _build_from_settings()
    if host is not None:
        config.host = host
    if port is not None:
        config.port = port
    if client_id is not None:
        config.client_id = client_id

    if _adapter is None:
        _adapter = build_adapter(provider, config)
        logger.info(
            "broker_adapter_selected",
            provider=_adapter.name, host=config.host, port=config.port,
        )
    else:
        _adapter.config = config

    return await _adapter.connect()


async def _reconnect_loop() -> None:
    """Retry the broker session with exponential backoff while disconnected."""
    delay = _RECONNECT_MIN_SECONDS
    try:
        while True:
            await asyncio.sleep(delay)
            if is_connected():
                delay = _RECONNECT_MIN_SECONDS
                continue

            logger.info("broker_reconnect_attempt", provider=provider_name(), delay=delay)
            if await connect():
                delay = _RECONNECT_MIN_SECONDS
            else:
                # Backoff with jitter so a restarting gateway isn't hammered.
                delay = min(delay * 2, _RECONNECT_MAX_SECONDS)
                delay = int(delay * (0.8 + random.random() * 0.4))
    except asyncio.CancelledError:
        logger.info("broker_reconnect_loop_stopped")
        raise
    except Exception as exc:
        # A crash here would silently end all reconnection for the process.
        logger.error("broker_reconnect_loop_crashed", error=str(exc))


def start_reconnect_loop() -> None:
    """Start the background reconnect loop. Called once after app startup."""
    global _reconnect_task
    if _reconnect_task is None or _reconnect_task.done():
        _reconnect_task = asyncio.create_task(_reconnect_loop())


def stop_reconnect_loop() -> None:
    """Cancel the background reconnect loop. Called on app shutdown."""
    global _reconnect_task
    if _reconnect_task is not None:
        _reconnect_task.cancel()
        _reconnect_task = None


async def disconnect() -> None:
    """Close the broker session. Called on app shutdown. Idempotent."""
    global _adapter
    if _adapter is not None:
        await _adapter.disconnect()
    _adapter = None


def is_connected() -> bool:
    return bool(_adapter is not None and _adapter.is_connected())


# ── Trading ───────────────────────────────────────────────────────────────────

async def place_limit_order(
    ticker: str,
    action: str,
    qty: int,
    limit_price: float,
    account_id: str = "",
    exchange: str = "SMART",
    currency: str = "USD",
    stop_loss_price: Optional[float] = None,
    take_profit_price: Optional[float] = None,
) -> Optional[str]:
    """
    Place a limit order. Returns the venue order ID (str) or None on failure.
    Supplying both stop and target submits a bracket; the ID returned is the
    entry order's.
    """
    if _adapter is None:
        logger.error("broker_not_configured", ticker=ticker)
        return None
    return await _adapter.place_limit_order(
        ticker, action, qty, limit_price,
        account_id=account_id, exchange=exchange, currency=currency,
        stop_loss_price=stop_loss_price, take_profit_price=take_profit_price,
    )


async def cancel_order(order_id: str) -> bool:
    """Cancel an open order by venue order ID."""
    if _adapter is None:
        return False
    return await _adapter.cancel_order(str(order_id))


async def cancel_open_orders(ticker: str, account_id: str = "") -> int:
    """
    Cancel every working order for `ticker`; returns the count.
    Call before submitting a manual exit so a live bracket leg cannot close the
    position a second time.
    """
    if _adapter is None:
        return 0
    return await _adapter.cancel_open_orders(ticker, account_id=account_id)


async def has_open_orders(ticker: str, account_id: str = "") -> bool:
    """True if any order for `ticker` is still working at the broker."""
    if _adapter is None:
        return False
    return await _adapter.has_open_orders(ticker, account_id=account_id)


async def get_account_summary(account_id: str = "") -> dict:
    """
    Account snapshot as a plain dict with keys: connected, net_liquidation,
    total_cash, unrealized_pnl, realized_pnl, buying_power.
    """
    from app.services.brokers.base import AccountSummary

    if _adapter is None:
        return AccountSummary().as_dict()
    summary = await _adapter.get_account_summary(account_id=account_id)
    return summary.as_dict()


async def get_positions() -> list[dict]:
    """Open positions as reported by the broker."""
    if _adapter is None:
        return []
    return [p.as_dict() for p in await _adapter.get_positions()]
