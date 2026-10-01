import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Cpu, Sparkle, Flame, MessageCircle, Shield, Database, Package, Users, Check } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

// Mirrors design parts/data.jsx PROJECT_COLORS — 10 swatches.
const COLORS = [
  '#5c9aed', '#a78bfa', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#06b6d4', '#84cc16',
  '#6366f1', '#14b8a6',
]

// Icon name → lucide component. Names align with backend ``group.icon``
// strings used in the design (cpu / sparkle / flame / message / shield /
// database / package / users).
const ICON_OPTIONS = [
  { name: 'cpu', Comp: Cpu },
  { name: 'sparkle', Comp: Sparkle },
  { name: 'flame', Comp: Flame },
  { name: 'message', Comp: MessageCircle },
  { name: 'shield', Comp: Shield },
  { name: 'database', Comp: Database },
  { name: 'package', Comp: Package },
  { name: 'users', Comp: Users },
]

function getInitials(value) {
  if (!value) return '??'
  const parts = String(value).trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0] || '').join('').toUpperCase() || '??'
}

/**
 * CreateGroupModal — create or edit a workspace group.
 *
 * Props:
 *   open                  — controlled open state.
 *   onOpenChange(boolean) — close handler.
 *   onSubmit(payload)     — async; receives `{ name, color, icon, description, member_ids }`.
 *                           Caller is expected to: (a) create/update the group,
 *                           and (b) reconcile member additions/removals.
 *   editGroup             — null for create, or `{ _id, name, color, icon, description }`.
 *   existingMemberIds     — array of user IDs currently in the group (edit mode).
 *   workspaceMembers      — list of `WorkspaceMember` rows from `workspaceService.members(wid)`.
 *                           Used to populate the member picker.
 */
export default function CreateGroupModal({
  open,
  onOpenChange,
  onSubmit,
  editGroup = null,
  existingMemberIds = [],
  workspaceMembers = [],
}) {
  const { t } = useTranslation(['projects', 'common'])
  const [name, setName] = useState('')
  const [color, setColor] = useState(COLORS[0])
  const [icon, setIcon] = useState(ICON_OPTIONS[0].name)
  const [description, setDescription] = useState('')
  const [memberIds, setMemberIds] = useState([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!open) return
    setName(editGroup?.name || '')
    setColor(editGroup?.color || COLORS[0])
    setIcon(editGroup?.icon || ICON_OPTIONS[0].name)
    setDescription(editGroup?.description || '')
    setMemberIds(existingMemberIds || [])
    setSearch('')
    setErr(null)
  }, [open, editGroup, existingMemberIds])

  const eligibleMembers = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (workspaceMembers || [])
      .filter((m) => m.status !== 'pending' && m.user?.id)
      .filter((m) => {
        if (!q) return true
        const name = (m.user.display_name || '').toLowerCase()
        const email = (m.user.email || '').toLowerCase()
        return name.includes(q) || email.includes(q)
      })
  }, [workspaceMembers, search])

  function toggleMember(uid) {
    setMemberIds((prev) =>
      prev.includes(uid) ? prev.filter((id) => id !== uid) : [...prev, uid],
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) {
      setErr(t('createGroup.errors.nameRequired'))
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await onSubmit({
        name: name.trim(),
        color,
        icon,
        description: description.trim() || null,
        member_ids: memberIds,
      })
      onOpenChange(false)
    } catch (ex) {
      setErr(ex?.response?.data?.error || t('createGroup.errors.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editGroup ? t('createGroup.titleEdit') : t('createGroup.titleNew')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="grp-name">{t('createGroup.nameLabel')}</Label>
            <Input
              id="grp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={80}
              autoFocus
              required
              placeholder={t('createGroup.namePlaceholderExample')}
            />
          </div>

          <div className="space-y-2">
            <Label>{t('createGroup.colorLabel')}</Label>
            <div className="flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={cn(
                    'w-7 h-7 rounded-md border-2 transition-colors',
                    color === c ? 'border-fg-0' : 'border-transparent',
                  )}
                  style={{ background: c }}
                  aria-label={t('createGroup.colorAriaLabel', { color: c })}
                />
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t('createGroup.iconLabel')}</Label>
            <ToggleGroup
              type="single"
              value={icon}
              // Keep one icon always selected: ignore a deselect-to-null toggle.
              onValueChange={(val) => { if (val) setIcon(val) }}
              className="flex-wrap justify-start gap-2"
            >
              {ICON_OPTIONS.map(({ name: iname, Comp }) => (
                <ToggleGroupItem
                  key={iname}
                  value={iname}
                  aria-label={iname}
                  title={iname}
                  className="h-8 w-8 min-w-0 p-0 border-line bg-bg-2 text-fg-2 hover:border-line-2 [&.Mui-selected]:border-accent [&.Mui-selected]:bg-accent/15 [&.Mui-selected]:text-fg-0"
                >
                  <Comp className="h-4 w-4" />
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          <div className="space-y-2">
            <Label htmlFor="grp-desc">{t('createGroup.descriptionLabel')}</Label>
            <Textarea
              id="grp-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              rows={2}
              placeholder={t('createGroup.descriptionPlaceholder')}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t('createGroup.membersLabel')}</Label>
              <span className="text-xs text-fg-3">
                {t('createGroup.selectedCount', { count: memberIds.length })}
              </span>
            </div>
            <Input
              type="search"
              placeholder={t('createGroup.membersPlaceholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="max-h-48 overflow-y-auto rounded-xl border border-line bg-bg-2/50">
              {eligibleMembers.length === 0 && (
                <p className="px-3 py-4 text-xs text-fg-3">
                  {t('createGroup.noMatching')}
                </p>
              )}
              {eligibleMembers.map((m) => {
                const uid = m.user.id
                const checked = memberIds.includes(uid)
                const label = m.user.display_name || m.user.email || t('createGroup.unknownUser')
                return (
                  <button
                    key={uid}
                    type="button"
                    onClick={() => toggleMember(uid)}
                    className={cn(
                      'flex w-full items-center gap-2 px-3 py-2 text-start text-sm hover:bg-bg-3 transition-colors',
                      checked && 'bg-accent/5',
                    )}
                  >
                    <span
                      className={cn(
                        'inline-flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border',
                        checked
                          ? 'border-accent bg-accent text-accent-foreground'
                          : 'border-line-2 bg-bg-0',
                      )}
                    >
                      {checked && <Check className="h-3 w-3" />}
                    </span>
                    <span className="text-fg-1 truncate">{label}</span>
                    {m.user.email && m.user.display_name && (
                      <span className="text-xs text-fg-3 truncate">
                        {m.user.email}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {err && <p className="text-sm text-err">{err}</p>}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={busy}
            >
              {t('common:actions.cancel')}
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy
                ? editGroup
                  ? t('createGroup.saving')
                  : t('createGroup.creating')
                : editGroup
                  ? t('createGroup.saveButton')
                  : t('createGroup.createButton')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// Re-export the icon resolver helper for use in GroupsTab rows.
// Returns the matched lucide component for the bounded ICON_OPTIONS set, or the
// raw name string for any other stored value — Ptile resolves a string name
// lazily via <DynamicIcon>, so we avoid importing the full lucide barrel here.
// Empty input → null (caller renders a letter fallback).
export function resolveGroupIcon(iconName) {
  if (!iconName) return null
  const found = ICON_OPTIONS.find((o) => o.name === iconName)
  if (found) return found.Comp
  return iconName
}

export { COLORS as GROUP_COLORS, ICON_OPTIONS as GROUP_ICONS, getInitials }
