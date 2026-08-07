"""
GET /performance — historical signal accuracy scoped to the current user's watchlist.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends

from app.db import COLL_SIGNAL_HISTORY, COLL_WATCHED, get_db
from app.dependencies import get_current_user
from app.models.stock import PerformanceResponse, SignalPerformanceRecord
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

    signal_buckets: dict[str, dict] = {
        "BUY":  {"total": 0, "settled": 0, "correct": 0, "returns": []},
        "SELL": {"total": 0, "settled": 0, "correct": 0, "returns": []},
        "HOLD": {"total": 0, "settled": 0, "correct": 0, "returns": []},
    }
    for rec in all_records:
        sig = rec.get("signal", "HOLD")
        bucket = signal_buckets.setdefault(sig, {"total": 0, "settled": 0, "correct": 0, "returns": []})
        bucket["total"] += 1
        ret = rec.get("return_20d")
        if ret is not None:
            bucket["settled"] += 1
            bucket["returns"].append(ret)
            if rec.get("was_correct"):
                bucket["correct"] += 1

    by_signal = []
    for sig, b in signal_buckets.items():
        win_rate = (b["correct"] / b["settled"]) if b["settled"] > 0 else None
        avg_ret  = (sum(b["returns"]) / len(b["returns"])) if b["returns"] else None
        by_signal.append(SignalPerformanceRecord(
            signal=sig, total=b["total"], settled=b["settled"], correct=b["correct"],
            win_rate=round(win_rate, 4) if win_rate is not None else None,
            avg_return_20d=round(avg_ret, 4) if avg_ret is not None else None,
        ))
    by_signal.sort(key=lambda x: x.signal)

    ticker_buckets: dict[str, dict] = defaultdict(lambda: {"total": 0, "settled": 0, "correct": 0, "returns": []})
    for rec in all_records:
        t = rec.get("ticker", "?")
        ticker_buckets[t]["total"] += 1
        ret = rec.get("return_20d")
        if ret is not None:
            ticker_buckets[t]["settled"] += 1
            ticker_buckets[t]["returns"].append(ret)
            if rec.get("was_correct"):
                ticker_buckets[t]["correct"] += 1

    by_ticker = []
    for ticker, b in sorted(ticker_buckets.items()):
        wr = (b["correct"] / b["settled"]) if b["settled"] > 0 else None
        ar = (sum(b["returns"]) / len(b["returns"])) if b["returns"] else None
        by_ticker.append({
            "ticker": ticker, "total": b["total"], "settled": b["settled"],
            "win_rate": round(wr, 4) if wr is not None else None,
            "avg_return_20d": round(ar, 4) if ar is not None else None,
        })

    all_returns = [r.get("return_20d") for r in settled if r.get("return_20d") is not None]
    directional = [r for r in settled if r.get("was_correct") is not None]
    overall_wr  = (sum(1 for r in directional if r["was_correct"]) / len(directional)) if directional else None
    overall_avg = (sum(all_returns) / len(all_returns)) if all_returns else None

    logger.info("performance_fetched", total=total, settled=len(settled), user_id=user_id)
    return PerformanceResponse(
        total_signals=total, settled_signals=len(settled),
        overall_win_rate=round(overall_wr, 4) if overall_wr is not None else None,
        overall_avg_return_20d=round(overall_avg, 4) if overall_avg is not None else None,
        by_signal=by_signal, by_ticker=by_ticker,
    )
