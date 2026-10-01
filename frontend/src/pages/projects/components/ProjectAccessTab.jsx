import { useState, useEffect, useCallback, useMemo } from 'react'
import { Plus, Lock, MoreHorizontal, Trash2, User as UserIcon, Layers, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import Section from '@/components/teams/Section'
import RoleBadge from '@/components/teams/RoleBadge'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'

import { fmtDate } from '@/utils/dateLocale'
import api from '@/services/api'
import projectService from '@/services/projectService'
import workspaceService from '@/services/workspaceService'

import AccessRow from './AccessRow'

function getRoleOptionsGroup(t) {
  return [
    { value: 'viewer', label: t('roles.viewer') },
    { value: 'editor', label: t('roles.editor') },
    { value: 'remove', label: t('roles.removeAccess'), danger: true },
  ]
}

function getRoleOptionsDirect(t) {
  // Project member API only accepts viewer|editor (owner is implied by the
  // workspace owner and returns 400 here) — do not offer it.
  return [
    { value: 'viewer', label: t('roles.viewer') },
    { value: 'editor', label: t('roles.editor') },
  ]
}

const ROLE_LABEL_KEYS = {
  owner: 'roles.owner',
  editor: 'roles.editor',
  viewer: 'roles.viewer',
  admin: 'roles.admin',
  manager: 'roles.manager',
  guest: 'roles.guest',
}

function roleLabel(role, t) {
  if (!t) return role || 'No access'
  if (!role) return t('projectSettings.access.noAccess')
  const key = ROLE_LABEL_KEYS[role]
  if (key) return t(key)
  // Unknown role — capitalize as a graceful fallback.
  return role.charAt(0).toUpperCase() + role.slice(1)
}

function formatExpires(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  try {
    return fmtDate(d, 'MMM d')
  } catch {
    return null
  }
}

function getInitials(name, email) {
  if (name) return name.slice(0, 2).toUpperCase()
  if (email) return email.slice(0, 2).toUpperCase()
  return '??'
}

export default function ProjectAccessTab({ project, workspace }) {
  const { t } = useTranslation('projects')
  const { confirm, confirmDialog } = useConfirmDelete()
  const roleOptionsGroup = getRoleOptionsGroup(t)
  const [access, setAccess] = useState({ groups: [], direct_members: [] })
  const [groups, setGroups] = useState([])
  const [wsMembers, setWsMembers] = useState([])
  const [loading, setLoading] = useState(true)

  const [addGroupOpen, setAddGroupOpen] = useState(false)
  const [addMemberOpen, setAddMemberOpen] = useState(false)

  const wid = project.workspace_id
  const pid = project._id

  const loadAccess = useCallback(async () => {
    try {
      const data = await projectService.getAccess(pid)
      setAccess(data || { groups: [], direct_members: [] })
    } catch (ex) {
      toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.loadFailed'))
    }
  }, [pid, t])

  const loadGroups = useCallback(async () => {
    if (!wid) return
    try {
      const r = await api.get(`/workspaces/${wid}/groups/list`)
      setGroups(r.data?.groups || [])
    } catch {
      // viewer-level may not always succeed; non-fatal
      setGroups([])
    }
  }, [wid])

  const loadWsMembers = useCallback(async () => {
    if (!wid) return
    try {
      const list = await workspaceService.members(wid)
      setWsMembers((list || []).filter(m => m.status === 'active'))
    } catch {
      setWsMembers([])
    }
  }, [wid])

  useEffect(() => {
    let mounted = true
    async function init() {
      setLoading(true)
      await Promise.all([loadAccess(), loadGroups(), loadWsMembers()])
      if (mounted) setLoading(false)
    }
    init()
    return () => { mounted = false }
  }, [loadAccess, loadGroups, loadWsMembers])

  const wsName = workspace?.name || t('projectSettings.access.thisWorkspace')
  const wsMemberCount = wsMembers.length

  // ---------------------------------------------------------------
  // Group access actions
  // ---------------------------------------------------------------
  async function handleGroupChange(grant, opt) {
    if (opt.value === 'remove') {
      try {
        await projectService.removeGroupAccess(pid, grant.group_id)
        await loadAccess()
        toast.success(t('projectSettings.access.toasts.groupRemoved'))
      } catch (ex) {
        toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.groupRemoveFailed'))
      }
      return
    }
    try {
      await projectService.setGroupAccess(pid, grant.group_id, opt.value)
      await loadAccess()
      toast.success(t('projectSettings.access.toasts.groupRoleUpdated'))
    } catch (ex) {
      toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.groupRoleUpdateFailed'))
    }
  }

  // ---------------------------------------------------------------
  // Direct member actions (delegates to existing project member API)
  // ---------------------------------------------------------------
  async function handleRemoveMember(m) {
    const ok = await confirm({
      title: t('projectSettings.access.removeFromProject'),
      description: t('projectSettings.access.confirmRemoveDesc', {
        name: m.name || m.email || t('projectSettings.access.unknownUser'),
      }),
      confirmLabel: t('projectSettings.access.removeFromProject'),
      destructive: true,
    })
    if (!ok) return
    await handleMemberRoleChange(m.user_id, 'remove')
  }

  async function handleMemberRoleChange(uid, role) {
    if (role === 'remove') {
      try {
        await projectService.removeMember(pid, uid)
        await loadAccess()
        toast.success(t('projectSettings.access.toasts.memberRemoved'))
      } catch (ex) {
        const code = ex.response?.data?.code
        if (code === 'last_owner_protected') {
          toast.error(t('projectSettings.access.toasts.lastOwnerCannotRemove'))
        } else {
          toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.memberRemoveFailed'))
        }
      }
      return
    }
    try {
      await projectService.updateMember(pid, uid, role)
      await loadAccess()
      toast.success(t('projectSettings.access.toasts.memberRoleUpdated'))
    } catch (ex) {
      const code = ex.response?.data?.code
      if (code === 'last_owner_protected') {
        toast.error(t('projectSettings.access.toasts.lastOwnerCannotDemote'))
      } else {
        toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.memberRoleUpdateFailed'))
      }
    }
  }

  // Groups already granted, used to filter Add-group modal.
  const grantedGroupIds = useMemo(
    () => new Set((access.groups || []).map(g => g.group_id)),
    [access.groups],
  )

  // Workspace members not yet in direct_members, used to filter Add-member modal.
  const directIds = useMemo(
    () => new Set((access.direct_members || []).map(m => m.user_id)),
    [access.direct_members],
  )

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------------- */}
      {/* Workspace access                                              */}
      {/* ------------------------------------------------------------- */}
      <Section
        title={t('projectSettings.access.workspaceAccessTitle')}
        hint={t('projectSettings.access.workspaceAccessDesc')}
      >
        <div className="flex flex-col gap-3">
          <AccessRow
            iconComponent={Globe}
            tone="sky"
            title={t('projectSettings.access.everyoneIn', { name: wsName })}
            sub={t('projectSettings.access.allMembers', { count: wsMemberCount })}
            value={t('projectSettings.access.noAccess')}
            disabled
          />

          {(access.groups || []).map(g => {
            const expires = formatExpires(g.expires_at)
            const value = expires
              ? t('projectSettings.access.rolePlusExpires', { role: roleLabel(g.role, t), date: expires })
              : roleLabel(g.role, t)
            return (
              <AccessRow
                key={g.group_id}
                iconComponent={Layers}
                iconColor={g.color || undefined}
                tone="sky"
                title={t('projectSettings.access.groupRow', { name: g.name })}
                sub={t('projectSettings.access.groupRowSub', { role: g.role })}
                value={value}
                options={roleOptionsGroup}
                onChange={opt => handleGroupChange(g, opt)}
              />
            )
          })}

          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAddGroupOpen(true)}
              disabled={loading}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('projectSettings.access.grantGroupAccess')}
            </Button>
          </div>
        </div>
      </Section>

      {/* ------------------------------------------------------------- */}
      {/* Direct members                                                */}
      {/* ------------------------------------------------------------- */}
      <Section
          title={t('projectSettings.access.directMembersTitle')}
          hint={t('projectSettings.access.directMembersHint')}
          padded={false}
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAddMemberOpen(true)}
              className="gap-1.5"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('projectSettings.access.addDirectMember')}
            </Button>
          }
        >
          <div className="m-4 overflow-hidden rounded-2xl border border-line">
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-bg-2/50 text-start text-[12px] font-bold uppercase tracking-wide text-fg-2">
                <th className="px-4 py-2.5 text-start font-bold">{t('projectSettings.access.memberHeader')}</th>
                <th className="px-4 py-2.5 text-start font-bold">{t('projectSettings.access.sourceHeader')}</th>
                <th className="px-4 py-2.5 text-start font-bold">{t('projectSettings.access.roleHeader')}</th>
                <th className="px-4 py-2.5 text-start font-bold">{t('projectSettings.access.lastActiveHeader')}</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {(access.direct_members || []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-xs text-fg-3">
                    {t('projectSettings.access.directMembersEmpty')}
                  </td>
                </tr>
              )}
              {(access.direct_members || []).map(m => {
                const source = m.source || 'direct'
                const isDirect = source === 'direct'
                const viaGroup = !isDirect && source.startsWith('via_')
                  ? source.slice(4)
                  : null
                return (
                  <tr key={m.user_id} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <Avatar size="sm">
                          {m.avatar_url && (
                            <AvatarImage src={m.avatar_url} alt={m.name || m.email} />
                          )}
                          <AvatarFallback className="text-[10px]">
                            {getInitials(m.name, m.email)}
                          </AvatarFallback>
                        </Avatar>
                        <div className="flex flex-col min-w-0">
                          <span className="text-fg-0 font-medium">
                            {m.name || m.email || t('projectSettings.access.unknownUser')}
                          </span>
                          {m.email && m.name && (
                            <span className="text-[11px] text-fg-3">
                              {m.email}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {isDirect ? (
                        <Badge
                          variant="default"
                          className="bg-accent/15 text-accent border border-accent/30 gap-1"
                        >
                          <UserIcon className="h-3 w-3" />
                          {t('projectSettings.access.directBadge')}
                        </Badge>
                      ) : (
                        <Badge
                          variant="default"
                          className="bg-fg-3/15 text-fg-2 border border-fg-3/30 gap-1"
                        >
                          <Layers className="h-3 w-3" />
                          {t('projectSettings.access.viaGroup', { group: viaGroup || t('projectSettings.access.viaGroupFallback') })}
                        </Badge>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <RoleBadge role={m.role || 'viewer'} />
                    </td>
                    <td className="px-4 py-2.5 text-[11px] text-fg-3 tabular-nums">
                      {m.last_active || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-end">
                      {/* Direct, non-owner members get a real actions menu —
                          change role or (with confirm) remove. Owner is implied
                          by the workspace and via-group access is managed on the
                          group, so neither exposes inline actions. */}
                      {isDirect && m.role !== 'owner' && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-fg-3"
                              aria-label={t('projectSettings.access.memberActions')}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {getRoleOptionsDirect(t).map((opt) => (
                              <DropdownMenuItem
                                key={opt.value}
                                disabled={(m.role || 'viewer') === opt.value}
                                onClick={() => handleMemberRoleChange(m.user_id, opt.value)}
                              >
                                {opt.label}
                              </DropdownMenuItem>
                            ))}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-error focus:text-error"
                              onClick={() => handleRemoveMember(m)}
                            >
                              <Trash2 className="h-4 w-4 me-2" />
                              {t('projectSettings.access.removeFromProject')}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          </div>
          </div>
        </Section>

      {/* ------------------------------------------------------------- */}
      {/* Sharing                                                        */}
      {/* ------------------------------------------------------------- */}
      <Section
          title={t('projectSettings.access.sharingTitle')}
          hint={t('projectSettings.access.sharingHint')}
        >
          <div className="flex items-center gap-3 opacity-60">
            <Lock className="h-5 w-5 text-fg-3 flex-shrink-0" />
            <div className="flex flex-col flex-1 min-w-0">
              <span className="text-sm font-medium text-fg-0">{t('projectSettings.access.publicLinkLabel')}</span>
              <span className="text-[11px] text-fg-3">
                {t('projectSettings.access.publicLinkDisabledBy', { name: wsName })}
              </span>
            </div>
            <Switch checked={false} disabled />
          </div>
        </Section>

      <AddGroupAccessDialog
        open={addGroupOpen}
        onOpenChange={setAddGroupOpen}
        groups={groups.filter(g => !grantedGroupIds.has(g._id))}
        onSubmit={async ({ group_id, role, expires_at }) => {
          try {
            await projectService.setGroupAccess(pid, group_id, role, expires_at || null)
            await loadAccess()
            setAddGroupOpen(false)
            toast.success(t('projectSettings.access.toasts.groupAdded'))
          } catch (ex) {
            toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.groupAddFailed'))
          }
        }}
      />

      <AddDirectMemberDialog
        open={addMemberOpen}
        onOpenChange={setAddMemberOpen}
        candidates={wsMembers.filter(m => !directIds.has(String(m.user?.id || m.user_id)))}
        onSubmit={async ({ user_id, role }) => {
          try {
            await projectService.addMember(pid, { user_id, role })
            await loadAccess()
            setAddMemberOpen(false)
            toast.success(t('projectSettings.access.toasts.memberAdded'))
          } catch (ex) {
            toast.error(ex.response?.data?.error || t('projectSettings.access.toasts.memberAddFailed'))
          }
        }}
      />

      {confirmDialog}
    </div>
  )
}

// ---------------------------------------------------------------------
// Add group access modal
// ---------------------------------------------------------------------
function AddGroupAccessDialog({ open, onOpenChange, groups, onSubmit }) {
  const { t } = useTranslation('projects')
  const [groupId, setGroupId] = useState('')
  const [role, setRole] = useState('viewer')
  const [expiresAt, setExpiresAt] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setGroupId('')
      setRole('viewer')
      setExpiresAt('')
    }
  }, [open])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!groupId) return
    setBusy(true)
    try {
      await onSubmit({
        group_id: groupId,
        role,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('projectSettings.access.grantGroupAccess')}</DialogTitle>
          <DialogDescription>
            {t('projectSettings.access.addGroupDialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <Label>{t('projectSettings.access.groupLabel')}</Label>
            {groups.length === 0 ? (
              <p className="text-xs text-fg-3">
                {t('projectSettings.access.noGroupsAvailable')}
              </p>
            ) : (
              <Select value={groupId} onValueChange={setGroupId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('projectSettings.access.selectGroup')} />
                </SelectTrigger>
                <SelectContent>
                  {groups.map(g => (
                    <SelectItem key={g._id} value={g._id}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-1">
            <Label>{t('projectSettings.access.roleLabel')}</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="viewer">{t('roles.viewer')}</SelectItem>
                <SelectItem value="editor">{t('roles.editor')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>{t('projectSettings.access.expiresOptionalLabel')}</Label>
            <Input
              type="date"
              value={expiresAt}
              onChange={e => setExpiresAt(e.target.value)}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={!groupId || busy}>
              {busy ? '...' : t('projectSettings.access.grantAccess')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------
// Add direct member modal
// ---------------------------------------------------------------------
function AddDirectMemberDialog({ open, onOpenChange, candidates, onSubmit }) {
  const { t } = useTranslation('projects')
  const roleOptionsDirect = getRoleOptionsDirect(t)
  const [uid, setUid] = useState('')
  const [role, setRole] = useState('editor')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setUid('')
      setRole('editor')
    }
  }, [open])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!uid) return
    setBusy(true)
    try {
      await onSubmit({ user_id: uid, role })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('projectSettings.access.addDirectMember')}</DialogTitle>
          <DialogDescription>
            {t('projectSettings.access.addMemberDialogDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <Label>{t('projectSettings.access.workspaceMemberLabel')}</Label>
            {candidates.length === 0 ? (
              <div className="space-y-1">
                <p className="text-xs text-fg-3">{t('projectSettings.access.allMembersAlreadyAdded')}</p>
                <p className="text-xs text-fg-3">{t('projectSettings.access.inviteAtWorkspaceHint')}</p>
              </div>
            ) : (
              <Select value={uid} onValueChange={setUid}>
                <SelectTrigger>
                  <SelectValue placeholder={t('projectSettings.access.selectMember')} />
                </SelectTrigger>
                <SelectContent>
                  {candidates.map(m => {
                    const id = m.user?.id || m.user_id
                    const label = m.user?.display_name || m.user?.email || id
                    return (
                      <SelectItem key={id} value={id}>
                        {label}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-1">
            <Label>{t('projectSettings.access.roleLabel')}</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roleOptionsDirect.map(o => (
                  <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={!uid || busy}>
              {busy ? '...' : t('projectSettings.access.addMember')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
