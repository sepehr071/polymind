import api from './api'

export const promptTemplateService = {
  /**
   * Get all prompt templates, optionally filtered by category
   * @param {string} category - Optional category filter
   * @returns {Promise} Promise resolving to templates data
   */
  getTemplates: async (category = null) => {
    const params = category ? { category } : {}
    const response = await api.get('/prompt-templates/list', { params })
    return response.data
  },

  /**
   * Get list of all template categories with counts
   * @returns {Promise} Promise resolving to categories data
   */
  getCategories: async () => {
    const response = await api.get('/prompt-templates/categories')
    return response.data
  },

  /**
   * Record usage of a template
   * @param {string} templateId - Template ID
   * @returns {Promise} Promise resolving to success response
   */
  useTemplate: async (templateId) => {
    const response = await api.post(`/prompt-templates/${templateId}/use`)
    return response.data
  },

  /**
   * Create a new template (admin only)
   * @param {Object} templateData - Template data
   * @returns {Promise} Promise resolving to created template
   */
  createTemplate: async (templateData) => {
    const response = await api.post('/prompt-templates/create', templateData)
    return response.data
  },

  /**
   * Update a template (admin only)
   * @param {string} templateId - Template ID
   * @param {Object} updates - Template updates
   * @returns {Promise} Promise resolving to success response
   */
  updateTemplate: async (templateId, updates) => {
    const response = await api.put(`/prompt-templates/${templateId}`, updates)
    return response.data
  },

  /**
   * Delete a template (admin only)
   * @param {string} templateId - Template ID
   * @returns {Promise} Promise resolving to success response
   */
  deleteTemplate: async (templateId) => {
    const response = await api.delete(`/prompt-templates/${templateId}`)
    return response.data
  },
}
