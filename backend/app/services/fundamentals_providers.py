"""
Fundamentals Providers
──────────────────────
Massive (Polygon.io) and Alpha Vantage clients, plus the rate limiting both
need.

Why this exists: yfinance 429s from the production host, so `fundamental_score`
sat at its 0.5 fallback for every ticker. That is 0.15 of the composite weight
contributing nothing, and with catalyst also near zero it left the composite
ceiling at 0.680 against a 0.700 BUY threshold — the engine could not emit a
directional signal at all.

Division of labour, chosen from what `_fundamental_score` actually weights:

    Alpha Vantage OVERVIEW   one call, covers 75% of the score weight
                             (analyst consensus 30%, revenue growth 25%,
                             P/E 20%) plus sector and target price
    Massive financials       the remaining 25% (free cash flow 15%,
                             debt/equity 10%), computed from the raw
                             statements, plus market cap and a P/E fallback

Neither is a per-cycle data source: **both are limited to roughly 5 requests a
minute**, and Alpha Vantage's free tier allows only 25 a day. Fundamentals move
quarterly, so callers must read from cache and let a background job refresh it
slowly — see `fundamentals.py`.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MASSIVE_BASE = "https://api.massive.com"
_ALPHA_BASE = "https://www.alphavantage.co/query"

#: Both providers cut off at 5 requests/minute on the free tiers. Pace below
#: that rather than at it — a burst that trips the limit costs a retry, and
#: nothing here is latency-sensitive.
_MASSIVE_MIN_INTERVAL = 13.0
_ALPHA_MIN_INTERVAL = 13.0

_HTTP_TIMEOUT = 25.0


class _RateLimiter:
    """
    Minimum spacing between calls, shared across coroutines.

    A token bucket would allow the initial burst that provoked the 429s in the
    first place. Fixed spacing is the conservative choice and costs nothing on
    a background refresh.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last = time.monotonic()


_massive_limiter = _RateLimiter(_MASSIVE_MIN_INTERVAL)
_alpha_limiter = _RateLimiter(_ALPHA_MIN_INTERVAL)


def _num(value: Any) -> Optional[float]:
    """
    Coerce to float, mapping absent/sentinel values to None.

    Alpha Vantage returns the strings "None" and "-" for missing figures rather
    than omitting the field; passing those through as 0.0 would score a company
    as having zero debt or zero growth.
    """
    if value in (None, "", "None", "-", "NA", "N/A"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


# ── Massive (Polygon.io) ──────────────────────────────────────────────────────

async def fetch_massive(ticker: str) -> dict:
    """
    Financial statements and reference data for `ticker`.

    Returns {} when unavailable — the caller keeps whatever it already had
    rather than overwriting good data with a gap.
    """
    settings = get_settings()
    key = settings.massive_api_key
    if not key:
        return {}

    ticker = ticker.upper()
    headers = {"Authorization": f"Bearer {key}"}
    out: dict = {}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
            # Two annual periods: year-over-year revenue growth needs a prior
            # comparison point, and one period alone cannot supply it.
            await _massive_limiter.wait()
            fin = await client.get(
                f"{_MASSIVE_BASE}/vX/reference/financials",
                params={"ticker": ticker, "timeframe": "annual", "limit": 2,
                        "order": "desc", "sort": "period_of_report_date"},
            )
            if fin.status_code == 200:
                out.update(_parse_massive_financials(fin.json().get("results") or []))
            elif fin.status_code == 429:
                logger.warning("massive_rate_limited", ticker=ticker, endpoint="financials")
            else:
                logger.warning("massive_financials_failed", ticker=ticker,
                               status=fin.status_code)

            await _massive_limiter.wait()
            det = await client.get(f"{_MASSIVE_BASE}/v3/reference/tickers/{ticker}")
            if det.status_code == 200:
                r = det.json().get("results") or {}
                out["market_cap"] = _num(r.get("market_cap"))
                # Massive reports SIC descriptions ("ELECTRONIC COMPUTERS"), not
                # GICS sectors. Kept under `industry` because that is what it
                # is; `sector` is left for Alpha Vantage's GICS value.
                out["industry"] = r.get("sic_description")
            elif det.status_code == 429:
                logger.warning("massive_rate_limited", ticker=ticker, endpoint="details")
    except Exception as exc:
        logger.warning("massive_fetch_failed", ticker=ticker, error=str(exc))
        return out

    if out:
        out["massive_ok"] = True
    return out


def _parse_massive_financials(results: list) -> dict:
    """Map two annual statements onto the fields `_fundamental_score` weights."""
    if not results:
        return {}

    def stmt(idx: int, name: str) -> dict:
        try:
            return (results[idx].get("financials") or {}).get(name) or {}
        except IndexError:
            return {}

    def val(d: dict, key: str) -> Optional[float]:
        item = d.get(key)
        if isinstance(item, dict):
            return _num(item.get("value"))
        return _num(item)

    inc_now, inc_prev = stmt(0, "income_statement"), stmt(1, "income_statement")
    bs_now = stmt(0, "balance_sheet")
    cf_now = stmt(0, "cash_flow_statement")

    out: dict = {}

    revenue_now = val(inc_now, "revenues")
    revenue_prev = val(inc_prev, "revenues")
    if revenue_now is not None and revenue_prev:
        out["revenue_growth_yoy"] = round((revenue_now - revenue_prev) / abs(revenue_prev), 4)

    eps = val(inc_now, "diluted_earnings_per_share")
    if eps is not None:
        out["eps_annual"] = eps

    liabilities = val(bs_now, "liabilities")
    equity = val(bs_now, "equity")
    if liabilities is not None and equity and equity > 0:
        # TOTAL LIABILITIES over equity, not debt over equity. This payload has
        # no long-term-debt line, so payables and deferred revenue are included
        # and the ratio runs well above the debt/equity figure the score was
        # calibrated against — Apple reads 387% here versus roughly 150% on a
        # true debt basis, which would max out the leverage penalty.
        #
        # Halved to bring it onto a comparable footing rather than left raw:
        # across large caps, total liabilities run roughly double total debt, so
        # this keeps the component directionally right instead of pinning every
        # liability-heavy balance sheet to zero. Approximate by construction —
        # hence the flag, so the fudge is visible to anything reading the doc.
        # Expressed as a percentage, matching yfinance's 45 = 45%.
        raw_ratio = 100.0 * liabilities / equity
        out["debt_to_equity"] = round(raw_ratio / 2.0, 2)
        out["debt_to_equity_basis"] = "total_liabilities_halved"
        out["total_liabilities_to_equity"] = round(raw_ratio, 2)

    # Operating cash flow stands in for free cash flow. Capital expenditure is
    # not broken out in this payload, so true FCF cannot be derived — but the
    # score only reads the SIGN of this field, and a company with positive
    # operating cash flow but negative FCF is the rare case, not the norm.
    ocf = val(cf_now, "net_cash_flow_from_operating_activities")
    if ocf is not None:
        out["free_cash_flow"] = ocf
        out["free_cash_flow_is_proxy"] = True

    net_income = val(inc_now, "net_income_loss")
    if net_income is not None and revenue_now:
        out["profit_margin"] = round(net_income / revenue_now, 4)
    if net_income is not None and equity and equity > 0:
        out["return_on_equity"] = round(net_income / equity, 4)

    if results:
        out["fiscal_year"] = results[0].get("fiscal_year")
    return out


# ── Alpha Vantage ─────────────────────────────────────────────────────────────

async def fetch_alpha_vantage(ticker: str) -> dict:
    """
    OVERVIEW fundamentals for `ticker`.

    One call yields analyst consensus, P/E, revenue growth, margins and sector —
    75% of the fundamental score's weight. Returns {} when unavailable.
    """
    settings = get_settings()
    key = settings.alphavantage_api_key
    if not key:
        return {}

    ticker = ticker.upper()
    try:
        await _alpha_limiter.wait()
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                _ALPHA_BASE,
                params={"function": "OVERVIEW", "symbol": ticker, "apikey": key},
            )
        if resp.status_code != 200:
            logger.warning("alphavantage_http_error", ticker=ticker, status=resp.status_code)
            return {}
        data = resp.json()
    except Exception as exc:
        logger.warning("alphavantage_fetch_failed", ticker=ticker, error=str(exc))
        return {}

    # The daily cap is reported as a 200 with an explanatory body, not a 429.
    # Treating that as data would write the note's absence of fields over good
    # cached values.
    if "Information" in data or "Note" in data:
        logger.warning("alphavantage_rate_limited", ticker=ticker,
                       detail=str(data.get("Information") or data.get("Note"))[:120])
        return {"alphavantage_rate_limited": True}
    if not data.get("Symbol"):
        logger.warning("alphavantage_empty", ticker=ticker)
        return {}

    out: dict = {
        "pe_ratio": _num(data.get("PERatio")),
        "peg_ratio": _num(data.get("PEGRatio")),
        "pb_ratio": _num(data.get("PriceToBookRatio")),
        "ps_ratio": _num(data.get("PriceToSalesRatioTTM")),
        "eps_ttm": _num(data.get("EPS")),
        "profit_margin": _num(data.get("ProfitMargin")),
        "return_on_equity": _num(data.get("ReturnOnEquityTTM")),
        "market_cap": _num(data.get("MarketCapitalization")),
        "week52_high": _num(data.get("52WeekHigh")),
        "week52_low": _num(data.get("52WeekLow")),
        "analyst_target_price": _num(data.get("AnalystTargetPrice")),
        "sector": (data.get("Sector") or "").title() or None,
        "industry": (data.get("Industry") or "").title() or None,
        "alphavantage_ok": True,
    }

    # QuarterlyRevenueGrowthYOY is already a fraction (0.164 = 16.4%), matching
    # what the score expects.
    rg = _num(data.get("QuarterlyRevenueGrowthYOY"))
    if rg is not None:
        out["revenue_growth_yoy"] = rg
    eg = _num(data.get("QuarterlyEarningsGrowthYOY"))
    if eg is not None:
        out["earnings_growth_yoy"] = eg

    rec, count = _consensus_from_counts(data)
    if rec:
        out["analyst_recommendation"] = rec
        out["analyst_count"] = count

    return {k: v for k, v in out.items() if v is not None}


def _consensus_from_counts(data: dict) -> tuple[Optional[str], Optional[int]]:
    """
    Collapse Alpha Vantage's per-rating analyst counts into the single verdict
    string `_fundamental_score` expects.

    Uses a weighted mean rather than the modal bucket: 10 strong buys against 9
    holds is a materially more bullish book than the plain majority suggests,
    and the mean reflects that where picking the largest bucket does not.
    """
    buckets = (
        ("AnalystRatingStrongBuy", 1.0),
        ("AnalystRatingBuy", 0.75),
        ("AnalystRatingHold", 0.5),
        ("AnalystRatingSell", 0.25),
        ("AnalystRatingStrongSell", 0.0),
    )
    total = 0
    weighted = 0.0
    for field, weight in buckets:
        n = _num(data.get(field))
        if n:
            total += int(n)
            weighted += weight * n
    if total == 0:
        return None, None

    mean = weighted / total
    if mean >= 0.90:
        rec = "strong_buy"
    elif mean >= 0.65:
        rec = "buy"
    elif mean >= 0.40:
        rec = "hold"
    elif mean >= 0.15:
        rec = "underperform"
    else:
        rec = "sell"
    return rec, total


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_fundamentals(ticker: str, alpha: dict, massive: dict, price: float | None = None) -> dict:
    """
    Combine both providers into one fundamentals document.

    Alpha Vantage wins on overlapping ratios: its figures are trailing-twelve-
    month, while the values derived from Massive's statements are as of the last
    annual filing and can be most of a year stale. Massive supplies what Alpha
    Vantage does not carry at all — free cash flow and debt/equity.
    """
    merged: dict = {}
    merged.update({k: v for k, v in massive.items() if v is not None})
    merged.update({k: v for k, v in alpha.items() if v is not None})

    # P/E from the annual EPS only if neither provider gave a real one — a
    # stale-but-real multiple beats no multiple, since the score treats a
    # missing P/E as "skip this component" and re-weights the rest.
    if merged.get("pe_ratio") is None and price and merged.get("eps_annual"):
        eps = merged["eps_annual"]
        if eps > 0:
            merged["pe_ratio"] = round(price / eps, 2)
            merged["pe_ratio_is_annual"] = True

    sources = []
    if massive.get("massive_ok"):
        sources.append("massive")
    if alpha.get("alphavantage_ok"):
        sources.append("alphavantage")

    merged["ticker"] = ticker.upper()
    merged["source"] = "+".join(sources) if sources else "none"
    merged["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()
    return merged
