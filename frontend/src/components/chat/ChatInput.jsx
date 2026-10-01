import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'motion/react'
import {
  Paperclip, X, Image, File, Loader2, Square,
  Plus, Globe, Link, FileText, AlertTriangle, Check,
  Brain, Zap, ArrowUp, Quote, FileArchive, AudioLines, Video
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '../../utils/cn'
import { useModelCatalog } from '../../hooks/useModelCatalog'
import PillBar from './PillBar'
import { Button } from '../ui/button'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { SLASH_COMMANDS } from '../../constants/slashCommands'
import { QUICK_MODEL_IDS } from '../../constants/models'

export default function ChatInput({
  onSend,
  onFileUpload,
  onStop,
  disabled = false,
  placeholder,
  isStreaming = false,
  // code_canvas_run platform flag — hides the Tools → Canvas item when OFF.
  // Default true so callers without the flag wiring keep the item.
  canvasEnabled = true,
  selectedConfig,
  selectedConfigId,
  // Model picker shown INSIDE the pill row (empty/new-chat composer only).
  // `showModelPicker` is gated by ChatPage's `isEmpty`; after the first send the
  // composer remounts without it and only the header pill remains.
  configs = [],
  onSelectConfig,
  showModelPicker = false,
  initialMessage = '',
  initialFiles = []
}) {
  const { t, i18n } = useTranslation('chat')
  const { getById, isEmpty: catalogEmpty } = useModelCatalog()

  // Vision gate: only let images be staged when the selected model can actually
  // read them. Resolve the underlying OpenRouter id the same way PillBar does
  // (quick:<id> prefix → bare id, else the persona's model_id), then check the
  // catalog's input modalities. Fail OPEN — if the catalog is empty/loading or
  // the model is unknown, allow images (don't block on missing data).
  const underlyingModelId = selectedConfigId?.startsWith('quick:')
    ? selectedConfigId.slice('quick:'.length)
    : selectedConfig?.model_id || null
  const catalogEntry = underlyingModelId ? getById(underlyingModelId) : null
  const modelCanSeeImages =
    catalogEmpty || !catalogEntry
      ? true
      : Boolean(catalogEntry.architecture?.input_modalities?.includes('image'))

  // Audio / video gates — same shape + fail-open contract as the vision gate.
  // When false, attaching A/V auto-switches to the multimodal default model
  // (uploadFiles) rather than blocking the attach.
  const modelCanHearAudio =
    catalogEmpty || !catalogEntry
      ? true
      : Boolean(catalogEntry.architecture?.input_modalities?.includes('audio'))
  const modelCanSeeVideo =
    catalogEmpty || !catalogEntry
      ? true
      : Boolean(catalogEntry.architecture?.input_modalities?.includes('video'))

  // Reasoning gate — same shape as the vision gate above. OpenRouter's
  // ``supported_parameters`` (synced into the local registry per model) carries
  // 'reasoning' only for models that accept the reasoning/effort knob. Fail
  // OPEN when the catalog is empty/unknown: OpenRouter silently ignores the
  // param on unsupported models, so a stray send is harmless.
  const modelSupportsReasoning =
    catalogEmpty || !catalogEntry
      ? true
      : Boolean(catalogEntry.supported_parameters?.includes('reasoning'))

  const [message, setMessage] = useState(initialMessage)
  const [files, setFiles] = useState(initialFiles)
  const [quotedText, setQuotedText] = useState('')
  const [uploading, setUploading] = useState(false)
  const [activeCommand, setActiveCommand] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)

  // Web-search toggle is sticky: seeded from localStorage so the choice survives
  // reloads + composer remounts (new chat, conversation switch), and persisted on
  // every flip. Read lazily so we touch localStorage once at mount, not per render.
  const [webSearch, setWebSearch] = useState(() => {
    try {
      return localStorage.getItem('chat_web_search') === '1'
    } catch {
      return false
    }
  })
  const toggleWebSearch = () => {
    setWebSearch((v) => {
      const next = !v
      try {
        localStorage.setItem('chat_web_search', next ? '1' : '0')
      } catch {
        /* private mode / quota — fall back to in-memory only */
      }
      return next
    })
  }

  // Web-fetch is AUTOMATIC, not a manual toggle: sibling to web search but
  // sender-driven. Search lets the model DISCOVER pages; fetch lets it READ a
  // specific URL/PDF the user pastes. Detect a URL in the composer text and flip
  // it on transparently, surfacing a non-removable informational chip.
  const hasUrl = /https?:\/\//i.test(message)

  // Reasoning effort switcher ("thinking"): null = provider default (Auto),
  // 'low' = quick response, 'high' = deep thinking. Sticky like web-search.
  // Sent per message as `reasoning_effort`; non-reasoning models ignore it.
  const [reasoningEffort, setReasoningEffortState] = useState(() => {
    try {
      const v = localStorage.getItem('chat_reasoning_effort')
      return v === 'low' || v === 'high' ? v : null
    } catch {
      return null
    }
  })
  const setReasoningEffort = (level) => {
    setReasoningEffortState(level)
    try {
      if (level) localStorage.setItem('chat_reasoning_effort', level)
      else localStorage.removeItem('chat_reasoning_effort')
    } catch {
      /* private mode / quota — in-memory only */
    }
  }
  const REASONING_LEVELS = [
    { value: null, icon: Check, labelKey: 'input.reasoning.auto' },
    { value: 'low', icon: Zap, labelKey: 'input.reasoning.fast' },
    { value: 'high', icon: Brain, labelKey: 'input.reasoning.deep' },
  ]
  // What actually gets SENT: a sticky preference survives model switches in
  // localStorage, but is suppressed (no param, no chip, no menu section) while
  // a non-reasoning model is selected.
  const effectiveReasoningEffort = modelSupportsReasoning ? reasoningEffort : null
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const dragDepthRef = useRef(0)

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      const newHeight = Math.min(textarea.scrollHeight, 200)
      textarea.style.height = newHeight + 'px'
    }
  }, [message])

  // Handle keyboard appearance on mobile
  useEffect(() => {
    const handleResize = () => {
      if (document.activeElement === textareaRef.current) {
        setTimeout(() => {
          textareaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 100)
      }
    }
    window.visualViewport?.addEventListener('resize', handleResize)
    return () => window.visualViewport?.removeEventListener('resize', handleResize)
  }, [])

  // Empty-state suggestion cards (ChatWindow) insert their prompt into the
  // composer via a window CustomEvent — the same loosely-coupled pattern the app
  // uses for `auth:cleared`. Keeps ChatPage out of the loop (no new prop plumbing
  // through the page) while leaving `message` as the single source of truth.
  // Appends to any in-progress draft (with a single separating space) rather than
  // clobbering it, so stacking suggestions / inserting mid-compose is non-destructive.
  useEffect(() => {
    const handleInsert = (e) => {
      const text = e.detail?.text
      if (typeof text !== 'string') return
      setMessage((prev) => (prev ? prev.replace(/\s+$/, '') + ' ' : '') + text)
      requestAnimationFrame(() => {
        const el = textareaRef.current
        if (!el) return
        el.focus()
        // Drop the caret at the end so the user types where the prompt trails off.
        const end = el.value.length
        try { el.setSelectionRange(end, end) } catch { /* unsupported */ }
      })
    }
    window.addEventListener('chat:composer-insert', handleInsert)
    return () => window.removeEventListener('chat:composer-insert', handleInsert)
  }, [])

  // Shift+Esc (global shortcut, MainLayout) refocuses the composer from
  // anywhere on the page via the same window-event pattern as insert above.
  useEffect(() => {
    const handleFocus = () => textareaRef.current?.focus()
    window.addEventListener('chat:composer-focus', handleFocus)
    return () => window.removeEventListener('chat:composer-focus', handleFocus)
  }, [])

  // ChatGPT-style "quote selection": a message-bubble selection action dispatches
  // the snippet via a window CustomEvent (same loose-coupling idiom as insert /
  // focus). We stash it in `quotedText` (rendered as a card above the composer)
  // and forward it out on send — it does NOT merge into `message`, so the user's
  // draft stays clean. Focus the textarea so they can type their reply at once.
  useEffect(() => {
    const handleQuote = (e) => {
      const text = e.detail?.text
      if (typeof text !== 'string' || !text.trim()) return
      setQuotedText(text.trim())
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
    window.addEventListener('chat:composer-quote', handleQuote)
    return () => window.removeEventListener('chat:composer-quote', handleQuote)
  }, [])

  // True while any staged attachment is still resolving (ZIP "opening" chip).
  // Sending then would dispatch a placeholder with no upload_id, so the send
  // path is blocked until every chip is ready.
  const hasPendingUpload = files.some((f) => f.status === 'opening')

  const handleSubmit = (e) => {
    e?.preventDefault()
    if ((!message.trim() && files.length === 0) || disabled || isStreaming || hasPendingUpload) return
    onSend(message.trim(), files, activeCommand, { webSearch, webFetch: hasUrl, reasoningEffort: effectiveReasoningEffort, quotedText })
    setMessage('')
    setFiles([])
    setActiveCommand(null)
    setQuotedText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
      return
    }
    // Open the unified [+] menu when typing '/' in an empty textarea with no
    // active command (attachments + capabilities now share one menu).
    if (e.key === '/' && !message && !activeCommand) {
      e.preventDefault()
      setMenuOpen(true)
      return
    }
    // Clear active command on backspace in empty textarea
    if (e.key === 'Backspace' && !message && activeCommand) {
      e.preventDefault()
      setActiveCommand(null)
    }
  }

  // Staging controller handed to onFileUpload so the ZIP path can drop an
  // immediate "opening… reading files" placeholder chip (before the upload
  // resolves) and reconcile it into the real archive chip + one chip per
  // extracted inner image. Placeholders are keyed by `placeholder_id`; every
  // other (single-attachment) path ignores this and is pushed via the return
  // value below.
  const makeStaging = () => {
    let used = false
    return {
      used: () => used,
      addPlaceholder: (placeholder) => {
        used = true
        setFiles((prev) => [...prev, placeholder])
      },
      replacePlaceholder: (placeholderId, replacements) => {
        const list = Array.isArray(replacements) ? replacements : [replacements]
        setFiles((prev) => {
          const idx = prev.findIndex((f) => f.placeholder_id === placeholderId)
          if (idx === -1) return [...prev, ...list]
          return [...prev.slice(0, idx), ...list, ...prev.slice(idx + 1)]
        })
      },
      removePlaceholder: (placeholderId) => {
        setFiles((prev) => prev.filter((f) => f.placeholder_id !== placeholderId))
      },
    }
  }

  // Shared upload path for picker / drag-drop / paste.
  const uploadFiles = async (fileList) => {
    let selectedFiles = Array.from(fileList || [])
    if (selectedFiles.length === 0 || !onFileUpload) return

    // Auto-switch to the multimodal default when the current model can't read
    // the staged media. Unlike images (which are dropped for text-only models),
    // A/V is rarer + pricier to re-stage, so we switch the model instead of
    // rejecting the file. Fail-open: skip the switch when the catalog is
    // empty/unknown (we can't prove the current model lacks the modality).
    const hasAudio = selectedFiles.some(f => (f.type || '').startsWith('audio/') || /\.(mp3|wav|m4a|ogg|flac|aac|aiff)$/i.test(f.name))
    const hasVideo = selectedFiles.some(f => (f.type || '').startsWith('video/') || /\.(mp4|webm|mov|mpeg|mpg)$/i.test(f.name))
    if (!catalogEmpty && onSelectConfig && ((hasAudio && !modelCanHearAudio) || (hasVideo && !modelCanSeeVideo))) {
      onSelectConfig(`quick:${QUICK_MODEL_IDS[0]}`)
      toast(t('input.autoSwitchedForMedia'), { icon: '🎬' })
    }

    // Drop images when the model can't see them (drag-drop / paste can carry
    // images even though the picker hides them). Warn once, keep the rest.
    // ZIPs are "files", not image inputs, so they're never gated here — their
    // inner images are staged regardless (the model reads extracted text + any
    // images the archive happens to contain).
    if (!modelCanSeeImages) {
      const blocked = selectedFiles.filter((f) => f.type?.startsWith('image/'))
      if (blocked.length > 0) {
        toast(t('input.imageUnsupportedToast'), { icon: '🚫' })
        selectedFiles = selectedFiles.filter((f) => !f.type?.startsWith('image/'))
      }
      if (selectedFiles.length === 0) return
    }
    setUploading(true)
    try {
      for (const file of selectedFiles) {
        const staging = makeStaging()
        const uploaded = await onFileUpload(file, staging)
        // When staging handled the chips (ZIP placeholder → reconcile), skip the
        // return-value push to avoid double-adding. Otherwise push the single
        // attachment (or array) the path returned.
        if (staging.used()) continue
        if (!uploaded) continue
        const additions = Array.isArray(uploaded) ? uploaded : [uploaded]
        setFiles((prev) => [...prev, ...additions])
      }
    } finally {
      setUploading(false)
    }
  }

  const handleFileSelect = async (e) => {
    await uploadFiles(e.target.files)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  // Drag-and-drop onto the composer. Depth counter avoids flicker as the
  // pointer moves over child elements (dragenter/leave fire per descendant).
  const handleDragEnter = (e) => {
    if (disabled || !onFileUpload) return
    if (!Array.from(e.dataTransfer?.types || []).includes('Files')) return
    e.preventDefault()
    dragDepthRef.current += 1
    setDragOver(true)
  }
  const handleDragOver = (e) => {
    if (disabled || !onFileUpload) return
    if (!Array.from(e.dataTransfer?.types || []).includes('Files')) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
  const handleDragLeave = (e) => {
    if (disabled || !onFileUpload) return
    e.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDragOver(false)
  }
  const handleDrop = async (e) => {
    if (disabled || !onFileUpload) return
    e.preventDefault()
    dragDepthRef.current = 0
    setDragOver(false)
    await uploadFiles(e.dataTransfer?.files)
  }

  // Paste (e.g. screenshot from clipboard) → upload any pasted files.
  const handlePaste = async (e) => {
    if (disabled || !onFileUpload) return
    const pasted = Array.from(e.clipboardData?.files || [])
    if (pasted.length === 0) return
    e.preventDefault()
    await uploadFiles(pasted)
  }

  // Stable identity for a staged attachment — placeholder_id (ZIP "opening"
  // chip) / upload_id when present, else name+size. Used for both the React key
  // and removal so two same-named files (or a placeholder vs its resolved chip)
  // don't collide.
  const fileKey = (f) => f.placeholder_id || f.upload_id || (f.name + '-' + f.size)
  const removeFile = (fileToRemove) => {
    const target = fileKey(fileToRemove)
    setFiles(prev => prev.filter(f => fileKey(f) !== target))
  }

  const isZip = (file) => file.type === 'zip'
  const isImage = (file) => !isZip(file) && (file.type?.startsWith('image/') || file.mime_type?.startsWith('image/'))
  // A/V chips: trust the explicit is_audio/is_video flags (set in
  // useChatMessages), falling back to MIME prefix or the filename extension so
  // a freshly-staged file before flag-resolution still renders the right icon.
  const isAudio = (file) => !isZip(file) && (
    file.is_audio === true ||
    (file.mime_type || file.type || '').startsWith('audio/') ||
    /\.(mp3|wav|m4a|ogg|flac|aac|aiff)$/i.test(file.name || file.filename || '')
  )
  const isVideo = (file) => !isZip(file) && (
    file.is_video === true ||
    (file.mime_type || file.type || '').startsWith('video/') ||
    /\.(mp4|webm|mov|mpeg|mpg)$/i.test(file.name || file.filename || '')
  )
  const canSend = (message.trim() || files.length > 0) && !disabled && !hasPendingUpload

  // RTL detection — preserve from original
  const detectDir = (text) => {
    const rtlChars = /[֑-߿‏‫‮יִ-﷽ﹰ-ﻼ]/
    return rtlChars.test(text) ? 'rtl' : 'ltr'
  }

  // Menu item handlers — close menu, then defer action so the dropdown unmounts
  // cleanly before any focus-stealing follow-up (file picker, etc.).
  const handleAttach = () => {
    setMenuOpen(false)
    requestAnimationFrame(() => fileInputRef.current?.click())
  }

  // Resolve a slash command's display label/placeholder, preferring its i18n
  // key (chat namespace) and falling back to the literal English string. This
  // lets the active-tool chip + textarea placeholder localize per command.
  const cmdLabel = (cmd) => (cmd?.labelKey ? t(cmd.labelKey, cmd.label) : cmd?.label)
  const cmdPlaceholder = (cmd) =>
    cmd?.placeholderKey ? t(cmd.placeholderKey, cmd.placeholder) : cmd?.placeholder

  // Capability commands toggle the single activeCommand chip. Selecting one
  // again is a no-op; the chip's X / Backspace clears it. Canvas is gated by
  // its platform flag.
  const canvasCommand = SLASH_COMMANDS.find((c) => c.id === 'canvas')
  const handleSelectCommand = (cmd) => {
    if (!cmd) return
    setMenuOpen(false)
    setActiveCommand(cmd)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  // Unified active-tool chips: web-search + the active slash command render from
  // ONE list so they sit side by side with identical styling/animation. Each
  // carries its own icon, label and dismiss handler.
  const activeTools = [
    webSearch && {
      key: 'web',
      icon: Globe,
      label: t('input.webShort'),
      onRemove: toggleWebSearch,
      removeLabel: t('input.webSearch'),
    },
    effectiveReasoningEffort && {
      key: 'reasoning',
      icon: effectiveReasoningEffort === 'low' ? Zap : Brain,
      label: t(effectiveReasoningEffort === 'low' ? 'input.reasoning.fast' : 'input.reasoning.deep'),
      onRemove: () => setReasoningEffort(null),
      removeLabel: t('input.removeCommand', {
        name: t(effectiveReasoningEffort === 'low' ? 'input.reasoning.fast' : 'input.reasoning.deep'),
      }),
    },
    activeCommand && {
      key: 'cmd',
      icon: activeCommand.icon,
      label: cmdLabel(activeCommand),
      onRemove: () => setActiveCommand(null),
      removeLabel: t('input.removeCommand', { name: cmdLabel(activeCommand) }),
    },
  ].filter(Boolean)

  return (
    <div className="px-3 md:px-4 pb-3 md:pb-4 bg-transparent">
      {/* Cockpit card */}
      <form
        onSubmit={handleSubmit}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'relative mx-auto max-w-[768px] overflow-hidden rounded-2xl border border-border bg-background-secondary shadow-[0_1px_2px_rgb(17_24_39/0.04),0_8px_24px_-12px_rgb(30_71_209/0.14)] transition-colors focus-within:border-accent/70 dark:shadow-none',
          dragOver && 'ring-2 ring-accent/40',
        )}
      >
        {/* Drag-and-drop overlay */}
        {dragOver && (
          <div
            className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center gap-2 bg-accent/10 text-accent text-sm font-medium"
          >
            <Paperclip className="h-4 w-4" />
            <span>{t('input.dropToAttach')}</span>
          </div>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={
            (modelCanSeeImages ? 'image/*,' : '') +
            '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.md,.html,.json,' +
            '.zip,application/zip,application/x-zip-compressed,' +
            // A/V unconditional: any model can attach; auto-switch handles capability.
            '.mp3,.wav,.m4a,.ogg,.flac,.aac,.aiff,.mp4,.webm,.mov,.mpeg,.mpg'
          }
          onChange={handleFileSelect}
          className="hidden"
        />

        {/* Row 1: Attachment chips (only when files present) */}
        <AnimatePresence>
          {files.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="flex flex-wrap gap-2 px-3 pt-3"
            >
              {files.map((file) => (
                <motion.div
                  key={fileKey(file)}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="relative group flex items-center gap-2 px-2 py-1.5 bg-background-tertiary rounded-lg border border-border"
                >
                  {isZip(file) ? (
                    // Archive chip — spinner while reading, then filename + a
                    // compact entry summary. Inner images appear as their own
                    // image chips (staged separately), so this chip is just the
                    // archive itself.
                    <ZipChip file={file} t={t} />
                  ) : (
                    <>
                      {isImage(file) && file.url ? (
                        // Thumbnail preview for staged images — the URL is the
                        // uploaded asset (returned by onFileUpload), so this is a
                        // real preview, not a re-read of the local File.
                        <img
                          src={file.url}
                          className="h-9 w-9 rounded-md object-cover shrink-0"
                          alt=""
                        />
                      ) : isImage(file) ? (
                        <Image className="h-3.5 w-3.5 text-accent shrink-0" />
                      ) : isAudio(file) ? (
                        <AudioLines className="h-3.5 w-3.5 text-accent shrink-0" />
                      ) : isVideo(file) ? (
                        <Video className="h-3.5 w-3.5 text-accent shrink-0" />
                      ) : (
                        <File className="h-3.5 w-3.5 text-foreground-secondary shrink-0" />
                      )}
                      <span className="text-xs text-foreground truncate max-w-[120px]">
                        {file.name || file.filename}
                      </span>

                      {/* Extraction status — "text" badge when extracted, warning otherwise */}
                      {file.extraction_status === 'ok' && (
                        <span
                          className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded bg-accent/10 text-accent text-[10px] font-medium leading-none"
                          title={t('input.extractionOk')}
                        >
                          <FileText className="h-2.5 w-2.5" />
                          {t('input.extractionTextBadge')}
                        </span>
                      )}
                      {['error', 'truncated', 'unavailable'].includes(file.extraction_status) && (
                        <AlertTriangle
                          className="h-3 w-3 text-warning shrink-0"
                          title={t(`input.extraction_${file.extraction_status}`)}
                        />
                      )}
                    </>
                  )}

                  {/* Removable while ready; the "opening" placeholder hides its X
                      (nothing to cancel client-side until the upload resolves). */}
                  {file.status !== 'opening' && (
                    <button
                      type="button"
                      onClick={() => removeFile(file)}
                      className="h-4 w-4 rounded-full flex items-center justify-center opacity-60 hover:opacity-100 hover:bg-background transition-opacity shrink-0"
                      aria-label={t('input.removeFile', { name: file.name || file.filename })}
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  )}
                </motion.div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Quoted snippet card — "quote selection" from a message bubble. Sits
            directly above the active-tool chips. Left-border card; forwarded out
            on send as `quotedText`, dismissable without affecting the draft. */}
        <AnimatePresence>
          {quotedText && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="px-3 pt-2"
            >
              <div className="flex items-start gap-2 border-s-2 border-accent/40 bg-accent/5 rounded-md ps-3 pe-2 py-1.5">
                <Quote className="h-3.5 w-3.5 text-accent shrink-0 mt-0.5" aria-hidden="true" />
                <p
                  className="flex-1 text-sm text-muted-foreground line-clamp-3 whitespace-pre-wrap"
                  aria-label={t('input.quotedAria')}
                >
                  {quotedText}
                </p>
                <button
                  type="button"
                  onClick={() => setQuotedText('')}
                  aria-label={t('input.removeQuote')}
                  className="ms-1 h-4 w-4 rounded-full flex items-center justify-center opacity-60 hover:opacity-100 hover:bg-accent/10 transition-opacity shrink-0"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Row 2: Active-tool chips (web search + slash command) + the automatic
            web-fetch chip — own row, side by side. Sits above the pill row.
            Removable toggle chips come from `activeTools`; the web-fetch chip is
            informational-only (auto-detected URL, no dismiss). */}
        {(activeTools.length > 0 || hasUrl) && (
          <div className="flex flex-wrap items-center gap-1 px-3 pt-2">
            <AnimatePresence>
              {activeTools.map((tool) => {
                const Icon = tool.icon
                return (
                  <motion.div
                    key={tool.key}
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.8 }}
                    className="flex items-center gap-1 px-2 h-7 rounded-full bg-accent/10 border border-accent/20 text-accent text-xs font-medium"
                  >
                    {Icon && <Icon className="h-3 w-3" />}
                    <span>{tool.label}</span>
                    <button
                      type="button"
                      onClick={tool.onRemove}
                      aria-label={tool.removeLabel}
                      className="ms-0.5 h-3.5 w-3.5 rounded-full flex items-center justify-center hover:bg-accent/20 transition-colors"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </motion.div>
                )
              })}
              {/* Automatic web-fetch chip — informational, NOT removable. Muted
                  styling (lower-contrast, no hover/dismiss) signals it's applied
                  automatically because the message contains a link. */}
              {hasUrl && (
                <motion.div
                  key="fetch-auto"
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="flex items-center gap-1 px-2 h-7 rounded-full bg-muted/40 border border-border/60 text-muted-foreground text-xs font-medium"
                >
                  <Link className="h-3 w-3" />
                  <span>{t('input.webFetchAuto')}</span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* Row 3: Single pill row — [+] menu · textarea · Send/Stop. `items-end`
            pins the round buttons to the bottom while the textarea grows up. */}
        <div className="flex items-end gap-1 px-2 py-1.5">
          {/* [+] DropdownMenu — unified menu: attach + web search + Canvas +
              reasoning. '/' in an empty composer opens it. */}
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={disabled}
                    aria-label={t('input.moreActions')}
                    className="shrink-0 mb-0.5 h-9 w-9 rounded-full"
                  >
                    <Plus className="h-5 w-5" />
                  </Button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent>{t('input.moreActions')}</TooltipContent>
            </Tooltip>

            <DropdownMenuContent side="top" align="start" sideOffset={8} className="min-w-[14rem]">
              {/* 1. Attach */}
              <DropdownMenuItem
                onSelect={(e) => { e.preventDefault(); handleAttach() }}
                disabled={disabled || uploading}
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
                <span>{t('input.attach')}</span>
              </DropdownMenuItem>

              {/* Vision hint — images are filtered out of attachments for
                  text-only models, so explain why the picker hides them. */}
              {!modelCanSeeImages && (
                <div className="px-2 py-1.5 text-[11px] leading-snug text-foreground-tertiary flex items-start gap-1.5">
                  <Image className="h-3 w-3 mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{t('input.imageUnsupportedHint')}</span>
                </div>
              )}

              <DropdownMenuSeparator />

              {/* 2. Web search toggle */}
              <DropdownMenuItem
                onSelect={(e) => { e.preventDefault(); toggleWebSearch() }}
              >
                <Globe className="h-4 w-4" />
                <span className="flex-1">{t('input.searchWeb')}</span>
                {webSearch && <Check className="h-4 w-4 text-accent" />}
              </DropdownMenuItem>

              {/* 3. Canvas */}
              {canvasCommand && canvasEnabled && (
                <DropdownMenuItem
                  onSelect={(e) => { e.preventDefault(); handleSelectCommand(canvasCommand) }}
                >
                  {canvasCommand.icon && <canvasCommand.icon className="h-4 w-4" />}
                  <span className="flex-1">{cmdLabel(canvasCommand)}</span>
                  {activeCommand?.id === canvasCommand.id && <Check className="h-4 w-4 text-accent" />}
                </DropdownMenuItem>
              )}

              {/* 4. Reasoning effort — friendly-named thinking levels. Single
                  select; Auto = provider default (no param sent). The section
                  AND its leading separator are hidden for models without
                  reasoning support. */}
              {modelSupportsReasoning && (
                <>
                  <DropdownMenuSeparator />
                  <div className="px-2 py-1 text-xs text-foreground-tertiary">
                    {t('input.reasoning.label')}
                  </div>
                  {REASONING_LEVELS.map(({ value, icon: LevelIcon, labelKey }) => (
                    <DropdownMenuItem
                      key={labelKey}
                      onSelect={(e) => { e.preventDefault(); setReasoningEffort(value) }}
                    >
                      <LevelIcon className="h-4 w-4" />
                      <span className="flex-1">{t(labelKey)}</span>
                      {reasoningEffort === value && <Check className="h-4 w-4 text-accent" />}
                    </DropdownMenuItem>
                  ))}
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Empty/new-chat only: bold model picker in the pill row, beside [+].
              PillBar's popover portals (MUI) so the form's overflow-hidden
              doesn't clip it. Removed after the first send (composer remounts).
              Hidden below md: the global Header already shows the same model
              pill (ChatHeader portals it in both empty + active states), so on
              phones we give the squeezed textarea the whole row. */}
          {showModelPicker && onSelectConfig && (
            <div className="hidden md:block shrink-0 mb-0.5 self-end">
              <PillBar
                prominent
                selectedConfig={selectedConfig}
                configs={configs}
                selectedConfigId={selectedConfigId}
                onSelectConfig={onSelectConfig}
              />
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={activeCommand ? cmdPlaceholder(activeCommand) : (placeholder ?? t('input.placeholder'))}
            aria-label={activeCommand ? cmdPlaceholder(activeCommand) : (placeholder ?? t('input.placeholder'))}
            disabled={disabled}
            rows={1}
            dir={message ? detectDir(message) : i18n.dir()}
            className={cn(
              'flex-1 px-2 py-2.5',
              'border-none focus:outline-none resize-none',
              'bg-transparent text-foreground placeholder:text-foreground-tertiary',
              'overflow-y-auto transition-[height] duration-100',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'text-base'
            )}
            style={{ minHeight: '44px', maxHeight: '200px' }}
          />

          {/* Send / Stop button — keyboard hint lives in the Send tooltip */}
          <AnimatePresence mode="wait">
            {isStreaming ? (
              <motion.div
                key="stop"
                className="shrink-0 mb-0.5"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
              >
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={onStop}
                      aria-label={t('input.stop')}
                      className="h-9 w-9 rounded-full bg-destructive/10 text-destructive hover:bg-destructive/20"
                    >
                      <Square className="h-4 w-4 fill-current" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('input.stop')}</TooltipContent>
                </Tooltip>
              </motion.div>
            ) : (
              <motion.div
                key="send"
                className="shrink-0 mb-0.5"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
              >
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="submit"
                      variant="default"
                      size="icon"
                      disabled={!canSend}
                      aria-label={t('input.send')}
                      className="h-9 w-9 rounded-full bg-accent text-accent-foreground shadow-primary-glow hover:bg-accent/90 disabled:bg-background-tertiary disabled:text-foreground-tertiary disabled:shadow-none"
                    >
                      <ArrowUp className="h-5 w-5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <span className="flex items-center gap-1 text-xs">
                      <kbd dir="ltr" className="px-1.5 py-0.5 rounded text-[11px] font-semibold leading-none" style={{ background: '#fff', color: '#0F172A' }}>Enter</kbd>
                      <span>{t('input.hintSend')}</span>
                      <span className="mx-0.5">·</span>
                      <kbd dir="ltr" className="px-1.5 py-0.5 rounded text-[11px] font-semibold leading-none" style={{ background: '#fff', color: '#0F172A' }}>Shift + Enter</kbd>
                      <span>{t('input.hintNewline')}</span>
                    </span>
                  </TooltipContent>
                </Tooltip>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </form>
    </div>
  )
}

// ZIP archive chip body (icon + label). While the upload is in flight the chip
// shows a spinner + "opening… reading files"; once ready it shows the archive
// name and a compact one-line summary derived from `zip_entries` — the file
// count plus the first few entry names + "+N more". When `zip_entries` is
// absent (older backend / large archive) it falls back to the extracted-image
// count, then the file count alone. Filenames are LTR-locked (mixed scripts /
// paths read wrong under RTL). Spinner uses the CSS keyframe animation, not a
// framer infinite loop.
function ZipChip({ file, t }) {
  const opening = file.status === 'opening'
  const entries = Array.isArray(file.zip_entries) ? file.zip_entries : null
  const imageCount = file.image_count || 0

  // Build the ready-state summary line. Prefer real entries; cap the inline
  // name list at 3 and roll the rest into "+N more".
  let summary = null
  if (!opening) {
    const parts = []
    if (entries && entries.length > 0) {
      parts.push(t('input.zip.files_count', { count: entries.length }))
      const shown = entries.slice(0, 3).map((e) => e.name)
      const rest = entries.length - shown.length
      let names = shown.join(', ')
      if (rest > 0) names += `, ${t('input.zip.moreEntries', { count: rest })}`
      if (names) summary = `${parts[0]} · ${names}`
    } else if (imageCount > 0) {
      summary = t('input.zip.imagesExtracted', { count: imageCount })
    } else if (file.extracted_chars > 0) {
      summary = t('input.extractionOk')
    }
  }

  return (
    <>
      {opening ? (
        <Loader2 className="h-3.5 w-3.5 text-accent shrink-0 animate-spin" aria-hidden="true" />
      ) : (
        <FileArchive className="h-3.5 w-3.5 text-accent shrink-0" aria-hidden="true" />
      )}
      <div className="flex flex-col min-w-0">
        <span className="text-xs text-foreground truncate max-w-[160px]" dir="ltr">
          {opening ? t('input.zip.opening') : (file.name || file.filename)}
        </span>
        {summary && (
          <span className="text-[10px] text-foreground-tertiary truncate max-w-[160px]" dir="ltr">
            {summary}
          </span>
        )}
      </div>
    </>
  )
}
