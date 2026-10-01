import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { fmtDate } from '@/utils/dateLocale'
import { Eye } from 'lucide-react'
import Section from '@/components/teams/Section'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { workspaceService } from '@/services/workspaceService'

// Canonical chip tones on intact scales only (accent/sky, emerald, amber, rose).
// violet/pink/zinc-500 are flat tokens under the tailwind.config override and
// silently break — never use them for chips.
const ACTION_BADGE_TONES = {
  workspace_invite: 'bg-accent/15 text-accent border-accent/30',
  project_create: 'bg-ok/15 text-ok border-ok/30',
  project_update: 'bg-warn/15 text-warn border-warn/30',
  project_archive: 'bg-fg-3/15 text-fg-2 border-fg-3/30',
  project_share: 'bg-accent/15 text-accent border-accent/30',
  group_join: 'bg-ok/15 text-ok border-ok/30',
  invite_rotate: 'bg-warn/15 text-warn border-warn/30',
  member_role_change: 'bg-accent/15 text-accent border-accent/30',
}

function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return fmtDate(d, 'MMM d, yyyy HH:mm')
}

function getInitials(name, email) {
  if (name) return name.slice(0, 2).toUpperCase()
  if (email) return email.slice(0, 2).toUpperCase()
  return '??'
}

function ActionBadge({ action, fallback }) {
  const tone =
    ACTION_BADGE_TONES[action] ||
    'bg-bg-3 text-fg-2 border-line'
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}
    >
      {action || fallback}
    </span>
  )
}

function DetailsCell({ details }) {
  if (!details || typeof details !== 'object') {
    return <span className="text-fg-3">—</span>
  }
  const keys = Object.keys(details)
  if (keys.length === 0) return <span className="text-fg-3">—</span>
  // Render up to 3 key:value pairs as compact muted text.
  const shown = keys.slice(0, 3).map((k) => {
    const v = details[k]
    let val = v
    if (v && typeof v === 'object') val = JSON.stringify(v)
    if (typeof val === 'string' && val.length > 40) val = val.slice(0, 40) + '…'
    return (
      <span key={k} className="text-[11px]">
        <span className="text-fg-3">{k}:</span>{' '}
        <span className="text-fg-2">{String(val)}</span>
      </span>
    )
  })
  return (
    <div className="flex flex-col gap-0.5 max-w-[480px]">{shown}</div>
  )
}

/**
 * AuditTab — workspace-scoped activity feed.
 * Wired to GET /api/workspaces/<wid>/audit (admin-gated).
 */
export default function AuditTab({ wid, members = [] }) {
  const { t } = useTranslation('projects')
  const [entries, setEntries] = useState([])
  const [nextBefore, setNextBefore] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [actionFilter, setActionFilter] = useState('__all__')
  const [actorFilter, setActorFilter] = useState('__all__')
  const [sinceFilter, setSinceFilter] = useState('')

  const ACTION_OPTIONS = useMemo(
    () => [
      { value: '__all__', label: t('workspaceSettings.audit.filters.allActions') },
      { value: 'workspace_invite', label: t('workspaceSettings.audit.filters.workspaceInvite') },
      { value: 'project_create', label: t('workspaceSettings.audit.filters.projectCreate') },
      { value: 'project_update', label: t('workspaceSettings.audit.filters.projectUpdate') },
      { value: 'project_archive', label: t('workspaceSettings.audit.filters.projectArchive') },
      { value: 'project_share', label: t('workspaceSettings.audit.filters.projectShare') },
      { value: 'group_join', label: t('workspaceSettings.audit.filters.groupJoin') },
      { value: 'invite_rotate', label: t('workspaceSettings.audit.filters.inviteRotate') },
      { value: 'member_role_change', label: t('workspaceSettings.audit.filters.memberRoleChange') },
    ],
    [t],
  )

  const memberOptions = useMemo(() => {
    return (members || [])
      .filter((m) => m.user)
      .map((m) => ({
        value: String(m.user._id || m.user.id),
        label:
          m.user.display_name ||
          m.user.email ||
          (m.user._id
            ? t('workspaceSettings.audit.userPlaceholder', { id: m.user._id.slice(0, 6) })
            : t('workspaceSettings.audit.unknownUser')),
      }))
  }, [members, t])

  const buildParams = useCallback(
    (before = null) => {
      const params = { limit: 50 }
      if (before) params.before = before
      if (actionFilter && actionFilter !== '__all__')
        params.action = actionFilter
      if (actorFilter && actorFilter !== '__all__')
        params.actor_id = actorFilter
      if (sinceFilter) {
        // Convert YYYY-MM-DD → ISO at start of day.
        try {
          const d = new Date(`${sinceFilter}T00:00:00`)
          if (!Number.isNaN(d.getTime())) params.since = d.toISOString()
        } catch {
          // ignore
        }
      }
      return params
    },
    [actionFilter, actorFilter, sinceFilter],
  )

  const load = useCallback(
    async (mode = 'reset') => {
      if (mode === 'reset') {
        setLoading(true)
      } else {
        setLoadingMore(true)
      }
      try {
        const before = mode === 'append' ? nextBefore : null
        const data = await workspaceService.getAudit(wid, buildParams(before))
        const newEntries = data?.entries || []
        if (mode === 'append') {
          setEntries((prev) => [...prev, ...newEntries])
        } else {
          setEntries(newEntries)
        }
        setNextBefore(data?.next_before || null)
      } catch (err) {
        const status = err.response?.status
        if (status === 403) {
          toast.error(t('workspaceSettings.audit.errors.forbidden'))
        } else {
          toast.error(t('workspaceSettings.audit.errors.loadFailed'))
        }
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [wid, buildParams, nextBefore, t],
  )

  // Initial load + reload on filter change.
  useEffect(() => {
    load('reset')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid, actionFilter, actorFilter, sinceFilter])

  return (
    <div className="space-y-6">
      <Section
        title={t('workspaceSettings.audit.title')}
        hint={t('workspaceSettings.audit.hint')}
      >
        {/* Filter row */}
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label className="text-[11px] text-fg-3">{t('workspaceSettings.audit.headers.action')}</Label>
            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ACTION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <Label className="text-[11px] text-fg-3">{t('workspaceSettings.audit.headers.actor')}</Label>
            <Select value={actorFilter} onValueChange={setActorFilter}>
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder={t('workspaceSettings.audit.anyActor')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">{t('workspaceSettings.audit.anyActor')}</SelectItem>
                {memberOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <Label className="text-[11px] text-fg-3" htmlFor="audit-since">
              {t('workspaceSettings.audit.since')}
            </Label>
            <Input
              id="audit-since"
              type="date"
              value={sinceFilter}
              onChange={(e) => setSinceFilter(e.target.value)}
              className="w-[160px]"
            />
          </div>

          {(actionFilter !== '__all__' ||
            actorFilter !== '__all__' ||
            sinceFilter) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setActionFilter('__all__')
                setActorFilter('__all__')
                setSinceFilter('')
              }}
            >
              {t('projectsPage.clearFilters')}
            </Button>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div className="px-4 py-6 text-sm text-fg-3">{t('workspaceSettings.audit.loading')}</div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
            <Eye className="h-6 w-6 text-fg-3" />
            <p className="text-sm text-fg-2">{t('workspaceSettings.audit.empty')}</p>
            <p className="text-xs text-fg-3 max-w-md">
              {t('workspaceSettings.audit.emptyHint')}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-line bg-bg-2/50">
            <table className="w-full text-start text-[13px]">
              <thead>
                <tr className="border-b border-line bg-bg-2/50 text-[12px] font-bold text-fg-2">
                  <th className="px-3 py-2.5 text-start whitespace-nowrap">{t('workspaceSettings.audit.headers.when')}</th>
                  <th className="px-3 py-2.5 text-start">{t('workspaceSettings.audit.headers.actor')}</th>
                  <th className="px-3 py-2.5 text-start">{t('workspaceSettings.audit.headers.action')}</th>
                  <th className="px-3 py-2.5 text-start">{t('workspaceSettings.audit.headers.target')}</th>
                  <th className="px-3 py-2.5 text-start">{t('workspaceSettings.audit.headers.details')}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => {
                  const actor = e.actor || {}
                  const display =
                    actor.display_name || actor.email || t('workspaceSettings.audit.systemActor')
                  return (
                    <tr
                      key={e._id}
                      className="border-b border-line last:border-0 align-top"
                    >
                      <td className="px-3 py-2.5 text-fg-2 whitespace-nowrap">
                        {fmtDateTime(e.created_at)}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <Avatar size="sm">
                            {actor.avatar_url && (
                              <AvatarImage
                                src={actor.avatar_url}
                                alt={display}
                              />
                            )}
                            <AvatarFallback className="text-[10px]">
                              {getInitials(actor.display_name, actor.email)}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex flex-col min-w-0">
                            <span className="text-fg-1 truncate">
                              {display}
                            </span>
                            {actor.display_name && actor.email && (
                              <span className="text-[11px] text-fg-3 truncate">
                                {actor.email}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <ActionBadge action={e.action} fallback={t('workspaceSettings.audit.unknownAction')} />
                      </td>
                      <td className="px-3 py-2.5 text-fg-2">
                        {e.target_type ? (
                          <div className="flex flex-col gap-0.5">
                            <span className="text-xs capitalize">
                              {e.target_type.replace(/_/g, ' ')}
                            </span>
                            {e.target_id && (
                              <span className="font-mono text-[10px] text-fg-3 truncate max-w-[320px]">
                                {String(e.target_id)}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-fg-3">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <DetailsCell details={e.details} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Load more */}
        {nextBefore && (
          <div className="mt-3 flex justify-center">
            <Button
              variant="outline"
              size="sm"
              disabled={loadingMore}
              onClick={() => load('append')}
            >
              {loadingMore ? t('common:actions.loading') : t('workspaceSettings.audit.loadMore')}
            </Button>
          </div>
        )}
      </Section>
    </div>
  )
}
