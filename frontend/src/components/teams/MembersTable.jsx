import { useState } from 'react'
import { Trash2, ShieldCheck, Key, MoreHorizontal, ArrowRightLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import toast from 'react-hot-toast'
import { fmtDate, fmtDistanceToNowSafe } from '@/utils/dateLocale'
import { useConfirmDelete } from '@/hooks/useConfirmDelete'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog'
import RoleBadge from './RoleBadge'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableHeader,
  TableBody,
  TableHeadRow,
  TableHead,
} from '@/components/ui/table'
import { workspaceService } from '@/services/workspaceService'

function getInitials(name, email) {
  if (name) return name.slice(0, 2).toUpperCase()
  if (email) return email.slice(0, 2).toUpperCase()
  return '??'
}

function formatRelative(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  // Older than ~30 days reads better as an absolute date than "30 days ago".
  if (Date.now() - d.getTime() >= 30 * 86400000) return fmtDate(d, 'MMM d')
  return fmtDistanceToNowSafe(d) || '—'
}

function formatJoined(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return fmtDate(d, sameYear ? 'MMM d' : 'MMM d, yyyy')
}

const ROLE_OPTION_KEYS = [
  { value: 'owner', key: 'roles.owner' },
  { value: 'editor', key: 'roles.editor' },
  { value: 'viewer', key: 'roles.viewer' },
]

/**
 * MembersTable — workspace member listing with extended columns.
 *
 * Extended columns:
 *   - Last active  : optional `member.last_active_at` ISO string.
 *   - Joined       : `member.joined_at` (or `created_at` fallback).
 *   - Auth         : `member.auth_method` ('sso' | 'password'), from the server.
 *                    Defaults to the SSO badge only when the field is absent.
 *
 * All extended columns degrade gracefully when the backend doesn't provide
 * the data — they render `—` rather than blanks.
 */
export default function MembersTable({
  members,
  currentUserId,
  currentUserRole,
  onRoleChange,
  onRemove,
  wid,
  onRefresh,
}) {
  const { t } = useTranslation(['projects', 'common'])
  const { confirm, confirmDialog } = useConfirmDelete()
  // FLIP on member add/remove/role-reorder; <tbody> holds only <tr> rows.
  const [tbodyRef] = useAutoAnimate()
  const isOwnerOrAdmin =
    currentUserRole === 'owner' || currentUserRole === 'admin'
  const isOwner = currentUserRole === 'owner'

  const [transferTarget, setTransferTarget] = useState(null)
  const [transferBusy, setTransferBusy] = useState(false)

  async function handleRoleSelect(uid, val) {
    if (val === 'owner') {
      const ok = await confirm({
        title: t('workspaceSettings.members.promoteOwnerTitle'),
        description: t('workspaceSettings.members.promoteOwnerBody'),
        confirmLabel: t('workspaceSettings.members.promoteOwnerConfirm'),
        destructive: true,
      })
      if (!ok) return
    }
    onRoleChange?.(uid, val)
  }

  async function handleRemoveClick(uid) {
    const ok = await confirm({
      title: t('workspaceSettings.members.removeConfirmTitle'),
      description: t('workspaceSettings.members.removeConfirmBody'),
      confirmLabel: t('workspaceSettings.members.removeConfirm'),
      destructive: true,
    })
    if (!ok) return
    onRemove?.(uid)
  }

  async function handleTransferOwnership() {
    if (!wid || !transferTarget) return
    setTransferBusy(true)
    try {
      await workspaceService.transferOwnership(wid, transferTarget.user?.id)
      toast.success(t('workspaceSettings.members.transferDone'))
      setTransferTarget(null)
      await onRefresh?.()
    } catch (err) {
      toast.error(err?.response?.data?.error || t('workspaceSettings.members.transferFailed'))
    } finally {
      setTransferBusy(false)
    }
  }

  const active = members.filter((m) => m.status !== 'pending')
  const pending = members.filter((m) => m.status === 'pending')

  function renderRow(member) {
    const uid = member.user?.id
    const name = member.user?.display_name
    const email = member.user?.email || member.invited_email || ''
    const isSelf = uid === currentUserId
    const isPending = member.status === 'pending'
    // Server now sends the real auth method; fall back to SSO only if absent.
    const authMethod = member.auth_method || 'sso'

    return (
      <tr
        key={member._id}
        className="border-b border-line last:border-0 hover:bg-bg-2/40 transition-colors"
      >
        <td className="py-3 pe-3 align-middle min-w-[200px]">
          <div className="flex items-center gap-2.5">
            <Avatar size="sm">
              {member.user?.avatar_url && (
                <AvatarImage src={member.user.avatar_url} alt={name || email} />
              )}
              <AvatarFallback className="text-[10px]">
                {getInitials(name, email)}
              </AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-col">
              <span className="flex items-center gap-1.5 text-[13px] font-medium text-fg-0 truncate">
                {name || email}
                {isSelf && (
                  <span className="text-[11px] font-normal text-fg-3">
                    {t('workspaceSettings.members.you')}
                  </span>
                )}
              </span>
              {name && (
                <span className="text-[11px] text-fg-3 truncate">{email}</span>
              )}
            </div>
          </div>
        </td>
        <td className="py-3 pe-3 align-middle">
          {isOwnerOrAdmin && !isPending && !isSelf ? (
            <Select
              value={member.role}
              onValueChange={(val) => handleRoleSelect(uid, val)}
            >
              <SelectTrigger className="h-7 w-[124px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTION_KEYS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {t(opt.key)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <RoleBadge role={member.role} />
          )}
        </td>
        <td className="py-3 pe-3 align-middle">
          <span className="text-[11px] text-fg-3 tabular-nums">
            {formatRelative(member.last_active_at)}
          </span>
        </td>
        <td className="py-3 pe-3 align-middle">
          <span className="text-[11px] text-fg-3 tabular-nums">
            {formatJoined(member.joined_at || member.created_at)}
          </span>
        </td>
        <td className="py-3 pe-3 align-middle">
          {isPending ? (
            <Badge variant="roleViewer" className="gap-1">
              {t('status.pending')}
            </Badge>
          ) : authMethod === 'sso' ? (
            <Badge variant="roleEditor" className="gap-1">
              <ShieldCheck className="h-3 w-3" />
              {t('auth.sso')}
            </Badge>
          ) : (
            <Badge variant="roleViewer" className="gap-1">
              <Key className="h-3 w-3" />
              {t('auth.password')}
            </Badge>
          )}
        </td>
        <td className="py-3 ps-2 align-middle text-end w-10">
          {isOwnerOrAdmin && !isPending && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 text-fg-3 hover:text-fg-1"
                  aria-label={t('workspaceSettings.members.memberActions')}
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {isOwner && !isSelf && member.role !== 'owner' && (
                  <>
                    <DropdownMenuItem
                      onClick={() => setTransferTarget(member)}
                      className="gap-2"
                    >
                      <ArrowRightLeft className="h-4 w-4" />
                      {t('workspaceSettings.members.transferOwnership')}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                )}
                <DropdownMenuItem
                  onClick={() => handleRemoveClick(uid)}
                  className="gap-2 text-err focus:text-err"
                >
                  <Trash2 className="h-4 w-4" />
                  {t('common:actions.remove')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </td>
      </tr>
    )
  }

  if (active.length === 0 && pending.length === 0) {
    return (
      <p className="text-sm text-fg-3 px-4 py-6">{t('workspaceSettings.members.noMembers')}</p>
    )
  }

  return (
    <>
      <Table bordered={false}>
        <TableHeader>
          <TableHeadRow>
            <TableHead>{t('workspaceSettings.members.headers.name')}</TableHead>
            <TableHead>{t('workspaceSettings.members.headers.role')}</TableHead>
            <TableHead>{t('workspaceSettings.members.headers.lastActive')}</TableHead>
            <TableHead>{t('workspaceSettings.members.headers.joined')}</TableHead>
            <TableHead>{t('workspaceSettings.members.headers.auth')}</TableHead>
            <TableHead className="w-10" />
          </TableHeadRow>
        </TableHeader>
        <TableBody ref={tbodyRef} className="[&>tr>td]:px-4">
          {active.map(renderRow)}
          {pending.map(renderRow)}
        </TableBody>
      </Table>

      {/* Transfer ownership confirm dialog */}
      <Dialog open={!!transferTarget} onOpenChange={(open) => !open && setTransferTarget(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('workspaceSettings.members.transferConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {transferTarget?.user?.display_name || transferTarget?.user?.email}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-fg-2">
            {t('workspaceSettings.members.transferConfirmBody')}
          </p>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setTransferTarget(null)}
              disabled={transferBusy}
            >
              {t('common:actions.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleTransferOwnership}
              disabled={transferBusy}
            >
              {transferBusy ? '...' : t('workspaceSettings.members.transferConfirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {confirmDialog}
    </>
  )
}
