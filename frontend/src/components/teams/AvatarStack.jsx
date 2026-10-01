import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { fmtNumber } from '@/utils/persianLocale'
import { getInitials } from '@/utils/avatarColor'

const SIZE_CLASSES = {
  sm: 'w-5 h-5 text-[9px]',
  md: 'w-7 h-7 text-[11px]',
  lg: 'w-10 h-10 text-sm',
}

// AvatarStack receives a precomputed `hue` from upstream (not a seed), so it maps
// hue→bg directly. The shared `avatarColors(seed)` helper hashes a seed into a
// hue first; the tone math (`hsl(hue, 40%, 32%)`) is identical, white text.
function avatarBg(hue) {
  if (hue == null) return 'hsl(220, 40%, 32%)'
  return `hsl(${hue}, 40%, 32%)`
}

/**
 * AvatarStack — overlapping circular avatars with overflow chip.
 * @param {Array<{name?: string, hue?: number, avatar_url?: string}>} users
 * @param {number} max
 * @param {'sm' | 'md' | 'lg'} size
 * @param {string} className
 */
export default function AvatarStack({ users = [], max = 4, size = 'sm', className }) {
  const { t } = useTranslation('projects')
  const sizeCls = SIZE_CLASSES[size] || SIZE_CLASSES.sm
  const shown = users.slice(0, max)
  const overflow = users.length - shown.length

  return (
    <div className={cn('inline-flex items-center', className)}>
      {shown.map((u, idx) => {
        const initials = getInitials(u.name)
        return (
          <span
            key={`${u.id || u.name || 'u'}-${idx}`}
            className={cn(
              'inline-flex items-center justify-center rounded-full font-semibold text-white ring-2 ring-background overflow-hidden',
              sizeCls,
              idx > 0 && '-ms-2',
            )}
            style={
              u.avatar_url
                ? undefined
                : { background: avatarBg(u.hue) }
            }
            title={u.name}
          >
            {u.avatar_url ? (
              <img
                src={u.avatar_url}
                alt={u.name || ''}
                className="w-full h-full object-cover"
              />
            ) : (
              initials
            )}
          </span>
        )
      })}
      {overflow > 0 && (
        <span
          className={cn(
            'inline-flex items-center justify-center rounded-full font-semibold ring-2 ring-background bg-background-tertiary text-foreground-secondary -ms-2',
            sizeCls,
          )}
          title={t('avatarStack.moreTitle', { count: overflow })}
        >
          +{fmtNumber(overflow)}
        </span>
      )}
    </div>
  )
}
