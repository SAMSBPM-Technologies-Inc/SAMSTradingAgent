/**
 * How an order came to exist.
 *
 * Mirrors `backend/app/routes/performance.py` exactly — `signal_type` in
 * {BUY, SELL, EXIT_ALERT} is the agent acting unattended, `PROPOSAL_APPROVED`
 * is the agent proposing and a human accepting, anything else is a human's own
 * idea. Kept identical to `frontend/src/lib/trade-source.ts`.
 *
 * The copy this replaces treated any non-MANUAL, non-PROPOSAL_APPROVED
 * signal_type as agent-placed, so an unusual value read "Agent" on this screen
 * while the backend counted it in the `manual` bucket on Performance. Same
 * record, two answers, on the same phone.
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
  manual: 'You',
}
