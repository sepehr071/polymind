import { useTranslation } from 'react-i18next'
import { useWorkspace } from '@/context/WorkspaceContext'
import ProjectSwitcher from './ProjectSwitcher'
import { cn } from '@/utils/cn'
import { TEAMS_UI_VISIBLE } from '@/constants/productFlags'

/**
 * Global header scope bar — the TEAM (project) switcher pill.
 *
 * Desktop: shows the team switcher ONLY. The company switcher lives in the
 * Sidebar brand row (WorkspaceHeader), so a company pill here would be a second
 * duplicate sitting right next to the team pill.
 *
 * Mobile (`< md`): hidden entirely. The Sidebar drawer hosts BOTH the company
 * and team switchers (WorkspaceHeader's mobile scope block); the phone header
 * has no room for them.
 *
 * The model picker lives per-surface (ChatHeader / ChatInput / Arena / Debate)
 * — the global header has no per-conversation context to drive it.
 */
export default function ScopePillBar() {
  if (!TEAMS_UI_VISIBLE) return null

  const { t } = useTranslation('layout')
  const { currentWorkspace } = useWorkspace()

  if (!currentWorkspace) return null

  return (
    <div
      className={cn(
        // Hidden on phones (switchers move to the drawer). On the glass Header
        // it stays translucent with a faint glass hairline on hover so it reads
        // as part of the frosted chrome system.
        'hidden md:inline-flex h-9 max-w-full items-center overflow-hidden rounded-lg',
        'border border-transparent transition',
        'hover:border-[rgb(var(--glass-border)/var(--glass-border-opacity))]',
      )}
      role="group"
      aria-label={t('scopePillBar.label')}
    >
      {/* Team pill — ProjectSwitcher in pill trigger mode (its own focusable
          trigger carrying projectSwitcher.pillAriaLabel). */}
      <span className="inline-flex min-w-0">
        <ProjectSwitcher pill />
      </span>
    </div>
  )
}
