import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../../utils/cn'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer'

const ROLE_STYLES = {
  assistant: 'bg-violet/15 text-violet border-violet/30',
  tool:      'bg-teal/15 text-teal border-teal/30',
  user:      'bg-accent/15 text-accent border-accent/30',
  final:     'bg-success/15 text-success border-success/30',
}

const RICH_ROLES = new Set(['assistant', 'final'])

function MessageCard({ msg }) {
  const { t } = useTranslation('automate')
  const [screenshotOpen, setScreenshotOpen] = useState(false)
  const isFinal = msg.type === 'final'
  const roleStyle = ROLE_STYLES[isFinal ? 'final' : msg.role] || ROLE_STYLES.assistant
  const renderRich = isFinal || RICH_ROLES.has(msg.role)

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className={cn(
          'flex gap-3 items-start p-3 rounded-lg border transition-colors',
          isFinal
            ? 'border-success/30 bg-success/5 hover:bg-success/10'
            : 'border-border bg-background-secondary hover:bg-background-tertiary'
        )}
      >
        <Badge
          variant="outline"
          className={cn('text-xs capitalize shrink-0 mt-0.5', roleStyle)}
        >
          {isFinal ? t('roles.final') : t(`roles.${msg.role}`, { defaultValue: msg.role })}
        </Badge>

        <div className="flex-1 min-w-0">
          {msg.summary ? (
            renderRich ? (
              <div className="markdown-content">
                <MarkdownRenderer content={msg.summary} />
              </div>
            ) : (
              <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap break-words">
                {msg.summary}
              </p>
            )
          ) : (
            <p className="text-xs text-foreground-tertiary italic">
              {msg.type || t('roles.message')}
            </p>
          )}
        </div>

        {msg.screenshot_url && (
          <button
            onClick={() => setScreenshotOpen(true)}
            className="shrink-0 rounded overflow-hidden border border-border hover:border-accent transition-colors"
            title={t('stream.screenshotTitle')}
          >
            <img
              src={msg.screenshot_url}
              alt={t('stream.screenshotAlt')}
              className="w-16 h-10 object-cover"
            />
          </button>
        )}
      </motion.div>

      <Dialog open={screenshotOpen} onOpenChange={setScreenshotOpen}>
        <DialogContent className="max-w-3xl p-2">
          <img
            src={msg.screenshot_url}
            alt={t('stream.screenshotFullAlt')}
            className="w-full rounded-lg"
          />
        </DialogContent>
      </Dialog>
    </>
  )
}

const TERMINAL_STATUSES = new Set(['completed', 'error', 'stopped', 'timed_out'])

export default function EventStream({ messages, status, currentTask }) {
  const { t } = useTranslation('automate')
  const bottomRef = useRef(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    const sentinel = bottomRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      ([entry]) => setAutoScroll(entry.isIntersecting),
      { root: null, rootMargin: '0px 0px -40px 0px', threshold: 0 }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages, currentTask, autoScroll])

  if (messages.length === 0) {
    if (status === 'idle' || TERMINAL_STATUSES.has(status)) return null
    return (
      <p className="p-4 text-sm text-foreground-tertiary">{t('stream.waiting')}</p>
    )
  }

  const lastSummary = messages[messages.length - 1]?.summary
  const showFinal = currentTask?.output && lastSummary !== currentTask.output

  return (
    <div className="flex flex-col gap-2 relative">
      <p className="text-xs font-semibold text-foreground-tertiary uppercase tracking-wider mb-1">
        {messages.length !== 1
          ? t('stream.header_other', { count: messages.length })
          : t('stream.header', { count: messages.length })}
      </p>

      <AnimatePresence initial={false}>
        {messages.map((msg, i) => (
          <MessageCard key={msg.cursor_id ?? i} msg={msg} />
        ))}

        {showFinal && (
          <MessageCard
            key="synthetic-final"
            msg={{ role: 'assistant', summary: currentTask.output, type: 'final' }}
          />
        )}
      </AnimatePresence>

      <div ref={bottomRef} />

      {!autoScroll && (
        <button
          type="button"
          onClick={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}
          className="sticky bottom-3 self-center flex items-center gap-1 ps-2 pe-3 py-1.5 rounded-full text-xs font-medium bg-accent/10 text-accent ring-1 ring-inset ring-accent/20 shadow-sm transition-colors hover:bg-accent/15"
        >
          <ChevronDown className="h-3.5 w-3.5" />
          {t('stream.jumpToLatest')}
        </button>
      )}
    </div>
  )
}
