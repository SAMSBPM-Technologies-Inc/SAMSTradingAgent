# Changelog

All notable changes to SAMSTradingAgent are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project aims at [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Backend, frontend, and mobile deploy together from this repository and share a
single version.

**Two conventions worth keeping.** Record *behaviour* changes, not commit
subjects — the question a reader has is "what is different for me", and a list
of subjects answers a different one. And keep the **Known gaps** section honest:
a release note that only lists wins is the kind of document nobody trusts twice.

---

## [1.2.0] — 2026-08-24

### Added

- **Broker recovery from the UI.** Orders → Broker panel shows session state and
  offers two actions kept deliberately separate, because they carry different
  risk. **Reconnect** asks for a session immediately instead of waiting out the
  15s→300s backoff; it needs no privileges and fixes a stale socket. **Restart
  gateway** restarts the container — the only thing that clears a gateway that is
  running but unauthenticated — and is **off by default**, because it requires
  the host Docker socket inside the API container, which is root on the host.
  The panel says why the button is unavailable rather than leaving it greyed
  out, and warns that a restart usually triggers a 2FA push that must be
  approved on a phone or the session never returns.
- **Broker disconnection alerts.** A 5-minute job notifies through the existing
  Slack / WhatsApp channels once the session has been down for
  `BROKER_ALERT_AFTER_MINUTES` (default 15) — once per outage, plus a recovery
  notice. The threshold sits above the reconnect ceiling so a blip the loop
  fixes on its own never pages anyone. This failure was previously silent: the
  agent keeps scoring and the UI keeps working while every order is refused.
- **`runbooks/ib-gateway-offline.md`** — why the gateway goes offline (IBKR
  weekend maintenance, the daily forced logout, unanswered 2FA), how to tell
  which case you are in from the logs, and how to recover from the UI or over
  SSH. The in-app Guide covers setup only.
- `GET /trading/broker/status`, `POST /trading/broker/reconnect`,
  `POST /trading/broker/restart`.

### Fixed

- **Order refusals now say what is blocking them.** "Position already open for
  this ticker" gave no way to tell a filled holding from a stale order record
  that never reconciled, and those need opposite responses. `FILLED` /
  `PARTIAL` / `PENDING` now read differently and name the quantity, date, and
  order id. The `FILLED` case also explains why the guard stands: the first
  entry's bracket is still working, so a second entry would put two stops on one
  holding and could oversell into a short.
- **`Close` reported success while doing nothing when the broker was
  unreachable.** Second instance of the bug fixed in 1.1.1 — that fix covered
  the `enabled` gate and missed the connectivity gate four lines below it.
  User-initiated closes now return 503; the scheduled agent still fails quietly
  because it retries next cycle.

### Known gaps

- **Runbooks live outside `docs/`** because that directory is gitignored as
  developer planning material. An operational runbook has to be in the repo, so
  it went to `runbooks/`. The nine documents in `docs/` remain untracked and
  exist only on whoever's machine wrote them.
- The UI restart path has not been exercised against a real Docker socket — it
  is off by default and was tested only for its refusal behaviour.

---

## [1.1.1] — 2026-08-22

Hotfix. **1.1.0 took the API down**, so login and everything else failed.

### Fixed

- **Startup crash.** The idempotency index added in 1.1.0 was declared
  `sparse=True`. A compound sparse index only skips a document when *every*
  indexed field is missing, and every trade has a `user_id` — so the whole
  existing `trades` collection was indexed with `idempotency_key: null`, and the
  second such document collided against `unique=True`. `create_index` raised
  inside `_ensure_indexes`, `connect_db` awaited it unguarded, and the exception
  propagated out of lifespan startup and killed the process. Now uses
  `partialFilterExpression`, the pattern the signal-history index three lines
  above already used for the same problem.
- **Index creation and data migration can no longer abort startup.** A defect in
  a *trades* index stopped people logging in, which is the wrong blast radius.
  Connecting to Mongo is the only load-bearing step in that sequence; the rest is
  maintenance, and maintenance failing should degrade the service rather than
  delete it. Both log at error level with the concrete consequence attached.

### Known gaps

- Not reproduced locally before shipping — no Docker daemon was available to run
  a MongoDB instance. **Every backend test at the time stubbed Mongo**, so
  `_ensure_indexes` never ran against a real database and a failure that only
  manifests against real documents was structurally invisible. Startup-path code
  needs a real database in test.

---

## [1.1.0] — 2026-08-22

The UI was showing roughly 60% of what the engine does, and misstating parts of
the rest. This release closes that gap, adds a user-initiated trading path, and
brings mobile to parity.

### Added

**Analysis that explains itself**

- **Score attribution** on the ticker page — each of the six sub-scores with its
  weight and the points of the composite it supplied. The sub-scores had always
  been computed and stored; nothing returned them, so the product showed a 0–100
  number with no attribution while offering sliders to reweight it.
- **Risk & Signal Gate panel** — the 0–10 risk score, the veto line, and which
  gate conditions passed. `risk` was a required field on every response and was
  rendered nowhere, though it gates every BUY.
- **Calibration screen** (`/calibration`, both clients) — whether the score ranks
  outcomes, what each candidate BUY cutoff would have returned, and whether
  stated confidence tracks being right. Every row carries its sample size; under
  30 settled records a bucket is marked *thin* rather than shown as a confident
  percentage.
- **Price chart** — candlesticks with SMA-20/50 and volume. The product had none.

**A user-initiated trading path**

- **Trading modes**: `MANUAL` / `SEMI_AUTO` / `AUTO`. Under MANUAL — and under
  SEMI_AUTO below the conviction bar — the agent runs every guard, sizes the
  order, then records it as a proposal for a human decision instead of sending
  it. New accounts default to MANUAL.
- **Order ticket** on the ticker page, pre-filled from the quantity, stop, and
  target the engine already computed.
- **Orders screen** — proposal queue, open positions with a close action, and
  full order history labelled by who decided (Agent / Approved / You).
- `POST /trading/order`, `GET /trading/proposals`, and proposal approve/decline.
- `GET /chart/{ticker}/series` — OHLCV plus server-computed moving averages.

**Interface**

- Toast notifications with an undo window; watchlist delete now defers its
  request rather than firing immediately with no way back.
- ⌘K ticker lookup from any page, and a `/search` screen — previously you could
  only search a ticker while adding it to a watchlist.
- Sortable watchlist columns.
- Realised performance splits three ways that are never pooled: agent-placed,
  agent-proposed-human-approved, and human-chosen.
- `npm run lint:a11y` in `frontend/` — jsx-a11y, which must stay clean.

### Changed

- **Autonomy is a dial, not a switch.** Existing accounts already trading
  unattended are migrated to `AUTO` explicitly on startup, so the safer MANUAL
  default cannot silently stop a running system. See `db._migrate_trading_mode`.
- **All order paths share one guard chain** (`_prepare_entry`). A user-initiated
  order differs in exactly two documented ways — no signal-score threshold and
  no whitelist — and still obeys the CIRO restriction, the position cap, the
  daily-loss kill switch, the cash reserve, and the refusal to open an
  unbracketed position.
- **Client-supplied order quantities are requests, not instructions.** The server
  re-derives the fundable quantity from live account state and takes the smaller
  of the two, so sizing cannot be escaped from a form field.
- Orders carry an idempotency key, backed by a unique sparse index — a
  double-clicked Buy places one order.
- Live-money orders and proposal approvals require typing the ticker to confirm.
- **Price history moved behind a provider seam** (`price_providers.py`).
  Switching to licensed data is `PRICE_PROVIDER=polygon` rather than an edit to
  the ingestion path. A licensed provider failing does *not* fall back to the
  unlicensed one.
- Data-source badges: seven yfinance-backed rows moved from **Live** to **Dev
  data**, with the licensing position stated.
- The analyst model shown in the UI now comes from config and reports honestly
  when the analyst did not run.
- Mobile reached parity: chart, calibration, attribution, risk gate, holdings,
  orders, and the autonomy ladder.

### Fixed

- **Dead "Analyze" tab.** The mobile bottom bar pointed at `/ticker/search`,
  which resolved as a ticker named "search" and rendered a full-page error.
- **Dark mode was broken on the Performance page.** 55 hardcoded light-mode hex
  values painted `#14110c` text on the `#0e0c09` dark background — the accuracy
  dashboard rendered as a near-black rectangle. Colours are design tokens now.
- **`POST /trading/close/{ticker}` did nothing for manual-mode users.** It ran
  through the agent's `enabled` gate, so it returned `close_order_submitted`
  while no order was submitted.
- A route handler named `get_settings` shadowed the config accessor in
  `trading.py`, which would have failed every order request.
- Mobile profile save sent a bare string where the API expects an object, so
  changing your display name failed.
- The Signal Weights panel offered a Volatility slider defaulting to 10% when
  the engine deliberately sets it to 0 — volatility is priced at the risk gate.
  The panel's Reset also disagreed with the server's own defaults.
- The UI named the wrong Claude model.
- Duplicate "By Ticker" heading and two columns both labelled "Exit".

### Accessibility

The frontend had 13 `<label>` elements and **zero** `htmlFor` — not one input
was programmatically named — and watchlist rows were `div onClick` with no role,
`tabIndex`, or key handler, making the expandable row keyboard-unreachable.

- Labels bound to their controls; rows are real disclosure controls with
  Enter/Space, `aria-expanded`, and `aria-controls`.
- Error banners are `role="alert"`; sort headers announce their direction;
  filter chips carry `aria-pressed`.
- The command palette traps Tab and restores focus on close.
- Skip-to-content link.
- Linting added, which caught four defects a manual sweep had missed.

### Security & compliance

- **"Not financial advice" now appears on every screen**, web and mobile. It
  previously existed only on the Guide page and inside exported PDFs, in an
  application that routes live orders to a broker.
- Price history was being fetched from Yahoo's undocumented
  `/v8/finance/chart` endpoint with a spoofed browser User-Agent. That remains
  the development default and is now labelled as such, with a licensed path
  available by configuration.

### Known gaps

- The **Polygon price adapter has never made a live request.** It is tested for
  the refusal path (no key → raises) but unproven against real data; it needs a
  plan covering aggregates.
- Short interest, options flow, and insider activity still use yfinance.
- Calibration will show mostly *thin* buckets until more signals settle. This is
  the honest state of a young track record, not a defect.
- Three mobile TypeScript errors remain — library typing noise
  (`react-hook-form` generic variance, a `<P style>` prop, one route literal)
  with no runtime impact.
- Mobile screens hardcode a light-only palette; the web design tokens are the
  reference if they are ever themed.
- The per-user subdomain split (`sta.` vs a custom domain) is presentational.
  There is no hostname check and all users share one broker account, which is
  correct for a single operator and would need real tenant isolation before a
  second one.

---

## [1.0.0] — before 2026-08-22

Baseline: the system as it stood before this changelog began. FastAPI + MongoDB
ingestion and scoring pipeline, React SPA, Expo mobile app, IBKR automated
trading, AI analyst reports, and the signal-history performance tracker.

History before this point is in the git log rather than here.

[1.1.0]: https://github.com/SAMSBPM-Technologies-Inc/SAMSTradingAgent/pull/3
