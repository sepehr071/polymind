import api from './api'
import i18n from '@/i18n'

const uiLang = () => (i18n.language || 'en').slice(0, 2).toLowerCase()

export const dlpService = {
  async getPolicy(wid) {
    const r = await api.get(`/workspaces/${wid}/dlp/policy`)
    return r.data
  },

  async updatePolicy(wid, payload) {
    const r = await api.put(`/workspaces/${wid}/dlp/policy`, payload)
    return r.data
  },

  async getStats(wid, days = 30) {
    const r = await api.get(`/workspaces/${wid}/dlp/stats`, { params: { days } })
    return r.data
  },

  async listEvents(wid, params = {}) {
    const r = await api.get(`/workspaces/${wid}/dlp/events`, { params })
    return r.data
  },

  // Returns the full response body:
  //   { result: {matches, highest_action}, redacted_preview: string|null, redactable: boolean }
  // Optional `attachments` (composer chips with upload_id) are forwarded so the
  // pre-flight scan covers file text the same way the chat gate does — required
  // for file-only secrets and a confirm_token HMAC that matches the gate.
  async scan(text, workspace_id, source = 'chat', project_id = null, attachments = null) {
    const body = { text: text ?? '', workspace_id, source, project_id, lang: uiLang() }
    if (Array.isArray(attachments) && attachments.length) {
      body.attachments = attachments
        .map((a) => {
          const uploadId = a?.upload_id || a?.id
          return uploadId ? { upload_id: uploadId } : null
        })
        .filter(Boolean)
    }
    const r = await api.post('/dlp/scan', body)
    return r.data
  },

  async testClassifier(text, workspace_id) {
    const r = await api.post('/dlp/test', { text, workspace_id, lang: uiLang() })
    return r.data
  },

  /** Rewrite a manager's smart-scan guidance via OpenRouter (owner-only). */
  async enhanceGuidance(wid, prompt) {
    const r = await api.post(`/workspaces/${wid}/dlp/enhance-guidance`, {
      prompt,
      lang: uiLang(),
    })
    return r.data
  },
}

export default dlpService
