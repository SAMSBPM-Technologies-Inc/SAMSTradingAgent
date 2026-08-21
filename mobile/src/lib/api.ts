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

  getProposals: () => api.get<import('../types').Proposal[]>('/trading/proposals'),
  approveProposal: (id: string, confirmLive = false) =>
    api.post<import('../types').OrderPlacementResponse>(
      `/trading/proposals/${id}/approve`, null, { params: { confirm_live: confirmLive } },
    ),
  declineProposal: (id: string) => api.post(`/trading/proposals/${id}/decline`),
}
