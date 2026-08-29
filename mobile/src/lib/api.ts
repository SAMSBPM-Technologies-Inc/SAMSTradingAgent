import axios from 'axios'
import Constants from 'expo-constants'

const BASE_URL =
  (Constants.expoConfig?.extra?.apiBaseUrl as string | undefined) ?? 'http://localhost:8000'

const TOKEN_KEY = 'sams_token'

export const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

// Module-level token cache — keeps the Axios interceptor synchronous
let _cachedToken: string | null = null
let _onUnauthorized: (() => void) | null = null

export function syncTokenToApi(token: string | null) {
  _cachedToken = token
}

export function registerUnauthorizedHandler(handler: () => void) {
  _onUnauthorized = handler
}

api.interceptors.request.use((config) => {
  if (_cachedToken) {
    config.headers.Authorization = `Bearer ${_cachedToken}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url: string = error.config?.url ?? ''
      if (!url.includes('/auth/')) {
        _cachedToken = null
        _onUnauthorized?.()
      }
    }
    return Promise.reject(error)
  },
)

export const TOKEN_STORAGE_KEY = TOKEN_KEY

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>(
      '/auth/login',
      { username: email, password },
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
    ),

  loginJson: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password }),

  me: () => api.get<{ id: string; email: string; display_name: string; scoring_weights?: Record<string, number> | null }>('/auth/me'),

  updateProfile: (data: { display_name?: string; scoring_weights?: Record<string, number> | null }) =>
    api.put<{ status: string }>('/auth/me', data),
}

export const watchlistApi = {
  get: () => api.get<import('../types').WatchlistResponse>('/watchlist'),
  add: (ticker: string) => api.post('/ticker', { ticker }),
  remove: (ticker: string) => api.delete(`/ticker/${ticker}`),
}

export const chartApi = {
  /** OHLCV + SMA for the chart. The PNG at /chart/{t} is export-only. */
  series: (ticker: string, days = 180) =>
    api.get<import('../types').ChartSeries>(`/chart/${ticker}/series`, { params: { days } }),
}

export const analyzeApi = {
  get: (ticker: string, forceRefresh = false) =>
    api.get('/analyze', { params: { ticker, force_refresh: forceRefresh } }),
  search: (q: string) =>
    api.get<{ symbol: string; name: string }[]>('/ticker/search', { params: { q } }),
}

export const researchApi = {
  /** Reads the stored dossier. Free and fast; may be stale. */
  get: (ticker: string) =>
    api.get<import('../types').ResearchDossier>(`/research/${ticker}`),
  /**
   * Builds a new one — five model calls and tens of seconds, so this is never
   * called implicitly. On mobile the long timeout matters more than on web:
   * the default would abort a request that is still working fine.
   */
  build: (ticker: string) =>
    api.post<import('../types').ResearchDossier>(`/research/${ticker}`, undefined, {
      timeout: 300_000,
    }),
  /**
   * The veto reading alone — whether research currently blocks a BUY on this
   * ticker. Cheap enough for an order ticket to call on every open, which the
   * full dossier is not: that response carries the whole evidence ledger.
   * Never 404s; a ticker with no dossier truthfully blocks nothing.
   */
  veto: (ticker: string) =>
    api.get<import('../types').ResearchVetoStatus>(`/research/${ticker}/veto`),
}

export const performanceApi = {
  get: () => api.get('/performance'),
  signals: () => api.get<import('../types').SignalRecord[]>('/performance/signals'),
  calibration: (ticker?: string, applyRiskGate = true) =>
    api.get<import('../types').CalibrationReport>('/performance/calibration', {
      params: { ticker, apply_risk_gate: applyRiskGate },
    }),
}

export const alertsApi = {
  getSettings: () => api.get<import('../types').AlertSettings>('/alerts/settings'),
  updateSettings: (data: import('../types').AlertSettings) =>
    api.put<import('../types').AlertSettings>('/alerts/settings', data),
  sendTest: () => api.post<{ status: string; channels: string[] }>('/alerts/test'),
}

export const tradingApi = {
  getSettings: () => api.get<import('../types').AutoTradeSettingsResponse>('/trading/settings'),
  updateSettings: (data: import('../types').AutoTradeSettings) =>
    api.put<import('../types').AutoTradeSettingsResponse>('/trading/settings', data),
  getAccount: () => api.get<import('../types').AccountSummaryResponse>('/trading/account'),
  getPositions: () => api.get<import('../types').TradeRecord[]>('/trading/positions'),
  getOrders: () => api.get<import('../types').TradeRecord[]>('/trading/orders'),
  closePosition: (ticker: string) => api.post(`/trading/close/${ticker}`),

  /**
   * Place a user-initiated order. `qty` is a request — the server re-derives
   * the fundable size and may return less. Always send an idempotency key so a
   * double-tapped button cannot buy twice.
   */
  placeOrder: (body: import('../types').ManualOrderRequest) =>
    api.post<import('../types').OrderPlacementResponse>('/trading/order', body),

  getHoldings: () => api.get<import('../types').HoldingsResponse>('/trading/holdings'),
  getProposals: () => api.get<import('../types').Proposal[]>('/trading/proposals'),
  approveProposal: (id: string, confirmLive = false) =>
    api.post<import('../types').OrderPlacementResponse>(
      `/trading/proposals/${id}/approve`, null, { params: { confirm_live: confirmLive } },
    ),
  declineProposal: (id: string) => api.post(`/trading/proposals/${id}/decline`),
}

/** Which models your agents run on. Keys are write-only: they go in through
 *  `addKey` and never come back — the response type has no field for one. */
export const llmApi = {
  settings: () => api.get<import('../types').LLMSettings>('/settings/llm'),
  save: (roles: import('../types').LLMRoleChains, researchEnabled: boolean) =>
    api.put<import('../types').LLMSettings>('/settings/llm', {
      roles,
      research_enabled: researchEnabled,
    }),
  /** Validated with a real schema-constrained call before it is stored — a key
   *  that does not work is refused here rather than skipped silently every
   *  night. */
  addKey: (provider: string, apiKey: string, label: string) =>
    api.post<import('../types').LLMSettings>('/settings/llm/keys', {
      provider,
      api_key: apiKey,
      label,
    }),
  deleteKey: (keyId: string) =>
    api.delete<import('../types').LLMSettings>(`/settings/llm/keys/${keyId}`),
  testKey: (keyId: string) =>
    api.post<import('../types').LLMKeyTestResult>(
      `/settings/llm/keys/${keyId}/test`,
    ),
}
