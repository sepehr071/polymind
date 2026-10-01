import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronLeft } from 'lucide-react'
import { cn } from '@/utils/cn'

function hexAlpha(hex, alpha) {
  const n = Math.round(Math.min(1, Math.max(0, alpha)) * 255).toString(16).padStart(2, '0')
  return `${hex}${n}`
}

/**
 * Home assistant tile. Compact like the ERP module card: icon, one title,
 * one subtitle, corner arrow. No frost.
 */
export default function ToolCard({ to, icon: Icon, art, labelKey, descKey }) {
  const { t } = useTranslation('layout')
  const { t: td } = useTranslation('dashboard')
  const slug = typeof labelKey === 'string' && labelKey.startsWith('sidebar.')
    ? labelKey.slice('sidebar.'.length)
    : null
  const label = slug
    ? td(`hub.toolTitle.${slug}`, { defaultValue: t(labelKey) })
    : t(labelKey)
  const fill = art?.fill

  return (
    <Link
      to={to}
      className={cn(
        'group relative flex h-full w-full flex-col overflow-hidden rounded-[20px] border border-border bg-background-secondary p-4 pb-12 text-start no-underline',
        'shadow-[0_1px_2px_rgb(17_24_39/0.04),0_8px_24px_-12px_rgb(30_71_209/0.14)]',
        'transition-transform duration-200 hover:-translate-y-0.5 hover:border-accent/40 dark:shadow-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'pointer-events-none absolute -bottom-12 -start-10 h-36 w-36 rounded-full',
          !fill && 'bg-accent/[0.12] dark:bg-accent/20',
        )}
        style={fill ? { background: hexAlpha(fill, 0.16) } : undefined}
      />
      <span
        aria-hidden
        className={cn(
          'pointer-events-none absolute -bottom-10 start-12 h-24 w-24 rounded-full',
          !fill && 'bg-accent/[0.08] dark:bg-accent/10',
        )}
        style={fill ? { background: hexAlpha(fill, 0.1) } : undefined}
      />

      <span className="relative z-10 grid h-11 w-11 place-items-center overflow-hidden rounded-2xl">
        {art?.src ? (
          <img src={art.src} alt="" className="h-11 w-11 object-cover" />
        ) : (
          <span
            className={cn(
              'grid h-11 w-11 place-items-center rounded-2xl',
              !fill && 'bg-accent/10 text-accent dark:bg-accent/15',
            )}
            style={fill ? { background: hexAlpha(fill, 0.14), color: fill } : undefined}
          >
            {Icon ? <Icon className="h-5 w-5" strokeWidth={2.1} /> : null}
          </span>
        )}
      </span>

      <div className="relative z-10 mt-4 min-w-0">
        <div className="truncate text-[15px] font-bold leading-6 text-foreground">{label}</div>
        {descKey && (
          <p className="mt-0.5 truncate text-[13px] leading-5 text-foreground-secondary">
            {td(descKey)}
          </p>
        )}
      </div>

      <span className="absolute bottom-3 end-3 z-10 grid h-7 w-7 place-items-center rounded-lg bg-background-tertiary text-foreground-tertiary ring-1 ring-border">
        <ChevronLeft className="h-4 w-4 ltr:-scale-x-100" />
      </span>
    </Link>
  )
}
