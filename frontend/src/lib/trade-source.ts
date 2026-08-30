/**
 * How an order came to exist.
 *
 * This mirrors the bucketing in `backend/app/routes/performance.py` exactly —
 * `signal_type` in {BUY, SELL, EXIT_ALERT} is the agent acting unattended,
 * `PROPOSAL_APPROVED` is the agent proposing and a human accepting, anything
 * else is a human's own idea.
 *
 * It is duplicated here rather than sent down per-trade because `/trading/orders`
 * returns the raw record, and a UI that guessed differently from
 * `/performance/trades` would show a position as agent-placed on one screen and
 * manual on another. If the server-side rule changes, this must change with it.
 *
 * The three are never pooled: signal_driven is the only clean read of the
 * engine, approved measures the human-plus-agent pair, and manual says nothing
 * about the engine at all.
 *
 * Note the deliberate split between the bucket **key** and its **label**: the
 * key stays `approved` because that is the backend's name for the bucket and
 * the two must be greppable as one thing, while the label reads "Semi" because
 * that is the question a trader is actually asking — did the tool decide alone,
 * did it suggest and I agree, or was this mine.
 */

export type TradeSource = 'agent' | 'approved' | 'manual'

const AGENT_SIGNAL_TYPES = new Set(['BUY', 'SELL', 'EXIT_ALERT'])

export function tradeSource(signalType?: string | null): TradeSource {
  if (signalType && AGENT_SIGNAL_TYPES.has(signalType)) return 'agent'
  if (signalType === 'PROPOSAL_APPROVED') return 'approved'
  return 'manual'
}

/**
 * Statuses that mean the agent asked and the trader answered — or has yet to.
 *
 * A PROPOSED or DECLINED record carries `signal_type: "BUY"`, because the
 * agent's own signal is what raised it, so `tradeSource` reads it as `agent`.
 * That is correct for the backend's purpose — it buckets *executed* trades, and
 * these were never executed — and wrong on screen, where "Agent" claims the
 * tool acted without the trader and a proposal is the exact opposite.
 *
 * So this lives beside `tradeSource` rather than inside it. `tradeSource` must
 * keep mirroring the server; `displaySource` is what a row of the activity
 * table reads.
 */
const SEMI_STATUSES = new Set(['PROPOSED', 'DECLINED'])

export function displaySource(
  order: { signal_type?: string | null; status?: string | null },
): TradeSource {
  if (order.status && SEMI_STATUSES.has(order.status)) return 'approved'
  return tradeSource(order.signal_type)
}

export const SOURCE_LABEL: Record<TradeSource, string> = {
  agent: 'Agent',
  approved: 'Semi',
  manual: 'Manual',
}

/** Longer form, for where there is room to say what the label means. */
export const SOURCE_DESCRIPTION: Record<TradeSource, string> = {
  agent: 'The tool decided and acted without you',
  approved: 'The tool recommended it, you actioned it',
  manual: 'You decided, without a tool recommendation',
}
