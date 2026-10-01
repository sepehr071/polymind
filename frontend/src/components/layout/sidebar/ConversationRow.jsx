import { memo, useState, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { MoreVertical, Pin, PinOff, Pencil, Archive, Trash2, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { fmtDate } from '@/utils/dateLocale'
import { cn } from '@/utils/cn'

// Absolute, Shamsi-aware date for the row's native `title` tooltip — the list
// itself groups by date bucket (Today / Yesterday / …), so the row is title-only
// and the precise timestamp lives on hover. Guarded: a malformed timestamp must
// not blank the row.
function absoluteTime(ts) {
  if (!ts) return undefined
  try {
    return fmtDate(new Date(ts), 'PPpp')
  } catch {
    return undefined
  }
}

/**
 * One conversation entry in the sidebar list — a ChatGPT-style text-first row.
 *
 * The trailing kebab menu is a SIBLING of the navigation <Link> (not nested):
 * a Radix dropdown trigger inside an anchor would either swallow the menu's
 * pointer events or fire navigation on open. It's absolutely positioned on the
 * inline-end edge and reveal-on-hover for pointer devices, always-visible on
 * touch (no hover there). Inline rename swaps the link for an <Input> so the row
 * stays put (no layout jump) while editing.
 */
function ConversationRow({
  conversation,
  active,
  onNavClick,
  onRename,
  onTogglePin,
  onArchive,
  onDelete,
  // Default chat path; Data Analyzer rail reuses this row with `/data-analyzer`.
  hrefBase = '/chat',
}) {
  const { t } = useTranslation('layout')
  const [editing, setEditing] = useState(false)
  const inputRef = useRef(null)
  // Guards against blur firing AFTER an Enter/Esc keydown already settled the
  // edit (Enter blurs the input) — without it we'd double-handle the rename.
  const settledRef = useRef(false)

  const title = conversation.title || t('conversationList.untitled')
  const whenAbs = absoluteTime(conversation.last_message_at || conversation.created_at)

  const startEditing = useCallback(() => {
    settledRef.current = false
    setEditing(true)
  }, [])

  const commitRename = useCallback(() => {
    if (settledRef.current) return
    settledRef.current = true
    const next = inputRef.current?.value.trim() ?? ''
    setEditing(false)
    // Only persist a real, changed title — empty or unchanged is a no-op cancel.
    if (next && next !== (conversation.title || '')) {
      onRename?.(conversation._id, next)
    }
  }, [conversation._id, conversation.title, onRename])

  const cancelRename = useCallback(() => {
    if (settledRef.current) return
    settledRef.current = true
    setEditing(false)
  }, [])

  const onKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        commitRename()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        cancelRename()
      }
    },
    [commitRename, cancelRename],
  )

  return (
    <li className="group relative">
      {editing ? (
        // Same vertical rhythm as the link so swapping in the editor doesn't
        // shift neighbouring rows. defaultValue + blur/Enter commit, Esc cancels.
        <div className="px-2 py-1">
          <Input
            ref={inputRef}
            size="sm"
            autoFocus
            defaultValue={conversation.title || ''}
            placeholder={t('conversationList.renamePlaceholder')}
            onKeyDown={onKeyDown}
            onBlur={commitRename}
            className="h-8"
          />
        </div>
      ) : (
        <>
          <Link
            to={`${hrefBase}/${conversation._id}`}
            onClick={onNavClick}
            aria-current={active ? 'page' : undefined}
            title={whenAbs}
            className={cn(
              // ChatGPT-style single-line row (~h-9): the date-bucket header is
              // the temporal context, so the row carries only the title.
              'flex items-center rounded-[9px] px-3 py-2 transition-colors duration-150',
              // pe-9 reserves room for the absolutely-positioned kebab so a long
              // title never slides under it.
              'pe-9 min-w-0',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              // Consistent UI System rail-item active state: flat accent-soft bg
              // + inset accent-line ring + accent text (NO glass blur).
              active
                ? 'text-accent'
                : 'text-foreground hover:bg-background-tertiary',
            )}
            style={
              active
                ? {
                    backgroundColor: 'hsl(var(--accent-soft))',
                    boxShadow: 'inset 0 0 0 1px hsl(var(--accent-line))',
                  }
                : undefined
            }
          >
            {/* Quiet title — position in the list already marks the chat list as
                the sidebar's primary surface; weight stays normal so rows don't
                out-shout the nav zones below. A small Users glyph marks chats
                shared with a team (own or shared-in). */}
            <span className="flex min-w-0 items-center gap-1.5">
              {conversation.share?.is_shared && (
                <Users className="h-3.5 w-3.5 shrink-0 text-foreground-tertiary" aria-hidden="true" />
              )}
              <span dir="auto" className="truncate text-start text-sm font-normal leading-tight min-w-0">
                {title}
              </span>
            </span>
          </Link>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={t('conversationList.moreOptions')}
                // Always reachable on touch (no hover); reveal-on-hover for
                // pointer devices; focus surfaces it for keyboard users.
                className={cn(
                  'absolute inset-y-0 end-1 my-auto h-7 w-7 flex items-center justify-center',
                  'rounded-md text-foreground-tertiary transition-opacity',
                  'hover:bg-background-tertiary hover:text-foreground',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  'opacity-100 focus:opacity-100 md:opacity-0 md:group-hover:opacity-100',
                )}
                onClick={(e) => {
                  // The trigger sits over the Link's row; stop the click from
                  // bubbling into navigation.
                  e.preventDefault()
                  e.stopPropagation()
                }}
              >
                <MoreVertical className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem onClick={() => onTogglePin?.(conversation)}>
                {conversation.is_pinned ? (
                  <>
                    <PinOff className="h-4 w-4 me-2" />
                    {t('conversationList.unpin')}
                  </>
                ) : (
                  <>
                    <Pin className="h-4 w-4 me-2" />
                    {t('conversationList.pin')}
                  </>
                )}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={startEditing}>
                <Pencil className="h-4 w-4 me-2" />
                {t('conversationList.rename')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onArchive?.(conversation)}>
                <Archive className="h-4 w-4 me-2" />
                {t('conversationList.archive')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete?.(conversation)}
                className="text-error focus:text-error"
              >
                <Trash2 className="h-4 w-4 me-2" />
                {t('conversationList.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
    </li>
  )
}

// Rows re-render only when their own conversation/active/callback identity
// changes — the list can be long, so memoize to keep typing in the search box
// from re-rendering every untouched row.
export default memo(ConversationRow)
