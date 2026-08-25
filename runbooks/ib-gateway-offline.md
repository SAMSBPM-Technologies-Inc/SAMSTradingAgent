# Runbook — IB Gateway offline

`07-user-guide.md` and the in-app Guide cover *setting up* IB Gateway. This
covers what to do when a working one stops working, which is a different job.

**Symptom:** the account bar reads "Broker disconnected", orders are refused with
*"IB Gateway not connected"*, and `Close` returns a 503.

Nothing is lost while it is down. Orders are refused rather than silently
dropped, and the backend reconnects on its own once the gateway is back.

---

## First: is this expected?

Three causes account for nearly every outage, and two of them are routine.

### 1. IBKR weekend maintenance — *most likely on a Monday morning*

IBKR takes its authentication infrastructure down over the weekend. IB Gateway
cannot log in during that window. The container restarts itself nightly at
`AUTO_RESTART_TIME` (default `11:45 PM America/New_York`) to survive IBKR's
daily forced logout — and a restart that lands inside the maintenance window
comes back **running but unauthenticated**, and stays that way.

This is the case where the process looks healthy, the port may even answer, and
no session exists. A restart is the only thing that clears it.

### 2. An unanswered two-factor prompt

IBKR pushes a 2FA request to the phone on the account. `TWOFA_TIMEOUT_ACTION=restart`
makes IBC retry rather than die, but **it will retry forever if nobody approves
it.** Any recovery attempt can stall here, including the UI button.

### 3. A deploy restarted it at a bad moment

The deploy runs `docker compose up -d --no-deps ibgateway`, and it rewrites
`.env.production` on every run, which can make compose recreate the container.
A deploy during a maintenance window produces case 1.

---

## Recovery, easiest first

### Option A — from the UI

**Orders → Broker panel.**

1. **Reconnect** — asks for a session immediately instead of waiting out the
   backoff (15s → 300s). Fixes a stale socket where the gateway is fine and this
   process is holding a dead connection. Always available.
2. **Restart gateway** — restarts the container. This is what clears case 1.
   Only enabled if the server was configured for it (see below); otherwise the
   button explains why it is unavailable.

After a restart, **watch your phone for a 2FA prompt.** The panel polls and
updates itself; login takes about two minutes.

### Option B — over SSH

Always available, and needs no special grant.

```bash
cd /opt/trading-agent/backend

# 1. What state is it in?
docker inspect --format='{{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}' \
  trading_ibgateway

# 2. Read the logs — this identifies WHICH case you are in
docker compose -f docker-compose.prod.yml logs --tail=200 ibgateway
```

What to look for:

| In the logs | Case | Action |
|---|---|---|
| `Login failed`, auth errors, peer resets | 1 — weekend maintenance | Restart |
| `Second Factor Authentication`, 2FA timeout | 2 — unanswered push | Restart, then approve on phone |
| Container restarting in a loop | Bad credentials or config | Check `TWS_USERID` / `TWS_PASSWORD` for the mode |
| Healthy, port answering | Stale socket on our side | `Reconnect` in the UI |

```bash
# 3. Restart
docker compose -f docker-compose.prod.yml --env-file .env.production \
  up -d --no-deps --force-recreate ibgateway

# 4. Approve the 2FA push on your phone if one arrives.

# 5. After ~120s, prove the API can reach the relay port
docker exec trading_agent_api python -c \
  "import os,socket; socket.create_connection((os.getenv('IBKR_HOST','ibgateway'), int(os.getenv('IBKR_PORT','4004'))), 5).close()" \
  && echo "relay OK"
```

**You do not need to restart the API.** `broker._reconnect_loop` retries with
backoff to a 300s ceiling, so the session returns within about five minutes of
the gateway being ready.

---

## Enabling the UI restart button

Off by default — set `ALLOW_GATEWAY_RESTART=true` in `.env.production` and
recreate the API container.

**What you are granting.** The API never sees the host Docker socket. A
`dockerproxy` sidecar holds it read-only and the API talks HTTP to that, on an
internal network that is never published to the host. The proxy answers only the
`/containers` endpoints; images, volumes, networks, exec, swarm and system are
refused outright.

That is a large reduction from the raw socket, and it is **not** a precise
"restart only" capability — `POST=1` also permits other container verbs. Smaller
blast radius, not zero. If you would rather grant nothing, leave the flag off
and use the SSH steps above; they achieve the same result.

`GET /trading/broker/status` reports `restart_available` so the UI never offers a
button that cannot work, and says which piece is missing when it is unavailable.

`GET /trading/broker/status` reports `restart_available` so the UI never offers
a button that cannot work.

---

## Alerting

A scheduled job checks the session every 5 minutes and alerts through the same
Slack / WhatsApp channels as signals once it has been down for
`BROKER_ALERT_AFTER_MINUTES` (default 15). It sends once per outage, and again
on recovery.

The threshold sits above the reconnect loop's 300s ceiling deliberately, so a
blip the loop fixes on its own never pages anyone.

Nothing arrives if no alert channel is configured — set one in **Profile →
Alerts**, otherwise this failure stays silent until you try to trade.

---

## Port model — worth knowing before changing anything

IB Gateway binds `4001` (live) / `4002` (paper) on **loopback inside its own
container**. A socat relay republishes them on `4003` / `4004` bound to
`0.0.0.0`.

Other containers must connect to **4003/4004**. Connecting to 4001/4002 is
refused, and it is the classic silent failure here — which is why the container
healthcheck probes the relay port rather than the gateway's own.
