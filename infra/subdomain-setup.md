# Onboarding a New User — Subdomain Setup

Each user gets their own subdomain (e.g., `sudheer.samsbpm.com`) pointing to the shared frontend,
backed by the shared API at `api.samsbpm.com`. The process takes about 5 minutes.

---

## Step 1 — Create the User Account

SSH into the Hetzner VPS, then run the create_user script from inside the backend container:

```bash
ssh root@204.168.166.162
docker exec -it trading-agent-api-1 python scripts/create_user.py \
  --email alice@example.com \
  --password "TemporaryPass123!" \
  --name "Alice"
```

The script will print the new user's ID and confirm creation.
Share the temporary password with the user and ask them to change it via their profile page.

---

## Step 2 — Add the Cloudflare Custom Domain

The frontend is deployed as a **Cloudflare Pages** project (`sta.samsbpm.com` is the primary domain).
Each user subdomain is just an additional custom hostname pointing to the same Pages deployment.

1. Go to **Cloudflare Dashboard → Pages → SAMSTradingAgent project → Custom domains**
2. Click **Set up a custom domain**
3. Enter `alice.samsbpm.com`
4. Cloudflare will add a CNAME record automatically (requires the samsbpm.com zone to be on Cloudflare)
5. Wait for SSL certificate provisioning (~1–2 minutes)

That's it — `alice.samsbpm.com` now serves the same app. Alice logs in with her email/password
and the JWT carries her identity. Her watchlist, alerts, IBKR settings, and scoring weights
are completely independent of other users.

---

## Step 3 — Tell the User

Send them:
- Their subdomain URL: `https://alice.samsbpm.com`
- Their email + temporary password
- A reminder to set up their scoring weights, alert channels, and IBKR settings from the Profile page

---

## CORS Note

If you add a new subdomain, make sure it's included in the backend's `CORS_ORIGINS` environment variable
on the Hetzner VPS (set in `.env.production` and the GitHub Actions deploy workflow):

```
CORS_ORIGINS=https://sta.samsbpm.com,https://sudheer.samsbpm.com,https://alice.samsbpm.com
```

After editing, redeploy:
```bash
cd /opt/trading-agent
docker compose -f docker-compose.prod.yml up -d --build api
```

---

## Removing a User

To revoke access, delete their account directly from MongoDB:

```bash
docker exec -it trading-agent-api-1 python -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings

async def delete():
    s = get_settings()
    client = AsyncIOMotorClient(s.mongodb_url)
    db = client[s.mongodb_db_name]
    result = await db['users'].delete_one({'email': 'alice@example.com'})
    print('Deleted:', result.deleted_count)
    client.close()

asyncio.run(delete())
"
```

Then remove the custom domain from the Cloudflare Pages project.
