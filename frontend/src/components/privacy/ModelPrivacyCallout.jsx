import { Cloud, HardDrive, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { resolvePrivacyMode } from '@/constants/modelPrivacy'

/**
 * PrivacyBadge — compact header chip (local = emerald bold, cloud = amber).
 * @param {'local'|'cloud'} mode  already-resolved display mode
 */
export function PrivacyBadge({ mode, className }) {
  const { t } = useTranslation('layout')
  if (mode !== 'local' && mode !== 'cloud') return null

  const local = mode === 'local'
  const Icon = local ? HardDrive : Cloud
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold tracking-tight',
        local
          ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
          : 'border-amber-500/45 bg-amber-500/15 text-amber-800 dark:text-amber-200',
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {t(local ? 'privacy.badge.local' : 'privacy.badge.cloud')}
    </span>
  )
}

/**
 * Hub chip — smaller; also supports unresolved `model` mode.
 */
export function PrivacyHubChip({ mode, className }) {
  const { t } = useTranslation('layout')
  if (!mode) return null

  if (mode === 'model') {
    return (
      <span
        className={cn(
          'mt-1 inline-flex items-center gap-1 rounded-md border border-border/70 bg-bg-2/80 px-1.5 py-0.5',
          'text-[10px] font-bold uppercase tracking-wide text-muted-foreground',
          className,
        )}
      >
        {t('privacy.badge.model')}
      </span>
    )
  }

  const local = mode === 'local'
  const Icon = local ? HardDrive : Cloud
  return (
    <span
      className={cn(
        'mt-1 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide',
        local
          ? 'border-emerald-500/40 bg-emerald-500/12 text-emerald-700 dark:text-emerald-300'
          : 'border-amber-500/40 bg-amber-500/12 text-amber-800 dark:text-amber-200',
        className,
      )}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      {t(local ? 'privacy.badge.local' : 'privacy.badge.cloud')}
    </span>
  )
}

/**
 * PrivacyBanner — full-width strip. Local = bold trust; cloud = warning.
 */
export function PrivacyBanner({ mode, className, onDismiss }) {
  const { t } = useTranslation('layout')
  if (mode !== 'local' && mode !== 'cloud') return null

  const local = mode === 'local'
  return (
    <div
      role={local ? 'status' : 'alert'}
      className={cn(
        'flex items-start gap-3 rounded-xl border px-4 py-3',
        local
          ? 'border-emerald-500/35 bg-emerald-500/10'
          : 'border-amber-500/40 bg-amber-500/10',
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'text-sm font-bold leading-snug',
            local ? 'text-emerald-800 dark:text-emerald-200' : 'text-amber-900 dark:text-amber-100',
          )}
        >
          {t(local ? 'privacy.banner.localTitle' : 'privacy.banner.cloudTitle')}
        </p>
        <p
          className={cn(
            'mt-0.5 text-[13px] leading-snug',
            local ? 'text-emerald-900/80 dark:text-emerald-100/80' : 'text-amber-950/80 dark:text-amber-50/80',
          )}
        >
          {t(local ? 'privacy.banner.localBody' : 'privacy.banner.cloudBody')}
        </p>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t('privacy.banner.dismiss')}
          className="shrink-0 rounded-md p-1 hover:bg-black/5 dark:hover:bg-white/10"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

/**
 * Resolve + render badge and/or banner from route mode + runtime opts.
 */
export function ModelPrivacyCallout({
  mode,
  modelId = null,
  localAvailable = false,
  showBadge = true,
  showBanner = true,
  badgeClassName,
  bannerClassName,
  className,
}) {
  const resolved = resolvePrivacyMode(mode, { modelId, localAvailable })
  if (!resolved) return null
  return (
    <div className={cn('space-y-3', className)}>
      {showBadge && <PrivacyBadge mode={resolved} className={badgeClassName} />}
      {showBanner && <PrivacyBanner mode={resolved} className={bannerClassName} />}
    </div>
  )
}

export default ModelPrivacyCallout
