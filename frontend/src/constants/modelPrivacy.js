/**
 * Route → privacy mode for Local AI vs OpenRouter callouts.
 * - local: in-house Ollama (email writer). Hub + page both probe; fallback → cloud.
 * - cloud: OpenRouter / external AI
 * - model: follow live model picker (chat)
 */
export const LOCAL_MODEL_ID = 'polymind/local-ai'

export const ROUTE_PRIVACY = {
  '/chat': 'model',
  '/email-writer': 'local',
  '/agent': 'cloud',
  '/arena': 'cloud',
  '/debate': 'cloud',
  '/image-studio': 'cloud',
  '/data-analyzer': 'cloud',
  '/payroll': 'cloud',
  '/presentations': 'cloud',
  '/ocr': 'cloud',
  '/cv-checker': 'cloud',
  '/research': 'cloud',
  '/contracts': 'cloud',
  '/tenders': 'cloud',
  '/shop': 'cloud',
  '/workflow': 'cloud',
  '/automate-agent': 'cloud',
  '/meetings': 'cloud',
  '/helper': 'cloud',
  '/configs': 'cloud',
}

export function isLocalModelId(modelId) {
  return String(modelId || '') === LOCAL_MODEL_ID
}

/** Longest-prefix match so `/meetings/xyz` → meetings cloud. */
export function privacyForPath(pathname) {
  if (!pathname) return null
  let best = null
  let bestLen = -1
  for (const [route, mode] of Object.entries(ROUTE_PRIVACY)) {
    if (pathname === route || pathname.startsWith(`${route}/`)) {
      if (route.length > bestLen) {
        best = mode
        bestLen = route.length
      }
    }
  }
  return best
}

/**
 * Resolve display mode for a surface.
 * @param {'local'|'cloud'|'model'|null} mode
 * @param {{ modelId?: string|null, localAvailable?: boolean, localStatusKnown?: boolean }} [opts]
 */
export function resolvePrivacyMode(
  mode,
  { modelId = null, localAvailable = false, localStatusKnown = true } = {},
) {
  if (mode === 'model') {
    return isLocalModelId(modelId) ? 'local' : 'cloud'
  }
  if (mode === 'local') {
    // Hide until the Ollama probe returns so hub and page don't disagree mid-load.
    if (!localStatusKnown) return null
    return localAvailable ? 'local' : 'cloud'
  }
  if (mode === 'cloud') return 'cloud'
  return null
}

/**
 * Hub + page share this. `model` is left unresolved (chat chip). `local` is
 * demoted to cloud when Ollama is unconfigured (silent OpenRouter fallback).
 */
export function displayPrivacyForPath(pathname, opts = {}) {
  const mode = privacyForPath(pathname)
  if (mode === 'local') return resolvePrivacyMode('local', opts)
  return mode
}
