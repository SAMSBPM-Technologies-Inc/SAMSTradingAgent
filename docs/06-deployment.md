# Deployment Guide

This guide covers everything needed to run SAMSTradingAgent locally for development and deploy it to a production environment using Hetzner Cloud and Cloudflare.

---

## 1. Prerequisites

Before starting, ensure the following are available:

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker | 24+ | Required for containerized deployment |
| Docker Compose | v2 (plugin) | Comes bundled with Docker Desktop; on Linux install `docker-compose-plugin` |
| Python | 3.12 | For local development without Docker |
| Node.js | 20+ | For building and running the frontend |
| npm | 10+ | Bundled with Node.js 20 |
| MongoDB | 6.0+ | Local via Docker Compose or a hosted Atlas cluster |

**Optional API keys** (features degrade gracefully if omitted):

| Key | Where to get it | Feature unlocked |
|-----|----------------|-----------------|
| Finnhub API key | [finnhub.io](https://finnhub.io) — free tier | Real-time and historical news sentiment |
| FRED API key | [fred.stlouisfed.org/docs/api](https://fred.stlouisfed.org/docs/api/api_key.html) — free | Live macro data (CPI, fed rate, unemployment, GDP) |
| Anthropic API key | [console.anthropic.com](https://console.anthropic.com) | AI analyst thesis generation |

---

## 2. Local Development Setup

### Backend (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values (see Section 3)
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive API docs: `http://localhost:8000/docs`

### Backend (with Docker Compose)

```bash
cd backend
cp .env.example .env
# Edit .env with your values
docker compose up --build
```

This starts both the FastAPI application and a local MongoDB container. The API is available at `http://localhost:8000`.

To run in detached mode:

```bash
docker compose up --build -d
docker compose logs -f api     # tail logs
docker compose down            # stop and remove containers
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
# Set VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

The frontend will be available at `http://localhost:5173` with hot module reloading enabled.

To build a production bundle locally:

```bash
npm run build
# Output in frontend/dist/
```

---

## 3. Environment Variables

### Backend (`backend/.env`)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MONGODB_URL` | `mongodb://localhost:27017` | Yes | MongoDB connection string. Use `mongodb://mongo:27017` when running inside Docker Compose. |
| `MONGODB_DB_NAME` | `trading_agent` | Yes | Name of the MongoDB database |
| `JWT_SECRET_KEY` | `change-me` | **Required in production** | Secret used to sign JWT tokens. Must be a strong random string in production (min 32 chars). |
| `FINNHUB_API_KEY` | _(empty)_ | No | Enables real news ingestion from Finnhub. Falls back to empty sentiment if unset. |
| `FRED_API_KEY` | _(empty)_ | No | Enables live macro data from FRED. Falls back to neutral macro scores if unset. |
| `ANTHROPIC_API_KEY` | _(empty)_ | No | Enables AI analyst thesis generation. Requires `ENABLE_AI_ANALYST=true`. |
| `ENABLE_AI_ANALYST` | `false` | No | Set to `true` to activate Claude-powered analyst reports |
| `ENABLE_ML_MODEL` | `false` | No | Set to `true` to activate XGBoost scoring overlay (model file must exist at `model/xgb_scorer.json`) |
| `ENABLE_BACKTESTING` | `false` | No | Set to `true` to enable the `GET /backtest` endpoint |
| `DEFAULT_TICKERS` | `PLTR,AAPL,TSLA,NVDA,MSFT` | No | Comma-separated list of tickers to ingest on startup and on schedule |
| `CORS_ORIGINS` | `http://localhost:5173` | Yes | Comma-separated list of allowed CORS origins. Must exactly match the frontend URL (no trailing slash). |
| `INGESTION_INTERVAL_MINUTES` | `30` | No | How often the background scheduler re-ingests data for all watched tickers |

### Frontend (`frontend/.env`)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Yes | Base URL for all API requests. Set to `https://sta.samsbpm.com` for production builds. |

> **Security note:** Never commit `.env` or `.env.production` files to version control. The `.gitignore` already excludes these files. Use `.env.example` and `.env.production.template` as safe, committed templates.

---

## 4. Production Deployment (Hetzner + Cloudflare)

The production stack runs on a Hetzner Cloud VPS with traffic routed through a Cloudflare Tunnel, eliminating the need to open any inbound firewall ports.

### Architecture Overview

```
User Browser
     |
     v
Cloudflare CDN / DDoS Protection
     |
     v
Cloudflare Tunnel (cloudflared container)
     |
     v
Hetzner VPS (private, no inbound ports required)
     |
     +--> Docker: api container (FastAPI, port 8000)
     +--> Docker: mongo container (MongoDB, port 27017, internal only)
```

### Server Setup

Provision a Hetzner Cloud VPS running Ubuntu 22.04. Then:

```bash
# Update system and install Docker
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git

# Add your user to the docker group (avoids needing sudo for docker commands)
sudo usermod -aG docker $USER

# Apply group changes without logging out
newgrp docker
```

### Application Setup

```bash
# Clone the repository
git clone https://github.com/SAMSBPM-Technologies-Inc/SAMSTradingAgent.git /opt/trading-agent

# Navigate to backend and create the production env file
cd /opt/trading-agent/backend
cp .env.production.template .env.production

# Edit with production values
nano .env.production
```

### .env.production (required values)

```env
MONGODB_URL=mongodb://mongo:27017
MONGODB_DB_NAME=trading_agent
JWT_SECRET_KEY=<strong-random-secret-min-32-chars>
CORS_ORIGINS=https://sta.samsbpm.com
FINNHUB_API_KEY=<your-finnhub-key>
FRED_API_KEY=<your-fred-key>
ANTHROPIC_API_KEY=<your-anthropic-key>
ENABLE_AI_ANALYST=true
ENABLE_ML_MODEL=false
DEFAULT_TICKERS=PLTR,AAPL,TSLA,NVDA,MSFT
INGESTION_INTERVAL_MINUTES=30
CLOUDFLARE_TUNNEL_TOKEN=<your-cloudflare-tunnel-token>
ADMIN_EMAIL=<the operator's account email>
```

Generate a strong `JWT_SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**`ADMIN_EMAIL` is set here by hand and is deliberately not injected by the
deploy workflow**, for the same reason `CONTACT_EMAIL` is not: the workflow's
`_set_key` writes `KEY=` for a variable it has no value for, and an empty admin
address makes *nobody* the operator — `/admin` becomes unreachable and account
provisioning silently stops working. It defaults in `config.py`, and
`main._check_admin_email` logs a warning at startup when it is empty or matches
no account. Check the api container's logs after a deploy:

```bash
docker compose -f docker-compose.prod.yml logs api | grep admin_email
```

Two other optional values, both cost controls rather than credentials:
`TIER_WATCHLIST_CAP_BASIC` / `TIER_WATCHLIST_CAP_PRO` (defaults 5 and 15 — the
number of tickers each plan may watch, which is what bounds how much work the
five-minute pipeline does on this deployment's own keys) and
`ANALYSIS_RUNS_PER_DAY` (default 25).

**First deploy after 1.18.0:** every existing account is written `access_tier:
TRADER` on startup, so nothing anyone was doing stops. New accounts default to
`BASIC`. Create the operator's account with `--tier TRADER` if it does not exist
yet, and make sure `ADMIN_EMAIL` matches it exactly.

### Cloudflare Tunnel Setup

The Cloudflare Tunnel replaces the need for Nginx, SSL certificates, or open inbound ports.

**Step 1:** Log in to the [Cloudflare Zero Trust dashboard](https://one.cloudflare.com) and navigate to **Access > Tunnels**.

**Step 2:** Click **Create a tunnel**, name it (e.g., `sta-production`), and copy the tunnel token into `.env.production` as `CLOUDFLARE_TUNNEL_TOKEN`.

**Step 3:** Configure `infra/cloudflared-config.yml`:

```yaml
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json

ingress:
  - hostname: sta.samsbpm.com
    service: http://api:8000
  - service: http_status:404
```

The `cloudflared` service in `docker-compose.prod.yml` mounts this config and uses the tunnel token from the environment variable to authenticate.

**Step 4:** In the Cloudflare DNS dashboard, ensure `sta.samsbpm.com` has a CNAME record pointing to `<tunnel-id>.cfargotunnel.com` with the proxy (orange cloud) enabled. Cloudflare Tunnel will create this automatically when the tunnel connects.

### First Deploy

```bash
cd /opt/trading-agent/backend

# Build images
docker compose -f docker-compose.prod.yml --env-file .env.production build

# Bring down any existing containers cleanly
docker compose -f docker-compose.prod.yml --env-file .env.production down --remove-orphans || true

# Start all services in detached mode
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

### Verify Deployment

```bash
# Check API health through the tunnel
curl https://sta.samsbpm.com/health
# Expected: {"status":"ok","db_connected":true}

# Check container status
docker compose -f docker-compose.prod.yml ps

# Tail API logs
docker compose -f docker-compose.prod.yml logs -f api
```

---

## 5. Frontend Deployment (Cloudflare Pages)

The frontend is a static Vite/React application deployed to Cloudflare Pages. It auto-deploys on every push to `main`.

**Setup steps:**

1. Navigate to [Cloudflare Pages](https://pages.cloudflare.com) in the Cloudflare dashboard.
2. Click **Create a project** and connect your GitHub repository.
3. Configure build settings:
   - **Build command:** `cd frontend && npm run build`
   - **Build output directory:** `frontend/dist`
4. Add environment variables:
   - `VITE_API_BASE_URL` = `https://sta.samsbpm.com`
5. Click **Save and Deploy**.

After initial setup, every push to the `main` branch (including changes outside the `frontend/` directory) triggers a new Pages deployment. Preview deployments are created for pull requests.

> **Note:** Frontend deployment via Cloudflare Pages is separate from the backend deployment workflow. The GitHub Actions CI/CD pipeline (Section 6) only handles backend deployment.

---

## 6. CI/CD Pipeline

Backend deployments are automated via GitHub Actions.

**Workflow file:** `.github/workflows/deploy.yml`

### Trigger Conditions

The workflow runs on pushes to `main` when any of the following paths change:

```yaml
on:
  push:
    branches: [main]
    paths:
      - 'backend/**'
      - '.github/workflows/deploy.yml'
```

### Workflow Steps

1. SSH into the Hetzner VPS using a deploy key
2. `git pull` the latest changes
3. `docker compose build` to rebuild the API image
4. `docker compose down --remove-orphans` to cleanly stop running containers
5. `docker compose up -d` to start updated containers

### Required GitHub Secrets

Configure these in **GitHub Repository > Settings > Secrets and variables > Actions**:

| Secret | Description |
|--------|-------------|
| `HETZNER_HOST` | IP address or hostname of the Hetzner VPS |
| `HETZNER_USER` | SSH user (e.g., `ubuntu` or `root`) |
| `HETZNER_SSH_KEY` | Private SSH key with access to the VPS (paste the full PEM content) |

### Adding the Deploy Key

On the Hetzner VPS, add the corresponding public key to `~/.ssh/authorized_keys`:

```bash
echo "<your-public-key>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

---

## 7. XGBoost Model Training (Optional)

The ML scoring feature uses an XGBoost model to augment the rule-based signal system. Training is optional; the system falls back to rule-based scoring if the model file is absent or `ENABLE_ML_MODEL=false`.

### Training

```bash
cd backend
pip install -r requirements.txt

# FRED API key is required for macro features
export FRED_API_KEY=<your-fred-key>

python scripts/train_xgb.py
```

The script will:
1. Download 3 years of daily OHLCV data for 30 large-cap US tickers from Yahoo Finance
2. Fetch macro features (CPI, fed rate, unemployment, GDP) from FRED
3. Engineer 14 features (see Technical Reference for full feature list)
4. Train an XGBoost classifier using time-series-aware cross-validation
5. Save the model to `backend/model/xgb_scorer.json`

**Training parameters:**

| Parameter | Value |
|-----------|-------|
| Training tickers | 30 large-cap US stocks |
| Historical data | 3 years daily bars |
| Features | 14 (technical + macro) |
| Train/test split | Time-based (no future leakage) |
| Estimated training time | 2–5 minutes on a modern CPU |

### Enabling the Model

After training completes:

```bash
# Verify the model file was created
ls -lh backend/model/xgb_scorer.json

# Enable in your .env
echo "ENABLE_ML_MODEL=true" >> backend/.env
```

Restart the API for the change to take effect. When enabled, `GET /analyze` responses will include a `ml_score` field alongside the rule-based `score`.

---

## 8. MongoDB Indexes

Indexes are created automatically at application startup via the `_ensure_indexes()` function in `db.py`. No manual index creation is required.

### Index Summary

| Collection | Index | Type | Notes |
|------------|-------|------|-------|
| `stocks_signals` | `ticker` | Unique | One document per ticker |
| `stocks_signal_history` | `(ticker, hour_bucket)` | Unique compound | Prevents duplicate signals within the same hour |
| `stocks_signal_history` | `ticker` | Standard | Fast per-ticker history lookups |
| `stocks_signal_history` | `generated_at` | Standard | TTL candidate; used for time-range queries |
| `stocks_signal_history` | `(generated_at, return_20d)` | Compound | Used by performance computation queries |
| `watched_tickers` | `(user_id, ticker)` | Unique compound | Ensures one watchlist entry per user per ticker |
| `users` | `email` | Unique | Fast login lookups; enforces unique email constraint |

### Manual Index Inspection

To verify indexes are in place on a running deployment:

```bash
docker exec -it trading_mongo mongosh trading_agent --eval "
  db.stocks_signal_history.getIndexes().forEach(i => printjson(i))
"
```

---

## 9. Health Monitoring

### Container Status

```bash
# Show running containers and their health status
docker compose -f docker-compose.prod.yml ps

# List containers with resource usage
docker stats --no-stream
```

### Log Inspection

```bash
# Tail live API logs (last 100 lines)
docker compose -f docker-compose.prod.yml logs -f api --tail=100

# View all service logs together
docker compose -f docker-compose.prod.yml logs -f --tail=50

# View cloudflared tunnel logs
docker compose -f docker-compose.prod.yml logs -f cloudflared
```

### API Health Check

```bash
# Check production endpoint
curl https://sta.samsbpm.com/health

# Check local endpoint
curl http://localhost:8000/health

# Expected response
# {"status":"ok","db_connected":true}
```

### MongoDB Health

```bash
# Ping MongoDB
docker exec -it trading_mongo mongosh --eval "db.adminCommand('ping')"

# Check collection sizes
docker exec -it trading_mongo mongosh trading_agent --eval "
  db.getCollectionNames().forEach(c => {
    print(c + ': ' + db[c].countDocuments() + ' documents')
  })
"

# Check signal history indexes
docker exec -it trading_mongo mongosh trading_agent --eval "
  db.stocks_signal_history.getIndexes()
"
```

### Scheduler Activity

The background ingestion scheduler logs its activity at the INFO level. To confirm it is running:

```bash
docker compose -f docker-compose.prod.yml logs api | grep -i "scheduler\|ingestion\|ingest"
```

---

## 10. Troubleshooting

| Problem | Symptoms | Fix |
|---------|----------|-----|
| Container won't start | Exits immediately with exit code 1 | Check logs: `docker compose -f docker-compose.prod.yml logs api`. Most commonly caused by a missing required `.env.production` value, model weight validation error, or import error. |
| Stale container state | "No such container" error during deploy | Run `docker compose down --remove-orphans` before `up -d`. This is already handled in `.github/workflows/deploy.yml`. |
| No signals appearing | Watchlist is empty or all tickers show no signal | Check that the scheduler is running (see logs). Signals are only generated during market hours (09:30–16:00 ET, Monday–Friday). Use `GET /analyze?force_refresh=true` to bypass scheduling and run immediately. |
| CORS errors in browser | Browser console shows "blocked by CORS policy" | Verify `CORS_ORIGINS` in `.env.production` exactly matches the frontend origin (e.g., `https://sta.samsbpm.com` — no trailing slash, correct protocol). |
| AI analyst not generating | Signals appear but `thesis`, `catalysts`, and `risks` are null | Confirm `ANTHROPIC_API_KEY` is set and valid. Confirm `ENABLE_AI_ANALYST=true`. Check logs for `anthropic` errors. |
| Yahoo Finance rate limiting | 429 or `Too Many Requests` errors in logs | Reduce the number of tickers in `DEFAULT_TICKERS` or increase `INGESTION_INTERVAL_MINUTES`. The backend serializes requests but high ticker counts can still hit informal limits. |
| MongoDB connection refused | `db_connected: false` in `/health` response | Verify the `mongo` container is running (`docker compose ps`). Check `MONGODB_URL` matches the service name in `docker-compose.prod.yml` (should be `mongodb://mongo:27017` inside Docker). |
| XGBoost model errors | API starts but `ml_score` is always null or startup logs show model load error | Verify `backend/model/xgb_scorer.json` exists and is not corrupt. Re-run `python scripts/train_xgb.py` or set `ENABLE_ML_MODEL=false` to disable. |
| Tunnel not connecting | API is running but `https://sta.samsbpm.com` returns a Cloudflare error | Check cloudflared container logs: `docker compose logs cloudflared`. Verify `CLOUDFLARE_TUNNEL_TOKEN` is set correctly in `.env.production`. Confirm the tunnel hostname is configured in the Cloudflare Zero Trust dashboard. |
| GitHub Actions deploy failing | Workflow fails at SSH step | Verify `HETZNER_HOST`, `HETZNER_USER`, and `HETZNER_SSH_KEY` secrets are set correctly. Ensure the public key corresponding to `HETZNER_SSH_KEY` is in `~/.ssh/authorized_keys` on the server. |
| JWT errors after restart | Users get 401 after a server restart or redeploy | If `JWT_SECRET_KEY` changed between deploys, all existing tokens are invalidated. Use a stable, persisted secret — do not regenerate it on each deploy. |

---

## Quick Reference

### Common Commands

```bash
# Start local dev (backend)
cd backend && uvicorn app.main:app --reload --port 8000

# Start local dev with Docker
cd backend && docker compose up

# Deploy to production (manually)
cd /opt/trading-agent/backend
docker compose -f docker-compose.prod.yml --env-file .env.production build
docker compose -f docker-compose.prod.yml --env-file .env.production down --remove-orphans || true
docker compose -f docker-compose.prod.yml --env-file .env.production up -d

# Tail production logs
docker compose -f docker-compose.prod.yml logs -f api --tail=100

# Health check
curl https://sta.samsbpm.com/health

# Train XGBoost model
cd backend && python scripts/train_xgb.py
```

### Port Reference

| Service | Port | Scope |
|---------|------|-------|
| FastAPI (local) | 8000 | Host-accessible |
| FastAPI (Docker) | 8000 | Host-accessible |
| MongoDB (local) | 27017 | Host-accessible |
| MongoDB (Docker) | 27017 | Internal only (not published in prod) |
| Vite dev server | 5173 | Host-accessible |
| Cloudflare Tunnel | — | No inbound ports required |
