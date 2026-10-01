import { useRef, useCallback, useEffect, useState } from 'react'
import { streamChat, streamRegenerate, cancelChat } from '../../../services/streamService'
import { chatActionError } from './useChatMessages'
import { parseHtmlCode, isRunnableCode } from '../../../components/chat/CodeCanvas/parse'
import { dlpService } from '@/services/dlpService'
import { touchConversationInCache } from '../../../components/layout/sidebar/useSidebarConversations'
import { useWorkspace } from '@/context/WorkspaceContext'
import toast from 'react-hot-toast'
import i18n from '../../../i18n'

export function useChatStream({
  conversationId,
  selectedConfigId,
  navigate,
  queryClient,
  setMessages,
  setStreamingContent,
  setStreamingMessageId,
  setIsStreaming,
  justFinishedStreamingRef,
  streamErrorRef,
  onCanvasIntent,
  projectId = null,
  onDLPViolation = null,
  onBudgetExceeded = null,
  // Base path the post-create navigate writes to (so a brand-new conversation
  // lands on the right surface). Chat keeps '/chat'; the Data Analyzer page
  // passes '/data-analyzer' so its first send promotes to /data-analyzer/<id>
  // instead of bouncing the user into the chat view.
  conversationBasePath = '/chat',
}) {
  // Ref to store abort controller for cancellation
  const abortControllerRef = useRef(null)
  // Failed-send descriptor for the inline retry banner. Mirrored into
  // streamErrorRef (owned by useChatMessages) so the conversation sync effect
  // doesn't wipe the orphaned optimistic bubble while a retry is offered.
  // Shape: { kind: 'network'|'server', message, content, attachments, command,
  //          options, tempId } | null
  const [streamError, setStreamError] = useState(null)

  // ── Data Analyzer live timeline (intent='data') ────────────────────────────
  // The agentic Python tool-loop streams tool_call (code) + tool_result
  // (stdout/error/artifacts) events ALONGSIDE the message_chunk prose. We
  // accumulate them here so <DataAnalysisBlock> can render the steps timeline +
  // chart/table artifacts LIVE beneath the streaming turn. On message_complete
  // the authoritative `data_artifacts` settle onto the persisted message
  // (metadata.data_artifacts), so this live state is purely for the in-flight
  // view and is cleared the moment the stream ends. Shape mirrors the persisted
  // contract: { steps:[{step,code,stdout,error}], artifacts:[<artifact>] } | null.
  const [liveDataAnalysis, setLiveDataAnalysis] = useState(null)
  // Document-extraction phase for intent='data' runs. The backend emits a
  // `data_status` SSE event ({ phase:'extracting'|'analyzing', file }) WHILE it
  // OCRs/extracts attached documents BEFORE the Python loop starts, so the
  // working placeholder can say "Reading <file>…" instead of a generic spinner.
  // Lifecycle mirrors liveDataAnalysis exactly: cleared at every send start,
  // stream end/complete/error, stop, and conversation switch.
  // Shape: { phase, file } | null.
  const [dataPhase, setDataPhase] = useState(null)
  // Always-current snapshot for callbacks (the stream handlers close over the
  // value at send time; tool events fire later). Read this in onMessageComplete
  // to settle the final timeline without re-creating handleSendMessage per tick.
  const liveDataAnalysisRef = useRef(null)
  useEffect(() => {
    liveDataAnalysisRef.current = liveDataAnalysis
  }, [liveDataAnalysis])
  const setFailure = useCallback((failure) => {
    if (streamErrorRef) streamErrorRef.current = failure
    setStreamError(failure)
  }, [streamErrorRef])

  // Switching conversations discards any pending failure (the conversationId
  // effect in useChatMessages clears the message list, bubble included).
  useEffect(() => {
    setFailure(null)
  }, [conversationId, setFailure])
  // Track the intent of the most recently sent message so the completion handler
  // can act on it even when the SSE event omits the echo.
  const lastSentIntentRef = useRef(null)

  // ── Streamed-render throttling ──────────────────────────────────────────
  // SSE delivers many small tokens; pushing each straight to `streamingContent`
  // re-parses the whole growing markdown/KaTeX/Prism tree per token → O(n²).
  // Accumulate tokens in a ref and flush to state at most once per animation
  // frame (rAF coalesces multiple tokens that land in the same frame into a
  // single parse + paint). The buffer ALWAYS holds the authoritative full text;
  // state lags by ≤1 frame. On completion the persisted `data.content` (full
  // server text) replaces the buffer, so a dropped trailing frame can never
  // truncate the final message; resetStreamBuffer() cancels any pending flush.
  const streamBufferRef = useRef('')
  const rafIdRef = useRef(null)

  const cancelStreamFlush = useCallback(() => {
    if (rafIdRef.current != null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  // Reset both the buffer and the displayed content to a known value, dropping
  // any pending flush. Used everywhere the old code did `setStreamingContent('')`.
  const resetStreamBuffer = useCallback((value = '') => {
    cancelStreamFlush()
    streamBufferRef.current = value
    setStreamingContent(value)
  }, [cancelStreamFlush, setStreamingContent])

  // Append a token to the buffer and schedule a coalesced flush.
  const appendStreamChunk = useCallback((chunk) => {
    streamBufferRef.current += chunk
    if (rafIdRef.current == null) {
      rafIdRef.current = requestAnimationFrame(() => {
        rafIdRef.current = null
        setStreamingContent(streamBufferRef.current)
      })
    }
  }, [setStreamingContent])

  // Drop any pending flush if the hook unmounts mid-stream.
  useEffect(() => cancelStreamFlush, [cancelStreamFlush])

  // Abort any in-flight stream when ChatPage truly unmounts (navigation AWAY
  // from chat). SAFE only because the route key is now section-scoped: a
  // param-only /chat → /chat/<id> change no longer unmounts, so this never
  // kills the live stream that the new-chat navigate itself triggers.
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [])

  // Genuine conversation SWITCH while a stream is in flight (sidebar click to a
  // different chat, or the New Chat button). ChatPage doesn't remount on a
  // param-only change, so without this the orphaned stream keeps `isStreaming`
  // true (blocking the destination's load in useChatMessages) and later writes
  // its completion into the switched-away view. Abort it and reset the streaming
  // state so the destination conversation can render.
  //   `prev != null` EXCLUDES the new-chat null→id promotion (onConversationCreated
  //   navigates undefined → newid): that stream MUST survive, so we never abort it.
  const prevConvForAbortRef = useRef(conversationId)
  useEffect(() => {
    const prev = prevConvForAbortRef.current
    prevConvForAbortRef.current = conversationId
    if (prev != null && prev !== conversationId) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
        setIsStreaming(false)
        setStreamingMessageId(null)
        resetStreamBuffer('')
        setMessages([])
      }
      justFinishedStreamingRef.current = false
      if (streamErrorRef) streamErrorRef.current = null
      lastSentIntentRef.current = null
      // Drop any in-flight Data Analyzer timeline — it belongs to the chat we
      // just left (the persisted artifacts ride the message into the new view).
      setLiveDataAnalysis(null)
      setDataPhase(null)
    }
  }, [conversationId, setIsStreaming, setStreamingMessageId, resetStreamBuffer, setMessages, justFinishedStreamingRef, streamErrorRef])

  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const handleSendMessage = useCallback(async (rawContent, attachments = [], command = null, options = {}) => {
    // A command MAY pin its own config (none currently do — canvas runs on the
    // picker-selected model; the backend swaps the system prompt by intent).
    const resolvedConfigId = command?.configId || selectedConfigId
    if (!resolvedConfigId) {
      toast.error(i18n.t('common:runtime.chat.selectConfig'))
      return
    }

    // A new send supersedes any pending failed attempt: drop its orphaned
    // optimistic bubble (it was never persisted) and dismiss the retry banner.
    // Retry reuses this exact path with the failed payload.
    const staleFailure = streamErrorRef?.current
    if (staleFailure) {
      setFailure(null)
      if (staleFailure.tempId) {
        setMessages(prev => prev.filter(m => m._id !== staleFailure.tempId))
      }
    }

    // Quote-embed: prefix the user's reply with the selected snippet as a
    // markdown blockquote. The `!rawContent.startsWith('> ')` guard prevents a
    // double-embed on the retry path — retry replays the already-embedded
    // `failed.content` AND `failed.options.quotedText`, so re-embedding would
    // stack a second blockquote; the guard short-circuits it.
    const quotedText = (options.quotedText || '').trim()
    const content = (quotedText && !rawContent.startsWith('> '))
      ? `> ${quotedText.replace(/\n/g, '\n> ')}\n\n${rawContent}`
      : rawContent

    const intent = command ? command.intent : null
    const webSearch = !!options.webSearch
    const webFetch = !!options.webFetch
    // 'low' | 'high' from the composer thinking switcher; anything else -> omit.
    const reasoningEffort = ['low', 'medium', 'high'].includes(options.reasoningEffort)
      ? options.reasoningEffort
      : null
    lastSentIntentRef.current = intent

    // Create the abort controller BEFORE the DLP pre-flight: Stop is reachable
    // the moment the optimistic bubble renders, so a stop during the scan must
    // abort the not-yet-started stream too (checked after the scan settles).
    const controller = new AbortController()
    abortControllerRef.current = controller

    // Optimistic update FIRST — the user's message must appear the instant Send
    // is pressed (ChatGPT behavior; also flips the empty-state layout to the
    // docked composer immediately). The DLP pre-flight below costs a network
    // round-trip (smart-scan: seconds); awaiting it before rendering made the
    // message "vanish" into a blank pause. DLP outcomes mutate this bubble in
    // place: block/dismiss → revert, redact → swap to the scrubbed preview.
    const tempUserMessage = {
      _id: `temp-${Date.now()}`,
      role: 'user',
      content,
      attachments,
      metadata: quotedText ? { quoted_text: quotedText } : undefined,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, tempUserMessage])
    setIsStreaming(true)
    resetStreamBuffer('')
    // Fresh send → clear any prior live Data Analyzer timeline. A new
    // intent='data' run repopulates it via onToolCall/onToolResult below.
    setLiveDataAnalysis(null)
    setDataPhase(null)

    const revertOptimistic = () => {
      setMessages(prev => prev.filter(m => m._id !== tempUserMessage._id))
      setIsStreaming(false)
      setStreamingMessageId(null)
      resetStreamBuffer('')
      setLiveDataAnalysis(null)
      setDataPhase(null)
      lastSentIntentRef.current = null
      // Stream ended — drop the controller so the switch-abort effect only
      // ever sees an actually-in-flight stream.
      abortControllerRef.current = null
    }

    // Swap the optimistic bubble's text for the scrubbed preview when a redact
    // path is taken. The preview is byte-identical to what the server persists,
    // so onMessageSaved still reconciles by content instead of appending a
    // second bubble.
    const swapOptimisticContent = (newContent) => {
      if (newContent == null) return
      setMessages(prev =>
        prev.map(m => (m._id === tempUserMessage._id ? { ...m, content: newContent } : m))
      )
    }

    // Pre-flight DLP scan (best-effort — never blocks user on infra failure).
    // `onDLPViolation` resolves the user's modal choice:
    //   - falsy            -> dismissed / Modify / block -> revert optimistic + abort send
    //   - { redact: true } -> "Redact & send"            -> dlp_redact
    // Stale require_confirm is a block. Never resend with dlp_confirmed.
    const dlpConfirmed = false
    let dlpRedact = false
    const dlpConfirmToken = null
    if (workspaceId && onDLPViolation) {
      try {
        const scanRes = await dlpService.scan(
          content,
          workspaceId,
          'chat',
          projectId || null,
          attachments,
        )
        const result = scanRes?.result
        if (result && result.highest_action && result.highest_action !== 'allow' && result.matches?.length) {
          // Workspace redact mode → server auto-redacts on send; skip the modal
          // entirely (frictionless) and stream with dlp_redact:true.
          if (scanRes.auto_redact) {
            toast.success(i18n.t('chat:dlp.autoRedacted', 'Sensitive info was redacted before sending'))
            dlpRedact = true
            swapOptimisticContent(scanRes?.redacted_preview ?? null)
          } else if (result.highest_action === 'warn') {
            // `warn` is advisory only — surface a non-blocking toast and fall
            // through to the normal optimistic send (parity with helper + the
            // shared useDlpConfirm hook). The blocking modal is reserved for
            // block / redact. Stale require_confirm is a block. The backend
            // never emits a server-side `warn` interruption (see onMessageError,
            // which handles dlp_blocked / dlp_confirm_required only), so this
            // advisory path lives solely in the pre-flight scan.
            toast(i18n.t('chat:dlp.warn'), { icon: 'i' })
          } else {
            // enforce mode → show modal (Redact & send works because
            // `redactable` is mode-independent). Do not continue the send
            // unless the user scrubs. A confirm decision must not unlock it.
            const decision = await onDLPViolation({
              matches: result.matches,
              highestAction: result.highest_action === 'require_confirm' ? 'block' : result.highest_action,
              text: content,
              attachments,
              redactedPreview: scanRes?.redacted_preview ?? null,
              redactable: !!scanRes?.redactable,
            })
            if (!decision?.redact) {
              revertOptimistic()
              return
            }
            dlpRedact = true
            swapOptimisticContent(scanRes?.redacted_preview ?? null)
          }
        }
      } catch (err) {
        console.error('DLP pre-flight scan failed:', err)
      }
    }

    // Stop pressed while the pre-flight was in flight — the stream never
    // started, so just drop the optimistic bubble (stop already reset the rest).
    if (controller.signal.aborted) {
      setMessages(prev => prev.filter(m => m._id !== tempUserMessage._id))
      return
    }

    const buildPayload = (confirmed, redact = false, confirmToken = null) => ({
      conversation_id: conversationId || null,
      config_id: resolvedConfigId,
      message: content,
      attachments,
      quoted_text: quotedText || undefined,
      intent,
      project_id: conversationId ? undefined : projectId,
      dlp_confirmed: confirmed || undefined,
      dlp_redact: redact || undefined,
      dlp_confirm_token: confirmToken || undefined,
      web_search: webSearch,
      web_fetch: webFetch,
      reasoning_effort: reasoningEffort || undefined,
      lang: (i18n.language || 'en').slice(0, 2).toLowerCase(),
    })

    const handlers = {
      onConversationCreated: (data) => {
        navigate(`${conversationBasePath}/${data.conversation._id}`, { replace: true })
        // A brand-new conversation row doesn't exist in the sidebar cache yet,
        // so a targeted patch can't surface it — a refetch is required. Scope
        // to `refetchType: 'active'` so only the currently-mounted sidebar list
        // refires (not every stale scoped page in cache).
        queryClient.invalidateQueries({ queryKey: ['conversations'], refetchType: 'active' })
      },
      onMessageSaved: (data) => {
        setMessages(prev => {
          if (prev.some(m => m._id === data.message._id)) return prev
          const tempIndex = prev.findIndex(m =>
            m._id.toString().startsWith('temp-') && m.content === data.message.content
          )
          if (tempIndex >= 0) {
            const newMessages = [...prev]
            newMessages[tempIndex] = data.message
            return newMessages
          }
          return [...prev, data.message]
        })

        const convId = conversationId || data.conversation_id
        if (convId) {
          queryClient.setQueryData(['conversation', convId], (old) => {
            if (!old) return old
            const exists = old.messages?.some(m => m._id === data.message._id)
            if (exists) return old
            return {
              ...old,
              messages: [...(old.messages || []), data.message]
            }
          })
        }
      },
      onMessageStart: (data) => {
        setStreamingMessageId(data.message_id)
        resetStreamBuffer('')
      },
      onMessageChunk: (data) => {
        appendStreamChunk(data.content)
      },
      // Data Analyzer: a run_python step begins — push its code as a new live
      // step (keyed by `step` so a duplicate emit updates rather than appends).
      onToolCall: (data) => {
        if (!data || data.step == null) return
        setLiveDataAnalysis((prev) => {
          const steps = prev?.steps ? [...prev.steps] : []
          const idx = steps.findIndex((s) => s.step === data.step)
          const next = { step: data.step, code: data.code ?? '', stdout: null, error: null }
          if (idx >= 0) steps[idx] = { ...steps[idx], ...next }
          else steps.push(next)
          return { steps, artifacts: prev?.artifacts || [] }
        })
      },
      // Data Analyzer: the step finished — merge stdout/error onto its step and
      // append any artifacts it produced (charts/tables render live beneath).
      onToolResult: (data) => {
        if (!data || data.step == null) return
        setLiveDataAnalysis((prev) => {
          const steps = prev?.steps ? [...prev.steps] : []
          const idx = steps.findIndex((s) => s.step === data.step)
          const patch = { stdout: data.stdout ?? null, error: data.error ?? null, done: true }
          if (idx >= 0) steps[idx] = { ...steps[idx], ...patch }
          else steps.push({ step: data.step, code: '', ...patch })
          const newArtifacts = Array.isArray(data.artifacts) ? data.artifacts : []
          return { steps, artifacts: [...(prev?.artifacts || []), ...newArtifacts] }
        })
      },
      // Data Analyzer: document extraction progress (PDF OCR etc.) emitted before
      // the Python loop starts. 'analyzing' marks the end of extraction; clear it
      // then so the working placeholder reverts to the generic analyzing state.
      onDataStatus: (data) => {
        if (!data || !data.phase) return
        if (data.phase === 'extracting') {
          setDataPhase({ phase: 'extracting', file: data.file ?? null })
        } else {
          setDataPhase(null)
        }
      },
      onMessageComplete: (data) => {
        // Settle the authoritative Data Analyzer payload onto the persisted
        // message so it survives reload (QuietMessage reads metadata.data_artifacts).
        // Prefer the server's `data_artifacts`; fall back to the live-accumulated
        // timeline if the completion event omitted it.
        const liveSnapshot = liveDataAnalysisRef.current
        const dataArtifacts =
          data.data_artifacts ||
          (liveSnapshot && (liveSnapshot.steps?.length || liveSnapshot.artifacts?.length)
            ? liveSnapshot
            : null)

        const baseMeta = data.annotations
          ? { ...(data.metadata || {}), annotations: data.annotations }
          : data.metadata
        const mergedMeta = dataArtifacts
          ? { ...(baseMeta || {}), data_artifacts: dataArtifacts, intent: 'data' }
          : baseMeta

        const newMessage = {
          _id: data.message_id,
          role: 'assistant',
          content: data.content,
          metadata: mergedMeta,
          created_at: new Date().toISOString(),
        }

        setMessages(prev => {
          const idx = prev.findIndex(m => m._id === data.message_id)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = newMessage
            return next
          }
          return [...prev, newMessage]
        })

        const convId = conversationId || data.conversation_id
        if (convId) {
          queryClient.setQueryData(['conversation', convId], (old) => {
            if (!old) return old
            const existingMessages = old.messages || []
            const idx = existingMessages.findIndex(m => m._id === data.message_id)
            if (idx >= 0) {
              const next = [...existingMessages]
              next[idx] = newMessage
              return { ...old, messages: next }
            }
            return { ...old, messages: [...existingMessages, newMessage] }
          })
        }

        const isCanvas = data.intent === 'canvas' || lastSentIntentRef.current === 'canvas'
        if (isCanvas && onCanvasIntent) {
          const fenceRe = /```(\w*)\n([\s\S]*?)```/g
          let match
          let opened = false
          while ((match = fenceRe.exec(data.content)) !== null) {
            const lang = (match[1] || 'html').toLowerCase()
            const code = match[2]
            if (isRunnableCode(lang)) {
              onCanvasIntent(parseHtmlCode(code, lang))
              opened = true
              break
            }
          }
          if (!opened) {
            toast(i18n.t('common:runtime.chat.canvasNoCode'), { icon: '⚠️' })
          }
        }

        // Scope the "skip stale-cache sync" guard to THIS conversation, so a
        // stream that finishes after the user already switched away can't block
        // the conversation now on screen (the sync effect compares this id).
        justFinishedStreamingRef.current = conversationId || data.conversation_id
        setIsStreaming(false)
        setStreamingMessageId(null)
        // Persisted message now renders via QuietMessage; drop the live buffer.
        resetStreamBuffer('')
        // Data Analyzer artifacts are now on the persisted message metadata —
        // drop the live timeline so it doesn't double-render beneath the turn.
        setLiveDataAnalysis(null)
        setDataPhase(null)
        lastSentIntentRef.current = null
        abortControllerRef.current = null

        // Bump this conversation to the top of the sidebar list in place rather
        // than refetching every loaded page. The detail cache is already kept
        // fresh by the setQueryData above; the sidebar only needs the row's
        // recency fields updated + reordered to the front. `last_message_at`
        // drives the date-bucket sort, so patch it (and `updated_at`) to now.
        if (convId) {
          const nowIso = new Date().toISOString()
          const found = touchConversationInCache(queryClient, convId, {
            last_message_at: nowIso,
            updated_at: nowIso,
          })
          // Cache miss only: the row is filtered out of the cached pages (e.g.
          // an active search box) — fall back to a scoped refetch so it can
          // resurface, without touching non-mounted scoped pages.
          if (!found) {
            queryClient.invalidateQueries({ queryKey: ['conversations'], refetchType: 'active' })
          }
        }
      },
      onMessageError: async (data) => {
        // Budget/credit ceiling reached (402) — hard block, no resend. Revert
        // the optimistic user bubble + clear the stream state (mirrors the DLP
        // dismissal path) and open the budget modal via the page handler.
        if (onBudgetExceeded && onBudgetExceeded(data)) {
          revertOptimistic()
          return
        }
        // Defensive fallback for backend DLP rejection (pre-flight skipped/failed).
        // `dlp_blocked` and stale `dlp_confirm_required` both stop the send.
        // `warn` is advisory and handled as a toast in pre-flight above.
        // Resubmit only when the user scrubs. Never replay with dlp_confirmed.
        if ((data.code === 'dlp_blocked' || data.code === 'dlp_confirm_required') && Array.isArray(data.matches) && onDLPViolation) {
          revertOptimistic()
          const rawAction = data.highest_action || 'block'
          const decision = await onDLPViolation({
            matches: data.matches,
            highestAction: rawAction === 'require_confirm' || data.code === 'dlp_confirm_required' ? 'block' : rawAction,
            text: content,
            attachments,
            redactedPreview: data.redacted_preview ?? null,
            redactable: !!data.redactable,
          })
          // Redaction neutralizes a block, so it applies to both rejection codes.
          if (decision && decision.redact) {
            // Render the scrubbed preview optimistically, never the raw text.
            const redactedTemp = { ...tempUserMessage, content: data.redacted_preview ?? tempUserMessage.content }
            setMessages(prev => [...prev, redactedTemp])
            setIsStreaming(true)
            resetStreamBuffer('')
            try {
              // Fresh controller: the original stream's promise already settled
              // (this fired from its !response.ok branch), so its signal is dead.
              const reController = new AbortController()
              abortControllerRef.current = reController
              await streamChat(buildPayload(false, true), handlers, reController.signal)
            } catch (e) {
              revertOptimistic()
            }
          }
          return
        }
        // Connection drop / upstream failure. Keep the optimistic bubble and
        // surface an inline retry banner instead of a transient toast — the
        // user must be able to resend without retyping, in the SAME chat.
        const offline = typeof navigator !== 'undefined' && navigator.onLine === false
        const isNetwork =
          offline || /fetch|network|timed out|connection|load failed/i.test(data.error || '')
        setFailure({
          kind: isNetwork ? 'network' : 'server',
          message: data.error || '',
          content,
          attachments,
          command,
          options,
          tempId: tempUserMessage._id,
        })
        setIsStreaming(false)
        setStreamingMessageId(null)
        resetStreamBuffer('')
        setLiveDataAnalysis(null)
        setDataPhase(null)
        lastSentIntentRef.current = null
        abortControllerRef.current = null
      },
      onTitleUpdated: (data) => {
        // Sidebar conversation lists store infinite-query shape under scoped
        // ['conversations', ...] keys — patch every matching cache entry.
        queryClient.setQueriesData({ queryKey: ['conversations'] }, (old) => {
          if (!old?.pages) return old
          return {
            ...old,
            pages: old.pages.map((p) => ({
              ...p,
              conversations: (p.conversations || []).map((c) =>
                c._id === data.conversation_id ? { ...c, title: data.title } : c
              ),
            })),
          }
        })
        queryClient.setQueryData(['conversation', data.conversation_id], (old) => {
          if (!old) return old
          return {
            ...old,
            conversation: { ...old.conversation, title: data.title }
          }
        })
      },
    }

    try {
      await streamChat(buildPayload(dlpConfirmed, dlpRedact, dlpConfirmToken), handlers, controller.signal)
    } catch (error) {
      setIsStreaming(false)
      setStreamingMessageId(null)
      resetStreamBuffer('')
      setLiveDataAnalysis(null)
      setDataPhase(null)
      lastSentIntentRef.current = null
      abortControllerRef.current = null
    }
  }, [
    conversationId,
    selectedConfigId,
    navigate,
    queryClient,
    setMessages,
    setStreamingContent,
    setStreamingMessageId,
    setIsStreaming,
    justFinishedStreamingRef,
    onCanvasIntent,
    projectId,
    workspaceId,
    onDLPViolation,
    onBudgetExceeded,
    appendStreamChunk,
    resetStreamBuffer,
    setFailure,
    streamErrorRef,
    conversationBasePath,
  ])

  // Resend the failed payload through the normal send path (which clears the
  // banner + stale bubble first).
  const retryFailedSend = useCallback(() => {
    const failed = streamErrorRef?.current
    if (!failed) return
    handleSendMessage(failed.content, failed.attachments, failed.command, failed.options)
  }, [handleSendMessage, streamErrorRef])

  // Dismiss the banner and drop the undelivered bubble. Callers should restore
  // the text into the composer (ChatPage does, via composerRestore) so nothing
  // the user typed is lost.
  const dismissStreamError = useCallback(() => {
    const failed = streamErrorRef?.current
    if (!failed) return
    setFailure(null)
    if (failed.tempId) {
      setMessages(prev => prev.filter(m => m._id !== failed.tempId))
    }
  }, [setFailure, setMessages, streamErrorRef])

  // Drop the assistant turn immediately, then stream a replacement. Stop uses
  // the same abort controller as a normal send.
  const handleRegenerateMessage = useCallback(async (messageId, configId = null) => {
    let removed = null
    setMessages(prev => {
      const idx = prev.findIndex(m => m._id === messageId)
      if (idx < 0) return prev
      removed = prev.slice(idx)
      return prev.slice(0, idx)
    })
    if (!removed) return

    if (conversationId) {
      queryClient.setQueryData(['conversation', conversationId], (old) => {
        if (!old?.messages) return old
        const idx = old.messages.findIndex(m => m._id === messageId)
        if (idx < 0) return old
        return { ...old, messages: old.messages.slice(0, idx) }
      })
    }

    const restore = () => {
      setMessages(prev => [...prev, ...removed])
      if (conversationId) {
        queryClient.setQueryData(['conversation', conversationId], (old) => {
          if (!old?.messages) return old
          const ids = new Set(old.messages.map(m => m._id))
          const extra = removed.filter(m => !ids.has(m._id))
          return extra.length ? { ...old, messages: [...old.messages, ...extra] } : old
        })
      }
      setIsStreaming(false)
      setStreamingMessageId(null)
      resetStreamBuffer('')
      abortControllerRef.current = null
    }

    setIsStreaming(true)
    resetStreamBuffer('')
    const controller = new AbortController()
    abortControllerRef.current = controller
    let settled = false
    let started = false

    await streamRegenerate(messageId, configId ? { config_id: configId } : {}, {
      onMessageStart: (data) => {
        started = true
        setStreamingMessageId(data.message_id)
        resetStreamBuffer('')
      },
      onMessageChunk: (data) => {
        if (data?.content) appendStreamChunk(data.content)
      },
      onMessageComplete: (data) => {
        settled = true
        const newMessage = {
          _id: data.message_id,
          role: 'assistant',
          content: data.content || '',
          metadata: data.annotations
            ? { ...(data.metadata || {}), annotations: data.annotations }
            : (data.metadata || {}),
          created_at: new Date().toISOString(),
        }
        setMessages(prev => {
          const idx = prev.findIndex(m => m._id === data.message_id)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = newMessage
            return next
          }
          return [...prev, newMessage]
        })
        const convId = conversationId || data.conversation_id
        if (convId) {
          queryClient.setQueryData(['conversation', convId], (old) => {
            if (!old) return old
            const msgs = old.messages || []
            const idx = msgs.findIndex(m => m._id === data.message_id)
            const next = idx >= 0
              ? msgs.map((m, i) => (i === idx ? newMessage : m))
              : [...msgs, newMessage]
            return { ...old, messages: next }
          })
        }
        if (justFinishedStreamingRef) justFinishedStreamingRef.current = convId
        setIsStreaming(false)
        setStreamingMessageId(null)
        resetStreamBuffer('')
        abortControllerRef.current = null
      },
      onMessageError: (data) => {
        if (settled) return
        settled = true
        // Before message_start the server has not deleted the row (4xx / network).
        // After it, the old reply is already gone.
        if (!started) restore()
        else {
          setIsStreaming(false)
          setStreamingMessageId(null)
          resetStreamBuffer('')
          abortControllerRef.current = null
        }
        if (data?.code === 'budget_exceeded' || data?.code === 'insufficient_credits') {
          onBudgetExceeded?.(data)
          return
        }
        toast.error(chatActionError(data?.error, 'common:runtime.chat.regenerateFailed'))
      },
    }, controller.signal)

    if (!settled && controller.signal.aborted) {
      // Stop already committed the partial text.
      settled = true
    }
  }, [
    appendStreamChunk,
    conversationId,
    justFinishedStreamingRef,
    onBudgetExceeded,
    queryClient,
    resetStreamBuffer,
    setIsStreaming,
    setMessages,
    setStreamingMessageId,
  ])

  const handleStopGeneration = useCallback(async (messageId) => {
    // Buffer is the full text so far (state can lag one frame). Abort drops
    // the SSE body, so message_complete never lands — keep this copy.
    const partial = streamBufferRef.current || ''
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    if (partial) {
      const partialMessage = {
        _id: messageId || `stopped-${Date.now()}`,
        role: 'assistant',
        content: partial,
        metadata: { finish_reason: 'cancelled' },
        created_at: new Date().toISOString(),
      }
      setMessages(prev => {
        if (messageId) {
          const idx = prev.findIndex(m => m._id === messageId)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], content: partial, metadata: { ...(next[idx].metadata || {}), finish_reason: 'cancelled' } }
            return next
          }
        }
        return [...prev, partialMessage]
      })
      if (conversationId) {
        queryClient.setQueryData(['conversation', conversationId], (old) => {
          if (!old) return old
          const msgs = old.messages || []
          const idx = messageId ? msgs.findIndex(m => m._id === messageId) : -1
          const nextMsgs = idx >= 0
            ? msgs.map((m, i) => (i === idx ? { ...m, content: partial } : m))
            : [...msgs, partialMessage]
          return { ...old, messages: nextMsgs }
        })
      }
      if (justFinishedStreamingRef) justFinishedStreamingRef.current = conversationId
    }

    if (messageId) {
      try {
        await cancelChat(messageId)
      } catch (error) {
        console.error('Cancel error:', error)
      }
    }

    setIsStreaming(false)
    setStreamingMessageId(null)
    resetStreamBuffer('')
    // Partial Data Analyzer run — no message_complete will fire, so drop the
    // orphaned live timeline (nothing persisted it to a message).
    setLiveDataAnalysis(null)
    setDataPhase(null)
  }, [conversationId, justFinishedStreamingRef, queryClient, resetStreamBuffer, setIsStreaming, setMessages, setStreamingMessageId])

  return {
    handleSendMessage,
    handleRegenerateMessage,
    handleStopGeneration,
    streamError,
    retryFailedSend,
    dismissStreamError,
    // Live Data Analyzer timeline (intent='data') — ChatPage threads this into
    // ChatWindow so <DataAnalysisBlock> renders the steps + artifacts beside the
    // streaming turn before the persisted message takes over.
    liveDataAnalysis,
    // Document-extraction phase ({ phase, file } | null) for intent='data' runs;
    // drives the "Reading <file>…" working placeholder in ChatWindow.
    dataPhase,
  }
}
