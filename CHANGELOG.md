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

## [1.5.0] — 2026-08-24

You can now add to a position you already hold. Holding a stock was never a
reason to refuse buying more of it — the refusal was standing in for a feature
that did not exist.

### Added

- **Scale-in.** A `BUY` on a ticker you already hold adds to that position
  instead of being skipped. One position record, one set of protective orders,
  sized to the whole holding. Under MANUAL/SEMI_AUTO an add is proposed like any
  other entry. `ENABLE_SCALE_IN=false` restores the old refusal.
  - **Sizing caps the position, not the order.** `position_size_pct` used to
    limit each order, which limited nothing: three 5% adds made a 15% position.
    Room is measured on **cost basis**, deliberately — on market value a falling
    position frees room as it falls, so the agent would buy more of a loser
    precisely as it got worse.
  - **An add below the stop is refused.** The stop is the level at which the
    thesis is declared wrong; buying more underneath it is overriding the exit
    you already chose.
  - **Protection is never weakened.** The combined stop is the higher of what
    the new blended cost implies and what is already working, so averaging down
    cannot loosen the stop on the shares bought first. If no valid pair exists,
    the add is refused and the existing bracket is left alone.
- **`place_protective_orders`** on both broker adapters — a stop and target on
  shares already held, with no entry attached (IB: OCA pair, `ocaType 1`;
  Alpaca: native OCO). A bracket can only hang off an entry, so without this
  "the position is unprotected" was a state the system could detect and not fix.
- **The reconciler re-protects an uncovered position.** Any filled holding the
  venue reports with no working order gets its stop and target back within two
  minutes. Scale-in is one way to arrive there; a rolled gateway session or a
  leg cancelled by hand are others. It never invents a level — a record with no
  stored stop is logged for a human instead.
- **`runbooks/scale-in-paper-verification.md`** — the paper-account check,
  including the partial-fill case and the leg quantities to read in TWS.

### Fixed

- **Closing a scaled position sold only the original shares.** `execute_exit`
  sizes from the trade record, which understates the holding while an add is
  still settling — the close sold the original 450, marked the record closed,
  and orphaned the 100 just added.

### Known gaps

- **Not yet exercised against the paper account.** The logic is covered by 31
  tests and the ib_async call surface was verified against the installed
  library, but no order from this code has reached IB. The gateway lives inside
  the VPS network and is not reachable from a development machine. Run the
  runbook before this touches funded money — step 4 (partial fill) and step 6
  (the healer) are the two that cannot be reasoned about from here.
- **A gap between fill and consolidation.** The add goes out unbracketed and the
  original bracket is left working, so the *added* shares carry no stop until
  the next reconciliation pass — up to two minutes. This is deliberate: the
  alternative (cancel first, or size the legs to the intended total) leaves the
  whole holding naked while the add rests, or over-covers a partial fill and
  sells into a short. Under-protection for two minutes is the cheaper failure,
  but it is a failure.
- **A resting add can buy back into a position that just stopped out.** The
  reconciler cancels the add and logs `scale_in_abandoned_position_closed`, but
  only on its next pass — a fill inside that window opens a small unprotected
  position, which the healer then brackets.
- Adds are refused while the previous one is still working, so a fast-moving
  thesis can only be acted on once per reconciliation cycle.
- Neither client has a scale-in affordance: pressing Buy on a held ticker now
  adds, but nothing in the UI says so before you press it. The order ticket
  still reads as though it were opening a position.

---

## [1.4.0] — 2026-08-24

A signal only means something if it stops changing. HXL sent eight alerts in
sixty-five minutes — BUY, HOLD, BUY, HOLD — with the score reported as 61 and
confidence as 55% in every one of them. Nothing about the stock had changed.
This release makes a verdict earn its way to your phone.

### Fixed

- **The AI analyst cache never worked.** `analyst_used` was set on the
  in-memory signal but never written to the document, and the cache check read
  it back from the database. Every ticker therefore looked like it had no
  analyst signal, on every cycle: Claude was re-run every five minutes per
  ticker instead of hourly, roughly a **12× overspend**, and the
  `/analyze` response reported "the analyst did not run" on reports the analyst
  had just written. This one line is what made HXL flip — a language model
  re-sampled twelve times an hour on unchanged inputs will disagree with itself
  when a call is genuinely marginal, which is also why the price target drifted
  $101 → $102 → $103 → $104 with the score frozen.
- **Repeat alerts for a conviction that had not changed.** A HIGH-conviction
  ticker re-alerted on every evaluation for as long as the analyst held its
  view. Now only the *transition* into HIGH conviction alerts.
- **Duplicate proposals.** `PROPOSED` is deliberately not an open position, so
  nothing stopped the agent queueing the same entry again next cycle. Four
  identical HXL cards could sit in the Orders queue with no way to tell which
  was current. One outstanding proposal per ticker; approving or declining it
  clears the way for the next.
- **Repeated skip records.** A standing condition — position already open, IB
  Gateway down — wrote an identical `SKIPPED` row on every evaluation and
  buried real order history. An unbroken run of the same reason is now recorded
  once. A *different* reason, or the same one after something else happened, is
  recorded again.

### Added

- **Signal debouncing** (`services/signal_stability.py`). A changed verdict
  becomes a *candidate* and publishes only after `SIGNAL_CONFIRMATIONS` (2)
  consecutive fresh evaluations agree **and** the current verdict has stood for
  `SIGNAL_MIN_DWELL_MINUTES` (60). An oscillating ticker therefore publishes
  nothing and says nothing, which is the honest report of a stock sitting on a
  threshold. **SELL is exempt from both** — delaying an exit costs money,
  delaying an entry costs an opportunity, and those are not the same price.
  While a candidate is withheld, the signal's explanation says so.
- **Hysteresis on the thresholds.** Entering BUY still requires clearing 0.70;
  leaving it now requires falling under 0.67 (`SIGNAL_HYSTERESIS`). One-sided
  on purpose: an existing verdict becomes sticky, never easier to acquire. The
  risk gate still vetoes a BUY the band would otherwise hold, and calibration
  replays continue to use the raw rule.
- **Alerts you can act on without opening the app.** A bare
  `Target: $102.00 | Stop: $87.50` never said what those levels were measured
  from. Each level is now quoted with its distance from the price the call was
  made at, alongside the reward-to-risk ratio, the risk score, the analyst's
  expected horizon, and your configured position size:

  ```
  📈 HXL signal flipped: HOLD -> BUY
  Score: 61/100 | Moderate | Confidence: 55% | Risk: 4.2/10
  Price now: $95.20
  Target: $102.00 (+7.1%)
  Stop: $87.50 (-8.1%)
  Reward:risk 0.9 : 1
  Expected horizon: 2-4 weeks
  Your sizing: 5% of account equity, adjusted for volatility
  ```

  That 0.9 : 1 is the point — the old format hid the fact that this particular
  setup risked more than it stood to make.
- **`pending_signal` on `GET /analyze`**, so a withheld candidate is visible
  rather than merely silent.

### Known gaps

- **The confirmation delay is real.** With the analyst cache working, a genuine
  BUY can take up to two analyst evaluations — as much as an hour or two — to
  publish. That is the deliberate trade: fewer, later, more trustworthy entries.
  It has not yet been measured against `stocks_signal_history` to say what it
  costs in missed entry price. Set `SIGNAL_CONFIRMATIONS=1` to opt out.
- **Neither client renders `pending_signal` yet.** The withheld candidate shows
  up only in the explanation text, which both clients already display. A proper
  "candidate, unconfirmed" chip on web and mobile is still to do.
- **There is still no time-based exit.** A position is closed by its stop, its
  target, or a SELL signal, and by nothing else. The analyst's `time_horizon`
  is displayed and now included in alerts, but nothing enforces it: a position
  whose thesis said "2-4 weeks" will sit there indefinitely if neither bracket
  leg fills. This is the most-asked question about the agent and it deserves a
  real answer, not a displayed string.
- The debounce is tuned from a single day's observation of one ticker. The
  defaults are a judgement call, not a measurement.

---

## [1.3.0] — 2026-08-24

Closes the security and operability items carried since 1.1.0.

### Added

- **Login rate limiting.** `/auth/login` had no limit of any kind — a known
  email could be guessed against as fast as the network allowed. Sliding window
  per email *and* per client address, both of which must pass: the first stops a
  slow grind against one account from many addresses, the second stops one
  address spraying many accounts. 8 attempts per 5 minutes, then a 15-minute
  lockout. A success clears the email's history so a user who mistypes twice
  carries no penalty; the client key is *not* cleared, because one valid
  credential should not buy an address unlimited guesses at every other account.
  Client identity comes from `CF-Connecting-IP` — everything arrives through
  Cloudflare, so `request.client.host` is always the tunnel and would collapse
  every user into one bucket.
- **The placeholder JWT secret is now impossible to miss.** `JWT_SECRET_KEY` is
  never injected by the deploy and `.env.production` persists on the server, so
  "never set" persisted silently while the app fell back to a value committed to
  this repo — anyone reading the source could forge a token for any user and
  reach order placement. Now logged at critical on startup, reported as
  `auth_secret_is_default` on `/health` (unauthenticated, deliberately — a
  forgeable signer makes auth meaningless anyway), and the deploy generates a
  real key when it finds the placeholder or nothing.
- **Unconfigured alerting is surfaced.** The broker watch job sends nothing when
  no Slack/WhatsApp channel is set, which is exactly how an outage goes
  unnoticed. The Broker panel now says so and links to Profile → Alerts.

### Changed

- **The gateway restart no longer needs the host Docker socket.** It goes
  through a `docker-socket-proxy` sidecar that holds the socket read-only and
  answers only the container endpoints — images, volumes, networks, exec, swarm
  and system are refused, and the proxy is never published to the host. This is
  a much smaller grant than the raw socket, *not* a precise "restart only"
  capability, and the compose comments say so rather than overselling it. Still
  gated behind `ALLOW_GATEWAY_RESTART` so a deployment can decline entirely.
  The restart call distinguishes a refused endpoint (403) from a missing
  container (404), which are different problems.

### Known gaps

- The restart path has **still never been exercised against a live Docker
  daemon** — only its refusal behaviour is tested.
- Rate-limit counters are in-process: they reset on restart, and a second API
  replica would keep its own. Fine for a single container, and the module says
  so rather than leaving it to be discovered.
- `JWT_SECRET_KEY` on the existing server has not been inspected. If it was
  already set by hand, nothing changes; if it was the placeholder, the next
  deploy replaces it and **all existing sessions are invalidated** — sign in
  again.

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
