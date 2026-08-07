# TradingAgent — Real Data & AI Analyst Plan

## What's Real vs Fake Today

| Component | Current State | Gap |
|---|---|---|
| Price data | Yahoo Finance | Good enough |
| Sentiment | Mock (seeded random) | Needs real news |
| Fundamentals | None | Missing entirely |
| Macro/sector | None | Missing entirely |
| Scoring | Weighted formula | No real intelligence |
| Signal output | Rule-based thresholds | Not analyst-quality |

---

## Phase 1 — Real Data Ingestion (Week 1–2)

### Price & Market Data
- Keep Yahoo Finance for OHLCV
- Add Polygon.io (free tier) for intraday + options flow
- Add FRED API (free) for macro: interest rates, CPI, unemployment

### News & Sentiment — replace mock entirely
- Finnhub (free tier): real-time news per ticker + built-in sentiment score
- NewsAPI (free tier): broader news search, run through your own NLP
- Reddit (pushshift or official API): WSB + investing subreddits for retail sentiment
- SEC EDGAR (free): 10-K/10-Q filings, earnings call transcripts

### Fundamentals — currently zero
- Use yfinance `.info`, `.financials`, `.earnings`
- Pull: P/E, P/B, EPS growth, revenue trend, debt/equity, free cash flow, earnings surprise history

### Alternative Signals
- Google Trends API (free): search interest in ticker/company
- Insider transactions via SEC Form 4 (EDGAR, free)
- Short interest via Finra (free, delayed)

---

## Phase 2 — Feature Enrichment (Week 2–3)

### Expand Technical Indicators
- Add: MACD, Bollinger Bands, ATR, OBV, VWAP, Stochastic RSI
- Add: Support/resistance levels (pivot points)
- Add: Volume anomaly detection

### Fundamental Score
- Build a normalized fundamental score (0–1) alongside technical score
- Piotroski F-Score or similar for financial health
- Revenue/earnings growth trend score

### Macro Score
- Rate environment (rising rates → bearish for growth stocks)
- Sector rotation signals
- VIX level as market fear input

### Multi-timeframe
- Currently daily only → add weekly trend for context, intraday for entry timing

---

## Phase 3 — AI Analyst Layer (Week 3–4)

Replace rule-based signals with an LLM that reasons like a senior analyst.

### Architecture
```
All data sources → Structured context builder → Claude/GPT-4 prompt → Structured JSON output → Signal + narrative report
```

### AI Prompt Inputs
- Price action
- Technical readings
- Fundamentals
- News + sentiment
- Macro context
- Earnings proximity
- Insider activity
- Short interest

### AI Structured Output
```json
{
  "signal": "BUY|SELL|HOLD",
  "conviction": "HIGH|MEDIUM|LOW",
  "price_target": 340.00,
  "stop_loss": 295.00,
  "time_horizon": "2-4 weeks",
  "thesis": "...",
  "bull_case": "...",
  "bear_case": "...",
  "key_risks": ["..."],
  "catalysts": ["..."],
  "analyst_note": "Full paragraph like a real research note"
}
```

---

## Phase 4 — Scoring Overhaul (Week 4)

Replace `0.4 × technical + 0.3 × sentiment + 0.3 × volatility` with:

- **Layer 1:** Technical score (RSI, MACD, MA, BB, volume)
- **Layer 2:** Fundamental score (valuation, growth, health)
- **Layer 3:** Sentiment score (news NLP, social, analyst ratings)
- **Layer 4:** Macro score (rates, sector, VIX)
- **Layer 5:** Catalyst score (earnings proximity, insider buys, unusual options)

→ Feed all 5 into XGBoost for numeric score
→ Feed all 5 to Claude for narrative and final conviction
→ Do both — XGBoost for the score, LLM for the thesis

---

## Phase 5 — Infrastructure (parallel)

### Data Freshness
- Market hours scheduler (9:30–16:00 ET, weekdays only)
- Pre-market news sweep at 8:00 ET
- Post-earnings immediate re-analysis trigger
- Earnings calendar integration

### Storage
- Time-series history of signals per ticker (currently overwrites)
- Store raw news articles for audit trail
- Track signal accuracy over time

### New API Endpoints
- `GET /report/{ticker}` — full analyst report (PDF-ready)
- `GET /signals/summary` — portfolio-level view
- `GET /watchlist` — ranked by conviction
- `POST /ticker` — add a new ticker to watch
- `GET /performance` — historical signal accuracy

---

## Recommended Build Order

1. Finnhub news → real sentiment (replaces #1 fake component)
2. yfinance fundamentals → fundamental score (adds missing dimension)
3. FRED macro data → macro score (adds market context)
4. Claude API analyst layer (transforms output quality)
5. XGBoost trained model (adds ML scoring)
6. Full scheduler + history tracking (production-readiness)

---

## Phase 6 — Correctness & Reliability Gap Fixes ✅ DONE (2026-08-07)

**Commit:** `acfc2cb` — 14 gaps fixed across 9 files.

- VIX propagation bug fixed (was always 20.0 at XGBoost inference)
- Analyst service converted to async Claude client (no longer blocks event loop)
- Scheduler sync `requests` → async `httpx`; shutdown `wait=True`
- Settlement window corrected (30→28 calendar days ≈ 20 trading days)
- MongoDB indexes added on startup (ticker, generated_at, hour_bucket, etc.)
- Catalyst score aligned with training schema (volume-only)
- fundamental_score and sentiment_score frozen at 0.5 in XGBoost path (matches training)
- `data_sources` + `analyst_used` provenance fields added to signal history records
- Idempotent history upsert keyed on (ticker, hour_bucket)
- Config weight validator added (fails fast on bad weights)
- OBV dead code removed; fetch limits raised 500→2000

---

## Phase 7 — Frontend Dashboard

React/Next.js UI consuming the existing API.

- Watchlist table with color-coded BUY/SELL/HOLD signal badges
- Signal cards with conviction level, price target, stop loss, thesis
- Performance charts (win rate, avg 20d return by signal type)
- Real-time polling or WebSocket updates

---

## Phase 8 — Backtesting Engine

Replay `stocks_signal_history` against actual price data to measure portfolio-level P&L.

- Compute returns if every signal was followed at generation time
- Metrics: Sharpe ratio, max drawdown, hit rate by signal type and ticker
- New endpoint: `GET /backtest?from=2025-01-01`

---

## Phase 9 — Alerts & Notifications

Push alerts when notable signals emerge — no polling required.

- Slack/email webhook on HIGH conviction BUY/SELL signals
- Daily digest of watchlist conviction changes
- Triggered from the scheduler after each pipeline run

---

## Phase 10 — Paper Trading Integration

Connect Alpaca paper-trading API to auto-execute signals.

- Execute BUY/SELL on HIGH conviction signals within position size limits
- Track paper P&L separately from signal accuracy stats
- New endpoint: `GET /paper-portfolio` for open positions and returns

---

## Phase 11 — Model Auto-Retraining Pipeline

Close the feedback loop using the system's own signal history as training data.

- Once `stocks_signal_history` has enough settled records (30+ days), retrain XGBoost on them weekly
- Compare new model vs current model on held-out recent records before swapping
- Scheduler job: retrain every Sunday, auto-deploy if test MAE improves
