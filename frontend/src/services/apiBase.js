// Frontend API base. Defaults to '/api' so vite proxy + same-origin prod
// (Traefik serving FE+BE on one domain) work without env vars. Override via
// `VITE_API_BASE_URL` when the SPA is served from a different origin than
// the Flask backend (e.g. CDN frontend + api.<host>). NO trailing slash.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
