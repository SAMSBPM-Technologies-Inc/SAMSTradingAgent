"""
Fundamentals Service
────────────────────
Fetches financial-statement ratios and key metrics via yfinance.

All values are coerced to float or None — no exceptions propagate to the caller.

Fields returned:
    Valuation  : pe_ratio, pb_ratio, ps_ratio, peg_ratio
    Size       : market_cap, enterprise_value
    Earnings   : eps_ttm, revenue_growth_yoy, earnings_growth_yoy
    Health     : debt_to_equity, free_cash_flow, profit_margin, return_on_equity
    Levels     : week52_high, week52_low, price_to_52w_high
    Calendar   : next_earnings_date
    Analyst    : analyst_target_price, analyst_recommendation, analyst_count
    Context    : sector, industry
"""
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def fetch_fundamentals(ticker: str) -> dict:
    """
    Return a fundamentals dict for *ticker*.
    Gracefully returns a partial dict with an ``error`` key on failure.
    """
    ticker = ticker.upper()
    try:
        return _fetch(ticker)
    except Exception as exc:
        logger.warning("fundamentals_fetch_failed", ticker=ticker, error=str(exc))
        return {"ticker": ticker, "source": "yfinance", "error": str(exc)}


# ── Internal ──────────────────────────────────────────────────────────────────

def _fetch(ticker: str) -> dict:
    yt = yf.Ticker(ticker)
    info: dict = yt.info or {}

    def get(key) -> Optional[float]:
        return safe_float(info.get(key))

    current_price = get("currentPrice") or get("regularMarketPrice")
    week52_high = get("fiftyTwoWeekHigh")
    week52_low = get("fiftyTwoWeekLow")

    price_to_52w_high: Optional[float] = None
    if current_price and week52_high and week52_high > 0:
        price_to_52w_high = round(current_price / week52_high, 4)

    next_earnings = _next_earnings_date(yt)

    result = {
        "ticker": ticker,
        "source": "yfinance",
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        # Valuation
        "pe_ratio": get("trailingPE"),
        "pb_ratio": get("priceToBook"),
        "ps_ratio": get("priceToSalesTrailing12Months"),
        "peg_ratio": get("pegRatio"),
        # Size
        "market_cap": get("marketCap"),
        "enterprise_value": get("enterpriseValue"),
        # Earnings
        "eps_ttm": get("trailingEps"),
        "revenue_growth_yoy": get("revenueGrowth"),       # e.g. 0.12 = 12 %
        "earnings_growth_yoy": get("earningsGrowth"),
        # Financial health
        "debt_to_equity": get("debtToEquity"),
        "free_cash_flow": get("freeCashflow"),
        "profit_margin": get("profitMargins"),
        "return_on_equity": get("returnOnEquity"),
        # Price levels
        "week52_high": week52_high,
        "week52_low": week52_low,
        "price_to_52w_high": price_to_52w_high,           # 1.0 = at 52w high
        # Calendar
        "next_earnings_date": next_earnings,
        # Analyst consensus
        "analyst_target_price": get("targetMeanPrice"),
        "analyst_recommendation": info.get("recommendationKey"),  # "buy", "hold", etc.
        "analyst_count": get("numberOfAnalystOpinions"),
        # Sector context
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }

    logger.info(
        "fundamentals_ok",
        ticker=ticker,
        pe=result["pe_ratio"],
        market_cap=result["market_cap"],
        revenue_growth=result["revenue_growth_yoy"],
        next_earnings=next_earnings,
    )
    return result


def _next_earnings_date(yt: yf.Ticker) -> Optional[str]:
    """Return the next earnings date as an ISO string, or None."""
    try:
        cal = yt.calendar
        if cal is None:
            return None
        # calendar may be a DataFrame or a dict depending on yfinance version
        if hasattr(cal, "empty") and cal.empty:
            return None
        if hasattr(cal, "loc") and "Earnings Date" in cal.index:
            ed = cal.loc["Earnings Date"].dropna()
            if not ed.empty:
                return str(ed.iloc[0])
        if isinstance(cal, dict) and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            if dates:
                return str(dates[0])
    except Exception:
        pass
    return None
