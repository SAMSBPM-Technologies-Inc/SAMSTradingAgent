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
 */

export type TradeSource = 'agent' | 'approved' | 'manual'

const AGENT_SIGNAL_TYPES = new Set(['BUY', 'SELL', 'EXIT_ALERT'])

export function tradeSource(signalType?: string | null): TradeSource {
  if (signalType && AGENT_SIGNAL_TYPES.has(signalType)) return 'agent'
  if (signalType === 'PROPOSAL_APPROVED') return 'approved'
  return 'manual'
}

export const SOURCE_LABEL: Record<TradeSource, string> = {
  agent: 'Agent',
  approved: 'Approved',
  manual: 'Manual',
}

/** Longer form, for where there is room to say what the label means. */
export const SOURCE_DESCRIPTION: Record<TradeSource, string> = {
  agent: 'Agent entry, placed unattended',
  approved: 'Agent proposed, you approved',
  manual: 'You placed this yourself',
}
