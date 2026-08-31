# Due-Diligence Questionnaire — SAMSTradingAgent

**Status of this document.** Answers below are drawn from the code and the
release record in this repository as of **v1.10.1 (27 Aug 2026)**. The product
is **pre-revenue, pre-customer, and has never traded real money.** Where a
question presumes an operating history that does not exist, the answer says so
rather than constructing one — a questionnaire answered optimistically is worth
less than one answered plainly, because the reader cannot tell which parts to
trust.

Three markers are used throughout:

- **[VERIFIED]** — checked against source in this repo; the file is named.
- **[TO CONFIRM]** — a business/legal fact not recorded in the repo. The
  founder must fill these in; they are not engineering answers.
- **[GAP]** — a real absence. Listed deliberately, with what closing it takes.

---

## 1. Company & Product Overview

### Business Information

**1.1 Legal name, jurisdiction, year established.**
[TO CONFIRM] — the GitHub organisation is *SAMSBPM Technologies Inc.* and the
code carries CIRO (Canadian) trading restrictions, which implies a Canadian
operating context. Exact registered name, jurisdiction of incorporation and
date of incorporation are not recorded in this repository and must be supplied
from the corporate records.

**1.2 Ownership structure.**
[TO CONFIRM] — founder-owned. No outside capital has been raised. No option
pool, no employee shareholders.

**1.3 How many employees support the platform?**
One. The entire commit history — 209 commits, ~37,600 lines across backend,
web and mobile — is authored by a single engineer. [VERIFIED: `git shortlog`]

There is no on-call rotation, no second pair of eyes on a deploy, and no
continuity if that person is unavailable. This is the single largest
operational risk in the platform and is stated first because every other
answer in Sections 8 and 10 inherits it.

**1.4 Percentage of employees by function.**

| Function | Share |
|---|---|
| Engineering | 100% (one person, part-time across all four functions below) |
| Quantitative research | 0% dedicated |
| Operations | 0% dedicated |
| Support | 0% dedicated |

**1.5 Active paying customers.**
Zero. There is no self-serve signup and no billing system of any kind. The
public landing page offers a contact form rather than an account, precisely
because pretending otherwise would be false. [VERIFIED: `routes/contact.py`,
CHANGELOG 1.10.0]

### Product Background

**1.6 First deployed to production.**
7 Aug 2026 (first commit). Continuously deployed since; the backend runs at
`api.samsbpm.com` and the web client at `sta.samsbpm.com`. Nineteen tagged
releases from 1.0.0 to 1.10.1. [VERIFIED: `CHANGELOG.md`]

**1.7 Major architectural revisions since launch.**

| Version | Date | Change |
|---|---|---|
| 1.1.0 | 22 Aug | Per-user IBKR connections; Fernet-encrypted credentials |
| 1.2.0–1.3.0 | 24 Aug | Removed tier gating and the admin portal; single-class users |
| 1.4.0 | 24 Aug | Signal stability layer — confirmation + dwell before publishing |
| 1.5.0 | 24 Aug | Score attribution and risk gate surfaced to clients |
| 1.6.0 | 25 Aug | Commission accrual; net-of-fee performance |
| 1.7.0 | 26 Aug | Deep-research agent fan-out with evidence ledger |
| 1.8.0 | 27 Aug | Trading mode dial (MANUAL / SEMI_AUTO / AUTO); proposal queue |
| 1.9.0 | 27 Aug | Exit settlement fix — exits were never reaching CLOSED |
| 1.10.0 | 27 Aug | Public landing page; the app is no longer auth-walled at the root |

Two of these were corrections of defects found in production, not planned
features (1.4.0 after HXL alerted eight times in 65 minutes on an unchanged
score; 1.9.0 after closed positions never settled). Both are documented in the
changelog with the incident that caused them.

**1.8 Primary target audience.**
Retail investors and self-directed individual traders holding a brokerage
account they control (IBKR today, Alpaca supported as an alternative venue).
The platform is **not** built for asset managers or family offices: it has no
multi-account administration, no client reporting, no fee billing, and no
compliance surface for managing other people's money.

**1.9 Is the platform used to manage real-money accounts?**
**No.** Production runs against an IB Gateway **paper** session
(`TRADING_MODE=paper`). Live trading is gated behind two independent flags —
`AUTO_TRADE_LIVE_ALLOWED` (permission) and the gateway session the container
actually launched (ground truth) — and a live order additionally requires the
user to type the ticker back in the UI before `confirm_live` is set.
[VERIFIED: `config.py`, `routes/trading.py`]

---

## 2. Strategy & Scoring Methodology

### Scoring Model

**2.1 Factor definitions.** [VERIFIED: `services/feature_engineering.py`,
`fundamentals.py`, `news.py`, `macro.py`, `catalyst.py`, `docs/09-analysis-sources.md`]

| Factor | Definition | Data sources | Refresh |
|---|---|---|---|
| **Technical** | RSI-14, MACD, Bollinger %B, Stochastic RSI, MA-20/50 cross, ATR, OBV, volume anomaly, combined under a declared *stance* (`mean_reversion` by default) | Yahoo Finance v8 chart API (dev) / Polygon via Massive (licensed path) — 90 days daily OHLCV | Every 5 min |
| **Fundamental** | Analyst recommendation 30%, revenue growth 25%, P/E 20%, free cash flow 15%, debt/equity 10% | Massive (Polygon) statements, Alpha Vantage OVERVIEW/EARNINGS, yfinance fallback | Daily (cached 24h — provider rate limits make anything faster impossible) |
| **Catalyst** | Volume anomaly vs 20-day average, plus an **additive** earnings-proximity bonus, insider buys, options signals | Alpha Vantage EARNINGS, yfinance option chain / Form 4 | 5 min (volume), weekly (earnings, 7-day cache; eager refresh inside 7 days of a report) |
| **Sentiment** | VADER polarity over the last 7 days of company headlines, plus bullish/bearish share and a capped buzz metric | Finnhub `/company-news` | Every 5 min |
| **Macro** | VIX 35%, 10y–2y yield curve 35%, CPI YoY 30%; Fed funds and unemployment carried for context | FRED (`VIXCLS`, `DGS10`, `DGS2`, `CPIAUCSL`, `FEDFUNDS`, `UNRATE`) | Daily (series publish daily at best) |
| **Volatility** | Inverse of 20-day annualised volatility | Derived from OHLCV | Every 5 min |

**Note on the volatility factor:** its scoring weight is **0.00 by default and
that is deliberate.** Volatility was being charged twice — 0.10 of the
composite *and* up to 7 of the 10 risk points, where risk ≥ 6 vetoes a BUY
outright. A high-beta name was marked down in the ranking and then blocked at
the gate for the same fact. Volatility is now priced only at the risk gate,
which is the question it actually answers ("is this too dangerous to hold"),
and the freed 0.10 went to technical and fundamental. [VERIFIED: `config.py`
weight block]

**2.2 The combining model.**

```
base  = 0.30·technical + 0.20·fundamental + 0.20·sentiment
      + 0.15·macro + 0.00·volatility + 0.15·catalyst        (six weights, sum = 1.0)

score = clamp( base + 0.10·(alternative_data − 0.5) )        (additive modifier, ±0.05)
```

Alternative data (options put/call ratio 50%, insider buy ratio 50%) is an
additive modifier centred on 0.5 rather than a seventh weighted share, so it
nudges the base and can drag it down; it deliberately does not participate in
the sum-to-1.0 constraint. The six base weights are validated to sum to 1.0 at
startup and the app refuses to boot otherwise. [VERIFIED: `config.py`
`validate_weights_sum`, `services/scoring.py`]

An XGBoost path exists (14 features) but is **disabled in production**
(`ENABLE_ML_MODEL=false`) — the fundamental and sentiment inputs to it are
still frozen. Re-enabling it is Phase 4 of `PLAN.md`. When it is on,
`explain_score` sets `attributable: false`: the linear weights did not produce
that number and presenting a weighted decomposition beside it would be a
fabrication. [VERIFIED: `services/scoring.py`]

**2.3 Static or dynamic weights?**
Static per user. Global defaults live in `config.py`; each user may override
them in `users.scoring_weights`, which is applied at read time via
`compute_personalized_score`. Nothing adapts them automatically. There is no
online learning, no regime detection, no auto-tuning.

**2.4 How were initial weights selected?**
**Judgement, not fitting.** [GAP] This is the most important honest answer in
the document: the weights were reasoned about from first principles (technical
timing carries the most, macro and catalyst least) and then adjusted twice for
*structural* reasons that are documented — the volatility double-count above,
and the technical stance being made explicit after it was found that the
component mix was silently 60/40 mean-reverting, i.e. the model was a dip-buyer
by accident rather than by decision. Neither adjustment was fitted to returns.
No weight in this system has ever been optimised against historical outcomes.

**2.5 Recalibration frequency.**
There is no scheduled recalibration. What exists instead is a **reporting**
surface: `/calibration` renders `GET /performance/calibration`, which answers
three questions from settled signal history — does a higher score actually earn
a higher 20-day return, what would each candidate BUY cutoff have returned, and
does stated confidence track being right. Every row carries `n` and a
`significant` flag; under 30 settled samples the UI marks it *thin* rather than
showing a confident-looking percentage. [VERIFIED: `services/calibration.py`]

The module reports and refuses to tune. Auto-fitting a threshold to its own
few hundred records is how a system talks itself into whatever the last few
months rewarded.

**2.6 Who approves weight changes?**
The founder, as a code change to `config.py` (or a user, for their own account,
through the profile UI). A global weight change is a commit, a review-less
merge to `main`, and a deploy. [GAP] There is no second approver and no
separation of duties.

**2.7 Factor correlation measurement.**
[GAP] Not measured. Factor correlations are not computed, monitored, or
reported anywhere. This matters — sentiment and catalyst both partly read news
flow, and technical and volatility both derive from the same OHLCV series, so
the effective independent dimensionality is lower than six. Closing this needs
a covariance report over `stocks_features` history, which is data the system
already retains.

### Model Governance

**2.8 Model versioning.**
Partial. Every feature document records `scoring_method` (`weighted` or
`xgboost`), and the app version is asserted in four places that move together
(`frontend/package.json`, `mobile/package.json`, `main.py`,
`HealthResponse.version`). [GAP] But the *weights in force at the time a signal
was generated* are not stamped onto the signal record. A signal from 20 Aug and
one from 27 Aug are indistinguishable in `stocks_signal_history` even though
the volatility weight changed between them.

**2.9 Can historical trades be reproduced under the model version active at the time?**
**No.** [GAP] Consequence of 2.8. Signals record score, risk and outcome, but
not the weight vector or the code version. Reproduction is possible to within
a git checkout by timestamp, manually. Making this a real capability means
writing the effective weights and a model-version string into every
`stocks_signal_history` record — a small change, not yet done.

**2.10 Model-change approval process.**
[GAP] None formal. Single committer, direct merge to `main`, automatic deploy.

**2.11 Are changes documented and auditable?**
Yes, unusually well for the stage — this is a genuine strength. `CHANGELOG.md`
records behaviour changes with the reasoning and the incident behind each, and
carries a mandatory **Known gaps** section per release. Non-obvious design
constraints are written into the code as prose comments at the point they apply
(see `config.py`, ~700 lines of which a large share is rationale). Git history
is complete from the first commit.

---

## 3. Backtesting & Performance Validation

**This entire section is a gap, and it is the gap a technically literate
investor should press hardest on.**

**3.1–3.2 Backtest results, Sharpe, Sortino, max drawdown, CAGR, win rate over 1/3/5/10 years.**
**None exist.** `services/backtesting.py` is a labelled stub: 60 lines, long-only,
driven by `_synthetic_signal()` — a trivial rule that is *not* the production
scoring engine — and disabled by default (`ENABLE_BACKTESTING=false`). Its own
docstring says to replace it with a walk-forward loop once the model is trained
on labelled historical data. [VERIFIED: `services/backtesting.py`]

No figure for net return, Sharpe, Sortino, drawdown, CAGR or win rate over any
horizon has ever been produced by this system, and none should be quoted from
it.

**3.3 Were commissions included?** N/A — no backtest. (Commissions *are*
tracked in live/paper accounting; see 4.1.)

**3.4–3.5 Slippage.** N/A — no backtest, and no slippage model exists.

**3.6 Delisted securities.** N/A. Note the structural problem for when a
backtest is built: the current price sources return data for currently-listed
symbols, so a naive historical replay over today's watchlist would be
survivorship-biased by construction.

**3.7 Survivorship and look-ahead bias.** [GAP] Not addressed, because there is
nothing yet to address it in. Two specific hazards are already known and should
be designed against before any backtest is trusted: (a) survivorship, per 3.6;
(b) look-ahead through fundamentals — `stocks_fundamentals` is replaced
wholesale on every refresh and carries no as-of date, so a replay would see
restated figures the market did not have. `financial_statements` is
append-only precisely so that a point-in-time series exists; it is the correct
basis for any historical work.

### Out-of-Sample Validation

**3.8 Walk-forward methodology.** [GAP] None.
**3.9 Withheld validation percentage.** N/A — no model has been fitted, so
there is nothing to withhold. The upside of never having fitted anything is
that the current weights **cannot be overfit**; they have simply never been
validated either.
**3.10 Evidence the model is not overfit.** The honest answer: the linear model
has zero fitted parameters, so overfitting is not the risk — *being wrong* is.
The evidence that would settle it is the calibration surface in 2.5, and it
does not yet have enough settled records to be significant.

---

## 4. Live Trading Performance

**4.1 Actual live trading performance.**
**None. No real money has ever been traded.** Production has run on an IBKR
paper account since 19 Aug 2026. The paper record tests plumbing — that orders
route, brackets attach, fills reconcile, exits settle, commissions accrue — and
must not be read as evidence about signal quality: paper fills are optimistic,
there is no market impact, and the sample is three weeks long.

Two data-integrity caveats apply even to the paper record:
- Trades closed before v1.6.0 can never be netted of commission; IB only serves
  the current session's executions.
- Exits did not reach `CLOSED` correctly until v1.9.0 (27 Aug 2026), so
  realised statistics before that date are unreliable by construction.

**4.2 Separation by origin.** This *is* implemented, and correctly.
`/performance/trades` keeps three buckets strictly apart and never pools them
[VERIFIED: `routes/performance.py`]:

| Bucket | Meaning | What it measures |
|---|---|---|
| `signal_driven` | Agent placed it unattended | The only clean read of the engine |
| `approved` | Agent proposed, human accepted | The **pair** — biased by what the human declined |
| `manual` | Human chose the ticker | The human |

**4.3–4.6 Monthly returns, equity curves, drawdowns, trade counts for 24 months.**
Not available — the system is three weeks old and has never traded real money.
The underlying reporting exists and will produce these once there is a record
to produce them from.

### Trade Attribution

**4.7 Can every trade be traced to factor scores, research, risk, and sizing?**
Largely yes, and this is a strength. Each trade record carries the signal score
that triggered it, the `size_basis_equity` frozen at entry, the computed
quantity, the bracket levels and their source (analyst-supplied or fallback
percentages), the skip reason if it was refused, `commission_exec_ids` for
every accrual, and a `PROPOSED`/`DECLINED` state if a human was in the loop.
`GET /analyze` returns the full `breakdown` (each factor's sub-score, weight
and points contributed) and the `gate` (thresholds and pass/fail) from the
engine itself, never from constants restated in the UI. [VERIFIED:
`models/trade.py`, `scoring.explain_score`]

The one break in the chain is 2.9: the *weights* in force are not stamped on
the record, so attribution is exact for the score and approximate for how the
score was assembled.

**4.8 Examples of best/worst trades and trades prevented by risk controls.**
No meaningful examples exist from a three-week paper run. Refusals **are**
recorded rather than silently dropped — every guard returns a reason string
which is written to the trade record and de-duplicated by signature so a
standing BUY does not log the same skip every five minutes [VERIFIED:
`_skip_signature`, `_already_skipped_for` in `trade_manager.py`]. Once there is
a record worth showing, this section becomes a query, not a construction.

Two documented cases where a control was **added because it had already cost
money** are more informative than any example trade, and are offered instead:

- **NVDA, 25 Aug 2026** — eight orders in one morning, seven of them for one or
  two shares. The position had hit its cap, and equity read live drifted up all
  session, handing a full position a sliver of fresh room every cycle that the
  retry loop spent immediately. Fixed by freezing `size_basis_equity` at entry
  and adding `MIN_ADD_FRACTION` / `MAX_SCALE_INS` / `SCALE_IN_DIP_PCT`.
- **HXL, 24 Aug 2026** — eight alerts in 65 minutes, alternating BUY/HOLD at an
  unchanged score of 0.61. Fixed by the signal-stability layer: a changed
  verdict is a *candidate* until `SIGNAL_CONFIRMATIONS` consecutive fresh
  evaluations agree and the standing verdict has served `SIGNAL_MIN_DWELL_MINUTES`.

---

## 5. Research Agent Architecture

### AI / Research Layer

**5.1 Agents and responsibilities.** [VERIFIED: `services/research/agents/specs.py`,
`dossier.py`]

The deep-research path is separate from the 5-minute pipeline — it runs **on
demand and once a day** (`RESEARCH_DAILY_REFRESH_HOUR`, default 06:00 local),
never per cycle, and nothing in the fast path may come to depend on it. One
dossier costs five model calls.

| Agent | Job | Model role |
|---|---|---|
| Fundamentals | Financial statements, valuation, earnings record | Specialist |
| Technical | Price, volume, trend; support/resistance only where the evidence names a price | Specialist |
| News | News flow, scheduled events, catalysts | Specialist |
| **Risk** | Argue the name is a bad investment, from evidence alone | Orchestrator (stronger model) |
| Synthesiser | Reconcile four independent reads into one dossier | Orchestrator |

The four specialists run concurrently via `asyncio.gather` over one shared
evidence ledger, each told explicitly that it is *one of four analysts working
the name independently*. Off unless `RESEARCH_AGENTS_ENABLED=true`.

**5.2 Models used.** Anthropic Claude, by role, both configurable:
`RESEARCH_ORCHESTRATOR_MODEL` = `claude-opus-5` (risk + synthesis — the
judgement-heavy roles), `RESEARCH_SPECIALIST_MODEL` = `claude-sonnet-5` (the
three descriptive roles). The separate fast-path AI analyst uses
`ANALYST_MODEL` = `claude-sonnet-5`. Effort levels and adaptive thinking are
configured per path. No model identifier is hard-coded in docs or UI; clients
read it from `AnalyzeResponse.analyst_model`.

**5.3 Model update frequency.** On demand, as a config change — models are not
pinned to a dated snapshot, so a provider-side model revision reaches
production without a deploy. [GAP] There is no regression suite that would
detect a change in model behaviour; 5.5 is the closest thing.

**5.4 Third-party LLM providers?** Yes — Anthropic only, over the public API.
No customer PII is sent: prompts carry ticker symbols, price series,
indicators, public filings figures and public headlines. No account numbers, no
positions, no credentials, no user identity.

### Hallucination Controls

This is the part of the system built most deliberately, and it is worth
reading carefully because the mechanism is unusual.

**5.5 How is factual accuracy measured?**
By construction rather than by scoring. Every fact enters an **evidence ledger**
(`evidence.py`) with an id, a claim, a value, a source and a date. Agents may
only cite ledger ids. Before storage, `strip_uncited` removes any statement
carrying no citation, and `unknown_citations` detects ids that do not exist —
i.e. fabricated ones.

**A claim without a citation is deleted, not flagged.** `Ledger.add` also
refuses a `None` value, because an "unknown" entry would still receive an id
and an agent would then cite it.

**5.6 What percentage of statements are rejected for missing citations?**
It is measured **per dossier and stored**, not as a global rate.
`ResearchDossier.citation_audit` carries exactly what was dropped and what was
fabricated. It is present whenever a report exists and `None` only when there
was nothing to filter — so "clean" and "never checked" are distinguishable
from the outside. This was a defect once: the audit lived under `_`-prefixed
keys inside `report`, which `ResearchReport` had no field for, and Pydantic
silently discarded it at the API boundary. [VERIFIED: `models`, CHANGELOG 1.7.0]

[GAP] No aggregate rejection rate is reported across dossiers yet. The data to
compute it is retained in `research_dossiers`; it is a query away and would be
a genuinely useful number to publish.

**5.7 How are citations validated?**
Set membership against the ledger's own ids, plus prefix scoping — each agent
is granted only the evidence prefixes relevant to its role (`P`,`F`,`V`,`E` for
fundamentals; `T`,`M` for technical; and so on), so a technical agent citing a
filings id is caught.

**5.8 Can users independently verify source material?**
Partly. Each evidence item carries its source and date and is rendered into the
dossier, so a reader can see *what* the claim rests on and go check it. [GAP]
There is no deep link back to the vendor document or filing URL, so
verification is manual.

### Red Team / Risk Agent

**5.9 How does the independent risk agent function?**
It runs **inside the fan-out, concurrently with the other three, and is never
shown the bull case.** That is the whole point. Given a thesis, a red team
argues against *that thesis* and inherits its framing; the single-analyst
design this replaced wrote both sides in one pass and produced a bear case
shaped to fit its own bull case. The risk agent sees the evidence ledger and
one instruction — argue this is a bad investment — with the full prefix set,
and is explicitly permitted to conclude that there is no strong bear case, as a
legitimate finding.

**5.10 How often does it disagree with the primary thesis?**
[GAP] Not measured. There is no counter for risk/thesis divergence. It would be
a good metric and the dossiers retain what is needed to compute it.

**5.11 What happens when research and risk disagree?**
The synthesiser must **address or carry every risk raised — never silently drop
one.** Disagreement is surfaced, not resolved away. Downstream, conviction is
blended from six dimension scores; the model may move it by ±15 and must
explain why.

Worth stating: **five of the six dimension scores are Python, not model
output** (`financial_strength`, `growth`, `valuation`, `technical`, `risk`).
Only `business_quality` is model-judged, and it is flagged as such. A headline
number that cannot be reproduced or regression-tested is decoration. Higher is
better on all six, `risk` included, where it means safer.

**5.12 Examples where the risk process prevented losses.**
None to show — the veto is **off by default** (`RESEARCH_VETO_ENABLED=false`)
and has not been enabled in production. A guard that can stop trades has to be
switched on deliberately, having been measured first.

The constraint on it is the part worth reviewing regardless:
**research may veto a BUY; it may never create one, enlarge one, or reach an
exit.** `_research_veto` sits inside `_prepare_entry` with the other guards and
is absent from `execute_exit`. Every uncertain path — missing dossier, stale,
undated, database error — **allows the trade**. A guard that halts buying when
a cron job misfires is a worse failure than one that occasionally lets a trade
through. [VERIFIED: `trade_manager.py`, `tests/test_research_veto.py` — 14 tests]

---

## 6. Data Management

### Market Data

**6.1–6.3 Providers, licensing, refresh.** [VERIFIED: `config.py`,
`services/price_providers.py`, `docs/09-analysis-sources.md`]

| Data type | Vendor | Refresh | Licence status |
|---|---|---|---|
| Market prices (OHLCV) | Yahoo Finance v8 chart API **(default)** / Polygon.io via Massive (`PRICE_PROVIDER=polygon`) | 5 min | **Yahoo is an undocumented endpoint accessed with a browser User-Agent and is NOT licensed for commercial use.** Polygon is the licensed path |
| Fundamentals | Massive (Polygon) statements; Alpha Vantage OVERVIEW; yfinance fallback | 24h cache | Paid API keys; commercial terms [TO CONFIRM] |
| Earnings history | Alpha Vantage EARNINGS | 7-day cache, eager inside 7 days of a report | As above |
| News | Finnhub `/company-news`, 7-day window | 5 min | Free/paid tier [TO CONFIRM] |
| Macro | FRED (US Federal Reserve) | Daily | Public domain |
| Options (put/call) | yfinance option chain, nearest expiry | 5 min | Unlicensed, same caveat as prices |
| Short interest & insider (Form 4) | yfinance `.info`, `insider_transactions` | 5 min | Unlicensed; short interest is **display only**, not scored |
| Sentiment | Computed locally (VADER) over Finnhub headlines | 5 min | N/A — own compute |

**This is the second thing a serious buyer should press on.** Production
currently defaults to `PRICE_PROVIDER=yahoo`. Yahoo is fine for development and
is not a basis on which to sell a commercial product; the licensed Polygon path
exists and is one config value away, but requires a plan that includes
aggregates and has not been the production default. It is flagged in the code
at the point of use rather than buried.

**Rate limits are a first-order design constraint, not an afterthought.** Both
fundamentals providers cap at roughly 5 requests/minute and Alpha Vantage at 25
calls/day, against a ~29-ticker watchlist and two call types. Hence:
`ALPHAVANTAGE_DAILY_BUDGET=22` (held under the cap so an ad-hoc refresh cannot
exhaust the scheduled job's budget), a 24-hour fundamentals cache, a 7-day
earnings cache with eager refresh near a report, and a cold-start backfill with
a 60-minute per-ticker cooldown so a permanently empty symbol does not re-fetch
every cycle.

### Data Quality

**6.4 Data-quality controls.**
- Weights validated to sum to 1.0 at startup; the app refuses to boot otherwise.
- Every external service degrades gracefully to a documented fallback rather
  than failing the cycle.
- Missing fundamentals fall back to a flat 0.5, which is *visible* in the
  breakdown rather than silent — and the cold-start backfill exists because
  that fallback was found running for 24 hours on a newly added mega-cap
  (ADBE, 21 Aug 2026) whose P/E and cash flow are entirely public.
- The research ledger refuses `None` values outright (5.5).
- Dimension scores carry a `thin` flag when their inputs are sparse.

**6.5 Stale-feed detection.**
Partial. Dossiers have an explicit TTL (`RESEARCH_DOSSIER_TTL_HOURS=24`) and
are marked stale in the UI and ignored by the veto past
`RESEARCH_VETO_MAX_AGE_HOURS=48`. Fundamentals carry a cache age. Broker
disconnection is detected and alerts after 15 minutes (deliberately longer than
the 300s reconnect backoff ceiling, so a routine blip that self-heals pages
nobody). Since 1.16 each data source carries a last-success timestamp and
the analysis cycle itself carries a last-run time, both readable at
`GET /system/status` and judged against the market clock rather than wall
time, so a quiet overnight is not reported as an outage.

[GAP] There is still **no staleness check on the price feed itself**. Health
recording observes whether a fetch *succeeded*, which is a different question
from whether the bar it returned was fresh — if
Yahoo returned a cached or frozen bar, nothing would currently notice.

**6.6 If a feed becomes unavailable.**
Each source degrades independently: no Finnhub key → neutral sentiment; no FRED
→ neutral macro; no fundamentals → 0.5 fallback; no Anthropic key → the
rule-based signal path. Trading does not stop for a data outage, and that is
the deliberate choice. The consequence — **a degraded score still produces a
verdict** — remains true and always will; what changed in 1.16 is that the
degradation is no longer invisible.

Every signal now carries an **input completeness** figure: the weighted share
of the composite that came from measured data, plus the names of the factors
sitting at a neutral placeholder. It is returned by `GET /analyze`, shown above
the factor breakdown on both clients, and frozen onto every trade the agent
takes, so a closed position can be judged on the data it was actually opened
on. Coverage is weight-independent and stored once; completeness is weighted by
the reader's own weights, because a factor weighted at zero is not part of
their score. A figure that cannot be computed — a signal generated before this
existed — stays **absent** rather than defaulting to 1.0, which would claim
every historical verdict was built on complete data.

Two consequences of the old blindness were found while writing
[`12-how-a-trade-is-judged.md`](12-how-a-trade-is-judged.md) and fixed in the
same release. A missing Finnhub key fed `article_count: 0` into the catalyst
factor, which read it as *genuine news silence* and scored it 0.40 — so an
unconfigured provider dragged the composite down rather than leaving it
neutral. And `data_sources.fundamentals` inferred the provider from whether a
P/E was present, naming a provider (`yfinance`) that had been removed from the
chain and reporting `"none"` for every Massive-only refresh that carried real
cash-flow and balance-sheet data.

The remaining honest limitation is stated in §6.5: completeness measures
whether an input *arrived*, not whether it was fresh.

**6.7 Data lineage.**
Yes within the research path — the evidence ledger *is* lineage, id by id, with
source and date. The fast pipeline now carries provider-level lineage: every
signal records which provider answered for price, sentiment, macro,
fundamentals (with a staleness flag) and alternative data, read from the
sentinel each fetch writes rather than inferred from the payload. It is
versioned (`data_sources_version`), and historical rows are **not**
backfilled — the provider that really answered on a given day is not
recoverable, and a guess written into a provenance field is worse than a gap
in one.

[GAP] It remains *provider*-level, not fact-level: the fast path still cannot
say which of two providers supplied a particular ratio, the way the research
ledger can for a particular claim.

**6.8 Corrections and revisions tracked?**
For filings, yes: `financial_statements` is **append-only** per
(ticker, period, timeframe) and only ever gains rows — it is the basis for every
trend, and the reason it exists is that `stocks_fundamentals` is replaced
wholesale on every refresh, so no trend could ever be computed from it. [GAP]
Price revisions and news retractions are not tracked.

---

## 7. Risk Management Controls

*(The source questionnaire truncates mid-question here; both parts are answered.)*

**7.1 Portfolio-level limits.** [VERIFIED: `models/trade.py`,
`trade_manager.py::_prepare_entry`, `config.py`]

Every order path — automated, semi-automated and manual — passes through **one
shared guard chain** in `_prepare_entry`. A guard is never added to one path
only. A manual order differs in exactly two documented ways: no signal-score
threshold (the human is the signal) and no ticker whitelist (that restricts
what the *agent* may pick, not what a person may buy).

| Control | Default | Note |
|---|---|---|
| Position size | 5% of equity | Measured on **cost basis** against `size_basis_equity` **frozen at entry** — a falling price cannot free room to average down, and rising intraday equity cannot hand a full position fresh room |
| Max open positions | 5 | `PROPOSED`/`DECLINED` are deliberately excluded from `OPEN` — a proposal commits nothing and must never consume a slot |
| Daily loss kill switch | 2% of equity realised | Blocks new entries for the day |
| Cash reserve | 5% of equity | Held back from sizing to absorb commission and limit-vs-fill slippage |
| Margin | **Disabled** | Sizing several positions off the same equity figure silently borrows; eight 8% positions on a $1M account once overshot into ~−$86k of margin. With margin off, entries size against settled cash |
| Minimum signal score | 0.75 | Agent path only; above the 0.70 BUY threshold |
| Conviction floor | HIGH | Below `auto_execute_conviction`, SEMI_AUTO proposes instead of executing |
| Ticker whitelist | Empty (= watchlist) | Agent path only |
| CIRO restriction | Canadian-listed refused | API-based automated trading is only permitted for US-listed securities |
| Unbracketed entries | Refused | An entry is submitted as a bracket or not at all |
| Volatility sizing | Applied | `_volatility_size_factor` shrinks size on high-vol names |
| Scale-in limits | dip ≥ 2% below blended cost; max 2 adds; add ≥ 25% of holding | Every add condition is really a *rate* limit, because a standing BUY re-runs the chain every 5 minutes |
| Order-level | `idempotency_key` with a unique sparse index on `(user_id, idempotency_key)` | The index, not a route lookup, is what stops a double-clicked Buy from buying twice |
| Live-money | `confirm_live` + user types the ticker back | Both web and mobile |

**Two invariants that hold the whole design together**, and which any reviewer
should test against:
1. **Protective orders may never cover more shares than are held** — that sells
   into a short.
2. **An add may never loosen the stop already on the holding.**

Because a bracket protects an *order* while a stop protects a *position*, a BUY
on a held ticker adds to the single existing position record (never a second
record — `execute_exit` loads exactly one and would orphan the rest), goes out
unbracketed with the existing legs left working, and `reconcile_trades` then
cancels them and places one OCA pair sized to what the venue says is held.
Verification procedure: `runbooks/scale-in-paper-verification.md`.

**Autonomy is a dial, not a switch.** `MANUAL` / `SEMI_AUTO` / `AUTO`. Under
MANUAL, and under SEMI_AUTO below the conviction floor, the agent runs every
guard, sizes the order, and then writes it as a `PROPOSED` trade instead of
sending it. New accounts default to MANUAL. Existing accounts that were already
trading unattended were migrated to AUTO by `db._migrate_trading_mode`, so
adding the safe default did not silently stop a live system.

**7.2 Exposure limits.** Per-position (5%) and per-portfolio (5 positions, 2%
daily loss, 5% cash reserve, no margin) as above. [GAP] There are **no sector,
factor, correlation, or single-issuer concentration limits.** Five positions in
five semiconductor names would pass every guard in the table. For a
five-position retail portfolio this is a smaller hazard than it would be at
scale, but it is a real absence and should be named as one.

---

## 8. Extreme Event Handling

Answered honestly: several rows below are *inherited* behaviour from IBKR and
Docker rather than logic this platform implements, and they are marked so.

### Market Events

| Scenario | Detection | Automated action | Recovery |
|---|---|---|---|
| **Flash crash** | None specific | None specific. Broker-side stop-losses execute — protection lives at IBKR, so it survives this app crashing, the gateway dropping, or the host going down. Risk scoring will mark volatility up on the *next* cycle | Manual review; positions already bracketed |
| **Trading halt** | Order rejection from IBKR | Order fails, reason recorded on the trade, skip de-duplicated so it does not re-log every 5 min | Retries next cycle; resumes when the halt lifts |
| **Circuit breaker** | Same as halt | Same | Same |
| **Exchange outage** | Order rejection / no fills | Entries fail and retry; no forced action | Automatic on resumption |
| **Broker outage** | Connection loss on the IB Gateway socket | Reconnect loop with backoff to a 300s ceiling; alert after 15 min disconnected; entries skip with "gateway down" and retry | `/trading/broker/reconnect` (safe, no privilege); `runbooks/ib-gateway-offline.md`; container restart via the filtered Docker proxy only if `ALLOW_GATEWAY_RESTART=true` |
| **Large overnight gap** | Next cycle's price | Broker-side stop triggers at the open — **at the gap price, not the stop price**, which is the ordinary behaviour of a stop and should be understood as such | Reconciliation settles the exit and accrues commission |
| **Extraordinary volatility** | `volatility_20d` feeds the risk score; the curve's knee sits exactly on the BUY veto, so "refused on volatility alone" and "moves more than 100% annualised" are the same statement. VIX ≥ 30 forces re-analysis of every ticker | New BUYs blocked at risk ≥ 6; sizing shrinks | Automatic — no manual action |

**[GAP] There is no market-wide kill switch.** The daily-loss limit is
per-user and realised-only, so an unrealised drawdown across all positions
triggers nothing. There is also no circuit-breaker on the agent itself — no
"stop trading if N consecutive losses" rule.

### Technology Failures

| Scenario | Detection | Automated action | Recovery |
|---|---|---|---|
| **Database outage** | `/health` reports `degraded` on a failed ping; the pipeline raises | Pipeline cycle fails; **no orders are placed without a database**, which is the safe failure — sizing and guards all read from it | Container restart; APScheduler resumes on the next 5-min tick. [GAP] no automated failover, single Mongo instance |
| **Research agent failure** | Exception per agent inside the `gather` | Dossier is absent or partial; **the veto fails open** and trading continues; the fast path never depended on research | Next daily refresh, or on-demand rebuild |
| **Scoring engine failure** | Exception in the pipeline | That ticker's cycle fails and is retried in 5 minutes; the last published signal stands (which is also why dwell/confirmation matter — a stale verdict does not flap) | Automatic |
| **Network interruption** | HTTP timeouts per provider | Each source degrades to its fallback independently; broker reconnect loop as above | Automatic |
| **Cloud-region outage** | External only — the host is gone | **None. Everything stops.** | [GAP] Manual. Single Hetzner VPS, single region, no standby, no automated restore |

**Recovery reality check.** The platform runs as Docker Compose on **one**
Hetzner VPS with **one** MongoDB instance. There are **no automated database
backups configured in this repository** — no `mongodump` cron, no snapshot
policy, no restore drill. A host loss today means losing `trades`,
`stocks_signal_history` (the entire calibration record), `research_dossiers`,
and every user account, with recovery limited to whatever the provider's own
disk snapshots hold. **This is the highest-severity gap in the document** and is
cheap to close relative to its cost.

---

## 9. Security Assessment

### Infrastructure Security

**9.1 Hosting architecture.**
Backend: Docker Compose on a single Hetzner VPS — `api` (FastAPI + APScheduler),
`mongo`, `ibgateway` (headless IB Gateway via IBC), `dockerproxy` (filtered
Docker socket), `cloudflared` (Cloudflare Tunnel terminating HTTPS). No port is
published to the public internet; all ingress arrives through the tunnel.
Frontend: static build on Cloudflare Pages (`sta.samsbpm.com`).
[VERIFIED: `backend/docker-compose.prod.yml`, `infra/`]

**9.2 Cloud providers.** Hetzner (compute), Cloudflare (DNS, tunnel, Pages),
Anthropic / Finnhub / FRED / Alpha Vantage / Massive-Polygon (APIs), IBKR and
optionally Alpaca (execution), Zoho SMTP (mail).

**9.3 Multi-region redundancy.** **No.** Single region, single host, single
database instance. [GAP]

**9.4 Penetration tests.** **None performed.** [GAP] No external test, no
automated scanning in CI, no dependency-vulnerability gate. What does exist is
one hardened decision worth crediting: the Docker socket is never handed to the
API container. A `tecnativa/docker-socket-proxy` sidecar holds it read-only on
an isolated network and answers only `/containers` endpoints — images, volumes,
networks, exec, build and swarm are refused explicitly rather than by default.
The code says plainly that this is a large blast-radius reduction and **not** a
precise "restart only" capability, since `POST=1` also permits other container
verbs, and that the whole service can be deleted if you would rather grant
nothing.

### Identity & Access Management

**9.5 Is MFA supported?** **No.** [GAP] There is no MFA implementation of any
kind — no TOTP, no WebAuthn, no email second factor. Grepping the backend and
both clients returns nothing.

**9.6 Is MFA mandatory?** N/A — see 9.5.

**For a platform that can place orders in a brokerage account, single-factor
authentication is the security gap that matters most, and it should be read
alongside 9.4.** The mitigations that exist are real but partial: bcrypt
password hashing (`passlib`), 24-hour JWT expiry, login rate limiting per email
*and* per client IP, responses deliberately identical for "no such user" and
"wrong password" so accounts cannot be enumerated, and a startup check that
refuses the shipped placeholder JWT secret — anyone who read the source could
otherwise forge a token granting every endpoint including order placement.
[VERIFIED: `services/auth.py`, `routes/auth.py`, `config.py::DEFAULT_JWT_SECRET`]

**9.7 Privileged account management.** [GAP] There are no privileged accounts —
the tier system and admin portal were removed in `f61066f7` when this became a
personal tool. As of 1.18.0 there are three access tiers — BASIC, PRO and
TRADER — and only TRADER reaches the broker. Server access is
SSH with a key held by one person.

**9.8 Credential rotation.** [GAP] No policy and no schedule. Secrets live in
GitHub Actions secrets scoped to the `Production` environment and are written
into `.env.production` at deploy time. One rotation hazard is documented in the
code: `ENCRYPTION_KEY` must never be rotated without first re-encrypting every
stored `ibkr_password_enc`, or every user's broker credential becomes
undecryptable.

### Data Protection

**9.9 Encryption.**
- **In transit:** TLS everywhere externally — Cloudflare Tunnel to the API,
  Cloudflare to Pages, TLS to every vendor API, STARTTLS to SMTP. The IB
  Gateway socket is container-to-container on an internal Docker network and is
  not encrypted; it is also not reachable from outside the host.
- **At rest:** IBKR credentials are **Fernet-encrypted** (AES-128-CBC + HMAC)
  in MongoDB with a key held only in the environment. Passwords are bcrypt
  hashes, never reversible. [GAP] The rest of the database — trades, signals,
  watchlists, email addresses — is **not** encrypted at rest beyond whatever
  the provider's disk encryption gives.

**9.10 Are customer portfolios segregated?**
Logically, yes — every collection is keyed by `user_id` and every trading query
filters on it; IB connections are per-user (Option C), so one user's orders go
to their own broker session under their own credentials. [GAP] Segregation is
enforced in application code, not by database-level access control, and there
is no automated test asserting that a query cannot cross the user boundary.

**9.11 Audit logging.**
Structured application logging throughout (`utils/logger.py`), and the
domain records are themselves an audit trail: every trade carries its trigger,
score, sizing basis, guard outcome, notification claims and commission
execution ids; every signal is written to `stocks_signal_history` and later
settled with its 20-day return. [GAP] There is **no tamper-evident or
append-only audit log** — an operator with database access can alter any record
— no log shipping, no retention policy, and no alerting on the logs. Container
logs are local and rotate with Docker's defaults.

---

## 10. Operations & Reliability

### Service Levels

**10.1 Uptime for the last 12 months.** Not available — the platform is three
weeks old. [GAP] There is no uptime monitor of any kind: no external health
check, no status page, no Prometheus/Grafana, no error-tracking service. The
`/health` endpoint exists and reports database connectivity (returning
`degraded` rather than failing, so an uptime checker sees a distinguishable
state), but nothing polls it.

**10.2 MTTR / MTBF / incident count.** Not tracked. [GAP] No incident register.
Reconstructing one from the changelog: at least three production defects in
three weeks were significant enough to ship a release — HXL alert storm
(24 Aug), NVDA order storm (25 Aug), exits never settling (fixed 27 Aug) — plus
an index bug that took production down, which is recorded in engineering notes
as having reached prod because tests ran against a stubbed MongoDB rather than
a real one.

**10.3 Monitoring and alerting.**
What exists is *user-facing* alerting rather than operational monitoring:
email, Slack webhook and WhatsApp (via CallMeBot) for signal changes, order
placed / filled / exited, a daily digest, and a broker disconnection alert
after 15 minutes. Mail failures are deliberately swallowed
everywhere except the contact form, so an SMTP outage never stops trading —
which also means a silent notification channel would not be noticed.
Since 1.16 there is also a user-facing **System status** screen and a
transition alert on the same channels: when a data source starts failing, or
recovers, one message goes out naming what it costs the score. It fires on the
*change* only, requires two consecutive bad cycles before it speaks, and never
mentions a key the operator simply chose not to set.

[GAP] That is still not operational monitoring. It is passive — every row is
what a source did on the last pipeline cycle, never a probe — and it is read
through the app rather than by an external checker, so it cannot report that
the app itself is down. Nothing alerts on: a frozen price feed, provider quota
exhaustion, database growth, disk, or memory.

**10.4 Disaster recovery.** [GAP] **No DR procedure exists.** No backups
(confirmed: no `mongodump`, no snapshot job, no backup tooling anywhere in the
repository), therefore no restore procedure and no restore drill, therefore no
meaningful RPO or RTO. Two runbooks exist for narrower failures
(`ib-gateway-offline.md`, `scale-in-paper-verification.md`) and are good; they
do not cover host or data loss.

### Change Management

**10.5 Production releases.** Push to `main` → GitHub Actions → SSH to Hetzner
→ `git pull` → generate `.env.production` from Production-scoped secrets →
`docker compose up --build -d`. Frontend deploys separately to Cloudflare Pages.
Backend, frontend and mobile share one version, declared in four places that
move together, and `CHANGELOG.md` is updated **in the same change that ships the
behaviour** — a discipline the repository actually keeps.

**10.6 Formal CAB.** None. Single engineer, no review gate. [GAP]

**10.7 Rollback.** By git revert and redeploy — roughly 3–5 minutes. There is
no one-command rollback, no blue/green, no canary, and **no database migration
rollback**: schema changes are forward-only helpers in `db.py`
(e.g. `_migrate_trading_mode`), so reverting code does not revert data. [GAP]

**10.8 Testing before deployment.**
303 backend tests across 17 files — concentrated, sensibly, on the parts that
move money: scale-in (43), research orchestration (32), dimension scoring (31),
trade notifications (27), catalyst (20), signal stability (18), calibration
(18), risk and sizing (16), exit settlement (14), research veto (14). The web
client has `npm run lint:a11y` (jsx-a11y) which must stay clean and which
caught four defects a manual sweep missed; suppressions require a written
reason and there are two.

**[GAP] None of it runs in CI.** The deploy workflow contains no `pytest`, no
lint, and no build gate — grepping `.github/workflows/` for test invocations
returns nothing. Tests are run locally at the author's discretion and a push to
`main` deploys regardless of whether they pass. This is the cheapest gap in the
entire document to close and should probably be closed before the next
conversation about it.

Two further testing notes, both known: startup-path code needs a **real**
MongoDB — a stubbed one let an index bug reach production — and there is no
frontend or mobile unit/E2E suite at all.

---

## 11. Compliance & Regulatory

**11.1 Is the company a registered investment adviser / broker-dealer /
portfolio manager?**
**No — none of the three.** [TO CONFIRM as a legal position, but the
engineering answer is unambiguous: no registration exists.]

**11.2 Licences held.** None. [TO CONFIRM]

**This is the third thing a serious buyer should press on, and it constrains
the product more than any technical gap.** The system generates buy/sell
recommendations and can place orders in a user's own brokerage account. Whether
that constitutes providing investment advice or discretionary management —
which in most jurisdictions requires registration — is a question for
securities counsel, not for this document. What can be said from the code:

- The platform never custodies assets or money. Orders route to the user's own
  IBKR/Alpaca account under the user's own credentials.
- The autonomy dial exists partly for this reason. MANUAL/SEMI_AUTO keep a
  human on every order, and new accounts default to MANUAL.
- One regulatory rule *is* implemented in code: **CIRO** — API-based automated
  trading is permitted only for US-listed securities, so Canadian-listed
  tickers are refused at the first guard in the chain.

**11.3 Jurisdictions where customers may use the platform.** [TO CONFIRM] —
undetermined. No geo-restriction, no KYC, no jurisdiction check exists in the
software; the only geography-aware logic is the CIRO listing check.

**11.4 Disclosures provided to users.** Partial, and better than nothing.

What exists: a **"Not financial advice"** disclaimer carried in both the
landing-page footer and the application shell (`components/Layout.tsx`),
stating that the platform is not a registered investment adviser,
broker-dealer or portfolio manager, that signals are model output rather than
research, that past signal accuracy does not predict future results, and that
trading risks total loss of capital. The landing page is also careful about
claims — every statement on it is something the engine actually does, the
sample readout is labelled a sample, and the public FAQ (section 05) states
plainly that no real money has ever been traded through the platform.

[GAP] What does not exist: **no terms of service, no privacy policy, no
per-signal risk disclosure at the point of decision**, and no record that a
user acknowledged any of it. For a tool that prints BUY next to a ticker, that is a
gap to close before the first external user, not after.

**11.5 Compliance monitoring.** [GAP] None beyond the CIRO guard.

**11.6 Customer complaints.** [GAP] No process. The contact form is the only
inbound channel; it delivers to `CONTACT_EMAIL` and is the one mail path that
reports failure to the sender rather than swallowing it, because a visitor told
"sent" when nothing was sent has been lied to and has no other route to anyone.

---

## 12. Customer References

**12.1 Three customer references.** None exist. There are no customers.

**12.2 A reference managing a live account over $100K / $500K / $1M.** None.
No live account of any size exists on the platform.

**12.3 Successful deployments, failed deployments, lessons learned.**
No customer deployments. The internal record, offered instead because it is the
only honest thing available and is more informative than a reference would be:

**What has worked.** Continuous deployment for three weeks with a complete
behaviour-level changelog; the guard chain has held (no unbracketed position
has been left unprotected since scale-in reconciliation shipped); the evidence
ledger has done what it was built to do.

**What has failed, and what it taught.**

| Incident | Date | Lesson, as implemented |
|---|---|---|
| Alert storm — 8 alerts in 65 min at an unchanged score | 24 Aug | Computing a verdict and publishing one are different acts. Confirmation + dwell now sit between them |
| Order storm — 8 orders, 7 of them for 1–2 shares | 25 Aug | Read the sizing basis live and a full position gains room all session. Freeze equity at entry; make every add condition a rate limit |
| Exits never reached `CLOSED` | 27 Aug | An unsettled exit means the daily-loss kill switch can never fire. Settlement is part of the risk system, not bookkeeping |
| Citation audit silently discarded at the API boundary | 26 Aug | A model with no field for a key drops it silently — "clean" and "never checked" became indistinguishable. Audits need their own schema |
| Index bug reached production | — | Startup-path code must be tested against a real MongoDB, not a stub |
| BUY/SELL arithmetically unreachable | — | Check score *variance* before suspecting the trading path — the signals were dead, not the executor |
| Fundamentals pinned at 0.5 for a mega-cap for 24h | 21 Aug | A graceful fallback that never resolves is a silent failure. Hence cold-start backfill |

The pattern across all seven is the same: **the failures were not in the
strategy, they were in the seams** — between computing and publishing, between
sizing and retrying, between placing and settling. That is worth saying plainly
to any investor, because it also describes where the remaining risk is.

---

# 13. Additional Questions

Questions the supplied questionnaire does not ask but which an investor, a
customer, or a technical architect will — answered here so they are not
answered improvised in a meeting. Grouped by who tends to ask them.

## 13A. For an investor

**What is the actual product, in one sentence, and who is the buyer?**
A per-user autonomous equity agent: it scores a watchlist every five minutes,
publishes a verdict only once it holds, and — at a level of autonomy the user
chooses — places bracketed orders into the user's own brokerage account. The
buyer is a self-directed retail investor with an IBKR account. There is no
paying buyer yet.

**What is the moat?**
Not the factors — RSI, MACD, VADER and P/E are commodities. If there is a
defensible asset it is the *discipline layer*: the confirmation/dwell publisher,
the frozen sizing basis, the single guard chain shared by every order path, the
evidence ledger that deletes uncited claims, and the fail-open veto. That is
the part that took seven production incidents to learn and is not obvious to
copy from a screenshot. It should also be said clearly: an incumbent could
build it, and none of it is patented.

**What is the unit economics picture?**
Infrastructure is one small VPS plus Cloudflare — negligible. The real variable
cost is model inference, and it has already been a problem: analyst spend hit
roughly **$20/day** and was dominated by *output* tokens, not calls. Two levers
were built rather than one. **Gating**: Claude is only called near a decision
boundary (within `ANALYST_GATE_MARGIN=0.08` of a threshold, so score ≥ 0.62 or
≤ 0.38) because 592 of 602 recorded signals were HOLD and a ticker sitting at
0.47 produces the same HOLD either way; open positions are exempt, because once
capital is committed the exit call is the most consequential one the analyst
makes. **Caching**: re-analysis only on staleness, a ≥3% price move, a ≥0.12
score shift, or VIX ≥ 30. Deep research is a further five calls per dossier and
is therefore daily/on-demand and off by default. [TO CONFIRM] Current
steady-state monthly spend per active watchlist ticker has not been measured
since gating shipped; it should be, before any pricing conversation.

**How would you price it, and what does that imply?**
[TO CONFIRM] — no pricing exists. Note the constraint the cost structure
imposes: per-user model spend scales with watchlist size and with how many
names sit near a threshold, so a flat subscription with an unbounded watchlist
is a margin risk. Watchlist caps or metered research are the obvious answers.

**What would you do with funding, ranked?**
On the evidence in this document: (1) close the backup/DR and CI gaps — days,
not weeks; (2) build a real point-in-time backtest on `financial_statements`
plus settled signal history, since Section 3 is currently empty and no
sophisticated buyer will get past it; (3) licensed market data as the default;
(4) securities counsel on Section 11; (5) a second engineer, because the bus
factor is one.

**What is the single biggest risk to the business?**
Not technical. It is Section 11: a determination that the product constitutes
unregistered investment advice or discretionary management would gate
distribution entirely, and it is unresolved.

**What is the biggest technical risk?**
That the strategy has no evidence behind it (Sections 2.4 and 3). The
engineering around the strategy is unusually careful; the strategy itself has
never been validated on out-of-sample data. Those two facts are easy to confuse
when reading the code, and should not be.

**How long is the runway / what is the burn?** [TO CONFIRM] — founder time plus
low hundreds of dollars a month in infrastructure and API spend.

**Is there any IP encumbrance?** Apache 2.0 licensed with a NOTICE file;
dependencies are standard OSS. [TO CONFIRM] whether any employment agreement
creates an ownership claim over work done on this codebase.

## 13B. For a prospective customer

**Will it trade my money without asking me?**
Only if you set it to. Autonomy is a three-position dial and **new accounts
default to MANUAL**, where the agent does all the work — every guard, the
sizing, the bracket levels — and then writes a *proposal* you approve or
decline. SEMI_AUTO executes only at or above your conviction floor and proposes
everything else. AUTO is opt-in. A live-money order additionally requires you
to type the ticker back before it will send.

**What happens to my money if your servers die?**
Your positions are unaffected — the platform never holds assets or cash, and
protective stops live **at the broker**, so they survive this app crashing, the
gateway dropping, or the host going down. What stops is new orders and
signal-driven exits: the agent does not sell on its own outside a SELL signal,
and a SELL signal requires the app to be running. An unbracketed position would
have no automatic exit at all, which is why an entry is submitted as a bracket
or not at all.

**Do you have my brokerage password?**
Encrypted, yes — Fernet at rest in MongoDB, decrypted only in memory to
authenticate the IB Gateway session. This is genuine custody of a credential
and you should weigh it accordingly, especially against the absence of MFA on
your platform account (9.5). The credential never leaves the host and is never
sent to any model.

**Can it lose more than I told it to risk?**
The designed answer is no: 5% per position, 5 positions, 2% realised daily loss
kill switch, 5% cash reserve, margin disabled so it cannot buy what it cannot
pay for. The honest caveats: the daily-loss switch is **realised-only**, so
unrealised drawdown does not trip it; a stop fills at the next available price,
not the stop price, so an overnight gap can exceed the intended loss; and there
are no sector or correlation limits, so five positions can be one bet.

**What has it actually returned?**
Nothing has been traded with real money, and the paper record is three weeks
long and tests plumbing rather than signals. Any number quoted from it would be
misleading. This is the correct answer today and it will stay the answer until
Section 3 and Section 4 have content.

**Why did it not buy something I expected it to?**
Every refusal records a reason, and the score attribution and risk gate are
returned by the API rather than restated in the UI — you can see each factor's
sub-score, its weight, the points it contributed, and which threshold the
ticker failed. Verdicts are also deliberately *slow*: a change publishes only
after consecutive fresh evaluations agree and the standing verdict has served
its dwell, so a borderline name will not flip at you all afternoon.

**Why did it sell immediately when it waits to buy?**
SELL is exempt from confirmation, dwell and the risk gate, on purpose. Delaying
an exit costs money; delaying an entry costs an opportunity. Those are not the
same price, and no brake will be added to the exit path to make the two
symmetrical.

**Can I use my own weights?** Yes — per-user scoring weights, applied at read
time, with the same thresholds and the same hysteresis as the stored signal, so
your view and the engine's cannot silently diverge.

**Is my data sold or used to train models?** No. Prompts to Anthropic carry
market data, not identity, positions, or credentials. [TO CONFIRM] this should
also be stated in the privacy policy that does not yet exist (11.4).

**Web or mobile?** Both, at parity — order ticket, proposal queue, orders,
chart, calibration, factor breakdown, risk gate, holdings. The two safety
behaviours are identical on both: the displayed quantity is never
authoritative (the server clamps a client request to what the risk model sizes
to), and a live order or approval requires typing the ticker back.

**What if the AI hallucinates a reason to buy?**
Two structural answers. In the fast path, the model's output never *creates* a
trade on its own — the score does, and the model's levels are validated
(a stop above entry or a target below entry is rejected in favour of
percentage fallbacks). In the research path, uncited claims are deleted before
storage and fabricated citation ids are recorded, and research **may only veto
a BUY — never create one, enlarge one, or reach an exit**.

## 13C. For a technical architect

**Where is the single point of failure?**
Several, and they are the same box: one VPS, one MongoDB, one IB Gateway
container, one scheduler process. There is no queue between the scheduler and
the executor; jobs run with `max_instances=1`, so an overrunning cycle causes
the next tick to be **skipped rather than queued** — work is dropped, not
absorbed, and nothing currently alerts on that.

**Is the scheduler safe to run in more than one replica?**
**No, and this is the most important scaling answer.** APScheduler runs
in-process with no distributed lock, and the rate limiters (login, contact) are
in-process too — a second replica would run the pipeline twice and keep its own
counters. Horizontal scaling therefore requires extracting the scheduler into a
single leader-elected worker (or a proper job queue) before adding an API
replica. Nothing today prevents someone from scaling the container and
double-trading.

**What actually prevents a duplicate order?**
A unique **sparse index on `(user_id, idempotency_key)`** — not the route's
lookup. The distinction matters: a lookup loses a race, an index does not. This
is the correct pattern and it is worth confirming it is the one relied upon.

**How does the system converge with the broker's view of the world?**
`reconcile_trades` runs every two minutes, re-reads a 24-hour fill window, and
treats the venue as authoritative: it settles fills, cancels stale legs, places
one OCA pair sized to what the venue says is *held*, heals unprotected
positions, settles exits, and accrues commission. Commission accrual is
**idempotent by execution id** (`commission_exec_ids`) because a re-read window
would otherwise double-count and climb for as long as the app stayed up.

**What is the read-consistency model between clients and the engine?**
Clients never restate engine constants. Thresholds, weights, the risk scale and
the analyst model identifier are all returned by the API from the modules that
own them. This was a real defect class — `compute_personalized_score` once held
its own copies of the thresholds, so tuning one place put custom-weight users
on a different model from the stored signal, silently.

**How large can a watchlist get before something breaks?**
The binding constraint is provider quota, not compute: Alpha Vantage's 25/day
cap against two call types already forces a 22-call budget and a 7-day earnings
cache at ~29 tickers. Beyond roughly 30–40 tickers per user the fundamentals
refresh cannot complete daily without a paid tier. Model spend is the second
constraint (13A).

**What is the schema migration story?**
Forward-only helpers invoked at startup in `db.py`. No versioned migration
tool, no down-migrations, no dry-run. Combined with no backups (10.4), a bad
migration is currently unrecoverable — the two gaps compound and should be
fixed together.

**How would you test this without a broker?**
Broker and model clients are injectable — `build_dossier(..., client=)` exists
specifically so orchestration is testable without the SDK, and the analyst call
it replaces built its client inline and has no tests to this day. That is the
pattern to extend. What is missing is an integration environment: 303 unit
tests, zero end-to-end tests against a real Mongo and a paper gateway, which is
exactly the seam where six of the seven production incidents happened.

**Why MongoDB for financial records?**
Pragmatic — schemaless documents suited fast iteration on feature shapes.
The honest counterpoint: trades and executions are relational, money is
involved, and there are no multi-document transactions in use. If the trade
ledger ever needs strict invariants across records, this is the decision to
revisit.

**What is the observability story?** Structured logs, and nothing else. No
metrics, no traces, no dashboards, no alerting on system health. See 10.3.

**What is `alternative_data` doing outside the weight normalisation?**
It is an additive modifier centred on 0.5 (±0.05 at the default weight), not a
seventh share, so it nudges a score rather than diluting the six factors — and
it can drag a score down, which a normalised share cannot. Short interest is
deliberately computed but **not scored**, because its direction is ambiguous
(high short interest is both a bearish signal and squeeze fuel); it is
displayed only.

**Why is earnings proximity a bonus rather than a factor?**
Because as a weighted component its *absence* would cost coverage, and coverage
is a penalty — so every ticker past the Alpha Vantage daily cap would score on
a narrower range than one inside it, for a reason that has nothing to do with
the company. An additive bonus has no such asymmetry.

**What happens on a partial fill?** Reconciliation sizes protection to what the
venue reports as held, so a partial fill is protected for the filled quantity —
the invariant that protective orders may never cover more shares than are held
is enforced from the broker's numbers, not the app's intent.

**Is there a data-retention or deletion path?** [GAP] No. There is no account
deletion, no data export, and no retention policy — which is also a GDPR/PIPEDA
question the moment there is a user outside the founder.

---

# 14. Gap Register, Prioritised

Every **[GAP]** above, ordered by what a reader should worry about first.
Effort is engineering-days for the current single engineer.

| # | Gap | Section | Severity | Effort |
|---|---|---|---|---|
| 1 | **No database backups, no restore procedure, no drill** | 8, 10.4 | Critical | 1 |
| 2 | **No registration determination; no ToS or privacy policy** (a "not financial advice" disclaimer does exist) | 11 | Critical | External counsel |
| 3 | **No validated strategy evidence — backtest is a stub** | 3 | Critical | 10–15 |
| 4 | **Tests do not run in CI; push to `main` deploys regardless** | 10.8 | High | 0.5 |
| 5 | **No MFA on an account that can place orders** | 9.5 | High | 2–3 |
| 6 | Production defaults to an unlicensed price source | 6.1 | High | 0.5 + vendor cost |
| 7 | Bus factor of one | 1.3 | High | Hiring |
| 8 | No *external* uptime monitoring. A status screen and degrade/recover alerts ship in 1.16, but both run inside the app and cannot report that the app is down | 10.1, 10.3 | High | 1 |
| 9 | Signals do not record the weights/model version in force | 2.8, 2.9 | Medium | 0.5 |
| 10 | No sector/correlation/concentration limits | 7.2 | Medium | 2 |
| 11 | Kill switch is realised-only; no unrealised-drawdown halt | 8 | Medium | 1 |
| 12 | No price-feed staleness detection | 6.5 | Medium | 1 |
| ~~13~~ | ~~No input-completeness figure on a signal~~ — **closed in 1.16** | 6.6 | — | done |
| 14 | Scheduler and rate limiters are in-process — cannot scale out | 13C | Medium | 3–5 |
| 15 | No end-to-end tests against real Mongo + paper gateway | 13C | Medium | 3 |
| 16 | Factor correlations never measured | 2.7 | Medium | 2 |
| 17 | No penetration test or dependency scanning | 9.4 | Medium | 1 + vendor |
| 18 | No tamper-evident audit log, no log shipping/retention | 9.11 | Medium | 2 |
| 19 | No account deletion / data export / retention policy | 13C | Medium | 2 |
| 20 | Forward-only migrations with no rollback (compounds #1) | 10.7 | Medium | 2 |
| 21 | Citation rejection rate not aggregated across dossiers | 5.6 | Low | 0.5 |
| 22 | Risk-agent disagreement rate not measured | 5.10 | Low | 0.5 |
| 23 | No deep links from evidence to source documents | 5.8 | Low | 1–2 |
| 24 | Fast-path lineage is provider-level, not fact-level (shipped 1.16); it cannot say which provider supplied a particular ratio | 6.7 | Low | 1 |
| 25 | No single-command rollback / canary | 10.7 | Low | 1 |
| 26 | Mobile screens hardcode a light-only palette | — | Low | 1 |

**Items 1 and 4 together are under two days of work and remove the two most
embarrassing answers in this document.** They should not survive the week in
which this questionnaire is sent.
