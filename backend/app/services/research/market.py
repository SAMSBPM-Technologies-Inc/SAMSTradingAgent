"""
Market evidence — technicals, news, macro and alternative data.

The technical half of this system is the part that already worked, so this
module mostly re-expresses what `feature_engineering` computed into the ledger
rather than computing anything new. Two things do change.

First, headlines arrive with their source, date and URL attached, so a claim
about a recent development can be cited to the article that reported it. Those
fields were always stored and always dropped before the model saw them.

Second, every reading that is *absent* stays absent. The old prompt rendered
"N/A" for missing indicators, and `next_earnings_date` — a field nothing ever
wrote — printed N/A on every run for months. A line that always says nothing is
worse than no line, because it looks like a reading.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger
from app.services.research.formatting import money, pct, ratio

_TECH_SOURCE = "Computed from daily OHLCV (90-day window)"
_NEWS_SOURCE = "Finnhub company news"
_MACRO_SOURCE = "FRED"
_ALT_SOURCE = "yfinance alternative data"


def build_technical(ledger: Ledger, features: dict, raw: dict,
                    risk: dict, position: Optional[dict] = None) -> dict:
    """Add technical evidence and return a short summary."""
    as_of = str(features.get("computed_at") or raw.get("fetched_at") or "")[:10] or None
    price = features.get("current_price") or raw.get("current_price")

    def add(claim: str, value, meta: bool = False) -> None:
        ledger.add("T", claim, value, _TECH_SOURCE, as_of=as_of, meta=meta)

    add("Current price", money(price))
    add("Change today", pct((raw.get("day_change_pct") or 0) / 100.0, digits=2)
        if raw.get("day_change_pct") is not None else None)
    add("RSI-14", _rsi(features.get("rsi_14")))
    add("Stochastic RSI", _stoch(features.get("stoch_rsi")))
    add("MACD", _macd(features.get("macd_bullish")))
    add("Bollinger band position", _bollinger(features.get("bb_pct")))
    add("20-day moving average", money(features.get("ma_20")))
    add("50-day moving average", money(features.get("ma_50")))
    add("Trend (MA20 vs MA50)", _trend(features.get("ma_cross_bullish")))
    add("ADX-14 (trend strength)", ratio(features.get("adx_14"), digits=1))
    add("ATR-14", money(features.get("atr_14")))
    add("20-day annualised volatility", pct(features.get("volatility_20d")))
    add("Volume versus 20-day average",
        ratio(features.get("volume_anomaly"), suffix="x"))
    add("On-balance-volume direction", features.get("obv_direction"))
    add("VWAP-20", money(features.get("vwap_20")))

    if price and features.get("ma_20"):
        add("Distance from MA-20", pct((price - features["ma_20"]) / features["ma_20"]))

    add("Price-risk score (0-10, engine gate)", ratio(risk.get("risk_score"), digits=1))
    add("Price-risk level", risk.get("risk_level"))
    add("Price-risk explanation", risk.get("explanation"))

    # History depth is itself evidence. An agent reasoning about a "long-term
    # trend" needs to know it is looking at one quarter of daily bars.
    add("Price history available", "90 calendar days of daily bars", meta=True)

    if position:
        add("Current position", f"{position.get('quantity')} shares at average cost "
                                f"{money(position.get('avg_price'))}")
        add("Unrealised P&L on position", money(position.get("unrealized_pnl")))

    return {"has_price": price is not None, "held": bool(position)}


def build_news(ledger: Ledger, raw: dict, limit: int = 12) -> dict:
    """
    Add headline evidence, each attributable to its article.

    The URL is what makes this different from the previous prompt. A headline
    without one is a claim the reader has to take on trust; with one it is a
    pointer they can follow.
    """
    headlines = raw.get("recent_headlines") or []
    sentiment = raw.get("sentiment_raw") or {}

    for article in headlines[:limit]:
        headline = (article.get("headline") or "").strip()
        if not headline:
            continue
        ledger.add(
            "N",
            "Headline",
            headline,
            article.get("source") or _NEWS_SOURCE,
            as_of=(article.get("datetime") or "")[:10] or None,
            url=article.get("url") or None,
        )

    def add(claim: str, value, meta: bool = False) -> None:
        ledger.add("N", claim, value, "Finnhub headlines + VADER sentiment", meta=meta)

    add("Headline count, last 7 days", sentiment.get("article_count"))
    add("Share of headlines scored bullish", pct(sentiment.get("bullish_pct"), digits=0))
    add("Share of headlines scored bearish", pct(sentiment.get("bearish_pct"), digits=0))
    if sentiment.get("article_count") is not None:
        add("Sentiment method",
            "Lexicon sentiment over headline text only — article bodies are not "
            "retrieved, so nuance beyond the headline is not captured",
            meta=True)

    return {"headlines": len([h for h in headlines[:limit] if h.get("headline")])}


def build_macro(ledger: Ledger, raw: dict) -> None:
    """Market-wide conditions. Identical across the watchlist by construction."""
    macro = raw.get("macro") or {}
    as_of = str(macro.get("fetched_at") or "")[:10] or None

    def add(claim: str, value) -> None:
        ledger.add("M", claim, value, _MACRO_SOURCE, as_of=as_of)

    add("Fed funds rate", ratio(macro.get("fed_funds_rate"), digits=2, suffix="%"))
    add("10-year Treasury", ratio(macro.get("treasury_10y"), digits=2, suffix="%"))
    add("2-year Treasury", ratio(macro.get("treasury_2y"), digits=2, suffix="%"))
    spread = macro.get("yield_curve_spread")
    if spread is not None:
        shape = "inverted" if spread < 0 else "normal"
        add("Yield curve (10y minus 2y)", f"{spread:+.2f}% ({shape})")
    add("CPI year on year", ratio(macro.get("cpi_yoy_pct"), digits=2, suffix="%"))
    add("Unemployment rate", ratio(macro.get("unemployment"), digits=1, suffix="%"))
    add("VIX", ratio(macro.get("vix"), digits=1))


def build_alternative(ledger: Ledger, raw: dict) -> None:
    """
    Insider, options and short-interest readings, each with its limits stated.

    Every figure here comes from yfinance, which this codebase documents as
    rate-limited to nothing from the production host. The caveats are added as
    evidence rather than left implicit because an agent that sees "0 insider
    buys" and does not know the fetch usually fails will read absence as a
    bearish signal.
    """
    alt = raw.get("alternative_data") or {}
    insider = alt.get("insider_trades") or {}
    options = alt.get("options_flow") or {}
    short = alt.get("short_interest") or {}

    def add(claim: str, value, meta: bool = False) -> None:
        ledger.add("A", claim, value, _ALT_SOURCE, meta=meta)

    if insider.get("net_sentiment"):
        add("Insider transactions on file",
            f"{insider.get('buy_count_90d', 0)} buys / "
            f"{insider.get('sell_count_90d', 0)} sells — "
            f"net {insider.get('net_sentiment')}")
        add("Insider data caveat",
            "Most recent ~20 filed transactions, not a date-bounded window, and "
            "not weighted by dollar value or by the filer's role",
            meta=True)

    if options.get("put_call_ratio") is not None:
        add("Put/call volume ratio",
            f"{options['put_call_ratio']:.2f} ({options.get('sentiment') or 'unlabelled'})")
        add("Options data caveat",
            "Nearest expiry only, volume not open interest — a single expiry is "
            "not a read on positioning",
            meta=True)

    if short.get("short_percent_of_float") is not None:
        add("Short interest as share of float",
            pct(short.get("short_percent_of_float")))
        add("Days to cover", ratio(short.get("short_ratio"), digits=1))
    else:
        add("Short interest", "Not available — provider returns nothing from this host",
            meta=True)

    add("Institutional ownership and 13F activity",
        "Not available from any configured provider", meta=True)


def _rsi(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    label = "overbought" if value > 70 else "oversold" if value < 30 else "neutral"
    return f"{value:.1f} ({label})"


def _stoch(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    label = "overbought" if value > 0.8 else "oversold" if value < 0.2 else "neutral"
    return f"{value:.2f} ({label})"


def _macd(bullish: Optional[bool]) -> Optional[str]:
    if bullish is None:
        return None
    return "bullish — MACD above signal" if bullish else "bearish — MACD below signal"


def _bollinger(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    where = ("above the upper band" if value > 1 else "below the lower band"
             if value < 0 else "inside the bands")
    return f"{value:.0%} of the band width ({where})"


def _trend(bullish: Optional[bool]) -> Optional[str]:
    if bullish is None:
        return None
    return "MA-20 above MA-50" if bullish else "MA-20 below MA-50"
