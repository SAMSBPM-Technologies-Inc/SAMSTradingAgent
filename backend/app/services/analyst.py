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
import json
import re
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS, get_db
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
- Respond with valid JSON only — no markdown fences, no text outside the JSON object
- Reference actual numbers from the data provided; do not invent figures
- Set price_target and stop_loss as realistic levels derived from ATR or support/resistance
- thesis: 1-2 sentences capturing the core investment case
- analyst_note: 2-3 paragraphs written like a real sell-side research note
- key_risks and catalysts: 2-4 items each, specific to this ticker and the current data
- Signal must be exactly one of: BUY, SELL, HOLD
- Conviction must be exactly one of: HIGH, MEDIUM, LOW
- When technicals and fundamentals conflict, reason through the dominant driver before deciding
"""

_RESPONSE_SCHEMA = """\
{
  "signal": "BUY|SELL|HOLD",
  "conviction": "HIGH|MEDIUM|LOW",
  "price_target": <float or null>,
  "stop_loss": <float or null>,
  "time_horizon": "<e.g. 2-4 weeks or 3-6 months>",
  "thesis": "<1-2 sentence core investment thesis>",
  "bull_case": "<primary upside argument>",
  "bear_case": "<primary downside risk>",
  "key_risks": ["<risk 1>", "<risk 2>"],
  "catalysts": ["<catalyst 1>", "<catalyst 2>"],
  "analyst_note": "<2-3 paragraph research note in sell-side style>"
}"""


async def run_analysis(ticker: str) -> Optional[dict]:
    """
    Produce a full analyst signal doc for *ticker*.
    Returns a signal-doc-compatible dict (ready to upsert into stocks_signals)
    or None if analyst is disabled / API call fails.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
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

    # Headlines
    headlines = raw.get("recent_headlines") or []
    hl_str = "\n".join(f"- {h['headline']}" for h in headlines[:8]) if headlines else "No recent headlines available"

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

Respond with this exact JSON schema (no markdown, no extra text):
{_RESPONSE_SCHEMA}"""


# ── Claude API call ────────────────────────────────────────────────────────────

async def _call_claude(
    context: str,
    api_key: str,
    model: str = _MODEL,
    extended_thinking: bool = True,
    effort: str = "medium",
) -> dict:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Prompt caching keeps the system prompt cheap on repeat calls. Worth having,
    # but not worth much here: input is a small share of the bill next to
    # thinking tokens, so the levers that matter are the model, the effort
    # level, and not making the call at all.
    system = [
        {
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    kwargs: dict = {
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": context}],
        "max_tokens": _MAX_TOKENS,
    }

    if extended_thinking:
        # Adaptive thinking replaces the fixed `budget_tokens` form, which is
        # deprecated on 4.6-era models and rejected outright by current ones.
        # It also matches spend to difficulty: an obvious HOLD no longer costs
        # the same as a genuinely contested call, which the fixed budget did.
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort}
    else:
        # Adaptive is the default on these models, so opting out has to be
        # explicit — omitting `thinking` would leave it on.
        kwargs["thinking"] = {"type": "disabled"}

    message = await client.messages.create(**kwargs)

    # A truncated response cannot be parsed and wastes the whole call. Surface
    # it rather than letting it read as a generic JSON failure downstream.
    if getattr(message, "stop_reason", None) == "max_tokens":
        logger.warning(
            "analyst_response_truncated",
            model=model, max_tokens=_MAX_TOKENS,
            hint="raise _MAX_TOKENS or lower analyst_effort",
        )

    # Extended thinking returns multiple content blocks; extract the text block
    raw_text = ""
    for block in message.content:
        if block.type == "text":
            raw_text = block.text.strip()
            break

    if not raw_text:
        raise ValueError("No text block in Claude response")

    # Strip markdown fences if model adds them despite instructions
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    parsed = json.loads(raw_text)

    # Validate required fields
    for field in ("signal", "conviction", "thesis", "analyst_note"):
        if field not in parsed:
            raise ValueError(f"Missing required field '{field}' in analyst response")

    # Normalise signal/conviction
    parsed["signal"] = parsed["signal"].upper()
    parsed["conviction"] = parsed["conviction"].upper()
    if parsed["signal"] not in ("BUY", "SELL", "HOLD"):
        parsed["signal"] = "HOLD"
    if parsed["conviction"] not in ("HIGH", "MEDIUM", "LOW"):
        parsed["conviction"] = "LOW"

    # Log cache and thinking usage for cost monitoring
    usage = message.usage
    logger.info(
        "analyst_claude_usage",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read=getattr(usage, "cache_read_input_tokens", 0),
        cache_created=getattr(usage, "cache_creation_input_tokens", 0),
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
