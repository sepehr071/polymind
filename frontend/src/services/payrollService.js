/**
 * Payroll service — upload a monthly payroll workbook, preview the parsed
 * employees, and stream the payslip-ZIP generation.
 *
 * Auth rides the httpOnly cookie everywhere (no Authorization/Bearer header):
 *   - JSON reads/writes go through the shared `api` axios (withCredentials +
 *     CSRF header injected by its request interceptor).
 *   - The SSE generate stream uses `fetch` + a manual ReadableStream parser
 *     because `EventSource` cannot send the `X-CSRF-Token` header the
 *     cookie-authed mutation requires. This mirrors streamService.js /
 *     meetingsService.streamMeetingStatus.
 */

import api from './api'
import { API_BASE_URL } from './apiBase'

/**
 * Idle watchdog for the generate SSE reader. Reset on EVERY chunk of received
 * bytes (incl. backend keepalive comments); on expiry we abort + surface an
 * error so the UI never spins forever on a stalled upstream. Generation can be
 * slow (one PDF per employee), so this is the gap BETWEEN bytes, not a total cap.
 */
const STREAM_IDLE_TIMEOUT_MS = 120000

/**
 * Upload the payroll spreadsheet via the shared file endpoint.
 * Response is NESTED `{ upload: { id, original_name, ... } }` — unwrap `.upload`.
 *
 * @param {File} file
 * @param {{ onUploadProgress?: (pct: number) => void }} [opts]
 * @returns {Promise<{ id: string, original_name?: string }>} the upload row
 */
export async function uploadPayrollFile(file, opts = {}) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/uploads/file', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: opts.onUploadProgress
      ? (e) => {
          const pct = e.total ? Math.round((e.loaded / e.total) * 100) : 0
          opts.onUploadProgress(pct)
        }
      : undefined,
  })
  // Route returns { upload: { ... } }; tolerate a flat shape just in case.
  return data?.upload ?? data
}

/**
 * Preview the parsed payroll for an uploaded workbook.
 *
 * @param {{ upload_id: string, employer?: string, month?: string }} params
 * @returns {Promise<{
 *   month: string,
 *   employer: string,
 *   count: number,
 *   columns_ok: boolean,
 *   warnings: string[],
 *   records: Array<{ code: string, name: string, net: number, earnings_total: number, deductions_total: number }>
 * }>}
 */
export async function previewPayroll({ upload_id, employer, month }) {
  const body = { upload_id }
  if (employer && employer.trim()) body.employer = employer.trim()
  if (month && month.trim()) body.month = month.trim()
  const { data } = await api.post('/payroll/preview', body)
  return data
}

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
 * Stream payslip-ZIP generation via SSE.
 *
 * Event types (per the backend contract):
 *   status -> { phase: 'parsing'|'rendering'|'zipping', done?: number, total?: number }
 *   file   -> { type:'file', url, name, ext, size }
 *   error  -> { error: string, status: number }
 *   done   -> {}
 *
 * @param {{ upload_id: string, employer?: string, month?: string }} params
 * @param {Object} handlers
 * @param {(d: { phase: string, done?: number, total?: number }) => void} [handlers.onStatus]
 * @param {(d: { url: string, name: string, ext: string, size: number }) => void} [handlers.onFile]
 * @param {(d: { error: string, status?: number }) => void} [handlers.onError]
 * @param {() => void} [handlers.onDone]
 * @param {AbortSignal} [signal] - optional external abort signal (unmount / cancel)
 * @returns {{ abort: () => void }}
 */
export function streamPayrollGenerate({ upload_id, employer, month }, handlers = {}, signal) {
  const controller = new AbortController()

  // Chain an external abort signal so the caller can cancel the reader loop
  // mid-stream (route change / component unmount). Mirrors streamChat/streamArena.
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  const body = { upload_id }
  if (employer && employer.trim()) body.employer = employer.trim()
  if (month && month.trim()) body.month = month.trim()

  ;(async () => {
    let response
    try {
      response = await fetch(`${API_BASE_URL}/payroll/generate`, {
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
      // with our legacy { error, status } shape — forward it.
      const errorData = await response.json().catch(() => ({}))
      handlers.onError?.({
        error: errorData.error || `HTTP ${response.status}`,
        status: errorData.status ?? response.status,
      })
      return
    }
    if (!response.body) {
      handlers.onError?.({ error: `HTTP ${response.status}` })
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
        case 'file':
          handlers.onFile?.(payload)
          break
        case 'error':
          handlers.onError?.(payload)
          break
        case 'done':
          handlers.onDone?.()
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

export default {
  uploadPayrollFile,
  previewPayroll,
  streamPayrollGenerate,
}
