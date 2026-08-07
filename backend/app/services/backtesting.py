"""
Backtesting Stub
────────────────
Skeleton for evaluating the signal generator on historical data.
Activate with ENABLE_BACKTESTING=true and call GET /backtest?ticker=PLTR.

This is a placeholder – swap _simulate_signals() with a proper walk-forward
loop once the scoring model is trained on labelled historical data.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def run_backtest(
    ticker: str,
    bars: list[dict],
    initial_capital: float = 10_000.0,
) -> dict:
    """
    Simple long-only backtest driven by mock signals.

    Parameters
    ----------
    ticker          : ticker symbol
    bars            : list of {"date": datetime, "close": float}
    initial_capital : starting portfolio value

    Returns
    -------
    dict with pnl, win_rate, max_drawdown, trades
    """
    if len(bars) < 30:
        return {"error": "Need at least 30 bars for backtesting"}

    trades: list[dict] = []
    cash = initial_capital
    position: Optional[dict] = None   # {"entry_price": float, "entry_date": datetime}
    peak = initial_capital
    max_drawdown = 0.0

    for i, bar in enumerate(bars):
        price = bar["close"]
        date = bar["date"]

        # Synthetic signal from a trivial rule (replace with real model output)
        signal = _synthetic_signal(bars, i)

        portfolio_value = cash + (price - position["entry_price"] if position else 0.0)
        peak = max(peak, portfolio_value)
        drawdown = (peak - portfolio_value) / peak if peak else 0.0
        max_drawdown = max(max_drawdown, drawdown)

        if signal == "BUY" and position is None and cash >= price:
            position = {"entry_price": price, "entry_date": date}
            cash -= price

        elif signal == "SELL" and position is not None:
            pnl = price - position["entry_price"]
            trades.append(
                {
                    "entry_date": position["entry_date"].isoformat(),
                    "exit_date": date.isoformat(),
                    "entry_price": round(position["entry_price"], 4),
                    "exit_price": round(price, 4),
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / position["entry_price"] * 100, 2),
                }
            )
            cash += price
            position = None

    # Close open position at last bar price
    if position is not None:
        last_price = bars[-1]["close"]
        pnl = last_price - position["entry_price"]
        trades.append(
            {
                "entry_date": position["entry_date"].isoformat(),
                "exit_date": bars[-1]["date"].isoformat(),
                "entry_price": round(position["entry_price"], 4),
                "exit_price": round(last_price, 4),
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl / position["entry_price"] * 100, 2),
                "note": "open_position_closed_at_end",
            }
        )
        cash += last_price

    total_pnl = cash - initial_capital
    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0

    logger.info(
        "backtest_complete",
        ticker=ticker,
        trades=len(trades),
        total_pnl=total_pnl,
        win_rate=win_rate,
    )

    return {
        "ticker": ticker,
        "initial_capital": initial_capital,
        "final_capital": round(cash, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_capital * 100, 2),
        "num_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "trades": trades,
        "note": "synthetic_signals_only – replace with real model for production",
    }


def _synthetic_signal(bars: list[dict], idx: int) -> str:
    """
    Trivial MA-crossover signal for backtesting demo.
    Returns "BUY", "SELL", or "HOLD".
    """
    if idx < 20:
        return "HOLD"
    closes = [b["close"] for b in bars[: idx + 1]]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    if ma5 > ma20 * 1.01:
        return "BUY"
    if ma5 < ma20 * 0.99:
        return "SELL"
    return "HOLD"
