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

#: How much statement history to pull. Ten-plus years of annuals is what makes
#: a margin trend or a revenue CAGR computable at all; three years of quarters
#: covers "what has the business done recently" without paging.
_ANNUAL_PERIODS = 12
_QUARTERLY_PERIODS = 12

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


def _text(value: Any) -> Optional[str]:
    """
    Coerce to a non-empty string, mapping Alpha Vantage's sentinels to None.

    The same "None"/"-" placeholders `_num` guards against appear in the text
    fields too, and a business description reading "None" is worse than an
    absent one: the research agents would cite it.
    """
    if value in (None, "", "None", "-", "NA", "N/A"):
        return None
    text = str(value).strip()
    return text or None


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

    annual_rows: list[dict] = []
    quarterly_rows: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
            # Twelve annual periods, not two. Two was enough for a single
            # year-over-year revenue delta and nothing else — no margin trend,
            # no CAGR, no sense of whether a good year is a pattern or an
            # outlier. A decade is the span the research layer reasons over.
            await _massive_limiter.wait()
            fin = await client.get(
                f"{_MASSIVE_BASE}/vX/reference/financials",
                params={"ticker": ticker, "timeframe": "annual", "limit": _ANNUAL_PERIODS,
                        "order": "desc", "sort": "period_of_report_date"},
            )
            if fin.status_code == 200:
                results = fin.json().get("results") or []
                annual_rows = _normalise_statements(results, "annual")
                out.update(_parse_massive_financials(results))
            elif fin.status_code == 429:
                logger.warning("massive_rate_limited", ticker=ticker, endpoint="financials")
            else:
                logger.warning("massive_financials_failed", ticker=ticker,
                               status=fin.status_code)

            # Quarterly as well: annual figures can be most of a year stale, and
            # "what did the latest quarter do" is a different question from
            # "what is the ten-year trend". Costs one more paced call on a job
            # that already runs daily, not per cycle.
            await _massive_limiter.wait()
            qfin = await client.get(
                f"{_MASSIVE_BASE}/vX/reference/financials",
                params={"ticker": ticker, "timeframe": "quarterly",
                        "limit": _QUARTERLY_PERIODS,
                        "order": "desc", "sort": "period_of_report_date"},
            )
            if qfin.status_code == 200:
                quarterly_rows = _normalise_statements(
                    qfin.json().get("results") or [], "quarterly"
                )
            elif qfin.status_code == 429:
                logger.warning("massive_rate_limited", ticker=ticker, endpoint="financials_q")
            else:
                logger.warning("massive_quarterly_failed", ticker=ticker,
                               status=qfin.status_code)

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

    if annual_rows:
        out.update(_derive_trends(annual_rows))
    if out or annual_rows or quarterly_rows:
        out["massive_ok"] = True
    # Reserved key, not a fundamentals field: `refresh_fundamentals` pops this
    # and writes it to `financial_statements`. `merge_fundamentals` drops it so
    # a decade of statements never lands inside the per-ticker snapshot doc.
    out["statements"] = {"annual": annual_rows, "quarterly": quarterly_rows}
    return out


#: Line items lifted out of each filing, by statement. Polygon's normalised
#: schema does not guarantee any of them — a filing that omits one leaves the
#: key absent rather than zero, because a zero here would read as "no debt" or
#: "no revenue" downstream instead of "not reported".
_INCOME_FIELDS = (
    "revenues", "cost_of_revenue", "gross_profit", "operating_expenses",
    "operating_income_loss", "income_tax_expense_benefit",
    "income_loss_from_continuing_operations_before_tax", "net_income_loss",
    "basic_earnings_per_share", "diluted_earnings_per_share",
    "basic_average_shares", "diluted_average_shares", "interest_expense_operating",
)
_BALANCE_FIELDS = (
    "assets", "current_assets", "noncurrent_assets", "liabilities",
    "current_liabilities", "noncurrent_liabilities", "equity",
    "equity_attributable_to_parent", "inventory", "fixed_assets", "long_term_debt",
)
_CASHFLOW_FIELDS = (
    "net_cash_flow", "net_cash_flow_from_operating_activities",
    "net_cash_flow_from_investing_activities",
    "net_cash_flow_from_financing_activities",
)

#: Capital expenditure is not part of Polygon's normalised cash-flow schema, so
#: for most filings true free cash flow cannot be derived and the operating
#: cash flow proxy stands. These are the keys that do sometimes appear; when one
#: does, FCF is computed properly and `free_cash_flow_is_proxy` goes False.
_CAPEX_KEYS = (
    "payments_to_acquire_property_plant_and_equipment",
    "capital_expenditure",
    "capital_expenditures",
    "purchase_of_property_plant_and_equipment",
)


def _line(statement: dict, key: str) -> Optional[float]:
    """Read one line item, tolerating both the wrapped and bare value shapes."""
    item = statement.get(key)
    if isinstance(item, dict):
        return _num(item.get("value"))
    return _num(item)


def _normalise_statements(results: list, timeframe: str) -> list[dict]:
    """
    Flatten Polygon filings into one row per reporting period.

    Kept as a series rather than folded into a snapshot because a trend is the
    thing the research layer actually reasons about, and the old code could not
    express one: it fetched two periods, used the second for a single revenue
    delta, and overwrote the document on every refresh.
    """
    rows: list[dict] = []
    for entry in results or []:
        financials = entry.get("financials") or {}
        income = financials.get("income_statement") or {}
        balance = financials.get("balance_sheet") or {}
        cashflow = financials.get("cash_flow_statement") or {}

        row: dict = {
            "timeframe": timeframe,
            "period_end": entry.get("end_date") or entry.get("period_of_report_date"),
            "period_start": entry.get("start_date"),
            "fiscal_year": entry.get("fiscal_year"),
            "fiscal_period": entry.get("fiscal_period"),
            "filing_date": entry.get("filing_date"),
            "source_filing_url": entry.get("source_filing_url"),
        }
        for key in _INCOME_FIELDS:
            value = _line(income, key)
            if value is not None:
                row[key] = value
        for key in _BALANCE_FIELDS:
            value = _line(balance, key)
            if value is not None:
                row[key] = value
        for key in _CASHFLOW_FIELDS:
            value = _line(cashflow, key)
            if value is not None:
                row[key] = value

        for key in _CAPEX_KEYS:
            capex = _line(cashflow, key)
            if capex is not None:
                # Reported as a negative outflow in most filings; store the
                # magnitude so callers do not have to guess the sign.
                row["capital_expenditure"] = abs(capex)
                break

        row.update(_period_ratios(row))
        if row.get("period_end"):
            rows.append(row)
    return rows


def _period_ratios(row: dict) -> dict:
    """
    Per-period ratios computed from whatever line items that filing carried.

    Each is emitted only when its operands are present. A margin that cannot be
    computed is absent, never 0.0 — the distinction between "no gross profit"
    and "gross profit not reported" is the whole reason the old snapshot's
    single net margin was misleading.
    """
    out: dict = {}
    revenue = row.get("revenues")

    if revenue:
        gross = row.get("gross_profit")
        if gross is None and row.get("cost_of_revenue") is not None:
            gross = revenue - row["cost_of_revenue"]
        if gross is not None:
            out["gross_margin"] = round(gross / revenue, 4)
        if row.get("operating_income_loss") is not None:
            out["operating_margin"] = round(row["operating_income_loss"] / revenue, 4)
        if row.get("net_income_loss") is not None:
            out["profit_margin"] = round(row["net_income_loss"] / revenue, 4)

    equity = row.get("equity") or row.get("equity_attributable_to_parent")
    if row.get("net_income_loss") is not None and equity and equity > 0:
        out["return_on_equity"] = round(row["net_income_loss"] / equity, 4)

    ocf = row.get("net_cash_flow_from_operating_activities")
    if ocf is not None:
        capex = row.get("capital_expenditure")
        if capex is not None:
            out["free_cash_flow"] = round(ocf - capex, 2)
            out["free_cash_flow_is_proxy"] = False
        else:
            out["free_cash_flow"] = ocf
            out["free_cash_flow_is_proxy"] = True

    out.update(_leverage(row))
    roic = _roic(row)
    if roic:
        out.update(roic)
    return out


def _leverage(row: dict) -> dict:
    """
    Debt/equity on a true debt basis where the filing reports one.

    The long-standing fallback divides total liabilities by two, because this
    payload usually has no long-term-debt line and raw liabilities/equity runs
    roughly double a real debt ratio — Apple reads 387% that way against about
    150% on a debt basis, which would max out the leverage penalty for every
    liability-heavy balance sheet. That approximation stays for filings without
    the line, flagged, but it is no longer applied to filings that have it.
    """
    equity = row.get("equity") or row.get("equity_attributable_to_parent")
    if not equity or equity <= 0:
        return {}

    debt = row.get("long_term_debt")
    if debt is not None:
        return {
            "debt_to_equity": round(100.0 * debt / equity, 2),
            "debt_to_equity_basis": "long_term_debt",
        }

    liabilities = row.get("liabilities")
    if liabilities is None:
        return {}
    raw_ratio = 100.0 * liabilities / equity
    return {
        "debt_to_equity": round(raw_ratio / 2.0, 2),
        "debt_to_equity_basis": "total_liabilities_halved",
        "total_liabilities_to_equity": round(raw_ratio, 2),
    }


def _roic(row: dict) -> dict:
    """
    Return on invested capital: NOPAT over debt plus equity.

    Absent entirely before this — the fundamental score had ROE but nothing
    that accounts for how much borrowed money produced the return. Computed
    only when operating income and equity are both reported; the effective tax
    rate is taken from the filing where it can be, and clamped to a sane band
    so one odd year of tax credits cannot invert the sign.
    """
    operating_income = row.get("operating_income_loss")
    equity = row.get("equity") or row.get("equity_attributable_to_parent")
    if operating_income is None or not equity or equity <= 0:
        return {}

    tax_rate = 0.21  # US statutory default when the filing does not support one
    pretax = row.get("income_loss_from_continuing_operations_before_tax")
    tax = row.get("income_tax_expense_benefit")
    basis = "statutory_tax_rate"
    if pretax and tax is not None and pretax > 0:
        effective = tax / pretax
        if 0.0 <= effective <= 0.60:
            tax_rate = effective
            basis = "effective_tax_rate"

    debt = row.get("long_term_debt") or 0.0
    invested = equity + debt
    if invested <= 0:
        return {}

    nopat = operating_income * (1.0 - tax_rate)
    return {
        "roic": round(nopat / invested, 4),
        "roic_basis": basis if debt else f"{basis}_equity_only",
    }


def _years_between(older: Optional[str], newer: Optional[str]) -> Optional[float]:
    """Elapsed years between two ISO period-end dates, or None if unparseable."""
    if not older or not newer:
        return None
    try:
        start = datetime.fromisoformat(str(older)[:10])
        end = datetime.fromisoformat(str(newer)[:10])
    except (TypeError, ValueError):
        return None
    return (end - start).days / 365.25


def _cagr(newest: Optional[float], oldest: Optional[float], years: float) -> Optional[float]:
    """
    Compound annual growth rate, or None where the maths is not meaningful.

    A negative or zero starting value has no compound rate — reporting one
    anyway is how a company that swung from a loss to a profit ends up with a
    triple-digit "growth" figure that means nothing.
    """
    if newest is None or oldest is None or years <= 0:
        return None
    if oldest <= 0 or newest <= 0:
        return None
    return round((newest / oldest) ** (1.0 / years) - 1.0, 4)


def _derive_trends(annual_rows: list[dict]) -> dict:
    """
    Multi-year trends across the annual series — the whole point of pulling it.

    Rows arrive newest-first. Everything here is emitted only when there are
    enough periods to support it, so a freshly covered ticker reports no trend
    rather than a trend computed from two points and called a decade.
    """
    rows = [r for r in annual_rows if r.get("period_end")]
    if len(rows) < 2:
        return {}

    newest, oldest = rows[0], rows[-1]
    # Span from the actual reporting dates, not the row count. A provider that
    # skips a year — or a ticker whose coverage starts mid-decade — would
    # otherwise have its CAGR computed over the wrong number of years, which
    # silently understates or overstates every growth rate in the dossier.
    span = _years_between(oldest.get("period_end"), newest.get("period_end"))
    if span is None or span <= 0:
        span = float(len(rows) - 1)
    out: dict = {
        "statement_periods": len(rows),
        "statement_span_years": round(span, 2),
        "statement_oldest_period": oldest.get("period_end"),
        "statement_newest_period": newest.get("period_end"),
    }

    revenue_cagr = _cagr(newest.get("revenues"), oldest.get("revenues"), span)
    if revenue_cagr is not None:
        out["revenue_cagr"] = revenue_cagr
    eps_cagr = _cagr(
        newest.get("diluted_earnings_per_share"),
        oldest.get("diluted_earnings_per_share"),
        span,
    )
    if eps_cagr is not None:
        out["eps_cagr"] = eps_cagr
    fcf_cagr = _cagr(newest.get("free_cash_flow"), oldest.get("free_cash_flow"), span)
    if fcf_cagr is not None:
        out["fcf_cagr"] = fcf_cagr

    # Margin direction, newest against oldest. Expressed as a delta rather than
    # a rate because margins are already percentages and compounding them says
    # nothing a reader can use.
    for key in ("gross_margin", "operating_margin", "profit_margin"):
        now, then = newest.get(key), oldest.get(key)
        if now is not None and then is not None:
            out[f"{key}_delta"] = round(now - then, 4)

    # Share count: dilution is invisible in per-share figures alone, and a
    # buyback is a real part of the return a shareholder sees.
    shares_now = newest.get("diluted_average_shares")
    shares_then = oldest.get("diluted_average_shares")
    if shares_now and shares_then and shares_then > 0:
        out["share_count_change"] = round((shares_now - shares_then) / shares_then, 4)

    return out


def _parse_massive_financials(results: list) -> dict:
    """
    Fold the newest filing into the flat snapshot the scorer reads.

    The scorer runs every five minutes and wants single numbers, not a series,
    so this stays a snapshot — but it is now derived from the same normalised
    rows the research layer uses, rather than a second hand-rolled parse that
    could drift from it. Everything beyond the newest period lives in
    `financial_statements`.
    """
    rows = _normalise_statements(results, "annual")
    if not rows:
        return {}

    newest = rows[0]
    carried = (
        "gross_margin", "operating_margin", "profit_margin", "return_on_equity",
        "free_cash_flow", "free_cash_flow_is_proxy", "debt_to_equity",
        "debt_to_equity_basis", "total_liabilities_to_equity", "roic", "roic_basis",
    )
    out: dict = {key: newest[key] for key in carried if key in newest}

    if newest.get("diluted_earnings_per_share") is not None:
        out["eps_annual"] = newest["diluted_earnings_per_share"]
    if newest.get("revenues") is not None:
        out["revenue_annual"] = newest["revenues"]
    if newest.get("fiscal_year"):
        out["fiscal_year"] = newest["fiscal_year"]

    if len(rows) > 1:
        revenue_now, revenue_prev = newest.get("revenues"), rows[1].get("revenues")
        if revenue_now is not None and revenue_prev:
            out["revenue_growth_yoy"] = round(
                (revenue_now - revenue_prev) / abs(revenue_prev), 4
            )

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

    # Everything below arrives in the same HTTP response. The original mapping
    # took 16 of roughly 50 fields and discarded the rest, which is why the
    # analyst prompt could describe a company's P/E but not what it sells —
    # `Description` was already being fetched and thrown away on every refresh.
    # Reading more of the payload costs no extra call and no extra budget.
    out: dict = {
        # Identity and business
        "company_name": _text(data.get("Name")),
        "description": _text(data.get("Description")),
        "sector": (data.get("Sector") or "").title() or None,
        "industry": (data.get("Industry") or "").title() or None,
        "country": _text(data.get("Country")),
        "exchange": _text(data.get("Exchange")),
        "currency": _text(data.get("Currency")),
        "fiscal_year_end": _text(data.get("FiscalYearEnd")),
        "latest_quarter": _text(data.get("LatestQuarter")),

        # Valuation multiples
        "pe_ratio": _num(data.get("PERatio")),
        "forward_pe": _num(data.get("ForwardPE")),
        "peg_ratio": _num(data.get("PEGRatio")),
        "pb_ratio": _num(data.get("PriceToBookRatio")),
        "ps_ratio": _num(data.get("PriceToSalesRatioTTM")),
        "ev_to_ebitda": _num(data.get("EVToEBITDA")),
        "ev_to_revenue": _num(data.get("EVToRevenue")),

        # Per-share and size
        "eps_ttm": _num(data.get("EPS")),
        "diluted_eps_ttm": _num(data.get("DilutedEPSTTM")),
        "book_value": _num(data.get("BookValue")),
        "revenue_per_share_ttm": _num(data.get("RevenuePerShareTTM")),
        "shares_outstanding": _num(data.get("SharesOutstanding")),
        "market_cap": _num(data.get("MarketCapitalization")),
        "ebitda": _num(data.get("EBITDA")),
        "revenue_ttm": _num(data.get("RevenueTTM")),
        "gross_profit_ttm": _num(data.get("GrossProfitTTM")),

        # Profitability
        "profit_margin": _num(data.get("ProfitMargin")),
        "operating_margin": _num(data.get("OperatingMarginTTM")),
        "return_on_equity": _num(data.get("ReturnOnEquityTTM")),
        "return_on_assets": _num(data.get("ReturnOnAssetsTTM")),

        # Market context
        "beta": _num(data.get("Beta")),
        "dividend_yield": _num(data.get("DividendYield")),
        "week52_high": _num(data.get("52WeekHigh")),
        "week52_low": _num(data.get("52WeekLow")),
        "analyst_target_price": _num(data.get("AnalystTargetPrice")),
        "alphavantage_ok": True,
    }

    # Gross margin is not a field Alpha Vantage returns, but both of its
    # operands are. Derived rather than left absent, because it is the margin
    # that separates a pricing-power business from a volume one and no other
    # source in this system carries it.
    if out["gross_profit_ttm"] is not None and out["revenue_ttm"]:
        out["gross_margin"] = round(out["gross_profit_ttm"] / out["revenue_ttm"], 4)

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


async def fetch_alpha_earnings(ticker: str) -> dict:
    """
    Reported-versus-estimated EPS history, and the earnings calendar.

    This is the one genuinely new API call in the research work, and it closes
    two gaps at once. It is the only source in this system for *what the market
    expected* — every other number here describes what happened, never what was
    forecast — and its `reportedDate` finally populates `next_earnings_date`,
    which the analyst prompt has read and rendered as `N/A` on every run since
    yfinance was dropped, because nothing has written it since.

    Costs one Alpha Vantage call against a 25/day free-tier cap that the
    watchlist already exceeds, so callers must cache it hard — see
    `fundamentals.refresh_earnings`. Returns {} when unavailable rather than a
    partial shape, so a rate-limited day leaves the last good history in place.
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
                params={"function": "EARNINGS", "symbol": ticker, "apikey": key},
            )
        if resp.status_code != 200:
            logger.warning("alphavantage_earnings_http_error", ticker=ticker,
                           status=resp.status_code)
            return {}
        data = resp.json()
    except Exception as exc:
        logger.warning("alphavantage_earnings_failed", ticker=ticker, error=str(exc))
        return {}

    if "Information" in data or "Note" in data:
        logger.warning("alphavantage_rate_limited", ticker=ticker, endpoint="earnings")
        return {"alphavantage_rate_limited": True}
    if not data.get("symbol"):
        logger.warning("alphavantage_earnings_empty", ticker=ticker)
        return {}

    quarterly = _parse_quarterly_earnings(data.get("quarterlyEarnings") or [])
    annual = _parse_annual_earnings(data.get("annualEarnings") or [])

    out: dict = {
        "ticker": ticker,
        "quarterly_earnings": quarterly,
        "annual_earnings": annual,
        "source": "alphavantage",
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    out.update(_earnings_summary(quarterly))
    return out


def _parse_quarterly_earnings(raw: list) -> list[dict]:
    """
    Normalise the quarterly rows, newest first.

    `surprisePercentage` is echoed from the provider *and* recomputed, because
    the provider's value is absent often enough that a beat/miss record built
    on it alone would have holes in it. The recomputation is skipped when the
    estimate is zero or negative — a percentage against a zero base is not a
    number, and reporting one would put an infinity in a research prompt.
    """
    rows: list[dict] = []
    for entry in raw:
        fiscal_ending = _text(entry.get("fiscalDateEnding"))
        if not fiscal_ending:
            continue
        reported = _num(entry.get("reportedEPS"))
        estimated = _num(entry.get("estimatedEPS"))
        row: dict = {
            "fiscal_date_ending": fiscal_ending,
            "reported_date": _text(entry.get("reportedDate")),
            "reported_eps": reported,
            "estimated_eps": estimated,
            "surprise": _num(entry.get("surprise")),
            "surprise_pct": _num(entry.get("surprisePercentage")),
        }
        if row["surprise"] is None and reported is not None and estimated is not None:
            row["surprise"] = round(reported - estimated, 4)
        if row["surprise_pct"] is None and row["surprise"] is not None and estimated:
            if estimated > 0:
                row["surprise_pct"] = round(100.0 * row["surprise"] / estimated, 2)
        rows.append(row)
    return rows


def _parse_annual_earnings(raw: list) -> list[dict]:
    """Normalise the annual reported-EPS series, newest first."""
    rows: list[dict] = []
    for entry in raw:
        fiscal_ending = _text(entry.get("fiscalDateEnding"))
        eps = _num(entry.get("reportedEPS"))
        if fiscal_ending and eps is not None:
            rows.append({"fiscal_date_ending": fiscal_ending, "reported_eps": eps})
    return rows


def _earnings_summary(quarterly: list[dict]) -> dict:
    """
    The beat/miss record, and the next and last report dates.

    `next_earnings_date` is the field the catalyst score has wanted since
    yfinance was removed — `catalyst.py` documents earnings proximity as
    structurally missing because nothing supplies it. Alpha Vantage lists
    future quarters with a `reportedDate` and no `reportedEPS`, so the next
    date is the earliest such row: an announced report that has not happened
    yet, which is exactly the definition the catalyst leg needs.
    """
    if not quarterly:
        return {}

    today = datetime.now(tz=timezone.utc).date().isoformat()
    out: dict = {}

    upcoming = [
        row["reported_date"] for row in quarterly
        if row.get("reported_date") and row.get("reported_eps") is None
        and row["reported_date"] >= today
    ]
    if upcoming:
        out["next_earnings_date"] = min(upcoming)

    settled = [row for row in quarterly if row.get("reported_eps") is not None]
    if not settled:
        return out

    out["last_earnings_date"] = settled[0].get("reported_date")
    out["last_reported_eps"] = settled[0].get("reported_eps")
    out["last_estimated_eps"] = settled[0].get("estimated_eps")
    out["last_surprise_pct"] = settled[0].get("surprise_pct")

    # Beat rate over the last eight settled quarters. Two years is long enough
    # to be a record rather than a mood, and short enough that a company which
    # has changed shape is not judged on what it was a decade ago.
    window = [row for row in settled[:8] if row.get("surprise") is not None]
    if window:
        beats = sum(1 for row in window if row["surprise"] > 0)
        out["earnings_beat_count"] = beats
        out["earnings_quarters_scored"] = len(window)
        out["earnings_beat_rate"] = round(beats / len(window), 3)
        surprises = [row["surprise_pct"] for row in window
                     if row.get("surprise_pct") is not None]
        if surprises:
            out["avg_surprise_pct"] = round(sum(surprises) / len(surprises), 2)
    return out


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
    # `statements` is the raw series, persisted separately by the caller. It
    # must not ride along into the snapshot: a decade of filings inside the doc
    # the 5-minute scorer reads on every ticker is a lot of bytes to move for a
    # handful of numbers.
    merged: dict = {}
    merged.update({k: v for k, v in massive.items()
                   if v is not None and k != "statements"})
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
