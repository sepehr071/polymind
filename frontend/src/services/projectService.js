import api from './api'

export const projectService = {
  list: (workspaceId) => api.get(`/projects/list?workspace_id=${workspaceId}`).then(r => r.data),
  get: (pid) => api.get(`/projects/${pid}`).then(r => r.data),
  create: (data) => api.post('/projects/create', data).then(r => r.data),
  update: (pid, data) => api.patch(`/projects/${pid}`, data).then(r => r.data),
  delete: (pid) => api.delete(`/projects/${pid}`).then(r => r.data),
  listMembers: (pid) => api.get(`/projects/${pid}/members`).then(r => r.data),
  addMember: (pid, payload) => api.post(`/projects/${pid}/members`, payload).then(r => r.data),
  updateMember: (pid, uid, role) => api.patch(`/projects/${pid}/members/${uid}`, { role }).then(r => r.data),
  removeMember: (pid, uid) => api.delete(`/projects/${pid}/members/${uid}`).then(r => r.data),
  setPinned: (pid, pinned) => api.patch(`/projects/${pid}/pin`, { pinned }).then(r => r.data),
  setTags: (pid, tags) => api.patch(`/projects/${pid}/tags`, { tags }).then(r => r.data),

  // Team / per-member budgets (advisory ceilings, 402 enforcement on call sites)
  getBudget: (pid) => api.get(`/projects/${pid}/budget`).then(r => r.data),
  setBudget: (pid, { amount_usd, enabled }) =>
    api.put(`/projects/${pid}/budget`, { amount_usd, enabled }).then(r => r.data),
  setMemberBudget: (pid, uid, { amount_usd, enabled }) =>
    api.put(`/projects/${pid}/members/${uid}/budget`, { amount_usd, enabled }).then(r => r.data),

  // Project access (groups + direct members)
  getAccess: (pid) => api.get(`/projects/${pid}/access`).then(r => r.data),
  setGroupAccess: (pid, group_id, role, expires_at = null) =>
    api
      .post(`/projects/${pid}/access/groups`, { group_id, role, expires_at })
      .then(r => r.data),
  removeGroupAccess: (pid, gid) =>
    api.delete(`/projects/${pid}/access/groups/${gid}`).then(r => r.data),

  // Webhooks (project-scoped integrations).
  // Secret returned only on create + rotate-secret.
  getWebhooks: (pid) =>
    api.get(`/projects/${pid}/webhooks`).then(r => r.data),
  createWebhook: (pid, payload) =>
    api.post(`/projects/${pid}/webhooks`, payload).then(r => r.data),
  updateWebhook: (pid, whid, payload) =>
    api.put(`/projects/${pid}/webhooks/${whid}`, payload).then(r => r.data),
  deleteWebhook: (pid, whid) =>
    api.delete(`/projects/${pid}/webhooks/${whid}`).then(r => r.data),
  rotateWebhookSecret: (pid, whid) =>
    api.post(`/projects/${pid}/webhooks/${whid}/rotate-secret`).then(r => r.data),
}

export default projectService
