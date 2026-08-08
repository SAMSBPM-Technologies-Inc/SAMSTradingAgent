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

  register: (email: string, password: string, display_name: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/register', {
      email,
      password,
      display_name,
    }),

  me: () => api.get<{ id: string; email: string; display_name: string }>('/auth/me'),

  updateProfile: (display_name: string) =>
    api.patch<{ id: string; email: string; display_name: string }>('/auth/me', { display_name }),
}

export const watchlistApi = {
  get: () => api.get('/watchlist'),
  add: (ticker: string) => api.post('/ticker', { ticker }),
  remove: (ticker: string) => api.delete(`/watchlist/${ticker}`),
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
