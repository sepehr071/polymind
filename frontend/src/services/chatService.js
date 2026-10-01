import api from './api'

export const chatService = {
  // Conversations
  async getConversations(params = {}) {
    const response = await api.get('/conversations', { params })
    return response.data
  },

  async getConversation(conversationId) {
    const response = await api.get(`/conversations/${conversationId}`)
    return response.data
  },

  async createConversation(configId, title = 'New conversation', folderId = null) {
    const response = await api.post('/conversations', {
      config_id: configId,
      title,
      folder_id: folderId,
    })
    return response.data
  },

  async updateConversation(conversationId, data) {
    const response = await api.put(`/conversations/${conversationId}`, data)
    return response.data
  },

  async deleteConversation(conversationId) {
    const response = await api.delete(`/conversations/${conversationId}`)
    return response.data
  },

  async archiveConversation(conversationId) {
    const response = await api.post(`/conversations/${conversationId}/archive`)
    return response.data
  },

  async exportConversation(conversationId, format = 'markdown', includeMetadata = true) {
    const response = await api.get(`/conversations/${conversationId}/export`, {
      params: { format, metadata: includeMetadata },
      responseType: 'blob',
      timeout: 180000,
    })
    return response
  },

  async searchConversations(query) {
    const response = await api.get('/conversations/search', { params: { q: query } })
    return response.data
  },

  async searchMessages(query) {
    const response = await api.get('/conversations/search/messages', { params: { q: query } })
    return response.data
  },

  // Messages (non-streaming)
  async sendMessage(conversationId, configId, message, attachments = []) {
    const response = await api.post('/chat/send', {
      conversation_id: conversationId,
      config_id: configId,
      message,
      attachments,
    })
    return response.data
  },

  async getMessages(conversationId, params = {}) {
    const response = await api.get(`/chat/${conversationId}/messages`, { params })
    return response.data
  },

  async deleteMessage(messageId) {
    const response = await api.delete(`/chat/messages/${messageId}`)
    return response.data
  },

  async regenerateMessage(messageId, configId = null, extra = {}) {
    // config_id is optional — only sent when a specific model/persona is chosen
    // (supports `quick:<model>` ids). Omitting it regenerates with the message's
    // original config. `extra` carries DLP confirm/redact fields when resubmitting.
    const body = { ...(configId ? { config_id: configId } : {}), ...extra }
    const response = await api.post(`/chat/regenerate/${messageId}`, body)
    return response.data
  },

  // Thumbs up/down on an assistant message. rating ∈ 'up' | 'down' | null
  // (null clears). Stored at message.metadata.feedback server-side.
  async submitMessageFeedback(messageId, rating) {
    const response = await api.post(`/chat/messages/${messageId}/feedback`, { rating })
    return response.data
  },

  async editMessage(messageId, content, regenerate = true, extra = {}) {
    const response = await api.put(`/chat/messages/${messageId}`, {
      content,
      regenerate,
      ...extra,
    })
    return response.data
  },

  // Branching
  async createBranch(conversationId, messageId, name) {
    const response = await api.post(`/conversations/${conversationId}/branch/${messageId}`, { name })
    return response.data
  },

  async getBranches(conversationId) {
    const response = await api.get(`/conversations/${conversationId}/branches`)
    return response.data
  },

  async switchBranch(conversationId, branchId) {
    const response = await api.put(`/conversations/${conversationId}/branch/${branchId}`)
    return response.data
  },

  async deleteBranch(conversationId, branchId) {
    const response = await api.delete(`/conversations/${conversationId}/branch/${branchId}`)
    return response.data
  },

  async renameBranch(conversationId, branchId, newName) {
    const response = await api.put(`/conversations/${conversationId}/branch/${branchId}/rename`, { name: newName })
    return response.data
  },

  async branchToNewConversation(conversationId, messageId) {
    const response = await api.post(`/conversations/${conversationId}/branch-to-new/${messageId}`)
    return response.data
  },

  // Upload image specifically (for vision models)
  async uploadImage(file) {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/uploads/image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  },

  // Upload any supported file to disk-backed storage (PDF / office / text /
  // large images). Backend extracts text server-side and returns
  // { id, url, mime/size..., extraction_status, extracted_chars, text_preview }.
  async uploadFile(file) {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/uploads/file', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    // Route returns { upload: { id, url, extraction_status, ... } } — unwrap it.
    return response.data?.upload || response.data
  },

  // Convert file to base64 for inline attachments (avoids server storage)
  async fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  },
}

export const configService = {
  async getConfigs(params = {}) {
    const response = await api.get('/configs', { params })
    return response.data
  },

  async getConfig(configId) {
    const response = await api.get(`/configs/${configId}`)
    return response.data
  },

  async createConfig(data) {
    const response = await api.post('/configs', data)
    return response.data
  },

  async updateConfig(configId, data) {
    const response = await api.put(`/configs/${configId}`, data)
    return response.data
  },

  async deleteConfig(configId) {
    const response = await api.delete(`/configs/${configId}`)
    return response.data
  },

  async publishConfig(configId) {
    const response = await api.post(`/configs/${configId}/publish`)
    return response.data
  },

  async unpublishConfig(configId) {
    const response = await api.post(`/configs/${configId}/unpublish`)
    return response.data
  },

  async duplicateConfig(configId, name = null) {
    const response = await api.post(`/configs/${configId}/duplicate`, { name })
    return response.data
  },

  async enhancePrompt(prompt, dlp = {}, mode = 'assistant') {
    const response = await api.post('/configs/enhance-prompt', { prompt, mode, ...dlp })
    return response.data
  },
}

export const modelService = {
  async getModels() {
    const response = await api.get('/models')
    return response.data
  },

  async getModel(modelId) {
    const response = await api.get(`/models/${modelId}`)
    return response.data
  },

  async getModelCategories() {
    const response = await api.get('/models/categories')
    return response.data
  },
}
