import api from './api'

export const arenaService = {
  createSession: async (configIds, title = 'Arena Session') => {
    const response = await api.post('/arena/sessions', { config_ids: configIds, title })
    return response.data
  },

  getSessions: async (params = {}) => {
    const response = await api.get('/arena/sessions', { params })
    return response.data
  },

  getSession: async (sessionId) => {
    const response = await api.get(`/arena/sessions/${sessionId}`)
    return response.data
  },

  deleteSession: async (sessionId) => {
    const response = await api.delete(`/arena/sessions/${sessionId}`)
    return response.data
  },

  updateSession: async (sessionId, data) => {
    const response = await api.patch(`/arena/sessions/${sessionId}`, data)
    return response.data
  },
}
