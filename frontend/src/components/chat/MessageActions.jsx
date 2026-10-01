import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, Check, Pencil, RefreshCw, ThumbsUp, ThumbsDown, ChevronDown } from 'lucide-react'
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
} from '../ui/dropdown-menu'
import { cn } from '../../utils/cn'
import SaveToKnowledgeButton from '../knowledge/SaveToKnowledgeButton'

const PERSISTED_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const ActionBtn = ({ onClick, label, disabled, active, children, className }) => (
  <Tooltip>
    <TooltipTrigger asChild>
      <button
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={active}
        className={cn(
          // Touch-comfortable on phones (≥40px); compact on desktop.
          'w-7 h-7 max-md:w-10 max-md:h-10 rounded-md grid place-items-center',
          'transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
          active
            ? 'text-accent hover:bg-background-tertiary'
            : 'text-foreground-tertiary hover:bg-background-tertiary hover:text-foreground',
          className
        )}
      >
        {children}
      </button>
    </TooltipTrigger>
    <TooltipContent>{label}</TooltipContent>
  </Tooltip>
)

/**
 * Message action bar rendered under every message turn.
 *
 * User turn:      Copy · Edit
 * Assistant turn: Copy · ThumbsUp · ThumbsDown · Regenerate(split) · [Save]
 *
 * Hover-gating + last-assistant always-on visibility is owned by the ChatWindow
 * wrapper (this component is always rendered; the wrapper controls opacity).
 */
const MessageActions = memo(function MessageActions({
  messageId,
  content,
  role,
  conversationId,
  message,
  isCopied,
  onCopy,
  onEdit,
  onRegenerate,
  onFeedback,
  regenOptions = [],
}) {
  const { t } = useTranslation('chat')
  const isUser = role === 'user'

  const feedback = message?.metadata?.feedback ?? null

  // Toggle semantics: clicking the active rating again clears it (→ null).
  const handleRate = (rating) => {
    if (!onFeedback) return
    onFeedback(messageId, feedback === rating ? null : rating)
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5 mt-1.5 h-7 max-md:h-auto">
      {/* Copy — both roles */}
      <ActionBtn
        onClick={() => onCopy?.(content, messageId)}
        label={isCopied ? t('messageActions.copied') : t('messageActions.copy')}
      >
        {isCopied
          ? <Check className="h-3.5 w-3.5 text-success" />
          : <Copy className="h-3.5 w-3.5" />}
      </ActionBtn>

      {isUser ? (
        /* User actions: Edit — only when parent wired a handler (agent omits). */
        onEdit ? (
          <ActionBtn onClick={onEdit} label={t('messageActions.edit')}>
            <Pencil className="h-3.5 w-3.5" />
          </ActionBtn>
        ) : null
      ) : (
        /* Assistant actions: feedback, regen (split), save */
        <>
          {onFeedback ? (
            <>
              <ActionBtn
                onClick={() => handleRate('up')}
                label={t('messageActions.goodResponse')}
                active={feedback === 'up'}
              >
                <ThumbsUp className={cn('h-3.5 w-3.5', feedback === 'up' && 'fill-current')} />
              </ActionBtn>
              <ActionBtn
                onClick={() => handleRate('down')}
                label={t('messageActions.badResponse')}
                active={feedback === 'down'}
              >
                <ThumbsDown className={cn('h-3.5 w-3.5', feedback === 'down' && 'fill-current')} />
              </ActionBtn>
            </>
          ) : null}

          {/* Regenerate — split button: primary one-click (same model) +
              optional chevron dropdown to pick a different model. */}
          {onRegenerate && PERSISTED_ID.test(String(messageId || '')) && (
            <div className="flex items-center">
              <ActionBtn
                onClick={() => onRegenerate(messageId)}
                label={t('messageActions.regenerate')}
                className="group/regen"
              >
                <RefreshCw className="h-3.5 w-3.5 transition-transform group-hover/regen:rotate-180 duration-300" />
              </ActionBtn>

              {regenOptions.length > 0 && (
                <DropdownMenu>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <DropdownMenuTrigger asChild>
                        <button
                          aria-label={t('messageActions.tryAgainWith')}
                          className={cn(
                            'w-5 h-7 max-md:w-8 max-md:h-10 rounded-md grid place-items-center',
                            'text-foreground-tertiary hover:bg-background-tertiary hover:text-foreground',
                            'transition-colors data-[state=open]:bg-background-tertiary data-[state=open]:text-foreground'
                          )}
                        >
                          <ChevronDown className="h-3 w-3" />
                        </button>
                      </DropdownMenuTrigger>
                    </TooltipTrigger>
                    <TooltipContent>{t('messageActions.tryAgainWith')}</TooltipContent>
                  </Tooltip>
                  <DropdownMenuContent align="start" className="min-w-[12rem]">
                    <DropdownMenuLabel>{t('messageActions.tryAgainWith')}</DropdownMenuLabel>
                    {regenOptions.map((opt) => (
                      <DropdownMenuItem
                        key={opt.id}
                        onSelect={() => onRegenerate(messageId, opt.id)}
                      >
                        <span className="truncate">{opt.name}</span>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          )}

          {/* Save to knowledge — self-contained button + dialog. Kept inline
              (it is the only overflow candidate; a 1-item "…" menu isn't worth
              the extra click). */}
          {conversationId && message && (
            <SaveToKnowledgeButton
              message={message}
              conversationId={conversationId}
              sourceType="chat"
            />
          )}
        </>
      )}
    </div>
  )
})

export default MessageActions
