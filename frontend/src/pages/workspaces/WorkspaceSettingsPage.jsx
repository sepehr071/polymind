import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
// companies namespace used for "Company" / "Companies" labels (Task F)
import toast from 'react-hot-toast'
import {
  Settings,
  Users,
  CreditCard,
  Activity,
  AlertTriangle,
  ShieldAlert,
  Search,
  Plus,
  Mail,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import PageShell from '@/components/layout/PageShell'
import Section from '@/components/teams/Section'
import RoleBadge from '@/components/teams/RoleBadge'
import MembersTable from '@/components/teams/MembersTable'
import PendingInvitesList from '@/components/teams/PendingInvitesList'
import DangerZone from '@/components/teams/DangerZone'
import GroupsTab from './components/GroupsTab'
import BillingTab from './components/BillingTab'
import AuditTab from './components/AuditTab'
import DLPPolicyTab from './components/DLPPolicyTab'
import { workspaceService } from '@/services/workspaceService'
import groupService from '@/services/groupService'
import { useWorkspace } from '@/context/WorkspaceContext'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/utils'

const TAB_DEFS = [
  { id: 'general',  labelKey: 'workspaceSettings.tabs.general',  icon: Settings },
  { id: 'members',  labelKey: 'workspaceSettings.tabs.members',  icon: Users, countKey: 'members' },
  { id: 'billing',  labelKey: 'workspaceSettings.tabs.billing',  icon: CreditCard },
  { id: 'activity', labelKey: 'workspaceSettings.tabs.activity', icon: Activity },
  { id: 'dlp',      labelKey: 'workspaceSettings.tabs.dlp',      icon: ShieldAlert },
  { id: 'danger',   labelKey: 'workspaceSettings.tabs.danger',   icon: AlertTriangle },
]

const VALID_TABS = TAB_DEFS.map((t) => t.id)

// Legacy / stale deep-links: map an external ?tab=<alias> onto a real tab id.
// Sidebar links ?tab=audit, but the audit log lives under the 'activity' tab.
// Company Overview CTAs link ?tab=invites / ?tab=groups; both live under the
// 'members' tab (Groups is a members sub-tab, see ?sub= sync below).
const TAB_ALIASES = { audit: 'activity', invites: 'members', groups: 'members' }

function resolveTab(requested) {
  const aliased = TAB_ALIASES[requested] || requested
  return VALID_TABS.includes(aliased) ? aliased : 'general'
}

const INVITE_ROLE_KEYS = [
  { value: 'editor', labelKey: 'workspaceSettings.members.inviteRole.editor' },
  { value: 'viewer', labelKey: 'workspaceSettings.members.inviteRole.viewer' },
]

const MEMBERS_SUBTABS = ['active', 'pending', 'groups']

// Lightweight "looks like an email" check for the invite free-text hint.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
function isValidEmail(value) {
  return EMAIL_RE.test(value)
}

export default function WorkspaceSettingsPage() {
  const { t } = useTranslation('projects')
  const { t: tc } = useTranslation('companies')
  const { wid } = useParams()
  const nav = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const { refresh: refreshWorkspaces } = useWorkspace()

  const requestedTab = searchParams.get('tab')
  const activeTab = resolveTab(requestedTab)

  // Members sub-tab from URL: explicit ?sub=, else the ?tab=groups alias itself
  // (so the Company Overview "New Group" CTA can deep-link straight to Groups).
  const requestedSubtab = searchParams.get('sub') || (requestedTab === 'groups' ? 'groups' : null)

  const [workspace, setWorkspace] = useState(null)
  const [members, setMembers] = useState([])
  const [invites, setInvites] = useState([])
  const [groupCount, setGroupCount] = useState(0)
  const [loading, setLoading] = useState(true)

  // General
  const [name, setName] = useState('')
  const [nameSaving, setNameSaving] = useState(false)

  // Members tab — search + status seg
  const [memberSearch, setMemberSearch] = useState('')
  const [memberStatus, setMemberStatus] = useState('all')

  // Invite row state
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('editor')
  const [inviteSending, setInviteSending] = useState(false)

  // Invite combobox — typeahead over invitable workspace users.
  const [inviteResults, setInviteResults] = useState([])
  const [inviteSearching, setInviteSearching] = useState(false)
  const [inviteResultsLoaded, setInviteResultsLoaded] = useState(false)
  const [inviteDropdownOpen, setInviteDropdownOpen] = useState(false)
  const inviteSearchSeq = useRef(0)
  const inviteBoxRef = useRef(null)

  // Members sub-tab — seeded from the URL (?sub= / ?tab=groups), defaults to active.
  const [membersSubtab, setMembersSubtab] = useState(
    () => (MEMBERS_SUBTABS.includes(requestedSubtab) ? requestedSubtab : 'active'),
  )

  // Keep the members sub-tab in sync with deep-link changes (e.g. navigating
  // from the Company Overview "New Group" CTA while already on this page).
  // Groups only exists on team workspaces, so fall back to active otherwise.
  useEffect(() => {
    if (!requestedSubtab || !MEMBERS_SUBTABS.includes(requestedSubtab)) return
    if (requestedSubtab === 'groups' && workspace && workspace.type !== 'team') {
      setMembersSubtab('active')
    } else {
      setMembersSubtab(requestedSubtab)
    }
  }, [requestedSubtab, workspace])

  const currentUserId = user?.id
  const currentUserRole = workspace?.member_role
  const isOwner = currentUserRole === 'owner'
  const isOwnerOrAdmin = isOwner || currentUserRole === 'admin'
  const isTeam = workspace?.type === 'team'

  const loadWorkspace = useCallback(async () => {
    try {
      const ws = await workspaceService.get(wid)
      setWorkspace(ws)
      setName(ws.name || '')
    } catch (err) {
      const status = err.response?.status
      if (status === 403 || status === 404) {
        toast.error(t('workspaceSettings.toasts.settingsAccessDenied'))
        nav('/dashboard', { replace: true })
        return
      }
      toast.error(t('workspaceSettings.toasts.loadFailed'))
    }
  }, [wid, nav, t])

  const loadMembers = useCallback(async () => {
    try {
      const list = await workspaceService.members(wid)
      setMembers(list)
    } catch {
      // silently fail
    }
  }, [wid])

  const loadInvites = useCallback(async () => {
    try {
      const list = await workspaceService.listInvites(wid)
      setInvites(list)
    } catch {
      // non-owners won't have access
    }
  }, [wid])

  const loadGroupOptions = useCallback(async () => {
    if (!isTeam) return
    try {
      const list = await groupService.list(wid)
      setGroupCount(list.length)
    } catch {
      // viewer+ should be able to read; if not, leave empty
    }
  }, [wid, isTeam])

  useEffect(() => {
    async function init() {
      setLoading(true)
      await loadWorkspace()
      await Promise.all([loadMembers(), loadInvites()])
      setLoading(false)
    }
    init()
  }, [loadWorkspace, loadMembers, loadInvites])

  useEffect(() => {
    if (workspace?.type === 'team') {
      loadGroupOptions()
    }
  }, [workspace?.type, loadGroupOptions])

  // Company settings only exist for TEAM workspaces. Non-owner members have no business here (global super-admins bypass the
  // owner check). Waits for the workspace to resolve so we don't bounce before
  // member_role / type are known.
  useEffect(() => {
    if (!workspace) return
    if (!isTeam || (!isOwnerOrAdmin && user?.role !== 'admin')) {
      toast.error(t('workspaceSettings.toasts.settingsAccessDenied'))
      nav('/dashboard', { replace: true })
    }
  }, [workspace, isTeam, isOwnerOrAdmin, user, nav, t])

  // Invite typeahead — debounced query against invitable workspace users.
  // Only fires for trimmed input ≥ 2 chars; a stale-response guard (seq)
  // prevents an earlier slow request from clobbering newer results.
  useEffect(() => {
    const q = inviteEmail.trim()
    if (q.length < 2) {
      setInviteResults([])
      setInviteResultsLoaded(false)
      setInviteSearching(false)
      return
    }
    const seq = ++inviteSearchSeq.current
    setInviteSearching(true)
    const handle = setTimeout(async () => {
      try {
        const list = await workspaceService.invitableUsers(wid, q)
        if (seq !== inviteSearchSeq.current) return
        setInviteResults(Array.isArray(list) ? list : [])
        setInviteResultsLoaded(true)
      } catch {
        if (seq !== inviteSearchSeq.current) return
        setInviteResults([])
        setInviteResultsLoaded(true)
      } finally {
        if (seq === inviteSearchSeq.current) setInviteSearching(false)
      }
    }, 250)
    return () => clearTimeout(handle)
  }, [inviteEmail, wid])

  // Close the results dropdown on outside click.
  useEffect(() => {
    if (!inviteDropdownOpen) return
    function onPointerDown(e) {
      if (inviteBoxRef.current && !inviteBoxRef.current.contains(e.target)) {
        setInviteDropdownOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [inviteDropdownOpen])

  // The [+ Add] action on a typeahead RESULT = an existing, registered user →
  // add them to the workspace directly (no invite/accept). The free-text email
  // path (handleSendInvite) still covers unknown / SSO-only addresses.
  async function handleAddExisting(u) {
    try {
      await workspaceService.addMember(wid, u.id, inviteRole)
      toast.success(t('workspaceSettings.members.addMemberSuccess'))
      await loadMembers()
      setInviteEmail('')
      setInviteDropdownOpen(false)
    } catch (err) {
      toast.error(err.response?.data?.error || t('workspaceSettings.members.addMemberFailed'))
    }
  }

  function setTab(id) {
    if (!VALID_TABS.includes(id)) return
    const next = new URLSearchParams(searchParams)
    next.set('tab', id)
    next.delete('sub')
    setSearchParams(next, { replace: true })
  }

  function setMembersSubtabAndUrl(sub) {
    if (!MEMBERS_SUBTABS.includes(sub)) return
    setMembersSubtab(sub)
    const next = new URLSearchParams(searchParams)
    next.set('tab', 'members')
    if (sub === 'active') next.delete('sub')
    else next.set('sub', sub)
    setSearchParams(next, { replace: true })
  }

  async function handleSaveName(e) {
    e.preventDefault()
    if (!name.trim() || name.trim() === workspace?.name) return
    setNameSaving(true)
    try {
      const updated = await workspaceService.update(wid, { name: name.trim() })
      setWorkspace((prev) => ({ ...prev, ...updated }))
      await refreshWorkspaces()
      toast.success(tc('renamed', { name: name.trim() }))
    } catch (err) {
      toast.error(err.response?.data?.error || t('workspaceSettings.toasts.saveFailed'))
    } finally {
      setNameSaving(false)
    }
  }

  async function handleRoleChange(uid, role) {
    try {
      await workspaceService.updateMember(wid, uid, role)
      await loadMembers()
      toast.success(t('workspaceSettings.toasts.roleUpdated'))
    } catch (err) {
      const code = err.response?.data?.code
      if (code === 'last_owner_protected') {
        toast.error(t('workspaceSettings.toasts.lastOwnerCannotDemote'))
      } else {
        toast.error(err.response?.data?.error || t('workspaceSettings.toasts.roleUpdateFailed'))
      }
    }
  }

  async function handleRemoveMember(uid) {
    try {
      await workspaceService.removeMember(wid, uid)
      await loadMembers()
      toast.success(t('workspaceSettings.toasts.memberRemoved'))
    } catch (err) {
      const code = err.response?.data?.code
      if (code === 'last_owner_protected') {
        toast.error(t('workspaceSettings.toasts.lastOwnerCannotRemove'))
      } else {
        toast.error(err.response?.data?.error || t('workspaceSettings.toasts.removeMemberFailed'))
      }
    }
  }

  async function handleSendInvite(e) {
    e?.preventDefault?.()
    const email = inviteEmail.trim()
    if (!email) return
    setInviteSending(true)
    setInviteDropdownOpen(false)
    try {
      const res = await workspaceService.invite(wid, { email, role: inviteRole })
      await loadInvites()
      if (res?.email_sent === false) {
        // No email channel — surface the copy-link on the Pending sub-tab.
        toast.success(t('workspaceSettings.toasts.inviteCreatedNoEmail'))
        setMembersSubtabAndUrl('pending')
      } else {
        toast.success(t('workspaceSettings.toasts.inviteSent', { email }))
      }
      setInviteEmail('')
      setInviteRole('editor')
    } catch (err) {
      toast.error(err.response?.data?.error || t('workspaceSettings.toasts.inviteSendFailed'))
    } finally {
      setInviteSending(false)
    }
  }

  async function handleRevokeInvite(token) {
    try {
      await workspaceService.revokeInvite(wid, token)
      await loadInvites()
      toast.success(t('workspaceSettings.toasts.inviteRevoked'))
    } catch {
      toast.error(t('workspaceSettings.toasts.inviteRevokeFailed'))
    }
  }

  async function handleDeleteWorkspace() {
    await workspaceService.delete(wid)
    localStorage.removeItem('active_workspace_id')
    await refreshWorkspaces()
    nav('/chat', { replace: true })
  }

  // Counts for tab-rail badges.
  const memberCount = useMemo(
    () => members.filter((m) => m.status !== 'pending').length,
    [members],
  )
  const pendingCount = useMemo(
    () => invites.filter((i) => !i.accepted_at).length,
    [invites],
  )

  const filteredMembers = useMemo(() => {
    let list = members
    if (memberStatus === 'pending') {
      list = list.filter((m) => m.status === 'pending')
    } else if (memberStatus === 'active') {
      list = list.filter((m) => m.status !== 'pending')
    } else if (memberStatus === 'suspended') {
      list = list.filter((m) => m.status === 'suspended')
    }
    if (memberSearch.trim()) {
      const q = memberSearch.toLowerCase()
      list = list.filter((m) => {
        const n = m.user?.display_name || ''
        const e = m.user?.email || m.invited_email || ''
        return n.toLowerCase().includes(q) || e.toLowerCase().includes(q)
      })
    }
    return list
  }, [members, memberSearch, memberStatus])

  const counts = {
    members: memberCount,
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    )
  }

  if (!workspace) return null

  const visibleTabs = TAB_DEFS

  return (
    <PageShell width="full" className="max-w-6xl">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 shrink-0 text-accent" />
            <h1 className="text-2xl font-extrabold text-foreground">{tc('settings')}</h1>
          </div>
          <p className="mt-1 text-sm text-foreground-secondary">{tc('settingsSubtitle')}</p>
        </div>
        {currentUserRole ? <RoleBadge role={currentUserRole} /> : null}
      </div>

      <nav className="flex gap-1 overflow-x-auto overflow-y-hidden rounded-full bg-background-secondary p-1.5 ring-1 ring-border">
        {visibleTabs.map((tab) => {
          const Icon = tab.icon
          const count = tab.countKey ? counts[tab.countKey] : 0
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setTab(tab.id)}
              className={cn(
                'inline-flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm transition-colors',
                active
                  ? 'bg-accent text-accent-foreground shadow-sm'
                  : 'text-foreground-secondary hover:text-foreground',
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="whitespace-nowrap">{t(tab.labelKey)}</span>
              {count > 0 && (
                <span className="text-[11px] tabular-nums opacity-80">{count}</span>
              )}
            </button>
          )
        })}
      </nav>

      <div>
          {activeTab === 'general' && (
              <Section
                title={t('workspaceSettings.general.detailsTitle')}
                hint={t('workspaceSettings.general.detailsHint')}
              >
                <form onSubmit={handleSaveName} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="ws-name">{t('workspaceSettings.general.nameLabel')}</Label>
                    <Input
                      id="ws-name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      maxLength={100}
                      placeholder={t('workspaceSettings.general.namePlaceholder')}
                      disabled={!isOwnerOrAdmin}
                    />
                  </div>
                  {isOwnerOrAdmin && (
                    <Button
                      type="submit"
                      size="sm"
                      disabled={
                        nameSaving || !name.trim() || name.trim() === workspace.name
                      }
                    >
                      {nameSaving ? t('workspaceSettings.general.saving') : t('workspaceSettings.general.saveChanges')}
                    </Button>
                  )}
                </form>
              </Section>
          )}

          {activeTab === 'members' && (
            <div className="space-y-6">
              {isTeam && isOwnerOrAdmin && (
                <Section
                  title={t('workspaceSettings.members.inviteSectionTitle')}
                  hint={t('workspaceSettings.members.inviteSectionHint')}
                  overflowVisible
                  className="relative z-30"
                >
                  {/* Plain div, NOT a form — Enter must never silently invite.
                      The two actions (Add existing / Invite by email) are
                      explicit buttons inside the results dropdown. */}
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-start gap-2">
                      <div
                        ref={inviteBoxRef}
                        className="relative flex-1 min-w-[180px]"
                      >
                        <div className="relative">
                          <Search className="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-fg-3" />
                          <Input
                            type="text"
                            dir="ltr"
                            placeholder={t('workspaceSettings.members.addMemberSearchPlaceholder')}
                            value={inviteEmail}
                            onChange={(e) => {
                              setInviteEmail(e.target.value)
                              setInviteDropdownOpen(true)
                            }}
                            onFocus={() => setInviteDropdownOpen(true)}
                            autoComplete="off"
                            className="ps-9 text-start"
                          />
                        </div>

                        {inviteDropdownOpen && inviteEmail.trim().length >= 2 && (
                          <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-line bg-bg-1 shadow-lg">
                            {inviteSearching && inviteResults.length === 0 ? (
                              <div className="px-3 py-2.5 text-[12px] text-fg-3">
                                {t('workspaceSettings.members.inviteSearching')}
                              </div>
                            ) : (
                              <>
                                {inviteResults.length > 0 && (
                                  <ul className="max-h-64 overflow-auto py-1">
                                    {inviteResults.map((u) => (
                                      <li
                                        key={u.id}
                                        className="flex items-center gap-2.5 px-3 py-2"
                                      >
                                        <Avatar size="sm" className="h-7 w-7 flex-shrink-0">
                                          {u.avatar_url && (
                                            <AvatarImage src={u.avatar_url} alt={u.display_name || u.email} />
                                          )}
                                          <AvatarFallback className="text-[10px]">
                                            {(u.display_name || u.email || '?').slice(0, 2).toUpperCase()}
                                          </AvatarFallback>
                                        </Avatar>
                                        <span className="flex min-w-0 flex-1 flex-col">
                                          <span className="truncate text-[13px] font-medium text-fg-0">
                                            {u.display_name || u.email}
                                          </span>
                                          {u.email && (
                                            <span dir="ltr" className="truncate text-[11px] text-fg-3 text-start">
                                              {u.email}
                                            </span>
                                          )}
                                        </span>
                                        <Button
                                          type="button"
                                          size="sm"
                                          variant="outline"
                                          onClick={() => handleAddExisting(u)}
                                          className="flex-shrink-0 gap-1"
                                        >
                                          <Plus className="h-3.5 w-3.5" />
                                          {t('workspaceSettings.members.addBtn')}
                                        </Button>
                                      </li>
                                    ))}
                                  </ul>
                                )}

                                {/* Valid email matching NO existing user → explicit
                                    "Invite by email" action row. */}
                                {inviteResultsLoaded &&
                                  !inviteSearching &&
                                  isValidEmail(inviteEmail.trim()) &&
                                  !inviteResults.some(
                                    (u) => (u.email || '').toLowerCase() === inviteEmail.trim().toLowerCase(),
                                  ) && (
                                    <div
                                      className={cn(
                                        'flex items-center gap-2.5 px-3 py-2',
                                        inviteResults.length > 0 && 'border-t border-line',
                                      )}
                                    >
                                      <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-bg-3">
                                        <Mail className="h-3.5 w-3.5 text-fg-2" />
                                      </span>
                                      <span className="min-w-0 flex-1 truncate text-[13px] text-fg-1">
                                        {t('workspaceSettings.members.inviteByEmailAction', { email: inviteEmail.trim() })}
                                      </span>
                                      <Button
                                        type="button"
                                        size="sm"
                                        onClick={() => handleSendInvite()}
                                        disabled={inviteSending}
                                        className="flex-shrink-0"
                                      >
                                        {inviteSending ? t('inviteForm.sending') : t('inviteForm.inviteButton')}
                                      </Button>
                                    </div>
                                  )}

                                {/* Empty state: results loaded, none matched, and the
                                    input isn't a valid email to invite. */}
                                {inviteResultsLoaded &&
                                  !inviteSearching &&
                                  inviteResults.length === 0 &&
                                  !isValidEmail(inviteEmail.trim()) && (
                                    <div className="px-3 py-2.5 text-[12px] text-fg-3">
                                      {t('workspaceSettings.members.inviteNoResults')}
                                    </div>
                                  )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                      <Select value={inviteRole} onValueChange={setInviteRole}>
                        <SelectTrigger className="w-[140px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {INVITE_ROLE_KEYS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {t(opt.labelKey)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <ul className="space-y-1 text-[11px] leading-snug text-fg-3">
                      <li>{t('workspaceSettings.members.roleLegendEditor')}</li>
                      <li>{t('workspaceSettings.members.roleLegendViewer')}</li>
                    </ul>
                  </div>
                </Section>
              )}

              {/* Members sub-tabs: Active | Pending | Groups — canonical
                  segmented filter (active = surface fill + small shadow). */}
              <div>
                <Tabs
                  value={membersSubtab}
                  onValueChange={setMembersSubtabAndUrl}
                  variant="segmented"
                  className="mb-4"
                >
                  <TabsList>
                    {MEMBERS_SUBTABS.filter((s) => s !== 'groups' || isTeam).map((s) => (
                      <TabsTrigger key={s} value={s} className="capitalize">
                        {t(`workspaceSettings.members.subtabs.${s}`)}
                        {s === 'pending' && pendingCount > 0 && (
                          <span className="ms-1.5 font-mono text-[10px] text-fg-3">{pendingCount}</span>
                        )}
                        {s === 'active' && memberCount > 0 && (
                          <span className="ms-1.5 font-mono text-[10px] text-fg-3">{memberCount}</span>
                        )}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>

                {membersSubtab === 'active' && (
                  <Section
                    title={t('workspaceSettings.members.subtabs.active')}
                    hint={
                      workspace.seats_total
                        ? t('workspaceSettings.members.activeCountWithSeats', {
                            count: memberCount,
                            remaining: Math.max(0, workspace.seats_total - memberCount),
                          })
                        : t('workspaceSettings.members.activeCountSummary', { count: memberCount })
                    }
                    padded={false}
                    action={
                      <div className="relative w-[150px] sm:w-[220px]">
                        <Search className="pointer-events-none absolute inset-y-0 start-3 my-auto h-3.5 w-3.5 text-fg-3" />
                        <Input
                          type="search"
                          size="sm"
                          placeholder={t('workspaceSettings.members.searchPlaceholder')}
                          value={memberSearch}
                          onChange={(e) => setMemberSearch(e.target.value)}
                          className="ps-9"
                        />
                      </div>
                    }
                  >
                    <MembersTable
                      members={filteredMembers.filter(m => m.status !== 'pending')}
                      currentUserId={currentUserId}
                      currentUserRole={currentUserRole}
                      onRoleChange={handleRoleChange}
                      onRemove={handleRemoveMember}
                      wid={wid}
                      onRefresh={async () => { await loadMembers(); await refreshWorkspaces() }}
                    />
                  </Section>
                )}

                {membersSubtab === 'pending' && (
                  <Section
                    title={t('workspaceSettings.members.subtabs.pending')}
                    hint={t('workspaceSettings.members.pendingHint', { count: pendingCount })}
                  >
                    <PendingInvitesList
                      invites={invites}
                      onRevoke={handleRevokeInvite}
                      onResend={(updated) => {
                        setInvites(prev =>
                          prev.map(i => i.token === updated.old_token ? updated.invite : i)
                        )
                      }}
                      wid={wid}
                    />
                  </Section>
                )}

                {membersSubtab === 'groups' && isTeam && (
                  <GroupsTab
                    wid={wid}
                    members={members}
                    canManage={isOwnerOrAdmin}
                    onCountChange={setGroupCount}
                  />
                )}
              </div>
            </div>
          )}

          {activeTab === 'billing' && (
            <BillingTab
              wid={wid}
              workspace={workspace}
              isOwner={isOwner}
              onUpdated={(updated) =>
                setWorkspace((prev) => ({ ...prev, ...updated }))
              }
            />
          )}

          {activeTab === 'activity' && (
            <AuditTab wid={wid} members={members} />
          )}

          {activeTab === 'dlp' && (
            <DLPPolicyTab wid={wid} isOwner={isOwner} />
          )}

          {activeTab === 'danger' && (
            <div className="max-w-3xl space-y-6">
              <Section
                title={t('workspaceSettings.danger.zoneTitle')}
                hint={t('workspaceSettings.danger.zoneHint')}
              >
                <DangerZone
                  title={t('workspaceSettings.danger.deleteCompany')}
                  description={t('workspaceSettings.danger.deleteCompanyDescription', { name: workspace.name })}
                  confirmText={workspace.name}
                  onConfirm={handleDeleteWorkspace}
                />
              </Section>
            </div>
          )}
      </div>
    </PageShell>
  )
}
