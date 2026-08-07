"""
Macro Data Service
──────────────────
Fetches macro-economic indicators from FRED (Federal Reserve Economic Data).
Requires a free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html

Indicators:
    fed_funds_rate   : Federal Funds Effective Rate (%)
    treasury_10y     : 10-Year Treasury Constant Maturity Rate (%)
    treasury_2y      : 2-Year Treasury Constant Maturity Rate (%)
    yield_curve_spread: treasury_10y − treasury_2y (negative = inverted curve)
    cpi              : CPI All Urban Consumers (level)
    cpi_yoy_pct      : CPI year-over-year % change (computed from last 13 monthly obs)
    unemployment     : US Civilian Unemployment Rate (%)
    vix              : CBOE Volatility Index (daily close)

All values are float or None. Gracefully degrades if FRED_API_KEY is absent.
"""
from datetime import datetime, timezone

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SERIES: dict[str, str] = {
    "fed_funds_rate": "FEDFUNDS",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "cpi": "CPIAUCSL",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
}


async def fetch_macro_data() -> dict:
    """
    Fetch the latest value for every macro indicator.
    Returns a flat dict; individual keys are None if the series call failed.
    """
    settings = get_settings()
    api_key = settings.fred_api_key

    if not api_key:
        logger.warning(
            "fred_key_missing",
            hint="Set FRED_API_KEY in .env for macro context",
        )
        return _empty("no_api_key")

    try:
        return _fetch_fred(api_key)
    except Exception as exc:
        logger.warning("fred_fetch_failed", error=str(exc))
        return _empty("error")


# ── Internal ──────────────────────────────────────────────────────────────────

def _fetch_fred(api_key: str) -> dict:
    from fredapi import Fred  # imported lazily — only needed when key is present

    fred = Fred(api_key=api_key)
    result: dict = {
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": "fred",
    }

    for field, series_id in _SERIES.items():
        try:
            series = fred.get_series_latest_release(series_id).dropna()
            latest = round(float(series.iloc[-1]), 4)

            if field == "cpi" and len(series) >= 13:
                yoy = (series.iloc[-1] - series.iloc[-13]) / series.iloc[-13] * 100
                result["cpi_yoy_pct"] = round(yoy, 4)

            result[field] = latest
        except Exception as exc:
            logger.warning("fred_series_failed", series=series_id, error=str(exc))
            result[field] = None

    # Derived: yield curve spread (positive = normal, negative = inverted)
    t10 = result.get("treasury_10y")
    t2 = result.get("treasury_2y")
    result["yield_curve_spread"] = round(t10 - t2, 4) if (t10 is not None and t2 is not None) else None

    if "cpi_yoy_pct" not in result:
        result["cpi_yoy_pct"] = None

    logger.info(
        "macro_ok",
        fed_funds=result.get("fed_funds_rate"),
        vix=result.get("vix"),
        cpi_yoy=result.get("cpi_yoy_pct"),
        yield_spread=result.get("yield_curve_spread"),
    )
    return result


def _empty(reason: str) -> dict:
    return {
        "source": reason,
        "fed_funds_rate": None,
        "treasury_10y": None,
        "treasury_2y": None,
        "cpi": None,
        "cpi_yoy_pct": None,
        "unemployment": None,
        "vix": None,
        "yield_curve_spread": None,
    }
