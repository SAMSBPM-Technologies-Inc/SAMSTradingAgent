"""
AI Analyst Service
──────────────────
Uses the Claude API to produce a structured, senior-analyst-quality research
note for a given ticker. Reads all enriched data directly from MongoDB so it
can be called independently of the pipeline step order.

Requires: ANTHROPIC_API_KEY + ENABLE_AI_ANALYST=true

Degrades gracefully: returns None when the key is absent or the API call fails,
allowing pipeline.py to fall back to the rule-based signal_generator.

Output schema stored in signal doc under "analyst_output":
  signal       : BUY | SELL | HOLD
  conviction   : HIGH | MEDIUM | LOW
  price_target : float | null
  stop_loss    : float | null
  time_horizon : str
  thesis       : str  (1-2 sentences)
  bull_case    : str
  bear_case    : str
  key_risks    : list[str]
  catalysts    : list[str]
  analyst_note : str  (2-3 paragraph research note)
"""
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS, get_db
from app.services.research.agents.base import AgentSpec, run_agent
from app.services.risk_engine import assess_risk
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Model config ───────────────────────────────────────────────────────────────
# Sonnet 5 reaches near-Opus quality on structured analysis at $3/$15 per MTok
# against Opus's $5/$25. Output rate is what matters: thinking tokens bill as
# output and dominate this workload — input is well under a tenth of the cost.
_MODEL = "claude-sonnet-5"

# A ceiling, not a reservation: only tokens actually generated are billed, so
# there is no cost to leaving adaptive thinking room. Too *low* is what costs —
# a truncated response fails to parse and the whole call is wasted.
_MAX_TOKENS = 12000

_SYSTEM_PROMPT = """\
You are a senior equity research analyst with 20 years of experience across multiple market cycles.
You produce institutional-grade research notes: specific, data-driven, and honest about uncertainty.

Rules:
- Reference actual numbers from the data provided; do not invent figures
- Set price_target and stop_loss as realistic levels derived from ATR or support/resistance
- thesis: 1-2 sentences capturing the core investment case
- analyst_note: 2-3 paragraphs written like a real sell-side research note
- key_risks and catalysts: 2-4 items each, specific to this ticker and the current data
- Signal must be exactly one of: BUY, SELL, HOLD
- Conviction must be exactly one of: HIGH, MEDIUM, LOW
- When technicals and fundamentals conflict, reason through the dominant driver before deciding
"""

# The shape, enforced server-side rather than requested in prose.
#
# This call used to paste a hand-written pseudo-schema into the prompt, take
# whatever came back, strip markdown fences with two regexes and hope
# `json.loads` worked. A truncated or fenced response failed to parse and wasted
# the entire call — including its thinking tokens, which are most of the bill.
# `services/research/` has used structured outputs since it was written; this is
# the same mechanism, so both paths now fail the same way and neither can
# silently return prose.
#
# Note the constraints deliberately absent: no `minimum`/`maximum`, no string
# length bounds, no array bounds. Structured outputs reject those outright with
# a 400 rather than ignoring them — the incident `tests/test_research_schemas.py`
# fences against. Bounds that matter are enforced in Python below.
_NUMBER_OR_NULL = {"type": ["number", "null"]}
_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}

_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "conviction": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "price_target": _NUMBER_OR_NULL,
        "stop_loss": _NUMBER_OR_NULL,
        "time_horizon": _STRING,
        "thesis": _STRING,
        "bull_case": _STRING,
        "bear_case": _STRING,
        "key_risks": _STRING_LIST,
        "catalysts": _STRING_LIST,
        "analyst_note": _STRING,
    },
    "required": ["signal", "conviction", "price_target", "stop_loss",
                 "time_horizon", "thesis", "bull_case", "bear_case",
                 "key_risks", "catalysts", "analyst_note"],
    "additionalProperties": False,
}


async def run_analysis(ticker: str, client: Any = None) -> Optional[dict]:
    """
    Produce a full analyst signal doc for *ticker*.
    Returns a signal-doc-compatible dict (ready to upsert into stocks_signals)
    or None if analyst is disabled / API call fails.
    """
    settings = get_settings()
    if client is None and not settings.anthropic_api_key:
        logger.warning("analyst_disabled", reason="ANTHROPIC_API_KEY not set")
        return None

    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    raw  = await db[COLL_RAW].find_one({"ticker": ticker})
    if not feat or not raw:
        logger.warning("analyst_missing_data", ticker=ticker)
        return None

    risk = assess_risk(feat)
    context = _build_context(ticker, feat, raw, risk)

    try:
        analyst_output = await _call_claude(
            context,
            settings.anthropic_api_key,
            model=settings.analyst_model,
            extended_thinking=settings.analyst_extended_thinking,
            effort=settings.analyst_effort,
            client=client,
        )
    except Exception as exc:
        logger.warning("analyst_claude_failed", ticker=ticker, error=str(exc))
        return None

    # Build a signal doc compatible with stocks_signals schema
    price = feat.get("current_price", 0.0)
    signal_doc = {
        "ticker": ticker,
        "generated_at": utcnow(),
        "score": round(feat.get("composite_score", 0.5), 4),
        "risk": risk,
        "signal": analyst_output.get("signal", "HOLD"),
        "confidence": _conviction_to_confidence(analyst_output.get("conviction", "LOW")),
        "entry_suggestion": _entry_suggestion(analyst_output, price),
        "exit_suggestion": _exit_suggestion(analyst_output, price),
        "explanation": _build_explanation(ticker, analyst_output, feat, risk),
        # Extended analyst fields
        "analyst_output": analyst_output,
        # Persisted, not merely returned. `pipeline._needs_analyst_refresh`
        # reads this field back off the stored document to decide whether a
        # cached analyst signal exists; the pipeline used to set it on the
        # in-memory dict only, so the stored document never carried it and
        # trigger 1 ("no_ai_signal") fired on every cycle. The 60-minute cache
        # therefore never hit once: Claude was re-called every ingestion cycle
        # for every ticker that passed the gate. That is what made a borderline
        # name flip BUY/HOLD eight times in an hour — each flip is a fresh
        # sampling of the model on unchanged inputs — and it is where the
        # analyst bill went. `GET /analyze` read the same missing field, so the
        # UI also reported "analyst did not run" on reports that it wrote.
        "analyst_used": True,
    }

    await db[COLL_SIGNALS].replace_one({"ticker": ticker}, signal_doc, upsert=True)

    logger.info(
        "analyst_complete",
        ticker=ticker,
        signal=signal_doc["signal"],
        conviction=analyst_output.get("conviction"),
        price_target=analyst_output.get("price_target"),
    )
    return signal_doc


# ── Context builder ────────────────────────────────────────────────────────────

def _format_headline(article: dict) -> str:
    """One headline line, carrying whatever provenance the article has."""
    headline = (article.get("headline") or "").strip()
    parts = []
    source = (article.get("source") or "").strip()
    if source:
        parts.append(source)
    published = (article.get("datetime") or "")[:10]
    if published:
        parts.append(published)
    url = (article.get("url") or "").strip()
    if url:
        parts.append(url)
    suffix = f"  [{' | '.join(parts)}]" if parts else ""
    return f"- {headline}{suffix}"


def _build_context(ticker: str, feat: dict, raw: dict, risk: dict) -> str:
    price   = feat.get("current_price", 0.0)
    chg     = raw.get("day_change_pct", 0.0)
    date    = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Technical
    rsi     = feat.get("rsi_14")
    rsi_str = f"{rsi:.1f} ({'overbought' if rsi and rsi > 70 else 'oversold' if rsi and rsi < 30 else 'neutral'})" if rsi else "N/A"
    macd_b  = feat.get("macd_bullish")
    macd_str = "Bullish crossover (MACD above signal)" if macd_b else ("Bearish crossover (MACD below signal)" if macd_b is False else "N/A")
    bb_pct  = feat.get("bb_pct")
    bb_str  = f"{bb_pct:.0%} (0%=lower band, 100%=upper band{', extended above upper band' if bb_pct and bb_pct > 1 else ''})" if bb_pct is not None else "N/A"
    stoch   = feat.get("stoch_rsi")
    stoch_str = f"{stoch:.2f} ({'overbought' if stoch and stoch > 0.8 else 'oversold' if stoch and stoch < 0.2 else 'neutral'})" if stoch is not None else "N/A"
    ma_20   = feat.get("ma_20")
    ma_50   = feat.get("ma_50")
    trend   = "Bullish (price > MA20 > MA50)" if feat.get("ma_cross_bullish") else "Bearish (MA20 < MA50)" if feat.get("ma_cross_bullish") is False else "Mixed"
    vol     = feat.get("volatility_20d", 0.0)
    atr     = feat.get("atr_14")
    vol_anom = feat.get("volume_anomaly", 1.0)

    # Scores
    tech_s  = feat.get("technical_score",   0.5)
    fund_s  = feat.get("fundamental_score", 0.5)
    sent_s  = feat.get("sentiment_score",   0.5)
    macro_s = feat.get("macro_score",       0.5)
    comp    = feat.get("composite_score",   0.5)

    # Fundamentals
    fund = raw.get("fundamentals") or {}
    pe      = fund.get("pe_ratio")
    rev_g   = fund.get("revenue_growth_yoy")
    fcf     = fund.get("free_cash_flow")
    de      = fund.get("debt_to_equity")
    rec     = fund.get("analyst_recommendation")
    tgt     = fund.get("analyst_target_price")
    n_earn  = fund.get("next_earnings_date")
    sector  = fund.get("sector")

    def fmt(v, suffix="", pct=False, dollar=False, scale=1):
        if v is None:
            return "N/A"
        v = float(v) * scale
        if pct:
            return f"{v:.1%}"
        if dollar:
            return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:.2f}"
        return f"{v:.2f}{suffix}"

    # Macro
    macro = raw.get("macro") or {}
    fed     = macro.get("fed_funds_rate")
    t10     = macro.get("treasury_10y")
    t2      = macro.get("treasury_2y")
    spread  = macro.get("yield_curve_spread")
    cpi     = macro.get("cpi_yoy_pct")
    unemp   = macro.get("unemployment")
    vix     = macro.get("vix")
    spread_str = f"{spread:+.2f}% ({'normal' if spread and spread > 0 else 'INVERTED — recession signal'})" if spread is not None else "N/A"
    vix_str = f"{vix:.1f} ({'elevated fear' if vix and vix > 25 else 'calm' if vix and vix < 18 else 'moderate'})" if vix else "N/A"

    # Headlines. Rendered with their source, date and URL — all three were
    # already stored on every article and all three were dropped here, which is
    # why the model could reference "recent news" but never attribute a claim to
    # anything. A model asked for institutional-grade research over anonymous
    # headline text has no way to cite, however it is prompted.
    headlines = raw.get("recent_headlines") or []
    hl_str = "\n".join(_format_headline(h) for h in headlines[:8]) \
        if headlines else "No recent headlines available"

    sent_raw = raw.get("sentiment_raw") or {}

    # Alternative data
    alt    = raw.get("alternative_data") or {}
    opt    = alt.get("options_flow") or {}
    short  = alt.get("short_interest") or {}
    ins    = alt.get("insider_trades") or {}
    pcr    = opt.get("put_call_ratio")
    pcr_str  = f"{pcr:.2f} ({opt.get('sentiment', 'N/A')})" if pcr is not None else "N/A"
    si_pct   = short.get("short_percent_of_float")
    si_str   = f"{si_pct:.1%} short float | {short.get('short_ratio', 'N/A')}d to cover | squeeze risk: {short.get('squeeze_risk', 'N/A')}" if si_pct is not None else "N/A"
    ins_str  = f"{ins.get('buy_count_90d', 0)} buys / {ins.get('sell_count_90d', 0)} sells (90d) — {ins.get('net_sentiment', 'N/A')}" if ins.get("net_sentiment") else "N/A"

    return f"""Analyze {ticker} as of {date}. Current price: ${price:.2f} ({chg:+.2f}% today){f' | Sector: {sector}' if sector else ''}

=== TECHNICAL ANALYSIS ===
RSI-14: {rsi_str}
MACD: {macd_str}
Bollinger Band position: {bb_str}
Stochastic RSI: {stoch_str}
MA-20: {fmt(ma_20, dollar=True)} | MA-50: {fmt(ma_50, dollar=True)} | Trend: {trend}
ATR-14: {fmt(atr, dollar=True)} | 20-day Annualised Volatility: {vol:.0%}
Volume anomaly: {vol_anom:.1f}x 20-day average

=== SCORES (0=bearish, 1=bullish) ===
Technical Score:   {tech_s:.2f}
Fundamental Score: {fund_s:.2f}
Sentiment Score:   {sent_s:.2f}  ({sent_raw.get('article_count', 0)} articles, {sent_raw.get('bullish_pct', 0.5):.0%} bullish, source: {sent_raw.get('source', 'N/A')})
Macro Score:       {macro_s:.2f}
Composite Score:   {comp:.2f}

=== FUNDAMENTALS ===
P/E Ratio: {fmt(pe)}
Revenue Growth (YoY): {fmt(rev_g, pct=True)}
Free Cash Flow: {fmt(fcf, dollar=True)}
Debt/Equity: {fmt(de)}%
Analyst Consensus: {rec or 'N/A'}{f' | Target: ${tgt:.2f}' if tgt else ''}
Next Earnings: {n_earn or 'N/A'}

=== MACRO ENVIRONMENT ===
Fed Funds Rate: {fmt(fed)}%
10Y Treasury: {fmt(t10)}% | 2Y Treasury: {fmt(t2)}%
Yield Curve (10Y-2Y): {spread_str}
CPI YoY: {fmt(cpi)}%
Unemployment: {fmt(unemp)}%
VIX: {vix_str}

=== RECENT NEWS (last 7 days) ===
{hl_str}

=== ALTERNATIVE DATA ===
Options Flow (P/C ratio): {pcr_str}
Short Interest: {si_str}
Insider Transactions (90d): {ins_str}

=== RISK ASSESSMENT ===
Risk Score: {risk['risk_score']:.1f}/10 ({risk['risk_level']})
{risk['explanation']}

Your response shape is enforced by the API — write the content, not the \
envelope. Leave price_target or stop_loss null rather than estimating one the \
data does not support."""


# ── Claude API call ────────────────────────────────────────────────────────────

async def _call_claude(
    context: str,
    api_key: str,
    model: str = _MODEL,
    extended_thinking: bool = True,
    effort: str = "medium",
    client: Any = None,
) -> dict:
    """
    One structured call, through the same seam the research agents use.

    This shares `agents/base.run_agent` rather than reimplementing the request,
    and that is the point of the change. The old version built its client
    inline — which is why this module has had no tests since it was written —
    asked for JSON in prose, stripped markdown fences with two regexes, and
    called `json.loads` on whatever survived. A truncated response failed to
    parse and wasted the whole call including its thinking tokens, which are
    most of the bill. `run_agent` already handles the refusal stop reason, the
    truncation stop reason, and schema enforcement, and it is covered by
    `tests/test_research_orchestrator.py`.

    `client` is injectable for the same reason it is on `build_dossier`: so
    this path can finally be tested without a network call.
    """
    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)

    spec = AgentSpec(
        name="analyst",
        prefixes=(),
        system_prompt=_SYSTEM_PROMPT,
        task=context,
        schema=_RESPONSE_SCHEMA,
        model_role="orchestrator",
    )
    # The system prompt carries the cache breakpoint here rather than an
    # evidence block: this path has no ledger, and the prompt is the only part
    # that repeats across tickers. It is small enough that the hit is worth
    # little — the levers that matter on this call are the model, the effort
    # level, and `pipeline._analyst_worth_calling` not making it at all.
    result = await run_agent(client, spec, _SYSTEM_PROMPT, model, effort,
                             extended_thinking)
    if not result.ok:
        raise ValueError(result.error or "analyst call produced no output")

    parsed = dict(result.output or {})

    # The schema guarantees the enum members, so these two normalisations are
    # now belt-and-braces rather than the only thing standing between the model
    # and a signal doc. Kept because `_conviction_to_confidence` and the
    # trading path both key off exact strings, and a silent drift to "Buy"
    # would route through `.get(..., 0.25)` and read as low conviction.
    parsed["signal"] = str(parsed.get("signal", "HOLD")).upper()
    parsed["conviction"] = str(parsed.get("conviction", "LOW")).upper()
    if parsed["signal"] not in ("BUY", "SELL", "HOLD"):
        parsed["signal"] = "HOLD"
    if parsed["conviction"] not in ("HIGH", "MEDIUM", "LOW"):
        parsed["conviction"] = "LOW"

    logger.info(
        "analyst_claude_usage",
        model=model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read=result.cache_read_tokens,
    )
    return parsed


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _conviction_to_confidence(conviction: str) -> float:
    return {"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(conviction, 0.25)


def _entry_suggestion(output: dict, price: float) -> Optional[str]:
    signal = output.get("signal")
    pt = output.get("price_target")
    sl = output.get("stop_loss")
    if signal == "BUY" and price > 0:
        entry = f"${price:.2f} (current)"
        parts = [entry]
        if sl:
            parts.append(f"stop-loss ${sl:.2f}")
        if pt:
            parts.append(f"target ${pt:.2f}")
        return " | ".join(parts)
    if signal == "SELL":
        return f"Short near ${price:.2f}" + (f" | cover target ${pt:.2f}" if pt else "")
    return None


def _exit_suggestion(output: dict, price: float) -> Optional[str]:
    signal = output.get("signal")
    sl = output.get("stop_loss")
    pt = output.get("price_target")
    horizon = output.get("time_horizon", "")
    if signal == "BUY":
        parts = []
        if sl:
            parts.append(f"Stop-loss ${sl:.2f}")
        if pt:
            parts.append(f"Take-profit ${pt:.2f}")
        if horizon:
            parts.append(f"Horizon: {horizon}")
        return " | ".join(parts) if parts else None
    if signal == "HOLD":
        return f"Monitor over {horizon}" if horizon else f"Monitor; re-evaluate on ±5% move from ${price:.2f}"
    return None


def _build_explanation(ticker: str, output: dict, feat: dict, risk: dict) -> str:
    signal    = output.get("signal", "HOLD")
    conviction = output.get("conviction", "LOW")
    thesis    = output.get("thesis", "")
    score     = feat.get("composite_score", 0.5)
    rsi       = feat.get("rsi_14")
    macd_bull = feat.get("macd_bullish")
    tech_s    = feat.get("technical_score", 0.5)
    fund_s    = feat.get("fundamental_score", 0.5)
    sent_s    = feat.get("sentiment_score", 0.5)
    macro_s   = feat.get("macro_score", 0.5)

    rsi_str  = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"
    macd_str = "MACD↑" if macd_bull else ("MACD↓" if macd_bull is False else "")

    indicators = " | ".join(filter(None, [rsi_str, macd_str]))
    scores_str = f"tech={tech_s:.2f} fund={fund_s:.2f} sent={sent_s:.2f} macro={macro_s:.2f}"

    return (
        f"{ticker} → {signal} ({conviction}) | score={score:.2f} | "
        f"Risk={risk['risk_level']} ({risk['risk_score']:.1f}/10) | "
        f"{indicators} | [{scores_str}] | {thesis}"
    )
