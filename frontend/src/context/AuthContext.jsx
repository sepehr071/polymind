import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { authService } from '../services/authService'
import toast from 'react-hot-toast'

const AuthContext = createContext(null)

const AUTH_ME_KEY = ['authMe']

// Strip every workspace/project scoping key from localStorage so a re-login
// (or post-logout idle) doesn't inherit a stale active workspace/project that
// no longer belongs to the new user.
function clearScopingState() {
  try {
    localStorage.removeItem('active_workspace_id')
    Object.keys(localStorage).forEach((k) => {
      if (k.startsWith('active_project_id::')) {
        localStorage.removeItem(k)
      }
    })
  } catch {
    // ignore — quota/privacy errors are non-fatal
  }
}

export function AuthProvider({ children }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { t } = useTranslation('auth')
  // httpOnly-cookie auth: JS can't read the access token, so we gate the
  // `/auth/me` query on a non-sensitive `auth_present` flag (the cookie is the
  // real credential). Force-re-evaluate `enabled` when login/logout flips it —
  // useQuery doesn't observe localStorage directly.
  const [hasToken, setHasToken] = useState(() => !!localStorage.getItem('auth_present'))

  // React Query owns the user. Per-query staleTime (30s) overrides the
  // global 5min in main.jsx; refetchOnWindowFocus picks up platform-feature
  // toggles when the user returns to the tab.
  const {
    data: user,
    isLoading: isQueryLoading,
    status: queryStatus,
    error: queryError,
  } = useQuery({
    queryKey: AUTH_ME_KEY,
    queryFn: async () => {
      try {
        return await authService.getMe()
      } catch (error) {
        // Try refresh on first 401; api.js interceptor will have already
        // attempted once, but the surfaced error may still be 401 if refresh
        // itself failed earlier. Re-attempt explicitly so first-load survives
        // a near-expired access cookie. The refresh token lives in an httpOnly
        // cookie — authService.refresh() carries it automatically and the
        // backend rotates + re-sets the cookies; nothing to read or store.
        const status = error?.response?.status
        if (status !== 401) throw error

        await authService.refresh()
        return await authService.getMe()
      }
    },
    enabled: hasToken,
    // 3-minute staleness is acceptable freshness for the user/feature payload.
    // Keep refetch-on-focus so a feature-flag toggle (the documented reason)
    // still gets picked up on the next alt-tab — but the longer staleTime stops
    // an /auth/me firing on EVERY focus for every active user.
    staleTime: 180_000,
    refetchOnWindowFocus: true,
    retry: false,
  })

  // isLoading semantics expected by ProtectedRoute / PublicRoute / FeatureGate:
  //   - no token  → not loading (we're logged out, render redirect)
  //   - token + first fetch in flight → loading
  //   - token + cached data present  → not loading (background refetch is fine)
  const isLoading = hasToken && isQueryLoading

  // Handle unrecoverable auth failure: clear tokens + scoping + cache.
  // Only fire when the query actually errored (refresh path dead). Reacting
  // to a transient `!isFetching && !user` window — which exists briefly under
  // StrictMode + slow networks before the result commits — would wrongly
  // clear a valid session and bounce mid-navigation.
  useEffect(() => {
    if (!hasToken) return
    if (queryStatus !== 'error') return
    const httpStatus = queryError?.response?.status
    // Only treat 401/403 as auth-dead. Network blips (status 0/undefined) or
    // 5xx should keep the session intact — react-query will retry-on-focus.
    if (httpStatus !== 401 && httpStatus !== 403) return
    // Signal LoginPage to surface a one-time "session expired" toast, since
    // this teardown drops the user on /login with no other explanation.
    sessionStorage.setItem('session_expired', '1')
    localStorage.removeItem('auth_present')
    localStorage.removeItem('auth_kind')
    localStorage.removeItem('kc_id_token')
    clearScopingState()
    queryClient.clear()
    setHasToken(false)
  }, [hasToken, queryStatus, queryError, queryClient])

  // Listen for `auth:cleared` from api.js's 401-refresh-failure path.
  // api.js owns localStorage cleanup (tokens + scoping keys) for low coupling;
  // we own React Query cache invalidation + SPA navigation so we don't have
  // to hard-reload the page. Cache `.clear()` after explicit removal of the
  // authMe key keeps the consumer state consistent even if React Query's
  // global cache is shared across providers.
  useEffect(() => {
    const handler = () => {
      // Same "session expired" signal as the 401/403 effect above — api.js's
      // refresh-failure path lands the user on /login with no explanation.
      sessionStorage.setItem('session_expired', '1')
      // api.js already dropped auth_present + scoping keys in its 401 path;
      // mirror the auth_present removal here so this handler is self-sufficient
      // even if dispatched from elsewhere.
      localStorage.removeItem('auth_present')
      localStorage.removeItem('auth_kind')
      localStorage.removeItem('kc_id_token')
      queryClient.removeQueries({ queryKey: AUTH_ME_KEY })
      queryClient.clear()
      setHasToken(false)
      navigate('/login', { replace: true })
    }
    window.addEventListener('auth:cleared', handler)
    return () => {
      window.removeEventListener('auth:cleared', handler)
    }
  }, [queryClient, navigate])

  const login = useCallback(async (email, password) => {
    try {
      const data = await authService.login(email, password)
      // httpOnly-cookie auth: the backend set the auth cookies as a side
      // effect; we only read the JSON body for user/features (no tokens to
      // store). Mark presence so the /auth/me query is enabled.
      localStorage.setItem('auth_present', '1')
      setHasToken(true)
      // Backend returns features at the top level (`{features, user:{...}}`),
      // NOT nested under user. Merge so consumers can read `user.features.<name>`
      // without waiting for the next /auth/me round-trip.
      queryClient.setQueryData(AUTH_ME_KEY, { ...data.user, features: data.features })
      // Single consistent success string across operator + SSO/callback paths.
      toast.success(t('signedIn'))
      return data
    } catch (error) {
      const message = error.response?.data?.error || t('toast.loginFailed')
      toast.error(message)
      throw error
    }
  }, [queryClient, t])

  const loginKeycloak = useCallback(async () => {
    try {
      const keycloakClient = (await import('../services/keycloakClient')).default
      await keycloakClient.init()
      if (!keycloakClient.isEnabled()) {
        toast.error(t('toast.ssoNotConfigured'))
        return
      }
      // Navigates away — never resolves
      await keycloakClient.loginRedirect()
    } catch (error) {
      toast.error(t('toast.ssoStartFailed'))
      throw error
    }
  }, [t])

  const logout = useCallback(async () => {
    const authKind = localStorage.getItem('auth_kind')
    const idTokenHint = localStorage.getItem('kc_id_token')

    // Build the KC end-session URL WHILE cookies still exist. Doing this after
    // POST /logout races in-flight /me → 401 → auth:cleared → /login toast.
    let federatedUrl = null
    if (authKind === 'keycloak') {
      try {
        const keycloakClient = (await import('../services/keycloakClient')).default
        await keycloakClient.init()
        federatedUrl = await keycloakClient.logoutUrl(idTokenHint)
        sessionStorage.setItem('kc_force_login', '1')
      } catch (e) {
        console.warn('Federated logout URL failed, falling back to local', e)
      }
    }

    try { await authService.logout() } catch {}

    localStorage.removeItem('auth_present')
    localStorage.removeItem('auth_kind')
    localStorage.removeItem('kc_id_token')
    clearScopingState()
    queryClient.clear()

    if (federatedUrl) {
      window.location.assign(federatedUrl)
      return
    }
    setHasToken(false)
    toast.success(t('toast.loggedOut'))
  }, [queryClient, t])

  const updateUser = useCallback((updates) => {
    queryClient.setQueryData(AUTH_ME_KEY, (prev) =>
      prev ? { ...prev, ...updates } : prev
    )
  }, [queryClient])

  const value = useMemo(() => ({
    user: user ?? null,
    isLoading,
    isAuthenticated: !!user,
    login,
    loginKeycloak,
    logout,
    updateUser,
  }), [user, isLoading, login, loginKeycloak, logout, updateUser])

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
