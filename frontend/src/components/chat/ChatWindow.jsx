import { useEffect, useRef, useState, memo, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useVirtualizer } from '@tanstack/react-virtual'
import { motion, AnimatePresence } from 'motion/react'
import {
  X, Send,
  FileText, ZoomIn, ChevronDown, Download,
  ShieldCheck, Quote,
} from 'lucide-react'
import MarkdownRenderer from './MarkdownRenderer'
import MessageSources from './MessageSources'
import MessageActions from './MessageActions'
import ModelDivider from './ModelDivider'
import StreamingTurn from './StreamingTurn'
// Lazy boundary — keeps ECharts + react-table out of the always-loaded chat
// chunk (loads on demand the first time a data-analyzer turn renders).
import DataAnalysisBlock from './DataAnalysis/LazyDataAnalysisBlock'
import AgentArtifacts from '../../pages/agent/components/AgentArtifacts'
import AgentToolTimeline from '../../pages/agent/components/AgentToolTimeline'
import { QUICK_MODELS } from '../../constants/models'
import { cn } from '../../utils/cn'
import { getTextDirection } from '../../utils/rtl'
import { getInitials, avatarColors } from '../../utils/avatarColor'
import toast from 'react-hot-toast'
import { fmtDate } from '../../utils/dateLocale'
import { Button } from '../ui/button'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip'
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '../ui/dialog'
import { Badge } from '../ui/badge'

/* ─── Blinking cursor keyframes injected once ──────────────────────── */
if (typeof document !== 'undefined') {
  const STYLE_ID = 'chat-blink-keyframes'
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style')
    style.id = STYLE_ID
    style.textContent = `@keyframes chat-blink { 0%,100%{opacity:1} 50%{opacity:0} }`
    document.head.appendChild(style)
  }
}

/* ─── Model-name helper ─────────────────────────────────────────────── */
function extractModelName(message) {
  return (
    message?.metadata?.model_id?.split('/')?.pop() ||
    message?.config_name ||
    message?.model_name ||
    null
  )
}

/* Vertical gap between virtualized message rows (was `space-y-7` = 1.75rem).
   Driven by the virtualizer's `gap` option so spacing survives the absolute
   positioning the virtualizer requires. */
const ROW_GAP_PX = 28
/* Conservative first-paint estimate for an unmeasured message row. The exact
   value only affects the scrollbar before a row is measured (measureElement
   corrects it on mount); a mid-range guess minimizes the initial jump. */
const ESTIMATED_ROW_PX = 140

/* ═══════════════════════════════════════════════════════════════════════
   ChatWindow
   ═══════════════════════════════════════════════════════════════════════ */
export default function ChatWindow({
  messages,
  isStreaming,
  streamingContent,
  // Data Analyzer live timeline (intent='data') — { steps, artifacts } | null.
  // Rendered beneath the streaming turn until the persisted message takes over.
  liveDataAnalysis = null,
  conversationId,
  onEditMessage,
  onRegenerateMessage,
  onFeedback,
  onRunCode,
  // New props (audit)
  maxColumnWidth = 768,
  // Collaborative (team-shared) chat: show per-message sender name + avatar.
  showSenders = false,
  // Data Analyzer page: drives the "Analyzing your data…" working state shown
  // before the first run_python lands (regular chat shows generic thinking dots).
  dataMode = false,
  // Document-extraction phase ({ phase, file } | null) for intent='data' runs.
  // When phase==='extracting' the working placeholder shows "Reading <file>…"
  // instead of the generic analyzing text (plain chat passes null — unaffected).
  dataPhase = null,
}) {
  const { t } = useTranslation('chat')
  const scrollRef = useRef(null)
  const [copiedId, setCopiedId] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editContent, setEditContent] = useState('')
  const [showScrollButton, setShowScrollButton] = useState(false)
  // Live "is the user pinned near the bottom?" flag, read synchronously by the
  // auto-scroll rAF. Kept in a ref (not state) so a fast token stream never
  // races a lagging setState — and so we never yank a user who scrolled up.
  const atBottomRef = useRef(true)
  const scrollRafRef = useRef(null)

  /* ── Last assistant message id ──
     Its action bar stays always-visible (ChatGPT parity); every other bar is
     hover/focus-gated by QuietMessage. */
  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.role === 'assistant') return messages[i]._id
    }
    return null
  }, [messages])

  /* ── Regenerate model options ──
     Quick models only in v1 — ChatWindow no longer receives the config list
     (PR4 removed selectedConfig), so custom personas can't be offered here
     without plumbing configs through ChatPage (cross-agent conflict). Mapped to
     `quick:<id>` so the backend resolves them via config_resolver. */
  const regenOptions = useMemo(
    () => QUICK_MODELS.map((m) => ({ id: `quick:${m.id}`, name: m.name })),
    []
  )

  /* ── Per-row divider/model labels (PERF) ──
     Precompute the model-switch divider decision + label for every index once
     per `messages` change. The virtualItems.map body ran extractModelName for
     BOTH the row and its predecessor on every ChatWindow render — i.e. every
     streamed frame, since streamingContent re-renders ChatWindow. Keyed on
     `messages` only (NOT streamingContent), so the streaming frames index into
     a stable array instead of recomputing. */
  const rowMeta = useMemo(() => {
    return messages.map((message, idx) => {
      const thisModel = extractModelName(message)
      const prevAssistantModel = idx > 0 ? extractModelName(messages[idx - 1]) : null
      const showDivider =
        message?.role === 'assistant' &&
        prevAssistantModel !== null &&
        thisModel !== null &&
        prevAssistantModel !== thisModel
      return { showDivider, modelLabel: thisModel }
    })
  }, [messages])

  /* ── Scroll tracking ── */
  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight
      atBottomRef.current = distanceFromBottom <= 80
      setShowScrollButton(distanceFromBottom > 200)
    }
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [])

  /* ── Auto-scroll (rAF-coalesced) ──
     One scrollTop write per frame instead of one per streamed flush, and only
     when the user is already pinned to the bottom (don't yank them if they
     scrolled up to read). The streamed render is itself rAF-throttled upstream
     (useChatStream), so `streamingContent` changes ~once/frame already; this
     guards against multiple deps landing in the same tick. */
  useEffect(() => {
    const container = scrollRef.current
    if (!container || !atBottomRef.current) return
    if (scrollRafRef.current != null) return
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null
      if (scrollRef.current && atBottomRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight
      }
    })
    return () => {
      if (scrollRafRef.current != null) {
        cancelAnimationFrame(scrollRafRef.current)
        scrollRafRef.current = null
      }
    }
  }, [messages, streamingContent, liveDataAnalysis])

  const scrollToBottom = () => {
    atBottomRef.current = true
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  /* ── Virtualizer (historical messages only) ──
     Windows the (up to 100) historical QuietMessage rows so we mount only the
     visible markdown parses instead of all of them. Mounted on the SAME scroll
     element as the auto-scroll / scroll-button logic above (getScrollElement →
     scrollRef.current), so that logic is untouched — it still drives
     scroll-to-bottom during streaming (the StreamingTurn is real DOM appended
     after the virtual container, so scrollHeight includes it).

     Dynamic heights via measureElement (markdown rows vary widely). `anchorTo:
     'end'` keeps the bottom-pinned viewport stable while estimated rows settle
     to their measured height (no upward jump on conversation open); it does not
     force-scroll a user who has scrolled up. `followOnAppend` keeps the newest
     measured row in view as the persisted assistant turn replaces the live
     StreamingTurn. The streaming turn itself stays outside the virtualizer. */
  const rowVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_PX,
    // Stable per-message key so re-measures and any future prepend (older-message
    // pagination) track the right row instead of an index that shifts.
    getItemKey: (index) => messages[index]?._id ?? index,
    overscan: 6,
    gap: ROW_GAP_PX,
    anchorTo: 'end',
    followOnAppend: true,
    scrollEndThreshold: 80,
  })
  const virtualItems = rowVirtualizer.getVirtualItems()
  const totalSize = rowVirtualizer.getTotalSize()

  /* ── Jump to bottom on conversation open / switch ──
     The non-virtualized list landed at the bottom because the auto-scroll
     effect fired on the messages change. With windowed estimated heights the
     total size keeps growing as rows are measured after first paint, so a
     single scrollTop write lands short. Re-pin to true bottom across a few
     post-mount frames while measurements settle, and arm atBottomRef so the
     rAF auto-scroll + anchorTo:'end' hold it from there. Skips while the user
     is streaming (the new-chat navigate flips conversationId mid-stream — we
     must not yank the in-flight view). */
  const lastPinnedConvRef = useRef(undefined)
  useEffect(() => {
    if (isStreaming) return
    if (lastPinnedConvRef.current === conversationId) return
    // Wait for the conversation's messages to actually arrive before claiming
    // this conversation as pinned. On a switch, useChatMessages first clears to
    // [] then the GET populates — consuming the guard on the empty pass would
    // skip the real pin once messages load.
    if (messages.length === 0) return
    lastPinnedConvRef.current = conversationId

    atBottomRef.current = true
    let frames = 0
    let rafId = null
    const pin = () => {
      const container = scrollRef.current
      if (!container) return
      container.scrollTop = container.scrollHeight
      // A handful of frames covers the ResizeObserver measurement cascade for
      // the on-screen rows without an open-ended loop.
      if (++frames < 6) rafId = requestAnimationFrame(pin)
    }
    rafId = requestAnimationFrame(pin)
    return () => { if (rafId != null) cancelAnimationFrame(rafId) }
  }, [conversationId, messages.length, isStreaming])

  /* ── Copy ── */
  const handleCopy = useCallback(async (content, messageId) => {
    try {
      await navigator.clipboard.writeText(content)
      setCopiedId(messageId)
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      toast.error(t('window.copyFailed'))
    }
  }, [t])

  /* ── Edit ── */
  const handleStartEdit = useCallback((message) => {
    setEditingId(message._id)
    setEditContent(message.content)
  }, [])

  const handleCancelEdit = useCallback(() => {
    setEditingId(null)
    setEditContent('')
  }, [])

  const handleSubmitEdit = (messageId) => {
    const content = editContent.trim()
    if (!content) { toast.error(t('window.editEmpty')); return }
    if (messageId.toString().startsWith('temp-')) {
      toast.error(t('window.editPending')); return
    }
    // Close the editor IMMEDIATELY — the hook applies the edit optimistically
    // (bubble swaps to the new text, tail truncates, thinking dots appear), so
    // holding the textarea open for the blocking regenerate read as frozen UI.
    handleCancelEdit()
    if (onEditMessage) onEditMessage(messageId, content)
  }

  return (
    <div className="flex-1 relative">
      {/* Floating "Ask Polymind AI" quote pill — appears on selecting ASSISTANT
          text inside the scroll container (see SelectionQuotePill). */}
      <SelectionQuotePill scrollRef={scrollRef} />
      <div
        ref={scrollRef}
        className="absolute inset-0 overflow-y-auto py-6"
        role="log"
        aria-label={t('window.chatMessages')}
        // `log` is itself a polite live region; the explicit attrs make intent
        // unmistakable and add a busy hint while tokens stream. NEVER `assertive`
        // — that would interrupt the user on every token. `aria-atomic="false"`
        // keeps announcements to *added* content (log semantics), so historical
        // rows mounting/unmounting during virtualized scroll aren't re-read.
        aria-live="polite"
        aria-atomic="false"
        aria-busy={isStreaming}
      >
        <div
          className="mx-auto px-4"
          style={{ maxWidth: maxColumnWidth }}
        >
          {/* Virtualized historical messages. The sized spacer holds total
              height; only on-screen rows (+overscan) are mounted, each
              absolutely positioned at its measured offset. */}
          <div
            className="relative w-full"
            style={{ height: totalSize }}
          >
            {virtualItems.map((virtualItem) => {
              const idx = virtualItem.index
              const message = messages[idx]
              if (!message) return null

              /* Model divider: precomputed in rowMeta (keyed on messages, not
                 streamingContent) so streamed frames don't recompute it. */
              const { showDivider, modelLabel: thisModel } = rowMeta[idx] || {}

              return (
                <div
                  key={virtualItem.key}
                  data-index={idx}
                  ref={rowVirtualizer.measureElement}
                  className="absolute top-0 inset-x-0"
                  style={{ transform: `translateY(${virtualItem.start}px)` }}
                >
                  {/* Model-switch divider — kept (no data removed) but
                      de-emphasised: muted + downscaled so the model name reads
                      as a quiet breadcrumb rather than a loud banner. */}
                  {showDivider && (
                    <div className="opacity-50 scale-[0.92] origin-center">
                      <ModelDivider modelName={thisModel} />
                    </div>
                  )}
                  <QuietMessage
                    message={message}
                    conversationId={conversationId}
                    copiedId={copiedId}
                    onCopy={handleCopy}
                    isEditing={editingId === message._id}
                    editContent={editContent}
                    onEditContentChange={setEditContent}
                    onStartEdit={
                      onEditMessage ? () => handleStartEdit(message) : undefined
                    }
                    onCancelEdit={handleCancelEdit}
                    onSubmitEdit={() => handleSubmitEdit(message._id)}
                    onRegenerate={onRegenerateMessage}
                    onFeedback={onFeedback}
                    regenOptions={regenOptions}
                    isLastAssistant={message._id === lastAssistantId}
                    onRunCode={onRunCode}
                    showSender={showSenders}
                  />
                </div>
              )
            })}
          </div>

          {/* Streaming turn — rendered AFTER the virtualized list (real DOM, not
              a virtual row). Spaced from the last historical row by ROW_GAP so
              it matches the inter-message rhythm. Stays outside the virtualizer
              so its live growth is driven solely by the rAF auto-scroll above. */}
          {isStreaming && (
            <div style={{ marginTop: messages.length > 0 ? ROW_GAP_PX : 0 }}>
              {/* Visually-hidden plain-text mirror of the in-progress reply (the
                  rendered markdown turn below is hard for SRs to follow live).
                  No own live region — the scroll container is the single polite
                  live region now; nesting one here would double-announce. */}
              <div className="sr-only">
                {streamingContent}
              </div>
              {/* Data Analyzer live timeline — steps + chart/table artifacts
                  stream in ABOVE the prose: the Python loop emits charts/tables
                  first, then the answer narrates them ("the chart above…"), so
                  the bottom-pinned viewport rests on the answer, not a chart. On
                  message_complete this clears and the persisted QuietMessage
                  renders the same block from metadata. */}
              {liveDataAnalysis && (
                <DataAnalysisBlock
                  steps={liveDataAnalysis.steps}
                  artifacts={liveDataAnalysis.artifacts}
                  streaming
                />
              )}
              {dataMode && !liveDataAnalysis && !streamingContent ? (
                /* Data mode, model still thinking before the first run_python:
                   a clear "Analyzing your data…" pill instead of bare thinking
                   dots. Once the steps timeline appears its own live header
                   ("Analyzing… step N") owns the status. */
                <div
                  className="flex items-center gap-2 rounded-xl border border-border bg-background-secondary px-3 py-3 text-sm text-foreground-tertiary"
                  role="status"
                >
                  <span className="flex gap-1">
                    {[0, 0.2, 0.4].map((d, i) => (
                      <span
                        key={i}
                        className="h-1.5 w-1.5 rounded-full bg-accent/70 animate-pulse-dot"
                        style={{ animationDelay: `${d}s` }}
                      />
                    ))}
                  </span>
                  <span>
                    {dataPhase?.phase === 'extracting'
                      ? (dataPhase.file
                          ? t('dataAnalyzer.readingFile', { name: dataPhase.file })
                          : t('dataAnalyzer.readingFiles'))
                      : t('dataAnalyzer.analyzing')}
                  </span>
                </div>
              ) : (
                <StreamingTurn content={streamingContent} onRunCode={onRunCode} />
              )}
            </div>
          )}
        </div>
      </div>

      {/* Scroll-to-bottom button */}
      <AnimatePresence>
        {showScrollButton && (
          <Tooltip>
            <TooltipTrigger asChild>
              <motion.div
                initial={{ opacity: 0, scale: 0.8, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.8, y: 10 }}
                className="absolute bottom-4 end-4"
              >
                <Button
                  onClick={scrollToBottom}
                  size="icon"
                  aria-label={t('window.scrollToBottom')}
                  className="h-11 w-11 rounded-full shadow-lg shadow-accent/30"
                >
                  <ChevronDown className="h-5 w-5" />
                </Button>
              </motion.div>
            </TooltipTrigger>
            <TooltipContent>{t('window.scrollToBottom')}</TooltipContent>
          </Tooltip>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   SelectionQuotePill — ChatGPT-style "Ask Polymind AI" floating action.
   Appears when the user text-selects inside an ASSISTANT body (anything under
   a `.markdown-content` node that the scroll container owns). User bubbles use
   a bare <p className="whitespace-pre-wrap"> with NO `.markdown-content`, so
   they're excluded; the scrollRef.contains() guard also excludes any markdown
   rendered outside this chat. Clicking dispatches `chat:composer-quote` with the
   trimmed selection for the composer to pick up.

   Portalled to <body> with position:fixed/zIndex 1500 (clears MUI's 1300 modal
   layer): the virtualizer rows carry `translateY` transforms, so an absolutely
   positioned in-tree pill would misplace against that transformed offset.
   ═══════════════════════════════════════════════════════════════════════ */
function SelectionQuotePill({ scrollRef }) {
  const { t } = useTranslation('chat')
  const [pill, setPill] = useState(null) // { text, top, left } | null
  const pillRef = useRef(null)

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return

    const hide = () => setPill(null)

    // Resolve the current selection → quotable assistant text, or null.
    const evaluate = () => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null
      const text = sel.toString().trim()
      if (!text) return null

      const range = sel.getRangeAt(0)
      let node = range.commonAncestorContainer
      const el = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement
      if (!el) return null
      // Must be assistant prose (under .markdown-content) AND inside this chat's
      // scroll container — user bubbles have no .markdown-content, and other
      // markdown surfaces on the page aren't contained by scrollRef.
      if (!el.closest('.markdown-content')) return null
      if (!container.contains(el)) return null

      const rect = range.getBoundingClientRect()
      if (!rect || (rect.width === 0 && rect.height === 0)) return null

      // Pill above the selection, horizontally centered, clamped to viewport.
      const PILL_HALF = 80 // approx half-width for clamping
      const top = Math.max(8, rect.top - 44)
      const left = Math.min(
        Math.max(rect.left + rect.width / 2, PILL_HALF + 8),
        window.innerWidth - PILL_HALF - 8
      )
      return { text, top, left }
    }

    const sync = () => {
      const next = evaluate()
      setPill(next)
    }

    const onMouseUp = () => {
      // Defer a tick so the browser finalizes the selection after mouseup.
      setTimeout(sync, 0)
    }
    const onSelectionChange = () => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed || !sel.toString().trim()) hide()
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') hide()
    }
    const onPointerDown = (e) => {
      // Clicking the pill itself must not dismiss it (handled in onClick).
      if (pillRef.current && pillRef.current.contains(e.target)) return
      hide()
    }

    container.addEventListener('mouseup', onMouseUp)
    container.addEventListener('scroll', hide, { passive: true })
    document.addEventListener('selectionchange', onSelectionChange)
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => {
      container.removeEventListener('mouseup', onMouseUp)
      container.removeEventListener('scroll', hide)
      document.removeEventListener('selectionchange', onSelectionChange)
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown, true)
    }
  }, [scrollRef])

  if (!pill) return null

  const handleClick = () => {
    const text = window.getSelection()?.toString().trim()
    if (text) {
      window.dispatchEvent(
        new CustomEvent('chat:composer-quote', { detail: { text } })
      )
    }
    window.getSelection()?.removeAllRanges()
    setPill(null)
  }

  return createPortal(
    <button
      ref={pillRef}
      type="button"
      // preventDefault keeps the active selection alive through the click.
      onMouseDown={(e) => e.preventDefault()}
      onClick={handleClick}
      style={{
        position: 'fixed',
        top: pill.top,
        left: pill.left,
        transform: 'translateX(-50%)',
        zIndex: 1500,
      }}
      className="rounded-full bg-popover text-popover-foreground border border-border shadow-lg px-3 py-1.5 text-sm flex items-center gap-1.5"
    >
      <Quote className="h-3.5 w-3.5" aria-hidden="true" />
      {t('input.askSelection')}
    </button>,
    document.body
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   QuietMessage — ChatGPT-style surface: identity conveyed by SHAPE, not
   labels. User = trailing rounded bubble (end-aligned column); assistant =
   flush full-width prose. No avatars, no role names.
   ═══════════════════════════════════════════════════════════════════════ */
const QuietMessage = memo(function QuietMessage({
  message,
  conversationId,
  copiedId,
  onCopy,
  isEditing,
  editContent,
  onEditContentChange,
  onStartEdit,
  onCancelEdit,
  onSubmitEdit,
  onRegenerate,
  onFeedback,
  regenOptions,
  isLastAssistant,
  onRunCode,
  showSender,
}) {
  const { t } = useTranslation('chat')
  const isUser = message.role === 'user'

  // Sender tag for collaborative (team-shared) chats — name + hue-tinted
  // initials above the user bubble. Null on private chats / assistant turns.
  const senderColors = message.sender?.name ? avatarColors(message.sender.name) : null
  const senderTag = showSender && senderColors ? (
    <div className="mb-1 flex items-center gap-1.5">
      <span
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold"
        style={{ backgroundColor: senderColors.bg, color: senderColors.fg }}
      >
        {getInitials(message.sender.name)}
      </span>
      <span className="text-xs text-foreground-tertiary">{message.sender.name}</span>
    </div>
  ) : null

  // Action-bar visibility. Both roles' bars are hover/focus-gated on pointer
  // devices; the LAST assistant turn stays pinned. Touch devices (no hover)
  // keep every bar visible — the md: prefix only arms the gating ≥ md.
  const actionVisibility = isLastAssistant
    ? 'opacity-100'
    : 'opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100'
  const isCopied = copiedId === message._id
  const textareaRef = useRef(null)

  // getTextDirection regex-scans the whole message; memoize so it runs once per
  // content change instead of 2-3× per render (was called inline at each use).
  const textDir = useMemo(() => getTextDirection(message.content), [message.content])

  /* Animate the bubble↔editor swap only when it IS a swap. Virtualized rows
     unmount/remount on scroll — an unconditional mount animation would flash
     every bubble scrolled back into view. During the render where isEditing
     flipped, the ref still holds the previous value (effects run post-render),
     so the swap animates exactly once per direction. */
  const wasEditingRef = useRef(isEditing)
  useEffect(() => { wasEditingRef.current = isEditing }, [isEditing])
  const animateSwap = wasEditingRef.current !== isEditing

  /* Focus + caret-to-end once on edit entry (NOT per keystroke — re-setting the
     selection while typing would yank the caret). */
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      const el = textareaRef.current
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  }, [isEditing])

  /* Textarea auto-resize */
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [isEditing, editContent])

  const handleEditKeyDown = (e) => {
    if (e.key === 'Escape') onCancelEdit()
    else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) onSubmitEdit()
  }

  // Absolute time string. User branch surfaces it only as a native `title` on
  // the bubble; assistant branch shows it inline on hover. No always-visible
  // timestamp anymore — the shape carries identity, not a metadata row.
  const timestamp = message.created_at
    ? fmtDate(new Date(message.created_at), 'HH:mm')
    : null

  /* ── Quoted-text contract (ChatGPT "quote selection") ──
     A user message that quoted assistant text carries the raw quote in
     `metadata.quoted_text`. The composer also prefixes the quote as a `> …`
     markdown block in `content`; strip that leading blockquote for display so
     the styled quote block (rendered separately below) isn't duplicated as
     plain text. Hooks run unconditionally (before the user-branch return) to
     keep hook order stable across renders. */
  const quotedText = message.metadata?.quoted_text
  const displayContent = useMemo(
    () => (quotedText ? message.content.replace(/^(?:> .*(?:\n|$))+\n?/, '') : message.content),
    [message.content, quotedText]
  )
  const [quoteExpanded, setQuoteExpanded] = useState(false)
  const isQuoteLong = !!quotedText && (quotedText.length > 160 || quotedText.split('\n').length > 3)

  /* ── User turn ──
     ChatGPT-style trailing bubble. The whole column is end-aligned (items-end),
     User messages are pinned to the RIGHT in BOTH directions (`items-end` is
     direction-resolved → it would flip to the left under RTL, so override with
     `rtl:items-start` to keep the bubble on the right for Persian too).
     Attachments, bubble, badge line and actions all stack within that column. */
  if (isUser) {
    return (
      <div className="group flex flex-col items-end rtl:items-start">
        {senderTag}
        {/* Attachments above the bubble — AttachmentPreview already right-sizes
            its tiles; living in the items-end column end-aligns the group. */}
        {message.attachments && message.attachments.length > 0 && (
          <AttachmentPreview attachments={message.attachments} />
        )}

        {isEditing ? (
          /* ── Edit mode ──
             Editor spans the full column (w-full) — the bubble width cap only
             applies to the read view. Mount animation gated to the actual swap
             (see animateSwap above). */
          <motion.div
            className="w-full"
            initial={animateSwap ? { opacity: 0, scale: 0.98, y: 2 } : false}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <textarea
              ref={textareaRef}
              value={editContent}
              onChange={(e) => onEditContentChange(e.target.value)}
              onKeyDown={handleEditKeyDown}
              className="w-full bg-background-secondary border border-accent rounded-xl px-3 py-2 md:px-4 md:py-3 text-foreground resize-none focus:outline-none focus:ring-[3px] focus:ring-accent/20 text-base"
              placeholder={t('window.editPlaceholder')}
              rows={1}
              style={{ minHeight: '60px' }}
            />
            <div className="flex items-center justify-between mt-2 gap-2">
              <span className="text-xs text-foreground-tertiary hidden sm:inline">
                {t('window.editHint')}
              </span>
              <div className="flex gap-2 ms-auto">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="secondary" size="icon" onClick={onCancelEdit} className="h-10 w-10" aria-label={t('window.cancelEdit')}>
                      <X className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('window.cancelEdit')}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="icon" onClick={onSubmitEdit} className="h-10 w-10" aria-label={t('window.saveEdit')}>
                      <Send className="h-4 w-4 rtl:-scale-x-100" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('window.saveEdit')}</TooltipContent>
                </Tooltip>
              </div>
            </div>
          </motion.div>
        ) : (
          /* Read view — wrapper keeps the parent column's end alignment; mount
             animation gated to the edit→read swap only. */
          <motion.div
            className="flex w-full flex-col items-end rtl:items-start"
            initial={animateSwap ? { opacity: 0, scale: 0.98 } : false}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {/* Bubble — Consistent UI System accent bubble: accent fill + white
                text, asymmetric radius 16/16/4/16 via the logical end-end corner
                (rounded-ee) so it mirrors correctly under RTL. Absolute time
                lives on `title` (no visible timestamp). */}
            <div
              className="max-w-[78%] rounded-[16px] rounded-ee-[4px] bg-accent px-4 py-2.5 text-[15px] leading-[1.65] text-accent-foreground"
              title={timestamp || undefined}
              onDoubleClick={onStartEdit}
            >
              {/* Quoted assistant text the user is replying to — styled block
                  above the message body. On the accent bubble the quote reads as
                  a translucent inset (white-on-accent), not the neutral muted
                  tones used on a grey bubble. Shows the raw quote VALUE (no `> `
                  markers); the body below renders the quote-stripped content. */}
              {quotedText && (
                <div className="mb-2 border-s-2 border-accent-foreground/40 bg-accent-foreground/10 rounded-e-md ps-2.5 pe-2 py-1.5">
                  <div
                    className={`text-xs leading-snug text-accent-foreground/80 whitespace-pre-wrap break-words ${
                      isQuoteLong && !quoteExpanded ? 'line-clamp-3' : ''
                    }`}
                  >
                    {quotedText}
                  </div>
                  {isQuoteLong && (
                    <button
                      type="button"
                      onClick={() => setQuoteExpanded((v) => !v)}
                      className="mt-1 text-[11px] font-medium text-accent-foreground/90 hover:underline focus:outline-none"
                    >
                      {quoteExpanded ? t('input.quoteShowLess') : t('input.quoteShowMore')}
                    </button>
                  )}
                </div>
              )}
              <p className="whitespace-pre-wrap" dir={textDir}>
                {displayContent}
              </p>
            </div>

            {/* Edited / DLP-redacted badges — quiet muted line under the bubble. */}
            {(message.is_edited || message.metadata?.dlp_redacted) && (
              <div className="mt-1 text-xs text-foreground-tertiary flex items-center gap-1">
                {message.metadata?.dlp_redacted && (
                  <span
                    className="inline-flex items-center gap-1 text-accent opacity-80"
                    title={t('dlp.redactedBadgeHint')}
                  >
                    <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                    {t('dlp.redactedBadge')}
                  </span>
                )}
                {message.is_edited && (
                  <span className="opacity-60">{t('window.edited')}</span>
                )}
              </div>
            )}

            {/* Actions — hover/focus-gated (always-on for the last assistant
                turn only; user turns reveal on hover ≥ md). Wrapped so it aligns
                end under the bubble. */}
            <div className={cn('flex justify-end transition-opacity', actionVisibility)}>
              <MessageActions
                messageId={message._id}
                content={message.content}
                role={message.role}
                conversationId={conversationId}
                message={message}
                isCopied={isCopied}
                onCopy={onCopy}
                onEdit={onStartEdit}
                onRegenerate={onRegenerate}
              />
            </div>
          </motion.div>
        )}
      </div>
    )
  }

  /* ── Assistant turn ──
     ChatGPT-style flush full-width prose: no avatar, no name label, body starts
     at the column edge. `group` on the wrapper drives the hover-revealed meta
     micro-line in the action row. */
  return (
    <div className="group">
      {/* Agent tool summary (non-python tools) — separate from Data Analyzer. */}
      {Array.isArray(message.metadata?.agent_steps) &&
        message.metadata.agent_steps.length > 0 && (
          <AgentToolTimeline
            steps={message.metadata.agent_steps}
            className="mb-3"
          />
        )}

      {/* Data Analyzer artifacts (persisted). For agent turns, only show python
          steps that have code — never label image/web as "Run Python". */}
      {message.metadata?.data_artifacts && (() => {
        const da = message.metadata.data_artifacts
        const isAgent = message.metadata?.intent === 'agent'
        const rawSteps = Array.isArray(da.steps) ? da.steps : []
        const steps = isAgent
          ? rawSteps.filter(
              (s) =>
                s?.name === 'run_python' ||
                (s?.code != null && String(s.code).trim() !== ''),
            )
          : rawSteps
        const arts = Array.isArray(da.artifacts) ? da.artifacts : []
        if (!steps.length && !arts.length) return null
        return (
          <DataAnalysisBlock steps={steps} artifacts={arts} />
        )
      })()}

      {/* Agent-generated images (survive reload via metadata.agent_artifacts). */}
      {Array.isArray(message.metadata?.agent_artifacts) && (
        <AgentArtifacts artifacts={message.metadata.agent_artifacts} />
      )}

      <div
        className={cn(
          'text-[15px] leading-[1.65] text-foreground',
          (message.metadata?.data_artifacts ||
            message.metadata?.agent_steps?.length ||
            message.metadata?.agent_artifacts?.length) &&
            'mt-3',
        )}
      >
        <div className="markdown-content" dir={textDir}>
          <MarkdownRenderer content={message.content} onRunCode={onRunCode} />
        </div>
      </div>

      {/* Web-search sources (chat + agent) */}
      <MessageSources annotations={message.metadata?.annotations} />
      {/* Agent soft badge when search ran but no citation list arrived */}
      {message.metadata?.intent === 'agent' &&
        message.metadata?.used_web &&
        !(
          Array.isArray(message.metadata?.annotations) &&
          message.metadata.annotations.length > 0
        ) && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary/8 px-2.5 py-0.5 text-[11px] text-primary">
            {t('window.usedWeb', { defaultValue: 'Used web' })}
          </div>
        )}

      {/* Action row — actions plus a hover-revealed meta micro-line carrying the
          timestamp, token count, and edited marker (all data kept, pushed back
          so it never competes with the reply). The whole row is hover/focus-
          gated except on the last assistant turn, which stays pinned. */}
      <div className={cn('flex items-center gap-2 transition-opacity', actionVisibility)}>
        <MessageActions
          messageId={message._id}
          content={message.content}
          role={message.role}
          conversationId={conversationId}
          message={message}
          isCopied={isCopied}
          onCopy={onCopy}
          onEdit={onStartEdit}
          onRegenerate={onRegenerate}
          onFeedback={onFeedback}
          regenOptions={regenOptions}
        />
        <span className="text-xs text-foreground-tertiary opacity-0 group-hover:opacity-100 transition-opacity">
          {[
            timestamp,
            message.metadata?.tokens
              ? t('window.tokens', { count: message.metadata.tokens.completion })
              : null,
            message.is_edited ? t('window.edited') : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>
    </div>
  )
}, (prev, next) => (
  prev.message._id === next.message._id &&
  prev.message.content === next.message.content &&
  prev.message.is_edited === next.message.is_edited &&
  // metadata is mutated in place on feedback — compare the field explicitly or
  // the thumbs state won't re-render.
  prev.message.metadata?.feedback === next.message.metadata?.feedback &&
  // Data Analyzer artifacts settle onto metadata when a stream completes; the
  // reference flips, so compare it or the persisted block won't appear.
  prev.message.metadata?.data_artifacts === next.message.metadata?.data_artifacts &&
  prev.message.metadata?.agent_artifacts === next.message.metadata?.agent_artifacts &&
  prev.message.metadata?.agent_steps === next.message.metadata?.agent_steps &&
  prev.message.metadata?.annotations === next.message.metadata?.annotations &&
  prev.message.metadata?.used_web === next.message.metadata?.used_web &&
  prev.isEditing === next.isEditing &&
  prev.editContent === next.editContent &&
  prev.copiedId === next.copiedId &&
  prev.isLastAssistant === next.isLastAssistant &&
  prev.onRegenerate === next.onRegenerate &&
  prev.onFeedback === next.onFeedback &&
  prev.showSender === next.showSender &&
  prev.message.sender?.id === next.message.sender?.id
))

/* MessageSources extracted to ./MessageSources.jsx (reused by the read-only
   shared-snapshot view). */

/* ═══════════════════════════════════════════════════════════════════════
   AttachmentPreview (unchanged behavior, re-aligned to quiet layout)
   ═══════════════════════════════════════════════════════════════════════ */
const AttachmentPreview = memo(function AttachmentPreview({ attachments }) {
  const { t } = useTranslation('chat')
  const [zoomedImage, setZoomedImage] = useState(null)

  const isImage = (a) =>
    a.type?.startsWith('image/') || a.mime_type?.startsWith('image/')

  const images = attachments.filter(isImage)
  const files = attachments.filter((a) => !isImage(a))

  return (
    <>
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {images.map((img, idx) => (
            <motion.button
              key={idx}
              type="button"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              className="relative group cursor-pointer overflow-hidden rounded-xl shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              onClick={() => setZoomedImage(img.url)}
              aria-label={t('window.zoomImage', { name: img.name || t('window.attachedImage') })}
            >
              <img
                src={img.url}
                alt={img.name || t('window.attachedImage')}
                className="max-w-[200px] max-md:max-w-[140px] max-h-[200px] object-cover border border-border rounded-xl transition-transform duration-300 group-hover:scale-105"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 rounded-xl flex items-end justify-center pb-3">
                <Badge variant="secondary" className="bg-foreground text-background shadow-lg">
                  <ZoomIn className="h-3 w-3 me-1" />
                  {t('window.view')}
                </Badge>
              </div>
            </motion.button>
          ))}
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {files.map((file, idx) => (
            <Badge key={idx} variant="secondary" className="px-3 py-2 h-auto gap-2">
              <FileText className="h-4 w-4" />
              <span className="truncate max-w-[150px]">{file.name || t('window.attachedFile')}</span>
            </Badge>
          ))}
        </div>
      )}

      <Dialog open={!!zoomedImage} onOpenChange={() => setZoomedImage(null)}>
        <DialogContent
          className="max-w-[95vw] max-h-[95vh] p-0 bg-black/95 border-none overflow-hidden"
          showClose={false}
        >
          <DialogTitle className="sr-only">{t('window.imagePreview')}</DialogTitle>
          <div className="relative flex items-center justify-center min-h-[50vh]">
            <img
              src={zoomedImage}
              alt={t('window.imagePreview')}
              className="max-h-[85vh] max-w-[90vw] object-contain"
            />
            <div className="absolute top-4 end-4 flex gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="secondary"
                    size="icon"
                    aria-label={t('window.download')}
                    className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white border-0"
                    onClick={(e) => {
                      e.stopPropagation()
                      const link = document.createElement('a')
                      link.href = zoomedImage
                      link.download = 'image.png'
                      link.click()
                    }}
                  >
                    <Download className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('window.download')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="secondary"
                    size="icon"
                    aria-label={t('window.close')}
                    className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white border-0"
                    onClick={() => setZoomedImage(null)}
                  >
                    <X className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('window.close')}</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
})
