import api from './api'

export const debateService = {
  /**
   * List all debate sessions for current user
   */
  listSessions: async () => {
    const response = await api.get('/debate/sessions')
    return response.data
  },

  /**
   * Create a new debate session
   * @param {Object} data - Session configuration
   * @param {string} data.topic - Debate topic
   * @param {Array<string>} data.config_ids - Array of debater config IDs (2-5)
   * @param {string} data.judge_config_id - Judge config ID
   * @param {number} data.rounds - Number of rounds (1-5)
   */
  createSession: async (data) => {
    const response = await api.post('/debate/sessions', data)
    return response.data
  },

  /**
   * Get a specific debate session
   * @param {string} id - Session ID
   */
  getSession: async (id) => {
    const response = await api.get(`/debate/sessions/${id}`)
    return response.data
  },

  /**
   * Delete a debate session
   * @param {string} id - Session ID
   */
  deleteSession: async (id) => {
    const response = await api.delete(`/debate/sessions/${id}`)
    return response.data
  },
}

export default debateService
