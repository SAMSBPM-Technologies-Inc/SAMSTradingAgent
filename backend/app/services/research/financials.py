"""
Financial statement evidence — the trend, not the snapshot.

The distinction is the whole point. The scorer has always had a fundamental
snapshot; what it never had was a second point to compare it against. Two annual
periods were fetched, one was used for a single revenue delta, and the document
was replaced on every refresh, so a decade of filings could pass through the
process and leave nothing behind.

With `financial_statements` accumulating, a margin that has compressed for four
straight years and a margin that dipped once look different here, and they are
different. Every figure carries its period, so an agent citing "gross margin"
is citing a specific filing rather than an undated number.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger
from app.services.research.formatting import count, money, pct, pct_points, ratio

_SOURCE = "Massive/Polygon financial statements"
_SNAPSHOT_SOURCE = "Alpha Vantage OVERVIEW (TTM)"

#: How many annual periods to spell out line by line. The full series informs
#: the trends below, but rendering twelve years of every metric would crowd out
#: everything else in a prompt that also has to carry valuation, news and risk.
_DETAIL_PERIODS = 5


def build(ledger: Ledger, fundamentals: dict, annual: list[dict],
          quarterly: Optional[list[dict]] = None) -> dict:
    """Add statement evidence and return a coverage summary."""
    annual = [row for row in (annual or []) if row.get("period_end")]
    quarterly = [row for row in (quarterly or []) if row.get("period_end")]

    _trailing_twelve_months(ledger, fundamentals)
    _annual_series(ledger, annual)
    _trends(ledger, fundamentals, annual)
    _latest_quarter(ledger, quarterly)
    _balance_sheet(ledger, fundamentals, annual)

    return {
        "annual_periods": len(annual),
        "quarterly_periods": len(quarterly),
        "oldest_period": annual[-1].get("period_end") if annual else None,
        "newest_period": annual[0].get("period_end") if annual else None,
    }


def _trailing_twelve_months(ledger: Ledger, fundamentals: dict) -> None:
    """
    The freshest read on profitability, from Alpha Vantage's TTM figures.

    Kept separate from the annual series and separately sourced, because mixing
    a TTM margin into a list of fiscal-year margins produces a trend with one
    point measured differently from the rest — which reads as a change in the
    business when it is a change in the ruler.
    """
    as_of = str(fundamentals.get("fetched_at") or "")[:10] or None

    def add(claim: str, value) -> None:
        ledger.add("F", claim, value, _SNAPSHOT_SOURCE, as_of=as_of)

    add("Revenue (TTM)", money(fundamentals.get("revenue_ttm")))
    add("Gross margin (TTM)", pct(fundamentals.get("gross_margin")))
    add("Operating margin (TTM)", pct(fundamentals.get("operating_margin")))
    add("Net profit margin (TTM)", pct(fundamentals.get("profit_margin")))
    add("Return on equity (TTM)", pct(fundamentals.get("return_on_equity")))
    add("Return on assets (TTM)", pct(fundamentals.get("return_on_assets")))
    add("Diluted EPS (TTM)", ratio(fundamentals.get("diluted_eps_ttm")))
    add("Revenue growth, latest quarter YoY", pct(fundamentals.get("revenue_growth_yoy")))
    add("Earnings growth, latest quarter YoY", pct(fundamentals.get("earnings_growth_yoy")))


def _annual_series(ledger: Ledger, annual: list[dict]) -> None:
    """One evidence line per fiscal year, so a trend can be cited period by period."""
    for row in annual[:_DETAIL_PERIODS]:
        period = row.get("period_end")
        label = row.get("fiscal_year") or str(period)[:4]

        def add(claim: str, value) -> None:
            ledger.add("F", f"{claim} (FY{label})", value, _SOURCE, as_of=period,
                       url=row.get("source_filing_url"))

        add("Revenue", money(row.get("revenues")))
        add("Gross margin", pct(row.get("gross_margin")))
        add("Operating margin", pct(row.get("operating_margin")))
        add("Net margin", pct(row.get("profit_margin")))
        add("Diluted EPS", ratio(row.get("diluted_earnings_per_share")))
        add(_fcf_label(row), money(row.get("free_cash_flow")))
        add("Return on invested capital", pct(row.get("roic")))


def _fcf_label(row: dict) -> str:
    """
    Name the cash-flow figure for what it actually is.

    Polygon's normalised cash-flow schema has no capital-expenditure line for
    most filings, so free cash flow usually cannot be derived and operating
    cash flow stands in. Labelling the proxy as "free cash flow" is how a
    reader ends up comparing two companies on different quantities — so the
    label changes with the basis rather than the caveat living in a comment
    nobody downstream can see.
    """
    if row.get("free_cash_flow_is_proxy") is False:
        return "Free cash flow"
    return "Operating cash flow (free cash flow proxy — capex not reported)"


def _trends(ledger: Ledger, fundamentals: dict, annual: list[dict]) -> None:
    """Multi-year direction: the thing a single snapshot structurally cannot say."""
    span = fundamentals.get("statement_span_years")
    if not span or len(annual) < 2:
        return

    window = f"{span:g}y" if isinstance(span, (int, float)) else str(span)
    as_of = fundamentals.get("statement_newest_period")

    def add(claim: str, value) -> None:
        ledger.add("F", claim, value, _SOURCE, as_of=as_of)

    add(f"Revenue CAGR ({window})", pct(fundamentals.get("revenue_cagr")))
    add(f"Diluted EPS CAGR ({window})", pct(fundamentals.get("eps_cagr")))
    add(f"Cash flow CAGR ({window})", pct(fundamentals.get("fcf_cagr")))
    add(f"Gross margin change ({window})", pct_points(fundamentals.get("gross_margin_delta")))
    add(f"Operating margin change ({window})",
        pct_points(fundamentals.get("operating_margin_delta")))
    add(f"Net margin change ({window})", pct_points(fundamentals.get("profit_margin_delta")))
    # Dilution is invisible in per-share figures alone, and a buyback is a real
    # part of the return a shareholder actually receives.
    add(f"Diluted share count change ({window})",
        pct(fundamentals.get("share_count_change")))
    add("Annual periods on file", count(fundamentals.get("statement_periods")))


def _latest_quarter(ledger: Ledger, quarterly: list[dict]) -> None:
    """The most recent quarter, so "latest results" is not a year-old annual."""
    if not quarterly:
        return
    row = quarterly[0]
    period = row.get("period_end")
    label = row.get("fiscal_period") or "latest quarter"

    def add(claim: str, value) -> None:
        ledger.add("F", f"{claim} ({label} ending {period})", value, _SOURCE,
                   as_of=period, url=row.get("source_filing_url"))

    add("Quarterly revenue", money(row.get("revenues")))
    add("Quarterly gross margin", pct(row.get("gross_margin")))
    add("Quarterly operating margin", pct(row.get("operating_margin")))
    add("Quarterly net income", money(row.get("net_income_loss")))
    add("Quarterly diluted EPS", ratio(row.get("diluted_earnings_per_share")))


def _balance_sheet(ledger: Ledger, fundamentals: dict, annual: list[dict]) -> None:
    """
    Leverage and balance-sheet shape, with the basis stated.

    `debt_to_equity` means one of two different things depending on whether the
    filing reported a long-term-debt line, and the difference is roughly a
    factor of two. Stating the basis in the claim text means an agent comparing
    two companies can see when it is comparing like with unlike.
    """
    row = annual[0] if annual else {}
    period = row.get("period_end")

    def add(claim: str, value) -> None:
        ledger.add("F", claim, value, _SOURCE, as_of=period,
                   url=row.get("source_filing_url"))

    basis = fundamentals.get("debt_to_equity_basis")
    de = fundamentals.get("debt_to_equity")
    if de is not None:
        label = {
            "long_term_debt": "Debt/equity (long-term debt basis)",
            "total_liabilities_halved":
                "Debt/equity (approximate — total liabilities halved, no debt line filed)",
        }.get(basis or "", "Debt/equity")
        add(label, ratio(de, digits=1, suffix="%"))

    add("Total liabilities / equity", ratio(
        fundamentals.get("total_liabilities_to_equity"), digits=1, suffix="%"))
    add("Total assets", money(row.get("assets")))
    add("Total liabilities", money(row.get("liabilities")))
    add("Shareholders' equity", money(row.get("equity")))
    add("Long-term debt", money(row.get("long_term_debt")))
    add("Book value per share", ratio(fundamentals.get("book_value")))

    current_assets = row.get("current_assets")
    current_liabilities = row.get("current_liabilities")
    if current_assets is not None and current_liabilities:
        add("Current ratio", ratio(current_assets / current_liabilities))
