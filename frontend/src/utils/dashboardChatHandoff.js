import { QUICK_MODEL_IDS } from '../constants/models.js'

/** Home composer → new /chat. Read once, then cleared. */
export const DASHBOARD_CHAT_CONFIG_KEY = 'dashboard_chat_config'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Accept a quick-model id or a persona UUID. Anything else is dropped. */
export function parseDashboardChatConfig(picked) {
  if (!picked || typeof picked !== 'string') return null
  if (picked.startsWith('quick:')) {
    return QUICK_MODEL_IDS.includes(picked.slice('quick:'.length)) ? picked : null
  }
  return UUID_RE.test(picked) ? picked : null
}

export function stashDashboardChatConfig(configId) {
  const safe = parseDashboardChatConfig(configId)
  if (!safe) return
  try {
    sessionStorage.setItem(DASHBOARD_CHAT_CONFIG_KEY, safe)
  } catch {
    /* private mode */
  }
}

/** Read and clear. Null when missing or not a known quick/persona id. */
export function takeDashboardChatConfig() {
  try {
    const picked = sessionStorage.getItem(DASHBOARD_CHAT_CONFIG_KEY) || ''
    if (picked) sessionStorage.removeItem(DASHBOARD_CHAT_CONFIG_KEY)
    return parseDashboardChatConfig(picked)
  } catch {
    return null
  }
}
