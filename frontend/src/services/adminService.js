import api from './api'

export const adminService = {
  async getUsers(params = {}) {
    const response = await api.get('/admin/users', { params })
    return response.data
  },

  async getUser(userId) {
    const response = await api.get('/admin/users/' + userId)
    return response.data
  },

  async banUser(userId, reason) {
    const response = await api.put('/admin/users/' + userId + '/ban', { reason })
    return response.data
  },

  async unbanUser(userId) {
    const response = await api.put('/admin/users/' + userId + '/unban')
    return response.data
  },

  async setUserLimits(userId, tokensLimit) {
    const response = await api.put('/admin/users/' + userId + '/limits', { tokens_limit: tokensLimit })
    return response.data
  },

  async getUserHistory(userId, includeMessages = false) {
    const response = await api.get('/admin/users/' + userId + '/history', { params: { include_messages: includeMessages } })
    return response.data
  },

  async getUserHistoryMessages(userId, conversationId) {
    const response = await api.get('/admin/users/' + userId + '/history/' + conversationId + '/messages')
    return response.data
  },

  async getTemplates() {
    const response = await api.get('/admin/templates')
    return response.data
  },

  async createTemplate(data) {
    const response = await api.post('/admin/templates', data)
    return response.data
  },

  async updateTemplate(templateId, data) {
    const response = await api.put('/admin/templates/' + templateId, data)
    return response.data
  },

  async deleteTemplate(templateId) {
    const response = await api.delete('/admin/templates/' + templateId)
    return response.data
  },

  async getAnalytics(days = 30) {
    const response = await api.get('/admin/analytics', { params: { days } })
    return response.data
  },

  // Unified analytics envelope (P1). params: { scope, id, granularity, from, to, breakdown }.
  // scope ∈ {holding, company, team, user}; children kind follows scope.
  async getAnalyticsUsage(params = {}) {
    const response = await api.get('/admin/analytics/usage', { params })
    return response.data
  },

  async getTimeseriesAnalytics(days = 30, granularity = 'day') {
    const response = await api.get('/admin/analytics/timeseries', { params: { days, granularity } })
    return response.data
  },

  async getAuditLogs(skip = 0, limit = 50, action = null, category = null) {
    const params = { skip, limit }
    if (action) params.action = action
    if (category) params.category = category
    const response = await api.get('/admin/audit-logs', { params })
    return response.data
  },

  async listCompanies(days = 30) {
    const response = await api.get('/admin/companies', { params: { days } })
    return response.data
  },

  async getCompanyDetail(wid, days = 30) {
    const response = await api.get(`/admin/companies/${wid}`, { params: { days } })
    return response.data
  },

  async listDlpEvents({ days = 30, action, severity, workspaceId, skip = 0, limit = 50 } = {}) {
    const params = { days, skip, limit }
    if (action) params.action = action
    if (severity) params.severity = severity
    if (workspaceId) params.workspace_id = workspaceId
    const response = await api.get('/admin/dlp/events', { params })
    return response.data
  },

  async getDlpSummary(days = 30) {
    const response = await api.get('/admin/dlp/stats', { params: { days } })
    return response.data
  },

  async reviewDlpEvent(eventId, { status, note } = {}) {
    const response = await api.patch('/admin/dlp/events/' + eventId, { status, note })
    return response.data
  },

  // Platform-feature flags (absorbed from the retired platform dashboard).
  async getFeatures() {
    const response = await api.get('/admin/features')
    return response.data
  },

  // Forward the object verbatim as the body: { feature, enabled } for a single
  // toggle OR { features } for a bulk replace. Returns { features, updated_at, updated_by }.
  async updateFeatures(payload) {
    const response = await api.put('/admin/features', payload)
    return response.data
  },

  async getHoldingOverview(days = 30) {
    const response = await api.get('/admin/holding/overview', { params: { days } })
    return response.data
  },

  // CEO profit dashboard — revenue (markup-priced) vs upstream OpenRouter cost,
  // with margin. Mirrors the analytics-usage envelope shape but adds revenue /
  // margin / margin_pct series + totals and `by_company`/`by_model` breakdowns.
  // params: { from, to, granularity, breakdown }. Returns the legacy dict
  // verbatim (NEVER response_model-shaped). `margin_visible` masks margin/cost.
  async getProfit({ from, to, granularity = 'day', breakdown } = {}) {
    const params = { granularity }
    if (from) params.from = from
    if (to) params.to = to
    if (breakdown) params.breakdown = breakdown
    const response = await api.get('/admin/analytics/profit', { params })
    return response.data
  },

  // Pricing knobs (markup % over upstream cost + credit conversion rate).
  // Returns { markup_pct, credits_per_usd } (plus optional updated_at/updated_by meta).
  async getPricing() {
    const response = await api.get('/admin/billing/config')
    return response.data
  },

  // Persist pricing knobs. Forward the object verbatim as the body
  // ({ markup_pct, credits_per_usd }). 400 on out-of-bounds values.
  async updatePricing(payload) {
    const response = await api.put('/admin/billing/config', payload)
    return response.data
  },

  async getHoldingLedger({ skip = 0, limit = 50 } = {}) {
    const response = await api.get('/admin/holding/ledger', { params: { skip, limit } })
    return response.data
  },

  async addHoldingCredits({ amountUsd, type = 'top_up', note = '' } = {}) {
    const response = await api.post('/admin/holding/credits', {
      amount_usd: amountUsd, type, note,
    })
    return response.data
  },

  async addCompanyCredits(wid, { amountUsd, type = 'top_up', note = '', source } = {}) {
    const body = { amount_usd: amountUsd, type, note }
    if (source !== undefined) body.source = source
    const response = await api.post(`/admin/companies/${wid}/credits`, body)
    return response.data
  },

  // Per-member monthly budget inside an org. amountUsd null clears the budget.
  async setMemberBudget(userId, { workspaceId, amountUsd }) {
    const response = await api.put(`/admin/users/${userId}/budget`, {
      workspace_id: workspaceId,
      amount_usd: amountUsd,
    })
    return response.data
  },

  // Bulk member budget. Partial success: { results, applied, failed }.
  async bulkSetMemberBudget({ workspaceId, userIds, amountUsd }) {
    const response = await api.post('/admin/users/budget/bulk', {
      workspace_id: workspaceId,
      user_ids: userIds,
      amount_usd: amountUsd,
    })
    return response.data
  },
}
