import { useEffect, useMemo } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  BookOpen,
  Images,
  PanelLeftClose,
  SquarePen,
  UserRound,
  Wallet,
  X,
} from 'lucide-react'
import PolymindLogo from '@/components/brand/PolymindLogo'
import UserMenu from '@/components/layout/sidebar/UserMenu'
import ConversationListSection from '@/components/layout/sidebar/ConversationListSection'
import { CreditValue } from '@/components/ui/CreditValue'
import { CostValue } from '@/components/ui/CostValue'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { hasFeature } from '@/utils/featureFlags'
import { canSeePriceInOrg } from '@/utils/money'
import { calendarMonthRange, toApiWindow, sumUsageRequests } from '@/utils/usageWindow'
import { usageService } from '@/services/usageService'
import { fmtNumber } from '@/utils/persianLocale'
import { cn } from '@/utils/cn'

/**
 * Persistent app sidebar (prototype shell).
 * Desktop: 280px column, collapsible. Mobile: off-canvas, opened from the top bar.
 * History is chat-kind only — data / agent / OCR keep their own rails.
 */
export default function AppSidebar({
  collapsed,
  mobileOpen,
  onNavigate,
  onClose,
  onCollapse,
}) {
  const { t } = useTranslation('layout')
  const { user } = useAuth()
  const { pathname } = useLocation()
  const showGallery = hasFeature(user, 'image_studio')
  const showKnowledge = hasFeature(user, 'knowledge')

  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileOpen, onClose])

  const itemClass = (to) =>
    cn(
      'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors',
      pathname === to || pathname.startsWith(`${to}/`)
        ? 'bg-accent/10 text-accent'
        : 'text-foreground/90 hover:bg-background-tertiary',
    )

  return (
    <aside
      id="app-sidebar"
      className={cn(
        'z-40 flex h-full min-h-0 w-[280px] shrink-0 flex-col overflow-hidden border-e border-border bg-background-secondary text-foreground',
        'fixed inset-y-0 start-0 transition-transform duration-200',
        // Off-canvas only below lg. A bare rtl:/ltr: translate comes later in
        // the Tailwind sheet than lg:translate-x-0 and shoves the desktop
        // column off-screen, leaving a blank strip.
        'lg:static lg:translate-x-0',
        mobileOpen ? 'translate-x-0' : 'max-lg:ltr:-translate-x-full max-lg:rtl:translate-x-full',
        collapsed && 'lg:hidden',
      )}
    >
      <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
        <Link
          to="/dashboard"
          onClick={onNavigate}
          className="flex min-w-0 items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        >
          <PolymindLogo size={36} showWordmark wordmarkClassName="text-lg font-extrabold" />
        </Link>
        <button
          type="button"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary hover:bg-background-tertiary hover:text-foreground lg:hidden"
          onClick={onClose}
          aria-label={t('sidebar.closeMenu')}
        >
          <X className="h-4 w-4" />
        </button>
        <button
          type="button"
          className="hidden h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary hover:bg-background-tertiary hover:text-foreground lg:inline-flex"
          onClick={onCollapse}
          aria-label={t('sidebar.collapseSidebar')}
        >
          <PanelLeftClose className="h-4 w-4 rtl:-scale-x-100" />
        </button>
      </div>

      <div className="space-y-0.5 px-3 pt-1">
        <Link
          to="/chat"
          onClick={onNavigate}
          className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-foreground/90 hover:bg-background-tertiary"
        >
          <SquarePen className="h-4 w-4 shrink-0" />
          <span>{t('sidebar.newChat')}</span>
        </Link>
      </div>

      <div className="mt-3 space-y-0.5 px-3">
        {showGallery && (
          <Link to="/gallery" onClick={onNavigate} className={itemClass('/gallery')}>
            <Images className="h-4 w-4 shrink-0" />
            <span>{t('sidebar.gallery')}</span>
          </Link>
        )}
      </div>

      <div className="mt-3 space-y-0.5 px-3">
        <div className="px-3 pb-1 text-[11px] font-semibold text-foreground-tertiary">
          {t('sidebar.library')}
        </div>
        {showKnowledge && (
          <Link to="/knowledge" onClick={onNavigate} className={itemClass('/knowledge')}>
            <BookOpen className="h-4 w-4 shrink-0" />
            <span>{t('sidebar.knowledgeVault')}</span>
          </Link>
        )}
        <Link to="/configs" onClick={onNavigate} className={itemClass('/configs')}>
          <UserRound className="h-4 w-4 shrink-0" />
          <span>{t('sidebar.aiPersonas')}</span>
        </Link>
      </div>

      <div className="mt-3 flex min-h-0 flex-1 flex-col px-1">
        <div className="mb-1 px-3 text-[11px] font-semibold text-foreground-tertiary">
          {t('sidebar.history')}
        </div>
        <ConversationListSection
          showContent
          onNavClick={onNavigate}
          className="min-h-0 flex-1"
        />
      </div>

      <div className="border-t border-border p-3">
        <SidebarCredit />
        <UserMenu layout="sidebar" />
      </div>
    </aside>
  )
}

function SidebarCredit() {
  const { t } = useTranslation('dashboard')
  const { user } = useAuth()
  const { workspaces, currentWorkspace } = useWorkspace()
  const workspaceId = currentWorkspace?._id || null
  const priceVisible = canSeePriceInOrg(user, workspaces, workspaceId)
  const apiWindow = useMemo(() => toApiWindow(calendarMonthRange()), [])

  const { data } = useQuery({
    queryKey: ['usage', 'me', 'breakdown', workspaceId, apiWindow.from, apiWindow.to, 'feature'],
    queryFn: () =>
      usageService.getMyUsage({
        from: apiWindow.from,
        to: apiWindow.to,
        group_by: 'feature',
        workspace_id: workspaceId,
      }),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })

  if (!data) return null

  const totalCredits = data.total_credits ?? 0
  const totalRequests = sumUsageRequests(data.data)

  return (
    <button
      type="button"
      onClick={() =>
        window.dispatchEvent(new CustomEvent('open-settings', { detail: { section: 'usage' } }))
      }
      className="mb-2 flex w-full items-center gap-2 rounded-xl border border-border bg-background-tertiary/80 px-2.5 py-2 text-start transition hover:border-accent/40 hover:bg-background-tertiary"
    >
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-background-secondary text-emerald-500">
        <Wallet className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1 leading-tight">
        <span className="block text-[10px] text-foreground-tertiary">{t('hub.usageSnapshot.title')}</span>
        <span className="mt-0.5 flex items-center justify-between gap-2">
          <span className="truncate text-sm font-bold tabular-nums">
            {priceVisible ? (
              <CostValue usd={data.total_cost} />
            ) : (
              <CreditValue credits={totalCredits} suffixKey="credits.jetonSuffix" />
            )}
          </span>
          <span className="shrink-0 text-[11px] text-foreground-secondary">
            <span className="font-semibold text-foreground">{fmtNumber(totalRequests)}</span>{' '}
            {t('hub.usageSnapshot.requests')}
          </span>
        </span>
      </span>
    </button>
  )
}
