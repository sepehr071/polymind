import api from './api'

export const modelCatalogService = {
  fetchCatalog: ({ modality, capability, sort = 'newest', page = 1, pageSize = 200 } = {}) => {
    const params = new URLSearchParams()
    if (modality) params.set('modality', modality)
    if (capability) params.set('capability', capability)
    params.set('sort', sort)
    params.set('page', page)
    params.set('page_size', pageSize)
    return api.get(`/models/catalog?${params}`).then(r => r.data)
  },

  fetchModel: (id) =>
    api.get(`/models/catalog/${encodeURIComponent(id)}`).then(r => r.data),

  fetchRefreshStatus: () =>
    api.get('/models/catalog/refresh-status').then(r => r.data),

  triggerRefresh: () =>
    api.post('/models/catalog/refresh').then(r => r.data),
}
