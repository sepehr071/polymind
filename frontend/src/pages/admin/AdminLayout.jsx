import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LayoutDashboard,
  Users as UsersIcon,
  Building2,
  Shield,
  Eye,
  ArrowLeft,
  BadgePercent,
} from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Super-admin shell. One title, six pills, then the page.
 * Holding, profit, templates, prompt templates, and audit stay routed
 * but sit off this strip.
 */
const TABS = [
  {
    to: '/admin',
    end: true,
    icon: LayoutDashboard,
    labelKey: 'shell.tab.overview',
    titleKey: 'shell.title.overview',
    subtitleKey: 'shell.subtitle.overview',
  },
  { to: '/admin/companies', icon: Building2, labelKey: 'shell.tab.companies' },
  {
    to: '/admin/pricing',
    icon: BadgePercent,
    labelKey: 'shell.tab.pricing',
    titleKey: 'shell.title.pricing',
    subtitleKey: 'shell.subtitle.pricing',
  },
  { to: '/admin/dlp', icon: Shield, labelKey: 'shell.tab.safety' },
  { to: '/admin/users', icon: UsersIcon, labelKey: 'shell.tab.users' },
  { to: '/admin/features', icon: Eye, labelKey: 'shell.tab.flags' },
]

function tabForPath(pathname) {
  if (pathname === '/admin') return TABS[0]
  return TABS.find((tab) => tab.to !== '/admin' && pathname.startsWith(tab.to)) || null
}

export default function AdminLayout() {
  const { t } = useTranslation('admin')
  const { pathname } = useLocation()
  const tab = tabForPath(pathname)
  const TitleIcon = tab?.icon || LayoutDashboard

  return (
    <div className="h-app-dvh overflow-y-auto bg-background">
      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-8">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <TitleIcon className="h-5 w-5 shrink-0 text-accent" />
              <h1 className="text-2xl font-extrabold text-foreground">
                {t(tab?.titleKey || 'shell.title.senior')}
              </h1>
            </div>
            <p className="mt-1 text-sm text-foreground-secondary">
              {t(tab?.subtitleKey || 'shell.subtitle.senior')}
            </p>
          </div>
          <Link
            to="/dashboard"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-background-tertiary hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5 rtl:rotate-180" />
            {t('shell.back')}
          </Link>
        </div>

        <nav className="mb-5 flex gap-1 overflow-x-auto rounded-full bg-background-secondary p-1.5 ring-1 ring-border">
          {TABS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'inline-flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground shadow-sm'
                    : 'text-foreground-secondary hover:text-foreground',
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>

        {/* PageShell owns a viewport scroller. Flatten it so this page scrolls once. */}
        <div className="[&>div]:!h-auto [&>div]:!overflow-visible [&>div]:!bg-transparent [&>div]:!p-0">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
