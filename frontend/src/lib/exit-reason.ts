/**
 * Why a position closed.
 *
 * Two kinds of value arrive in `exit_reason`, and the difference matters:
 *
 *   - A sentence written by `execute_exit`, which is the only code that knows
 *     whether the score fell, the setup scan flagged an exit, or a person
 *     pressed Close. It arrives with an `exit_trigger` code beside it.
 *   - A machine code written by reconciliation, which can see that a position
 *     went flat but never why. `bracket_or_manual` is its honest guess and
 *     genuinely does mean a stop, a target, or an order placed at the broker —
 *     but only because nothing we submitted is behind it.
 *
 * Sentences pass through untouched. Codes are translated here, and none of them
 * is translated into a claim about a cause we do not have.
 */

const CODE_LABEL: Record<string, string> = {
  // Reconciliation found the position flat and could not attribute it to either
  // bracket leg — the fill sat between the stop and the target, or the trade
  // carried no levels. Still the honest answer; it is just no longer the ONLY
  // answer, which is what it used to be for every bracket exit ever recorded.
  bracket_or_manual: 'Stop or target fired, or closed at the broker',
  // Closed, but the execution that would price it is gone.
  closed_unpriced: 'Closed — exit price unavailable',
  // No position, no working order, and no execution in the log.
  no_broker_record: 'No broker record — outcome unknown',
  // Settled from before `execute_exit` recorded reasons. Not a cause.
  closed_reason_unrecorded: 'Reason not recorded',
}

/** Human-readable exit reason, or null when the record carries none. */
export function exitReasonLabel(reason?: string | null): string | null {
  if (!reason) return null
  return CODE_LABEL[reason] ?? reason
}

/**
 * Whether this exit is one the agent or the user chose, as opposed to one the
 * venue's own working orders produced. Drives emphasis, never wording.
 */
export function isDecidedExit(trigger?: string | null): boolean {
  // TAKE_PROFIT and STOP_LOSS are deliberately absent: they are the venue's own
  // working orders resolving, not a choice anyone made at the time. EXIT_ALERT
  // is absent because it never existed — `execute_exit` defaulted to it and no
  // caller ever passed it, so no record carries it.
  return trigger === 'SELL_SIGNAL' || trigger === 'MANUAL_CLOSE'
}

/** Short form for a dense feed: a few words rather than a full sentence. */
const TRIGGER_SHORT: Record<string, string> = {
  SELL_SIGNAL: 'sell signal',
  MANUAL_CLOSE: 'you closed it',
  // Named by reconciliation from the levels the trade carried against the price
  // it filled at. Before that both of these were `bracket_or_manual` and the
  // most basic question about an exit — target or stop — had no answer.
  TAKE_PROFIT: 'target reached',
  STOP_LOSS: 'stopped out',
}

export function exitTriggerShort(trigger?: string | null): string | null {
  return trigger ? TRIGGER_SHORT[trigger] ?? null : null
}
