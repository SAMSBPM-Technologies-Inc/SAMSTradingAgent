# Buying the Dip and Selling the Rip — what the code actually does

**Objective:** test how faithfully the engine's mathematics match its motto.

**Revision note.** The first version of this document concluded that the engine
"falls asleep" during a rip — that a ripping stock's composite settles at
0.50–0.60, comfortably above the 0.30 SELL threshold, so the agent watches a
winner run and does nothing. Three of its claims did not survive being checked
against the code, and the conclusion inverted. The corrected findings are below;
the original claims are kept at the end, because a review that quietly rewrites
itself is not one anybody should trust twice.

---

## 1. Buying the dip — this half holds up

`_technical_score` gates its oscillators on trend rather than averaging against
it:

```python
osc = sum(s * w for s, w, _ in oscillators) / sum(w for _, w, _ in oscillators)
return clamp(osc * (_TREND_FLOOR + (1.0 - _TREND_FLOOR) * trend))
```

That restores the conditional the strategy always implied — *oversold is a
reason to buy only when the trend is intact* — and separates a pullback (0.697)
from a falling knife (0.388) about seven times more widely than the additive
blend it replaced. `setup_scan.classify_trigger` imports the same
`trend_confirmation`, so the ENTRY badge and the score cannot drift apart.

**On scale-in, the original review was wrong.** It read `scale_in_dip_pct` as a
strategy gate that "financially gags" the agent out of a shallow, profitable
dip. It is a **rate limit**. A standing BUY re-runs `_prepare_entry` on every
five-minute cycle — deliberately, so a skip for "gateway down" retries — which
makes every add condition a rate limit by construction. That is why
`MAX_SCALE_INS` and `MIN_ADD_FRACTION` sit beside it, and why the fee floors
apply to adds and not to opening entries: an entry has no alternative, an add's
alternative is doing nothing.

---

## 2. Selling the rip — the engine sold them, for the wrong reason

### The composite had the two cases backwards

Under `mean_reversion`, an extended name floors the oscillators *by design*:
RSI ≥ 70 scores 0.0, a Bollinger reading near the top band scores `1 - bb_pct`.
An oversold reading is the entry timer. But `weight_technical` is 0.30, and the
low end of the composite publishes SELL.

AAPL: `bb_pct` 1.03, `stoch_rsi` 0.99, up 24% in six months, at 0.87 of its
52-week range — technical score **0.066**, and a published **SELL**.

Measured on the real functions, with everything else held plausible:

| | composite | exit reading |
|---|---|---|
| extended leader (trend intact, strong RS) | **0.297** → SELL | 0.558 → HOLD |
| broken trend, negative RS, weak fundamentals | **0.340** → HOLD | 0.247 → SELL |

The ordering itself was inverted. The composite sold the leader and held the
name that was falling apart, and no threshold could have fixed that — it is the
wrong number, not the wrong cutoff.

This mattered more than an ordinary mis-score because **SELL is the one verdict
with no brakes**: it skips the risk gate in `classify_signal`, skips
confirmations and dwell in `signal_stability`, is unreachable by the research
veto, and is unappealable by the analyst (`sell_restored`).

**Fixed in 1.31.0.** `scoring.exit_score` recomputes the composite with the
oscillator component swapped for a condition component — `trend_confirmation`
and `momentum_score`, both already on the feature document. Momentum decides
exits; technical decides entries. It adds no veto and no delay: a deteriorating
name still sells immediately.

### The trailing stop could not fire — the defect the first review missed

The original review was right that profit-taking fell to a static broker
bracket, and right that `trailing_stop_enabled` shipped `False`. It did not
check what happened if you switched it on. Simulated across a position walking
from entry to its target, on the shipped defaults:

```
peak +4.00%   breakeven → stop 100.00
peak +9.89%   trail     → stop 101.10   ← take-profit fills at +10%
```

The trail fired **once**, locked in **1.1%**, inside the last 0.11% of price
travel before the limit leg closed the trade. Nothing ever raised the target, so
the peak could not exceed +10%, so the trail had no room. `config.py` advertised
"an 8% trail on a name up 20% still locks in ~10%" — a position that could not
exist. This is the `EXIT_ALERT` ghost again: a dead path reading as a live one,
in the code that sells things.

**Fixed in 1.31.0.** `_ratcheted_target` raises the target with the peak, both
legs move as one OCA pair through the existing `_reprotect`, and they share one
switch — a trail under a fixed target is inert, so neither may be enabled alone.

### The analyst could always sell a rip

The original review's claim that the agent "does not autonomously sell the rip"
was already false. `ENABLE_AI_ANALYST=true` in production,
`analyst_position_context` defaults on, `_analyst_worth_calling` calls the
analyst on *every* open position at any score, and the system prompt says: *"A
good company at a stretched price is a reason to take a profit, not a reason to
keep holding."* A model SELL over a rule HOLD publishes as SELL — neither
`_gate_analyst_signal` branch fires.

### EXIT_ALERT is still advisory, and now measurable

`setup_scan` flags overbought (RSI ≥ 70 or bb_pct ≥ 0.90) and nothing sells on
it. That is unchanged and deliberate. What 1.31.0 adds is the evidence to argue
about it: `first_exit_alert_price` on the position record and
`avg_return_at_first_exit_alert_pct` on `/performance/trades`, against
`avg_return_pct` in the same bucket. Wiring it to an order has to be argued from
that number, and until this release no stored row could produce one.

---

## 3. Where the original review was wrong

| Claim | Finding |
|---|---|
| "The engine fights itself — momentum pushes the score up while mean-reversion pushes it down, cancelling into HOLD." | `weight_momentum` is **0.00**. Momentum contributes nothing to the composite. Nothing cancels; the score simply had no way to say "this is working". |
| "A ripping stock scores 0.50–0.60, so the engine issues HOLD and goes to sleep." | An extended leader scored **0.297** and published **SELL**. The engine did not sleep through rips; it sold them, through the one path with no brakes. |
| "The agent does not autonomously sell the rip." | The analyst path could, and does. See above. |
| "Scale-in financially gags the agent out of a shallow dip." | `scale_in_dip_pct` is a rate limit on a guard that re-runs every five minutes, not a strategy gate. |

What it got right: profit-taking rested on a static bracket set at entry, the
trailing stop shipped off, and `EXIT_ALERT` sells nothing.

---

## Summary

The engine was a competent dip buyer whose exit logic asked the entry question.
It is now measured on two readings: the composite ranks *entry* opportunity, and
`exit_score` judges whether a position is still worth holding. The bracket that
takes the profit moves with the position instead of being frozen at the moment
of entry.

Both changes ship **on**, which departs from the measurement-first posture used
for `RESEARCH_VETO_ENABLED` and `weight_momentum` — see the Known gaps in
`CHANGELOG.md` 1.31.0, which states plainly what has and has not been measured.
