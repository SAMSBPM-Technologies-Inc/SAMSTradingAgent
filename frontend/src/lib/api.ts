import axios from 'axios'

const TOKEN_KEY = 'sams_token'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor — inject auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor — handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url: string = error.config?.url ?? ''
      // Don't redirect on auth endpoints — let the form handler show the error message
      if (!url.includes('/auth/')) {
        localStorage.removeItem(TOKEN_KEY)
        if (typeof window !== 'undefined') {
          window.location.href = '/auth'
        }
      }
    }
    return Promise.reject(error)
  },
)

export const TOKEN_STORAGE_KEY = TOKEN_KEY

// Typed API helpers

/* The only endpoint the public landing page calls, and the only one on the
   whole client that needs no token — the axios interceptor simply finds none
   to attach. Kept separate from authApi so it is obvious that reaching it does
   not imply a session. */
export const contactApi = {
  send: (body: { name: string; email: string; message: string; company?: string }) =>
    api.post<{ sent: boolean }>('/contact', body),
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', {
      username: email,
      password,
    }, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),

  loginJson: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', { email, password }),

  me: () => api.get<import('../types').User>('/auth/me'),

  updateProfile: (data: { display_name?: string; scoring_weights?: import('../types').ScoringWeights | null }) =>
    api.put<{ status: string }>('/auth/me', data),
}

export const watchlistApi = {
  get: () => api.get<import('../types').WatchlistResponse>('/watchlist'),
  add: (ticker: string) => api.post('/ticker', { ticker }),
  remove: (ticker: string) => api.delete(`/ticker/${ticker}`),
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
   * Builds a new dossier. Five model calls and tens of seconds, so this is
   * never called implicitly — the user has to ask for it.
   */
  build: (ticker: string) =>
    api.post<import('../types').ResearchDossier>(`/research/${ticker}`, undefined, {
      timeout: 300_000,
    }),
}

export const performanceApi = {
  get: () => api.get('/performance'),
  signals: () => api.get<import('../types').SignalRecord[]>('/performance/signals'),
  trades: () =>
    api.get<import('../types').TradePerformanceResponse>('/performance/trades'),
  calibration: (ticker?: string, applyRiskGate = true) =>
    api.get<import('../types').CalibrationReport>('/performance/calibration', {
      params: { ticker, apply_risk_gate: applyRiskGate },
    }),
}

export const chartApi = {
  /** OHLCV + SMA for the interactive chart. The PNG at /chart/{t} is export-only. */
  series: (ticker: string, days = 180) =>
    api.get<import('../types').ChartSeries>(`/chart/${ticker}/series`, {
      params: { days },
    }),
}

export const alertsApi = {
  getSettings: () => api.get<import('../types').AlertSettings>('/alerts/settings'),
  updateSettings: (data: import('../types').AlertSettings) => api.put<import('../types').AlertSettings>('/alerts/settings', data),
  sendTest: () => api.post<{ status: string; channels: string[] }>('/alerts/test'),
}

export const tradingApi = {
  getSettings: () => api.get<import('../types').AutoTradeSettingsResponse>('/trading/settings'),
  updateSettings: (data: import('../types').AutoTradeSettings) =>
    api.put<import('../types').AutoTradeSettingsResponse>('/trading/settings', data),
  getAccount: () => api.get<import('../types').AccountSummaryResponse>('/trading/account'),
  getPositions: () => api.get<import('../types').TradeRecord[]>('/trading/positions'),
  getHoldings: () => api.get<import('../types').HoldingsResponse>('/trading/holdings'),
  getOrders: () => api.get<import('../types').TradeRecord[]>('/trading/orders'),
  closePosition: (ticker: string) => api.post(`/trading/close/${ticker}`),

  /**
   * Place a user-initiated order. `qty` is a request — the server re-derives
   * the fundable size and may return less. Always send an idempotency key so a
   * double-clicked button cannot buy twice.
   */
  placeOrder: (body: import('../types').ManualOrderRequest) =>
    api.post<import('../types').OrderPlacementResponse>('/trading/order', body),

  brokerStatus: () => api.get<import('../types').BrokerStatus>('/trading/broker/status'),
  /** Safe: forces an immediate connect attempt instead of waiting out the backoff. */
  brokerReconnect: () =>
    api.post<import('../types').BrokerRecoveryResult>('/trading/broker/reconnect'),
  /** Restarts the gateway container — only where the server allows it. */
  brokerRestart: () =>
    api.post<import('../types').BrokerRecoveryResult>('/trading/broker/restart'),

  getProposals: () => api.get<import('../types').Proposal[]>('/trading/proposals'),
  approveProposal: (id: string, confirmLive = false) =>
    api.post<import('../types').OrderPlacementResponse>(
      `/trading/proposals/${id}/approve`, null, { params: { confirm_live: confirmLive } },
    ),
  declineProposal: (id: string) => api.post(`/trading/proposals/${id}/decline`),
}
