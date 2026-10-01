import * as React from 'react'
import { toast as rht } from 'react-hot-toast'
import { Check, AlertTriangle, Loader2, Info, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/utils'
import { SOLID_SURFACE_CLASS } from '@/theme/glass'

// Solid toast surface (readable over any page chrome).
const GLASS_SURFACE = SOLID_SURFACE_CLASS

const VARIANTS = {
  success: {
    disc: 'bg-success/15 text-success ring-1 ring-success/25',
    Icon: Check,
    role: 'status',
  },
  error: {
    disc: 'bg-error/15 text-error ring-1 ring-error/30',
    Icon: AlertTriangle,
    role: 'alert',
  },
  loading: {
    disc: 'bg-accent/15 text-accent ring-1 ring-accent/25',
    Icon: Loader2,
    role: 'status',
    spin: true,
  },
  blank: {
    disc: 'bg-foreground/10 text-foreground-secondary ring-1 ring-border',
    Icon: Info,
    role: 'status',
  },
}

export default function Toast({ t }) {
  const { t: translate } = useTranslation('common')
  const variant = VARIANTS[t.type] || VARIANTS.blank
  const { Icon, disc, role, spin } = variant

  return (
    <div
      role={role}
      data-visible={t.visible}
      className={cn(
        'pointer-events-auto flex items-center gap-3 min-w-[320px] max-w-[440px]',
        'rounded-2xl border border-border bg-background-elevated',
        GLASS_SURFACE,
        'ring-1 ring-black/[0.04] dark:ring-white/[0.04]',
        'px-3.5 py-3',
        'data-[visible=true]:animate-toast-in data-[visible=false]:animate-toast-out',
        'will-change-transform',
      )}
    >
      <span
        className={cn(
          'h-8 w-8 rounded-full grid place-items-center shrink-0',
          disc,
        )}
        aria-hidden="true"
      >
        <Icon
          className={cn('h-[18px] w-[18px]', spin && 'animate-spin')}
          strokeWidth={2.5}
        />
      </span>

      <div className="flex-1 min-w-0 text-[13.5px] font-semibold text-foreground leading-snug break-words">
        {typeof t.message === 'function' ? t.message(t) : t.message}
      </div>

      {t.type !== 'loading' && (
        <button
          type="button"
          onClick={() => rht.dismiss(t.id)}
          aria-label={translate('aria.dismiss')}
          className={cn(
            'shrink-0 grid place-items-center h-7 w-7 rounded-lg',
            'text-foreground-tertiary hover:text-foreground hover:bg-background-tertiary',
            'transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          )}
        >
          <X className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
      )}
    </div>
  )
}
