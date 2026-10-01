import api from './api'

export const imageService = {
  getImageModels: async () => {
    const response = await api.get('/image-gen/models')
    return response.data
  },

  generateImage: async (data) => {
    // Conversational image-edit threads: forward conversation_id (omit to start
    // a new thread), parent_image_id (set when "editing" a prior image), and
    // config_id (when an image assistant drives the thread). Spreading `data`
    // already carries prompt/model/negative_prompt/aspect_ratio/input_images +
    // the DLP fields; these three just pass through when present.
    // Use longer timeout for image generation (150 seconds).
    const response = await api.post('/image-gen/generate', data, {
      timeout: 150000, // 150 seconds
    })
    return response.data
  },

  // --- Conversational image-edit threads --------------------------------
  // A thread groups a series of edits ("make it blue", "now add a hat"); each
  // generated image IS a turn. Lists carry cover thumbs only (no full base64).
  getThreads: async ({ page = 1, limit = 20 } = {}) => {
    const response = await api.get('/image-gen/threads', {
      params: { page, limit },
    })
    return response.data
  },

  // One thread + its ordered turns (oldest → newest). Images are thumbs only;
  // the full base64 is fetched per-id via getImage on demand.
  getThread: async (cid) => {
    const response = await api.get(`/image-gen/threads/${cid}`)
    return response.data
  },

  renameThread: async (cid, title) => {
    const response = await api.patch(`/image-gen/threads/${cid}`, { title })
    return response.data
  },

  deleteThread: async (cid) => {
    const response = await api.delete(`/image-gen/threads/${cid}`)
    return response.data
  },

  getHistory: async (params = {}) => {
    // The grids omit the heavy full-res base64 payload from the list; each row
    // carries a small `thumb` (downscaled WebP data URI, ~5-15KB) the grid
    // renders directly. The full image is fetched by id only on
    // detail-open/download/zoom (see getImage). Un-backfilled rows have
    // `thumb: null` -> the tile falls back to the lazy full-by-id fetch.
    // Callers may override.
    const response = await api.get('/image-gen/history', {
      params: { include_payload: false, ...params },
    })
    return response.data
  },

  // Fetch a single image WITH its full base64 payload (pairs with the
  // payload-less list). Returns the image dict ({ image_data, ... }).
  getImage: async (id) => {
    const response = await api.get(`/image-gen/${id}`)
    return response.data.image
  },

  // Owner-scoped MEDIUM (~1024px WebP) rendition for the hero canvas — sharp
  // without pushing multi-MB full base64 into the DOM. Returns { preview }
  // (a `data:image/webp;base64,...` URI). Cached server- and client-side
  // (renditions are immutable per image; pair with staleTime: Infinity).
  getImagePreview: async (id) => {
    const response = await api.get(`/image-gen/${id}/preview`)
    return response.data
  },

  deleteImage: async (id) => {
    const response = await api.delete(`/image-gen/${id}`)
    return response.data
  },

  toggleFavorite: async (id) => {
    const response = await api.post(`/image-gen/${id}/favorite`)
    return response.data
  },

  bulkDelete: async (imageIds) => {
    const response = await api.post('/image-gen/bulk-delete', { image_ids: imageIds })
    return response.data
  },
}
