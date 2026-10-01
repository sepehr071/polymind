import * as oauth from 'oauth4webapi'
import { API_BASE_URL } from './apiBase'

// Keycloak public client (PKCE, no secret) wrapper around oauth4webapi.
//
// Strategy:
//  - init() resolves config from Vite env vars first, then falls back to
//    GET /api/auth/keycloak/config (backend echoes the same shape).
//  - Issuer metadata discovery is cached for the lifetime of the page so
//    we only round-trip once per session.
//  - PKCE artefacts (verifier/state/nonce) live in sessionStorage so the
//    redirect-back flow can pick them up. They are cleaned up on success
//    OR failure in handleCallback().

const SS_VERIFIER = 'kc_code_verifier'
const SS_STATE = 'kc_state'
const SS_NONCE = 'kc_nonce'

const REDIRECT_PATH = '/login/callback'
const POST_LOGOUT_PATH = '/login'
const SS_FORCE_LOGIN = 'kc_force_login'

const noScheme = (s) => typeof s === 'string' && s.length > 0

let config = null // { url, realm, client_id, redirect_uri, ... } | null
let configLoaded = false
let discoveryPromise = null
let asPromise = null // AuthorizationServer cached

// Why config ended up null:
//   'network' → the backend config endpoint was unreachable (fetch threw,
//               timed out, or returned a non-OK status). This is a transient
//               failure the UI can retry.
//   null      → the endpoint was reachable but SSO is genuinely not configured
//               (env vars absent AND the backend returned an empty/absent shape).
let lastConfigError = null

const CONFIG_FETCH_TIMEOUT_MS = 8000

function originUris() {
  const origin = window.location.origin
  return {
    redirect_uri: `${origin}${REDIRECT_PATH}`,
    post_logout_redirect_uri: `${origin}${POST_LOGOUT_PATH}`,
  }
}

function assembleConfig({ url, realm, client_id }, backend) {
  const fb = originUris()
  const trimmed = String(url).replace(/\/+$/, '')
  return {
    url: trimmed,
    realm,
    client_id,
    redirect_uri: (backend?.redirect_uri && noScheme(backend.redirect_uri))
      ? backend.redirect_uri
      : fb.redirect_uri,
    post_logout_redirect_uri: (backend?.post_logout_redirect_uri && noScheme(backend.post_logout_redirect_uri))
      ? backend.post_logout_redirect_uri
      : fb.post_logout_redirect_uri,
    end_session_endpoint: backend?.end_session_endpoint || '',
    account_console_url: backend?.account_console_url
      || `${trimmed}/realms/${realm}/account`,
  }
}

async function fetchBackendConfig() {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), CONFIG_FETCH_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE_URL}/auth/keycloak/config`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!res.ok) return { error: 'network', data: null }
    const data = await res.json().catch(() => ({}))
    return { error: null, data }
  } catch {
    return { error: 'network', data: null }
  } finally {
    clearTimeout(timer)
  }
}

async function loadConfig() {
  if (configLoaded) return config
  configLoaded = true
  lastConfigError = null

  const envUrl = import.meta.env?.VITE_KEYCLOAK_URL
  const envRealm = import.meta.env?.VITE_KEYCLOAK_REALM
  const envClient = import.meta.env?.VITE_KEYCLOAK_CLIENT_ID
  const envHas = noScheme(envUrl) && noScheme(envRealm) && noScheme(envClient)

  const { error, data } = await fetchBackendConfig()

  if (envHas) {
    lastConfigError = null
    config = assembleConfig(
      { url: envUrl, realm: envRealm, client_id: envClient },
      data,
    )
    return config
  }

  if (error) {
    lastConfigError = 'network'
    config = null
    return null
  }

  const url = data?.url
  const realm = data?.realm
  const client_id = data?.client_id
  if (noScheme(url) && noScheme(realm) && noScheme(client_id)) {
    lastConfigError = null
    config = assembleConfig({ url, realm, client_id }, data)
    return config
  }
  lastConfigError = null
  config = null
  return null
}

function issuerUrl() {
  if (!config) throw new Error('Keycloak is not configured')
  return new URL(`${config.url}/realms/${config.realm}`)
}

function getClient() {
  if (!config) throw new Error('Keycloak is not configured')
  return {
    client_id: config.client_id,
    token_endpoint_auth_method: 'none', // public client
  }
}

async function discover() {
  if (asPromise) return asPromise
  asPromise = (async () => {
    const issuer = issuerUrl()
    const res = await oauth.discoveryRequest(issuer, { algorithm: 'oidc' })
    const as = await oauth.processDiscoveryResponse(issuer, res)
    return as
  })()
  return asPromise
}

function redirectUri() {
  return (config?.redirect_uri && noScheme(config.redirect_uri))
    ? config.redirect_uri
    : `${window.location.origin}${REDIRECT_PATH}`
}

function normalizeTokens(tokenSet) {
  return {
    access_token: tokenSet.access_token,
    refresh_token: tokenSet.refresh_token,
    id_token: tokenSet.id_token,
    expires_in: tokenSet.expires_in,
  }
}

const keycloakClient = {
  async init() {
    if (!configLoaded) {
      await loadConfig()
    }
    if (config && !discoveryPromise) {
      // Kick off (but don't await) discovery so first redirect is faster.
      discoveryPromise = discover().catch(() => null)
    }
  },

  isEnabled() {
    return !!(config && config.url && config.realm && config.client_id)
  },

  // 'network' = transient fetch failure (retryable), null = genuinely
  // not configured (or config loaded fine). Lets the UI distinguish a
  // "couldn't reach the sign-in service" error from "SSO is disabled".
  getConfigError() {
    return lastConfigError
  },

  // Re-attempt config resolution after a transient failure. Resets the cached
  // load state so init() re-runs loadConfig() from scratch.
  async retryConfig() {
    configLoaded = false
    config = null
    lastConfigError = null
    discoveryPromise = null
    asPromise = null
    await this.init()
  },

  async loginRedirect() {
    await this.init()
    if (!this.isEnabled()) {
      throw new Error('Keycloak SSO is not configured')
    }

    const as = await discover()
    const client = getClient()

    const code_verifier = oauth.generateRandomCodeVerifier()
    const code_challenge = await oauth.calculatePKCECodeChallenge(code_verifier)
    const state = oauth.generateRandomState()
    const nonce = oauth.generateRandomNonce()

    sessionStorage.setItem(SS_VERIFIER, code_verifier)
    sessionStorage.setItem(SS_STATE, state)
    sessionStorage.setItem(SS_NONCE, nonce)

    const authorizationUrl = new URL(as.authorization_endpoint)
    authorizationUrl.searchParams.set('client_id', client.client_id)
    authorizationUrl.searchParams.set('redirect_uri', redirectUri())
    authorizationUrl.searchParams.set('response_type', 'code')
    authorizationUrl.searchParams.set('scope', 'openid email profile')
    authorizationUrl.searchParams.set('code_challenge', code_challenge)
    authorizationUrl.searchParams.set('code_challenge_method', 'S256')
    authorizationUrl.searchParams.set('state', state)
    authorizationUrl.searchParams.set('nonce', nonce)
    if (sessionStorage.getItem(SS_FORCE_LOGIN) === '1') {
      authorizationUrl.searchParams.set('prompt', 'login')
      sessionStorage.removeItem(SS_FORCE_LOGIN)
    }

    window.location.assign(authorizationUrl.toString())

    // Return a never-resolving promise so callers don't proceed after redirect.
    return new Promise(() => {})
  },

  async handleCallback() {
    await this.init()
    if (!this.isEnabled()) {
      throw new Error('Keycloak SSO is not configured')
    }

    const as = await discover()
    const client = getClient()

    const code_verifier = sessionStorage.getItem(SS_VERIFIER)
    const expected_state = sessionStorage.getItem(SS_STATE)
    const expected_nonce = sessionStorage.getItem(SS_NONCE)

    try {
      if (!code_verifier || !expected_state) {
        throw new Error('Missing PKCE/state in session — start sign-in again')
      }

      const currentUrl = new URL(window.location.href)

      // validateAuthResponse throws on state mismatch / OAuth error params.
      const params = oauth.validateAuthResponse(as, client, currentUrl, expected_state)

      const tokenResponse = await oauth.authorizationCodeGrantRequest(
        as,
        client,
        oauth.None(),
        params,
        redirectUri(),
        code_verifier,
      )

      const result = await oauth.processAuthorizationCodeResponse(as, client, tokenResponse, {
        expectedNonce: expected_nonce || undefined,
        requireIdToken: true,
      })

      return normalizeTokens(result)
    } finally {
      sessionStorage.removeItem(SS_VERIFIER)
      sessionStorage.removeItem(SS_STATE)
      sessionStorage.removeItem(SS_NONCE)
    }
  },

  async refresh(refreshToken) {
    await this.init()
    if (!this.isEnabled()) {
      throw new Error('Keycloak SSO is not configured')
    }
    if (!refreshToken) {
      throw new Error('No refresh token')
    }

    const as = await discover()
    const client = getClient()

    const tokenResponse = await oauth.refreshTokenGrantRequest(
      as,
      client,
      oauth.None(),
      refreshToken,
    )

    const result = await oauth.processRefreshTokenResponse(as, client, tokenResponse)
    const tokens = normalizeTokens(result)

    // NOTE: client-side KC refresh is retired under the httpOnly-cookie auth
    // model — renewals run through the cookie-driven POST /auth/refresh. We no
    // longer persist the KC refresh token to localStorage (a sensitive token in
    // JS reach is exactly what the cookie migration removes).
    return tokens
  },

  async logoutUrl(idTokenHint) {
    if (!config) {
      throw new Error('Keycloak is not configured')
    }
    let endpoint = config.end_session_endpoint
    try {
      const as = await discover()
      if (as?.end_session_endpoint) endpoint = as.end_session_endpoint
    } catch {
      // constructed /config endpoint is enough
    }
    if (!endpoint) {
      endpoint = `${config.url}/realms/${config.realm}/protocol/openid-connect/logout`
    }
    const post = config.post_logout_redirect_uri
      || `${window.location.origin}${POST_LOGOUT_PATH}`
    const url = new URL(endpoint)
    url.searchParams.set('post_logout_redirect_uri', post)
    url.searchParams.set('client_id', config.client_id)
    if (idTokenHint) {
      url.searchParams.set('id_token_hint', idTokenHint)
    }
    return url.toString()
  },

  accountConsoleUrl() {
    return config?.account_console_url || ''
  },
}

export default keycloakClient
