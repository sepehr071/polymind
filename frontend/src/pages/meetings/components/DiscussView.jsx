import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ArrowUp, Square, MessageSquare, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'

import { spawnConversation } from '@/services/meetingsService'
import { chatService } from '@/services/chatService'
import { streamChat, cancelChat } from '@/services/streamService'
import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'
import { dirOf } from '@/utils/rtl'
import { cn } from '@/utils/cn'
import { useDlpConfirm } from '@/hooks/useDlpConfirm'
import { useBudgetBlock } from '@/hooks/useBudgetBlock'
import { RADII } from '@/theme/tokens'

/**
 * Slim in-page chat for a single meeting. Talks to the regular chat SSE
 * endpoint (`POST /chat/stream`) against the conversation that
 * `/meetings/<id>/spawn-conversation` returns (now idempotent — same convId
 * across reopens of the Discuss tab).
 *
 * Excluded by design: file attachments, slash commands, branching, model
 * picker, code canvas. The seeded `system` message carries the meeting's
 * transcript + summary; the model is locked to `quick:<MEETING_DISCUSSION_MODEL>`
 * via the conversation's `config_id`.
 */
export default function DiscussView({ meetingId, meetingReady }) {
  const { t } = useTranslation('meetings')
  const queryClient = useQueryClient()

  const [conversationId, setConversationId] = useState(null)
  const [draft, setDraft] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingMessageId, setStreamingMessageId] = useState(null)
  const [pendingMessages, setPendingMessages] = useState([])

  const abortRef = useRef(null)
  const scrollerRef = useRef(null)
  const textareaRef = useRef(null)

  const { scan: dlpScan, dlpModal } = useDlpConfirm({ source: 'meeting' })
  const { handleBudgetError, budgetModal } = useBudgetBlock()

  // Step 1: ensure the meeting conversation exists. Idempotent server-side.
  const spawnMut = useMutation({
    mutationFn: () => spawnConversation(meetingId),
    onSuccess: (resp) => {
      const id = resp?.conversation_id ?? resp?._id ?? resp?.id
      if (id) setConversationId(String(id))
    },
  })

  useEffect(() => {
    if (!meetingReady) return
    if (conversationId) return
    if (spawnMut.isPending || spawnMut.isError) return
    spawnMut.mutate()
    // mutate only fires once until success — the guards above prevent loop.
  }, [meetingReady, conversationId, spawnMut])

  // Step 2: load persisted messages for that conversation.
  const messagesQ = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => chatService.getConversation(conversationId),
    enabled: !!conversationId,
    staleTime: 30_000,
  })

  // Surface visible messages (drop the system seed; users see chat only).
  const visibleMessages = useMemo(() => {
    const persisted = messagesQ.data?.messages || []
    const all = [...persisted, ...pendingMessages]
    return all.filter((m) => m.role !== 'system')
  }, [messagesQ.data, pendingMessages])

  // Reconcile: once the conversation refetch returns the saved assistant turn,
  // drop any pending placeholders whose content matches a persisted message.
  useEffect(() => {
    if (!messagesQ.data?.messages?.length) return
    const persistedIds = new Set(messagesQ.data.messages.map((m) => String(m._id)))
    setPendingMessages((prev) => prev.filter((m) => !persistedIds.has(String(m._id))))
  }, [messagesQ.data])

  // Auto-scroll to bottom on new content.
  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [visibleMessages.length, streamingContent])

  // Cleanup any in-flight stream on unmount.
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort()
        abortRef.current = null
      }
    }
  }, [])

  const conversation = messagesQ.data?.conversation
  const configId = conversation?.config_id

  async function handleSend() {
    const message = draft.trim()
    if (!message || !conversationId || !configId || isStreaming) return

    // DLP preflight (source=meeting). null = dismissed / blocked.
    let dlpConfirmed = false
    let dlpRedact = false
    let dlpConfirmToken = null
    try {
      const decision = await dlpScan(message)
      if (decision === null) return
      dlpConfirmed = !!decision.confirmed
      dlpRedact = !!decision.redact
      dlpConfirmToken = decision.confirm_token || null
    } catch {
      // Backend gate is defence-in-depth.
    }

    const tempUserId = `temp-user-${Date.now()}`
    const tempAssistantId = `temp-asst-${Date.now()}`
    setPendingMessages((prev) => [
      ...prev,
      {
        _id: tempUserId,
        role: 'user',
        content: message,
        created_at: new Date().toISOString(),
      },
    ])
    setDraft('')
    setIsStreaming(true)
    setStreamingContent('')
    setStreamingMessageId(tempAssistantId)

    const controller = new AbortController()
    abortRef.current = controller

    const restoreOnFail = () => {
      setPendingMessages((prev) => prev.filter((m) => m._id !== tempUserId))
      setDraft(message) // keep draft — don't lose text on error
      setIsStreaming(false)
      setStreamingMessageId(null)
      setStreamingContent('')
    }

    try {
      await streamChat(
        {
          conversation_id: conversationId,
          config_id: configId,
          message,
          attachments: [],
          dlp_confirmed: dlpConfirmed || undefined,
          dlp_redact: dlpRedact || undefined,
          dlp_confirm_token: dlpConfirmToken || undefined,
        },
        {
          onMessageSaved: (data) => {
            // Swap optimistic user msg with saved one.
            setPendingMessages((prev) =>
              prev.map((m) =>
                m._id === tempUserId && data?.message?.role === 'user'
                  ? data.message
                  : m
              )
            )
          },
          onMessageStart: (data) => {
            if (data?.message_id) setStreamingMessageId(data.message_id)
          },
          onMessageChunk: (data) => {
            setStreamingContent((prev) => prev + (data?.content || ''))
          },
          onMessageComplete: (data) => {
            const newAssistant = {
              _id: data?.message_id || tempAssistantId,
              role: 'assistant',
              content: data?.content || '',
              metadata: data?.metadata,
              created_at: new Date().toISOString(),
            }
            setPendingMessages((prev) => [...prev, newAssistant])
            setIsStreaming(false)
            setStreamingMessageId(null)
            setStreamingContent('')
            // Refetch so the persisted thread becomes the source of truth.
            queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
          },
          onMessageError: (data) => {
            if (handleBudgetError(data)) {
              restoreOnFail()
              return
            }
            toast.error(data?.error || t('detail.discussFailed'))
            restoreOnFail()
          },
        },
        controller.signal
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('detail.discussFailed'))
      restoreOnFail()
    } finally {
      abortRef.current = null
    }
  }

  async function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    if (streamingMessageId && !String(streamingMessageId).startsWith('temp-')) {
      try {
        await cancelChat(streamingMessageId)
      } catch {
        // best-effort
      }
    }
    setIsStreaming(false)
    setStreamingMessageId(null)
    setStreamingContent('')
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Auto-grow textarea up to ~5 lines.
  function handleDraftChange(e) {
    setDraft(e.target.value)
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`
    }
  }

  // --- render branches -----------------------------------------------------

  if (!meetingReady) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex max-w-md flex-col items-center gap-3 text-center">
          <MessageSquare className="size-9 text-foreground-tertiary" />
          <p className="text-sm text-foreground-secondary">
            {t('detail.discussNotReady')}
          </p>
        </div>
      </div>
    )
  }

  if (spawnMut.isError) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex max-w-md flex-col items-center gap-3 text-center">
          <AlertTriangle className="size-9 text-error" />
          <p className="text-sm text-foreground-secondary">
            {t('detail.discussFailed')}
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => spawnMut.reset()}
          >
            {t('detail.discussRetry')}
          </Button>
        </div>
      </div>
    )
  }

  if (!conversationId || messagesQ.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-2.5 text-foreground-secondary">
          <Loader2 className="size-6 animate-spin text-amber-600 dark:text-amber-400" />
          <p className="text-sm">{t('detail.discussLoading')}</p>
        </div>
      </div>
    )
  }

  const showEmptyState = visibleMessages.length === 0 && !isStreaming

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto scroll-thin px-1 pb-2"
      >
        {showEmptyState ? (
          <div className="flex h-full flex-col items-center justify-center gap-5 px-6 py-10 text-center">
            <IconTile icon={MessageSquare} tone="amber" size="xl" />
            <p className="max-w-md text-sm text-foreground-secondary">
              {t('detail.discussEmpty')}
            </p>
            <div className="flex max-w-md flex-wrap items-center justify-center gap-2">
              {['discussSampleQ1', 'discussSampleQ2', 'discussSampleQ3'].map((key) => {
                const q = t(`detail.${key}`)
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setDraft(q)}
                    className="rounded-full bg-amber-500/10 px-3 py-1.5 text-[11px] font-semibold text-amber-700 transition-colors hover:bg-amber-500/20 dark:bg-amber-400/10 dark:text-amber-300 dark:hover:bg-amber-400/20"
                  >
                    {q}
                  </button>
                )
              })}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-[720px] flex-col gap-5 py-6">
            {visibleMessages.map((m) => (
              <MessageBubble key={String(m._id)} message={m} />
            ))}
            {isStreaming && (
              <div className="flex items-start gap-3">
                <IconTile icon={MessageSquare} tone="sky" className="mt-0.5 h-[30px] w-[30px] rounded-[10px]" iconClassName="size-4" />
                <div className="min-w-0 flex-1 pt-0.5 text-sm text-foreground">
                  {streamingContent ? (
                    <MarkdownRenderer content={streamingContent} />
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-foreground-tertiary">
                      <Loader2 className="size-3.5 animate-spin" />
                      …
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-border bg-background px-4 py-3">
        <div
          className="mx-auto flex max-w-[720px] items-end gap-2 border border-border bg-card p-2 shadow-card focus-within:border-accent focus-within:shadow-[0_0_0_3px_hsl(var(--accent)/0.18)]"
          style={{ borderRadius: RADII.overlay }}
        >
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={handleDraftChange}
            onKeyDown={handleKeyDown}
            placeholder={t('detail.discussPlaceholder')}
            aria-label={t('detail.discussInputLabel')}
            dir={draft ? dirOf(draft) : undefined}
            rows={1}
            disabled={isStreaming || !configId}
            className={cn(
              'flex-1 resize-none border-0 bg-transparent px-2.5 py-2 text-sm text-foreground',
              'placeholder:text-foreground-tertiary',
              'focus:outline-none focus:ring-0',
              'disabled:cursor-not-allowed disabled:opacity-60'
            )}
          />
          {isStreaming ? (
            <Button
              type="button"
              variant="destructive"
              size="icon"
              onClick={handleStop}
              aria-label={t('detail.discussStop')}
              className="h-9 w-9 shrink-0 rounded-full"
            >
              <Square className="size-3.5" />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon"
              onClick={handleSend}
              disabled={!draft.trim() || !configId}
              aria-label={t('detail.discussSend')}
              className="h-9 w-9 shrink-0 rounded-full"
            >
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>
      </div>
      {dlpModal}
      {budgetModal}
    </div>
  )
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  if (isUser) {
    return (
      <div className="flex flex-row-reverse">
        <div
          className="max-w-[78%] rounded-[16px_16px_4px_16px] bg-accent px-4 py-2.5 text-sm text-accent-foreground"
          dir={message.content ? dirOf(message.content) : undefined}
        >
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-3">
      <IconTile
        icon={MessageSquare}
        tone="sky"
        className="mt-0.5 h-[30px] w-[30px] rounded-[10px]"
        iconClassName="size-4"
      />
      <div
        className="min-w-0 flex-1 pt-0.5 text-sm text-foreground"
        dir={message.content ? dirOf(message.content) : undefined}
      >
        <MarkdownRenderer content={message.content || ''} />
      </div>
    </div>
  )
}
