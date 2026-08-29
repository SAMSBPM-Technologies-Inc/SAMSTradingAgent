"""
Prediction-market evidence — funded probabilities (prefix `K`).

The participants here are financially exposed to being wrong, which is what
separates these items from the `S` block. A price is a probability somebody has
paid to hold.

These are macro backdrop and nothing more. Polymarket has depth on rate
decisions, elections and recession calls, and essentially nothing on individual
equities — so an item here changes how the *macro* section of a dossier should
be read, and says nothing about a company. Each carries its question, its
resolution date and its volume, so an agent can cite the market and cannot
assert the outcome.

`meta=True` throughout, deliberately. These describe the environment, not the
business, and `substantive_count` decides both whether a ticker is researchable
and whether an agent is worth calling — a name with no financials must not
become researchable because the Fed has a liquid market this week.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger

_SOURCE = "Polymarket (funded prediction market)"

#: How many markets reach the ledger. The useful set is a handful of macro
#: questions; a long tail would be noise an agent has to be told to ignore.
_MAX_ITEMS = 6


def build(ledger: Ledger, markets: Optional[list[dict]]) -> dict:
    """Add prediction-market evidence and return a coverage summary."""
    if markets is None:
        return {"available": False, "reason": "not collected"}
    if not markets:
        ledger.add("K", "Prediction markets",
                   "no market cleared the liquidity floor", _SOURCE, meta=True)
        return {"available": False, "reason": "nothing liquid enough"}

    added = 0
    for market in markets[:_MAX_ITEMS]:
        probability = market.get("probability")
        if probability is None:
            continue
        ends = market.get("ends")
        detail = f"{probability:.0%} implied, ${market.get('volume', 0):,.0f} traded"
        if ends:
            detail += f", resolves {ends}"
        if ledger.add(
            "K",
            f"Market price on: {market.get('question')}",
            detail, _SOURCE, as_of=market.get("as_of"), meta=True,
        ):
            added += 1

    return {"available": added > 0, "items": added}
