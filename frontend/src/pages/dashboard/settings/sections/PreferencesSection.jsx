import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { userService } from '@/services/userService'
import { aiPreferencesService } from '@/services/aiPreferencesService'
import { useTheme } from '@/context/ThemeContext'
import { useLanguage } from '@/context/LanguageContext'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/utils/cn'

const COMMON_TIMEZONES = [
  'UTC',
  'America/Los_Angeles',
  'America/Denver',
  'America/Chicago',
  'America/New_York',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
]

function getAllTimezones() {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return COMMON_TIMEZONES
  }
}

const ALL_TIMEZONES = getAllTimezones()
const OTHER_TIMEZONES = ALL_TIMEZONES.filter((tz) => !COMMON_TIMEZONES.includes(tz))

const CONTROL_W = 'w-[240px]'

// Canonical 2+ option segmented filter (ui/tabs.jsx segmented variant).
function SegmentedControl({ value, onValueChange, options, ariaLabel }) {
  return (
    <Tabs value={value} onValueChange={onValueChange} variant="segmented">
      <TabsList aria-label={ariaLabel} className="h-10 w-full">
        {options.map((opt) => (
          <TabsTrigger key={opt.value} value={opt.value} className="h-8 leading-none">
            {opt.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

function RowLabel({ title, desc, htmlFor }) {
  return (
    <div className="min-w-0 space-y-0.5 text-start">
      <Label htmlFor={htmlFor} className="text-[13px] font-semibold leading-none">{title}</Label>
      {desc && <p className="text-xs leading-snug text-foreground-tertiary">{desc}</p>}
    </div>
  )
}

/** Label (start) + control (end), vertically centered. Control column = 240×40. */
function PrefRow({ title, desc, htmlFor, children }) {
  return (
    <div className="flex items-center gap-4">
      <div className="min-w-0 flex-1">
        <RowLabel title={title} desc={desc} htmlFor={htmlFor} />
      </div>
      <div className={cn('flex h-10 shrink-0 items-center justify-end', CONTROL_W)}>
        {children}
      </div>
    </div>
  )
}

export default function PreferencesSection() {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const queryClient = useQueryClient()
  const { theme, setTheme } = useTheme()
  const { language, setLanguage, numerals, setNumerals } = useLanguage()

  const { data: settingsData, isLoading: settingsLoading } = useQuery({
    queryKey: ['user-settings'],
    queryFn: userService.getSettings,
  })
  const settings = settingsData?.settings || {}

  const { data: aiPrefsData, isLoading: aiPrefsLoading } = useQuery({
    queryKey: ['ai-preferences'],
    queryFn: aiPreferencesService.get,
  })
  const timezone = aiPrefsData?.preferences?.timezone || 'UTC'

  const updateSettingsMutation = useMutation({
    mutationFn: userService.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-settings'] })
      toast.success(t('preferences.updated'))
    },
    onError: () => toast.error(t('preferences.failedToUpdate')),
  })

  const updateTimezoneMutation = useMutation({
    mutationFn: (tz) => aiPreferencesService.update({ timezone: tz }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-preferences'] })
      toast.success(t('preferences.timezoneSaved'))
    },
    onError: () => toast.error(t('preferences.failedToUpdate')),
  })

  const handleThemeChange = (newTheme) => {
    setTheme(newTheme)
    updateSettingsMutation.mutate({ theme: newTheme })
  }

  if (settingsLoading || aiPrefsLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PrefRow
        title={t('preferences.interfaceLanguageTitle')}
        desc={t('preferences.interfaceLanguageDesc')}
      >
        <Select
          value={language}
          onValueChange={(value) => {
            setLanguage(value)
            toast.success(t('preferences.languageChangedToast'))
          }}
        >
          <SelectTrigger className="h-10 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="en">{tCommon('language.english')}</SelectItem>
            <SelectItem value="fa">{tCommon('language.persian')}</SelectItem>
          </SelectContent>
        </Select>
      </PrefRow>

      <Separator />

      <PrefRow
        title={t('preferences.numeralsTitle')}
        desc={t('preferences.numeralsDesc')}
      >
        <SegmentedControl
          ariaLabel={t('preferences.numeralsTitle')}
          value={numerals}
          onValueChange={(value) => {
            setNumerals(value)
            toast.success(t('preferences.numeralsChangedToast'))
          }}
          options={[
            { value: 'latin', label: t('preferences.numeralsLatin') },
            { value: 'persian', label: t('preferences.numeralsPersian') },
          ]}
        />
      </PrefRow>

      <Separator />

      <PrefRow
        title={t('preferences.themeLabel')}
        desc={t('preferences.themeDesc')}
      >
        <SegmentedControl
          ariaLabel={t('preferences.themeLabel')}
          value={theme}
          onValueChange={handleThemeChange}
          options={[
            { value: 'light', label: t('preferences.themeLight') },
            { value: 'dark', label: t('preferences.themeDark') },
          ]}
        />
      </PrefRow>

      <Separator />

      <PrefRow
        title={t('preferences.timezoneLabel')}
        desc={t('preferences.timezoneDesc')}
      >
        <Select
          value={timezone}
          onValueChange={(v) => updateTimezoneMutation.mutate(v)}
          disabled={updateTimezoneMutation.isPending}
        >
          <SelectTrigger className="h-10 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              value="__label_common__"
              disabled
              className="text-xs font-semibold text-foreground-tertiary uppercase tracking-wider"
            >
              {t('preferences.timezoneCommonLabel')}
            </SelectItem>
            {COMMON_TIMEZONES.map((tz) => (
              <SelectItem key={tz} value={tz}>
                <span dir="ltr">{tz}</span>
              </SelectItem>
            ))}
            {OTHER_TIMEZONES.length > 0 && (
              <SelectItem
                value="__label_all__"
                disabled
                className="text-xs font-semibold text-foreground-tertiary uppercase tracking-wider mt-1"
              >
                {t('preferences.timezoneAllLabel')}
              </SelectItem>
            )}
            {OTHER_TIMEZONES.map((tz) => (
              <SelectItem key={tz} value={tz}>
                <span dir="ltr">{tz}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </PrefRow>

      <Separator />

      <PrefRow
        title={t('preferences.notificationsLabel')}
        desc={t('preferences.notificationsDesc')}
      >
        <Switch
          checked={!!settings.notifications_enabled}
          onCheckedChange={(checked) => updateSettingsMutation.mutate({ notifications_enabled: checked })}
        />
      </PrefRow>
    </div>
  )
}
