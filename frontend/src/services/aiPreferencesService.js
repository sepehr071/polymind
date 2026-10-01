import api from './api'

export const aiPreferencesService = {
  async get() {
    const response = await api.get('/users/ai-preferences')
    return response.data
  },

  async update(preferences) {
    const response = await api.put('/users/ai-preferences', preferences)
    return response.data
  },
}
