import { useNavigate } from 'react-router-dom'
import {
  ShieldAlert,
  Settings,
  LogOut,
  Sun,
  Moon,
  Languages,
  LifeBuoy,
  Users,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { TEAMS_UI_VISIBLE } from '@/constants/productFlags'
import { useAuth } from '@/context/AuthContext'
import { useTheme } from '@/context/ThemeContext'
import { useLanguage } from '@/context/LanguageContext'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { getInitials } from '@/utils/avatarColor'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'

/**
 * UserMenu — the account dropdown in the global top bar (AppTopBar). An
 * avatar-only trigger opening a menu with: Teams, Helper, User Settings (opens
 * the settings modal via the `open-settings` window event), the single
 * holding-admin entry (super-admin only), language + theme toggles, and sign out.
 *
 * It carries the per-account surfaces that used to sit at the bottom of the old
 * fixed sidebar; company-level deep-links (company settings / invite / new
 * company) live in the WorkspaceSwitcher popover beside it.
 *
 * Built on the Radix DropdownMenu primitive for keyboard dismiss (Esc), focus
 * trap + roving-focus arrow nav, and proper menu/menuitem roles.
 */
export default function UserMenu({ layout = 'icon' }) {
  const { t } = useTranslation('layout')
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const { language, setLanguage } = useLanguage()
  const navigate = useNavigate()

  if (!user) return null

  const name = user.profile?.display_name || user.email?.split('@')[0]
  const sidebar = layout === 'sidebar'

  // Gate ALL admin entries on the super-admin role to match the adminOnly route
  // guard (managers would otherwise see these and bounce off the guard).
  const isAdmin = user.role === 'admin'

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t('userMenu.account')}
          className={
            sidebar
              ? 'flex w-full items-center gap-2 rounded-xl px-1 py-1 text-start hover:bg-background-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60'
              : 'inline-flex h-9 w-9 items-center justify-center rounded-full transition-transform duration-150 ease-out hover:scale-[1.04] active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background'
          }
        >
          <Avatar size="sm">
            <AvatarFallback className="text-sm" seed={user.email || user.id}>
              {getInitials(name || '')}
            </AvatarFallback>
          </Avatar>
          {sidebar && (
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-sm font-semibold text-foreground">{name}</span>
              <span className="block truncate text-[11px] text-foreground-tertiary">{user.email}</span>
            </span>
          )}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        side={sidebar ? 'top' : 'bottom'}
        align={sidebar ? 'start' : 'end'}
        sideOffset={8}
        className="min-w-[15rem] p-1"
      >
        <div className="px-2 py-1.5">
          <p className="truncate text-sm font-medium text-foreground">
            {name}
          </p>
          <p className="truncate text-xs text-foreground-tertiary">{user.email}</p>
        </div>
        <DropdownMenuSeparator />

        {TEAMS_UI_VISIBLE && (
          <DropdownMenuItem onSelect={() => navigate('/projects')} className="h-11">
            <Users className="h-4 w-4" />
            {t('sidebar.projects')}
          </DropdownMenuItem>
        )}

        {/* Helper moved out of the high-traffic nav into the account menu. */}
        <DropdownMenuItem onSelect={() => navigate('/helper')} className="h-11">
          <LifeBuoy className="h-4 w-4" />
          {t('sidebar.supportAssistant')}
        </DropdownMenuItem>

        {/* Opens the ChatGPT-style settings modal (AppShell listens for this
            event). The standalone /settings route still exists for deep links. */}
        <DropdownMenuItem
          onSelect={() =>
            window.dispatchEvent(new CustomEvent('open-settings', { detail: { section: 'profile' } }))
          }
          className="h-11"
        >
          <Settings className="h-4 w-4" />
          {t('sidebar.userSettings')}
        </DropdownMenuItem>

        {isAdmin && (
          <>
            <DropdownMenuSeparator />
            {/* SINGLE consolidated admin entry — lands on /admin, where the
                AdminLayout sub-nav owns the rest. */}
            <DropdownMenuItem onSelect={() => navigate('/admin')} className="h-11">
              <ShieldAlert className="h-4 w-4" />
              {t('sidebar.holdingAdmin')}
            </DropdownMenuItem>
          </>
        )}

        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(e) => {
            // Keep the menu open for in-place toggles.
            e.preventDefault()
            setLanguage(language === 'fa' ? 'en' : 'fa')
          }}
          className="h-11"
        >
          <Languages className="h-4 w-4" />
          <span className="flex-1 text-start">{t('userMenu.language')}</span>
          <span dir="ltr" className="text-xs text-foreground-tertiary">
            {language === 'fa' ? t('userMenu.switchToEnglish') : t('userMenu.switchToPersian')}
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(e) => {
            e.preventDefault()
            toggleTheme()
          }}
          className="h-11"
        >
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          <span className="flex-1 text-start">{t('userMenu.theme')}</span>
          <span className="text-xs text-foreground-tertiary">
            {theme === 'dark' ? t('userMenu.switchToLight') : t('userMenu.switchToDark')}
          </span>
        </DropdownMenuItem>

        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={handleLogout}
          className="h-11 focus:bg-error/10 focus:text-error"
        >
          <LogOut className="h-4 w-4" />
          {t('sidebar.signOut')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
