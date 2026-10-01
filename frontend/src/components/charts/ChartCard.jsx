import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/**
 * Card shell for every analytics chart: header (title/subtitle + a right-side
 * toolbar slot for range/granularity/export controls), then one of three body
 * states — loading skeleton, empty placeholder, or `children`.
 *
 * The shell owns the three async states so individual charts stay pure: they
 * render `children` only when there IS data. `empty` is decided by the caller
 * (it knows whether `series.length === 0`).
 *
 * @param {React.ReactNode} title
 * @param {React.ReactNode} [subtitle]
 * @param {React.ReactNode} [toolbar]   right-aligned controls in the header
 * @param {boolean} [loading]
 * @param {boolean} [empty]
 * @param {React.ReactNode} [emptyLabel] shown in the empty state
 * @param {number} [height]             body height in px (chart area)
 */
export function ChartCard({
  title,
  subtitle,
  toolbar,
  loading = false,
  empty = false,
  emptyLabel,
  height = 280,
  className,
  bodyClassName,
  children,
}) {
  return (
    <Card className={className}>
      <CardContent className="p-5">
        {(title || toolbar) && (
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              {title && (
                <h3 className="text-sm font-semibold text-foreground">{title}</h3>
              )}
              {subtitle && (
                <p className="mt-0.5 text-xs text-foreground-tertiary">{subtitle}</p>
              )}
            </div>
            {toolbar && <div className="flex flex-shrink-0 items-center gap-2">{toolbar}</div>}
          </div>
        )}

        <div className={cn('relative', bodyClassName)} style={{ height }}>
          {loading ? (
            <Skeleton className="h-full w-full" />
          ) : empty ? (
            <div className="flex h-full items-center justify-center text-sm text-foreground-tertiary">
              {emptyLabel}
            </div>
          ) : (
            children
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default ChartCard
