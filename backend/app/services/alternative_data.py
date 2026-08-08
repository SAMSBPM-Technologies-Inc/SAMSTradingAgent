"""
Alternative Data Service
────────────────────────
Fetches non-standard data sources that provide informational edge:

  Short interest  : % of float shorted + days-to-cover (yfinance)
  Options flow    : Put/call ratio for nearest expiry (yfinance)
  Insider trading : Recent Form 4 buys/sells (yfinance insider_transactions)

All functions run sync yfinance calls in a thread pool so they don't block
the event loop. Failures degrade gracefully — returns partial dict.

compute_alternative_score() returns a 0-1 score:
  - Options flow P/C ratio (50%): low P/C = bullish calls dominating
  - Insider buy/sell ratio (50%): more buys = insider confidence
  Short interest is displayed only (too ambiguous to score directionally).
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def fetch_alternative_data(ticker: str) -> dict:
    """
    Fetch all alternative data sources concurrently (all run in threads).
    Returns a dict with keys: short_interest, options_flow, insider_trades, fetched_at.
    """
    ticker = ticker.upper()

    short_task   = asyncio.to_thread(_fetch_short_interest, ticker)
    options_task = asyncio.to_thread(_fetch_options_flow, ticker)
    insider_task = asyncio.to_thread(_fetch_insider_trades, ticker)

    short, options, insider = await asyncio.gather(
        short_task, options_task, insider_task,
        return_exceptions=True,
    )

    if isinstance(short, Exception):
        logger.warning("short_interest_failed", ticker=ticker, error=str(short))
        short = {"source": "error"}
    if isinstance(options, Exception):
        logger.warning("options_flow_failed", ticker=ticker, error=str(options))
        options = {"source": "error"}
    if isinstance(insider, Exception):
        logger.warning("insider_trades_failed", ticker=ticker, error=str(insider))
        insider = {"source": "error"}

    return {
        "short_interest":  short,
        "options_flow":    options,
        "insider_trades":  insider,
        "fetched_at":      datetime.now(tz=timezone.utc).isoformat(),
    }


def compute_alternative_score(alt_data: dict) -> float:
    """
    Derive a 0-1 score from alternative data.

    Components:
      Options flow P/C ratio  50%  low ratio = calls dominating = bullish
      Insider buy ratio        50%  more buys than sells = confidence
    Short interest displayed only — directional signal is ambiguous.
    """
    if not alt_data:
        return 0.5

    components: list[tuple[float, float]] = []

    # 1. Options flow — put/call ratio
    options = alt_data.get("options_flow") or {}
    pcr = options.get("put_call_ratio")
    if pcr is not None:
        # ≤0.5 = bullish (1.0), ≥1.5 = bearish (0.0), linear between
        opt_score = clamp(1.0 - (float(pcr) - 0.5) / 1.0)
        components.append((opt_score, 0.50))

    # 2. Insider buy ratio
    insider = alt_data.get("insider_trades") or {}
    buy_count  = int(insider.get("buy_count_90d")  or 0)
    sell_count = int(insider.get("sell_count_90d") or 0)
    total = buy_count + sell_count
    if total > 0:
        insider_score = buy_count / total   # 1.0 = all buys, 0.0 = all sells
        components.append((insider_score, 0.50))

    if not components:
        return 0.5

    total_weight = sum(w for _, w in components)
    return clamp(sum(s * w for s, w in components) / total_weight)


# ── Internal helpers (sync — called via asyncio.to_thread) ────────────────────

def _fetch_short_interest(ticker: str) -> dict:
    """Short interest data from yfinance.Ticker.info."""
    import yfinance as yf
    info: dict = yf.Ticker(ticker).info or {}

    short_ratio = _sf(info.get("shortRatio"))          # days to cover
    short_pct   = _sf(info.get("shortPercentOfFloat"))  # fraction e.g. 0.12

    squeeze_risk: Optional[str] = None
    if short_pct is not None and short_ratio is not None:
        if short_pct > 0.20 and short_ratio > 5:
            squeeze_risk = "HIGH"
        elif short_pct > 0.10 and short_ratio > 3:
            squeeze_risk = "MEDIUM"
        else:
            squeeze_risk = "LOW"

    return {
        "source":                 "yfinance",
        "short_ratio":            short_ratio,   # days to cover
        "short_percent_of_float": short_pct,     # 0–1 fraction
        "squeeze_risk":           squeeze_risk,  # HIGH / MEDIUM / LOW / None
    }


def _fetch_options_flow(ticker: str) -> dict:
    """
    Put/call ratio from the nearest-expiry options chain.
    High P/C (>1.5) = bearish hedging. Low (<0.7) = bullish call buying.
    """
    import yfinance as yf
    yt = yf.Ticker(ticker)

    expirations = yt.options
    if not expirations:
        return {"source": "yfinance", "put_call_ratio": None, "sentiment": None}

    exp   = expirations[0]
    chain = yt.option_chain(exp)

    put_vol  = float(chain.puts["volume"].fillna(0).sum())
    call_vol = float(chain.calls["volume"].fillna(0).sum())

    if call_vol == 0:
        return {"source": "yfinance", "expiry": exp, "put_call_ratio": None, "sentiment": None}

    pcr = round(put_vol / call_vol, 3)

    if pcr > 1.5:
        sentiment = "BEARISH"
    elif pcr > 1.0:
        sentiment = "MILDLY_BEARISH"
    elif pcr > 0.7:
        sentiment = "NEUTRAL"
    elif pcr > 0.5:
        sentiment = "MILDLY_BULLISH"
    else:
        sentiment = "BULLISH"

    return {
        "source":         "yfinance",
        "expiry":         exp,
        "put_volume":     round(put_vol),
        "call_volume":    round(call_vol),
        "put_call_ratio": pcr,
        "sentiment":      sentiment,
    }


def _fetch_insider_trades(ticker: str) -> dict:
    """
    Recent insider buy/sell transactions from yfinance.
    Scans column names defensively (they vary between yfinance versions).
    """
    import pandas as pd
    import yfinance as yf

    yt = yf.Ticker(ticker)
    try:
        df = yt.insider_transactions
    except Exception as exc:
        return {"source": "yfinance", "error": str(exc), "buy_count_90d": 0, "sell_count_90d": 0, "net_sentiment": "NEUTRAL", "recent": []}

    if df is None or (hasattr(df, "empty") and df.empty):
        return {"source": "yfinance", "buy_count_90d": 0, "sell_count_90d": 0, "net_sentiment": "NEUTRAL", "recent": []}

    # Find columns defensively
    cols = {c.lower(): c for c in df.columns}
    txn_col     = next((cols[k] for k in cols if "transaction" in k or "text" in k), None)
    shares_col  = next((cols[k] for k in cols if "shares" in k), None)
    value_col   = next((cols[k] for k in cols if "value" in k), None)
    insider_col = next((cols[k] for k in cols if "insider" in k or "name" in k), None)

    buys = sells = 0
    recent: list[dict] = []

    for idx, row in df.head(20).iterrows():
        txn_str = str(row.get(txn_col, "")).lower() if txn_col else ""
        is_buy  = "buy" in txn_str or "purchase" in txn_str
        is_sell = "sale" in txn_str or "sell" in txn_str
        if is_buy:
            buys += 1
        elif is_sell:
            sells += 1

        if len(recent) < 6:
            recent.append({
                "date":        str(idx.date()) if hasattr(idx, "date") else str(idx),
                "insider":     str(row[insider_col])[:40] if insider_col and insider_col in row else None,
                "transaction": str(row[txn_col])          if txn_col    and txn_col    in row else None,
                "shares":      int(row[shares_col]) if shares_col and shares_col in row and pd.notna(row[shares_col]) else None,
                "value":       int(row[value_col])  if value_col  and value_col  in row and pd.notna(row[value_col])  else None,
            })

    if buys > sells:
        sentiment = "BULLISH"
    elif sells > buys:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    return {
        "source":         "yfinance",
        "buy_count_90d":  buys,
        "sell_count_90d": sells,
        "net_sentiment":  sentiment,
        "recent":         recent,
    }


def _sf(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None   # NaN check
    except (TypeError, ValueError):
        return None
