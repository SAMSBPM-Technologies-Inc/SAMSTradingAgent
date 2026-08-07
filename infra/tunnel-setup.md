# Cloudflare Tunnel Setup

One-time steps to expose the trading agent API through Cloudflare without opening any inbound ports on your Hetzner server.

---

## Prerequisites

- Cloudflare account with your domain added (free plan is fine)
- Hetzner server bootstrapped via `infra/setup-server.sh`
- Docker Compose stack **not yet running** (tunnel token needed first)

---

## Step 1 — Create the Tunnel

1. Go to [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/)
2. Left sidebar → **Networks** → **Tunnels**
3. Click **Create a tunnel**
4. Choose **Cloudflared** → click **Next**
5. Name it `trading-agent` → click **Save tunnel**
6. On the next screen, select **Docker** as the environment
7. Copy the **token** from the `docker run` command shown:
   ```
   docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run \
     --token eyJh...LONG_TOKEN_HERE...
   ```
   You only need the token string after `--token`.

---

## Step 2 — Add the Token to .env.production

SSH into your Hetzner server and edit the env file:

```bash
ssh deploy@YOUR_SERVER_IP
nano /opt/trading-agent/backend/.env.production
```

Set:
```
CLOUDFLARE_TUNNEL_TOKEN=eyJh...LONG_TOKEN_HERE...
```

---

## Step 3 — Configure the Public Hostname

Back in the Cloudflare dashboard (still on the tunnel setup page, or edit the tunnel later):

1. Click **Next** (or **Edit** → **Public Hostname** tab)
2. Click **Add a public hostname**
3. Fill in:
   | Field | Value |
   |-------|-------|
   | Subdomain | `trading-api` (or whatever you want) |
   | Domain | your domain (e.g. `yourdomain.com`) |
   | Service Type | `HTTP` |
   | URL | `api:8000` |
4. Click **Save hostname**

Your API will be reachable at `https://trading-api.yourdomain.com`.

> **Why `api:8000`?** The `cloudflared` container is on the same internal Docker network as the `api` container. Docker's internal DNS resolves `api` to the API container's IP — no host port binding needed.

---

## Step 4 — Update CORS_ORIGINS

In `.env.production`, set your frontend origin:

```
CORS_ORIGINS=https://trading.yourdomain.com
```

If you also have a Cloudflare Pages frontend:
```
CORS_ORIGINS=https://trading.yourdomain.com,https://your-app.pages.dev
```

---

## Step 5 — Deploy

From your local machine:

```bash
# First deploy (setup-server.sh must have been run already)
DEPLOY_HOST=deploy@YOUR_SERVER_IP ./infra/deploy.sh
```

---

## Step 6 — Verify

```bash
# Health check through the tunnel (from anywhere)
curl https://trading-api.yourdomain.com/health

# Expected response:
# {"status":"ok","db":"connected","scheduler":"running"}
```

---

## Tunnel Status

Check tunnel connectivity in the Cloudflare dashboard:
- **Networks → Tunnels** → your tunnel should show **Healthy** (green)

If it shows **Inactive**, the `cloudflared` container isn't running. Check with:
```bash
ssh deploy@YOUR_SERVER_IP docker compose -f /opt/trading-agent/backend/docker-compose.prod.yml ps
```

---

## Updating the Tunnel Domain

If you need to change the public hostname later:
1. Cloudflare dashboard → **Networks → Tunnels** → click your tunnel
2. **Public Hostname** tab → edit or add hostnames
3. No server restart needed — changes propagate within seconds.
