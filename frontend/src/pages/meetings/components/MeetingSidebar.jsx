import { Link } from 'react-router-dom'
import {
  ArrowRight,
  CheckSquare,
  ClipboardList,
  FileText,
  Gavel,
  HelpCircle,
  AlertCircle,
  Mail,
  MessageSquare,
  Package,
  RefreshCw,
  Share2,
  Sparkles,
  Users,
  Clock,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import MeetingStatus from './MeetingStatus'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils/cn'
import { dirOf, formatJalali } from '@/utils/rtl'

const ICON_MAP = {
  sparkles: Sparkles,
  check: CheckSquare,
  gavel: Gavel,
  help: HelpCircle,
  circleQ: AlertCircle,
  mail: Mail,
  package: Package,
  doc: ClipboardList,
  list: FileText,
  chat: MessageSquare,
}

/**
 * Inner content of the meeting-detail rail (header + nav + footer actions) with
 * NO `<aside>`/glass wrapper. Rendered both inside the desktop `<aside>` (see
 * `MeetingSidebar` below) and inside a mobile `<Sheet>` on the detail page, so a
 * single source of truth feeds both layouts. Tabs: summary, actions, decisions,
 * qa, open, email, minutes, transcript, discuss.
 */
export function MeetingSidebarContent({
  meetingId,
  title,
  duration,
  speakerCount,
  createdAt,
  active,
  onSelect,
  counts,
  initialStatus,
  onShare,
  onRegenerate,
  regenDisabled,
  regenPending,
  discussDisabled,
}) {
  const { t } = useTranslation('meetings')

  const GROUPS = [
    {
      label: t('sidebar.groupInsights'),
      items: [
        { id: 'summary', label: t('sidebar.summary'), icon: 'sparkles', desc: t('sidebar.desc.summary') },
        { id: 'actions', label: t('sidebar.actions'), icon: 'check', desc: t('sidebar.desc.actions') },
        { id: 'decisions', label: t('sidebar.decisions'), icon: 'gavel', desc: t('sidebar.desc.decisions') },
        { id: 'qa', label: t('sidebar.qa'), icon: 'help', desc: t('sidebar.desc.qa') },
        { id: 'open', label: t('sidebar.open'), icon: 'circleQ', desc: t('sidebar.desc.open') },
      ],
    },
    {
      label: t('sidebar.groupOutputs'),
      items: [
        { id: 'pack', label: t('sidebar.pack'), icon: 'package', desc: t('sidebar.desc.pack') },
        { id: 'email', label: t('sidebar.email'), icon: 'mail', desc: t('sidebar.desc.email') },
        { id: 'minutes', label: t('sidebar.minutes'), icon: 'doc', desc: t('sidebar.desc.minutes') },
      ],
    },
    {
      label: t('sidebar.groupSources'),
      items: [
        { id: 'transcript', label: t('sidebar.transcript'), icon: 'list', desc: t('sidebar.desc.transcript') },
      ],
    },
    {
      label: t('sidebar.groupExplore'),
      items: [
        {
          id: 'discuss',
          label: t('sidebar.discuss'),
          icon: 'chat',
          desc: t('sidebar.desc.discuss'),
          disabled: discussDisabled,
        },
      ],
    },
  ]

  return (
    <>
      <div className="border-b border-border px-4 py-4">
        <Link
          to="/meetings"
          className="inline-flex items-center gap-1.5 text-xs text-foreground-secondary transition-colors hover:text-foreground"
        >
          <ArrowRight className="size-3 rtl:rotate-180" />
          {t('detail.allMeetings')}
        </Link>
        <h2
          dir={title ? dirOf(title) : undefined}
          className="mt-2 line-clamp-2 text-sm font-semibold leading-snug tracking-tight text-foreground"
        >
          {title || '—'}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-foreground-tertiary">
          {duration && (
            <span
              className="inline-flex items-center gap-1 font-mono tabular-nums"
              dir="ltr"
            >
              <Clock className="size-3" />
              {duration}
            </span>
          )}
          {speakerCount != null && (
            <>
              <span aria-hidden="true">•</span>
              <span className="inline-flex items-center gap-1">
                <Users className="size-3" />
                {t('card.speakerCount', { count: speakerCount })}
              </span>
            </>
          )}
          {createdAt && (
            <>
              <span aria-hidden="true">•</span>
              <span>{formatJalali(createdAt)}</span>
            </>
          )}
        </div>
        <div className="mt-2.5">
          <MeetingStatus meetingId={meetingId} initialStatus={initialStatus} />
        </div>
      </div>

      <nav
        className="flex-1 overflow-y-auto px-2.5 py-3 scroll-thin"
        aria-label={t('sidebar.groupInsights')}
      >
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-2.5">
            <div className="px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">
              {group.label}
            </div>
            <div className="flex flex-col gap-px">
              {group.items.map((tab) => {
                const Icon = ICON_MAP[tab.icon]
                const isActive = active === tab.id
                const count = counts?.[tab.id]
                const isDisabled = !!tab.disabled
                return (
                  <button
                    key={tab.id}
                    onClick={() => !isDisabled && onSelect(tab.id)}
                    disabled={isDisabled}
                    title={tab.desc}
                    aria-label={tab.desc ? `${tab.label} — ${tab.desc}` : tab.label}
                    className={cn(
                      'flex flex-col rounded-[9px] px-2.5 py-2 text-start text-sm transition-colors',
                      isActive
                        ? 'bg-amber-500/10 text-amber-700 ring-1 ring-inset ring-amber-500/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25'
                        : 'text-foreground-secondary hover:bg-background-tertiary hover:text-foreground',
                      isDisabled && 'cursor-not-allowed opacity-50 hover:bg-transparent hover:text-foreground-secondary'
                    )}
                  >
                    <span className="flex w-full items-center gap-2.5">
                      <Icon className="size-3.5 shrink-0" />
                      <span className="flex-1">{tab.label}</span>
                      {count != null && count > 0 && (
                        <span
                          className={cn(
                            'rounded-full px-1.5 py-px font-mono text-[10px] tabular-nums',
                            isActive
                              ? 'bg-amber-500/15 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300'
                              : 'bg-background-tertiary text-foreground-tertiary'
                          )}
                        >
                          {count}
                        </span>
                      )}
                    </span>
                    {isActive && tab.desc && (
                      <span className="mt-1 ps-6 text-[11px] font-normal leading-snug text-foreground-tertiary">
                        {tab.desc}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="flex gap-1.5 border-t border-border p-3">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={onShare}
          className="flex-1"
        >
          <Share2 className="size-3" />
          {t('sidebar.share')}
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={onRegenerate}
          disabled={regenDisabled}
          className="flex-1"
        >
          <RefreshCw className={cn('size-3', regenPending && 'animate-spin')} />
          {t('sidebar.regenerate')}
        </Button>
      </div>
    </>
  )
}

/**
 * Desktop left rail for meeting detail: a fixed 256px flat surf2 `<aside>`
 * wrapping `MeetingSidebarContent`. The caller gates it `hidden md:flex` so it
 * disappears below the `md` breakpoint, where the detail page surfaces the same
 * content via a mobile `<Sheet>` instead. Flat panel — glass is for chrome only.
 */
export default function MeetingSidebar({ className, ...props }) {
  return (
    <aside
      className={cn(
        'flex w-64 shrink-0 flex-col border-e border-border bg-background-secondary',
        className,
      )}
    >
      <MeetingSidebarContent {...props} />
    </aside>
  )
}
