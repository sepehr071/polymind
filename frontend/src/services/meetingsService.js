import axios from 'axios'
import api from './api'
import { API_BASE_URL } from './apiBase'

/**
 * Idle watchdog timeout for the meeting-status SSE reader loop. Reset on every
 * chunk of received bytes (incl. backend `:keepalive` comments); on expiry we
 * abort + call `onError` so the UI doesn't spin forever on a stalled upstream.
 */
const STREAM_IDLE_TIMEOUT_MS = 60000

// Dedicated axios instance for large multipart uploads (audio files up to 500MB).
// The default `api` instance caps content/body at 50MB which would block real uploads.
// Auth rides the httpOnly cookie (withCredentials); non-GET needs the CSRF header.
const uploadApi = axios.create({
  baseURL: API_BASE_URL,
  maxContentLength: 500 * 1024 * 1024, // 500MB
  maxBodyLength: 500 * 1024 * 1024, // 500MB
  withCredentials: true,
})

uploadApi.interceptors.request.use(
  (config) => {
    if ((config.method || 'get').toLowerCase() !== 'get') {
      config.headers['X-CSRF-Token'] = '1'
    }
    return config
  },
  (error) => Promise.reject(error)
)

/**
 * Upload an audio/video file for meeting transcription & summarization.
 *
 * @param {File|Blob} file
 * @param {object} [opts]
 * @param {string|null} [opts.title]
 * @param {number|null} [opts.num_speakers]
 * @param {string|null} [opts.meeting_brief]
 * @param {string|null} [opts.series_id]
 * @param {string} [opts.filename]
 * @param {(progress: number) => void} [opts.onUploadProgress]
 * @returns {Promise<object>} Meeting
 */
export async function uploadMeeting(file, opts = {}) {
  const fd = new FormData()
  const fname =
    opts.filename ?? (file instanceof File ? file.name : 'recording.webm')
  fd.append('file', file, fname)
  if (opts.title) fd.append('title', opts.title)
  if (opts.num_speakers != null && opts.num_speakers > 0) {
    fd.append('num_speakers', String(opts.num_speakers))
  }
  if (opts.meeting_brief && opts.meeting_brief.trim()) {
    fd.append('meeting_brief', opts.meeting_brief.trim())
  }
  if (opts.series_id) fd.append('series_id', opts.series_id)

  const response = await uploadApi.post('/meetings/upload', fd, {
    onUploadProgress: opts.onUploadProgress
      ? (e) => {
          const pct = e.total ? Math.round((e.loaded / e.total) * 100) : 0
          opts.onUploadProgress(pct)
        }
      : undefined,
  })
  return response.data?.meeting ?? response.data
}

export async function listMeetings({ series_id, q, limit, offset } = {}) {
  const params = {}
  if (series_id) params.series_id = series_id
  if (q && q.trim()) params.q = q.trim()
  if (limit != null) params.limit = limit
  if (offset != null) params.offset = offset
  const response = await api.get('/meetings/list', { params })
  return {
    meetings: response.data?.meetings ?? [],
    has_more: response.data?.has_more ?? false,
  }
}

export async function getMeeting(id) {
  const response = await api.get(`/meetings/${id}`)
  return response.data?.meeting ?? response.data
}

export async function getTranscript(id) {
  const response = await api.get(`/meetings/${id}/transcript`)
  return response.data?.transcript ?? response.data
}

export async function getSummary(id) {
  const response = await api.get(`/meetings/${id}/summary`)
  return response.data?.summary ?? response.data
}

export async function renameSpeaker(id, speakerId, displayName) {
  const response = await api.patch(`/meetings/${id}/speakers/${speakerId}`, {
    display_name: displayName,
  })
  return response.data?.meeting ?? response.data
}

export async function generateActionPack(id, body = {}) {
  const response = await api.post(`/meetings/${id}/action-pack`, body)
  return response.data
}

export async function regenerate(id) {
  const response = await api.post(`/meetings/${id}/regenerate-summary`)
  return response.data
}

export async function cancelMeeting(id) {
  const response = await api.post(`/meetings/${id}/cancel`)
  return response.data?.meeting ?? response.data
}

export async function suggestSeries(title) {
  const response = await api.get('/meetings/suggest-series', {
    params: { title },
  })
  return response.data?.suggestion ?? null
}

export async function spawnConversation(id) {
  const response = await api.post(`/meetings/${id}/spawn-conversation`)
  return response.data
}

/**
 * Stream meeting status updates via SSE.
 *
 * `EventSource` cannot send custom headers, so we use `fetch` + a manual
 * ReadableStream parser; auth rides the httpOnly cookie (credentials:'include').
 *
 * Protocol (per the SSE spec we care about here):
 *   - Frames separated by `\n\n`
 *   - Each frame may contain multiple lines:
 *       `event: <name>`     — event name (default "message")
 *       `data: <payload>`   — payload; multiple `data:` lines concatenated with `\n`
 *       `:<text>`           — comment (e.g. `:keepalive`), ignored
 *
 * @param {string} id
 * @param {object} handlers
 * @param {(evt: { event: string, data: string }) => void} handlers.onEvent
 * @param {(err: Error) => void} [handlers.onError]
 * @param {AbortSignal} [handlers.signal]
 * @returns {{ cancel: () => void }}
 */
export function streamMeetingStatus(id, { onEvent, onError, signal } = {}) {
  const ac = new AbortController()
  // Chain caller-provided signal if present.
  if (signal) {
    if (signal.aborted) ac.abort()
    else signal.addEventListener('abort', () => ac.abort(), { once: true })
  }

  ;(async () => {
    let resp
    try {
      resp = await fetch(`${API_BASE_URL}/meetings/${id}/stream`, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
        },
        credentials: 'include',
        signal: ac.signal,
      })
    } catch (err) {
      if (err?.name === 'AbortError') return
      onError?.(err instanceof Error ? err : new Error(String(err)))
      return
    }

    if (!resp.ok || !resp.body) {
      onError?.(new Error(`SSE failed: ${resp.status} ${resp.statusText}`))
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    // Idle watchdog: abort + surface error if upstream stalls mid-stream.
    let idleTimer = null
    let timedOut = false
    const clearIdle = () => { if (idleTimer) { clearTimeout(idleTimer); idleTimer = null } }
    const armIdle = () => {
      clearIdle()
      idleTimer = setTimeout(() => {
        timedOut = true
        onError?.(new Error('Stream timed out'))
        ac.abort()
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

        // SSE frames are separated by a blank line (`\n\n`).
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const frame of parts) {
          if (!frame) continue
          let eventName = 'message'
          const dataLines = []
          for (const rawLine of frame.split('\n')) {
            const line = rawLine.replace(/\r$/, '')
            if (!line) continue
            if (line.startsWith(':')) continue // comment / keepalive
            const colonIdx = line.indexOf(':')
            let field, fieldValue
            if (colonIdx === -1) {
              field = line
              fieldValue = ''
            } else {
              field = line.slice(0, colonIdx)
              fieldValue = line.slice(colonIdx + 1)
              if (fieldValue.startsWith(' ')) fieldValue = fieldValue.slice(1)
            }
            if (field === 'event') eventName = fieldValue
            else if (field === 'data') dataLines.push(fieldValue)
            // `id` and `retry` fields ignored — not used by our backend.
          }
          if (dataLines.length === 0) continue
          onEvent?.({ event: eventName, data: dataLines.join('\n') })
        }
      }
    } catch (err) {
      // Watchdog already fired onError before aborting; the AbortError here is
      // that abort (or a caller-initiated cancel) so don't double-report.
      if (err?.name === 'AbortError') return
      onError?.(err instanceof Error ? err : new Error(String(err)))
    } finally {
      clearIdle()
      void timedOut
      try {
        reader.releaseLock()
      } catch {
        /* ignore */
      }
    }
  })()

  return {
    cancel() {
      ac.abort()
    },
  }
}
