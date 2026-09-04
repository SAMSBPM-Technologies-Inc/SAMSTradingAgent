import type { AccessTier, Entitlements } from '../lib/entitlements'
export type Signal = 'BUY' | 'SELL' | 'HOLD'

/**
 * Timing setup for a watched ticker — the dip-buy classification that used to
 * live on its own /radar page. PENDING means the pipeline has not produced
 * indicator data for the ticker yet.
 */
export type Trigger = 'ENTRY' | 'EXIT_ALERT' | 'NEUTRAL' | 'PENDING'

export interface AlternativeData {
  short_interest?: {
    short_ratio?: number | null
    short_percent_of_float?: number | null
    squeeze_risk?: 'HIGH' | 'MEDIUM' | 'LOW' | null
    source?: string
  }
  options_flow?: {
    put_call_ratio?: number | null
    sentiment?: string | null
    put_volume?: number | null
    call_volume?: number | null
    expiry?: string | null
    source?: string
  }
  insider_trades?: {
    buy_count_90d?: number
    sell_count_90d?: number
    net_sentiment?: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    recent?: Array<{
      date?: string
      insider?: string | null
      transaction?: string | null
      shares?: number | null
      value?: number | null
    }>
    source?: string
  }
  fetched_at?: string
}
export type Conviction = 'HIGH' | 'MEDIUM' | 'LOW'

export interface ScoringWeights {
  technical: number
  fundamental: number
  sentiment: number
  macro: number
  volatility: number
  catalyst: number
  alternative_data: number
}

export interface User {
  id: string
  email: string
  display_name: string
  scoring_weights?: ScoringWeights | null
  /** The plan this account is on. Label it with `TIER_LABELS`, never raw. */
  access_tier?: AccessTier
  is_admin?: boolean
  /** Resolved by the server. Read it; never derive it from `access_tier`. */
  entitlements?: Entitlements | null
}

export interface WatchlistItem {
  ticker: string
  /** 'PENDING' while the ticker is watched but not yet scored. */
  signal: Signal | 'PENDING'
  score: number
  confidence: number
  conviction?: Conviction
  current_price?: number
  day_change_pct?: number
  price_target?: number
  thesis?: string
  generated_at: string

  // ── Timing setup (formerly the Alpha Radar dip-buy scan) ──────────────────
  trigger: Trigger
  rsi_14?: number
  stoch_rsi?: number
  bb_pct?: number
  ma_20?: number
  volume_anomaly?: number
  pct_from_ma20?: number
  computed_at?: string
}

export interface WatchlistSetupCounts {
  entry: number
  exit_alert: number
  neutral: number
  pending: number
}

export interface WatchlistResponse {
  count: number
  items: WatchlistItem[]
  setups: WatchlistSetupCounts
}

/** Risk assessment — gates every BUY, and went unrendered until Tier 1. */
export interface RiskAssessment {
  risk_score: number
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH'
  explanation: string
}

/** One sub-score and the share of the composite it supplied. */
export interface FactorContribution {
  key: string
  label: string
  /** Sub-score, 0–1. */
  score: number
  weight: number
  /** Points of the composite. Signed for the alternative-data modifier. */
  contribution: number
}

export interface ScoreBreakdown {
  method: string
  /** False on the XGBoost path, where a weighted decomposition would be fiction. */
  attributable: boolean
  personalized: boolean
  factors: FactorContribution[]
  alternative_data?: FactorContribution | null
  base_total: number
  composite: number
}

/** What the AI analyst asked for, and what the gate made of it. */
export interface AnalystGate {
  /** False on a signal stored before the gate existed — not the same as "it agreed". */
  checked: boolean
  wanted?: Signal | null
  override?: 'buy_refused' | 'sell_restored' | null
  reason?: string | null
}

/**
 * The thresholds behind the verdict, read from the engine rather than restated.
 *
 * `score_passes_buy` is measured against `effective_buy_threshold`, not the raw
 * `buy_threshold`: a standing BUY is held by the hysteresis band down to the
 * lower level, and testing it against the entry threshold is what printed a
 * failing gate underneath a published BUY.
 */
export interface SignalGate {
  buy_threshold: number
  sell_threshold: number
  risk_max_for_buy: number
  score_passes_buy: boolean
  risk_passes_buy: boolean
  hysteresis: number
  effective_buy_threshold: number
  /**
   * The number the SELL test was measured against. The BUY side reads the
   * composite; the exit side reads a version of it with the mean-reversion
   * oscillator component swapped for trend and relative strength, because an
   * extended winner floors the oscillators by design and that says nothing
   * about whether to sell. `null` on a pre-1.31.0 document or an XGBoost score,
   * where the SELL test read the composite itself.
   */
  exit_score?: number | null
  /** Whether the exit reading is below the level that sells. */
  score_passes_sell?: boolean | null
  /** Which component produced the verdict. An overridden analyst read is `rule`. */
  decided_by: 'rule' | 'analyst'
  analyst?: AnalystGate | null
  /**
   * The reader's own `min_signal_score` — a second score bar applied where the
   * order is placed, not where the verdict is classified. Clearing everything
   * above is not sufficient to trade. `null` when the account has no
   * auto-trade settings, which is not the same as a bar of zero.
   */
  order_threshold?: number | null
  /** Whether the score clears it. `null` when there is no bar to clear. */
  score_passes_order?: boolean | null
}

/** One factor's share of measured input. */
export interface FactorInput {
  key: string
  label: string
  /** `measured` all of it · `partial` some · `fallback` none, so it is the flat 0.5. */
  state: 'measured' | 'partial' | 'fallback'
  coverage: number
}

/**
 * How much of a score was measured.
 *
 * Every source here degrades to a neutral 0.5 rather than failing the cycle, so
 * a composite built on three fallbacks used to look identical to one built on
 * live data. This is that distinction — and it is what makes the six-factor
 * breakdown beside it readable, since a 0.50 sub-score can mean "measured, and
 * genuinely neutral" or "we never found out".
 */
export interface SignalInputs {
  factors: FactorInput[]
  /** Weighted by *your* weights. Null for signals from before this existed. */
  completeness: number | null
  /** Weighted factors carrying no measured data, heaviest first. */
  fallback_factors: string[]
}

export interface AnalyzeResponse {
  ticker: string
  score: number
  signal: Signal
  confidence: number
  conviction?: Conviction
  price_target?: number
  stop_loss?: number
  time_horizon?: string
  thesis?: string
  analyst_note?: string
  entry_suggestion?: string
  exit_suggestion?: string
  explanation: string
  generated_at: string
  risk?: RiskAssessment
  breakdown?: ScoreBreakdown | null
  gate?: SignalGate | null
  bull_case?: string
  bear_case?: string
  /**
   * The scannable form of the two cases, written by the analyst. Empty on any
   * analysis stored before 1.20.0 — render the paragraph in that case. Never
   * split the prose into bullets on the client: which clause carried the
   * argument is not something this layer knows.
   */
  bull_points?: string[]
  bear_points?: string[]
  catalysts?: string[]
  key_risks?: string[]
  alternative_data?: AlternativeData
  current_price?: number
  day_change_pct?: number
  /** Whether the AI analyst actually ran for this document, or the rule-based path did. */
  analyst_used?: boolean
  /** The model this server is configured to call. Null when the analyst is disabled. */
  analyst_model?: string | null
  /** Which provider actually supplied each input to this score. */
  data_sources?: Record<string, string | number | boolean> | null
  /** How much of this score was measured, and how much is a placeholder. */
  inputs?: SignalInputs | null
}

/**
 * One attributable fact from the research ledger.
 *
 * The `id` is what the report's prose cites. Any claim in a dossier that did
 * not reference one of these was removed server-side before storage, so
 * anything rendered here is supportable by construction.
 */
export interface EvidenceItem {
  id: string
  claim: string
  value: string
  source: string
  as_of?: string | null
  url?: string | null
}

/**
 * One of the six report dimensions, 0-100.
 *
 * Higher is better on all six — `risk` included, where higher means safer.
 * `model_judged` marks the one score that is a model's judgement rather than
 * arithmetic; `thin` marks a dimension built from too few inputs to lean on.
 */
export interface DimensionScore {
  key: string
  label: string
  score?: number | null
  coverage: number
  thin: boolean
  model_judged: boolean
  components: { name: string; score: number; weight: number }[]
  note?: string | null
}

export interface ResearchReport {
  assessment?: 'BULLISH' | 'NEUTRAL' | 'BEARISH' | null
  /** Conviction is deliberately absent here — the server stops sending the
   *  same 0-100 number at two depths of one response. Read
   *  `ResearchDossier.research_conviction`. */
  thesis?: string | null
  bull_case?: string | null
  bear_case?: string | null
  what_the_market_is_missing?: string | null
  key_catalysts: string[]
  key_risks: string[]
  /** Risks the risk agent raised that the synthesiser answered rather than carried. */
  risks_addressed: string[]
  what_would_change_my_opinion: string[]
  conclusion?: string | null
  conviction_rationale?: string | null
}

export interface CitationAudit {
  /** Per-field count of items removed for citing nothing. */
  dropped: Record<string, number>
  /** Citation ids the model referenced that the evidence ledger never issued
   *  — the case worth the most suspicion, since a fabricated id looks exactly
   *  like a real one to a reader skimming the prose. */
  invented: string[]
}

export interface ResearchVetoStatus {
  /** RESEARCH_VETO_ENABLED. False means nothing here can stop an order. */
  enabled: boolean
  /** The dossier exists and is fresh enough to be capable of vetoing. */
  considered: boolean
  /** The dossier meets a blocking trigger, whether or not the veto is on.
   *  Separate from `blocking` because the flag is off by default: "research
   *  would refuse this entry if you switched the veto on" is the sentence a
   *  user needs in order to decide whether to switch it on. */
  would_block: boolean
  /** `enabled && would_block` — the only field the backend guard acts on. */
  blocking: boolean
  reason?: string | null
  /** 'bearish' | 'low_conviction' | null */
  trigger?: string | null
  assessment?: string | null
  research_conviction?: number | null
  /** The floor conviction must clear, so the distance to the edge can be shown
   *  rather than a bare number with no scale. */
  min_conviction: number
  age_hours?: number | null
  max_age_hours: number
  /** 'no_dossier' | 'undated' | 'stale' — each allows the trade, and each for
   *  a different reason worth telling apart. */
  not_considered_reason?: string | null
}

/** How this reading turned out, once enough time passed to know. Absent on a
 *  dossier too recent to grade — the normal state for the one a ticker page
 *  shows, since it was written today. */
export interface ResearchOutcome {
  settled_at?: string | null
  horizon_days?: number | null
  price_at_dossier?: number | null
  price_at_settlement?: number | null
  return?: number | null
  benchmark_ticker?: string | null
  benchmark_return?: number | null
  alpha?: number | null
  assessment?: string | null
  research_conviction?: number | null
  /** Judged on ALPHA, not raw return: BULLISH on a name that rose 4% while the
   *  market rose 9% was not right. `null` for a NEUTRAL reading and for a
   *  window whose benchmark could not be read — both mean "cannot say", and
   *  neither may be rendered as a miss. */
  assessment_correct?: boolean | null
  reflection?: ResearchReflection | null
}

export interface ResearchReflection {
  /** `null` when nothing the model wrote cited a real evidence id. The numbers
   *  beside it still stand — the prose is the optional part, and an
   *  unattributable lesson must never be carried into a future prompt. */
  lesson?: string | null
  what_held: string[]
  what_failed: string[]
  /** True when the whole lesson was dropped for citing nothing. "We reflected
   *  and it was unusable" and "we never reflected" are different facts. */
  uncited: boolean
  fabricated_citations: string[]
}

/** How many settled prior readings were in this dossier's evidence when it was
 *  built. Zero for any name being read for the first time. */
export interface PriorRecordCoverage {
  same_ticker: number
  cross_ticker: number
  available: boolean
}

export interface RebuttalSide {
  answered: string[]
  /** Risk analyst only. */
  surviving: string[]
  sharpened: string[]
  /** Defence only — the valuable half. An answer that disposes of every risk
   *  is the strongest signal the step was not done honestly. */
  conceded: string[]
  overstated: string[]
  residual_severity?: number | null
  residual_rationale?: string | null
  strongest_surviving_risk?: string | null
}

/** One exchange, after both sides had already written independently. Either
 *  side may be null — its call failed — which is not the same as a side that
 *  argued and found nothing. */
export interface ResearchDebate {
  rounds: number
  risk_rebuttal?: RebuttalSide | null
  defence_rebuttal?: RebuttalSide | null
}

/** One temperament's reading of the position, not of the company.
 *
 *  **Advisory only.** No order quantity follows from these: sizing is
 *  arithmetic on a frozen equity basis and no part of the trading guard chain
 *  reads them. They also do not see account exposure — a dossier is shared, so
 *  a per-user panel would multiply its cost by the user count. */
export interface TradeStance {
  stance?: 'SIZE_UP' | 'HOLD_SIZE' | 'SIZE_DOWN' | 'WAIT' | null
  /** `null` when the reasoning cited nothing and was stripped. The stance is a
   *  closed enum and survives; the visible gap is intended. */
  rationale?: string | null
  what_would_change_it?: string | null
}

export interface ResearchStances {
  aggressive?: TradeStance | null
  conservative?: TradeStance | null
  neutral?: TradeStance | null
}

// ── Model configuration ───────────────────────────────────────────────────────
// A trader brings their own keys and assigns a model per role. Order within a
// role is the priority: a rate-limited or dead key falls through to the next.

export type LLMRole = 'orchestrator' | 'specialist' | 'analyst'

/** A stored credential, as the client is allowed to see it.
 *
 *  There is no key field here and there must never be one — the server's
 *  response type has no room for one either. To check a key works, call the
 *  test endpoint, which returns a verdict rather than a secret. */
export interface LLMKeyStatus {
  id: string
  provider: string
  label: string
  /** e.g. `sk-ant-…4f2a` — enough to tell two of your own keys apart. */
  fingerprint: string
  added_at?: string | null
  last_ok_at?: string | null
  last_error?: string | null
  last_error_at?: string | null
}

export interface LLMRoleEntry {
  key_id: string
  model: string
}

export interface LLMRoleChains {
  orchestrator: LLMRoleEntry[]
  specialist: LLMRoleEntry[]
  analyst: LLMRoleEntry[]
}

export interface LLMSettings {
  keys: LLMKeyStatus[]
  roles: LLMRoleChains
  /** Gates the daily research job for this user. Off until asked: research is
   *  five to seven model calls per ticker per day, on your own key. */
  research_enabled: boolean
  /** What the server falls back to when your chain is empty or exhausted. A
   *  trader who configures nothing still gets dossiers, and should be able to
   *  see what produced them. */
  server_fallback?: string | null
}

export interface LLMKeyTestResult {
  ok: boolean
  provider: string
  model?: string | null
  error?: string | null
  /** `auth` reads very differently from `rate_limit` when you are deciding
   *  whether to re-paste a key. */
  error_kind?: string | null
}

/** One producer behind a dossier, and the agents it wrote. */
export interface ModelUsed {
  provider?: string | null
  model?: string | null
  agents: string[]
}


export interface ResearchDossier {
  ticker: string
  as_of: string
  stale: boolean
  age_hours?: number | null
  /** 0-100, the research module's own conviction. Distinct from the analyst's
   *  HIGH/MEDIUM/LOW `conviction` on a signal or a trade: different scale,
   *  different producer, different gate — this one feeds the entry veto, that
   *  one decides whether the agent may execute unattended. */
  research_conviction?: number | null
  /** The arithmetic anchor conviction was clamped to. A persistent gap between
   *  this and `research_conviction` means the numbers and the model's read
   *  disagree. */
  derived_research_conviction?: number | null
  report?: ResearchReport | null
  dimensions: DimensionScore[]
  evidence: EvidenceItem[]
  evidence_count: number
  data_gaps: string[]
  /** Agents whose call failed. A dossier missing a section is still served. */
  agents_failed: string[]
  /** Agents never run because their evidence slice held no facts about the
   *  company. Not a failure — nothing broke, there was nothing to assess. */
  agents_skipped: string[]
  /** Set only when `report` is null because the merge call itself failed,
   *  as opposed to there being nothing for it to merge. */
  synthesis_error?: string | null
  /** What the citation filter removed from `report` — present and possibly
   *  empty whenever a report was produced, absent when there was none to
   *  filter. A non-clean audit means the model wrote at least one uncited or
   *  fabricated claim that no longer appears in the report. */
  citation_audit?: CitationAudit | null
  /** What this dossier does to a BUY on this ticker, right now. Always sent —
   *  a dossier that blocks nothing says so, because "no veto field" and "veto
   *  found nothing" are not the same claim. */
  veto?: ResearchVetoStatus | null
  outcome?: ResearchOutcome | null
  prior_record?: PriorRecordCoverage | null
  debate?: ResearchDebate | null
  /** Advisory stance panel. Never binding on an order — see `TradeStance`. */
  stances?: ResearchStances | null
  /** Which models produced this reading. Empty on dossiers written
   *  before provenance was recorded. */
  models_used?: ModelUsed[]
}

export interface PerformanceResponse {
  total_signals: number
  settled_signals: number
  overall_win_rate?: number
  overall_avg_return_20d?: number
  /** What alpha is measured against, so the client never names it itself. */
  benchmark_ticker?: string | null
  /** Alpha carries its own count. Records settled before benchmark
   *  measurement existed have a return and no alpha, so `settled_signals`
   *  overstates the evidence behind the alpha figure. */
  alpha_settled_signals?: number
  overall_avg_alpha_20d?: number | null
  by_signal: SignalPerformanceRecord[]
  by_ticker: TickerPerformance[]
}

export interface SignalPerformanceRecord {
  signal: Signal
  total: number
  settled: number
  correct: number
  win_rate?: number
  avg_return_20d?: number
  /** Its own denominator — see `PerformanceResponse.alpha_settled_signals`. */
  alpha_settled?: number
  avg_alpha_20d?: number | null
}

export interface TickerPerformance {
  ticker: string
  total: number
  settled: number
  win_rate?: number
  avg_return_20d?: number
  alpha_settled?: number
  avg_alpha_20d?: number | null
}

export interface SignalRecord {
  ticker: string
  signal: Signal
  score: number
  conviction?: string
  price_at_signal?: number
  return_20d?: number
  was_correct?: boolean
  generated_at: string
  analyst_used?: boolean
}

export interface AlertSettings {
  slack_webhook_url?: string
  whatsapp_phone?: string
  whatsapp_apikey?: string
  notify_on_signal_flip: boolean
  notify_on_high_conviction: boolean
  daily_digest: boolean
  /**
   * Order lifecycle notifications, gated separately: `trade` fires when the
   * agent submits an order, `fill` when it actually executes and when a
   * position closes with its realised P&L.
   *
   * Neither has a control on the profile screen yet. They are declared here
   * because both clients PUT the whole settings object back — the round-trip
   * has to carry them, and a field the type does not know about survives only
   * by accident.
   */
  notify_on_trade?: boolean
  notify_on_fill?: boolean
  /** A data source degraded or recovered. Transitions only. */
  notify_on_degraded?: boolean
  /** Blank sends to the account email. */
  trade_email?: string
}

/**
 * How much autonomy the agent has. The ladder is suggest → confirm → automate;
 * new accounts start at MANUAL because an agent that can move money should be
 * opted into rather than defaulted into.
 */
export type TradingMode = 'MANUAL' | 'SEMI_AUTO' | 'AUTO'

export interface AutoTradeSettings {
  enabled: boolean
  mode: TradingMode
  /** SEMI_AUTO only: weakest conviction the agent may act on unattended. */
  auto_execute_conviction: Conviction
  paper_trading: boolean
  min_signal_score: number
  position_size_pct: number
  max_open_positions: number
  max_daily_loss_pct: number
  allowed_tickers: string[]
}

export interface ManualOrderRequest {
  ticker: string
  action: 'BUY' | 'SELL'
  /** A request, not an instruction — the server clamps to what it can fund. */
  qty?: number
  limit_price?: number
  /** Required when the server routes to a live-money account. */
  confirm_live?: boolean
  idempotency_key?: string
}

export interface OrderPlacementResponse {
  placed: boolean
  status: string
  ticker: string
  action: string
  qty: number
  limit_price: number
  order_id?: number | string | null
  stop_loss?: number | null
  take_profit?: number | null
  is_paper: boolean
  trade_id?: string | null
  /** Why it wasn't placed, or how the quantity was adjusted. */
  reason?: string | null
  /** Why it was taken. Same words the order history will show. */
  entry_reason?: string | null
  /** True when this matched an earlier request and no new order was sent. */
  duplicate: boolean
}

export interface BrokerStatus {
  connected: boolean
  provider: string
  host: string
  port: number
  trading_mode: string
  /** False on most deployments — restarting needs the Docker socket mounted. */
  restart_available: boolean
  restart_unavailable_reason?: string | null
  /** Roughly how long IBC takes to log in after a restart. */
  login_seconds: number
}

export interface BrokerRecoveryResult {
  action: string
  connected: boolean
  detail: string
  /** True when the caller should wait rather than read connected=false as failure. */
  pending: boolean
}

/** An entry the agent wanted to take but was not permitted to take alone. */
export interface Proposal {
  id: string
  ticker: string
  action: string
  qty: number
  limit_price: number
  stop_loss?: number | null
  take_profit?: number | null
  signal_score?: number | null
  conviction?: Conviction | null
  reason?: string | null
  /** Why the order was taken, in the few words a person reads: the score
   *  against the bar it had to clear, the factors that actually moved it, and
   *  the analyst's conviction. Written from the same arithmetic that produced
   *  the score — never by a model, and never naming a factor on the ML path.
   *  Distinct from `reason`, which says why an order was *not* placed. */
  entry_reason?: string | null
  proposed_at: string
  is_paper: boolean
}

export interface AutoTradeSettingsResponse extends AutoTradeSettings {
  connected: boolean
}

export interface AccountSummaryResponse {
  net_liquidation: number
  total_cash: number
  unrealized_pnl: number
  realized_pnl: number
  buying_power: number
  connected: boolean
  /** Broker account being traded — this login manages more than one. */
  account_id: string
  /** Market value of open positions ("funds in trade"). */
  gross_position_value: number
}

export interface Holding {
  ticker: string
  qty: number
  avg_cost: number
  market_value: number | null
  unrealized_pnl: number | null
}

export interface HoldingsResponse {
  connected: boolean
  account_id: string
  holdings: Holding[]
  total_market_value: number
}

export interface TradeRecord {
  id: string
  user_id: string
  ticker: string
  action: string
  qty: number
  limit_price: number
  order_id?: number
  status: string
  reason?: string
  signal_score?: number
  signal_type?: string
  /** The analyst's HIGH/MEDIUM/LOW at the time. Present on agent-originated
   *  records; a manual order has none, because nothing was asked. */
  conviction?: string | null
  /** Why the order was taken, in the few words a person reads: the score
   *  against the bar it had to clear, the factors that actually moved it, and
   *  the analyst's conviction. Written from the same arithmetic that produced
   *  the score — never by a model, and never naming a factor on the ML path.
   *  Distinct from `reason`, which says why an order was *not* placed. */
  entry_reason?: string | null
  entry_price?: number
  exit_price?: number
  pnl?: number
  is_paper: boolean
  opened_at: string
  closed_at?: string
  filled_qty?: number
  filled_at?: string
  /** Share of the score built on measured rather than fallback inputs, frozen
   *  at entry. Missing stays missing — 1.0 would claim a completeness nobody
   *  measured. */
  input_completeness?: number | null
  stop_loss?: number
  take_profit?: number
  /** Why the position closed, in the words a person reads. */
  exit_reason?: string | null
  /** The stable code behind it: SELL_SIGNAL / EXIT_ALERT / MANUAL_CLOSE.
   *  Absent on an exit nobody here submitted — a stop or target firing. */
  exit_trigger?: string | null
  /** True while exit_price and pnl are the levels we asked for, not a fill. */
  exit_price_estimated?: boolean | null
}

/**
 * One live price, and where it came from.
 *
 * Deliberately separate from `AnalyzeResponse`: the analysis is a stored
 * judgement that can be hours old and still worth reading, while a price is
 * only worth reading if it is current. `source` says which the reader is
 * looking at — a quote provider being down shows the last stored price,
 * labelled, rather than blanking the page.
 */
export interface Quote {
  ticker: string
  price?: number | null
  day_change_pct?: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  prev_close?: number | null
  as_of?: string | null
  source: 'live' | 'stored' | 'unavailable'
  /** Why the live quote was not used, when it was not. */
  note?: string | null
}

// ── System status ─────────────────────────────────────────────────────────────

/**
 * `ok` working · `stale` a real answer served past its freshness window ·
 * `degraded` answering with less than it should · `failed` configured and
 * erroring · `not_configured` no key, which is a choice rather than a fault ·
 * `never_run` nothing recorded yet.
 */
export type SourceState =
  | 'ok' | 'stale' | 'degraded' | 'failed' | 'not_configured' | 'never_run'

/** What losing a capability costs. Same three words the document groups by. */
export type CapabilityTier = 'stops' | 'behaviour' | 'quiet'

export interface CapabilityStatus {
  id: string
  label: string
  tier: CapabilityTier
  /** The env var that switches it on, when one does. */
  required_key: string | null
  /** What the system does without it — the reason the row is worth reading. */
  impact: string
  /** Which factor it feeds, and that factor's default weight. */
  feeds: string | null
  /** Whether this deployment switched it on. Separate from whether it works. */
  configured: boolean
  state: SourceState
  /** What is happening, as opposed to what it would mean. */
  detail: string
  last_success_at: string | null
  last_error: string | null
  last_error_at: string | null
  consecutive_failures: number
}

export interface CycleStatus {
  last_run_at: string | null
  age_minutes: number | null
  /** Judged against the market clock — the pipeline does not run overnight. */
  stale: boolean
  tickers_ok: number | null
  tickers_total: number | null
  failed_tickers: string[]
  last_error: string | null
}

export interface SystemStatus {
  overall: 'ok' | 'degraded' | 'halted'
  /** Composed on the server so web and mobile cannot word it differently. */
  summary: string
  checked_at: string
  market_open: boolean
  cycle: CycleStatus
  capabilities: CapabilityStatus[]
}

export interface AuthResponse {
  access_token: string
  token_type: string
}

export interface DipBuyCandidate {
  ticker: string
  current_price: number
  rsi_14?: number
  stoch_rsi?: number
  bb_pct?: number
  ma_20?: number
  volume_anomaly?: number
  technical_score: number
  pct_from_ma20?: number
  trigger: 'ENTRY' | 'EXIT_ALERT'
  computed_at: string
}

export interface DipBuyScanResponse {
  entry_candidates: DipBuyCandidate[]
  exit_alerts: DipBuyCandidate[]
  neutral_tickers: DipBuyCandidate[]
  unanalyzed_tickers: string[]
  scanned: number
}

/**
 * Realised trading performance — what the executed orders actually did.
 *
 * Kept separate from signal accuracy: that measures whether a call was right
 * 20 days later, this measures money. Manual and signal-driven trades are
 * never pooled, because a hand-placed position says nothing about whether the
 * signal engine works.
 */
export interface TradeStats {
  closed: number
  /** Closed, but the execution behind the exit is gone — excluded from win_rate. */
  closed_unpriced: number
  open: number
  /** Terminal but unknowable: no position, no order, no execution. Not an outcome. */
  unreconciled: number
  wins: number
  losses: number
  win_rate: number | null
  realised_pnl: number | null
  /**
   * What actually reached the account. Gross P&L is what the position did;
   * this is what survived commission. On a small account the gap is not a
   * rounding detail — a $200 entry pays the same fixed ticket as a $20,000
   * one, so a round trip can cost 0.5% against 0.005%.
   *
   * null when no closed trade has a complete fee total (see net_unknown).
   */
  realised_pnl_net: number | null
  commission_paid: number | null
  /** Fees as a fraction of the gross P&L they were charged against. */
  commission_drag: number | null
  win_rate_net: number | null
  /** Closed and priced trades with a complete fee total — the net denominator. */
  netted: number
  /**
   * Priced, but with no usable commission figure: closed before fee capture
   * shipped, or an execution the venue never priced. Reported rather than
   * folded in at zero, which would understate cost in one direction every time.
   */
  net_unknown: number
  /** Profitable before fees, not after. The number that should drive sizing. */
  wins_lost_to_fees: number
  avg_win: number | null
  avg_loss: number | null
  best: number | null
  worst: number | null
  /**
   * Capital these trades turned over — each round trip's own basis (blended
   * entry × filled qty, so scale-ins are included), summed.
   *
   * It is turnover, NOT account size and NOT capital at risk: ten sequential
   * $1,000 trades deploy $10,000. Right base for "did these trades earn their
   * keep", wrong one for "how is the account doing" — that is net liquidation.
   */
  capital_deployed: number | null
  /** Gross P&L as a fraction of `capital_deployed`, over the same trades. */
  return_on_capital: number | null
  /** The same two, narrowed to trades with a complete fee total. */
  capital_deployed_net: number | null
  return_on_capital_net: number | null

  // ── Benchmark-relative ──────────────────────────────────────────────────
  // Served since benchmark measurement shipped; typed here late, so treat
  // every one as possibly absent from an older response.
  benchmark_ticker?: string | null
  /** Closed trades carrying an alpha — alpha's own denominator, never `closed`. */
  alpha_measured?: number
  /** Priced, but closed before alpha existed or with an unreadable benchmark. */
  alpha_unknown?: number
  avg_alpha?: number | null
  alpha_win_rate?: number | null
  /** What holding the index over the same windows returned — the bar to clear. */
  avg_benchmark_return?: number | null
  /** Made money and still lost to the index. */
  wins_lost_to_benchmark?: number
}

export interface ClosedTrade {
  ticker: string
  action: string
  qty: number | null
  entry_price: number | null
  exit_price: number | null
  pnl: number | null
  pnl_net: number | null
  commission_paid: number | null
  /** false marks a fee total that is a floor, not a figure — show gross only. */
  commission_complete: boolean
  /** Adds made to this position; each one paid its own ticket. */
  scale_ins: number
  pnl_pct: number | null
  stop_loss: number | null
  take_profit: number | null
  /**
   * What the position did between entry and exit, against entry.
   *
   * `mfe_pct` beside `pnl_pct` is the whole give-back story on one row: +0.09
   * and −0.05 is a position that ran nine percent and stopped out. Null — never
   * 0 — when the position was never observed while open, which is every trade
   * closed before excursions were recorded.
   */
  mfe_pct?: number | null
  mae_pct?: number | null
  gave_back_pct?: number | null
  /** `breakeven` or `trail` when the stop was raised while the position ran. */
  stop_raised_by?: string | null
  /** Why the position was opened. Both halves of the story on one row. */
  entry_reason?: string | null
  exit_reason: string | null
  /**
   * The stable code behind exit_reason. `TAKE_PROFIT` / `STOP_LOSS` are named
   * by reconciliation from the levels the trade carried; `SELL_SIGNAL` /
   * `MANUAL_CLOSE` come from the exit path itself. Null means the close could
   * not be attributed to either leg — not that a leg fired.
   */
  exit_trigger?: string | null
  status: string
  signal_type: string | null
  is_paper: boolean
  opened_at: string | null
  closed_at: string | null
}

export interface TradePerformanceResponse {
  /** The agent chose it and placed it unattended — the only clean read of the engine. */
  signal_driven: TradeStats
  /** The agent chose it, a human approved it. Measures the pair, not the agent. */
  approved: TradeStats
  /** A human chose it. Says nothing about the engine. */
  manual: TradeStats
  /**
   * `signal_driven` + `approved`: every trade the *tool* picked, however it
   * reached the venue. The one legitimate pooling, because it answers a
   * question the three separate buckets cannot — whose ideas were better,
   * the tool's or yours — and who pressed the button is irrelevant to it.
   *
   * Not a clean read of the engine and must never be labelled as one: half of
   * it passed a human filter. Anything showing this must also show the
   * auto/semi split it was built from.
   */
  agent_originated: TradeStats
  all: TradeStats
  /**
   * How positions actually ended, keyed by `exit_trigger` (plus `unknown`).
   *
   * The four buckets above answer "who chose this trade"; none of them answers
   * "how did it end", which for a strategy built on buying weakness and selling
   * strength is the other half. `avg_gave_back_pct` against `avg_return_pct` in
   * the same bucket is what a trailing stop should be argued from.
   */
  exits: Record<string, ExitBucket>
  recent_closed: ClosedTrade[]
}

export interface ExitBucket {
  n: number
  significant: boolean
  wins: number
  total_pnl: number | null
  avg_return_pct: number | null
  /**
   * Its own sample count: the excursion series starts later than the trade
   * series, so a mean over four of forty rows must not read as one over forty.
   */
  measured_n: number
  avg_mfe_pct: number | null
  avg_mae_pct: number | null
  avg_gave_back_pct: number | null
}

// ── Chart ─────────────────────────────────────────────────────────────────────

export interface OhlcBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartSeries {
  ticker: string
  bars: OhlcBar[]
  sma_20: { date: string; value: number }[]
  sma_50: { date: string; value: number }[]
}

// ── Calibration ───────────────────────────────────────────────────────────────

/**
 * Every bucket carries `n` and `significant`. Below `min_samples_for_signal`
 * a win rate is anecdote, and the API says so rather than returning a
 * confident-looking percentage — the UI must not launder that away.
 */
export interface CalibrationBucket {
  n: number
  win_rate: number | null
  avg_return: number | null
  median_return: number | null
  significant: boolean
  /** Alpha carries its OWN count and its own significance flag. Records
   *  settled before benchmark measurement existed have a return and no alpha,
   *  so the two samples are different sizes — showing one `n` against both
   *  would let a three-record alpha inherit a three-hundred-record
   *  confidence. */
  alpha_n: number
  alpha_win_rate: number | null
  avg_alpha: number | null
  median_alpha: number | null
  alpha_significant: boolean
}

export interface ScoreBucket extends CalibrationBucket {
  lo: number
  hi: number
}

export interface ThresholdRow extends CalibrationBucket {
  threshold: number
  risk_filtered: boolean
  /** Fraction of the sample that actually carried a risk score. */
  risk_coverage: number
}

export interface ConfidenceBucket extends CalibrationBucket {
  lo: number
  hi: number
}

export interface CalibrationReport {
  ticker: string | null
  settled_records: number
  benchmark_ticker?: string | null
  alpha_records?: number
  base_rate: CalibrationBucket
  score_buckets: ScoreBucket[]
  /** null when there aren't enough usable buckets to say either way. */
  score_ranks_outcomes: boolean | null
  /** The stricter test, asked of alpha on its own sample. A score can rank raw
   *  returns simply by preferring high-beta names in a rising market, and
   *  would look calibrated right up to the month the market turns. */
  score_ranks_alpha?: boolean | null
  usable_buckets: number
  alpha_usable_buckets?: number
  threshold_sweep: ThresholdRow[]
  confidence_buckets: ConfidenceBucket[]
  analyst_gate?: OverrideCounterfactual | null
  min_samples_for_signal: number
}

/**
 * One side of the analyst gate, against the decisions it left alone.
 *
 * `direction` is `short` on the restored-SELL block, meaning its outcomes are
 * sign-flipped: a SELL is right when the name falls, so raw figures would
 * report a fall as a loss and invert the finding.
 */
export interface OverrideBlock {
  direction: 'long' | 'short'
  control_label: string
  overridden: CalibrationBucket
  control: CalibrationBucket
  /** Positive = the gate's intervention was justified. The only figure
   *  comparable across the two blocks — within a block the raw numbers share
   *  an orientation with each other and not with the other block. */
  alpha_saved: number | null
  conclusive: boolean
}

export interface OverrideCounterfactual {
  /** Rows where the gate was recorded at all. Rows predating 1.24.0 carry no
   *  override field and are excluded — absent is "never recorded", which is
   *  not the same fact as "nothing to override". */
  recorded_records: number
  buy_refused: OverrideBlock
  sell_restored: OverrideBlock
}

// ── Research calibration ──────────────────────────────────────────────────────
// Whether the deep-research reading predicts anything. Graded on alpha rather
// than raw return: BULLISH on a name that rose 4% while the market rose 9% was
// not right, and counting it as a win is how a desk mistakes exposure for skill.

export interface ConvictionBucket extends CalibrationBucket {
  lo: number
  hi: number
}

export interface AssessmentAccuracyRow extends CalibrationBucket {
  assessment: 'BULLISH' | 'NEUTRAL' | 'BEARISH'
  /** Smaller than `n` on purpose: NEUTRAL readings and unmeasurable windows
   *  are excluded rather than counted as misses, which would make the number
   *  describe the sample's direction instead of the reading's quality. */
  graded: number
  correct: number
  accuracy: number | null
}

/** What the names research would have refused actually did. The number
 *  `RESEARCH_VETO_ENABLED` should be argued from, and that nobody has had. */
export interface VetoCounterfactual {
  floor: number
  would_block: CalibrationBucket
  allowed: CalibrationBucket
  /** Positive means the veto refused the worse names — the only result that
   *  justifies switching it on. `null` when either side is too thin to
   *  compare, which is the honest answer far more often than not. */
  alpha_saved: number | null
  conclusive: boolean
}

export interface ResearchCalibrationReport {
  ticker: string | null
  graded_dossiers: number
  benchmark_ticker: string
  base_rate: CalibrationBucket
  conviction_buckets: ConvictionBucket[]
  conviction_ranks_alpha: boolean | null
  usable_buckets: number
  assessment_accuracy: AssessmentAccuracyRow[]
  veto_counterfactual: VetoCounterfactual
  /** A high graded count with few lessons means reflection is running and
   *  being citation-filtered away — a different problem from it not running. */
  lessons_recorded: number
  min_samples_for_signal: number
}

/** One account, as the Admin page sees it. Carries no credential of any kind. */
export interface AdminUser {
  id: string
  email: string
  display_name: string
  created_at?: string | null
  access_tier: AccessTier
  /** The operator's per-user override, or null when the plan default applies. */
  watchlist_cap_override?: number | null
  /** What that resolves to. null is unlimited. */
  watchlist_cap?: number | null
  watching: number
  research_enabled: boolean
  research_daily_allowed: boolean
  llm_key_count: number
  is_admin: boolean
}

/** A contact-form submission, waiting to be turned into an account. */
export interface AccessRequest {
  id: string
  name: string
  email: string
  message: string
  interest?: string | null
  created_at?: string | null
}
