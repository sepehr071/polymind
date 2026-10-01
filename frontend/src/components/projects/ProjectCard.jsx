import { MoreHorizontal, MessageSquare, Database, Clock, Star, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Ptile from '@/components/teams/Ptile'
import AvatarStack from '@/components/teams/AvatarStack'
import { fmtDistanceToNowSafe } from '@/utils/dateLocale'
import { fmtNumber } from '@/utils/persianLocale'
import { cn } from '@/lib/utils'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import HoverLift from '@/components/ui/hover-lift'

/**
 * ProjectCard — refined-variant card matching design parts/projects-index.jsx:264.
 *
 * @param {object} p Project payload (name, color, icon, description, pinned, tags, last_activity_at,
 *                   member_count, chats_count, knowledge_count, group, workspace_name, _id).
 * @param {(p: object) => void} onPin Toggle pin handler. Receives project; should flip pinned.
 * @param {(p: object) => void} onClick Open handler; defaults to noop.
 * @param {(p: object) => void} onMenu Optional kebab handler.
 * @param {Array<{name?: string, hue?: number, avatar_url?: string}>} members
 */
export default function ProjectCard({ p, onPin, onClick, onMenu, members = [] }) {
  const { t } = useTranslation('projects')
  const memberCount = p.member_count ?? members.length ?? 0
  const chats = (p.chats_count ?? p.chats ?? 0)
  const knowledge = p.knowledge_count ?? p.knowledge ?? 0
  const groupLabel = p.group || p.workspace_name || ''

  return (
    <HoverLift
      y={-3}
      onClick={() => onClick?.(p)}
      style={solidPanelSx({ radius: RADII.surface })}
      className={cn(
        'group relative cursor-pointer rounded-xl p-4',
        'transition-[border-color,box-shadow] hover:border-line-2 hover:shadow-lg',
      )}
    >
      {/* Top row */}
      <div className="flex items-start gap-3 mb-3">
        <Ptile
          color={p.color || '#5c9aed'}
          icon={p.icon}
          letter={(p.name || '?').charAt(0).toUpperCase()}
          size="md"
        />
        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <h3 className="m-0 truncate text-[14px] font-semibold text-fg-0 leading-tight">
              {p.name}
            </h3>
            {p.pinned && (
              <button
                type="button"
                aria-label={t('projectCard.unpinAriaLabel')}
                onClick={(e) => {
                  e.stopPropagation()
                  onPin?.(p)
                }}
                className="flex-shrink-0 inline-flex items-center justify-center rounded p-0.5 hover:bg-bg-3"
              >
                <Star className="h-3 w-3 text-warn fill-warn" />
              </button>
            )}
            {!p.pinned && onPin && (
              <button
                type="button"
                aria-label={t('projectCard.pinAriaLabel')}
                onClick={(e) => {
                  e.stopPropagation()
                  onPin?.(p)
                }}
                className="flex-shrink-0 inline-flex items-center justify-center rounded p-0.5 opacity-0 hover:bg-bg-3 group-hover:opacity-100 hover:opacity-100 focus-visible:opacity-100"
              >
                <Star className="h-3 w-3 text-fg-3" />
              </button>
            )}
          </div>
          {p.description && (
            <span className="truncate text-[11px] text-fg-3">{p.description}</span>
          )}
        </div>
        <button
          type="button"
          aria-label={t('projectCard.actionsAriaLabel')}
          onClick={(e) => {
            e.stopPropagation()
            onMenu?.(p)
          }}
          className="flex-shrink-0 inline-flex items-center justify-center rounded p-1 text-fg-3 hover:bg-bg-3 hover:text-fg-1"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Meta strip */}
      <div className="flex items-center gap-3 mb-3 text-[11px] text-fg-3">
        <span className="inline-flex items-center gap-1 tabular-nums">
          <MessageSquare className="h-3 w-3" />
          {fmtNumber(Number(chats))}
        </span>
        <span className="inline-flex items-center gap-1 tabular-nums">
          <Database className="h-3 w-3" />
          {fmtNumber(Number(knowledge))}
        </span>
        <span className="flex-1" />
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {fmtDistanceToNowSafe(p.last_activity_at) || '—'}
        </span>
      </div>

      {/* Tags */}
      {p.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {p.tags.map((t) => (
            <span
              key={t}
              className="inline-flex items-center rounded-full border border-line-2 bg-bg-3 px-1.5 py-0.5 font-mono text-[9.5px] text-fg-2"
            >
              #{t}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-3 border-t border-line">
        <div className="flex items-center gap-2 min-w-0">
          {members.length > 0 && <AvatarStack users={members} max={4} size="sm" />}
          <span className="inline-flex items-center gap-1 text-[11px] text-fg-3 tabular-nums">
            {members.length === 0 && <Users className="h-3 w-3" />}
            {fmtNumber(memberCount)}
          </span>
        </div>
        {groupLabel && (
          <span className="inline-flex items-center gap-1 rounded-full border border-line-2 bg-transparent px-2 py-0.5 text-[10.5px] text-fg-2">
            <Users className="h-3 w-3" />
            <span className="truncate max-w-[120px]">{groupLabel}</span>
          </span>
        )}
      </div>
    </HoverLift>
  )
}
