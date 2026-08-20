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

from app.db import COLL_TRADES, COLL_USERS, get_db
from app.dependencies import get_current_user
from app.models.trade import (
    AccountSummaryResponse,
    AutoTradeSettings,
    AutoTradeSettingsResponse,
    TradeResponse,
    TradeStatus,
)
from app.services import broker as ibkr
from app.services.trade_manager import execute_exit
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

    await execute_exit(user_id, ticker.upper(), current_price, trigger="MANUAL_CLOSE")
    return {"status": "close_order_submitted", "ticker": ticker.upper()}
