import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Loader2, Plus, Sparkles, History, Search, WifiOff, Paperclip, ArrowUp, Globe,
} from 'lucide-react'
import { chatService } from '../../services/chatService'
import { streamAgent, streamAgentClarify } from '../../services/agentService'
import { useProject } from '../../context/ProjectContext'
import ChatWindow from '../../components/chat/ChatWindow'
import { Button } from '../../components/ui/button'
import { IconTile } from '../../components/ui/icon-tile'
import HeaderSlot from '../../components/layout/HeaderSlot'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { Input } from '../../components/ui/input'
import { Textarea } from '../../components/ui/textarea'
import { Sheet, SheetContent, SheetTitle } from '../../components/ui/sheet'
import ConversationRow from '../../components/layout/sidebar/ConversationRow'
import { useConfirmDelete } from '../../hooks/useConfirmDelete'
import { useOnlineStatus } from '../../hooks/useOnlineStatus'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { useBudgetBlock } from '../../hooks/useBudgetBlock'
import { useDlpConfirm } from '../../hooks/useDlpConfirm'
import { cn } from '@/lib/utils'
import { glassSx, GLASS_CLASS } from '@/theme/glass'
import useAgentConversations from '../../hooks/useAgentConversations'
import AgentClarifyCard from './components/AgentClarifyCard'
import AgentEmptyState from './components/AgentEmptyState'
import AgentToolTimeline, { phaseLabel } from './components/AgentToolTimeline'
import AgentArtifacts from './components/AgentArtifacts'

function isPythonStep(s) {
  return s?.name === 'run_python' || (s?.code != null && String(s.code).trim() !== '')
}

function nonImageArts(arts) {
  return (Array.isArray(arts) ? arts : []).filter((a) => a?.type !== 'image')
}

/**
 * All-in-one router agent surface — fixed orchestrator, tool loop, clarify card.
 */
export default function AgentPage() {
  const { t, i18n } = useTranslation(['agent', 'chat', 'layout', 'common'])
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { currentProject } = useProject()
  const projectId = currentProject?._id || null
  const isOnline = useOnlineStatus()
  const isLg = useMediaQuery('(min-width: 1024px)')
  const { confirm, confirmDialog } = useConfirmDelete()
  const { handleBudgetError, budgetModal } = useBudgetBlock()
  const { scan: dlpScan, dlpModal } = useDlpConfirm({ source: 'agent' })

  const [mobileRailOpen, setMobileRailOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [composerText, setComposerText] = useState('')
  const [attachments, setAttachments] = useState([])
  const [clarify, setClarify] = useState(null) // { questions, messageId }
  const [liveArtifacts, setLiveArtifacts] = useState([])
  const [toolSteps, setToolSteps] = useState([])
  const [agentPhase, setAgentPhase] = useState(null) // thinking | generating_image | …
  const [streamError, setStreamError] = useState(null)
  const abortRef = useRef(null)
  const fileInputRef = useRef(null)
  // Bumps on each send/switch so late SSE from a dead stream can't re-stick UI.
  const streamGenRef = useRef(0)
  // Chat-parity: skip RQ overwrite for ~1s after stream ends (stale cache).
  const justFinishedStreamingRef = useRef(null)
  // Failed-send marker — keep optimistic bubble until retry/dismiss.
  const streamErrorRef = useRef(null)
  // Always-current conversation id for SSE handlers (new-chat null→id).
  const conversationIdRef = useRef(conversationId)
  conversationIdRef.current = conversationId
  // Last live clarify snapshot — restore card if resume stream fails after clear.
  const clarifyRef = useRef(null)
  // Live flag for composer/ChatWindow — ref so handlers don't close over stale state.
  const isStreamingRef = useRef(false)
  // Last send payload for Retry (text + attachments + conversation snapshot).
  const lastSendRef = useRef(null)
  // Live tool/artifact snapshots for settling into message_complete metadata.
  const toolStepsRef = useRef([])
  const liveArtifactsRef = useRef([])
  // True when stream reached a terminal SSE (complete / clarify / error).
  // Used to surface silent proxy drops after clarify as a Retry banner.
  const terminalEventRef = useRef(false)

  const endStreamChrome = useCallback((convIdForGuard = null, { keepTools = false } = {}) => {
    isStreamingRef.current = false
    setIsStreaming(false)
    setStreamingContent('')
    setAgentPhase(null)
    if (!keepTools) {
      setToolSteps([])
      toolStepsRef.current = []
    }
    if (convIdForGuard) {
      justFinishedStreamingRef.current = convIdForGuard
    }
  }, [])

  const rail = useAgentConversations()

  const {
    data: conversationData,
    isLoading: isLoadingConversation,
    isError: isConversationError,
    refetch: refetchConversation,
  } = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => chatService.getConversation(conversationId),
    enabled: !!conversationId,
    staleTime: 30000,
  })

  // Load messages when conversation changes — NEVER clobber mid-stream
  // (new-chat null→id promote navigates while SSE still open).
  const prevConvForSyncRef = useRef(conversationId)
  useEffect(() => {
    const prevId = prevConvForSyncRef.current
    prevConvForSyncRef.current = conversationId
    const isRealSwitch = prevId != null && prevId !== conversationId

    if (isRealSwitch) {
      justFinishedStreamingRef.current = null
      streamErrorRef.current = null
      streamGenRef.current += 1
      isStreamingRef.current = false
      setIsStreaming(false)
    }

    if (isStreaming || isStreamingRef.current) return
    // Failed send: keep optimistic bubble (chat streamErrorRef contract).
    if (streamErrorRef.current) return
    // Just finished stream on THIS conv — RQ may still be pre-stream snapshot.
    if (
      justFinishedStreamingRef.current &&
      justFinishedStreamingRef.current === conversationId
    ) {
      setTimeout(() => {
        if (justFinishedStreamingRef.current === conversationId) {
          justFinishedStreamingRef.current = null
        }
      }, 1000)
      return
    }

    if (!conversationId) {
      setMessages([])
      setClarify(null)
      clarifyRef.current = null
      setLiveArtifacts([])
      setToolSteps([])
      setStreamingContent('')
      return
    }
    const msgs = conversationData?.messages || conversationData?.conversation?.messages
    if (Array.isArray(msgs)) {
      setMessages(msgs)
      // Restore pending clarify from server — only APPLY when present.
      // Never wipe a live SSE clarify with stale cache that lacks pending_clarify
      // (that was the "card vanishes until refresh" bug).
      const last = [...msgs].reverse().find((m) => m.role === 'assistant')
      const pending = last?.metadata?.pending_clarify
      if (pending?.questions?.length) {
        const next = {
          questions: pending.questions,
          messageId: last._id || last.id,
        }
        setClarify(next)
        clarifyRef.current = next
      } else if (isRealSwitch) {
        setClarify(null)
        clarifyRef.current = null
      }
      // else: keep live clarify (if any); send/submit/newAgent clear explicitly
    } else if (conversationData && !isLoadingConversation) {
      setMessages([])
    } else if (!conversationId || isRealSwitch) {
      setMessages([])
    }
  }, [conversationId, conversationData, isLoadingConversation, isStreaming])

  // Abort only on REAL conversation switch (A→B). Exclude new-chat null→id
  // promote (onConversationCreated navigate) — that stream MUST survive
  // (same contract as useChatStream).
  const prevConvForAbortRef = useRef(conversationId)
  useEffect(() => {
    const prev = prevConvForAbortRef.current
    prevConvForAbortRef.current = conversationId
    if (prev != null && prev !== conversationId) {
      streamGenRef.current += 1
      abortRef.current?.abort?.()
      abortRef.current = null
      endStreamChrome()
      setLiveArtifacts([])
      setClarify(null)
      clarifyRef.current = null
      setStreamError(null)
      streamErrorRef.current = null
    }
  }, [conversationId, endStreamChrome])

  // Unmount only (leave /agent entirely)
  useEffect(() => {
    return () => {
      abortRef.current?.abort?.()
    }
  }, [])

  // Empty-state starters fill composer (fill-not-send).
  useEffect(() => {
    const onInsert = (e) => {
      const text = e?.detail?.text
      if (typeof text === 'string') setComposerText(text)
    }
    window.addEventListener('chat:composer-insert', onInsert)
    return () => window.removeEventListener('chat:composer-insert', onInsert)
  }, [])

  const invalidateLists = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }, [queryClient])

  const resolveConvId = useCallback(
    (d) => d?.conversation_id || conversationIdRef.current || null,
    [],
  )

  const bindHandlers = useCallback(
    (streamGen, handlersExtra = {}) => {
      const alive = () => streamGenRef.current === streamGen
      terminalEventRef.current = false
      return {
        onConversationCreated: (d) => {
          if (!alive()) return
          const id = d?.conversation?._id || d?.conversation?.id
          if (id) {
            navigate(`/agent/${id}`, { replace: true })
            invalidateLists()
          }
        },
        onMessageSaved: (d) => {
          if (!alive() || !d?.message) return
          const serverId = d.message._id || d.message.id
          setMessages((prev) => {
            if (prev.some((m) => (m._id || m.id) === serverId)) return prev
            // Replace optimistic temp bubble (chat parity) — never append a twin.
            const tempIndex = prev.findIndex((m) => {
              const id = String(m._id || m.id || '')
              return (
                m.role === 'user' &&
                (id.startsWith('temp-') || id.startsWith('tmp-')) &&
                (m.content || '') === (d.message.content || '')
              )
            })
            if (tempIndex >= 0) {
              const next = [...prev]
              next[tempIndex] = d.message
              return next
            }
            // Fallback: replace any leading optimistic user without content match
            const anyTemp = prev.findIndex((m) => {
              const id = String(m._id || m.id || '')
              return m.role === 'user' && (id.startsWith('temp-') || id.startsWith('tmp-'))
            })
            if (anyTemp >= 0) {
              const next = [...prev]
              next[anyTemp] = d.message
              return next
            }
            return [...prev, d.message]
          })
          const convId = resolveConvId(d)
          if (convId) {
            queryClient.setQueryData(['conversation', convId], (old) => {
              if (!old) return old
              const list = old.messages || old.conversation?.messages
              if (!Array.isArray(list)) return old
              if (list.some((m) => (m._id || m.id) === serverId)) return old
              const messages = [...list, d.message]
              if (old.messages) return { ...old, messages }
              return {
                ...old,
                conversation: { ...old.conversation, messages },
              }
            })
          }
        },
        onMessageStart: (d) => {
          if (!alive()) return
          setStreamingContent('')
          isStreamingRef.current = true
          setIsStreaming(true)
          if (!d?.resumed) {
            setLiveArtifacts([])
            setToolSteps([])
          }
        },
        onMessageChunk: (d) => {
          if (!alive()) return
          if (d?.content) setStreamingContent((c) => c + d.content)
        },
        onMessageComplete: (d) => {
          if (!alive()) return
          terminalEventRef.current = true
          const content = d?.content || ''
          const mid = d?.message_id
          const arts = d?.artifacts || liveArtifactsRef.current || []
          const steps = d?.steps || toolStepsRef.current || []
          const annotations = d?.annotations || null
          const usedWeb = Boolean(d?.used_web)
          const pythonSteps = steps.filter(isPythonStep)
          const row = {
            _id: mid,
            role: 'assistant',
            content,
            metadata: {
              intent: 'agent',
              agent_artifacts: arts,
              agent_steps: steps,
              annotations: annotations || undefined,
              used_web: usedWeb,
              data_artifacts: {
                steps: pythonSteps,
                artifacts: nonImageArts(arts),
              },
              pending_clarify: null,
            },
          }
          setMessages((prev) => {
            const idx = prev.findIndex((m) => (m._id || m.id) === mid)
            if (idx >= 0) {
              const next = [...prev]
              next[idx] = { ...next[idx], ...row }
              return next
            }
            return [...prev, row]
          })
          // Full answer landed — drop typing chrome; tools settled on message.
          const convId = resolveConvId(d)
          endStreamChrome(convId)
          setLiveArtifacts([])
          liveArtifactsRef.current = []
          setClarify(null)
          clarifyRef.current = null
          if (convId) {
            queryClient.setQueryData(['conversation', convId], (old) => {
              if (!old) return old
              const list = old.messages || old.conversation?.messages
              if (!Array.isArray(list)) return old
              const idx = list.findIndex((m) => (m._id || m.id) === mid)
              const messages =
                idx >= 0
                  ? list.map((m, i) => (i === idx ? { ...m, ...row } : m))
                  : [...list, row]
              if (old.messages) return { ...old, messages }
              return {
                ...old,
                conversation: { ...old.conversation, messages },
              }
            })
            queryClient.invalidateQueries({ queryKey: ['conversation', convId] })
          }
        },
        onToolCall: (d) => {
          if (!alive()) return
          setToolSteps((s) => {
            const next = [...s, { ...d, status: 'running' }]
            toolStepsRef.current = next
            return next
          })
          if (d?.name === 'generate_image') setAgentPhase('generating_image')
          else if (d?.name === 'ask_user') setAgentPhase('asking')
          else if (d?.name === 'web_search') setAgentPhase('web_search')
          else if (d?.name === 'web_fetch') setAgentPhase('web_fetch')
          else if (d?.name) setAgentPhase('tool')
        },
        onToolResult: (d) => {
          if (!alive()) return
          setToolSteps((s) => {
            const next = s.map((step) =>
              step.step === d.step
                ? { ...step, ...d, status: d.error ? 'error' : 'done' }
                : step,
            )
            toolStepsRef.current = next
            return next
          })
          if (Array.isArray(d?.artifacts)) {
            setLiveArtifacts((a) => {
              const next = [...a, ...d.artifacts]
              liveArtifactsRef.current = next
              return next
            })
          }
          // Image already on screen — show "finishing" not bare thinking dots.
          if (d?.name === 'generate_image' && !d?.error) setAgentPhase('finishing')
          else if (d?.name === 'generate_image') setAgentPhase('thinking')
        },
        onStatus: (d) => {
          if (!alive()) return
          if (d?.phase) setAgentPhase(d.phase)
          // Synthetic tool chips when server web tools surface as status only.
          if (d?.phase === 'web_search' || d?.phase === 'web_fetch') {
            setToolSteps((s) => {
              if (s.some((x) => x.name === d.phase && x.status === 'running')) return s
              const next = [
                ...s,
                {
                  step: s.length + 1,
                  name: d.phase,
                  status: 'running',
                  synthetic: true,
                },
              ]
              toolStepsRef.current = next
              return next
            })
          } else if (d?.phase === 'thinking' || d?.phase === 'generating_image') {
            setToolSteps((s) => {
              const next = s.map((x) =>
                x.synthetic && x.status === 'running' ? { ...x, status: 'done' } : x,
              )
              toolStepsRef.current = next
              return next
            })
          }
        },
        onDataStatus: (d) => {
          if (!alive()) return
          if (d?.phase === 'extracting') setAgentPhase('extracting')
        },
        onArtifact: (d) => {
          if (!alive() || !d) return
          setLiveArtifacts((a) => {
            const next = [...a, d]
            liveArtifactsRef.current = next
            return next
          })
        },
        onClarify: (d) => {
          if (!alive()) return
          terminalEventRef.current = true
          const questions = d?.questions || []
          const messageId = d?.message_id
          const nextClarify = { questions, messageId }
          setClarify(nextClarify)
          clarifyRef.current = nextClarify
          const convId = resolveConvId(d)
          endStreamChrome(convId)
          // Persist assistant pause row so load-effect can restore (not wipe).
          const row = {
            _id: messageId,
            role: 'assistant',
            content: '',
            metadata: {
              intent: 'agent',
              finish_reason: 'clarify',
              pending_clarify: { questions },
              agent_artifacts: liveArtifactsRef.current || [],
              agent_steps: toolStepsRef.current || [],
            },
          }
          setMessages((prev) => {
            const idx = prev.findIndex((m) => (m._id || m.id) === messageId)
            if (idx >= 0) {
              const next = [...prev]
              next[idx] = {
                ...next[idx],
                ...row,
                metadata: { ...(next[idx].metadata || {}), ...row.metadata },
              }
              return next
            }
            return [...prev, row]
          })
          if (convId) {
            queryClient.setQueryData(['conversation', convId], (old) => {
              if (!old) return old
              const list = old.messages || old.conversation?.messages
              if (!Array.isArray(list)) return old
              const idx = list.findIndex((m) => (m._id || m.id) === messageId)
              const messages =
                idx >= 0
                  ? list.map((m, i) =>
                      i === idx
                        ? {
                            ...m,
                            ...row,
                            metadata: { ...(m.metadata || {}), ...row.metadata },
                          }
                        : m,
                    )
                  : [...list, row]
              if (old.messages) return { ...old, messages }
              return {
                ...old,
                conversation: { ...old.conversation, messages },
              }
            })
            queryClient.invalidateQueries({ queryKey: ['conversation', convId] })
          }
        },
        onDone: (d) => {
          if (!alive()) return
          // done after clarify/ok is terminal; clarify handler already set flag.
          if (d?.status === 'ok' || d?.status === 'clarify') {
            terminalEventRef.current = true
          }
          // Always end typing chrome — clarify path already did; ok idempotent.
          endStreamChrome(resolveConvId(d))
          invalidateLists()
        },
        onError: (err) => {
          if (!alive()) return
          terminalEventRef.current = true
          // Budget modal still needs isStreaming cleared or send stays locked.
          endStreamChrome(conversationIdRef.current)
          if (handleBudgetError(err)) return
          const msg = err?.error || err?.message || 'Stream failed'
          setStreamError(msg)
          streamErrorRef.current = msg
        },
        onAbort: () => {
          if (!alive()) return
          endStreamChrome(conversationIdRef.current)
        },
        onTitleUpdated: () => {
          if (!alive()) return
          invalidateLists()
        },
        ...handlersExtra,
      }
    },
    [navigate, invalidateLists, queryClient, handleBudgetError, resolveConvId, endStreamChrome],
  )

  const runSend = useCallback(
    async ({ text, files, convId }) => {
      if ((!text && !files?.length) || isStreamingRef.current || clarifyRef.current) return
      if (!isOnline) return

      setStreamError(null)
      streamErrorRef.current = null
      lastSendRef.current = { text, files: files || [], convId: convId || null }

      const tempId = `temp-${Date.now()}`
      setMessages((prev) => [
        ...prev,
        {
          _id: tempId,
          role: 'user',
          content: text,
          attachments: files || [],
        },
      ])
      const streamGen = ++streamGenRef.current
      isStreamingRef.current = true
      setIsStreaming(true)
      setClarify(null)
      clarifyRef.current = null
      setLiveArtifacts([])
      liveArtifactsRef.current = []
      setToolSteps([])
      toolStepsRef.current = []

      const controller = new AbortController()
      abortRef.current = controller

      const body = {
        message: text,
        attachments: files || [],
        conversation_id: convId || conversationIdRef.current || null,
        project_id: projectId,
        lang: i18n.language,
      }

      try {
        // Attachments must join FE scan text so confirm_token HMAC matches BE.
        const dlp = await dlpScan(text, files || [])
        if (dlp === null) {
          setMessages((prev) => prev.filter((m) => m._id !== tempId))
          setComposerText(text)
          setAttachments(files || [])
          if (streamGenRef.current === streamGen) endStreamChrome()
          return
        }
        const dlpExtras = {}
        if (dlp?.confirmed) {
          dlpExtras.dlp_confirmed = true
          if (dlp.confirm_token) dlpExtras.dlp_confirm_token = dlp.confirm_token
        }
        if (dlp?.redact) dlpExtras.dlp_redact = true

        await streamAgent(
          { ...body, ...dlpExtras },
          bindHandlers(streamGen),
          controller.signal,
        )
        // Silent drop (proxy kill / worker death) — no complete/clarify/error.
        if (
          streamGenRef.current === streamGen &&
          !terminalEventRef.current &&
          !controller.signal.aborted
        ) {
          const msg = t('streamDropped', {
            defaultValue:
              'Connection dropped before the agent finished. Retry — image work may have been interrupted.',
          })
          setStreamError(msg)
          streamErrorRef.current = msg
        }
      } catch (err) {
        if (err?.name === 'AbortError') return
        if (handleBudgetError(err?.response?.data || err)) {
          if (streamGenRef.current === streamGen) endStreamChrome(conversationIdRef.current)
          return
        }
        const msg = err?.message || 'Failed to send'
        setStreamError(msg)
        streamErrorRef.current = msg
      } finally {
        if (streamGenRef.current === streamGen) {
          endStreamChrome(conversationIdRef.current)
          if (abortRef.current === controller) abortRef.current = null
        }
      }
    },
    [isOnline, projectId, i18n.language, dlpScan, bindHandlers, handleBudgetError, endStreamChrome, t],
  )

  const handleSend = useCallback(async () => {
    const text = composerText.trim()
    if ((!text && !attachments.length) || isStreaming || clarify) return
    if (!isOnline) return
    setComposerText('')
    const files = attachments
    setAttachments([])
    await runSend({ text, files, convId: conversationId || null })
  }, [
    composerText,
    attachments,
    isStreaming,
    clarify,
    isOnline,
    conversationId,
    runSend,
  ])

  const handleClarifySubmit = useCallback(
    async (answers) => {
      if (!conversationId || isStreaming) return
      // Snapshot so a failed resume can put the card back.
      const prior = clarifyRef.current || clarify
      setClarify(null)
      clarifyRef.current = null
      // Stash for Retry after a silent drop post-answer.
      lastSendRef.current = {
        kind: 'clarify',
        answers,
        prior,
        convId: conversationId,
      }
      const streamGen = ++streamGenRef.current
      isStreamingRef.current = true
      setIsStreaming(true)
      setStreamError(null)
      streamErrorRef.current = null
      setLiveArtifacts([])
      liveArtifactsRef.current = []
      setToolSteps([])
      toolStepsRef.current = []
      const controller = new AbortController()
      abortRef.current = controller
      try {
        // DLP on clarify answers (BE gates the same text).
        const answerBlob = Object.values(answers || {})
          .map((v) => (typeof v === 'string' ? v : Array.isArray(v) ? v.join(', ') : String(v ?? '')))
          .filter(Boolean)
          .join('\n')
        const dlp = await dlpScan(answerBlob)
        if (dlp === null) {
          setClarify(prior)
          clarifyRef.current = prior
          if (streamGenRef.current === streamGen) endStreamChrome(conversationId)
          return
        }
        const dlpExtras = {}
        if (dlp?.confirmed) {
          dlpExtras.dlp_confirmed = true
          if (dlp.confirm_token) dlpExtras.dlp_confirm_token = dlp.confirm_token
        }
        if (dlp?.redact) dlpExtras.dlp_redact = true

        await streamAgentClarify(
          conversationId,
          answers,
          bindHandlers(streamGen), // real onClarify — second pause must show card
          controller.signal,
          dlpExtras,
        )
        // Silent drop after clarify answer (proxy / worker) — no complete.
        if (
          streamGenRef.current === streamGen &&
          !terminalEventRef.current &&
          !controller.signal.aborted
        ) {
          const msg = t('streamDropped', {
            defaultValue:
              'Connection dropped before the agent finished. Retry — image work may have been interrupted.',
          })
          setStreamError(msg)
          streamErrorRef.current = msg
          if (prior?.questions?.length) {
            setClarify(prior)
            clarifyRef.current = prior
          }
        } else if (
          streamErrorRef.current &&
          prior?.questions?.length &&
          !clarifyRef.current?.questions?.length
        ) {
          // Explicit error path: restore card if no new clarify.
          setClarify(prior)
          clarifyRef.current = prior
        }
      } catch (err) {
        if (err?.name === 'AbortError') return
        if (handleBudgetError(err?.response?.data || err)) {
          if (streamGenRef.current === streamGen) endStreamChrome(conversationId)
          return
        }
        const msg = err?.message || 'Failed to continue'
        setStreamError(msg)
        streamErrorRef.current = msg
        if (prior?.questions?.length) {
          setClarify(prior)
          clarifyRef.current = prior
        }
      } finally {
        if (streamGenRef.current === streamGen) {
          endStreamChrome(conversationId)
          if (abortRef.current === controller) abortRef.current = null
        }
      }
    },
    [conversationId, isStreaming, bindHandlers, handleBudgetError, clarify, endStreamChrome, t, dlpScan],
  )

  const handleRetry = useCallback(async () => {
    const last = lastSendRef.current
    if (!last || isStreaming) return
    setStreamError(null)
    streamErrorRef.current = null
    if (last.kind === 'clarify' && last.answers) {
      await handleClarifySubmit(last.answers)
      return
    }
    setMessages((prev) =>
      prev.filter((m) => {
        const id = String(m._id || m.id || '')
        return !(m.role === 'user' && (id.startsWith('temp-') || id.startsWith('tmp-')))
      }),
    )
    await runSend({
      text: last.text || '',
      files: last.files || [],
      convId: conversationId || last.convId || null,
    })
  }, [isStreaming, conversationId, runSend, handleClarifySubmit])

  const handleFilePick = useCallback(async (e) => {
    const fileList = Array.from(e.target.files || [])
    e.target.value = ''
    if (!fileList.length) return
    for (const file of fileList) {
      try {
        const upload = await chatService.uploadFile(file)
        if (upload) {
          setAttachments((prev) => [
            ...prev,
            {
              upload_id: upload._id || upload.id,
              original_name: upload.original_name || file.name,
              mime_type: upload.mime_type || file.type,
              size: upload.size || file.size,
            },
          ])
        }
      } catch {
        /* toast optional */
      }
    }
  }, [])

  const stop = useCallback(() => {
    streamGenRef.current += 1
    abortRef.current?.abort?.()
    abortRef.current = null
    endStreamChrome(conversationIdRef.current)
  }, [endStreamChrome])

  const newAgent = () => {
    streamGenRef.current += 1
    abortRef.current?.abort?.()
    abortRef.current = null
    endStreamChrome()
    navigate('/agent')
    setMessages([])
    setClarify(null)
    clarifyRef.current = null
    setComposerText('')
    setStreamError(null)
    streamErrorRef.current = null
    justFinishedStreamingRef.current = null
  }

  // Pass raw history only — ChatWindow renders StreamingTurn separately
  // (injecting a streaming assistant into messages doubled the agent reply).

  const railBody = (
    <div className="flex h-full flex-col gap-2 p-3">
      <Button variant="outline" className="w-full justify-start gap-2" onClick={newAgent}>
        <Plus className="size-4" />
        {t('new', { defaultValue: 'New agent task' })}
      </Button>
      <div className="relative">
        <Search className="pointer-events-none absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={rail.search}
          onChange={(e) => rail.setSearch(e.target.value)}
          className="ps-8 h-9 text-[13px]"
          placeholder={t('search', { defaultValue: 'Search…' })}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rail.isLoading && (
          <div className="flex justify-center py-6">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        )}
        {rail.pinned?.map((c) => (
          <ConversationRow
            key={c._id}
            conversation={c}
            active={rail.activeConversationId === c._id}
            hrefBase="/agent"
            onNavClick={() => setMobileRailOpen(false)}
            onRename={(id, title) => rail.rename(id, title)}
            onTogglePin={(conv) => rail.togglePin(conv._id, conv.is_pinned)}
            onDelete={async (conv) => {
              const ok = await confirm({
                title: t('deleteTitle', { defaultValue: 'Delete task?' }),
                description: t('deleteDesc', { defaultValue: 'This cannot be undone.' }),
                destructive: true,
              })
              if (ok) rail.remove(conv._id)
            }}
          />
        ))}
        {(rail.groups || []).map((g) => (
          <div key={g.key} className="mt-2">
            <div className="px-2 py-1 text-[11px] font-medium text-muted-foreground">
              {g.label}
            </div>
            {g.items.map((c) => (
              <ConversationRow
                key={c._id}
                conversation={c}
                active={rail.activeConversationId === c._id}
                hrefBase="/agent"
                onNavClick={() => setMobileRailOpen(false)}
                onRename={(id, title) => rail.rename(id, title)}
                onTogglePin={(conv) => rail.togglePin(conv._id, conv.is_pinned)}
                onDelete={async (conv) => {
                  const ok = await confirm({
                    title: t('deleteTitle', { defaultValue: 'Delete task?' }),
                    description: t('deleteDesc', { defaultValue: 'This cannot be undone.' }),
                    destructive: true,
                  })
                  if (ok) rail.remove(conv._id)
                }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )

  return (
    // Full-height flex shell under AppShell main. gridTemplateRows not needed
    // (single column + rail) but every flex child that scrolls needs min-h-0.
    <div className="flex h-full min-h-0 w-full">
      <HeaderSlot side="start">
        <div className="flex min-w-0 items-center gap-2.5">
          <IconTile tone="sky" size="md">
            <Sparkles className="size-4" />
          </IconTile>
          <div className="min-w-0">
            <span className="block truncate text-[15px] font-bold leading-tight tracking-[-0.01em] text-foreground">
              {t('title', { defaultValue: 'Agent' })}
            </span>
            <span className="hidden truncate text-[11px] text-muted-foreground sm:block max-w-[28rem]">
              {t('subtitle')}
            </span>
          </div>
        </div>
      </HeaderSlot>
      <HeaderSlot side="end">
        <div className="flex items-center gap-2">
          <PrivacyBadge mode="cloud" />
          <Button
            variant="ghost"
            size="sm"
            className="lg:hidden gap-1.5"
            onClick={() => setMobileRailOpen(true)}
          >
            <History className="size-4" />
            {t('history', { defaultValue: 'History' })}
          </Button>
        </div>
      </HeaderSlot>

      {isLg && (
        <aside className="hidden w-72 shrink-0 border-e border-border/60 lg:flex lg:flex-col min-h-0">
          {railBody}
        </aside>
      )}
      {!isLg && (
        <Sheet open={mobileRailOpen} onOpenChange={setMobileRailOpen}>
          <SheetContent side="start" className="w-80 p-0">
            <SheetTitle className="sr-only">{t('history', { defaultValue: 'History' })}</SheetTitle>
            {railBody}
          </SheetContent>
        </Sheet>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="shrink-0 px-3 pt-2 md:px-4">
          <PrivacyBanner mode="cloud" className="mx-auto max-w-[768px]" />
        </div>
        {!isOnline && (
          <div className="flex shrink-0 items-center gap-2 bg-amber-500/10 px-4 py-2 text-[12px] text-amber-700 dark:text-amber-300">
            <WifiOff className="size-3.5" />
            {t('chat:connection.offline', { defaultValue: 'You are offline' })}
          </div>
        )}

        {/* flex-col + min-h-0 so ChatWindow's flex-1 + absolute scroll fills
            under the AppTopBar without painting under it. */}
        <div className="flex min-h-0 flex-1 flex-col">
          {isLoadingConversation &&
          conversationId &&
          !isStreaming &&
          messages.length === 0 ? (
            <div className="flex flex-1 items-center justify-center">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : isConversationError && messages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2">
              <p className="text-sm text-muted-foreground">{t('loadError')}</p>
              <Button variant="outline" size="sm" onClick={() => refetchConversation()}>
                {t('retry')}
              </Button>
            </div>
          ) : !conversationId && messages.length === 0 && !isStreaming ? (
            <AgentEmptyState
              onPickStarter={(prompt) => {
                setComposerText(prompt)
                window.dispatchEvent(
                  new CustomEvent('chat:composer-insert', { detail: { text: prompt } }),
                )
              }}
            />
          ) : (
            <ChatWindow
              messages={messages}
              conversationId={conversationId}
              // Clarify card owns the turn — never keep typing dots under it.
              isStreaming={Boolean(isStreaming && !clarify)}
              streamingContent={clarify ? '' : streamingContent}
              liveDataAnalysis={(() => {
                if (clarify) return null
                const py = toolSteps.filter(isPythonStep)
                const arts = nonImageArts(liveArtifacts)
                if (!py.length && !arts.length) return null
                return { steps: py, artifacts: arts }
              })()}
              // Never dataMode — that shows "analyzing your data…" which is
              // wrong for plain chat. Empty StreamingTurn = 3 thinking dots.
              dataMode={false}
              dataPhase={agentPhase === 'extracting' ? { phase: 'extracting' } : null}
            />
          )}
        </div>

        {/* Live image strip while tools still running */}
        {isStreaming && liveArtifacts.some((a) => a?.type === 'image') && (
          <div className="border-t border-border/40 px-4 py-2">
            <AgentArtifacts artifacts={liveArtifacts} />
          </div>
        )}

        <div className="mx-auto w-full max-w-[768px] px-4 pb-4 pt-2">
          {clarify?.questions?.length ? (
            <AgentClarifyCard
              questions={clarify.questions}
              onSubmit={handleClarifySubmit}
              disabled={isStreaming}
            />
          ) : null}

          {streamError && (
            <div role="alert" className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
              <span className="flex-1">{streamError}</span>
              {lastSendRef.current && (
                <button type="button" className="underline" onClick={handleRetry}>
                  {t('retry')}
                </button>
              )}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setStreamError(null)
                  streamErrorRef.current = null
                }}
              >
                {t('dismiss')}
              </button>
            </div>
          )}

          {isStreaming && !clarify && (
            <div className="mb-2 flex flex-col gap-1.5">
              {agentPhase &&
                !toolSteps.some((s) => s.status === 'running') &&
                phaseLabel(agentPhase, t) && (
                  <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-[11px] text-muted-foreground">
                    <Loader2 className="size-3 animate-spin" />
                    {phaseLabel(agentPhase, t)}
                  </span>
                )}
              <AgentToolTimeline steps={toolSteps} streaming compact />
            </div>
          )}

          <div
            className={cn(
              GLASS_CLASS,
              'flex flex-col gap-2 border border-border/50 p-2',
            )}
            style={glassSx({ strong: true, radius: 16 })}
          >
            <div className="flex flex-wrap items-center gap-1.5 px-1">
              <span
                title={t('webBadgeHint')}
                className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary"
              >
                <Globe className="size-3" aria-hidden />
                {t('webBadge')}
              </span>
            </div>
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-1">
                {attachments.map((a) => (
                  <span
                    key={a.upload_id}
                    className="rounded-full bg-bg-2/80 px-2 py-0.5 text-[11px] text-muted-foreground"
                  >
                    {a.original_name}
                    <button
                      type="button"
                      className="ms-1 opacity-60 hover:opacity-100"
                      onClick={() =>
                        setAttachments((prev) => prev.filter((x) => x.upload_id !== a.upload_id))
                      }
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                multiple
                accept=".pdf,.xlsx,.xls,.csv,.docx,.pptx,.png,.jpg,.jpeg,.webp,.txt,.json,.parquet"
                onChange={handleFilePick}
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="shrink-0"
                disabled={isStreaming || !!clarify}
                onClick={() => fileInputRef.current?.click()}
                aria-label={t('chat:input.attach', { defaultValue: 'Attach' })}
              >
                <Paperclip className="size-4" />
              </Button>
              <Textarea
                value={composerText}
                onChange={(e) => setComposerText(e.target.value)}
                disabled={isStreaming || !!clarify}
                placeholder={t('placeholder')}
                aria-label={t('placeholder')}
                rows={1}
                className="min-h-[40px] max-h-40 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                dir={i18n.dir()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
              />
              {isStreaming ? (
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  onClick={stop}
                  aria-label={t('chat:input.stop', { defaultValue: 'Stop' })}
                >
                  <span className="size-2.5 rounded-sm bg-foreground" />
                </Button>
              ) : (
                <Button
                  type="button"
                  size="icon"
                  className="bg-accent text-accent-foreground shadow-primary-glow"
                  disabled={(!composerText.trim() && !attachments.length) || !!clarify}
                  onClick={handleSend}
                  aria-label={t('chat:input.send', { defaultValue: 'Send' })}
                >
                  <ArrowUp className="size-4" />
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>

      {confirmDialog}
      {budgetModal}
      {dlpModal}
    </div>
  )
}
