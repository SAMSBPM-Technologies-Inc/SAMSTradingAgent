"""
Automated Trading Routes
─────────────────────────
GET  /trading/settings          — get current user's auto-trade settings
PUT  /trading/settings          — update settings
GET  /trading/account           — live IBKR account summary
GET  /trading/positions         — open positions tracked in the trades collection
GET  /trading/orders            — order history (all trades for this user)
POST /trading/close/{ticker}    — manually close an open position
"""
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

# Aliased: this module defines a route handler called `get_settings` (the
# auto-trade settings endpoint), which shadows the config accessor otherwise.
from app.config import get_settings as get_env_settings
from app.db import COLL_SIGNALS, COLL_TRADES, COLL_USERS, get_db
from app.dependencies import get_current_user
from app.models.trade import (
    AccountSummaryResponse,
    AutoTradeSettings,
    AutoTradeSettingsResponse,
    ManualOrderRequest,
    OrderPlacementResponse,
    ProposalResponse,
    TradeResponse,
    TradeStatus,
)
from app.services import broker as ibkr
from app.services.trade_manager import execute_exit, execute_manual_entry
from app.utils.logger import get_logger

router = APIRouter(prefix="/trading", tags=["trading"])
logger = get_logger(__name__)


def _trade_to_response(doc: dict) -> TradeResponse:
    return TradeResponse(
        id=str(doc["_id"]),
        user_id=doc.get("user_id", ""),
        ticker=doc.get("ticker", ""),
        action=doc.get("action", ""),
        qty=doc.get("qty", 0),
        limit_price=doc.get("limit_price", 0.0),
        order_id=doc.get("order_id"),
        stop_loss=doc.get("stop_loss"),
        take_profit=doc.get("take_profit"),
        status=doc.get("status", TradeStatus.PENDING),
        reason=doc.get("reason"),
        signal_score=doc.get("signal_score"),
        signal_type=doc.get("signal_type"),
        entry_price=doc.get("entry_price"),
        exit_price=doc.get("exit_price"),
        pnl=doc.get("pnl"),
        is_paper=doc.get("is_paper", True),
        opened_at=doc.get("opened_at", datetime.utcnow()),
        closed_at=doc.get("closed_at"),
    )


@router.get("/settings", response_model=AutoTradeSettingsResponse, summary="Get auto-trade settings")
async def get_settings(current_user: dict = Depends(get_current_user)) -> AutoTradeSettingsResponse:
    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"auto_trade_settings": 1}
    )
    raw = (user or {}).get("auto_trade_settings") or {}
    settings = AutoTradeSettings(**raw)
    return AutoTradeSettingsResponse(**settings.model_dump(), connected=ibkr.is_connected())


@router.put("/settings", response_model=AutoTradeSettingsResponse, summary="Update auto-trade settings")
async def update_settings(
    body: AutoTradeSettings,
    current_user: dict = Depends(get_current_user),
) -> AutoTradeSettingsResponse:
    # Safety: enforce paper=True if user tries to enable live trading
    # (live trading requires an explicit separate flag in env — see AUTO_TRADE_LIVE_ALLOWED)
    from app.config import get_settings as cfg
    settings_env = cfg()
    if not body.paper_trading and not getattr(settings_env, "auto_trade_live_allowed", False):
        raise HTTPException(
            status_code=403,
            detail="Live trading is not enabled on this server. Set AUTO_TRADE_LIVE_ALLOWED=true in env.",
        )

    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"auto_trade_settings": body.model_dump()}},
    )
    logger.info(
        "auto_trade_settings_updated",
        user_id=str(current_user["_id"]),
        enabled=body.enabled,
        paper=body.paper_trading,
    )
    return AutoTradeSettingsResponse(**body.model_dump(), connected=ibkr.is_connected())


@router.get("/account", response_model=AccountSummaryResponse, summary="Live IBKR account summary")
async def get_account(current_user: dict = Depends(get_current_user)) -> AccountSummaryResponse:
    from app.config import get_settings
    account_id = get_settings().ibkr_account_id
    summary = await ibkr.get_account_summary(account_id=account_id)
    return AccountSummaryResponse(**summary)


@router.post("/reconcile", summary="Force a broker reconciliation pass now")
async def force_reconcile(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Run trade reconciliation immediately instead of waiting for the schedule.

    Also returns what the broker currently reports, because the usual question
    when a trade looks stuck is not "what did reconciliation decide" but "what
    does the venue actually say" — and the two are only separable side by side.
    """
    from app.services.trade_manager import reconcile_trades

    summary = await reconcile_trades()

    account = await ibkr.get_account_summary()
    account_id = account.get("account_id") or ""
    statuses = await ibkr.get_order_statuses(account_id)
    positions = await ibkr.get_positions()
    fills = await ibkr.get_fills(1440)

    return {
        "reconciled": summary,
        "broker": {
            "connected": account.get("connected", False),
            "account_id": account_id,
            "order_ids_visible": sorted(statuses.keys()),
            "orders": [
                {
                    "order_id": o.order_id, "status": o.status,
                    "filled": o.filled_qty, "remaining": o.remaining_qty,
                    "avg_price": o.avg_fill_price,
                }
                for o in list(statuses.values())[:40]
            ],
            "positions": [{"ticker": p["ticker"], "qty": p["qty"]} for p in positions],
            "fill_count": len(fills),
            # Grouped by (ticker, side, order) so a P&L figure can be traced back
            # to the executions it came from. Exit matching is by ticker and
            # time — the closing order belongs to the bracket, not to us — so
            # this is the only way to see whether an unrelated sell was absorbed.
            "fills_by_order": _summarise_fills(fills),
        },
    }


def _summarise_fills(fills: list) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for f in fills:
        key = (f.ticker, f.side, str(f.order_id))
        g = grouped.setdefault(key, {
            "ticker": f.ticker, "side": f.side, "order_id": str(f.order_id),
            "qty": 0.0, "notional": 0.0, "first": None, "last": None,
        })
        g["qty"] += f.qty
        g["notional"] += f.qty * f.price
        stamp = f.executed_at.isoformat() if f.executed_at else None
        if stamp:
            g["first"] = min(g["first"] or stamp, stamp)
            g["last"] = max(g["last"] or stamp, stamp)
    out = []
    for g in grouped.values():
        out.append({
            "ticker": g["ticker"], "side": g["side"], "order_id": g["order_id"],
            "qty": g["qty"],
            "vwap": round(g["notional"] / g["qty"], 4) if g["qty"] else None,
            "first": g["first"], "last": g["last"],
        })
    out.sort(key=lambda x: (x["ticker"], x["side"], x["order_id"]))
    return out


@router.get("/holdings", summary="Live holdings straight from the broker")
async def get_holdings(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Current holdings as the broker reports them, fetched on demand.

    Distinct from /trading/positions, which reflects this app's own trade
    records. This endpoint is the broker's truth: it includes anything bought
    outside the agent and excludes anything the agent believes it holds but
    does not. Deliberately not polled — it costs a broker round-trip.
    """
    from app.config import get_settings

    if not ibkr.is_connected():
        return {"connected": False, "account_id": "", "holdings": [], "total_market_value": 0.0}

    account_id = get_settings().ibkr_account_id
    summary = await ibkr.get_account_summary(account_id=account_id)
    positions = await ibkr.get_positions()

    holdings = []
    total = 0.0
    for p in positions:
        qty = float(p.get("qty") or 0)
        if not qty:
            continue
        mv = p.get("market_value")
        mv = float(mv) if mv is not None else None
        if mv is not None:
            total += mv
        holdings.append({
            "ticker": p.get("ticker", ""),
            "qty": qty,
            "avg_cost": float(p.get("avg_cost") or 0.0),
            "market_value": mv,
            "unrealized_pnl": (
                float(p["unrealized_pnl"]) if p.get("unrealized_pnl") is not None else None
            ),
        })

    holdings.sort(key=lambda h: (h["market_value"] or 0.0), reverse=True)
    return {
        "connected": True,
        "account_id": summary.get("account_id", "") or account_id,
        "holdings": holdings,
        "total_market_value": round(total, 2),
    }


@router.get("/positions", response_model=list[TradeResponse], summary="Open positions tracked locally")
async def get_positions(current_user: dict = Depends(get_current_user)) -> list[TradeResponse]:
    """Returns trades that are open (BUY without a closed_at)."""
    db = await get_db()
    user_id = str(current_user["_id"])
    docs = await db[COLL_TRADES].find({
        "user_id": user_id,
        "action": "BUY",
        "status": {"$in": list(TradeStatus.OPEN)},
        "closed_at": None,
    }).sort("opened_at", -1).to_list(length=200)
    return [_trade_to_response(d) for d in docs]


@router.get("/orders", response_model=list[TradeResponse], summary="Full trade history")
async def get_orders(current_user: dict = Depends(get_current_user)) -> list[TradeResponse]:
    db = await get_db()
    user_id = str(current_user["_id"])
    docs = await db[COLL_TRADES].find(
        {"user_id": user_id}
    ).sort("opened_at", -1).limit(200).to_list(length=200)
    return [_trade_to_response(d) for d in docs]


@router.post("/close/{ticker}", summary="Manually close an open position")
async def close_position(
    ticker: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    db = await get_db()

    # Find the open position
    open_trade = await db[COLL_TRADES].find_one({
        "user_id": user_id,
        "ticker": ticker.upper(),
        "action": "BUY",
        "status": {"$in": list(TradeStatus.OPEN)},
        "closed_at": None,
    })
    if not open_trade:
        raise HTTPException(status_code=404, detail=f"No open position found for {ticker.upper()}")

    # Get current price from IBKR positions (approximate)
    ibkr_positions = await ibkr.get_positions()
    current_price = None
    for pos in ibkr_positions:
        if pos["ticker"].upper() == ticker.upper():
            avg_cost = pos.get("avg_cost")
            current_price = avg_cost  # best estimate without live quote

    # require_enabled=False: this is the user asking to get out, not the agent
    # acting. Gating it on the auto-trade switch meant every manual-mode user
    # got "close_order_submitted" while nothing was submitted.
    await execute_exit(
        user_id, ticker.upper(), current_price,
        trigger="MANUAL_CLOSE", require_enabled=False,
    )
    logger.info("manual_close_requested", user_id=user_id, ticker=ticker.upper())
    return {"status": "close_order_submitted", "ticker": ticker.upper()}


# ── Manual orders ─────────────────────────────────────────────────────────────

@router.post("/order", response_model=OrderPlacementResponse, summary="Place a user-initiated order")
async def place_order(
    body: ManualOrderRequest,
    current_user: dict = Depends(get_current_user),
) -> OrderPlacementResponse:
    """
    Place an order the user chose, subject to every guard the agent obeys.

    The client's `qty` and `limit_price` are treated as requests. The server
    re-derives the fundable quantity from live account state and takes the
    smaller of the two, so position sizing and the cash reserve cannot be
    escaped by editing a form field.

    Live-money orders additionally require `confirm_live`, which the UI only
    sets after a typed confirmation.
    """
    user_id = str(current_user["_id"])
    ticker = body.ticker.upper().strip()
    env = get_env_settings()

    if body.action != "BUY":
        # SELL is a position close, and closing is not symmetrical with opening:
        # it must cancel the working bracket first and size to what the broker
        # actually holds. /trading/close/{ticker} does that.
        raise HTTPException(
            status_code=400,
            detail="Use POST /trading/close/{ticker} to exit a position.",
        )

    # ── Guard: live-money confirmation ────────────────────────────────────────
    if env.is_live_trading and not body.confirm_live:
        raise HTTPException(
            status_code=428,
            detail="This account trades live money. Re-submit with confirm_live=true.",
        )

    db = await get_db()

    # ── Idempotency ───────────────────────────────────────────────────────────
    # A double-clicked Buy button must not buy twice. The unique index on
    # (user_id, idempotency_key) is the real guarantee; this lookup just turns
    # the second request into a friendly answer instead of a 500.
    if body.idempotency_key:
        prior = await db[COLL_TRADES].find_one({
            "user_id": user_id, "idempotency_key": body.idempotency_key,
        })
        if prior:
            logger.info(
                "manual_order_deduplicated",
                user_id=user_id, ticker=ticker, key=body.idempotency_key,
            )
            return OrderPlacementResponse(
                placed=prior.get("status") in TradeStatus.OPEN,
                status=prior.get("status", TradeStatus.PENDING),
                ticker=prior.get("ticker", ticker),
                action=prior.get("action", "BUY"),
                qty=prior.get("qty", 0),
                limit_price=prior.get("limit_price", 0.0),
                order_id=prior.get("order_id"),
                stop_loss=prior.get("stop_loss"),
                take_profit=prior.get("take_profit"),
                is_paper=prior.get("is_paper", True),
                trade_id=str(prior["_id"]),
                reason="Already submitted — returning the original order.",
                duplicate=True,
            )

    # Reuse the analyst's own protective levels when we have them, exactly as
    # the automated path does, rather than always falling back to percentages.
    signal_doc = await db[COLL_SIGNALS].find_one(
        {"ticker": ticker}, {"analyst_output": 1, "score": 1}
    ) or {}
    ao = signal_doc.get("analyst_output") or {}

    result = await execute_manual_entry(
        user_id, ticker,
        requested_qty=body.qty,
        limit_price=body.limit_price,
        analyst_stop_loss=ao.get("stop_loss"),
        analyst_price_target=ao.get("price_target"),
        signal_score=signal_doc.get("score"),
    )

    if result.get("trade_id") and body.idempotency_key:
        await db[COLL_TRADES].update_one(
            {"_id": ObjectId(result["trade_id"])},
            {"$set": {"idempotency_key": body.idempotency_key}},
        )

    logger.info(
        "manual_order_result",
        user_id=user_id, ticker=ticker, placed=result.get("placed"),
        qty=result.get("qty"), status=result.get("status"),
        live=env.is_live_trading,
    )
    return OrderPlacementResponse(action="BUY", **{
        k: v for k, v in result.items() if k != "action"
    })


# ── Proposals ─────────────────────────────────────────────────────────────────

@router.get("/proposals", response_model=list[ProposalResponse], summary="Entries awaiting your approval")
async def list_proposals(current_user: dict = Depends(get_current_user)) -> list[ProposalResponse]:
    """
    Entries the agent wanted to take but its mode does not let it take alone.

    Nothing here is committed and none of it consumes a position slot — a
    proposal is a recommendation with the arithmetic already done.
    """
    db = await get_db()
    docs = await db[COLL_TRADES].find({
        "user_id": str(current_user["_id"]),
        "status": TradeStatus.PROPOSED,
    }).sort("opened_at", -1).to_list(length=100)

    return [
        ProposalResponse(
            id=str(d["_id"]),
            ticker=d.get("ticker", ""),
            action=d.get("action", "BUY"),
            qty=d.get("qty", 0),
            limit_price=d.get("limit_price", 0.0),
            stop_loss=d.get("stop_loss"),
            take_profit=d.get("take_profit"),
            signal_score=d.get("signal_score"),
            conviction=d.get("conviction"),
            reason=d.get("reason"),
            proposed_at=d.get("opened_at", datetime.utcnow()),
            is_paper=d.get("is_paper", True),
        )
        for d in docs
    ]


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=OrderPlacementResponse,
    summary="Approve a proposed entry and place it",
)
async def approve_proposal(
    proposal_id: str,
    confirm_live: bool = False,
    current_user: dict = Depends(get_current_user),
) -> OrderPlacementResponse:
    """
    Place a proposed entry.

    The stored quantity and price are re-validated rather than replayed: a
    proposal can sit for hours, and the account, the price, and the position
    count may all have moved since it was written.
    """
    user_id = str(current_user["_id"])
    env = get_env_settings()

    if env.is_live_trading and not confirm_live:
        raise HTTPException(
            status_code=428,
            detail="This account trades live money. Re-submit with confirm_live=true.",
        )

    db = await get_db()
    try:
        oid = ObjectId(proposal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid proposal id.")

    # Claim it atomically. Two clicks on Approve must not place two orders, and
    # a status check followed by an update leaves exactly that window open.
    claimed = await db[COLL_TRADES].find_one_and_update(
        {"_id": oid, "user_id": user_id, "status": TradeStatus.PROPOSED},
        {"$set": {"status": TradeStatus.CANCELLED,
                  "reason": "Superseded by the approved order",
                  "closed_at": datetime.utcnow()}},
    )
    if not claimed:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found, or it has already been acted on.",
        )

    result = await execute_manual_entry(
        user_id, claimed.get("ticker", ""),
        requested_qty=claimed.get("qty"),
        analyst_stop_loss=claimed.get("stop_loss"),
        analyst_price_target=claimed.get("take_profit"),
        signal_score=claimed.get("signal_score"),
        # Kept distinct from a hand-picked order: the agent chose this ticker,
        # but a human filtered the set, so it is not a clean read of either.
        source="PROPOSAL_APPROVED",
    )

    if not result.get("placed"):
        # Put it back — a refused approval should leave the proposal actionable
        # rather than quietly consuming it.
        await db[COLL_TRADES].update_one(
            {"_id": oid},
            {"$set": {"status": TradeStatus.PROPOSED, "closed_at": None,
                      "reason": result.get("reason") or "Could not be placed"}},
        )

    logger.info(
        "proposal_approved",
        user_id=user_id, proposal_id=proposal_id,
        ticker=claimed.get("ticker"), placed=result.get("placed"),
    )
    return OrderPlacementResponse(action="BUY", **{
        k: v for k, v in result.items() if k != "action"
    })


@router.post("/proposals/{proposal_id}/decline", summary="Decline a proposed entry")
async def decline_proposal(
    proposal_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Reject a proposal. Terminal, and explicitly not a trade outcome."""
    db = await get_db()
    try:
        oid = ObjectId(proposal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid proposal id.")

    updated = await db[COLL_TRADES].find_one_and_update(
        {"_id": oid, "user_id": str(current_user["_id"]), "status": TradeStatus.PROPOSED},
        {"$set": {"status": TradeStatus.DECLINED, "closed_at": datetime.utcnow(),
                  "reason": "Declined by user"}},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Proposal not found, or already acted on.")

    logger.info(
        "proposal_declined",
        user_id=str(current_user["_id"]), proposal_id=proposal_id,
        ticker=updated.get("ticker"),
    )
    return {"status": "declined", "ticker": updated.get("ticker", "")}
