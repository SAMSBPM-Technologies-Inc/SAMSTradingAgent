# SAMSTradingAgent — Design Document

> Last updated: 2026-08-08

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Why These Data Sources?](#2-why-these-data-sources)
3. [Signal Design Decisions](#3-signal-design-decisions)
4. [Alternative Data Design](#4-alternative-data-design)
5. [Notification Design](#5-notification-design)
6. [Performance Tracking Design](#6-performance-tracking-design)
7. [UI/UX Design Decisions](#7-uiux-design-decisions)
8. [Data Quality Signals](#8-data-quality-signals)
9. [Scoring Weight Rationale](#9-scoring-weight-rationale)

---

## 1. Design Philosophy

SAMSTradingAgent is built around five guiding principles. Every architectural and UX decision traces back to at least one of them.

### Signal Quality Over Quantity

A trading tool that generates spurious BUY and SELL signals is worse than useless — it gives users false confidence. This system is deliberately biased toward HOLD. A signal only fires when multiple independent indicators agree, and when risk conditions are appropriate. The goal is that when a BUY or SELL does appear, it means something.

### Graceful Degradation

Every external data source — FRED, Finnhub, Yahoo Finance, Anthropic — is treated as unreliable. Network failures, rate limits, and stale data are expected, not exceptional. Every sub-score has a defined fallback: when data is unavailable, the component returns `0.5` (neutral) rather than raising an error or crashing the pipeline. The composite score is always computable, even if only price data is available.

### Informational Edge

The system exists to surface signals that Bloomberg terminals and retail platforms don't surface easily in a unified, integrated view. Put/call ratios, insider transaction patterns, and yield curve inversion are all publicly available — but scattered. Aggregating and scoring them in a single pipeline gives retail investors the kind of multi-dimensional view that was historically only practical for institutional analysts.

### Transparency Over Black-Box Output

Every signal record carries confidence, conviction, and the sub-scores that produced it. Users can always see whether a BUY came from technical strength, fundamental quality, or sentiment momentum. The AI analyst goes further: it must justify its signal in plain English, with a written thesis grounded in the same numbers the user can inspect. No signal should be taken on faith.

### No Premature Action

The system defaults to inaction. This is intentional. Retail investors lose money disproportionately from over-trading relative to under-trading. When the evidence is mixed or weak, HOLD is not a failure mode — it is the correct recommendation.

---

## 2. Why These Data Sources?

The following table compares the signal layers in SAMSTradingAgent against what a professional Bloomberg terminal provides and what this system contributes.

| Signal Layer | Source Used | Bloomberg Equivalent | What This System Adds |
|---|---|---|---|
| Price / Volume | Yahoo Finance (yfinance) | Yes | Free, real-time-enough for daily signals; no licensing cost |
| Technical indicators | `ta` library (local computation) | Yes | Standard RSI/MACD/Bollinger/Stoch RSI computed locally; no API dependency |
| Fundamentals | yfinance `.info` | Yes | P/E, revenue growth, free cash flow, analyst consensus, debt/equity |
| Macro environment | FRED (Federal Reserve) | Yes | Official Federal Reserve data, free tier; VIX from yfinance |
| News sentiment | Finnhub + VADER | Partial | Real ticker-specific headlines with NLP sentiment scoring; Bloomberg has this but charges for it |
| AI analyst narrative | Claude `claude-sonnet-4-6` | No | Full structured research note with thesis, bull/bear case, catalysts, risks — Bloomberg has no equivalent |
| Options flow (P/C ratio) | yfinance options chain | Expensive | Put/call ratio for the nearest expiry; options data on Bloomberg costs extra |
| Short interest | yfinance `.info` | Yes | `% float shorted`, days to cover; displayed as informational context |
| Insider transactions | yfinance insider transactions | Partial | 90-day buy/sell count, scored; Bloomberg shows this but doesn't score it |

The deliberate choice to use free or low-cost data sources is not a quality compromise — it is the design goal. The system is intended to be self-hostable for individual investors without institutional data budgets.

---

## 3. Signal Design Decisions

### Why 0.65 / 0.35 Thresholds for BUY / SELL?

The composite score is a blend of six noisy sub-scores, each computed from imperfect external data. Any individual sub-score at `0.6` could be noise. Setting the BUY threshold at `0.65` — 15 percentage points above neutral — means the composite only crosses the line when multiple independent signals are aligned in the bullish direction simultaneously. The same logic applies to SELL at `0.35`.

This is intentionally conservative. A threshold of `0.55` would produce more signals but more false positives. The design trades recall for precision.

### Why Is HOLD the Default?

The if/elif/else logic resolves to HOLD for everything between `0.35` and `0.65`. This covers the majority of observations. In practice, markets spend most of their time in ambiguous regimes where no directional call is well-supported by data.

Retail investors lose more money from over-trading than under-trading. Action based on weak signals has negative expected value after transaction costs and bid/ask spread. When conviction is unclear, the system's job is to say so clearly — not to generate a direction.

### Why Does Risk Gate BUY but Not SELL?

The risk engine computes a score that rises with volatility, overbought RSI, high VIX, and bearish technical momentum. When `risk_score > 6.5`, a computed BUY is overridden to HOLD.

The asymmetry is intentional:

- **Entry gatekeeping (BUY):** High volatility and overbought conditions are strong reasons not to enter a new position. The risk context correctly prevents entry at a bad time.
- **Exit confirmation (SELL):** If a SELL signal has fired, the composite score has already fallen below threshold. The deterioration is already baked into the signal. Gating SELL with risk would prevent users from exiting deteriorating positions — the opposite of the intended protection.

### Why Freeze `fundamental_score` at 0.5 in XGBoost?

Training the XGBoost model requires labeling historical days with their forward returns. The technical indicators and macro data at any historical date can be reconstructed from price history and FRED archives. Fundamental ratios (P/E, revenue growth, FCF) cannot: Yahoo Finance does not provide point-in-time historical snapshots of these figures.

If current fundamentals were used to label historical training rows, the model would train on data that was not available at the time of the signal — look-ahead bias. This would inflate training accuracy and produce a model that fails out of sample.

By freezing both `fundamental_score` and `sentiment_score` at `0.5` during training, the model learns from only the signals it can actually observe historically. Inference uses the same `0.5` value to match the training distribution. The model therefore reflects purely technical and macro-driven return patterns, which is acceptable for the swing trade time horizon this system targets.

---

## 4. Alternative Data Design

### Options Flow: Put/Call Ratio

**Why put/call ratio?**
Institutional participants and informed traders use options to hedge or express directional views before expected price moves. A spike in put volume relative to call volume — especially concentrated in near-term expiries — has historically been a leading indicator of downward price pressure. The ratio is a proxy for aggregate market positioning.

**Why nearest expiry?**
Near-dated options have the highest open interest concentration and the most active participation from both retail and institutional traders. Longer-dated options are used more for structural hedges (LEAPS), which are less relevant to the 20-trading-day signal horizon of this system.

**Score mapping:**

| P/C Ratio | Score | Interpretation |
|---|---|---|
| ≤ 0.5 | 1.0 | Calls dominating — bullish positioning |
| 0.5 – 1.5 | Linear | Neutral range |
| ≥ 1.5 | 0.0 | Puts dominating — bearish hedging activity |

### Short Interest: Display Only, Not Scored

Short interest as a percentage of float is shown on the ticker detail page but is not included in the composite score. This is a deliberate design decision.

High short interest is fundamentally ambiguous:

- **Bearish reading:** A large fraction of market participants expect the price to fall. This is consensus information — not necessarily edge.
- **Contrarian / squeeze reading:** High short interest combined with declining availability of borrow is the precondition for a short squeeze. Stocks like GameStop showed that high short interest can become violently bullish if a catalyst appears.

Because the net directional implication depends on subsequent price action that the system cannot predict, scoring short interest would introduce more noise than signal. Instead, it is surfaced as informational context so users can apply their own judgment.

**Squeeze risk badge:** When short interest exceeds 20% of float AND days-to-cover exceeds 5, the UI displays a `HIGH SQUEEZE RISK` badge on the ticker. This is informational only — it does not affect the composite score or the signal.

### Insider Transactions: Why Buys Signal, Sells Don't

**Why insider buying is a clean signal:**
Corporate insiders buy their own company's stock with personal money. They have no fiduciary reason to do so; the only rational motive is that they believe the stock will go up. Cluster buying — multiple insiders buying within the same 90-day window — is one of the most academically well-supported alternative signals in financial research.

**Why insider selling is not a reliable signal:**
Insiders sell shares for many reasons that have nothing to do with expected price direction:

- Pre-scheduled 10b5-1 plans (sales set up months in advance)
- Diversification of personal wealth out of concentrated equity positions
- Tax planning around vesting events
- Exercise of expiring options

Because insider selling can happen at any valuation for non-predictive reasons, it is a noisy signal. Including it in the score would dilute the clean buy signal rather than complement it. The insider score therefore counts only purchases:

```
insider_score = insider_buys / (insider_buys + insider_sells)
```

If an insider bought 3 of the 4 transactions in the past 90 days, the score is `0.75`. If there are no transactions, the score defaults to `0.5` (neutral — no information).

**Why 90 days?**
A 90-day window is short enough to reflect current management sentiment, but long enough to accumulate a meaningful sample of transactions. Most insiders do not transact daily; a 30-day window would often return zero transactions.

---

## 5. Notification Design

### Why Slack and WhatsApp?

**Slack** provides a free Incoming Webhook URL for personal workspaces with no per-message cost. It supports rich message formatting and is already in use by many developers and technical retail investors. Setup is three clicks — create a workspace, create a Webhook URL, paste it into the `.env` file.

**WhatsApp** is the dominant messaging platform for personal communication outside the United States and is growing within it. The CallMeBot gateway provides a free API that delivers WhatsApp messages via a simple GET request with no SDK or SDK account required. For personal use at low alert volumes, it is effectively zero-cost.

**Why not email?**

| Consideration | Slack/WhatsApp | Email |
|---|---|---|
| Setup complexity | Minimal (one URL or phone number) | SMTP credentials, DKIM/SPF, spam handling |
| Delivery speed | Near-instant | Variable; often minutes |
| Spam/deliverability | Not applicable | Significant; home servers often blocked |
| Mobile push | Native | Depends on email client settings |
| Alert fatigue management | Conversation-native threading | Inbox clutter |

For a personal trading tool, the friction of email outweighs its benefits. Users already have Slack and WhatsApp on their phones; those channels deliver push notifications without additional configuration.

### Signal Flip Detection

The pipeline captures `prev_signal` from the MongoDB stock document before running the analysis. After the pipeline completes and the new signal is written, the system compares the two values.

```python
if prev_signal != new_signal:
    fire_signal_flip_notification(ticker, prev_signal, new_signal, composite_score)
```

**Why this prevents notification spam:**
Without flip detection, every hourly pipeline run would generate an alert — turning a useful tool into noise. The majority of pipeline runs will produce the same signal as the previous run. Only genuine transitions carry actionable information. By gating on changes, the system fires at most one notification per transition, regardless of how many pipeline runs confirm that same signal afterward.

---

## 6. Performance Tracking Design

### Why 20 Trading Days?

The system is designed to support swing trade decisions — medium-term directional calls rather than intraday trades or long-term investments. Twenty trading days is approximately one calendar month:

- Short enough to be actionable: if a signal is wrong, 20 days is enough time to know
- Long enough to see meaningful directional movement beyond day-to-day noise
- Standard in academic finance literature for short-to-medium-term return attribution

### Why Settle at 28 Calendar Days?

The settlement job runs daily and looks for signals older than 28 calendar days that have not yet been settled. The original design used 30 calendar days, but was reduced to 28 after identifying that:

- 30 calendar days in a holiday-heavy period (e.g., Thanksgiving week + Christmas week) can occasionally yield only 19 trading days
- 28 calendar days reliably produces ≥ 20 trading days in all observed market calendars

Using a calendar-day threshold rather than trading-day counting eliminates the need for a holiday calendar dependency, simplifying the codebase with negligible accuracy cost.

### Why Idempotent History Write?

The `stocks_signal_history` collection uses an upsert keyed on `(ticker, hour_bucket)` rather than a plain insert. This matters because:

1. **Force refresh:** Users can trigger an on-demand pipeline run for any ticker at any time. If this happens within the same clock-hour as a scheduled run, a naive insert would create two history records for the same ticker in the same hour.
2. **APScheduler retry:** If the scheduler misfires and retries a run, it could double-write.

Without deduplication, performance statistics would count signals twice — inflating the denominator in win rate calculations and skewing the distribution of settled signals. The `hour_bucket` key prevents this entirely: the second write is always an update, not an insert.

### Why Track `was_correct` Per-Signal-Type?

The `was_correct` field is:
- `True` for BUY signals where `return_20d > 0`
- `True` for SELL signals where `return_20d < 0`
- `None` for HOLD signals

HOLD signals are excluded from win rate because HOLD has no directional prediction — "the stock may go up, may go down, or may stay flat" cannot be evaluated as correct or incorrect. Including HOLD in the denominator would suppress win rate in a misleading way. Performance metrics only evaluate the system's directional conviction.

---

## 7. UI/UX Design Decisions

### Why Mobile-First with Bottom Tab Bar?

Retail investors check their portfolio positions throughout the trading day, predominantly on their phones. Mobile-first is not a trend choice — it is where the target user is. A bottom navigation bar:

- Keeps primary navigation reachable with the thumb without repositioning the hand
- Mirrors the navigation pattern users already know from iOS App Store apps and Google Play apps
- Places the four most-used views (Dashboard, Signals, Watchlist, Alerts) in permanent chrome

Desktop gets a top header navigation bar, which is the standard for data-dense web applications where mouse use and wider viewports allow horizontal layouts.

### Why a Score Gauge (Semicircular Meter)?

The composite score is a number in `[0, 100]`. A raw number like "62" carries meaning only if the user remembers the signal thresholds. A semicircular gauge conveys:

- **Direction:** The needle pointing left or right communicates bearish vs bullish before the number is read
- **Magnitude:** Distance from center communicates conviction strength
- **Threshold zones:** The gauge can be colored (red / yellow / green zones) to show where BUY and SELL thresholds fall

Users trained on dashboard instruments (cars, industrial panels) parse a gauge faster than parsing a number in context.

### Why Conviction Badge Separate from Signal?

The signal (`BUY` / `SELL` / `HOLD`) and the conviction (`HIGH` / `MEDIUM` / `LOW`) carry different information:

- Signal is the direction of the recommendation
- Conviction is the confidence in that direction

Combining them into a single label (e.g., "HIGH CONFIDENCE BUY") would obscure cases where conviction is low. Displaying them as separate badges trains users to interpret both dimensions: a `MEDIUM` conviction `BUY` warrants less position sizing than a `HIGH` conviction `BUY`. Over time this prevents the system from being treated as a binary on/off switch.

### Why Light Mode Default?

The tool is used during trading hours — 9:30 AM to 4:00 PM ET — in daylit environments. Light mode text on a light background is more readable in ambient light. Dark mode is more comfortable for late-night chart analysis but is not the primary use case.

Light mode also matches the aesthetic of professional financial terminals (Bloomberg terminal is a notable exception; most web-based tools like TradingView and Robinhood default to light). Professional associations carry credibility weight for a tool designed for informed decision-making.

Users can switch to dark mode via the `ThemeToggle` component; the preference is persisted in `localStorage`.

### Buyer's Guide vs Seller's Guide (Two Contextual Views)

The ticker detail page presents two distinct panels depending on the signal:

- **Entry context (BUY signal):** Highlights technical entry points, support levels, risk/reward ratio relative to price target and stop-loss, catalyst timing
- **Exit context (SELL signal):** Highlights deterioration reasons, resistance levels, what conditions would change the recommendation back to HOLD or BUY

The same underlying data means different things to someone deciding to enter a position versus someone managing an existing one. Forcing the user to interpret all data in a generic view increases cognitive load and the chance of misapplication. Contextual framing reduces the interpretive burden and focuses attention on what matters for the current decision.

---

## 8. Data Quality Signals

### `data_sources` Field on Every Signal Document

Each signal record stored in MongoDB includes a `data_sources` object listing which external systems were successfully queried during that pipeline run:

```json
{
  "data_sources": {
    "yfinance": true,
    "finnhub": false,
    "fred": true,
    "options": true,
    "insider": true
  }
}
```

This provides **provenance** for every signal. A `BUY` signal generated with full data (all `true`) carries more epistemic weight than a `BUY` generated while Finnhub was down and macro defaulted to neutral. Users who understand the system can factor data completeness into their decision.

The `data_sources` field is surfaced in the UI as a collapsible "Data Quality" section on the ticker detail page, with each source shown as a green checkmark or orange warning icon.

### `analyst_used` Flag

Every signal record includes a boolean `analyst_used` field:

- `true`: The signal was produced by the Claude `claude-sonnet-4-6` AI analyst
- `false`: The signal was produced by the rule-based generator in `signal_generator.py`

This distinction matters to users who want to understand the basis of a recommendation:

- A `HIGH` conviction `BUY` from the AI analyst reflects Claude's synthesis of price action, fundamentals, macro context, news sentiment, and alternative data, expressed in natural language reasoning
- A `HIGH` composite score `BUY` from the rule-based system means the weighted formula crossed the 0.65 threshold

Both are valid signals, but they have different interpretive depth. Surfacing which path was used prevents users from treating all signals as equivalent regardless of their origin.

---

## 9. Scoring Weight Rationale

The default weights were chosen to reflect the relative reliability and relevance of each signal category for swing trades (roughly 20-trading-day holding period). They can be adjusted via environment variables without code changes.

| Weight | Default | Rationale |
|---|---|---|
| `WEIGHT_TECHNICAL` | 0.25 | Price action and momentum are the most reliable near-term signals. RSI, MACD, and Bollinger Bands reflect what market participants are actually doing, not what analysts predict they will do. Given highest weight. |
| `WEIGHT_SENTIMENT` | 0.20 | News flow drives short-term price movements with measurable impact. However, sentiment from headline NLP is noisy — a positive headline can accompany a negative earnings miss. 20% keeps it influential without dominating. |
| `WEIGHT_FUNDAMENTAL` | 0.15 | Fundamentals matter most for long-term valuation. At a 20-day swing trade horizon, P/E ratios and revenue growth are slow-moving relative to price action. Lower weight than technical. |
| `WEIGHT_MACRO` | 0.15 | Market environment (VIX, yield curve, inflation) is systemic — it affects all stocks simultaneously. Including it prevents recommending BUY in a high-VIX environment. 15% is sufficient to influence signals without over-indexing on regime. |
| `WEIGHT_CATALYST` | 0.15 | Volume anomalies are a leading indicator: unusual volume often precedes price moves by 1-3 days. At 15%, a strong volume spike meaningfully moves the composite in the bullish direction without single-handedly triggering a signal. |
| `WEIGHT_VOLATILITY` | 0.10 | Volatility primarily informs risk assessment rather than direction. A volatile stock might go up or down; low volatility makes it easier to hold a position without stop-loss triggering. 10% weight; the primary risk signal is the separate `risk_score`. |
| `WEIGHT_ALTERNATIVE_DATA` | 0.10 (modifier) | Applied as `weight × (alt_score - 0.5)`, making it a signed modifier rather than a base weight component. Maximum impact is ±0.05 on the composite, preventing options flow or insider data from dominating. These sources are valuable but have data quality risks (low options volume for small-caps, sparse insider transactions). |

### Why Alternative Data Is a Modifier, Not a Base Weight

If `WEIGHT_ALTERNATIVE_DATA` were treated as a 7th base component (requiring the six primary weights to sum to less than 1.0), a strong put/call ratio signal could contribute as much as the technical score. For small-cap tickers where options volume is thin, the put/call ratio can be meaningless — driven by a handful of contracts rather than institutional positioning. Making it a modifier caps its maximum contribution and ensures it supplements rather than overrides the primary signal.

The modifier formula `weight × (alt_score - 0.5)` centers alternative data at zero contribution when data is neutral or unavailable. Only meaningful deviation from neutral (strong put buying or cluster insider buying) moves the composite, and only modestly.
