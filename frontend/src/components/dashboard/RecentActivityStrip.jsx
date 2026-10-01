import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { MessageSquare, BarChart3, Image as ImageIcon } from 'lucide-react'
import { chatService } from '@/services/chatService'
import { imageService } from '@/services/imageService'
import { useWorkspace } from '@/context/WorkspaceContext'
import { Card } from '@/components/ui/card'
import { IconTile } from '@/components/ui/icon-tile'
import { fmtDistanceToNowSafe } from '@/utils/dateLocale'
import { cn } from '@/utils/cn'

/**
 * RecentActivityStrip — a small grid of "recent work" cards on the dashboard hub
 * so users resume fast (open the last chat / analysis / image session in one
 * tap).
 *
 * A wrapping grid (not a horizontal scroller) is deliberate: RTL horizontal
 * scroll has inconsistent scroll-origin behavior across browsers and was
 * clipping the first card. A grid shows every card fully, no scroll math.
 *
 * Data REUSES existing queries — no new endpoints:
 *  - Conversations: `chatService.getConversations` (the SAME source the sidebar
 *    `useSidebarConversations` + Data Analyzer `useDataConversations` hooks use),
 *    personal scope (`project_id: 'null'`) so it never leaks across workspaces.
 *    `kind: 'chat'` → `/chat/<id>`, `kind: 'data'` → `/data-analyzer/<id>`.
 *  - Images: `imageService.getHistory` (payload-less; rows carry a small `thumb`
 *    data-URI) → `/image-studio`.
 *
 * Merged, sorted newest-first, capped at MAX_CARDS. Cards lead with the image
 * thumb when present, else a tone-tinted IconTile. Relative time via the
 * locale-aware `fmtDistanceToNowSafe` (Shamsi digits under `fa`).
 *
 * Renders NOTHING (null) when there's no recent activity, while loading, or on a
 * failed query — no empty-state placeholder.
 */

const MAX_CARDS = 6

export default function RecentActivityStrip() {
  const { t } = useTranslation('dashboard')
  const { currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null

  const { data: chatData } = useQuery({
    queryKey: ['conversations', workspaceId, 'unfiled', '', 'chat', 'hub-recent'],
    queryFn: () =>
      chatService.getConversations({ page: 1, limit: MAX_CARDS, project_id: 'null', workspace_id: workspaceId, kind: 'chat' }),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })

  const { data: dataData } = useQuery({
    queryKey: ['conversations', workspaceId, 'unfiled', '', 'data', 'hub-recent'],
    queryFn: () =>
      chatService.getConversations({ page: 1, limit: MAX_CARDS, project_id: 'null', workspace_id: workspaceId, kind: 'data' }),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })

  const { data: imageData } = useQuery({
    queryKey: ['imageHistory', { page: 1, limit: MAX_CARDS, favoritesOnly: false, search: '' }, 'hub-recent'],
    queryFn: () => imageService.getHistory({ page: 1, limit: MAX_CARDS }),
    staleTime: 60_000,
  })

  const untitled = t('history.untitled')

  const items = useMemo(() => {
    const merged = []

    for (const c of chatData?.conversations || []) {
      merged.push({
        id: `chat:${c._id}`,
        to: `/chat/${c._id}`,
        title: c.title || untitled,
        icon: MessageSquare,
        tone: 'sky',
        kindLabel: t('hub.recentKind.chat'),
        thumb: null,
        ts: c.last_message_at || c.updated_at || c.created_at,
      })
    }

    for (const c of dataData?.conversations || []) {
      merged.push({
        id: `data:${c._id}`,
        to: `/data-analyzer/${c._id}`,
        title: c.title || untitled,
        icon: BarChart3,
        tone: 'amber',
        kindLabel: t('hub.recentKind.data'),
        thumb: null,
        ts: c.last_message_at || c.updated_at || c.created_at,
      })
    }

    for (const img of imageData?.images || []) {
      merged.push({
        id: `image:${img._id}`,
        to: '/image-studio',
        title: img.prompt || untitled,
        icon: ImageIcon,
        tone: 'emerald',
        kindLabel: t('hub.recentKind.image'),
        thumb: img.thumb || null,
        ts: img.created_at,
      })
    }

    return merged
      .sort((a, b) => {
        const ta = a.ts ? new Date(a.ts).getTime() : 0
        const tb = b.ts ? new Date(b.ts).getTime() : 0
        return tb - ta
      })
      .slice(0, MAX_CARDS)
  }, [chatData, dataData, imageData, untitled, t])

  if (items.length === 0) return null

  return (
    <section>
      <div className="mb-3">
        <h2 className="text-[17px] font-bold text-foreground">{t('hub.sections.recent')}</h2>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {items.map((item) => (
          <Link
            key={item.id}
            to={item.to}
            className={cn(
              'group block rounded-2xl no-underline',
              'transition-transform duration-200 ease-out hover:-translate-y-0.5',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            )}
          >
            <Card hover className="flex h-full items-center gap-3 p-3.5 text-start">
              {item.thumb ? (
                <img
                  src={item.thumb}
                  alt=""
                  className="h-9 w-9 flex-shrink-0 rounded-xl border border-border object-cover"
                />
              ) : (
                <IconTile icon={item.icon} tone={item.tone} size="lg" />
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-foreground">{item.title}</div>
                <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-foreground-tertiary">
                  <span className="font-medium text-foreground-secondary">{item.kindLabel}</span>
                  {item.ts && (
                    <>
                      <span aria-hidden>·</span>
                      <span>{fmtDistanceToNowSafe(item.ts)}</span>
                    </>
                  )}
                </p>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </section>
  )
}
