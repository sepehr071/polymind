/**
 * All-in-one router agent — SSE client for /api/agent.
 */
import { API_BASE_URL } from './apiBase'
import api from './api'

// Image gen can take 60–120s with only keepalives; 90s was tight under proxy lag.
const STREAM_IDLE_TIMEOUT_MS = 180000

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
        events.push({ type: currentEvent, data: JSON.parse(currentData) })
      } catch {
        /* ignore */
      }
      currentEvent = null
      currentData = ''
    }
  }
  return events
}

async function streamPost(path, body, handlers = {}, signal) {
  const controller = new AbortController()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-CSRF-Token': '1',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      handlers.onError?.({
        ...errorData,
        error: errorData.error || `HTTP ${response.status}`,
        status: errorData.status ?? response.status,
      })
      return { abort: () => controller.abort() }
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

    const dispatch = (event) => {
      const d = event.data
      switch (event.type) {
        case 'conversation_created':
          handlers.onConversationCreated?.(d)
          break
        case 'message_saved':
          handlers.onMessageSaved?.(d)
          break
        case 'message_start':
          handlers.onMessageStart?.(d)
          break
        case 'message_chunk':
          handlers.onMessageChunk?.(d)
          break
        case 'message_complete':
          handlers.onMessageComplete?.(d)
          break
        case 'title_updated':
          handlers.onTitleUpdated?.(d)
          break
        case 'tool_call':
          handlers.onToolCall?.(d)
          break
        case 'tool_result':
          handlers.onToolResult?.(d)
          break
        case 'data_status':
          handlers.onDataStatus?.(d)
          break
        case 'status':
          handlers.onStatus?.(d)
          break
        case 'artifact':
          handlers.onArtifact?.(d)
          break
        case 'clarify':
          handlers.onClarify?.(d)
          break
        case 'done':
          handlers.onDone?.(d)
          break
        case 'error':
          handlers.onError?.(d)
          break
        default:
          break
      }
    }

    armIdle()
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (value) armIdle()
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          if (!part.trim()) continue
          for (const ev of parseSSE(part + '\n\n')) dispatch(ev)
        }
      }
      if (buffer.trim()) {
        for (const ev of parseSSE(buffer + '\n\n')) dispatch(ev)
      }
    } finally {
      clearIdle()
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      // Surface abort so callers can clear isStreaming; ignore pure cleanup.
      handlers.onAbort?.()
    } else {
      handlers.onError?.({ error: err instanceof Error ? err.message : String(err) })
    }
  }

  return { abort: () => controller.abort() }
}

export function streamAgent(body, handlers, signal) {
  return streamPost('/agent/stream', body, handlers, signal)
}

export function streamAgentClarify(conversationId, answers, handlers, signal, extras = {}) {
  return streamPost(
    `/agent/${conversationId}/clarify`,
    { answers, ...extras },
    handlers,
    signal,
  )
}

export async function listAgentConversations(params = {}) {
  const { data } = await api.get('/agent', { params })
  return data
}

export const agentService = {
  streamAgent,
  streamAgentClarify,
  listAgentConversations,
}

export default agentService
