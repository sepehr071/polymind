import { lazy } from 'react'

const RETRY_KEY = 'lazy-retry-attempted'

function isChunkLoadError(err) {
  if (!err) return false
  const msg = String(err.message || err)
  return (
    err.name === 'ChunkLoadError' ||
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Loading chunk') ||
    msg.includes('Importing a module script failed')
  )
}

function clearRetryFlag() {
  try { sessionStorage.removeItem(RETRY_KEY) } catch { /* ignore */ }
}

export default function lazyWithRetry(importer) {
  return lazy(() =>
    importer()
      .then((mod) => {
        // Successful load means we recovered (or never needed to retry).
        // Always clear the flag so a *later* unrelated ChunkLoadError in the
        // same tab can still trigger a one-shot reload.
        clearRetryFlag()
        return mod
      })
      .catch((err) => {
        if (!isChunkLoadError(err)) throw err
        // Timestamp guard (not a boolean) so a chunk that stays 404 after a
        // redeploy can't loop reload→spinner forever: we reload at most once
        // per 10s window. A repeat failure inside that window throws so the
        // nearest ErrorBoundary surfaces a retry Card instead of reloading.
        const last = Number(sessionStorage.getItem(RETRY_KEY)) || 0
        if (Date.now() - last < 10000) {
          clearRetryFlag()
          throw err
        }
        sessionStorage.setItem(RETRY_KEY, String(Date.now()))
        window.location.reload()
        return new Promise(() => {})
      })
  )
}
