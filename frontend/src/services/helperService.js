/**
 * Helper Service - Streams the in-app helper assistant via SSE.
 *
 * Mirrors `services/streamService.js` (chat/arena/debate). Helper events the
 * server emits:
 *   - message_start                  {message_id, ...}
 *   - message_chunk                  {message_id, content}
 *   - message_complete               {message_id, content, deep_links?}
 *   - message_error                  {error, code?}
 *   - dlp_block                      {matches, highest_action}    (HTTP 403)
 *   - dlp_confirm_required is emitted as dlp_block (stale confirm is a block)
 *
 * The DLP variants surface the parsed body via `onEvent` BEFORE returning so
 * the caller can wire its violation modal without a separate code path.
 */

import { API_BASE_URL } from './apiBase'

/**
 * Idle watchdog timeout for the SSE reader loop. Reset on every chunk of
 * received bytes (incl. backend keepalives); on expiry we abort + emit a
 * `message_error` so the UI doesn't spin forever on a stalled upstream.
 */
const STREAM_IDLE_TIMEOUT_MS = 60000

function parseSSE(text) {
  const events = []
  const lines = text.split('\n')

  let currentEvent = null
  let currentData = ''

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7).trim()
    } else if (line.startsWith('data: ')) {
      currentData = line.slice(6)
    } else if (line === '' && currentEvent && currentData) {
      try {
        events.push({
          type: currentEvent,
          data: JSON.parse(currentData),
        })
      } catch (e) {
        console.error('Failed to parse helper SSE data:', currentData, e)
      }
      currentEvent = null
      currentData = ''
    }
  }

  return events
}

/**
 * Stream a helper response.
 *
 * @param {Object} params
 * @param {string} params.message - User message.
 * @param {Object} [params.page_context] - Page-context payload {route, title?, ...}.
 * @param {boolean} [params.dlp_confirmed] - Still forwarded. The UI does not set this to unlock a hit.
 * @param {boolean} [params.dlp_redact] - User opted to redact sensitive spans before sending.
 * @param {(event: {type: string, ...payload: object}) => void} onEvent - Event sink.
 * @param {AbortSignal} [signal] - Optional external abort signal.
 * @returns {Promise<{abort: () => void}>}
 */
export async function streamHelper(
  { message, page_context, dlp_confirmed, dlp_redact, dlp_confirm_token } = {},
  onEvent,
  signal,
) {
  const controller = new AbortController()
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  const body = { message }
  if (page_context !== undefined) body.page_context = page_context
  if (dlp_confirmed) body.dlp_confirmed = true
  if (dlp_redact) body.dlp_redact = true
  if (dlp_confirm_token) body.dlp_confirm_token = dlp_confirm_token

  const emit = (type, payload) => {
    if (typeof onEvent === 'function') {
      onEvent({ type, ...(payload || {}) })
    }
  }

  try {
    const response = await fetch(`${API_BASE_URL}/helper/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1',
      },
      credentials: 'include',
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))

      if (response.status === 403) {
        // 403 covers dlp_blocked and stale dlp_confirm_required. Both are a
        // block — do not surface a confirmable modal or a send-anyway retry.
        emit('dlp_block', errorBody)
        return { abort: () => controller.abort() }
      }

      emit('message_error', {
        error: errorBody.error || `HTTP ${response.status}`,
        code: errorBody.code,
        // Forward the budget-block fields so useBudgetBlock shows the correct
        // scope + headroom (was stripped -> modal defaulted to 'team' w/ no amounts).
        scope: errorBody.scope,
        remaining: errorBody.remaining,
        limit: errorBody.limit,
      })
      return { abort: () => controller.abort() }
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const drain = (chunk) => {
      const events = parseSSE(chunk)
      for (const ev of events) {
        // Pass the inner data spread so listeners see flat payloads like
        // {type:'message_chunk', message_id, content}
        emit(ev.type, ev.data || {})
      }
    }

    // Idle watchdog: abort + surface error if upstream stalls mid-stream.
    let idleTimer = null
    let timedOut = false
    const clearIdle = () => { if (idleTimer) { clearTimeout(idleTimer); idleTimer = null } }
    const armIdle = () => {
      clearIdle()
      idleTimer = setTimeout(() => {
        timedOut = true
        emit('message_error', { error: 'Stream timed out' })
        controller.abort()
      }, STREAM_IDLE_TIMEOUT_MS)
    }

    try {
      armIdle()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // Reset on any received bytes (keepalives included).
        if (value) armIdle()

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue
          drain(part + '\n\n')
        }
      }

      if (buffer.trim()) {
        drain(buffer + '\n\n')
      }
    } finally {
      clearIdle()
    }

    // Watchdog already emitted the error before aborting.
    void timedOut
  } catch (error) {
    if (error.name === 'AbortError') return { abort: () => controller.abort() }
    emit('message_error', { error: error.message })
  }

  return { abort: () => controller.abort() }
}

/**
 * Wipe the user's helper history (server-side).
 */
export async function clearHelper() {
  const response = await fetch(`${API_BASE_URL}/helper/clear`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': '1' },
    credentials: 'include',
  })
  return response.json()
}

/**
 * Fetch persisted helper history.
 *
 * @returns {Promise<Array<{role:string,content:string,page_context?:object,deep_links?:Array,created_at:string}>>}
 */
export async function getHelperHistory() {
  const response = await fetch(`${API_BASE_URL}/helper/history`, {
    method: 'GET',
    credentials: 'include',
  })
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}))
    throw new Error(errorBody.error || `HTTP ${response.status}`)
  }
  const data = await response.json()
  // Backend may return either an array or {messages:[...]}; accept both.
  if (Array.isArray(data)) return data
  return data?.messages || []
}

export default {
  streamHelper,
  clearHelper,
  getHelperHistory,
}
