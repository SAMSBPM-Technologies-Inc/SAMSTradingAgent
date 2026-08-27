"""
Valuation evidence — multiples, where they sit historically, and against peers.

Before this, the entire valuation logic in the system was one linear ramp on
P/E: 15 or below scored 1.0, 60 or above scored 0.0, worth a fifth of the
fundamental factor. `pb_ratio`, `ps_ratio` and `peg_ratio` were fetched, stored,
and read by nothing.

Three additions matter more than the extra multiples themselves:

  * **Forward P/E and EV/EBITDA** were in the OVERVIEW response all along.
    EV/EBITDA in particular is the multiple that survives a leveraged balance
    sheet, which P/E does not.
  * **FCF yield**, derived from cash flow and market cap, is the one multiple
    here that cannot be manufactured by accounting choices.
  * **A historical band.** A P/E of 40 means nothing on its own; a P/E of 40
    against a five-year range of 22–35 is a statement. This is computed from
    the accumulated statement series and the current price, so it exists only
    once enough history has been collected — and says so when it has not.

Peer comparison is explicitly the weak part and is labelled that way in the
evidence text itself, not just in a docstring the reader never sees.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger
from app.services.research.formatting import money, pct, ratio

_SOURCE = "Alpha Vantage OVERVIEW"
_DERIVED = "Derived from statements and current price"

#: Minimum annual periods before a historical multiple range is offered at all.
#: Three points is the fewest that can show a direction rather than a line
#: between two dots, and a "range" built from one prior year would invite an
#: agent to call something cheap or expensive on no evidence.
_MIN_HISTORY = 3


def build(ledger: Ledger, fundamentals: dict, annual: list[dict],
          price: Optional[float]) -> dict:
    """Add valuation evidence and return a summary of what could be computed."""
    annual = [row for row in (annual or []) if row.get("period_end")]
    as_of = str(fundamentals.get("fetched_at") or "")[:10] or None

    def add(claim: str, value, source: str = _SOURCE, meta: bool = False) -> None:
        ledger.add("V", claim, value, source, as_of=as_of, meta=meta)

    add("Trailing P/E", ratio(fundamentals.get("pe_ratio")))
    add("Forward P/E", ratio(fundamentals.get("forward_pe")))
    add("PEG ratio", ratio(fundamentals.get("peg_ratio")))
    add("Price/book", ratio(fundamentals.get("pb_ratio")))
    add("Price/sales", ratio(fundamentals.get("ps_ratio")))
    add("EV/EBITDA", ratio(fundamentals.get("ev_to_ebitda")))
    add("EV/revenue", ratio(fundamentals.get("ev_to_revenue")))

    if fundamentals.get("pe_ratio_is_annual"):
        add("P/E basis note",
            "Trailing P/E derived from last annual EPS, not TTM — treat as approximate",
            meta=True)

    fcf_yield = _fcf_yield(fundamentals, annual)
    if fcf_yield is not None:
        add("Free cash flow yield", pct(fcf_yield), source=_DERIVED)

    earnings_yield = _inverse(fundamentals.get("pe_ratio"))
    if earnings_yield is not None:
        add("Earnings yield (inverse P/E)", pct(earnings_yield), source=_DERIVED)

    band = _historical_pe_band(annual, price)
    if band:
        add(f"Historical P/E range ({band['periods']} fiscal years, at today's price)",
            f"{band['low']:.1f}–{band['high']:.1f} (median {band['median']:.1f})",
            source=_DERIVED)
        add("Historical P/E caveat",
            "Range applies today's price to each year's EPS — it shows how the "
            "current price would have been valued against past earnings, not "
            "what the multiple actually was at the time",
            source=_DERIVED, meta=True)
    elif len(annual) < _MIN_HISTORY:
        add("Historical valuation range",
            f"Not available — only {len(annual)} annual period(s) collected so far",
            source=_DERIVED, meta=True)

    _range_position(add, fundamentals, price)

    return {
        "has_forward_pe": fundamentals.get("forward_pe") is not None,
        "has_ev_ebitda": fundamentals.get("ev_to_ebitda") is not None,
        "has_fcf_yield": fcf_yield is not None,
        "has_history": bool(band),
    }


def _inverse(value: Optional[float]) -> Optional[float]:
    if not value or value <= 0:
        return None
    return 1.0 / value


def _fcf_yield(fundamentals: dict, annual: list[dict]) -> Optional[float]:
    """
    Cash flow over market cap.

    Uses the same figure the statements labelled — which for most filings is
    operating cash flow standing in for FCF, because Polygon does not break out
    capex. The evidence text for the underlying line says so; this one inherits
    that caveat rather than restating it, and is only offered when a cash-flow
    figure exists at all.
    """
    market_cap = fundamentals.get("market_cap")
    if not market_cap or market_cap <= 0:
        return None
    cash_flow = None
    if annual and annual[0].get("free_cash_flow") is not None:
        cash_flow = annual[0]["free_cash_flow"]
    elif fundamentals.get("free_cash_flow") is not None:
        cash_flow = fundamentals["free_cash_flow"]
    if cash_flow is None:
        return None
    return round(cash_flow / market_cap, 4)


def _historical_pe_band(annual: list[dict], price: Optional[float]) -> Optional[dict]:
    """
    What today's price would be worth against each of the past few years' EPS.

    This is a weaker statement than a true historical multiple range, which
    needs a price series going back as far as the earnings — and price history
    here is capped at 90 days. Rather than skip valuation context entirely, the
    band answers the question it can answer, and the caveat is added to the
    ledger beside it so an agent citing the range also has the limitation
    available to cite.
    """
    if not price or price <= 0 or len(annual) < _MIN_HISTORY:
        return None
    multiples = [
        price / row["diluted_earnings_per_share"]
        for row in annual
        if row.get("diluted_earnings_per_share")
        and row["diluted_earnings_per_share"] > 0
    ]
    if len(multiples) < _MIN_HISTORY:
        return None
    multiples.sort()
    mid = len(multiples) // 2
    median = (multiples[mid] if len(multiples) % 2
              else (multiples[mid - 1] + multiples[mid]) / 2)
    return {
        "low": multiples[0],
        "high": multiples[-1],
        "median": median,
        "periods": len(multiples),
    }


def _range_position(add, fundamentals: dict, price: Optional[float]) -> None:
    """Where the price sits in its 52-week range — cheap context, already fetched."""
    high = fundamentals.get("week52_high")
    low = fundamentals.get("week52_low")
    add("52-week high", money(high))
    add("52-week low", money(low))
    if price and high and low and high > low:
        position = (price - low) / (high - low)
        add("Position in 52-week range", pct(position), source=_DERIVED)

    target = fundamentals.get("analyst_target_price")
    add("Mean analyst price target", money(target))
    if target and price and price > 0:
        add("Implied upside to target", pct((target - price) / price), source=_DERIVED)
    add("Analyst consensus", fundamentals.get("analyst_recommendation"))
