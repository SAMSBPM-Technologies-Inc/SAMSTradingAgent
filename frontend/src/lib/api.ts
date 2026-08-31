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
  send: (body: {
    name: string
    email: string
    message: string
    company?: string
    /** What they are after, in their terms. Never a plan name — see HomePage. */
    interest?: 'read' | 'research' | 'trade' | ''
  }) => api.post<{ sent: boolean }>('/contact', body),
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

  /**
   * Change your own password. Returns a fresh token, and that is not a
   * convenience: the change invalidates every token issued before it,
   * including the one this request was sent with. The caller must store the
   * new one or it signs itself out.
   */
  changePassword: (current_password: string, new_password: string) =>
    api.put<{ access_token: string; token_type: string }>('/auth/password', {
      current_password,
      new_password,
    }),

  /** Ask for a reset link. The response is identical whether or not the
   *  address has an account — do not try to read anything into it. */
  forgotPassword: (email: string) =>
    api.post<{ sent: boolean }>('/auth/forgot-password', { email }),

  /** Redeem a link. Returns a token, so the caller lands signed in. */
  resetPassword: (token: string, new_password: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/reset-password', {
      token,
      new_password,
    }),
}

export const watchlistApi = {
  get: () => api.get<import('../types').WatchlistResponse>('/watchlist'),
  add: (ticker: string) => api.post('/ticker', { ticker }),
  remove: (ticker: string) => api.delete(`/ticker/${ticker}`),
}

export const analyzeApi = {
  /**
   * The last analysis, whatever its age, and never a pipeline run.
   *
   * This is what a ticker click calls. Plain `/analyze` rebuilds anything older
   * than 30 minutes, and a rebuild is yfinance, Finnhub, FRED, fundamentals and
   * an LLM call — seconds of waiting for work the reader did not ask for.
   * 404 means nothing has ever been analysed, which is an empty state, not an
   * error.
   */
  get: (ticker: string) =>
    api.get<import('../types').AnalyzeResponse>('/analyze', {
      params: { ticker, stored_only: true },
    }),
  /** The explicit full run. The only call on the client that starts a pipeline. */
  run: (ticker: string) =>
    api.get<import('../types').AnalyzeResponse>('/analyze', {
      params: { ticker, force_refresh: true },
      // A cold run does the whole pipeline plus an analyst call; the default
      // axios timeout would abandon it halfway and report a failure that was
      // still succeeding on the server.
      timeout: 180_000,
    }),
  /** One live price. Cheap enough to call on every ticker view. */
  quote: (ticker: string) =>
    api.get<import('../types').Quote>(`/quote/${ticker}`),
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
  trades: () =>
    api.get<import('../types').TradePerformanceResponse>('/performance/trades'),
  calibration: (ticker?: string, applyRiskGate = true) =>
    api.get<import('../types').CalibrationReport>('/performance/calibration', {
      params: { ticker, apply_risk_gate: applyRiskGate },
    }),
  /** Does the deep-research reading predict anything? Unscoped by watchlist:
   *  dossiers are a shared series, and slicing them per-user would thin every
   *  bucket for no gain in relevance. */
  researchCalibration: (ticker?: string) =>
    api.get<import('../types').ResearchCalibrationReport>(
      '/performance/research-calibration', { params: { ticker } },
    ),
}

export const chartApi = {
  /** OHLCV + SMA for the interactive chart. The PNG at /chart/{t} is export-only. */
  series: (ticker: string, days = 180) =>
    api.get<import('../types').ChartSeries>(`/chart/${ticker}/series`, {
      params: { days },
    }),
}

export const systemApi = {
  /**
   * What is working right now. Nothing is probed on the server — every row is
   * what the source actually did on the last pipeline cycle, so this is cheap
   * to poll and, unlike a probe, describes the data behind the score on screen.
   */
  status: () => api.get<import('../types').SystemStatus>('/system/status'),
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
  /** Every order, newest first — or one ticker's, for a per-symbol audit trail
   *  that does not depend on the global row cap reaching far enough back. */
  getOrders: (ticker?: string, limit?: number) =>
    api.get<import('../types').TradeRecord[]>('/trading/orders', {
      params: { ticker, limit },
    }),
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


/**
 * Provisioning. Reachable only by the address in `ADMIN_EMAIL` on the server,
 * which computes `is_admin` and reports it on `/auth/me` — the client never
 * decides who is the operator.
 *
 * Note what is absent: no delete, and no password read-back. A generated
 * password is returned once, by the call that generated it.
 */
export const adminApi = {
  users: () => api.get<import('../types').AdminUser[]>('/admin/users'),

  createUser: (body: {
    email: string
    display_name?: string
    access_tier: import('./entitlements').AccessTier
    watchlist_cap?: number | null
    research_daily_allowed?: boolean
    password?: string
  }) =>
    api.post<{ user: import('../types').AdminUser; password: string | null }>(
      '/admin/users',
      body,
    ),

  updateUser: (
    id: string,
    body: {
      access_tier?: import('./entitlements').AccessTier
      watchlist_cap?: number
      clear_watchlist_cap?: boolean
      research_daily_allowed?: boolean
    },
    force = false,
  ) =>
    api.patch<import('../types').AdminUser>(`/admin/users/${id}`, body, {
      params: force ? { force: true } : undefined,
    }),

  accessRequests: () =>
    api.get<import('../types').AccessRequest[]>('/admin/access-requests'),

  /**
   * Reset an account's password. Returns it once — nothing can read it back,
   * and every session that account had is dead by the time this resolves.
   */
  resetPassword: (id: string, password?: string) =>
    api.post<{ email: string; password: string }>(
      `/admin/users/${id}/password`,
      password ? { password } : {},
    ),
}
