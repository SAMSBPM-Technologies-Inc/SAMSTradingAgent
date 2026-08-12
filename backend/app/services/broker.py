"""
IBKR Broker Service
────────────────────
Wraps ib_insync to provide an async interface for:
  - Connecting to IB Gateway / TWS
  - Placing and cancelling limit orders
  - Fetching account summary and positions

TWS / IB Gateway must be running locally (or via Docker on the same network)
with API access enabled. Configure via env vars:
  IBKR_HOST     (default: 127.0.0.1)
  IBKR_PORT     (default: 7497  — paper trading)  live = 7496
  IBKR_CLIENT_ID (default: 1)

CIRO Note: API-based automated order submission is only permitted for
US-listed securities. Canadian-exchange securities must NOT be traded
via this service (regulatory requirement for Canadian residents).
"""
import asyncio
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Singleton IB instance ─────────────────────────────────────────────────────

_ib = None          # ib_insync.IB instance (lazy-loaded)
_connected = False
_last_host: str = "127.0.0.1"
_last_port: int = 4002
_last_client_id: int = 1


def _get_ib():
    """Lazy-import ib_insync so the app starts even if the package is absent."""
    global _ib
    if _ib is None:
        try:
            from ib_insync import IB
            _ib = IB()
        except ImportError:
            logger.warning("ib_insync_not_installed", hint="pip install ib-insync")
            return None
    return _ib


async def _ensure_connected() -> bool:
    """
    Verify the connection is alive; attempt reconnect using last known address
    if disconnected. This handles IB Gateway restarts gracefully.
    """
    global _connected
    ib = _get_ib()
    if ib is None:
        return False
    if ib.isConnected():
        return True
    # Gateway may have restarted — try reconnecting transparently
    logger.info("ibkr_reconnecting", host=_last_host, port=_last_port)
    return await connect(_last_host, _last_port, _last_client_id)


async def connect(host: str = "127.0.0.1", port: int = 4002, client_id: int = 1) -> bool:
    """
    Connect to IB Gateway / TWS. Returns True on success.
    Port 4002 = paper trading (Docker), 4001 = live (Docker).
    Port 7497 = paper trading (local TWS), 7496 = live (local TWS).
    Safe to call multiple times — no-op if already connected.
    """
    global _connected, _last_host, _last_port, _last_client_id
    ib = _get_ib()
    if ib is None:
        return False
    if ib.isConnected():
        _connected = True
        return True
    # Save for reconnect attempts
    _last_host, _last_port, _last_client_id = host, port, client_id
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=10)
        _connected = True
        logger.info("ibkr_connected", host=host, port=port, client_id=client_id)
        return True
    except Exception as exc:
        _connected = False
        logger.warning("ibkr_connect_failed", host=host, port=port, error=str(exc))
        return False


def disconnect() -> None:
    global _connected
    ib = _get_ib()
    if ib and ib.isConnected():
        ib.disconnect()
    _connected = False
    logger.info("ibkr_disconnected")


def is_connected() -> bool:
    ib = _get_ib()
    if ib is None:
        return False
    return ib.isConnected()


async def place_limit_order(
    ticker: str,
    action: str,       # "BUY" or "SELL"
    qty: int,
    limit_price: float,
    exchange: str = "SMART",
    currency: str = "USD",
    account_id: str = "",
) -> Optional[int]:
    """
    Place a limit order. Returns the IBKR order ID or None on failure.

    NOTE: Only US-listed securities (USD, SMART routing) are supported.
    Canadian-listed securities must not be passed here (CIRO restriction).
    """
    if not await _ensure_connected():
        logger.error("ibkr_not_connected", ticker=ticker, action=action)
        return None

    ib = _get_ib()
    try:
        from ib_insync import Stock, LimitOrder
        contract = Stock(ticker, exchange, currency)
        # Qualify the contract so IBKR resolves the correct exchange
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
            ticker=ticker, action=action, qty=qty,
            limit_price=limit_price, order_id=order_id,
            account_id=account_id or "default",
        )
        return order_id
    except Exception as exc:
        logger.error("ibkr_place_order_failed", ticker=ticker, action=action, error=str(exc))
        return None


async def cancel_order(order_id: int) -> bool:
    """Cancel an open order by IBKR order ID."""
    ib = _get_ib()
    if ib is None or not ib.isConnected():
        return False
    try:
        from ib_insync import Order
        order = Order()
        order.orderId = order_id
        ib.cancelOrder(order)
        logger.info("ibkr_order_cancelled", order_id=order_id)
        return True
    except Exception as exc:
        logger.error("ibkr_cancel_order_failed", order_id=order_id, error=str(exc))
        return False


async def get_account_summary(account_id: str = "") -> dict:
    """
    Fetch account summary from IBKR.
    Returns dict with: net_liquidation, total_cash, unrealized_pnl,
                       realized_pnl, buying_power, connected.
    """
    if not await _ensure_connected():
        return {"connected": False, "net_liquidation": 0.0, "total_cash": 0.0,
                "unrealized_pnl": 0.0, "realized_pnl": 0.0, "buying_power": 0.0}

    ib = _get_ib()
    try:
        summary = ib.accountSummary(account=account_id) if account_id else ib.accountSummary()
        values: dict = {}
        for item in summary:
            values[item.tag] = float(item.value) if item.value else 0.0

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
        return {"connected": False, "net_liquidation": 0.0, "total_cash": 0.0,
                "unrealized_pnl": 0.0, "realized_pnl": 0.0, "buying_power": 0.0}


async def get_positions() -> list[dict]:
    """
    Fetch open positions from IBKR account.
    Returns list of dicts with: ticker, qty, avg_cost, market_value, unrealized_pnl.
    """
    ib = _get_ib()
    if ib is None or not ib.isConnected():
        return []
    try:
        positions = ib.positions()
        result = []
        for pos in positions:
            result.append({
                "ticker": pos.contract.symbol,
                "qty": pos.position,
                "avg_cost": pos.avgCost,
                "market_value": pos.marketValue if hasattr(pos, "marketValue") else None,
                "unrealized_pnl": pos.unrealizedPNL if hasattr(pos, "unrealizedPNL") else None,
            })
        return result
    except Exception as exc:
        logger.error("ibkr_positions_failed", error=str(exc))
        return []
