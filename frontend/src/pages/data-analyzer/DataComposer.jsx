import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'motion/react'
import {
  Paperclip, X, File, Loader2, Square, ArrowUp,
  FileText, AlertTriangle, FileSpreadsheet,
} from 'lucide-react'
import { cn } from '../../utils/cn'
import PillBar from '../../components/chat/PillBar'
import { Button } from '../../components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent } from '../../components/ui/tooltip'
import { DATA_ANALYZER_MODEL_LABEL } from '../../constants/slashCommands'

// Must stay in sync with useChatMessages.handleFileUpload allow-list (subset of
// chat) AND backend Data Analyzer sandbox ingest types.
const DATA_ACCEPT = '.csv,.xlsx,.xls,.xlsm,.json,.txt,.parquet,.jsonl,.pdf,.docx,.pptx,.html,.md,.xml,.tsv,.png,.jpg,.jpeg,.webp'

/**
 * DataComposer — upload-first composer for Data Analyzer.
 * Leaner than ChatInput: no model picker, web-search, or slash commands.
 */
export default function DataComposer({
  onSend,
  onFileUpload,
  onStop,
  isStreaming = false,
  disabled = false,
  // True once conversation already has attachments (backend reuses dataset).
  hasDataset = false,
  // Filenames already bound to this analysis (sticky strip under chips).
  datasetLabels = [],
  // Restore after failed send / starter pick (parent remounts via key).
  initialMessage = '',
  initialFiles = [],
}) {
  const { t, i18n } = useTranslation('chat')

  const [message, setMessage] = useState(initialMessage)
  const [files, setFiles] = useState(initialFiles)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)
  const dragDepthRef = useRef(0)

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px'
    }
  }, [message])

  const hasPendingUpload = files.some((f) => f.status === 'opening')
  const hasUsableData = files.length > 0 || hasDataset
  const hasQuestion = message.trim().length > 0
  // Require a real question — file-only send is useless for analysis and the
  // backend rejects empty message content with 400 anyway.
  const canSend =
    hasQuestion &&
    hasUsableData &&
    !disabled &&
    !hasPendingUpload

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

  const uploadFiles = async (fileList) => {
    const selectedFiles = Array.from(fileList || [])
    if (selectedFiles.length === 0 || !onFileUpload) return
    setUploading(true)
    try {
      for (const file of selectedFiles) {
        const staging = makeStaging()
        const uploaded = await onFileUpload(file, staging)
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

  const handlePaste = async (e) => {
    if (disabled || !onFileUpload) return
    const pasted = Array.from(e.clipboardData?.files || [])
    if (pasted.length === 0) return
    e.preventDefault()
    await uploadFiles(pasted)
  }

  const fileKey = (f) => f.placeholder_id || f.upload_id || (f.name + '-' + f.size)
  const removeFile = (fileToRemove) => {
    const target = fileKey(fileToRemove)
    setFiles((prev) => prev.filter((f) => fileKey(f) !== target))
  }

  const handleSubmit = (e) => {
    e?.preventDefault()
    if (!canSend || isStreaming) return
    onSend(message.trim(), files)
    setMessage('')
    setFiles([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const detectDir = (text) => /[֑-߿‏‫‮יִ-﷽ﹰ-ﻼ]/.test(text) ? 'rtl' : 'ltr'

  return (
    <div className="px-3 md:px-4 pb-3 md:pb-4 bg-transparent">
      {/* Sticky dataset strip — files already bound to this analysis. */}
      {hasDataset && datasetLabels.length > 0 && files.length === 0 && (
        <div className="mx-auto mb-2 max-w-[768px] flex flex-wrap items-center gap-1.5 px-0.5">
          <span className="text-[11px] font-medium text-foreground-tertiary">
            {t('dataAnalyzer.datasetLabel')}
          </span>
          {datasetLabels.map((name) => (
            <span
              key={name}
              className="inline-flex max-w-[160px] items-center gap-1 rounded-md border border-border bg-background-tertiary px-2 py-0.5 text-[11px] text-foreground-secondary"
              dir="auto"
              title={name}
            >
              <FileSpreadsheet className="h-3 w-3 shrink-0 text-accent" aria-hidden="true" />
              <span className="truncate">{name}</span>
            </span>
          ))}
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'relative mx-auto max-w-[768px] border overflow-hidden transition-colors',
          'bg-background shadow-[0_6px_24px_-12px_rgb(15_23_42_/_0.25)]',
          dragOver ? 'border-accent ring-2 ring-accent/40' : 'border-border',
        )}
        style={{ borderRadius: 16 }}
      >
        {dragOver && (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center gap-2 bg-accent/10 text-accent text-sm font-medium" style={{ borderRadius: 16 }}>
            <FileSpreadsheet className="h-4 w-4" />
            <span>{t('dataAnalyzer.dropToAttach')}</span>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={DATA_ACCEPT}
          onChange={handleFileSelect}
          className="hidden"
        />

        <AnimatePresence>
          {files.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="flex flex-wrap gap-2 px-3 pt-3"
            >
              {files.map((file) => {
                const label = fileDisplayName(file)
                const spreadsheet = isSpreadsheet(file)
                return (
                <motion.div
                  key={fileKey(file)}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  className="relative group flex items-center gap-2 px-2 py-1.5 bg-background-tertiary rounded-lg border border-border"
                  title={label}
                >
                  {file.status === 'opening' ? (
                    <Loader2 className="h-3.5 w-3.5 text-accent shrink-0 animate-spin" aria-hidden="true" />
                  ) : spreadsheet ? (
                    <FileSpreadsheet className="h-3.5 w-3.5 text-accent shrink-0" />
                  ) : (
                    <File className="h-3.5 w-3.5 text-foreground-secondary shrink-0" />
                  )}
                  <span className="text-xs text-foreground truncate max-w-[160px]" dir="ltr">
                    {label}
                  </span>

                  {/* "text" badge is for docs/OCR — hide on spreadsheets (reads as "this is text", not Excel). */}
                  {!spreadsheet && file.extraction_status === 'ok' && (
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

                  {file.status !== 'opening' && (
                    <button
                      type="button"
                      onClick={() => removeFile(file)}
                      className="h-4 w-4 rounded-full flex items-center justify-center opacity-60 hover:opacity-100 hover:bg-background transition-opacity shrink-0"
                      aria-label={t('input.removeFile', { name: label })}
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  )}
                </motion.div>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center gap-1 px-3 pt-2">
          <PillBar
            locked
            prominent
            lockedLabel={DATA_ANALYZER_MODEL_LABEL}
            lockedTitle={t('dataAnalyzer.modelLocked')}
          />
        </div>

        <div className="flex items-end gap-1 px-2 py-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled || uploading}
                aria-label={t('dataAnalyzer.attachData')}
                className="shrink-0 mb-0.5 h-9 w-9 rounded-full"
              >
                {uploading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Paperclip className="h-5 w-5" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('dataAnalyzer.attachData')}</TooltipContent>
          </Tooltip>

          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={t('dataAnalyzer.placeholder')}
            aria-label={t('dataAnalyzer.placeholder')}
            disabled={disabled}
            rows={1}
            dir={message ? detectDir(message) : i18n.dir()}
            className={cn(
              'flex-1 px-2 py-2.5',
              'border-none focus:outline-none resize-none',
              'bg-transparent text-foreground placeholder:text-foreground-tertiary',
              'overflow-y-auto transition-[height] duration-100',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'text-base',
            )}
            style={{ minHeight: '44px', maxHeight: '200px' }}
          />

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
                    {!hasUsableData
                      ? t('dataAnalyzer.attachFirstHint')
                      : !hasQuestion
                        ? t('dataAnalyzer.typeQuestionHint')
                        : (
                        <span className="flex items-center gap-1 text-xs">
                          <kbd dir="ltr" className="px-1.5 py-0.5 rounded text-[11px] font-semibold leading-none" style={{ background: '#fff', color: '#0F172A' }}>Enter</kbd>
                          <span>{t('input.hintSend')}</span>
                          <span className="mx-0.5">·</span>
                          <kbd dir="ltr" className="px-1.5 py-0.5 rounded text-[11px] font-semibold leading-none" style={{ background: '#fff', color: '#0F172A' }}>Shift + Enter</kbd>
                          <span>{t('input.hintNewline')}</span>
                        </span>
                      )}
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

function fileDisplayName(file) {
  return (
    file.name ||
    file.filename ||
    file.original_name ||
    'file'
  )
}

function isSpreadsheet(file) {
  const name = fileDisplayName(file).toLowerCase()
  const mime = (file.mime_type || file.type || '').toLowerCase()
  return (
    /\.(csv|tsv|xlsx|xls|xlsm|parquet|jsonl)$/.test(name) ||
    mime.includes('csv') ||
    mime.includes('spreadsheet') ||
    mime.includes('excel') ||
    mime.includes('parquet') ||
    // Office Excel MIME when the browser omits extension on the staged object
    mime === 'application/vnd.ms-excel' ||
    mime === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
    mime === 'application/vnd.ms-excel.sheet.macroenabled.12'
  )
}
