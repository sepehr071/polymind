import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Cpu, Thermometer } from 'lucide-react'
import Section from '@/components/teams/Section'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import projectService from '@/services/projectService'
import { configService } from '@/services/chatService'
import { QUICK_MODELS } from '@/constants/models'

/**
 * DefaultsTab — project-level default model + temperature.
 *
 * Owner-only writes; editors/viewers see read-only fields.
 */
export default function DefaultsTab({ project, onSaved }) {
  const { t } = useTranslation('projects')
  const [defaultModel, setDefaultModel] = useState(project?.default_model || '__none__')
  const [defaultTemp, setDefaultTemp] = useState(
    typeof project?.default_temperature === 'number'
      ? project.default_temperature
      : 0.7,
  )
  const [hasTempOverride, setHasTempOverride] = useState(
    typeof project?.default_temperature === 'number',
  )
  const [assistants, setAssistants] = useState([])
  const [busy, setBusy] = useState(false)

  const isOwner = project?.member_role === 'owner'

  useEffect(() => {
    setDefaultModel(project?.default_model || '__none__')
    if (typeof project?.default_temperature === 'number') {
      setDefaultTemp(project.default_temperature)
      setHasTempOverride(true)
    } else {
      setDefaultTemp(0.7)
      setHasTempOverride(false)
    }
  }, [project])

  // Load user's assistants for inclusion in the model picker.
  useEffect(() => {
    let alive = true
    async function loadAssistants() {
      try {
        const data = await configService.getConfigs()
        const list = Array.isArray(data) ? data : data?.configs || []
        if (alive) setAssistants(list)
      } catch {
        // No-op — fall back to quick models only.
      }
    }
    loadAssistants()
    return () => {
      alive = false
    }
  }, [])

  const modelOptions = useMemo(() => {
    const out = QUICK_MODELS.map((m) => ({
      value: m.id,
      label: m.name,
      hint: m.description,
      group: t('projectSettings.defaults.modelGroupQuick'),
    }))
    if (Array.isArray(assistants)) {
      assistants.forEach((a) => {
        if (a.model) {
          out.push({
            value: a.model,
            label: a.name || a.model,
            hint: t('projectSettings.defaults.assistantHint'),
            group: t('projectSettings.defaults.modelGroupAssistants'),
          })
        }
      })
    }
    return out
  }, [assistants, t])

  async function handleSave() {
    if (!isOwner) return
    setBusy(true)
    try {
      const payload = {
        default_model:
          defaultModel === '__none__' ? null : defaultModel,
        default_temperature: hasTempOverride ? Number(defaultTemp) : null,
      }
      const updated = await projectService.update(project._id, payload)
      toast.success(t('projectSettings.defaults.savedToast'))
      onSaved?.(updated)
    } catch (ex) {
      toast.error(ex.response?.data?.error || t('projectSettings.defaults.saveFailedToast'))
    } finally {
      setBusy(false)
    }
  }

  const disabled = !isOwner

  return (
    <div className="space-y-4">
      <Section
        title={t('projectSettings.defaults.modelTitle')}
        hint={t('projectSettings.defaults.modelDesc')}
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-fg-2" />
            <Label className="text-[13px] font-medium text-fg-1">
              {t('projectSettings.defaults.modelLabel')}
            </Label>
          </div>
          <Select
            value={defaultModel}
            onValueChange={setDefaultModel}
            disabled={disabled}
          >
            <SelectTrigger className="w-full max-w-[420px]">
              <SelectValue placeholder={t('projectSettings.defaults.noDefaultPlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t('projectSettings.defaults.noDefault')}</SelectItem>
              {modelOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  <span className="flex flex-col">
                    <span>{opt.label}</span>
                    {opt.hint && (
                      <span className="text-[11px] text-fg-3">
                        {opt.hint}
                      </span>
                    )}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11.5px] text-fg-3">
            {t('projectSettings.defaults.currently')}{' '}
            <span className="font-mono text-fg-2">
              {project?.default_model || t('projectSettings.defaults.noneFallback')}
            </span>
          </p>
        </div>
      </Section>

      <Section
        title={t('projectSettings.defaults.temperatureTitle')}
        hint={t('projectSettings.defaults.temperatureDesc')}
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-fg-2" />
            <Label className="text-[13px] font-medium text-fg-1">
              {t('projectSettings.defaults.temperatureLabel')}
            </Label>
            <span className="ms-auto font-mono text-[13px] text-fg-1">
              {hasTempOverride ? defaultTemp.toFixed(1) : '—'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Slider
              value={[defaultTemp]}
              onValueChange={(v) => {
                setDefaultTemp(v[0])
                setHasTempOverride(true)
              }}
              min={0}
              max={2}
              step={0.1}
              disabled={disabled}
              className="flex-1"
            />
            {hasTempOverride && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={disabled}
                onClick={() => {
                  setHasTempOverride(false)
                  setDefaultTemp(0.7)
                }}
              >
                {t('common:actions.clear')}
              </Button>
            )}
          </div>
          <p className="text-[11.5px] text-fg-3">
            {t('projectSettings.defaults.temperatureHint')}
          </p>
        </div>
      </Section>

      <div className="flex justify-end pt-1">
        <Button
          onClick={handleSave}
          disabled={busy || disabled}
          title={disabled ? t('projectSettings.defaults.ownerOnly') : undefined}
        >
          {busy ? t('projectSettings.defaults.saving') : t('projectSettings.defaults.saveDefaults')}
        </Button>
      </div>
    </div>
  )
}
