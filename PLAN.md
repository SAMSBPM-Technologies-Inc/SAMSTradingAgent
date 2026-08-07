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

## Phase 7 — Hosting & Infrastructure

### Backend: Cloudflare Tunnel + VPS

Cloudflare Workers **cannot** run this backend directly — Workers Python (Pyodide) has no asyncio, no Motor driver, and no APScheduler support. The right architecture is:

```
Docker container (Fly.io / Railway / Render / VPS)
  └── FastAPI + Motor + APScheduler
  └── cloudflared daemon (outbound-only tunnel)
        └── Cloudflare Network (DDoS, WAF, TLS, CDN)
              └── api.yourdomain.com → public internet
```

**What's required:**

1. **VPS / container platform** — Fly.io (free tier), Railway, Render, or any $5/mo VPS
   - Deploy existing Docker image unchanged
   - MongoDB stays as a container OR migrate to MongoDB Atlas (free M0 tier)

2. **MongoDB Atlas** (replace self-hosted Docker mongo)
   - Free M0 cluster (512 MB) works for dev; M10+ for prod
   - Change `MONGODB_URL` in `.env` to Atlas connection string
   - Atlas handles backups, failover, and monitoring

3. **Cloudflare Tunnel** (`cloudflared`)
   - Install `cloudflared` on the VPS alongside the container
   - Create tunnel: maps `api.yourdomain.com` → `http://localhost:8000`
   - No public IP needed on the server — outbound-only connection to Cloudflare
   - Free tier includes DDoS protection, TLS, and WAF

4. **Cloudflare DNS** — point your domain to Cloudflare nameservers (free)

5. **Environment changes needed:**
   - `MONGODB_URL` → Atlas URI
   - `APP_HOST` → `0.0.0.0` (already set)
   - `CORS` origins → restrict to your frontend domain in production

6. **Secret management** — move `.env` values to platform secrets (Fly.io secrets, Railway variables, etc.)

### Frontend: Cloudflare Pages

React (Vite) SPA deployed to Cloudflare Pages — free, global CDN, auto-deploy from GitHub.

```
GitHub repo → Cloudflare Pages build → global CDN edge
  └── calls api.yourdomain.com (Cloudflare Tunnel backend)
```

**What's required:**

1. **React + Vite** app (scaffold with `npm create cloudflare -- my-app --framework=react`)
2. **Cloudflare Pages** — connect GitHub repo, set build command (`npm run build`), output dir (`dist`)
3. **Environment variable:** `VITE_API_BASE_URL=https://api.yourdomain.com`
4. **CORS** — backend must allow the Pages domain in `allow_origins`

**Alternative:** React Native / Expo app (same API, different client) — decide later.

---

## Phase 8 — User Profiles & Authentication

Make the tool multi-user. Each user has their own watchlist, alert config, notes, and history.

### Architecture

```
Frontend (Cloudflare Pages)
  └── POST /auth/register | /auth/login → JWT access token
  └── All other requests: Authorization: Bearer <token>

Backend (FastAPI)
  └── JWT middleware validates token on every request
  └── All collections scoped by user_id
```

### New MongoDB Collections

| Collection | Purpose |
|---|---|
| `users` | Credentials, profile, preferences |
| `user_watchlists` | Per-user ticker list (replaces global `watched_tickers`) |
| `user_alerts` | Per-user alert rules |
| `user_notes` | Per-user ticker annotations |
| `user_signal_ratings` | User feedback on signal quality |

### New API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account (email + password) |
| POST | `/auth/login` | Returns JWT access token |
| GET | `/auth/me` | Current user profile |
| PUT | `/auth/me` | Update display name, preferences |
| POST | `/auth/logout` | Invalidate token (server-side blocklist) |

### All User Actions (complete list)

**Watchlist**
- Add ticker to personal watchlist → triggers background analysis
- Remove ticker from personal watchlist
- View personal watchlist ranked by conviction/score
- Reorder / prioritize watchlist manually

**Signals & Analysis**
- View latest signal for any ticker in their watchlist
- Force refresh analysis on demand for a specific ticker
- View full AI analyst report (thesis, bull/bear, risks, catalysts)
- View signal history for a ticker (own analysis runs)

**Performance & Tracking**
- View personal signal accuracy (win rate, avg 20d return) for their watchlist
- View per-ticker performance breakdown
- Compare signal performance across tickers (sort by win rate, avg return)

**Alerts & Notifications**
- Create alert rule: trigger on BUY/SELL/HOLD + conviction level + min confidence
- Set notification channel: email, Slack webhook URL, or in-app
- Toggle daily digest on/off (summary of watchlist signals each morning)
- View alert history (which alerts fired, when)

**Notes & Feedback**
- Add personal note to any ticker (free text, timestamped)
- Edit / delete notes
- Rate a signal (thumbs up / thumbs down) — feeds into model retraining signal quality
- View all notes across watchlist

**Preferences**
- Set default signal filter (show only BUY, or all)
- Set minimum confidence threshold for display
- Set risk tolerance preference (LOW/MEDIUM/HIGH max risk shown)
- Choose notification frequency (real-time, hourly digest, daily only)
- Dark/light theme preference

**Data Export**
- Export watchlist signals to CSV
- Export signal history to CSV
- Share a read-only report link for a specific ticker (no login required for recipient)

### Auth Implementation

- **Library:** `python-jose[cryptography]` + `passlib[bcrypt]` (FastAPI standard)
- **Token:** JWT with `user_id`, `email`, `exp` (24h access token)
- **Middleware:** `Depends(get_current_user)` injected into all protected routes
- **Password:** bcrypt hashed, never stored plain
- **No Cloudflare Access** for end-user auth (that's for internal/admin tooling) — build custom JWT auth in FastAPI

### Backend Changes Required

- All watchlist, signals, history queries gain `user_id` filter
- Scheduler pipeline runs per-user watchlist (union of all users' tickers, deduplicated)
- `POST /ticker` and `DELETE /ticker/{ticker}` scoped to authenticated user
- `GET /signals`, `/watchlist`, `/performance`, `/report` all scoped to authenticated user's tickers

---

## Phase 9 — Frontend Dashboard

React (Vite) SPA on Cloudflare Pages consuming the authenticated API.

- Login / register screens
- Personal watchlist table with color-coded BUY/SELL/HOLD badges
- Signal cards: conviction, price target, stop loss, thesis, analyst note
- Full report view per ticker (bull/bear case, key risks, catalysts)
- Performance dashboard: win rate, avg 20d return, signal history chart
- Alert management UI
- Ticker notes panel
- CSV export buttons
- Real-time polling (30s interval) or WebSocket for live signal updates

---

## Phase 10 — Backtesting Engine

Replay `stocks_signal_history` against actual price data to measure portfolio-level P&L.

- Compute returns if every signal was followed at generation time
- Metrics: Sharpe ratio, max drawdown, hit rate by signal type and ticker
- Scoped per user (only their watchlist history)
- New endpoint: `GET /backtest?from=2025-01-01`

---

## Phase 11 — Alerts & Notifications

Push alerts when notable signals emerge — no polling required.

- Slack/email webhook on HIGH conviction BUY/SELL signals (per user alert rules)
- Daily digest of watchlist conviction changes
- Triggered from the scheduler after each pipeline run

---

## Phase 12 — Paper Trading Integration

Connect Alpaca paper-trading API to auto-execute signals.

- Execute BUY/SELL on HIGH conviction signals within position size limits
- Track paper P&L separately from signal accuracy stats
- New endpoint: `GET /paper-portfolio` for open positions and returns

---

## Phase 13 — Model Auto-Retraining Pipeline

Close the feedback loop using the system's own signal history as training data.

- Once `stocks_signal_history` has enough settled records (30+ days), retrain XGBoost on them weekly
- Compare new model vs current model on held-out recent records before swapping
- Incorporate user signal ratings (thumbs up/down) as quality weights
- Scheduler job: retrain every Sunday, auto-deploy if test MAE improves
