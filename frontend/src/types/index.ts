export type Signal = 'BUY' | 'SELL' | 'HOLD'

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
}

export interface WatchlistItem {
  ticker: string
  signal: Signal
  score: number
  confidence: number
  conviction?: Conviction
  current_price?: number
  day_change_pct?: number
  price_target?: number
  thesis?: string
  generated_at: string
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
  risk?: Record<string, unknown>
  bull_case?: string
  bear_case?: string
  catalysts?: string[]
  key_risks?: string[]
  alternative_data?: AlternativeData
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
}

export interface AuthResponse {
  access_token: string
  token_type: string
}
