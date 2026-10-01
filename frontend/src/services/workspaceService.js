import api from './api'

export const workspaceService = {
  list: () => api.get('/workspaces/list').then(r => r.data),
  get: (wid) => api.get(`/workspaces/${wid}`).then(r => r.data),
  create: (data) => api.post('/workspaces/create', data).then(r => r.data),
  update: (wid, data) => api.patch(`/workspaces/${wid}`, data).then(r => r.data),
  delete: (wid) => api.delete(`/workspaces/${wid}`).then(r => r.data),
  invite: (wid, payload) => api.post(`/workspaces/${wid}/invites`, payload).then(r => r.data),
  listInvites: (wid) => api.get(`/workspaces/${wid}/invites`).then(r => r.data),
  revokeInvite: (wid, token) => api.delete(`/workspaces/${wid}/invites/${token}`).then(r => r.data),
  acceptInvite: (token) => api.post('/workspaces/accept-invite', { token }).then(r => r.data),
  members: (wid) => api.get(`/workspaces/${wid}/members`).then(r => r.data),
  invitableUsers: (wid, q) =>
    api.get(`/workspaces/${wid}/invitable-users`, { params: { q } }).then(r => r.data),
  updateMember: (wid, uid, role) => api.patch(`/workspaces/${wid}/members/${uid}`, { role }).then(r => r.data),
  // Direct-add an existing user as a workspace member (viewer|editor) — no
  // invite/accept handshake. Backend: POST /workspaces/{wid}/members.
  addMember: (wid, userId, role) =>
    api.post(`/workspaces/${wid}/members`, { user_id: userId, role }).then(r => r.data),
  removeMember: (wid, uid) => api.delete(`/workspaces/${wid}/members/${uid}`).then(r => r.data),
  getOverview: (wid) => api.get(`/workspaces/${wid}/overview`).then(r => r.data),
  // Audit log — workspace-scoped feed.
  getAudit: (wid, params = {}) =>
    api.get(`/workspaces/${wid}/audit`, { params }).then(r => r.data),
  // Billing — see billingService.js for the dedicated client. These are thin
  // pass-throughs so the workspace surface can call them without a second import.
  getBillingUsage: (wid, params = {}) =>
    api.get(`/workspaces/${wid}/billing/usage`, { params }).then(r => r.data),
  addCredits: (wid, amountUsd, note = '', type = 'top_up') =>
    api
      .post(`/workspaces/${wid}/billing/credits`, {
        amount_usd: amountUsd,
        note,
        type,
      })
      .then(r => r.data),
  getLedger: (wid, { limit = 100, skip = 0 } = {}) =>
    api
      .get(`/workspaces/${wid}/billing/ledger`, { params: { limit, skip } })
      .then(r => r.data),
  resendInvite: (wid, token) =>
    api.post(`/workspaces/${wid}/invites/${token}/resend`).then(r => r.data),
  transferOwnership: (wid, newOwnerUserId) =>
    api.post(`/workspaces/${wid}/transfer-ownership`, { new_owner_user_id: newOwnerUserId }).then(r => r.data),
  // Persist the active workspace server-side. DLP + spend gates resolve the
  // governing workspace from users.active_workspace_id; the switcher used to
  // write only localStorage, so a stale column scanned turns under the wrong
  // workspace's DLP policy (modal appeared even when the visible workspace had
  // DLP off). Best-effort — the UI switches optimistically regardless.
  setActive: (wid) => api.put('/users/active-workspace', { workspace_id: wid }).then(r => r.data),
}

export default workspaceService
