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
