"""
GET /chart/{ticker}         — candlestick chart (PNG) with SMA-20/50 overlay
GET /chart/{ticker}/series  — the same bars as JSON, for the interactive chart

The PNG is for report export, where a static image is the right answer. The
web and mobile clients render from /series instead: a server-rendered image
cannot be zoomed, cannot carry a crosshair, costs a matplotlib process per
view, and is baked in one theme.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.db import COLL_RAW, get_db
from app.dependencies import get_current_user
from app.services.charting import generate_chart
from app.utils.logger import get_logger

router = APIRouter(tags=["chart"])
logger = get_logger(__name__)

#: Below this the moving averages are mostly undefined and the chart misleads.
_MIN_BARS = 20


@router.get("/chart/{ticker}", summary="Candlestick chart (PNG) for a ticker")
async def chart(
    ticker: str,
    days: int = Query(180, ge=20, le=730, description="Number of trading days to render"),
    current_user: dict = Depends(get_current_user),
) -> Response:
    ticker = ticker.upper().strip()
    try:
        png_bytes = await generate_chart(ticker, days=days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.warning("chart_generation_failed", ticker=ticker, error=str(exc))
        raise HTTPException(status_code=502, detail="Chart generation failed")

    return Response(content=png_bytes, media_type="image/png")


@router.get("/chart/{ticker}/series", summary="OHLCV bars (JSON) for a ticker")
async def chart_series(
    ticker: str,
    days: int = Query(180, ge=_MIN_BARS, le=730, description="Number of trading days"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Raw bars for client-side charting, plus the SMA-20/50 the PNG overlays.

    The averages are computed here rather than in the browser so both renderers
    draw the same line: the PNG's `mav=(20, 50)` and a hand-rolled JS window
    would diverge at the edges, and "the chart disagrees with the chart" is a
    hard bug to see and an easy one to ship.
    """
    ticker = ticker.upper().strip()
    db = await get_db()

    raw_doc = await db[COLL_RAW].find_one({"ticker": ticker}, {"bars": 1})
    if not raw_doc:
        raise HTTPException(
            status_code=404, detail=f"No price history for {ticker}. Run an analysis first."
        )

    bars = raw_doc.get("bars") or []
    if len(bars) < _MIN_BARS:
        raise HTTPException(
            status_code=404,
            detail=f"Insufficient price history for {ticker} "
                   f"(need ≥{_MIN_BARS} bars, have {len(bars)}).",
        )

    # Sort before slicing — ingestion appends, but a re-ingest can interleave,
    # and an out-of-order series silently breaks both the SMA and the chart.
    bars = sorted(bars, key=lambda b: str(b.get("date", "")))

    closes = [float(b.get("close") or 0.0) for b in bars]
    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50)

    window = slice(max(0, len(bars) - days), len(bars))
    out_bars = [
        {
            "date": str(b.get("date", ""))[:10],
            "open": float(b.get("open") or 0.0),
            "high": float(b.get("high") or 0.0),
            "low": float(b.get("low") or 0.0),
            "close": float(b.get("close") or 0.0),
            "volume": float(b.get("volume") or 0.0),
        }
        for b in bars[window]
    ]

    def _series(values: list[float | None]) -> list[dict]:
        return [
            {"date": bar["date"], "value": round(v, 4)}
            for bar, v in zip(out_bars, values[window])
            if v is not None
        ]

    logger.info("chart_series", ticker=ticker, bars=len(out_bars))
    return {
        "ticker": ticker,
        "bars": out_bars,
        "sma_20": _series(sma_20),
        "sma_50": _series(sma_50),
    }


def _sma(values: list[float], window: int) -> list[float | None]:
    """Simple moving average, None until the window is full."""
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        out.append(running / window if i >= window - 1 else None)
    return out
