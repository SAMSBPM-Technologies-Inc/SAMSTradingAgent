# 12 — How a trade is judged, and what each system is worth

This document answers two questions that are usually asked together and answered
separately: **how does this thing reach a verdict**, and **what happens to that
verdict when a piece of it is missing**.

It does not restate the other documents. [`09-analysis-sources.md`](09-analysis-sources.md)
describes what each source supplies and how each sub-score is computed.
[`11-data-paths.md`](11-data-paths.md) covers provider limits, costs and the
Alpha Vantage budget arithmetic. [`10-due-diligence.md`](10-due-diligence.md) is
the institutional questionnaire, with a gap register. This one is the chain, and
the price of each link.

Claims below marked **[VERIFIED]** were read out of the code named beside them,
not recalled. Where something cannot be known, the document says so rather than
estimating.

---

## Part A — The chain, in one pass

Ten steps run between a price bar and an order. Each is a separate act, and
several exist specifically to *refuse* to act.

**1. Ingest** — `services/ingestion.py`. Ninety days of daily OHLCV from the
configured provider, then five enrichment fetches concurrently: news sentiment,
headlines, fundamentals, macro, alternative data. Each of the five degrades to a
documented safe default rather than failing the run. Bars do not.

**2. Features** — `services/feature_engineering.py`. RSI-14, MACD, Bollinger %B,
Stochastic RSI, MA-20/50, ATR, OBV, ADX, volume anomaly, 20-day realised
volatility. From those and the enrichments, six sub-scores plus one modifier,
each on 0–1.

**3. Composite** — `services/scoring.py`.

```
base  = 0.30·technical + 0.20·fundamental + 0.20·sentiment
      + 0.15·macro + 0.00·volatility + 0.15·catalyst      (sums to exactly 1.0)

score = clamp( base + 0.10·(alternative_data − 0.5) )     (signed modifier, ±0.05)
```

The six weights are validated to sum to 1.0 at startup and the app refuses to
boot otherwise. Volatility is weighted **0.00 by default and deliberately** — it
is priced at the risk gate instead, and scoring it here charged the same fact
twice. Alternative data is additive rather than a seventh share, so it nudges the
base and can drag it down. [VERIFIED: `config.py`, `services/scoring.py`]

**4. Risk** — `services/risk_engine.py`. A 0–10 score, of which volatility is up
to 7 points.

**5. Classification** — `signal_generator.classify_signal`. BUY above 0.70 **and**
risk below 6; SELL below 0.30; HOLD otherwise. BUY is the only verdict gated on
risk, and that asymmetry is deliberate: the gate asks "is it safe to take on this
exposure", which has no bearing on whether to leave one you already hold. A
one-sided hysteresis band of 0.03 makes an existing verdict sticky without making
a new one easier to acquire.

**6. Publication is a separate act** — `services/signal_stability.py`. Computing
a verdict and publishing one are different things. A changed verdict becomes a
*candidate* and publishes only after `SIGNAL_CONFIRMATIONS` consecutive **fresh**
evaluations agree — cache hits confirm nothing — and the standing verdict has
lasted `SIGNAL_MIN_DWELL_MINUTES`. **SELL is exempt from every delay**: delaying
an exit costs money, delaying an entry costs an opportunity.

**7. The analyst** — `services/analyst.py`. Runs only when the ticker is near a
decision boundary and the cached read is stale. It produces the thesis, a stop, a
target, and **conviction** — which step 8 depends on.

**8. Autonomy** — `models/trade.py::may_auto_execute`. `MANUAL` never places an
order; `SEMI_AUTO` places only at or above `auto_execute_conviction`; `AUTO`
places everything that clears the guards. Anything not placed is written as a
`PROPOSED` trade — a recommendation with the arithmetic already done, which
commits nothing and consumes no position slot.

**9. The guard chain** — `trade_manager.py::_prepare_entry`. Every order path
goes through it: the agent's, a proposal you approved, and one you typed
yourself. CIRO restriction, ticker whitelist, research veto, open-position cap,
daily-loss kill switch, cash reserve, broker connectivity, and a refusal to open
a position it cannot bracket. A manual order differs in exactly two documented
ways — no signal-score threshold (you are the signal) and no whitelist (that
restricts what the *agent* may pick). [VERIFIED: `trade_manager.py`]

**10. Sizing, then the order.** Position size is a fraction of account equity
**frozen at entry**, adjusted for volatility, and measured on cost basis, so a
falling price cannot free up room to average down. The order goes out bracketed.

Exits run a deliberately shorter path: no score threshold, no fee floor, no
research veto, no stability delay. Everything that slows an entry is absent from
an exit on purpose.

---

## Part B — What each system is worth

Three tiers. The tier is the answer to "what actually happens without this", and
the same three groupings appear on the **System status** page in the app, so the
page and this document read against each other.

### Tier 1 — Stops trading

| System | Without it |
|---|---|
| **MongoDB** | Nothing runs. |
| **Price feed** | The cycle raises for that ticker. No score is written, no order is evaluated, and the previous verdict stays on screen without the agent acting on it. **Trading pauses rather than running on stale prices.** There is deliberately no fallback from a licensed provider to the unlicensed one — that would quietly reintroduce the exposure the switch exists to remove. [VERIFIED: `price_providers.py:200`, `ingestion.py:39`] |
| **≥20 price bars** | Feature computation refuses. A listing younger than 20 sessions cannot be scored at all. [VERIFIED: `feature_engineering.py:42`] |
| **IB Gateway session** | Orders are refused, never silently lost. Entries retry on the next 5-minute cycle; a close *you* press raises rather than reporting a success that did not happen; reconciliation stops instead of reading an empty position list as a flat account. |

### Tier 2 — Changes what the agent does

| System | Without it |
|---|---|
| **`ANTHROPIC_API_KEY`** | Verdicts come from the rule-based path, which is a supported mode. **But the analyst is what produces conviction, and `SEMI_AUTO` refuses to act on an absent conviction** — so every entry becomes a proposal awaiting approval. The mode still reads SEMI_AUTO and nothing names the cause. AUTO and MANUAL are unaffected. This is the most consequential silent degradation in the system. [VERIFIED: `pipeline.py:88`, `models/trade.py:67`] |
| **`ENABLE_ML_MODEL`** | Scores come from the six weighted factors. This is the default and the normal state — see the scenario in Part C. |
| **`RESEARCH_AGENTS_ENABLED`** | No dossiers. The research veto has nothing to read and allows every entry — it fails open on *every* uncertain path, deliberately: a guard that halts buying when a cron job misfires is a worse failure than one that occasionally lets a trade through. |
| **`AUTO_TRADE_ENABLED` / `AUTO_TRADE_LIVE_ALLOWED`** | The agent places nothing; live-money orders additionally require a typed per-order confirmation. |

### Tier 3 — Degrades a score quietly

This is the tier that needed a document. Each of these fails **silently**: the
factor goes to a neutral 0.50, the verdict still publishes, and nothing about the
screen looks different.

| System | Without it | Cost |
|---|---|---|
| **`FINNHUB_API_KEY`** | Sentiment pinned to 0.50 for every ticker. It stops *distinguishing* between names rather than scoring them badly. Headlines also vanish from the analyst's prompt. | 0.20 of the composite |
| **`FRED_API_KEY`** | Macro pinned to 0.50 market-wide. The VIX-spike trigger that forces a fresh analyst read never fires. | 0.15 |
| **`MASSIVE_API_KEY` / `ALPHAVANTAGE_API_KEY`** | The fundamental factor blends toward 0.50 **in proportion to what is missing**, so a thin read lands near neutral rather than scoring whatever happened to arrive. | 0.20, plus part of catalyst |
| **Alternative data** | **Costs exactly nothing.** It is an additive modifier centred on 0.50, so an absent one moves the composite by 0.00 rather than by a fallback. | 0.00 |

The coverage weighting in row three is worth stating plainly, because the naive
alternative is worse. Cerebras listed in May 2026 with no annual report, so P/E,
free cash flow and debt/equity were all unavailable. The two checks that survived
— analyst consensus and revenue growth — were both bullish, and re-normalising
over just those two would have scored it **0.918: the highest fundamental score
in the watchlist**, above NVDA's 0.864, which is measured on all five *including*
a P/E that counts against it. Coverage weighting pulls the unmeasured share to
0.5 and lands CBRS at ~0.73 instead. A company whose only available data is
optimistic must not outrank one with a complete picture.

---

## Part C — The three scenarios, worked through

### 1. An API key is absent

Nothing breaks. Every fetch has a documented fallback, and the composite is
always computable — from price data alone if necessary. The engine is designed
this way and it is the right design: a verdict built on four factors is more
useful than no verdict.

The cost is that **a degraded score is still a verdict**, and until version 1.16
a composite assembled from three fallbacks was indistinguishable in the API from
one assembled entirely from live data. That is now fixed in two places:

- `GET /analyze` returns an **input completeness** figure — the weighted share of
  the score that came from measured data — and names the factors that are
  neutral placeholders. It is shown above the factor breakdown on the ticker
  page and stored on every trade the agent takes.
- `GET /system/status` reports which sources are configured, which are working,
  and what each one costs.

A completeness figure that cannot be computed stays **absent** rather than
defaulting to 1.0. Signals generated before this existed have no figure, and
giving them a flattering default would be a claim nothing supports.

**Watch for the interaction, not the individual factor.** The Anthropic key is
filed under "degrades quietly" by instinct and belongs in Tier 2, for the
SEMI_AUTO reason above.

### 2. XGBoost fails

`ENABLE_ML_MODEL` is **false in production** and the model file is gitignored, so
it never reaches a deployed box. Every failure path — missing file, load error,
and (since 1.16) an exception during inference — falls back to the weighted
score. The verdict is unaffected.

Until 1.16 the *label* was affected, and that was the real defect.
`scoring_method` was stamped `"xgboost"` from the configuration flag before the
model was consulted, so a document scored by the weighted path claimed a model
produced it. `explain_score` reads that field and refuses to decompose an
XGBoost score — correctly, since the weights did not produce it — which meant the
mislabel **withheld a factor breakdown that was not merely available but exactly
correct**, from the ticker page and from every trade rationale written on that
path. The method now reports whichever path actually ran, and the status page
says so explicitly when the ML path is switched on but not running.
[VERIFIED: `scoring.py`]

### 3. Alpha Vantage or Massive is rate-limited

The arithmetic is in [`11-data-paths.md`](11-data-paths.md#the-alpha-vantage-budget-worked-through)
and is not repeated here: 22 calls against a documented cap of 25, roughly 15
spent at 13 tickers with a warm cache, and 11 tickers' worth on a cold one.

What it means for a *judgement*: past the budget a ticker refreshes from Massive
alone. That keeps free cash flow and debt/equity and loses P/E, revenue growth,
sector and the analyst target price. Fundamental coverage drops and the factor
blends toward neutral; catalyst coverage drops to 0.70 because the analyst-upside
component goes with it; and the earnings-proximity bonus silently becomes zero
because the next report date came from the same call.

**The sharp point, and the honest weakness of the design: the refresh order
becomes a data-quality ranking.** The ticker at the bottom of the list is scored
on less evidence than the one at the top, for a reason that has nothing to do
with the company. Held positions and watchlist names are refreshed first
precisely because of this. Since 1.16 the thinner read is *visible* — the
completeness figure and the ticker page's source panel both show it — but
visibility is a mitigation, not a fix. The fix is a paid tier or moving those
fields to Massive.

---

## Part D — What is measured, and what is asserted

Two things this document deliberately does not claim.

**How reliable a provider is in practice.** There is no uptime monitoring of any
kind, so nobody can say what FRED's availability has been over the last quarter.
The status page reports the last observed state and the app now sends an alert on
a transition; neither is a measurement of long-run reliability, and neither
should be read as one. This is registered as gap #8 in
[`10-due-diligence.md`](10-due-diligence.md).

**Whether a frozen price feed would be noticed.** It would not. Health recording
observes whether a fetch *succeeded*, which is a different question from whether
the bar it returned was fresh. Detecting a stale-but-successful price feed needs
bar-timestamp comparison against a market calendar with holidays and halts, and
that is not built. Registered as gap #12.

Both are stated here rather than left to be discovered, because a document about
what the system knows is worth nothing if it is quiet about what it does not.

---

## Part E — Checking it yourself

**System status** in the app (`/status` on web, Settings → System status on
mobile) reports every capability in the three tiers above, with what each one
costs. Six states, and the distinction between the last two matters:

| State | Meaning |
|---|---|
| **Working** | Answered on the last cycle. |
| **Stale** | A real provider answer, served from a cache past its freshness window. Still data, just not today's. |
| **Degraded** | Answering, but with less than it should. |
| **Failing** | Configured, and erroring. |
| **Off** | No API key. **A configuration choice, not a fault.** The factor it feeds sits at a neutral 0.50. |
| **No reading** | Nothing recorded yet — a fresh deployment. |

Two properties of that page are worth knowing when reading it:

**Nothing is probed.** Every row is what the source actually did on the last
pipeline cycle. This is not a shortcut. A probe would spend the Alpha Vantage
budget it was reporting on, and it would answer the wrong question — "can this
container reach FRED right now" is not "did FRED build the macro factor behind
the BUY on your screen". A probe can be green while the 09:35 score was built on
a fallback after a transient failure.

**Freshness is judged against the market clock.** The pipeline does not run
outside trading hours, so a quiet overnight is the design and not an outage.

The per-report answer is separate and lives on the ticker page: the source panel
under *Where the inputs come from* describes **that report**, not the system now.
A source that failed at 09:35 and recovered at 10:00 still reads as absent on the
09:35 report, because that is what the score in front of you was built from.
