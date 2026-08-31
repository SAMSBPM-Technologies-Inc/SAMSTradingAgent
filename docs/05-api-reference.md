# API Reference

**Version:** 1.0
**Base URL (Production):** `https://sta.samsbpm.com`
**Base URL (Local):** `http://localhost:8000`
**Interactive Docs:** `{base_url}/docs` (Swagger UI) | `{base_url}/redoc` (ReDoc)

---

## Authentication

All endpoints except `/health`, `/auth/login`, `POST /contact`, `POST /auth/forgot-password` and `POST /auth/reset-password` require a Bearer token in the `Authorization` header. Authenticated endpoints may additionally require an access tier — see *Access tiers*.

```
Authorization: Bearer <access_token>
```

Tokens are obtained by registering a new account or logging in. The default token expiry is **24 hours**. After expiry, re-authenticate using `/auth/login`.

---

## Endpoints

### GET /system/status

Which data sources and subsystems are working, and what each one costs the
judgement. **Authenticated** — unlike `/health`, it names environment
variables and provider error text.

Nothing is probed. Every capability row is what that source actually did on
the last pipeline cycle, read from records the fetches themselves wrote. A
probe would spend the Alpha Vantage daily budget it was reporting on, and
would answer "can we reach FRED now" when the question is "did FRED build the
macro factor behind this score".

```json
{
  "overall": "ok",
  "summary": "Everything configured is working. Macro environment is switched off on this server, so the factor it feeds sits at neutral.",
  "checked_at": "2026-08-31T14:32:00Z",
  "market_open": true,
  "cycle": {
    "last_run_at": "2026-08-31T14:30:00Z",
    "age_minutes": 2,
    "stale": false,
    "tickers_ok": 13,
    "tickers_total": 13,
    "failed_tickers": [],
    "last_error": null
  },
  "capabilities": [
    {
      "id": "macro",
      "label": "Macro environment",
      "tier": "quiet",
      "required_key": "FRED_API_KEY",
      "impact": "The macro factor is pinned to 0.50 market-wide, and the VIX spike that would otherwise force a fresh analyst read never fires.",
      "feeds": "Macro (0.15 of the composite by default)",
      "configured": false,
      "state": "not_configured",
      "detail": "Not configured on this server — set FRED_API_KEY to switch it on.",
      "last_success_at": null,
      "last_error": null,
      "last_error_at": null,
      "consecutive_failures": 0
    }
  ]
}
```

`tier` groups by what the absence costs: `stops` (trading pauses), `behaviour`
(a different decision path runs), `quiet` (a factor goes neutral and the
verdict still publishes).

**`configured` and `state` are separate, and must stay separate.** A source
with no key reports `not_configured`, never `failed` — an absent key is a
deliberate choice rather than a fault, the same distinction
`ResearchVetoStatus` draws between `enabled` and `would_block`.

`cycle.stale` is judged against the market clock. The pipeline does not run
outside trading hours, so a quiet overnight is the design, not an outage.

---

### GET /health

**Description:** Returns the current health status of the API and its database connection. Useful for load balancer health checks and uptime monitoring.

**Auth required:** No

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| status | string | Always `"ok"` when service is running |
| db_connected | boolean | `true` if MongoDB is reachable |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 200 | Always returns 200; check `db_connected` for database health |

**Example:**

```json
// GET /health
// Response 200
{
  "status": "ok",
  "db_connected": true
}
```

---

### Registration — there isn't one

There is no `POST /auth/register`, and there never will be on this deployment.
Accounts are provisioned by the operator: people ask through `POST /contact`,
which records an `access_requests` row, and the operator creates the account
from `POST /admin/users` (or `scripts/create_user.py` for the very first one)
and emails the credentials.

Every account carries an **access tier** — `BASIC`, `PRO` or `TRADER` — which
decides what it may reach. See *Access tiers* below.

---

## Access tiers

| | BASIC | PRO | TRADER |
|---|---|---|---|
| Stored analysis, watchlist, signals, performance, calibration, status, alerts | ✓ | ✓ | ✓ |
| `POST /research/{ticker}`, `/analyze?force_refresh=true` | ✗ | ✓ | ✓ |
| `/settings/llm` key management | ✗ | ✓ | ✓ |
| Falls back to the deployment's model key | ✗ | ✗ | ✓ |
| Nightly research enrolment | ✗ | operator grant | ✓ |
| Every route under `/trading` | ✗ | ✗ | ✓ |
| Watchlist cap (default) | 5 | 15 | unlimited |

Two behaviours are worth calling out because they are not refusals:

* **Plain `GET /analyze`** (neither `force_refresh` nor `stored_only`) normally
  rebuilds a signal older than the cache window. For a caller who may not spend
  tokens it behaves as `stored_only` instead — returning the stored document at
  any age, or 404 — rather than 403, because the report export and the watchlist
  warm-up both call it.
* **`DELETE /settings/llm/keys/{key_id}`** and setting `research_enabled: false`
  are never refused, whatever the plan. Removing a credential or stopping a
  recurring spend must always work.

### The refusal shape

Tier refusals return **403** with a structured `detail` — note that every route
predating this returns a plain string there, so a client must read both:

```json
{
  "detail": {
    "error": "tier_required",
    "capability": "may_trade",
    "tier": "PRO",
    "message": "Trading and broker access are not part of your plan. Contact the desk to change your plan."
  }
}
```

`POST /ticker` uses the same envelope with `"error": "watchlist_cap"` plus `cap`
and `watching`. `/admin/*` uses `"error": "admin_required"`.

---

### POST /auth/login

**Description:** Authenticates an existing user using OAuth2 password flow and returns an access token.

**Auth required:** No

**Request body** (`application/x-www-form-urlencoded`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | Yes | The user's registered email address |
| password | string | Yes | The user's password |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| access_token | string | JWT bearer token |
| token_type | string | Always `"bearer"` |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Invalid email or password |
| 422 | Missing required fields |

**Example:**

```
// POST /auth/login
// Content-Type: application/x-www-form-urlencoded
username=trader%40example.com&password=securepassword123

// Response 200
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

### Password

Three routes set a password, and all three go through one helper that also
records `password_changed_at`. That field, compared against the token's `iat`,
**ends every session issued before the change** — without it a reset would
rotate the credential and leave a stolen token working for the rest of its 24
hours. A token with no `iat` fails closed against a recorded change; an account
that has never changed its password is unaffected.

#### PUT /auth/password

Auth required. Body: `current_password`, `new_password` (min 12).

The current password is required even though the caller holds a valid token: a
token can be stolen, and without the check whoever stole one could lock the
real owner out permanently. Rate limited on the same counter as sign-in.

Returns `{access_token, token_type}` — **the caller must store it**. Their old
token is among the ones this change just invalidated, so the swap is what keeps
them signed in on this device while every other session ends.

| Status | Condition |
|--------|-----------|
| 400 | The new password is the same as the current one |
| 403 | `current_password` is wrong |
| 429 | Too many attempts |

#### POST /auth/forgot-password

**Public.** Body: `email`. Always returns `{"sent": true}`.

The response is identical whether the address has an account, whether the mail
sent, and whether it was never real. There is no self-serve signup here, so an
address with an account is one the operator chose to let in, and confirming
which is worth having to anyone probing. The rate limit is charged *before* the
lookup for the same reason — charging only on a match would make the limiter
itself an oracle.

Rate limited to 5 per address and 15 per client per hour. A **503** means the
deployment has no mail configured, or the token could not be stored; neither
answer depends on the address, so reporting them leaks nothing.

#### POST /auth/reset-password

**Public.** Body: `token`, `new_password` (min 12). Returns
`{access_token, token_type}`, so somebody who has just proved they control the
mailbox lands signed in rather than retyping the password they set ten seconds
ago.

A single **400** covers expired, already used, superseded and never-real — one
answer on purpose, since telling them apart tells whoever holds a stale link
something about the account it came from.

Links live one hour, work once, are stored only as a SHA-256 of the token, and
are revoked by any password change.

---

### GET /auth/me

**Description:** Returns the profile of the currently authenticated user.

**Auth required:** Yes

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique user ID (MongoDB ObjectId as string) |
| email | string | User's email address |
| display_name | string | User's display name |
| access_tier | string | `BASIC`, `PRO` or `TRADER` |
| is_admin | boolean | Whether this address is the configured operator |
| entitlements | object | What this account may do, resolved by the server |

`entitlements` is the whole resolved object — `may_trade`, `may_spend_tokens`,
`may_bring_own_key`, `may_use_server_key`, `may_enrol_in_nightly_research` and
`watchlist_cap` (`null` = unlimited). **Clients read these booleans; they never
map a tier name to a feature or restate a cap.** A new tier, or a retuned
default, then needs no client change. It is the same rule `/analyze` follows by
returning `breakdown` and `gate` from the engine rather than letting the UI keep
its own copy of the weights.

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /auth/me
// Response 200
{
  "id": "64a1f2b3c4d5e6f7a8b9c0d1",
  "email": "trader@example.com",
  "display_name": "Alice Trader",
  "access_tier": "PRO",
  "is_admin": false,
  "entitlements": {
    "tier": "PRO",
    "may_trade": false,
    "may_spend_tokens": true,
    "may_bring_own_key": true,
    "may_use_server_key": false,
    "may_enrol_in_nightly_research": false,
    "watchlist_cap": 15
  }
}
```

---

### PATCH /auth/me

**Description:** Updates the display name of the currently authenticated user.

**Auth required:** Yes

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| display_name | string | Yes | New display name to set |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| id | string | User ID |
| email | string | User's email address |
| display_name | string | Updated display name |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 422 | Missing `display_name` field |

**Example:**

```json
// PATCH /auth/me
// Request body
{
  "display_name": "Alice T."
}

// Response 200
{
  "id": "64a1f2b3c4d5e6f7a8b9c0d1",
  "email": "trader@example.com",
  "display_name": "Alice T."
}
```

---

### GET /ticker/search

**Description:** Searches for US common stock tickers by symbol or company name. Returns up to 10 matching results. Used to populate the ticker search UI.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| q | string | Yes | Search query (partial symbol or company name) |

**Response:** Array of objects:

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Stock ticker symbol (e.g., `"PLTR"`) |
| name | string | Company name (e.g., `"Palantir Technologies Inc."`) |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 422 | Missing required `q` parameter |

**Example:**

```json
// GET /ticker/search?q=palantir
// Response 200
[
  { "symbol": "PLTR", "name": "Palantir Technologies Inc." },
  { "symbol": "PLTM", "name": "Palanite Mining Corp." }
]
```

---

### GET /analyze

**Description:** Runs a full analysis on the specified ticker and returns a comprehensive `AnalyzeResponse` including price data, technical indicators, sentiment, macro context, signal score, and AI analyst output (if enabled). Results are cached; use `force_refresh=true` to bypass the cache and re-run ingestion.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| ticker | string | Yes | — | Stock ticker symbol (e.g., `PLTR`) |
| force_refresh | boolean | No | `false` | If `true`, bypasses cache and re-ingests all data |

**Response:** See [`AnalyzeResponse`](#analyzeresponse) model below.

**Error responses:**

| Status | Condition |
|--------|-----------|
| 400 | Invalid ticker symbol |
| 401 | Missing or invalid token |
| 404 | Ticker not found or no data available |
| 422 | Missing required `ticker` parameter |
| 503 | Upstream data source unavailable |

**Example:**

```json
// GET /analyze?ticker=PLTR&force_refresh=false
// Response 200
{
  "ticker": "PLTR",
  "company_name": "Palantir Technologies Inc.",
  "current_price": 24.57,
  "price_change_pct": 1.23,
  "signal": "BUY",
  "confidence": 0.78,
  "score": 72.4,
  "conviction": "HIGH",
  "thesis": "Strong institutional accumulation with bullish MACD crossover...",
  "technical": { ... },
  "sentiment": { ... },
  "macro": { ... },
  "last_updated": "2024-01-15T14:30:00Z"
}
```

---

### GET /backtest

**Description:** Runs a historical backtest for the specified ticker using the current signal model. Returns performance statistics over historical data. Requires the `ENABLE_BACKTESTING=true` environment variable to be set; returns 503 if backtesting is disabled.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol to backtest |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| ticker | string | The ticker that was backtested |
| total_signals | integer | Total number of signals generated in backtest period |
| win_rate | number | Fraction of signals that were profitable (0.0–1.0) |
| avg_return | number | Average return per signal (as decimal, e.g., 0.032 = 3.2%) |
| sharpe_ratio | number | Risk-adjusted return ratio |
| max_drawdown | number | Maximum peak-to-trough decline |
| signals | array | Array of individual backtest signal records |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 422 | Missing required `ticker` parameter |
| 503 | Backtesting is disabled (`ENABLE_BACKTESTING` not set to `true`) |

**Example:**

```json
// GET /backtest?ticker=PLTR
// Response 200
{
  "ticker": "PLTR",
  "total_signals": 47,
  "win_rate": 0.638,
  "avg_return": 0.034,
  "sharpe_ratio": 1.42,
  "max_drawdown": -0.087,
  "signals": [ ... ]
}
```

---

### GET /signals

**Description:** Returns a filtered, paginated list of the most recent signals across all watched tickers for the current user. Supports filtering by signal direction and minimum confidence threshold.

**Auth required:** Yes

**Query parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| signal | string | No | — | Filter by direction: `BUY`, `SELL`, or `HOLD` |
| min_confidence | number | No | `0.0` | Minimum confidence score (0.0–1.0) |
| limit | integer | No | `50` | Maximum number of signals to return (max 100) |

**Response:** See [`SignalListResponse`](#signallistresponse) below.

| Field | Type | Description |
|-------|------|-------------|
| signals | array | Array of `SignalRecord` objects |
| total | integer | Total number of matching signals (before limit) |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 422 | Invalid filter parameter value |

**Example:**

```json
// GET /signals?signal=BUY&min_confidence=0.5&limit=50
// Response 200
{
  "signals": [
    {
      "ticker": "PLTR",
      "signal": "BUY",
      "confidence": 0.78,
      "score": 72.4,
      "conviction": "HIGH",
      "generated_at": "2024-01-15T14:30:00Z"
    }
  ],
  "total": 1
}
```

---

### GET /signals/summary

**Description:** Returns an aggregated summary of all signals across the user's watchlist, including counts by direction and average confidence.

**Auth required:** Yes

**Response:** See [`SignalSummary`](#signalsummary) below.

| Field | Type | Description |
|-------|------|-------------|
| total | integer | Total number of active signals |
| buy_count | integer | Number of BUY signals |
| sell_count | integer | Number of SELL signals |
| hold_count | integer | Number of HOLD signals |
| avg_confidence | number | Average confidence across all signals |
| high_conviction | integer | Count of signals with conviction = `"HIGH"` |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /signals/summary
// Response 200
{
  "total": 5,
  "buy_count": 3,
  "sell_count": 1,
  "hold_count": 1,
  "avg_confidence": 0.65,
  "high_conviction": 2
}
```

---

### GET /signals/dip-buy

**Description:** Scans all tickers in the current user's watchlist and returns entry setups and exit alerts based on technical indicator thresholds. No pipeline run is triggered — results come from the latest cached `stocks_features` documents. Call `POST /analyze?ticker=X&force_refresh=true` first if you need fresh data for a specific ticker.

**Auth required:** Yes

**Query parameters:** None

**Entry criteria (all three must hold):**

| Indicator | Threshold | Meaning |
|---|---|---|
| RSI-14 | ≤ 45 | Not yet overbought |
| Stochastic RSI | ≤ 0.20 (20%) | Oversold momentum |
| Bollinger Band % | ≤ 0.35 (35%) | Near or below lower band |

**Exit alert criteria (either fires):**

| Indicator | Threshold | Meaning |
|---|---|---|
| RSI-14 | ≥ 70 | Overbought territory |
| Bollinger Band % | ≥ 0.90 (90%) | Near upper band |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| entry_candidates | `DipBuyCandidate[]` | Tickers matching all entry criteria, sorted most oversold first |
| exit_alerts | `DipBuyCandidate[]` | Tickers triggering exit criteria, sorted most overbought first |
| scanned | integer | Total number of watchlist tickers evaluated |

**`DipBuyCandidate` object:**

| Field | Type | Description |
|-------|------|-------------|
| ticker | string | Stock ticker symbol |
| current_price | number | Latest price |
| rsi_14 | number \| null | RSI over 14 periods |
| stoch_rsi | number \| null | Stochastic RSI (0–1 scale) |
| bb_pct | number \| null | Bollinger Band position (0 = lower band, 1 = upper band) |
| ma_20 | number \| null | 20-day moving average price |
| pct_from_ma20 | number \| null | % difference of current price from MA-20 (negative = below) |
| volume_anomaly | number \| null | Current volume / 20-day average volume ratio |
| technical_score | number | Composite technical sub-score (0–1) |
| trigger | string | `"ENTRY"` or `"EXIT_ALERT"` |
| computed_at | string (ISO 8601) | When the feature document was last computed |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /signals/dip-buy
// Response 200
{
  "entry_candidates": [
    {
      "ticker": "PLTR",
      "current_price": 21.40,
      "rsi_14": 38.2,
      "stoch_rsi": 0.12,
      "bb_pct": 0.18,
      "ma_20": 23.10,
      "pct_from_ma20": -7.4,
      "volume_anomaly": 1.45,
      "technical_score": 0.41,
      "trigger": "ENTRY",
      "computed_at": "2026-08-08T14:05:00Z"
    }
  ],
  "exit_alerts": [
    {
      "ticker": "NVDA",
      "current_price": 142.80,
      "rsi_14": 74.1,
      "stoch_rsi": 0.88,
      "bb_pct": 0.93,
      "ma_20": 128.50,
      "pct_from_ma20": 11.1,
      "volume_anomaly": 0.92,
      "technical_score": 0.78,
      "trigger": "EXIT_ALERT",
      "computed_at": "2026-08-08T14:05:00Z"
    }
  ],
  "scanned": 5
}
```

---

### GET /watchlist

**Description:** Returns all tickers in the current user's watchlist along with their latest cached signal data.

**Auth required:** Yes

**Response:** See [`WatchlistResponse`](#watchlistresponse) below.

| Field | Type | Description |
|-------|------|-------------|
| items | array | Array of `WatchlistItem` objects |
| count | integer | Total number of items in watchlist |
| cap | integer \| null | How many tickers this plan covers. `null` is unlimited; zero is a real cap. Returned so a client can show "7 of 15" and disable the add box before the request — the 403 from `POST /ticker` is the actual gate |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /watchlist
// Response 200
{
  "items": [
    {
      "ticker": "PLTR",
      "company_name": "Palantir Technologies Inc.",
      "current_price": 24.57,
      "signal": "BUY",
      "confidence": 0.78,
      "score": 72.4,
      "conviction": "HIGH",
      "added_at": "2024-01-10T09:00:00Z",
      "last_updated": "2024-01-15T14:30:00Z"
    }
  ],
  "count": 1
}
```

---

### POST /ticker

**Description:** Adds a ticker to the current user's watchlist and triggers background ingestion. The ticker must be a valid US common stock symbol.

**Auth required:** Yes

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol to add (e.g., `"AAPL"`) |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| ticker | string | The ticker symbol that was added |
| status | string | `"added"` if new, `"already_exists"` if already in watchlist |
| message | string | Human-readable confirmation message |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 400 | Invalid or unrecognized ticker symbol |
| 401 | Missing or invalid token |
| 422 | Missing `ticker` field in body |

**Example:**

```json
// POST /ticker
// Request body
{
  "ticker": "NVDA"
}

// Response 200
{
  "ticker": "NVDA",
  "status": "added",
  "message": "NVDA has been added to your watchlist and queued for analysis."
}
```

---

### DELETE /ticker/{ticker}

**Description:** Removes a ticker from the current user's watchlist. Does not affect other users who may also be watching the same ticker.

**Auth required:** Yes

**Path parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol to remove |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| message | string | Confirmation message |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 404 | Ticker not found in user's watchlist |

**Example:**

```json
// DELETE /ticker/NVDA
// Response 200
{
  "message": "NVDA has been removed from your watchlist."
}
```

---

### GET /report/{ticker}

**Description:** Returns the full `AnalystReport` for a specific ticker. The report includes the AI-generated thesis, conviction rating, key catalysts, risk factors, and price target (requires `ENABLE_AI_ANALYST=true`). If the AI analyst is disabled, returns the rule-based signal without narrative content.

**Auth required:** Yes

**Path parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol |

**Response:** See [`AnalystReport`](#analystreport) model below.

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 404 | No data available for the specified ticker |

**Example:**

```json
// GET /report/PLTR
// Response 200
{
  "ticker": "PLTR",
  "company_name": "Palantir Technologies Inc.",
  "signal": "BUY",
  "confidence": 0.78,
  "conviction": "HIGH",
  "thesis": "Palantir continues to demonstrate strong revenue growth driven by US commercial expansion...",
  "catalysts": [
    "AIP platform adoption accelerating among Fortune 500 companies",
    "US Government contract renewals with expanded scope"
  ],
  "risks": [
    "Valuation premium relative to peers",
    "Dependence on a small number of large government contracts"
  ],
  "price_target": 28.00,
  "generated_at": "2024-01-15T14:30:00Z"
}
```

---

### GET /performance

**Description:** Returns aggregate performance statistics for the current user's signal history, including win rate, average return, and Sharpe ratio computed from tracked signal outcomes.

**Auth required:** Yes

**Response:** See [`PerformanceResponse`](#performanceresponse) model below.

| Field | Type | Description |
|-------|------|-------------|
| total_signals | integer | Total number of signals with tracked outcomes |
| win_rate | number | Fraction of signals that resulted in positive returns |
| avg_return_20d | number | Average 20-day return per signal |
| best_signal | object | Best-performing signal record |
| worst_signal | object | Worst-performing signal record |
| by_ticker | object | Per-ticker breakdown of signal performance |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /performance
// Response 200
{
  "total_signals": 124,
  "win_rate": 0.61,
  "avg_return_20d": 0.028,
  "best_signal": {
    "ticker": "NVDA",
    "signal": "BUY",
    "return_20d": 0.31,
    "generated_at": "2023-10-15T10:00:00Z"
  },
  "worst_signal": {
    "ticker": "TSLA",
    "signal": "BUY",
    "return_20d": -0.14,
    "generated_at": "2023-11-02T10:00:00Z"
  },
  "by_ticker": {
    "PLTR": { "win_rate": 0.70, "avg_return": 0.041, "count": 20 },
    "NVDA": { "win_rate": 0.75, "avg_return": 0.058, "count": 16 }
  }
}
```

---

### GET /performance/signals

**Description:** Returns the last 100 individual signal history records for the current user, ordered by generation time descending. Each record includes the 20-day return outcome if available.

**Auth required:** Yes

**Response:** Array of `SignalRecord` objects (up to 100):

| Field | Type | Description |
|-------|------|-------------|
| ticker | string | Stock ticker symbol |
| signal | string | Signal direction: `BUY`, `SELL`, or `HOLD` |
| confidence | number | Confidence score at time of signal (0.0–1.0) |
| score | number | Composite score at time of signal (0–100) |
| conviction | string | `"HIGH"`, `"MEDIUM"`, or `"LOW"` |
| generated_at | string | ISO 8601 timestamp when signal was generated |
| return_20d | number \| null | Actual 20-day return; `null` if not yet available |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /performance/signals
// Response 200
[
  {
    "ticker": "PLTR",
    "signal": "BUY",
    "confidence": 0.78,
    "score": 72.4,
    "conviction": "HIGH",
    "generated_at": "2024-01-15T14:30:00Z",
    "return_20d": 0.052
  },
  {
    "ticker": "AAPL",
    "signal": "HOLD",
    "confidence": 0.55,
    "score": 51.2,
    "conviction": "LOW",
    "generated_at": "2024-01-14T14:30:00Z",
    "return_20d": null
  }
]
```

---

### GET /alerts/settings

**Description:** Returns the current user's alert notification settings, including which channels are enabled and what thresholds trigger alerts.

**Auth required:** Yes

**Response:** See [`AlertSettings`](#alertsettings) model below.

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |

**Example:**

```json
// GET /alerts/settings
// Response 200
{
  "email_enabled": true,
  "email_address": "trader@example.com",
  "slack_enabled": false,
  "slack_webhook_url": null,
  "min_confidence_threshold": 0.65,
  "signal_types": ["BUY", "SELL"],
  "conviction_filter": ["HIGH"],
  "quiet_hours_start": "22:00",
  "quiet_hours_end": "07:00"
}
```

---

### PUT /alerts/settings

**Description:** Updates the current user's alert notification settings. Replaces all settings with the provided values.

**Auth required:** Yes

**Request body** (`application/json`): See [`AlertSettings`](#alertsettings) model.

**Response:** Updated `AlertSettings` object.

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 422 | Validation error (invalid threshold, malformed webhook URL, etc.) |

**Example:**

```json
// PUT /alerts/settings
// Request body
{
  "email_enabled": true,
  "email_address": "trader@example.com",
  "slack_enabled": true,
  "slack_webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX",
  "min_confidence_threshold": 0.70,
  "signal_types": ["BUY"],
  "conviction_filter": ["HIGH", "MEDIUM"],
  "quiet_hours_start": "23:00",
  "quiet_hours_end": "06:00"
}

// Response 200
{
  "email_enabled": true,
  "email_address": "trader@example.com",
  "slack_enabled": true,
  "slack_webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX",
  "min_confidence_threshold": 0.70,
  "signal_types": ["BUY"],
  "conviction_filter": ["HIGH", "MEDIUM"],
  "quiet_hours_start": "23:00",
  "quiet_hours_end": "06:00"
}
```

---

### POST /alerts/test

**Description:** Sends a test notification through all currently enabled alert channels. Useful for verifying that webhook URLs and email settings are correctly configured before relying on them for real signals.

**Auth required:** Yes

**Request body:** None required.

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| status | string | `"sent"` if all channels succeeded, `"partial"` if some failed, `"failed"` if all failed |
| channels | object | Per-channel result map (key: channel name, value: `"ok"` or error message) |

**Error responses:**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid token |
| 400 | No alert channels are enabled |

**Example:**

```json
// POST /alerts/test
// Response 200
{
  "status": "sent",
  "channels": {
    "email": "ok",
    "slack": "ok"
  }
}

// Response 200 (partial failure)
{
  "status": "partial",
  "channels": {
    "email": "ok",
    "slack": "Invalid webhook URL"
  }
}
```

---

### Admin

Every route below is under `/admin` and requires the address configured in
`ADMIN_EMAIL`. **Being `TRADER` is not being the operator** — the highest tier
is a customer. There is no `is_admin` field on the user document, so no request
body can grant it.

No response on this router has a field capable of holding a `password_hash` or
a key ciphertext; that is a type-level guarantee, not a deletion before
serialising.

#### GET /admin/users

Every account: `id`, `email`, `display_name`, `created_at`, `access_tier`,
`watchlist_cap_override` (the operator's per-user value, or `null`),
`watchlist_cap` (what it resolves to), `watching`, `research_enabled`,
`research_daily_allowed`, `llm_key_count`, `is_admin`.

#### POST /admin/users

Creates an account. Body: `email`, optional `display_name`, `access_tier`
(defaults `BASIC`), optional `watchlist_cap`, `research_daily_allowed`, and an
optional `password` — omit it and one is generated.

Returns `{ "user": AdminUserRow, "password": string | null }`. **`password` is
populated only when this call generated it, and only on this response.** It is
never stored in plaintext, never logged, and no route can read it back.

| Status | Condition |
|--------|-----------|
| 201 | Created |
| 409 | That email already has an account |

#### PATCH /admin/users/{user_id}

Body: any of `access_tier`, `watchlist_cap`, `clear_watchlist_cap` (a separate
boolean because `watchlist_cap: null` is indistinguishable from "not supplied"
in a PATCH), `research_daily_allowed`. Query: `force`.

Downgrading an account out of trading while it holds open positions returns
**409** naming the tickers, because it removes the interface that closes them.
`?force=true` proceeds and logs at warning. Nothing rewrites
`auto_trade_settings` to tidy up: `_prepare_entry` already refuses new entries
and `execute_exit` still works, so the positions stay closable by the agent —
what is lost is closing them by hand, which is worth stopping to say.

A downgrade that removes nightly-research eligibility also clears
`llm_settings.research_enabled` in the same write.

#### POST /admin/users/{user_id}/password

Sets a new password and returns it once, as `{email, password}`. Body: an
optional `password`; omit it and one is generated.

No current password is asked for — the situation this exists for is that nobody
has it — which makes it the most powerful route on the API. **Every session
that account had dies here**, including the one being reset because it was
compromised. The password is never stored in plaintext and never logged; the
log line records that a reset happened and for whom, which is what an audit
needs.

#### GET /admin/access-requests

Contact-form submissions, newest first. Read-only: provisioning is the action,
and it shows up in `GET /admin/users`. Rows age out after 180 days via a TTL
index.

**There is no delete and no password reset.** A user document is referenced by
rows in `watched_tickers`, `trades`, `research_dossiers` and the per-user signal
series, none of which cascade — shipping half a cascade is worse than shipping
none. A forgotten password means recreating the account.

---

### POST /contact

The only unauthenticated write, and the only unauthenticated insert. Rate
limited to 3 per address per hour, counting every submission.

Body: `name`, `email`, `message`, optional `company` (a honeypot — anything in
it returns a normal success and records nothing), and optional `interest`, one
of `read` / `research` / `trade`. Deliberately not plan names: a stranger has no
idea what `PRO` means, and naming plans on a page with no prices invites a
question the page cannot answer.

Returns `{"sent": true}`. A **502** means the message was not delivered — this
is the one mail path that reports failure rather than swallowing it. The
`access_requests` row is written first and never fails the request, but a
successful write never masks a failed send.

---

## Data Models

### AnalyzeResponse

Full analysis output returned by `GET /analyze`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol |
| company_name | string | Yes | Full company name |
| current_price | number | Yes | Latest closing price (USD) |
| price_change_pct | number | Yes | 1-day price change as percentage |
| signal | string | Yes | `"BUY"`, `"SELL"`, or `"HOLD"` |
| confidence | number | Yes | Signal confidence (0.0–1.0) |
| score | number | Yes | Composite score (0–100) |
| conviction | string | Yes | `"HIGH"`, `"MEDIUM"`, or `"LOW"` |
| thesis | string \| null | No | AI-generated investment thesis (requires `ENABLE_AI_ANALYST=true`) |
| technical | object | Yes | Technical indicator snapshot (see below) |
| sentiment | object | Yes | News and social sentiment summary (see below) |
| macro | object | Yes | Macro environment context (see below) |
| ml_score | number \| null | No | XGBoost model score (requires `ENABLE_ML_MODEL=true`) |
| last_updated | string | Yes | ISO 8601 timestamp of last data ingestion |

**technical sub-object:**

| Field | Type | Description |
|-------|------|-------------|
| rsi_14 | number | RSI(14) value |
| macd | number | MACD line value |
| macd_signal | number | MACD signal line value |
| macd_histogram | number | MACD histogram value |
| sma_20 | number | 20-day simple moving average |
| sma_50 | number | 50-day simple moving average |
| ema_12 | number | 12-day exponential moving average |
| ema_26 | number | 26-day exponential moving average |
| bb_upper | number | Bollinger Band upper band |
| bb_lower | number | Bollinger Band lower band |
| atr_14 | number | Average True Range (14) |
| volume_ratio | number | Current volume vs. 20-day average volume |
| price_vs_sma20 | number | Price relative to SMA20 as decimal |
| price_vs_sma50 | number | Price relative to SMA50 as decimal |

**sentiment sub-object:**

| Field | Type | Description |
|-------|------|-------------|
| overall_score | number | Composite sentiment score (-1.0 to 1.0) |
| news_score | number | News article sentiment score |
| article_count | integer | Number of news articles analyzed |
| positive_count | integer | Number of positive articles |
| negative_count | integer | Number of negative articles |

**macro sub-object:**

| Field | Type | Description |
|-------|------|-------------|
| fed_rate | number \| null | Current federal funds rate (%) |
| cpi_yoy | number \| null | CPI year-over-year inflation (%) |
| unemployment | number \| null | Current unemployment rate (%) |
| gdp_growth | number \| null | GDP growth rate (%) |
| macro_score | number | Composite macro environment score (-1.0 to 1.0) |

---

### WatchlistItem

Represents a single item in a user's watchlist with its latest signal.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol |
| company_name | string | Yes | Full company name |
| current_price | number \| null | No | Latest price; null if not yet ingested |
| price_change_pct | number \| null | No | 1-day price change percentage |
| signal | string \| null | No | Latest signal direction; null if not yet analyzed |
| confidence | number \| null | No | Latest confidence score |
| score | number \| null | No | Latest composite score |
| conviction | string \| null | No | `"HIGH"`, `"MEDIUM"`, or `"LOW"` |
| added_at | string | Yes | ISO 8601 timestamp when ticker was added to watchlist |
| last_updated | string \| null | No | ISO 8601 timestamp of last signal generation |

---

### AlertSettings

Notification preferences for a user.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| email_enabled | boolean | Yes | `false` | Whether email alerts are enabled |
| email_address | string \| null | No | `null` | Email address for alerts; required if `email_enabled=true` |
| slack_enabled | boolean | Yes | `false` | Whether Slack webhook alerts are enabled |
| slack_webhook_url | string \| null | No | `null` | Slack incoming webhook URL; required if `slack_enabled=true` |
| min_confidence_threshold | number | Yes | `0.5` | Minimum confidence required to trigger an alert (0.0–1.0) |
| signal_types | array[string] | Yes | `["BUY","SELL","HOLD"]` | Which signal directions trigger alerts |
| conviction_filter | array[string] | Yes | `["HIGH","MEDIUM","LOW"]` | Which conviction levels trigger alerts |
| quiet_hours_start | string \| null | No | `null` | Start of quiet period (HH:MM, 24h format); no alerts sent in this window |
| quiet_hours_end | string \| null | No | `null` | End of quiet period (HH:MM, 24h format) |

---

### PerformanceResponse

Aggregate performance metrics for a user's signal history.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| total_signals | integer | Yes | Total signals with tracked 20-day outcomes |
| win_rate | number | Yes | Fraction of signals that resulted in positive 20-day returns |
| avg_return_20d | number | Yes | Average 20-day return across all tracked signals |
| best_signal | SignalRecord \| null | No | Highest-return signal record |
| worst_signal | SignalRecord \| null | No | Lowest-return signal record |
| by_ticker | object | Yes | Map of ticker to `{win_rate, avg_return, count}` |
| computed_at | string | Yes | ISO 8601 timestamp when metrics were computed |

---

### SignalRecord

An individual signal event, stored in `stocks_signal_history`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol |
| signal | string | Yes | `"BUY"`, `"SELL"`, or `"HOLD"` |
| confidence | number | Yes | Confidence score at time of signal (0.0–1.0) |
| score | number | Yes | Composite score at time of signal (0–100) |
| conviction | string | Yes | `"HIGH"`, `"MEDIUM"`, or `"LOW"` |
| hour_bucket | string | Yes | Truncated timestamp used for deduplication (1-hour granularity) |
| generated_at | string | Yes | ISO 8601 timestamp when signal was generated |
| return_20d | number \| null | No | Actual 20-day price return; populated after 20 trading days |

---

### AnalystReport

Full AI analyst output for a ticker. Extends the basic signal with narrative content.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| ticker | string | Yes | Stock ticker symbol |
| company_name | string | Yes | Full company name |
| signal | string | Yes | `"BUY"`, `"SELL"`, or `"HOLD"` |
| confidence | number | Yes | Signal confidence (0.0–1.0) |
| conviction | string | Yes | `"HIGH"`, `"MEDIUM"`, or `"LOW"` |
| thesis | string \| null | No | Full AI-generated investment thesis paragraph(s) |
| catalysts | array[string] | No | List of near-term bullish or bearish catalysts |
| risks | array[string] | No | List of key risk factors |
| price_target | number \| null | No | AI-estimated 12-month price target (USD) |
| technical_summary | string \| null | No | Brief AI narrative on technical setup |
| sentiment_summary | string \| null | No | Brief AI narrative on news sentiment |
| macro_summary | string \| null | No | Brief AI narrative on macro context |
| generated_at | string | Yes | ISO 8601 timestamp when report was generated |

---

### SignalListResponse

Wrapper object returned by `GET /signals`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| signals | array[SignalRecord] | Yes | Array of matching signal records |
| total | integer | Yes | Total count before `limit` was applied |

---

### SignalSummary

Aggregate counts returned by `GET /signals/summary`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| total | integer | Yes | Total active signals across watchlist |
| buy_count | integer | Yes | Number of `BUY` signals |
| sell_count | integer | Yes | Number of `SELL` signals |
| hold_count | integer | Yes | Number of `HOLD` signals |
| avg_confidence | number | Yes | Average confidence score across all signals |
| high_conviction | integer | Yes | Count of signals with conviction = `"HIGH"` |

---

### WatchlistResponse

Wrapper object returned by `GET /watchlist`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| items | array[WatchlistItem] | Yes | All watchlist items with latest signals |
| count | integer | Yes | Total number of items in the watchlist |

---

## Rate Limits

The backend enforces sequential data ingestion to avoid hammering upstream APIs. The following limits apply per data source:

| Source | Limit | Notes |
|--------|-------|-------|
| Yahoo Finance | ~1 request/second | No official rate limit; the backend serializes requests. Reduce `DEFAULT_TICKERS` count if seeing 429 errors. |
| Finnhub | 60 calls/minute | Free tier limit. Used for real-time news. Upgrade plan if watchlist exceeds ~20 tickers with frequent refresh. |
| FRED | 120 calls/minute | Free tier; limit is generous. Used for macro data (fed rate, CPI, unemployment, GDP). |
| Anthropic | Varies by plan | Used for AI analyst thesis generation. Rate limited by your API tier. Production builds should use Tier 2 or higher. |

**Recommendations:**

- Set `INGESTION_INTERVAL_MINUTES=30` or higher in production to stay well within Yahoo Finance limits.
- Do not add more than 30–40 tickers to a single user's watchlist when using the free Finnhub tier.
- The `/analyze?force_refresh=true` endpoint triggers immediate re-ingestion; use it sparingly in production.
