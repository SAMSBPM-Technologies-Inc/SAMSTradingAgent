"""
Interactive Brokers adapter (IB Gateway + ib_async)
───────────────────────────────────────────────────
Connects over TCP to an IB Gateway instance running IBC for headless login.

PORT MODEL — the single most common misconfiguration
────────────────────────────────────────────────────
Inside the `ghcr.io/gnzsnz/ib-gateway` container IB Gateway binds its API to
**127.0.0.1 only**:  4001 = live, 4002 = paper. Those are unreachable from any
other container. The image runs `socat` to republish them on all interfaces
under different numbers:  **4003 = live, 4004 = paper**. Anything connecting
from outside the gateway container must use 4003/4004.

Why ib_async and not ib_insync
──────────────────────────────
ib_insync has been unmaintained since its author's death in early 2024;
ib_async is the API-compatible community successor. Equally important: this
adapter uses ONLY the async call paths (`*Async`). ib_insync/ib_async's
synchronous helpers (`accountSummary()`, `positions()`) internally spin the
event loop via nest_asyncio, which cannot patch uvloop — so under
`uvicorn[standard]` they raise at runtime. The app pins `--loop asyncio`
as defence in depth, but this adapter must not depend on that.

CIRO: automated API order entry is permitted for US-listed securities only.
"""
from __future__ import annotations

import asyncio

from app.services.brokers.base import (
    AccountSummary,
    BrokerAdapter,
    BrokerConfig,
    Position,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# IB "error" callbacks that are actually routine status notices. Logging these
# at error level buries the ones that matter (326 client-id clash, 502 no
# gateway, 1100 connectivity lost, 201 order rejected).
_INFO_ERROR_CODES = {
    1102,  # Connectivity restored — data maintained
    2104,  # Market data farm connection is OK
    2106,  # HMDS data farm connection is OK
    2107,  # HMDS data farm connection is inactive but should be available
    2108,  # Market data farm connection is inactive but should be available
    2119,  # Market data farm is connecting
    2158,  # Sec-def data farm connection is OK
}

# How many distinct client IDs to cycle through when reconnecting. IB Gateway
# can hold a stale client ID for minutes after an ungraceful disconnect and
# rejects re-use with error 326; rotating sidesteps that entirely.
_CLIENT_ID_ROTATION = 8


class IbkrAdapter(BrokerAdapter):
    name = "ibkr"

    def __init__(self, config: BrokerConfig) -> None:
        super().__init__(config)
        self._ib = None
        self._attempt = 0
        self._lock = asyncio.Lock()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _new_ib(self):
        """Import ib_async lazily so the app still boots if it's absent."""
        try:
            from ib_async import IB
            return IB()
        except ImportError:
            logger.error(
                "ib_async_not_installed",
                hint="pip install ib_async==2.1.0 — automated trading is disabled",
            )
            return None

    def _wire_events(self, ib) -> None:
        """
        Surface IBKR's own diagnostics. Without this the gateway can reject
        every order and the only symptom is a silent absence of fills.
        """
        def _on_error(reqId, errorCode, errorString, contract=None):
            if errorCode in _INFO_ERROR_CODES:
                logger.info("ibkr_status", code=errorCode, message=errorString)
            else:
                logger.error(
                    "ibkr_error",
                    code=errorCode,
                    message=errorString,
                    req_id=reqId,
                    symbol=getattr(contract, "symbol", None),
                )

        def _on_disconnected():
            logger.warning("ibkr_disconnected_event", host=self.config.host, port=self.config.port)

        ib.errorEvent += _on_error
        ib.disconnectedEvent += _on_disconnected

    async def connect(self) -> bool:
        """
        Open a session, rotating the client ID on each retry.
        Serialised by a lock so the reconnect loop and a manual call can't race.
        """
        async with self._lock:
            if self.is_connected():
                return True

            # Drop any half-dead handle before making a new one — the previous
            # implementation reassigned over it and leaked the socket.
            await self._close_quietly()

            ib = self._new_ib()
            if ib is None:
                return False
            self._wire_events(ib)

            client_id = self.config.client_id + (self._attempt % _CLIENT_ID_ROTATION)
            self._attempt += 1
            try:
                await ib.connectAsync(
                    self.config.host,
                    self.config.port,
                    clientId=client_id,
                    timeout=20,          # IBC login is slow; 10s was marginal
                    readonly=False,
                )
                self._ib = ib
                logger.info(
                    "ibkr_connected",
                    host=self.config.host,
                    port=self.config.port,
                    client_id=client_id,
                    paper=self.config.paper,
                    accounts=list(ib.managedAccounts() or []),
                )
                return True
            except Exception as exc:
                logger.warning(
                    "ibkr_connect_failed",
                    host=self.config.host,
                    port=self.config.port,
                    client_id=client_id,
                    error=str(exc),
                    hint=(
                        "Port must be the socat relay port (4004 paper / 4003 live), "
                        "not IB Gateway's loopback 4002/4001."
                    ),
                )
                try:
                    ib.disconnect()
                except Exception:
                    pass
                return False

    async def _close_quietly(self) -> None:
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None

    async def disconnect(self) -> None:
        async with self._lock:
            if self._ib is not None and self._ib.isConnected():
                logger.info("ibkr_disconnect")
            await self._close_quietly()

    def is_connected(self) -> bool:
        return bool(self._ib is not None and self._ib.isConnected())

    # ── Trading ──────────────────────────────────────────────────────────────

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
        if not self.is_connected():
            logger.error("ibkr_not_connected", ticker=ticker)
            return None

        # Refuse to submit into an ambiguous account. IB only defaults sanely
        # when the login manages exactly one account; with several (e.g. an
        # individual account alongside a registered one) an order without an
        # explicit account code can land in the wrong one. Failing closed is
        # the only safe behaviour for real money.
        managed = [a for a in (self._ib.managedAccounts() or []) if a]
        if not account_id and len(managed) > 1:
            logger.error(
                "ibkr_ambiguous_account_for_order",
                ticker=ticker, accounts=sorted(managed),
                hint="set IBKR_ACCOUNT_ID to the account that should be traded",
            )
            return None
        if account_id and managed and account_id not in managed:
            logger.error(
                "ibkr_unknown_account", ticker=ticker,
                account_id=account_id, managed=sorted(managed),
            )
            return None

        try:
            from ib_async import LimitOrder, Stock

            contract = Stock(ticker, exchange, currency)
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.error("ibkr_contract_not_found", ticker=ticker)
                return None

            order = LimitOrder(action, qty, round(limit_price, 2))
            order.tif = "DAY"
            order.outsideRth = False
            # Tag orders so they're identifiable in TWS / account statements.
            order.orderRef = f"STA-{ticker}-{action}"
            if account_id:
                order.account = account_id

            trade = self._ib.placeOrder(qualified[0], order)

            # Give IB a moment to accept or reject. placeOrder returns
            # immediately; without this an outright rejection looks like success.
            for _ in range(20):
                await asyncio.sleep(0.1)
                status = trade.orderStatus.status
                if status in ("Cancelled", "Inactive", "ApiCancelled"):
                    reason = "; ".join(e.message for e in trade.log) or status
                    logger.error("ibkr_order_rejected", ticker=ticker, status=status, reason=reason)
                    return None
                if status in ("PreSubmitted", "Submitted", "Filled"):
                    break

            order_id = str(trade.order.orderId)
            logger.info(
                "ibkr_order_placed",
                ticker=ticker, action=action, qty=qty,
                limit_price=limit_price, order_id=order_id,
                status=trade.orderStatus.status,
                account_id=account_id or "default",
            )
            return order_id
        except Exception as exc:
            logger.error("ibkr_place_order_failed", ticker=ticker, error=str(exc))
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel by looking up the live Trade. The previous implementation built a
        bare `Order()` carrying only an orderId, which IB silently ignores —
        cancellation appeared to succeed while the order stayed working.
        """
        if not self.is_connected():
            return False
        try:
            target = str(order_id)
            for trade in self._ib.openTrades():
                if str(trade.order.orderId) == target:
                    self._ib.cancelOrder(trade.order)
                    logger.info("ibkr_order_cancelled", order_id=target)
                    return True
            logger.warning("ibkr_cancel_order_not_found", order_id=target)
            return False
        except Exception as exc:
            logger.error("ibkr_cancel_order_failed", order_id=order_id, error=str(exc))
            return False

    # ── Read-only state ──────────────────────────────────────────────────────

    async def get_account_summary(self, account_id: str = "") -> AccountSummary:
        if not self.is_connected():
            return AccountSummary()
        try:
            # MUST be accountSummaryAsync, never accountSummary. The sync form
            # unconditionally calls IB._run() -> loop.run_until_complete, which
            # raises "This event loop is already running" inside any async
            # caller — regardless of whether the summary cache is warm. Under
            # the previous code every call raised, was swallowed by the except
            # below, and returned zero equity, so trade_manager skipped every
            # trade with "Could not read account equity from IBKR".
            # accountValues/portfolio/positions/openTrades are plain cache reads
            # and are safe to call directly.
            rows = await self._ib.accountSummaryAsync(account_id or "")

            # Filter to the requested account. IB returns one row per tag PER
            # ACCOUNT, so with several managed accounts the flattening below
            # would let the last account silently overwrite the others and
            # position sizing could be computed from the wrong balance.
            if account_id:
                rows = [r for r in rows if r.account == account_id]
                if not rows:
                    rows = [r for r in self._ib.accountValues(account_id)
                            if r.account == account_id]
            elif len({r.account for r in rows if r.account}) > 1:
                logger.error(
                    "ibkr_ambiguous_account",
                    accounts=sorted({r.account for r in rows if r.account}),
                    hint="set IBKR_ACCOUNT_ID — equity and orders would target an arbitrary account",
                )
                return AccountSummary()

            values: dict[str, float] = {}
            for item in rows:
                try:
                    values[item.tag] = float(item.value) if item.value else 0.0
                except (ValueError, TypeError):
                    continue

            return AccountSummary(
                connected=True,
                net_liquidation=values.get("NetLiquidation", 0.0),
                total_cash=values.get("TotalCashValue", 0.0),
                unrealized_pnl=values.get("UnrealizedPnL", 0.0),
                realized_pnl=values.get("RealizedPnL", 0.0),
                buying_power=values.get("BuyingPower", 0.0),
            )
        except Exception as exc:
            logger.error("ibkr_account_summary_failed", error=str(exc))
            return AccountSummary()

    async def get_positions(self) -> list[Position]:
        if not self.is_connected():
            return []
        try:
            # portfolio() carries market value and unrealised PnL; positions()
            # only has size and average cost. Prefer the richer source.
            portfolio = self._ib.portfolio()
            if portfolio:
                return [
                    Position(
                        ticker=item.contract.symbol,
                        qty=item.position,
                        avg_cost=item.averageCost,
                        market_value=item.marketValue,
                        unrealized_pnl=item.unrealizedPNL,
                    )
                    for item in portfolio
                ]

            await self._ib.reqPositionsAsync()
            return [
                Position(
                    ticker=pos.contract.symbol,
                    qty=pos.position,
                    avg_cost=pos.avgCost,
                )
                for pos in self._ib.positions()
            ]
        except Exception as exc:
            logger.error("ibkr_positions_failed", error=str(exc))
            return []
