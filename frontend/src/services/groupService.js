import api from './api'

/**
 * Groups API client.
 *
 * Backend mounts these routes under `/api/workspaces/<wid>/groups/...`. The
 * list path is the named subpath `/groups/list` (avoids the trailing-slash
 * JWT bug noted in CLAUDE.md).
 */
export const groupService = {
  list: (wid) =>
    api.get(`/workspaces/${wid}/groups/list`).then((r) => r.data?.groups ?? []),
  get: (wid, gid) =>
    api.get(`/workspaces/${wid}/groups/${gid}`).then((r) => r.data),
  create: (wid, payload) =>
    api.post(`/workspaces/${wid}/groups`, payload).then((r) => r.data),
  update: (wid, gid, payload) =>
    api.put(`/workspaces/${wid}/groups/${gid}`, payload).then((r) => r.data),
  delete: (wid, gid) =>
    api.delete(`/workspaces/${wid}/groups/${gid}`).then((r) => r.data),
  addMember: (wid, gid, userId) =>
    api
      .post(`/workspaces/${wid}/groups/${gid}/members`, { user_id: userId })
      .then((r) => r.data),
  removeMember: (wid, gid, uid) =>
    api
      .delete(`/workspaces/${wid}/groups/${gid}/members/${uid}`)
      .then((r) => r.data),
}

export default groupService
