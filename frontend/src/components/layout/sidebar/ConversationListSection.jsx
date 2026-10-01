import { useCallback, useEffect, useRef } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import useSidebarConversations from './useSidebarConversations'
import ConversationRow from './ConversationRow'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'

// Consistent UI System rail group header: 11px / 700 / uppercase / fg-3.
const GROUP_LABEL =
  'text-[11px] font-bold tracking-[0.08em] uppercase text-fg-3 px-3 pt-3.5 pb-1.5'

// Maps a hook fixed-bucket key to its i18n string. Month buckets carry their
// own pre-formatted (Shamsi/Gregorian) `label` and bypass this.
const FIXED_BUCKET_I18N = {
  today: 'conversationList.today',
  yesterday: 'conversationList.yesterday',
  prev7: 'conversationList.previous7Days',
  prev30: 'conversationList.previous30Days',
}

/**
 * The conversation history surface — the sidebar's primary block, sitting
 * directly under the New Chat button above the (collapsed) nav zones.
 * Search + pinned cluster + ChatGPT-style date-bucketed groups (Today /
 * Yesterday / Previous 7 Days / Previous 30 Days / per month-year) + infinite
 * scroll, collapsing to a single "view all history" icon-button when the rail
 * is collapsed.
 *
 * Props:
 *   showContent  boolean — sidebar expanded (search + list) vs collapsed rail
 *   onNavClick   () => void — close the drawer on mobile after navigating
 *   className    string — parent passes `flex-1 min-h-0` so the scroll region grows
 */
export default function ConversationListSection({ showContent, onNavClick, className }) {
  const { t } = useTranslation('layout')
  const { confirm, confirmDialog } = useConfirmDelete()
  const {
    search,
    setSearch,
    pinned,
    groups,
    conversations,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
    activeConversationId,
    rename,
    togglePin,
    archive,
    remove,
  } = useSidebarConversations()

  // Stable delete handler (confirm → remove) shared by every row — an inline
  // arrow here would defeat ConversationRow's memo() on each list re-render.
  const handleDelete = useCallback(
    async (conv) => {
      // Deleting a chat shared with a TEAM removes it for every member (live
      // access ends). A link share is unaffected — its snapshot + any saved
      // copies are independent — so only warn for team shares.
      const sharedWithTeam = (conv?.share?.teams?.length || 0) > 0
      if (
        await confirm({
          title: t('conversationList.deleteTitle'),
          description: sharedWithTeam
            ? t('conversationList.deleteSharedDescription')
            : t('conversationList.deleteDescription'),
          destructive: true,
        })
      ) {
        remove(conv)
      }
    },
    [confirm, remove, t],
  )

  // IntersectionObserver against the scroll container (NOT the viewport) so the
  // sentinel fires when it nears the bottom of the inner list, not the page.
  const scrollRef = useRef(null)
  const sentinelRef = useRef(null)
  // FLIP animation on add/remove/reorder (new chat, delete, pin/title-rename
  // reorder). auto-animate only animates the DIRECT children of the element it's
  // on, and the hook count must be STATIC — so we can't ref every per-bucket
  // <ul> in a loop. We attach it to exactly two lists: the Pinned cluster and
  // the "Today" bucket. Those cover the moments that actually animate — a brand
  // new chat lands in Today, and a pin/unpin removes from one of these two and
  // inserts into the other (each side animates independently). Older buckets
  // mutate only on delete/archive (rare) and render without FLIP. Both refs
  // skip initial mount, honor reduce-motion, and are RTL-safe by default.
  const [pinnedListRef] = useAutoAnimate()
  const [todayListRef] = useAutoAnimate()
  useEffect(() => {
    const root = scrollRef.current
    const target = sentinelRef.current
    if (!showContent || !root || !target || !hasNextPage) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { root, rootMargin: '120px' },
    )
    io.observe(target)
    return () => io.disconnect()
  }, [showContent, hasNextPage, isFetchingNextPage, fetchNextPage])

  // Collapsed rail (68px): render nothing. The chat list needs the expanded
  // sidebar, and the chat-history archive link was removed — so the nav zones
  // simply fill the rail instead.
  if (!showContent) return null

  // No conversations AND no active search → friendly two-liner (compact, this
  // is a 240px column — not the full empty-state component).
  const isEmpty = !isLoading && !isError && conversations.length === 0

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Search */}
      <div className="shrink-0 px-2 pb-1.5">
        <div className="relative">
          <Search className="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-foreground-tertiary" />
          {/* Canonical rail search: ~38px tall, radius10 (from the Input
              primitive), 3px accent-soft focus ring. */}
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('conversationList.searchPlaceholder')}
            aria-label={t('conversationList.searchPlaceholder')}
            className="ps-9 !min-h-[38px]"
          />
        </div>
      </div>

      {/* Scroll region — IntersectionObserver root */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-2">
        {isLoading ? (
          <ul className="space-y-1 pt-1" aria-hidden="true">
            {/* h-9 ≈ real single-line row (py-2 + title) — no jump on load. */}
            {Array.from({ length: 5 }).map((_, i) => (
              <li key={i}>
                <Skeleton className="h-9 w-full" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="px-2 py-6 text-center">
            <p className="text-xs text-foreground-tertiary mb-2">{t('conversationList.loadError')}</p>
            <Button variant="ghost" size="sm" onClick={() => refetch()}>
              {t('conversationList.retry')}
            </Button>
          </div>
        ) : isEmpty ? (
          <div className="px-3 py-8 text-center">
            <p className="text-sm font-medium text-foreground-secondary">
              {t('conversationList.empty')}
            </p>
            <p className="mt-1 text-xs text-foreground-tertiary">
              {t('conversationList.emptyHint')}
            </p>
          </div>
        ) : conversations.length === 0 ? (
          // Active search, zero matches.
          <p className="px-3 py-8 text-center text-xs text-foreground-tertiary">
            {t('conversationList.noResults')}
          </p>
        ) : (
          <>
            {/* Pinned cluster — always above the date buckets, its own FLIP list. */}
            {pinned.length > 0 && (
              <div className="mb-1">
                <div className={GROUP_LABEL}>{t('conversationList.pinned')}</div>
                <ul ref={pinnedListRef} className="space-y-0.5">
                  {pinned.map((conv) => (
                    <ConversationRow
                      key={conv._id}
                      conversation={conv}
                      active={conv._id === activeConversationId}
                      onNavClick={onNavClick}
                      onRename={rename}
                      onTogglePin={togglePin}
                      onArchive={archive}
                      onDelete={handleDelete}
                    />
                  ))}
                </ul>
              </div>
            )}

            {/* Date-bucketed groups, newest-first. Each non-empty bucket renders
                its header (fixed buckets map key → t(); month buckets carry a
                pre-formatted Shamsi/Gregorian label) + its own <ul>. Only the
                topmost bucket (Today, or the newest non-empty one) gets the
                FLIP ref — see hook comment. */}
            {groups.map((group, idx) => (
              <div key={group.key} className="mb-1">
                <div className={GROUP_LABEL}>
                  {group.label ?? t(FIXED_BUCKET_I18N[group.key] || group.key)}
                </div>
                <ul ref={idx === 0 ? todayListRef : undefined} className="space-y-0.5">
                  {group.items.map((conv) => (
                    <ConversationRow
                      key={conv._id}
                      conversation={conv}
                      active={conv._id === activeConversationId}
                      onNavClick={onNavClick}
                      onRename={rename}
                      onTogglePin={togglePin}
                      onArchive={archive}
                      onDelete={handleDelete}
                    />
                  ))}
                </ul>
              </div>
            ))}

            {/* Infinite-scroll sentinel + in-flight indicator. */}
            <div ref={sentinelRef} aria-hidden="true" />
            {isFetchingNextPage && (
              <div className="flex items-center justify-center py-3 text-foreground-tertiary">
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
            )}
          </>
        )}
      </div>

      {confirmDialog}
    </div>
  )
}
