import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { fmtDate, fmtDistanceToNow } from '@/utils/dateLocale'
import { fmtNumber, fmtCurrency } from '@/utils/persianLocale'
import { useAuth } from '@/context/AuthContext'
import { useWorkspace } from '@/context/WorkspaceContext'
import { CostValue } from '@/components/ui/CostValue'
import {
  Building2,
  ShieldCheck,
  Key,
  Download,
  Settings,
  Plus,
  ChevronRight,
  FileText,
  Activity,
  Layers,
  RotateCw,
  // Bounded audit-log action glyphs, resolved by name via the allowlist below.
  // Named imports keep lucide tree-shakeable; the old `import * as Lucide`
  // barrel pinned all ~1962 icons into the eager entry chunk.
  UserPlus,
  UserMinus,
  Mail,
  MailX,
  FolderPlus,
  Folder,
  FolderX,
  MessageSquare,
} from 'lucide-react'
import { DynamicIcon } from 'lucide-react/dynamic'

// Allowlist for the bounded, fixed audit-log `ACTION_ICON` targets (PascalCase)
// + the page's own default glyphs. Keys are separator-stripped + lowercased so
// `MessageSquare`/`message-square`/`message_square` all hit one key. Open-ended,
// seed-authored project/group icons go through `DynamicLucide` instead (the
// seed uses names like smartphone/gitBranch/compass/globe — far past this set).
const ACTION_ICONS = {
  userplus: UserPlus,
  userminus: UserMinus,
  mail: Mail,
  mailx: MailX,
  settings: Settings,
  building2: Building2,
  folderplus: FolderPlus,
  folder: Folder,
  folderx: FolderX,
  layers: Layers,
  messagesquare: MessageSquare,
  activity: Activity,
  filetext: FileText,
}

/**
 * Resolve a bounded audit-log action icon (PascalCase name) to its lucide
 * component, falling back to Activity. Used only for the fixed ACTION_ICON set.
 */
function resolveActionIcon(name) {
  if (!name || typeof name !== 'string') return Activity
  const key = name.replace(/[-_\s]+/g, '').toLowerCase()
  return ACTION_ICONS[key] || Activity
}

// Normalize a stored icon token (PascalCase export, camelCase, snake/kebab, or
// short design alias) to a lucide kebab-case id for <DynamicIcon>. Mirrors
// teams/Ptile.toKebabIconName so both render the same DB icon strings.
const DYNAMIC_ICON_ALIASES = { message: 'message-circle' }
function toKebabIconName(name) {
  if (!name || typeof name !== 'string') return null
  const raw = name.trim()
  if (!raw) return null
  const lower = raw.toLowerCase()
  if (DYNAMIC_ICON_ALIASES[lower]) return DYNAMIC_ICON_ALIASES[lower]
  return raw
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/([a-zA-Z])([0-9])/g, '$1-$2')
    .replace(/[-_\s]+/g, '-')
    .toLowerCase()
    .replace(/^-+|-+$/g, '')
}

/**
 * IconTile-compatible component that lazily renders a lucide glyph from an
 * open-ended stored icon NAME (project/group `icon`). Forwards `className` etc.
 * to <DynamicIcon>; unknown names render nothing (the tile then shows empty,
 * matching the prior barrel's `Lucide[name]` miss behavior for the IconTile).
 */
function DynamicLucide({ name, ...props }) {
  const kebab = toKebabIconName(name)
  if (!kebab) return null
  return <DynamicIcon name={kebab} {...props} />
}

/**
 * Build an IconTile `icon` component for a stored project/group icon name,
 * or `null` when no name is set (caller supplies its own fallback component).
 */
function dynamicIconFor(name) {
  if (!name || typeof name !== 'string' || !name.trim()) return null
  return (props) => <DynamicLucide name={name} {...props} />
}
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { IconTile } from '@/components/ui/icon-tile'
import { cn } from '@/lib/utils'
import { workspaceService } from '@/services/workspaceService'
import { solidPanelSx } from '@/theme/glass'
import { RADII } from '@/theme/tokens'
import PageHeader from '@/components/layout/PageHeader'
import PageShell from '@/components/layout/PageShell'
import Section from '@/components/teams/Section'
import StatTile from '@/components/teams/StatTile'

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------


function formatRelative(value) {
  if (!value) return '—'
  try {
    const d = typeof value === 'string' ? new Date(value) : value
    if (Number.isNaN(d.getTime())) return '—'
    return fmtDistanceToNow(d, { addSuffix: true })
  } catch {
    return '—'
  }
}

function formatNumber(n) {
  return fmtNumber(Number(n || 0))
}

// Cycle through canonical IconTile tones (intact-scale hues only) so list rows
// stay visually varied without raw hex. Tones map to the app's tinted-tile
// gradient + ring + inset highlight per ui/icon-tile.jsx.
const TILE_TONES = ['sky', 'emerald', 'amber', 'rose', 'accent']
function toneForIndex(i) {
  return TILE_TONES[((i % TILE_TONES.length) + TILE_TONES.length) % TILE_TONES.length]
}

// Map common audit-log actions to a lucide icon name.
const ACTION_ICON = {
  member_added: 'UserPlus',
  member_removed: 'UserMinus',
  invite_sent: 'Mail',
  invite_revoked: 'MailX',
  workspace_updated: 'Settings',
  workspace_created: 'Building2',
  project_created: 'FolderPlus',
  project_updated: 'Folder',
  project_deleted: 'FolderX',
  group_created: 'Layers',
  group_deleted: 'Layers',
  conversation_created: 'MessageSquare',
}

// ----------------------------------------------------------------------------
// ActivityRow
// ----------------------------------------------------------------------------

function getActivityIcon(action) {
  const name = ACTION_ICON[action] || 'Activity'
  return name
}

function describeActivity(a, t) {
  const action = a.action || t('workspacePage.activity.eventFallback')
  const verb = action.replaceAll('_', ' ')
  const targetType = a.target_type || ''
  const targetName =
    a.details?.name ||
    a.details?.target_name ||
    a.details?.email ||
    (a.target_id ? targetType : '')
  return { verb, what: targetName || targetType || '' }
}

function ActivityRow({ entry, t }) {
  const iconName = getActivityIcon(entry.action)
  const ActivityIcon = resolveActionIcon(iconName)
  const { verb, what } = describeActivity(entry, t)
  const who =
    entry.actor_name ||
    entry.actor_email ||
    entry.admin_email ||
    entry.admin_name ||
    t('workspacePage.activity.systemActor')
  const when = formatRelative(entry.created_at)

  return (
    <div className="flex items-start gap-3">
      <IconTile icon={ActivityIcon} tone="neutral" size="md" />
      <div className="flex grow flex-col" style={{ gap: 1 }}>
        <div className="text-xs leading-snug">
          <span className="font-medium text-fg-0">{who}</span>
          <span className="text-fg-3"> {verb} </span>
          {what && <span className="text-fg-1">{what}</span>}
        </div>
        <span className="text-[11px] text-fg-3">{when}</span>
      </div>
    </div>
  )
}

// ----------------------------------------------------------------------------
// TopProjectRow
// ----------------------------------------------------------------------------

function TopProjectRow({ rank, project, maxMessages, isLast, t }) {
  const messages = Number(project.message_count || 0)
  const pct = maxMessages > 0 ? Math.min(100, (messages / maxMessages) * 100) : 0
  const tone = toneForIndex(rank - 1)
  const Icon = dynamicIconFor(project.icon) || FileText

  return (
    <div
      className={cn(
        'flex items-center gap-3 py-2',
        !isLast && 'border-b border-line',
      )}
    >
      <span className="w-3.5 font-mono text-[11px] text-fg-4">#{rank}</span>
      <IconTile icon={Icon} tone={tone} size="md" />
      <span className="grow truncate text-xs text-fg-1">
        {project.name || t('workspacePage.untitledProject')}
      </span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-bg-3">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-12 font-mono tabular-nums text-[11px] text-fg-3 text-end">
        {formatNumber(messages)}
      </span>
    </div>
  )
}

// ----------------------------------------------------------------------------
// GroupRow
// ----------------------------------------------------------------------------

function GroupRow({ group, index, t }) {
  const tone = toneForIndex(index)
  const Icon = dynamicIconFor(group.icon) || Layers
  return (
    <div className="flex cursor-pointer items-center gap-3 rounded-[9px] px-2 py-2 transition-colors hover:bg-bg-3">
      <IconTile icon={Icon} tone={tone} size="md" />
      <span className="grow text-xs font-medium text-fg-1">
        {group.name || t('workspacePage.untitledGroup')}
      </span>
      <span className="text-[11px] text-fg-3">
        {t('workspaceSettings.groups.membersCount', { count: Number(group.member_count || 0) })}
      </span>
      <ChevronRight className="h-3.5 w-3.5 text-fg-4 rtl:rotate-180" />
    </div>
  )
}

// ----------------------------------------------------------------------------
// Page
// ----------------------------------------------------------------------------

export default function WorkspaceOverviewPage() {
  const { t } = useTranslation('projects')
  const { wid } = useParams()
  const { user } = useAuth()
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const load = useCallback(async () => {
    if (!wid) return
    setLoading(true)
    setError(null)
    try {
      const res = await workspaceService.getOverview(wid)
      if (mountedRef.current) setData(res)
    } catch (err) {
      if (!mountedRef.current) return
      const status = err.response?.status
      if (status === 403 || status === 404) {
        toast.error(t('workspacePage.errors.noAccess'))
        nav('/chat', { replace: true })
        return
      }
      setError(err.response?.data?.error || t('workspacePage.errors.loadFailed'))
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [wid, nav, t])

  useEffect(() => {
    load()
  }, [load])

  // Company overview is team-only and owner/admin-only. IdP-synced orgs have no
  // owner_id, so owner-ness comes from the membership role in WorkspaceContext.
  const { workspaces: memberWorkspaces } = useWorkspace()
  const loadedWs = data?.workspace
  useEffect(() => {
    if (!loadedWs) return
    const membership = memberWorkspaces.find((w) => w._id === (loadedWs._id || loadedWs.id))
    const isWsOwner =
      membership?.member_role === 'owner' ||
      Boolean(user?.id && loadedWs.owner_id && loadedWs.owner_id === user.id)
    if (loadedWs.type !== 'team' || (!isWsOwner && user?.role !== 'admin')) {
      nav('/chat', { replace: true })
    }
  }, [loadedWs, memberWorkspaces, user?.id, user?.role, nav])

  if (loading) {
    return (
      <PageShell width="dense">
        <span className="sr-only" aria-live="polite">{t('workspacePage.loading')}</span>
        {/* Header */}
        <Skeleton className="h-12 rounded-xl" />
        {/* Plan banner */}
        <Skeleton className="h-20 rounded-xl" />
        {/* Stat grid 3-up */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
        {/* Activity · projects · groups grid */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          <Skeleton className="h-56 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
        </div>
      </PageShell>
    )
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-bg-0 p-6">
        <div className="text-center">
          <p className="text-sm text-err">{error}</p>
          <div className="mt-3 flex items-center justify-center gap-2">
            <Button size="sm" onClick={() => load()} className="gap-1.5">
              <RotateCw className="h-3.5 w-3.5" />
              {t('workspacePage.buttons.retry')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => nav('/chat')}
            >
              {t('workspacePage.buttons.backToChat')}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (!data) return null

  const ws = data.workspace || {}
  const billing = data.billing || {}
  const stats = data.stats || {}
  const topProjects = Array.isArray(data.top_projects) ? data.top_projects : []
  const recentActivity = Array.isArray(data.recent_activity) ? data.recent_activity : []
  const groups = Array.isArray(data.groups) ? data.groups : []
  const seatsUsed = Number(billing.seats_used || 0)
  const seatsTotal = Number(billing.seats_total || 0)
  const seatsAvailable = Math.max(0, seatsTotal - seatsUsed)
  const messagesMtd = Number(stats.messages_mtd || 0)
  const activeProjects = Number(stats.active_projects || 0)
  const planTier = (billing.plan_tier || ws.plan || 'free').toLowerCase()
  const isEnterprise = planTier === 'enterprise'
  const ssoEnforced = !!billing.sso_enforced
  const scimEnabled = !!billing.scim_enabled
  const domain = billing.domain
  const renewsAt = billing.renews_at
  const createdAt = ws.created_at

  // $ figures are owner-only (super-admins bypass). Owner = serialized
  // `owner_id` matches the signed-in user. Headline credit = reconciled
  // remaining (Σledger − Σusage); lifetime top-ups stay a secondary "total
  // added" so the two numbers never contradict each other.
  const isOwner =
    memberWorkspaces.find((w) => w._id === (ws._id || ws.id))?.member_role === 'owner' ||
    Boolean(user?.id && ws.owner_id && ws.owner_id === user.id)
  const canSeeMoney = isOwner || user?.role === 'admin'
  const creditRemaining =
    billing.credits_remaining_usd != null ? Number(billing.credits_remaining_usd) : null
  const creditTotalAdded =
    billing.credits_balance_usd != null ? Number(billing.credits_balance_usd) : null

  const wsName = ws.name || t('workspacePage.workspaceFallback')
  const wsLetter = wsName.trim().charAt(0).toUpperCase() || 'W'

  const maxProjectMessages = topProjects.reduce(
    (m, p) => Math.max(m, Number(p.message_count || 0)),
    0,
  )

  function handleExportReport() {
    try {
      const payload = JSON.stringify(data, null, 2)
      const blob = new Blob([payload], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const slug = (wsName || 'workspace')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'workspace'
      a.href = url
      a.download = `${slug}-overview-${fmtDate(new Date(), 'yyyy-MM-dd')}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.success(t('workspacePage.export.success'))
    } catch {
      toast.error(t('workspacePage.export.failed'))
    }
  }

  return (
    <PageShell width="dense">
      <PageHeader
        icon={Building2}
        title={wsName}
        subtitle={ws.description || t('workspacePage.subtitle')}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              animated={false}
              onClick={handleExportReport}
            >
              <Download className="h-3.5 w-3.5" />
              {t('workspacePage.buttons.exportReport')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              animated={false}
              onClick={() => nav(`/workspaces/${wid}/settings`)}
            >
              <Settings className="h-3.5 w-3.5" />
              {t('workspacePage.buttons.settings')}
            </Button>
            <Button
              size="sm"
              animated={false}
              onClick={() => nav(`/workspaces/${wid}/settings?tab=members`)}
            >
              <Plus className="h-3.5 w-3.5" />
              {t('workspacePage.buttons.invite')}
            </Button>
          </>
        }
      />

      {/* Plan banner — solid identity strip with a faint accent wash. */}
      <div
        className={cn('relative flex items-center gap-4 overflow-hidden rounded-xl p-4')}
        style={{
          ...solidPanelSx({ radius: RADII.surface }),
          backgroundImage:
            'linear-gradient(135deg, hsl(var(--accent) / 0.08), transparent 70%)',
        }}
      >
          <span
            className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-hover text-sm font-bold text-white"
            aria-hidden
          >
            {wsLetter}
          </span>
          <div className="flex grow flex-col gap-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-semibold text-fg-0 truncate">
                {wsName}
              </span>
              {isEnterprise && (
                <span className="inline-flex items-center rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-semibold leading-tight text-accent">
                  {t('workspacePage.badges.enterprise')}
                </span>
              )}
              {ssoEnforced && (
                <span className="inline-flex items-center gap-1 rounded-full bg-ok/15 px-2 py-0.5 text-[11px] font-semibold leading-tight text-ok">
                  <ShieldCheck className="h-3 w-3" />
                  {t('workspacePage.badges.ssoEnforced')}
                </span>
              )}
              {scimEnabled && (
                <span className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-semibold leading-tight text-accent">
                  <Key className="h-3 w-3" />
                  {t('workspacePage.badges.scim')}
                </span>
              )}
            </div>
            <span className="text-[11px] text-fg-3 truncate">
              {[
                domain,
                createdAt
                  ? t('workspacePage.meta.created', {
                      date: fmtDate(new Date(createdAt), 'MMM d, yyyy'),
                    })
                  : null,
                t('workspacePage.meta.memberCount', { count: seatsUsed }),
                t('workspacePage.meta.activeProjectCount', { count: activeProjects }),
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </div>
          <div className="flex flex-shrink-0 flex-col items-end gap-2">
            {canSeeMoney && creditRemaining != null && (
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-fg-4">
                  {t('workspacePage.creditBalance')}
                </span>
                <CostValue
                  usd={creditRemaining}
                  className={cn(
                    'text-base font-semibold',
                    creditRemaining < 0 ? 'text-err' : 'text-fg-0',
                  )}
                />
                {creditTotalAdded != null && (
                  <span className="text-[11px] text-fg-3">
                    {t('workspacePage.creditTotalAdded', { amount: fmtCurrency(creditTotalAdded) })}
                  </span>
                )}
              </div>
            )}
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-[11px] text-fg-3">{t('workspacePage.renews')}</span>
              <span className="text-xs font-semibold text-fg-0">
                {renewsAt ? fmtDate(new Date(renewsAt), 'MMM d, yyyy') : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Stat grid 3-up — spend lives on Billing tab only */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatTile
            label={t('workspacePage.stats.activeMembers')}
            value={
              seatsTotal > 0
                ? `${formatNumber(seatsUsed)} / ${formatNumber(seatsTotal)}`
                : formatNumber(seatsUsed)
            }
            hint={
              seatsTotal > 0
                ? t('workspacePage.statHints.seatsAvailable', { count: seatsAvailable })
                : t('workspacePage.statHints.noSeatCap')
            }
          />
          <StatTile
            label={t('workspacePage.stats.messagesMonth')}
            value={formatNumber(messagesMtd)}
            hint={
              messagesMtd > 0
                ? t('workspacePage.statHints.acrossAllProjects')
                : t('workspacePage.statHints.noMessagesYet')
            }
          />
          <StatTile
            label={t('workspacePage.stats.activeProjects')}
            value={formatNumber(activeProjects)}
            hint={
              activeProjects === 0
                ? t('workspacePage.statHints.createProjectCta')
                : t('workspacePage.statHints.inThisWorkspace')
            }
          />
        </div>

        {/* Activity · Top projects · Groups — one responsive grid. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          <Section title={t('workspacePage.sections.recentActivity')} hint={t('workspacePage.hints.recentActivity')}>
            {recentActivity.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <Activity className="h-5 w-5 text-fg-4" />
                <span className="text-xs text-fg-3">
                  {t('workspacePage.empty.recentActivity')}
                </span>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {recentActivity.map((a, i) => (
                  <ActivityRow key={a._id || a.id || i} entry={a} t={t} />
                ))}
              </div>
            )}
          </Section>

          <Section
            title={t('workspacePage.sections.topProjects')}
            hint={t('workspacePage.hints.topProjects')}
          >
            {topProjects.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <FileText className="h-5 w-5 text-fg-4" />
                <span className="text-xs text-fg-3">
                  {t('workspacePage.empty.topProjects')}
                </span>
              </div>
            ) : (
              <div className="flex flex-col">
                {topProjects.map((p, i) => (
                  <TopProjectRow
                    key={p.project_id || p._id || i}
                    rank={i + 1}
                    project={p}
                    maxMessages={maxProjectMessages}
                    isLast={i === topProjects.length - 1}
                    t={t}
                  />
                ))}
              </div>
            )}
          </Section>

          <Section
            title={t('workspacePage.sections.groups')}
            hint={t('workspacePage.hints.groups')}
            action={
              <Button
                variant="ghost"
                size="sm"
                animated={false}
                onClick={() =>
                  nav(`/workspaces/${wid}/settings?tab=members&sub=groups`)
                }
              >
                <Plus className="h-3.5 w-3.5" />
                {t('workspacePage.buttons.newGroup')}
              </Button>
            }
          >
            {groups.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <Layers className="h-5 w-5 text-fg-4" />
                <span className="text-xs text-fg-3">
                  {t('workspacePage.empty.groups')}
                </span>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {groups.map((g, i) => (
                  <GroupRow key={g._id || g.id || i} group={g} index={i} t={t} />
                ))}
              </div>
            )}
          </Section>
        </div>
    </PageShell>
  )
}
