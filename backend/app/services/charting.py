"""
Charting Service
─────────────────
Renders a candlestick price chart (SMA-20/50 overlay + volume panel) from
the same OHLCV bars used by feature_engineering.py. Returns PNG bytes
in-memory — nothing is written to disk, so no static volume/mount is
needed in the container.
"""
import io

import mplfinance as mpf
import pandas as pd

from app.db import COLL_RAW, get_db


async def generate_chart(ticker: str, days: int = 180) -> bytes:
    """Return PNG bytes for a candlestick chart of *ticker*'s last *days* bars."""
    ticker = ticker.upper()
    db = await get_db()

    raw_doc = await db[COLL_RAW].find_one({"ticker": ticker})
    if not raw_doc:
        raise ValueError(f"No raw data found for {ticker}. Run ingestion first.")

    bars = raw_doc.get("bars", [])[-days:]
    if len(bars) < 20:
        raise ValueError(
            f"Insufficient price history for {ticker} (need ≥20 bars, got {len(bars)})"
        )

    df = pd.DataFrame(bars)
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.set_index("date")
        .sort_index()
        .rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
    )

    buf = io.BytesIO()
    mpf.plot(
        df,
        type="candle",
        style="yahoo",
        mav=(20, 50),
        volume=True,
        title=f"\n{ticker}",
        savefig=dict(fname=buf, format="png", dpi=150, bbox_inches="tight"),
    )
    buf.seek(0)
    return buf.getvalue()
