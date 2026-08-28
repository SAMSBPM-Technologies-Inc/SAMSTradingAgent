# 11 — Data paths: what runs, when, why, and what it costs

Every route into this system, what it calls, what it needs, and how its limits
reach the person using it.

Written against the code, not against intent. Where production disagrees with
the design, the disagreement is recorded rather than smoothed over — see
[Observed production state](#observed-production-state), which is the section
most likely to go stale and the one worth re-running.

---

## The two analysis paths, and why they are separate

The single most common misreading of this system is that `/analyze` and
`/research` are the same engine at different depths. They are not. They share
almost no code, run on different schedules, cost different amounts, and answer
different questions.

| | **Fast path** — `/analyze` | **Research path** — `/research` |
|---|---|---|
| Question | What is the verdict on this name *right now*? | What is the case for and against this company? |
| Trigger | Every 5 min per ticker, and on page load | Once a day, or when a user explicitly asks |
| Cost | One Claude call, and only when gated in | **Five** Claude calls, two on the larger model |
| Latency | Sub-second cached; seconds cold | Tens of seconds |
| Calls providers? | **Yes** — Yahoo, Finnhub, FRED | **No.** Cache-only, reads what the fast path stored |
| Output | Score, signal, risk gate, short narrative | Evidence ledger, four agent reports, synthesis |
| Blocks a trade? | Yes — it *is* the signal | Only as a veto, never to create or enlarge |
| Feature flag | Always on | `RESEARCH_AGENTS_ENABLED` |

### Why the orchestrator is not on the fast path

Four reasons, in descending order of how much they matter.

**1. Cost per call, multiplied by frequency.** The fast path runs every five
minutes per ticker. At 13 tickers that is roughly 1,000 pipeline runs a
trading day. A dossier is five model calls, two of them on
`research_orchestrator_model` (`claude-opus-5`) with `research_effort: high`
and extended thinking. Putting the fan-out on the fast path multiplies a
deliberately-rationed expense by a thousand. The AI analyst on the fast path is
already gated (`analyst_gate_enabled`) to fire only near a decision boundary,
precisely because even *one* call per cycle was too much — see the
`analyst-cost-controls` history.

**2. Latency the trading loop cannot absorb.** `run_pipeline` is synchronous
and the 5-minute scheduler job holds `max_instances=1`. A path that takes tens
of seconds per ticker would not finish 13 tickers inside its own interval, and
the job would start colliding with itself.

**3. The dossier has nothing fresh to read.** `dossier._load_context` is
documented as *"Cache-only — nothing here calls a provider."* It assembles from
`stocks_features`, `stocks_raw` and the fundamentals cache. Running it more
often than those are refreshed produces the same report from the same inputs.
This is also why `_research_refresh_job` is scheduled *after*
`_fundamentals_refresh_job` — the ordering is load-bearing, not tidy: build a
dossier before the cache is warm and you get a report about yesterday.

**4. Different failure tolerance.** A fast-path failure must degrade to a
verdict — every enrichment source is wrapped so it can return nothing without
stopping the score. A research failure is allowed to return `None` and produce
no dossier at all, because *"an empty report is indistinguishable from a bad
one at a glance."* Those two stances cannot live in one function.

The consequence worth internalising: **the orchestrator and the risk agent
never run while a ticker page loads.** That is why the loading screen does not
list them.

---

## Path A — the fast path

`GET /analyze?ticker=X` and the 5-minute `market_pipeline` job both land in
`services/pipeline.py::run_pipeline`.

**Cache first.** `routes/analysis.py` serves `stocks_signals` directly when the
stored document is younger than `_CACHE_TTL_MINUTES` (30). This is the common
case; the pipeline below runs only on a miss.

| Step | Module | Providers | Notes |
|---|---|---|---|
| 1 | `ingestion.ingest_ticker` | Yahoo (`price_provider: yahoo`) | OHLCV bars. Raises if empty — the one hard failure |
| 2 | ↳ enrichment | Finnhub, FRED, fundamentals **cache** | All degrade gracefully; none can stop a score |
| 3 | `feature_engineering` | none | RSI, MACD, Bollinger, ATR, OBV, Stochastic RSI |
| 4 | `scoring.score_ticker` | none | Six weighted factors; weights validated to sum to 1.0 |
| 5 | `analyst.run_analysis` | Anthropic | Gated *and* cached — usually skipped |
| 6 | `signal_generator` + `signal_stability` | none | Verdict, then the confirm/dwell gate before publishing |

**`price_provider` is `yahoo` in production.** Massive (Polygon) is configured
and its key is set, but it supplies *fundamentals*, not bars. Yahoo is an
undocumented endpoint hit with a browser User-Agent — fine for development,
**not licensed for commercial use**. Switching to `polygon` needs a Massive plan
that includes aggregates.

---

## Path B — the research path

`services/research/dossier.py::build_dossier`.

1. `_load_context` — cache-only read of features, raw and fundamentals.
2. `_assemble` — builds an evidence `Ledger`. Every fact gets an id, value,
   source and date. Returns `None` if fewer than **5 substantive** facts exist
   — counting facts about the company, not "not available" lines.
3. `_fan_out` — four specialists concurrently via `asyncio.gather`:
   **Fundamentals**, **Technical**, **News**, **Risk**. `return_exceptions=True`
   so one failure cannot cancel its siblings. An agent whose slice holds no
   substantive facts is skipped without a model call.
4. `_synthesise` — merges. May not introduce a fact nobody raised, and **must
   address or carry every risk the Risk agent raised**.
5. `_persist` — appends to `research_dossiers`, retained as a series.

**The Risk agent is not shown the bull case.** Given a thesis, a red team argues
against *that thesis* and inherits its framing. It runs inside the fan-out on
the same evidence as everyone else.

**Conviction is anchored.** Derived from the scored dimensions; the synthesiser
may move it ±15 and must explain why. Five of the six dimension scores are
Python, not model output — only `business_quality` is model-judged, and it is
flagged as such.

**Citations are enforced by deletion, not by warning.** An uncited claim is
stripped before storage; a fabricated evidence id is stripped *and recorded* in
`citation_audit` on the dossier.

**Verb split.** `GET /research/{ticker}` reads the stored dossier — free, fast,
possibly stale, 404 if none exists. `POST` builds one — slow, costs money, rate
limited, and 503 when `RESEARCH_AGENTS_ENABLED` is false. A GET must never
silently trigger a build.

### How research reaches trading

Through exactly one door: `_research_veto` inside `_prepare_entry`.

> **Research may veto a BUY. It may never create one, enlarge one, or reach an
> exit.**

Every uncertain path — missing dossier, stale, undated, database error —
**allows** the trade. A guard that halts buying because a cron job misfired is a
worse failure than one that occasionally lets a trade through. `execute_exit`
does not run the guard chain at all.

---

## Path C — the trading path

Every order, agent or human, goes through `_prepare_entry`: CIRO checks,
position cap, daily-loss kill switch, cash reserve, refusal to open unbracketed,
and the research veto. `execute_entry` and `execute_manual_entry` share it.

A manual order differs in exactly two documented ways: no signal-score threshold
(the human is the signal) and no whitelist (that restricts what the *agent* may
pick).

Autonomy is `AutoTradeSettings.mode` — `MANUAL` / `SEMI_AUTO` / `AUTO`. Under
MANUAL, and under SEMI_AUTO below `auto_execute_conviction`, a fully-sized order
is written as a `PROPOSED` trade instead of being sent. **`PROPOSED` is
deliberately not in `TradeStatus.OPEN`**: it consumes no position slot and never
reaches realised performance.

**SELL is exempt from every delay.** Delaying an exit costs money; delaying an
entry costs an opportunity.

---

## Scheduled jobs

| Job | Schedule | Purpose | Needs |
|---|---|---|---|
| `market_pipeline` | every `INGESTION_INTERVAL_MINUTES` (5), market hours | The signal engine | Yahoo, Finnhub, FRED |
| `reconcile_trades` | every 2 min in window | Observe fills, accrue commission, place OCA pairs | IB Gateway |
| `fundamentals_refresh` | 07:00 ET Mon–Fri | Warm the cache before signals read it | Massive, Alpha Vantage |
| `research_refresh` | `RESEARCH_DAILY_REFRESH_HOUR`:30 ET Mon–Fri | Rebuild dossiers, held positions first | Anthropic |
| `premarket_sweep` | 08:00 ET Mon–Fri | News and macro before the open | Finnhub, FRED |
| `perf_tracker` | 06:00 UTC daily | Settle 20-day signal outcomes | none |
| `daily_digest` | 09:00 ET Mon–Fri | Watchlist email | SMTP |
| `broker_watch` | every 5 min, always | Catch a dead gateway before an order does | IB Gateway |

`research_refresh` runs **sequentially** by design. Each dossier is five
internally-concurrent model calls; running tickers in parallel would burst the
API for no benefit, since nothing waits on this job. Held positions go first so
that a truncated run has already covered the names carrying money.

---

## Providers, limits, and what a trader actually feels

| Provider | Supplies | Limit | Cached | If it fails |
|---|---|---|---|---|
| Yahoo | OHLCV bars | Informal; 429s under load | 30 min via signals cache | **Hard failure** — no bars, no analysis |
| Finnhub | Headlines | Plan-dependent | Per pipeline run | Sentiment falls back; score continues |
| FRED | Rates, CPI, VIX | Generous | Per pipeline run | Macro factor degrades to neutral |
| Massive (Polygon) | Financial statements | ~5/min | `FUNDAMENTALS_CACHE_HOURS` (24) | Fundamental score → 0.5 fallback |
| Alpha Vantage | Ratios, consensus, earnings | **~5/min and 25/day** | 24h; earnings multi-day | See below |
| Anthropic | Analyst + research | Account | Analyst cached per ticker | Rule-based narrative instead |
| IB Gateway | Quotes, orders, fills | Session | — | Orders refused, never silently lost |

### The Alpha Vantage budget, worked through

`ALPHAVANTAGE_DAILY_BUDGET` is **22**, against a documented provider cap of 25.

The refresh loop spends one shared budget across two call types. Each ticker
costs **one** call for the OVERVIEW pass, plus **one more** if its earnings
history is due. `_earnings_refresh_due` returns `True` for a ticker with *no*
cached earnings document at all — so on a cold cache every ticker costs two.

At 13 watched tickers:

- **Warm earnings cache** — 13 OVERVIEW calls + earnings for the roughly one
  name in seven that is near reporting ≈ **15 calls**. Comfortably inside 22.
- **Cold earnings cache** — 2 calls each, so the budget is exhausted after
  **11 tickers**. The last 2 get no Alpha Vantage at all.

**What the trader sees when the budget runs out.** Not an error, and not a
missing page. The affected tickers fall back to Massive alone, which still
covers revenue growth, debt/equity and free cash flow — about **70% of the
fundamental score's weight**. The remaining 30% degrades toward the 0.5 neutral
fallback. The visible effect is a fundamental sub-score that is *less
differentiated* for tickers late in the list: the factor breakdown on the ticker
page still renders, still sums correctly, and gives no indication that this
name's fundamental input was thinner than the one above it.

That is the honest weakness. **The order of the refresh list silently becomes a
data-quality ranking**, which is why `refresh_all_fundamentals` documents that
callers must pass held positions and watchlist first, and why
`_research_refresh_job` sorts held-first for the same reason.

**Earnings proximity is an additive catalyst bonus, not a weighted component** —
deliberately, so that a ticker past the daily cap is not scored on a narrower
range than one inside it for a reason unrelated to the company.

### Scaling limit

Above roughly **22 tickers with a warm cache, or 11 cold**, Alpha Vantage stops
being able to cover the universe in a day. That is the practical ceiling on
watchlist size before fundamental scoring quality becomes position-dependent.
Raising it means a paid Alpha Vantage tier or moving those fields to Massive.

---

## Observed production state

Read from the production database on **27 Aug 2026**. Facts, not design.

| Collection | Documents | Expected |
|---|---|---|
| `watched_tickers` | 13 | — |
| `stocks_fundamentals` | 13 | one per ticker ✅ |
| `research_dossiers` | 6 | one per ticker per day ⚠️ |
| `earnings_history` | **0** | one per ticker ❌ |
| `financial_statements` | **0** | append-only, grows ❌ |

Three things worth investigating:

1. **`earnings_history` is empty.** A sample fundamentals document shows
   `source: "massive+alphavantage"`, so the OVERVIEW call *is* succeeding —
   Alpha Vantage credentials and connectivity are fine. But the EARNINGS call
   has never persisted a document. Since `_earnings_refresh_due({})` is `True`
   for every ticker, calls are being spent against the budget on this. **The
   earnings-proximity catalyst bonus is therefore never applied**, and every
   ticker is missing it equally.

2. **`financial_statements` is empty.** `CLAUDE.md` describes it as
   append-only and "the basis for every trend". Nothing has accumulated, so no
   fundamental trend can currently be computed from it.

3. **`research_dossiers` holds 6 for 13 tickers.** Consistent with a
   sequential daily job being cut short, or with `build_dossier` returning
   `None` on the thin-evidence guard — the two are indistinguishable from the
   count alone, and (1) and (2) would both push tickers toward thin evidence.

**Cause not established.** The API container restarted during the 1.11.1 deploy
and the logs that would have shown the failing calls were rotated with it. The
next `fundamentals_refresh` (07:00 ET Mon–Fri) will reproduce the conditions;
grep for `alphavantage` and `fundamentals_refresh_all_done` in the container
logs before that container is replaced again.

---

## Quick reference: what needs what

| To work at all | Requires |
|---|---|
| Any analysis | Mongo, Yahoo reachable |
| Sentiment factor | `FINNHUB_API_KEY` |
| Macro factor | `FRED_API_KEY` |
| Fundamental factor above fallback | `MASSIVE_API_KEY` and/or `ALPHAVANTAGE_API_KEY` |
| AI narrative | `ANTHROPIC_API_KEY` + `ENABLE_AI_ANALYST` |
| Deep research | the above + `RESEARCH_AGENTS_ENABLED=true` |
| Any order | IB Gateway session + `AUTO_TRADE_ENABLED` |
| Live money | additionally `AUTO_TRADE_LIVE_ALLOWED` and per-order `confirm_live` |
