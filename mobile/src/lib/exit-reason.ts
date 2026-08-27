/**
 * Why a position closed.
 *
 * Kept identical to `frontend/src/lib/exit-reason.ts` — same rule as
 * `trade-source.ts`. A phone and a browser disagreeing about why a position
 * closed is worse than either of them being terse about it.
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
  // Reconciliation found the position flat with no exit of ours behind it.
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
  return trigger === 'SELL_SIGNAL' || trigger === 'EXIT_ALERT' || trigger === 'MANUAL_CLOSE'
}

/** Short form for a dense feed: a few words rather than a full sentence. */
const TRIGGER_SHORT: Record<string, string> = {
  SELL_SIGNAL: 'sell signal',
  EXIT_ALERT: 'exit alert',
  MANUAL_CLOSE: 'you closed it',
}

export function exitTriggerShort(trigger?: string | null): string | null {
  return trigger ? TRIGGER_SHORT[trigger] ?? null : null
}
