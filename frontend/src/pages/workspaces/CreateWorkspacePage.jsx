import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Building2 } from 'lucide-react'
import PageHeader from '@/components/layout/PageHeader'
import PageShell from '@/components/layout/PageShell'
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
import { workspaceService } from '@/services/workspaceService'
import { useWorkspace } from '@/context/WorkspaceContext'
import { makeSwitchTo } from '@/utils/navHelpers'

/**
 * CreateWorkspacePage — provision a new team workspace.
 * Personal workspaces are created automatically at signup, so the form only
 * supports team type. On success we set the new workspace active and route
 * to its overview.
 */
export default function CreateWorkspacePage() {
  const { t } = useTranslation('projects')
  const { t: tc } = useTranslation('companies')
  const nav = useNavigate()
  const location = useLocation()
  const { refresh, setActiveWorkspace, currentWorkspace } = useWorkspace()
  const switchTo = makeSwitchTo({
    setActiveWorkspace,
    currentWorkspaceId: currentWorkspace?._id,
    navigate: nav,
    location,
  })
  const [name, setName] = useState('')
  const [type, setType] = useState('team')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim()) {
      setErr(t('createWorkspace.nameRequired'))
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const created = await workspaceService.create({
        name: name.trim(),
        type,
      })
      // Refresh the workspace list so context picks up the new one.
      await refresh()
      // P1.20: set it active AND re-target the URL via the shared helper so
      // wid-scoped routes don't drift to the old workspace id.
      switchTo(created)
      toast.success(tc('created', { name: created.name }))
      nav(`/workspaces/${created._id}`)
    } catch (ex) {
      const msg = ex?.response?.data?.error || t('createWorkspace.createFailed')
      setErr(msg)
      toast.error(msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageShell>
      <PageHeader
        icon={Building2}
        title={t('createWorkspace.title')}
        subtitle={t('createWorkspace.subtitle')}
      />

      <div className="max-w-[640px] space-y-4">
        <Section
          title={t('createWorkspace.detailsTitle')}
          hint={t('createWorkspace.detailsHint')}
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="cw-name">{t('createWorkspace.nameLabel')}</Label>
              <Input
                id="cw-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('createWorkspace.namePlaceholder')}
                maxLength={100}
                required
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cw-type">{t('createWorkspace.typeLabel')}</Label>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger id="cw-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="team">
                    <span className="flex items-center gap-2">
                      <Building2 className="h-4 w-4" />
                      {t('createWorkspace.typeTeam')}
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {err && <p className="text-sm text-err">{err}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => nav(-1)}
                disabled={busy}
              >
                {t('common:actions.cancel')}
              </Button>
              <Button type="submit" disabled={busy || !name.trim()}>
                {busy ? t('createWorkspace.creating') : t('createWorkspace.createButton')}
              </Button>
            </div>
          </form>
        </Section>
      </div>
    </PageShell>
  )
}
