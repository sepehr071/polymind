import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

export const SEVERITY_TONES = {
  critical: 'bg-err/15 text-err border-err/30',
  high: 'bg-warn/15 text-warn border-warn/30',
  medium: 'bg-warn/15 text-warn border-warn/30',
  low: 'bg-fg-3/15 text-fg-2 border-fg-3/30',
}

export const ACTION_TONES = {
  block: 'bg-err/15 text-err border-err/30',
  require_confirm: 'bg-warn/15 text-warn border-warn/30',
  warn: 'bg-accent/15 text-accent border-accent/30',
  redact: 'bg-accent/15 text-accent border-accent/30',
}

export function SeverityBadge({ severity }) {
  const { t } = useTranslation('dlp')
  return (
    <span className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium', SEVERITY_TONES[severity] || SEVERITY_TONES.low)}>
      {t(`severity.${severity}`, { defaultValue: severity })}
    </span>
  )
}

export function ActionBadge({ action }) {
  const { t } = useTranslation('dlp')
  return (
    <span className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium', ACTION_TONES[action] || ACTION_TONES.warn)}>
      {t(`action.${action}`, { defaultValue: action })}
    </span>
  )
}
