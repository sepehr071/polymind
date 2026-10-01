/**
 * Cookie-authed SSE POST shared by studio tools (OCR, research, email, …).
 * @returns {{ abort: () => void }}
 */
import { API_BASE_URL } from './apiBase'

function parseFrame(frame) {
  let eventName = 'message'
  const dataLines = []
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line) continue
    if (line.startsWith(':')) continue
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
  }
  if (dataLines.length === 0) return null
  return { event: eventName, data: dataLines.join('\n') }
}

/**
 * @param {Object} opts
 * @param {string} opts.url - path under API_BASE_URL e.g. '/research/run'
 * @param {Object} opts.body
 * @param {Object} opts.handlers - { onStatus, onDelta, onToken, onDone, onError, onResult, … }
 *   Unknown event names call handlers[`on${PascalCase}`] if present, else ignored.
 * @param {AbortSignal} [opts.signal]
 * @param {number} [opts.idleTimeoutMs=180000]
 */
export function streamStudio({
  url,
  body,
  handlers = {},
  signal,
  idleTimeoutMs = 180_000,
}) {
  const controller = new AbortController()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  const path = url.startsWith('/') ? url : `/${url}`

  ;(async () => {
    let response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          'X-CSRF-Token': '1',
        },
        body: JSON.stringify(body ?? {}),
        signal: controller.signal,
      })
    } catch (err) {
      if (err?.name === 'AbortError') return
      handlers.onError?.({ error: err instanceof Error ? err.message : String(err) })
      return
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      handlers.onError?.({
        ...errorData,
        error: errorData.error || errorData.message || `HTTP ${response.status}`,
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
      }, idleTimeoutMs)
    }

    const dispatch = (evt) => {
      if (!evt) return
      let payload = {}
      try {
        payload = evt.data ? JSON.parse(evt.data) : {}
      } catch {
        return
      }
      const name = evt.event || 'message'
      switch (name) {
        case 'status':
          handlers.onStatus?.(payload)
          break
        case 'delta':
          handlers.onDelta?.(payload)
          break
        case 'token':
          handlers.onToken?.(payload)
          handlers.onDelta?.(payload) // alias
          break
        case 'result':
          handlers.onResult?.(payload)
          break
        case 'file_result':
          handlers.onFileResult?.(payload)
          break
        case 'file_error':
          handlers.onFileError?.(payload)
          break
        case 'error':
          handlers.onError?.(payload)
          break
        case 'done':
          handlers.onDone?.(payload)
          break
        default: {
          const key = `on${name.charAt(0).toUpperCase()}${name.slice(1).replace(/_([a-z])/g, (_, c) => c.toUpperCase())}`
          handlers[key]?.(payload)
          break
        }
      }
    }

    try {
      armIdle()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (value) armIdle()
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const frame of parts) {
          if (!frame.trim()) continue
          dispatch(parseFrame(frame))
        }
      }
      if (buffer.trim()) dispatch(parseFrame(buffer))
    } catch (err) {
      if (err?.name !== 'AbortError') {
        handlers.onError?.({ error: err instanceof Error ? err.message : String(err) })
      }
    } finally {
      clearIdle()
    }
  })()

  return { abort: () => controller.abort() }
}
