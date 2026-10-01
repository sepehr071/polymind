import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { User, Users, Building2 } from 'lucide-react'
import { cn } from '@/utils/cn'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useProject } from '@/context/ProjectContext'
import { useAuth } from '@/context/AuthContext'

/**
 * SettingsBreadcrumb — compact signpost row that orients the user across the
 * three settings scopes: "Personal · Team: X · Company: Y". The segment for the
 * current `level` is highlighted (inert, aria-current), every other active
 * scope renders as a Link to its own settings route. A scope segment is omitted
 * entirely when that scope isn't active (no active team / no active company).
 *
 * Routes: personal=/settings, team=/projects/<pid>/settings,
 * company=/workspaces/<wid>/settings.
 *
 * @param {('personal'|'team'|'company')} level - which scope this page lives in.
 * @param {string} [name] - optional override for the current scope's label
 *   (falls back to the active workspace/project name from context).
 * @param {string} [wid] - route-resolved workspace id for the page being edited;
 *   preferred over the active-context id so links target the entity in the URL
 *   (which may differ from the active company/team).
 * @param {string} [pid] - route-resolved project id (same rationale as `wid`).
 */
function Divider() {
  return (
    <span className="text-foreground-tertiary/40 select-none" aria-hidden>
      ·
    </span>
  )
}

export default function SettingsBreadcrumb({ level, name, wid: widProp, pid: pidProp }) {
  const { t } = useTranslation('layout')
  const { currentWorkspace } = useWorkspace()
  const { currentProject } = useProject()
  const { user } = useAuth()

  // Prefer the route-resolved id (the entity actually being edited) over the
  // active-context id, so the segment links don't point at an unrelated scope
  // when editing a non-active company/team.
  const wid = widProp || currentWorkspace?._id || null
  const pid = pidProp || currentProject?._id || null
  const companyName = (level === 'company' && name) || currentWorkspace?.name || ''
  const teamName = (level === 'team' && name) || currentProject?.name || ''

  // Only link scopes the user can open — company/team settings are owner-only
  // (super-admin can always open). Avoids breadcrumb links that silent-bounce.
  const isSuperAdmin = user?.role === 'admin'
  const canOpenCompany =
    Boolean(wid) &&
    (isSuperAdmin ||
      level === 'company' ||
      (currentWorkspace?.type === 'team' &&
        (currentWorkspace?.role === 'owner' ||
          currentWorkspace?.member_role === 'owner' ||
          currentWorkspace?.member_role === 'admin')))
  const canOpenTeam =
    Boolean(pid) &&
    (isSuperAdmin ||
      level === 'team' ||
      currentProject?.member_role === 'owner')

  const segments = [
    {
      key: 'personal',
      active: true, // personal scope always exists for an authed user
      icon: User,
      label: t('settingsNav.personal'),
      to: '/settings',
    },
    {
      key: 'team',
      active: Boolean(pid) && (canOpenTeam || level === 'team'),
      icon: Users,
      label: teamName
        ? `${t('settingsNav.team')}: ${teamName}`
        : t('settingsNav.team'),
      to: canOpenTeam && pid ? `/projects/${pid}/settings` : null,
    },
    {
      key: 'company',
      active: Boolean(wid) && (canOpenCompany || level === 'company'),
      icon: Building2,
      label: companyName
        ? `${t('settingsNav.company')}: ${companyName}`
        : t('settingsNav.company'),
      to: canOpenCompany && wid ? `/workspaces/${wid}/settings` : null,
    },
  ].filter((s) => s.active || s.key === level)

  return (
    <nav
      aria-label={t('settingsNav.lookingFor')}
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-foreground-tertiary"
    >
      {segments.map((seg, i) => {
        const Icon = seg.icon
        const isCurrent = seg.key === level
        const inner = (
          <span className="inline-flex items-center gap-1.5">
            <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="truncate max-w-[14rem]">{seg.label}</span>
          </span>
        )
        return (
          <span key={seg.key} className="inline-flex items-center gap-2">
            {i > 0 && <Divider />}
            {isCurrent || !seg.to ? (
              <span
                aria-current={isCurrent ? 'page' : undefined}
                className={cn(
                  'inline-flex items-center rounded-md px-1.5 py-0.5',
                  isCurrent
                    ? 'bg-accent/10 font-medium text-foreground'
                    : 'text-foreground-tertiary',
                )}
              >
                {inner}
              </span>
            ) : (
              <Link
                to={seg.to}
                className="inline-flex items-center rounded-md px-1.5 py-0.5 text-foreground-secondary transition-colors hover:bg-background-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
              >
                {inner}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}
