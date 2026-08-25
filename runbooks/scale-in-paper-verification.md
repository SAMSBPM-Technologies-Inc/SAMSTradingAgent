# Runbook — verifying scale-in against the paper account

Scaling into a position touches the code that protects live money: it changes
what a `BUY` on a held ticker does, and it moves the protective stop and target
from an order-attached bracket to a standalone OCA pair. The unit tests pin the
arithmetic and the decision logic. They cannot tell you that **IB accepts these
orders**, which is the part that matters.

Run this before scale-in reaches an account with real money in it.

**Prerequisite:** `TRADING_MODE=paper`, a connected gateway (`/trading/broker/status`
reports `connected: true`), and a market session — resting limit orders will not
fill outside RTH, and half of what follows is about fills.

Throughout, `sta.samsbpm.com/orders` shows the position record and the API
container shows the decisions. The compose service is **`api`** (container
`trading_agent_api`) — there is no `backend` service — and compose needs the
env file or every variable resolves blank:

```bash
cd /opt/trading-agent/backend
docker logs -f trading_agent_api 2>&1 | grep -E \
  "scale_in|reprotect|position_found_unprotected|position_left_unprotected|ibkr_protective"

# equivalently, via compose:
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api
```

Keep TWS or IB's web portal open on the paper account: **the venue is the source
of truth for what is protecting the position**, not our UI.

---

## 1. Establish a position to add to

Buy a liquid, cheap US name from `/ticker/<SYM>` — 5–10 shares is enough.

Confirm before continuing:

- The record shows `FILLED` with an entry price.
- **In TWS: one stop and one target, each for exactly the quantity held.**

If the entry rests unfilled, scale-in will refuse it (`PENDING` is not
addable) — that refusal is correct, but it is not what you are testing.

---

## 2. The add itself

Press Buy again on the same ticker.

Expected, in order:

| Where | What |
|---|---|
| Log | `scale_in_submitted` with `add_qty`, `held_qty`, `total_qty`, `blended_entry` |
| TWS | the original stop and target **still working, unchanged** |
| TWS | a new plain BUY limit, no bracket attached |
| Record | `pending_add` populated; `qty` still the *original* quantity |

The point of this step is the second row. The original protection must survive
the add — if the old legs disappear here, stop and investigate, because the
holding is naked for as long as the new order rests.

`qty` staying at the original number is also deliberate: the position is not
550 shares until 550 shares are actually owned.

---

## 3. Consolidation

Wait for the add to fill, then for the reconciler (runs every 2 minutes).

| Where | What |
|---|---|
| Log | `scale_in_settled` with `held_qty` matching the venue |
| TWS | the old pair **cancelled**, replaced by one stop + one target |
| TWS | **both legs sized to the full combined holding** |
| Record | `qty` and `filled_qty` updated, `entry_price` now the blended cost, `pending_add: null`, `scale_ins: 1` |

Check the arithmetic on `entry_price` by hand once — it should be the
share-weighted average of the two fills, not the average of the two prices.

**The critical assertion is the leg quantity.** Legs covering more than is held
would sell shares that do not exist; that is the failure this design is shaped
around, and the only way to confirm it is to read the numbers in TWS.

---

## 4. The partial fill (the case worth engineering for)

Place an add with a limit price far enough below the market that only part of
it fills — or add a large quantity in a thin name.

After the next reconciliation, the protective legs must cover **what filled**,
not what was ordered. If you ordered 100, 30 filled, and the legs read 550
against 480 held, stop: a stop-out would short 70 shares.

---

## 5. Exiting a scaled position

Press Close.

- The sell quantity must be the **whole** holding, not the original entry.
- No working orders remain for the ticker afterwards.
- `pnl` is computed against the blended entry.

The specific bug to watch for is a close that sells only the original shares
and marks the record closed, orphaning the added ones.

---

## 6. The healer

With a position open, cancel its stop and target by hand in TWS.

Within two minutes:

```
position_found_unprotected  ticker=… qty=…
ibkr_protective_orders_placed  ticker=… qty=…
```

and the pair is back. This is what closes the window in step 2/3 — verify it
works, because every other guarantee here leans on it.

---

## What failure looks like

| Log line | Meaning | Action |
|---|---|---|
| `scale_in_rejected` | IB refused the add; **nothing was cancelled**, position keeps its bracket | Read the rejection; no cleanup needed |
| `reprotect_aborted_orders_still_working` | Cancel did not take — most likely a read-only API session | Restart the gateway container |
| `position_left_unprotected` | Legs cancelled, replacements refused. **A live holding has no automatic exit** | Place a stop by hand now; retried in 2 min |
| `scale_in_abandoned_position_closed` | Position exited while the add rested; the add was cancelled | Expected — no action |

`unprotected_since` on the trade record is the durable form of the third row.
A position carrying it for more than a few minutes needs a human.

---

## Rolling back

`ENABLE_SCALE_IN=false` restores the previous behaviour: a `BUY` on a held
ticker is skipped. It does not affect positions already scaled — those are
ordinary positions with an OCA pair instead of a bracket, and exit normally.
