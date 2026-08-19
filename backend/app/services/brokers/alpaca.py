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

import httpx

from app.services.brokers.base import (
    AccountSummary,
    BrokerAdapter,
    BrokerConfig,
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
    ) -> str | None:
        if not self.is_connected():
            logger.error("alpaca_not_connected", ticker=ticker)
            return None
        try:
            resp = await self._client.post(
                "/v2/orders",
                json={
                    "symbol": ticker.upper(),
                    "qty": str(qty),
                    "side": action.lower(),      # "buy" / "sell"
                    "type": "limit",
                    "time_in_force": "day",
                    "limit_price": str(round(limit_price, 2)),
                    "extended_hours": False,
                    "client_order_id": None,
                },
            )
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
