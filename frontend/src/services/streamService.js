/**
 * Stream Service - Handles SSE (Server-Sent Events) streaming for chat and arena
 * Replaces WebSocket/Socket.IO implementation
 */

import { API_BASE_URL } from './apiBase'

/**
 * Idle watchdog timeout for SSE reader loops. If `reader.read()` doesn't
 * resolve with bytes within this window the upstream is considered stalled —
 * we abort the stream and fire the error callback. Reset on EVERY chunk of
 * received bytes (incl. backend keepalive heartbeats) so a live-but-quiet
 * stream stays alive.
 */
const STREAM_IDLE_TIMEOUT_MS = 60000

/**
 * Parse SSE event text into structured events
 * SSE format: "event: type\ndata: {...}\n\n"
 */
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
          data: JSON.parse(currentData)
        })
      } catch (e) {
        console.error('Failed to parse SSE data:', currentData, e)
      }
      currentEvent = null
      currentData = ''
    }
  }

  return events
}

/**
 * Stream chat messages using SSE
 *
 * @param {Object} data - Request data
 * @param {string|null} data.conversation_id - Existing conversation ID or null for new
 * @param {string} data.config_id - LLM config ID
 * @param {string} data.message - User message content
 * @param {Array} data.attachments - Image attachments (optional)
 * @param {Object} handlers - Event handlers
 * @param {Function} handlers.onConversationCreated - New conversation created
 * @param {Function} handlers.onMessageSaved - User message saved
 * @param {Function} handlers.onMessageStart - AI generation started
 * @param {Function} handlers.onMessageChunk - Streaming chunk received
 * @param {Function} handlers.onMessageComplete - Generation complete
 * @param {Function} handlers.onMessageError - Error occurred
 * @param {Function} handlers.onTitleUpdated - Title was updated
 * @returns {Promise<{abort: Function}>} Object with abort function to cancel stream
 */
export async function streamChat({ conversation_id, config_id, message, attachments, intent, project_id, dlp_confirmed, dlp_redact, dlp_confirm_token, web_search, web_fetch, reasoning_effort, quoted_text, lang }, handlers, signal) {
  const controller = new AbortController()

  // Chain an external abort signal (conversation switch / Stop button / unmount)
  // so the caller can actually cancel the reader loop mid-stream — the returned
  // `{abort}` only resolves after the stream ends, so it can't. Mirrors
  // streamArena/streamDebate. Without this the page's AbortController was a
  // no-op and an orphaned stream kept writing into a switched-away view.
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort())
  }

  const body = { conversation_id, config_id, message, attachments }
  if (intent) body.intent = intent
  if (project_id !== undefined) body.project_id = project_id
  if (dlp_confirmed) body.dlp_confirmed = true
  if (dlp_redact) body.dlp_redact = true
  if (dlp_confirm_token) body.dlp_confirm_token = dlp_confirm_token
  if (web_search) body.web_search = true
  if (web_fetch) body.web_fetch = true
  if (reasoning_effort) body.reasoning_effort = reasoning_effort
  if (quoted_text) body.quoted_text = quoted_text
  // UI language for DLP explanations (backend _resolve_user_lang prefers body
  // lang). Was silently dropped by this whitelist before.
  if (lang) body.lang = lang

  try {
    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      // httpOnly-cookie auth: send cookies (no Authorization header) + CSRF
      // header the cookie-authed mutation requires.
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1'
      },
      body: JSON.stringify(body),
      signal: controller.signal
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      // Forward full error body (with code/matches for DLP) to handler before throwing
      if (handlers?.onMessageError && (errorData.code || errorData.matches)) {
        handlers.onMessageError({
          error: errorData.error || `HTTP ${response.status}`,
          code: errorData.code,
          matches: errorData.matches,
          highest_action: errorData.highest_action,
          redacted_preview: errorData.redacted_preview,
          redactable: errorData.redactable,
          // Replay token the gate minted against its OWN scanned text (incl.
          // server-side attachment text). Still forwarded. The UI does not use
          // it to unlock a send.
          confirm_token: errorData.confirm_token,
          scope: errorData.scope,
          remaining: errorData.remaining,
          limit: errorData.limit,
          remaining_credits: errorData.remaining_credits,
          limit_credits: errorData.limit_credits,
        })
        return { abort: () => controller.abort() }
      }
      throw new Error(errorData.error || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
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
        if (handlers.onMessageError) handlers.onMessageError({ error: 'Stream timed out' })
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

        // Process complete events from buffer
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || '' // Keep incomplete event in buffer

        for (const part of parts) {
          if (!part.trim()) continue

          const events = parseSSE(part + '\n\n')
          for (const event of events) {
            const handler = {
              'conversation_created': handlers.onConversationCreated,
              'message_saved': handlers.onMessageSaved,
              'message_start': handlers.onMessageStart,
              'message_chunk': handlers.onMessageChunk,
              'message_complete': handlers.onMessageComplete,
              'message_error': handlers.onMessageError,
              'title_updated': handlers.onTitleUpdated,
              // Data Analyzer agentic tool-loop: each run_python step emits a
              // tool_call (code) then a tool_result (stdout/error + artifacts).
              'tool_call': handlers.onToolCall,
              'tool_result': handlers.onToolResult,
              // Data Analyzer document extraction (PDF OCR etc.) progress emitted
              // before analysis begins: { phase, file, conversation_id }.
              'data_status': handlers.onDataStatus,
              'error': handlers.onMessageError
            }[event.type]

            if (handler) {
              handler(event.data)
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.trim()) {
        const events = parseSSE(buffer + '\n\n')
        for (const event of events) {
          const handler = {
            'conversation_created': handlers.onConversationCreated,
            'message_saved': handlers.onMessageSaved,
            'message_start': handlers.onMessageStart,
            'message_chunk': handlers.onMessageChunk,
            'message_complete': handlers.onMessageComplete,
            'message_error': handlers.onMessageError,
            'title_updated': handlers.onTitleUpdated,
            'tool_call': handlers.onToolCall,
            'tool_result': handlers.onToolResult,
            'data_status': handlers.onDataStatus,
            'error': handlers.onMessageError
          }[event.type]

          if (handler) {
            handler(event.data)
          }
        }
      }
    } finally {
      clearIdle()
    }

    // Watchdog already fired the error callback before aborting.
    void timedOut

  } catch (error) {
    if (error.name === 'AbortError') {
      // Stream was cancelled
      return
    }
    if (handlers.onMessageError) {
      handlers.onMessageError({ error: error.message })
    }
  }

  return { abort: () => controller.abort() }
}

/**
 * Cancel an ongoing chat generation
 *
 * @param {string} messageId - Message ID to cancel
 */
/**
 * Regenerate one assistant turn over SSE. Same events as streamChat
 * (message_start / message_chunk / message_complete / message_error).
 * The server has already deleted the old assistant row before the first token.
 */
export async function streamRegenerate(messageId, body, handlers, signal) {
  const controller = new AbortController()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let response
  try {
    response = await fetch(`${API_BASE_URL}/chat/regenerate/${messageId}`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1',
      },
      body: JSON.stringify({ stream: true, ...(body || {}) }),
      signal: controller.signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') return { abort: () => controller.abort() }
    if (handlers.onMessageError) handlers.onMessageError({ error: error.message })
    return { abort: () => controller.abort() }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    if (handlers.onMessageError) {
      handlers.onMessageError({
        error: errorData.error || `HTTP ${response.status}`,
        status: response.status,
        code: errorData.code,
        scope: errorData.scope,
        remaining: errorData.remaining,
        limit: errorData.limit,
        remaining_credits: errorData.remaining_credits,
        limit_credits: errorData.limit_credits,
      })
    }
    return { abort: () => controller.abort() }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (event) => {
    const handler = {
      message_start: handlers.onMessageStart,
      message_chunk: handlers.onMessageChunk,
      message_complete: handlers.onMessageComplete,
      message_error: handlers.onMessageError,
      error: handlers.onMessageError,
    }[event.type]
    if (handler) handler(event.data)
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        if (!part.trim()) continue
        for (const event of parseSSE(part + '\n\n')) dispatch(event)
      }
    }
    if (buffer.trim()) {
      for (const event of parseSSE(buffer + '\n\n')) dispatch(event)
    }
  } catch (error) {
    if (error.name !== 'AbortError' && handlers.onMessageError) {
      handlers.onMessageError({ error: error.message })
    }
  }

  return { abort: () => controller.abort() }
}

export async function cancelChat(messageId) {
  const response = await fetch(`${API_BASE_URL}/chat/cancel/${messageId}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-CSRF-Token': '1'
    }
  })
  return response.json()
}

/**
 * Stream arena messages using SSE
 * Streams responses from multiple configs in parallel
 *
 * @param {Object} data - Request data
 * @param {string|null} data.session_id - Existing session ID or null for new
 * @param {string} data.message - User message content
 * @param {Array<string>} data.config_ids - Array of config IDs (2-4)
 * @param {Object} handlers - Event handlers
 * @param {Function} handlers.onSessionCreated - New session created
 * @param {Function} handlers.onUserMessage - User message saved
 * @param {Function} handlers.onMessageStart - Config started generating (includes config_id)
 * @param {Function} handlers.onMessageChunk - Streaming chunk (includes config_id)
 * @param {Function} handlers.onMessageComplete - Config finished (includes config_id)
 * @param {Function} handlers.onMessageError - Config error (includes config_id)
 * @param {AbortSignal} [signal] - Optional external abort signal (Stop button)
 * @returns {Promise<{abort: Function}>} Object with abort function
 */
export async function streamArena(data, handlers, signal) {
  const controller = new AbortController()

  // Chain external signal so the page's Stop button aborts the reader loop
  // mid-stream (the returned `{abort}` only resolves after the stream ends).
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  try {
    const response = await fetch(`${API_BASE_URL}/arena/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1'
      },
      body: JSON.stringify(data),
      signal: controller.signal
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      // Forward full error body (with code/matches for DLP) so callers can
      // surface the violation modal as a defence-in-depth fallback when the
      // client skipped pre-flight.
      if (handlers?.onMessageError && (errorData.code || errorData.matches)) {
        handlers.onMessageError({
          error: errorData.error || `HTTP ${response.status}`,
          code: errorData.code,
          matches: errorData.matches,
          highest_action: errorData.highest_action,
          scope: errorData.scope,
          remaining: errorData.remaining,
          limit: errorData.limit,
          remaining_credits: errorData.remaining_credits,
          limit_credits: errorData.limit_credits,
        })
        return { abort: () => controller.abort() }
      }
      throw new Error(errorData.error || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
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
        if (handlers.onMessageError) handlers.onMessageError({ error: 'Stream timed out' })
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

        // Process complete events from buffer
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue

          const events = parseSSE(part + '\n\n')
          for (const event of events) {
            const handler = {
              'arena_session_created': handlers.onSessionCreated,
              'arena_user_message': handlers.onUserMessage,
              'arena_message_start': handlers.onMessageStart,
              'arena_message_chunk': handlers.onMessageChunk,
              'arena_message_complete': handlers.onMessageComplete,
              'arena_message_error': handlers.onMessageError,
              'error': handlers.onMessageError
            }[event.type]

            if (handler) {
              handler(event.data)
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.trim()) {
        const events = parseSSE(buffer + '\n\n')
        for (const event of events) {
          const handler = {
            'arena_session_created': handlers.onSessionCreated,
            'arena_user_message': handlers.onUserMessage,
            'arena_message_start': handlers.onMessageStart,
            'arena_message_chunk': handlers.onMessageChunk,
            'arena_message_complete': handlers.onMessageComplete,
            'arena_message_error': handlers.onMessageError,
            'error': handlers.onMessageError
          }[event.type]

          if (handler) {
            handler(event.data)
          }
        }
      }
    } finally {
      clearIdle()
    }

    // Watchdog already fired the error callback before aborting.
    void timedOut

  } catch (error) {
    if (error.name === 'AbortError') {
      return
    }
    if (handlers.onMessageError) {
      handlers.onMessageError({ error: error.message })
    }
  }

  return { abort: () => controller.abort() }
}

/**
 * Cancel an ongoing arena generation
 *
 * @param {string} sessionId - Session ID to cancel
 */
export async function cancelArena(sessionId) {
  const response = await fetch(`${API_BASE_URL}/arena/cancel/${sessionId}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-CSRF-Token': '1'
    }
  })
  return response.json()
}

/**
 * Stream debate session using SSE
 * Handles multi-round debate with multiple debaters and a judge
 *
 * @param {Object} data - Request data
 * @param {string} data.session_id - Debate session ID
 * @param {Object} handlers - Event handlers
 * @param {Function} handlers.onSessionStarted - Debate session started
 * @param {Function} handlers.onRoundStart - New round started (includes round number)
 * @param {Function} handlers.onMessageStart - Debater started (includes config_id, round)
 * @param {Function} handlers.onMessageChunk - Streaming chunk (includes config_id, round, content)
 * @param {Function} handlers.onMessageComplete - Debater finished (includes config_id, round, content, concluded)
 * @param {Function} handlers.onDebaterConcluded - Debater signaled done (infinite mode only)
 * @param {Function} handlers.onRoundComplete - Round finished (includes round number, concluded_count)
 * @param {Function} handlers.onJudgeStart - Judge started evaluating
 * @param {Function} handlers.onJudgeChunk - Judge streaming chunk
 * @param {Function} handlers.onJudgeComplete - Judge finished with verdict
 * @param {Function} handlers.onSessionComplete - Entire debate finished
 * @param {Function} handlers.onError - Error occurred
 * @param {AbortSignal} [signal] - Optional external abort signal (Stop button)
 * @returns {Promise<{abort: Function}>} Object with abort function
 */
export async function streamDebate(data, handlers, signal) {
  const controller = new AbortController()

  // Chain external signal so the page's Stop button aborts the reader loop
  // mid-stream (the returned `{abort}` only resolves after the stream ends).
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  try {
    const response = await fetch(`${API_BASE_URL}/debate/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1'
      },
      body: JSON.stringify(data),
      signal: controller.signal
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      // Forward DLP rejection bodies to `onError` so callers can surface the
      // violation modal as a defence-in-depth fallback.
      if (handlers?.onError && (errorData.code || errorData.matches)) {
        handlers.onError({
          error: errorData.error || `HTTP ${response.status}`,
          code: errorData.code,
          matches: errorData.matches,
          highest_action: errorData.highest_action,
          scope: errorData.scope,
          remaining: errorData.remaining,
          limit: errorData.limit,
          remaining_credits: errorData.remaining_credits,
          limit_credits: errorData.limit_credits,
        })
        return { abort: () => controller.abort() }
      }
      throw new Error(errorData.error || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
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
        if (handlers.onError) handlers.onError({ error: 'Stream timed out' })
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

        // Process complete events from buffer
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue

          const events = parseSSE(part + '\n\n')
          for (const event of events) {
            const handler = {
              'debate_session_started': handlers.onSessionStarted,
              'debate_round_start': handlers.onRoundStart,
              'debate_message_start': handlers.onMessageStart,
              'debate_message_chunk': handlers.onMessageChunk,
              'debate_message_complete': handlers.onMessageComplete,
              'debate_debater_concluded': handlers.onDebaterConcluded,
              'debate_round_complete': handlers.onRoundComplete,
              'debate_judge_start': handlers.onJudgeStart,
              'debate_judge_chunk': handlers.onJudgeChunk,
              'debate_judge_complete': handlers.onJudgeComplete,
              'debate_session_complete': handlers.onSessionComplete,
              'debate_error': handlers.onError,
              'error': handlers.onError
            }[event.type]

            if (handler) {
              handler(event.data)
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.trim()) {
        const events = parseSSE(buffer + '\n\n')
        for (const event of events) {
          const handler = {
            'debate_session_started': handlers.onSessionStarted,
            'debate_round_start': handlers.onRoundStart,
            'debate_message_start': handlers.onMessageStart,
            'debate_message_chunk': handlers.onMessageChunk,
            'debate_message_complete': handlers.onMessageComplete,
            'debate_debater_concluded': handlers.onDebaterConcluded,
            'debate_round_complete': handlers.onRoundComplete,
            'debate_judge_start': handlers.onJudgeStart,
            'debate_judge_chunk': handlers.onJudgeChunk,
            'debate_judge_complete': handlers.onJudgeComplete,
            'debate_session_complete': handlers.onSessionComplete,
            'debate_error': handlers.onError,
            'error': handlers.onError
          }[event.type]

          if (handler) {
            handler(event.data)
          }
        }
      }
    } finally {
      clearIdle()
    }

    // Watchdog already fired the error callback before aborting.
    void timedOut

  } catch (error) {
    if (error.name === 'AbortError') {
      return
    }
    if (handlers.onError) {
      handlers.onError({ error: error.message })
    }
  }

  return { abort: () => controller.abort() }
}

/**
 * Stream automate-agent task execution using SSE
 * Backend polls browser-use cloud and re-emits events.
 *
 * @param {Object} params
 * @param {string} params.task - Natural language task description
 * @param {string} params.model - Model ID (e.g. 'claude-sonnet-4.6')
 * @param {Function} params.onTaskStarted - {task_id, session_id, live_url, model}
 * @param {Function} params.onMessage - {cursor_id, role, type, summary, screenshot_url}
 * @param {Function} params.onStatusChange - {status}
 * @param {Function} params.onComplete - {output, total_messages, duration_ms}
 * @param {Function} params.onError - {message, code}
 * @param {AbortSignal} params.signal - Optional external abort signal
 * @returns {Promise<{abort: Function}>}
 */
export async function streamAutomateTask({ task, model, dlp_confirmed, dlp_confirm_token, onTaskStarted, onMessage, onStatusChange, onComplete, onError, signal }) {
  const controller = new AbortController()

  // Chain external signal so callers can abort without holding controller ref
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  const body = { task, model }
  if (dlp_confirmed) body.dlp_confirmed = true
  if (dlp_confirm_token) body.dlp_confirm_token = dlp_confirm_token

  try {
    const response = await fetch(`${API_BASE_URL}/automate-agent/tasks/run`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': '1'
      },
      body: JSON.stringify(body),
      signal: controller.signal
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      // Forward DLP rejection bodies to `onError` so callers can surface the
      // violation modal as a defence-in-depth fallback.
      if (onError && (errorData.code || errorData.matches)) {
        onError({
          message: errorData.error || `HTTP ${response.status}`,
          code: errorData.code,
          matches: errorData.matches,
          highest_action: errorData.highest_action,
          scope: errorData.scope,
          remaining: errorData.remaining,
          limit: errorData.limit,
          remaining_credits: errorData.remaining_credits,
          limit_credits: errorData.limit_credits,
        })
        return { abort: () => controller.abort() }
      }
      throw new Error(errorData.error || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
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
        if (onError) onError({ message: 'Stream timed out' })
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

          const events = parseSSE(part + '\n\n')
          for (const event of events) {
            const handler = {
              'task_started': onTaskStarted,
              'message': onMessage,
              'status_change': onStatusChange,
              'task_complete': onComplete,
              'error': onError,
            }[event.type]

            if (handler) handler(event.data)
          }
        }
      }

      // Flush remaining buffer
      if (buffer.trim()) {
        const events = parseSSE(buffer + '\n\n')
        for (const event of events) {
          const handler = {
            'task_started': onTaskStarted,
            'message': onMessage,
            'status_change': onStatusChange,
            'task_complete': onComplete,
            'error': onError,
          }[event.type]

          if (handler) handler(event.data)
        }
      }
    } finally {
      clearIdle()
    }

    // Watchdog already fired the error callback before aborting.
    void timedOut

  } catch (error) {
    if (error.name === 'AbortError') return
    if (onError) onError({ message: error.message })
  }

  return { abort: () => controller.abort() }
}

/**
 * Cancel an ongoing debate session
 *
 * @param {string} sessionId - Session ID to cancel
 */
export async function cancelDebate(sessionId) {
  const response = await fetch(`${API_BASE_URL}/debate/cancel/${sessionId}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-CSRF-Token': '1'
    }
  })
  return response.json()
}

export default {
  streamChat,
  cancelChat,
  streamArena,
  cancelArena,
  streamDebate,
  cancelDebate,
  streamAutomateTask,
}
