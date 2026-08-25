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
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_SIGNALS, COLL_TRADES, COLL_USERS, get_db
from app.models.trade import AutoTradeSettings, TradeRecord, TradeStatus
from app.services import broker as ibkr
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BrokerUnavailable(RuntimeError):
    """
    The broker could not be reached, so the requested action did not happen.

    Raised only on user-initiated paths. The scheduled agent swallows the same
    condition and retries on its next cycle, but a person who pressed a button
    has to be told, or the UI reports a success that never occurred.
    """


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


def _combined_bracket_levels(
    *,
    blended_entry: float,
    current_price: float,
    existing_stop: float | None,
    existing_target: float | None,
    analyst_stop: float | None,
    analyst_target: float | None,
) -> tuple[float | None, float | None]:
    """
    Resolve the stop and target for a position that just grew.

    Two rules, and the first one is the whole point:

    **A scale-in may never weaken the protection already on the holding.** The
    naive move is to recompute from the new blended cost — but adding lower
    drags the blended entry down, which drags a percentage-derived stop down
    with it, and the shares bought first end up with a looser stop than they
    had before the "improvement". So the combined stop is the *higher* of what
    the blend implies and what is already working, and the target the higher of
    the two likewise.

    **The result must be live-able.** A stop at or above the current price
    triggers the moment it reaches the venue and liquidates the position
    instantly; a target at or below it fills into the spread. Both are rejected
    outright rather than clamped, because a level quietly moved to somewhere it
    was not chosen is not protection, and the caller can leave the existing
    bracket alone — which is the safe failure.

    Returns (stop, target), or (None, None) if no valid pair exists.
    """
    implied_stop, implied_target = _bracket_levels(
        blended_entry, analyst_stop, analyst_target
    )
    if implied_stop is None or implied_target is None:
        return None, None

    stop = max(implied_stop, existing_stop or 0.0)
    target = max(implied_target, existing_target or 0.0)

    if not (stop < current_price < target):
        logger.warning(
            "scale_in_levels_unusable",
            blended_entry=blended_entry, current_price=current_price,
            stop=stop, target=target,
            hint="combined stop/target would not straddle the live price",
        )
        return None, None
    if not (stop < blended_entry < target):
        logger.warning(
            "scale_in_levels_straddle_failed",
            blended_entry=blended_entry, stop=stop, target=target,
        )
        return None, None
    return round(stop, 2), round(target, 2)


#: Annualised volatility that `position_size_pct` is calibrated for. A name at
#: this level gets exactly the configured size; quieter names get more, wilder
#: names less, so each position carries comparable risk rather than comparable
#: dollars.
_SIZING_PIVOT_VOL = 0.35

#: Bounds on the scaling factor. Without a floor, a 150%-volatility name sizes
#: to almost nothing and the fill is dominated by commission; without a ceiling,
#: a very quiet name could take a position several times the intended size and
#: quietly concentrate the book.
_SIZING_MIN_FACTOR = 0.35
_SIZING_MAX_FACTOR = 1.50


def _volatility_size_factor(volatility_20d: float | None) -> float:
    """
    Scale the configured position size by how violent the name is.

    A flat percentage of equity gives a 15%-volatility utility and a
    130%-volatility growth name the same dollar exposure and therefore wildly
    different risk — the quiet one can barely move the account and the wild one
    can halve the position in a week.

    This matters more since volatility was removed from the composite score,
    which is correct — a stock is not a better opportunity for being quiet — but
    left sizing as the place where volatility SHOULD be expressed, and it wasn't
    expressed there either.

    Returns 1.0 when volatility is unknown, so a missing feature document
    reproduces the previous flat behaviour rather than guessing.
    """
    if not volatility_20d or volatility_20d <= 0:
        return 1.0
    factor = _SIZING_PIVOT_VOL / float(volatility_20d)
    return max(_SIZING_MIN_FACTOR, min(_SIZING_MAX_FACTOR, factor))


def _calculate_qty(
    price: float,
    equity: float,
    position_size_pct: float,
    volatility_20d: float | None = None,
) -> int:
    """Whole-share quantity for a given position size, scaled by volatility."""
    if price <= 0 or equity <= 0:
        return 0
    dollar_amount = equity * position_size_pct * _volatility_size_factor(volatility_20d)
    return max(1, int(dollar_amount / price))


async def _ticker_volatility(ticker: str) -> float | None:
    """Latest realised volatility for *ticker*, or None if not yet computed."""
    db = await get_db()
    doc = await db[COLL_FEATURES].find_one(
        {"ticker": ticker.upper()}, {"volatility_20d": 1}
    )
    return (doc or {}).get("volatility_20d")


async def _get_user_settings(user_id) -> AutoTradeSettings | None:
    """
    Load auto-trade settings from the users collection.

    Accepts the id as either a str or an ObjectId. This matters: `users._id` is
    an ObjectId, but `watched_tickers.user_id` and `trades.user_id` store the
    stringified form, and the pipeline passes the string straight through. The
    previous `{"_id": user_id}` lookup therefore never matched, execute_entry
    returned at its first guard, and automated trading could not place an order
    at all — silently, because that early return logs nothing.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    db = await get_db()

    # Match either storage convention rather than assuming one.
    candidates = [user_id]
    if isinstance(user_id, str):
        try:
            candidates.append(ObjectId(user_id))
        except (InvalidId, TypeError):
            pass
    else:
        candidates.append(str(user_id))

    user = await db[COLL_USERS].find_one(
        {"_id": {"$in": candidates}}, {"auto_trade_settings": 1}
    )
    if not user:
        logger.warning(
            "auto_trade_user_not_found",
            user_id=str(user_id),
            hint="no users document matched this id — auto-trading cannot run for it",
        )
        return None
    raw = user.get("auto_trade_settings")
    if not raw:
        return None
    return AutoTradeSettings(**raw)


async def _trade_email_recipient(user_id) -> str:
    """
    Address for trade notifications: the alert_settings override if set,
    otherwise the account email. Returns "" when the user has opted out.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    db = await get_db()
    candidates = [user_id]
    if isinstance(user_id, str):
        try:
            candidates.append(ObjectId(user_id))
        except (InvalidId, TypeError):
            pass
    user = await db[COLL_USERS].find_one(
        {"_id": {"$in": candidates}}, {"email": 1, "alert_settings": 1}
    )
    if not user:
        return ""
    prefs = user.get("alert_settings") or {}
    if not prefs.get("notify_on_trade", True):
        return ""
    return (prefs.get("trade_email") or user.get("email") or "").strip()


async def _notify_trade(user_id, **kwargs) -> None:
    """Email the user that an order went out. Never raises."""
    try:
        to = await _trade_email_recipient(user_id)
        if not to:
            return
        from app.services.notifier import send_trade_email
        await send_trade_email(to, **kwargs)
    except Exception as exc:
        logger.warning("trade_email_failed", user_id=str(user_id), error=str(exc))


async def _get_user_account_id(user_id: str) -> str:
    """Return the server IBKR account ID from config (same for all users)."""
    return get_settings().ibkr_account_id


async def _open_position(user_id: str, ticker: str) -> dict | None:
    """
    The open (PENDING / FILLED / PARTIAL) BUY blocking this ticker, if any.

    Returns the document rather than a bool so callers can say *what* is in the
    way. "Position already open" gave no way to tell a filled holding from a
    stale order record that never reconciled, and those need opposite responses.
    """
    db = await get_db()
    return await db[COLL_TRADES].find_one({
        "user_id": user_id,
        "ticker": ticker,
        "action": "BUY",
        "status": {"$in": list(TradeStatus.OPEN)},
        "closed_at": None,
    })


def _blocked_by_open_position(trade: dict) -> str:
    """
    Explain the refusal in terms of what the user can act on.

    Why a second entry is refused at all: the first one is bracketed, and its
    stop and target are still working at the venue. A second entry would attach
    a second bracket to the same holding, so two stops could fire against one
    position and sell more than is held — the same oversell-into-a-short hazard
    `execute_exit` cancels the bracket to avoid. Scaling in safely means
    cancelling the working legs and submitting one combined bracket, which is a
    deliberate feature, not a side effect of pressing Buy twice.
    """
    status = trade.get("status", "OPEN")
    qty = trade.get("filled_qty") or trade.get("qty") or 0
    opened = trade.get("opened_at")
    when = opened.strftime("%d %b") if hasattr(opened, "strftime") else "earlier"

    if status == TradeStatus.FILLED:
        return (
            f"You already hold {qty:g} shares from {when}, with a stop and target "
            f"working at the broker. Adding to it would attach a second bracket to "
            f"the same holding. Close the position first, or leave it to run."
        )
    if status == TradeStatus.PARTIAL:
        return (
            f"An order from {when} is partially filled ({qty:g} shares so far). "
            f"Wait for it to complete or close the position before adding."
        )
    # PENDING — submitted but not filled. May also be a record that never
    # reconciled, which the user cannot tell apart without being told.
    order_id = trade.get("order_id")
    return (
        f"An order for {qty:g} shares from {when} is still working"
        + (f" (broker order {order_id})" if order_id else " and has no broker order id")
        + ". Wait for it to fill, or close it from the Orders page if it is stale."
    )


async def _already_skipped_for(user_id: str, ticker: str, reason: str) -> bool:
    """
    Is the newest record for this user+ticker already this same skip?

    Compares against the newest record rather than searching history, so a skip
    that recurs *after* something else happened — an entry, an exit, a
    different refusal — is recorded again. Only an unbroken run collapses.
    """
    db = await get_db()
    latest = await db[COLL_TRADES].find_one(
        {"user_id": user_id, "ticker": ticker},
        {"status": 1, "reason": 1},
        sort=[("opened_at", -1)],
    )
    return bool(
        latest
        and latest.get("status") == TradeStatus.SKIPPED
        and latest.get("reason") == reason
    )


async def _pending_proposal(user_id: str, ticker: str) -> dict | None:
    """The proposal for this ticker still awaiting a human decision, if any."""
    db = await get_db()
    return await db[COLL_TRADES].find_one({
        "user_id": user_id,
        "ticker": ticker,
        "action": "BUY",
        "status": TradeStatus.PROPOSED,
        "closed_at": None,
    })


async def _count_open_positions(user_id: str) -> int:
    db = await get_db()
    return await db[COLL_TRADES].count_documents({
        "user_id": user_id,
        "action": "BUY",
        "status": {"$in": list(TradeStatus.OPEN)},
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


@dataclass
class EntryPlan:
    """A validated, fundable, bracketed order — everything but the submission."""
    ticker: str
    qty: int
    limit_price: float
    stop_price: float
    target_price: float
    account_id: str
    #: Set when the requested size was cut to what the account can actually fund.
    adjustment: str | None = None
    #: Set when this order adds to a holding instead of opening one. Carries the
    #: id of the position record to update — an add must never insert a second
    #: record, because `execute_exit` loads exactly one and would leave the
    #: remainder held, unprotected and unowned by any trade the agent can see.
    add_to_trade_id: str | None = None
    #: Shares already held. The protective legs must cover `qty + held_qty`.
    held_qty: int = 0
    #: Cost basis per share across the combined position, once this fills.
    blended_entry: float | None = None

    @property
    def is_add(self) -> bool:
        return self.add_to_trade_id is not None

    @property
    def total_qty(self) -> int:
        """Shares held once this order fills — what protection must cover."""
        return self.qty + self.held_qty


async def _prepare_entry(
    user_id: str,
    ticker: str,
    settings: AutoTradeSettings,
    current_price: float | None,
    analyst_stop_loss: float | None,
    analyst_price_target: float | None,
    *,
    requested_qty: int | None = None,
    enforce_whitelist: bool = True,
) -> tuple[EntryPlan | None, str | None]:
    """
    Run every risk guard and size the order. Returns (plan, skip_reason).

    Extracted so the automated and user-initiated paths cannot drift apart. A
    manual order is a different *decision*, not a different set of guards: it
    still may not breach the CIRO restriction, the position cap, the daily-loss
    kill switch, the cash reserve, or the refusal to open an unprotected entry.

    Only two things differ for a manual order, and both are passed in rather
    than assumed here: the signal-score threshold does not apply (the human is
    the signal), and the whitelist does not apply (it restricts what the *agent*
    may pick, and the user has explicitly chosen this ticker).
    """
    # ── Guard: CIRO restriction ───────────────────────────────────────────────
    if _is_canadian_listed(ticker):
        return None, "Canadian-listed security — API trading prohibited (CIRO rule)"

    # ── Guard: ticker whitelist ───────────────────────────────────────────────
    if enforce_whitelist and settings.allowed_tickers:
        if ticker.upper() not in [t.upper() for t in settings.allowed_tickers]:
            return None, f"Ticker not in allowed list: {settings.allowed_tickers}"

    # ── Existing position: add to it, or refuse ───────────────────────────────
    # Holding a stock is not a reason to refuse buying more of it. What the
    # refusal actually protected was the bracket: a second entry used to attach
    # a second, independent stop and target to one holding, and `execute_exit`
    # cancels every working order for the ticker but closes only the single
    # record it loads — so an exit left the remainder held, unprotected, and
    # invisible to the agent. Scaling in is that missing feature, not a relaxed
    # guard: one position record, one bracket, sized to the whole holding.
    add_to: dict | None = None
    held_qty = 0
    existing = await _open_position(user_id, ticker)
    if existing is not None:
        blocked = _blocked_by_open_position(existing)
        if not get_settings().enable_scale_in:
            return None, blocked
        # Only a settled position can be added to. While the first entry is
        # still working there is no fill price to blend, no held quantity to
        # size legs against, and the resting order may yet fill or die — the
        # combined bracket would be built on a guess.
        if existing.get("status") != TradeStatus.FILLED:
            return None, blocked
        held_qty = int(existing.get("filled_qty") or existing.get("qty") or 0)
        if held_qty < 1:
            return None, blocked
        # One add at a time. A second would cancel the bracket the first is
        # waiting on, and the two orders would each believe they own the
        # combined size.
        working_add = existing.get("pending_add")
        if working_add:
            when = working_add.get("submitted_at")
            when_str = when.strftime("%d %b %H:%M") if hasattr(when, "strftime") else "earlier"
            return None, (
                f"An add of {working_add.get('qty')} shares to {ticker} from "
                f"{when_str} is still working. Wait for it to fill or cancel it."
            )
        add_to = existing

    # ── Guard: no duplicate outstanding proposal ──────────────────────────────
    # PROPOSED is deliberately not in TradeStatus.OPEN — a proposal commits
    # nothing — but that also meant nothing stopped the agent proposing the same
    # entry again on the next evaluation. A ticker oscillating around the BUY
    # threshold queued a fresh proposal on every flip, so the user opened the
    # Orders page to four identical HXL cards and no way to tell which one was
    # current. One outstanding proposal per ticker; approving or declining it
    # clears the way for the next.
    pending_proposal = await _pending_proposal(user_id, ticker)
    if pending_proposal is not None:
        when = pending_proposal.get("opened_at")
        when_str = when.strftime("%d %b %H:%M") if hasattr(when, "strftime") else "earlier"
        return None, (
            f"A proposal for {ticker} from {when_str} is already waiting for your "
            f"decision. Approve or decline it on the Orders page."
        )

    # ── Guard: max open positions ─────────────────────────────────────────────
    # Skipped for an add: the cap counts positions, and adding to one does not
    # create another. Applying it here would refuse every add once the book was
    # full, which is backwards — concentrating into a name you already hold uses
    # no new slot and is the cheaper risk of the two.
    if add_to is None:
        if await _count_open_positions(user_id) >= settings.max_open_positions:
            return None, f"Max open positions reached ({settings.max_open_positions})"

    # ── Guard: broker connectivity ────────────────────────────────────────────
    if not ibkr.is_connected():
        return None, "IB Gateway not connected"

    account_id = await _get_user_account_id(user_id)

    # ── Guard: daily loss limit ───────────────────────────────────────────────
    acct = await ibkr.get_account_summary(account_id=account_id)
    equity = acct.get("net_liquidation", 0.0)
    if equity <= 0:
        return None, "Could not read account equity from IBKR"

    daily_loss = await _daily_realized_loss(user_id)
    max_loss_dollars = equity * settings.max_daily_loss_pct
    if daily_loss >= max_loss_dollars:
        return None, f"Daily loss limit hit (${daily_loss:.2f} >= ${max_loss_dollars:.2f})"

    # ── Calculate order ───────────────────────────────────────────────────────
    price = current_price or 0.0
    if price <= 0:
        return None, "No current price available"

    vol = await _ticker_volatility(ticker)
    sized_qty = _calculate_qty(price, equity, settings.position_size_pct, vol)

    adjustment: str | None = None

    if add_to is not None:
        # ── Guard: don't add into a position that is already failing ──────────
        # The stop is the level at which this thesis is declared wrong. Buying
        # more below it is not scaling in, it is overriding the exit you already
        # decided on, and it is the single most reliable way to turn a bounded
        # loss into an unbounded one.
        existing_stop = float(add_to.get("stop_loss") or 0.0)
        if existing_stop > 0 and price <= existing_stop:
            return None, (
                f"{ticker} is at ${price:,.2f}, at or below your stop of "
                f"${existing_stop:,.2f}. Adding here would be averaging down "
                f"through the level that says the thesis is wrong."
            )

        # ── Size against the POSITION, not the order ──────────────────────────
        # position_size_pct caps how much of the account one name may represent.
        # Sized per order it caps nothing: three 5% adds make a 15% position.
        #
        # Room is measured on COST BASIS, deliberately. On market value a
        # falling position frees room as it falls, so the agent would buy more
        # of a loser precisely as it got worse — mechanical averaging down,
        # dressed up as risk sizing.
        held_cost = held_qty * float(add_to.get("entry_price") or add_to.get("limit_price") or price)
        max_dollars = equity * settings.position_size_pct * _volatility_size_factor(vol)
        room = max_dollars - held_cost
        room_qty = int(room / price) if price > 0 else 0
        if room_qty < 1:
            return None, (
                f"Already at your full size for {ticker}: {held_qty:g} shares cost "
                f"${held_cost:,.2f} against a {settings.position_size_pct:.0%} "
                f"limit of ${max_dollars:,.2f}."
            )
        if room_qty < sized_qty:
            adjustment = (
                f"Adding {room_qty} shares to {held_qty:g} already held — the rest "
                f"of a full-size order would breach your "
                f"{settings.position_size_pct:.0%} limit for one name."
            )
        sized_qty = min(sized_qty, room_qty)

    if requested_qty is not None:
        # A client-supplied quantity is a request, never an instruction. Take
        # the smaller of what was asked for and what the risk model sizes to,
        # so the sizing rules cannot be escaped by editing a form field.
        qty = min(int(requested_qty), sized_qty) if sized_qty >= 1 else 0
        if qty < int(requested_qty):
            # Appended, not assigned: an add can already carry a note about the
            # position cap, and overwriting it would hide why the size moved.
            adjustment = " ".join(filter(None, [adjustment, (
                f"Requested {int(requested_qty)} shares; reduced to {qty} to stay "
                f"within your {settings.position_size_pct:.0%} position size."
            )]))
    else:
        qty = sized_qty

    if qty < 1:
        return None, "Calculated quantity < 1 share"

    logger.info(
        "position_sized",
        ticker=ticker, qty=qty, volatility_20d=vol,
        size_factor=round(_volatility_size_factor(vol), 3),
        requested_qty=requested_qty,
    )

    limit_price = round(price, 2)

    # ── Guard: fundable from available money ──────────────────────────────────
    # position_size_pct is a fraction of EQUITY, which says nothing about
    # whether the cash exists. Every position sizes off the same equity
    # figure, so N positions commit N x pct of it and the account quietly
    # borrows the difference. Size against real available funds instead.
    env = get_settings()
    available = (
        acct.get("buying_power", 0.0) if env.allow_margin
        else acct.get("total_cash", 0.0)
    )
    available -= equity * env.cash_reserve_pct

    if available <= 0:
        return None, (
            f"No available funds "
            f"(cash ${acct.get('total_cash', 0.0):,.2f}, "
            f"reserve ${equity * env.cash_reserve_pct:,.2f}"
            f"{'' if env.allow_margin else '; margin disabled'})"
        )

    if qty * limit_price > available:
        reduced = int(available // limit_price)
        if reduced < 1:
            return None, (
                f"Available funds ${available:,.2f} below one share at ${limit_price:,.2f}"
            )
        logger.info(
            "position_size_reduced_to_available_funds",
            user_id=user_id, ticker=ticker,
            requested_qty=qty, funded_qty=reduced, available=round(available, 2),
        )
        adjustment = " ".join(filter(None, [adjustment, (
            f"Reduced from {qty} to {reduced} shares — available funds "
            f"${available:,.2f}."
        )]))
        qty = reduced

    # ── Protective exits ──────────────────────────────────────────────────────
    blended_entry: float | None = None
    if add_to is not None:
        held_price = float(add_to.get("entry_price") or add_to.get("limit_price") or limit_price)
        blended_entry = round(
            (held_qty * held_price + qty * limit_price) / (held_qty + qty), 4
        )
        stop_price, target_price = _combined_bracket_levels(
            blended_entry=blended_entry,
            current_price=limit_price,
            existing_stop=float(add_to.get("stop_loss") or 0.0) or None,
            existing_target=float(add_to.get("take_profit") or 0.0) or None,
            analyst_stop=analyst_stop_loss,
            analyst_target=analyst_price_target,
        )
        if stop_price is None or target_price is None:
            return None, (
                f"Could not build a valid stop and target for the combined "
                f"{held_qty + qty:g}-share position — leaving the existing "
                f"bracket in place rather than replacing it with a worse one."
            )
    else:
        stop_price, target_price = _bracket_levels(
            limit_price, analyst_stop_loss, analyst_price_target
        )
        if stop_price is None or target_price is None:
            # Refuse rather than open a position nothing will ever close. The
            # app only sells on a SELL signal, which requires it to be running.
            return None, "Could not derive a valid stop-loss — refusing unprotected entry"

    return EntryPlan(
        ticker=ticker, qty=qty, limit_price=limit_price,
        stop_price=stop_price, target_price=target_price,
        account_id=account_id, adjustment=adjustment,
        add_to_trade_id=str(add_to["_id"]) if add_to is not None else None,
        held_qty=held_qty,
        blended_entry=blended_entry,
    ), None


async def _submit_entry(
    user_id: str,
    plan: EntryPlan,
    *,
    signal_score: float | None,
    signal_type: str,
    trigger: str,
    extra: dict | None = None,
) -> tuple[str, str, object | None]:
    """
    Log the trade, send it to the broker, record the outcome.

    Returns (trade_id, final_status, order_id).
    """
    now = utcnow()
    is_paper = not get_settings().is_live_trading

    if plan.is_add:
        return await _submit_add(
            user_id, plan,
            signal_score=signal_score, signal_type=signal_type, trigger=trigger,
        )

    record = {
        "user_id": user_id, "ticker": plan.ticker, "action": "BUY",
        "qty": plan.qty, "limit_price": plan.limit_price,
        "stop_loss": plan.stop_price, "take_profit": plan.target_price,
        "status": TradeStatus.PENDING,
        "signal_score": signal_score, "signal_type": signal_type,
        # Reflects the gateway session actually in use, not the user's
        # preference — the server's TRADING_MODE decides which account is hit.
        "is_paper": is_paper,
        "opened_at": now, "closed_at": None,
    }
    if plan.adjustment:
        record["reason"] = plan.adjustment
    record.update(extra or {})

    trade_id = await _log_trade(record)

    order_id = await ibkr.place_limit_order(
        plan.ticker, "BUY", plan.qty, plan.limit_price,
        account_id=plan.account_id,
        stop_loss_price=plan.stop_price,
        take_profit_price=plan.target_price,
    )

    if order_id is None:
        await _update_trade(trade_id, {
            "status": TradeStatus.REJECTED,
            "reason": "IBKR rejected or did not return order ID",
        })
        return trade_id, TradeStatus.REJECTED, None

    await _update_trade(trade_id, {"order_id": order_id})
    logger.info(
        "trade_entry_placed", user_id=user_id, ticker=plan.ticker,
        qty=plan.qty, limit_price=plan.limit_price, order_id=order_id,
        stop_loss=plan.stop_price, take_profit=plan.target_price,
        paper=is_paper, trigger=trigger, signal_type=signal_type,
    )
    await _notify_trade(
        user_id, action="BUY", ticker=plan.ticker, qty=plan.qty,
        limit_price=plan.limit_price, order_id=order_id,
        stop_loss=plan.stop_price, take_profit=plan.target_price,
        is_paper=is_paper, account_id=plan.account_id, trigger=trigger,
        signal_score=signal_score,
    )
    return trade_id, TradeStatus.PENDING, order_id


async def _submit_add(
    user_id: str,
    plan: EntryPlan,
    *,
    signal_score: float | None,
    signal_type: str,
    trigger: str,
) -> tuple[str, str, object | None]:
    """
    Add to a holding, without ever taking down the protection it already has.

    The obvious implementation — cancel the old bracket, submit the add with
    legs covering the combined position — is wrong twice over, and both faults
    are worse than the problem being solved:

      * **The cancel comes first, so the holding is naked while the add rests.**
        A day limit order can sit unfilled for hours. Protection that was
        working is gone for all of it.
      * **Legs sized to the combined position over-protect a partial fill.** IB
        activates a bracket's children when the parent *begins* to fill, so 30
        of a 100-share add going through leaves a 550-share stop against 480
        held. Firing it sells 70 shares that do not exist — a naked short, in an
        account where shorting is prohibited outright.

    So the existing bracket is left alone and the add goes out as a plain limit
    order. Nothing is cancelled, nothing is over-covered, and if the add is
    rejected there is nothing to undo. `reconcile_trades` consolidates once the
    add resolves: it cancels the old legs and places one protective pair sized
    to what is *actually* held.

    The cost is a gap the other way — between the fill and the next
    reconciliation pass (at most two minutes) the added shares have no stop,
    while the original shares keep theirs. That is under-protection, which
    costs market risk on part of a position for a couple of minutes.
    Over-protection costs a short. They are not close.

    Returns (trade_id, status, order_id), matching `_submit_entry`.
    """
    trade_id = plan.add_to_trade_id or ""
    is_paper = not get_settings().is_live_trading
    total_qty = plan.total_qty

    # Deliberately unbracketed: the position's existing stop and target stay
    # working and untouched, and consolidation happens after the fill.
    order_id = await ibkr.place_limit_order(
        plan.ticker, "BUY", plan.qty, plan.limit_price,
        account_id=plan.account_id,
    )

    if order_id is None:
        logger.warning(
            "scale_in_rejected",
            user_id=user_id, ticker=plan.ticker, qty=plan.qty,
            hint="nothing was cancelled; the position keeps the bracket it had",
        )
        return trade_id, TradeStatus.REJECTED, None

    # ── Record the pending add on the position ────────────────────────────────
    # qty stays at what is actually held. It becomes `total_qty` only when the
    # add fills, which reconcile settles — claiming 550 shares before the fill
    # would size the next exit to stock we do not own.
    # The stop and target the *combined* position should end up with are stored
    # alongside the pending add rather than written over the live ones: until
    # the add fills, the working bracket still covers only the original shares
    # and `stop_loss`/`take_profit` must keep describing it. Claiming the new
    # levels early would make an exit size itself against a bracket that is not
    # there.
    await _update_trade(trade_id, {
        "pending_add": {
            "qty": plan.qty,
            "limit_price": plan.limit_price,
            "order_id": order_id,
            "total_qty": total_qty,
            "blended_entry": plan.blended_entry,
            "combined_stop": plan.stop_price,
            "combined_target": plan.target_price,
            "submitted_at": utcnow(),
            "signal_score": signal_score,
            "trigger": trigger,
        },
    })

    logger.info(
        "scale_in_submitted",
        user_id=user_id, ticker=plan.ticker,
        add_qty=plan.qty, held_qty=plan.held_qty, total_qty=total_qty,
        limit_price=plan.limit_price, order_id=order_id,
        stop_loss=plan.stop_price, take_profit=plan.target_price,
        blended_entry=plan.blended_entry, paper=is_paper, trigger=trigger,
    )
    await _notify_trade(
        user_id, action="BUY", ticker=plan.ticker, qty=plan.qty,
        limit_price=plan.limit_price, order_id=order_id,
        stop_loss=plan.stop_price, take_profit=plan.target_price,
        is_paper=is_paper, account_id=plan.account_id,
        trigger=f"{trigger} (adding to {plan.held_qty:g} held)",
        signal_score=signal_score,
    )
    return trade_id, TradeStatus.PENDING, order_id


async def execute_entry(
    user_id: str,
    ticker: str,
    signal_score: float,
    current_price: float | None,
    analyst_stop_loss: float | None = None,
    analyst_price_target: float | None = None,
    conviction: str | None = None,
) -> None:
    """
    Act on a BUY signal for this user+ticker, as far as their mode allows.

    Under AUTO this places the order. Under MANUAL — and under SEMI_AUTO below
    the conviction bar — it records a PROPOSED trade instead and stops there,
    so the entry the agent wanted is preserved for a human decision rather than
    silently dropped.

    Logs the outcome (including skips) to the trades collection. Never raises.
    """
    try:
        settings = await _get_user_settings(user_id)
        if not settings or not settings.enabled:
            return

        now = utcnow()

        async def _skip(reason: str) -> None:
            # A standing condition is recorded once, not once per evaluation.
            # The agent re-tests every guard on every BUY evaluation — that is
            # deliberate, since a skip for "IB Gateway not connected" must
            # retry once the gateway is back — but writing an identical
            # SKIPPED row each time buried the user's real order history under
            # repeats of the same sentence. Re-stating the reason changes
            # nothing the user can act on; a *different* reason does.
            if await _already_skipped_for(user_id, ticker, reason):
                logger.debug("trade_skip_repeat", user_id=user_id, ticker=ticker, reason=reason)
                return
            await _log_trade({
                "user_id": user_id, "ticker": ticker, "action": "BUY",
                "qty": 0, "limit_price": 0.0,
                "status": TradeStatus.SKIPPED, "reason": reason,
                "signal_score": signal_score, "signal_type": "BUY",
                "is_paper": not get_settings().is_live_trading,
                "opened_at": now, "closed_at": now,
            })
            logger.info("trade_skipped", user_id=user_id, ticker=ticker, reason=reason)

        # ── Guard: signal score threshold ─────────────────────────────────────
        # Agent-only: a manual order has no signal score to test.
        if signal_score < settings.min_signal_score:
            await _skip(f"Score {signal_score:.2f} below threshold {settings.min_signal_score:.2f}")
            return

        plan, skip_reason = await _prepare_entry(
            user_id, ticker, settings, current_price,
            analyst_stop_loss, analyst_price_target,
        )
        if plan is None:
            await _skip(skip_reason or "Entry refused")
            return

        # ── Autonomy gate ─────────────────────────────────────────────────────
        # Every risk guard has passed and the order is fully specified. The only
        # remaining question is whether this user lets the agent send it alone.
        if not settings.may_auto_execute(conviction):
            await _log_trade({
                "user_id": user_id, "ticker": plan.ticker, "action": "BUY",
                "qty": plan.qty, "limit_price": plan.limit_price,
                "stop_loss": plan.stop_price, "take_profit": plan.target_price,
                "status": TradeStatus.PROPOSED,
                "signal_score": signal_score, "signal_type": "BUY",
                "conviction": conviction,
                "reason": (
                    f"{settings.mode.value} mode — awaiting your approval"
                    + (f" (conviction {conviction} below "
                       f"{settings.auto_execute_conviction})"
                       if settings.mode.value == "SEMI_AUTO" else "")
                ),
                "is_paper": not get_settings().is_live_trading,
                "opened_at": now, "closed_at": None,
            })
            logger.info(
                "trade_proposed",
                user_id=user_id, ticker=ticker, mode=settings.mode.value,
                conviction=conviction, qty=plan.qty,
            )
            return

        await _submit_entry(
            user_id, plan,
            signal_score=signal_score, signal_type="BUY", trigger="BUY signal",
            extra={"conviction": conviction} if conviction else None,
        )

    except Exception as exc:
        logger.error("execute_entry_failed", user_id=user_id, ticker=ticker, error=str(exc))


async def execute_manual_entry(
    user_id: str,
    ticker: str,
    *,
    requested_qty: int | None = None,
    limit_price: float | None = None,
    analyst_stop_loss: float | None = None,
    analyst_price_target: float | None = None,
    signal_score: float | None = None,
    source: str = "MANUAL",
) -> dict:
    """
    Place a user-initiated BUY. Raises nothing; returns a result dict.

    Runs the same guards as the automated path — see `_prepare_entry`. A user
    clicking Buy is choosing the ticker and the moment; it is not permission to
    breach the position cap or the daily-loss kill switch.

    `source` distinguishes a hand-placed order ("MANUAL") from an agent proposal
    the user approved ("PROPOSAL_APPROVED"). They are kept apart because a
    human-filtered set of the agent's picks is not a clean read of the agent.
    """
    ticker = ticker.upper().strip()

    settings = await _get_user_settings(user_id) or AutoTradeSettings()
    # Deliberately not gated on settings.enabled: that switch governs whether
    # the *agent* may act. A user placing their own order is a different act,
    # and requiring auto-trading to be on before you can press Buy would be
    # exactly backwards.

    price = limit_price
    if price is None:
        price = await _last_known_price(ticker)

    plan, skip_reason = await _prepare_entry(
        user_id, ticker, settings, price,
        analyst_stop_loss, analyst_price_target,
        requested_qty=requested_qty,
        # The whitelist restricts what the agent may pick. The user picked this.
        enforce_whitelist=False,
    )
    if plan is None:
        logger.info(
            "manual_order_refused",
            user_id=user_id, ticker=ticker, reason=skip_reason, source=source,
        )
        return {"placed": False, "status": TradeStatus.SKIPPED,
                "ticker": ticker, "reason": skip_reason}

    trade_id, status, order_id = await _submit_entry(
        user_id, plan,
        signal_score=signal_score, signal_type=source,
        trigger="manual order" if source == "MANUAL" else "approved proposal",
    )

    return {
        "placed": order_id is not None,
        "status": status,
        "ticker": plan.ticker,
        "qty": plan.qty,
        "limit_price": plan.limit_price,
        "order_id": order_id,
        "stop_loss": plan.stop_price,
        "take_profit": plan.target_price,
        "is_paper": not get_settings().is_live_trading,
        "trade_id": trade_id,
        "reason": plan.adjustment or (
            None if order_id is not None
            else "Broker rejected or did not return an order ID"
        ),
    }


async def _last_known_price(ticker: str) -> float | None:
    """Most recent price the pipeline recorded for *ticker*."""
    db = await get_db()
    doc = await db[COLL_SIGNALS].find_one(
        {"ticker": ticker.upper()}, {"current_price": 1}
    )
    return (doc or {}).get("current_price")


async def execute_exit(
    user_id: str,
    ticker: str,
    current_price: float | None,
    trigger: str = "EXIT_ALERT",
    *,
    require_enabled: bool = True,
) -> None:
    """
    Close an open BUY position for this user+ticker.

    `require_enabled` gates the *agent's* exits on the auto-trade switch. A
    user-initiated close passes False: refusing to let someone out of a position
    because they had auto-trading switched off would trap them in it, and
    `POST /trading/close/{ticker}` did exactly that — it returned success while
    silently doing nothing for every manual-mode user.

    No-op if no open position exists.
    """
    try:
        settings = await _get_user_settings(user_id)
        if require_enabled and (not settings or not settings.enabled):
            return

        db = await get_db()
        open_trade = await db[COLL_TRADES].find_one({
            "user_id": user_id, "ticker": ticker, "action": "BUY",
            "status": {"$in": list(TradeStatus.OPEN)},
            "closed_at": None,
        })
        if not open_trade:
            return

        if not ibkr.is_connected():
            logger.warning("exit_skipped_not_connected", user_id=user_id, ticker=ticker)
            # A user-initiated close must not report success it did not achieve.
            # The agent's own exits still fail quietly — it retries next cycle —
            # but someone pressing Close needs to know the order never left.
            if not require_enabled:
                raise BrokerUnavailable(
                    f"Broker not connected — the close order for {ticker} was not sent."
                )
            return

        price = current_price or 0.0
        if price <= 0:
            return

        qty = open_trade.get("qty", 0)
        # A scale-in that filled between reconciliation passes has not yet been
        # written back to `qty`, so the record can understate the holding. Add
        # the pending quantity to what we claim to own — `min(qty, held)` below
        # still keeps the sell inside what the venue actually reports, and the
        # cap exists to avoid liquidating shares of the same ticker the user
        # bought outside the agent. Without this a close sells the original 450
        # and orphans the 100 just added, with its record marked closed.
        pending_add = open_trade.get("pending_add") or {}
        if pending_add:
            qty += int(pending_add.get("qty") or 0)
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

        # Size the exit to what the broker ACTUALLY holds, not to the quantity
        # recorded when the entry was submitted. The entry is a resting limit
        # order and may never have filled — selling its nominal quantity in that
        # case does not close anything, it opens a short. Partial fills have the
        # same problem in smaller form.
        held = 0.0
        for p in await ibkr.get_positions():
            if p.get("ticker", "").upper() == ticker.upper():
                held = float(p.get("qty") or 0.0)
                break

        if held <= 0:
            # Nothing to sell. The working orders are already cancelled above,
            # so close the record out rather than leaving it open forever.
            logger.info(
                "exit_no_position_held",
                user_id=user_id, ticker=ticker, recorded_qty=qty, trigger=trigger,
                hint="entry never filled — cancelled the order instead of selling",
            )
            await db[COLL_TRADES].update_one(
                {"_id": open_trade["_id"]},
                {"$set": {
                    "closed_at": utcnow(),
                    "status": TradeStatus.CANCELLED,
                    "reason": "Entry never filled; order cancelled on exit signal",
                }},
            )
            return

        if held < qty:
            logger.warning(
                "exit_partial_position",
                user_id=user_id, ticker=ticker, recorded_qty=qty, held=held,
            )
        qty = int(min(qty, held))

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
            paper=not get_settings().is_live_trading,
        )
        await _notify_trade(
            user_id, action="SELL", ticker=ticker, qty=qty,
            limit_price=limit_price, order_id=order_id,
            is_paper=not get_settings().is_live_trading,
            account_id=account_id, trigger=trigger,
        )

    except BrokerUnavailable:
        # Deliberately not swallowed: the caller is a person waiting on an
        # answer, and this handler exists to keep the scheduled agent alive,
        # not to hide failures from the UI.
        raise
    except Exception as exc:
        logger.error("execute_exit_failed", user_id=user_id, ticker=ticker, error=str(exc))
        if not require_enabled:
            # Same reasoning — a user-initiated close reports what happened.
            raise


# ── Reconciliation ────────────────────────────────────────────────────────────
#
# Submission and outcome are separate events, and nothing pushes the second one
# to us. Orders were logged PENDING and left there: no fill price, no realised
# P&L, and `_daily_realized_loss` summing a `pnl` field nothing ever wrote — so
# the daily-loss kill switch could never fire. This closes that loop.

#: Don't judge a position closed the instant its entry fills — the positions
#: cache can lag a fill by a beat, and reading "no position" too early would
#: close the trade at a fabricated exit.
_CLOSURE_GRACE_MINUTES = 3


async def _settle_pending_add(
    trade: dict,
    statuses: dict,
    buys_by_order: dict,
    held: dict,
    account_id: str,
) -> bool:
    """
    Finish a scale-in: adopt what actually filled, then make the protective
    orders cover exactly what is held.

    Called for every open trade on every reconciliation pass — two minutes is
    the worst-case lifetime of the gap `_submit_add` deliberately accepts.

    The consolidation is driven by the venue's position, never by the order we
    sent. A partial fill, a cancel, and a full fill all end in the same place:
    cancel whatever legs are working and place one pair sized to `held`. Sizing
    protection from an order's intent rather than from the position is precisely
    how a stop ends up selling shares that were never bought.

    Returns True if anything changed.
    """
    pending = trade.get("pending_add")
    if not pending:
        return False

    ticker = str(trade.get("ticker", "")).upper()
    add_order_id = str(pending.get("order_id") or "")
    st = statuses.get(add_order_id)

    # Still working — leave it. `is_dead` covers cancelled/rejected/inactive.
    if st is not None and not (st.is_filled or st.is_dead):
        if not st.is_partial:
            return False

    actual = int(held.get(ticker, 0))
    prior_qty = int(trade.get("filled_qty") or trade.get("qty") or 0)

    if actual <= 0:
        # The position is gone — the original bracket fired while the add was
        # resting, or someone closed by hand. Cancel the add so it cannot open a
        # fresh, unprotected position into a thesis that has already exited, and
        # let phase 3 close the record.
        await ibkr.cancel_open_orders(ticker, account_id=account_id)
        await _update_trade(str(trade["_id"]), {"pending_add": None})
        logger.warning(
            "scale_in_abandoned_position_closed",
            ticker=ticker, add_order_id=add_order_id,
            hint="position exited while the add was still working",
        )
        return True

    # Adopt the venue's quantity and blend the cost basis over what really
    # filled, not over what was requested.
    added = actual - prior_qty
    update: dict = {"pending_add": None}
    if added > 0:
        prior_price = float(trade.get("entry_price") or trade.get("limit_price") or 0.0)
        fills = buys_by_order.get(add_order_id) or []
        if fills:
            add_price = sum(f.qty * f.price for f in fills) / sum(f.qty for f in fills)
        elif st is not None and st.avg_fill_price > 0:
            add_price = st.avg_fill_price
        else:
            add_price = float(pending.get("limit_price") or prior_price)
        update["qty"] = actual
        update["filled_qty"] = actual
        if prior_price > 0:
            update["entry_price"] = round(
                (prior_qty * prior_price + added * add_price) / actual, 4
            )
        update["scaled_in_at"] = utcnow()
        update["scale_ins"] = int(trade.get("scale_ins") or 0) + 1

    # Consolidate protection onto the real holding.
    stop = float(pending.get("combined_stop") or trade.get("stop_loss") or 0.0)
    target = float(pending.get("combined_target") or trade.get("take_profit") or 0.0)
    protected = await _reprotect(ticker, actual, stop, target, account_id)
    if protected:
        update["stop_loss"] = round(stop, 2)
        update["take_profit"] = round(target, 2)
        update["unprotected_since"] = None
    else:
        update["unprotected_since"] = trade.get("unprotected_since") or utcnow()

    await _update_trade(str(trade["_id"]), update)
    logger.info(
        "scale_in_settled",
        ticker=ticker, prior_qty=prior_qty, held_qty=actual, added=added,
        entry_price=update.get("entry_price"), protected=bool(protected),
    )
    return True


async def _heal_unprotected(trade: dict, held: dict, account_id: str) -> bool:
    """
    Put protection back on a filled position that has none working.

    Deliberately narrow. It acts only when the venue reports the shares held
    *and* reports no working order of any kind for the ticker — an absence, not
    a judgement. It never second-guesses a bracket that exists, never adjusts a
    level, and refuses when the stored levels do not straddle nothing useful.

    Skips a position with a pending add: `_settle_pending_add` owns that one,
    and its resting buy order counts as working anyway.
    """
    if trade.get("action") != "BUY" or trade.get("closed_at") is not None:
        return False
    if trade.get("status") != TradeStatus.FILLED or trade.get("pending_add"):
        return False

    ticker = str(trade.get("ticker", "")).upper()
    qty = int(held.get(ticker, 0))
    if qty < 1:
        return False  # not held — phase 3 decides what happened

    stop = float(trade.get("stop_loss") or 0.0)
    target = float(trade.get("take_profit") or 0.0)
    if not (0 < stop < target):
        # Nothing usable to restore. Recomputing a stop here would invent a
        # level nobody chose, on a position that may be days old.
        if not trade.get("unprotected_since"):
            logger.warning(
                "position_unprotected_no_levels",
                ticker=ticker, qty=qty,
                hint="no stop/target on the record — close or bracket by hand",
            )
        return False

    if await ibkr.has_open_orders(ticker, account_id=account_id):
        # Something is working. If we had flagged it, clear the flag.
        if trade.get("unprotected_since"):
            await _update_trade(str(trade["_id"]), {"unprotected_since": None})
        return False

    logger.warning(
        "position_found_unprotected",
        ticker=ticker, qty=qty, stop=stop, target=target,
        since=str(trade.get("unprotected_since") or "just now"),
    )
    pair = await _reprotect(ticker, qty, stop, target, account_id)
    await _update_trade(str(trade["_id"]), {
        "unprotected_since": None if pair else (trade.get("unprotected_since") or utcnow()),
    })
    return bool(pair)


async def _reprotect(
    ticker: str, qty: int, stop: float, target: float, account_id: str
) -> str | None:
    """
    Replace whatever is working on `ticker` with one stop/target pair for `qty`.

    Cancel-then-place, with the cancellation confirmed. Placing first would put
    two stops on one holding for the overlap, and cancelling without confirming
    would do the same silently — a read-only gateway session refuses cancels
    exactly as it refuses orders.

    Returns the new pair's identifier, or None if the position was left
    uncovered. A None here is a real exposure, not a warning: the caller stamps
    `unprotected_since` so it is visible in the position record and retried on
    the next pass.
    """
    if qty < 1 or not (0 < stop < target):
        logger.error(
            "reprotect_invalid", ticker=ticker, qty=qty, stop=stop, target=target,
        )
        return None

    await ibkr.cancel_open_orders(ticker, account_id=account_id)
    if await ibkr.has_open_orders(ticker, account_id=account_id):
        logger.error(
            "reprotect_aborted_orders_still_working",
            ticker=ticker,
            hint="old legs survived cancellation; not adding a second pair",
        )
        return None

    pair = await ibkr.place_protective_orders(
        ticker, qty, stop, target, account_id=account_id
    )
    if not pair:
        logger.error(
            "position_left_unprotected",
            ticker=ticker, qty=qty, stop=stop, target=target,
            hint="holding has no automatic exit; retried next reconciliation",
        )
    return pair


async def reconcile_trades() -> dict:
    """
    Bring local trade records in line with what the broker actually did.

    Phase 1 — fills:    PENDING/PARTIAL orders adopt the venue's status and
                        average fill price.
    Phase 2 — closures: a filled BUY with no remaining broker position means a
                        bracket leg fired (or someone closed it by hand); record
                        the exit and realised P&L.

    Returns a counts summary for logging. Never raises.
    """
    summary = {"filled": 0, "partial": 0, "dead": 0, "closed": 0,
               "unpriced": 0, "unreconciled": 0, "scaled": 0, "reprotected": 0}

    if not ibkr.is_connected():
        logger.debug("reconcile_skipped_broker_disconnected")
        return summary

    # A disconnected adapter answers get_positions() with [] — indistinguishable
    # from "genuinely flat". Closing every open trade against that would invent
    # exits for live positions, so demand a summary that positively reports a
    # connection before trusting any absence below.
    account = await ibkr.get_account_summary()
    if not account.get("connected"):
        logger.warning("reconcile_skipped_no_account_snapshot")
        return summary

    db = await get_db()
    account_id = account.get("account_id") or get_settings().ibkr_account_id

    open_trades = await db[COLL_TRADES].find({
        "status": {"$in": list(TradeStatus.OPEN)},
        "closed_at": None,
    }).to_list(length=1000)

    if not open_trades:
        return summary

    # ── Phase 1: adopt venue order status ────────────────────────────────────
    try:
        statuses = await ibkr.get_order_statuses(account_id)
    except Exception as exc:
        logger.warning("reconcile_order_statuses_failed", error=str(exc))
        statuses = {}

    for trade in open_trades:
        order_id = trade.get("order_id")
        if order_id is None:
            continue
        st = statuses.get(str(order_id))
        if st is None:
            # Not "unfilled" — venues age completed orders out of the working
            # set. Phase 2 settles it from position state instead of guessing.
            continue

        update: dict = {}
        if st.is_filled and trade.get("status") != TradeStatus.FILLED:
            update = {
                "status": TradeStatus.FILLED,
                "filled_qty": st.filled_qty,
                "filled_at": trade.get("filled_at") or utcnow(),
            }
            if st.avg_fill_price > 0:
                update["entry_price"] = round(st.avg_fill_price, 4)
            summary["filled"] += 1
        elif st.is_partial and trade.get("status") != TradeStatus.PARTIAL:
            update = {"status": TradeStatus.PARTIAL, "filled_qty": st.filled_qty}
            if st.avg_fill_price > 0:
                update["entry_price"] = round(st.avg_fill_price, 4)
            summary["partial"] += 1
        elif st.is_dead:
            update = {
                "status": TradeStatus.REJECTED if "REJECT" in st.status.upper()
                else TradeStatus.CANCELLED,
                "closed_at": utcnow(),
                "reason": f"broker reported {st.status}",
            }
            summary["dead"] += 1

        if update:
            await _update_trade(str(trade["_id"]), update)
            trade.update(update)
            logger.info(
                "trade_reconciled",
                ticker=trade.get("ticker"), order_id=str(order_id),
                status=update.get("status"), fill_price=update.get("entry_price"),
            )

    # ── Phase 2: recover fills the order status pass could not see ───────────
    try:
        positions = await ibkr.get_positions()
    except Exception as exc:
        logger.warning("reconcile_positions_failed", error=str(exc))
        return summary

    held = {
        str(p.get("ticker", "")).upper(): float(p.get("qty") or 0)
        for p in positions
    }

    try:
        fills = await ibkr.get_fills(lookback_minutes=1440)
    except Exception as exc:
        logger.warning("reconcile_fills_failed", error=str(exc))
        fills = []

    # An entry can fill while nothing is watching — the app restarts, or the
    # gateway session rolls — and the parent order then ages out of the order
    # set before phase 1 ever observes it filled. Its execution is still in the
    # log, so match on that rather than leaving the trade stuck at PENDING.
    #
    # Matched by order ID only. Matching on ticker alone would happily attach
    # an unrelated purchase of the same stock to this record.
    buys_by_order: dict[str, list] = {}
    for f in fills:
        if f.side == "BUY" and f.order_id:
            buys_by_order.setdefault(str(f.order_id), []).append(f)

    for trade in open_trades:
        if trade.get("action") != "BUY" or trade.get("closed_at") is not None:
            continue
        if trade.get("entry_price") and trade.get("status") == TradeStatus.FILLED:
            continue
        matched = buys_by_order.get(str(trade.get("order_id") or ""))
        if not matched:
            continue

        qty = sum(f.qty for f in matched)
        if qty <= 0:
            continue
        vwap = sum(f.qty * f.price for f in matched) / qty
        update = {
            "status": TradeStatus.FILLED,
            "entry_price": round(vwap, 4),
            "filled_qty": qty,
            "filled_at": trade.get("filled_at") or min(
                (f.executed_at for f in matched if f.executed_at), default=utcnow()
            ),
        }
        await _update_trade(str(trade["_id"]), update)
        trade.update(update)
        summary["filled"] += 1
        logger.info(
            "trade_fill_recovered",
            ticker=trade.get("ticker"), order_id=str(trade.get("order_id")),
            qty=qty, price=update["entry_price"],
        )

    # ── Phase 2b: settle scale-ins and re-protect what is uncovered ──────────
    for trade in open_trades:
        try:
            if await _settle_pending_add(trade, statuses, buys_by_order, held, account_id):
                summary["scaled"] += 1
        except Exception as exc:
            logger.error(
                "scale_in_settle_failed",
                ticker=trade.get("ticker"), error=str(exc),
            )

    # A held position with nothing working at the venue has no automatic exit.
    # Scaling in is one way to arrive here — a consolidation that could not
    # place its pair — but not the only one: a venue can age orders out, a
    # gateway session can roll, a leg can be cancelled by hand. Detecting it and
    # not fixing it would be the worst of both.
    if get_settings().enable_bracket_orders:
        for trade in open_trades:
            try:
                if await _heal_unprotected(trade, held, account_id):
                    summary["reprotected"] += 1
            except Exception as exc:
                logger.error(
                    "reprotect_check_failed",
                    ticker=trade.get("ticker"), error=str(exc),
                )

    # ── Phase 3: detect closures and price them ──────────────────────────────
    now = utcnow()
    for trade in open_trades:
        if trade.get("action") != "BUY" or trade.get("closed_at") is not None:
            continue
        # Deliberately not restricted to FILLED: a trade that filled and closed
        # entirely between two reconciliation passes never appears as FILLED,
        # and requiring that status would leave it PENDING forever.
        if trade.get("status") not in TradeStatus.OPEN:
            continue

        ticker = str(trade.get("ticker", "")).upper()
        if held.get(ticker, 0) > 0:
            continue  # still open — nothing to settle

        # An order still working has not resolved; leave it alone.
        if str(trade.get("order_id") or "") in statuses:
            continue

        # Never observed filled and no execution to prove it did. Could have
        # filled and closed unseen, or never filled at all — the record cannot
        # say which, so mark it unreconciled rather than inventing an outcome.
        if not trade.get("entry_price") or trade.get("status") == TradeStatus.PENDING:
            if not buys_by_order.get(str(trade.get("order_id") or "")):
                await _update_trade(str(trade["_id"]), {
                    "status": TradeStatus.UNRECONCILED,
                    "closed_at": now,
                    "exit_reason": "no_broker_record",
                })
                summary["unreconciled"] += 1
                logger.warning(
                    "trade_unreconcilable",
                    ticker=ticker, order_id=str(trade.get("order_id")),
                    hint="no position, no working order, and no execution in the log",
                )
                continue

        filled_at = trade.get("filled_at") or trade.get("opened_at")
        if isinstance(filled_at, datetime):
            if filled_at.tzinfo is None:
                filled_at = filled_at.replace(tzinfo=timezone.utc)
            if (now - filled_at).total_seconds() < _CLOSURE_GRACE_MINUTES * 60:
                continue

        exit_price = _latest_sell_price(fills, ticker, filled_at)
        entry_price = trade.get("entry_price") or trade.get("limit_price")
        qty = float(trade.get("filled_qty") or trade.get("qty") or 0)

        update = {
            "status": TradeStatus.CLOSED,
            "closed_at": now,
            "exit_reason": "bracket_or_manual",
        }
        if exit_price and entry_price and qty:
            update["exit_price"] = round(exit_price, 4)
            update["pnl"] = round((exit_price - float(entry_price)) * qty, 2)
            summary["closed"] += 1
        else:
            # Close it regardless so position counts and the duplicate-entry
            # guard stay accurate, but leave pnl unset rather than inventing a
            # number. IB only serves same-session executions, so a position that
            # closed on an earlier day genuinely cannot be priced from here.
            update["exit_reason"] = "closed_unpriced"
            summary["unpriced"] += 1

        await _update_trade(str(trade["_id"]), update)
        logger.info(
            "trade_closed",
            ticker=ticker, entry=entry_price, exit=update.get("exit_price"),
            pnl=update.get("pnl"), reason=update["exit_reason"],
        )

    if any(summary.values()):
        logger.info("reconcile_trades_done", **summary)
    return summary


def _latest_sell_price(fills: list, ticker: str, after: datetime | None) -> float | None:
    """
    Volume-weighted price of the SELL fills that closed `ticker` after `after`.

    A bracket exit can print in several pieces; averaging by size gives the
    price the position actually left at, where taking the last fill alone would
    report whichever fragment happened to settle last.
    """
    total_qty = 0.0
    total_notional = 0.0
    for f in fills:
        if f.ticker != ticker or f.side != "SELL":
            continue
        executed = f.executed_at
        if after is not None and executed is not None:
            if executed.tzinfo is None:
                executed = executed.replace(tzinfo=timezone.utc)
            if executed < after:
                continue
        if f.qty > 0 and f.price > 0:
            total_qty += f.qty
            total_notional += f.qty * f.price
    return (total_notional / total_qty) if total_qty > 0 else None
