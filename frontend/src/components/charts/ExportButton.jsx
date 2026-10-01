import { memo } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { exportSeriesCsv, exportBreakdownCsv } from '@/utils/exportCsv'

/**
 * CSV export control for an analytics envelope. Renders a dropdown offering the
 * time-`series` and any present breakdown list (`children` / `by_model`) as
 * separate downloads — each flattened + BOM-prefixed by `utils/exportCsv`.
 *
 * Localized column headers come from the `analytics` namespace
 * (`export.columns.*`); the file name template from `export.fileName`.
 * Disabled when there's nothing to export (no series and no breakdown rows).
 *
 * @param {object} envelope            the P1 analytics envelope
 * @param {string} scope               'holding'|'company'|'team'|'user' — file name slug
 */
function ExportButtonBase({ envelope, scope, disabled = false, className }) {
  const { t } = useTranslation('analytics')

  const series = Array.isArray(envelope?.series) ? envelope.series : []
  const children = Array.isArray(envelope?.breakdown?.children)
    ? envelope.breakdown.children
    : []
  const byModel = Array.isArray(envelope?.breakdown?.by_model)
    ? envelope.breakdown.by_model
    : []

  const win = envelope?.window || {}
  const baseName = t('export.fileName', {
    scope: scope || envelope?.scope || 'usage',
    from: win.from || '',
    to: win.to || '',
  }).replace(/\.csv$/i, '')

  const columnLabels = t('export.columns', { returnObjects: true }) || {}

  const hasAny = series.length > 0 || children.length > 0 || byModel.length > 0
  const breakdownRows = children.length > 0 ? children : byModel

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled || !hasAny}
          className={className}
        >
          <Download className="h-3.5 w-3.5" />
          <span>{t('export.button', 'Export CSV')}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[180px]">
        <DropdownMenuItem
          disabled={series.length === 0}
          onSelect={() =>
            exportSeriesCsv(envelope, `${baseName}-series`, { labels: columnLabels })
          }
        >
          {t('export.series', 'Time series')}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={breakdownRows.length === 0}
          onSelect={() =>
            exportBreakdownCsv(breakdownRows, `${baseName}-breakdown`, {
              labels: columnLabels,
            })
          }
        >
          {t('export.breakdown', 'Breakdown')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export const ExportButton = memo(ExportButtonBase)
export default ExportButton
