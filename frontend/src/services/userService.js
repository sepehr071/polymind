import api from './api'

export const userService = {
  async getProfile() {
    const response = await api.get('/users/profile')
    return response.data
  },

  async updateProfile(data) {
    const response = await api.put('/users/profile', data)
    return response.data
  },

  async getStats() {
    const response = await api.get('/users/stats')
    return response.data
  },

  async getCosts(days = 30) {
    const response = await api.get('/users/costs', { params: { days } })
    return response.data
  },

  async getSettings() {
    const response = await api.get('/users/settings')
    return response.data
  },

  async updateSettings(data) {
    const response = await api.put('/users/settings', data)
    return response.data
  },

  // Idempotent: stamps settings.onboarding_seen_at server-side so the
  // onboarding wizard auto-appears exactly once per account (any browser).
  async markOnboardingSeen() {
    const response = await api.post('/users/onboarding-seen')
    return response.data
  },
}
