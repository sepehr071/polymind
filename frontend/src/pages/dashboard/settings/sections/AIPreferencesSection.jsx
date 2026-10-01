import { useState, useEffect, useMemo, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Save, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { aiPreferencesService } from '@/services/aiPreferencesService'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/utils/cn'

// Stored `value` stays an English-name identifier (the backend AI prompt reads
// it as the output language); only the displayed label is localised. Persian is
// first so Persian-speaking users see their language at the top of the list.
const CONTROL_W = 'w-[240px]'

function FieldRow({ title, desc, htmlFor, children }) {
  return (
    <div className="flex items-center gap-4">
      <div className="min-w-0 flex-1 space-y-0.5 text-start">
        <Label htmlFor={htmlFor} className="text-[13px] font-semibold leading-none">{title}</Label>
        {desc && <p className="text-xs leading-snug text-foreground-tertiary">{desc}</p>}
      </div>
      <div className={cn('flex h-10 shrink-0 items-center', CONTROL_W)}>
        {children}
      </div>
    </div>
  )
}

const LANGUAGE_OPTIONS = [
  { value: 'Persian', key: 'languages.persian' },
  { value: 'English', key: 'languages.english' },
  { value: 'Spanish', key: 'languages.spanish' },
  { value: 'French', key: 'languages.french' },
  { value: 'German', key: 'languages.german' },
  { value: 'Chinese', key: 'languages.chinese' },
  { value: 'Arabic', key: 'languages.arabic' },
  { value: 'Portuguese', key: 'languages.portuguese' },
  { value: 'Russian', key: 'languages.russian' },
  { value: 'Japanese', key: 'languages.japanese' },
  { value: 'Korean', key: 'languages.korean' },
  { value: 'Italian', key: 'languages.italian' },
  { value: 'Dutch', key: 'languages.dutch' },
  { value: 'Hindi', key: 'languages.hindi' },
]

export default function AIPreferencesSection() {
  const { t } = useTranslation('settings')
  const queryClient = useQueryClient()
  const [preferences, setPreferences] = useState({
    enabled: true,
    user_info: { name: '', language: 'English', expertise_level: 'intermediate' },
    behavior: { tone: 'professional', response_style: 'balanced' },
    custom_instructions: '',
  })
  // Baseline snapshot of the last-saved (server) state. Compared against the
  // live form to derive a dirty flag so Save is disabled when nothing changed.
  const baselineRef = useRef(null)

  // Localised option arrays only change when the translator (`t`) does, i.e. on
  // language switch — memoise so they aren't rebuilt on every form keystroke.
  const EXPERTISE_LEVELS = useMemo(() => [
    { value: 'beginner', label: t('aiPreferences.expertiseBeginner') },
    { value: 'intermediate', label: t('aiPreferences.expertiseIntermediate') },
    { value: 'expert', label: t('aiPreferences.expertiseExpert') },
  ], [t])

  const TONES = useMemo(() => [
    { value: 'professional', label: t('aiPreferences.toneProfessional') },
    { value: 'friendly', label: t('aiPreferences.toneFriendly') },
    { value: 'casual', label: t('aiPreferences.toneCasual') },
  ], [t])

  const RESPONSE_STYLES = useMemo(() => [
    { value: 'concise', label: t('aiPreferences.styleConcise') },
    { value: 'balanced', label: t('aiPreferences.styleBalanced') },
    { value: 'detailed', label: t('aiPreferences.styleDetailed') },
  ], [t])

  const { data, isLoading } = useQuery({
    queryKey: ['ai-preferences'],
    queryFn: aiPreferencesService.get,
  })

  useEffect(() => {
    if (data?.preferences) {
      const next = {
        enabled: data.preferences.enabled ?? true,
        user_info: {
          name: data.preferences.user_info?.name || '',
          language: data.preferences.user_info?.language || 'English',
          expertise_level: data.preferences.user_info?.expertise_level || 'intermediate',
        },
        behavior: {
          tone: data.preferences.behavior?.tone || 'professional',
          response_style: data.preferences.behavior?.response_style || 'balanced',
        },
        custom_instructions: data.preferences.custom_instructions || '',
      }
      // Snapshot the server state as the dirty-comparison baseline before
      // applying it to the form, so a fresh load / post-save refetch resets it.
      baselineRef.current = JSON.stringify(next)
      setPreferences(next)
    }
  }, [data])

  // Dirty when the live form diverges from the last-saved baseline. Stable key
  // order (same shape both sides) makes JSON comparison reliable here.
  const isDirty = useMemo(
    () => baselineRef.current != null && JSON.stringify(preferences) !== baselineRef.current,
    [preferences]
  )

  const updateMutation = useMutation({
    mutationFn: aiPreferencesService.update,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-preferences'] })
      toast.success(t('aiPreferences.updated'))
    },
    onError: () => toast.error(t('aiPreferences.failedToUpdate')),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    // Timezone is owned by Preferences section now — don't include it in the
    // payload so AI-Prefs Save can't clobber a value Preferences just wrote.
    updateMutation.mutate(preferences)
  }

  const updateUserInfo = (key, value) => {
    setPreferences((prev) => ({
      ...prev,
      user_info: { ...prev.user_info, [key]: value },
    }))
  }

  const updateBehavior = (key, value) => {
    setPreferences((prev) => ({
      ...prev,
      behavior: { ...prev.behavior, [key]: value },
    }))
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-6">
      <div className="flex w-full items-center justify-between gap-4">
        <Label className="text-[13px] font-semibold">{t('aiPreferences.enableLabel')}</Label>
        <Switch
          checked={preferences.enabled}
          onCheckedChange={(checked) => setPreferences((prev) => ({ ...prev, enabled: checked }))}
        />
      </div>
      <p dir="auto" className="w-full text-start text-xs leading-relaxed text-foreground-tertiary break-words">
        {t('aiPreferences.enableDesc')}
      </p>

      <div className={cn('space-y-6 transition-opacity', !preferences.enabled && 'opacity-50 pointer-events-none')}>
        <Separator />

        <div>
          <h3 className="mb-4 text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">{t('aiPreferences.userInfoTitle')}</h3>
          <div className="space-y-4">
            <FieldRow title={t('aiPreferences.yourName')} desc={t('aiPreferences.yourNameHint')} htmlFor="ai_name">
              <Input
                id="ai_name"
                type="text"
                value={preferences.user_info.name}
                onChange={(e) => updateUserInfo('name', e.target.value)}
                placeholder={t('aiPreferences.yourNamePlaceholder')}
                className="h-10 min-h-10 w-full rounded-[10px]"
              />
            </FieldRow>
            <FieldRow
              title={t('aiPreferences.outputLanguage')}
              desc={`${t('aiPreferences.outputLanguageHint')} ${t('aiPreferences.outputLanguageScopeNote')}`}
            >
              <Select value={preferences.user_info.language} onValueChange={(v) => updateUserInfo('language', v)}>
                <SelectTrigger className="h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGE_OPTIONS.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {t(`aiPreferences.${lang.key}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldRow>
            <FieldRow title={t('aiPreferences.expertiseLevel')} desc={t('aiPreferences.expertiseHint')}>
              <Select value={preferences.user_info.expertise_level} onValueChange={(v) => updateUserInfo('expertise_level', v)}>
                <SelectTrigger className="h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPERTISE_LEVELS.map((level) => (
                    <SelectItem key={level.value} value={level.value}>{level.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldRow>
          </div>
        </div>

        <Separator />

        <div>
          <h3 className="mb-4 text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">{t('aiPreferences.aiBehaviorTitle')}</h3>
          <div className="space-y-4">
            <FieldRow title={t('aiPreferences.tone')}>
              <Select value={preferences.behavior.tone} onValueChange={(v) => updateBehavior('tone', v)}>
                <SelectTrigger className="h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TONES.map((tone) => (
                    <SelectItem key={tone.value} value={tone.value}>{tone.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldRow>
            <FieldRow title={t('aiPreferences.responseStyle')}>
              <Select value={preferences.behavior.response_style} onValueChange={(v) => updateBehavior('response_style', v)}>
                <SelectTrigger className="h-10 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RESPONSE_STYLES.map((style) => (
                    <SelectItem key={style.value} value={style.value}>{style.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldRow>
          </div>
        </div>

        <Separator />

        <div>
          <h3 className="mb-4 text-[11px] font-bold uppercase tracking-wider text-foreground-tertiary">{t('aiPreferences.customInstructionsTitle')}</h3>
          <div className="space-y-2">
            <Textarea
              value={preferences.custom_instructions}
              onChange={(e) => setPreferences((prev) => ({ ...prev, custom_instructions: e.target.value.slice(0, 2000) }))}
              rows={5}
              placeholder={t('aiPreferences.customInstructionsPlaceholder')}
              maxLength={2000}
            />
            <p className="text-xs text-foreground-tertiary text-end">
              {t('aiPreferences.customInstructionsLimit', { count: preferences.custom_instructions.length })}
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={updateMutation.isPending || !isDirty}>
          {updateMutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin me-2" />
              {t('aiPreferences.saving')}
            </>
          ) : (
            <>
              <Save className="h-4 w-4 me-2" />
              {t('aiPreferences.savePreferences')}
            </>
          )}
        </Button>
        {isDirty && !updateMutation.isPending && (
          <span className="flex items-center gap-1.5 text-sm text-foreground-secondary" role="status">
            <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
            {t('aiPreferences.unsavedChanges')}
          </span>
        )}
      </div>
    </form>
  )
}
