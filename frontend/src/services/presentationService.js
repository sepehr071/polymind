/**
 * Presentation service — generate a deck outline, persist/patch it, and stream
 * the .pptx render. Two SSE flows + two plain JSON calls.
 *
 * Auth rides the httpOnly cookie everywhere (no Authorization/Bearer header):
 *   - JSON reads/writes go through the shared `api` axios (withCredentials +
 *     CSRF header injected by its request interceptor).
 *   - The outline/render SSE streams use `fetch` + a manual ReadableStream
 *     parser because `EventSource` cannot send the `X-CSRF-Token` header the
 *     cookie-authed mutation requires. This mirrors payrollService.js /
 *     streamService.js / meetingsService.streamMeetingStatus.
 *
 * Backend contract (app/api/routers/presentations.py):
 *   POST /presentations/outline       — SSE: status, outline, error, done
 *   POST /presentations/{id}/render   — SSE: status, warning, file, error, done
 *   GET  /presentations               — { presentations: [...] }
 *   PATCH /presentations/{id}         — the updated record
 * SSE frames are `event: <type>\ndata: <json>\n\n`. A non-2xx response (DLP 403 /
 * budget 402 / validation 400) returns a JSON body — we forward it to onError.
 */

import api from './api'
import { API_BASE_URL } from './apiBase'

/**
 * Idle watchdog for an SSE reader. Reset on EVERY chunk of received bytes (incl.
 * backend keepalive comments); on expiry we abort + surface an error so the UI
 * never spins forever on a stalled upstream. Per-slide image generation can be
 * slow, so this is the gap BETWEEN bytes, not a total cap.
 */
// Multi-agent outline (research→plan→draft→design→critic) can sit on one
// OpenRouter call for a long stretch; 10m idle matches research SSE budget.
const STREAM_IDLE_TIMEOUT_MS = 600000

/**
 * SSE event field parser for one frame.
 * Frames are separated by a blank line (`\n\n`); within a frame:
 *   `event: <name>`   — event name (default "message")
 *   `data: <payload>` — payload; multiple `data:` lines concatenated with `\n`
 *   `:<text>`         — comment (e.g. `:keepalive`), ignored
 */
function parseFrame(frame) {
  let eventName = 'message'
  const dataLines = []
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line) continue
    if (line.startsWith(':')) continue // comment / keepalive
    const colonIdx = line.indexOf(':')
    let field
    let value
    if (colonIdx === -1) {
      field = line
      value = ''
    } else {
      field = line.slice(0, colonIdx)
      value = line.slice(colonIdx + 1)
      if (value.startsWith(' ')) value = value.slice(1)
    }
    if (field === 'event') eventName = value
    else if (field === 'data') dataLines.push(value)
    // `id` / `retry` ignored — not used by our backend.
  }
  if (dataLines.length === 0) return null
  return { event: eventName, data: dataLines.join('\n') }
}

/**
 * Generic cookie-authed SSE POST with a ReadableStream parser + idle watchdog.
 * Forwards parsed frames to the matching `handlers.on*` callback by event name.
 *
 * @param {string} path  - path under API_BASE_URL (e.g. '/presentations/outline')
 * @param {Object} body  - JSON request body
 * @param {Object} handlers
 * @param {(d: any) => void} [handlers.onStatus]
 * @param {(d: any) => void} [handlers.onOutline]
 * @param {(d: any) => void} [handlers.onFile]
 * @param {(d: any) => void} [handlers.onWarning]
 * @param {(d: any) => void} [handlers.onError]
 * @param {(d: any) => void} [handlers.onDone]
 * @param {AbortSignal} [signal] - optional external abort signal (unmount / cancel)
 * @returns {{ abort: () => void }}
 */
function streamPost(path, body, handlers = {}, signal) {
  const controller = new AbortController()

  // Chain an external abort signal so the caller can cancel the reader loop
  // mid-stream (route change / component unmount). Mirrors streamPayrollGenerate.
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  ;(async () => {
    let response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        // httpOnly-cookie auth: send cookies (no Authorization header) + the
        // CSRF header the cookie-authed mutation requires.
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          'X-CSRF-Token': '1',
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
    } catch (err) {
      if (err?.name === 'AbortError') return
      handlers.onError?.({ error: err instanceof Error ? err.message : String(err) })
      return
    }

    if (!response.ok) {
      // Non-2xx: a gate (DLP/budget) or validation failure returns a JSON body
      // with our legacy { error, status } shape (+ DLP/budget `code`, `scope`,
      // `remaining`, `limit` fields). Forward the WHOLE body so the budget hook
      // can read `code`/`scope`, then layer `status` on top.
      const errorData = await response.json().catch(() => ({}))
      handlers.onError?.({
        ...errorData,
        error: errorData.error || `HTTP ${response.status}`,
        status: errorData.status ?? response.status,
      })
      return
    }
    if (!response.body) {
      handlers.onError?.({ error: `HTTP ${response.status}`, status: response.status })
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    let idleTimer = null
    const clearIdle = () => {
      if (idleTimer) {
        clearTimeout(idleTimer)
        idleTimer = null
      }
    }
    const armIdle = () => {
      clearIdle()
      idleTimer = setTimeout(() => {
        handlers.onError?.({ error: 'Stream timed out' })
        controller.abort()
      }, STREAM_IDLE_TIMEOUT_MS)
    }

    const dispatch = (evt) => {
      if (!evt) return
      let payload = {}
      try {
        payload = evt.data ? JSON.parse(evt.data) : {}
      } catch {
        // Non-JSON data frame — ignore (keepalive padding etc.).
        return
      }
      switch (evt.event) {
        case 'status':
          handlers.onStatus?.(payload)
          break
        case 'outline':
          handlers.onOutline?.(payload)
          break
        case 'file':
          handlers.onFile?.(payload)
          break
        case 'warning':
          handlers.onWarning?.(payload)
          break
        case 'error':
          handlers.onError?.(payload)
          break
        case 'done':
          handlers.onDone?.(payload)
          break
        default:
          // Unknown event name — ignore.
          break
      }
    }

    try {
      armIdle()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // Reset on any received bytes (keepalives included).
        if (value) armIdle()

        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line.
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const frame of parts) {
          if (!frame.trim()) continue
          dispatch(parseFrame(frame))
        }
      }

      // Flush any trailing frame left in the buffer.
      if (buffer.trim()) dispatch(parseFrame(buffer))
    } catch (err) {
      // Watchdog already fired onError before aborting; the AbortError here is
      // that abort (or a caller-initiated cancel) so don't double-report.
      if (err?.name === 'AbortError') return
      handlers.onError?.({ error: err instanceof Error ? err.message : String(err) })
    } finally {
      clearIdle()
      try {
        reader.releaseLock()
      } catch {
        /* ignore */
      }
    }
  })()

  return {
    abort() {
      controller.abort()
    },
  }
}

/**
 * Stream deck-outline generation via SSE.
 *
 * Event types (per the backend contract):
 *   status  -> { phase: 'researching'|'planning'|'drafting'|'designing'|'reviewing'|… }
 *   warning -> { message }
 *   outline -> { id, outline, theme? }
 *   error   -> { error, status }
 *   done    -> { id }
 *
 * @param {Object} body - { topic, slide_count?, tone?, audience?, language?,
 *   theme?, workspace_id?, project_id?, upload_ids?, knowledge_ids?,
 *   generate_images?, dlp_confirmed?, dlp_confirm_token? }
 * @param {Object} handlers - { onStatus, onOutline, onError, onDone }
 * @param {AbortSignal} [signal]
 * @returns {{ abort: () => void }}
 */
export function streamOutline(body, handlers, signal) {
  return streamPost('/presentations/outline', body, handlers, signal)
}

/**
 * Stream a deck render to .pptx via SSE.
 *
 * Event types (per the backend contract):
 *   status  -> { phase: 'imaging'|'rendering', done?, total? }
 *   warning -> { slide, message }
 *   file    -> { type:'file', url, name, ext, size, upload_id }
 *   error   -> { error, status }
 *   done    -> { id }
 *
 * @param {string} id - presentation id
 * @param {Object} body - { outline?, dlp_confirmed?, dlp_confirm_token? }
 * @param {Object} handlers - { onStatus, onWarning, onFile, onError, onDone }
 * @param {AbortSignal} [signal]
 * @returns {{ abort: () => void }}
 */
export function streamRender(id, body, handlers, signal) {
  return streamPost(`/presentations/${id}/render`, body, handlers, signal)
}

/**
 * List the caller's decks (most-recent first).
 * @param {{ project_id?: string }} [params]
 * @returns {Promise<{ presentations: Array<Object> }>}
 */
export async function listPresentations(params = {}) {
  const { data } = await api.get('/presentations', { params })
  return data
}

/**
 * Patch a deck's outline / title / theme.
 * @param {string} id
 * @param {{ outline?: Object, title?: string, theme?: string }} patch
 * @returns {Promise<Object>} the updated record
 */
export async function savePresentation(id, patch) {
  const { data } = await api.patch(`/presentations/${id}`, patch)
  return data
}

export default {
  streamOutline,
  streamRender,
  listPresentations,
  savePresentation,
}
