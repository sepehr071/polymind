import { useTranslation } from 'react-i18next'
import { Menu, PanelLeftOpen, SunMoon } from 'lucide-react'
import OrgSwitcher from '@/components/layout/OrgSwitcher'
import { cn } from '@/utils/cn'
import { useTheme } from '@/context/ThemeContext'

/**
 * Slim top bar. Brand and account live in the sidebar.
 * Org switcher sits in the end cluster (visual left in RTL, beside theme).
 * HeaderSlot portals stay so ChatHeader can inject the model pill.
 */
export default function AppTopBar({ sidebarCollapsed, mobileOpen, onOpenSidebar, onExpandSidebar }) {
  const { t } = useTranslation('layout')
  const { toggleTheme } = useTheme()

  return (
    <header
      className={cn(
        'relative z-20 flex h-14 shrink-0 items-center gap-2 border-b border-border/60 bg-background-secondary px-3',
      )}
    >
      <button
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary hover:bg-background-tertiary hover:text-foreground lg:hidden"
        onClick={onOpenSidebar}
        aria-label={t('sidebar.menu')}
        aria-controls="app-sidebar"
        aria-expanded={mobileOpen}
      >
        <Menu className="h-4 w-4" />
      </button>

      {sidebarCollapsed && (
        <button
          type="button"
          className="hidden h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary hover:bg-background-tertiary hover:text-foreground lg:inline-flex"
          onClick={onExpandSidebar}
          aria-label={t('sidebar.expandSidebar')}
        >
          <PanelLeftOpen className="h-4 w-4 rtl:-scale-x-100" />
        </button>
      )}

      <div id="header-route-start" className="inline-flex h-full min-w-0 items-center gap-2" />
      <div className="ms-auto inline-flex h-full min-w-0 items-center gap-2">
        <div id="header-route-end" className="inline-flex h-full min-w-0 items-center gap-2" />
        <OrgSwitcher />
        <button
          type="button"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-foreground-secondary hover:bg-background-tertiary hover:text-foreground"
          onClick={toggleTheme}
          aria-label={t('sidebar.theme')}
          title={t('sidebar.theme')}
        >
          <SunMoon className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
