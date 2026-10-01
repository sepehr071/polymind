import { cn } from '@/utils/cn'
import { useTheme } from '@/context/ThemeContext'
import logoLight from '@/assets/brand/polymind-logo-light.svg'
import logoDark from '@/assets/brand/polymind-logo-dark.svg'

/**
 * Polymind brand mark. Picks light/dark asset from theme.
 * Wordmark is always Latin (`dir="ltr"`) per product brand rule.
 */
export default function PolymindLogo({
  size = 28,
  showWordmark = false,
  wordmarkClassName,
  className,
  imgClassName,
  alt = 'Polymind AI',
}) {
  const { isDark } = useTheme()
  const src = isDark ? logoDark : logoLight

  return (
    <span
      className={cn('inline-flex items-center gap-2 leading-none', className)}
      dir={showWordmark ? 'ltr' : undefined}
    >
      <img
        src={src}
        alt={showWordmark ? '' : alt}
        width={size}
        height={size}
        draggable={false}
        className={cn('shrink-0 object-contain select-none', imgClassName)}
        style={{ width: size, height: size }}
      />
      {showWordmark ? (
        <span
          className={cn(
            'font-bold tracking-tight text-foreground',
            wordmarkClassName,
          )}
        >
          Polymind AI
        </span>
      ) : null}
    </span>
  )
}
