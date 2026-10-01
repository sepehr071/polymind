import api from './api'

export const automateAgentService = {
  listTasks: async ({ limit = 50, skip = 0 } = {}) => {
    const response = await api.get('/automate-agent/tasks', { params: { limit, skip } })
    return response.data
  },

  getTask: async (id) => {
    const response = await api.get(`/automate-agent/tasks/${id}`)
    return response.data
  },

  deleteTask: async (id) => {
    const response = await api.delete(`/automate-agent/tasks/${id}`)
    return response.data
  },

  stopTask: async (id) => {
    const response = await api.post(`/automate-agent/tasks/${id}/stop`)
    return response.data
  },
}

export default automateAgentService
