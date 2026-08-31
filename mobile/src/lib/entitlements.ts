/**
 * What the signed-in account may do — read from the server, never derived here.
 *
 * `GET /auth/me` returns the whole resolved object, so no client maps a tier
 * name to a feature or keeps its own copy of a cap. That is the same rule
 * `/analyze` already follows by returning `breakdown` and `gate` from the
 * engine instead of letting the UI restate the weights, and it means a new
 * tier — or a retuned cap — needs no change on either client.
 *
 * **Hiding a control is presentation; the server check is the gate.** Every
 * control hidden by these booleans has a matching refusal in the backend, and
 * the tests assert only the server side. Behind `/trading` is one shared
 * brokerage account belonging to the operator, so a control that is merely
 * hidden is not protected at all.
 *
 * This file is kept **byte-identical** with `mobile/src/lib/entitlements.ts`,
 * exactly as `trade-source.ts` is: the two clients must not disagree about who
 * may do what.
 */

export type AccessTier = 'BASIC' | 'PRO' | 'TRADER'

export interface Entitlements {
  tier: AccessTier
  /** The whole /trading surface, including reads of the shared account. */
  may_trade: boolean
  /** Deep research and full analysis runs — anything that calls a model. */
  may_spend_tokens: boolean
  /** Configuring provider keys and role chains. */
  may_bring_own_key: boolean
  /** Falling back to the deployment's own key rather than paying for it. */
  may_use_server_key: boolean
  /** Enrolling in the unattended nightly research job. */
  may_enrol_in_nightly_research: boolean
  /** Tickers this plan covers. `null` is unlimited; zero is a real cap. */
  watchlist_cap: number | null
}

/**
 * Fail closed. A missing object means an anonymous visitor, a client built
 * against an older server, or a request that has not landed yet — and in all
 * three the safe reading is to hide rather than to show something the server
 * will refuse anyway.
 */
const NOTHING: Entitlements = {
  tier: 'BASIC',
  may_trade: false,
  may_spend_tokens: false,
  may_bring_own_key: false,
  may_use_server_key: false,
  may_enrol_in_nightly_research: false,
  watchlist_cap: 0,
}

export function entitlementsOf(
  user: { entitlements?: Entitlements | null } | null | undefined,
): Entitlements {
  return user?.entitlements ?? NOTHING
}

export interface TierRefusal {
  capability: string
  message: string
  /** Present on a watchlist-cap refusal. */
  cap?: number
  watching?: number
}

/**
 * Read a plan refusal out of an Axios error.
 *
 * Tolerates both shapes on purpose: the tier gates raise a structured
 * `detail`, while every route that predates them raises a plain string. A
 * helper that understood only the new one would silently drop the message on
 * half the API.
 */
export function tierRefusal(err: unknown): TierRefusal | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (!detail) return null
  if (typeof detail === 'string') return { capability: '', message: detail }
  if (typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (typeof d.message === 'string') {
      return {
        capability: typeof d.capability === 'string' ? d.capability : '',
        message: d.message,
        cap: typeof d.cap === 'number' ? d.cap : undefined,
        watching: typeof d.watching === 'number' ? d.watching : undefined,
      }
    }
  }
  return null
}

/** How each plan is named on screen. Never the raw enum value. */
export const TIER_LABELS: Record<AccessTier, string> = {
  BASIC: 'Basic',
  PRO: 'Pro',
  TRADER: 'Trader',
}
