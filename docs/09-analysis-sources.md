# Analysis Sources & Methodology

This document describes every data source that feeds into a SAMSTradingAgent signal, how each is scored, known limitations, and the roadmap to improve reliability.

---

## Current Data Sources (Live)

### 1. Price & Market Data
- **Source:** Yahoo Finance v8 Chart API (`query1.finance.yahoo.com`)
- **Data fetched:** 90 days of daily OHLCV (open, high, low, close, volume), current price, previous-close day change %
- **Used for:** All technical indicators — RSI-14, MACD, Bollinger Bands, Stochastic RSI, MA-20/50 cross, ATR, volume anomaly

### 2. Fundamentals
- **Source:** yfinance Python library (Yahoo Finance `.info`, `.financials`, `.earnings`)
- **Data fetched:** P/E, P/B, P/S, PEG ratios; market cap; EV; EPS; revenue growth YoY; earnings growth YoY; debt/equity; free cash flow; profit margin; ROE; 52-week high/low; analyst target price; analyst recommendation + count; sector; industry; next earnings date
- **Used for:** Fundamental sub-score (0–1), displayed stat cells on ticker page

### 3. News & Sentiment
- **Source:** Finnhub API (`/company-news`) — last 7 days of company headlines
- **Scoring:** VADER (Valence Aware Dictionary and sEntiment Reasoner) applied locally to each headline
- **Output:** Sentiment score (0–1), bullish %, bearish %, article count, buzz metric (capped at 1.0)
- **Used for:** Sentiment sub-score, news headlines fed into Claude analyst prompt

### 4. Macro Environment
- **Source:** FRED (Federal Reserve Economic Data) API
- **Series fetched:**
  - `FEDFUNDS` — Federal Funds Rate
  - `DGS10` / `DGS2` — 10-year and 2-year Treasury yields (spread = recession signal)
  - `CPIAUCSL` — CPI (YoY inflation computed from 13 observations)
  - `UNRATE` — Unemployment Rate
  - `VIXCLS` — CBOE Volatility Index
- **Used for:** Macro sub-score (VIX 35%, yield curve 35%, CPI 30%); VIX also fed into ML model features

### 5. Options Flow
- **Source:** yfinance option chain for nearest expiry
- **Data fetched:** Put volume + call volume across the full chain → put/call ratio
- **Sentiment mapping:** ≤0.5 = BULLISH, 0.5–0.7 = MILDLY_BULLISH, 0.7–1.0 = NEUTRAL, 1.0–1.5 = MILDLY_BEARISH, >1.5 = BEARISH
- **Used for:** 50% of the alternative-data modifier score

### 6. Short Interest
- **Source:** yfinance `.info` fields `shortRatio` (days-to-cover) and `shortPercentOfFloat`
- **Squeeze risk logic:** HIGH if float % > 20% and days-to-cover > 5; MEDIUM if float % > 10% and days-to-cover > 3
- **Used for:** Display only (shown in Alternative Data section); not currently scored due to directional ambiguity

### 7. Insider Activity (Form 4)
- **Source:** yfinance `insider_transactions` (SEC Form 4 filings)
- **Data fetched:** Buy count and sell count over trailing 90 days; most recent transactions with insider name, type, shares, value
- **Used for:** 50% of the alternative-data modifier score (buy ratio = buys / total transactions)

### 8. AI Analyst
- **Model:** Claude Sonnet 4.6 (Anthropic API)
- **Enabled when:** `ENABLE_AI_ANALYST=true` and `ANTHROPIC_API_KEY` set
- **Inputs:** Full context including all technical indicators, all sub-scores, fundamentals, macro data, last 8 Finnhub headlines, options sentiment, short interest, insider counts, risk assessment
- **Outputs:** Signal (BUY/SELL/HOLD), conviction (HIGH/MEDIUM/LOW), price target, stop loss, time horizon, investment thesis, bull case, bear case, key risks, catalysts, analyst note
- **Fallback:** If API call fails or key is absent, rule-based signal_generator is used

---

## Composite Scoring

### Sub-scores (each 0–1)

| Sub-score | Weight (default) | Key inputs |
|---|---|---|
| Technical | configurable | RSI, MACD, Bollinger Bands, Stoch RSI, MA cross |
| Fundamental | configurable | Analyst rec (30%), revenue growth (25%), P/E (20%), FCF (15%), debt (10%) |
| Sentiment | configurable | VADER score on Finnhub headlines |
| Macro | configurable | VIX (35%), yield curve (35%), CPI (30%) |
| Volatility | configurable | Inverse of 20-day annualized vol |
| Catalyst | configurable | Volume anomaly vs 20-day average |
| Alternative data | modifier (±) | Options P/C (50%) + insider buy ratio (50%) |

Alternative data acts as a ±modifier: 0.5 = neutral, >0.5 = upward nudge, <0.5 = downward drag.

### Signal thresholds (rule-based mode)
```
score > 0.70 AND risk_score < 6.0  →  BUY
score < 0.30                        →  SELL
otherwise                           →  HOLD
```

### ML mode (XGBoost)
When `ENABLE_ML_MODEL=true` and a model file is present, a 14-feature XGBoost model replaces the weighted formula. **Current caveat:** fundamental and sentiment features were frozen at 0.5 during training — the model must be retrained with real historical data before ML mode produces reliable output.

---

## Known Limitations & Caveats

| Issue | Impact | Fix (see roadmap) |
|---|---|---|
| XGBoost trained with frozen fundamental/sentiment features | ML mode score is unreliable | Retrain on real historical data once signal history has 30+ settled records |
| Short interest not scored | Squeeze risk shown but doesn't affect score | Add directional logic: high short % + rising price = bullish adjustment |
| VADER sentiment is lexicon-based | Misses sarcasm, context, financial jargon | Replace with fine-tuned financial NLP (FinBERT or similar) |
| Options flow = nearest expiry only | Misses macro hedging in far-dated contracts | Aggregate across all expiries weighted by OI |
| No real-time intraday data | Day change % is vs previous close, not live | Add Polygon.io intraday feed |
| No earnings transcript analysis | Qualitative guidance missed | Add SEC EDGAR 10-Q/earnings call parsing |
| Reddit / retail sentiment absent | Momentum/meme moves not captured | Add Reddit API sentiment per ticker |

---

## Roadmap: Improving Reliability

### Near-term
- **Retrain XGBoost** with real fundamental and sentiment features from signal history
- **Score short interest** directionally (bullish when price rising + squeeze conditions; bearish when unwinding)
- **Polygon.io intraday** feed for live pricing and real options volume
- **Aggregate options flow** across all expiries weighted by open interest

### Medium-term
- **Replace VADER** with FinBERT (financial-domain fine-tuned BERT) for sentiment scoring
- **SEC EDGAR** integration: parse 10-K/10-Q filings and earnings call transcripts for qualitative signals
- **NewsAPI + Reddit** sentiment to capture broader news cycle and retail momentum

### Longer-term
- **Auto-retraining pipeline**: retrain XGBoost weekly on settled signal history; deploy only if held-out MAE improves
- **User feedback loop**: thumbs-up/down on signals feeds into training weights
- **Sector rotation signals**: macro layer extended with sector ETF flows and factor exposure
- **Multi-model ensemble**: combine XGBoost, a small transformer, and the Claude analyst — majority vote for signal, confidence weighted by agreement

---

## Disclaimer

All signals and analysis produced by SAMSTradingAgent are for **informational purposes only** and do not constitute financial advice. Past signal accuracy does not guarantee future performance. Always conduct your own due diligence before making investment decisions.
