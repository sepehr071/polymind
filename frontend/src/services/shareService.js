import api from './api'

/**
 * Chat sharing — link snapshots + live team grants.
 *
 * Owner-only management endpoints live under /conversations/{id}/share/*; the
 * read endpoint /share/{token} returns the FROZEN snapshot and is readable by
 * any logged-in user (uses the same authed axios instance).
 */
export const shareService = {
  // Owner view of current shares: { link: { token } | null, teams: [projectId, ...] }
  async listShares(conversationId) {
    const { data } = await api.get(`/conversations/${conversationId}/shares`)
    return data
  },

  // Create (or replace) the frozen-snapshot link share. Returns { token }.
  async createLinkShare(conversationId) {
    const { data } = await api.post(`/conversations/${conversationId}/share/link`)
    return data
  },

  // Revoke the active link share.
  async revokeLinkShare(conversationId) {
    const { data } = await api.delete(`/conversations/${conversationId}/share/link`)
    return data
  },

  // Replace the set of teams this chat is shared into. Returns { teams: [...] }.
  async setTeamShares(conversationId, projectIds) {
    const { data } = await api.put(`/conversations/${conversationId}/share/teams`, {
      project_ids: projectIds,
    })
    return data
  },

  // Public-ish snapshot view (any logged-in user). Returns { snapshot, shared_at }.
  async getSnapshot(token) {
    const { data } = await api.get(`/share/${token}`)
    return data
  },

  // Import the snapshot as the caller's OWN new chat. Returns { conversation_id }.
  async saveSnapshot(token) {
    const { data } = await api.post(`/share/${token}/save`)
    return data
  },
}

export default shareService
