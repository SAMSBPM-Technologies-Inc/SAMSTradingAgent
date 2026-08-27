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
  conviction?: number | null
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

export interface ResearchDossier {
  ticker: string
  as_of: string
  stale: boolean
  age_hours?: number | null
  conviction?: number | null
  /** The arithmetic anchor conviction was clamped to. A persistent gap between
   *  this and `conviction` means the numbers and the model's read disagree. */
  derived_conviction?: number | null
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
  entry_price?: number
  exit_price?: number
  pnl?: number
  is_paper: boolean
  opened_at: string
  closed_at?: string
  filled_qty?: number
  stop_loss?: number
  take_profit?: number
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
  exit_reason: string | null
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
  all: TradeStats
  recent_closed: ClosedTrade[]
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
