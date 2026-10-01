import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Star, Inbox, Folder } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import Ptile from '@/components/teams/Ptile'
import { useProject } from '@/context/ProjectContext'
import { cn } from '@/lib/utils'

function firstLetter(name) {
  return (name || '?').trim().charAt(0).toUpperCase()
}

export default function ProjectSwitcher({ onClose, headless = false, pill = false }) {
  const { t } = useTranslation('layout')
  const nav = useNavigate()
  const projCtx = useProject()
  const { projects, currentProject, setActiveProject, setUnfiledView } = projCtx
  const [localOpen, setLocalOpen] = useState(false)
  // P1.22 — when rendered headlessly from ScopePillBar we use the context's
  // shared open state so the Header pill can act as the trigger anchor.
  const open = headless ? (projCtx.switcherOpen ?? false) : localOpen
  const setOpen = headless ? (projCtx.setSwitcherOpen ?? setLocalOpen) : setLocalOpen

  const pinnedProjects = useMemo(
    () => projects.filter((p) => p.pinned && !p.archived).slice(0, 5),
    [projects],
  )

  const recentProjects = useMemo(() => {
    const pinned = new Set(pinnedProjects.map((p) => p._id))
    return projects
      .filter((p) => !p.archived && !pinned.has(p._id))
      .sort((a, b) => {
        const ta = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0
        const tb = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0
        return tb - ta
      })
      .slice(0, 5)
  }, [projects, pinnedProjects])

  const displayName = currentProject?.name || t('workspaceSwitcher.unfiled')

  function selectProject(p) {
    setActiveProject(p)
    setOpen(false)
    onClose?.()
  }

  function selectUnfiled() {
    setUnfiledView()
    setOpen(false)
    onClose?.()
  }

  function goAllProjects() {
    setOpen(false)
    onClose?.()
    nav('/projects')
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {pill ? (
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="inline-flex h-9 min-w-0 items-center gap-2 rounded-md px-2 text-sm leading-none hover:bg-bg-2 transition"
            aria-label={t('projectSwitcher.pillAriaLabel')}
          >
            {currentProject ? (
              <>
                <span
                  style={{ background: currentProject.color || '#5c9aed' }}
                  className="h-4 w-4 shrink-0 rounded-sm"
                />
                <span className="hidden max-w-[140px] truncate leading-none text-fg-1 md:inline">
                  {currentProject.name}
                </span>
              </>
            ) : (
              <>
                <Inbox className="h-4 w-4 shrink-0 text-fg-3" />
                <span className="hidden italic leading-none text-fg-3 md:inline">
                  {t('scopeChip.unfiled')}
                </span>
              </>
            )}
            <ChevronDown className="h-4 w-4 shrink-0 text-fg-4" />
          </button>
        </DropdownMenuTrigger>
      ) : !headless ? (
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-bg-3 transition-colors text-start group"
          >
            {currentProject ? (
              <span
                style={{ background: currentProject.color || '#5c9aed' }}
                className="w-3 h-3 rounded-sm flex-shrink-0"
              />
            ) : (
              <Inbox className="h-3 w-3 text-fg-3 flex-shrink-0" />
            )}
            <span className="flex-1 truncate text-xs text-fg-1">{displayName}</span>
            <ChevronDown className="h-3.5 w-3.5 text-fg-3 flex-shrink-0 group-hover:text-fg-1 transition-colors" />
          </button>
        </DropdownMenuTrigger>
      ) : null}

      <DropdownMenuContent align="start" className="w-[220px] p-1">
        <DropdownMenuItem
          onClick={selectUnfiled}
          className={cn(
            'flex items-center gap-2 text-xs rounded-md px-2 py-1.5',
            !currentProject && 'bg-bg-3 font-medium',
          )}
        >
          <Inbox className="h-3.5 w-3.5 text-fg-3 flex-shrink-0" />
          <span className="italic text-fg-3">{t('workspaceSwitcher.unfiled')}</span>
        </DropdownMenuItem>

        {pinnedProjects.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-4">
              <Star className="h-2.5 w-2.5 inline-block me-1" />
              {t('sidebar.pinnedProjects')}
            </div>
            {pinnedProjects.map((p) => (
              <ProjectRow
                key={p._id}
                p={p}
                active={currentProject?._id === p._id}
                onClick={() => selectProject(p)}
              />
            ))}
          </>
        )}

        {recentProjects.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-4">
              <Folder className="h-2.5 w-2.5 inline-block me-1" />
              {t('projectSwitcher.recent')}
            </div>
            {recentProjects.map((p) => (
              <ProjectRow
                key={p._id}
                p={p}
                active={currentProject?._id === p._id}
                onClick={() => selectProject(p)}
              />
            ))}
          </>
        )}

        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={goAllProjects}
          className="text-xs text-fg-3 hover:text-fg-1 px-2 py-1.5"
        >
          {t('projectSwitcher.allProjects')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ProjectRow({ p, active, onClick }) {
  return (
    <DropdownMenuItem
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 text-xs rounded-md px-2 py-1.5',
        active && 'bg-bg-3 font-medium',
      )}
    >
      <Ptile
        size="sm"
        color={p.color || '#5c9aed'}
        icon={p.icon}
        letter={firstLetter(p.name)}
        className="!w-[18px] !h-[18px] !rounded-sm !text-[9px]"
      />
      <span className="truncate flex-1">{p.name}</span>
    </DropdownMenuItem>
  )
}
