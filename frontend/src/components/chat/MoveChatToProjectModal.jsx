import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Folder } from 'lucide-react'
import { useProject } from '@/context/ProjectContext'
import api from '@/services/api'

export default function MoveChatToProjectModal({ open, onOpenChange, conversationId, currentProjectId, onMoved }) {
  const { t } = useTranslation('chat')
  const { projects } = useProject()
  const [selected, setSelected] = useState(currentProjectId || null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => { if (open) { setSelected(currentProjectId || null); setErr(null) } }, [open, currentProjectId])

  async function handleSubmit() {
    setBusy(true); setErr(null)
    try {
      await api.post(`/conversations/${conversationId}/move`, { project_id: selected })
      onMoved?.(selected)
      onOpenChange(false)
    } catch (ex) {
      setErr(ex.response?.data?.error || t('moveChatModal.moveError'))
    } finally { setBusy(false) }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('moveChatModal.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-1 max-h-72 overflow-auto">
          <button onClick={() => setSelected(null)}
            className={`w-full text-start rounded-md px-3 py-2 hover:bg-background-tertiary flex items-center gap-2 ${selected === null ? 'bg-background-tertiary' : ''}`}>
            <Folder className="h-4 w-4 opacity-60" />
            <span className="italic text-foreground-tertiary">{t('moveChatModal.unfiled')}</span>
          </button>
          {projects.filter(p => !p.archived).map(p => (
            <button key={p._id} onClick={() => setSelected(p._id)}
              className={`w-full text-start rounded-md px-3 py-2 hover:bg-background-tertiary flex items-center gap-2 ${selected === p._id ? 'bg-background-tertiary' : ''}`}>
              <Folder className="h-4 w-4" style={p.color ? { color: p.color } : undefined} />
              <span className="truncate">{p.name}</span>
            </button>
          ))}
        </div>
        {err && <p className="text-sm text-error">{err}</p>}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>{t('moveChatModal.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={busy}>{t('moveChatModal.move')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
