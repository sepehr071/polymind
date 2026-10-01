import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { Sparkles, Trash2, MessageSquare, Square, AlertTriangle, RotateCcw } from 'lucide-react'
import { Button } from '../../components/ui/button'
import {
  getHelperHistory,
  clearHelper,
} from '../../services/helperService'
import HelperMessage from '../../components/helper/HelperMessage'
import HelperInput from '../../components/helper/HelperInput'
import HeaderSlot from '../../components/layout/HeaderSlot'
import { PrivacyBadge, PrivacyBanner } from '@/components/privacy/ModelPrivacyCallout'
import { useConfirmDelete } from '../../hooks/useConfirmDelete'
import { dirOf } from '../../utils/rtl'

const SUGGESTION_KEYS = ['navigate', 'image', 'workflow', 'knowledge']

/**
 * Full-page support assistant.
 *
 * Mirrors the legacy in-rail helper semantics but uses the page's full
 * vertical height with a centered max-w-3xl message column. Reaches the same
 * helper service (`/helper/stream`, `/helper/history`, `/helper/clear`).
 */
export default function HelperPage() {
  const { t } = useTranslation('helper')
  const location = useLocation()
  const { confirm, confirmDialog } = useConfirmDelete()

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamingId, setStreamingId] = useState(null)
  // History fetch lifecycle — distinguishes "loaded but empty" (show the welcome
  // state) from "failed to load" (show an inline error + retry).
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(false)
  const abortRef = useRef(null)
  const submitRef = useRef(null)
  const scrollRef = useRef(null)
  // Last user text — replayed by the Retry affordance on a failed turn.
  const lastUserTextRef = useRef('')
  // Synchronous "is the user pinned to the bottom?" flag. A ref (not state) so a
  // fast token stream never races a lagging setState — and so we never yank a
  // user who scrolled up to read.
  const atBottomRef = useRef(true)

  // Load history. Returns a cleanup-aware loader so both the mount effect and
  // the inline retry button can drive it. `aliveRef` guards against setState
  // after the loader was superseded (unmount / re-trigger).
  const aliveRef = useRef(true)
  const loadHistory = useCallback(() => {
    setHistoryLoading(true)
    setHistoryError(false)
    getHelperHistory()
      .then((rows) => {
        if (!aliveRef.current) return
        setMessages(
          (rows || []).map((m, idx) => ({
            id: m._id || `${idx}-${m.created_at || ''}`,
            role: m.role,
            content: m.content || '',
          })),
        )
        setHistoryError(false)
      })
      .catch(() => {
        if (!aliveRef.current) return
        // A failed fetch is NOT an empty history — surface a retryable error
        // instead of silently rendering the welcome/empty state.
        setHistoryError(true)
      })
      .finally(() => {
        if (aliveRef.current) setHistoryLoading(false)
      })
  }, [])

  // Load history once on mount
  useEffect(() => {
    aliveRef.current = true
    loadHistory()
    return () => {
      aliveRef.current = false
    }
  }, [loadHistory])

  // Track whether the user is pinned near the bottom. Updated on every scroll;
  // gates the auto-scroll below so a user who scrolled up is never yanked back.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el
      atBottomRef.current = scrollHeight - scrollTop - clientHeight <= 80
    }
    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [])

  // Autoscroll to bottom on new content — ONLY when already pinned to bottom.
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !atBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages, streaming])

  // Cancel in-flight stream on route change
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        try {
          abortRef.current()
        } catch {
          /* ignore */
        }
        abortRef.current = null
      }
    }
  }, [location.pathname])

  const handleClear = useCallback(async () => {
    const ok = await confirm({
      title: t('clearTitle'),
      description: t('clearConfirm'),
      destructive: true,
    })
    if (!ok) return
    try {
      await clearHelper()
    } catch {
      // best-effort — UI still wipes
    }
    setMessages([])
  }, [confirm, t])

  const handleMessageStart = useCallback((text) => {
    lastUserTextRef.current = text
    // Sending always re-pins to bottom so the new turn is visible.
    atBottomRef.current = true
    const userId = `u-${Date.now()}`
    const assistantId = `a-${Date.now()}`
    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setStreamingId(assistantId)
    setStreaming(true)
    setInput('')
  }, [])

  const handleMessageChunk = useCallback((event) => {
    const chunk = event?.content || ''
    if (!chunk) return
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const next = prev.slice()
      const last = next[next.length - 1]
      if (last?.role === 'assistant') {
        next[next.length - 1] = { ...last, content: (last.content || '') + chunk }
      }
      return next
    })
  }, [])

  const handleMessageComplete = useCallback((event) => {
    const final = event?.content
    if (typeof final === 'string') {
      setMessages((prev) => {
        if (prev.length === 0) return prev
        const next = prev.slice()
        const last = next[next.length - 1]
        if (last?.role === 'assistant') {
          next[next.length - 1] = { ...last, content: final }
        }
        return next
      })
    }
    setStreaming(false)
    setStreamingId(null)
    abortRef.current = null
  }, [])

  const handleMessageError = useCallback(
    (event) => {
      const msg = event?.error || t('errorStreaming')
      setMessages((prev) => {
        if (prev.length === 0) return prev
        const next = prev.slice()
        const last = next[next.length - 1]
        if (last?.role === 'assistant' && !last.content) {
          // Nothing streamed yet — turn the empty bubble into the error row.
          next[next.length - 1] = { ...last, content: msg, isError: true }
        } else {
          // Mid-stream failure: keep the partial reply, append an error
          // affordance below it so the user can retry the turn.
          next.push({ id: `e-${Date.now()}`, role: 'assistant', content: msg, isError: true })
        }
        return next
      })
      setStreaming(false)
      setStreamingId(null)
      abortRef.current = null
    },
    [t],
  )

  // Abort an in-flight stream. The partial reply already rendered stays put.
  const handleStop = useCallback(() => {
    if (abortRef.current) {
      try {
        abortRef.current()
      } catch {
        /* ignore */
      }
      abortRef.current = null
    }
    setStreaming(false)
    setStreamingId(null)
  }, [])

  // Re-send the last user turn after a failure. Drops the trailing error row(s)
  // so the conversation reads cleanly, then re-submits via the composer.
  const handleRetry = useCallback(() => {
    const text = lastUserTextRef.current
    if (!text || streaming) return
    setMessages((prev) => {
      const next = prev.slice()
      // Strip trailing assistant rows (the failed/partial reply + error row)
      // back to the originating user turn, which submit() will re-append.
      while (next.length && next[next.length - 1].role === 'assistant') next.pop()
      if (next.length && next[next.length - 1].role === 'user') next.pop()
      return next
    })
    submitRef.current?.submit(text)
  }, [streaming])

  const handleDlpBlock = useCallback(() => {
    handleMessageError({ error: t('dlp.block') })
  }, [handleMessageError, t])
  const handleDlpConfirmRequired = useCallback(() => {
    handleMessageError({ error: t('dlp.confirm') })
  }, [handleMessageError, t])

  // Clickable starter prompts for the empty state. Keys live under
  // helper:empty.suggestions (en + fa).
  const handleSuggestion = useCallback((text) => {
    if (streaming) return
    submitRef.current?.submit(text)
  }, [streaming])

  const hasMessages = messages.length > 0

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Page title — portaled into the global top bar (inline-start), no second
          glass header band. */}
      <HeaderSlot side="start">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
          <span className="truncate text-base font-semibold text-foreground">
            {t('pageTitle')}
          </span>
        </div>
      </HeaderSlot>

      {/* Stop / Clear + privacy chip — top bar end. Badge always on. */}
      <HeaderSlot side="end">
        <div className="flex items-center gap-1">
          <PrivacyBadge mode="cloud" />
          {streaming && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleStop}
                aria-label={t('stop')}
                title={t('stop')}
                className="h-8 gap-1.5 text-xs"
                animated={false}
              >
                <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
                {t('stop')}
              </Button>
            )}
            {hasMessages && (
              <Button
                variant="ghost"
                size="icon"
                onClick={handleClear}
                aria-label={t('clear')}
                title={t('clear')}
                className="h-8 w-8 text-foreground-tertiary hover:text-error"
                animated={false}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            )}
          </div>
        </HeaderSlot>

      <div className="shrink-0 px-4 pt-2">
        <PrivacyBanner mode="cloud" className="mx-auto max-w-3xl" />
      </div>

      {/* Message list — centered column */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-6 space-y-4">
          {!hasMessages && historyLoading && (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-hidden="true" />
              <span className="text-sm text-foreground-tertiary">{t('historyLoading')}</span>
            </div>
          )}

          {!hasMessages && !historyLoading && historyError && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center px-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-error/10 text-error">
                <AlertTriangle className="h-6 w-6" aria-hidden="true" />
              </div>
              <h2 className="text-base font-semibold text-foreground">
                {t('historyError.title')}
              </h2>
              <p className="max-w-md text-sm text-foreground-tertiary leading-relaxed">
                {t('historyError.body')}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={loadHistory}
                className="mt-1 gap-1.5"
                animated={false}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                {t('historyError.retry')}
              </Button>
            </div>
          )}

          {!hasMessages && !historyLoading && !historyError && (
            <div className="relative flex flex-col items-center justify-center gap-3 text-center py-16 px-4">
              {/* Subtle radial sky glow behind the hero (chat-surface spec). */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 -z-10"
                style={{
                  background:
                    'radial-gradient(60% 50% at 50% 38%, rgba(14,165,233,0.06), transparent 70%)',
                }}
              />
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/10 text-accent">
                <MessageSquare className="h-6 w-6" aria-hidden="true" />
              </div>
              <h2 className="text-base font-semibold text-foreground">
                {t('empty.title')}
              </h2>
              <p className="max-w-md text-sm text-foreground-tertiary leading-relaxed">
                {t('empty.body')}
              </p>
              <div className="mt-2 flex flex-col items-center gap-2">
                <span className="text-xs font-medium text-foreground-tertiary">
                  {t('empty.suggestionsLabel')}
                </span>
                <div className="flex flex-wrap justify-center gap-2">
                  {SUGGESTION_KEYS.map((key) => {
                    const text = t(`empty.suggestions.${key}`)
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleSuggestion(text)}
                        dir={dirOf(text)}
                        className="rounded-full bg-accent/10 px-3 py-1 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      >
                        {text}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {hasMessages &&
            messages.map((m) => (
              <HelperMessage
                key={m.id}
                role={m.role}
                content={m.content}
                isError={m.isError}
                onRetry={m.isError ? handleRetry : undefined}
              />
            ))}

          {/* In-progress reply — announced to screen readers via aria-live. */}
          <div aria-live="polite" aria-atomic="true" className="sr-only">
            {streaming ? t('streamingAria') : ''}
          </div>

          {streaming && streamingId && (() => {
            const last = messages[messages.length - 1]
            if (last?.role === 'assistant' && !last.content) {
              return (
                <div className="text-xs text-foreground-tertiary ps-1">
                  {t('loading')}
                </div>
              )
            }
            return null
          })()}
        </div>
      </div>

      {/* Composer — flat dock, top hairline only, centered to match message column */}
      <div className="relative z-10 shrink-0 border-t border-border bg-background">
        <div className="mx-auto w-full max-w-3xl">
          <HelperInput
            value={input}
            onChange={setInput}
            streaming={streaming}
            onMessageStart={handleMessageStart}
            onMessageChunk={handleMessageChunk}
            onMessageComplete={handleMessageComplete}
            onMessageError={handleMessageError}
            onDlpBlock={handleDlpBlock}
            onDlpConfirmRequired={handleDlpConfirmRequired}
            abortRef={abortRef}
            submitRef={submitRef}
          />
        </div>
      </div>

      {confirmDialog}
    </div>
  )
}
