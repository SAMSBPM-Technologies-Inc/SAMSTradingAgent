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

# A group account summary carries rows under the pseudo-account "All" alongside
# the real account numbers. Counting those as accounts makes a single-account
# login look ambiguous, which blanks out the equity read and skips every trade.
_PSEUDO_ACCOUNTS = frozenset({"All", ""})

# Order statuses that mean "this will never fill".
# ValidationError is the one that matters most and is easy to miss: IB reports a
# read-only API session by *accepting* the placeOrder call and then marking the
# order ValidationError. Without it here, a fully rejected order looks placed
# and a trade record is written for an order the broker never took.
_REJECTED_STATUSES = frozenset({
    "Cancelled",
    "ApiCancelled",
    "Inactive",
    "ValidationError",
})


def _bracket_levels_valid(
    action: str, entry: float, stop: float, target: float
) -> bool:
    """
    Reject a bracket whose protective legs sit on the wrong side of the entry.

    For a BUY the stop must be below and the target above; for a SELL the
    reverse. IB would reject an inverted bracket anyway, but catching it here
    means the entry never goes out either — submitting the parent and having the
    children rejected would leave exactly the unprotected position brackets
    exist to prevent.
    """
    if entry <= 0 or stop <= 0 or target <= 0:
        return False
    if action.upper() == "BUY":
        return stop < entry < target
    if action.upper() == "SELL":
        return target < entry < stop
    return False


class IbkrAdapter(BrokerAdapter):
    name = "ibkr"

    def __init__(self, config: BrokerConfig) -> None:
        super().__init__(config)
        self._ib = None
        self._attempt = 0
        self._lock = asyncio.Lock()
        #: Latched when IB reports a read-only API session (error 321). Cleared
        #: on each new connection, since a gateway restart is what fixes it.
        self._read_only = False

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
            # 321 with this cause means IB Gateway's API is read-only: it accepts
            # placeOrder and then marks the order ValidationError. Latch it so
            # orders are refused up front with an actionable message instead of
            # each one failing individually.
            #
            # This happens on EVERY fresh gateway start: IBC unchecks the
            # Read-Only API box during login, but the API layer has already read
            # the old value, so the first session stays read-only until the
            # gateway is restarted.
            if errorCode == 321 and "Read-Only" in (errorString or ""):
                if not self._read_only:
                    logger.error(
                        "ibkr_read_only_api",
                        message=errorString,
                        hint="restart the ibgateway container — IBC's fix only "
                             "applies from the NEXT gateway start",
                    )
                self._read_only = True
                return
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
            self._read_only = False
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
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> str | None:
        if not self.is_connected():
            logger.error("ibkr_not_connected", ticker=ticker)
            return None

        if self._read_only:
            logger.error(
                "ibkr_read_only_refusing_order",
                ticker=ticker,
                hint="gateway API is read-only; restart the ibgateway container",
            )
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

            entry = round(limit_price, 2)
            stop = round(stop_loss_price, 2) if stop_loss_price else None
            target = round(take_profit_price, 2) if take_profit_price else None

            # A bracket needs both legs; IB rejects a half-formed one.
            use_bracket = stop is not None and target is not None
            if use_bracket and not _bracket_levels_valid(action, entry, stop, target):
                logger.error(
                    "ibkr_invalid_bracket",
                    ticker=ticker, action=action,
                    entry=entry, stop=stop, target=target,
                    hint="stop/target are on the wrong side of entry — refusing to submit",
                )
                return None

            # Applied to every leg. `account` in particular MUST reach the child
            # orders, or the protective legs can be routed to another account.
            common = {"tif": "DAY", "outsideRth": False}
            if account_id:
                common["account"] = account_id

            if use_bracket:
                bracket = self._ib.bracketOrder(
                    action, qty, entry, target, stop, **common
                )
                # Order matters: children reference parent.orderId, and only the
                # last leg carries transmit=True, which releases the whole set.
                parent_trade = None
                for leg, suffix in zip(bracket, ("ENTRY", "TP", "SL")):
                    leg.orderRef = f"STA-{ticker}-{action}-{suffix}"
                    placed = self._ib.placeOrder(qualified[0], leg)
                    if leg.orderId == bracket.parent.orderId:
                        parent_trade = placed
                if parent_trade is None:
                    logger.error("ibkr_bracket_parent_missing", ticker=ticker)
                    return None
                trade = parent_trade
                logger.info(
                    "ibkr_bracket_submitted",
                    ticker=ticker, entry=entry, stop=stop, target=target,
                    risk_per_share=round(abs(entry - stop), 2),
                )
            else:
                order = LimitOrder(action, qty, entry, **common)
                # Tag orders so they're identifiable in TWS / account statements.
                order.orderRef = f"STA-{ticker}-{action}"
                trade = self._ib.placeOrder(qualified[0], order)
                logger.warning(
                    "ibkr_unprotected_order",
                    ticker=ticker,
                    hint="no bracket — this position has no automatic exit",
                )

            # Give IB a moment to accept or reject. placeOrder returns
            # immediately; without this an outright rejection looks like success.
            for _ in range(20):
                await asyncio.sleep(0.1)
                status = trade.orderStatus.status
                if status in _REJECTED_STATUSES:
                    reason = "; ".join(e.message for e in trade.log if e.message) or status
                    logger.error("ibkr_order_rejected", ticker=ticker, status=status, reason=reason)
                    return None
                if status in ("PreSubmitted", "Submitted", "Filled"):
                    break
            else:
                # Never reached an accepted state within the window. Treat as a
                # failure rather than reporting a phantom order — the caller
                # records a trade against whatever ID we return.
                logger.error(
                    "ibkr_order_not_accepted",
                    ticker=ticker, status=trade.orderStatus.status,
                    reason="; ".join(e.message for e in trade.log if e.message) or "timed out",
                )
                return None

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

    async def _refresh_open_orders(self) -> None:
        """
        Pull ALL working orders for the account into the local cache.

        `openTrades()` only reports orders submitted by the CURRENT client
        session. Any bracket placed before the last reconnect — and the client
        id rotates on every reconnect — is invisible without this. That blind
        spot is dangerous: has_open_orders would report "nothing working" while
        a stop leg was live, and the exit path would sell into it.
        """
        try:
            await self._ib.reqAllOpenOrdersAsync()
        except Exception as exc:
            logger.warning("ibkr_req_all_open_orders_failed", error=str(exc))

    async def cancel_open_orders(self, ticker: str, account_id: str = "") -> int:
        """Cancel all working orders for `ticker` — including live bracket legs."""
        if not self.is_connected():
            return 0
        try:
            symbol = ticker.upper()
            await self._refresh_open_orders()

            def _working() -> list:
                return [
                    t for t in self._ib.openTrades()
                    if getattr(t.contract, "symbol", "").upper() == symbol
                    and (not account_id
                         or getattr(t.order, "account", "") in ("", account_id))
                ]

            before = _working()
            if not before:
                return 0
            for trade in before:
                self._ib.cancelOrder(trade.order)

            # Give IB time to process before anything is submitted against the
            # same position, then count what ACTUALLY left the working set —
            # cancelOrder is fire-and-forget and can itself be rejected (a
            # read-only API session refuses cancels too).
            await asyncio.sleep(1.5)
            remaining = _working()
            cancelled = len(before) - len(remaining)

            if remaining:
                logger.error(
                    "ibkr_cancel_open_orders_incomplete",
                    ticker=symbol, requested=len(before), cancelled=cancelled,
                    still_working=len(remaining),
                    hint="protective legs are still live — do NOT submit a closing order",
                )
            else:
                logger.info("ibkr_open_orders_cancelled", ticker=symbol, count=cancelled)
            return cancelled
        except Exception as exc:
            logger.error("ibkr_cancel_open_orders_failed", ticker=ticker, error=str(exc))
            return 0

    async def has_open_orders(self, ticker: str, account_id: str = "") -> bool:
        if not self.is_connected():
            return False
        await self._refresh_open_orders()
        symbol = ticker.upper()
        return any(
            getattr(t.contract, "symbol", "").upper() == symbol
            and (not account_id or getattr(t.order, "account", "") in ("", account_id))
            for t in self._ib.openTrades()
        )

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

            # Resolve which account this snapshot describes, then keep only its
            # rows. IB returns one row per tag PER ACCOUNT, so flattening across
            # accounts would let the last one silently win and position sizing
            # could be computed from the wrong balance.
            #
            # `_REAL_ACCOUNTS` filtering matters: a group summary also carries
            # rows under the pseudo-account "All", which is not a tradable
            # account. Counting it made a single-account login look ambiguous.
            real = {r.account for r in rows if r.account and r.account not in _PSEUDO_ACCOUNTS}

            if account_id:
                target = account_id
            elif len(real) == 1:
                target = next(iter(real))
            elif len(real) > 1:
                logger.error(
                    "ibkr_ambiguous_account",
                    accounts=sorted(real),
                    hint="set IBKR_ACCOUNT_ID — equity and orders would target an arbitrary account",
                )
                return AccountSummary()
            else:
                target = ""

            if target:
                scoped = [r for r in rows if r.account == target]
                if not scoped:
                    scoped = [r for r in self._ib.accountValues(target)
                              if r.account == target]
                rows = scoped

            values: dict[str, float] = {}
            for item in rows:
                try:
                    values[item.tag] = float(item.value) if item.value else 0.0
                except (ValueError, TypeError):
                    continue

            # UnrealizedPnL is not part of the account-summary tag set; it comes
            # from the portfolio subscription. Sum it there, scoped to the same
            # account, so the dashboard's P&L matches the positions it lists.
            resolved = target or next(
                (r.account for r in rows
                 if r.account and r.account not in _PSEUDO_ACCOUNTS), ""
            )
            unrealized = values.get("UnrealizedPnL")
            realized = values.get("RealizedPnL")
            if unrealized is None or realized is None:
                pf = [p for p in self._ib.portfolio() if not resolved or p.account == resolved]
                if unrealized is None:
                    unrealized = sum(p.unrealizedPNL or 0.0 for p in pf)
                if realized is None:
                    realized = sum(p.realizedPNL or 0.0 for p in pf)

            return AccountSummary(
                connected=True,
                net_liquidation=values.get("NetLiquidation", 0.0),
                total_cash=values.get("TotalCashValue", 0.0),
                unrealized_pnl=unrealized or 0.0,
                realized_pnl=realized or 0.0,
                buying_power=values.get("BuyingPower", 0.0),
                account_id=resolved,
                gross_position_value=values.get("GrossPositionValue", 0.0),
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
