"""
Trade Manager
─────────────
Orchestrates signal → order flow:
  1. Reads per-user AutoTradeSettings
  2. Runs risk guards (position cap, daily loss limit, duplicate prevention)
  3. Calculates position size from account equity
  4. Places limit order via broker service
  5. Logs every attempt (including skips) to the `trades` collection

Called from pipeline._execute_trades() after a signal is generated.
"""
from datetime import datetime, timezone

from app.config import get_settings
from app.db import COLL_TRADES, COLL_USERS, get_db
from app.models.trade import AutoTradeSettings, TradeRecord, TradeStatus
from app.services import broker as ibkr
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Exchange listing for Canadian-listed tickers (CIRO restriction — cannot trade via API)
_CANADIAN_EXCHANGE_SUFFIXES = {".TO", ".V", ".CN", ".NEO"}


def _is_canadian_listed(ticker: str) -> bool:
    """Return True if ticker suffix indicates a Canadian-exchange listing."""
    return any(ticker.upper().endswith(sfx) for sfx in _CANADIAN_EXCHANGE_SUFFIXES)


def _bracket_levels(
    entry: float,
    analyst_stop: float | None,
    analyst_target: float | None,
) -> tuple[float | None, float | None]:
    """
    Resolve the protective levels for a long entry.

    Prefers the AI analyst's own stop/target, since those reflect the thesis for
    this specific setup. Falls back to fixed percentages when a level is absent
    OR fails validation — an analyst can return a stop above the entry, and
    trusting that blindly would submit an inverted bracket that IB rejects,
    leaving the position unprotected.

    Returns (stop, target), or (None, None) if bracketing is disabled.
    """
    s = get_settings()
    if not s.enable_bracket_orders or entry <= 0:
        return None, None

    stop = analyst_stop if (analyst_stop and 0 < analyst_stop < entry) else None
    target = analyst_target if (analyst_target and analyst_target > entry) else None

    if stop is None:
        stop = entry * (1.0 - s.bracket_stop_loss_pct)
    if target is None:
        target = entry * (1.0 + s.bracket_take_profit_pct)

    stop, target = round(stop, 2), round(target, 2)

    # Rounding at low prices can collapse the levels onto the entry.
    if not (stop < entry < target):
        return None, None
    return stop, target


def _calculate_qty(price: float, equity: float, position_size_pct: float) -> int:
    """Calculate whole-share quantity for a given position size."""
    if price <= 0 or equity <= 0:
        return 0
    dollar_amount = equity * position_size_pct
    return max(1, int(dollar_amount / price))


async def _get_user_settings(user_id: str) -> AutoTradeSettings | None:
    """Load auto-trade settings from the users collection."""
    db = await get_db()
    user = await db[COLL_USERS].find_one({"_id": user_id}, {"auto_trade_settings": 1})
    if not user:
        return None
    raw = user.get("auto_trade_settings")
    if not raw:
        return None
    return AutoTradeSettings(**raw)


async def _get_user_account_id(user_id: str) -> str:
    """Return the server IBKR account ID from config (same for all users)."""
    return get_settings().ibkr_account_id


async def _open_position_exists(user_id: str, ticker: str) -> bool:
    """Return True if there's already an open (PENDING or FILLED BUY) trade for this ticker."""
    db = await get_db()
    doc = await db[COLL_TRADES].find_one({
        "user_id": user_id,
        "ticker": ticker,
        "action": "BUY",
        "status": {"$in": [TradeStatus.PENDING, TradeStatus.FILLED, TradeStatus.PARTIAL]},
        "closed_at": None,
    })
    return doc is not None


async def _count_open_positions(user_id: str) -> int:
    db = await get_db()
    return await db[COLL_TRADES].count_documents({
        "user_id": user_id,
        "action": "BUY",
        "status": {"$in": [TradeStatus.PENDING, TradeStatus.FILLED, TradeStatus.PARTIAL]},
        "closed_at": None,
    })


async def _daily_realized_loss(user_id: str) -> float:
    """Sum of realized losses (negative PnL) for today's closed trades."""
    db = await get_db()
    today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pipeline = [
        {"$match": {
            "user_id": user_id,
            "closed_at": {"$gte": today_start},
            "pnl": {"$lt": 0},
        }},
        {"$group": {"_id": None, "total_loss": {"$sum": "$pnl"}}},
    ]
    result = await db[COLL_TRADES].aggregate(pipeline).to_list(length=1)
    return abs(result[0]["total_loss"]) if result else 0.0


async def _log_trade(record: dict) -> str:
    """Insert trade record and return its string ID."""
    db = await get_db()
    result = await db[COLL_TRADES].insert_one(record)
    return str(result.inserted_id)


async def _update_trade(trade_id: str, update: dict) -> None:
    from bson import ObjectId
    db = await get_db()
    await db[COLL_TRADES].update_one({"_id": ObjectId(trade_id)}, {"$set": update})


async def execute_entry(
    user_id: str,
    ticker: str,
    signal_score: float,
    current_price: float | None,
    analyst_stop_loss: float | None = None,
    analyst_price_target: float | None = None,
) -> None:
    """
    Attempt to open a BUY position for this user+ticker if all risk guards pass.
    Logs the outcome (including skips) to the trades collection.
    """
    try:
        settings = await _get_user_settings(user_id)
        if not settings or not settings.enabled:
            return

        now = utcnow()

        async def _skip(reason: str) -> None:
            await _log_trade({
                "user_id": user_id, "ticker": ticker, "action": "BUY",
                "qty": 0, "limit_price": 0.0,
                "status": TradeStatus.SKIPPED, "reason": reason,
                "signal_score": signal_score, "signal_type": "BUY",
                "is_paper": settings.paper_trading,
                "opened_at": now, "closed_at": now,
            })
            logger.info("trade_skipped", user_id=user_id, ticker=ticker, reason=reason)

        # ── Guard: CIRO restriction ───────────────────────────────────────────
        if _is_canadian_listed(ticker):
            await _skip("Canadian-listed security — API trading prohibited (CIRO rule)")
            return

        # ── Guard: signal score threshold ─────────────────────────────────────
        if signal_score < settings.min_signal_score:
            await _skip(f"Score {signal_score:.2f} below threshold {settings.min_signal_score:.2f}")
            return

        # ── Guard: ticker whitelist ───────────────────────────────────────────
        if settings.allowed_tickers and ticker.upper() not in [t.upper() for t in settings.allowed_tickers]:
            await _skip(f"Ticker not in allowed list: {settings.allowed_tickers}")
            return

        # ── Guard: no duplicate open position ─────────────────────────────────
        if await _open_position_exists(user_id, ticker):
            await _skip("Position already open for this ticker")
            return

        # ── Guard: max open positions ─────────────────────────────────────────
        open_count = await _count_open_positions(user_id)
        if open_count >= settings.max_open_positions:
            await _skip(f"Max open positions reached ({settings.max_open_positions})")
            return

        # ── Guard: IBKR connectivity ──────────────────────────────────────────
        if not ibkr.is_connected():
            await _skip("IB Gateway not connected")
            return

        account_id = await _get_user_account_id(user_id)

        # ── Guard: daily loss limit ───────────────────────────────────────────
        acct = await ibkr.get_account_summary(account_id=account_id)
        equity = acct.get("net_liquidation", 0.0)
        if equity <= 0:
            await _skip("Could not read account equity from IBKR")
            return

        daily_loss = await _daily_realized_loss(user_id)
        max_loss_dollars = equity * settings.max_daily_loss_pct
        if daily_loss >= max_loss_dollars:
            await _skip(
                f"Daily loss limit hit (${daily_loss:.2f} >= ${max_loss_dollars:.2f})"
            )
            return

        # ── Calculate order ───────────────────────────────────────────────────
        price = current_price or 0.0
        if price <= 0:
            await _skip("No current price available")
            return

        qty = _calculate_qty(price, equity, settings.position_size_pct)
        if qty < 1:
            await _skip("Calculated quantity < 1 share")
            return

        # Limit price: current price (will fill at or better)
        limit_price = round(price, 2)

        # ── Protective exits ──────────────────────────────────────────────────
        stop_price, target_price = _bracket_levels(
            limit_price, analyst_stop_loss, analyst_price_target
        )
        if stop_price is None:
            # Refuse rather than open a position nothing will ever close. The
            # app only sells on a SELL signal, which requires it to be running.
            await _skip("Could not derive a valid stop-loss — refusing unprotected entry")
            return

        # ── Log pending trade ─────────────────────────────────────────────────
        trade_id = await _log_trade({
            "user_id": user_id, "ticker": ticker, "action": "BUY",
            "qty": qty, "limit_price": limit_price,
            "stop_loss": stop_price, "take_profit": target_price,
            "status": TradeStatus.PENDING,
            "signal_score": signal_score, "signal_type": "BUY",
            # Reflects the gateway session actually in use, not the user's
            # preference — the server's TRADING_MODE decides which account is hit.
            "is_paper": not get_settings().is_live_trading,
            "opened_at": now, "closed_at": None,
        })

        # ── Place order ───────────────────────────────────────────────────────
        order_id = await ibkr.place_limit_order(
            ticker, "BUY", qty, limit_price,
            account_id=account_id,
            stop_loss_price=stop_price,
            take_profit_price=target_price,
        )
        if order_id is not None:
            await _update_trade(trade_id, {"order_id": order_id})
            logger.info(
                "trade_entry_placed", user_id=user_id, ticker=ticker,
                qty=qty, limit_price=limit_price, order_id=order_id,
                stop_loss=stop_price, take_profit=target_price,
                paper=not get_settings().is_live_trading,
            )
        else:
            await _update_trade(trade_id, {
                "status": TradeStatus.REJECTED,
                "reason": "IBKR rejected or did not return order ID",
            })

    except Exception as exc:
        logger.error("execute_entry_failed", user_id=user_id, ticker=ticker, error=str(exc))


async def execute_exit(
    user_id: str,
    ticker: str,
    current_price: float | None,
    trigger: str = "EXIT_ALERT",
) -> None:
    """
    Close an open BUY position for this user+ticker (triggered by EXIT_ALERT).
    No-op if no open position exists.
    """
    try:
        settings = await _get_user_settings(user_id)
        if not settings or not settings.enabled:
            return

        db = await get_db()
        open_trade = await db[COLL_TRADES].find_one({
            "user_id": user_id, "ticker": ticker, "action": "BUY",
            "status": {"$in": [TradeStatus.PENDING, TradeStatus.FILLED, TradeStatus.PARTIAL]},
            "closed_at": None,
        })
        if not open_trade:
            return

        if not ibkr.is_connected():
            logger.warning("exit_skipped_not_connected", user_id=user_id, ticker=ticker)
            return

        price = current_price or 0.0
        if price <= 0:
            return

        qty = open_trade.get("qty", 0)
        if qty < 1:
            return

        limit_price = round(price, 2)
        account_id = await _get_user_account_id(user_id)

        # Cancel the entry's bracket first. Its stop and target are still
        # working, so submitting a closing sell alongside them could liquidate
        # the position twice — our order plus the stop firing — leaving an
        # unintended short. Must complete before the exit is submitted.
        cancelled = await ibkr.cancel_open_orders(ticker, account_id=account_id)
        if cancelled:
            logger.info(
                "exit_cancelled_protective_orders",
                user_id=user_id, ticker=ticker, count=cancelled,
            )

        # Confirm, don't assume. cancelOrder is fire-and-forget and can itself be
        # refused (a read-only API session rejects cancels too). Selling while a
        # stop leg is still working could close the position twice and leave a
        # short, so abort instead — the bracket still protects the position, which
        # is the safe side to fail on.
        if await ibkr.has_open_orders(ticker, account_id=account_id):
            logger.error(
                "exit_aborted_orders_still_working",
                user_id=user_id, ticker=ticker, trigger=trigger,
                hint="protective legs survived cancellation; position left bracketed",
            )
            return

        # Plain limit order: the protective legs are gone, so this must not
        # carry a bracket of its own.
        order_id = await ibkr.place_limit_order(ticker, "SELL", qty, limit_price, account_id=account_id)

        from bson import ObjectId
        update: dict = {
            "closed_at": utcnow(),
            "exit_price": limit_price,
            "status": TradeStatus.PENDING,  # will be settled by perf tracker
        }
        if order_id:
            update["exit_order_id"] = order_id

        entry_price = open_trade.get("entry_price") or open_trade.get("limit_price", 0.0)
        if entry_price:
            update["pnl"] = round((price - entry_price) * qty, 2)

        await db[COLL_TRADES].update_one(
            {"_id": open_trade["_id"]},
            {"$set": update},
        )
        logger.info(
            "trade_exit_placed", user_id=user_id, ticker=ticker,
            qty=qty, limit_price=limit_price, trigger=trigger,
            paper=settings.paper_trading,
        )

    except Exception as exc:
        logger.error("execute_exit_failed", user_id=user_id, ticker=ticker, error=str(exc))
