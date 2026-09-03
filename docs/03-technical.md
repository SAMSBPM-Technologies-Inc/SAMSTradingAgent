# SAMSTradingAgent — Technical Reference

> Last updated: 2026-08-08

---

## Table of Contents

1. [Technology Stack](#1-technology-stack)
2. [Configuration Reference](#2-configuration-reference)
3. [Technical Indicators Computed](#3-technical-indicators-computed)
4. [Scoring Formula](#4-scoring-formula)
5. [Sub-Score Calculation Methods](#5-sub-score-calculation-methods)
6. [Signal Generation Rules](#6-signal-generation-rules)
7. [Risk Engine](#7-risk-engine)
8. [Alert System](#8-alert-system)
9. [Performance Tracking](#9-performance-tracking)
10. [Frontend Architecture](#10-frontend-architecture)

---

## 1. Technology Stack

### Backend

| Package | Version | Role |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.111 | Async ASGI web framework |
| Motor | 3.4 | Async MongoDB driver |
| APScheduler | 3.10 | Background job scheduling |
| yfinance | 0.2.40 | Market data (prices, fundamentals, options) |
| ta | 0.11 | Technical analysis: RSI, MACD, Bollinger Bands, ATR, Stochastic RSI |
| XGBoost | 2.0.3 | ML scoring model (optional, feature-flagged) |
| FRED API | — | Macroeconomic data from the Federal Reserve |
| Anthropic SDK | ≥0.30 | Claude `claude-sonnet-4-6` via `AsyncAnthropic` |
| httpx | 0.27 | Async HTTP client for external API calls |
| structlog | 24.1 | Structured JSON logging |
| python-jose | — | JWT encoding/decoding |
| passlib + bcrypt | — | Password hashing for user authentication |
| pydantic-settings | 2.2 | Environment variable configuration management |

### Frontend

| Package | Version | Role |
|---|---|---|
| React | 18.3 | UI component framework |
| TypeScript | — | Type safety across the frontend |
| Vite | 5.3 | Build tool and dev server |
| React Router | 6.26 | Client-side routing |
| Tailwind CSS | 3.4 | Utility-first CSS framework |
| Axios | 1.7 | HTTP client for API requests |
| Lucide React | 0.427 | Icon library |
| react-hook-form | — | Form state management |
| zod | — | Schema validation for forms |

### Infrastructure

| Component | Technology | Notes |
|---|---|---|
| Containerization | Docker + Docker Compose | Single `docker-compose.yml` for all services |
| Database | MongoDB 7 | Document store for signals, users, history |
| Ingress | Cloudflare Tunnel | No open inbound ports on the VPS |
| Frontend hosting | Cloudflare Pages | Global CDN, automatic branch deploys |
| CI/CD | GitHub Actions | Build, test, push images on merge to main |
| Backend hosting | Hetzner VPS | Cost-effective European cloud VM |

---

## 2. Configuration Reference

All configuration is loaded from environment variables via `pydantic-settings`. Provide these in a `.env` file at the project root or inject them at container runtime.

### Database

| Variable | Default | Required | Description |
|---|---|---|---|
| `MONGODB_URL` | `mongodb://localhost:27017` | Yes | Full MongoDB connection URI |
| `MONGODB_DB_NAME` | `trading_agent` | No | MongoDB database name |

### Application

| Variable | Default | Required | Description |
|---|---|---|---|
| `APP_ENV` | `development` | No | `development` or `production` |
| `APP_HOST` | `0.0.0.0` | No | Uvicorn bind host |
| `APP_PORT` | `8000` | No | Uvicorn bind port |
| `LOG_LEVEL` | `INFO` | No | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CORS_ORIGINS` | `http://localhost:5173` | No | Comma-separated allowed CORS origins |

### Ingestion

| Variable | Default | Required | Description |
|---|---|---|---|
| `INGESTION_INTERVAL_MINUTES` | `60` | No | How often the pipeline runs per ticker (minutes) |
| `DEFAULT_TICKERS` | `AAPL,MSFT,GOOGL,AMZN,META` | No | Comma-separated list of tickers to ingest if no user watchlists exist |

### Authentication

| Variable | Default | Required | Description |
|---|---|---|---|
| `JWT_SECRET_KEY` | — | Yes | Secret key for signing JWT tokens — must be a long random string |
| `JWT_ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `JWT_EXPIRE_HOURS` | `24` | No | Token lifetime in hours |

### External API Keys

| Variable | Default | Required | Description |
|---|---|---|---|
| `FINNHUB_API_KEY` | — | No | Finnhub API key for news headlines; degrades gracefully to neutral if absent |
| `FRED_API_KEY` | — | No | FRED (Federal Reserve) API key for macro data; degrades gracefully if absent |
| `ANTHROPIC_API_KEY` | — | No | Anthropic API key; required only if `ENABLE_AI_ANALYST=true` |

### Feature Flags

| Variable | Default | Required | Description |
|---|---|---|---|
| `ENABLE_ML_MODEL` | `false` | No | Enable XGBoost scoring path instead of weighted fallback |
| `ENABLE_BACKTESTING` | `false` | No | Enable backtesting endpoints |
| `ENABLE_AI_ANALYST` | `false` | No | Enable Claude-powered AI analyst narrative generation |

### Scoring Weights

All weight variables are floats. `WEIGHT_TECHNICAL` through `WEIGHT_CATALYST` must sum to exactly `1.0`. `WEIGHT_ALTERNATIVE_DATA` is an additive modifier and is not part of that sum constraint.

| Variable | Default | Description |
|---|---|---|
| `WEIGHT_TECHNICAL` | `0.25` | Weight for technical indicator sub-score |
| `WEIGHT_FUNDAMENTAL` | `0.15` | Weight for fundamental analysis sub-score |
| `WEIGHT_SENTIMENT` | `0.20` | Weight for news sentiment sub-score |
| `WEIGHT_MACRO` | `0.15` | Weight for macroeconomic environment sub-score |
| `WEIGHT_VOLATILITY` | `0.10` | Weight for volatility sub-score |
| `WEIGHT_CATALYST` | `0.15` | Weight for catalyst (volume anomaly) sub-score |
| `WEIGHT_ALTERNATIVE_DATA` | `0.10` | Modifier coefficient for alternative data; applied as `weight × (alt_score - 0.5)` |

> **Constraint:** `WEIGHT_TECHNICAL + WEIGHT_FUNDAMENTAL + WEIGHT_SENTIMENT + WEIGHT_MACRO + WEIGHT_VOLATILITY + WEIGHT_CATALYST` must equal `1.0`. The server will log a warning and may reject startup if this constraint is violated.

---

## 3. Technical Indicators Computed

All indicators are computed on daily OHLCV data fetched from Yahoo Finance via `yfinance`. The `ta` library handles all rolling calculations.

| Indicator | Library | Window / Parameters | Notes |
|---|---|---|---|
| RSI | `ta` | 14 periods | Momentum oscillator. Overbought >70, oversold <30 |
| MACD | `ta` | 12 / 26 / 9 (fast/slow/signal) | Trend indicator. Bullish when MACD line crosses above signal line |
| Bollinger Bands | `ta` | 20 periods, 2σ | Price position expressed as `bb_pct`: 0.0 = at lower band, 1.0 = at upper band |
| Stochastic RSI | `ta` | 14 / 3 / 3 (RSI/K/D) | Momentum oscillator in [0, 1] range. Low values = oversold (bullish), high = overbought |
| ATR | `ta` | 14 periods | Average True Range. Used in position sizing suggestion calculations, not in composite score |
| MA-20 | `ta` | 20-day simple moving average | Short-term trend benchmark |
| MA-50 | `ta` | 50-day simple moving average | Medium-term trend benchmark |
| Volume Anomaly | Computed | Latest volume / 20-day avg volume | Ratio >2 signals unusual activity; used in catalyst score and alternative data |
| 20-day Annualised Volatility | Computed | 20 trading days | `std(log_returns) × √252`. Used in volatility score and risk engine |

---

## 4. Scoring Formula

The pipeline produces a `composite_score` in the range [0, 1]. Two paths are available, controlled by the `ENABLE_ML_MODEL` feature flag.

### 4.1 XGBoost Path (`ENABLE_ML_MODEL=true`)

When the ML model is enabled, composite scoring is handled by a trained XGBoost regressor that predicts 20-day forward returns.

**Feature vector (14 features):**

| # | Feature | Fallback if missing |
|---|---|---|
| 1 | `rsi` | `50.0` |
| 2 | `macd` | `0.0` |
| 3 | `macd_signal` | `0.0` |
| 4 | `bb_pct` | `0.5` |
| 5 | `stoch_rsi` | `0.5` |
| 6 | `volume_ratio` | `1.0` |
| 7 | `volatility_20d` | `0.2` |
| 8 | `ma_20` | current price |
| 9 | `ma_50` | current price |
| 10 | `vix` | `20.0` |
| 11 | `yield_curve_spread` | `0.0` |
| 12 | `cpi_yoy` | `3.0` |
| 13 | `fundamental_score` | `0.5` (frozen — see note) |
| 14 | `sentiment_score` | `0.5` (frozen — see note) |

**Training details:**
- Training corpus: 30 large-cap tickers, 3 years of daily data
- Labels: 20-day forward returns, clipped to `[-0.5, 0.5]` to reduce the influence of extreme outliers
- Model output is a predicted return, which is then linearly scaled to `[0, 1]` for the composite score
- Hyperparameters: `n_estimators=500`, `max_depth=4`, `learning_rate=0.05`, `reg_alpha=0.1` (L1), `reg_lambda=1.0` (L2)

> **Note on frozen scores:** `fundamental_score` and `sentiment_score` are frozen at `0.5` during inference. Historical Yahoo Finance snapshots used during training did not include historical fundamental ratios at the signal date. Using current fundamentals for historical labels would introduce look-ahead bias. Freezing at `0.5` (neutral) matches the distribution the model was trained on.

### 4.2 Weighted Fallback Path (default, `ENABLE_ML_MODEL=false`)

```
composite = weight_technical    × tech_score
          + weight_fundamental  × fund_score
          + weight_sentiment    × sent_score
          + weight_macro        × macro_score
          + weight_volatility   × vol_score
          + weight_catalyst     × catalyst_score
          + weight_alternative  × (alt_score - 0.5)   # additive modifier, not a primary weight
```

All sub-scores are in `[0, 1]` where `0.5` is neutral. The alternative data term is centered at `0.5` so it acts as a signed modifier: values above `0.5` nudge composite up, values below nudge it down.

**Default weights:**

| Component | Default Weight |
|---|---|
| Technical | 0.25 |
| Fundamental | 0.15 |
| Sentiment | 0.20 |
| Macro | 0.15 |
| Volatility | 0.10 |
| Catalyst | 0.15 |
| Alternative Data (modifier) | 0.10 |

---

## 5. Sub-Score Calculation Methods

All sub-scores are normalized to `[0, 1]`. A score of `0.5` indicates neutral or missing data. A score above `0.5` is bullish; below `0.5` is bearish.

### 5.1 Technical Score

Composed of five weighted components:

| Component | Weight | Bullish Condition | Bearish Condition | Notes |
|---|---|---|---|---|
| RSI | 25% | RSI < 30 → `1.0` | RSI > 70 → `0.0` | Linear interpolation between 30–70 |
| MACD Crossover | 25% | MACD line > signal line → `1.0` | MACD line < signal line → `0.0` | Binary |
| Bollinger Band Position | 20% | `bb_pct` near 0 (lower band) → `1.0` | `bb_pct` near 1 (upper band) → `0.0` | `score = 1 - bb_pct` |
| Stochastic RSI | 15% | Low stoch_rsi (oversold) → `1.0` | High stoch_rsi (overbought) → `0.0` | `score = 1 - stoch_rsi` |
| MA Cross | 15% | MA-20 > MA-50 → `1.0` | MA-20 < MA-50 → `0.0` | Binary; signals short-term uptrend |

**Formula:**
```
tech_score = 0.25 × rsi_score
           + 0.25 × macd_score
           + 0.20 × bb_score
           + 0.15 × stoch_score
           + 0.15 × ma_cross_score
```

### 5.2 Fundamental Score

Composed of five weighted components sourced from `yfinance.Ticker.info`:

| Component | Weight | Bullish Condition | Bearish Condition | Notes |
|---|---|---|---|---|
| Analyst Recommendation | 30% | `strong_buy` → `1.0`, `buy` → `0.85` | `sell` → `0.1`, `strong_sell` → `0.0` | `hold` → `0.5` |
| Revenue Growth YoY | 25% | > 30% → `1.0` | < -20% → `0.0` | Linear interpolation between thresholds |
| P/E Ratio | 20% | ≤ 15 → `1.0` | ≥ 60 → `0.0` | Linear interpolation; negative P/E maps to `0.2` |
| Free Cash Flow | 15% | Positive FCF → `1.0` | Negative FCF → `0.0` | Binary; missing → `0.5` |
| Debt/Equity Ratio | 10% | Low D/E (≤ 0.3) → `1.0` | High D/E (≥ 3.0) → `0.0` | Linear interpolation |

**Formula:**
```
fund_score = 0.30 × analyst_score
           + 0.25 × revenue_growth_score
           + 0.20 × pe_score
           + 0.15 × fcf_score
           + 0.10 × debt_equity_score
```

### 5.3 Macro Score

Composed of three components sourced from FRED and `yfinance` (VIX):

| Component | Weight | Bullish Condition | Bearish Condition | Notes |
|---|---|---|---|---|
| VIX | 35% | VIX ≤ 15 → `1.0` (calm market) | VIX ≥ 35 → `0.0` (fear) | Linear interpolation between 15–35 |
| Yield Curve Spread (10Y–2Y) | 35% | Positive spread → `1.0` (healthy) | Inverted (≤ 0) → `0.0` | Linear; inversion signals recession risk |
| CPI YoY Inflation | 30% | ~2% → `1.0` (Fed target) | > 6% → `0.0` (hot inflation) | Peak at 2%; degrades toward 0 and 6% |

**Formula:**
```
macro_score = 0.35 × vix_score
            + 0.35 × yield_curve_score
            + 0.30 × cpi_score
```

Macro data is fetched from FRED at ingestion time and cached in MongoDB. If FRED is unavailable, all macro components default to `0.5`.

### 5.4 Sentiment Score

- Source: Finnhub news headlines API for the ticker, last 7 days
- Scoring: VADER (`vaderSentiment`) compound score per headline, averaged across all fetched headlines
- Normalization: VADER compound is in `[-1, 1]`; mapped to `[0, 1]` via `(compound + 1) / 2`
- Fallback: `0.5` (neutral) if Finnhub API is unavailable or returns no headlines

### 5.5 Volatility Score

- Input: 20-day annualised volatility (`volatility_20d`)
- Interpretation: lower volatility is less risky — higher score
- Formula: `vol_score = max(0, 1 - (volatility_20d / 0.6))` — volatility at 60% annualised maps to `0.0`
- A stock with 20% annualised volatility scores approximately `0.67`
- Fallback: `0.5` if insufficient price history

### 5.6 Catalyst Score

- Input: `volume_ratio` = latest_volume / 20-day_average_volume
- Represents unusual volume as a potential upcoming catalyst signal
- Formula: `catalyst_score = min(1.0, max(0.0, (volume_ratio - 1) / 2))`
  - Normal volume (`ratio = 1.0`) → `0.0` catalyst score
  - 3× average volume (`ratio = 3.0`) → `1.0` catalyst score
- Fallback: `0.0` (no anomaly) if volume data is unavailable

### 5.7 Alternative Data Score

Composed of two equal components:

| Component | Weight | Bullish Condition | Bearish Condition | Source |
|---|---|---|---|---|
| Options Put/Call Ratio | 50% | P/C ≤ 0.5 → `1.0` (calls dominating) | P/C ≥ 1.5 → `0.0` (puts dominating) | `yfinance` options chain, nearest expiry |
| Insider Buy Ratio | 50% | High buy ratio → `1.0` | Low / no buys → `0.0` | `yfinance` insider transactions, 90-day window |

**Formula:**
```
alt_score = 0.50 × pc_ratio_score + 0.50 × insider_score

insider_score = insider_buys / (insider_buys + insider_sells)
# if no transactions in 90 days → 0.5 (neutral)
```

The alternative data score is applied as an additive modifier to the composite, not a multiplicative weight component:
```
composite += weight_alternative × (alt_score - 0.5)
```

---

## 6. Signal Generation Rules

### 6.1 Rule-Based Generator (`signal_generator.py`)

The rule-based generator is the default path when `ENABLE_AI_ANALYST=false`.

```python
if composite_score > 0.65 and risk_score < 6.5:
    signal = "BUY"
elif composite_score < 0.35 or (composite_score < 0.45 and risk_score > 7.0):
    signal = "SELL"
else:
    signal = "HOLD"
```

- BUY requires both a high composite score AND a low-to-moderate risk score. High risk overrides a BUY to HOLD.
- SELL fires on either a clearly bearish composite score OR a moderately weak score combined with very high risk.
- HOLD is the default for all ambiguous conditions.

### 6.2 AI Analyst (`analyst.py`)

When `ENABLE_AI_ANALYST=true`, Claude `claude-sonnet-4-6` generates a full research note via `AsyncAnthropic`.

**Context provided to Claude:**
- Current price, daily change, volume
- All computed technical indicators (RSI, MACD, BB, Stoch RSI, ATR, MAs)
- All sub-scores and the composite score
- Fundamental data (P/E, revenue growth, FCF, analyst consensus, D/E)
- Macro environment (VIX, yield curve, CPI)
- Alternative data (P/C ratio, insider buy ratio, short interest)
- Recent news headlines (from Finnhub, last 7 days)
- Risk assessment from the risk engine

**Structured JSON response schema:**

```json
{
  "signal": "BUY | SELL | HOLD",
  "conviction": "HIGH | MEDIUM | LOW",
  "price_target": 195.00,
  "stop_loss": 165.00,
  "time_horizon": "1-2 weeks | 2-6 weeks | 1-3 months | 3-6 months",
  "thesis": "Primary rationale in 2-3 sentences",
  "bull_case": "What needs to go right",
  "bear_case": "What could go wrong",
  "key_risks": ["risk 1", "risk 2"],
  "catalysts": ["catalyst 1", "catalyst 2"],
  "analyst_note": "Extended professional commentary"
}
```

**Conviction to confidence mapping:**

| Conviction | Confidence Value |
|---|---|
| `HIGH` | `0.85` |
| `MEDIUM` | `0.55` |
| `LOW` | `0.25` |

---

## 7. Alpha Radar

Alpha Radar is a dedicated scan page that surfaces actionable entry and exit setups from the user's watchlist without triggering a new pipeline run. It reads directly from the latest `stocks_features` documents in MongoDB.

### 7.1 Backend — `GET /signals/dip-buy`

Implemented in `backend/app/routes/signals.py`. Fetches feature docs for all watched tickers in one MongoDB query (projection to 8 fields, index-covered), then applies thresholds in Python.

**Entry thresholds (AND logic — all three must hold):**

| Constant | Value | Indicator |
|---|---|---|
| `_ENTRY_RSI_MAX` | 45.0 | RSI-14 |
| `_ENTRY_STOCH_MAX` | 0.20 | Stochastic RSI (0–1) |
| `_ENTRY_BB_MAX` | 0.35 | Bollinger Band % position |

**Exit-alert thresholds (OR logic — either fires):**

| Constant | Value | Indicator |
|---|---|---|
| `_EXIT_RSI_MIN` | 70.0 | RSI-14 |
| `_EXIT_BB_MIN` | 0.90 | Bollinger Band % position |

Entry results are sorted ascending by `stoch_rsi` (most oversold first). Exit results are sorted descending by `rsi_14` (most overbought first). Both lists are returned in the single `DipBuyScanResponse`.

### 7.2 Frontend — `AlphaRadarPage.tsx`

- Calls `radarApi.scan()` → `GET /signals/dip-buy` on mount and on user-triggered "Scan Now".
- Renders a stats strip: tickers scanned / entry setups / exit alerts.
- **EntryCard** (green left border): shows RSI-14, Stochastic RSI, and BB % as colored progress bars. Blue bar = very oversold (target zone). Clicking navigates to the full ticker analysis page.
- **ExitAlertCard** (amber left border): same indicator bars. Amber bar highlights overbought zone.
- **IndicatorBar** component: color-coded — `danger="high"` (overbought risk) colors red above 75%, amber 50–75%, green below 50%. `danger="low"` (oversold opportunity) colors blue below 25%, amber 25–50%, green above 50%.
- **AddTickerForm**: inline ticker search with debounced autocomplete (300ms) via `analyzeApi.search()`. Adds the ticker to the watchlist and displays a 30-second delay message before suggesting a re-scan.
- Collapsible **"How signals are detected"** section lists the exact thresholds for user transparency.

### 7.3 Data Flow

```
User clicks "Scan Now"
  → radarApi.scan() → GET /signals/dip-buy
  → signals.py reads stocks_features for all watched tickers
  → applies RSI/Stoch/BB thresholds in Python
  → returns entry_candidates[] + exit_alerts[] + scanned count
  → AlphaRadarPage renders EntryCard / ExitAlertCard grids
```

No new analysis is run during the scan. If the user wants fresh data for a specific ticker, they should visit that ticker's analysis page and trigger a force refresh.

---

## 8. Risk Engine

The risk engine (`risk_engine.py`) produces a `risk_score` in `[0, 10]` that is used both for display and as a gate on BUY signals.

**Inputs:**

| Input | Source |
|---|---|
| `rsi` | Technical indicators |
| `volatility_20d` | Computed from price history |
| `vix` | FRED / yfinance |
| `bb_pct` | Bollinger Band position |
| `macd_bullish` | MACD line vs signal line (bool) |

**Risk score composition:**

| Component | Contribution Logic |
|---|---|
| Volatility | `volatility_20d / 0.5 × 3.0` — high volatility contributes up to 3 points |
| RSI extremes | RSI > 75 → +2.0; RSI < 25 → +1.0 (oversold is a milder risk signal) |
| VIX | VIX > 30 → +2.5; VIX > 20 → +1.5; VIX ≤ 20 → +0.5 |
| Technical momentum | MACD bearish → +1.0; BB in upper quartile (`bb_pct > 0.75`) → +0.5 |

All contributions are summed and clamped to `[0, 10]`.

**Risk level bands:**

| Band | Score Range | Effect |
|---|---|---|
| `LOW` | 0.0 – 3.5 | No signal override |
| `MEDIUM` | 3.5 – 6.5 | Allowed for BUY |
| `HIGH` | 6.5 – 10.0 | BUY signal overridden to HOLD |

A `HIGH` risk score does not gate SELL signals — if deterioration has triggered a sell, the risk context is already reflected in that signal.

---

## 8. Alert System

### 8.1 Notification Channels

| Channel | Mechanism | Configuration |
|---|---|---|
| Slack | Incoming Webhook POST | `SLACK_WEBHOOK_URL` env var; message sent to the configured channel |
| WhatsApp | CallMeBot GET API | `WHATSAPP_PHONE` and `CALLMEBOT_API_KEY` env vars |

Both channels are optional. A user can configure either, both, or neither. Alerts are sent only on configured channels.

### 8.2 Trigger Conditions

Alerts fire when either of the following is true:

1. **Signal flip detected:** The signal for a ticker changed since the previous pipeline run (e.g., `HOLD` → `BUY`, `BUY` → `SELL`). This requires `notify_on_signal_flip=true` in user preferences.
2. **High conviction AI signal:** The AI analyst returned `conviction=HIGH`, regardless of whether the signal flipped. This requires `notify_on_high_conviction=true` in user preferences.

The previous signal is captured from MongoDB before each pipeline run and compared after. If no change occurred, no notification is sent.

### 8.3 Daily Digest

- Schedule: `9:00 AM ET` every market day (APScheduler cron job)
- Content: All tracked tickers sorted by composite score descending, with signal, conviction, and score
- Delivery: Sent only to users with `daily_digest=true` in preferences AND at least one configured notification channel

### 8.4 Test Endpoint

```
POST /alerts/test
```

Sends a sample `HOLD → BUY` signal flip notification for the synthetic ticker `TEST` to validate that Slack and/or WhatsApp are correctly configured. Does not modify any database records.

### 8.5 Per-User Preference Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `notify_on_signal_flip` | bool | `true` | Fire notification when signal changes |
| `notify_on_high_conviction` | bool | `true` | Fire notification on HIGH conviction AI signals |
| `daily_digest` | bool | `false` | Receive 9 AM ET daily summary |

---

## 9. Performance Tracking

### 9.1 Signal History Write

Every pipeline run upserts a record to the `stocks_signal_history` collection, keyed on `(ticker, hour_bucket)`:

```python
hour_bucket = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
```

This ensures idempotency: multiple pipeline runs within the same clock-hour produce exactly one history record. This matters because force-refresh can trigger a second run in the same hour — without deduplication, performance statistics would count duplicates.

**Record fields written at signal time:**
- `ticker`, `hour_bucket`, `signal`, `composite_score`, `entry_price`, `created_at`
- `return_20d`: `null` at creation; populated by the settlement job
- `was_correct`: `null` at creation; populated at settlement

### 9.2 Settlement Job

The `perf_tracker` job runs daily at `06:00 UTC` (APScheduler).

**Settlement logic:**

1. Query `stocks_signal_history` for records where:
   - `return_20d` is `null` (not yet settled)
   - `created_at` is ≥ 28 calendar days ago
2. For each unsettled record, fetch the current price from Yahoo Finance (`yfinance.Ticker.history`)
3. Calculate: `return_20d = (current_price - entry_price) / entry_price`
4. Determine correctness:
   - `BUY` signal: `was_correct = True` if `return_20d > 0`
   - `SELL` signal: `was_correct = True` if `return_20d < 0`
   - `HOLD` signal: `was_correct = None` (not directional; excluded from win rate)
5. Upsert the record with `return_20d` and `was_correct`

> **Why 28 calendar days instead of 20 trading days?** 28 calendar days reliably covers ≥ 20 trading days even in holiday-heavy periods. Using strict 20-trading-day logic would require a calendar of market holidays and adds complexity without meaningfully changing the result.

### 9.3 Win Rate Calculation

```
win_rate = count(was_correct == True) / count(was_correct is not None)
```

HOLD signals are excluded from the denominator. Win rate is computed per signal type (BUY-only, SELL-only, combined) for the `/performance` API endpoint.

---

## 10. Frontend Architecture

### 10.1 State Management

The frontend uses React Context for global state — no Redux or Zustand dependency.

| Context | Provided State | Key Methods |
|---|---|---|
| `AuthContext` | `user`, `token`, `isAuthenticated` | `login(email, password)`, `logout()`, `refreshProfile()` |
| `ThemeContext` | `theme` (`light` \| `dark`) | `toggleTheme()` — persists preference to `localStorage` |

### 10.2 API Layer

`src/api/client.ts` exports a configured Axios instance:

- **Base URL:** Set from `VITE_API_URL` environment variable at build time
- **Bearer token interceptor:** Reads `token` from `AuthContext` and injects `Authorization: Bearer <token>` on every outgoing request
- **401 redirect interceptor:** On any 401 response, clears auth state and redirects to `/login`. The interceptor skips `/auth/` routes to avoid redirect loops on login failures.

### 10.3 Routing

React Router 6 with a `ProtectedRoute` wrapper component:

```
/login          → LoginPage (public)
/register       → RegisterPage (public)
/               → Dashboard (protected)
/signals        → SignalsPage (protected)
/watchlist      → WatchlistPage (protected)
/performance    → PerformancePage (protected)
/alerts         → AlertsPage (protected)
/settings       → SettingsPage (protected)
/ticker/:symbol → TickerDetailPage (protected)
```

`ProtectedRoute` checks `AuthContext.isAuthenticated`. If false, it redirects to `/login` with the originally requested path in `state` for post-login redirect.

### 10.4 Responsive Layout

The `Layout` component renders differently based on viewport:

- **Desktop (md+):** Top header navigation bar with horizontal links
- **Mobile (<md):** Bottom tab bar with icon-only navigation, thumb-friendly tap targets

### 10.5 Design Token System

Colors are defined as CSS custom properties in `index.css` and switched by toggling a `data-theme` attribute on `<html>`:

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--color-fg` | `#111827` | `#f9fafb` | Primary text |
| `--color-surface` | `#ffffff` | `#1f2937` | Card backgrounds |
| `--color-surface-alt` | `#f3f4f6` | `#111827` | Alternate surface |
| `--color-border` | `#e5e7eb` | `#374151` | Borders and dividers |
| `--color-accent` | `#2563eb` | `#3b82f6` | Primary action color |

Tailwind classes use `text-[var(--color-fg)]` syntax to reference these tokens, making all components automatically respond to theme switches.

### 10.6 Key Shared Components

| Component | Props | Description |
|---|---|---|
| `SignalBadge` | `signal: "BUY" \| "SELL" \| "HOLD"` | Colored pill badge — green/BUY, red/SELL, gray/HOLD |
| `ConvictionBadge` | `conviction: "HIGH" \| "MEDIUM" \| "LOW"` | Confidence badge with intensity coloring |
| `LoadingSpinner` | `size?`, `className?` | Centered spinner with Tailwind animation |
| `ThemeToggle` | — | Sun/moon icon button wired to `ThemeContext.toggleTheme` |
| `ScoreGauge` | `score: number` (0–100) | Semicircular SVG meter for composite score visualization |
