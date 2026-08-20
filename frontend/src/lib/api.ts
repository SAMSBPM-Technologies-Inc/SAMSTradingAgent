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
  get: () => api.get('/watchlist'),
  add: (ticker: string) => api.post('/ticker', { ticker }),
  remove: (ticker: string) => api.delete(`/ticker/${ticker}`),
}

export const analyzeApi = {
  get: (ticker: string, forceRefresh = false) =>
    api.get('/analyze', { params: { ticker, force_refresh: forceRefresh } }),
  search: (q: string) =>
    api.get<{ symbol: string; name: string }[]>('/ticker/search', { params: { q } }),
}

export const performanceApi = {
  get: () => api.get('/performance'),
  signals: () => api.get<import('../types').SignalRecord[]>('/performance/signals'),
}

export const radarApi = {
  scan: () => api.get<import('../types').DipBuyScanResponse>('/signals/dip-buy'),
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
}
