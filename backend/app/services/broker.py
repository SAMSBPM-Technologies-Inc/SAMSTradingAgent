"""
IBKR Broker Service — per-user connection pool
────────────────────────────────────────────────
Each user runs their own IB Gateway (or TWS) instance.
This module maintains a pool of ib_insync.IB connections keyed by user_id
and routes all broker calls through the correct per-user connection.

User-side setup (Option C):
  1. Install IB Gateway on a machine the user controls.
  2. Enable API access: File → Global Configuration → API → Settings
     - Enable ActiveX and Socket Clients ✓
     - Socket port: 7497 (paper) or 7496 (live)
     - Uncheck "Read-Only API" for order submission
  3. Enter the host (IP or hostname) + port in their SAMS profile.

CIRO Note: API-based automated order submission is only permitted for
US-listed securities. Canadian-exchange securities must NOT be traded
via this service.
"""
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Per-user connection pool: user_id -> ib_insync.IB instance
_pool: dict[str, object] = {}


def _make_ib():
    """Lazy-import ib_insync so the app starts even if the package is absent."""
    try:
        from ib_insync import IB
        return IB()
    except ImportError:
        logger.warning("ib_insync_not_installed", hint="pip install ib-insync")
        return None


async def _get_connection(user_id: str, host: str, port: int) -> Optional[object]:
    """Return an active IB connection for this user, reconnecting if stale."""
    existing = _pool.get(user_id)
    if existing and existing.isConnected():
        return existing

    ib = _make_ib()
    if ib is None:
        return None

    try:
        await ib.connectAsync(host, port, clientId=1, timeout=10)
        _pool[user_id] = ib
        logger.info("ibkr_user_connected", user_id=user_id, host=host, port=port)
        return ib
    except Exception as exc:
        logger.warning("ibkr_user_connect_failed", user_id=user_id, host=host, port=port, error=str(exc))
        return None


def is_user_connected(user_id: str) -> bool:
    ib = _pool.get(user_id)
    return bool(ib and ib.isConnected())


async def check_connection(user_id: str, host: str, port: int) -> bool:
    """Attempt to connect (or reuse) and return True if successful."""
    ib = await _get_connection(user_id, host, port)
    return ib is not None


async def place_limit_order(
    user_id: str,
    host: str,
    port: int,
    ticker: str,
    action: str,
    qty: int,
    limit_price: float,
    account_id: str = "",
    exchange: str = "SMART",
    currency: str = "USD",
) -> Optional[int]:
    """
    Place a limit order via the user's IB Gateway.
    Returns the IBKR order ID or None on failure.
    Only US-listed securities (SMART routing, USD) are supported.
    """
    ib = await _get_connection(user_id, host, port)
    if ib is None:
        logger.error("ibkr_not_connected", user_id=user_id, ticker=ticker)
        return None

    try:
        from ib_insync import LimitOrder, Stock
        contract = Stock(ticker, exchange, currency)
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            logger.error("ibkr_contract_not_found", ticker=ticker)
            return None

        order = LimitOrder(action, qty, round(limit_price, 2))
        if account_id:
            order.account = account_id

        trade = ib.placeOrder(qualified[0], order)
        order_id = trade.order.orderId
        logger.info(
            "ibkr_order_placed",
            user_id=user_id, ticker=ticker, action=action,
            qty=qty, limit_price=limit_price, order_id=order_id,
            account_id=account_id or "default",
        )
        return order_id
    except Exception as exc:
        logger.error("ibkr_place_order_failed", user_id=user_id, ticker=ticker, error=str(exc))
        return None


async def cancel_order(user_id: str, host: str, port: int, order_id: int) -> bool:
    """Cancel an open order by IBKR order ID."""
    ib = await _get_connection(user_id, host, port)
    if ib is None:
        return False
    try:
        from ib_insync import Order
        order = Order()
        order.orderId = order_id
        ib.cancelOrder(order)
        logger.info("ibkr_order_cancelled", user_id=user_id, order_id=order_id)
        return True
    except Exception as exc:
        logger.error("ibkr_cancel_order_failed", user_id=user_id, order_id=order_id, error=str(exc))
        return False


async def get_account_summary(
    user_id: str,
    host: str,
    port: int,
    account_id: str = "",
) -> dict:
    """
    Fetch account summary from the user's IB Gateway.
    Returns dict with: net_liquidation, total_cash, unrealized_pnl,
                       realized_pnl, buying_power, connected.
    """
    _empty = {
        "connected": False,
        "net_liquidation": 0.0, "total_cash": 0.0,
        "unrealized_pnl": 0.0, "realized_pnl": 0.0, "buying_power": 0.0,
    }

    ib = await _get_connection(user_id, host, port)
    if ib is None:
        return _empty

    try:
        summary = ib.accountSummary(account=account_id) if account_id else ib.accountSummary()
        values: dict = {}
        for item in summary:
            try:
                values[item.tag] = float(item.value) if item.value else 0.0
            except (ValueError, TypeError):
                pass
        return {
            "connected": True,
            "net_liquidation": values.get("NetLiquidation", 0.0),
            "total_cash": values.get("TotalCashValue", 0.0),
            "unrealized_pnl": values.get("UnrealizedPnL", 0.0),
            "realized_pnl": values.get("RealizedPnL", 0.0),
            "buying_power": values.get("BuyingPower", 0.0),
        }
    except Exception as exc:
        logger.error("ibkr_account_summary_failed", user_id=user_id, error=str(exc))
        return _empty


async def get_positions(user_id: str, host: str, port: int) -> list[dict]:
    """Fetch open positions from the user's IB Gateway."""
    ib = _pool.get(user_id)
    if ib is None or not ib.isConnected():
        return []
    try:
        result = []
        for pos in ib.positions():
            result.append({
                "ticker": pos.contract.symbol,
                "qty": pos.position,
                "avg_cost": pos.avgCost,
                "market_value": getattr(pos, "marketValue", None),
                "unrealized_pnl": getattr(pos, "unrealizedPNL", None),
            })
        return result
    except Exception as exc:
        logger.error("ibkr_positions_failed", user_id=user_id, error=str(exc))
        return []


def disconnect_user(user_id: str) -> None:
    """Disconnect and remove a user's IB connection from the pool."""
    ib = _pool.pop(user_id, None)
    if ib and ib.isConnected():
        ib.disconnect()
        logger.info("ibkr_user_disconnected", user_id=user_id)


def disconnect_all() -> None:
    """Disconnect all pooled connections. Called on app shutdown."""
    for user_id in list(_pool.keys()):
        disconnect_user(user_id)
