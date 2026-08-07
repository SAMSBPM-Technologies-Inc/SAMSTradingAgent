#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — Push latest code to Hetzner and restart production containers
#
# Usage:
#   ./infra/deploy.sh                     # uses DEPLOY_HOST env var or prompts
#   DEPLOY_HOST=root@1.2.3.4 ./infra/deploy.sh
#   ./infra/deploy.sh root@1.2.3.4        # host as first argument
#
# Prerequisites on the server (run infra/setup-server.sh once first):
#   - Docker + Docker Compose
#   - Git repo cloned to $APP_DIR
#   - .env.production filled in at $APP_DIR/backend/.env.production
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST="${1:-${DEPLOY_HOST:-}}"
if [[ -z "$HOST" ]]; then
  echo "Usage: ./infra/deploy.sh <user@host>"
  echo "   or: DEPLOY_HOST=root@1.2.3.4 ./infra/deploy.sh"
  exit 1
fi

APP_DIR="${DEPLOY_APP_DIR:-/opt/trading-agent}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"

echo "▶ Deploying to $HOST → $APP_DIR"

ssh -o StrictHostKeyChecking=no "$HOST" bash -s -- "$APP_DIR" "$COMPOSE" <<'ENDSSH'
APP_DIR=$1
COMPOSE=$2

set -euo pipefail
cd "$APP_DIR/backend"

echo "── Pulling latest code ───────────────────────────────────────────"
git -C "$APP_DIR" pull origin main

echo "── Building API image ────────────────────────────────────────────"
$COMPOSE build --no-cache

echo "── Restarting containers ─────────────────────────────────────────"
$COMPOSE up -d --remove-orphans

echo "── Waiting for health check ──────────────────────────────────────"
sleep 10
$COMPOSE ps

echo "── Tail logs (last 30 lines) ─────────────────────────────────────"
$COMPOSE logs --tail=30 api
ENDSSH

echo "✓ Deploy complete"
