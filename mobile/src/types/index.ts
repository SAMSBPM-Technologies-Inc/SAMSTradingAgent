export type Signal = 'BUY' | 'SELL' | 'HOLD'

/**
 * Timing setup for a watched ticker — the dip-buy classification that used to
 * live on its own Radar tab. PENDING means the pipeline has not produced
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

export interface User {
  id: string
  email: string
  display_name: string
  scoring_weights?: Record<string, number> | null
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

  // ── Timing setup (formerly the Radar tab's dip-buy scan) ──────────────────
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

/** Risk assessment — gates every BUY. */
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

/** The thresholds behind the verdict, read from the engine rather than restated. */
export interface SignalGate {
  buy_threshold: number
  sell_threshold: number
  risk_max_for_buy: number
  score_passes_buy: boolean
  risk_passes_buy: boolean
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
  catalysts?: string[]
  key_risks?: string[]
  alternative_data?: AlternativeData
  current_price?: number
  day_change_pct?: number
  /** Whether the AI analyst actually ran for this document, or the rule-based path did. */
  analyst_used?: boolean
  /** The model this server is configured to call. Null when the analyst is disabled. */
  analyst_model?: string | null
}

export interface PerformanceResponse {
  total_signals: number
  settled_signals: number
  overall_win_rate?: number
  overall_avg_return_20d?: number
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
}

export interface TickerPerformance {
  ticker: string
  total: number
  settled: number
  win_rate?: number
  avg_return_20d?: number
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

export interface AutoTradeSettingsResponse extends AutoTradeSettings {
  connected: boolean
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
  /** True when this matched an earlier request and no new order was sent. */
  duplicate: boolean
}

/**
 * Every bucket carries `n` and `significant`. Below `min_samples_for_signal` a
 * win rate is anecdote, and the API says so rather than returning a
 * confident-looking percentage — the UI must not launder that away.
 */
export interface CalibrationBucket {
  n: number
  win_rate: number | null
  avg_return: number | null
  median_return: number | null
  significant: boolean
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
  base_rate: CalibrationBucket
  score_buckets: ScoreBucket[]
  /** null when there aren't enough usable buckets to say either way. */
  score_ranks_outcomes: boolean | null
  usable_buckets: number
  threshold_sweep: ThresholdRow[]
  confidence_buckets: ConfidenceBucket[]
  min_samples_for_signal: number
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
  proposed_at: string
  is_paper: boolean
}

export interface AccountSummaryResponse {
  net_liquidation: number
  total_cash: number
  unrealized_pnl: number
  realized_pnl: number
  buying_power: number
  connected: boolean
  account_id: string
  gross_position_value: number
}

export interface TradeRecord {
  id: string
  user_id: string
  ticker: string
  action: string
  qty: number
  limit_price: number
  /** IBKR emits ints, Alpaca emits UUID strings. */
  order_id?: number | string
  /** Protective legs submitted with the entry. */
  stop_loss?: number | null
  take_profit?: number | null
  status: string
  reason?: string
  signal_score?: number
  signal_type?: string
  entry_price?: number
  exit_price?: number
  pnl?: number
  is_paper: boolean
  opened_at: string
  closed_at?: string
  /** Written by reconciliation — may be less than qty on a partial fill. */
  filled_qty?: number | null
  filled_at?: string | null
  /** Why the position closed, in the words a person reads. */
  exit_reason?: string | null
  /** The stable code behind it: SELL_SIGNAL / EXIT_ALERT / MANUAL_CLOSE.
   *  Absent on an exit nobody here submitted — a stop or target firing. */
  exit_trigger?: string | null
  /** True while exit_price and pnl are the levels we asked for, not a fill. */
  exit_price_estimated?: boolean | null
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
