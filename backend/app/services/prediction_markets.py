"""
Prediction Markets — Polymarket
───────────────────────────────
What people betting real money think will happen.

This is the one sentiment source in the system where the participants are
financially exposed to being wrong, which makes it categorically different from
a message board and worth a separate module rather than a third social feed. A
market price is a probability somebody is willing to fund.

What it is good for here is narrow and worth stating, because the temptation is
to over-read it. Polymarket has deep markets on macro and political events —
rate decisions, elections, recession calls — and almost nothing on individual
equities. So this contributes *backdrop*, not a view on a company: a dossier
whose macro section says the Fed is expected to hold reads differently when a
funded market puts that at 88% than when it puts it at 51%.

Two rules, both the same ones the rest of the evidence layer follows. A market
that cannot be read contributes nothing rather than a neutral prior. And the
probability enters the ledger as a citable number with its question and its
resolution date attached — an agent may cite "the market prices a hold at 88%
[K1]" and cannot assert what the Fed will do.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_GAMMA_BASE = "https://gamma-api.polymarket.com/markets"
_TIMEOUT = 10.0

#: How many active markets to read. Small on purpose: the useful set is a
#: handful of macro questions, and a long tail of niche markets is noise an
#: agent would have to be told to ignore.
_LIMIT = 20

#: Only markets with real money behind them. A market with $400 of volume is a
#: few people's opinion wearing a price tag.
_MIN_VOLUME = 50_000.0


async def fetch_macro_markets() -> Optional[list[dict]]:
    """
    Liquid, unresolved macro markets, newest first.

    Returns None on failure and an empty list when nothing clears the liquidity
    floor — different facts, and the caller renders them differently.
    """
    if not get_settings().prediction_markets_enabled:
        return None

    params = {
        "active": "true",
        "closed": "false",
        "limit": str(_LIMIT),
        "order": "volumeNum",
        "ascending": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_GAMMA_BASE, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("polymarket_fetch_failed", error=str(exc))
        return None

    if not isinstance(payload, list):
        return None

    out: list[dict] = []
    for market in payload:
        volume = _number(market.get("volumeNum") or market.get("volume"))
        if volume is None or volume < _MIN_VOLUME:
            continue
        probability = _yes_probability(market)
        if probability is None:
            continue
        question = str(market.get("question") or "").strip()
        if not question:
            continue
        out.append({
            "question": question,
            "probability": round(probability, 4),
            "volume": round(volume, 2),
            "ends": _date(market.get("endDate")),
            "source": "Polymarket",
            "as_of": datetime.now(tz=timezone.utc).date().isoformat(),
        })
    return out


def _yes_probability(market: dict) -> Optional[float]:
    """
    The YES price, as a probability.

    Polymarket returns outcome prices as a JSON-encoded string in some
    responses and a list in others. Both are handled; anything else returns
    None rather than a guess, because a mis-parsed price here would enter the
    ledger looking exactly like a real one.
    """
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    value = _number(raw[0])
    if value is None or not (0.0 <= value <= 1.0):
        return None
    return value


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> Optional[str]:
    if not value:
        return None
    return str(value)[:10]
