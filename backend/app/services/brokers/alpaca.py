"""
Alpaca adapter (REST) — fallback / alternative execution venue
──────────────────────────────────────────────────────────────
Exists so the agent is not structurally tied to IB Gateway. Alpaca needs no
gateway process, no daily re-authentication, and no 2FA — the failure modes
that cap how autonomous an IBKR-based agent can be.

Enable with:  BROKER_PROVIDER=alpaca, ALPACA_API_KEY, ALPACA_API_SECRET
Paper trading uses https://paper-api.alpaca.markets (the default).

Built on httpx, which is already a dependency — no new package required.

⚠️  STATUS: written against Alpaca's documented v2 REST contract but NOT yet
    exercised against a live Alpaca account. Validate in paper mode before
    routing any real capital through it.

Scope: US equities only, which lines up with the CIRO constraint the trade
manager already enforces.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.services.brokers.base import (
    AccountSummary,
    BrokerAdapter,
    BrokerConfig,
    Fill,
    OrderStatus,
    Position,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PAPER_URL = "https://paper-api.alpaca.markets"
_LIVE_URL = "https://api.alpaca.markets"


def _f(value, default: float = 0.0) -> float:
    """Alpaca returns numerics as JSON strings; some fields may be null."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"

    def __init__(self, config: BrokerConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    def _base_url(self) -> str:
        if self.config.base_url:
            return self.config.base_url.rstrip("/")
        return _PAPER_URL if self.config.paper else _LIVE_URL

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Alpaca is stateless HTTP — "connecting" means proving the credentials
        work, so `is_connected()` reflects something real rather than always
        returning True.
        """
        if not self.config.api_key or not self.config.api_secret:
            logger.error("alpaca_credentials_missing", hint="set ALPACA_API_KEY / ALPACA_API_SECRET")
            return False
        try:
            self._client = httpx.AsyncClient(
                base_url=self._base_url(),
                headers={
                    "APCA-API-KEY-ID": self.config.api_key,
                    "APCA-API-SECRET-KEY": self.config.api_secret,
                },
                timeout=15.0,
            )
            resp = await self._client.get("/v2/account")
            resp.raise_for_status()
            account = resp.json()
            self._connected = True
            logger.info(
                "alpaca_connected",
                paper=self.config.paper,
                account_number=account.get("account_number"),
                status=account.get("status"),
            )
            return True
        except Exception as exc:
            logger.warning("alpaca_connect_failed", base_url=self._base_url(), error=str(exc))
            await self._close_quietly()
            return False

    async def _close_quietly(self) -> None:
        self._connected = False
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def disconnect(self) -> None:
        if self._connected:
            logger.info("alpaca_disconnect")
        await self._close_quietly()

    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ── Trading ──────────────────────────────────────────────────────────────

    async def place_limit_order(
        self,
        ticker: str,
        action: str,
        qty: int,
        limit_price: float,
        account_id: str = "",
        exchange: str = "SMART",   # unused — Alpaca routes internally
        currency: str = "USD",     # unused — USD only
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> str | None:
        if not self.is_connected():
            logger.error("alpaca_not_connected", ticker=ticker)
            return None
        try:
            entry = round(limit_price, 2)
            stop = round(stop_loss_price, 2) if stop_loss_price else None
            target = round(take_profit_price, 2) if take_profit_price else None

            payload: dict = {
                "symbol": ticker.upper(),
                "qty": str(qty),
                "side": action.lower(),      # "buy" / "sell"
                "type": "limit",
                "time_in_force": "day",
                "limit_price": str(entry),
                "extended_hours": False,
            }

            # Alpaca expresses brackets natively via order_class, which is
            # simpler than IB's parent/child linkage — one request, one order ID.
            if stop is not None and target is not None:
                ok = (stop < entry < target) if action.upper() == "buy".upper() \
                    else (target < entry < stop)
                if not ok:
                    logger.error(
                        "alpaca_invalid_bracket",
                        ticker=ticker, entry=entry, stop=stop, target=target,
                    )
                    return None
                payload["order_class"] = "bracket"
                payload["take_profit"] = {"limit_price": str(target)}
                payload["stop_loss"] = {"stop_price": str(stop)}
            else:
                logger.warning(
                    "alpaca_unprotected_order",
                    ticker=ticker,
                    hint="no bracket — this position has no automatic exit",
                )

            resp = await self._client.post("/v2/orders", json=payload)
            if resp.status_code >= 400:
                logger.error(
                    "alpaca_order_rejected",
                    ticker=ticker, status=resp.status_code, body=resp.text[:500],
                )
                return None
            order = resp.json()
            order_id = str(order.get("id", ""))
            logger.info(
                "alpaca_order_placed",
                ticker=ticker, action=action, qty=qty,
                limit_price=limit_price, order_id=order_id,
                status=order.get("status"),
            )
            return order_id or None
        except Exception as exc:
            logger.error("alpaca_place_order_failed", ticker=ticker, error=str(exc))
            return None

    async def place_protective_orders(
        self,
        ticker: str,
        qty: int,
        stop_price: float,
        target_price: float,
        account_id: str = "",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> str | None:
        """
        Stop and target on an existing holding, as an OCO pair.

        Alpaca expresses this natively: `order_class=oco` with both legs on one
        sell request, which is exactly the semantics required — a fill on one
        cancels the other.
        """
        if not self.is_connected():
            logger.error("alpaca_not_connected", ticker=ticker)
            return None
        if qty < 1 or not (0 < stop_price < target_price):
            logger.error(
                "alpaca_invalid_protective_levels",
                ticker=ticker, qty=qty, stop=stop_price, target=target_price,
            )
            return None
        try:
            payload = {
                "symbol": ticker.upper(),
                "qty": str(qty),
                "side": "sell",
                "type": "limit",
                "time_in_force": "gtc",
                "order_class": "oco",
                "take_profit": {"limit_price": str(round(target_price, 2))},
                "stop_loss": {"stop_price": str(round(stop_price, 2))},
            }
            resp = await self._client.post("/v2/orders", json=payload)
            if resp.status_code >= 400:
                logger.error(
                    "alpaca_protective_rejected",
                    ticker=ticker, status=resp.status_code, body=resp.text[:500],
                )
                return None
            order_id = str(resp.json().get("id", ""))
            logger.info(
                "alpaca_protective_orders_placed",
                ticker=ticker, qty=qty,
                stop=round(stop_price, 2), target=round(target_price, 2),
                order_id=order_id,
            )
            return order_id or None
        except Exception as exc:
            logger.error("alpaca_place_protective_failed", ticker=ticker, error=str(exc))
            return None

    async def cancel_order(self, order_id: str) -> bool:
        if not self.is_connected():
            return False
        try:
            resp = await self._client.delete(f"/v2/orders/{order_id}")
            # 204 = cancelled, 404 = already gone, 422 = not cancellable
            if resp.status_code in (200, 204):
                logger.info("alpaca_order_cancelled", order_id=order_id)
                return True
            logger.warning(
                "alpaca_cancel_order_failed",
                order_id=order_id, status=resp.status_code, body=resp.text[:300],
            )
            return False
        except Exception as exc:
            logger.error("alpaca_cancel_order_failed", order_id=order_id, error=str(exc))
            return False

    async def cancel_open_orders(self, ticker: str, account_id: str = "") -> int:
        """Cancel all working orders for `ticker` — including live bracket legs."""
        if not self.is_connected():
            return 0
        try:
            symbol = ticker.upper()
            # nested=true surfaces bracket children, which are otherwise hidden
            # behind their parent and would survive cancelling the parent alone.
            resp = await self._client.get(
                "/v2/orders", params={"status": "open", "symbols": symbol, "nested": "true"}
            )
            resp.raise_for_status()

            def _ids(orders: list) -> list[str]:
                out: list[str] = []
                for o in orders:
                    out.append(str(o.get("id")))
                    out.extend(_ids(o.get("legs") or []))
                return out

            cancelled = 0
            for oid in _ids(resp.json()):
                r = await self._client.delete(f"/v2/orders/{oid}")
                if r.status_code in (200, 204):
                    cancelled += 1
            if cancelled:
                logger.info("alpaca_open_orders_cancelled", ticker=symbol, count=cancelled)
            return cancelled
        except Exception as exc:
            logger.error("alpaca_cancel_open_orders_failed", ticker=ticker, error=str(exc))
            return 0

    async def has_open_orders(self, ticker: str, account_id: str = "") -> bool:
        if not self.is_connected():
            return False
        try:
            r = await self._client.get(
                "/v2/orders",
                params={"status": "open", "symbols": ticker.upper(), "nested": "true"},
            )
            r.raise_for_status()
            return len(r.json()) > 0
        except Exception as exc:
            # Fail closed: an unknown order state must not green-light a close.
            logger.error("alpaca_has_open_orders_failed", ticker=ticker, error=str(exc))
            return True

    # ── Read-only state ──────────────────────────────────────────────────────

    async def get_account_summary(self, account_id: str = "") -> AccountSummary:
        if not self.is_connected():
            return AccountSummary()
        try:
            resp = await self._client.get("/v2/account")
            resp.raise_for_status()
            a = resp.json()

            # Alpaca's account payload has no aggregate unrealised PnL field —
            # sum it from the position list instead.
            unrealized = 0.0
            try:
                pos_resp = await self._client.get("/v2/positions")
                if pos_resp.status_code == 200:
                    unrealized = sum(_f(p.get("unrealized_pl")) for p in pos_resp.json())
            except Exception:
                pass

            # "Funds in trade" — Alpaca reports long and short market value
            # separately; gross exposure is the sum of their magnitudes.
            gross = abs(_f(a.get("long_market_value"))) + abs(_f(a.get("short_market_value")))

            return AccountSummary(
                connected=True,
                net_liquidation=_f(a.get("equity")),
                total_cash=_f(a.get("cash")),
                unrealized_pnl=unrealized,
                # Realised PnL is not exposed on the account object; the local
                # trades collection is the source of truth for it.
                realized_pnl=0.0,
                buying_power=_f(a.get("buying_power")),
                account_id=str(a.get("account_number") or ""),
                gross_position_value=gross,
            )
        except Exception as exc:
            logger.error("alpaca_account_summary_failed", error=str(exc))
            return AccountSummary()

    async def get_positions(self) -> list[Position]:
        if not self.is_connected():
            return []
        try:
            resp = await self._client.get("/v2/positions")
            resp.raise_for_status()
            return [
                Position(
                    ticker=p.get("symbol", ""),
                    qty=_f(p.get("qty")),
                    avg_cost=_f(p.get("avg_entry_price")),
                    market_value=_f(p.get("market_value")),
                    unrealized_pnl=_f(p.get("unrealized_pl")),
                )
                for p in resp.json()
            ]
        except Exception as exc:
            logger.error("alpaca_positions_failed", error=str(exc))
            return []

    # ── Reconciliation ───────────────────────────────────────────────────────

    async def get_order_statuses(self, account_id: str = "") -> dict[str, OrderStatus]:
        """
        Recent orders in every state, keyed by Alpaca's order UUID.

        `account_id` is accepted for interface symmetry and ignored: Alpaca keys
        the account off the API credentials, so a client can only ever see one.
        """
        if not self.is_connected():
            return {}
        try:
            resp = await self._client.get(
                "/v2/orders",
                params={"status": "all", "limit": 500, "nested": "true"},
            )
            resp.raise_for_status()

            statuses: dict[str, OrderStatus] = {}

            def _absorb(order: dict) -> None:
                oid = str(order.get("id") or "")
                if not oid:
                    return
                filled = _f(order.get("filled_qty"))
                total = _f(order.get("qty"))
                statuses[oid] = OrderStatus(
                    order_id=oid,
                    status=str(order.get("status") or ""),
                    filled_qty=filled,
                    remaining_qty=max(0.0, total - filled),
                    avg_fill_price=_f(order.get("filled_avg_price")),
                )
                # nested=true nests bracket children under the parent; they are
                # the legs that actually close a position, so walk into them.
                for leg in order.get("legs") or []:
                    _absorb(leg)

            for order in resp.json():
                _absorb(order)
            return statuses
        except Exception as exc:
            logger.error("alpaca_order_statuses_failed", error=str(exc))
            return {}

    async def get_fills(self, lookback_minutes: int = 1440) -> list[Fill]:
        """Fill activities from the account activity log, oldest first."""
        if not self.is_connected():
            return []
        try:
            since = datetime.now(tz=timezone.utc) - timedelta(minutes=lookback_minutes)
            resp = await self._client.get(
                "/v2/account/activities/FILL",
                params={"after": since.isoformat(), "page_size": 500},
            )
            resp.raise_for_status()

            out: list[Fill] = []
            for a in resp.json():
                executed_at = None
                raw_time = a.get("transaction_time")
                if raw_time:
                    try:
                        executed_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                out.append(Fill(
                    ticker=str(a.get("symbol") or "").upper(),
                    side="BUY" if str(a.get("side", "")).lower().startswith("b") else "SELL",
                    qty=_f(a.get("qty")),
                    price=_f(a.get("price")),
                    executed_at=executed_at,
                    order_id=str(a.get("order_id") or ""),
                    exec_id=str(a.get("id") or ""),
                    # Alpaca US equities are commission-free, so 0.0 is the
                    # true figure here rather than a missing one. Reported
                    # explicitly so net P&L is computable on this venue instead
                    # of being suppressed as unknown.
                    commission=0.0,
                    commission_currency="USD",
                ))
            out.sort(key=lambda x: (x.executed_at is None, x.executed_at))
            return out
        except Exception as exc:
            logger.error("alpaca_get_fills_failed", error=str(exc))
            return []
