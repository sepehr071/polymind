import axios from 'axios'
import { API_BASE_URL } from './apiBase'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  // httpOnly-cookie auth: the access/refresh tokens live in cookies JS cannot
  // read, so every request must carry credentials for the browser to attach
  // them. There is no Authorization header anymore.
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
  maxContentLength: 50 * 1024 * 1024, // 50MB
  maxBodyLength: 50 * 1024 * 1024, // 50MB
})

// CSRF: the backend requires `X-CSRF-Token` on every cookie-authed mutation.
// We attach it to all non-GET requests (harmless on the ones that don't need
// it). GET/HEAD are exempt because they're not state-changing.
api.interceptors.request.use(
  (config) => {
    const method = (config.method || 'get').toLowerCase()
    if (method !== 'get' && method !== 'head') {
      config.headers['X-CSRF-Token'] = '1'
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Single-flight refresh lock. The backend rotates the refresh token on every
// /auth/refresh (P0.4) — if N parallel requests 401 at once and each fires its
// own refresh, request #1 rotates the jti and #2..N replay the now-revoked
// token → 401 → logout mid-session. We collapse all concurrent refreshes onto
// one shared promise; waiters await it and retry with the resulting token.
let refreshPromise = null

// Performs exactly one token refresh. The refresh token lives in an httpOnly
// cookie the browser sends automatically with `withCredentials`; the backend
// rotates it and re-sets the cookies as a side effect. There is nothing to
// read from or write to JS storage. Uses bare `axios.post` (NOT the `api`
// instance) so the refresh call never recurses back through this interceptor,
// but still sends credentials + the CSRF header the cookie-authed endpoint
// requires.
async function performTokenRefresh() {
  await axios.post(`${API_BASE_URL}/auth/refresh`, {}, {
    timeout: 15000,
    withCredentials: true,
    headers: {
      'X-CSRF-Token': '1',
    },
  })
}

// Response interceptor to handle token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // If 401 and not already retried, try to refresh token
    const reqUrl = originalRequest?.url || ''
    if (typeof reqUrl === 'string' && reqUrl.includes('/auth/logout')) {
      return Promise.reject(error)
    }
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        // Single-flight: the first 401 starts the refresh; concurrent 401s
        // await the same in-flight promise instead of racing their own
        // refresh (which would replay a rotated/revoked token). Reset in
        // `finally` so the next token expiry can refresh again.
        if (!refreshPromise) {
          refreshPromise = performTokenRefresh().finally(() => {
            refreshPromise = null
          })
        }
        await refreshPromise

        // Retry original request — the rotated tokens are already in cookies,
        // so there is no Authorization header to re-set.
        return api(originalRequest)
      } catch (refreshError) {
        // Refresh failed → effectively logged out. The auth cookies are
        // cleared server-side (or already expired); here we drop the
        // non-sensitive auth_present flag and scoping keys so the next login
        // lands the user on a real workspace/project instead of inheriting
        // stale IDs.
        localStorage.removeItem('auth_present')
        localStorage.removeItem('auth_kind')
        localStorage.removeItem('kc_id_token')
        try {
          localStorage.removeItem('active_workspace_id')
          Object.keys(localStorage).forEach((k) => {
            if (k.startsWith('active_project_id::')) {
              localStorage.removeItem(k)
            }
          })
        } catch {
          // ignore
        }
        // Event-bus handoff to AuthContext: it owns queryClient + router.
        // Listener clears React Query cache and SPA-navigates to /login,
        // avoiding the full-page reload that previously masked the
        // missing cache.clear(). Guarded for non-browser/test contexts.
        if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
          window.dispatchEvent(new Event('auth:cleared'))
        } else {
          // Fallback for environments without dispatchEvent (e.g. SSR).
          if (typeof window !== 'undefined') {
            window.location.href = '/login'
          }
        }
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

export default api
