"""
Company profile evidence — what the business actually is.

This closes the single largest gap in the previous analyst. Its entire input
was a numeric block plus eight anonymous headlines; the only company context it
carried was `sector` and an `industry` string derived from an SIC code, and
both existed solely to index a hardcoded sector→macro-beta table. A model asked
for a view on moat, customer concentration or competitive risk had no idea what
the company sold.

The description was not missing from the data. Alpha Vantage's OVERVIEW
response has carried it all along, on the same call that supplied the P/E, and
it was discarded during parsing on every refresh.

Peers are the honest weak spot here, and are labelled as such downstream: they
are other names on the same watchlist sharing a sector or industry, plus a small
static map. That is a convenience, not a screen — a real peer set needs a
universe this system does not have.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger
from app.services.research.formatting import count, money, pct, ratio

_SOURCE = "Alpha Vantage OVERVIEW"

#: A few industries where the obvious comparables are not on any one watchlist.
#: Deliberately tiny and deliberately hand-written — it exists so a dossier for
#: a lone semiconductor name is not compared against a bank, not to pretend
#: this is a screening universe.
_STATIC_PEERS: dict[str, tuple[str, ...]] = {
    "semiconductors": ("NVDA", "AMD", "INTC", "AVGO", "TSM", "QCOM", "MU"),
    "software—infrastructure": ("MSFT", "ORCL", "CRM", "ADBE", "NOW"),
    "software—application": ("CRM", "ADBE", "NOW", "INTU", "WDAY"),
    "internet content & information": ("GOOGL", "META", "NFLX"),
    "consumer electronics": ("AAPL", "SONY", "DELL", "HPQ"),
    "auto manufacturers": ("TSLA", "GM", "F", "RIVN", "TM"),
}


def build(ledger: Ledger, ticker: str, fundamentals: dict,
          watchlist: Optional[list[dict]] = None) -> dict:
    """
    Add profile evidence and return a small summary for the prompt header.

    The description is added as evidence like any other fact, not spliced into
    the system prompt, so a claim about what the company does is attributable
    to a dated source in exactly the way a claim about its margin is.
    """
    as_of = _as_of(fundamentals)
    add = _adder(ledger, as_of)

    add("Company name", fundamentals.get("company_name"))
    add("Business description", _trim(fundamentals.get("description")))
    add("Sector", fundamentals.get("sector"))
    add("Industry", fundamentals.get("industry"))
    add("Country of domicile", fundamentals.get("country"))
    add("Listing exchange", fundamentals.get("exchange"))
    add("Market capitalisation", money(fundamentals.get("market_cap")))
    add("Shares outstanding", count(fundamentals.get("shares_outstanding")))
    add("Beta vs market", ratio(fundamentals.get("beta")))
    add("Dividend yield", pct(fundamentals.get("dividend_yield"), digits=2))
    add("Fiscal year end", fundamentals.get("fiscal_year_end"))
    add("Most recent reported quarter", fundamentals.get("latest_quarter"))

    peers = _peers(ticker, fundamentals, watchlist)
    if peers:
        add("Comparable names considered", ", ".join(peers))

    return {
        "company_name": fundamentals.get("company_name"),
        "sector": fundamentals.get("sector"),
        "industry": fundamentals.get("industry"),
        "peers": peers,
        "has_description": bool(fundamentals.get("description")),
    }


def _adder(ledger: Ledger, as_of: Optional[str]):
    def add(claim: str, value) -> None:
        ledger.add("P", claim, value, _SOURCE, as_of=as_of)
    return add


def _as_of(fundamentals: dict) -> Optional[str]:
    fetched = fundamentals.get("fetched_at")
    return str(fetched)[:10] if fetched else None


def _trim(description: Optional[str], limit: int = 1200) -> Optional[str]:
    """
    Cap the description length.

    Alpha Vantage descriptions run to a couple of paragraphs, which is the
    right amount of context. A handful run much longer, and since this text is
    replayed into four agent prompts a runaway one is paid for four times.
    """
    if not description:
        return None
    text = " ".join(str(description).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _peers(ticker: str, fundamentals: dict,
           watchlist: Optional[list[dict]]) -> list[str]:
    """
    Assemble a comparable set from the watchlist and the static map.

    Ordered watchlist-first because those are names this system already holds
    real data for, so a comparison against them can be evidenced rather than
    asserted from the model's own recall.
    """
    ticker = ticker.upper()
    sector = (fundamentals.get("sector") or "").strip().lower()
    industry = (fundamentals.get("industry") or "").strip().lower()

    peers: list[str] = []
    for row in watchlist or []:
        symbol = str(row.get("ticker", "")).upper()
        if not symbol or symbol == ticker or symbol in peers:
            continue
        row_sector = str(row.get("sector") or "").strip().lower()
        row_industry = str(row.get("industry") or "").strip().lower()
        if (industry and row_industry == industry) or (sector and row_sector == sector):
            peers.append(symbol)

    for symbol in _STATIC_PEERS.get(industry, ()):
        if symbol != ticker and symbol not in peers:
            peers.append(symbol)

    return peers[:8]
