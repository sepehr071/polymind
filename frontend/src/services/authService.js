import api from './api'

export const authService = {
  async login(email, password) {
    const response = await api.post('/auth/login', {
      email,
      password,
    })
    return response.data
  },

  async refresh() {
    // The refresh token lives in an httpOnly cookie sent automatically with
    // credentials; the backend rotates it and re-sets the cookies. Nothing to
    // read from or write to JS storage.
    const response = await api.post('/auth/refresh', {}, {
      withCredentials: true,
    })
    return response.data
  },

  async logout() {
    // Backend clears the auth cookies; credentials must be sent so it can
    // identify (and revoke) the session.
    await api.post('/auth/logout', {}, { withCredentials: true })
  },

  async getMe() {
    const response = await api.get('/auth/me')
    return response.data
  },

  async changePassword(currentPassword, newPassword) {
    const response = await api.put('/auth/password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    return response.data
  },

  // POST /api/auth/keycloak/sync — exchanges a verified KC access token for a
  // hydrated user payload (same shape as /auth/login: {access_token,
  // refresh_token, token_type, expires_in, features, user}). Backend echoes
  // the access_token; we still send the refresh_token in the body so it
  // appears in the response for symmetry with the operator login flow.
  async syncKeycloak(accessToken, refreshToken, idToken) {
    const response = await api.post('/auth/keycloak/sync', {
      access_token: accessToken,
      refresh_token: refreshToken,
      id_token: idToken,
    })
    return response.data
  },
}
