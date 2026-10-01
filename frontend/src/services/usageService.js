import api from './api'

export const usageService = {
  getMyUsage: ({ from, to, group_by = 'feature', workspace_id } = {}) => {
    const params = new URLSearchParams()
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    params.set('group_by', group_by)
    if (workspace_id) params.set('workspace_id', workspace_id)
    return api.get(`/usage/me?${params}`).then(r => r.data)
  },

  getAdminUsage: ({ from, to, group_by = 'feature', user_id } = {}) => {
    const params = new URLSearchParams()
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    params.set('group_by', group_by)
    if (user_id) params.set('user_id', user_id)
    return api.get(`/admin/usage?${params}`).then(r => r.data)
  },
}
