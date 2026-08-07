#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup-server.sh — One-time Hetzner server bootstrap
#
# Run this ONCE on a fresh Ubuntu 22.04 / Debian 12 server before deploying.
#
# Usage (from your local machine):
#   ssh root@YOUR_SERVER_IP 'bash -s' < infra/setup-server.sh
#
# What it does:
#   1. Installs Docker + Docker Compose plugin
#   2. Creates deploy user (non-root, docker group)
#   3. Clones this repo to /opt/trading-agent
#   4. Prints next steps (tunnel token + .env.production)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/YOUR_ORG/SAMSTradingAgent.git}"
APP_DIR="${APP_DIR:-/opt/trading-agent}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

echo "════════════════════════════════════════════════════════════"
echo " SAMSTradingAgent — Server Bootstrap"
echo "════════════════════════════════════════════════════════════"

# ── 1. System packages ────────────────────────────────────────────────────────
echo ""
echo "── Installing system packages ───────────────────────────────"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl gnupg git ufw

# ── 2. Docker ─────────────────────────────────────────────────────────────────
echo ""
echo "── Installing Docker ─────────────────────────────────────────"
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
  echo "  Docker $(docker --version) installed."
else
  echo "  Docker already installed — skipping."
fi

# ── 3. Deploy user ────────────────────────────────────────────────────────────
echo ""
echo "── Creating deploy user '$DEPLOY_USER' ──────────────────────"
if ! id "$DEPLOY_USER" &>/dev/null; then
  useradd -m -s /bin/bash "$DEPLOY_USER"
  echo "  User created."
else
  echo "  User already exists — skipping."
fi
usermod -aG docker "$DEPLOY_USER"
echo "  Added '$DEPLOY_USER' to docker group."

# Copy root's authorized_keys so the deploy user can SSH in
DEPLOY_HOME=$(getent passwd "$DEPLOY_USER" | cut -d: -f6)
mkdir -p "$DEPLOY_HOME/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  cp /root/.ssh/authorized_keys "$DEPLOY_HOME/.ssh/authorized_keys"
  chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh"
  chmod 700 "$DEPLOY_HOME/.ssh"
  chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
  echo "  Copied authorized_keys to $DEPLOY_HOME/.ssh/"
fi

# ── 4. Clone repo ─────────────────────────────────────────────────────────────
echo ""
echo "── Cloning repo to $APP_DIR ─────────────────────────────────"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
  chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
  echo "  Cloned."
else
  echo "  Repo already cloned — skipping."
fi

# ── 5. Firewall (UFW) ─────────────────────────────────────────────────────────
echo ""
echo "── Configuring UFW firewall ──────────────────────────────────"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
# No need to open 8000 — cloudflared tunnels through outbound HTTPS
ufw --force enable
echo "  UFW enabled (SSH only inbound; cloudflared uses outbound)."

# ── 6. Create .env.production placeholder ────────────────────────────────────
echo ""
echo "── Creating .env.production placeholder ─────────────────────"
ENV_FILE="$APP_DIR/backend/.env.production"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/backend/.env.production.template" "$ENV_FILE"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "  Created $ENV_FILE — fill in real values before deploying!"
else
  echo "  $ENV_FILE already exists — not overwriting."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo " Bootstrap complete!"
echo ""
echo " NEXT STEPS:"
echo "   1. Edit $ENV_FILE and fill in:"
echo "        CLOUDFLARE_TUNNEL_TOKEN=<from Cloudflare dashboard>"
echo "        FINNHUB_API_KEY=..."
echo "        FRED_API_KEY=..."
echo "        ANTHROPIC_API_KEY=..."
echo "        CORS_ORIGINS=https://your-frontend.pages.dev"
echo ""
echo "   2. Create Cloudflare Tunnel:"
echo "        See infra/tunnel-setup.md for step-by-step instructions."
echo "        Service URL to enter in dashboard: http://api:8000"
echo ""
echo "   3. Deploy:"
echo "        DEPLOY_HOST=$DEPLOY_USER@\$(hostname -I | awk '{print \$1}') \\"
echo "          ./infra/deploy.sh"
echo ""
echo "   4. Verify:"
echo "        curl https://YOUR_TUNNEL_DOMAIN/health"
echo "════════════════════════════════════════════════════════════"
