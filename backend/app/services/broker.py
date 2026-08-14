"""
IBKR Broker Service — singleton server-level connection
────────────────────────────────────────────────────────
One IB Gateway connection shared across all auto-trade requests.
Configured via env vars: IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IBKR_ACCOUNT_ID.

IB Gateway must be running on the same server (127.0.0.1) or a reachable host.
Auto-trading is effectively single-user: all orders go through this connection.

CIRO Note: API-based automated order submission is only permitted for
US-listed securities. Canadian-exchange securities must NOT be traded
via this service.
"""
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_ib: Optional[object] = None


def _make_ib():
    """Lazy-import ib_insync so the app starts even if the package is absent."""
    try:
        from ib_insync import IB
        return IB()
    except ImportError:
        logger.warning("ib_insync_not_installed", hint="pip install ib-insync")
        return None


async def connect(host: str = "127.0.0.1", port: int = 4002, client_id: int = 1) -> bool:
    """Connect to IB Gateway. Called on app startup. Returns True on success."""
    global _ib
    ib = _make_ib()
    if ib is None:
        return False
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=10)
        _ib = ib
        logger.info("ibkr_connected", host=host, port=port)
        return True
    except Exception as exc:
        logger.warning("ibkr_connect_failed", host=host, port=port, error=str(exc))
        return False


def disconnect() -> None:
    """Disconnect from IB Gateway. Called on app shutdown."""
    global _ib
    if _ib and _ib.isConnected():
        _ib.disconnect()
        logger.info("ibkr_disconnected")
    _ib = None


def is_connected() -> bool:
    return bool(_ib and _ib.isConnected())


async def place_limit_order(
    ticker: str,
    action: str,
    qty: int,
    limit_price: float,
    account_id: str = "",
    exchange: str = "SMART",
    currency: str = "USD",
) -> Optional[int]:
    """
    Place a limit order via IB Gateway.
    Returns the IBKR order ID or None on failure.
    Only US-listed securities (SMART routing, USD) are supported.
    """
    if not is_connected():
        logger.error("ibkr_not_connected", ticker=ticker)
        return None
    try:
        from ib_insync import LimitOrder, Stock
        contract = Stock(ticker, exchange, currency)
        qualified = await _ib.qualifyContractsAsync(contract)
        if not qualified:
            logger.error("ibkr_contract_not_found", ticker=ticker)
            return None

        order = LimitOrder(action, qty, round(limit_price, 2))
        if account_id:
            order.account = account_id

        trade = _ib.placeOrder(qualified[0], order)
        order_id = trade.order.orderId
        logger.info(
            "ibkr_order_placed",
            ticker=ticker, action=action,
            qty=qty, limit_price=limit_price, order_id=order_id,
            account_id=account_id or "default",
        )
        return order_id
    except Exception as exc:
        logger.error("ibkr_place_order_failed", ticker=ticker, error=str(exc))
        return None


async def cancel_order(order_id: int) -> bool:
    """Cancel an open order by IBKR order ID."""
    if not is_connected():
        return False
    try:
        from ib_insync import Order
        order = Order()
        order.orderId = order_id
        _ib.cancelOrder(order)
        logger.info("ibkr_order_cancelled", order_id=order_id)
        return True
    except Exception as exc:
        logger.error("ibkr_cancel_order_failed", order_id=order_id, error=str(exc))
        return False


async def get_account_summary(account_id: str = "") -> dict:
    """
    Fetch account summary from IB Gateway.
    Returns dict with: net_liquidation, total_cash, unrealized_pnl,
                       realized_pnl, buying_power, connected.
    """
    _empty = {
        "connected": False,
        "net_liquidation": 0.0, "total_cash": 0.0,
        "unrealized_pnl": 0.0, "realized_pnl": 0.0, "buying_power": 0.0,
    }
    if not is_connected():
        return _empty
    try:
        summary = _ib.accountSummary(account=account_id) if account_id else _ib.accountSummary()
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
        logger.error("ibkr_account_summary_failed", error=str(exc))
        return _empty


async def get_positions() -> list[dict]:
    """Fetch open positions from IB Gateway."""
    if not is_connected():
        return []
    try:
        result = []
        for pos in _ib.positions():
            result.append({
                "ticker": pos.contract.symbol,
                "qty": pos.position,
                "avg_cost": pos.avgCost,
                "market_value": getattr(pos, "marketValue", None),
                "unrealized_pnl": getattr(pos, "unrealizedPNL", None),
            })
        return result
    except Exception as exc:
        logger.error("ibkr_positions_failed", error=str(exc))
        return []
