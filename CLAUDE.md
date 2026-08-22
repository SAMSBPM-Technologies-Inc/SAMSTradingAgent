# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAMSTradingAgent is a production AI-powered stock analysis system with three sub-projects:
- **backend/**: FastAPI + MongoDB + APScheduler engine deployed at `api.samsbpm.com`
- **frontend/**: React + Vite + Tailwind SPA deployed at `sta.samsbpm.com` (Cloudflare Pages)
- **mobile/**: React Native + Expo cross-platform app

## Releases

`CHANGELOG.md` at the repo root is the release record — update it in the same
change that ships the behaviour, not afterwards. Record what is *different for a
user*, not commit subjects. Keep the **Known gaps** section of each release
honest; a note that only lists wins is not trusted twice.

Backend, frontend, and mobile deploy together and share one version. When
bumping, all four declarations move together: `frontend/package.json`,
`mobile/package.json`, `backend/app/main.py` (`version=`), and
`backend/app/models/stock.py` (`HealthResponse.version`).

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

4. **AI Analyst** (`analyst.py`): Claude API generates structured JSON bull/bear report, cached per ticker with invalidation triggers (price change ≥3%, score change ≥0.12, VIX spike ≥30). The model is `ANALYST_MODEL` in `.env` (default `claude-sonnet-5` — see `config.py`); do not restate it in docs or UI, both read it from config via `AnalyzeResponse.analyst_model`.

5. **IBKR Trading** (`broker.py`, `trade_manager.py`): Per-user IB Gateway connections (Option C). Credentials stored Fernet-encrypted in MongoDB.

   **Autonomy is a dial, not a switch.** `AutoTradeSettings.mode` is
   `MANUAL` / `SEMI_AUTO` / `AUTO` (see `TradingMode`). Under MANUAL — and under
   SEMI_AUTO below `auto_execute_conviction` — `execute_entry` runs every guard,
   sizes the order, then writes it as a `PROPOSED` trade instead of sending it.
   PROPOSED and DECLINED are deliberately **not** in `TradeStatus.OPEN`: a
   proposal commits nothing and must never consume a position slot or reach
   realised performance. New accounts default to MANUAL; `db._migrate_trading_mode`
   writes AUTO for accounts that were already trading unattended, so the safe
   default never silently stops a live system.

   **Every order path shares one guard chain.** `_prepare_entry` holds all of
   them (CIRO, position cap, daily-loss kill switch, cash reserve, refusal to
   open unbracketed). `execute_entry` and `execute_manual_entry` both go through
   it — do not add a guard to one path only. A manual order differs in exactly
   two documented ways: no signal-score threshold (the human is the signal) and
   no whitelist (that restricts what the *agent* may pick).

   **Client quantities are requests.** `POST /trading/order` takes the smaller
   of the requested qty and what the risk model sizes to, so sizing cannot be
   escaped from a form field. Orders carry an `idempotency_key` — the unique
   sparse index on `(user_id, idempotency_key)`, not the route's lookup, is what
   stops a double-clicked Buy from buying twice. Live-money orders require
   `confirm_live`, which the UI sets only after the user types the ticker back.

### MongoDB Collections

| Collection | Purpose |
|---|---|
| `users` | Accounts, JWT, per-user scoring weights, IBKR creds (encrypted), alert settings |
| `stocks_raw` | Latest OHLCV + sentiment per ticker |
| `stocks_features` | Technical/fundamental/sentiment/macro/catalyst scores |
| `stocks_signals` | Latest BUY/SELL/HOLD per ticker (per-user aware) |
| `stocks_signal_history` | Historical signals for performance tracking + ML retraining |
| `watchlists` | Per-user ticker lists |
| `trades` | Auto-trading order records |
| `performance_stats` | Signal accuracy, win rates per ticker |

### Authentication

JWT-based auth, no feature gating. The tier system (0–3) and the admin portal
were removed in `f61066f7` when this became a personal tool with master/user
separation — every authenticated user gets every feature.

### Frontend Route Structure

```
/auth          → AuthPage (register/login)
/              → DashboardPage (watchlist: signals + dip-buy setups in one table)
/search        → SearchPage (ticker lookup — analyse without watching first)
/ticker/:sym   → TickerPage (chart, score breakdown, risk gate, order ticket, AI report)
/orders        → OrdersPage (proposal queue, open positions, full order history)
/holdings      → HoldingsPage (IBKR positions)
/performance   → PerformancePage (signal history, win rate)
/calibration   → CalibrationPage (do the thresholds hold up? see below)
/profile       → ProfilePage (alerts, IBKR config, auto-trade)
/guide         → GuidePage (IB Gateway setup)
/radar         → redirects to / (see below)
```

**Alpha Radar is merged into the dashboard.** It was never a second set of
tickers — both pages read the same `watchlists` collection, one joining
`stocks_signals` for the verdict and the other joining `stocks_features` for
dip-buy timing. `GET /watchlist` now returns both projections per row: the
signal plus a `trigger` (`ENTRY` / `EXIT_ALERT` / `NEUTRAL` / `PENDING`) with
the indicators behind it, surfaced as a Setup column, filter chips, and an
expandable row detail. Thresholds live in `services/setup_scan.py`;
`GET /signals/dip-buy` is deprecated but still served from the same module.

**Score attribution and the risk gate are surfaced, not hidden.** The six
sub-scores in `stocks_features` drive every verdict, so `GET /analyze` returns
a `breakdown` (each factor's sub-score, weight, and points contributed) and a
`gate` (the BUY/SELL thresholds and which the ticker passes). Both come from the
engine — `scoring.explain_score` and `signal_generator`'s constants — never from
constants restated in the UI. `explain_score` sets `attributable: false` on the
XGBoost path, where the weights did not produce the score and a decomposition
would be a fabrication.

**Calibration reports; it does not tune.** `/calibration` renders
`GET /performance/calibration`: whether the score ranks outcomes, what each
candidate BUY cutoff would have returned, and whether stated confidence tracks
being right. Every row carries `n` and a `significant` flag — under
`MIN_SAMPLES_FOR_SIGNAL` (30) the UI marks it *thin* rather than showing a
confident-looking percentage. Do not add auto-tuning here.

**Charts.** `GET /chart/{ticker}` (PNG, mplfinance) is for report export only.
The web client draws from `GET /chart/{ticker}/series` with `lightweight-charts`,
lazy-loaded so the library stays off pages that have no chart. SMA-20/50 are
computed server-side so the PNG and the interactive chart cannot disagree.

**Realised performance keeps three buckets apart** (`/performance/trades`):
`signal_driven` (agent placed it unattended — the only clean read of the
engine), `approved` (agent proposed, human accepted — biased by what the human
declined, so it measures the pair), and `manual` (human chose it). Never pool
them.

Key shared infrastructure: `AuthContext` (JWT persistence), `ThemeContext` (light/dark), `ToastContext` (`toast` / `toastWithUndo` — destructive actions defer their request for the length of the undo window), `lib/api.ts` (Axios with bearer token). The mobile app mirrors this structure using Expo Router.

**Mobile is at parity with web.** Order ticket, proposal queue, Orders tab,
chart, calibration, factor breakdown, risk gate, and holdings all exist on both
clients and must stay in step — particularly the two safety behaviours: the
displayed quantity is never authoritative (the server clamps it), and a
live-money order or approval requires the user to type the ticker back.

The mobile chart is `react-native-svg`, not `lightweight-charts` (DOM-only), but
reads the same `/chart/{ticker}/series` and the same server-computed moving
averages, so all three renderers plot the same line. Mobile screens still
hardcode a light-only `C` palette; the web tokens are the reference if they are
ever themed.

**Accessibility is linted, not audited by hand.** `npm run lint:a11y` in
`frontend/` runs jsx-a11y and must stay clean — it caught four defects a manual
sweep missed. Suppressions require a written reason; there are two.

**Colours are tokens, never hexes.** Every colour lives in both `:root` and
`.dark` in `frontend/src/index.css`. A raw hex in a component is a light-mode-only
colour — that is how the Performance page ended up painting `#14110c` on a
`#0e0c09` background and rendering as a black rectangle.

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
