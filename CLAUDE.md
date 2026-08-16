# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAMSTradingAgent is a production AI-powered stock analysis system with three sub-projects:
- **backend/**: FastAPI + MongoDB + APScheduler engine deployed at `api.samsbpm.com`
- **frontend/**: React + Vite + Tailwind SPA deployed at `sta.samsbpm.com` (Cloudflare Pages)
- **mobile/**: React Native + Expo cross-platform app

## Commands

### Backend

```bash
cd backend

# Local development
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in MONGODB_URL and API keys
uvicorn app.main:app --reload --port 8000

# Docker (local)
docker compose up --build

# Docker (production)
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# Quick API tests
curl http://localhost:8000/health
curl "http://localhost:8000/analyze?ticker=AAPL"
curl http://localhost:8000/signals
# Swagger UI: http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev       # Vite dev server
npm run build     # tsc && vite build (production)
npm run preview   # preview production build
```

### Mobile

```bash
cd mobile
npm install
npm start         # Expo dev server
npm run ios
npm run android
npm run web
```

## Architecture

### Backend Request Flow

1. **Ingestion** (5-minute APScheduler job): `pipeline.py` orchestrates the full cycle per ticker
   - `ingestion.py` → yfinance OHLCV + Finnhub news
   - `feature_engineering.py` → RSI, MACD, Bollinger Bands, ATR, OBV, Stochastic RSI
   - `fundamentals.py` → P/E, EPS growth, debt/equity via yfinance
   - `news.py` → Finnhub headlines + VADER sentiment
   - `macro.py` → FRED API (interest rates, CPI, VIX)
   - `alternative_data.py` → options flow, short interest, insider activity
   - `catalyst.py` → earnings proximity, insider buys, options signals

2. **Scoring** (`scoring.py`): weighted combiner
   ```
   score = w_tech×technical + w_fund×fundamental + w_sent×sentiment +
           w_macro×macro + w_vol×volatility + w_cat×catalyst
   ```
   Weights configured via `.env` and validated to sum to 1.0 in `config.py`.

3. **Signal Generation** (`signal_generator.py`):
   - BUY: score > 0.70 AND risk_score < 6
   - SELL: score < 0.30
   - HOLD: otherwise

4. **AI Analyst** (`analyst.py`): Claude API (claude-opus-4-6) generates structured JSON bull/bear report, cached per ticker with invalidation triggers (price change ≥3%, score change ≥0.12, VIX spike ≥30).

5. **IBKR Auto-Trading** (`broker.py`, `trade_manager.py`): Per-user IB Gateway connections (Option C). Credentials stored Fernet-encrypted in MongoDB.

### MongoDB Collections

| Collection | Purpose |
|---|---|
| `users` | Accounts, JWT, tier (0-3), role, IBKR creds (encrypted), alert settings |
| `stocks_raw` | Latest OHLCV + sentiment per ticker |
| `stocks_features` | Technical/fundamental/sentiment/macro/catalyst scores |
| `stocks_signals` | Latest BUY/SELL/HOLD per ticker (per-user aware) |
| `stocks_signal_history` | Historical signals for performance tracking + ML retraining |
| `watchlists` | Per-user ticker lists |
| `trades` | Auto-trading order records |
| `performance_stats` | Signal accuracy, win rates per ticker |

### Authentication & Tiers

JWT-based auth. User tiers gate feature access:
- Tier 0: Basic signals
- Tier 1: Full dashboard
- Tier 2+: AI Analyst report (`/report/{ticker}`)
- Tier 3: Admin (`sudheer.samudrala@samsbpm.com` auto-elevated on startup)

### Frontend Route Structure

```
/auth          → AuthPage (register/login)
/              → DashboardPage (watchlist + live signals)
/ticker/:sym   → TickerPage (full AI report, bull/bear, technical chart)
/performance   → PerformancePage (signal history, win rate)
/profile       → ProfilePage (alerts, IBKR config, auto-trade)
/alpha-radar   → AlphaRadarPage (dip-buy scanner)
/guide         → GuidePage (IB Gateway setup)
/admin         → AdminPage (user management, tier/role)
```

Key shared infrastructure: `AuthContext` (JWT persistence), `ThemeContext` (light/dark), `lib/api.ts` (Axios with bearer token). The mobile app mirrors this structure using Expo Router.

### Configuration

All backend config flows through `app/config.py` (Pydantic BaseSettings from `.env`). Key flags:
- `ENABLE_ML_MODEL` — XGBoost inference path (currently disabled in prod)
- `ENABLE_AI_ANALYST` — Claude analyst reports
- `ENABLE_BACKTESTING` — backtesting engine (stub)
- `AUTO_TRADE_ENABLED` / `AUTO_TRADE_LIVE_ALLOWED` — IBKR paper vs live

### Deployment

CI/CD: GitHub Actions (`.github/workflows/deploy.yml`) → SSH to Hetzner VPS → `git pull` → generate `.env.production` from GitHub Secrets → `docker compose -f docker-compose.prod.yml up --build -d`. The `cloudflared` service in `docker-compose.prod.yml` handles HTTPS via Cloudflare Tunnel.

### Current Development State

See `PLAN.md` for full roadmap. Next priority: **Phase 4 — XGBoost Scoring Overhaul** (fundamental and sentiment scores currently frozen in the ML inference path).

**Production data note:** yfinance is used for development only. Production use requires a licensed data provider (Polygon.io, Alpaca, or Refinitiv).
