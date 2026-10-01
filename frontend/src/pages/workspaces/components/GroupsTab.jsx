import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Plus, Pencil, Trash2, Users } from 'lucide-react'
import Section from '@/components/teams/Section'
import Ptile from '@/components/teams/Ptile'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import CreateGroupModal, {
  resolveGroupIcon,
} from '@/components/teams/CreateGroupModal'
import groupService from '@/services/groupService'

/**
 * GroupsTab — list + manage workspace permission groups.
 *
 * Reconciles edit-modal member additions/removals against the existing roster
 * by diffing in `handleSave` (`prev` vs `next`).
 */
export default function GroupsTab({
  wid,
  members = [],
  canManage = false,
  onCountChange,
}) {
  const { t } = useTranslation('projects')
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState(null) // hydrated group + members
  const [deleteTarget, setDeleteTarget] = useState(null)

  const loadGroups = useCallback(async () => {
    setLoading(true)
    try {
      const list = await groupService.list(wid)
      setGroups(list)
      onCountChange?.(list.length)
    } catch (err) {
      console.error('Failed to load groups', err)
      toast.error(t('workspaceSettings.groups.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [wid, onCountChange, t])

  useEffect(() => {
    loadGroups()
  }, [loadGroups])

  async function openEdit(group) {
    try {
      const full = await groupService.get(wid, group._id)
      setEditTarget(full)
    } catch {
      toast.error(t('workspaceSettings.groups.openFailed'))
    }
  }

  async function reconcileMembers(gid, prevIds, nextIds) {
    const toAdd = nextIds.filter((id) => !prevIds.includes(id))
    const toRemove = prevIds.filter((id) => !nextIds.includes(id))
    for (const uid of toAdd) {
      try {
        await groupService.addMember(wid, gid, uid)
      } catch (err) {
        console.error('addMember failed', err)
      }
    }
    for (const uid of toRemove) {
      try {
        await groupService.removeMember(wid, gid, uid)
      } catch (err) {
        console.error('removeMember failed', err)
      }
    }
  }

  async function handleCreate(payload) {
    const { member_ids, ...rest } = payload
    const created = await groupService.create(wid, rest)
    if (Array.isArray(member_ids) && member_ids.length > 0) {
      await reconcileMembers(created._id, [], member_ids)
    }
    toast.success(t('workspaceSettings.groups.created'))
    await loadGroups()
  }

  async function handleEdit(payload) {
    if (!editTarget) return
    const { member_ids, ...rest } = payload
    const prevIds = (editTarget.members || [])
      .map((m) => m.user?.id)
      .filter(Boolean)
    await groupService.update(wid, editTarget._id, rest)
    await reconcileMembers(editTarget._id, prevIds, member_ids || [])
    toast.success(t('workspaceSettings.groups.updated'))
    setEditTarget(null)
    await loadGroups()
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await groupService.delete(wid, deleteTarget._id)
      toast.success(t('workspaceSettings.groups.deleted'))
      setDeleteTarget(null)
      await loadGroups()
    } catch (err) {
      toast.error(err?.response?.data?.error || t('workspaceSettings.groups.deleteFailed'))
    }
  }

  return (
    <div style={{ maxWidth: 920 }}>
      <Section
        title={t('workspaceSettings.groups.title')}
        hint={t('workspaceSettings.groups.hint')}
        padded={false}
        action={
          canManage ? (
            <Button
              size="sm"
              onClick={() => setCreateOpen(true)}
              className="h-7 gap-1.5 text-xs"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('workspaceSettings.groups.newGroup')}
            </Button>
          ) : null
        }
      >
        {loading ? (
          <div className="px-4 py-6 text-sm text-fg-3">{t('workspaceSettings.groups.loading')}</div>
        ) : groups.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
            <Users className="h-6 w-6 text-fg-3" />
            <p className="text-sm text-fg-2">{t('workspaceSettings.groups.empty')}</p>
            {canManage && (
              <p className="text-xs text-fg-3">
                {t('workspaceSettings.groups.emptyHint')}
              </p>
            )}
          </div>
        ) : (
          <ul>
            {groups.map((g) => {
              const Icon = resolveGroupIcon(g.icon)
              return (
                <li
                  key={g._id}
                  className="flex items-center gap-3 border-b border-line px-4 py-3 last:border-0 hover:bg-bg-2/40 transition-colors"
                >
                  <Ptile
                    color={g.color || '#5c9aed'}
                    icon={Icon || undefined}
                    letter={!Icon ? (g.name?.[0] || '?').toUpperCase() : undefined}
                    size="sm"
                    gradient
                  />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm font-medium text-fg-0 truncate">
                      {g.name}
                    </span>
                    {g.description && (
                      <span className="text-[11px] text-fg-3 truncate">
                        {g.description}
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[11px] text-fg-3">
                    {t('workspaceSettings.groups.membersCount', { count: g.member_count ?? 0 })}
                  </span>
                  {canManage && (
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-fg-3 hover:text-fg-0"
                        onClick={() => openEdit(g)}
                        title={t('workspaceSettings.groups.editGroup')}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0 text-fg-3 hover:text-err"
                        onClick={() => setDeleteTarget(g)}
                        title={t('workspaceSettings.groups.deleteGroup')}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <CreateGroupModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={handleCreate}
        workspaceMembers={members}
      />

      <CreateGroupModal
        open={!!editTarget}
        onOpenChange={(v) => !v && setEditTarget(null)}
        onSubmit={handleEdit}
        editGroup={editTarget}
        existingMemberIds={
          editTarget?.members?.map((m) => m.user?.id).filter(Boolean) || []
        }
        workspaceMembers={members}
      />

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(v) => !v && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('workspaceSettings.groups.deleteConfirmTitle')} &quot;{deleteTarget?.name}&quot;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('workspaceSettings.groups.deleteConfirmDesc')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('workspaceSettings.groups.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-err text-accent-foreground hover:bg-err/90"
            >
              {t('workspaceSettings.groups.confirmDelete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
