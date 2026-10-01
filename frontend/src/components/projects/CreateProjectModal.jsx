import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

const COLORS = [
  { hex: '#5c9aed', nameKey: 'createProject.colors.blue' },
  { hex: '#7c3aed', nameKey: 'createProject.colors.violet' },
  { hex: '#10b981', nameKey: 'createProject.colors.green' },
  { hex: '#f59e0b', nameKey: 'createProject.colors.amber' },
  { hex: '#ef4444', nameKey: 'createProject.colors.red' },
  { hex: '#ec4899', nameKey: 'createProject.colors.pink' },
  { hex: '#06b6d4', nameKey: 'createProject.colors.cyan' },
  { hex: '#84cc16', nameKey: 'createProject.colors.lime' },
]

export default function CreateProjectModal({ open, onOpenChange, onSubmit, editProject = null }) {
  const { t } = useTranslation('projects')
  const [name, setName] = useState('')
  const [color, setColor] = useState(COLORS[0].hex)
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (open) {
      setName(editProject?.name || '')
      setColor(editProject?.color || COLORS[0].hex)
      setDescription(editProject?.description || '')
      setErr(null)
    }
  }, [open, editProject])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) { setErr(t('createProject.nameRequired', 'Name required')); return }
    setBusy(true); setErr(null)
    try {
      await onSubmit({ name: name.trim(), color, description: description.trim() || null })
      onOpenChange(false)
    } catch (ex) {
      setErr(ex.response?.data?.error || t('createProject.saveFailed', 'Could not save project'))
    } finally { setBusy(false) }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editProject ? t('createProject.titleEdit') : t('createProject.titleNew')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="proj-name">{t('createProject.nameLabel')}</Label>
            <Input id="proj-name" value={name} onChange={e => setName(e.target.value)} maxLength={100} autoFocus required placeholder={t('createProject.namePlaceholder')} />
          </div>
          <div className="space-y-2">
            <Label>{t('createProject.colorLabel')}</Label>
            <div className="flex gap-2" role="group" aria-label={t('createProject.colorLabel')}>
              {COLORS.map(c => {
                const selected = color === c.hex
                return (
                  <button
                    key={c.hex}
                    type="button"
                    onClick={() => setColor(c.hex)}
                    aria-pressed={selected}
                    aria-label={t(c.nameKey)}
                    className={cn(
                      'h-7 w-7 rounded-md ring-offset-2 ring-offset-background transition-shadow',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      selected
                        ? 'ring-2 ring-foreground'
                        : 'ring-1 ring-line-2 hover:ring-fg-3',
                    )}
                    style={{ background: c.hex }}
                  />
                )
              })}
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="proj-desc">{t('createProject.descriptionLabel')}</Label>
            <Input id="proj-desc" value={description} onChange={e => setDescription(e.target.value)} maxLength={500} placeholder={t('createProject.descriptionPlaceholder')} />
          </div>
          {err && <p className="text-sm text-err">{err}</p>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>{t('common:actions.cancel')}</Button>
            <Button type="submit" disabled={busy || !name.trim()}>{busy ? (editProject ? t('createProject.saving') : t('createProject.creating')) : (editProject ? t('createProject.saveButton') : t('createProject.createButton'))}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
