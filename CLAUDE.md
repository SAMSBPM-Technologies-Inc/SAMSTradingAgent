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

   **A verdict is not published until it holds.** Computing a signal and
   publishing one are different acts, and `services/signal_stability.py` sits
   between them. A changed verdict becomes a *candidate*: it publishes only
   after `SIGNAL_CONFIRMATIONS` consecutive **fresh evaluations** agree (cache
   hits confirm nothing) and the standing verdict has lasted
   `SIGNAL_MIN_DWELL_MINUTES`. `classify_signal` additionally takes the previous
   signal and applies a one-sided `SIGNAL_HYSTERESIS` band, so an established
   verdict is sticky while a new one still has to clear the full threshold.
   Omitting `previous_signal` gives the raw rule — that is what calibration
   replays want.

   **SELL is exempt from every delay**, the same asymmetry that makes BUY the
   only risk-gated verdict: delaying an exit costs money, delaying an entry
   costs an opportunity. Never add a brake to the exit path to make the two
   symmetrical.

   This exists because HXL alerted eight times in 65 minutes on 24 Aug 2026,
   alternating BUY/HOLD at an unchanged score of 0.61. Alerts fire on published
   *changes* only — an unconfirmed candidate is not news, and neither is a
   conviction that was already HIGH last cycle.

4. **AI Analyst** (`analyst.py`): Claude API generates structured JSON bull/bear report, cached per ticker with invalidation triggers (price change ≥3%, score change ≥0.12, VIX spike ≥30). The model is `ANALYST_MODEL` in `.env` (default `claude-sonnet-5` — see `config.py`); do not restate it in docs or UI, both read it from config via `AnalyzeResponse.analyst_model`.

   **The analyst may veto a BUY. It may never create one.** Same rule as deep
   research, on the path that actually places orders.
   `_gate_analyst_signal` reconciles the model's verdict against
   `classify_signal` before anything is published: a model BUY the rule refuses
   is published as HOLD, a model HOLD over a rule BUY passes through, and a
   SELL is never gated at any score — refusing to buy costs an opportunity,
   refusing to sell costs money. `previous_signal` reaches it from the
   pipeline, so both paths share one hysteresis band.

   This was missing until 1.22.0, and it was not theoretical.
   `analyst_gate_margin` is 0.08, so the analyst is called on exactly the band
   the rule declines — `[0.62, 0.70)` — and its answer was written into
   `stocks_signals` verbatim, then handed to `execute_entry`. Neither
   `BUY_THRESHOLD` nor `RISK_MAX_FOR_BUY` was applied, and neither is stated in
   the system prompt. AMZN was bought at 0.62 and CBRS at 0.66 on a risk score
   of 6.3, past a veto documented here as unconditional.

   Three properties are load-bearing. `analyst_output` keeps the model's own
   answer **unrewritten** — it is the only evidence the override can be judged
   from later. `analyst_gate` is written **whenever the analyst ran**, agreeing
   or not, because "the gate ran and agreed" and "no gate ran" are different
   facts and only one can be argued from (the `citation_audit` rule). And every
   derived field — entry suggestion, exit suggestion, explanation, confidence —
   describes the **published** verdict, or a refused BUY prints a full buy plan
   with a stop and a target underneath a HOLD.

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
   them (the account's plan, CIRO, the risk gate, position cap, daily-loss kill
   switch, cash reserve, refusal to open unbracketed). `execute_entry` and
   `execute_manual_entry` both go through it — do not add a guard to one path
   only. A manual order differs in exactly three documented ways: no
   signal-score threshold (the human is the signal), no whitelist, and no risk
   gate — the last two restrict what the *agent* may pick, and the order ticket
   already tells the user in as many words that they may place a vetoed name
   themselves. The research veto is the one that refuses a hand-placed order
   too.

   **`RISK_MAX_FOR_BUY` is checked where orders are placed, not only where
   verdicts are classified.** It used to live solely inside `classify_signal`,
   which guarded the rule's verdict and nothing else — so any BUY that reached
   `execute_entry` without having been produced by that rule was never
   risk-checked at all. The analyst path published exactly such BUYs (see
   `_gate_analyst_signal`). `_risk_veto` assesses the **live** feature document,
   because the question is whether the exposure is safe to take on now, and it
   applies to adds as well as first entries. Uncertainty allows the trade, as
   with research. Fixing this at the analyst alone would have been the same
   mistake as shipping only the `/trading` router gate: one gate that another
   caller can route around is not a gate.

   The plan check is **first**, because it answers "may this account trade at
   all" rather than "is this trade sound", and it is the only guard here that a
   route dependency could not have covered — `pipeline._execute_trades` reaches
   `execute_entry` on the 5-minute cycle without a request. It is deliberately
   **absent from `execute_exit`**, which does not run this chain: a downgraded
   account's open positions must stay closable. See the Authentication section.

   **A stop protects a position; a bracket only protects an order.** That
   distinction is the whole of scale-in. A `BUY` on a held ticker adds to the
   existing position record — never a second record, because `execute_exit`
   loads exactly one and would orphan the rest. The add goes out **unbracketed**
   and the existing legs are **left working**; `reconcile_trades` then cancels
   them and places one OCA pair (`place_protective_orders`) sized to what the
   venue says is held. Two rules must not be broken: protective orders may never
   cover more shares than are held (that sells into a short), and an add may
   never loosen the stop already on the holding. `position_size_pct` caps the
   *position* and is measured on cost basis, so a falling price cannot free up
   room to average down. Same guard chain as any other entry — see
   `_prepare_entry`. Verify with `runbooks/scale-in-paper-verification.md`.

   **An order costs money to place, so order count is a risk of its own.** A
   standing `BUY` re-runs `_prepare_entry` every 5-minute cycle — deliberate,
   because a skip for "gateway down" must retry — which means every add
   condition is really a *rate* limit. Three bound it: an add must be
   `SCALE_IN_DIP_PCT` below blended cost (being above the stop is a reason not
   to panic, not a reason to buy), `MAX_SCALE_INS` caps adds per position, and
   `MIN_ADD_FRACTION` refuses an add that moves the holding too little to carry
   its commission.

   **The fee limits apply to adds, not to opening entries**, and that asymmetry
   is the point. An entry has no alternative — refuse it and there is no
   position — so a flat floor there just silences a small account and makes the
   agent look broken. An add's alternative is doing nothing, so it must earn its
   ticket. `MIN_ADD_FRACTION` is a fraction of the holding rather than a dollar
   figure so it scales with the account; `MIN_ORDER_NOTIONAL` is an absolute
   floor across all entries, off by default, for when the account outgrows that.
   Neither **rounds an order up** to clear itself — that would let a fee rule
   override the position cap — and neither touches exits, because closing a
   position must never be blocked.

   **The equity the position cap is measured against is frozen at entry**
   (`size_basis_equity`), for the same reason the holding is measured at cost.
   Read live, the cap drifts up all session and hands a full position a share
   or two of fresh room every few minutes, which the retry loop spends at once.
   That, not a broken guard, is how NVDA took eight orders on 25 Aug 2026 with
   seven of them for one or two shares.

   **Client quantities are requests.** `POST /trading/order` takes the smaller
   of the requested qty and what the risk model sizes to, so sizing cannot be
   escaped from a form field. Orders carry an `idempotency_key` — the unique
   sparse index on `(user_id, idempotency_key)`, not the route's lookup, is what
   stops a double-clicked Buy from buying twice. Live-money orders require
   `confirm_live`, which the UI sets only after the user types the ticker back.

6. **Deep Research** (`services/research/`): a second, slower path — **on
   demand and once a day, never on the 5-minute pipeline.** `dossier.py` builds
   an evidence ledger, fans out four scoped agents with `asyncio.gather`, then
   synthesises. Off unless `RESEARCH_AGENTS_ENABLED=true`.

   **A claim without a citation is deleted, not flagged.** Every fact enters
   `evidence.py` with an id, value, source and date; agents cite ids; anything
   uncited is stripped before storage, and a *fabricated* id is stripped and
   recorded. `Ledger.add` refuses a `None` value for the same reason — an
   "unknown" entry would get an id and an agent would cite it. This is the same
   instinct as `explain_score` refusing to decompose an XGBoost score.

   **The removal is provable, not asserted.** `citation_audit` on
   `ResearchDossier` carries what was actually dropped and what was fabricated
   — present whenever a report exists, `None` only when there was none to
   filter. It used to live inside `report` under `_`-prefixed keys that
   `ResearchReport` had no field for, so Pydantic silently discarded it at the
   API boundary; a clean-looking report and a checked-and-found-nothing report
   were indistinguishable from outside a log line or the raw Mongo document.

   **The Risk agent runs in the fan-out and is not shown the bull case.** Given
   a thesis, a red team argues against *that thesis* and inherits its framing;
   the previous single analyst wrote both sides in one pass and produced a bear
   case shaped to fit its own bull case. The synthesiser must then **address or
   carry every risk it raised** — never silently drop one.

   **Five of the six dimension scores are Python, not model output.** Only
   `business_quality` is model-judged, and it is flagged. A headline number
   that cannot be reproduced or regression-tested is decoration. Higher is
   better on all six, `risk` included, where it means safer. Conviction is
   blended from those scores; the model may move it ±15 and must explain why.

   **The client is injectable** (`build_dossier(..., client=)`) so the
   orchestration is testable without the SDK — the analyst call this replaces
   built its client inline and has no tests to this day.

   **Research may veto a BUY. It may never create one, enlarge one, or reach an
   exit.** `_research_veto` lives inside `_prepare_entry` with the other
   guards; `execute_exit` does not run that chain. Every uncertain path —
   missing dossier, stale, undated, database error — **allows the trade**. A
   guard that halts buying when a cron job misfires is a worse failure than one
   that occasionally lets a trade through.

   **The veto is reported before it is tripped.** The judgement is a pure
   function in `services/research/veto.py` over a dossier and the settings, so
   the same reading that refuses an order explains itself on the ticker page —
   in the dossier panel and on the order ticket, via `GET /research/{ticker}/veto`.
   It was previously discoverable only by placing an order and reading the
   refusal afterwards on a SKIPPED trade row. `blocking` and `would_block` are
   **separate fields and must stay separate**: `RESEARCH_VETO_ENABLED` is off by
   default, so on most deployments the true statement is "research would refuse
   this if you switched the veto on", which is exactly the fact needed to decide
   whether to switch it on. Note the asymmetry the UI must state: the risk gate
   restricts what the *agent* may pick and a human can override it, but the veto
   is in the shared guard chain and **refuses a manual order too**.

   **Two things were both called `conviction`; they are not the same number.**
   The analyst's is `HIGH`/`MEDIUM`/`LOW` and gates unattended execution
   (`may_auto_execute`); research's is 0–100 and feeds the veto. Research's is
   `research_conviction` (anchor: `derived_research_conviction`) everywhere it
   leaves `services/research/` — stored document, API model, both clients. The
   model's own report JSON keeps the bare key, since that is what the prompt
   asks for, and `ResearchReport` deliberately does not re-expose it: one
   0–100 number at two depths of a response invites a client to read the
   unclamped one. `latest_dossier` normalises documents written under the old
   key; dossiers are a retained series, so those are still live. In UI copy,
   the analyst's is labelled "analyst conviction" wherever the word would
   otherwise stand alone.

   **Which model answers is the trader's choice.** `services/llm/` is the one
   seam — `base.py` (the `LLMResult` contract and the `ErrorKind` enum),
   `registry.py` (named providers, capability flags, per-provider
   `normalise_schema`), one adapter each for Anthropic/OpenAI/Google, and
   `resolver.py`. `run_agent` walks an ordered chain resolved from the user's
   `llm_settings`; **the server's own key is appended last to every chain the
   caller is entitled to reach it on** (`build_chain(..., allow_server_key=)`),
   so a trader who configures nothing still gets dossiers and a single-key
   deployment behaves exactly as it did before the seam existed. A tier that
   pays for its own tokens does not get that link: its chain is its keys and
   nothing else, so a key that fails mid-dossier fails the dossier rather than
   quietly moving the bill to the operator. The default is still `True`, which
   is what keeps every caller with no user behind it — the pipeline's analyst
   call above all — unchanged.

   **The fallback policy branches on `ErrorKind` and nothing else.** Auth,
   rate-limit, overload, timeout and refusal spend the next key; a 400, an
   unparseable body, or a truncation do not — the next provider would fail
   identically, at double the cost, with the real error buried. **Structured
   output is a gate, not a preference**: `analyst.py` had its fence-stripping
   regexes deleted on purpose, and a provider that cannot enforce a schema
   would put them back. Keys are validated with a real schema-constrained call
   at save time and refused if they fail. Anthropic alone gets a hand-placed
   cache breakpoint; elsewhere the same dossier costs more, which is why
   `models_used` is recorded.

   **Dossiers are per-user.** `latest_dossier(ticker, user_id)` reads that
   reader's own, falling back only to the legacy shared series (documents with
   no `user_id`) and never to another user's. `prior_record.load_resolved` is
   scoped the same way and that one is load-bearing: it renders into the ledger
   as citable `O` evidence about how *this desk* read a name, and unscoped it
   leaks one trader's graded record into another's prompt. The daily jobs reach
   only users with `llm_settings.research_enabled` **and a plan that allows it**
   — `research_enabled` defaults false, and on a PRO account the nightly job
   additionally needs the operator's `research_daily_allowed` grant. Research is
   five to seven calls per ticker per day and is the one cost here that
   multiplies with users. The cohort filter uses `$in` over the enrolable
   tiers, **never `$ne: "BASIC"`**: `$ne` also matches documents where the field
   is *absent*, which is every account predating the migration, so a failed
   migration plus a `$ne` would enrol everybody rather than nobody.

   **The desk's own record is evidence, not injected prose.** `outcomes.py`
   grades every dossier ~20 days on (`RESEARCH_OUTCOME_HORIZON_DAYS`) against
   forward **alpha**, then writes a short lesson that must cite ids from *that
   dossier's own stored ledger* — uncited prose is deleted and a fabricated id
   recorded, like any report. `prior_record.py` then feeds settled readings
   back as `O`-prefixed ledger items, shown to all four specialists and the
   synthesiser. Three properties are load-bearing: items are `meta=True` so a
   track record cannot make a name researchable; only *resolved* readings are
   shown, since an unsettled one is a prediction with no ground truth; and
   **nothing here reaches `derived_research_conviction`**, which is arithmetic
   over company data alone. Memory can temper a reading; the ±15 clamp means it
   can never manufacture one. Correctness is judged on alpha — NEUTRAL and
   unmeasurable windows score `None`, never a miss.

   **The Risk agent is answered exactly once, after both sides have written.**
   `RISK_REBUTTAL` and `DEFENCE_REBUTTAL` (`RESEARCH_DEBATE_ROUNDS`, default 1)
   run after the fan-out, never before: a debate whose second speaker reacts to
   the first inherits its framing, which is the anchoring the unanchored
   fan-out exists to prevent. One exchange, because successive rounds converge
   on agreement and that reads as resolution without being any. Both sides are
   citation-filtered and argue over byte-identical material.

   **The stance panel is advisory and must stay that way.** Three temperaments
   read the *trade* rather than the company (`RESEARCH_STANCE_PANEL_ENABLED`,
   off). Nothing in `_prepare_entry` reads them and no quantity moves because of
   them — a test asserts no stance token reaches `trade_manager.py`. This is the
   one idea from TradingAgents deliberately not adopted: its portfolio-manager
   agent decides the position, and deterministic sizing on frozen equity is why
   the same inputs produce the same order twice.

   **Earnings proximity is an additive catalyst bonus, not a fourth weighted
   component.** As a component its absence would cost coverage, and coverage is
   a penalty — so every ticker past the Alpha Vantage daily cap would score on
   a narrower range than one inside it, for a reason unrelated to the company.

   **`financial_statements` only ever gains rows.** `stocks_fundamentals` is
   replaced wholesale on every refresh, which is why no trend could ever be
   computed from it. Do not "simplify" the series back into the snapshot.

### MongoDB Collections

| Collection | Purpose |
|---|---|
| `users` | Accounts, JWT, `access_tier` + `watchlist_cap` + `research_daily_allowed`, per-user scoring weights, alert settings, `llm_settings` (Fernet-encrypted provider keys + role chains) |
| `stocks_raw` | Latest OHLCV + sentiment per ticker |
| `stocks_features` | Technical/fundamental/sentiment/macro/catalyst scores |
| `stocks_signals` | Latest BUY/SELL/HOLD per ticker (per-user aware) |
| `stocks_signal_history` | Historical signals for performance tracking + ML retraining |
| `watchlists` | Per-user ticker lists |
| `trades` | Auto-trading order records |
| `performance_stats` | Signal accuracy, win rates per ticker |
| `financial_statements` | Accumulated filings per (ticker, period, timeframe) — append-only, the basis for every trend |
| `earnings_history` | Reported vs estimated EPS, surprise record, next report date |
| `research_dossiers` | Deep-research output **per user**, retained as a series; `outcome` added on settlement. Documents with no `user_id` are the pre-1.14 shared series |
| `access_requests` | Contact-form submissions, so provisioning is a queue rather than an inbox search. Bounded by a 180-day TTL as well as by the per-address rate limit |
| `password_resets` | Outstanding reset links, stored as a SHA-256 of the token and never the token itself. Single-use, one-hour expiry, TTL-swept |

### Authentication and access tiers

JWT-based auth. Three named access tiers on `users.access_tier` — **BASIC**
(the portal as a reader), **PRO** (research and full analysis runs, on their own
provider key, no broker surface at all), **TRADER** (everything). A numeric 0–3
ladder and an admin portal were removed in `f61066f7`; this is deliberately not
that. Capabilities are **named**, in one table in `services/entitlements.py`,
and **routes name capabilities rather than tiers** — `tier >= n` is the numeric
system coming back through the side door. The field is `access_tier` because
`CapabilityStatus.tier` already means something else.

**Two gates, and neither is sufficient alone.** The `/trading` router carries
`Depends(require_trading)`, which covers all fifteen handlers and every one
added later. But `pipeline._execute_trades` runs on the 5-minute cycle, loads
every watcher of a ticker and calls `execute_entry` directly — no request, no
dependency — so the plan check is also the **first guard in `_prepare_entry`**,
which both entry paths share. Without it a downgraded `mode=AUTO` account keeps
placing orders on the operator's brokerage account forever with its UI hidden.
It is deliberately **absent from `execute_exit`**: open positions must stay
closable. Shipping only the router gate is worse than shipping neither, because
it looks done.

**The tier is not in the JWT.** `get_current_user` loads the document on every
request anyway, and a claim would be stale for the token's whole 24-hour life —
so a downgrade would take effect whenever the user next signed in, which for a
control whose purpose is to stop a spend now is the wrong direction.

**Hiding a control is presentation; the server check is the gate.** Behind
`/trading` is *one* brokerage account, the operator's, so a missed route does
not leak a feature — it leaks balances, holdings and container control. Tests
assert only the server side, and `test_tier_routes.py` enumerates the app's own
route table rather than a hand-written list.

**BASIC cannot *initiate* a token spend, which is not the same as costing
nothing.** The shared pipeline's analyst call is deployment cost, attributed to
no user, and is bounded by the per-user ticker cap — which is why the cap
applies to BASIC too, not only to PRO. That cap, not a token budget, is the real
cost control here: every watched ticker joins the union `market_pipeline` runs
every five minutes, and `stocks_signals` is one shared document per ticker.
The check asks *"would this add a row"*, so re-adding a watched ticker at the
cap still succeeds; it accepts a benign over-by-one race under concurrent adds,
which the unique index does **not** prevent.

**Registration is closed and stays closed.** There is no register endpoint.
People ask through `POST /contact`, the operator provisions them at `/admin`
(or `scripts/create_user.py` for the first account — both build the document
through `services.auth.new_user_document` so they cannot drift). Admin identity
is `ADMIN_EMAIL` in config, **not a field on the user document**: a document
field would create a privilege-escalation path through the admin route itself,
where one careless `$set` of a request body turns an editable field into an
admin-granting one. It is deliberately not injected by the deploy workflow, for
the same reason `CONTACT_EMAIL` is not, and `main._check_admin_email` says so
loudly at startup — being *silently* locked out of provisioning is the failure
worth engineering against.

`db._migrate_access_tier` writes TRADER onto every account that predates the
field, because they were all provisioned with every feature. A document still
missing it afterwards resolves to **BASIC** — the migration's job is the known
population; anything else is a bug, and the safe reading of a bug is the small
one.

**A password is set in exactly one place.** `services.auth.password_update` is
the only thing that writes `password_hash`, and a test enforces that no route
does it directly. The reason is the field it also records:
`password_changed_at`, compared in `get_current_user` against an `iat` claim,
ends every session issued before the change. Without it a reset would rotate
the credential and leave a stolen token working for the rest of its 24 hours,
which is most of what resetting is for — and the omission would not fail
visibly, because the new password would work fine. A token with no `iat` fails
**closed** against a recorded change; an account that never changed its
password is untouched, which is what stops a deploy signing everybody out. Both
the self-service change and the reset hand back a fresh token, so the person
doing it stays signed in on that device while every other session dies.

**Recovery is shaped entirely by not enumerating accounts.** There is no
self-serve signup, so an address with an account is one the operator chose to
let in, and confirming which is a fact worth having to anyone probing.
`POST /auth/forgot-password` therefore returns the same body whether the lookup
matched, whether the mail sent, or whether the address was never real; the rate
limit is **charged before the lookup**, or the limiter itself becomes the
oracle; and redeeming gives one answer for expired, used, superseded and
never-real. The one thing reported honestly is a deployment with no mail
configured — that answer does not depend on the address, and silence would
leave somebody waiting for a message that was never coming.

**Only a hash of a reset token is stored.** A link sets a password without
knowing the old one, so a stored copy is as good as the credential — a dump, a
backup or a log line must not yield a working one. Plain SHA-256 rather than
bcrypt, deliberately: 256 bits from `secrets` has nothing to brute-force, and a
slow hash could not be looked up by value. Links are single-use via
`find_one_and_delete` (read-then-delete lets two requests race one link), carry
their expiry **in the query rather than a check after it**, and are revoked by
any password change so an old email cannot undo a new password.

### Frontend Route Structure

```
/               → HomePage when signed out, TradePage when signed in
/home           → HomePage (always — the public landing page)
/auth           → AuthPage (register/login)
/ticker/:sym    → TradePage, centre column = one name's analysis
/transaction/:id→ TradePage, centre column = one order's record + that ticker's history
/analysis/:sym  → AnalysisPage (the same report, no dashboard — "New window")
/search         → SearchPage (ticker lookup — analyse without watching first)
/performance    → PerformancePage (signal history, win rate)
/calibration    → CalibrationPage (do the thresholds hold up? see below)
/status         → StatusPage (what the engine is actually running on)
/settings       → SettingsPage (alerts, IBKR config, auto-trade, LLM keys)
/guide          → GuidePage (IB Gateway setup — Trader only)
/admin          → AdminPage (provisioning; the ADMIN_EMAIL address only)
/forgot-password → ForgotPasswordPage (public)
/reset-password  → ResetPasswordPage (public; reads ?token=)
/positions /holdings /orders /radar → redirect to /
/profile        → redirects to /settings
```

**The centre column is a routed region with three states, and none of them is a
modal.** `TradePage` renders `PositionsDashboard`, `TickerPanel` or
`TransactionDetail` depending on the route; the rail and the right-hand panels
are unchanged around it. The analysis used to be a sheet over the dashboard —
it stopped being one because the context a reader wants beside a record is
exactly what a backdrop hides. Do not reintroduce an overlay here. All three are
real URLs, so Back walks what was looked at.

**Reading a name and acting on it are separate columns.** The centre answers
"what is this and why"; `TickerActions` (Watch, Remove, Export, Run full
analysis) and the order ticket are the top of the right rail. Those four used to
be a row inside `TickerHeader`, between the verdict and the reasoning for it —
which put a control that spends an analyst call, and one that destroys a
watchlist row, directly in the path of a reader's eye. `TickerHeader` therefore
carries **no control at all**; keep it that way. The ticket sat at the bottom of
the centre column under a comment about not hiding behind a sheet — that reason
expired when the analysis stopped being a sheet. `TickerActions` is not gated on
`may_trade`: none of the four is a trading action. `/analysis/:symbol` has no
right column, so it renders the same component `layout="inline"`, without watch
and unwatch — mutating a list that window does not display would strand the
dashboard in the other window.

**The ticker page is a verdict, an argument, and then evidence on demand.**
Order under the header: the "Why" band, the two cases, the chart, then
everything else collapsed. `CasePanel` shows at most three analyst-written
bullets a side (`bull_points` / `bear_points`), with the prose, catalysts and
key risks behind a *Full case* toggle. **A client must never split the prose
into bullets** — which clause carried the argument is not something the view
layer knows — so an analysis stored before 1.20.0 shows its clamped paragraph
instead, the same refusal-to-fabricate as `explain_score` on the XGBoost path.
The chart is the one detail left open, because it is scanned rather than read.
Mobile mirrors this ordering in `app/ticker/[symbol].tsx`.

**The broker box is not on the ticker rail unless the session is down.** A
standing "IB Gateway connected" panel on a screen about one company is restated
on every ticker a reader opens, and `AccountBar` already carries a live dot for
it — the same reason `InputsChip` renders nothing when `overall === 'ok'`. When
`account.connected` is false it appears at the top of the rail with Reconnect
and Restart, because then it is the only thing there that can be acted on. It
reads the shared `useTradingSettings` account rather than polling
`/trading/broker/status` a second time.

**Reading is not analysing.** `GET /analyze?stored_only=true` returns the stored
verdict at *any* age and can never reach `run_pipeline`; that is what a ticker
click calls, on both clients. `force_refresh=true` is the explicit run and the
only thing behind the "Run full analysis" button. Plain `/analyze` keeps its old
stored-if-fresh-else-rebuild behaviour for the report export and the watchlist
warm-up. The negative property is the one worth protecting and is tested in
`backend/tests/test_stored_analysis.py` — a regression here does not fail
loudly, it just makes the app slow again in production.

**The price is separate from the verdict.** `GET /quote/{ticker}` is one Finnhub
call and the only source of the price shown on a ticker page — `current_price` on
a stored analysis is whatever it was when the pipeline last ran. It never 5xxs:
no key, an error or a timeout falls back to `stocks_raw` and reports
`source: "stored"`, which the UI must label. This is not a health probe and does
not contradict "observed, never probed" — that rule protects the Alpha Vantage
cap and answers "did this source build the score".

**One activity trail, not two.** `ActivityTable`
(`components/positions/ActivityTable.tsx`, mirrored by mobile's `ActivityList`)
replaced the separate "Agent positions" and "Order history" tables. Rows are
grouped by what a status *means* — Waiting on you / Active / Closed / Not taken
/ Unreconciled — and a PROPOSED row carries Approve and Reject. The live-money
gate must survive every path: a paper proposal resolves in the row, a live one
routes to the transaction page where the type-the-ticker input lives. All three
call sites share `ProposalActions`; there must never be a second implementation
of that confirmation.

**`tradeSource` mirrors the backend; `displaySource` is what a row reads.** A
PROPOSED or DECLINED record carries `signal_type: "BUY"`, so `tradeSource` calls
it `agent` — correct for `/performance/trades`, which buckets *executed* trades,
and wrong on screen, where "Agent" claims the tool acted without the trader. The
bucket key stays `approved`; the label is **"Semi"** everywhere, including the
Performance page, and means *the tool recommended it and you actioned it*. Note
what the data cannot say: a SEMI_AUTO trade the agent executed unattended is
indistinguishable from an AUTO one, because no trading mode is recorded per
trade.

**The landing page is the only public screen, and it knows nothing about
auth.** `sta.samsbpm.com` used to open on a password prompt, which tells a
first-time visitor nothing. `/` now branches in `App.tsx`: signed out renders
`HomePage`, signed in renders the dashboard unchanged. `HomePage` reads no
context and makes no request on load — the plan is to move it to its own public
host, so deleting that branch must be the whole of the migration. Its only call
is the contact form, and only on submit. Its claims are all things the engine
actually does; the sample readout is labelled a sample.

**It is set as a document, not built from cards.** Structure comes from a
numbered section grid and hairlines (`--home-rule`, one step lighter than
`--color-border`); the Discipline band is the only filled block, because that
section is the argument. There are no feature icons — an icon illustrating
nothing is decoration standing where a fact should be — no blur, and one static
warm wash behind the hero. Landing-only colours are `--home-*` tokens declared
in both theme blocks; the band inverts through its own pair rather than
swapping `--color-fg`, because a cream block is an accent in light mode and a
flashbang in dark.

**There is one drawing of what the system does.**
`scripts/render_pipeline_diagram.py` is its only source: geometry authored
once, both palettes derived, emitting `frontend/public/img/pipeline-{light,dark}.svg`.
The landing page swaps the two on the theme toggle, and the README and
`docs/02-architecture.md` embed the same files through `<picture>`. Edit the
script, never the SVGs — and keep its four stage names identical to the four
steps the landing page prints beneath it, which have disagreed once already.

**The identity lives in `components/Logo.tsx`.** `IconMark` and `LogoLockup`
were local to `Layout.tsx` while the app chrome was the only consumer; the
landing page was the second, and promptly drew its own gradient "S" that
matched nothing. Import them.

`AuthProvider` starts `isLoading` from whether a token is actually stored, not
`true` — otherwise every anonymous visitor paints a spinner for a frame before
the public page appears.

**`POST /contact` was the only unauthenticated write on the API**; password
recovery added two more (`/auth/forgot-password`, `/auth/reset-password`), and
all three are shaped by the same instinct — see *Authentication and access
tiers* for what recovery adds on top. Contact remains the only endpoint a
stranger can use to make the server mail *the operator*, and since it also
records an `access_requests` row, an unauthenticated insert.
Three rules come with the row: **a honeypot trip persists nothing** (filling the
queue with what the honeypot exists to absorb defeats the point of having one),
**a failed write never fails the request** (a dropped queue row is a lost
convenience, a dropped email is a lost person), and **a successful write never
masks a failed send** — the 502 stands, because that is the exact lie this
endpoint exists not to tell. Four things hold it:
a per-address rate limit that counts *every* submission (not just failures, as
login does — there is no submission that should not be charged for), a honeypot
field that returns a normal success so a bot learns nothing, length caps in the
schema, and the visitor's address in `Reply-To` rather than `From`, since
forging a From the SMTP provider has not authenticated is how a sending domain
dies. It is also the one mail path that **reports failure instead of swallowing
it** — elsewhere a mail outage must not stop trading, but a person told "sent"
when nothing was sent has been lied to and has no other route to anyone.
Delivery address is `CONTACT_EMAIL`, which defaults in `config.py` and is
deliberately not injected by the deploy workflow — `_set_key` writes `KEY=` for
an unset variable, and an empty recipient would turn every submission into a
502.

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

**Every realised return is measured against a benchmark.**
`services/benchmark.py` (`BENCHMARK_TICKER`, default SPY) is the only source;
settlement writes `benchmark_return_20d`/`alpha_20d` on signals and
`benchmark_return`/`alpha` on closed trades. **An alpha that cannot be computed
stays `None`, never `0.0`** — the `commission_paid` rule, for the same reason: a
zero benchmark reports the whole return as skill, flatteringly, every time the
market rose. Alpha carries its **own sample count** everywhere it is shown,
because history settled before this existed has a return and no alpha.

**Calibration reports; it does not tune.** `/calibration` renders
`GET /performance/calibration`: whether the score ranks outcomes, what each
candidate BUY cutoff would have returned, and whether stated confidence tracks
being right. Every row carries `n` and a `significant` flag — under
`MIN_SAMPLES_FOR_SIGNAL` (30) the UI marks it *thin* rather than showing a
confident-looking percentage. Do not add auto-tuning here.

`GET /performance/research-calibration` is scoped to the caller and
**segmented by `(provider, model)`** — pooling producers measures the mixture,
and a strong model averaged with a weak one yields a curve describing neither.
A `pooled` row is returned alongside, flagged `mixes_producers`, because the
segmented rows take far longer to reach `n`. It asks the same questions of the
research module — does conviction rank forward alpha, were the verdicts right, and
**would the veto have saved anything**. That last one is the number
`RESEARCH_VETO_ENABLED` should be argued from and nothing produced it before.
Same `n`/`significant` discipline, same refusal to tune.

**Charts.** `GET /chart/{ticker}` (PNG, mplfinance) is for report export only.
The web client draws from `GET /chart/{ticker}/series` with `lightweight-charts`,
lazy-loaded so the library stays off pages that have no chart. SMA-20/50 are
computed server-side so the PNG and the interactive chart cannot disagree.

**Health is observed, never probed — and "no key" is not "broken".** Two
invariants, and the next well-meaning change will break both.
`services/source_health.py` reads the `source` sentinel every fetch already
writes into `stocks_raw` (`finnhub+vader+finlex`, `no_api_key`, `error`,
`massive+alphavantage`, `pending`) and remembers it; `services/system_status.py`
turns those into `GET /system/status`. **A probe endpoint would spend the Alpha
Vantage budget it is reporting on** — 22 calls against a cap of 25 — and would
answer the wrong question: "can this container reach FRED now" is not "did FRED
build the macro factor behind that BUY". Passive health *is* provenance. The one
exception is the broker session, which is process state rather than a past fetch
and already has `GET /trading/broker/status`; compose the two client-side rather
than duplicating it.

`configured` (a key exists) is a separate field from the working `state`, and a
source with no key reports `not_configured`, never `failed` — the same
distinction `ResearchVetoStatus` draws between `enabled` and `would_block`.
Painting a deliberate absence red is how a status page becomes something nobody
opens twice. Every capability carries an `impact` line saying what its absence
costs; that table in `system_status.py` is the single source the page renders and
`docs/12-how-a-trade-is-judged.md` quotes, so the two cannot drift.

Two granularities, and they must not be confused. **"Is FRED up now" is global**
and comes from the health records. **"Was *this* verdict built on complete
inputs" is per-signal**, lives in `inputs` on the feature document, and is what
the ticker page shows — a source that failed at 09:35 and recovered at 10:00 is
still absent from the 09:35 report. Coverage is weight-independent and stored;
completeness weights it by *the reader's* weights and is computed at read time.
A completeness that cannot be computed stays `None`, never 1.0 — the
`commission_paid` rule. Freshness is judged against `is_market_hours()`: the
pipeline does not run overnight, and reporting that as an outage is the fastest
way to build a page nobody believes.

**Every order says why it was taken, and nothing says it that cannot be
checked.** `services/trade_rationale.py` writes the one line a trade record
carries to justify itself — entries, adds, proposals and score-driven exits
alike — and it is pure functions over the feature document and the effective
weights, never a model call. Three rules hold it honest, and all three are the
same rule `explain_score` follows: a factor is named on its **lift away from
neutral** (`weight × (score − 0.5)`), not its weight, or the heaviest weight
heads every reason ever written; the XGBoost path names no factor at all and
says so, because a weighted story about a model's output is a fabrication; and
the sentence **concedes the strongest factor arguing the other way**, since a
reason that only lists agreement reads as marketing. `entry_reason` and
`exit_reason` are separate fields answering separate questions, and both are
separate from `reason`, which says why an order was *not* placed. Only
`SELL_SIGNAL` exits get a drivers clause — an exit alert and a manual close
were not decided by the score.

**Gross is what the position did; net is what reached the account.** Every
trade accrues `commission_paid` from the venue's own execution reports — entry,
each scale-in add, and the exit — and `/performance/trades` reports net
alongside gross. Two rules hold the number honest. Accrual is **idempotent by
execution id** (`commission_exec_ids`), because reconcile re-reads a 24-hour
fill window every two minutes and a double-count would climb on its own for as
long as the app stayed up. And a commission the venue has not reported stays
`None`, never `0.0`: `commission_complete` gates whether `pnl_net` is written at
all, and unnettable trades surface as `net_unknown` rather than being folded in
at zero, which would understate cost in one direction every time. Trades closed
before 1.6.0 can never be netted — IB only serves the current session.
`wins_lost_to_fees` is the number the sizing thresholds should be argued from.

**Realised performance keeps three buckets apart** (`/performance/trades`):
`signal_driven` (agent placed it unattended — the only clean read of the
engine), `approved` (agent proposed, human accepted — biased by what the human
declined, so it measures the pair), and `manual` (human chose it). Never pool
them.

**`agent_originated` is the one exception, and it is additive.** It is
`signal_driven + approved` — every trade the *tool* picked, however it reached
the venue — and it exists because the dashboard's "Agent vs you" panel asks a
question the three cannot: whose ideas were better. For *that* question who
pressed the button is not part of it; for "does the engine work" it is
everything, which is why the original three are untouched and
`signal_driven` remains the only clean read. Two rules come with it: it is
named `agent_originated` rather than `agent` so nothing reads it as the
engine's report card, and **any surface showing it must also show the
auto/semi split it was built from**, because half of it is filtered by whatever
the trader declined.

**A dollar total cannot be compared across buckets; a rate can.** Each bucket
carries `capital_deployed`/`return_on_capital` and their `_net` twins. The
denominator is **turnover, not account size** — ten sequential $1,000 trades
deploy $10,000 — and every surface showing the rate must say so, or it gets
read as a return on the account. A trade whose basis cannot be known leaves
**both** sides of the ratio rather than just the denominator; keeping its P&L
in the numerator would inflate the return invisibly, in one direction, every
time. The basis is blended entry × filled qty, which is what `pnl` is computed
against, so a scaled-in position is divided by what it actually cost. Empty
stays `None`, never `0.0` — the `commission_paid` rule.

Key shared infrastructure: `AuthContext` (JWT persistence), `ThemeContext` (light/dark), `ToastContext` (`toast` / `toastWithUndo` — destructive actions defer their request for the length of the undo window), `lib/api.ts` (Axios with bearer token). The mobile app mirrors this structure using Expo Router.

**Mobile is at parity with web.** Order ticket, activity trail with inline
Approve/Reject, transaction detail (`app/transaction/[id].tsx`), the two-step
ticker view, chart, calibration, factor breakdown, risk gate, and holdings all
exist on both clients and must stay in step — particularly the two safety
behaviours: the displayed quantity is never authoritative (the server clamps
it), and a live-money order or approval requires the user to type the ticker
back.

Where the two clients differ, they differ for a reason worth stating. The mobile
activity card has room for the type-the-ticker input, so a live proposal is
approvable in place; a web table row does not, so it routes to the transaction
page instead. The web ticker screen puts that ticker's transactions in the right
rail; the phone has no rail, so they are a section. **There is no admin screen
on mobile and no Models card**, so `may_bring_own_key` has no mobile surface at
all — provisioning and provider keys are desk work, and the parity rule here is
about *trading safety behaviours*. `trade-source.ts` and `entitlements.ts` are
both kept byte-identical between `frontend/src/lib/` and `mobile/src/lib/` — the
two clients must not disagree about who decided a trade, or about who may do
what.

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
