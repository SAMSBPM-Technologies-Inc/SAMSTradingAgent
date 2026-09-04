"""
GET /performance — historical signal accuracy scoped to the current user's watchlist.
GET /performance/signals — last 100 individual signal history records for watchlist tickers.
GET /performance/calibration — were the thresholds in the right place?
GET /performance/research-calibration — is the deep-research reading worth its cost?
"""
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.db import COLL_SIGNAL_HISTORY, COLL_TRADES, COLL_WATCHED, get_db
from app.dependencies import get_current_user
from app.models.stock import PerformanceResponse, SignalPerformanceRecord
from app.models.trade import TradeStatus
from app.services.benchmark import benchmark_ticker
from app.services.calibration import MIN_SAMPLES_FOR_SIGNAL, research_calibration_report
from app.services.calibration import summarise as calibration_summary
from app.services.risk_engine import RISK_MAX_FOR_BUY
from app.utils.logger import get_logger

router = APIRouter(tags=["performance"])
logger = get_logger(__name__)


@router.get("/performance", response_model=PerformanceResponse, summary="Historical signal accuracy for your watchlist")
async def get_performance(current_user: dict = Depends(get_current_user)) -> PerformanceResponse:
    user_id = str(current_user["_id"])
    db = await get_db()

    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    tickers = [d["ticker"] for d in watched]

    all_records = await db[COLL_SIGNAL_HISTORY].find(
        {"ticker": {"$in": tickers}} if tickers else {}
    ).to_list(length=10000)

    total = len(all_records)
    settled = [r for r in all_records if r.get("return_20d") is not None]

    def _empty_bucket() -> dict:
        return {"total": 0, "settled": 0, "correct": 0, "returns": [], "alphas": []}

    signal_buckets: dict[str, dict] = {
        "BUY": _empty_bucket(), "SELL": _empty_bucket(), "HOLD": _empty_bucket(),
    }
    for rec in all_records:
        sig = rec.get("signal", "HOLD")
        bucket = signal_buckets.setdefault(sig, _empty_bucket())
        bucket["total"] += 1
        ret = rec.get("return_20d")
        if ret is not None:
            bucket["settled"] += 1
            bucket["returns"].append(ret)
            if rec.get("was_correct"):
                bucket["correct"] += 1
        # Alpha is accumulated on its own, not alongside the return: records
        # settled before benchmark measurement existed have one and not the
        # other, and averaging a short alpha sample under the long sample's
        # count would present it as better evidenced than it is.
        alpha_val = rec.get("alpha_20d")
        if isinstance(alpha_val, (int, float)):
            bucket["alphas"].append(alpha_val)

    by_signal = []
    for sig, b in signal_buckets.items():
        win_rate = (b["correct"] / b["settled"]) if b["settled"] > 0 else None
        avg_ret  = (sum(b["returns"]) / len(b["returns"])) if b["returns"] else None
        avg_alpha = (sum(b["alphas"]) / len(b["alphas"])) if b["alphas"] else None
        by_signal.append(SignalPerformanceRecord(
            signal=sig, total=b["total"], settled=b["settled"], correct=b["correct"],
            win_rate=round(win_rate, 4) if win_rate is not None else None,
            avg_return_20d=round(avg_ret, 4) if avg_ret is not None else None,
            alpha_settled=len(b["alphas"]),
            avg_alpha_20d=round(avg_alpha, 4) if avg_alpha is not None else None,
        ))
    by_signal.sort(key=lambda x: x.signal)

    ticker_buckets: dict[str, dict] = defaultdict(_empty_bucket)
    for rec in all_records:
        t = rec.get("ticker", "?")
        ticker_buckets[t]["total"] += 1
        ret = rec.get("return_20d")
        if ret is not None:
            ticker_buckets[t]["settled"] += 1
            ticker_buckets[t]["returns"].append(ret)
            if rec.get("was_correct"):
                ticker_buckets[t]["correct"] += 1
        alpha_val = rec.get("alpha_20d")
        if isinstance(alpha_val, (int, float)):
            ticker_buckets[t]["alphas"].append(alpha_val)

    by_ticker = []
    for ticker, b in sorted(ticker_buckets.items()):
        wr = (b["correct"] / b["settled"]) if b["settled"] > 0 else None
        ar = (sum(b["returns"]) / len(b["returns"])) if b["returns"] else None
        aa = (sum(b["alphas"]) / len(b["alphas"])) if b["alphas"] else None
        by_ticker.append({
            "ticker": ticker, "total": b["total"], "settled": b["settled"],
            "win_rate": round(wr, 4) if wr is not None else None,
            "avg_return_20d": round(ar, 4) if ar is not None else None,
            "alpha_settled": len(b["alphas"]),
            "avg_alpha_20d": round(aa, 4) if aa is not None else None,
        })

    all_returns = [r.get("return_20d") for r in settled if r.get("return_20d") is not None]
    all_alphas = [r["alpha_20d"] for r in all_records
                  if isinstance(r.get("alpha_20d"), (int, float))]
    directional = [r for r in settled if r.get("was_correct") is not None]
    overall_wr  = (sum(1 for r in directional if r["was_correct"]) / len(directional)) if directional else None
    overall_avg = (sum(all_returns) / len(all_returns)) if all_returns else None
    overall_alpha = (sum(all_alphas) / len(all_alphas)) if all_alphas else None

    logger.info(
        "performance_fetched", total=total, settled=len(settled),
        with_alpha=len(all_alphas), user_id=user_id,
    )
    return PerformanceResponse(
        total_signals=total, settled_signals=len(settled),
        overall_win_rate=round(overall_wr, 4) if overall_wr is not None else None,
        overall_avg_return_20d=round(overall_avg, 4) if overall_avg is not None else None,
        benchmark_ticker=benchmark_ticker(),
        alpha_settled_signals=len(all_alphas),
        overall_avg_alpha_20d=round(overall_alpha, 4) if overall_alpha is not None else None,
        by_signal=by_signal, by_ticker=by_ticker,
    )


@router.get("/performance/trades", summary="Realised trading performance from executed orders")
async def get_trade_performance(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    What the executed trades actually did, as distinct from whether the signals
    were right.

    Signal accuracy takes ~28 days to settle and only scores BUY and SELL, so
    with the current signal mix it will rest on a handful of records for weeks.
    Realised P&L is available the moment a position closes, and it is the
    measure that reflects money.

    Manual and signal-driven trades are reported separately and never pooled: a
    hand-seeded position says nothing about whether the signal engine works, and
    averaging the two produces a number that describes neither.
    """
    user_id = str(current_user["_id"])
    db = await get_db()

    trades = await db[COLL_TRADES].find({"user_id": user_id}).to_list(length=5000)

    def cost_basis(t: dict) -> float | None:
        """
        What this trade actually tied up, or None if it cannot be known.

        `entry_price` is the *blended* cost after every scale-in and
        `filled_qty` the total shares held, so this is the whole position's
        basis and not just its first leg — which is also exactly what `pnl` is
        computed against, so the two can be divided.

        None rather than zero for the usual reason: a missing basis in the
        denominator would inflate the percentage without bound, and a basis
        silently taken as zero is how a return of 4% comes to read as 400%.
        """
        entry = t.get("entry_price") or t.get("limit_price")
        qty = t.get("filled_qty") or t.get("qty")
        if not entry or not qty:
            return None
        return abs(float(entry) * float(qty))

    def return_on(rows: list[dict], pnl_key: str) -> tuple[float | None, float | None]:
        """
        (capital deployed, return on it) over the trades that have both.

        The numerator is re-summed over the rows with a usable basis rather
        than reusing the headline P&L, so a trade counted in one is counted in
        the other. Mixing the two sets would divide the P&L of every closed
        trade by the capital of only some of them — a bias in one direction,
        which is the same failure `net_unknown` exists to avoid.
        """
        pairs = [(t, b) for t in rows if (b := cost_basis(t)) is not None]
        deployed = sum(b for _, b in pairs)
        if not pairs or deployed <= 0:
            return None, None
        return round(deployed, 2), round(sum(t[pnl_key] for t, _ in pairs) / deployed, 4)

    def summarise(rows: list[dict]) -> dict:
        closed = [t for t in rows if t.get("status") == TradeStatus.CLOSED]
        priced = [t for t in closed if t.get("pnl") is not None]
        wins = [t for t in priced if t["pnl"] > 0]
        losses = [t for t in priced if t["pnl"] < 0]
        open_rows = [t for t in rows if t.get("status") in TradeStatus.OPEN]
        total = sum(t["pnl"] for t in priced)

        # ── Net of commission ────────────────────────────────────────────────
        # Gross P&L is what the position did; net is what reached the account.
        # On a small account the gap is not a rounding detail — a $200 entry
        # pays the same fixed ticket as a $20,000 one, so the round trip can
        # cost 0.5% against 0.005%, and a strategy that looks profitable gross
        # can lose money net.
        #
        # Only trades whose fee total is known to be complete are counted, and
        # the rest are reported as `net_unknown` rather than folded in at zero.
        # Zero would be a *systematic* understatement of cost — flattering in
        # one direction every time — which is worse than an honest gap. Trades
        # that closed before this shipped have no commission recorded and can
        # never get one: IB only serves the current session's executions.
        netted = [
            t for t in priced
            if t.get("pnl_net") is not None and t.get("commission_complete")
        ]
        net_total = sum(t["pnl_net"] for t in netted)
        fees = sum(float(t.get("commission_paid") or 0.0) for t in netted)
        net_wins = [t for t in netted if t["pnl_net"] > 0]
        # The headline number: how many trades were profitable before fees and
        # not after. This is the one that should drive the sizing thresholds.
        flipped = [t for t in netted if t["pnl"] > 0 >= t["pnl_net"]]

        # ── Benchmark-relative ───────────────────────────────────────────────
        # What the trade earned against what the market handed out over the
        # same days. A win rate computed on raw P&L cannot separate a good
        # entry from a rising tide, and the sizing and threshold arguments this
        # endpoint feeds have been made on the raw number alone.
        #
        # Counted on its own denominator for the same reason `netted` is: only
        # trades closed after benchmark measurement shipped carry an alpha, and
        # a position whose benchmark could not be read stays None rather than
        # zero, which would have credited the whole return as skill.
        with_alpha = [t for t in priced if isinstance(t.get("alpha"), (int, float))]
        alpha_wins = [t for t in with_alpha if t["alpha"] > 0]
        avg_alpha = (
            sum(t["alpha"] for t in with_alpha) / len(with_alpha)
            if with_alpha else None
        )
        bench_rets = [
            t["benchmark_return"] for t in with_alpha
            if isinstance(t.get("benchmark_return"), (int, float))
        ]

        # ── Return on the capital that earned it ─────────────────────────────
        # A dollar figure cannot be compared between two buckets that traded
        # different amounts of money: $400 made on $40,000 and $400 made on
        # $4,000 are not the same result, and on this account the agent and the
        # trader size positions differently. Percentages are what makes the
        # head-to-head mean anything.
        #
        # Note what the denominator is and is not. It sums each round trip's
        # own basis, so ten sequential $1,000 trades deploy $10,000 — it is
        # capital *turned over*, not capital at risk and not account size.
        # That is the right base for "did these trades earn their keep" and the
        # wrong one for "how did the account do"; the tiles above use net
        # liquidation for the latter.
        deployed, roc = return_on(priced, "pnl")
        deployed_net, roc_net = return_on(netted, "pnl_net")

        return {
            "benchmark_ticker": benchmark_ticker(),
            "alpha_measured": len(with_alpha),
            # Priced, but closed before benchmark measurement existed or with a
            # benchmark series that could not be read. Never folded in at zero.
            "alpha_unknown": len(priced) - len(with_alpha),
            "avg_alpha": round(avg_alpha, 4) if avg_alpha is not None else None,
            "alpha_win_rate": (
                round(len(alpha_wins) / len(with_alpha), 4) if with_alpha else None
            ),
            # What simply holding the index over those same windows returned —
            # the bar the trades had to clear.
            "avg_benchmark_return": (
                round(sum(bench_rets) / len(bench_rets), 4) if bench_rets else None
            ),
            # Trades that made money and still lost to the index. The
            # benchmark-relative twin of `wins_lost_to_fees`, and the number
            # that says whether the agent is adding anything at all.
            "wins_lost_to_benchmark": sum(
                1 for t in with_alpha if t["pnl"] > 0 and t["alpha"] < 0
            ),
            "realised_pnl_net": round(net_total, 2) if netted else None,
            "commission_paid": round(fees, 2) if netted else None,
            # Fees as a share of the gross P&L they were charged against —
            # the drag, stated as the fraction of the result it consumed.
            "commission_drag": (
                round(fees / abs(sum(t["pnl"] for t in netted)), 4)
                if netted and sum(t["pnl"] for t in netted) != 0 else None
            ),
            "win_rate_net": round(len(net_wins) / len(netted), 4) if netted else None,
            "netted": len(netted),
            # Priced, but with no usable commission figure — pre-existing
            # trades, or a venue that never reported one.
            "net_unknown": len(priced) - len(netted),
            "wins_lost_to_fees": len(flipped),
            "closed": len(closed),
            # Closed but unpriceable — the exit exists, the execution behind it
            # does not. Reported separately so the win rate is never computed
            # over a denominator that quietly excludes them.
            "closed_unpriced": len(closed) - len(priced),
            "open": len(open_rows),
            "unreconciled": sum(1 for t in rows if t.get("status") == TradeStatus.UNRECONCILED),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(priced), 4) if priced else None,
            "realised_pnl": round(total, 2) if priced else None,
            # Capital deployed and what came back as a fraction of it, gross
            # and net. Each pair shares a denominator with its own numerator.
            "capital_deployed": deployed,
            "return_on_capital": roc,
            "capital_deployed_net": deployed_net,
            "return_on_capital_net": roc_net,
            "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else None,
            "best": round(max((t["pnl"] for t in priced), default=0), 2) if priced else None,
            "worst": round(min((t["pnl"] for t in priced), default=0), 2) if priced else None,
        }

    # signal_type marks how the order came to exist. Three buckets, never
    # pooled, because they answer different questions:
    #
    #   signal_driven — the agent chose it and placed it unattended. The only
    #                   clean read of the engine.
    #   approved      — the agent chose it, a human approved it. Biased upward
    #                   by whatever the human declined, so it measures the
    #                   pair, not the agent.
    #   manual        — a human chose it. Says nothing about the engine.
    _SIGNAL_TYPES = {"BUY", "SELL", "EXIT_ALERT"}
    signal_driven = [t for t in trades if t.get("signal_type") in _SIGNAL_TYPES]
    approved = [t for t in trades if t.get("signal_type") == "PROPOSAL_APPROVED"]
    manual = [
        t for t in trades
        if t.get("signal_type") not in _SIGNAL_TYPES
        and t.get("signal_type") != "PROPOSAL_APPROVED"
    ]

    recent = sorted(
        [t for t in trades if t.get("status") in (TradeStatus.CLOSED, TradeStatus.UNRECONCILED)],
        key=lambda t: t.get("closed_at") or t.get("opened_at"),
        reverse=True,
    )[:50]

    # A fourth bucket, and the one exception to "never pool", because it
    # answers a question the three cannot: *whose ideas were better* — the
    # tool's or the trader's. Both auto and semi trades were the agent's pick;
    # the difference between them is who pressed the button, which matters for
    # measuring the engine and not at all for measuring whose idea it was.
    #
    # It is `agent_originated` rather than `agent` so that nothing reads it as
    # "the agent's performance". It is not a clean measure of the engine and
    # must never be presented as one: half of it is filtered by a human, so a
    # trader who declines badly makes it look worse and one who declines well
    # makes it look better. `signal_driven` remains the only clean read, the
    # three original buckets are untouched, and every surface that shows this
    # must also show the split it was built from.
    agent_originated = signal_driven + approved

    return {
        "signal_driven": summarise(signal_driven),
        "exits": _exit_breakdown(trades),
        "approved": summarise(approved),
        "manual": summarise(manual),
        "agent_originated": summarise(agent_originated),
        "all": summarise(trades),
        "recent_closed": [
            {
                "ticker": t.get("ticker"),
                "action": t.get("action"),
                "qty": t.get("filled_qty") or t.get("qty"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "pnl": t.get("pnl"),
                "pnl_net": t.get("pnl_net"),
                "return_pct": t.get("return_pct"),
                "benchmark_return": t.get("benchmark_return"),
                "alpha": t.get("alpha"),
                "commission_paid": t.get("commission_paid"),
                # False marks a fee total that is a floor, not a figure — at
                # least one execution never reported. The row shows gross only.
                "commission_complete": bool(t.get("commission_complete")),
                "scale_ins": int(t.get("scale_ins") or 0),
                "pnl_pct": (
                    round((t["exit_price"] - t["entry_price"]) / t["entry_price"], 4)
                    if t.get("exit_price") and t.get("entry_price") else None
                ),
                "stop_loss": t.get("stop_loss"),
                "take_profit": t.get("take_profit"),
                # What the position did between entry and exit. `mfe_pct` beside
                # `return_pct` is the whole give-back story on one row: a trade
                # that shows +0.09 and −0.05 ran nine percent and stopped out.
                "mfe_pct": t.get("mfe_pct"),
                "mae_pct": t.get("mae_pct"),
                "gave_back_pct": t.get("gave_back_pct"),
                "stop_raised_by": t.get("stop_raised_by"),
                # Both halves of the story on one closed row: why it was
                # bought, and why it was sold. A realised result read without
                # the thesis behind it teaches nothing about the thesis.
                "entry_reason": t.get("entry_reason"),
                "exit_reason": t.get("exit_reason"),
                # The code behind the sentence, so the client can mark an exit
                # the agent chose differently from one a stop fired.
                "exit_trigger": t.get("exit_trigger"),
                "status": t.get("status"),
                "signal_type": t.get("signal_type"),
                "is_paper": t.get("is_paper", True),
                "opened_at": t.get("opened_at"),
                "closed_at": t.get("closed_at"),
            }
            for t in recent
        ],
    }


def _exit_breakdown(trades: list[dict]) -> dict:
    """
    How positions actually ended, and how much of the move was still there.

    The three buckets above answer "who chose this trade". None of them answers
    "how did it end", which for a strategy whose whole thesis is buying weakness
    and selling strength is the other half of the question. `/performance/trades`
    could not previously say how many exits were targets and how many were
    stop-outs, because reconciliation stamped one value on both.

    Grouped by `exit_trigger`, which is a *code* and never a guess: a close the
    record cannot explain lands in `unknown` rather than being assigned to the
    likelier leg. Rows from before excursions were recorded have no `mfe_pct`
    and are counted in `n` but excluded from `avg_mfe_pct` — the same
    absent-versus-zero rule as `alpha`, and for the same reason: folding them in
    at zero would report every unmeasured trade as having given nothing back.

    `avg_return_at_first_exit_alert_pct` is the same kind of number for the
    setup scan's overbought flag, which sells nothing and never has. Against
    `avg_return_pct` it says whether taking that alert would have beaten
    holding. It carries `alerted_n` rather than reusing `measured_n`: a position
    can close having never drawn an alert, and that is an absence, not a zero.

    `avg_gave_back_pct` is the number a trailing stop should be argued from.
    Against `avg_return_pct` in the same bucket it says what the current static
    exit costs: a stop-loss bucket returning −5% that averaged +6% at its peak
    is a different system from one that never rose at all, and until now those
    two were the same row.
    """
    closed = [t for t in trades if t.get("status") == TradeStatus.CLOSED]

    def _mean(rows: list[dict], field: str) -> float | None:
        vals = [float(r[field]) for r in rows if r.get(field) is not None]
        return round(sum(vals) / len(vals), 6) if vals else None

    buckets: dict[str, list[dict]] = {}
    for t in closed:
        buckets.setdefault(t.get("exit_trigger") or "unknown", []).append(t)

    out: dict[str, Any] = {}
    for name, rows in buckets.items():
        priced = [t for t in rows if t.get("pnl") is not None]
        measured = [t for t in rows if t.get("mfe_pct") is not None]
        out[name] = {
            "n": len(rows),
            "significant": len(rows) >= MIN_SAMPLES_FOR_SIGNAL,
            "wins": sum(1 for t in priced if t["pnl"] > 0),
            "total_pnl": round(sum(t["pnl"] for t in priced), 2) if priced else None,
            "avg_return_pct": _mean(rows, "return_pct"),
            # Sample size of its own, because the excursion series starts later
            # than the trade series and a mean over four of forty rows must not
            # read as a mean over forty.
            "measured_n": len(measured),
            "avg_mfe_pct": _mean(rows, "mfe_pct"),
            "avg_mae_pct": _mean(rows, "mae_pct"),
            "avg_gave_back_pct": _mean(rows, "gave_back_pct"),
            # The advisory overbought flag, finally measurable. Against
            # `avg_return_pct` in the same bucket this is the counterfactual for
            # wiring EXIT_ALERT to an order: what the position was worth when the
            # flag first fired, versus what it actually exited at. Its own `n`,
            # because a position can close having never drawn an alert and that
            # is not a zero — the `commission_paid` rule.
            "alerted_n": len([
                t for t in rows
                if t.get("return_at_first_exit_alert_pct") is not None
            ]),
            "avg_return_at_first_exit_alert_pct": _mean(
                rows, "return_at_first_exit_alert_pct",
            ),
        }
    return out


@router.get("/performance/signals", summary="Recent individual signal history for your watchlist")
async def get_signal_history(current_user: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    user_id = str(current_user["_id"])
    db = await get_db()

    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    tickers = [d["ticker"] for d in watched]

    cursor = db[COLL_SIGNAL_HISTORY].find(
        {"ticker": {"$in": tickers}} if tickers else {},
        {"_id": 0},
    ).sort("generated_at", -1).limit(100)

    records = await cursor.to_list(length=100)

    result: list[dict[str, Any]] = []
    for rec in records:
        result.append({
            "ticker":          rec.get("ticker"),
            "signal":          rec.get("signal"),
            "score":           rec.get("score"),
            "conviction":      rec.get("conviction"),
            "price_at_signal": rec.get("price_at_signal"),
            "return_20d":      rec.get("return_20d"),
            "was_correct":     rec.get("was_correct"),
            "generated_at":    rec.get("generated_at"),
            "analyst_used":    rec.get("analyst_used"),
        })

    logger.info("signal_history_fetched", count=len(result), user_id=user_id)
    return result


@router.get(
    "/performance/calibration",
    summary="Were the signal thresholds in the right place?",
)
async def get_calibration(
    ticker: Optional[str] = Query(None, description="Restrict to one ticker."),
    apply_risk_gate: bool = Query(
        True, description="Also apply the BUY risk veto when sweeping thresholds."
    ),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Compare emitted signals against their realised 20-day returns.

    The engine has always written this history and never read it, so
    BUY_THRESHOLD has stayed where it was originally guessed while the evidence
    to place it accumulated unused.

    Read `score_ranks_outcomes` first. If the composite does not rank outcomes,
    no threshold is the right threshold and the answer is to fix the score, not
    move the line. Every row carries `n` and a `significant` flag — under
    `min_samples_for_signal` settled records a win rate is anecdote, and the
    endpoint says so rather than returning a confident-looking percentage.
    """
    user_id = str(current_user["_id"])
    db = await get_db()

    watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
    tickers = [d["ticker"] for d in watched]

    query: dict[str, Any] = {"return_20d": {"$ne": None}}
    if ticker:
        query["ticker"] = ticker.upper()
    elif tickers:
        query["ticker"] = {"$in": tickers}

    records = await db[COLL_SIGNAL_HISTORY].find(
        query,
        {"ticker": 1, "score": 1, "signal": 1, "confidence": 1,
         "risk_score": 1, "return_20d": 1, "generated_at": 1,
         "alpha_20d": 1, "benchmark_return_20d": 1,
         # Kept in step with the projection in `calibration.calibration_report`
         # — two explicit field lists over the same collection, and a field
         # added to one and not the other is a silent hole.
         "analyst_used": 1, "analyst_override": 1, "analyst_wanted": 1,
         "rule_signal": 1, "exit_score": 1,
         # The dip-buy setup behind the verdict, so the strategy this system
         # actually runs can be measured rather than assumed. Carried here for
         # the same reason as the override fields, and it is the same trap:
         # a field named in one of these two lists and not the other is dropped
         # silently by Mongo and the report describes nothing.
         "technical_score": 1, "setup_trigger": 1,
         "rsi_14": 1, "stoch_rsi": 1, "bb_pct": 1,
         "macd_bullish": 1, "ma_cross_bullish": 1,
         },
    ).to_list(length=100_000)

    report = calibration_summary(
        records, risk_max=RISK_MAX_FOR_BUY if apply_risk_gate else None
    )
    report["ticker"] = ticker.upper() if ticker else None

    logger.info(
        "calibration_report",
        user_id=user_id,
        ticker=ticker or "watchlist",
        settled=report["settled_records"],
        ranks=report["score_ranks_outcomes"],
    )
    return report


@router.get(
    "/performance/research-calibration",
    summary="Does the deep-research reading actually predict anything?",
)
async def get_research_calibration(
    ticker: Optional[str] = Query(None, description="Restrict to one ticker"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    The only evidence there is on whether the agent path earns its cost.

    Every dossier written more than `RESEARCH_OUTCOME_HORIZON_DAYS` ago is
    graded against what the name actually did, measured as alpha rather than
    raw return — a BULLISH reading of a stock that rose 4% while the index rose
    9% was not right, and counting it as a win is how a desk mistakes exposure
    for skill.

    Three readings come back. `conviction_buckets` asks whether a higher
    research conviction earns a higher forward alpha; a flat curve means the
    number separates nothing and no veto floor is the right floor.
    `assessment_accuracy` scores each verdict, excluding NEUTRAL and
    ungradeable windows from the denominator rather than counting them as
    misses. And `veto_counterfactual` answers the question
    `RESEARCH_VETO_ENABLED` has never had an answer to: did the names research
    would have refused actually do worse? If they did not, the guard is
    refusing trades for no return.

    Reports; does not tune. Nothing here moves a threshold — the same standing
    refusal as the signal calibration endpoint, and for the same reason.

    Unscoped by watchlist deliberately: dossiers are a shared series, not
    per-user, and slicing them by whose list a ticker happens to be on would
    thin every bucket for no gain in relevance.
    """
    report = await research_calibration_report(ticker, str(current_user["_id"]))
    logger.info(
        "research_calibration_fetched",
        user_id=str(current_user["_id"]),
        ticker=ticker or "ALL",
        graded=report["graded_dossiers"],
    )
    return report
